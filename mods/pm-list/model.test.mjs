import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { pmRows, pmStatus, splitArchived, archivedDay, age, lastEventAt, track, listHeight, underNav, remotePmStates, HEADER, ROW, MAX_ROWS, PAD } from './model.js';
import * as list from './model.js';
import * as dash from '../pm-dash/model.js';
import * as nav from '../pm-nav/model.js';

const term = (address, extra = {}) => ({ address, state: 'live', labels: {}, ...extra });

test('rows show the project name, live status by terminal, most urgent first then by name', () => {
  const state = { pms: [
    { name: 'pm-zeta', project: 'zeta', pane: 'hc:t1', status: 'idle' },
    { name: 'pm-alpha', project: 'alpha', pane: 'hc:t2', status: 'idle' },
    { name: 'pm-beta', project: 'beta', pane: 'wX:p1', status: 'working' }, // not in the desktop
    { name: 'pm-gamma', project: 'gamma', pane: 'hc:t4', status: 'idle' },
    { name: 'pm-delta', project: '', pane: 'hc:t5', status: 'idle' },
  ] };
  const terms = [term('t1', { program: { icon: 'icons/claude.svg', tint: true } }), term('t2'),
    term('t4', { labels: { pm: 'gamma' } }), term('t5'), term('box/t1')];
  const live = [{ address: 't1', status: 'done' }, { address: 't2', status: 'blocked' },
    { address: 't4', status: 'working' }];
  const rows = pmRows(state, {}, terms, live);
  assert.deepEqual(rows.map(r => [r.label, r.status]), [
    ['alpha', 'blocked'], ['zeta', 'done'], ['beta', 'working'], ['gamma', 'working'], ['delta', 'unknown']]);
  assert.equal(rows[1].program.icon, 'icons/claude.svg');
  const beta = rows.find(r => r.key === 'pm-beta');
  assert.equal(beta.terminal, null);
  assert.equal(beta.exact, false);
  assert.deepEqual(pmRows({}, {}, [], []), []);
});

test('a PM outside the desktop opens a terminal in its repo, without borrowing its status', () => {
  const pm = { name: 'pm-a', project: 'a', repo: '/r/a/', pane: 'wA:p1', status: 'idle' };
  const terms = [term('t9', { cwd: '/r/a' }), term('t8', { cwd: '/r/a', program: { agent: true } })];
  const [row] = pmRows({ pms: [pm] }, {}, terms, [{ address: 't8', status: 'blocked' }]);
  assert.equal(row.terminal.address, 't8');
  assert.equal(row.exact, false);
  assert.equal(row.status, 'idle');
  assert.equal(row.program, null);
});

test('status words map to the four agent states', () => {
  const t = term('t1', { status: 'working' });
  assert.equal(pmStatus({ status: 'idle' }, t, true, []), 'working'); // terminal status when agents() lacks it
  assert.equal(pmStatus({}, t, true, [{ address: 't1', status: 'error' }]), 'blocked');
  assert.equal(pmStatus({ status: 'mystery' }, null, false, []), 'idle');
  assert.equal(pmStatus({ status: 'working' }, null, false, []), 'working');
});

test('ages read like the agents list', () => {
  assert.deepEqual([0, 59999, 60000, 3599999, 3600000, 86400000 * 2].map(age), ['<1m', '<1m', '1m', '59m', '1h', '2d']);
});

test('a status change stamps now; first sight starts from the last ledger event', () => {
  const events = [{ pm: 'pm-a', at: '2026-11-13 09:21' }, { pm: 'pm-a', at: '2026-11-13 09:25' }, { pm: 'pm-b', at: 'x' }];
  assert.equal(lastEventAt(events, 'pm-a'), new Date('2026-11-13T09:25').getTime());
  assert.equal(lastEventAt(events, 'pm-b'), 0);
  const [a, b] = pmRows({ pms: [{ name: 'pm-a', project: 'a', status: 'working' }, { name: 'pm-b', project: 'b' }], events }, {}, [], []);
  const first = track({}, [a, b], 5);
  assert.deepEqual(first, { 'pm-a': { s: 'working', at: lastEventAt(events, 'pm-a') }, 'pm-b': { s: 'idle', at: 0 } });
  assert.equal(track(first, [a], 9), first); // unchanged: same object
  assert.deepEqual(track(first, [{ ...b, status: 'done' }], 9), first); // done counts as idle
  assert.deepEqual(track(first, [{ ...a, status: 'blocked' }], 9)['pm-a'], { s: 'blocked', at: 9 });
});

