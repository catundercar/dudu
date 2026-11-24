"""System tools that know nothing of the ledger: the platform, command lines, process groups, small text helpers.
Standard library only (layer 0)."""
import contextlib
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path, PurePath, PureWindowsPath

# The UTF-8 re-run on Windows and `pm.py --home <dir>` happen in the launcher (scripts/pm.py), before this is imported.
WINDOWS = os.name == "nt"


def python_command(windows=None):
    """How a command line names a Python 3 that runs this script: python3 on macOS and Linux; on Windows the
    py launcher, else this interpreter's path (python3 there may be the Microsoft Store stub). setup.py has a copy."""
    is_win = WINDOWS if windows is None else windows
    if not is_win:
        return "python3"
    if shutil.which("py"):
        return "py -3"
    exe = PureWindowsPath(sys.executable).as_posix()
    return f'"{exe}"' if " " in exe else exe


def shell_quote(arg, powershell=False):
    """One argument of a command line that a person or an agent runs on this machine. macOS and Linux: shlex. Windows
    has no quoting that cmd, PowerShell and Git Bash all read the same; double quotes as subprocess.list2cmdline
    writes them come closest, and a path is written with forward slashes (as setup.py writes the hooks), so it
    reads the same in all three. powershell: a line for PowerShell, whose double quotes take ` escapes."""
    if isinstance(arg, PurePath):
        arg = PureWindowsPath(arg).as_posix() if WINDOWS else str(arg)
    if not WINDOWS:
        return shlex.quote(arg)
    if powershell:
        if arg and not re.search(r"[\s\"'`$&|;,<>(){}@#]", arg):
            return arg
        return '"' + re.sub(r'([`"$])', r"`\1", arg) + '"'
    if arg and not re.search(r'[\s"&|<>^()]', arg):
        return arg
    # list2cmdline's rules, with cmd's metacharacters quoted too: backslashes before a quote and at the end double.
    arg = re.sub(r'(\\*)"', lambda m: m.group(1) * 2 + '\\"', arg)
    return '"' + re.sub(r"(\\+)$", r"\1\1", arg) + '"'


def shell_join(args, powershell=False):
    """A whole command line from its arguments, quoted by shell_quote. PowerShell runs a program whose name is in
    quotes only after `&`."""
    line = " ".join(shell_quote(arg, powershell) for arg in args)
    return f"& {line}" if WINDOWS and powershell and line.startswith('"') else line


def file_text(path):
    """A file's text as one argument, in a "send it by hand" line. It reads the same in Git Bash and PowerShell
    (PowerShell joins the lines with spaces); cmd has no way to say it."""
    return f'"$(cat {shell_quote(path)})"'



def own_group(background=False):
    """Popen arguments that start a child in a process group of its own, so stop_group ends it with what it started
    and it outlives the session that started it. POSIX: a session of its own. Windows has no setsid: a new process
    group, and for a background child also a console of its own without a window, so closing the starting
    console does not end it."""
    if not WINDOWS:
        return {"start_new_session": True}
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    if background:
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return {"creationflags": flags}



def process_name(pid):
    """The command name of a process (POSIX), or ""."""
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        pass
    try:
        out = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True, timeout=10)
        return Path(out.stdout.strip()).name if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""



def unfailing(step, *args, **kwargs):
    """Run a step of a hook that must never fail the session it runs in: a broken task file or an hc that does
    not answer costs that step, not the turn."""
    try:
        step(*args, **kwargs)
    except Exception:  # noqa: BLE001
        pass



def stop_group(proc):
    """Kill a check and everything it started (it runs in a process group of its own, see own_group)."""
    if proc and proc.poll() is None:
        if WINDOWS:  # no killpg or SIGKILL there: taskkill ends the shell's whole process tree
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if proc.poll() is None:
                with contextlib.suppress(OSError):
                    proc.kill()
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        proc.wait()



def clip(text, width):
    return text if not width or len(text) <= width else text[:width] + " …"


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40].strip("-")



def _is_zombie(pid):
    """Whether a POSIX process is a zombie (exited, awaiting waitpid) so pid_alive/stop_pid_group do not spin."""
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text()
        rparen = stat_text.rfind(")")
        if rparen >= 0:
            fields = stat_text[rparen + 1:].split()
            return bool(fields) and fields[0] == "Z"
    except OSError:
        pass
    try:
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            st = out.stdout.strip()
            return not st or st.startswith("Z")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


def pid_alive(pid):
    if not pid or pid <= 0:
        return False
    if WINDOWS:
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, errors="replace", timeout=10)
            return str(pid) in (out.stdout or "")
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        os.kill(pid, 0)
        return not _is_zombie(pid)
    except ProcessLookupError:
        return False
    except OSError:
        return True


def stop_pid_group(pid, grace=3.0):
    """Terminate the process group of `pid` (never the enclosing seat terminal), escalating to SIGKILL after `grace`."""
    if not pid or pid <= 0:
        return
    if WINDOWS:
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=15)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


def stale_lock(lock):
    """A reattach lock whose holder is gone: its process has ended, or it is older than five minutes. One
    without a pid yet is being written; it is stale only after a few seconds."""
    try:
        text, age = lock.read_text().split(), time.time() - lock.stat().st_mtime
    except OSError:
        return False
    if age > 300:
        return True
    if not text or not text[0].isdigit():
        return age > 5
    if WINDOWS:  # signal 0 there is CTRL_C_EVENT, sent to a process group: use tasklist via pid_alive
        return not pid_alive(int(text[0]))
    try:
        os.kill(int(text[0]), 0)
    except ProcessLookupError:
        return True
    except OSError:
        pass  # alive, another user's
    return False


class Options:
    """A command's options as one value: the class lists each name with its default (`name: type = default`, never a
    mutable default), the instance holds what was given. Unlike a dataclass it generates no code when the class is
    defined, which keeps the eagerly imported command modules cheap at startup; `required` names must be given."""

    required: tuple = ()

    def __init__(self, **given):
        names = self._names()
        for name in self.required:
            if name not in given:
                raise TypeError(f"{type(self).__name__} needs {name}")
        for name, value in given.items():
            if name not in names:
                raise TypeError(f"{type(self).__name__} has no option {name}")
            setattr(self, name, value)

    @classmethod
    def _names(cls):
        names = set()
        for klass in cls.__mro__:
            names.update(getattr(klass, "__annotations__", {}))
        return names - {"required"}

    def __repr__(self):
        shown = ", ".join(f"{n}={getattr(self, n, None)!r}" for n in sorted(self._names()))
        return f"{type(self).__name__}({shown})"
