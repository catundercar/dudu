"""`Reviews(ctx)` service: start a read-only reviewer thread, plan sync on review start/done, auto-review gating and
the auto-review launch. Zero globals, zero `sys.exit`, zero `print`. Layer 3."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Sequence

from ..agents.profiles import WorkerSpec, fable_fallback, fallback_said, review_models, worker_record
from ..caller import Caller
from ..context import Context
from ..errors import PmError, Refused
from ..events.deliver import PASSED
from ..events.stalls import StallWatcher
from ..ledger.ledger import Change, Ledger
from ..ledger.plan import auto_review_max_rounds, has_pending_review_step, step_anchor
from ..ledger.question import QUESTION_FIELDS
from ..ledger.task import Task
from ..memory.layer import MemoryLayer
from ..osutil import Options, clip, file_text, slugify
from ..project.project import ProjectRegistry
from ..store import StoreError, valid_task_id
from ..terminals.tabs import bug_of, hc_name, new_tabs, not_renamed, tab_short, tab_title, tabs_cfg, task_bug
from ..workers.dispatch import review_placement_for
from ..workers.escalate import review_reports, task_workspace_for, tui_prompt_for, tui_tab_agent_for
from ..workers.lifecycle import end_worker_for, live_worker_for
from ..workers.send import send_when_ready_for
from ..workers.service import Workers
from ..workers.sessions import clear_task_session_for
from .land import verify_commands_for


class ReviewRequest(Options):
    """Typed input for `Reviews.start` (the `pm.py review` flags)."""

    required = ('id',)

    id: str = ""
    name: str | None = None
    kind: str | None = None
    model: str | None = None
    effort: str | None = None
    tab: str | None = None
    bug: str | None = None
    codex_profile: str | None = None
    dry_run: bool = False

    @classmethod
    def from_args(cls, a: Any) -> ReviewRequest:
        return cls(
            id=a.id,
            name=getattr(a, "name", None),
            kind=getattr(a, "kind", None),
            model=getattr(a, "model", None),
            effort=getattr(a, "effort", None),
            tab=getattr(a, "tab", None),
            bug=getattr(a, "bug", None),
            codex_profile=getattr(a, "codex_profile", None),
            dry_run=bool(getattr(a, "dry_run", False)),
        )


@dataclass(repr=False, eq=False)
class ReviewStarted:
    """What `Reviews.start` did: stdout lines, stderr lines (in the order they arose) and, for --dry-run, the plan."""

    review_id: str = ""
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    plan: dict[str, Any] | None = None
    said: list[tuple[str, str]] = field(default_factory=list)  # ("out"|"err", text) in order


class ReviewFailed(PmError):
    """`Reviews.start` stopped: the message, plus what it had said before it stopped (for the auto-review reason)."""

    def __init__(self, message: str, said: Sequence[tuple[str, str]] = (), *, code: int | None = None,
                 stream: str | None = None) -> None:
        super().__init__(message, code=code, stream=stream)
        self.said = list(said)


class Reviews:
    """Layer 3 service owning review threads (`pm.py review`), plan-driven auto-review and the reviewer's plan sync."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._ledger = Ledger(ctx)
        self._projects = ProjectRegistry(ctx)

    @property
    def _caller(self) -> Caller:
        return self.ctx.caller if self.ctx.caller is not None else Caller(self.ctx)

    def _tr(self, en: str, zh: str) -> str:
        return self.ctx.config.tr(en, zh)

    # --- plan sync ---

    def sync_on_start(self, task_id: str) -> None:
        """When a review starts for task_id, mark any doing work step done and the review step doing."""
        def _mark(cur: Task | None, _ch: Change) -> dict[str, Any] | None:
            raw = cur.raw if cur is not None else None
            plan = raw.get("plan") if isinstance(raw, dict) else None
            if not isinstance(plan, list) or not plan:
                return None
            changed = False
            for s in plan:
                if isinstance(s, dict) and s.get("state") == "doing" and step_anchor(s) not in ("review", "merge"):
                    s["state"] = "done"
                    changed = True
            for s in plan:
                if isinstance(s, dict) and step_anchor(s) == "review" and s.get("state") != "done":
                    if s.get("state") != "doing":
                        s["state"] = "doing"
                        changed = True
                    break
            return raw if changed else None

        with contextlib.suppress(Exception):
            self._ledger.change(task_id, _mark, board=False)

    def sync_on_done(self, parent_id: str, review_id: str, review_note: str, *, passed: bool) -> None:
        """Update the parent task's outer @review step and auto_review metadata silently when its reviewer finishes."""
        if not parent_id or not valid_task_id(parent_id) or not self.ctx.home.task(parent_id).is_file():
            return

        def _finish(cur: Task | None, ch: Change) -> dict[str, Any] | None:
            raw = cur.raw if cur is not None else None
            if not isinstance(raw, dict):
                return None
            changed = False
            plan = raw.get("plan")
            if passed and isinstance(plan, list):
                for state_target in ("doing", "todo"):
                    idx = next(
                        (i for i, s in enumerate(plan)
                         if isinstance(s, dict) and step_anchor(s) == "review" and s.get("state") == state_target),
                        None,
                    )
                    if idx is not None:
                        plan[idx]["state"] = "done"
                        changed = True
                        break
            ar = raw.get("auto_review")
            had_auto = isinstance(ar, dict) and ar.get("status") in ("starting", "running")
            if had_auto:
                ar["status"] = "passed" if passed else "blockers"
                ar["finished_at"] = self.ctx.clock.now()
                ar["verdict"] = clip(review_note, 400)
                changed = True
            if changed:
                summary = clip(" ".join(review_note.split()), 300)
                msg = (self._tr(f"review passed ({review_id}): {summary}", f"审查通过（{review_id}）：{summary}")
                       if passed else
                       self._tr(f"review found blockers ({review_id}): {summary}",
                                f"审查发现问题（{review_id}）：{summary}"))
                ch.note_on(raw, msg, source="reviewer", wake=False)
            return raw if changed else None

        with contextlib.suppress(Exception):
            self._ledger.change(parent_id, _finish, board=False)

    # --- auto-review gating ---

    def prev_review_failed(self, task_id: str) -> bool:
        """Whether the previous review thread for task_id finished with blockers (not passed, not retired)."""
        path = self.ctx.home.task(f"{task_id}-review")
        if not path.is_file():
            return False
        try:
            old = json.loads(path.read_text())
        except (OSError, ValueError):
            return False
        if not isinstance(old, dict) or old.get("review_of") != task_id or old.get("retired") or old.get("status") == "in_progress":
            return False
        reports = review_reports(old)
        return bool(reports and not PASSED.match(reports[-1][1]))

    def should_auto_review(self, task: dict[str, Any], commit: str | None, changes: Sequence[str]) -> tuple[bool, str, str]:
        """Decide whether a worker's report should trigger plan-driven auto-review: `(should_run, resolved_sha,
        skip_reason)`."""
        if not commit or task.get("review_of") or self._caller.is_pm_caller(task):
            return False, "", ""
        if task.get("status") != "review":
            return False, "", ""
        if task.get("no_review") or not has_pending_review_step(task):
            return False, "", ""
        branch, repo = task.get("branch"), task.get("repo")
        worktree = task.get("worktree") or (self.ctx.git.checkout_of(repo, branch) if repo and branch else "")
        if not branch or not worktree or not Path(worktree).is_dir():
            return False, "", "no worktree"
        resolved = self.ctx.git.run(worktree, "rev-parse", "--verify", f"{commit}^{{commit}}") or commit
        rev_path = self.ctx.home.task(f"{task['id']}-review")
        if rev_path.is_file():
            try:
                old = json.loads(rev_path.read_text())
            except (OSError, ValueError):
                old = {}
            if (isinstance(old, dict) and old.get("review_of") == task["id"] and old.get("status") == "in_progress"
                    and live_worker_for(self.ctx, old)):
                ar = task.get("auto_review") if isinstance(task.get("auto_review"), dict) else {}
                same_commit = resolved == task.get("auto_reviewed_commit") or (
                    ar.get("status") in ("starting", "running") and resolved == ar.get("resolved")
                )
                return False, resolved, ("duplicate running commit" if same_commit else "review already running")
        if not ("status=review" in changes or any(c.startswith("commit=") for c in changes)):
            return False, "", ""
        ahead, _ = self.ctx.git.git_state(worktree, branch, task.get("base") or "main")
        if ahead is not None and ahead <= 0:
            return False, "", "no commits ahead"
        if resolved == task.get("auto_reviewed_commit"):
            return False, resolved, "already reviewed"
        next_rounds = (task.get("rounds") or 0) + (1 if self.prev_review_failed(task["id"]) else 0)
        if next_rounds >= auto_review_max_rounds(self.ctx.config.read()):
            return False, resolved, "round limit reached"
        return True, resolved, ""

    # --- the reviewer ---

    def brief(self, task: dict[str, Any], rid: str, worktree: str | Path) -> str:
        """The reviewer's brief (`sent/<id>-review.md`, before the memory block)."""
        if getattr(self.ctx, "_legacy", False) and review_brief is not _DEFAULT_REVIEW_BRIEF:
            return review_brief(task, rid, worktree)
        return self._brief_impl(task, rid, worktree)

    def _brief_impl(self, task: dict[str, Any], rid: str, worktree: str | Path) -> str:
        branch, base = task["branch"], task["base"]
        checks = verify_commands_for(self.ctx, task["repo"])
        cmd = f"{self.ctx.procs.pm_command()} update {rid} --status done --note"  # done: a review is not work waiting to be merged
        run = "\n".join(f"  - `{c}`" for c in checks or [])
        docs = self.ctx.agents.docs_line()
        ref = self._ledger.task_ref(task)
        return self._tr(
            f"Review (read-only) of task {ref}: {task['title']}\n"
            "Do not commit, edit files or create branches: read, run the checks, report.\n"
            f"- Brief: {task.get('brief') or '(none recorded)'}\n"
            f"- Worktree: {worktree}; range `git diff {base}...{branch}` (`--stat` first, then the source changes)\n"
            "- Checklist:\n"
            "  1. The diff against the brief: flag anything outside it.\n"
            "  2. Red lines: no `git add -A` debris, no secrets, no third-party assets, nothing that touches the user's "
            "running apps or system settings.\n"
            "  3. Correctness: edge cases the worker could not have seen (destructive file operations, compatibility "
            "with old peers, signing, OS-version behaviour). Test a claim in a scratch directory when it is cheap.\n"
            "  4. Visual or UX results: look at the evidence image.\n"
            + (f"- The project's checks (run them in the worktree; `git status` must stay clean):\n{run}\n" if checks
               else "- The project has no verify file: skip the checks.\n")
            + f"\nReport: `{cmd} \"<numbered findings, one per line; none: no blockers>\"`\n"
            "The PM reads only this report. Keep it under 600 characters, in the user's language. Then stop.\n"
            + docs,
            f"审查（只读）任务 {ref}：{task['title']}\n"
            "不提交、不改文件、不开新分支：只读代码、跑检查、汇报。\n"
            f"- 任务书：{task.get('brief') or '（未登记）'}\n"
            f"- 工作树：{worktree}；范围 `git diff {base}...{branch}`（先 `--stat`，再读源码改动）\n"
            "- 检查清单：\n"
            "  1. 对照任务书看 diff：超出范围的都指出来。\n"
            "  2. 红线：没有 `git add -A` 带进来的杂物、密钥、第三方资源，没有碰用户正在运行的应用或系统设置。\n"
            "  3. 正确性：worker 看不到的边界情况（破坏性的文件操作、与旧版本的兼容、签名、系统版本差异）。"
            "便宜的就在临时目录里试一下。\n"
            "  4. 有界面结果的：看证据图。\n"
            + (f"- 项目的验证命令（在工作树里跑，跑完 `git status` 仍应干净）：\n{run}\n" if checks
               else "- 项目没有 verify 文件：跳过验证命令。\n")
            + f"\n汇报：`{cmd} \"<编号的问题清单，每条一行；没有问题就写 无阻塞>\"`\n"
            "PM 只看这条汇报。写在 600 字以内，用中文。然后停下。\n" + docs)

    def reviewer_spec(self, given: WorkerSpec, task: dict[str, Any]) -> tuple[WorkerSpec, bool]:
        """The reviewer's kind, model and effort, and whether they came from the review table (`by_table`).

        A model given, or a configured `reviewer`: the reviewer role as before. Otherwise the review table
        (`review_models`) by the profile the task's worker ran with, so a different model reviews the work; Claude
        unless the entry says otherwise. A reviewer runs without a profile's advisor; a Fable reviewer falls back to
        Sonnet when Fable cannot be used. Raises `Refused` for an unknown profile."""
        cfg = self.ctx.config.read()
        entry = (review_models(cfg).get((task.get("worker") or {}).get("profile") or "")
                 if not given.model and not cfg.get("reviewer") else None)
        entry = {"model": entry} if isinstance(entry, str) else entry if isinstance(entry, dict) else {}
        kind = entry.get("kind") or "claude"
        by_table = bool(entry.get("model")) and given.kind in ("", kind)
        if by_table:
            spec = WorkerSpec.from_args(given)
            spec.kind, spec.model, spec.effort = kind, entry["model"], given.effort or entry.get("effort") or ""
        else:
            spec = self.ctx.agents.resolve_worker(given, role="reviewer")
        spec.profile, spec.advisor = "", ""
        spec.fallback = fable_fallback(spec.kind, spec.model, "reviewer", cfg=cfg)
        return spec, by_table

    def start(self, req: ReviewRequest) -> ReviewStarted:
        """Start a read-only reviewer on a task's branch, as a thread of its own: task <id>-review.

        Raises `ReviewFailed` (a `PmError`, exit 1 on stderr) when nothing could be started or the brief was not
        delivered; `ReviewFailed.said` carries what was said before."""
        out = ReviewStarted()

        def say(text: str) -> None:
            out.lines.append(text)
            out.said.append(("out", text))

        def warn(text: str) -> None:
            out.warnings.append(text)
            out.said.append(("err", text))

        def fail(text: str) -> ReviewFailed:
            return ReviewFailed(text, out.said)

        tr = self._tr
        try:
            task = self._ledger.load(req.id).raw
        except StoreError:
            raise
        except PmError as err:
            raise fail(str(err)) from err
        tid = task["id"]
        if task.get("review_of") or not task.get("branch"):
            raise fail(tr(f"{tid} has no branch to review", f"{tid} 没有可审查的分支"))
        worktree = task.get("worktree") or self.ctx.git.checkout_of(task["repo"], task["branch"])
        if not worktree or not Path(worktree).is_dir():
            raise fail(tr(f"no checkout has {task['branch']}", f"没有检出 {task['branch']} 的工作树"))
        given = WorkerSpec(kind=req.kind or "", model=req.model or "", effort=req.effort or "",
                           codex_profile=req.codex_profile or "", name=req.name or "", dry_run=req.dry_run)
        try:
            spec, by_table = self.reviewer_spec(given, task)
        except Refused as err:
            raise fail(str(err)) from err
        dry = req.dry_run
        workers = Workers(self.ctx)
        try:
            spec, pool_warn = workers.apply_codex_pool(spec, task["repo"], "reviewer", hold=not dry)
        except StoreError:
            raise
        except PmError as err:
            raise ReviewFailed(str(err), out.said, code=err.code, stream=err.stream) from err
        try:
            if pool_warn:
                warn(pool_warn)
            rid = f"{tid}-review"
            path = self.ctx.home.task(rid)
            old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if old and old.get("review_of") != tid:
                raise fail(f"task {rid} exists and is not a review of {tid}")
            worker = task.get("agent") or slugify(tid)
            tui = self._caller.in_tui()
            # A herdr TUI agent name, and an hc terminal name, has at most 32 characters (hc's: a-z 0-9 - _).
            name = req.name or (f"{worker[:25].rstrip('-')}-review" if tui else f"{hc_name(worker, 25)}-review")
            # With tabs.new_tab, its tab: "<terminal>-<BUG>-<tabs.review>-<the task's short>".
            cfg = self.ctx.config
            review_word = tabs_cfg(cfg).get("review") or tr("review", "审查")
            bug = bug_of(req.bug or "", req.tab or "", cfg=cfg) or ("" if req.tab else task_bug(task, cfg=cfg))
            short = tab_short(req.tab or f"{review_word}-" + tab_short(task.get("tab") or task["title"],
                                                                       task_bug(task, cfg=cfg))[:16], bug)
            tab = tab_title(short, bug, dry=True, cfg=cfg) if new_tabs(cfg=cfg, pane=self.ctx.pane) else ""
            # A Claude Code reviewer is given no tool that writes files: it reads, runs the checks and reports.
            extra = ["--disallowedTools", "Edit,Write,NotebookEdit"] if spec.kind == "claude" else []
            reads = self.ctx.agents.outside_reads(task["repo"], task.get("brief") or "")
            if dry:
                out.plan = workers.build_dry_run_plan(
                    spec, task["repo"], "review", rid, worktree, tab,
                    parent=task.get("parent") or "", reads=reads, extra=extra,
                )
                out.review_id = rid
                return out
            if old:
                end_worker_for(self.ctx, old, why="review")  # a review that is run again starts from a fresh reviewer
            sent = self.ctx.home.sent(rid)
            sent.parent.mkdir(parents=True, exist_ok=True)
            sent.write_text(self.brief(task, rid, worktree) + MemoryLayer(self.ctx, task.get("repo")).memory_part(),
                            encoding="utf-8")
            workspace, agent, fast = "", name, ""
            argv = workers.worker_argv(spec, reads, task["repo"], extra, wrap=not tui)
            if tui:
                # In the herdr TUI: a tab beside the task's worker, as escalate makes one. Never herdr-core, even where
                # `hc` is installed: the desktop app would run it where this PM cannot see it.
                workspace = task_workspace_for(self.ctx, task)
                pane, failed = tui_tab_agent_for(self.ctx, workspace, worktree, name, spec.kind, argv)
                workers.pool_started(spec, task["repo"])
                if failed:
                    raise fail(tr(f"no reviewer was started: no tab could be made in workspace {workspace or '(none)'}"
                                  if failed == "no tab" else f"no reviewer was started: agent start failed in {pane}",
                                  f"没有起审查 worker：没能在工作区 {workspace or '（无）'} 开出标签页" if failed == "no tab"
                                  else f"没有起审查 worker：在 {pane} 启动 agent 失败"))
            else:
                made = self.ctx.hc.start_terminal(name, worktree, argv, review_placement_for(self.ctx, task))
                workers.pool_started(spec, task["repo"])
                if not made:
                    raise fail("hc run failed; no reviewer was started")
                tab = tab_title(short, bug, made, cfg=cfg) if tab else ""
                agent = tab or name
                if not self.ctx.hc.worker_tab(made, rid, tab, parent=task.get("parent") or "",
                                              caller_pane=self.ctx.pane) and tab:
                    tab += not_renamed(cfg=cfg)
                fast = workers.codex_fast(made, spec)
                pane = f"hc:{made}"
        finally:
            workers.pool_started(spec, task["repo"])
        # A review run again after the one before reported blockers: that round of work did not pass. Not after a pass
        # (a report that starts as the brief says, "no blockers"), after a review that never reported, or once the
        # review thread is closed (an escalation closes it, so the new worker's rounds start from nothing).
        reports = review_reports(old) if old and not old.get("retired") and old.get("status") != "in_progress" else []
        if reports and not PASSED.match(reports[-1][1]):
            def _inc_rounds(cur: Task | None, _ch: Change) -> dict[str, Any]:
                assert cur is not None
                cur.raw["rounds"] = (cur.raw.get("rounds") or 0) + 1
                return cur.raw
            self._ledger.change(tid, _inc_rounds)
        said = " ".join(x for x in (f"{spec.kind} -p {spec.provider}" if spec.provider else spec.kind,
                                    spec.model, spec.effort) if x)
        of = (task.get("worker") or {}).get("profile") if by_table else ""
        review_note = (tr(f"review started ({said}" + (f", the review model for {of})" if of else ")"),
                          f"开始审查（{said}" + (f"，{of} 档的评审模型）" if of else "）"))
                       + fallback_said(spec, tr_fn=self.ctx.config.tr)
                       + "".join(f"; {x}" for x in (spec.pool_said, f"tab={tab}" if tab else "", fast) if x))
        w_rec = worker_record(spec)
        stalls = StallWatcher(self.ctx)

        def _start_review(cur: Task | None, ch: Change) -> dict[str, Any]:
            base_rev = dict(cur.raw) if cur is not None else {}
            review = {**base_rev, "id": rid, "title": tr("Review: ", "审查：") + task["title"],
                      "project": task["project"], "repo": task["repo"], "status": "in_progress", "base": task["base"],
                      "owner": "pm", "workspace": workspace, "pane": pane, "worker_pane": pane, "agent": agent,
                      "brief": str(sent), "tab": short, "review_of": tid, "worker": w_rec,
                      "created": base_rev.get("created") or self.ctx.clock.now()}
            if bug:
                review["bug"] = bug
            if base_rev:
                clear_task_session_for(self.ctx, review)
            for f in ("retired", "commit", "session", "closed", *QUESTION_FIELDS):
                review.pop(f, None)
            ch.note_on(review, review_note)
            if not tui:
                stalls.round_starts(review, pane[3:], handed=False)  # starting up until the brief is sent
            return review

        self._ledger.change(rid, _start_review, create=True)
        self.sync_on_start(tid)
        if tui:
            got = tui_prompt_for(self.ctx, name, pane, sent.read_text())
            if got in ("refused", "gone"):
                seen_text = (tr("(no agent in the pane)", "（窗格里已经没有 agent）") if got == "gone" else
                             tr("(the prompt was refused)", "（提示没送进去）"))
                self._note(rid, tr(f"brief not sent: {seen_text}", f"任务书没送达：{seen_text}"))
                raise fail(f"the review brief was not sent to {pane}: {seen_text}\nOnce it is ready, send it by hand: "
                           f"herdr agent prompt {name} {file_text(sent)}")
            if got == "idle":
                warn(f"warning: {name} did not start working; read its screen")
        else:
            seen: dict[str, Any] = {}
            sent_ok = send_when_ready_for(self.ctx, pane[3:], sent.read_text(), tries=30, pause=2,
                                          strict=spec.kind in ("claude", "codex"), trust=worktree,
                                          kind=spec.kind, seen=seen)
            if not stalls.round_sent(rid, pane[3:], sent_ok, seen):
                seen_text = self.ctx.hc.screen_line(pane[3:])
                self._note(rid, tr(f"brief not sent; the reviewer's screen: {seen_text}",
                                   f"任务书没送达；审查 worker 屏幕上是：{seen_text}"))
                raise fail(f"the review brief was not sent to {pane}. Its screen: {seen_text}\nOnce it is ready, "
                           f"send it by hand: hc send {pane[3:]} {file_text(sent)}")
        workers._deliver_later(task["repo"])  # it watches the reviewer from now on
        if self._projects.app_pm(task["repo"]):
            say(tr(f"{rid}: reviewer in {pane}. Its findings are delivered to you when it reports.",
                   f"{rid}：审查 worker 在 {pane}。它汇报后结论会送到你这里。"))
        else:
            say(tr(f"{rid}: reviewer in {pane}. Get its findings with `pm.py wait {rid}`.",
                   f"{rid}：审查 worker 在 {pane}。用 `pm.py wait {rid}` 拿结论。"))
        out.review_id = rid
        return out

    def _note(self, task_id: str, text: str, **extra: Any) -> None:
        self._ledger.change(task_id, lambda cur, ch: (ch.note_on(cur.raw, text, **extra), cur.raw)[1])

    # --- plan-driven auto-review ---

    def run_auto_review(self, task_id: str, commit: str, resolved_sha: str, worker_note: str) -> str:
        """Launch an independent read-only reviewer for task_id; on failure hand the report to the PM (wake it when
        it runs in the app). Returns the one stdout line to show."""
        tr = self._tr
        try:
            self.start(ReviewRequest(id=task_id))
        except (SystemExit, Exception) as err:  # noqa: BLE001 - whatever stopped it, the PM gets the report
            if isinstance(err, SystemExit):
                raw = str(err.code) if err.code not in (None, 0) else ""
            else:
                raw = str(err)
            said = list(getattr(err, "said", ()) or ())
            lines = [ln.strip() for _, block in said for ln in block.splitlines() if ln.strip()]
            reason = clip(raw or (lines[-1] if lines else "failed"), 200)

            def _fail(cur: Task | None, ch: Change) -> dict[str, Any]:
                assert cur is not None
                raw_task = cur.raw
                ar = dict(raw_task.get("auto_review") or {})
                ar.update({"status": "failed", "error": reason, "failed_at": self.ctx.clock.now()})
                raw_task["auto_review"] = ar
                if isinstance(raw_task.get("plan"), list):
                    for s in raw_task["plan"]:
                        if isinstance(s, dict) and step_anchor(s) == "review" and s.get("state") == "doing":
                            s["state"] = "todo"
                told = {"source": "worker", **({"wake": True} if self._projects.app_pm(raw_task.get("repo")) else {})}
                msg = tr(
                    f"auto-review failed ({reason}); handed to PM (commit {commit})"
                    + (f": {worker_note}" if worker_note else ""),
                    f"自动审查启动失败（{reason}），转交 PM（commit {commit}）"
                    + (f"：{worker_note}" if worker_note else ""),
                )
                ch.note_on(raw_task, msg, **told)
                return raw_task

            parent = self._ledger.change(task_id, _fail)
            if parent is not None and parent.raw.get("repo"):
                Workers(self.ctx)._deliver_later(parent.raw["repo"])
            return tr(f"{task_id}: auto-review failed ({reason}); handed to PM",
                      f"{task_id}：自动审查启动失败（{reason}），已转交 PM")

        rid = f"{task_id}-review"

        def _started(cur: Task | None, ch: Change) -> dict[str, Any]:
            assert cur is not None
            raw_task = cur.raw
            raw_task["auto_reviewed_commit"] = resolved_sha
            ar = dict(raw_task.get("auto_review") or {})
            ar.update({
                "status": "running",
                "review_id": rid,
                "commit": commit,
                "resolved": resolved_sha,
                "note": worker_note or "",
                "started_at": self.ctx.clock.now(),
            })
            raw_task["auto_review"] = ar
            ch.note_on(raw_task, tr(f"auto-review started ({rid})", f"已自动拉起独立审查（{rid}）"),
                       source="harness", wake=False)
            return raw_task

        self._ledger.change(task_id, _started, board=False)
        return tr(f"{task_id}: auto-review started ({rid})", f"{task_id}：已自动拉起独立审查（{rid}）")


