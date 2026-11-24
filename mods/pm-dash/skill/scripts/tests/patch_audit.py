#!/usr/bin/env python3
"""Static contract audit for test patches on `pm` / `pmlib` / `pm_*.py` (Pass-2 refactoring safety net).

Principle: anything that cannot be statically proven safe is surfaced in `MANUAL REVIEW` rather than
silently dropped (prefer false-positive review prompts over silent false negatives).

Checks three things purely via Python's `ast` module (no imports of `pmlib`, pure stdlib):
1. Collects all patched `pm` / `pmlib` / `pm_*` attributes in `test_pm*.py` and `tests/*.py`,
   resolving each replacement callable's signature (`lambda`/`def`/`class.__init__`/`partial`/
   `*.append`/factory functions; `MagicMock`/`return_value` as ANY; unresolved callables as
   `UNKNOWN_SIG` manual review).
2. Scans all production call sites in `pmlib/**/*.py`, `pm_*.py`, and `pm.py` (including calls
   forwarded through port classes via `__init__` positional/keyword args, `*.legacy()`, `Context`
   fields, and `register_*` methods), checking that every patched callable signature accepts the
   positional and keyword arguments passed (and flagging `*args`/`**kwargs` unpacking against
   fixed-arity fakes for manual review).
3. Checks reachability and bypass risks: reports missing attributes, dead patches (including
   submodule-specific `target_mod != "pm"` patches with no references on that submodule), and
   `from ... import X as Y` alias imports that bypass `compat.py` as errors; flags same-name
   port/class methods that don't delegate to `X`, direct `_X_impl`/`_DEFAULT_X` calls, and
   legacy-only references as `MANUAL REVIEW`.

Usage:
    python3 mods/pm-dash/skill/scripts/tests/patch_audit.py [--scripts DIR] [--strict] [--no-baseline] [--json]
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
import time
from typing import Any


_LINENO_RE = re.compile(r":\d+")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CallableSig:
    kind: str  # "any" | "callable" | "value" | "unknown"
    posonly: tuple[str, ...] = ()
    pos_or_kw: tuple[str, ...] = ()
    kwonly: tuple[str, ...] = ()
    defaults_count: int = 0
    kw_defaults: frozenset[str] = frozenset()
    has_vararg: bool = False
    has_varkw: bool = False
    raw: str = ""

    @property
    def max_pos(self) -> int | None:
        return None if self.has_vararg else len(self.posonly) + len(self.pos_or_kw)

    @property
    def all_pos_params(self) -> tuple[str, ...]:
        return self.posonly + self.pos_or_kw

    @property
    def required_pos_count(self) -> int:
        return max(0, len(self.all_pos_params) - self.defaults_count)

    @property
    def accepted_kwargs(self) -> frozenset[str]:
        return frozenset(self.pos_or_kw) | frozenset(self.kwonly)

    @property
    def required_kwonly(self) -> frozenset[str]:
        return frozenset(self.kwonly) - self.kw_defaults

    def check_call(self, call: CallSite, *, sig_label: str = "patch sig") -> str | None:
        """Return an error reason if `call` would raise TypeError against this signature, else None."""
        if self.kind != "callable":
            return None

        target_noun = "bridge" if sig_label == "bridge sig" else "patch"

        # 1. Unexpected keyword arguments (ignoring explicitly guarded kwargs)
        effective_kws = [k for k in call.kw_names if k not in call.guarded_kwargs]
        if not self.has_varkw:
            bad_kws = [k for k in effective_kws if k not in self.accepted_kwargs]
            if bad_kws:
                return f"unexpected keyword argument(s): {', '.join(bad_kws)} ({sig_label}: {self.raw})"

        # 2. Too many positional arguments
        if self.max_pos is not None and call.pos_count > self.max_pos:
            return (
                f"too many positional args: call passes {call.pos_count}, "
                f"{target_noun} accepts at most {self.max_pos} ({sig_label}: {self.raw})"
            )

        # 3. Duplicate argument (passed both positionally and by keyword)
        n_posonly = len(self.posonly)
        for idx, pname in enumerate(self.pos_or_kw):
            pos_index = n_posonly + idx
            if pname in effective_kws and pos_index < call.pos_count:
                return f"multiple values for argument '{pname}' ({sig_label}: {self.raw})"

        # 4. Missing required positional arguments (only check when call has no *args / **kwargs)
        if not call.has_star_args and not call.has_double_star:
            req_n = self.required_pos_count
            missing_pos: list[str] = []
            for idx in range(call.pos_count, req_n):
                if idx < n_posonly:
                    missing_pos.append(self.posonly[idx])
                else:
                    pname = self.pos_or_kw[idx - n_posonly]
                    if pname not in call.kw_names:
                        missing_pos.append(pname)
            if missing_pos:
                return f"missing required argument(s): {', '.join(missing_pos)} ({sig_label}: {self.raw})"

        # 5. Missing required keyword-only arguments
        if not call.has_double_star:
            missing_kw = sorted(k for k in self.required_kwonly if k not in call.kw_names)
            if missing_kw:
                return f"missing required keyword-only argument(s): {', '.join(missing_kw)} ({sig_label}: {self.raw})"

        return None


SIG_ANY = CallableSig(kind="any", raw="(*args, **kwargs)")
SIG_VALUE = CallableSig(kind="value", raw="<value>")
SIG_UNKNOWN = CallableSig(kind="unknown", raw="<unknown>")
SIG_SINGLE_POSONLY = CallableSig(kind="callable", posonly=("item",), raw="(item, /)")


def sig_from_arguments(args: ast.arguments, *, drop_first: bool = False) -> CallableSig:
    """Convert an AST `ast.arguments` node to a `CallableSig`."""
    posonly = [a.arg for a in args.posonlyargs]
    pos_or_kw = [a.arg for a in args.args]
    defaults_count = len(args.defaults)
    if drop_first:
        total_pos = len(posonly) + len(pos_or_kw)
        if posonly:
            posonly = posonly[1:]
        elif pos_or_kw:
            pos_or_kw = pos_or_kw[1:]
        if defaults_count > total_pos - 1:
            defaults_count = max(0, total_pos - 1)
    kwonly = [a.arg for a in args.kwonlyargs]
    kw_defaults = frozenset(
        a.arg for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None
    )
    has_vararg = args.vararg is not None
    has_varkw = args.kwarg is not None

    parts: list[str] = []
    all_pos = posonly + pos_or_kw
    first_default = len(all_pos) - defaults_count
    for i, name in enumerate(posonly):
        parts.append(f"{name}=..." if i >= first_default else name)
    if posonly:
        parts.append("/")
    for j, name in enumerate(pos_or_kw):
        idx = len(posonly) + j
        parts.append(f"{name}=..." if idx >= first_default else name)
    if has_vararg:
        parts.append(f"*{args.vararg.arg}")
    elif kwonly:
        parts.append("*")
    for name in kwonly:
        parts.append(f"{name}=..." if name in kw_defaults else name)
    if has_varkw:
        parts.append(f"**{args.kwarg.arg}")
    raw = "(" + ", ".join(parts) + ")"
    return CallableSig(
        kind="callable",
        posonly=tuple(posonly),
        pos_or_kw=tuple(pos_or_kw),
        kwonly=tuple(kwonly),
        defaults_count=defaults_count,
        kw_defaults=kw_defaults,
        has_vararg=has_vararg,
        has_varkw=has_varkw,
        raw=raw,
    )


@dataclass(frozen=True)
class SymbolDef:
    name: str
    module: str
    file: str
    lineno: int
    kind: str  # "func" | "class" | "value"
    sig: CallableSig = SIG_VALUE


@dataclass(frozen=True)
class ClassMethodInfo:
    cls_name: str
    method_name: str
    module: str
    file: str
    lineno: int
    calls_module_sym: bool
    self_attr_calls: frozenset[str]


@dataclass(frozen=True)
class PatchSite:
    file: str
    lineno: int
    target_mod: str  # "pm" or canonical "pmlib.xxx"
    attr: str
    style: str  # "assign" | "patch.object" | "patch" | "patch.multiple"
    sig: CallableSig
    expr: str = ""


@dataclass(frozen=True)
class CallSite:
    file: str
    lineno: int
    module: str
    target_name: str
    pos_count: int
    has_star_args: bool
    kw_names: tuple[str, ...]
    has_double_star: bool
    guarded_kwargs: frozenset[str] = frozenset()
    via: str = "direct"
    expr: str = ""
    target_mod_ref: str = ""


@dataclass(frozen=True)
class RefSite:
    file: str
    lineno: int
    module: str
    target_name: str
    kind: str  # "call" | "read" | "callback" | "legacy_only"
    expr: str = ""
    target_mod_ref: str = ""


@dataclass(frozen=True)
class Finding:
    severity: str  # "error" | "review"
    code: str  # SIG_MISMATCH | MISSING_ATTR | UNREACHABLE_PATCH | ALIAS_IMPORT_BYPASS | BYPASS_RISK | DYNAMIC_CALL_SITE | UNKNOWN_SIG
    attr: str
    message: str
    call_loc: str = ""
    patch_loc: str = ""

    @property
    def fingerprint(self) -> str:
        """Line-number-independent key so refactoring line shifts don't churn baseline entries."""
        call_file = self.call_loc.split(":", 1)[0] if self.call_loc else ""
        patch_file = self.patch_loc.split(":", 1)[0] if self.patch_loc else ""
        norm_msg = _LINENO_RE.sub("", self.message)
        return f"{self.code}|{self.attr}|{call_file}|{patch_file}|{norm_msg}"


@dataclass
class AuditReport:
    scripts_dir: str
    prod_files: int
    test_files: int
    patch_sites: int
    patched_attrs: int
    call_sites: int
    elapsed_ms: float
    errors: list[Finding] = field(default_factory=list)
    baselined: list[Finding] = field(default_factory=list)
    reviews: list[Finding] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _short_unparse(node: ast.AST, limit: int = 80) -> str:
    try:
        text = ast.unparse(node).replace("\n", " ")
    except Exception:
        return "<expr>"
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _resolve_relative_module(cur_mod: str, is_pkg: bool, level: int, module: str | None) -> str:
    if level == 0:
        return module or ""
    parts = cur_mod.split(".")
    base = parts if is_pkg else parts[:-1]
    up = level - 1
    if up > 0:
        base = base[:-up] if up <= len(base) else []
    if module:
        return ".".join(base + module.split("."))
    return ".".join(base)


def _attr_chain(node: ast.AST) -> list[str] | None:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        parts.reverse()
        return parts
    return None


