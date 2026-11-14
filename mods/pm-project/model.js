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

// What a quick answer sends as the user's turn.
export function answerText(title, option) {
  return `【${title}】${option}`;
}

// The timeline, oldest first. Kinds:
//   day       a date divider
//   user      the user's words (right bubble); pending/failed for an unconfirmed one
//   pm        the coordinator's reply (markdown): {text, lead, long}; a long one folds to its lead
//   threads   adjacent thread rows: {rows: [{task, title, status, latest, waiting, tone, cleanup, closed}]}
//   question  the event that blocked a task: {task, title, text, options, open}
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
  const items = [], shown = new Set(), before = new Map(), keys = new Map();
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
    items.push({ at: e.at || '', ...item });
  };
  for (const e of events) {
    if (e.type === 'user' || e.type === 'pm') {
      if (!squash(e.text)) continue;
      const item = { kind: e.type, key: key(e, e.type), text: String(e.text).trim() };
      if (e.type === 'pm') {
        const opening = lead(item.text);
        item.lead = opening.text; item.long = opening.more;
      }
      push(e, item);
    } else if (e.type === 'decision') {
      if (squash(e.text)) push(e, { kind: 'decision', key: key(e, 'decision'), text: squash(e.text), quote: squash(e.quote) });
    } else if (e.type === 'thread' && e.task) {
      const was = before.get(e.task);
      before.set(e.task, e.status);
      if (!shown.has(e.task)) {
        shown.add(e.task);
        const row = { task: e.task, ...now(e.task) };
        const last = items[items.length - 1];
        if (last?.kind === 'threads' && String(e.at || '').slice(0, 10) === day) last.rows.push(row);
        else push(e, { kind: 'threads', key: key(e, 'threads'), rows: [row] });
      }
      if (e.status === 'blocked' && was !== 'blocked') {
        push(e, { kind: 'question', key: key(e, 'question'), task: e.task, title: now(e.task).title,
          text: cleanTaskLog(e.text).text, open: false,
          options: (Array.isArray(e.options) ? e.options : []).map(squash).filter(Boolean) });
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
  }
  if (typing) items.push({ kind: 'typing', key: 'typing' });
  return items;
}

// Timeline items in blocks: a day divider, a user bubble, or a coordinator turn {kind: 'turn', parts,
// index} drawn beside one avatar. A turn ends with the coordinator's reply; the reply leads the turn
// and what the coordinator did on the way to it (threads, decisions, questions) follows, as a message
// with its attachments. The working dots are a turn of their own. `index` lists the places in `items`
// of the block's parts.
export function turns(items) {
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
        before.parts.push(...block.parts); before.index.push(...block.index);
        continue;
      }
      block.bare = true;
    }
    kept.push(block);
  }
  for (const block of kept) {
    if (block.kind === 'turn') block.parts = [...block.parts.filter(p => p.kind === 'pm'), ...block.parts.filter(p => p.kind !== 'pm')];
  }
  return kept;
}

// The newest reply is read whole; older long ones fold until the user opens them.
export function newestReply(items) {
  for (let i = items.length - 1; i >= 0; i--) if (items[i].kind === 'pm') return items[i].key;
  return '';
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
