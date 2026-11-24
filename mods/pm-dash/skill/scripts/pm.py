#!/usr/bin/env python3
"""Task ledger and herdr helpers for the pm skill: the entry point.

The code is the pmlib package beside this file. Run as a script, this file prepares the process and calls pmlib's
main(). Imported (`import pm`, as the tests and older callers do), it becomes a module whose attributes are pmlib's
(pmlib/compat.py). Both happen before anything in pmlib is imported, because pmlib works out the ledger home's paths
when it is imported.
"""
import contextlib
import importlib
import os
import signal
import subprocess
import sys
from pathlib import Path

try:
    import ctypes
    from ctypes import wintypes as _wintypes
except ImportError:
    ctypes = None
    _wintypes = None


def _win_kill_job():
    """Create a Windows Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE so a re-exec'd child never outlives us."""
    if os.name != "nt" or ctypes is None or _wintypes is None:
        return None
    try:
        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", _wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", _wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", _wintypes.DWORD),
                ("SchedulingClass", _wintypes.DWORD),
            ]

        class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, _wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = _wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [_wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, _wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = _wintypes.BOOL
        kernel32.CloseHandle.argtypes = [_wintypes.HANDLE]
        kernel32.CloseHandle.restype = _wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            return None
        return int(job)
    except Exception:
        return None


def _reexec_utf8_windows():
    """Re-run pm.py in UTF-8 mode on Windows, keeping the child in a kill-on-close Job Object and staying alive on
    SIGBREAK/SIGINT/SIGTERM until the child finishes its own cleanup."""
    job = _win_kill_job()
    proc = subprocess.Popen([sys.executable, "-X", "utf8", *sys.argv])
    if job and ctypes is not None and _wintypes is not None:
        with contextlib.suppress(Exception):
            kernel32 = ctypes.windll.kernel32
            kernel32.AssignProcessToJobObject.argtypes = [_wintypes.HANDLE, _wintypes.HANDLE]
            kernel32.AssignProcessToJobObject.restype = _wintypes.BOOL
            handle = getattr(proc, "_handle", None)
            if handle:
                kernel32.AssignProcessToJobObject(_wintypes.HANDLE(job), _wintypes.HANDLE(int(handle)))

    # The child shares our console process group, so CTRL_BREAK_EVENT / CTRL_C_EVENT reach it directly; do not exit
    # early before it finishes cleanup (e.g. `pm.py seat` unlinking next-session.json and seat.json).
    def _wait_child(_signum, _frame):
        pass

    def _on_term(_signum, _frame):
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.terminate()

    for sig_name, handler in (("SIGINT", signal.SIG_IGN), ("SIGBREAK", _wait_child), ("SIGTERM", _on_term)):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            with contextlib.suppress(OSError, ValueError):
                signal.signal(sig, handler)

    try:
        while proc.poll() is None:
            try:
                proc.wait()
            except KeyboardInterrupt:
                pass
        rc = proc.returncode
    finally:
        if job and ctypes is not None and _wintypes is not None:
            with contextlib.suppress(Exception):
                ctypes.windll.kernel32.CloseHandle(_wintypes.HANDLE(job))
    sys.exit(rc)


def _prepare():
    # Windows: files, pipes and child output are read and written in the locale's code page unless Python runs in
    # UTF-8 mode, and the ledger and `state` hold Chinese text. Run again in UTF-8 mode (the child inherits stdin,
    # stdout and stderr, so hooks and the desktop app see one process).
    if os.name == "nt" and not sys.flags.utf8_mode:
        _reexec_utf8_windows()
    # `pm.py --home <dir> <command>`: the ledger home as an option. pm_command writes it so on Windows, where cmd,
    # PowerShell and Git Bash each set an environment variable their own way; it applies to the processes this one
    # starts.
    if sys.argv[1:2] == ["--home"] and len(sys.argv) > 2:
        os.environ["PM_HOME"] = sys.argv[2]
        del sys.argv[1:3]


def _pmlib(name):
    """Import pmlib's module `name`; exit with the reason when pmlib is missing or incomplete (pm.py copied alone,
    or an install halfway through copying the folder)."""
    here = Path(__file__).resolve()
    if str(here.parent) not in sys.path:
        sys.path.insert(0, str(here.parent))
    try:
        return importlib.import_module(name)
    except ImportError as missing:
        if not (missing.name or "").startswith("pmlib"):
            raise
        sys.exit(f"pm.py cannot run without the pmlib folder beside {here} ({missing.name} is missing or "
                 "incomplete): install or copy the whole skills/pm folder, not pm.py alone")


if __name__ == "__main__":
    _prepare()
    _pmlib("pmlib.cli").main()
else:
    _pmlib("pmlib.cli")
    _pmlib("pmlib.compat").install(sys.modules[__name__])
