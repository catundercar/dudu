#!/usr/bin/env python3
"""Task ledger and herdr helpers for the pm skill.

State lives in ~/.claude/pm (override with PM_HOME): one JSON file per task in
tasks/, and BOARD.md, which is regenerated after every write. Each project has
its own PM: the herdr agent named "pm-<project slug>". PM registrations live in
pms/, and discord.json holds the
optional board channel that BOARD.md is mirrored to.
"""
import argparse
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("PM_HOME", Path.home() / ".claude" / "pm"))
TASKS = STATE / "tasks"
PMS = STATE / "pms"
BOARD = STATE / "BOARD.md"
DISCORD_CFG = STATE / "discord.json"
DISCORD_HOME = Path(os.environ.get("DISCORD_HOME", Path.home() / ".claude" / "channels" / "discord"))
DISCORD_TOKEN_FILE = DISCORD_HOME / "pm-token.env"
DISCORD_PLUGIN_ROOT = Path.home() / ".claude" / "plugins" / "cache" / "claude-plugins-official" / "discord"
MCP_DIR = STATE / "mcp"
MCP_SERVER = "discord-pm"
DISCORD_API = "https://discord.com/api/v10"
ACTIVE = ["proposed", "in_progress", "review", "blocked", "paused"]
CLOSED = ["merged", "released", "done", "abandoned"]
# A session is identified by its herdr pane, or in the herdr desktop app by its herdr-core terminal ("hc:t7").
HC_TERMINAL = os.environ.get("HC_TERMINAL_ID", "")
PANE = os.environ.get("HERDR_PANE_ID", "") or (f"hc:{HC_TERMINAL}" if HC_TERMINAL else "")
WORKSPACE = os.environ.get("HERDR_WORKSPACE_ID", "")
PROJECTS = STATE / "projects"
# Above this many context tokens a PM is told to hand over at the next task boundary.
ROTATE_TOKENS = int(os.environ.get("PM_ROTATE_TOKENS", "200000"))


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def herdr(*args):
    """Return the `result` object of a herdr CLI call, or None outside herdr."""
    try:
        out = subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout)["result"]
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        return None


def agents():
    return (herdr("agent", "list") or {}).get("agents", [])


def hc(*args):
    """Parsed JSON of a herdr-core CLI call, or None when hc is missing or the call fails."""
    try:
        # --json goes before a "--": what follows that belongs to the program being started.
        cut = args.index("--") if "--" in args else len(args)
        out = subprocess.run(["hc", *args[:cut], "--json", *args[cut:]], capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def hc_pm(root):
    """The registered herdr-core PM of the project at root, if its terminal is live and still labelled pm=<project>."""
    path = PMS / f"{project_slug(root)}.json"
    rec = json.loads(path.read_text()) if path.exists() else {}
    if rec.get("runtime") != "hc" or not rec.get("terminal"):
        return None
    term = hc("get", rec["terminal"]) or {}
    if term.get("state") != "live" or (term.get("labels") or {}).get("pm") != Path(root).name:
        return None
    return {"pane_id": f"hc:{rec['terminal']}", "name": rec["name"], "cwd": term.get("cwd"),
            "agent_status": (term.get("status") or {}).get("state", ""), "workspace_id": ""}


def project_slug(repo):
    """Lowercase project name usable in a herdr agent name."""
    return re.sub(r"[^a-z0-9_-]+", "-", Path(repo).resolve().name.lower()).strip("-")[:28] or "project"


def pm_name(repo):
    return f"pm-{project_slug(repo)}"


def find_pm(listing=None, repo=None):
    """The PM agent for the project containing repo (default: the current directory).

    The PM is the herdr agent named pm-<project slug>, or the herdr-core terminal its registration names
    (runtime "hc"); outside a repository there is none. The registration decides when both exist.
    """
    listing = agents() if listing is None else listing
    root = project_root(repo or ".")
    if not root:
        return None
    in_hc = hc_pm(root)
    if in_hc:
        return in_hc
    want = pm_name(root)
    pms = [a for a in listing if a.get("name") == want]
    pms.sort(key=lambda a: a.get("workspace_id") != WORKSPACE)
    return pms[0] if pms else None


def pm_record(repo):
    """The registration file of the PM for repo, or None."""
    root = project_root(repo or ".")
    path = PMS / f"{project_slug(root)}.json" if root else None
    return json.loads(path.read_text()) if path and path.exists() else None


def git(path, *args):
    try:
        r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def main_root(path):
    """The main checkout of the repository containing path, so worktrees map to one project."""
    common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return str(Path(common).parent) if common else None


def project_root(path):
    """Main checkout of the repository containing path, or the directory itself when it is not under git.

    A PM can coordinate a plain working directory (for example an issue-triage folder).
    """
    root = main_root(path)
    if root:
        return root
    d = Path(path).resolve()
    return str(d) if d.is_dir() else None


def base_branch(repo):
    for name in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet", name) is not None:
            return name
    return "HEAD"


def git_state(path, branch, base):
    """(commits on branch not in base, changed files in path) or (None, None)."""
    ahead = git(path, "rev-list", "--count", f"{base}..{branch}") if branch else None
    status = git(path, "status", "--porcelain") if path and Path(path).is_dir() else None
    dirty = None
    if status is not None:
        # Linked tool caches such as `.tools` are expected in fresh worktrees.
        dirty = len([l for l in status.splitlines() if l and not l.endswith(" .tools")])
    return (int(ahead) if ahead and ahead.isdigit() else None), dirty


# ---- ledger -----------------------------------------------------------------

def load(task_id):
    path = TASKS / f"{task_id}.json"
    if not path.exists():
        sys.exit(f"no task {task_id}")
    return json.loads(path.read_text())


def save(task):
    TASKS.mkdir(parents=True, exist_ok=True)
    task["updated"] = now()
    tmp = TASKS / f".{task['id']}.json.tmp"
    tmp.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(TASKS / f"{task['id']}.json")
    write_board()
    post_board()


def all_tasks():
    if not TASKS.exists():
        return []
    return sorted((json.loads(p.read_text()) for p in TASKS.glob("*.json")),
                  key=lambda t: t.get("updated", ""), reverse=True)


def note(task, text):
    task.setdefault("log", []).append({"at": now(), "by": PANE or "user", "text": text})


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40].strip("-")


