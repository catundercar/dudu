#!/usr/bin/env python3
"""Install the bundled PM skill and hooks; --status never writes files."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        if path.exists():
            temporary.chmod(path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def remove_path(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


class Setup:
    def __init__(self, args, repo=None):
        self.args = args
        self.source = Path(__file__).resolve().parent / "skill"
        self.repo = repo or self.source.parent
        self.claude = Path(getattr(args, "claude_home", None) or os.environ.get("CLAUDE_HOME")
                           or Path.home() / ".claude").expanduser().absolute()
        self.settings_path = self.claude / "settings.json"
        self.backup = self.claude / "settings.json.pm-backup"
        self.skill = self.claude / "skills/pm"
        script = self.skill / "scripts/pm.py"
        self.script_command = ("~/.claude/skills/pm/scripts/pm.py" if self.claude == Path.home() / ".claude"
                               else shlex.quote(str(script)))
        self.prefix = "Would " if args.dry_run else ""
    def read_settings(self):
        value = json.loads(self.settings_path.read_text(encoding="utf-8")) if self.settings_path.exists() else {}
        if not isinstance(value, dict) or not isinstance(value.get("hooks", {}), dict):
            raise ValueError("settings.json and its hooks must be JSON objects")
        for entries in value.get("hooks", {}).values():
            if not isinstance(entries, list) or any(
                not isinstance(entry, dict) or not isinstance(entry.get("hooks", []), list)
                or any(not isinstance(hook, dict) for hook in entry.get("hooks", []))
                for entry in entries
            ):
                raise ValueError("settings.json contains an unsupported hook structure; left unchanged")
        return value
    def save_settings(self):
        settings, original = self.settings, self.original
        if settings == original:
            print("Skip settings: no hook changes needed.")
            return
        if self.settings_path.exists() and not self.backup.exists():
            print(f"{self.prefix}Back up settings to {self.backup}")
            if not self.args.dry_run:
                shutil.copy2(self.settings_path, self.backup)
        print(f"{self.prefix}Update hooks in {self.settings_path}")
        if not self.args.dry_run:
            write_json(self.settings_path, settings)
    def copy_files(self, source, target, excluded):
        if source.resolve() == target.resolve():
            print(f"Skip copy: {target} already points to the repository source.")
            return
        if target.exists() or target.is_symlink():
            print(f"{self.prefix}Remove old installation at {target}")
            if not self.args.dry_run:
                remove_path(target)
        print(f"{self.prefix}Copy {source.relative_to(self.repo)} to {target}")
        if not self.args.dry_run:
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(*excluded))

    def prepare(self):
        try:
            settings = self.read_settings()
        except (OSError, ValueError) as error:
            if not self.args.uninstall:
                raise
            print(f"Warning: skip hook cleanup: {error}")
            settings = {}
        original = copy.deepcopy(settings)
        if self.args.uninstall:
            for event, entries in list(settings.get("hooks", {}).items()):
                kept = []
                for entry in entries:
                    hooks = entry.get("hooks", [])
                    remaining = [hook for hook in hooks if "skills/pm/scripts/pm.py" not in str(hook.get("command", ""))]
                    if len(remaining) == len(hooks):
                        kept.append(entry)
                    elif remaining:
                        kept.append(dict(entry, hooks=remaining))
                if kept or not entries:
                    settings["hooks"][event] = kept
                else:
                    del settings["hooks"][event]
            if original.get("hooks") and not settings.get("hooks"):
                del settings["hooks"]
        else:
            hooks = settings.setdefault("hooks", {})
            events = [("SessionStart", "hook-session-start", 10)]
            if self.args.discord:
                events += [("UserPromptSubmit", "hook-mirror", 15), ("Stop", "hook-mirror", 15)]
            else:
                print("Skip Discord hooks: --discord not requested; existing hooks are kept.")
            for event, action, timeout in events:
                command = f"python3 {self.script_command} {action}"
                entries = hooks.setdefault(event, [])
                if any(hook.get("command") == command for entry in entries for hook in entry.get("hooks", [])):
                    print(f"Skip {event}: PM command already installed.")
                    continue
                hook = {"type": "command", "command": command, "timeout": timeout}
                entry = {"hooks": [hook]}
                if event == "SessionStart":
                    entry["matcher"] = "^(startup|resume|clear|compact)$"
                else:
                    hook["async"] = True
                entries.append(entry)
        self.settings, self.original = settings, original
    def install_skill(self):
        self.copy_files(self.source, self.skill, ("test_pm.py", "__pycache__", ".DS_Store"))
    def remove_skill(self):
        if self.skill.exists() or self.skill.is_symlink():
            print(f"{self.prefix}Remove {self.skill}")
            if not self.args.dry_run:
                remove_path(self.skill)
        else:
            print(f"Skip removal: {self.skill} is absent.")
    def kept(self):
        print(f"Keep ledger and configuration: {self.claude / 'pm'} (also any custom PM_HOME).")
        print("Keep settings.json.pm-backup and any Discord credentials/state.")
    def finish(self):
        print('Next, start a Claude Code session in your project inside Herdr and say "act as PM for this project",')
        print(f"or run: python3 {self.script_command} claim")
        if self.args.dry_run:
            print("Dry run complete; no files written.")
        else:
            print("Installation complete. Restart existing Claude Code sessions to load the skill and hooks.")
    def status(self):
        def fingerprint(path):
            if not path.is_file():
                return None
            data = path.read_bytes()
            return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

        bundled = fingerprint(self.source / "scripts/pm.py")
        if bundled is None:
            raise ValueError("bundled skill/scripts/pm.py is missing")
        installed = fingerprint(self.skill / "scripts/pm.py")
        result = {"skill_present": (self.skill / "SKILL.md").is_file() and installed is not None,
                  "hooks_present": False, "script_matches": installed == bundled,
                  "bundled": bundled, "installed": installed}
        try:
            settings = self.read_settings()
            command = f"python3 {self.script_command} hook-session-start"
            result["hooks_present"] = any(
                hook.get("command") == command
                for entry in settings.get("hooks", {}).get("SessionStart", [])
                for hook in entry.get("hooks", []))
        except (OSError, ValueError) as error:
            result["error"] = f"Install failed: {error}"
        return result


def run(action):
    try:
        action()
    except shutil.Error as error:
        details = error.args[0]
        for detail in details if isinstance(details, list) else [details]:
            if isinstance(detail, tuple) and len(detail) == 3:
                print(f"Copy failed: {detail[0]} -> {detail[1]}: {detail[2]}", file=sys.stderr)
            else:
                print(f"Copy failed: {detail}", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError) as error:
        sys.exit(f"Install failed: {error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discord", action="store_true", help="add optional chat-mirroring hooks")
    parser.add_argument("--dry-run", action="store_true", help="print planned changes without writing files")
    parser.add_argument("--uninstall", action="store_true", help="remove PM hooks and skill; keep the ledger")
    parser.add_argument("--status", action="store_true", help="print read-only setup facts as JSON")
    parser.add_argument("--claude-home", help="override the Claude home (desktop uses ~/.claude)")
    args = parser.parse_args()
    setup = Setup(args)
    if args.status:
        print(json.dumps(setup.status()))
        return
    setup.prepare()
    if args.uninstall:
        setup.save_settings()
        setup.remove_skill()
        setup.kept()
    else:
        setup.install_skill()
        setup.save_settings()
        setup.finish()


if __name__ == "__main__":
    run(main)
