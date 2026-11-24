// Pure parts of the sidebar PM list: live status, order, "3m ago" text, block height.

// Most urgent first, the same order as Herdr's agents list; a terminal that reports no status last.
export const RANK = { blocked: 4, done: 3, working: 2, idle: 1, unknown: 0 };

// A live terminal's status as Herdr has it (the agents list, else the terminal's own word). A terminal
// whose program reports none (not an agent Herdr knows, or no reports on that platform) is 'unknown':
// nothing says it is idle.
export function liveStatus(terminal, live) {
  const raw = live.find(a => a.address === terminal.address)?.status || terminal.status;
  return raw === 'error' ? 'blocked' : RANK[raw] ? raw : 'unknown';
}

// A matched terminal reports Herdr's live status (liveStatus); a PM outside the desktop
// keeps the ledger's word, idle when it has none.
export function pmStatus(pm, terminal, exact, live) {
  if (exact && terminal) return liveStatus(terminal, live);
  const raw = pm.status;
  return raw === 'error' ? 'blocked' : RANK[raw] ? raw : 'idle';
}

// The project's own name: the sidebar sits under the Projects entry, so no "PM-" before it.
export function pmName(pm) {
  return pm.project || String(pm.name || '').replace(/^pm-/, '');
}

// How many of a project's threads wait for the user: the ledger's `counts`, else its blocked tasks the user has not answered.
export function waitingCount(pm, tasks) {
  if (Number.isFinite(pm?.counts?.waiting)) return pm.counts.waiting;
  return (Array.isArray(tasks) ? tasks : []).filter(t => t?.pm === pm?.name && t.status === 'blocked' && !t.answered).length;
}

// Default PM auto-compaction threshold when an older remote `pm.py state` omits `compact_tokens`.
export const DEFAULT_COMPACT_TOKENS = 200_000;
export const DEFAULT_ROTATE_TOKENS = DEFAULT_COMPACT_TOKENS;

export function resolveCompactTokens(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value > 0 ? Math.floor(value) : 0;
  return DEFAULT_COMPACT_TOKENS;
}
export const resolveRotateTokens = resolveCompactTokens;

// Positive integer context token count from `pm.py state` (`context_tokens`), or 0 when absent/unknown.
export function contextTokens(value) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

// Compact token count ("123k", "800"), or '' when absent/0.
export function contextShort(tokens) {
  const n = contextTokens(tokens);
  if (!n) return '';
  return n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
}

// Context usage label ("上下文 123k" / "Context 123k"), or '' when absent/0.
export function contextLabel(tokens, lang = 'en') {
  const short = contextShort(tokens);
  if (!short) return '';
  return lang === 'zh' ? `上下文 ${short}` : `Context ${short}`;
}

// PM context usage relative to `compact_tokens` (`pm.py` configures auto-compaction near `COMPACT_TOKENS`).
export function pmContextLevel(tokens, compactTokens = DEFAULT_COMPACT_TOKENS) {
  const n = contextTokens(tokens), limit = resolveCompactTokens(compactTokens);
  if (!n) return 'none';
  if (!limit) return 'normal';
  if (n > limit) return 'over';
  return n > Math.floor(limit * 0.8) ? 'near' : 'normal';
}

// Tooltip line for a PM's context usage, noting when it nears or passes `compact_tokens`.
export function pmContextTip(tokens, lang = 'en', compactTokens = DEFAULT_COMPACT_TOKENS) {
  const short = contextShort(tokens), limit = resolveCompactTokens(compactTokens), zh = lang === 'zh';
  if (!short) return '';
  const cap = contextShort(limit);
  if (!limit || !cap) return zh ? `上下文 ${short}` : `Context ${short}`;
  const level = pmContextLevel(tokens, limit);
  if (level === 'over') return zh ? `上下文 ${short} · 已超 ${cap} 压缩阈值` : `Context ${short} · over ${cap} compact threshold`;
  if (level === 'near') return zh ? `上下文 ${short} · 接近 ${cap} 压缩阈值` : `Context ${short} · approaching ${cap} compaction`;
  return zh ? `上下文 ${short}（压缩阈值 ${cap}）` : `Context ${short} (compact above ${cap})`;
}

