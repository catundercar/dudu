"""Self-hosted worker CLI commands (`worker enroll|join|revoke|list`, `worker-agent`, `worker-hub`, `mailbox-sync`). Layer 4."""
from __future__ import annotations

import dataclasses
from pathlib import Path
import re
import sys
from typing import Any

from ..context import Context
from ..errors import IdentityError, PmError, Refused, StoreError
from ..messaging.nodes import DEFAULT_ENROLL_TTL_S, NodeError, NodeRegistry, NodeStreams, public_node
from ..messaging.transports.self_hosted import LEASE_TIMEOUT_S
from ..nodes.agent import (
    AGENT_FILE,
    AgentError,
    FileDriver,
    HcDriver,
    IDLE_POLL_S,
    WorkerAgent,
    _read_json,
    default_state_dir,
    join as agent_join,
)
from ..nodes.hub import SyncHub
from ..nodes.wire import HubUnavailable, client_for, serve_http, serve_stdio
from ..osutil import shell_quote
from .emit import exit_with


_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.IGNORECASE)
_DURATION_MULT = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def parse_ttl_s(raw: str | int | float | None) -> float:
    """Parse a TTL like `15m`, `1h`, `90s`, or `900` into seconds."""
    if raw is None or str(raw).strip() == "":
        return float(DEFAULT_ENROLL_TTL_S)
    m = _DURATION_RE.match(str(raw))
    if not m:
        raise Refused(f"invalid --ttl {raw!r}: use e.g. 15m, 1h, 90s, or seconds")
    val = float(m.group(1)) * _DURATION_MULT[m.group(2).lower()]
    if val <= 0:
        raise Refused(f"invalid --ttl {raw!r}: must be positive")
    return val


