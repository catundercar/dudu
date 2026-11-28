"""The remote worker's side of the report path (`pm-message-routing.md` §6.1, §6.5, §7.2, §8.1): its state folder
(`<worker_state>/context.json`, `credential.json`, `outbox.jsonl`), the append-only report outbox with monotonic
`seq`, and the per-task HMAC that binds every outbox line to the `(task_id, epoch)` the coordinator issued the token
for. The ledger never lives here: a worker on another machine only appends; the coordinator pulls by `seq` and
applies (`reports.RemoteReportSync`). Layer 2.

Layout of `<worker_state>` (one folder per remote task, outside the worktree so nothing in it is ever committed):

- `context.json`  read-only session context `{role, project, task_id, epoch, machine, land_approved, lang, ...}`,
  rewritten by the coordinator when approval or rotation changes it (never a stale dispatch snapshot).
- `credential.json`  `{task_id, epoch, credential_id, token}` (0600): the token signs outbox lines.
- `outbox.jsonl`  one line per report: `{"seq": N, "envelope": {...}, "mac": "<hex>"}`; line N holds seq N.
- `obs-journal.jsonl`  optional observation lines `{"seq": N, ...}` (MR-D3: only with the optional watcher).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from typing import Any, Mapping

from ..store import file_lock, lock_file, unlock_file, write_atomic
from .envelope import Envelope


WORKER_STATE_ENV = "PM_WORKER_STATE"
CONTEXT_FILE = "context.json"
CREDENTIAL_FILE = "credential.json"
OUTBOX_FILE = "outbox.jsonl"
OUTBOX_LOCK = "outbox.lock"
OBS_JOURNAL_FILE = "obs-journal.jsonl"
MAX_ENVELOPE_BYTES = 512 * 1024  # §8.4: one envelope at most 512 KiB


def new_token() -> str:
    """A fresh 256-bit task token (hex)."""
    return secrets.token_hex(32)


def canonical_envelope(env: Envelope | Mapping[str, Any]) -> str:
    data = env.to_dict() if isinstance(env, Envelope) else dict(env)
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_envelope(token: str, env: Envelope | Mapping[str, Any]) -> str:
    return hmac.new(token.encode("utf-8"), canonical_envelope(env).encode("utf-8"), hashlib.sha256).hexdigest()


def verify_envelope(token: str, env: Envelope | Mapping[str, Any], mac: str) -> bool:
    if not token or not mac:
        return False
    return hmac.compare_digest(sign_envelope(token, env), str(mac))


@dataclass(frozen=True)
class OutboxLine:
    """One parsed outbox line: its `seq`, the envelope as written, and the MAC over it."""

    seq: int
    envelope: dict[str, Any]
    mac: str = ""

    @classmethod
    def parse(cls, raw: str) -> OutboxLine | None:
        try:
            obj = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(obj, Mapping):
            return None
        seq = obj.get("seq")
        env = obj.get("envelope")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq <= 0 or not isinstance(env, Mapping):
            return None
        return cls(seq=seq, envelope=dict(env), mac=str(obj.get("mac") or ""))

    def to_line(self) -> str:
        return json.dumps({"seq": self.seq, "envelope": self.envelope, "mac": self.mac},
                          ensure_ascii=False, separators=(",", ":")) + "\n"


def parse_outbox_text(text: str, *, after_seq: int = 0) -> list[OutboxLine]:
    """The well-formed lines of an outbox chunk with `seq > after_seq`, in file order (a torn last line, written
    while it was read, is skipped and read again next time)."""
    out: list[OutboxLine] = []
    for raw in str(text or "").splitlines():
        if not raw.strip():
            continue
        line = OutboxLine.parse(raw)
        if line is not None and line.seq > after_seq:
            out.append(line)
    return out


@dataclass
class WorkerState:
    """A remote worker's `<worker_state>` folder (§6.5)."""

    root: Path
    context: dict[str, Any] = field(default_factory=dict)
    credential: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None) -> WorkerState | None:
        """The folder `PM_WORKER_STATE` names, when it holds a remote worker's `context.json`; else None (a worker
        on the coordinator's own machine reports straight into the ledger)."""
        raw = str((env or {}).get(WORKER_STATE_ENV) or "").strip()
        if not raw:
            return None
        return cls.load(Path(raw).expanduser())

    @classmethod
    def load(cls, root: Path) -> WorkerState | None:
        ctx_path = root / CONTEXT_FILE
        if not ctx_path.is_file():
            return None
        context = _read_json(ctx_path)
        if not context.get("task_id") or not context.get("remote"):
            return None
        return cls(root=root, context=context, credential=_read_json(root / CREDENTIAL_FILE))

    @property
    def task_id(self) -> str:
        return str(self.context.get("task_id") or "")

    @property
    def project(self) -> str:
        return str(self.context.get("project") or "")

    @property
    def epoch(self) -> int:
        val = self.credential.get("epoch") or self.context.get("epoch") or 1
        return int(val) if isinstance(val, int) and not isinstance(val, bool) and val > 0 else 1

    @property
    def machine(self) -> str:
        return str(self.context.get("machine") or "")

    @property
    def outbox(self) -> WorkerOutbox:
        return WorkerOutbox(self.root)


