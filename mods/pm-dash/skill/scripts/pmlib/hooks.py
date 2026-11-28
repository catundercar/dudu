"""The hooks an agent runs: before a tool (hook-pre-tool: a PM's question goes to a ledger card), before compaction
(hook-pre-compact), at session start (hook-session-start), at each turn (hook-turn, hook-mirror, prompt_kind,
record_taken_in), and what they share: the turn log, reading a hook's stdin, the `@` pointers of a prompt, the
transcript rows of words a running turn took in. A hook never fails the session. Layer 4."""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import select
import stat
import sys
import urllib.parse

from .context import Context
from .discord import DiscordMirror
from .events.deliver import DELIVER_SENDER, HC_SENT, SLASH_COMMAND, Delivery, prompt_kind, row_time, unwrap_pasted
from .messaging.envelope import extract_env_id
from .messaging.mailbox import PENDING_TURN
from .events.stalls import StallWatcher
from .events.supervisor import format_occupation_hint
from .helpers.service import Helpers
from .home import project_slug
from .ledger.ledger import Ledger
from .ledger.question import strip_recommend_marker
from .ledger.task import task_number
from .manager.handover import handover_compact_text
from .manager.launch import pm_compact_instructions
from .manager.rotate import name_later
from .osutil import WINDOWS, shell_quote, unfailing
from .project.conversation import Conversation
from .project.project import ProjectRegistry
from .project.readmodel import IMAGE_MARK
from .project.turn_state import TurnTracker
from .store import DOCUMENT_ROOTS, StoreError, registration_slug, replace_task_file, valid_task_id, write_atomic
from .workers.sessions import remember_pm_session_for, remember_worker_session_for


def in_herdr_session(ctx):
    """A hook acts only in a session inside herdr: a pane of the herdr TUI (HERDR_ENV=1) or a herdr-core terminal."""
    return bool(ctx.pane) and (ctx.env.get("HERDR_ENV") == "1" or bool(ctx.hc_terminal))


def turn_log(text, *, ctx=None):
    """Append one line to the turn log; hooks must never fail, so failures are swallowed."""
    try:
        ctx = Context.from_env() if ctx is None else ctx
        ctx.home.root.mkdir(parents=True, exist_ok=True)
        with open(ctx.home.turn_log, "a") as f:
            f.write(f"{ctx.clock.now()} [{ctx.pane or '-'}] {text}\n")
    except OSError:
        pass


def read_hook_stdin():
    """Read a hook's JSON payload from stdin without blocking when stdin is empty or interactive."""
    if sys.stdin is None:
        return {}
    try:
        if sys.stdin.isatty():
            return {}
    except (AttributeError, OSError, ValueError):
        pass
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        fd = None
    if fd is not None and not WINDOWS:
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                ready, _, _ = select.select([fd], [], [], 0.1)
                if not ready:
                    return {}
        except (OSError, ValueError):
            pass
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


PM_QUESTION_TOOLS = frozenset({"AskUserQuestion", "request_user_input", "ask_user", "ask_question"})
PM_SHELL_TOOLS = frozenset({"Bash", "shell", "local_shell_call", "run_command", "execute_command", "terminal"})
WORKER_SUBPLAN_TOOLS = frozenset({
    "Edit", "Write", "MultiEdit", "NotebookEdit",
    "apply_patch", "write_file", "edit_file",
})

_QUOTED_STR_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_CMD_SPLIT_RE = re.compile(r"(?:&&|\|\||[;\n|])")
_SLEEP_CMD_RE = re.compile(r"^\s*(?:env\s+(?:\w+=\S+\s+)*)?sleep\s+(\d+(?:\.\d+)?)([smhd]?)\b", re.I)
_SSH_CMD_RE = re.compile(r"^\s*(?:env\s+(?:\w+=\S+\s+)*)?(?:ssh|scp|rsync)\s+\S+", re.I)
_PM_LAND_RE = re.compile(r"\bpm\.py\s+land\b")
_WAIT_CMD_RE = re.compile(r"\b(?:hc\s+wait|pm\.py\s+wait|pm\.py\s+helper\s+wait)\b")
_INSTALL_CMD_RE = re.compile(
    r"(?:\binstall\.py\b|\bsetup\.py\b|\b(?:npm|pnpm|yarn)\s+(?:ci|install)\b|\bpip3?\s+install\b|\bbrew\s+(?:install|upgrade)\b|\bcargo\s+(?:build|install)\b)",
    re.I,
)
_FULL_TEST_CMD_RE = re.compile(
    r"(?:\brun_checks\.py\b|\brender_check\.py\b|\bpytest\b|\bcargo\s+test\b|\b(?:npm|pnpm|yarn)\s+test\b|\bgo\s+test\b|\bpython3?\s+-m\s+unittest\b|\bnode\s+--test\b)",
    re.I,
)


def _strip_quoted_literals(cmd: str) -> str:
    """Replace quoted strings with empty quotes so words like `ssh` or `sleep 60` inside a log message don't trigger."""
    return _QUOTED_STR_RE.sub('""', cmd)


def detect_slow_pm_command(command: str) -> tuple[str, str] | None:
    """Classify a known slow foreground shell command in a coordinator session (§3.8 O-d, D2).

    Returns `(category, detail)` or `None` when the command looks fast/safe.
    """
    raw = str(command or "").strip()
    if not raw:
        return None
    unquoted = _strip_quoted_literals(raw)
    segments = [seg.strip() for seg in _CMD_SPLIT_RE.split(unquoted) if seg.strip()]
    for seg in segments:
        if _PM_LAND_RE.search(seg) and "--delegate" not in seg:
            return "pm_land", "pm.py land"
        if _WAIT_CMD_RE.search(seg):
            m = _WAIT_CMD_RE.search(seg)
            return "wait", m.group(0) if m else "wait"
        m_sleep = _SLEEP_CMD_RE.match(seg)
        if m_sleep:
            val = float(m_sleep.group(1))
            unit = (m_sleep.group(2) or "s").lower()
            mult = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}.get(unit, 1.0)
            if val * mult >= 10.0:
                return "long_sleep", f"sleep {m_sleep.group(1)}{m_sleep.group(2)}"
        if _SSH_CMD_RE.match(seg):
            first = seg.split(None, 1)[0]
            return "ssh", first
        if _INSTALL_CMD_RE.search(seg) and not ("setup.py" in seg and ("--status" in seg or "--dry-run" in seg)):
            m = _INSTALL_CMD_RE.search(seg)
            return "install", m.group(0) if m else "install"
        if _FULL_TEST_CMD_RE.search(seg):
            m = _FULL_TEST_CMD_RE.search(seg)
            return "test_suite", m.group(0) if m else "test suite"
    return None


