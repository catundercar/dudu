export const NAV_HEIGHT = 40;
export const NAV_COMPACT_UNFOLD_HEIGHT = 72;

// True when the layout has no visible `agents` block (e.g. wrapped inside hidden `herdr-lists`).
// On macOS collapsed 76px rail, workspace-chrome hides its top sidebar-toggle because traffic lights
// fill row 1 and relies on `agents` rendering `»`. When `agents` is hidden, pm-nav renders `»` instead.
export function isAgentsHidden(tree, ancestorHidden = false) {
  if (!tree || typeof tree !== 'object') return true;
  const hidden = ancestorHidden || Boolean(tree.hidden);
  if (tree.content?.mod === 'agents') return hidden;
  const kids = Array.isArray(tree.children) ? tree.children : [];
  for (const child of kids) {
    if (!isAgentsHidden(child, hidden)) return false;
  }
  return true;
}

// Whether pm-nav writes <ledger home>/cache/remote-states.json (pm-list's only source of other machines'
// projects). Another machine's ledger is read over hc and needs no Set up here, so remote projects are
// cached even when this computer has no skill installed (or cannot read it). With nothing remote and no
// Set up here, it writes only to empty a cache that exists, so a disconnected machine does not linger.
export function shouldWriteRemoteCache(setupAvailable, states, cacheExists = false) {
  return Boolean(setupAvailable) || Object.keys(states || {}).length > 0 || Boolean(cacheExists);
}

// The Projects entry shows the summary whenever there is a project to count (on this computer or
// another machine); "Set up" only when Set up is missing here and there is nothing to show at all.
export function showsSummary(setupAvailable, counts) {
  return Boolean(setupAvailable) || Number(counts?.projects) > 0;
}

export function needsRailUnfold(tree, win) {
  return Boolean(tree && win?.platform === 'macos' && isAgentsHidden(tree));
}

export function navHeight(compact, showUnfold) {
  return compact && showUnfold ? NAV_COMPACT_UNFOLD_HEIGHT : NAV_HEIGHT;
}

// Compare navigation identities, not cwd: a shell changing directory is not
// sidebar navigation. Keep remote machine prefixes intact.
export function focusKey(focus) {
  return JSON.stringify(['space', 'tab', 'pane', 'terminal', 'shown', 'agent'].map(key => focus?.[key] ?? null));
}

// A terminal shown inside a pm-project floating window (openOverlay({ kind: 'window', layout }))
// takes keyboard focus with `pane == null` and `terminal` set to its address. Clicking it must
// not pull the stage back to `work`; clicking that same terminal's workspace pane sets `pane`.
export function isOverlayTerminalFocus(focus, overlayTerminals) {
  if (!focus || !focus.terminal || focus.pane != null) return false;
  if (!Array.isArray(overlayTerminals) || !overlayTerminals.length) return false;
  return overlayTerminals.includes(focus.terminal);
}

export function shouldReturnToWork(shown, wasShown, focus, previousFocus, { overlayFocus = false } = {}) {
  if (overlayFocus) return false;
  return shown && wasShown && focus !== previousFocus;
}

// Decide which pm-stage child should be active when a dudu layout mounts (e.g. after switching
// layouts or reloading mods). Returns the child id to select via layout.select, or null if
// stage.active already matches the desired child.
// Priority:
//   1. Persisted shared('pm-stage').child when present in stage.children (for 'pm-project',
//      requires a non-empty shared('pm-project').pm, else falls back to 'pm-board').
//   2. When no saved stage exists yet (e.g. switching from an older layout), restore 'pm-project'
//      if shared('pm-project').pm is set, otherwise default to 'pm-board' (Projects page).
export function initialStageChild(stage, savedStage, projectPage) {
  const children = (stage?.children ?? []).map(c => c?.id).filter(Boolean);
  if (!stage || !children.length) return null;
  const hasProject = typeof projectPage?.pm === 'string' && Boolean(projectPage.pm.trim());
  const saved = typeof savedStage?.child === 'string' ? savedStage.child : '';
  let target = '';
  if (saved && children.includes(saved)) {
    if (saved === 'pm-project' && !hasProject) {
      target = children.includes('pm-board') ? 'pm-board' : stage.active;
    } else {
      target = saved;
    }
  } else if (hasProject && children.includes('pm-project')) {
    target = 'pm-project';
  } else if (children.includes('pm-board')) {
    target = 'pm-board';
  } else {
    target = stage.active;
  }
  return target && target !== stage.active ? target : null;
}

