"""The hooks an agent runs: before a tool (hook-pre-tool: a PM's question goes to a ledger card), before compaction
(hook-pre-compact), at session start (hook-session-start), at each turn (hook-turn, hook-mirror, prompt_kind,
record_taken_in), and what they share: the turn log, reading a hook's stdin, the `@` pointers of a prompt, the
transcript rows of words a running turn took in. A hook never fails the session. Layer 4."""
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
from .events.deliver import DELIVER_SENDER, Delivery, unwrap_pasted
from .events.stalls import StallWatcher
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
from .store import DOCUMENT_ROOTS, StoreError, replace_task_file, valid_task_id, write_atomic
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


def format_pm_question_redirect(tool_input, tool_name="AskUserQuestion", repo="", *, ctx=None):
    """Build the PreToolUse deny reason instructing the PM to post a ledger question card instead."""
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    cmd = ctx.procs.pm_command()
    questions = _extract_tool_questions(tool_input, tr=tr)
    commands = []
    for q in questions:
        parts = [cmd, "new", shell_quote(q["header"]), "--status", "blocked", "--note", shell_quote(q["question"])]
        rec_idx = next((i for i, (_, _, is_rec) in enumerate(q["options"]) if is_rec), None)
        for i, (label, why, _is_rec) in enumerate(q["options"]):
            opt_text = f"{label} {tr('(Recommended)', '（推荐）')}" if rec_idx is not None and i == rec_idx and rec_idx > 0 else label
            parts += ["--option", shell_quote(opt_text)]
            if why:
                parts += ["--why", shell_quote(why)]
        if rec_idx == 0:
            parts.append("--recommend")
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


