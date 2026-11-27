export const STEP_LABEL_UNITS = 24; // ~12 CJK chars or 24 ASCII chars for short step labels
export const PLAN_STRINGS = {
  en: {
    reviewing: 'Reviewing',
    planTitle: 'Steps',
    planProgress: (done, total) => `${done}/${total}`,
    planAutoReview: 'Auto-review',
    planAutoReviewTip: 'Auto-starts an independent reviewer on commit',
    planNoReview: 'No review',
    planNoReviewTip: 'No code review in this task plan',
    planRound: n => `R${n}`,
    planFoldedRounds: n => n === 1 ? 'R1' : `R1–${n}`,
    planFallbackWork: 'Work',
    planFallbackReview: 'Review',
    planFallbackDone: 'Done',
    planPostStep: (done, total, step) => `${done}/${total} · ${step}`,
    depsTitle: 'Waiting',
    depsReady: 'Ready to dispatch',
    depsJumpTip: title => `Open ${title}`,
    depsAbandoned: 'Abandoned',
    depsMissing: 'Missing',
    substepsFoldTip: (done, total) => `${done}/${total} sub-steps`,
    detailReviewStepTip: 'Click to toggle review window',
  },
  zh: {
    reviewing: '审查中',
    planTitle: '步骤',
    planProgress: (done, total) => `${done}/${total}`,
    planAutoReview: '自动审',
    planAutoReviewTip: '提交后自动拉起独立审查',
    planNoReview: '免审',
    planNoReviewTip: '本任务计划不含代码审查',
    planRound: n => `第${n}轮`,
    planFoldedRounds: n => n === 1 ? '第1轮' : `第1-${n}轮`,
    planFallbackWork: '执行',
    planFallbackReview: '审查',
    planFallbackDone: '完成',
    planPostStep: (done, total, step) => `${done}/${total} · ${step}`,
    depsTitle: '等待',
    depsReady: '可以派了',
    depsJumpTip: title => `跳转到 ${title}`,
    depsAbandoned: '已放弃',
    depsMissing: '不存在',
    substepsFoldTip: (done, total) => `${done}/${total} 个子步骤`,
    detailReviewStepTip: '点击开关审查小窗',
  },
};

