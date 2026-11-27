"""Rotation: swapping a project's PM session for a fresh one (in the herdr TUI, or inside the seat), naming the
new agent, falling back when it does not start, and ending the outgoing session once its turn is over. Layer 3."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

from ..agents.profiles import profiles as agent_profiles
from ..agents.sessions import claude_folder, opening, pm_session
from ..context import Context
from ..errors import Refused
from ..events.supervisor import deliver_under_typist_lock
from ..home import project_slug
from ..messaging.address import LogicalAddress, parse_legacy_endpoint
from ..messaging.envelope import P4_BATCH, Envelope, new_env_id
from ..messaging.principal import Principal
from ..osutil import shell_join
from ..procs import background_work
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry
from ..project.turn_reducer import record_endpoint
from ..project.turn_state import TurnTracker
from .launch import pm_argv, pm_model, pm_start_argv, successor_argv
from .seat import RETIRE_WAIT, record_swap_notice, swap_reason_text


def resolve_rotate_target(
    profile: str | None,
    model: str | None,
    fallback_kind: str,
    *,
    ctx: Context | None = None,
) -> tuple[str, str, str]:
    """Resolve `(agent_kind, model, effort)` for `pm.py rotate [--profile P] [--model M]`."""
    c = Context.from_env() if ctx is None else ctx
    eff_kind = str(fallback_kind or "claude").strip().lower() or "claude"
    eff_model = str(model or "").strip()
    eff_profile = str(profile or "").strip()
    if not eff_profile:
        return eff_kind, eff_model, ""
    table = agent_profiles(c.config.read())
    entry = table.get(eff_profile)
    if not isinstance(entry, Mapping):
        raise Refused(c.config.tr(
            f"unknown rotation profile {eff_profile!r}; known: {', '.join(table) or '(none)'}",
            f"未知的轮换档位 {eff_profile!r}；可用：{', '.join(table) or '（无）'}",
        ))
    kind_val = str(entry.get("kind") or eff_kind or "claude").strip().lower()
    model_val = eff_model or str(entry.get("model") or "").strip()
    effort_val = str(entry.get("effort") or "").strip()
    return kind_val, model_val, effort_val


def _apply_claude_effort(argv: list[str], effort: str) -> list[str]:
    if not effort:
        return list(argv)
    out = list(argv)
    cut = out.index("--") if "--" in out else len(out)
    head = out[:cut]
    cleaned: list[str] = []
    i = 0
    while i < len(head):
        if head[i] == "--effort" and i + 1 < len(head):
            i += 2
            continue
        cleaned.append(head[i])
        i += 1
    cleaned.extend(["--effort", effort])
    return cleaned + out[cut:]


def _rotate_herdr_impl(
    a: Any,
    repo: str,
    rec: dict[str, Any],
    previous: dict[str, Any],
    prompt: str,
    is_self: bool,
    *,
    ctx: Context,
) -> list[str]:
    """In herdr (TUI): the new PM starts in a new tab of the outgoing PM's workspace. Returns status lines."""
    c = ctx
    slug, name, old = project_slug(repo), rec["name"], rec.get("pane") or ""
    pane_info = c.tui.pane_get(old) or {}
    workspace = pane_info.get("workspace_id")
    made = re.search(r'"pane_id": "([^"]+)"', json.dumps(
        c.tui.tab_create("--workspace", workspace, "--cwd", repo, "--label", "pm", "--no-focus") or {})
    ) if workspace else None
    if not made:
        c.store.change_registration(slug, lambda cur: {**(cur or rec), "previous": previous})
        raise Refused(
            f"handover notes saved, but no tab could be opened beside {old or 'the old PM'}. Start a fresh "
            f"session by hand (references/hub.md, \"Restart a PM\", without --resume) and give it this prompt:\n{prompt}"
        )
    new = made.group(1)
    info = c.tui.pane_process_info(old)
    prev_kind = rec.get("agent") or "claude"
    profile_arg = getattr(a, "profile", None)
    model_arg = getattr(a, "model", None)
    kind, target_model, target_effort = resolve_rotate_target(profile_arg, model_arg, prev_kind, ctx=c)
    if kind != prev_kind:
        argv = pm_start_argv(repo, kind, pm_model(kind, target_model or None, ctx=c), prompt, ctx=c)
    else:
        program = Path(c.agents.start_argv(kind)[0]).name
        args = next((p["argv"][1:] for p in info.get("foreground_processes", [])
                     if p.get("argv") and Path(p["argv"][0]).name == program), [])
        argv = pm_argv(kind, successor_argv(kind, args, pm_model(kind, target_model or None, ctx=c), prompt, ctx=c), repo, ctx=c)
    if target_effort and kind == "claude":
        argv = _apply_claude_effort(argv, target_effort)
    # The name must be free for the new session, and the registration names its pane before it starts.
    holder = next((x.get("pane_id") for x in c.tui.agents() if x.get("name") == name), None)
    kept = dict(rec, previous=previous)
    if holder and not retire_name(holder, name, ctx=c):
        c.tui.pane_close(new)
        c.store.change_registration(slug, lambda cur: {**(cur or rec), "previous": previous})
        raise Refused(
            f"handover notes saved, but {holder} keeps the name {name} (no free ex-{name} name for it), so no new "
            f"PM was started. Rename or close {holder}, then rotate again."
        )

    def _switch(cur: dict[str, Any] | None) -> dict[str, Any]:
        fresh = dict(cur) if cur is not None else dict(rec)
        fresh["agent_session"] = None
        cur_ep = record_endpoint(fresh)
        next_epoch = int((cur_ep.epoch if cur_ep else 1) or 1) + 1
        ep_dict = {**(cur_ep.to_dict() if cur_ep else {"runtime": "tui", "machine": None}),
                   "workspace": workspace, "terminal": new, "epoch": next_epoch}
        fresh.update({"pane": new, "workspace": workspace, "claimed": c.clock.now(), "previous": previous,
                      "endpoint": ep_dict, "epoch": next_epoch,
                      "rotations": fresh.get("rotations", 0) + 1})
        return fresh

    c.store.change_registration(slug, _switch)
    switched_reg = c.store.registration(slug) or {}
    switched_epoch = int(switched_reg.get("epoch") or 1)
    TurnTracker(c, repo).pm_mailbox.requeue_unconsumed_on_epoch_change(switched_epoch)
    if c.tui.bootstrap_pane_exec(new, shell_join(argv, powershell=True)) is None:
        # Nothing started: the old session stays the PM, under its name.
        c.tui.pane_close(new)
        if holder:
            c.tui.agent_rename(holder, name)
        c.store.change_registration(slug, lambda _cur: kept)
        raise Refused(
            f"handover notes saved, but the new PM could not be started in {new}; {old} stays the PM. Start a "
            f"fresh session by hand (references/hub.md, \"Restart a PM\", without --resume) with this prompt:\n{prompt}"
        )
    record_swap_notice(repo, swap_reason_text(a, ctx=c), by=new, ctx=c)
    # Its own SessionStart hook runs before herdr sees the agent in the pane, too early to give it the name.
    named = name_agent(new, name, ctx=c)
    seen = named and c.tui.agent_wait(name, "--until", "working", "--until", "idle", "--until", "done",
                                      "--until", "blocked", "--timeout", "30000")
    lines = [
        f"new PM session started in {new}; {old} is retired"
        + (": stop acting as PM in this session and tell the user to continue there." if is_self else ".")
    ]
    if not seen:
        lines.append(
            f"check {new}: it may be waiting at a startup dialog (folder trust) that the user has to confirm"
            + ("." if named else f"; once it runs, name it: herdr agent rename {new} {name}")
        )
    return lines


