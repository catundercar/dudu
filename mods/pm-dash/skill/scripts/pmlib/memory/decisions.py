"""Project decisions (`projects/<slug>/decisions.md`): `Decisions` over explicit `Context`, plus legacy wrappers.
Layer 2."""
from __future__ import annotations

from pathlib import Path
import re

from ..context import Context
from .layer import MemoryLayer, alike, squash


QUOTED = re.compile(r" — (?:the user's words: \".*\"|用户原话：「.*」)\s*$")
DECISION_DATE_RE = re.compile(r"^-\s+\d{4}-\d{2}-\d{2}\s+")


class Decisions:
    """One project's `decisions.md` log and deduplication against active memory."""

    def __init__(self, ctx: Context, repo: str | Path) -> None:
        self.ctx = ctx
        self.repo = str(repo)

    @property
    def path(self) -> Path:
        return self.ctx.home.project_for(self.repo).decisions

    def lines(self) -> list[str]:
        """The lines of the project's decisions file, oldest first; none without one."""
        try:
            return [line for line in self.path.read_text().splitlines() if line.strip()]
        except OSError:
            return []

    def unremembered(self) -> list[str]:
        """Lines in decisions.md not already covered by active project or personal memory (`--once` always kept)."""
        lines = self.lines()
        if not lines:
            return []
        known = [
            m
            for layer in (MemoryLayer(self.ctx, self.repo), MemoryLayer(self.ctx, None))
            for m in layer.memories()
            if not layer.expired(m)
        ]
        kept: list[str] = []
        for line in lines:
            body = DECISION_DATE_RE.sub("", QUOTED.sub("", line).strip()).strip()
            if body.startswith("[once] "):
                kept.append(line)
                continue
            sq = squash(body)
            if not body or not any(
                alike(body, m["description"])
                or (len(sq) >= 6 and sq in squash(f"{m['description']} {m['body']}"))
                for m in known
            ):
                kept.append(line)
        return kept


def decision_lines(repo: str | Path) -> list[str]:
    """The lines of the project's decisions file, oldest first; none without one."""
    return Decisions(Context.from_env(), repo).lines()


def unremembered_decisions(repo: str | Path) -> list[str]:
    """Lines in decisions.md not already covered by active project or personal memory (`--once` always kept)."""
    return Decisions(Context.from_env(), repo).unremembered()
