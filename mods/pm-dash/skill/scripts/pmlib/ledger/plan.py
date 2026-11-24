"""Two-layer plans (--plan/--step): parsing, anchor inference, progress, and status-driven transitions. Layer 2."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from ..config import config

PLAN_STATES = ("todo", "doing", "done")
PLAN_ANCHORS = ("work", "review", "merge", "custom")
AUTO_REVIEW_MAX_ROUNDS = 2


@dataclass(frozen=True)
class PlanInput:
    """Typed plan update payload replacing raw CLI plan flags."""

    outer_steps: list[dict[str, Any]] | None = None
    outer_explicit_states: bool = False
    sub_steps: list[dict[str, Any]] | None = None

_EXPLICIT_ANCHOR_RE = re.compile(r"(?i)(?:^|\s)@(work|review|merge|custom|none)(?=\s|$)")
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_STATE_PREFIX_RE = re.compile(r"^\s*(?:\[(?P<box>[xX>\*\s])\]|(?P<glyph>[✓✔◌○]))\s*")

_NEG_REVIEW_RE = re.compile(
    r"(?:免|不|无需|不用|不做|跳过|无)(?:代码)?(?:审查|评审|复审|review)"
    r"|\b(?:no|without|skip(?:ping)?)\s+(?:code\s+)?reviews?\b",
    re.I,
)
_USER_SIGNOFF_RE = re.compile(
    r"(?:等你|用户|待你)(?:审查|审阅|确认|验收)|(?:和|与|给)用户"
    r"|\b(?:your|user|human)\s+(?:review|sign-?off|approval|check)\b"
    r"|\bwith\s+(?:the\s+)?(?:user|you|human)\b",
    re.I,
)
_REVIEW_HEAD_RE = re.compile(
    r"^\s*(?:(?:独立\s*)?(?:代码\s*)?(?:审查|复审|评审)|送审"
    r"|(?:independent\s+)?(?:code\s+)?(?:re-?)?review(?:ing)?(?![a-z]))",
    re.I,
)
_NEG_MERGE_RE = re.compile(
    r"(?:不|无需|不用|暂不|先不|免)(?:合入|合并|合进|合到|合\s*(?:main|master|主分支|主线)|land)"
    r"|\b(?:no|without|don'?t|do\s+not|not|skip(?:ping)?)\s+(?:code\s+)?(?:merge|land)(?:ing)?\b",
    re.I,
)
_MERGE_ANCHOR_RE = re.compile(
    r"合进|合入|合到|合\s*(?:main|master|主分支|主线)"
    r"|合并(?:进|入|到|\s*(?:main|master|主分支|主线|分支)|$)"
    r"|(?<![a-z])(?:pm\.py\s+)?land(?:\s+(?:to|into|on|in|branch|main|master)\b|\s*$)"
    r"|(?<![a-z])merge(?:\s+(?:to|into|with|branch|main|master|pr)\b|\s*$)",
    re.I,
)
_CORE_WORK_RE = re.compile(
    r"实现|开发|编码|修复|重构|调研|设计|翻译"
    r"|\b(?:implement\w*|develop\w*|refactor\w*|research\w*|design\w*|translat\w*)\b",
    re.I,
)
_CUSTOM_POST_RE = re.compile(
    r"安装|装到|部署|发布|挂分支|待验收|等你|审阅"
    r"|\b(?:install\w*|deploy\w*|release\w*|hold\w*|await\w*|sign-?off)\b",
    re.I,
)
_WORK_ANCHOR_RE = re.compile(
    r"实现|开发|编写|编码|修复|改造|重构|调研|设计|出稿|交互稿|翻译|译为|修改|改动|调整|补充|补齐|盘点|迁移|优化|执行任务"
    r"|\b(?:implement\w*|develop\w*|build\w*|code|coding|fix\w*|refactor\w*|research\w*|design\w*|translat\w*"
    r"|modif\w*|updat\w*|migrat\w*|optimi[sz]\w*|patch\w*|writ(?:e|ing)|draft\w*)\b",
    re.I,
)


def auto_review_max_rounds(cfg: Any = None) -> int:
    """Maximum auto-review rounds before handing straight to the PM (`config.json auto_review.max_rounds`)."""
    if cfg is None:
        data = config()
    elif hasattr(cfg, "read"):
        data = cfg.read()
    else:
        data = cfg
    raw = (data.get("auto_review") or {}).get("max_rounds") if isinstance(data.get("auto_review"), dict) else None
    if raw is None:
        raw = data.get("review_max_rounds")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    return AUTO_REVIEW_MAX_ROUNDS


def infer_anchor(text):
    """Infer lightweight lifecycle anchor ('work', 'review', 'merge', or 'custom') from step text.

    Without an explicit @tag, 'review' matches only when the whole step starts as a review phrase
    (审查/复审/review/re-review) with no other work/merge verbs, negations, or user sign-off phrases.
    """
    raw = str(text or "").strip()
    if not raw:
        return "custom"
    m = _REVIEW_HEAD_RE.match(raw)
    if m and not _NEG_REVIEW_RE.search(raw) and not _USER_SIGNOFF_RE.search(raw):
        tail = raw[m.end():]
        if not _WORK_ANCHOR_RE.search(tail) and not _MERGE_ANCHOR_RE.search(_NEG_MERGE_RE.sub(" ", tail)):
            return "review"
    merge_clean = _NEG_MERGE_RE.sub(" ", raw)
    if _MERGE_ANCHOR_RE.search(merge_clean):
        return "merge"
    if _CUSTOM_POST_RE.search(raw) and not _CORE_WORK_RE.search(raw):
        return "custom"
    if _WORK_ANCHOR_RE.search(raw):
        return "work"
    return "custom"


def step_anchor(step):
    """Return the stored anchor ('work', 'review', 'merge', or 'custom') of a plan step.

    Object steps without an explicit/valid anchor default to 'custom' (matching model.js) without re-inferring.
    """
    if not isinstance(step, dict):
        return "custom"
    val = str(step.get("anchor") or "").strip().lower()
    return val if val in PLAN_ANCHORS else "custom"


def _split_plan_items(plan_vals, step_vals):
    items = []
    if plan_vals is not None:
        vals = [plan_vals] if isinstance(plan_vals, str) else list(plan_vals)
        for v in vals:
            for part in re.split(r"[;；\n]+", str(v)):
                if part.strip():
                    items.append(part.strip())
    if step_vals is not None:
        vals = [step_vals] if isinstance(step_vals, str) else list(step_vals)
        for v in vals:
            if str(v).strip():
                items.append(str(v).strip())
    return items


def parse_plan_steps(plan_vals=None, step_vals=None, *, outer=True):
    """Parse --plan / --step strings into normalized [{'text', 'state', ...}] step dicts.

    Returns (steps, has_explicit_state). When outer=True, parses optional @work/@review/@merge/@custom/@none
    tags and infers missing anchors.
    """
    items = _split_plan_items(plan_vals, step_vals)
    steps, has_explicit = [], False
    for raw in items:
        s = _BULLET_PREFIX_RE.sub("", raw).strip()
        state, explicit_here = "todo", False
        m = _STATE_PREFIX_RE.match(s)
        if m:
            explicit_here = True
            has_explicit = True
            tok = m.group("box") or m.group("glyph") or ""
            if tok in ("x", "X", "✓", "✔"):
                state = "done"
            elif tok in (">", "*", "◌"):
                state = "doing"
            else:
                state = "todo"
            s = s[m.end():].strip()
        explicit_anchor = ""
        if outer:
            def _take_anchor(match):
                nonlocal explicit_anchor
                explicit_anchor = match.group(1).lower()
                return " "
            s = " ".join(_EXPLICIT_ANCHOR_RE.sub(_take_anchor, s).split())
            if not s and explicit_anchor:
                s = {"work": "Work", "review": "Review", "merge": "Merge", "custom": "Step"}.get(explicit_anchor, "")
        if not s:
            continue
        entry = {"text": s, "state": state}
        if outer:
            if explicit_anchor in ("none", "custom"):
                entry["anchor"] = "custom"
            elif explicit_anchor in ("work", "review", "merge"):
                entry["anchor"] = explicit_anchor
            else:
                entry["anchor"] = infer_anchor(s)
        steps.append(entry)
    return steps, has_explicit


def has_pending_review_step(task):
    """True when task['plan'] includes an unfinished review step."""
    plan = task.get("plan") if isinstance(task, Mapping) else None
    return isinstance(plan, list) and any(
        isinstance(s, dict) and step_anchor(s) == "review" and s.get("state") != "done"
        for s in plan
    )


def has_unfinished_plan(task):
    """True when task['plan'] exists and still has steps not marked done."""
    plan = task.get("plan") if isinstance(task, Mapping) else None
    return isinstance(plan, list) and any(
        isinstance(s, dict) and s.get("state") != "done" for s in plan
    )


def plan_progress(steps):
    """Return (done_count, total_count, current_step_text) for a plan or subplan list."""
    if not isinstance(steps, list) or not steps:
        return 0, 0, ""
    valid = [s for s in steps if isinstance(s, dict)]
    done = sum(1 for s in valid if s.get("state") == "done")
    active = next((s.get("text") or "" for s in valid if s.get("state") == "doing"), "")
    if not active:
        active = next((s.get("text") or "" for s in valid if s.get("state") != "done"), "")
    return done, len(valid), active


def close_doing_subplan(task):
    """Mark any 'doing' inner subplan steps as 'done' when the work step completes or transitions."""
    sub = task.get("subplan")
    if isinstance(sub, list):
        for s in sub:
            if isinstance(s, dict) and s.get("state") == "doing":
                s["state"] = "done"


def activate_first_todo(plan):
    """If no outer step is currently 'doing', mark the first 'todo' work/custom step (else first 'todo') 'doing'."""
    if not isinstance(plan, list) or any(isinstance(s, dict) and s.get("state") == "doing" for s in plan):
        return
    for s in plan:
        if isinstance(s, dict) and s.get("state") == "todo" and step_anchor(s) not in ("review", "merge"):
            s["state"] = "doing"
            return
    for s in plan:
        if isinstance(s, dict) and s.get("state") == "todo":
            s["state"] = "doing"
            return


def sync_plan_on_merge(task, *, advance_next=True):
    """Advance existing outer plan steps on merge without ever inventing steps.

    Returns True if unfinished outer steps remain after the merge step.
    """
    close_doing_subplan(task)
    plan = task.get("plan")
    if not isinstance(plan, list) or not plan:
        return False
    merge_idx = next(
        (i for i, s in enumerate(plan) if isinstance(s, dict) and step_anchor(s) == "merge" and s.get("state") != "done"),
        None,
    )
    if merge_idx is not None:
        for i in range(merge_idx + 1):
            if isinstance(plan[i], dict):
                plan[i]["state"] = "done"
    else:
        for s in plan:
            if isinstance(s, dict) and s.get("state") == "doing" and step_anchor(s) in ("work", "review"):
                s["state"] = "done"
    remaining = [s for s in plan if isinstance(s, dict) and s.get("state") != "done"]
    if remaining and advance_next and not any(s.get("state") == "doing" for s in remaining):
        remaining[0]["state"] = "doing"
    return bool(remaining)


def sync_plan_on_approve(task):
    """When PM approves merge, mark prior doing work/review steps done and activate the @merge step."""
    plan = task.get("plan")
    if not isinstance(plan, list) or not plan:
        return
    merge_idx = next(
        (i for i, s in enumerate(plan) if isinstance(s, dict) and step_anchor(s) == "merge" and s.get("state") != "done"),
        None,
    )
    if merge_idx is not None:
        for i in range(merge_idx):
            if isinstance(plan[i], dict) and plan[i].get("state") != "done":
                if plan[i].get("state") == "doing" or step_anchor(plan[i]) in ("work", "review"):
                    plan[i]["state"] = "done"
        plan[merge_idx]["state"] = "doing"
    else:
        for s in plan:
            if isinstance(s, dict) and s.get("state") == "doing" and step_anchor(s) in ("work", "review"):
                s["state"] = "done"


def post_merge_steps(task):
    """Unfinished outer plan steps that remain AFTER the task's @merge step (empty when none or no plan)."""
    plan = task.get("plan")
    if not isinstance(plan, list) or not plan:
        return []
    merge_idx = next(
        (i for i, s in enumerate(plan) if isinstance(s, dict) and step_anchor(s) == "merge"),
        None,
    )
    if merge_idx is None:
        return []
    return [s for s in plan[merge_idx + 1:] if isinstance(s, dict) and s.get("state") != "done"]