test('the block holds the header alone, then grows per row up to a cap', () => {
  assert.equal(listHeight(0, false), HEADER);
  assert.ok(listHeight(1, false) > HEADER);
  assert.equal(listHeight(3, false) - listHeight(2, false), ROW);
  assert.equal(listHeight(MAX_ROWS + 4, false), listHeight(MAX_ROWS, false));
  assert.equal(listHeight(0, true), PAD * 2);
  assert.ok(listHeight(2, true) < listHeight(2, false));
});

test('right under pm-nav the list has no header of its own', () => {
  const block = mod => ({ id: mod, type: 'block', content: { mod } });
  const sidebar = (...mods) => ({ id: 'root', children: [{ id: 'sidebar', children: [{ id: 'brand' }, { id: 'lists', children: mods.map(block) }] }, { id: 'stage' }] });
  assert.equal(underNav(sidebar('pm-nav', 'pm-list', 'spaces', 'agents')), true);
  assert.equal(underNav(sidebar('pm-nav', 'spaces', 'pm-list', 'agents')), false);   // the earlier place: it keeps "PM n"
  assert.equal(underNav(sidebar('pm-list', 'pm-nav')), false);
  assert.equal(underNav(sidebar('spaces')), false);
  assert.equal(underNav(null), false);
  // Without the header: the rows alone, and a sliver while there is no PM.
  assert.equal(listHeight(3, false, false), listHeight(3, false) - HEADER);
  assert.equal(listHeight(0, false, false), PAD);
  assert.equal(listHeight(2, true, false), listHeight(2, true));
});

test('copied ledger and terminal rules stay identical to pm-dash', () => {
  assert.equal(list.LEDGER_HOME_SH, dash.LEDGER_HOME_SH);
  for (const name of ['terminalFor', 'terminalTargetFor', 'focusPlan']) assert.equal(list[name].toString(), dash[name].toString());
});

test('pm-nav counts what waits with the same rule as the rows\' badges', () => {
  assert.equal(nav.waitingCount.toString(), list.waitingCount.toString());
});

test('PMs on other machines come from pm-nav\'s cache and match their own machine\'s terminals', () => {
  const remote = remotePmStates(JSON.stringify({ at: 1, states: {
    dev: { pms: [{ name: 'pm-a', project: 'a', pane: 'hc:t1', repo: '/r/a', status: 'idle' }], tasks: [],
      events: [{ pm: 'pm-a', at: '2026-11-13 08:00' }] },
    broken: { tasks: [] } } }));
  assert.deepEqual(Object.keys(remote), ['dev']);
  const local = { pms: [{ name: 'pm-a', project: 'a', pane: 'hc:t1', status: 'idle' }], events: [] };
  const terms = [term('t1'), term('dev/t1'), term('dev/t2', { cwd: '/r/a' })];
  const rows = pmRows(local, remote, terms, [{ address: 'dev/t1', status: 'blocked' }, { address: 't1', status: 'working' }]);
  assert.deepEqual(rows.map(r => [r.key, r.machine, r.terminal.address, r.status]),
    [['dev/pm-a', 'dev', 'dev/t1', 'blocked'], ['pm-a', '', 't1', 'working']]);
  assert.equal(rows[0].seed, new Date('2026-11-13T08:00').getTime());
  // Without its exact terminal, a remote PM opens a folder terminal on that machine only.
  const [away] = pmRows({}, { dev: { ...remote.dev, pms: [{ ...remote.dev.pms[0], pane: '' }] } }, terms, []);
  assert.equal(away.terminal.address, 'dev/t2');
  assert.equal(away.exact, false);
  for (const text of ['', '{', 'null', '{"states":[]}']) assert.deepEqual(remotePmStates(text), {});
});

test('an age reads in the largest whole unit, in the view\'s language', () => {
  assert.equal(list.age.toString(), dash.age.toString());   // the Projects cards use the same words
  const spans = [0, 59_000, 60_000, 16 * 3_600_000, 2 * 86_400_000 + 5];
  assert.deepEqual(spans.map(ms => age(ms)), ['<1m', '<1m', '1m', '16h', '2d']);
  assert.deepEqual(spans.map(ms => age(ms, 'en')), ['<1m', '<1m', '1m', '16h', '2d']);
  assert.deepEqual(spans.map(ms => age(ms, 'zh')), ['刚刚', '刚刚', '1 分钟', '16 小时', '2 天']);
});

