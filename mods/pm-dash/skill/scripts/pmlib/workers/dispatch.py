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
from ..osutil import clip
from ..project.conversation import Conversation, conversation_events
from ..project.project import ProjectRegistry
from .codex_pool import codex_pool_for


THIN_BRIEF_REFERENCES = Path(__file__).resolve().parents[3] / "references"
THIN_BRIEF_CONV_LIMIT = 5
THIN_BRIEF_SNIPPET_CHARS = 160

_THIN_FALLBACK_EN = """[Task: {title}. From the PM ({pane})]

Where: {where}

What the user asked (verbatim):
{ask}

Attachments:
{attachments}

Recent conversation pointers ({conversation_path}):
{conversation_pointers}

PM note:
{note}

Investigation & working rules:
- Investigate the codebase and facts from first principles before making changes; do not guess.
- If a product decision or user confirmation is needed, stop and report `blocked` with clear options rather than assuming.
- Stay within the requested scope; do not add unnecessary scripts, frameworks, or abstractions.
- Run targeted checks for what you changed and summarize them concisely.

Red lines:
- Do not touch the user's running apps or system settings; test only in isolated directories.
- No `git add -A`, no push, no merge.

Commits: 1–3, conventional style. Write a brief evidence note in `evidence/<topic>/README.md` if applicable. When done, report as the appended section says, then stop.
"""

_THIN_FALLBACK_ZH = """【任务：{title}。来自 PM（{pane}）】

工作位置：{where}

用户原话：
{ask}

附件：
{attachments}

最近对话出处（{conversation_path}）：
{conversation_pointers}

PM 补充：
{note}

调查与开工要求：
- 先从第一性原理查清代码与现场再动手，不要猜测。
- 需要产品拍板或用户确认时，立即报 `blocked` 并给出清晰选项，不要自行臆断。
- 严格控制在需求范围内，不加不需要的脚本、框架或抽象层。
- 跑完与改动相关的针对性检查并简明汇报。

红线：
- 不碰用户正在运行的应用或系统设置，测试一律用隔离目录。
- 不用 `git add -A`，不 push，不合并。

提交：1–3 个，conventional 风格。必要时在 `evidence/<topic>/README.md` 写简短证据说明。完成后按末尾追加的「汇报」一段写进台账，然后停下。
"""


def thin_brief_title(ask: str) -> str:
    """Derive a concise default task title from a `--ask` prompt when no positional title is given."""
    flat = " ".join(str(ask or "").split()).strip()
    if not flat:
        return "Task"
    return clip(flat, 56)


def _load_thin_brief_template(ctx: Context) -> str:
    zh = ctx.config.lang() == "zh"
    fname = "thin-brief-template.zh.md" if zh else "thin-brief-template.md"
    path = THIN_BRIEF_REFERENCES / fname
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except OSError:
        pass
    return _THIN_FALLBACK_ZH if zh else _THIN_FALLBACK_EN


def recent_conversation_pointers_for(
    ctx: Context,
    repo: str | Path,
    *,
    limit: int = THIN_BRIEF_CONV_LIMIT,
) -> tuple[str, list[str]]:
    """Return `(conversation_path, pointer_lines)` for the most recent user/PM exchanges in this project."""
    conv = Conversation(ctx, repo)
    conv_path = conv.path
    events = conversation_events(conv_path) if conv_path.is_file() else []
    turns = [
        e for e in events
        if isinstance(e, dict) and e.get("type") in ("user", "pm") and str(e.get("text") or "").strip()
    ]
    recent = turns[-max(1, int(limit)):]
    lines: list[str] = []
    for e in recent:
        role = ctx.config.tr("User", "用户") if e.get("type") == "user" else "PM"
        seq_part = f"seq #{e['seq']}" if isinstance(e.get("seq"), int) else ""
        at_part = str(e.get("at") or "").strip()
        meta = " / ".join(x for x in (seq_part, at_part) if x)
        snippet = clip(" ".join(str(e.get("text") or "").split()), THIN_BRIEF_SNIPPET_CHARS)
        lines.append(f"- [{meta}] {role}: {snippet}" if meta else f"- {role}: {snippet}")
    return str(conv_path), lines


def assemble_thin_brief_for(
    ctx: Context,
    *,
    repo: str | Path,
    title: str,
    ask: str,
    attachments: Sequence[str] = (),
    note: str = "",
    branch: str | None = None,
    base: str | None = None,
    here: bool = False,
) -> str:
    """Assemble a thin-dispatch worker brief from the bundled template, verbatim `--ask`, attachments,
    recent conversation pointers, and optional PM `--note` (`pm-stuck-root-fix.md` §3.8 O-b, D4)."""
    tr = ctx.config.tr
    template = _load_thin_brief_template(ctx)
    if here:
        where = tr(f"in-place project directory `{repo}`", f"项目主目录 `{repo}`（就地工作）")
    else:
        base_str = f", based on `{base}`" if base else ""
        base_zh = f"，基于 `{base}`" if base else ""
        where = tr(
            f"the worktree and branch `{branch or ''}`{base_str} created by `pm.py dispatch`",
            f"`pm.py dispatch` 创建的工作树与分支 `{branch or ''}`{base_zh}",
        )
    pane = ctx.pane or "pm.py"
    clean_attachments = [str(p).strip() for p in attachments if str(p or "").strip()]
    if clean_attachments:
        att_lines = []
        for raw in clean_attachments:
            p = Path(raw).expanduser()
            resolved = str(p.resolve()) if p.exists() else raw
            att_lines.append(f"- `{resolved}`")
        att_block = "\n".join(att_lines)
    else:
        att_block = tr("- (none)", "- （无）")

    conv_path, pointer_lines = recent_conversation_pointers_for(ctx, repo)
    pointers_block = "\n".join(pointer_lines) if pointer_lines else tr("- (no prior conversation)", "- （暂无历史对话）")
    note_clean = str(note or "").strip()
    note_block = note_clean if note_clean else tr("(none)", "（无）")

    out = template
    for key, val in (
        ("{title}", str(title or "").strip() or thin_brief_title(ask)),
        ("{pane}", pane),
        ("{where}", where),
        ("{ask}", str(ask or "").strip()),
        ("{attachments}", att_block),
        ("{conversation_path}", conv_path),
        ("{conversation_pointers}", pointers_block),
        ("{note}", note_block),
    ):
        out = out.replace(key, val)
    return out


def write_thin_brief_for(ctx: Context, label: str, content: str) -> Path:
    """Persist an assembled thin brief under `<ledger>/sent/` so review/escalate can read `task['brief']`."""
    ctx.home.sent_dir.mkdir(parents=True, exist_ok=True)
    stamp = int(ctx.clock.time() * 1000)
    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in (label or "task")).strip("-")[:40] or "task"
    path = ctx.home.sent_dir / f"thin-{safe_label}-{stamp}.md"
    path.write_text(content, encoding="utf-8")
    return path


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