// local: this computer's `pm.py state`; remote: {machine: state} as pm-nav caches it.
// A remote PM keeps its own name for terminal lookup and is keyed "<machine>/<name>".
export function pmRows(local, remote, terms, live) {
  const sources = [['', local], ...Object.entries(remote || {}).filter(([machine]) => machine)];
  return sources.flatMap(([machine, state]) => {
    const pms = Array.isArray(state?.pms) ? state.pms : [];
    const tasks = pms.some(pm => !Number.isFinite(pm?.counts?.waiting)) ? foldReviews(state?.tasks) : [];
    const stateCompact = state?.compact_tokens ?? state?.rotate_tokens;
    return pms.map(pm => {
      const row = { ...pm, type: 'pm', machine, sourceName: pm.name };
      const { terminal, exact } = terminalTargetFor(row, terms);
      const ctx = contextTokens(pm.context_tokens);
      const rawCompact = pm.compact_tokens ?? stateCompact;
      const hasCompact = typeof rawCompact === 'number' && Number.isFinite(rawCompact);
      return { key: machine ? `${machine}/${pm.name}` : pm.name, label: pmName(pm), machine,
        terminal: terminal || null, exact, status: pmStatus(pm, terminal, exact, live),
        program: exact ? terminal.program : null, seed: lastEventAt(state.events, pm.name),
        project: pm.project || '', archived: pm.archived || null, waiting: waitingCount(pm, tasks),
        ...(ctx ? { contextTokens: ctx, ...(hasCompact ? { compactTokens: resolveCompactTokens(rawCompact) } : {}) } : {}) };
    });
  }).sort(byUrgency);
}
const byUrgency = (a, b) => RANK[b.status] - RANK[a.status] || a.label.localeCompare(b.label) ||
  a.machine.localeCompare(b.machine);

// A live terminal labelled pm=<project> that no ledger row names, on this computer or another
// machine: a PM this ledger has no registration for. It gets a row of its own, so no PM goes missing; the
// row shows its terminal (there is no project here to open). rows: pmRows' rows, archived ones included.
export function labelledPmRows(rows, terms, live) {
  const named = new Set(rows.map(r => `${r.machine}\n${r.project || r.label}`));
  const shown = new Set(rows.filter(r => r.exact).map(r => r.terminal.address));
  const extra = [];
  for (const t of terms) {
    const project = t.labels?.pm;
    if (t.state !== 'live' || !project || !t.address || shown.has(t.address)) continue;
    const slash = t.address.lastIndexOf('/'), machine = slash < 0 ? '' : t.address.slice(0, slash);
    if (named.has(`${machine}\n${project}`)) continue;
    named.add(`${machine}\n${project}`);
    shown.add(t.address);
    extra.push({ key: `terminal:${t.address}`, label: project, machine, terminal: t, exact: true, unregistered: true,
      status: liveStatus(t, live), program: t.program || null, seed: 0, project, archived: null, waiting: 0 });
  }
  return extra;
}

// All rows of the list: the ledger's PMs, then PM terminals it has no registration for, most urgent first.
export function allPmRows(local, remote, terms, live) {
  const rows = pmRows(local, remote, terms, live);
  return [...rows, ...labelledPmRows(rows, terms, live)].sort(byUrgency);
}

// A row opens the project view (pm-project) when the stage has one: a local PM's and a remote PM's
// alike, since pm-project reads a remote project from its machine. Without that page (an older
// layout) the row focuses the PM's terminal instead.
export function opensProject(row, stage) {
  return Boolean(row) && !row.unregistered && Boolean(stage?.children?.some(c => c.id === 'pm-project'));
}
// What shared('pm-project') is set to for a row: its key, and the machine of a remote PM.
export function projectShared(row) {
  return row.machine ? { pm: row.key, machine: row.machine } : { pm: row.key };
}

