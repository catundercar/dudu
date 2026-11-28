import test from 'node:test';
import assert from 'node:assert/strict';
import { pageBefore, pageBack, focusKey, isOverlayTerminalFocus, shouldReturnToWork, initialStageChild, summary } from './model.js';
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

test('focusing a pm-project floating agent terminal window does not return to work, and closing it restores baseline without misfiring', () => {
  const baseFocused = { space: 's1', tab: 'tab1', pane: 'p1', terminal: 't1', shown: null, agent: null };
  const overlayFocused = { space: 's1', tab: 'tab1', pane: null, terminal: 't42', shown: null, agent: null };
  const sameTerminalPane = { space: 's1', tab: 'tab42', pane: 'p42', terminal: 't42', shown: null, agent: null };
  const otherTerminalPane = { space: 's1', tab: 'tab2', pane: 'p2', terminal: 't2', shown: null, agent: null };
  const remoteOverlay = { space: 's1', tab: 'tab1', pane: null, terminal: 'mbp/t9', shown: null, agent: null };
  const openOverlays = ['mbp/t9', 't42'];

  // Overlay terminal focus (pane == null && terminal in openOverlays) is recognized; workspace panes are not.
  assert.equal(isOverlayTerminalFocus(overlayFocused, openOverlays), true);
  assert.equal(isOverlayTerminalFocus(remoteOverlay, openOverlays), true);
  assert.equal(isOverlayTerminalFocus(sameTerminalPane, openOverlays), false);
  assert.equal(isOverlayTerminalFocus(otherTerminalPane, openOverlays), false);
  assert.equal(isOverlayTerminalFocus(overlayFocused, []), false);

  // Simulate pm-nav's render loop: baseline -> click overlay terminal -> close overlay (restores baseline) -> click sidebar terminal.
  let prevFocus = focusKey(baseFocused);
  const step = (curFocused, overlays) => {
    const focus = focusKey(curFocused);
    const overlayFocus = isOverlayTerminalFocus(curFocused, overlays);
    const ret = shouldReturnToWork(true, true, focus, prevFocus, { overlayFocus });
    if (!overlayFocus) prevFocus = focus;
    return ret;
  };
  assert.equal(step(overlayFocused, openOverlays), false, 'clicking floating agent terminal must not return to work');
  assert.equal(step(remoteOverlay, openOverlays), false, 'clicking remote floating agent terminal must not return to work');
  assert.equal(step(baseFocused, []), false, 'closing floating agent terminal and restoring previous pane must not return to work');
  assert.equal(step(sameTerminalPane, openOverlays), true, 'clicking that terminal in sidebar (with a pane) still returns to work');
  prevFocus = focusKey(baseFocused);
  assert.equal(step(otherTerminalPane, openOverlays), true, 'clicking another terminal in sidebar still returns to work');
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

test('macOS collapsed 76px rail renders » unfold button in pm-nav when agents is hidden inside herdr-lists', async () => {
  const { readFileSync } = await import('node:fs');
  const hiddenTree = {
    id: 'root',
    children: [{
      id: 'sidebar',
      size: { px: 76 },
      children: [{
        id: 'sidebar-lists',
        children: [
          { id: 'pm-nav', type: 'block', size: { px: 40 }, content: { mod: 'pm-nav' } },
          { id: 'pm-list', type: 'block', size: { weight: 1 }, content: { mod: 'pm-list' } },
          { id: 'herdr-lists', type: 'column', hidden: true, children: [{ id: 'agents', content: { mod: 'agents' } }] },
        ],
      }],
    }],
  };
  const visibleTree = structuredClone(hiddenTree);
  visibleTree.children[0].children[0].children[2].hidden = false;

  assert.equal(nav.isAgentsHidden(hiddenTree), true);
  assert.equal(nav.isAgentsHidden(visibleTree), false);
  assert.equal(nav.needsRailUnfold(hiddenTree, { platform: 'macos' }), true);
  assert.equal(nav.needsRailUnfold(hiddenTree, { platform: 'linux' }), false);
  assert.equal(nav.needsRailUnfold(visibleTree, { platform: 'macos' }), false);
  assert.equal(nav.navHeight(true, true), nav.NAV_COMPACT_UNFOLD_HEIGHT);
  assert.equal(nav.navHeight(true, false), nav.NAV_HEIGHT);
  assert.equal(nav.navHeight(false, true), nav.NAV_HEIGHT);

  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import .*;$/gm, '').replace('export default class PmNav', 'class PmNav');
  let curTree = hiddenTree;
  let curWin = { platform: 'macos' };
  const runs = [];
  const sharedMap = new Map([['sidebar.width', 280]]);
  const rendered = new Map();
  const element = () => {
    const rec = { id: '', texts: [], click: null };
    const node = new Proxy(rec, {
      get(target, prop) {
        if (prop === 'id') return v => { target.id = v; rendered.set(v, target); return node; };
        if (prop === 'child') return c => { if (typeof c === 'string') target.texts.push(c); return node; };
        if (prop === 'when') return (cond, fn) => (cond ? fn(node) : node);
        if (prop === 'on_click') return fn => { target.click = fn; return node; };
        return () => node;
      },
    });
    return node;
  };
  const bindings = {
    ...nav, View: class {}, div: element, svg: element, v_flex: element, h_flex: element,
    theme: () => ({ chrome: '#111', foreground: '#eee', muted: '#999', dim: '#666', hover: '#222', selected: '#333', blocked: '#f55' }),
    home: () => '/h', appHome: () => '/a', exec: async () => ({ code: 0, stdout: '{}' }),
    watchFolder: async () => {}, nextCommand: () => new Promise(() => {}),
    layout: () => curTree, focused: () => null, run: (cmd, args) => runs.push([cmd, args]),
    shared: k => sharedMap.get(k), setShared: (k, v) => sharedMap.set(k, v), openOverlay: () => {},
    window: () => curWin, execPython: async () => ({ code: 0, stdout: '{}' }), createErrorLogger: null,
  };
  const PmNav = new Function(...Object.keys(bindings), `${source}; return PmNav;`)(...Object.values(bindings));
  const view = new PmNav();
  Object.assign(view, { localState: { pms: [], tasks: [], events: [] }, remoteStates: {}, counts: { projects: 2, active: 1, blocked: 0 }, setupAvailable: true, compact: true, width: 76, lang: 'zh' });
  view.render({ timer: { after() {} } });
  assert.ok(rendered.get('pm-sidebar-unfold'), 'macOS compact rail with hidden agents shows » unfold button');
  assert.deepEqual(rendered.get('pm-sidebar-unfold').texts, ['»']);
  assert.deepEqual(runs.at(-1), ['layout.resize', { id: 'pm-nav', px: 72 }]);
  rendered.get('pm-sidebar-unfold').click();
  assert.equal(sharedMap.get('sidebar.collapsed'), false);
  assert.deepEqual(runs.at(-1), ['layout.resize', { id: 'sidebar', px: 280 }]);

  // When herdr-lists is visible, agents renders its own » so pm-nav omits duplicate button
  curTree = visibleTree;
  rendered.clear();
  view.render({ timer: { after() {} } });
  assert.equal(rendered.has('pm-sidebar-unfold'), false);
});

test('initialStageChild restores saved stage, falls back to shared project or Projects page', () => {
  const stage = active => ({
    id: 'pm-stage',
    type: 'stack',
    active,
    children: [{ id: 'work' }, { id: 'pm-board' }, { id: 'pm-project' }],
  });

  // Switching from old pm layout (no shared pm-stage yet) with an active project restores pm-project.
  assert.equal(initialStageChild(stage('work'), null, { pm: 'dudu' }), 'pm-project');
  assert.equal(initialStageChild(stage('pm-board'), undefined, { pm: 'mbp/dudu', machine: 'mbp' }), 'pm-project');
  assert.equal(initialStageChild(stage('pm-project'), null, { pm: 'dudu' }), null);

  // Fresh dudu layout with no saved stage and no project lands on pm-board (Projects).
  assert.equal(initialStageChild(stage('work'), null, null), 'pm-board');
  assert.equal(initialStageChild(stage('work'), null, { pm: '' }), 'pm-board');
  assert.equal(initialStageChild(stage('pm-board'), null, null), null);

  // Explicit saved stage is respected across layout switches.
  assert.equal(initialStageChild(stage('work'), { child: 'pm-project' }, { pm: 'dudu' }), 'pm-project');
  assert.equal(initialStageChild(stage('work'), { child: 'pm-board' }, { pm: 'dudu' }), 'pm-board');
  assert.equal(initialStageChild(stage('work'), { child: 'work' }, { pm: 'dudu' }), null);
  assert.equal(initialStageChild(stage('pm-board'), { child: 'work' }, { pm: 'dudu' }), 'work');

  // Saved pm-project with no project name falls back to pm-board.
  assert.equal(initialStageChild(stage('work'), { child: 'pm-project' }, {}), 'pm-board');
  // Unknown saved child falls back to project or board.
  assert.equal(initialStageChild(stage('work'), { child: 'removed' }, { pm: 'dudu' }), 'pm-project');
  assert.equal(initialStageChild(stage('work'), { child: 'removed' }, null), 'pm-board');
});

test('PmNav restores pm-project on layout switch without breaking sidebar-click-leaves-board', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import .*;$/gm, '').replace('export default class PmNav', 'class PmNav');
  const makeTree = active => ({
    id: 'root',
    children: [
      { id: 'sidebar', children: [{ id: 'pm-nav', type: 'block', size: { px: 40 }, content: { mod: 'pm-nav' } }] },
      { id: 'pm-stage', type: 'stack', active, children: [{ id: 'work' }, { id: 'pm-board' }, { id: 'pm-project' }] },
    ],
  });
  let curTree = makeTree('work');
  let curFocused = null;
  const runs = [];
  const sharedMap = new Map([['pm-project', { pm: 'dudu' }]]);
  const element = () => {
    const node = new Proxy({}, {
      get(_t, prop) {
        if (prop === 'when') return (cond, fn) => (cond ? fn(node) : node);
        return () => node;
      },
    });
    return node;
  };
  const bindings = {
    ...nav, View: class {}, div: element, svg: element, v_flex: element, h_flex: element,
    theme: () => ({ chrome: '#111', foreground: '#eee', muted: '#999', dim: '#666', hover: '#222', selected: '#333', blocked: '#f55' }),
    home: () => '/h', appHome: () => '/a', exec: async () => ({ code: 0, stdout: '{}' }),
    watchFolder: async () => {}, nextCommand: () => new Promise(() => {}),
    layout: () => curTree, focused: () => curFocused, run: (cmd, args) => runs.push([cmd, args]),
    shared: k => sharedMap.get(k), setShared: (k, v) => sharedMap.set(k, v), openOverlay: () => {},
    window: () => ({ platform: 'macos' }), execPython: async () => ({ code: 0, stdout: '{}' }), createErrorLogger: null,
  };
  const PmNav = new Function(...Object.keys(bindings), `${source}; return PmNav;`)(...Object.values(bindings));
  const view = new PmNav();
  Object.assign(view, { localState: { pms: [], tasks: [], events: [] }, remoteStates: {}, counts: { projects: 1, active: 0, blocked: 0 }, setupAvailable: true, width: 240, lang: 'en' });
  const cx = { timer: { after() {} } };

  // Render 1 (mount on stale work stage): restores pm-project, does not clobber shared('pm-stage').
  view.render(cx);
  assert.deepEqual(runs, [['layout.select', { stack: 'pm-stage', child: 'pm-project' }]]);
  assert.equal(sharedMap.get('pm-stage'), undefined);

  // Intermediate render before layout.select applies: still does not overwrite shared('pm-stage') with work.
  view.render(cx);
  assert.equal(runs.length, 1);
  assert.equal(sharedMap.get('pm-stage'), undefined);

  // Render 2 (layout.select applied to pm-project, initial focus also settles): stays on pm-project.
  curTree = makeTree('pm-project');
  curFocused = { space: 's1', tab: 't1', pane: 'p1', terminal: 'term1', shown: null, agent: null };
  view.render(cx);
  assert.equal(runs.length, 1, 'initial focus settlement during restore must not bounce back to work');
  assert.deepEqual(sharedMap.get('pm-stage'), { child: 'pm-project' });

  // Render 3 (user clicks a space/agent in sidebar -> focus changes): returns to work (sidebar-click-leaves-board).
  curFocused = { space: 's2', tab: 't2', pane: 'p2', terminal: 'term2', shown: null, agent: null };
  view.render(cx);
  assert.deepEqual(runs.at(-1), ['layout.select', { stack: 'pm-stage', child: 'work' }]);
  assert.deepEqual(sharedMap.get('pm-stage'), { child: 'work' });

  // Render 4 (stage is now work): stays on work and does not re-restore pm-project.
  curTree = makeTree('work');
  const beforeCount = runs.length;
  view.render(cx);
  assert.equal(runs.length, beforeCount);
  assert.deepEqual(sharedMap.get('pm-stage'), { child: 'work' });
});

