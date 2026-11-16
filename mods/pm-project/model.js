// Pure parts of the project view: the conversation log turned into a timeline,
// the waiting count, optimistic bubbles, and the words in both languages.

const STRINGS = {
  en: {
    you: 'You', waiting: 'Waiting for you', waitingCount: n => `${n} ${n === 1 ? 'item' : 'items'} waiting for you`,
    nothingWaiting: 'Nothing waiting for you',
    openPm: 'Open the PM terminal', noPmTerminal: 'The PM is not in the desktop app',
    chatView: 'Conversation', boardView: 'Board',
    say: name => `Message the ${name} coordinator…`, sayThread: 'Message only this thread…',
    send: 'Send', sendThread: 'Send to this thread', diffTab: branch => `diff ${branch}`,
    offline: 'No PM session of this project is running in the desktop app. Start it, then run pm.py claim.',
    threadOffline: 'This thread has no live terminal',
    subThreads: 'Split into', partOf: title => `Part of ${title}`, moreParts: n => `${n} more`,
    reviewThread: 'Review', openReviewTerminal: "Open the reviewer's terminal",
    disconnected: 'Disconnected', group_offline: 'Disconnected',
    reattach: "Reattach: resume this thread's agent session, or start a new agent with its brief and ledger log",
    reattaching: 'Reattaching…', reattachFailed: error => `Not reattached: ${error}`,
    openTerminal: 'Open its terminal', terminalNowhere: 'Its terminal is in no pane, and neither is its PM: nowhere to open it',
    diff: 'See the changes', noDiff: 'No branch to compare yet', close: 'Close',
    resizePanel: 'Drag to resize the side panel; double-click for its default width',
    sending: 'Sending…', failed: error => `Not sent: ${error}`, decision: 'Decision',
    pick: 'Pick a project in the PM list to open its conversation.', noProject: 'This PM is no longer in the ledger.',
    remoteLoading: machine => `Reading the project from ${machine}…`,
    remoteError: (machine, error) => `Could not read the project from ${machine}. Is that machine connected in Herdr, with the pm skill installed there?\n${error}`,
    remoteDiff: 'The changes are on the other machine: open its terminal to see them',
    remoteAttach: 'Files can only be attached to a project on this computer',
    empty: 'Nothing said in this project yet.', readError: 'Could not read the conversation',
    today: 'Today', yesterday: 'Yesterday', noLog: 'No log yet', agent: (program, address) => `${program} · terminal ${address}`,
    unfold: 'Show the whole reply', fold: 'Fold',
    threads: 'Threads', showThreads: 'Show the threads', hideThreads: 'Hide the threads',
    group_waiting: 'Waiting on you', group_review: 'In review', group_working: 'Working', group_paused: 'Paused',
    group_parked: 'Not started',
    groupSessions: 'Sessions', groupFinished: 'Finished', recommended: 'Recommended', openThread: 'Open this thread',
    ownAnswer: 'Answer in your own words…', answeringTo: title => `Answering ${title}`, stopAnswering: 'Stop answering this question (Esc)',
    noThreads: 'No threads in this project yet.', openSession: 'Click opens this session',
    session_working: 'Working', session_blocked: 'Needs you', session_done: 'Done', session_idle: 'Idle',
    in_progress: 'In progress', blocked: 'Blocked', answered: 'Answered', review: 'Review', paused: 'Paused', proposed: 'Proposed',
    merged: 'Merged', released: 'Released', done: 'Done', abandoned: 'Abandoned', cleanup: 'Merged · not retired',
    attach: 'Attach files (or drop them here, or paste a screenshot)', removeFile: name => `Remove ${name}`,
    attachFailed: error => `Could not attach: ${error}`, attachments: 'Attachments:',
    notAFile: names => `not a file: ${names}`, noPasteFolder: 'this project has no conversation log yet, so a pasted image has nowhere to be kept',
    engineProfile: name => `Profile: ${name}`, engineWhy: why => `Why: ${why}`, engineRounds: n => `Review rounds: ${n}`,
    engineEscalated: (from, to, why) => `Escalated ${from} → ${to}${why ? `: ${why}` : ''}`,
  },
  zh: {
    you: '你', waiting: '等你', waitingCount: n => `${n} 件事等你`, nothingWaiting: '没有等你的事',
    openPm: '打开 PM 终端', noPmTerminal: 'PM 不在桌面里',
    chatView: '对话', boardView: '看板',
    say: name => `对 ${name} 的协调者说…`, sayThread: '只对这个线程说…',
    send: '发送', sendThread: '发给这个线程', diffTab: branch => `改动 ${branch}`,
    offline: '这个项目没有在桌面里运行的 PM 会话。启动它，再运行 pm.py claim。',
    threadOffline: '这个线程没有在线的终端',
    subThreads: '拆出的子线程', partOf: title => `属于 ${title}`, moreParts: n => `还有 ${n} 条`,
    reviewThread: '审查', openReviewTerminal: '打开审查终端',
    disconnected: '已断开', group_offline: '已断开',
    reattach: '接回：恢复这个线程的 agent 会话；找不到会话就新开一个，把任务书和台账记录交给它',
    reattaching: '正在接回…', reattachFailed: error => `没接回：${error}`,
    openTerminal: '打开终端', terminalNowhere: '它的终端不在任何窗格里，PM 也不在，没有地方打开它',
    diff: '看改动', noDiff: '还没有可以比较的分支', close: '收起',
    resizePanel: '拖动调整侧栏宽度，双击恢复默认宽度',
    sending: '正在发送…', failed: error => `没发出去：${error}`, decision: '决定',
    pick: '在 PM 列表里点一个项目，打开它的对话。', noProject: '台账里已经没有这个 PM。',
    remoteLoading: machine => `正在从 ${machine} 读取这个项目…`,
    remoteError: (machine, error) => `读不到 ${machine} 上的这个项目。确认这台机器在 Herdr 里已连接，并装了 pm 技能。\n${error}`,
    remoteDiff: '改动在另一台机器上，打开它的终端查看',
    remoteAttach: '只有这台电脑上的项目能添加附件',
    empty: '这个项目还没有对话。', readError: '对话记录读取失败',
    today: '今天', yesterday: '昨天', noLog: '暂无日志', agent: (program, address) => `${program} · 终端 ${address}`,
    unfold: '展开全文', fold: '收起',
    threads: '线程', showThreads: '显示线程列表', hideThreads: '收起线程列表',
    group_waiting: '等你', group_review: '审查中', group_working: '进行中', group_paused: '暂停', group_parked: '未开始',
    groupSessions: '对话', groupFinished: '已结束', recommended: '推荐', openThread: '打开这个线程',
    ownAnswer: '用自己的话回答…', answeringTo: title => `回答 ${title}`, stopAnswering: '不回答这个问题了（Esc）',
    noThreads: '这个项目还没有线程。', openSession: '点击打开这个对话',
    session_working: '工作中', session_blocked: '等你', session_done: '已完成', session_idle: '空闲',
    in_progress: '进行中', blocked: '阻塞', answered: '已回答', review: '审查中', paused: '暂停', proposed: '提议',
    merged: '已合并', released: '已发布', done: '完成', abandoned: '放弃', cleanup: '已合并 · 待回收',
    attach: '添加附件（也可以把文件拖进来，或粘贴截图）', removeFile: name => `移除 ${name}`,
    attachFailed: error => `附件没加上：${error}`, attachments: '附件：',
    notAFile: names => `不是文件：${names}`, noPasteFolder: '这个项目还没有对话记录，贴的图没有地方存',
    engineProfile: name => `档位：${name}`, engineWhy: why => `理由：${why}`, engineRounds: n => `评审轮数：${n}`,
    engineEscalated: (from, to, why) => `升级 ${from} → ${to}${why ? `：${why}` : ''}`,
  },
};
export function word(lang, key, ...args) {
  const value = STRINGS[lang === 'zh' ? 'zh' : 'en'][key];
  return typeof value === 'function' ? value(...args) : value ?? key;
}

export const EVENT_LIMIT = 200;
export const WAITING = ['blocked'];
// Work that is over: its thread is one quiet line in the conversation, not a card row.
export const CLOSED = ['merged', 'released', 'done', 'abandoned'];
// Work that was given up (a proposal another task replaced, a test run) is not shown among the
// threads: no line in the conversation, no place in the side panel. A question it asked stays in
// the conversation, and a link that names it still opens it.
const GIVEN_UP = 'abandoned';
// A task in one of these has work to show. One that enters the log `blocked` and never reaches any
// of them is only the coordinator asking (`pm.py new --status blocked`, then closed with the answer).
const WORK = ['in_progress', 'review', 'paused', 'proposed'];

// The tasks in these events that are only a question: the question line stands for them, so they
// get no thread row in the conversation and are not listed among the threads that ended.
export function questionOnly(events) {
  const first = new Map(), worked = new Set();
  for (const e of events || []) {
    if (e.type !== 'thread' || !e.task) continue;
    if (!first.has(e.task)) first.set(e.task, e.status);
    if (WORK.includes(e.status)) worked.add(e.task);
  }
  return new Set([...first].filter(([task, status]) => status === 'blocked' && !worked.has(task)).map(([task]) => task));
}

// A ledger entry that asks the user a question: `pm.py update --status blocked` (its text says
// status=blocked, also while the task already was blocked) or one that offers quick answers (--option).
// A task entering blocked from another status asks too (see timeline). The same rule as pm.py's asks_again.
export function asksAgain(e) {
  return /\bstatus=blocked\b/.test(String(e?.text || '')) || (Array.isArray(e?.options) && e.options.some(o => squash(o)));
}

// The last `limit` events of conversation.jsonl text. Lines that are not JSON
// objects (a torn last line, a stray `null`) are skipped, as pm.py does.
export function parseConversation(text, limit = EVENT_LIMIT) {
  const events = [];
  for (const line of String(text || '').split('\n')) {
    if (!line.trim()) continue;
    try {
      const event = JSON.parse(line);
      if (event && typeof event === 'object' && !Array.isArray(event) && typeof event.type === 'string') events.push(event);
    } catch (_) { /* not an event */ }
  }
  return events.slice(-limit);
}

