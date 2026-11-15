import test from 'node:test';
import assert from 'node:assert/strict';
import { pageBefore, pageBack, shouldReturnToWork, summary } from './model.js';

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
