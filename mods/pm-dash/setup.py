#!/usr/bin/env python3
"""Install the bundled PM skill and its hooks for your coding agents; --status never writes files."""
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

# Where each coding agent keeps its skills and hooks: label, environment variable that moves its home,
# default home under ~, and the hooks file inside that home (None: the agent has no hooks).
AGENTS = {
    "claude": ("Claude Code", "CLAUDE_HOME", ".claude", "settings.json"),
    "codex": ("Codex", "CODEX_HOME", ".codex", "hooks.json"),
    "pi": ("pi", "PI_CODING_AGENT_DIR", ".pi/agent", None),
}
# Every agent with hooks gets all three. The turn hook only notes the turn for the board and prints the
# hand-over reminder; what UserPromptSubmit prints is added to the session's context, so it stays synchronous.
HOOKS = [("SessionStart", "hook-session-start", 10), ("UserPromptSubmit", "hook-turn", 15), ("Stop", "hook-turn", 15)]
SCRIPT = "skills/pm/scripts/pm.py"


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


def agent_list(text):
    """argparse type for --agents claude,codex,pi."""
    names = [name.strip() for name in text.split(",") if name.strip()]
    unknown = [name for name in names if name not in AGENTS]
    if unknown or not names:
        raise argparse.ArgumentTypeError(f"choose from {', '.join(AGENTS)} (got {text!r})")
    return list(dict.fromkeys(names))


def ledger_home():
    """The rule pm.py uses: PM_HOME, else ~/.claude/pm where an earlier install keeps it, else ~/.dudu."""
    earlier = Path.home() / ".claude" / "pm"
    return Path(os.environ.get("PM_HOME") or (earlier if earlier.exists() else Path.home() / ".dudu"))


def fingerprint(path):
    if not path.is_file():
        return None
    data = path.read_bytes()
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def strip_hooks(value, drop):
    """Remove every hook for which drop(command) is true; drop entries and events left empty."""
    hooks = value.get("hooks", {})
    for event, entries in list(hooks.items()):
        kept = []
        for entry in entries:
            inner = entry.get("hooks", [])
            remaining = [hook for hook in inner if not drop(str(hook.get("command", "")))]
            if len(remaining) == len(inner):
                kept.append(entry)
            elif remaining:
                kept.append(dict(entry, hooks=remaining))
        if kept or not entries:
            hooks[event] = kept
        else:
            del hooks[event]


class Agent:
    def __init__(self, name, home=None):
        self.name = name
        self.label, variable, default, hooks_file = AGENTS[name]
        default = Path.home() / default
        self.home = Path(home or os.environ.get(variable) or default).expanduser().absolute()
        self.skill = self.home / "skills/pm"
        self.hooks_path = self.home / hooks_file if hooks_file else None
        script = self.skill / "scripts/pm.py"
        # Hook commands run through a shell; the default home is written as ~/... like the docs show it.
        self.script_command = (f"~/{script.relative_to(Path.home())}" if self.home == default
                               else shlex.quote(str(script)))
        self.hooks = self.original = None

    @property
    def detected(self):
        return self.home.is_dir()

    def command(self, action):
        return f"python3 {self.script_command} {action}"

    def read_hooks(self):
        path = self.hooks_path
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(value, dict) or not isinstance(value.get("hooks", {}), dict):
            raise ValueError(f"{path.name} and its hooks must be JSON objects")
        for entries in value.get("hooks", {}).values():
            if not isinstance(entries, list) or any(
                not isinstance(entry, dict) or not isinstance(entry.get("hooks", []), list)
                or any(not isinstance(hook, dict) for hook in entry.get("hooks", []))
                for entry in entries
            ):
                raise ValueError(f"{path} contains an unsupported hook structure; left unchanged")
        return value

    def hooks_present(self, value):
        return all(any(hook.get("command") == self.command(action)
                       for entry in value.get("hooks", {}).get(event, []) for hook in entry.get("hooks", []))
                   for event, action, _ in HOOKS)

    def plan(self, uninstall):
        """Compute the new hooks file in memory; nothing is written here."""
        value = self.read_hooks()
        original = copy.deepcopy(value)
        if uninstall:
            strip_hooks(value, lambda command: SCRIPT in command)
            if original.get("hooks") and not value.get("hooks"):
                del value["hooks"]
        else:
            # `hook-mirror` was the turn hook's earlier name; `hook-turn` replaces it.
            strip_hooks(value, lambda command: SCRIPT in command and command.split()[-1:] == ["hook-mirror"])
            hooks = value.setdefault("hooks", {})
            for event, action, timeout in HOOKS:
                entries = hooks.setdefault(event, [])
                if any(hook.get("command") == self.command(action) for entry in entries for hook in entry.get("hooks", [])):
                    print(f"Skip {self.label} {event}: PM command already installed.")
                    continue
                hook = {"type": "command", "command": self.command(action), "timeout": timeout}
                entry = {"hooks": [hook]}
                if event == "SessionStart" and self.name == "claude":
                    entry["matcher"] = "^(startup|resume|clear|compact)$"
                if event == "Stop":
                    hook["async"] = True  # both Claude Code and Codex accept the key
                entries.append(entry)
        self.hooks, self.original = value, original


