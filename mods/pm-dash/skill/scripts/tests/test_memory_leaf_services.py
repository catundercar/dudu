"""Context-based unit tests for Stage 3c: MemoryLayer, MemoryCandidates, Decisions, LibraryService, HomeMover, DiscordMirror."""
from __future__ import annotations

import datetime
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

if "pmlib.context" not in sys.modules:
    _saved_pm_home = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = str(Path(tempfile.gettempdir()) / "pm-home-for-test-memory-3c")
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved_pm_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_pm_home

from pmlib import context as context_mod, discord as discord_mod, library as library_mod  # noqa: E402
from pmlib.context import Context  # noqa: E402
from pmlib.discord import DiscordMirror, chunks, replied_on_discord  # noqa: E402
from pmlib.errors import Refused, VersionConflict  # noqa: E402
from pmlib.homemove import HomeMover  # noqa: E402
from pmlib.ledger import ledger as ledger_mod  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.library import LibraryService  # noqa: E402
from pmlib.memory import candidates as candidates_mod, layer as layer_mod  # noqa: E402
from pmlib.memory.candidates import CANDIDATE_GRACE, MemoryCandidates  # noqa: E402
from pmlib.memory.decisions import Decisions  # noqa: E402
from pmlib.memory.layer import MemoryLayer, MemoryRefused, memory_text, read_memory  # noqa: E402
from pmlib.project import conversation as conversation_mod  # noqa: E402
from tests.fakes import FakeClock, FakeHc, FakeTui, make_ctx  # noqa: E402


class MemoryLayerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "demo-repo"
        self.repo.mkdir()
        self.clock = FakeClock("2026-11-23 10:00:00")
        self.pruned: list[str] = []
        self.ctx = make_ctx(
            self.base,
            clock=self.clock,
            candidate_pruner=lambda r: self.pruned.append(str(r)),
        )

    def test_remember_index_caps_history_and_restore(self) -> None:
        layer = MemoryLayer(self.ctx, self.repo, index_lines_cap=3)
        m1, notes1 = layer.remember(
            "Use explicit Context everywhere",
            writer=("user", "user"),
            name="explicit-context",
            kind="project",
        )
        self.assertEqual(m1["name"], "explicit-context")
        self.assertEqual(notes1, [])
        self.assertEqual(self.pruned, [str(self.repo)])

        # Replace twice in the same second: .history gets collision-suffixed filename.
        m2, _ = layer.remember(
            "Use explicit Context everywhere v2",
            writer=("user", "user"),
            name="explicit-context",
            kind="project",
        )
        m3, _ = layer.remember(
            "Use explicit Context everywhere v3",
            writer=("user", "user"),
            name="explicit-context",
            kind="project",
        )
        self.assertEqual(m2["description"], "Use explicit Context everywhere v2")
        self.assertEqual(m3["description"], "Use explicit Context everywhere v3")
        hist = layer.history("explicit-context")
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["version"], "20261123-100000-02")
        self.assertEqual(hist[1]["version"], "20261123-100000")

        # Add a second memory to overflow index_lines_cap=3 (heading + 1 line = 2; 2nd line = 3; 3rd overflows).
        layer.remember("Keep wire protocols backward compatible", writer=("user", "user"), name="second-rule", kind="project")
        _, notes3 = layer.remember("Zero print calls inside layer three services", writer=("user", "user"), name="third-rule", kind="project")
        self.assertTrue(any("over its limit" in n for n in notes3))

        # Forget and restore.
        layer.forget(read_memory(layer.dir / "third-rule.md"), writer=("user", "user"), why="obsolete")
        self.assertFalse((layer.dir / "third-rule.md").exists())
        restored = layer.restore("third-rule", writer=("user", "user"))
        self.assertEqual(restored["description"], "Zero print calls inside layer three services")

    def test_writer_rules_pitfall_footer_and_deliver_turn_guard(self) -> None:
        layer = MemoryLayer(self.ctx, self.repo)
        # Worker trying to write a project decision gets coerced to pitfall (requires --verified).
        with self.assertRaises(MemoryRefused):
            layer.remember("A trap I found", writer=("worker", "worker:t1"), name="trap-one", kind="project")

        m, notes = layer.remember(
            "A trap I found",
            writer=("worker", "worker:t1"),
            name="trap-one",
            kind="project",
            verified="ran unit test",
        )
        self.assertEqual(m["type"], "pitfall")
        self.assertEqual(m["topic"], "pitfalls")
        self.assertEqual(m["task"], "t1")
        self.assertTrue(any("Recorded as a pitfall" in n for n in notes))

        index_text = (layer.dir / "MEMORY.md").read_text()
        self.assertIn("1 engineering pitfalls are given to workers", index_text)
        self.assertNotIn("trap-one", index_text)
        self.assertIn("trap-one", layer.memory_block(worker=True))

        # PM in a delivered turn cannot write personal memory or quoted rules.
        tc = self.ctx.home.project_for(self.repo).turn_cause
        tc.parent.mkdir(parents=True, exist_ok=True)
        tc.write_text(json.dumps({"after": "deliver"}))
        personal = MemoryLayer(self.ctx, None)
        with self.assertRaises(MemoryRefused):
            personal.remember(
                "Always reply in Chinese",
                writer=("pm", "pm-demo-repo"),
                name="reply-zh",
                kind="feedback",
                quote="reply in Chinese",
                project_repo=self.repo,
            )

    def test_decisions_unremembered_keeps_once(self) -> None:
        layer = MemoryLayer(self.ctx, self.repo)
        layer.remember("Use MIT license", writer=("user", "user"), name="mit-license", kind="project")
        dec = Decisions(self.ctx, self.repo)
        dec.path.parent.mkdir(parents=True, exist_ok=True)
        dec.path.write_text(
            "- 2026-11-22 Use MIT license\n"
            "- 2026-11-22 [once] Deploy after merge\n"
            "- 2026-11-22 Keep CLI surface frozen\n",
            encoding="utf-8",
        )
        self.assertEqual(
            dec.unremembered(),
            ["- 2026-11-22 [once] Deploy after merge", "- 2026-11-22 Keep CLI surface frozen"],
        )


class MemoryCandidatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "demo-repo"
        self.repo.mkdir()
        self.clock = FakeClock("2026-11-23 12:00:00")
        self.ctx = make_ctx(self.base, clock=self.clock)

    def test_prune_and_adopt_and_drop(self) -> None:
        cands = MemoryCandidates(self.ctx, self.repo)
        (cands.dir / "stale-worker").mkdir(parents=True)
        (cands.dir / "stale-worker" / "MEMORY.md").write_text("")
        old_ts = self.clock.time() - 2 * CANDIDATE_GRACE
        os.utime(cands.dir / "stale-worker", (old_ts, old_ts))

        (cands.dir / "w1").mkdir(parents=True)
        (cands.dir / "w1" / "tip.md").write_text(
            memory_text({"name": "tip", "description": "Watch out for locks", "type": "pitfall", "body": "Full detail"}),
            encoding="utf-8",
        )
        self.assertEqual(cands.prune(), ["stale-worker"])
        self.assertEqual(len(cands.list()), 1)

        with self.assertRaises(Refused):
            cands.adopt("w1/tip", writer=("worker", "worker:t1"))

        res = cands.adopt("w1/tip", writer=("pm", "pm-demo-repo"), verified="verified in test")
        self.assertFalse(res.dropped)
        self.assertEqual(res.memory["name"], "tip")
        self.assertEqual(res.memory["by"], "worker:w1")
        self.assertFalse((cands.dir / "w1").exists())

        # Drop path.
        (cands.dir / "w2").mkdir(parents=True)
        (cands.dir / "w2" / "junk.md").write_text(
            memory_text({"name": "junk", "description": "Ignore me", "type": "pitfall", "body": "x"}),
            encoding="utf-8",
        )
        dropped = cands.adopt("w2/junk", writer=("user", "user"), drop=True)
        self.assertTrue(dropped.dropped)
        self.assertIsNone(dropped.memory)
        self.assertEqual(cands.list(), [])


class LibraryServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "demo-repo"
        self.repo.mkdir()
        self.clock = FakeClock("2026-11-23 12:00:00")
        self.ctx = make_ctx(self.base, clock=self.clock)
        self.svc = LibraryService(self.ctx)

    def test_save_retopic_version_conflict_and_memory_page(self) -> None:
        raw = memory_text({
            "name": "use-ports",
            "description": "Isolate IO behind ports",
            "type": "project",
            "topic": "architecture",
            "body": "Body v1",
        })
        m, created = self.svc.save_memory_file(
            self.repo, False, "use-ports", raw, writer=("user", "user"), if_version="new"
        )
        self.assertTrue(created)
        self.assertEqual(m["topic"], "architecture")

        with self.assertRaises(VersionConflict):
            self.svc.save_memory_file(
                self.repo, False, "use-ports", "Body v2", writer=("user", "user"), if_version="stale"
            )

        moved, created2 = self.svc.retopic_memory(
            self.repo, False, "use-ports", writer=("user", "user"), topic="workflow"
        )
        self.assertFalse(created2)
        self.assertEqual(moved["topic"], "workflow")

        page = self.svc.memory_page(self.repo)
        self.assertEqual(page["project"], "demo-repo")
        self.assertEqual(len(page["files"]), 1)
        self.assertEqual(page["history"]["project"], 1)
        self.assertEqual(
            page["dream"],
            {
                "auto": False,
                "running": False,
                "last_at": "",
                "summary": None,
                "failures": 0,
                "pending": 0,
            },
        )

    def test_research_migration_dry_run_and_apply(self) -> None:
        slug = "demo-repo"
        ev = self.ctx.home.project(slug).research / "topic-a"
        ev.mkdir(parents=True)
        (ev / "README.md").write_text("# Report\nSee [img](shot.png)\n", encoding="utf-8")
        (ev / "shot.png").write_bytes(b"png")

        dry = self.svc.migrate_research(slug, apply=False)
        self.assertFalse(dry["applied"])
        self.assertEqual(dry["reports"][0]["status"], "move")
        self.assertEqual(dry["reports"][0]["links_to_fix"], ["shot.png"])

        applied = self.svc.migrate_research(slug, apply=True)
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["reports"][0]["status"], "moved")
        self.assertTrue((self.ctx.home.project(slug).docs_research / "topic-a.md").is_file())


class HomeMoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.fake_home = self.base / "home"
        self.fake_home.mkdir()

    def test_inspect_format_status_and_active_writers_with_fakes(self) -> None:
        hc = FakeHc(terminals={
            "t1": {"address": "t1", "state": "live", "labels": {"pm": "demo"}},
            "t2": {"address": "t2", "state": "live", "labels": {"task": "demo-1"}},
        })
        tui = FakeTui(server_ok=False)
        ctx = make_ctx(self.base, hc=hc, tui=tui, env={"PM_HOME": ""})
        mover = HomeMover(ctx)

        legacy = self.fake_home / ".claude" / "pm"
        (legacy / "pms").mkdir(parents=True)
        (legacy / "tasks").mkdir(parents=True)
        (legacy / "pms" / "demo.json").write_text(json.dumps({"project": "demo", "name": "pm-demo", "pane": "hc:t1"}))
        (legacy / "tasks" / "demo-1.json").write_text(json.dumps({"id": "demo-1", "status": "in_progress", "pane": "w1:p1"}))

        info = mover.inspect(home_dir=self.fake_home)
        self.assertEqual(info["status"], "legacy")
        lines = mover.format_status(info)
        self.assertTrue(any("legacy ledger" in line for line in lines))
        self.assertTrue(any("home --migrate --dry-run" in line for line in lines))

        blockers = mover.active_writers(legacy)
        kinds = {b["kind"] for b in blockers}
        self.assertIn("pm_terminal", kinds)
        self.assertIn("worker_terminal", kinds)

        ctx.home.root.mkdir(parents=True, exist_ok=True)
        (ctx.home.root / "BOARD.md").write_text("# Board\n")
        backup = mover.create_backfill_backup(backup_dir=self.base / "backups")
        self.assertTrue(Path(backup["path"]).is_file())
        self.assertGreaterEqual(backup["entries"], 1)


class DiscordMirrorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "demo-repo"
        self.repo.mkdir()
        self.discord_home = self.base / "discord-home"
        self.plugin_root = self.base / "discord-plugin"

    def test_off_by_default_and_post_board_and_mcp_state(self) -> None:
        calls: list[tuple[str, str, object]] = []

        def fake_api(method: str, path: str, body: object) -> object:
            calls.append((method, path, body))
            if method == "PATCH":
                return None  # simulate deleted message -> fallback to POST
            return {"id": "msg-42"}

        ctx_off = make_ctx(self.base / "off")
        mirror_off = DiscordMirror(ctx_off, discord_home=self.discord_home, plugin_root_dir=self.plugin_root, api_fn=fake_api)
        self.assertFalse(mirror_off.is_on())
        with self.assertRaises(Refused):
            mirror_off.require_on()
        self.assertFalse(mirror_off.post_board())
        self.assertEqual(calls, [])

        ctx_on = make_ctx(
            self.base / "on",
            pane="hc:t7",
            config={"discord": True},
            env={"DISCORD_BOT_TOKEN": "tok-123"},
        )
        Ledger(ctx_on).save({"id": "demo-1", "title": "Ship 3c", "project": "demo", "repo": str(self.repo), "status": "in_progress"})
        ctx_on.home.discord_config.parent.mkdir(parents=True, exist_ok=True)
        ctx_on.home.discord_config.write_text(json.dumps({"board_channel": "ch-1", "message_id": "old-msg"}))

        mirror = DiscordMirror(ctx_on, discord_home=self.discord_home, plugin_root_dir=self.plugin_root, api_fn=fake_api)
        self.assertTrue(mirror.post_board())
        self.assertEqual([c[0] for c in calls], ["PATCH", "POST"])
        saved_cfg = json.loads(ctx_on.home.discord_config.read_text())
        self.assertEqual(saved_cfg["message_id"], "msg-42")

        # Missing plugin raises Refused, not sys.exit.
        with self.assertRaises(Refused):
            mirror.plugin_root()

        ver = self.plugin_root / "1.0.0"
        ver.mkdir(parents=True)
        (ver / "server.ts").write_text("// ok")
        sdir = mirror.write_state(self.repo, "ch-9", ["u1"])
        self.assertTrue((sdir / ".env").is_file())
        self.assertTrue((sdir / "access.json").is_file())
        self.assertTrue(mirror.mcp_config_path(self.repo).is_file())

        # Pure helpers.
        self.assertEqual(len(chunks("a\n" * 2000, size=100, limit=2)), 2)
        self.assertFalse(replied_on_discord(None))


