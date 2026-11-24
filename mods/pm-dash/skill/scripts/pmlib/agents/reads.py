"""Outside-worktree read permissions for agents: Herdr API docs path, `docs_line`, `outside_reads`, `wide_folder`,
and Claude Code's `--settings <file>` generator (`read_settings`). Layer 1."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterable, Mapping

import pmlib.home
from .. import config as config_mod
from . import base as base_mod


# Herdr's mod API docs (herdr.d.ts, AGENTS.md); the running app keeps its state here too, so workers only read it.
HERDR_DOCS = Path.home() / ".config" / "herdr-app"
_DEFAULT_HERDR_DOCS = HERDR_DOCS


def docs_line(
    *,
    herdr_docs: Path | str | None = None,
    tr_fn: Callable[[str, str], str] | None = None,
) -> str:
    """Said to every worker and reviewer where Herdr's API docs are: they are let read them (outside_reads), and the
    running app keeps its state in that folder, so nothing is written there."""
    docs = HERDR_DOCS if herdr_docs is None else Path(herdr_docs)
    if not docs.is_dir():
        return ""
    where = f"~/{docs.relative_to(Path.home())}" if docs.is_relative_to(Path.home()) else str(docs)
    translate = config_mod.tr if tr_fn is None else tr_fn
    return "\n" + translate(
        f"Herdr's API docs in {where} are for reading only: write nothing there (the running app keeps "
        "its state in it).",
        f"{where} 里的 Herdr API 文档只读：不要往这个目录写任何东西（正在运行的 Herdr 在里面存状态）。",
    ) + "\n"


def wide_folder(place: Path | str) -> bool:
    """A folder too wide to let a worker read all of: the root, the home folder and those above it, the shared
    temporary folders."""
    target = Path(place)
    home = Path.home()
    wide = [Path("/"), home, *home.parents, Path("/tmp"), Path("/var/tmp"), Path(tempfile.gettempdir())]
    if target.anchor:
        wide.append(Path(target.anchor))

    def spell(p: Path) -> set[str]:
        return {os.path.normcase(str(p.absolute())), os.path.normcase(str(p.resolve()))}

    return bool(spell(target) & set().union(*map(spell, wide)))


def _rule_path(path: str | Path) -> str:
    """Normalize a path for Claude Code `Read(...)`/`Write(...)` rules: forward slashes with a leading `//` for
    absolute filesystem paths (POSIX `/Users/...` -> `//Users/...`; Windows `C:\\Users\\...` -> `//C:/Users/...`)."""
    posix = Path(path).as_posix()
    return f"/{posix}" if posix.startswith("/") else f"//{posix}"


def _outside_reads_impl(
    repo: str | Path | None,
    *briefs: str | Path | None,
    herdr_docs: Path | str | None = None,
) -> list[str]:
    docs = HERDR_DOCS if herdr_docs is None else Path(herdr_docs)
    places = [b if wide_folder(b.parent) else b.parent for b in (Path(x).absolute() for x in briefs if x)]
    out: list[str] = []
    for place in [*places, Path(repo) / "briefs" if repo else None, docs]:
        if place and place.exists():
            out += [p for p in dict.fromkeys((str(place.absolute()), str(place.resolve()))) if p not in out]
    return out


def outside_reads(
    repo: str | Path | None,
    *briefs: str | Path | None,
    herdr_docs: Path | str | None = None,
) -> list[str]:
    """What a worker reads outside its worktree: each brief's folder, the project's briefs/ (briefs and the
    screenshots they name) and Herdr's API docs. A brief kept in a wide folder (wide_folder) is let through alone,
    not its folder. Every spelling a read may arrive by: Claude Code follows no link."""
    return _outside_reads_impl(repo, *briefs, herdr_docs=herdr_docs)


_DEFAULT_OUTSIDE_READS = outside_reads


def read_settings(
    kind: str,
    paths: Iterable[str | Path],
    extra: Mapping[str, Any] | None = None,
    writes: Iterable[str | Path] = (),
    *,
    home: pmlib.home.Home | None = None,
    kinds: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """For Claude Code: `--settings <file>` that lets it read these folders without asking. permissions.allow
    Read rules: auto mode asks before a read outside the working directories, and an allow rule answers it. With
    permissions.blockReadsOutsideWorkingDirectories on, which no allow rule lifts, blockReadsExemptPaths lets the
    same folders through (Claude Code takes that key only from --settings). Reads only: the folders do not become
    working directories (--add-dir would let a worker in acceptEdits write there) and no Edit or Write rule is added,
    except for explicit single-file `writes` (used only for a helper's own conclusion file).
    A file, not the JSON itself: a short command line. The herdr terminal UI quotes each argument as it types the
    command into a shell (a path with spaces arrives whole), so the path is passed as it is, never quoted here.
    Other programs ask about no such reads. extra: more settings for the same file (native_memory's)."""
    table = base_mod.agent_kinds() if kinds is None else kinds
    program = Path(((table.get(kind) or {}).get("argv") or [""])[0]).name
    extra_dict = dict(extra or {})
    r_paths = [str(p) for p in paths or ()]
    w_paths: list[str] = []
    for w in writes or ():
        if w:
            pw = Path(w)
            for s in dict.fromkeys((str(pw.absolute()), str(pw.resolve()))):
                if s not in w_paths:
                    w_paths.append(s)
    if not (r_paths or w_paths or extra_dict) or program != "claude":
        return []
    allow = [f"Read({_rule_path(p)}/**)" if Path(p).is_dir() else f"Read({_rule_path(p)})" for p in r_paths]
    for w in w_paths:
        allow.append(f"Read({_rule_path(w)})")
        allow.append(f"Write({_rule_path(w)})")
    allow = list(dict.fromkeys(allow))
    exempt = list(dict.fromkeys([*r_paths, *(str(Path(w).parent) for w in w_paths)]))
    perms = {"permissions": {"allow": allow, "blockReadsExemptPaths": exempt}} if (r_paths or w_paths) else {}
    text = json.dumps({**perms, **extra_dict}, indent=1, ensure_ascii=False) + "\n"
    ledger_home = pmlib.home.current() if home is None else home
    path = ledger_home.reads / f"{hashlib.sha1(text.encode()).hexdigest()[:12]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_text() != text:
        path.write_text(text)
    return ["--settings", str(path)]
