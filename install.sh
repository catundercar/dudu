#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 - "$REPO_ROOT" "$@" <<'PY'
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import importlib.util

repo = Path(sys.argv.pop(1))
# Import without writing bytecode, including during --dry-run.
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("pm_setup", repo / "mods/pm-dash/setup.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

parser = argparse.ArgumentParser(prog="install.sh", description="Install the PM skill for your coding agents and optional Herdr desktop mods.")
installer.add_agent_arguments(parser)
parser.add_argument("--desktop", action="store_true", help="install desktop mods even if HERDR_APP_HOME is absent")
parser.add_argument("--dry-run", action="store_true", help="print planned changes without writing files")
parser.add_argument("--uninstall", action="store_true", help="remove PM hooks, skills, mods and layout; keep the ledger")
args = parser.parse_args()
desktop = Path(os.environ.get("HERDR_APP_HOME") or Path.home() / ".config/herdr-app").expanduser().absolute()
prefix = "Would " if args.dry_run else ""
generated_by = "dudu install.sh"
# The pm layout draws notifications with pm-toast, which hides dispatched workers' agent notices.
TOAST = "pm-toast"
TOAST_HINT = f'"toast": "{TOAST}"'
# The PM list sits right above the agents list; the mod sizes its own block.
PM_LIST = {"id": "pm-list", "type": "block", "size": {"px": 30}, "content": {"mod": "pm-list"}}
# The project view: a child of the pm-stage stack, beside the work column and the board.
PM_PROJECT = {"id": "pm-project", "type": "block", "content": {"mod": "pm-project"}}
MODS = ("pm-dash", "pm-nav", "pm-list", "pm-toast", "pm-project")
setup = installer.Setup(args, repo=repo)
write_json, remove_path = installer.write_json, installer.remove_path


def nodes(tree):
    if not isinstance(tree, dict):
        raise ValueError("layout nodes must be objects")
    yield tree
    children = tree.get("children", [])
    if not isinstance(children, list):
        raise ValueError("layout children must be arrays")
    for child in children:
        yield from nodes(child)


def has_mod(node, name):
    content = node.get("content")
    return node.get("id") == name or (isinstance(content, dict) and content.get("mod") == name)


def insert_pm_list(children):
    agents = [i for i, child in enumerate(children) if isinstance(child, dict) and has_mod(child, "agents")]
    children.insert(agents[0] if agents else len(children), dict(PM_LIST, size=dict(PM_LIST["size"])))


def manual_layout(reason):
    print(f"Skip automatic layout: {reason}")
    print(f"Manual fallback (also in README.md): copy {desktop / 'layouts/main.json'} to {desktop / 'layouts/pm.json'}.")
    print('In sidebar-lists.children, insert first: {"id":"pm-nav","type":"block","size":{"px":64},"content":{"mod":"pm-nav"}}')
    print(f'and right before the agents block: {json.dumps(PM_LIST, separators=(",", ":"))}')
    print('Replace the work column with: {"id":"pm-stage","type":"stack","active":"work","children":[<original work node>,'
          '{"id":"pm-board","type":"block","content":{"mod":"pm-dash"}},' + json.dumps(PM_PROJECT, separators=(",", ":")) + ']}')
    print(f'At the root, add: {TOAST_HINT}')
    print("Keep the original work node intact; if main.json is missing, obtain the default layout from your Herdr desktop installation first.")


def back_up(target):
    layout_backup = target.with_name("pm.json.pm-backup")
    if not layout_backup.exists():
        print(f"{prefix}Back up layout to {layout_backup}")
        if not args.dry_run:
            shutil.copy2(target, layout_backup)


def install_layout():
    target = desktop / "layouts/pm.json"
    source = desktop / "layouts/main.json"
    try:
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if any(has_mod(node, "pm-nav") for node in nodes(existing)):
                changed, hint = False, None
                parent = next((node for node in nodes(existing)
                               if any(isinstance(child, dict) and has_mod(child, "pm-nav")
                                      for child in node.get("children", []))), None)
                has_list = any(has_mod(node, "pm-list") for node in nodes(existing))
                if not has_list and parent is None:
                    # Never fall back to regenerating: that would replace the person's layout.
                    print(f"Skip pm-list: no column in {target} holds pm-nav. Add this block by hand, "
                          f"right before the agents block: {json.dumps(PM_LIST, separators=(',', ':'))}")
                elif not has_list:
                    # A layout from before pm-list, the person's own edits included: add only the block.
                    insert_pm_list(parent["children"])
                    back_up(target)
                    print(f"{prefix}Add the pm-list block to {target}")
                    changed = True
                stage = next((node for node in nodes(existing) if node.get("id") == "pm-stage"
                              and node.get("type") == "stack" and isinstance(node.get("children"), list)), None)
                if stage is not None and not any(has_mod(node, "pm-project") for node in nodes(existing)):
                    # A layout from before the project view: add only its block to the stack.
                    stage["children"].append(dict(PM_PROJECT, content=dict(PM_PROJECT["content"])))
                    back_up(target)
                    print(f"{prefix}Add the pm-project block to {target}")
                    changed = True
                if "toast" not in existing:
                    if existing.get("generated_by") == generated_by:
                        # A layout this installer generated before pm-toast existed.
                        existing["toast"] = TOAST
                        print(f"{prefix}Add {TOAST_HINT} to {target}")
                        changed = True
                    else:
                        hint = f"To hide finished-worker toasts, add {TOAST_HINT} at the root of {target}."
                if changed and not args.dry_run:
                    write_json(target, existing)
                if not changed:
                    print(f"Skip layout: {target} already contains pm-nav.")
                if hint:
                    print(hint)
                return
        tree = json.loads(source.read_text(encoding="utf-8"))
        all_nodes = list(nodes(tree))
        sidebars = [node for node in all_nodes if node.get("id") == "sidebar-lists"]
        works = [node for node in all_nodes if node.get("id") == "work"]
        if (len(sidebars) != 1 or len(works) != 1
                or sidebars[0].get("type") != "column" or works[0].get("type") != "column"
                or "children" not in sidebars[0] or "children" not in works[0]
                or any(node.get("id") in ("pm-nav", "pm-list", "pm-stage", "pm-board", "pm-project") for node in all_nodes)):
            raise ValueError("expected one sidebar-lists column and one work column, without PM nodes")
        sidebar, work = sidebars[0], works[0]
        parents = [node for node in all_nodes if any(child is work for child in node.get("children", []))]
        if len(parents) != 1 or sidebar in list(nodes(work)) or work in list(nodes(sidebar)):
            raise ValueError("sidebar-lists and work must be separate branches")
        sidebar["children"].insert(0, {"id": "pm-nav", "type": "block", "size": {"px": 64}, "content": {"mod": "pm-nav"}})
        insert_pm_list(sidebar["children"])
        children = parents[0]["children"]
        children[children.index(work)] = {"id": "pm-stage", "type": "stack", "active": "work", "children": [
            work, {"id": "pm-board", "type": "block", "content": {"mod": "pm-dash"}},
            dict(PM_PROJECT, content=dict(PM_PROJECT["content"]))]}
    except (OSError, ValueError, AttributeError) as error:
        manual_layout(str(error))
        return
    tree["toast"] = TOAST
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
    setup.prepare()
    if args.uninstall:
        print('Before removing the pm layout, switch back: herdr-app do layout.switch \'{"name":"main"}\'')
        setup.save_settings()
        setup.remove_skill()
        for path in (*(desktop / "mods" / name for name in MODS), desktop / "layouts/pm.json"):
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
        setup.kept()
        return

    setup.install_skill()
    if desktop.exists() or args.desktop:
        for name in MODS:
            setup.copy_files(repo / "mods" / name, desktop / "mods" / name,
                       ("gpui-kit.d.ts", "jsconfig.json", "*.test.mjs", "__pycache__", ".DS_Store"))
        install_layout()
        print('Next, select the pm layout: herdr-app do layout.switch \'{"name":"pm"}\'')
        print("Then click the PM board entry in the sidebar. If layout generation was skipped, finish the manual steps first.")
    else:
        print(f"Skip desktop: {desktop} does not exist; use --desktop to install it explicitly.")
    setup.save_settings()
    setup.finish()


installer.run(main)
PY
