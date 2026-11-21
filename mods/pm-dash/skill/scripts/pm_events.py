"""Blocking change notifications for PM waits. Standard library only.

Windows directory notifications and Linux inotify cover inbox appends and atomic
task replacements. hc's fact stream covers workers that stop without reporting.
Notifications are hints: callers always read the durable ledger / current state.
An occasional reconciliation covers unsupported filesystems and missed events.
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


def relevant_fact(message):
    """Do not turn title animations, output, or heartbeats into status polling."""
    if not isinstance(message, dict):
        return False
    return ("terminals" in message or message.get("method") == "missed"
            or (message.get("method") == "event"
                and (message.get("params") or {}).get("type") in FACTS))


class DirectoryEvents:
    def __init__(self, paths, changed):
        self.changed = changed
        self.active = False
        self.thread = None
        self.handles = []
        self.fd = None
        self.pipe = None
        if os.name == "nt":
            from ctypes import wintypes as w
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
                    self.changed()  # Includes overflow: reconcile, do not trust individual events.
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
    def __init__(self, paths, hc_args=None):
        self.queue = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.process_lock = threading.Lock()
        self.process = None
        self.thread = None
        self.files = None
        self.hc_args = hc_args
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)
        try:
            self.files = DirectoryEvents(paths, self.wake)
        except (OSError, AttributeError) as error:
            print(f"PM file events unavailable ({error}); reconciling every {RECONCILE}s.", file=sys.stderr)
        if hc_args is not None:
            self.thread = threading.Thread(target=self._facts, daemon=True, name="pm-hc-events")
            self.thread.start()

    def wake(self):
        try:
            self.queue.put_nowait(True)
        except queue.Full:
            pass

    def _facts(self):
        delay = 1
        while not self.stop.is_set():
            process = None
            try:
                with self.process_lock:
                    if self.stop.is_set():
                        return
                    process = subprocess.Popen(
                        ["hc", "events", "--json", *self.hc_args],
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
                    if relevant_fact(message):
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