class Setup:
    def __init__(self, args, repo=None):
        self.args = args
        self.source = Path(__file__).resolve().parent / "skill"
        self.repo = repo or self.source.parent
        homes = {name: getattr(args, f"{name}_home", None) for name in AGENTS}
        self.all = [Agent(name, homes[name]) for name in AGENTS]
        self.prefix = "Would " if args.dry_run else ""
        self.notes = []
        chosen = getattr(args, "agents", None)
        if chosen:
            self.agents = [agent for agent in self.all if agent.name in chosen]
        elif args.uninstall:
            self.agents = list(self.all)
        else:
            self.agents = [agent for agent in self.all if agent.detected]
            if not self.agents:
                self.agents = [self.all[0]]
                self.notes.append(f"No coding agent home found ({', '.join(str(a.home) for a in self.all)}); "
                                  f"installing for {self.all[0].label}.")

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
        """Read and plan every hooks file first, so an invalid one aborts the install before anything is written."""
        for note in self.notes:
            print(note)
        for agent in self.agents:
            if agent.hooks_path is None:
                continue
            try:
                agent.plan(self.args.uninstall)
            except (OSError, ValueError) as error:
                if not self.args.uninstall:
                    raise
                print(f"Warning: skip hook cleanup for {agent.label}: {error}")
                agent.hooks = agent.original = None

    def save_settings(self):
        for agent in self.agents:
            if agent.hooks is None:
                continue
            if agent.hooks == agent.original:
                print(f"Skip {agent.hooks_path}: no hook changes needed.")
                continue
            backup = agent.hooks_path.with_name(agent.hooks_path.name + ".pm-backup")
            if agent.hooks_path.exists() and not backup.exists():
                print(f"{self.prefix}Back up {agent.hooks_path.name} to {backup}")
                if not self.args.dry_run:
                    shutil.copy2(agent.hooks_path, backup)
            print(f"{self.prefix}Update hooks in {agent.hooks_path}")
            if not self.args.dry_run:
                write_json(agent.hooks_path, agent.hooks)

    def install_skill(self):
        for agent in self.agents:
            self.copy_files(self.source, agent.skill, ("test_pm.py", "__pycache__", ".DS_Store"))

    def remove_skill(self):
        for agent in self.agents:
            if agent.skill.exists() or agent.skill.is_symlink():
                print(f"{self.prefix}Remove {agent.skill}")
                if not self.args.dry_run:
                    remove_path(agent.skill)
            else:
                print(f"Skip removal: {agent.skill} is absent.")

    def kept(self):
        print(f"Keep the ledger and configuration: {ledger_home()}.")
        print("Keep the *.pm-backup copies of hooks files.")

    def finish(self):
        names = ", ".join(agent.label for agent in self.agents)
        first = self.agents[0]
        print(f'Next, start {names} in your project inside Herdr and say "act as PM for this project",')
        print(f"or start a PM from a terminal: python3 {first.script_command} start --repo <project> --kind {first.name}")
        if any(agent.name == "codex" for agent in self.agents):
            print("Codex runs these hooks once you trust them (it asks at its next start) and while `hooks` is on "
                  "under [features] in ~/.codex/config.toml (the default; check with `codex features list`).")
        if self.args.dry_run:
            print("Dry run complete; no files written.")
        else:
            print(f"Installation complete. Restart running sessions of {names} to load the skill and hooks.")

    def status(self):
        bundled = fingerprint(self.source / "scripts/pm.py")
        if bundled is None:
            raise ValueError("bundled skill/scripts/pm.py is missing")
        result = {"agents": {}, "bundled": bundled,
                  "summary": {"detected": [], "installed": [], "ready": [], "outdated": []}}
        errors = []
        for agent in self.all:
            installed = fingerprint(agent.skill / "scripts/pm.py")
            facts = {"label": agent.label, "home": str(agent.home), "detected": agent.detected,
                     "skill_present": (agent.skill / "SKILL.md").is_file() and installed is not None,
                     "script_matches": installed == bundled, "installed": installed}
            if agent.hooks_path is not None:
                facts["hooks_present"] = False
                try:
                    facts["hooks_present"] = agent.hooks_present(agent.read_hooks())
                except (OSError, ValueError) as error:
                    facts["error"] = f"Install failed: {error}"
                    errors.append(facts["error"])
            result["agents"][agent.name] = facts
            summary = result["summary"]
            if facts["detected"]:
                summary["detected"].append(agent.name)
            if facts["skill_present"]:
                summary["installed"].append(agent.name)
            if installed is not None and not facts["script_matches"]:
                summary["outdated"].append(agent.name)
            if facts["skill_present"] and facts["script_matches"] and facts.get("hooks_present", True):
                summary["ready"].append(agent.name)
        if errors:
            result["error"] = "; ".join(errors)
        return result


def add_agent_arguments(parser):
    parser.add_argument("--agents", type=agent_list, metavar="claude,codex,pi",
                        help="agents to set up (default: every one whose home exists; Claude Code when none does)")


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
    add_agent_arguments(parser)
    parser.add_argument("--dry-run", action="store_true", help="print planned changes without writing files")
    parser.add_argument("--uninstall", action="store_true", help="remove PM hooks and skills; keep the ledger")
    parser.add_argument("--status", action="store_true", help="print read-only setup facts per agent as JSON")
    parser.add_argument("--claude-home", help="Claude Code home (default: CLAUDE_HOME, else ~/.claude)")
    parser.add_argument("--codex-home", help="Codex home (default: CODEX_HOME, else ~/.codex)")
    parser.add_argument("--pi-home", help="pi agent folder (default: PI_CODING_AGENT_DIR, else ~/.pi/agent)")
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