// The stage page the Projects page covers, for the next Projects click to come back to: the stage's
// child, and for a project's conversation (pm-project) or its board (pm-board), which project (a
// remote one's key is "<machine>/<name>", and its conversation keeps the machine).
export function pageBefore(active, projectPage, dashPage) {
  if (!active) return null;
  if (active === 'pm-project') return projectPage?.pm ? { child: active, pm: projectPage.pm,
    ...(projectPage.machine ? { machine: projectPage.machine } : {}) } : null;
  if (active === 'pm-board') return dashPage?.project ? { child: active, pm: dashPage.project } : null;
  return { child: active };
}

// Where Projects goes from the Projects page: the page it covered, or the workspace when none was
// recorded, the stage no longer has that child, or its project is gone (archived or removed).
// pms: every listed PM by its key (projectKeys).
export function pageBack(page, children = [], pms = []) {
  const work = { child: 'work' };
  if (!page || !children.includes(page.child)) return work;
  if ('pm' in page && !pms.some(pm => pm?.name === page.pm && !pm.archived)) return work;
  return page;
}

// The PMs of this computer and of other machines, named by their keys as pm-list and the board name
// them: a remote one "<machine>/<name>".
export function projectKeys(local, remote = {}) {
  const pms = state => (Array.isArray(state?.pms) ? state.pms : []);
  return [...pms(local), ...Object.entries(remote || {}).filter(([machine]) => machine)
    .flatMap(([machine, state]) => pms(state).map(pm => ({ ...pm, name: `${machine}/${pm?.name}` })))];
}

// A copy of pm-list's waitingCount (a mod cannot import from another mod's folder);
// pm-list's model.test.mjs checks that both stay identical.
export function waitingCount(pm, tasks) {
  if (Number.isFinite(pm?.counts?.waiting)) return pm.counts.waiting;
  return (Array.isArray(tasks) ? tasks : []).filter(t => t?.pm === pm?.name && t.status === 'blocked' && !t.answered).length;
}

// How many of a project's threads are actively working (in progress and terminal not offline):
// pm.py's `counts.working`, else the same rule locally for an older remote pm.py.
export function workingCount(pm, tasks) {
  if (Number.isFinite(pm?.counts?.working)) return pm.counts.working;
  return (Array.isArray(tasks) ? tasks : []).filter(t => t?.pm === pm?.name && t.status === 'in_progress' && !t.offline).length;
}

// Unified overview counts across local and remote machines: prefers pm.py's top-level `state.counts`
// (and falls back to per-PM `counts` / folded tasks for an older remote pm.py). Only non-archived
// projects count here; unclaimed blocked tasks are shown separately in the overview, not in `blocked`.
export function summary(local, remote = {}) {
  let projects = 0, active = 0, blocked = 0;
  for (const state of [local, ...Object.values(remote || {})]) {
    if (!state || !Array.isArray(state.pms) || !Array.isArray(state.tasks)) continue;
    const c = state.counts;
    if (c && Number.isFinite(c.working) && Number.isFinite(c.waiting)) {
      projects += Number.isFinite(c.projects) ? c.projects : state.pms.filter(pm => !pm?.archived).length;
      active += c.working;
      blocked += c.waiting;
      continue;
    }
    const listed = state.pms.filter(pm => !pm?.archived);
    const needsTasks = listed.some(pm => !Number.isFinite(pm?.counts?.waiting) || !Number.isFinite(pm?.counts?.working));
    const tasks = needsTasks ? foldReviews(state.tasks) : [];
    projects += listed.length;
    for (const pm of listed) {
      active += workingCount(pm, tasks);
      blocked += waitingCount(pm, tasks);
    }
  }
  return { projects, active, blocked };
}

// Half an em per Latin character, one em per wide CJK character. The kit
// exposes layout sizes, but no text measurement or whole-child overflow hiding.
export function estimateTextWidth(text, fontSize = 11.5) {
  return Array.from(text).reduce((width, char) => width +
    (/[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe10-\ufe6f\uff01-\uff60\uffe0-\uffe6\u{20000}-\u{3ffff}]/u.test(char) ? 2 : 1), 0) * fontSize / 2;
}

// The entry's quiet count, "4 · 2 等你": the projects in work and what waits for the user. When
// the row is too narrow for it, only what waits; then nothing (the tooltip keeps it all).
export function navText(counts, lang, width) {
  const waiting = counts.blocked ? (lang === 'zh' ? `${counts.blocked} 等你` : `${counts.blocked} need you`) : '';
  const full = [String(counts.projects), waiting].filter(Boolean).join(' · ');
  return [full, waiting].find(text => text && estimateTextWidth(text) + 4 <= width) || '';
}