test('an exited PM terminal is not matched as live; a live PM terminal takes over', () => {
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', pane: 'hc:t3b', status: 'idle' };
  const exited = { address: 't3b', state: 'exited', cwd: '/r/dudu', labels: {}, status: 'working' };
  const [row] = pmRows({ pms: [pm] }, {}, [exited], [{ address: 't3b', status: 'working' }]);
  assert.deepEqual([row.terminal, row.exact, row.status], [null, false, 'idle']);
  const next = { address: 't3k', state: 'live', cwd: '/r/dudu', labels: { pm: 'dudu' }, status: 'working' };
  assert.equal(pmRows({ pms: [pm] }, {}, [exited, next], []).at(0).terminal.address, 't3k');
});

test('archived projects leave the list for the fold, newest first; waiting comes from counts', () => {
  const state = { pms: [
    { name: 'pm-dudu', project: 'dudu', status: 'working', archived: null, counts: { waiting: 0 } },
    { name: 'pm-homenet', project: 'homenet', archived: '2026-10-31' },
    { name: 'pm-dsh-dudu', project: 'dsh-dudu', archived: '2026-11-04 10:12' },
    { name: 'pm-liquid', project: 'appkit', counts: { waiting: 2 } },
    { name: 'pm-hub', project: 'hub' },
  ], tasks: [{ id: 'x', pm: 'pm-hub', status: 'blocked' }, { id: 'y', pm: 'pm-homenet', status: 'paused' }] };
  const { active, archived } = splitArchived(pmRows(state, {}, [], []));
  assert.deepEqual(active.map(r => r.label).sort(), ['appkit', 'dudu', 'hub']);
  assert.ok(active.every(r => !r.label.startsWith('PM-')));
  assert.deepEqual(archived.map(r => [r.label, archivedDay(r.archived)]), [['dsh-dudu', '11-04'], ['homenet', '10-31']]);
  assert.deepEqual(active.map(r => [r.label, r.waiting]).sort(), [['appkit', 2], ['dudu', 0], ['hub', 1]]);
  // Without counts (older pm.py), review threads fold before counting waiting so a task and its review count once.
  const old = {
    pms: [{ name: 'pm-hub', project: 'hub' }],
    tasks: [
      { id: 'a', pm: 'pm-hub', status: 'blocked' },
      { id: 'a-review', pm: 'pm-hub', status: 'blocked', review_of: 'a' },
      { id: 'b', pm: 'pm-hub', status: 'review' },
      { id: 'b-review', pm: 'pm-hub', status: 'blocked', review_of: 'b' },
    ],
  };
  assert.equal(pmRows(old, {}, [], [])[0].waiting, 2);
});

// The bug: on a computer connected to another machine's herdr-core, a click on that machine's project
// focused its PM's terminal (`!row.machine` kept remote rows out of the project view).
test("a remote project's row opens the project view, named by its key and machine, not its terminal", async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '').replace('export default class PmList extends View', 'return class');
  const stage = { id: 'pm-stage', active: 'work', children: [{ id: 'work' }, { id: 'pm-board' }, { id: 'pm-project' }] };
  const calls = [];
  const stubs = { View: class {}, opensProject: list.opensProject, projectShared: list.projectShared, focusPlan: list.focusPlan,
    layout: () => ({ id: 'root', children: [stage] }), terminals: () => [], panes: () => [{ terminal: 'box/t73' }], agents: () => [],
    run: (name, args) => calls.push([name, args]), setShared: (key, value) => calls.push(['shared', key, value]) };
  const Mod = new Function('scope', `with (scope) { ${source} }`)(new Proxy(stubs, {
    has: (target, name) => name in target || !(name in globalThis), get: (target, name) => target[name],
  }));
  const [row] = pmRows({ pms: [] }, { box: { pms: [{ name: 'pm-dudu', project: 'dudu', pane: 'hc:t73' }], tasks: [] } },
    [term('box/t73', { labels: { pm: 'dudu' } })], []);
  assert.equal(row.terminal.address, 'box/t73');
  Object.create(Mod.prototype).open(row);
  assert.deepEqual(calls, [['shared', 'pm-project', { pm: 'box/pm-dudu', machine: 'box' }],
    ['layout.select', { stack: 'pm-stage', child: 'pm-project' }]]);
  // A local row is named as before; an older layout without the project page still focuses the terminal.
  assert.deepEqual(list.projectShared({ key: 'pm-dudu', machine: '' }), { pm: 'pm-dudu' });
  assert.equal(list.opensProject(row, { id: 'pm-stage', children: [{ id: 'work' }] }), false);
});