const STRINGS = {
  en: {
    in_progress: 'In progress', working: 'Working', blocked: 'Blocked', review: 'Review',
    reviewed: 'Reviewed',
    idle: 'Idle', done: 'Done', offline: 'Offline', pending: 'Pending', cancelled: 'Cancelled', unknown: 'Unknown',
    disconnected: 'Disconnected', closedReattach: 'Closed · can reattach', reviewClosed: 'Review · closed',
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
    windowMinimize: 'Minimize', windowMaximize: 'Maximize', windowRestore: 'Restore', windowClose: 'Close',
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
    unclaimedBlocked: n => `Unclaimed blocked ${n}`, unclaimedShort: 'Unclaimed',
    unclaimedTip: 'Blocked tasks with no project PM (not counted in waiting for you). Click to view on the board.',
    today: 'Today', yesterday: day => `Yesterday · ${day}`, earlier: 'Earlier',
    ...PLAN_STRINGS.en,
  },
  zh: {
    in_progress: '进行中', working: '工作中', blocked: '阻塞', review: '待审',
    reviewed: '审查有结果',
    idle: '空闲', done: '完成', offline: '离线', pending: '待办', cancelled: '取消', unknown: '未知',
    disconnected: '已断开', closedReattach: '已关闭，可重连', reviewClosed: '待审 · 已关闭',
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
    windowMinimize: '最小化', windowMaximize: '最大化', windowRestore: '还原', windowClose: '关闭',
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
    unclaimedBlocked: n => `无人认领的阻塞 ${n}`, unclaimedShort: '无人认领',
    unclaimedTip: '没有对应项目 PM 的阻塞任务（不计入「等你」）。点击到看板查看。',
    today: '今天', yesterday: day => `昨天 · ${day}`, earlier: '更早',
    ...PLAN_STRINGS.zh,
  },
};
export function word(lang, key, ...args) {
  const value = STRINGS[lang === 'zh' ? 'zh' : 'en'][key];
  return typeof value === 'function' ? value(...args) : value ?? key;
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

export function shouldRecheckSetup(status, busy = false, checking = false) {
  return !busy && !checking && (status === 'missing' || status === 'outdated');
}

// The ledger home pm.py uses: PM_HOME, else ~/.claude/pm where an earlier install
// keeps it (not when ~/.claude/pm symlinks to ~/.dudu), else ~/.dudu. `pm.py state`
// reports it as `home`; this shell line answers the same question before the first
// state arrives.
export const LEDGER_HOME_SH = 'if [ -n "$PM_HOME" ]; then printf %s "$PM_HOME"; ' +
  'elif [ -d "$HOME/.claude/pm" ] && ! [ "$HOME/.claude/pm" -ef "$HOME/.dudu" ]; then printf %s "$HOME/.claude/pm"; else printf %s "$HOME/.dudu"; fi';

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

// True when an offline task's terminal was ended on purpose (`closed` from `pm.py state`, matching `pane`).
export const isClosedTask = row => Boolean(row?.offline && row?.closed && typeof row.closed === 'object'
  && !Array.isArray(row.closed) && (!row.closed.pane || !row.pane || row.closed.pane === row.pane));

export function taskStatusText(lang, row) {
  if (row.cleanup) return word(lang, 'cleanup');
  if (disconnected(row)) return word(lang, isClosedTask(row) ? 'closedReattach' : 'disconnected');
  // Answered (pm.py's `answered`): it waits for the PM now, not for the user.
  if (row.status === 'blocked') return word(lang, row.answered ? 'answered' : 'blockedWaiting');
  if (row.status === 'review' && isClosedTask(row)) return word(lang, 'reviewClosed');
  if (['review', 'paused', 'proposed', 'done', 'merged', 'released', 'abandoned', 'cancelled'].includes(row.status)) return label(lang, row.status);
  return row.live === 'working' ? word(lang, 'workingNow') : label(lang, row.status);
}

export function lostSummary(lang, lost) {
  if (!lost || typeof lost !== 'object') return '';
  const hasPm = Boolean(lost.pm && typeof lost.pm === 'object');
  const n = Array.isArray(lost.threads) ? lost.threads.length : 0;
  if (!hasPm && !n) return '';
  const restart = Boolean(lost.restart);
  if (lang === 'zh') {
    if (hasPm && n) return restart ? `重启后 PM 和 ${n} 个 agent 没回来` : `PM 和 ${n} 个 agent 停了`;
    if (hasPm) return restart ? '重启后 PM 没回来' : 'PM 停了';
    return restart ? `重启后 ${n} 个 agent 没回来` : `${n} 个 agent 停了`;
  }
  const agentsWord = n === 1 ? '1 agent' : `${n} agents`;
  if (hasPm && n) return restart ? `PM and ${agentsWord} did not come back` : `PM and ${agentsWord} stopped`;
  if (hasPm) return restart ? 'PM did not come back' : 'PM stopped';
  return restart ? `${agentsWord} did not come back` : `${agentsWord} stopped`;
}

// What waits undelivered for a project's PM (`pm.py state` pms[].undelivered): the events of a batch
// (`count`) and the messages past their delivery SLA (`messages`, the alert.undelivered route's hub
// outlet), which may be there with no batch at all (`count` 0).
export function undeliveredSummary(lang, undelivered) {
  if (!undelivered || typeof undelivered !== 'object') return '';
  const count = (Number(undelivered.count) || 0) + (Number(undelivered.messages) || 0);
  if (count <= 0) return '';
  const secs = Math.max(60, Number(undelivered.waiting_seconds) || 0);
  const dur = age(secs * 1000, lang);
  return lang === 'zh' ? `${count} 条未送达（${dur}）` : `${count} undelivered (${dur})`;
}

// Task numbers (`#42`) assigned per project; absent on review threads and older remote peers.
// pm-project and pm-dash keep identical copies of `taskNumber` and `formatTaskNumber`.
export function taskNumber(value) {
  const raw = value && typeof value === 'object' ? (value.number ?? value.num) : value;
  return Number.isInteger(raw) && raw > 0 ? raw : null;
}

export function formatTaskNumber(value) {
  const num = taskNumber(value);
  return num ? `#${num}` : '';
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
// Prefer floating beside the row (left, then right) so adjacent rows in the
// vertical task list stay uncovered and reachable; fall back above/below only
// when neither horizontal side fits, still avoiding neighbor rows when possible.
export function hoverCardPosition(row, stageHeight, viewport, height, scale = 1, options = {}) {
  const top = Math.max(0, viewport.top), stageBottom = Math.min(stageHeight, viewport.bottom);
  if (!(height > 0) || row.y + row.h <= top || row.y >= stageBottom) return null;
  const gap = 6 * scale;
  const minW = options.minWidth ?? 200 * scale;
  const maxSideW = options.maxSideWidth ?? 400 * scale;
  const maxW = options.maxWidth ?? 520 * scale;
  const minH = Math.max(0, options.minHeight ?? 0);
  // A short 1-task stage may be shorter than one card while the scroll viewport has plenty of room.
  const sideBottom = stageBottom - top >= height ? stageBottom
    : Math.min(viewport.bottom, Math.max(stageBottom, top + height));
  const sideSpan = sideBottom - top;
  const leftEdge = Math.max(0, viewport.left ?? 0);
  const anchorX = options.columnX ?? row.x;
  const leftW = anchorX - gap - leftEdge;
  if (leftW >= minW && sideSpan > 0 && sideSpan >= minH) {
    const w = Math.min(maxSideW, leftW), h = Math.min(height, sideSpan);
    const y = Math.max(top, Math.min(row.y, sideBottom - h));
    return { x: anchorX - gap - w, y, w, h, side: 'left' };
  }
  const stageW = options.stageWidth ?? Math.max(row.x + row.w, viewport.right ?? 0);
  const rightEdge = viewport.right !== undefined ? Math.min(stageW, viewport.right) : stageW;
  const rightW = rightEdge - (row.x + row.w) - gap;
  if (rightW >= minW && sideSpan > 0 && sideSpan >= minH) {
    const w = Math.min(maxSideW, rightW), h = Math.min(height, sideSpan);
    const y = Math.max(top, Math.min(row.y, sideBottom - h));
    return { x: row.x + row.w + gap, y, w, h, side: 'right' };
  }
  const w = Math.min(maxW, row.w);
  if (w <= 0) return null;
  const vpBelow = Math.max(0, stageBottom - row.y - row.h - gap);
  const vpAbove = Math.max(0, row.y - gap - top);
  let clearBelow = vpBelow, clearAbove = vpAbove;
  if (Array.isArray(options.rows)) {
    for (const other of options.rows) {
      if (!other || other === row || (row.id && other.id === row.id) || !(other.h > 0)) continue;
      if (other.x + other.w <= row.x || other.x >= row.x + w) continue;
      if (other.y >= row.y + row.h) clearBelow = Math.min(clearBelow, Math.max(0, other.y - row.y - row.h - gap * 2));
      else if (other.y + other.h <= row.y) clearAbove = Math.min(clearAbove, Math.max(0, row.y - other.y - other.h - gap * 2));
    }
  }
  const canClear = clearBelow >= height || clearAbove >= height ||
    ((clearBelow > 0 || clearAbove > 0) && Math.max(clearBelow, clearAbove) >= minH && minH > 0);
  const below = canClear ? clearBelow : vpBelow;
  const above = canClear ? clearAbove : vpAbove;
  const up = below < height && (above >= height || above > below);
  const h = Math.min(height, up ? above : below);
  return h > 0 && h >= minH ? { x: row.x, y: up ? row.y - gap - h : row.y + row.h + gap,
    w, h, side: up ? 'above' : 'below' } : null;
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
  const totals = { projects: 0, working: 0, waiting: 0, review: 0, proposed: 0, merged_today: 0, unclaimed_blocked: 0 };
  let hasCounts = false;
  for (const [machine, state] of [['', local], ...Object.entries(remote).filter(([name]) => name)]) {
    if (!state || !['pms', 'tasks', 'events'].every(k => Array.isArray(state[k]))) continue;
    const key = value => machine ? `${machine}/${value || ''}` : value || '';
    // A review thread is shown as the task it reviews (foldReviews): its reports reach that task, as what
    // the review says, never as the task's own status (a review's done is not the task's).
    const tasks = foldReviews(state.tasks);
    const into = new Map(tasks.filter(t => t.review).map(t => [t.review.id, t.id]));
    const asReview = e => !into.has(e.task) ? e : { ...e, status: '', review: e.status && e.status !== 'in_progress' ? 'reviewed' : 'review',
      text: String(e.text || '').replace(/^status=\w+;?\s*/, '') };
    const c = state.counts;
    if (c && Number.isFinite(c.working) && Number.isFinite(c.waiting) && Number.isFinite(c.unclaimed_blocked)) {
      hasCounts = true;
      totals.projects += Number.isFinite(c.projects) ? c.projects : state.pms.filter(p => !p?.archived).length;
      totals.working += c.working;
      totals.waiting += c.waiting;
      totals.review += Number.isFinite(c.review) ? c.review : 0;
      totals.proposed += Number.isFinite(c.proposed) ? c.proposed : 0;
      totals.merged_today += Number.isFinite(c.merged_today) ? c.merged_today : 0;
      totals.unclaimed_blocked += c.unclaimed_blocked;
    } else {
      const activePms = state.pms.filter(p => !p?.archived);
      const allPmNames = new Set(state.pms.map(p => p?.name).filter(Boolean));
      totals.projects += activePms.length;
      for (const pm of activePms) {
        const pc = projectCounts(pm, tasks);
        totals.working += pc.working;
        totals.waiting += pc.waiting;
        totals.review += pc.review;
        totals.proposed += pc.proposed;
        totals.merged_today += pc.merged_today;
      }
      totals.unclaimed_blocked += tasks.filter(t => (!t?.pm || !allPmNames.has(t.pm)) && t.status === 'blocked' && !t.answered).length;
    }
    merged.pms.push(...state.pms.map(p => ({ ...p, machine, sourceName: p.name, name: key(p.name) })));
    merged.tasks.push(...tasks.map(t => ({ ...t, machine, sourceId: t.id, sourcePm: t.pm,
      id: key(t.id), pm: key(t.pm) })));
    merged.events.push(...state.events.map(asReview).map(e => ({ ...e, machine, key: key(e.key),
      pm: key(e.pm), task: e.task ? key(into.get(e.task) || e.task) : '' })));
  }
  if (hasCounts) merged.counts = totals;
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
// follows in a bundle of its own. Reviewing and answered tasks stay in the Working ('in_progress')
// bundle, sorted post-gate -> review -> answered -> in_progress (newest updated first inside each).
// Ended tasks fold into one node; abandoned ones (and cancelled) hide behind it.
export const BUNDLES = ['blocked', 'in_progress', 'proposed', 'paused'];
export const ENDED = ['done', 'merged', 'released'];
export const DROPPED = ['abandoned', 'cancelled'];
const newestFirst = (a, b) => String(b.updated || '').localeCompare(String(a.updated || ''));
const bundleRank = status => BUNDLES.includes(status) ? BUNDLES.indexOf(status) : BUNDLES.length;
const workingSubRank = task => {
  if (isPostGateTask(task)) return 0;
  if (task?.status === 'review') return 1;
  if (task?.status === 'blocked' && task?.answered) return 2;
  return 3;
};

// Stable throughout: urgency then newest-first within Working, ledger order within other bundles,
// and among ended tasks of the same minute.
export function boardGroups(tasks) {
  const bundles = [], ended = [], dropped = [];
  for (const task of tasks) {
    if (ENDED.includes(task.status)) ended.push(task);
    else if (DROPPED.includes(task.status)) dropped.push(task);
    else {
      const rawStatus = task.status || '';
      const status = rawStatus === 'review' || (rawStatus === 'blocked' && task.answered) ? 'in_progress' : rawStatus;
      let bundle = bundles.find(b => b.status === status);
      if (!bundle) bundles.push(bundle = { status, tasks: [] });
      bundle.tasks.push(task);
    }
  }
  const working = bundles.find(b => b.status === 'in_progress');
  if (working) working.tasks.sort((a, b) => workingSubRank(a) - workingSubRank(b) || newestFirst(a, b));
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

// Unified overview/board counts using pm.py's definitions:
// - waiting ("等你"): claimed by an active PM, blocked and not answered (review does not count).
// - running ("在干活"): claimed by an active PM, in progress and terminal not offline.
// - unclaimed ("没人认领的阻塞"): blocked and not answered with no registered PM; tracked separately.
// Prefers `state.counts` (and per-PM `pm.counts`) from pm.py, falling back to folded tasks for older pm.py.
export function counts(state) {
  const pms = Array.isArray(state?.pms) ? state.pms : [];
  const activePms = pms.filter(p => !p?.archived);
  const allPmNames = new Set(pms.map(p => p?.name).filter(Boolean));
  const tasks = foldReviews(state?.tasks);
  const c = state?.counts;
  const hasStateCounts = Boolean(c && Number.isFinite(c.working) && Number.isFinite(c.waiting) && Number.isFinite(c.unclaimed_blocked));
  let running = 0, review = 0, waiting = 0, unclaimed = 0;
  const waitingByPm = [];
  for (const pm of activePms) {
    const pc = projectCounts(pm, tasks);
    running += pc.working;
    review += pc.review;
    waiting += pc.waiting;
    if (pc.waiting > 0) {
      waitingByPm.push({ name: pm.project || (pm.sourceName ?? pm.name) || word(state?.lang, 'unassigned'), count: pc.waiting });
    }
  }
  if (hasStateCounts) {
    running = c.working;
    waiting = c.waiting;
    review = Number.isFinite(c.review) ? c.review : review;
    unclaimed = c.unclaimed_blocked;
  } else {
    unclaimed = tasks.filter(t => (!t?.pm || !allPmNames.has(t.pm)) && t.status === 'blocked' && !t.answered).length;
  }
  const blocked = waiting;
  const conclusion = word(state?.lang, 'conclusion', waitingByPm.map(({ name, count }) => word(state?.lang, 'waitingForProject', name, count)));
  return { running, review, blocked, waiting, unclaimed, conclusion };
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

// A PM's activity never makes a different worker's wire active.
export function wireFlows(wire, rows) {
  // A bundle's trunk flows while any of its tasks does; the ended node's line never does.
  if (wire.members) return wire.members.some(id => wireFlows({ to: id }, rows));
  const target = rows.find(row => row.id === wire.to);
  if (!target || target.live !== 'working') return false;
  return target.type === 'pm' || (target.type === 'task' &&
    !['paused', 'proposed', 'done', 'merged', 'released', 'abandoned', 'cancelled'].includes(target.status));
}

// True when a task in review has a live reviewer actively working right now.
// Stays false while waiting for PM verdict (no active review thread, or review already ended/done),
// when the reviewer is offline/idle/blocked/paused/proposed, or when the task is not in review.
export function reviewWorking(task, terms = [], live = []) {
  if (!task || typeof task !== 'object' || task.cleanup) return false;
  if (task.status !== 'review') return false;
  const r = task.review;
  if (!r || typeof r !== 'object' || !r.id) return false;
  if (r.status !== 'in_progress' || r.offline) return false;
  const rRow = {
    type: 'task',
    task: r.id,
    sourceId: r.sourceId ?? r.id,
    pane: r.pane,
    machine: r.machine ?? task.machine ?? '',
  };
  const rTerm = terminalFor(rRow, terms || []);
  if (rTerm) {
    const status = (live || []).find(a => a.address === rTerm.address)?.status || rTerm.status;
    return status === 'working';
  }
  return r.worker === 'working';
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
  const tasks = state.tasks.filter(t => mine(t.pm));
  const events = state.events.filter(e => mine(e.pm));
  const out = { ...state, project, pms, tasks, events };
  if (project) {
    if (pms.length === 1 && pms[0]?.counts && typeof pms[0].counts === 'object') {
      out.counts = { projects: 1, ...projectCounts(pms[0], tasks), unclaimed_blocked: 0 };
    } else {
      delete out.counts;
    }
  }
  return out;
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
    ...(!pm.archived && pm.lost && typeof pm.lost === 'object' ? { lost: pm.lost } : {}),
    ...(!pm.archived && pm.undelivered && typeof pm.undelivered === 'object' ? { undelivered: pm.undelivered } : {}),
    at: lastEventAt(state.events, pm.name), line: lines[pm.name] || [],
    paused: state.tasks.filter(t => (t.pm || '') === pm.name && t.status === 'paused').map(t => t.title || t.sourceId || t.id),
  }));
  return { active: cards.filter(c => !c.archived).sort((a, b) => b.at - a.at || a.name.localeCompare(b.name)),
    archived: cards.filter(c => c.archived).sort((a, b) => String(b.archived).localeCompare(String(a.archived))) };
}
// Blocked tasks with no registered PM: not counted in "waiting for you", shown separately in the overview.
export function unclaimedBlocked(state) {
  const pmNames = new Set((Array.isArray(state?.pms) ? state.pms : []).map(p => p?.name).filter(Boolean));
  const tasks = foldReviews(state?.tasks).filter(t => (!t?.pm || !pmNames.has(t.pm)) && t.status === 'blocked' && !t.answered);
  const count = Number.isFinite(state?.counts?.unclaimed_blocked) ? state.counts.unclaimed_blocked : tasks.length;
  return { count, tasks };
}
export function pageTotals(cards, state = null) {
  const c = state?.counts;
  const projects = Number.isFinite(c?.projects) ? c.projects : cards.length;
  const working = Number.isFinite(c?.working) ? c.working : cards.reduce((n, card) => n + card.counts.working, 0);
  const waiting = Number.isFinite(c?.waiting) ? c.waiting : cards.reduce((n, card) => n + card.counts.waiting, 0);
  return state ? { projects, working, waiting, unclaimed: unclaimedBlocked(state).count } : { projects, working, waiting };
}

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

// ---- Two-layer prompt-driven task plan (`task.plan` + `task.subplan`) ----------------------

export function inferStepAnchor(text) {
  const raw = String(text || '').trim();
  if (!raw) return 'custom';
  const tags = raw.match(/(?:^|\s)@(work|review|merge|custom|none)(?=\s|$)/gi);
  if (tags) {
    const k = tags[tags.length - 1].trim().slice(1).toLowerCase();
    return k === 'none' ? 'custom' : k;
  }
  const negReviewRe = /(?:免|不|无需|不用|不做|跳过|无)(?:代码)?(?:审查|评审|复审|review)|\b(?:no|without|skip(?:ping)?)\s+(?:code\s+)?reviews?\b/i;
  const userSignoffRe = /(?:等你|用户|待你)(?:审查|审阅|确认|验收)|(?:和|与|给)用户|\b(?:your|user|human)\s+(?:review|sign-?off|approval|check)\b|\bwith\s+(?:the\s+)?(?:user|you|human)\b/i;
  const reviewHeadRe = /^\s*(?:(?:独立\s*)?(?:代码\s*)?(?:审查|复审|评审)|送审|(?:independent\s+)?(?:code\s+)?(?:re-?)?review(?:ing)?(?![a-z]))/i;
  const negMergeRe = /(?:不|无需|不用|暂不|先不|免)(?:合入|合并|合进|合到|合\s*(?:main|master|主分支|主线)|land)|\b(?:no|without|don'?t|do\s+not|not|skip(?:ping)?)\s+(?:code\s+)?(?:merge|land)(?:ing)?\b/gi;
  const mergeAnchorRe = /合进|合入|合到|合\s*(?:main|master|主分支|主线)|合并(?:进|入|到|\s*(?:main|master|主分支|主线|分支)|$)|(?:^|[^a-z])(?:pm\.py\s+)?land(?:\s+(?:to|into|on|in|branch|main|master)\b|\s*$)|(?:^|[^a-z])merge(?:\s+(?:to|into|with|branch|main|master|pr)\b|\s*$)/i;
  const coreWorkRe = /实现|开发|编码|修复|重构|调研|设计|翻译|\b(?:implement\w*|develop\w*|refactor\w*|research\w*|design\w*|translat\w*)\b/i;
  const customPostRe = /安装|装到|部署|发布|挂分支|待验收|等你|审阅|\b(?:install\w*|deploy\w*|release\w*|hold\w*|await\w*|sign-?off)\b/i;
  const workAnchorRe = /实现|开发|编写|编码|修复|改造|重构|调研|设计|出稿|交互稿|翻译|译为|修改|改动|调整|补充|补齐|盘点|迁移|优化|执行任务|\b(?:implement\w*|develop\w*|build\w*|code|coding|fix\w*|refactor\w*|research\w*|design\w*|translat\w*|modif\w*|updat\w*|migrat\w*|optimi[sz]\w*|patch\w*|writ(?:e|ing)|draft\w*)\b/i;

  const reviewMatch = reviewHeadRe.exec(raw);
  if (reviewMatch && !negReviewRe.test(raw) && !userSignoffRe.test(raw)) {
    const tail = raw.slice(reviewMatch[0].length);
    if (!workAnchorRe.test(tail) && !mergeAnchorRe.test(tail.replace(negMergeRe, ' '))) return 'review';
  }
  const mergeClean = raw.replace(negMergeRe, ' ');
  if (mergeAnchorRe.test(mergeClean)) return 'merge';
  if (customPostRe.test(raw) && !coreWorkRe.test(raw)) return 'custom';
  if (workAnchorRe.test(raw)) return 'work';
  return 'custom';
}

export function parsePlanItems(raw) {
  if (!raw) return [];
  let items;
  if (typeof raw === 'string') {
    items = raw.split(/[\n;；]/).map(s => s.trim()).filter(Boolean);
  } else if (Array.isArray(raw)) {
    items = raw;
  } else if (typeof raw === 'object') {
    items = Array.isArray(raw.steps) ? raw.steps : Array.isArray(raw.items) ? raw.items : [];
  } else {
    return [];
  }
  const normState = (v, doneFlag) => {
    if (doneFlag === true) return 'done';
    const s = String(v || '').trim().toLowerCase();
    if (['done', 'completed', 'checked', 'x'].includes(s)) return 'done';
    if (['doing', 'in_progress', 'active', 'running', 'working', '>'].includes(s)) return 'doing';
    if (['todo', 'pending', 'open'].includes(s)) return 'todo';
    return '';
  };
  const normAnchor = v => {
    const s = String(v || '').trim().toLowerCase().replace(/^@/, '');
    if (['work', 'impl', 'execute', 'exec'].includes(s)) return 'work';
    if (s === 'review') return 'review';
    if (['merge', 'land'].includes(s)) return 'merge';
    if (s === 'custom' || s === 'none') return 'custom';
    return '';
  };
  const out = [];
  for (const item of items) {
    if (item == null) continue;
    let isObject = false;
    let text = '';
    let state = '';
    let explicitState = false;
    let explicitAnchor = '';
    let right = '';
    let at = '';
    let commit = '';
    let round = 0;
    if (typeof item === 'string') {
      text = item.trim().replace(/^(?:[-*+]|\d+[.)])\s+/, '');
    } else if (typeof item === 'object' && !Array.isArray(item)) {
      isObject = true;
      text = String(item.text ?? item.title ?? item.label ?? item.name ?? '').trim();
      const st = normState(item.state ?? item.status, item.done);
      if (st) { state = st; explicitState = true; }
      explicitAnchor = normAnchor(item.anchor ?? item.role ?? item.kind ?? item.tag);
      right = String(item.right || '');
      at = String(item.at || '');
      commit = String(item.commit || '');
      if (Number.isFinite(Number(item.round)) && Number(item.round) > 0) round = Math.floor(Number(item.round));
    } else {
      continue;
    }
    const prefix = /^\s*(?:\[([^\]]*)\]|([✓✔◌○]))\s*(.*)$/.exec(text);
    if (prefix) {
      const mark = (prefix[1] != null ? prefix[1] : prefix[2]).trim().toLowerCase();
      if (!explicitState) {
        if (['x', '✓', '✔'].includes(mark)) { state = 'done'; explicitState = true; }
        else if (['>', '*', '~', '◌'].includes(mark)) { state = 'doing'; explicitState = true; }
        else if (mark === '' || mark === '○') { state = 'todo'; explicitState = true; }
      }
      text = prefix[3].trim();
    }
    const tagRe = /(?:^|\s)@(work|review|merge|custom|none)(?=\s|$)/gi;
    let foundTag = '';
    text = text.replace(tagRe, (_, k) => { foundTag = k.toLowerCase(); return ' '; }).replace(/\s+/g, ' ').trim();
    if (!explicitAnchor && foundTag) explicitAnchor = normAnchor(foundTag);
    if (!text && foundTag) {
      text = { work: 'Work', review: 'Review', merge: 'Merge', custom: 'Step' }[foundTag] || '';
    }
    if (!text) continue;
    out.push({
      text,
      state: state || 'todo',
      explicitState,
      anchor: explicitAnchor || (isObject ? 'custom' : inferStepAnchor(text)),
      explicitAnchor: Boolean(explicitAnchor),
      right,
      at,
      commit,
      round,
    });
  }
  return out;
}

export function taskSteps(task, { lang = 'en' } = {}) {
  const summarizeStep = raw => {
    const src = String(raw || '').trim();
    const notes = [];
    const stripped = src.replace(/（([^）]*)）|\(([^)]*)\)/g, (_, zhNote, enNote) => {
      const n = String(zhNote ?? enNote ?? '').trim();
      if (n) notes.push(n);
      return '';
    });
    const core = stripped.replace(/\s+/g, ' ').trim() || src;
    let units = 0;
    let cut = '';
    let clipped = false;
    for (const ch of core) {
      const w = ch.codePointAt(0) > 255 ? 2 : 1;
      if (units + w > STEP_LABEL_UNITS) { clipped = true; break; }
      cut += ch;
      units += w;
    }
    const shortText = clipped ? `${cut.trimEnd()}…` : core;
    const note = notes.join(' · ');
    const tip = shortText !== src ? src : '';
    return { shortText, note, tip };
  };
  const outer = parsePlanItems(task?.plan);
  const sub = parsePlanItems(task?.subplan);
  const status = String(task?.status || '');
  const rawRounds = Math.max(0, Number(task?.rounds) || 0, Array.isArray(task?.review_history) ? task.review_history.length : 0);
  const hasPlan = outer.length > 0;
  const hasSubplan = sub.length > 0;
  const substeps = sub.map((s, index) => ({ index, text: s.text, ...summarizeStep(s.text), state: s.state }));

  let steps;
  if (!hasPlan) {
    const hadReview = status === 'review' || Boolean(task?.review) || rawRounds > 0 ||
      (Array.isArray(task?.log) && task.log.some(e => /\bstatus=review\b/.test(String(e?.text || ''))));
    const templates = hadReview
      ? [
          { text: word(lang, 'planFallbackWork'), anchor: 'work' },
          { text: word(lang, 'planFallbackReview'), anchor: 'review' },
          { text: word(lang, 'planFallbackDone'), anchor: 'custom' },
        ]
      : [
          { text: word(lang, 'planFallbackWork'), anchor: 'work' },
          { text: word(lang, 'planFallbackDone'), anchor: 'custom' },
        ];
    const doneReview = Boolean(task?.review && ['done', 'merged', 'released'].includes(task.review.status));
    steps = templates.map((tpl, index) => {
      let state = 'todo';
      if (['done', 'released', 'merged'].includes(status)) {
        state = 'done';
      } else if (['abandoned', 'cancelled', 'proposed'].includes(status)) {
        state = 'todo';
      } else if (status === 'review') {
        state = tpl.anchor === 'work' ? 'done' : tpl.anchor === 'review' ? 'doing' : 'todo';
      } else if (status === 'paused') {
        if (hadReview && doneReview) state = tpl.anchor === 'work' || tpl.anchor === 'review' ? 'done' : 'todo';
        else state = tpl.anchor === 'work' ? 'doing' : 'todo';
      } else {
        state = tpl.anchor === 'work' ? 'doing' : 'todo';
      }
      return {
        index,
        text: tpl.text,
        ...summarizeStep(tpl.text),
        state,
        anchor: tpl.anchor,
        right: '',
        at: '',
        commit: '',
        round: 0,
        substeps: null,
        subProgress: null,
      };
    });
    if (['done', 'released', 'merged', 'review'].includes(status)) {
      for (const s of substeps) if (s.state === 'doing') s.state = 'done';
    } else if (['abandoned', 'cancelled', 'proposed'].includes(status)) {
      for (const s of substeps) if (s.state === 'doing') s.state = 'todo';
    }
  } else {
    steps = outer.map((item, index) => ({
      index,
      text: item.text,
      ...summarizeStep(item.text),
      state: item.state,
      anchor: item.anchor,
      right: item.right,
      at: item.at,
      commit: item.commit,
      round: item.round,
      substeps: null,
      subProgress: null,
    }));
    const closeDoingSub = () => {
      for (const s of substeps) if (s.state === 'doing') s.state = 'done';
    };
    if (['done', 'released'].includes(status)) {
      for (const s of steps) s.state = 'done';
      closeDoingSub();
    } else if (['abandoned', 'cancelled'].includes(status)) {
      for (const s of steps) if (s.state === 'doing') s.state = 'todo';
      for (const s of substeps) if (s.state === 'doing') s.state = 'todo';
    } else if (status === 'proposed') {
      for (const s of steps) if (s.state === 'doing') s.state = 'todo';
      for (const s of substeps) if (s.state === 'doing') s.state = 'todo';
    } else if (status === 'paused') {
      // Preserve recorded step states while paused.
    } else if (status === 'merged' || (status === 'in_progress' && Boolean(task?.landed || task?.merged_at))) {
      closeDoingSub();
      let mi = -1;
      for (let i = steps.length - 1; i >= 0; i--) if (steps[i].anchor === 'merge') { mi = i; break; }
      if (mi >= 0) {
        for (let i = 0; i <= mi; i++) steps[i].state = 'done';
        const nextIdx = steps.findIndex((s, i) => i > mi && s.state !== 'done');
        for (let i = mi + 1; i < steps.length; i++) {
          if (i === nextIdx) steps[i].state = 'doing';
          else if (steps[i].state === 'doing') steps[i].state = 'todo';
        }
      } else if (status === 'merged') {
        for (const s of steps) s.state = 'done';
      }
    } else if (status === 'review') {
      closeDoingSub();
      let ri = steps.findIndex(s => s.anchor === 'review' && s.state !== 'done');
      if (ri < 0) {
        for (let i = steps.length - 1; i >= 0; i--) if (steps[i].anchor === 'review') { ri = i; break; }
      }
      if (ri >= 0) {
        for (let i = 0; i < ri; i++) steps[i].state = 'done';
        steps[ri].state = 'doing';
        for (let i = ri + 1; i < steps.length; i++) if (steps[i].state === 'doing') steps[i].state = 'todo';
      } else {
        let wi = steps.findIndex(s => s.state === 'doing');
        if (wi < 0) wi = steps.findIndex(s => s.anchor === 'work' && s.state !== 'done');
        if (wi < 0) {
          for (let i = steps.length - 1; i >= 0; i--) if (steps[i].anchor === 'work') { wi = i; break; }
        }
        if (wi >= 0 && wi < steps.length - 1) {
          for (let i = 0; i <= wi; i++) steps[i].state = 'done';
          const nextIdx = steps.findIndex((s, i) => i > wi && s.state !== 'done');
          for (let i = wi + 1; i < steps.length; i++) {
            if (i === nextIdx) steps[i].state = 'doing';
            else if (steps[i].state === 'doing') steps[i].state = 'todo';
          }
        } else if (wi >= 0) {
          for (let i = 0; i < wi; i++) steps[i].state = 'done';
          steps[wi].state = 'doing';
        }
      }
    } else {
      // in_progress or blocked
      let di = steps.findIndex(s => s.state === 'doing');
      const unansweredBlocked = status === 'blocked' && !task?.answered;
      const reviewLive = Boolean(task?.review && !['done', 'merged', 'released', 'abandoned', 'cancelled', 'paused', 'proposed'].includes(task.review.status));
      if (di >= 0 && steps[di].anchor === 'review' && !reviewLive) {
        steps[di].state = 'todo';
        let wi = -1;
        for (let i = di - 1; i >= 0; i--) if (steps[i].anchor === 'work') { wi = i; break; }
        if (wi < 0 && di > 0) wi = 0;
        if (wi >= 0 && !(unansweredBlocked && steps[wi].state === 'done')) {
          steps[wi].state = 'doing';
          di = wi;
        } else {
          di = -1;
        }
      }
      if (di < 0) {
        let mergeDone = -1;
        for (let i = steps.length - 1; i >= 0; i--) {
          if (steps[i].anchor === 'merge' && steps[i].state === 'done') { mergeDone = i; break; }
        }
        if (mergeDone >= 0) {
          const next = steps.findIndex((s, i) => i > mergeDone && s.state === 'todo');
          if (next >= 0 && !(unansweredBlocked && steps[next].anchor === 'review' && !reviewLive)) {
            steps[next].state = 'doing';
          }
        } else {
          const workTodo = steps.findIndex(s => s.anchor === 'work' && s.state === 'todo');
          const anyTodo = steps.findIndex(s => s.state === 'todo');
          const pick = workTodo >= 0 ? workTodo : anyTodo;
          if (pick >= 0 && !(unansweredBlocked && steps[pick].anchor === 'review' && !reviewLive)) {
            steps[pick].state = 'doing';
          }
        }
      }
    }
  }

  const isOpenActive = !['done', 'merged', 'released', 'abandoned', 'cancelled', 'paused', 'proposed'].includes(status) &&
    !(status === 'blocked' && !task?.answered);
  const activeIndex = steps.findIndex(s => s.state === 'doing');
  const active = activeIndex >= 0 ? steps[activeIndex] : null;
  const hasPriorDoneMerge = activeIndex > 0 && steps.slice(0, activeIndex).some(s => s.anchor === 'merge' && s.state === 'done');
  const hasPriorDoneReviewNoMoreGates = activeIndex > 0 &&
    steps.slice(0, activeIndex).some(s => s.anchor === 'review' && s.state === 'done') &&
    !steps.slice(activeIndex).some(s => s.anchor === 'work' || s.anchor === 'review' || s.anchor === 'merge');
  const postGate = Boolean(hasPlan && isOpenActive && active && active.anchor === 'custom' &&
    (hasPriorDoneMerge || hasPriorDoneReviewNoMoreGates));

  const reviewOpen = status === 'review' ||
    Boolean(task?.review && !['done', 'merged', 'released', 'abandoned', 'cancelled', 'paused', 'proposed'].includes(task.review.status));
  const pastReview = postGate || steps.some(s => s.anchor === 'merge' && s.state === 'done') ||
    (steps.some(s => s.anchor === 'review' && s.state === 'done') && !steps.some(s => s.anchor === 'review' && s.state !== 'done'));
  let round = 0;
  let foldedRounds = 0;
  if (reviewOpen) {
    round = Math.max(1, rawRounds);
    foldedRounds = round > 1 ? round - 1 : 0;
  } else if (['in_progress', 'blocked'].includes(status) && !pastReview && rawRounds >= 1) {
    round = rawRounds + 1;
    foldedRounds = rawRounds;
  } else {
    round = 0;
    foldedRounds = rawRounds > 1 ? rawRounds - 1 : 0;
  }
  const foldedLabel = foldedRounds > 0 ? word(lang, 'planFoldedRounds', foldedRounds) : '';
  if (active && round > 1 && (active.anchor === 'review' || active.anchor === 'work')) {
    active.round = round;
  }

  let attachedSubsteps = [];
  if (hasSubplan && steps.length) {
    let attachIdx = -1;
    if (active && active.anchor === 'work') attachIdx = activeIndex;
    else if (active && active.anchor !== 'review' && active.anchor !== 'merge' && !postGate && !steps.some(s => s.anchor === 'work')) {
      attachIdx = activeIndex;
    } else {
      const bound = activeIndex >= 0 ? activeIndex : steps.length;
      for (let i = bound - 1; i >= 0; i--) if (steps[i].anchor === 'work' && steps[i].state === 'done') { attachIdx = i; break; }
      if (attachIdx < 0) for (let i = steps.length - 1; i >= 0; i--) if (steps[i].anchor === 'work' && steps[i].state === 'done') { attachIdx = i; break; }
      if (attachIdx < 0) for (let i = bound - 1; i >= 0; i--) if (steps[i].state === 'done') { attachIdx = i; break; }
      if (attachIdx < 0) attachIdx = steps.findIndex(s => s.anchor === 'work');
      if (attachIdx < 0) attachIdx = 0;
    }
    const subDone = substeps.filter(s => s.state === 'done').length;
    steps[attachIdx].substeps = substeps;
    steps[attachIdx].subProgress = { done: subDone, total: substeps.length };
    attachedSubsteps = substeps;
  }

  const done = steps.filter(s => s.state === 'done').length;
  const total = steps.length;
  const progress = total ? `${done}/${total}` : '';
  const pill = !hasPlan ? '' : postGate && active ? word(lang, 'planPostStep', done, total, active.shortText) : progress;
  const activeSubstep = attachedSubsteps.find(s => s.state === 'doing') || null;
  const noReview = Boolean(task?.no_review) || (hasPlan && !steps.some(s => s.anchor === 'review'));
  const autoReview = !noReview && task?.auto_review !== false && hasPlan && steps.some(s => s.anchor === 'review');
  const rail = [
    ...(foldedRounds > 0 ? [{ kind: 'folded', state: 'done', text: foldedLabel }] : []),
    ...steps.map(s => ({ kind: 'step', state: s.state, text: s.shortText, anchor: s.anchor, round: s.round })),
  ];
  return {
    hasPlan,
    hasSubplan,
    done,
    total,
    progress,
    pill,
    postGate,
    activeIndex,
    activeStep: active,
    activeSubstep,
    round,
    foldedRounds,
    foldedLabel,
    noReview,
    autoReview,
    paused: status === 'paused',
    steps,
    rail,
  };
}

