"""`pm.py worker-agent`: the self-hosted node's side (`pm-message-routing.md` §5.3 column 3, §6.5, §7.2, §8.3; phase
6b). Layer 3 (nodes).

The node never holds a ledger and is never called: each cycle it connects out to the hub (HTTPS or SSH stdio) with
one signed sync request that carries what it buffered (report outbox lines, observations, the worker's branch as a
bundle) and brings back what waits for it (the pull queue, task grants, contexts), then types what it got into its
local runtime through a driver. Offline, everything stays in its state folder and goes on the next successful sync
(exponential backoff 2 s -> 60 s); nothing is lost (cursors move only on the hub's receipts) and nothing is applied
twice (the hub's per-(task, epoch) cursor and the applier's idempotency keys).

Layout of `<worker_state>` (0700):

- `credential.json`  `{node_id, secret, alias, hub, projects}` (0600, created exclusively under umask 077).
- `agent.json`       hub, repos (`{slug: clone}`), worktrees root, pm/worker commands, cursors, backoff.
- `inbox.jsonl`      the pull queue as stored here (0600), `seq` as the hub numbered it.
- `tasks/<task>-e<epoch>/`  one worker state folder per task (`PM_WORKER_STATE` of its session): `context.json`
  (§6.5: task metadata and this project's memories only), `credential.json` (the task grant's token), `outbox.jsonl`
  (written by the worker's own `pm.py update|log|remember|helper done`), `obs-journal.jsonl`, `delivered.json`.

Drivers (`start`, `deliver`, `interrupt`, `keys`, `status`, `capabilities`): `HcDriver` (this machine's herdr-core,
typing through `LocalHcTransport`), `FileDriver` (no live session: prompts are written to the task folder for a
person or a script), or any object with those methods (tests).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping

from ..messaging.address import Endpoint
from ..messaging.envelope import Envelope, format_deliver_text
from ..messaging.mailbox import MailboxItem
from ..messaging.nodes import MAX_SYNC_BYTES, safe_name, signed_request
from ..messaging.outbox import CONTEXT_FILE, CREDENTIAL_FILE, WorkerObsJournal, WorkerOutbox
from ..messaging.transports.local_hc import LocalHcTransport
from ..store import write_atomic
from .wire import HubUnavailable


CREDENTIAL = "credential.json"
AGENT_FILE = "agent.json"
INBOX_FILE = "inbox.jsonl"
DELIVERED_FILE = "delivered.json"
BACKOFF_MIN_S = 2.0
BACKOFF_MAX_S = 60.0
IDLE_POLL_S = 5.0
OUTBOX_BATCH = 200
MAX_BUNDLE_BYTES = 3 * 1024 * 1024
RETRY_LATER = frozenset({"status_mismatch", "blocked_prompt", "partitioned", "timeout_uncertain", "not_ready"})
DEFAULT_STATE = "~/.herdr/pm-worker-agent"


class AgentError(Exception):
    """A refusal on the node side (no credential, credential already there, a revoked node)."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, data: Mapping[str, Any], *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, (json.dumps(dict(data), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    if private:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def write_private_exclusive(path: Path, data: Mapping[str, Any]) -> None:
    """Create `path` with mode 0600 from its first byte (umask 077, `O_EXCL`): never readable by others, never over
    an existing file (`FileExistsError`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    old = os.umask(0o077)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    finally:
        os.umask(old)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(dict(data), indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())


def write_private(path: Path, data: Mapping[str, Any]) -> None:
    """Replace `path` (0600 from its first byte) atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.unlink()
    except OSError:
        pass
    write_private_exclusive(tmp, data)
    os.replace(tmp, path)


def default_state_dir(env: Mapping[str, str] | None = None) -> Path:
    raw = str((env or {}).get("PM_WORKER_AGENT_STATE") or "").strip() or DEFAULT_STATE
    return Path(raw).expanduser()


# --- join -------------------------------------------------------------------------------------------------------


