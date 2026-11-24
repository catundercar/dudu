"""Question card options and recommendation markers: pure rules over CLI answer flags. Layer 2."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

from ..errors import Refused

_RECOMMEND_MARKER = re.compile(r"\s*(?:\(recommended\)|\[recommended\]|（推荐）|\[推荐\])\s*$", re.IGNORECASE)


def strip_recommend_marker(text: Any) -> tuple[str, bool]:
    """Strip a trailing `(Recommended)` / `（推荐）` / `[Recommended]` / `[推荐]` marker from an option label.
    Returns `(clean_label, marked)`. Never empties a label that consists solely of the marker."""
    s = str(text or "").strip()
    if not s:
        return "", False
    cleaned = _RECOMMEND_MARKER.sub("", s).strip()
    if cleaned and cleaned != s:
        return cleaned, True
    return s, False


@dataclass(frozen=True)
class QuestionCard:
    """Validated question-card options and recommendation metadata."""

    options: tuple[str, ...] = ()
    option_notes: tuple[str, ...] = ()
    recommended: bool = False
    recommended_index: int | None = None

    @classmethod
    def from_inputs(
        cls,
        options: Sequence[str] | None = None,
        why: Mapping[int, str] | None = None,
        recommend: bool = False,
    ) -> QuestionCard:
        raw = [str(o).strip() for o in (options or [])]
        why_map = {i: (text or "").strip() for i, text in (why or {}).items()}
        parsed = [strip_recommend_marker(o) for o in raw]
        marked_raw = next((i for i, (title, marked) in enumerate(parsed) if title and marked), None)
        if recommend and marked_raw is None and not (raw and raw[0]):
            raise Refused("--recommend marks the first answer as your pick: give that answer with --option")
        if any(text and not (i < len(raw) and raw[i]) for i, text in why_map.items()):
            raise Refused("--why explains the --option before it, and that one is empty")
        kept = [i for i, (title, _) in enumerate(parsed) if title]
        titles = tuple(parsed[i][0] for i in kept)
        notes = tuple(why_map.get(i, "") for i in kept) if any(why_map.get(i) for i in kept) else ()
        rec_idx = kept.index(marked_raw) if marked_raw is not None and marked_raw in kept else (0 if recommend and titles else None)
        return cls(
            options=titles,
            option_notes=notes,
            recommended=rec_idx is not None,
            recommended_index=rec_idx if (rec_idx is not None and rec_idx > 0) else None,
        )

    def to_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {"options": list(self.options)} if self.options else {}
        if self.option_notes:
            fields["option_notes"] = list(self.option_notes)
        if self.recommended:
            fields["recommended"] = True
            if self.recommended_index is not None and self.recommended_index > 0:
                fields["recommended_index"] = self.recommended_index
        return fields


def quick_answers(a: Any) -> tuple[list[str], dict[str, Any]]:
    """The answers a question offers: (titles, fields for the task and its conversation event).
    --why gives the --option before it one line of explanation; --recommend marks the first answer as
    recommended (or an inline `(Recommended)` / `（推荐）` suffix on any --option marks that answer and
    is stripped from its stored text). An answer is kept as written, and it alone is what a pick sends back."""
    card = QuestionCard.from_inputs(
        options=getattr(a, "option", None),
        why=getattr(a, "why", None),
        recommend=bool(getattr(a, "recommend", False)),
    )
    return list(card.options), card.to_fields()


QUESTION_FIELDS = ("options", "option_notes", "recommended", "recommended_index")
