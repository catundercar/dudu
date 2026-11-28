"""Self-hosted worker nodes (`pm-message-routing.md` §8.3, §9.3 phase 6b): enrollment, credentials, revocation, task
grants, request signing, and the coordinator's per-node pull/observation streams. Layer 2.

Credentials (Python 3.9 standard library only, no third-party package):

- An enrollment token `enroll_<64 hex>` (256 bits) is single use and short lived (default 15 minutes); only its
  SHA-256 digest is kept, in `<ledger_home>/tokens/workers.json` (0600, folder 0700).
- `join` exchanges it for a fixed `node_id` and a 256-bit node secret. Ed25519 is not in the standard library, so
  requests are signed with HMAC-SHA256 under that secret: the coordinator (the only trusted machine, §8.4) keeps the
  secret in `workers.json`; the node keeps it in `<worker_state>/credential.json` (0600, created exclusively).
- Every sync request signs `pm-sync-v1\\n<node_id>\\n<ts_ms>\\n<nonce>\\n<sha256(canonical body)>`; the coordinator
  refuses a clock skew over 300 s and a nonce it has seen (replay).
- A node has no write right on any task by itself: `dispatch --on <node>` grants `(node_id, task_id, epoch)`; a revoked
  node is refused (`authz_denied`) on its next request, its grants dropped.

Coordinator-side streams, `<ledger_home>/nodes/<node_id>/` (`NodeStreams`):

- `inbox.jsonl`  the node's pull queue: one line per entry `{seq, slot, env_id, envelope | ctrl}`, `seq` monotonic,
  idempotent by `(slot, env_id)`; the node acknowledges by the highest `seq` it stored.
- `obs/<slot>.jsonl`  observations the node pushed for one endpoint (its own `seq`), read by `observe`.
- `state.json`  last sync (the heartbeat a lease is measured from), the node's acked inbox `seq`, each slot's latest
  endpoint state, and recent nonces.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from typing import Any, Iterable, Mapping

from ..store import file_lock, lock_file, unlock_file, write_atomic


WORKERS_FILE = "workers.json"
WORKERS_LOCK = ".workers.lock"
ENROLL_PREFIX = "enroll_"
NODE_PREFIX = "node_"
DEFAULT_ENROLL_TTL_S = 15 * 60
CLOCK_SKEW_S = 300
NONCE_KEEP = 512
MAX_SYNC_BYTES = 4 * 1024 * 1024  # §8.4: one sync batch at most 4 MiB
SIGNING_TAG = "pm-sync-v1"
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,47}$")


class NodeError(Exception):
    """A refused node request: `code` is the protocol's error code (`authz_denied`, `bad_signature`, ...)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def body_digest(body: Any) -> str:
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def signing_string(node_id: str, ts_ms: int, nonce: str, digest: str) -> str:
    return f"{SIGNING_TAG}\n{node_id}\n{int(ts_ms)}\n{nonce}\n{digest}"


def sign_request(secret: str, node_id: str, ts_ms: int, nonce: str, body: Any) -> str:
    msg = signing_string(node_id, ts_ms, nonce, body_digest(body)).encode("utf-8")
    return hmac.new(str(secret).encode("utf-8"), msg, hashlib.sha256).hexdigest()


def signed_request(credential: Mapping[str, Any], body: Mapping[str, Any], *, now_ms: int) -> dict[str, Any]:
    """The JSON request a node sends: `{v, auth: {node_id, ts_ms, nonce, sig}, body}`."""
    node_id = str(credential.get("node_id") or "")
    nonce = secrets.token_hex(12)
    sig = sign_request(str(credential.get("secret") or ""), node_id, now_ms, nonce, dict(body))
    return {"v": 1, "auth": {"node_id": node_id, "ts_ms": int(now_ms), "nonce": nonce, "sig": sig}, "body": dict(body)}


