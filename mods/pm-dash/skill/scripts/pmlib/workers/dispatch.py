"""Dispatch helpers: worker command assembly, herdr-core placement, advisor/Fable question text, held tasks,
and dispatch log notes. Layer 3."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

from ..agents.profiles import fallback_said, worker_summary
from ..context import Context
from ..errors import Refused
from ..ledger.ledger import Change, Ledger
from ..ledger.task import Task, hc_terminal_of
from ..memory.layer import native_memory
from ..project.project import ProjectRegistry
from .codex_pool import codex_pool_for


PREAPPROVED = (
    "Fable pre-approved by the user (config.json deep.confirmed)",
    "用户已长期同意用 Fable（config.json deep.confirmed）",
)


def tui_agent_gone_for(ctx: Context, pane: str) -> bool:
    """In the herdr terminal UI: no agent runs in this pane any more (False when the list is not known)."""
    listing = ctx.tui.agents()
    return bool(listing) and pane not in {x.get("pane_id") for x in listing}


def tui_agent_gone(pane: str) -> bool:
    return tui_agent_gone_for(Context.from_env(), pane)


def ask_rule_for(ctx: Context) -> str:
    """Said with every Fable question: the way past it is the user's answer, never another model."""
    return ctx.config.tr(
        "Do not switch to another profile or model to get past this question: whether hard is used instead "
        "is the user's answer. Only if the user says Fable is fine from now on, not just this once, set "
        "\"deep\": {\"confirmed\": true} in config.json (references/config.md) and record it with `pm.py decide`.",
        "不要为了绕开这个问题改用别的档位或模型：要不要改用 hard 由用户回答。只有用户明确说以后都可以用 Fable（不是只这一次），"
        "才在 config.json 里设置 \"deep\": {\"confirmed\": true}（见 references/config.md），并用 `pm.py decide` 记下。",
    )


def ask_rule() -> str:
    return ask_rule_for(Context.from_env())


def no_fable_answer_for(ctx: Context, profile: str) -> str:
    """The question card's answer for a user who has no Fable at all."""
    return ctx.config.tr(
        f'No Fable: use {profile} without the advisor, and set "fable": false in config.json',
        f'没有 Fable：改用不带 advisor 的 {profile}，并在 config.json 里设置 "fable": false',
    )


def no_fable_answer(profile: str) -> str:
    return no_fable_answer_for(Context.from_env(), profile)


def advisor_refused_for(ctx: Context, a: Any) -> str:
    return ctx.config.tr(
        f"this account has not agreed to Fable's billing yet, or cannot use Fable at all. Billing: run /model "
        f"fable once in any Claude session. No Fable: use hard without the advisor (`--profile "
        f"{a.profile or 'hard'} --advisor none`), and set \"fable\": false in config.json so that hard runs "
        f"without it and no Fable is used again.",
        f"这个账号还没同意 Fable 计费，或者根本用不了 Fable。计费的问题：在任意 Claude 会话里运行一次 /model fable。"
        f"没有 Fable：改用不带 advisor 的 hard（`--profile {a.profile or 'hard'} --advisor none`），"
        f"并在 config.json 里设置 \"fable\": false，以后 hard 不带 advisor，也不会再用 Fable。",
    )


def advisor_refused(a: Any) -> str:
    return advisor_refused_for(Context.from_env(), a)


def hold_exited_for(
    ctx: Context,
    task_id: str,
    spec: Any,
    seen: str,
    place: dict[str, Any] | None = None,
    *,
    emitted_lines: Iterable[str] = (),
) -> None:
    """A worker started with an advisor exited at once: block the task with a question and raise `Refused`."""
    answers = [
        ctx.config.tr("I ran /model fable: dispatch again", "已运行 /model fable，重新派发"),
        no_fable_answer_for(ctx, "hard"),
    ]
    msg = (
        ctx.config.tr(
            f"status=blocked; the worker exited at once with advisor {spec.advisor} (its screen: {seen}). ",
            f"status=blocked；带 advisor {spec.advisor} 起的 worker 一启动就退出了（屏幕：{seen}）。",
        )
        + advisor_refused_for(ctx, spec)
    )

    def _hold(cur: Task | None, ch: Change) -> dict[str, Any]:
        assert cur is not None
        raw = cur.raw
        raw.update(status="blocked", held="advisor", options=answers, pane=ctx.pane)
        if place:
            raw["held_in"] = place
        ch.note_on(raw, msg, options=answers)
        return raw

    Ledger(ctx).change(task_id, _hold)
    raise Refused(
        ctx.config.tr(
            f"{task_id}: blocked. The worker exited at once with --advisor {spec.advisor}: ",
            f"{task_id}：已标成 blocked。带 --advisor {spec.advisor} 的 worker 一启动就退出了：",
        )
        + advisor_refused_for(ctx, spec)
        + ctx.config.tr(
            " Then run the same dispatch again; it reuses this task and its worktree.",
            "之后再运行同一条 dispatch，会接着用这个任务和它的工作树。",
        ),
        payload={"emitted_lines": list(emitted_lines)} if emitted_lines else None,
    )


