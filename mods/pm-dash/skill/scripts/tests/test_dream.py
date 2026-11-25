"""Tests for autoDream Step 1 core engine, CLI commands, keep_history return value, and recall redirect."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pmlib.errors import Refused
from pmlib.helpers.records import helper_entries
from pmlib.home import project_slug
from pmlib.ledger.ledger import Ledger
from pmlib.memory.dream import Dream, DreamWatcher, dream_config, extract_repo_paths, protected
from pmlib.memory.layer import MemoryLayer, memory_text, read_memory
from pmlib.project.conversation import Conversation
from pmlib.project.turn_state import TurnTracker
from tests.fakes import FakeClock, FakeHc, FakeProcs, make_ctx, run_main


class _HelperCaller:
    """Minimal caller double for testing dream apply / undo permissions."""

    def __init__(self, *, helper_info=None, writer=("user", "user")):
        self._helper_info = helper_info
        self._writer = writer

    def helper_self_info(self):
        return self._helper_info

    def memory_writer(self, repo):
        return self._writer


class DreamTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "myrepo"
        self.repo.mkdir()
        self.slug = project_slug(self.repo)
        self.clock = FakeClock("2026-11-24 10:00:00")
        self.ctx = make_ctx(self.tmp, clock=self.clock)
        self.layer = MemoryLayer(self.ctx, self.repo)
        self.layer.dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_mem(
        self,
        name: str,
        *,
        description: str = "A useful engineering note",
        kind: str = "pitfall",
        topic: str | None = None,
        by: str = "worker:t1",
        modified: str = "2026-11-20T10:00:00.000Z",
        verified: str = "observed in test run",
        checked: str = "2026-11-20",
        quote: str = "",
        body: str | None = None,
        personal: bool = False,
        extra: dict | None = None,
    ) -> Path:
        target_layer = MemoryLayer(self.ctx, None if personal else self.repo)
        target_layer.dir.mkdir(parents=True, exist_ok=True)
        m = {
            "name": name,
            "description": description,
            "type": kind,
            "topic": topic or ("pitfalls" if kind == "pitfall" else "reference" if kind == "reference" else "architecture"),
            "modified": modified,
            "by": by,
            "quote": quote,
            "verified": verified,
            "checked": checked,
            "body": body if body is not None else description,
            "extra": extra or {},
        }
        p = target_layer.dir / f"{name}.md"
        p.write_text(memory_text(m), encoding="utf-8")
        return p

    def _write_candidate(
        self,
        worker: str,
        name: str,
        *,
        description: str = "Worker discovered pitfall about cache eviction",
        kind: str = "pitfall",
        body: str = "Always clear the cache after reload.",
    ) -> Path:
        folder = self.layer.dir / "candidates" / worker
        folder.mkdir(parents=True, exist_ok=True)
        m = {
            "name": name,
            "description": description,
            "type": kind,
            "topic": "pitfalls" if kind == "pitfall" else "reference",
            "modified": "2026-11-22T09:00:00.000Z",
            "by": f"worker:{worker}",
            "body": body,
            "extra": {},
        }
        p = folder / f"{name}.md"
        p.write_text(memory_text(m), encoding="utf-8")
        return p

    def _start_run(self, dream: Dream):
        packed = dream.pack()
        with dream.state.lock():
            st = dream.state.load()
            st["run"] = {
                "id": packed.run_id,
                "status": "running",
                "trigger": "manual",
                "started_at": self.clock.now_sec(),
                "terminal": "t99",
                "profile": "light",
                "reviewed_to": packed.reviewed_to,
            }
            dream.state.save(st)
        return packed

    def _as_dream_helper(self):
        self.ctx.caller = _HelperCaller(
            helper_info={"of": f"pm-{self.slug}", "name": "auto-dream", "project": self.slug, "terminal": "t99"},
            writer=("helper", "helper:auto-dream"),
        )

    def _as_user(self):
        self.ctx.caller = _HelperCaller(helper_info=None, writer=("user", "user"))


class TestProtectedAndPack(DreamTestBase):
    def test_01_protected_rules(self):
        # Personal layer
        p_path = self._write_mem("personal-ref", kind="reference", by="worker:t1", personal=True)
        self.assertTrue(protected(read_memory(p_path)))
        self.assertTrue(protected({"name": "x", "type": "pitfall", "by": "worker:t1"}, personal=True))

        # Protected types: user, feedback, project
        for kind in ("user", "feedback", "project"):
            path = self._write_mem(f"type-{kind}", kind=kind, by="worker:t1")
            self.assertTrue(protected(read_memory(path)), kind)

        # Quote present
        q_path = self._write_mem("quoted-pitfall", kind="pitfall", by="worker:t1", quote="always do X")
        self.assertTrue(protected(read_memory(q_path)))

        # Protected authors: pm, user, claude-code, empty
        for author in ("pm", "user", "claude-code", ""):
            path = self._write_mem(f"by-{author or 'empty'}", kind="pitfall", by=author)
            self.assertTrue(protected(read_memory(path)), repr(author))

        # Last memory event by user or pm
        w_path = self._write_mem("worker-pitfall", kind="pitfall", by="worker:x")
        w_mem = read_memory(w_path)
        self.assertTrue(protected(w_mem, "user"))
        self.assertTrue(protected(w_mem, "pm"))

        # Eligible: worker:x pitfall / reference / helper / session / dream
        self.assertEqual(protected(w_mem, ""), "")
        self.assertEqual(protected(w_mem, "worker:x"), "")
        self.assertEqual(protected(w_mem, "dream"), "")
        for by in ("worker:x", "helper:h1", "session:s1", "dream"):
            r_path = self._write_mem(f"ok-{by.replace(':', '-')}", kind="reference", by=by)
            self.assertEqual(protected(read_memory(r_path), ""), "")

    def test_02_pack_filtering_order_cap_and_manifest(self):
        # Protected entries must never appear anywhere in pack.md
        self._write_mem("secret-decision", kind="project", by="pm", description="Secret product decision")
        self._write_mem("user-rule", kind="feedback", by="pm", quote="never do Y", description="User rule")
        self._write_mem("human-edited", kind="pitfall", by="worker:a", description="Edited by user")
        Conversation(self.ctx, self.repo).record(
            "memory", layer="project", action="edit", name="human-edited", by="user"
        )
        self._write_mem("personal-note", kind="reference", by="worker:a", personal=True, description="Personal only")

        # 45 eligible pitfalls with distinct timestamps
        for i in range(45):
            day = 1 + (i // 24)
            hour = i % 24
            self._write_mem(
                f"pit-{i:02d}",
                kind="pitfall",
                by="worker:w1",
                modified=f"2026-11-{day:02d}T{hour:02d}:00:00.000Z",
                description=f"Pitfall number {i:02d}",
                body=f"Body for pitfall {i:02d} with ```code``` block",
            )

        # Active worker candidate must be excluded; finished worker candidate included
        ledger = Ledger(self.ctx)
        ledger.save({
            "id": "t-active",
            "name": "active-worker",
            "status": "in_progress",
            "repo": str(self.repo),
        })
        ledger.save({
            "id": "t-done",
            "name": "done-worker",
            "status": "done",
            "repo": str(self.repo),
        })
        self._write_candidate("active-worker", "in-flight-note", description="Still working")
        self._write_candidate("done-worker", "finished-note", description="Finished worker finding")

        dream = Dream(self.ctx, self.repo)
        packed = dream.pack()

        pack_text = packed.pack_path.read_text(encoding="utf-8")
        run_data = json.loads(packed.run_path.read_text(encoding="utf-8"))

        # Protected items absent from all sections
        for forbidden in ("secret-decision", "user-rule", "human-edited", "personal-note", "in-flight-note"):
            self.assertNotIn(forbidden, pack_text)

        # Section A has 40 oldest entries, oldest first
        self.assertEqual(packed.dirty_count, 40)
        self.assertEqual(run_data["dirty"], [f"pit-{i:02d}" for i in range(40)])
        self.assertLess(pack_text.index("### pit-00"), pack_text.index("### pit-39"))
        self.assertNotIn("### pit-40", pack_text)

        # Catalog & run.json entries cover all 45 eligible entries
        self.assertEqual(packed.eligible_count, 45)
        self.assertEqual(len(run_data["entries"]), 45)
        self.assertIn("pit-44", run_data["entries"])
        self.assertIn("- pit-44 (pitfall):", pack_text)

        # Only finished worker's candidate is included
        self.assertEqual(list(run_data["candidates"].keys()), ["done-worker/finished-note.md"])
        self.assertIn("### done-worker/finished-note", pack_text)


class TestApplyPermissionsAndOps(DreamTestBase):
    def test_03_apply_caller_run_status_and_dry_run(self):
        self._write_mem("pit-a", description="First pitfall")
        self._write_mem("pit-b", description="Second pitfall")
        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        plan = json.dumps({
            "run": packed.run_id,
            "ops": [{
                "op": "merge",
                "into": "pit-a",
                "sources": ["pit-a", "pit-b"],
                "description": "Combined pitfall",
                "why": "duplicate",
            }],
        })

        # Non-helper caller refused
        self._as_user()
        with self.assertRaises(Refused):
            dream.apply(packed.run_id, plan)
        self.assertTrue((self.layer.dir / "pit-b.md").exists())

        # Wrong helper name refused
        self.ctx.caller = _HelperCaller(
            helper_info={"of": f"pm-{self.slug}", "name": "other-helper", "project": self.slug, "terminal": "t99"}
        )
        with self.assertRaises(Refused):
            dream.apply(packed.run_id, plan)

        # Wrong project refused
        self.ctx.caller = _HelperCaller(
            helper_info={"of": "pm-other-proj", "name": "auto-dream", "project": "other-proj", "terminal": "t99"}
        )
        with self.assertRaises(Refused):
            dream.apply(packed.run_id, plan)

        # dry-run succeeds for any caller without mutating disk
        self._as_user()
        dry = dream.apply(packed.run_id, plan, dry_run=True)
        self.assertTrue(dry.dry_run)
        self.assertEqual(dry.summary["merged"], 1)
        self.assertTrue((self.layer.dir / "pit-b.md").exists())
        self.assertFalse((dream.state.run_dir(packed.run_id) / "receipt.json").exists())

        # Mismatched run id in plan -> code 2, state still running
        self._as_dream_helper()
        bad_plan = json.dumps({"run": "wrong-run-id", "ops": []})
        with self.assertRaises(Refused) as cm:
            dream.apply(packed.run_id, bad_plan)
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(dream.state.load()["run"]["status"], "running")

        # run.status != running -> refused
        with dream.state.lock():
            st = dream.state.load()
            st["run"]["status"] = "applied"
            dream.state.save(st)
        with self.assertRaises(Refused):
            dream.apply(packed.run_id, plan)
        self.assertTrue((self.layer.dir / "pit-b.md").exists())

    def test_04_merge_and_recall_redirect(self):
        self._write_mem(
            "pit-keep",
            description="Keep this memory",
            body="Original body of pit-keep.",
            verified="cmd-1",
            checked="2026-11-18",
            modified="2026-11-18T10:00:00.000Z",
        )
        self._write_mem(
            "pit-old",
            description="Duplicate memory",
            body="Verbatim body of pit-old.",
            verified="cmd-2",
            checked="2026-11-10",
            modified="2026-11-15T12:00:00.000Z",
        )
        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        self._as_dream_helper()

        plan = json.dumps({
            "run": packed.run_id,
            "ops": [{
                "op": "merge",
                "into": "pit-keep",
                "sources": ["pit-keep", "pit-old"],
                "description": "Merged description for pit-keep",
                "why": "same trap",
            }],
        })
        res = dream.apply(packed.run_id, plan)
        self.assertEqual(res.summary["merged"], 1)
        self.assertEqual(res.summary["removed"], 1)

        # Surviving entry checks
        kept = read_memory(self.layer.dir / "pit-keep.md")
        self.assertIsNotNone(kept)
        self.assertEqual(kept["by"], "dream")
        self.assertEqual(kept["description"], "Merged description for pit-keep")
        self.assertIn("Original body of pit-keep.", kept["body"])
        self.assertIn("Verbatim body of pit-old.", kept["body"])
        self.assertIn("## Merged from pit-old (worker:t1, 2026-11-15)", kept["body"])
        self.assertEqual(kept["verified"], "cmd-1 | cmd-2")
        self.assertEqual(kept["checked"], "2026-11-10")

        # Removed file gone, history kept with merged_into
        self.assertFalse((self.layer.dir / "pit-old.md").exists())
        hist = self.layer.history("pit-old")
        self.assertEqual(len(hist), 1)
        hist_mem = read_memory(hist[0]["file"])
        self.assertEqual(hist_mem["extra"].get("merged_into"), "pit-keep")

        # MEMORY.md rebuilt
        self.assertTrue((self.layer.dir / "MEMORY.md").is_file())

        # pm.py recall pit-old redirects to pit-keep
        code, stdout, stderr = run_main(self.ctx, "recall", "pit-old", "--repo", str(self.repo))
        self.assertEqual(code, 0, stderr)
        self.assertIn("pit-old", stdout)
        self.assertIn("pit-keep", stdout)
        self.assertIn("Merged description for pit-keep", stdout)

    def test_05_merge_refusals(self):
        self._write_mem("p1", kind="pitfall", description="Pitfall one")
        self._write_mem("p2", kind="pitfall", description="Pitfall two")
        self._write_mem("p3", kind="pitfall", description="Pitfall three")
        self._write_mem("p4", kind="pitfall", description="Pitfall four")
        self._write_mem("p5", kind="pitfall", description="Pitfall five")
        self._write_mem("p6", kind="pitfall", description="Pitfall six")
        self._write_mem("r1", kind="reference", description="Reference one")
        self._write_mem("prot", kind="project", by="pm", description="Protected decision")
        self._write_mem("stale-a", kind="pitfall", description="Stale A")
        self._write_mem("stale-b", kind="pitfall", description="Stale B")

        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)

        # Mutate stale-b after pack so its version changes
        stale_b_path = self.layer.dir / "stale-b.md"
        stale_b_path.write_text(stale_b_path.read_text(encoding="utf-8") + "\nextra line\n", encoding="utf-8")

        self._as_dream_helper()
        plan = json.dumps({
            "run": packed.run_id,
            "ops": [
                # Protected source
                {"op": "merge", "into": "p1", "sources": ["p1", "prot"], "description": "bad1"},
                # Mixed types
                {"op": "merge", "into": "p2", "sources": ["p2", "r1"], "description": "bad2"},
                # Changed since pack
                {"op": "merge", "into": "stale-a", "sources": ["stale-a", "stale-b"], "description": "bad3"},
                # More than 5 sources
                {"op": "merge", "into": "p3", "sources": ["p3", "p4", "p5", "p6", "p1", "p2"], "description": "bad4"},
                # into not in sources
                {"op": "merge", "into": "p5", "sources": ["p3", "p4"], "description": "bad5"},
            ],
        })
        res = dream.apply(packed.run_id, plan)
        self.assertEqual(res.summary["merged"], 0)
        self.assertEqual(res.summary["refused"], 5)
        self.assertTrue(all(op["status"] == "refused" for op in res.ops))

    def test_06_forget_path_verification(self):
        # Stub git ls-files on ctx.git
        tracked = [
            "mods/pm-dash/skill/scripts/tests/fakes.py",
            "mods/pm-dash/skill/scripts/pmlib/store.py",
        ]
        self.ctx.git.git_results[(str(self.repo), "ls-files")] = "\n".join(tracked)

        # 1. Deleted relative path -> allowed
        self._write_mem(
            "gone-file",
            description="Workaround for legacy/deleted_module.py",
            body="See legacy/deleted_module.py for old shim.",
        )
        # 2. Suffix of a tracked file (tests/fakes.py) -> refused
        self._write_mem(
            "suffix-match",
            description="Trap in tests/fakes.py",
            body="tests/fakes.py stubs git",
        )
        # 3. Bare filename (fakes.py) -> refused
        self._write_mem(
            "bare-file",
            description="See old_helper.py and legacy/removed_one.py",
            body="Mentions bare filename old_helper.py",
        )
        # 4. Tilde path (~/.claude/settings.json) -> refused
        self._write_mem(
            "tilde-file",
            description="Config in ~/.claude/settings.json and legacy/removed_two.py",
            body="Tilde path cannot be verified",
        )
        # 5. No path at all -> refused
        self._write_mem(
            "no-path",
            description="General advice with no files mentioned",
            body="Just remember to be careful.",
            verified="manual check",
        )

        # Quick unit check on extract_repo_paths
        rel, unv = extract_repo_paths("Check ~/.claude/foo.json and bare.py and sub/ok.py")
        self.assertEqual(rel, ["sub/ok.py"])
        self.assertIn("~/.claude/foo.json", unv)
        self.assertIn("bare.py", unv)

        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        self._as_dream_helper()
        plan = json.dumps({
            "run": packed.run_id,
            "ops": [
                {"op": "forget", "name": "gone-file", "why": "deleted"},
                {"op": "forget", "name": "suffix-match", "why": "suffix"},
                {"op": "forget", "name": "bare-file", "why": "bare"},
                {"op": "forget", "name": "tilde-file", "why": "tilde"},
                {"op": "forget", "name": "no-path", "why": "none"},
            ],
        })
        res = dream.apply(packed.run_id, plan)
        self.assertEqual(res.summary["forgotten"], 1)
        self.assertEqual(res.summary["refused"], 4)
        self.assertFalse((self.layer.dir / "gone-file.md").exists())
        self.assertEqual(len(self.layer.history("gone-file")), 1)
        for kept in ("suffix-match", "bare-file", "tilde-file", "no-path"):
            self.assertTrue((self.layer.dir / f"{kept}.md").exists(), kept)

    def test_07_adopt_rules_and_refusals(self):
        # Existing memory for similarity and same-name checks
        existing_same = self._write_mem(
            "existing-name",
            kind="project",
            by="pm",
            description="Protected decision that must not be overwritten",
            body="Original protected body.",
        )
        existing_same_bytes = existing_same.read_bytes()
        self._write_mem(
            "similar-existing",
            kind="pitfall",
            by="worker:w0",
            description="SQLite busy timeout needs five seconds on Windows CI",
        )

        # Candidates
        self._write_candidate(
            "w1",
            "new-pitfall",
            description="Unrelated distinct pitfall about subprocess env vars",
            body="Strip PM_HELPER_OF before spawning child.",
        )
        self._write_candidate(
            "w1",
            "bad-type",
            description="Trying to adopt as feedback",
        )
        self._write_candidate(
            "w1",
            "near-dup",
            description="SQLite busy timeout needs five seconds on Windows CI!",
        )
        self._write_candidate(
            "w1",
            "existing-name",
            description="Completely different text with colliding name",
        )

        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        self._as_dream_helper()

        plan = json.dumps({
            "run": packed.run_id,
            "ops": [
                {
                    "op": "adopt",
                    "candidate": "w1/new-pitfall",
                    "type": "pitfall",
                    "verified": "MODEL_INJECTED_VERIFIED",
                },
                {
                    "op": "adopt",
                    "candidate": "w1/bad-type",
                    "type": "feedback",
                },
                {
                    "op": "adopt",
                    "candidate": "w1/near-dup",
                    "type": "pitfall",
                },
                {
                    "op": "adopt",
                    "candidate": "w1/existing-name",
                    "type": "pitfall",
                },
            ],
        })
        res = dream.apply(packed.run_id, plan)
        self.assertEqual(res.summary["adopted"], 1)
        self.assertEqual(res.summary["refused"], 3)

        # Adopted entry has code-generated verified, never model text
        adopted = read_memory(self.layer.dir / "new-pitfall.md")
        self.assertIsNotNone(adopted)
        self.assertEqual(
            adopted["verified"],
            f"worker w1's own session memory, adopted by dream {packed.run_id}",
        )
        self.assertNotIn("MODEL_INJECTED_VERIFIED", adopted["verified"])

        # Similar candidate still intact
        self.assertTrue((self.layer.dir / "candidates" / "w1" / "near-dup.md").is_file())

        # Same-name existing entry unchanged byte-for-byte
        self.assertEqual(existing_same.read_bytes(), existing_same_bytes)

    def test_08_caps_max_ops_and_max_removed(self):
        self.ctx.git.git_results[(str(self.repo), "ls-files")] = "keep/real.py"
        # 25 forgettable entries + 10 droppable candidates = 35 ops
        for i in range(25):
            self._write_mem(
                f"gone-{i:02d}",
                description=f"Old note for gone/file_{i:02d}.py",
                body=f"Refers to gone/file_{i:02d}.py",
                modified=f"2026-11-10T00:{i:02d}:00.000Z",
            )
        for i in range(10):
            self._write_candidate("wdrop", f"cand-{i:02d}", description=f"Candidate {i:02d}")

        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        self._as_dream_helper()

        ops = [
            {"op": "forget", "name": f"gone-{i:02d}", "why": "removed"} for i in range(25)
        ] + [
            {"op": "drop", "candidate": f"wdrop/cand-{i:02d}", "why": "noise"} for i in range(10)
        ]
        res = dream.apply(packed.run_id, json.dumps({"run": packed.run_id, "ops": ops}))

        # First 20 forgets succeed, 21-25 refused by MAX_REMOVED=20;
        # ops 26-30 (first 5 drops) succeed; ops 31-35 refused by MAX_OPS=30
        self.assertEqual(res.summary["forgotten"], 20)
        self.assertEqual(res.summary["dropped"], 5)
        self.assertEqual(res.summary["refused"], 10)
        self.assertIn("20", res.ops[20]["reason"])
        self.assertIn("30", res.ops[30]["reason"])

    def test_09_watermark_advances_even_when_all_refused_and_dream_by_not_pending(self):
        self._write_mem("p1", description="Entry 1", verified="manual", modified="2026-11-20T01:00:00.000Z")
        self._write_mem("p2", description="Entry 2", verified="manual", modified="2026-11-21T02:00:00.000Z")
        self._write_candidate("w1", "c1", description="Candidate 1")

        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        self._as_dream_helper()

        # Submit a plan whose single op is refused
        plan = json.dumps({
            "run": packed.run_id,
            "ops": [{"op": "forget", "name": "p1", "why": "no paths"}],
        })
        res = dream.apply(packed.run_id, plan)
        self.assertEqual(res.summary["refused"], 1)

        st = dream.state.load()
        self.assertEqual(st["reviewed_until"], "2026-11-21T02:00:00.000Z")
        self.assertIn("w1/c1.md", st["seen_candidates"])

        # No longer pending
        dirty, unseen = dream.pending()
        self.assertEqual(dirty, [])
        self.assertEqual(unseen, [])

        # A newer entry written by dream is not counted as pending
        self._write_mem("from-dream", by="dream", modified="2026-11-23T05:00:00.000Z", description="Dream output")
        dirty2, _ = dream.pending()
        self.assertEqual(dirty2, [])

    def test_10_and_11_undo_roundtrip_protection_skip_and_no_wake_events(self):
        self.ctx.git.git_results[(str(self.repo), "ls-files")] = "keep/real.py"

        p_keep = self._write_mem("m-keep", description="Merge survivor", body="Body keep", verified="v1")
        p_src = self._write_mem("m-src", description="Merge source", body="Body src", verified="v2")
        p_gone = self._write_mem("m-gone", description="Obsolete old/gone.py note", body="old/gone.py is gone")
        c_adopt = self._write_candidate("w1", "c-adopt", description="Distinct candidate to adopt", body="Adopt body")
        c_drop = self._write_candidate("w1", "c-drop", description="Candidate to drop", body="Drop body")

        before_keep = memory_text(read_memory(p_keep))
        before_src = memory_text(read_memory(p_src))
        before_gone = memory_text(read_memory(p_gone))
        before_adopt_cand = c_adopt.read_text(encoding="utf-8")
        before_drop_cand = c_drop.read_text(encoding="utf-8")

        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        self._as_dream_helper()

        plan = json.dumps({
            "run": packed.run_id,
            "ops": [
                {
                    "op": "merge",
                    "into": "m-keep",
                    "sources": ["m-keep", "m-src"],
                    "description": "Merged survivor",
                    "why": "dup",
                },
                {"op": "forget", "name": "m-gone", "why": "deleted"},
                {"op": "adopt", "candidate": "w1/c-adopt", "type": "pitfall"},
                {"op": "drop", "candidate": "w1/c-drop", "why": "noise"},
            ],
            "flags": [{"name": "m-keep", "note": "double check"}],
        })
        res = dream.apply(packed.run_id, plan)
        self.assertEqual(res.summary["merged"], 1)
        self.assertEqual(res.summary["forgotten"], 1)
        self.assertEqual(res.summary["adopted"], 1)
        self.assertEqual(res.summary["dropped"], 1)

        # Criterion 11: no memory event carries wake=True
        events = Conversation(self.ctx, self.repo).events()
        mem_events = [e for e in events if e.get("type") == "memory"]
        self.assertTrue(len(mem_events) >= 3)
        self.assertFalse(any(e.get("wake") is True for e in mem_events))

        # Undo as user
        self._as_user()
        undone = dream.undo(packed.run_id)
        self.assertEqual(undone.skipped, [])
        self.assertEqual(len(undone.restored), 4)

        # Byte-for-byte identical via memory_text
        self.assertEqual(memory_text(read_memory(p_keep)), before_keep)
        self.assertEqual(memory_text(read_memory(p_src)), before_src)
        self.assertEqual(memory_text(read_memory(p_gone)), before_gone)
        self.assertFalse((self.layer.dir / "c-adopt.md").exists())
        self.assertEqual(c_adopt.read_text(encoding="utf-8"), before_adopt_cand)
        self.assertEqual(c_drop.read_text(encoding="utf-8"), before_drop_cand)

        # Restored entries are now protected (last memory event by user)
        last_by = dream._last_by_map()
        for name in ("m-keep", "m-src", "m-gone"):
            m = read_memory(self.layer.dir / f"{name}.md")
            self.assertTrue(protected(m, last_by.get(name, "")), name)

        # Still no memory event with wake=True after undo
        all_mem_events = [e for e in Conversation(self.ctx, self.repo).events() if e.get("type") == "memory"]
        self.assertFalse(any(e.get("wake") is True for e in all_mem_events))

    def test_10b_undo_skips_modified_survivor(self):
        p_keep = self._write_mem("s-keep", description="Keep me", body="Keep body")
        self._write_mem("s-src", description="Source me", body="Source body")
        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        self._as_dream_helper()

        plan = json.dumps({
            "run": packed.run_id,
            "ops": [{
                "op": "merge",
                "into": "s-keep",
                "sources": ["s-keep", "s-src"],
                "description": "Merged",
            }],
        })
        dream.apply(packed.run_id, plan)

        # User edits surviving entry after dream
        p_keep.write_text(p_keep.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")

        self._as_user()
        undone = dream.undo(packed.run_id)
        self.assertEqual(undone.restored, [])
        self.assertEqual(len(undone.skipped), 1)
        self.assertIn("modified", undone.skipped[0][1])


class TestDreamCli(DreamTestBase):
    def test_cli_status_run_dry_run_apply_and_undo(self):
        self._write_mem("cli-a", description="CLI entry A", body="Body A")
        self._write_mem("cli-b", description="CLI entry B", body="Body B")

        # status --json
        code, stdout, stderr = run_main(self.ctx, "dream", "status", "--repo", str(self.repo), "--json")
        self.assertEqual(code, 0, stderr)
        data = json.loads(stdout)
        self.assertEqual(data["pending"], 2)
        self.assertFalse(data["running"])
        self.assertFalse(data["auto"])

        # run --dry-run
        code, stdout, stderr = run_main(self.ctx, "dream", "run", "--dry-run", "--repo", str(self.repo))
        self.assertEqual(code, 0, stderr)
        self.assertIn("pack.md", stdout)

        # apply --dry-run via --stdin
        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        plan = json.dumps({
            "run": packed.run_id,
            "ops": [{
                "op": "merge",
                "into": "cli-a",
                "sources": ["cli-a", "cli-b"],
                "description": "Merged CLI",
            }],
        })
        code, stdout, stderr = run_main(
            self.ctx, "dream", "apply", "--run", packed.run_id, "--stdin", "--dry-run", "--repo", str(self.repo),
            stdin=plan,
        )
        self.assertEqual(code, 0, stderr)
        self.assertIn("applied", stdout)
        self.assertTrue((self.layer.dir / "cli-b.md").exists())

        # apply real via --plan file as dream helper
        plan_file = self.tmp / "plan.json"
        plan_file.write_text(plan, encoding="utf-8")
        self._as_dream_helper()
        code, stdout, stderr = run_main(
            self.ctx, "dream", "apply", "--run", packed.run_id, "--plan", str(plan_file), "--repo", str(self.repo)
        )
        self.assertEqual(code, 0, stderr)
        self.assertFalse((self.layer.dir / "cli-b.md").exists())

        # undo via CLI as user
        self._as_user()
        code, stdout, stderr = run_main(self.ctx, "dream", "undo", "--repo", str(self.repo))
        self.assertEqual(code, 0, stderr)
        self.assertIn("restored", stdout)
        self.assertTrue((self.layer.dir / "cli-b.md").exists())


class TestDreamRunHelperLaunch(DreamTestBase):
    def setUp(self):
        super().setUp()
        self.hc = FakeHc(clock=self.clock)
        self.procs = FakeProcs(self.tmp)
        self.pm_term = "t10"
        self.hc.terminals[self.pm_term] = {
            "address": self.pm_term,
            "name": f"pm-{self.slug}",
            "state": "live",
            "labels": {"pm": self.repo.name},
            "status": {"state": "idle"},
            "turn": 1,
        }
        self.ctx = make_ctx(
            self.tmp,
            pane="",
            hc_terminal="",
            hc=self.hc,
            clock=self.clock,
            procs=self.procs,
        )
        self.ctx.store.change_registration(self.slug, lambda _: {
            "name": f"pm-{self.slug}",
            "project": self.repo.name,
            "repo": str(self.repo),
            "runtime": "hc",
            "terminal": self.pm_term,
            "pane": f"hc:{self.pm_term}",
            "claimed": self.clock.now(),
        })
        self.layer = MemoryLayer(self.ctx, self.repo)
        self.layer.dir.mkdir(parents=True, exist_ok=True)

    def test_dream_run_nothing_pending_does_not_start_helper(self):
        code, stdout, stderr = run_main(self.ctx, "dream", "run", "--repo", str(self.repo))
        self.assertEqual(code, 0, stderr)
        self.assertIn("nothing pending", stdout.lower())
        self.assertEqual(helper_entries(self.ctx.store.registration(self.slug)), [])
        self.assertIsNone(Dream(self.ctx, self.repo).state.load()["run"])

    def test_dream_run_launches_quiet_parent_pm_helper_and_refuses_duplicate(self):
        self._write_mem("pit-1", description="First pitfall to consolidate")
        self._write_mem("pit-2", description="Second pitfall to consolidate")

        placements: list[list[str]] = []
        orig_start = self.hc.start_terminal

        def _spy_start(name, cwd, argv, placement=(), labels=(), env=None):
            placements.append(list(placement))
            return orig_start(name, cwd, argv, placement=placement, labels=labels, env=env)

        self.hc.start_terminal = _spy_start  # type: ignore[method-assign]

        code, stdout, stderr = run_main(self.ctx, "dream", "run", "--repo", str(self.repo))
        self.assertEqual(code, 0, stderr)
        self.assertIn("auto-dream", stdout)
        self.assertEqual(placements, [["--parent", self.pm_term, "--no-notify"]])

        helpers = helper_entries(self.ctx.store.registration(self.slug))
        self.assertEqual(len(helpers), 1)
        h = helpers[0]
        self.assertEqual(h["name"], "auto-dream")
        self.assertTrue(h.get("quiet"))
        self.assertEqual(h["parent"], self.pm_term)
        self.assertEqual(h["mode"], "readonly")

        st = Dream(self.ctx, self.repo).state.load()
        self.assertIsNotNone(st["run"])
        self.assertEqual(st["run"]["status"], "running")
        self.assertEqual(st["run"]["terminal"], h["terminal"])
        self.assertEqual(st["run"]["trigger"], "manual")
        self.assertEqual(st["failures"], 0)

        # Saved helper brief includes both pack data and DREAM_PROMPT instructions.
        result_path = Path(h["result"])
        brief_path = result_path.parent / f".{result_path.stem}-brief.md"
        brief_text = brief_path.read_text(encoding="utf-8")
        self.assertIn("pit-1", brief_text)
        self.assertIn(f"dream apply --run {st['run']['id']} --stdin", brief_text)
        self.assertIn("helper done", brief_text)

        # Running again while auto-dream is already running is refused without starting a second helper.
        code2, _, stderr2 = run_main(self.ctx, "dream", "run", "--repo", str(self.repo))
        self.assertNotEqual(code2, 0)
        self.assertIn("already running", f"{code2} {stderr2}".lower())
        self.assertEqual(len(helper_entries(self.ctx.store.registration(self.slug))), 1)

    def test_dream_run_refused_by_helpers_clears_run_sets_retry_at_without_incrementing_failures(self):
        self._write_mem("pit-refuse", description="Will hit refused start")
        # Make PM terminal offline so Helpers.start raises Refused.
        self.hc.terminals[self.pm_term]["state"] = "exited"

        code, _, stderr = run_main(self.ctx, "dream", "run", "--repo", str(self.repo))
        self.assertNotEqual(code, 0)
        self.assertIn("not online", f"{code} {stderr}".lower())

        st = Dream(self.ctx, self.repo).state.load()
        self.assertIsNone(st["run"])
        self.assertEqual(st["retry_at"], "2026-11-24 11:00:00")
        self.assertEqual(st["failures"], 0)


class TestDreamWatcher(DreamTestBase):
    def setUp(self):
        super().setUp()
        self.clock = FakeClock("2026-11-24 10:00:00", mono=1000.0)
        self.hc = FakeHc(clock=self.clock)
        self.procs = FakeProcs(self.tmp)
        self.pm_term = "t10"
        self.hc.terminals[self.pm_term] = {
            "address": self.pm_term,
            "name": f"pm-{self.slug}",
            "state": "live",
            "labels": {"pm": self.repo.name},
            "status": {"state": "idle"},
            "turn": 1,
        }
        self.ctx = make_ctx(
            self.tmp,
            pane="",
            hc_terminal="",
            hc=self.hc,
            clock=self.clock,
            procs=self.procs,
        )
        self.ctx.store.change_registration(self.slug, lambda _: {
            "name": f"pm-{self.slug}",
            "project": self.repo.name,
            "repo": str(self.repo),
            "runtime": "hc",
            "terminal": self.pm_term,
            "pane": f"hc:{self.pm_term}",
            "claimed": self.clock.now(),
        })
        self.layer = MemoryLayer(self.ctx, self.repo)
        self.layer.dir.mkdir(parents=True, exist_ok=True)

    def _set_dream_cfg(self, dream_cfg: dict | None) -> None:
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        payload = {} if dream_cfg is None else {"memory": {"dream": dream_cfg}}
        self.ctx.home.config.write_text(json.dumps(payload), encoding="utf-8")

    def _mark_pm_idle(self) -> None:
        tracker = TurnTracker(self.ctx, self.repo)
        tracker.begin_turn(terminal=self.pm_term, agent_kind="claude", cause="user", from_hook=True)
        tracker.end_turn()

    def _seed_pending(self, count: int = 8, *, modified: str = "2026-11-23T10:00:00.000Z") -> None:
        for i in range(count):
            self._write_mem(
                f"pit-{i:02d}",
                description=f"Pending pitfall {i:02d}",
                modified=modified,
            )

    def test_01_auto_default_or_false_skips_memory_dir_and_never_spawns(self):
        from unittest import mock

        self._seed_pending(10)
        self._mark_pm_idle()

        for cfg in (None, {"auto": False}):
            self._set_dream_cfg(cfg)
            stops: dict = {}
            with mock.patch.object(MemoryLayer, "memories", side_effect=AssertionError("must not read memory dir")):
                wait = DreamWatcher(self.ctx).look(str(self.repo), stops, {})
            self.assertEqual(wait, 600.0)
            self.assertEqual(self.procs.spawned, [])

    def test_02_each_of_six_gates_blocks_with_spec_wait_and_no_spawn(self):
        self._seed_pending(8)
        self._mark_pm_idle()

        # Gate 1: auto disabled -> 600s
        self._set_dream_cfg({"auto": False})
        self.assertEqual(DreamWatcher(self.ctx).look(str(self.repo), {}, {}), 600.0)
        self.assertEqual(self.procs.spawned, [])

        # Enable auto for gates 2..6
        self._set_dream_cfg({"auto": True, "min_hours": 24, "min_new": 8, "max_wait_days": 7, "timeout": 900})
        dream = Dream(self.ctx, self.repo)

        # Gate 2: failures >= 3 -> 3600s
        st = dream.state.load()
        st["failures"] = 3
        dream.state.save(st)
        self.assertEqual(DreamWatcher(self.ctx).look(str(self.repo), {}, {}), 3600.0)
        self.assertEqual(self.procs.spawned, [])

        # Gate 3: active running run (within timeout + 120) -> 300s
        st = dream.state.load()
        st["failures"] = 0
        st["run"] = {
            "id": "20261124-095500",
            "status": "running",
            "trigger": "auto",
            "started_at": "2026-11-24 09:55:00",
        }
        dream.state.save(st)
        self.assertEqual(DreamWatcher(self.ctx).look(str(self.repo), {}, {}), 300.0)
        self.assertEqual(self.procs.spawned, [])

        # Gate 4a: cooldown since last_attempt_at -> remaining seconds until min_hours
        st["run"] = None
        st["last_attempt_at"] = "2026-11-24 04:00:00"  # 6h ago -> 18h (64800s) left
        st["retry_at"] = ""
        dream.state.save(st)
        self.assertEqual(DreamWatcher(self.ctx).look(str(self.repo), {}, {}), 18 * 3600.0)
        self.assertEqual(self.procs.spawned, [])

        # Gate 4b: retry_at overrides last_attempt_at -> remaining seconds until retry_at
        st["retry_at"] = "2026-11-24 10:30:00"  # 1800s left
        dream.state.save(st)
        self.assertEqual(DreamWatcher(self.ctx).look(str(self.repo), {}, {}), 1800.0)
        self.assertEqual(self.procs.spawned, [])

        # Gate 5: PM turn still working -> 120s
        st["last_attempt_at"] = "2026-11-22 00:00:00"
        st["retry_at"] = ""
        dream.state.save(st)
        TurnTracker(self.ctx, self.repo).begin_turn(terminal=self.pm_term, agent_kind="claude", cause="user", from_hook=True)
        self.assertEqual(DreamWatcher(self.ctx).look(str(self.repo), {}, {}), 120.0)
        self.assertEqual(self.procs.spawned, [])

        # Gate 6: fewer than min_new and younger than max_wait_days -> 3600s
        self._mark_pm_idle()
        for f in list(self.layer.dir.glob("*.md")):
            f.unlink()
        self._seed_pending(3, modified="2026-11-22T10:00:00.000Z")  # 2 days old < 7
        self.assertEqual(DreamWatcher(self.ctx).look(str(self.repo), {}, {}), 3600.0)
        self.assertEqual(self.procs.spawned, [])

        # Gate 6 passes when oldest entry has waited >= max_wait_days even if count < min_new
        self._write_mem("old-pit", description="Old pitfall waiting 8 days", modified="2026-11-16T09:00:00.000Z")
        DreamWatcher(self.ctx).look(str(self.repo), {}, {})
        self.assertEqual(len(self.procs.spawned), 1)
        self.assertEqual(self.procs.spawned[0]["args"], ["dream", "run", "--auto", "--repo", str(self.repo)])

    def test_03_all_gates_pass_writes_last_attempt_before_spawn_and_dedups_next_look(self):
        self._set_dream_cfg({"auto": True})
        self._seed_pending(8)
        self._mark_pm_idle()

        dream = Dream(self.ctx, self.repo)
        attempt_seen_at_spawn: list[str] = []
        orig_spawn = self.procs.spawn_pm

        def _spy_spawn(args, *, env=None, cwd=None):
            attempt_seen_at_spawn.append(dream.state.load()["last_attempt_at"])
            return orig_spawn(args, env=env, cwd=cwd)

        self.procs.spawn_pm = _spy_spawn  # type: ignore[method-assign]

        stops: dict = {}
        DreamWatcher(self.ctx).look(str(self.repo), stops, {})

        self.assertEqual(len(self.procs.spawned), 1)
        self.assertEqual(self.procs.spawned[0]["args"], ["dream", "run", "--auto", "--repo", str(self.repo)])
        self.assertEqual(self.procs.spawned[0]["cwd"], str(self.repo))
        self.assertEqual(attempt_seen_at_spawn, ["2026-11-24 10:00:00"])

        # Immediate second look with same stops (O(1) throttle) does not re-spawn
        wait_same = DreamWatcher(self.ctx).look(str(self.repo), stops, {})
        self.assertGreater(wait_same, 0.0)
        self.assertEqual(len(self.procs.spawned), 1)

        # Immediate second look with fresh stops also blocked by persisted last_attempt_at cooldown
        wait_fresh = DreamWatcher(self.ctx).look(str(self.repo), {}, {})
        self.assertEqual(wait_fresh, 24 * 3600.0)
        self.assertEqual(len(self.procs.spawned), 1)

    def test_04_exceptions_inside_look_are_swallowed_and_return_600(self):
        from unittest import mock

        self._set_dream_cfg({"auto": True})
        with mock.patch("pmlib.memory.dream.dream_config", side_effect=RuntimeError("boom")):
            wait = DreamWatcher(self.ctx).look(str(self.repo), {}, {})
        self.assertEqual(wait, 600.0)
        self.assertEqual(self.procs.spawned, [])

        # Even a broken stops object is swallowed safely
        wait2 = DreamWatcher(self.ctx).look(str(self.repo), None, {})  # type: ignore[arg-type]
        self.assertEqual(wait2, 600.0)

    def test_05_timed_out_run_increments_failures_caps_at_3_and_manual_run_recovers(self):
        self._set_dream_cfg({"auto": True, "timeout": 900, "min_hours": 1, "min_new": 2})
        self._seed_pending(4)
        self._mark_pm_idle()

        dream = Dream(self.ctx, self.repo)
        # Seed a run started 1020s ago (timeout 900 + 120 grace) with failures already at 2
        st = dream.state.load()
        st["failures"] = 2
        st["last_attempt_at"] = "2026-11-24 08:00:00"
        st["run"] = {
            "id": "20261124-094300",
            "status": "running",
            "trigger": "auto",
            "started_at": "2026-11-24 09:43:00",  # 17 min = 1020s ago
        }
        dream.state.save(st)

        # First look marks the timed-out run failed and bumps failures to 3 without spawning
        wait = DreamWatcher(self.ctx).look(str(self.repo), {}, {})
        self.assertEqual(wait, 3600.0)
        self.assertEqual(self.procs.spawned, [])
        st_after = dream.state.load()
        self.assertEqual(st_after["run"]["status"], "failed")
        self.assertEqual(st_after["failures"], 3)

        # Subsequent looks stay blocked at gate 2 (failures == 3)
        self.clock.advance(7200)
        self.assertEqual(DreamWatcher(self.ctx).look(str(self.repo), {}, {}), 3600.0)
        self.assertEqual(self.procs.spawned, [])

        # A successful manual run + apply resets failures back to 0
        code, _, stderr = run_main(self.ctx, "dream", "run", "--repo", str(self.repo))
        self.assertEqual(code, 0, stderr)
        run_id = dream.state.load()["run"]["id"]
        self._as_dream_helper()
        dream.apply(run_id, json.dumps({"run": run_id, "ops": []}))
        self.assertEqual(dream.state.load()["failures"], 0)

        # Add fresh pending entries and advance past cooldown -> auto trigger recovers!
        self.procs.spawned.clear()
        self.clock.advance(7200)
        self._write_mem("pit-new-1", description="Fresh pitfall 1", modified="2026-11-24T13:00:00.000Z")
        self._write_mem("pit-new-2", description="Fresh pitfall 2", modified="2026-11-24T13:05:00.000Z")
        DreamWatcher(self.ctx).look(str(self.repo), {}, {})
        self.assertEqual(len(self.procs.spawned), 1)
        self.assertEqual(self.procs.spawned[0]["args"], ["dream", "run", "--auto", "--repo", str(self.repo)])

    def test_06_config_invalid_numbers_fall_back_to_defaults(self):
        self._set_dream_cfg({
            "auto": True,
            "profile": "   ",
            "min_hours": -5,
            "min_new": 0,
            "max_wait_days": "seven",
            "timeout": True,
        })
        cfg = dream_config(self.ctx)
        self.assertTrue(cfg["auto"])
        self.assertEqual(cfg["profile"], "light")
        self.assertEqual(cfg["min_hours"], 24)
        self.assertEqual(cfg["min_new"], 8)
        self.assertEqual(cfg["max_wait_days"], 7)
        self.assertEqual(cfg["timeout"], 900)


class TestRealCallerAndEdgeCases(DreamTestBase):
    def setUp(self):
        super().setUp()
        self.hc = FakeHc(clock=self.clock)
        self.procs = FakeProcs(self.tmp)
        self.pm_term = "t10"
        self.worker_term = "t20"
        self.other_helper_term = "t21"
        self.task_id = f"{self.slug}-work"
        self.hc.terminals[self.pm_term] = {
            "address": self.pm_term,
            "name": f"pm-{self.slug}",
            "state": "live",
            "labels": {"pm": self.repo.name},
            "status": {"state": "idle"},
            "turn": 1,
        }
        self.hc.terminals[self.worker_term] = {
            "address": self.worker_term,
            "name": "worker-1",
            "state": "live",
            "labels": {"task": self.task_id},
            "status": {"state": "working"},
            "turn": 1,
        }
        self.hc.terminals[self.other_helper_term] = {
            "address": self.other_helper_term,
            "name": "h-triage",
            "state": "live",
            "labels": {
                "helper.of": f"pm-{self.slug}",
                "helper": "triage",
                "helper.project": self.slug,
            },
            "status": {"state": "working"},
            "turn": 1,
        }
        self.ctx = self._ctx_for("")
        self.ctx.store.change_registration(self.slug, lambda _: {
            "name": f"pm-{self.slug}",
            "project": self.repo.name,
            "repo": str(self.repo),
            "runtime": "hc",
            "terminal": self.pm_term,
            "pane": f"hc:{self.pm_term}",
            "claimed": self.clock.now(),
        })
        self.ctx.store.change_task(self.task_id, lambda _: {
            "id": self.task_id,
            "title": "Feature work",
            "project": self.repo.name,
            "repo": str(self.repo),
            "status": "in_progress",
            "owner": "pm",
            "base": "main",
            "pane": f"hc:{self.worker_term}",
            "worktree": str(self.repo),
            "created": self.clock.now(),
            "updated": self.clock.now(),
            "log": [],
            "dispatched": True,
        })
        self.layer = MemoryLayer(self.ctx, self.repo)
        self.layer.dir.mkdir(parents=True, exist_ok=True)

    def _ctx_for(self, term: str, *, env: dict[str, str] | None = None):
        return make_ctx(
            self.tmp,
            pane=f"hc:{term}" if term else "",
            hc_terminal=term,
            hc=self.hc,
            clock=self.clock,
            procs=self.procs,
            env=env,
        )

    def test_real_caller_permissions_over_hc_labels_and_env(self):
        self._write_mem("real-a", description="First real-caller pitfall", body="Body real A")
        self._write_mem("real-b", description="Second real-caller pitfall", body="Body real B")

        cli_ctx = self._ctx_for("")
        pm_ctx = self._ctx_for(self.pm_term)
        worker_ctx = self._ctx_for(self.worker_term)
        other_helper_ctx = self._ctx_for(self.other_helper_term)

        # A task worker terminal cannot start PM's dream helper.
        w_code, _, w_err = run_main(worker_ctx, "dream", "run", "--repo", str(self.repo))
        self.assertNotEqual(w_code, 0)
        self.assertIn("worker", f"{w_code} {w_err}".lower())

        # Start dream run from bare CLI (as Deliverer or shell user does).
        code, _, stderr = run_main(cli_ctx, "dream", "run", "--repo", str(self.repo))
        self.assertEqual(code, 0, stderr)
        helpers = helper_entries(self.ctx.store.registration(self.slug))
        self.assertEqual(len(helpers), 1)
        hterm = helpers[0]["terminal"]
        h_labels = self.hc.terminals[hterm]["labels"]
        self.assertEqual(h_labels.get("helper.of"), f"pm-{self.slug}")
        self.assertEqual(h_labels.get("helper"), "auto-dream")
        self.assertEqual(h_labels.get("helper.project"), self.slug)

        run_id = Dream(self.ctx, self.repo).state.load()["run"]["id"]
        plan = json.dumps({
            "run": run_id,
            "ops": [{
                "op": "merge",
                "into": "real-a",
                "sources": ["real-a", "real-b"],
                "description": "Merged via real Caller",
            }],
        })

        # Non-dream-helper callers (CLI, PM, worker, another PM helper) are all refused via real Caller.
        for bad_ctx in (cli_ctx, pm_ctx, worker_ctx, other_helper_ctx):
            c_bad, _, _ = run_main(
                bad_ctx, "dream", "apply", "--run", run_id, "--stdin", "--repo", str(self.repo), stdin=plan
            )
            self.assertNotEqual(c_bad, 0)
        self.assertTrue((self.layer.dir / "real-b.md").exists())

        # The spawned auto-dream helper terminal is accepted via real Caller(ctx).
        dream_helper_ctx = self._ctx_for(hterm, env=self.hc.terminals[hterm].get("env") or {})
        c_ok, _, err_ok = run_main(
            dream_helper_ctx, "dream", "apply", "--run", run_id, "--stdin", "--repo", str(self.repo), stdin=plan
        )
        self.assertEqual(c_ok, 0, err_ok)
        self.assertFalse((self.layer.dir / "real-b.md").exists())

        # Worker and helper terminals cannot undo; PM terminal can undo via real Caller(ctx).
        for non_pm_ctx in (worker_ctx, dream_helper_ctx):
            u_bad, _, _ = run_main(non_pm_ctx, "dream", "undo", "--repo", str(self.repo))
            self.assertNotEqual(u_bad, 0)
        self.assertFalse((self.layer.dir / "real-b.md").exists())

        u_ok, _, u_err = run_main(pm_ctx, "dream", "undo", "--repo", str(self.repo))
        self.assertEqual(u_ok, 0, u_err)
        self.assertTrue((self.layer.dir / "real-b.md").exists())

        dream = Dream(self.ctx, self.repo)
        last_by = dream._last_by_map()
        for name in ("real-a", "real-b"):
            self.assertEqual(last_by.get(name), "pm")
            self.assertIn("pm", protected(read_memory(self.layer.dir / f"{name}.md"), last_by.get(name, "")))

    def test_pack_timestamp_ties_fence_escaping_byte_cap_and_run_dir_pruning(self):
        dream = Dream(self.ctx, self.repo)

        # Seed 22 old run directories; pack must prune to MAX_RUN_DIRS (20) total including the new run.
        for i in range(22):
            old_dir = dream.state.run_dir(f"20261101-0000{i:02d}")
            old_dir.mkdir(parents=True, exist_ok=True)
            (old_dir / "pack.md").write_text("old", encoding="utf-8")

        # 39 entries before cutoff, 3 entries tied on the 40th timestamp, and 2 newer entries.
        for i in range(39):
            self._write_mem(
                f"early-{i:02d}",
                modified=f"2026-11-01T00:{i:02d}:00.000Z",
                description=f"Early entry {i:02d}",
                body="Contains ````quad backticks```` inside body" if i == 0 else f"Body {i:02d}",
            )
        for j in range(3):
            self._write_mem(
                f"tied-{j}",
                modified="2026-11-02T00:00:00.000Z",
                description=f"Tied 40th entry {j}",
            )
        for k in range(2):
            self._write_mem(
                f"later-{k}",
                modified=f"2026-11-03T00:0{k}:00.000Z",
                description=f"Later entry {k}",
            )

        packed = dream.pack(run_id="20261124-100000")
        pack_text = packed.pack_path.read_text(encoding="utf-8")
        # All 39 early + all 3 tied = 42 in section A; 2 later entries deferred.
        self.assertEqual(packed.dirty_count, 42)
        for j in range(3):
            self.assertIn(f"### tied-{j}", pack_text)
        self.assertNotIn("### later-0", pack_text)
        # 4-backtick body is fenced with 5 backticks so untrusted body cannot break out of code block.
        self.assertIn("`````text\nContains ````quad backticks```` inside body\n`````", pack_text)

        run_dirs = [p.name for p in dream.state.root.iterdir() if p.is_dir()]
        self.assertLessEqual(len(run_dirs), 20)
        self.assertNotIn("20261101-000000", run_dirs)
        self.assertIn("20261124-100000", run_dirs)

        # Oversized bodies exceeding 120 KB are trimmed to stay within PACK_MAX_BYTES (120_000).
        big_body = "x" * 6000
        for i in range(30):
            self._write_mem(
                f"huge-{i:02d}",
                modified=f"2026-11-04T00:{i:02d}:00.000Z",
                description=f"Huge entry {i:02d} " + ("d" * 120),
                body=big_body,
            )
        for i in range(10):
            self._write_candidate("whuge", f"hcand-{i:02d}", description=f"Huge cand {i}", body=big_body)
        packed_big = dream.pack(run_id="20261124-100500")
        self.assertLessEqual(packed_big.bytes_size, 120_000)

    def test_plan_uniqueness_drop_refusals_secret_guards_untracked_disk_path_and_project_memory_cli(self):
        import subprocess
        from pmlib.gitrepo import GitRepo

        # 1. With real GitRepo on a non-git directory (`ls-files` -> None), forget must refuse safely.
        non_git_ctx = make_ctx(self.tmp, clock=self.clock, git=GitRepo())
        self._write_mem("unverified-git", description="Note on gone/mod.py", body="gone/mod.py")
        dream_nogit = Dream(non_git_ctx, self.repo)
        p0 = self._start_run(dream_nogit)
        non_git_ctx.caller = _HelperCaller(
            helper_info={"of": f"pm-{self.slug}", "name": "auto-dream", "project": self.slug, "terminal": "t99"},
            writer=("helper", "helper:auto-dream"),
        )
        r0 = dream_nogit.apply(p0.run_id, json.dumps({
            "run": p0.run_id,
            "ops": [{"op": "forget", "name": "unverified-git", "why": "deleted"}],
        }))
        self.assertEqual(r0.summary["forgotten"], 0)
        self.assertIn("ls-files", r0.ops[0]["reason"])
        self.assertTrue((self.layer.dir / "unverified-git.md").exists())

        # 1b. Real git repository with tracked suffix file (`nested/pkg/keep_mod.py`) vs deleted file (`old/gone_mod.py`).
        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, env=git_env)
        tracked_real = self.repo / "nested" / "pkg" / "keep_mod.py"
        tracked_real.parent.mkdir(parents=True, exist_ok=True)
        tracked_real.write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "nested/pkg/keep_mod.py"], check=True, env=git_env)
        self._write_mem("real-git-suffix", description="Refers to pkg/keep_mod.py", modified="2026-11-24T00:30:00.000Z")
        self._write_mem("real-git-gone", description="Refers to old/gone_mod.py", modified="2026-11-24T00:31:00.000Z")
        p0b = self._start_run(dream_nogit)
        r0b = dream_nogit.apply(p0b.run_id, json.dumps({
            "run": p0b.run_id,
            "ops": [
                {"op": "forget", "name": "real-git-suffix", "why": "suffix of real tracked file"},
                {"op": "forget", "name": "real-git-gone", "why": "genuinely absent from real git"},
            ],
        }))
        self.assertEqual(r0b.summary["forgotten"], 1)
        self.assertEqual(r0b.summary["refused"], 1)
        self.assertTrue((self.layer.dir / "real-git-suffix.md").exists())
        self.assertFalse((self.layer.dir / "real-git-gone.md").exists())

        # 2. Untracked file existing on disk, absolute path, parent traversal, duplicate touches, drop refusals, secrets.
        dream = Dream(self.ctx, self.repo)
        self._as_dream_helper()
        self.ctx.git.git_results[(str(self.repo), "ls-files")] = "keep/tracked.py"
        untracked = self.repo / "sub" / "untracked_local.py"
        untracked.parent.mkdir(parents=True, exist_ok=True)
        untracked.write_text("# untracked but present on disk\n", encoding="utf-8")

        self._write_mem("disk-present", description="Mentions sub/untracked_local.py", modified="2026-11-24T01:00:00.000Z")
        self._write_mem("abs-path", description="Mentions /etc/hosts.cfg and gone/a.py", modified="2026-11-24T01:01:00.000Z")
        self._write_mem("dotdot-path", description="Mentions ../outside.py and gone/b.py", modified="2026-11-24T01:02:00.000Z")
        self._write_mem("dup-1", description="Dup entry 1", modified="2026-11-24T01:03:00.000Z")
        self._write_mem("dup-2", description="Dup entry 2", modified="2026-11-24T01:04:00.000Z")
        self._write_candidate("w2", "c-dup", description="Unique candidate for dup test")
        self._write_candidate("w2", "c-nowhy", description="Candidate missing why")
        self._write_candidate("w2", "c-badcov", description="Candidate bad covered_by")
        c_mut = self._write_candidate("w2", "c-mut", description="Candidate mutated after pack")
        self._write_candidate("w2", "c-sec", description="Candidate with secret override")

        p1 = self._start_run(dream)
        c_mut.write_text(c_mut.read_text(encoding="utf-8") + "\nmutated\n", encoding="utf-8")
        fake_secret = "sk-" + "A" * 24

        r1 = dream.apply(p1.run_id, json.dumps({
            "run": p1.run_id,
            "ops": [
                {"op": "forget", "name": "disk-present", "why": "not tracked"},
                {"op": "forget", "name": "abs-path", "why": "abs"},
                {"op": "forget", "name": "dotdot-path", "why": "dotdot"},
                {"op": "merge", "into": "dup-1", "sources": ["dup-1", "dup-2"], "description": f"Leaked {fake_secret}"},
                # dup-1 was already touched by the merge op above -> must be refused as duplicate touch
                {"op": "forget", "name": "dup-1", "why": "touched twice"},
                {"op": "adopt", "candidate": "w2/c-sec", "type": "pitfall", "description": f"Secret {fake_secret}"},
                {"op": "adopt", "candidate": "w2/c-dup", "type": "pitfall"},
                {"op": "drop", "candidate": "w2/c-dup", "why": "touched twice"},
                {"op": "drop", "candidate": "w2/c-nowhy", "why": "   "},
                {"op": "drop", "candidate": "w2/c-badcov", "covered_by": "nonexistent-mem", "why": "covered"},
                {"op": "drop", "candidate": "w2/c-mut", "why": "changed"},
            ],
        }))
        self.assertEqual(r1.summary["adopted"], 1)
        self.assertEqual(r1.summary["forgotten"], 0)
        self.assertEqual(r1.summary["merged"], 0)
        self.assertEqual(r1.summary["dropped"], 0)
        self.assertEqual(r1.summary["refused"], 10)
        self.assertIn("exists on disk", r1.ops[0]["reason"])
        self.assertIn("unverifiable", r1.ops[1]["reason"])
        self.assertIn("unverifiable", r1.ops[2]["reason"])
        self.assertIn("secret", r1.ops[3]["reason"])
        self.assertIn("already touched", r1.ops[4]["reason"])
        self.assertIn("secret", r1.ops[5]["reason"])
        self.assertIn("already touched", r1.ops[7]["reason"])
        self.assertIn("why", r1.ops[8]["reason"])
        self.assertIn("does not exist", r1.ops[9]["reason"])
        self.assertIn("changed since the pack", r1.ops[10]["reason"])

        # 3. Step 4 CLI contract: `pm.py project memory <slug>` exposes `dream` status JSON.
        code, stdout, stderr = run_main(self.ctx, "project", "memory", self.slug)
        self.assertEqual(code, 0, stderr)
        mem_payload = json.loads(stdout)
        self.assertIn("dream", mem_payload)
        self.assertEqual(mem_payload["dream"]["running"], False)
        self.assertEqual(mem_payload["dream"]["summary"]["adopted"], 1)
        self.assertEqual(mem_payload["dream"]["summary"]["refused"], 10)


class TestReviewRepros(DreamTestBase):
    """Expected-failure reproducers for production issues identified in final review."""

    def setUp(self):
        super().setUp()
        self.hc = FakeHc(clock=self.clock)
        self.procs = FakeProcs(self.tmp)
        self.pm_term = "t10"
        self.hc.terminals[self.pm_term] = {
            "address": self.pm_term,
            "name": f"pm-{self.slug}",
            "state": "live",
            "labels": {"pm": self.repo.name},
            "status": {"state": "idle"},
            "turn": 1,
        }
        self.ctx = make_ctx(
            self.tmp,
            pane="",
            hc_terminal="",
            hc=self.hc,
            clock=self.clock,
            procs=self.procs,
        )
        self.ctx.store.change_registration(self.slug, lambda _: {
            "name": f"pm-{self.slug}",
            "project": self.repo.name,
            "repo": str(self.repo),
            "runtime": "hc",
            "terminal": self.pm_term,
            "pane": f"hc:{self.pm_term}",
            "claimed": self.clock.now(),
        })
        self.layer = MemoryLayer(self.ctx, self.repo)
        self.layer.dir.mkdir(parents=True, exist_ok=True)

    def test_repro_dream_run_recovers_after_helper_exits_with_auto_off(self):
        """With default auto=False, a manual `dream run` whose helper exits/times out without `dream apply`
        must not leave `status().running` stuck True and wedge all future `dream run` calls forever."""
        from pmlib.helpers.watch import HelperWatcher

        self._write_mem("stuck-1", description="Pitfall one")
        code1, _, err1 = run_main(self.ctx, "dream", "run", "--repo", str(self.repo))
        self.assertEqual(code1, 0, err1)

        helpers = helper_entries(self.ctx.store.registration(self.slug))
        del self.hc.terminals[helpers[0]["terminal"]]
        HelperWatcher(self.ctx).look(str(self.repo), {})
        self.clock.advance(2000)  # well past timeout (900) + grace (120)

        self.assertFalse(Dream(self.ctx, self.repo).status()["running"])
        code2, _, err2 = run_main(self.ctx, "dream", "run", "--repo", str(self.repo))
        self.assertEqual(code2, 0, err2)

    def test_repro_watcher_reaps_timed_out_manual_run_even_when_failures_at_cap(self):
        """When failures == 3 (auto paused) and a manual recovery `dream run` times out, Gate 2 returning
        before Gate 3 must not leave `state.run.status == 'running'` permanently."""
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps({"memory": {"dream": {"auto": True, "timeout": 900}}}), encoding="utf-8")

        dream = Dream(self.ctx, self.repo)
        st = dream.state.load()
        st["failures"] = 3
        st["run"] = {
            "id": "20261124-090000",
            "status": "running",
            "trigger": "manual",
            "started_at": "2026-11-24 09:00:00",
        }
        dream.state.save(st)

        DreamWatcher(self.ctx).look(str(self.repo), {}, {})
        self.assertNotEqual(dream.state.load()["run"]["status"], "running")

    def test_repro_undo_merge_does_not_clobber_newly_created_memory_at_removed_source_name(self):
        """If a new (e.g. protected `project`) memory was created under a merged-away source's name after
        `dream apply`, `dream undo` must not overwrite that new memory without checking existence."""
        self._write_mem("m-keep", description="Survivor pitfall", body="Keep body")
        self._write_mem("m-src", description="Merged source pitfall", body="Src body")
        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        self._as_dream_helper()
        dream.apply(packed.run_id, json.dumps({
            "run": packed.run_id,
            "ops": [{
                "op": "merge",
                "into": "m-keep",
                "sources": ["m-keep", "m-src"],
                "description": "Merged pitfall",
            }],
        }))

        # User/PM creates a protected project decision reusing the free slug `m-src`.
        self._write_mem(
            "m-src",
            kind="project",
            by="pm",
            quote="keep m-src as a product decision",
            description="Protected decision created after merge",
            body="Must never be overwritten by dream undo.",
        )

        self._as_user()
        dream.undo(packed.run_id)
        after_src = read_memory(self.layer.dir / "m-src.md")
        self.assertEqual(after_src["type"], "project")
        self.assertEqual(after_src["description"], "Protected decision created after merge")

    def test_repro_undo_does_not_crash_mid_run_after_single_source_restored_from_history(self):
        """Restoring a single merged source via the Memory page History drawer (`MemoryLayer.restore`
        unlinks its `.history` snapshot) must not cause a later `dream undo` to raise `MemoryRefused`
        mid-loop after partially mutating disk."""
        self._write_mem("h-keep", description="Keep note", body="Keep body")
        self._write_mem("h-src", description="Source note", body="Source body")
        self._write_candidate("w1", "h-drop", description="Dropped candidate")
        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        self._as_dream_helper()
        dream.apply(packed.run_id, json.dumps({
            "run": packed.run_id,
            "ops": [
                {"op": "merge", "into": "h-keep", "sources": ["h-keep", "h-src"], "description": "Merged"},
                {"op": "drop", "candidate": "w1/h-drop", "why": "noise"},
            ],
        }))

        # User restores `h-src` from the History drawer first, which unlinks its `.history` file.
        self.layer.restore("h-src", writer=("user", "user"), project_repo=self.repo)

        self._as_user()
        undone = dream.undo(packed.run_id)
        self.assertTrue(dream.last_receipt()["undone_at"])
        self.assertTrue(undone.restored or undone.skipped)

    def test_repro_deliver_ready_preserves_quiet_when_helper_already_stopped(self):
        """If a `quiet=True` async helper was already stopped/timed out before `_deliver-ready` finishes
        `send_when_ready(handed=False)`, `deliver_ready` must not emit a `wake=True` event."""
        from unittest import mock
        from pmlib.helpers.service import HelperStartRequest, Helpers

        pm_ctx = make_ctx(
            self.tmp,
            pane=f"hc:{self.pm_term}",
            hc_terminal=self.pm_term,
            hc=self.hc,
            clock=self.clock,
            procs=self.procs,
        )
        svc = Helpers(pm_ctx)
        res = svc.start(HelperStartRequest(
            prompt="Quiet async", name="auto-dream", quiet=True, async_=True, repo=str(self.repo),
        ))
        svc.stop(["auto-dream"], repo=str(self.repo))
        # Simulate terminal still briefly reporting blocked/live when _deliver-ready finishes polling.
        self.hc.terminals[res.terminal] = {
            "address": res.terminal,
            "state": "live",
            "status": {"state": "blocked"},
            "screen": "Prompt dialog",
        }
        bg_svc = Helpers(self.ctx)
        with mock.patch.object(bg_svc._workers, "send_when_ready", return_value=False):
            bg_svc.deliver_ready(
                res.terminal,
                "brief text",
                kind="claude",
                repo=str(self.repo),
                owner_kind="pm",
                owner_id=f"pm-{self.slug}",
                slug=self.slug,
                name="auto-dream",
            )
        events = [e for e in Conversation(self.ctx, self.repo).events() if e.get("type") == "helper"]
        self.assertFalse(any(e.get("wake") is True for e in events), events)

    def test_repro_extract_repo_paths_treats_env_var_prefixed_paths_as_unverifiable(self):
        """`$HOME/.claude/settings.json` must be treated as unverifiable, not extracted as `HOME/...`."""
        rel, unv = extract_repo_paths("Check $HOME/.claude/settings.json and legacy/deleted.py")
        self.assertEqual(rel, ["legacy/deleted.py"])
        self.assertTrue(unv, f"expected env-prefixed path in unverifiable, got rel={rel!r}, unv={unv!r}")

    def test_undo_merge_prechecks_missing_source_history_before_modifying_into(self):
        """If a removed source's `.history` snapshot is missing while the source file does not exist,
        `dream undo` must skip the merge op before modifying `into` (no partial rollback)."""
        self._write_mem("a-keep", description="Original keep", body="Keep body")
        self._write_mem("a-src", description="Original src", body="Src body")
        dream = Dream(self.ctx, self.repo)
        packed = self._start_run(dream)
        self._as_dream_helper()
        dream.apply(packed.run_id, json.dumps({
            "run": packed.run_id,
            "ops": [{
                "op": "merge",
                "into": "a-keep",
                "sources": ["a-keep", "a-src"],
                "description": "Merged description",
            }],
        }))
        # Remove `a-src`'s history snapshot directly while `a-src.md` is absent.
        for row in self.layer.history("a-src"):
            row["file"].unlink()

        self._as_user()
        undone = dream.undo(packed.run_id)
        self.assertTrue(any(k == "merge:a-keep" for k, _ in undone.skipped), undone.skipped)
        # `a-keep` must remain unmodified (merged state), proving no partial rollback happened.
        after_keep = read_memory(self.layer.dir / "a-keep.md")
        self.assertEqual(after_keep["description"], "Merged description")
        self.assertFalse((self.layer.dir / "a-src.md").exists())

    def test_dream_run_auto_enforces_gates(self):
        """`dream run --auto` must self-check gates so direct CLI invocation cannot bypass them."""
        for i in range(8):
            self._write_mem(f"auto-{i}", description=f"Auto pitfall {i}")

        # Gate 1: auto=False -> refused
        code, _, err = run_main(self.ctx, "dream", "run", "--auto", "--repo", str(self.repo))
        self.assertNotEqual(code, 0)
        self.assertIn("disabled", f"{code} {err}".lower())

        # Enable auto, set failures=3 -> Gate 2 refuses
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps({"memory": {"dream": {"auto": True, "min_new": 8}}}), encoding="utf-8")
        dream = Dream(self.ctx, self.repo)
        st = dream.state.load()
        st["failures"] = 3
        dream.state.save(st)
        code, _, err = run_main(self.ctx, "dream", "run", "--auto", "--repo", str(self.repo))
        self.assertNotEqual(code, 0)
        self.assertIn("failures", f"{code} {err}".lower())

        # Clear failures, but PM turn not stopped -> Gate 5 refuses
        st["failures"] = 0
        dream.state.save(st)
        code, _, err = run_main(self.ctx, "dream", "run", "--auto", "--repo", str(self.repo))
        self.assertNotEqual(code, 0)
        self.assertIn("idle", f"{code} {err}".lower())

        # Mark PM idle, reduce pending below min_new (and young) -> Gate 6 refuses
        tracker = TurnTracker(self.ctx, self.repo)
        tracker.begin_turn(terminal=self.pm_term, agent_kind="claude", cause="user", from_hook=True)
        tracker.end_turn()
        for i in range(2, 8):
            (self.layer.dir / f"auto-{i}.md").unlink()
        code, _, err = run_main(self.ctx, "dream", "run", "--auto", "--repo", str(self.repo))
        self.assertNotEqual(code, 0)
        self.assertIn("threshold", f"{code} {err}".lower())

        # Restore 8 pending entries -> all gates pass and run starts
        for i in range(2, 8):
            self._write_mem(f"auto-{i}", description=f"Auto pitfall {i}")
        code, _, err = run_main(self.ctx, "dream", "run", "--auto", "--repo", str(self.repo))
        self.assertEqual(code, 0, err)


if __name__ == "__main__":
    unittest.main()