def _parse_projects(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for raw in values or []:
        for part in str(raw).split(","):
            slug = part.strip()
            if slug:
                out.append(slug)
    return out


def _parse_repos(values: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in values or []:
        slug, sep, path = str(raw).partition("=")
        slug, path = slug.strip(), path.strip()
        if not sep or not slug or not path:
            raise Refused(f"invalid --repo {raw!r}: use <project-slug>=<local-clone-path>")
        out[slug] = path
    return out


def _build_driver(ctx: Context, kind: str, worker_command: list[str]) -> Any:
    choice = str(kind or "auto").strip().lower()
    if choice == "hc" or (choice == "auto" and worker_command):
        return HcDriver(ctx, worker_command)
    return FileDriver()


def cmd_worker(a: Any, ctx: Any = None) -> None:
    """`pm.py worker enroll | join | revoke | list`."""
    ctx = Context.from_env() if ctx is None else ctx
    sub = getattr(a, "worker_cmd", None)
    try:
        if sub == "enroll":
            _worker_enroll(a, ctx)
        elif sub == "join":
            _worker_join(a, ctx)
        elif sub == "revoke":
            _worker_revoke(a, ctx)
        elif sub == "list":
            _worker_list(a, ctx)
        else:
            exit_with(ctx, Refused(f"unknown worker subcommand {sub!r}"))
    except (StoreError, IdentityError):
        raise
    except (NodeError, AgentError, HubUnavailable, ValueError) as err:
        exit_with(ctx, Refused(str(err)))
    except PmError as err:
        exit_with(ctx, err)


def _worker_enroll(a: Any, ctx: Context) -> None:
    reg = NodeRegistry(ctx.home.tokens, clock=ctx.clock)
    ttl_s = parse_ttl_s(getattr(a, "ttl", None))
    projects = _parse_projects(getattr(a, "projects", None))
    enr = reg.enroll(a.name, projects, ttl_s=ttl_s)
    hub_hint = str(getattr(a, "hub", None) or "").strip() or "<hub-url-or-ssh-host>"
    join_cmd = f"pm.py worker join --hub {shell_quote(hub_hint)} --token {enr.token}"
    if getattr(a, "json", False):
        ctx.out.json({
            "token": enr.token,
            "alias": enr.alias,
            "projects": list(enr.projects),
            "expires_ms": enr.expires_ms,
            "join_command": join_cmd,
        })
        return
    ctx.out.line(f"enrolled {enr.alias} (projects: {', '.join(enr.projects)}; ttl: {int(ttl_s)}s)")
    ctx.out.line(f"token: {enr.token}")
    ctx.out.line(f"join:  {join_cmd}")


def _worker_join(a: Any, ctx: Context) -> None:
    state_dir = Path(a.state).expanduser() if getattr(a, "state", None) else default_state_dir(ctx.env)
    hub_cmd = list(getattr(a, "hub_cmd", None) or [])
    worker_cmd = list(getattr(a, "worker_cmd_argv", None) or [])
    driver = _build_driver(ctx, getattr(a, "driver", "auto"), worker_cmd)
    client = client_for(a.hub, hub_command=hub_cmd or None)
    repos = _parse_repos(getattr(a, "repo", None))
    info = agent_join(
        state_dir,
        client,
        a.token,
        hub=a.hub,
        hub_command=hub_cmd or None,
        repos=repos,
        worktrees=str(getattr(a, "worktrees", None) or ""),
        pm_command=str(getattr(a, "pm_command", None) or ""),
        worker_command=worker_cmd or None,
        capabilities=driver.capabilities(),
        force=bool(getattr(a, "force", False)),
    )
    if getattr(a, "json", False):
        ctx.out.json({**info, "state": str(state_dir)})
        return
    ctx.out.line(f"joined as {info['node_id']} ({info['alias']}) -> {state_dir}")


def _worker_revoke(a: Any, ctx: Context) -> None:
    reg = NodeRegistry(ctx.home.tokens, clock=ctx.clock)
    node = public_node(reg.revoke(a.node))
    if getattr(a, "json", False):
        ctx.out.json(node)
        return
    ctx.out.line(f"revoked {node['node_id']} ({node.get('alias') or node['node_id']})")


def _worker_list(a: Any, ctx: Context) -> None:
    reg = NodeRegistry(ctx.home.tokens, clock=ctx.clock)
    now_ms = int(float(ctx.clock.time()) * 1000)
    lease_ms = int(LEASE_TIMEOUT_S * 1000)
    show_all = bool(getattr(a, "all", False))
    rows = []
    for raw in reg.nodes():
        revoked = bool(raw.get("revoked_ms"))
        if revoked and not show_all:
            continue
        node = public_node(raw)
        last = NodeStreams(ctx.home.nodes, str(node["node_id"])).last_sync_ms()
        if revoked:
            link = "revoked"
        elif last and now_ms - last <= lease_ms:
            link = "connected"
        else:
            link = "disconnected"
        rows.append({
            **node,
            "link_state": link,
            "last_sync_ms": last,
            "grant_count": len(node.get("grants") or {}),
        })
    if getattr(a, "json", False):
        ctx.out.json(rows)
        return
    if not rows:
        ctx.out.line("no self-hosted worker nodes registered")
        return
    for row in rows:
        projs = ",".join(row.get("projects") or [])
        ctx.out.line(f"{row['node_id']}  {row.get('alias') or '-':16}  {row['link_state']:12}  "
                     f"projects={projs}  grants={row['grant_count']}")


def cmd_mailbox_sync(a: Any, ctx: Any = None) -> None:
    """`pm.py mailbox-sync --stdio`: restricted SSH stdio carrier for the self-hosted sync protocol."""
    del a
    ctx = Context.from_env() if ctx is None else ctx
    hub = SyncHub(ctx)
    serve_stdio(hub, sys.stdin, ctx.out.line)


def cmd_worker_hub(a: Any, ctx: Any = None) -> None:
    """`pm.py worker-hub`: lightweight HTTP JSON endpoint serving `POST /v1/worker/sync`."""
    ctx = Context.from_env() if ctx is None else ctx
    hub = SyncHub(ctx)
    serve_http(
        hub,
        host=str(getattr(a, "host", None) or "127.0.0.1"),
        port=int(getattr(a, "port", 8765) or 0),
        ready=lambda srv: ctx.out.line(
            f"listening on http://{srv.server_address[0]}:{srv.server_address[1]}/v1/worker/sync"
        ),
    )


def cmd_worker_agent(a: Any, ctx: Any = None) -> None:
    """`pm.py worker-agent`: foreground polling daemon (or `--once` single cycle) on a self-hosted node."""
    ctx = Context.from_env() if ctx is None else ctx
    state_dir = Path(a.state).expanduser() if getattr(a, "state", None) else default_state_dir(ctx.env)
    cfg = _read_json(state_dir / AGENT_FILE)
    hub = str(getattr(a, "hub", None) or cfg.get("hub") or "").strip()
    hub_cmd = list(getattr(a, "hub_cmd", None) or cfg.get("hub_command") or [])
    worker_cmd = list(cfg.get("worker_command") or [])
    try:
        client = client_for(hub, hub_command=hub_cmd or None)
        driver = _build_driver(ctx, getattr(a, "driver", "auto"), worker_cmd)
        agent = WorkerAgent(state_dir, client, driver, clock=ctx.clock, out=ctx.out.line)
    except (AgentError, ValueError) as err:
        exit_with(ctx, Refused(str(err)))
        return
    if getattr(a, "once", False):
        cyc = agent.run_once(force=True)
    else:
        cyc = agent.run(
            interval_s=float(getattr(a, "interval", IDLE_POLL_S) or IDLE_POLL_S),
            max_cycles=getattr(a, "max_cycles", None),
            sleep=ctx.clock.sleep,
        )
    if getattr(a, "json", False):
        ctx.out.json(dataclasses.asdict(cyc))
    elif getattr(a, "once", False):
        state = "ok" if cyc.ok else ("revoked" if cyc.revoked else ("offline" if cyc.offline else "error"))
        ctx.out.line(f"sync {state}: pulled={cyc.pulled} handled={cyc.handled} applied={cyc.applied} "
                     f"rejected={cyc.rejected}" + (f" ({cyc.error})" if cyc.error else ""))
    if cyc.revoked:
        sys.exit(2)
    if getattr(a, "once", False) and not cyc.ok:
        sys.exit(1)


def register_node_commands(sub: Any) -> None:
    w = sub.add_parser("worker", help="manage self-hosted worker nodes (enroll, join, revoke, list)")
    wsub = w.add_subparsers(dest="worker_cmd", required=True)

    en = wsub.add_parser("enroll", help="issue a single-use enrollment token for a self-hosted worker node")
    en.add_argument("--name", required=True, help="logical alias for the node")
    en.add_argument("--projects", action="append", required=True,
                    help="allowed project slug(s), comma-separated or repeated (or '*' for any)")
    en.add_argument("--ttl", default="15m", help="enrollment token lifetime (e.g. 15m, 1h, 90s; default 15m)")
    en.add_argument("--hub", help="hub URL or SSH host to include in the printed join command")
    en.add_argument("--json", action="store_true", help="emit enrollment details as JSON")

    jn = wsub.add_parser("join", help="exchange an enrollment token for persistent node credentials")
    jn.add_argument("--hub", required=True, help="coordinator hub URL (https://...) or SSH host")
    jn.add_argument("--token", required=True, help="single-use enroll_... token from `pm.py worker enroll`")
    jn.add_argument("--state", help="worker-agent state directory (default: $PM_WORKER_AGENT_STATE or ~/.herdr/pm-worker-agent)")
    jn.add_argument("--repo", action="append", metavar="SLUG=PATH", help="local git clone path for a project (repeatable)")
    jn.add_argument("--worktrees", help="root folder for local task worktrees")
    jn.add_argument("--pm-command", help="command workers on this node use to invoke pm.py")
    jn.add_argument("--worker-cmd", dest="worker_cmd_argv", action="append", metavar="ARG",
                    help="argv token of the local agent command launched by HcDriver (repeatable)")
    jn.add_argument("--hub-cmd", action="append", metavar="ARG",
                    help="override stdio hub command argv instead of ssh (repeatable; useful for local pipes/tests)")
    jn.add_argument("--driver", choices=("auto", "hc", "file"), default="auto", help="local worker driver")
    jn.add_argument("--force", action="store_true", help="replace an existing credential.json in --state")
    jn.add_argument("--json", action="store_true", help="emit join details as JSON")

    rv = wsub.add_parser("revoke", help="immediately revoke a self-hosted worker node and drop its task grants")
    rv.add_argument("node", help="node id (node_...) or alias")
    rv.add_argument("--json", action="store_true", help="emit revoked node record as JSON")

    ls = wsub.add_parser("list", help="list registered self-hosted worker nodes")
    ls.add_argument("--all", action="store_true", help="include revoked nodes")
    ls.add_argument("--json", action="store_true", help="emit node list as JSON")

    ms = sub.add_parser("mailbox-sync", help="isomorphic JSON sync endpoint over stdio (for restricted SSH)")
    ms.add_argument("--stdio", action="store_true", help="read signed JSON requests on stdin and write JSON replies on stdout")

    wh = sub.add_parser("worker-hub", help="run a lightweight HTTP server serving POST /v1/worker/sync")
    wh.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    wh.add_argument("--port", type=int, default=8765, help="bind port (default 8765; 0 for ephemeral)")

    wa = sub.add_parser("worker-agent", help="run the self-hosted worker pull/sync agent")
    wa.add_argument("--state", help="worker-agent state directory")
    wa.add_argument("--hub", help="override hub URL or SSH host from agent.json")
    wa.add_argument("--hub-cmd", action="append", metavar="ARG", help="override stdio hub command argv")
    wa.add_argument("--driver", choices=("auto", "hc", "file"), default="auto", help="local worker driver")
    wa.add_argument("--once", action="store_true", help="run a single sync cycle and exit")
    wa.add_argument("--interval", type=float, default=IDLE_POLL_S, help="idle poll interval in seconds")
    wa.add_argument("--max-cycles", type=int, help="stop after this many cycles")
    wa.add_argument("--json", action="store_true", help="emit cycle result as JSON")
