"""Worker escalation helpers: gathering review findings, building the escalation brief, Fable confirmation and
refusal handling, starting the escalated worker in hc or herdr TUI, and quieting the previous worker. Layer 3."""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import re
from typing import Any

from ..agents.profiles import LADDER, worker_summary
from ..caller import Caller
from ..context import Context
from ..errors import Refused
from ..home import project_slug
from ..ledger.ledger import Change, Ledger
from ..ledger.question import QUESTION_FIELDS
from ..ledger.task import Task
from ..messaging.address import Endpoint, LogicalAddress
from ..messaging.principal import resolve_local_principal
from ..messaging.typist import interrupt_endpoint
from ..osutil import clip
from ..terminals.tabs import tab_title
from .brief import report_section_for
from .codex_pool import codex_fast_for, pool_started, release_pool_lock
from .dispatch import (
    advisor_refused_for,
    ask_rule_for,
    no_fable_answer_for,
    tui_agent_gone_for,
    worker_argv_for,
    worker_placement_for,
)
from .lifecycle import end_terminal_for
from .send import deliver_now_for, send_when_ready_for, terminal_envelope, worker_endpoint
from .sessions import _worker_caller


def review_reports(review: dict[str, Any]) -> list[tuple[str, str]]:
    """A review thread's reports, oldest first, as (at, text)."""
    found = [
        (e.get("at") or "", re.match(r"status=[^;]*; (.+)", e.get("text") or "", re.S))
        for e in review.get("log") or []
    ]
    return [(at, m.group(1).strip()) for at, m in found if m]


def review_findings_for(ctx: Context, task: Any) -> list[str]:
    """What the task's reviews have reported so far, oldest first: the reports in its <id>-review thread."""
    raw = task.raw if isinstance(task, Task) else task
    try:
        review = json.loads(ctx.home.task(f"{raw['id']}-review").read_text())
    except (OSError, ValueError):
        return []
    if review.get("review_of") != raw["id"]:
        return []
    return [f"- {at}:\n  " + clip(text, 1200).replace("\n", "\n  ") for at, text in review_reports(review)]


def review_findings(task: Any) -> list[str]:
    return review_findings_for(Context.from_env(), task)


def escalation_brief_for(ctx: Context, task: Any, spec: Any, worktree: str | Path, why: str) -> str:
    """What the new worker of an escalated task is told."""
    raw = task.raw if isinstance(task, Task) else task
    tid, title, branch, base = raw["id"], raw.get("title") or raw["id"], raw["branch"], raw["base"]
    because = ctx.config.tr(f" Why: {why}.", f"理由：{why}。") if why else ""
    text = "[from pm.py escalate] " + ctx.config.tr(
        f"You take over task {tid} ({title}), now on {worker_summary(spec)}.{because} Another worker has worked on it: "
        f"its commits are already on branch {branch}, in this same worktree ({worktree}). Carry on from there, do not "
        f"start over: read `git log {base}..HEAD` and `git status` first, then fix what the reviews below found.",
        f"你来接手任务 {tid}（{title}），现在用 {worker_summary(spec)}。{because}前一个 worker 的提交已经在分支 {branch} 上，"
        f"就在这个工作树（{worktree}）里。从这里接着做，不要从头重写：先看 `git log {base}..HEAD` 和 `git status`，"
        "再把下面评审指出的问题改掉。",
    )
    findings = review_findings_for(ctx, raw)
    text += "\n\n" + ctx.config.tr("The review findings so far:", "到目前为止的评审意见：") + "\n" + (
        "\n".join(findings) or ctx.config.tr(
            "(no review has reported in the review thread; see the ledger entries)",
            "（评审线程里还没有汇报；看下面的台账记录）",
        )
    )
    log = "\n".join(
        f"- {e.get('at')} {e.get('by')}: {clip(' '.join(str(e.get('text') or '').split()), 600)}"
        for e in (raw.get("log") or [])[-8:]
    )
    if log:
        text += "\n\n" + ctx.config.tr("The task's latest ledger entries:", "任务最近的台账记录：") + "\n" + log
    brief = ""
    for path in (ctx.home.sent_dir / f"{tid}.md", Path(raw.get("brief") or "")):
        with contextlib.suppress(OSError):
            if str(path) and path.is_file():
                brief = path.read_text().strip()
                break
    text += "\n\n" + ctx.config.tr("The brief:", "原任务书：") + "\n" + (brief or ctx.config.tr("(none recorded)", "（未登记）"))
    return text + "\n" if f"update {tid} --status review" in brief else text + report_section_for(ctx, tid)


