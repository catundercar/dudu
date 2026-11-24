"""Reading what a terminal shows: startup prompts (trust a folder, update the program) and how to answer them, and
what a stuck screen means (quota, login, a permission or hook prompt)."""
import re

from ..osutil import clip
from . import hc as hc_mod


def screen_of(term, *, host=None):
    if host is not None:
        return host.read(term)
    return (hc_mod.hc("read", term) or {}).get("text") or ""


# How Claude Code, codex, agy and other coding agents ask whether to trust a folder/workspace.
TRUST_ASKS = (
    "trust this folder",
    "trust the files in this folder",
    "trust the contents of this directory",
    "allow codex to work in this folder",
    "trust this directory",
    "trust this workspace",
    "trust the workspace",
    "do you trust",
    "trust folder",
    "workspace trust",
)
_CLAUDE_SAFETY_ASK = ("quick safety check", "project you created or one you trust")
OPTION = r"\s*(?:([❯›>▸▶●•*])\s*)?(?:\d+\.\s*)?(Yes|No|Trust|Don't trust|Do not trust|Allow|Deny|Decline|Cancel|Exit)\b"
_TRUST_OPTION_RE = re.compile(OPTION, re.I)
_TRUST_POSITIVE = ("yes", "trust", "allow")
_TRUST_NEGATIVE = ("no", "don't trust", "do not trust", "deny", "decline", "cancel", "exit")
_INLINE_YN = re.compile(r"\[(?:y/n|Y/n|y/N)\]|\((?:y/n|Y/n|y/N)\)")

UPDATE_ASKS = (
    "update available",
    "new version available",
    "upgrade available",
    "a new version",
    "new release available",
    "update cli",
    "upgrade codex",
    "upgrade claude",
    "upgrade agy",
)
_UPDATE_OPTION = re.compile(
    r"\s*(?:([❯›>▸▶●•*])\s*)?(?:\d+\.\s*)?"
    r"(?!(?:Update|Upgrade)\s+available\b)"
    r"(Update|Upgrade|Install|Yes|Skip|Not now|Later|Remind me later|Dismiss|Continue without|No)\b",
    re.I,
)
_UPDATE_ACCEPT = ("update", "upgrade", "install", "yes")
_UPDATE_SKIP = ("skip", "not now", "later", "remind me later", "dismiss", "continue without", "no")

# Any dialog mentioning commands, tools, destructive operations, permissions, MCP or hooks must NEVER be auto-answered.
_FORBIDDEN_AUTO_DIALOG_RE = re.compile(
    r"(\brm\s+-[a-z]*[rf]|\bsudo\b|\bchmod\b|\bchown\b|\bgit\s+(?:push|reset|clean)\b|\bdd\s+if=|\bmkfs\b|"
    r"\bdelete\b|\bremove\s+all\b|\berase\b|\bdrop\s+table\b|\boverwrite\b|"
    r"\bdo you want to (?:run|execute|proceed|allow|delete|remove|edit|write|create|apply|make this edit)\b|"
    r"\b(?:run|execute)\s+(?:this\s+)?(?:command|bash|shell|script|tool)\b|"
    r"\b(?:allow|approve)\s+(?:this\s+)?(?:command|tool|bash|edit|write|mcp|hook|once)\b|"
    r"\b(?:bash|shell)\s+command\b|\btool\s+(?:call|use|permission|approval)\b|\bcommand\s+confirmation\b|"
    r"\bnew mcp server\b|\bmcp server\b|\bhook[s]?\s+needs?\s+review\b|\bpermission\s+required\b)",
    re.I,
)
_BOX_BORDER_RE = re.compile(r"^[\s─━═│╭╮╰╯┌┐└┘├┤┬┴┼·•\-_=]+$")


def _active_viewport_lines(screen, max_lines=24):
    """Return only the bottom active viewport lines (never ancient scrollback history)."""
    lines = (screen or "").splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    return lines[-max_lines:]


