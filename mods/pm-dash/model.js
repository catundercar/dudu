const STRINGS = {
  en: {
    in_progress: 'In progress', working: 'Working', blocked: 'Blocked', review: 'Review',
    reviewed: 'Reviewed',
    idle: 'Idle', done: 'Done', offline: 'Offline', pending: 'Pending', cancelled: 'Cancelled', unknown: 'Unknown',
    disconnected: 'Disconnected',
    paused: 'Paused', proposed: 'Proposed', merged: 'Merged', released: 'Released', abandoned: 'Abandoned',
    cleanup: 'Merged · not retired',
    noPm: 'No PM', unassigned: 'Unassigned project',
    waitingForProject: (name, n) => `${name} has ${n} ${n === 1 ? 'item' : 'items'} waiting for you`,
    conclusion: parts => parts.length ? parts.join('; ') + '.' : 'Nothing is waiting for you right now.',
    prompt: 'You sent a message', reply: 'PM replied to this turn',
    allProjects: 'All your projects', waiting: n => `${n} ${n === 1 ? 'item' : 'items'} waiting`,
    nothingWaiting: 'Nothing waiting', notDesktop: 'Not in desktop', inDesktop: 'In desktop', localMachine: 'Local',
    pmProjectFallback: "PM session is not in the desktop app. Click opens the project's space.",
    pmDesktopMissing: 'PM session is not in the desktop app. Start it there and run pm.py claim.',
    blockedWaiting: 'Blocked · Waiting for you', answered: 'Answered', workingNow: 'Working…',
    task: 'Task', projects: 'Project PMs', tasks: 'Tasks', running: 'Running',
    recent: 'Recent activity', replay: 'Replay · ', noEvents: 'No new records yet.', idleReplay: 'Idle replay',
    noLogs: 'No logs yet', openTerminal: 'Click to open its terminal', board: 'Board', readError: 'Could not read ledger. Retrying soon',
    live: 'Live from ledger', loading: 'Reading ledger…',
    setupTitle: 'Set up PM', setup: 'Set up', settingUp: 'Setting up…', checkingSetup: 'Checking PM setup…',
    setupDescription: "Copies the PM skill into your coding agents' skill folders (Claude Code, Codex, pi) and adds their hooks.",
    setupDone: 'Done. Restart your coding agent sessions, then say "act as PM for this project".',
    setupOutdated: 'A PM skill update is available.', update: 'Update',
    setupIncomplete: 'Setup did not finish. Try again.',
    // No Python 3.8+ to run the PM scripts (Windows: the Microsoft Store stub does not count).
    noPython: 'PM needs Python 3 first. Install Python 3.8 or newer from python.org, restart Herdr, then click Set up.',
    noPythonWindows: 'PM needs Python 3 first. Install it from python.org, or run winget install Python.Python.3.12 in a terminal. Then restart Herdr and click Set up.',
    line: (name, text) => `${name}: ${text}`,
    summaryLead: (p, r) => `${p} ${p === 1 ? 'project' : 'projects'} · ${r} ${r === 1 ? 'task' : 'tasks'} running ·`,
    summaryWaiting: w => `${w} ${w === 1 ? 'item' : 'items'} waiting`,
    summary: (p, r, w) => `${p} ${p === 1 ? 'project' : 'projects'} · ${r} ${r === 1 ? 'task' : 'tasks'} running · ${w} ${w === 1 ? 'item' : 'items'} waiting`,

    // The Projects page, the project board and their dialogs. "Projects" is a name, in every language.
    projectsTitle: 'Projects', listView: 'List', boardView: 'Board', chatView: 'Conversation',
    pageSummary: (p, r, w) => `${p} ${p === 1 ? 'project' : 'projects'} · ${r} ${r === 1 ? 'thread' : 'threads'} working · ${w} waiting for you`,
    count_waiting: n => `Needs you ${n}`, count_working: n => `In progress ${n}`, count_review: n => `Review ${n}`,
    count_proposed: n => `Not started ${n}`, count_merged_today: n => `Merged ${n}`,
    noOpen: 'No threads in progress', idlePm: 'The PM is idle; nothing is open.', noProjects: 'No projects yet. Start one with +.',
    archivedN: n => `Archived ${n}`, archivedTitle: 'Archived', backToProjects: 'Projects',
    archivedSummary: n => `${n} ${n === 1 ? 'project' : 'projects'} · restoring starts a new PM that takes over from the handover`,
    pausedLine: (n, titles) => `Paused ${n}: ${titles}`, nothingPaused: 'Nothing was open', archivedOn: day => `archived ${day}`,
    restore: 'Restore', openProject: 'Open project', archiveProject: 'Archive project', newProject: 'New project',
    remoteProject: 'On another machine: click opens its conversation; archive it there',
    archiveTitle: name => `Archive ${name}?`, archiveLead: 'The PM session closes, and these threads are marked paused and stop reminding you:',
    archiveNone: 'The PM session closes. No threads are open.',
    archiveKeep: 'The conversation, the ledger and the decisions you made all stay. On restore a new PM takes over from the handover.',
    cancel: 'Cancel', archive: 'Archive', thread_blocked: 'Needs you', thread_in_progress: 'In progress',
    thread_review: 'Review', thread_proposed: 'Not started',
    folder: 'Folder', chooseFolder: 'Choose a folder…', name: 'Name', manager: 'Manager', place: 'Where',
    newSpace: name => `New space “${name}”`, currentSpace: name => `Current space “${name}”`,
    placeHint: 'The PM starts in this space and the project view opens.', create: 'Create · ⌘↵', creating: 'Starting the PM…',
    ledgerOpen: (name, n, titles) => `The ledger already has ${n} open ${n === 1 ? 'item' : 'items'} for ${name} (${titles}); the new PM takes ${n === 1 ? 'it' : 'them'} over.`,
    failedAction: text => `Failed: ${text}`,
    endedCount: n => `Ended ${n}`, endedRecent: titles => `Latest: ${titles}`, endedMore: n => `Click to see all ${n}`,
    showDropped: n => `Show ${n} abandoned`, hideDropped: n => `Hide ${n} abandoned`,
    today: 'Today', yesterday: day => `Yesterday · ${day}`, earlier: 'Earlier',
  },
  zh: {
    in_progress: '进行中', working: '工作中', blocked: '阻塞', review: '待审',
    reviewed: '审查有结果',
    idle: '空闲', done: '完成', offline: '离线', pending: '待办', cancelled: '取消', unknown: '未知',
    disconnected: '已断开',
    paused: '暂停', proposed: '提议', merged: '已合并', released: '已发布', abandoned: '放弃',
    cleanup: '已合并 · 待回收',
    noPm: '无 PM', unassigned: '未分配项目',
    waitingForProject: (name, n) => `${name} 有 ${n} 件事等你`,
    conclusion: parts => parts.length ? parts.join('；') + '。' : '现在没有等你的事。',
    prompt: '你发来一条消息', reply: 'PM 回复了这一轮',
    allProjects: '项目都在这里', waiting: n => `${n} 件等你`,
    nothingWaiting: '没有等你的事', notDesktop: '不在 desktop', inDesktop: '在 desktop', localMachine: '本机',
    pmProjectFallback: 'PM 会话不在 desktop 里，点击打开该项目的空间。',
    pmDesktopMissing: 'PM 会话不在 desktop 里。在 desktop 里启动后运行 pm.py claim。',
    blockedWaiting: '阻塞 · 等你', answered: '已回答', workingNow: '工作中…',
    task: '任务', projects: '项目 PM', tasks: '任务', running: '在跑',
    recent: '最近发生了什么', replay: '回放 · ', noEvents: '还没有新的记录。', idleReplay: '空闲回放',
    noLogs: '暂无日志', openTerminal: '点击跳到该终端', board: '看 板', readError: '台账读取失败，稍后重试',
    live: '实时，来自台账', loading: '正在读取台账…',
    setupTitle: '设置 PM', setup: '设置', settingUp: '正在设置…', checkingSetup: '正在检查 PM 设置…',
    setupDescription: '将 PM 技能复制到各编程 agent 的技能目录（Claude Code、Codex、pi），并添加它们的 hooks。',
    setupDone: '设置完成。重启编程 agent 的会话，然后说“作为本项目的 PM”。',
    setupOutdated: 'PM 技能有可用更新。', update: '更新',
    setupIncomplete: '设置尚未完成，请重试。',
    noPython: 'PM 需要先装 Python 3：从 python.org 安装 3.8 或更新的版本，装好后重开 Herdr，再点「设置」。',
    noPythonWindows: 'PM 需要先装 Python 3：从 python.org 下载安装，或在终端运行 winget install Python.Python.3.12。装好后重开 Herdr，再点「设置」。',
    line: (name, text) => `${name}：${text}`,
    summaryLead: (p, r) => `${p} 个项目 · ${r} 个任务在跑 ·`,
    summaryWaiting: w => `${w} 件事等你`,
    summary: (p, r, w) => `${p} 个项目 · ${r} 个任务在跑 · ${w} 件事等你`,

    projectsTitle: 'Projects', listView: '列表', boardView: '看板', chatView: '对话',
    pageSummary: (p, r, w) => `${p} 个项目 · ${r} 个线程在做 · ${w} 件等你`,
    count_waiting: n => `等你 ${n}`, count_working: n => `进行中 ${n}`, count_review: n => `待审 ${n}`,
    count_proposed: n => `未开始 ${n}`, count_merged_today: n => `已合并 ${n}`,
    noOpen: '没有进行中的线程', idlePm: 'PM 空闲，没有在办的事。', noProjects: '还没有项目。点 + 新建一个。',
    archivedN: n => `已归档 ${n}`, archivedTitle: '已归档', backToProjects: 'Projects',
    archivedSummary: n => `${n} 个项目 · 恢复后 PM 重新启动，从交接记录接手`,
    pausedLine: (n, titles) => `暂停 ${n}：${titles}`, nothingPaused: '归档时没有在办的事', archivedOn: day => `${day} 归档`,
    restore: '恢复', openProject: '打开项目', archiveProject: '归档项目', newProject: '新建项目',
    remoteProject: '在另一台机器上：点击打开对话；归档要到那台机器上做',
    archiveTitle: name => `归档 ${name}?`, archiveLead: 'PM 会话会关掉，下面这些线程标成暂停，不再提醒你：',
    archiveNone: 'PM 会话会关掉。现在没有在办的线程。',
    archiveKeep: '对话、台账和你做过的决定都留着。恢复时新 PM 从交接记录接手。',
    cancel: '取消', archive: '归档', thread_blocked: '等你', thread_in_progress: '进行中',
    thread_review: '待审', thread_proposed: '未开始',
    folder: '文件夹', chooseFolder: '选择文件夹…', name: '名称', manager: '管理者', place: '放在哪',
    newSpace: name => `新开 space「${name}」`, currentSpace: name => `放进当前 space「${name}」`,
    placeHint: 'PM 在这个 space 里启动，项目视图直接打开。', create: '创建 · ⌘↵', creating: '正在启动 PM…',
    ledgerOpen: (name, n, titles) => `台账里已有 ${name} 的 ${n} 件没结束的事（${titles}），新 PM 会接着管。`,
    failedAction: text => `没有成功：${text}`,
    endedCount: n => `已结束 ${n}`, endedRecent: titles => `最近：${titles}`, endedMore: n => `点开看全部 ${n} 条`,
    showDropped: n => `显示放弃的 ${n} 条`, hideDropped: n => `隐藏放弃的 ${n} 条`,
    today: '今天', yesterday: day => `昨天 · ${day}`, earlier: '更早',
  },
};
export function word(lang, key, ...args) {
  const value = STRINGS[lang === 'zh' ? 'zh' : 'en'][key];
  return typeof value === 'function' ? value(...args) : value;
}
export const label = (lang, status) => word(lang, status) || status || word(lang, 'unknown');