def cmd_hook_pre_tool(a, ctx=None):
    """PreToolUse hook: in a registered PM session, deny built-in interactive user-question tools
    (`AskUserQuestion`, `request_user_input`, etc.) and redirect the PM to post a ledger question card."""
    ctx = Context.from_env() if ctx is None else ctx
    if not in_herdr_session(ctx):
        return
    data = read_hook_stdin()
    field = lambda name: data[name] if isinstance(data.get(name), str) else ""
    tool_name = field("tool_name")
    if tool_name not in PM_QUESTION_TOOLS:
        return
    rec = ctx.caller.own_pm_record(field("cwd") or None)
    if not rec:
        return
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    reason = format_pm_question_redirect(tool_input, tool_name=tool_name, repo=rec.get("repo") or "", ctx=ctx)
    ctx.out.line(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


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
        if rec and (field("transcript_path") or field("session_id")):
            unfailing(remember_pm_session_for, ctx, rec, field("transcript_path"), field("session_id"))
        is_compact = bool(getattr(a, "compact", False) or field("source") == "compact")
        if is_compact and repo:
            ctx.out.line(handover_compact_text(repo, ctx=ctx))
        else:
            ctx.out.line(f"You are {pm.get('name')}, the PM for this project (pm skill). Ledger board: {ctx.home.board}. "
                         "If you have not read it in this session, run `pm.py handover` before anything else.")
        if repo:
            Delivery(ctx, repo).ensure_running()  # events that came while no PM ran
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


def row_time(stamp):
    """A time in a transcript as an aware datetime, or None: ISO 8601 (Claude Code writes UTC, "…Z"; one without a
    zone is read as UTC) or a count of ms (or s) since the epoch."""
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        try:
            return datetime.datetime.fromtimestamp(stamp / 1000 if stamp > 1e11 else stamp, datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    m = re.fullmatch(r"(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?", str(stamp or "").strip())
    if not m:
        return None
    try:
        t = datetime.datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    zone, tz = m.group(4) or "Z", datetime.timezone.utc
    if zone != "Z":
        minutes = int(zone[1:3]) * 60 + int(zone[-2:])
        tz = datetime.timezone(datetime.timedelta(minutes=-minutes if zone[0] == "-" else minutes))
    return t.replace(microsecond=int(((m.group(3) or "") + "000000")[:6]), tzinfo=tz)


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


SLASH_COMMAND = re.compile(r"/[\w:.-]+(\s|$)")  # "/compact", not a path such as "/Users/me/shot.png"
HC_SENT = re.compile(r'<hc from="([^"]+)">(.*)</hc>$', re.S)


def prompt_kind(prompt):
    """What words that came into a PM session are, for its conversation log: (kind, sender, text).
    kind: "user" (the user's words: recorded as theirs), "agent" (another agent typed them in: recorded with `sender`),
    "batch" (events `pm.py deliver` sent: already in the log, see took_delivery), "rotate" (the takeover prompt of a
    rotation: nothing to record) or "other" (task notifications, slash commands, system text: nothing to record).
    One rule for a prompt (the UserPromptSubmit hook) and for words a running turn took in (record_taken_in)."""
    prompt, sender = (prompt or "").strip(), ""
    # Text typed in by another agent is not the user's turn: `hc send` from a terminal wraps it in
    # <hc from="t3">…</hc>, and `pm.py notify` starts it with "[from <pane>]". Long pastes may also be wrapped in
    # <pasted_content ...>…</pasted_content ...> by Claude Code (outside or inside <hc>).
    while True:
        unwrapped = unwrap_pasted(prompt)
        if unwrapped != prompt:
            prompt = unwrapped
            continue
        wrapped = HC_SENT.match(prompt)
        if wrapped and not sender:
            sender, prompt = f"hc:{wrapped.group(1)}", wrapped.group(2).strip()
            continue
        break
    named = re.match(r"\[from ([^\]]+)\]\s*", prompt)
    if named:
        sender, prompt = sender or named.group(1), prompt[named.end():]
    if sender == "pm.py rotate":
        return "rotate", sender, prompt
    # A batch of events from `pm.py deliver`; hc wraps it with the terminal of whoever wrote the last one.
    if named and named.group(1) == DELIVER_SENDER:
        return "batch", sender, prompt
    if sender:
        return "agent", sender, prompt
    if prompt and not prompt.startswith("<") and not SLASH_COMMAND.match(prompt):
        return "user", "", prompt
    return "other", "", prompt


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
    transcript = field("transcript_path")
    unfailing(remember_pm_session_for, ctx, rec, transcript, field("session_id"))
    delivery = Delivery(ctx, repo) if repo else None
    conv = Conversation(ctx, repo) if repo else None
    mirror = DiscordMirror(ctx)
    if delivery is not None:
        unfailing(delivery.ensure_running)  # a desktop-app PM's deliverer: started again if none runs
    if event == "UserPromptSubmit":
        # What a UserPromptSubmit hook prints is added to the session's context.
        raw = field("prompt").strip()
        kind, sender, prompt = prompt_kind(raw)
        if repo:
            # Words a turn took in while it worked and that no Stop hook recorded (the user stopped that turn):
            # before this prompt, where they were said. The prompt itself, if it is there too, is this hook's.
            unfailing(record_taken_in, rec, transcript, False, raw, ctx=ctx)
        if kind == "rotate":
            return  # the takeover prompt: nothing the user should read about
        if kind == "batch":
            if delivery is not None:
                def _took():
                    receipt = delivery.took_delivery(prompt)
                    if receipt.warning:
                        ctx.out.line(receipt.warning)
                unfailing(_took)
            return  # its events are in the log already
        if delivery is not None:
            def _bring():
                text_out = delivery.bring_pending()
                if text_out:
                    ctx.out.line(text_out)
            unfailing(_bring)
        if kind == "agent":
            if conv is not None and prompt:
                conv.record("agent", by=sender, text=prompt)
                mirror.mirror(rec, f"**{sender}**\n{prompt}")
            return
        if kind != "user":
            return  # task notifications, slash commands
        if conv is not None:
            conv.record("user", text=prompt)
            rec_slug = rec.get("name", "")[3:] if isinstance(rec.get("name"), str) and rec["name"].startswith("pm-") and ctx.store.has_project(rec["name"][3:]) else ""
            unfailing(emit_mention_hints, repo, prompt, rec_slug or None, ctx=ctx)
        mirror.mirror(rec, f"**你**\n{prompt}")
    else:
        # Words that came in while the turn worked are recorded first, so they stand before the turn's reply.
        if repo:
            unfailing(record_taken_in, rec, transcript, True, ctx=ctx)
        # The agent's Stop hook carries the final message of the turn (Claude Code and Codex name it so).
        reply = field("last_assistant_message").strip()
        if conv is not None and reply:
            # `by`: which session spoke, so the project view can tell this PM's ledger entries from a worker's.
            # `after`: a turn that a delivered batch started answers that batch, not the user (turn_cause).
            pane = ctx.pane
            conv.record("pm", text=reply, **({"by": pane} if pane else {}), **conv.turn_cause())
        if repo:
            unfailing(lambda: ProjectRegistry(ctx).app_pm(repo) and StallWatcher(ctx).sweep_exited(repo))
        if reply and rec.get("discord") and mirror.is_on() and not mirror.replied_on_discord(transcript):
            mirror.mirror(rec, f"**{rec['name']}**\n{reply}")
    turn_log(f"{event}: turn", ctx=ctx)


cmd_hook_mirror = cmd_hook_turn  # the name earlier installs put in their hooks


TAKEN_IN_TAIL = 4 << 20  # bytes at the end of a transcript read when the mark does not say where to go on from
TAKEN_IN_MORE = 32 << 20  # bytes read on from the mark: a turn that wrote more is read from the end, as with no mark
TAKEN_IN_KEYS = 200      # ids of rows (two a row) the mark remembers as done
TAKEN_IN_FILES = 8       # transcripts the mark remembers how far it has read: a rotation's old and new session, say


def record_taken_in(rec, transcript, ended, prompt="", *, ctx=None):
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
    recorded here as well; so is a line already in the log with the same words said within seconds of them."""
    ctx = Context.from_env() if ctx is None else ctx
    repo = rec.get("repo")
    if not repo or not transcript or not isinstance(transcript, str):
        return
    path, key = Path(transcript), str(Path(transcript))
    try:
        size = path.stat().st_size
    except (OSError, ValueError):
        return
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    near = datetime.timedelta(seconds=5)
    proj_dir = ctx.home.project_for(repo).ensure()
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
    if not isinstance(start, int) or isinstance(start, bool) or not 0 <= start <= size or size - start > TAKEN_IN_MORE:
        start, whole = max(0, size - TAKEN_IN_TAIL), False
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
    conv = Conversation(ctx, repo)
    delivery = Delivery(ctx, repo)
    mirror = DiscordMirror(ctx)
    local = lambda t: t.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    logged, used = conv.events(), set()
    for (words, _, origin), said, written in found:
        kind, sender, text = prompt_kind(words)
        if kind == "user" and origin == "peer":
            kind, sender = "agent", "peer"  # another agent's message that names no sender
        if kind == "batch":
            unfailing(delivery.took_delivery, text, True)
            continue
        if kind not in ("user", "agent") or not text:
            continue
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