def escalation_brief(task: Any, b: Any, worktree: str | Path, why: str) -> str:
    return escalation_brief_for(Context.from_env(), task, b, worktree, why)


def escalated_name(name: str, profile: str) -> str:
    """The new worker's terminal name, beside the old one that is still live: hc wants it unique, 1-32 of a-z 0-9 - _."""
    base = re.sub(r"-(?:" + "|".join(LADDER) + r")$", "", re.sub(r"[^a-z0-9_-]+", "-", name.lower())).strip("-")
    return f"{base[:31 - len(profile)].rstrip('-') or 'worker'}-{profile}"


def ask_escalation_for(ctx: Context, task: Any, spec: Any, current: str, why: str) -> tuple[str, str]:
    """A Fable worker waits for the user's yes: block the task with a question card. Returns `(task_id, message)`."""
    raw = task.raw if isinstance(task, Task) else task
    what = ctx.config.tr(
        f"profile {spec.profile} ({' '.join(x for x in (spec.kind, spec.model, spec.effort) if x)})",
        f"{spec.profile} 档（{' '.join(x for x in (spec.kind, spec.model, spec.effort) if x)}）",
    )
    again = ctx.config.tr(
        f"Once the user agrees, run `pm.py escalate {raw['id']} --profile {spec.profile} --confirmed`.",
        f"用户同意后运行 `pm.py escalate {raw['id']} --profile {spec.profile} --confirmed`。",
    ) + " " + ask_rule_for(ctx)
    if raw["status"] == "blocked" and (raw.get("escalating") or {}).get("to") == spec.profile:
        msg = ctx.config.tr(
            f"{raw['id']}: still waiting for the user's answer on {what}. {again}",
            f"{raw['id']}：还在等用户回答是否升到 {what}。{again}",
        )
        return raw["id"], msg
    since = current or ctx.config.tr("its worker", "现在的 worker")
    asked = ctx.config.tr(
        f"Escalate this task from {since} to {what}" + (f" ({why})" if why else "")
        + "? The user decides before a Fable worker starts.",
        f"这个任务要从 {since} 升到 {what}" + (f"，理由：{why}" if why else "") + "。用 Fable 前先问你：同意吗？",
    )
    options = [
        ctx.config.tr(f"Agree: escalate to {what}", f"同意，升到 {what}"),
        ctx.config.tr("Do not escalate", "先不升级"),
    ]

    def _ask(cur: Task | None, ch: Change) -> dict[str, Any]:
        assert cur is not None
        r = cur.raw
        for f in QUESTION_FIELDS:
            r.pop(f, None)
        r.update(status="blocked", options=options, escalating={"to": spec.profile, "why": why})
        ch.note_on(r, "status=blocked; " + asked, options=options)
        return r

    Ledger(ctx).change(raw["id"], _ask)
    msg = ctx.config.tr(
        f"{raw['id']}: blocked, no worker started: {what} needs the user's yes. {again}",
        f"{raw['id']}：已标成 blocked，没有起 worker：升到 {what} 要先等用户同意。{again}",
    )
    return raw["id"], msg


def escalation_refused_for(ctx: Context, task_id: str, spec: Any, why: str, seen: str) -> None:
    """The new worker exited at once with its advisor: block with a question card and raise `Refused`."""
    answers = [
        ctx.config.tr("I ran /model fable: escalate again", "已运行 /model fable，重新升级"),
        no_fable_answer_for(ctx, spec.profile),
    ]
    msg = (
        ctx.config.tr(
            f"status=blocked; the escalated worker exited at once with advisor {spec.advisor} (its screen: {seen}); "
            "the previous worker is kept. ",
            f"status=blocked；升级起的 worker 带 advisor {spec.advisor} 一启动就退出了（屏幕：{seen}），前一个 worker 还留着。",
        )
        + advisor_refused_for(ctx, spec)
    )

    def _refused(cur: Task | None, ch: Change) -> dict[str, Any]:
        assert cur is not None
        r = cur.raw
        for f in QUESTION_FIELDS:
            r.pop(f, None)
        r.update(status="blocked", options=answers, escalating={"to": spec.profile, "why": why})
        ch.note_on(r, msg, options=answers)
        return r

    Ledger(ctx).change(task_id, _refused)
    raise Refused(
        ctx.config.tr(
            f"{task_id}: blocked. The escalated worker exited at once with --advisor {spec.advisor}: ",
            f"{task_id}：已标成 blocked。带 --advisor {spec.advisor} 起的升级 worker 一启动就退出了：",
        )
        + advisor_refused_for(ctx, spec)
        + ctx.config.tr(
            f" Then run `pm.py escalate {task_id} --profile {spec.profile}` again.",
            f"之后再运行 `pm.py escalate {task_id} --profile {spec.profile}`。",
        )
    )