def token_digest(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def safe_name(raw: str) -> str:
    return _SAFE.sub("_", str(raw or "")).strip("._") or "x"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_private(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    write_atomic(path, (json.dumps(dict(data), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def public_node(node: Mapping[str, Any]) -> dict[str, Any]:
    """A node record without its secret."""
    return {k: v for k, v in dict(node).items() if k != "secret"}


@dataclass(frozen=True)
class Enrollment:
    token: str
    alias: str
    projects: tuple[str, ...]
    expires_ms: int


class NodeRegistry:
    """`<ledger_home>/tokens/workers.json`: enrollments (digests only), nodes, their grants (coordinator side)."""

    def __init__(self, tokens_dir: Path | str, *, clock: Any = None) -> None:
        self.dir = Path(tokens_dir)
        self._clock = clock

    @property
    def path(self) -> Path:
        return self.dir / WORKERS_FILE

    def _now_ms(self) -> int:
        if self._clock is not None:
            return int(float(self._clock.time()) * 1000)
        return int(time.time() * 1000)

    def _lock(self) -> Any:
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        return file_lock(self.dir / WORKERS_LOCK, lock_fn=lock_file, unlock_fn=unlock_file)

    def _read(self) -> dict[str, Any]:
        data = _read_json(self.path)
        ens = data.get("enrollments")
        nodes = data.get("nodes")
        return {"enrollments": dict(ens) if isinstance(ens, Mapping) else {},
                "nodes": dict(nodes) if isinstance(nodes, Mapping) else {}}

    def _write(self, data: Mapping[str, Any]) -> None:
        _write_private(self.path, data)

    # --- enrollment --------------------------------------------------------------------------------------------

    def enroll(self, alias: str, projects: Iterable[str], *, ttl_s: float = DEFAULT_ENROLL_TTL_S) -> Enrollment:
        alias = str(alias or "").strip()
        if not _ALIAS_RE.match(alias):
            raise NodeError("bad_request", f"node name {alias!r}: letters, digits, '-', '_', '.' (at most 48)")
        projs = tuple(sorted({str(p).strip() for p in projects if str(p).strip()}))
        if not projs:
            raise NodeError("bad_request", "a node needs at least one project (--projects <slug>[,<slug>])")
        ttl_ms = int(max(60.0, float(ttl_s)) * 1000)
        token = ENROLL_PREFIX + secrets.token_hex(32)
        now = self._now_ms()
        with self._lock():
            data = self._read()
            for node in data["nodes"].values():
                if node.get("alias") == alias and not node.get("revoked_ms"):
                    raise NodeError("bad_request", f"an active node is already named {alias}: revoke it first")
            # Expired, unused enrollments are dropped as new ones are made.
            data["enrollments"] = {k: v for k, v in data["enrollments"].items()
                                   if isinstance(v, Mapping) and (v.get("used_ms") or int(v.get("expires_ms") or 0) > now)}
            data["enrollments"][token_digest(token)] = {
                "alias": alias, "projects": list(projs), "created_ms": now, "expires_ms": now + ttl_ms,
            }
            self._write(data)
        return Enrollment(token=token, alias=alias, projects=projs, expires_ms=now + ttl_ms)

    def join(self, token: str, *, capabilities: Mapping[str, Any] | None = None, pm_command: str = "",
             label: str = "") -> dict[str, Any]:
        """Exchange a single-use enrollment token for a node (returned with its secret, once)."""
        token = str(token or "").strip()
        if not token.startswith(ENROLL_PREFIX):
            raise NodeError("invalid_token", "not an enrollment token")
        digest = token_digest(token)
        now = self._now_ms()
        with self._lock():
            data = self._read()
            row = data["enrollments"].get(digest)
            if not isinstance(row, Mapping):
                raise NodeError("invalid_token", "unknown enrollment token")
            if row.get("used_ms"):
                raise NodeError("token_used", "this enrollment token was already used")
            if int(row.get("expires_ms") or 0) <= now:
                raise NodeError("token_expired", "this enrollment token has expired: enroll again")
            node_id = NODE_PREFIX + secrets.token_hex(8)
            node = {
                "node_id": node_id,
                "alias": str(row.get("alias") or node_id),
                "projects": list(row.get("projects") or []),
                "secret": secrets.token_hex(32),
                "created_ms": now,
                "revoked_ms": 0,
                "capabilities": dict(capabilities or {}),
                "pm_command": str(pm_command or ""),
                "label": str(label or "")[:80],
                "grants": {},
            }
            data["nodes"][node_id] = node
            data["enrollments"][digest] = {**dict(row), "used_ms": now, "node_id": node_id}
            self._write(data)
        return dict(node)

    # --- nodes -------------------------------------------------------------------------------------------------

    def nodes(self) -> list[dict[str, Any]]:
        return [dict(n) for n in self._read()["nodes"].values() if isinstance(n, Mapping)]

    def get(self, node_id: str) -> dict[str, Any] | None:
        node = self._read()["nodes"].get(str(node_id or ""))
        return dict(node) if isinstance(node, Mapping) else None

    def find(self, ref: str, *, active_only: bool = False) -> dict[str, Any] | None:
        """A node by id, else by alias (the active one first)."""
        ref = str(ref or "").strip()
        if not ref:
            return None
        nodes = self.nodes()
        hit = next((n for n in nodes if n.get("node_id") == ref), None)
        if hit is None:
            named = [n for n in nodes if n.get("alias") == ref]
            named.sort(key=lambda n: (not n.get("revoked_ms"), int(n.get("created_ms") or 0)), reverse=True)
            hit = named[0] if named else None
        if hit is not None and active_only and hit.get("revoked_ms"):
            return None
        return hit

    def revoke(self, ref: str) -> dict[str, Any]:
        node = self.find(ref)
        if node is None:
            raise NodeError("not_found", f"no node {ref!r}")
        with self._lock():
            data = self._read()
            cur = dict(data["nodes"].get(node["node_id"]) or node)
            if not cur.get("revoked_ms"):
                cur["revoked_ms"] = self._now_ms()
            cur["grants"] = {}
            data["nodes"][cur["node_id"]] = cur
            self._write(data)
        return cur

    def update(self, node_id: str, **fields: Any) -> None:
        with self._lock():
            data = self._read()
            cur = data["nodes"].get(node_id)
            if not isinstance(cur, Mapping):
                return
            new = {**dict(cur), **fields}
            if new != cur:
                data["nodes"][node_id] = new
                self._write(data)

    # --- task grants -------------------------------------------------------------------------------------------

    def grant(self, node_id: str, task_id: str, epoch: int) -> None:
        with self._lock():
            data = self._read()
            cur = data["nodes"].get(node_id)
            if not isinstance(cur, Mapping) or cur.get("revoked_ms"):
                raise NodeError("authz_denied", f"node {node_id} is revoked or unknown")
            cur = dict(cur)
            grants = dict(cur.get("grants") or {})
            row = dict(grants.get(task_id) or {})
            epochs = sorted({int(e) for e in (row.get("epochs") or []) if isinstance(e, int)} | {int(epoch or 1)})
            grants[task_id] = {"epochs": epochs, "granted_ms": self._now_ms()}
            cur["grants"] = grants
            data["nodes"][node_id] = cur
            self._write(data)

    def drop_grant(self, node_id: str, task_id: str) -> None:
        with self._lock():
            data = self._read()
            cur = data["nodes"].get(node_id)
            if isinstance(cur, Mapping) and task_id in (cur.get("grants") or {}):
                cur = dict(cur)
                grants = dict(cur.get("grants") or {})
                grants.pop(task_id, None)
                cur["grants"] = grants
                data["nodes"][node_id] = cur
                self._write(data)

    @staticmethod
    def granted_epochs(node: Mapping[str, Any] | None, task_id: str) -> list[int]:
        row = ((node or {}).get("grants") or {}).get(task_id)
        return [int(e) for e in (row or {}).get("epochs") or [] if isinstance(e, int)] if isinstance(row, Mapping) else []

    # --- authentication ----------------------------------------------------------------------------------------

    def authenticate(self, request: Mapping[str, Any], streams_root: Path | str | None = None) -> dict[str, Any]:
        """The node a signed request comes from, or `NodeError`: unknown / revoked node (`authz_denied`), a bad
        signature, a clock skew over 300 s, a nonce already seen (`replay`)."""
        auth = request.get("auth") if isinstance(request.get("auth"), Mapping) else {}
        body = request.get("body")
        node_id = str(auth.get("node_id") or "")
        ts = auth.get("ts_ms")
        nonce = str(auth.get("nonce") or "")
        sig = str(auth.get("sig") or "")
        if not node_id or not isinstance(ts, int) or isinstance(ts, bool) or not nonce or not sig \
                or not isinstance(body, Mapping):
            raise NodeError("bad_request", "missing auth fields")
        node = self.get(node_id)
        if node is None:
            raise NodeError("authz_denied", "unknown node")
        if node.get("revoked_ms"):
            raise NodeError("authz_denied", "node revoked")
        want = sign_request(str(node.get("secret") or ""), node_id, ts, nonce, dict(body))
        if not hmac.compare_digest(want, sig):
            raise NodeError("bad_signature", "signature does not match the node credential")
        now = self._now_ms()
        if abs(now - int(ts)) > CLOCK_SKEW_S * 1000:
            raise NodeError("clock_skew", f"request time is more than {CLOCK_SKEW_S}s off the coordinator's")
        if streams_root is not None and not NodeStreams(streams_root, node_id).note_nonce(nonce, int(ts), now):
            raise NodeError("replay", "nonce already used")
        return node


class NodeStreams:
    """The coordinator's side of one node: its pull queue, the observations it pushed, its heartbeat (see module)."""

    def __init__(self, root: Path | str, node_id: str) -> None:
        self.root = Path(root) / safe_name(node_id)
        self.node_id = node_id

    @property
    def inbox_path(self) -> Path:
        return self.root / "inbox.jsonl"

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def obs_path(self, slot: str) -> Path:
        return self.root / "obs" / f"{safe_name(slot)}.jsonl"

    def _lock(self) -> Any:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        return file_lock(self.root / ".lock", lock_fn=lock_file, unlock_fn=unlock_file)

    def state(self) -> dict[str, Any]:
        return _read_json(self.state_path)

    def _save_state(self, data: Mapping[str, Any]) -> None:
        _write_private(self.state_path, data)

    # --- pull queue --------------------------------------------------------------------------------------------

    def _inbox_rows(self) -> list[dict[str, Any]]:
        if not self.inbox_path.is_file():
            return []
        out = []
        for raw in self.inbox_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(raw)
            except ValueError:
                continue  # a torn last line (a crash mid-append) is skipped; its entry is re-appended by the retry
            if isinstance(row, dict) and isinstance(row.get("seq"), int):
                out.append(row)
        return out

    def append(self, slot: str, entry: Mapping[str, Any]) -> tuple[int, bool]:
        """Append one entry for `slot` (`env_id` its identity): `(seq, new)`; the same `(slot, env_id)` again returns
        the first `seq`."""
        env_id = str(entry.get("env_id") or "")
        with self._lock():
            rows = self._inbox_rows()
            if env_id:
                hit = next((r for r in rows if r.get("env_id") == env_id and r.get("slot") == slot), None)
                if hit is not None:
                    return int(hit["seq"]), False
            seq = (int(rows[-1]["seq"]) if rows else 0) + 1
            line = {**dict(entry), "seq": seq, "slot": slot}
            with open(self.inbox_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(self.inbox_path, 0o600)
            except OSError:
                pass
            return seq, True

    def entries_after(self, seq: int, *, limit: int = 200, max_bytes: int = 3 * 1024 * 1024) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        size = 0
        for row in self._inbox_rows():
            if int(row["seq"]) <= seq:
                continue
            n = len(json.dumps(row, ensure_ascii=False))
            if out and (len(out) >= limit or size + n > max_bytes):
                break
            out.append(row)
            size += n
        return out

    def entries_for(self, slot: str) -> list[dict[str, Any]]:
        return [r for r in self._inbox_rows() if r.get("slot") == slot]

    def head(self) -> int:
        rows = self._inbox_rows()
        return int(rows[-1]["seq"]) if rows else 0

    # --- heartbeat, nonces, slots ------------------------------------------------------------------------------

    def note_nonce(self, nonce: str, ts_ms: int, now_ms: int) -> bool:
        with self._lock():
            st = self.state()
            seen = dict(st.get("nonces") or {})
            if nonce in seen:
                return False
            floor = now_ms - 2 * CLOCK_SKEW_S * 1000
            seen = {k: v for k, v in seen.items() if isinstance(v, int) and v >= floor}
            seen[nonce] = int(ts_ms)
            if len(seen) > NONCE_KEEP:
                seen = dict(sorted(seen.items(), key=lambda kv: kv[1])[-NONCE_KEEP:])
            st["nonces"] = seen
            self._save_state(st)
            return True

    def record_sync(self, now_ms: int, *, inbox_acked: int) -> None:
        with self._lock():
            st = self.state()
            st["last_sync_ms"] = int(now_ms)
            st["inbox_acked_seq"] = max(int(st.get("inbox_acked_seq") or 0), int(inbox_acked or 0))
            self._save_state(st)

    def last_sync_ms(self) -> int:
        return int(self.state().get("last_sync_ms") or 0)

    def slot(self, slot: str) -> dict[str, Any]:
        row = (self.state().get("slots") or {}).get(slot)
        return dict(row) if isinstance(row, Mapping) else {}

    def set_slot(self, slot: str, **fields: Any) -> None:
        with self._lock():
            st = self.state()
            slots = dict(st.get("slots") or {})
            slots[slot] = {**dict(slots.get(slot) or {}), **fields}
            st["slots"] = slots
            self._save_state(st)

    # --- observations ------------------------------------------------------------------------------------------

    def append_obs(self, slot: str, rows: Iterable[Mapping[str, Any]]) -> int:
        """Store the node's observation rows for `slot` with `seq` past what is stored (a resent row is dropped);
        returns the highest stored `seq`."""
        with self._lock():
            st = self.state()
            slots = dict(st.get("slots") or {})
            cur = dict(slots.get(slot) or {})
            top = int(cur.get("obs_seq") or 0)
            fresh = sorted((dict(r) for r in rows if isinstance(r.get("seq"), int) and int(r["seq"]) > top),
                           key=lambda r: int(r["seq"]))
            if fresh:
                path = self.obs_path(slot)
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    for r in fresh:
                        f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                top = int(fresh[-1]["seq"])
                for r in fresh:
                    if r.get("kind") == "endpoint_state":
                        cur.update({k: r.get(k) for k in ("status", "reported", "gone") if k in r})
                        cur["state_ms"] = r.get("t")
                cur["obs_seq"] = top
                slots[slot] = cur
                st["slots"] = slots
                self._save_state(st)
            return top

    def obs_after(self, slot: str, seq: int, *, limit: int = 500) -> list[dict[str, Any]]:
        path = self.obs_path(slot)
        if not path.is_file():
            return []
        out = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("seq"), int) and row["seq"] > seq:
                out.append(row)
                if len(out) >= limit:
                    break
        return out