def _extract_tail_options(lines, opt_re):
    """Find a single contiguous cursor-selectable option block at the bottom of the active viewport.
    Returns (header_lines, option_lines, matches) or None when no active bottom option dialog exists."""
    non_empty_idx = [i for i, ln in enumerate(lines) if ln.strip() and not _BOX_BORDER_RE.match(ln)]
    if not non_empty_idx:
        return None
    # The option block must end near the bottom (allowing at most 3 footer/hint lines such as "Enter to confirm").
    tail_candidates = non_empty_idx[-5:]
    end_idx = None
    for idx in reversed(tail_candidates):
        if opt_re.match(lines[idx]):
            end_idx = idx
            break
    if end_idx is None:
        return None
    opt_indices = [end_idx]
    blanks = 0
    i = end_idx - 1
    while i >= 0:
        ln = lines[i]
        if not ln.strip():
            blanks += 1
            if blanks > 1:
                break
            i -= 1
            continue
        if opt_re.match(ln):
            opt_indices.append(i)
            blanks = 0
            i -= 1
            continue
        break
    opt_indices.reverse()
    matches = [opt_re.match(lines[idx]) for idx in opt_indices]
    if not (2 <= len(matches) <= 4):
        return None
    cursor = [k for k, m in enumerate(matches) if m.group(1)]
    if len(cursor) != 1:
        return None
    # Collect up to 8 immediately preceding non-empty header lines directly above the option block.
    start_idx = opt_indices[0]
    header = []
    j = start_idx - 1
    while j >= 0 and len(header) < 8:
        ln = lines[j]
        if ln.strip() and not _BOX_BORDER_RE.match(ln):
            header.append(ln)
        j -= 1
    header.reverse()
    option_lines = [lines[idx] for idx in opt_indices]
    return header, option_lines, matches


def trust_keys(screen):
    """The keys that move a folder-trust dialog's cursor to its Yes/Trust option and confirm it, or None when the
    active bottom dialog is not a verified folder-trust prompt. Inspects only the active bottom dialog (never
    scrollback history) and strictly refuses any command/tool/permission confirmation dialog."""
    lines = _active_viewport_lines(screen)
    if not lines:
        return None
    extracted = _extract_tail_options(lines, _TRUST_OPTION_RE)
    if extracted:
        header_lines, option_lines, matches = extracted
        header_low = "\n".join(header_lines).lower()
        opt_low = "\n".join(option_lines).lower()
        dialog_text = "\n".join(header_lines + option_lines)
        if _FORBIDDEN_AUTO_DIALOG_RE.search(dialog_text):
            return None
        header_has_trust = any(ask in header_low for ask in TRUST_ASKS)
        claude_safety = any(ask in header_low for ask in _CLAUDE_SAFETY_ASK) and any(ask in opt_low for ask in TRUST_ASKS)
        if not (header_has_trust or claude_safety):
            return None
        cursor = [i for i, m in enumerate(matches) if m.group(1)]
        yes = [i for i, m in enumerate(matches) if m.group(2).lower() in _TRUST_POSITIVE]
        no = [i for i, m in enumerate(matches) if m.group(2).lower() in _TRUST_NEGATIVE]
        if len(cursor) == 1 and len(yes) == 1 and len(no) >= 1:
            step = yes[0] - cursor[0]
            return ["down"] * step + ["up"] * -step + ["enter"]
        return None
    # Inline [y/N] trust prompt: trust phrase must appear on the very last non-empty line (or the line right above it).
    non_empty = [ln for ln in lines if ln.strip() and not _BOX_BORDER_RE.match(ln)]
    if not non_empty:
        return None
    last_line = non_empty[-1]
    if _INLINE_YN.search(last_line):
        inline_text = "\n".join(non_empty[-2:])
        if _FORBIDDEN_AUTO_DIALOG_RE.search(inline_text):
            return None
        if any(ask in inline_text.lower() for ask in TRUST_ASKS):
            return ["y", "enter"]
    return None


def update_keys(screen):
    """The keys that dismiss/skip an active CLI update/upgrade prompt safely without upgrading mid-task, else None.
    Inspects only the active bottom dialog (never scrollback history) and never triggers on command/permission prompts."""
    lines = _active_viewport_lines(screen)
    if not lines:
        return None
    extracted = _extract_tail_options(lines, _UPDATE_OPTION)
    if extracted:
        header_lines, option_lines, matches = extracted
        header_low = "\n".join(header_lines).lower()
        dialog_text = "\n".join(header_lines + option_lines)
        if _FORBIDDEN_AUTO_DIALOG_RE.search(dialog_text):
            return None
        if not any(ask in header_low for ask in UPDATE_ASKS):
            return None
        cursor = [i for i, m in enumerate(matches) if m.group(1)]
        accept = [i for i, m in enumerate(matches) if m.group(2).lower() in _UPDATE_ACCEPT]
        skip = [i for i, m in enumerate(matches) if m.group(2).lower() in _UPDATE_SKIP]
        if len(cursor) == 1 and accept and skip:
            step = skip[0] - cursor[0]
            return ["down"] * step + ["up"] * -step + ["enter"]
        return None
    non_empty = [ln for ln in lines if ln.strip() and not _BOX_BORDER_RE.match(ln)]
    if not non_empty:
        return None
    last_line = non_empty[-1]
    if _INLINE_YN.search(last_line):
        inline_text = "\n".join(non_empty[-2:])
        if _FORBIDDEN_AUTO_DIALOG_RE.search(inline_text):
            return None
        if any(ask in inline_text.lower() for ask in UPDATE_ASKS):
            return ["n", "enter"]
    tail_block = "\n".join(non_empty[-8:])
    tail_low = tail_block.lower()
    if (not _FORBIDDEN_AUTO_DIALOG_RE.search(tail_block)
            and any(ask in tail_low for ask in UPDATE_ASKS)
            and ("press esc" in tail_low or "esc to dismiss" in tail_low or "esc to skip" in tail_low)):
        return ["escape"]
    return None


