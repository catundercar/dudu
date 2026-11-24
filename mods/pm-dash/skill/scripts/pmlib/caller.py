"""Who runs this process: its terminal, its herdr session, and the part it plays in a project (the project's PM, a
worker the PM started, a helper, another session, or a person at a shell). Layer 2.

`Caller(ctx)` owns single-read `terminal_info`/`labels` (one `ctx.hc.get(terminal)` shared across `labels`,
`own_task`, `helper`, and `helper_caller_identity`), instance-cached TUI multi-session inventory/session state,
and all identity/role/guard queries over explicit `Context` ports (`ctx.hc`, `ctx.tui`, `ctx.git`, `ctx.home`,
`ctx.store`, `ctx.env`).

During Stages 1-5, the legacy module-level identity functions and `_IDENTITY`/`_SESSION`/`HERDR_PANE` remain as
thin bridges over `Caller.current()` so existing `test_pm*.py` suites stay untouched until Stage 6.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterator, Optional

from .context import Context
from .errors import IdentityError
from .home import project_slug
from .ledger.ledger import Ledger
from .ledger.task import ACTIVE, pm_started
from .project.project import ProjectRegistry, in_scope, pm_name
from .terminals.hc import TerminalInfo


_UNREAD = object()


def tui_registration(rec: dict[str, Any]) -> bool:
    """A registration of a herdr TUI PM: not archived (no PM then) and not the desktop app's (hc_role checks those)."""
    return not rec.get("archived") and rec.get("runtime") != "hc" and not str(rec.get("pane") or "").startswith("hc:")


def authorize(role: str, action: str) -> None:
    if action != "read" and role == "uncertain":
        raise IdentityError("PM reservation has an uncertain session or different live identity; "
                            "reconcile explicitly, do not rename")
    if action == "coordinate" and role != "pm":
        raise IdentityError("only the registered PM may coordinate; hand the task to the existing PM")
    if action == "implement" and role == "pm":
        raise IdentityError("PM cannot implement code, documents or deliverables; dispatch to a worker")


@dataclass(frozen=True)
class Role:
    """The part a caller plays in a project. kind is one of Role.KINDS; task: the task a worker or reviewer works on;
    owner: whose helper a helper is (a task id, or the PM)."""
    kind: str
    task: Optional[str] = None
    owner: Optional[str] = None

    MANAGER, WORKER, REVIEWER, HELPER, SESSION, USER = "manager", "worker", "reviewer", "helper", "session", "user"
    KINDS = (MANAGER, WORKER, REVIEWER, HELPER, SESSION, USER)


