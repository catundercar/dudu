"""Self-hosted workers (`pm-message-routing.md` §6.5, §7.3, §8.3, §9.3 phase 6b), the coordinator's side: the task's
self-hosted endpoint, the worker's read-only context (§6.5 boundary), its brief, the messages queued for its node,
and its branch brought back from the bundles the node uploads. Layer 3 (workers).

A self-hosted node only ever connects out. Nothing here reaches it: what it should get waits in its pull queue
(`SelfHostedPullTransport`), what it sends arrives on its next sync (`nodes/hub.py`).

§6.5 boundary: the context and the brief a node gets carry the task's metadata and this project's memories only. No
personal memory goes to a node unless the user names it in `config.json` (`self_hosted.share_personal_memories`), and
never a `user` memory; no other project's data, no path of the coordinator's machine.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

from ..context import Context
from ..errors import Refused
from ..home import project_slug
from ..ledger.ledger import Ledger
from ..memory.layer import MemoryLayer
from ..messaging.address import Endpoint, LogicalAddress, endpoint_from_dict
from ..messaging.envelope import P3_DIRECT, Envelope, new_env_id
from ..messaging.nodes import NodeRegistry, body_digest
from ..messaging.principal import Principal
from ..messaging.transport import DeliverOutcome
from ..messaging.typist import drain_endpoint, enqueue_for_endpoint
from .brief import report_section_for
from .remote import DEFAULT_REMOTE_PM, RemoteWorkspace, is_remote_task, refresh_remote_context


MAX_BUNDLE_BYTES = 3 * 1024 * 1024  # a bundle rides in one sync batch (4 MiB with its base64 and the rest)
CLOSED_STATUSES = ("merged", "done", "abandoned")
MEMORY_FIELDS = ("name", "type", "description", "body", "topic", "modified")


def is_self_hosted_task(task: Mapping[str, Any] | None) -> bool:
    sh = (task or {}).get("self_hosted")
    return isinstance(sh, Mapping) and bool(sh.get("node_id")) and bool(sh.get("slot"))


def is_offsite_task(task: Mapping[str, Any] | None) -> bool:
    """A worker whose commits live on another machine: a remote `<machine>/t7` or a self-hosted node."""
    return is_remote_task(task) or is_self_hosted_task(task)


def is_closed_task(task: Mapping[str, Any] | None) -> bool:
    return bool((task or {}).get("closed")) or str((task or {}).get("status") or "") in CLOSED_STATUSES


def offsite_where(task: Mapping[str, Any]) -> str:
    """Where the worker is, for a person: `dev/t7`, or `node <alias> (sh:<node>/<slot>)`."""
    if is_self_hosted_task(task):
        sh = task["self_hosted"]
        return f"node {sh.get('alias') or sh['node_id']} (sh:{sh['node_id']}/{sh['slot']})"
    remote = task.get("remote") if isinstance(task.get("remote"), Mapping) else {}
    return f"{remote.get('machine')}/{remote.get('terminal')}"


def offsite_machine(task: Mapping[str, Any]) -> str:
    if is_self_hosted_task(task):
        return str(task["self_hosted"].get("alias") or task["self_hosted"]["node_id"])
    return str((task.get("remote") or {}).get("machine") or "")


def self_hosted_endpoint(task: Mapping[str, Any]) -> Endpoint | None:
    if not is_self_hosted_task(task):
        return None
    ep = endpoint_from_dict(task.get("endpoint")) if isinstance(task.get("endpoint"), Mapping) else None
    if ep is not None and ep.runtime == "self_hosted":
        return ep
    sh = task["self_hosted"]
    return Endpoint(runtime="self_hosted", machine=str(sh["node_id"]), terminal=str(sh["slot"]),
                    epoch=int(sh.get("epoch") or 1))


def node_runs(task: Mapping[str, Any] | None, node_id: str) -> list[dict[str, Any]]:
    """Every run of the task on `node_id` (the current one first, then earlier epochs there)."""
    rows = [(task or {}).get("self_hosted"), *((task or {}).get("self_hosted_history") or [])]
    return [dict(r) for r in rows if isinstance(r, Mapping) and r.get("node_id") == node_id]


def next_offsite_epoch(task: Mapping[str, Any] | None) -> int:
    """One past every earlier endpoint of the task (remote, self-hosted, structured endpoint)."""
    best = 0
    rows = [(task or {}).get("remote"), *((task or {}).get("remote_history") or []),
            (task or {}).get("self_hosted"), *((task or {}).get("self_hosted_history") or []),
            (task or {}).get("endpoint")]
    for row in rows:
        if isinstance(row, Mapping) and isinstance(row.get("epoch"), int) and not isinstance(row.get("epoch"), bool):
            best = max(best, int(row["epoch"]))
    return best + 1 if best else 1


# --- §6.5: what a node may see -----------------------------------------------------------------------------------


def shared_memories(ctx: Context, repo: str, *, slug: str = "") -> list[dict[str, Any]]:
    """This project's memories, plus the personal ones the user named for nodes (never a `user` memory)."""
    out = []
    for m in MemoryLayer(ctx, repo, slug=slug or None).memories() if (repo or slug) else []:
        out.append({k: m.get(k) for k in MEMORY_FIELDS if m.get(k) not in (None, "")})
    cfg = ctx.config.get("self_hosted") if ctx.config is not None else None
    allowed = {str(n) for n in ((cfg or {}).get("share_personal_memories") or [])} if isinstance(cfg, Mapping) else set()
    if allowed:
        for m in MemoryLayer(ctx, None).memories():
            if m.get("name") in allowed and m.get("type") != "user":
                out.append({**{k: m.get(k) for k in MEMORY_FIELDS if m.get(k) not in (None, "")}, "shared": "personal"})
    return out


