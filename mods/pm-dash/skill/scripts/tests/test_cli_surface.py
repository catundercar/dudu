"""The command line of pm.py, frozen: every command, subcommand and argument of build_parser().

Agents, hooks, the mods and older or newer copies of pm.py on the same ledger call pm.py by these names, options,
defaults and positional orders; a refactor that moves build_parser around must leave this dump unchanged. Help
texts and metavars are left out: they may change freely.

PM_UPDATE_GOLDEN=1 rewrites golden/cli_surface.json from the current parser (only when a change is meant).
"""
import argparse
import difflib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
GOLDEN = HERE / "golden" / "cli_surface.json"


def load_pm():
    """Import pm with PM_HOME pointing at an empty temporary folder, so importing it never looks at a real ledger."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    if "pm" in sys.modules:
        return sys.modules["pm"]
    saved = os.environ.get("PM_HOME")
    with tempfile.TemporaryDirectory() as home:
        os.environ["PM_HOME"] = home
        try:
            return importlib.import_module("pm")
        finally:
            if saved is None:
                os.environ.pop("PM_HOME", None)
            else:
                os.environ["PM_HOME"] = saved


def plain(value):
    """A JSON value for a default or a choice; anything else by its repr."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    return repr(value)


def dump_parser(parser):
    arguments, subcommands = [], {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                subcommands[name] = dump_parser(child)
            arguments.append({"subcommands": action.dest, "required": action.required,
                              "action": type(action).__name__})
            continue
        arguments.append({
            "options": list(action.option_strings),
            "dest": action.dest,
            "nargs": plain(action.nargs),
            "default": plain(action.default),
            "const": plain(action.const),
            "choices": plain(list(action.choices)) if action.choices is not None else None,
            # A positional's `required` attribute differs between Python versions for nargs "*" and "..." (3.13
            # changed it) while parsing is the same: record what parsing does, which nargs decides.
            "required": action.required if action.option_strings else action.nargs not in ("?", "*", "..."),
            "type": getattr(action.type, "__name__", repr(action.type)) if action.type is not None else None,
            "action": type(action).__name__,
        })
    groups = [[a.dest for a in group._group_actions] for group in parser._mutually_exclusive_groups]
    out = {"arguments": arguments}
    if groups:
        out["mutually_exclusive"] = groups
    if subcommands:
        out["subcommands"] = subcommands
    return out


def surface_text():
    return json.dumps(dump_parser(load_pm().build_parser()), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


class CliSurfaceTest(unittest.TestCase):
    def test_parser_tree_matches_golden(self):
        current = surface_text()
        if os.environ.get("PM_UPDATE_GOLDEN") == "1":
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_text(current, encoding="utf-8")
        self.assertTrue(GOLDEN.is_file(), f"{GOLDEN} is missing; write it with PM_UPDATE_GOLDEN=1")
        golden = GOLDEN.read_text(encoding="utf-8")
        if current != golden:
            diff = "".join(difflib.unified_diff(golden.splitlines(True), current.splitlines(True),
                                                "golden/cli_surface.json", "build_parser()", n=4))
            self.fail("pm.py's command line changed (PM_UPDATE_GOLDEN=1 rewrites the golden file when the change "
                      "is meant):\n" + diff)

    def test_golden_lists_every_command(self):
        # The contract names 68 commands; a golden file written from a broken parser would not.
        tree = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(len(tree["subcommands"]), 68)  # +tokens, +remote-sync (P6a), +worker/mailbox-sync/worker-hub/worker-agent (P6b)
        self.assertEqual(len(tree["subcommands"]["project"]["subcommands"]), 24)
        self.assertEqual(sorted(tree["subcommands"]["project"]["subcommands"]["folders"]["subcommands"]),
                         ["add", "ls", "remove", "rename-alias"])
        self.assertEqual(sorted(tree["subcommands"]["turn-journal"]["subcommands"]), ["export"])
        self.assertEqual(sorted(tree["subcommands"]["helper"]["subcommands"]), ["done", "ls", "start", "stop", "wait"])
        self.assertEqual(sorted(tree["subcommands"]["dream"]["subcommands"]), ["apply", "run", "status", "undo"])
        self.assertEqual(sorted(tree["subcommands"]["worker"]["subcommands"]), ["enroll", "join", "list", "revoke"])


if __name__ == "__main__":
    unittest.main()