class Caller:
    """Who runs this process: its terminal (`pane`: a herdr TUI pane or "hc:<terminal>"; `terminal`: the herdr-core
    terminal id), its workspace, its agent session id, and what herdr-core / herdr TUI say about it.

    Single-read guarantee: `terminal_info`, `labels`, `own_task`, and `helper` all share one lazy `ctx.hc.get(...)`
    call on this `Caller` instance. TUI multi-session inventory and socket session are cached per instance as well.
    Building a `Caller` does zero IO.
    """

    def __init__(
        self,
        ctx: Context | None = None,
        *,
        pane: str | None = None,
        terminal: str | None = None,
        workspace: str | None = None,
        herdr_pane: str | None = None,
        session_id: str | None = None,
        _projects: ProjectRegistry | None = None,
        _ledger: Ledger | None = None,
        _in_tui_fn: Callable[[], bool] | None = None,
        _herdr_session_fn: Callable[[], str] | None = None,
        _check_role_fn: Callable[..., dict[str, Any]] | None = None,
        _current_pm_record_fn: Callable[..., dict[str, Any] | None] | None = None,
        _inventory: dict[str, Any] | None = None,
        _on_inventory: Callable[[dict[str, Any]], None] | None = None,
        _on_session: Callable[[str], None] | None = None,
    ) -> None:
        self.ctx = Context.from_env() if ctx is None else ctx
        self.pane = self.ctx.pane if pane is None else pane
        if terminal is not None:
            self.terminal = terminal
        elif pane is not None:
            self.terminal = pane[3:] if pane.startswith("hc:") else ""
        else:
            self.terminal = self.ctx.hc_terminal
        self.workspace = self.ctx.workspace if workspace is None else workspace
        if herdr_pane is not None:
            self.herdr_pane = herdr_pane
        elif pane is not None:
            self.herdr_pane = "" if pane.startswith("hc:") else pane
        else:
            env_pane = str(self.ctx.env.get("HERDR_PANE_ID") or "")
            self.herdr_pane = "" if env_pane.startswith("hc:") else env_pane
        self.session_id = str(self.ctx.env.get("CLAUDE_CODE_SESSION_ID") or "") if session_id is None else session_id
        self._projects_cache: ProjectRegistry | None = _projects
        self._ledger_cache: Ledger | None = _ledger
        self._in_tui_fn = _in_tui_fn
        self._herdr_session_fn = _herdr_session_fn
        self._check_role_fn = _check_role_fn
        self._current_pm_record_fn = _current_pm_record_fn
        self._terminal_info: Any = _UNREAD
        self._labels: Any = _UNREAD
        self._own_task: Any = _UNREAD
        self._helper: Any = _UNREAD
        self._inventory: dict[str, Any] | None = _inventory
        self._session: str | None = None
        self._on_inventory = _on_inventory
        self._on_session = _on_session

    @property
    def _projects(self) -> ProjectRegistry:
        if self._projects_cache is None:
            self._projects_cache = ProjectRegistry(self.ctx)
        return self._projects_cache

    @property
    def _ledger(self) -> Ledger:
        if self._ledger_cache is None:
            self._ledger_cache = Ledger(self.ctx)
        return self._ledger_cache

    @classmethod
    def from_context(cls, ctx: Context) -> Caller:
        """Return `ctx.caller` if already bound, else construct, cache on `ctx.caller`, and return one."""
        if isinstance(ctx.caller, cls):
            return ctx.caller
        inst = cls(ctx)
        ctx.caller = inst
        return inst

    @classmethod
    def current(cls) -> Caller:
        """Build a `Caller` from the current process environment."""
        return cls(Context.from_env())

    # ---- single-read herdr-core terminal properties ----

    @property
    def terminal_info(self) -> TerminalInfo | None:
        """The herdr-core `TerminalInfo` for this terminal, read at most once (None outside desktop app)."""
        if self._terminal_info is _UNREAD:
            self._terminal_info = self.ctx.hc.get(self.terminal) if self.terminal else None
        return self._terminal_info

    @property
    def labels(self) -> dict[str, str]:
        """The labels herdr-core shows on this terminal ({} outside the desktop app, or when it does not answer)."""
        if self._labels is _UNREAD:
            info = self.terminal_info
            self._labels = dict(info.labels) if info is not None else {}
        return self._labels

    @property
    def own_task(self) -> dict[str, Any] | None:
        """The open task this session works on: its `task=<id>` label on this herdr-core terminal, else a task that
        recorded this Claude Code session as its agent, or None."""
        if self._own_task is _UNREAD:
            self._own_task = self._resolve_own_task()
        return self._own_task

    def _resolve_own_task(self) -> dict[str, Any] | None:
        def active(task_id: str) -> dict[str, Any] | None:
            # A label is free text: only a plain file name in tasks/.
            if not task_id or not re.fullmatch(r"[^/\\\s.][^/\\\s]*", task_id) or ".." in task_id:
                return None
            path = self.ctx.home.task(task_id)
            if not path.exists():
                return None
            try:
                task = json.loads(path.read_text())
            except (OSError, ValueError):
                return None
            return task if isinstance(task, dict) and task.get("status") in ACTIVE else None

        if self.terminal:
            task = active(str(self.labels.get("task") or ""))
            if task:
                return task
        if self.session_id:
            try:
                mine = [
                    t for t in self._ledger.raw_tasks()
                    if (t.get("session") or {}).get("id") == self.session_id and t.get("status") in ACTIVE
                ]
            except (OSError, ValueError, AttributeError):
                mine = []
            if mine:
                return mine[0]
        return None

    @property
    def helper(self) -> dict[str, str] | None:
        """{of, name, project, terminal} when this process runs inside a helper terminal, else None.
        Checks hc terminal labels first (authoritative), then PM_HELPER_* env vars."""
        if self._helper is _UNREAD:
            self._helper = self._resolve_helper()
        return self._helper

    def _resolve_helper(self) -> dict[str, str] | None:
        env_of = str(self.ctx.env.get("PM_HELPER_OF") or "")
        env_name = str(self.ctx.env.get("PM_HELPER_NAME") or "")
        env_proj = str(self.ctx.env.get("PM_HELPER_PROJECT") or "")
        labels = self.labels if self.terminal else {}
        of = str(labels.get("helper.of") or env_of or "")
        name = str(labels.get("helper") or env_name or "")
        proj = str(labels.get("helper.project") or env_proj or "")
        if of or name:
            return {"of": of, "name": name, "project": proj, "terminal": self.terminal}
        return None

    def helper_self_info(self) -> dict[str, str] | None:
        return self.helper

    # ---- host & TUI session inventory (instance-cached) ----

    def strict_herdr(self, *args: Any, session: str | None = None) -> dict[str, Any]:
        return self.ctx.tui.strict(*args, session=session)

    def herdr_sessions(self) -> list[dict[str, Any]]:
        """The local herdr sessions ({name, socket_path, running}), checked; IdentityError when unreadable."""
        sessions = self.ctx.tui.sessions()
        if not isinstance(sessions, list):
            raise IdentityError("cannot enumerate herdr sessions: unavailable")
        return sessions

    def socket_session(self, sessions: list[dict[str, Any]] | None = None) -> str:
        """The running session whose socket this process inherited (`herdr status server`)."""
        name = self.ctx.tui.socket_session(sessions)
        if not name:
            raise IdentityError("cannot verify caller session: inherited socket is not one known running session")
        return name

    def herdr_session(self) -> str:
        """Name of the herdr session this pane runs in, or "" when it cannot be told (best effort, never raises)."""
        if self._herdr_session_fn is not None:
            return self._herdr_session_fn()
        if not self.herdr_pane:
            return ""
        try:
            return self.socket_session(self.herdr_sessions())
        except IdentityError:
            return ""

    def identity_inventory(self) -> dict[str, Any]:
        """Read every running local session and reconcile registrations without changing them."""
        if self._inventory is not None:
            return self._inventory
        sessions = self.herdr_sessions()
        live: list[dict[str, Any]] = []
        panes: list[dict[str, Any]] = []
        for s in sessions:
            if not s["running"]:
                continue
            for command, field, dest in [("agent", "agents", live), ("pane", "panes", panes)]:
                rows = self.strict_herdr(command, "list", session=s["name"]).get(field)
                if not isinstance(rows, list) or any(
                    not isinstance(x, dict) or not x.get("pane_id") or not x.get("workspace_id") for x in rows
                ):
                    raise IdentityError(f"incomplete {command} list in herdr session {s['name']}")
                dest.extend({**x, "session": s["name"]} for x in rows)
        records: list[dict[str, Any]] = []
        regs_dir = self.ctx.home.registrations
        for path in sorted(regs_dir.glob("*.json")) if regs_dir.exists() else []:
            try:
                rec = json.loads(path.read_text())
                if not isinstance(rec, dict):
                    raise ValueError("not an object")
                if not tui_registration(rec):
                    continue
                if not all(rec.get(k) for k in ("repo", "name", "pane", "workspace")):
                    raise ValueError("missing repo/name/pane/workspace")
                rec = {**rec, "repo": str(Path(rec["repo"]).resolve())}
            except (OSError, ValueError, TypeError) as e:
                raise IdentityError(f"invalid PM registration {path}: {e}") from e
            if not rec.get("session"):
                named = [
                    p for p in live
                    if p.get("name") == rec["name"]
                    and p["pane_id"] == rec["pane"]
                    and p["workspace_id"] == rec["workspace"]
                ]
                rec["session"] = named[0]["session"] if len(named) == 1 else None
            rec["uncertain"] = rec["session"] not in {s["name"] for s in sessions}
            rec.update(pane_id=rec["pane"], workspace_id=rec["workspace"], registered=True)
            actual = [p for p in live if (p["session"], p["pane_id"]) == (rec["session"], rec["pane"])]
            rec["verified"] = bool(
                actual and actual[0].get("name") == rec["name"] and actual[0]["workspace_id"] == rec["workspace"]
            )
            records.append(rec)
        pms = list(records)
        for p in live:
            if str(p.get("name") or "").startswith("pm-") and not any(
                (r["session"], r["pane"]) == (p["session"], p["pane_id"]) for r in records
            ):
                pms.append({**p, "pane": p["pane_id"], "workspace": p["workspace_id"], "registered": False})
        workspaces: dict[Any, Any] = {}
        projects: dict[Any, Any] = {}
        names: dict[Any, Any] = {}
        for pm_rec in pms:
            for seen, key, label in [
                (workspaces, (pm_rec["session"], pm_rec["workspace"]), "workspace"),
                (projects, pm_rec.get("repo"), "project"),
                (names, pm_rec["name"], "PM name"),
            ]:
                if key is None:
                    continue
                if key in seen:
                    raise IdentityError(f"multiple PMs reserve {label} {key}: {seen[key]['name']} and {pm_rec['name']}")
                seen[key] = pm_rec
        self._inventory = {"sessions": sessions, "agents": live, "panes": panes, "pms": pms, "records": records}
        if self._on_inventory is not None:
            self._on_inventory(self._inventory)
        return self._inventory

    def caller_identity(self, inventory: dict[str, Any] | None = None) -> dict[str, str] | None:
        """The inherited socket, pane and workspace must identify the same running pane."""
        herdr_env = self.ctx.env.get("HERDR_ENV")
        if not self.herdr_pane and not self.workspace and herdr_env != "1":
            return None
        if not self.herdr_pane or not self.workspace or herdr_env != "1":
            raise IdentityError("incomplete herdr identity; require HERDR_ENV=1, HERDR_PANE_ID and HERDR_WORKSPACE_ID")
        inv = self.identity_inventory() if inventory is None else inventory
        session = self.socket_session(inv["sessions"])
        if not any(
            (p["session"], p["workspace_id"], p["pane_id"]) == (session, self.workspace, self.herdr_pane)
            for p in inv["panes"]
        ):
            raise IdentityError(f"caller pane {session}/{self.workspace}/{self.herdr_pane} does not exist")
        self._session = session
        if self._on_session is not None:
            self._on_session(session)
        return {"session": session, "workspace": self.workspace, "pane": self.herdr_pane}

    def inventory_pm(self, repo: str | Path | None = None, inventory: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """The registered project PM across sessions, or the caller workspace's PM."""
        inv = inventory or self.identity_inventory()
        root = self.ctx.git.project_root(repo or ".")
        pms = [p for p in inv["pms"] if p.get("repo") == root or p.get("name") == pm_name(root)] if root else []
        if not pms and self.herdr_pane and self.workspace:
            caller = self.caller_identity(inv)
            if caller is not None:
                pms = [
                    p for p in inv["pms"]
                    if (p["session"], p["workspace"]) == (caller["session"], caller["workspace"])
                ]
        if len(pms) > 1:
            raise IdentityError("multiple project PM matches; reconcile registrations")
        return pms[0] if pms else None

    # ---- host detection & guard ----

    def app_caller(self) -> bool:
        """A session of the desktop app (a herdr-core terminal), not of the herdr terminal UI."""
        return bool(self.terminal) and self.ctx.env.get("HERDR_ENV") != "1"

    def in_tui(self) -> bool:
        """This session runs in a pane of the herdr terminal UI ($HERDR_PANE_ID), not in the desktop app's herdr-core."""
        if self._in_tui_fn is not None:
            return bool(self._in_tui_fn())
        return bool(self.pane) and not self.pane.startswith("hc:")

    def hc_registration(self, pane: str | None = None) -> dict[str, Any] | None:
        target = self.pane if pane is None else pane
        regs_dir = self.ctx.home.registrations
        matches: list[dict[str, Any]] = []
        for path in sorted(regs_dir.glob("*.json")) if regs_dir.exists() else []:
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get("pane") == target and not rec.get("archived"):
                matches.append(rec)
        if not matches:
            return None
        if len(matches) > 1 and target == self.pane and self.terminal:
            for rec in matches:
                if self._hc_pm_matches(rec.get("repo")):
                    return rec
        return matches[0]

    def hc_role(self, action: str = "read", repo: str | Path = ".") -> dict[str, Any]:
        """check_role in the desktop app: the PM is the terminal its registration names while herdr-core shows it live
        and labelled pm=<project>. A registration naming this terminal that herdr-core does not confirm is uncertain."""
        caller = {"session": "hc", "workspace": "", "pane": self.pane}
        own = self.hc_registration(self.pane)
        live = self._projects.hc_pm(own["repo"]) if own and own.get("repo") else None
        verified = bool(live and live["pane_id"] == self.pane)
        root = self.ctx.git.project_root(repo or ".")
        found = live if verified else (self._projects.hc_pm(root) if root else None)
        rec = own if verified else (self._projects.pm_record(root) if found else None)
        pm = None
        if found:
            pm = {
                "name": found["name"],
                "repo": (rec or {}).get("repo") or root,
                "session": "hc",
                "workspace": "",
                "pane": found["pane_id"],
                "pane_id": found["pane_id"],
                "registered": True,
                "verified": True,
                "uncertain": False,
            }
        elif own:
            pm = {
                "name": own.get("name"),
                "repo": own.get("repo"),
                "session": "hc",
                "workspace": "",
                "pane": self.pane,
                "pane_id": self.pane,
                "registered": True,
                "verified": False,
                "uncertain": True,
            }
        role = "pm" if verified else ("uncertain" if own else "worker")
        authorize(role, action)
        return {"role": role, "caller": caller, "pm": pm, "unresolved_registrations": []}

    def check_guard(self, action: str = "read", repo: str | Path = ".") -> dict[str, Any]:
        """The caller's role: pm, worker, observer (outside herdr: read only) or uncertain (read only).
        IdentityError when the action is not allowed or the identity cannot be verified."""
        if self._check_role_fn is not None:
            if repo == ".":
                return self._check_role_fn(action) if action != "read" else self._check_role_fn()
            return self._check_role_fn(action, repo)
        if self.app_caller():
            return self.hc_role(action, repo)
        inventory = self.identity_inventory()
        caller = self.caller_identity(inventory)
        if caller is None:
            if action != "read":
                raise IdentityError("observer outside herdr is read-only; cannot claim, coordinate or implement")
            return {"role": "observer", "caller": None, "pm": self.inventory_pm(repo=repo, inventory=inventory)}
        own = [p for p in inventory["pms"] if (p["session"], p["pane"]) == (caller["session"], caller["pane"])]
        workspace_pm = [
            p for p in inventory["pms"] if (p["session"], p["workspace"]) == (caller["session"], caller["workspace"])
        ]
        pm = own[0] if own else (workspace_pm[0] if workspace_pm else self.inventory_pm(repo=repo, inventory=inventory))
        role = "pm" if own and own[0]["registered"] else "worker"
        uncertain = [
            p for p in inventory["pms"]
            if p.get("uncertain") and (p["workspace"] == caller["workspace"] or p.get("repo") == self.ctx.git.project_root(repo))
        ]
        if uncertain or (own and not own[0].get("verified")):
            role = "uncertain"
        authorize(role, action)
        return {
            "role": role,
            "caller": caller,
            "pm": pm,
            "unresolved_registrations": [p["name"] for p in inventory["records"] if p.get("uncertain")],
        }

    def check_role(self, action: str = "read", repo: str | Path = ".") -> dict[str, Any]:
        return self.check_guard(action, repo)

    # ---- registration, task, and role queries ----

    def blocked_by_worker(self, task: dict[str, Any]) -> bool:
        """Whether the latest entry that blocked `task` was written by a worker (neither this PM nor the user)."""
        log = [e for e in (task.get("log") or []) if isinstance(e, dict)]
        asking = [e for e in log if re.search(r"\bstatus\s*=\s*blocked\b", str(e.get("text") or ""))]
        entry = (asking or log or [{}])[-1 if asking else 0]
        by = str(entry.get("by") or "").strip()
        return bool(by) and by != "user" and by != self.pane

    def pm_record_for_pane(self, pane: str | None = None) -> dict[str, Any] | None:
        target = self.pane if pane is None else pane
        regs_dir = self.ctx.home.registrations
        matches: list[dict[str, Any]] = []
        for path in sorted(regs_dir.glob("*.json")) if regs_dir.exists() else []:
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get("pane") == target and not rec.get("archived"):
                matches.append(rec)
        if not matches:
            return None
        if len(matches) > 1 and target == self.pane:
            if self.terminal:
                for rec in matches:
                    if self._hc_pm_matches(rec.get("repo")):
                        return rec
            elif self.in_tui():
                for rec in matches:
                    if self._tui_pm_matches(rec.get("repo")):
                        return rec
        return matches[0]

    def _hc_pm_matches(self, repo: str | Path | None) -> bool:
        """True unless live herdr-core labels on this terminal explicitly name a different project's PM or a worker/helper."""
        if not self.terminal or not repo:
            return True
        live_pm = str(self.labels.get("pm") or "")
        if not live_pm:
            if self.labels.get("task") or self.labels.get("helper") or self.labels.get("helper.of"):
                return False
            return True
        root = self.ctx.git.project_root(repo) or str(repo)
        return live_pm in (project_slug(root), Path(root).name)

    def _tui_pm_matches(self, repo: str | Path | None, cwd: str | Path | None = None, *, check_cwd: bool = True) -> bool:
        """True unless live herdr TUI facts (agent name or cwd) show this pane belongs to a different project."""
        if not self.in_tui() or not repo:
            return True
        root = self.ctx.git.project_root(repo) or str(repo)
        want_name = pm_name(root)
        session = self.herdr_session() or None
        try:
            live_agents = self.ctx.tui.agents(session=session) if session else self.ctx.tui.agents()
        except Exception:
            live_agents = []
        for agent in live_agents or ():
            if isinstance(agent, dict) and agent.get("pane_id") == self.herdr_pane:
                name = str(agent.get("name") or "")
                if name.startswith("pm-") and name != want_name:
                    return False
                break
        if check_cwd:
            try:
                here = self.ctx.git.project_root(cwd or os.getcwd())
            except OSError:
                here = None
            if here and not (in_scope(here, root) or in_scope(root, here)):
                return False
        return True

    def is_pm_caller(self, task: dict[str, Any] | None = None, repo: str | Path | None = None) -> bool:
        """Whether the current process runs from the project's PM terminal."""
        r = repo or (task or {}).get("repo") or ""
        if not self.pane:
            return False
        if r and self.manages(r):
            return True
        rec = self.own_pm_record()
        if rec and (not r or not rec.get("repo") or in_scope(r, rec["repo"]) or in_scope(rec["repo"], r)):
            return True
        return False

    def own_pm_record(self, cwd: str | Path | None = None) -> dict[str, Any] | None:
        """The registration of the PM this session is, for its hooks: the one naming its pane."""
        rec = self.pm_record_for_pane(self.pane) if self.pane else None
        if not rec:
            return None
        if self.terminal and not self._hc_pm_matches(rec.get("repo")):
            return None
        if self.in_tui():
            try:
                here = self.ctx.git.project_root(cwd or os.getcwd())
            except OSError:  # the session's folder was removed
                here = None
            repo = rec.get("repo")
            if not here or not repo or not (in_scope(here, repo) or in_scope(repo, here)):
                return None
            # The same pane id in another herdr session (see identity_inventory): not this session's registration.
            if rec.get("session") and rec["session"] != (self.herdr_session() or rec["session"]):
                return None
            if not self._tui_pm_matches(repo, cwd=cwd, check_cwd=False):
                return None
        return rec

    def caller_projects(self, reg_idx: Any) -> Iterator[str]:
        """The projects this terminal works in, most certain first, lazily evaluated."""
        rec = self.own_pm_record()
        if rec and rec.get("repo"):
            yield project_slug(rec["repo"])
        own = self.own_task
        if own:
            yield self.ctx.store._task_slug(own, reg_idx)

    def workspace_registration(self) -> dict[str, Any] | None:
        """In the herdr TUI: the registration of the PM whose workspace this pane is in, or None. Never raises."""
        regs_dir = self.ctx.home.registrations
        if not self.in_tui() or not self.workspace or not regs_dir.exists():
            return None
        session = None
        for path in sorted(regs_dir.glob("*.json")):
            try:
                rec = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(rec, dict) or not tui_registration(rec) or rec.get("workspace") != self.workspace:
                continue
            if rec.get("session"):
                session = self.herdr_session() if session is None else session
                if session and rec["session"] != session:
                    continue
            return rec
        return None

    def own_registration(self) -> dict[str, Any] | None:
        """The registration of the PM this session is."""
        if self.app_caller():
            rec = self.hc_registration(self.pane)
            return rec if rec and self._hc_pm_matches(rec.get("repo")) else None
        inventory = self.identity_inventory()
        caller = self.caller_identity(inventory)
        if not caller:
            return None
        for rec in inventory["records"]:
            if (rec["session"], rec["pane"]) == (caller["session"], caller["pane"]) and rec.get("verified"):
                return rec
        return None

    def current_pm_record(self, project: str | None = None, repo: str | Path = ".") -> dict[str, Any] | None:
        """Registration of the PM named by project (slug, project or PM name), else of this session, else of repo."""
        if self._current_pm_record_fn is not None:
            if project is None and repo == ".":
                return self._current_pm_record_fn()
            if project is None:
                return self._current_pm_record_fn(repo=repo)
            if repo == ".":
                return self._current_pm_record_fn(project)
            return self._current_pm_record_fn(project, repo)
        if project:
            if self.app_caller():
                regs_dir = self.ctx.home.registrations
                recs = [json.loads(p.read_text()) for p in sorted(regs_dir.glob("*.json"))] if regs_dir.exists() else []
            else:
                recs = self.identity_inventory()["records"]
            for rec in recs:
                if project in (project_slug(rec.get("repo") or "."), rec.get("project"), rec.get("name")):
                    return rec
            return None
        return (self.own_registration() if self.pane else None) or self._projects.pm_record(repo)

    def memory_writer(self, repo: str | Path) -> tuple[str, str]:
        """(role, by) of the session writing a memory."""
        if not self.pane:
            return "user", "user"
        rec = self._projects.pm_record(repo)
        if rec and rec.get("pane") == self.pane and not rec.get("archived") and self.manages(repo):
            return "pm", "pm"

        def _matches_worker(t: dict[str, Any] | None) -> bool:
            if not t or t.get("status") not in ACTIVE or not pm_started(t):
                return False
            t_repo = t.get("repo")
            return bool(t_repo and (in_scope(t_repo, repo) or in_scope(repo, t_repo)))

        task = self.own_task
        if not _matches_worker(task):
            task = next(
                (t for t in self._ledger.raw_tasks() if t.get("pane") == self.pane and _matches_worker(t)),
                None,
            )
        if task:
            return "worker", f"worker:{task['id']}"
        helper = self.helper
        if helper and (not helper.get("project") or helper.get("project") == project_slug(repo)):
            name = helper.get("name") or self.terminal or self.pane
            return "helper", f"helper:{name}"
        return "other", f"session:{self.pane}"

    def helper_caller_identity(self) -> tuple[str, Any]:
        """Actual identity of this terminal, independent of --task/--pm flags:
        ('helper', self_info), ('pm', rec), ('task', task), ('worker_unknown', None), or ('cli', None)."""
        self_info = self.helper
        if self_info:
            return "helper", self_info
        if self.pane:
            rec = self.own_pm_record()
            if not rec and self.pane.startswith("hc:"):
                hc_rec = self.hc_registration(self.pane)
                if hc_rec and self._hc_pm_matches(hc_rec.get("repo")):
                    rec = hc_rec
            if rec and not rec.get("archived"):
                return "pm", rec
            if not (self.terminal and self.labels.get("pm")):
                task = self.own_task
                if not task:
                    matches = [
                        t for t in self._ledger.raw_tasks()
                        if t.get("pane") == self.pane and t.get("status") in ACTIVE and pm_started(t)
                    ]
                    if len(matches) == 1:
                        task = matches[0]
                if task:
                    return "task", task
            return "worker_unknown", None
        return "cli", None

    def manages(self, repo: str | Path) -> bool:
        """Whether this terminal is one the PM of repo's project writes from (its own, or the one it took over)."""
        if not self.pane or self.pane not in self._projects.pm_panes(repo):
            return False
        if self.terminal:
            return self._hc_pm_matches(repo)
        if self.in_tui():
            rec = self._projects.pm_record(repo) or {}
            if rec.get("session") and rec["session"] != (self.herdr_session() or rec["session"]):
                return False
            return self._tui_pm_matches(repo)
        return True

    def role_in(self, project: str | Path) -> Role:
        """This caller's Role in the project at `project` (its folder, as a task's `repo`)."""
        if not self.pane:
            return Role(Role.USER)
        if self.manages(project):
            return Role(Role.MANAGER)
        mine = self.own_task
        if mine and pm_started(mine):
            mine_repo = mine.get("repo")
            if mine_repo and (in_scope(mine_repo, project) or in_scope(project, mine_repo)):
                return Role(Role.REVIEWER if mine.get("review_of") else Role.WORKER, task=mine.get("id"))
        helper = self.helper
        if helper and helper.get("project") == project_slug(project):
            return Role(Role.HELPER, owner=helper.get("of") or None)
        return Role(Role.SESSION)


# ---- Legacy module-level thin wrappers (Stages 1-5 compatibility) ---------------------------------------------------


def strict_herdr(*args, session=None):
    return Caller.current().strict_herdr(*args, session=session)


def herdr_sessions():
    """The local herdr sessions ({name, socket_path, running}), checked; IdentityError when they cannot be read."""
    return Caller.current().herdr_sessions()


def socket_session(sessions):
    """The running session whose socket this process inherited (`herdr status server`)."""
    return Caller.current().socket_session(sessions)


def herdr_session():
    """Name of the herdr session this pane runs in, or "" when it cannot be told (best effort, never raises)."""
    return Caller.current().herdr_session()


_DEFAULT_HERDR_SESSION = herdr_session


def identity_inventory():
    """Read every running local session and reconcile registrations without changing them."""
    return Caller.current().identity_inventory()


def caller_identity(inventory):
    """The inherited socket, pane and workspace must identify the same running pane."""
    return Caller.current().caller_identity(inventory)


def inventory_pm(repo=None, inventory=None):
    """The registered project PM across sessions, or the caller workspace's PM."""
    return Caller.current().inventory_pm(repo=repo, inventory=inventory)


def app_caller():
    """A session of the desktop app (a herdr-core terminal), not of the herdr terminal UI."""
    return Caller.current().app_caller()


def hc_registration(pane):
    return Caller.current().hc_registration(pane)


def hc_role(action="read", repo="."):
    """check_role in the desktop app: the PM is the terminal its registration names while herdr-core shows it live
    and labelled pm=<project>. A registration naming this terminal that herdr-core does not confirm is uncertain."""
    return Caller.current().hc_role(action=action, repo=repo)


def check_role(action="read", repo="."):
    """The caller's role: pm, worker, observer (outside herdr: read only) or uncertain (read only).
    IdentityError when the action is not allowed or the identity cannot be verified."""
    return Caller.current().check_guard(action=action, repo=repo)


_DEFAULT_CHECK_ROLE = check_role


def blocked_by_worker(task):
    """Whether the latest entry that blocked `task` was written by a worker (neither this PM nor the user)."""
    return Caller.current().blocked_by_worker(task)


def is_pm_caller(task=None, repo=None):
    """Whether the current process runs from the project's PM terminal."""
    return Caller.current().is_pm_caller(task=task, repo=repo)


def own_task():
    """The open task this session works on, only where that can be checked."""
    return Caller.current().own_task


def caller_projects(reg_idx):
    """The projects this terminal works in, most certain first, lazily evaluated."""
    return Caller.current().caller_projects(reg_idx)


def workspace_registration():
    """In the herdr TUI: the registration of the PM whose workspace this pane is in, or None. Never raises."""
    return Caller.current().workspace_registration()


def own_registration():
    """The registration of the PM this session is."""
    return Caller.current().own_registration()


def current_pm_record(project=None, repo="."):
    """Registration of the PM named by project (slug, project or PM name), else of this session, else of repo."""
    return Caller.current().current_pm_record(project=project, repo=repo)


_DEFAULT_CURRENT_PM_RECORD = current_pm_record


def in_tui():
    """This session runs in a pane of the herdr terminal UI ($HERDR_PANE_ID), not in the desktop app's herdr-core."""
    return Caller.current().in_tui()


_DEFAULT_IN_TUI = in_tui


def pm_record_for_pane(pane):
    return Caller.current().pm_record_for_pane(pane)


def own_pm_record(cwd=None):
    """The registration of the PM this session is, for its hooks: the one naming its pane."""
    return Caller.current().own_pm_record(cwd=cwd)


def memory_writer(repo):
    """(role, by) of the session writing a memory."""
    return Caller.current().memory_writer(repo)


def helper_self_info():
    """If this process runs inside a helper terminal, return {of, name, project, terminal}; else None."""
    return Caller.current().helper_self_info()


def _helper_caller_identity():
    """Actual identity of this terminal, independent of --task/--pm flags."""
    return Caller.current().helper_caller_identity()
