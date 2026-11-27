"""The layering of pmlib (docs/design/pm-py-refactor.md, section 2.2 & pm-py-pass-two.md, section 6.2), checked on the source.

- No pmlib module imports `pm` (the launcher, and the forwarding module tests import).
- Imports happen at the top of a module, never inside a function: a deliverer or a seat runs for hours while an
  install replaces the files under it, and a late import would bring a newer module into an older process. The few
  late imports of the standard library are listed in LATE_IMPORTS.
- A module imports only from its own layer or below, and inside layer 3 only along the arrows. A module that is not
  in LAYERS fails the test: a new module gets its place in the table first.
- Outside pmlib, a module imports only the standard library (the four pm_*.py siblings live in pmlib now).
- Five AST ratchet allowlists track modules that still contain legacy patterns during Stages 1-5; cleaned modules
  must be removed from these allowlists and never added back.
- One typist per terminal (pm-message-routing.md §9.2, Phase 3b): text, prompt keys and interrupts reach a terminal
  only through `messaging/transports/` (driven under the endpoint's typist lease); `terminals/` defines the raw
  calls. Anywhere else a raw `hc.send/keys/interrupt` or `tui.agent_prompt/agent_send_keys/pane_run` fails, and the
  pre-mailbox bootstrap primitives stay at their five call sites.
"""
import ast
from pathlib import Path
import sys
import unittest

PMLIB = Path(__file__).resolve().parent.parent / "pmlib"

# Bottom to top. A key is a module or a folder of pmlib, as a path without .py; the longest key that matches wins.
LAYERS = {
    "__init__": 0, "errors": 0, "osutil": 0,
    "config": 1, "context": 1, "home": 1, "store": 1, "gitrepo": 1, "procs": 1, "terminals": 1, "agents": 1,
    "ledger": 2, "project": 2, "project/turn_reducer": 2, "caller": 2, "memory": 2,
    "messaging": 2,
    "events": 3, "workers": 3, "review": 3, "reactions": 3, "landing": 3, "manager": 3, "helpers": 3, "library": 3,
    "homemove": 3, "discord": 3, "reports": 3,
    "cli": 4, "commands": 4, "hooks": 4, "views": 4,
    "compat": 4,  # the forwarding module behind `import pm`; it finds the package's modules at run time
}
# Inside layer 3, who may import whom (besides itself), closed under "and what those may import": workers <- review
# <- reactions <- landing; events <- workers; helpers <- review; manager uses workers and events; helpers and
# dependencies register with the deliverer (events) as watchers instead of being imported by it. Landing sits above
# reactions because the PM's own merge is an `update --status merged` with its reactions.
ARROWS = {
    "workers": {"events"},
    "review": {"workers", "helpers", "events"},
    "reactions": {"review", "workers", "helpers", "events"},
    "landing": {"reactions", "review", "workers", "helpers", "events"},
    "manager": {"workers", "events", "discord"},
    "helpers": {"workers", "events"},
    "reports": {"reactions", "review", "workers", "helpers", "events"},
}
# (module, outermost function, imported module): the few stdlib late imports, all for commands that are not
# long-running processes' code paths at import time (Discord, the browser board).
LATE_IMPORTS = {
    ("discord", "discord_api", "urllib.error"),
    ("discord", "discord_api", "urllib.request"),
    ("views/dash", "cmd_dash", "http.server"),
    ("views/dash", "cmd_dash", "threading"),
    ("views/dash", "cmd_dash", "time"),
    ("views/dash", "cmd_dash", "webbrowser"),
    ("views/dash", "cmd_dash", "socket"),
}

CONTEXT_GLOBALS = frozenset({
    "STATE", "TASKS", "PMS", "PROJECTS", "INBOX", "BOARD", "PANE", "HC_TERMINAL", "WORKSPACE",
})

# AST ratchet allowlists (pm-py-pass-two.md, section 6.2): every module cleaned in Stages 1-6 is removed from these
# sets and must never re-enter. By Stage 6c all five sets are empty.
CONTEXT_GLOBAL_ALLOWLIST = set()

SYS_EXIT_ALLOWLIST = set()

PRINT_ALLOWLIST = set()

NAMESPACE_ALLOWLIST = set()

DIRECT_HOST_ALLOWLIST = set()