class WorkerOutbox:
    """Append-only `outbox.jsonl` under `outbox.lock`: line N carries `seq` N; nothing is ever rewritten."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    @property
    def path(self) -> Path:
        return self.root / OUTBOX_FILE

    @property
    def lock_path(self) -> Path:
        return self.root / OUTBOX_LOCK

    def lines(self, *, after_seq: int = 0) -> list[OutboxLine]:
        if not self.path.is_file():
            return []
        return parse_outbox_text(self.path.read_text(encoding="utf-8"), after_seq=after_seq)

    def last_seq(self) -> int:
        rows = self.lines()
        return rows[-1].seq if rows else 0

    def find(self, idempotency_key: str) -> OutboxLine | None:
        if not idempotency_key:
            return None
        return next((r for r in self.lines() if r.envelope.get("idempotency_key") == idempotency_key), None)

    def append(self, env: Envelope, *, token: str) -> OutboxLine:
        """Append one report (a retry of the same idempotency key returns its first line), fsynced before return."""
        data = env.to_dict()
        if len(canonical_envelope(data).encode("utf-8")) > MAX_ENVELOPE_BYTES:
            raise ValueError(f"report envelope larger than {MAX_ENVELOPE_BYTES} bytes")
        self.root.mkdir(parents=True, exist_ok=True)
        with file_lock(self.lock_path, lock_fn=lock_file, unlock_fn=unlock_file):
            existing = self.find(env.idempotency_key)
            if existing is not None:
                return existing
            line = OutboxLine(seq=self.last_seq() + 1, envelope=data, mac=sign_envelope(token, data) if token else "")
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line.to_line())
                f.flush()
                os.fsync(f.fileno())
            return line


class WorkerObsJournal:
    """Append-only `obs-journal.jsonl` of a worker state folder (a self-hosted node's agent writes it, phase 6b):
    line N carries `seq` N and the time `t` (ms); synced to the coordinator by `seq` like the outbox."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    @property
    def path(self) -> Path:
        return self.root / OBS_JOURNAL_FILE

    def lines(self, *, after_seq: int = 0) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return obs_lines(self.path.read_text(encoding="utf-8"), after_seq=after_seq)

    def append(self, kind: str, *, t: int, **fields: Any) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        with file_lock(self.root / "obs-journal.lock", lock_fn=lock_file, unlock_fn=unlock_file):
            rows = self.lines()
            row = {**fields, "seq": (int(rows[-1]["seq"]) if rows else 0) + 1, "kind": kind, "t": int(t)}
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                f.flush()
                os.fsync(f.fileno())
            return row


def write_worker_state_files(root: Path, *, context: Mapping[str, Any], credential: Mapping[str, Any] | None = None) -> None:
    """Write `context.json` (and `credential.json`, 0600) into a local worker-state folder (tests, and the remote
    side when the coordinator hands the files over through `hc file write`)."""
    root.mkdir(parents=True, exist_ok=True)
    write_atomic(root / CONTEXT_FILE, (json.dumps(dict(context), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    if credential is not None:
        cred_path = root / CREDENTIAL_FILE
        write_atomic(cred_path, (json.dumps(dict(credential), indent=2) + "\n").encode("utf-8"))
        try:
            os.chmod(cred_path, 0o600)
        except OSError:
            pass


def obs_lines(text: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
    """Observation journal lines (`{"seq": N, ...}`) with `seq > after_seq`."""
    out: list[dict[str, Any]] = []
    for raw in str(text or "").splitlines():
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        seq = obj.get("seq") if isinstance(obj, dict) else None
        if isinstance(seq, int) and not isinstance(seq, bool) and seq > after_seq:
            out.append(obj)
    return out


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


class TaskTokens:
    """The coordinator's per-`(task_id, epoch)` remote worker tokens, `<ledger_home>/tokens/task-<id>.json` (0600;
    the folder 0700). A new epoch (reattach, escalate) gets a new token; the old ones stay so a late report from an
    earlier epoch still verifies and is archived (MR-D4) instead of being taken for a forgery."""

    def __init__(self, tokens_dir: Path | str) -> None:
        self.dir = Path(tokens_dir)

    def _path(self, task_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in task_id)
        return self.dir / f"task-{safe}.json"

    def _read(self, task_id: str) -> dict[str, Any]:
        data = _read_json(self._path(task_id))
        epochs = data.get("epochs")
        return {"epochs": dict(epochs) if isinstance(epochs, Mapping) else {}}

    def issue(self, task_id: str, epoch: int, *, machine: str = "") -> dict[str, Any]:
        """The credential for `(task_id, epoch)`: the existing one, else a fresh token."""
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        lock = self.dir / f".task-{task_id}.lock"
        with file_lock(lock, lock_fn=lock_file, unlock_fn=unlock_file):
            data = self._read(task_id)
            key = str(int(epoch or 1))
            row = data["epochs"].get(key)
            if not isinstance(row, Mapping) or not row.get("token"):
                row = {"token": new_token(), "machine": machine}
                data["epochs"][key] = row
                path = self._path(task_id)
                write_atomic(path, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
        return {"task_id": task_id, "epoch": int(epoch or 1), "credential_id": f"task-token:{task_id}:{int(epoch or 1)}",
                "token": str(row["token"])}

    def token_for(self, task_id: str, epoch: int) -> str:
        row = self._read(task_id)["epochs"].get(str(int(epoch or 1)))
        return str(row.get("token") or "") if isinstance(row, Mapping) else ""


def task_remote_outboxes(task: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Every remote worker state a task has had (`remote`, then the earlier ones in `remote_history`), each
    `{machine, terminal, epoch, state_dir, ...}`: the coordinator keeps pulling an earlier epoch's outbox so its late
    reports are archived (MR-D4), not lost."""
    if not isinstance(task, Mapping):
        return []
    out: list[dict[str, Any]] = []
    rows = [task.get("remote"), *(task.get("remote_history") or [])]
    seen: set[tuple[str, int]] = set()
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("machine") or not row.get("state_dir"):
            continue
        epoch = row.get("epoch")
        ep = int(epoch) if isinstance(epoch, int) and not isinstance(epoch, bool) and epoch > 0 else 1
        key = (str(row["state_dir"]), ep)
        if key in seen:
            continue
        seen.add(key)
        out.append({**dict(row), "epoch": ep})
    return out