export function isPostGateTask(task) {
  if (!task?.plan) return false;
  return taskSteps(task).postGate;
}

export function taskDependencies(task, allTasks = [], { terms = [], live = [] } = {}) {
  const rawList = Array.isArray(task?.deps) && task.deps.length
    ? task.deps
    : (Array.isArray(task?.depends_on) ? task.depends_on.map(id => ({ id })) : []);
  if (!rawList.length) return null;
  const list = Array.isArray(allTasks) ? allTasks : [];
  const taskMachine = task?.machine || '';
  const findTarget = depId => {
    const namespaced = taskMachine ? `${taskMachine}/${depId}` : depId;
    return list.find(t => t && (t.id === depId || t.id === namespaced ||
      ((t.machine || '') === taskMachine && t.sourceId === depId))) || null;
  };
  const items = [];
  for (const raw of rawList) {
    const depId = typeof raw === 'string' ? raw.trim() : String(raw?.id || '').trim();
    if (!depId) continue;
    const entry = typeof raw === 'object' && raw ? raw : { id: depId };
    const target = findTarget(depId);
    const status = String(target?.status || entry.status || 'missing');
    let state;
    if (target) {
      if (['merged', 'done', 'released'].includes(status) || Boolean(target.landed)) state = 'met';
      else if (['abandoned', 'cancelled'].includes(status)) state = 'abandoned';
      else state = 'waiting';
    } else if (['met', 'waiting', 'abandoned', 'missing'].includes(entry.state)) {
      state = entry.state;
    } else {
      state = 'missing';
    }
    const isMet = state === 'met';
    const isBroken = state === 'abandoned' || state === 'missing';
    const isReview = !isMet && !isBroken && status === 'review';
    const isReviewWorking = isReview && target ? reviewWorking(target, terms, live) : false;
    const isBlocked = !isMet && !isBroken && status === 'blocked' && !target?.answered;
    const isWorking = !isMet && !isBroken && !target?.offline &&
      (status === 'in_progress' || (status === 'blocked' && Boolean(target?.answered)));
    items.push({
      id: depId,
      targetId: target?.id || (taskMachine ? `${taskMachine}/${depId}` : depId),
      sourceId: target?.sourceId || depId,
      pm: target?.pm || task?.pm || '',
      sourcePm: target?.sourcePm || task?.sourcePm || '',
      machine: target?.machine ?? taskMachine,
      title: String(target?.title || entry.title || depId),
      state,
      status,
      isMet,
      isBroken,
      isReview,
      isReviewWorking,
      isBlocked,
      isWorking,
      clickable: state !== 'missing',
    });
  }
  if (!items.length) return null;
  const metCount = items.filter(i => i.isMet).length;
  const total = items.length;
  const allMet = metCount === total;
  const ready = Boolean(task?.status === 'proposed' && allMet);
  return {
    hasDeps: true,
    showAsWaiting: task?.status === 'proposed',
    items,
    metCount,
    total,
    progress: `${metCount}/${total}`,
    allMet,
    ready,
    broken: items.some(i => i.isBroken),
  };
}