def pm_slow_cmd_guard_mode(ctx) -> str:
    """Read `config.json` `pm.slow_cmd_guard` (`"warn"` default per D2, or `"deny"` / `"off"`)."""
    cfg = ctx.config.read() if ctx.config is not None else {}
    pm_cfg = cfg.get("pm") if isinstance(cfg, dict) and isinstance(cfg.get("pm"), dict) else {}
    mode = str(pm_cfg.get("slow_cmd_guard") or "warn").strip().lower()
    return mode if mode in ("warn", "deny", "off") else "warn"


def format_pm_slow_command_notice(category: str, detail: str, *, mode: str = "warn", ctx=None) -> str:
    """Build a concise warning or deny reason for a slow foreground command in a coordinator session (§3.8 O-d)."""
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    cmd = ctx.procs.pm_command()
    suggestions = {
        "pm_land": tr(
            f"Delegate merge asynchronously with `{cmd} approve <id>` instead of running `{detail}` in the PM foreground.",
            f"请用 `{cmd} approve <id>` 异步委派合并，不要在 PM 前台直接跑 `{detail}`。",
        ),
        "wait": tr(
            "Do not block the PM foreground waiting on workers; rely on automatic `deliver` notifications (or run in background).",
            "不要在 PM 前台同步等待；依赖 `deliver` 自动唤醒通知（或放到后台）。",
        ),
        "long_sleep": tr(
            "Avoid long `sleep` in the PM foreground; finish the turn and wait for events or delegate to a background helper.",
            "不要在 PM 前台长时间 `sleep`；先结束本轮等事件唤醒，或交给后台 helper。",
        ),
        "ssh": tr(
            f"Offload remote `{detail}` operations to an async exec helper (`{cmd} helper start --exec --async`) or run in background.",
            f"远程 `{detail}` 操作请交给异步 helper（`{cmd} helper start --exec --async`）或放后台运行。",
        ),
        "install": tr(
            f"Offload install/build (`{detail}`) to an async exec helper (`{cmd} helper start --exec --async`) or background job.",
            f"安装/构建（`{detail}`）请交给异步 helper（`{cmd} helper start --exec --async`）或放后台运行。",
        ),
        "test_suite": tr(
            f"Offload test execution (`{detail}`) to a worker or async helper (`{cmd} helper start --async`) instead of blocking the PM turn.",
            f"测试执行（`{detail}`）请交给 worker 或异步 helper（`{cmd} helper start --async`），不要卡住 PM 前台。",
        ),
    }
    advice = suggestions.get(category, tr(
        "Run slow commands in the background or delegate to a worker/helper to keep the PM responsive.",
        "耗时命令请放后台或委派给 worker/helper，保持 PM 前台随时接话。",
    ))
    if mode == "deny":
        return tr(
            f"Blocked slow foreground command (`{detail}`) in PM session (`pm.slow_cmd_guard=deny`). {advice}",
            f"PM 会话已拦截前台慢命令（`{detail}`，`pm.slow_cmd_guard=deny`）。{advice}",
        )
    return tr(
        f"[pm] Slow foreground command detected (`{detail}`). {advice}",
        f"[pm] 检测到 PM 前台慢命令（`{detail}`）。{advice}",
    )


def _extract_tool_questions(tool_input, *, tr=None):
    """Normalize Claude Code `AskUserQuestion` / Codex `request_user_input` tool_input into
    `[{"header": str, "question": str, "options": [(label, why, recommended), ...]}]`."""
    if not isinstance(tool_input, dict):
        return []
    raw_list = tool_input.get("questions")
    if not isinstance(raw_list, list) or not raw_list:
        q_text = str(tool_input.get("question") or tool_input.get("prompt") or "").strip()
        opts = tool_input.get("options") if isinstance(tool_input.get("options"), list) else []
        if not q_text and not opts:
            return []
        raw_list = [{"header": tool_input.get("header") or tool_input.get("title") or "",
                     "question": q_text, "options": opts}]
    out = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        q_text = str(item.get("question") or item.get("prompt") or "").strip()
        header = str(item.get("header") or item.get("title") or "").strip()
        if not header:
            short = " ".join(q_text.split())[:24].rstrip("？?：: ")
            header = short or (tr("Decision needed", "需要你确认") if tr else "Decision needed")
        opts = []
        for raw_opt in (item.get("options") if isinstance(item.get("options"), list) else []):
            if isinstance(raw_opt, dict):
                raw_label = str(raw_opt.get("label") or raw_opt.get("title") or raw_opt.get("text") or "").strip()
                why = str(raw_opt.get("description") or raw_opt.get("why") or "").strip()
                explicit_rec = bool(raw_opt.get("recommended"))
            elif isinstance(raw_opt, str):
                raw_label, why, explicit_rec = raw_opt.strip(), "", False
            else:
                continue
            label, marked = strip_recommend_marker(raw_label)
            if not label:
                continue
            opts.append((label, why, explicit_rec or marked))
        if q_text or opts:
            out.append({"header": header, "question": q_text or header, "options": opts})
    return out


def _append_question_options(parts, options, tr):
    """Append `--option`, `--why`, and `--recommend` flags for normalized question options."""
    rec_idx = next((i for i, (_, _, is_rec) in enumerate(options) if is_rec), None)
    for i, (label, why, _is_rec) in enumerate(options):
        opt_text = f"{label} {tr('(Recommended)', '（推荐）')}" if rec_idx is not None and i == rec_idx and rec_idx > 0 else label
        parts += ["--option", shell_quote(opt_text)]
        if why:
            parts += ["--why", shell_quote(why)]
    if rec_idx == 0:
        parts.append("--recommend")


