"""Reattaching offline tasks and adopting orphan worker terminals under the current PM seat. Layer 3."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any

from ..agents.profiles import WorkerSpec
from ..context import Context
from ..errors import Refused
from ..events.deliver import deliver_later
from ..ledger.ledger import Change, Ledger
from ..ledger.question import QUESTION_FIELDS
from ..ledger.task import Task
from ..osutil import clip, shell_join, stale_lock
from ..project.project import ProjectRegistry
from ..project.readmodel import owner_of, task_offline
from ..terminals.tabs import hc_name, not_renamed, tab_title, task_bug
from .brief import report_section_for
from .dispatch import ask_rule_for, review_placement_for
from .escalate import unmark_switching_for, worker_busy_for
from .lifecycle import active_review_of_for, end_terminal_for
from .send import send_when_ready_for
from .sessions import clear_task_session_for, dispatched_with, find_session_for, session_places_for


ADOPTABLE = ("in_progress", "review", "blocked", "paused")


@dataclass(frozen=True)
class AdoptWorkerResult:
    """Structured outcome of `Workers.adopt`."""

    task_id: str
    lines: tuple[str, ...]
    asked: bool = False
    already_under_seat: bool = False
    pane: str = ""
    how: str = ""


def _deliver_later_for(ctx: Context, repo: str) -> None:
    if not repo:
        return
    if getattr(ctx, "_legacy", False):
        deliver_later(repo)
    elif ProjectRegistry(ctx).app_pm(repo):
        ctx.procs.spawn_pm(["deliver", str(repo)], env=ctx.procs.clean_session_env(), cwd=ctx.home.root)


def _round_sent_for(ctx: Context, task_id: str, term: str, sent: bool, seen: dict[str, Any]) -> bool:
    turn = seen.get("turn") if sent else None
    if turn is None:
        turn = (ctx.hc.get_raw(term) or {}).get("turn") or 0

    def _set_round(cur: Task | None, _ch: Change) -> dict[str, Any]:
        assert cur is not None
        cur.raw["round"] = {"terminal": term, "at": ctx.clock.now(), "turn": turn}
        return cur.raw

    Ledger(ctx).change(task_id, _set_round)
    return sent


def offline_now_for(ctx: Context, task: Any) -> bool:
    if getattr(ctx, "_legacy", False) and offline_now is not _DEFAULT_OFFLINE_NOW:
        return bool(offline_now(task))
    return _offline_now_impl(ctx, task)


def _offline_now_impl(ctx: Context, task: Any) -> bool:
    raw = task.raw if isinstance(task, Task) else task
    is_hc = (raw.get("pane") or "").startswith("hc:")
    hc_live = ctx.hc.live_terminals() if is_hc else None
    listing = ctx.tui.agents() if not is_hc else []
    return task_offline(raw, hc_live, {x.get("pane_id") for x in listing} if listing else None)


def reattach_prompt_for(ctx: Context, task: Any, cwd: str, resumed: bool) -> str:
    """What the agent of an offline task is told."""
    raw = task.raw if isinstance(task, Task) else task
    tid, title = raw["id"], raw.get("title") or raw["id"]
    if resumed:
        cmd = ctx.procs.pm_command()
        return "[from pm.py reattach] " + ctx.config.tr(
            f"This session's terminal was gone and it has been reattached. Carry on with task {tid} ({title}): "
            f"read the ledger's latest entries (`{cmd} show {tid}`) and the state of {cwd}, then continue "
            "and report in the ledger as before.",
            f"这个会话的终端断开过，现在接回来了。继续任务 {tid}（{title}）：先看台账最近的记录"
            f"（`{cmd} show {tid}`）和 {cwd} 的现状，再接着做，照原来的方式在台账汇报。",
        )
    sent = ctx.home.sent_dir / f"{tid}.md"
    brief = ""
    for path in (sent, Path(raw.get("brief") or "")):
        try:
            if str(path) and path.is_file():
                brief = path.read_text().strip()
                break
        except OSError:
            pass
    log = "\n".join(
        f"- {e.get('at')} {e.get('by')}: {clip(' '.join(str(e.get('text') or '').split()), 400)}"
        for e in (raw.get("log") or [])[-8:]
    )
    where = cwd + (ctx.config.tr(f", branch {raw['branch']}", f"，分支 {raw['branch']}") if raw.get("branch") else "")
    text = "[from pm.py reattach] " + ctx.config.tr(
        f"You take over the thread \"{title}\" (task {tid}). Its terminal is gone and its session could not be "
        f"found. Working folder: {where}. Read git status and git log there first to see what is done.",
        f"你来接手线程「{title}」（任务 {tid}）。它原来的终端断开了，会话也找不到了。"
        f"工作目录：{where}。先在那里看 git status 和 git log，弄清已经做了哪些。",
    )
    if brief:
        text += "\n\n" + ctx.config.tr("The brief:", "任务书：") + "\n" + brief
    if log:
        text += "\n\n" + ctx.config.tr("The ledger's latest entries:", "台账最近的记录：") + "\n" + log
    text += "\n\n" + ctx.config.tr("Carry on from there.", "从那里接着做。")
    return text if f"update {tid} --status review" in brief else text + report_section_for(ctx, tid)


def reattach_plan_for(ctx: Context, task: Any, old_cwd: str = "") -> dict[str, Any]:
    """How `reattach` brings the task's agent back: `{how: resume|fresh, kind, argv, cwd, prompt, session}`."""
    if getattr(ctx, "_legacy", False) and reattach_plan is not _DEFAULT_REATTACH_PLAN:
        return reattach_plan(task, old_cwd)
    return _reattach_plan_impl(ctx, task, old_cwd)