// ---- Bounded hover tooltips (max width, CJK/word wrapping, line cap, panel/window clamping) ----

export const TOOLTIP_MAX_WIDTH = 420;
export const TOOLTIP_MIN_WIDTH = 56;
export const TOOLTIP_MAX_LINES = 5;
export const TOOLTIP_FONT_SIZE = 11.5;
export const TOOLTIP_LINE_HEIGHT = 16.5;
export const TOOLTIP_PAD_X = 18;
export const TOOLTIP_PAD_Y = 12;
export const TOOLTIP_MARGIN = 16;
export const TOOLTIP_GAP = 6;

function isWideCodePoint(code) {
  return code > 0xFFFF
    || (code >= 0x1100 && code <= 0x115F)
    || (code >= 0x2E80 && code <= 0xA4CF)
    || (code >= 0xAC00 && code <= 0xD7A3)
    || (code >= 0xF900 && code <= 0xFAFF)
    || (code >= 0xFE10 && code <= 0xFE19)
    || (code >= 0xFE30 && code <= 0xFE6F)
    || (code >= 0xFF00 && code <= 0xFF60)
    || (code >= 0xFFE0 && code <= 0xFFE6);
}

function charEmWidth(ch) {
  const code = ch.codePointAt(0) || 0;
  if (isWideCodePoint(code)) return 1.0;
  if (' ilI1.,:;\'!|()[]/-·tfjr'.includes(ch)) return 0.38;
  if ('WMmw@%#GOQ'.includes(ch)) return 0.78;
  return 0.58;
}