def known_prompt_action(screen, *, allow_trust=False):
    """Return (kind, keys) for a known safe prompt that the harness can auto-handle, else (None, None)."""
    if not screen:
        return None, None
    uk = update_keys(screen)
    if uk:
        return "update", uk
    if allow_trust:
        tk = trust_keys(screen)
        if tk:
            return "trust", tk
    return None, None


_QUOTA_RE = re.compile(
    r"(rate.?limit|quota.?exceeded|insufficient_quota|usage.?limit|hit your limit|too many requests|"
    r"\b429\b|credits? exhausted|out of credits|billing limit|overloaded_error|capacity exceeded|配额|限流)",
    re.I,
)
_AUTH_RE = re.compile(
    r"(not logged in|please log ?in|authentication failed|invalid api key|unauthorized|\b401\b|"
    r"token expired|sign in to continue|login required|未登录|鉴权失败)",
    re.I,
)
_HOOK_REVIEW_RE = re.compile(r"hook[s]?\s+needs?\s+review|review\s+hook", re.I)
_MCP_RE = re.compile(r"new mcp server|use this mcp server|approve mcp", re.I)
_PERM_RE = re.compile(
    r"(\bdo you want to (?:proceed|run|allow|execute|create|edit|delete|remove|apply)\b|"
    r"\b(?:allow|approve)\s+(?:this\s+)?(?:command|tool|bash|edit|write|once)\b|"
    r"\b(?:run|execute)\s+(?:this\s+)?(?:command|bash|shell)\b|"
    r"\bpermission\s+required\b|\brequires?\s+(?:your\s+)?(?:approval|permission)\b)",
    re.I,
)


def _clean_screen_excerpt(screen, width=160):
    lines = [s.strip() for s in _active_viewport_lines(screen) if s.strip().strip("─━│╭╮╰╯ ")]
    return clip(" / ".join(lines[-3:] if len(lines) > 3 else lines), width) if lines else ""


def classify_stuck_screen(screen):
    """Classify the active bottom viewport into a structured conclusion {kind, summary} for the PM (no raw dump)."""
    tail_lines = _active_viewport_lines(screen)
    text = "\n".join(tail_lines)
    low = text.lower()
    summary = _clean_screen_excerpt(text, width=160)
    if _QUOTA_RE.search(text):
        hit = next((ln.strip() for ln in reversed(tail_lines) if _QUOTA_RE.search(ln)), summary)
        return {"kind": "quota", "summary": clip(hit, 160)}
    if _AUTH_RE.search(text):
        hit = next((ln.strip() for ln in reversed(tail_lines) if _AUTH_RE.search(ln)), summary)
        return {"kind": "auth", "summary": clip(hit, 160)}
    if _HOOK_REVIEW_RE.search(text):
        return {"kind": "hook_review", "summary": summary}
    if _MCP_RE.search(text):
        return {"kind": "mcp", "summary": summary}
    if _PERM_RE.search(text):
        return {"kind": "permission", "summary": summary}
    # Trust / update detection in classification also checks the active bottom lines (last 10 non-empty).
    non_empty = [ln for ln in tail_lines if ln.strip() and not _BOX_BORDER_RE.match(ln)]
    active_tail = "\n".join(non_empty[-10:]).lower()
    if any(ask in active_tail for ask in TRUST_ASKS):
        return {"kind": "trust", "summary": summary}
    if any(ask in active_tail for ask in UPDATE_ASKS):
        return {"kind": "update", "summary": summary}
    return {"kind": "unknown", "summary": summary}


def screen_line(term, width=160, *, host=None):
    """What a terminal shows, as one line for the task log."""
    raw = host.read(term) if host is not None else screen_of(term)
    lines = [s.strip() for s in raw.splitlines() if s.strip().strip("─━│╭╮╰╯ ")]
    return clip(" / ".join(lines[:3]), width) or "(empty screen)"
