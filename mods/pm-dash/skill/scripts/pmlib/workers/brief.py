"""Putting a worker's brief together: the project of the task it is for, and the report section appended to briefs.
Layer 3. Outside-worktree read permissions (`HERDR_DOCS`, `docs_line`, `outside_reads`, `wide_folder`,
`read_settings`) live in `pmlib.agents.reads` (Layer 1) and are re-exported here for callers."""
from __future__ import annotations

import json
from pathlib import Path

from ..agents.reads import HERDR_DOCS, docs_line, outside_reads, read_settings, wide_folder
from ..context import Context
from ..ledger.ledger import Ledger
from ..memory.layer import MemoryLayer
from ..store import valid_task_id

__all__ = [
    "HERDR_DOCS",
    "docs_line",
    "keep_sent",
    "keep_sent_for",
    "outside_reads",
    "read_settings",
    "report_section",
    "report_section_for",
    "sent_repo",
    "sent_repo_for",
    "wide_folder",
]


def sent_repo_for(ctx: Context, task_id: str) -> str | None:
    """The project of a task a brief is written for, None when the task is not on record."""
    path = ctx.home.task(task_id)
    try:
        return json.loads(path.read_text()).get("repo")
    except (OSError, ValueError):
        return None


def report_section_for(ctx: Context, task_id: str) -> str:
    """Appended to every brief: the worker reports in the ledger, and that report is all the PM reads."""
    cmd = ctx.procs.pm_command()
    task = ctx.store.task(task_id) if valid_task_id(task_id) else None
    ref = Ledger(ctx).task_ref(task) if task else task_id
    return "\n\n" + ctx.config.tr(
        f"Reporting (task {ref}):\n"
        f"- When done: `{cmd} update {task_id} --status review --commit <sha> --note \"<what changed; which "
        "checks ran; what was not verified>\"`\n"
        f"- When a person has to decide something: `{cmd} update {task_id} --status blocked --note \"<the question>\"`\n"
        f"- Sub-steps (optional, silent write, does not wake the PM): `{cmd} update {task_id} --plan \"[x] done; [>] current; [ ] next\"`\n"
        "The PM reads only this report, never your screen. Keep the note under 600 characters, and write it, "
        "like every ledger note, in the user's language: the user reads it in the thread panel.",
        f"汇报（任务 {ref}）：\n"
        f"- 做完时：`{cmd} update {task_id} --status review --commit <sha> --note \"<改了什么；跑了哪些检查；"
        "哪些没验证>\"`\n"
        f"- 需要人来决定时：`{cmd} update {task_id} --status blocked --note \"<问题>\"`\n"
        f"- 开发子步骤（可选，静默落盘，不唤醒 PM）：`{cmd} update {task_id} --plan \"[x] 已做完; [>] 当前步; [ ] 下一步\"`\n"
        "PM 只看这条汇报，不会读你的屏幕。写在 600 字以内；这条和所有台账记录都用中文写，用户会在线程侧栏里读到。") + "\n"


def keep_sent_for(ctx: Context, task_id: str, brief: str) -> Path:
    """The brief as the worker gets it, report section included, kept as sent/<id>.md for a resend."""
    path = ctx.home.sent_dir / f"{task_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    repo = sent_repo_for(ctx, task_id)
    mem = MemoryLayer(ctx, repo).memory_part() if repo else ""
    path.write_text(brief + report_section_for(ctx, task_id) + mem + ctx.agents.docs_line())
    return path


def keep_sent(task_id: str, brief: str) -> Path:
    """The brief as the worker gets it, report section included, kept as sent/<id>.md for a resend."""
    return keep_sent_for(Context.from_env(), task_id, brief)


def report_section(task_id: str) -> str:
    """Appended to every brief: the worker reports in the ledger, and that report is all the PM reads."""
    return report_section_for(Context.from_env(), task_id)


def sent_repo(task_id: str) -> str | None:
    """The project of a task a brief is written for, None when the task is not on record."""
    return sent_repo_for(Context.from_env(), task_id)
