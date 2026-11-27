"""What the deliverer does for helpers each round: the terminals of running helpers, and watching them finish, time out,
stall or ask. Layer 3.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..agents.base import HOOKED_KINDS, terminal_kind
from ..context import Context
from ..events import stalls as stalls_mod
from ..home import project_slug
from ..ledger.ledger import Change, Ledger
from ..ledger.task import Task
from ..messaging.address import parse_legacy_endpoint
from ..messaging.typist import unblock_endpoint
from ..project.conversation import Conversation
from ..terminals.events import RECONCILE
from ..terminals.screen import classify_stuck_screen, known_prompt_action
from .records import (
    _clear_helper_cleanup_for,
    _harvest_entry_for,
    _send_to_worker_if_active_for,
    helper_elapsed,
    helper_entries,
    helper_remaining,
    helper_wait_active_for,
    kill_helper_terminal_for,
)


class HelperWatcher:
    """Deliverer watcher for running helpers and finished helpers pending terminal cleanup, over an explicit `Context`."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._ledger = Ledger(ctx)

    def active_terminals(self, repo: str | Path) -> set[str]:
        """Set of hc terminal addresses of running helpers (and finished helpers pending cleanup) in `repo`.
        No hc calls."""
        if not repo:
            return set()
        repo_str = str(repo)
        slug = project_slug(repo_str)
        reg = self.ctx.store.registration(slug)
        terms = {
            h["terminal"] for h in helper_entries(reg)
            if h.get("terminal") and (h.get("status") == "running" or h.get("cleanup_term"))
        }
        for t in self._ledger.project_tasks(repo_str):
            for h in helper_entries(t):
                if h.get("terminal") and (h.get("status") == "running" or h.get("cleanup_term")):
                    terms.add(h["terminal"])
        return terms

    def look(self, repo: str | Path, stops: dict[Any, Any], bases: Any = None) -> float:
        """Called from `Deliverer.look`: manage all project helpers (both PM-owned and worker-owned):
        - end finished helpers that ran `helper done` once their turn ends (`cleanup_term`),
        - sweep timeouts,
        - reap exited/removed terminals (`gone`),
        - alert owners when a helper sits in `blocked`/`error`,
        - harvest unhooked helpers (agy/pi) that stopped after their turn without running `helper done`
          (skipped for a worker currently inside `helper wait`, which harvests them directly).
        Returns seconds until next check. Fast-path: zero hc calls when no helper is running or pending cleanup."""
        if not repo:
            return float(RECONCILE)
        repo_str = str(repo)
        slug = project_slug(repo_str)
        reg = self.ctx.store.registration(slug)
        owners: list[tuple[str, str, str, str, Any]] = []
        if any(h.get("status") == "running" or h.get("cleanup_term") for h in helper_entries(reg)):
            owners.append(("pm", f"pm-{slug}", slug, repo_str, reg))
        for t in self._ledger.project_tasks(repo_str):
            if any(h.get("status") == "running" or h.get("cleanup_term") for h in helper_entries(t)):
                owners.append(("task", t["id"], slug, t.get("repo") or repo_str, t))
        if not owners:
            return float(RECONCILE)

        stall_grace = stalls_mod.STALL_GRACE
        round_start = stalls_mod.ROUND_START
        now_m, due, seen = self.ctx.clock.monotonic(), float(RECONCILE), set()
        for owner_kind, owner_id, oslug, orepo, owner_rec in owners:
            entries = helper_entries(owner_rec)
            waiting = helper_wait_active_for(self.ctx, owner_id)
            # 1. Clean up helpers that already ran `helper done` once their turn finishes.
            for h in entries:
                if h.get("status") == "running" or not h.get("cleanup_term") or not h.get("terminal"):
                    continue
                if waiting:
                    continue  # helper wait handles terminal cleanup (and respects --keep)
                term = h["terminal"]
                info = self.ctx.hc.get_raw(term, errors=True) or {}
                state = (info.get("status") or {}).get("state")
                bg = bool(self.ctx.procs.background_work(info)) if info.get("state") == "live" and not info.get("error") else False
                if (info.get("error") or info.get("state") != "live" or (state in ("idle", "done") and not bg)
                        or (info.get("reported") and not info.get("status"))):
                    kill_helper_terminal_for(self.ctx, term)
                    _clear_helper_cleanup_for(self.ctx, owner_kind, owner_id, oslug, term)
                else:
                    due = min(due, stall_grace)

            # 2. Watch running helpers for timeout, exit, blocked/error dialog, or unreported stop.
            for h in entries:
                if h.get("status") != "running":
                    continue
                term = h.get("terminal") or ""
                name = h.get("name") or "?"
                if not term:
                    continue
                rem = helper_remaining(h, clock=self.ctx.clock)
                if rem <= 0:
                    _harvest_entry_for(
                        self.ctx, owner_kind, owner_id, oslug, orepo, h, reason="timeout", kill_term=True, notify=True,
                    )
                    continue
                due = min(due, rem)
                if waiting:
                    continue  # worker is actively blocked in `helper wait`, which observes hc events directly
                info = self.ctx.hc.get_raw(term, errors=True) or {}
                if info.get("error") and (info.get("error") or {}).get("kind") != "not_found":
                    continue
                gone = ((info.get("error") or {}).get("kind") == "not_found"
                        or info.get("state") != "live"
                        or (info.get("reported") and not info.get("status")))
                if gone:
                    _harvest_entry_for(
                        self.ctx, owner_kind, owner_id, oslug, orepo, h, reason="gone", kill_term=False, notify=True,
                    )
                    continue
                state = (info.get("status") or {}).get("state")
                turn = info.get("turn") or 0
                stop_key = ("helper", term)
                if state in ("blocked", "error"):
                    seen.add(stop_key)
                    key = f"{term}:{state}:{turn}"
                    known = stops.get(stop_key)
                    if not known or known[0] != key:
                        stops[stop_key] = (key, now_m, False)
                        due = min(due, stall_grace)
                        continue
                    if known[2]:
                        continue
                    if now_m - known[1] < stall_grace:
                        due = min(due, stall_grace - (now_m - known[1]))
                        continue
                    raw_screen = self.ctx.hc.read(term)
                    pkind, keys = known_prompt_action(
                        raw_screen, allow_trust=self.ctx.git.is_owned_worktree(h.get("cwd") or ""),
                    )
                    auto_key = ("helper-auto", term, pkind)
                    ep = parse_legacy_endpoint(f"hc:{term}", runtime_hint="hc")
                    pressed = (unblock_endpoint(self.ctx, ep, keys)
                               if keys and stops.get(auto_key, 0) < 2 and ep is not None else False)
                    if pressed is None:  # another typist on this terminal right now: look again, not stuck yet
                        due = min(due, stall_grace)
                        continue
                    if pressed:
                        stops[auto_key] = stops.get(auto_key, 0) + 1
                        stops.pop(stop_key, None)
                        due = min(due, stall_grace)
                        continue
                    diag = classify_stuck_screen(raw_screen)
                    screen = diag["summary"] or self.ctx.hc.screen_line(term, width=200)
                    msg = self.ctx.config.tr(
                        f"helper {name} (hc:{term}) is {state} ({diag['kind']}): {screen}; "
                        f"stop with `pm.py helper stop {name}`",
                        f"helper {name}（hc:{term}）处于 {state}（{diag['kind']}）：{screen}；"
                        f"可用 `pm.py helper stop {name}` 停掉",
                    )
                    if owner_kind == "pm":
                        Conversation(self.ctx, orepo).record(
                            "helper", by=f"hc:{term}", source="helper", helper=name, status=state,
                            result=h.get("result") or "", text=msg, wake=not bool(h.get("quiet")), key=key,
                        )
                    else:
                        def _add_note(cur: Task | None, ch: Change, m: str = msg) -> dict[str, Any] | None:
                            if cur is None:
                                return None
                            ch.note(m)
                            return cur.raw
                        self._ledger.change(owner_id, _add_note)
                        _send_to_worker_if_active_for(self.ctx, owner_id, h, f"[from helper {name}] {msg}")
                    stops[stop_key] = (key, known[1], True)
                    continue
                handed = h.get("handed")
                turn_base = h.get("turn_base")
                ready_to_judge = (handed is True and turn_base is not None) or helper_elapsed(h, clock=self.ctx.clock) >= round_start
                hooked = (h.get("kind") or terminal_kind(info)) in HOOKED_KINDS
                if state in ("idle", "done") and ready_to_judge and not hooked and turn > (turn_base or 0):
                    if self.ctx.procs.background_work(info):
                        due = min(due, stall_grace)
                        continue
                    seen.add(stop_key)
                    key = f"{term}:idle:{turn}"
                    known = stops.get(stop_key)
                    if not known or known[0] != key:
                        stops[stop_key] = (key, now_m, False)
                        due = min(due, stall_grace)
                        continue
                    if now_m - known[1] < stall_grace:
                        due = min(due, stall_grace - (now_m - known[1]))
                        continue
                    fresh_rec = self.ctx.store.registration(oslug) if owner_kind == "pm" else self.ctx.store.task(owner_id)
                    fresh = next((x for x in helper_entries(fresh_rec) if x.get("terminal") == term), None)
                    if fresh and fresh.get("status") == "running":
                        _harvest_entry_for(
                            self.ctx, owner_kind, owner_id, oslug, orepo, fresh,
                            reason="unreported", kill_term=True, notify=True,
                        )
                    stops[stop_key] = (key, known[1], True)
        for k in [k for k in list(stops) if isinstance(k, tuple) and len(k) == 2 and k[0] == "helper" and k not in seen]:
            del stops[k]
        return due


# ── Legacy module-level wrappers (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────


def active_helper_terminals(repo: str | Path) -> set[str]:
    return HelperWatcher(Context.from_env()).active_terminals(repo)


def watch_helpers(repo: str | Path, stops: dict[Any, Any], bases: Any = None) -> float:
    return HelperWatcher(Context.from_env()).look(repo, stops, bases)
