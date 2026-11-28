#!/usr/bin/env python3
"""Install the bundled PM skill and its hooks for your coding agents; --status never writes files."""
import argparse
import copy
import ctypes
import datetime
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

# Where each coding agent keeps its skills and hooks: label, environment variable that moves its home,
# default home under ~, and the hooks file inside that home (None: the agent has no hooks).
AGENTS = {
    "claude": ("Claude Code", "CLAUDE_HOME", ".claude", "settings.json"),
    "codex": ("Codex", "CODEX_HOME", ".codex", "hooks.json"),
    "pi": ("pi", "PI_CODING_AGENT_DIR", ".pi/agent", None),
}
# Every agent with hooks gets all five. SessionStart syncs the ledger after compaction; PreCompact outputs
# PM preservation rules (Claude Code & Codex); PreToolUse redirects PM interactive question tools to ledger
# question cards; hook-turn logs conversation turns (UserPromptSubmit output is added to the session's
# context, so only Stop runs asynchronously).
HOOKS = [
    ("SessionStart", "hook-session-start", 10),
    ("PreCompact", "hook-pre-compact", 10),
    ("PreToolUse", "hook-pre-tool", 10),
    ("UserPromptSubmit", "hook-turn", 15),
    ("Stop", "hook-turn", 15),
]
PRE_TOOL_MATCHERS = {
    "claude": "AskUserQuestion|Bash|Edit|Write|MultiEdit|NotebookEdit",
    "codex": "request_user_input|ask_user|AskUserQuestion|Bash|shell|local_shell_call|apply_patch|write_file|edit_file|Edit|Write",
}
SCRIPT = "skills/pm/scripts/pm.py"
WINDOWS = os.name == "nt"


def python_command():
    """How a command line names a Python 3 that runs pm.py (a copy of pm.py's): python3 on macOS and Linux; on
    Windows the py launcher, else the Python running this setup (python3 there may be the Microsoft Store stub)."""
    if not WINDOWS:
        return "python3"
    if shutil.which("py"):
        return "py -3"
    exe = PureWindowsPath(sys.executable).as_posix()
    return f'"{exe}"' if " " in exe else exe


def restore_windows_acl(path, recursive=False):
    """On Windows, reset path's NTFS DACL so it inherits permissions from its parent directory.
    Prevents elevated OpenSSH installs (running as Administrators) from leaving restricted ACLs that
    block non-elevated desktop apps such as herdr-app.exe with os error 5 (Access is denied)."""
    if sys.platform != "win32":
        return False
    target = Path(path)
    if not target.exists():
        return False
    cmd = ["icacls", str(target), "/reset"]
    if recursive:
        cmd.append("/T")
    cmd.append("/Q")
    try:
        result = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except OSError:
        return False


def _create_temp_file(parent, prefix):
    """Create a unique temporary file in parent. On Windows, avoid tempfile's restricted DACL
    so the file inherits its parent directory's NTFS ACL."""
    if sys.platform == "win32":
        for _ in range(64):
            candidate = parent / f"{prefix}{secrets.token_hex(8)}.tmp"
            try:
                stream = open(candidate, "x", encoding="utf-8")
                return candidate, stream
            except FileExistsError:
                continue
        raise FileExistsError(f"could not create temporary file in {parent}")
    stream = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=parent, prefix=prefix, delete=False)
    return Path(stream.name), stream


