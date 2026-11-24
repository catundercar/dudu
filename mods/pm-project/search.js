// Unified Project Search engine & overlay UI builder (Interface I).
// Pure module importing only from ./model.js (zero direct gpui-kit/gpui-base/herdr imports so Node tests can import it directly).

import {
  word, withAlpha, isDarkTheme, squash, searchTerms,
  highlightSegments, windowAroundMatch, searchLibrary, searchMemory,
  taskNumber, formatTaskNumber, statusLabel, tone, disconnected,
  isClosedTask, CLOSED, foldReviews, questionOnly, logText, clock,
  age, eventTime, contextDay, fileName,
} from './model.js';

export const SEARCH_SCOPES = ['all', 'threads', 'messages', 'decisions', 'library'];
export const SEARCH_GROUP_CAP = 6;
export const SEARCH_SCOPED_CAP = 50;
export const SEARCH_RECENT_THREADS = 5;
export const SEARCH_RECENT_DECISIONS = 4;

const MENTION_LINK_CLEAN_RE = /\[@([^\]]+)\]\((?:thread|session|library|file):[^)]+\)/g;
const IMAGE_MARK_RE = /\[Image #\d+\][ \t]*/g;

export function cleanMessageForSearch(text) {
  return squash(
    String(text ?? '')
      .replace(MENTION_LINK_CLEAN_RE, '@$1')
      .replace(IMAGE_MARK_RE, ''),
  );
}

function isSubsequence(needle, hay) {
  if (!needle) return true;
  if (needle.length > hay.length) return false;
  let j = 0;
  for (let i = 0; i < hay.length && j < needle.length; i++) {
    if (hay[i] === needle[j]) j++;
  }
  return j === needle.length;
}

function segmentMatch(hay, needle) {
  const idx = hay.indexOf(needle);
  if (idx < 0) return -1;
  if (idx === 0) return 0;
  return /[^a-z0-9]/.test(hay[idx - 1]) ? 1 : 2;
}

export function scoreSearchMatch(queryLow, terms, primaryLow, secondaryLow = '', bodyLow = '') {
  if (!terms.length) return 1;
  const combined = [primaryLow, secondaryLow, bodyLow].filter(Boolean).join(' ');
  if (terms.every(t => combined.includes(t))) {
    if (primaryLow === queryLow) return 1000;
    if (primaryLow.startsWith(queryLow)) return 850;
    const pSeg = segmentMatch(primaryLow, queryLow);
    if (pSeg === 0 || pSeg === 1) return 700;
    if (terms.every(t => primaryLow.includes(t))) return 550;
    if (secondaryLow && secondaryLow.includes(queryLow)) return 420;
    const headCombined = secondaryLow ? `${primaryLow} ${secondaryLow}` : primaryLow;
    if (terms.every(t => headCombined.includes(t))) return 340;
    if (bodyLow && bodyLow.includes(queryLow)) return 260;
    return 180;
  }
  if (terms.length === 1 && queryLow.length >= 2) {
    const first = queryLow[0];
    if (primaryLow.includes(first) && isSubsequence(queryLow, primaryLow)) return 120;
    if (secondaryLow && secondaryLow.includes(first) && isSubsequence(queryLow, secondaryLow)) return 80;
  }
  return 0;
}

function threadGroupOf(t) {
  const status = String(t?.status || '');
  if (CLOSED.includes(status)) return 'finished';
  if (disconnected(t)) return 'offline';
  if (status === 'blocked' && !t.answered) return 'waiting';
  if (status === 'paused') return 'paused';
  if (status === 'proposed') return 'parked';
  return 'working';
}

export function searchProjectThreads({
  pm,
  tasks = [],
  stateEvents = [],
  events = [],
  threadId = '',
  threadLog = null,
  retiredParts = [],
  lang = 'en',
  query = '',
  now = Date.now(),
} = {}) {
  const pmName = pm?.name || '';
  const qRaw = String(query ?? '').trim();
  const qLow = qRaw.toLowerCase();
  const terms = searchTerms(qRaw);

  const rawTasks = Array.isArray(tasks) ? tasks : [];
  const mineRaw = rawTasks.filter(t => t?.id && (!pmName || !t.pm || t.pm === pmName));
  const folded = mineRaw.some(t => t.review) ? mineRaw : foldReviews(mineRaw);

  const taskMap = new Map();
  const reviewParent = new Map();
  for (const t of folded) {
    if (!t?.id) continue;
    if (t.review?.id) reviewParent.set(t.review.id, t.id);
    if (t.status === 'abandoned') continue;
    taskMap.set(t.id, t);
  }
  for (const t of Array.isArray(retiredParts) ? retiredParts : []) {
    if (!t?.id || t.status === 'abandoned') continue;
    if (pmName && t.pm && t.pm !== pmName) continue;
    if (!taskMap.has(t.id)) taskMap.set(t.id, t);
  }

  const questions = questionOnly(events);
  const evList = Array.isArray(events) ? events : [];
  for (const e of evList) {
    if (e?.type !== 'thread' || !e.task || questions.has(e.task)) continue;
    if (reviewParent.has(e.task)) continue;
    if (/-review$/.test(e.task) && taskMap.has(e.task.slice(0, -'-review'.length))) continue;
    if (!taskMap.has(e.task) && e.status !== 'abandoned') {
      taskMap.set(e.task, {
        id: e.task,
        title: e.title || e.task,
        status: e.status || 'done',
        latest: e.text || '',
        updated: e.at || '',
        pm: pmName,
      });
    }
  }

  // Collect newest-first deduplicated logs per thread id (plus folded review logs).
  const logsByTask = new Map();
  const pushLog = (id, text) => {
    const clean = logText(lang, text, true);
    if (!clean) return;
    let list = logsByTask.get(id);
    if (!list) { list = []; logsByTask.set(id, list); }
    if (!list.includes(clean)) list.push(clean);
  };
  for (const [id, t] of taskMap) {
    if (t.latest) pushLog(id, t.latest);
    if (t.review?.latest) pushLog(id, t.review.latest);
  }
  for (let i = (Array.isArray(stateEvents) ? stateEvents.length : 0) - 1; i >= 0; i--) {
    const e = stateEvents[i];
    const id = reviewParent.get(e?.task) || e?.task;
    if (id && taskMap.has(id) && e?.text) pushLog(id, e.text);
  }
  for (let i = evList.length - 1; i >= 0; i--) {
    const e = evList[i];
    if (e?.type !== 'thread' || !e.task || !e.text) continue;
    const id = reviewParent.get(e.task) || e.task;
    if (taskMap.has(id)) pushLog(id, e.text);
  }
  if (threadId && Array.isArray(threadLog?.entries)) {
    const id = reviewParent.get(threadId) || threadId;
    if (taskMap.has(id)) {
      for (let i = threadLog.entries.length - 1; i >= 0; i--) {
        const entry = threadLog.entries[i];
        if (entry?.text) pushLog(id, entry.text);
      }
    }
  }

  const numHashMatch = /^#(\d+)$/.exec(qLow);
  const rows = [];
  for (const [id, t] of taskMap) {
    const num = taskNumber(t);
    const numTag = formatTaskNumber(t);
    const title = t.title || id;
    const offline = disconnected(t);
    const closedInfo = isClosedTask({ ...t, offline }) ? t.closed : null;
    const group = threadGroupOf(t);
    const tn = tone(t.status, Boolean(t.cleanup), offline, Boolean(t.answered));
    const statusText = statusLabel(lang, t.status, Boolean(t.cleanup), offline, Boolean(t.answered), Boolean(closedInfo));
    const logs = logsByTask.get(id) || [];
    const latestClean = logs[0] || '';
    const updated = String(t.updated || '');
    const at = eventTime(updated);
    const ageText = at > 0 ? age(Math.max(0, now - at), lang) : '';

    if (!terms.length) {
      const activeScore = group === 'waiting' ? 500
        : group === 'working' ? 400
        : group === 'offline' ? 300
        : group === 'paused' ? 200
        : group === 'parked' ? 150 : 50;
      rows.push({
        kind: 'thread',
        key: `thread:${id}`,
        task: id,
        num,
        numTag,
        title,
        status: t.status || '',
        statusText,
        tone: tn,
        group,
        offline,
        closed: closedInfo,
        reviewTitle: t.review?.title || '',
        branch: String(t.branch || ''),
        snippet: latestClean,
        matchInLog: false,
        updated,
        ageText,
        score: activeScore,
      });
      continue;
    }

    const primaryLow = `${numTag ? `${numTag} ` : ''}${title}`.toLowerCase();
    const secondaryLow = [id, num != null ? String(num) : '', t.branch || '', statusText, t.review?.id || '', t.review?.title || '']
      .filter(Boolean).join(' ').toLowerCase();
    const logHayLow = logs.join(' ').toLowerCase();

    let numBoost = 0;
    if (num != null && (qLow === `#${num}` || qLow === String(num))) numBoost = 1200;
    else if (numHashMatch && numTag && numTag.startsWith(qLow)) numBoost = 950;

    let score = Math.max(numBoost, scoreSearchMatch(qLow, terms, primaryLow, secondaryLow, logHayLow));
    if (numHashMatch && numBoost === 0 && !(`${primaryLow} ${secondaryLow} ${logHayLow}`).includes(qLow)) {
      score = 0;
    }
    if (score <= 0) continue;

    const headLow = `${primaryLow} ${secondaryLow}`;
    const inHead = terms.every(term => headLow.includes(term));
    let snippet = latestClean;
    let matchInLog = false;
    if (!inHead && logs.length) {
      const hitLog = logs.find(line => terms.every(term => line.toLowerCase().includes(term)))
        || logs.find(line => terms.some(term => line.toLowerCase().includes(term)));
      if (hitLog) {
        snippet = hitLog;
        matchInLog = true;
      }
    }

    rows.push({
      kind: 'thread',
      key: `thread:${id}`,
      task: id,
      num,
      numTag,
      title,
      status: t.status || '',
      statusText,
      tone: tn,
      group,
      offline,
      closed: closedInfo,
      reviewTitle: t.review?.title || '',
      branch: String(t.branch || ''),
      snippet,
      matchInLog,
      updated,
      ageText,
      score,
    });
  }

  rows.sort((a, b) =>
    b.score - a.score
    || (a.group === 'finished') - (b.group === 'finished')
    || b.updated.localeCompare(a.updated)
    || a.title.localeCompare(b.title),
  );
  return !terms.length ? rows.slice(0, SEARCH_RECENT_THREADS) : rows;
}

export function searchProjectMessages({
  items = [],
  lang = 'en',
  today = '',
  query = '',
} = {}) {
  const qRaw = String(query ?? '').trim();
  const qLow = qRaw.toLowerCase();
  const terms = searchTerms(qRaw);
  if (!terms.length) return [];

  const list = Array.isArray(items) ? items : [];
  const hits = [];
  for (let i = 0; i < list.length; i++) {
    const item = list[i];
    if (!item || (item.kind !== 'user' && item.kind !== 'pm' && item.kind !== 'question')) continue;

    let displayText = '';
    let extraHay = '';
    let speaker = '';
    if (item.kind === 'user') {
      const clean = cleanMessageForSearch(item.text);
      const files = Array.isArray(item.files) ? item.files.map(fileName).join(' ') : '';
      displayText = clean || files;
      extraHay = `${item.text || ''} ${files}`;
      speaker = word(lang, 'searchMsgYou');
    } else if (item.kind === 'pm') {
      displayText = cleanMessageForSearch(item.text);
      extraHay = String(item.text || '');
      speaker = word(lang, 'searchMsgPm');
    } else {
      const qClean = cleanMessageForSearch(item.text);
      const optsText = [
        ...(Array.isArray(item.options) ? item.options : []),
        ...(Array.isArray(item.notes) ? item.notes : []),
      ].filter(Boolean).join(' · ');
      displayText = [qClean, optsText].filter(Boolean).join(' · ');
      extraHay = `${item.title || ''} ${item.text || ''} ${optsText}`;
      speaker = item.title ? `${word(lang, 'searchMsgQuestion')} · ${item.title}` : word(lang, 'searchMsgQuestion');
    }

    const hayLow = `${displayText} ${extraHay}`.toLowerCase();
    if (!terms.every(term => hayLow.includes(term))) continue;
    const score = displayText.toLowerCase().includes(qLow) ? 300 : 200;
    const snippet = windowAroundMatch(displayText || extraHay, terms, 108, 36);
    hits.push({
      kind: 'message',
      key: `msg:${item.key}`,
      itemKey: item.key,
      msgKind: item.kind,
      speaker,
      timeLabel: clock(item.at, today),
      snippet,
      at: item.at || '',
      order: i,
      score,
    });
  }

  hits.sort((a, b) => b.score - a.score || b.order - a.order);
  return hits;
}

export function searchProjectDecisions({
  memoryData = null,
  items = [],
  docCache = null,
  lang = 'en',
  currentYear = '',
  today = '',
  query = '',
} = {}) {
  const qRaw = String(query ?? '').trim();
  const qLow = qRaw.toLowerCase();
  const terms = searchTerms(qRaw);
  const list = Array.isArray(items) ? items : [];

  if (!terms.length) {
    const files = Array.isArray(memoryData?.files) ? memoryData.files : [];
    const recentMem = files
      .filter(m => m && m.layer === 'project' && (m.type === 'project' || m.type === 'feedback'))
      .sort((a, b) => String(b.modified || '').localeCompare(String(a.modified || '')) || String(a.name || '').localeCompare(String(b.name || '')))
      .slice(0, SEARCH_RECENT_DECISIONS)
      .map(m => ({
        kind: 'memory',
        key: `mem:${m.root}/${m.path}`,
        root: m.root,
        path: m.path,
        title: m.name,
        desc: m.description || '',
        type: m.type || 'project',
        typeLabel: word(lang, `memType_${m.type || 'project'}`),
        topicLabel: m.topic ? word(lang, `topic_${m.topic}`) : '',
        layerLabel: word(lang, 'memLayerProject'),
        modified: contextDay(m.modified, currentYear),
        dimmed: false,
      }));
    if (recentMem.length) return recentMem;
    const evDecisions = [];
    for (let i = list.length - 1; i >= 0 && evDecisions.length < SEARCH_RECENT_DECISIONS; i--) {
      const it = list[i];
      if (it?.kind !== 'decision') continue;
      evDecisions.push({
        kind: 'decisionEvent',
        key: `dec:${it.key}`,
        itemKey: it.key,
        title: it.text,
        desc: it.quote ? word(lang, 'memQuote', it.quote) : '',
        typeLabel: word(lang, 'searchDecisionEvent'),
        modified: clock(it.at, today),
        dimmed: false,
      });
    }
    return evDecisions;
  }

  const memRows = memoryData ? searchMemory(memoryData, qRaw, docCache, lang, currentYear) : [];
  const coveredNorms = new Set();
  const tierOf = r => {
    if (r.type === 'pitfall') return 4;
    if (r.layer === 'project' && r.type === 'project') return 0;
    if (r.layer === 'project' && r.type === 'feedback') return 1;
    if (r.layer === 'project') return 2;
    return 3;
  };
  const ranked = memRows.map((r, idx) => {
    const dNorm = squash(r.file?.description || r.desc || '').toLowerCase();
    const qNorm = squash(r.file?.quote || '').toLowerCase();
    if (dNorm) coveredNorms.add(dNorm);
    if (qNorm) coveredNorms.add(qNorm);
    return {
      tier: tierOf(r),
      order: idx,
      hit: {
        kind: 'memory',
        key: `mem:${r.key}`,
        root: r.root,
        path: r.path,
        title: r.title,
        desc: r.desc,
        type: r.type,
        typeLabel: r.typeLabel,
        topicLabel: r.topicLabel,
        layerLabel: r.layerLabel,
        modified: r.modified,
        dimmed: Boolean(r.dimmed),
      },
    };
  });

  for (let i = list.length - 1; i >= 0; i--) {
    const it = list[i];
    if (it?.kind !== 'decision') continue;
    const textLow = String(it.text || '').toLowerCase();
    const quoteLow = String(it.quote || '').toLowerCase();
    const hay = `${textLow} ${quoteLow}`;
    if (!terms.every(term => hay.includes(term))) continue;
    const textNorm = squash(it.text).toLowerCase();
    if (textNorm && [...coveredNorms].some(c => c.includes(textNorm) || textNorm.includes(c))) continue;
    const exact = textLow.includes(qLow) ? 0 : 1;
    ranked.push({
      tier: 0.5 + exact * 0.1,
      order: list.length - i,
      hit: {
        kind: 'decisionEvent',
        key: `dec:${it.key}`,
        itemKey: it.key,
        title: it.text,
        desc: it.quote ? word(lang, 'memQuote', it.quote) : '',
        typeLabel: word(lang, 'searchDecisionEvent'),
        modified: clock(it.at, today),
        dimmed: false,
      },
    });
  }

  ranked.sort((a, b) => a.tier - b.tier || a.order - b.order);
  return ranked.map(x => x.hit);
}

export function searchProjectLibrary({
  libraryFiles = [],
  docCache = null,
  lang = 'en',
  currentYear = '',
  query = '',
} = {}) {
  const qRaw = String(query ?? '').trim();
  if (!qRaw || !Array.isArray(libraryFiles) || !libraryFiles.length) return [];
  return searchLibrary(libraryFiles, qRaw, docCache, lang, currentYear).map(r => ({
    kind: 'library',
    key: `lib:${r.key}`,
    root: r.root,
    path: r.path,
    title: r.title,
    desc: r.desc,
    kindLabel: r.kindLabel,
    modified: r.modified,
    archive: Boolean(r.archive),
    row: r,
  }));
}

export function buildProjectSearch({
  pm = null,
  tasks = [],
  stateEvents = [],
  events = [],
  items = [],
  threadId = '',
  threadLog = null,
  retiredParts = [],
  memoryData = null,
  libraryFiles = [],
  docCache = null,
  librarySupported = true,
  memorySupported = true,
  lang = 'en',
  today = '',
  query = '',
  scope = 'all',
  now = Date.now(),
} = {}) {
  const qRaw = String(query ?? '').trim();
  const terms = searchTerms(qRaw);
  const currentYear = String(today || '').slice(0, 4);

  const threads = searchProjectThreads({
    pm, tasks, stateEvents, events, threadId, threadLog, retiredParts, lang, query: qRaw, now,
  });
  const messages = searchProjectMessages({ items, lang, today, query: qRaw });
  const decisions = memorySupported
    ? searchProjectDecisions({ memoryData, items, docCache, lang, currentYear, today, query: qRaw })
    : searchProjectDecisions({ memoryData: null, items, docCache: null, lang, currentYear, today, query: qRaw });
  const library = librarySupported
    ? searchProjectLibrary({ libraryFiles, docCache, lang, currentYear, query: qRaw })
    : [];

  const availableScopes = ['all', 'threads', 'messages', 'decisions', ...(librarySupported ? ['library'] : [])];
  const activeScope = availableScopes.includes(scope) ? scope : 'all';

  const counts = {
    threads: threads.length,
    messages: messages.length,
    decisions: decisions.length,
    library: library.length,
    all: threads.length + messages.length + decisions.length + library.length,
  };

  const scopes = availableScopes.map(id => ({
    id,
    label: word(lang, id === 'all' ? 'searchScopeAll'
      : id === 'threads' ? 'searchScopeThreads'
      : id === 'messages' ? 'searchScopeMessages'
      : id === 'decisions' ? 'searchScopeDecisions'
      : 'searchScopeLibrary'),
    count: counts[id] || 0,
  }));

  const pool = [
    { id: 'threads', title: word(lang, !terms.length ? 'searchRecentThreads' : 'searchGroupThreads'), rows: threads },
    { id: 'messages', title: word(lang, 'searchGroupMessages'), rows: messages },
    { id: 'decisions', title: word(lang, !terms.length ? 'searchRecentDecisions' : 'searchGroupDecisions'), rows: decisions },
    ...(librarySupported ? [{ id: 'library', title: word(lang, 'searchGroupLibrary'), rows: library }] : []),
  ];

  const groups = [];
  const flat = [];
  const cap = activeScope === 'all' ? SEARCH_GROUP_CAP : SEARCH_SCOPED_CAP;

  for (const g of pool) {
    if (activeScope !== 'all' && g.id !== activeScope) continue;
    if (!g.rows.length) continue;
    const shown = g.rows.slice(0, cap);
    const itemsWithMore = [...shown];
    if (activeScope === 'all' && terms.length && g.rows.length > SEARCH_GROUP_CAP) {
      itemsWithMore.push({
        kind: 'more',
        key: `more:${g.id}`,
        scope: g.id,
        total: g.rows.length,
        shown: shown.length,
      });
    }
    const startIndex = flat.length;
    for (const row of itemsWithMore) flat.push(row);
    groups.push({
      id: g.id,
      title: g.title,
      total: g.rows.length,
      items: itemsWithMore,
      startIndex,
    });
  }

  let earliestAt = '';
  for (const e of Array.isArray(events) ? events : []) {
    if (e?.at && (!earliestAt || String(e.at) < earliestAt)) earliestAt = String(e.at);
  }
  const earliestLoadedDate = earliestAt ? contextDay(earliestAt, currentYear) : '';

  return {
    query: qRaw,
    terms,
    activeScope,
    scopes,
    counts,
    groups,
    flat,
    earliestLoadedDate,
  };
}

export function stepSearchSelection(flat, currentIndex = 0, currentKey = '', delta = 0) {
  const list = Array.isArray(flat) ? flat : [];
  if (!list.length) return { index: 0, key: '' };
  let base = currentKey ? list.findIndex(r => r.key === currentKey) : -1;
  if (base < 0) base = Math.max(0, Math.min(Number(currentIndex) || 0, list.length - 1));
  const next = ((base + delta) % list.length + list.length) % list.length;
  return { index: next, key: list[next]?.key || '' };
}

export function stepSearchScope(currentScope, scopes, delta = 1) {
  const ids = (Array.isArray(scopes) ? scopes : SEARCH_SCOPES).map(s => typeof s === 'string' ? s : s.id).filter(Boolean);
  if (!ids.length) return 'all';
  const cur = ids.indexOf(currentScope);
  const base = cur >= 0 ? cur : 0;
  return ids[((base + delta) % ids.length + ids.length) % ids.length];
}

export function stepSearchEscape({ query = '', scope = 'all' } = {}) {
  if (String(query ?? '').trim()) return { action: 'clear' };
  if (scope && scope !== 'all') return { action: 'resetScope' };
  return { action: 'close' };
}

export function renderHighlightedText(text, terms, ui, t, {
  maxChars = 96,
  around = 32,
  baseColor,
  textSize = 13,
  fontWeight = 400,
} = {}) {
  const { div, h_flex } = ui;
  const shown = windowAroundMatch(text, terms, maxChars, around);
  if (!shown) return div();
  const segs = highlightSegments(shown, terms);
  const color = baseColor || t.foreground;
  if (!segs.some(s => s.match)) {
    return div().min_w(0).truncate().text_size(textSize).font_weight(fontWeight).text_color(color).child(shown);
  }
  const hiBg = withAlpha(t.accent, isDarkTheme(t) ? .28 : .20);
  return h_flex().min_w(0).overflow_hidden().items_center()
    .text_size(textSize).font_weight(fontWeight).text_color(color)
    .children(segs.map(seg => seg.match
      ? div().flex_none().whitespace_nowrap().px(1.5).rounded(3).bg(hiBg)
          .text_color(t.foreground).font_semibold().child(seg.text)
      : div().flex_none().whitespace_nowrap().child(seg.text)));
}

export function renderProjectSearchOverlay({
  ui,
  theme: t,
  lang = 'en',
  query = '',
  scope = 'all',
  inputState,
  scrollHandle,
  result,
  selectedIndex = 0,
  memoryLoading = false,
  libraryLoading = false,
  earlierEvents = false,
  earlierLoading = false,
  earlierError = '',
  oldRemote = false,
  actions = {},
}) {
  const { div, svg, v_flex, h_flex, Input, Scrollbar, icon, iconButton, threadMark, memoryTypeColor, SPINNER } = ui;
  const q = String(query ?? '').trim();
  const terms = result?.terms || [];
  const groups = result?.groups || [];
  const scopes = result?.scopes || [];

  const scopePills = h_flex().id('project-search-scopes').flex_none().px(12).py(7).gap(4)
    .items_center().border_b(1).border_color(t.border)
    .children(scopes.map(s => {
      const active = s.id === (result?.activeScope || scope);
      const countText = q && s.id !== 'all' && s.count > 0 ? String(s.count) : '';
      return h_flex().id(`project-search-scope-${s.id}`).h(24).px(8).gap(4).rounded(7)
        .items_center().cursor_pointer().text_size(11.5)
        .when(active, el => el.bg(t.raised).text_color(t.foreground).font_medium())
        .when(!active, el => el.text_color(t.muted).hover(st => st.bg(t.hover).text_color(t.foreground)))
        .on_mouse_down('left', (_e, cx) => cx?.stop_propagation?.())
        .on_click((_e, cx) => { cx?.stop_propagation?.(); actions.onScope?.(s.id, cx); })
        .child(s.label)
        .when(Boolean(countText), el => el.child(div().font_family('monospace').text_size(10.5)
          .text_color(active ? t.accent : t.dim).child(countText)));
    }));

  const inputHint = div().absolute().left(0).top(6).right(0).truncate().text_size(13.5).text_color(t.dim)
    .child(word(lang, 'searchProjectPlaceholder'));
  const inputBar = h_flex().id('project-search-input-bar').flex_none().h(46).px(14).gap(9)
    .items_center().border_b(1).border_color(t.border)
    .child(icon('search', 16).text_color(t.muted))
    .child(div().relative().flex_1().min_w(0).h(30).when(!query, el => el.child(inputHint))
      .child(Input.new(inputState).w_full().h(30).items_center().text_size(13.5).text_color(t.foreground)))
    .when(Boolean(memoryLoading || libraryLoading), el => el.child(svg(SPINNER).size(13).flex_none().text_color(t.dim).spin(900)))
    .when(Boolean(query), el => el.child(iconButton('project-search-clear', 'close', word(lang, 'clearSearch'),
      cx => actions.onClear?.(cx), t, 12)))
    .child(h_flex().id('project-search-close').h(22).px(6).rounded(6).flex_none().items_center().justify_center()
      .bg(t.raised).border_1().border_color(t.border).cursor_pointer()
      .font_family('monospace').text_size(10.5).text_color(t.dim)
      .hover(s => s.bg(t.hover).text_color(t.foreground))
      .tooltip(word(lang, 'searchCloseTip')).accessibility_label(word(lang, 'searchCloseTip'))
      .on_mouse_down('left', (_e, cx) => cx?.stop_propagation?.())
      .on_click((_e, cx) => { cx?.stop_propagation?.(); actions.onClose?.(cx); })
      .child('Esc'));

  const renderHitRow = (hit, flatIdx) => {
    const selected = flatIdx === selectedIndex;
    if (hit.kind === 'more') {
      const moreLabel = word(lang, 'searchShowAll', hit.total);
      return h_flex().id(`project-search-more-${hit.scope}`).flex_none().h(28).mx(4).px(10).gap(6).rounded(7)
        .items_center().cursor_pointer().text_size(12).text_color(t.accent)
        .when(selected, el => el.bg(t.raised))
        .when(!selected, el => el.hover(s => s.bg(t.hover)))
        .on_mouse_down('left', (_e, cx) => cx?.stop_propagation?.())
        .on_click((_e, cx) => { cx?.stop_propagation?.(); actions.onPick?.(hit, cx); })
        .child(div().flex_1().min_w(0).truncate().child(moreLabel))
        .child(icon('chevron', 11).text_color(t.accent));
    }

    if (hit.kind === 'thread') {
      const tip = [hit.numTag, hit.title, hit.statusText, hit.snippet].filter(Boolean).join(' · ');
      const markRow = { group: hit.group, status: hit.status, tone: hit.tone, working: false };
      return h_flex().id(`project-search-row-${flatIdx}`).flex_none().w_full().px(10).py(7).gap(9).rounded(8)
        .items_start().cursor_pointer()
        .when(selected, el => el.bg(t.raised))
        .when(!selected, el => el.hover(s => s.bg(t.hover)))
        .tooltip(tip).accessibility_label(tip)
        .on_mouse_down('left', (_e, cx) => cx?.stop_propagation?.())
        .on_click((_e, cx) => { cx?.stop_propagation?.(); actions.onPick?.(hit, cx); })
        .child(h_flex().h(19).w(16).flex_none().items_center().justify_center().child(threadMark(markRow, t)))
        .child(v_flex().flex_1().min_w(0).gap(2)
          .child(h_flex().w_full().gap(6).items_center()
            .when(Boolean(hit.numTag), el => el.child(renderHighlightedText(hit.numTag, terms, ui, t, {
              maxChars: 16, baseColor: t.dim, textSize: 11.5, fontWeight: 500,
            }).font_family('monospace').flex_none()))
            .child(div().flex_1().min_w(0).child(renderHighlightedText(hit.title, terms, ui, t, {
              maxChars: 84, baseColor: hit.group === 'finished' ? t.muted : t.foreground, textSize: 13, fontWeight: 500,
            })))
            .child(div().flex_none().text_size(11).text_color(t.dim).child(hit.statusText))
            .when(Boolean(hit.ageText), el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(hit.ageText))))
          .when(Boolean(hit.snippet), el => el.child(h_flex().w_full().gap(5).items_center()
            .when(Boolean(hit.matchInLog), el => el.child(div().flex_none().px(4).rounded(4).bg(t.surface)
              .border_1().border_color(t.border).text_size(10).text_color(t.dim).child(word(lang, 'searchLogMatch'))))
            .child(div().flex_1().min_w(0).child(renderHighlightedText(hit.snippet, terms, ui, t, {
              maxChars: 96, baseColor: t.dim, textSize: 11.8,
            }))))));
    }

    if (hit.kind === 'message') {
      const glyph = hit.msgKind === 'user' ? 'chat' : hit.msgKind === 'question' ? 'bell' : 'dudu';
      const tip = [hit.speaker, hit.timeLabel, hit.snippet].filter(Boolean).join(' · ');
      return h_flex().id(`project-search-row-${flatIdx}`).flex_none().w_full().px(10).py(7).gap(9).rounded(8)
        .items_start().cursor_pointer()
        .when(selected, el => el.bg(t.raised))
        .when(!selected, el => el.hover(s => s.bg(t.hover)))
        .tooltip(tip).accessibility_label(tip)
        .on_mouse_down('left', (_e, cx) => cx?.stop_propagation?.())
        .on_click((_e, cx) => { cx?.stop_propagation?.(); actions.onPick?.(hit, cx); })
        .child(h_flex().h(19).w(16).flex_none().items_center().justify_center()
          .child(icon(glyph, 13.5).text_color(hit.msgKind === 'question' ? t.blocked : t.muted)))
        .child(v_flex().flex_1().min_w(0).gap(2)
          .child(h_flex().w_full().gap(6).items_center()
            .child(div().flex_1().min_w(0).truncate().text_size(12).font_medium().text_color(t.muted).child(hit.speaker))
            .when(Boolean(hit.timeLabel), el => el.child(div().flex_none().font_family('monospace').text_size(10.5)
              .text_color(t.dim).child(hit.timeLabel))))
          .child(renderHighlightedText(hit.snippet, terms, ui, t, {
            maxChars: 108, around: 36, baseColor: t.foreground, textSize: 12.5,
          })));
    }

    if (hit.kind === 'memory' || hit.kind === 'decisionEvent') {
      const dotColor = hit.kind === 'decisionEvent' ? t.accent : memoryTypeColor(hit.type, t);
      const badgeText = [hit.typeLabel, hit.topicLabel].filter(Boolean).join(' · ');
      const tip = [hit.title, badgeText, hit.desc].filter(Boolean).join(' · ');
      return h_flex().id(`project-search-row-${flatIdx}`).flex_none().w_full().px(10).py(7).gap(9).rounded(8)
        .items_start().cursor_pointer()
        .when(hit.dimmed, el => el.opacity(.78))
        .when(selected, el => el.bg(t.raised))
        .when(!selected, el => el.hover(s => s.bg(t.hover)))
        .tooltip(tip).accessibility_label(tip)
        .on_mouse_down('left', (_e, cx) => cx?.stop_propagation?.())
        .on_click((_e, cx) => { cx?.stop_propagation?.(); actions.onPick?.(hit, cx); })
        .child(h_flex().h(19).w(16).flex_none().items_center().justify_center()
          .child(hit.kind === 'decisionEvent'
            ? icon('check', 13.5).text_color(t.accent)
            : div().size(7).rounded_full().bg(dotColor)))
        .child(v_flex().flex_1().min_w(0).gap(2)
          .child(h_flex().w_full().gap(6).items_center()
            .child(div().flex_1().min_w(0).child(renderHighlightedText(hit.title, terms, ui, t, {
              maxChars: 84, baseColor: hit.dimmed ? t.muted : t.foreground, textSize: 13, fontWeight: 500,
            })))
            .when(Boolean(hit.typeLabel), el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(hit.typeLabel)))
            .when(Boolean(hit.modified), el => el.child(div().flex_none().text_size(10.5).text_color(t.dim).child(hit.modified))))
          .when(Boolean(hit.desc), el => el.child(renderHighlightedText(hit.desc, terms, ui, t, {
            maxChars: 96, baseColor: t.dim, textSize: 11.8,
          }))));
    }

    // Library hit
    const glyph = hit.root === 'research' ? 'report' : hit.root === 'instructions' ? 'lock' : 'file';
    const tip = [hit.title, hit.kindLabel, hit.path, hit.desc].filter(Boolean).join(' · ');
    return h_flex().id(`project-search-row-${flatIdx}`).flex_none().w_full().px(10).py(7).gap(9).rounded(8)
      .items_start().cursor_pointer()
      .when(hit.archive, el => el.opacity(.75))
      .when(selected, el => el.bg(t.raised))
      .when(!selected, el => el.hover(s => s.bg(t.hover)))
      .tooltip(tip).accessibility_label(tip)
      .on_mouse_down('left', (_e, cx) => cx?.stop_propagation?.())
      .on_click((_e, cx) => { cx?.stop_propagation?.(); actions.onPick?.(hit, cx); })
      .child(h_flex().h(19).w(16).flex_none().items_center().justify_center()
        .child(icon(glyph, 13.5).text_color(t.dim)))
      .child(v_flex().flex_1().min_w(0).gap(2)
        .child(h_flex().w_full().gap(6).items_center()
          .child(div().flex_1().min_w(0).child(renderHighlightedText(hit.title, terms, ui, t, {
            maxChars: 84, baseColor: t.foreground, textSize: 13, fontWeight: 500,
          })))
          .when(Boolean(hit.kindLabel), el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(hit.kindLabel)))
          .when(Boolean(hit.modified), el => el.child(div().flex_none().text_size(10.5).text_color(t.dim).child(hit.modified))))
        .when(Boolean(hit.desc), el => el.child(renderHighlightedText(hit.desc, terms, ui, t, {
          maxChars: 96, baseColor: t.dim, textSize: 11.8,
        }))));
  };

  const listChildren = [];
  if (groups.length) {
    groups.forEach((g, gi) => {
      listChildren.push(h_flex().id(`project-search-group-${g.id}`).flex_none()
        .min_h(gi > 0 ? 28 : 22).px(10).when(gi > 0, el => el.pt(6))
        .gap(6).items_center().text_size(11).font_medium().text_color(t.dim)
        .child(g.title)
        .when(Boolean(q), el => el.child(String(g.total))));
      g.items.forEach((item, idx) => listChildren.push(renderHitRow(item, g.startIndex + idx)));
    });
  } else {
    listChildren.push(v_flex().id('project-search-empty').flex_none().px(14).py(22).gap(6).items_center()
      .child(div().text_size(13).text_color(t.muted).whitespace_normal()
        .child(word(lang, q ? 'searchNoMatches' : 'searchEmptyHint')))
      .when(Boolean(q && (earlierEvents || earlierLoading || earlierError)), el => el.child(
        div().text_size(11.5).text_color(t.dim).whitespace_normal().child(word(lang, 'searchNoMatchesEarlier')))));
  }

  const showEarlierFooter = Boolean(earlierEvents || earlierLoading || earlierError);
  const earlierTip = earlierLoading
    ? word(lang, 'searchLoadingEarlier')
    : earlierError
      ? word(lang, 'searchLoadEarlierFailed', earlierError)
      : word(lang, 'searchLoadEarlier');
  const footer = h_flex().id('project-search-footer').flex_none().min_h(34).px(12).py(6).gap(8)
    .items_center().border_t(1).border_color(t.border).bg(t.chrome)
    .when(showEarlierFooter, el => el
      .child(h_flex().flex_1().min_w(0).gap(6).items_center()
        .child(div().min_w(0).truncate().text_size(11.5)
          .text_color(earlierError ? t.blocked : t.dim)
          .child(word(lang, 'searchLoadedOnly', result?.earliestLoadedDate || '')))
        .child(earlierLoading
          ? h_flex().id('project-search-load-earlier').size(24).flex_none().rounded(6).items_center().justify_center()
              .tooltip(earlierTip).accessibility_label(earlierTip)
              .child(svg(SPINNER).size(12).flex_none().text_color(t.muted).spin(900))
          : iconButton('project-search-load-earlier', 'earlier', earlierTip,
              cx => actions.onLoadEarlier?.(cx), t, 13)
              .when(Boolean(earlierError), b => b.text_color(t.blocked))))
      .child(div().flex_none().text_size(10.5).text_color(t.dim).child(word(lang, 'searchNavHintShort'))))
    .when(!showEarlierFooter && oldRemote, el => el
      .child(div().flex_1().min_w(0).truncate().text_size(11.5).text_color(t.dim)
        .child(word(lang, 'searchRemotePartial')))
      .child(div().flex_none().text_size(10.5).text_color(t.dim).child(word(lang, 'searchNavHintShort'))))
    .when(!showEarlierFooter && !oldRemote, el => el
      .child(div().flex_1().min_w(0).truncate().text_size(11).text_color(t.dim)
        .child(word(lang, 'searchNavHint'))));

  const card = v_flex().id('project-search-card').w_full().max_w(580).max_h('100%')
    .rounded(14).bg(t.popover || t.surface).border_1().border_color(t.border).shadow_lg().overflow_hidden()
    .key_context('PmSearchOpen')
    .on_action('pm-search-up', (_e, cx) => { cx.stop_propagation?.(); actions.onMove?.(-1, cx); })
    .on_action('pm-search-down', (_e, cx) => { cx.stop_propagation?.(); actions.onMove?.(1, cx); })
    .on_action('pm-search-accept', (_e, cx) => { cx.stop_propagation?.(); actions.onAccept?.(cx); })
    .on_action('pm-search-escape', (_e, cx) => { cx.stop_propagation?.(); actions.onEscape?.(cx); })
    .on_action('pm-search-scope-next', (_e, cx) => { cx.stop_propagation?.(); actions.onCycleScope?.(1, cx); })
    .on_action('pm-search-scope-prev', (_e, cx) => { cx.stop_propagation?.(); actions.onCycleScope?.(-1, cx); })
    .on_mouse_down('left', (_e, cx) => cx.stop_propagation?.())
    .on_key_down((e, cx) => actions.onKeyDown?.(e, cx))
    .child(inputBar)
    .child(scopePills)
    .child(v_flex().id('project-search-results-wrap').relative().w_full().min_h(0).flex_shrink(1).max_h(440)
      .child(v_flex().id('project-search-results').w_full().min_h(0).flex_shrink(1).max_h(440)
        .px(8).py(6).gap(2).overflow_y_scroll()
        .when(Boolean(scrollHandle), el => el.track_scroll(scrollHandle))
        .children(listChildren))
      .when(Boolean(Scrollbar?.vertical), el => el.child(Scrollbar.vertical('project-search-results').absolute().inset_0())))
    .child(footer);

  return v_flex().id('project-search-backdrop').absolute().left(0).right(0).top(0).bottom(0)
    .items_center().pt(52).pb(48).px(20)
    .bg(withAlpha(t.background || '#000000', isDarkTheme(t) ? .55 : .28))
    .on_mouse_down('left', (_e, cx) => { cx?.stop_propagation?.(); actions.onClose?.(cx); })
    .child(card);
}