// Facts come from setup.py --status, per agent with a summary. Ready: at least one
// agent is fully set up and no installed copy is outdated. An agent that has the
// skill but lacks its hooks is not ready; Set up installs them.
export function setupState(status) {
  const summary = status?.summary, list = key => Array.isArray(summary?.[key]) ? summary[key] : [];
  if (!list('installed').length) return 'missing';
  if (list('outdated').length) return 'outdated';
  return list('ready').length ? 'ready' : 'missing';
}

// The ledger home pm.py uses: PM_HOME, else ~/.claude/pm where an earlier install
// keeps it, else ~/.dudu. `pm.py state` reports it as `home`; this shell line
// answers the same question before the first state arrives.
export const LEDGER_HOME_SH = 'if [ -n "$PM_HOME" ]; then printf %s "$PM_HOME"; ' +
  'elif [ -d "$HOME/.claude/pm" ]; then printf %s "$HOME/.claude/pm"; else printf %s "$HOME/.dudu"; fi';

// Where another machine may keep pm.py: the desktop bundle, then each agent's skill folder.
export const PM_SCRIPTS = ['.config/herdr-app/mods/pm-dash/skill/scripts/pm.py', '.claude/skills/pm/scripts/pm.py',
  '.codex/skills/pm/scripts/pm.py', '.pi/agent/skills/pm/scripts/pm.py'];

