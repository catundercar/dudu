#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 - "$REPO_ROOT" "$@" <<'PY'
import argparse
import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile

repo = Path(sys.argv.pop(1))
parser = argparse.ArgumentParser(prog="install.sh", description="Install the PM skill and optional Herdr desktop mods.")
parser.add_argument("--discord", action="store_true", help="add optional chat-mirroring hooks")
parser.add_argument("--desktop", action="store_true", help="install desktop mods even if HERDR_APP_HOME is absent")
parser.add_argument("--dry-run", action="store_true", help="print planned changes without writing files")
parser.add_argument("--uninstall", action="store_true", help="remove PM hooks, skill, mods and layout; keep the ledger")
args = parser.parse_args()
claude = Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude").expanduser().absolute()
desktop = Path(os.environ.get("HERDR_APP_HOME") or Path.home() / ".config/herdr-app").expanduser().absolute()
settings_path = claude / "settings.json"
backup = claude / "settings.json.pm-backup"
skill = claude / "skills/pm"
script = skill / "scripts/pm.py"
script_command = ("~/.claude/skills/pm/scripts/pm.py" if claude == Path.home() / ".claude"
                  else shlex.quote(str(script)))
prefix = "Would " if args.dry_run else ""
generated_by = "dudu install.sh"


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


def read_settings():
    value = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
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


def save_settings(settings, original):
    if settings == original:
        print("Skip settings: no hook changes needed.")
        return
    if settings_path.exists() and not backup.exists():
        print(f"{prefix}Back up settings to {backup}")
        if not args.dry_run:
            shutil.copy2(settings_path, backup)
    print(f"{prefix}Update hooks in {settings_path}")
    if not args.dry_run:
        write_json(settings_path, settings)


def copy_files(source, target, excluded):
    if source.resolve() == target.resolve():
        print(f"Skip copy: {target} already points to the repository source.")
        return
    if target.exists() or target.is_symlink():
        print(f"{prefix}Remove old installation at {target}")
        if not args.dry_run:
            remove_path(target)
    print(f"{prefix}Copy {source.relative_to(repo)} to {target}")
    if not args.dry_run:
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(*excluded))