# --- Legacy module-level functions (Stages 1-5 compatibility) ---


def sync_plan_on_review_start(task_id: str) -> None:
    Reviews(Context.from_env()).sync_on_start(task_id)


def sync_plan_on_review_done(parent_id: str, review_id: str, review_note: str, *, passed: bool) -> None:
    Reviews(Context.from_env()).sync_on_done(parent_id, review_id, review_note, passed=passed)


def prev_review_failed(task_id: str) -> bool:
    return Reviews(Context.from_env()).prev_review_failed(task_id)


def should_auto_review(task: dict[str, Any], a: Any, changes: Sequence[str]) -> tuple[bool, str, str]:
    """Decide whether worker's report should trigger plan-driven auto-review: `(should_run, resolved_sha,
    skip_reason)`."""
    return Reviews(Context.from_env()).should_auto_review(task, getattr(a, "commit", None), changes)


def review_brief(task: dict[str, Any], rid: str, worktree: str | Path) -> str:
    return Reviews(Context.from_env())._brief_impl(task, rid, worktree)


_DEFAULT_REVIEW_BRIEF = review_brief


def reviewer_defaults(a: Any, task: dict[str, Any]) -> Any:
    """`Reviews.reviewer_spec` written back onto a namespace (`by_table`, `kind`, `model`, `effort`, `profile`,
    `advisor`, `fallback`), as before."""
    spec, by_table = Reviews(Context.from_env()).reviewer_spec(WorkerSpec.from_args(a), task)
    a.by_table = by_table
    if by_table:
        a.kind, a.model, a.effort = spec.kind, spec.model, spec.effort
    else:
        spec.apply_to(a)
    a.profile, a.advisor = "", ""
    a.fallback = spec.fallback
    return a