def rotate_herdr(
    a: Any,
    repo: str,
    rec: dict[str, Any],
    previous: dict[str, Any],
    prompt: str,
    is_self: bool,
) -> list[str]:
    """Legacy wrapper for `rotate_herdr` using `Context.from_env()`."""
    return _rotate_herdr_impl(a, repo, rec, previous, prompt, is_self, ctx=Context.from_env())


_DEFAULT_ROTATE_HERDR = rotate_herdr


def retire_name(pane: str, name: str, *, ctx: Context | None = None) -> bool:
    """Rename the agent in pane, a PM that is handing over, so its name is free: ex-<name>, else ex2-<name> and so on
    while earlier retired sessions still hold those (herdr names are unique among live agents, at most 32
    characters). True once renamed."""
    c = Context.from_env() if ctx is None else ctx
    for n in range(1, 10):
        if c.tui.agent_rename(pane, (("ex-" if n == 1 else f"ex{n}-") + name)[:32]):
            return True
    return False


NAME_WAIT = 30  # seconds to wait for herdr to see a new agent in its pane before it can be named
RETIRE_LOOK = 5  # seconds between `end-session` checks


def name_agent(pane: str, name: str, wait: float = NAME_WAIT, *, ctx: Context | None = None) -> bool:
    """Give the agent that is starting in this herdr TUI pane its name, once herdr sees it there (an agent's name is
    cleared when it exits, and a session's SessionStart hook runs before herdr sees it). True when named."""
    c = Context.from_env() if ctx is None else ctx
    deadline = c.clock.time() + wait
    while True:
        if any(x.get("pane_id") == pane for x in c.tui.agents()) and c.tui.agent_rename(pane, name):
            return True
        if c.clock.time() >= deadline:
            return False
        c.clock.sleep(1)