function measureEm(str) {
  let w = 0;
  for (const ch of str) w += charEmWidth(ch);
  return w;
}

function isBreakAfter(ch) {
  const code = ch.codePointAt(0) || 0;
  return ch === ' ' || ch === '\t' || isWideCodePoint(code)
    || '/-·,;。，、：；）】」'.includes(ch);
}

export function tooltipMaxWidth({
  panelWidth: panelW = 0,
  viewWidth = 0,
  maxWidth = TOOLTIP_MAX_WIDTH,
  margin = TOOLTIP_MARGIN,
} = {}) {
  const base = Number.isFinite(maxWidth) && maxWidth > 0 ? maxWidth : TOOLTIP_MAX_WIDTH;
  let cap = Math.max(80, Math.min(TOOLTIP_MAX_WIDTH, base));
  if (Number.isFinite(panelW) && panelW > 0) {
    cap = Math.min(cap, Math.max(80, Math.floor(panelW - margin * 2)));
  }
  if (Number.isFinite(viewWidth) && viewWidth > 0) {
    cap = Math.min(cap, Math.max(80, Math.floor(viewWidth - margin * 2)));
  }
  return Math.round(cap);
}

export function wrapTooltipText(text, maxWidthPx, {
  maxLines = TOOLTIP_MAX_LINES,
  fontSize = TOOLTIP_FONT_SIZE,
  padX = TOOLTIP_PAD_X,
} = {}) {
  const clean = String(text ?? '').replace(/\r\n?/g, '\n').trim();
  if (!clean) return { lines: [], text: '', truncated: false, longestEm: 0 };
  const innerW = Math.max(40, (Number.isFinite(maxWidthPx) && maxWidthPx > 0 ? maxWidthPx : TOOLTIP_MAX_WIDTH) - padX);
  const budgetEm = Math.max(4, innerW / fontSize);
  const limit = Math.max(1, Math.floor(maxLines || TOOLTIP_MAX_LINES));
  const rawLines = [];
  for (const para of clean.split('\n')) {
    const trimmed = para.replace(/\s+$/g, '');
    if (!trimmed) {
      if (rawLines.length && rawLines[rawLines.length - 1] !== '') rawLines.push('');
      continue;
    }
    const chars = Array.from(trimmed);
    let buf = [];
    let w = 0;
    let lastBreakIdx = -1;
    let lastBreakW = 0;
    for (let i = 0; i < chars.length; i++) {
      const ch = chars[i];
      if (!buf.length && (ch === ' ' || ch === '\t')) continue;
      const cw = charEmWidth(ch);
      if (buf.length > 0 && w + cw > budgetEm) {
        if (lastBreakIdx > 0 && lastBreakW >= budgetEm * 0.35) {
          const head = buf.slice(0, lastBreakIdx).join('').replace(/\s+$/g, '');
          const tail = buf.slice(lastBreakIdx);
          while (tail.length && (tail[0] === ' ' || tail[0] === '\t')) tail.shift();
          rawLines.push(head);
          buf = tail;
          w = measureEm(buf.join(''));
          lastBreakIdx = -1;
          lastBreakW = 0;
          for (let j = 0; j < buf.length; j++) {
            if (isBreakAfter(buf[j])) {
              lastBreakIdx = j + 1;
              lastBreakW = measureEm(buf.slice(0, j + 1).join(''));
            }
          }
          if (buf.length > 0 && w + cw > budgetEm) {
            rawLines.push(buf.join('').replace(/\s+$/g, ''));
            buf = [];
            w = 0;
            lastBreakIdx = -1;
            lastBreakW = 0;
          }
        } else {
          rawLines.push(buf.join('').replace(/\s+$/g, ''));
          buf = [];
          w = 0;
          lastBreakIdx = -1;
          lastBreakW = 0;
        }
        if (!buf.length && (ch === ' ' || ch === '\t')) continue;
      }
      buf.push(ch);
      w += cw;
      if (isBreakAfter(ch)) {
        lastBreakIdx = buf.length;
        lastBreakW = w;
      }
    }
    if (buf.length) rawLines.push(buf.join('').replace(/\s+$/g, ''));
  }
  while (rawLines.length && rawLines[rawLines.length - 1] === '') rawLines.pop();
  let truncated = false;
  let lines = rawLines;
  if (rawLines.length > limit) {
    truncated = true;
    lines = rawLines.slice(0, limit);
    const ellBudget = Math.max(2, budgetEm - 1.0);
    const chars = Array.from(lines[limit - 1]);
    while (chars.length > 0 && measureEm(chars.join('')) > ellBudget) chars.pop();
    lines[limit - 1] = `${chars.join('').replace(/\s+$/g, '')}…`;
  }
  const longestEm = lines.reduce((m, l) => Math.max(m, measureEm(l)), 0);
  return { lines, text: lines.join('\n'), truncated, longestEm };
}

