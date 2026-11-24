"""Blocking change notifications for PM waits. Standard library only.

Windows directory notifications, Linux inotify and macOS/BSD kqueue cover inbox
appends and atomic task replacements. hc's fact stream covers workers that stop
without reporting. Notifications are hints: callers always read the durable
ledger / current state. An occasional reconciliation covers unsupported
filesystems and missed events.
"""
import ctypes
import json
import os
import queue
import select
import subprocess
import sys
import threading
import time

if os.name == "nt":
    from ctypes import wintypes as _wintypes

RECONCILE = 60
FACTS = {"created", "finished", "removed", "status", "lost", "restarted", "labels"}


def replace_task_file(source, target):
    """Briefly retry Windows sharing conflicts with a reader/antivirus.

    File notifications can wake readers while the temp file is still being
    renamed. This is a bounded write retry, not a status-polling loop.
    """
    for attempt in range(6):
        try:
            source.replace(target)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 5:
                raise
            time.sleep(.02 * (attempt + 1))


from .. import config as config_mod  # noqa: E402 - import after replace_task_file so store -> events -> config has no cycle


def relevant_fact(message, terminals=None):
    """Do not turn title animations, output, or heartbeats into status polling.

    terminals: when given, a fact about a terminal outside this set does not wake either (an unfiltered stream
    that follows a few terminals); a fresh snapshot or a gap in the stream always does."""
    if not isinstance(message, dict):
        return False
    if "terminals" in message or message.get("method") == "missed":
        return True
    params = message.get("params") or {}
    return (message.get("method") == "event" and params.get("type") in FACTS
            and (terminals is None or params.get("terminal") in terminals))


def same_status(message, states):
    """A status fact that leaves a terminal's state as it was (an agent's own word on what it is doing, its
    progress) is no news for a wait; states: {terminal: (reported, state)} as last seen on this stream. It is fed
    every status fact, of terminals followed or not, so that it never holds a state a terminal has since left."""
    params = (message.get("params") or {}) if isinstance(message, dict) else {}
    if params.get("type") != "status" or not isinstance(params.get("data"), dict):
        return False
    data = params["data"]
    status = data.get("status") if isinstance(data.get("status"), dict) else {}
    now = (bool(data.get("reported")), status.get("state"))
    same = states.get(params.get("terminal")) == now
    states[params.get("terminal")] = now
    return same


if hasattr(select, "kqueue"):
    # O_EVTONLY (Python 3.10+ names it): watch without keeping the volume busy.
    EVTONLY = getattr(os, "O_EVTONLY", 0x8000) if sys.platform == "darwin" else os.O_RDONLY
    GONE = select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME | select.KQ_NOTE_REVOKE
    VNODE = select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_ATTRIB | GONE


