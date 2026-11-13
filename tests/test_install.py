import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "mods/pm-dash"
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
        self.codex = self.root / "codex home"
        self.pi = self.root / "pi home"
        self.desktop = self.root / "desktop home"
        # Every agent home points into the temporary directory; real homes are never touched.
        self.env = dict(os.environ, HOME=str(self.root), CLAUDE_HOME=str(self.claude), CODEX_HOME=str(self.codex),
                        PI_CODING_AGENT_DIR=str(self.pi), HERDR_APP_HOME=str(self.desktop))
        self.env.pop("PM_HOME", None)
        self.settings = self.claude / "settings.json"

    def run_install(self, *args):
        result = subprocess.run([str(REPO / "install.sh"), *args], env=self.env,
                                cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def read_settings(self):
        return json.loads(self.settings.read_text())

    def run_setup(self, *args, bundle=BUNDLE, success=True):
        result = subprocess.run(["python3", str(bundle / "setup.py"), *args], env=self.env,
                                cwd=self.root, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() if p.is_file() else None
                for p in self.root.rglob("*")}

    def test_setup_status_install_and_update_from_standalone_renamed_bundle(self):
        # A directory download has no repository or install.sh, and a mod clone
        # must install the skill alongside its own setup.py.
        bundle = self.root / "app home/mods/custom-board"
        shutil.copytree(BUNDLE, bundle, ignore=shutil.ignore_patterns("__pycache__"))
        before = self.snapshot()
        status = self.claude_status(bundle=bundle)
        self.assertFalse(status["skill_present"])
        self.assertFalse(status["hooks_present"])
        self.assertEqual(self.snapshot(), before)
        self.run_setup("--dry-run", bundle=bundle)
        self.assertEqual(self.snapshot(), before)
        self.run_setup(bundle=bundle)
        status = self.claude_status(bundle=bundle)
        self.assertTrue(all(status[key] for key in ("skill_present", "hooks_present", "script_matches")))
        first_settings = self.settings.read_bytes()
        installed = self.claude / "skills/pm/scripts/pm.py"
        bundled = bundle / "skill/scripts/pm.py"
        # Equal size is not enough: an edit must be caught by the hash.
        content = bundled.read_bytes()
        bundled.write_bytes(content.replace(b"import ", b"#mport ", 1))
        full = json.loads(self.run_setup("--status", bundle=bundle).stdout)
        status = full["agents"]["claude"]
        self.assertTrue(status["skill_present"] and status["hooks_present"])
        self.assertFalse(status["script_matches"])
        self.assertEqual(full["summary"]["outdated"], ["claude"])
        self.assertEqual(status["installed"]["size"], full["bundled"]["size"])
        self.assertNotEqual(status["installed"]["sha256"], full["bundled"]["sha256"])
        self.run_setup(bundle=bundle)
        self.assertEqual(installed.read_bytes(), bundled.read_bytes())
        self.assertEqual(self.settings.read_bytes(), first_settings)
        self.assertTrue(self.claude_status(bundle=bundle)["script_matches"])
        self.assertFalse(self.desktop.exists())

    def test_setup_status_partial_install_invalid_settings_and_no_writes(self):
        self.run_setup()
        self.write_settings({"hooks": {"SessionStart": []}})
        before = self.snapshot()
        status = self.claude_status()
        self.assertTrue(status["skill_present"])
        self.assertFalse(status["hooks_present"])
        self.assertEqual(self.snapshot(), before)
        self.run_setup()
        (self.claude / "skills/pm/SKILL.md").unlink()
        status = self.claude_status()
        self.assertFalse(status["skill_present"])
        self.assertTrue(status["hooks_present"])
        for invalid in ('{invalid', '{"hooks":[]}', '{"hooks":{"SessionStart":[null]}}'):
            with self.subTest(settings=invalid):
                self.settings.write_text(invalid)
                before = self.snapshot()
                full = json.loads(self.run_setup("--status").stdout)
                self.assertFalse(full["agents"]["claude"]["hooks_present"])
                self.assertIn("Install failed", full["error"])
                self.assertIn("Install failed", self.run_setup(success=False).stderr)
                self.assertEqual(self.snapshot(), before)

    def test_shell_and_board_install_have_identical_skill_and_hooks(self):
        self.env.pop("CLAUDE_HOME")
        self.claude = self.root / ".claude"
        self.settings = self.claude / "settings.json"
        original = {"permissions": {"allow": ["Read"]}, "hooks": {
            "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "echo other"}]}]}}
        self.write_settings(original)
        self.settings.chmod(0o640)
        self.run_setup("--claude-home", str(self.claude))
        board = self.snapshot()
        expected = copy.deepcopy(original)
        expected["hooks"]["SessionStart"].append({"matcher": "^(startup|resume|clear|compact)$", "hooks": [{
            "type": "command", "command": "python3 ~/.claude/skills/pm/scripts/pm.py hook-session-start", "timeout": 10}]})
        expected["hooks"]["UserPromptSubmit"] = [{"hooks": [{"type": "command", "command":
            "python3 ~/.claude/skills/pm/scripts/pm.py hook-turn", "timeout": 15}]}]
        expected["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command":
            "python3 ~/.claude/skills/pm/scripts/pm.py hook-turn", "timeout": 15, "async": True}]}]
        self.assertEqual(self.read_settings(), expected)
        self.assertEqual(self.skill_files(self.claude), self.bundle_files())
        shutil.rmtree(self.claude)
        self.write_settings(original)
        self.settings.chmod(0o640)
        self.run_install()
        self.assertEqual(self.snapshot(), board)
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o640)

    def claude_status(self, bundle=BUNDLE):
        return json.loads(self.run_setup("--status", bundle=bundle).stdout)["agents"]["claude"]

    @staticmethod
    def bundle_files():
        return {str(p.relative_to(BUNDLE / "skill")): p.read_bytes()
                for p in (BUNDLE / "skill").rglob("*") if p.is_file()
                and p.name not in ("test_pm.py", ".DS_Store") and "__pycache__" not in p.parts}

    @staticmethod
    def skill_files(home):
        return {str(p.relative_to(home / "skills/pm")): p.read_bytes()
                for p in (home / "skills/pm").rglob("*") if p.is_file()}

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
        output = self.run_install("--desktop")
        self.assertIn("Skip automatic layout", output)
        self.assertIn("No coding agent home found", output)
        self.assertTrue((self.claude / "skills/pm/scripts/pm.py").is_file())
        self.assertTrue((self.claude / "skills/pm/SKILL.md").is_file())
        self.assertFalse((self.claude / "skills/pm/scripts/test_pm.py").exists())
        self.assertFalse(list((self.claude / "skills/pm").rglob("__pycache__")))
        for name in ("pm-dash", "pm-nav", "pm-toast"):
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
            # The prompt hook's output joins the session's context, so only Stop may run in the background.
            self.assertEqual(hook.get("async", False), event == "Stop")
            self.assertEqual(hook["timeout"], 15)
            self.assertTrue(hook["command"].endswith(" hook-turn"))
        self.assertFalse(self.codex.exists() or self.pi.exists())

    def test_repeat_install_is_identical(self):
        self.run_install("--desktop")
        first = self.settings.read_bytes()
        stale = [self.claude / "skills/pm/removed.txt", self.desktop / "mods/pm-dash/removed.txt",
                 self.desktop / "mods/pm-nav/removed.txt", self.desktop / "mods/pm-toast/removed.txt"]
        for path in stale:
            path.write_text("obsolete")
        self.run_install()
        for path in stale:
            self.assertFalse(path.exists())
        self.assertEqual(self.settings.read_bytes(), first)
        self.assertEqual([len(entries) for entries in self.read_settings()["hooks"].values()], [1, 1, 1])
        self.run_install("--uninstall")
        self.assertNotIn("hooks", self.read_settings())
        # A linked development install must neither delete nor copy onto the source.
        (self.claude / "skills/pm").symlink_to(REPO / "mods/pm-dash/skill", target_is_directory=True)
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
        self.assertEqual(updated["hooks"]["Stop"][0], other)
        self.assertEqual(updated["hooks"]["SessionStart"][0], other)
        self.run_install()
        self.assertEqual((self.claude / "settings.json.pm-backup").read_text(), old_text)

    def test_desktop_is_optional_and_discord_is_gone(self):
        output = self.run_install()
        self.assertEqual(list(self.read_settings()["hooks"]), ["SessionStart", "UserPromptSubmit", "Stop"])
        self.assertNotIn("hook-mirror", self.settings.read_text())
        self.assertFalse(self.desktop.exists())
        self.assertIn("Skip desktop", output)
        self.assertNotIn("discord", output.lower())
        for command in ([str(REPO / "install.sh"), "--discord"], ["python3", str(BUNDLE / "setup.py"), "--discord"]):
            result = subprocess.run(command, env=self.env, cwd=self.root, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("unrecognized arguments: --discord", result.stderr)

    def test_shipped_layout(self):
        shipped = REPO / "layouts/pm.json"
        tree = json.loads(shipped.read_text())
        self.assertNotIn("generated_by", tree)
        self.assertEqual(tree["toast"], "pm-toast")
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
        expected["toast"] = "pm-toast"
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
        # A layout generated before pm-toast gets the field and keeps the person's edits.
        del actual["toast"]
        target.write_text(json.dumps(actual))
        self.assertIn('Add "toast": "pm-toast"', self.run_install())
        self.assertEqual(json.loads(target.read_text()), {**actual, "toast": "pm-toast"})
        self.assertFalse(target.with_name("pm.json.pm-backup").exists())
        # An unmarked pm layout is the person's: unchanged, with one line on adding it by hand.
        del actual["generated_by"]
        target.write_text(json.dumps(actual))
        own = target.read_bytes()
        output = self.run_install()
        self.assertIn(f'add "toast": "pm-toast" at the root of {target}', output)
        self.assertEqual(target.read_bytes(), own)
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
        self.run_install()
        ledger = self.root / ".dudu/tasks/task.json"
        ledger.parent.mkdir(parents=True)
        ledger.write_text('{"title":"keep"}')
        settings = self.read_settings()
        settings["hooks"]["SessionStart"][0]["hooks"].append(other)
        self.settings.write_text(json.dumps(settings))
        self.assertIn(f"Keep the ledger and configuration: {self.root / '.dudu'}.", self.run_install("--uninstall"))
        self.assertEqual(ledger.read_text(), '{"title":"keep"}')
        self.assertEqual(self.read_settings()["env"], original["env"])
        self.assertEqual(self.read_settings()["hooks"]["Stop"], original["hooks"]["Stop"])
        self.assertEqual(self.read_settings()["hooks"]["SessionStart"][0]["hooks"], [other])
        self.assertNotIn("skills/pm/scripts/pm.py", self.settings.read_text())
        for path in (self.claude / "skills/pm", self.desktop / "mods/pm-dash", self.desktop / "mods/pm-nav",
                     self.desktop / "mods/pm-toast", self.desktop / "layouts/pm.json"):
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
        for variable in ("CLAUDE_HOME", "CODEX_HOME", "PI_CODING_AGENT_DIR", "HERDR_APP_HOME"):
            self.env.pop(variable, None)
        (self.root / ".codex").mkdir()
        self.run_install("--agents", "claude,codex")
        for name, file in (("claude", "settings.json"), ("codex", "hooks.json")):
            settings = json.loads((self.root / f".{name}" / file).read_text())
            for event, action in (("SessionStart", "hook-session-start"), ("Stop", "hook-turn"),
                                  ("UserPromptSubmit", "hook-turn")):
                self.assertEqual(settings["hooks"][event][0]["hooks"][0]["command"],
                                 f"python3 ~/.{name}/skills/pm/scripts/pm.py {action}")

    def test_dry_run_writes_nothing(self):
        self.run_install("--dry-run", "--desktop")
        self.assertEqual(list(self.root.iterdir()), [])
        self.seed_layout()
        self.write_settings({"env": {"KEEP": "yes"}})
        def snapshot():
            return {str(path.relative_to(self.root)): path.read_bytes() if path.is_file() else None
                    for path in self.root.rglob("*")}
        before = snapshot()
        self.codex.mkdir()
        (self.codex / "hooks.json").write_text('{"hooks": {}}')
        self.pi.mkdir()
        before = snapshot()
        self.run_install("--dry-run", "--desktop")
        self.assertEqual(snapshot(), before)
        self.run_install("--desktop")
        before = snapshot()
        self.run_install("--uninstall", "--dry-run")
        self.assertEqual(snapshot(), before)

    def codex_hooks(self):
        return json.loads((self.codex / "hooks.json").read_text())

    def test_codex_keeps_its_hooks_file_and_replaces_mirror_hooks(self):
        self.codex.mkdir()
        other = {"hooks": [{"type": "command", "command": "'/opt/tool/bin/hook' codex-hook"}]}
        state = {"hooks": [{"type": "command", "command": "bash '/tmp/state.sh' session", "timeout": 10}]}
        old = "python3 ~/.codex/skills/pm/scripts/pm.py hook-mirror"
        mirror = {"hooks": [{"type": "command", "command": old, "timeout": 15, "async": True}]}
        original = {"hooks": {"PermissionRequest": [other], "SessionStart": [other, state],
                              "Stop": [other, mirror], "UserPromptSubmit": [mirror]}, "version": 1}
        text = json.dumps(original, indent=4)
        (self.codex / "hooks.json").write_text(text)
        (self.codex / "hooks.json").chmod(0o600)
        output = self.run_install()
        self.assertIn("Codex runs these hooks once you trust them", output)
        self.assertFalse(self.claude.exists() or self.pi.exists())  # only detected homes
        command = lambda action: f"python3 {shlex.quote(str(self.codex / 'skills/pm/scripts/pm.py'))} {action}"
        expected = copy.deepcopy(original)
        expected["hooks"]["SessionStart"].append(
            {"hooks": [{"type": "command", "command": command("hook-session-start"), "timeout": 10}]})
        expected["hooks"]["Stop"] = [other, {"hooks": [
            {"type": "command", "command": command("hook-turn"), "timeout": 15, "async": True}]}]
        expected["hooks"]["UserPromptSubmit"] = [{"hooks": [
            {"type": "command", "command": command("hook-turn"), "timeout": 15}]}]
        self.assertEqual(self.codex_hooks(), expected)
        self.assertEqual((self.codex / "hooks.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.codex / "hooks.json.pm-backup").read_text(), text)
        self.assertEqual(self.skill_files(self.codex), self.bundle_files())
        status = json.loads(self.run_setup("--status").stdout)
        self.assertTrue(all(status["agents"]["codex"][key] for key in ("skill_present", "hooks_present", "script_matches")))
        self.assertEqual(status["summary"], {"detected": ["codex"], "installed": ["codex"], "ready": ["codex"], "outdated": []})
        first = (self.codex / "hooks.json").read_bytes()
        self.run_install()
        self.assertEqual((self.codex / "hooks.json").read_bytes(), first)
        self.run_install("--uninstall")
        self.assertEqual(self.codex_hooks(), {"hooks": {"PermissionRequest": [other], "SessionStart": [other, state],
                                                        "Stop": [other]}, "version": 1})
        self.assertFalse((self.codex / "skills/pm").exists())
        self.assertEqual((self.codex / "hooks.json.pm-backup").read_text(), text)

    def test_invalid_codex_hooks_abort_every_agent(self):
        self.codex.mkdir()
        self.claude.mkdir()
        (self.codex / "hooks.json").write_text('{"hooks": {"Stop": {}}}')
        before = self.snapshot()
        result = self.run_setup(success=False)
        self.assertIn("hooks.json contains an unsupported hook structure", result.stderr)
        self.assertEqual(self.snapshot(), before)
        status = json.loads(self.run_setup("--status").stdout)
        self.assertIn("Install failed", status["agents"]["codex"]["error"])
        self.assertFalse(status["agents"]["codex"]["hooks_present"])

    def test_pi_gets_the_skill_only(self):
        self.pi.mkdir()
        self.run_setup()
        self.assertEqual(self.skill_files(self.pi), self.bundle_files())
        self.assertEqual(sorted(p.name for p in self.pi.iterdir()), ["skills"])
        self.assertFalse(self.claude.exists() or self.codex.exists())
        status = json.loads(self.run_setup("--status").stdout)
        self.assertNotIn("hooks_present", status["agents"]["pi"])
        self.assertEqual(status["summary"]["ready"], ["pi"])
        self.run_setup("--uninstall")
        self.assertEqual(list(self.pi.iterdir()), [self.pi / "skills"])
        self.assertEqual(list((self.pi / "skills").iterdir()), [])

    def test_agent_selection_and_default(self):
        # Default: every agent whose home exists.
        self.claude.mkdir()
        self.pi.mkdir()
        self.run_setup()
        self.assertTrue((self.claude / "skills/pm").is_dir() and (self.pi / "skills/pm").is_dir())
        self.assertFalse(self.codex.exists())
        status = json.loads(self.run_setup("--status").stdout)
        self.assertEqual(status["summary"]["detected"], ["claude", "pi"])
        self.assertEqual(status["summary"]["ready"], ["claude", "pi"])
        # Naming an agent installs it even without a home, and only it.
        (self.pi / "skills/pm/scripts/pm.py").write_text("old")
        self.run_setup("--agents", "codex")
        self.assertTrue((self.codex / "skills/pm/SKILL.md").is_file())
        self.assertEqual((self.pi / "skills/pm/scripts/pm.py").read_text(), "old")
        status = json.loads(self.run_setup("--status").stdout)
        self.assertEqual(status["summary"]["outdated"], ["pi"])
        self.assertEqual(status["summary"]["installed"], ["claude", "codex", "pi"])
        self.run_setup("--uninstall", "--agents", "pi,claude")
        self.assertFalse((self.pi / "skills/pm").exists() or (self.claude / "skills/pm").exists())
        self.assertTrue((self.codex / "skills/pm").exists())
        self.assertNotIn("hook-turn", self.settings.read_text())
        result = self.run_setup("--agents", "claude,gemini", success=False)
        self.assertIn("choose from claude, codex, pi", result.stderr)


if __name__ == "__main__":
    unittest.main()
