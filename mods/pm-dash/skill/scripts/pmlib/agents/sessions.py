"""An agent's own transcripts, read without the ledger: where Claude Code and Codex keep them, a transcript's opening
and whose session it is (a manager's, a helper's, a reviewer's), how surely it is a task's agent, the context it has
used, and the command that resumes a session. Layer 1: nothing here reads or writes a task; matching sessions to
tasks is workers/sessions.py."""
import json
import os
from pathlib import Path
import re
import sys

import pmlib.home
from . import base as base_mod

try:
    from .transcripts import claude_folder
    pm_sessions = sys.modules["pmlib.agents.transcripts"]
except ImportError:
    # Missing transcripts.py: `state` and hooks degrade quietly (optional
    # context_tokens is omitted), while `project session` exits with an explicit error.
    pm_sessions = None

    def claude_folder(path):
        """The folder under ~/.claude/projects where Claude Code keeps the sessions started in path."""
        return re.sub(r"[^A-Za-z0-9]", "-", str(path))


CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"


# What the pm hooks put in a session's transcript: this one was a PM, not the agent of a task.
PM_SESSION_MARK = "the PM for this project (pm skill)"

PM_PROMPT = re.compile(r"\[from pm\.py (?:start|rotate|restore)\]")
HELPER_PROMPT = re.compile(
    r"\[Helper [^\]]+ for [^\]]+\]"
    r"|【临时 helper [^】]+，归属 [^】]+】"
    r"|You are helper \S+ for \S+ \(read-only\)"
    r"|你是 \S+ 的临时 helper \S+（只读）"
)
REVIEW_PROMPT = re.compile(r"Review(?: \(read-only\))? of task |审查(?:（只读）)?任务 ")  # review_brief's first words


def own_transcript(*, env=None, claude_projects=None):
    """Transcript file of the Claude Code session running this command, or "" (other agents: not read yet)."""
    env_map = os.environ if env is None else env
    sid = env_map.get("CLAUDE_CODE_SESSION_ID", "")
    root = Path(claude_projects) if claude_projects is not None else CLAUDE_PROJECTS
    hits = list(root.glob(f"*/{sid}.jsonl")) if sid else []
    return str(hits[0]) if hits else ""


def transcript_rows(path):
    try:  # lines end at "\n" only: words may hold U+2028 and the like, which splitlines() also breaks at
        lines = Path(path).read_text(errors="replace").split("\n")
    except (OSError, TypeError, ValueError):  # no such file, or a path that is none (a hook input of another shape)
        return
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not row.get("isSidechain"):
            yield row


def context_tokens(path):
    """Context size of a session: the input side of its latest model call (stopping at compact_boundary)."""
    if pm_sessions is not None:
        return pm_sessions.context_tokens_file(path)
    used = 0
    for row in transcript_rows(path):
        if row.get("type") == "system" and row.get("subtype") == "compact_boundary":
            meta = row.get("compactMetadata")
            used = int(meta.get("postTokens") or 0) if isinstance(meta, dict) else 0
            continue
        usage = (row.get("message") or {}).get("usage") if row.get("type") == "assistant" else None
        if usage:
            tokens = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens",
                                                     "cache_creation_input_tokens"))
            if tokens > 0:
                used = tokens
    return used


def sessions_reader(cache=False, *, home=None, claude_projects=None, agy_dir=None):
    """Sessions interface wired to pm.py's dynamic CLAUDE_PROJECTS, agy_dir, and optional disk cache."""
    if pm_sessions is None:
        return None
    cache_path = (lambda: (home or pmlib.home.current()).context_tokens_cache) if cache else None
    projects_dir = claude_projects if claude_projects is not None else (lambda: CLAUDE_PROJECTS)
    return pm_sessions.default_sessions(projects_dir=projects_dir, cache_path=cache_path, agy_dir=agy_dir)


def opening(text):
    """A transcript's opening: its lines up to the first reply (startup hook output, the first prompt)."""
    head = []
    for line in text.split("\n"):
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        if isinstance(row, dict) and (
            "assistant" in (row.get("type"), (row.get("message") or {}).get("role"),
                            (row.get("payload") or {}).get("role"))
            or row.get("type") == "PLANNER_RESPONSE"
        ):
            break
        head.append(line)
    return "\n".join(head)


def pm_session(text):
    """A PM's session: it was started as one (pm.py start/rotate/restore) or told it is one at startup.
    Only the opening counts: a worker may quote those words later on."""
    head = opening(text)
    return PM_SESSION_MARK in head or bool(PM_PROMPT.search(head))


def helper_session(text):
    """A temporary helper's session: its opening carries the helper brief or SessionStart hook reminder.
    Only the opening counts: a worker may quote helper text later on. Decodes \\uXXXX escapes in JSONL lines."""
    head = opening(text)
    if HELPER_PROMPT.search(head):
        return True
    if "\\u" not in head:
        return False
    for line in head.split("\n"):
        if "\\u" not in line:
            continue
        try:
            decoded = json.dumps(json.loads(line), ensure_ascii=False)
        except ValueError:
            continue
        if HELPER_PROMPT.search(decoded):
            return True
    return False


def reviewer_session(text):
    """A reviewer's session: its opening carries the review brief (review_brief). Only the opening counts: a
    worker may quote a review later on. Decodes \\uXXXX escapes in JSONL lines, as helper_session does."""
    head = opening(text)
    if REVIEW_PROMPT.search(head):
        return True
    for line in head.split("\n") if "\\u" in head else []:
        if "\\u" not in line:
            continue
        try:
            decoded = json.dumps(json.loads(line), ensure_ascii=False)
        except ValueError:
            continue
        if REVIEW_PROMPT.search(decoded):
            return True
    return False


def session_score(text, task_id):
    """How surely a transcript is the agent of task_id: 2 when it reports on the task (`update <id>`, which its
    brief or its own registration put there), 1 when it only names it, 0 when it is not (a PM's or helper's session).
    A reviewer's session (its opening is a review brief) is its review task's alone: 2 for the task its brief tells
    it to report on (`update <id>-review`), 0 for the reviewed task, whose ledger entries it quotes verbatim."""
    if task_id not in text or pm_session(text) or helper_session(text):
        return 0
    report = re.compile(rf"\b(?:update|log) {re.escape(task_id)}(?![\w.-])")
    if reviewer_session(text):
        return 2 if report.search(opening(text)) else 0
    return 2 if report.search(text) else 1


def first_cwd(path):
    """The folder a transcript's session was started in: the first `cwd` it records."""
    try:
        with open(path, errors="replace") as f:
            for line in f:
                found = re.search(r'"cwd":\s*"((?:[^"\\]|\\.)*)"', line)
                if found:
                    return json.loads(f'"{found.group(1)}"')
    except OSError:
        pass
    return ""


def resume_argv(kind, session_id, model="", effort="", advisor="", fallback=""):
    """The command that resumes a session of this kind, or None for a kind that cannot be resumed here."""
    return base_mod.build_agent_kind(kind, base_mod.agent_kinds().get(kind)).resume_argv(
        session_id, model, effort, advisor=advisor, fallback=fallback
    )