test('remote cache and summary do not depend on Set up here (Windows host: skill folder unreadable)', () => {
  const remote = { mbp: { pms: [{ name: 'pm-dudu' }], tasks: [], events: [] } };
  assert.equal(nav.shouldWriteRemoteCache(true, {}), true);
  assert.equal(nav.shouldWriteRemoteCache(false, remote), true);
  assert.equal(nav.shouldWriteRemoteCache(false, {}), false);
  assert.equal(nav.shouldWriteRemoteCache(false, {}, true), true, 'empties a cache that exists');
  assert.equal(nav.shouldWriteRemoteCache(false, null), false);
  assert.equal(nav.showsSummary(true, null), true);
  assert.equal(nav.showsSummary(false, { projects: 3, active: 1 }), true);
  assert.equal(nav.showsSummary(false, { projects: 0, active: 0 }), false);
  assert.equal(nav.showsSummary(false, null), false);
});

test('PmNav without Set up still caches remote projects and shows their count, not "Set up"', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import .*;$/gm, '').replace('export default class PmNav', 'class PmNav');
  const rendered = new Map(), py = [], files = new Map(), allTexts = [];
  const element = () => {
    const rec = { texts: [] };
    const node = new Proxy(rec, {
      get(target, prop) {
        if (prop === 'id') return v => { rendered.set(v, target); return node; };
        if (prop === 'child') return c => { if (typeof c === 'string') allTexts.push(c); return node; };
        if (prop === 'when') return (cond, fn) => (cond ? fn(node) : node);
        return () => node;
      },
    });
    return node;
  };
  const tree = { id: 'root', children: [{ id: 'pm-nav', type: 'block', size: { px: 40 }, content: { mod: 'pm-nav' } },
    { id: 'pm-stage', type: 'stack', active: 'work', children: [{ id: 'work' }, { id: 'pm-board' }, { id: 'pm-project' }] }] };
  const bindings = {
    ...nav, View: class {}, div: element, svg: element, v_flex: element, h_flex: element,
    theme: () => ({}), home: () => '/h', appHome: () => '/a', exec: async () => ({ code: 0, stdout: '{}' }),
    watchFolder: async () => {}, nextCommand: () => new Promise(() => {}),
    layout: () => tree, focused: () => null, run: () => {},
    shared: () => undefined, setShared: () => {}, openOverlay: () => {}, window: () => ({ platform: 'windows' }),
    readTextFile: async path => { if (files.has(path)) return files.get(path); throw new Error('ENOENT'); },
    writeTextFile: async (path, text) => { files.set(path, text); },
    execPython: async (_run, args) => { py.push(args); return { code: 0, stdout: '' }; }, createErrorLogger: null,
  };
  const PmNav = new Function(...Object.keys(bindings), `${source}; return PmNav;`)(...Object.values(bindings));
  const view = new PmNav();
  Object.assign(view, { ledgerHome: 'C:/Users/dev/.dudu', setupAvailable: false, localState: { pms: [], tasks: [], events: [] },
    remoteStates: {}, counts: { projects: 0, active: 0, blocked: 0 }, width: 240, lang: 'en', stageRestored: true });

  // Nothing remote and no Set up: nothing written, no cache existed.
  assert.equal(await view.writeRemoteCache(1), false);
  assert.equal(py.length, 0);
  view.render({ timer: { after() {} } });
  assert.ok(allTexts.includes('Set up'), allTexts.join('|'));

  // A connected machine's projects: written even though Set up failed here.
  view.remoteStates = { '198.51.100.10': { pms: [{ name: 'pm-dudu' }], tasks: [], events: [] } };
  assert.equal(await view.writeRemoteCache(2), true);
  assert.ok(py.some(args => args.includes('C:/Users/dev/.dudu/cache/remote-states.json')));
  view.counts = nav.summary(view.localState, view.remoteStates);
  allTexts.length = 0;
  view.render({ timer: { after() {} } });
  const texts = allTexts;
  assert.ok(!texts.includes('Set up'), texts.join('|'));
  assert.ok(texts.some(t => /\b1\b/.test(t)), texts.join('|'));

  // The machine disconnects: the cache it wrote is emptied, not left listing its projects.
  view.remoteStates = {};
  py.length = 0;
  assert.equal(await view.writeRemoteCache(3), true);
  assert.equal(py.length, 1);
});
