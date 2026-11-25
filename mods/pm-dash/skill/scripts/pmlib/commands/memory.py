"""Memory, decision and context commands (`remember`, `recall`, `forget`, `adopt`, `memory`, `decide`, `context`,
`decisions`). Layer 4."""
from pathlib import Path
import sys

from ..agents.sessions import context_tokens, own_transcript
from ..context import Context
from ..errors import IdentityError, PmError, StoreError
from ..ledger.ledger import Ledger
from ..manager.launch import COMPACT_TOKENS
from ..memory.candidates import MemoryCandidates
from ..memory.decisions import Decisions
from ..memory.layer import (
    MEMORY_TYPES,
    TOPICS,
    MemoryLayer,
    MemoryRefused,
    find_memory_in,
    recall_text,
    squash,
)
from ..osutil import clip
from ..project.conversation import Conversation
from . import workers
from .emit import exit_with


def cmd_remember(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    repo = ctx.git.project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    try:
        body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else ""
        layer = MemoryLayer(ctx, None if a.personal else repo)
        m, notes = layer.remember(
            a.text,
            writer=ctx.caller.memory_writer(repo),
            kind=a.type,
            name=a.name,
            quote=a.quote or "",
            verified=a.verified or "",
            body=body,
            expires=a.expires or "",
            new=a.new,
            topic=getattr(a, "topic", None),
            project_repo=repo,
        )
    except (StoreError, IdentityError):
        raise
    except (MemoryRefused, OSError) as e:
        sys.exit(str(e))
    ctx.out.line(tr(f"remembered ({'personal' if a.personal else 'project'}): {m['name']}",
                    f"记住了（{'个人' if a.personal else '项目'}）：{m['name']}"))
    for line in notes:
        ctx.out.line(f"[pm] {line}")
    if any("limit" in line or "上限" in line for line in notes):
        sys.exit(3)


def cmd_recall(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    repo = ctx.git.project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    kind, topic = getattr(a, "type", None), getattr(a, "topic", None)
    if a.search or kind or topic:
        word = squash(a.search or "")
        hits = [
            mem_layer.index_line(m)
            for layer in (repo, None)
            for mem_layer in (MemoryLayer(ctx, layer),)
            for m in mem_layer.memories()
            if word in squash(m["name"] + m["description"] + m["body"] + m.get("quote", ""))
            and kind in (None, m["type"]) and topic in (None, m["topic"])
        ]
        ctx.out.line("\n".join(hits) if hits else tr("(no memory mentions that)", "（没有提到它的记忆）"))
        return
    if not a.name:
        sys.exit("name a memory, or search: recall --search <word>")
    layer, m = find_memory_in(ctx, repo, a.name, personal=a.personal)
    if not m:
        if not a.personal:
            slug = Path(a.name).stem
            proj_layer = MemoryLayer(ctx, repo)
            kept = proj_layer.history(slug)
            if kept:
                old = proj_layer.read(kept[0]["file"])
                into = str((old or {}).get("extra", {}).get("merged_into") or "").strip()
                if into:
                    target = proj_layer.read(proj_layer.dir / f"{Path(into).stem}.md")
                    if target:
                        ctx.out.line(tr(
                            f"{slug} was merged into {into}",
                            f"{slug} 已并入 {into}",
                        ))
                        ctx.out.line(proj_layer.recall_text(target))
                        return
        sys.exit(f"no memory called {a.name} (`pm.py memory` lists them)")
    ctx.out.line(MemoryLayer(ctx, layer).recall_text(m))


def cmd_forget(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    repo = ctx.git.project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    layer, m = find_memory_in(ctx, repo, a.name, personal=a.personal)
    if not m:
        sys.exit(f"no memory called {a.name}")
    try:
        MemoryLayer(ctx, layer).forget(m, writer=ctx.caller.memory_writer(repo), why=a.why or "")
    except MemoryRefused as e:
        sys.exit(str(e))
    ctx.out.line(tr(f"forgot {m['name']} (kept in .history)", f"已忘掉 {m['name']}（旧内容留在 .history）"))


def adopt_memory_candidate(a, ctx=None):
    """Take a candidate (what a worker's own memory saved) into the project's memory, through `remember`'s checks,
    or drop it."""
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    repo = ctx.git.project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    try:
        res = MemoryCandidates(ctx, repo).adopt(
            a.candidate,
            writer=ctx.caller.memory_writer(repo),
            drop=bool(a.drop),
            text=a.text,
            name=a.name,
            kind=a.type,
            topic=getattr(a, "topic", None),
            quote=a.quote or "",
            verified=a.verified or "",
        )
    except (StoreError, IdentityError):
        raise
    except PmError as e:
        exit_with(ctx, e)
    if res.dropped:
        ctx.out.line(tr(f"dropped {res.worker}/{res.source_name}", f"已丢弃 {res.worker}/{res.source_name}"))
        return
    ctx.out.line(tr(f"adopted {res.worker}/{res.source_name} as {res.memory['name']}",
                    f"已收编 {res.worker}/{res.source_name}，名字是 {res.memory['name']}"))
    for line in res.notes:
        ctx.out.line(f"[pm] {line}")


def cmd_adopt(a, ctx=None):
    """Adopt a worker's memory candidate (`<worker>/<name>`) into project memory, or adopt an idle orphan task
    worker (`<task id>`) under the current PM seat."""
    ctx = Context.from_env() if ctx is None else ctx
    mem_only = any(getattr(a, f, None) for f in ("drop", "text", "name", "type", "topic", "quote", "verified"))
    if "/" in a.candidate or mem_only:
        return adopt_memory_candidate(a, ctx=ctx)
    resolved = Ledger(ctx).try_resolve_id(a.candidate)
    if resolved and ctx.home.task(resolved).is_file():
        a.candidate = resolved
        return workers.adopt_task(a, ctx=ctx)
    if getattr(a, "confirmed", False):
        return workers.adopt_task(a, ctx=ctx)
    repo = ctx.git.project_root(a.repo)
    if repo and any(m["name"] == Path(a.candidate).stem for _, m in MemoryCandidates(ctx, repo).list()):
        return adopt_memory_candidate(a, ctx=ctx)
    sys.exit(f"no task or memory candidate called {a.candidate} (`pm.py status` or `pm.py memory --candidates`)")


def cmd_memory(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    repo = ctx.git.project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    if a.candidates:
        rows = [f"- {who}/{m['name']} ({m['type']}) — {clip(m['description'], 150)}"
                for who, m in MemoryCandidates(ctx, repo).list()]
        ctx.out.line("\n".join(rows) if rows else tr("(no candidates)", "（没有候选）"))
        return
    ctx.out.line(MemoryLayer(ctx, repo).memory_block() or tr("(no memories yet)", "（还没有记忆）"))


def cmd_decide(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    repo = ctx.git.project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    once = bool(getattr(a, "once", False))
    tag = "[once] " if once else ""
    line = f"- {ctx.clock.now()[:10]} {tag}{a.text}" + (tr(f' — the user\'s words: "{a.quote}"', f" — 用户原话：「{a.quote}」") if a.quote else "")
    with open(ctx.home.project_for(repo).ensure() / "decisions.md", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    Conversation(ctx, repo).record("decision", text=a.text, quote=a.quote or "", **({"once": True} if once else {}))
    ctx.out.line(line)
    if once:
        return
    # A decision that is to hold is also a memory, which later sessions and every worker are given; a one-off
    # instruction (--once) stays in the log alone.
    try:
        layer = MemoryLayer(ctx, None if getattr(a, "personal", False) else repo)
        m, notes = layer.remember(
            a.text,
            writer=ctx.caller.memory_writer(repo),
            kind=getattr(a, "type", None) or "project",
            quote=a.quote or "",
            name=getattr(a, "name", None),
            auto_name=True,
            topic=getattr(a, "topic", None),
            project_repo=repo,
        )
    except (StoreError, IdentityError):
        raise
    except (MemoryRefused, OSError) as e:
        ctx.out.line(tr(f"(not remembered: {e})", f"（没有写进记忆：{e}）"))
        return
    ctx.out.line(tr(f"remembered as {m['name']}", f"已写进记忆：{m['name']}"))
    for note_line in notes:
        ctx.out.line(f"[pm] {note_line}")


def cmd_context(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    path = a.transcript or own_transcript(env=ctx.env, claude_projects=ctx.agents.claude_projects)
    if not path:
        sys.exit("no transcript: pass --transcript")
    used = context_tokens(path)
    ctx.out.line(f"{used // 1000}k context tokens (auto-compact target {COMPACT_TOKENS // 1000}k)")


def cmd_decisions(a, ctx=None):
    """Print the decisions the user has made, with their words: what a handover shortens to the latest ones."""
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    repo = ctx.git.project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    lines = Decisions(ctx, repo).lines()
    ctx.out.line("\n".join(lines[-a.last:] if a.last else lines) if lines else tr("(no decisions recorded)", "（还没有记录决定）"))


def register_memory_commands(sub):
    dc = sub.add_parser("decide", help="record a decision the user made, for every later PM session")
    dc.add_argument("text")
    dc.add_argument("--quote", help="the user's own words")
    dc.add_argument("--once", action="store_true",
                    help="a one-off instruction (\"push\", \"install after this\"): logged, not written to memory")
    dc.add_argument("--type", choices=MEMORY_TYPES, help="the memory's type (default project; feedback for a "
                                                         "correction of how to work)")
    dc.add_argument("--topic", choices=TOPICS, help="the memory's group (default by type: project architecture, "
                                                    "feedback workflow)")
    dc.add_argument("--personal", action="store_true", help="about the user, not this project: remembered for "
                                                            "every project")
    dc.add_argument("--name", help="the memory's short English name (default: from the text)")
    dc.add_argument("--repo", default=".")
    rm = sub.add_parser("remember", help="write a memory: what later sessions and workers should know without "
                                         "asking (a worker: --type pitfall --verified, or --type reference)")
    rm.add_argument("text", help="the memory in one sentence; for a rule, the rule itself")
    rm.add_argument("--name", help="a short English slug; an existing name updates that memory")
    rm.add_argument("--type", choices=MEMORY_TYPES, help="project (a decision of the user's; the default), feedback, "
                                                         "reference, pitfall (a worker's default) or user")
    rm.add_argument("--topic", choices=TOPICS, help="its group, one of the six fixed ones (default by type: "
                                                    "pitfall pitfalls, reference reference, feedback workflow, "
                                                    "project architecture)")
    rm.add_argument("--quote", help="the user's own words (needed for user and feedback)")
    rm.add_argument("--verified", help="how you know: the command, the task, what you saw (a project fact)")
    rm.add_argument("--personal", action="store_true", help="the personal layer: every project gets it")
    rm.add_argument("--body-file", help="a file with the memory's full text (default: the sentence)")
    rm.add_argument("--expires", help="YYYY-MM-DD after which it leaves the index")
    rm.add_argument("--new", action="store_true", help="keep it beside a memory that says nearly the same")
    rm.add_argument("--repo", default=".")
    rc = sub.add_parser("recall", help="print one memory in full, with where it comes from and how old it is")
    rc.add_argument("name", nargs="?")
    rc.add_argument("--search", help="list the memories that mention this")
    rc.add_argument("--type", choices=MEMORY_TYPES, help="list the memories of this type")
    rc.add_argument("--topic", choices=TOPICS, help="list the memories of this group")
    rc.add_argument("--personal", action="store_true")
    rc.add_argument("--repo", default=".")
    fg = sub.add_parser("forget", help="remove a memory (what it said is kept in .history)")
    fg.add_argument("name")
    fg.add_argument("--why", help="why it no longer holds")
    fg.add_argument("--personal", action="store_true")
    fg.add_argument("--repo", default=".")
    ad = sub.add_parser("adopt", help="adopt an idle orphan task worker under the PM seat, or take a worker's "
                                      "memory candidate into project memory")
    ad.add_argument("candidate", help="<task id> (orphan worker) or <worker>/<name> (`memory --candidates`)")
    ad.add_argument("--confirmed", action="store_true",
                    help="with <task id>: restart under the PM seat even when the worker has no resumable session")
    ad.add_argument("--text", help="the sentence to keep instead of the candidate's")
    ad.add_argument("--name")
    ad.add_argument("--type", choices=MEMORY_TYPES)
    ad.add_argument("--topic", choices=TOPICS)
    ad.add_argument("--quote", help="the user's own words, when it is a rule of the user's")
    ad.add_argument("--verified", help="how it is known, when it is a fact")
    ad.add_argument("--drop", action="store_true", help="throw the candidate away")
    ad.add_argument("--repo", default=".")
    me = sub.add_parser("memory", help="print the memory a session is given: both indexes")
    me.add_argument("--candidates", action="store_true", help="list what workers' own memory saved")
    me.add_argument("--repo", default=".")


def register_decisions_command(sub):
    dd = sub.add_parser("decisions", help="print the decisions the user has made, with the user's words")
    dd.add_argument("--repo", default=".")
    dd.add_argument("--last", type=int, default=0, help="only the latest N (default: all)")


def register_context_command(sub):
    cxp = sub.add_parser("context", help="context tokens held by this session")
    cxp.add_argument("--transcript")