def escalation_failed_for(ctx: Context, task_id: str, spec: Any, why: str, seen: str) -> None:
    """The new worker exited at once. With an advisor -> `escalation_refused_for`; else log and raise `Refused`."""
    if spec.advisor:
        escalation_refused_for(ctx, task_id, spec, why, seen)
    msg = ctx.config.tr(
        f"not escalated to {spec.profile}: the new worker exited at once (its screen: {seen}); the previous worker is kept",
        f"没升到 {spec.profile}：新 worker 一启动就退出了（屏幕：{seen}），前一个 worker 还留着",
    )

    def _log_fail(cur: Task | None, ch: Change) -> dict[str, Any]:
        assert cur is not None
        ch.note_on(cur.raw, msg)
        return cur.raw

    Ledger(ctx).change(task_id, _log_fail)
    raise Refused(ctx.config.tr(
        f"{task_id}: not escalated. The new worker exited at once; its screen: {seen}. The task and its worker are as they were.",
        f"{task_id}：没有升级。新 worker 一启动就退出了，屏幕上是：{seen}。任务和它的 worker 都没变。",
    ))


def start_escalated_for(
    ctx: Context,
    task: Any,
    spec: Any,
    name: str,
    worktree: str | Path,
    text: str,
    why: str,
    *,
    tab_short_val: str = "",
    bug: str = "",
    want_tab: bool = False,
    pool_lock: Any = None,
) -> tuple[str, str, str, list[str], str, str, int | None]:
    """Start the new worker in the task's worktree and give it `text`.

    Returns `(pane, workspace, unsent, warnings, resolved_tab, fast_said, handed_turn)`.
    Raises `Refused` when no worker could be started or the worker exited at once.
    """
    raw = task.raw if isinstance(task, Task) else task
    warnings: list[str] = []
    if ctx.pane.startswith("hc:"):
        made = None
        try:
            reads = ctx.agents.outside_reads(raw["repo"], raw.get("brief") or "")
            argv = worker_argv_for(ctx, spec, reads, raw["repo"], wrap=True)
            made = ctx.hc.start_terminal(name, worktree, argv, worker_placement_for(ctx))
        finally:
            if pool_lock is not None:
                release_pool_lock(ctx, pool_lock, spec, raw["repo"], tries=10 if made else 0)
            elif getattr(ctx, "_legacy", False):
                pool_started(spec, raw["repo"], tries=10 if made else 0)
        if not made:
            raise Refused(ctx.config.tr(f"hc run failed; nothing changed for {raw['id']}", f"hc run 失败；{raw['id']} 什么都没改"))
        resolved_tab = tab_title(tab_short_val, bug, made, cfg=ctx.config) if want_tab else ""
        ctx.hc.worker_tab(made, raw["id"], resolved_tab, parent=raw.get("parent") or "", caller_pane=ctx.pane)
        fast_said = codex_fast_for(ctx, made, spec)
        seen: dict[str, Any] = {}
        if send_when_ready_for(
            ctx, made, text, tries=30, pause=2, strict=spec.kind in ("claude", "codex"),
            trust=worktree, stop_on_exit=True, kind=spec.kind, seen=seen,
        ):
            return f"hc:{made}", "", "", warnings, resolved_tab, fast_said, seen.get("turn")
        seen_text = ctx.hc.screen_line(made, width=300)
        if ctx.hc.worker_state(made) in ("exited", "removed"):
            end_terminal_for(ctx, made, why="escalate")
            escalation_failed_for(ctx, raw["id"], spec, why, seen_text)
        return f"hc:{made}", "", seen_text or "(empty screen)", warnings, resolved_tab, fast_said, None

    pane: str | None = None
    failed = "no tab"
    try:
        workspace = task_workspace_for(ctx, raw, fallback="")
        reads = ctx.agents.outside_reads(raw["repo"], raw.get("brief") or "")
        argv = worker_argv_for(ctx, spec, reads, raw["repo"])
        pane, failed = tui_tab_agent_for(ctx, workspace, worktree, name, spec.kind, argv)
    finally:
        if pool_lock is not None:
            release_pool_lock(ctx, pool_lock, spec, raw["repo"], tries=10 if not failed else 0)
        elif getattr(ctx, "_legacy", False):
            pool_started(spec, raw["repo"], tries=10 if not failed else 0)
    if failed == "no tab":
        raise Refused(ctx.config.tr(
            f"no tab could be made in {raw['id']}'s workspace; nothing changed",
            f"没能在 {raw['id']} 的工作区开出标签页；什么都没改",
        ))
    if failed:
        raise Refused(ctx.config.tr(
            f"agent start failed in {pane}; nothing changed",
            f"在 {pane} 启动 agent 失败；什么都没改",
        ))
    assert pane is not None
    said = tui_prompt_for(ctx, name, pane, text)
    if said == "gone":
        escalation_failed_for(ctx, raw["id"], spec, why, ctx.config.tr("(no agent in the pane)", "（窗格里已经没有 agent）"))
    if said == "idle":
        warnings.append(f"warning: {name} did not start working; read its screen")
    unsent = ctx.config.tr("(the prompt was refused)", "（提示没送进去）") if said == "refused" else ""
    return pane, workspace, unsent, warnings, "", "", None