def join(state_dir: Path, client: Any, token: str, *, hub: str, hub_command: list[str] | None = None,
         repos: Mapping[str, str] | None = None, worktrees: str = "", pm_command: str = "",
         worker_command: list[str] | None = None, capabilities: Mapping[str, Any] | None = None,
         force: bool = False) -> dict[str, Any]:
    """Exchange an enrollment token for this node's credential and write the node's state folder."""
    cred_path = state_dir / CREDENTIAL
    if cred_path.exists() and not force:
        raise AgentError(f"{cred_path} exists: this folder already belongs to a node (pass --force to replace it, "
                         f"or use another --state)")
    reply = client.call({"v": 1, "op": "join", "token": token, "capabilities": dict(capabilities or {}),
                         "pm_command": pm_command})
    if not reply.get("ok"):
        err = reply.get("error") or {}
        raise AgentError(f"join refused: {err.get('code')}: {err.get('message')}")
    node = reply.get("node") or {}
    cred = {"node_id": str(node.get("node_id") or ""), "secret": str(reply.get("secret") or ""),
            "alias": str(node.get("alias") or ""), "projects": list(node.get("projects") or []), "hub": hub}
    if not cred["node_id"] or not cred["secret"]:
        raise AgentError("join reply without a node id or secret")
    if cred_path.exists():
        cred_path.unlink()
    write_private_exclusive(cred_path, cred)
    agent = _read_json(state_dir / AGENT_FILE)
    agent.update({"hub": hub, "hub_command": list(hub_command or []), "repos": dict(repos or agent.get("repos") or {}),
                  "worktrees": worktrees or agent.get("worktrees") or str(state_dir / "worktrees"),
                  "pm_command": pm_command or agent.get("pm_command") or "",
                  "worker_command": list(worker_command or agent.get("worker_command") or [])})
    agent.pop("revoked", None)
    _write_json(state_dir / AGENT_FILE, agent)
    return {**cred, "secret": "***"}


# --- drivers ----------------------------------------------------------------------------------------------------


class FileDriver:
    """No live session: each prompt is appended to `<task>/prompts.jsonl` (for a person, a script, a CI job)."""

    def capabilities(self) -> dict[str, bool]:
        return {"can_report_status": False, "can_interrupt": False, "can_unblock_keys": False,
                "can_observe_screen": False, "can_observe_procs": False, "can_observe_transcript": False}

    def start(self, task: TaskState, brief: Envelope) -> str:
        return self.deliver(task, brief)

    def deliver(self, task: TaskState, env: Envelope) -> str:
        with open(task.dir / "prompts.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"env_id": env.env_id, "kind": env.kind, "text": format_deliver_text(env)},
                               ensure_ascii=False) + "\n")
        return "typed"

    def interrupt(self, task: TaskState) -> str:
        return "unsupported"

    def keys(self, task: TaskState, keys: list[str]) -> bool:
        return False

    def status(self, task: TaskState) -> dict[str, Any]:
        return {"status": "", "reported": False, "gone": False}


