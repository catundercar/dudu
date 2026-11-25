"""`Helpers(ctx)` service: helper brief generation, start/done/wait/ls/stop orchestration, owner resolution and
authorization, and SessionStart/Stop hook logic over an explicit `Context`. Zero globals, zero `sys.exit`,
zero `print`. Layer 3.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Sequence

from ..agents.base import HOOKED_KINDS, terminal_kind
from ..agents.profiles import WorkerSpec
from ..agents.reads import docs_line
from ..caller import Caller
from ..context import Context
from ..errors import NotFound, Refused
from ..events import stalls as stalls_mod
from ..events.deliver import Delivery
from ..home import project_slug
from ..ledger.ledger import Ledger, slugify
from ..ledger.task import ACTIVE
from ..memory.layer import MemoryLayer
from ..osutil import clip, file_text
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry
from ..store import file_lock, lock_file, replace_task_file, unlock_file, valid_task_id, write_atomic
from ..terminals.screen import classify_stuck_screen
from ..workers.service import Workers
from .config import (
    HELPER_TIMEOUT,
    helper_env_for,
    helper_hc_name_for,
    helper_placement_for,
    helpers_max_for,
    helpers_project_max_for,
    helpers_timeout_for,
    resolve_helper_spec,
)
from .records import (
    _clear_helper_cleanup_for,
    _format_helper_wait_results,
    _harvest_entry_for,
    _helper_owner_ledger_paths_for,
    _match_helper,
    capture_helper_screen_for,
    finalize_helper_for,
    format_helper_wait_lines,
    helper_elapsed,
    helper_entries,
    helper_excerpt,
    helper_remaining,
    helper_result_path_for,
    helper_result_text,
    helper_wait_guard_for,
    kill_helper_terminal_for,
    project_active_counts_for,
    reconcile_owner_helpers_for,
    reconcile_project_helpers_for,
    update_helper_owner_for,
)


@dataclass
class HelperStartRequest:
    """Typed input for `Helpers.start`."""

    prompt: str | None = None
    brief: str | None = None
    name: str | None = None
    profile: str | None = None
    kind: str | None = None
    model: str | None = None
    effort: str | None = None
    advisor: str | None = None
    codex_profile: str | None = None
    timeout: int | None = None
    cwd: str | None = None
    task: str | None = None
    pm: bool = False
    repo: str = "."
    confirmed: bool = False
    exec_mode: bool = False
    async_: bool = False
    for_task: str | None = None
    dry_run: bool = False
    quiet: bool = False
    parent_pm: bool = False

    @classmethod
    def from_args(cls, a: Any) -> HelperStartRequest:
        return cls(
            prompt=getattr(a, "prompt", None),
            brief=getattr(a, "brief", None),
            name=getattr(a, "name", None),
            profile=getattr(a, "profile", None),
            kind=getattr(a, "kind", None),
            model=getattr(a, "model", None),
            effort=getattr(a, "effort", None),
            advisor=getattr(a, "advisor", None),
            codex_profile=getattr(a, "codex_profile", None),
            timeout=getattr(a, "timeout", None),
            cwd=getattr(a, "cwd", None),
            task=getattr(a, "task", None),
            pm=bool(getattr(a, "pm", False)),
            repo=getattr(a, "repo", None) or ".",
            confirmed=bool(getattr(a, "confirmed", False)),
            exec_mode=bool(getattr(a, "exec_mode", False)),
            async_=bool(getattr(a, "async_", False)),
            for_task=getattr(a, "for_task", None),
            dry_run=bool(getattr(a, "dry_run", False)),
        )


@dataclass(frozen=True)
class HelperStartResult:
    """Structured outcome of `Helpers.start`."""

    name: str = ""
    terminal: str = ""
    result: str = ""
    line: str = ""
    stderr_lines: tuple[str, ...] = ()
    dry_run_plan: dict[str, Any] | None = None
    is_async: bool = False


@dataclass(frozen=True)
class HelperDoneResult:
    """Structured outcome of `Helpers.done`."""

    name: str
    result: str
    transitioned: bool
    line: str


@dataclass(frozen=True)
class HelperWaitResult:
    """Structured outcome of `Helpers.wait`."""

    items: list[dict[str, Any]]
    lines: tuple[str, ...]
    exit_code: int = 0
    stderr_line: str = ""


@dataclass(frozen=True)
class HelperLsResult:
    """Structured outcome of `Helpers.ls`."""

    entries: list[dict[str, Any]]
    lines: tuple[str, ...]


@dataclass(frozen=True)
class HelperStopResult:
    """Structured outcome of `Helpers.stop`."""

    stopped: list[dict[str, Any]]
    lines: tuple[str, ...]


@dataclass(frozen=True)
class HelperStopHookResult:
    """Structured outcome of `Helpers.handle_stop_hook`."""

    block_payload: dict[str, Any] | None = None
    finalized: bool = False


def _default_helper_name(prompt_text: str, existing_names: set[str | None]) -> str:
    """Derive a short helper name from prompt text or helper-1, helper-2, ..."""
    words = re.findall(r"[a-zA-Z0-9]+", prompt_text or "")[:3]
    base = slugify("-".join(words))[:20] if words else ""
    if not base:
        base = "helper"
    if base not in existing_names:
        return base
    for i in range(2, 100):
        cand = f"{base[:20].rstrip('-')}-{i}"
        if cand not in existing_names:
            return cand
    return f"helper-{os.urandom(2).hex()}"


class Helpers:
    """Layer 3 service owning helper lifecycle (`start`, `done`, `wait`, `ls`, `stop`) and helper hook logic."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._ledger = Ledger(ctx)
        self._projects = ProjectRegistry(ctx)
        self._workers = Workers(ctx)

    @property
    def _caller(self) -> Caller:
        return self.ctx.caller if self.ctx.caller is not None else Caller(self.ctx)

    def brief(
        self,
        name: str,
        owner_id: str,
        prompt_text: str,
        result_path: str | Path,
        cwd: str | Path,
        *,
        exec_mode: bool = False,
        repo: str = "",
    ) -> str:
        """Instructions sent to a newly started helper."""
        cmd = self.ctx.procs.pm_command()
        rpath = str(result_path)
        docs = docs_line(herdr_docs=self.ctx.herdr_docs, tr_fn=self.ctx.config.tr)
        if exec_mode:
            mem = MemoryLayer(self.ctx, repo).memory_part() if repo else ""
            return self.ctx.config.tr(
                f"[Execution Helper {name} for {owner_id}]\n\n"
                f"Working directory: {cwd}\n"
                "Rules (PM-delegated execution helper):\n"
                "- Perform ONLY the delegated execution task below; do not start nested helpers or make unrequested repo edits.\n"
                f"- Check project/personal memories if needed via `{cmd} recall <name>`.\n"
                f"- Write your concise, actionable conclusion to: {rpath}\n\n"
                f"Task:\n{prompt_text.strip()}\n\n"
                "When done:\n"
                f"1. Write your concise conclusion to `{rpath}` (or pass `--text` / `--stdin` to `{cmd} helper done`).\n"
                f"2. Run: `{cmd} helper done`\n"
                "Then stop.\n" + mem + docs,
                f"【执行 helper {name}，归属 {owner_id}】\n\n"
                f"工作目录：{cwd}\n"
                "规则（PM 委派的执行 helper）：\n"
                "- 只执行下方委派的操作，不要再开子 helper，不要做任务外改动。\n"
                f"- 如需查阅环境/部署记忆，运行 `{cmd} recall <name>`。\n"
                f"- 把简明结论写进结果文件：{rpath}\n\n"
                f"任务：\n{prompt_text.strip()}\n\n"
                "完成时：\n"
                f"1. 把简明可操作的结论写进 `{rpath}`（或通过 `{cmd} helper done --text \"...\"` / `--stdin` 写入）。\n"
                f"2. 运行：`{cmd} helper done`\n"
                "然后停下。\n" + mem + docs,
            )
        return self.ctx.config.tr(
            f"[Helper {name} for {owner_id}]\n\n"
            f"Working directory: {cwd}\n"
            "Rules (read-only temporary helper):\n"
            "- Do NOT edit repository files, create branches, make commits, register ledger tasks, or start nested helpers.\n"
            f"- Write your conclusion ONLY to: {rpath}\n\n"
            f"Task:\n{prompt_text.strip()}\n\n"
            "When done:\n"
            f"1. Write your concise, actionable conclusion to `{rpath}` (or pipe it via `{cmd} helper done --stdin`).\n"
            f"2. Run: `{cmd} helper done`\n"
            "Then stop.\n" + docs,
            f"【临时 helper {name}，归属 {owner_id}】\n\n"
            f"工作目录：{cwd}\n"
            "规则（只读临时 helper）：\n"
            "- 不要修改仓库文件、建分支、提交、登记台账任务，也不要再开子 helper。\n"
            f"- 只把结论写进结果文件：{rpath}\n\n"
            f"任务：\n{prompt_text.strip()}\n\n"
            "完成时：\n"
            f"1. 把简明可操作的结论写进 `{rpath}`（或通过 `{cmd} helper done --stdin` 写入）。\n"
            f"2. 运行：`{cmd} helper done`\n"
            "然后停下。\n" + docs,
        )

    def find_by_self(self, info: dict[str, str]) -> tuple[str, str, str, str, dict[str, Any]] | None:
        """Locate `(owner_kind, owner_id, slug, repo, entry)` for a helper identified by `Caller.helper_self_info()`."""
        of = info.get("of") or ""
        name = info.get("name") or ""
        proj = info.get("project") or ""
        term = info.get("terminal") or ""
        # 1. PM-owned helper: helper.of = pm-<slug>
        if of.startswith("pm-"):
            slug = proj or of[3:]
            reg = self.ctx.store.registration(slug)
            if reg:
                items = helper_entries(reg)
                idx = _match_helper(items, term=term, name=name)
                if idx >= 0:
                    return "pm", f"pm-{slug}", slug, reg.get("repo") or "", items[idx]
        # 2. Task-owned helper: helper.of = <task_id>
        if of and valid_task_id(of):
            task = self.ctx.store.task(of)
            if task:
                items = helper_entries(task)
                idx = _match_helper(items, term=term, name=name)
                if idx >= 0:
                    repo = task.get("repo") or ""
                    slug = proj or (project_slug(repo) if repo else "")
                    return "task", task["id"], slug, repo, items[idx]
        # 3. Fallback scan by terminal across registrations and tasks
        if term:
            for reg in self.ctx.store.registrations():
                items = helper_entries(reg)
                idx = _match_helper(items, term=term)
                if idx >= 0:
                    repo = reg.get("repo") or ""
                    slug = project_slug(repo) if repo else (reg.get("name") or "")[3:]
                    return "pm", f"pm-{slug}", slug, repo, items[idx]
            for task in self._ledger.raw_tasks():
                items = helper_entries(task)
                idx = _match_helper(items, term=term)
                if idx >= 0:
                    repo = task.get("repo") or ""
                    return "task", task["id"], project_slug(repo) if repo else proj, repo, items[idx]
        return None

    def session_start_message(self) -> str | None:
        """SessionStart hook branch for a helper terminal: return reminder text, or None if caller is not a helper."""
        if not self.ctx.hc_terminal:
            return None
        info = self._caller.helper_self_info()
        if not info:
            return None
        found = self.find_by_self(info)
        entry = found[4] if found else {}
        result = entry.get("result") or ""
        cmd = self.ctx.procs.pm_command()
        if entry.get("mode") == "exec":
            return self.ctx.config.tr(
                f"You are execution helper {info.get('name') or '?'} for {info.get('of') or '?'}. "
                "Carry out ONLY the delegated execution task in your brief; do not start nested helpers. "
                + (f"Write your conclusion to {result}, then run `{cmd} helper done`." if result
                   else f"Write your conclusion to the result file in your brief, then run `{cmd} helper done`."),
                f"你是 {info.get('of') or '?'} 的执行 helper {info.get('name') or '?'}。"
                "只执行任务书交给你的操作，不要再开子 helper。"
                + (f"把简明结论写进 {result}，然后运行 `{cmd} helper done`。" if result
                   else f"把简明结论写进任务书指定的结果文件，然后运行 `{cmd} helper done`。"),
            )
        return self.ctx.config.tr(
            f"You are helper {info.get('name') or '?'} for {info.get('of') or '?'} (read-only). "
            "Do not edit repository files, commit, create branches, register tasks, or start nested helpers. "
            + (f"Write your conclusion to {result}, then run `{cmd} helper done`." if result
               else f"Write your conclusion to the result file in your brief, then run `{cmd} helper done`."),
            f"你是 {info.get('of') or '?'} 的临时 helper {info.get('name') or '?'}（只读）。"
            "不要修改仓库文件、提交、建分支、登记任务，也不能再开 helper。"
            + (f"把结论写进 {result}，然后运行 `{cmd} helper done`。" if result
               else f"把结论写进任务书指定的结果文件，然后运行 `{cmd} helper done`。"),
        )

    def handle_stop_hook(self, data: dict[str, Any]) -> HelperStopHookResult:
        """Stop hook for a Claude Code or Codex helper that ended its turn without running `pm.py helper done`.
        Claude Code is nudged once (returns `block_payload`); on the second stop (or Codex) the conclusion is
        harvested from the result file, else `last_assistant_message`, else terminal screen, and delivered."""
        if not self.ctx.hc_terminal or data.get("background_tasks"):
            return HelperStopHookResult()
        info = self._caller.helper_self_info()
        if not info:
            return HelperStopHookResult()
        found = self.find_by_self(info)
        if not found:
            return HelperStopHookResult()
        owner_kind, owner_id, slug, repo, entry = found
        if entry.get("status") != "running":
            return HelperStopHookResult()
        result = Path(entry.get("result") or "")
        cmd = self.ctx.procs.pm_command()
        if self.ctx.env.get("CLAUDE_CODE_SESSION_ID") and not data.get("stop_hook_active"):
            return HelperStopHookResult(
                block_payload={
                    "decision": "block",
                    "reason": self.ctx.config.tr(
                        f"Write your conclusion to {result} and run `{cmd} helper done` before stopping.",
                        f"停下之前请把结论写进 {result} 并运行 `{cmd} helper done`。",
                    ),
                },
            )
        text = helper_result_text(result) if entry.get("result") else ""
        fallback = ""
        if not text and entry.get("result"):
            reply = str(data.get("last_assistant_message") or "").strip()
            if reply:
                header = self.ctx.config.tr(
                    "<!-- Captured from final reply: helper did not write the result file. -->\n\n",
                    "<!-- 从最终回复截取：helper 未写入结果文件。 -->\n\n",
                )
                write_atomic(result, (header + reply + "\n").encode("utf-8"), replace_fn=replace_task_file)
                text = reply
                fallback = "reply"
            else:
                captured = capture_helper_screen_for(self.ctx, self.ctx.hc_terminal, result, reason="unreported")
                if captured:
                    text = captured
                    fallback = "screen"
        summary = helper_excerpt(text) if text else ""
        finalize_helper_for(
            self.ctx, owner_kind, owner_id, slug, repo, term=self.ctx.hc_terminal, name=entry.get("name") or "",
            status="done" if text else "exited", summary=summary, fallback=fallback,
            cleanup_term=True, notify=True,
        )
        return HelperStopHookResult(finalized=True)

    def authorize_target(
        self,
        action: str,
        caller_role: str,
        caller_obj: Any,
        target_kind: str | None,
        target_id: str | None,
    ) -> None:
        """Enforce ownership boundaries for start/done/stop: a worker cannot act on PM's helpers or another task's."""
        if caller_role == "helper":
            raise Refused(self.ctx.config.tr(
                f"refused: a helper cannot {action} other helpers",
                f"已拒绝：helper 不能对其他 helper 执行 {action}",
            ))
        if caller_role in ("pm", "cli"):
            return
        # caller_role is "task" or "worker_unknown" (non-PM terminal inside hc/TUI).
        if target_kind == "pm":
            raise Refused(self.ctx.config.tr(
                f"refused: a worker cannot {action} the PM's helpers",
                f"已拒绝：worker 不能对 PM 的 helper 执行 {action}",
            ))
        if caller_role == "task" and target_id != caller_obj["id"]:
            raise Refused(self.ctx.config.tr(
                f"refused: a worker can only {action} its own task's helpers ({caller_obj['id']})",
                f"已拒绝：worker 只能对自己任务（{caller_obj['id']}）的 helper 执行 {action}",
            ))
        if caller_role == "worker_unknown" and target_kind == "task":
            t = self.ctx.store.task(target_id or "") or {}
            if t.get("pane") and t.get("pane") != self.ctx.pane:
                raise Refused(self.ctx.config.tr(
                    f"refused: a worker can only {action} its own task's helpers",
                    f"已拒绝：worker 只能对自己任务的 helper 执行 {action}",
                ))

    def resolve_owner(
        self,
        *,
        task: str | None = None,
        pm: bool = False,
        repo: str = ".",
        require_owner: bool = True,
        allow_closed_task: bool = False,
    ) -> tuple[str | None, str | None, str | None, str | None, str | None]:
        """Determine `(owner_kind, owner_id, owner_dir, repo, slug)` for helper commands.
        Returns `(None, None, None, repo, slug)` when `require_owner=False` and no specific owner applies."""
        repo_arg = repo or "."
        if task and pm:
            raise Refused(self.ctx.config.tr("pass --task or --pm, not both", "--task 和 --pm 不能同时传"))
        if task:
            t = self._ledger.load(task)
            if not allow_closed_task and t.get("status") not in ACTIVE:
                raise Refused(self.ctx.config.tr(
                    f"task {task} is {t.get('status')}: helpers require an open task",
                    f"任务 {task} 状态是 {t.get('status')}：只能在未关闭的任务下开 helper",
                ))
            resolved_repo = t.get("repo") or self.ctx.git.project_root(repo_arg)
            return "task", t["id"], t["id"], resolved_repo, project_slug(resolved_repo)
        if pm:
            resolved_repo = self.ctx.git.project_root(repo_arg)
            rec = self._projects.pm_record(resolved_repo) if resolved_repo else None
            if not rec:
                raise NotFound(self.ctx.config.tr(
                    f"no PM registration for {resolved_repo or repo_arg}",
                    f"没有找到 {resolved_repo or repo_arg} 的 PM 登记",
                ))
            actual_repo = rec.get("repo") or resolved_repo
            slug = project_slug(actual_repo)
            return "pm", f"pm-{slug}", "pm", actual_repo, slug
        # Auto-detect from caller terminal.
        if self.ctx.pane:
            caller = self._caller
            rec = caller.own_pm_record() or (
                caller.hc_registration(self.ctx.pane) if self.ctx.pane.startswith("hc:") else None
            )
            if rec and not rec.get("archived"):
                resolved_repo = rec.get("repo") or self.ctx.git.project_root(repo_arg)
                slug = project_slug(resolved_repo)
                return "pm", f"pm-{slug}", "pm", resolved_repo, slug
            mine = caller.own_task
            if not mine:
                matches = [
                    t for t in self._ledger.raw_tasks()
                    if t.get("pane") == self.ctx.pane and t.get("status") in ACTIVE
                ]
                if len(matches) == 1:
                    mine = matches[0]
            if mine:
                resolved_repo = mine.get("repo") or self.ctx.git.project_root(repo_arg)
                return "task", mine["id"], mine["id"], resolved_repo, project_slug(resolved_repo)
        if require_owner:
            raise Refused(self.ctx.config.tr(
                "cannot identify caller as a PM or task worker: run from a PM or task terminal, or pass --task <id>",
                "无法识别调用方身份（既不是已登记的 PM，也没有对应未关闭任务）：请在 PM 或 worker 终端里运行，或传入 --task <id>",
            ))
        resolved_repo = self.ctx.git.project_root(repo_arg)
        return None, None, None, resolved_repo, (project_slug(resolved_repo) if resolved_repo else None)

    def start(self, req: HelperStartRequest) -> HelperStartResult:
        """Start a read-only or PM-delegated execution helper under the caller's terminal."""
        prompt_parts: list[str] = []
        if req.brief:
            prompt_parts.append(Path(req.brief).read_text(encoding="utf-8"))
        if req.prompt:
            prompt_parts.append(req.prompt)
        prompt_text = "\n\n".join(p.strip() for p in prompt_parts if p and p.strip())
        if not prompt_text:
            raise Refused(self.ctx.config.tr(
                "helper start needs a prompt or --brief <file>",
                "helper start 需要给任务说明或 --brief <文件>",
            ))

        dry = bool(req.dry_run)
        allow_parent_pm = bool(req.parent_pm) and not self.ctx.pane
        if not dry and not self.ctx.pane.startswith("hc:") and not allow_parent_pm:
            raise Refused(self.ctx.config.tr(
                "pm.py helper start requires a herdr-core terminal ($HC_TERMINAL_ID)",
                "pm.py helper start 需要在 herdr-core 终端（$HC_TERMINAL_ID）里运行",
            ))
        # Depth limit: max depth 1 (PM -> helper or PM -> worker -> helper; never helper -> helper).
        if self._caller.helper_self_info():
            raise Refused(self.ctx.config.tr(
                "refused: a helper cannot start another helper (max depth is 1)",
                "已拒绝：helper 不能再开 helper（最大深度为 1）",
            ))

        owner_kind, owner_id, owner_dir, repo, slug = self.resolve_owner(
            task=req.task, pm=req.pm, repo=req.repo, require_owner=True,
        )
        if not repo or not slug or not owner_kind or not owner_id or not owner_dir:
            raise Refused(self.ctx.config.tr("cannot resolve project directory", "无法确定项目目录"))
        caller_role, caller_obj = self._caller.helper_caller_identity()
        if caller_role != "cli":
            self.authorize_target("start", caller_role, caller_obj, owner_kind, owner_id)
        parent_term = self.ctx.pane[3:] if self.ctx.pane.startswith("hc:") else ""
        if not dry and not parent_term:
            if not (allow_parent_pm and caller_role == "cli" and owner_kind == "pm"):
                raise Refused(self.ctx.config.tr(
                    "pm.py helper start requires a herdr-core terminal ($HC_TERMINAL_ID)",
                    "pm.py helper start 需要在 herdr-core 终端（$HC_TERMINAL_ID）里运行",
                ))
            pm_rec = self._projects.app_pm(repo)
            pm_term = str((pm_rec or {}).get("terminal") or "")
            pm_info = self.ctx.hc.get(pm_term) if pm_term else None
            if not pm_term or pm_info is None or pm_info.state != "live":
                raise Refused(self.ctx.config.tr(
                    f"PM terminal for {slug} is not online in herdr-core",
                    f"项目 {slug} 的协调者终端未在 herdr-core 中在线",
                ))
            parent_term = pm_term
        exec_mode = bool(req.exec_mode)
        if exec_mode and caller_role not in ("pm", "cli"):
            raise Refused(self.ctx.config.tr(
                "refused: only the PM may start an execution helper (--exec); workers may start read-only helpers only",
                "已拒绝：只有 PM 可以启动执行 helper（--exec）；worker 只能开只读 helper",
            ))
        async_mode = bool(req.async_)
        for_task_raw = req.for_task or ""
        for_task = self._ledger.resolve_id(for_task_raw, repo=repo) if for_task_raw else ""

        spec = resolve_helper_spec(self.ctx, req)

        timeout = req.timeout if req.timeout is not None else helpers_timeout_for(self.ctx)
        if timeout <= 0:
            raise Refused(self.ctx.config.tr(
                "--timeout must be a positive number of seconds",
                "--timeout 必须是正整数秒",
            ))

        if req.cwd:
            cwd = Path(req.cwd).expanduser().resolve()
        elif owner_kind == "task":
            task_now = self.ctx.store.task(owner_id) or {}
            cwd = Path(task_now.get("worktree") or os.getcwd()).resolve()
        else:
            cwd = Path(os.getcwd()).resolve()
        if not cwd.is_dir():
            raise Refused(f"{cwd} is not a directory")

        max_owner = helpers_max_for(self.ctx)
        max_proj = helpers_project_max_for(self.ctx)
        stderr_lines: list[str] = []

        # For dry-run, inspect current state without mutating or starting anything.
        if dry:
            spec, warn = self._workers.apply_codex_pool(spec, repo, "worker", hold=False)
            if warn:
                stderr_lines.append(warn)
            preapproved = spec.asks_first() and not req.confirmed and self._workers.deep_confirmed(repo)
            asks = spec.asks_first() and not req.confirmed and not preapproved
            rec = self.ctx.store.registration(slug) if owner_kind == "pm" else self.ctx.store.task(owner_id)
            existing = helper_entries(rec)
            running_owner = [h for h in existing if h.get("status") == "running"]
            name = slugify(req.name)[:28] if req.name else _default_helper_name(
                prompt_text, {h.get("name") for h in running_owner},
            )
            result_path = helper_result_path_for(self.ctx, slug, owner_dir, name)
            extra = self.ctx.agents.helper_extra_argv(spec.kind, exec_mode=exec_mode)
            reads = self.ctx.agents.outside_reads(repo, req.brief or "")
            writes = self.ctx.agents.helper_writes(spec.kind, result_path)
            argv = self._workers.worker_argv(spec, reads, repo, extra, wrap=True, memory=False, writes=writes)
            active_threads, running_proj = project_active_counts_for(self.ctx, repo)
            plan = {
                "what": "helper",
                "mode": "exec" if exec_mode else "readonly",
                "owner": owner_id,
                "owner_kind": owner_kind,
                "name": name,
                "profile": spec.profile or None,
                "kind": spec.kind,
                "model": spec.model,
                "effort": spec.effort,
                "codex_profile": spec.provider or None,
                "pool": spec.pool_said,
                "cwd": str(cwd),
                "result": str(result_path),
                "timeout": timeout,
                "asks_user_first": asks,
                "limits": {
                    "owner_running": len(running_owner),
                    "owner_max": max_owner,
                    "project_threads": active_threads,
                    "project_helpers": len(running_proj),
                    "project_max": max_proj,
                },
                "argv": argv,
            }
            return HelperStartResult(
                name=name,
                result=str(result_path),
                stderr_lines=tuple(stderr_lines),
                dry_run_plan=plan,
            )

        # Hold per-project helper-start lock ONLY across reconcile + limit check + codex pool + spawn + ledger record
        # (never across send_when_ready, so multiple helpers can start concurrently).
        start_lock = self.ctx.home.locks / f"helper-start-{slug}.lock"
        with file_lock(start_lock, timeout=self.ctx.store.lock_timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            reconcile_project_helpers_for(self.ctx, repo)
            rec = self.ctx.store.registration(slug) if owner_kind == "pm" else self.ctx.store.task(owner_id)
            if rec is None:
                raise NotFound(self.ctx.config.tr(
                    f"owner record for {owner_id} not found",
                    f"找不到 {owner_id} 的台账记录",
                ))
            existing = helper_entries(rec)
            running_owner = [h for h in existing if h.get("status") == "running"]
            if len(running_owner) >= max_owner:
                who = ", ".join(f"{h['name']} (hc:{h.get('terminal') or '?'})" for h in running_owner)
                raise Refused(self.ctx.config.tr(
                    f"refused: {owner_id} already has {len(running_owner)}/{max_owner} running helpers: {who}. "
                    "Wait for or stop one first (`pm.py helper wait` / `pm.py helper stop <name>`).",
                    f"已拒绝：{owner_id} 已有 {len(running_owner)}/{max_owner} 个运行中的 helper：{who}。"
                    "请先等待完成或停掉一个（`pm.py helper wait` / `pm.py helper stop <名字>`）。",
                ))

            active_threads, running_proj = project_active_counts_for(self.ctx, repo)
            total_proj = active_threads + len(running_proj)
            if total_proj >= max_proj:
                who = ", ".join(
                    f"{h['name']}({h.get('owner') or '?'}, hc:{h.get('terminal') or '?'})"
                    for h in running_proj
                ) or self.ctx.config.tr("(none)", "（无）")
                raise Refused(self.ctx.config.tr(
                    f"refused: project {slug} is at capacity ({active_threads} active thread(s) + "
                    f"{len(running_proj)} running helper(s) = {total_proj}/{max_proj}); running helpers: {who}",
                    f"已拒绝：项目 {slug} 已达并发上限（{active_threads} 个在跑线程 + {len(running_proj)} 个在跑 helper "
                    f"= {total_proj}/{max_proj}）；当前 helper：{who}",
                ))

            if req.name:
                name = slugify(req.name)[:28]
                if not name:
                    raise Refused(self.ctx.config.tr(
                        f"invalid helper name: {req.name!r}",
                        f"无效的 helper 名字：{req.name!r}",
                    ))
                clash = next((h for h in running_owner if h.get("name") == name), None)
                if clash:
                    raise Refused(self.ctx.config.tr(
                        f"helper {name} is already running in hc:{clash.get('terminal') or '?'}; "
                        "choose another --name or stop it first",
                        f"helper {name} 已经在 hc:{clash.get('terminal') or '?'} 运行中；"
                        "请换一个 --name 或先停掉它",
                    ))
            else:
                name = _default_helper_name(prompt_text, {h.get("name") for h in running_owner})

            try:
                spec, warn = self._workers.apply_codex_pool(spec, repo, "worker", hold=True)
                if warn:
                    stderr_lines.append(warn)
                preapproved = spec.asks_first() and not req.confirmed and self._workers.deep_confirmed(repo)
                if spec.asks_first() and not req.confirmed and not preapproved:
                    model_desc = spec.summary()
                    raise Refused(self.ctx.config.tr(
                        f"refused: helper profile {model_desc} uses Fable and requires user confirmation; "
                        "ask the user first and pass --confirmed, or pick another profile (e.g. --profile opus)",
                        f"已拒绝：helper 档位 {model_desc} 使用 Fable，需要先征得用户同意；请先问用户并传 --confirmed，"
                        "或改用其他档位（如 --profile opus）",
                    ))

                result_path = helper_result_path_for(self.ctx, slug, owner_dir, name)
                result_path.parent.mkdir(parents=True, exist_ok=True)
                brief_text = self.brief(name, owner_id, prompt_text, result_path, cwd, exec_mode=exec_mode, repo=repo)
                brief_saved = result_path.parent / f".{result_path.stem}-brief.md"
                write_atomic(brief_saved, brief_text.encode("utf-8"), replace_fn=replace_task_file)

                extra = self.ctx.agents.helper_extra_argv(spec.kind, exec_mode=exec_mode)
                reads = self.ctx.agents.outside_reads(repo, req.brief or "")
                writes = self.ctx.agents.helper_writes(spec.kind, result_path)
                argv = self._workers.worker_argv(spec, reads, repo, extra, wrap=True, memory=False, writes=writes)

                term_name = helper_hc_name_for(self.ctx, owner_dir, name)
                labels: tuple[str, ...] = (f"helper.of={owner_id}", f"helper={name}", f"helper.project={slug}")
                if exec_mode:
                    labels = (*labels, "helper.mode=exec")
                if for_task:
                    labels = (*labels, f"helper.task={for_task}")
                made = self.ctx.hc.start_terminal(
                    term_name, cwd, argv,
                    helper_placement_for(self.ctx, parent=parent_term if allow_parent_pm else None),
                    labels=labels,
                    env=helper_env_for(self.ctx, owner_id, name, slug),
                )
            finally:
                self._workers.pool_started(spec, repo)
            if not made:
                raise Refused(self.ctx.config.tr(
                    "hc run failed; no helper was started",
                    "hc run 失败；没有启动 helper",
                ))

            entry: dict[str, Any] = {
                "name": name,
                "terminal": made,
                "parent": parent_term,
                "owner": owner_id,
                "owner_kind": owner_kind,
                "project": slug,
                "mode": "exec" if exec_mode else "readonly",
                "cwd": str(cwd),
                "status": "running",
                "profile": spec.profile or "",
                "kind": spec.kind,
                "model": spec.model,
                "effort": spec.effort,
                "result": str(result_path),
                "prompt": clip(" ".join(prompt_text.split()), 200),
                "started": self.ctx.clock.now_sec(),
                "started_ts": self.ctx.clock.time(),
                "timeout": timeout,
                "ended": "",
                "handed": False,
                "turn_base": None,
                "summary": "",
            }
            if req.quiet:
                entry["quiet"] = True
            if for_task:
                entry["for_task"] = for_task
            if spec.provider:
                entry["provider"] = spec.provider
            start_note = self.ctx.config.tr(
                f"started helper {name} (hc:{made}, {spec.summary()}) -> {result_path}",
                f"开启 helper {name}（hc:{made}，{spec.summary()}）-> {result_path}",
            )
            update_helper_owner_for(
                self.ctx, owner_kind, owner_id, slug, lambda items: (items.append(entry), True)[1],
                task_note=start_note if owner_kind == "task" else None,
            )

        if async_mode:
            self._workers.send_ready_later(
                made, brief_saved, kind=spec.kind, trust=str(cwd), strict=spec.kind in ("claude", "codex"),
                stop_on_exit=True, repo=repo, helper_owner_kind=owner_kind, helper_owner_id=owner_id,
                helper_slug=slug, helper_name=name,
            )
            Delivery(self.ctx, repo).ensure_running()
            return HelperStartResult(
                name=name,
                terminal=made,
                result=str(result_path),
                line=f"helper={name} terminal=hc:{made} result={result_path} ({spec.summary()}) (async)",
                stderr_lines=tuple(stderr_lines),
                is_async=True,
            )

        # Deliver the brief outside the start lock so parallel helpers start concurrently.
        seen: dict[str, Any] = {}
        handed = self._workers.send_when_ready(
            made, brief_text, tries=30, pause=2, strict=spec.kind in ("claude", "codex"),
            trust=cwd, stop_on_exit=True, kind=spec.kind, seen=seen,
        )
        turn_base = seen.get("turn", 0) if handed else None

        def _mark_handed(items: list[dict[str, Any]]) -> bool:
            idx = _match_helper(items, term=made, running_only=True)
            if idx < 0:
                return False
            items[idx]["handed"] = bool(handed)
            items[idx]["turn_base"] = turn_base
            return True

        update_helper_owner_for(self.ctx, owner_kind, owner_id, slug, _mark_handed)
        if not handed:
            scr = self.ctx.hc.screen_line(made, width=300)
            if self.ctx.hc.worker_state(made) in ("exited", "removed"):
                finalize_helper_for(
                    self.ctx, owner_kind, owner_id, slug, repo, term=made, name=name, status="failed",
                    summary=scr, kill_term=False, notify=False,
                    note_text=self.ctx.config.tr(
                        f"helper {name} exited before receiving its brief: {scr}",
                        f"helper {name} 还没收到任务就退出了：{scr}",
                    ),
                )
                raise Refused(self.ctx.config.tr(
                    f"helper {name} (hc:{made}) exited before receiving its brief. Screen: {scr}",
                    f"helper {name}（hc:{made}）在收到任务前就退出了。屏幕：{scr}",
                ))
            raise Refused(self.ctx.config.tr(
                f"brief was not sent: helper {name} in hc:{made} is not ready. Screen: {scr}\n"
                f"Read it (`hc read {made}`), then send by hand (`hc send {made} {file_text(brief_saved)}`) "
                f"or stop it (`pm.py helper stop {name}`).",
                f"任务书没送达：hc:{made} 里的 helper {name} 还没就绪。屏幕：{scr}\n"
                f"查看屏幕（`hc read {made}`），就绪后手动发送（`hc send {made} {file_text(brief_saved)}`），"
                f"或停掉它（`pm.py helper stop {name}`）。",
            ))

        Delivery(self.ctx, repo).ensure_running()
        return HelperStartResult(
            name=name,
            terminal=made,
            result=str(result_path),
            line=f"helper={name} terminal=hc:{made} result={result_path} ({spec.summary()})",
            stderr_lines=tuple(stderr_lines),
        )

    def deliver_ready(
        self,
        term: str,
        text: str,
        *,
        kind: str = "",
        trust: str = "",
        strict: bool = False,
        stop_on_exit: bool = False,
        repo: str = "",
        owner_kind: str = "",
        owner_id: str = "",
        slug: str = "",
        name: str = "",
    ) -> None:
        """Background brief delivery for `helper start --async` (`_deliver-ready`)."""
        seen: dict[str, Any] = {}
        handed = self._workers.send_when_ready(
            term, text, tries=30, pause=2, strict=strict,
            trust=trust or None, stop_on_exit=stop_on_exit, kind=kind, seen=seen,
        )
        turn_base = seen.get("turn", 0) if handed else None

        is_quiet = [False]

        def _mark_handed(items: list[dict[str, Any]]) -> bool:
            idx = _match_helper(items, term=term, running_only=False)
            if idx < 0:
                return False
            is_quiet[0] = bool(items[idx].get("quiet"))
            if items[idx].get("status") != "running":
                return False
            items[idx]["handed"] = bool(handed)
            items[idx]["turn_base"] = turn_base
            return True

        update_helper_owner_for(self.ctx, owner_kind, owner_id, slug, _mark_handed)
        if not handed:
            diag = classify_stuck_screen(self.ctx.hc.read(term))
            summary = diag["summary"] or self.ctx.hc.screen_line(term, width=200)
            if self.ctx.hc.worker_state(term) in ("exited", "removed"):
                finalize_helper_for(
                    self.ctx, owner_kind, owner_id, slug, repo,
                    term=term, name=name, status="failed", summary=summary,
                    kill_term=False, notify=True,
                    note_text=self.ctx.config.tr(
                        f"helper {name} exited before receiving its brief ({diag['kind']}): {summary}",
                        f"helper {name} 在收到任务前退出（{diag['kind']}）：{summary}",
                    ),
                )
            elif owner_kind == "pm" and repo:
                msg = self.ctx.config.tr(
                    f"helper {name} (hc:{term}) was not ready ({diag['kind']}): {summary}; "
                    f"stop with `pm.py helper stop {name}`",
                    f"helper {name}（hc:{term}）未就绪（{diag['kind']}）：{summary}；"
                    f"可用 `pm.py helper stop {name}` 停掉",
                )
                Conversation(self.ctx, repo).record(
                    "helper", by=f"hc:{term}", source="helper", helper=name,
                    status="blocked", text=msg, wake=not is_quiet[0],
                )
                if not is_quiet[0]:
                    Delivery(self.ctx, repo).ensure_running()
        elif repo:
            Delivery(self.ctx, repo).ensure_running()

    def done(
        self,
        *,
        name: str | None = None,
        text: str | None = None,
        stdin_text: str | None = None,
        from_stdin: bool = False,
        summary: str | None = None,
        task: str | None = None,
        pm: bool = False,
        repo: str = ".",
    ) -> HelperDoneResult:
        """Mark a helper finished and deliver/notify its owner."""
        self_info = self._caller.helper_self_info()
        found = self.find_by_self(self_info) if self_info else None
        is_self = False
        is_owner = False
        if self_info:
            if pm or task:
                raise Refused(self.ctx.config.tr(
                    "refused: a helper can only mark itself done (do not pass --pm or --task)",
                    "已拒绝：helper 只能标记自己完成（不要传 --pm 或 --task）",
                ))
            if not found:
                raise NotFound(self.ctx.config.tr(
                    "helper record not found for this terminal",
                    "找不到当前终端对应的 helper 台账记录",
                ))
            if name and found[4].get("name") != name:
                raise Refused(self.ctx.config.tr(
                    f"refused: this terminal is helper {found[4].get('name')}, not {name}",
                    f"已拒绝：当前终端是 helper {found[4].get('name')}，不是 {name}",
                ))
            owner_kind, owner_id, slug, resolved_repo, entry = found
            is_self = True
        else:
            caller_role, caller_obj = self._caller.helper_caller_identity()
            owner_kind, owner_id, _dir, resolved_repo, slug = self.resolve_owner(
                task=task, pm=pm, repo=repo, require_owner=True, allow_closed_task=True,
            )
            assert owner_kind and owner_id and slug
            resolved_repo = resolved_repo or ""
            self.authorize_target("finalize", caller_role, caller_obj, owner_kind, owner_id)
            is_owner = ((caller_role == "pm" and owner_kind == "pm")
                        or (caller_role == "task" and owner_kind == "task" and caller_obj["id"] == owner_id))
            rec = self.ctx.store.registration(slug) if owner_kind == "pm" else self.ctx.store.task(owner_id)
            items = helper_entries(rec)
            target_name = name or ""
            idx = _match_helper(items, name=target_name, running_only=True)
            if idx < 0 and target_name:
                idx = _match_helper(items, name=target_name, running_only=False)
            if idx < 0:
                raise NotFound(self.ctx.config.tr(
                    f"no helper {target_name or '(unnamed)'} found for {owner_id}",
                    f"在 {owner_id} 下找不到 helper {target_name or '（未指定名字）'}",
                ))
            entry = items[idx]

        result_path = Path(entry.get("result") or "")
        if not entry.get("result"):
            raise Refused(self.ctx.config.tr(
                f"helper {entry.get('name')} has no result path recorded",
                f"helper {entry.get('name')} 没有登记结果文件路径",
            ))

        if from_stdin and text is not None:
            raise Refused(self.ctx.config.tr("pass --text or --stdin, not both", "--text 和 --stdin 不能同时传"))
        if from_stdin:
            content = stdin_text or ""
            if not content.strip():
                raise Refused(self.ctx.config.tr(
                    "stdin is empty; write your conclusion to the result file or pass non-empty text",
                    "标准输入为空；请把结论写进结果文件或传入非空内容",
                ))
            write_atomic(result_path, (content.rstrip("\n") + "\n").encode("utf-8"), replace_fn=replace_task_file)
        elif text is not None:
            if not str(text).strip():
                raise Refused(self.ctx.config.tr(
                    "--text is empty; provide a non-empty conclusion",
                    "--text 为空；请提供非空结论",
                ))
            write_atomic(result_path, (str(text).rstrip("\n") + "\n").encode("utf-8"), replace_fn=replace_task_file)

        conclusion = helper_result_text(result_path)
        fallback = ""
        if not conclusion:
            if is_self:
                cmd = self.ctx.procs.pm_command()
                raise Refused(self.ctx.config.tr(
                    f"result file {result_path} is missing or empty; write your conclusion there first "
                    f"(or pass `--text \"...\"` / `--stdin`) and run `{cmd} helper done` again",
                    f"结果文件 {result_path} 不存在或为空；请先把结论写进该文件（或传 `--text \"...\"` / `--stdin`），"
                    f"再运行 `{cmd} helper done`",
                ))
            captured = capture_helper_screen_for(
                self.ctx, entry.get("terminal") or "", result_path, reason="unreported",
            )
            if not captured:
                raise Refused(self.ctx.config.tr(
                    f"result file {result_path} is missing or empty and no screen output could be captured",
                    f"结果文件 {result_path} 不存在或为空，且无法从屏幕截取内容",
                ))
            conclusion = captured
            fallback = "screen"

        summary_val = (summary or "").strip() or helper_excerpt(conclusion)
        updated, transitioned = finalize_helper_for(
            self.ctx, owner_kind, owner_id, slug, resolved_repo,
            term=entry.get("terminal") or "", name=entry.get("name") or "",
            status="done", summary=summary_val, fallback=fallback, kill_term=not is_self,
            cleanup_term=is_self, notify=not is_owner,
        )
        if is_self and resolved_repo:
            Delivery(self.ctx, resolved_repo).ensure_running()
        final_name = (updated or entry).get("name") or "?"
        if transitioned:
            line = self.ctx.config.tr(
                f"helper {final_name} done -> {result_path}",
                f"helper {final_name} 已完成 -> {result_path}",
            )
        else:
            line = self.ctx.config.tr(
                f"helper {final_name} already done ({result_path})",
                f"helper {final_name} 此前已完成（{result_path}）",
            )
        return HelperDoneResult(name=final_name, result=str(result_path), transitioned=transitioned, line=line)

    def wait(
        self,
        names: Sequence[str] = (),
        *,
        wait_any: bool = False,
        timeout: int | float | None = None,
        keep: bool = False,
        as_json: bool = False,
        task: str | None = None,
        pm: bool = False,
        repo: str = ".",
    ) -> HelperWaitResult:
        """Wait for one or more helpers (event-driven via ChangeWaiter on owner ledger + hc events)."""
        caller_role, caller_obj = self._caller.helper_caller_identity()
        owner_kind, owner_id, _dir, resolved_repo, slug = self.resolve_owner(
            task=task, pm=pm, repo=repo, require_owner=True, allow_closed_task=True,
        )
        assert owner_kind and owner_id and slug
        resolved_repo = resolved_repo or ""
        if caller_role != "cli":
            self.authorize_target("wait", caller_role, caller_obj, owner_kind, owner_id)
        reconcile_owner_helpers_for(self.ctx, owner_kind, owner_id, slug, resolved_repo, notify=False)

        def read_helpers() -> list[dict[str, Any]]:
            rec = self.ctx.store.registration(slug) if owner_kind == "pm" else self.ctx.store.task(owner_id)
            return helper_entries(rec)

        items = read_helpers()
        name_list = list(names)
        if name_list:
            targets: list[tuple[str, str]] = []
            for n in name_list:
                idx = _match_helper(items, name=n, running_only=True)
                if idx < 0:
                    idx = _match_helper(items, name=n, running_only=False)
                if idx < 0:
                    raise NotFound(self.ctx.config.tr(
                        f"no helper named {n} for {owner_id}",
                        f"{owner_id} 下没有叫 {n} 的 helper",
                    ))
                targets.append((items[idx].get("terminal") or "", items[idx].get("name") or n))
        else:
            running = [h for h in items if h.get("status") == "running"]
            if not running:
                empty_line = "[]" if as_json else self.ctx.config.tr("no running helpers", "没有运行中的 helper")
                return HelperWaitResult(items=[], lines=(empty_line,), exit_code=0)
            targets = [(h.get("terminal") or "", h.get("name") or "") for h in running]

        # Overall wait timeout: explicit --timeout, else max remaining helper timeout + small margin.
        if timeout is not None:
            wait_timeout = float(timeout)
        else:
            matching = [
                items[_match_helper(items, term=t, name=n)] for t, n in targets
                if _match_helper(items, term=t, name=n) >= 0
            ]
            wait_timeout = max(
                [helper_remaining(h, clock=self.ctx.clock) for h in matching]
                or [float(helpers_timeout_for(self.ctx))]
            ) + 5.0
        deadline = self.ctx.clock.monotonic() + max(0.0, wait_timeout)

        watch_dirs, watch_files = _helper_owner_ledger_paths_for(self.ctx, owner_kind, owner_id, slug)
        target_terms = {t for t, _ in targets if t}
        stops: dict[str, tuple[tuple[str, str, int], float]] = {}
        alerts: dict[str, str] = {}

        with helper_wait_guard_for(self.ctx, owner_id):
            with self.ctx.hc.change_waiter(
                watch_dirs, [] if target_terms else None, files=watch_files, terminals=set(target_terms),
            ) as changes:
                while True:
                    stall_grace = stalls_mod.STALL_GRACE
                    round_start = stalls_mod.ROUND_START
                    items = read_helpers()
                    resolved: list[dict[str, Any]] = []
                    still_working: list[dict[str, Any]] = []
                    blocked_entries: list[dict[str, Any]] = []
                    now_m = self.ctx.clock.monotonic()
                    due = max(0.0, deadline - now_m)

                    for t_term, t_name in targets:
                        idx = _match_helper(items, term=t_term, name=t_name)
                        if idx < 0:
                            continue
                        h = dict(items[idx])
                        term = h.get("terminal") or t_term
                        if h.get("status") != "running":
                            if not keep and term:
                                kill_helper_terminal_for(self.ctx, term)
                                if h.get("cleanup_term"):
                                    _clear_helper_cleanup_for(self.ctx, owner_kind, owner_id, slug, term)
                            resolved.append(h)
                            continue
                        # Still marked running: check timeout first.
                        rem = helper_remaining(h, clock=self.ctx.clock)
                        if rem <= 0:
                            entry, _ = _harvest_entry_for(
                                self.ctx, owner_kind, owner_id, slug, resolved_repo, h,
                                reason="timeout", kill_term=not keep, notify=False,
                            )
                            resolved.append(entry or {**h, "status": "timeout"})
                            continue
                        due = min(due, rem)
                        if not term:
                            still_working.append(h)
                            continue
                        info = self.ctx.hc.get_raw(term, errors=True) or {}
                        if info.get("error") and (info.get("error") or {}).get("kind") != "not_found":
                            still_working.append(h)
                            continue
                        gone = ((info.get("error") or {}).get("kind") == "not_found"
                                or info.get("state") != "live"
                                or (info.get("reported") and not info.get("status")))
                        if gone:
                            entry, _ = _harvest_entry_for(
                                self.ctx, owner_kind, owner_id, slug, resolved_repo, h,
                                reason="gone", kill_term=False, notify=False,
                            )
                            resolved.append(entry or {**h, "status": "exited"})
                            continue
                        state = (info.get("status") or {}).get("state")
                        turn = info.get("turn") or 0
                        if state in ("blocked", "error"):
                            key = (term, state, turn)
                            since = stops.get(term)
                            if not since or since[0] != key:
                                stops[term] = (key, now_m)
                                due = min(due, stall_grace)
                                still_working.append(h)
                            elif now_m - since[1] < stall_grace:
                                due = min(due, stall_grace - (now_m - since[1]))
                                still_working.append(h)
                            else:
                                scr = self.ctx.hc.screen_line(term, width=240)
                                alerts[term] = self.ctx.config.tr(
                                    f"helper {h['name']} (hc:{term}) is {state}: {scr}. "
                                    f"Read `hc read {term} | tail -40` or stop `pm.py helper stop {h['name']}`.",
                                    f"helper {h['name']}（hc:{term}）处于 {state}：{scr}。"
                                    f"查看 `hc read {term} | tail -40` 或停止 `pm.py helper stop {h['name']}`。",
                                )
                                blocked_entries.append({**h, "status": state, "alert": alerts[term]})
                            continue
                        handed = h.get("handed")
                        turn_base = h.get("turn_base")
                        ready_to_judge = (
                            (handed is True and turn_base is not None)
                            or helper_elapsed(h, clock=self.ctx.clock) >= round_start
                        )
                        hooked = (h.get("kind") or terminal_kind(info)) in HOOKED_KINDS
                        if state in ("idle", "done") and ready_to_judge and not hooked and turn > (turn_base or 0):
                            if self.ctx.procs.background_work(info):
                                stops.pop(term, None)
                                due = min(due, stall_grace)
                                still_working.append(h)
                                continue
                            key = (term, "idle", turn)
                            since = stops.get(term)
                            if not since or since[0] != key:
                                stops[term] = (key, now_m)
                                due = min(due, stall_grace)
                                still_working.append(h)
                            elif now_m - since[1] < stall_grace:
                                due = min(due, stall_grace - (now_m - since[1]))
                                still_working.append(h)
                            else:
                                # Re-read before harvesting: helper may have just completed `helper done`.
                                fresh_items = read_helpers()
                                fidx = _match_helper(fresh_items, term=term, name=t_name)
                                fresh = fresh_items[fidx] if fidx >= 0 else h
                                if fresh.get("status") != "running":
                                    if not keep and term:
                                        kill_helper_terminal_for(self.ctx, term)
                                    resolved.append(dict(fresh))
                                else:
                                    entry, _ = _harvest_entry_for(
                                        self.ctx, owner_kind, owner_id, slug, resolved_repo, fresh,
                                        reason="unreported", kill_term=not keep, notify=False,
                                    )
                                    resolved.append(entry or {**fresh, "status": "done"})
                            continue
                        stops.pop(term, None)
                        still_working.append(h)

                    ready_now = resolved + blocked_entries
                    if (wait_any and ready_now) or (not wait_any and not still_working):
                        formatted = _format_helper_wait_results(ready_now)
                        lines = tuple(format_helper_wait_lines(self.ctx, formatted, as_json=as_json))
                        bad = any(x["status"] != "done" for x in formatted)
                        return HelperWaitResult(items=formatted, lines=lines, exit_code=3 if bad else 0)
                    if self.ctx.clock.monotonic() >= deadline:
                        formatted = _format_helper_wait_results(ready_now + still_working)
                        lines = tuple(format_helper_wait_lines(self.ctx, formatted, as_json=as_json))
                        stderr_line = ""
                        if not as_json:
                            names_left = ", ".join(h.get("name") or "?" for h in still_working)
                            stderr_line = self.ctx.config.tr(
                                f"wait timeout: still running: {names_left}",
                                f"等待超时：仍在运行：{names_left}",
                            )
                        return HelperWaitResult(
                            items=formatted, lines=lines, exit_code=2, stderr_line=stderr_line,
                        )
                    if hasattr(changes, "terminals"):
                        changes.terminals = {h.get("terminal") for h in still_working if h.get("terminal")}
                    changes.wait(max(0.05, due))

    def ls(
        self,
        *,
        show_all: bool = False,
        active_only: bool = False,
        task: str | None = None,
        pm: bool = False,
        repo: str = ".",
    ) -> HelperLsResult:
        """List helpers for the caller or the whole project, reconciling timeouts/exited terminals first."""
        owner_kind, owner_id, _dir, resolved_repo, slug = self.resolve_owner(
            task=task, pm=pm, repo=repo,
            require_owner=bool(task or pm), allow_closed_task=True,
        )
        if not resolved_repo:
            raise Refused(self.ctx.config.tr(f"{repo} is not a directory", f"{repo} 不是目录"))
        slug = slug or project_slug(resolved_repo)
        if show_all or not owner_kind:
            reconcile_project_helpers_for(self.ctx, resolved_repo)
        else:
            assert owner_id
            reconcile_owner_helpers_for(self.ctx, owner_kind, owner_id, slug, resolved_repo)

        entries: list[dict[str, Any]] = []
        if show_all or not owner_kind:
            reg = self.ctx.store.registration(slug)
            entries += [dict(h) for h in helper_entries(reg)]
            for t in self._ledger.project_tasks(resolved_repo):
                entries += [dict(h) for h in helper_entries(t)]
        else:
            assert owner_id
            rec = self.ctx.store.registration(slug) if owner_kind == "pm" else self.ctx.store.task(owner_id)
            entries = [dict(h) for h in helper_entries(rec)]

        if active_only:
            entries = [h for h in entries if h.get("status") == "running"]

        live_rows = self.ctx.hc.live_rows() if any(h.get("status") == "running" for h in entries) else {}
        for h in entries:
            term = h.get("terminal") or ""
            if h.get("status") == "running" and term and live_rows is not None:
                row = live_rows.get(term)
                if row is not None:
                    if hasattr(row, "agent_state"):
                        row_status = row.agent_state
                    else:
                        raw_st = row.get("status") if isinstance(row, dict) else None
                        row_status = raw_st.get("state") if isinstance(raw_st, dict) else (raw_st if isinstance(raw_st, str) else "")
                    h["live_state"] = row_status or "live"
                else:
                    h["live_state"] = "offline"

        active_threads, running_proj = project_active_counts_for(self.ctx, resolved_repo)
        max_owner = helpers_max_for(self.ctx)
        max_proj = helpers_project_max_for(self.ctx)
        lines: list[str] = []
        if owner_kind and not show_all:
            running_mine = sum(1 for h in entries if h.get("status") == "running")
            lines.append(self.ctx.config.tr(
                f"Helpers of {owner_id} ({running_mine}/{max_owner} running; "
                f"project {slug}: {active_threads} thread(s) + {len(running_proj)} helper(s) / {max_proj}):",
                f"{owner_id} 的 helper（{running_mine}/{max_owner} 运行中；"
                f"项目 {slug}：{active_threads} 个线程 + {len(running_proj)} 个 helper / {max_proj}）：",
            ))
        else:
            lines.append(self.ctx.config.tr(
                f"Helpers of project {slug} ({len(running_proj)} running; "
                f"{active_threads} thread(s) + {len(running_proj)} helper(s) / {max_proj}):",
                f"项目 {slug} 的 helper（{len(running_proj)} 个运行中；"
                f"{active_threads} 个线程 + {len(running_proj)} 个 helper / {max_proj}）：",
            ))
        if not entries:
            lines.append("  (none)")
        else:
            for h in entries:
                st = h.get("status") or "?"
                if st == "running" and h.get("live_state"):
                    st = f"running ({h['live_state']})"
                eng = " ".join(x for x in (h.get("profile"), h.get("kind"), h.get("model")) if x)
                when = (
                    f"{int(helper_elapsed(h, clock=self.ctx.clock))}s/{h.get('timeout') or HELPER_TIMEOUT}s"
                    if h.get("status") == "running" else (h.get("ended") or "")
                )
                lines.append(
                    f"  [{st}] {h.get('name')}  of={h.get('owner') or '?'}  hc:{h.get('terminal') or '-'}  {eng}  {when}"
                )
                if h.get("result"):
                    lines.append(f"      result: {h['result']}")
                if h.get("summary"):
                    lines.append(f"      summary: {h['summary']}")
        return HelperLsResult(entries=entries, lines=tuple(lines))

    def stop(
        self,
        names: Sequence[str] = (),
        *,
        stop_all: bool = False,
        remove: bool = False,
        task: str | None = None,
        pm: bool = False,
        repo: str = ".",
    ) -> HelperStopResult:
        """Stop one, several, or all running helpers."""
        name_list = list(names)
        if not name_list and not stop_all:
            raise Refused(self.ctx.config.tr(
                "specify helper name(s)/terminal(s) to stop, or pass --all",
                "请指定要停止的 helper 名字或终端，或传入 --all",
            ))

        caller_role, caller_obj = self._caller.helper_caller_identity()
        caller_kind, caller_id, _dir, resolved_repo, slug = self.resolve_owner(
            task=task, pm=pm, repo=repo, require_owner=False, allow_closed_task=True,
        )
        if not resolved_repo:
            raise Refused(self.ctx.config.tr("cannot resolve project directory", "无法确定项目目录"))
        slug = slug or project_slug(resolved_repo)

        # Enforce ownership: workers can only stop their own task's helpers (never PM's or another task's).
        owners: list[tuple[str, str, str, str]] = []
        if task or pm:
            self.authorize_target("stop", caller_role, caller_obj, caller_kind, caller_id)
            assert caller_kind and caller_id
            owners.append((caller_kind, caller_id, resolved_repo, slug))
        elif caller_role == "helper":
            self.authorize_target("stop", caller_role, caller_obj, caller_kind, caller_id)
        elif caller_role == "pm":
            owners.append(("pm", f"pm-{slug}", resolved_repo, slug))
            if name_list:
                for t in self._ledger.project_tasks(resolved_repo):
                    owners.append(("task", t["id"], t.get("repo") or resolved_repo, slug))
        elif caller_role == "task":
            owners.append(("task", caller_obj["id"], caller_obj.get("repo") or resolved_repo, slug))
        elif caller_role == "worker_unknown":
            raise Refused(self.ctx.config.tr(
                "cannot identify caller's task; pass --task <your-task-id>",
                "无法识别当前 worker 的任务；请传入 --task <你的任务 id>",
            ))
        else:
            # Outside hc/TUI (operator CLI): search project's PM and tasks.
            if self.ctx.store.registration(slug):
                owners.append(("pm", f"pm-{slug}", resolved_repo, slug))
            for t in self._ledger.project_tasks(resolved_repo):
                owners.append(("task", t["id"], t.get("repo") or resolved_repo, slug))

        stopped: list[dict[str, Any]] = []
        if stop_all:
            for okind, oid, orepo, oslug in owners:
                rec = self.ctx.store.registration(oslug) if okind == "pm" else self.ctx.store.task(oid)
                for h in helper_entries(rec):
                    if h.get("status") != "running":
                        continue
                    entry, did = finalize_helper_for(
                        self.ctx, okind, oid, oslug, orepo, term=h.get("terminal") or "",
                        name=h.get("name") or "", status="stopped", kill_term=True,
                        remove_term=remove, notify=False,
                    )
                    if entry and did:
                        stopped.append(entry)
        else:
            for raw_target in name_list:
                t_term = raw_target[3:] if raw_target.startswith("hc:") else ""
                hit = False
                for okind, oid, orepo, oslug in owners:
                    rec = self.ctx.store.registration(oslug) if okind == "pm" else self.ctx.store.task(oid)
                    items = helper_entries(rec)
                    idx = _match_helper(items, term=t_term or raw_target, running_only=True)
                    if idx < 0:
                        idx = _match_helper(items, name=raw_target, running_only=True)
                    if idx >= 0:
                        h = items[idx]
                        entry, did = finalize_helper_for(
                            self.ctx, okind, oid, oslug, orepo, term=h.get("terminal") or "",
                            name=h.get("name") or "", status="stopped", kill_term=True,
                            remove_term=remove, notify=False,
                        )
                        if entry and did:
                            stopped.append(entry)
                        hit = True
                        break
                if not hit:
                    raise NotFound(self.ctx.config.tr(
                        f"no running helper matching {raw_target!r}",
                        f"找不到运行中的 helper {raw_target!r}",
                    ))

        if not stopped:
            return HelperStopResult(
                stopped=[],
                lines=(self.ctx.config.tr("no running helpers to stop", "没有运行中的 helper 需要停止"),),
            )
        lines = tuple(
            self.ctx.config.tr(
                f"stopped helper {h['name']} (hc:{h.get('terminal') or '?'})",
                f"已停止 helper {h['name']}（hc:{h.get('terminal') or '?'}）",
            )
            for h in stopped
        )
        return HelperStopResult(stopped=stopped, lines=lines)


# ── Legacy module-level wrappers (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────


def helper_brief(
    name: str,
    owner_id: str,
    prompt_text: str,
    result_path: str | Path,
    cwd: str | Path,
    *,
    exec_mode: bool = False,
    repo: str = "",
) -> str:
    return Helpers(Context.from_env()).brief(
        name, owner_id, prompt_text, result_path, cwd, exec_mode=exec_mode, repo=repo,
    )


def _find_helper_record_by_self(info: dict[str, str]) -> tuple[str, str, str, str, dict[str, Any]] | None:
    return Helpers(Context.from_env()).find_by_self(info)


def _authorize_helper_target(
    action: str,
    caller_role: str,
    caller_obj: Any,
    target_kind: str | None,
    target_id: str | None,
) -> None:
    Helpers(Context.from_env()).authorize_target(action, caller_role, caller_obj, target_kind, target_id)


def _resolve_helper_owner(
    a: Any,
    *,
    require_owner: bool = True,
    allow_closed_task: bool = False,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    return Helpers(Context.from_env()).resolve_owner(
        task=getattr(a, "task", None),
        pm=bool(getattr(a, "pm", False)),
        repo=getattr(a, "repo", None) or ".",
        require_owner=require_owner,
        allow_closed_task=allow_closed_task,
    )
