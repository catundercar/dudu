"""Minimal public facade behind `import pm` (docs/design/pm-py-pass-two.md, section 4.4).

scripts/pm.py, when imported rather than run as a script, calls `install()` on itself to expose the small
static surface needed by external callers and `tests/test_install.py` (`main`, `build_parser`, `Context`,
`Home`, `WINDOWS`, `python_command`). The CLI runs `pmlib.cli.main()` directly without importing this module.
"""
from . import cli, context, home, osutil


def install(facade):
    """Populate `facade` (`pm`) with the minimal static public surface."""
    facade.main = cli.main
    facade.build_parser = cli.build_parser
    facade.Context = context.Context
    facade.Home = home.Home
    facade.WINDOWS = osutil.WINDOWS
    facade.python_command = lambda: osutil.python_command(windows=facade.WINDOWS)
    return facade