def _is_mock_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        chain = _attr_chain(node.func)
        if chain and chain[-1] in ("MagicMock", "Mock", "NonCallableMagicMock", "NonCallableMock", "AsyncMock"):
            return True
    chain = _attr_chain(node)
    if chain and chain[-1] in ("MagicMock", "Mock", "DEFAULT"):
        return True
    return False


def _is_non_callable_literal(node: ast.AST) -> bool:
    if isinstance(node, (ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.JoinedStr)):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add, ast.Sub, ast.Mult)):
        return True
    if isinstance(node, ast.Call):
        chain = _attr_chain(node.func)
        if chain and chain[-1] in (
            "Path", "PurePath", "PurePosixPath", "PureWindowsPath",
            "dict", "list", "set", "frozenset", "tuple", "str", "int", "float", "bool",
            "Namespace", "SimpleNamespace", "StringIO", "BytesIO",
            "OSError", "RuntimeError", "ValueError", "KeyError", "TypeError", "Exception", "AssertionError",
            "TimeoutExpired", "CalledProcessError", "iter", "object",
        ):
            return True
    return False


def _class_init_sig(cls_node: ast.ClassDef) -> CallableSig:
    for item in cls_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
            return sig_from_arguments(item.args, drop_first=True)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__new__":
            return sig_from_arguments(item.args, drop_first=True)
    if cls_node.bases:
        return SIG_ANY
    return CallableSig(kind="callable", raw="()")


def _infer_factory_return_sig(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> CallableSig | None:
    """If a helper function/method returns a nested `def` or `lambda` (or MagicMock), return its CallableSig."""
    inner_defs: dict[str, CallableSig] = {}
    for stmt in fn_node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inner_defs[stmt.name] = sig_from_arguments(stmt.args)
        elif isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and isinstance(stmt.value, ast.Lambda):
                    inner_defs[tgt.id] = sig_from_arguments(stmt.value.args)

    returned: list[CallableSig] = []
    for node in ast.walk(fn_node):
        if node is not fn_node and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            val = node.value
            if isinstance(val, ast.Lambda):
                returned.append(sig_from_arguments(val.args))
            elif isinstance(val, ast.Name) and val.id in inner_defs:
                returned.append(inner_defs[val.id])
            elif _is_mock_expr(val):
                returned.append(SIG_ANY)
            else:
                return None
    if not returned:
        return None
    first = returned[0]
    if all(r == first for r in returned):
        return first
    return None


def _analyze_class_method(
    cls_name: str,
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    minfo: ModuleInfo,
) -> ClassMethodInfo:
    """Inspect a class method body to see if it directly invokes module-level `method.name` or `self._*`."""
    calls_mod_sym = False
    self_attrs: set[str] = set()
    mname = method.name
    param_names = {
        a.arg for a in method.args.posonlyargs + method.args.args + method.args.kwonlyargs
    }
    if method.args.vararg:
        param_names.add(method.args.vararg.arg)
    if method.args.kwarg:
        param_names.add(method.args.kwarg.arg)
    has_local_mod_sym = mname in minfo.defs or mname in minfo.sym_imports

    for node in ast.walk(method):
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == mname
                and mname not in param_names
                and has_local_mod_sym
            ):
                calls_mod_sym = True
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
                    self_attrs.add(node.func.attr)
                elif node.func.attr == mname:
                    chain = _attr_chain(node.func)
                    if chain and len(chain) >= 2 and ".".join(chain[:-1]) in minfo.mod_imports:
                        calls_mod_sym = True
        elif isinstance(node, ast.Attribute) and node.attr == mname:
            chain = _attr_chain(node)
            if chain and len(chain) >= 2 and ".".join(chain[:-1]) in minfo.mod_imports:
                calls_mod_sym = True
    return ClassMethodInfo(
        cls_name=cls_name,
        method_name=mname,
        module=minfo.name,
        file=minfo.relpath,
        lineno=method.lineno,
        calls_module_sym=calls_mod_sym,
        self_attr_calls=frozenset(self_attrs),
    )


# ---------------------------------------------------------------------------
# Stage 1: Production Index
# ---------------------------------------------------------------------------

@dataclass
class ModuleInfo:
    name: str
    path: Path
    relpath: str
    is_pkg: bool
    tree: ast.Module
    defs: dict[str, SymbolDef] = field(default_factory=dict)
    mod_imports: dict[str, str] = field(default_factory=dict)       # local_name -> canonical pmlib.* module
    sym_imports: dict[str, tuple[str, str]] = field(default_factory=dict)  # local_name -> (canonical_mod, orig_name)
    sym_import_lines: dict[str, int] = field(default_factory=dict)
    default_snapshots: dict[str, str] = field(default_factory=dict)  # _DEFAULT_X -> X
    all_names: set[str] = field(default_factory=set)


@dataclass
class ProdIndex:
    scripts_dir: Path
    modules: dict[str, ModuleInfo] = field(default_factory=dict)  # canonical_name -> ModuleInfo
    shims: dict[str, str] = field(default_factory=dict)           # "pm_events" -> "pmlib.terminals.events"
    owners: dict[str, list[SymbolDef]] = field(default_factory=lambda: defaultdict(list))
    holders: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # sym -> set of canonical mod names
    class_methods: dict[str, list[ClassMethodInfo]] = field(default_factory=lambda: defaultdict(list))
    alias_imports: dict[str, list[tuple[str, str, str, int]]] = field(default_factory=lambda: defaultdict(list))

    def resolve_module(self, name: str) -> str:
        return self.shims.get(name, name)

    def has_pm_attr(self, attr: str) -> bool:
        return attr in self.owners or attr in self.holders

    def has_mod_attr(self, mod_name: str, attr: str) -> bool:
        canon = self.resolve_module(mod_name)
        mod = self.modules.get(canon)
        if mod is None:
            return False
        return attr in mod.defs or attr in mod.sym_imports or attr in mod.mod_imports

    def symbol_kind(self, attr: str) -> str:
        defs = self.owners.get(attr)
        if not defs:
            return "unknown"
        return defs[0].kind


def _detect_shim(tree: ast.Module) -> str | None:
    """Detect `_sys.modules[__name__] = _impl` shim files like `pm_events.py`."""
    imports: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                imports[alias.asname or alias.name] = alias.name
        elif isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if (
                    isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Attribute)
                    and tgt.value.attr == "modules"
                    and isinstance(tgt.slice, ast.Name)
                    and tgt.slice.id == "__name__"
                    and isinstance(stmt.value, ast.Name)
                    and stmt.value.id in imports
                ):
                    return imports[stmt.value.id]
    return None


def build_prod_index(scripts_dir: Path) -> ProdIndex:
    idx = ProdIndex(scripts_dir=scripts_dir)
    pkg_dir = scripts_dir / "pmlib"

    files_to_parse: list[tuple[str, Path, bool]] = []
    pm_py = scripts_dir / "pm.py"
    if pm_py.is_file():
        files_to_parse.append(("pm", pm_py, False))
    for p in sorted(scripts_dir.glob("pm_*.py")):
        files_to_parse.append((p.stem, p, False))
    if pkg_dir.is_dir():
        for p in sorted(pkg_dir.rglob("*.py")):
            rel_parts = p.relative_to(pkg_dir).parts
            if "__pycache__" in rel_parts:
                continue
            if p.name == "compat.py" or p.name.startswith("test_"):
                continue
            is_pkg = p.name == "__init__.py"
            if is_pkg:
                mod_name = ".".join(("pmlib",) + rel_parts[:-1])
            else:
                mod_name = ".".join(("pmlib",) + rel_parts[:-1] + (p.stem,))
            files_to_parse.append((mod_name, p, is_pkg))

    for mod_name, path, is_pkg in files_to_parse:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        if mod_name.startswith("pm_"):
            target = _detect_shim(tree)
            if target:
                idx.shims[mod_name] = target
                continue

        minfo = ModuleInfo(
            name=mod_name,
            path=path,
            relpath=_rel(path, scripts_dir),
            is_pkg=is_pkg,
            tree=tree,
        )
        idx.modules[mod_name] = minfo

        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sdef = SymbolDef(
                    name=stmt.name,
                    module=mod_name,
                    file=minfo.relpath,
                    lineno=stmt.lineno,
                    kind="func",
                    sig=sig_from_arguments(stmt.args),
                )
                minfo.defs[stmt.name] = sdef
            elif isinstance(stmt, ast.ClassDef):
                sdef = SymbolDef(
                    name=stmt.name,
                    module=mod_name,
                    file=minfo.relpath,
                    lineno=stmt.lineno,
                    kind="class",
                    sig=_class_init_sig(stmt),
                )
                minfo.defs[stmt.name] = sdef
            elif isinstance(stmt, ast.Assign):
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name):
                        name = tgt.id
                        if name == "__all__" and isinstance(stmt.value, (ast.List, ast.Tuple)):
                            for elt in stmt.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    minfo.all_names.add(elt.value)
                            continue
                        if isinstance(stmt.value, ast.Name) and name.startswith("_DEFAULT_"):
                            minfo.default_snapshots[name] = stmt.value.id
                        if isinstance(stmt.value, ast.Lambda):
                            sdef = SymbolDef(
                                name=name, module=mod_name, file=minfo.relpath,
                                lineno=stmt.lineno, kind="func",
                                sig=sig_from_arguments(stmt.value.args),
                            )
                        else:
                            sdef = SymbolDef(
                                name=name, module=mod_name, file=minfo.relpath,
                                lineno=stmt.lineno, kind="value",
                            )
                        minfo.defs[name] = sdef
                    elif isinstance(tgt, (ast.Tuple, ast.List)):
                        for elt in tgt.elts:
                            if isinstance(elt, ast.Name):
                                minfo.defs[elt.id] = SymbolDef(
                                    name=elt.id, module=mod_name, file=minfo.relpath,
                                    lineno=stmt.lineno, kind="value",
                                )
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                name = stmt.target.id
                minfo.defs[name] = SymbolDef(
                    name=name, module=mod_name, file=minfo.relpath,
                    lineno=stmt.lineno, kind="value",
                )
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    target = idx.resolve_module(alias.name)
                    if target == "pmlib" or target.startswith("pmlib."):
                        local = alias.asname or alias.name.split(".")[0]
                        if alias.asname:
                            minfo.mod_imports[local] = target
                        else:
                            minfo.mod_imports[local] = alias.name.split(".")[0]
                            minfo.mod_imports[alias.name] = target
            elif isinstance(stmt, ast.ImportFrom):
                base = _resolve_relative_module(mod_name, is_pkg, stmt.level, stmt.module)
                base = idx.resolve_module(base)
                if base == "pmlib" or base.startswith("pmlib."):
                    for alias in stmt.names:
                        if alias.name == "*":
                            continue
                        local = alias.asname or alias.name
                        minfo.sym_imports[local] = (base, alias.name)
                        minfo.sym_import_lines[local] = stmt.lineno

    # Split sym_imports into mod_imports vs sym_imports
    for minfo in idx.modules.values():
        to_move: list[tuple[str, str]] = []
        for local, (base, orig) in list(minfo.sym_imports.items()):
            base = idx.resolve_module(base)
            candidate_mod = f"{base}.{orig}"
            if candidate_mod in idx.modules:
                to_move.append((local, candidate_mod))
            else:
                minfo.sym_imports[local] = (base, orig)
        for local, canon_mod in to_move:
            del minfo.sym_imports[local]
            minfo.sym_import_lines.pop(local, None)
            minfo.mod_imports[local] = canon_mod

    # Analyze class methods after `mod_imports` / `sym_imports` are finalized so module-qualified
    # calls (`sessions_mod.claude_dir`) are distinguished from instance attributes (`self._ctx.claude_dir`).
    for minfo in idx.modules.values():
        for stmt in minfo.tree.body:
            if isinstance(stmt, ast.ClassDef):
                for item in stmt.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not (item.name.startswith("__") and item.name.endswith("__")):
                            idx.class_methods[item.name].append(
                                _analyze_class_method(stmt.name, item, minfo)
                            )

    # Build compat owners, holders, and aliased-symbol imports (`from ... import X as Y`)
    for mod_name, minfo in idx.modules.items():
        if not mod_name.startswith("pmlib."):
            continue
        for sym, sdef in minfo.defs.items():
            if sym.startswith("__") and sym.endswith("__"):
                continue
            idx.owners[sym].append(sdef)
            idx.holders[sym].add(mod_name)
        for local, (_base, orig) in minfo.sym_imports.items():
            if local.startswith("__") and local.endswith("__"):
                continue
            if local == orig:
                idx.holders[local].add(mod_name)
            else:
                # `from .mod import X as Y` -> compat.py cannot update `Y` when `pm.X` is patched!
                lineno = minfo.sym_import_lines.get(local, 1)
                idx.alias_imports[orig].append((mod_name, minfo.relpath, local, lineno))

    return idx


