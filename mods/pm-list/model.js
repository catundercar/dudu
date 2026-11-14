// Pure parts of the sidebar PM list: live status, order, "3m ago" text, block height.

// Most urgent first, the same order as Herdr's agents list.
export const RANK = { blocked: 4, done: 3, working: 2, idle: 1 };

// A matched terminal reports Herdr's live status; a PM outside the desktop
// keeps the ledger's word. Anything unknown reads as idle.
export function pmStatus(pm, terminal, exact, live) {
  const raw = exact && terminal ? live.find(a => a.address === terminal.address)?.status || terminal.status : pm.status;
  return raw === 'error' ? 'blocked' : RANK[raw] ? raw : 'idle';
}

export function pmName(pm) {
  return `PM-${pm.project || String(pm.name || '').replace(/^pm-/, '')}`;
}

// local: this computer's `pm.py state`; remote: {machine: state} as pm-nav caches it.
// A remote PM keeps its own name for terminal lookup and is keyed "<machine>/<name>".
export function pmRows(local, remote, terms, live) {
  const sources = [['', local], ...Object.entries(remote || {}).filter(([machine]) => machine)];
  return sources.flatMap(([machine, state]) => (Array.isArray(state?.pms) ? state.pms : []).map(pm => {
    const row = { ...pm, type: 'pm', machine, sourceName: pm.name };
    const { terminal, exact } = terminalTargetFor(row, terms);
    return { key: machine ? `${machine}/${pm.name}` : pm.name, label: pmName(pm), machine,
      terminal: terminal || null, exact, status: pmStatus(pm, terminal, exact, live),
      program: exact ? terminal.program : null, seed: lastEventAt(state.events, pm.name) };
  })).sort((a, b) => RANK[b.status] - RANK[a.status] || a.label.localeCompare(b.label) ||
    a.machine.localeCompare(b.machine));
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

// "<1m", "5m", "3h", "2d": the largest whole unit.
const UNITS = [[86400000, 'd'], [3600000, 'h'], [60000, 'm']];
export function age(ms) {
  const unit = UNITS.find(([size]) => ms >= size);
  return unit ? `${Math.floor(ms / unit[0])}${unit[1]}` : '<1m';
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

export const HEADER = 30, ROW = 30, COMPACT_ROW = 28, PAD = 6, MAX_ROWS = 6;
// The block's height in px: the header alone with no PM, at most MAX_ROWS rows
// (the rest scroll). The rail keeps a sliver so the block still gets its width.
export function listHeight(count, compact) {
  const rows = Math.min(count, MAX_ROWS);
  if (compact) return rows * COMPACT_ROW + PAD * 2;
  return HEADER + (rows ? rows * ROW + PAD : 0);
}

// Copies of pm-dash/model.js (a mod cannot import from another mod's folder);
// model.test.mjs checks that they stay identical.
export const LEDGER_HOME_SH = 'if [ -n "$PM_HOME" ]; then printf %s "$PM_HOME"; ' +
  'elif [ -d "$HOME/.claude/pm" ]; then printf %s "$HOME/.claude/pm"; else printf %s "$HOME/.dudu"; fi';
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