// ---- PMs that report no status (workers are Herdr's Agents list's) ----

test('a PM whose live terminal reports no status is unknown, never idle; one outside the desktop keeps the ledger word', () => {
  const pms = [{ name: 'pm-a', project: 'a', pane: 'hc:t1', status: 'idle' },
    { name: 'pm-b', project: 'b', pane: 'wX:p1', status: 'offline' }];
  const rows = pmRows({ pms }, {}, [term('t1')], []);
  assert.deepEqual(rows.map(r => [r.label, r.status]), [['b', 'idle'], ['a', 'unknown']]);
  assert.equal(pmStatus(pms[0], term('t1', { status: 'working' }), true, []), 'working');
  assert.equal(list.liveStatus(term('t1', { status: 'error' }), []), 'blocked');
  assert.equal(list.RANK.unknown, 0);
});

test('a terminal labelled as a PM that the ledger does not name gets one row, here or on another machine', () => {
  const pm = term('dev/t3', { labels: { pm: 'project' }, program: { icon: 'icons/claude.svg' } });
  const rows = list.allPmRows({ pms: [] }, {}, [pm, pm], []);
  assert.equal(rows.length, 1);
  assert.deepEqual([rows[0].label, rows[0].machine, rows[0].status, rows[0].unregistered, rows[0].exact],
    ['project', 'dev', 'unknown', true, true]);
  assert.equal(rows[0].terminal.address, 'dev/t3');
  assert.equal(list.opensProject(rows[0], { children: [{ id: 'pm-project' }] }), false);
  // Reporting a status, it shows that status.
  assert.equal(list.allPmRows({}, {}, [term('t4', { labels: { pm: 'p' } })], [{ address: 't4', status: 'working' }])[0].status, 'working');
});

test('a PM the ledger names, an exited or unlabelled terminal gets no extra row', () => {
  const pms = [{ name: 'pm-project', project: 'project', pane: 'hc:t9', status: 'idle' }];
  // The ledger's PM, matched or by name on the same machine: no second row.
  assert.equal(list.allPmRows({ pms }, {}, [term('t3', { labels: { pm: 'project' } })], []).length, 1);
  assert.equal(list.allPmRows({}, { dev: { pms } }, [term('dev/t3', { labels: { pm: 'project' } })], []).length, 1);
  // The same project on another machine is another PM.
  assert.equal(list.allPmRows({ pms }, {}, [term('dev/t3', { labels: { pm: 'project' } })], []).length, 2);
  for (const t of [term('t5', { state: 'exited', labels: { pm: 'x' } }), term('t5')]) {
    assert.deepEqual(list.labelledPmRows([], [t], []), []);
  }
});

test('the view lists PMs only: their workers are left to the Agents list', () => {
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import .*;$/gm, '').replace('export default class PmList', 'class PmList');
  const texts = [], clicks = new Map(), calls = [];
  const element = () => {
    let id;
    const node = new Proxy({}, { get: (_, key) => (...args) => {
      if (key === 'id') { id = args[0]; clicks.set(id, null); }
      if (key === 'on_click' && id) clicks.set(id, args[0]);
      if (key === 'child' && typeof args[0] === 'string') texts.push(args[0]);
      if (key === 'when' && args[0]) args[1](node);
      return node;
    } });
    return node;
  };
  const terms = [term('t3', { labels: { pm: 'proj' } }), term('t62', { parent: 't3', labels: { task: 'x' }, name: 'worker' }),
    term('t63', { parent: 't62' }), term('t70', { parent: 't3', labels: { pm: 'nested' } }), term('t71', { parent: 't70' })];
  const bindings = {
    ...list, View: class {}, div: element, svg: element, image: element, v_flex: element, h_flex: element,
    theme: () => ({}), home: () => '/h', appHome: () => '/a', exec: async () => ({}), readTextFile: async () => '',
    watchFolder: async () => {}, layout: () => null, run: (...args) => calls.push(args), terminals: () => terms,
    agents: () => [{ address: 't62', status: 'working' }], panes: () => [{ terminal: 't62' }, { terminal: 't3' }],
    shared: () => null, setShared: () => {}, openOverlay: () => {}, execPython: async () => ({}),
    localStorage: { setItem() {}, getItem() { return null; } },
  };
  const PmList = new Function(...Object.keys(bindings), `${source}; return PmList;`)(...Object.values(bindings));
  const view = new PmList();
  Object.assign(view, { state: { pms: [{ name: 'pm-proj', project: 'proj', pane: 'hc:t3', status: 'idle' }], lang: 'en' },
    remote: {}, changed: {}, folded: true, compact: false, hover: null, error: '' });
  view.render({ notify() {}, stop_propagation() {} });
  // The ledger's PM and the unregistered nested one, each once; no worker, no fold.
  assert.deepEqual(texts.filter(x => ['proj', 'nested'].includes(x)).sort(), ['nested', 'proj']);
  for (const text of ['t62', 't63', 't64', 't71', 'worker']) assert.ok(!texts.some(x => x.includes(text)), text);
  assert.ok(![...clicks.keys()].some(id => /^pm-(worker|fold)-/.test(id)));
  // A click on the PM row still shows its terminal (no project view in this layout).
  clicks.get('pm-pm-proj')();
  assert.deepEqual(calls.pop(), ['pane.focus', { terminal: 't3' }]);
});

