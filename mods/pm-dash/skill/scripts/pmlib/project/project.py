"""Projects and their coordinators as the ledger home registers them (`pms/<slug>.json`): `Coordinator`, `Project`,
`ProjectRegistry`, plus legacy module-level wrappers. Layer 2.

Whether a seated PM's seat process still runs is injected via `ctx.seat_alive` (or `ProjectRegistry(..., seat_alive=)`),
eliminating module-level callback globals.
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from ..context import Context
from ..home import project_slug
from ..store import SLUG_RE, StoreError
from .turn_reducer import Endpoint, record_endpoint


def _every_seat_alive(repo: Any, rec: Any, term: Any = None) -> bool:
    return True


def pm_name(repo: str | Path) -> str:
    return f"pm-{project_slug(repo)}"


def in_scope(repo: str | Path | None, scope: str | Path) -> bool:
    """repo is the folder scope or one under it. Not a sibling that only starts with its name (dudu-old)."""
    if not repo:
        return False
    return Path(repo).resolve().is_relative_to(Path(scope).resolve())


class Coordinator:
    """Dict-preserving view over a project's manager registration (`pms/<slug>.json`)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def raw(self) -> dict[str, Any]:
        return self._data

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: object) -> bool:
        return key in self._data

    @property
    def name(self) -> str:
        return str(self._data.get("name") or "")

    @property
    def project(self) -> str:
        return str(self._data.get("project") or "")

    @property
    def repo(self) -> str:
        return str(self._data.get("repo") or "")

    @property
    def runtime(self) -> str:
        return str(self._data.get("runtime") or "")

    @property
    def terminal(self) -> str:
        return str(self._data.get("terminal") or "")

    @property
    def pane(self) -> str:
        return str(self._data.get("pane") or "")

    @property
    def agent(self) -> str:
        return str(self._data.get("agent") or "")

    @property
    def archived(self) -> bool:
        return bool(self._data.get("archived"))

    @property
    def previous(self) -> dict[str, Any]:
        prev = self._data.get("previous")
        return prev if isinstance(prev, dict) else {}

    @property
    def panes(self) -> set[str]:
        return {p for p in (self._data.get("pane"), self.previous.get("pane")) if p}

    @property
    def is_app_pm(self) -> bool:
        return bool(self.runtime == "hc" and self.terminal and not self.archived)

    @property
    def endpoint(self) -> Endpoint | None:
        return record_endpoint(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Coordinator):
            return self._data == other._data
        return NotImplemented

    def __repr__(self) -> str:
        return f"Coordinator(name={self.name!r}, runtime={self.runtime!r}, pane={self.pane!r})"


class Project:
    """Project metadata view paired with its `Coordinator` registration over `pms/<slug>.json`."""

    def __init__(self, slug: str, data: dict[str, Any]) -> None:
        self.slug = slug
        self._data = data
        self.coordinator = Coordinator(data)

    @property
    def raw(self) -> dict[str, Any]:
        return self._data

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    @property
    def name(self) -> str:
        return str(self._data.get("project") or self.slug)

    @property
    def repo(self) -> str:
        return str(self._data.get("repo") or "")

    @property
    def archived(self) -> bool:
        return bool(self._data.get("archived"))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Project):
            return self.slug == other.slug and self._data == other._data
        return NotImplemented

    def __repr__(self) -> str:
        return f"Project(slug={self.slug!r}, repo={self.repo!r})"