// The sidebar's two parts: projects in work, and the archived ones folded at the bottom
// (newest archive first). `pm.py state` gives an archived PM its date, else null.
export function splitArchived(rows) {
  return { active: rows.filter(r => !r.archived),
    archived: rows.filter(r => r.archived).sort((a, b) => String(b.archived).localeCompare(String(a.archived))) };
}

// "2026-10-31…" as "10-31"; anything else as written.
export function archivedDay(value) {
  const m = /^\d{4}-(\d{2}-\d{2})/.exec(String(value || ''));
  return m ? m[1] : String(value || '');
}

// pm-nav's cache of other machines' states: {at, states: {machine: state}}. Its
// `at` stays put while nothing changes, so the age is not checked; pm-nav
// rewrites the file when a machine drops out. Unreadable text gives {}.
export function remotePmStates(text) {
  try {
    const states = JSON.parse(text)?.states;
    if (!states || typeof states !== 'object' || Array.isArray(states)) return {};
    return Object.fromEntries(Object.entries(states).filter(([, state]) => Array.isArray(state?.pms)));
  } catch (_) { return {}; }
}

// How long ago, in the largest whole unit: "<1m", "5m", "3h", "2d"; in a Chinese view "刚刚",
// "5 分钟", "3 小时", "2 天".
const UNITS = [[86400000, 'd', '天'], [3600000, 'h', '小时'], [60000, 'm', '分钟']];
export function age(ms, lang) {
  const unit = UNITS.find(([size]) => ms >= size), zh = lang === 'zh';
  if (!unit) return zh ? '刚刚' : '<1m';
  return zh ? `${Math.floor(ms / unit[0])} ${unit[2]}` : `${Math.floor(ms / unit[0])}${unit[1]}`;
}

// The ledger's newest event for a PM ("YYYY-MM-DD HH:MM", local time), in ms; 0 if none.
export function lastEventAt(events, pm) {
  let at = 0;
  for (const e of Array.isArray(events) ? events : []) {
    if (e?.pm !== pm || typeof e.at !== 'string') continue;
    const ms = new Date(e.at.replace(' ', 'T')).getTime();
    if (ms > at) at = ms;
  }
  return at;
}

// changed: {row key: {s: status, at: ms}}. A status change stamps `now`; done
// and idle count as one, as in the agents list (looking turns done into idle).
// A PM seen for the first time starts from its last ledger event (`seed`), if any.
export function track(changed, rows, now) {
  const next = { ...changed };
  let dirty = false;
  for (const row of rows) {
    const s = row.status === 'done' ? 'idle' : row.status;
    if (next[row.key]?.s === s) continue;
    next[row.key] = { s, at: next[row.key] ? now : row.seed || 0 };
    dirty = true;
  }
  return dirty ? next : changed;
}

export const HEADER = 30, ROW = 30, COMPACT_ROW = 28, PAD = 6, MAX_ROWS = 8;
// The block's height in px: the header alone with no PM, at most MAX_ROWS rows' height
// (the rest scroll). The rail keeps a sliver so the block still gets its width, and so
// does a list without its header (see underNav) while it has no PM.
export function listHeight(count, compact, header = true) {
  const rows = Math.min(count, MAX_ROWS);
  if (compact) return rows * COMPACT_ROW + PAD * 2;
  return (header ? HEADER : 0) + (rows ? rows * ROW + PAD : header ? 0 : PAD);
}

// True when the list's block comes right after pm-nav's in the same column: the PM title and the
// board entry are then its heading, and the list draws no "PM n" header of its own.
export function underNav(tree) {
  const mod = node => node?.content?.mod;
  const kids = Array.isArray(tree?.children) ? tree.children : [];
  const at = kids.findIndex(kid => mod(kid) === 'pm-list');
  if (at >= 0) return at > 0 && mod(kids[at - 1]) === 'pm-nav';
  return kids.some(kid => underNav(kid));
}