// One shell line for `hc exec --on <machine>`: run `state` with the first script that exists.
export function remoteStateCommand(scripts = PM_SCRIPTS) {
  return `for f in ${scripts.map(path => `"$HOME/${path}"`).join(' ')}; do ` +
    'if [ -f "$f" ]; then exec python3 "$f" state; fi; done; echo "pm.py not found" >&2; exit 127';
}

// A PM card's status line names its agent program quietly when the ledger knows it.
export function pmStatusText(lang, row) {
  return [label(lang, row.live), row.agent].filter(Boolean).join(' · ');
}

// A task in progress whose terminal is gone (`pm.py state`: offline) is no work going on.
export const disconnected = row => Boolean(row?.offline) && row.status === 'in_progress';

export function taskStatusText(lang, row) {
  if (row.cleanup) return word(lang, 'cleanup');
  if (disconnected(row)) return word(lang, 'disconnected');
  // Answered (pm.py's `answered`): it waits for the PM now, not for the user.
  if (row.status === 'blocked') return word(lang, row.answered ? 'answered' : 'blockedWaiting');
  if (['review', 'paused', 'proposed', 'done', 'merged', 'released', 'abandoned', 'cancelled'].includes(row.status)) return label(lang, row.status);
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
    // A review thread is shown as the task it reviews (foldReviews): its reports reach that task, as what
    // the review says, never as the task's own status (a review's done is not the task's).
    const tasks = foldReviews(state.tasks);
    const into = new Map(tasks.filter(t => t.review).map(t => [t.review.id, t.id]));
    const asReview = e => !into.has(e.task) ? e : { ...e, status: '', review: e.status && e.status !== 'in_progress' ? 'reviewed' : 'review',
      text: String(e.text || '').replace(/^status=\w+;?\s*/, '') };
    merged.pms.push(...state.pms.map(p => ({ ...p, machine, sourceName: p.name, name: key(p.name) })));
    merged.tasks.push(...tasks.map(t => ({ ...t, machine, sourceId: t.id, sourcePm: t.pm,
      id: key(t.id), pm: key(t.pm) })));
    merged.events.push(...state.events.map(asReview).map(e => ({ ...e, machine, key: key(e.key),
      pm: key(e.pm), task: e.task ? key(into.get(e.task) || e.task) : '' })));
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

// `view`: the board's own state, by PM name: which ended lists are open (`open`), which show their
// abandoned tasks (`dropped`), and today ("YYYY-MM-DD") for their day headings.
export function fitBoard(state, width, height, fixedHeight, view = {}) {
  const frame = boardFrame(width);
  // The scale follows the folded board: an opened ended list adds height that scrolls.
  const folded = layout(state, frame.graphWidth, height, 1, frame.wide, { ...view, open: [] });
  const fixed = fixedHeight ?? (frame.wide ? 160 : 210 + Math.min(5, state.events.length) * 30);
  const scale = Math.max(.6, Math.min(1, (height - fixed) / folded.height));
  const same = scale === 1 && !view.open?.length;
  return { ...(same ? folded : layout(state, frame.graphWidth, height, scale, frame.wide, view)), frame, scale };
}

// ---- Bundles: one PM's tasks on the board ---------------------------------------

// Active tasks bundle by status, the one waiting for the user first; an unknown status (or none)
// follows in a bundle of its own. Ended tasks fold into one node; abandoned ones (and cancelled)
// hide behind it.
export const BUNDLES = ['blocked', 'review', 'in_progress', 'proposed', 'paused'];
export const ENDED = ['done', 'merged', 'released'];
export const DROPPED = ['abandoned', 'cancelled'];
const newestFirst = (a, b) => String(b.updated || '').localeCompare(String(a.updated || ''));
const bundleRank = status => BUNDLES.includes(status) ? BUNDLES.indexOf(status) : BUNDLES.length;

// Stable throughout: ledger order within a bundle, and among ended tasks of the same minute.
export function boardGroups(tasks) {
  const bundles = [], ended = [], dropped = [];
  for (const task of tasks) {
    if (ENDED.includes(task.status)) ended.push(task);
    else if (DROPPED.includes(task.status)) dropped.push(task);
    else {
      const status = task.status || '';
      let bundle = bundles.find(b => b.status === status);
      if (!bundle) bundles.push(bundle = { status, tasks: [] });
      bundle.tasks.push(task);
    }
  }
  bundles.sort((a, b) => bundleRank(a.status) - bundleRank(b.status));
  return { bundles, ended: ended.sort(newestFirst), dropped: dropped.sort(newestFirst) };
}
// What an opened ended list shows: the ended tasks, and the abandoned ones only when asked.
export const endedList = ({ ended, dropped }, showDropped) =>
  showDropped ? [...ended, ...dropped].sort(newestFirst) : ended;

export const bundleLabel = (lang, status) =>
  ['blocked', 'review', 'in_progress', 'proposed'].includes(status) ? word(lang, `thread_${status}`) : label(lang, status);

const DAY = /^\d{4}-\d{2}-\d{2}/;
export function previousDay(day) {
  if (!DAY.test(String(day || ''))) return '';
  const [y, m, d] = day.slice(0, 10).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d - 1)).toISOString().slice(0, 10);
}
// A newest-first list cut into days: today, yesterday, then each older date; the undated last.
export function endedDays(tasks, today, lang) {
  const days = [];
  for (const task of tasks) {
    const key = DAY.exec(String(task.updated || ''))?.[0] || '';
    if (days.at(-1)?.key !== key) days.push({ key, tasks: [], title: !key ? word(lang, 'earlier') :
      key === today ? word(lang, 'today') : key === previousDay(today) ? word(lang, 'yesterday', key.slice(5)) : key.slice(5) });
    days.at(-1).tasks.push(task);
  }
  return days;
}
// "HH:MM" on `day`, else "MM-DD HH:MM", from the ledger's "YYYY-MM-DD HH:MM".
export function endedTime(updated, day) {
  const text = String(updated || '');
  if (!DAY.test(text)) return '';
  return day && text.startsWith(day) ? text.slice(11, 16) : text.slice(5, 16);
}

