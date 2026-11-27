"""Append-only segmented `MailboxStore`, monotonic `seq`, per-endpoint `typist.lock`, crash recovery (C1-C5),
and one-time legacy `pm-turn.json` / `inbox/*.jsonl` migration (§2.2-2.5, §9.2). Layer 2.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Mapping, Sequence

from ..errors import StoreError
from ..store import file_lock, lock_file, unlock_file, write_atomic
from ..terminals.events import replace_task_file
from .address import LogicalAddress
from .envelope import (
    P1_USER,
    P4_BATCH,
    TERMINAL_DELIVERY_STATES,
    TERMINAL_REPORT_STATES,
    Envelope,
    new_env_id,
)
from .principal import Principal

SEGMENT_MAX_BYTES = 2 << 20
RECENT_KEYS_LIMIT = 2048
RECENT_COMPLETED_LIMIT = 64
# A hook marks what it just read for the turn it is starting; that turn binds it (`TurnTracker.begin_turn`).
PENDING_TURN = "pending"
PENDING_TURN_STALE_MS = 120_000
_SEG_NAME_RE = re.compile(r"^mailbox\.(\d{4,})\.jsonl$")

VALID_DELIVERY_TRANSITIONS: dict[str, frozenset[str]] = {
    "accepted": frozenset({"accepted", "typed", "consumed", "answered", "failed", "expired", "superseded"}),
    "typed": frozenset({"accepted", "typed", "consumed", "answered", "failed", "expired", "superseded"}),
    "consumed": frozenset({"accepted", "consumed", "answered", "failed", "expired", "superseded"}),
    "answered": frozenset({"answered"}),
    "failed": frozenset({"accepted", "failed", "superseded"}),
    "expired": frozenset({"expired"}),
    "superseded": frozenset({"superseded"}),
}

VALID_REPORT_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"queued", "accepted", "applied", "rejected"}),
    "accepted": frozenset({"accepted", "applied", "rejected"}),
    "applied": frozenset({"applied"}),
    "rejected": frozenset({"rejected"}),
}


@dataclass(frozen=True)
class MailboxItem:
    """Materialized item inside a `MailboxStore`."""

    seq: int
    envelope: Envelope
    state: str
    attempts: int
    accepted_ms: int
    updated_ms: int
    target_endpoint_uid: str = ""
    bound_turn_id: str = ""
    last_error: str = ""
    hold_reason: str = ""
    intent: dict[str, Any] | None = None
    typed_ms: int = 0
    consumed_ms: int = 0
    answered_ms: int = 0
    endpoint_epoch: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def is_terminal(self) -> bool:
        if self.envelope.kind.startswith("report."):
            return self.state in TERMINAL_REPORT_STATES
        return self.state in TERMINAL_DELIVERY_STATES

    def next_attempt(self) -> int:
        if self.meta.get("attempts_preincremented") and self.attempts > 0:
            return int(self.attempts)
        return int(self.attempts) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": int(self.seq),
            "envelope": self.envelope.to_dict(),
            "state": self.state,
            "attempts": int(self.attempts),
            "accepted_ms": int(self.accepted_ms),
            "updated_ms": int(self.updated_ms),
            "target_endpoint_uid": self.target_endpoint_uid,
            "bound_turn_id": self.bound_turn_id,
            "last_error": self.last_error,
            "hold_reason": self.hold_reason,
            "intent": dict(self.intent) if isinstance(self.intent, Mapping) else None,
            "typed_ms": int(self.typed_ms),
            "consumed_ms": int(self.consumed_ms),
            "answered_ms": int(self.answered_ms),
            "endpoint_epoch": int(self.endpoint_epoch),
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MailboxItem:
        raw_env = data.get("envelope")
        env = raw_env if isinstance(raw_env, Envelope) else Envelope.from_dict(
            raw_env if isinstance(raw_env, Mapping) else {}
        )
        intent_raw = data.get("intent")
        meta_raw = data.get("meta")
        return cls(
            seq=int(data.get("seq") or 0),
            envelope=env,
            state=str(data.get("state") or "accepted"),
            attempts=int(data.get("attempts") or 0),
            accepted_ms=int(data.get("accepted_ms") or env.created_ms or 0),
            updated_ms=int(data.get("updated_ms") or env.created_ms or 0),
            target_endpoint_uid=str(data.get("target_endpoint_uid") or ""),
            bound_turn_id=str(data.get("bound_turn_id") or ""),
            last_error=str(data.get("last_error") or ""),
            hold_reason=str(data.get("hold_reason") or ""),
            intent=dict(intent_raw) if isinstance(intent_raw, Mapping) else None,
            typed_ms=int(data.get("typed_ms") or 0),
            consumed_ms=int(data.get("consumed_ms") or 0),
            answered_ms=int(data.get("answered_ms") or 0),
            endpoint_epoch=int(data.get("endpoint_epoch") or 0),
            meta=dict(meta_raw) if isinstance(meta_raw, Mapping) else {},
        )


def _segment_num(name: str) -> int:
    m = _SEG_NAME_RE.match(name)
    return int(m.group(1)) if m else 0


def _segment_name(num: int) -> str:
    return f"mailbox.{num:04d}.jsonl"


def _sanitize_uid_filename(uid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(uid or "endpoint")).strip("._") or "endpoint"


class MailboxStore:
    """Append-only segmented mailbox stream with monotonic `seq`, crash-safe replay, and typist leases."""

    def __init__(
        self,
        root: Path | str,
        *,
        clock: Any = None,
        segment_max_bytes: int = SEGMENT_MAX_BYTES,
        archive_keep: int = 2,
        lock_timeout: float = 10.0,
        typist_dir: Path | str | None = None,
    ) -> None:
        self.root = Path(root)
        self._clock = clock
        self.segment_max_bytes = max(256, int(segment_max_bytes))
        self.archive_keep = max(0, int(archive_keep))
        self.lock_path = self.root / "mailbox.lock"
        self.state_path = self.root / "mailbox.state.json"
        self.lock_timeout = lock_timeout
        # The typist lease guards a terminal, not a mailbox: every mailbox that can type into the same endpoint
        # must share one lease directory (`Home.typists`), or two typists interleave keystrokes (single typist).
        self.typist_dir = Path(typist_dir) if typist_dir is not None else self.root

    def _now_ms(self) -> int:
        if self._clock is not None:
            return int(float(self._clock.time()) * 1000)
        return int(time.time() * 1000)

    def _segments(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        found: list[tuple[int, Path]] = []
        try:
            with os.scandir(self.root) as it:
                for entry in it:
                    num = _segment_num(entry.name)
                    if num > 0 and entry.is_file():
                        found.append((num, Path(entry.path)))
        except OSError:
            return []
        found.sort(key=lambda pair: pair[0])
        return [p for _, p in found]

    @staticmethod
    def _truncate_partial_tail_unlocked(seg_path: Path) -> int:
        """C1 recovery: discard any incomplete trailing line without a newline or valid JSON."""
        if not seg_path.is_file():
            return 0
        with open(seg_path, "r+b") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return 0
            f.seek(0)
            data = f.read()
        last_nl = data.rfind(b"\n")
        if last_nl < 0:
            with open(seg_path, "r+b") as f:
                f.truncate(0)
            return 0
        valid_end = last_nl + 1
        # Verify the final complete line parses as JSON; if corrupt, roll back to previous newline.
        prev_nl = data.rfind(b"\n", 0, last_nl)
        line_start = prev_nl + 1 if prev_nl >= 0 else 0
        last_line = data[line_start:last_nl]
        if last_line.strip():
            try:
                obj = json.loads(last_line.decode("utf-8"))
                if not isinstance(obj, dict):
                    raise ValueError("non-dict line")
            except (UnicodeDecodeError, ValueError):
                valid_end = line_start
        if valid_end != size:
            with open(seg_path, "r+b") as f:
                f.truncate(valid_end)
        return valid_end

    def _default_snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "last_seq": 0,
            "segment": _segment_name(1),
            "byte_offset": 0,
            "acked_seq": 0,
            "active": {},
            "recent_keys": {},
            "recent_completed": {},
            "segment_bounds": {},
            "legacy_migrated": False,
        }

    def _read_snapshot_unlocked(self) -> tuple[dict[str, Any], bool]:
        if not self.state_path.is_file():
            return self._default_snapshot(), False
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return self._default_snapshot(), True
        except (OSError, ValueError):
            return self._default_snapshot(), True
        snap = self._default_snapshot()
        snap.update({
            "last_seq": int(raw.get("last_seq") or 0),
            "segment": str(raw.get("segment") or _segment_name(1)),
            "byte_offset": max(0, int(raw.get("byte_offset") or 0)),
            "acked_seq": max(0, int(raw.get("acked_seq") or 0)),
            "active": dict(raw.get("active") or {}) if isinstance(raw.get("active"), Mapping) else {},
            "recent_keys": dict(raw.get("recent_keys") or {}) if isinstance(raw.get("recent_keys"), Mapping) else {},
            "recent_completed": dict(raw.get("recent_completed") or {}) if isinstance(raw.get("recent_completed"), Mapping) else {},
            "segment_bounds": dict(raw.get("segment_bounds") or {}) if isinstance(raw.get("segment_bounds"), Mapping) else {},
            "legacy_migrated": bool(raw.get("legacy_migrated")),
        })
        return snap, False

    def _write_snapshot_unlocked(self, snap: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        out = dict(snap)
        recent_keys = dict(out.get("recent_keys") or {})
        if len(recent_keys) > RECENT_KEYS_LIMIT:
            keep = list(recent_keys.items())[-RECENT_KEYS_LIMIT:]
            out["recent_keys"] = dict(keep)
        recent_completed = dict(out.get("recent_completed") or {})
        if len(recent_completed) > RECENT_COMPLETED_LIMIT:
            ordered = sorted(
                recent_completed.items(),
                key=lambda kv: int((kv[1] or {}).get("updated_ms") or 0),
            )[-RECENT_COMPLETED_LIMIT:]
            out["recent_completed"] = dict(ordered)
        payload = (json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8")
        write_atomic(self.state_path, payload, replace_fn=replace_task_file)

    @staticmethod
    def _apply_record_to_snapshot(snap: dict[str, Any], rec: Mapping[str, Any], seg_name: str) -> None:
        seq = int(rec.get("seq") or 0)
        if seq > int(snap.get("last_seq") or 0):
            snap["last_seq"] = seq
        bounds = snap.setdefault("segment_bounds", {})
        if seg_name not in bounds:
            bounds[seg_name] = {"min_seq": seq, "max_seq": seq}
        else:
            b = bounds[seg_name]
            if seq > 0:
                b["min_seq"] = min(int(b.get("min_seq") or seq), seq)
                b["max_seq"] = max(int(b.get("max_seq") or seq), seq)

        rtype = str(rec.get("rec") or "")
        at_ms = int(rec.get("at_ms") or 0)
        if rtype == "seg":
            return

        if rtype == "enq":
            raw_env = rec.get("env")
            if not isinstance(raw_env, Mapping):
                return
            env = Envelope.from_dict(raw_env)
            state = str(rec.get("state") or "accepted")
            item = MailboxItem(
                seq=seq,
                envelope=env,
                state=state,
                attempts=int(rec.get("attempts") or 0),
                accepted_ms=at_ms or env.created_ms,
                updated_ms=at_ms or env.created_ms,
                target_endpoint_uid=str(rec.get("target_endpoint_uid") or ""),
                hold_reason=str(rec.get("hold_reason") or ""),
                endpoint_epoch=int(rec.get("endpoint_epoch") or 0),
                meta=dict(rec.get("meta") or {}) if isinstance(rec.get("meta"), Mapping) else {},
            )
            item_dict = item.to_dict()
            if item.is_terminal():
                snap["active"].pop(env.env_id, None)
                snap["recent_completed"][env.env_id] = item_dict
            else:
                snap["active"][env.env_id] = item_dict
            if env.idempotency_key:
                snap["recent_keys"][env.idempotency_key] = {
                    "env_id": env.env_id,
                    "seq": seq,
                    "state": state,
                    "kind": env.kind,
                }
            return

        env_id = str(rec.get("env_id") or "")
        if not env_id:
            return
        cur_dict = snap["active"].get(env_id) or snap["recent_completed"].get(env_id)
        if not isinstance(cur_dict, dict):
            return
        item = MailboxItem.from_dict(cur_dict)

        if rtype == "intent":
            intent_obj = {
                "env_id": env_id,
                "seq": seq,
                "at_ms": at_ms,
                "attempt": int(rec.get("attempt") or item.next_attempt()),
                "pre_turn": int(rec.get("pre_turn") or 0),
                "pre_status_ms": int(rec.get("pre_status_ms") or 0),
                "pre_working": bool(rec.get("pre_working")),
                "endpoint_uid": str(rec.get("endpoint_uid") or item.target_endpoint_uid or ""),
            }
            updated = MailboxItem(
                seq=item.seq,
                envelope=item.envelope,
                state=item.state,
                attempts=item.attempts,
                accepted_ms=item.accepted_ms,
                updated_ms=max(item.updated_ms, at_ms),
                target_endpoint_uid=intent_obj["endpoint_uid"] or item.target_endpoint_uid,
                bound_turn_id=item.bound_turn_id,
                last_error=item.last_error,
                hold_reason=item.hold_reason,
                intent=intent_obj,
                typed_ms=item.typed_ms,
                consumed_ms=item.consumed_ms,
                answered_ms=item.answered_ms,
                endpoint_epoch=item.endpoint_epoch,
                meta=item.meta,
            )
            if updated.is_terminal():
                snap["recent_completed"][env_id] = updated.to_dict()
            else:
                snap["active"][env_id] = updated.to_dict()
            return

        if rtype == "hold":
            updated = MailboxItem(
                seq=item.seq,
                envelope=item.envelope,
                state=item.state,
                attempts=item.attempts,
                accepted_ms=item.accepted_ms,
                updated_ms=max(item.updated_ms, at_ms),
                target_endpoint_uid=str(rec.get("target_endpoint_uid") or item.target_endpoint_uid),
                bound_turn_id=item.bound_turn_id,
                last_error=item.last_error,
                hold_reason=str(rec.get("hold_reason") or ""),
                intent=None if rec.get("clear_intent") else item.intent,
                typed_ms=item.typed_ms,
                consumed_ms=item.consumed_ms,
                answered_ms=item.answered_ms,
                endpoint_epoch=item.endpoint_epoch,
                meta=item.meta,
            )
            if updated.is_terminal():
                snap["recent_completed"][env_id] = updated.to_dict()
            else:
                snap["active"][env_id] = updated.to_dict()
            return

        if rtype == "st":
            to_state = str(rec.get("to") or item.state)
            attempts = int(rec.get("attempts")) if rec.get("attempts") is not None else item.attempts
            target_uid = str(rec.get("target_endpoint_uid") or item.target_endpoint_uid)
            bound_turn = str(rec.get("turn_id") if rec.get("turn_id") is not None else item.bound_turn_id)
            last_error = str(rec.get("error") if rec.get("error") is not None else item.last_error)
            hold_reason = str(rec.get("hold_reason") if rec.get("hold_reason") is not None else (
                "" if to_state in ("typed", "consumed", "answered") else item.hold_reason
            ))
            typed_ms = 0 if to_state == "accepted" else (
                at_ms if (to_state == "typed" and item.state != "typed") else (item.typed_ms or (at_ms if to_state == "typed" else 0))
            )
            consumed_ms = 0 if to_state == "accepted" else (item.consumed_ms or (at_ms if to_state == "consumed" else 0))
            answered_ms = item.answered_ms or (at_ms if to_state in ("answered", "applied") else 0)
            ep_epoch = int(rec.get("endpoint_epoch") or item.endpoint_epoch or 0)
            if to_state == "accepted":
                bound_turn = ""
            meta = dict(item.meta)
            if isinstance(rec.get("meta"), Mapping):
                for mk, mv in rec["meta"].items():
                    if mv is None:
                        meta.pop(mk, None)
                    else:
                        meta[mk] = mv
            if to_state == "accepted":
                meta.pop("turn_opened_seq", None)
            updated = MailboxItem(
                seq=item.seq,
                envelope=item.envelope,
                state=to_state,
                attempts=attempts,
                accepted_ms=item.accepted_ms,
                updated_ms=max(item.updated_ms, at_ms),
                target_endpoint_uid=target_uid,
                bound_turn_id=bound_turn,
                last_error=last_error,
                hold_reason=hold_reason,
                intent=None if to_state != item.state or rec.get("clear_intent") else item.intent,
                typed_ms=typed_ms,
                consumed_ms=consumed_ms,
                answered_ms=answered_ms,
                endpoint_epoch=ep_epoch,
                meta=meta,
            )
            upd_dict = updated.to_dict()
            if updated.is_terminal():
                snap["active"].pop(env_id, None)
                snap["recent_completed"][env_id] = upd_dict
            else:
                snap["recent_completed"].pop(env_id, None)
                snap["active"][env_id] = upd_dict
            if item.envelope.idempotency_key:
                snap["recent_keys"][item.envelope.idempotency_key] = {
                    "env_id": env_id,
                    "seq": item.seq,
                    "state": to_state,
                    "kind": item.envelope.kind,
                }

    def _catch_up_unlocked(self) -> tuple[dict[str, Any], bool]:
        """Replay any JSONL records past `snapshot.(segment, byte_offset)` (C1/C2 recovery)."""
        snap, needs_save = self._read_snapshot_unlocked()
        segments = self._segments()
        if not segments:
            return snap, False

        cur_seg_name = str(snap.get("segment") or _segment_name(1))
        cur_num = _segment_num(cur_seg_name)
        start_off = int(snap.get("byte_offset") or 0)

        # If state.json was missing or corrupted, replay all segments from offset 0.
        if needs_save or not self.state_path.is_file():
            snap = self._default_snapshot()
            cur_num = 0
            start_off = 0
            needs_save = True

        for seg_path in segments:
            seg_num = _segment_num(seg_path.name)
            if seg_num < cur_num:
                continue
            valid_end = self._truncate_partial_tail_unlocked(seg_path)
            off = start_off if seg_num == cur_num else 0
            if off > valid_end:
                off = 0
            if valid_end > off:
                with open(seg_path, "rb") as f:
                    f.seek(off)
                    chunk = f.read(valid_end - off)
                for raw_line in chunk.split(b"\n"):
                    if not raw_line.strip():
                        continue
                    try:
                        rec = json.loads(raw_line.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        continue
                    if isinstance(rec, Mapping):
                        self._apply_record_to_snapshot(snap, rec, seg_path.name)
                        needs_save = True
            snap["segment"] = seg_path.name
            snap["byte_offset"] = valid_end
            start_off = 0
            cur_num = seg_num

        if needs_save:
            self._write_snapshot_unlocked(snap)
        return snap, needs_save

    def _append_record_unlocked(self, snap: dict[str, Any], rec: Mapping[str, Any]) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        segments = self._segments()
        if not segments:
            seg_path = self.root / _segment_name(1)
            seg_num = 1
        else:
            seg_path = segments[-1]
            seg_num = _segment_num(seg_path.name)

        next_seq = int(snap.get("last_seq") or 0) + 1
        payload_rec = dict(rec)
        payload_rec["seq"] = next_seq
        line_bytes = (json.dumps(payload_rec, ensure_ascii=False) + "\n").encode("utf-8")

        cur_size = seg_path.stat().st_size if seg_path.is_file() else 0
        if cur_size > 0 and cur_size + len(line_bytes) > self.segment_max_bytes:
            prev_last = int(snap.get("last_seq") or 0)
            seg_num += 1
            seg_path = self.root / _segment_name(seg_num)
            seg_hdr = {
                "rec": "seg",
                "seq": next_seq,
                "prev_last_seq": prev_last,
                "at_ms": int(rec.get("at_ms") or self._now_ms()),
            }
            hdr_bytes = (json.dumps(seg_hdr, ensure_ascii=False) + "\n").encode("utf-8")
            with open(seg_path, "ab") as f:
                f.write(hdr_bytes)
                f.flush()
                os.fsync(f.fileno())
            self._apply_record_to_snapshot(snap, seg_hdr, seg_path.name)
            next_seq += 1
            payload_rec["seq"] = next_seq
            line_bytes = (json.dumps(payload_rec, ensure_ascii=False) + "\n").encode("utf-8")

        with open(seg_path, "ab") as f:
            f.write(line_bytes)
            f.flush()
            os.fsync(f.fileno())
            end_off = f.tell()

        self._apply_record_to_snapshot(snap, payload_rec, seg_path.name)
        snap["segment"] = seg_path.name
        snap["byte_offset"] = end_off
        self._compact_archives_unlocked(snap)
        self._write_snapshot_unlocked(snap)
        return payload_rec

    def _compact_archives_unlocked(self, snap: dict[str, Any]) -> None:
        """Delete old segments once all items inside are terminal and below `acked_seq`, keeping `archive_keep`."""
        segments = self._segments()
        if len(segments) <= self.archive_keep + 1:
            return
        active_seqs = {
            int(v.get("seq") or 0)
            for v in (snap.get("active") or {}).values()
            if isinstance(v, Mapping)
        }
        acked_seq = int(snap.get("acked_seq") or 0)
        bounds = snap.get("segment_bounds") or {}
        cur_seg = str(snap.get("segment") or "")
        eligible: list[Path] = []
        for seg_path in segments[:-1]:
            if seg_path.name == cur_seg:
                continue
            b = bounds.get(seg_path.name) if isinstance(bounds, Mapping) else None
            if not isinstance(b, Mapping):
                continue
            max_seq = int(b.get("max_seq") or 0)
            min_seq = int(b.get("min_seq") or 0)
            if any(min_seq <= s <= max_seq for s in active_seqs):
                continue
            if acked_seq > 0 and max_seq > acked_seq:
                continue
            eligible.append(seg_path)
        if len(eligible) > self.archive_keep:
            to_remove = eligible[: len(eligible) - self.archive_keep]
            for seg_path in to_remove:
                with contextlib.suppress(OSError):
                    seg_path.unlink()
                if isinstance(bounds, dict):
                    bounds.pop(seg_path.name, None)

    def _lookup_by_key_unlocked(self, snap: Mapping[str, Any], idem_key: str) -> MailboxItem | None:
        if not idem_key:
            return None
        rk = (snap.get("recent_keys") or {}).get(idem_key)
        if isinstance(rk, Mapping):
            env_id = str(rk.get("env_id") or "")
            raw = (snap.get("active") or {}).get(env_id) or (snap.get("recent_completed") or {}).get(env_id)
            if isinstance(raw, Mapping):
                return MailboxItem.from_dict(raw)
        for pool in ((snap.get("active") or {}), (snap.get("recent_completed") or {})):
            for raw in pool.values():
                if isinstance(raw, Mapping) and (raw.get("envelope") or {}).get("idempotency_key") == idem_key:
                    return MailboxItem.from_dict(raw)
        if isinstance(rk, Mapping):
            # Finished long enough ago to have left `recent_completed` (64 items, kept small: bodies can be large),
            # but still within the idempotency window (`recent_keys`, 2048 keys): a retry of it is a duplicate.
            return self._key_tombstone(idem_key, rk)
        return None

    @staticmethod
    def _key_tombstone(idem_key: str, rk: Mapping[str, Any]) -> MailboxItem:
        """A stand-in for an item known only by its idempotency key (its record was compacted away)."""
        env_id = str(rk.get("env_id") or f"gone:{idem_key}")
        kind = str(rk.get("kind") or ("chat.user" if idem_key.startswith("ui:") else "event.notify"))
        parts = idem_key.split(":")
        project = parts[1] if len(parts) > 2 and parts[1] else "compacted"
        env = Envelope(
            env_id=env_id,
            idempotency_key=idem_key,
            schema_version=1,
            created_ms=0,
            kind=kind,
            sender=Principal.supervisor(project),
            recipient=LogicalAddress.pm(project),
            project=project,
            cause={"kind": "compacted"},
            priority=P4_BATCH,
            body={},
        )
        meta = dict(rk.get("meta") or {}) if isinstance(rk.get("meta"), Mapping) else {}
        return MailboxItem(
            seq=int(rk.get("seq") or 0),
            envelope=env,
            state=str(rk.get("state") or "answered"),
            attempts=0,
            accepted_ms=0,
            updated_ms=0,
            meta={**meta, "compacted": True},
        )

    def enqueue(
        self,
        env: Envelope,
        *,
        initial_state: str = "accepted",
        now_ms: int | None = None,
        hold_reason: str = "",
        target_endpoint_uid: str = "",
        endpoint_epoch: int = 0,
        meta: Mapping[str, Any] | None = None,
    ) -> tuple[MailboxItem, bool]:
        """Idempotently enqueue `env` into this mailbox. Returns `(item, created)`."""
        ts = self._now_ms() if now_ms is None else int(now_ms)
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            if env.idempotency_key:
                existing = self._lookup_by_key_unlocked(snap, env.idempotency_key)
                if existing is not None:
                    return existing, False
            if env.env_id in (snap.get("active") or {}) or env.env_id in (snap.get("recent_completed") or {}):
                raw = (snap.get("active") or {}).get(env.env_id) or (snap.get("recent_completed") or {})[env.env_id]
                return MailboxItem.from_dict(raw), False
            rec: dict[str, Any] = {
                "rec": "enq",
                "at_ms": ts,
                "env": env.to_dict(),
                "state": initial_state,
                "attempts": 0,
                "target_endpoint_uid": target_endpoint_uid,
                "hold_reason": hold_reason,
                "endpoint_epoch": int(endpoint_epoch or 0),
            }
            if meta:
                rec["meta"] = dict(meta)
            self._append_record_unlocked(snap, rec)
            raw = (snap.get("active") or {}).get(env.env_id) or (snap.get("recent_completed") or {})[env.env_id]
            return MailboxItem.from_dict(raw), True

    def transition(self, env_id: str, to_state: str, *, now_ms: int | None = None, **meta: Any) -> MailboxItem:
        """Transition `env_id` to `to_state` under `mailbox.lock` and return the updated `MailboxItem`."""
        ts = self._now_ms() if now_ms is None else int(now_ms)
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            raw = (snap.get("active") or {}).get(env_id) or (snap.get("recent_completed") or {}).get(env_id)
            if not isinstance(raw, Mapping):
                raise KeyError(f"unknown envelope {env_id!r}")
            cur = MailboxItem.from_dict(raw)
            allowed_map = (
                VALID_REPORT_TRANSITIONS if cur.envelope.kind.startswith("report.") else VALID_DELIVERY_TRANSITIONS
            )
            allowed = allowed_map.get(cur.state, frozenset())
            if to_state not in allowed:
                raise StoreError(f"illegal mailbox transition for {env_id}: {cur.state!r} -> {to_state!r}")
            rec: dict[str, Any] = {
                "rec": "st",
                "at_ms": ts,
                "env_id": env_id,
                "from": cur.state,
                "to": to_state,
            }
            for k in ("attempts", "turn_id", "error", "hold_reason", "target_endpoint_uid", "endpoint_epoch", "clear_intent"):
                if k in meta:
                    rec[k] = meta[k]
            extra_meta = meta.get("meta")
            if isinstance(extra_meta, Mapping):
                rec["meta"] = dict(extra_meta)
            self._append_record_unlocked(snap, rec)
            updated = (snap.get("active") or {}).get(env_id) or (snap.get("recent_completed") or {})[env_id]
            return MailboxItem.from_dict(updated)

    def update_hold_reason(
        self,
        env_id: str,
        hold_reason: str,
        *,
        now_ms: int | None = None,
        clear_intent: bool = False,
    ) -> MailboxItem | None:
        ts = self._now_ms() if now_ms is None else int(now_ms)
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            raw = (snap.get("active") or {}).get(env_id)
            if not isinstance(raw, Mapping):
                return None
            if str(raw.get("hold_reason") or "") == str(hold_reason or "") and not (clear_intent and raw.get("intent")):
                return MailboxItem.from_dict(raw)
            rec: dict[str, Any] = {
                "rec": "hold",
                "at_ms": ts,
                "env_id": env_id,
                "hold_reason": str(hold_reason or ""),
            }
            if clear_intent:
                rec["clear_intent"] = True
            self._append_record_unlocked(snap, rec)
            updated = (snap.get("active") or {}).get(env_id) or (snap.get("recent_completed") or {}).get(env_id)
            return MailboxItem.from_dict(updated) if isinstance(updated, Mapping) else None

    def record_intent(
        self,
        env_id: str,
        *,
        pre_turn: int,
        pre_status_ms: int,
        pre_working: bool = False,
        now_ms: int | None = None,
        attempt: int | None = None,
        endpoint_uid: str = "",
    ) -> MailboxItem:
        """Write pre-delivery `intent` anchor before releasing `mailbox.lock` and calling `Transport` (C3)."""
        ts = self._now_ms() if now_ms is None else int(now_ms)
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            raw = (snap.get("active") or {}).get(env_id)
            if not isinstance(raw, Mapping):
                raise KeyError(f"cannot record intent for inactive/unknown envelope {env_id!r}")
            cur = MailboxItem.from_dict(raw)
            eff_attempt = int(attempt if attempt is not None else cur.next_attempt())
            rec = {
                "rec": "intent",
                "at_ms": ts,
                "env_id": env_id,
                "attempt": eff_attempt,
                "pre_turn": int(pre_turn or 0),
                "pre_status_ms": int(pre_status_ms or 0),
                "pre_working": bool(pre_working),
                "endpoint_uid": endpoint_uid or cur.target_endpoint_uid,
            }
            self._append_record_unlocked(snap, rec)
            updated = (snap.get("active") or {}).get(env_id)
            assert isinstance(updated, Mapping)
            return MailboxItem.from_dict(updated)

    def clear_intent(self, env_id: str, *, now_ms: int | None = None, hold_reason: str | None = None) -> MailboxItem | None:
        ts = self._now_ms() if now_ms is None else int(now_ms)
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            raw = (snap.get("active") or {}).get(env_id)
            if not isinstance(raw, Mapping):
                return None
            eff_reason = str(raw.get("hold_reason") or "") if hold_reason is None else str(hold_reason)
            if raw.get("intent") is None and eff_reason == str(raw.get("hold_reason") or ""):
                return MailboxItem.from_dict(raw)
            self._append_record_unlocked(snap, {
                "rec": "hold",
                "at_ms": ts,
                "env_id": env_id,
                "hold_reason": eff_reason,
                "clear_intent": True,
            })
            updated = (snap.get("active") or {}).get(env_id)
            return MailboxItem.from_dict(updated) if isinstance(updated, Mapping) else None

    def get(self, env_id: str) -> MailboxItem | None:
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            raw = (snap.get("active") or {}).get(env_id) or (snap.get("recent_completed") or {}).get(env_id)
            return MailboxItem.from_dict(raw) if isinstance(raw, Mapping) else None

    def get_by_key(self, idempotency_key: str) -> MailboxItem | None:
        if not idempotency_key:
            return None
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            return self._lookup_by_key_unlocked(snap, idempotency_key)

    def active_items(self, states: Sequence[str] | None = None) -> list[MailboxItem]:
        want = set(states) if states is not None else None
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            items = [
                MailboxItem.from_dict(raw)
                for raw in (snap.get("active") or {}).values()
                if isinstance(raw, Mapping) and (want is None or raw.get("state") in want)
            ]
        items.sort(key=lambda it: (it.envelope.priority, it.seq))
        return items

    def pending_for_endpoint(self, endpoint_uid: str = "") -> list[MailboxItem]:
        """Return deliverable (`accepted` or `queued`) items ordered strictly by `(priority ASC, seq ASC)`."""
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            items: list[MailboxItem] = []
            for raw in (snap.get("active") or {}).values():
                if not isinstance(raw, Mapping):
                    continue
                if raw.get("state") not in ("accepted", "queued"):
                    continue
                tuid = str(raw.get("target_endpoint_uid") or "")
                if endpoint_uid and tuid and tuid != endpoint_uid:
                    continue
                items.append(MailboxItem.from_dict(raw))
        items.sort(key=lambda it: (it.envelope.priority, it.seq))
        return items

    def read_stream_after(self, after_seq: int, *, limit: int = 200) -> tuple[list[dict[str, Any]], int]:
        """Read immutable JSONL records with `seq > after_seq`, returning `(records, last_seq)`."""
        rows: list[dict[str, Any]] = []
        last_seq = max(0, int(after_seq))
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            self._catch_up_unlocked()
            for seg_path in self._segments():
                try:
                    data = seg_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for line in data.split("\n"):
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    seq = int(obj.get("seq") or 0)
                    if seq > after_seq:
                        rows.append(obj)
                        last_seq = max(last_seq, seq)
                        if limit > 0 and len(rows) >= limit:
                            return rows, last_seq
        return rows, last_seq

    def set_acked_seq(self, acked_seq: int, *, now_ms: int | None = None) -> None:
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            if int(acked_seq) > int(snap.get("acked_seq") or 0):
                snap["acked_seq"] = int(acked_seq)
                self._compact_archives_unlocked(snap)
                self._write_snapshot_unlocked(snap)

    def requeue_unconsumed_on_epoch_change(
        self,
        new_epoch: int,
        *,
        now_ms: int | None = None,
        endpoint_uid: str = "",
    ) -> list[MailboxItem]:
        """G4: on a new session epoch / endpoint, put `typed` (unconsumed) items that need a reply back to `accepted`.

        Items that need no reply (`event.notify`, the seat opening `cmd.send`, ...) have no consumption receipt, so
        `typed` is the last state they reach: they belonged to the old session and are `expired`, never retyped into
        the new one. Untyped `accepted` items bound to another endpoint uid follow the PM to `endpoint_uid`."""
        ts = self._now_ms() if now_ms is None else int(now_ms)
        requeued: list[MailboxItem] = []
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            if endpoint_uid:
                stranded = [
                    MailboxItem.from_dict(raw)
                    for raw in (snap.get("active") or {}).values()
                    if isinstance(raw, Mapping) and raw.get("state") == "accepted"
                    and str(raw.get("target_endpoint_uid") or "") not in ("", endpoint_uid)
                ]
                stranded.sort(key=lambda it: it.seq)
                for item in stranded:
                    self._append_record_unlocked(snap, {
                        "rec": "st",
                        "at_ms": ts,
                        "env_id": item.envelope.env_id,
                        "from": "accepted",
                        "to": "accepted",
                        "endpoint_epoch": int(new_epoch),
                        "target_endpoint_uid": endpoint_uid,
                        "clear_intent": True,
                    })
            active_items = [
                MailboxItem.from_dict(raw)
                for raw in (snap.get("active") or {}).values()
                if isinstance(raw, Mapping) and raw.get("state") == "typed"
            ]
            active_items.sort(key=lambda it: it.seq)
            for item in active_items:
                if item.endpoint_epoch >= new_epoch and (not endpoint_uid or item.target_endpoint_uid == endpoint_uid):
                    continue
                if not item.envelope.require_reply or item.envelope.kind == "cmd.resume_turn":
                    self._append_record_unlocked(snap, {
                        "rec": "st",
                        "at_ms": ts,
                        "env_id": item.envelope.env_id,
                        "from": "typed",
                        "to": "expired",
                        "error": "session_changed",
                        "clear_intent": True,
                    })
                    continue
                self._append_record_unlocked(snap, {
                    "rec": "st",
                    "at_ms": ts,
                    "env_id": item.envelope.env_id,
                    "from": "typed",
                    "to": "accepted",
                    "hold_reason": "epoch_requeued",
                    "endpoint_epoch": int(new_epoch),
                    "target_endpoint_uid": endpoint_uid or item.target_endpoint_uid,
                    "clear_intent": True,
                    "meta": {"turn_opened_seq": None},
                })
                raw = (snap.get("active") or {}).get(item.envelope.env_id)
                if isinstance(raw, Mapping):
                    requeued.append(MailboxItem.from_dict(raw))
        return requeued

    @staticmethod
    def _typed_before_turn_start(item: MailboxItem, *, seq: int, turn_started_ms: int, turn_opened_ms: int) -> bool:
        opened_seq = int(item.meta.get("turn_opened_seq") or 0)
        if opened_seq > 0:
            return seq <= 0 or opened_seq <= seq
        t_ms = int(item.typed_ms or 0)
        if t_ms <= 0:
            return False
        if turn_started_ms > 0 and t_ms <= turn_started_ms:
            return True
        if not item.meta.get("typed_while_working") and turn_opened_ms > 0 and t_ms <= turn_opened_ms:
            return True
        return False

    def mark_typed_turn_opened(
        self,
        turn_seq: int,
        *,
        turn_started_ms: int = 0,
        turn_opened_ms: int = 0,
        now_ms: int | None = None,
    ) -> list[MailboxItem]:
        """Record `turn_opened_seq` on `typed` items once a confirmed turn starts after they were typed (B4)."""
        seq = int(turn_seq or 0)
        if seq <= 0:
            return []
        ts = self._now_ms() if now_ms is None else int(now_ms)
        eff_opened = max(int(turn_started_ms or 0), int(turn_opened_ms or 0))
        marked: list[MailboxItem] = []
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            candidates = [
                MailboxItem.from_dict(raw)
                for raw in (snap.get("active") or {}).values()
                if isinstance(raw, Mapping) and raw.get("state") == "typed"
            ]
            candidates.sort(key=lambda it: it.seq)
            for item in candidates:
                if int(item.meta.get("turn_opened_seq") or 0) > 0:
                    continue
                if item.envelope.kind not in ("chat.user", "event.batch"):
                    continue
                if not self._typed_before_turn_start(
                    item, seq=seq, turn_started_ms=int(turn_started_ms or 0), turn_opened_ms=eff_opened,
                ):
                    continue
                self._append_record_unlocked(snap, {
                    "rec": "st",
                    "at_ms": ts,
                    "env_id": item.envelope.env_id,
                    "from": "typed",
                    "to": "typed",
                    "meta": {**item.meta, "turn_opened_seq": seq},
                })
                raw_upd = (snap.get("active") or {}).get(item.envelope.env_id)
                if isinstance(raw_upd, Mapping):
                    marked.append(MailboxItem.from_dict(raw_upd))
        return marked

    def _settle_consumed_unlocked(
        self, snap: dict[str, Any], item: MailboxItem, outcome: str, turn_id: str, ts: int
    ) -> MailboxItem | None:
        """G5 for one `consumed` item whose turn closed with `outcome`.

        A batch (any other item that needs a reply) goes back to `accepted` (attempts + 1, until `max_attempts`,
        then `failed`) only when its turn visibly did not finish: `interrupted` (an interrupt stopped it) or
        `errored`. `silent` is what a closure without a reply signal infers (the supervisor seeing hc go idle
        before the Stop hook or the agy transcript says how the turn ended), so it is not evidence of an unhandled
        batch: retyping on it would deliver the same batch up to three times. A user message ends `answered` whatever
        the outcome: the coordinator read it (an Esc, an error or a silent turn is the user's to follow up, never an
        automatic retype). Items that need no reply end `answered` too. `closed` = an older turn whose own outcome
        was not seen (two turns closed in one catch-up): settled as answered, never retyped on a guess."""
        env_id = item.envelope.env_id
        done = (
            outcome not in ("interrupted", "errored")
            or item.envelope.kind in ("chat.user", "cmd.resume_turn")
            or not item.envelope.require_reply
        )
        meta = {**item.meta, "turn_outcome": outcome, "attempts_preincremented": False}
        if done:
            self._append_record_unlocked(snap, {
                "rec": "st", "at_ms": ts, "env_id": env_id, "from": "consumed", "to": "answered",
                "turn_id": turn_id or item.bound_turn_id, "meta": meta,
            })
            raw_done = (snap.get("recent_completed") or {}).get(env_id)
            return MailboxItem.from_dict(raw_done) if isinstance(raw_done, Mapping) else None
        next_attempts = item.attempts + 1
        exhausted = next_attempts > item.envelope.max_attempts
        retry_meta = {**meta, "attempts_preincremented": not exhausted}
        self._append_record_unlocked(snap, {
            "rec": "st", "at_ms": ts, "env_id": env_id, "from": "consumed", "to": "failed" if exhausted else "accepted",
            "attempts": next_attempts,
            "error": f"turn_{outcome}" if exhausted else "",
            "hold_reason": "" if exhausted else f"retry_after_{outcome}",
            "turn_id": "",
            "clear_intent": True,
            "meta": retry_meta,
        })
        pool = snap.get("recent_completed") if exhausted else snap.get("active")
        raw_next = (pool or {}).get(env_id)
        return MailboxItem.from_dict(raw_next) if isinstance(raw_next, Mapping) else None

    def reconcile_turn_outcome(
        self,
        turn_id: str,
        outcome: str,
        *,
        now_ms: int | None = None,
        turn_seq: int = 0,
    ) -> list[MailboxItem]:
        """G5: settle `consumed` items bound to `turn_id` / `turn_seq` (or unbound) on that turn's closure."""
        ts = self._now_ms() if now_ms is None else int(now_ms)
        changed: list[MailboxItem] = []
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            candidates = [
                MailboxItem.from_dict(raw)
                for raw in (snap.get("active") or {}).values()
                if isinstance(raw, Mapping) and raw.get("state") == "consumed"
            ]
            candidates.sort(key=lambda it: it.seq)
            for item in candidates:
                matched = False
                if turn_id and item.bound_turn_id == turn_id:
                    matched = True
                elif turn_seq > 0 and item.meta.get("turn_seq") == turn_seq:
                    matched = True
                elif not item.bound_turn_id:
                    matched = True
                if not matched:
                    continue
                settled = self._settle_consumed_unlocked(snap, item, outcome, turn_id, ts)
                if settled is not None:
                    changed.append(settled)
        return changed

    def settle_closed_turn(
        self,
        turn_seq: int,
        turn_id: str,
        outcome: str,
        *,
        ended_ms: int,
        turn_started_ms: int = 0,
        turn_opened_ms: int = 0,
        settle_typed_on_reply: bool = False,
        now_ms: int | None = None,
        pending_stale_ms: int = PENDING_TURN_STALE_MS,
    ) -> list[MailboxItem]:
        """G5 on every turn closure, whatever closed it (Stop hook, agy transcript, hc back to idle, an Esc).

        Settles the `consumed` items of turn `turn_seq` with `outcome`, and those of any older turn (bound to a
        lower seq, or never bound and read before this turn ended) as `closed`. An item a hook has just read for
        the turn that is starting (`bound_turn_id == PENDING_TURN`) is left for that turn, unless it went stale.
        When `outcome == 'replied'`, also settles items that were already `typed` before this turn started on
        coordinators without prompt-consumption hooks (`pi`, `other`, or unhooked sessions — B4)."""
        ts = self._now_ms() if now_ms is None else int(now_ms)
        seq = int(turn_seq or 0)
        own_refs = {r for r in (turn_id, f"seq:{seq}" if seq > 0 else "") if r}
        eff_opened = max(int(turn_started_ms or 0), int(turn_opened_ms or 0))
        changed: list[MailboxItem] = []
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            candidates = [
                MailboxItem.from_dict(raw)
                for raw in (snap.get("active") or {}).values()
                if isinstance(raw, Mapping) and raw.get("state") == "consumed"
            ]
            candidates.sort(key=lambda it: it.seq)
            for item in candidates:
                bound = item.bound_turn_id
                read_ms = int(item.consumed_ms or item.updated_ms or 0)
                raw_seq = item.meta.get("turn_seq")
                item_seq = int(raw_seq) if isinstance(raw_seq, int) and not isinstance(raw_seq, bool) else 0
                if not item_seq and bound.startswith("seq:") and bound[4:].isdigit():
                    item_seq = int(bound[4:])
                how = ""
                if bound == PENDING_TURN:
                    if read_ms <= ts - int(pending_stale_ms):
                        how = outcome
                elif item_seq > 0:
                    if seq > 0 and item_seq == seq:
                        how = outcome
                    elif seq > 0 and item_seq < seq:
                        how = "closed"
                elif bound in own_refs:
                    how = outcome
                elif read_ms <= int(ended_ms):
                    how = outcome if not bound else "closed"
                if not how:
                    continue
                settled = self._settle_consumed_unlocked(snap, item, how, turn_id, ts)
                if settled is not None:
                    changed.append(settled)

            if settle_typed_on_reply and outcome in ("replied", "silent", "interrupted"):
                typed_candidates = [
                    MailboxItem.from_dict(raw)
                    for raw in (snap.get("active") or {}).values()
                    if isinstance(raw, Mapping) and raw.get("state") == "typed"
                ]
                typed_candidates.sort(key=lambda it: it.seq)
                for item in typed_candidates:
                    if item.envelope.kind == "chat.user":
                        pass
                    elif item.envelope.kind == "event.batch" and outcome in ("replied", "silent"):
                        pass
                    else:
                        continue
                    if not self._typed_before_turn_start(
                        item, seq=seq, turn_started_ms=int(turn_started_ms or 0), turn_opened_ms=eff_opened,
                    ):
                        continue
                    meta = {
                        **item.meta,
                        "turn_outcome": outcome,
                        "attempts_preincremented": False,
                        **({"turn_opened_seq": seq} if seq > 0 and not item.meta.get("turn_opened_seq") else {}),
                    }
                    self._append_record_unlocked(snap, {
                        "rec": "st",
                        "at_ms": ts,
                        "env_id": item.envelope.env_id,
                        "from": "typed",
                        "to": "answered",
                        "turn_id": turn_id or item.bound_turn_id,
                        "meta": meta,
                    })
                    raw_done = (snap.get("recent_completed") or {}).get(item.envelope.env_id)
                    if isinstance(raw_done, Mapping):
                        changed.append(MailboxItem.from_dict(raw_done))
        return changed

    def unanswered_user_items(self) -> list[MailboxItem]:
        """Return active `chat.user` items not yet `answered`, sorted by `seq` (for `handover`, G4)."""
        items = [it for it in self.active_items(("accepted", "typed", "consumed")) if it.envelope.kind == "chat.user"]
        items.sort(key=lambda it: it.seq)
        return items

    def inbox_projection(self, *, limit: int = 32) -> list[dict[str, Any]]:
        """Project active + recent terminal items into `pm-turn.json` `inbox` format (§3.4, §3.9)."""
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            rows: list[tuple[int, dict[str, Any]]] = []
            for pool_name in ("active", "recent_completed"):
                pool = snap.get(pool_name) or {}
                for raw in pool.values():
                    if not isinstance(raw, Mapping):
                        continue
                    item = MailboxItem.from_dict(raw)
                    env = item.envelope
                    body = env.body if isinstance(env.body, Mapping) else {}
                    msg_id = str(body.get("msg_id") or env.env_id)
                    short_kind = "user" if env.kind == "chat.user" else ("batch" if env.kind == "event.batch" else env.kind)
                    rows.append((item.seq, {
                        "id": msg_id,
                        "env_id": env.env_id,
                        "seq": item.seq,
                        "kind": short_kind,
                        "priority": env.priority,
                        "state": item.state,
                        "accepted_ms": item.accepted_ms,
                        "typed_ms": item.typed_ms,
                        "consumed_ms": item.consumed_ms,
                        "answered_ms": item.answered_ms,
                        "attempts": item.attempts,
                        "reason": item.hold_reason or item.last_error,
                        "hold_reason": item.hold_reason,
                        "last_error": item.last_error,
                        # A send of it is in flight or came back uncertain (the UI says "sending", not "queued").
                        "sending": item.state == "accepted" and isinstance(item.intent, Mapping),
                        "alerted": bool(item.meta.get("undelivered_alerted")),
                    }))
        rows.sort(key=lambda pair: pair[0])
        cap = max(1, int(limit))
        if len(rows) <= cap:
            return [entry for _, entry in rows]
        # F2: never evict unsettled/failed `chat.user` entries when batches flood `inbox_projection`.
        pinned = [
            (seq_i, entry)
            for seq_i, entry in rows
            if entry.get("kind") == "user" and entry.get("state") not in ("answered", "superseded", "expired")
        ]
        pinned_seqs = {seq_i for seq_i, _ in pinned}
        tail_budget = max(0, cap - len(pinned))
        rest = [(seq_i, entry) for seq_i, entry in rows if seq_i not in pinned_seqs]
        kept = [*pinned, *(rest[-tail_budget:] if tail_budget > 0 else [])]
        kept.sort(key=lambda pair: pair[0])
        return [entry for _, entry in kept]

    def undelivered_summary(self, now_ms: int | None = None) -> dict[str, Any] | None:
        """Compute `{count, oldest_ms, oldest_seq, oldest_priority, reason, waiting_seconds}` for queued items."""
        ts = self._now_ms() if now_ms is None else int(now_ms)
        pending = [it for it in self.active_items(("accepted",)) if it.envelope.kind != "ctrl.interrupt"]
        if not pending:
            return None
        pending.sort(key=lambda it: it.seq)
        oldest = pending[0]
        oldest_ms = oldest.accepted_ms or oldest.envelope.created_ms or ts
        wait_s = max(0, int((ts - oldest_ms) // 1000))
        reason = ""
        for it in pending:
            if it.hold_reason:
                reason = it.hold_reason
                break
            if it.last_error:
                reason = it.last_error
                break
        return {
            "count": len(pending),
            "oldest_ms": oldest_ms,
            "oldest_seq": oldest.seq,
            "oldest_priority": oldest.envelope.priority,
            "reason": reason,
            "waiting_seconds": wait_s,
        }

    def receipts_projection(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """1-version compat `receipts` projection from consumed/answered `chat.user` mailbox items."""
        if not self.root.is_dir() or (not self.state_path.is_file() and not self._segments()):
            return []
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            rows: list[tuple[int, int, dict[str, Any]]] = []
            for pool_name in ("active", "recent_completed"):
                pool = snap.get(pool_name) or {}
                for raw in pool.values():
                    if not isinstance(raw, Mapping):
                        continue
                    item = MailboxItem.from_dict(raw)
                    env = item.envelope
                    if env.kind != "chat.user" or item.state not in ("consumed", "answered"):
                        continue
                    body = env.body if isinstance(env.body, Mapping) else {}
                    raw_text = str(body.get("text") or "")
                    msg_id = str(body.get("msg_id") or "")
                    at_ms = int(item.consumed_ms or item.answered_ms or item.typed_ms or item.accepted_ms or env.created_ms or 0)
                    at_str = (
                        datetime.datetime.fromtimestamp(at_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
                        if at_ms > 0
                        else ""
                    )
                    entry: dict[str, Any] = {
                        "at": at_str,
                        "at_ms": at_ms,
                        "text": raw_text[:500],
                        "truncated": len(raw_text) > 500,
                        "len": len(raw_text),
                    }
                    if raw_text:
                        entry["digest"] = hashlib.sha1(raw_text.encode("utf-8", errors="replace")).hexdigest()[:16]
                    if msg_id:
                        entry["msg_id"] = msg_id
                    if entry.get("at") and (entry.get("text") or entry.get("digest") or entry.get("msg_id")):
                        rows.append((at_ms, item.seq, entry))
        rows.sort(key=lambda t: (t[0], t[1]))
        return [entry for _, _, entry in rows[-max(1, int(limit)):]]

    def migrate_legacy_pm_state(
        self,
        pm_turn_path: Path,
        legacy_inbox_jsonl: Path | None = None,
        *,
        project: str,
        now_ms: int | None = None,
    ) -> int:
        """One-time migration absorbing v1 `pm-turn.json` (`outbox`/`inflight`/`recent_msg_ids`) & `inbox/*.jsonl`."""
        ts = self._now_ms() if now_ms is None else int(now_ms)
        migrated = 0
        with file_lock(self.lock_path, timeout=self.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            snap, _ = self._catch_up_unlocked()
            if snap.get("legacy_migrated"):
                return 0
            pm_raw: dict[str, Any] = {}
            if pm_turn_path.is_file():
                try:
                    loaded = json.loads(pm_turn_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        pm_raw = loaded
                except (OSError, ValueError):
                    pm_raw = {}

            # Seed recent_msg_ids first: a message the old code delivered dedupes a retry of it after the upgrade
            # (the tombstone lookup), and an `inflight`/`outbox` entry it already delivered is not queued again.
            recent = pm_raw.get("recent_msg_ids")
            if isinstance(recent, Mapping):
                for mid, meta in recent.items():
                    if not isinstance(mid, str) or not mid:
                        continue
                    idem = f"ui:{project}:{mid}"
                    if idem not in snap["recent_keys"]:
                        snap["recent_keys"][idem] = {
                            "env_id": f"legacy:{mid}",
                            "seq": 0,
                            "state": "answered",
                            "kind": "chat.user",
                            "meta": dict(meta) if isinstance(meta, Mapping) else {},
                        }

            candidates: list[dict[str, Any]] = []
            inflight = pm_raw.get("inflight")
            if isinstance(inflight, Mapping) and inflight.get("msg_id") and inflight.get("text"):
                candidates.append({
                    "msg_id": str(inflight["msg_id"]),
                    "text": str(inflight["text"]),
                    "question": str(inflight.get("question") or ""),
                    "at_ms": int(inflight.get("at_ms") or ts),
                    "reason": "migrated_inflight",
                    # The old code was typing it: whether it landed is decided like any interrupted send (C3),
                    # by the terminal's turn moving past this anchor, before it is typed again.
                    "pre_turn": int(inflight.get("pre_turn") or 0),
                })
            for ob in pm_raw.get("outbox") or ():
                if isinstance(ob, Mapping) and ob.get("msg_id") and ob.get("text"):
                    candidates.append({
                        "msg_id": str(ob["msg_id"]),
                        "text": str(ob["text"]),
                        "question": str(ob.get("question") or ""),
                        "at_ms": int(ob.get("queued_ms") or ts),
                        "reason": str(ob.get("reason") or "migrated_outbox"),
                    })
            for item in candidates:
                idem = f"ui:{project}:{item['msg_id']}"
                if self._lookup_by_key_unlocked(snap, idem) is not None:
                    continue
                env = Envelope(
                    env_id=new_env_id(item["at_ms"]),
                    idempotency_key=idem,
                    schema_version=1,
                    created_ms=item["at_ms"],
                    kind="chat.user",
                    sender=Principal.user(project),
                    recipient=LogicalAddress.pm(project),
                    project=project,
                    cause={"kind": "legacy_migration", "question_task": item["question"]},
                    priority=P1_USER,
                    body={"text": item["text"], "msg_id": item["msg_id"], "question": item["question"]},
                    require_reply=True,
                )
                self._append_record_unlocked(snap, {
                    "rec": "enq",
                    "at_ms": item["at_ms"],
                    "env": env.to_dict(),
                    "state": "accepted",
                    "attempts": 0,
                    "hold_reason": item["reason"],
                })
                if int(item.get("pre_turn") or 0) > 0:
                    self._append_record_unlocked(snap, {
                        "rec": "intent",
                        "at_ms": item["at_ms"],
                        "env_id": env.env_id,
                        "attempt": 1,
                        "pre_turn": int(item["pre_turn"]),
                        "pre_status_ms": 0,
                        "endpoint_uid": "",
                    })
                migrated += 1

            # Absorb legacy inbox/*.jsonl lines if present.
            if legacy_inbox_jsonl is not None and legacy_inbox_jsonl.is_file():
                try:
                    raw_lines = legacy_inbox_jsonl.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    raw_lines = []
                for idx, line in enumerate(raw_lines):
                    text = line.strip()
                    if not text:
                        continue
                    # A stable key (`hash()` differs per process): a re-run never absorbs the line twice.
                    digest = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:16]
                    idem = f"legacy_inbox:{project}:{idx}:{digest}"
                    if self._lookup_by_key_unlocked(snap, idem) is not None:
                        continue
                    try:
                        parsed = json.loads(text)
                        body_text = str(parsed.get("text") or text) if isinstance(parsed, dict) else text
                    except ValueError:
                        body_text = text
                    env = Envelope(
                        env_id=new_env_id(ts),
                        idempotency_key=idem,
                        schema_version=1,
                        created_ms=ts,
                        kind="event.notify",
                        sender=Principal.supervisor(project),
                        recipient=LogicalAddress.pm(project),
                        project=project,
                        cause={"kind": "legacy_inbox"},
                        priority=P4_BATCH,
                        body={"text": body_text},
                        require_reply=False,
                    )
                    self._append_record_unlocked(snap, {
                        "rec": "enq",
                        "at_ms": ts,
                        "env": env.to_dict(),
                        "state": "accepted",
                        "attempts": 0,
                    })
                    migrated += 1

            snap["legacy_migrated"] = True
            self._write_snapshot_unlocked(snap)
        return migrated

    # ---- Per-endpoint non-blocking typist lease (`typist.lock`, never nests with `mailbox.lock`) ----
    #
    # The lease is held by an owner *token*, not a pid: two typists in one process (the deliverer's driver and a
    # `still_running`/notify call, or a seat thread) must exclude each other too. A holder renews by acquiring again
    # with the same token; nobody steals a lease before `lease_until_ms`, even when the holder's pid looks dead,
    # because an orphaned `hc send` child can still be typing after its parent died (TTL is the bound).

    def _typist_lease_paths(self, endpoint_uid: str) -> tuple[Path, Path]:
        safe = _sanitize_uid_filename(endpoint_uid)
        return self.typist_dir / f"{safe}.typist.lock", self.typist_dir / f"{safe}.typist.json"

    @staticmethod
    def _lease_owner_token(cur: Mapping[str, Any]) -> str:
        return str(cur.get("owner") or cur.get("owner_pid") or "")

    def acquire_typist_lease(
        self,
        endpoint_uid: str,
        owner_pid: int,
        ttl_ms: int = 75_000,
        *,
        now_ms: int | None = None,
        owner: str = "",
    ) -> bool:
        """Take (or renew, for the same `owner` token) `<endpoint>.typist.lock` without blocking.

        `owner` defaults to `str(owner_pid)`. Returns False while another token holds an unexpired lease."""
        ts = self._now_ms() if now_ms is None else int(now_ms)
        token = str(owner or owner_pid)
        lock_path, meta_path = self._typist_lease_paths(endpoint_uid)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with file_lock(lock_path, timeout=0.05, lock_fn=lock_file, unlock_fn=unlock_file):
                acquired_ms = ts
                if meta_path.is_file():
                    try:
                        cur = json.loads(meta_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        cur = {}
                    if isinstance(cur, Mapping):
                        cur_token = self._lease_owner_token(cur)
                        lease_until = int(cur.get("lease_until_ms") or 0)
                        if cur_token and cur_token != token and ts < lease_until:
                            return False
                        if cur_token == token and cur.get("acquired_ms") is not None:
                            acquired_ms = int(cur["acquired_ms"])
                write_atomic(
                    meta_path,
                    (json.dumps({
                        "endpoint_uid": endpoint_uid,
                        "owner": token,
                        "owner_pid": int(owner_pid),
                        "acquired_ms": acquired_ms,
                        "renewed_ms": ts,
                        "lease_until_ms": ts + max(1000, int(ttl_ms)),
                    }) + "\n").encode("utf-8"),
                    replace_fn=replace_task_file,
                )
                return True
        except OSError:
            return False

    def release_typist_lease(self, endpoint_uid: str, owner_pid: int, *, owner: str = "") -> None:
        token = str(owner or owner_pid)
        lock_path, meta_path = self._typist_lease_paths(endpoint_uid)
        if not meta_path.is_file():
            return
        with contextlib.suppress(OSError):
            with file_lock(lock_path, timeout=0.2, lock_fn=lock_file, unlock_fn=unlock_file):
                try:
                    cur = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    cur = {}
                if not isinstance(cur, Mapping) or self._lease_owner_token(cur) == token:
                    meta_path.unlink(missing_ok=True)

    def typist_lease_holder(self, endpoint_uid: str, *, now_ms: int | None = None) -> dict[str, Any] | None:
        """The unexpired lease record on `endpoint_uid` (diagnostics/tests), or None when nobody types."""
        ts = self._now_ms() if now_ms is None else int(now_ms)
        _, meta_path = self._typist_lease_paths(endpoint_uid)
        try:
            cur = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(cur, Mapping) or ts >= int(cur.get("lease_until_ms") or 0):
            return None
        return dict(cur)


def merge_receipts_compat(
    primary: Sequence[Mapping[str, Any]],
    legacy: Sequence[Mapping[str, Any]],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Merge primary mailbox-projected receipts with 1-version legacy `receipts.json` fallback."""
    cap = max(1, int(limit))
    if not legacy:
        return [dict(r) for r in primary[-cap:]]
    if not primary:
        return [dict(r) for r in legacy[-cap:]]
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_keys: set[tuple[Any, ...]] = set()
    for r in (*primary, *legacy):
        if not isinstance(r, Mapping):
            continue
        mid = str(r.get("msg_id") or "")
        if mid:
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
        key = (int(r.get("at_ms") or 0), str(r.get("at") or ""), str(r.get("digest") or r.get("text") or ""))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        merged.append(dict(r))
    merged.sort(key=lambda r: (int(r.get("at_ms") or 0), str(r.get("at") or "")))
    return merged[-cap:]