def format_pm_question_redirect(tool_input, tool_name="AskUserQuestion", repo="", *, ctx=None):
    """Build the PreToolUse deny reason instructing the PM to post a ledger question card instead."""
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    cmd = ctx.procs.pm_command()
    questions = _extract_tool_questions(tool_input, tr=tr)
    commands = []
    for q in questions:
        parts = [cmd, "new", shell_quote(q["header"]), "--status", "blocked", "--note", shell_quote(q["question"])]
        _append_question_options(parts, q["options"], tr)
        commands.append(" ".join(parts))
    if not commands:
        commands.append(
            f'{cmd} new {shell_quote(tr("Decision needed", "需要你确认"))} --status blocked '
            f'--note {shell_quote(tr("<your question>", "<你的问题>"))} '
            f'--option {shell_quote(tr("<recommended option>", "<推荐选项>"))} '
            f'--why {shell_quote(tr("<why>", "<理由>"))} '
            f'--option {shell_quote(tr("<other option>", "<其他选项>"))} --recommend'
        )
    cmd_block = "\n".join(commands)
    return tr(
        f"Blocked `{tool_name}` in a PM session: questions to the user must go through the single ledger question-card "
        "channel so they appear in the project conversation (not hidden in the terminal TUI), survive compaction/swap, "
        "and let the user answer via card click, free text, or terminal.\n"
        f"Run this command now (or use `{cmd} update <task-id> --status blocked ...` if it belongs to an existing task):\n"
        f"{cmd_block}\n"
        "Then write a brief reply if needed and end your turn. Once the user replies, record the answer and close or "
        f"advance the task (`{cmd} update <id> --status done|in_progress --note \"<answer>\"`).",
        f"PM 会话里禁止直接调用 `{tool_name}`：向用户提问必须统一走台账问题卡，才能在项目对话里显示（而不是藏在终端里），"
        "且跨压缩/换会话不丢，用户既能在卡上点选或用自己的话答，也能在终端答。\n"
        f"请立即改用以下命令发出问题卡（若属于已有任务，把 `new \"...\"` 换成 `update <task-id>`）：\n"
        f"{cmd_block}\n"
        "发出后简短说明并结束本轮；等用户回复后，再运行 "
        f"`{cmd} update <id> --status done|in_progress --note \"<回答>\"` 关闭或推进任务。",
    )


def _active_worker_task(ctx):
    """Return the active (`in_progress`) task of a dispatched worker session, or None."""
    task = ctx.caller.own_task
    if isinstance(task, dict) and task.get("status") == "in_progress" and task.get("id"):
        return task
    if not ctx.pane:
        return None
    matches = [
        t for t in Ledger(ctx).raw_tasks()
        if t.get("pane") == ctx.pane and t.get("dispatched") and t.get("status") == "in_progress" and t.get("id")
    ]
    return matches[0] if len(matches) == 1 else None


def format_worker_question_redirect(task_id, tool_input, tool_name="AskUserQuestion", *, ctx=None):
    """Build the PreToolUse deny reason instructing a dispatched worker to post a ledger question card instead."""
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    cmd = ctx.procs.pm_command()
    questions = _extract_tool_questions(tool_input, tr=tr)
    commands = []
    for q in questions:
        parts = [cmd, "update", shell_quote(task_id), "--status", "blocked", "--note", shell_quote(q["question"])]
        _append_question_options(parts, q["options"], tr)
        commands.append(" ".join(parts))
    if not commands:
        commands.append(
            f'{cmd} update {shell_quote(task_id)} --status blocked '
            f'--note {shell_quote(tr("<your question>", "<你的问题>"))} '
            f'--option {shell_quote(tr("<recommended option>", "<推荐选项>"))} '
            f'--why {shell_quote(tr("<why>", "<理由>"))} '
            f'--option {shell_quote(tr("<other option>", "<其他选项>"))} --recommend'
        )
    cmd_block = "\n".join(commands)
    return tr(
        f"Blocked `{tool_name}` in a dispatched worker session: terminal-only interactive prompts do not appear in the "
        "Project conversation. Report `blocked` with a ledger question card instead so it shows up immediately in the "
        "Project view, enters \"Waiting on you\", and wakes you automatically once answered.\n"
        f"Run this command now:\n"
        f"{cmd_block}\n"
        "Then pause and wait for the answer.",
        f"派发 worker 会话里禁止直接调用 `{tool_name}`：终端交互菜单不会出现在 Project 主对话里。"
        "请改用台账问题卡报 `blocked`，问题会立刻显示在 Project 主对话并进入「Waiting on you」，用户点选回答后会自动唤醒你。\n"
        f"请立即运行以下命令：\n"
        f"{cmd_block}\n"
        "发出后暂停等待回复即可。",
    )


def worker_subplan_reminder(ctx):
    """Fallback reminder for a dispatched worker that starts editing/writing in `in_progress` without a `subplan`.
    Returns a short reminder line at most once per task (recording `subplan_reminded`), or None."""
    if not ctx.pane:
        return None
    ledger = Ledger(ctx)
    task = next(
        (t for t in ledger.raw_tasks()
         if t.get("pane") == ctx.pane and t.get("dispatched") and not t.get("review_of")
         and t.get("status") == "in_progress"),
        None,
    )
    if not task or task.get("subplan") or task.get("subplan_reminded") or task.get("land_approved"):
        return None
    tid = task.get("id")
    if not tid:
        return None
    reminded = False

    def _mark(cur, _ch):
        nonlocal reminded
        if cur is None:
            return None
        raw = cur.raw
        if raw.get("status") != "in_progress" or raw.get("subplan") or raw.get("subplan_reminded") or raw.get("land_approved"):
            return None
        raw["subplan_reminded"] = True
        reminded = True
        return raw

    ledger.change(tid, _mark, board=False)
    if not reminded:
        return None
    cmd = ctx.procs.pm_command()
    return ctx.config.tr(
        f"[pm] Reminder: record 3-8 verifiable sub-steps for {tid} with "
        f"`{cmd} update {tid} --plan \"[>] current; [ ] next\"` (silent write; skip for trivial single-step edits).",
        f"[pm] 提醒：请用 `{cmd} update {tid} --plan \"[>] 当前步; [ ] 下一步\"` 为任务 {tid} 写下 3~8 个可检验子步骤"
        "（静默落盘，不唤醒 PM；随手小活可忽略）。",
    )


def cmd_hook_pre_tool(a, ctx=None):
    """PreToolUse hook: in a registered PM session, deny built-in interactive user-question tools
    (`AskUserQuestion`, `request_user_input`, etc.) and redirect the PM to post a ledger question card;
    in a dispatched worker session, emit a one-time gentle reminder on the first edit/write tool call
    if no `subplan` has been recorded yet."""
    ctx = Context.from_env() if ctx is None else ctx
    if not in_herdr_session(ctx):
        return
    data = read_hook_stdin()
    field = lambda name: data[name] if isinstance(data.get(name), str) else ""
    tool_name = field("tool_name")
    if tool_name in PM_QUESTION_TOOLS:
        tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        rec = ctx.caller.own_pm_record(field("cwd") or None)
        if rec:
            reason = format_pm_question_redirect(tool_input, tool_name=tool_name, repo=rec.get("repo") or "", ctx=ctx)
        else:
            worker_task = _active_worker_task(ctx)
            if not worker_task:
                return
            reason = format_worker_question_redirect(worker_task["id"], tool_input, tool_name=tool_name, ctx=ctx)
        ctx.out.line(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }, ensure_ascii=False))
        return
    if tool_name in PM_SHELL_TOOLS:
        tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        if tool_input.get("run_in_background") is True:
            return
        rec = ctx.caller.own_pm_record(field("cwd") or None)
        if not rec:
            return
        guard_mode = pm_slow_cmd_guard_mode(ctx)
        if guard_mode == "off":
            return
        shell_cmd = str(tool_input.get("command") or tool_input.get("CommandLine") or tool_input.get("cmd") or "").strip()
        hit = detect_slow_pm_command(shell_cmd)
        if not hit:
            return
        category, detail = hit
        reason = format_pm_slow_command_notice(category, detail, mode=guard_mode, ctx=ctx)
        if guard_mode == "deny":
            ctx.out.line(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }, ensure_ascii=False))
        else:
            ctx.out.line(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": reason,
                }
            }, ensure_ascii=False))
        return
    if tool_name in WORKER_SUBPLAN_TOOLS:
        if ctx.caller.own_pm_record(field("cwd") or None):
            return
        def _subplan_remind():
            msg = worker_subplan_reminder(ctx)
            if msg:
                ctx.out.line(json.dumps({
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": msg,
                    }
                }, ensure_ascii=False))
        unfailing(_subplan_remind)


