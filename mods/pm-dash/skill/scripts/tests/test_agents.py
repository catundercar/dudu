"""Unit tests for Stage 2b Agent Ports (`AgentSpec`, `GenericAgent`, `ClaudeAgent`, `CodexAgent`, `PiAgent`,
`AgentRegistry`, `WorkerSpec`, and `pmlib.agents.reads`)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

if "pmlib.context" not in sys.modules:
    _saved_home = os.environ.get("PM_HOME")
    _init_tmp = tempfile.mkdtemp(prefix="pm-agents-init-")
    os.environ["PM_HOME"] = _init_tmp
    try:
        from pmlib import context, osutil  # noqa: E402
    finally:
        if _saved_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_home
else:
    from pmlib import context, osutil  # noqa: E402

from pmlib.agents import base as agents_base, reads as agents_reads  # noqa: E402
from pmlib.agents.base import (  # noqa: E402
    AgentSpec,
    ClaudeAgent,
    CodexAgent,
    GenericAgent,
    PiAgent,
)
from pmlib.agents.profiles import WorkerSpec  # noqa: E402
from pmlib.agents.registry import AgentRegistry  # noqa: E402
from pmlib.errors import Refused  # noqa: E402
from fakes import make_ctx  # noqa: E402


class AgentKindsAndSpecTest(unittest.TestCase):
    def test_builtin_subclasses_and_flag_ordering(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = make_ctx(td)
            reg = AgentRegistry.from_context(ctx)

            claude = reg.get("claude")
            self.assertIsInstance(claude, ClaudeAgent)
            self.assertTrue(claude.has_stop_hook)
            self.assertTrue(claude.takes_prompt)
            self.assertTrue(claude.supports_advisor)
            self.assertTrue(claude.supports_fallback)
            self.assertEqual(
                claude.start_argv("fable", "high", prompt="go", advisor="fable", fallback="opus"),
                ["claude", "--model", "fable", "--effort", "high", "--advisor", "fable", "--fallback-model", "opus", "go"],
            )
            self.assertEqual(
                claude.resume_argv("sid-1", "fable", "high", advisor="", fallback="opus"),
                ["claude", "--model", "fable", "--effort", "high", "--fallback-model", "opus", "--resume", "sid-1"],
            )
            self.assertEqual(claude.stop_block_payload("wait"), {"decision": "block", "reason": "wait"})

            codex = reg.get("codex")
            self.assertIsInstance(codex, CodexAgent)
            self.assertTrue(codex.has_stop_hook)
            self.assertEqual(
                codex.start_argv("gpt-5", "xhigh", prompt="hello", advisor="fable", fallback="opus"),
                ["codex", "-c", "check_for_update_on_startup=false", "-m", "gpt-5", "-c", 'model_reasoning_effort="xhigh"', "hello"],
            )
            self.assertEqual(
                codex.resume_argv("s-2", "gpt-5", "high"),
                ["codex", "resume", "-c", "check_for_update_on_startup=false", "-m", "gpt-5", "-c", 'model_reasoning_effort="high"', "s-2"],
            )

            pi = reg.get("pi")
            self.assertIsInstance(pi, PiAgent)
            self.assertFalse(pi.has_stop_hook)
            self.assertIsNone(pi.resume_argv("s-3"))
            self.assertEqual(
                pi.start_argv("claude-sonnet", "high", prompt="hi"),
                ["pi", "--model", "claude-sonnet", "--thinking", "high", "hi"],
            )

            gemini = reg.get("gemini")
            self.assertIs(type(gemini), GenericAgent)
            self.assertFalse(gemini.takes_prompt)
            self.assertEqual(gemini.start_argv("2.5-pro", "high", prompt="ignored"), ["gemini", "-m", "2.5-pro"])

            custom = reg.get("myagent --fast")
            self.assertIs(type(custom), GenericAgent)
            self.assertEqual(custom.start_argv("m1", prompt="ignored"), ["myagent", "--fast"])

    def test_custom_config_agent_and_launcher_wrapping(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = make_ctx(
                td,
                config={
                    "agents": {"agy": {"argv": ["agy", "--yes"], "model": ["--model", "{}"], "prompt_arg": True}},
                    "claude": {"launcher": ["zsh", "-ic", "my-claude {args}"]},
                    "codex": {"launcher": ["env", "FOO=1", "codex"]},
                },
            )
            reg = AgentRegistry.from_context(ctx)
            self.assertTrue(reg.has("agy"))
            self.assertEqual(reg.start_argv("agy", "neon", prompt="run"), ["agy", "--yes", "--model", "neon", "run"])
            self.assertEqual(
                reg.launch_wrap("claude", ["claude", "--model", "opus", "--effort", "high"]),
                ["zsh", "-ic", "my-claude --model opus --effort high"],
            )
            self.assertEqual(
                reg.launch_wrap("codex", ["codex", "-m", "gpt-5"]),
                ["env", "FOO=1", "codex", "-m", "gpt-5"],
            )
            # Non-claude/codex kinds ignore launcher wrapping
            self.assertEqual(reg.launch_wrap("pi", ["pi", "--model", "x"]), ["pi", "--model", "x"])

            # Windows shell_join quoting through launcher
            with mock.patch.object(osutil, "WINDOWS", True):
                wrapped = reg.launch_wrap("claude", ["claude", "--effort", "x high"])
                self.assertEqual(wrapped, ["zsh", "-ic", 'my-claude --effort "x high"'])

    def test_claude_codex_pi_pm_helpers(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c_dir = base / "claude"
            (c_dir / "skills" / "other").mkdir(parents=True)
            (c_dir / "skills" / "other" / "SKILL.md").write_text("# other")
            (c_dir / "skills" / "pm").mkdir(parents=True)
            (c_dir / "skills" / "pm" / "SKILL.md").write_text("# pm")
            (c_dir / "settings.json").write_text(json.dumps({"enabledPlugins": {"plug@a": True, "off@b": False}}))

            ctx = make_ctx(td)
            ctx.claude_dir = c_dir
            reg = AgentRegistry.from_context(ctx)
            lean = reg.claude_lean_settings()
            self.assertEqual(lean["enabledPlugins"], {"plug@a": False})
            self.assertEqual(lean["skillOverrides"], {"other": "user-invocable-only"})

            claude = reg.get("claude")
            self.assertIsInstance(claude, ClaudeAgent)
            assert isinstance(claude, ClaudeAgent)
            self.assertEqual(
                claude.narrow_pm_argv(["claude", "--model", "opus", "--", "hi"]),
                ["claude", "--model", "opus", "--disallowedTools", "Edit,NotebookEdit", "--", "hi"],
            )
            self.assertEqual(
                claude.narrow_pm_argv(
                    ["claude", "--disallowedTools", "Edit,NotebookEdit", "--", "hi"],
                    narrow_tools=False,
                ),
                ["claude", "--", "hi"],
            )
            self.assertEqual(
                claude.successor_argv(["--resume", "s1", "--permission-mode", "auto", "--", "old"], "opus", "new"),
                ["claude", "--permission-mode", "auto", "--model", "opus", "--", "new"],
            )

            codex_compact = CodexAgent.compact_pm_argv(
                ["codex", "-c", "model_auto_compact_token_limit=100000", "-m", "gpt-5"],
                limit=220_000,
                post_turn_percent=80,
                compact_prompt="cp",
            )
            self.assertEqual(codex_compact[0], "codex")
            self.assertIn("model_auto_compact_token_limit=220000", codex_compact)
            self.assertNotIn("model_auto_compact_token_limit=100000", codex_compact)

            ext = base / "pm_pi_compact.js"
            ext.write_text("// ext")
            pi_compact = PiAgent.compact_pm_argv(["pi", "-e", "/old/pm_pi_compact.js", "--model", "m"], ext_path=ext)
            self.assertEqual(pi_compact, ["pi", "-e", str(ext), "--model", "m"])


class WorkerSpecAndRegistryResolutionTest(unittest.TestCase):
    def test_resolve_worker_profiles_fable_off_and_refused(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = make_ctx(td, config={"fable": False, "lang": "zh"})
            reg = AgentRegistry.from_context(ctx)

            hard = reg.resolve_worker(WorkerSpec(profile="hard"))
            self.assertEqual((hard.kind, hard.model, hard.effort, hard.advisor, hard.fallback), ("claude", "opus", "xhigh", "", ""))
            self.assertEqual(hard.to_record(), {"profile": "hard", "kind": "claude", "model": "opus", "effort": "xhigh", "advisor": ""})
            self.assertEqual(hard.summary(), "hard: claude opus xhigh")
            self.assertEqual(hard.engine_label(), "Opus·xhigh")
            self.assertEqual(reg.ladder(), ("light", "standard", "hard"))

            with self.assertRaises(Refused) as err:
                reg.resolve_worker(WorkerSpec(profile="deep"))
            self.assertEqual(err.exception.code, 1)
            self.assertIn("没有档位 deep", str(err.exception))
            self.assertIn('"fable": false', str(err.exception))

    def test_worker_argv_with_codex_pool_and_claude_reads(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            (repo / "briefs").mkdir(parents=True)
            brief = repo / "briefs" / "b.md"
            brief.write_text("brief")
            herdr_docs = base / "herdr-docs"
            herdr_docs.mkdir()

            ctx = make_ctx(
                td,
                config={
                    "codex": {"args": ["-c", 'model_provider="pm"', "-c", "service_tier=fast", "-c", "keep=1"], "model_prefix": "p/"},
                },
            )
            ctx.herdr_docs = herdr_docs
            reg = AgentRegistry.from_context(ctx)

            # Codex with provider strips model_provider and service_tier, prefixes model, injects -p
            cspec = WorkerSpec(kind="codex", model="gpt-5", effort="high", provider="acct1")
            c_argv = reg.worker_argv(cspec, codex_pool_active=True)
            self.assertEqual(
                c_argv,
                [
                    "codex",
                    "-p", "acct1",
                    "-c", "keep=1",
                    "-c", "check_for_update_on_startup=false",
                    "-m", "p/gpt-5",
                    "-c", 'model_reasoning_effort="high"',
                ],
            )
            self.assertEqual(cspec.to_record()["provider"], "acct1")
            self.assertEqual(cspec.summary(), "codex -p acct1 gpt-5 high")

            # Outside reads & docs_line use ctx.herdr_docs (isolated from real ~/.config/herdr-app)
            reads = reg.outside_reads(repo, brief)
            self.assertIn(str(herdr_docs.resolve()), reads)
            self.assertIn(str(herdr_docs), reg.docs_line())

            cl_spec = reg.resolve_worker(WorkerSpec(profile="standard"))
            cl_argv = reg.worker_argv(cl_spec, reads=reads, writes=[base / "out.md"])
            self.assertIn("--settings", cl_argv)
            settings_file = Path(cl_argv[cl_argv.index("--settings") + 1])
            self.assertTrue(settings_file.is_relative_to(ctx.home.reads))
            data = json.loads(settings_file.read_text())
            out_rule = f"Write(//{(base / 'out.md').resolve().as_posix().lstrip('/')})"
            self.assertIn(out_rule, data["permissions"]["allow"])
            self.assertTrue(all("\\" not in rule for rule in data["permissions"]["allow"]))

            # Context.from_env wires ctx.agents automatically
            env_ctx = context.Context.from_env(home_option=ctx.home.root, env={"PM_HOME": str(ctx.home.root)})
            self.assertIsInstance(env_ctx.agents, AgentRegistry)

    def test_terminal_kind_and_seat_unwrapping(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = make_ctx(td)
            reg = AgentRegistry.from_context(ctx)
            seat = ["python3", "/x/pm.py", "--home", "/h", "seat", "--repo", "/r", "--kind", "codex", "--", "codex", "-m", "gpt-5"]
            self.assertTrue(agents_base.is_seat_argv(seat))
            self.assertEqual(reg.kind_from_argv(seat), "codex")
            self.assertEqual(
                reg.terminal_kind({"argv": ["zsh"], "status": {"app": "claude-code"}}),
                "claude",
            )


class LegacyPatchCompatAndDynamicCtxTest(unittest.TestCase):
    def test_make_ctx_sets_agents_and_tracks_ctx_path_mutations_dynamically(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            ctx = make_ctx(td)
            self.assertIsInstance(ctx.agents, AgentRegistry)

            new_docs = base / "custom-docs"
            new_docs.mkdir()
            new_claude = base / "custom-claude"
            (new_claude / "skills" / "demo-skill").mkdir(parents=True)
            (new_claude / "skills" / "demo-skill" / "SKILL.md").write_text("# demo")
            new_projects = new_claude / "projects"
            new_codex = base / "custom-codex" / "sessions"

            ctx.herdr_docs = new_docs
            ctx.claude_dir = new_claude
            ctx.claude_projects = new_projects
            ctx.codex_sessions = new_codex

            self.assertEqual(ctx.agents.herdr_docs, new_docs)
            self.assertEqual(ctx.agents.claude_dir, new_claude)
            self.assertEqual(ctx.agents.claude_projects, new_projects)
            self.assertEqual(ctx.agents.codex_sessions, new_codex)
            self.assertIn(str(new_docs), ctx.agents.docs_line())
            self.assertIn(str(new_docs.resolve()), ctx.agents.outside_reads(None))
            self.assertEqual(ctx.agents.claude_lean_settings()["skillOverrides"], {"demo-skill": "user-invocable-only"})

    def test_make_ctx_agents_override_and_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            docs = base / "docs"
            docs.mkdir()
            iso_ctx = make_ctx(td)
            iso_ctx.herdr_docs = docs
            iso_ctx.claude_dir.mkdir(parents=True, exist_ok=True)
            (iso_ctx.claude_dir / "settings.json").write_text(json.dumps({"enabledPlugins": {"x": True}}), encoding="utf-8")
            self.assertIn(str(docs.resolve()), iso_ctx.agents.outside_reads(None))
            self.assertEqual(iso_ctx.agents.claude_lean_settings(), {"enabledPlugins": {"x": False}, "skillOverrides": {}})

    def test_from_env_builds_agents_without_importing_cli(self):
        code = (
            "import os, sys, tempfile\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "td = Path(tempfile.mkdtemp(prefix='pm-l1-env-'))\n"
            "os.environ['PM_HOME'] = str(td / 'ledger')\n"
            "from pmlib import context\n"
            "assert 'pmlib.cli' not in sys.modules\n"
            "assert 'pmlib.workers.brief' not in sys.modules\n"
            "ctx = context.Context.from_env(home_option=td / 'ledger', env={'PM_HOME': str(td / 'ledger')})\n"
            "assert ctx.agents is not None\n"
            "assert ctx.agents.herdr_docs == ctx.herdr_docs\n"
            "assert ctx.agents.claude_projects == ctx.claude_projects\n"
            "assert ctx.agents.codex_sessions == ctx.codex_sessions\n"
            "print('ok')\n"
        )
        res = subprocess.run([sys.executable, "-c", code, str(SCRIPTS)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(res.stdout.strip(), "ok")

    def test_cmd_review_and_reattach_plan_translate_refused_to_system_exit(self):
        import argparse
        from pmlib.commands import review as review_cmd
        from pmlib.ledger.task import Task
        from pmlib.review import review as review_mod
        from pmlib.workers import reattach as reattach_mod

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            ctx = make_ctx(td)
            task = {"id": "demo-1", "repo": str(repo), "branch": "dev/x", "worktree": str(repo), "status": "review"}
            # Stage 5: cmd_review's body is Reviews.start (it loads through Ledger, resolves through reviewer_spec).
            with mock.patch.object(review_mod.Ledger, "load", return_value=Task(task)), \
                    mock.patch.object(review_mod.Reviews, "reviewer_spec", side_effect=Refused("no profile ghost")):
                a = argparse.Namespace(id="demo-1")
                with self.assertRaises(SystemExit) as stop:
                    review_cmd.cmd_review(a, ctx=ctx)
                self.assertEqual(str(stop.exception.code), "no profile ghost")

            from pmlib.agents import profiles as agents_profiles
            with mock.patch.object(reattach_mod, "dispatched_with", return_value=("", "", "")), \
                    mock.patch.object(reattach_mod, "find_session_for", return_value=None), \
                    mock.patch.object(agents_profiles, "resolve_worker_spec", side_effect=Refused("no profile ghost")):
                with self.assertRaises(Refused) as stop:
                    reattach_mod.reattach_plan({"id": "demo-1", "repo": str(repo)})
                self.assertEqual(str(stop.exception), "no profile ghost")

    def test_sessions_reader_works_without_importing_cli_and_tracks_claude_projects_dynamically(self):
        code = (
            "import json, os, sys, tempfile\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "sys.path.insert(0, sys.argv[2])\n"
            "td = Path(tempfile.mkdtemp(prefix='pm-no-cli-sessions-'))\n"
            "os.environ['PM_HOME'] = str(td / 'ledger')\n"
            "from pmlib import context\n"
            "from fakes import make_ctx\n"
            "assert 'pmlib.cli' not in sys.modules\n"
            "env_ctx = context.Context.from_env(home_option=td / 'ledger', env={'PM_HOME': str(td / 'ledger')})\n"
            "assert env_ctx.agents.sessions_reader() is not None\n"
            "ctx = make_ctx(td)\n"
            "reader = ctx.agents.sessions_reader()\n"
            "assert reader is not None\n"
            "# Mutate ctx.claude_projects AFTER obtaining reader and verify dynamic resolution\n"
            "alt_proj = td / 'alt-claude-projects'\n"
            "repo_dir = td / 'demo-repo'\n"
            "repo_dir.mkdir()\n"
            "from pmlib.agents.transcripts import claude_folder\n"
            "folder = alt_proj / claude_folder(repo_dir)\n"
            "folder.mkdir(parents=True)\n"
            "tr_file = folder / 'sid-dyn.jsonl'\n"
            "tr_file.write_text(json.dumps({'type': 'assistant', 'message': {'usage': {'input_tokens': 123}}}) + '\\n')\n"
            "ctx.claude_projects = alt_proj\n"
            "found = reader.transcript({'kind': 'claude', 'id': 'sid-dyn', 'cwd_hints': [str(repo_dir)]})\n"
            "assert found == tr_file.resolve(), (found, tr_file.resolve())\n"
            "assert 'pmlib.cli' not in sys.modules\n"
            "print('ok')\n"
        )
        res = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), str(TESTS_DIR)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(res.stdout.strip(), "ok")

    def test_native_memory_settings_and_reviewer_helper_disallowed_tools(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            mem_root = base / "memory"
            mem_root.mkdir()
            ctx = make_ctx(td)
            reg = ctx.agents

            # Claude PM native memory points directly at memory root; worker uses candidates/<slug>
            pm_mem = reg.native_memory_settings("claude", mem_root, "pm")
            self.assertEqual(pm_mem, {"autoMemoryEnabled": True, "autoMemoryDirectory": str(mem_root)})
            w_mem = reg.native_memory_settings("claude", mem_root, "worker", "My Task!")
            self.assertEqual(w_mem, {"autoMemoryEnabled": True, "autoMemoryDirectory": str(mem_root / "candidates" / "my-task")})
            self.assertTrue((mem_root / "candidates" / "my-task").is_dir())
            # Dry-run create=False does not create candidate directory
            dry_mem = reg.native_memory_settings("claude", mem_root, "worker", "Dry One", create=False)
            self.assertEqual(dry_mem["autoMemoryDirectory"], str(mem_root / "candidates" / "dry-one"))
            self.assertFalse((mem_root / "candidates" / "dry-one").exists())
            # Non-claude agents return empty dict
            self.assertEqual(reg.native_memory_settings("codex", mem_root, "pm"), {})
            self.assertEqual(reg.native_memory_settings("pi", mem_root, "worker", "w"), {})
            # Config {"memory": {"native": false}} disables it for claude too
            off_ctx = make_ctx(td, config={"memory": {"native": False}})
            self.assertEqual(off_ctx.agents.native_memory_settings("claude", mem_root, "pm"), {})

            # Reviewer & helper tool restrictions (reviewers can edit/commit test fixes)
            self.assertEqual(reg.reviewer_extra_argv("claude"), [])
            self.assertEqual(reg.reviewer_extra_argv("codex"), [])
            self.assertEqual(reg.helper_extra_argv("claude", exec_mode=False), ["--disallowedTools", "Edit,NotebookEdit"])
            self.assertEqual(reg.helper_extra_argv("claude", exec_mode=True), [])
            self.assertEqual(reg.helper_extra_argv("codex", exec_mode=False), [])
            self.assertEqual(reg.helper_writes("claude", "/tmp/out.md"), ("/tmp/out.md",))
            self.assertEqual(reg.helper_writes("codex", "/tmp/out.md"), ())

    def test_native_memory_settings_matches_legacy_on_long_names_trailing_dash_and_custom_claude_kind(self):
        from pmlib.memory.layer import MemoryLayer

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "demo-repo"
            repo.mkdir()
            cfg = {"agents": {"claude-work": {"argv": ["claude", "--work"], "model": ["--model", "{}"]}}}
            ctx = make_ctx(td, config=cfg)
            mem_root = ctx.home.memory_dir(repo)
            mem_root.mkdir(parents=True)

            # 39 'a' + '-' + 'bbb': [:40] slices to 39 'a' + '-', so post-slice strip('-') is essential
            long_trailing_dash = "a" * 39 + " bbb-extra-long-task-name"
            long_plain = "x" * 55

            layer = MemoryLayer(ctx, repo)
            for kind in ("claude", "claude-work", "codex"):
                for role, name in (
                    ("pm", ""),
                    ("worker", long_trailing_dash),
                    ("worker", long_plain),
                ):
                    got = ctx.agents.native_memory_settings(kind, mem_root, role, name, create=False)
                    via_layer = layer.native_memory(kind, role, name, create=False)
                    self.assertEqual(got, via_layer, (kind, role, name))

            # Explicitly verify custom claude-work (argv[0] == "claude") is active and trailing '-' is stripped
            got_work = ctx.agents.native_memory_settings(
                "claude-work", mem_root, "worker", long_trailing_dash, create=False
            )
            self.assertEqual(
                got_work,
                {"autoMemoryEnabled": True, "autoMemoryDirectory": str(mem_root / "candidates" / ("a" * 39))},
            )
            self.assertFalse(Path(got_work["autoMemoryDirectory"]).name.endswith("-"))


if __name__ == "__main__":
    unittest.main()