def _reattach_plan_impl(ctx: Context, task: Any, old_cwd: str = "") -> dict[str, Any]:
    raw = task.raw if isinstance(task, Task) else task
    kind, model, effort = dispatched_with(raw)
    advisor = (raw["worker"].get("advisor") or "") if isinstance(raw.get("worker"), dict) else ""
    session = find_session_for(ctx, raw, old_cwd)
    same = bool(session and session["kind"] == kind)
    role = "reviewer" if raw.get("review_of") else "worker"
    argv = (
        ctx.agents.resume_argv(
            session["kind"], session["id"],
            model if same else "", effort if same else "",
            advisor if same else "", ctx.agents.fable_fallback(kind, model, role) if same else "",
        )
        if session else None
    )
    reviewed = ctx.home.task(str(raw.get("review_of"))) if raw.get("review_of") else None
    of = json.loads(reviewed.read_text()).get("brief") or "" if reviewed is not None and reviewed.is_file() else ""
    reads = ctx.agents.outside_reads(raw.get("repo") or "", raw.get("brief") or "", of)
    provider = (raw["worker"].get("provider") or "") if isinstance(raw.get("worker"), dict) else ""
    if argv:
        argv += ctx.agents.read_settings(session["kind"], reads)
        if session["kind"] == "codex" and provider:
            argv[1:1] = ["-p", provider]
        cwd = session["cwd"] if Path(session["cwd"] or "").is_dir() else ""
        cwd = cwd or next(p for p in session_places_for(ctx, raw, old_cwd) + [str(Path.home())] if Path(p).is_dir())
        return {
            "how": "resume", "kind": session["kind"], "argv": argv, "cwd": cwd,
            "session": session["id"], "prompt": reattach_prompt_for(ctx, raw, cwd, True),
        }
    if not kind:
        kind = ctx.agents.resolve_worker(WorkerSpec(kind="", model=model, effort=effort)).kind
    cwd = next((p for p in (raw.get("worktree"), raw.get("repo"), old_cwd) if p and Path(p).is_dir()), str(Path.home()))
    argv = ctx.agents.start_argv(
        kind, model, effort, advisor=advisor, fallback=ctx.agents.fable_fallback(kind, model, role)
    ) + ctx.agents.read_settings(kind, reads)
    if kind == "codex" and provider:
        argv[1:1] = ["-p", provider]
    return {
        "how": "fresh", "kind": kind, "argv": argv, "cwd": cwd,
        "session": "", "prompt": reattach_prompt_for(ctx, raw, cwd, False),
    }


