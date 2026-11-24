"""Contract tests pinning the stderr error substrings matched by `mods/pm-project/model.js`
(`docs/design/pm-py-refactor.md`, section 3.4 & `docs/design/pm-py-pass-two.md`, section 6.2)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
PM_PY = SCRIPTS / "pm.py"


def _run_pm(*args: str, ledger: Path, env_extra: dict[str, str] | None = None, script: Path = PM_PY) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("HERDR_PANE_ID", "HC_TERMINAL_ID", "HERDR_WORKSPACE_ID", "HERDR_ENV")}
    env["PM_HOME"] = str(ledger)
    env["PM_NO_DISCORD"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(script), *args], env=env, capture_output=True, text=True, timeout=30)


class ModErrorContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-mod-contract-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger = self.root / "ledger"
        (self.ledger / "tasks").mkdir(parents=True)
        (self.ledger / "pms").mkdir(parents=True)
        (self.ledger / "projects" / "demo").mkdir(parents=True)
        self.repo = self.root / "demo"
        self.repo.mkdir()
        (self.ledger / "pms" / "demo.json").write_text(json.dumps({
            "project": "demo", "repo": str(self.repo), "name": "pm-demo", "runtime": "hc", "terminal": "t1",
        }), encoding="utf-8")

    def test_argparse_and_ledger_and_document_substrings(self) -> None:
        # 1 & 2: invalid choice & unrecognized arguments
        bad_cmd = _run_pm("not-a-command", ledger=self.ledger)
        self.assertNotEqual(bad_cmd.returncode, 0)
        self.assertIn("invalid choice:", bad_cmd.stderr)

        bad_flag = _run_pm("state", "--not-a-flag", ledger=self.ledger)
        self.assertNotEqual(bad_flag.returncode, 0)
        self.assertIn("unrecognized arguments", bad_flag.stderr)

        # 3: already exists (start when registered desktop PM terminal is already live)
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        (fake_bin / "hc").write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "args = [a for a in sys.argv[1:] if a != '--json']\n"
            "if args[:2] == ['get', 't1']:\n"
            "    print(json.dumps({'address': 't1', 'state': 'live', 'labels': {'pm': 'demo'}, 'status': {'state': 'idle'}}))\n"
            "else:\n"
            "    print(json.dumps({}))\n",
            encoding="utf-8",
        )
        (fake_bin / "hc").chmod(0o755)
        dup = _run_pm(
            "start", "--repo", str(self.repo), ledger=self.ledger,
            env_extra={"PATH": os.pathsep.join([str(fake_bin), "/usr/bin", "/bin"])},
        )
        self.assertNotEqual(dup.returncode, 0)
        self.assertIn("already exists", dup.stderr)

        # 4: is not offline (reattach on a task whose terminal/pane is not offline)
        (self.ledger / "tasks" / "demo-live.json").write_text(json.dumps({
            "id": "demo-live", "title": "Live", "project": "demo", "repo": str(self.repo),
            "status": "in_progress", "pane": "remote/t1", "updated": "2026-11-22 10:00",
        }), encoding="utf-8")
        not_off = _run_pm("reattach", "demo-live", ledger=self.ledger)
        self.assertNotEqual(not_off.returncode, 0)
        self.assertIn("is not offline", not_off.stderr)

        # 5, 6, 7: was replaced / shorter than / no line ends at byte (conversation log)
        conv = self.ledger / "projects" / "demo" / "conversation.jsonl"
        conv.write_text(json.dumps({"at": "2026-11-22 10:00", "type": "pm", "text": "hello"}) + "\n", encoding="utf-8")
        replaced = _run_pm("project", "events", "demo", "--before", "9999", ledger=self.ledger)
        self.assertNotEqual(replaced.returncode, 0)
        self.assertIn("was replaced", replaced.stderr)
        self.assertIn("shorter than", replaced.stderr)

        mid_line = _run_pm("project", "events", "demo", "--before", "3", ledger=self.ledger)
        self.assertNotEqual(mid_line.returncode, 0)
        self.assertIn("no line ends at byte", mid_line.stderr)

        # 14 & 16: no task / invalid document root
        no_task = _run_pm("show", "demo-missing", ledger=self.ledger)
        self.assertNotEqual(no_task.returncode, 0)
        self.assertIn("no task ", no_task.stderr)

        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        from pmlib.project.readmodel import Projects
        from pmlib.store import FileStore
        with self.assertRaisesRegex(ValueError, "invalid document root"):
            Projects(FileStore(self.ledger)).document("demo", "badroot", "x.md")

    def test_project_session_substrings_and_missing_pm_sessions(self) -> None:
        # 15: not a task id
        bad_id = _run_pm("project", "session", "../escape", ledger=self.ledger)
        self.assertNotEqual(bad_id.returncode, 0)
        self.assertIn("not a task id", bad_id.stderr)

        # 9: is not supported
        (self.ledger / "tasks" / "demo-codex.json").write_text(json.dumps({
            "id": "demo-codex", "title": "Codex", "project": "demo", "repo": str(self.repo),
            "status": "in_progress", "worker": {"kind": "codex"}, "updated": "2026-11-22 10:00",
        }), encoding="utf-8")
        unsup = _run_pm("project", "session", "demo-codex", ledger=self.ledger)
        self.assertNotEqual(unsup.returncode, 0)
        self.assertIn("is not supported", unsup.stderr)

        # 10: no session found
        (self.ledger / "tasks" / "demo-nosess.json").write_text(json.dumps({
            "id": "demo-nosess", "title": "NoSess", "project": "demo", "repo": str(self.repo),
            "status": "in_progress", "worker": {"kind": "claude"}, "updated": "2026-11-22 10:00",
        }), encoding="utf-8")
        no_sess = _run_pm("project", "session", "demo-nosess", ledger=self.ledger, env_extra={"HOME": str(self.root / "empty-home")})
        self.assertNotEqual(no_sess.returncode, 0)
        self.assertIn("no session found", no_sess.stderr)

        # 12: transcript not found
        (self.ledger / "tasks" / "demo-missing-tr.json").write_text(json.dumps({
            "id": "demo-missing-tr", "title": "MissTr", "project": "demo", "repo": str(self.repo),
            "status": "in_progress", "session": {"kind": "claude", "id": "sid-does-not-exist"},
            "updated": "2026-11-22 10:00",
        }), encoding="utf-8")
        miss_tr = _run_pm("project", "session", "demo-missing-tr", ledger=self.ledger, env_extra={"HOME": str(self.root / "empty-home")})
        self.assertNotEqual(miss_tr.returncode, 0)
        self.assertIn("transcript not found", miss_tr.stderr)

        # 8: no line of the transcript starts at byte
        claude_dir = self.root / "home-with-tr" / ".claude" / "projects" / "demo-proj"
        claude_dir.mkdir(parents=True)
        (claude_dir / "sid-real.jsonl").write_text(
            json.dumps({"type": "user", "timestamp": "2026-11-22T10:00:00Z", "message": {"content": "hello world"}}) + "\n",
            encoding="utf-8",
        )
        (self.ledger / "tasks" / "demo-tr.json").write_text(json.dumps({
            "id": "demo-tr", "title": "Tr", "project": "demo", "repo": str(self.repo),
            "status": "in_progress", "session": {"kind": "claude", "id": "sid-real"},
            "updated": "2026-11-22 10:00",
        }), encoding="utf-8")
        bad_off = _run_pm("project", "session", "demo-tr", "--before", "4", ledger=self.ledger, env_extra={"HOME": str(self.root / "home-with-tr")})
        self.assertNotEqual(bad_off.returncode, 0)
        self.assertIn("no line of the transcript starts at byte", bad_off.stderr)

        # 13: no unambiguous claude session (case-insensitive check matching model.js)
        ambig_home = self.root / "ambig-home"
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        from pmlib.agents.sessions import claude_folder
        ambig_dir = ambig_home / ".claude" / "projects" / claude_folder(self.repo)
        ambig_dir.mkdir(parents=True)
        (ambig_dir / "sid-mention.jsonl").write_text(
            json.dumps({"type": "user", "timestamp": "2026-11-22T10:00:00Z", "message": {"content": "mentioned demo-ambig once"}}) + "\n",
            encoding="utf-8",
        )
        (self.ledger / "tasks" / "demo-ambig.json").write_text(json.dumps({
            "id": "demo-ambig", "title": "Ambig", "project": "demo", "repo": str(self.repo),
            "status": "in_progress", "updated": "2026-11-22 10:00",
        }), encoding="utf-8")
        ambig = _run_pm("project", "session", "demo-ambig", ledger=self.ledger, env_extra={"HOME": str(ambig_home)})
        self.assertNotEqual(ambig.returncode, 0)
        self.assertIn("no unambiguous claude session", ambig.stderr.lower())

        # 11: no session recorded (SessionRegistry.turns(None))
        from pmlib.agents.transcripts import SessionNotFoundError, default_sessions
        with self.assertRaisesRegex(SessionNotFoundError, "no session recorded"):
            default_sessions().turns(None)

        # 17: pm_sessions.py is missing
        solo = self.root / "solo"
        solo.mkdir()
        shutil.copy2(PM_PY, solo / "pm.py")
        shutil.copytree(SCRIPTS / "pmlib", solo / "pmlib", ignore=shutil.ignore_patterns("__pycache__"))
        (solo / "pmlib" / "agents" / "transcripts.py").unlink()
        missing_sess = _run_pm("project", "session", "demo-tr", ledger=self.ledger, script=solo / "pm.py")
        self.assertNotEqual(missing_sess.returncode, 0)
        self.assertIn("pm_sessions.py is missing", missing_sess.stderr)

    def test_cli_main_pm_error_preserves_substrings_verbatim(self) -> None:
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); msg = sys.argv[2]; "
            "from pmlib import cli; from pmlib.errors import Refused; "
            "cli.COMMANDS['status'] = (type('M', (), {'f': staticmethod(lambda _a, ctx=None: (_ for _ in ()).throw(Refused(msg)))}), 'f'); "
            "sys.argv = ['pm.py', 'status']; cli.main()"
        )
        for text in ("already exists", "no task demo-1", "not a task id: x", "invalid document root: 'bad'"):
            res = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), text], capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn(text, res.stderr)


if __name__ == "__main__":
    unittest.main()
