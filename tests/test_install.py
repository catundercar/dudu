import argparse
import contextlib
import copy
import fnmatch
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import sys
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "mods/pm-dash"
WINDOWS = os.name == "nt"
# Same node hierarchy as the shipped desktop main.json; no personal content.
MAIN = {
    "id": "root", "type": "row", "background": "canvas", "version": "1", "children": [
        {"id": "sidebar", "type": "column", "children": [
            {"id": "sidebar-lists", "type": "column", "children": [
                {"id": "spaces", "type": "block", "content": {"mod": "spaces"}},
                {"id": "agents", "type": "block", "content": {"mod": "agents"}}
            ]}
        ]},
        {"id": "work", "type": "column", "resizable": False, "children": [
            {"id": "tabs", "type": "block", "content": {"mod": "tabs"}}
        ]}
    ]
}
PM_LIST = {"id": "pm-list", "type": "block", "size": {"px": 30}, "content": {"mod": "pm-list"}}
PM_LIST_WEIGHT = {"id": "pm-list", "type": "block", "size": {"weight": 1}, "content": {"mod": "pm-list"}}
PM_BOARD = {"id": "pm-board", "type": "block", "window_drag": True, "content": {"mod": "pm-dash"}}
PM_PROJECT_HEADER = {
    "id": "pm-project-header", "type": "block", "size": {"px": 56},
    "window_drag": True, "content": {"mod": "pm-project", "props": {"header": True}},
}
PM_PROJECT_BODY = {
    "id": "pm-project-body", "type": "block",
    "content": {"mod": "pm-project", "props": {"body": True}},
}
PM_PROJECT = {
    "id": "pm-project", "type": "column", "resizable": False,
    "children": [PM_PROJECT_HEADER, PM_PROJECT_BODY],
}
MODS = ("pm-dash", "pm-nav", "pm-list", "pm-toast", "pm-project")
# What the skill install must leave out, written here on its own (not read from setup.py) so a wrong list there fails:
# any test file, any tests/ folder, Python's cache and Finder's file, matched against every part of a path.
SKILL_EXCLUDED = ("test_*.py", "tests", "__pycache__", ".DS_Store")