export function clampTooltipRect(triggerRect, cardSize, boundsRect, {
  placement = 'above-left',
  gap = TOOLTIP_GAP,
  margin = TOOLTIP_MARGIN,
} = {}) {
  const wantBelow = String(placement || '').startsWith('below');
  const wantRight = String(placement || '').endsWith('right');
  const minX = boundsRect.x + margin;
  const maxX = Math.max(minX, boundsRect.x + boundsRect.w - cardSize.w - margin);
  const minY = boundsRect.y + margin;
  const maxY = Math.max(minY, boundsRect.y + boundsRect.h - cardSize.h - margin);
  const yAbove = triggerRect.y - gap - cardSize.h;
  const yBelow = triggerRect.y + triggerRect.h + gap;
  const fitsAbove = yAbove >= minY;
  const fitsBelow = yBelow <= maxY;
  const roomAbove = triggerRect.y - gap - minY;
  const roomBelow = (boundsRect.y + boundsRect.h - margin) - (triggerRect.y + triggerRect.h + gap);
  let vert = wantBelow ? 'below' : 'above';
  if (vert === 'above' && !fitsAbove && (fitsBelow || roomBelow > roomAbove)) vert = 'below';
  else if (vert === 'below' && !fitsBelow && (fitsAbove || roomAbove > roomBelow)) vert = 'above';
  const rawY = vert === 'below' ? yBelow : yAbove;
  const rawX = wantRight ? triggerRect.x + triggerRect.w - cardSize.w : triggerRect.x;
  const x = Math.round(Math.max(minX, Math.min(maxX, rawX)));
  const y = Math.round(Math.max(minY, Math.min(maxY, rawY)));
  return { x, y, w: cardSize.w, h: cardSize.h, placement: `${vert}-${wantRight ? 'right' : 'left'}` };
}

