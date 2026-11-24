"""Tests for `pmlib/cli.py`: command dispatch table, call-time patching of `pm.cmd_*`, and error-to-exit mapping."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent

CHECK_DISPATCH = textwrap.dedent("""
    import argparse
    import contextlib
    import io
    import sys
    from unittest import mock

    sys.path.insert(0, sys.argv[1])
    import pm
    from pmlib import cli

    parser = cli.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert set(cli.COMMANDS) == set(sub.choices), (set(cli.COMMANDS) ^ set(sub.choices))
    assert len(cli.COMMANDS) == 59, len(cli.COMMANDS)
    for name, (mod, fn_name) in cli.COMMANDS.items():
        fn = getattr(mod, fn_name)
        assert callable(fn), (name, mod, fn_name)

    # Call-time lookup: patching the command module handler reaches pm.main() and restores on exit.
    for cmd_name, argv in (
        ("status", ["pm.py", "status"]),
        ("new", ["pm.py", "new", "hello"]),
        ("hook-mirror", ["pm.py", "hook-mirror"]),
    ):
        mod, attr_name = cli.COMMANDS[cmd_name]
        orig = getattr(mod, attr_name)
        seen = []
        with mock.patch.object(mod, attr_name, side_effect=lambda a, ctx=None, _seen=seen: _seen.append((a.cmd, ctx is not None))), \\
                mock.patch.object(sys, "argv", argv):
            pm.main()
        assert seen == [(cmd_name, True)], (cmd_name, seen)
        assert getattr(mod, attr_name) is orig, (cmd_name, getattr(mod, attr_name), orig)

    # Error-to-exit-code mapping: IdentityError -> 2, StoreError -> 1.
    from pmlib.errors import IdentityError, StoreError
    status_mod, status_attr = cli.COMMANDS["status"]

    def raise_identity(_a, ctx=None):
        raise IdentityError("wrong pane")

    def raise_store(_a, ctx=None):
        raise StoreError("corrupt ledger")

    for err_fn, expected_code, expected_msg in (
        (raise_identity, 2, "PM identity check failed: wrong pane"),
        (raise_store, 1, "ledger store error: corrupt ledger"),
    ):
        err = io.StringIO()
        with mock.patch.object(status_mod, status_attr, side_effect=err_fn), \\
                mock.patch.object(sys, "argv", ["pm.py", "status"]), \\
                contextlib.redirect_stderr(err):
            try:
                pm.main()
            except SystemExit as exc:
                assert exc.code == expected_code, (exc.code, expected_code)
            else:
                raise AssertionError("expected SystemExit")
        assert err.getvalue().strip() == expected_msg, err.getvalue()

    print("ok")
""")


CHECK_REGISTRATIONS_PM = textwrap.dedent("""
    import sys

    sys.path.insert(0, sys.argv[1])
    import pm
    from pmlib import context
    from pmlib.events import deliver

    ctx = context.Context.from_env()
    assert len(ctx.after_save) == 2, len(ctx.after_save)
    assert ctx.seat_alive is not None
    assert ctx.caller_projects is not None
    assert [w.name for w in ctx.deliver_watchers] == ["helpers", "dependencies", "agy-transcript"], ctx.deliver_watchers
    assert len(ctx.deliver_holds) == 1, ctx.deliver_holds
    assert not hasattr(deliver, "_WATCHERS") and not hasattr(deliver, "_HOLDS")
    assert pm.Context is context.Context
    print("ok")
""")


CHECK_CLI_DIRECT_IMPORT = textwrap.dedent("""
    import pathlib
    import sys

    sys.path.insert(0, sys.argv[1])
    import pmlib.cli  # CLI startup path without importing `pm` or `compat`
    from pmlib import context
    from pmlib.events import deliver

    ctx = context.Context.from_env()
    assert len(ctx.after_save) == 2, len(ctx.after_save)
    assert ctx.seat_alive is not None
    assert ctx.caller_projects is not None
    assert [w.name for w in ctx.deliver_watchers] == ["helpers", "dependencies", "agy-transcript"], ctx.deliver_watchers
    assert len(ctx.deliver_holds) == 1, ctx.deliver_holds
    assert not hasattr(deliver, "_WATCHERS") and not hasattr(deliver, "_HOLDS")

    # Every pmlib module except compat must be eagerly loaded on startup.
    pmlib_dir = pathlib.Path(sys.argv[1]) / "pmlib"
    expected = set()
    for p in pmlib_dir.rglob("*.py"):
        if "__pycache__" in p.parts or p.name.startswith("test_"):
            continue
        rel = p.relative_to(pathlib.Path(sys.argv[1])).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        name = ".".join(parts)
        if name != "pmlib.compat":
            expected.add(name)
    loaded = {k for k in sys.modules if k == "pmlib" or k.startswith("pmlib.")}
    missing = sorted(expected - loaded)
    assert not missing, f"modules not eagerly imported by pmlib.cli: {missing}"
    assert "pmlib.compat" not in loaded
    print("ok")
""")


def child_env(home):
    env = {k: v for k, v in os.environ.items() if k not in ("HERDR_PANE_ID", "HC_TERMINAL_ID", "HERDR_WORKSPACE_ID",
                                                          "HERDR_ENV")}
    env.update(PM_HOME=str(home), PM_NO_DISCORD="1", PYTHONDONTWRITEBYTECODE="1")
    return env


class CliTest(unittest.TestCase):
    def run_child(self, code):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir(parents=True)
            out = subprocess.run([sys.executable, "-c", code, str(SCRIPTS)],
                                 env=child_env(home), capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertEqual(out.stdout.strip().splitlines()[-1:], ["ok"], out.stdout + out.stderr)

    def test_dispatch_table_call_time_patch_and_error_exit_codes(self):
        self.run_child(CHECK_DISPATCH)

    def test_startup_registrations_active_and_patchable_after_import_pm(self):
        self.run_child(CHECK_REGISTRATIONS_PM)

    def test_startup_registrations_and_eager_imports_on_direct_cli_import(self):
        self.run_child(CHECK_CLI_DIRECT_IMPORT)


if __name__ == "__main__":
    unittest.main()
