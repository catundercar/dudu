"""Worker memory candidates (`projects/<slug>/memory/candidates/<worker>/`): `MemoryCandidates` over explicit
`Context`, plus legacy wrappers. Layer 2.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..context import Context
from ..errors import Refused
from ..home import project_slug
from ..ledger.ledger import Ledger, slugify
from ..ledger.task import ACTIVE
from .layer import MemoryLayer, read_memory


CANDIDATE_GRACE = 600  # seconds a new, empty candidates folder is left for the worker that is starting


@dataclass(frozen=True)
class AdoptResult:
    """Outcome of adopting or dropping a worker memory candidate."""

    worker: str
    source_name: str
    dropped: bool
    memory: dict[str, Any] | None = None
    notes: tuple[str, ...] = ()


def candidate_names_of(task: dict[str, Any]) -> set[str]:
    return {
        slugify(str(task.get(k) or "").rsplit("/", 1)[-1])
        for k in ("agent", "name", "label", "branch", "id")
    } - {""}


class MemoryCandidates:
    """Worker candidate memories under `projects/<slug>/memory/candidates/<worker>/`."""

    def __init__(self, ctx: Context, repo: str | Path = "", *, slug: str | None = None) -> None:
        self.ctx = ctx
        self.repo = str(repo or "")
        resolved_slug = slug if slug else (ctx.store.folder_project_slug(repo) if repo else "")
        self._explicit_slug = slug or (resolved_slug if (resolved_slug and repo and resolved_slug != project_slug(repo)) else "")
        self.slug = resolved_slug

    @property
    def dir(self) -> Path:
        if self._explicit_slug:
            return self.ctx.home.project(self._explicit_slug).memory / "candidates"
        return self.ctx.home.memory_dir(self.repo) / "candidates"

    def list(self) -> list[tuple[str, dict[str, Any]]]:
        """What workers' own memory wrote, waiting to be adopted: [(worker's folder name, memory)]."""
        d = self.dir
        found = (
            [(p.parent.name, read_memory(p)) for p in sorted(d.glob("*/*.md")) if p.name != "MEMORY.md"]
            if d.is_dir() else []
        )
        return [(who, m) for who, m in found if m]

    def prune(self, keep: Iterable[str] = (), finished: Iterable[str] = ()) -> list[str]:
        """Remove empty `candidates/<worker>/` folders of finished/stale workers; returns removed folder names."""
        d = self.dir
        if not d.is_dir() or d.is_symlink():
            return []
        done = {slugify(str(n)) for n in finished} - {""}
        now_t = self.ctx.clock.time()
        empty: list[Path] = []
        for folder in sorted(d.iterdir()):
            with contextlib.suppress(OSError):
                if folder.is_symlink() or not folder.is_dir():
                    continue
                if any(f.name not in ("MEMORY.md", ".lock", ".DS_Store") for f in folder.iterdir()):
                    continue
                if folder.name in done or now_t - folder.stat().st_mtime >= CANDIDATE_GRACE:
                    empty.append(folder)
        if not empty:
            return []
        working = {slugify(str(n)) for n in keep} - {""}
        for t in Ledger(self.ctx).all_tasks():
            if t.get("status") in ACTIVE and t.get("repo") and project_slug(t["repo"]) == self.slug:
                working |= candidate_names_of(t)
        gone: list[str] = []
        for folder in empty:
            try:
                if folder.name in working:
                    continue
                for f in folder.iterdir():
                    f.unlink()
                folder.rmdir()
                gone.append(folder.name)
            except OSError:
                continue
        with contextlib.suppress(OSError):
            if not any(d.iterdir()):
                d.rmdir()
        return gone

    def adopt(
        self,
        candidate: str,
        *,
        writer: tuple[str, str],
        drop: bool = False,
        text: str | None = None,
        name: str | None = None,
        kind: str | None = None,
        topic: str | None = None,
        quote: str = "",
        verified: str = "",
    ) -> AdoptResult:
        """Adopt a worker candidate into project memory through `MemoryLayer.remember`, or drop it."""
        if writer[0] not in ("pm", "user"):
            raise Refused("candidates are the PM's to adopt")
        who, _, cand_name = candidate.rpartition("/")
        found = [(w, m) for w, m in self.list() if m["name"] == Path(cand_name).stem and who in ("", w)]
        if len(found) != 1:
            raise Refused(f"no single candidate called {candidate} (`pm.py memory --candidates` lists them)")
        who, m = found[0]
        layer = MemoryLayer(self.ctx, self.repo, slug=self._explicit_slug or None)
        kept: dict[str, Any] | None = None
        notes: list[str] = []
        if not drop:
            chosen_kind = kind or ("pitfall" if m["type"] == "project" and not quote else m["type"])
            if chosen_kind == "user":  # what Claude Code calls a user memory, saved by a worker, is a fact of this machine
                chosen_kind = "pitfall" if not quote else "feedback"
            kept, notes = layer.remember(
                text or m["description"],
                writer=writer,
                kind=chosen_kind,
                name=name or m["name"],
                quote=quote or "",
                verified=verified or "",
                body=m["body"],
                by=f"worker:{who}" if not quote else None,
                topic=topic,
                project_repo=self.repo,
            )
        Path(m["path"]).unlink(missing_ok=True)
        folder = Path(m["path"]).parent
        with contextlib.suppress(OSError):
            if not [f for f in folder.iterdir() if f.name not in ("MEMORY.md", ".lock", ".DS_Store")]:
                for f in folder.iterdir():
                    f.unlink()
                folder.rmdir()
        layer.write_index()
        return AdoptResult(worker=who, source_name=m["name"], dropped=bool(drop), memory=kept, notes=tuple(notes))


# ── Legacy module-level wrappers (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────

def candidates(repo: str | Path) -> list[tuple[str, dict[str, Any]]]:
    """What workers' own memory wrote, waiting to be adopted: [(worker's folder name, memory)]."""
    return MemoryCandidates(Context.from_env(), repo).list()


def prune_candidates(repo: str | Path, keep: Iterable[str] = (), finished: Iterable[str] = ()) -> list[str]:
    return MemoryCandidates(Context.from_env(), repo).prune(keep=keep, finished=finished)