class Stage3cReviewRegressionTest(unittest.TestCase):
    """Regressions pinned from carbon review of Stage 3c."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "demo-repo"
        self.repo.mkdir()

    def test_candidate_pruner_wired_without_cli_and_in_make_ctx_and_from_env(self) -> None:
        # 1. Importing only pmlib.memory.layer (no cli, no pm) still populates Context.from_env().candidate_pruner.
        code = (
            f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); "
            "import pmlib.memory.layer; "
            "from pmlib.context import Context; "
            "assert Context.from_env().candidate_pruner is not None"
        )
        env = {**os.environ, "PM_HOME": str(self.base / "sub-home")}
        proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        # 2. make_ctx without explicit candidate_pruner falls back to MemoryCandidates.prune() during write_index().
        clock = FakeClock("2026-11-23 12:00:00")
        ctx = make_ctx(self.base / "fallback", clock=clock)
        layer = MemoryLayer(ctx, self.repo)
        layer.dir.mkdir(parents=True, exist_ok=True)
        stale = layer.dir / "candidates" / "stale-w"
        stale.mkdir(parents=True)
        old_ts = clock.time() - 2 * CANDIDATE_GRACE
        os.utime(stale, (old_ts, old_ts))
        layer.write_index()
        self.assertFalse(stale.exists())

        # 3. Context.from_env forwards candidate_pruner.
        seen: list[str] = []
        env_ctx = Context.from_env(self.base / "from-env", env={"PM_HOME": str(self.base / "from-env")},
                                   candidate_pruner=lambda r: seen.append(str(r)))
        self.assertIsNotNone(env_ctx.candidate_pruner)
        env_ctx.candidate_pruner(self.repo)
        self.assertEqual(seen, [str(self.repo)])

    def test_legacy_bridges_forward_all_tasks_record_and_three_arg_discord_api(self) -> None:
        ledger_dir = self.base / "legacy-home"
        ledger_dir.mkdir()
        (ledger_dir / "config.json").write_text(json.dumps({"discord": True}))
        ctx = Context.from_env(home_option=ledger_dir, env={"PM_HOME": str(ledger_dir)})
        Ledger(ctx).save({
            "id": "demo-1",
            "title": "Context task",
            "project": "demo-repo",
            "repo": str(self.repo),
            "status": "in_progress",
            "agent": "busy-w",
        })
        cands_dir = ledger_dir / "projects" / "demo-repo" / "memory" / "candidates" / "busy-w"
        cands_dir.mkdir(parents=True)
        old_ts = 1_000_000.0
        os.utime(cands_dir, (old_ts, old_ts))
        self.assertEqual(MemoryCandidates(ctx, self.repo).prune(), [])
        self.assertIn("Context task", DiscordMirror(ctx).board_text())

        MemoryLayer(ctx, self.repo).remember("Keep context working", name="keep-ctx", kind="project", writer=("user", "user"))
        LibraryService(ctx).save_memory_file(self.repo, False, "keep-ctx", "Updated body", writer=("user", "user"))
        conv_events = [e for e in (ledger_dir / "projects" / "demo-repo" / "conversation.jsonl").read_text(encoding="utf-8").splitlines() if e]
        self.assertEqual(len(conv_events), 2)

        api_calls: list[tuple[str, str, object]] = []
        dm = DiscordMirror(
            ctx,
            api_fn=lambda method, path, body=None: api_calls.append((method, path, body)) or {"id": "m-9"},
        )
        dm.write_cfg({"board_channel": "ch-7"})
        self.assertTrue(dm.post_board(force=True))
        dm.mirror({"discord": {"channel_id": "ch-8"}}, "hello")
        self.assertEqual([c[:2] for c in api_calls], [
            ("POST", "/channels/ch-7/messages"),
            ("POST", "/channels/ch-8/messages"),
        ])

    def test_discord_paths_resolve_from_context_home_and_env(self) -> None:
        state_a = self.base / "state-a"
        state_b = self.base / "state-b"
        state_a.mkdir()
        state_b.mkdir()
        ctx_b = Context.from_env(home_option=state_b, env={"PM_HOME": str(state_b)})
        dm_b = DiscordMirror(ctx_b)
        dm_b.write_cfg({"board_channel": "ch-b"})
        self.assertTrue((state_b / "discord.json").is_file())
        self.assertFalse((state_a / "discord.json").exists())
        self.assertEqual(dm_b.read_cfg(), {"board_channel": "ch-b"})

        custom_discord = self.base / "custom-discord-home"
        custom_discord.mkdir()
        (custom_discord / "pm-token.env").write_text("DISCORD_BOT_TOKEN=env-tok-99\n")
        with mock.patch.dict(os.environ, {"DISCORD_HOME": str(custom_discord)}, clear=False):
            os.environ.pop("DISCORD_BOT_TOKEN", None)
            self.assertEqual(discord_mod.discord_state_dir(self.repo), custom_discord / "pm-demo-repo")
            self.assertEqual(discord_mod.discord_token_file(), custom_discord / "pm-token.env")
            self.assertEqual(discord_mod.discord_token(), "env-tok-99")


if __name__ == "__main__":
    unittest.main()
