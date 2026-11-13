const STRINGS = {
  en: {
    in_progress: 'In progress', working: 'Working', blocked: 'Blocked', review: 'Review',
    idle: 'Idle', done: 'Done', offline: 'Offline', pending: 'Pending', cancelled: 'Cancelled', unknown: 'Unknown',
    paused: 'Paused', proposed: 'Proposed', merged: 'Merged', released: 'Released', abandoned: 'Abandoned',
    cleanup: 'Merged · not retired',
    noPm: 'No PM', unassigned: 'Unassigned project',
    waitingForProject: (name, n) => `${name} has ${n} ${n === 1 ? 'item' : 'items'} waiting for you`,
    conclusion: parts => parts.length ? parts.join('; ') + '.' : 'Nothing is waiting for you right now.',
    prompt: 'You sent a message', reply: 'PM replied to this turn',
    allProjects: 'All your projects', waiting: n => `${n} ${n === 1 ? 'item' : 'items'} waiting`,
    nothingWaiting: 'Nothing waiting', notDesktop: 'Not in desktop', inDesktop: 'In desktop', localMachine: 'Local',
    blockedWaiting: 'Blocked · Waiting for you', reviewWaiting: 'Review · Waiting for you', workingNow: 'Working…',
    task: 'Task', projects: 'Project PMs', tasks: 'Tasks', running: 'Running',
    recent: 'Recent activity', replay: 'Replay · ', noEvents: 'No new records yet.', idleReplay: 'Idle replay',
    noLogs: 'No logs yet', openTerminal: 'Click to open its terminal', board: 'Board', readError: 'Could not read ledger. Retrying soon',
    live: 'Live from ledger', loading: 'Reading ledger…',
    setupTitle: 'Set up PM', setup: 'Set up', settingUp: 'Setting up…', checkingSetup: 'Checking PM setup…',
    setupDescription: 'Copies the PM skill to ~/.claude/skills/pm and adds its hooks to ~/.claude/settings.json.',
    setupDone: 'Done. Restart your Claude Code sessions, then say "act as PM for this project".',
    setupOutdated: 'A PM skill update is available.', update: 'Update',
    setupIncomplete: 'Setup did not finish. Try again.',
    line: (name, text) => `${name}: ${text}`,
    summaryLead: (p, r) => `${p} ${p === 1 ? 'project' : 'projects'} · ${r} ${r === 1 ? 'task' : 'tasks'} running ·`,
    summaryWaiting: w => `${w} ${w === 1 ? 'item' : 'items'} waiting`,
    summary: (p, r, w) => `${p} ${p === 1 ? 'project' : 'projects'} · ${r} ${r === 1 ? 'task' : 'tasks'} running · ${w} ${w === 1 ? 'item' : 'items'} waiting`,
  },
  zh: {
    in_progress: '进行中', working: '工作中', blocked: '阻塞', review: '待审',
    idle: '空闲', done: '完成', offline: '离线', pending: '待办', cancelled: '取消', unknown: '未知',
    paused: '暂停', proposed: '提议', merged: '已合并', released: '已发布', abandoned: '放弃',
    cleanup: '已合并 · 待回收',
    noPm: '无 PM', unassigned: '未分配项目',
    waitingForProject: (name, n) => `${name} 有 ${n} 件事等你`,
    conclusion: parts => parts.length ? parts.join('；') + '。' : '现在没有等你的事。',
    prompt: '你发来一条消息', reply: 'PM 回复了这一轮',
    allProjects: '项目都在这里', waiting: n => `${n} 件等你`,
    nothingWaiting: '没有等你的事', notDesktop: '不在 desktop', inDesktop: '在 desktop', localMachine: '本机',
    blockedWaiting: '阻塞 · 等你', reviewWaiting: '待审 · 等你', workingNow: '工作中…',
    task: '任务', projects: '项目 PM', tasks: '任务', running: '在跑',
    recent: '最近发生了什么', replay: '回放 · ', noEvents: '还没有新的记录。', idleReplay: '空闲回放',
    noLogs: '暂无日志', openTerminal: '点击跳到该终端', board: '看 板', readError: '台账读取失败，稍后重试',
    live: '实时，来自台账', loading: '正在读取台账…',
    setupTitle: '设置 PM', setup: '设置', settingUp: '正在设置…', checkingSetup: '正在检查 PM 设置…',
    setupDescription: '将 PM 技能复制到 ~/.claude/skills/pm，并将其 hooks 添加到 ~/.claude/settings.json。',
    setupDone: '设置完成。重启 Claude Code 会话，然后说“作为本项目的 PM”。',
    setupOutdated: 'PM 技能有可用更新。', update: '更新',
    setupIncomplete: '设置尚未完成，请重试。',
    line: (name, text) => `${name}：${text}`,
    summaryLead: (p, r) => `${p} 个项目 · ${r} 个任务在跑 ·`,
    summaryWaiting: w => `${w} 件事等你`,
    summary: (p, r, w) => `${p} 个项目 · ${r} 个任务在跑 · ${w} 件事等你`,
  },
};
export function word(lang, key, ...args) {
  const value = STRINGS[lang === 'zh' ? 'zh' : 'en'][key];
  return typeof value === 'function' ? value(...args) : value;
}
export const label = (lang, status) => word(lang, status) || status || word(lang, 'unknown');