def _make_staging_dir(stage_dir, prefix):
    """Create a unique staging directory in stage_dir. On Windows, use normal os.mkdir instead of
    tempfile.mkdtemp (which applies a 0o700 protected DACL that strips inherited user permissions
    under elevated OpenSSH sessions)."""
    if sys.platform == "win32":
        for _ in range(64):
            candidate = stage_dir / f"{prefix}{secrets.token_hex(6)}"
            try:
                os.mkdir(candidate)
                return candidate
            except FileExistsError:
                continue
        raise FileExistsError(f"could not create staging directory in {stage_dir}")
    return Path(tempfile.mkdtemp(prefix=prefix, dir=stage_dir))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        temporary, stream = _create_temp_file(path.parent, f".{path.name}.")
        with stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        if path.exists():
            temporary.chmod(path.stat().st_mode & 0o777)
        _replace_file(temporary, path)
        temporary = None
        restore_windows_acl(path, recursive=False)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def remove_path(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _atomic_exchange_dirs(staging, target):
    """Atomically exchange two directories on the same filesystem via a single kernel syscall.
    Returns True on success, False if unsupported on this platform or filesystem."""
    try:
        if sys.platform == "darwin":
            libc = ctypes.CDLL(None, use_errno=True)
            fn = libc.renameatx_np
            fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            fn.restype = ctypes.c_int
            # AT_FDCWD = -2 on macOS, RENAME_SWAP = 0x00000002
            return fn(-2, os.fsencode(staging), -2, os.fsencode(target), 0x00000002) == 0
        if sys.platform.startswith("linux"):
            libc = ctypes.CDLL(None, use_errno=True)
            fn = getattr(libc, "renameat2", None)
            if fn is None:
                return False
            fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            fn.restype = ctypes.c_int
            # AT_FDCWD = -100 on Linux, RENAME_EXCHANGE = 2
            return fn(-100, os.fsencode(staging), -100, os.fsencode(target), 2) == 0
    except (OSError, AttributeError):
        return False
    return False


def _replace_file(source, target, attempts=6):
    """os.replace, retried briefly: on Windows a reader holding the file open can refuse the swap for a moment."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


# Written last, so the reload their change triggers sees every other new file already in place.
ENTRY_FILES = ("mod.json", "main.js")


def _sync_tree_in_place(staging, target):
    """Make target hold exactly staging's files while target itself stays the same folder: each file moves in
    with an atomic same-filesystem replace (a watcher never reads half a file), the mod's entry files last,
    then what the new tree no longer has is removed. Moves files out of staging; the caller removes the rest."""
    moves = []
    keep = set()
    for root, dirs, files in os.walk(staging):
        rel = Path(root).relative_to(staging)
        for name in dirs:
            keep.add(rel / name)
            dest = target / rel / name
            if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
                remove_path(dest)
            dest.mkdir(exist_ok=True)
        for name in files:
            keep.add(rel / name)
            moves.append((Path(root) / name, target / rel / name, rel == Path(".") and name in ENTRY_FILES))
    for source, dest, _entry in sorted(moves, key=lambda move: (move[2], ENTRY_FILES.index(move[1].name) if move[2] else 0)):
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        _replace_file(source, dest)
    for root, dirs, files in os.walk(target, topdown=False):
        rel = Path(root).relative_to(target)
        for name in files + dirs:
            if rel / name not in keep:
                try:
                    remove_path(Path(root) / name)
                except FileNotFoundError:
                    pass


def _staging_parent(target, staging_root=None):
    """Choose a same-filesystem directory outside target.parent (e.g. ~/.config/herdr-app/.dudu-staging
    instead of mods/, or ~/.claude/.dudu-staging instead of skills/) so file watchers and mod/skill
    scanners never see temporary staging or backup folders inside target.parent.
    Returns (directory, should_prune_if_empty)."""
    target_parent_dev = os.stat(target.parent).st_dev
    if staging_root is not None:
        candidate = Path(staging_root)
        candidate.mkdir(parents=True, exist_ok=True)
        if os.stat(candidate).st_dev == target_parent_dev:
            return candidate, False
        raise OSError(f"staging_root {candidate} is not on the same filesystem as {target.parent}")
    grandparent = target.parent.parent
    if grandparent != target.parent:
        candidate = grandparent / ".dudu-staging"
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            if os.stat(candidate).st_dev == target_parent_dev:
                return candidate, True
            try:
                candidate.rmdir()
            except OSError:
                pass
        except OSError:
            pass
    return target.parent, False


def replace_tree(source, target, excluded, staging_root=None):
    """Copy source into a same-filesystem staging directory outside target.parent, then atomically swap it into target.
    Avoids exposing half-copied, missing, or temporary directories inside mods/ or skills/ to file watchers."""
    target.parent.mkdir(parents=True, exist_ok=True)
    stage_dir, prune_stage_dir = _staging_parent(target, staging_root=staging_root)
    staging = _make_staging_dir(stage_dir, f".{target.name}.staging-")
    backup = None
    try:
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns(*excluded), dirs_exist_ok=True)
        if not (target.exists() or target.is_symlink()):
            os.replace(staging, target)
            staging = None
        elif target.is_dir() and not target.is_symlink() and _atomic_exchange_dirs(staging, target):
            # Atomic swap succeeded: staging now holds the previous target tree, removed in finally.
            pass
        elif target.is_dir() and not target.is_symlink():
            # No atomic exchange (Windows, or a filesystem without RENAME_EXCHANGE): update the folder in
            # place, never renaming it. A running Herdr on Windows watches each mod folder by handle; when
            # the folder is renamed aside its reload fails with "cannot read <mod>: Access is denied
            # (os error 5)" and later edits are never seen, so the window keeps the old code until restart.
            _sync_tree_in_place(staging, target)
        else:
            # Fallback for a symlink or file target: move target aside into stage_dir on the same
            # filesystem, rename staging into place, and roll back if the second rename fails.
            backup = _make_staging_dir(stage_dir, f".{target.name}.old-")
            backup.rmdir()
            os.rename(target, backup)
            try:
                os.rename(staging, target)
                staging = None
            except BaseException:
                if not (target.exists() or target.is_symlink()) and (backup.exists() or backup.is_symlink()):
                    try:
                        os.rename(backup, target)
                        backup = None
                    except OSError:
                        pass
                raise
        restore_windows_acl(target, recursive=True)
    finally:
        if staging is not None and (staging.exists() or staging.is_symlink()):
            remove_path(staging)
        if backup is not None and (backup.exists() or backup.is_symlink()):
            remove_path(backup)
        if prune_stage_dir:
            try:
                stage_dir.rmdir()
            except OSError:
                pass


def agent_list(text):
    """argparse type for --agents claude,codex,pi."""
    names = [name.strip() for name in text.split(",") if name.strip()]
    unknown = [name for name in names if name not in AGENTS]
    if unknown or not names:
        raise argparse.ArgumentTypeError(f"choose from {', '.join(AGENTS)} (got {text!r})")
    return list(dict.fromkeys(names))


def ledger_home():
    """The rule pm.py uses: PM_HOME, else ~/.claude/pm where an earlier install keeps it (unless it links to ~/.dudu),
    else ~/.dudu."""
    env = os.environ.get("PM_HOME")
    if env:
        return Path(env)
    canonical = Path.home() / ".dudu"
    earlier = Path.home() / ".claude" / "pm"
    if earlier.exists():
        try:
            if canonical.exists() and earlier.samefile(canonical):
                return canonical
        except OSError:
            pass
        return earlier
    return canonical


def legacy_ledger_path():
    """Return ~/.claude/pm when it is an unmigrated legacy ledger directory (not a symlink to ~/.dudu and PM_HOME is unset)."""
    if os.environ.get("PM_HOME"):
        return None
    canonical = Path.home() / ".dudu"
    earlier = Path.home() / ".claude" / "pm"
    if not earlier.is_dir() or earlier.is_symlink():
        return None
    try:
        if canonical.exists() and earlier.samefile(canonical):
            return None
    except OSError:
        pass
    return earlier


# What the skill install leaves out of the bundled skill/, as fnmatch patterns matched against every part of a path:
# test files and test folders (scripts/test_*.py, scripts/tests/), and what Python and Finder write into a copy.
# Anything else, a new module or a package folder beside pm.py included, is installed and fingerprinted.
SKILL_EXCLUDED = ("test_*.py", "tests", "__pycache__", ".DS_Store")


def unreadable_reason(path):
    """Why this user cannot read the folder at path (a sentence), or None when it reads (or is absent).
    Walks it the way fingerprint() does, opening every file, so a folder that lists but whose files are
    denied counts too. Uses os.scandir, not Path.rglob: rglob skips a folder it may not list without a word."""
    def walk(folder):
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    walk(entry.path)
                elif entry.is_file():
                    with open(entry.path, "rb"):
                        pass

    try:
        if path.is_symlink() or not path.is_dir():
            return None
        walk(path)
    except PermissionError as error:
        return f"Cannot read {path}: {error}."
    except OSError:
        return None
    return None


def repair_hint(path):
    """How a person repairs a folder an elevated install left unreadable."""
    if WINDOWS:
        return f'Repair it from an administrator prompt: icacls "{path}" /reset /T /Q'
    return f'Repair it: sudo chown -R "$USER" "{path}"'


def fingerprint(skill):
    """{size, sha256} of the skill folder: every file the install copies, by path and content, so a copy whose
    pm.py and pm_events.py came from different versions is outdated. None without scripts/pm.py."""
    if not (skill / "scripts/pm.py").is_file():
        return None
    digest, size = hashlib.sha256(), 0
    for path in sorted(skill.rglob("*"), key=lambda p: p.relative_to(skill).as_posix()):
        parts = path.relative_to(skill).parts
        if not path.is_file() or any(fnmatch.fnmatch(part, pattern) for part in parts for pattern in SKILL_EXCLUDED):
            continue
        data = path.read_bytes()
        size += len(data)
        digest.update(b"%s\0%d\0" % ("/".join(parts).encode(), len(data)) + data)
    return {"size": size, "sha256": digest.hexdigest()}


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
        # Windows: the shell may be cmd, PowerShell or Git Bash, and only an absolute path in double quotes
        # reads the same in all three; forward slashes, so Git Bash keeps them.
        if WINDOWS:
            self.script_command = f'"{PureWindowsPath(script).as_posix()}"'
        else:
            self.script_command = (f"~/{script.relative_to(Path.home())}" if self.home == default
                                   else shlex.quote(str(script)))
        self.hooks = self.original = None

    @property
    def detected(self):
        return self.home.is_dir()

    def command(self, action):
        return f"{python_command()} {self.script_command} {action}"

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
            if WINDOWS:
                # The Python found may differ from the last setup's (py installed since): replace, not add.
                current = {self.command(action): action for _, action, _ in HOOKS}
                strip_hooks(value, lambda command: SCRIPT in command and command not in current
                            and command.split()[-1:] in ([action] for action in current.values()))
            hooks = value.setdefault("hooks", {})
            for event, action, timeout in HOOKS:
                entries = hooks.setdefault(event, [])
                existing = next(
                    (entry for entry in entries
                     if any(hook.get("command") == self.command(action) for hook in entry.get("hooks", []))),
                    None,
                )
                if existing is not None:
                    wanted_matcher = PRE_TOOL_MATCHERS.get(self.name) if event == "PreToolUse" else None
                    if wanted_matcher and existing.get("matcher") != wanted_matcher:
                        existing["matcher"] = wanted_matcher
                        print(f"Update {self.label} {event} matcher.")
                    else:
                        print(f"Skip {self.label} {event}: PM command already installed.")
                    continue
                hook = {"type": "command", "command": self.command(action), "timeout": timeout}
                entry = {"hooks": [hook]}
                if event == "SessionStart" and self.name == "claude":
                    entry["matcher"] = "^(startup|resume|clear|compact)$"
                if event == "PreToolUse" and self.name in PRE_TOOL_MATCHERS:
                    entry["matcher"] = PRE_TOOL_MATCHERS[self.name]
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
            print(f"{self.prefix}Replace {target} with {source.relative_to(self.repo)}")
        else:
            print(f"{self.prefix}Copy {source.relative_to(self.repo)} to {target}")
        if not self.args.dry_run:
            replace_tree(source, target, excluded)

    def prepare(self):
        """Read and plan every hooks file first, so an invalid one aborts the install before anything is written."""
        for note in self.notes:
            print(note)
        if not self.args.uninstall:
            for agent in self.agents:
                self.repair_unreadable(agent)
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
                if not self.args.dry_run and agent.hooks_path.exists():
                    restore_windows_acl(agent.hooks_path, recursive=False)
                continue
            backup = agent.hooks_path.with_name(agent.hooks_path.name + ".pm-backup")
            if agent.hooks_path.exists() and not backup.exists():
                print(f"{self.prefix}Back up {agent.hooks_path.name} to {backup}")
                if not self.args.dry_run:
                    shutil.copy2(agent.hooks_path, backup)
                    restore_windows_acl(backup, recursive=False)
            print(f"{self.prefix}Update hooks in {agent.hooks_path}")
            if not self.args.dry_run:
                write_json(agent.hooks_path, agent.hooks)

    # What each install copied, so the next one can tell local edits from the files it put there; kept in the
    # ledger home, outside every skills folder (a copy in there would load as a second skill).
    def manifest_path(self, agent):
        return ledger_home() / "install" / f"skill-{agent.name}.json"

    def keep_local_changes(self, agent):
        """Before the installed skill is replaced or removed: when its files differ from what the last install
        copied (or, with no record of one, from the bundle), copy the folder to the ledger home and say so. The
        skill's source is the repository: an edit to the installed copy is lost at the next install otherwise.
        A link (a development install, or a folder linked from elsewhere) is only unlinked: nothing is lost."""
        target = agent.skill
        if target.is_symlink() and target.resolve() != self.source.resolve():
            print(f"  {target} links to {target.resolve()}: the link goes, that folder is left as it is.")
        if not target.is_dir() or target.is_symlink() or target.resolve() == self.source.resolve():
            return
        try:
            record = json.loads(self.manifest_path(agent).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = None
        known = isinstance(record, dict) and record.get("path") == str(target) and "fingerprint" in record
        if fingerprint(target) == (record["fingerprint"] if known else fingerprint(self.source)) \
                or not any(path.is_file() for path in target.rglob("*")):
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = ledger_home() / "install" / "backups" / f"{agent.name}-skill-{stamp}"
        what = "it differs from what the last install copied" if known else \
            "it differs from the version being installed (no record of the last install, so it may hold local edits)"
        print(f"{self.prefix}Back up local changes in {target} to {backup}: {what}")
        print("  The skill's source is the dudu repository (mods/pm-dash/skill): change it there and install again, "
              "or open a pull request; an edit to the installed copy is replaced by the next install.")
        if not self.args.dry_run:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(target, backup, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))

    def record_install(self, agent):
        if self.args.dry_run or not agent.skill.is_dir() or agent.skill.is_symlink():
            return
        write_json(self.manifest_path(agent), {"path": str(agent.skill), "fingerprint": fingerprint(agent.skill)})

    def repair_unreadable(self, agent):
        """A skill folder this user cannot read (an elevated install left it owned by Administrators with a DACL
        that grants the user nothing) fails the install at its first read. Reset its ACL, which works when this
        install is elevated; otherwise stop before anything is written and say how to repair it. A non-elevated
        process cannot take the folder back, nor move it aside: Windows refuses the rename as well (checked
        on Windows 11 with a non-elevated token)."""
        target = agent.skill
        if self.args.dry_run or unreadable_reason(target) is None:
            return
        restore_windows_acl(target, recursive=True)
        reason = unreadable_reason(target)
        if reason is not None:
            raise OSError(f"{reason} {repair_hint(target)}")

    def install_skill(self):
        for agent in self.agents:
            if self.source.resolve() != agent.skill.resolve():
                self.keep_local_changes(agent)
            self.copy_files(self.source, agent.skill, SKILL_EXCLUDED)
            self.record_install(agent)

    def remove_skill(self):
        for agent in self.agents:
            if agent.skill.exists() or agent.skill.is_symlink():
                self.keep_local_changes(agent)
                print(f"{self.prefix}Remove {agent.skill}")
                if not self.args.dry_run:
                    remove_path(agent.skill)
                    self.manifest_path(agent).unlink(missing_ok=True)
            else:
                print(f"Skip removal: {agent.skill} is absent.")

    def kept(self):
        print(f"Keep the ledger and configuration: {ledger_home()}.")
        print("Keep the *.pm-backup copies of hooks files.")

    def finish(self):
        names = ", ".join(agent.label for agent in self.agents)
        first = self.agents[0]
        print(f'Next, start {names} in your project inside Herdr and say "act as PM for this project",')
        print(f"or start a PM from a terminal: {python_command()} {first.script_command} start --repo <project> --kind {first.name}")
        if any(agent.name == "codex" for agent in self.agents):
            print("Codex runs these hooks once you trust them (it asks at its next start) and while `hooks` is on "
                  "under [features] in ~/.codex/config.toml (the default; check with `codex features list`).")
        legacy = legacy_ledger_path()
        if legacy is not None:
            print(f"Note: legacy ledger found at {legacy} (default is now {Path.home() / '.dudu'}).")
            print("  To migrate it with a full backup and compatibility symlink:")
            print(f"    {python_command()} {first.script_command} home --migrate --dry-run")
            print(f"    {python_command()} {first.script_command} home --migrate")
        if self.args.dry_run:
            print("Dry run complete; no files written.")
        else:
            print(f"Installation complete. Restart running sessions of {names} to load the skill and hooks.")

    def status(self):
        bundled = fingerprint(self.source)
        if bundled is None:
            raise ValueError("bundled skill/scripts/pm.py is missing")
        result = {"agents": {}, "bundled": bundled,
                  "summary": {"detected": [], "installed": [], "ready": [], "outdated": []}}
        errors = []
        for agent in self.all:
            # One agent's unreadable folder must not hide the others (nor fail the whole status): it
            # counts as not installed, with the reason and the repair, and Set up moves it aside.
            unreadable = unreadable_reason(agent.skill)
            installed = None if unreadable else fingerprint(agent.skill)
            facts = {"label": agent.label, "home": str(agent.home), "detected": agent.detected,
                     "skill_present": not unreadable and installed is not None and (agent.skill / "SKILL.md").is_file(),
                     "script_matches": installed == bundled, "installed": installed}
            if unreadable:
                facts["unreadable"] = True
                facts["error"] = f"{unreadable} {repair_hint(agent.skill)}"
                errors.append(facts["error"])
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