# Raw calls that type into a terminal, by the attribute they are called on (`ctx.hc.send`, `self.ctx.tui.agent_prompt`,
# a bare `hc.send` too), and the only places they may appear.
RAW_TERMINAL_CALLS = {"hc": {"send", "keys", "interrupt"}, "tui": {"agent_prompt", "agent_send_keys", "pane_run"}}
RAW_TERMINAL_HOME = ("messaging/transports/", "terminals/")
# Wave 1: the bootstrap primitives that run before a terminal has a mailbox (a shell `exec` into the seat, the codex
# pool's `/fast`, a TUI pane's launch command), and how many calls each module may make. A new one is a design change.
BOOTSTRAP_SITES = {
    ("manager/service", "bootstrap_shell_exec"): 2,
    ("workers/codex_pool", "init_session_flag"): 1,
    ("manager/rotate", "bootstrap_pane_exec"): 1,
    ("workers/reattach", "bootstrap_pane_exec"): 1,
}
BOOTSTRAP_PRIMITIVES = {name for _, name in BOOTSTRAP_SITES}


def _owner_name(node):
    """`hc` for `ctx.hc.send(...)` / `self.ctx.hc.send(...)` / `hc.send(...)`: what the method is called on."""
    owner = node.func.value
    if isinstance(owner, ast.Attribute):
        return owner.attr
    return owner.id if isinstance(owner, ast.Name) else ""


