"""The report path (`pm-message-routing.md` §6, §9.2 wave 4): `pm.py update | log | remember | helper done` as
`report.*` envelopes. `ReportClient` builds and submits them; on this machine `LocalReportTransport` hands them in
process to `ReportApplier`, which authorizes the sender (`authorize_envelope`), applies them idempotently (the
idempotency key kept in the target file under its lock, C6a) and answers with an `ApplyReceipt`. Layer 3.

Two ways a report is refused, never silently (§6.4): submitted synchronously (every local command), the refusal
is raised to the command, which prints it and exits non-zero as it always did; queued (`queue_only`, the
cross-machine outbox to come), it becomes an `event.report_rejected` envelope routed to the worker or the PM."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .context import Context
from .errors import IdentityError, NotFound, PmError, Refused, StoreError
from .helpers.service import Helpers
from .home import project_slug
from .ledger.ledger import Ledger, slugify
from .ledger.task import pm_started
from .ledger.transition import Transition, UpdateRequest
from .memory.layer import MemoryLayer, clean_memory, read_memory
from .messaging.address import Endpoint, LogicalAddress, endpoint_from_dict
from .messaging.authz import authorize_envelope
from .messaging.envelope import P3_DIRECT, P4_BATCH, Envelope, new_env_id
from .messaging.mailbox import MailboxStore
from .messaging.principal import Principal, resolve_local_principal
from .messaging.router import EndpointSnapshot, Router, RoutingSnapshot
from .reactions import Say, Updates
from .store import file_lock, lock_file, unlock_file, write_atomic


MAX_APPLIED_RECEIPTS = 512


@dataclass(frozen=True)
class ApplyReceipt:
    """Result returned by `ReportApplier.apply_envelope` and `ReportClient.submit`."""

    env_id: str
    idempotency_key: str
    status: str  # applied | rejected
    code: str = ""
    reason: str = ""
    already_applied: bool = False
    late_report: bool = False
    result: dict[str, Any] = field(default_factory=dict)


class _NoReceipts:
    """Where a report names no project (nothing to file its receipt under): no receipt is kept rather than a
    project folder made up from a working directory's name."""

    def get(self, idempotency_key: str) -> ApplyReceipt | None:
        return None

    def record(self, receipt: ApplyReceipt) -> None:
        return None