# ---------------------------------------------------------------------------
# Stage 2: Test Patch Collector
# ---------------------------------------------------------------------------

class _Scope:
    def __init__(self, parent: _Scope | None = None, is_class: bool = False) -> None:
        self.parent = parent
        self.is_class = is_class
        self.callables: dict[str, CallableSig] = {}
        self.factory_returns: dict[str, CallableSig] = {}
        self.saved_origs: set[str] = set()
        self.mod_aliases: dict[str, str] = {}

    def lookup_callable(self, name: str) -> CallableSig | None:
        cur: _Scope | None = self
        while cur is not None:
            if name in cur.callables:
                return cur.callables[name]
            cur = cur.parent
        return None

    def lookup_factory_return(self, name: str) -> CallableSig | None:
        cur: _Scope | None = self
        while cur is not None:
            if name in cur.factory_returns:
                return cur.factory_returns[name]
            cur = cur.parent
        return None

    def is_saved_orig(self, name: str) -> bool:
        cur: _Scope | None = self
        while cur is not None:
            if name in cur.saved_origs:
                return True
            cur = cur.parent
        return False

    def lookup_mod(self, name: str) -> str | None:
        cur: _Scope | None = self
        while cur is not None:
            if name in cur.mod_aliases:
                return cur.mod_aliases[name]
            cur = cur.parent
        return None


class _TestPatchVisitor(ast.NodeVisitor):
    def __init__(self, relpath: str, prod: ProdIndex) -> None:
        self.relpath = relpath
        self.prod = prod
        self.patches: list[PatchSite] = []
        self.scope = _Scope()
        self.class_methods_stack: list[dict[str, CallableSig]] = []
        self.class_factories_stack: list[dict[str, CallableSig]] = []

    def _push(self, is_class: bool = False) -> _Scope:
        self.scope = _Scope(parent=self.scope, is_class=is_class)
        return self.scope

    def _pop(self) -> None:
        assert self.scope.parent is not None
        self.scope = self.scope.parent

    def _predeclare_block(self, stmts: list[ast.stmt], *, is_class: bool = False) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                is_static = any(
                    isinstance(d, ast.Name) and d.id == "staticmethod" for d in stmt.decorator_list
                )
                sig = sig_from_arguments(stmt.args, drop_first=(is_class and not is_static))
                self.scope.callables[stmt.name] = sig
                if is_class and self.class_methods_stack:
                    self.class_methods_stack[-1][stmt.name] = sig
                ret_sig = _infer_factory_return_sig(stmt)
                if ret_sig is not None:
                    self.scope.factory_returns[stmt.name] = ret_sig
                    if is_class and self.class_factories_stack:
                        self.class_factories_stack[-1][stmt.name] = ret_sig
            elif isinstance(stmt, ast.ClassDef):
                self.scope.callables[stmt.name] = _class_init_sig(stmt)

    def visit_Module(self, node: ast.Module) -> None:
        self._predeclare_block(node.body)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_methods_stack.append({})
        self.class_factories_stack.append({})
        self._push(is_class=True)
        self._predeclare_block(node.body, is_class=True)
        for stmt in node.body:
            self.visit(stmt)
        self._pop()
        self.class_factories_stack.pop()
        self.class_methods_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._push()
        self._predeclare_block(node.body)
        for stmt in node.body:
            self.visit(stmt)
        self._pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            canon = self.prod.resolve_module(alias.name)
            if canon == "pm" or canon == "pmlib" or canon.startswith("pmlib."):
                local = alias.asname or alias.name.split(".")[0]
                self.scope.mod_aliases[local] = canon if alias.asname else alias.name.split(".")[0]
                if not alias.asname:
                    self.scope.mod_aliases[alias.name] = canon

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = self.prod.resolve_module(node.module or "")
        if mod == "pmlib" or mod.startswith("pmlib."):
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                sub = f"{mod}.{alias.name}"
                if sub in self.prod.modules:
                    self.scope.mod_aliases[local] = sub

    def _resolve_target(self, expr: ast.AST) -> tuple[str, str] | None:
        """Resolve an expression like `pm` or `pm.foo` or `deliverer` to `(target_mod, prefix_attr)`."""
        chain = _attr_chain(expr)
        if not chain:
            return None
        for k in range(len(chain), 0, -1):
            prefix = ".".join(chain[:k])
            mod = self.scope.lookup_mod(prefix)
            if mod is not None:
                rest = chain[k:]
                if not rest:
                    return (mod, "")
                if len(rest) == 1:
                    if mod == "pm" and not self.prod.has_pm_attr(rest[0]):
                        return None
                    if mod != "pm" and not self.prod.has_mod_attr(mod, rest[0]):
                        return None
                    return (mod, rest[0])
                return None
        return None

    def _resolve_replacement_sig(self, expr: ast.AST) -> CallableSig:
        if isinstance(expr, ast.Lambda):
            return sig_from_arguments(expr.args)
        if _is_mock_expr(expr):
            return SIG_ANY
        if _is_non_callable_literal(expr):
            return SIG_VALUE
        if isinstance(expr, ast.Name):
            if self.scope.is_saved_orig(expr.id):
                return SIG_VALUE
            found = self.scope.lookup_callable(expr.id)
            if found is not None:
                return found
            return SIG_UNKNOWN
        if isinstance(expr, ast.Attribute):
            # Built-in 1-arg container mutators like `calls.append` / `seen.add`
            if expr.attr in ("append", "add"):
                return SIG_SINGLE_POSONLY
            # self.helper_method
            if isinstance(expr.value, ast.Name) and expr.value.id == "self" and self.class_methods_stack:
                for cls_methods in reversed(self.class_methods_stack):
                    if expr.attr in cls_methods:
                        return cls_methods[expr.attr]
            # Restoring from `pm.X` directly
            if isinstance(expr.value, ast.Name) and self.scope.lookup_mod(expr.value.id) is not None:
                return SIG_VALUE
        if isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Name):
            if self.scope.is_saved_orig(expr.value.id):
                return SIG_VALUE
        if isinstance(expr, ast.Call):
            chain = _attr_chain(expr.func)
            # functools.partial(fn, ...)
            if chain and chain[-1] == "partial" and expr.args:
                inner = self._resolve_replacement_sig(expr.args[0])
                if inner.kind == "callable":
                    bound_pos = len(expr.args) - 1
                    bound_kws = {kw.arg for kw in expr.keywords if kw.arg}
                    return _apply_partial(inner, bound_pos, bound_kws)
                return inner
            # Factory function call: `make_fake(...)` or `self.fake_hc(...)`
            if isinstance(expr.func, ast.Name):
                ret_sig = self.scope.lookup_factory_return(expr.func.id)
                if ret_sig is not None:
                    return ret_sig
            elif (
                isinstance(expr.func, ast.Attribute)
                and isinstance(expr.func.value, ast.Name)
                and expr.func.value.id == "self"
                and self.class_factories_stack
            ):
                for cls_facts in reversed(self.class_factories_stack):
                    if expr.func.attr in cls_facts:
                        return cls_facts[expr.func.attr]
        return SIG_UNKNOWN

    def _is_restore_expr(self, expr: ast.AST) -> bool:
        if isinstance(expr, ast.Name) and self.scope.is_saved_orig(expr.id):
            return True
        if isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Name):
            if self.scope.is_saved_orig(expr.value.id):
                return True
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            if expr.value.id == "self" and expr.attr.startswith(("_saved", "saved", "_orig", "orig")):
                return True
            if self.scope.lookup_mod(expr.value.id) is not None:
                return True
        return False

    def _expr_reads_pm(self, expr: ast.AST) -> bool:
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            if self.scope.lookup_mod(expr.value.id) is not None:
                return True
        if isinstance(expr, (ast.Tuple, ast.List)):
            return any(self._expr_reads_pm(e) for e in expr.elts)
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "getattr":
            if expr.args and isinstance(expr.args[0], ast.Name) and self.scope.lookup_mod(expr.args[0].id):
                return True
        return False

    def visit_Assign(self, node: ast.Assign) -> None:
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                if self._expr_reads_pm(node.value):
                    self.scope.saved_origs.add(tgt.id)
                else:
                    resolved_sig = self._resolve_replacement_sig(node.value)
                    if resolved_sig.kind in ("callable", "any"):
                        self.scope.callables[tgt.id] = resolved_sig
            elif isinstance(tgt, (ast.Tuple, ast.List)) and isinstance(node.value, (ast.Tuple, ast.List)):
                if len(tgt.elts) == len(node.value.elts):
                    for lt, rv in zip(tgt.elts, node.value.elts):
                        if isinstance(lt, ast.Name):
                            if self._expr_reads_pm(rv):
                                self.scope.saved_origs.add(lt.id)
                            else:
                                resolved_sig = self._resolve_replacement_sig(rv)
                                if resolved_sig.kind in ("callable", "any"):
                                    self.scope.callables[lt.id] = resolved_sig

        for tgt in node.targets:
            if isinstance(tgt, ast.Attribute):
                self._handle_attr_assign(tgt, node.value, node.lineno)
            elif isinstance(tgt, (ast.Tuple, ast.List)):
                if isinstance(node.value, (ast.Tuple, ast.List)) and len(tgt.elts) == len(node.value.elts):
                    for lt, rv in zip(tgt.elts, node.value.elts):
                        if isinstance(lt, ast.Attribute):
                            self._handle_attr_assign(lt, rv, node.lineno)
                else:
                    for lt in tgt.elts:
                        if isinstance(lt, ast.Attribute):
                            self._handle_attr_assign(lt, node.value, node.lineno)

        self.generic_visit(node)

    def _handle_attr_assign(self, tgt: ast.Attribute, value: ast.AST, lineno: int) -> None:
        if self._is_restore_expr(value):
            return
        resolved = self._resolve_target(tgt.value)
        if resolved is None:
            return
        mod, prefix = resolved
        if prefix:
            return
        sig = self._resolve_replacement_sig(value)
        self.patches.append(
            PatchSite(
                file=self.relpath,
                lineno=lineno,
                target_mod=mod,
                attr=tgt.attr,
                style="assign",
                sig=sig,
                expr=_short_unparse(value),
            )
        )

    def visit_Call(self, node: ast.Call) -> None:
        chain = _attr_chain(node.func)
        if chain:
            if len(chain) >= 2 and chain[-2:] == ["patch", "object"]:
                self._handle_patch_object(node)
            elif len(chain) >= 2 and chain[-2:] == ["patch", "multiple"]:
                self._handle_patch_multiple(node)
            elif chain == ["mock", "patch"] or chain == ["patch"] or chain == ["unittest", "mock", "patch"]:
                self._handle_patch_str(node)
        self.generic_visit(node)

    def _extract_mock_patch_sig(self, new_expr: ast.AST | None, keywords: list[ast.keyword]) -> tuple[CallableSig, str]:
        kw_map = {kw.arg: kw.value for kw in keywords if kw.arg}
        if new_expr is not None:
            return self._resolve_replacement_sig(new_expr), _short_unparse(new_expr)
        if "new" in kw_map:
            return self._resolve_replacement_sig(kw_map["new"]), _short_unparse(kw_map["new"])
        if "autospec" in kw_map:
            return SIG_ANY, "autospec"
        if "side_effect" in kw_map:
            se = kw_map["side_effect"]
            if _is_non_callable_literal(se):
                return SIG_ANY, f"side_effect={_short_unparse(se)}"
            sig = self._resolve_replacement_sig(se)
            if sig.kind == "value":
                return SIG_ANY, f"side_effect={_short_unparse(se)}"
            return sig, f"side_effect={_short_unparse(se)}"
        return SIG_ANY, "MagicMock"

    def _handle_patch_object(self, node: ast.Call) -> None:
        if len(node.args) < 2:
            return
        attr_node = node.args[1]
        if not (isinstance(attr_node, ast.Constant) and isinstance(attr_node.value, str)):
            return
        resolved = self._resolve_target(node.args[0])
        if resolved is None:
            return
        mod, prefix = resolved
        if prefix:
            return
        new_expr = node.args[2] if len(node.args) >= 3 else None
        sig, expr = self._extract_mock_patch_sig(new_expr, node.keywords)
        self.patches.append(
            PatchSite(
                file=self.relpath,
                lineno=node.lineno,
                target_mod=mod,
                attr=attr_node.value,
                style="patch.object",
                sig=sig,
                expr=expr,
            )
        )

    def _handle_patch_multiple(self, node: ast.Call) -> None:
        if not node.args:
            return
        resolved = self._resolve_target(node.args[0])
        if resolved is None:
            return
        mod, prefix = resolved
        if prefix:
            return
        skip_kws = {"spec", "create", "spec_set", "autospec", "new_callable"}
        for kw in node.keywords:
            if not kw.arg or kw.arg in skip_kws:
                continue
            sig = self._resolve_replacement_sig(kw.value)
            self.patches.append(
                PatchSite(
                    file=self.relpath,
                    lineno=node.lineno,
                    target_mod=mod,
                    attr=kw.arg,
                    style="patch.multiple",
                    sig=sig,
                    expr=_short_unparse(kw.value),
                )
            )

    def _handle_patch_str(self, node: ast.Call) -> None:
        if not node.args:
            return
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            return
        target = first.value
        if not target.startswith(("pm.", "pmlib.", "pm_")):
            return
        mod_part, _, attr = target.rpartition(".")
        if not mod_part or not attr:
            return
        canon = self.prod.resolve_module(mod_part)
        if canon != "pm" and canon not in self.prod.modules:
            return
        new_expr = node.args[1] if len(node.args) >= 2 else None
        sig, expr = self._extract_mock_patch_sig(new_expr, node.keywords)
        self.patches.append(
            PatchSite(
                file=self.relpath,
                lineno=node.lineno,
                target_mod=canon,
                attr=attr,
                style="patch",
                sig=sig,
                expr=expr,
            )
        )