test('PM context usage formats cleanly, flags compact threshold, and omits 0 or missing tokens', () => {
  const { contextTokens, contextShort, contextLabel, pmContextLevel, pmContextTip } = list;
  for (const empty of [undefined, null, 0, -50, NaN, false, true, '12000']) {
    assert.equal(contextTokens(empty), 0);
    assert.equal(contextShort(empty), '');
    assert.equal(contextLabel(empty, 'zh'), '');
    assert.equal(pmContextLevel(empty), 'none');
    assert.equal(pmContextTip(empty, 'zh'), '');
  }
  assert.equal(contextLabel(800, 'zh'), '上下文 800');
  assert.equal(contextLabel(123_012, 'zh'), '上下文 123k');
  assert.equal(contextLabel(123_012, 'en'), 'Context 123k');
  // Strict `>` against `compact_tokens` (200_000 is 'near', 200_001 is 'over'; 160_000 is 'normal', 160_001 is 'near').
  assert.equal(pmContextLevel(160_000), 'normal');
  assert.equal(pmContextLevel(160_001), 'near');
  assert.equal(pmContextLevel(200_000), 'near');
  assert.equal(pmContextLevel(200_001), 'over');
  // Custom `compact_tokens` from `pm.py state` (`PM_COMPACT_TOKENS`) overrides the 200k fallback per machine.
  assert.equal(pmContextLevel(210_000, 400_000), 'normal');
  assert.equal(pmContextLevel(320_001, 400_000), 'near');
  assert.equal(pmContextLevel(400_001, 400_000), 'over');
  assert.match(pmContextTip(175_000, 'zh'), /接近 200k 压缩阈值/);
  assert.match(pmContextTip(210_000, 'zh'), /已超 200k 压缩阈值/);
  assert.match(pmContextTip(410_000, 'zh', 400_000), /已超 400k 压缩阈值/);
  assert.match(pmContextTip(410_000, 'en', 400_000), /over 400k compact threshold/);

  const state = {
    compact_tokens: 300_000,
    pms: [
      { name: 'pm-claude', project: 'claude-proj', pane: 'hc:t1', status: 'working', context_tokens: 250_000 },
      { name: 'pm-codex', project: 'codex-proj', pane: 'hc:t4', status: 'working', context_tokens: 210_000, compact_tokens: 220_000 },
      { name: 'pm-nocompact', project: 'nocompact-proj', pane: 'hc:t5', status: 'idle', context_tokens: 210_000, compact_tokens: 0 },
      { name: 'pm-agy', project: 'agy-proj', pane: 'hc:t2', status: 'working' },
      { name: 'pm-zero', project: 'zero-proj', pane: 'hc:t3', status: 'idle', context_tokens: 0 },
    ],
    lang: 'zh',
  };
  const rows = pmRows(state, {
    dev: { pms: [{ name: 'pm-rem', project: 'rem', pane: 'hc:r1', status: 'idle', context_tokens: 185_000 }] },
    old: { rotate_tokens: 250_000, pms: [{ name: 'pm-old', project: 'old', pane: 'hc:o1', status: 'idle', context_tokens: 260_000 }] },
  }, [], []);
  const byName = Object.fromEntries(rows.map(r => [r.label, r]));
  assert.equal(byName['claude-proj'].contextTokens, 250_000);
  assert.equal(byName['claude-proj'].compactTokens, 300_000);
  assert.equal(byName['codex-proj'].compactTokens, 220_000, 'per-PM compact_tokens overrides state-level default');
  assert.equal(pmContextLevel(byName['codex-proj'].contextTokens, byName['codex-proj'].compactTokens), 'near');
  assert.equal(byName['nocompact-proj'].compactTokens, 0, 'per-PM compact_tokens=0 disables threshold warning');
  assert.equal(pmContextLevel(byName['nocompact-proj'].contextTokens, byName['nocompact-proj'].compactTokens), 'normal');
  assert.equal(byName['rem'].compactTokens, undefined, 'older remote state without compact_tokens falls back cleanly');
  assert.equal(byName['old'].compactTokens, 250_000, 'older remote state with rotate_tokens maps cleanly');
  assert.equal(byName['agy-proj'].contextTokens, undefined);
  assert.equal(byName['zero-proj'].contextTokens, undefined);

  // Render PmList: shows "上下文 182k" in warning color, never renders "0", and yields to archive button on hover.
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import .*;$/gm, '').replace('export default class PmList', 'class PmList');
  const rendered = [];
  const element = () => {
    const rec = { id: '', texts: [], colors: [], tips: [] };
    const node = new Proxy({}, {
      get: (_, key) => (...args) => {
        if (key === 'id') { rec.id = args[0]; rendered.push(rec); }
        if (key === 'child' && typeof args[0] === 'string') rec.texts.push(args[0]);
        if (key === 'text_color') rec.colors.push(args[0]);
        if (key === 'tooltip') rec.tips.push(args[0]);
        if (key === 'when' && args[0]) args[1](node);
        return node;
      },
    });
    return node;
  };
  const themeObj = { dim: '#666', muted: '#999', foreground: '#eee', ansi3: '#f5a623', blocked: '#ff5555' };
  const bindings = {
    ...list, View: class {}, div: element, svg: element, image: element, v_flex: element, h_flex: element,
    theme: () => themeObj, home: () => '/h', appHome: () => '/a', exec: async () => ({}), readTextFile: async () => '',
    watchFolder: async () => {}, layout: () => null, run: () => {}, terminals: () => [], agents: () => [], panes: () => [],
    shared: () => null, setShared: () => {}, openOverlay: () => {}, execPython: async () => ({}),
    localStorage: { setItem() {}, getItem() { return null; } },
  };
  const PmList = new Function(...Object.keys(bindings), `${source}; return PmList;`)(...Object.values(bindings));
  const view = new PmList();
  Object.assign(view, { state, remote: {}, changed: {}, folded: true, compact: false, narrow: false, hover: null, error: '' });
  view.render({ notify() {}, stop_propagation() {} });

  const ctxNode = rendered.find(r => r.id === 'pm-context-pm-claude');
  assert.ok(ctxNode, 'claude PM renders context node');
  assert.deepEqual(ctxNode.texts, ['上下文 250k']);
  assert.ok(ctxNode.colors.includes('#f5a623'), '250k > 240k (80% of 300k compact_tokens) uses warning color');
  assert.equal(rendered.some(r => r.id === 'pm-context-pm-agy' || r.id === 'pm-context-pm-zero'), false);
  assert.equal(rendered.some(r => r.texts.some(t => /\b0k?\b/.test(t) && t.includes('上下文'))), false);

  // Hovering the local row offers archive in place of context/age so nothing crowds.
  rendered.length = 0;
  view.hover = 'pm-claude';
  view.render({ notify() {}, stop_propagation() {} });
  assert.equal(rendered.some(r => r.id === 'pm-context-pm-claude'), false);
  assert.equal(rendered.some(r => r.id === 'archive-pm-claude'), true);
});

