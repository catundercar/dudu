"""The codex side of starting a worker: the provider settings (codex.args, model_prefix), which codex profile a command
line runs on, the PM's args without what a profile sets, the fallback when every profile is full, and reading codex's
status line for fast. Layer 1.

The pool itself (codex_pool, the per-project count and its lock, apply_codex_pool) is workers/codex_pool.py: which
projects a pool covers is decided from the managers' registrations (project_names), which are layer 2."""
import re

from ..config import config
from ..terminals.screen import screen_of
from .base import codex_settings, strip_codex_args
from .profiles import PROFILES, review_models


# A PM's registration (pms/<project>.json) may carry {"codex": {"args": ["-c", "model_provider=\"<name>\"", ...],
# "model_prefix": "<prefix>/"}}; config.json's "codex" block is the default for PMs without one. `dispatch`, `review`
# and `escalate` start codex workers with them too.


def codex_args(model, effort, rec=None, *, cfg=None):
    """codex CLI arguments: the provider settings of PM rec (else config.json), then model and effort."""
    if cfg is not None:
        rec_codex = rec.get("codex") if isinstance(rec, dict) else None
        settings = rec_codex if isinstance(rec_codex, dict) else (cfg if isinstance(cfg, dict) else {})
    else:
        settings = codex_settings(rec)
    prefix = settings.get("model_prefix", "")
    if prefix and not model.startswith(prefix):
        model = prefix + model
    return [*settings.get("args", []), "-m", model, "-c", f'model_reasoning_effort="{effort}"']


def codex_cfg():
    cfg = config().get("codex")
    return cfg if isinstance(cfg, dict) else {}


def codex_profile_of(argv):
    """The codex profile a command line runs on: -p/--profile, else its -c model_provider=, else "default"."""
    for i, x in enumerate(argv):
        if x in ("-p", "--profile") and i + 1 < len(argv):
            return argv[i + 1]
        if x.startswith("--profile="):
            return x.split("=", 1)[1]
    for x in argv:
        found = re.search(r'model_provider\s*=\s*"?([^"\s]+)"?', x)
        if found:
            return found.group(1)
    return "default"


def claude_defaults(a):
    """config.json claude.effort: a Claude worker's or reviewer's effort when nothing else names one."""
    if a.kind == "claude" and not a.effort:
        a.effort = (config().get("claude") or {}).get("effort") or ""


def pool_fallback(role):
    """What a worker runs on instead when every codex profile is full: config.json codex.fallback.<role>, else
    the built-in standard profile (Claude Opus) for a worker, and for a reviewer the review table's standard entry
    (Fable; Sonnet with "fable": false)."""
    entry = (codex_cfg().get("fallback") or {}).get(role)
    if isinstance(entry, dict) and (entry.get("kind") or entry.get("model")):
        return {"kind": "claude", **entry}
    if role == "reviewer":
        table = review_models().get("standard")
        return {"kind": "claude", **(table if isinstance(table, dict) else {"model": table})}
    return dict(PROFILES["standard"])


CODEX_STATUS = re.compile(r"·\s*Context\b")  # codex's status line: "<model> high fast · Context 21% used · …"


def codex_status_line(term):
    lines = [s.strip() for s in screen_of(term).splitlines() if CODEX_STATUS.search(s)]
    return lines[-1] if lines else ""


def shows_fast(line):
    """The status line says fast (the service tier, before the first "·"); ultrafast is not fast."""
    return bool(re.search(r"(?<![a-z])fast\b", line.split("·")[0], re.I))