def task_workspace_for(ctx: Context, task: Any, fallback: str | None = None) -> str:
    """The herdr TUI workspace a task's worker runs in."""
    raw = task.raw if isinstance(task, Task) else task
    old = raw.get("pane") or ""
    found = raw.get("workspace") or (
        ((ctx.tui.pane_get(old) or {}).get("workspace_id") or "")
        if old and not old.startswith("hc:") else ""
    )
    return found or (ctx.workspace if fallback is None else fallback)


def task_workspace(task: Any, fallback: str | None = None) -> str:
    return task_workspace_for(Context.from_env(), task, fallback=fallback)


def tui_tab_agent_for(
    ctx: Context,
    workspace: str,
    cwd: str | Path,
    name: str,
    kind: str,
    argv: list[str],
) -> tuple[str | None, str]:
    """In the herdr terminal UI: a new tab of workspace at cwd, and the agent `name` started in it."""
    made = re.search(
        r'"pane_id": "([^"]+)"',
        json.dumps(ctx.tui.tab_create("--workspace", workspace, "--cwd", str(cwd), "--label", name, "--no-focus") or {}),
    ) if workspace else None
    if not made:
        return None, "no tab"
    pane = made.group(1)
    if not ctx.tui.agent_start(name, kind=kind, pane=pane, argv=argv[1:]):
        ctx.tui.pane_close(pane)
        return pane, "no agent"
    return pane, ""


def tui_tab_agent(workspace: str, cwd: str | Path, name: str, kind: str, argv: list[str]) -> tuple[str | None, str]:
    return tui_tab_agent_for(Context.from_env(), workspace, cwd, name, kind, argv)


def tui_prompt_for(ctx: Context, name: str, pane: str, text: str) -> str:
    """Give a herdr TUI agent its first text: a `cmd.brief` envelope typed under the agent's typist lease."""
    env = terminal_envelope(ctx, text, kind="cmd.brief", target=name)
    prompted = deliver_now_for(ctx, Endpoint(runtime="tui", terminal=name), env, timeout_s=70.0).status == "typed"
    if prompted and ctx.tui.agent_wait(name, "--until", "working", "--timeout", "20000"):
        return ""
    if tui_agent_gone_for(ctx, pane):
        ctx.tui.pane_close(pane)
        return "gone"
    return "idle" if prompted else "refused"


def tui_prompt(name: str, pane: str, text: str) -> str:
    return tui_prompt_for(Context.from_env(), name, pane, text)


def own_worker_for(ctx: Context, task: Any, pane: str) -> bool:
    """The pane holds a worker that pm.py started for this task, which escalate may stop and end."""
    raw = task.raw if isinstance(task, Task) else task
    if not pane or pane == ctx.pane or _worker_caller(ctx).pm_record_for_pane(pane):
        return False
    if pane.startswith("hc:"):
        labels = (ctx.hc.get_raw(pane[3:]) or {}).get("labels") or {}
        return not labels.get("pm") and labels.get("task") == raw["id"]
    return raw.get("worker_pane") == pane and any(
        x.get("pane_id") == pane and x.get("name") == raw.get("agent") for x in ctx.tui.agents()
    )