def name_later(pane: str, name: str, *, ctx: Context | None = None) -> None:
    """name_agent from a process of its own (`pm.py name-agent`), so the session-start hook does not wait for it."""
    c = Context.from_env() if ctx is None else ctx
    c.procs.spawn_pm(["name-agent", pane, name])


def takeover_prompt(name: str, handover: str, reason: str = "", *, ctx: Context | None = None) -> str:
    """What a rotated-in PM is told in the desktop app: take over transparently from the ledger."""
    c = Context.from_env() if ctx is None else ctx
    why = f" ({reason})" if reason else ""
    why_zh = f"（原因：{reason}）" if reason else ""
    return c.config.tr(
        f"You are the PM of the {name} project (pm skill), taking over in the PM seat after a session swap{why}. "
        f"Run `{handover}` and take over from what it prints, nothing else. Start no `wait` or `watch`: reports "
        "are delivered to you. A one-line swap notice has already been posted in the project conversation. "
        "If the handover shows something the user said that is not answered yet, answer it as the previous PM "
        "would have (if it points back to earlier talk, run `pm.py conversation --last 40` first). Otherwise "
        "confirm briefly in one or two sentences what is open and what is waiting.",
        f"你是 {name} 项目的 PM（pm skill），因换会话{why_zh}在 PM 座位里接手上一任。"
        f"运行 `{handover}`，只按它给出的内容接手。不要起 `wait` 或 `watch`：汇报会自动送到你这里。"
        "项目对话里已经写了一行换会话说明。"
        "如果交接里显示用户有尚未答复的话，先像上一任那样回答它（如果指代前文，先运行 `pm.py conversation --last 40`）；"
        "否则用一两句话简短说明当前在办与待定的事项即可。")


def successor_env(*, ctx: Context | None = None) -> dict[str, str]:
    """This environment without the outgoing session's own variables, for the PM that takes over."""
    c = Context.from_env() if ctx is None else ctx
    return c.procs.clean_session_env()


