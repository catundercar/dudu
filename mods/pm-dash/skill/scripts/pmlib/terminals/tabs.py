"""Desktop tab names: what a worker's or a PM's tab is called, and renaming a tab (through herdr-app, or in the app's
document in herdr-core). Layer 1."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
from typing import Any

from .. import config as config_mod, context
from . import hc as hc_mod


def doc_tabs(value: Any):
    """(tab, its terminals) for every tab in the app's document ("herdr-app": spaces, tabs, a tree of blocks)."""
    return hc_mod._doc_tabs(value)


def pm_tab_name(repo: str | Path, display_name: str | None = None) -> str:
    label = str(display_name or "").strip() or Path(repo).name
    return f"PM-{label}"


def _legacy_hc_host(*, with_rename_hook: bool = False) -> hc_mod.HcHost:
    return hc_mod.HcHost(
        config_port=lambda: config_mod.config(),
        runner=lambda *a, **kw: hc_mod.hc(*a, **kw),
        rpc_runner=lambda m, p: hc_mod.hc_rpc(m, p),
        rename_tab_fn=rename_tab if with_rename_hook else None,
    )


def name_tab(terminal: str, name: str, only_if: str | None = None, wait: float = 0) -> bool:
    """Rename the desktop tab that shows terminal; an empty name gives the tab its number back.
    With only_if, only a tab now called that. No app, or no tab (a bare or sub-agent terminal): nothing happens.
    wait: seconds to wait for a tab the app is still making. Where herdr-app is not installed (herdr-core on a
    machine the app reaches over ssh) nothing is renamed, unless config.json tabs.rename_via_core says to rename it
    in the app's document in herdr-core (rename_tab). True when the tab was renamed."""
    return _legacy_hc_host(with_rename_hook=True).name_tab(terminal, name, only_if=only_if, wait=wait)


def rename_tab(terminal: str, name: str, wait: float = 15, only_if: str | None = None) -> bool:
    """Name the desktop tab that shows terminal in the app's document, which the app keeps in herdr-core (doc
    "herdr-app"); for a machine without herdr-app, and only with config.json tabs.rename_via_core. The whole
    document is read and written back: herdr-core's doc protocol is not in Herdr's documented API, so it is off by
    default. A tab the app is still making (a terminal just labelled herdr.tab=…) is waited for up to `wait`
    seconds; a write that loses to another one (the version moved on) is tried again. True once named."""
    return _legacy_hc_host().rename_tab(terminal, name, wait=wait, only_if=only_if)


TERM_HEAD = re.compile(r"^(t(?=[0-9a-z]*[0-9])[0-9a-z]{1,4})-")  # a herdr-core address heading a tab: "t5g-"
DRY_TERM = "t?"  # --dry-run: the address is known only once the terminal is made


