import test from 'node:test';
import assert from 'node:assert/strict';
import { pageBefore, pageBack, shouldReturnToWork, summary } from './model.js';
import * as nav from './model.js';

const CHILDREN = ['work', 'pm-board', 'pm-project'];
const PMS = [{ name: 'dudu' }, { name: 'herdr' }, { name: 'old', archived: true }];
// Open Projects from a page, then click Projects again on the Projects page.
const roundTrip = (active, projectPage, dashPage, pms = PMS, children = CHILDREN) =>
  pageBack(pageBefore(active, projectPage, dashPage), children, pms);

test("from a project's conversation, Projects comes back to that conversation", () => {
  assert.deepEqual(roundTrip('pm-project', { pm: 'dudu' }, { view: 'list', project: '' }), { child: 'pm-project', pm: 'dudu' });
});

test("from a project's board, Projects comes back to that board", () => {
  assert.deepEqual(roundTrip('pm-board', { pm: 'dudu' }, { view: 'board', project: 'herdr' }), { child: 'pm-board', pm: 'herdr' });
});

test('from the workspace, Projects comes back to the workspace', () => {
  assert.deepEqual(roundTrip('work', { pm: 'dudu' }, { view: 'board', project: '' }), { child: 'work' });
});

test('a recorded project that is gone (removed or archived) falls back to the workspace', () => {
  assert.deepEqual(roundTrip('pm-project', { pm: 'gone' }, {}), { child: 'work' });
  assert.deepEqual(roundTrip('pm-project', { pm: 'old' }, {}), { child: 'work' });
  assert.deepEqual(roundTrip('pm-board', {}, { view: 'board', project: 'old' }), { child: 'work' });
  // The project was archived while the Projects page was up.
  const covered = pageBefore('pm-project', { pm: 'dudu' }, {});
  assert.deepEqual(pageBack(covered, CHILDREN, [{ name: 'dudu', archived: true }]), { child: 'work' });
});

test('nothing recorded, or a stage child that is gone, falls back to the workspace', () => {
  assert.deepEqual(pageBack(null, CHILDREN, PMS), { child: 'work' });
  assert.deepEqual(roundTrip(undefined, {}, {}), { child: 'work' });
  assert.deepEqual(roundTrip('pm-project', {}, {}), { child: 'work' });            // no project named
  assert.deepEqual(roundTrip('pm-project', { pm: 'dudu' }, {}, PMS, ['work', 'pm-board']), { child: 'work' });
});

test('another stage child comes back as itself', () => {
  assert.deepEqual(roundTrip('notes', {}, {}, PMS, [...CHILDREN, 'notes']), { child: 'notes' });
});

test('sidebar navigation away from the board still returns to work', () => {
  assert.equal(shouldReturnToWork(true, true, 'b', 'a'), true);
  assert.equal(shouldReturnToWork(true, true, 'a', 'a'), false);
  assert.equal(shouldReturnToWork(true, false, 'b', 'a'), false);
});

test('the in-progress count leaves out a task whose terminal is gone', () => {
  const state = tasks => ({ pms: [{ name: 'pm-issues' }], tasks });
  const gone = { id: 'g', pm: 'pm-issues', status: 'in_progress', offline: true };
  assert.equal(summary(state([gone])).active, 0);
  assert.equal(summary(state([gone, { id: 'l', pm: 'pm-issues', status: 'in_progress', offline: false }])).active, 1);
  assert.equal(summary(state([]), { mbp: state([{ ...gone, id: 'r' }]) }).active, 0);
});

test("a remote project's conversation is come back to with its machine; gone from that machine, work", () => {
  const remote = { box: { pms: [{ name: 'pm-dudu' }], tasks: [] } };
  const pms = nav.projectKeys({ pms: PMS }, remote);
  assert.deepEqual(pms.map(pm => pm.name), ['dudu', 'herdr', 'old', 'box/pm-dudu']);
  const page = { pm: 'box/pm-dudu', machine: 'box' };
  assert.deepEqual(roundTrip('pm-project', page, {}, pms), { child: 'pm-project', pm: 'box/pm-dudu', machine: 'box' });
  assert.deepEqual(roundTrip('pm-project', page, {}, nav.projectKeys({ pms: PMS }, {})), { child: 'work' });
  // Its board (pm-dash scoped to the merged name) the same way.
  assert.deepEqual(roundTrip('pm-board', {}, { project: 'box/pm-dudu' }, pms), { child: 'pm-board', pm: 'box/pm-dudu' });
});

test('summary prefers pm.py counts and falls back per-machine for older remote pm.py', () => {
  const local = {
    pms: [{ name: 'pm-a', counts: { working: 2, waiting: 1 } }],
    tasks: [{ id: 'orphan', pm: '', status: 'in_progress' }, { id: 'orphan-b', pm: '', status: 'blocked' }],
    counts: { projects: 1, working: 2, waiting: 1, unclaimed_blocked: 1 },
  };
  const remoteOld = {
    pms: [{ name: 'pm-b' }, { name: 'pm-old', archived: '2026-11-01' }],
    tasks: [
      { id: '1', pm: 'pm-b', status: 'in_progress', offline: false },
      { id: '2', pm: 'pm-b', status: 'in_progress', offline: true },
      { id: '3', pm: 'pm-b', status: 'review' },
      { id: '3-r', pm: 'pm-b', status: 'blocked', review_of: '3' },
      { id: '4', pm: 'pm-old', status: 'in_progress' },
      { id: '5', pm: '', status: 'in_progress' },
      { id: '6', pm: '', status: 'blocked' },
    ],
  };
  assert.deepEqual(summary(local, { dev: remoteOld }), { projects: 2, active: 3, blocked: 2 });
});
