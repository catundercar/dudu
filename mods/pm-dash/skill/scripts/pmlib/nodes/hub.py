"""The coordinator's sync endpoint for self-hosted worker nodes (`pm-message-routing.md` §5.3, §6.1, §7.2, §8.3,
§12.1 MR-D2; phase 6b). Layer 3 (nodes).

One pure request -> response handler (`SyncHub.handle`) serves both carriers with the same JSON, byte for byte:

- HTTPS: `POST /v1/worker/sync` (`nodes/wire.py`: a WSGI app, a `BaseHTTPRequestHandler` server, `pm.py worker-hub`);
- restricted SSH stdio: `ssh <hub> pm.py mailbox-sync --stdio` (one JSON request per line in, one JSON reply per line
  out).

Request `{"v": 1, "auth": {node_id, ts_ms, nonce, sig}, "body": {...}}` (HMAC-SHA256, `messaging/nodes.py`), or
`{"v": 1, "op": "join", "token": "enroll_...", ...}` to enroll. A sync body:

    {"op": "sync",
     "inbox_after": N,                     # the node stored the pull queue up to N (its ack)
     "outbox": [{task_id, epoch, seq, envelope, mac}],   # report lines (per-task HMAC with the task grant's token)
     "obs": [{task_id, epoch, slot, seq, kind, t, ...}],  # observations (endpoint_state, typed, consumed, ...)
     "bundles": [{task_id, branch, head, bundle}],        # the worker's branch, as a git bundle (base64)
     "context_versions": {"<tid>@<epoch>": "<digest>"},   # what context it holds
     "have_grants": ["<tid>@<epoch>"],                    # which task tokens it holds
     "capabilities": {...}}                                # what its local runtime can do

Reply `{"ok": true, inbox: [...], receipts: [{task_id, epoch, seq, status, code, ...}], outbox_acked: {key: seq},
obs_acked: {slot: seq}, contexts: {key: {version, context}}, grants: {key: {...}}, closed: [key], bundles: [...]}`;
a refusal `{"ok": false, "error": {"code", "message"}}` (`authz_denied` for a revoked node).

Each report line is checked like a remote hc worker's (phase 6a): the task must be one this node holds a grant for in
that epoch; its MAC must match that `(task, epoch)` token; the sender is bound from the grant, whatever the envelope
says; it is applied through `ReportApplier` once (a per-`(task, epoch)` cursor plus the applier's own idempotency).
A stale epoch's status report is archived with a P4 summary (MR-D4). A closed task's grant is over: its lines are
refused (`authz_denied`), never applied.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Mapping

from ..context import Context
from ..errors import Refused
from ..home import project_slug
from ..ledger.ledger import Ledger
from ..messaging.address import safe_endpoint_uid
from ..messaging.envelope import Envelope
from ..messaging.nodes import MAX_SYNC_BYTES, NodeError, NodeRegistry, NodeStreams, public_node
from ..messaging.outbox import TaskTokens, verify_envelope
from ..messaging.principal import Principal
from ..messaging.transports.self_hosted import LEASE_TIMEOUT_S, SelfHostedPullTransport
from ..messaging.typist import drain_endpoint
from ..reports import ReportApplier
from ..store import write_atomic
from ..workers.self_hosted import (
    SelfHostedWorkspace,
    context_version,
    is_closed_task,
    node_runs,
    self_hosted_context,
    self_hosted_endpoint,
)


CAP_KEYS = ("can_report_status", "can_interrupt", "can_unblock_keys", "can_observe_screen", "can_observe_procs",
            "can_observe_transcript")
HTTP_STATUS = {"bad_request": 400, "too_large": 413, "bad_signature": 401, "clock_skew": 401, "replay": 401,
               "authz_denied": 403, "invalid_token": 403, "token_used": 403, "token_expired": 403, "not_found": 404}


def task_key(task_id: str, epoch: int) -> str:
    return f"{task_id}@{int(epoch)}"


def error_reply(code: str, message: str = "") -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message or code}}


def http_status_of(reply: Mapping[str, Any]) -> int:
    if reply.get("ok"):
        return 200
    return HTTP_STATUS.get(str((reply.get("error") or {}).get("code") or ""), 400)


class SyncHub:
    """See the module docstring."""

    def __init__(self, ctx: Context, *, lease_timeout_s: float = LEASE_TIMEOUT_S) -> None:
        self.ctx = ctx
        self.registry = NodeRegistry(ctx.home.tokens, clock=ctx.clock)
        self.lease_timeout_s = float(lease_timeout_s)
        self._tokens = TaskTokens(ctx.home.tokens)

    def _now_ms(self) -> int:
        return int(float(self.ctx.clock.time()) * 1000)

    # --- carriers ------------------------------------------------------------------------------------------------

    def handle_bytes(self, raw: bytes | str) -> bytes:
        """One request's bytes -> one reply's bytes (a JSON object, no trailing newline): what HTTP and stdio share."""
        data = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
        if len(data) > MAX_SYNC_BYTES + 64 * 1024:
            reply = error_reply("too_large", f"request over {MAX_SYNC_BYTES} bytes")
        else:
            try:
                req = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                req = None
            reply = self.handle(req) if isinstance(req, Mapping) else error_reply("bad_request", "not a JSON object")
        return json.dumps(reply, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def handle(self, req: Mapping[str, Any]) -> dict[str, Any]:
        try:
            if req.get("op") == "join":
                return self._join(req)
            node = self.registry.authenticate(req, self.ctx.home.nodes)
            body = req.get("body") if isinstance(req.get("body"), Mapping) else {}
            op = str(body.get("op") or "sync")
            if op != "sync":
                return error_reply("bad_request", f"unknown op {op!r}")
            return self._sync(node, body)
        except NodeError as err:
            return error_reply(err.code, err.message)

    # --- join ----------------------------------------------------------------------------------------------------

    def _join(self, req: Mapping[str, Any]) -> dict[str, Any]:
        caps = req.get("capabilities") if isinstance(req.get("capabilities"), Mapping) else {}
        node = self.registry.join(str(req.get("token") or ""),
                                  capabilities={k: bool(caps.get(k)) for k in CAP_KEYS if k in caps},
                                  pm_command=str(req.get("pm_command") or "")[:300],
                                  label=str(req.get("label") or ""))
        return {"ok": True, "node": public_node({k: v for k, v in node.items() if k != "grants"}),
                "secret": node["secret"], "server_ms": self._now_ms(), "lease_timeout_s": self.lease_timeout_s}

    # --- sync ----------------------------------------------------------------------------------------------------

    def _node_tasks(self, node_id: str) -> dict[str, dict[str, Any]]:
        """Every task this node has run (open or not), by id."""
        return {str(t["id"]): t for t in Ledger(self.ctx).raw_tasks() if node_runs(t, node_id)}

    def _sync(self, node: Mapping[str, Any], body: Mapping[str, Any]) -> dict[str, Any]:
        node_id = str(node["node_id"])
        streams = NodeStreams(self.ctx.home.nodes, node_id)
        now = self._now_ms()
        caps = body.get("capabilities")
        if isinstance(caps, Mapping):
            new_caps = {k: bool(caps.get(k)) for k in CAP_KEYS if k in caps}
            if new_caps != dict(node.get("capabilities") or {}):
                self.registry.update(node_id, capabilities=new_caps)
        tasks = self._node_tasks(node_id)
        slots = {str(run.get("slot")): (tid, int(run.get("epoch") or 1))
                 for tid, t in tasks.items() for run in node_runs(t, node_id)}

        obs_acked = self._take_obs(streams, slots, body.get("obs"))
        bundles = self._take_bundles(node, tasks, body.get("bundles"))
        receipts, outbox_acked = self._take_outbox(node, tasks, body.get("outbox"))

        inbox_after = body.get("inbox_after")
        inbox_after = int(inbox_after) if isinstance(inbox_after, int) and not isinstance(inbox_after, bool) else 0
        streams.record_sync(now, inbox_acked=inbox_after)

        # Re-read tasks after applying outbox reports so closed tasks / updated contexts reflect immediately.
        tasks = self._node_tasks(node_id)

        # What waited for this node (queued while it was away, or since its last sync) goes to its pull queue now.
        current = {tid: t for tid, t in tasks.items()
                   if not is_closed_task(t) and (t.get("self_hosted") or {}).get("node_id") == node_id}
        transport = SelfHostedPullTransport(self.ctx, lease_timeout_s=self.lease_timeout_s)
        for task in current.values():
            ep = self_hosted_endpoint(task)
            if ep is not None:
                drain_endpoint(self.ctx, ep, wait_s=0, transport=transport)

        have_ctx = body.get("context_versions") if isinstance(body.get("context_versions"), Mapping) else {}
        have_grants = {str(k) for k in (body.get("have_grants") or []) if isinstance(k, str)}
        contexts: dict[str, Any] = {}
        grants: dict[str, Any] = {}
        open_keys = set()
        for tid, task in current.items():
            sh = task["self_hosted"]
            epoch = int(sh.get("epoch") or 1)
            if epoch not in NodeRegistry.granted_epochs(self.registry.get(node_id), tid):
                continue
            key = task_key(tid, epoch)
            open_keys.add(key)
            c = self_hosted_context(self.ctx, task)
            ver = context_version(c)
            if have_ctx.get(key) != ver:
                contexts[key] = {"version": ver, "context": c}
            if key not in have_grants:
                grants[key] = self._tokens.issue(tid, epoch, machine=node_id)
        closed = sorted(k for k in set(have_ctx) | have_grants if k not in open_keys)
        return {
            "ok": True,
            "node_id": node_id,
            "server_ms": now,
            "lease_timeout_s": self.lease_timeout_s,
            "inbox": streams.entries_after(inbox_after),
            "inbox_head": streams.head(),
            "receipts": receipts,
            "outbox_acked": outbox_acked,
            "obs_acked": obs_acked,
            "contexts": contexts,
            "grants": grants,
            "closed": closed,
            "bundles": bundles,
        }

    def _take_obs(self, streams: NodeStreams, slots: Mapping[str, tuple[str, int]], rows: Any) -> dict[str, int]:
        by_slot: dict[str, list[dict[str, Any]]] = {}
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, Mapping) and str(row.get("slot") or "") in slots:
                by_slot.setdefault(str(row["slot"]), []).append(dict(row))
        return {slot: streams.append_obs(slot, rs) for slot, rs in by_slot.items()}

    @staticmethod
    def _project_allowed(node: Mapping[str, Any], task: Mapping[str, Any] | None) -> bool:
        if not isinstance(task, Mapping):
            return False
        allowed = {str(p) for p in (node.get("projects") or []) if p}
        if "*" in allowed:
            return True
        repo = str(task.get("repo") or "")
        slug = project_slug(repo) if repo else str(task.get("project") or "")
        return bool(slug and slug in allowed)

    def _take_bundles(self, node: Mapping[str, Any], tasks: Mapping[str, Any], rows: Any) -> list[dict[str, Any]]:
        out = []
        ws = SelfHostedWorkspace(self.ctx)
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            tid = str(row.get("task_id") or "")
            task = tasks.get(tid)
            res = {"task_id": tid, "head": str(row.get("head") or "")}
            if (task is None or is_closed_task(task)
                    or (task.get("self_hosted") or {}).get("node_id") != node["node_id"]
                    or not self._project_allowed(node, task)):
                out.append({**res, "status": "rejected", "code": "authz_denied"})
                continue
            try:
                got = ws.import_bundle(task, str(node["node_id"]), str(row.get("branch") or ""),
                                       str(row.get("bundle") or ""))
            except Refused as err:
                out.append({**res, "status": "rejected", "code": "bad_bundle", "reason": str(err)})
                continue
            out.append({**res, "status": "stored", "stored_head": got})
        return out

    # --- reports -------------------------------------------------------------------------------------------------

    def _cursor_path(self, repo: str, task_id: str, epoch: int) -> Path:
        files = self.ctx.home.project_for(repo)
        return Path(files.applied_reports_json).parent / "remote-sync" / f"{safe_endpoint_uid(task_id)}-e{int(epoch)}.json"

    def _take_outbox(self, node: Mapping[str, Any], tasks: Mapping[str, Any], rows: Any
                     ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        groups: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping) or not isinstance(row.get("seq"), int) or not row.get("task_id"):
                continue
            ep = row.get("epoch")
            groups.setdefault((str(row["task_id"]), int(ep) if isinstance(ep, int) else 1), []).append(row)
        receipts: list[dict[str, Any]] = []
        acked: dict[str, int] = {}
        node_id = str(node["node_id"])
        granted = self.registry.get(node_id)
        for (tid, epoch), lines in groups.items():
            lines = sorted(lines, key=lambda r: int(r["seq"]))
            key = task_key(tid, epoch)
            task = tasks.get(tid)
            runs = {int(r.get("epoch") or 1) for r in node_runs(task, node_id)}
            authorized = (task is not None and self._project_allowed(node, task)
                          and epoch in runs and epoch in NodeRegistry.granted_epochs(granted, tid))
            if not authorized:
                for r in lines:
                    receipts.append(self._receipt(tid, epoch, int(r["seq"]), "rejected", "authz_denied",
                                                  "this node holds no grant for that task and epoch"))
                acked[key] = int(lines[-1]["seq"])
                continue
            assert task is not None
            path = self._cursor_path(str(task.get("repo") or ""), tid, epoch)
            state = _read(path)
            cursor = int(state.get("outbox_seq") or 0)
            token = self._tokens.token_for(tid, epoch)
            for r in lines:
                seq = int(r["seq"])
                if seq <= cursor:
                    receipts.append(self._receipt(tid, epoch, seq, "applied", "duplicate", already=True))
                    continue
                if seq != cursor + 1:
                    break  # a gap: nothing past it is taken; the node sends from cursor + 1 again
                receipts.append(self._apply_line(task, node_id, epoch, token, r))
                cursor = seq
                state["outbox_seq"] = cursor
                _write(path, state)
            acked[key] = cursor
        return receipts, acked

    @staticmethod
    def _receipt(tid: str, epoch: int, seq: int, status: str, code: str = "", reason: str = "", *,
                 already: bool = False, late: bool = False) -> dict[str, Any]:
        return {"task_id": tid, "epoch": epoch, "seq": seq, "status": status, "code": code, "reason": reason,
                "already_applied": already, "late_report": late}

    def _apply_line(self, task: Mapping[str, Any], node_id: str, epoch: int, token: str,
                    row: Mapping[str, Any]) -> dict[str, Any]:
        tid = str(task["id"])
        fresh = self.ctx.store.task(tid)
        if isinstance(fresh, Mapping):
            task = fresh
        seq = int(row["seq"])
        raw_env = row.get("envelope") if isinstance(row.get("envelope"), Mapping) else {}
        if is_closed_task(task):
            self._note(tid, f"[self-hosted report seq={seq} (epoch {epoch}) refused: the task is closed]")
            return self._receipt(tid, epoch, seq, "rejected", "authz_denied", "the task is closed")
        if not token or not verify_envelope(token, raw_env, str(row.get("mac") or "")):
            self._note(tid, f"[self-hosted report seq={seq} (epoch {epoch}) refused: signature does not match "
                            f"the task token]")
            return self._receipt(tid, epoch, seq, "rejected", "bad_signature", "signature does not match the task token")
        try:
            env = Envelope.from_dict(raw_env)
        except (ValueError, TypeError) as err:
            return self._receipt(tid, epoch, seq, "rejected", "bad_request", f"unreadable envelope: {err}")
        repo = str(task.get("repo") or "")
        slug = project_slug(repo) if repo else str(env.project or "")
        bound = Principal.worker(slug, tid, epoch=epoch, machine=node_id, credential_id=f"task-token:{tid}:{epoch}")
        body = dict(env.body) if isinstance(env.body, Mapping) else {}
        # The node names no path of this machine (§6.5): the report is filed under the task's own project here.
        if repo:
            body["repo"] = repo
            if env.kind == "report.memory_write":
                body["project_repo"] = repo
        env = dataclasses.replace(env, sender=bound, project=slug, body=body)
        wctx = dataclasses.replace(self.ctx, pane=str(task.get("pane") or ""), hc_terminal="", caller=None)
        rec = ReportApplier(wctx).apply_envelope(env, raise_errors=False)
        return self._receipt(tid, epoch, seq, rec.status, rec.code, rec.reason, already=rec.already_applied,
                             late=rec.late_report)

    def _note(self, tid: str, text: str) -> None:
        def _log(cur: Any, ch: Any) -> dict[str, Any]:
            assert cur is not None
            ch.note(text, source="self_hosted_sync", wake=True)
            return cur.raw

        Ledger(self.ctx).change(tid, _log)


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, (json.dumps(dict(data), indent=2) + "\n").encode("utf-8"))