def _read_cfg_dict(cfg: Any) -> dict[str, Any]:
    if cfg is None:
        return config_mod.config()
    read = getattr(cfg, "read", None)
    if callable(read):
        data = read()
        return data if isinstance(data, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def tabs_cfg(cfg: Any = None) -> dict[str, Any]:
    data = _read_cfg_dict(cfg).get("tabs")
    return data if isinstance(data, dict) else {}


def new_tabs(*, cfg: Any = None, pane: str | None = None) -> bool:
    """Each worker gets a desktop tab of its own, named <terminal>-<BUG>-<short> like its ledger agent
    (config.json tabs.new_tab). Off by default: a worker is a sub-agent row under its PM's terminal."""
    caller_pane = pane or ""
    return tabs_cfg(cfg).get("new_tab") is True and caller_pane.startswith("hc:")


def bug_of(bug: str = "", *texts: Any, cfg: Any = None) -> str:
    """The BUG number a worker's tab shows: --bug as given, else what config.json tabs.bug_pattern (a regular
    expression; its first group, else the whole match) finds first in texts (--tab, then the task's title). ""
    when there is none."""
    if str(bug or "").strip():
        return str(bug).strip().lstrip("#")
    pattern = tabs_cfg(cfg).get("bug_pattern")
    if not pattern:
        return ""
    try:
        found = re.compile(str(pattern))
    except re.error:
        return ""
    for text in texts:
        m = found.search(str(text or ""))
        if m:
            return (m.group(1) if m.groups() else m.group(0)).lstrip("#")
    return ""


def task_bug(task: dict[str, Any], *, cfg: Any = None) -> str:
    """The BUG number a task's tabs carry: the one dispatch recorded, else from its tab or title."""
    return task.get("bug") or bug_of("", task.get("tab"), task.get("title"), cfg=cfg)


def tab_short(text: Any, bug: str = "") -> str:
    """A tab's short name as the ledger keeps it (`tab`): no spaces, no terminal address ahead of it, and without
    bug, the BUG number the tab shows on its own (tab_title puts it back after the address)."""
    text = re.sub(r"\s+", "", str(text or ""))
    text = text[TERM_HEAD.match(text).end():] if TERM_HEAD.match(text) else text
    if bug:
        text = re.sub(r"-{2,}", "-", re.sub(rf"#?(?<![0-9]){re.escape(bug)}(?![0-9])", "", text)).strip("-_#:：")
    return text


def tab_title(short: Any, bug: str = "", term: str = "", dry: bool = False, *, cfg: Any = None) -> str:
    """The worker's tab, which is also its ledger `agent`: "<terminal>-<BUG>-<short>" ("t5g-12345-login-fix"),
    "<terminal>-<short>" without a BUG number ("t5m-review-login-fix"). term: the herdr-core address ("t5g"), known
    once the terminal is made; a short that starts with an address already ("t5g-…") gets term in its place, not a
    second one (with no term it keeps its own; dry: "t?" stands for the address to come). The BUG number is taken
    out of short and put after the address. short is clipped to tabs.max characters (default 20)."""
    size = int(tabs_cfg(cfg).get("max") or 20)
    short = re.sub(r"\s+", "", str(short or ""))
    given = TERM_HEAD.match(short)
    if given:
        short = short[given.end():]
    head = term or (given.group(1) if given else "") or (DRY_TERM if dry else "")
    short = tab_short(short, bug)[:size].rstrip("-")
    return "-".join(x for x in (head, bug, short or ("" if bug else "worker")) if x)


def hc_name(text: Any, size: int = 32) -> str:
    """A herdr-core terminal name from text: 1-32 of a-z 0-9 - _ ("t5g-12345-登录" keeps "t5g-12345")."""
    return re.sub(r"[^a-z0-9_-]+", "-", str(text or "").lower()).strip("-")[:size].strip("-") or "worker"


def not_renamed(*, cfg: Any = None) -> str:
    """Said in the task log when a worker's tab kept the app's name: no herdr-app on this machine (the app runs on
    another one and reaches this herdr-core over ssh), or no tab with that terminal was found."""
    translate = cfg.tr if (cfg is not None and callable(getattr(cfg, "tr", None))) else config_mod.tr
    if not shutil.which("herdr-app") and tabs_cfg(cfg).get("rename_via_core") is not True:
        return translate(
            " (not renamed: herdr-app is not installed here; tabs.rename_via_core renames through herdr-core)",
            "（未改名：这台机器没装 herdr-app；要经 herdr-core 改名就打开 tabs.rename_via_core）",
        )
    return translate(" (not renamed: no tab found)", "（未改名：没找到标签页）")


def worker_tab(made: str, task_id: str, name: str, parent: str = "", *, pane: str = "") -> bool:
    """Label a new worker terminal (task=<id>, and parent= / category= its parent task) and, with tabs.new_tab, give
    it a tab of its own in this PM's space named `name` (otherwise it stays a sub-agent row under the PM). The app
    makes the tab when it sees herdr.tab=<new id>; it is renamed once it is there. True when the tab got its name."""
    caller_pane = pane
    labels = [f"task={task_id}"] + ([f"parent={parent}", f"category={parent}"] if parent else [])
    space = ""
    if new_tabs(pane=caller_pane):
        space = ((hc_mod.hc("get", caller_pane[3:]) or {}).get("labels") or {}).get("herdr.space") or ""
        if space:
            labels += [f"herdr.space={space}", f"herdr.tab=tb{os.urandom(16).hex()}"]
    hc_mod.hc("label", made, *labels)
    return bool(space and name) and name_tab(made, name, wait=15)