def cmd_hook_pre_compact(a, ctx=None):
    """PreCompact hook: emit PM preservation rules before compaction (Claude Code plain text, Codex JSON)."""
    ctx = Context.from_env() if ctx is None else ctx
    if getattr(a, "print_only", False):
        ctx.out.line(pm_compact_instructions())
        return
    if not in_herdr_session(ctx):
        return
    data = read_hook_stdin()
    field = lambda name: data[name] if isinstance(data.get(name), str) else ""
    rec = ctx.caller.own_pm_record(field("cwd") or None)
    if not rec:
        return
    instructions = pm_compact_instructions()
    if "turn_id" in data:
        ctx.out.line(json.dumps({"continue": True, "systemMessage": instructions}, ensure_ascii=False))
    else:
        ctx.out.line(instructions)


def helper_session_start(*, ctx=None):
    """SessionStart hook branch for a helper terminal: remind it of its helper role and return True."""
    ctx = Context.from_env() if ctx is None else ctx
    msg = Helpers(ctx).session_start_message()
    if msg is None:
        return False
    ctx.out.line(msg)
    return True


def helper_stopped(data, *, ctx=None):
    """Stop hook for a Claude Code or Codex helper that ended its turn without running `pm.py helper done`."""
    ctx = Context.from_env() if ctx is None else ctx
    res = Helpers(ctx).handle_stop_hook(data)
    if res.block_payload is not None:
        ctx.out.line(json.dumps(res.block_payload, ensure_ascii=False))


def cmd_hook_session_start(a, ctx=None):
    """SessionStart hook: tell a session inside herdr whether a PM exists, or sync disk state after compaction."""
    ctx = Context.from_env() if ctx is None else ctx
    if not in_herdr_session(ctx):
        return
    if helper_session_start(ctx=ctx):
        return
    pm = ProjectRegistry(ctx).find_pm()
    if not pm:
        # A restarted PM loses its herdr name; restore it from the registration for this pane.
        rec = ctx.caller.own_pm_record()
        if rec and not rec.get("archived") and ctx.tui.agent_rename(ctx.pane, rec["name"]):
            pm = {"pane_id": ctx.pane, "name": rec["name"]}
        elif rec and not rec.get("archived") and ctx.caller.in_tui():
            name_later(ctx.pane, rec["name"], ctx=ctx)  # too early: herdr does not see this agent in its pane yet
            pm = {"pane_id": ctx.pane, "name": rec["name"]}
        else:
            unfailing(remember_worker_session_for, ctx)
            return
    if pm["pane_id"] == ctx.pane:
        data = read_hook_stdin()
        field = lambda name: data[name] if isinstance(data.get(name), str) else ""
        rec = ctx.caller.own_pm_record(field("cwd") or None)
        repo = (rec or {}).get("repo") or ""
        pslug = registration_slug(rec) or (ctx.store.folder_project_slug(repo) if repo else "")
        if rec and (field("transcript_path") or field("session_id")):
            unfailing(remember_pm_session_for, ctx, rec, field("transcript_path"), field("session_id"))
        is_compact = bool(getattr(a, "compact", False) or field("source") == "compact")
        target = pslug or repo
        if is_compact and target:
            ctx.out.line(handover_compact_text(target, ctx=ctx))
        else:
            ctx.out.line(f"You are {pm.get('name')}, the PM for this project (pm skill). Ledger board: {ctx.home.board}. "
                         "If you have not read it in this session, run `pm.py handover` before anything else.")
        if repo or pslug:
            Delivery(ctx, repo, slug=pslug or None).ensure_running()  # events that came while no PM ran
        return
    unfailing(remember_worker_session_for, ctx)
    ctx.out.line(f"A PM coordinator ({pm.get('name')}) runs in {pm['pane_id']}. Before implementing a non-trivial change, "
                 "load the pm skill: register the task in the ledger (or hand it to the PM if the user asks), "
                 "and mark it `review` when it is ready to merge.")


MENTION_RE = re.compile(r"\[@([^\]\n]+)\]\((thread|library|file|session):([^)\s\n]+)\)")
_MENTION_LEGACY_ROOTS = {
    "project": "docs",
    "user": "personal",
}


def extract_mentions(text):
    """Return deduplicated `(scheme, target, label)` tuples for `@` pointer links in `text`."""
    out = []
    seen = set()
    for m in MENTION_RE.finditer(text or ""):
        label = m.group(1).strip()
        scheme = m.group(2)
        try:
            target = urllib.parse.unquote(m.group(3))
        except Exception:
            continue
        if not target or (scheme, target) in seen:
            continue
        seen.add((scheme, target))
        out.append((scheme, target, label))
    return out