// Copies of pm-dash/model.js (a mod cannot import from another mod's folder);
// model.test.mjs checks that both stay identical.
export const LEDGER_HOME_SH = 'if [ -n "$PM_HOME" ]; then printf %s "$PM_HOME"; ' +
  'elif [ -d "$HOME/.claude/pm" ] && ! [ "$HOME/.claude/pm" -ef "$HOME/.dudu" ]; then printf %s "$HOME/.claude/pm"; else printf %s "$HOME/.dudu"; fi';
export const PM_SCRIPTS = ['.config/herdr-app/mods/pm-dash/skill/scripts/pm.py', '.claude/skills/pm/scripts/pm.py',
  '.codex/skills/pm/scripts/pm.py', '.pi/agent/skills/pm/scripts/pm.py'];
export function remoteStateCommand(scripts = PM_SCRIPTS) {
  return `for f in ${scripts.map(path => `"$HOME/${path}"`).join(' ')}; do ` +
    'if [ -f "$f" ]; then exec python3 "$f" state; fi; done; echo "pm.py not found" >&2; exit 127';
}

export const ENSURE_DIR_PY = "import sys; from pathlib import Path; Path(sys.argv[1]).mkdir(parents=True, exist_ok=True)";

// Stable signature of remote machines and their PMs, used to wake pm-list via
// shared('pm-remote-cache') only when the remote project set actually changes.
export function remoteCacheSig(states) {
  return Object.entries(states || {})
    .filter(([machine, state]) => machine && Array.isArray(state?.pms))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([machine, state]) => `${machine}:${state.pms.map(pm => `${pm?.name || ''}:${pm?.archived ? 1 : 0}`).sort().join(',')}`)
    .join('|');
}

// writeTextFile documents atomic replacement of existing files, but not parent
// creation or atomic first creation. Stage large JSON to a sibling file with
// writeTextFile (avoiding OS argv limits such as Windows' 32 KiB CreateProcess
// limit and Linux's 128 KiB MAX_ARG_STRLEN) and pass `--from-file <tmp>` so
// Python validates, deduplicates unchanged states, cleans up the staging file,
// and atomically replaces the target. Inline JSON in argv[2] remains supported
// for direct callers.
export const WRITE_REMOTE_CACHE = `
import json, os, sys, tempfile
from pathlib import Path
path = Path(sys.argv[1])
if sys.argv[2] == '--from-file':
    source = Path(sys.argv[3])
    at = int(sys.argv[4])
    try:
        states = json.loads(source.read_text(encoding='utf-8'))
    finally:
        try:
            source.unlink()
        except OSError:
            pass
else:
    states = json.loads(sys.argv[2])
    at = int(sys.argv[3])
try:
    old = json.loads(path.read_text(encoding='utf-8'))
except (OSError, ValueError):
    old = None
if (isinstance(old, dict) and type(old.get('at')) in (int, float)
        and 0 <= old['at'] <= at and old.get('states') == states):
    sys.exit(0)
path.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix='.remote-states-', dir=path.parent)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump({'at': at, 'states': states}, output, ensure_ascii=False)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
`;

// A review thread (`pm.py review`: a task with `review_of`) is part of the task it reviews: it leaves
// the list and rides on that task as `review`, so one piece of work is one row and counts once. While
// the review is open the task reads as what the review is: waiting on the user (blocked, with the
// review's `answered`) when the review asks, else in review; a task that itself waits on the user, or
// is paused, or a paused review, leaves the task's own status. A review whose task is not in the list
// stays a row of its own, so nothing goes missing, and so does an open review of a task that is over
// (done, abandoned: nothing of it is in review). pm.py's counts use the same rule (folded_status).
// pm-project, pm-dash, pm-nav and pm-list keep identical copies (pm-project's model.test.mjs checks).
export function foldReviews(tasks) {
  const list = (Array.isArray(tasks) ? tasks : []).filter(Boolean);
  const over = status => ['merged', 'released', 'done', 'abandoned'].includes(status);
  const byId = new Map(list.map(t => [t.id, t]));
  const reviews = new Map(list.filter(t => t.review_of && t.review_of !== t.id && byId.has(t.review_of) &&
    (over(t.status) || !over(byId.get(t.review_of).status))).map(t => [t.review_of, t]));
  if (!reviews.size) return list;
  const fold = (t, r) => {
    const quiet = over(r.status) || r.status === 'paused' || ['blocked', 'paused'].includes(t.status);
    if (quiet) return { ...t, review: r };
    return r.status === 'blocked' ? { ...t, review: r, status: 'blocked', answered: Boolean(r.answered) } : { ...t, review: r, status: 'review' };
  };
  return list.filter(t => !(t.review_of && reviews.get(t.review_of) === t))
    .map(t => reviews.has(t.id) ? fold(t, reviews.get(t.id)) : t);
}
