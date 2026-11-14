import test from 'node:test';
import assert from 'node:assert/strict';
import { pmRows, pmStatus, age, lastEventAt, track, listHeight, remotePmStates, HEADER, ROW, MAX_ROWS, PAD } from './model.js';
import * as list from './model.js';
import * as dash from '../pm-dash/model.js';

const term = (address, extra = {}) => ({ address, state: 'live', labels: {}, ...extra });

test('rows show PM-<project>, live status by terminal, most urgent first then by name', () => {
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
    ['PM-alpha', 'blocked'], ['PM-zeta', 'done'], ['PM-beta', 'working'], ['PM-gamma', 'working'], ['PM-delta', 'idle']]);
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

test('copied ledger and terminal rules stay identical to pm-dash', () => {
  assert.equal(list.LEDGER_HOME_SH, dash.LEDGER_HOME_SH);
  for (const name of ['terminalFor', 'terminalTargetFor']) assert.equal(list[name].toString(), dash[name].toString());
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
