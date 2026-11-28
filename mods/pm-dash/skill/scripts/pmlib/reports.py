"""The report path (`pm-message-routing.md` §6, §9.2 wave 4): `pm.py update | log | remember | helper done` as
`report.*` envelopes. `ReportClient` builds and submits them; on this machine `LocalReportTransport` hands them in
process to `ReportApplier`, which authorizes the sender (`authorize_envelope`), applies them idempotently (the
idempotency key kept in the target file under its lock, C6a) and answers with an `ApplyReceipt`. Layer 3.

Two ways a report is refused, never silently (§6.4): submitted synchronously (every local command), the refusal
is raised to the command, which prints it and exits non-zero as it always did; queued (`queue_only`, the
cross-machine outbox to come), it becomes an `event.report_rejected` envelope routed to the worker or the PM."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import datetime
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
from .messaging.address import Endpoint, LogicalAddress, endpoint_from_dict, safe_endpoint_uid
from .messaging.authz import authorize_envelope
from .messaging.envelope import P3_DIRECT, P4_BATCH, Envelope, new_env_id
from .messaging.mailbox import MailboxStore
from .messaging.outbox import OUTBOX_FILE, TaskTokens, WorkerState, task_remote_outboxes, verify_envelope
from .messaging.principal import Principal, resolve_local_principal
from .messaging.router import EndpointSnapshot, Router, RoutingSnapshot
from .messaging.typist import endpoint_mailbox, transport_for
from .procs import supervisor_env
from .reactions import Say, Updates
from .store import file_lock, lock_file, unlock_file, write_atomic
from .workers.remote import remote_workers_enabled


MAX_APPLIED_RECEIPTS = 512
REMOTE_IDLE_MIN_S = 2.0   # §12.2 item 4: event-driven pull with idle backoff 2 s -> 10 s
REMOTE_IDLE_MAX_S = 10.0


def _utc(ms: int) -> str:
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "?"


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
        if env.project:
            return self.ctx.home.project(env.project)
        pslug = self.ctx.store.folder_project_slug(repo) if repo else ""
        return self.ctx.home.project(pslug) if pslug else self.ctx.home.project_for(repo)

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

    def _archive_late_report(self, env: Envelope, body: Mapping[str, Any], tid: str, *, current_epoch: int) -> bool:
        """Write a stale-epoch status report into the task's log, once per idempotency key (the key kept in the task
        file in the same locked write, C6a). False when it was already there."""
        parts = [f"status={body['status']}" if body.get("status") else "",
                 f"commit={body['commit']}" if body.get("commit") else "",
                 f"note={body['note']}" if body.get("note") else ""]
        text = (f"[late report from epoch {int(env.sender.epoch or 1)} (current {current_epoch}), created "
                f"{_utc(env.created_ms)}; status not changed] " + " ".join(x for x in parts if x)).strip()
        done = {"new": False}

        def _archive(cur: Any, ch: Any) -> dict[str, Any] | None:
            assert cur is not None
            raw = cur.raw
            amap = raw.get("applied_reports") if isinstance(raw.get("applied_reports"), dict) else {}
            if env.idempotency_key and env.idempotency_key in amap:
                return None
            entry = ch.note(text, source="late_report", late_report=True, sender_epoch=int(env.sender.epoch or 1),
                            **({"commit": str(body["commit"])} if body.get("commit") else {}))
            entry["late_report"] = True
            if env.idempotency_key:
                amap = dict(amap)
                order = [str(k) for k in (raw.get("last_applied_keys") or []) if isinstance(k, str) and k != env.idempotency_key]
                order.append(env.idempotency_key)
                while len(order) > 64:
                    amap.pop(order.pop(0), None)
                amap[env.idempotency_key] = {"env_id": env.env_id, "at": self.ctx.clock.now(), "changes": [],
                                             "late_report": True}
                raw["applied_reports"] = amap
                raw["last_applied_keys"] = order
            done["new"] = True
            return raw

        Ledger(self.ctx).change(tid, _archive)
        return done["new"]

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
        layer = MemoryLayer(
            self.ctx,
            None if body.get("personal") else str(body.get("repo") or repo),
            slug=None if body.get("personal") else (str(body.get("project_slug") or "") or None),
        )
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
                # MR-D4: archived on the task's log (commit and note kept), one P4 summary to the PM; the current
                # status and the current worker are left alone.
                archived = self._archive_late_report(env, body, tid, current_epoch=int(cur_ep.epoch or 1))
                if archived:
                    self._emit_late_report(env, snap, files, current_epoch=int(cur_ep.epoch or 1))
                return _applied({"task_id": tid, "current_epoch": int(cur_ep.epoch or 1)}, code="late_report",
                                reason=f"worker epoch {env.sender.epoch} < current {cur_ep.epoch}", late_report=True,
                                already_applied=not archived)
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
            existing_l = snap.tasks.get(tid) or self.ctx.store.task(tid) or {}
            ep_l = endpoint_from_dict(existing_l.get("endpoint")) if isinstance(existing_l.get("endpoint"), Mapping) else None
            if env.sender.role == "worker" and ep_l is not None and int(ep_l.epoch or 1) > int(env.sender.epoch or 1):
                # §6.3.1: an append-only report keeps its words, marked as delayed from an earlier epoch.
                text = f"[delayed report from epoch {int(env.sender.epoch or 1)}, created {_utc(env.created_ms)}] {text}"

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
            ml = MemoryLayer(
                self.ctx,
                repo=target_repo,
                slug=None if body.get("personal") else (env.project or None),
            )
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


class OutboxReportTransport:
    """The report transport of a worker on another machine (§6.1 branch 2a, §11.3): no ledger here, so the
    envelope is appended (signed with this task's token, fsynced) to `<worker_state>/outbox.jsonl`; the coordinator
    pulls it by `seq` and applies it. The command returns 0 at once, saying the report is queued."""

    def __init__(self, ctx: Context, state: WorkerState) -> None:
        self.ctx = ctx
        self.state = state

    def submit(
        self,
        env: Envelope,
        *,
        local: LocalFacts | None = None,
        on_after_task_write: Callable[[Transition], None] | None = None,
    ) -> ApplyReceipt:
        line = self.state.outbox.append(env, token=str(self.state.credential.get("token") or ""))
        self.ctx.out.line(self.ctx.config.tr(
            f"[pm] report queued in the outbox (seq={line.seq}); the coordinator applies it when it next syncs",
            f"[pm] 汇报已写入本机发件箱（seq={line.seq}），协调者下次同步时生效"))
        return ApplyReceipt(env_id=env.env_id, idempotency_key=env.idempotency_key, status="applied",
                            result={"queued": True, "seq": line.seq})


class ReportClient:
    """Where `pm.py update | log | remember | helper done` hand in their report: `submit` goes through the
    transport (on this machine, `LocalReportTransport`: applied now); `queue_only` leaves it in the project's
    inbound-reports mailbox for a later apply (the cross-machine outbox path)."""

    def __init__(self, ctx: Context, transport: Any = None) -> None:
        self.ctx = ctx
        self._applier = ReportApplier(ctx)
        if transport is None:
            state = WorkerState.from_env(getattr(ctx, "env", None))
            transport = OutboxReportTransport(ctx, state) if state is not None else LocalReportTransport(self._applier)
        self.transport = transport

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


def remote_worker_state(ctx: Context) -> WorkerState | None:
    """This session's remote worker state (`PM_WORKER_STATE`), when it runs on a machine without the ledger."""
    return WorkerState.from_env(getattr(ctx, "env", None))


def _remote_sender(state: WorkerState) -> Principal:
    return Principal.worker(state.project, state.task_id, epoch=state.epoch, machine=state.machine or None,
                            credential_id=str(state.credential.get("credential_id") or ""))


def _remote_task_id(state: WorkerState, given: str) -> str:
    """The task a remote worker names: its own (by id, short id or number) unless it spells out another."""
    g = str(given or "").strip()
    own = state.task_id
    aliases = {own, str(state.context.get("short_id") or ""), str(state.context.get("number") or ""),
               f"#{state.context.get('number')}" if state.context.get("number") else ""}
    return own if (not g or g in aliases) else g


def report_envelope(ctx: Context, kind: str, body: Mapping[str, Any], *, repo: str = "", task_id: str = "",
                    sender: Principal | None = None, project: str = "") -> Envelope:
    """A `report.*` envelope from this session: its sender as this machine resolves the caller (explicit
    `Principal`, never an environment variable taken at its word by the applier), a fresh idempotency key per
    invocation (`rep:<actor>:<env_id>`; a retry of the same envelope keeps it), addressed to `ledger://<slug>`."""
    now = int(float(ctx.clock.time()) * 1000)
    project = project or (project_slug(repo) if repo else "")
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
    body = {k: getattr(req, k) for k in UpdateRequest.__annotations__ if k != "id" and getattr(req, k, None) is not None}
    state = remote_worker_state(ctx)
    if state is not None:
        tid = _remote_task_id(state, req.id)
        req.id = tid
        return report_envelope(ctx, "report.task_update", body, repo=str(state.context.get("repo") or ""),
                               task_id=tid, sender=_remote_sender(state), project=state.project)
    task = Ledger(ctx).load(req.id).raw
    return report_envelope(ctx, "report.task_update", body, repo=str(task.get("repo") or ""), task_id=str(task["id"]))


def task_log_report(ctx: Context, task_id: str, text: str) -> Envelope:
    """`pm.py log`: one line on the task's log."""
    state = remote_worker_state(ctx)
    if state is not None:
        return report_envelope(ctx, "report.task_log", {"text": text}, repo=str(state.context.get("repo") or ""),
                               task_id=_remote_task_id(state, task_id), sender=_remote_sender(state),
                               project=state.project)
    task = Ledger(ctx).load(task_id).raw
    return report_envelope(ctx, "report.task_log", {"text": text}, repo=str(task.get("repo") or ""),
                           task_id=str(task["id"]))


def memory_report(ctx: Context, repo: str, *, personal: bool = False, **fields: Any) -> Envelope:
    """`pm.py remember`: the memory's fields (`type` is its kind); `repo`: the project it is written for."""
    body = {k: v for k, v in fields.items() if v is not None}
    body["personal"] = bool(personal)
    state = remote_worker_state(ctx)
    if state is not None:
        # The memory is the coordinator's: filed under the project's checkout there, not this machine's path.
        coord_repo = str(state.context.get("repo") or repo)
        body["project_repo"] = coord_repo
        return report_envelope(ctx, "report.memory_write", body, repo=coord_repo, sender=_remote_sender(state),
                               project=state.project)
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


# --- The coordinator's side of the remote outbox (§6.1 branch 2a, §7.2, §9.3 phase 6a) ---------------------------


@dataclass(frozen=True)
class RemoteSyncResult:
    """One pull of one remote outbox."""

    task_id: str
    epoch: int
    link_state: str
    applied: int = 0
    duplicates: int = 0
    rejected: int = 0
    late: int = 0
    cursor: int = 0
    next_poll_s: float = REMOTE_IDLE_MIN_S
    skipped: bool = False
    missing_token: bool = False


class RemoteReportSync:
    """Pull each remote worker's `outbox.jsonl` by `seq` (`hc file read --on <machine>` through
    `RemoteHcTransport.observe`), check each line's MAC against the task token of its epoch, bind the sender to the
    `(task, epoch)` that token names (whatever the envelope claims), and apply it through `ReportApplier` as that
    worker. Idempotent end to end: the cursor is saved after each line, and a line applied twice (a crash between
    apply and cursor save, a retry) hits the applied-reports receipt or the task file's own key and changes nothing.

    While the machine is unreachable nothing is pulled and nothing is concluded (I4); the cursor waits. An empty
    pull backs off 2 s -> 4 s -> 8 s -> 10 s; a pull that found lines polls again at 2 s."""
    def __init__(self, ctx: Context, *, transport: Any = None) -> None:
        self.ctx = ctx
        self._transport = transport
        self._applier = ReportApplier(ctx)
        self._tokens = TaskTokens(ctx.home.tokens)

    # state ------------------------------------------------------------------------------------------------------

    def _state_path(self, repo: str, task_id: str, epoch: int) -> Path:
        task = self.ctx.store.task(task_id) if task_id else None
        pslug = self.ctx.store.task_project_slug(task) if isinstance(task, Mapping) else ""
        files = self.ctx.home.project(pslug) if pslug else self.ctx.home.project_for(repo)
        return Path(files.applied_reports_json).parent / "remote-sync" / f"{safe_endpoint_uid(task_id)}-e{int(epoch)}.json"

    def _load(self, path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        return raw if isinstance(raw, dict) else {}

    def _save(self, path: Path, data: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, (json.dumps(dict(data), indent=2) + "\n").encode("utf-8"))

    def _now_ms(self) -> int:
        return int(float(self.ctx.clock.time()) * 1000)

    # pulling ----------------------------------------------------------------------------------------------------

    def remote_tasks(self, repo: str | Path | None = None) -> list[dict[str, Any]]:
        out = []
        for task in Ledger(self.ctx).raw_tasks():
            if repo is not None and str(task.get("repo") or "") != str(repo):
                continue
            if task.get("closed") or not task_remote_outboxes(task):
                continue
            out.append(task)
        return out

    def look(self, repo: str | Path, stops: Any = None, bases: Any = None) -> float | None:
        """The deliverer's watcher hook: sync whatever remote outbox is due; the soonest next look (clock seconds).
        Off unless remote workers are switched on (`experimental.remote_workers`); `pm.py remote-sync` still pulls."""
        if not remote_workers_enabled(self.ctx):
            return None
        due: float | None = None
        for task in self.remote_tasks(repo):
            for res in self.sync_task(task):
                at = float(self.ctx.clock.time()) + res.next_poll_s
                due = at if due is None else min(due, at)
        return due

    def sync_task(self, task: Mapping[str, Any], *, force: bool = False) -> list[RemoteSyncResult]:
        return [self.sync_outbox(task, row, force=force) for row in task_remote_outboxes(task)]

    def sync_outbox(self, task: Mapping[str, Any], row: Mapping[str, Any], *, force: bool = False) -> RemoteSyncResult:
        tid = str(task.get("id") or "")
        repo = str(task.get("repo") or "")
        epoch = int(row.get("epoch") or 1)
        path = self._state_path(repo, tid, epoch)
        state = self._load(path)
        cursor = int(state.get("outbox_seq") or 0)
        now = self._now_ms()
        if not force and now < int(state.get("next_poll_ms") or 0):
            return RemoteSyncResult(task_id=tid, epoch=epoch, link_state=str(state.get("link_state") or "connected"),
                                    cursor=cursor, skipped=True,
                                    next_poll_s=max(0.0, (int(state["next_poll_ms"]) - now) / 1000.0))
        ep = Endpoint(runtime="hc", machine=str(row["machine"]), terminal=str(row.get("terminal") or ""),
                      workspace=str(row.get("worktree") or ""), epoch=epoch)
        transport = self._transport if self._transport is not None else transport_for(self.ctx, ep)
        outbox = str(row["state_dir"]).rstrip("/") + "/" + OUTBOX_FILE
        batch = transport.observe(ep, {"outbox_seq": cursor}, outbox_path=outbox)
        if batch.link_state != "connected":
            state.update(link_state=batch.link_state, next_poll_ms=now + int(REMOTE_IDLE_MAX_S * 1000))
            self._save(path, state)
            return RemoteSyncResult(task_id=tid, epoch=epoch, link_state=batch.link_state, cursor=cursor,
                                    next_poll_s=REMOTE_IDLE_MAX_S)
        counts = {"applied": 0, "duplicates": 0, "rejected": 0, "late": 0}
        token = self._tokens.token_for(tid, epoch)
        if not token and batch.inbound_meta:
            # No token for this epoch here (a moved or restored ledger home): nothing can be checked, so nothing is
            # refused and the cursor stays; the lines wait until the token is back. Said once, not every poll.
            if not state.get("missing_token_noted"):
                self._note_missing_token(tid, epoch)
                state["missing_token_noted"] = True
            state.update(link_state="connected", next_poll_ms=now + int(REMOTE_IDLE_MAX_S * 1000))
            self._save(path, state)
            return RemoteSyncResult(task_id=tid, epoch=epoch, link_state="connected", cursor=cursor,
                                    next_poll_s=REMOTE_IDLE_MAX_S, missing_token=True)
        state.pop("missing_token_noted", None)
        for meta in batch.inbound_meta:
            seq = int(meta.get("seq") or 0)
            if seq <= cursor:
                continue
            kind = self._apply_line(task, row, epoch, token, meta)
            counts[kind] += 1
            cursor = seq
            state["outbox_seq"] = cursor
            self._save(path, state)
        if any(counts.values()):
            state["empty_polls"] = 0
            wait_s = REMOTE_IDLE_MIN_S
        else:
            n = int(state.get("empty_polls") or 0) + 1
            state["empty_polls"] = n
            wait_s = min(REMOTE_IDLE_MIN_S * (2 ** (n - 1)), REMOTE_IDLE_MAX_S)
        state.update(link_state="connected", outbox_seq=cursor, next_poll_ms=now + int(wait_s * 1000))
        if self._resume_held_sends(task, row, ep, state, now):
            state["drain_spawned_ms"] = now
        self._save(path, state)
        return RemoteSyncResult(task_id=tid, epoch=epoch, link_state="connected", cursor=cursor, next_poll_s=wait_s,
                                **counts)

    def _resume_held_sends(self, task: Mapping[str, Any], row: Mapping[str, Any], ep: Endpoint,
                           state: Mapping[str, Any], now: int) -> bool:
        """The line is back: what was queued for the current worker during the partition is typed now, by the same
        detached `_drain-endpoint` a send starts (under the terminal's lease; at most one start per 30 s)."""
        if self._transport is not None or str(task.get("pane") or "") != f"hc:{ep.hc_target}":
            return False
        if now - int(state.get("drain_spawned_ms") or 0) < 30_000:
            return False
        held = [it for it in endpoint_mailbox(self.ctx, ep).pending_for_endpoint(ep.uid)
                if it.state == "accepted" and not it.envelope.kind.startswith("ctrl.")]
        if not held:
            return False
        procs = getattr(self.ctx, "procs", None)
        if procs is None or not hasattr(procs, "spawn_pm"):
            return False
        procs.spawn_pm(["_drain-endpoint", ep.hc_target, "--timeout", "180"],
                       env=supervisor_env(procs.clean_session_env()), cwd=self.ctx.home.root)
        return True

    def _apply_line(self, task: Mapping[str, Any], row: Mapping[str, Any], epoch: int, token: str,
                    meta: Mapping[str, Any]) -> str:
        tid = str(task.get("id") or "")
        raw_env = meta.get("envelope") if isinstance(meta.get("envelope"), Mapping) else {}
        if not meta.get("parsed") or not verify_envelope(token, raw_env, str(meta.get("mac") or "")):
            why = "unreadable envelope" if not meta.get("parsed") else "signature does not match the task token"
            self._note_rejected(tid, int(meta.get("seq") or 0), epoch, why)
            return "rejected"
        env = Envelope.from_dict(raw_env)
        slug = str(env.project or project_slug(str(task.get("repo") or "")))
        bound = Principal.worker(slug, tid, epoch=epoch, machine=str(row.get("machine") or "") or None,
                                 credential_id=f"task-token:{tid}:{epoch}")
        env = dataclasses.replace(env, sender=bound, project=slug)
        # Run the apply as that worker (its pane), so the worker-only rules (who reported, who is woken) hold as
        # they do for a local worker; the identity comes from the verified token, never from this process.
        wctx = dataclasses.replace(self.ctx, pane=str(task.get("pane") or ""), hc_terminal="", caller=None)
        receipt = ReportApplier(wctx).apply_envelope(env, raise_errors=False)
        if receipt.status == "rejected":
            return "rejected"
        if receipt.late_report:
            return "late" if not receipt.already_applied else "duplicates"
        return "duplicates" if receipt.already_applied else "applied"

    def _note_missing_token(self, tid: str, epoch: int) -> None:
        text = self.ctx.config.tr(
            f"[remote reports of epoch {epoch} wait: no task token for that epoch on this machine "
            f"({self._tokens.dir}); restore it to apply them]",
            f"[epoch {epoch} 的远端汇报暂停应用：本机缺该 epoch 的任务令牌（{self._tokens.dir}）；恢复后自动应用]")

        def _log(cur: Any, ch: Any) -> dict[str, Any]:
            assert cur is not None
            ch.note(text, source="remote_sync", wake=True)
            return cur.raw

        Ledger(self.ctx).change(tid, _log)

    def _note_rejected(self, tid: str, seq: int, epoch: int, why: str) -> None:
        text = self.ctx.config.tr(f"[remote report seq={seq} (epoch {epoch}) refused: {why}]",
                                  f"[远端汇报 seq={seq}（epoch {epoch}）被拒收：{why}]")

        def _log(cur: Any, ch: Any) -> dict[str, Any]:
            assert cur is not None
            ch.note(text, source="remote_sync", wake=True)
            return cur.raw

        Ledger(self.ctx).change(tid, _log)