// Facts come from setup.py --status. Missing prerequisites take precedence over
// a version difference; optional Discord hooks do not affect readiness.
export function setupState(status) {
  if (status?.skill_present !== true || status?.hooks_present !== true) return 'missing';
  return status.script_matches === true ? 'ready' : 'outdated';
}

export function taskStatusText(lang, row) {
  if (row.cleanup) return word(lang, 'cleanup');
  if (row.status === 'blocked') return word(lang, 'blockedWaiting');
  if (row.status === 'review') return word(lang, 'reviewWaiting');
  if (['paused', 'proposed', 'done', 'merged', 'released', 'abandoned', 'cancelled'].includes(row.status)) return label(lang, row.status);
  return row.live === 'working' ? word(lang, 'workingNow') : label(lang, row.status);
}

// Strip only a leading ledger status/commit prefix, never prose mentioning
// those fields later in the log. Keep the commit separate for the metadata row.
export function cleanTaskLog(latest) {
  const text = typeof latest === 'string' ? latest.trim() : '';
  const prefix = /^status\s*=\s*[\w-]+(?:\s*[,;，；]\s*commit\s*=\s*([^\s,;，；]+))?\s*(?:[,;，；]\s*|$)/.exec(text);
  return { text: prefix ? text.slice(prefix[0].length).trim() : text, commit: prefix?.[1] || '' };
}

// Rows already contain scaled stage coordinates. The viewport is translated
// into that same coordinate system from the current painted stage bounds.
export function hoverCardPosition(row, stageHeight, viewport, height, scale = 1) {
  const top = Math.max(0, viewport.top), bottom = Math.min(stageHeight, viewport.bottom);
  if (row.y + row.h <= top || row.y >= bottom) return null;
  const gap = 6 * scale;
  const below = Math.max(0, bottom - row.y - row.h - gap);
  const above = Math.max(0, row.y - gap - top);
  // Prefer below, flip above if it fits. In a tiny viewport neither side may
  // fit: use the larger side and constrain the card, never cover its own row.
  const up = below < height && (above >= height || above > below);
  const h = Math.min(height, up ? above : below);
  return h > 0 ? { x: row.x, y: up ? row.y - gap - h : row.y + row.h + gap,
    w: Math.min(520 * scale, row.w), h, side: up ? 'above' : 'below' } : null;
}

export function cachedRemoteStates(text, now = Date.now()) {
  try {
    const cached = JSON.parse(text);
    const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    if (!object(cached) || !Number.isFinite(cached.at) || cached.at < 0 ||
        cached.at > now || now - cached.at > 10 * 60 * 1000 || !object(cached.states)) return null;
    if (!Object.values(cached.states).every(state => object(state) &&
        ['pms', 'tasks', 'events'].every(key => Array.isArray(state[key]) && state[key].every(object)))) return null;
    return cached.states;
  } catch (_) { return null; }
}

