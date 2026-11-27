"""Paths in the ledger home: `Home` and `ProjectFiles`. Paths only; `project_dir` and `ProjectFiles.ensure()`
make the project's folder when explicitly requested. Layer 1.

In Stages 1-5, `current()` builds a `Home` from `context.legacy_home_args()` on each call so tests that assign
`pm.STATE`, `pm.TASKS`, `pm.PMS` or `pm.PROJECTS` are seen at once.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Mapping


def project_slug(repo: str | Path) -> str:
    """Lowercase project name usable in a herdr agent name."""
    return re.sub(r"[^a-z0-9_-]+", "-", Path(repo).resolve().name.lower()).strip("-")[:28] or "project"


from . import context  # noqa: E402 - import after project_slug so store <- home <- context <- procs <- store has no cycle


class ProjectFiles:
    """Every path inside one `projects/<slug>/` folder. Paths only: properties do not touch disk."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def __fspath__(self) -> str:
        return str(self.root)

    def __truediv__(self, other: str | Path) -> Path:
        return self.root / other

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ProjectFiles):
            return self.root == other.root
        return NotImplemented

    def __repr__(self) -> str:
        return f"ProjectFiles({str(self.root)!r})"

    def ensure(self) -> Path:
        """Create the project directory if missing and return its `Path`."""
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    @property
    def conversation(self) -> Path:
        return self.root / "conversation.jsonl"

    @property
    def receipts(self) -> Path:
        return self.root / "receipts.json"

    @property
    def receipts_lock(self) -> Path:
        return self.root / "receipts.lock"

    @property
    def delivered(self) -> Path:
        return self.root / "delivered.json"

    @property
    def delivered_lock(self) -> Path:
        return self.root / "delivered.lock"

    @property
    def deliver_lock(self) -> Path:
        return self.root / "deliver.lock"

    @property
    def seat_state(self) -> Path:
        return self.root / "seat.json"

    @property
    def seat_lock(self) -> Path:
        return self.root / "seat.lock"

    @property
    def next_session(self) -> Path:
        return self.root / "next-session.json"

    @property
    def turn_cause(self) -> Path:
        return self.root / "turn-cause.json"

    @property
    def taken_in(self) -> Path:
        return self.root / "taken-in.json"

    @property
    def agy_transcript(self) -> Path:
        return self.root / "agy-transcript.json"

    @property
    def pm_turn(self) -> Path:
        return self.root / "pm-turn.json"

    @property
    def pm_turn_lock(self) -> Path:
        return self.root / "pm-turn.lock"

    @property
    def pm_turn_journal(self) -> Path:
        return self.root / "pm-turn-journal.jsonl"

    @property
    def pm_turn_journal_prev(self) -> Path:
        return self.root / "pm-turn-journal.1.jsonl"

    @property
    def pm_turn_beat(self) -> Path:
        return self.root / "pm-turn.beat"

    @property
    def mailboxes(self) -> Path:
        return self.root / "mailboxes"

    @property
    def pm_mailbox(self) -> Path:
        return self.mailboxes / "pm"

    @property
    def inbound_reports_mailbox(self) -> Path:
        return self.mailboxes / "inbound-reports"

    def endpoint_mailbox(self, safe_uid: str) -> Path:
        return self.mailboxes / "endpoints" / safe_uid

    @property
    def applied_reports_json(self) -> Path:
        return self.root / "applied-reports.json"

    @property
    def applied_reports_jsonl(self) -> Path:
        return self.root / "applied-reports.0001.jsonl"

    @property
    def applied_reports_lock(self) -> Path:
        return self.root / "applied-reports.lock"

    @property
    def task_seq(self) -> Path:
        return self.root / "task-seq.json"

    @property
    def handover(self) -> Path:
        return self.root / "handover.md"

    @property
    def verify(self) -> Path:
        return self.root / "verify"

    @property
    def pm_settings(self) -> Path:
        return self.root / "pm-settings.json"

    @property
    def decisions(self) -> Path:
        return self.root / "decisions.md"

    @property
    def library_state(self) -> Path:
        return self.root / "library.json"

    @property
    def research_sources(self) -> Path:
        return self.root / "research-sources.json"

    @property
    def docs(self) -> Path:
        return self.root / "docs"

    @property
    def docs_research(self) -> Path:
        return self.root / "docs" / "research"

    @property
    def research(self) -> Path:
        return self.root / "research"

    @property
    def attachments(self) -> Path:
        return self.root / "attachments"

    @property
    def memory(self) -> Path:
        return self.root / "memory"

    @property
    def memory_candidates(self) -> Path:
        return self.root / "memory" / "candidates"

    @property
    def memory_history(self) -> Path:
        return self.root / "memory" / ".history"

    @property
    def helpers(self) -> Path:
        return self.root / "helpers"

    def helper_dir(self, owner_dir: str) -> Path:
        return self.helpers / owner_dir


