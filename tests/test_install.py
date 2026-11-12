import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
# Same node hierarchy as the shipped desktop main.json; no personal content.
MAIN = {
    "id": "root", "type": "row", "background": "canvas", "version": "1", "children": [
        {"id": "sidebar", "type": "column", "children": [
            {"id": "sidebar-lists", "type": "column", "children": [
                {"id": "spaces", "type": "block", "content": {"mod": "spaces"}}
            ]}
        ]},
        {"id": "work", "type": "column", "resizable": False, "children": [
            {"id": "tabs", "type": "block", "content": {"mod": "tabs"}}
        ]}
    ]
}


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.claude = self.root / "claude home"
        self.desktop = self.root / "desktop home"
        self.env = dict(os.environ, CLAUDE_HOME=str(self.claude), HERDR_APP_HOME=str(self.desktop))
        self.settings = self.claude / "settings.json"

    def run_install(self, *args):
        result = subprocess.run([str(REPO / "install.sh"), *args], env=self.env,
                                cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def read_settings(self):
        return json.loads(self.settings.read_text())

    def write_settings(self, value):
        self.claude.mkdir(parents=True, exist_ok=True)
        text = json.dumps(value, indent=4) + "\n"
        self.settings.write_text(text)
        return text

    def seed_layout(self, value=MAIN):
        path = self.desktop / "layouts/main.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return path

    def test_fresh_install(self):
        output = self.run_install("--desktop", "--discord")
        self.assertIn("Skip automatic layout", output)
        self.assertTrue((self.claude / "skills/pm/scripts/pm.py").is_file())
        self.assertTrue((self.claude / "skills/pm/SKILL.md").is_file())
        self.assertFalse((self.claude / "skills/pm/scripts/test_pm.py").exists())
        self.assertFalse(list((self.claude / "skills/pm").rglob("__pycache__")))
        for name in ("pm-dash", "pm-nav"):
            mod = self.desktop / "mods" / name
            self.assertTrue((mod / "main.js").is_file())
            self.assertTrue((mod / "mod.json").is_file())
            self.assertFalse((mod / "gpui-kit.d.ts").exists())
            self.assertFalse((mod / "jsconfig.json").exists())
            self.assertFalse(list(mod.rglob("*.test.mjs")))
        hooks = self.read_settings()["hooks"]
        session = hooks["SessionStart"][0]
        self.assertEqual(session["matcher"], "^(startup|resume|clear|compact)$")
        command = session["hooks"][0]
        self.assertEqual(command["timeout"], 10)
        self.assertEqual(shlex.split(command["command"]), ["python3", str(self.claude / "skills/pm/scripts/pm.py"), "hook-session-start"])
        for event in ("UserPromptSubmit", "Stop"):
            hook = hooks[event][0]["hooks"][0]
            self.assertTrue(hook["async"])
            self.assertEqual(hook["timeout"], 15)
            self.assertTrue(hook["command"].endswith(" hook-mirror"))

    def test_repeat_install_is_identical(self):
        self.run_install("--discord", "--desktop")
        first = self.settings.read_bytes()
        stale = [self.claude / "skills/pm/removed.txt", self.desktop / "mods/pm-dash/removed.txt",
                 self.desktop / "mods/pm-nav/removed.txt"]
        for path in stale:
            path.write_text("obsolete")
        self.run_install("--discord")
        for path in stale:
            self.assertFalse(path.exists())
        self.run_install()  # Not opting in again must not remove existing mirror hooks.
        self.assertEqual(self.settings.read_bytes(), first)
        self.assertEqual([len(entries) for entries in self.read_settings()["hooks"].values()], [1, 1, 1])
        self.run_install("--uninstall")
        self.assertNotIn("hooks", self.read_settings())
        # A linked development install must neither delete nor copy onto the source.
        (self.claude / "skills/pm").symlink_to(REPO / "skill/pm", target_is_directory=True)
        self.assertIn("already points to the repository source", self.run_install())
        self.assertTrue((self.claude / "skills/pm").is_symlink())

    def test_preserve_settings_and_original_backup(self):
        other = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo other"}]}
        original = {"permissions": {"allow": ["Read"]}, "env": {"KEEP": "yes"},
                    "hooks": {"SessionStart": [other], "Stop": [other]}}
        old_text = self.write_settings(original)
        self.run_install()
        updated = self.read_settings()
        self.assertEqual(updated["permissions"], original["permissions"])
        self.assertEqual(updated["env"], original["env"])
        self.assertEqual(updated["hooks"]["Stop"], original["hooks"]["Stop"])
        self.assertEqual(updated["hooks"]["SessionStart"][0], other)
        self.run_install("--discord")
        self.assertEqual((self.claude / "settings.json.pm-backup").read_text(), old_text)

    def test_discord_and_desktop_are_optional(self):
        output = self.run_install()
        self.assertEqual(list(self.read_settings()["hooks"]), ["SessionStart"])
        self.assertNotIn("hook-mirror", self.settings.read_text())
        self.assertFalse(self.desktop.exists())
        self.assertIn("Skip desktop", output)

    def test_shipped_layout(self):
        shipped = REPO / "layouts/pm.json"
        tree = json.loads(shipped.read_text())
        self.assertNotIn("generated_by", tree)
        sidebar, stage = tree["children"]
        lists = next(node for node in sidebar["children"] if node["id"] == "sidebar-lists")
        self.assertEqual(lists["children"][0], {
            "id": "pm-nav", "type": "block", "size": {"px": 64}, "content": {"mod": "pm-nav"}})
        self.assertEqual(stage["id"], "pm-stage")
        self.assertEqual(stage["type"], "stack")
        self.assertEqual(stage["active"], "work")
        self.assertEqual([node["id"] for node in stage["children"]], ["work", "pm-board"])
        self.assertEqual(stage["children"][0]["type"], "column")
        self.assertEqual(stage["children"][1], {
            "id": "pm-board", "type": "block", "content": {"mod": "pm-dash"}})

        # Adding the directory layout first must not transfer ownership to the installer.
        self.seed_layout()
        target = self.desktop / "layouts/pm.json"
        target.write_bytes(shipped.read_bytes())
        self.assertIn("already contains pm-nav", self.run_install())
        self.assertEqual(target.read_bytes(), shipped.read_bytes())
        self.assertIn("Keep layout", self.run_install("--uninstall"))
        self.assertEqual(target.read_bytes(), shipped.read_bytes())

    def test_layout(self):
        source = self.seed_layout()
        source_bytes = source.read_bytes()
        self.run_install()  # Existing HERDR_APP_HOME enables desktop automatically.
        target = self.desktop / "layouts/pm.json"
        actual = json.loads(target.read_text())
        expected = copy.deepcopy(MAIN)
        expected["generated_by"] = "dudu install.sh"
        expected["cloned_from"] = {"name": "main", "version": "1"}
        expected["children"][0]["children"][0]["children"].insert(0, {
            "id": "pm-nav", "type": "block", "size": {"px": 64}, "content": {"mod": "pm-nav"}})
        expected["children"][1] = {"id": "pm-stage", "type": "stack", "active": "work", "children": [
            copy.deepcopy(MAIN["children"][1]), {"id": "pm-board", "type": "block", "content": {"mod": "pm-dash"}}]}
        self.assertEqual(actual, expected)
        self.assertEqual(source.read_bytes(), source_bytes)
        actual["background"] = "custom"
        target.write_text(json.dumps(actual))
        custom = target.read_bytes()
        self.run_install()
        self.assertEqual(target.read_bytes(), custom)
        target.unlink()
        self.seed_layout({"id": "root", "type": "row", "children": []})
        self.assertIn("Manual fallback", self.run_install())
        self.assertFalse(target.exists())
        self.seed_layout()
        target.write_text('{"id":"custom","type":"row","children":[]}')
        previous = target.read_bytes()
        self.run_install()
        self.assertEqual(target.with_name("pm.json.pm-backup").read_bytes(), previous)
        self.assertEqual(json.loads(target.read_text())["generated_by"], "dudu install.sh")

    def test_uninstall_keeps_ledger_and_other_hooks(self):
        self.seed_layout()
        other = {"type": "command", "command": "echo other"}
        original = {"env": {"KEEP": "yes"}, "hooks": {"Stop": [{"hooks": [other]}]}}
        self.write_settings(original)
        self.run_install("--discord")
        ledger = self.claude / "pm/tasks/task.json"
        ledger.parent.mkdir(parents=True)
        ledger.write_text('{"title":"keep"}')
        settings = self.read_settings()
        settings["hooks"]["SessionStart"][0]["hooks"].append(other)
        self.settings.write_text(json.dumps(settings))
        self.run_install("--uninstall")
        self.assertEqual(ledger.read_text(), '{"title":"keep"}')
        self.assertEqual(self.read_settings()["env"], original["env"])
        self.assertEqual(self.read_settings()["hooks"]["Stop"], original["hooks"]["Stop"])
        self.assertEqual(self.read_settings()["hooks"]["SessionStart"][0]["hooks"], [other])
        self.assertNotIn("skills/pm/scripts/pm.py", self.settings.read_text())
        for path in (self.claude / "skills/pm", self.desktop / "mods/pm-dash",
                     self.desktop / "mods/pm-nav", self.desktop / "layouts/pm.json"):
            self.assertFalse(path.exists())
        self.assertTrue((self.desktop / "layouts/main.json").is_file())
        self.assertTrue((self.claude / "settings.json.pm-backup").is_file())
        self.run_install("--uninstall")

    def test_invalid_settings_install_does_not_write(self):
        self.claude.mkdir()
        for invalid in ('{invalid', '{"hooks":null}', '{"hooks":[]}'):
            with self.subTest(settings=invalid):
                self.settings.write_text(invalid)
                before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                result = subprocess.run([str(REPO / "install.sh"), "--desktop"], env=self.env,
                                        cwd=self.root, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Install failed", result.stderr)
                self.assertEqual({str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}, before)
                self.assertEqual(set(self.root.rglob("*")), {self.claude, self.settings})
                # Uninstall must still remove installed files with unreadable hooks.
                installed = self.claude / "skills/pm"
                installed.mkdir(parents=True)
                (installed / "old.txt").write_text("old")
                self.assertIn("Warning: skip hook cleanup", self.run_install("--uninstall"))
                self.assertFalse(installed.exists())
                self.assertEqual(self.settings.read_text(), invalid)
                installed.parent.rmdir()

    def test_uninstall_preserves_unmarked_layout(self):
        self.seed_layout()
        target = self.desktop / "layouts/pm.json"
        for content in ('{"id":"custom","type":"row","children":[]}',
                        '{"id":"pm-nav","type":"block"}', '{invalid'):
            with self.subTest(layout=content):
                target.write_text(content)
                self.assertIn("Keep layout", self.run_install("--uninstall"))
                self.assertEqual(target.read_text(), content)

    def test_default_hook_path_uses_tilde(self):
        self.env["HOME"] = str(self.root)
        self.env.pop("CLAUDE_HOME", None)
        self.env.pop("HERDR_APP_HOME", None)
        self.run_install("--discord")
        settings = json.loads((self.root / ".claude/settings.json").read_text())
        for event, action in (("SessionStart", "hook-session-start"), ("Stop", "hook-mirror"),
                              ("UserPromptSubmit", "hook-mirror")):
            self.assertEqual(settings["hooks"][event][0]["hooks"][0]["command"],
                             f"python3 ~/.claude/skills/pm/scripts/pm.py {action}")

    def test_dry_run_writes_nothing(self):
        self.run_install("--dry-run", "--desktop", "--discord")
        self.assertEqual(list(self.root.iterdir()), [])
        self.seed_layout()
        self.write_settings({"env": {"KEEP": "yes"}})
        def snapshot():
            return {str(path.relative_to(self.root)): path.read_bytes() if path.is_file() else None
                    for path in self.root.rglob("*")}
        before = snapshot()
        self.run_install("--dry-run", "--desktop", "--discord")
        self.assertEqual(snapshot(), before)
        self.run_install("--desktop", "--discord")
        before = snapshot()
        self.run_install("--uninstall", "--dry-run")
        self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    unittest.main()