// Keep source labels for terminal lookup; namespace every ledger reference together.
// Missing/failed remote reads are omitted without affecting the local snapshot.
export function mergeStates(local, remote = {}) {
  const merged = { lang: local?.lang, pms: [], tasks: [], events: [] };
  for (const [machine, state] of [['', local], ...Object.entries(remote).filter(([name]) => name)]) {
    if (!state || !['pms', 'tasks', 'events'].every(k => Array.isArray(state[k]))) continue;
    const key = value => machine ? `${machine}/${value || ''}` : value || '';
    merged.pms.push(...state.pms.map(p => ({ ...p, machine, sourceName: p.name, name: key(p.name) })));
    merged.tasks.push(...state.tasks.map(t => ({ ...t, machine, sourceId: t.id, sourcePm: t.pm,
      id: key(t.id), pm: key(t.pm) })));
    merged.events.push(...state.events.map(e => ({ ...e, machine, key: key(e.key),
      pm: key(e.pm), task: e.task ? key(e.task) : '' })));
  }
  merged.events.sort((a, b) => (Date.parse((a.at || '').replace(' ', 'T')) || 0) -
    (Date.parse((b.at || '').replace(' ', 'T')) || 0));
  return merged;
}

// Pure geometry and state comparison. No host APIs.
export const pmId = name => `pm:${name || ''}`;
export const taskId = id => `task:${id}`;
export function boardFrame(width) {
  const w = Math.max(560, width), wide = w >= 1500;
  // Give up outer whitespace before introducing horizontal overflow at 560px.
  const inset = Math.min(wide ? 36 : 28, (w - 560) / 2);
  const feedWidth = wide ? 330 : 0, gap = wide ? 36 : 0;
  return { width: w, inset, wide, feedWidth, gap, graphWidth: w - inset * 2 - feedWidth - gap };
}

export function fitBoard(state, width, height, fixedHeight) {
  const frame = boardFrame(width);
  const natural = layout(state, frame.graphWidth, height, 1, frame.wide);
  const fixed = fixedHeight ?? (frame.wide ? 160 : 210 + Math.min(5, state.events.length) * 30);
  const scale = Math.max(.6, Math.min(1, (height - fixed) / natural.height));
  return { ...(scale === 1 ? natural : layout(state, frame.graphWidth, height, scale, frame.wide)), frame, scale };
}

// Urgency tiers are deliberately equal for blocked/review; stable sort keeps
// the ledger order within each tier. Filtering first leaves the source untouched.
const urgency = task => ['blocked', 'review'].includes(task.status) ? 0 : task.status === 'in_progress' ? 1 : 2;