def find_pm_session(repo: str | Path, kind: str, *, ctx: Context | None = None) -> dict[str, str] | None:
    """Locate the most recent PM session transcript on disk for `repo` (`claude` or `codex`), or None."""
    c = Context.from_env() if ctx is None else ctx
    resolved = str(Path(repo).resolve())
    if kind == "claude":
        folder = c.agents.claude_projects / claude_folder(resolved)
        candidates_found: list[tuple[float, Path]] = []
        for path in folder.glob("*.jsonl") if folder.is_dir() else ():
            try:
                text = path.read_text(errors="replace")
                if pm_session(text):
                    candidates_found.append((path.stat().st_mtime, path))
            except OSError:
                continue
        if candidates_found:
            best = max(candidates_found, key=lambda x: x[0])[1]
            return {"kind": "claude", "id": best.stem, "path": str(best)}
        return None
    if kind == "codex":
        codex_found: list[tuple[float, str, Path]] = []
        codex_root = c.agents.codex_sessions
        for path in codex_root.rglob("rollout-*.jsonl") if codex_root.is_dir() else ():
            try:
                text = path.read_text(errors="replace")
                meta = (json.loads(text.split("\n", 1)[0]) or {}).get("payload") or {}
                cwd = str(meta.get("cwd") or "")
                if meta.get("id") and cwd == resolved and (pm_session(text) or "handover" in opening(text)):
                    codex_found.append((path.stat().st_mtime, str(meta["id"]), path))
            except (OSError, ValueError, AttributeError):
                continue
        if codex_found:
            _, sid, best = max(codex_found, key=lambda x: x[0])
            return {"kind": "codex", "id": sid, "path": str(best)}
    return None