def skill_excluded(relative):
    return any(fnmatch.fnmatch(part, pattern) for part in Path(relative).parts for pattern in SKILL_EXCLUDED)


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
        self.env = dict(os.environ, HOME=str(self.root), USERPROFILE=str(self.root),
                        CLAUDE_HOME=str(self.claude), CODEX_HOME=str(self.codex),
                        PI_CODING_AGENT_DIR=str(self.pi), HERDR_APP_HOME=str(self.desktop))
        self.env.pop("PM_HOME", None)
        self.settings = self.claude / "settings.json"

    def run_install(self, *args):
        cmd = [sys.executable, str(REPO / "install.py"), *args] if WINDOWS else [str(REPO / "install.sh"), *args]
        result = subprocess.run(cmd, env=self.env, cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def read_settings(self):
        return json.loads(self.settings.read_text())

    def run_setup(self, *args, bundle=BUNDLE, success=True):
        result = subprocess.run([sys.executable, str(bundle / "setup.py"), *args], env=self.env,
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

    def test_setup_status_covers_every_skill_file_not_only_pm_py(self):
        bundle = self.root / "app home/mods/pm-dash"
        shutil.copytree(BUNDLE, bundle, ignore=shutil.ignore_patterns("__pycache__"))
        self.run_setup(bundle=bundle)
        installed = self.claude / "skills/pm/scripts"
        # Running pm.py writes __pycache__ beside it; a test file in the bundle is not installed: neither counts.
        subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pm_events",
                        str(installed)], check=True, env=self.env)
        self.assertTrue(list(installed.glob("__pycache__/*")))
        self.assertTrue(self.claude_status(bundle=bundle)["script_matches"])
        # pm.py from one version beside pm_events.py from another: outdated.
        events = bundle / "skill/scripts/pm_events.py"
        events.write_text(events.read_text() + "\n# a newer pm_events.py\n")
        status = json.loads(self.run_setup("--status", bundle=bundle).stdout)
        self.assertFalse(status["agents"]["claude"]["script_matches"])
        self.assertEqual(status["summary"]["outdated"], ["claude"])
        self.run_setup(bundle=bundle)
        self.assertTrue(self.claude_status(bundle=bundle)["script_matches"])
        self.assertEqual((installed / "pm_events.py").read_bytes(), events.read_bytes())

    def copied_bundle(self):
        bundle = self.root / "app home/mods/pm-dash"
        shutil.copytree(BUNDLE, bundle, ignore=shutil.ignore_patterns("__pycache__"))
        return bundle

    def test_scripts_tests_folder_is_never_installed_or_fingerprinted(self):
        bundle = self.copied_bundle()
        tests = bundle / "skill/scripts/tests"
        (tests / "golden").mkdir(parents=True, exist_ok=True)
        (tests / "replay_helper.py").write_text("print('not a test_ name, still under tests/')\n")
        (tests / "golden/extra.json").write_text("{}\n")
        self.run_setup(bundle=bundle)
        installed = self.claude / "skills/pm/scripts"
        self.assertTrue((installed / "pm.py").is_file())
        self.assertFalse((installed / "tests").exists())
        # A change under scripts/tests/ is not a change of the installed skill.
        (tests / "golden/extra.json").write_text('{"changed": true}\n')
        (tests / "another.py").write_text("x = 1\n")
        self.assertTrue(self.claude_status(bundle=bundle)["script_matches"])

    def test_a_test_file_of_any_name_is_never_installed_or_fingerprinted(self):
        bundle = self.copied_bundle()
        scripts = bundle / "skill/scripts"
        (scripts / "test_brand_new_area.py").write_text("import unittest\n")
        (scripts / "pmlib").mkdir(exist_ok=True)  # the bundle has pmlib/ since pm.py became a launcher
        (scripts / "pmlib/test_inside_package.py").write_text("import unittest\n")
        self.run_setup(bundle=bundle)
        installed = self.claude / "skills/pm/scripts"
        self.assertFalse((installed / "test_brand_new_area.py").exists())
        self.assertFalse((installed / "pmlib/test_inside_package.py").exists())
        (scripts / "test_brand_new_area.py").write_text("import unittest  # edited\n")
        (scripts / "test_yet_another.py").write_text("\n")
        self.assertTrue(self.claude_status(bundle=bundle)["script_matches"])

    def test_a_package_folder_beside_pm_py_is_installed_and_fingerprinted(self):
        bundle = self.copied_bundle()
        package = bundle / "skill/scripts/pmlib"
        package.mkdir(exist_ok=True)  # the bundle has pmlib/ since pm.py became a launcher
        (package / "__init__.py").write_text('"""pm.py\'s package."""\n')
        (package / "x.py").write_text("VALUE = 1\n")
        self.run_setup(bundle=bundle)
        installed = self.claude / "skills/pm/scripts/pmlib"
        self.assertEqual((installed / "__init__.py").read_bytes(), (package / "__init__.py").read_bytes())
        self.assertEqual((installed / "x.py").read_text(), "VALUE = 1\n")
        self.assertTrue(self.claude_status(bundle=bundle)["script_matches"])
        # pm.py of one version beside a pmlib module of another: outdated, and an update copies the module.
        (package / "x.py").write_text("VALUE = 2\n")
        status = json.loads(self.run_setup("--status", bundle=bundle).stdout)
        self.assertFalse(status["agents"]["claude"]["script_matches"])
        self.assertEqual(status["summary"]["outdated"], ["claude"])
        self.run_setup(bundle=bundle)
        self.assertEqual((installed / "x.py").read_text(), "VALUE = 2\n")
        self.assertTrue(self.claude_status(bundle=bundle)["script_matches"])
        # A module only in the installed copy (left from an older layout) counts too.
        (installed / "stale.py").write_text("OLD = True\n")
        self.assertFalse(self.claude_status(bundle=bundle)["script_matches"])

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
        if WINDOWS:
            setup_mod = load_module("pm_setup_cmp", BUNDLE / "setup.py")
            cmd_prefix = f"{setup_mod.python_command()} {setup_mod.Agent('claude', str(self.claude)).script_command}"
        else:
            cmd_prefix = "python3 ~/.claude/skills/pm/scripts/pm.py"
        expected["hooks"]["SessionStart"].append({"matcher": "^(startup|resume|clear|compact)$", "hooks": [{
            "type": "command", "command": f"{cmd_prefix} hook-session-start", "timeout": 10}]})
        expected["hooks"]["PreCompact"] = [{"hooks": [{"type": "command", "command":
            f"{cmd_prefix} hook-pre-compact", "timeout": 10}]}]
        expected["hooks"]["PreToolUse"] = [{"matcher": "AskUserQuestion|Bash|Edit|Write|MultiEdit|NotebookEdit", "hooks": [{"type": "command", "command":
            f"{cmd_prefix} hook-pre-tool", "timeout": 10}]}]
        expected["hooks"]["UserPromptSubmit"] = [{"hooks": [{"type": "command", "command":
            f"{cmd_prefix} hook-turn", "timeout": 15}]}]
        expected["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command":
            f"{cmd_prefix} hook-turn", "timeout": 15, "async": True}]}]
        self.assertEqual(self.read_settings(), expected)
        self.assertEqual(self.skill_files(self.claude), self.bundle_files())
        shutil.rmtree(self.claude)
        self.write_settings(original)
        self.settings.chmod(0o640)
        self.run_install()
        self.assertEqual(self.snapshot(), board)
        if not WINDOWS:
            self.assertEqual(self.settings.stat().st_mode & 0o777, 0o640)

    def claude_status(self, bundle=BUNDLE):
        return json.loads(self.run_setup("--status", bundle=bundle).stdout)["agents"]["claude"]

    @staticmethod
    def bundle_files():
        return {str(p.relative_to(BUNDLE / "skill")): p.read_bytes()
                for p in (BUNDLE / "skill").rglob("*") if p.is_file()
                and not skill_excluded(p.relative_to(BUNDLE / "skill"))}

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
        installed = self.claude / "skills/pm"
        self.assertEqual([str(p.relative_to(installed)) for p in installed.rglob("*") if p.name.startswith("test_")], [])
        self.assertFalse((installed / "scripts/tests").exists())
        self.assertTrue((BUNDLE / "skill/scripts/tests").is_dir())  # the bundle has one, so the check means something
        self.assertTrue((self.claude / "skills/pm/scripts/pm_events.py").is_file())
        self.assertTrue((self.claude / "skills/pm/scripts/pm_sessions.py").is_file())
        self.assertTrue((self.claude / "skills/pm/scripts/pm_store.py").is_file())
        self.assertTrue((self.claude / "skills/pm/scripts/pm_project.py").is_file())
        self.assertTrue((self.claude / "skills/pm/scripts/pmlib/cli.py").is_file())
        self.assertTrue((self.claude / "skills/pm/scripts/pmlib/procs.py").is_file())
        self.assertFalse(list((self.claude / "skills/pm").rglob("__pycache__")))
        for name in MODS:
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
        if WINDOWS:
            self.assertTrue(command["command"].endswith(" hook-session-start"))
            self.assertIn((self.claude / "skills/pm/scripts/pm.py").as_posix(), command["command"])
        else:
            self.assertEqual(shlex.split(command["command"]), ["python3", str(self.claude / "skills/pm/scripts/pm.py"), "hook-session-start"])
        pre = hooks["PreCompact"][0]["hooks"][0]
        self.assertFalse(pre.get("async", False))
        self.assertEqual(pre["timeout"], 10)
        self.assertTrue(pre["command"].endswith(" hook-pre-compact"))
        pre_tool = hooks["PreToolUse"][0]
        self.assertEqual(pre_tool["matcher"], "AskUserQuestion|Bash|Edit|Write|MultiEdit|NotebookEdit")
        self.assertFalse(pre_tool["hooks"][0].get("async", False))
        self.assertEqual(pre_tool["hooks"][0]["timeout"], 10)
        self.assertTrue(pre_tool["hooks"][0]["command"].endswith(" hook-pre-tool"))
        for event in ("UserPromptSubmit", "Stop"):
            hook = hooks[event][0]["hooks"][0]
            # The prompt hook's output joins the session's context, so only Stop may run in the background.
            self.assertEqual(hook.get("async", False), event == "Stop")
            self.assertEqual(hook["timeout"], 15)
            self.assertTrue(hook["command"].endswith(" hook-turn"))
        self.assertFalse(self.codex.exists() or self.pi.exists())
        # The installed launcher finds its package: `state` runs, on a ledger home of its own.
        state = subprocess.run([sys.executable, str(self.claude / "skills/pm/scripts/pm.py"), "state"], text=True,
                               capture_output=True, env=dict(self.env, PM_HOME=str(self.root / "ledger")))
        self.assertEqual(state.returncode, 0, state.stderr)
        self.assertEqual(json.loads(state.stdout)["tasks"], [])

    def test_repeat_install_is_identical(self):
        self.run_install("--desktop")
        first = self.settings.read_bytes()
        stale = [self.claude / "skills/pm/removed.txt", *(self.desktop / "mods" / name / "removed.txt" for name in MODS)]
        for path in stale:
            path.write_text("obsolete")
        self.run_install()
        for path in stale:
            self.assertFalse(path.exists())
        self.assertEqual(self.settings.read_bytes(), first)
        self.assertEqual([len(entries) for entries in self.read_settings()["hooks"].values()], [1, 1, 1, 1, 1])
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
        self.assertEqual(list(self.read_settings()["hooks"]), ["SessionStart", "PreCompact", "PreToolUse", "UserPromptSubmit", "Stop"])
        self.assertNotIn("hook-mirror", self.settings.read_text())
        self.assertFalse(self.desktop.exists())
        self.assertIn("Skip desktop", output)
        self.assertNotIn("discord", output.lower())
        cmds = [
            *(() if WINDOWS else ([str(REPO / "install.sh"), "--discord"],)),
            [sys.executable, str(REPO / "install.py"), "--discord"],
            [sys.executable, str(BUNDLE / "setup.py"), "--discord"],
        ]
        for command in cmds:
            result = subprocess.run(command, env=self.env, cwd=self.root, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("unrecognized arguments: --discord", result.stderr)

    def test_shipped_layout(self):
        shipped = REPO / "layouts/dudu.json"
        tree = json.loads(shipped.read_text())
        self.assertNotIn("generated_by", tree)
        self.assertEqual(tree["toast"], "pm-toast")
        sidebar, stage = tree["children"]
        lists = next(node for node in sidebar["children"] if node["id"] == "sidebar-lists")
        self.assertEqual(lists["children"][0], {
            "id": "pm-nav", "type": "block", "size": {"px": 64}, "content": {"mod": "pm-nav"}})
        self.assertEqual([node["id"] for node in lists["children"]], ["pm-nav", "pm-list", "herdr-lists"])
        self.assertEqual(lists["children"][1], PM_LIST_WEIGHT)
        drawer = lists["children"][2]
        self.assertEqual(drawer["type"], "column")
        self.assertEqual(drawer["hidden"], True)
        self.assertEqual(drawer["size"], {"weight": 1})
        self.assertEqual([node["id"] for node in drawer["children"]], ["spaces", "agents"])
        self.assertEqual(drawer["children"][-1]["content"]["mod"], "agents")
        self.assertEqual(stage["id"], "pm-stage")
        self.assertEqual(stage["type"], "stack")
        self.assertEqual(stage["active"], "pm-board")
        self.assertEqual([node["id"] for node in stage["children"]], ["work", "pm-board", "pm-project"])
        self.assertEqual(stage["children"][0]["type"], "column")
        self.assertEqual(stage["children"][1:], [PM_BOARD, PM_PROJECT])

        # Adding the directory layout first must not transfer ownership to the installer.
        self.seed_layout()
        target = self.desktop / "layouts/dudu.json"
        target.write_bytes(shipped.read_bytes())
        self.assertIn("already contains pm-nav", self.run_install())
        self.assertEqual(target.read_bytes(), shipped.read_bytes())
        self.assertIn("Keep layout", self.run_install("--uninstall"))
        self.assertEqual(target.read_bytes(), shipped.read_bytes())

    def test_layout(self):
        source = self.seed_layout()
        source_bytes = source.read_bytes()
        self.run_install()  # Existing HERDR_APP_HOME enables desktop automatically.
        target = self.desktop / "layouts/dudu.json"
        actual = json.loads(target.read_text())
        expected = copy.deepcopy(MAIN)
        expected["toast"] = "pm-toast"
        expected["generated_by"] = "dudu install.sh"
        expected["cloned_from"] = {"name": "main", "version": "1"}
        expected["children"][0]["children"][0]["children"] = [
            {"id": "pm-nav", "type": "block", "size": {"px": 64}, "content": {"mod": "pm-nav"}},
            PM_LIST_WEIGHT,
            {
                "id": "herdr-lists", "type": "column", "hidden": True, "size": {"weight": 1},
                "children": copy.deepcopy(MAIN["children"][0]["children"][0]["children"]),
            },
        ]
        expected["children"][1] = {"id": "pm-stage", "type": "stack", "active": "pm-board", "children": [
            copy.deepcopy(MAIN["children"][1]), PM_BOARD, PM_PROJECT]}
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
        self.assertFalse(target.with_name("dudu.json.pm-backup").exists())
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
        self.assertEqual(target.with_name("dudu.json.pm-backup").read_bytes(), previous)
        self.assertEqual(json.loads(target.read_text())["generated_by"], "dudu install.sh")

    def seed_pm_agents(self, own=False):
        """What an install of pull request #2 left: mods/pm-agents (a clone of agents) and the pm layout's agents
        block pointing at it. own: a mod of the person's that happens to have that name."""
        mod = self.desktop / "mods/pm-agents"
        mod.mkdir(parents=True)
        (mod / "mod.json").write_text(json.dumps({"place": "none", "title": "Agents"} if own else
                                                 {"place": "none", "title": "Agents",
                                                  "cloned_from": {"name": "agents", "version": "0.1.16"}}))
        (mod / "model.js").write_text("export function mine() {}" if own else "export function includePMs() {}")
        (mod / "main.js").write_text("export default class Agents {}")
        layout = json.loads((REPO / "layouts/dudu.json").read_text())
        drawer = layout["children"][0]["children"][1]["children"][-1]
        block = drawer["children"][-1]
        block["content"]["mod"] = "pm-agents"
        target = self.desktop / "layouts/dudu.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(layout))
        return mod, target, layout, block

    def test_an_install_over_pull_request_2_gives_the_agents_block_back_and_removes_pm_agents(self):
        self.seed_layout()
        mod, target, layout, block = self.seed_pm_agents()
        before = target.read_bytes()
        self.run_install("--dry-run")
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue(mod.is_dir())
        output = self.run_install()
        self.assertIn("Show agents instead of pm-agents (retired)", output)
        self.assertFalse(mod.exists())
        self.assertEqual(target.with_name("dudu.json.pm-backup").read_bytes(), before)
        block["content"]["mod"] = "agents"
        self.assertEqual(json.loads(target.read_text()), layout)
        self.assertIn("Skip layout", self.run_install())  # nothing left to migrate

    def test_uninstall_removes_pm_agents_and_its_block(self):
        self.seed_layout()
        mod, target, layout, block = self.seed_pm_agents()
        output = self.run_install("--uninstall")
        self.assertIn("Keep layout", output)
        self.assertFalse(mod.exists())
        block["content"]["mod"] = "agents"
        self.assertEqual(json.loads(target.read_text()), layout)

    def test_a_pm_agents_mod_of_the_persons_own_is_kept(self):
        self.seed_layout()
        mod, target, layout, block = self.seed_pm_agents(own=True)
        self.assertIn("not the pm-agents mod this installer shipped", self.run_install())
        self.assertTrue((mod / "main.js").is_file())
        self.assertEqual(json.loads(target.read_text()), layout)  # its block keeps pointing at it
        self.assertIn("not the pm-agents mod this installer shipped", self.run_install("--uninstall"))
        self.assertTrue((mod / "main.js").is_file())
        self.assertEqual(json.loads(target.read_text()), layout)

    def test_existing_layout_gets_pm_list(self):
        # A pm layout from before pm-list, unmarked and edited by the person (as Herdr rewrites it).
        self.seed_layout()
        target = self.desktop / "layouts/dudu.json"
        layout = json.loads((REPO / "layouts/dudu.json").read_text())
        lists = layout["children"][0]["children"][1]
        # Flatten herdr-lists back to pre-drawer layout for legacy pm-list migration tests.
        drawer = lists["children"][2]
        lists["children"] = [lists["children"][0], *drawer["children"]]
        lists["children"][1]["size"] = {"px": 200}
        layout["background"] = "custom"
        target.write_text(json.dumps(layout))
        before = target.read_bytes()
        output = self.run_install("--dry-run")
        self.assertIn(f"Would Add the pm-list block to {target}", output)
        self.assertIn(f"Would Hide spaces and agents in herdr-lists drawer in {target}", output)
        self.assertEqual(target.read_bytes(), before)
        output = self.run_install()
        self.assertIn(f"Add the pm-list block to {target}", output)
        self.assertIn(f"Hide spaces and agents in herdr-lists drawer in {target}", output)
        self.assertEqual(target.with_name("dudu.json.pm-backup").read_bytes(), before)
        expected = copy.deepcopy(layout)
        expected["children"][0]["children"][1]["children"] = [
            expected["children"][0]["children"][1]["children"][0],
            PM_LIST_WEIGHT,
            {
                "id": "herdr-lists", "type": "column", "hidden": True, "size": {"weight": 1},
                "children": expected["children"][0]["children"][1]["children"][1:],
            },
        ]
        self.assertEqual(json.loads(target.read_text()), expected)
        # Once added, later installs leave the layout alone (even if user toggles hidden: false).
        output = self.run_install()
        self.assertIn("already contains pm-nav", output)
        self.assertNotIn("move the pm-list block", output)
        self.assertEqual(json.loads(target.read_text()), expected)
        expected_open = copy.deepcopy(expected)
        expected_open["children"][0]["children"][1]["children"][2]["hidden"] = False
        target.write_text(json.dumps(expected_open))
        self.assertIn("already contains pm-nav", self.run_install())
        self.assertEqual(json.loads(target.read_text()), expected_open)
        # Where earlier installers put the list (right above agents): a hint, and the layout stays as it is.
        old = copy.deepcopy(layout)
        old["children"][0]["children"][1]["children"].insert(2, PM_LIST)
        self.assertEqual([node["id"] for node in old["children"][0]["children"][1]["children"]],
                         ["pm-nav", "spaces", "pm-list", "agents"])
        target.write_text(json.dumps(old))
        output = self.run_install()
        self.assertIn(f"move the pm-list block right after pm-nav in {target}", output)
        self.assertEqual(json.loads(target.read_text()), old)
        # A column without an agents block gets the list in the same place.
        del layout["toast"]
        lists["children"] = [node for node in lists["children"] if node["id"] != "agents"]
        target.write_text(json.dumps(layout))
        output = self.run_install()
        self.assertIn(f'add "toast": "pm-toast" at the root of {target}', output)
        self.assertEqual([node["id"] for node in json.loads(target.read_text())["children"][0]["children"][1]["children"]],
                         ["pm-nav", "pm-list", "spaces"])
        self.assertNotIn("toast", json.loads(target.read_text()))
        # pm-nav at the root (no column to join): only a hint, the layout stays as it is.
        target.write_text(json.dumps({"id": "pm-nav", "type": "block", "toast": "pm-toast", "content": {"mod": "pm-nav"}}))
        own = target.read_bytes()
        output = self.run_install()
        self.assertIn("Skip pm-list: no column", output)
        self.assertIn('"id":"pm-list"', output)
        self.assertNotIn("Manual fallback", output)
        self.assertEqual(target.read_bytes(), own)

    def test_existing_layout_gets_pm_project(self):
        # A pm layout from before the project view, unmarked and edited by the person.
        self.seed_layout()
        target = self.desktop / "layouts/dudu.json"
        layout = json.loads((REPO / "layouts/dudu.json").read_text())
        stage = layout["children"][1]
        stage["children"] = stage["children"][:2]
        layout["background"] = "custom"
        target.write_text(json.dumps(layout))
        before = target.read_bytes()
        self.assertIn(f"Would Add the pm-project block to {target}", self.run_install("--dry-run"))
        self.assertEqual(target.read_bytes(), before)
        self.assertIn(f"Add the pm-project block to {target}", self.run_install())
        self.assertEqual(target.with_name("dudu.json.pm-backup").read_bytes(), before)
        expected = copy.deepcopy(layout)
        expected["children"][1]["children"].append(PM_PROJECT)
        self.assertEqual(json.loads(target.read_text()), expected)
        # Once there, wherever the person put it, later installs leave the layout alone.
        self.assertIn("already contains pm-nav", self.run_install())
        self.assertEqual(json.loads(target.read_text()), expected)
        # Without a pm-stack there is nowhere to add it: the layout stays as it is.
        lone = {"id": "root", "type": "column", "toast": "pm-toast", "children": [
            {"id": "pm-nav", "type": "block", "content": {"mod": "pm-nav"}}, PM_LIST]}
        target.write_text(json.dumps(lone))
        own = target.read_bytes()
        self.assertIn("already contains pm-nav", self.run_install())
        self.assertEqual(target.read_bytes(), own)

    def test_existing_layout_gets_window_drag(self):
        # A pm layout from before pm-board had window_drag, and with legacy single-block pm-project.
        self.seed_layout()
        target = self.desktop / "layouts/dudu.json"
        layout = json.loads((REPO / "layouts/dudu.json").read_text())
        board = layout["children"][1]["children"][1]
        del board["window_drag"]
        layout["children"][1]["children"][2] = {
            "id": "pm-project", "type": "block", "window_drag": True, "content": {"mod": "pm-project"},
        }
        layout["background"] = "custom"
        target.write_text(json.dumps(layout))
        before = target.read_bytes()
        board_msg = f"Let the pm-board title bar move the window in {target}"
        proj_msg = f"Split pm-project into header and body blocks in {target}"
        dry = self.run_install("--dry-run")
        self.assertIn(f"Would {board_msg}", dry)
        self.assertIn(f"Would {proj_msg}", dry)
        self.assertEqual(target.read_bytes(), before)
        applied = self.run_install()
        self.assertIn(board_msg, applied)
        self.assertIn(proj_msg, applied)
        self.assertEqual(target.with_name("dudu.json.pm-backup").read_bytes(), before)
        expected = copy.deepcopy(layout)
        expected["children"][1]["children"][1:] = copy.deepcopy([PM_BOARD, PM_PROJECT])
        self.assertEqual(json.loads(target.read_text()), expected)
        self.assertIn("already contains pm-nav", self.run_install())
        # Legacy single-block pm-project with explicit window_drag=False and custom keys preserves all unknown keys.
        layout_no_drag = copy.deepcopy(expected)
        layout_no_drag["children"][1]["children"][2] = {
            "id": "pm-project", "type": "block", "window_drag": False,
            "background": "surface", "size": {"weight": 2}, "min": 420,
            "content": {"mod": "pm-project"},
        }
        target.write_text(json.dumps(layout_no_drag))
        self.assertIn(proj_msg, self.run_install())
        migrated = json.loads(target.read_text())
        migrated_proj = migrated["children"][1]["children"][2]
        self.assertEqual(migrated_proj["type"], "column")
        self.assertEqual(migrated_proj["background"], "surface")
        self.assertEqual(migrated_proj["size"], {"weight": 2})
        self.assertEqual(migrated_proj["min"], 420)
        self.assertNotIn("window_drag", migrated_proj)
        self.assertNotIn("content", migrated_proj)
        self.assertEqual(migrated_proj["children"][0]["window_drag"], False)
        self.assertNotIn("window_drag", migrated_proj["children"][1])
        # Non-matching nodes (explicit False on pm-board, other mods sharing the id, or already a column) stay untouched.
        stage = expected["children"][1]["children"]
        stage[1]["window_drag"] = False
        stage.append({"id": "pm-board", "type": "block", "content": {"mod": "other"}})
        stage.append({"id": "pm-project", "type": "block", "window_drag": True, "content": {"mod": "other"}})
        stage.append({"id": "pm-project", "type": "column", "window_drag": True, "content": {"mod": "pm-project"}, "children": []})
        target.write_text(json.dumps(expected))
        own = target.read_bytes()
        self.assertIn("already contains pm-nav", self.run_install())
        self.assertEqual(target.read_bytes(), own)

    def test_migrates_legacy_pm_layout_safely(self):
        # Existing user with customized layouts/pm.json (no dudu.json yet): copy to dudu.json,
        # keep pm.json intact so a running pm layout is not disrupted, and apply pending upgrades.
        self.seed_layout()
        legacy = self.desktop / "layouts/pm.json"
        target = self.desktop / "layouts/dudu.json"
        layout = json.loads((REPO / "layouts/dudu.json").read_text())
        layout["background"] = "custom-canvas"
        layout["font"] = "Custom Mono"
        layout["generated_by"] = "dudu install.sh"
        legacy.write_text(json.dumps(layout))
        before = legacy.read_bytes()

        dry = self.run_install("--dry-run")
        self.assertIn(f"Would Migrate {legacy} to {target}", dry)
        self.assertFalse(target.exists())
        self.assertEqual(legacy.read_bytes(), before)

        output = self.run_install()
        self.assertIn(f"Migrate {legacy} to {target}", output)
        self.assertIn(f"Kept {legacy}", output)
        self.assertIn('layout.switch \'{"name":"dudu"}\'', output)
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(legacy.read_bytes(), before)
        self.assertFalse(target.with_name("dudu.json.pm-backup").exists())

        # Subsequent run is idempotent and does not overwrite edits made to dudu.json.
        updated = json.loads(target.read_text())
        updated["background"] = "dudu-edited"
        target.write_text(json.dumps(updated))
        dudu_bytes = target.read_bytes()
        again = self.run_install()
        self.assertIn("already contains pm-nav", again)
        self.assertEqual(target.read_bytes(), dudu_bytes)
        self.assertEqual(legacy.read_bytes(), before)

        # Migrating an older pm.json (missing pm-list and toast) upgrades dudu.json while leaving pm.json untouched.
        target.unlink()
        old = json.loads((REPO / "layouts/dudu.json").read_text())
        old["background"] = "old-custom"
        old["generated_by"] = "dudu install.sh"
        del old["toast"]
        old["children"][0]["children"][1]["children"] = [
            node for node in old["children"][0]["children"][1]["children"] if node["id"] != "pm-list"
        ]
        legacy.write_text(json.dumps(old))
        old_bytes = legacy.read_bytes()
        upgraded_out = self.run_install()
        self.assertIn(f"Migrate {legacy} to {target}", upgraded_out)
        self.assertIn(f"Add the pm-list block to {target}", upgraded_out)
        self.assertIn('Add "toast": "pm-toast"', upgraded_out)
        self.assertEqual(legacy.read_bytes(), old_bytes)
        migrated = json.loads(target.read_text())
        self.assertEqual(migrated["background"], "old-custom")
        self.assertEqual(migrated["toast"], "pm-toast")
        self.assertEqual([n["id"] for n in migrated["children"][0]["children"][1]["children"]],
                         ["pm-nav", "pm-list", "herdr-lists"])

        # An unrelated pm.json (without pm-nav, or invalid JSON) is left untouched and dudu.json is generated from main.json.
        for unrelated in ('{"id":"custom","type":"row","children":[]}', '{invalid'):
            with self.subTest(unrelated=unrelated):
                target.unlink(missing_ok=True)
                legacy.write_text(unrelated)
                out = self.run_install()
                self.assertIn(f"Generate {target}", out)
                self.assertEqual(legacy.read_text(), unrelated)
                self.assertEqual(json.loads(target.read_text())["generated_by"], "dudu install.sh")

    def test_migrates_stage_active_work_to_board(self):
        self.seed_layout()
        target = self.desktop / "layouts/dudu.json"
        layout = json.loads((REPO / "layouts/dudu.json").read_text())
        layout["children"][1]["active"] = "work"
        target.write_text(json.dumps(layout))
        before = target.read_bytes()

        output = self.run_install()
        self.assertIn(f"Default pm-stage to pm-board in {target}", output)
        migrated = json.loads(target.read_text())
        self.assertEqual(migrated["children"][1]["active"], "pm-board")
        self.assertEqual(target.with_name("dudu.json.pm-backup").read_bytes(), before)

        # Custom active (e.g. pm-project) is left untouched.
        migrated["children"][1]["active"] = "pm-project"
        target.write_text(json.dumps(migrated))
        custom = target.read_bytes()
        self.assertIn("already contains pm-nav", self.run_install())
        self.assertEqual(target.read_bytes(), custom)

    def test_uninstall_handles_legacy_pm_layout(self):
        self.seed_layout()
        legacy = self.desktop / "layouts/pm.json"
        target = self.desktop / "layouts/dudu.json"
        marked = json.loads((REPO / "layouts/dudu.json").read_text())
        marked["generated_by"] = "dudu install.sh"
        legacy.write_text(json.dumps(marked))
        self.run_install()
        self.assertTrue(target.is_file())
        self.assertTrue(legacy.is_file())
        # Uninstall removes both marked dudu.json and marked legacy pm.json.
        self.run_install("--uninstall")
        self.assertFalse(target.exists())
        self.assertFalse(legacy.exists())

        # Unmarked legacy pm.json is preserved on uninstall.
        unmarked = (REPO / "layouts/dudu.json").read_bytes()
        legacy.write_bytes(unmarked)
        out = self.run_install("--uninstall")
        self.assertIn(f"Keep layout {legacy}", out)
        self.assertEqual(legacy.read_bytes(), unmarked)

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
        for path in (self.claude / "skills/pm", *(self.desktop / "mods" / name for name in MODS), self.desktop / "layouts/dudu.json"):
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
                cmd = [sys.executable, str(REPO / "install.py"), "--desktop"] if WINDOWS else [str(REPO / "install.sh"), "--desktop"]
                result = subprocess.run(cmd, env=self.env, cwd=self.root, text=True, capture_output=True)
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
                self.assertTrue(self.backups())  # a folder that is not what an install copied is kept aside first
                shutil.rmtree(self.root / ".dudu")
                self.assertEqual(self.settings.read_text(), invalid)
                installed.parent.rmdir()

    def test_uninstall_preserves_unmarked_layout(self):
        self.seed_layout()
        target = self.desktop / "layouts/dudu.json"
        for content in ('{"id":"custom","type":"row","children":[]}',
                        '{"id":"pm-nav","type":"block"}', '{invalid'):
            with self.subTest(layout=content):
                target.write_text(content)
                self.assertIn("Keep layout", self.run_install("--uninstall"))
                self.assertEqual(target.read_text(), content)

    @unittest.skipIf(WINDOWS, "tilde hook paths are POSIX-only; Windows uses absolute paths")
    def test_default_hook_path_uses_tilde(self):
        self.env["HOME"] = str(self.root)
        for variable in ("CLAUDE_HOME", "CODEX_HOME", "PI_CODING_AGENT_DIR", "HERDR_APP_HOME"):
            self.env.pop(variable, None)
        (self.root / ".codex").mkdir()
        self.run_install("--agents", "claude,codex")
        for name, file in (("claude", "settings.json"), ("codex", "hooks.json")):
            settings = json.loads((self.root / f".{name}" / file).read_text())
            for event, action in (("SessionStart", "hook-session-start"), ("PreCompact", "hook-pre-compact"),
                                  ("PreToolUse", "hook-pre-tool"),
                                  ("Stop", "hook-turn"), ("UserPromptSubmit", "hook-turn")):
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

    def backups(self):
        folder = self.root / ".dudu/install/backups"
        return sorted(folder.iterdir()) if folder.is_dir() else []

    def test_local_changes_are_backed_up_before_an_install_replaces_them(self):
        skill = self.claude / "skills/pm"
        self.run_install()
        self.assertEqual(self.backups(), [])
        self.assertNotIn("Back up local changes", self.run_install())  # nothing changed since: no backup
        (skill / "SKILL.md").write_text("edited here")
        (skill / "scripts/mine.py").write_text("print(1)")
        (skill / "scripts/__pycache__").mkdir()
        (skill / "scripts/__pycache__/pm.cpython-39.pyc").write_bytes(b"cache")  # Python's cache is no change
        output = self.run_setup("--dry-run").stdout
        self.assertIn("Would Back up local changes", output)
        self.assertEqual(self.backups(), [])  # a dry run writes nothing
        output = self.run_install()
        self.assertIn("it differs from what the last install copied", output)
        self.assertIn("change it there and install again", output)
        backup, = self.backups()
        self.assertEqual((backup / "SKILL.md").read_text(), "edited here")
        self.assertEqual((backup / "scripts/mine.py").read_text(), "print(1)")
        self.assertEqual(self.skill_files(self.claude), self.bundle_files())
        self.assertNotIn("Back up local changes", self.run_install())

    def test_an_install_from_before_the_record_is_backed_up_when_it_differs(self):
        skill = self.claude / "skills/pm"
        shutil.copytree(BUNDLE / "skill", skill, ignore=shutil.ignore_patterns(*SKILL_EXCLUDED))
        self.assertNotIn("Back up local changes", self.run_install())  # the same files as the bundle
        (self.root / ".dudu/install/skill-claude.json").unlink()
        (skill / "scripts/pm.py").write_text("# an older or edited copy\n")
        output = self.run_install()
        self.assertIn("no record of the last install", output)
        backup, = self.backups()
        self.assertEqual((backup / "scripts/pm.py").read_text(), "# an older or edited copy\n")

    def test_uninstall_backs_up_local_changes_and_a_linked_skill_keeps_its_folder(self):
        skill = self.claude / "skills/pm"
        self.run_install()
        (skill / "SKILL.md").write_text("edited here")
        self.assertIn("Back up local changes", self.run_install("--uninstall"))
        self.assertFalse(skill.exists())
        self.assertFalse((self.root / ".dudu/install/skill-claude.json").exists())
        elsewhere = self.root / "agents/skills/pm"
        shutil.copytree(BUNDLE / "skill", elsewhere)
        (elsewhere / "SKILL.md").write_text("edited elsewhere")
        skill.symlink_to(elsewhere, target_is_directory=True)
        output = self.run_install()
        self.assertIn("the link goes, that folder is left as it is", output)
        self.assertFalse(skill.is_symlink())
        self.assertEqual((elsewhere / "SKILL.md").read_text(), "edited elsewhere")

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
        if WINDOWS:
            setup_mod = load_module("pm_setup_codex", BUNDLE / "setup.py")
            prefix = f"{setup_mod.python_command()} {setup_mod.Agent('codex', str(self.codex)).script_command}"
            command = lambda action: f"{prefix} {action}"
        else:
            command = lambda action: f"python3 {shlex.quote(str(self.codex / 'skills/pm/scripts/pm.py'))} {action}"
        expected = copy.deepcopy(original)
        expected["hooks"]["SessionStart"].append(
            {"hooks": [{"type": "command", "command": command("hook-session-start"), "timeout": 10}]})
        expected["hooks"]["PreCompact"] = [{"hooks": [
            {"type": "command", "command": command("hook-pre-compact"), "timeout": 10}]}]
        expected["hooks"]["PreToolUse"] = [{"matcher": "request_user_input|ask_user|AskUserQuestion|Bash|shell|local_shell_call|apply_patch|write_file|edit_file|Edit|Write", "hooks": [
            {"type": "command", "command": command("hook-pre-tool"), "timeout": 10}]}]
        expected["hooks"]["Stop"] = [other, {"hooks": [
            {"type": "command", "command": command("hook-turn"), "timeout": 15, "async": True}]}]
        expected["hooks"]["UserPromptSubmit"] = [{"hooks": [
            {"type": "command", "command": command("hook-turn"), "timeout": 15}]}]
        self.assertEqual(self.codex_hooks(), expected)
        if not WINDOWS:
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

    @unittest.skipIf(WINDOWS or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "POSIX mode bits stand in for the Windows DACL an elevated install leaves; root reads anything")
    def test_unreadable_skill_folder_neither_fails_status_nor_blocks_set_up(self):
        # Windows host: an elevated install left skills/pm owned by Administrators with a DACL that
        # grants the user nothing; `setup.py --status` then failed as a whole ("Install failed: [WinError 5]"),
        # so pm-nav showed "Set up" and wrote no cache of other machines' projects.
        self.claude.mkdir()
        self.codex.mkdir()
        self.run_setup()
        scripts = self.claude / "skills/pm/scripts"
        scripts.chmod(0)
        self.addCleanup(lambda: scripts.chmod(0o755) if scripts.exists() else None)
        status = json.loads(self.run_setup("--status").stdout)
        claude = status["agents"]["claude"]
        self.assertTrue(claude["unreadable"])
        self.assertFalse(claude["skill_present"])
        self.assertIn("Cannot read", claude["error"])
        self.assertIn("Repair it", claude["error"])
        self.assertEqual(status["summary"]["installed"], ["codex"])
        self.assertEqual(status["summary"]["ready"], ["codex"])
        # Set up cannot take the folder back without privileges: it stops before writing anything and says how.
        before = self.snapshot_readable()
        result = self.run_setup(success=False)
        self.assertIn("Cannot read", result.stderr)
        self.assertIn("Repair it", result.stderr)
        self.assertEqual(self.snapshot_readable(), before)
        # Once repaired, Set up and status are whole again.
        scripts.chmod(0o755)
        self.run_setup()
        status = json.loads(self.run_setup("--status").stdout)
        self.assertEqual(status["summary"]["ready"], ["claude", "codex"])
        self.assertNotIn("error", status)

    def snapshot_readable(self):
        return {str(p.relative_to(self.root)): p.read_bytes() if p.is_file() else None
                for p in self.root.rglob("*") if os.access(p, os.R_OK)}

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

    def run_install_py(self, *args):
        result = subprocess.run([sys.executable, str(REPO / "install.py"), *args], env=self.env,
                                cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_install_py_matches_install_sh_and_needs_no_bash(self):
        # Running install.py directly (as on Windows without Bash) produces identical files, hooks, and layout.
        self.seed_layout()
        self.write_settings({"env": {"KEEP": "yes"}})
        pyc_before = sorted(str(p) for p in (REPO / "__pycache__", BUNDLE / "__pycache__") if p.exists()
                            for p in p.rglob("*"))
        self.run_install_py("--dry-run", "--desktop")
        self.assertFalse((self.claude / "skills/pm").exists())
        self.assertFalse((self.desktop / "layouts/dudu.json").exists())
        pyc_after = sorted(str(p) for p in (REPO / "__pycache__", BUNDLE / "__pycache__") if p.exists()
                           for p in p.rglob("*"))
        self.assertEqual(pyc_after, pyc_before)

        self.run_install_py("--desktop")
        py_snapshot = self.snapshot()
        layout = json.loads((self.desktop / "layouts/dudu.json").read_text())
        self.assertEqual(layout["generated_by"], "dudu install.sh")
        self.assertEqual(layout["toast"], "pm-toast")
        self.assertEqual(layout["children"][1]["children"][1:], [PM_BOARD, PM_PROJECT])
        for name in MODS:
            self.assertTrue((self.desktop / "mods" / name / "main.js").is_file())
        self.assertTrue((self.claude / "skills/pm/scripts/pm.py").is_file())

        # Re-running with install.sh is identical, and install.py --uninstall cleans up cleanly.
        self.run_install("--desktop")
        self.assertEqual(self.snapshot(), py_snapshot)
        self.run_install_py("--uninstall")
        self.assertFalse((self.claude / "skills/pm").exists())
        self.assertFalse((self.desktop / "layouts/dudu.json").exists())
        for name in MODS:
            self.assertFalse((self.desktop / "mods" / name).exists())
        self.assertNotIn("hooks", self.read_settings())

    def test_install_py_splits_legacy_pm_project_and_rejects_reserved_split_ids(self):
        self.seed_layout()
        target = self.desktop / "layouts/dudu.json"
        layout = json.loads((REPO / "layouts/dudu.json").read_text())
        layout["children"][1]["children"][2] = {
            "id": "pm-project", "type": "block", "window_drag": False,
            "background": "surface", "size": {"weight": 2},
            "content": {"mod": "pm-project"},
        }
        target.write_text(json.dumps(layout))
        before = target.read_bytes()
        proj_msg = f"Split pm-project into header and body blocks in {target}"
        self.assertIn(f"Would {proj_msg}", self.run_install_py("--dry-run"))
        self.assertEqual(target.read_bytes(), before)
        self.assertIn(proj_msg, self.run_install_py())
        self.assertEqual(target.with_name("dudu.json.pm-backup").read_bytes(), before)
        migrated = json.loads(target.read_text())["children"][1]["children"][2]
        self.assertEqual(migrated["type"], "column")
        self.assertEqual(migrated["resizable"], False)
        self.assertEqual(migrated["background"], "surface")
        self.assertEqual(migrated["size"], {"weight": 2})
        self.assertNotIn("window_drag", migrated)
        self.assertNotIn("content", migrated)
        self.assertEqual(migrated["children"][0], dict(PM_PROJECT_HEADER, window_drag=False))
        self.assertEqual(migrated["children"][1], PM_PROJECT_BODY)
        # Idempotent once split.
        self.assertIn("already contains pm-nav", self.run_install_py())

        # main.json containing pm-project-header or pm-project-body falls back to manual layout.
        for reserved in ("pm-project-header", "pm-project-body"):
            with self.subTest(reserved=reserved):
                target.unlink(missing_ok=True)
                bad_main = copy.deepcopy(MAIN)
                bad_main["children"][1]["children"].append({"id": reserved, "type": "block", "content": {"mod": "other"}})
                self.seed_layout(bad_main)
                self.assertIn("Manual fallback", self.run_install_py())
                self.assertFalse(target.exists())

    @unittest.skipIf(WINDOWS, "install.sh is POSIX-only")
    def test_install_sh_skips_broken_python3_stub(self):
        # Simulate Windows where `python3` on PATH is a Microsoft Store stub exiting 9009, while `python` works.
        fakebin = self.root / "fakebin"
        fakebin.mkdir()
        stub = fakebin / "python3"
        stub.write_text("#!/bin/sh\nexit 127\n")
        stub.chmod(0o755)
        real_py = fakebin / "python"
        real_py.symlink_to(sys.executable)
        env = dict(self.env, PATH=f"{fakebin}:/usr/bin:/bin")
        result = subprocess.run([str(REPO / "install.sh"), "--dry-run"], env=env,
                                cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Dry run complete", result.stdout)

    @unittest.skipIf(WINDOWS, "install.sh is POSIX-only")
    def test_install_sh_requires_python_3_9(self):
        # A Python 3.8 stub fails the (3, 9) probe; when no 3.9+ interpreter exists on PATH, install.sh fails cleanly.
        fakebin = self.root / "fakebin38"
        fakebin.mkdir()
        probe_38 = (
            "#!/bin/sh\n"
            '[ "$1" = "-3" ] && shift\n'
            f'exec "{sys.executable}" -c "import sys; sys.version_info = (3, 8, 19); exec(sys.argv[1])" "$2"\n'
        )
        for name in ("python3", "py", "python"):
            stub = fakebin / name
            stub.write_text(probe_38)
            stub.chmod(0o755)
        # Also test that install.sh skips the 3.8 python3 stub when a 3.9+ python is available.
        with_py = self.root / "fakebin38_ok"
        with_py.mkdir()
        (with_py / "python3").write_text(probe_38)
        (with_py / "python3").chmod(0o755)
        (with_py / "python").symlink_to(sys.executable)
        ok = subprocess.run(["/bin/bash", str(REPO / "install.sh"), "--dry-run"],
                            env=dict(self.env, PATH=f"{with_py}:/usr/bin:/bin"),
                            cwd=self.root, text=True, capture_output=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("Dry run complete", ok.stdout)

        # When every candidate fails the 3.9 probe, install.sh exits non-zero with the 3.9+ message.
        fail = subprocess.run(["/bin/bash", str(REPO / "install.sh"), "--dry-run"],
                              env=dict(self.env, PATH=f"{fakebin}:/bin"),
                              cwd=self.root, text=True, capture_output=True)
        self.assertNotEqual(fail.returncode, 0)
        self.assertIn("Python 3.9+ is required", fail.stderr)

    def test_atomic_replace_leaves_no_temp_dirs_and_cleans_stale_files(self):
        self.run_install("--desktop")
        for name in MODS:
            (self.desktop / "mods" / name / "stale.js").write_text("old")
        (self.claude / "skills/pm/stale.txt").write_text("old")
        self.run_install("--desktop")
        # Stale files are gone and no staging/old temp dirs remain in mods/, skills/, or their parents.
        for parent in (self.desktop / "mods", self.claude / "skills", self.desktop, self.claude):
            leftovers = [p.name for p in parent.iterdir()
                         if ".staging-" in p.name or ".old-" in p.name or p.name == ".dudu-staging"]
            self.assertEqual(leftovers, [], f"leftover temp entries in {parent}: {leftovers}")
        for name in MODS:
            self.assertFalse((self.desktop / "mods" / name / "stale.js").exists())
        self.assertFalse((self.claude / "skills/pm/stale.txt").exists())

    def test_replace_tree_stages_outside_mods_dir_and_prunes_staging_parent(self):
        setup_mod = load_module("pm_setup_atomic_outside", BUNDLE / "setup.py")
        src = self.root / "src_mod_outside"
        app_home = self.root / "herdr-app"
        mods_dir = app_home / "mods"
        dst = mods_dir / "pm-project"
        src.mkdir(parents=True)
        (src / "mod.json").write_text('{"name":"pm-project"}')
        (src / "main.js").write_text("new")
        dst.mkdir(parents=True)
        (dst / "mod.json").write_text('{"name":"pm-project"}')
        (dst / "main.js").write_text("old")

        observed = {}
        real_copytree = shutil.copytree

        def spy_copytree(s, d, *args, **kwargs):
            observed["staging"] = Path(d)
            observed["mods_entries_during_copy"] = sorted(p.name for p in mods_dir.iterdir())
            return real_copytree(s, d, *args, **kwargs)

        with mock.patch.object(setup_mod.shutil, "copytree", side_effect=spy_copytree):
            setup_mod.replace_tree(src, dst, ())

        # During copytree, staging lives in herdr-app/.dudu-staging, never inside mods/.
        self.assertEqual(observed["staging"].parent, app_home / ".dudu-staging")
        self.assertEqual(observed["mods_entries_during_copy"], ["pm-project"])
        # After swap, target is updated and .dudu-staging is pruned cleanly.
        self.assertEqual((dst / "main.js").read_text(), "new")
        self.assertFalse((app_home / ".dudu-staging").exists())
        self.assertEqual(sorted(p.name for p in mods_dir.iterdir()), ["pm-project"])

    def test_replace_tree_preserves_existing_target_when_copy_fails(self):
        setup_mod = load_module("pm_setup_atomic_fail", BUNDLE / "setup.py")
        src = self.root / "src_mod"
        dst = self.root / "mods/pm-project"
        src.mkdir(parents=True)
        (src / "main.js").write_text("new main")
        (src / "model.js").write_text("new model")
        dst.mkdir(parents=True)
        (dst / "main.js").write_text("old main")
        (dst / "model.js").write_text("old model")

        real_copytree = shutil.copytree

        def failing_copytree(s, d, *args, **kwargs):
            Path(d).mkdir(parents=True, exist_ok=True)
            (Path(d) / "main.js").write_text("partial")
            raise OSError("simulated disk full during copy")

        with mock.patch.object(setup_mod.shutil, "copytree", side_effect=failing_copytree):
            with self.assertRaises(OSError):
                setup_mod.replace_tree(src, dst, ())

        # Original directory is completely untouched, and the sibling staging dir was cleaned up.
        self.assertEqual((dst / "main.js").read_text(), "old main")
        self.assertEqual((dst / "model.js").read_text(), "old model")
        self.assertEqual(sorted(p.name for p in dst.parent.iterdir()), ["pm-project"])

        # Subsequent real copytree succeeds cleanly.
        with mock.patch.object(setup_mod.shutil, "copytree", real_copytree):
            setup_mod.replace_tree(src, dst, ())
        self.assertEqual((dst / "main.js").read_text(), "new main")
        self.assertEqual((dst / "model.js").read_text(), "new model")
        self.assertEqual(sorted(p.name for p in dst.parent.iterdir()), ["pm-project"])

    def test_replace_tree_without_atomic_exchange_updates_mod_folder_in_place(self):
        # Windows has no atomic directory exchange. A running Herdr there watches each mod folder by
        # handle: renaming the folder aside fails its reload ("cannot read <mod>: Access is denied
        # (os error 5)") and later edits go unseen until restart (seen on Windows). So the
        # folder must stay put and only files move in, the entry files last.
        setup_mod = load_module("pm_setup_inplace", BUNDLE / "setup.py")
        src = self.root / "src_mod2"
        dst = self.root / "herdr-app/mods/pm-nav"
        (src / "icons").mkdir(parents=True)
        (src / "main.js").write_text("v2 main")
        (src / "model.js").write_text("v2 model")
        (src / "mod.json").write_text("{}")
        (src / "icons/a.svg").write_text("<svg/>")
        (src / "was_dir").write_text("now a file")
        (dst / "gone_dir").mkdir(parents=True)
        (dst / "gone_dir/x.js").write_text("x")
        (dst / "was_dir").mkdir()
        (dst / "main.js").write_text("v1 main")
        (dst / "old_only.js").write_text("gone in v2")
        (dst / "__pycache__").mkdir()
        (dst / "__pycache__/m.pyc").write_bytes(b"0")
        before = os.stat(dst)

        real_rename, real_replace = os.rename, os.replace
        renamed, replaced = [], []

        def spy_rename(a, b):
            renamed.append((Path(a), Path(b)))
            return real_rename(a, b)

        def spy_replace(a, b):
            replaced.append(Path(b))
            return real_replace(a, b)

        with mock.patch.object(setup_mod, "_atomic_exchange_dirs", return_value=False), \
             mock.patch.object(setup_mod.os, "rename", side_effect=spy_rename), \
             mock.patch.object(setup_mod.os, "replace", side_effect=spy_replace):
            setup_mod.replace_tree(src, dst, ("__pycache__",))

        after = os.stat(dst)
        self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino), "mod folder was replaced")
        self.assertFalse(any(dst in (a, b) for a, b in renamed), renamed)
        self.assertEqual(sorted(str(p.relative_to(dst)) for p in dst.rglob("*")),
                         ["icons", str(Path("icons/a.svg")), "main.js", "mod.json", "model.js", "was_dir"])
        self.assertEqual((dst / "main.js").read_text(), "v2 main")
        self.assertEqual((dst / "was_dir").read_text(), "now a file")
        # mod.json then main.js come last: the reload they trigger sees every other new file.
        self.assertEqual([p.name for p in replaced[-2:]], ["mod.json", "main.js"])
        self.assertTrue(all(p.parent == dst or dst in p.parents for p in replaced))
        # Staging (outside mods/) is gone, nothing temporary is left next to the mod.
        self.assertEqual(sorted(p.name for p in dst.parent.iterdir()), ["pm-nav"])
        self.assertEqual(sorted(p.name for p in dst.parent.parent.iterdir()), ["mods"])

    def test_replace_file_retries_a_briefly_locked_target(self):
        setup_mod = load_module("pm_setup_replace_retry", BUNDLE / "setup.py")
        src, dst = self.root / "a.tmp", self.root / "main.js"
        src.write_text("new")
        dst.write_text("old")
        real_replace = os.replace
        calls = {"n": 0}

        def locked_twice(a, b):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(32, "The process cannot access the file")
            return real_replace(a, b)

        with mock.patch.object(setup_mod.os, "replace", side_effect=locked_twice), \
             mock.patch.object(setup_mod.time, "sleep"):
            setup_mod._replace_file(src, dst)
        self.assertEqual(dst.read_text(), "new")
        self.assertEqual(calls["n"], 3)

    def test_replace_tree_file_target_swap_and_rollback_on_rename_failure(self):
        setup_mod = load_module("pm_setup_atomic_fallback", BUNDLE / "setup.py")
        src = self.root / "src_mod2"
        dst = self.root / "mods/pm-dash"
        src.mkdir(parents=True)
        (src / "main.js").write_text("v2")
        dst.parent.mkdir(parents=True)
        dst.write_text("a file where the mod folder goes")

        # If os.rename(staging, target) fails, the moved-aside target is rolled back.
        real_rename = os.rename
        calls = {"n": 0}

        def fail_second_rename(a, b):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("simulated rename failure")
            return real_rename(a, b)

        with mock.patch.object(setup_mod.os, "rename", side_effect=fail_second_rename):
            with self.assertRaises(OSError):
                setup_mod.replace_tree(src, dst, ())
        self.assertEqual(dst.read_text(), "a file where the mod folder goes")
        self.assertEqual(sorted(p.name for p in dst.parent.iterdir()), ["pm-dash"])

        # Without the failure the file is replaced by the folder.
        setup_mod.replace_tree(src, dst, ())
        self.assertEqual((dst / "main.js").read_text(), "v2")
        self.assertEqual(sorted(p.name for p in dst.parent.iterdir()), ["pm-dash"])

    def test_replace_tree_replaces_symlink_without_touching_linked_dir(self):
        setup_mod = load_module("pm_setup_atomic_link", BUNDLE / "setup.py")
        src = self.root / "src_skill"
        linked = self.root / "elsewhere_skill"
        dst = self.root / "skills/pm"
        src.mkdir(parents=True)
        (src / "SKILL.md").write_text("new skill")
        linked.mkdir(parents=True)
        (linked / "SKILL.md").write_text("keep untouched")
        dst.parent.mkdir(parents=True)
        dst.symlink_to(linked, target_is_directory=True)

        setup_mod.replace_tree(src, dst, ())
        self.assertFalse(dst.is_symlink())
        self.assertEqual((dst / "SKILL.md").read_text(), "new skill")
        self.assertEqual((linked / "SKILL.md").read_text(), "keep untouched")
        self.assertEqual(sorted(p.name for p in dst.parent.iterdir()), ["pm"])

    def test_install_keys_adds_herdr_lists_shortcut_and_preserves_existing(self):
        install_mod = load_module("dudu_install_keys_test", REPO / "install.py")
        self.assertEqual(install_mod.default_herdr_lists_key("darwin"), "cmd-shift-e")
        self.assertEqual(install_mod.default_herdr_lists_key("linux"), "ctrl-shift-e")
        self.assertEqual(install_mod.default_herdr_lists_key("win32"), "ctrl-shift-e")
        self.assertEqual(install_mod.default_project_search_key("darwin"), "cmd-k")
        self.assertEqual(install_mod.default_project_search_key("linux"), "ctrl-k")
        self.assertEqual(install_mod.default_project_search_key("win32"), "ctrl-k")
        expected_key = install_mod.default_herdr_lists_key()
        expected_search_key = install_mod.default_project_search_key()

        self.seed_layout()
        keys_path = self.desktop / "keys.json"
        # Missing keys.json must not be created partially (would block Herdr's default generation).
        out_missing = self.run_install()
        self.assertIn("Skip keys:", out_missing)
        self.assertFalse(keys_path.exists())

        seed = {
            "global": {"cmd-b": "layout.toggle:sidebar", "cmd-p": "mod.open:picker"},
            "terminal": {"cmd-c": "terminal.copy"},
        }
        keys_path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")

        # Dry run reports without mutating.
        out_dry = self.run_install("--dry-run")
        self.assertIn(f"Would Bind {expected_key} to layout.toggle:herdr-lists", out_dry)
        self.assertIn(f"Would Bind {expected_search_key} to pm-project.search", out_dry)
        self.assertIn(f"Would Bind {expected_search_key} to terminal in terminal section", out_dry)
        self.assertEqual(json.loads(keys_path.read_text(encoding="utf-8")), seed)

        # Real install writes layout:dudu bindings + terminal passthrough, backs up once, and keeps existing sections intact.
        out_install = self.run_install()
        self.assertIn(f"Bind {expected_key} to layout.toggle:herdr-lists", out_install)
        self.assertIn(f"Bind {expected_search_key} to pm-project.search", out_install)
        data = json.loads(keys_path.read_text(encoding="utf-8"))
        self.assertEqual(data["global"], seed["global"])
        self.assertEqual(data["terminal"], {"cmd-c": "terminal.copy", expected_search_key: "terminal"})
        self.assertEqual(data["layout:dudu"], {
            expected_key: "layout.toggle:herdr-lists",
            expected_search_key: "pm-project.search",
        })
        self.assertTrue(keys_path.with_name("keys.json.pm-backup").exists())

        # Idempotent re-run does not touch keys.json.
        before = keys_path.read_bytes()
        out_again = self.run_install()
        self.assertIn("already binds layout.toggle:herdr-lists", out_again)
        self.assertIn("already binds pm-project.search", out_again)
        self.assertEqual(keys_path.read_bytes(), before)

        # Uninstall removes only dudu's bindings and preserves user keys.
        out_un = self.run_install("--uninstall")
        self.assertIn("Remove layout.toggle:herdr-lists binding", out_un)
        self.assertIn("Remove pm-project.search binding", out_un)
        after_un = json.loads(keys_path.read_text(encoding="utf-8"))
        self.assertEqual(after_un, seed)

    def test_install_keys_respects_custom_binding_and_conflicts(self):
        install_mod = load_module("dudu_install_keys_conflict", REPO / "install.py")
        expected_key = install_mod.default_herdr_lists_key()
        expected_search_key = install_mod.default_project_search_key()
        self.seed_layout()
        keys_path = self.desktop / "keys.json"

        # 1) User already bound both actions (object form) to custom keys.
        custom = {
            "global": {
                "cmd-alt-s": {"command": "layout.toggle", "args": {"id": "herdr-lists"}},
                "cmd-alt-k": {"command": "pm-project.search"},
            },
        }
        keys_path.write_text(json.dumps(custom, indent=2) + "\n", encoding="utf-8")
        out_custom = self.run_install()
        self.assertIn("already binds layout.toggle:herdr-lists", out_custom)
        self.assertIn("already binds pm-project.search", out_custom)
        self.assertEqual(json.loads(keys_path.read_text(encoding="utf-8")), custom)

        # 2) User already bound the default keys to something else -> never overwrite or touch terminal.
        conflict = {
            "global": {expected_key: "app.palette", expected_search_key: "app.palette"},
        }
        keys_path.write_text(json.dumps(conflict, indent=2) + "\n", encoding="utf-8")
        out_conflict = self.run_install()
        self.assertIn(f"{expected_key} is already bound", out_conflict)
        self.assertIn(f"{expected_search_key} is already bound", out_conflict)
        self.assertEqual(json.loads(keys_path.read_text(encoding="utf-8")), conflict)

        # 3) User already bound search key in terminal to a custom action -> keep user's terminal action, still bind layout:dudu.
        custom_term = {
            "global": {"cmd-b": "layout.toggle:sidebar"},
            "terminal": {expected_search_key: "send:\u000c"},
            "layout:dudu": {expected_key: "layout.toggle:herdr-lists"},
        }
        keys_path.write_text(json.dumps(custom_term, indent=2) + "\n", encoding="utf-8")
        out_term = self.run_install()
        self.assertIn(f"Bind {expected_search_key} to pm-project.search", out_term)
        after_term = json.loads(keys_path.read_text(encoding="utf-8"))
        self.assertEqual(after_term["terminal"][expected_search_key], "send:\u000c")
        self.assertEqual(after_term["layout:dudu"][expected_search_key], "pm-project.search")
        # Uninstall must not remove user's custom terminal binding.
        self.run_install("--uninstall")
        after_un = json.loads(keys_path.read_text(encoding="utf-8"))
        self.assertEqual(after_un["terminal"][expected_search_key], "send:\u000c")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # pm.py, imported, turns the module registered under its name into pmlib's forwarder
    spec.loader.exec_module(module)
    return module


class WindowsHookTest(unittest.TestCase):
    """setup.py as it runs on Windows (WINDOWS forced on; the paths are this machine's). Not run on Windows."""
    PYTHON = r"C:\Users\Ann Lee\AppData\Local\Programs\Python\Python312\python.exe"

    def setUp(self):
        self.setup = load_module("pm_setup_under_test", BUNDLE / "setup.py")
        self.pm = load_module("pm_under_test", BUNDLE / "skill/scripts/pm.py")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.claude = Path(temp.name) / "claude home"
        self.claude.mkdir()

    def windows(self, py):
        """Patch both scripts as on Windows: py is the launcher's path, or None when it is not installed."""
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(self.setup, "WINDOWS", True))
        stack.enter_context(mock.patch.object(self.pm, "WINDOWS", True))
        stack.enter_context(mock.patch.object(shutil, "which", lambda name: py if name == "py" else None))
        stack.enter_context(mock.patch.object(sys, "executable", self.PYTHON))
        self.addCleanup(stack.close)

    def install(self):
        args = argparse.Namespace(dry_run=False, uninstall=False, agents=["claude"], claude_home=str(self.claude),
                                  codex_home=None, pi_home=None)
        setup = self.setup.Setup(args)
        setup.prepare()
        setup.save_settings()
        return [hook["command"] for entries in json.loads((self.claude / "settings.json").read_text())["hooks"].values()
                for entry in entries for hook in entry["hooks"]]

    def test_python_command(self):
        with mock.patch.object(self.setup, "WINDOWS", False):
            self.assertEqual(self.setup.python_command(), "python3")  # macOS and Linux: as before
        self.windows(r"C:\Windows\py.exe")
        self.assertEqual(self.setup.python_command(), "py -3")
        self.assertEqual(self.pm.python_command(), "py -3")

    def test_python_command_without_launcher_is_the_quoted_interpreter(self):
        self.windows(None)
        quoted = '"C:/Users/Ann Lee/AppData/Local/Programs/Python/Python312/python.exe"'
        self.assertEqual(self.setup.python_command(), quoted)
        self.assertEqual(self.pm.python_command(), quoted)
        with mock.patch.object(sys, "executable", r"C:\Python312\python.exe"):
            self.assertEqual(self.setup.python_command(), "C:/Python312/python.exe")

    def test_hooks_name_the_launcher_and_an_absolute_script(self):
        self.windows(r"C:\Windows\py.exe")
        script = self.setup.PureWindowsPath(self.claude / "skills/pm/scripts/pm.py").as_posix()
        self.assertEqual(sorted(self.install()), sorted(f'py -3 "{script}" {action}'
                                                        for _, action, _ in self.setup.HOOKS))
        self.assertEqual(self.setup.Agent("claude", r"C:\Users\Ann\.claude").script_command.count("\\"), 0)

    def test_hooks_without_launcher_and_a_later_launcher_replaces_them(self):
        self.windows(None)
        first = self.install()
        self.assertTrue(all(c.startswith('"C:/Users/Ann Lee/') for c in first), first)
        self.assertEqual(len(first), 5)
        self.windows(r"C:\Windows\py.exe")
        second = self.install()
        self.assertEqual(len(second), 5, second)  # replaced, not added next to the old ones
        self.assertTrue(all(c.startswith("py -3 ") for c in second), second)

    def test_windows_path_forms(self):
        self.assertEqual(self.setup.PureWindowsPath(r"C:\Users\Ann\.claude\skills\pm\scripts\pm.py").as_posix(),
                         "C:/Users/Ann/.claude/skills/pm/scripts/pm.py")

    def test_installer_hints_migration_for_legacy_ledger_and_recognizes_symlink(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = Path(temp.name)
        claude = home / ".claude"
        legacy = claude / "pm"
        legacy.mkdir(parents=True)
        (legacy / "tasks").mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ("PM_HOME", "CLAUDE_HOME", "CODEX_HOME", "PI_CODING_AGENT_DIR")}
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        res = subprocess.run([sys.executable, str(BUNDLE / "setup.py"), "--agents", "claude"],
                             env=env, cwd=str(home), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("legacy ledger found", res.stdout)
        self.assertIn("home --migrate --dry-run", res.stdout)
        # Installer must never auto-migrate the ledger.
        self.assertTrue(legacy.is_dir() and not legacy.is_symlink())
        self.assertFalse((home / ".dudu").exists())
        # Once migrated (~/.claude/pm -> ~/.dudu), installer treats ~/.dudu as ledger home and stops hinting.
        os.rename(legacy, home / ".dudu")
        os.symlink(str(home / ".dudu"), str(legacy), target_is_directory=True)
        res2 = subprocess.run([sys.executable, str(BUNDLE / "setup.py"), "--agents", "claude"],
                              env=env, cwd=str(home), capture_output=True, text=True)
        self.assertEqual(res2.returncode, 0, res2.stdout + res2.stderr)
        self.assertNotIn("legacy ledger found", res2.stdout)
        self.assertTrue((home / ".dudu" / "install" / "skill-claude.json").is_file())


class WindowsAclTest(unittest.TestCase):
    """Windows NTFS ACL inheritance restoration and tempfile avoidance (mocking sys.platform == 'win32')."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.setup = load_module("pm_setup_win_acl", BUNDLE / "setup.py")

    def test_restore_windows_acl_noop_on_non_windows(self):
        target = self.root / "file.json"
        target.write_text("{}", encoding="utf-8")
        for plat in ("darwin", "linux"):
            with mock.patch.object(sys, "platform", plat), \
                 mock.patch.object(self.setup.subprocess, "run") as run_mock:
                self.assertFalse(self.setup.restore_windows_acl(target, recursive=True))
                run_mock.assert_not_called()

    def test_restore_windows_acl_invokes_icacls_and_handles_errors(self):
        file_target = self.root / "dudu.json"
        file_target.write_text("{}", encoding="utf-8")
        dir_target = self.root / "pm-dash"
        dir_target.mkdir()
        missing = self.root / "does-not-exist"

        ok = subprocess.CompletedProcess(args=[], returncode=0)
        fail = subprocess.CompletedProcess(args=[], returncode=5)

        with mock.patch.object(sys, "platform", "win32"):
            with mock.patch.object(self.setup.subprocess, "run", return_value=ok) as run_mock:
                self.assertTrue(self.setup.restore_windows_acl(file_target, recursive=False))
                self.assertTrue(self.setup.restore_windows_acl(dir_target, recursive=True))
                self.assertFalse(self.setup.restore_windows_acl(missing, recursive=True))
                self.assertEqual(
                    [call.args[0] for call in run_mock.call_args_list],
                    [
                        ["icacls", str(file_target), "/reset", "/Q"],
                        ["icacls", str(dir_target), "/reset", "/T", "/Q"],
                    ],
                )
            with mock.patch.object(self.setup.subprocess, "run", return_value=fail):
                self.assertFalse(self.setup.restore_windows_acl(file_target))
            with mock.patch.object(self.setup.subprocess, "run", side_effect=FileNotFoundError("icacls")):
                self.assertFalse(self.setup.restore_windows_acl(dir_target, recursive=True))

    def test_replace_tree_and_write_json_avoid_tempfile_and_restore_acl_on_windows(self):
        src = self.root / "src_mod"
        (src / "sub").mkdir(parents=True)
        (src / "mod.json").write_text('{"name":"pm-dash"}', encoding="utf-8")
        (src / "main.js").write_text("v1", encoding="utf-8")
        (src / "sub/helper.js").write_text("h1", encoding="utf-8")
        dst = self.root / "herdr-app/mods/pm-dash"
        json_target = self.root / "herdr-app/layouts/dudu.json"

        ok = subprocess.CompletedProcess(args=[], returncode=0)
        icacls_cmds = []

        def fake_run(cmd, *args, **kwargs):
            icacls_cmds.append(cmd)
            return ok

        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(self.setup.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(self.setup.tempfile, "mkdtemp", side_effect=AssertionError("mkdtemp called on win32")), \
             mock.patch.object(self.setup.tempfile, "NamedTemporaryFile",
                               side_effect=AssertionError("NamedTemporaryFile called on win32")):
            # Fresh install of directory tree.
            self.setup.replace_tree(src, dst, ())
            self.assertEqual((dst / "main.js").read_text(encoding="utf-8"), "v1")
            # In-place update of existing directory tree.
            (src / "main.js").write_text("v2", encoding="utf-8")
            self.setup.replace_tree(src, dst, ())
            self.assertEqual((dst / "main.js").read_text(encoding="utf-8"), "v2")
            # JSON write.
            self.setup.write_json(json_target, {"toast": "pm-toast"})
            self.assertEqual(json.loads(json_target.read_text(encoding="utf-8")), {"toast": "pm-toast"})

        self.assertEqual(
            icacls_cmds,
            [
                ["icacls", str(dst), "/reset", "/T", "/Q"],
                ["icacls", str(dst), "/reset", "/T", "/Q"],
                ["icacls", str(json_target), "/reset", "/Q"],
            ],
        )
        self.assertFalse((self.root / "herdr-app/.dudu-staging").exists())

    def test_full_install_restores_acl_for_mods_skills_layout_and_keys_on_windows(self):
        install_mod = load_module("dudu_install_win_acl", REPO / "install.py")
        claude = self.root / "claude"
        codex = self.root / "codex"
        desktop = self.root / "herdr-app"
        claude.mkdir()
        codex.mkdir()
        (desktop / "layouts").mkdir(parents=True)
        (desktop / "layouts/main.json").write_text(json.dumps(MAIN), encoding="utf-8")
        (desktop / "keys.json").write_text(json.dumps({"global": {"ctrl-b": "layout.toggle:sidebar"}}), encoding="utf-8")

        env = {
            "HOME": str(self.root),
            "USERPROFILE": str(self.root),
            "CLAUDE_HOME": str(claude),
            "CODEX_HOME": str(codex),
            "HERDR_APP_HOME": str(desktop),
            "PM_HOME": str(self.root / ".dudu"),
        }
        ok = subprocess.CompletedProcess(args=[], returncode=0)
        icacls_cmds = []

        def fake_run(cmd, *args, **kwargs):
            icacls_cmds.append(cmd)
            return ok

        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(install_mod.installer.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(install_mod.installer.tempfile, "mkdtemp",
                               side_effect=AssertionError("mkdtemp called on win32")), \
             mock.patch.object(install_mod.installer.tempfile, "NamedTemporaryFile",
                               side_effect=AssertionError("NamedTemporaryFile called on win32")):
            # --dry-run must never run icacls.
            install_mod.main(["--agents", "claude,codex", "--desktop", "--dry-run"])
            self.assertEqual(icacls_cmds, [])

            # Real install restores ACLs on skills, mods, layout, keys, and hooks files.
            install_mod.main(["--agents", "claude,codex", "--desktop"])
            expected_dir_cmds = [
                ["icacls", str(claude / "skills/pm"), "/reset", "/T", "/Q"],
                ["icacls", str(codex / "skills/pm"), "/reset", "/T", "/Q"],
                *(["icacls", str(desktop / "mods" / name), "/reset", "/T", "/Q"] for name in MODS),
            ]
            expected_file_cmds = [
                ["icacls", str(desktop / "layouts/dudu.json"), "/reset", "/Q"],
                ["icacls", str(desktop / "keys.json"), "/reset", "/Q"],
                ["icacls", str(claude / "settings.json"), "/reset", "/Q"],
                ["icacls", str(codex / "hooks.json"), "/reset", "/Q"],
            ]
            for cmd in expected_dir_cmds + expected_file_cmds:
                self.assertIn(cmd, icacls_cmds)

            # Idempotent re-run still heals existing layout, keys, hooks, skills, and mods.
            icacls_cmds.clear()
            install_mod.main(["--agents", "claude,codex", "--desktop"])
            for cmd in expected_dir_cmds + expected_file_cmds:
                self.assertIn(cmd, icacls_cmds)


if __name__ == "__main__":
    unittest.main()