class ProjectRegistry:
    """Domain registry for projects and their live managers over an explicit `Context`."""

    def __init__(
        self,
        ctx: Context,
        *,
        seat_alive: Callable[..., bool] | None = None,
        _hc_pm_fn: Callable[[Any], dict[str, Any] | None] | None = None,
        _pm_record_fn: Callable[[Any], dict[str, Any] | None] | None = None,
    ) -> None:
        self.ctx = ctx
        self._seat_alive = seat_alive if seat_alive is not None else (ctx.seat_alive or _every_seat_alive)
        self._hc_pm_fn = _hc_pm_fn
        self._pm_record_fn = _pm_record_fn

    def seat_says_alive(self, repo: Any, rec: Any, term: Any = None) -> bool:
        """What the injected seat check says of a seated PM's registration."""
        return bool(self._seat_alive(repo, rec, term))

    def _hc_pm_impl(self, root: str | Path | None) -> dict[str, Any] | None:
        if not root:
            return None
        try:
            rec = self.ctx.store.registration(project_slug(root)) or {}
        except StoreError:
            rec = {}
        if rec.get("runtime") != "hc" or not rec.get("terminal"):
            return None
        info = self.ctx.hc.get(rec["terminal"])
        if info is None:
            return None
        if info.state != "live" or info.labels.get("pm") != Path(root).name:
            return None
        term = dict(info.raw) if isinstance(info.raw, Mapping) and info.raw else {
            "address": info.address,
            "state": info.state,
            "labels": dict(info.labels),
            "cwd": info.cwd,
            "status": {"state": info.agent_state} if info.agent_state else {},
        }
        if not self.seat_says_alive(root, rec, term):
            return None
        cwd = info.raw.get("cwd") if isinstance(info.raw, Mapping) and info.raw else (info.cwd or None)
        return {
            "pane_id": f"hc:{rec['terminal']}",
            "name": rec["name"],
            "cwd": cwd,
            "agent_status": info.agent_state,
            "workspace_id": "",
        }

    def hc_pm(self, root: str | Path | None) -> dict[str, Any] | None:
        """The registered herdr-core PM of the project at root, if its terminal is live and still labelled pm=<project>."""
        if self._hc_pm_fn is not None:
            return self._hc_pm_fn(root)
        if getattr(self.ctx, "_legacy", False) and hc_pm is not _DEFAULT_HC_PM:
            return hc_pm(root)
        return self._hc_pm_impl(root)

    def _find_pm_impl(self, listing: list[dict[str, Any]] | None = None, repo: str | Path | None = None) -> dict[str, Any] | None:
        listing = self.ctx.tui.agents() if listing is None else listing
        root = self.ctx.git.project_root(repo or ".")
        if not root:
            return None
        in_hc = self.hc_pm(root)
        if in_hc:
            return in_hc
        want = pm_name(root)
        pms = [a for a in listing if a.get("name") == want]
        pms.sort(key=lambda a: a.get("workspace_id") != self.ctx.workspace)
        return pms[0] if pms else None

    def find_pm(self, listing: list[dict[str, Any]] | None = None, repo: str | Path | None = None) -> dict[str, Any] | None:
        """The PM agent for the project containing repo (default: the current directory).

        The PM is the herdr agent named pm-<project slug>, or the herdr-core terminal its registration names
        (runtime "hc"); outside a repository there is none. The registration decides when both exist.
        """
        if getattr(self.ctx, "_legacy", False) and find_pm is not _DEFAULT_FIND_PM:
            if listing is None and repo is None:
                return find_pm()
            if listing is None:
                return find_pm(repo=repo)
            if repo is None:
                return find_pm(listing)
            return find_pm(listing, repo)
        return self._find_pm_impl(listing=listing, repo=repo)

    def _pm_record_impl(self, repo: str | Path | None) -> dict[str, Any] | None:
        root = self.ctx.git.project_root(repo or ".")
        return self.ctx.store.registration(project_slug(root)) if root else None

    def pm_record(self, repo: str | Path | None) -> dict[str, Any] | None:
        """The registration file of the PM for repo, or None."""
        if self._pm_record_fn is not None:
            return self._pm_record_fn(repo)
        if getattr(self.ctx, "_legacy", False) and pm_record is not _DEFAULT_PM_RECORD:
            return pm_record(repo)
        return self._pm_record_impl(repo)

    def coordinator(self, repo: str | Path | None) -> Coordinator | None:
        rec = self.pm_record(repo)
        return Coordinator(rec) if isinstance(rec, dict) else None

    def get(self, slug: str) -> Project | None:
        rec = self.ctx.store.registration(slug)
        return Project(slug, rec) if isinstance(rec, dict) else None

    def status_scope(self, tasks: list[dict[str, Any]], repo: str | Path, everything: bool = False) -> str | None:
        """The project `status` lists by default: the one at repo, when a PM is registered for that very folder or the
        ledger has tasks in it; its tasks include those in folders under it (in_scope). None lists every project: --all,
        a folder that is no project, or the hub's folder (it sits in the ledger home and coordinates every project)."""
        root = None if everything else self.ctx.git.project_root(repo)
        if not root or Path(root).resolve().is_relative_to(self.ctx.home.root.resolve()):
            return None
        path = self.ctx.home.registration(project_slug(root))
        try:
            registered = path.exists() and json.loads(path.read_text()).get("repo") == root
        except (OSError, ValueError):
            registered = False
        return root if registered or any(t.get("repo") == root for t in tasks) else None

    def _app_pm_impl(self, repo: str | Path | None) -> dict[str, Any] | None:
        if not repo:
            return None
        rec = self.pm_record(repo)
        return rec if rec and rec.get("runtime") == "hc" and rec.get("terminal") and not rec.get("archived") else None

    def app_pm(self, repo: str | Path | None) -> dict[str, Any] | None:
        """The registration of repo's PM when it runs in the desktop app (a herdr-core terminal), else None: only such
        a PM has events delivered to it."""
        if getattr(self.ctx, "_legacy", False) and app_pm is not _DEFAULT_APP_PM:
            return app_pm(repo)
        return self._app_pm_impl(repo)

    def pm_panes(self, repo: str | Path | None) -> set[str]:
        """The terminals the PM of repo's project writes from: its own and the one it took over from."""
        rec = self.pm_record(repo) or {}
        return {rec.get("pane"), (rec.get("previous") or {}).get("pane")} - {None, ""}

    def registered_repo(self, project: str | Path) -> str | None:
        """The folder of a project given as its folder, or as the name it is registered under."""
        if Path(project).is_dir():
            return self.ctx.git.project_root(project)
        regs = self.ctx.home.registrations
        for path in sorted(regs.glob("*.json")) if regs.exists() else []:
            rec = json.loads(path.read_text())
            if project in (rec.get("project"), path.stem) and rec.get("repo"):
                return rec["repo"]
        return None

    def pm_records(self) -> list[dict[str, Any]]:
        out = []
        regs = self.ctx.home.registrations
        for path in sorted(regs.glob("*.json")) if regs.exists() else []:
            with contextlib.suppress(OSError, ValueError):
                rec = json.loads(path.read_text())
                out.append({**rec, "name": rec.get("name") or "", "project": rec.get("project") or "",
                            "repo": rec.get("repo") or ""})
        return out

    def all_projects(self) -> list[Project]:
        out: list[Project] = []
        regs = self.ctx.home.registrations
        for path in sorted(regs.glob("*.json")) if regs.exists() else []:
            with contextlib.suppress(OSError, ValueError):
                rec = json.loads(path.read_text())
                if isinstance(rec, dict):
                    out.append(Project(path.stem, rec))
        return out

    def pm_record_for_project(self, project: str) -> dict[str, Any] | None:
        regs = self.ctx.home.registrations
        for p in regs.glob("*.json") if regs.exists() else []:
            try:
                rec = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            if rec.get("project") == project:
                return rec
        return None

    def resolve_project_slug(self, target: Any) -> str:
        """Resolve a project slug, PM name (pm-<slug>), registered project name or folder to its canonical slug."""
        if not isinstance(target, str) or not target:
            return ""
        if SLUG_RE.match(target):
            if self.ctx.store.has_project(target):
                return target
            if target.startswith("pm-") and SLUG_RE.match(target[3:]) and self.ctx.store.has_project(target[3:]):
                return target[3:]
        with contextlib.suppress(OSError):
            if Path(target).is_dir():
                root = self.ctx.git.project_root(target)
                if root:
                    return project_slug(root)
        for rec in self.ctx.store.registrations():
            if target in (rec.get("project"), rec.get("name")) or str(rec.get("project") or "").lower() == target.lower():
                repo = rec.get("repo")
                if isinstance(repo, str) and repo:
                    return project_slug(repo)
                name = str(rec.get("name") or "")
                if name.startswith("pm-") and SLUG_RE.match(name[3:]):
                    return name[3:]
        return target