export function layout(state, width = 980, _height = 640, scale = 1, wide = width >= 1300, view = {}) {
  const w = Math.max(560, width), rows = [], wires = [], guides = [], links = [], routes = {};
  const open = view.open || [], showDropped = view.dropped || [];
  // A board scoped to one project (scopeState) starts at its PM: there is no hub to wire from.
  const hub = !state.project;
  const you = { id: 'you', title: 'dudu', x: 0, y: 0, w: hub ? (wide ? 176 : 148) : 0, h: hub ? 148 : 0 };
  if (hub) rows.push(you);
  const groups = [...state.pms];
  for (const task of state.tasks) {
    if (!groups.some(p => (p.name || '') === (task.pm || ''))) groups.push({ name: task.pm || '',
      sourceName: task.sourcePm, machine: task.machine, project: '', status: 'offline' });
  }
  const fit = Math.min(1, (w - 560) / 420);
  const pw = wide ? 260 : 168 + Math.round(46 * fit);
  const px = hub ? you.w + (wide ? 150 : 20 + Math.round(64 * fit)) : 0;
  // Room between the PMs and the tasks: each bundle's trunk, then its fork into the rows.
  const reach = hub ? (wide ? 120 : 32 + Math.round(52 * fit)) : (wide ? 200 : 56 + Math.round(104 * fit));
  const tx = px + pw + reach, fork = tx - Math.min(44, Math.round(reach * .4));
  const rowHeight = wide ? 36 : 32, rowGap = 4, labelHeight = 18, bundleGap = 10, laneGap = wide ? 14 : 10;
  const endedHeight = rowHeight + 6, entryHeight = 26, dayHeight = 20;
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
    const pm = p.name || '', base = { pm, machine: p.machine };
    const parts = boardGroups(state.tasks.filter(t => (t.pm || '') === pm));
    const latest = [...state.events].reverse().find(e => e.pm === p.name);
    const pmRow = { ...p, id: pmId(p.name), type: 'pm', title: p.project || (p.sourceName ?? p.name) || word(state.lang, 'noPm'),
      machineNumber: machines.length > 1 ? machines.find(m => m.machine === (p.machine || '')).number : null,
      latest: eventText(latest, state.lang), x: px, y, w: pw, h: 48 };
    rows.push(pmRow);
    const top = y, anchors = [], link = (id, from, to, extra) => links.push({ id, owner: pmRow, from, to, ...extra });
    let bottom = y;
    for (const bundle of parts.bundles) {
      rows.push({ ...base, id: `label:${pm}:${bundle.status}`, type: 'label', status: bundle.status,
        title: bundleLabel(state.lang, bundle.status), count: bundle.tasks.length, x: tx + 2, y, w: w - tx - 2, h: labelHeight });
      y += labelHeight + 4;
      const members = bundle.tasks.map((t, i) => {
        const row = { ...t, task: t.id, id: taskId(t.id), type: 'task', first: i === 0, x: tx, y, w: w - tx, h: rowHeight };
        rows.push(row); y += rowHeight + rowGap;
        return row;
      });
      bottom = y - rowGap; y = bottom + bundleGap + 4;
      anchors.push(members[0].y + rowHeight / 2, members.at(-1).y + rowHeight / 2);
      if (members.length === 1) {
        link(members[0].id, pmRow, members[0]);
        routes[members[0].id] = [members[0].id];
        continue;
      }
      // One trunk from the PM to the bundle's fork, then a branch to each of its tasks.
      const middle = (members[0].y + members.at(-1).y + rowHeight) / 2, trunk = `trunk:${pm}:${bundle.status}`;
      const junction = { ...base, id: `junction:${pm}:${bundle.status}`, type: 'junction', status: bundle.status,
        members: members.map(r => r.id), x: fork - 3, y: middle - 3, w: 6, h: 6 };
      rows.push(junction);
      link(trunk, pmRow, junction, { members: junction.members });
      for (const row of members) {
        link(row.id, junction, row, { trunk });
        routes[row.id] = [trunk, row.id];
      }
    }
    if (parts.ended.length || parts.dropped.length) {
      const expanded = open.includes(pm), showing = showDropped.includes(pm);
      // One static line for all of them. "Ended N" never counts the abandoned ones.
      const node = { ...base, id: `ended:${pm}`, type: 'ended', count: parts.ended.length, dropped: parts.dropped.length,
        open: expanded, showDropped: showing, recent: parts.ended.slice(0, 3).map(t => t.title || t.sourceId || t.id),
        peek: parts.ended.slice(0, 6), x: tx, y, w: w - tx, h: endedHeight };
      rows.push(node);
      link(node.id, pmRow, node, { ended: true });
      for (const t of [...parts.ended, ...parts.dropped]) routes[taskId(t.id)] = [node.id];
      anchors.push(y + endedHeight / 2);
      y += endedHeight; bottom = y;
      const list = expanded ? endedList(parts, showing) : [];
      if (list.length) {
        // Opened in place under the node, by day, along one straight guide (not a wire per task).
        y += 8;
        for (const day of endedDays(list, view.today, state.lang)) {
          rows.push({ ...base, id: `day:${pm}:${day.key}`, type: 'day', title: day.title, x: tx + 34, y, w: w - tx - 34, h: dayHeight });
          y += dayHeight + 2;
          for (const t of day.tasks) {
            rows.push({ ...t, task: t.id, id: taskId(t.id), type: 'task', entry: true, time: endedTime(t.updated, day.key),
              x: tx + 26, y, w: w - tx - 26, h: entryHeight });
            y += entryHeight + 1;
          }
        }
        bottom = y - 1;
        guides.push({ ...base, id: `guide:${pm}`, x: tx + 18, y: node.y + endedHeight,
          h: bottom - entryHeight / 2 - node.y - endedHeight });
      }
    }
    // The PM sits at the middle of its folded rows; an opened list grows below without moving it.
    const middle = anchors.length ? (anchors[0] + anchors.at(-1)) / 2 : top + 24;
    pmRow.y = Math.max(top, middle - 24);
    y = Math.max(bottom, pmRow.y + pmRow.h) + laneGap;
  }
  const bodyBottom = Math.max(bodyTop + you.h, y - (groups.length ? laneGap : 0));
  const height = bodyBottom + 32;
  you.y = bodyTop + (bodyBottom - bodyTop - you.h) / 2;
  // Keep column positions/widths; only the hub's own width scales. Build
  // wires from these same rows so static curves and moving packets agree.
  for (const row of [...rows, ...guides]) { row.y *= scale; row.h *= scale; }
  you.w *= scale;
  const wire = (id, from, to, pm, extra) => {
    const a = [from.x + from.w, from.y + from.h / 2], b = [to.x, to.y + to.h / 2];
    const mx = (a[0] + b[0]) / 2;
    wires.push({ id, pm, from: from.id, to: to.id, points: [a, [mx, a[1]], [mx, b[1]], b], straight: a[1] === b[1], ...extra });
  };
  for (const pm of rows.filter(r => r.type === 'pm')) {
    if (hub) wire(pm.id, you, pm, pm.name || '');
    for (const { id, owner, from, to, ...extra } of links) if (owner === pm) wire(id, from, to, pm.name || '', extra);
  }
  return { rows, wires, guides, routes, machines, pmX: px, taskX: tx,
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
  // A blocked task the user has answered (pm.py's `answered`) waits for the PM, not for the user.
  const asking = state.tasks.filter(t => t.status === 'blocked' && !t.answered);
  const running = state.tasks.filter(t => t.status === 'in_progress' && t.worker === 'working').length;
  // Only blocked work waits for the user; review is the PM's job.
  const waiting = asking.length;
  const groups = new Map();
  for (const task of asking) {
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
// A retired PM's terminal (`pm.py rotate` labels it pm.retired=<project>) is nobody's: not the
// project's PM, and not the terminal of a task that was parked on it.
function liveTerminalsFor(row, terms) {
  const machine = row.machine || '';
  return terms.filter(t => t.state === 'live' && !t.labels?.['pm.retired'] &&
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

// A project terminal is a navigation destination, not evidence of the PM session.
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
  // A retired PM up the chain (labeled pm.retired by `pm.py rotate`, or a PM terminal that is not the
  // project's current one) is passed over: shown on its tab, the thread would invite talking to it.
  const retired = t => Boolean(t?.labels?.['pm.retired'] || (home && t?.labels?.pm && t.address !== home));
  const seen = new Set([address]);
  for (let up = byAddress.get(address)?.parent; up && !seen.has(up); up = byAddress.get(up)?.parent) {
    if (has.has(up) && !retired(byAddress.get(up))) return { focus: up, peek: address };
    seen.add(up);
  }
  return home && has.has(home) ? { focus: home, peek: address } : none;
}

// A PM's activity never makes a different worker's wire active.
export function wireFlows(wire, rows) {
  // A bundle's trunk flows while any of its tasks does; the ended node's line never does.
  if (wire.members) return wire.members.some(id => wireFlows({ to: id }, rows));
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

// ---- The Projects page ------------------------------------------------------

export const AGENT_NAMES = { claude: 'Claude Code', codex: 'Codex', pi: 'pi' };
export const agentName = kind => AGENT_NAMES[kind] || kind || '';
export const projectName = pm => pm?.project || String(pm?.sourceName ?? pm?.name ?? '').replace(/^pm-/, '');

// What a board shows: one project's PM, threads and events (`project`: its PM's name), or every
// project that is not archived. Tasks no PM owns stay on the all-projects board.
export function scopeState(state, project = '') {
  const keep = project ? pm => pm.name === project : pm => !pm.archived;
  const pms = state.pms.filter(keep), shown = new Set(pms.map(pm => pm.name));
  const hidden = new Set(state.pms.filter(pm => !keep(pm)).map(pm => pm.name));
  const mine = pm => project ? shown.has(pm) : !hidden.has(pm);
  return { ...state, project, pms, tasks: state.tasks.filter(t => mine(t.pm)), events: state.events.filter(e => mine(e.pm)) };
}

const OPEN = ['blocked', 'in_progress', 'review', 'proposed'];
// A project's numbers as `pm.py state` counts them (`counts`); a ledger from before that field
// counts its own open tasks the same way. `today`: "YYYY-MM-DD".
export function projectCounts(pm, tasks, today = '') {
  const c = pm?.counts;
  if (c && typeof c === 'object') {
    return Object.fromEntries(['working', 'waiting', 'review', 'proposed', 'merged_today'].map(k => [k, Number(c[k]) || 0]));
  }
  const mine = tasks.filter(t => (t.pm || '') === (pm?.name || ''));
  const n = status => mine.filter(t => t.status === status).length;
  // An in-progress task whose terminal is gone (disconnected) is no work going on, as pm.py counts it.
  return { working: mine.filter(t => t.status === 'in_progress' && !disconnected(t)).length, waiting: mine.filter(t => t.status === 'blocked' && !t.answered).length, review: n('review'), proposed: n('proposed'),
    merged_today: mine.filter(t => t.status === 'merged' && today && String(t.updated || '').startsWith(today)).length };
}
// The card's quiet numbers, most urgent first, without the zeros.
export const COUNT_ORDER = ['waiting', 'working', 'review', 'proposed', 'merged_today'];
export const countChips = counts => COUNT_ORDER.filter(k => counts[k] > 0).map(k => [k, counts[k]]);

export function lastEventAt(events, pm) {
  let at = 0;
  for (const e of events) {
    if (e?.pm !== pm) continue;
    const ms = new Date(String(e.at || '').replace(' ', 'T')).getTime();
    if (ms > at) at = ms;
  }
  return at;
}
const UNITS = [[86400000, 'd', '天'], [3600000, 'h', '小时'], [60000, 'm', '分钟']];
// A copy of pm-list's age (the sidebar and the cards read alike); pm-list's test keeps them identical.
export function age(ms, lang) {
  const unit = UNITS.find(([size]) => ms >= size), zh = lang === 'zh';
  if (!unit) return zh ? '刚刚' : '<1m';
  return zh ? `${Math.floor(ms / unit[0])} ${unit[2]}` : `${Math.floor(ms / unit[0])}${unit[1]}`;
}
export const archivedDay = value => /^\d{4}-(\d{2}-\d{2})/.exec(String(value || ''))?.[1] || String(value || '');

// The cards of the Projects page from a merged state (mergeStates): those in work, most recently
// active first, and the archived ones, newest archive first. `lines`: {pm name: lastPmLine(...)}.
export function projectCards(state, lines = {}, today = '') {
  const cards = state.pms.map(pm => ({
    key: pm.name, name: projectName(pm), repo: pm.repo || '', machine: pm.machine || '', status: pm.status || '',
    agent: agentName(pm.agent), archived: pm.archived || null, counts: projectCounts(pm, state.tasks, today),
    at: lastEventAt(state.events, pm.name), line: lines[pm.name] || [],
    paused: state.tasks.filter(t => (t.pm || '') === pm.name && t.status === 'paused').map(t => t.title || t.sourceId || t.id),
  }));
  return { active: cards.filter(c => !c.archived).sort((a, b) => b.at - a.at || a.name.localeCompare(b.name)),
    archived: cards.filter(c => c.archived).sort((a, b) => String(b.archived).localeCompare(String(a.archived))) };
}
export const pageTotals = cards => ({ projects: cards.length,
  working: cards.reduce((n, c) => n + c.counts.working, 0), waiting: cards.reduce((n, c) => n + c.counts.waiting, 0) });

// The PM's newest words in a conversation log (JSON lines): the first line of its last `pm` event,
// as text and link pieces ([title](thread:id) keeps its title), without markdown marks.
export function lastPmLine(text) {
  let last = '';
  for (const line of String(text || '').split('\n')) {
    try { const e = JSON.parse(line); if (e?.type === 'pm' && typeof e.text === 'string' && e.text.trim()) last = e.text; }
    catch (_) { /* not an event */ }
  }
  const first = last.split('\n').map(l => l.trim()).find(Boolean) || '';
  const plain = s => s.replace(/\*\*|__|`/g, '').replace(/^[-*>#]+\s*/, '');
  const pieces = [], links = /\[([^\]]+)\]\(([^)]+)\)/g;
  let at = 0, m;
  while ((m = links.exec(first))) {
    if (m.index > at) pieces.push({ text: plain(first.slice(at, m.index)) });
    pieces.push({ text: plain(m[1]), link: m[2] });
    at = m.index + m[0].length;
  }
  if (at < first.length) pieces.push({ text: plain(first.slice(at)) });
  return pieces.filter(p => p.text);
}

// The threads archiving pauses: a project's open ones, those waiting for the user first; a review
// thread goes with the task it reviews (foldReviews).
export function archiveThreads(state, pm) {
  return foldReviews(state.tasks).filter(t => (t.pm || '') === pm && OPEN.includes(t.status))
    .sort((a, b) => OPEN.indexOf(a.status) - OPEN.indexOf(b.status));
}

// ---- New project --------------------------------------------------------------

export const folderName = path => String(path || '').replace(/\/+$/, '').split('/').pop() || '';
export const KINDS = ['claude', 'codex', 'pi'];
// Open work the ledger already keeps under this project name: the new PM takes it over.
export function ledgerOpen(state, name) {
  const key = String(name || '').trim().toLowerCase();
  return key ? state.tasks.filter(t => [...OPEN, 'paused'].includes(t.status) && String(t.project || '').toLowerCase() === key) : [];
}
// What the form runs: pm.py start for the chosen folder, name, agent and space (new | current).
export function startArgv(script, form) {
  return [script, 'start', '--repo', form.repo, '--name', String(form.name || '').trim() || folderName(form.repo),
    '--kind', form.kind || 'claude', '--space', form.space === 'current' ? 'current' : 'new'];
}

// ---- Esc ----------------------------------------------------------------------

// Esc goes back one layer, one layer a press (page = shared('pm-dash')): a task's hover card (or the
// ended node's preview) closes first; then the opened ended lists fold; then one project's board goes
// back to that project's conversation, the archived projects back to the list, and the Projects page
// (list or board) back to the page it covered, as a second Projects click does ('back', which pm-nav decides). A dialog over the page has the keyboard and
// closes itself. Only while the stage shows this page (shown); otherwise null, and the key goes on.
export function escapeTarget(shown, page, { hoverCard = false, ended = false } = {}) {
  if (!shown) return null;
  if (hoverCard) return { hoverCard: true };
  // Only a board on screen has ended lists to fold: the list and archived pages go on.
  if (ended && (page?.project || page?.view === 'board')) return { ended: true };
  if (page?.project) return { project: page.project };
  if (page?.view === 'archived') return { view: 'list' };
  return { back: true };
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
