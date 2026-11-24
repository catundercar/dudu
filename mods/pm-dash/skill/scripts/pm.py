#!/usr/bin/env python3
"""Task ledger and herdr helpers for the pm skill: the entry point.

The code is the pmlib package beside this file. Run as a script, this file prepares the process and calls pmlib's
main(). Imported (`import pm`, as the tests and older callers do), it becomes a module whose attributes are pmlib's
(pmlib/compat.py). Both happen before anything in pmlib is imported, because pmlib works out the ledger home's paths
when it is imported.
"""
import importlib
import os
import subprocess
import sys
from pathlib import Path


def _prepare():
    # Windows: files, pipes and child output are read and written in the locale's code page unless Python runs in
    # UTF-8 mode, and the ledger and `state` hold Chinese text. Run again in UTF-8 mode (the child inherits stdin,
    # stdout and stderr, so hooks and the desktop app see one process).
    if os.name == "nt" and not sys.flags.utf8_mode:
        sys.exit(subprocess.run([sys.executable, "-X", "utf8", *sys.argv]).returncode)
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