def self_hosted_context(ctx: Context, task: Mapping[str, Any]) -> dict[str, Any]:
    """The node's read-only `context.json` for one task. Stable for the same task state (no clock in it): the hub
    sends it again only when its digest changes (approval, a new epoch, a memory written)."""
    sh = task.get("self_hosted") if isinstance(task.get("self_hosted"), Mapping) else {}
    la = task.get("land_approved")
    repo = str(task.get("repo") or "")
    pslug = ctx.store.task_project_slug(task)
    return {
        "remote": True,
        "self_hosted": True,
        "role": "worker",
        "project": pslug or (project_slug(repo) if repo else str(task.get("project") or "")),
        "task_id": str(task.get("id") or ""),
        "number": task.get("number"),
        "title": str(task.get("title") or ""),
        "branch": str(task.get("branch") or ""),
        "base": str(task.get("base") or ""),
        "base_sha": str(sh.get("base_sha") or ""),
        "epoch": int(sh.get("epoch") or 1),
        "machine": str(sh.get("node_id") or ""),
        "node": str(sh.get("alias") or ""),
        "slot": str(sh.get("slot") or ""),
        "status": str(task.get("status") or ""),
        "land_approved": ({k: v for k, v in dict(la).items() if k in ("commit", "short", "base", "executor", "at")}
                          if isinstance(la, Mapping) else None),
        "lang": ctx.config.lang() if ctx.config is not None else "en",
        "pm": str(sh.get("pm") or DEFAULT_REMOTE_PM),
        "memories": shared_memories(ctx, repo, slug=pslug),
    }


def context_version(context: Mapping[str, Any]) -> str:
    return body_digest(dict(context))[:24]


def project_memory_block(ctx: Context, repo: str, pm_command: str, *, slug: str = "") -> str:
    rows = shared_memories(ctx, repo, slug=slug)
    if not rows:
        return ""
    tr = ctx.config.tr if ctx.config is not None else (lambda en, zh: en)
    head = tr("## Memory\nThis project's (full text: the `memories` of `$PM_WORKER_STATE/context.json`):",
              "## Memory\n本项目的（全文见 `$PM_WORKER_STATE/context.json` 的 `memories`）：")
    lines = [f"- [{m.get('name')}]({m.get('name')}.md) — {m.get('description') or ''} ({m.get('type')})" for m in rows]
    return "\n" + head + "\n" + "\n".join(lines) + "\n"


def self_hosted_brief(ctx: Context, task: Mapping[str, Any], brief: str, pm_command: str) -> str:
    """The brief as the node's worker gets it: the PM's brief, the report section (naming the node's pm.py), this
    project's memories. Not the personal memory block of a local brief (§6.5)."""
    tid = str(task.get("id") or "")
    local_cmd = ctx.procs.pm_command() if ctx.procs is not None and hasattr(ctx.procs, "pm_command") else ""
    section = report_section_for(ctx, tid)
    if local_cmd:
        section = section.replace(local_cmd, pm_command)
    pslug = ctx.store.task_project_slug(task)
    return brief + section + project_memory_block(ctx, str(task.get("repo") or ""), pm_command, slug=pslug)