def new_id(project, hint):
    base = f"{project}-{slugify(hint) or datetime.datetime.now().strftime('%m%d-%H%M')}"
    candidate, n = base, 2
    while (TASKS / f"{candidate}.json").exists():
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def write_board():
    tasks = all_tasks()
    lines = [f"# PM Board", "", f"Updated {now()}. Ledger: `{TASKS}`.", ""]
    for project in sorted({t["project"] for t in tasks}):
        mine = [t for t in tasks if t["project"] == project]
        active = [t for t in mine if t["status"] in ACTIVE]
        closed = [t for t in mine if t["status"] in CLOSED][:8]
        lines += [f"## {project}", "", "| Task | Status | Owner | Where | Branch | Updated | Latest |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for t in active + closed:
            latest = (t.get("log") or [{}])[-1].get("text", "").replace("|", "/")[:80]
            where = " ".join(x for x in (t.get("pane"), t.get("agent")) if x)
            lines.append(f"| {t['title']} (`{t['id']}`) | {t['status']} | {t.get('owner', '')} | {where} "
                         f"| {t.get('branch') or ''} | {t['updated'][5:]} | {latest} |")
        lines.append("")
    STATE.mkdir(parents=True, exist_ok=True)
    BOARD.write_text("\n".join(lines))


# ---- discord ----------------------------------------------------------------

def discord_token():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token and DISCORD_TOKEN_FILE.exists():
        m = re.search(r"^DISCORD_BOT_TOKEN=(.+)$", DISCORD_TOKEN_FILE.read_text(), re.M)
        token = m.group(1).strip() if m else None
    return token


def discord_api(method, path, body=None):
    """One Discord REST call with the bot token; returns the parsed JSON or None."""
    import urllib.error
    import urllib.request
    token = discord_token()
    if not token:
        return None
    req = urllib.request.Request(f"{DISCORD_API}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                                          "User-Agent": "pm.py (herdr PM skill)"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        hook_log(f"discord {method} {path}: HTTP {e.code} {e.read()[:200]!r}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        hook_log(f"discord {method} {path}: {e!r}")
    return None


def hook_log(text):
    """Append one line to ~/.claude/pm/hook-mirror.log; hooks must never fail, so failures are logged instead."""
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with open(STATE / "hook-mirror.log", "a") as f:
            f.write(f"{now()} [{PANE or '-'}] {text}\n")
    except OSError:
        pass


def discord_cfg():
    return json.loads(DISCORD_CFG.read_text()) if DISCORD_CFG.exists() else {}


def board_text():
    """BOARD.md condensed for a single Discord message (limit 2000 chars)."""
    tasks = all_tasks()
    lines = [f"**PM Board** · {now()}"]
    for project in sorted({t["project"] for t in tasks}):
        pm = pm_record_for_project(project)
        where = f" · PM {pm['pane']}" if pm and pm.get("pane") else ""
        lines.append(f"\n__{project}__{where}")
        for t in [t for t in tasks if t["project"] == project and t["status"] in ACTIVE]:
            latest = (t.get("log") or [{}])[-1].get("text", "").replace("\n", " ")[:60]
            who = " ".join(x for x in (t.get("pane"), t.get("agent")) if x) or t.get("owner", "")
            lines.append(f"• `{t['status']}` {t['title']} — {who} · {latest}")
        if not any(t["project"] == project and t["status"] in ACTIVE for t in tasks):
            lines.append("• (no active tasks)")
    text = "\n".join(lines)
    return text if len(text) <= 1900 else text[:1880] + "\n…(truncated)"


def pm_record_for_project(project):
    for p in PMS.glob("*.json") if PMS.exists() else []:
        rec = json.loads(p.read_text())
        if rec.get("project") == project:
            return rec
    return None


def post_board(force=False):
    """Mirror the board into the configured Discord channel by editing one message in place.

    Best effort: never fails the ledger write. Returns True when the message was updated.
    """
    cfg = discord_cfg()
    channel = cfg.get("board_channel")
    if not channel or (os.environ.get("PM_NO_DISCORD") and not force):
        return False
    body = {"content": board_text()}
    if cfg.get("message_id"):
        if discord_api("PATCH", f"/channels/{channel}/messages/{cfg['message_id']}", body):
            return True
        cfg.pop("message_id", None)  # deleted by hand; post a fresh one
    created = discord_api("POST", f"/channels/{channel}/messages", body)
    if not created or "id" not in created:
        return False
    cfg["message_id"] = created["id"]
    DISCORD_CFG.write_text(json.dumps(cfg, indent=2) + "\n")
    return True


def discord_state_dir(repo):
    return DISCORD_HOME / pm_name(repo)


def write_discord_state(repo, channel_id, user_ids):
    """Per-PM plugin state: own .env (token) and an access.json that admits only this PM's channel."""
    sdir = discord_state_dir(repo)
    sdir.mkdir(parents=True, exist_ok=True)
    token = discord_token()
    if not token:
        sys.exit(f"no bot token: put DISCORD_BOT_TOKEN=... in {DISCORD_TOKEN_FILE}")
    env = sdir / ".env"
    env.write_text(f"DISCORD_BOT_TOKEN={token}\n")
    env.chmod(0o600)
    access_file = sdir / "access.json"
    access = json.loads(access_file.read_text()) if access_file.exists() else {}
    # "disabled" would drop guild messages too; allowlist with nobody drops DMs silently and keeps the channel.
    access.update({"dmPolicy": "allowlist", "allowFrom": [], "pending": {}})
    access.setdefault("groups", {})[str(channel_id)] = {"requireMention": False, "allowFrom": list(user_ids)}
    access_file.write_text(json.dumps(access, indent=2) + "\n")
    access_file.chmod(0o600)
    write_mcp_config(repo)
    return sdir


def plugin_root():
    """Newest installed version of the official discord plugin."""
    versions = sorted(DISCORD_PLUGIN_ROOT.glob("*/server.ts"), key=lambda p: p.parent.name)
    if not versions:
        sys.exit(f"discord plugin not installed under {DISCORD_PLUGIN_ROOT}")
    return versions[-1].parent


def mcp_config_path(repo):
    return MCP_DIR / f"{pm_name(repo)}.json"


def write_mcp_config(repo):
    """A session-only MCP config that runs the plugin's server with this PM's state dir.

    Claude Code does not pass the parent environment to plugin MCP servers, so the
    state dir has to be set through a server config's env block.
    """
    MCP_DIR.mkdir(parents=True, exist_ok=True)
    cfg = {"mcpServers": {MCP_SERVER: {
        "command": "bun",
        "args": ["run", "--cwd", str(plugin_root()), "--shell=bun", "--silent", "start"],
        "env": {"DISCORD_STATE_DIR": str(discord_state_dir(repo))}}}}
    mcp_config_path(repo).write_text(json.dumps(cfg, indent=2) + "\n")
    return mcp_config_path(repo)


def launch_command(repo, resume=None):
    # A manually configured server only counts as a channel through the development-channels flag.
    # Do not also pass --channels for it: the first matching entry wins and that one is not marked dev.
    return (f"claude --mcp-config {mcp_config_path(repo)} "
            f"--dangerously-load-development-channels server:{MCP_SERVER}"
            + (f" --resume {resume}" if resume else "") + " <your usual flags>")


# ---- commands ---------------------------------------------------------------

FIELDS = ["title", "status", "owner", "workspace", "pane", "agent", "branch", "worktree",
          "base", "brief", "commit", "release"]


def cmd_new(a):
    repo = project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    project = Path(repo).name
    pm = find_pm()
    task = {"id": new_id(project, a.slug or a.branch or a.title), "title": a.title, "project": project,
            "repo": repo, "status": a.status, "base": a.base or base_branch(repo),
            "owner": a.owner or ("pm" if pm and pm.get("pane_id") == PANE else "self"),
            # An explicit empty --pane/--workspace records work that is not tied to this session.
            "workspace": WORKSPACE if a.workspace is None else a.workspace,
            "pane": PANE if a.pane is None else a.pane, "created": now()}
    for f in ("agent", "branch", "worktree", "brief"):
        if getattr(a, f):
            task[f] = getattr(a, f)
    note(task, a.note or f"registered ({task['status']})")
    save(task)
    print(task["id"])
    return task["id"]


def cmd_update(a):
    task = load(a.id)
    changes = []
    for f in FIELDS:
        value = getattr(a, f, None)
        if value is not None and task.get(f) != value:
            changes.append(f"{f}={value}")
            task[f] = value
    if a.note or changes:
        note(task, "; ".join(x for x in [", ".join(changes), a.note] if x))
    save(task)
    print(f"{task['id']}: {task['status']}")
    # A merged task that the PM dispatched is cleaned up at once; its worker, worktree and branch have no further use.
    if "status=merged" in changes and task.get("dispatched") and not a.keep:
        try:
            cmd_retire(argparse.Namespace(id=task["id"], force=False))
        except SystemExit as stop:
            print(f"not retired: {stop}. Fix that, then run `pm.py retire {task['id']}`.")


def needs_cleanup(task):
    """Merged or released, but its worker terminal, worktree or branch has not been removed with `retire`."""
    return task["status"] in ("merged", "released") and not task.get("retired") and bool(
        task.get("branch") or task.get("worktree"))


def cmd_log(a):
    task = load(a.id)
    note(task, a.text)
    save(task)


def cmd_show(a):
    task = load(a.id)
    ahead, dirty = git_state(task.get("worktree") or task["repo"], task.get("branch"), task["base"])
    print(json.dumps({**task, "live": {"ahead": ahead, "dirty": dirty}}, ensure_ascii=False, indent=2))


def cmd_board(a):
    write_board()
    if a.post or a.channel:
        cfg = discord_cfg()
        if a.channel:
            cfg = {"board_channel": str(a.channel)}  # new channel: start a fresh message
            STATE.mkdir(parents=True, exist_ok=True)
            DISCORD_CFG.write_text(json.dumps(cfg, indent=2) + "\n")
        if not cfg.get("board_channel"):
            sys.exit("no board channel configured; pass --channel <id> once")
        print("board posted to Discord" if post_board(force=True) else "posting to Discord failed")
        return
    print(BOARD.read_text())


def cmd_status(a):
    listing = agents()
    by_pane = {x["pane_id"]: x for x in listing}
    labels = {w["workspace_id"]: w.get("label") for w in (herdr("workspace", "list") or {}).get("workspaces", [])}
    pm_panes = {x["pane_id"] for x in listing if str(x.get("name") or "").startswith("pm-")}
    print("PMs:")
    for x in listing:
        if x["pane_id"] in pm_panes:
            rec = pm_record(x.get("cwd") or ".")
            discord = f" discord #{rec['discord']['channel_id']}" if rec and rec.get("discord") else ""
            print(f"  {x['name']}  {x['pane_id']}{' (this session)' if x['pane_id'] == PANE else ''}  "
                  f"{x.get('agent_status')}  {x.get('cwd')}{discord}")
    in_hc = [pm for pm in (hc_pm(json.loads(p.read_text()).get("repo") or "") for p in sorted(PMS.glob("*.json"))
                           if json.loads(p.read_text()).get("runtime") == "hc") if pm] if PMS.exists() else []
    for pm in in_hc:
        print(f"  {pm['name']}  {pm['pane_id']}{' (this session)' if pm['pane_id'] == PANE else ''}  "
              f"{pm['agent_status']}  {pm['cwd']}")
    if not pm_panes and not in_hc:
        print("  (none)")
    tasks = all_tasks()
    # Merged or released work stays listed until `retire` removes its worktree and branch.
    active = [t for t in tasks if t["status"] in ACTIVE or (a.all and t["status"] in CLOSED)
              or (t["status"] in ("merged", "released") and not t.get("retired"))]
    linked_panes, linked_branches = set(), set()
    print("\nTasks:")
    for t in active:
        live = by_pane.get(t.get("pane") or "", {})
        state = live.get("agent_status", "-") if t.get("pane") else "-"
        ahead, dirty = git_state(t.get("worktree") or t["repo"], t.get("branch"), t["base"])
        linked_panes.add(t.get("pane"))
        linked_branches.add((t["repo"], t.get("branch")))
        latest = (t.get("log") or [{}])[-1].get("text", "")[:70]
        print(f"  [{t['status']}] {t['id']}  {t['title']}\n"
              f"      {t.get('pane') or '-'} {live.get('name') or t.get('agent') or ''} agent={state} "
              f"branch={t.get('branch') or '-'} ahead={ahead} dirty={dirty} updated={t['updated'][5:]}\n"
              f"      latest: {latest}"
              + (f"\n      not retired: run `pm.py retire {t['id']}`" if needs_cleanup(t) else ""))
    if not active:
        print("  (none)")
    # Work nobody registered: a busy or diverged pane, or a diverged worktree branch.
    found, repos = [], set()
    for x in listing:
        if x["pane_id"] in linked_panes or x["pane_id"] in pm_panes:
            continue
        repo = main_root(x.get("cwd") or "")
        if not repo:
            continue
        repos.add(repo)
        branch = git(x["cwd"], "branch", "--show-current")
        if (repo, branch) in linked_branches:
            continue
        ahead, dirty = git_state(x["cwd"], branch, base_branch(repo))
        if x.get("agent_status") == "working" or (ahead or 0) > 0 or (dirty or 0) > 0:
            found.append(f"  pane {x['pane_id']} [{labels.get(x.get('workspace_id'), '')}] {x.get('agent')} "
                         f"{x.get('agent_status')} {Path(repo).name}:{branch} ahead={ahead} dirty={dirty} "
                         f"— {x.get('terminal_title_stripped', '')[:60]}")
    for repo in repos | {t["repo"] for t in active}:
        base = base_branch(repo)
        porcelain = git(repo, "worktree", "list", "--porcelain") or ""
        for block in porcelain.split("\n\n"):
            path = re.search(r"^worktree (.+)$", block, re.M)
            branch = re.search(r"^branch refs/heads/(.+)$", block, re.M)
            if not path or not branch or branch.group(1) == base or (repo, branch.group(1)) in linked_branches:
                continue
            if any(t["repo"] == repo and t.get("branch") == branch.group(1) for t in tasks):
                continue
            ahead, dirty = git_state(path.group(1), branch.group(1), base)
            if (ahead or 0) > 0 or (dirty or 0) > 0:
                found.append(f"  worktree {path.group(1)} {Path(repo).name}:{branch.group(1)} "
                             f"ahead={ahead} dirty={dirty}")
    print("\nUnregistered work:")
    print("\n".join(dict.fromkeys(found)) if found else "  (none)")


def cmd_find(a):
    pm = find_pm(repo=a.repo)
    if not pm:
        sys.exit(1)
    print(pm["pane_id"])


def cmd_claim(a):
    # --pane lets the hub register a PM for another pane, usually a shell where the PM is then started.
    pane = a.pane or PANE
    if not pane:
        sys.exit("not running inside a herdr pane; pass --pane")
    repo = project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    pm = find_pm(repo=repo)
    if pm and pm["pane_id"] != pane:
        sys.exit(f"PM for {Path(repo).name} already exists at {pm['pane_id']}; ask the user before replacing it")
    name = pm_name(repo)
    if pane.startswith("hc:"):
        workspace = ""
        if hc("label", pane[3:], f"pm={Path(repo).name}") is None:
            sys.exit(f"hc label {pane[3:]} failed")
    elif pane == PANE:
        workspace = WORKSPACE
        if not herdr("agent", "rename", PANE, name):
            sys.exit(f"herdr agent rename {PANE} {name} failed")
    else:
        # A shell pane has no agent to rename yet: start it with `herdr agent start <name>`.
        workspace = ((herdr("pane", "get", pane) or {}).get("pane") or {}).get("workspace_id")
        if not workspace:
            sys.exit(f"no herdr pane {pane}")
    PMS.mkdir(parents=True, exist_ok=True)
    rec_path = PMS / f"{project_slug(repo)}.json"
    rec = json.loads(rec_path.read_text()) if rec_path.exists() else {}
    rec.update({"project": Path(repo).name, "repo": repo, "name": name, "pane": pane, "workspace": workspace,
                "claimed": now()})
    for key in ("runtime", "terminal"):
        rec.pop(key, None)
    if pane.startswith("hc:"):
        rec.update({"runtime": "hc", "terminal": pane[3:]})
    print(f"{pane} is now {name} (PM for {Path(repo).name})")
    if a.discord_channel:
        users = a.discord_users.split(",") if a.discord_users else default_discord_users()
        sdir = write_discord_state(repo, a.discord_channel, users)
        rec["discord"] = {"channel_id": str(a.discord_channel), "state_dir": str(sdir), "users": users}
        print(f"discord: channel {a.discord_channel} bound; plugin state in {sdir}")
        if pane == PANE and os.environ.get("DISCORD_STATE_DIR") != str(sdir):
            print("this session is not connected to that channel yet. Restart it as:\n  "
                  + launch_command(repo, resume="<session id>"))
    rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    if pane != PANE and not pane.startswith("hc:"):
        flags = launch_command(repo).removeprefix("claude ") if a.discord_channel else "<your usual flags>"
        print(f"start it: herdr agent start {name} --kind claude --pane {pane} -- {flags}")


def default_discord_users():
    """Users already paired with the bot in the shared access.json (the user's own account)."""
    shared = DISCORD_HOME / "access.json"
    try:
        return list(json.loads(shared.read_text()).get("allowFrom", []))
    except (OSError, ValueError):
        return []


def cmd_launch(a):
    repo = project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    print(launch_command(repo, resume=a.resume))


def cmd_notify(a):
    pm = find_pm(repo=a.repo)
    if not pm:
        print("no PM in herdr; the ledger entry is enough")
        return
    if pm["pane_id"] == PANE:
        print("this session is the PM")
        return
    text = f"[from {PANE or 'a session'}] {a.text}"
    if pm["pane_id"].startswith("hc:"):
        result = hc("send", pm["pane_id"][3:], text)
    else:
        result = herdr("agent", "prompt", pm["pane_id"], text)
    print(f"notified PM at {pm['pane_id']}" if result else "notify failed; the ledger entry still records it")


def cmd_dispatch(a):
    repo = main_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not in a git repository")
    brief = Path(a.brief).read_text()
    worker_defaults(a)
    if PANE.startswith("hc:"):
        return dispatch_hc(a, repo, brief)
    created = herdr("worktree", "create", "--cwd", repo, "--branch", a.branch, "--base", a.base or base_branch(repo),
                    "--label", a.label, "--no-focus")
    if not created:
        sys.exit("herdr worktree create failed")
    flat = json.dumps(created)
    workspace = re.search(r'"workspace_id": "([^"]+)"', flat)
    pane = re.search(r'"pane_id": "([^"]+)"', flat)
    path = re.search(r'"path": "([^"]+)"', flat)
    if not (workspace and pane and path):
        sys.exit(f"unexpected worktree create result: {flat[:600]}")
    if a.prep:
        subprocess.run(["zsh", "-c", a.prep], cwd=path.group(1), check=True,
                       env={**os.environ, "MAIN": repo})
    args = ["agent", "start", a.name, "--kind", a.kind, "--pane", pane.group(1)]
    if len(worker_argv(a)) > 1:
        args += ["--", *worker_argv(a)[1:]]
    if not herdr(*args):
        sys.exit(f"agent start failed in {pane.group(1)}")
    if not herdr("agent", "prompt", a.name, brief):
        sys.exit("prompt failed; the agent is running, send the brief by hand")
    # A startup screen (for example codex's hook trust review) can swallow the brief.
    if not herdr("agent", "wait", a.name, "--until", "working", "--timeout", "20000"):
        print(f"warning: {a.name} did not start working; read its screen and resend the brief", file=sys.stderr)
    task = argparse.Namespace(repo=repo, title=a.title, status="in_progress", owner="pm", base=a.base,
                              workspace=workspace.group(1), pane=pane.group(1), agent=a.name, branch=a.branch,
                              worktree=path.group(1), brief=str(Path(a.brief).resolve()), slug=a.label,
                              note=f"dispatched to {a.name} ({' '.join(x for x in (a.kind, a.model, a.effort) if x)})")
    cmd_new(task)
    print(f"workspace={workspace.group(1)} pane={pane.group(1)} worktree={path.group(1)}")


def config():
    """Personal settings: ~/.claude/pm/config.json, for example {"worker": {"kind": "codex", "model": "...", "effort": "high"}}."""
    try:
        return json.loads((STATE / "config.json").read_text())
    except (OSError, ValueError):
        return {}


def tr(en, zh):
    """Built-in text in the configured language: English unless config.json says {"lang": "zh"}."""
    return zh if config().get("lang") == "zh" else en


def worker_defaults(a):
    """Fill the worker's kind, model and effort: the command line wins, then config.json, then the program's own defaults."""
    cfg = config().get("worker") or {}
    a.kind = a.kind or cfg.get("kind") or "codex"
    a.model = a.model or cfg.get("model") or ""
    a.effort = a.effort or cfg.get("effort") or ""
    return a


def worker_argv(a):
    if a.kind == "codex":
        # No update prompt at startup: it would take the place of the input and the brief could not be delivered.
        return (["codex", "-c", "check_for_update_on_startup=false"] + (["-m", a.model] if a.model else [])
                + (["-c", f'model_reasoning_effort="{a.effort}"'] if a.effort else []))
    return [a.kind]


def worker_placement():
    """How `hc run` places a worker: as a sub-agent of the PM's terminal, so the app lists it under the PM,
    and outliving it, because a rotated PM's terminal ends. No notes typed into the PM: the ledger carries progress."""
    return ["--parent", PANE[3:], "--outlive-parent", "--no-notify"] if PANE.startswith("hc:") else ["--no-parent"]


def dispatch_hc(a, repo, brief):
    """Dispatch from a PM in the herdr desktop app: a git worktree and a herdr-core terminal for the worker."""
    base = a.base or base_branch(repo)
    path = Path.home() / ".herdr" / "worktrees" / Path(repo).name / a.branch.replace("/", "-")
    if path.exists():
        sys.exit(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    if git(repo, "worktree", "add", str(path), "-b", a.branch, base) is None:
        sys.exit(f"git worktree add {path} -b {a.branch} {base} failed")
    if a.prep:
        subprocess.run(["zsh", "-c", a.prep], cwd=str(path), check=True, env={**os.environ, "MAIN": repo})
    made = (hc("run", "--bg", *worker_placement(), "--name", a.name, "--cwd", str(path),
               "--", *worker_argv(a)) or {}).get("address")
    if not made:
        sys.exit(f"hc run failed; the worktree {path} is ready, start the worker by hand")
    task = argparse.Namespace(repo=repo, title=a.title, status="in_progress", owner="pm", base=a.base,
                              workspace="", pane=f"hc:{made}", agent=a.name, branch=a.branch,
                              worktree=str(path), brief=str(Path(a.brief).resolve()), slug=a.label,
                              note=f"dispatched to {a.name} ({' '.join(x for x in (a.kind, a.model, a.effort) if x)})")
    task_id = cmd_new(task)
    hc("label", made, f"task={task_id}")
    task = load(task_id)
    task["dispatched"] = True  # `update --status merged` retires only what `dispatch` created
    save(task)
    # The agent needs a moment before its input is ready; a send that comes too early is refused.
    for attempt in range(8):
        time.sleep(3)
        state = ((hc("get", made) or {}).get("status") or {}).get("state")
        if state == "idle" and (hc("send", made, brief) or {}).get("started"):
            break
    else:
        sys.exit(f"the brief was not sent: the worker in hc:{made} is not ready (read its screen: it may be at a "
                 "startup dialog such as folder trust). Send the brief by hand with `hc send`.")
    print(f"pane=hc:{made} worktree={path}")


def hc_terminal_of(task):
    pane = task.get("pane") or ""
    return pane[3:] if pane.startswith("hc:") else ""


def cmd_retire(a):
    task = load(a.id)
    repo, branch, base = task["repo"], task.get("branch"), task["base"]
    worktree = task.get("worktree")
    done = []
    if branch and git(repo, "merge-base", "--is-ancestor", branch, base) is None and not a.force:
        sys.exit(f"{branch} is not merged into {base}; pass --force to discard it")
    # Several tasks can run one after another in the same worktree and terminal: the last one retired removes them.
    others = [t for t in all_tasks() if t["id"] != task["id"] and not t.get("retired")
              and t["status"] not in ("done", "abandoned")]
    if worktree and any(t.get("worktree") == worktree for t in others):
        print(f"{worktree} is kept: another task still uses it")
        worktree = None
    if worktree and Path(worktree).is_dir() and Path(worktree).resolve() != Path(repo).resolve():
        _, dirty = git_state(worktree, None, base)
        if dirty and not a.force:
            sys.exit(f"{worktree} has {dirty} uncommitted changes")
        term = hc_terminal_of(task)
        info = (hc("get", term) or {}) if term and f"hc:{term}" != PANE else {}
        # End the worker's terminal with its worktree, never a PM's or one that sits elsewhere.
        if (info and not (info.get("labels") or {}).get("pm")
                and Path(info.get("cwd") or "/").resolve() == Path(worktree).resolve()):
            if info.get("state") == "live":
                hc("kill", term)
            hc("rm", term)
            done.append(f"terminal hc:{term}")
        listed = herdr("worktree", "list", "--cwd", repo) or {}
        owned = [w for w in listed.get("worktrees", [])
                 if Path(w.get("path", "")).resolve() == Path(worktree).resolve() and w.get("open_workspace_id")]
        tools = Path(worktree) / ".tools"
        if tools.is_symlink():
            tools.unlink()
        # Only a workspace that herdr opened for this worktree is removed with it.
        if owned and owned[0]["open_workspace_id"] != WORKSPACE:
            herdr("worktree", "remove", "--workspace", owned[0]["open_workspace_id"], "--force")
        else:
            git(repo, "worktree", "remove", "--force", worktree)
        if not Path(worktree).is_dir():
            done.append(f"worktree {worktree}")
    if branch and branch != base:
        # Merged was checked above; -D because git's own check compares with the checked-out branch.
        if git(repo, "branch", "-D", branch) is not None:
            done.append(f"branch {branch}")
    task["retired"] = now()
    if task["status"] in ACTIVE:
        task["status"] = "abandoned" if a.force else "merged"
    note(task, "retired: removed " + (", ".join(done) or "nothing"))
    save(task)
    print(f"{task['id']} retired: removed " + (", ".join(done) or "nothing"))


def cmd_hook_session_start(a):
    """SessionStart hook: tell a session inside herdr whether a PM exists."""
    if not PANE or (os.environ.get("HERDR_ENV") != "1" and not HC_TERMINAL):
        return
    pm = find_pm()
    if not pm:
        # A restarted PM loses its herdr name; restore it from the registration for this pane.
        rec = pm_record_for_pane(PANE, require_discord=False)
        if rec and herdr("agent", "rename", PANE, rec["name"]):
            pm = {"pane_id": PANE, "name": rec["name"]}
        else:
            return
    if pm["pane_id"] == PANE:
        print(f"You are {pm.get('name')}, the PM for this project (pm skill). Ledger board: ~/.claude/pm/BOARD.md. "
              "If you have not read it in this session, run `pm.py handover` before anything else.")
        return
    print(f"A PM coordinator ({pm.get('name')}) runs in {pm['pane_id']}. Before implementing a non-trivial change, "
          "load the pm skill: register the task in the ledger (or hand it to the PM if the user asks), "
          "and mark it `review` when it is ready to merge.")


def pm_record_for_pane(pane, require_discord=True):
    for path in PMS.glob("*.json") if PMS.exists() else []:
        rec = json.loads(path.read_text())
        if rec.get("pane") == pane and (rec.get("discord", {}).get("channel_id") or not require_discord):
            return rec
    return None


def chunks(text, size=1900, limit=3):
    parts = []
    while text and len(parts) < limit:
        cut = text.rfind("\n", 0, size) if len(text) > size else len(text)
        cut = cut if cut > size // 2 else size
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        parts[-1] = parts[-1][:size - 30] + tr("\n…(truncated; the full text is in the terminal)", "\n…(已截断，完整内容见终端)")
    return parts


def last_reply(transcript):
    """Final assistant text of the last turn in a Claude Code transcript, or None if the turn answered on Discord.

    Returns "" while the final message is not written yet: the transcript has one row per content block,
    so until then the last row is a tool call or result and the newest text is only a progress note.
    """
    text, replied_on_discord, final_written = None, False, None
    for line in Path(transcript).read_text().splitlines()[::-1]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if final_written is None and row.get("type") in ("user", "assistant"):
            final_written = row["type"] == "assistant" and isinstance(content, list) and any(
                b.get("type") == "text" and b.get("text", "").strip() for b in content)
        if row.get("type") == "user":
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
            if any(b.get("type") == "text" for b in blocks):
                break  # the prompt that started this turn
        elif row.get("type") == "assistant" and isinstance(content, list):
            if any(b.get("type") == "tool_use" and "discord" in str(b.get("name", "")) and str(b.get("name", "")).endswith("__reply")
                   for b in content):
                replied_on_discord = True
            if text is None:
                texts = [b["text"] for b in content if b.get("type") == "text" and b.get("text", "").strip()]
                if texts:
                    text = "\n".join(texts)
    if replied_on_discord:
        return None
    return text if final_written and text else ""


def cmd_hook_mirror(a):
    """UserPromptSubmit/Stop hook: mirror a PM session's terminal chat into its Discord channel."""
    try:
        data = json.load(sys.stdin)
    except ValueError as e:
        hook_log(f"bad stdin: {e!r}")
        return
    event = data.get("hook_event_name", "")
    if event == "UserPromptSubmit" and PANE and pm_record_for_pane(PANE, require_discord=False):
        # What a UserPromptSubmit hook prints is added to the session's context.
        used = context_tokens(data.get("transcript_path") or "")
        if used > ROTATE_TOKENS:
            print(f"[pm] This PM session holds {used // 1000}k context tokens (limit {ROTATE_TOKENS // 1000}k). "
                  "Finish the step in hand, then hand over: `pm.py rotate --notes \"<what the ledger does not say>\"`.")
    rec = pm_record_for_pane(PANE) if PANE else None
    if not rec or os.environ.get("PM_NO_DISCORD"):
        return
    if event == "UserPromptSubmit":
        prompt = (data.get("prompt") or "").strip()
        if not prompt or prompt.startswith("<") or prompt.startswith("/"):
            return  # task notifications, channel relays, slash commands
        # Prompts typed in by another agent (`pm.py notify`, briefs) start with "[from <pane>]".
        sender = re.match(r"\[from ([^\]]+)\]\s*", prompt)
        text = f"**{sender.group(1)}**\n{prompt[sender.end():]}" if sender else f"**{tr('You', '你')}**\n{prompt}"
    elif event == "Stop":
        path = data.get("transcript_path") or ""
        if not Path(path).exists():
            hook_log(f"Stop: transcript missing: {path!r}; keys={sorted(data)}")
            return
        import time
        reply = ""
        for attempt in range(8):  # the final message may be appended to the transcript after the hook starts
            reply = last_reply(path)
            if reply != "":  # text found, or None = this turn answered on Discord already
                break
            time.sleep(0.5)
        if reply is None:
            hook_log("Stop: turn answered on Discord via reply; not mirrored")
            return
        if not reply:
            hook_log(f"Stop: no final text in transcript after 4s: {path}")
            return
        text = f"**{rec['name']}**\n{reply}"
    else:
        return
    channel = rec["discord"]["channel_id"]
    for part in chunks(text):
        if not discord_api("POST", f"/channels/{channel}/messages", {"content": part, "flags": 4}):  # 4 = suppress embeds
            hook_log(f"{event}: post failed ({len(part)} chars)")
            return
    hook_log(f"{event}: mirrored {len(text)} chars")


# ---- rotation: the PM is the project's record, not one session ----------------

def project_dir(repo):
    d = PROJECTS / project_slug(repo)
    d.mkdir(parents=True, exist_ok=True)
    return d


def own_transcript():
    """Transcript file of the Claude Code session running this command, or ""."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    hits = list((Path.home() / ".claude" / "projects").glob(f"*/{sid}.jsonl")) if sid else []
    return str(hits[0]) if hits else ""


def transcript_rows(path):
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not row.get("isSidechain"):
            yield row


def context_tokens(path):
    """Context size of a session: the input side of its latest model call."""
    used = 0
    for row in transcript_rows(path):
        usage = (row.get("message") or {}).get("usage") if row.get("type") == "assistant" else None
        if usage:
            used = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens",
                                                   "cache_creation_input_tokens"))
    return used


def conversation_tail(path, turns=6, width=700):
    """The last exchanges of a session: what the user typed and the PM's final text of that turn."""
    out, current = [], None
    for row in transcript_rows(path):
        content = (row.get("message") or {}).get("content")
        if row.get("type") == "user":
            text = content if isinstance(content, str) else "\n".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            text = text.strip()
            if text and not text.startswith("<"):  # tool results and system notices are not the user speaking
                current = {"user": text, "pm": ""}
                out.append(current)
        elif row.get("type") == "assistant" and current is not None and isinstance(content, list):
            texts = [b["text"] for b in content if b.get("type") == "text" and b.get("text", "").strip()]
            if texts:
                current["pm"] = "\n".join(texts)  # later rows overwrite: the final message wins
    clip = lambda t: t if len(t) <= width else t[:width] + " …"
    return [{"user": clip(t["user"]), "pm": clip(t["pm"])} for t in out[-turns:]]


def cmd_decide(a):
    repo = project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    line = f"- {now()[:10]} {a.text}" + (tr(f' — the user\'s words: "{a.quote}"', f" — 用户原话：「{a.quote}」") if a.quote else "")
    with open(project_dir(repo) / "decisions.md", "a") as f:
        f.write(line + "\n")
    print(line)


def cmd_context(a):
    path = a.transcript or own_transcript()
    if not path:
        sys.exit("no transcript: pass --transcript")
    used = context_tokens(path)
    print(f"{used // 1000}k context tokens (hand over above {ROTATE_TOKENS // 1000}k)")


def cmd_handover(a):
    """Everything a fresh PM session needs, from the project's record on disk."""
    repo = project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    rec, d, name = pm_record(repo) or {}, project_dir(repo), Path(repo).name
    out = [f"# Handover: PM of {name}", "",
           f"You are {pm_name(repo)}. Repository: {repo}. This text is the project's record; trust it over anything "
           "you think you remember, and do not read the previous session's transcript.",
           "Then read `references/pm-playbook.md` of the pm skill."]
    profile = Path(repo) / ".claude" / "coordination.md"
    if profile.exists():
        out.append(f"Project profile (read it): {profile}")
    for title, path in (("Decisions the user has made", d / "decisions.md"),
                        ("Notes from the previous PM", d / "handover.md")):
        if path.exists() and path.read_text().strip():
            out += ["", f"## {title}", path.read_text().strip()]
    tasks = [t for t in all_tasks() if t.get("project") == name and str(Path(t["repo"]).resolve()) == repo]
    active = [t for t in tasks if t["status"] in ACTIVE or (t["status"] in ("merged", "released") and not t.get("retired"))]
    out += ["", "## Open work"] + ([] if active else ["(none)"])
    for t in active:
        where = " ".join(f"{k}={t[k]}" for k in ("pane", "agent", "branch", "worktree", "brief") if t.get(k))
        out.append(f"- [{t['status']}] {t['id']}: {t['title']} (owner {t.get('owner')}; {where})")
        out += [f"    {e['at']} {e['by']}: {e['text'][:400]}" for e in (t.get("log") or [])[-3:]]
    day_ago = (datetime.datetime.now() - datetime.timedelta(hours=48)).strftime("%Y-%m-%d %H:%M")
    closed = [t for t in tasks if t not in active and t.get("updated", "") >= day_ago]
    if closed:
        out += ["", "## Closed in the last 48 h"] + [f"- [{t['status']}] {t['id']}: {t['title']}" for t in closed]
    tail = conversation_tail((rec.get("previous") or {}).get("transcript") or "", turns=a.turns)
    if tail:
        out += ["", "## The last exchanges with the user (previous session, shortened)"]
        for t in tail:
            out += [f"{tr('User', '用户')}: {t['user']}", f"PM: {t['pm'] or '(no final text)'}", ""]
    print("\n".join(out))


# Flags of the outgoing PM whose value is carried over to its successor.
KEEP_VALUE = ("--mcp-config", "--dangerously-load-development-channels", "--permission-mode", "--settings", "--add-dir")


def successor_argv(args, model, prompt):
    """The claude command of the next PM: the outgoing session's flags, minus anything that would resume it."""
    argv = ["claude"]
    for i, arg in enumerate(args):
        if not arg.startswith("-") or arg in ("--resume", "-r", "--continue", "-c", "--model", "--fork-session"):
            continue  # also drops a session id, a model name and an initial prompt
        argv.append(arg)
        if arg in KEEP_VALUE and i + 1 < len(args):
            argv.append(args[i + 1])
    return argv + (["--model", model] if model else []) + [prompt]


def rotate_herdr(a, repo, rec, previous, prompt, is_self):
    """In herdr (TUI): the new PM starts in a new tab of the outgoing PM's workspace."""
    path, name, old = PMS / f"{project_slug(repo)}.json", rec["name"], rec.get("pane") or ""
    workspace = ((herdr("pane", "get", old) or {}).get("pane") or {}).get("workspace_id")
    made = re.search(r'"pane_id": "([^"]+)"', json.dumps(
        herdr("tab", "create", "--workspace", workspace, "--cwd", repo, "--label", "pm", "--no-focus") or {})
    ) if workspace else None
    if not made:
        rec["previous"] = previous
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        sys.exit(f"handover notes saved, but no tab could be opened beside {old or 'the old PM'}. Start a fresh "
                 f"session by hand (SKILL.md, \"Restart a PM\", without --resume) and give it this prompt:\n{prompt}")
    new = made.group(1)
    info = ((herdr("pane", "process-info", "--pane", old) or {}).get("process_info") or {})
    args = next((p["argv"][1:] for p in info.get("foreground_processes", [])
                 if p.get("argv") and Path(p["argv"][0]).name == "claude"), [])
    argv = successor_argv(args, a.model, prompt)
    if rec.get("discord") and "--mcp-config" not in argv:
        argv[1:1] = ["--mcp-config", str(mcp_config_path(repo)),
                     "--dangerously-load-development-channels", f"server:{MCP_SERVER}"]
    # The name must be free: the new session's SessionStart hook takes it from the registration of its pane.
    herdr("agent", "rename", old, f"ex-{name}")
    rec.update({"pane": new, "workspace": workspace, "claimed": now(), "previous": previous,
                "rotations": rec.get("rotations", 0) + 1})
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    herdr("pane", "run", new, shlex.join(argv))
    seen = herdr("agent", "wait", new, "--until", "working", "--until", "idle", "--until", "blocked",
                 "--timeout", "30000")
    print(f"new PM session started in {new}; {old} is retired"
          + (": stop acting as PM in this session and tell the user to continue there." if is_self else "."))
    if not seen or rec.get("discord"):
        print(f"check {new}: it may be waiting at a startup dialog (folder trust, development channels) "
              "that the user has to confirm.")


def cmd_rotate(a):
    """Replace the PM session of a project with a fresh one that starts from `handover`."""
    repo = project_root(a.repo)
    rec = pm_record(repo) if repo else None
    if not rec:
        sys.exit("no PM registered for this project")
    d = project_dir(repo)
    is_self = rec.get("pane") == PANE
    transcript = a.transcript or (own_transcript() if is_self else "")
    notes = f"Written {now()} by the outgoing PM ({rec.get('pane')}).\n\n{a.notes.strip()}\n" if a.notes else ""
    (d / "handover.md").write_text(notes)
    previous = {"pane": rec.get("pane"), "transcript": transcript, "at": now(),
                "tokens": context_tokens(transcript) if transcript else 0}
    handover = f"python3 {Path(__file__).resolve()} handover"
    prompt = "[from pm.py rotate] " + tr(
        f"You are the PM of the {Path(repo).name} project (pm skill), replacing the session that was just rotated "
        "out. If the startup notice says another PM exists, that is the one you replace; the registration is "
        f"about to move to you. First run `{handover}` and take over from what it prints, nothing else. Then tell "
        "the user in three or four sentences what you took over and what is waiting for them.",
        f"你是 {Path(repo).name} 项目的 PM（pm skill），接替刚轮换下去的上一任会话。"
        "启动提示里如果说另有一个 PM，那就是你要接替的那一个，登记马上会转到你名下。"
        f"先运行 `{handover}`，只按它给出的内容接手，"
        "然后用三四句话告诉用户：你接手了哪些在办的事、哪些事在等他。")
    if rec.get("runtime") != "hc":
        return rotate_herdr(a, repo, rec, previous, prompt, is_self)
    old = hc("get", rec["terminal"]) or {}
    argv = successor_argv(((old.get("foreground") or {}).get("argv") or [])[1:], a.model, prompt)
    space = (old.get("labels") or {}).get("herdr.space")
    made = None
    if space:  # a tab next to the outgoing PM in the desktop app
        try:
            out = subprocess.run(["herdr-app", "do", "tab.new", json.dumps({"space": space, "folder": repo, "argv": argv})],
                                 capture_output=True, text=True, timeout=30)
            made = json.loads(out.stdout).get("terminal")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            made = None
    if not made:
        made = (hc("run", "--bg", "--no-parent", "--cwd", repo, "--", *argv) or {}).get("address")
    if not made:
        sys.exit("could not start the new PM session; the old one stays registered")
    hc("label", made, f"pm={Path(repo).name}")
    hc("label", rec["terminal"], "pm=")
    rec.update({"pane": f"hc:{made}", "terminal": made, "claimed": now(), "previous": previous,
                "rotations": rec.get("rotations", 0) + 1})
    (PMS / f"{project_slug(repo)}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    print(f"new PM session started in hc:{made}; {previous['pane']} is retired"
          + (": stop acting as PM in this session and tell the user to continue there." if is_self else "."))


# ---- dash: live board in the browser ----------------------------------------

DASH_HTML = Path(__file__).resolve().parent.parent / "assets" / "dash.html"
MIRROR_LOG = STATE / "hook-mirror.log"
MIRROR_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d) \[([^\]]+)\] (UserPromptSubmit|Stop): (?:mirrored|post failed)")


def dash_state():
    """Everything the dashboard draws: PMs, tasks, live agents and recent events."""
    listing = agents()
    by_pane = {x["pane_id"]: x for x in listing}
    agent_map = {x["pane_id"]: {"name": x.get("name") or "", "kind": x.get("agent") or "",
                                "status": x.get("agent_status") or "",
                                "title": x.get("terminal_title_stripped") or ""} for x in listing}
    pms = []
    for path in sorted(PMS.glob("*.json")) if PMS.exists() else []:
        rec = json.loads(path.read_text())
        live = by_pane.get(rec.get("pane") or "", {})
        if rec.get("runtime") == "hc":
            live = hc_pm(rec.get("repo") or "") or {}
        alive = live.get("name") == rec.get("name")
        pms.append({"name": rec["name"], "project": rec.get("project", ""), "repo": rec.get("repo", ""),
                    "pane": rec.get("pane", ""), "status": live.get("agent_status") if alive else "offline",
                    "title": live.get("terminal_title_stripped", "") if alive else "",
                    "discord": bool(rec.get("discord"))})

    def owner_pm(t):
        repo = str(Path(t["repo"]).resolve())
        exact = [p for p in pms if p["repo"] and str(Path(p["repo"]).resolve()) == repo]
        nested = [p for p in pms if p["repo"] and repo.startswith(str(Path(p["repo"]).resolve()) + "/")]
        named = [p for p in pms if p["project"].lower() == t["project"].lower()]
        hit = exact or nested or named
        return hit[0]["name"] if hit else ""

    day_ago = (datetime.datetime.now() - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
    tasks, events = [], []
    for t in all_tasks():
        # Closed work stays on the board for a day, until `retire` cleans it up.
        if not (t["status"] in ACTIVE or (t.get("updated", "") >= day_ago and not t.get("retired"))):
            continue
        pm = owner_pm(t)
        pm_pane = next((p["pane"] for p in pms if p["name"] == pm), "")
        log = t.get("log") or []
        tasks.append({k: t.get(k) or "" for k in ("id", "title", "project", "status", "owner", "pane", "agent",
                                                   "branch", "updated")}
                     | {"pm": pm, "latest": (log[-1].get("text", "") if log else ""), "cleanup": needs_cleanup(t),
                        # a task parked on the PM's own pane has no worker of its own
                        "worker": by_pane.get(t["pane"], {}).get("agent_status", "")
                        if t.get("pane") and t["pane"] != pm_pane else ""})
        for i, e in enumerate(log):
            by = e.get("by", "")
            status = re.search(r"\bstatus=(\w+)", e.get("text", ""))
            events.append({"key": f"{t['id']}#{i}", "at": e.get("at", ""), "by": by, "task": t["id"], "pm": pm,
                           "kind": "dispatch" if by in ("user", pm_pane) else "report",
                           "status": status.group(1) if status else "", "text": e.get("text", "")})
    # Chat turns with a PM, as recorded by the Discord mirror hook.
    if MIRROR_LOG.exists():
        pane_pm = {p["pane"]: p["name"] for p in pms}
        for line in MIRROR_LOG.read_text(errors="replace").splitlines()[-400:]:
            m = MIRROR_LINE.match(line)
            if m and m.group(2) in pane_pm:
                events.append({"key": "m:" + line, "at": m.group(1), "by": m.group(2), "task": "",
                               "pm": pane_pm[m.group(2)], "status": "", "text": "",
                               "kind": "prompt" if m.group(3) == "UserPromptSubmit" else "reply"})
    events = sorted(events, key=lambda e: e["at"])[-120:]
    return {"now": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "pms": pms, "tasks": tasks,
            "agents": agent_map, "events": events, "lang": tr("en", "zh")}


def cmd_state(a):
    print(json.dumps(dash_state(), ensure_ascii=False))


def cmd_dash(a):
    import http.server
    import threading
    import time
    import webbrowser
    lock, cache = threading.Lock(), {"at": 0.0, "body": b""}

    class Handler(http.server.BaseHTTPRequestHandler):
        # The stdlib default (HTTP/0.9) answers an unparsable request, such as a browser trying
        # https first, with a bare body and no headers, which some browsers save as a file.
        default_request_version = "HTTP/1.0"

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            if self.path.split("?")[0] == "/api/state":
                with lock:  # one herdr call per second however many tabs are open
                    if time.time() - cache["at"] > 1:
                        cache["body"] = json.dumps(dash_state(), ensure_ascii=False).encode()
                        cache["at"] = time.time()
                    body, kind = cache["body"], "application/json; charset=utf-8"
            elif self.path.split("?")[0] in ("/", "/index.html"):
                body, kind = DASH_HTML.read_bytes(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def log_message(self, fmt, *args):
            line = fmt % args
            if '"GET /api/state' in line and '" 200 ' in line:
                return  # the page polls every 3 s; log only page loads and errors
            ua = self.headers.get("User-Agent", "-") if getattr(self, "headers", None) else "-"
            print(f"{self.log_date_time_string()} {self.client_address[0]} {line} [{ua}]", flush=True)

    server = http.server.ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '') else a.host}:{a.port}/"
    print(f"PM dashboard on {url}  (ctrl+c to stop)", flush=True)
    if a.host in ("0.0.0.0", ""):
        import socket
        try:  # the address other devices on the LAN reach this machine at (no packet is sent)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))
                print(f"on the LAN: http://{s.getsockname()[0]}:{a.port}/", flush=True)
        except OSError:
            pass
    if a.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    p = argparse.ArgumentParser(prog="pm.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("title")
    n.add_argument("--repo", default=".")
    n.add_argument("--status", default="in_progress", choices=ACTIVE + CLOSED)
    for f in ("owner", "workspace", "pane", "agent", "branch", "worktree", "base", "brief", "slug", "note"):
        n.add_argument(f"--{f}")
    u = sub.add_parser("update")
    u.add_argument("id")
    for f in FIELDS + ["note"]:
        u.add_argument(f"--{f}", choices=ACTIVE + CLOSED if f == "status" else None)
    u.add_argument("--keep", action="store_true",
                   help="with --status merged: keep the worker, worktree and branch (no automatic retire)")
    l = sub.add_parser("log")
    l.add_argument("id")
    l.add_argument("text")
    sub.add_parser("show").add_argument("id")
    b = sub.add_parser("board")
    b.add_argument("--post", action="store_true", help="mirror the board to the configured Discord channel")
    b.add_argument("--channel", help="set (or change) the Discord board channel, then post")
    sub.add_parser("status").add_argument("--all", action="store_true")
    sub.add_parser("find").add_argument("--repo", default=".")
    c = sub.add_parser("claim")
    c.add_argument("--repo", default=".")
    c.add_argument("--pane", help="register the PM for this pane instead of the current one")
    c.add_argument("--discord-channel", help="guild channel ID this PM listens to")
    c.add_argument("--discord-users", help="comma-separated user IDs allowed to talk there (default: paired users)")
    la = sub.add_parser("launch", help="print the command that starts a Discord-connected PM session")
    la.add_argument("--repo", default=".")
    la.add_argument("--resume")
    nt = sub.add_parser("notify")
    nt.add_argument("text")
    nt.add_argument("--repo", default=".")
    d = sub.add_parser("dispatch")
    d.add_argument("title")
    d.add_argument("--repo", default=".")
    d.add_argument("--branch", required=True)
    d.add_argument("--label", required=True)
    d.add_argument("--brief", required=True)
    d.add_argument("--name", required=True)
    d.add_argument("--base")
    d.add_argument("--prep")
    d.add_argument("--kind", help="worker program (default: config.json, else codex)")
    d.add_argument("--model", help="default: config.json, else the program's own")
    d.add_argument("--effort", help="default: config.json, else the program's own")
    r = sub.add_parser("retire")
    r.add_argument("id")
    r.add_argument("--force", action="store_true")
    sub.add_parser("state", help="print dashboard state as JSON")
    ds = sub.add_parser("dash", help="serve the live dashboard (routing view of PMs, tasks and agents)")
    ds.add_argument("--port", type=int, default=7317)
    ds.add_argument("--host", default="127.0.0.1")
    ds.add_argument("--open", action="store_true", help="open it in the browser")
    dc = sub.add_parser("decide", help="record a decision the user made, for every later PM session")
    dc.add_argument("text")
    dc.add_argument("--quote", help="the user's own words")
    dc.add_argument("--repo", default=".")
    ho = sub.add_parser("handover", help="print what a fresh PM session needs to take over this project")
    ho.add_argument("--repo", default=".")
    ho.add_argument("--turns", type=int, default=6, help="how many past exchanges with the user to include")
    cxp = sub.add_parser("context", help="context tokens held by this session")
    cxp.add_argument("--transcript")
    ro = sub.add_parser("rotate", help="hand the project to a fresh PM session")
    ro.add_argument("--repo", default=".")
    ro.add_argument("--notes", help="what is in flight that the ledger and decisions do not say")
    ro.add_argument("--model", help="model for the new session (default: the CLI's default)")
    ro.add_argument("--transcript", help="the outgoing session's transcript (default: this session's)")
    sub.add_parser("hook-session-start")
    sub.add_parser("hook-mirror")
    a = p.parse_args()
    globals()["cmd_" + a.cmd.replace("-", "_")](a)


if __name__ == "__main__":
    main()
