"""Unit and integration tests for `tests/patch_audit.py` (Pass-2 patch contract safety net)."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import patch_audit  # noqa: E402


def _make_toy_scripts(root: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return root


class PatchAuditUnitTests(unittest.TestCase):
    def _run_toy(self, files: dict[str, str]) -> patch_audit.AuditReport:
        with tempfile.TemporaryDirectory() as tmp:
            scripts = _make_toy_scripts(Path(tmp), files)
            return patch_audit.audit(scripts)

    def test_catches_unexpected_kwarg_like_screen_of_host(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/terminals/__init__.py": "",
            "pmlib/terminals/screen.py": """
                def screen_of(term, *, host=None):
                    return ""

                def screen_line(term, *, host=None):
                    return screen_of(term, host=host)
            """,
            "test_pm.py": """
                from unittest import mock
                import pm

                def test_fast():
                    with mock.patch.object(pm, "screen_of", side_effect=lambda t: "ok"):
                        pass
            """,
        })
        codes = [(f.code, f.attr) for f in report.errors]
        self.assertEqual(codes, [("SIG_MISMATCH", "screen_of")])
        self.assertIn("unexpected keyword argument(s): host", report.errors[0].message)
        self.assertEqual(report.errors[0].call_loc, "pmlib/terminals/screen.py:5")
        self.assertEqual(report.errors[0].patch_loc, "test_pm.py:5")

    def test_catches_positional_arity_and_missing_required_args(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/foo.py": """
                def alpha(a, b, c=1):
                    return a + b + c

                def beta(x):
                    return x

                def caller():
                    alpha(1, 2, 3)
                    beta(1)
            """,
            "test_pm.py": """
                import pm

                def fake_alpha(a, b=0):
                    return a

                def fake_beta(x, y):
                    return x + y

                def test_it():
                    pm.alpha = fake_alpha
                    pm.beta = fake_beta
            """,
        })
        by_attr = {f.attr: f for f in report.errors}
        self.assertIn("alpha", by_attr)
        self.assertIn("too many positional args", by_attr["alpha"].message)
        self.assertIn("beta", by_attr)
        self.assertIn("missing required argument(s): y", by_attr["beta"].message)

    def test_magic_mock_and_non_callable_side_effect_accept_anything(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/foo.py": """
                def work(a, b, *, flag=False):
                    return a

                def caller():
                    return work(1, 2, flag=True)
            """,
            "test_pm.py": """
                from unittest import mock
                import pm

                def test_mocks():
                    with mock.patch.object(pm, "work", return_value="x"):
                        pass
                    with mock.patch.object(pm, "work", side_effect=[1, 2]):
                        pass
                    with mock.patch.object(pm, "work", side_effect=OSError("boom")):
                        pass
                    pm.work = mock.MagicMock(return_value=1)
            """,
        })
        self.assertEqual(report.errors, [])

    def test_catches_forwarded_port_calls_via_legacy_wiring(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/host.py": """
                class HcHost:
                    def __init__(self, *, runner=None):
                        self._runner = runner

                    def call(self, *args, errors=False, timeout=60):
                        if self._runner is not None:
                            return self._runner(*args, errors=errors, timeout=timeout)
                        return None

                    @classmethod
                    def legacy(cls):
                        return cls(runner=lambda *args, **kw: hc(*args, **kw))

                def hc(*args, errors=False, timeout=60):
                    return None
            """,
            "test_pm.py": """
                import pm

                def fake_hc(*args, errors=False):
                    return {}

                def test_hc():
                    pm.hc = fake_hc
            """,
        })
        self.assertEqual(len(report.errors), 1)
        err = report.errors[0]
        self.assertEqual(err.code, "SIG_MISMATCH")
        self.assertEqual(err.attr, "hc")
        self.assertIn("forwarded via HcHost._runner", err.message)
        self.assertIn("timeout", err.message)

    def test_guarded_kwarg_check_does_not_false_positive(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/reads.py": """
                def outside_reads(repo, *briefs, herdr_docs=None):
                    return []
            """,
            "pmlib/registry.py": """
                from . import reads as reads_mod

                def _accepts_kwarg(fn, name):
                    return False

                def call_reads(repo, *briefs):
                    fn = reads_mod.outside_reads
                    if _accepts_kwarg(fn, "herdr_docs"):
                        return fn(repo, *briefs, herdr_docs="/tmp")
                    return fn(repo, *briefs)
            """,
            "test_pm.py": """
                import pm

                def test_reads():
                    pm.outside_reads = lambda repo, brief="": []
            """,
        })
        self.assertEqual(report.errors, [])

    def test_catches_missing_attr_and_unreachable_patch(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/worker.py": """
                def dead_helper(x):
                    return x

                def real_work():
                    return 42
            """,
            "test_pm.py": """
                from unittest import mock
                import pm

                def test_dead():
                    with mock.patch.object(pm, "dead_helper", return_value=1):
                        pass
                    with mock.patch.object(pm, "gone_forever", return_value=2):
                        pass
            """,
        })
        codes = sorted((f.code, f.attr) for f in report.errors)
        self.assertEqual(codes, [("MISSING_ATTR", "gone_forever"), ("UNREACHABLE_PATCH", "dead_helper")])

    def test_flags_bypass_risk_for_manual_review(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/reads.py": """
                def _outside_reads_impl(repo):
                    return []

                def outside_reads(repo):
                    return _outside_reads_impl(repo)

                _DEFAULT_OUTSIDE_READS = outside_reads
            """,
            "pmlib/registry.py": """
                from . import reads as reads_mod

                def get_reads(repo, legacy=False):
                    if legacy and reads_mod.outside_reads is not reads_mod._DEFAULT_OUTSIDE_READS:
                        return reads_mod.outside_reads(repo)
                    return reads_mod._outside_reads_impl(repo)
            """,
            "test_pm.py": """
                import pm

                def test_reads():
                    pm.outside_reads = lambda repo: []
            """,
        })
        self.assertEqual(report.errors, [])
        self.assertEqual([(r.code, r.attr) for r in report.reviews], [("BYPASS_RISK", "outside_reads")])
        self.assertIn("pmlib/registry.py", report.reviews[0].message)

    def test_shim_module_and_teardown_restore_and_global_rebind(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/events.py": """
                _CACHE = None

                def get_cache():
                    global _CACHE
                    if _CACHE is None:
                        _CACHE = 1
                    return _CACHE

                def watch(path):
                    return path
            """,
            "pmlib/cli.py": """
                from . import events

                def run():
                    return events.watch("/tmp")
            """,
            "pm_events.py": """
                import sys as _sys
                import pmlib.events as _impl
                _sys.modules[__name__] = _impl
            """,
            "test_pm_events.py": """
                from unittest import mock
                import pm
                import pm_events

                def test_shim_and_restore():
                    saved = pm._CACHE
                    pm._CACHE = None
                    pm._CACHE = saved
                    with mock.patch.object(pm_events, "watch", side_effect=lambda p: p):
                        pass
            """,
        })
        self.assertEqual(report.errors, [])

    def test_catches_narrow_varargs_forwarding_and_context_and_register_wiring(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/screen.py": """
                def screen_line(term, width=160):
                    return ""
            """,
            "pmlib/host.py": """
                from . import screen as screen_mod

                class HcHost:
                    def __init__(self, config_port=None, *, rpc_runner=None, screen_line_fn=None):
                        self._config = config_port
                        self._rpc_runner = rpc_runner
                        self._screen_line_fn = screen_line_fn
                        self._hooks = []

                    def register_hook(self, fn):
                        self._hooks.append(fn)

                    def rpc(self, m, p):
                        return self._rpc_runner(m, p)

                    def screen_line(self, term, width=160):
                        return self._screen_line_fn(term, width)

                    @classmethod
                    def legacy(cls):
                        return cls(
                            lambda: config(),
                            rpc_runner=lambda m, p: hc_rpc(m, p),
                            screen_line_fn=lambda *args: screen_mod.screen_line(*args),
                        )

                def config():
                    return {}

                def hc_rpc(m, p):
                    return None
            """,
            "pmlib/ctx.py": """
                from dataclasses import dataclass
                from typing import Any

                def seat_alive(pid):
                    return True

                @dataclass
                class Context:
                    seat_alive: Any = None

                def make_legacy():
                    return Context(seat_alive=seat_alive)

                def check(ctx):
                    return ctx.seat_alive(123, extra=True)
            """,
            "test_pm.py": """
                import pm

                def test_all():
                    pm.screen_line = lambda t: "ok"
                    pm.hc_rpc = lambda m, p: None
                    pm.config = lambda: {}
                    pm.seat_alive = lambda pid: True
            """,
        })
        by_attr = {f.attr: f for f in report.errors}
        self.assertIn("screen_line", by_attr)
        self.assertIn("too many positional args", by_attr["screen_line"].message)
        self.assertIn("seat_alive", by_attr)
        self.assertIn("unexpected keyword argument(s): extra", by_attr["seat_alive"].message)
        # hc_rpc is called via HcHost.rpc (non-legacy) so it must NOT be flagged as legacy-only BYPASS_RISK
        hc_rpc_reviews = [r for r in report.reviews if r.attr == "hc_rpc"]
        self.assertEqual(hc_rpc_reviews, [])

    def test_catches_alias_import_bypass_and_submodule_unreachable_and_class_method_bypass(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/cfg.py": """
                def config():
                    return {}
            """,
            "pmlib/consumer.py": """
                from .cfg import config as legacy_config

                def read_it():
                    return legacy_config()

                class Home:
                    def config(self):
                        return {}
            """,
            "pmlib/sub_a.py": """
                def ping():
                    return 1
            """,
            "pmlib/sub_b.py": """
                from .sub_a import ping

                def use_ping():
                    return ping()
            """,
            "test_pm.py": """
                from unittest import mock
                import pm
                from pmlib import sub_a

                def test_bypasses():
                    pm.config = lambda: {}
                    with mock.patch.object(sub_a, "ping", return_value=2):
                        pass
            """,
        })
        err_codes = {(f.code, f.attr) for f in report.errors}
        self.assertIn(("ALIAS_IMPORT_BYPASS", "config"), err_codes)
        # Patching sub_a.ping directly does NOT reach sub_b's bare `from .sub_a import ping`!
        self.assertIn(("UNREACHABLE_PATCH", "ping"), err_codes)
        rev_codes = {(r.code, r.attr) for r in report.reviews}
        self.assertIn(("BYPASS_RISK", "config"), rev_codes)

    def test_surfaces_unknown_sig_and_append_and_factory_and_star_args_unpacking(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/work.py": """
                def notify(repo, extra=False):
                    pass

                def dispatch(cmd):
                    pass

                def reads(repo, *briefs):
                    return []

                def opaque(x):
                    return x

                def caller(items):
                    notify("/r", extra=True)
                    dispatch("go")
                    reads("/r", *items)
                    opaque(1)
            """,
            "test_pm.py": """
                from unittest import mock
                import pm

                class MyTests:
                    def make_dispatch(self):
                        return lambda cmd: None

                    def test_it(self, mystery_fn):
                        seen = []
                        pm.notify = seen.append
                        with mock.patch.object(pm, "dispatch", side_effect=self.make_dispatch()):
                            pass
                        pm.reads = lambda repo, brief="": []
                        pm.opaque = mystery_fn
            """,
        })
        # seen.append rejects extra=True
        self.assertEqual([(f.code, f.attr) for f in report.errors], [("SIG_MISMATCH", "notify")])
        # dispatch resolved via factory -> no error, no UNKNOWN_SIG
        rev_pairs = {(r.code, r.attr) for r in report.reviews}
        self.assertIn(("UNKNOWN_SIG", "opaque"), rev_pairs)
        self.assertIn(("DYNAMIC_CALL_SITE", "reads"), rev_pairs)
        self.assertNotIn(("UNKNOWN_SIG", "dispatch"), rev_pairs)

    def test_catches_fixed_and_varargs_bridge_lambda_signature_mismatches(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/port.py": """
                def fn_fixed(x):
                    return x

                def fn_varargs(*args):
                    return args

                def fn_prefixed(a, *args):
                    return (a, args)

                class Port:
                    def __init__(self, *, fixed=None, varargs=None, prefixed=None):
                        self._fixed = fixed
                        self._varargs = varargs
                        self._prefixed = prefixed

                    def call_fixed_too_many(self):
                        return self._fixed(1, 2)

                    def call_fixed_kw(self):
                        return self._fixed(1, extra=True)

                    def call_fixed_star(self, items):
                        return self._fixed(*items)

                    def call_varargs_kw(self):
                        return self._varargs(1, kw=2)

                    def call_varargs_dstar(self, opts):
                        return self._varargs(1, **opts)

                    def call_prefixed_missing(self):
                        return self._prefixed()

                    def call_prefixed_narrow_patch(self):
                        return self._prefixed(1, 2)

                    @classmethod
                    def legacy(cls):
                        return cls(
                            fixed=lambda x: fn_fixed(x),
                            varargs=lambda *args: fn_varargs(*args),
                            prefixed=lambda prefix, *args: fn_prefixed(prefix, *args),
                        )
            """,
            "test_pm.py": """
                import pm

                def test_bridges():
                    pm.fn_fixed = lambda *a, **kw: None
                    pm.fn_varargs = lambda *a, **kw: None
                    pm.fn_prefixed = lambda a: a
            """,
        })
        errs_by_attr: dict[str, list[str]] = {}
        for f in report.errors:
            self.assertEqual(f.code, "SIG_MISMATCH")
            errs_by_attr.setdefault(f.attr, []).append(f.message)

        # Fixed-arg bridge rejects extra positional arg and unexpected kwarg even when patch accepts (*a, **kw)
        self.assertTrue(
            any("too many positional args" in m and "bridge sig: (x)" in m for m in errs_by_attr.get("fn_fixed", [])),
            errs_by_attr,
        )
        self.assertTrue(
            any("unexpected keyword argument(s): extra" in m and "bridge sig: (x)" in m for m in errs_by_attr.get("fn_fixed", [])),
            errs_by_attr,
        )
        # Varargs-only bridge rejects kwarg even when patch accepts (*a, **kw)
        self.assertTrue(
            any("unexpected keyword argument(s): kw" in m and "bridge sig: (*args)" in m for m in errs_by_attr.get("fn_varargs", [])),
            errs_by_attr,
        )
        # Prefixed varargs bridge rejects missing prefix arg AND still checks forwarded arity against narrow patch
        self.assertTrue(
            any("missing required argument(s): prefix" in m and "bridge sig: (prefix, *args)" in m for m in errs_by_attr.get("fn_prefixed", [])),
            errs_by_attr,
        )
        self.assertTrue(
            any("too many positional args" in m and "patch sig: (a)" in m for m in errs_by_attr.get("fn_prefixed", [])),
            errs_by_attr,
        )
        # Unpacking *items into fixed bridge / **opts into varargs-only bridge -> DYNAMIC_CALL_SITE manual review
        rev_pairs = {(r.code, r.attr) for r in report.reviews}
        self.assertIn(("DYNAMIC_CALL_SITE", "fn_fixed"), rev_pairs)
        self.assertIn(("DYNAMIC_CALL_SITE", "fn_varargs"), rev_pairs)

    def test_tracks_callback_calls_inside_for_loops_on_hooks_and_context(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/bus.py": """
                from dataclasses import dataclass
                from typing import Any

                def hook_direct(x):
                    return x

                def hook_fixed(x):
                    return x

                def after_a(x):
                    return x

                def after_b(x):
                    return x

                class Bus:
                    def __init__(self, ctx=None):
                        self._ctx = ctx
                        self._hooks = []

                    def register_hook(self, fn):
                        self._hooks.append(fn)

                    def fire(self):
                        for fn in self._hooks:
                            fn(1, extra=True)

                    def fire_ctx(self):
                        for cb in (self._ctx.after_save or ()):
                            cb(1, 2)

                @dataclass
                class Context:
                    after_save: tuple[Any, ...] = ()

                def wire_all():
                    bus = Bus()
                    bus.register_hook(hook_direct)
                    bus.register_hook(lambda x: hook_fixed(x))
                    return Context(after_save=(after_a, after_b))

                def run_after(ctx):
                    for fn in ctx.after_save:
                        fn(bad=1)
            """,
            "test_pm.py": """
                import pm

                def test_loops():
                    pm.hook_direct = lambda x: x
                    pm.hook_fixed = lambda *a, **kw: None
                    pm.after_a = lambda x: x
                    pm.after_b = lambda x: x
            """,
        })
        errs_by_attr: dict[str, list[str]] = {}
        for f in report.errors:
            self.assertEqual(f.code, "SIG_MISMATCH")
            errs_by_attr.setdefault(f.attr, []).append(f.message)

        self.assertTrue(
            any("unexpected keyword argument(s): extra" in m for m in errs_by_attr.get("hook_direct", [])),
            errs_by_attr,
        )
        self.assertTrue(
            any("unexpected keyword argument(s): extra" in m and "bridge sig: (x)" in m for m in errs_by_attr.get("hook_fixed", [])),
            errs_by_attr,
        )
        for attr in ("after_a", "after_b"):
            self.assertTrue(
                any("too many positional args" in m for m in errs_by_attr.get(attr, [])),
                errs_by_attr,
            )
            self.assertTrue(
                any("unexpected keyword argument(s): bad" in m for m in errs_by_attr.get(attr, [])),
                errs_by_attr,
            )

    def test_distinguishes_module_attr_from_instance_attr_and_checks_unknown_sig_on_called_values(self):
        report = self._run_toy({
            "pmlib/__init__.py": "",
            "pmlib/launch.py": """
                def claude_dir():
                    return "/tmp/claude"

                def resume_argv(sid):
                    return [sid]

                def delegated(x):
                    return x

                def _make_cb():
                    return lambda x: x

                value_callable = _make_cb()
            """,
            "pmlib/registry.py": """
                from . import launch as launch_mod

                class AgentRegistry:
                    def __init__(self, ctx=None):
                        self._ctx = ctx

                    def get(self, kind):
                        return self._ctx

                    @property
                    def claude_dir(self):
                        return self._ctx.claude_dir

                    def resume_argv(self, kind, sid):
                        return self.get(kind).resume_argv(sid)

                    def delegated(self, x):
                        return launch_mod.delegated(x)

                def invoke_value():
                    return launch_mod.value_callable(1)
            """,
            "test_pm.py": """
                import pm

                def test_attrs(mystery_fn):
                    pm.claude_dir = lambda: "/fake"
                    pm.resume_argv = lambda sid: [sid]
                    pm.delegated = lambda x: x
                    pm.value_callable = mystery_fn
            """,
        })
        rev_pairs = {(r.code, r.attr) for r in report.reviews}
        # Instance attribute reads/calls (self._ctx.claude_dir, self.get(kind).resume_argv) must NOT silence BYPASS_RISK
        self.assertIn(("BYPASS_RISK", "claude_dir"), rev_pairs)
        self.assertIn(("BYPASS_RISK", "resume_argv"), rev_pairs)
        # True module-qualified call (launch_mod.delegated) DOES delegate, so no BYPASS_RISK
        self.assertNotIn(("BYPASS_RISK", "delegated"), rev_pairs)
        # Symbol defined via assignment (kind="value") but called in prod must still emit UNKNOWN_SIG
        self.assertIn(("UNKNOWN_SIG", "value_callable"), rev_pairs)

    def test_fingerprint_is_line_number_independent(self):
        f1 = patch_audit.Finding(
            severity="error",
            code="SIG_MISMATCH",
            attr="hc",
            message="self._runner(*args, timeout=t) [forwarded via HcHost._runner (wired at pmlib/hc.py:547)]",
            call_loc="pmlib/hc.py:210",
            patch_loc="test_pm.py:2347",
        )
        f2 = patch_audit.Finding(
            severity="error",
            code="SIG_MISMATCH",
            attr="hc",
            message="self._runner(*args, timeout=t) [forwarded via HcHost._runner (wired at pmlib/hc.py:559)]",
            call_loc="pmlib/hc.py:212",
            patch_loc="test_pm.py:2360",
        )
        self.assertEqual(f1.fingerprint, f2.fingerprint)
        self.assertNotIn(":547", f1.fingerprint)
        self.assertNotIn(":210", f1.fingerprint)

    def test_cli_exit_codes_and_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = _make_toy_scripts(Path(tmp), {
                "pmlib/__init__.py": "",
                "pmlib/screen.py": """
                    def screen_of(term, *, host=None):
                        return ""

                    def screen_line(term, *, host=None):
                        return screen_of(term, host=host)
                """,
                "test_pm.py": """
                    from unittest import mock
                    import pm

                    def test_fast():
                        with mock.patch.object(pm, "screen_of", side_effect=lambda t: "ok"):
                            pass
                """,
            })
            res = subprocess.run(
                [sys.executable, str(TESTS_DIR / "patch_audit.py"), "--scripts", str(scripts), "--no-baseline"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
            self.assertIn("SIG_MISMATCH", res.stdout)

            # With baseline updated, exit code becomes 0
            baseline_file = scripts / "tests" / "patch_audit_baseline.json"
            baseline_file.parent.mkdir(parents=True, exist_ok=True)
            res_upd = subprocess.run(
                [sys.executable, str(TESTS_DIR / "patch_audit.py"), "--scripts", str(scripts),
                 "--baseline", str(baseline_file), "--update-baseline"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(res_upd.returncode, 0, res_upd.stdout + res_upd.stderr)

            res_ok = subprocess.run(
                [sys.executable, str(TESTS_DIR / "patch_audit.py"), "--scripts", str(scripts),
                 "--baseline", str(baseline_file)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(res_ok.returncode, 0, res_ok.stdout + res_ok.stderr)


class PatchAuditRepoIntegrationTests(unittest.TestCase):
    def test_real_scripts_tree_has_no_new_patch_contract_errors(self):
        baseline_path = patch_audit.default_baseline_path(SCRIPTS_DIR)
        baseline = patch_audit.load_baseline(baseline_path)
        report = patch_audit.audit(SCRIPTS_DIR, baseline=baseline)
        self.assertLess(report.elapsed_ms, 5000.0, f"patch_audit took too long: {report.elapsed_ms:.0f}ms")
        self.assertEqual(
            report.errors,
            [],
            "New patch contract errors found:\n" + patch_audit.format_report(report),
        )


if __name__ == "__main__":
    unittest.main()