def seat_says_alive(repo: Any, rec: Any, term: Any = None) -> bool:
    """What the registered seat check says of a seated PM's registration (the deliverer asks it on each look)."""
    return ProjectRegistry(Context.from_env()).seat_says_alive(repo, rec, term)


def hc_pm(root: str | Path | None) -> dict[str, Any] | None:
    """The registered herdr-core PM of the project at root, if its terminal is live and still labelled pm=<project>."""
    return ProjectRegistry(Context.from_env())._hc_pm_impl(root)


_DEFAULT_HC_PM = hc_pm


def find_pm(listing: list[dict[str, Any]] | None = None, repo: str | Path | None = None) -> dict[str, Any] | None:
    """The PM agent for the project containing repo (default: the current directory)."""
    return ProjectRegistry(Context.from_env())._find_pm_impl(listing=listing, repo=repo)


_DEFAULT_FIND_PM = find_pm


def pm_record(repo: str | Path | None) -> dict[str, Any] | None:
    """The registration file of the PM for repo, or None."""
    return ProjectRegistry(Context.from_env())._pm_record_impl(repo)


_DEFAULT_PM_RECORD = pm_record


def status_scope(tasks: list[dict[str, Any]], repo: str | Path, everything: bool = False) -> str | None:
    """The project `status` lists by default."""
    return ProjectRegistry(Context.from_env()).status_scope(tasks, repo, everything=everything)


def app_pm(repo: str | Path | None) -> dict[str, Any] | None:
    """The registration of repo's PM when it runs in the desktop app (a herdr-core terminal), else None."""
    return ProjectRegistry(Context.from_env())._app_pm_impl(repo)


_DEFAULT_APP_PM = app_pm


def pm_panes(repo: str | Path | None) -> set[str]:
    """The terminals the PM of repo's project writes from: its own and the one it took over from."""
    return ProjectRegistry(Context.from_env()).pm_panes(repo)


def registered_repo(project: str | Path) -> str | None:
    """The folder of a project given as its folder, or as the name it is registered under."""
    return ProjectRegistry(Context.from_env()).registered_repo(project)


def pm_records() -> list[dict[str, Any]]:
    return ProjectRegistry(Context.from_env()).pm_records()


def pm_record_for_project(project: str) -> dict[str, Any] | None:
    return ProjectRegistry(Context.from_env()).pm_record_for_project(project)


def resolve_project_slug(target: Any) -> str:
    """Resolve a project slug, PM name (pm-<slug>), registered project name or folder to its canonical slug."""
    return ProjectRegistry(Context.from_env()).resolve_project_slug(target)