test('pm-list excludes background-shell-only working status and calibrates remote cross-timezone lastEventAt', () => {
  const bgTerm = term('t1', { status: 'working', report: { state: 'working', msg: '1 shell still running' } });
  assert.equal(list.liveStatus(bgTerm, [{ address: 't1', status: 'working' }]), 'idle');

  const unhookedBgTerm = term('t2', { status: 'working', report: { state: 'working', msg: '' } });
  assert.equal(
    list.pmStatus({ name: 'pm-a', status: 'working', turn: { phase: 'idle', bg_shells: 1 } }, unhookedBgTerm, true, [{ address: 't2', status: 'working' }]),
    'idle',
  );

  // Remote state with `at_ms` or `(now, server_now_ms)` produces exact UTC seed regardless of viewer timezone.
  const trueUtcMs = 1795491000000;
  assert.equal(list.lastEventAt([{ pm: 'pm-a', at: '2026-11-23 10:00', at_ms: trueUtcMs }], 'pm-a'), trueUtcMs);
  const remoteState = {
    now: '2026-11-23 10:00:00',
    server_now_ms: trueUtcMs,
    pms: [{ name: 'pm-a', project: 'a', pane: 'hc:t1', status: 'idle' }],
    tasks: [],
    events: [{ pm: 'pm-a', at: '2026-11-23 09:55:00' }],
  };
  const [row] = pmRows({}, { studio: remoteState }, [term('studio/t1')], []);
  assert.equal(row.seed, trueUtcMs - 5 * 60_000);
});