// 'blocked' | 'review' | 'running' | 'quiet': which status color a thread gets. A blocked task the
// user has answered (see answeredTasks) is quiet: it waits for the coordinator, not for the user.
export function tone(status, cleanup = false, offline = false, answered = false) {
  if (cleanup || (offline && status === 'in_progress') || (answered && status === 'blocked')) return 'quiet';
  if (status === 'blocked') return 'blocked';
  if (status === 'review') return 'review';
  return status === 'in_progress' ? 'running' : 'quiet';
}

export function statusLabel(lang, status, cleanup = false, offline = false, answered = false) {
  if (cleanup) return word(lang, 'cleanup');
  if (answered && status === 'blocked') return word(lang, 'answered');
  return word(lang, disconnected({ status, offline }) ? 'disconnected' : status || 'in_progress');
}

// A task `pm.py state` marks offline is open work whose terminal is gone. One in progress then reads as
// Disconnected, quietly, not as work going on; one that waits for the user or is in review keeps saying so.
export function disconnected(task) {
  return Boolean(task?.offline) && (task.status || 'in_progress') === 'in_progress';
}

// What the thread panel's terminal icon does: 'open' the thread's live terminal; 'reattach' an offline
// thread (pm.py reattach); 'reattaching' while that runs; 'none' when there is nothing to do; 'hidden'
// (no icon at all) for a task that never had a terminal (no pane) and was split into sub-threads
// (`parts` of them): its work is done there, and they are listed in its panel.
export function terminalAction(terminal, task, busy = false, parts = 0) {
  if (terminal) return 'open';
  if (busy) return 'reattaching';
  if (task?.offline) return 'reattach';
  return !task?.pane && parts > 0 ? 'hidden' : 'none';
}

// `pm.py reattach <id>` as the project view runs it: without this app's terminal identity, so the
// ledger records the user as the one who reattached (as sendArgv does for a send).
export function reattachArgv(script, id) {
  return ['-u', 'HC_TERMINAL_ID', '-u', 'HERDR_PANE_ID', 'python3', script, 'reattach', id];
}

const squash = text => String(text || '').replace(/\s+/g, ' ').trim();

// "2026-11-13 09:08:12" (pm.py's local time) as ms.
export function eventTime(at) {
  const ms = new Date(String(at || '').replace(' ', 'T')).getTime();
  return Number.isFinite(ms) ? ms : 0;
}

// Messages sent from the view show at once and give way to the same text in the
// log. pending: [{id, text, sentAt (ms), failed?}]. A logged `user` event takes
// the oldest pending bubble with its text, if it was written no earlier than a
// minute before that bubble was sent (the log keeps whole seconds).
export function settlePending(pending, events) {
  const left = [...(pending || [])];
  const used = new Set();
  for (const p of pending || []) {
    if (p.failed) continue;
    const i = events.findIndex((e, n) => !used.has(n) && e.type === 'user' && sameMessage(e.text, p.text) &&
      eventTime(e.at) >= p.sentAt - 60000);
    if (i < 0) continue;
    used.add(i);
    left.splice(left.indexOf(p), 1);
  }
  return left.length === (pending || []).length ? pending : left;
}