// Copies of pm-dash/model.js (a mod cannot import from another mod's folder);
// model.test.mjs checks that they stay identical.
export const LEDGER_HOME_SH = 'if [ -n "$PM_HOME" ]; then printf %s "$PM_HOME"; ' +
  'elif [ -d "$HOME/.claude/pm" ] && ! [ "$HOME/.claude/pm" -ef "$HOME/.dudu" ]; then printf %s "$HOME/.claude/pm"; else printf %s "$HOME/.dudu"; fi';
// Live terminals on the row's machine (`''` means local, so no `machine/` prefix).
function liveTerminalsFor(row, terms) {
  const machine = row.machine || '';
  return terms.filter(t => t.state === 'live' &&
    (machine ? t.address?.startsWith(`${machine}/`) : !t.address?.includes('/')));
}
export function terminalFor(row, terms) {
  const machine = row.machine || '';
  const candidates = liveTerminalsFor(row, terms);
  const key = row.type === 'pm' ? 'pm' : 'task';
  const value = row.type === 'pm' ? row.project || (row.sourceName ?? row.name)?.replace(/^pm-/, '') : row.sourceId ?? row.task;
  // Prefer a labeled child over a recorded parent pane (tasks may share their PM's pane).
  const labeled = candidates.find(t => value && t.labels?.[key] === value);
  const pane = row.pane?.startsWith('hc:') ? row.pane.slice(3) : '';
  const address = machine ? `${machine}/${pane}` : pane;
  return labeled || (pane ? candidates.find(t => t.address === address &&
    // A task recorded on its PM's pane must not borrow that PM's live status.
    (row.type === 'pm' || (!t.labels?.pm && (!t.labels?.task || t.labels.task === value)))) : undefined);
}
export function terminalTargetFor(row, terms) {
  const exact = terminalFor(row, terms);
  if (exact) return { terminal: exact, exact: true };
  const folder = path => typeof path === 'string' && path ? path.replace(/\/+$/, '') || '/' : '';
  const repo = folder(row.repo);
  const candidates = row.type === 'pm' && repo ? liveTerminalsFor(row, terms)
    .filter(t => t.address && folder(t.cwd) === repo) : [];
  candidates.sort((a, b) => Number(Boolean(b.program?.agent)) - Number(Boolean(a.program?.agent)) ||
    (a.address < b.address ? -1 : a.address > b.address ? 1 : 0));
  return { terminal: candidates[0], exact: false };
}
// How a click brings a terminal up. One with a pane: pane.focus, which shows its own space and tab.
// A sub-agent without a pane (Herdr's agents list peeks those) is peeked over the tab of the nearest
// terminal up its parent chain that has a pane and is not a retired PM, else over its project's current
// PM (`home`): a worker that outlived a PM rotated out (closed, or still open but retired). With neither, nothing: no pane is focused and the work
// column is not shown, since that would reveal whatever space was active — another project's.
// agent.focus is not used: on a paneless terminal it changes no tab (t5h opened OldName).
// `paned`: the addresses that have a pane (panes()' terminals, agents()' addresses).
export function focusPlan(address, terms, paned, home = '') {
  const none = { focus: '', peek: '' };
  if (!address) return none;
  const has = new Set(paned.filter(Boolean));
  if (has.has(address)) return { focus: address, peek: '' };
  const byAddress = new Map(terms.map(t => [t.address, t]));
  // Another PM terminal up the chain (`home` is the project's current PM) is passed over:
  // shown on its tab, the thread would invite talking to the wrong PM.
  const otherPm = t => Boolean(home && t?.labels?.pm && t.address !== home);
  const seen = new Set([address]);
  for (let up = byAddress.get(address)?.parent; up && !seen.has(up); up = byAddress.get(up)?.parent) {
    if (has.has(up) && !otherPm(byAddress.get(up))) return { focus: up, peek: address };
    seen.add(up);
  }
  return home && has.has(home) ? { focus: home, peek: address } : none;
}

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