def start_beside_pm_for(ctx: Context, task: Any, plan: dict[str, Any], name: str) -> tuple[str, str]:
    """Start the plan's program for the task where `dispatch` would."""
    if getattr(ctx, "_legacy", False) and start_beside_pm is not _DEFAULT_START_BESIDE_PM:
        return start_beside_pm(task, plan, name)
    return _start_beside_pm_impl(ctx, task, plan, name)


def _start_beside_pm_impl(ctx: Context, task: Any, plan: dict[str, Any], name: str) -> tuple[str, str]:
    raw = task.raw if isinstance(task, Task) else task
    projects = ProjectRegistry(ctx)
    rec = owner_of(raw, projects.pm_records())
    pm = projects.find_pm(repo=rec["repo"]) if rec and Path(rec["repo"]).is_dir() else None
    pane = (pm or {}).get("pane_id") or ""
    if pane and not pane.startswith("hc:"):
        workspace = pm.get("workspace_id") or ((ctx.tui.pane_get(pane) or {}).get("workspace_id") or "")
        made = re.search(
            r'"pane_id": "([^"]+)"',
            json.dumps(
                ctx.tui.tab_create("--workspace", workspace, "--cwd", plan["cwd"], "--label", name, "--no-focus") or {}
            ),
        ) if workspace else None
        if not made:
            return "", ""
        ctx.tui.pane_run(
            made.group(1),
            shell_join(
                plan["argv"] + ([plan["prompt"]] if ctx.agents.takes_prompt(plan["kind"]) else []),
                powershell=True,
            ),
        )
        return made.group(1), workspace
    if raw.get("review_of"):
        reviewed = ctx.store.task(raw["review_of"]) or {"repo": raw.get("repo") or ""}
        placement = review_placement_for(ctx, reviewed, fallback_pane=pane)
    else:
        placement = ["--parent", pane[3:], "--outlive-parent", "--no-notify"] if pane.startswith("hc:") else ["--no-parent"]
    made = ctx.hc.start_terminal(
        hc_name(name), plan["cwd"], ctx.agents.launch_wrap(plan["kind"], plan["argv"]), placement
    )
    return (f"hc:{made}", "") if made else ("", "")


def ask_adopt_fresh_for(ctx: Context, task: Any, plan: dict[str, Any], old_pane: str) -> AdoptWorkerResult:
    """Block an orphan task with no resumable session with a question card before restarting fresh."""
    raw = task.raw if isinstance(task, Task) else task
    tid, kind = raw["id"], plan["kind"]
    again = ctx.config.tr(
        f"Once the user agrees, run `pm.py adopt {tid} --confirmed`.",
        f"用户同意后运行 `pm.py adopt {tid} --confirmed`。",
    ) + " " + ask_rule_for(ctx)
    pending = raw.get("adopting") if isinstance(raw.get("adopting"), dict) else {}
    if raw["status"] == "blocked" and pending.get("pane") == old_pane:
        msg = ctx.config.tr(
            f"{tid}: still waiting for the user's answer on adopting {old_pane} ({kind}). {again}",
            f"{tid}：还在等用户回答是否把 {old_pane}（{kind}）收归 PM 座位下。{again}",
        )
        return AdoptWorkerResult(task_id=tid, lines=(msg,), asked=True)
    prev_from = pending.get("from") or raw["status"]
    asked = ctx.config.tr(
        f"Worker {old_pane} ({kind}) has no resumable session on disk: adopting it under the PM seat will end "
        f"{old_pane} and start a fresh {kind} session from the brief and ledger, losing its in-session context. "
        "Restart it under the PM seat, or keep the current orphan terminal?",
        f"worker {old_pane}（{kind}）找不到可恢复的会话：收到 PM 座位下面会关掉 {old_pane}，凭任务书和台账重开一个新的 "
        f"{kind} 会话，原来的会话上下文会丢掉。要重开收到座位下面，还是保留现在的孤儿终端不动？",
    )
    options = [
        ctx.config.tr(f"Restart {kind} under PM seat (from brief and ledger)", f"在 PM 座位下重开 {kind}（凭任务书和台账，丢上下文）"),
        ctx.config.tr(f"Keep {old_pane} as it is", f"保留 {old_pane} 不动"),
    ]

    def _ask(cur: Task | None, ch: Change) -> dict[str, Any]:
        assert cur is not None
        r = cur.raw
        for f in QUESTION_FIELDS:
            r.pop(f, None)
        r.update(status="blocked", options=options, adopting={"from": prev_from, "pane": old_pane, "kind": kind})
        ch.note_on(r, "status=blocked; " + asked, options=options)
        return r

    Ledger(ctx).change(tid, _ask)
    msg = ctx.config.tr(
        f"{tid}: blocked with a question card; {old_pane} kept ({kind} has no resumable session). {again}",
        f"{tid}：已发问题卡标成 blocked；{old_pane} 先留着（{kind} 没有可恢复的会话）。{again}",
    )
    return AdoptWorkerResult(task_id=tid, lines=(msg,), asked=True)