def mark(path):
    """What tells one state of a file from the next: (inode, size, mtime_ns), or None while it does not exist."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_ino, st.st_size, st.st_mtime_ns


class DirectoryEvents:
    """Call changed() from a thread of its own when something in one of paths changes.

    files: the files in those folders that matter; without them, any change in a folder wakes.
    Windows and Linux report every change in a watched folder: an inbox folder holds every PM's
    log, offset and snapshot, and tasks/ every task. There a folder event wakes only when one of
    files is not as it was (mark: inode, size, mtime), so a watcher wakes for its own PM's log
    and a wait for its own task. (Not by the names in the events: Windows' change notifications
    carry none, and the mark also covers a replaced file and an overflowed inotify queue.)
    kqueue (macOS) sees only a folder's entries being added, removed or renamed, not an append
    to a file that stays (the inbox log), so it also watches each of files itself and watches
    it again when the folder shows it created or replaced; there a folder change wakes only
    when one of files appeared, vanished or was replaced.
    """
    def __init__(self, paths, changed, files=()):
        self.changed = changed
        self.active = False
        self.thread = None
        self.handles = []
        self.fd = None
        self.pipe = None
        self.kq = None
        self.dirs = {}
        self.watched = {}
        self.files = [str(f) for f in files]
        self.marks = {f: mark(f) for f in self.files}
        if os.name == "nt":
            w = _wintypes
            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
            for name, args, result in (
                ("FindFirstChangeNotificationW", [w.LPCWSTR, w.BOOL, w.DWORD], w.HANDLE),
                ("FindNextChangeNotification", [w.HANDLE], w.BOOL),
                ("FindCloseChangeNotification", [w.HANDLE], w.BOOL),
                ("CreateEventW", [ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE),
                ("SetEvent", [w.HANDLE], w.BOOL),
                ("CloseHandle", [w.HANDLE], w.BOOL),
                ("WaitForMultipleObjects", [w.DWORD, ctypes.POINTER(w.HANDLE), w.BOOL, w.DWORD], w.DWORD),
            ):
                fn = getattr(self.api, name)
                fn.argtypes, fn.restype = args, result
            self.stop_handle = self.api.CreateEventW(None, True, False, None)
            if not self.stop_handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                for path in paths:
                    # FILE_NAME | DIR_NAME | SIZE | LAST_WRITE
                    h = self.api.FindFirstChangeNotificationW(str(path), False, 0x1B)
                    if h == ctypes.c_void_p(-1).value:
                        raise ctypes.WinError(ctypes.get_last_error())
                    self.handles.append(h)
                self.array = (w.HANDLE * (len(self.handles) + 1))(self.stop_handle, *self.handles)
            except BaseException:
                self.close()
                raise
            target = self._windows
        elif sys.platform.startswith("linux"):
            api = ctypes.CDLL(None, use_errno=True)
            api.inotify_init1.argtypes, api.inotify_init1.restype = [ctypes.c_int], ctypes.c_int
            api.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
            api.inotify_add_watch.restype = ctypes.c_int
            self.fd = api.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
            if self.fd < 0:
                self.fd = None
                raise OSError(ctypes.get_errno(), "inotify_init1")
            try:
                for path in paths:
                    # MODIFY | CLOSE_WRITE | MOVED_FROM/TO | CREATE/DELETE | DELETE/MOVE_SELF
                    if api.inotify_add_watch(self.fd, os.fsencode(path), 0xFCA) < 0:
                        raise OSError(ctypes.get_errno(), "inotify_add_watch")
                self.pipe = os.pipe()
            except BaseException:
                self.close()
                raise
            target = self._linux
        elif hasattr(select, "kqueue"):
            try:
                self.kq = select.kqueue()
                self.pipe = os.pipe()
                self.kq.control([select.kevent(self.pipe[0], select.KQ_FILTER_READ, select.KQ_EV_ADD)], 0)
                for path in paths:
                    fd = os.open(str(path), EVTONLY)
                    self.dirs[fd] = str(path)
                    self._watch(fd)
                self._arm()
            except BaseException:
                self.close()
                raise
            target = self._kqueue
        else:
            raise OSError("native PM file notifications are unavailable on this platform")
        self.active = True
        self.thread = threading.Thread(target=target, daemon=True, name="pm-files")
        self.thread.start()

    def _windows(self):
        try:
            while True:
                index = self.api.WaitForMultipleObjects(len(self.array), self.array, False, 0xFFFFFFFF)
                if index == 0:
                    return
                if not 1 <= index <= len(self.handles):
                    raise OSError("directory notification wait failed")
                if not self.api.FindNextChangeNotification(self.handles[index - 1]):
                    raise ctypes.WinError(ctypes.get_last_error())
                if self.moved():
                    self.changed()
        except OSError:
            self.active = False
            self.changed()

    def _linux(self):
        try:
            while True:
                ready, _, _ = select.select([self.fd, self.pipe[0]], [], [])
                if self.pipe[0] in ready:
                    return
                if self.fd in ready:
                    os.read(self.fd, 65536)
                    # Overflow included: the files' marks, not the events, say what changed.
                    if self.moved():
                        self.changed()
        except OSError:
            self.active = False
            self.changed()

    def moved(self):
        """After a folder event (Windows, Linux): True when one of files is not as it was. Without files, always."""
        if not self.files:
            return True
        now = {f: mark(f) for f in self.files}
        moved, self.marks = now != self.marks, now
        return moved

    def _watch(self, fd):
        self.kq.control([select.kevent(fd, select.KQ_FILTER_VNODE,
                                       select.KQ_EV_ADD | select.KQ_EV_CLEAR, VNODE)], 0)

    def _arm(self):
        """Watch each of files as it is now. True when one appeared, vanished or was replaced."""
        moved = False
        for path in self.files:
            try:
                ino = os.stat(path).st_ino
            except OSError:
                ino = None
            fd, was = self.watched.get(path, (None, None))
            if ino == was:
                continue
            moved = True
            if fd is not None:
                os.close(fd)  # closing a descriptor drops its kevent
                del self.watched[path]
            if ino is None:
                continue
            try:
                fd = os.open(path, EVTONLY)
            except OSError:
                continue  # gone again: the folder's next event arms it
            self._watch(fd)
            self.watched[path] = (fd, os.fstat(fd).st_ino)
        return moved

    def _kqueue(self):
        try:
            while True:
                events = self.kq.control(None, 64, None)
                if any(e.ident == self.pipe[0] for e in events):
                    return
                folder = [e for e in events if e.ident in self.dirs]
                if any(e.fflags & GONE for e in folder):
                    raise OSError("a watched folder was removed or moved")
                moved = self._arm() if folder or any(e.fflags & GONE for e in events) else False
                if moved or (folder and not self.files) or any(e.ident not in self.dirs for e in events):
                    self.changed()
        except OSError:
            self.active = False
            self.changed()

    def close(self):
        if os.name == "nt" and getattr(self, "stop_handle", None):
            self.api.SetEvent(self.stop_handle)
        elif self.pipe:
            os.write(self.pipe[1], b"x")
        if self.thread:
            self.thread.join()
        for fd in [*self.dirs, *(fd for fd, _ in self.watched.values())]:
            os.close(fd)
        self.dirs, self.watched = {}, {}
        if self.kq is not None:
            self.kq.close()
            self.kq = None
        if os.name == "nt" and getattr(self, "stop_handle", None):
            for h in self.handles:
                self.api.FindCloseChangeNotification(h)
            self.api.CloseHandle(self.stop_handle)
            self.stop_handle = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.pipe:
            for fd in self.pipe:
                os.close(fd)
            self.pipe = None
        self.active = False


class ChangeWaiter:
    """Subscribe before the first read, then block; coalesce hints, not reports.

    The hc reader reconnects with bounded backoff and every fresh snapshot wakes
    the caller for reconciliation. It never executes data received from events.
    """
    def __init__(self, paths, hc_args=None, files=(), hc="hc", terminals=None, folders=(), *, warn=None):
        """files: the files in paths that matter (see DirectoryEvents); hc_args: `hc events` filters, or None;
        hc: the herdr-core CLI to run (pm.py passes config.json's "hc"); terminals: only facts about these
        terminals wake (relevant_fact), a set the caller may replace at any time (`terminals = {...}`);
        folders: more folders where any change wakes (a DirectoryEvents of their own, without files)."""
        self.terminals = terminals
        self.folders = None
        self.queue = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.process_lock = threading.Lock()
        self.process = None
        self.thread = None
        self.files = None
        self.hc_args, self.hc = hc_args, hc
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)
        try:
            self.files = DirectoryEvents(paths, self.wake, files)
        except (OSError, AttributeError) as error:
            msg = f"PM file events unavailable ({error}); reconciling every {RECONCILE}s."
            if warn is not None:
                warn(msg)
            else:
                sys.stderr.write(msg + "\n")
        if folders:
            try:
                for path in folders:
                    path.mkdir(parents=True, exist_ok=True)
                self.folders = DirectoryEvents(folders, self.wake)
            except (OSError, AttributeError):
                self.folders = None  # the reconciliation covers them
        if hc_args is not None:
            self.thread = threading.Thread(target=self._facts, daemon=True, name="pm-hc-events")
            self.thread.start()

    def follow(self, hc_args):
        """Follow other terminals' facts from now on (a task's worker was replaced).

        The running stream is ended; the reader reconnects with these filters and
        its fresh snapshot wakes the caller."""
        with self.process_lock:
            if hc_args == self.hc_args or self.stop.is_set():
                return
            self.hc_args = hc_args
            process = self.process
        if self.thread is None or not self.thread.is_alive():
            # None before, or a reader that ended when the filters went to None.
            self.thread = threading.Thread(target=self._facts, daemon=True, name="pm-hc-events")
            self.thread.start()
        elif process is not None and process.poll() is None:
            process.terminate()

    def wake(self):
        try:
            self.queue.put_nowait(True)
        except queue.Full:
            pass

    def hint(self, message, states):
        """Whether a message of the fact stream wakes the caller. states (same_status) follows every terminal, and
        starts again at a snapshot or a gap in the stream, where states may have changed unseen."""
        if isinstance(message, dict) and ("terminals" in message or message.get("method") == "missed"):
            states.clear()
        params = (message.get("params") or {}) if isinstance(message, dict) else {}
        if params.get("type") == "removed":
            states.pop(params.get("terminal"), None)
        same = same_status(message, states)
        return relevant_fact(message, self.terminals) and not same

    def _facts(self):
        delay, states = 1, {}
        while not self.stop.is_set():
            process = None
            states.clear()  # a new stream: what the last one said may be out of date
            try:
                with self.process_lock:
                    if self.stop.is_set() or self.hc_args is None:
                        return
                    process = subprocess.Popen(
                        [self.hc, "events", "--json", *self.hc_args],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        encoding="utf-8", errors="replace",
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
                    self.process = process
                for line in process.stdout:
                    if self.stop.is_set():
                        return
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(message, dict) and message.get("method") == "heartbeat":
                        delay = 1
                    if self.hint(message, states):
                        self.wake()
            except OSError:
                pass
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    process.stdout.close()
                    with self.process_lock:
                        self.process = None
            # No repeated task reads on failed reconnects: the 60s reconciliation
            # checks state; a successfully reconnected snapshot wakes it at once.
            if self.stop.wait(delay):
                return
            delay = min(delay * 2, 30)

    def wait(self, timeout):
        try:
            self.queue.get(timeout=max(0, min(timeout, RECONCILE)))
            return True
        except queue.Empty:
            return False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stop.set()
        try:
            with self.process_lock:
                process = self.process
            if process is not None and process.poll() is None:
                process.terminate()
                # The reader may be blocked on stdout, so it cannot reach its
                # own finally/kill fallback until we stop the process here.
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            if self.thread:
                self.thread.join(timeout=4)
        finally:
            if self.files:
                self.files.close()
            if self.folders:
                self.folders.close()


WAIT_POLL = 5  # one-shot grace before declaring a stopped worker unreported


class TimedLooks:
    """A ChangeWaiter's stand-in when ChangeWaiter is unavailable: every wait may have seen a change, after WAIT_POLL s."""
    def __init__(self, *_, **__):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def wait(self, timeout):
        time.sleep(max(0, min(timeout, WAIT_POLL)))
        return True


def change_waiter(paths, hc_args=None, files=(), terminals=None, folders=()):
    """ChangeWaiter: file notifications on paths (files: the ones there that matter) and hc events
    (terminals: only facts about these wake, a set the caller replaces as it goes); folders: any change in these
    wakes too."""
    if ChangeWaiter is None:
        return TimedLooks()
    more = {**({"terminals": terminals} if terminals is not None else {}), **({"folders": folders} if folders else {})}
    return ChangeWaiter(paths, hc_args, files=files, hc=str(config_mod.config().get("hc") or "hc"), **more)