# --- the task's record ------------------------------------------------------------------------------------------


def record_self_hosted_worker(ctx: Context, task_id: str, *, node: Mapping[str, Any], slot: str, epoch: int,
                              base_sha: str, pm_command: str) -> dict[str, Any]:
    """Write the self-hosted endpoint on the task (`self_hosted`; the earlier run moved to `self_hosted_history`,
    whose late reports are still archived, MR-D4) and the structured `endpoint`."""
    def _rec(cur: Any, _ch: Any) -> dict[str, Any]:
        assert cur is not None
        raw = cur.raw
        old = raw.get("self_hosted")
        if isinstance(old, Mapping) and (old.get("node_id"), old.get("slot")) != (node["node_id"], slot):
            hist = [dict(h) for h in (raw.get("self_hosted_history") or []) if isinstance(h, Mapping)]
            hist.append(dict(old))
            raw["self_hosted_history"] = hist[-8:]
        pane = f"sh:{node['node_id']}/{slot}"
        raw["pane"] = pane
        raw["worker_pane"] = pane
        raw["self_hosted"] = {"node_id": str(node["node_id"]), "alias": str(node.get("alias") or ""), "slot": slot,
                              "epoch": int(epoch), "base_sha": base_sha, "pm": pm_command}
        raw["endpoint"] = Endpoint(runtime="self_hosted", machine=str(node["node_id"]), terminal=slot,
                                   agent_kind=str((raw.get("worker") or {}).get("kind") or ""),
                                   epoch=int(epoch)).to_dict()
        return raw

    changed = Ledger(ctx).change(task_id, _rec)
    return changed.raw if changed is not None else {}


def resolve_node(ctx: Context, ref: str) -> dict[str, Any] | None:
    """An active enrolled node named `ref` (id or alias), or None."""
    return NodeRegistry(ctx.home.tokens, clock=ctx.clock).find(ref, active_only=True)


# --- messages to the node -------------------------------------------------------------------------------------


def self_hosted_envelope(ctx: Context, task: Mapping[str, Any], text: str, *, kind: str = "cmd.send",
                         sender: Principal | None = None, priority: int = P3_DIRECT, idempotency_key: str = "",
                         body: Mapping[str, Any] | None = None) -> Envelope:
    now = int(float(ctx.clock.time()) * 1000)
    slug = project_slug(str(task.get("repo") or "")) if task.get("repo") else str(task.get("project") or "")
    eid = new_env_id(now)
    return Envelope(
        env_id=eid, idempotency_key=idempotency_key or f"sh:{kind}:{eid}", schema_version=1, created_ms=now,
        kind=kind, sender=sender or Principal.pm(slug), recipient=LogicalAddress.worker(str(task["id"]), project=slug),
        project=slug, cause={"kind": kind, "task_id": str(task["id"])}, priority=priority,
        body={"text": text, "task_id": str(task["id"]), **dict(body or {})},
    )


def queue_for_self_hosted(ctx: Context, task: Mapping[str, Any], env: Envelope) -> DeliverOutcome:
    """Queue `env` in the endpoint's mailbox and hand it to the node's pull queue now if its line is up (never
    blocks: the pull queue is a local append). Offline: it stays `accepted`; the node's next sync takes it."""
    ep = self_hosted_endpoint(task)
    if ep is None:
        raise Refused(f"{task.get('id')}: not a self-hosted task")
    _mb, item = enqueue_for_endpoint(ctx, ep, env)
    res = drain_endpoint(ctx, ep, wait_for=[item.envelope.env_id], wait_s=0)
    for it, out in (*res.typed, *res.failed, *res.held):
        if it.envelope.env_id == env.env_id:
            return out
    return DeliverOutcome(status="partitioned", detail="queued; handed to the node on its next sync")


def send_to_self_hosted(ctx: Context, task: Mapping[str, Any], text: str, *, kind: str = "cmd.send",
                        sender: Principal | None = None, idempotency_key: str = "") -> DeliverOutcome:
    return queue_for_self_hosted(ctx, task, self_hosted_envelope(ctx, task, text, kind=kind, sender=sender,
                                                                 idempotency_key=idempotency_key))


# --- the branch -----------------------------------------------------------------------------------------------


def track_ref(node_id: str, branch: str) -> str:
    return f"refs/remotes/workers/{node_id}/{branch}"