class HcDriver:
    """The node's own herdr-core: one terminal per task (`hc run`), typed through `LocalHcTransport` (the same
    contract as on the coordinator's machine); the worker command comes from `agent.json` `worker_command`."""

    def __init__(self, ctx: Any, worker_command: list[str]) -> None:
        self.ctx = ctx
        self.worker_command = list(worker_command or [])
        self.transport = LocalHcTransport(ctx)

    def capabilities(self) -> dict[str, bool]:
        return {"can_report_status": True, "can_interrupt": True, "can_unblock_keys": True,
                "can_observe_screen": True, "can_observe_procs": False, "can_observe_transcript": False}

    def _ep(self, task: TaskState) -> Endpoint | None:
        term = str(task.meta.get("terminal") or "")
        return Endpoint(runtime="hc", machine=None, terminal=term, workspace=task.worktree) if term else None

    def start(self, task: TaskState, brief: Envelope) -> str:
        if not task.meta.get("terminal"):
            if not self.worker_command:
                return "rejected"
            argv = ["env", f"PM_WORKER_STATE={task.dir}", *self.worker_command]
            term = self.ctx.hc.start_terminal(f"{task.task_id}", task.worktree or str(task.dir), argv, ())
            if not term:
                return "not_ready"
            task.save_meta(terminal=str(term))
        return self.deliver(task, brief)

    def _item(self, env: Envelope) -> MailboxItem:
        now = int(time.time() * 1000)
        return MailboxItem(seq=1, envelope=env, state="accepted", attempts=0, accepted_ms=now, updated_ms=now)

    def deliver(self, task: TaskState, env: Envelope) -> str:
        ep = self._ep(task)
        if ep is None:
            return "not_ready"
        return self.transport.deliver(ep, self._item(env), if_idle=False).status

    def interrupt(self, task: TaskState) -> str:
        ep = self._ep(task)
        return self.transport.interrupt(ep).status if ep is not None else "endpoint_gone"

    def keys(self, task: TaskState, keys: list[str]) -> bool:
        ep = self._ep(task)
        return bool(ep is not None and self.transport.unblock_prompt(ep, keys))

    def status(self, task: TaskState) -> dict[str, Any]:
        ep = self._ep(task)
        if ep is None:
            return {"status": "", "reported": False, "gone": False}
        info = self.ctx.hc.get_raw(ep.hc_target, errors=True) or {}
        err = (info.get("error") or {}).get("kind") if isinstance(info.get("error"), Mapping) else info.get("error")
        if err in ("not_found", "finished") or str(info.get("state") or "") in ("exited", "finished", "removed"):
            return {"status": "", "reported": False, "gone": True}
        st = info.get("status") if isinstance(info.get("status"), Mapping) else {}
        return {"status": str(st.get("state") or ""), "reported": info.get("reported") is not False and bool(st),
                "gone": False}


# --- task folders -----------------------------------------------------------------------------------------------


@dataclass
class TaskState:
    """One task's worker state folder on the node."""

    dir: Path
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def task_id(self) -> str:
        return str(self.meta.get("task_id") or "")

    @property
    def epoch(self) -> int:
        return int(self.meta.get("epoch") or 1)

    @property
    def slot(self) -> str:
        return str(self.meta.get("slot") or "")

    @property
    def worktree(self) -> str:
        return str(self.meta.get("worktree") or "")

    @property
    def key(self) -> str:
        return f"{self.task_id}@{self.epoch}"

    def save_meta(self, **fields: Any) -> None:
        self.meta.update(fields)
        _write_json(self.dir / "task.json", self.meta)

    def delivered(self) -> set[str]:
        return set(_read_json(self.dir / DELIVERED_FILE).get("env_ids") or [])

    def mark_delivered(self, env_id: str) -> None:
        seen = sorted(self.delivered() | {env_id})[-500:]
        _write_json(self.dir / DELIVERED_FILE, {"env_ids": seen})


@dataclass
class Cycle:
    """What one sync cycle did."""

    ok: bool = False
    offline: bool = False
    revoked: bool = False
    error: str = ""
    pulled: int = 0
    handled: int = 0
    sent_reports: int = 0
    applied: int = 0
    rejected: int = 0
    next_s: float = IDLE_POLL_S
    receipts: list[dict[str, Any]] = field(default_factory=list)