def mention_hints(repo, text, slug=None, *, ctx=None):
    """Concise resolution lines for `@` pointers in a user prompt, for PM session context."""
    ctx = Context.from_env() if ctx is None else ctx
    mentions = extract_mentions(text)
    if not mentions:
        return []
    slug = slug or (project_slug(repo) if repo else "")
    ledger = Ledger(ctx)
    lines = []
    for scheme, target, _label in mentions:
        if scheme == "thread":
            resolved_tid = ledger.try_resolve_id(target) or target
            task = ctx.store.task(resolved_tid) if valid_task_id(resolved_tid) else None
            if isinstance(task, dict):
                num = task_number(task)
                num_part = f"#{num}; " if num else ""
                title = task.get("title") or resolved_tid
                status = task.get("status") or "in_progress"
                branch = task.get("branch") or "-"
                pane = task.get("pane") or "-"
                lines.append(f"thread:{resolved_tid} ({num_part}{title}; status={status}, branch={branch}, pane={pane})")
            else:
                lines.append(f"thread:{target}")
        elif scheme == "library":
            root, slash, rel = target.partition("/")
            if not slash or not rel or ".." in rel.split("/") or rel.startswith("/"):
                lines.append(f"library:{target}")
                continue
            if root == "project" and rel.startswith("memory/"):
                root, rel = "memory", rel[len("memory/"):]
            else:
                root = _MENTION_LEGACY_ROOTS.get(root, root)
            if root not in DOCUMENT_ROOTS or root == "repo":
                continue
            resolved = None
            if slug:
                with contextlib.suppress(OSError, ValueError, StoreError):
                    resolved, _ = ctx.store.document_path(slug, root, rel)
            if resolved is not None:
                lines.append(f"library:{root}/{rel} -> {resolved}")
            elif slug:
                lines.append(f"library:{root}/{rel} (read via pm.py project file {slug} --root {root} -- {rel})")
            else:
                lines.append(f"library:{root}/{rel}")
        elif scheme == "file":
            parts = target.split("/")
            if target.startswith("/") or "\\" in target or any(p in ("", ".", "..", ".git") for p in parts):
                continue
            if repo:
                repo_path = Path(repo)
                joined = repo_path / target
                try:
                    repo_real = repo_path.resolve()
                    cand_real = joined.resolve()
                    if cand_real == repo_real or repo_real in cand_real.parents:
                        lines.append(f"file:{target} -> {joined}")
                    else:
                        lines.append(f"file:{target}")
                except OSError:
                    lines.append(f"file:{target} -> {joined}")
            else:
                lines.append(f"file:{target}")
        elif scheme == "session":
            lines.append(f"session:{target}")
    return lines


