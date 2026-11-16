import test from 'node:test';
import assert from 'node:assert/strict';
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
    ['alpha', 'blocked'], ['zeta', 'done'], ['beta', 'working'], ['gamma', 'working'], ['delta', 'idle']]);
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

test('a retired PM terminal is not the PM', () => {
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', pane: 'hc:t3b', status: 'idle' };
  const old = { address: 't3b', state: 'live', cwd: '/r/dudu', labels: { 'pm.retired': 'dudu' }, status: 'working' };
  // Neither by the recorded pane nor as the project folder's terminal.
  const [row] = pmRows({ pms: [pm] }, {}, [old], [{ address: 't3b', status: 'working' }]);
  assert.deepEqual([row.terminal, row.exact, row.status], [null, false, 'idle']);
  const next = { address: 't3k', state: 'live', cwd: '/r/dudu', labels: { pm: 'dudu' }, status: 'working' };
  assert.equal(pmRows({ pms: [pm] }, {}, [old, next], []).at(0).terminal.address, 't3k');
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