class WorkerAgent:
    """See the module docstring."""

    def __init__(self, state_dir: Path | str, client: Any, driver: Any, *, clock: Any = None,
                 out: Callable[[str], None] | None = None, git_env: Mapping[str, str] | None = None) -> None:
        self.dir = Path(state_dir)
        self.client = client
        self.driver = driver
        self._clock = clock
        self._out = out or (lambda _t: None)
        self._git_env = dict(git_env) if git_env is not None else None
        cred = _read_json(self.dir / CREDENTIAL)
        if not cred.get("node_id") or not cred.get("secret"):
            raise AgentError(f"no node credential in {self.dir} (run `pm.py worker join` first)")
        self.cred = cred

    # --- state ---------------------------------------------------------------------------------------------------

    def _now_ms(self) -> int:
        return int(float(self._clock.time()) * 1000) if self._clock is not None else int(time.time() * 1000)

    def agent(self) -> dict[str, Any]:
        return _read_json(self.dir / AGENT_FILE)

    def _save_agent(self, data: Mapping[str, Any]) -> None:
        _write_json(self.dir / AGENT_FILE, data)

    def tasks(self) -> list[TaskState]:
        root = self.dir / "tasks"
        out = []
        for meta_path in sorted(root.glob("*/task.json")) if root.is_dir() else []:
            meta = _read_json(meta_path)
            if meta.get("task_id"):
                out.append(TaskState(dir=meta_path.parent, meta=meta))
        return out

    def task(self, task_id: str, epoch: int, *, create: bool = False, **meta: Any) -> TaskState | None:
        d = self.dir / "tasks" / f"{safe_name(task_id)}-e{int(epoch)}"
        if not (d / "task.json").is_file():
            if not create:
                return None
            d.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass
            ts = TaskState(dir=d, meta={"task_id": task_id, "epoch": int(epoch)})
            ts.save_meta(**meta)
            return ts
        ts = TaskState(dir=d, meta=_read_json(d / "task.json"))
        if meta:
            ts.save_meta(**{k: v for k, v in meta.items() if v not in (None, "")})
        return ts

    def task_by_slot(self, slot: str) -> TaskState | None:
        return next((t for t in self.tasks() if t.slot == slot), None)

    def inbox(self) -> list[dict[str, Any]]:
        path = self.dir / INBOX_FILE
        if not path.is_file():
            return []
        out = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("seq"), int):
                out.append(row)
        return out

    def _store_inbox(self, rows: list[dict[str, Any]], have: int) -> int:
        """Append rows past `have` in order (gap-free), fsynced; returns the new stored head."""
        path = self.dir / INBOX_FILE
        fresh = []
        nxt = have
        for row in sorted(rows, key=lambda r: int(r.get("seq") or 0)):
            if int(row["seq"]) <= nxt:
                continue
            if int(row["seq"]) != nxt + 1:
                break
            fresh.append(row)
            nxt = int(row["seq"])
        if fresh:
            old = os.umask(0o077)
            try:
                with open(path, "a", encoding="utf-8") as f:
                    for row in fresh:
                        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            finally:
                os.umask(old)
        return nxt

    def obs(self, task: TaskState, kind: str, **fields: Any) -> None:
        WorkerObsJournal(task.dir).append(kind, t=self._now_ms(), task_id=task.task_id, epoch=task.epoch,
                                          slot=task.slot, **fields)

    # --- one cycle -----------------------------------------------------------------------------------------------

    def run_once(self, *, force: bool = True) -> Cycle:
        agent = self.agent()
        if agent.get("revoked"):
            return Cycle(revoked=True, error="this node was revoked by the coordinator; join again to come back")
        now = self._now_ms()
        if not force and now < int(agent.get("next_attempt_ms") or 0):
            return Cycle(offline=True, next_s=(int(agent["next_attempt_ms"]) - now) / 1000.0, error="backing off")
        self._sense()
        body = self._body(agent)
        try:
            reply = self.client.call(signed_request(self.cred, body, now_ms=self._now_ms()))
        except HubUnavailable as err:
            return self._failed(agent, str(err), offline=True)
        if not reply.get("ok"):
            err = reply.get("error") or {}
            code = str(err.get("code") or "error")
            if code == "authz_denied":
                agent["revoked"] = True
                self._save_agent(agent)
                self._out(f"[worker-agent] the coordinator refused this node: {err.get('message')} (authz_denied)")
                return Cycle(revoked=True, error=f"authz_denied: {err.get('message')}")
            return self._failed(agent, f"{code}: {err.get('message')}", offline=False)
        cyc = self._take(agent, reply)
        handled = self._materialize()
        cyc.handled = handled
        return cyc

    def _failed(self, agent: dict[str, Any], why: str, *, offline: bool) -> Cycle:
        n = int(agent.get("fail_count") or 0) + 1
        wait = min(BACKOFF_MIN_S * (2 ** (n - 1)), BACKOFF_MAX_S)
        agent.update(fail_count=n, backoff_s=wait, next_attempt_ms=self._now_ms() + int(wait * 1000), last_error=why)
        self._save_agent(agent)
        return Cycle(offline=offline, error=why, next_s=wait)

    def _sense(self) -> None:
        """Push each live task's endpoint state when it changed (the hub's `if_idle`, I4 `gone`)."""
        for t in self.tasks():
            if t.meta.get("closed") or not t.meta.get("started"):
                continue
            try:
                st = dict(self.driver.status(t) or {})
            except Exception as err:  # noqa: BLE001 - a broken local runtime is reported, never fatal to the sync
                st = {"status": "", "reported": False, "gone": False, "error": str(err)[:200]}
            sig = [st.get("status"), bool(st.get("reported")), bool(st.get("gone"))]
            if t.meta.get("last_state") != sig:
                self.obs(t, "endpoint_state", status=str(st.get("status") or ""), reported=bool(st.get("reported")),
                         gone=bool(st.get("gone")))
                t.save_meta(last_state=sig)

    def _body(self, agent: Mapping[str, Any]) -> dict[str, Any]:
        acked = dict(agent.get("outbox_acked") or {})
        obs_acked = dict(agent.get("obs_acked") or {})
        outbox: list[dict[str, Any]] = []
        obs: list[dict[str, Any]] = []
        bundles: list[dict[str, Any]] = []
        versions: dict[str, str] = {}
        grants: list[str] = []
        size = 0
        budget = MAX_SYNC_BYTES - 512 * 1024
        for t in self.tasks():
            key = t.key
            for line in WorkerOutbox(t.dir).lines(after_seq=int(acked.get(key) or 0))[:OUTBOX_BATCH]:
                row = {"task_id": t.task_id, "epoch": t.epoch, "seq": line.seq, "envelope": line.envelope,
                       "mac": line.mac}
                n = len(json.dumps(row, ensure_ascii=False))
                if outbox and size + n > budget:
                    break
                outbox.append(row)
                size += n
            for row in WorkerObsJournal(t.dir).lines(after_seq=int(obs_acked.get(t.slot) or 0))[:500]:
                obs.append({**row, "task_id": t.task_id, "epoch": t.epoch, "slot": t.slot})
            if t.meta.get("closed"):
                continue
            if t.meta.get("context_version"):
                versions[key] = str(t.meta["context_version"])
            if (t.dir / CREDENTIAL_FILE).is_file():
                grants.append(key)
            b = self._bundle(t)
            if b is not None and size + len(b["bundle"]) <= budget:
                bundles.append(b)
                size += len(b["bundle"])
        return {"op": "sync", "inbox_after": int(agent.get("inbox_seq") or 0), "outbox": outbox, "obs": obs,
                "bundles": bundles, "context_versions": versions, "have_grants": grants,
                "capabilities": dict(self.driver.capabilities())}

    def _take(self, agent: dict[str, Any], reply: Mapping[str, Any]) -> Cycle:
        cyc = Cycle(ok=True)
        for key, grant in (reply.get("grants") or {}).items():
            tid, _, ep = str(key).rpartition("@")
            t = self.task(tid, int(ep or 1), create=True)
            assert t is not None
            write_private(t.dir / CREDENTIAL_FILE, {k: grant.get(k) for k in ("task_id", "epoch", "credential_id",
                                                                               "token")})
        for key, row in (reply.get("contexts") or {}).items():
            tid, _, ep = str(key).rpartition("@")
            c = dict(row.get("context") or {})
            t = self.task(tid, int(ep or 1), create=True, slot=str(c.get("slot") or ""),
                          project=str(c.get("project") or ""), branch=str(c.get("branch") or ""),
                          base_sha=str(c.get("base_sha") or ""))
            assert t is not None
            _write_json(t.dir / CONTEXT_FILE, c)
            t.save_meta(context_version=str(row.get("version") or ""))
        acked = dict(agent.get("outbox_acked") or {})
        for key, seq in (reply.get("outbox_acked") or {}).items():
            if isinstance(seq, int):
                acked[key] = max(int(acked.get(key) or 0), seq)
        agent["outbox_acked"] = acked
        obs_acked = dict(agent.get("obs_acked") or {})
        for slot, seq in (reply.get("obs_acked") or {}).items():
            if isinstance(seq, int):
                obs_acked[slot] = max(int(obs_acked.get(slot) or 0), seq)
        agent["obs_acked"] = obs_acked
        for rec in reply.get("receipts") or []:
            cyc.receipts.append(dict(rec))
            if rec.get("status") == "rejected":
                cyc.rejected += 1
                self._out(f"[worker-agent] report {rec.get('task_id')} seq={rec.get('seq')} rejected: "
                          f"{rec.get('code')} {rec.get('reason')}".rstrip())
            elif not rec.get("already_applied"):
                cyc.applied += 1
        heads = dict(agent.get("uploaded_heads") or {})
        for b in reply.get("bundles") or []:
            if b.get("status") == "stored":
                heads[str(b.get("task_id"))] = str(b.get("head") or "")
            else:
                self._out(f"[worker-agent] branch upload for {b.get('task_id')} refused: {b.get('code')} "
                          f"{b.get('reason') or ''}".rstrip())
                heads[str(b.get("task_id"))] = str(b.get("head") or "")  # said once; the next head tries again
        agent["uploaded_heads"] = heads
        for key in reply.get("closed") or []:
            tid, _, ep = str(key).rpartition("@")
            t = self.task(tid, int(ep or 1))
            if t is not None and not t.meta.get("closed"):
                t.save_meta(closed=True)
        rows = [dict(r) for r in reply.get("inbox") or [] if isinstance(r, Mapping) and isinstance(r.get("seq"), int)]
        have = int(agent.get("inbox_seq") or 0)
        head = self._store_inbox(rows, have)
        cyc.pulled = head - have
        agent["inbox_seq"] = head
        cyc.sent_reports = sum(1 for r in cyc.receipts if not r.get("already_applied"))
        agent.update(fail_count=0, backoff_s=0, next_attempt_ms=0, last_sync_ms=self._now_ms(), last_error="")
        self._save_agent(agent)
        return cyc

    # --- typing what came ----------------------------------------------------------------------------------------

    def _materialize(self) -> int:
        """Run each stored entry past `handled_seq`, in order; one that cannot go in yet stops the run (it is
        tried again next cycle, ahead of what came after it)."""
        agent = self.agent()
        handled = int(agent.get("handled_seq") or 0)
        n = 0
        for row in self.inbox():
            seq = int(row["seq"])
            if seq <= handled:
                continue
            done = self._handle(row)
            if not done:
                break
            handled = seq
            n += 1
            agent = self.agent()
            agent["handled_seq"] = handled
            self._save_agent(agent)
        return n

    def _handle(self, row: Mapping[str, Any]) -> bool:
        slot = str(row.get("slot") or "")
        env_raw = row.get("envelope")
        env = Envelope.from_dict(env_raw) if isinstance(env_raw, Mapping) else None
        t = self.task_by_slot(slot)
        if t is None and env is not None and env.kind == "cmd.brief":
            body = env.body if isinstance(env.body, Mapping) else {}
            t = self.task(str(body.get("task_id") or ""), int(body.get("epoch") or 1), create=True, slot=slot,
                          project=str(body.get("project") or ""), branch=str(body.get("branch") or ""),
                          base_sha=str(body.get("base_sha") or ""))
        if t is None:
            return True  # nothing here knows that slot (a task closed and cleaned up): skipped, not retried
        if t.meta.get("closed"):
            return True
        ctrl = str(row.get("ctrl") or "")
        if ctrl == "interrupt":
            out = self.driver.interrupt(t)
            self.obs(t, "interrupt_outcome", outcome=str(out), ctrl_id=str(row.get("env_id") or ""))
            return True
        if ctrl == "keys":
            ok = self.driver.keys(t, [str(k) for k in row.get("keys") or []])
            self.obs(t, "keys_sent", ok=bool(ok), keys=list(row.get("keys") or []))
            return True
        if env is None:
            return True
        if env.env_id in t.delivered():
            return True  # typed before a crash that lost the cursor: never twice
        if env.kind == "cmd.brief":
            self._prepare(t, env)
            status = self.driver.start(t, env)
            if status == "typed":
                t.save_meta(started=True)
        else:
            status = self.driver.deliver(t, env)
        if status in RETRY_LATER:
            return False
        if status == "typed":
            t.mark_delivered(env.env_id)
            self.obs(t, "typed", env_id=env.env_id, env_kind=env.kind)
        else:
            self.obs(t, "deliver_failed", env_id=env.env_id, env_kind=env.kind, outcome=str(status))
        return True

    # --- git -----------------------------------------------------------------------------------------------------

    def _git(self, *args: str, cwd: str = "", input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
        argv = ["git", *(["-C", cwd] if cwd else []), *args]
        return subprocess.run(argv, input=input_bytes, capture_output=True, timeout=300, env=self._git_env)

    def _prepare(self, t: TaskState, brief: Envelope) -> None:
        """The task's worktree in this node's clone of the project (`agent.json` `repos`): reused, else checked
        out from the branch, else made from the base commit (fetched first when the clone lacks it)."""
        if t.worktree and Path(t.worktree).is_dir():
            return
        body = brief.body if isinstance(brief.body, Mapping) else {}
        agent = self.agent()
        project = str(body.get("project") or t.meta.get("project") or "")
        branch = str(body.get("branch") or t.meta.get("branch") or "")
        base_sha = str(body.get("base_sha") or t.meta.get("base_sha") or "")
        clone = str((agent.get("repos") or {}).get(project) or "")
        if not clone or not branch:
            self.obs(t, "workspace_missing", reason=f"no clone of {project!r} configured on this node" if not clone
                     else "no branch")
            return
        clone = str(Path(clone).expanduser())
        wt = Path(str(agent.get("worktrees") or self.dir / "worktrees")).expanduser() / project / branch.replace("/", "-")
        if wt.is_dir():
            t.save_meta(worktree=str(wt))
            return
        wt.parent.mkdir(parents=True, exist_ok=True)
        if self._git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=clone).returncode == 0:
            res = self._git("worktree", "add", str(wt), branch, cwd=clone)
        else:
            if base_sha and self._git("cat-file", "-e", f"{base_sha}^{{commit}}", cwd=clone).returncode != 0:
                self._git("fetch", "--all", "--quiet", cwd=clone)
            res = self._git("worktree", "add", "-b", branch, str(wt), base_sha or "HEAD", cwd=clone)
        if res.returncode == 0:
            t.save_meta(worktree=str(wt))
        else:
            self.obs(t, "workspace_failed", reason=(res.stderr or b"").decode("utf-8", "replace").strip()[-300:])

    def _bundle(self, t: TaskState) -> dict[str, Any] | None:
        """The worker's branch as a bundle when its head moved since the last upload (past the base)."""
        branch = str(t.meta.get("branch") or "")
        if not t.worktree or not branch or not Path(t.worktree).is_dir():
            return None
        res = self._git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=t.worktree)
        head = (res.stdout or b"").decode().strip() if res.returncode == 0 else ""
        base = str(t.meta.get("base_sha") or "")
        if not head or head == base or head == str((self.agent().get("uploaded_heads") or {}).get(t.task_id) or ""):
            return None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.bundle"
            spec = [f"refs/heads/{branch}"] + ([f"^{base}"] if base else [])
            made = self._git("bundle", "create", str(path), *spec, cwd=t.worktree)
            if made.returncode != 0:
                made = self._git("bundle", "create", str(path), f"refs/heads/{branch}", cwd=t.worktree)
            if made.returncode != 0 or not path.is_file():
                return None
            data = path.read_bytes()
        if len(data) > MAX_BUNDLE_BYTES:
            self.obs(t, "bundle_too_large", head=head, size=len(data))
            return None
        return {"task_id": t.task_id, "branch": branch, "head": head, "bundle": base64.b64encode(data).decode("ascii")}

    # --- the loop ------------------------------------------------------------------------------------------------

    def run(self, *, interval_s: float = IDLE_POLL_S, max_cycles: int | None = None,
            sleep: Callable[[float], None] = time.sleep) -> Cycle:
        n = 0
        last = Cycle()
        while max_cycles is None or n < max_cycles:
            last = self.run_once(force=False)
            n += 1
            if last.revoked:
                break
            wait = last.next_s if last.offline else (0.5 if last.pulled or last.handled else float(interval_s))
            sleep(max(0.2, float(wait)))
        return last