test('PmList loads remote-states.json even while local pm.py state is pending or failing', async () => {
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import .*;$/gm, '').replace('export default class PmList', 'class PmList');
  const remoteCache = JSON.stringify({
    at: Date.now(),
    states: {
      dev: { pms: [{ name: 'pm-dudu', project: 'dudu', pane: 'hc:t73', status: 'working' }], tasks: [], events: [] },
    },
  });
  const stage = { id: 'pm-stage', active: 'work', children: [{ id: 'work' }, { id: 'pm-project' }] };
  const makeHarness = (execPythonImpl) => {
    const tasks = [];
    let notifies = 0;
    const cx = {
      spawn: fn => { const p = Promise.resolve().then(() => fn(cx)); tasks.push(p); return p; },
      timer: { every: () => ({ cancel() {} }) },
      notify: () => { notifies++; },
    };
    const bindings = {
      ...list, View: class {}, div: () => {}, svg: () => {}, image: () => {}, v_flex: () => {}, h_flex: () => {},
      theme: () => ({}), home: () => '/h', appHome: () => '/a',
      exec: async () => ({ code: 0, stdout: '/h/.dudu', stderr: '' }),
      readTextFile: async path => (path === '/h/.dudu/cache/remote-states.json' ? remoteCache : ''),
      watchFolder: () => new Promise(() => {}),
      layout: () => ({ id: 'root', children: [stage] }), run: () => {},
      terminals: () => [term('dev/t73', { labels: { pm: 'dudu' } })], agents: () => [], panes: () => [],
      shared: () => null, setShared: () => {}, openOverlay: () => {},
      execPython: execPythonImpl,
      localStorage: { setItem() {}, getItem() { return null; } },
    };
    const PmList = new Function(...Object.keys(bindings), `${source}; return PmList;`)(...Object.values(bindings));
    const view = new PmList();
    return { view, cx, flush: async () => { for (let i = 0; i < 6; i++) await new Promise(r => setImmediate(r)); }, getNotifies: () => notifies };
  };

  // Case 1: local pm.py state has not returned yet (never settles).
  const pending = makeHarness(() => new Promise(() => {}));
  pending.view.init({}, pending.cx);
  await pending.flush();
  const pendingRows = list.allPmRows(pending.view.state, pending.view.remote, [term('dev/t73', { labels: { pm: 'dudu' } })], []);
  assert.equal(pendingRows.length, 1);
  assert.equal(pendingRows[0].key, 'dev/pm-dudu');
  assert.equal(Boolean(pendingRows[0].unregistered), false);
  assert.equal(pending.view.viewable(pendingRows[0]), true);

  // Case 2: local pm.py state fails.
  const failing = makeHarness(async () => { throw new Error('boom'); });
  failing.view.init({}, failing.cx);
  await failing.flush();
  assert.match(failing.view.error, /boom/);
  assert.equal(failing.view.loading, false);
  const failingRows = list.allPmRows(failing.view.state, failing.view.remote, [term('dev/t73', { labels: { pm: 'dudu' } })], []);
  assert.equal(failingRows.length, 1);
  assert.equal(failingRows[0].key, 'dev/pm-dudu');
  assert.equal(Boolean(failingRows[0].unregistered), false);
  assert.equal(failing.view.viewable(failingRows[0]), true);
});