def build_fallback_spec(
    repo: str,
    failed_spec: Mapping[str, Any],
    reason: str,
    *,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """When a rotated-in PM session fails to start, resume the outgoing session (`claude`/`codex`) or start a fresh
    session from `handover` (`pi`/`agy` or missing transcript), recording a `notice` event in conversation.jsonl."""
    c = Context.from_env() if ctx is None else ctx
    tr = c.config.tr
    name = Path(repo).name
    rec = ProjectRegistry(c).pm_record(repo) or {}
    prev = failed_spec.get("previous") if isinstance(failed_spec.get("previous"), dict) else (
        rec.get("previous") if isinstance(rec.get("previous"), dict) else {})
    prev_sess = prev.get("agent_session") if isinstance(prev.get("agent_session"), dict) else {}
    prev_kind = (prev.get("agent") or prev_sess.get("kind") or rec.get("agent")
                 or failed_spec.get("kind") or "claude")
    sid = str(prev_sess.get("id") or "") if prev_sess.get("kind") in (None, "", prev_kind) else ""
    transcript_path = str(prev_sess.get("path") or prev.get("transcript") or "")
    if not sid and prev_kind == "claude" and transcript_path:
        p = Path(transcript_path)
        if p.suffix == ".jsonl":
            sid = p.stem
    if not sid and prev_kind in ("claude", "codex"):
        found = find_pm_session(repo, prev_kind, ctx=c)
        if found:
            sid, transcript_path = found["id"], found["path"]
    by_pane = f"hc:{c.hc_terminal}" if c.hc_terminal else (rec.get("pane") or "")

    if sid and prev_kind in ("claude", "codex"):
        fallback_prompt = "[from pm.py rotate] " + tr(
            f"The new PM session could not start ({reason}), so your previous session ({sid}) was resumed in the "
            f"PM seat. You are the PM of {name} again; carry on.",
            f"新的 PM 会话没能启动（{reason}），已在 PM 座位里恢复你原来的会话（{sid}）。"
            f"你重新是 {name} 的 PM，接着做。")
        if prev_kind == "claude":
            prev_args = prev.get("args") if isinstance(prev.get("args"), list) else []
            base = successor_argv("claude", prev_args, pm_model("claude", ctx=c), fallback_prompt, ctx=c)
            cut = base.index("--")
            resumed_argv = pm_argv("claude", base[:cut] + ["--resume", sid] + base[cut:], repo, ctx=c)
            send_after = ""
        else:
            resumed_argv = c.agents.resume_argv("codex", sid, pm_model("codex", ctx=c)) or []
            send_after = fallback_prompt
        restored = {"kind": prev_kind, "id": sid, **({"path": transcript_path} if transcript_path else {})}

        def _restore_session(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            if cur is None:
                return None
            cur["agent_session"] = restored
            cur["agent"] = prev_kind
            kept_retired = [s for s in (cur.get("retired_sessions") or []) if s != sid]
            if kept_retired:
                cur["retired_sessions"] = kept_retired
            else:
                cur.pop("retired_sessions", None)
            return cur

        c.store.change_registration(project_slug(repo), _restore_session)
        said = tr(f"The new PM session could not start ({reason}), so the previous {prev_kind} session ({sid}) was "
                  "resumed in the PM seat.",
                  f"新的 PM 会话没能启动（{reason}），已在 PM 座位里恢复原来的 {prev_kind} 会话（{sid}）接着做。")
        Conversation(c, repo).record("pm", text=said, by=by_pane, notice=True)
        return {"argv": resumed_argv, "kind": prev_kind, "prompt": send_after,
                "rotated_in": False, "is_fallback": True}

    handover = f"{c.procs.pm_script()} handover"
    fresh_prompt = "[from pm.py rotate] " + tr(
        f"You are the PM of {name} (pm skill). The rotated-in PM session could not start ({reason}) and no resumable "
        f"{prev_kind} session was available, so a fresh session was started in the PM seat. First run `{handover}` "
        "and take over from what it prints.",
        f"你是 {name} 项目的 PM（pm skill）。刚轮换上来的会话没能启动（{reason}），且原来的 {prev_kind} 会话没法恢复，"
        f"已在 PM 座位里重开新会话。先运行 `{handover}`，按它给出的内容接手。")
    fresh_argv = pm_start_argv(repo, prev_kind, pm_model(prev_kind, ctx=c), fresh_prompt, ctx=c)

    def _clear_session(cur: dict[str, Any] | None) -> dict[str, Any] | None:
        if cur is None:
            return None
        cur["agent_session"] = None
        cur["agent"] = prev_kind
        return cur

    c.store.change_registration(project_slug(repo), _clear_session)
    said = tr(f"The new PM session could not start ({reason}) and no resumable {prev_kind} session was found, so a "
              "fresh PM session was started from handover.",
              f"新的 PM 会话没能启动（{reason}），且没有可恢复的 {prev_kind} 会话，已在 PM 座位里凭 handover 重开新会话。")
    Conversation(c, repo).record("pm", text=said, by=by_pane, notice=True)
    return {"argv": fresh_argv, "kind": prev_kind,
            "prompt": "" if c.agents.takes_prompt(prev_kind) else fresh_prompt,
            "rotated_in": False, "is_fallback": True}


def _end_session_later_impl(
    repo: str,
    term: str,
    agent_pid: int | None = None,
    kill_terminal: bool = False,
    *,
    force: bool = False,
    ctx: Context,
) -> str | None:
    """End the outgoing PM session from a detached background process once its turn and background work finish.
    For an in-seat rotation (`kill_terminal=False`), only the outgoing session's process group (`agent_pid`) ends,
    never the PM's terminal; for the one-time legacy transition (`kill_terminal=True`), the old terminal is killed.
    Returns a warning line if spawning failed, else None."""
    args = ["end-session", term, "--repo", repo]
    if agent_pid:
        args += ["--agent-pid", str(agent_pid)]
    if kill_terminal:
        args.append("--kill-terminal")
    if force:
        args.append("--force")
    cwd = ctx.home.root if ctx.home.root.is_dir() else None
    if ctx.procs.spawn_pm(args, cwd=cwd) is None:
        tr = ctx.config.tr
        if kill_terminal:
            return tr(f"hc:{term} could not be ended for you; end it once it is idle: hc kill {term}",
                      f"没能自动结束 hc:{term}；等它空闲后手动结束：hc kill {term}")
        return tr(f"the outgoing PM session in hc:{term} could not be ended automatically; exit it once idle",
                  f"没能自动结束座位 hc:{term} 里的当前会话；等它空闲后手动退出即可")
    return None


def end_session_later(
    repo: str,
    term: str,
    agent_pid: int | None = None,
    kill_terminal: bool = False,
    *,
    force: bool = False,
) -> str | None:
    """Legacy wrapper for `end_session_later` using `Context.from_env()`."""
    return _end_session_later_impl(repo, term, agent_pid=agent_pid, kill_terminal=kill_terminal, force=force, ctx=Context.from_env())


_DEFAULT_END_SESSION_LATER = end_session_later


def restore_cancelled_rotation(repo: str, terminal: str, *, ctx: Context | None = None) -> None:
    """When `end-session` cancels an in-seat rotation after `timeout`, unlink `next-session.json` and restore
    the staying PM session's `agent_session` (removing its id from `retired_sessions` so hooks and later
    rotations/reattaches can track it again)."""
    c = Context.from_env() if ctx is None else ctx
    nxt_path = c.home.project_for(repo).next_session
    nxt_prev: dict[str, Any] = {}
    try:
        if nxt_path.exists():
            raw = json.loads(nxt_path.read_text())
            if isinstance(raw, dict) and isinstance(raw.get("previous"), dict):
                nxt_prev = raw["previous"]
    except (OSError, ValueError):
        pass
    nxt_path.unlink(missing_ok=True)

    def _restore(cur: dict[str, Any] | None) -> dict[str, Any] | None:
        if cur is None or cur.get("terminal") != terminal:
            return None
        prev = nxt_prev or (cur.get("previous") if isinstance(cur.get("previous"), dict) else {})
        restored = prev.get("agent_session") if isinstance(prev.get("agent_session"), dict) else None
        prev_kind = prev.get("agent") or (restored or {}).get("kind") or cur.get("agent") or "claude"
        transcript = str((restored or {}).get("path") or prev.get("transcript") or "")
        if not restored and prev_kind == "claude" and transcript and Path(transcript).suffix == ".jsonl":
            restored = {"kind": "claude", "id": Path(transcript).stem, "path": transcript}
        if not restored and prev_kind in ("claude", "codex"):
            found = find_pm_session(repo, prev_kind, ctx=c)
            if found:
                restored = {"kind": found["kind"], "id": found["id"], "path": found["path"]}
        sid = (restored or {}).get("id") or ""
        retired_list = [s for s in (cur.get("retired_sessions") or []) if isinstance(s, str)]
        if sid:
            retired_list = [s for s in retired_list if s != sid]
        elif retired_list and cur.get("agent_session") is None:
            retired_list = retired_list[:-1]
        if retired_list:
            cur["retired_sessions"] = retired_list
        else:
            cur.pop("retired_sessions", None)
        if isinstance(restored, dict) and cur.get("agent_session") is None:
            cur["agent_session"] = restored
        return cur

    c.store.change_registration(project_slug(repo), _restore)


_DEFAULT_BACKGROUND_WORK = background_work


def still_running(old: str, work: list[str], *, ctx: Context | None = None) -> None:
    """A legacy retired PM terminal still works after RETIRE_WAIT: it is left running, and the PM now in charge is
    told, so the work is not cut off and the session is not forgotten."""
    c = Context.from_env() if ctx is None else ctx
    rec = next((r for r in ProjectRegistry(c).pm_records() if (r.get("previous") or {}).get("terminal") == old), None)
    if not rec or not rec.get("terminal"):
        return
    tr = c.config.tr
    what = "; ".join(work) or tr("its turn", "它这一轮")
    msg = "[from pm.py end-session] " + tr(
        f"The previous PM session hc:{old} still runs ({what}) {RETIRE_WAIT // 60} min after the rotation, so it was "
        f"not ended. Once that is done, end it: `hc kill {old}`.",
        f"上一任 PM 会话 hc:{old} 轮换 {RETIRE_WAIT // 60} 分钟后还在跑（{what}），所以没有关掉它。"
        f"那些活做完后再关：`hc kill {old}`。",
    )
    ep = record_endpoint(rec) or parse_legacy_endpoint(str(rec["terminal"]), runtime_hint="hc")
    if ep is None:
        return
    now_ms = int(float(c.clock.time()) * 1000)
    proj_slug = project_slug(rec.get("repo") or rec.get("name") or "project")
    env = Envelope(
        env_id=new_env_id(now_ms),
        idempotency_key="",
        schema_version=1,
        created_ms=now_ms,
        kind="event.notify",
        sender=Principal.supervisor(proj_slug),
        recipient=LogicalAddress.pm(proj_slug),
        project=proj_slug,
        cause={"kind": "end_session_still_running", "old_terminal": old},
        priority=P4_BATCH,
        body={"text": msg},
    )
    repo = str(rec.get("repo") or "")
    deliver_under_typist_lock(c, ep, env, repo=repo, if_idle=False)