def emit_mention_hints(repo, text, slug=None, *, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    lines = mention_hints(repo, text, slug=slug, ctx=ctx)
    if lines:
        ctx.out.line("[mentions]")
        for line in lines:
            ctx.out.line(f"- {line}")


def taken_in(row):
    """The words in a transcript row of words a running turn took in: Claude Code writes them as an attachment of
    type queued_command, and no hook sees them. (words, prompt as written, who sent them: origin.kind) or None.
    Words with pictures are a list of blocks: their text, and a picture the text does not mark is an "[Image #N]"
    mark before it, as a prompt of Claude Code's has it. A finished background task and a shell command (`!`) are no
    words; neither is a row without them."""
    attachment = row.get("attachment") if row.get("type") == "attachment" else None
    if not isinstance(attachment, dict) or attachment.get("type") != "queued_command":
        return None
    origin = attachment.get("origin") if isinstance(attachment.get("origin"), dict) else {}
    if attachment.get("commandMode") not in (None, "", "prompt") or origin.get("kind") == "task-notification":
        return None
    prompt = attachment.get("prompt")
    if isinstance(prompt, list):
        blocks = [b for b in prompt if isinstance(b, dict)]
        words = "\n".join(str(b.get("text") or "") for b in blocks
                          if b.get("type") == "text" and str(b.get("text") or "").strip())
        missing = sum(b.get("type") == "image" for b in blocks) - len(IMAGE_MARK.findall(words))
        words = " ".join([f"[Image #{n}]" for n in range(1, missing + 1)] + ([words] if words.strip() else []))
    elif isinstance(prompt, str):
        words = prompt
    else:
        return None
    return words.strip(), str(prompt if isinstance(prompt, str) else words).strip(), str(origin.get("kind") or "")


def prompt_row(row):
    """Whether a transcript row is a prompt that started a turn: words of a user row that Claude Code did not add
    itself, not tool results and not a compact summary."""
    if (row.get("type") != "user" or row.get("isMeta")
            or row.get("isCompactSummary") or row.get("isVisibleInTranscriptOnly")):
        return False
    content = (row.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return any(isinstance(b, dict) and b.get("type") == "text" and str(b.get("text") or "").strip()
               for b in content or [])


def _transcript_has_newer_prompt(path: Path) -> bool:
    """True when the trailing 64 KiB of a Claude/Codex transcript shows a user prompt after the last assistant row."""
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size <= 0:
        return False
    start = max(0, size - 65_536)
    try:
        with open(path, "rb") as f:
            f.seek(start)
            raw = f.read(65_536)
    except OSError:
        return False
    nl = raw.rfind(b"\n")
    if nl < 0:
        return False
    lines = raw[:nl].split(b"\n")
    if start > 0 and lines:
        lines = lines[1:]
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("isSidechain"):
            continue
        if prompt_row(row):
            return True
        if row.get("type") == "assistant":
            return False
        payload = row.get("payload")
        if row.get("type") in ("response_item", "event_msg") and isinstance(payload, dict):
            ptype = str(payload.get("type") or "")
            if ptype in ("user_message", "turn_started"):
                return True
            if ptype in ("agent_message", "task_complete", "turn_complete"):
                return False
    return False


def _stop_expected_seq(tracker: TurnTracker, data: dict, transcript: str) -> int | None:
    """Resolve the `turn_seq` that this `Stop` hook is closing so a late async `Stop` cannot close a newer turn (FS-9)."""
    raw_seq = data.get("turn_seq")
    if isinstance(raw_seq, int) and not isinstance(raw_seq, bool) and raw_seq > 0:
        return raw_seq
    st = tracker.read()
    cur_seq = int(st.get("turn_seq") or 0)
    if cur_seq <= 0:
        return None
    sid = data.get("session_id") if isinstance(data.get("session_id"), str) else ""
    if sid:
        s_turns = st.get("session_turns") or {}
        if sid in s_turns:
            sid_seq = int(s_turns.get(sid) or 0)
            if 0 < sid_seq < cur_seq:
                return sid_seq
    if transcript and cur_seq > 1 and _transcript_has_newer_prompt(Path(transcript)):
        return cur_seq - 1
    return cur_seq


def cmd_hook_turn(a, ctx=None):
    """UserPromptSubmit/Stop hook of a PM session: keep the project's conversation log and note the turn for
    the board."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    field = lambda name: data[name] if isinstance(data.get(name), str) else ""  # a field of another type is none
    event = field("hook_event_name")
    rec = ctx.caller.own_pm_record(field("cwd") or None)
    if event in ("AgentStart", "ToolStart", "ToolEnd") and rec:
        repo = rec.get("repo") or ""
        if repo:
            tracker = TurnTracker(ctx, repo)
            if event == "AgentStart":
                unfailing(
                    lambda: tracker.begin_turn(
                        terminal=ctx.pane,
                        agent_kind="pi",
                        cause="user",
                        session_id=field("session_id"),
                        from_hook=True,
                    )
                )
            elif event == "ToolStart":
                unfailing(
                    lambda: tracker.note_activity(
                        kind="tool",
                        tool=field("tool_name") or "tool",
                        summary=field("tool_summary"),
                        src="hook:pi",
                    )
                )
            else:
                unfailing(lambda: tracker.note_activity(kind="thinking", src="hook:pi"))
        return
    if not rec and event in ("UserPromptSubmit", "Stop"):
        unfailing(remember_worker_session_for, ctx, field("transcript_path"), field("session_id"), field("cwd"))
    if event == "Stop" and not rec:
        def _worker_stopped():
            payload = StallWatcher(ctx).worker_stopped(data)
            if payload is not None:
                ctx.out.line(json.dumps(payload, ensure_ascii=False))
        unfailing(_worker_stopped)
        unfailing(helper_stopped, data, ctx=ctx)
    if event not in ("UserPromptSubmit", "Stop") or not rec:
        return
    repo = rec.get("repo") or ""
    pslug = registration_slug(rec) or (ctx.store.folder_project_slug(repo) if repo else "")
    transcript = field("transcript_path")
    session_id = field("session_id")
    unfailing(remember_pm_session_for, ctx, rec, transcript, session_id)
    delivery = Delivery(ctx, repo, slug=pslug or None) if (repo or pslug) else None
    conv = Conversation(ctx, repo, slug=pslug or None) if (repo or pslug) else None
    tracker = TurnTracker(ctx, repo, slug=pslug or None) if (repo or pslug) else None
    mirror = DiscordMirror(ctx)
    if delivery is not None:
        unfailing(delivery.ensure_running)  # a desktop-app PM's deliverer: started again if none runs
    if event == "UserPromptSubmit":
        # What a UserPromptSubmit hook prints is added to the session's context.
        raw = field("prompt").strip()
        kind, sender, prompt = prompt_kind(raw)
        consumed_ui = False
        matched_ids: list[str] = []
        unlogged_prompt = prompt
        if kind == "user" and tracker is not None and prompt:
            consumed_ui, matched_ids, unlogged_prompt = tracker.consume_ui_prompt(prompt)
        if repo or pslug:
            # Words a turn took in while it worked and that no Stop hook recorded (the user stopped that turn):
            # before this prompt, where they were said. Bounded to 512 KiB on synchronous UserPromptSubmit so a
            # multi-MB transcript never hits the 15s hook timeout. They belong to that earlier turn (the newest one
            # so far: this prompt's turn has not begun), and are settled with it when it has closed already.
            prev_seq = 0
            if tracker is not None:
                try:
                    prev_seq = int(tracker.read().get("turn_seq") or 0)
                except Exception:  # noqa: BLE001
                    prev_seq = 0
            unfailing(record_taken_in, rec, transcript, False, raw, ctx=ctx, max_scan_bytes=512 << 10,
                      turn_seq=prev_seq or None)
            if tracker is not None and prev_seq:
                unfailing(tracker.settle_turn_if_closed, prev_seq)
        if kind == "rotate":
            return  # the takeover prompt: nothing the user should read about
        if kind == "supervisor":
            if tracker is not None:
                def _begin_sup() -> None:
                    env_hit = extract_env_id(raw)
                    orig_cause = ""
                    orig_mids: list[str] = []
                    orig_batch: list[int] | None = None
                    if env_hit and tracker.files.pm_mailbox.is_dir():
                        it = tracker.pm_mailbox.get(env_hit)
                        if it is not None:
                            eb = it.envelope.body if isinstance(it.envelope.body, dict) else {}
                            ec = it.envelope.cause if isinstance(it.envelope.cause, dict) else {}
                            orig_cause = str(eb.get("original_cause") or ec.get("original_cause") or "")
                            orig_mids = [str(m) for m in (eb.get("msg_ids") or ec.get("msg_ids") or []) if m]
                            if it.state in ("typed", "accepted"):
                                tracker.pm_mailbox.transition(
                                    env_hit, "consumed", turn_id=PENDING_TURN, clear_intent=True,
                                )
                    st_inc = tracker.read().get("incident") if tracker.files.pm_turn.is_file() else None
                    if isinstance(st_inc, dict):
                        if not orig_cause:
                            orig_cause = str(st_inc.get("cause_kind") or "")
                        if not orig_mids:
                            orig_mids = [str(m) for m in (st_inc.get("msg_ids") or []) if m]
                        if isinstance(st_inc.get("batch"), list) and len(st_inc["batch"]) == 2:
                            orig_batch = [int(st_inc["batch"][0]), int(st_inc["batch"][1])]
                    eff_cause = orig_cause if orig_cause in ("user", "deliver") else "recovery"
                    tseq = int(tracker.begin_turn(
                        terminal=ctx.pane,
                        agent_kind=str(rec.get("agent") or "claude"),
                        cause=eff_cause,
                        msg_ids=orig_mids or None,
                        batch=orig_batch,
                        session_id=session_id,
                        from_hook=True,
                    ) or 0)
                    tracker.bind_turn_to_consumed(f"seq:{tseq}" if tseq > 0 else session_id, turn_seq=tseq)

                unfailing(_begin_sup)
            return  # supervisor continuation prompt: do not log as a fake agent event
        if kind == "batch":
            if delivery is not None:
                def _took():
                    receipt = delivery.took_delivery(prompt)
                    if tracker is not None:
                        tseq = int(tracker.begin_turn(
                            terminal=ctx.pane,
                            agent_kind=str(rec.get("agent") or "claude"),
                            cause="deliver",
                            batch=[receipt.start, receipt.end],
                            session_id=session_id,
                            from_hook=True,
                        ) or 0)
                        turn_ref = f"seq:{tseq}" if tseq > 0 else session_id
                        tracker.bind_turn_to_consumed(turn_ref, turn_seq=tseq)
                    if receipt.warning:
                        ctx.out.line(receipt.warning)
                unfailing(_took)
            return  # its events are in the log already
        if delivery is not None:
            def _bring():
                # Print and flush pending batch BEFORE committing ack_delivery so a hook timeout never swallows a batch.
                peeked = delivery.peek_pending(include_git_state=False)
                if peeked is not None:
                    b_start, b_end, text_out = peeked
                    if text_out:
                        ctx.out.line(text_out)
                        with contextlib.suppress(Exception):
                            sys.stdout.flush()
                    delivery.ack_delivery(b_start, b_end)
            unfailing(_bring)
        if kind == "agent":
            if tracker is not None:
                unfailing(
                    lambda: tracker.begin_turn(
                        terminal=ctx.pane, agent_kind=str(rec.get("agent") or "claude"),
                        cause="agent", session_id=session_id, from_hook=True,
                    )
                )
            if conv is not None and prompt:
                conv.record("agent", by=sender, text=prompt)
                mirror.mirror(rec, f"**{sender}**\n{prompt}")
            return
        if kind != "user":
            return  # task notifications, slash commands
        if tracker is not None:
            def _begin_user_turn() -> None:
                tseq = tracker.begin_turn(
                    terminal=ctx.pane, agent_kind=str(rec.get("agent") or "claude"),
                    cause="user", msg_ids=matched_ids, session_id=session_id, from_hook=True,
                )
                tracker.bind_turn_to_consumed(f"seq:{tseq}" if tseq > 0 else session_id, turn_seq=tseq)

            unfailing(_begin_user_turn)
        if tracker is not None:
            def _emit_occ_hint():
                hint_data = tracker.consume_occupation_hint()
                if hint_data:
                    ctx.out.line(format_occupation_hint(ctx, hint_data))
            unfailing(_emit_occ_hint)
        if conv is not None:
            if not consumed_ui and unlogged_prompt:
                conv.record("user", text=unlogged_prompt)
            rec_slug = rec.get("name", "")[3:] if isinstance(rec.get("name"), str) and rec["name"].startswith("pm-") and ctx.store.has_project(rec["name"][3:]) else ""
            unfailing(emit_mention_hints, repo, prompt, rec_slug or None, ctx=ctx)
        if not consumed_ui and unlogged_prompt:
            mirror.mirror(rec, f"**你**\n{unlogged_prompt}")
    else:
        # Capture the turn sequence BEFORE slow transcript scans (`record_taken_in`) so a newer turn starting
        # while this async Stop hook runs cannot be closed or stripped of its cause (FS-9).
        expected_seq = _stop_expected_seq(tracker, data, transcript) if tracker is not None else None
        # Words that came in while the turn worked are recorded first, so they stand before the turn's reply.
        if repo:
            # ... and belong to the turn ending now, so its closure settles them (G5) like what started it.
            unfailing(record_taken_in, rec, transcript, True, ctx=ctx, turn_seq=expected_seq)
        # The agent's Stop hook carries the final message of the turn (Claude Code and Codex name it so).
        reply = field("last_assistant_message").strip()
        cause_fields: dict[str, object] = {}
        if tracker is not None:
            # Closing the turn also settles what it read (G5, `TurnTracker._settle_closed_turn`), as every other
            # closing path does (agy transcript, hc back to idle, an Esc).
            cause_fields = tracker.end_turn(expected_seq=expected_seq, has_reply=bool(reply))
            # The supervisor may have closed the turn on hc idle before this hook caught up with what it read.
            unfailing(tracker.settle_turn_if_closed, expected_seq)
        if not cause_fields and conv is not None:
            cause_fields = conv.turn_cause()
        if conv is not None and reply:
            # `by`: which session spoke, so the project view can tell this PM's ledger entries from a worker's.
            # `after`: a turn that a delivered batch started answers that batch, not the user (turn_cause).
            pane = ctx.pane
            conv.record("pm", text=reply, **({"by": pane} if pane else {}), **cause_fields)
        sweep_target = pslug or repo
        if sweep_target:
            unfailing(lambda: ProjectRegistry(ctx).app_pm(sweep_target) and StallWatcher(ctx).sweep_exited(sweep_target))
        if reply and rec.get("discord") and mirror.is_on() and not mirror.replied_on_discord(transcript):
            mirror.mirror(rec, f"**{rec['name']}**\n{reply}")
        return


cmd_hook_mirror = cmd_hook_turn  # the name earlier installs put in their hooks


TAKEN_IN_TAIL = 4 << 20  # bytes at the end of a transcript read when the mark does not say where to go on from
TAKEN_IN_MORE = 32 << 20  # bytes read on from the mark: a turn that wrote more is read from the end, as with no mark
TAKEN_IN_KEYS = 200      # ids of rows (two a row) the mark remembers as done
TAKEN_IN_FILES = 8       # transcripts the mark remembers how far it has read: a rotation's old and new session, say


def record_taken_in(rec, transcript, ended, prompt="", *, ctx=None, max_scan_bytes=None, turn_seq=None):
    """Record in the conversation log the words a turn of this PM session took in while it worked (taken_in): the
    user's, another agent's, a delivered batch. No hook sees them come; the turn hook catches up with them in the
    session's transcript, at Stop (ended) before the turn's reply, and at the next UserPromptSubmit for a turn that
    ended with no Stop hook (the user stopped it). Each is recorded as prompt_kind says a prompt of the same words
    is, with the time it was said: the user's as `user`, another agent's as `agent`, a batch moves the delivered mark
    (took_delivery), the rest not at all. What a prompt also gets that cannot be done here: nothing is printed (it
    no longer reaches the PM, and a Stop hook's output is not read), so no rotation reminder and no pending events
    (bring_pending); a turn the user spoke into answers the user (turn-cause.json goes, as bring_pending does).

    The mark, projects/<project>/taken-in.json: for each of the last transcripts read (TAKEN_IN_FILES), the byte read
    up to and the newest row's time seen in it; the newest time seen in any; the keys of the last rows done. A row is
    done once: in a transcript the mark knows, it is new only when no earlier than that transcript's time and not among
    those keys. A transcript the mark does not know (the first turn after this was installed, a lost or broken mark,
    a resumed or compacted session in a file of its own, a session that was no PM before) brings back nothing of an
    earlier turn: at Stop only the words of the turn ending now count, from the prompt that started it and no earlier
    than the newest time seen in any transcript; at UserPromptSubmit none. Only the end of a transcript is read then
    (TAKEN_IN_TAIL), never a whole long one; in a known one, what came after the mark (up to TAKEN_IN_MORE). No time
    the mark keeps is later than now, so a broken file or a clock that was ahead holds no words back.
    prompt: this UserPromptSubmit hook's prompt: a row of the same words written just now is its, so it is not
    recorded here as well; so is a line already in the log with the same words said within seconds of them.
    turn_seq: the turn that took these words in; what they match in the PM mailbox is bound to it (read by that
    turn), so that turn's closure settles it instead of the next turn's."""
    ctx = Context.from_env() if ctx is None else ctx
    repo = rec.get("repo") or ""
    pslug = registration_slug(rec) or (ctx.store.folder_project_slug(repo) if repo else "")
    if (not repo and not pslug) or not transcript or not isinstance(transcript, str):
        return
    path, key = Path(transcript), str(Path(transcript))
    try:
        size = path.stat().st_size
    except (OSError, ValueError):
        return
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    near = datetime.timedelta(seconds=5)
    proj_dir = ctx.home.project_for(pslug or repo).ensure()
    mark_path = proj_dir / "taken-in.json"
    try:
        mark = json.loads(mark_path.read_text())
    except (OSError, ValueError):
        mark = {}
    mark = mark if isinstance(mark, dict) else {}

    def kept(stamp):  # a time the mark keeps: none from the future
        t = row_time(stamp)
        return t if t and t <= now_utc + datetime.timedelta(minutes=1) else None
    keys = [k for k in mark.get("keys") or [] if isinstance(k, str)] if isinstance(mark.get("keys"), list) else []
    files = {f: v for f, v in mark["files"].items() if isinstance(v, dict)} if isinstance(mark.get("files"), dict) else {}
    seen = files.get(key) or {}
    floor = kept(seen.get("at"))
    start = seen.get("offset") if floor else None
    more_cap = TAKEN_IN_MORE if max_scan_bytes is None else min(TAKEN_IN_MORE, int(max_scan_bytes))
    tail_cap = TAKEN_IN_TAIL if max_scan_bytes is None else min(TAKEN_IN_TAIL, int(max_scan_bytes))
    if not isinstance(start, int) or isinstance(start, bool) or not 0 <= start <= size or size - start > more_cap:
        start, whole = max(0, size - tail_cap), False
    else:
        whole = True  # going on from a line's end
    try:
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read(size - start)
    except OSError:
        return
    complete = data[:data.rfind(b"\n") + 1]  # a half-written last line waits for the next look
    lines = complete.split(b"\n")[:-1]
    if not whole and start > 0 and lines:
        lines = lines[1:]  # the end of a line read from its middle
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and not row.get("isSidechain"):
            rows.append((row, row_time(row.get("timestamp"))))
    # A row written while the clock was ahead holds no later words back.
    times = [t for _, t in rows if t]
    newest = min(max(times), now_utc) if times else None
    if floor is None:
        # Not a transcript the mark knows: the turn ending now only, from the prompt that started it (without that
        # prompt in view, nothing), and nothing an earlier turn of any session took in.
        floor = next((t for row, t in reversed(rows) if t and prompt_row(row)), None) if ended else None
        overall = kept(mark.get("at"))
        if floor and overall and overall > floor:
            floor = overall
        seen_at = newest or now_utc
    else:
        seen_at = max(floor, newest) if newest else floor
    found = []
    for row, t in rows:
        words = taken_in(row)
        attachment = row.get("attachment")
        t = t or (row_time(attachment.get("timestamp")) if words else None)
        if not words or not t:
            continue
        # A copy of the row (a resumed or compacted session) may get an id of its own; what it carries keeps its own.
        ids = [str(i) for i in (row.get("uuid"), attachment.get("source_uuid")) if i] or [
            hashlib.sha1(json.dumps(row, sort_keys=True).encode()).hexdigest()]
        if any(i in keys for i in ids):
            continue
        keys += ids
        if floor is not None and t >= floor:
            said = min(row_time(attachment.get("timestamp")) or t, now_utc)
            found.append((words, said, min(t, now_utc)))
    if prompt:  # the newest row of this hook's own prompt, written just now, is the hook's
        own = next((i for i in range(len(found) - 1, -1, -1) if found[i][0][1] == prompt.strip()
                    and max(found[i][1], found[i][2]) >= now_utc - near), None)
        if own is not None:
            found.pop(own)
    files.pop(key, None)
    files[key] = {"offset": start + len(complete), "at": seen_at.isoformat()}
    overall = max([t for t in (kept(mark.get("at")), newest) if t], default=None)
    fresh = {"files": dict(list(files.items())[-TAKEN_IN_FILES:]), "at": overall.isoformat() if overall else None,
             "keys": keys[-TAKEN_IN_KEYS:]}
    if fresh != mark:
        try:
            write_atomic(mark_path, (json.dumps(fresh) + "\n").encode("utf-8"), replace_fn=replace_task_file)
        except OSError:
            pass
    if not found:
        return
    conv = Conversation(ctx, repo, slug=pslug or None)
    delivery = Delivery(ctx, repo, slug=pslug or None)
    tracker = TurnTracker(ctx, repo, slug=pslug or None)
    mirror = DiscordMirror(ctx)
    turn_ref = f"seq:{int(turn_seq)}" if turn_seq else ""
    local = lambda t: t.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    logged, used = conv.events(), set()
    for (words, _, origin), said, written in found:
        kind, sender, text = prompt_kind(words)
        if kind == "user" and origin == "peer":
            kind, sender = "agent", "peer"  # another agent's message that names no sender
        if kind == "batch":
            unfailing(delivery.took_delivery, text, True, turn_id=turn_ref)
            continue
        if kind not in ("user", "agent") or not text:
            continue
        if kind == "user":
            consumed_ui, matched_ids, remainder = tracker.consume_ui_prompt(text, turn_id=turn_ref)
            if consumed_ui:
                continue
            text = remainder or text
        # Recorded already, by a hook that saw these words come in (should Claude Code fire one for them): a line of
        # the same words from within seconds of when they were said or written. Either kind: a hook takes another
        # agent's words that name no sender (origin "peer") for the user's. Not one from long after: the user said
        # them again (a late Stop of a session that has been replaced).
        early, late = local(min(said, written) - near), local(max(said, written) + near)
        same = next((i for i, e in enumerate(logged) if i not in used and e.get("type") in ("user", "agent")
                     and str(e.get("text") or "") == text and early <= str(e.get("at") or "") <= late), None)
        if same is not None:
            used.add(same)
            continue
        if kind == "agent":
            conv.record("agent", at=local(said), by=sender, text=text)
            unfailing(mirror.mirror, rec, f"**{sender}**\n{text}")
        else:
            (proj_dir / "turn-cause.json").unlink(missing_ok=True)
            conv.record("user", at=local(said), text=text)
            unfailing(mirror.mirror, rec, f"**你**\n{text}")


def register_hook_commands(sub):
    hss = sub.add_parser("hook-session-start")
    hss.add_argument("--compact", action="store_true", help="emit post-compaction live disk sync")
    hpc = sub.add_parser("hook-pre-compact", help="PreCompact hook: print PM compaction preservation instructions")
    hpc.add_argument("--print", dest="print_only", action="store_true",
                     help="print the preservation instructions unconditionally")
    sub.add_parser("hook-pre-tool", help="PreToolUse hook: redirect PM interactive user-question tools to ledger question cards")
    sub.add_parser("hook-turn")
    sub.add_parser("hook-mirror")  # earlier installs