def _apply_partial(sig: CallableSig, bound_pos: int, bound_kws: set[str]) -> CallableSig:
    posonly = sig.posonly
    pos_or_kw = sig.pos_or_kw
    rem_posonly = posonly[bound_pos:] if bound_pos < len(posonly) else ()
    rem_after = max(0, bound_pos - len(posonly))
    rem_pos_or_kw = tuple(p for p in pos_or_kw[rem_after:] if p not in bound_kws)
    kwonly = tuple(k for k in sig.kwonly if k not in bound_kws)
    kw_defaults = sig.kw_defaults | (frozenset(sig.kwonly) & bound_kws)
    return CallableSig(
        kind="callable",
        posonly=rem_posonly,
        pos_or_kw=rem_pos_or_kw,
        kwonly=kwonly,
        defaults_count=min(sig.defaults_count, len(rem_posonly) + len(rem_pos_or_kw)),
        kw_defaults=kw_defaults,
        has_vararg=sig.has_vararg,
        has_varkw=sig.has_varkw,
        raw=f"partial({sig.raw})",
    )


def collect_patches(scripts_dir: Path, prod: ProdIndex) -> tuple[list[PatchSite], int]:
    test_files: list[Path] = sorted(scripts_dir.glob("test_pm*.py"))
    tests_dir = scripts_dir / "tests"
    if tests_dir.is_dir():
        for p in sorted(tests_dir.glob("*.py")):
            if p.name in ("patch_audit.py", "test_patch_audit.py"):
                continue
            test_files.append(p)

    all_patches: list[PatchSite] = []
    for path in test_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        visitor = _TestPatchVisitor(_rel(path, scripts_dir), prod)
        visitor.visit(tree)
        all_patches.extend(visitor.patches)
    return all_patches, len(test_files)


# ---------------------------------------------------------------------------
# Stage 3: Production Call-Site, Port-Forwarding, and Reference Collector
# ---------------------------------------------------------------------------

def _call_shape(node: ast.Call) -> tuple[int, bool, tuple[str, ...], bool]:
    pos_count = 0
    has_star = False
    for a in node.args:
        if isinstance(a, ast.Starred):
            has_star = True
        else:
            pos_count += 1
    kw_names: list[str] = []
    has_dstar = False
    for kw in node.keywords:
        if kw.arg is None:
            has_dstar = True
        else:
            kw_names.append(kw.arg)
    return pos_count, has_star, tuple(kw_names), has_dstar


@dataclass(frozen=True)
class _ForwardWire:
    target_sym: str
    target_mod_ref: str
    kind: str  # "direct" | "transparent" | "varargs" | "kwargs" | "fixed"
    wire_loc: str
    bridge_sig: CallableSig | None = None
    forwards_var: bool = False
    forwards_kw: bool = False
    body_fixed_pos: int = 0
    body_has_extra_star: bool = False
    body_fixed_kws: tuple[str, ...] = ()
    body_has_extra_dstar: bool = False


def _resolve_sym_in_module(expr: ast.AST, minfo: ModuleInfo) -> tuple[str, str] | None:
    """Resolve `X` or `mod.X` in `minfo` to `(symbol_name, target_mod_ref)`."""
    if isinstance(expr, ast.Name):
        if expr.id in minfo.defs or expr.id in minfo.sym_imports:
            return expr.id, minfo.name
    if isinstance(expr, ast.Attribute):
        chain = _attr_chain(expr)
        if chain and len(chain) >= 2:
            prefix = ".".join(chain[:-1])
            if prefix in minfo.mod_imports:
                return chain[-1], minfo.mod_imports[prefix]
    return None