class SelfHostedWorkspace:
    """The coordinator's checkout side of a self-hosted task: the node uploads its branch as a git bundle on its
    sync (it cannot be reached); it lands on `refs/remotes/workers/<node>/<branch>`; review and merge fast-forward
    the local branch to it (MR-D1: the merge always runs here)."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def _tr(self, en: str, zh: str) -> str:
        return self.ctx.config.tr(en, zh) if self.ctx.config is not None else en

    def import_bundle(self, task: Mapping[str, Any], node_id: str, branch: str, bundle_b64: str) -> str:
        """Fetch an uploaded bundle into the track ref; returns its head."""
        repo = str(task.get("repo") or "")
        if not repo or not branch or branch != str(task.get("branch") or ""):
            raise Refused("bundle for another branch than the task's")
        try:
            data = base64.b64decode(bundle_b64.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError) as err:
            raise Refused(f"unreadable bundle: {err}") from err
        if len(data) > MAX_BUNDLE_BYTES:
            raise Refused(f"bundle of {len(data)} bytes is over {MAX_BUNDLE_BYTES}")
        ref = track_ref(node_id, branch)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "upload.bundle"
            path.write_bytes(data)
            res = self.ctx.git.run_raw(repo, "fetch", "--no-tags", str(path), f"+refs/heads/{branch}:{ref}", timeout=300)
        if res is None or not res.ok:
            raise Refused(f"git fetch of the uploaded bundle failed: {(res.stderr if res else '').strip()[-300:]}")
        return self.ctx.git.run(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") or ""

    def fetch_branch(self, task: Mapping[str, Any]) -> str:
        """Move the local branch to what the node uploaded (fast-forward only, compare-and-swap)."""
        sh = task.get("self_hosted") if isinstance(task.get("self_hosted"), Mapping) else {}
        repo = str(task.get("repo") or "")
        branch = str(task.get("branch") or "")
        git = self.ctx.git
        ref = track_ref(str(sh.get("node_id") or ""), branch)
        sha = git.run(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") or ""
        if not sha:
            raise Refused(self._tr(
                f"node {sh.get('alias') or sh.get('node_id')} has not uploaded {branch} yet (it does on its next sync "
                f"once the branch moves past the base)",
                f"节点 {sh.get('alias') or sh.get('node_id')} 还没上传 {branch}（分支超过基准后，下次同步时上传）"))
        local = git.run(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}") or ""
        if local == sha:
            return sha
        anc = git.run_raw(repo, "merge-base", "--is-ancestor", local, sha) if local else None
        if local and (anc is None or not anc.ok):
            raise Refused(self._tr(
                f"{branch} here ({local[:7]}) is not an ancestor of the node's {sha[:7]} (at {ref}): not a "
                f"fast-forward, left as it is",
                f"本机 {branch}（{local[:7]}）不是节点 {sha[:7]} 的祖先（在 {ref}）：非快进，保持不动"))
        holder = git.checkout_of(repo, branch)
        if holder:
            raise Refused(self._tr(f"{branch} is checked out in {holder} here; cannot move it to {sha[:7]}",
                                   f"{branch} 在本机 {holder} 里检出着，不能改指到 {sha[:7]}"))
        if git.run(repo, "update-ref", f"refs/heads/{branch}", sha, local or "0" * 40) is None:
            raise Refused(self._tr(f"{branch} changed here meanwhile; try again", f"{branch} 在本机被改动了；请重试"))
        return sha

    def review_checkout(self, task: Mapping[str, Any], sha: str) -> str:
        return RemoteWorkspace.review_checkout(self, task, sha)  # type: ignore[arg-type]


def offsite_workspace_for(ctx: Context, task: Mapping[str, Any]) -> Any:
    """The workspace that brings an offsite worker's branch here (`fetch_branch`, `review_checkout`)."""
    if is_self_hosted_task(task):
        return SelfHostedWorkspace(ctx)
    return RemoteWorkspace.for_task(ctx, task)


def refresh_offsite_context(ctx: Context, task: Mapping[str, Any]) -> str:
    """A remote worker's context is rewritten there now; a self-hosted node's comes with its next sync (the hub
    sends it whenever its digest changed), so nothing is to be done here."""
    if is_self_hosted_task(task):
        return ""
    return refresh_remote_context(ctx, task)


def bundle_note(task_id: str, node_id: str, branch: str, sha: str) -> str:
    return json.dumps({"task_id": task_id, "node": node_id, "branch": branch, "head": sha})