def raw_terminal_calls(tree):
    """`(line, "hc.send")` for every raw terminal call in `tree` (including `hc.call("send", ...)`)."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner, meth = _owner_name(node), node.func.attr
        if meth in RAW_TERMINAL_CALLS.get(owner, ()):
            found.append((node.lineno, f"{owner}.{meth}"))
        elif (owner in RAW_TERMINAL_CALLS and meth == "call" and node.args and isinstance(node.args[0], ast.Constant)
              and node.args[0].value in RAW_TERMINAL_CALLS[owner]):
            found.append((node.lineno, f"{owner}.call({node.args[0].value!r})"))
    return found


def bootstrap_calls(tree):
    """`(line, name)` for every call of a bootstrap primitive in `tree`."""
    return [(node.lineno, node.func.attr) for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in BOOTSTRAP_PRIMITIVES]


def modules():
    """Every pmlib module but test files, as its path without .py (`terminals/hc`)."""
    return sorted(str(p.relative_to(PMLIB).with_suffix("")).replace("\\", "/") for p in PMLIB.rglob("*.py")
                  if "__pycache__" not in p.parts and not p.name.startswith("test_"))


def layer_key(module):
    """The LAYERS key of a module (`events/deliver` -> `events`, `project/turn_reducer` -> `project/turn_reducer`), or None."""
    parts = module.split("/")
    if parts[-1] == "__init__" and len(parts) > 1:
        parts = parts[:-1]
    for n in range(len(parts), 0, -1):
        key = "/".join(parts[:n])
        if key in LAYERS:
            return key
    return None


def parse_module(module):
    path = PMLIB / f"{module}.py"
    return ast.parse(path.read_text(encoding="utf-8"), str(path))


def imports(module):
    """(pmlib target or None, absolute name, line, outermost function or None) for every import in a module. A target
    is a module path like the ones modules() gives; `from . import x` names the module x."""
    package = module.split("/")[:-1]  # the folder the module is in; for an __init__ that is its own package
    found = []

    def visit(node, function):
        for child in ast.iter_child_nodes(node):
            inner = function
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and function is None:
                inner = getattr(child, "name", "<lambda>")
            if isinstance(child, ast.Import):
                for alias in child.names:
                    name = alias.name
                    target = name[len("pmlib."):].replace(".", "/") if name.startswith("pmlib.") else None
                    found.append((target, name, child.lineno, inner))
            elif isinstance(child, ast.ImportFrom):
                if child.level:
                    base = package[:len(package) - (child.level - 1)]
                    stem = base + (child.module.split(".") if child.module else [])
                    if child.module:
                        found.append(("/".join(stem), "pmlib." + ".".join(stem), child.lineno, inner))
                    else:
                        for alias in child.names:
                            found.append(("/".join(stem + [alias.name]), "pmlib." + ".".join(stem + [alias.name]),
                                          child.lineno, inner))
                else:
                    name = child.module
                    target = name[len("pmlib."):].replace(".", "/") if name.startswith("pmlib.") else None
                    if name == "pmlib":
                        target = None  # `from pmlib import x`: each x below
                        for alias in child.names:
                            found.append((alias.name, f"pmlib.{alias.name}", child.lineno, inner))
                        continue
                    found.append((target, name, child.lineno, inner))
            visit(child, inner)

    visit(parse_module(module), None)
    return found


def ratchet_findings():
    """Scan all non-compat pmlib modules for the five legacy patterns tracked by the pass-two AST ratchets."""
    ctx_mods, exit_mods, print_mods, ns_mods, host_mods = set(), set(), set(), set(), set()
    for m in modules():
        if m == "compat":
            continue
        tree = parse_module(m)
        layer = LAYERS[layer_key(m)]
        for node in ast.walk(tree):
            if (m != "context" and isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "context" and node.attr in CONTEXT_GLOBALS):
                ctx_mods.add(m)
            if (layer <= 3 and isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "sys"
                    and node.func.attr == "exit"):
                exit_mods.add(m)
            if (layer <= 3 and isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "print"):
                print_mods.add(m)
            if m != "cli" and isinstance(node, ast.Attribute) and node.attr == "Namespace":
                ns_mods.add(m)
            if not m.startswith("terminals/") and isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in ("hc", "herdr", "hc_rpc"):
                    host_mods.add(m)
                elif isinstance(node.func, ast.Attribute) and node.func.attr in ("hc", "herdr", "hc_rpc"):
                    host_mods.add(m)
    return ctx_mods, exit_mods, print_mods, ns_mods, host_mods


def allowed(source, target):
    """May module `source` import pmlib module `target` under the layer rules?"""
    a, b = layer_key(source), layer_key(target)
    if a is None or b is None:
        return False
    area_a, area_b = a.split("/")[0], b.split("/")[0]
    if area_a == area_b:  # inside one folder (project/turn_state -> project/turn_reducer), never upwards
        return LAYERS[a] >= LAYERS[b]
    if LAYERS[a] == LAYERS[b] == 3:
        return area_b in ARROWS.get(area_a, set())
    return LAYERS[a] >= LAYERS[b]


def is_stdlib(name):
    top = name.split(".")[0]
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return top in names
    return not top.startswith("pm")  # Python 3.9: no list; at least nothing of ours


def _has_future_annotations(tree):
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(alias.name == "annotations" for alias in node.names):
                return True
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        else:
            break
    return False


def _contains_bitor(node):
    if node is None:
        return False
    return any(isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr) for sub in ast.walk(node))


def py39_compat_findings():
    """Find Python 3.10+ constructs in pmlib that break macOS /usr/bin/python3 (3.9.6)."""
    bad = []
    for m in modules():
        tree = parse_module(m)
        future_ann = _has_future_annotations(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                if name == "dataclass":
                    for kw in node.keywords:
                        if kw.arg in ("slots", "kw_only", "match_args"):
                            bad.append((m, node.lineno, f"dataclass({kw.arg}=...) requires Python 3.10+"))
                elif name in ("isinstance", "issubclass") and len(node.args) >= 2 and _contains_bitor(node.args[1]):
                    bad.append((m, node.lineno, f"{name}(..., X | Y) requires Python 3.10+"))
                elif isinstance(fn, ast.Name) and fn.id == "zip":
                    for kw in node.keywords:
                        if kw.arg == "strict":
                            bad.append((m, node.lineno, "zip(..., strict=...) requires Python 3.10+"))
            if not future_ann:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if _contains_bitor(node.returns):
                        bad.append((m, node.lineno, "PEP 604 return annotation without `from __future__ import annotations`"))
                    for arg in (
                        list(node.args.posonlyargs)
                        + list(node.args.args)
                        + list(node.args.kwonlyargs)
                        + ([node.args.vararg] if node.args.vararg else [])
                        + ([node.args.kwarg] if node.args.kwarg else [])
                    ):
                        if _contains_bitor(arg.annotation):
                            bad.append((m, arg.lineno, "PEP 604 arg annotation without `from __future__ import annotations`"))
                elif isinstance(node, ast.AnnAssign) and _contains_bitor(node.annotation):
                    bad.append((m, node.lineno, "PEP 604 variable annotation without `from __future__ import annotations`"))
    return bad


class LayerTest(unittest.TestCase):
    def test_every_module_has_a_layer(self):
        self.assertIn("cli", modules())
        self.assertEqual([m for m in modules() if layer_key(m) is None], [])

    def test_no_module_imports_pm(self):
        bad = [(m, name, line) for m in modules() for target, name, line, _ in imports(m)
               if name == "pm" or name.startswith("pm.")]
        self.assertEqual(bad, [])

    def test_no_import_inside_a_function(self):
        late = {(m, function, name) for m in modules() for _, name, _, function in imports(m) if function}
        self.assertEqual(late - LATE_IMPORTS, set())

    def test_imports_follow_the_layers(self):
        known = set(modules())
        bad = []
        for m in modules():
            for target, name, line, _ in imports(m):
                if target is None:
                    if not is_stdlib(name):
                        bad.append((m, name, line, "not the standard library"))
                elif target not in known and f"{target}/__init__" not in known:
                    bad.append((m, name, line, "no such pmlib module"))
                elif not allowed(m, target if target in known else f"{target}/__init__"):
                    bad.append((m, name, line, "against the layers"))
        self.assertEqual(bad, [])

    def test_ratchet_allowlists_match_source(self):
        ctx_mods, exit_mods, print_mods, ns_mods, host_mods = ratchet_findings()
        self.assertEqual(ctx_mods, CONTEXT_GLOBAL_ALLOWLIST)
        self.assertEqual(exit_mods, SYS_EXIT_ALLOWLIST)
        self.assertEqual(print_mods, PRINT_ALLOWLIST)
        self.assertEqual(ns_mods, NAMESPACE_ALLOWLIST)
        self.assertEqual(host_mods, DIRECT_HOST_ALLOWLIST)

    def test_python39_compatibility(self):
        self.assertEqual(py39_compat_findings(), [])

    def test_only_the_transports_type_into_a_terminal(self):
        bad = [(m, line, call) for m in modules() if not m.startswith(RAW_TERMINAL_HOME)
               for line, call in raw_terminal_calls(parse_module(m))]
        self.assertEqual(bad, [], "type into a terminal through messaging/typist.py or a Transport, under its lease")

    def test_the_bootstrap_primitives_stay_at_their_call_sites(self):
        seen = {}
        for m in modules():
            if m.startswith("terminals/"):
                continue
            for _, name in bootstrap_calls(parse_module(m)):
                seen[(m, name)] = seen.get((m, name), 0) + 1
        self.assertEqual(seen, BOOTSTRAP_SITES)

    def test_the_terminal_gate_catches_what_it_should(self):
        found = raw_terminal_calls(ast.parse(
            "ctx.hc.send(t, x)\nself.ctx.hc.keys(t, 'enter')\nhc.interrupt(t)\nc.tui.agent_prompt(p, x)\n"
            "ctx.tui.agent_send_keys(p, 'esc')\nctx.tui.pane_run(p, c)\nctx.hc.call('send', t, x)\n"
            "ctx.hc.get_raw(t)\nctx.hc.read(t)\nctx.hc.bootstrap_shell_exec(t, c)\ntransport.deliver(ep, it)\n"
            "ctx.hc.call('get', t)\nmailbox.send(x)\n"))
        self.assertEqual([call for _, call in found], [
            "hc.send", "hc.keys", "hc.interrupt", "tui.agent_prompt", "tui.agent_send_keys", "tui.pane_run",
            "hc.call('send')"])
        self.assertEqual([n for _, n in bootstrap_calls(ast.parse("ctx.hc.bootstrap_shell_exec(t, c)\nx.init_session_flag(t, f)\n"))],
                         ["bootstrap_shell_exec", "init_session_flag"])

    def test_the_rules_themselves(self):
        self.assertTrue(allowed("ledger/task", "home"))
        self.assertTrue(allowed("ledger/task", "ledger/plan"))
        self.assertFalse(allowed("home", "ledger/task"))
        self.assertTrue(allowed("events/deliver", "messaging/router"))
        self.assertFalse(allowed("messaging/router", "events/deliver"))
        self.assertTrue(allowed("reactions", "workers/lifecycle"))
        self.assertTrue(allowed("landing", "reactions"))
        self.assertFalse(allowed("reactions", "landing"))
        self.assertFalse(allowed("review/review", "reactions"))
        self.assertFalse(allowed("workers/dispatch", "review/review"))
        self.assertFalse(allowed("events/deliver", "helpers/watch"))
        self.assertTrue(allowed("procs", "terminals/hc"))       # one layer, outside layer 3: allowed
        self.assertTrue(allowed("cli", "workers/dispatch"))
        self.assertTrue(allowed("cli", "views/state"))
        self.assertFalse(allowed("library", "discord"))
        self.assertIsNone(layer_key("nowhere"))
        self.assertEqual(layer_key("terminals/__init__"), "terminals")


if __name__ == "__main__":
    unittest.main()