def held_task_for(ctx: Context, repo: str, branch: str | None, title: str | None = None) -> dict[str, Any] | None:
    """The task dispatch registered for this branch without a worker at work in it."""
    def same(t: dict[str, Any]) -> bool:
        if branch:
            return t.get("branch") == branch
        return (
            bool(title)
            and not t.get("branch")
            and bool(t.get("held_here") or t.get("in_place"))
            and t.get("title") == title
        )

    return next(
        (
            t for t in Ledger(ctx).raw_tasks()
            if t.get("held") and t.get("status") == "blocked" and t.get("repo") == repo and same(t)
        ),
        None,
    )


def held_task(repo: str, branch: str | None, title: str | None = None) -> dict[str, Any] | None:
    return held_task_for(Context.from_env(), repo, branch, title=title)


def dispatch_note_for(ctx: Context, spec: Any) -> str:
    text = f"dispatched to {spec.name} ({worker_summary(spec)})"
    if spec.advisor_dropped:
        text += ctx.config.tr(
            f"; {spec.kind} takes no advisor, advisor {spec.advisor_dropped} left out",
            f"；{spec.kind} 没有 advisor 参数，已忽略 advisor {spec.advisor_dropped}",
        )
    pool = getattr(spec, "pool_said", "")
    return (
        text
        + fallback_said(spec, tr_fn=ctx.config.tr)
        + (f"; {pool}" if pool else "")
        + ("; " + ctx.config.tr(*PREAPPROVED) if getattr(spec, "preapproved", False) else "")
    )


def dispatch_note(a: Any) -> str:
    return dispatch_note_for(Context.from_env(), a)


def worker_argv_for(
    ctx: Context,
    spec: Any,
    reads: Iterable[str | Path] = (),
    repo: str | Path | None = None,
    extra: Sequence[str] = (),
    wrap: bool = False,
    memory: bool = True,
    writes: Iterable[str | Path] = (),
) -> list[str]:
    """Assemble a worker's command line from `spec`, `reads`, `repo`, `extra`, `wrap`, `memory`, and `writes`."""
    codex_rec = ProjectRegistry(ctx).pm_record(repo) if (spec.kind == "codex" and repo) else None
    pool_active = bool(codex_pool_for(ctx, repo)) if spec.kind == "codex" else False
    mine: dict[str, Any] = {}
    if memory:
        worker_name = getattr(spec, "name", None) or getattr(spec, "branch", None) or ""
        create_mem = not getattr(spec, "dry_run", False)
        if getattr(ctx, "_legacy", False):
            mine = native_memory(spec.kind, repo, "worker", worker_name, create=create_mem)
        else:
            mem_root = ctx.home.memory_dir(repo) if repo else None
            mine = ctx.agents.native_memory_settings(spec.kind, mem_root, "worker", worker_name, create=create_mem)
    return ctx.agents.worker_argv(
        spec,
        reads,
        extra=extra,
        wrap=wrap,
        codex_rec=codex_rec,
        codex_pool_active=pool_active,
        memory_settings=mine,
        writes=writes,
    )


def worker_argv(
    a: Any,
    reads: Iterable[str | Path] = (),
    repo: str | Path | None = None,
    extra: Sequence[str] = (),
    wrap: bool = False,
    memory: bool = True,
    writes: Iterable[str | Path] = (),
) -> list[str]:
    return worker_argv_for(Context.from_env(), a, reads=reads, repo=repo, extra=extra, wrap=wrap, memory=memory, writes=writes)


def worker_placement_for(ctx: Context) -> list[str]:
    """How `hc run` places a worker: as a sub-agent of the PM's terminal, outliving it."""
    return ["--parent", ctx.pane[3:], "--outlive-parent", "--no-notify"] if ctx.pane.startswith("hc:") else ["--no-parent"]


def worker_placement() -> list[str]:
    return worker_placement_for(Context.from_env())


def review_placement_for(ctx: Context, task: Any, fallback_pane: str = "") -> list[str]:
    """How `hc run` places a reviewer: under the reviewed task's live hc worker terminal, else PM terminal."""
    raw = task.raw if isinstance(task, Task) else task
    worker = hc_terminal_of(raw) if isinstance(raw, dict) else ""
    if worker and "/" not in worker:
        info = ctx.hc.get(worker)
        if info is not None and info.is_live:
            return ["--parent", worker, "--no-notify"]
    if ctx.pane.startswith("hc:") and ctx.pane[3:] != worker:
        return ["--parent", ctx.pane[3:], "--no-notify"]
    pm_pane = fallback_pane if (fallback_pane or "").startswith("hc:") else ""
    if not pm_pane and isinstance(raw, dict) and raw.get("repo"):
        pm_pane = (ProjectRegistry(ctx).hc_pm(raw["repo"]) or {}).get("pane_id") or ""
    if pm_pane.startswith("hc:") and pm_pane[3:] != worker:
        return ["--parent", pm_pane[3:], "--no-notify"]
    return ["--no-parent"]


def review_placement(task: Any, fallback_pane: str = "") -> list[str]:
    return review_placement_for(Context.from_env(), task, fallback_pane=fallback_pane)