export function tooltipLayout(text, opts = {}) {
  const fontSize = opts.fontSize || TOOLTIP_FONT_SIZE;
  const lineHeight = opts.lineHeight || TOOLTIP_LINE_HEIGHT;
  const padX = opts.padX ?? TOOLTIP_PAD_X;
  const padY = opts.padY ?? TOOLTIP_PAD_Y;
  const maxLines = opts.maxLines || TOOLTIP_MAX_LINES;
  const gap = opts.gap ?? TOOLTIP_GAP;
  const margin = opts.margin ?? TOOLTIP_MARGIN;
  const maxWidth = tooltipMaxWidth(opts);
  const wrapped = wrapTooltipText(text, maxWidth, { maxLines, fontSize, padX });
  if (!wrapped.lines.length) return null;
  const width = Math.min(maxWidth, Math.max(TOOLTIP_MIN_WIDTH, Math.ceil(wrapped.longestEm * fontSize + padX + 10)));
  const height = Math.ceil(wrapped.lines.length * lineHeight + padY);
  const maxHeight = Math.ceil(maxLines * lineHeight + padY + 4);
  const placement = opts.placement || 'above-left';
  let anchor = 'bottom_left';
  let pos = { left: 0, top: -gap };
  if (placement === 'above-right') { anchor = 'bottom_right'; pos = { right: 0, top: -gap }; }
  else if (placement === 'below-left') { anchor = 'top_left'; pos = { left: 0, bottom: -gap }; }
  else if (placement === 'below-right') { anchor = 'top_right'; pos = { right: 0, bottom: -gap }; }
  const rect = opts.triggerRect && opts.boundsRect
    ? clampTooltipRect(opts.triggerRect, { w: width, h: height }, opts.boundsRect, { placement, gap, margin })
    : null;
  return {
    lines: wrapped.lines,
    text: wrapped.text,
    truncated: wrapped.truncated,
    width,
    maxWidth,
    height,
    maxHeight,
    fontSize,
    lineHeight,
    placement: rect ? rect.placement : placement,
    anchor,
    pos,
    rect,
  };
}

export function windowControlButtons(win, { overlay = false } = {}) {
  if (overlay || win?.buttons !== true) return [];
  const isWindows = win.platform === 'windows';
  const maximized = win.maximized === true;
  return [
    {
      id: 'win-minimize',
      command: 'window.minimize',
      icon: isWindows ? 'mods/tabs/win-min.svg' : null,
      glyph: isWindows ? '' : '−',
      iconSize: 16,
      danger: false,
      labelKey: 'windowMinimize',
    },
    {
      id: 'win-maximize',
      command: 'window.maximize',
      icon: isWindows ? (maximized ? 'mods/tabs/win-restore.svg' : 'mods/tabs/win-max.svg') : null,
      glyph: isWindows ? '' : '□',
      iconSize: 16,
      danger: false,
      labelKey: maximized ? 'windowRestore' : 'windowMaximize',
    },
    {
      id: 'win-close',
      command: 'window.close',
      icon: isWindows ? 'mods/tabs/win-close.svg' : 'mods/pane/close.svg',
      glyph: '',
      iconSize: isWindows ? 16 : 13,
      danger: true,
      labelKey: 'windowClose',
    },
  ];
}