// The opening of a PM reply as plain text: what the conversation shows while the reply is folded.
// {text, more}: `more` is false when the opening is the whole reply. The opening is the first
// paragraph up to where a list, table, heading, quote or code block starts (or the first line of
// one), without markdown marks. `limit` only guards against a reply that is one endless paragraph:
// past it the opening is cut at a sentence end.
const STRUCTURE = /^\s*([-*+]|\d{1,9}[.)]|#{1,6}|>)\s|^\s*\||^ *(`{3,}|~{3,})/;
export function lead(text, limit = 400) {
  const body = String(text || '').trim();
  const blocks = body.split(/\n[ \t]*\n/), lines = blocks[0].split('\n');
  const taken = [lines[0]];
  if (!STRUCTURE.test(lines[0])) for (const next of lines.slice(1)) { if (STRUCTURE.test(next)) break; taken.push(next); }
  const line = squash(taken.join(' ').replace(/^\s*(#{1,6}|>|[-*+]|\d{1,9}[.)])\s+/, '').replace(/^ *(`{3,}|~{3,}).*$/, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\*\*|__|`/g, '').replace(/\|/g, ' '));
  let cut = line;
  if (line.length > limit) {
    const head = line.slice(0, limit);
    const stop = Math.max(...['。', '！', '？', '；', '. ', '! ', '? ', '; '].map(mark => head.lastIndexOf(mark)));
    cut = stop >= limit / 2 ? head.slice(0, stop + 1).trim() : `${head.trimEnd()}…`;
  }
  return { text: cut, more: cut !== line || taken.length < lines.length || blocks.length > 1 };
}

// A reply can name a thread as a link, `[name](thread:<task id>)`. The task id of such a link's
// address, or '' for any other address and for an id that could not be a ledger file's name.
export function threadLink(url) {
  const found = /^thread:(?:\/\/)?([^?#]+)/i.exec(String(url || '').trim());
  if (!found) return '';
  let id = found[1].replace(/\/+$/, '');
  try { id = decodeURIComponent(id); } catch (_) { return ''; }
  // A task id is its project's folder name and a slug: letters and digits of any script, spaces, . _ -
  return /^[\p{L}\p{N}][\p{L}\p{N} ._-]*$/u.test(id) && !id.includes('..') ? id : '';
}

// Drafts: what is typed into a message box and not sent yet. The view keeps them in localStorage
// as they change, so a reload of the mod (any save of its files) or a restart of the app loses
// nothing. One per box: the project's ('pm:<PM name>') and each thread's ('thread:<task id>').
// Stored as {key: {text, at, files?}} with `at` in ms; only the newest DRAFT_LIMIT are kept.
// files: the box's attachments, absolute paths (see withFiles); a draft can be files alone.
export const DRAFT_LIMIT = 40;
export const draftKey = (kind, id) => (id ? `${kind}:${id}` : '');
export const draftText = (drafts, key) => (key && drafts?.[key]?.text) || '';
export const draftFiles = (drafts, key) => (key && Array.isArray(drafts?.[key]?.files) ? drafts[key].files : []);
// The stored JSON as drafts; text that is not such an object reads as none.
export function readDrafts(text) {
  try {
    const raw = JSON.parse(text);
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
    return Object.fromEntries(Object.entries(raw).flatMap(([key, draft]) => {
      if (!draft || typeof draft !== 'object' || (draft.text !== undefined && typeof draft.text !== 'string')) return [];
      const words = draft.text?.trim() ? draft.text : '', files = withFiles([], draft.files);
      if (!words && !files.length) return [];
      return [[key, { text: words, at: Number(draft.at) || 0, ...(files.length ? { files } : {}) }]];
    }));
  } catch (_) { return {}; }
}
// The drafts with the box `key` holding `text` and the attachments `files` (unchanged when not
// given); a box without words or files has no draft. Returns `drafts` itself when nothing changes,
// so the caller writes only what is new.
export function keepDraft(drafts, key, text, now, files = draftFiles(drafts, key)) {
  text = String(text ?? '');
  if (!text.trim()) text = '';
  files = withFiles([], files);
  if (!key || (draftText(drafts, key) === text && sameFiles(draftFiles(drafts, key), files))) return drafts;
  const { [key]: _old, ...rest } = drafts;
  if (!text && !files.length) return rest;
  const kept = Object.entries({ ...rest, [key]: { text, at: now, ...(files.length ? { files } : {}) } });
  return Object.fromEntries(kept.length > DRAFT_LIMIT ? kept.sort((a, b) => b[1].at - a[1].at).slice(0, DRAFT_LIMIT) : kept);
}

// Attachments. A file goes with a message as its absolute path: dropped on a message box, picked
// with the paperclip, or a pasted screenshot saved in the project's attachments folder. The message
// carries them as its last lines, one path a line, after a blank line (see messageText); the agent
// that reads it opens the files, an image as an image.
// A path is absolute and names something below a folder: "/clear" or "/model opus" is a command.
// A name may start or end with spaces, so a path is never trimmed.
const PATH = /^\/[^/\s]+\/[^\n]*[^/\n]$/;
const isPath = path => typeof path === 'string' && PATH.test(path);
const sameFiles = (a, b) => a.length === b.length && a.every((path, i) => path === b[i]);
// `files` with `added` after them: each path once, in the order it first came; what is not a path is left out.
export function withFiles(files, added = []) {
  const out = [];
  for (const path of [...(Array.isArray(files) ? files : []), ...(Array.isArray(added) ? added : [])]) {
    if (isPath(path) && !out.includes(path)) out.push(path);
  }
  return out;
}
export const withoutFile = (files, path) => (files || []).filter(f => f !== path);
// What of `paths` (dropped or picked) cannot attach: not a file's absolute path.
export const notFiles = paths => (Array.isArray(paths) ? paths : []).filter(path => !isPath(path));
// The picker's output as paths: one a line, kept exactly as written (a name may end in a space).
export const pickedPaths = out => String(out ?? '').split('\n').filter(line => line !== '');
// The drafts with `paths` added to the box `key`'s files as they are stored, its words as stored:
// the box may show less than its draft (words on their way are still the draft until they went out).
export function addFiles(drafts, key, paths, now) {
  return keepDraft(drafts, key, draftText(drafts, key), now, withFiles(draftFiles(drafts, key), paths));
}
// The line before the paths of a message that is only files, in either language: a message that
// starts with "/" would be read as a command by the agent's prompt.
const FILES_ONLY = [STRINGS.en.attachments, STRINGS.zh.attachments];
// What a box sends: its words, then its files after a blank line; files alone after `label`.
export function messageText(text, files = [], label = FILES_ONLY[0]) {
  const words = String(text ?? '').trim(), paths = withFiles([], files);
  if (!paths.length) return words;
  return words ? `${words}\n\n${paths.join('\n')}` : `${label}\n${paths.join('\n')}`;
}
// A message as {text, files}: the paths at its end come off as its files (all of it may be paths,
// or the files-only label and paths). Paths that run on from the words without a blank line are words.
export function splitMessage(message) {
  const whole = String(message ?? '').replace(/^\s*\n|\n\s*$/g, '');
  const lines = whole.split('\n');
  let at = lines.length;
  while (at > 0 && isPath(lines[at - 1])) at--;
  const files = () => withFiles([], lines.slice(at));
  if (at === lines.length) return { text: whole.trim(), files: [] };
  if (at === 0 || (at === 1 && FILES_ONLY.includes(lines[0].trim()))) return { text: '', files: files() };
  if (lines[at - 1].trim()) return { text: whole.trim(), files: [] };
  return { text: lines.slice(0, at).join('\n').trim(), files: files() };
}
// Claude Code may record an image sent with a message as an "[Image #3]" mark in place of its path,
// before the words ("[Image #3]看这里") or on a line of its own. How many a message has, and the
// message without them.
const IMAGE_MARK = /\[Image #\d+\][ \t]*/g;
const imageMarks = message => (String(message ?? '').match(IMAGE_MARK) || []).length;
const withoutMarks = message => String(message ?? '').replace(IMAGE_MARK, '');
// A message's words, for telling which sent message a logged one is: its last lines that are paths
// are not words, nor are image marks.
function wordsOf(message) {
  const lines = withoutMarks(message).split('\n');
  while (lines.length && (!lines[lines.length - 1].trim() || isPath(lines[lines.length - 1]))) lines.pop();
  const words = squash(lines.join('\n'));
  return FILES_ONLY.includes(words) ? '' : words;
}
// Whether a logged message is the one a pending bubble sent. One with files may be logged with its
// images as marks, so its words decide.
export const sameMessage = (logged, sent) => squash(logged) === squash(sent) ||
  (splitMessage(sent).files.length > 0 && wordsOf(logged) === wordsOf(sent));
// A file's name, for its card.
export const fileName = path => String(path || '').split('/').filter(Boolean).pop() || String(path || '');
const IMAGE = /\.(png|jpe?g|gif|webp|heic|tiff?|bmp|svg)$/i;
export const isImage = path => IMAGE.test(String(path || ''));
// A pasted screenshot's file in the attachments folder: paste-20261114-093012.png, -2 for a second one that second.
export function pasteName(date, n = 1) {
  const pad = (v, w = 2) => String(v).padStart(w, '0');
  const stamp = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
  return `paste-${stamp}${n > 1 ? `-${n}` : ''}.png`;
}
// The project's attachments folder, beside its conversation log: <ledger>/projects/<project>/attachments.
export function attachmentsDir(pm) {
  const log = String(pm?.conversation || '');
  return log.includes('/') ? `${log.slice(0, log.lastIndexOf('/'))}/attachments` : '';
}
// When a pasted screenshot was saved, from its name (see pasteName): [ms, n], or null for another file.
const PASTE = /(?:^|\/)paste-(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)(?:-(\d+))?\.png$/;
function pasteTime(path) {
  const m = PASTE.exec(String(path || ''));
  if (!m) return null;
  const [y, mo, d, h, mi, s] = m.slice(1, 7).map(Number);
  return [new Date(y, mo - 1, d, h, mi, s).getTime(), Number(m[7] || 1)];
}
// The pasted screenshots among `names` (an `ls` of the attachments folder `dir`), as paths.
export const pastesIn = (dir, names) => (dir ? String(names ?? '').split('\n').filter(n => pasteTime(n)).map(n => `${dir}/${n}`) : []);
// A logged message with image marks and no paths shows the screenshots pasted for it: the newest of
// `pastes` saved since the message before it with marks (at most PASTE_WINDOW before it), one per
// mark, that no other message carries. Without such screenshots the marks just do not show.
const PASTE_WINDOW = 30 * 60000;
function pastedFiles(events, pastes, carried) {
  const pool = (pastes || []).map(path => ({ path, when: pasteTime(path) }))
    .filter(p => p.when && !carried.has(p.path)).sort((a, b) => a.when[0] - b.when[0] || a.when[1] - b.when[1]);
  const out = new Map();
  let since = 0;
  for (const e of events) {
    if (e.type !== 'user') continue;
    const marks = imageMarks(e.text);
    if (!marks) continue;
    const at = eventTime(e.at), from = Math.max(since, at - PASTE_WINDOW);
    since = at;
    if (splitMessage(withoutMarks(e.text)).files.length) continue;
    const fits = pool.filter(p => !p.taken && p.when[0] > from && p.when[0] <= at).slice(-marks);
    for (const p of fits) p.taken = true;
    if (fits.length) out.set(e, fits.map(p => p.path));
  }
  return out;
}
// A box's draft after a send of `sent` ({text, files}) came back, or null when it stays as stored.
// Gone once sent: the words if they still are the box's draft, and the files that went. Not sent:
// the draft is what went out again when the box has been left empty, else what was typed since.
export function afterSend(stored, sent, ok) {
  const text = stored?.text || '', files = stored?.files || [];
  if (!ok) return text.trim() || files.length ? null : { text: sent.text, files: sent.files || [] };
  const next = { text: text.trim() === sent.text ? '' : text, files: files.filter(f => !(sent.files || []).includes(f)) };
  return next.text === text && next.files.length === files.length ? null : next;
}
// The picker, shown by osascript: the chosen files' paths one a line; nothing when it is cancelled.
export const CHOOSE_FILES = 'set picked to choose file with multiple selections allowed\n' +
  'set out to ""\nrepeat with f in picked\nset out to out & POSIX path of f & linefeed\nend repeat\nreturn out';
// The clipboard's image saved as a PNG at argv's path (item 1) in argv's folder (item 2), by
// osascript: prints "saved", or "none" when the clipboard holds no image, without making the folder.
// A TIFF image, as some apps copy, is converted with sips; its temporary file goes either way.
export const SAVE_CLIPBOARD_IMAGE = [
  'on run argv',
  'set target to item 1 of argv',
  'set fmt to "png"',
  'try',
  'set img to the clipboard as «class PNGf»',
  'on error',
  'try',
  'set img to the clipboard as TIFF picture',
  'set fmt to "tiff"',
  'on error',
  'return "none"',
  'end try',
  'end try',
  'do shell script "mkdir -p " & quoted form of (item 2 of argv)',
  'set outPath to target',
  'if fmt is "tiff" then set outPath to target & ".tiff"',
  'set f to open for access POSIX file outPath with write permission',
  'try',
  'set eof f to 0',
  'write img to f',
  'close access f',
  'on error e',
  'close access f',
  'do shell script "rm -f " & quoted form of outPath',
  'error e',
  'end try',
  'if fmt is "tiff" then do shell script "s=0; sips -s format png " & quoted form of outPath & " --out " & quoted form of target & " >/dev/null || s=$?; rm -f " & quoted form of outPath & "; exit $s"',
  'return "saved"',
  'end run',
].join('\n');

// What a quick answer sends as the user's turn.
export function answerText(title, option) {
  return `【${title}】${option}`;
}

// What a blocked task without a question card in the conversation is asked under (threadQuestion):
// a quick answer from its thread's detail carries it, and timeline() marks words that answer it so.
const ASK = 'ask:';
export const askKey = id => `${ASK}${id}`;

// The timeline, oldest first. Kinds:
//   day       a date divider
//   user      the user's words (right bubble); files: the paths it ended with (see splitMessage);
//             pending/failed for an unconfirmed one; `answers`: the
//             key of the question it answers, when it says so: a quick answer, or words that start
//             with the question's 【title】 (absent otherwise: other words name no question)
//   pm        the coordinator's reply (markdown): {text, lead, long, by}; a long one folds to its lead;
//             by: the session that spoke ('' in logs from before replies recorded it)
//   threads   adjacent thread rows: {rows: [{task, title, status, latest, waiting, tone, cleanup, closed, answered}]};
//             answered (only when true): blocked, and the user answered it (see answeredTasks);
//             a task that is abandoned now has no row and no `about`
//   about     a later ledger entry of a thread that already showed: {task, title, by (who wrote
//             it)}. turns() keeps the ones the coordinator wrote, to name what its reply is about.
//   question  the event that blocked a task, or asked again (asksAgain): {task, title, text, options, notes, recommended, open,
//             chosen}. notes: a line of explanation per option ('' for none); recommended: the first
//             option is the coordinator's pick; chosen: the option the user picked (its place in
//             options, from a quick answer in the log or one still being sent), else -1; answered
//             (only when true): open, and the user answered it (see answeredTasks). A task that
//             enters the log blocked (the coordinator asking) is this alone; it gets its thread row
//             where it first becomes work, if it ever does.
//   decision  a recorded decision
//   typing    the coordinator is working
// tasks: `pm.py state` tasks; a task's row shows what it is now, falling back to
// its newest event here once the ledger no longer lists it. `agent` events are not shown.
// A task blocked in the ledger that the events never show asked (its question is older than the log,
// or than the events shown) has no card; words said after the ledger asked (`asked_at`, see pm.py's
// asked_at) that start with its 【title】 still answer it: the user item then `answers` askKey(task)
// (see threadQuestion, where such a task is asked). A task's first event asks unless the ledger asked
// before it: a note on a question asked earlier (`pm.py log`) is no new question. pm: the project's
// name: only its tasks count so (tasks of other projects can share a title). The same rule as pm.py's
// answered_tasks.
export function timeline(events, tasks = [], { pending = [], typing = false, today = '', pastes = [], pm = '' } = {}) {
  const byId = new Map((tasks || []).map(t => [t.id, t]));
  const newest = new Map();
  for (const e of events) if (e.type === 'thread' && e.task) newest.set(e.task, e);
  const now = id => {
    const t = byId.get(id), last = newest.get(id) || {};
    const status = t?.status || last.status || '', cleanup = Boolean(t?.cleanup), offline = disconnected({ ...t, status });
    const answered = !cleanup && status === 'blocked' && Boolean(t?.answered);
    return { status, cleanup, ...(offline ? { offline } : {}), ...(answered ? { answered } : {}), title: t?.title || last.title || id,
      latest: cleanTaskLog(t ? t.latest : last.text).text, waiting: !cleanup && WAITING.includes(status) && !answered,
      tone: tone(status, cleanup, offline, answered), closed: CLOSED.includes(status) };
  };
  const items = [], shown = new Set(), asked = new Set(), before = new Map(), keys = new Map(), questions = [];
  const carried = new Set([...events.filter(e => e.type === 'user'), ...(pending || [])]
    .flatMap(e => splitMessage(withoutMarks(e.text)).files));
  const pasted = pastedFiles(events, pastes, carried);
  // A thread event that asks the user (see above); was: the task's status before it, undefined at its first.
  const minute = at => String(at || '').slice(0, 16), askedAt = id => String(byId.get(id)?.asked_at || '');
  const asking = (e, was) => e.status === 'blocked' && (was === undefined
    ? asksAgain(e) || !(askedAt(e.task) && minute(e.at) > askedAt(e.task)) : was !== 'blocked' || asksAgain(e));
  const seen = new Map(), shownAsking = new Set();
  for (const e of events) {
    if (e.type !== 'thread' || !e.task) continue;
    if (asking(e, seen.get(e.task))) shownAsking.add(e.task);
    seen.set(e.task, e.status);
  }
  // The blocked tasks without a card (see above): {key, title, at: when the ledger asked}.
  const cardless = (tasks || []).filter(t => t?.id && t.status === 'blocked' && !t.cleanup && !shownAsking.has(t.id)
    && (!pm || t.pm === pm)).map(t => ({ key: askKey(t.id), title: now(t.id).title, at: askedAt(t.id) }));
  // The newest question so far whose 【title】 the user's words start with; then the ones without a card,
  // asked before the words were said (at: when they were; none for words on their way).
  const addressed = (said, at = '') => [...cardless.filter(q => !at || !q.at || minute(at) >= q.at), ...questions].reverse()
    .find(q => q.title && said.startsWith(squash(answerText(q.title, ''))));
  let day = '';
  const key = (e, kind) => {
    const base = `${kind}:${e.at || ''}:${e.task || ''}`;
    const n = keys.get(base) || 0;
    keys.set(base, n + 1);
    return n ? `${base}:${n}` : base;
  };
  const push = (e, item) => {
    const date = String(e.at || '').slice(0, 10);
    if (date && date !== day) {
      day = date;
      items.push({ kind: 'day', key: `day:${date}`, date, today: date === today });
    }
    const pushed = { at: e.at || '', ...item };
    items.push(pushed);
    return pushed;
  };
  for (const e of events) {
    if (e.type === 'user' || e.type === 'pm') {
      if (!squash(e.text)) continue;
      // A message that was only images keeps its marks when no screenshot is found for it.
      const bare = e.type === 'user' ? withoutMarks(e.text) : e.text;
      const said = pasted.has(e) || wordsOf(bare) || splitMessage(bare).files.length ? bare : e.text;
      const item = { kind: e.type, key: key(e, e.type), text: String(said).trim() };
      if (e.type === 'user') {
        // A quick answer in the log marks the option it picked, on the newest question that offered it.
        const words = squash(said);
        const hit = [...questions].reverse().find(q => q.chosen < 0 && q.options.some(o => squash(answerText(q.title, o)) === words));
        if (hit) { hit.chosen = hit.options.findIndex(o => squash(answerText(hit.title, o)) === words); item.answers = hit.key; }
        else { const named = addressed(words, e.at); if (named) item.answers = named.key; }
        // The files it carried show as cards in its bubble, not as lines of paths; its image marks
        // as the screenshots pasted for it.
        const { text, files } = splitMessage(said);
        if (files.length) { item.text = text; item.files = files; }
        else if (pasted.has(e)) { item.text = FILES_ONLY.includes(text) ? '' : text; item.files = pasted.get(e); }
      }
      if (e.type === 'pm') {
        const opening = lead(item.text);
        item.lead = opening.text; item.long = opening.more; item.by = String(e.by || '');
      }
      push(e, item);
    } else if (e.type === 'decision') {
      if (squash(e.text)) push(e, { kind: 'decision', key: key(e, 'decision'), text: squash(e.text), quote: squash(e.quote) });
    } else if (e.type === 'thread' && e.task) {
      const known = before.has(e.task);
      if (!known && asking(e, undefined)) asked.add(e.task);
      const was = before.get(e.task);
      before.set(e.task, e.status);
      const gone = now(e.task).status === GIVEN_UP;
      // A task that entered as a question waits for its row until it is work.
      if (!gone && !shown.has(e.task) && (!asked.has(e.task) || WORK.includes(e.status))) {
        shown.add(e.task);
        const row = { task: e.task, ...now(e.task) };
        // Rows stay one group across the labels of threads that reported in between.
        let at = items.length - 1;
        while (at >= 0 && items[at].kind === 'about') at--;
        const last = items[at];
        if (last?.kind === 'threads' && String(e.at || '').slice(0, 10) === day) last.rows.push(row);
        else push(e, { kind: 'threads', key: key(e, 'threads'), rows: [row] });
      } else if (known && !gone) {
        push(e, { kind: 'about', key: key(e, 'about'), task: e.task, title: now(e.task).title, by: String(e.by || '') });
      }
      if (asking(e, was)) {
        const offered = (Array.isArray(e.options) ? e.options : [])
          .map((option, i) => [squash(option), squash(Array.isArray(e.option_notes) ? e.option_notes[i] : '')]).filter(([option]) => option);
        questions.push(push(e, { kind: 'question', key: key(e, 'question'), task: e.task, title: now(e.task).title,
          text: cleanTaskLog(e.text).text, open: false, options: offered.map(([option]) => option),
          notes: offered.map(([, why]) => why), recommended: Boolean(e.recommended) && offered.length > 0, chosen: -1 }));
      }
    }
  }
  // Only a task's latest question, while the task still waits, can be answered.
  const answered = new Set();
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item.kind !== 'question' || answered.has(item.task)) continue;
    answered.add(item.task);
    item.open = now(item.task).status === 'blocked';
  }
  for (const p of pending || []) {
    const answers = p.question || addressed(squash(p.text))?.key;
    const { text, files } = splitMessage(p.text);
    items.push({ kind: 'user', key: `pending:${p.id}`, text, pending: !p.failed, failed: p.failed || '',
      ...(files.length ? { files } : {}), ...(answers ? { answers } : {}) });
    // A quick answer on its way already shows as the picked option.
    const asking = p.question && !p.failed ? questions.find(q => q.key === p.question) : null;
    if (asking && asking.chosen < 0) asking.chosen = asking.options.findIndex(o => squash(answerText(asking.title, o)) === squash(p.text));
  }
  // What the user answered waits for the coordinator now: its question and its rows say so, and no longer wait.
  const held = answeredTasks(items);
  for (const item of items) {
    if (item.kind === 'question' && item.open && held.has(item.task)) item.answered = true;
    if (item.kind !== 'threads') continue;
    for (const row of item.rows) {
      if (held.has(row.task) && row.status === 'blocked' && !row.cleanup) Object.assign(row, { answered: true, waiting: false, tone: 'quiet' });
    }
  }
  if (typing) items.push({ kind: 'typing', key: 'typing' });
  return items;
}

// Timeline items in blocks: a day divider, a user bubble, or a coordinator turn {kind: 'turn', parts,
// index} drawn beside one avatar. A turn ends with the coordinator's reply. Its parts, in order: the
// names of the threads the reply is about, the reply, then what the coordinator did on the way to it
// (new threads, questions, decisions), as a message with its attachments. The working dots are a
// turn of their own. `index` lists the places in `items` of the block's parts.
// A reply is about the threads the coordinator itself wrote a ledger entry for in that turn: one name
// per thread, none for a thread whose row or question is in the same turn. A worker's entry names
// nothing (it may have logged while the user asked about something else), and without a reply there
// is nothing to name. The coordinator is the session that spoke the reply; a reply from before that
// was recorded counts as `pmPane`'s, the PM's pane now.
export function turns(items, pmPane = '') {
  const out = [];
  items.forEach((item, index) => {
    const last = out[out.length - 1];
    if (item.kind === 'day' || item.kind === 'user') out.push({ ...item, index: [index] });
    else if (last?.kind === 'turn' && !last.said && item.kind !== 'typing') {
      last.parts.push(item); last.index.push(index); last.said = item.kind === 'pm';
    } else {
      out.push({ kind: 'turn', key: `turn:${item.key}`, parts: [item], index: [index],
        said: item.kind === 'pm' || item.kind === 'typing' });
    }
  });
  // Parts that got no reply of their own (the user spoke first, or a day ended) join the turn right
  // before them; with no turn there they stand without an avatar (`bare`), as the newest ones do
  // while the coordinator is still working toward its reply.
  const kept = [];
  const tail = out.filter(b => b.parts?.[0]?.kind !== 'typing').pop();
  for (const block of out) {
    const before = kept[kept.length - 1];
    if (block.kind === 'turn' && !block.said) {
      if (block !== tail && before?.kind === 'turn' && before.said) {
        // The earlier reply was not about these: only what stands on its own moves over.
        block.parts.forEach((part, i) => {
          if (part.kind !== 'about') { before.parts.push(part); before.index.push(block.index[i]); }
        });
        continue;
      }
      block.bare = true;
    }
    kept.push(block);
  }
  for (const block of kept) {
    if (block.kind !== 'turn') continue;
    const reply = block.parts.find(p => p.kind === 'pm');
    const coordinator = reply ? reply.by || pmPane : '';
    // Threads this turn already shows: a new row, or a question card that carries the name.
    const here = new Set(block.parts.flatMap(p => p.kind === 'threads' ? p.rows.map(row => row.task) : p.kind === 'question' ? [p.task] : []));
    const named = new Set();
    const about = block.parts.filter(p => p.kind === 'about' && coordinator && p.by === coordinator &&
      !here.has(p.task) && !named.has(p.task) && named.add(p.task));
    block.parts = [...about, ...block.parts.filter(p => p.kind === 'pm'), ...block.parts.filter(p => p.kind !== 'pm' && p.kind !== 'about')];
  }
  return kept.filter(block => block.kind !== 'turn' || block.parts.length);
}

// The newest reply is read whole; older long ones fold until the user opens them.
export function newestReply(items) {
  for (let i = items.length - 1; i >= 0; i--) if (items[i].kind === 'pm') return items[i].key;
  return '';
}

// A session's name as the app's agents list gives it, so the two lists read alike: the tab's name
// when someone named the tab, else the agent's own title when it says something (not the program's
// name, a folder or user@host), else the program's name. `tab`: {name, named} or null.
export function sessionLabel(agent, tab) {
  const program = agent?.program?.name || '';
  if (tab?.named && tab.name && tab.name !== program) return tab.name;
  const raw = String(agent?.title || '');
  const title = raw.replace(/^[^\p{L}\p{N}]+/u, '').trim();           // without a leading status glyph
  const folder = /^[^\p{L}\p{N}~/]*([~/]|[A-Za-z]:\\)/.test(raw);
  const telling = title && title !== program && title.toLowerCase() !== agent?.program?.key && !folder && !title.includes('@');
  return telling ? title : program || agent?.address || '';
}

// What the side panel lists for one project while no thread is open there:
//   open      the PM's tasks that are not over, most pressing first:
//             {task, title, status, group, tone, waiting, latest, working (its own worker is at work),
//             offline (only when its terminal is gone), answered (only when true: blocked, and the user
//             answered it; tasks: see markAnswered), updated, branch}; group: 'waiting' (blocked) | 'review' |
//             'working' (in progress, or answered) | 'offline' (in progress, its terminal gone) | 'paused' |
//             'parked' (proposed), in that order
//   sessions  the agents in the window whose folder is the project's or one of its worktrees, except
//             the PM, a PM that handed over (label pm.retired) and the workers of open tasks (their
//             task's row stands for them):
//             {address, label, status, program}; the app's order: needs you, done, working, idle
//   finished  the newest FINISHED_LIMIT threads that are over: {task, title, status, cleanup};
//             an answered question (see questionOnly) is not one, nor is an abandoned task
// tasks: `pm.py state` tasks; events: the conversation log; terms: terminals(); live: agents();
// tabs: every space's tabs ({id, name, named}); lang: the view's language, for `latest` (see logText).
export const FINISHED_LIMIT = 6;
const OPEN_ORDER = ['blocked', 'review', 'in_progress', 'offline', 'paused', 'proposed'];
const GROUP = { blocked: 'waiting', review: 'review', in_progress: 'working', paused: 'paused' };

// The tasks whose own worker is at work now: a live terminal on this computer labeled with the task
// and reporting `working`. Only these move on screen (dots in the conversation, the arc in the panel).
export function workingTasks(terms = [], live = []) {
  const ids = new Set();
  for (const term of terms || []) {
    const task = term.labels?.task;
    if (!task || term.state !== 'live' || !term.address || term.address.includes('/')) continue;
    if (((live || []).find(a => a.address === term.address)?.status || term.status) === 'working') ids.add(task);
  }
  return ids;
}
const SESSION_RANK = { blocked: 4, done: 3, working: 2, idle: 1 };
// A blocked task the user has answered (see markAnswered) waits for the coordinator: among the work going on.
const answeredRow = t => t.status === 'blocked' && Boolean(t.answered);
const openRank = t => {
  const i = OPEN_ORDER.indexOf(disconnected(t) ? 'offline' : answeredRow(t) ? 'in_progress' : t.status);
  return i < 0 ? OPEN_ORDER.length : i;
};
const openRow = (t, lang, atWork) => ({ task: t.id, title: t.title || t.id, status: t.status || '',
  tone: tone(t.status, false, Boolean(t.offline), answeredRow(t)),
  waiting: WAITING.includes(t.status) && !answeredRow(t), ...(answeredRow(t) ? { answered: true } : {}),
  group: disconnected(t) ? 'offline' : answeredRow(t) ? 'working' : GROUP[t.status] || 'parked',
  latest: logText(lang, t.latest), updated: String(t.updated || ''), ...(t.offline ? { offline: true } : {}),
  branch: String(t.branch || ''), working: !disconnected(t) && atWork.has(t.id) });

// The threads a task was split into (`pm.py state` tasks whose `parent` is `id`), as the side panel's
// rows (see threadList's open), open ones first in the list's order, then those that are over
// (group 'finished', with cleanup). Each is still its own row in the thread list too.
// retired: the state's `retired_parts`, sub-threads gone from the board (merged and retired); they are
// over, and a task listed in both counts once.
export function subThreads(tasks, id, terms = [], live = [], lang = 'en', retired = []) {
  if (!id) return [];
  const atWork = workingTasks(terms, live);
  const seen = new Set();
  const parts = [...(Array.isArray(tasks) ? tasks : []), ...(Array.isArray(retired) ? retired : [])]
    .filter(t => t?.id && t.id !== id && t.parent === id && !seen.has(t.id) && seen.add(t.id));
  const newest = (a, b) => String(b.updated || '').localeCompare(String(a.updated || ''));
  const open = parts.filter(t => !CLOSED.includes(t.status)).sort((a, b) => openRank(a) - openRank(b) || newest(a, b))
    .map(t => openRow(t, lang, atWork));
  const over = parts.filter(t => CLOSED.includes(t.status)).sort(newest)
    .map(t => ({ task: t.id, title: t.title || t.id, status: t.status, tone: 'quiet', group: 'finished',
      cleanup: Boolean(t.cleanup), updated: String(t.updated || '') }));
  return [...open, ...over];
}

// The sub-threads the panel shows: past PARTS_LIMIT the rest fold behind a row that says how many
// more there are (`more`), until it is opened (`open`).
export const PARTS_LIMIT = 6;
export function foldParts(parts, open = false, limit = PARTS_LIMIT) {
  const rows = Array.isArray(parts) ? parts : [];
  if (open || rows.length <= limit) return { shown: rows, more: 0 };
  return { shown: rows.slice(0, limit), more: rows.length - limit };
}

// The review thread folded into a task (foldReviews), for that task's side panel: a row as the thread
// list's (its mark, status and latest report; group 'finished' once it is over), or null without one.
export function reviewRow(task, terms = [], live = [], lang = 'en') {
  const r = task?.review;
  if (!r?.id) return null;
  const row = !CLOSED.includes(r.status) ? openRow(r, lang, workingTasks(terms, live))
    : { task: r.id, title: r.title || r.id, status: r.status, tone: 'quiet', group: 'finished',
      latest: logText(lang, r.latest), updated: String(r.updated || '') };
  // A reviewer's report can be long: its opening, as a reply's is shown folded.
  return { ...row, latest: row.latest ? lead(row.latest, 160).text : '' };
}
// The thread a link or a line opens: a review thread folded into its task opens that task.
export function threadFor(tasks, id) {
  return (Array.isArray(tasks) ? tasks : []).find(t => t?.review?.id === id)?.id || id;
}

// The task a thread was split from, for the side panel's link back: {task, title}, or null when it
// has none or that task is not in `pm.py state` (closed and gone from the board).
export function parentThread(tasks, task) {
  const id = task?.parent;
  const found = id && id !== task.id ? (Array.isArray(tasks) ? tasks : []).find(t => t?.id === id) : null;
  return found ? { task: found.id, title: found.title || found.id } : null;
}
const trimFolder = path => typeof path === 'string' && path ? path.replace(/\/+$/, '') || '/' : '';
export function threadList(pm, tasks, events, terms = [], live = [], tabs = [], lang = 'en') {
  const mine = (Array.isArray(tasks) ? tasks : []).filter(t => (t.pm || '') === (pm?.name || ''));
  // A PM that handed over is no session to talk to: its terminal is labeled pm.retired.
  const local = (terms || []).filter(x => x.state === 'live' && x.address && !x.address.includes('/') && !x.labels?.['pm.retired']);
  const atWork = workingTasks(terms, live);
  // A thread in progress whose terminal is gone is listed apart, after the work going on.
  const rank = openRank;
  const open = mine.filter(t => !CLOSED.includes(t.status))
    .sort((a, b) => rank(a) - rank(b) || String(b.updated || '').localeCompare(String(a.updated || '')))
    .map(t => openRow(t, lang, atWork));

  const roots = [trimFolder(pm?.repo), trimFolder(pm?.worktrees)].filter(Boolean);
  const within = cwd => roots.some(root => cwd === root || cwd.startsWith(root === '/' ? root : `${root}/`));
  const pmAddress = pm ? terminalFor(pmRow(pm), terms || [])?.address : '';
  // A folded review's worker is part of its task's row too (foldReviews).
  const openIds = new Set([...open.map(row => row.task), ...mine.filter(t => t.review?.id).map(t => t.review.id)]);
  const found = (live || []).flatMap(agent => {
    const term = local.find(x => x.address === agent.address);
    if (!term || !within(trimFolder(term.cwd))) return [];
    if (term.address === pmAddress || term.labels?.pm || openIds.has(term.labels?.task)) return [];
    return [{ agent, term }];
  });
  const perTab = new Map();
  for (const { agent } of found) perTab.set(agent.tab, (perTab.get(agent.tab) || 0) + 1);
  const tabOf = new Map((tabs || []).map(tab => [tab.id, tab]));
  const sessions = found.map(({ agent, term }) => ({
    address: agent.address, status: SESSION_RANK[agent.status] ? agent.status : 'idle', program: agent.program || term.program || null,
    // Two agents in one tab cannot both carry the tab's name.
    label: sessionLabel(agent, perTab.get(agent.tab) > 1 ? null : tabOf.get(agent.tab)), seq: Number(agent.seq) || 0,
  })).sort((a, b) => SESSION_RANK[b.status] - SESSION_RANK[a.status] || b.seq - a.seq)
    .map(({ seq, ...row }) => row);

  const byId = new Map(mine.map(t => [t.id, t]));
  const over = new Map(), questions = questionOnly(events);
  const ended = status => CLOSED.includes(status) && status !== GIVEN_UP;
  // A review's own events (the log names it, not what it reviews): folded into its task, not a row. The
  // log carries no review_of: a `<id>-review` whose <id> is a thread here or in the log is one.
  const named = new Set([...byId.keys(), ...(events || []).map(e => e.task)]);
  const folded = new Set(mine.filter(t => t.review?.id).map(t => t.review.id));
  const review = id => folded.has(id) || (/-review$/.test(id) && named.has(id.slice(0, -'-review'.length)));
  for (const e of events || []) {
    if (e.type !== 'thread' || !e.task || questions.has(e.task) || review(e.task)) continue;
    const t = byId.get(e.task), status = t?.status || e.status || '';
    if (ended(status)) over.set(e.task, { task: e.task, title: t?.title || e.title || e.task, status, cleanup: Boolean(t?.cleanup), at: String(e.at || '') });
    else over.delete(e.task);
  }
  for (const t of mine) {
    if (ended(t.status) && !over.has(t.id) && !questions.has(t.id)) {
      over.set(t.id, { task: t.id, title: t.title || t.id, status: t.status, cleanup: Boolean(t.cleanup), at: String(t.updated || '') });
    }
  }
  const finished = [...over.values()].sort((a, b) => b.at.localeCompare(a.at)).slice(0, FINISHED_LIMIT)
    .map(({ at, ...row }) => row);
  return { open, sessions, finished };
}

// A PM reply as markdown the app's renderer numbers right. Herdr 0.1.15's TextView
// gives a paragraph that follows a sub-list its own list marker, so
//   1. Do this:\n   - a\n\n   Then that.\n2. Next
// shows 1, 1, 2, 2 (fixed upstream in gpui-component fe2e4bcf). Such a paragraph,
// and the rest of its top-level item, moves out to the left edge; the list then
// resumes at the next item's own number (a list keeps its start).
const ITEM = /^( {0,3})([-*+]|\d{1,9}[.)])( +|$)/;
const MARKER = /^([-*+]|\d{1,9}[.)])(\s|$)/;
const FENCE = /^ *(`{3,}|~{3,})/;
const indentOf = line => /^ */.exec(line)[0].length;
export function viewMarkdown(text) {
  const out = [];
  let item = null, sub = false, lifting = false, blank = false, fence = '';
  for (const line of String(text || '').split('\n')) {
    const lift = l => lifting ? l.slice(Math.min(item.content, indentOf(l))) : l;
    if (fence) {
      out.push(lift(line));
      if (line.trim().startsWith(fence)) fence = '';
      continue;
    }
    if (!line.trim()) { out.push(lift(line)); blank = true; continue; }
    const indent = indentOf(line), inside = item && indent >= item.content;
    const top = !inside && ITEM.exec(line);
    if (top) {
      if (lifting && out.length && out[out.length - 1].trim()) out.push('');
      // Text starts after the marker's spaces; none, or more than four, count as one.
      const [, lead, marker, gap] = top;
      item = { content: lead.length + marker.length + (gap.length && gap.length <= 4 ? gap.length : 1) };
      sub = false; lifting = false; blank = false;
      out.push(line);
      continue;
    }
    if (inside) {
      const rest = line.slice(item.content);
      const opens = FENCE.exec(rest);
      if (opens && indentOf(rest) < 4) { fence = opens[1]; sub = false; }
      else if (indentOf(rest) === 0 && MARKER.test(rest)) sub = true;
      else if (indentOf(rest) === 0) {
        if (blank && sub && !lifting) lifting = true;
        sub = false;
      }
      out.push(lift(line));
    } else {
      if (item && blank) { item = null; lifting = false; sub = false; }
      const opens = FENCE.exec(line);
      if (opens) fence = opens[1];
      out.push(line);
    }
    blank = false;
  }
  return out.join('\n');
}

// Where the bell scrolls: the latest open question, else the latest thread
// group holding a waiting row; -1 when nothing waits.
// What the conversation's scroll area holds, top to bottom: the blocks of turns(), with each
// coordinator turn cut into rows. The area can only be asked to reveal one of its own children, and
// the bell goes to one question, so a question must be such a child and not a part inside a tall
// turn. A turn's first row carries the avatar beside the thread names and the reply (beside its first
// part when it has neither); every further part is a row of its own under it.
// A turn's row: {kind: 'turn', key, parts, first, bare}; a day or a bubble stays the block it was.
export function timelineRows(blocks) {
  return blocks.flatMap(block => {
    if (block.kind !== 'turn') return [block];
    const head = block.parts.filter(p => p.kind === 'about' || p.kind === 'pm');
    const groups = [...(head.length ? [head] : []), ...block.parts.filter(p => !head.includes(p)).map(p => [p])];
    return groups.map((parts, n) => ({ kind: 'turn', key: n ? `${block.key}/${parts[0].key}` : block.key, parts,
      first: n === 0, bare: Boolean(block.bare) }));
  });
}
// The row that holds `item` (one of the timeline's items), or -1.
export const rowOf = (rows, item) => rows.findIndex(row => row.parts?.includes(item));

// The view follows the end of the conversation only for a reader who is at the end, and it cannot
// read where the scroll area rests. So it keeps count of how far above the end the reader is, in px
// (`rise`; 0 is the end), from what it does know: the wheel, each row's height and the area's height.
// The count errs toward following, since a reader wrongly taken to be away misses what arrives below.
// After the wheel moved by `dy` (> 0 is toward the top). room: how far the area can scroll at all
// (its content minus its height); view: its height. Going up never counts past what can be scrolled
// (a short conversation, or the top, does not move) nor past two screens; coming down takes off three
// times the distance, which also absorbs what the count missed (a dragged scrollbar, a key).
export function riseAfterWheel(rise, dy, room, view) {
  if (dy > 0) return Math.max(0, Math.min(rise + dy, room, 2 * view));
  return Math.max(0, rise + 3 * dy);
}
// After the scroll area was asked to reveal row `at` (the bell): it moves the least that shows the
// row, and not at all when the row is in view. heights: every row's height, top to bottom; tail: the
// space after the last row. With a height still unknown, a jump counts as a screen, except to the
// last row (the reader at the end has it in view).
export function riseAfterJump(rise, heights, at, view, tail = 0) {
  if (!(view > 0) || heights.some(h => !(h > 0))) return at >= heights.length - 1 ? rise : Math.max(rise, view || 1);
  // Distances from the end of the content: the row's lower and upper edge, and the area's (rise, rise + view).
  const low = heights.slice(at + 1).reduce((sum, h) => sum + h, tail), high = low + heights[at];
  if (high > rise + view) return Math.max(0, high - view);   // above the area: its top comes to the area's top
  if (low >= rise) return rise;                              // in view: nothing moves
  return low <= tail ? 0 : low;                              // below it: its bottom comes to the area's bottom (the last row: the end)
}

// The blocked tasks the user has answered, as task ids: the task's open question (its newest one, asked
// when the task last entered blocked or asked again, see asksAgain) was answered: an option picked on
// it (`chosen`, from the log or on its way) or words that name it (`answers`: a quick answer, or words
// that start with its 【title】). A row or question timeline() marked answered counts too (pm.py's
// `answered`, for a question older than the events shown). The task then waits for the coordinator,
// not for the user, until the coordinator moves it on; a reply in between changes nothing. A new
// question (the task asking again) is unanswered. Words that name no question answer none: they may
// be about something else. A blocked task without a card is answered by words that name it
// (askKey, see timeline).
export function answeredTasks(items) {
  const answers = new Set(items.filter(i => i.kind === 'user' && !i.failed && i.answers).map(i => i.answers));
  const out = new Set([...answers].filter(key => key.startsWith(ASK)).map(key => key.slice(ASK.length)));
  for (const i of items) {
    if (i.kind === 'question' && i.open && (i.answered || i.chosen >= 0 || answers.has(i.key))) out.add(i.task);
    else if (i.kind === 'threads') for (const r of i.rows) if (r.answered) out.add(r.task);
  }
  return out;
}

// `tasks` (pm.py state's) with `answered: true` on the blocked ones in `answered` (see answeredTasks):
// the side panel shows what the conversation already knows, before pm.py has read it.
export function markAnswered(tasks, answered) {
  return (Array.isArray(tasks) ? tasks : []).map(t => t?.status === 'blocked' && !t.answered && answered.has(t.id) ? { ...t, answered: true } : t);
}

// The question cards that wait for the user, as places in `items`, newest first: a task's open question,
// unless the user answered it (see answeredTasks).
export function bellTargets(items) {
  const out = [];
  for (let i = items.length - 1; i >= 0; i--) if (items[i].kind === 'question' && items[i].open && !items[i].answered) out.push(i);
  return out;
}

// Where the bell goes, one stop per task that waits for the user, in click order: its question card
// ({key, at: its place in `items`}, see bellTargets), newest first; then, for a waiting task with no
// card in the conversation (asked before the events shown, or before the log), its thread
// ({key, thread: the task's id}), whose detail asks it (threadQuestion). tasks: `pm.py state` tasks,
// the ones of `pm` (the project) that are blocked and not answered, as waitingCount counts them.
export function bellStops(items, tasks = [], pm = null) {
  const cards = bellTargets(items).map(at => ({ key: items[at].key, at }));
  const asked = new Set(items.filter(i => i.kind === 'question' && i.open).map(i => i.task));
  const answered = answeredTasks(items);
  const threads = (Array.isArray(tasks) ? tasks : []).filter(t => t?.status === 'blocked' && !t.answered && !t.cleanup
    && (!pm || t.pm === pm.name) && !asked.has(t.id) && !answered.has(t.id))
    .map(t => ({ key: `thread:${t.id}`, thread: t.id }));
  return [...cards, ...threads];
}

// What waits for the user in a project: its tasks that are blocked and not answered (pm.py marks a task
// `answered`, see answered_tasks there), one each, whether or not the conversation shows where. It is
// the project's badge in the sidebar and on the board: a copy of pm-list's waitingCount (a mod cannot
// import from another mod's folder; model.test.mjs checks the copies stay identical), so pm.py's
// counts.waiting when it gives one, else the PM's blocked tasks not answered (an older pm.py).
export function waitingCount(pm, tasks) {
  if (Number.isFinite(pm?.counts?.waiting)) return pm.counts.waiting;
  return (Array.isArray(tasks) ? tasks : []).filter(t => t?.pm === pm?.name && t.status === 'blocked' && !t.answered).length;
}

// The bell's number: waitingCount, less the tasks the conversation shows answered (see answeredTasks)
// that pm.py has not read yet, so a picked answer takes the bell down at once. It is the thread
// list's waiting group.
export function bellCount(pm, tasks, answered) {
  const unread = (Array.isArray(tasks) ? tasks : [])
    .filter(t => t?.pm === pm?.name && t.status === 'blocked' && !t.answered && answered.has(t.id)).length;
  return Math.max(0, waitingCount(pm, tasks) - unread);
}

// The stop (see bellStops) the next click on the bell goes to, null when nothing waits. `last` is what
// the click before left: {key: the stop it went to, seen: the keys of the stops then}. Clicks step
// through the stops in order and start over after the last. They also start over at the first when
// something waits that did not at the last click.
export function bellNext(stops, last) {
  if (!stops.length) return null;
  const known = last && stops.every(s => last.seen.includes(s.key));
  const at = known ? last.seen.indexOf(last.key) : -1;
  return (at >= 0 && stops.find(s => last.seen.indexOf(s.key) > at)) || stops[0];
}

// What an open thread's detail asks while its task waits for the user (blocked, not answered), null
// otherwise: {key, title, text, options, notes, recommended}, answered as a question card is (a quick
// answer sends answerText(title, option) tagged `key`; the user's own words go after the 【title】).
// A task with a question card in the conversation asks that card's question, under its key. One
// without (see bellStops) asks what its ledger file says: the entry that last made it blocked (its
// note), else its latest entry, and the quick answers the task offers; under askKey(task).
// task: the thread's ledger file over its `pm.py state` task (`answered`, see markAnswered).
export function threadQuestion(task, items = []) {
  if (!task?.id || task.status !== 'blocked' || task.answered || task.cleanup) return null;
  const card = [...items].reverse().find(i => i.kind === 'question' && i.task === task.id && i.open);
  if (card) {
    return card.answered || card.chosen >= 0 ? null : { key: card.key, title: card.title, text: card.text,
      options: card.options, notes: card.notes, recommended: card.recommended };
  }
  const log = Array.isArray(task.log) ? task.log : [];
  const asking = [...log].reverse().find(e => /\bstatus\s*=\s*blocked\b/.test(String(e?.text || '')));
  const latest = log.length ? log[log.length - 1].text : task.latest;
  const text = cleanTaskLog(asking?.text).text || cleanTaskLog(latest).text;
  const offered = (Array.isArray(task.options) ? task.options : [])
    .map((option, i) => [squash(option), squash(Array.isArray(task.option_notes) ? task.option_notes[i] : '')]).filter(([o]) => o);
  return { key: askKey(task.id), title: task.title || task.id, text, options: offered.map(([o]) => o),
    notes: offered.map(([, why]) => why), recommended: Boolean(task.recommended) && offered.length > 0 };
}

// The thread a bell stop (see bellStops) opens: a review's is the task it reviews (threadFor; tasks
// as the list shows them, foldReviews); '' when that detail is already open (shown), as a second
// click must not close it.
export function bellThread(stop, tasks, shown = '') {
  const id = stop?.thread ? threadFor(tasks, stop.thread) : '';
  return id && id !== shown ? id : '';
}

// What an open thread's detail asks (see threadQuestion). folded: the thread as the list shows it
// (foldReviews, markAnswered); own: its own `pm.py state` task; file: its ledger file, once read. A
// task whose review waits shows as blocked (foldReviews): the question is then the review's, not one
// of the task's own older ones, which were answered.
export function detailQuestion(folded, own, file, items = []) {
  if (!folded?.id) return null;
  if (folded.review?.status === 'blocked' && folded.status === 'blocked' && own?.status !== 'blocked') return threadQuestion(folded.review, items);
  const status = (folded.review ? folded.status : file?.status || folded.status) || '';
  return threadQuestion({ ...folded, ...(file || {}), id: folded.id, status, answered: Boolean(folded.answered), cleanup: folded.cleanup }, items);
}

// "09:08" today, else "11-12 09:08"; log entries ("YYYY-MM-DD HH:MM") and events alike.
export function clock(at, today) {
  const text = String(at || '');
  const time = text.slice(11, 16);
  return text.slice(0, 10) === today ? time : `${text.slice(5, 10)} ${time}`.trim();
}

export function dayLabel(lang, date, today, yesterday) {
  if (date === today) return word(lang, 'today');
  if (date === yesterday) return word(lang, 'yesterday');
  return date;
}

// "~/project/repos/dudu" for a folder under home.
export function shortPath(path, home) {
  const p = String(path || '');
  return home && (p === home || p.startsWith(home + '/')) ? '~' + p.slice(home.length) : p;
}

// The command that shows a thread's changes in a new tab, or null without a branch.
export function diffArgv(task) {
  const tree = task?.worktree || task?.repo, branch = task?.branch;
  if (!tree || !branch) return null;
  return ['git', '-C', tree, 'diff', `${task.base || 'main'}...${branch}`];
}

// The send command: `hc send` run without this app's terminal identity, so the
// PM's hook records the text as the user's turn, not as another agent's.
// `--` keeps a text starting with "-" (a Markdown list) from parsing as an option.
export function sendArgv(address, text) {
  return ['-u', 'HC_TERMINAL_ID', 'hc', 'send', '--', address, text];
}

// ---- a project on another machine ------------------------------------------------
// shared('pm-project') names the project: {pm, machine?}. A remote PM is keyed "<machine>/<name>" (as
// pm-list keys its row and pm-dash names it on the board); `name` is its name in that machine's ledger.
export function projectRef(value) {
  const key = typeof value?.pm === 'string' ? value.pm : '';
  const machine = typeof value?.machine === 'string' && key.startsWith(`${value.machine}/`) ? value.machine : '';
  return { key, machine, name: machine ? key.slice(machine.length + 1) : key };
}

// What a remote project's view reads is that machine's: its ledger (`pm.py state` there), its log and
// task files, through Herdr's exec/readTextFile `on`. Its terminals and agents are shown to the rest
// of the view as that machine sees them (machineView: its own only, addresses without "<machine>/"),
// so the ledger's panes and labels match as they do at home; an address goes back out with its
// prefix (onMachine) to be focused or sent to. Local items (machine '') pass as they are.
export function machineView(items, machine = '') {
  const list = Array.isArray(items) ? items : [];
  if (!machine) return list;
  const prefix = `${machine}/`, strip = a => typeof a === 'string' && a.startsWith(prefix) ? a.slice(prefix.length) : a;
  return list.filter(x => typeof x?.address === 'string' && x.address.startsWith(prefix))
    .map(x => ({ ...x, address: strip(x.address), ...(x.parent ? { parent: strip(x.parent) } : {}) }));
}
export const onMachine = (address, machine = '') => (machine && address ? `${machine}/${address}` : address);

// A copy of pm-dash's PM_SCRIPTS (model.test.mjs checks): where pm.py lives on another machine.
export const PM_SCRIPTS = ['.config/herdr-app/mods/pm-dash/skill/scripts/pm.py', '.claude/skills/pm/scripts/pm.py',
  '.codex/skills/pm/scripts/pm.py', '.pi/agent/skills/pm/scripts/pm.py'];
// `pm.py <args>` on another machine, as exec's [command, args]: the first pm.py found there, run
// without a terminal identity (as reattachArgv); args are passed as they are, never through the shell.
export function remotePmArgv(args, scripts = PM_SCRIPTS) {
  return ['sh', ['-c', `for f in ${scripts.map(path => `"$HOME/${path}"`).join(' ')}; do ` +
    'if [ -f "$f" ]; then exec env -u HC_TERMINAL_ID -u HERDR_PANE_ID python3 "$f" "$@"; fi; done; ' +
    'echo "pm.py not found" >&2; exit 127', 'sh', ...args]];
}

// A PM from `pm.py state` as a row the terminal lookup understands (as pm-list builds it).
export function pmRow(pm) {
  return pm ? { ...pm, type: 'pm', machine: '', sourceName: pm.name } : null;
}

// A ledger task (or a state task) as a row the terminal lookup understands.
export function taskRow(task) {
  return task ? { ...task, type: 'task', task: task.id, machine: '' } : null;
}

// What a thread's worker runs as (the task file's `worker`, `pm.py state`'s `engine`: {profile, kind, model,
// effort, advisor}); {} or nothing for a task dispatched before profiles.
export function taskEngine(task) {
  const of = [task?.engine, task?.worker].find(x => x && typeof x === 'object' && !Array.isArray(x)) || {};
  return ['profile', 'kind', 'model', 'effort', 'advisor'].some(k => of[k]) ? of : null;
}

// A model ID as people say it: opus → Opus, claude-fable-5-2 → Fable 5.2, claude-opus-4-1-20250805 → Opus 4.1,
// us.anthropic.claude-sonnet-5-5-v1:0 → Sonnet 5.5; anything else as it is, its first letter raised.
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
export function modelName(id) {
  const raw = String(id || '').trim().replace(/\[.*\]$/, '');
  const m = raw.toLowerCase().match(/(?:^|[.\/])(?:claude-)?(opus|sonnet|haiku|fable)((?:-\d{1,2})*)(?:-\d{8})?(?:-v\d+(?::\d+)?)?$/);
  if (!m) return raw && cap(raw);
  return cap(m[1]) + (m[2] ? ` ${m[2].slice(1).split('-').join('.')}` : '');
}

// The quiet label beside the thread's agent icon: Opus·xhigh, Sonnet·medium, Opus, Opus·xhigh+Fable, Codex·high.
// Claude's workers are named by model; another program by its own name. Null: nothing known, no label.
export function engineLabel(task) {
  const e = taskEngine(task);
  if (!e) return null;
  const kind = String(e.kind || 'claude');
  const name = kind === 'claude' ? modelName(e.model) || 'Claude' : cap(kind);
  return name + (e.effort ? `·${e.effort}` : '') + (e.advisor ? `+${modelName(e.advisor).split(' ')[0]}` : '');
}

// The task's escalations ({from, to, why, at}), in order; anything not shaped so is left out.
export function escalations(task) {
  return (Array.isArray(task?.escalations) ? task.escalations : []).filter(x => x && (x.from || x.to));
}

// Escalated at least once: the label gets a small up arrow.
export const wasEscalated = task => escalations(task).length > 0;

// One side of an escalation: a profile name, or a worker record ({profile, model, …}) said by its profile or label.
const stepName = side => (side && typeof side === 'object' ? side.profile || engineLabel({ engine: side }) : side) || '?';

// The reason the PM wrote when dispatching: the latest log note "<profile>：<why>" (or "<profile>: <why>").
export function engineReason(task) {
  const profile = taskEngine(task)?.profile;
  if (!profile) return '';
  const said = text => {
    const m = String(text || '').match(/^\s*([^\s:：]+)\s*[：:]\s*(.+)$/s);
    return m && m[1].toLowerCase() === String(profile).toLowerCase() ? m[2].trim() : '';
  };
  return (Array.isArray(task.log) ? task.log : []).map(e => said(e?.text)).filter(Boolean).pop() || '';
}

// What hovering the label says, one line each: the profile, the dispatch reason, each escalation, review rounds.
export function engineTip(lang, task) {
  const e = taskEngine(task);
  if (!e) return '';
  const lines = [];
  if (e.profile) lines.push(word(lang, 'engineProfile', e.profile));
  const why = engineReason(task);
  if (why) lines.push(word(lang, 'engineWhy', why));
  for (const x of escalations(task)) lines.push(word(lang, 'engineEscalated', stepName(x.from), stepName(x.to), x.why || ''));
  if (Number.isInteger(task.rounds) || /^\d+$/.test(task.rounds ?? '')) lines.push(word(lang, 'engineRounds', Number(task.rounds)));
  return lines.join('\n') || engineLabel(task);
}

// How long ago, in the largest whole unit: "<1m", "5m", "3h", "2d"; in a Chinese view "刚刚",
// "5 分钟", "3 小时", "2 天" (pm-list's rule; model.test.mjs keeps the copy identical).
const UNITS = [[86400000, 'd', '天'], [3600000, 'h', '小时'], [60000, 'm', '分钟']];
export function age(ms, lang) {
  const unit = UNITS.find(([size]) => ms >= size), zh = lang === 'zh';
  if (!unit) return zh ? '刚刚' : '<1m';
  return zh ? `${Math.floor(ms / unit[0])} ${unit[2]}` : `${Math.floor(ms / unit[0])}${unit[1]}`;
}

// A ledger log line as the thread panel shows it.
// A line that starts with changed fields (`pm.py update`: "status=review, commit=abc; <note>") is
// its note. One that is only such changes is '' (the list: the row's group already says it), or,
// with `whole`, the changes spelled out (the thread's log, where every entry shows).
// pm.py also writes a few lines by itself, in English: a registration, a dispatch, a retire. In a
// Chinese view these and the field names read as Chinese. What a person or an agent wrote is shown
// as written.
const LOG_FIELDS = 'title|status|owner|workspace|pane|agent|branch|worktree|base|brief|commit|release|parent';
const LOG_FIELD = new RegExp(`^(${LOG_FIELDS})\\s*=\\s*`);
const LOG_FIELD_END = new RegExp(`[,，]\\s*(?=(?:${LOG_FIELDS})\\s*=)|[;；]\\s*|$`);
const FIELD_ZH = { title: '标题', status: '状态改为', owner: '负责', workspace: '工作区', pane: '终端', agent: 'agent',
  branch: '分支', worktree: '工作树', base: '基线', brief: '任务书', commit: '提交', release: '发布', parent: '属于' };
const RETIRED_ZH = { terminal: '终端', worktree: '工作树', branch: '分支' };
export function logText(lang, text, whole = false) {
  const zh = lang === 'zh';
  let rest = typeof text === 'string' ? text.trim() : '';
  const fields = [];
  for (let found = LOG_FIELD.exec(rest); found; found = LOG_FIELD.exec(rest)) {
    const after = rest.slice(found[0].length), end = LOG_FIELD_END.exec(after);
    fields.push([found[1], after.slice(0, end.index).trim()]);
    rest = after.slice(end.index + end[0].length);
    if (/^[;；]/.test(end[0])) break;
  }
  if (fields.length) {
    if (rest.trim() || !whole) return rest.trim();
    return zh ? fields.map(([key, value]) => (key === 'status' ? `${FIELD_ZH.status}${word('zh', value)}` : `${FIELD_ZH[key]} ${value}`)).join('，')
      : fields.map(([key, value]) => `${key}=${value}`).join(', ');
  }
  if (!zh) return rest;
  let found = /^registered \((\w+)\)$/.exec(rest);
  if (found) return `登记（${word('zh', found[1])}）`;
  found = /^dispatched to (\S+) \(([^()]*)\)$/.exec(rest);
  if (found) return `派给 ${found[1]}（${found[2]}）`;
  found = /^retired: worktree and branch (\S+)$/.exec(rest);
  if (found) return `已回收：工作树和分支 ${found[1]}`;
  found = /^retired: removed (.+?)(?:; branch (\S+) is kept: (.+))?$/.exec(rest);
  if (!found) return rest;
  const removed = found[1] === 'nothing' ? '没有要清理的' : found[1].split(', ')
    .map(item => item.replace(/^(terminal|worktree|branch) /, (_all, kind) => `${RETIRED_ZH[kind]} `)).join('、');
  const why = (found[3] || '').replace(/^checked out in (.+)$/, '在 $1 检出着').replace(/^git refused to delete it$/, 'git 拒绝删除');
  return `已回收：${removed}${found[2] ? `；分支 ${found[2]} 保留：${why}` : ''}`;
}

// Copies of pm-dash/model.js (a mod cannot import from another mod's folder);
// model.test.mjs checks that they stay identical.
export const LEDGER_HOME_SH = 'if [ -n "$PM_HOME" ]; then printf %s "$PM_HOME"; ' +
  'elif [ -d "$HOME/.claude/pm" ]; then printf %s "$HOME/.claude/pm"; else printf %s "$HOME/.dudu"; fi';
export function cleanTaskLog(latest) {
  const text = typeof latest === 'string' ? latest.trim() : '';
  const prefix = /^status\s*=\s*[\w-]+(?:\s*[,;，；]\s*commit\s*=\s*([^\s,;，；]+))?\s*(?:[,;，；]\s*|$)/.exec(text);
  return { text: prefix ? text.slice(prefix[0].length).trim() : text, commit: prefix?.[1] || '' };
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

// What Esc does on a project's conversation page, one layer a press. The project's box answering a
// question card in the user's own words (answering) stops answering first, its words kept; then a box
// being typed in that holds words (typing) lets go of the keyboard and nothing else, so a press never
// takes a draft off screen; then an open thread's detail closes back to the thread list; then a
// thread list the header's icon slid open over a narrow window (listOpen) closes. Otherwise nothing:
// the conversation is the top (its board is pm-dash's page, which goes back here by itself).
export function escapeStep({ answering = false, typing = false, detail = false, listOpen = false } = {}) {
  if (answering) return 'answer';
  if (typing) return 'blur';
  if (detail) return 'detail';
  if (listOpen) return 'list';
  return null;
}

// The side panel's width. The reader drags the edge between it and the conversation; the width
// they leave it at is kept (per viewer, in the view's localStorage) and holds across projects and
// restarts. However wide they asked for, the panel stays at least PANEL_MIN and leaves the
// conversation at least TALK_MIN; a window too narrow for both keeps the panel's minimum and the
// conversation takes what is left. Never wider than the view, so nothing scrolls sideways.
export const PANEL_WIDTH = 360, PANEL_MIN = 260, TALK_MIN = 360;

// `want`: the width asked for (null: the default); `view`: the whole view's width (0 before it is measured).
export function panelWidth(want, view = 0) {
  const asked = Number.isFinite(want) && want > 0 ? want : PANEL_WIDTH;
  const width = Math.round(Math.max(PANEL_MIN, Math.min(asked, view > 0 ? view - TALK_MIN : asked)));
  return view > 0 ? Math.min(width, Math.round(view)) : width;
}

// Where a drag of the panel's left edge leaves its width: `drag` is {x, width} at the press, `x` the
// pointer now; moving left widens the panel. Fitted to the view as panelWidth fits it.
export function draggedWidth(drag, x, view = 0) {
  return panelWidth(drag.width + drag.x - x, view);
}

// The kept width as storage has it: a positive number, or null for the default (nothing kept, or junk).
export function readPanelWidth(text) {
  if (text == null || String(text).trim() === '') return null;
  const n = Number(text);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : null;
}

// The page's block has window_drag: a left press that reaches it moves the window, and a double-click
// maximizes it. The page keeps every press but those on its header's blank space and words, with this
// handler. Stopping the press also stops the root's own focus-on-press, so `keyboard` (the page's
// focus handle) is given the keyboard here instead, for Esc; where something pressed takes the keyboard
// itself (a message box, a reply's selectable words), the press is kept with no handle.
export function keepPressHandler(keyboard) {
  return (_e, cx) => {
    if (keyboard) keyboard.focus();
    cx.stop_propagation();
  };
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