def adopt_task_for(ctx: Context, candidate: str, *, confirmed: bool = False) -> AdoptWorkerResult:
    """End an idle orphan worker terminal and reattach the task's agent under the current PM seat."""
    ledger = Ledger(ctx)
    task = ledger.load(candidate).raw
    tid = task["id"]
    if task["status"] not in ADOPTABLE:
        raise Refused(ctx.config.tr(
            f"{tid} is {task['status']}: only open tasks (in_progress, review, blocked, paused) can be adopted",
            f"{tid} 的状态是 {task['status']}：只有未结任务（in_progress、review、blocked、paused）能 adopt",
        ))
    projects = ProjectRegistry(ctx)
    rec = owner_of(task, projects.pm_records())
    pm = projects.find_pm(repo=rec["repo"]) if rec and Path(rec["repo"]).is_dir() else None
    pm_pane = (pm or {}).get("pane_id") or ""
    if not pm_pane.startswith("hc:"):
        raise Refused(ctx.config.tr(
            f"no live desktop-app PM seat found for {tid}",
            f"没找到 {tid} 所属项目正在运行的桌面版 PM 座位",
        ))
    pm_term = pm_pane[3:]
    old_pane = task.get("pane") or ""
    if not old_pane or not old_pane.startswith("hc:"):
        raise Refused(ctx.config.tr(
            f"{tid}: pane {old_pane or '(none)'} is not a herdr-core terminal",
            f"{tid}：终端 {old_pane or '（无）'} 不是 herdr-core 终端",
        ))
    if "/" in old_pane:
        raise Refused(ctx.config.tr(
            f"{tid}: remote worker {old_pane} cannot be adopted onto this machine's PM seat",
            f"{tid}：远程终端 {old_pane} 不能收归本机 PM 座位下",
        ))
    old = old_pane[3:]
    if old == pm_term:
        raise Refused(ctx.config.tr(f"{tid}: {old_pane} is the PM terminal itself", f"{tid}：{old_pane} 就是 PM 自己的终端"))
    info = ctx.hc.get_raw(old, errors=True) or {}
    if (info.get("labels") or {}).get("pm"):
        raise Refused(ctx.config.tr(
            f"{tid}: {old_pane} is labelled as a PM terminal; refusing to end it",
            f"{tid}：{old_pane} 标着 pm=，不能当 worker 关掉",
        ))
    if info.get("state") != "live":
        raise Refused(ctx.config.tr(
            f"{tid}: {old_pane} is already offline; run `pm.py reattach {tid}` instead",
            f"{tid}：{old_pane} 已经断开了；请改用 `pm.py reattach {tid}`",
        ))
    if info.get("parent") == pm_term:
        msg = ctx.config.tr(
            f"{tid}: {old_pane} is already under PM seat {pm_pane}; nothing changed",
            f"{tid}：{old_pane} 已经挂在 PM 座位 {pm_pane} 下面；不用动",
        )
        return AdoptWorkerResult(task_id=tid, lines=(msg,), already_under_seat=True, pane=old_pane)
    old_parent = str(info.get("parent") or "")
    if old_parent:
        parent_info = ctx.hc.get_raw(old_parent, errors=True) or {}
        if parent_info.get("state") == "live":
            raise Refused(ctx.config.tr(
                f"{tid}: {old_pane} is not an orphan (its parent hc:{old_parent} is still live); nothing changed",
                f"{tid}：{old_pane} 不是孤儿（它的父终端 hc:{old_parent} 还在运行）；什么都没改",
            ))
    if worker_busy_for(ctx, old_pane):
        raise Refused(ctx.config.tr(
            f"{tid}: {old_pane} is still working; wait until it is idle before adopting it",
            f"{tid}：{old_pane} 还在干活；等它空闲后再 adopt",
        ))
    rev = active_review_of_for(ctx, tid)
    if rev:
        raise Refused(ctx.config.tr(
            f"{tid}: active review {rev['id']} is running under {old_pane}; finish or retire the review "
            f"first (`pm.py retire {rev['id']}`)",
            f"{tid}：审查 {rev['id']} 正挂在 {old_pane} 下运行；请先等审查结束或回收它（`pm.py retire {rev['id']}`）",
        ))
    old_cwd = info.get("cwd") or ""
    plan = reattach_plan_for(ctx, task, old_cwd)
    if plan["how"] == "fresh" and not confirmed:
        return ask_adopt_fresh_for(ctx, task, plan, old_pane)

    lock = ctx.home.reattach / f"{tid}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if stale_lock(lock):
        with contextlib.suppress(OSError):
            lock.unlink()
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise Refused(ctx.config.tr(f"{tid} is being reattached or adopted already", f"{tid} 正在接回或收归座位"))
    os.write(fd, f"{os.getpid()} {int(ctx.clock.time())}\n".encode())
    os.close(fd)
    try:
        if worker_busy_for(ctx, old_pane):
            raise Refused(ctx.config.tr(
                f"{tid}: {old_pane} started working again; nothing changed",
                f"{tid}：{old_pane} 又开始干活了；什么都没改",
            ))
        rev = active_review_of_for(ctx, tid)
        if rev:
            raise Refused(ctx.config.tr(
                f"{tid}: active review {rev['id']} started under {old_pane}; finish or retire the review "
                f"first (`pm.py retire {rev['id']}`)",
                f"{tid}：审查 {rev['id']} 已挂在 {old_pane} 下启动；请先等审查结束或回收它（`pm.py retire {rev['id']}`）",
            ))
        ledger.change(tid, lambda cur, _ch: {**cur.raw, "switching": ctx.clock.now()})
        try:
            end_terminal_for(ctx, old)
            name = task.get("agent") or task["id"]
            pane, workspace = start_beside_pm_for(ctx, task, plan, name)
            if not pane:
                unmark_switching_for(ctx, tid)
                raise Refused(ctx.config.tr(
                    f"ended {old_pane}, but no terminal could be started for {tid}; run `pm.py reattach {tid}`",
                    f"已关掉 {old_pane}，但没能为 {tid} 开出新终端；请运行 `pm.py reattach {tid}`",
                ))
        except BaseException:
            unmark_switching_for(ctx, tid)
            raise
        made = pane[3:] if pane.startswith("hc:") else ""
        tab = (
            tab_title(task.get("tab") or task["title"], task_bug(task, cfg=ctx.config), made, cfg=ctx.config)
            if made and ctx.hc.new_tabs(caller_pane=ctx.pane) else ""
        )
        named = bool(made and ctx.hc.worker_tab(made, task["id"], tab, parent=task.get("parent") or "", caller_pane=ctx.pane))

        def _apply_adopt(cur: Task | None, ch: Change) -> dict[str, Any]:
            assert cur is not None
            r = cur.raw
            previous = r.get("pane") or ""
            adopting = r.pop("adopting", None)
            r.pop("switching", None)
            r.pop("closed", None)
            if isinstance(adopting, dict):
                for f in QUESTION_FIELDS:
                    r.pop(f, None)
                if r.get("status") == "blocked" and adopting.get("from"):
                    r["status"] = adopting["from"]
            r["pane"], r["workspace"] = pane, workspace
            r["worker_pane"] = pane
            if tab:
                r["agent"] = tab
                ch.note_on(r, f"tab={tab}" + ("" if named else not_renamed(cfg=ctx.config)))
            if plan["how"] == "resume":
                r["session"] = {"kind": plan["kind"], "id": plan["session"]}
                ch.note_on(r, ctx.config.tr(
                    f"adopted under {pm_pane}: ended orphan {previous} and resumed {plan['kind']} session "
                    f"{plan['session']} in {pane}",
                    f"收归 {pm_pane} 座位下：关掉孤儿终端 {previous}，在 {pane} 恢复了 {plan['kind']} 会话 "
                    f"{plan['session']}",
                ))
            else:
                clear_task_session_for(ctx, r)
                ch.note_on(r, ctx.config.tr(
                    f"adopted under {pm_pane} (--confirmed): ended orphan {previous} and started {plan['kind']} "
                    f"in {pane} with brief and latest ledger entries",
                    f"收归 {pm_pane} 座位下（已确认）：关掉孤儿终端 {previous}，在 {pane} 新开了 {plan['kind']}，"
                    "交给它任务书和最近的台账记录",
                ))
            if made:
                r["round"] = {"terminal": made, "at": ctx.clock.now(), "turn": None}
            return r

        updated = ledger.change(tid, _apply_adopt)
        assert updated is not None
        seen: dict[str, Any] = {}
        sent = not made or _round_sent_for(
            ctx, tid, made,
            send_when_ready_for(
                ctx, made, plan["prompt"], tries=30, pause=2,
                strict=plan["kind"] in ("claude", "codex"),
                trust=plan["cwd"], kind=plan["kind"], seen=seen,
            ),
            seen,
        )
        if not sent:
            seen_line = ctx.hc.screen_line(made)
            msg = ctx.config.tr(f"adopt prompt not sent; the screen: {seen_line}", f"收归座位后的提示没送达；屏幕上是：{seen_line}")
            ledger.change(tid, lambda cur, ch: (ch.note_on(cur.raw, msg), cur.raw)[1])
            raise Refused(ctx.config.tr(
                f"{pane} is started under {pm_pane} but the prompt was not sent. Its screen: {seen_line}",
                f"{pane} 已在 {pm_pane} 下开出，但提示没送达。屏幕上是：{seen_line}",
            ))
        line = (
            f"{plan['how']} {plan['kind']} pane={pane} parent={pm_pane}"
            + (f" session={plan['session']}" if plan["session"] else "")
        )
        _deliver_later_for(ctx, updated.raw["repo"])
        return AdoptWorkerResult(task_id=tid, lines=(line,), pane=pane, how=plan["how"])
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


# --- Legacy module-level shims (Stages 1-5 compatibility) ---


def offline_now(task: Any) -> bool:
    return _offline_now_impl(Context.from_env(), task)


_DEFAULT_OFFLINE_NOW = offline_now


def reattach_prompt(task: Any, cwd: str, resumed: bool) -> str:
    return reattach_prompt_for(Context.from_env(), task, cwd, resumed)


def reattach_plan(task: Any, old_cwd: str = "") -> dict[str, Any]:
    return _reattach_plan_impl(Context.from_env(), task, old_cwd)


_DEFAULT_REATTACH_PLAN = reattach_plan


def start_beside_pm(task: Any, plan: dict[str, Any], name: str) -> tuple[str, str]:
    return _start_beside_pm_impl(Context.from_env(), task, plan, name)


_DEFAULT_START_BESIDE_PM = start_beside_pm
