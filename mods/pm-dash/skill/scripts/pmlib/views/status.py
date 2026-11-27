"""Text read views of the ledger (`log`, `show`, `board`, `status`, `diff`, `find`) and the diff file classifiers
(`side_file`, `ui_file`). Layer 4."""
import json
from pathlib import Path
import re
import sys

from ..commands.emit import exit_with
from ..context import Context
from ..discord import DiscordMirror
from ..errors import IdentityError, PmError, StoreError
from ..events.deliver import Delivery
from ..helpers.config import HELPER_TIMEOUT
from ..helpers.records import helper_elapsed, project_running_helpers_for, reconcile_project_helpers_for
from ..ledger.board import Board
from ..ledger.deps import evaluate_depends_on, format_dep_item, format_dep_summary
from ..ledger.family import format_children_summary, task_children_map
from ..ledger.ledger import Ledger
from ..ledger.plan import plan_progress
from ..ledger.task import ACTIVE, CLOSED, hc_terminal_of, needs_cleanup, started_by_pm, task_number
from ..osutil import clip
from ..project.project import ProjectRegistry, in_scope
from ..project.readmodel import owner_of, task_offline
from ..reports import ReportClient, task_log_report
from ..workers.lifecycle import active_review_of_for, term_status


def cmd_log(a, ctx=None):
    """`pm.py log`: a `report.task_log` envelope, applied here (one entry, kept once under its idempotency key)."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        ReportClient(ctx).submit(task_log_report(ctx, a.id, a.text))
    except (StoreError, IdentityError):
        raise
    except PmError as e:
        exit_with(ctx, e)


SHOW_LOG = 3       # ledger entries `show` prints without --json
SHOW_WIDTH = 600  # each one clipped to this many characters


def cmd_show(a, ctx=None):
    """A task in a few lines: status, branch and the latest ledger entries. --json prints the whole record."""
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    ledger = Ledger(ctx)
    try:
        task = ledger.load(a.id).raw
    except (StoreError, IdentityError):
        raise
    except PmError as e:
        exit_with(ctx, e)
    ahead, dirty = ctx.git.git_state(task.get("worktree") or task["repo"], task.get("branch"), task["base"])
    every = ledger.raw_tasks()
    by_id = {t["id"]: t for t in every if isinstance(t, dict) and t.get("id")}
    children = [t for t in every if t.get("parent") == task["id"]]
    dep_info = evaluate_depends_on(task, by_id)
    if getattr(a, "json", False):
        live = {"ahead": ahead, "dirty": dirty}
        if task.get("status") == "proposed" or dep_info["depends_on"]:
            live["ready"] = dep_info["ready"]
        if dep_info["depends_on"]:
            live["deps"] = dep_info["items"]
        ctx.out.line(json.dumps({**task, "live": live}, ensure_ascii=False, indent=2))
        return
    ctx.out.line(f"{ledger.task_ref(task)}  [{task['status']}]  {task.get('title', '')}")
    parent_val = task.get("parent")
    if parent_val:
        ptask = ctx.store.task(parent_val)
        pnum = task_number(ptask)
        if pnum:
            parent_val = f"#{pnum} {parent_val}"
    ctx.out.line("  " + " ".join(f"{k}={v}" for k, v in (
        ("branch", task.get("branch") or "-"), ("base", task.get("base")), ("ahead", ahead), ("dirty", dirty),
        ("commit", task.get("commit")), ("landed", (task.get("landed") or {}).get("commit")),
        ("pane", task.get("pane")), ("profile", (task.get("worker") or {}).get("profile")),
        ("parent", parent_val)) if v not in (None, "")))
    if task.get("brief"):
        ctx.out.line(f"  brief: {task['brief']}")
    if task.get("worktree"):
        ctx.out.line(f"  worktree: {task['worktree']}")
    if isinstance(task.get("land_approved"), dict):
        la = task["land_approved"]
        who = la.get("executor_pane") or la.get("helper_name") or la.get("executor") or "worker"
        ctx.out.line(f"  merge_approved: {la.get('short') or la.get('commit') or '-'} -> {la.get('base') or task.get('base')} ({who})")
    if dep_info["depends_on"]:
        state_word = tr("ready to dispatch", "可以派了") if dep_info["ready"] else (
            tr("blocked by broken dependency", "前置依赖异常") if dep_info["broken"] else tr("waiting", "等待前置"))
        ctx.out.line(f"  depends_on ({state_word}):")
        for item in dep_info["items"]:
            mark = "[x]" if item["state"] == "met" else "[!]" if item["state"] in ("abandoned", "missing") else "[ ]"
            ctx.out.line(f"    {mark} {format_dep_item(item, tr_fn=tr)}")
    if children:
        c_deps = {c["id"]: evaluate_depends_on(c, by_id) for c in children}
        ctx.out.line(f"  {format_children_summary(children, c_deps, tr_fn=tr)}:")
        for c in children:
            c_info = c_deps[c["id"]]
            tail = ""
            if c.get("status") == "proposed" and c_info["depends_on"]:
                tail = "  [" + (tr("ready", "可以派了") if c_info["ready"] else format_dep_summary(c_info, tr_fn=tr)) + "]"
            ctx.out.line(f"    [{c['status']}] {c['id']}  {c.get('title', '')}{tail}")
    if task["status"] == "blocked":
        for i, option in enumerate(task.get("options") or []):
            ctx.out.line(f"  option {i + 1}: {option}")
    if isinstance(task.get("plan"), list) and task["plan"]:
        done_n, total_n, _ = plan_progress(task["plan"])
        marks = {"done": "[x]", "doing": "[>]", "todo": "[ ]"}
        ctx.out.line(f"  plan ({done_n}/{total_n}):")
        active_set = False
        for s in task["plan"]:
            if not isinstance(s, dict):
                continue
            st = s.get("state") or "todo"
            ctx.out.line(f"    {marks.get(st, '[ ]')} {s.get('text', '')}")
            if not active_set and st == "doing" and isinstance(task.get("subplan"), list) and task["subplan"]:
                active_set = True
                for sub in task["subplan"]:
                    if isinstance(sub, dict):
                        ctx.out.line(f"      {marks.get(sub.get('state') or 'todo', '[ ]')} {sub.get('text', '')}")
        if not active_set and isinstance(task.get("subplan"), list) and task["subplan"]:
            sd, st_n, _ = plan_progress(task["subplan"])
            ctx.out.line(f"  subplan ({sd}/{st_n}):")
            for sub in task["subplan"]:
                if isinstance(sub, dict):
                    ctx.out.line(f"    {marks.get(sub.get('state') or 'todo', '[ ]')} {sub.get('text', '')}")
    elif isinstance(task.get("subplan"), list) and task["subplan"]:
        sd, st_n, _ = plan_progress(task["subplan"])
        marks = {"done": "[x]", "doing": "[>]", "todo": "[ ]"}
        ctx.out.line(f"  subplan ({sd}/{st_n}):")
        for sub in task["subplan"]:
            if isinstance(sub, dict):
                ctx.out.line(f"    {marks.get(sub.get('state') or 'todo', '[ ]')} {sub.get('text', '')}")
    log = task.get("log") or []
    ctx.out.line(tr(f"log (last {min(SHOW_LOG, len(log))} of {len(log)}; --json for the whole record):",
                    f"日志（最近 {min(SHOW_LOG, len(log))} 条，共 {len(log)} 条；--json 看完整记录）："))
    for e in log[-SHOW_LOG:]:
        ctx.out.line(clip(f"- {e.get('at', '')} {e.get('by', '')}: {e.get('text', '')}", SHOW_WIDTH))


def cmd_board(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    Board(ctx).write()
    if getattr(a, "post", False) or getattr(a, "channel", None):
        mirror = DiscordMirror(ctx)
        try:
            mirror.require_on()
        except (StoreError, IdentityError):
            raise
        except PmError as e:
            exit_with(ctx, e)
        cfg = mirror.read_cfg()
        if a.channel:
            cfg = {"board_channel": str(a.channel)}  # new channel: start a fresh message
            mirror.write_cfg(cfg)
        if not cfg.get("board_channel"):
            sys.exit("no board channel configured; pass --channel <id> once")
        ctx.out.line("board posted to Discord" if mirror.post_board(force=True) else "posting to Discord failed")
        return
    ctx.out.line(ctx.home.board.read_text(encoding="utf-8"))


def cmd_status(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    ledger = Ledger(ctx)
    projects = ProjectRegistry(ctx)
    listing = ctx.tui.agents()
    by_pane = {x["pane_id"]: x for x in listing}
    labels = {w["workspace_id"]: w.get("label") for w in (ctx.tui.call("workspace", "list") or {}).get("workspaces", [])}
    pm_panes = {x["pane_id"] for x in listing if str(x.get("name") or "").startswith("pm-")}
    ctx.out.line("PMs:")
    for x in listing:
        if x["pane_id"] in pm_panes:
            ctx.out.line(f"  {x['name']}  {x['pane_id']}{' (this session)' if x['pane_id'] == ctx.pane else ''}  "
                         f"{x.get('agent_status')}  {x.get('cwd')}")
    regs = ctx.home.registrations
    hc_recs = []
    if regs.exists():
        for p in sorted(regs.glob("*.json")):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get("runtime") == "hc":
                hc_recs.append(rec)
    in_hc = [pm for pm in (projects.hc_pm(r.get("repo") or "") for r in hc_recs) if pm]
    live_hc_by_name = {pm["name"]: pm for pm in in_hc}
    for pm in in_hc:
        ctx.out.line(f"  {pm['name']}  {pm['pane_id']}{' (this session)' if pm['pane_id'] == ctx.pane else ''}  "
                     f"{pm['agent_status']}  {pm['cwd']}")
    if not pm_panes and not in_hc:
        ctx.out.line("  (none)")
    for rec in hc_recs:
        if rec.get("archived") or not rec.get("repo"):
            continue
        live_pm = live_hc_by_name.get(rec.get("name"))
        live_state = str(live_pm.get("agent_status") or "") if live_pm else "offline"
        undel = Delivery(ctx, rec["repo"]).undelivered_status(live_state=live_state)
        if undel:
            mins = max(1, int(undel["waiting_seconds"] // 60))
            pane = rec.get("pane") or f"hc:{rec.get('terminal') or '?'}"
            st_word = undel["state"]
            no_del_en = ", deliverer not running" if not undel["deliverer_running"] else ""
            no_del_zh = "，投递器未运行" if not undel["deliverer_running"] else ""
            n_ev, n_msg = int(undel.get("count") or 0), int(undel.get("messages") or 0)
            what_en = ", ".join(x for x in (
                f"{n_ev} pending event(s)" if n_ev else "", f"{n_msg} message(s) not typed in" if n_msg else "") if x)
            what_zh = "、".join(x for x in (
                f"{n_ev} 条待投递事件" if n_ev else "", f"{n_msg} 条消息未打进终端" if n_msg else "") if x)
            why = str(undel.get("message_reason") or "")
            ctx.out.line(tr(
                f"  ! {rec['name']} ({pane}): {what_en} undelivered for {mins}m "
                f"(state={st_word}{no_del_en}{f', {why}' if why else ''})",
                f"  ! {rec['name']}（{pane}）：{what_zh}已等待 {mins} 分钟未送达"
                f"（状态={st_word}{no_del_zh}{f'，{why}' if why else ''}）",
            ))
    tasks = ledger.raw_tasks()
    scope = projects.status_scope(tasks, getattr(a, "repo", "."), getattr(a, "all", False))
    pms = projects.pm_records() if scope else []
    # This project's tasks: in its folder or one under it (issues/site-a), or the board's for its PM (owner_of).
    mine = lambda t: not scope or in_scope(t["repo"], scope) or in_scope((owner_of(t, pms) or {}).get("repo"), scope)
    # Merged or released work stays listed until `retire` removes its worktree and branch.
    active = [t for t in tasks if mine(t)
              and (t["status"] in ACTIVE or (getattr(a, "closed", False) and t["status"] in CLOSED)
                   or (t["status"] in ("merged", "released") and not t.get("retired")))]
    linked_panes, linked_branches = set(), set()
    raw_hc_rows = ctx.hc.live_rows() if any((t.get("pane") or "").startswith("hc:") for t in active) else None
    hc_rows = None if raw_hc_rows is None else {k: v.raw for k, v in raw_hc_rows.items()}
    hc_live = set(hc_rows) if hc_rows is not None else None
    by_id = {t["id"]: t for t in tasks if isinstance(t, dict) and t.get("id")}
    dep_by_id = {t["id"]: evaluate_depends_on(t, by_id) for t in active}
    children_map = task_children_map([t for t in tasks if mine(t)])
    ready_tasks = [t for t in active if t["status"] == "proposed" and dep_by_id[t["id"]]["ready"]]
    if ready_tasks:
        ctx.out.line(tr(f"\nReady to dispatch ({len(ready_tasks)}):", f"\n可以派了（{len(ready_tasks)}）："))
        for t in ready_tasks:
            info = dep_by_id[t["id"]]
            meta = [format_dep_summary(info, include_empty=True, tr_fn=tr)]
            if t.get("parent"):
                meta.append(f"parent={t['parent']}")
            if t.get("brief"):
                meta.append(f"brief={t['brief']}")
            ctx.out.line(f"  {ledger.task_ref(t, by_id)}  {t['title']}  [{'; '.join(meta)}]")
    ctx.out.line(tr(f"\nTasks of {Path(scope).name} (--all: every project):", f"\n{Path(scope).name} 的任务（--all：所有项目）：")
                 if scope else "\nTasks:")
    for t in active:
        live = by_pane.get(t.get("pane") or "", {})
        state = live.get("agent_status", "-") if t.get("pane") else "-"
        ahead, dirty = ctx.git.git_state(t.get("worktree") or t["repo"], t.get("branch"), t["base"])
        linked_panes.add(t.get("pane"))
        linked_branches.add((t["repo"], t.get("branch")))
        latest = (t.get("log") or [{}])[-1].get("text", "")[:70]
        plan_tag = ""
        if isinstance(t.get("plan"), list) and t["plan"]:
            pdone, ptotal, pnext = plan_progress(t["plan"])
            plan_tag = f" plan={pdone}/{ptotal}" + (f" ({clip(pnext, 30)})" if t.get("landed") and pnext else "")
        kids = children_map.get(t["id"])
        child_tag = f" {format_children_summary(kids, dep_by_id, tr_fn=tr)}" if kids else ""
        dep_line = ""
        info = dep_by_id[t["id"]]
        if info["depends_on"]:
            if info["ready"]:
                dep_line = "\n      " + tr(
                    f"deps: ready ({format_dep_summary(info, tr_fn=tr)})",
                    f"依赖：可以派了（{format_dep_summary(info, tr_fn=tr)}）",
                )
            else:
                dep_line = "\n      " + format_dep_summary(info, tr_fn=tr)
        ctx.out.line(f"  [{t['status']}] {ledger.task_ref(t, by_id)}  {t['title']}\n"
                     f"      {t.get('pane') or '-'} {live.get('name') or t.get('agent') or ''} agent={state} "
                     f"branch={t.get('branch') or '-'} ahead={ahead} dirty={dirty}{plan_tag}{child_tag} updated={t['updated'][5:]}\n"
                     f"      latest: {latest}"
                     + dep_line
                     + (f"\n      not retired: run `pm.py retire {t['id']}`" if needs_cleanup(t) else "")
                     + (f"\n      offline: its terminal is gone; `pm.py reattach {t['id']}` brings its agent back"
                        if task_offline(t, hc_live, set(by_pane) if listing else None) else ""))
    if not active:
        ctx.out.line("  (none)")
    # Reported work whose worker terminal still sits idle: nothing ends it until the task is closed or retired.
    # Skip workers that have an active review running under them (`--parent <worker>`).
    reported = [(t, hc_terminal_of(t)) for t in active if t["status"] in ("review", "done") and not t.get("retired")
                and started_by_pm(t) and not active_review_of_for(ctx, t["id"], tasks=tasks)
                and term_status((hc_rows or {}).get(hc_terminal_of(t)) or {}) in ("idle", "done")]
    if reported:
        ctx.out.line(tr("\nReported, worker terminal still open (`pm.py idle-workers --close <t>` ends it; so do `land` and "
                        "`retire`):", "\n已汇报、worker 终端还开着（`pm.py idle-workers --close <t>` 关掉；`land`、`retire` 也会关）："))
        for t, term in reported:
            ctx.out.line(f"  {ledger.task_ref(t, by_id)}  hc:{term}  [{t['status']}]  {t['title']}")
    helper_repos = [scope] if scope else list(dict.fromkeys(
        [p.get("repo") for p in projects.pm_records() if p.get("repo")] + [t["repo"] for t in active if t.get("repo")]))
    running_helpers = []
    for hrepo in helper_repos:
        reconcile_project_helpers_for(ctx, hrepo)
        running_helpers += project_running_helpers_for(ctx, hrepo)
    if running_helpers:
        ctx.out.line(tr("\nRunning helpers (`pm.py helper ls --all` for details):",
                        "\n运行中的 helper（详情见 `pm.py helper ls --all`）："))
        for h in running_helpers:
            elapsed = int(max(0, helper_elapsed(h, clock=ctx.clock)))
            ctx.out.line(f"  {h['name']}  of={h.get('owner') or '?'}  hc:{h.get('terminal') or '?'}  "
                         f"{h.get('profile') or h.get('kind') or ''}  {elapsed}s/{h.get('timeout') or HELPER_TIMEOUT}s")
    # Work nobody registered: a busy or diverged pane, or a diverged worktree branch.
    found, repos = [], set()
    for x in listing:
        if x["pane_id"] in linked_panes or x["pane_id"] in pm_panes:
            continue
        repo = ctx.git.main_root(x.get("cwd") or "")
        if not repo or (scope and not in_scope(repo, scope)):
            continue
        repos.add(repo)
        branch = ctx.git.run(x["cwd"], "branch", "--show-current")
        if (repo, branch) in linked_branches:
            continue
        ahead, dirty = ctx.git.git_state(x["cwd"], branch, ctx.git.base_branch(repo))
        if x.get("agent_status") == "working" or (ahead or 0) > 0 or (dirty or 0) > 0:
            found.append(f"  pane {x['pane_id']} [{labels.get(x.get('workspace_id'), '')}] {x.get('agent')} "
                         f"{x.get('agent_status')} {Path(repo).name}:{branch} ahead={ahead} dirty={dirty} "
                         f"— {x.get('terminal_title_stripped', '')[:60]}")
    for repo in repos | {t["repo"] for t in active}:
        base = ctx.git.base_branch(repo)
        porcelain = ctx.git.run(repo, "worktree", "list", "--porcelain") or ""
        for block in porcelain.split("\n\n"):
            path = re.search(r"^worktree (.+)$", block, re.M)
            branch = re.search(r"^branch refs/heads/(.+)$", block, re.M)
            if not path or not branch or branch.group(1) == base or (repo, branch.group(1)) in linked_branches:
                continue
            if any(t["repo"] == repo and t.get("branch") == branch.group(1) for t in tasks):
                continue
            ahead, dirty = ctx.git.git_state(path.group(1), branch.group(1), base)
            if (ahead or 0) > 0 or (dirty or 0) > 0:
                found.append(f"  worktree {path.group(1)} {Path(repo).name}:{branch.group(1)} "
                             f"ahead={ahead} dirty={dirty}")
    ctx.out.line("\nUnregistered work:")
    ctx.out.line("\n".join(dict.fromkeys(found)) if found else "  (none)")


SMALL_SOURCE = 40   # a change the PM may read and land without a reviewer (playbook §4): source lines …
SMALL_TOTAL = 150   # … and all lines, tests and evidence included


def cmd_diff(a, ctx=None):
    """What a task's branch changes against its base, without the diff text: the diffstat, line totals (all, and
    source without tests and evidence), deleted, binary and UI files, and whether it is small enough for the PM to
    read itself (§4). A worktree that is gone is not needed: the branch is read from the main checkout."""
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    try:
        task = Ledger(ctx).load(a.id).raw
    except (StoreError, IdentityError):
        raise
    except PmError as e:
        exit_with(ctx, e)
    a.id = task["id"]
    worktree, branch = task.get("worktree"), task.get("branch")
    repo = worktree if worktree and Path(worktree).is_dir() else task["repo"]
    if not branch:
        sys.exit(tr(f"{a.id} has no branch", f"{a.id} 没有分支"))
    base = ctx.git.merge_target(task["repo"], task["base"])
    span = f"{base}...{branch}"
    named = ("-c", "core.quotepath=off")  # file names as they are, not quoted octal escapes
    numstat = ctx.git.run(repo, *named, "diff", "--numstat", "-z", span)
    if numstat is None:
        sys.exit(tr(f"git diff {span} failed in {repo}", f"在 {repo} 里 git diff {span} 失败"))
    files, tokens = [], iter(numstat.split("\0"))
    for token in tokens:
        if not token.strip():
            continue
        added, removed, path = token.lstrip("\n").split("\t", 2)
        if not path:  # a rename: the old and new names follow
            next(tokens, "")
            path = next(tokens, "")
        binary = added == "-"
        files.append((0 if binary else int(added), 0 if binary else int(removed), path, binary))
    deleted = [p for p in (ctx.git.run(repo, *named, "diff", "--name-only", "-z", "--diff-filter=D", span) or "").split("\0")
               if p.strip()]
    source = [f for f in files if not side_file(f[2])]
    binaries = [f[2] for f in files if f[3]]
    on_branch = lambda p: ctx.git.run(repo, "show", f"{branch}:{p}") if p.endswith(".swift") else None  # for its imports
    ui = [f[2] for f in files if ui_file(f[2], on_branch(f[2]))]
    ctx.out.line(f"git diff --stat {span}")
    ctx.out.line(ctx.git.run(repo, *named, "diff", "--stat", span) or tr("(no changes)", "（没有改动）"))
    total = lambda fs: (len(fs), sum(f[0] for f in fs), sum(f[1] for f in fs))
    n, plus, minus = total(files)
    all_lines = plus + minus
    ctx.out.line(tr(f"total: {n} files, +{plus} -{minus} ({all_lines} lines)",
                    f"合计：{n} 个文件，+{plus} -{minus}（{all_lines} 行）"))
    n, plus, minus = total(source)
    source_lines = plus + minus
    ctx.out.line(tr(f"source (without tests and evidence): {n} files, +{plus} -{minus} ({source_lines} lines)",
                    f"源码（不含测试和 evidence）：{n} 个文件，+{plus} -{minus}（{source_lines} 行）"))
    for label, names in ((tr("deleted: ", "删除的文件："), deleted), (tr("binary: ", "二进制："), binaries),
                         (tr("UI (visual result): ", "界面文件（有视觉结果）："), ui)):
        if names:
            ctx.out.line(label + ", ".join(names))
    if worktree and repo != worktree:
        ctx.out.line(tr(f"worktree gone; read from {repo}", f"worktree 已不在，从 {repo} 读取"))
    else:
        _, dirty = ctx.git.git_state(repo, None, base)
        if dirty:
            ctx.out.line(tr(f"uncommitted in {repo}: {dirty} files (not counted)",
                            f"{repo} 里有 {dirty} 个未提交的文件（未计入）"))
    why = [w for w, hit in (
        (tr(f"{source_lines} source lines > {SMALL_SOURCE}", f"源码 {source_lines} 行 > {SMALL_SOURCE}"),
         source_lines > SMALL_SOURCE),
        (tr(f"{all_lines} lines in all > {SMALL_TOTAL}", f"总计 {all_lines} 行 > {SMALL_TOTAL}"), all_lines > SMALL_TOTAL),
        (tr("deletes files", "删除了文件"), deleted), (tr("binary files", "有二进制文件"), binaries),
        (tr("UI files", "改了界面文件"), ui)) if hit]
    ctx.out.line(tr(f"small (§4): no, {'; '.join(why)}: start a reviewer" if why else
                    "small (§4): yes, unless it touches release, security or a protocol, or shows on screen: read the diff "
                    "yourself",
                    f"小改动（§4）：否，{'；'.join(why)}：开审查线程" if why else
                    "小改动（§4）：是，只要不涉及发布、安全、协议，也不改界面：自己读 diff"))


def side_file(path):
    """A test or evidence: not counted as source by `diff`. Docs count: for an agent, a playbook is code."""
    path = path.lower()  # Tests/ in a Swift package
    name = Path(path).name
    return (path.startswith(("evidence/", "tests/", "test/")) or "/tests/" in path or "/test/" in path
            or name.startswith("test_") or ".test." in name
            or name.endswith(("_test.py", "_test.go", ".spec.js", ".spec.ts")))


UI_SUFFIXES = (".css", ".scss", ".html", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".jsx", ".tsx", ".vue",
               ".svelte", ".xib", ".storyboard")


def ui_file(path, text=None):
    """A file whose change shows on screen: styles, pages, images, components, Xcode interface files and asset
    catalogs, a Swift file that imports SwiftUI or UIKit (text: its content on the branch), and a mod's own code and
    manifest (mods/<mod>/*.js, mod.json, its assets), whose result is visual. Tests are not. Other native UI (an
    AppKit view, another toolkit) does not show in a name: the PM judges it (§4)."""
    name = Path(path).name.lower()
    if side_file(path):
        return False
    if name.endswith(UI_SUFFIXES) or ".xcassets/" in path:
        return True
    if text and name.endswith(".swift") and re.search(r"^\s*import\s+(SwiftUI|UIKit)\b", text, re.M):
        return True
    parts = Path(path).parts
    return len(parts) >= 3 and parts[0] == "mods" and "scripts" not in parts and (
        name.endswith((".js", ".mjs", ".ts")) or name == "mod.json")


def cmd_find(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    pm = ProjectRegistry(ctx).find_pm(repo=a.repo)
    if not pm:
        sys.exit(1)
    ctx.out.line(pm["pane_id"])


def register_status_views(sub):
    l = sub.add_parser("log")
    l.add_argument("id")
    l.add_argument("text")
    sh = sub.add_parser("show", help="a task's status, branch and latest ledger entries")
    sh.add_argument("id")
    sh.add_argument("--json", action="store_true", help="print the whole record as JSON (the old output)")
    b = sub.add_parser("board")
    b.add_argument("--post", action="store_true", help="mirror the board to the configured Discord channel")
    b.add_argument("--channel", help="set (or change) the Discord board channel, then post")
    so = sub.add_parser("status", help="PMs, this project's open tasks and unregistered work")
    so.add_argument("--all", action="store_true", help="every project, not only this one")
    so.add_argument("--closed", action="store_true", help="closed tasks too (done, merged, released, …)")
    so.add_argument("--repo", default=".")
    df = sub.add_parser("diff", help="what a task's branch changes: the diffstat and line totals, no diff text")
    df.add_argument("id")
    sub.add_parser("find").add_argument("--repo", default=".")