export function layout(state, width = 980, _height = 640, scale = 1, wide = width >= 1300) {
  const w = Math.max(560, width), rows = [], wires = [], taskGroups = [];
  const you = { id: 'you', title: 'dudu', x: 0, y: 0, w: wide ? 176 : 148, h: 148 };
  rows.push(you);
  const groups = [...state.pms];
  for (const task of state.tasks) {
    if (!groups.some(p => (p.name || '') === (task.pm || ''))) groups.push({ name: task.pm || '',
      sourceName: task.sourcePm, machine: task.machine, project: '', status: 'offline' });
  }
  const fit = Math.min(1, (w - 560) / 420);
  const pw = wide ? 260 : 168 + Math.round(46 * fit);
  const px = you.w + (wide ? 150 : 20 + Math.round(64 * fit));
  const tx = px + pw + (wide ? 84 : 20 + Math.round(24 * fit));
  const rowHeight = wide ? 36 : 32, laneGap = wide ? 14 : 10;
  const machines = [...new Set(groups.map(p => p.machine || ''))].map((machine, i) => ({
    machine, number: i + 1, title: machine || word(state.lang, 'localMachine'),
  }));
  // Wrap machine chips inside the PM column; even long hostnames cannot
  // collide with the task heading. Positions use the same scale as the rows.
  let chipX = state.lang === 'zh' ? 54 : 82, chipY = 0;
  for (const machine of machines) {
    machine.label = `${machines.length > 1 ? machine.number + ' · ' : ''}${machine.title}`;
    machine.w = Math.min(pw, 16 + [...machine.label].reduce((n, c) => n + (c.codePointAt(0) > 255 ? 11 : 6.6), 0));
    if (chipX + machine.w > pw) { chipX = 0; chipY += 22; }
    machine.x = px + chipX; machine.y = chipY * scale; machine.h = 18 * scale;
    chipX += machine.w + 8;
  }
  const bodyTop = Math.max(28, chipY + 26);
  let y = bodyTop;
  for (const p of groups) {
    const tasks = state.tasks.filter(t => (t.pm || '') === (p.name || '')).sort((a, b) => urgency(a) - urgency(b));
    const span = Math.max(48, tasks.length * rowHeight);
    const latest = [...state.events].reverse().find(e => e.pm === p.name);
    rows.push({ ...p, id: pmId(p.name), type: 'pm', title: p.project || (p.sourceName ?? p.name) || word(state.lang, 'noPm'),
      machineNumber: machines.length > 1 ? machines.find(m => m.machine === (p.machine || '')).number : null,
      latest: eventText(latest, state.lang), x: px, y: y + (span - 48) / 2, w: pw, h: 48 });
    const top = y + (span - tasks.length * rowHeight) / 2;
    if (tasks.length) taskGroups.push({ id: `group:${p.name || ''}`, pm: p.name || '', x: tx, y: top,
      w: w - tx, h: tasks.length * rowHeight });
    tasks.forEach((t, i) => rows.push({ ...t, task: t.id, id: taskId(t.id), type: 'task',
      first: i === 0, x: tx, y: top + i * rowHeight, w: w - tx, h: rowHeight }));
    y += span + laneGap;
  }
  const bodyBottom = Math.max(bodyTop + you.h, y - (groups.length ? laneGap : 0));
  const height = bodyBottom + 32;
  you.y = bodyTop + (bodyBottom - bodyTop - you.h) / 2;
  // Keep column positions/widths; only the hub's own width scales. Build
  // wires from these same rows so static curves and moving packets agree.
  for (const row of [...rows, ...taskGroups]) { row.y *= scale; row.h *= scale; }
  you.w *= scale;
  const wire = (id, from, to, pm) => {
    const a = [from.x + from.w, from.y + from.h / 2], b = [to.x, to.y + to.h / 2];
    const mx = (a[0] + b[0]) / 2;
    wires.push({ id, pm, from: from.id, to: to.id, points: [a, [mx, a[1]], [mx, b[1]], b], straight: a[1] === b[1] });
  };
  for (const pm of rows.filter(r => r.type === 'pm')) {
    wire(pm.id, you, pm, pm.name || '');
    for (const task of rows.filter(r => r.type === 'task' && (r.pm || '') === (pm.name || ''))) wire(task.id, pm, task, pm.name || '');
  }
  return { rows, wires, taskGroups, machines, pmX: px, taskX: tx,
    bodyTop: bodyTop * scale, bodyBottom: bodyBottom * scale, width: w, height: height * scale };
}

// gpui-kit accepts #rgb, #rrggbb and #rrggbbaa. Preserve a token's existing
// alpha instead of stacking opacity on its text or replacing its RGB color.
export function withAlpha(color, opacity) {
  const hex = color.slice(1), rgb = hex.length === 3 ? [...hex].map(c => c + c).join('') : hex.slice(0, 6);
  const alpha = hex.length === 8 ? parseInt(hex.slice(6), 16) : 255;
  return `#${rgb}${Math.round(alpha * opacity).toString(16).padStart(2, '0')}`;
}

function luminance(color) {
  const hex = color.slice(1), rgb = hex.length === 3 ? [...hex].map(c => c + c).join('') : hex;
  return [0, 2, 4].reduce((n, offset, i) => {
    const c = parseInt(rgb.slice(offset, offset + 2), 16) / 255;
    return n + (c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4) * [.2126, .7152, .0722][i];
  }, 0);
}

// herdr.theme() exposes color tokens, unlike gpui-base's Theme.is_dark.
export function isDarkTheme(theme) {
  return luminance(theme.foreground) > luminance(theme.background);
}

// Use only supplied theme tokens, choosing their higher-contrast foreground
// for each solid fill rather than assuming white also works in a dark theme.
export function solidText(fill, theme) {
  const bg = luminance(fill);
  const contrast = color => { const fg = luminance(color); return (Math.max(bg, fg) + .05) / (Math.min(bg, fg) + .05); };
  return [theme.foreground, theme.background, theme.surface, theme.accent_foreground]
    .filter(Boolean).reduce((best, color) => contrast(color) > contrast(best) ? color : best);
}

export function pmColor(name) {
  const palette = ['ansi4', 'ansi5', 'ansi6', 'ansi3', 'ansi2', 'ansi1'];
  let hash = 0;
  for (const char of name || '') hash = (Math.imul(hash, 31) + char.codePointAt(0)) >>> 0;
  return palette[hash % palette.length];
}

