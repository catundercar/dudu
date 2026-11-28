"""A project's conversation log, projects/<slug>/conversation.jsonl: `Conversation` domain object plus legacy wrappers
for appending an event, reading them all, reading what came after a byte offset, and the last exchanges between the
user and the PM. Layer 2."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..context import Context
from ..home import project_slug
from ..osutil import clip
from ..store import _stamp_to_ms, file_lock, local_tz_offset, lock_file, replace_task_file, unlock_file, valid_slug, write_atomic


RECEIPT_LIMIT = 50
RECEIPT_TEXT_LIMIT = 4000


def read_receipts(path: str | Path) -> list[dict[str, Any]]:
    """Recent PM user-message receipts at `path`, oldest first; empty when absent or unreadable."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("receipts") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    return [r for r in items if isinstance(r, dict) and r.get("at") and (r.get("text") or r.get("digest"))]


def conversation_events(path: str | Path) -> list[dict[str, Any]]:
    """The events of the conversation log at `path`, oldest first; none when it cannot be read."""
    try:  # lines end at "\n" only: the user's words may hold U+2028 and the like, which splitlines() also breaks at
        lines = Path(path).read_text(errors="replace").split("\n")
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):  # a stray `null` or `[]` line is not an event
            events.append(event)
    return events


class Conversation:
    """One project's conversation log (`projects/<slug>/conversation.jsonl`) over an explicit `Context`."""

    def __init__(self, ctx: Context, repo: str | Path = "", *, slug: str | None = None) -> None:
        self.ctx = ctx
        self.repo = str(repo) if repo else ""
        if slug and valid_slug(slug):
            self.slug = slug
        elif repo:
            self.slug = ctx.store.folder_project_slug(repo) or project_slug(repo)
        else:
            self.slug = "project"
        self.files = ctx.home.project(self.slug)

    @property
    def path(self) -> Path:
        return self.files.conversation

    def events_after(self, offset: int) -> tuple[int, list[tuple[int, dict[str, Any]]]]:
        """(end, [(start, event), ...]): the complete lines of the conversation log after byte offset, each with the
        byte it starts at, and the byte after the last of them. A half-written last line waits for the next look."""
        path = self.files.conversation
        size = path.stat().st_size if path.exists() else 0
        if size < offset:  # replaced by a shorter file: read it from the start
            offset = 0
        if size == offset:
            return offset, []
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(size - offset)
        out, at = [], offset
        for line in data[:data.rfind(b"\n") + 1].split(b"\n")[:-1]:
            try:
                event = json.loads(line)
            except ValueError:
                event = None
            if isinstance(event, dict):
                out.append((at, event))
            at += len(line) + 1
        return at, out

    def _record_impl(self, kind: str, at: str | None = None, **fields: Any) -> Any:
        try:
            stamp = at or self.ctx.clock.now_sec()
            extra = dict(fields)
            if kind in ("user", "pm", "agent"):
                now_ms = int(self.ctx.clock.time() * 1000)
                if "at_ms" not in extra:
                    extra["at_ms"] = now_ms if at is None else _stamp_to_ms(stamp, now_ms)
                if "tz" not in extra:
                    extra["tz"] = local_tz_offset(self.ctx.clock.datetime_now())
            return self.ctx.store.append_event(self.slug, {"at": stamp, "type": kind, **extra})
        except (OSError, TypeError, ValueError):
            return None

    def record(self, kind: str, at: str | None = None, **fields: Any) -> Any:
        """Append one event to the project's conversation log, projects/<project>/conversation.jsonl.

        Nothing may fail because of it, so errors are swallowed.
        """
        if getattr(self.ctx, "_legacy", False) and record is not _DEFAULT_RECORD:
            if at is None:
                return record(self.repo, kind, **fields)
            return record(self.repo, kind, at=at, **fields)
        return self._record_impl(kind, at=at, **fields)

    def events(self) -> list[dict[str, Any]]:
        """The events of the project's conversation log, oldest first."""
        return self.ctx.store.all_events(self.slug)

    def record_receipt(
        self,
        text: str,
        *,
        at: str | None = None,
        at_ms: int | None = None,
        pane: str = "",
        session: str = "",
        msg_id: str = "",
        msg_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Atomically record a receipt in projects/<slug>/receipts.json as soon as the PM receives a user prompt.

        Written before conversation.jsonl append so a frontend resend check sees PM receipt even if
        conversation.jsonl is delayed or fails to write. Errors are swallowed.
        """
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            self.files.ensure()
            stamp = at or self.ctx.clock.now_sec()
            ms = int(at_ms) if at_ms is not None else int(self.ctx.clock.time() * 1000)
            norm = " ".join(raw.split())
            digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()
            truncated = len(raw) > RECEIPT_TEXT_LIMIT
            entry: dict[str, Any] = {
                "at": stamp,
                "at_ms": ms,
                "digest": digest,
                "len": len(norm),
                "text": raw[:RECEIPT_TEXT_LIMIT] if truncated else raw,
            }
            if truncated:
                entry["truncated"] = True
            if pane:
                entry["pane"] = pane
            if session:
                entry["session"] = session
            if msg_id:
                entry["msg_id"] = str(msg_id)
            if msg_ids:
                clean_ids = [str(x) for x in msg_ids if x]
                if clean_ids:
                    entry["msg_ids"] = clean_ids
            lock_path = self.files.receipts_lock
            with file_lock(lock_path, timeout=5.0, lock_fn=lock_file, unlock_fn=unlock_file):
                existing = read_receipts(self.files.receipts)
                existing.append(entry)
                payload = (json.dumps({"receipts": existing[-RECEIPT_LIMIT:]}, ensure_ascii=False) + "\n").encode("utf-8")
                write_atomic(self.files.receipts, payload, replace_fn=replace_task_file)
            return entry
        except (OSError, TypeError, ValueError):
            return None

    def receipts(self) -> list[dict[str, Any]]:
        """Recent user-message receipts for this project, oldest first."""
        return read_receipts(self.files.receipts)

    def tail(self, turns: int = 6, width: int = 700) -> list[dict[str, str]]:
        """The last exchanges in the conversation log: what the user said and the PM's reply to it.

        The reply to a user turn is the first `pm` event after it. Later ones answer something else (a finished
        background wait, the next session taking over), and so does any reply after an `agent` event. What the user said
        again before that reply (words a turn took in while it worked) is one exchange with what came first.
        """
        out: list[dict[str, str]] = []
        awaiting_reply = False
        for event in self.events():
            kind = event.get("type")
            if kind == "user" and awaiting_reply:
                # Words said before the reply came (taken in while the turn worked, or after a stopped turn): one reply
                # answers them all.
                out[-1]["user"] += "\n" + str(event.get("text") or "")
            elif kind == "user":
                out.append({"user": str(event.get("text") or ""), "pm": ""})
                awaiting_reply = True
            elif kind == "agent" and not event.get("wake"):  # one with `wake` is written where it was sent, not read
                awaiting_reply = False
            elif kind == "pm" and event.get("after") == "deliver":
                pass  # the reply to a batch of events
            elif kind == "pm" and awaiting_reply and not event.get("notice"):  # a notice of rotate's answers nothing
                out[-1]["pm"] = str(event.get("text") or "")
                awaiting_reply = False
        return [{"user": clip(t["user"], width), "pm": clip(t["pm"], width)} for t in out[-turns:]]

    def turn_cause(self) -> dict[str, Any]:
        """{"after": "deliver", "batch": [start, end]} when the turn ending now was started by a delivered batch."""
        try:
            snap = json.loads(self.files.pm_turn.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            snap = None
        if isinstance(snap, dict):
            turn = snap.get("turn")
            if isinstance(turn, dict):
                phase = str(turn.get("phase") or "idle")
                if phase not in ("idle", "offline", "starting"):
                    cause_obj = turn.get("cause")
                    if isinstance(cause_obj, dict):
                        kind = str(cause_obj.get("kind") or "")
                        if kind == "deliver":
                            batch = cause_obj.get("batch")
                            return {"after": "deliver", **({"batch": list(batch)} if isinstance(batch, list) else {})}
                        if kind:
                            return {}
        # 1-version read-only fallback for unupgraded peers/migrations (§4.8).
        try:
            cause = json.loads(self.files.turn_cause.read_text())
        except (OSError, ValueError):
            return {}
        return {k: cause[k] for k in ("after", "batch") if k in cause} if isinstance(cause, dict) else {}


def events_after(repo: str | Path, offset: int) -> tuple[int, list[tuple[int, dict[str, Any]]]]:
    """(end, [(start, event), ...]): the complete lines of the conversation log after byte offset."""
    return Conversation(Context.from_env(), repo).events_after(offset)


def record(repo: str | Path, kind: str, at: str | None = None, **fields: Any) -> Any:
    """Append one event to the project's conversation log, projects/<project>/conversation.jsonl."""
    return Conversation(Context.from_env(), repo)._record_impl(kind, at=at, **fields)


_DEFAULT_RECORD = record


def conversation(repo: str | Path) -> list[dict[str, Any]]:
    """The events of the project's conversation log, oldest first."""
    return Conversation(Context.from_env(), repo).events()


def log_tail(repo: str | Path, turns: int = 6, width: int = 700) -> list[dict[str, str]]:
    """The last exchanges in the conversation log: what the user said and the PM's reply to it."""
    return Conversation(Context.from_env(), repo).tail(turns=turns, width=width)


def turn_cause(repo: str | Path) -> dict[str, Any]:
    """{"after": "deliver", "batch": [start, end]} when the turn ending now was started by a delivered batch."""
    return Conversation(Context.from_env(), repo).turn_cause()