def _extract_forwarder(expr: ast.AST, minfo: ModuleInfo, wire_loc: str) -> _ForwardWire | None:
    """Recognize direct refs AND any forwarding lambda (transparent `*a, **kw`, `*a`-only, `**kw`-only, or fixed-arg)."""
    # 1. Direct reference: `rename_tab` or `pmlib.config.config`
    direct = _resolve_sym_in_module(expr, minfo)
    if direct is not None:
        return _ForwardWire(target_sym=direct[0], target_mod_ref=direct[1], kind="direct", wire_loc=wire_loc)

    # 2. Lambda wrapping a call to `X(...)` or `mod.X(...)`
    if isinstance(expr, ast.Lambda) and isinstance(expr.body, ast.Call):
        body_call = expr.body
        target = _resolve_sym_in_module(body_call.func, minfo)
        if target is None:
            return None
        sym, mod_ref = target
        bridge_sig = sig_from_arguments(expr.args)
        vararg_name = expr.args.vararg.arg if expr.args.vararg is not None else None
        kwarg_name = expr.args.kwarg.arg if expr.args.kwarg is not None else None

        body_fixed_pos = 0
        forwards_var = False
        body_has_extra_star = False
        for a in body_call.args:
            if isinstance(a, ast.Starred):
                if vararg_name is not None and isinstance(a.value, ast.Name) and a.value.id == vararg_name:
                    forwards_var = True
                else:
                    body_has_extra_star = True
            else:
                body_fixed_pos += 1

        body_fixed_kws: list[str] = []
        forwards_kw = False
        body_has_extra_dstar = False
        for kw in body_call.keywords:
            if kw.arg is None:
                if kwarg_name is not None and isinstance(kw.value, ast.Name) and kw.value.id == kwarg_name:
                    forwards_kw = True
                else:
                    body_has_extra_dstar = True
            else:
                body_fixed_kws.append(kw.arg)

        if forwards_var and forwards_kw:
            kind = "transparent"
        elif forwards_var:
            kind = "varargs"
        elif forwards_kw:
            kind = "kwargs"
        else:
            kind = "fixed"

        return _ForwardWire(
            target_sym=sym,
            target_mod_ref=mod_ref,
            kind=kind,
            wire_loc=wire_loc,
            bridge_sig=bridge_sig,
            forwards_var=forwards_var,
            forwards_kw=forwards_kw,
            body_fixed_pos=body_fixed_pos,
            body_has_extra_star=body_has_extra_star,
            body_fixed_kws=tuple(body_fixed_kws),
            body_has_extra_dstar=body_has_extra_dstar,
        )

    return None


@dataclass
class _ClassWiringSpec:
    pos_params: list[str] = field(default_factory=list)
    param_to_attr: dict[str, str] = field(default_factory=dict)
    method_specs: dict[str, tuple[list[str], dict[str, str]]] = field(default_factory=dict)


@dataclass
class _PortForwarding:
    """Maps `(class_name, self_attr)` -> list of `_ForwardWire` for callbacks wired via `__init__`,
    `Context` dataclass fields, `*.legacy()`, or `register_*` methods."""
    class_specs: dict[str, _ClassWiringSpec] = field(default_factory=lambda: defaultdict(_ClassWiringSpec))
    wired: dict[tuple[str, str], list[_ForwardWire]] = field(default_factory=lambda: defaultdict(list))
    context_fields: dict[str, list[_ForwardWire]] = field(default_factory=lambda: defaultdict(list))


def _collect_port_forwarding(prod: ProdIndex, patched_names: set[str]) -> _PortForwarding:
    pf = _PortForwarding()

    # Pass 1: Collect `__init__`, dataclass fields, and setter/register_* methods for every class
    for minfo in prod.modules.values():
        for stmt in minfo.tree.body:
            if not isinstance(stmt, ast.ClassDef):
                continue
            spec = pf.class_specs[stmt.name]
            has_init = False
            dataclass_fields: list[str] = []

            for item in stmt.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    dataclass_fields.append(item.target.id)
                elif isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    has_init = True
                    pos_params = [a.arg for a in item.args.posonlyargs + item.args.args[1:]]
                    all_params = set(pos_params) | {a.arg for a in item.args.kwonlyargs}
                    spec.pos_params = pos_params
                    for body_stmt in item.body:
                        if (
                            isinstance(body_stmt, ast.Assign)
                            and len(body_stmt.targets) == 1
                            and isinstance(body_stmt.targets[0], ast.Attribute)
                            and isinstance(body_stmt.targets[0].value, ast.Name)
                            and body_stmt.targets[0].value.id == "self"
                            and isinstance(body_stmt.value, ast.Name)
                            and body_stmt.value.id in all_params
                        ):
                            spec.param_to_attr[body_stmt.value.id] = body_stmt.targets[0].attr
                elif isinstance(item, ast.FunctionDef) and item.name != "__init__":
                    # Inspect register_* / set_* / add_* methods that store a param on `self.<attr>`
                    m_pos = [a.arg for a in item.args.posonlyargs + item.args.args[1:]]
                    m_all = set(m_pos) | {a.arg for a in item.args.kwonlyargs}
                    m_map: dict[str, str] = {}
                    for body_stmt in ast.walk(item):
                        if (
                            isinstance(body_stmt, ast.Assign)
                            and len(body_stmt.targets) == 1
                            and isinstance(body_stmt.targets[0], ast.Attribute)
                            and isinstance(body_stmt.targets[0].value, ast.Name)
                            and body_stmt.targets[0].value.id == "self"
                            and isinstance(body_stmt.value, ast.Name)
                            and body_stmt.value.id in m_all
                        ):
                            m_map[body_stmt.value.id] = body_stmt.targets[0].attr
                        elif (
                            isinstance(body_stmt, ast.Call)
                            and isinstance(body_stmt.func, ast.Attribute)
                            and body_stmt.func.attr == "append"
                            and isinstance(body_stmt.func.value, ast.Attribute)
                            and isinstance(body_stmt.func.value.value, ast.Name)
                            and body_stmt.func.value.value.id == "self"
                            and len(body_stmt.args) == 1
                            and isinstance(body_stmt.args[0], ast.Name)
                            and body_stmt.args[0].id in m_all
                        ):
                            m_map[body_stmt.args[0].id] = body_stmt.func.value.attr
                    if m_map:
                        spec.method_specs[item.name] = (m_pos, m_map)

            if not has_init and dataclass_fields:
                spec.pos_params = dataclass_fields
                for fname in dataclass_fields:
                    spec.param_to_attr[fname] = fname

    # Pass 2: Scan all class constructions, `.legacy(...)` calls, and `register_*` / setter calls
    for minfo in prod.modules.values():
        _scan_wiring(minfo, pf, patched_names)

    return pf


def _record_wire(
    pf: _PortForwarding,
    cls_name: str,
    attr: str,
    expr: ast.AST,
    minfo: ModuleInfo,
    lineno: int,
    patched_names: set[str],
) -> None:
    # Handle tuple/list of callbacks (e.g. Context(after_save=(fn1, fn2)))
    if isinstance(expr, (ast.Tuple, ast.List)):
        for elt in expr.elts:
            _record_wire(pf, cls_name, attr, elt, minfo, lineno, patched_names)
        return
    wire = _extract_forwarder(expr, minfo, f"{minfo.relpath}:{lineno}")
    if wire is not None and wire.target_sym in patched_names:
        pf.wired[(cls_name, attr)].append(wire)
        if cls_name == "Context":
            pf.context_fields[attr].append(wire)


def _scan_wiring(minfo: ModuleInfo, pf: _PortForwarding, patched_names: set[str]) -> None:
    # Also index every class's `legacy(...)` param names so positional args to `Class.legacy(...)` map properly
    class _WireVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.cur_class: str | None = None

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            prev = self.cur_class
            self.cur_class = node.name
            self.generic_visit(node)
            self.cur_class = prev

        def visit_Call(self, node: ast.Call) -> None:
            cls_name: str | None = None
            method_name: str | None = None
            chain = _attr_chain(node.func)
            if chain:
                if chain == ["cls"] and self.cur_class:
                    cls_name = self.cur_class
                elif len(chain) == 1 and chain[0] in pf.class_specs:
                    cls_name = chain[0]
                elif len(chain) >= 2 and chain[-1] == "legacy" and chain[-2] in pf.class_specs:
                    cls_name = chain[-2]
                elif len(chain) >= 2 and chain[-1] in pf.class_specs:
                    cls_name = chain[-1]
                elif len(chain) >= 2:
                    # Check if calling a known register_* / setter method on any class
                    cand_method = chain[-1]
                    for cname, cspec in pf.class_specs.items():
                        if cand_method in cspec.method_specs:
                            cls_name = cname
                            method_name = cand_method
                            break

            if cls_name and cls_name in pf.class_specs:
                spec = pf.class_specs[cls_name]
                if method_name is not None:
                    pos_params, param_map = spec.method_specs[method_name]
                else:
                    pos_params, param_map = spec.pos_params, spec.param_to_attr

                # Bind positional arguments
                for idx, arg_expr in enumerate(node.args):
                    if isinstance(arg_expr, ast.Starred):
                        break
                    if idx < len(pos_params):
                        pname = pos_params[idx]
                        if pname in param_map:
                            _record_wire(pf, cls_name, param_map[pname], arg_expr, minfo, node.lineno, patched_names)

                # Bind keyword arguments
                for kw in node.keywords:
                    if kw.arg and kw.arg in param_map:
                        _record_wire(pf, cls_name, param_map[kw.arg], kw.value, minfo, node.lineno, patched_names)

            self.generic_visit(node)

    _WireVisitor().visit(minfo.tree)


def _extract_kwarg_guard(test: ast.expr) -> tuple[str, str] | None:
    """Detect `if _accepts_kwarg(fn, "herdr_docs"):` -> `(var_name, kw_name)`."""
    if isinstance(test, ast.Call):
        chain = _attr_chain(test.func)
        if chain and chain[-1] == "_accepts_kwarg" and len(test.args) >= 2:
            if (
                isinstance(test.args[0], ast.Name)
                and isinstance(test.args[1], ast.Constant)
                and isinstance(test.args[1].value, str)
            ):
                return test.args[0].id, test.args[1].value
    return None