class AppliedReportsStore:
    """Crash-safe per-project `applied-reports.json` store protected by `applied-reports.lock`."""

    def __init__(self, json_path: Path | str, lock_path: Path | str, *, clock: Any = None) -> None:
        self.json_path = Path(json_path)
        self.lock_path = Path(lock_path)
        self._clock = clock

    def _now_ms(self) -> int:
        if self._clock is not None:
            return int(float(self._clock.time()) * 1000)
        return 0

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.json_path.is_file():
            return {"order": [], "receipts": {}}
        try:
            raw = json.loads(self.json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"order": [], "receipts": {}}
        if not isinstance(raw, dict):
            return {"order": [], "receipts": {}}
        order = [str(k) for k in (raw.get("order") or []) if isinstance(k, str)]
        receipts = dict(raw.get("receipts") or {}) if isinstance(raw.get("receipts"), Mapping) else {}
        return {"order": order, "receipts": receipts}

    def get(self, idempotency_key: str) -> ApplyReceipt | None:
        if not idempotency_key:
            return None
        with file_lock(self.lock_path, lock_fn=lock_file, unlock_fn=unlock_file):
            data = self._read_unlocked()
            row = (data.get("receipts") or {}).get(idempotency_key)
        if not isinstance(row, Mapping):
            return None
        return ApplyReceipt(
            env_id=str(row.get("env_id") or ""),
            idempotency_key=idempotency_key,
            status=str(row.get("status") or "applied"),
            code=str(row.get("code") or ""),
            reason=str(row.get("reason") or ""),
            already_applied=True,
            late_report=bool(row.get("late_report")),
            result=dict(row.get("result") or {}) if isinstance(row.get("result"), Mapping) else {},
        )

    def has_key(self, idempotency_key: str) -> bool:
        return self.get(idempotency_key) is not None

    def record(self, receipt: ApplyReceipt) -> None:
        if not receipt.idempotency_key:
            return
        with file_lock(self.lock_path, lock_fn=lock_file, unlock_fn=unlock_file):
            data = self._read_unlocked()
            order = [k for k in data["order"] if k != receipt.idempotency_key]
            receipts = data["receipts"]
            order.append(receipt.idempotency_key)
            while len(order) > MAX_APPLIED_RECEIPTS:
                evict = order.pop(0)
                receipts.pop(evict, None)
            receipts[receipt.idempotency_key] = {
                "env_id": receipt.env_id,
                "status": receipt.status,
                "code": receipt.code,
                "reason": receipt.reason,
                "late_report": bool(receipt.late_report),
                "at_ms": self._now_ms(),
                "result": dict(receipt.result),
            }
            payload = (json.dumps({"order": order, "receipts": receipts}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            self.json_path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(self.json_path, payload)


@dataclass
class LocalFacts:
    """What only an in-process (same machine, same session) submit can hand the applier besides the envelope: the
    callback that writes each line as `pm.py update` says it, the `UpdateRequest` object itself (no JSON round
    trip), the memory writer as this session's caller resolves it, and a helper's stdin. Never sent anywhere."""

    say: Say | None = None
    request: UpdateRequest | None = None
    memory_writer: tuple[str, str] | None = None
    stdin_text: str | None = None
    from_stdin: bool = False


class ReportApplier:
    """Authorize and apply `report.*` envelopes with C6a locked `idem_key` recovery & §6.3/§6.4 safeguards."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._router = Router()

    def _project_repo(self, env: Envelope) -> str:
        body = env.body if isinstance(env.body, Mapping) else {}
        explicit = str(body.get("repo") or "").strip()
        if explicit:
            return explicit
        proj = env.project or env.recipient.project
        if proj:
            reg = self.ctx.store.registration(proj)
            if isinstance(reg, Mapping) and reg.get("repo"):
                return str(reg["repo"])
        tid = str(body.get("task_id") or "")
        if tid:
            t = self.ctx.store.task(tid)
            if isinstance(t, Mapping) and t.get("repo"):
                return str(t["repo"])
        return ""

    def _files_for(self, env: Envelope, repo: str):
        return self.ctx.home.project_for(repo or env.project)

    def _build_snapshot(self, env: Envelope, repo: str) -> RoutingSnapshot:
        slug = env.project or (project_slug(repo) if repo else "project")
        tasks_map: dict[str, dict[str, Any]] = {}
        body = env.body if isinstance(env.body, Mapping) else {}
        tid = str(body.get("task_id") or "")
        if tid:
            raw = self.ctx.store.task(tid)
            if isinstance(raw, dict):
                tasks_map[tid] = raw
        endpoints: dict[str, Endpoint] = {}
        endpoint_states: dict[str, EndpointSnapshot] = {}
        reg = self.ctx.store.registration(slug)
        if isinstance(reg, Mapping) and pm_started(reg):
            ep_raw = reg.get("endpoint")
            pm_ep = endpoint_from_dict(ep_raw) if isinstance(ep_raw, Mapping) else None
            if pm_ep is not None:
                endpoints[f"pm://{slug}"] = pm_ep
                endpoint_states[f"pm://{slug}"] = EndpointSnapshot(endpoint=pm_ep, live_state="live")
        if tid and tid in tasks_map:
            t_raw = tasks_map[tid]
            wk_ep = endpoint_from_dict(t_raw.get("endpoint")) if isinstance(t_raw.get("endpoint"), Mapping) else None
            if wk_ep is not None:
                endpoints[f"worker://{tid}"] = wk_ep
                endpoint_states[f"worker://{tid}"] = EndpointSnapshot(
                    endpoint=wk_ep,
                    live_state="closed" if t_raw.get("closed") else "live",
                )
        return RoutingSnapshot(
            project=slug,
            now_ms=int(float(self.ctx.clock.time()) * 1000),
            endpoints=endpoints,
            endpoint_states=endpoint_states,
            tasks=tasks_map,
        )

    def _emit_rejection(self, env: Envelope, snap: RoutingSnapshot, files: Any, *, code: str, reason: str) -> None:
        """§6.4.2: a queued report refused after its sender has moved on: an `event.report_rejected` envelope, to the
        worker when it is still there for a business refusal, else to the PM (an authorization refusal always)."""
        body = env.body if isinstance(env.body, Mapping) else {}
        tid = str(body.get("task_id") or env.sender.task_id or "")
        slug = snap.project
        authz_denied = code in ("authz_denied", "stale_epoch")
        rej_env = Envelope(
            env_id=new_env_id(snap.now_ms),
            idempotency_key=f"reject:{env.env_id}",
            schema_version=1,
            created_ms=snap.now_ms,
            kind="event.report_rejected",
            sender=Principal.supervisor(slug),
            recipient=LogicalAddress.worker(tid, project=slug) if tid else LogicalAddress.pm(slug),
            project=slug,
            cause={"kind": "report_rejected", "report_env_id": env.env_id},
            priority=P3_DIRECT if tid else P4_BATCH,
            body={
                "task_id": tid,
                "code": code or "rejected",
                "reason": reason,
                "authz_denied": authz_denied,
                "sender_epoch": int(env.sender.epoch or 1),
                "text": f"[report rejected: {reason}]" if reason else "[report rejected]",
            },
            require_reply=False,
        )
        decision = self._router.route(rej_env, snap)
        mb = MailboxStore(files.pm_mailbox, clock=self.ctx.clock)
        ep_uid = decision.endpoint.uid if decision.endpoint is not None else ""
        ep_epoch = decision.endpoint.epoch if decision.endpoint is not None else 0
        mb.enqueue(
            rej_env,
            initial_state="accepted",
            now_ms=snap.now_ms,
            target_endpoint_uid=ep_uid,
            endpoint_epoch=ep_epoch,
            meta={"targets": list(decision.targets), "rule_id": decision.rule_id},
        )

    def _emit_late_report(self, env: Envelope, snap: RoutingSnapshot, files: Any, *, current_epoch: int) -> None:
        slug = snap.project
        body = dict(env.body) if isinstance(env.body, Mapping) else {}
        tid = str(body.get("task_id") or env.sender.task_id or "")
        late_env = Envelope(
            env_id=new_env_id(snap.now_ms),
            idempotency_key=f"late:{env.env_id}",
            schema_version=1,
            created_ms=snap.now_ms,
            kind="event.late_report",
            sender=Principal.supervisor(slug),
            recipient=LogicalAddress.pm(slug),
            project=slug,
            cause={"kind": "stale_worker_epoch", "report_env_id": env.env_id},
            priority=P4_BATCH,
            body={
                "task_id": tid,
                "sender_epoch": int(env.sender.epoch or 1),
                "current_epoch": int(current_epoch),
                "report": body,
                "text": f"Late report from {env.sender.actor_id} (epoch {env.sender.epoch} < current {current_epoch}) on {tid}",
            },
            require_reply=False,
        )
        mb = MailboxStore(files.pm_mailbox, clock=self.ctx.clock)
        mb.enqueue(late_env, initial_state="accepted", now_ms=snap.now_ms)

    def _refused(
        self, env: Envelope, snap: RoutingSnapshot, files: Any, store: AppliedReportsStore, *,
        code: str, reason: str, raise_errors: bool, err: BaseException | None = None,
    ) -> ApplyReceipt:
        """Record a refused report (so a retry of the same envelope gets the same answer) and make it seen: raised
        to a synchronous caller (its command prints it and exits non-zero), else routed (§6.4.2)."""
        rec = ApplyReceipt(env_id=env.env_id, idempotency_key=env.idempotency_key, status="rejected", code=code,
                           reason=reason)
        store.record(rec)
        if raise_errors:
            if err is not None:
                raise err
            raise Refused(self.ctx.config.tr(f"refused: {reason}", f"已拒绝：{reason}"), code=1)
        if files is not None:
            self._emit_rejection(env, snap, files, code=code, reason=reason)
        return rec

    def _memory_already_written(self, body: Mapping[str, Any], repo: str) -> dict[str, Any] | None:
        """For a memory report caught mid-apply (an `applying` receipt): the memory it wrote, if it got that far."""
        layer = MemoryLayer(self.ctx, None if body.get("personal") else str(body.get("repo") or repo))
        text = clean_memory(str(body.get("text") or ""))
        name = slugify(str(body.get("name") or "")) if body.get("name") else ""
        if name:
            m = read_memory(layer.dir / f"{name}.md")
            return m if m and clean_memory(str(m.get("description") or "")) == text else None
        return next((m for m in layer.memories() if clean_memory(str(m.get("description") or "")) == text), None)

    def apply_envelope(
        self,
        env: Envelope,
        *,
        on_after_task_write: Callable[[Transition], None] | None = None,
        local: LocalFacts | None = None,
        raise_errors: bool = False,
    ) -> ApplyReceipt:
        """Apply one report. `raise_errors` (a synchronous submit): a refusal is raised to the caller (the
        `PmError` the service raised, unchanged, or `Refused` for an authorization refusal) after its receipt is
        recorded; `StoreError` / `IdentityError` pass through unrecorded (a retry may succeed)."""
        facts = local or LocalFacts()
        repo = self._project_repo(env)
        files = self._files_for(env, repo) if (repo or env.project) else None
        store: Any = (AppliedReportsStore(files.applied_reports_json, files.applied_reports_lock, clock=self.ctx.clock)
                      if files is not None else _NoReceipts())
        cached = store.get(env.idempotency_key)
        if cached is not None and cached.status != "applying":
            return cached

        snap = self._build_snapshot(env, repo)
        authz = authorize_envelope(env.sender, env, snap)
        if not authz.allowed:
            return self._refused(env, snap, files, store, code=authz.code or "authz_denied", reason=authz.reason,
                                 raise_errors=raise_errors)

        body = dict(env.body) if isinstance(env.body, Mapping) else {}
        try:
            return self._apply(env, body, repo, snap, files, store, cached, facts, on_after_task_write)
        except (StoreError, IdentityError):
            raise
        except PmError as err:
            return self._refused(env, snap, files, store, code=getattr(err, "kind", "") or "pm_error",
                                 reason=str(err), raise_errors=raise_errors, err=err)

    def _apply(
        self,
        env: Envelope,
        body: dict[str, Any],
        repo: str,
        snap: RoutingSnapshot,
        files: Any,
        store: AppliedReportsStore,
        cached: ApplyReceipt | None,
        facts: LocalFacts,
        on_after_task_write: Callable[[Transition], None] | None,
    ) -> ApplyReceipt:
        def _applied(result: Mapping[str, Any], **kw: Any) -> ApplyReceipt:
            rec = ApplyReceipt(env_id=env.env_id, idempotency_key=env.idempotency_key, status="applied",
                               result=dict(result), **kw)
            store.record(rec)
            return rec

        if env.kind == "report.task_update":
            tid = str(body.get("task_id") or "")
            existing = snap.tasks.get(tid) or self.ctx.store.task(tid) or {}
            ep_raw = existing.get("endpoint") if isinstance(existing, Mapping) else None
            cur_ep = endpoint_from_dict(ep_raw) if isinstance(ep_raw, Mapping) else None
            if (
                env.sender.role == "worker"
                and cur_ep is not None
                and int(cur_ep.epoch or 1) > int(env.sender.epoch or 1)
            ):
                self._emit_late_report(env, snap, files, current_epoch=int(cur_ep.epoch or 1))
                return _applied({"task_id": tid, "current_epoch": int(cur_ep.epoch or 1)}, code="late_report",
                                reason=f"worker epoch {env.sender.epoch} < current {cur_ep.epoch}", late_report=True)
            req = facts.request
            if req is None:
                req_data = {k: v for k, v in body.items() if k != "task_id" and hasattr(UpdateRequest, k)}
                req_data["id"] = tid
                req = UpdateRequest(**req_data)
            done = Updates(self.ctx).update(
                req,
                **({"say": facts.say} if facts.say is not None else {}),
                idem_key=env.idempotency_key,
                env_id=env.env_id,
                on_after_task_write=on_after_task_write,
            )
            already = bool(done.transition and done.transition.already_applied)
            return _applied({"task_id": done.task.get("id", tid), "status": done.task.get("status", "")},
                            already_applied=already)

        if env.kind == "report.task_log":
            tid = str(body.get("task_id") or "")
            text = str(body.get("text") or "")
            applied_now = {"already": False}

            def _log_apply(cur: Any, ch: Any) -> dict[str, Any] | None:
                assert cur is not None
                raw = cur.raw
                if env.idempotency_key:
                    amap = raw.get("applied_reports")
                    if isinstance(amap, dict) and env.idempotency_key in amap:
                        applied_now["already"] = True
                        return None
                ch.note(text, **({k: v for k, v in body.items() if k in ("source", "wake", "by")}))
                if env.idempotency_key:
                    amap = dict(raw.get("applied_reports") or {}) if isinstance(raw.get("applied_reports"), dict) else {}
                    order = [str(k) for k in (raw.get("last_applied_keys") or []) if isinstance(k, str) and k != env.idempotency_key]
                    order.append(env.idempotency_key)
                    while len(order) > 64:
                        amap.pop(order.pop(0), None)
                    amap[env.idempotency_key] = {"env_id": env.env_id, "at": self.ctx.clock.now(), "changes": []}
                    raw["applied_reports"] = amap
                    raw["last_applied_keys"] = order
                return raw

            Ledger(self.ctx).change(tid, _log_apply)
            return _applied({"task_id": tid}, already_applied=applied_now["already"])

        if env.kind == "report.memory_write":
            if cached is not None and cached.status == "applying":
                # Caught between writing the memory and recording the receipt: the file says whether it went.
                done_m = self._memory_already_written(body, repo)
                if done_m is not None:
                    return _applied({"name": done_m.get("name", ""), "notes": []}, already_applied=True)
            store.record(ApplyReceipt(env_id=env.env_id, idempotency_key=env.idempotency_key, status="applying"))
            target_repo = None if body.get("personal") else (str(body.get("repo") or repo))
            ml = MemoryLayer(self.ctx, repo=target_repo)
            writer = facts.memory_writer or (env.sender.role or "worker", env.sender.actor_id or "worker")
            mem, notes = ml.remember(
                str(body.get("text") or ""),
                writer=writer,
                kind=body.get("type") or body.get("kind"),
                name=body.get("name"),
                quote=str(body.get("quote") or ""),
                verified=str(body.get("verified") or ""),
                body=str(body.get("body") or ""),
                expires=str(body.get("expires") or ""),
                new=bool(body.get("new")),
                auto_name=bool(body.get("auto_name")),
                by=body.get("by"),
                when=str(body.get("when") or ""),
                quiet=bool(body.get("quiet")),
                topic=body.get("topic"),
                project_repo=str(body.get("project_repo") or repo),
            )
            return _applied({"name": mem.get("name", ""), "notes": list(notes)})

        if env.kind == "report.helper_done":
            # Idempotent by the helper's own record: once done, a second `done` only says so (no second notice).
            res = Helpers(self.ctx).done(
                name=body.get("name"),
                text=body.get("text"),
                stdin_text=facts.stdin_text,
                from_stdin=bool(facts.from_stdin),
                summary=body.get("summary"),
                task=body.get("task"),
                pm=bool(body.get("pm")),
                repo=str(body.get("helper_repo") or body.get("repo") or repo or "."),
            )
            return _applied({"name": getattr(res, "name", ""), "line": getattr(res, "line", ""),
                             "result": getattr(res, "result", ""),
                             "transitioned": bool(getattr(res, "transitioned", False))})

        raise Refused(f"unsupported report kind {env.kind!r}", code=1)


class LocalReportTransport:
    """The report transport of a command run on the coordinator's own machine: the envelope goes to the applier
    in this process, synchronously; a refusal comes back as the error it is (§6.4.1)."""

    def __init__(self, applier: ReportApplier) -> None:
        self.applier = applier

    def submit(
        self,
        env: Envelope,
        *,
        local: LocalFacts | None = None,
        on_after_task_write: Callable[[Transition], None] | None = None,
    ) -> ApplyReceipt:
        return self.applier.apply_envelope(env, local=local, on_after_task_write=on_after_task_write,
                                           raise_errors=True)


class ReportClient:
    """Where `pm.py update | log | remember | helper done` hand in their report: `submit` goes through the
    transport (on this machine, `LocalReportTransport`: applied now); `queue_only` leaves it in the project's
    inbound-reports mailbox for a later apply (the cross-machine outbox path)."""

    def __init__(self, ctx: Context, transport: Any = None) -> None:
        self.ctx = ctx
        self._applier = ReportApplier(ctx)
        self.transport = transport if transport is not None else LocalReportTransport(self._applier)

    def submit(
        self,
        env: Envelope,
        *,
        queue_only: bool = False,
        on_after_task_write: Callable[[Transition], None] | None = None,
        local: LocalFacts | None = None,
    ) -> ApplyReceipt:
        if queue_only:
            repo = self._applier._project_repo(env)
            files = self._applier._files_for(env, repo)
            mb = MailboxStore(files.inbound_reports_mailbox, clock=self.ctx.clock)
            item, _ = mb.enqueue(env, initial_state="accepted")
            return ApplyReceipt(
                env_id=item.envelope.env_id,
                idempotency_key=item.envelope.idempotency_key,
                status="applied",
                result={"queued": True, "seq": item.seq},
            )
        return self.transport.submit(env, local=local, on_after_task_write=on_after_task_write)

    def apply_queued(self, env: Envelope) -> ApplyReceipt:
        """Apply a queued report (no one is waiting on it: a refusal is routed as `event.report_rejected`)."""
        return self._applier.apply_envelope(env, raise_errors=False)


# --- The envelopes of the four report commands ------------------------------------------------------------------


def report_envelope(ctx: Context, kind: str, body: Mapping[str, Any], *, repo: str = "", task_id: str = "",
                    sender: Principal | None = None) -> Envelope:
    """A `report.*` envelope from this session: its sender as this machine resolves the caller (explicit
    `Principal`, never an environment variable taken at its word by the applier), a fresh idempotency key per
    invocation (`rep:<actor>:<env_id>`; a retry of the same envelope keeps it), addressed to `ledger://<slug>`."""
    now = int(float(ctx.clock.time()) * 1000)
    project = project_slug(repo) if repo else ""
    who = sender if sender is not None else resolve_local_principal(ctx, project)
    env_id = new_env_id(now)
    return Envelope(
        env_id=env_id,
        idempotency_key=f"rep:{who.actor_id}:{env_id}",
        schema_version=1,
        created_ms=now,
        kind=kind,
        sender=who,
        recipient=LogicalAddress.ledger(project or "local"),
        project=project,
        cause={"kind": "report", "task_id": task_id},
        priority=P3_DIRECT,
        body={**dict(body), **({"task_id": task_id} if task_id else {}), **({"repo": repo} if repo else {})},
    )


def task_update_report(ctx: Context, req: UpdateRequest) -> Envelope:
    """`pm.py update`: the request's fields as the body; the task id resolved first (a short `alpha#1` names the
    same task the sender's authorization is checked against)."""
    task = Ledger(ctx).load(req.id).raw
    body = {k: getattr(req, k) for k in UpdateRequest.__annotations__ if k != "id" and getattr(req, k, None) is not None}
    return report_envelope(ctx, "report.task_update", body, repo=str(task.get("repo") or ""), task_id=str(task["id"]))


def task_log_report(ctx: Context, task_id: str, text: str) -> Envelope:
    """`pm.py log`: one line on the task's log."""
    task = Ledger(ctx).load(task_id).raw
    return report_envelope(ctx, "report.task_log", {"text": text}, repo=str(task.get("repo") or ""),
                           task_id=str(task["id"]))


def memory_report(ctx: Context, repo: str, *, personal: bool = False, **fields: Any) -> Envelope:
    """`pm.py remember`: the memory's fields (`type` is its kind); `repo`: the project it is written for."""
    body = {k: v for k, v in fields.items() if v is not None}
    body["personal"] = bool(personal)
    body["project_repo"] = repo
    return report_envelope(ctx, "report.memory_write", body, repo=repo)


def helper_done_report(ctx: Context, *, repo: str = ".", task: str | None = None, **fields: Any) -> Envelope:
    """`pm.py helper done`: which helper, its conclusion (`text`; stdin stays a local fact) and summary. `repo` is
    the command's `--repo` (as `Helpers.done` takes it); the report is filed under the project the helper works
    for: the calling helper's own, else the `--task`'s, else the project `repo` is in."""
    body = {k: v for k, v in fields.items() if v is not None}
    body["helper_repo"] = repo or "."
    if task:
        body["task"] = task
    project_repo = ""
    caller = getattr(ctx, "caller", None)
    helper = getattr(caller, "helper", None) if caller is not None else None
    if isinstance(helper, Mapping) and helper.get("project"):
        project_repo = str((ctx.store.registration(str(helper["project"])) or {}).get("repo") or "")
    if not project_repo and task:
        tid = Ledger(ctx).try_resolve_id(task) or task
        project_repo = str((ctx.store.task(tid) or {}).get("repo") or "")
    if not project_repo:
        project_repo = str(ctx.git.project_root(repo or ".") or "")
    return report_envelope(ctx, "report.helper_done", body, repo=project_repo)