def remove_path(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def nodes(tree):
    if not isinstance(tree, dict):
        raise ValueError("layout nodes must be objects")
    yield tree
    children = tree.get("children", [])
    if not isinstance(children, list):
        raise ValueError("layout children must be arrays")
    for child in children:
        yield from nodes(child)


def manual_layout(reason):
    print(f"Skip automatic layout: {reason}")
    print(f"Manual fallback (also in README.md): copy {desktop / 'layouts/main.json'} to {desktop / 'layouts/pm.json'}.")
    print('In sidebar-lists.children, insert first: {"id":"pm-nav","type":"block","size":{"px":64},"content":{"mod":"pm-nav"}}')
    print('Replace the work column with: {"id":"pm-stage","type":"stack","active":"work","children":[<original work node>,{"id":"pm-board","type":"block","content":{"mod":"pm-dash"}}]}')
    print("Keep the original work node intact; if main.json is missing, obtain the default layout from your Herdr desktop installation first.")


def install_layout():
    target = desktop / "layouts/pm.json"
    source = desktop / "layouts/main.json"
    try:
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if any(node.get("id") == "pm-nav" or node.get("content", {}).get("mod") == "pm-nav"
                   for node in nodes(existing)):
                print(f"Skip layout: {target} already contains pm-nav.")
                return
        tree = json.loads(source.read_text(encoding="utf-8"))
        all_nodes = list(nodes(tree))
        sidebars = [node for node in all_nodes if node.get("id") == "sidebar-lists"]
        works = [node for node in all_nodes if node.get("id") == "work"]
        if (len(sidebars) != 1 or len(works) != 1
                or sidebars[0].get("type") != "column" or works[0].get("type") != "column"
                or "children" not in sidebars[0] or "children" not in works[0]
                or any(node.get("id") in ("pm-nav", "pm-stage", "pm-board") for node in all_nodes)):
            raise ValueError("expected one sidebar-lists column and one work column, without PM nodes")
        sidebar, work = sidebars[0], works[0]
        parents = [node for node in all_nodes if any(child is work for child in node.get("children", []))]
        if len(parents) != 1 or sidebar in list(nodes(work)) or work in list(nodes(sidebar)):
            raise ValueError("sidebar-lists and work must be separate branches")
        sidebar["children"].insert(0, {"id": "pm-nav", "type": "block", "size": {"px": 64}, "content": {"mod": "pm-nav"}})
        children = parents[0]["children"]
        children[children.index(work)] = {"id": "pm-stage", "type": "stack", "active": "work", "children": [
            work, {"id": "pm-board", "type": "block", "content": {"mod": "pm-dash"}}]}
    except (OSError, ValueError, AttributeError) as error:
        manual_layout(str(error))
        return
    tree["generated_by"] = generated_by
    if "version" in tree:
        tree["cloned_from"] = {"name": "main", "version": tree["version"]}
    layout_backup = target.with_name("pm.json.pm-backup")
    if target.exists() and not layout_backup.exists():
        print(f"{prefix}Back up layout to {layout_backup}")
        if not args.dry_run:
            shutil.copy2(target, layout_backup)
    print(f"{prefix}Generate {target} from {source}")
    if not args.dry_run:
        write_json(target, tree)


def main():
    try:
        settings = read_settings()
    except (OSError, ValueError) as error:
        if not args.uninstall:
            raise
        print(f"Warning: skip hook cleanup: {error}")
        settings = {}
    original = copy.deepcopy(settings)
    if args.uninstall:
        print('Before removing the pm layout, switch back: herdr-app do layout.switch \'{"name":"main"}\'')
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
        save_settings(settings, original)
        for path in (skill, desktop / "mods/pm-dash", desktop / "mods/pm-nav", desktop / "layouts/pm.json"):
            if path.exists() or path.is_symlink():
                if path == desktop / "layouts/pm.json":
                    try:
                        layout = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, ValueError) as error:
                        print(f"Keep layout {path}: cannot verify ownership ({error}).")
                        continue
                    if not isinstance(layout, dict) or layout.get("generated_by") != generated_by:
                        print(f"Keep layout {path}: not marked as generated by this installer.")
                        continue
                print(f"{prefix}Remove {path}")
                if not args.dry_run:
                    remove_path(path)
            else:
                print(f"Skip removal: {path} is absent.")
        print(f"Keep ledger and configuration: {claude / 'pm'} (also any custom PM_HOME).")
        print("Keep settings.json.pm-backup and any Discord credentials/state.")
        return

    hooks = settings.setdefault("hooks", {})
    events = [("SessionStart", "hook-session-start", 10)]
    if args.discord:
        events += [("UserPromptSubmit", "hook-mirror", 15), ("Stop", "hook-mirror", 15)]
    else:
        print("Skip Discord hooks: --discord not requested; existing hooks are kept.")
    for event, action, timeout in events:
        command = f"python3 {script_command} {action}"
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
    copy_files(repo / "skill/pm", skill, ("test_pm.py", "__pycache__", ".DS_Store"))
    if desktop.exists() or args.desktop:
        for name in ("pm-dash", "pm-nav"):
            copy_files(repo / "mods" / name, desktop / "mods" / name,
                       ("gpui-kit.d.ts", "jsconfig.json", "*.test.mjs", "__pycache__", ".DS_Store"))
        install_layout()
        print('Next, select the pm layout: herdr-app do layout.switch \'{"name":"pm"}\'')
        print("Then click the PM board entry in the sidebar. If layout generation was skipped, finish the manual steps first.")
    else:
        print(f"Skip desktop: {desktop} does not exist; use --desktop to install it explicitly.")
    save_settings(settings, original)
    print('Next, start a Claude Code session in your project inside Herdr and say "act as PM for this project",')
    print(f"or run: python3 {script_command} claim")
    if args.dry_run:
        print("Dry run complete; no files written.")
    else:
        print("Installation complete. Restart existing Claude Code sessions to load the skill and hooks.")


try:
    main()
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
PY