class _ProdUsageVisitor(ast.NodeVisitor):
    def __init__(
        self,
        minfo: ModuleInfo,
        prod: ProdIndex,
        patched_names: set[str],
        pf: _PortForwarding,
    ) -> None:
        self.minfo = minfo
        self.prod = prod
        self.patched_names = patched_names
        self.pf = pf
        self.calls: list[CallSite] = []
        self.refs: list[RefSite] = []
        self.bridge_errors: list[Finding] = []
        self.bridge_reviews: list[Finding] = []
        self.direct_impl_calls: dict[str, list[str]] = defaultdict(list)
        self.scope_locals: list[set[str]] = [set()]
        self.scope_globals: list[set[str]] = [set()]
        self.fn_aliases: list[dict[str, tuple[str, str]]] = [{}]  # local var -> (sym, target_mod_ref)
        self.wired_aliases: list[dict[str, tuple[list[_ForwardWire], str]]] = [{}]
        self.dyn_mods: list[dict[str, str]] = [{}]
        self.guarded_kws: list[dict[str, set[str]]] = [{}]
        self.cur_class: str | None = None
        self.cur_top_func: str | None = None
        self.in_legacy_func: bool = False

    def _is_shadowed(self, name: str) -> bool:
        for locals_set, globals_set in zip(self.scope_locals[1:], self.scope_globals[1:]):
            if name in locals_set and name not in globals_set:
                return True
        return False

    def _lookup_local_callable(
        self, name: str
    ) -> tuple[str, Any] | None:
        """Look up `name` from innermost scope outward, returning ('alias', (sym, mod)) or ('wired', (wires, via))."""
        for fn_d, wired_d in zip(reversed(self.fn_aliases), reversed(self.wired_aliases)):
            if name in wired_d:
                return "wired", wired_d[name]
            if name in fn_d:
                return "alias", fn_d[name]
        return None

    def _resolve_wired_expr(self, expr: ast.AST) -> tuple[list[_ForwardWire], str] | None:
        """Resolve `self.<attr>`, `ctx.<field>`, `self._ctx.<field>`, or simple wrappers/aliases to wired callbacks."""
        if isinstance(expr, ast.Name):
            hit = self._lookup_local_callable(expr.id)
            if hit is not None and hit[0] == "wired":
                return hit[1]
            return None
        if isinstance(expr, ast.Attribute):
            if (
                self.cur_class is not None
                and isinstance(expr.value, ast.Name)
                and expr.value.id == "self"
            ):
                wired_list = self.pf.wired.get((self.cur_class, expr.attr))
                if wired_list:
                    return wired_list, f"{self.cur_class}.{expr.attr}"
            chain = _attr_chain(expr)
            if chain and len(chain) >= 2 and chain[-2] in ("ctx", "_ctx", "context"):
                ctx_wires = self.pf.context_fields.get(chain[-1])
                if ctx_wires:
                    return ctx_wires, f"Context.{chain[-1]}"
            return None
        if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.Or):
            for val in expr.values:
                hit = self._resolve_wired_expr(val)
                if hit is not None:
                    return hit
            return None
        if (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id in ("list", "tuple", "reversed", "iter")
            and len(expr.args) == 1
        ):
            return self._resolve_wired_expr(expr.args[0])
        return None

    def _lookup_dyn_mod(self, name: str) -> str | None:
        for d in reversed(self.dyn_mods):
            if name in d:
                return d[name]
        return None

    def _lookup_guarded_kws(self, name: str) -> frozenset[str]:
        res: set[str] = set()
        for d in self.guarded_kws:
            if name in d:
                res |= d[name]
        return frozenset(res)

    def _resolve_mod_attr(self, node: ast.Attribute) -> tuple[str, str] | None:
        chain = _attr_chain(node)
        if not chain or len(chain) < 2:
            return None
        attr = chain[-1]
        prefix = ".".join(chain[:-1])
        if prefix in self.minfo.mod_imports:
            return self.minfo.mod_imports[prefix], attr
        if len(chain) == 2:
            dyn = self._lookup_dyn_mod(chain[0])
            if dyn:
                return dyn, attr
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev = self.cur_class
        self.cur_class = node.name
        self.scope_locals.append(set())
        self.scope_globals.append(set())
        self.fn_aliases.append({})
        self.wired_aliases.append({})
        self.dyn_mods.append({})
        self.guarded_kws.append({})
        self.generic_visit(node)
        self.scope_locals.pop()
        self.scope_globals.pop()
        self.fn_aliases.pop()
        self.wired_aliases.pop()
        self.dyn_mods.pop()
        self.guarded_kws.pop()
        self.cur_class = prev

    def visit_Global(self, node: ast.Global) -> None:
        self.scope_globals[-1].update(node.names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        is_top = self.cur_class is None and self.cur_top_func is None
        prev_top = self.cur_top_func
        prev_legacy = self.in_legacy_func
        if is_top:
            self.cur_top_func = node.name
        if "legacy" in node.name:
            self.in_legacy_func = True

        params = {a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs}
        if node.args.vararg:
            params.add(node.args.vararg.arg)
        if node.args.kwarg:
            params.add(node.args.kwarg.arg)

        self.scope_locals.append(params)
        self.scope_globals.append(set())
        self.fn_aliases.append({})
        self.wired_aliases.append({})
        self.dyn_mods.append({})
        self.guarded_kws.append({})
        for stmt in node.body:
            self.visit(stmt)
        self.scope_locals.pop()
        self.scope_globals.pop()
        self.fn_aliases.pop()
        self.wired_aliases.pop()
        self.dyn_mods.pop()
        self.guarded_kws.pop()

        self.cur_top_func = prev_top
        self.in_legacy_func = prev_legacy

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        params = {a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs}
        if node.args.vararg:
            params.add(node.args.vararg.arg)
        if node.args.kwarg:
            params.add(node.args.kwarg.arg)
        self.scope_locals.append(params)
        self.scope_globals.append(set())
        self.fn_aliases.append({})
        self.wired_aliases.append({})
        self.dyn_mods.append({})
        self.guarded_kws.append({})
        self.visit(node.body)
        self.scope_locals.pop()
        self.scope_globals.pop()
        self.fn_aliases.pop()
        self.wired_aliases.pop()
        self.dyn_mods.pop()
        self.guarded_kws.pop()

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        wired_hit = (
            self._resolve_wired_expr(node.iter)
            if isinstance(node.target, ast.Name)
            else None
        )
        if isinstance(node.target, ast.Name) and len(self.scope_locals) > 1:
            self.scope_locals[-1].add(node.target.id)
        if wired_hit is not None and isinstance(node.target, ast.Name):
            self.fn_aliases.append({})
            self.wired_aliases.append({node.target.id: wired_hit})
            for stmt in node.body:
                self.visit(stmt)
            self.wired_aliases.pop()
            self.fn_aliases.pop()
        else:
            for stmt in node.body:
                self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    visit_AsyncFor = visit_For

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        guard = _extract_kwarg_guard(node.test)
        if guard:
            var_name, kw_name = guard
            self.guarded_kws.append({var_name: {kw_name}})
            for stmt in node.body:
                self.visit(stmt)
            self.guarded_kws.pop()
        else:
            for stmt in node.body:
                self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(self.scope_locals) == 1:
            if (
                len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and (node.targets[0].id == "__all__" or node.targets[0].id.startswith("_DEFAULT_"))
            ):
                return

        if len(self.scope_locals) > 1:
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    if (
                        isinstance(node.value, ast.Call)
                        and _attr_chain(node.value.func) == ["sys", "modules", "get"]
                        and node.value.args
                        and isinstance(node.value.args[0], ast.Constant)
                        and isinstance(node.value.args[0].value, str)
                        and node.value.args[0].value.startswith("pmlib.")
                    ):
                        self.dyn_mods[-1][tgt.id] = node.value.args[0].value
                    elif isinstance(node.value, ast.Attribute):
                        res = self._resolve_mod_attr(node.value)
                        if res and res[1] in self.patched_names:
                            self.fn_aliases[-1][tgt.id] = (res[1], res[0])
                        else:
                            wired_hit = self._resolve_wired_expr(node.value)
                            if wired_hit is not None:
                                self.wired_aliases[-1][tgt.id] = wired_hit
                    else:
                        wired_hit = self._resolve_wired_expr(node.value)
                        if wired_hit is not None:
                            self.wired_aliases[-1][tgt.id] = wired_hit
                    self.scope_locals[-1].add(tgt.id)

        self.visit(node.value)

    def _emit_wired_call(
        self,
        wires: list[_ForwardWire],
        node: ast.Call,
        via_prefix: str,
        pos_count: int,
        has_star: bool,
        kw_names: tuple[str, ...],
        has_dstar: bool,
    ) -> None:
        expr_str = _short_unparse(node)
        call_loc = f"{self.minfo.relpath}:{node.lineno}"
        for w in wires:
            ref_kind = "legacy_only" if self.in_legacy_func else "call"
            self.refs.append(
                RefSite(
                    file=self.minfo.relpath,
                    lineno=node.lineno,
                    module=self.minfo.name,
                    target_name=w.target_sym,
                    kind=ref_kind,
                    expr=expr_str,
                    target_mod_ref=w.target_mod_ref,
                )
            )
            via = f"forwarded via {via_prefix} (wired at {w.wire_loc})"
            if w.kind == "direct":
                self.calls.append(
                    CallSite(
                        file=self.minfo.relpath,
                        lineno=node.lineno,
                        module=self.minfo.name,
                        target_name=w.target_sym,
                        pos_count=pos_count,
                        has_star_args=has_star,
                        kw_names=kw_names,
                        has_double_star=has_dstar,
                        via=via,
                        expr=expr_str,
                        target_mod_ref=w.target_mod_ref,
                    )
                )
                continue

            # Lambda bridge: first validate call arguments against the bridge lambda's own signature.
            if w.bridge_sig is not None:
                raw_call = CallSite(
                    file=self.minfo.relpath,
                    lineno=node.lineno,
                    module=self.minfo.name,
                    target_name=w.target_sym,
                    pos_count=pos_count,
                    has_star_args=has_star,
                    kw_names=kw_names,
                    has_double_star=has_dstar,
                    via=via,
                    expr=expr_str,
                    target_mod_ref=w.target_mod_ref,
                )
                bridge_reason = w.bridge_sig.check_call(raw_call, sig_label="bridge sig")
                if bridge_reason is not None:
                    self.bridge_errors.append(
                        Finding(
                            severity="error",
                            code="SIG_MISMATCH",
                            attr=w.target_sym,
                            message=f"{expr_str} [{via}] -> {bridge_reason}",
                            call_loc=call_loc,
                            patch_loc=w.wire_loc,
                        )
                    )
                    continue
                if has_dstar and not w.bridge_sig.has_varkw:
                    self.bridge_reviews.append(
                        Finding(
                            severity="review",
                            code="DYNAMIC_CALL_SITE",
                            attr=w.target_sym,
                            message=(
                                f"Call `{expr_str}` [{via}] uses **kwargs, while bridge lambda at "
                                f"{w.wire_loc} has signature {w.bridge_sig.raw} without **kwargs"
                            ),
                            call_loc=call_loc,
                            patch_loc=w.wire_loc,
                        )
                    )
                if has_star and not w.bridge_sig.has_vararg:
                    self.bridge_reviews.append(
                        Finding(
                            severity="review",
                            code="DYNAMIC_CALL_SITE",
                            attr=w.target_sym,
                            message=(
                                f"Call `{expr_str}` [{via}] unpacks *args, while bridge lambda at "
                                f"{w.wire_loc} has fixed positional signature {w.bridge_sig.raw} without *args"
                            ),
                            call_loc=call_loc,
                            patch_loc=w.wire_loc,
                        )
                    )

            # For lambdas that forward `*args` and/or `**kwargs`, also project the forwarded call shape
            # onto `w.target_sym` so it is checked against test patch signatures.
            # (`kind == "fixed"` body calls like `fn(x)` are already checked directly by `visit_Call`.)
            if w.forwards_var or w.forwards_kw:
                bridge_pos_count = len(w.bridge_sig.all_pos_params) if w.bridge_sig is not None else 0
                bridge_named = w.bridge_sig.accepted_kwargs if w.bridge_sig is not None else frozenset()
                if w.forwards_var:
                    fwd_pos = w.body_fixed_pos + max(0, pos_count - bridge_pos_count)
                    fwd_has_star = has_star or w.body_has_extra_star
                else:
                    fwd_pos = w.body_fixed_pos
                    fwd_has_star = w.body_has_extra_star

                if w.forwards_kw:
                    forwarded_kws = [k for k in kw_names if k not in bridge_named]
                    fwd_kws = tuple(dict.fromkeys((*w.body_fixed_kws, *forwarded_kws)))
                    fwd_has_dstar = has_dstar or w.body_has_extra_dstar
                else:
                    fwd_kws = w.body_fixed_kws
                    fwd_has_dstar = w.body_has_extra_dstar

                self.calls.append(
                    CallSite(
                        file=self.minfo.relpath,
                        lineno=node.lineno,
                        module=self.minfo.name,
                        target_name=w.target_sym,
                        pos_count=fwd_pos,
                        has_star_args=fwd_has_star,
                        kw_names=fwd_kws,
                        has_double_star=fwd_has_dstar,
                        via=via,
                        expr=expr_str,
                        target_mod_ref=w.target_mod_ref,
                    )
                )

    def visit_Call(self, node: ast.Call) -> None:
        pos_count, has_star, kw_names, has_dstar = _call_shape(node)
        target_sym: str | None = None
        target_mod_ref = self.minfo.name
        via = "direct"
        guarded: frozenset[str] = frozenset()

        if isinstance(node.func, ast.Name):
            name = node.func.id
            local_hit = self._lookup_local_callable(name)
            if local_hit is not None and local_hit[0] == "alias":
                target_sym, target_mod_ref = local_hit[1]
                via = "alias"
                guarded = self._lookup_guarded_kws(name)
            elif local_hit is not None and local_hit[0] == "wired":
                wires, via_prefix = local_hit[1]
                self._emit_wired_call(
                    wires, node, via_prefix, pos_count, has_star, kw_names, has_dstar,
                )
            elif not self._is_shadowed(name) and name in self.patched_names:
                if name in self.minfo.defs or name in self.minfo.sym_imports:
                    target_sym = name
                    target_mod_ref = self.minfo.name
                    via = "direct"
            if name.startswith("_") and name.endswith("_impl"):
                base = name[1:-5]
                if base in self.patched_names and self.cur_top_func != base:
                    self.direct_impl_calls[base].append(f"{self.minfo.relpath}:{node.lineno}")
            elif name in self.minfo.default_snapshots:
                orig = self.minfo.default_snapshots[name]
                if orig in self.patched_names and self.cur_top_func != orig:
                    self.direct_impl_calls[orig].append(f"{self.minfo.relpath}:{node.lineno}")

        elif isinstance(node.func, ast.Attribute):
            res = self._resolve_mod_attr(node.func)
            if res is not None:
                canon_mod, attr = res
                if attr in self.patched_names:
                    target_sym = attr
                    target_mod_ref = canon_mod
                    via = "module"
                elif attr.startswith("_") and attr.endswith("_impl"):
                    base = attr[1:-5]
                    if base in self.patched_names and self.cur_top_func != base:
                        self.direct_impl_calls[base].append(f"{self.minfo.relpath}:{node.lineno}")
            else:
                wired_hit = self._resolve_wired_expr(node.func)
                if wired_hit is not None:
                    wires, via_prefix = wired_hit
                    self._emit_wired_call(
                        wires, node, via_prefix, pos_count, has_star, kw_names, has_dstar,
                    )

        if target_sym is not None:
            self.calls.append(
                CallSite(
                    file=self.minfo.relpath,
                    lineno=node.lineno,
                    module=self.minfo.name,
                    target_name=target_sym,
                    pos_count=pos_count,
                    has_star_args=has_star,
                    kw_names=kw_names,
                    has_double_star=has_dstar,
                    guarded_kwargs=guarded,
                    via=via,
                    expr=_short_unparse(node),
                    target_mod_ref=target_mod_ref,
                )
            )
            if not (via == "direct" and self.cur_top_func == target_sym):
                self.refs.append(
                    RefSite(
                        file=self.minfo.relpath,
                        lineno=node.lineno,
                        module=self.minfo.name,
                        target_name=target_sym,
                        kind="legacy_only" if self.in_legacy_func else "call",
                        expr=_short_unparse(node),
                        target_mod_ref=target_mod_ref,
                    )
                )

        for a in node.args:
            self.visit(a)
        for kw in node.keywords:
            self.visit(kw.value)
        if isinstance(node.func, ast.Attribute) and target_sym is None:
            self.visit(node.func.value)
        elif not isinstance(node.func, (ast.Name, ast.Attribute)):
            self.visit(node.func)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            res = self._resolve_mod_attr(node)
            if res is not None:
                canon_mod, attr = res
                if attr in self.patched_names:
                    self.refs.append(
                        RefSite(
                            file=self.minfo.relpath,
                            lineno=node.lineno,
                            module=self.minfo.name,
                            target_name=attr,
                            kind="legacy_only" if self.in_legacy_func else "read",
                            expr=_short_unparse(node),
                            target_mod_ref=canon_mod,
                        )
                    )
                    return
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            name = node.id
            if not self._is_shadowed(name) and name in self.patched_names:
                if name in self.minfo.defs or name in self.minfo.sym_imports:
                    if self.cur_top_func != name:
                        self.refs.append(
                            RefSite(
                                file=self.minfo.relpath,
                                lineno=node.lineno,
                                module=self.minfo.name,
                                target_name=name,
                                kind="legacy_only" if self.in_legacy_func else "read",
                                expr=name,
                                target_mod_ref=self.minfo.name,
                            )
                        )


# ---------------------------------------------------------------------------
# Stage 4: Audit Engine
# ---------------------------------------------------------------------------

def load_baseline(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        return {str(x) for x in data["entries"]}
    if isinstance(data, list):
        return {str(x) for x in data}
    return set()


def save_baseline(path: Path, findings: list[Finding]) -> None:
    entries = sorted({f.fingerprint for f in findings})
    payload = {
        "comment": (
            "Pre-existing narrow test_pm*.py patch mismatches present on main (frozen in Pass 2 Stages 1-5). "
            "Run `patch_audit.py --no-baseline` to view all raw findings."
        ),
        "entries": entries,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def audit(scripts_dir: Path | str, *, baseline: set[str] | None = None) -> AuditReport:
    t0 = time.monotonic()
    scripts = Path(scripts_dir).resolve()
    prod = build_prod_index(scripts)
    patches, n_test_files = collect_patches(scripts, prod)

    by_attr: dict[str, list[PatchSite]] = defaultdict(list)
    by_mod_attr: dict[tuple[str, str], list[PatchSite]] = defaultdict(list)
    for p in patches:
        by_attr[p.attr].append(p)
        by_mod_attr[(p.target_mod, p.attr)].append(p)
    patched_names = set(by_attr.keys())

    pf = _collect_port_forwarding(prod, patched_names)

    all_calls: list[CallSite] = []
    all_refs: list[RefSite] = []
    bridge_errors: list[Finding] = []
    bridge_reviews: list[Finding] = []
    direct_impl_calls: dict[str, list[str]] = defaultdict(list)

    for minfo in prod.modules.values():
        visitor = _ProdUsageVisitor(minfo, prod, patched_names, pf)
        visitor.visit(minfo.tree)
        all_calls.extend(visitor.calls)
        all_refs.extend(visitor.refs)
        bridge_errors.extend(visitor.bridge_errors)
        bridge_reviews.extend(visitor.bridge_reviews)
        for k, locs in visitor.direct_impl_calls.items():
            direct_impl_calls[k].extend(locs)

    calls_by_attr: dict[str, list[CallSite]] = defaultdict(list)
    for c in all_calls:
        calls_by_attr[c.target_name].append(c)

    refs_by_attr: dict[str, list[RefSite]] = defaultdict(list)
    for r in all_refs:
        refs_by_attr[r.target_name].append(r)

    errors: list[Finding] = []
    reviews: list[Finding] = []

    # 1. Missing attribute check
    seen_missing: set[tuple[str, str]] = set()
    for p in patches:
        key = (p.target_mod, p.attr)
        if key in seen_missing:
            continue
        exists = (
            prod.has_pm_attr(p.attr)
            if p.target_mod == "pm"
            else prod.has_mod_attr(p.target_mod, p.attr)
        )
        if not exists:
            seen_missing.add(key)
            errors.append(
                Finding(
                    severity="error",
                    code="MISSING_ATTR",
                    attr=p.attr,
                    message=f"Test patches {p.target_mod}.{p.attr}, but it does not exist in production code",
                    patch_loc=f"{p.file}:{p.lineno}",
                )
            )

    # 2. Aliased import bypass check (`from ... import X as Y` bypasses compat.py)
    for attr in sorted(patched_names):
        if ("pm", attr) not in by_mod_attr:
            continue
        aliases = prod.alias_imports.get(attr, [])
        if aliases:
            first_patch = f"{by_mod_attr[('pm', attr)][0].file}:{by_mod_attr[('pm', attr)][0].lineno}"
            for _imp_mod, relpath, local_alias, lineno in aliases:
                errors.append(
                    Finding(
                        severity="error",
                        code="ALIAS_IMPORT_BYPASS",
                        attr=attr,
                        message=(
                            f"`from ... import {attr} as {local_alias}` at {relpath}:{lineno} "
                            f"bypasses compat.py when tests patch `pm.{attr}`"
                        ),
                        call_loc=f"{relpath}:{lineno}",
                        patch_loc=first_patch,
                    )
                )

    # 3. Signature compatibility check + UNKNOWN_SIG + DYNAMIC_CALL_SITE (*args and **kwargs)
    seen_sig_errors: set[tuple[str, str, str]] = set()
    for err in bridge_errors:
        dedup_key = (err.attr, err.call_loc, err.patch_loc)
        if dedup_key not in seen_sig_errors:
            seen_sig_errors.add(dedup_key)
            errors.append(err)
    reviews.extend(bridge_reviews)

    for attr in sorted(patched_names):
        attr_calls = calls_by_attr.get(attr, [])
        attr_patches = by_attr[attr]
        callable_patches = [p for p in attr_patches if p.sig.kind == "callable"]
        unknown_patches = [p for p in attr_patches if p.sig.kind == "unknown"]

        # Never silently drop UNKNOWN_SIG on callable production symbols or any symbol called in prod
        if prod.symbol_kind(attr) in ("func", "class") or attr_calls:
            for p in unknown_patches:
                reviews.append(
                    Finding(
                        severity="review",
                        code="UNKNOWN_SIG",
                        attr=attr,
                        message=(
                            f"Cannot statically determine callable signature of `{p.expr}` "
                            f"patching `{p.target_mod}.{attr}`; verify compatibility manually"
                        ),
                        patch_loc=f"{p.file}:{p.lineno}",
                    )
                )

        for call in attr_calls:
            call_loc = f"{call.file}:{call.lineno}"
            is_transparent_wrapper = (
                call.pos_count == 0 and call.has_star_args and not call.kw_names
            )
            for p in callable_patches:
                # If patch targets a specific submodule, only check calls that hit that submodule
                if p.target_mod != "pm" and call.target_mod_ref and call.target_mod_ref != p.target_mod:
                    continue
                reason = p.sig.check_call(call)
                if reason is not None:
                    patch_loc = f"{p.file}:{p.lineno}"
                    dedup_key = (attr, call_loc, patch_loc)
                    if dedup_key in seen_sig_errors:
                        continue
                    seen_sig_errors.add(dedup_key)
                    via_note = f" [{call.via}]" if call.via != "direct" else ""
                    errors.append(
                        Finding(
                            severity="error",
                            code="SIG_MISMATCH",
                            attr=attr,
                            message=f"{call.expr}{via_note} -> {reason}",
                            call_loc=call_loc,
                            patch_loc=patch_loc,
                        )
                    )
                else:
                    if call.has_double_star and not p.sig.has_varkw and not is_transparent_wrapper:
                        reviews.append(
                            Finding(
                                severity="review",
                                code="DYNAMIC_CALL_SITE",
                                attr=attr,
                                message=(
                                    f"Call `{call.expr}` uses **kwargs, while patch at {p.file}:{p.lineno} "
                                    f"has signature {p.sig.raw} without **kwargs"
                                ),
                                call_loc=call_loc,
                                patch_loc=f"{p.file}:{p.lineno}",
                            )
                        )
                    if call.has_star_args and not p.sig.has_vararg and not is_transparent_wrapper:
                        reviews.append(
                            Finding(
                                severity="review",
                                code="DYNAMIC_CALL_SITE",
                                attr=attr,
                                message=(
                                    f"Call `{call.expr}` unpacks *args, while patch at {p.file}:{p.lineno} "
                                    f"has fixed positional signature {p.sig.raw} without *args"
                                ),
                                call_loc=call_loc,
                                patch_loc=f"{p.file}:{p.lineno}",
                            )
                        )

    # 4. Reachability check — checked per `(target_mod, attr)` so submodule patches are verified accurately
    for (target_mod, attr), mod_patches in sorted(by_mod_attr.items()):
        if (target_mod, attr) in seen_missing:
            continue
        first_patch = f"{mod_patches[0].file}:{mod_patches[0].lineno}"
        all_attr_refs = refs_by_attr.get(attr, [])
        if target_mod == "pm":
            matching_refs = all_attr_refs
        else:
            # Direct submodule patch does NOT go through compat.py: only refs targeting `target_mod` see it!
            matching_refs = [r for r in all_attr_refs if r.target_mod_ref == target_mod]

        if not matching_refs:
            scope_desc = f"`{attr}`" if target_mod == "pm" else f"`{target_mod}.{attr}`"
            errors.append(
                Finding(
                    severity="error",
                    code="UNREACHABLE_PATCH",
                    attr=attr,
                    message=(
                        f"Patched in {len(mod_patches)} place(s) (e.g. {first_patch}), "
                        f"but no production code references or calls {scope_desc}"
                    ),
                    patch_loc=first_patch,
                )
            )
            continue

        # Bypass risks (manual review)
        impl_locs = direct_impl_calls.get(attr, [])
        if impl_locs:
            reviews.append(
                Finding(
                    severity="review",
                    code="BYPASS_RISK",
                    attr=attr,
                    message=(
                        f"Production code calls `_{attr}_impl` / `_DEFAULT_{attr}` directly at "
                        f"{', '.join(impl_locs[:3])}; verify patches to `{attr}` are not bypassed"
                    ),
                    call_loc=impl_locs[0],
                    patch_loc=first_patch,
                )
            )
        elif all(r.kind == "legacy_only" for r in matching_refs):
            reviews.append(
                Finding(
                    severity="review",
                    code="BYPASS_RISK",
                    attr=attr,
                    message=(
                        f"`{attr}` is only referenced inside `legacy` bridge code "
                        f"({matching_refs[0].file}:{matching_refs[0].lineno}); "
                        f"verify non-legacy paths don't bypass test patches"
                    ),
                    call_loc=f"{matching_refs[0].file}:{matching_refs[0].lineno}",
                    patch_loc=first_patch,
                )
            )

    # 5. Same-name port/class method bypass check (uses `prod.class_methods`)
    for attr in sorted(patched_names):
        if prod.symbol_kind(attr) not in ("func", "class") and not calls_by_attr.get(attr):
            continue
        first_patch = f"{by_attr[attr][0].file}:{by_attr[attr][0].lineno}"
        for cm in prod.class_methods.get(attr, []):
            if cm.calls_module_sym:
                continue
            # Check if the class method invokes any `self._*` attribute wired to `attr`
            delegates_via_wire = any(
                any(w.target_sym == attr for w in pf.wired.get((cm.cls_name, sa), ()))
                for sa in cm.self_attr_calls
            )
            if not delegates_via_wire:
                reviews.append(
                    Finding(
                        severity="review",
                        code="BYPASS_RISK",
                        attr=attr,
                        message=(
                            f"Class method `{cm.cls_name}.{cm.method_name}` ({cm.file}:{cm.lineno}) "
                            f"shares name with patched `{attr}` without delegating to it; "
                            f"verify callers using `{cm.cls_name}.{cm.method_name}` don't bypass patches"
                        ),
                        call_loc=f"{cm.file}:{cm.lineno}",
                        patch_loc=first_patch,
                    )
                )

    # Deduplicate review findings by (code, attr, call_loc, patch_loc)
    dedup_reviews: list[Finding] = []
    seen_rev: set[tuple[str, str, str, str]] = set()
    for r in reviews:
        k = (r.code, r.attr, r.call_loc, r.patch_loc)
        if k not in seen_rev:
            seen_rev.add(k)
            dedup_reviews.append(r)

    active_errors: list[Finding] = []
    baselined_errors: list[Finding] = []
    if baseline:
        for e in errors:
            if e.fingerprint in baseline:
                baselined_errors.append(e)
            else:
                active_errors.append(e)
    else:
        active_errors = errors

    elapsed_ms = (time.monotonic() - t0) * 1000.0
    return AuditReport(
        scripts_dir=str(scripts),
        prod_files=len(prod.modules),
        test_files=n_test_files,
        patch_sites=len(patches),
        patched_attrs=len(patched_names),
        call_sites=len(all_calls),
        elapsed_ms=elapsed_ms,
        errors=active_errors,
        baselined=baselined_errors,
        reviews=dedup_reviews,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def format_report(report: AuditReport) -> str:
    lines: list[str] = []
    base_note = f", {len(report.baselined)} baselined" if report.baselined else ""
    lines.append(
        f"patch_audit: {report.prod_files} prod modules, {report.test_files} test files, "
        f"{report.patch_sites} patch sites ({report.patched_attrs} unique attrs), "
        f"{report.call_sites} prod call sites{base_note} [{report.elapsed_ms:.0f}ms]"
    )
    if report.errors:
        lines.append(f"\nERRORS ({len(report.errors)}):")
        for f in report.errors:
            loc = f"call={f.call_loc} patch={f.patch_loc}" if f.call_loc else f"patch={f.patch_loc}"
            lines.append(f"  [{f.code}] {f.attr} ({loc})")
            lines.append(f"    {f.message}")
    else:
        lines.append("\nERRORS (0): none")

    if report.reviews:
        lines.append(f"\nMANUAL REVIEW ({len(report.reviews)}):")
        for f in report.reviews:
            loc = f"call={f.call_loc} patch={f.patch_loc}" if f.call_loc else f"patch={f.patch_loc}"
            lines.append(f"  [{f.code}] {f.attr} ({loc})")
            lines.append(f"    {f.message}")
    else:
        lines.append("\nMANUAL REVIEW (0): none")

    return "\n".join(lines)


def default_baseline_path(scripts_dir: Path | None = None) -> Path:
    if scripts_dir is not None:
        candidate = scripts_dir / "tests" / "patch_audit_baseline.json"
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parent / "patch_audit_baseline.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Static contract audit for pm/pmlib test patches.")
    parser.add_argument(
        "--scripts",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Path to mods/pm-dash/skill/scripts (default: parent of tests/)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Path to baseline JSON file (default: tests/patch_audit_baseline.json if present).",
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="Ignore baseline and report every raw finding (including pre-existing main mismatches).",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Write all current errors to the baseline JSON file and exit 0.",
    )
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on manual-review items too.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output JSON report.")
    args = parser.parse_args(argv)

    scripts = args.scripts.resolve()
    baseline_path = args.baseline if args.baseline is not None else default_baseline_path(scripts)

    if args.update_baseline:
        raw_report = audit(scripts, baseline=None)
        save_baseline(baseline_path, raw_report.errors)
        print(f"Wrote {len({f.fingerprint for f in raw_report.errors})} unique baseline entries to {baseline_path}")
        return 0

    baseline_keys = set() if args.no_baseline else load_baseline(baseline_path)
    report = audit(scripts, baseline=baseline_keys)
    if args.as_json:
        payload: dict[str, Any] = {
            "scripts_dir": report.scripts_dir,
            "prod_files": report.prod_files,
            "test_files": report.test_files,
            "patch_sites": report.patch_sites,
            "patched_attrs": report.patched_attrs,
            "call_sites": report.call_sites,
            "baselined_count": len(report.baselined),
            "elapsed_ms": round(report.elapsed_ms, 1),
            "errors": [f.__dict__ for f in report.errors],
            "reviews": [f.__dict__ for f in report.reviews],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))

    if report.errors:
        return 1
    if args.strict and report.reviews:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
