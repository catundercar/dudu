#!/usr/bin/env python3
"""What a carve did to the code: compare every top-level function, class and assignment of pm.py's code between two
trees, wherever in pmlib it lives now.

    python3 moved.py --old <scripts dir> --new <scripts dir> [--show NAME ...]

A scripts dir holds either pm.py alone (before stage 1) or pm.py with pmlib/. For each top-level name it reports:
moved (same code, another module), changed (code differs: prints which module and, with --show, a diff), gone, new,
and names defined in two modules. "Same code" compares the syntax tree, so comments, blank lines and line breaks do not
count; docstrings do. Exit code 1 when something is gone or defined twice.
"""
import argparse
import ast
import difflib
import sys
from pathlib import Path


def sources(scripts):
    scripts = Path(scripts)
    package = scripts / "pmlib"
    if package.is_dir():
        return sorted(p for p in package.rglob("*.py") if "__pycache__" not in p.parts
                      and not p.name.startswith("test_") and p.name != "compat.py")
    return [scripts / "pm.py"]


def definitions(scripts):
    """{name: [(module, kind, dump, source)]} for the top-level definitions of every source file."""
    found = {}
    root = Path(scripts)
    for path in sources(scripts):
        text = path.read_text(encoding="utf-8")
        module = str(path.relative_to(root).with_suffix(""))
        for node in ast.parse(text, str(path)).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names, kind = [node.name], "def" if not isinstance(node, ast.ClassDef) else "class"
            elif isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                kind = "value"
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names, kind = [node.target.id], "value"
            else:
                continue
            segment = ast.get_source_segment(text, node) or ""
            for name in names:
                found.setdefault(name, []).append((module, kind, ast.dump(node), segment))
    return found


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.add_argument("--show", nargs="*", default=[], help="print the diff of these changed names ('all': every one)")
    a = p.parse_args()
    old, new = definitions(a.old), definitions(a.new)
    moved, changed, gone, added, twice = [], [], [], [], []
    for name, olds in sorted(old.items()):
        news = new.get(name)
        if not news:
            gone.append((name, olds[0][0]))
            continue
        # A name bound twice in one module (a fallback in try/except, a redefinition) is compared as the list it is.
        if len({m for m, *_ in news}) > 1:
            twice.append((name, sorted({m for m, *_ in news})))
        if [d for _, _, d, _ in olds] == [d for _, _, d, _ in news]:
            if olds[0][0] != news[0][0]:
                moved.append((name, olds[0][0], news[0][0]))
        else:
            changed.append((name, olds[0][0], news[0][0], olds[-1][3], news[-1][3]))
    for name, news in sorted(new.items()):
        if name not in old:
            added.append((name, news[0][0]))
    by_target = {}
    for name, _, target in moved:
        by_target.setdefault(target, []).append(name)
    print(f"moved unchanged: {len(moved)}")
    for target, names in sorted(by_target.items()):
        print(f"  -> {target}: {len(names)}: {', '.join(names)}")
    print(f"changed: {len(changed)}")
    for name, was, now, before, after in changed:
        print(f"  {name}: {was} -> {now}")
        if "all" in a.show or name in a.show:
            for line in difflib.unified_diff(before.splitlines(), after.splitlines(), "old", "new", lineterm="", n=1):
                print("      " + line)
    print(f"new: {len(added)}")
    by_module = {}
    for name, module in added:
        by_module.setdefault(module, []).append(name)
    for module, names in sorted(by_module.items()):
        print(f"  {module}: {', '.join(names)}")
    print(f"gone: {len(gone)}")
    for name, module in gone:
        print(f"  {name} (was in {module})")
    print(f"defined in two modules: {len(twice)}")
    for name, modules in twice:
        print(f"  {name}: {', '.join(modules)}")
    sys.exit(1 if gone or twice else 0)


if __name__ == "__main__":
    main()