def own_worker(task: Any, pane: str) -> bool:
    return own_worker_for(Context.from_env(), task, pane)


def worker_busy_for(ctx: Context, pane: str) -> bool:
    """The agent in this pane is in the middle of a turn or running background work."""
    if pane.startswith("hc:"):
        info = ctx.hc.get_raw(pane[3:]) or {}
        if info.get("state") != "live":
            return False
        state = (info.get("status") or {}).get("state")
        if bool(state) and state not in ("idle", "done", "blocked", "error"):
            return True
        return bool(ctx.procs.background_work(info))
    return any(x.get("pane_id") == pane and x.get("agent_status") == "working" for x in ctx.tui.agents())


def worker_busy(pane: str) -> bool:
    return worker_busy_for(Context.from_env(), pane)


QUIET_TRIES = 30  # looks, two seconds apart, for the previous worker to go idle and for git's index.lock to go


def quiet_old_worker_for(ctx: Context, task: Any, pane: str, ours: bool, worktree: str | Path) -> bool:
    """Stop the previous worker and wait until git's index.lock is gone. Raises `Refused` if it does not get quiet."""
    if getattr(ctx, "_legacy", False) and quiet_old_worker is not _DEFAULT_QUIET_OLD_WORKER:
        return bool(quiet_old_worker(task, pane, ours, worktree))
    return _quiet_old_worker_impl(ctx, task, pane, ours, worktree)


def _quiet_old_worker_impl(ctx: Context, task: Any, pane: str, ours: bool, worktree: str | Path) -> bool:
    interrupted = False
    if pane and pane != ctx.pane and worker_busy_for(ctx, pane):
        if not ours:
            raise Refused(ctx.config.tr(
                f"{pane} is still working in {worktree} and is not a worker escalate may stop; nothing changed. "
                "Let it finish or stop it, then escalate again.",
                f"{pane} 还在 {worktree} 里干活，又不是 escalate 能停的 worker；什么都没改。等它做完或停下后再升级。",
            ))
        # A `ctrl.interrupt` envelope (P0) through the worker's transport: hc Esc (ctrl+c where the program
        # reports no status), TUI esc.
        raw = task.raw if isinstance(task, Task) else task
        slug = project_slug(raw.get("repo")) if raw.get("repo") else ""
        ep = worker_endpoint(pane[3:]) if pane.startswith("hc:") else Endpoint(runtime="tui", terminal=pane)
        if ep is not None:
            interrupt_endpoint(
                ctx, ep, sender=resolve_local_principal(ctx, slug),
                recipient=LogicalAddress.worker(str(raw.get("id") or pane), slug), project=slug,
                cause={"kind": "escalate", "task_id": str(raw.get("id") or "")}, timeout_s=10,
            )
        interrupted = True
        for _ in range(QUIET_TRIES):
            if not worker_busy_for(ctx, pane):
                break
            ctx.clock.sleep(2)
        else:
            raise Refused(ctx.config.tr(
                f"{pane} was interrupted but is still working; nothing else changed. Escalate again once it has stopped.",
                f"已中断 {pane}，但它还在干活；别的都没改。等它停下后再升级。",
            ))
    for _ in range(QUIET_TRIES):
        lock = ctx.git.index_lock(worktree)
        if not lock:
            return interrupted
        ctx.clock.sleep(2)
    raise Refused(ctx.config.tr(
        f"git's {lock} is still there: something is writing to the worktree, so no new worker was started. "
        "If no git runs there, remove the file and escalate again.",
        f"git 的 {lock} 一直在：有程序在写这个工作树，所以没起新 worker。确认那里没有 git 在跑后删掉这个文件，再升级。",
    ))


def quiet_old_worker(task: Any, pane: str, ours: bool, worktree: str | Path) -> bool:
    return _quiet_old_worker_impl(Context.from_env(), task, pane, ours, worktree)


_DEFAULT_QUIET_OLD_WORKER = quiet_old_worker


def unmark_switching_for(ctx: Context, task_id: str) -> None:
    """An escalation that stopped before the switch: its task is watched again."""
    def _unmark(cur: Task | None, _ch: Change) -> dict[str, Any]:
        assert cur is not None
        cur.raw.pop("switching", None)
        return cur.raw

    Ledger(ctx).change(task_id, _unmark)


def unmark_switching(task_id: str) -> None:
    unmark_switching_for(Context.from_env(), task_id)
