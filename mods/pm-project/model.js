// Pure parts of the project view: the conversation log turned into a timeline,
// the waiting count, optimistic bubbles, and the words in both languages.

const STRINGS = {
  en: {
    you: 'You', waiting: 'Waiting for you', waitingCount: n => `${n} ${n === 1 ? 'item' : 'items'} waiting for you`,
    nothingWaiting: 'Nothing waiting for you',
    openPm: 'Open the PM terminal', noPmTerminal: 'The PM is not in the desktop app',
    say: name => `Message the ${name} coordinator…`, sayThread: 'Message only this thread…',
    send: 'Send', sendThread: 'Send to this thread',
    offline: 'No PM session of this project is running in the desktop app. Start it, then run pm.py claim.',
    threadOffline: 'This thread has no live terminal',
    openTerminal: 'Open its terminal', diff: 'See the changes', noDiff: 'No branch to compare yet', close: 'Close',
    sending: 'Sending…', failed: error => `Not sent: ${error}`, decision: 'Decision',
    pick: 'Pick a project in the PM list to open its conversation.', noProject: 'This PM is no longer in the ledger.',
    empty: 'Nothing said in this project yet.', readError: 'Could not read the conversation',
    today: 'Today', yesterday: 'Yesterday', noLog: 'No log yet', agent: (program, address) => `${program} · terminal ${address}`,
    unfold: 'Show the whole reply', fold: 'Fold',
    threads: 'Threads', showThreads: 'Show the threads', hideThreads: 'Hide the threads',
    group_waiting: 'Waiting on you', group_review: 'In review', group_working: 'Working', group_paused: 'Paused',
    group_parked: 'Not started',
    groupSessions: 'Sessions', groupFinished: 'Finished', recommended: 'Recommended', openThread: 'Open this thread',
    noThreads: 'No threads in this project yet.', openSession: 'Click opens this session',
    session_working: 'Working', session_blocked: 'Needs you', session_done: 'Done', session_idle: 'Idle',
    in_progress: 'In progress', blocked: 'Blocked', review: 'Review', paused: 'Paused', proposed: 'Proposed',
    merged: 'Merged', released: 'Released', done: 'Done', abandoned: 'Abandoned', cleanup: 'Merged · not retired',
  },
  zh: {
    you: '你', waiting: '等你', waitingCount: n => `${n} 件事等你`, nothingWaiting: '没有等你的事',
    openPm: '打开 PM 终端', noPmTerminal: 'PM 不在桌面里',
    say: name => `对 ${name} 的协调者说…`, sayThread: '只对这个线程说…',
    send: '发送', sendThread: '发给这个线程',
    offline: '这个项目没有在桌面里运行的 PM 会话。启动它，再运行 pm.py claim。',
    threadOffline: '这个线程没有在线的终端',
    openTerminal: '打开终端', diff: '看改动', noDiff: '还没有可以比较的分支', close: '收起',
    sending: '正在发送…', failed: error => `没发出去：${error}`, decision: '决定',
    pick: '在 PM 列表里点一个项目，打开它的对话。', noProject: '台账里已经没有这个 PM。',
    empty: '这个项目还没有对话。', readError: '对话记录读取失败',
    today: '今天', yesterday: '昨天', noLog: '暂无日志', agent: (program, address) => `${program} · 终端 ${address}`,
    unfold: '展开全文', fold: '收起',
    threads: '线程', showThreads: '显示线程列表', hideThreads: '收起线程列表',
    group_waiting: '等你', group_review: '审查中', group_working: '进行中', group_paused: '暂停', group_parked: '未开始',
    groupSessions: '对话', groupFinished: '已结束', recommended: '推荐', openThread: '打开这个线程',
    noThreads: '这个项目还没有线程。', openSession: '点击打开这个对话',
    session_working: '工作中', session_blocked: '等你', session_done: '已完成', session_idle: '空闲',
    in_progress: '进行中', blocked: '阻塞', review: '审查中', paused: '暂停', proposed: '提议',
    merged: '已合并', released: '已发布', done: '完成', abandoned: '放弃', cleanup: '已合并 · 待回收',
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

// The tasks of one PM that wait for the user: the board's rule (pm-dash counts
// blocked tasks under their PM; review is the PM's job), so the two numbers agree.
export function waitingCount(state, pmName) {
  return (Array.isArray(state?.tasks) ? state.tasks : [])
    .filter(t => (t.pm || '') === (pmName || '') && WAITING.includes(t.status)).length;
}

// 'blocked' | 'review' | 'running' | 'quiet': which status color a thread gets.
export function tone(status, cleanup = false) {
  if (cleanup) return 'quiet';
  if (status === 'blocked') return 'blocked';
  if (status === 'review') return 'review';
  return status === 'in_progress' ? 'running' : 'quiet';
}

export function statusLabel(lang, status, cleanup = false) {
  return cleanup ? word(lang, 'cleanup') : word(lang, status || 'in_progress');
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
    const i = events.findIndex((e, n) => !used.has(n) && e.type === 'user' && squash(e.text) === squash(p.text) &&
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

// What a quick answer sends as the user's turn.
export function answerText(title, option) {
  return `【${title}】${option}`;
}

// The timeline, oldest first. Kinds:
//   day       a date divider
//   user      the user's words (right bubble); pending/failed for an unconfirmed one
//   pm        the coordinator's reply (markdown): {text, lead, long, by}; a long one folds to its lead;
//             by: the session that spoke ('' in logs from before replies recorded it)
//   threads   adjacent thread rows: {rows: [{task, title, status, latest, waiting, tone, cleanup, closed}]};
//             a task that is abandoned now has no row and no `about`
//   about     a later ledger entry of a thread that already showed: {task, title, by (who wrote
//             it)}. turns() keeps the ones the coordinator wrote, to name what its reply is about.
//   question  the event that blocked a task: {task, title, text, options, notes, recommended, open,
//             chosen}. notes: a line of explanation per option ('' for none); recommended: the first
//             option is the coordinator's pick; chosen: the option the user picked (its place in
//             options, from a quick answer in the log or one still being sent), else -1. A task that
//             enters the log blocked (the coordinator asking) is this alone; it gets its thread row
//             where it first becomes work, if it ever does.
//   decision  a recorded decision
//   typing    the coordinator is working
// tasks: `pm.py state` tasks; a task's row shows what it is now, falling back to
// its newest event here once the ledger no longer lists it. `agent` events are not shown.
export function timeline(events, tasks = [], { pending = [], typing = false, today = '' } = {}) {
  const byId = new Map((tasks || []).map(t => [t.id, t]));
  const newest = new Map();
  for (const e of events) if (e.type === 'thread' && e.task) newest.set(e.task, e);
  const now = id => {
    const t = byId.get(id), last = newest.get(id) || {};
    const status = t?.status || last.status || '', cleanup = Boolean(t?.cleanup);
    return { status, cleanup, title: t?.title || last.title || id,
      latest: cleanTaskLog(t ? t.latest : last.text).text, waiting: !cleanup && WAITING.includes(status), tone: tone(status, cleanup),
      closed: CLOSED.includes(status) };
  };
  const items = [], shown = new Set(), asked = new Set(), before = new Map(), keys = new Map(), questions = [];
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
      const item = { kind: e.type, key: key(e, e.type), text: String(e.text).trim() };
      if (e.type === 'user') {
        // A quick answer in the log marks the option it picked, on the newest question that offered it.
        const said = squash(e.text);
        const hit = [...questions].reverse().find(q => q.chosen < 0 && q.options.some(o => squash(answerText(q.title, o)) === said));
        if (hit) hit.chosen = hit.options.findIndex(o => squash(answerText(hit.title, o)) === said);
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
      if (!known && e.status === 'blocked') asked.add(e.task);
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
      if (e.status === 'blocked' && was !== 'blocked') {
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
    items.push({ kind: 'user', key: `pending:${p.id}`, text: p.text, pending: !p.failed, failed: p.failed || '' });
    // A quick answer on its way already shows as the picked option.
    const asking = p.question && !p.failed ? questions.find(q => q.key === p.question) : null;
    if (asking && asking.chosen < 0) asking.chosen = asking.options.findIndex(o => squash(answerText(asking.title, o)) === squash(p.text));
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
//             updated, branch}; group: 'waiting' (blocked) | 'review' | 'working' (in progress) |
//             'paused' | 'parked' (proposed), in that order
//   sessions  the agents in the window whose folder is the project's or one of its worktrees, except
//             the PM and the workers of open tasks (their task's row stands for them):
//             {address, label, status, program}; the app's order: needs you, done, working, idle
//   finished  the newest FINISHED_LIMIT threads that are over: {task, title, status, cleanup};
//             an answered question (see questionOnly) is not one, nor is an abandoned task
// tasks: `pm.py state` tasks; events: the conversation log; terms: terminals(); live: agents();
// tabs: every space's tabs ({id, name, named}).
export const FINISHED_LIMIT = 6;
const OPEN_ORDER = ['blocked', 'review', 'in_progress', 'paused', 'proposed'];
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
const trimFolder = path => typeof path === 'string' && path ? path.replace(/\/+$/, '') || '/' : '';
export function threadList(pm, tasks, events, terms = [], live = [], tabs = []) {
  const mine = (Array.isArray(tasks) ? tasks : []).filter(t => (t.pm || '') === (pm?.name || ''));
  const local = (terms || []).filter(x => x.state === 'live' && x.address && !x.address.includes('/'));
  const atWork = workingTasks(terms, live);
  const rank = status => { const i = OPEN_ORDER.indexOf(status); return i < 0 ? OPEN_ORDER.length : i; };
  const open = mine.filter(t => !CLOSED.includes(t.status))
    .sort((a, b) => rank(a.status) - rank(b.status) || String(b.updated || '').localeCompare(String(a.updated || '')))
    .map(t => ({ task: t.id, title: t.title || t.id, status: t.status || '', tone: tone(t.status), waiting: WAITING.includes(t.status),
      group: GROUP[t.status] || 'parked', latest: cleanTaskLog(t.latest).text, updated: String(t.updated || ''),
      branch: String(t.branch || ''), working: atWork.has(t.id) }));

  const roots = [trimFolder(pm?.repo), trimFolder(pm?.worktrees)].filter(Boolean);
  const within = cwd => roots.some(root => cwd === root || cwd.startsWith(root === '/' ? root : `${root}/`));
  const pmAddress = pm ? terminalFor(pmRow(pm), terms || [])?.address : '';
  const openIds = new Set(open.map(row => row.task));
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
  for (const e of events || []) {
    if (e.type !== 'thread' || !e.task || questions.has(e.task)) continue;
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
export function bellTarget(items) {
  for (let i = items.length - 1; i >= 0; i--) if (items[i].kind === 'question' && items[i].open) return i;
  for (let i = items.length - 1; i >= 0; i--) if (items[i].kind === 'threads' && items[i].rows.some(r => r.waiting)) return i;
  return -1;
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

// A PM from `pm.py state` as a row the terminal lookup understands (as pm-list builds it).
export function pmRow(pm) {
  return pm ? { ...pm, type: 'pm', machine: '', sourceName: pm.name } : null;
}

// A ledger task (or a state task) as a row the terminal lookup understands.
export function taskRow(task) {
  return task ? { ...task, type: 'task', task: task.id, machine: '' } : null;
}

// "<1m", "5m", "3h", "2d": the largest whole unit (pm-list's rule; model.test.mjs keeps the copy identical).
const UNITS = [[86400000, 'd'], [3600000, 'h'], [60000, 'm']];
export function age(ms) {
  const unit = UNITS.find(([size]) => ms >= size);
  return unit ? `${Math.floor(ms / unit[0])}${unit[1]}` : '<1m';
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
