// Compare navigation identities, not cwd: a shell changing directory is not
// sidebar navigation. Keep remote machine prefixes intact.
export function focusKey(focus) {
  return JSON.stringify(['space', 'tab', 'pane', 'terminal', 'shown', 'agent'].map(key => focus?.[key] ?? null));
}

export function shouldReturnToWork(shown, wasShown, focus, previousFocus) {
  return shown && wasShown && focus !== previousFocus;
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

// writeTextFile documents atomic replacement of existing files, but not parent
// creation or atomic first creation. Rename a sibling temp file in both cases.
export const WRITE_REMOTE_CACHE = `
import json, os, sys, tempfile
from pathlib import Path
path = Path(sys.argv[1])
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