export function counts(state) {
  const review = state.tasks.filter(t => t.status === 'review').length;
  const blocked = state.tasks.filter(t => t.status === 'blocked').length;
  const running = state.tasks.filter(t => t.status === 'in_progress' && t.worker === 'working').length;
  const waiting = review + blocked;
  const groups = new Map();
  for (const task of state.tasks.filter(t => ['review', 'blocked'].includes(t.status))) {
    const pm = state.pms.find(p => p.name === task.pm);
    const name = pm?.project || (pm?.sourceName ?? pm?.name) || task.project || word(state.lang, 'unassigned');
    const key = JSON.stringify([task.machine || '', pm?.name || name]);
    const group = groups.get(key) || { name, count: 0 };
    group.count++;
    groups.set(key, group);
  }
  const conclusion = word(state.lang, 'conclusion', [...groups.values()].map(({ name, count }) => word(state.lang, 'waitingForProject', name, count)));
  return { running, review, blocked, waiting, conclusion };
}

export function eventText(e, lang) {
  return !e ? '' : e.text || (e.kind === 'prompt' ? word(lang, 'prompt') : e.kind === 'reply' ? word(lang, 'reply') : '');
}
export function newEvents(previous, next) {
  if (!previous) return [];
  const seen = new Set(previous.events.map(e => e.key));
  return next.events.filter(e => !seen.has(e.key) && seen.add(e.key));
}
export function pointAt(points, u) {
  const v = 1 - u, c = [v*v*v, 3*v*v*u, 3*v*u*u, u*u*u];
  return { x: points.reduce((s,p,i) => s + c[i]*p[0], 0), y: points.reduce((s,p,i) => s + c[i]*p[1], 0) };
}
export function terminalFor(row, terms) {
  const machine = row.machine || '';
  const candidates = terms.filter(t => t.state === 'live' &&
    (machine ? t.address?.startsWith(`${machine}/`) : !t.address?.includes('/')));
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

// A PM's activity never makes a different worker's wire active.
export function wireFlows(wire, rows) {
  const target = rows.find(row => row.id === wire.to);
  if (!target || target.live !== 'working') return false;
  return target.type === 'pm' || (target.type === 'task' &&
    !['paused', 'proposed', 'done', 'merged', 'released', 'abandoned', 'cancelled'].includes(target.status));
}

// Arc-length resampling at 2px, retaining the residual between fine segments.
export function sampleWire(points) {
  const out = [{ ...pointAt(points, 0), distance: 0 }];
  let previous = out[0], remaining = 2, total = 0;
  for (let i = 1; i <= 600; i++) {
    const next = pointAt(points, i / 600);
    let distance = Math.hypot(next.x - previous.x, next.y - previous.y);
    total += distance;
    while (distance >= remaining) {
      const u = remaining / distance;
      previous = { x: previous.x + (next.x - previous.x) * u, y: previous.y + (next.y - previous.y) * u };
      out.push({ ...previous, distance: out.length * 2 });
      distance = Math.hypot(next.x - previous.x, next.y - previous.y);
      remaining = 2;
    }
    remaining -= distance;
    previous = next;
  }
  const end = { ...pointAt(points, 1), distance: total };
  if (total - out[out.length - 1].distance < 1e-6) out[out.length - 1] = end;
  else out.push(end); // Keep the exact endpoint, including the final <2px tail.
  return out;
}

export const PACKET_SPEED = 260; // px/s for every wire, in either direction.
export const PACKET_STEP = 24;

export function arcHops(samples, reverse = false) {
  const total = samples.at(-1)?.distance || 0;
  const at = distance => {
    if (distance <= 0) return { x: samples[0].x, y: samples[0].y };
    if (distance >= total) return { x: samples.at(-1).x, y: samples.at(-1).y };
    let lo = 0, hi = samples.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (samples[mid].distance < distance) lo = mid;
      else hi = mid;
    }
    const a = samples[lo], b = samples[hi], u = (distance - a.distance) / (b.distance - a.distance);
    return { x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u };
  };
  const hops = [];
  for (let start = 0; start < total; start += PACKET_STEP) {
    const end = Math.min(total, start + PACKET_STEP), distance = end - start;
    hops.push({ from: at(reverse ? total - start : start), to: at(reverse ? total - end : end),
      distance, duration: distance / PACKET_SPEED * 1000 });
  }
  return hops;
}