class Home:
    """Where things are in a ledger home. Paths only: nothing here reads or writes the disk.

    The folders are given one by one (tests point TASKS or PROJECTS somewhere of their own); a folder not given is
    the usual one under root.
    """

    def __init__(
        self,
        root: Path | str,
        tasks: Path | str | None = None,
        registrations: Path | str | None = None,
        projects: Path | str | None = None,
        inbox: Path | str | None = None,
        board: Path | str | None = None,
    ) -> None:
        self.root = Path(root)
        self.tasks = Path(tasks) if tasks is not None else self.root / "tasks"
        self.registrations = Path(registrations) if registrations is not None else self.root / "pms"
        self.projects = Path(projects) if projects is not None else self.root / "projects"
        self.inbox = Path(inbox) if inbox is not None else self.root / "inbox"
        self.board = Path(board) if board is not None else self.root / "BOARD.md"

    @classmethod
    def from_env(cls, home_option: Path | str | None = None, *, env: Mapping[str, str] | None = None) -> Home:
        """Build a `Home` from `--home` (if given) else `context.default_home(env=env)`."""
        return cls(home_option) if home_option else cls(context.default_home(env=env))

    @property
    def config(self) -> Path:
        """config.json: personal settings."""
        return self.root / "config.json"

    @property
    def memory(self) -> Path:
        return self.root / "memory"

    @property
    def memory_history(self) -> Path:
        return self.root / "memory" / ".history"

    @property
    def sent_dir(self) -> Path:
        return self.root / "sent"

    @property
    def waits(self) -> Path:
        return self.root / "waits"

    @property
    def locks(self) -> Path:
        return self.root / "locks"

    @property
    def tmp(self) -> Path:
        return self.root / "tmp"

    @property
    def reads(self) -> Path:
        return self.root / "reads"

    @property
    def reattach(self) -> Path:
        return self.root / "reattach"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def context_tokens_cache(self) -> Path:
        return self.root / "cache" / "context-tokens.json"

    @property
    def turn_log(self) -> Path:
        return self.root / "turns.log"

    @property
    def pm_stall_log(self) -> Path:
        return self.root / "pm-stall.log"

    @property
    def pm_settings(self) -> Path:
        return self.root / "pm-settings.json"

    @property
    def discord_config(self) -> Path:
        return self.root / "discord.json"

    @property
    def discord_log(self) -> Path:
        return self.root / "discord.log"

    @property
    def mcp(self) -> Path:
        return self.root / "mcp"

    @property
    def tokens(self) -> Path:
        return self.root / "tokens"

    @property
    def typists(self) -> Path:
        """Per-endpoint `typist.lock` leases, shared by every mailbox that types into a terminal (single typist)."""
        return self.root / "mailboxes" / "typists"

    def endpoint_mailbox(self, safe_uid: str) -> Path:
        """Mailbox of an endpoint that no project's PM mailbox owns (no repo known)."""
        return self.root / "mailboxes" / "endpoints" / safe_uid

    def task(self, task_id: str) -> Path:
        """The task file of task_id: tasks/<id>.json."""
        return self.tasks / f"{task_id}.json"

    def registration(self, slug: str) -> Path:
        """The manager registration of a project: pms/<slug>.json."""
        return self.registrations / f"{slug}.json"

    def project(self, slug: str) -> ProjectFiles:
        """A project's own folder: projects/<slug>/ (conversation log, memory, seat files, ...)."""
        return ProjectFiles(self.projects / slug)

    def project_for(self, repo: str | Path) -> ProjectFiles:
        """A project's `ProjectFiles` resolved from its repository path."""
        return self.project(project_slug(repo))

    def memory_dir(self, repo: str | Path | None = None) -> Path:
        """The project's memory folder, or the personal one (`repo` is None)."""
        return self.project_for(repo).memory if repo else self.memory

    def sent(self, task_id: str) -> Path:
        return self.sent_dir / f"{task_id}.md"

    def sent_escalated(self, task_id: str) -> Path:
        return self.sent_dir / f"{task_id}.escalated.md"

    def wait_file(self, task_id: str) -> Path:
        return self.waits / f"{task_id}.json"

    def lock(self, name: str) -> Path:
        return self.locks / f"{name}.lock"

    def reattach_lock(self, task_id: str) -> Path:
        return self.reattach / f"{task_id}.lock"

    def inbox_log(self, name: str) -> Path:
        return self.inbox / f"{name}.log"

    def inbox_offset(self, name: str) -> Path:
        return self.inbox / f"{name}.offset"

    def inbox_watch_lock(self, name: str) -> Path:
        return self.inbox / f"{name}.watch.lock"

    def inbox_watch_states(self, name: str) -> Path:
        return self.inbox / f"{name}.watch-states.json"

    def store_dirs(self) -> tuple[Path, Path, Path, Path]:
        """Return `(root, registrations, tasks, projects)` as expected by `FileStore`."""
        return (self.root, self.registrations, self.tasks, self.projects)

    def __repr__(self) -> str:
        return f"Home({str(self.root)!r})"


def current() -> Home:
    """The Home of this process from the current environment."""
    return Home.from_env()


def seat_lock_path(repo: str | Path, create: bool = False) -> Path:
    return (project_dir(repo) / "seat.lock") if create else current().project_for(repo).seat_lock


def seat_state_path(repo: str | Path, create: bool = False) -> Path:
    return (project_dir(repo) / "seat.json") if create else current().project_for(repo).seat_state


def next_session_path(repo: str | Path, create: bool = False) -> Path:
    return (project_dir(repo) / "next-session.json") if create else current().project_for(repo).next_session


def inbox_path(name: str) -> Path:
    return current().inbox_log(name)


def verify_file(repo: str | Path) -> Path:
    return current().project_for(repo).verify


def project_dir(repo: str | Path) -> Path:
    return current().project_for(repo).ensure()


def memory_dir(repo: str | Path | None = None) -> Path:
    """The project's memory folder, or the personal one (repo None)."""
    return (project_dir(repo) if repo else current().root) / "memory"


def waits_dir() -> Path:
    return current().waits
