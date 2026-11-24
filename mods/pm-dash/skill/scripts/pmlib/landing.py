"""`Landing(ctx)` service: approve a merge and hand it to the worker or an exec helper (`approve`), hand a stuck worker
to a triage helper (`triage`), and merge a task's branch in the main checkout once the project's checks pass
(`land`). Zero globals, zero `sys.exit`, zero `print`: what it has to say is returned as `(stream, text)` pairs, and
it raises `PmError` with `land`'s exit codes (2 refused on stderr; 1, 4, 5 and 128+n on stdout). Layer 3, above
`reactions`: the PM's own merge is an ordinary `update --status merged` with its reactions. Exec helpers start
through `Helpers(ctx).start`.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
import signal
from typing import Any, Callable

from .caller import Caller
from .context import Context
from .errors import PmError, Refused
from .events.deps_watch import DependencyWatcher
from .events.stalls import StallWatcher
from .helpers.config import helpers_timeout_for
from .helpers.records import helper_entries
from .helpers.service import HelperStartRequest, Helpers
from .home import project_slug
from .ledger.ledger import Change, Ledger
from .ledger.plan import plan_progress, post_merge_steps, sync_plan_on_approve, sync_plan_on_merge
from .ledger.question import QUESTION_FIELDS
from .ledger.task import CLOSED, Task, hc_terminal_of
from .ledger.transition import UpdateRequest
from .osutil import Options, shell_quote, slugify, stop_group
from .project.project import ProjectRegistry
from .reactions import Updates, _rollup_ancestors
from .review.land import (
    LAND_CONFLICTS,
    LAND_REFUSED,
    LAND_STUCK,
    LandStopped,
    branch_matches_approved_commit_for,
    run_checks,
    verify_commands_for,
)
from .store import LockTimeoutError, file_lock, lock_file, unlock_file
from .workers.lifecycle import close_later_for
from .workers.service import Workers

Said = list  # [(stream, text)], stream "out" or "err"


class ApproveRequest(Options):
    """`pm.py approve` (and `land --delegate`)."""

    required = ('id',)

    id: str = ""
    commit: str | None = None
    message: str | None = None
    keep: bool = False
    timeout: int | None = None
    via: str = "auto"
    note: str | None = None
    profile: str | None = None
    kind: str | None = None
    model: str | None = None
    effort: str | None = None
    advisor: str | None = None
    codex_profile: str | None = None
    confirmed: bool = False
    revoke: bool = False

    @classmethod
    def from_args(cls, a: Any) -> ApproveRequest:
        return cls(
            id=a.id, commit=getattr(a, "commit", None), message=getattr(a, "message", None),
            keep=bool(getattr(a, "keep", False)), timeout=getattr(a, "timeout", None),
            via=getattr(a, "via", "auto") or "auto", note=getattr(a, "note", None),
            profile=getattr(a, "profile", None), kind=getattr(a, "kind", None), model=getattr(a, "model", None),
            effort=getattr(a, "effort", None), advisor=getattr(a, "advisor", None),
            codex_profile=getattr(a, "codex_profile", None), confirmed=bool(getattr(a, "confirmed", False)),
            revoke=bool(getattr(a, "revoke", False)),
        )


class TriageRequest(Options):
    """`pm.py triage`."""

    required = ('id',)

    id: str = ""
    note: str | None = None
    profile: str | None = None
    kind: str | None = None
    model: str | None = None
    effort: str | None = None
    advisor: str | None = None
    codex_profile: str | None = None
    confirmed: bool = False

    @classmethod
    def from_args(cls, a: Any) -> TriageRequest:
        return cls(
            id=a.id, note=getattr(a, "note", None), profile=getattr(a, "profile", None),
            kind=getattr(a, "kind", None), model=getattr(a, "model", None), effort=getattr(a, "effort", None),
            advisor=getattr(a, "advisor", None), codex_profile=getattr(a, "codex_profile", None),
            confirmed=bool(getattr(a, "confirmed", False)),
        )


class LandRequest(Options):
    """`pm.py land` (without --delegate)."""

    required = ('id',)

    id: str = ""
    keep: bool = False
    message: str | None = None
    timeout: int | None = None

    @classmethod
    def from_args(cls, a: Any) -> LandRequest:
        return cls(id=a.id, keep=bool(getattr(a, "keep", False)), message=getattr(a, "message", None),
                   timeout=getattr(a, "timeout", None))


@dataclass(repr=False, eq=False)
class Landed:
    """What a Landing call said, `(stream, text)` in order, and the task id it resolved to."""

    task_id: str = ""
    said: list[tuple[str, str]] = field(default_factory=list)


class Landing:
    """Layer 3 service owning merge approval, triage delegation and `land`."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._ledger = Ledger(ctx)
        self._projects = ProjectRegistry(ctx)

    @property
    def _caller(self) -> Caller:
        return self.ctx.caller if self.ctx.caller is not None else Caller(self.ctx)

    def _tr(self, en: str, zh: str) -> str:
        return self.ctx.config.tr(en, zh)

    def _refuse(self, text: str) -> Refused:
        return Refused(text, code=LAND_REFUSED)

    def _change(self, task_id: str, fn: Callable[[dict[str, Any], Change], Any], *, board: bool = True) -> dict[str, Any]:
        def _apply(cur: Task | None, ch: Change) -> dict[str, Any]:
            assert cur is not None
            fn(cur.raw, ch)
            return cur.raw

        res = self._ledger.change(task_id, _apply, board=board)
        assert res is not None
        return res.raw

    def _helper_name(self, base: str, repo: str) -> str:
        """A helper name not used by a running helper of the project (suffixed -2, -3, ... when it is)."""
        hname = slugify(base)[:28]
        reg = self.ctx.store.registration(project_slug(repo))
        running_names = {h.get("name") for h in helper_entries(reg) if h.get("status") == "running"}
        if hname in running_names:
            for i in range(2, 50):
                cand = f"{hname[:24].rstrip('-')}-{i}"
                if cand not in running_names:
                    hname = cand
                    break
        return hname

    def _start(self, fields: dict[str, Any], done: Landed) -> str:
        """Start the exec helper; its stderr notices join what is said. A refusal leaves as `helper start` did:
        on stderr always with exit 1 and the message, on stdout with its own code."""
        try:
            res = Helpers(self.ctx).start(HelperStartRequest(**fields))
        except PmError as err:
            if err.stream == "stdout":
                raise
            raise Refused(str(err)) from err
        done.said.extend(("err", line) for line in res.stderr_lines)
        return res.terminal or ""

    # --- who may land ---

    def verify_caller(self, task: dict[str, Any]) -> str:
        """Enforce merge authorization and return the caller's role ("helper", "worker", "pm" or "cli"):
        - PM or plain CLI (no pane): allowed directly.
        - Worker terminal: ONLY its own task (not a review thread), with an active PM `land_approved` record whose
          branch matches and whose HEAD equals the approved commit (or has ONLY pure `merge <base>` conflict-
          resolution commits after it).
        - Helper terminal: ONLY the PM-authorized exec helper recorded in `land_approved`, with the same commit check.
        Raises `Refused` (exit 2) otherwise."""
        tr, caller = self._tr, self._caller
        helper_info = caller.helper_self_info()
        if helper_info:
            approved = task.get("land_approved")
            if not isinstance(approved, dict) or not approved.get("by") or approved.get("executor") != "helper":
                raise self._refuse(tr(
                    f"refused: helper cannot land {task['id']} without PM merge approval (`pm.py approve {task['id']} --via helper`)",
                    f"已拒绝：helper 未获 PM 合并授权，不能 land {task['id']}（需 `pm.py approve {task['id']} --via helper`）"))
            term_match = bool(self.ctx.hc_terminal and approved.get("executor_pane") == f"hc:{self.ctx.hc_terminal}")
            name_match = bool(approved.get("helper_name") and helper_info.get("name") == approved.get("helper_name")
                              and (not helper_info.get("project") or helper_info.get("project") == project_slug(task["repo"])))
            if not (term_match or name_match):
                raise self._refuse(tr(f"refused: this helper is not authorized to land {task['id']}",
                                      f"已拒绝：当前 helper 未被授权合并 {task['id']}"))
            self._check_approved_commit(task, approved)
            return "helper"
        if self.ctx.pane and not caller.is_pm_caller(task):
            if task.get("review_of"):
                raise self._refuse(tr(f"refused: review thread {task['id']} cannot be landed",
                                      f"已拒绝：审查线程 {task['id']} 不能执行 land"))
            own = caller.own_task
            if own and own["id"] != task["id"]:
                raise self._refuse(tr(f"refused: worker of {own['id']} can only land its own task, not {task['id']}",
                                      f"已拒绝：{own['id']} 的 worker 只能合并自己的任务，不能 land {task['id']}"))
            if not ((own and own["id"] == task["id"]) or task.get("pane") == self.ctx.pane):
                raise self._refuse(tr(f"refused: only the worker of {task['id']} or the PM may land it",
                                      f"已拒绝：只有 {task['id']} 自己的 worker 或 PM 可以执行 land"))
            approved = task.get("land_approved")
            if not isinstance(approved, dict) or not approved.get("by"):
                raise self._refuse(tr(
                    f"refused: {task['id']} has not been approved for merge by the PM; "
                    f"report with `pm.py update {task['id']} --status review --commit <sha>` and wait for PM approval",
                    f"已拒绝：{task['id']} 尚未获 PM 批准合并；请先用 `pm.py update {task['id']} --status review --commit <sha>` 汇报并等 PM 裁决"))
            self._check_approved_commit(task, approved)
            return "worker"
        return "pm" if self.ctx.pane else "cli"

    def _check_approved_commit(self, task: dict[str, Any], approved: dict[str, Any]) -> None:
        tr = self._tr
        if approved.get("branch") and approved["branch"] != task.get("branch"):
            raise self._refuse(tr(f"refused: approved branch {approved['branch']} does not match {task.get('branch')}",
                                  f"已拒绝：授权分支 {approved['branch']} 与当前分支 {task.get('branch')} 不一致"))
        approved_commit = approved.get("commit") or ""
        if not approved_commit or not branch_matches_approved_commit_for(
                self.ctx, task["repo"], task.get("branch"), approved.get("base") or task.get("base"), approved_commit):
            raise self._refuse(tr(
                f"refused: branch {task.get('branch')} differs from the PM-approved commit {approved_commit[:12] or '(none)'} "
                "(only merge-base conflict commits are allowed); report for re-review and re-approval",
                f"已拒绝：分支 {task.get('branch')} 相对 PM 授权的提交 {approved_commit[:12] or '（无）'} 存在非 merge-base 的新改动；"
                "请重新报 review 并由 PM 重新 approve"))

    def handoff_prompt(self, task: dict[str, Any], approved: dict[str, Any], *, for_helper: bool = False) -> str:
        """The execution prompt sent to the worker or exec helper once the PM approves a merge."""
        tid = task["id"]
        repo, branch, base = task["repo"], task.get("branch") or "", approved.get("base") or task.get("base") or "main"
        worktree = task.get("worktree") or ""
        cmd = self.ctx.procs.pm_command()
        land_parts = [cmd, "land", tid]
        if approved.get("message"):
            land_parts += ["--message", shell_quote(approved["message"])]
        if approved.get("keep"):
            land_parts.append("--keep")
        if approved.get("timeout") and approved["timeout"] != 600:
            land_parts += ["--timeout", str(approved["timeout"])]
        land_cmd = " ".join(land_parts)
        remaining = post_merge_steps(task)
        extra_note = (approved.get("note") or "").strip()
        lines = []
        if self._tr("en", "zh") == "zh":
            lines.append(f"PM 已裁决合并任务 {tid}（{branch} -> {base}）。请按以下步骤执行：")
            if extra_note:
                lines.append(f"- PM 补充说明：{extra_note}")
            lines.append(f"1. 运行合并与检查：`{land_cmd}`")
            lines.append(f"2. 若遇到合并冲突（退出码 4）：在工作树（{worktree or repo}）里运行 `git merge {base}`，"
                         f"解决冲突、跑相关检查并提交，再重新运行 `{land_cmd}`。")
            lines.append(f"3. 若检查失败（退出码 1）：查看报错；如属小问题直接修复提交并报 review，或需拍板时用 "
                         f"`{cmd} update {tid} --status blocked --note \"<原因>\"` 汇报。")
            if remaining:
                step_list = "；".join(s.get("text") or "" for s in remaining)
                lines.append(f"4. 合并成功后，在主检出 `{repo}` 中继续执行剩余外层计划步骤：{step_list}")
                lines.append(f"   - 具体做法按外层步骤原文、项目 profile（`{repo}/.claude/coordination.md`，如有）及项目/个人记忆（可用 `{cmd} recall <名称>` 查阅）执行；只做步骤或用户要求的范围，不要自行扩展。")
                lines.append(f"   - 每完成一个中间步骤可运行 `{cmd} update {tid} --step-done` 打勾；全部完成后运行 "
                             f"`{cmd} update {tid} --status done --note \"<合并提交、已完成步骤与验证结果>\"` 汇报。")
            else:
                lines.append("4. 该任务没有合后步骤：`land` 退出 0 即自动标为 merged、通知 PM 并安排清理，无需再汇报，直接停下。")
            if for_helper:
                lines.append(f"5. 全部结束后务必运行 `{cmd} helper done --text \"<简明结果>\"` 向 PM 汇报结论。")
        else:
            lines.append(f"PM approved merging task {tid} ({branch} -> {base}). Execute the following:")
            if extra_note:
                lines.append(f"- PM note: {extra_note}")
            lines.append(f"1. Run merge & checks: `{land_cmd}`")
            lines.append(f"2. On conflicts (exit 4): in worktree ({worktree or repo}) run `git merge {base}`, "
                         f"resolve conflicts, run targeted checks, commit, then re-run `{land_cmd}`.")
            lines.append(f"3. On check failure (exit 1): diagnose; if a fix requires code changes report "
                         f"`{cmd} update {tid} --status review --commit <sha> --note \"...\"`, or if blocked report "
                         f"`{cmd} update {tid} --status blocked --note \"<reason>\"`.")
            if remaining:
                step_list = "; ".join(s.get("text") or "" for s in remaining)
                lines.append(f"4. After merge succeeds, execute the remaining outer plan steps from main checkout `{repo}`: {step_list}")
                lines.append(f"   - Follow the exact outer plan steps, the project profile (`{repo}/.claude/coordination.md` if present), and relevant project/personal memories (`{cmd} recall <name>`); stay strictly within the requested targets.")
                lines.append(f"   - Check off intermediate steps with `{cmd} update {tid} --step-done`, and finish with "
                             f"`{cmd} update {tid} --status done --note \"<merge sha, completed steps, checks>\"`.")
            else:
                lines.append("4. No post-merge steps remain: once `land` exits 0, the task is marked merged, PM is notified, and cleanup is scheduled — stop immediately.")
            if for_helper:
                lines.append(f"5. When finished, run `{cmd} helper done --text \"<concise summary>\"` to deliver the conclusion to the PM.")
        return "\n".join(lines)

    # --- approve ---

    def approve(self, req: ApproveRequest) -> Landed:
        """PM approves a task for merge and delegates execution (`land` + post-merge steps) asynchronously to its
        worker (default when live) or a dedicated execution helper. Returns at once; never blocks the PM."""
        tr, ctx = self._tr, self.ctx
        task = self._ledger.load(req.id).raw
        tid = task["id"]
        done = Landed(task_id=tid)
        if self._caller.helper_self_info() or (ctx.pane and not self._caller.is_pm_caller(task)):
            raise self._refuse(tr(f"refused: only the PM may approve merging {tid}",
                                  f"已拒绝：只有 PM 可以批准合并 {tid}"))
        if req.revoke:
            def _revoke(cur: dict[str, Any], ch: Change) -> None:
                cur.pop("land_approved", None)
                ch.note_on(cur, tr("PM revoked merge approval", "PM 撤销了合并授权"), source="pm")
            self._change(tid, _revoke)
            done.said.append(("out", tr(f"{tid}: merge approval revoked", f"{tid}：已撤销合并授权")))
            return done
        if task.get("review_of"):
            raise self._refuse(tr(f"{tid} is a review thread; approve the parent task {task['review_of']} instead",
                                  f"{tid} 是审查线程；请对父任务 {task['review_of']} 执行 approve"))
        if task.get("landed") or task.get("status") in ("merged", "abandoned"):
            raise self._refuse(tr(
                f"{tid} is already {task.get('status')}" + (f" (landed {task['landed'].get('commit', '')})" if task.get("landed") else ""),
                f"{tid} 已经是 {task.get('status')}" + (f"（已合并 {task['landed'].get('commit', '')}）" if task.get("landed") else "")))
        repo, branch = task["repo"], task.get("branch")
        if not branch:
            raise self._refuse(tr(f"{tid} has no branch to land", f"{tid} 没有可合并的分支"))
        git = ctx.git
        base = git.merge_target(repo, task["base"])
        if git.run(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}") is None:
            raise self._refuse(tr(f"branch {branch} does not exist in {repo}", f"{repo} 里找不到分支 {branch}"))
        branch_head = git.run(repo, "rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}") or ""
        explicit_commit = req.commit or ""
        recorded_commit = explicit_commit or task.get("auto_reviewed_commit") or task.get("commit") or ""
        if recorded_commit:
            resolved_rec = git.run(repo, "rev-parse", "--verify", "--quiet", f"{recorded_commit}^{{commit}}") or ""
            if resolved_rec and branch_head and not branch_matches_approved_commit_for(ctx, repo, branch, base, resolved_rec):
                raise self._refuse(tr(
                    f"{tid}: branch {branch} HEAD ({branch_head[:7]}) has commits beyond the reported/reviewed "
                    f"commit ({resolved_rec[:7]}); review the new commits or pass `--commit {branch_head[:7]}` explicitly",
                    f"{tid}：分支 {branch} 当前 HEAD（{branch_head[:7]}）超出了汇报/审查的提交（{resolved_rec[:7]}）；"
                    f"请先复审新提交，或显式传 `--commit {branch_head[:7]}` 授权"))
            commit_sha = resolved_rec or branch_head or recorded_commit
        else:
            commit_sha = branch_head
        short_sha = (git.run(repo, "rev-parse", "--short", commit_sha) if commit_sha else "") or task.get("commit") or ""

        via = req.via or "auto"
        term = hc_terminal_of(task)
        worker_info = (ctx.hc.get_raw(term, errors=True) or {}) if term and "/" not in term else {}
        worker_live = worker_info.get("state") == "live"
        if via == "worker":
            if not worker_live:
                raise self._refuse(tr(
                    f"{tid}: worker terminal {task.get('pane') or '(none)'} is not live; "
                    f"run `pm.py reattach {tid}` or `pm.py approve {tid} --via helper`",
                    f"{tid}：worker 终端 {task.get('pane') or '（无）'} 未运行；"
                    f"请先 `pm.py reattach {tid}` 或改用 `pm.py approve {tid} --via helper`"))
            executor = "worker"
        elif via == "helper":
            if not ctx.pane.startswith("hc:"):
                raise self._refuse(tr("--via helper requires a desktop-app PM ($HC_TERMINAL_ID)",
                                      "--via helper 需要桌面版 PM（$HC_TERMINAL_ID）"))
            executor = "helper"
        else:
            if worker_live:
                executor = "worker"
            elif ctx.pane.startswith("hc:"):
                executor = "helper"
            else:
                executor = "manual"

        approved = {
            "by": ctx.pane or "cli",
            "at": ctx.clock.now_sec(),
            "branch": branch,
            "base": base,
            "commit": commit_sha,
            "short": short_sha,
            "message": req.message or "",
            "keep": bool(req.keep),
            "timeout": req.timeout or 600,
            "executor": executor,
            "executor_pane": f"hc:{term}" if executor == "worker" else "",
            "helper_name": "",
            "note": (req.note or "").strip(),
        }
        workers = Workers(ctx)

        if executor == "helper":
            prompt_text = self.handoff_prompt(task, approved, for_helper=True)
            # Avoid colliding with a running helper of the same name by suffixing if needed.
            hname = self._helper_name(f"land-{tid}", repo)
            fields = self._helper_fields(prompt_text, hname, req, repo, tid,
                                         timeout=max(int(approved["timeout"]) + 300, helpers_timeout_for(ctx)))
            # Write approval first (with helper_name) so the helper is authorized immediately on start,
            # then update executor_pane once the terminal address is known.
            approved["helper_name"] = hname

            def _record_approve_helper(cur: dict[str, Any], ch: Change) -> None:
                was_blocked = cur.get("status") == "blocked" and self._caller.blocked_by_worker(cur)
                cur["land_approved"] = dict(approved)
                cur["status"] = "in_progress"
                for f in (*QUESTION_FIELDS, "paused_from", "auto_review"):
                    cur.pop(f, None)
                sync_plan_on_approve(cur)
                ch.note_on(cur, tr(f"PM approved merge ({short_sha} -> {base}); delegating to exec helper {hname}",
                                   f"PM 批准合并（{short_sha} -> {base}）；交给执行 helper {hname}"),
                           source="pm", **({"handled_by": "pm"} if was_blocked else {}))

            self._change(tid, _record_approve_helper)
            try:
                hterm = self._start(fields, done)
            except (SystemExit, Exception):
                # Roll back approval if helper failed to start so ledger stays clean.
                self._change(tid, lambda cur, _ch: cur.pop("land_approved", None))
                raise
            if hterm:
                def _bind_helper_pane(cur: dict[str, Any], _ch: Change) -> None:
                    if isinstance(cur.get("land_approved"), dict):
                        cur["land_approved"]["executor_pane"] = f"hc:{hterm}"
                self._change(tid, _bind_helper_pane, board=False)
            workers._deliver_later(repo)
            done.said.append(("out", tr(
                f"{tid}: merge approved ({short_sha} -> {base}); delegated to exec helper {hname}"
                + (f" (hc:{hterm})" if hterm else "") + " (async)",
                f"{tid}：已批准合并（{short_sha} -> {base}）；已异步交给执行 helper {hname}"
                + (f"（hc:{hterm}）" if hterm else ""))))
            return done

        stalls = StallWatcher(ctx)

        def _record_approve(cur: dict[str, Any], ch: Change) -> None:
            was_blocked = cur.get("status") == "blocked" and self._caller.blocked_by_worker(cur)
            cur["land_approved"] = dict(approved)
            cur["status"] = "in_progress"
            for f in (*QUESTION_FIELDS, "paused_from", "auto_review"):
                cur.pop(f, None)
            sync_plan_on_approve(cur)
            if executor == "worker":
                stalls.round_starts(cur, term, turn=worker_info.get("turn") or 0)
            who = f"worker hc:{term}" if executor == "worker" else "manual"
            ch.note_on(cur, tr(f"PM approved merge ({short_sha} -> {base}); delegated to {who}",
                               f"PM 批准合并（{short_sha} -> {base}）；已交给 {who}"),
                       source="pm", **({"handled_by": "pm"} if was_blocked else {}))

        task = self._change(tid, _record_approve)
        prompt_text = self.handoff_prompt(task, approved, for_helper=False)
        if executor == "worker":
            message = f"[from {ctx.pane or 'pm.py'}] {prompt_text}"
            workers.send_async_later(term, message, task_id=tid, repo=repo,
                                     pre_turn=worker_info.get("turn") or 0, timeout=180)
            workers._deliver_later(repo)
            done.said.append(("out", tr(
                f"{tid}: merge approved ({short_sha} -> {base}); delegated to worker hc:{term} (async)",
                f"{tid}：已批准合并（{short_sha} -> {base}）；已异步交给 worker hc:{term}")))
            return done
        cmd = ctx.procs.pm_command()
        done.said.append(("out", tr(
            f"{tid}: merge approved ({short_sha} -> {base}); worker can now run `{cmd} land {tid}`",
            f"{tid}：已批准合并（{short_sha} -> {base}）；执行者现在可运行 `{cmd} land {tid}`")))
        return done

    def _helper_fields(self, prompt_text: str, hname: str, req: Any, repo: str, tid: str, *,
                       timeout: int) -> dict[str, Any]:
        """The `pm.py helper start` options of a PM-delegated exec helper working for task `tid`."""
        return {
            "prompt": prompt_text, "brief": None, "name": hname,
            "profile": req.profile, "kind": req.kind, "model": req.model, "effort": req.effort,
            "advisor": req.advisor, "codex_profile": req.codex_profile,
            "timeout": timeout, "cwd": repo, "task": None, "pm": True, "repo": repo,
            "confirmed": bool(req.confirmed), "dry_run": False, "exec_mode": True, "async_": True,
            "for_task": tid,
        }

    # --- triage ---

    def triage(self, req: TriageRequest) -> Landed:
        """PM delegates inspection and safe unblocking of a stuck worker terminal to an async exec helper."""
        tr, ctx = self._tr, self.ctx
        task = self._ledger.load(req.id).raw
        tid = task["id"]
        if self._caller.helper_self_info() or (ctx.pane and not self._caller.is_pm_caller(task)):
            raise self._refuse(tr(f"refused: only the PM may triage {tid}", f"已拒绝：只有 PM 可以发起 {tid} 的排查"))
        if not ctx.pane.startswith("hc:"):
            raise Refused(tr("pm.py triage requires a desktop-app PM ($HC_TERMINAL_ID)",
                             "pm.py triage 需要桌面版 PM（$HC_TERMINAL_ID）"))
        term = hc_terminal_of(task)
        if not term or "/" in term:
            raise Refused(tr(f"{tid} has no local herdr-core terminal to triage",
                             f"{tid} 没有可排查的本机 herdr-core 终端"))
        info = ctx.hc.get_raw(term, errors=True) or {}
        if info.get("state") != "live":
            raise Refused(tr(f"{tid}: worker terminal hc:{term} is not live ({info.get('state') or 'gone'}); "
                             f"run `pm.py reattach {tid}` instead",
                             f"{tid}：worker 终端 hc:{term} 未在运行（{info.get('state') or 'gone'}）；请改用 `pm.py reattach {tid}`"))
        repo = task["repo"]
        worktree = task.get("worktree") or ""
        extra = (req.note or "").strip()
        cmd = ctx.procs.pm_command()
        prompt_text = tr(
            f"Triage stuck worker terminal hc:{term} for task {tid} ({task.get('title') or ''}).\n"
            f"- Task worktree: {worktree or '(none)'}\n"
            + (f"- PM note: {extra}\n" if extra else "")
            + f"1. Inspect `hc get {term} --json` and `hc read {term} | tail -60`.\n"
            "2. If it is stuck on a safe known prompt (folder trust for the task's own worktree under ~/.herdr/worktrees/, "
            "CLI update prompt, or a transient retryable error), unblock it with `hc keys`/`hc send` and confirm it resumed.\n"
            "3. If it is stuck on quota/rate-limit, auth/login, billing, MCP/hook approval, destructive permission, or a "
            "question needing human input, do NOT click risky options — diagnose clearly.\n"
            f"4. Report a crisp 1-2 sentence conclusion (what happened, whether it resumed, or what decision is needed) via "
            f"`{cmd} helper done --text \"<conclusion>\"`.",
            f"排查卡住的 worker 终端 hc:{term}（任务 {tid}：{task.get('title') or ''}）。\n"
            f"- 任务工作树：{worktree or '（无）'}\n"
            + (f"- PM 补充：{extra}\n" if extra else "")
            + f"1. 查看 `hc get {term} --json` 和 `hc read {term} | tail -60`。\n"
            "2. 如果卡在安全已知提示（~/.herdr/worktrees/ 下本任务工作树的目录信任、CLI 升级提示、或可重试的瞬时错误），"
            "用 `hc keys`/`hc send` 解卡并确认已恢复工作。\n"
            "3. 如果卡在配额/限流、登录鉴权、计费、MCP/hook 审批、破坏性权限或需要用户拍板的问题，不要乱点确认，直接诊断清楚。\n"
            f"4. 用 1-2 句简明结论（原因、是否已恢复、或需要什么决定）运行 `{cmd} helper done --text \"<结论>\"` 汇报。")
        hname = self._helper_name(f"triage-{tid}", repo)
        done = Landed(task_id=tid)
        hterm = self._start(self._helper_fields(prompt_text, hname, req, repo, tid, timeout=600), done)
        done.said.append(("out", tr(
            f"{tid}: triage delegated to exec helper {hname}" + (f" (hc:{hterm})" if hterm else "") + " (async)",
            f"{tid}：已异步交给执行 helper {hname}" + (f"（hc:{hterm}）" if hterm else "") + " 排查处理")))
        return done

    # --- land ---

    def _stuck(self, repo: str) -> PmError:
        """The merge could not be undone: what the main checkout holds now (exit 5)."""
        git, tr = self.ctx.git, self._tr
        merging = git.run(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD") is not None
        changed = (git.run(repo, "status", "--short", "--untracked-files=no") or "").splitlines()
        head = tr(f"the merge could not be undone; {repo} is left "
                  + ("in the middle of the merge (MERGE_HEAD is set)" if merging else "with uncommitted changes")
                  + ". Look at it and clean it up by hand (`git merge --abort`, or `git status`):",
                  f"合并没能撤销；{repo} " + ("停在合并中途（MERGE_HEAD 还在）" if merging else "留有未提交的改动")
                  + "。请手动查看并清理（`git merge --abort`，或 `git status`）：")
        return PmError(head + "\n" + "\n".join(f"  {line}" for line in changed[:20]), code=LAND_STUCK, stream="stdout")

    def land(self, req: LandRequest) -> Landed:
        """Merge a task's branch in the main checkout, run the project's checks, and commit only when all pass."""
        tr, ctx, git = self._tr, self.ctx, self.ctx.git
        task = self._ledger.load(req.id).raw
        tid = task["id"]
        done = Landed(task_id=tid)
        caller_role = self.verify_caller(task)
        delegated_caller = caller_role in ("worker", "helper")
        self_landing = caller_role == "worker" and bool(ctx.pane and task.get("pane") == ctx.pane)
        approved = task.get("land_approved") if isinstance(task.get("land_approved"), dict) else {}
        message = req.message if req.message is not None else (approved.get("message") or None)
        keep = bool(req.keep or (delegated_caller and approved.get("keep")))
        timeout = req.timeout if req.timeout is not None else (approved.get("timeout") or 600)
        if task.get("landed"):
            raise self._refuse(tr(f"{tid} was already landed as {task['landed'].get('commit', '')}",
                                  f"{tid} 已经合并过了（{task['landed'].get('commit', '')}）"))
        repo, branch = task["repo"], task.get("branch")
        base = git.merge_target(repo, task["base"])
        if not branch:
            raise self._refuse(tr(f"{tid} has no branch to land", f"{tid} 没有可合并的分支"))
        checks = verify_commands_for(ctx, repo)
        if not checks:  # no file, or only comments
            vfile = ctx.home.project_for(repo).verify
            raise self._refuse(tr(
                f"no checks for {Path(repo).name}: write them to {vfile}, one shell command per line "
                "(`#` starts a comment), then land again.",
                f"{Path(repo).name} 没有验证命令：写进 {vfile}，一行一条命令（`#` 开头是注释），再合并。"))

        # Serialize merges per project so parallel workers/helpers never collide in the main checkout.
        land_lock = ctx.home.lock(f"land-{project_slug(repo)}")
        try:
            lock_ctx = file_lock(land_lock, timeout=min(max(float(timeout), 60.0), 600.0),
                                 lock_fn=lock_file, unlock_fn=unlock_file)
            lock_ctx.__enter__()
        except LockTimeoutError:
            raise self._refuse(tr(f"another merge is already running in {Path(repo).name}; retry once it finishes",
                                  f"{Path(repo).name} 里已有另一条合并正在运行，等它结束后重试"))
        try:
            current = git.run(repo, "branch", "--show-current")
            if base != "HEAD" and current != base:
                raise self._refuse(tr(f"{repo} is on {current or 'a detached HEAD'}, not {base}",
                                      f"{repo} 当前在 {current or '游离 HEAD'}，不是 {base}"))
            if git.run(repo, "status", "--porcelain", "--untracked-files=no"):
                raise self._refuse(tr(f"{repo} has uncommitted changes; land merges only into a clean checkout",
                                      f"{repo} 有未提交的改动，主检出干净时才合并"))
            if git.run(repo, "merge-base", "--is-ancestor", branch, "HEAD") is not None:
                raise self._refuse(tr(f"{branch} is already in {base}: `pm.py update {tid} --status merged`",
                                      f"{branch} 已经在 {base} 里了：`pm.py update {tid} --status merged`"))
            merged = git.merge_no_commit(repo, branch)
            if not merged.ok:
                conflicts = git.conflicts(repo)
                if not git.undo_merge(repo):
                    raise self._stuck(repo)
                if not conflicts:  # git refused to start, for example over untracked files in the way
                    raise self._refuse(f"git merge {branch}: {(merged.stderr or merged.stdout).strip()[-600:]}")
                cmd = ctx.procs.pm_command()
                if delegated_caller:
                    head = tr(f"conflicts in {len(conflicts)} files; the merge is aborted. "
                              f"In your worktree run `git merge {base}`, resolve conflicts, commit, then re-run `{cmd} land {tid}`:",
                              f"{len(conflicts)} 个文件有冲突，已中止合并。请在工作树里运行 `git merge {base}`，"
                              f"解完冲突并提交后重新运行 `{cmd} land {tid}`：")
                else:
                    head = tr(f"conflicts in {len(conflicts)} files; the merge is aborted. Merge by hand (playbook §5):",
                              f"{len(conflicts)} 个文件有冲突，已中止合并。按手册 §5 手动合并：")
                raise PmError(head + "\n" + "\n".join(f"  {f}" for f in conflicts), code=LAND_CONFLICTS,
                              stream="stdout")
            # From here on the main checkout is mid-merge: whatever happens, it is committed or undone.
            def stopped(signum: int, frame: Any) -> None:
                raise LandStopped(signum)
            signals = tuple(getattr(signal, s) for s in ("SIGTERM", "SIGINT", "SIGHUP") if hasattr(signal, s))  # no SIGHUP on Windows
            before = {s: signal.signal(s, stopped) for s in signals}
            running: list[Any] = []
            failed, landed, why_commit, signum, undone = None, False, "", 0, False
            try:
                failed = run_checks(repo, checks, timeout, running, env=ctx.env, tr=tr)
                if not failed:
                    committed = git.commit(repo, message or f"merge {branch}: {task['title']}")
                    landed = committed.ok
                    why_commit = (committed.stderr or committed.stdout).strip()[-600:]
            except LandStopped as stop:
                signum = stop.args[0]
            finally:
                for s in signals:
                    signal.signal(s, signal.SIG_IGN)  # a second ^C must not stop the undo half way
                if not landed:
                    stop_group(running[0] if running else None)
                    undone = git.undo_merge(repo)
                for s, handler in before.items():
                    signal.signal(s, handler)
            if not landed:
                if not undone:
                    raise self._stuck(repo)
                if signum:
                    raise PmError(tr(f"stopped by signal {signum}; the merge is aborted",
                                     f"被信号 {signum} 中止，已撤销合并"), code=128 + signum, stream="stdout")
                if not failed:
                    raise PmError(f"git commit: {why_commit}", code=1, stream="stdout")
                check, why, out = failed
                said = (tr(f"check failed ({why}), the merge is aborted: {check}", f"检查失败（{why}），已中止合并：{check}")
                        + "\n" + "\n".join(out.rstrip().splitlines()[-20:]))
                msg = tr(f"land: check failed ({why}): {check}", f"land：检查失败（{why}）：{check}")
                self._change(tid, lambda cur, ch: ch.note_on(cur, msg))
                raise PmError(said, code=1, stream="stdout")
            sha = git.run(repo, "rev-parse", "--short", "HEAD")
        finally:
            lock_ctx.__exit__(None, None, None)

        probe_plan = copy.deepcopy(task.get("plan")) if isinstance(task.get("plan"), list) else None
        has_remaining = bool(probe_plan and sync_plan_on_merge({"plan": probe_plan}, advance_next=True))
        if not has_remaining:
            if delegated_caller:
                return self._landed_delegated(done, task, sha, base, branch, checks, caller_role, self_landing, keep)
            return self._landed_by_pm(done, task, sha, base, checks, keep)
        return self._landed_with_steps(done, task, sha, base, branch, checks, caller_role, delegated_caller,
                                       self_landing, keep)

    def _retire_lines(self, task: dict[str, Any], *, keep_active: bool = False) -> list[str]:
        tid = task["id"]
        try:
            return list(Workers(self.ctx).retire(tid, force=False, keep_active=keep_active).lines)
        except PmError as stop:
            return [f"not retired: {stop}. Fix that, then run `pm.py retire {tid}`."]

    def _landed_delegated(self, done: Landed, task: dict[str, Any], sha: str, base: str, branch: str,
                          checks: list[str], caller_role: str, self_landing: bool, keep: bool) -> Landed:
        """No post-merge steps, merged by the worker or exec helper: the hand-written merged record (no reaction
        rows 8-9b; the deliverer reconciles dependents), research, and the worker's cleanup."""
        tr, ctx = self._tr, self.ctx
        tid, repo = task["id"], task["repo"]
        wake_pm = bool(self._projects.app_pm(repo))

        def _land_done_delegated(cur: dict[str, Any], ch: Change) -> None:
            cur["status"] = "merged"
            cur["commit"] = sha
            cur["landed"] = {"commit": sha, "base": base, "branch": branch, "at": ctx.clock.now(), "by": caller_role}
            cur.pop("land_approved", None)
            for f in (*QUESTION_FIELDS, "paused_from", "escalating", "adopting", "auto_review"):
                cur.pop(f, None)
            sync_plan_on_merge(cur, advance_next=False)
            msg = tr(f"status=merged, commit={sha}; landed ({caller_role}): {len(checks)} checks passed",
                     f"status=merged, commit={sha}；已由 {caller_role} 合并：{len(checks)} 条检查通过")
            ch.note_on(cur, msg, source=caller_role, **({"wake": True} if wake_pm else {}))

        task = self._change(tid, _land_done_delegated)
        workers = Workers(ctx)
        if wake_pm:
            workers._deliver_later(repo)
        extra = self._research_lines(task)
        if self_landing:
            closed = workers.retire_review(task)
            if closed:
                extra.append(f"{tid}: closed {', '.join(closed)}")
            if task.get("dispatched") and not keep:
                term = hc_terminal_of(task)
                if term:
                    close_later_for(ctx, term, tid, 10, 7200, CLOSED, retire=True)
                    extra.append(tr(f"{tid}: hc:{term} and workspace will retire once this turn ends",
                                    f"{tid}：hc:{term} 和工作树将在本轮结束后自动回收"))
        elif task.get("dispatched") and not keep:
            extra.extend(self._retire_lines(task))
        else:
            closed = workers.retire_review(task)
            if closed:
                extra.append(f"{tid}: closed {', '.join(closed)}")
        parent_id = task.get("parent")
        if parent_id:
            _rollup_ancestors(ctx, parent_id, child_id=tid)
        done.said.append(("out", tr(f"{tid}: merged as {sha} on {base}; {len(checks)} checks passed",
                                    f"{tid}：已合并为 {sha}（{base}），{len(checks)} 条检查通过")))
        self._say_block(done, extra)
        return done

    def _landed_by_pm(self, done: Landed, task: dict[str, Any], sha: str, base: str, checks: list[str],
                      keep: bool) -> Landed:
        """No post-merge steps, merged by the PM or from a plain shell: `update --status merged` with its reactions;
        the reactions' lines follow the merged line (the `<id>: merged` status line is not repeated)."""
        tr, tid = self._tr, task["id"]
        if task.get("land_approved"):
            self._change(tid, lambda cur, _ch: cur.pop("land_approved", None), board=False)
        heard: list[tuple[str, str]] = []
        Updates(self.ctx).update(
            UpdateRequest(id=tid, status="merged", commit=sha, keep=keep,
                          note=tr(f"landed: {len(checks)} checks passed", f"已合并：{len(checks)} 条检查通过")),
            say=lambda text, err=False: heard.append(("err" if err else "out", text)),
        )
        done.said.extend(s for s in heard if s[0] == "err")
        out = "".join(f"{text}\n" for stream, text in heard if stream == "out")
        done.said.append(("out", tr(f"{tid}: merged as {sha} on {base}; {len(checks)} checks passed",
                                    f"{tid}：已合并为 {sha}（{base}），{len(checks)} 条检查通过")))
        done.said.append(("out", "\n".join(out.splitlines()[1:])))  # what retire removed, or why it did not
        return done

    def _landed_with_steps(self, done: Landed, task: dict[str, Any], sha: str, base: str, branch: str,
                           checks: list[str], caller_role: str, delegated_caller: bool, self_landing: bool,
                           keep: bool) -> Landed:
        """Post-merge steps remain: the task stays in progress on its next step; dependents are reconciled now."""
        tr, ctx = self._tr, self.ctx
        tid, repo = task["id"], task["repo"]
        next_info: dict[str, Any] = {}

        def _land_keep_active(cur: dict[str, Any], ch: Change) -> None:
            cur["status"] = "in_progress"
            cur["commit"] = sha
            landed_rec = {"commit": sha, "base": base, "branch": branch, "at": ctx.clock.now()}
            if self_landing:
                landed_rec["by_worker"] = True
            elif delegated_caller:
                landed_rec["by"] = caller_role
            cur["landed"] = landed_rec
            cur.pop("land_approved", None)
            for f in (*QUESTION_FIELDS, "paused_from", "escalating", "adopting", "auto_review"):
                cur.pop(f, None)
            sync_plan_on_merge(cur, advance_next=True)
            done_n, total_n, next_step = plan_progress(cur.get("plan"))
            next_info.update({"done": done_n, "total": total_n, "next": next_step})
            msg = tr(
                f"landed {sha} on {base}: {len(checks)} checks passed ({done_n}/{total_n}, next: {next_step})",
                f"已合并 {sha}（{base}），{len(checks)} 条检查通过（{done_n}/{total_n}，下一步：{next_step}）",
            )
            ch.note_on(cur, msg, source=caller_role if delegated_caller else "pm", wake=False)

        task = self._change(tid, _land_keep_active)
        DependencyWatcher(ctx).reconcile_dependents_of(tid, primary_repo=repo)
        workers = Workers(ctx)
        extra = self._research_lines(task)
        if self_landing:
            # Keep the worker terminal and worktree intact while the worker completes remaining post-merge steps.
            closed = workers.retire_review(task)
            if closed:
                extra.append(f"{tid}: closed {', '.join(closed)}")
        elif task.get("dispatched") and not keep:
            extra.extend(self._retire_lines(task, keep_active=True))
        else:
            closed = workers.retire_review(task)
            if closed:
                extra.append(f"{tid}: closed {', '.join(closed)}")
        done_n, total_n, next_step = next_info.get("done", 0), next_info.get("total", 0), next_info.get("next", "")
        done.said.append(("out", tr(
            f"{tid}: merged as {sha} on {base}; {len(checks)} checks passed (active {done_n}/{total_n}, next: {next_step})",
            f"{tid}：已合并为 {sha}（{base}），{len(checks)} 条检查通过（任务保持进行中 {done_n}/{total_n}，下一步：{next_step}）",
        )))
        if delegated_caller:
            cmd = ctx.procs.pm_command()
            done.said.append(("out", tr(
                f"Continue post-merge steps in {repo}, check off intermediate steps with `{cmd} update {tid} --step-done`, "
                f"and finish with `{cmd} update {tid} --status done --note \"<summary>\"`.",
                f"请在主检出 {repo} 继续执行合后步骤，中间步骤可用 `{cmd} update {tid} --step-done` 打勾，"
                f"全部完成后运行 `{cmd} update {tid} --status done --note \"<总结>\"`。")))
        self._say_block(done, extra)
        return done

    def _research_lines(self, task: dict[str, Any]) -> list[str]:
        collected = Workers(self.ctx).collect_research(task)
        return [f"{task['id']}: collected research: {', '.join(collected)}"] if collected else []

    @staticmethod
    def _say_block(done: Landed, extra: list[str]) -> None:
        """The cleanup lines after the merged line, as one block without surrounding blank lines."""
        text = "".join(f"{line}\n" for line in extra).strip()
        if text:
            done.said.append(("out", text))