def advance_outer_plan_step(task):
    """Check off the active (or first unfinished) outer plan step and activate the next todo step.
    Returns (changed, done_n, total_n, next_step_text)."""
    plan = task.get("plan")
    if not isinstance(plan, list) or not plan:
        return False, 0, 0, ""
    idx = next((i for i, s in enumerate(plan) if isinstance(s, dict) and s.get("state") == "doing"), None)
    if idx is None:
        idx = next((i for i, s in enumerate(plan) if isinstance(s, dict) and s.get("state") != "done"), None)
    if idx is None:
        d, t, nxt = plan_progress(plan)
        return False, d, t, nxt
    plan[idx]["state"] = "done"
    for s in plan[idx + 1:]:
        if isinstance(s, dict) and s.get("state") == "todo":
            s["state"] = "doing"
            break
    d, t, nxt = plan_progress(plan)
    return True, d, t, nxt


def sync_plan_for_status(task, new_status, *, prev_status="", explicit_outer=False, explicit_outer_states=False):
    """Update existing outer plan & subplan states on ledger status transitions without inventing steps."""
    if new_status in ("review", "done", "released", "merged"):
        close_doing_subplan(task)
    plan = task.get("plan")
    if not isinstance(plan, list) or not plan:
        return
    if new_status == "in_progress":
        if explicit_outer:
            activate_first_todo(plan)
            return
        if prev_status == "review":
            rev_idx = next(
                (i for i, s in enumerate(plan) if isinstance(s, dict) and step_anchor(s) == "review" and s.get("state") == "doing"),
                None,
            )
            if rev_idx is None:
                rev_idx = next(
                    (i for i in range(len(plan) - 1, -1, -1)
                     if isinstance(plan[i], dict) and step_anchor(plan[i]) == "review" and plan[i].get("state") == "done"),
                    None,
                )
            if rev_idx is not None:
                plan[rev_idx]["state"] = "todo"
                work_idx = next(
                    (i for i in range(rev_idx - 1, -1, -1)
                     if isinstance(plan[i], dict) and step_anchor(plan[i]) == "work"),
                    None,
                )
                if work_idx is None:
                    work_idx = next(
                        (i for i in range(rev_idx - 1, -1, -1)
                         if isinstance(plan[i], dict) and step_anchor(plan[i]) not in ("review", "merge")),
                        None,
                    )
                if work_idx is not None:
                    plan[work_idx]["state"] = "doing"
                    return
        activate_first_todo(plan)
    elif new_status == "review":
        if explicit_outer:
            return
        marked_doing = False
        for s in plan:
            if isinstance(s, dict) and s.get("state") == "doing" and step_anchor(s) not in ("review", "merge"):
                s["state"] = "done"
                marked_doing = True
        if not marked_doing:
            for s in plan:
                if not isinstance(s, dict):
                    continue
                anc = step_anchor(s)
                if anc in ("review", "merge") and s.get("state") != "done":
                    break
                if anc == "work" and s.get("state") == "todo":
                    s["state"] = "done"
                    break
        for s in plan:
            if isinstance(s, dict) and step_anchor(s) == "review" and s.get("state") != "done":
                s["state"] = "doing"
                break
    elif new_status in ("done", "released"):
        if explicit_outer and explicit_outer_states:
            return
        for s in plan:
            if isinstance(s, dict):
                s["state"] = "done"
    elif new_status == "merged":
        sync_plan_on_merge(task, advance_next=False)
