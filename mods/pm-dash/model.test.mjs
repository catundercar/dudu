import test from 'node:test';
import { summary, waitingCount, navText, estimateTextWidth, focusKey, shouldReturnToWork, WRITE_REMOTE_CACHE } from '../pm-nav/model.js';
import * as nav from '../pm-nav/model.js';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { setupState, layout, boardFrame, fitBoard, withAlpha, solidText, isDarkTheme, cleanTaskLog, hoverCardPosition, mergeStates, cachedRemoteStates, newEvents, pointAt, terminalFor, terminalTargetFor, focusPlan, pmId, taskId, counts, eventText, word, taskStatusText, pmColor, wireFlows, sampleWire, arcHops, PACKET_SPEED, PACKET_STEP, LEDGER_HOME_SH, PM_SCRIPTS, remoteStateCommand, pmStatusText, scopeState, projectCards, projectCounts, countChips, pageTotals, startArgv, folderName, ledgerOpen, lastPmLine, boardGroups, endedList, endedDays, endedTime, previousDay } from './model.js';

const setupSummary = (installed = [], ready = [], outdated = []) =>
  ({ summary: { detected: installed, installed, ready, outdated } });

test('setup is ready when one agent is complete and no installed copy is outdated', () => {
  // No agent has the skill, or the earlier single-agent shape.
  for (const input of [null, undefined, {}, { summary: {} }, setupSummary(),
    { skill_present: true, hooks_present: true, script_matches: true }]) {
    assert.equal(setupState(input), 'missing');
  }
  assert.equal(setupState(setupSummary(['claude'], ['claude'])), 'ready');
  assert.equal(setupState(setupSummary(['claude', 'pi'], ['claude'])), 'ready'); // pi without hooks is still fine
  // Any differing copy asks for an update, even next to a ready agent.
  assert.equal(setupState(setupSummary(['claude', 'codex'], ['claude'], ['codex'])), 'outdated');
  assert.equal(setupState(setupSummary(['codex'], [], ['codex'])), 'outdated');
  // The skill without its hooks is not set up yet.
  assert.equal(setupState(setupSummary(['codex'], [])), 'missing');
  for (const lang of ['en', 'zh']) {
    for (const key of ['setupTitle', 'setup', 'settingUp', 'checkingSetup', 'setupDescription',
      'setupDone', 'setupOutdated', 'update', 'setupIncomplete']) assert.ok(word(lang, key));
    for (const agent of ['Claude Code', 'Codex', 'pi']) assert.ok(word(lang, 'setupDescription').includes(agent));
    assert.ok(!word(lang, 'setupDescription').includes('~/.claude'));
    assert.ok(!word(lang, 'setupDone').includes('Claude'));
  }
});

// Exercise async setup/IO decisions without starting Herdr or executing Python.
function modWithIO(file, bindings) {
  const source = readFileSync(new URL(file, import.meta.url), 'utf8')
    .replace(/^import .*;$/gm, '').replace('export default class ', 'return class ');
  const Mod = new Function('View', ...Object.keys(bindings), source)(class {}, ...Object.values(bindings));
  return new Mod();
}
function asyncContext() {
  const pending = [];
  const cx = { notify() {}, spawn(task) { pending.push(task(cx)); } };
  return { cx, async drain() { while (pending.length) await pending.shift(); } };
}

test('board checks are read-only, setup failures retry, and success refreshes state and sidebar', async () => {
  const calls = [], commands = [];
  let installed = false, fail = true, refreshed = 0;
  const board = modWithIO('./main.js', {
    appHome: () => '/app home', home: () => '/test home', setupState, word,
    run: name => commands.push(name),
    exec: async (program, args) => {
      calls.push({ program, args });
      if (args.includes('--status')) return { code: 0, stdout: JSON.stringify(installed
        ? setupSummary(['claude', 'codex'], ['claude', 'codex']) : setupSummary()) };
      if (fail) return { code: 1, stderr: 'Install failed: invalid settings\n' };
      installed = true;
      return { code: 0, stdout: 'Installation complete.' };
    },
  });
  board.state = { lang: 'en' };
  board.refresh = () => { refreshed++; };
  const { cx, drain } = asyncContext();
  await board.checkSetup();
  assert.equal(board.setupStatus, 'missing');
  assert.equal(calls.length, 1);
  assert.ok(calls[0].args.includes('--status'));
  assert.equal(installed, false);
  board.setUp(cx);
  board.setUp(cx); // A repeated click while busy must not start a second installer.
  await drain();
  assert.equal(calls.length, 2);
  assert.equal(board.setupStatus, 'missing');
  assert.match(board.setupError, /Install failed: invalid settings/);
  assert.equal(board.setupBusy, false);
  assert.equal(refreshed, 0);
  fail = false;
  board.setUp(cx);
  await drain();
  assert.equal(board.setupStatus, 'ready');
  assert.equal(board.setupDone, true);
  assert.equal(board.setupError, '');
  assert.equal(refreshed, 1);
  assert.deepEqual(commands, ['pm-nav.setup-changed', 'pm-nav.setup-changed']);
  for (const call of calls) {
    assert.equal(call.program, 'python3');
    assert.equal(call.args[0], '/app home/mods/pm-dash/setup.py');
    assert.deepEqual(call.args.slice(-2), ['--claude-home', '/test home/.claude']);
  }
});

test('sidebar keeps remote reads but suppresses cache writes until setup is available', async () => {
  const calls = [];
  const nav = modWithIO('../pm-nav/main.js', {
    home: () => '/test home', WRITE_REMOTE_CACHE,
    exec: async (program, args) => {
      calls.push({ program, args });
      return { code: 0, stdout: '[]' };
    },
  });
  nav.remoteStates = {}; nav.publish = () => {};
  const { cx, drain } = asyncContext();
  nav.setupAvailable = false; nav.ledgerHome = '/test home/.dudu';
  nav.refreshRemote(cx);
  await drain();
  assert.deepEqual(calls.map(call => call.program), ['hc']);
  nav.setupAvailable = true;
  nav.refreshRemote(cx);
  await drain();
  assert.deepEqual(calls.map(call => call.program), ['hc', 'hc', 'python3']);
  assert.equal(calls[2].args[2], '/test home/.dudu/cache/remote-states.json');
});

test('both mods read other machines with the same command and follow the ledger home', async () => {
  for (const file of ['./main.js', '../pm-nav/main.js']) {
    const calls = [], watched = [], wakes = [];
    const mod = modWithIO(file, {
      home: () => '/test home', WRITE_REMOTE_CACHE, remoteStateCommand: nav.remoteStateCommand,
      boardVisible: () => true, desktopLayout: () => ({}), props: () => ({}),
      watchFolder: path => { watched.push(path); return new Promise(resolve => wakes.push(resolve)); },
      exec: async (program, args) => {
        calls.push({ program, args });
        if (args[0] === 'machine') return { code: 0, stdout: JSON.stringify([{ name: 'box', state: 'connected' }]) };
        return { code: 0, stdout: JSON.stringify({ pms: [], tasks: [], events: [] }) };
      },
    });
    mod.remoteStates = {}; mod.publish = () => {}; mod.resolveHome = () => {};
    let refreshed = 0;
    mod.refresh = () => { refreshed++; };
    const { cx, drain } = asyncContext();
    mod.refreshRemote(cx);
    await drain();
    assert.deepEqual(calls[1], { program: 'hc', args: ['exec', '--on', 'box', remoteStateCommand()] }, file);
    // The watcher follows `home`; repeating the same home keeps one watcher, a new one re-arms.
    mod.ledgerHome = '';
    mod.setLedgerHome('/test home/.dudu', cx);
    mod.setLedgerHome('/test home/.dudu', cx);
    await Promise.resolve();
    assert.deepEqual(watched, ['/test home/.dudu/tasks'], file);
    wakes.shift()();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(refreshed, 1, file);
    assert.deepEqual(watched, ['/test home/.dudu/tasks', '/test home/.dudu/tasks'], file);
    mod.setLedgerHome('/test home/.claude/pm', cx);
    await Promise.resolve();
    assert.equal(watched.at(-1), '/test home/.claude/pm/tasks', file);
    wakes.shift()(); // the old watcher wakes once more, then stops without refreshing
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(refreshed, 1, file);
    assert.equal(watched.length, 3, file);
  }
});

test('the remote command runs state with the first pm.py that exists, in the same order in both mods', () => {
  assert.equal(nav.remoteStateCommand(), remoteStateCommand());
  assert.deepEqual(nav.PM_SCRIPTS, PM_SCRIPTS);
  assert.equal(nav.LEDGER_HOME_SH, LEDGER_HOME_SH);
  assert.deepEqual(PM_SCRIPTS, ['.config/herdr-app/mods/pm-dash/skill/scripts/pm.py', '.claude/skills/pm/scripts/pm.py',
    '.codex/skills/pm/scripts/pm.py', '.pi/agent/skills/pm/scripts/pm.py']);
  const dir = mkdtempSync(join(tmpdir(), 'pm-remote-'));
  try {
    const run = () => {
      try {
        return { code: 0, out: execFileSync('sh', ['-c', remoteStateCommand()], { env: { HOME: dir, PATH: process.env.PATH }, encoding: 'utf8', stdio: 'pipe' }) };
      } catch (error) { return { code: error.status, out: error.stderr }; }
    };
    assert.deepEqual(run(), { code: 127, out: 'pm.py not found\n' });
    for (const [i, path] of [[3, PM_SCRIPTS[3]], [2, PM_SCRIPTS[2]], [1, PM_SCRIPTS[1]], [0, PM_SCRIPTS[0]]]) {
      mkdirSync(dirname(join(dir, path)), { recursive: true });
      writeFileSync(join(dir, path), `import sys; print(${i}, sys.argv[1])\n`);
      assert.deepEqual(run(), { code: 0, out: `${i} state\n` });
    }
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('the fallback ledger home follows PM_HOME, then an earlier ~/.claude/pm, then ~/.dudu', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pm-home-'));
  try {
    const home = extra => execFileSync('sh', ['-c', LEDGER_HOME_SH], { env: { HOME: dir, PATH: process.env.PATH, ...extra }, encoding: 'utf8' });
    assert.equal(home(), `${dir}/.dudu`);
    mkdirSync(join(dir, '.claude/pm'), { recursive: true });
    assert.equal(home(), `${dir}/.claude/pm`);
    assert.equal(home({ PM_HOME: '/elsewhere' }), '/elsewhere');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('a PM card names its agent quietly, and nothing when the ledger has none', () => {
  assert.equal(pmStatusText('en', { live: 'idle', agent: 'codex' }), 'Idle · codex');
  assert.equal(pmStatusText('zh', { live: 'working', agent: 'pi' }), '工作中 · pi');
  assert.equal(pmStatusText('en', { live: 'idle', agent: '' }), 'Idle');
  assert.equal(pmStatusText('en', { live: 'idle' }), 'Idle');
});

test('the Projects entry counts projects in work and what waits, dropping words that do not fit', () => {
  const counts = { projects: 4, active: 1, blocked: 2 };
  assert.equal(navText(counts, 'zh', 200), '4 · 2 等你');
  assert.equal(navText(counts, 'en', 200), '4 · 2 need you');
  assert.equal(navText(counts, 'zh', estimateTextWidth('2 等你') + 4), '2 等你');
  assert.equal(navText(counts, 'zh', 10), '');
  assert.equal(navText({ projects: 3, active: 0, blocked: 0 }, 'zh', 200), '3');
  assert.equal(estimateTextWidth('项目'), estimateTextWidth('abcd'));
  assert.equal(summary({ pms: [{}, { archived: '2026-10-31' }], tasks: [] }).projects, 1);
});

test('task status text shows cleanup in both languages and preserves false or missing behavior', () => {
  for (const [lang, cleanupText, mergedText, releasedText, workingText, blockedText, reviewText] of [
    ['en', 'Merged · not retired', 'Merged', 'Released', 'Working…', 'Blocked · Waiting for you', 'Review'],
    ['zh', '已合并 · 待回收', '已合并', '已发布', '工作中…', '阻塞 · 等你', '待审'],
  ]) {
    for (const [status, expected] of [['merged', mergedText], ['released', releasedText],
      ['in_progress', workingText], ['blocked', blockedText], ['review', reviewText]]) {
      const row = { status, live: 'working' };
      assert.equal(taskStatusText(lang, { ...row, cleanup: true }), cleanupText);
      assert.equal(taskStatusText(lang, { ...row, cleanup: false }), expected);
      assert.equal(taskStatusText(lang, row), expected);
    }
  }
});

test('task log cleanup removes only a leading machine prefix and retains commit metadata', () => {
  for (const latest of [undefined, null, '', 'status=blocked', 'status=blocked;', 'status=review,']) {
    assert.deepEqual(cleanTaskLog(latest), { text: '', commit: '' });
  }
  for (const delimiter of [';', ',', '；', '，']) {
    assert.deepEqual(cleanTaskLog(`status=blocked${delimiter} 等用户确认，暂不执行。`), { text: '等用户确认，暂不执行。', commit: '' });
    assert.deepEqual(cleanTaskLog(`status=merged, commit=abc1234${delimiter} 已完成，待回收。`), { text: '已完成，待回收。', commit: 'abc1234' });
  }
  assert.deepEqual(cleanTaskLog('status=merged, commit=abc1234'), { text: '', commit: 'abc1234' });
  assert.deepEqual(cleanTaskLog('status=merged; commit=abc1234;'), { text: '', commit: 'abc1234' });
  assert.deepEqual(cleanTaskLog('  status=in_progress;\nTests passed.\nWaiting for review.  '), { text: 'Tests passed.\nWaiting for review.', commit: '' });
  for (const text of ['完成排查，等待复核。', 'Tests passed; ready for review.',
    'The report contains status=blocked, commit=abc1234; keep this detail.',
    'status=blocked is an example, not a ledger prefix.', 'commit=abc1234; keep this note.']) {
    assert.deepEqual(cleanTaskLog(text), { text, commit: '' });
  }
  assert.deepEqual(cleanTaskLog('status=review; 日志内的 status=blocked, commit=abc1234 不应再清洗'),
    { text: '日志内的 status=blocked, commit=abc1234 不应再清洗', commit: '' });
  assert.equal(word('zh', 'openTerminal'), '点击跳到该终端');
  assert.equal(word('en', 'openTerminal'), 'Click to open its terminal');
});

test('hover card aligns to its task column and flips at the stage or viewport edge', () => {
  const row = { x: 490, y: 100, w: 600, h: 32 };
  const original = { ...row };
  assert.deepEqual(hoverCardPosition(row, 600, { top: 0, bottom: 600 }, 160),
    { x: 490, y: 138, w: 520, h: 160, side: 'below' });
  // Exactly enough room below is still below; the stage may end before the viewport.
  assert.equal(hoverCardPosition(row, 298, { top: 0, bottom: 900 }, 160).side, 'below');
  assert.deepEqual(hoverCardPosition({ ...row, y: 400 }, 550, { top: 0, bottom: 900 }, 160),
    { x: 490, y: 234, w: 520, h: 160, side: 'above' });
  assert.deepEqual(hoverCardPosition({ ...row, y: 500 }, 1000, { top: 100, bottom: 600 }, 160),
    { x: 490, y: 334, w: 520, h: 160, side: 'above' });
  assert.equal(hoverCardPosition({ ...row, w: 204 }, 600, { top: 0, bottom: 600 }, 160).w, 204);
  assert.deepEqual(row, original);
});

test('hover card scaling preserves its gap and scrolling translates both visibility and placement', () => {
  const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`);
  for (const scale of [.6, .8, 1]) {
    const row = { x: 490, y: 100 * scale, w: 600, h: 32 * scale };
    const card = hoverCardPosition(row, 800 * scale, { top: 0, bottom: 800 * scale }, 160 * scale, scale);
    close(card.y - row.y - row.h, 6 * scale);
    close(card.w, 520 * scale);
    close(card.h, 160 * scale);
    assert.equal(card.x, row.x);
    assert.equal(card.side, 'below');
  }
  const row = { x: 490, y: 400, w: 600, h: 32 };
  for (const [stageY, side] of [[200, 'above'], [-100, 'below']]) {
    const viewport = { top: 100 - stageY, bottom: 700 - stageY };
    const card = hoverCardPosition(row, 1000, viewport, 140);
    assert.equal(card.side, side);
    assert.ok(stageY + card.y >= 100 && stageY + card.y + card.h <= 700);
    close(stageY + card.y, side === 'above' ? stageY + row.y - 6 - card.h : stageY + row.y + row.h + 6);
  }
  assert.equal(hoverCardPosition(row, 1000, { top: 432, bottom: 800 }, 140), null);
  assert.equal(hoverCardPosition(row, 1000, { top: 0, bottom: 400 }, 140), null);
});

test('when neither side fits, hover cards stay in the larger space without covering their task', () => {
  for (const [y, side, expectedY, height] of [[60, 'below', 86, 74], [90, 'above', 0, 84]]) {
    const row = { x: 350, y, w: 210, h: 20 };
    const card = hoverCardPosition(row, 160, { top: 0, bottom: 160 }, 180);
    assert.deepEqual(card, { x: 350, y: expectedY, w: 210, h: height, side });
    assert.ok(card.y >= 0 && card.y + card.h <= 160);
    assert.ok(side === 'above' ? card.y + card.h + 6 <= row.y : card.y >= row.y + row.h + 6);
  }
  assert.equal(hoverCardPosition({ x: 0, y: 0, w: 210, h: 32 }, 32, { top: 0, bottom: 32 }, 180), null);
});

test('cleanup survives local and remote rows without affecting counts or conclusions', () => {
  const tasks = ['merged', 'released'].flatMap(status => [{ cleanup: true }, { cleanup: false }, {}]
    .map((flag, i) => ({ id: `${status}-${i}`, pm: 'pm-a', status, worker: 'working', ...flag })));
  const input = { pms: [{ name: 'pm-a', project: 'Alpha' }], tasks, events: [] };
  for (const lang of ['en', 'zh']) {
    const merged = mergeStates({ ...input, lang }, { remote: input });
    // Ended tasks are rows only in an opened ended list.
    const rows = layout(merged, 980, 640, 1, false, { open: merged.pms.map(pm => pm.name) }).rows.filter(row => row.type === 'task');
    assert.deepEqual(rows.map(row => row.cleanup), [...tasks, ...tasks].map(task => task.cleanup));
    assert.deepEqual(counts({ ...merged, tasks: rows }), counts({ lang, pms: [], tasks: [] }));
  }
});

test('cache writer creates directories, skips unchanged states, and replaces changed or broken files', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pm-remote-cache-'));
  try {
    const path = join(dir, 'cache with spaces', 'remote-states.json');
    const remote = { pms: [{ name: '远端项目' }], tasks: [], events: [] };
    const states = { second: remote, first: remote };
    const write = (value, at) => execFileSync('python3', ['-c', WRITE_REMOTE_CACHE, path, JSON.stringify(value), String(at)]);
    write(states, 1_000_000);
    const original = readFileSync(path, 'utf8'), modified = statSync(path).mtimeMs;
    assert.deepEqual(cachedRemoteStates(original, 1_000_000), states);
    write({ first: { events: [], tasks: [], pms: remote.pms }, second: remote }, 2_000_000);
    assert.equal(readFileSync(path, 'utf8'), original);
    assert.equal(statSync(path).mtimeMs, modified);
    assert.equal(cachedRemoteStates(original, 2_000_000), null); // No timestamp-only renewal.
    write({}, 2_000_001);
    assert.deepEqual(JSON.parse(readFileSync(path, 'utf8')), { at: 2_000_001, states: {} });
    writeFileSync(path, '{broken');
    write(states, 2_000_002);
    assert.deepEqual(cachedRemoteStates(readFileSync(path, 'utf8'), 2_000_002), states);
    assert.deepEqual(readdirSync(dirname(path)), ['remote-states.json']);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('remote cache accepts only valid machine states within ten minutes, including the boundary', () => {
  const now = 1_000_000, remote = { pms: [{ name: 'pm' }], tasks: [], events: [] };
  const states = { '100.64.0.1': remote };
  for (const age of [0, 1, 600_000]) {
    assert.deepEqual(cachedRemoteStates(JSON.stringify({ at: now - age, states }), now), states);
  }
  assert.deepEqual(cachedRemoteStates(JSON.stringify({ at: now, states: {} }), now), {});
  for (const at of [now - 600_001, now + 1, -1, null, '1000000', undefined]) {
    assert.equal(cachedRemoteStates(JSON.stringify({ at, states }), now), null);
  }
  for (const invalid of [null, [], 'bad', { host: null }, { host: {} },
    { host: { ...remote, tasks: {} } }, { host: { ...remote, pms: [null] } }]) {
    assert.equal(cachedRemoteStates(JSON.stringify({ at: now, states: invalid }), now), null);
  }
  for (const text of [null, '', '{', 'null', '[]', '{}']) assert.equal(cachedRemoteStates(text, now), null);
});

test('board navigation observes every focus identity but ignores cwd and opening the board', () => {
  const focus = { space: 's1', tab: 'tab1', pane: 'p1', terminal: 't1', shown: null, agent: null, cwd: '/before' };
  const before = focusKey(focus);
  for (const field of ['space', 'tab', 'pane', 'terminal', 'shown', 'agent']) {
    const after = focusKey({ ...focus, [field]: 'other' });
    assert.equal(shouldReturnToWork(true, true, after, before), true, field);
    assert.equal(shouldReturnToWork(true, false, after, before), false);
    assert.equal(shouldReturnToWork(false, true, after, before), false);
  }
  assert.equal(shouldReturnToWork(true, true, focusKey({ ...focus, cwd: '/after' }), before), false);
  // A repeated sidebar selection has no signal in focused(); it is not fixed by comparison.
  assert.equal(shouldReturnToWork(true, true, focusKey({ ...focus }), before), false);
  assert.equal(focusKey(null), focusKey({}));
});

test('board navigation preserves remote machine identities including replacement agents', () => {
  const local = { space: 's1', tab: 'tab1', pane: 'p1', terminal: 't15' };
  const remote = Object.fromEntries(Object.entries(local).map(([key, value]) => [key, `100.64.0.1/${value}`]));
  assert.equal(shouldReturnToWork(true, true, focusKey(remote), focusKey(local)), true);
  assert.equal(shouldReturnToWork(true, true, focusKey({ ...remote, shown: '100.64.0.1/t16' }), focusKey(remote)), true);
  assert.equal(shouldReturnToWork(true, true, focusKey({ ...remote, agent: '100.64.0.1/t16' }), focusKey(remote)), true);
  assert.equal(shouldReturnToWork(true, true, focusKey({ ...remote, terminal: '100.64.0.2/t15' }), focusKey(remote)), true);
});

const state = { pms: [{ name: 'pm-a', project: 'a' }], tasks: [
  { id: '1', pm: 'pm-a', title: 'one' }, { id: '2', pm: 'pm-a', title: 'two' }, { id: '3', pm: '', title: 'orphan' }
], events: [] };
test('layout retains every task, groups orphans, and joins row edges at both panel sizes', () => {
  for (const [w,h] of [[980,640], [1600,900]]) {
    const g = layout(state,w,h);
    assert.equal(g.rows.filter(r => r.type === 'task').length,3); assert.equal(g.rows.filter(r => r.type === 'pm').length,2);
    // Hub to both PMs; pm-a's two-task bundle is a trunk and two branches; the orphan's single task, one line.
    assert.equal(g.wires.length,6);
    for (const wire of g.wires) {
      const a = g.rows.find(r => r.id === wire.from), b = g.rows.find(r => r.id === wire.to);
      assert.deepEqual(pointAt(wire.points,0), {x:a.x+a.w,y:a.y+a.h/2});
      assert.deepEqual(pointAt(wire.points,1), {x:b.x,y:b.y+b.h/2});
      assert.ok(b.x+b.w <= w); assert.ok(b.y+b.h <= g.height);
    }
    const tasks = g.rows.filter(r => r.type === 'task');
    assert.equal(tasks[0].y,g.bodyTop + 22); // under its bundle's heading
    assert.equal(tasks[0].h,w >= 1300 ? 36 : 32);
    assert.equal(tasks[1].y,tasks[0].y + tasks[0].h + 4);
    assert.ok(tasks[2].y-(tasks[1].y+tasks[1].h) >= 10);
    const hub = g.rows[0];
    assert.equal(hub.y+hub.h/2, (g.bodyTop+g.bodyBottom)/2);
    assert.ok(g.rows.filter(r => r.type === 'pm').every(r => r.h === 48));
  }
});
test('layout fits narrow boards without overlapping columns and floors width at 560', () => {
  for (const width of [400, 560, 600, 760, 980, 1400]) {
    const g = layout(state, width, 300);
    assert.equal(g.width, Math.max(560, width));
    if (width >= 560) assert.ok(g.width <= width);
    for (const row of g.rows) {
      assert.ok(row.x >= 0 && row.w > 0);
      assert.ok(row.x + row.w <= g.width, `${row.id} exceeds width ${width}`);
    }
    const hub = g.rows[0], pms = g.rows.filter(r => r.type === 'pm'), tasks = g.rows.filter(r => r.type === 'task');
    assert.ok(pms.every(pm => hub.x + hub.w < pm.x));
    assert.ok(pms.every(pm => tasks.every(task => pm.x + pm.w < task.x)));
    assert.equal(hub.y + hub.h / 2, (g.bodyTop + g.bodyBottom) / 2);
  }
  assert.deepEqual(layout(state, 400), layout(state, 560));
});

test('normal and wide geometry use the mockup column widths and bundle rows under their heading', () => {
  for (const [width, wide, hubWidth, pmX, pmWidth, taskX, rowHeight] of [
    [1164, false, 148, 232, 214, 530, 32],
    [1462, true, 176, 326, 260, 706, 36],
  ]) {
    const g = layout(state, width, 900, 1, wide);
    assert.equal(g.rows[0].w, hubWidth);
    assert.equal(g.pmX, pmX);
    assert.equal(g.taskX, taskX);
    assert.ok(g.rows.filter(r => r.type === 'pm').every(r => r.w === pmWidth));
    assert.ok(g.rows.filter(r => r.type === 'task').every(r => r.h === rowHeight));
    for (const label of g.rows.filter(r => r.type === 'label')) {
      const tasks = g.rows.filter(r => r.type === 'task' && (r.pm || '') === label.pm && (r.status || '') === label.status);
      assert.equal(label.count, tasks.length);
      assert.equal(tasks[0].y, label.y + label.h + 4);
      assert.ok(tasks.every((r, i) => r.x === g.taskX && r.y === tasks[0].y + i * (rowHeight + 4)));
      assert.deepEqual(tasks.map(r => r.first), tasks.map((_, i) => i === 0));
    }
  }
});

test('short viewports keep content height and center the hub inside the row area', () => {
  const many = { pms: Array.from({ length: 12 }, (_, i) => ({ name: `pm-${i}` })), tasks: [], events: [] };
  for (const input of [{ pms: [], tasks: [], events: [] }, state, many]) {
    for (const width of [600, 760, 980, 1400]) {
      const g = layout(input, width, 100);
      assert.deepEqual(g, layout(input, width, 900));
      assert.ok(g.height > 100);
      for (const row of g.rows) {
        assert.ok(row.y >= g.bodyTop && row.y + row.h <= g.bodyBottom);
        assert.ok(row.x + row.w <= g.width);
      }
      const hub = g.rows[0];
      assert.equal(hub.y - g.bodyTop, g.bodyBottom - hub.y - hub.h);
    }
  }
});

test('omitted scale matches scale 1 without changing any layout field', () => {
  for (const width of [400, 560, 760, 980, 1400]) {
    assert.deepEqual(layout(state, width, 640), layout(state, width, 640, 1));
  }
});

test('height scaling keeps columns, non-overlapping rows, centered hub and connected curve endpoints', () => {
  const many = {
    pms: Array.from({ length: 5 }, (_, i) => ({ name: `pm-${i}`, machine: i ? 'remote' : '' })),
    tasks: Array.from({ length: 17 }, (_, i) => ({ id: `task-${i}`, pm: `pm-${i % 5}` })), events: [],
  };
  const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`);
  for (const input of [{ pms: [], tasks: [], events: [] }, state, many]) {
    for (const width of [400, 560, 760, 980, 1400]) {
      const natural = layout(input, width, 640);
      for (const scale of [.6, .8]) {
        const g = layout(input, width, 640, scale);
        assert.equal(g.width, natural.width);
        close(g.height, natural.height * scale);
        assert.equal(g.rows.length, natural.rows.length);
        assert.equal(g.wires.length, natural.wires.length);
        for (const [i, row] of g.rows.entries()) {
          const original = natural.rows[i];
          assert.equal(row.x, original.x);
          assert.equal(row.w, original.w * (row.type ? 1 : scale));
          close(row.y, original.y * scale);
          close(row.h, original.h * scale);
          assert.ok(row.y >= g.bodyTop && row.y + row.h <= g.bodyBottom + 1e-8);
        }
        for (const type of ['pm', 'task']) {
          const column = g.rows.filter(row => row.type === type);
          for (let i = 1; i < column.length; i++) assert.ok(column[i].y + 1e-8 >= column[i - 1].y + column[i - 1].h);
        }
        const hub = g.rows[0];
        close(hub.y - g.bodyTop, g.bodyBottom - hub.y - hub.h);
        for (const [i, wire] of g.wires.entries()) {
          const a = g.rows.find(row => row.id === wire.from), b = g.rows.find(row => row.id === wire.to);
          assert.deepEqual(pointAt(wire.points, 0), { x: a.x + a.w, y: a.y + a.h / 2 });
          assert.deepEqual(pointAt(wire.points, 1), { x: b.x, y: b.y + b.h / 2 });
          // Only the hub's right edge moves horizontally with its own width.
          // PM/task wires retain every x, including their Bezier controls.
          if (a.type) assert.deepEqual(wire.points.map(p => p[0]), natural.wires[i].points.map(p => p[0]));
          else assert.equal(wire.points[3][0], natural.wires[i].points[3][0]);
          for (let j = 0; j < 4; j++) close(wire.points[j][1], natural.wires[i].points[j][1] * scale);
          const middleX = (wire.points[0][0] + wire.points[3][0]) / 2;
          assert.deepEqual(wire.points[1], [middleX, wire.points[0][1]]);
          assert.deepEqual(wire.points[2], [middleX, wire.points[3][1]]);
        }
      }
    }
  }
});

test('each task keeps its own curved branch from its bundle\'s fork at every scale', () => {
  const input = { pms: [{ name: 'a' }], tasks: Array.from({ length: 9 }, (_, i) => ({ id: String(i), pm: 'a' })), events: [] };
  for (const width of [560, 980, 1462]) {
    for (const scale of [.6, .8, 1]) {
      const g = layout(input, width, 300, scale), fork = g.rows.find(r => r.type === 'junction');
      const pm = g.rows.find(r => r.type === 'pm'), trunk = g.wires.find(w => w.to === fork.id);
      assert.deepEqual(trunk.points[0], [pm.x + pm.w, pm.y + pm.h / 2]);
      assert.ok(pm.x + pm.w < fork.x && fork.x + fork.w < g.taskX);
      const wires = g.wires.filter(w => w.to.startsWith('task:'));
      assert.equal(wires.length, input.tasks.length);
      assert.equal(new Set(wires.map(w => w.to)).size, input.tasks.length);
      const first = g.rows.find(r => r.type === 'task'), last = g.rows.filter(r => r.type === 'task').at(-1);
      assert.ok(Math.abs(fork.y + fork.h / 2 - (first.y + last.y + last.h) / 2) < 1e-8); // the fork faces the bundle's middle
      for (const wire of wires) {
        const row = g.rows.find(r => r.id === wire.to);
        assert.equal(wire.from, fork.id); assert.equal(wire.trunk, trunk.id);
        assert.deepEqual(wire.points[0], [fork.x + fork.w, fork.y + fork.h / 2]);
        assert.deepEqual(wire.points[3], [g.taskX, row.y + row.h / 2]);
        assert.equal(wire.points[1][1], wire.points[0][1]);
        assert.equal(wire.points[2][1], wire.points[3][1]);
        assert.ok(wire.points[1][0] > wire.points[0][0] && wire.points[2][0] < wire.points[3][0]);
      }
    }
  }
});

test('bundles follow urgency, keep ledger order within each, per PM and machine, and never mutate the ledger', () => {
  const statuses = ['paused', 'review', 'in_progress', 'blocked', 'proposed', 'review', 'in_progress', 'merged'];
  const input = { pms: [{ name: 'a' }, { name: 'empty' }], tasks: statuses.map((status, i) => ({
    id: String(i), pm: 'a', status, cleanup: status === 'merged',
  })), events: [] };
  const state = mergeStates(input, { 'remote-a': input, 'remote-b': input });
  const original = structuredClone(state), g = layout(state);
  for (const pm of g.rows.filter(r => r.type === 'pm' && r.sourceName === 'a')) {
    assert.deepEqual(g.rows.filter(r => r.type === 'task' && r.pm === pm.name).map(r => r.sourceId), ['3', '1', '5', '2', '6', '4', '0']);
    assert.deepEqual(g.rows.filter(r => r.type === 'label' && r.pm === pm.name).map(r => r.status),
      ['blocked', 'review', 'in_progress', 'proposed', 'paused']);
    assert.equal(g.rows.find(r => r.id === `ended:${pm.name}`).count, 1); // the merged one
  }
  assert.equal(g.rows.filter(r => r.type === 'ended').length, 3);
  // Empty PMs draw no heading, fork or ended node.
  assert.equal(g.rows.filter(r => r.type !== 'pm' && String(r.pm).endsWith('empty')).length, 0);
  assert.deepEqual(state, original);
});

test('machine chips wrap without overlapping columns and card numbers retain the source machine', () => {
  const input = { pms: [{ name: 'a' }, { name: 'b' }], tasks: [], events: [] };
  const state = mergeStates(input, { '100.64.0.1': input, 'a-very-long-machine-name.example': input });
  for (const width of [560, 980, 1462]) {
    const g = layout(state, width);
    assert.deepEqual(g.machines.map(m => m.machine), ['', '100.64.0.1', 'a-very-long-machine-name.example']);
    for (const row of g.rows.filter(r => r.type === 'pm')) {
      assert.equal(g.machines.find(m => m.number === row.machineNumber).machine, row.machine);
    }
    for (const chip of g.machines) {
      assert.ok(chip.x >= g.pmX && chip.x + chip.w < g.taskX);
      assert.ok(chip.y + chip.h < g.bodyTop);
    }
    assert.ok(g.bodyTop > 28);
  }
  assert.ok(layout(input).rows.filter(r => r.type === 'pm').every(r => r.machineNumber === null));
});

test('board reserves the wide sidebar and fits height down to .6 without losing scrollable content', () => {
  for (const width of [400, 560, 600, 980, 1220, 1499, 1500, 1900]) {
    const frame = boardFrame(width), natural = layout(state, frame.graphWidth, 900, 1, frame.wide);
    assert.equal(frame.width, Math.max(560, width));
    assert.equal(frame.wide, width >= 1500);
    assert.equal(natural.width + frame.feedWidth + frame.gap + frame.inset * 2, frame.width);
    for (const [ratio, expected] of [[2, 1], [.8, .8], [.4, .6]]) {
      const g = fitBoard(state, width, 200 + natural.height * ratio, 200);
      assert.ok(Math.abs(g.scale - expected) < 1e-8);
      assert.ok(Math.abs(g.height - natural.height * expected) < 1e-8);
      assert.equal(g.rows.length, natural.rows.length);
      if (ratio < .6) assert.ok(g.height + 200 > 200 + natural.height * ratio);
    }
  }
});

test('theme darkness compares foreground and background luminance across supported hex formats', () => {
  for (const [foreground, background] of [['#ececee', '#17181a'], ['#eee', '#111'], ['#ececeeff', '#17181aff']]) {
    assert.equal(isDarkTheme({ foreground, background }), true);
    assert.equal(isDarkTheme({ foreground: background, background: foreground }), false);
  }
});

test('alpha fills preserve token RGB and solid labels choose readable theme ink in light and dark', () => {
  assert.equal(withAlpha('#2a8a57', .15), '#2a8a5726');
  assert.equal(withAlpha('#abc', .16), '#aabbcc29');
  assert.equal(withAlpha('#11223380', .5), '#11223340');
  const light = { foreground: '#1a1b1e', background: '#f4f4f1', surface: '#ffffff', accent_foreground: '#ffffff' };
  const dark = { foreground: '#ececee', background: '#17181a', surface: '#212226', accent_foreground: '#15161a' };
  assert.equal(solidText('#d0402f', light), light.surface);
  assert.equal(solidText('#2c6bdc', light), light.surface);
  assert.equal(solidText('#f07467', dark), dark.accent_foreground);
  assert.equal(solidText('#6a9df2', dark), dark.accent_foreground);
});

test('events prime silently, deduplicate keys, retain mirror events and source order', () => {
  const old = { events: [{key:'a'}] }, next = { events: [{key:'a'}, {key:'b',kind:'report'}, {key:'m:x',kind:'prompt'}, {key:'b'}] };
  assert.deepEqual(newEvents(null,next), []);
  assert.deepEqual(newEvents(old,next).map(e=>e.key), ['b','m:x']);
  assert.deepEqual(newEvents(next,next), []);
});
test('terminal routing requires matching labels and live state', () => {
  const row = {type:'pm',project:'a'}, hidden = {address:'t1',state:'exited',labels:{pm:'a','herdr.space':'s','herdr.tab':'tab'}};
  const desktop = {address:'t2',state:'live',labels:{pm:'a','herdr.space':'s','herdr.tab':'tab'}};
  assert.equal(terminalFor(row,[hidden,desktop]),desktop);
  assert.equal(terminalFor({type:'task',task:'missing'},[desktop]),undefined);
});

test('live child agent needs neither a pane nor desktop labels to match a task', () => {
  const child = {address:'t13',state:'live',status:'working',labels:{task:'dudu-pm-dash'}};
  assert.equal(terminalFor({type:'task',task:'dudu-pm-dash'},[child]),child);
  assert.equal(terminalFor({type:'task',task:'dudu-pm-dash'},[{...child,state:'exited'}]),undefined);
});

test('PM project fallback matches live cwd on its own machine, normalizing trailing slashes only', () => {
  const row = { type: 'pm', project: 'sample', repo: '/work/sample/', pane: 'wS:p1' };
  const local = { address: 't8', state: 'live', cwd: '/work/sample' };
  const remote = { ...local, address: 'remote-a/t8', cwd: '/work/sample/' };
  const others = [{ ...local, address: 'remote-b/t1' },
    { ...local, address: 't1', state: 'exited' },
    { ...local, address: 't2', cwd: '/work/sample/child' },
    { ...local, address: 't3', cwd: '/work/other' },
    { ...local, address: 't4', cwd: null },
    { ...local, address: 't5', cwd: '/work/Sample' }];
  assert.deepEqual(terminalTargetFor(row, [...others, remote, local]), { terminal: local, exact: false });
  assert.deepEqual(terminalTargetFor({ ...row, machine: 'remote-a', repo: '/work/sample' },
    [...others, local, remote]), { terminal: remote, exact: false });
  assert.equal(terminalTargetFor(row, [...others, remote]).terminal, undefined);
  assert.equal(terminalTargetFor({ ...row, machine: 'remote-a' }, [...others, local]).terminal, undefined);
  for (const repo of [undefined, null, '', 42]) {
    assert.equal(terminalTargetFor({ ...row, repo }, [local, { ...local, cwd: '' }]).terminal, undefined);
  }
  const root = { ...local, cwd: '/' };
  assert.equal(terminalTargetFor({ ...row, repo: '/' }, [root]).terminal, root);
});

test('PM project fallback prefers agents then stable address order without reordering input', () => {
  const row = { type: 'pm', repo: '/work/sample' };
  const shell = { address: 't1', state: 'live', cwd: row.repo, program: { agent: false } };
  const agent = { ...shell, address: 't20', program: { agent: true } };
  const later = { ...agent, address: 't30' };
  const terms = [later, shell, agent], before = JSON.stringify(terms);
  assert.equal(terminalTargetFor(row, terms).terminal, agent);
  assert.equal(terminalTargetFor(row, [...terms].reverse()).terminal, agent);
  assert.equal(terminalTargetFor(row, [later, shell]).terminal, later);
  assert.equal(terminalTargetFor(row, [{ ...shell, address: 't2' }, shell]).terminal, shell);
  assert.equal(JSON.stringify(terms), before);
});

test('project fallback never applies to tasks or overrides labels and recorded hc panes', () => {
  for (const machine of ['', 'remote-a']) {
    const address = id => machine ? `${machine}/${id}` : id;
    const row = { type: 'pm', machine, project: 'sample', repo: '/work/sample', pane: 'hc:t9' };
    const fallback = { address: address('t1'), state: 'live', cwd: row.repo, program: { agent: true } };
    const pane = { address: address('t9'), state: 'live', cwd: '/work/elsewhere' };
    const labeled = { ...pane, address: address('t10'), labels: { pm: 'sample' } };
    assert.deepEqual(terminalTargetFor(row, [fallback, pane, labeled]), { terminal: labeled, exact: true });
    assert.deepEqual(terminalTargetFor(row, [fallback, pane]), { terminal: pane, exact: true });
    assert.deepEqual(terminalTargetFor({ ...row, type: 'task', task: 'sample-task', pane: 'wS:p1' },
      [fallback]), { terminal: undefined, exact: false });
    const task = { ...labeled, labels: { task: 'sample-task' } };
    assert.deepEqual(terminalTargetFor({ ...row, type: 'task', task: 'sample-task' }, [fallback, pane, task]),
      { terminal: task, exact: true });
  }
});

test('PM presentation uses fallback for navigation without borrowing its agent or terminal status', () => {
  const board = modWithIO('./main.js', { terminalTargetFor, pmId, taskId });
  board.queue = []; board.trip = null; board.shownLive = {}; board.shownStatus = {};
  const row = { id: 'pm:sample', name: 'sample', type: 'pm', repo: '/work/sample', status: 'offline' };
  const fallback = { address: 't8', state: 'live', cwd: row.repo, status: 'working', program: { agent: true } };
  const live = [{ address: fallback.address, status: 'blocked' }];
  let presented = board.presentation(row, [fallback], live);
  assert.equal(presented.terminal, fallback);
  assert.equal(presented.terminalExact, false);
  assert.equal(presented.live, 'offline');
  assert.equal(wireFlows({ to: row.id }, [presented]), false);
  assert.equal(board.presentation({ ...row, status: 'idle' }, [fallback], []).live, 'idle');
  const exact = { ...fallback, labels: { pm: 'sample' } };
  presented = board.presentation(row, [exact], live);
  assert.equal(presented.terminalExact, true);
  assert.equal(presented.live, 'blocked');
  assert.equal(board.presentation(row, [exact], []).live, 'working');
  assert.equal(board.presentation(row, [fallback], live).live, 'offline');
  assert.equal(board.presentation(row, [], live).terminal, undefined);
  assert.equal(board.presentation(row, [], live).live, 'offline');
});

test('a board row on a paneless sub-agent brings up its PM\'s space and peeks it, never a neighbour by address', () => {
  // 2026-11-15: t5h (dudu's, no pane yet) opened OldName, where t5c/t5g of appkit are.
  const terms = [{ address: 't52', state: 'live', labels: { pm: 'dudu' } },
    { address: 't5c', state: 'live', labels: { pm: 'appkit' } },
    { address: 't5g', state: 'live', labels: { task: 'appkit-pairing-redesign' }, parent: 't5c' },
    { address: 't5h', state: 'live', labels: { task: 'dudu-window-drag-review' }, parent: 't52' }];
  const row = { id: 'task:dudu-window-drag-review', type: 'task', task: 'dudu-window-drag-review', pane: 'hc:t5h' };
  const commands = [], panes = [{ pane: 'p1', terminal: 't52' }, { pane: 'p2', terminal: 't5c' }];
  const board = modWithIO('./main.js', { focusPlan, terminalFor, terminals: () => terms, panes: () => panes,
    agents: () => panes.map(p => ({ address: p.terminal, pane: p.pane })), props: () => ({}), closeOverlay: () => {},
    run: (name, args) => commands.push([name, args]) });
  board.state = { pms: [{ name: 'pm-dudu', project: 'dudu', pane: 'hc:t52' }, { name: 'pm-appkit', project: 'appkit' }] };
  const task = { ...row, pm: 'pm-dudu', terminal: terminalFor(row, terms) };
  board.openTerminal(task);
  assert.deepEqual(commands, [['pane.focus', { terminal: 't52' }], ['layout.select', { stack: 'pm-stage', child: 'work' }],
    ['terminal.peek', { terminal: 't5h' }]]);
  // t52 rotated out and closed (the worker outlives it): over the current PM t5p, found by its pm label.
  commands.length = 0;
  terms[0] = { ...terms[0], state: 'exited' }; terms.push({ address: 't5p', state: 'live', labels: { pm: 'dudu' } });
  panes[0] = { pane: 'p3', terminal: 't5p' };
  board.openTerminal(task);
  assert.deepEqual(commands.map(([name, args]) => [name, args.terminal || args.child]),
    [['pane.focus', 't5p'], ['layout.select', 'work'], ['terminal.peek', 't5h']]);
  // Its PM has no pane either: nothing runs — never the other project's space that happens to be active.
  commands.length = 0;
  panes.splice(0, 1);
  board.openTerminal(task);
  assert.deepEqual(commands, []);
});

test('a toast for an agent opens it as the board does, and does nothing when it has nowhere to show', async () => {
  const toastModel = await import('../pm-toast/model.js');
  assert.equal(toastModel.focusPlan.toString(), focusPlan.toString());
  const terms = [{ address: 't52', state: 'live', labels: { pm: 'dudu' } }, { address: 't5c', state: 'live', labels: { pm: 'appkit' } },
    { address: 't7', state: 'live', parent: 't52' }, { address: 't8', state: 'live', parent: 't404' }];
  const commands = [], closed = [];
  const source = readFileSync(new URL('../pm-toast/main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '').replace('export default class PmToast extends View', 'return class');
  const stubs = { View: class {}, focusPlan: toastModel.focusPlan, terminals: () => terms,
    panes: () => [{ pane: 'p1', terminal: 't52' }, { pane: 'p2', terminal: 't5c' }],
    agents: () => [{ address: 't52', pane: 'p1' }, { address: 't5c', pane: 'p2' }],
    layout: () => ({ id: 'root', children: [{ id: 'pm-stage', active: 'pm-project' }] }),
    run: (name, args) => commands.push([name, args]), closeOverlay: id => closed.push(id) };
  const Toast = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
  const toast = new Toast();
  toast.goTo('t7');
  assert.deepEqual(commands, [['pane.focus', { terminal: 't52' }], ['layout.select', { stack: 'pm-stage', child: 'work' }],
    ['terminal.peek', { terminal: 't7' }]]);
  commands.length = 0;
  toast.goTo('t8');
  assert.deepEqual(commands, []);
  toast.goTo('t5c');
  assert.deepEqual(commands, [['pane.focus', { terminal: 't5c' }], ['layout.select', { stack: 'pm-stage', child: 'work' }]]);
  // The terminal list unreadable: nothing runs (the click then only closes the toast).
  commands.length = 0;
  const Broken = new Function(...Object.keys(stubs), source)(...Object.values({ ...stubs, terminals: () => { throw new Error('gone'); } }));
  new Broken().goTo('t7');
  assert.deepEqual(commands, []);
});

test('missing PM session hints explain project fallback and desktop claim in both languages', () => {
  assert.equal(word('en', 'pmProjectFallback'), "PM session is not in the desktop app. Click opens the project's space.");
  assert.equal(word('zh', 'pmProjectFallback'), 'PM 会话不在 desktop 里，点击打开该项目的空间。');
  assert.equal(word('en', 'pmDesktopMissing'), 'PM session is not in the desktop app. Start it there and run pm.py claim.');
  assert.equal(word('zh', 'pmDesktopMissing'), 'PM 会话不在 desktop 里。在 desktop 里启动后运行 pm.py claim。');
});

const machine = '100.64.0.1';
const machineState = {
  lang: 'zh', pms: [{ name: 'pm-dudu', project: 'dudu', pane: 'hc:t15' }],
  tasks: [{ id: 'work', pm: 'pm-dudu', title: 'Work', pane: 'hc:t16', status: 'in_progress' }],
  events: [{ key: 'work#0', pm: 'pm-dudu', task: 'work', at: '2026-11-11 12:00:00' }],
};

test('merging machines namespaces identities and references, preserves labels and local language, and sorts events', () => {
  const remote = { ...machineState, lang: 'en', events: [
    { ...machineState.events[0], at: '2026-11-11 11:00:00' },
    { key: 'chat', pm: 'pm-dudu', task: '', kind: 'prompt', at: '2026-11-11 13:00:00' },
  ] };
  const before = JSON.stringify([machineState, remote]);
  const merged = mergeStates(machineState, { [machine]: remote });
  assert.equal(merged.lang, 'zh');
  assert.equal(mergeStates({ ...machineState, lang: undefined }, { [machine]: remote }).lang, undefined);
  assert.deepEqual(merged.pms.map(p => [p.name, p.machine]), [['pm-dudu', ''], [`${machine}/pm-dudu`, machine]]);
  assert.deepEqual(merged.tasks.map(t => [t.id, t.pm, t.machine]), [
    ['work', 'pm-dudu', ''], [`${machine}/work`, `${machine}/pm-dudu`, machine],
  ]);
  assert.deepEqual(merged.events.map(e => [e.key, e.machine, e.pm, e.task]), [
    [`${machine}/work#0`, machine, `${machine}/pm-dudu`, `${machine}/work`],
    ['work#0', '', 'pm-dudu', 'work'], [`${machine}/chat`, machine, `${machine}/pm-dudu`, ''],
  ]);
  assert.equal(merged.tasks[1].sourceId, 'work');
  const g = layout(merged);
  assert.equal(new Set(g.rows.map(r => r.id)).size, g.rows.length);
  assert.deepEqual(g.rows.filter(r => r.type === 'pm').map(r => r.title), ['dudu', 'dudu']);
  for (const wire of g.wires.filter(w => w.from !== 'you')) {
    assert.equal(g.rows.find(r => r.id === wire.from).machine, g.rows.find(r => r.id === wire.to).machine);
  }
  assert.deepEqual(summary(merged), { projects: 2, active: 2, blocked: 0 });
  assert.deepEqual(summary(machineState, { [machine]: remote }), summary(merged));
  assert.equal(JSON.stringify([machineState, remote]), before);
});

test('remote PM and task routing use only their own machine, including hc pane fallback and pane-less child labels', () => {
  const rows = layout(mergeStates(machineState, { [machine]: machineState })).rows;
  for (const type of ['pm', 'task']) {
    const row = rows.find(r => r.type === type && r.machine === machine);
    const localRow = rows.find(r => r.type === type && !r.machine);
    const id = type === 'pm' ? 't15' : 't16';
    const labels = type === 'pm' ? { pm: 'dudu' } : { task: 'work' };
    const local = { address: id, state: 'live', labels };
    const other = { ...local, address: `other/${id}` };
    const own = { ...local, address: `${machine}/${id}`, status: 'working' };
    assert.equal(terminalFor(row, [local, other, own]), own);
    assert.equal(terminalFor(localRow, [other, own, local]), local);
    assert.equal(terminalFor(row, [local, other]), undefined);
    assert.equal(terminalFor(localRow, [other, own]), undefined);
    assert.equal(terminalFor(row, [{ ...own, state: 'exited' }]), undefined);
    const unlabeled = { ...own, labels: {} };
    assert.equal(terminalFor(row, [local, other, unlabeled]), unlabeled);
    const child = { ...own, address: `${machine}/t20` };
    assert.equal(terminalFor({ ...row, pane: '' }, [local, other, child]), child);
    assert.equal(terminalFor(row, [unlabeled, child]), child);
    assert.equal(wireFlows({ to: row.id }, [{ ...row, live: terminalFor(row, [own]).status }]), true);
  }
  const task = rows.find(r => r.type === 'task' && r.machine === machine);
  assert.equal(terminalFor({ ...task, pane: 'hc:t15' }, [
    { address: `${machine}/t15`, state: 'live', labels: { pm: 'dudu' }, status: 'working' },
  ]), undefined);
});

test('failed machines leave local rows intact and do not discard healthy remote machines', () => {
  const failed = { offline: null, missing: undefined, invalid: {}, malformed: { pms: [], tasks: null, events: [] } };
  assert.deepEqual(mergeStates(machineState, failed), mergeStates(machineState));
  assert.deepEqual(summary(machineState, failed), summary(machineState));
  const merged = mergeStates(machineState, { ...failed, [machine]: machineState });
  assert.equal(layout(merged).rows.filter(r => r.type === 'task').length, 2);
  assert.deepEqual(summary(merged), { projects: 2, active: 2, blocked: 0 });
  const orphans = { pms: [], tasks: [{ id: 'orphan', pm: '', status: 'blocked' }], events: [] };
  const rows = layout(mergeStates(orphans, { [machine]: orphans })).rows;
  assert.equal(rows.filter(r => r.type === 'pm').length, 2);
  assert.equal(new Set(rows.map(r => r.id)).size, rows.length);
  assert.deepEqual(rows.filter(r => r.type === 'pm').map(r => r.machine), ['', machine]);
});

test('navigation summary counts ledger task states, not worker activity or closed tasks', () => {
  assert.deepEqual(summary({pms:[{name:'pm-a'},{name:'pm-b'}],tasks:[
    {pm:'pm-a',status:'in_progress',worker:'blocked'}, {pm:'pm-b',status:'in_progress'},
    {pm:'pm-a',status:'blocked'}, {pm:'pm-a',status:'review',worker:'working'}, {pm:'pm-b',status:'merged'},
    {pm:'pm-b',status:'paused'}
  ]}), {projects:2,active:2,blocked:1});
  assert.deepEqual(summary({pms:[],tasks:[]}), {projects:0,active:0,blocked:0});
});

test('what waits on the entry is the sum of the listed projects\' badges', () => {
  // As `pm.py state` gives it: OldName's tasks sit in appkit's repo, so they count
  // there; homenet has no PM and is not in the list, so its blocked tasks are not counted.
  const state = { pms: [
    { name: 'pm-dudu', counts: { waiting: 1 } }, { name: 'pm-appkit', counts: { waiting: 3 } },
    { name: 'pm-old', archived: '2026-10-31', counts: { waiting: 2 } },
  ], tasks: [
    { pm: 'pm-dudu', project: 'dudu', status: 'blocked' }, { pm: 'pm-appkit', project: 'appkit', status: 'blocked' },
    { pm: 'pm-appkit', project: 'OldName', status: 'blocked' }, { pm: 'pm-appkit', project: 'OldName', status: 'blocked' },
    { pm: '', project: 'homenet', status: 'blocked' }, { pm: '', project: 'homenet', status: 'blocked' },
    { pm: 'pm-old', project: 'old', status: 'blocked' }, { pm: 'pm-old', project: 'old', status: 'blocked' },
  ] };
  const badges = state.pms.filter(pm => !pm.archived).reduce((n, pm) => n + waitingCount(pm, state.tasks), 0);
  assert.equal(summary(state).blocked, badges);
  assert.equal(summary(state).blocked, 4);
  assert.equal(navText(summary(state), 'zh', 200), '2 · 4 等你');
  // A ledger from before `counts` falls back to the PM's own blocked tasks, as the list does.
  const old = { ...state, pms: state.pms.map(({ counts, ...pm }) => pm) };
  assert.equal(summary(old).blocked, 4);
  // Other machines add their own listed projects.
  assert.equal(summary(state, { dev: { pms: [{ name: 'pm-x', counts: { waiting: 2 } }], tasks: [] } }).blocked, 6);
});

test('dashboard counts blocked work as waiting and running workers without counting idle or closed work', () => {
  const result = counts({lang:'zh',pms:[{name:'pm-a',project:'Alpha'}],tasks:[
    {pm:'pm-a',status:'review',worker:'working'}, {pm:'pm-a',status:'blocked'},
    {pm:'pm-a',status:'in_progress',worker:'working'}, {status:'in_progress',worker:'idle'},
    {status:'merged',worker:'working'}, {status:'paused',worker:'working'}
  ]});
  assert.deepEqual(result, {running:1,review:1,blocked:1,waiting:1,conclusion:'Alpha 有 1 件事等你。'});
  // Review is the PM's job: a review task alone waits for nobody.
  assert.deepEqual(counts({lang:'zh',pms:[{name:'pm-a',project:'Alpha'}],tasks:[{pm:'pm-a',status:'review'}]}),
    {running:0,review:1,blocked:0,waiting:0,conclusion:'现在没有等你的事。'});
  assert.deepEqual(counts({lang:'zh',pms:[],tasks:[]}), {running:0,review:0,blocked:0,waiting:0,conclusion:'现在没有等你的事。'});
  // A blocked task the user has answered (pm.py's `answered`) waits for the PM: not counted, as on the bell.
  assert.deepEqual(counts({lang:'zh',pms:[{name:'pm-a',project:'Alpha'}],tasks:[{pm:'pm-a',status:'blocked',answered:true}]}),
    {running:0,review:0,blocked:1,waiting:0,conclusion:'现在没有等你的事。'});
  assert.equal(projectCounts({ name: 'pm-a' }, [{ pm: 'pm-a', status: 'blocked', answered: true }, { pm: 'pm-a', status: 'blocked' }]).waiting, 1);
  // Its row on the board says so, quietly.
  assert.equal(taskStatusText('zh', { status: 'blocked', answered: true }), '已回答');
  assert.equal(taskStatusText('en', { status: 'blocked', answered: true }), 'Answered');
  assert.equal(taskStatusText('zh', { status: 'blocked' }), '阻塞 · 等你');
});
test('project colors are stable theme tokens, independent of project order', () => {
  const names = ['dudu', 'Sample App', '测试项目', ''];
  const first = new Map(names.map(name => [name, pmColor(name)]));
  for (const name of [...names].reverse()) {
    assert.equal(pmColor(name),first.get(name));
    assert.match(pmColor(name), /^ansi[1-6]$/);
  }
  assert.ok(new Set(first.values()).size > 1);
});

test('only the wire target working flows; a working PM cannot animate merged or idle tasks', () => {
  const rows = [
    {id:'pm:a',type:'pm',live:'working'},
    {id:'task:merged',type:'task',status:'merged',live:'idle'},
    {id:'task:idle',type:'task',status:'in_progress',live:'idle'},
    {id:'task:running',type:'task',status:'in_progress',live:'working'},
    {id:'task:stale',type:'task',status:'merged',live:'working'},
    {id:'pm:idle',type:'pm',live:'idle'},
  ];
  assert.deepEqual(rows.map(row => wireFlows({to:row.id}, rows)), [true,false,false,true,false,false]);
  assert.equal(wireFlows({to:'missing'}, rows),false);
});

test('arc-length hops have equal distance and proportional duration, including reverse and short tails', () => {
  for (const curve of [
    [[0,0],[20,0],[40,0],[59,0]],
    [[0,0],[2,0],[5,0],[7,0]],
    [[0,0],[120,0],[120,340],[240,340]],
  ]) {
    const samples = sampleWire(curve);
    let measured = 0, previous = pointAt(curve,0);
    for (let i=1; i<=2000; i++) {
      const point = pointAt(curve,i/2000);
      measured += Math.hypot(point.x-previous.x,point.y-previous.y); previous=point;
    }
    for (const reverse of [false,true]) {
      const hops = arcHops(samples,reverse);
      assert.deepEqual(hops[0].from,pointAt(curve,reverse ? 1 : 0));
      assert.deepEqual(hops.at(-1).to,pointAt(curve,reverse ? 0 : 1));
      for (let i=0; i<hops.length; i++) {
        const hop = hops[i];
        if (i < hops.length-1) assert.equal(hop.distance,PACKET_STEP);
        else assert.ok(hop.distance > 0 && hop.distance <= PACKET_STEP);
        assert.ok(Math.abs(hop.duration / hop.distance - 1000 / PACKET_SPEED) < 1e-10);
        if (i) assert.deepEqual(hop.from,hops[i-1].to);
        if (curve[3][1] === 0) assert.ok(Math.abs(Math.hypot(hop.to.x-hop.from.x,hop.to.y-hop.from.y)-hop.distance) < 1e-8);
      }
      assert.ok(Math.abs(hops.reduce((sum,hop)=>sum+hop.distance,0)-measured) < .02);
    }
  }
});


test('built-in text defaults to English and preserves Chinese wording and ledger text', () => {
  const input = {pms:[{name:'pm-a',project:'Alpha'}],tasks:[{pm:'pm-a',status:'blocked'}]};
  assert.equal(counts(input).conclusion, 'Alpha has 1 item waiting for you.');
  assert.equal(counts({...input,lang:'zh'}).conclusion, 'Alpha 有 1 件事等你。');
  assert.equal(counts({...input,tasks:[...input.tasks,...input.tasks]}).conclusion, 'Alpha has 2 items waiting for you.');
  assert.equal(counts({pms:[],tasks:[]}).conclusion, 'Nothing is waiting for you right now.');
  assert.equal(counts({...input,lang:'unsupported'}).conclusion, counts(input).conclusion);
  assert.equal(eventText({kind:'prompt'}), 'You sent a message');
  assert.equal(eventText({kind:'reply'}, 'zh'), 'PM 回复了这一轮');
  assert.equal(eventText({kind:'prompt',text:'用户原文'}, 'en'), '用户原文');
  assert.equal(word(undefined, 'summary', 1, 1, 1), '1 project · 1 task running · 1 item waiting');
  assert.equal(word('en', 'summary', 2, 0, 2), '2 projects · 0 tasks running · 2 items waiting');
  assert.equal(word('zh', 'summary', 2, 0, 2), '2 个项目 · 0 个任务在跑 · 2 件事等你');
  for (const lang of ['en', 'zh']) {
    assert.equal(`${word(lang, 'summaryLead', 2, 0)} ${word(lang, 'summaryWaiting', 2)}`, word(lang, 'summary', 2, 0, 2));
    for (const key of ['inDesktop', 'notDesktop', 'localMachine']) assert.ok(word(lang, key));
  }
  assert.equal(layout(state).rows.find(r => r.type === 'pm' && !r.name).title, 'No PM');
  assert.equal(layout({...state,lang:'zh'}).rows.find(r => r.type === 'pm' && !r.name).title, '无 PM');
});

test('the pm layout hides every agent notice of an agent the PM dispatched', async () => {
  const { isWorkerNotice } = await import('../pm-toast/model.js');
  const terms = [
    { address: 't1', state: 'live', labels: { pm: 'demo' } }, // the PM itself
    { address: 't9', state: 'live', parent: 't1', labels: { task: 'demo-fix' } }, // a task worker
    { address: 't5', state: 'live', parent: 't1' }, // the PM's sub-agent without a task
    { address: 'box/t2', state: 'live', labels: { pm: 'api' } },
    { address: 'box/t4', state: 'live', parent: 'box/t2' },
    { address: 't3', state: 'live' }, // an agent the person started
    { address: 't6', state: 'live', parent: 't3' }, // its own sub-agent
    { address: 't8', state: 'live', parent: 't404' }, // parent not listed
  ];
  const notice = (terminal, title = 'Claude Code finished') =>
    ({ title, body: 'demo / 1', level: 'success', action: { name: 'agent.focus', args: { terminal } }, overlay: 'o1' });
  for (const address of ['t9', 't5', 'box/t4']) {
    for (const title of ['Claude Code finished', 'Codex needs you']) {
      assert.equal(isWorkerNotice(notice(address, title), terms), true, `${address} ${title}`);
    }
  }
  // The PM, the person's own agents and unknown terminals show (fail open).
  for (const address of ['t1', 'box/t2', 't3', 't6', 't8', 't404', '', undefined]) {
    for (const title of ['Claude Code finished', 'Codex needs you']) {
      assert.equal(isWorkerNotice(notice(address, title), terms), false, `${address} ${title}`);
    }
  }
  assert.equal(isWorkerNotice(notice('t9'), null), false);
  assert.equal(isWorkerNotice(notice('t9'), [{ address: 't1', labels: { pm: '' } }, { address: 't9', parent: 't1' }]), false);
  assert.equal(isWorkerNotice({ ...notice('t9'), action: { name: 'pane.focus', args: { terminal: 't9' } } }, terms), false);
  for (const props of [null, undefined, {}, { title: 'x finished' }]) assert.equal(isWorkerNotice(props, terms), false);
});

test('a retired PM terminal is neither the PM nor a task\'s terminal', () => {
  const old = { address: 't3b', state: 'live', cwd: '/r/dudu', labels: { 'pm.retired': 'dudu' } };
  const pm = { type: 'pm', name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', pane: 'hc:t3b' };
  assert.equal(terminalFor(pm, [old]), undefined);
  assert.equal(terminalTargetFor(pm, [old]).terminal, undefined);
  assert.equal(terminalFor({ type: 'task', task: 'dudu-y', pane: 'hc:t3b' }, [old]), undefined);
  const next = { address: 't3k', state: 'live', cwd: '/r/dudu', labels: { pm: 'dudu' } };
  assert.equal(terminalFor(pm, [old, next]), next);
});

test('Projects cards take their numbers from counts and keep archived projects apart', () => {
  const state = { lang: 'zh', pms: [
    { name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', agent: 'claude', counts: { working: 1, waiting: 0, review: 2, proposed: 6, merged_today: 0 } },
    { name: 'pm-ll', project: 'appkit', agent: 'codex', counts: { working: 0, waiting: 2, review: 0, proposed: 0, merged_today: 2 } },
    { name: 'pm-homenet', project: 'homenet', archived: '2026-10-31' },
  ], tasks: [
    // Tasks disagree with counts on purpose: the card shows the ledger's counts.
    { id: 'a', pm: 'pm-dudu', status: 'blocked', title: 'x' },
    { id: 'b', pm: 'pm-homenet', status: 'paused', paused_from: 'blocked', title: '光猫配置 DMZ' },
  ], events: [{ pm: 'pm-ll', at: '2026-11-14 22:00' }, { pm: 'pm-dudu', at: '2026-11-14 22:30' }] };
  const { active, archived } = projectCards(state);
  assert.deepEqual(active.map(c => [c.name, c.agent]), [['dudu', 'Claude Code'], ['appkit', 'Codex']]);
  assert.deepEqual(countChips(active[0].counts), [['working', 1], ['review', 2], ['proposed', 6]]);
  assert.deepEqual(countChips(active[1].counts), [['waiting', 2], ['merged_today', 2]]);
  assert.deepEqual(pageTotals(active), { projects: 2, working: 1, waiting: 2 });
  assert.deepEqual(archived.map(c => [c.name, c.paused]), [['homenet', ['光猫配置 DMZ']]]);
  // A ledger without counts counts its own tasks.
  assert.equal(projectCounts({ name: 'pm-dudu' }, state.tasks).waiting, 1);
  // Without counts, an in-progress task whose terminal is gone is not working; one with a terminal is.
  const gone = [{ id: 'g', pm: 'pm-x', status: 'in_progress', offline: true }];
  assert.equal(projectCounts({ name: 'pm-x' }, gone).working, 0);
  assert.equal(projectCounts({ name: 'pm-x' }, [...gone, { id: 'l', pm: 'pm-x', status: 'in_progress' }]).working, 1);
  assert.equal(word('zh', 'projectsTitle'), 'Projects');
  assert.equal(word('en', 'projectsTitle'), 'Projects');
});

test('a project board keeps only that project; the all-projects board leaves archived ones out', () => {
  const state = { pms: [{ name: 'pm-a' }, { name: 'pm-b' }, { name: 'pm-z', archived: '2026-10-31' }],
    tasks: [{ id: 't1', pm: 'pm-a' }, { id: 't2', pm: 'pm-b' }, { id: 't3', pm: 'pm-z' }, { id: 't4', pm: '' }],
    events: [{ key: 'e1', pm: 'pm-a' }, { key: 'e2', pm: 'pm-b' }, { key: 'e3', pm: 'pm-z' }] };
  const one = scopeState(state, 'pm-a');
  assert.deepEqual([one.pms.map(p => p.name), one.tasks.map(t => t.id), one.events.map(e => e.key)], [['pm-a'], ['t1'], ['e1']]);
  const g = layout(one, 980);
  assert.deepEqual(g.rows.map(r => r.id), ['pm:pm-a', 'label:pm-a:', 'task:t1']);   // no hub: the board starts at its PM
  assert.deepEqual(g.wires.map(w => w.id), ['task:t1']);
  const all = scopeState(state, '');
  assert.deepEqual([all.pms.map(p => p.name), all.tasks.map(t => t.id)], [['pm-a', 'pm-b'], ['t1', 't2', 't4']]);
  assert.equal(layout(all, 980).rows[0].id, 'you');
});

test('the new-project form runs pm.py start with its folder, name, agent and space', () => {
  const script = '/app/mods/pm-dash/skill/scripts/pm.py';
  assert.deepEqual(startArgv(script, { repo: '/Users/x/project/repos/homenet', name: '', kind: 'claude', space: 'new' }),
    [script, 'start', '--repo', '/Users/x/project/repos/homenet', '--name', 'homenet', '--kind', 'claude', '--space', 'new']);
  assert.deepEqual(startArgv(script, { repo: '/r/a/', name: ' home net ', kind: 'pi', space: 'current' }).slice(4),
    ['--name', 'home net', '--kind', 'pi', '--space', 'current']);
  assert.equal(folderName('/r/homenet/'), 'homenet');
  const open = ledgerOpen({ tasks: [{ project: 'homenet', status: 'blocked' }, { project: 'HomeNet', status: 'paused' },
    { project: 'homenet', status: 'merged' }, { project: 'other', status: 'blocked' }] }, 'homenet');
  assert.equal(open.length, 2);
});

test('a card shows the PM\'s newest line, links as their titles', () => {
  const log = [
    JSON.stringify({ type: 'pm', text: 'old' }),
    JSON.stringify({ type: 'pm', text: '在出 Projects 的设计稿；[输入框草稿不丢](thread:dudu-keep-drafts) 由 t1h 在做。\n- 第二行' }),
    JSON.stringify({ type: 'thread', text: 'not the PM' }), 'not json'].join('\n');
  assert.deepEqual(lastPmLine(log), [{ text: '在出 Projects 的设计稿；' },
    { text: '输入框草稿不丢', link: 'thread:dudu-keep-drafts' }, { text: ' 由 t1h 在做。' }]);
  assert.deepEqual(lastPmLine(''), []);
});

test('a task in progress whose terminal is gone reads as disconnected on the board', () => {
  for (const [lang, text] of [['en', 'Disconnected'], ['zh', '已断开']]) {
    assert.equal(taskStatusText(lang, { status: 'in_progress', offline: true, live: 'in_progress' }), text);
    // What waits for the user, or is in review, says so still.
    assert.equal(taskStatusText(lang, { status: 'blocked', offline: true }), word(lang, 'blockedWaiting'));
    assert.equal(taskStatusText(lang, { status: 'review', offline: true }), word(lang, 'review'));
  }
  assert.equal(taskStatusText('zh', { status: 'in_progress', live: 'working' }), '工作中…');
  const rows = layout({ lang: 'zh', pms: [{ name: 'pm-a', project: 'a' }], events: [],
    tasks: [{ id: 'a-1', pm: 'pm-a', title: 'T', status: 'in_progress', offline: true }] }).rows;
  assert.equal(rows.find(r => r.type === 'task').offline, true);  // the row carries what state said
});

test('Esc leaves a project board for its conversation and the Projects page for what it covered', async () => {
  const { escapeTarget } = await import('./model.js');
  assert.deepEqual(escapeTarget(true, { view: 'board', project: 'dudu' }), { project: 'dudu' });
  assert.deepEqual(escapeTarget(true, { view: 'archived', project: '' }), { view: 'list' });
  for (const page of [{ view: 'list', project: '' }, { view: 'board', project: '' }, {}, null, undefined]) {
    assert.deepEqual(escapeTarget(true, page), { back: true });
  }
  // The page is not on screen (another stage child, or an overlay copy): Esc is not ours.
  assert.equal(escapeTarget(false, { view: 'board', project: 'dudu' }), null);
  assert.equal(escapeTarget(false, { view: 'list' }), null);
  // One layer a press: an open hover card closes before the page goes anywhere.
  assert.deepEqual(escapeTarget(true, { view: 'board', project: 'dudu' }, { hoverCard: true }), { hoverCard: true });
  assert.deepEqual(escapeTarget(true, { view: 'board', project: '' }, { hoverCard: true }), { hoverCard: true });
  assert.equal(escapeTarget(false, { view: 'board' }, { hoverCard: true }), null);
  // Then the opened ended lists fold, before the page goes anywhere.
  assert.deepEqual(escapeTarget(true, { view: 'board', project: 'dudu' }, { ended: true }), { ended: true });
  assert.deepEqual(escapeTarget(true, { view: 'board', project: '' }, { hoverCard: true, ended: true }), { hoverCard: true });
  assert.equal(escapeTarget(false, { view: 'board' }, { ended: true }), null);
  // A list opened on the board stays open behind the list or archived page; Esc there is the page's.
  assert.deepEqual(escapeTarget(true, { view: 'list', project: '' }, { ended: true }), { back: true });
  assert.deepEqual(escapeTarget(true, { view: 'archived', project: '' }, { ended: true }), { view: 'list' });
});

// ---- Many tasks: bundles by status, one ended node -------------------------------------

const board = (tasks, pm = 'pm-a') => ({ lang: 'zh', project: pm, pms: [{ name: pm }], events: [],
  tasks: tasks.map(t => ({ pm, title: `T ${t.id}`, ...t })) });

test('active tasks bundle by status: a trunk per bundle forks into a branch per task and flows only with its work', () => {
  const input = board([{ id: 'r1', status: 'review' }, { id: 'w1', status: 'in_progress' }, { id: 'b1', status: 'blocked' },
    { id: 'w2', status: 'in_progress' }, { id: 'x', status: 'later' }, { id: 'p1', status: 'paused' }, { id: 'w3', status: 'in_progress' }]);
  assert.deepEqual(boardGroups(input.tasks).bundles.map(b => [b.status, b.tasks.map(t => t.id)]), [['blocked', ['b1']],
    ['review', ['r1']], ['in_progress', ['w1', 'w2', 'w3']], ['paused', ['p1']], ['later', ['x']]]);
  const g = layout(input, 980);
  assert.deepEqual(g.rows.filter(r => r.type === 'label').map(r => `${r.title} ${r.count}`), ['等你 1', '待审 1', '进行中 3', '暂停 1', 'later 1']);
  // A single task's bundle is one line from the PM; the three in progress share one trunk.
  assert.deepEqual(g.wires.map(w => w.id), ['task:b1', 'task:r1', 'trunk:pm-a:in_progress', 'task:w1', 'task:w2', 'task:w3', 'task:p1', 'task:x']);
  assert.deepEqual(g.routes['task:w2'], ['trunk:pm-a:in_progress', 'task:w2']);
  assert.deepEqual(g.routes['task:b1'], ['task:b1']);
  const working = ids => g.rows.map(r => r.type === 'task' ? { ...r, live: ids.includes(r.task) ? 'working' : 'idle' } : r);
  const trunk = g.wires.find(w => w.id === 'trunk:pm-a:in_progress'), branch = id => g.wires.find(w => w.id === `task:${id}`);
  assert.equal(wireFlows(trunk, working([])), false);
  assert.equal(wireFlows(trunk, working(['b1'])), false); // another bundle's work leaves this trunk still
  assert.equal(wireFlows(trunk, working(['w2'])), true);
  assert.equal(wireFlows(branch('w2'), working(['w2'])), true);
  assert.equal(wireFlows(branch('w1'), working(['w2'])), false); // only the working task's own branch
});

const ended = [
  { id: 'w', status: 'in_progress' }, { id: 'd1', status: 'done', updated: '2026-11-15 00:54' },
  { id: 'a1', status: 'abandoned', updated: '2026-11-15 00:50' }, { id: 'm1', status: 'merged', updated: '2026-11-14 22:26', cleanup: true },
  { id: 'r1', status: 'released', updated: '2026-11-14 21:36' }, { id: 'd2', status: 'done', updated: '2026-11-15 00:10' },
  { id: 'c1', status: 'cancelled', updated: '2026-11-13 09:00' },
];

test('ended tasks fold into one node on one still line, and its count leaves the abandoned out', () => {
  const input = board(ended), parts = boardGroups(input.tasks);
  assert.deepEqual(parts.ended.map(t => t.id), ['d1', 'd2', 'm1', 'r1']); // newest first
  assert.deepEqual(parts.dropped.map(t => t.id), ['a1', 'c1']);
  const g = layout(input, 980), node = g.rows.find(r => r.type === 'ended');
  assert.deepEqual([node.count, node.dropped, node.open, node.showDropped], [4, 2, false, false]);
  assert.deepEqual(node.recent, ['T d1', 'T d2', 'T m1']);
  assert.deepEqual(node.peek.map(t => t.id), ['d1', 'd2', 'm1', 'r1']);
  assert.deepEqual(g.rows.filter(r => r.type === 'task').map(r => r.task), ['w']); // folded: no row per ended task
  const line = g.wires.filter(w => w.to === node.id);
  assert.equal(line.length, 1); assert.equal(g.wires.length, 2);
  for (const id of ['d1', 'a1', 'c1']) assert.deepEqual(g.routes[`task:${id}`], [node.id]);
  assert.equal(wireFlows(line[0], g.rows.map(r => ({ ...r, live: 'working' }))), false); // never flows
  // A PM with only abandoned work still has the node, to hold the eye.
  const only = layout(board([ended[2]]), 980).rows.find(r => r.type === 'ended');
  assert.deepEqual([only.count, only.dropped], [0, 1]);
  // Opening the list moves neither the PM nor the board's scale: the list scrolls.
  const opened = layout(input, 980, 640, 1, false, { open: ['pm-a'] });
  assert.equal(opened.rows.find(r => r.type === 'pm').y, g.rows.find(r => r.type === 'pm').y);
  assert.ok(opened.height > g.height);
  const height = 200 + g.height * .8;
  assert.ok(Math.abs(fitBoard(input, 980, height, 200).scale - .8) < 1e-8);
  assert.equal(fitBoard(input, 980, height, 200, { open: ['pm-a'] }).scale, fitBoard(input, 980, height, 200).scale);
});

test('the eye shows the abandoned in the opened list without counting them; another PM\'s switch is its own', () => {
  const input = board(ended);
  const g = view => layout(input, 980, 640, 1, false, { today: '2026-11-15', ...view });
  const list = view => g(view).rows.filter(r => r.entry).map(r => r.task);
  assert.deepEqual(list({}), []);
  assert.deepEqual(list({ dropped: ['pm-a'] }), []); // folded still
  assert.deepEqual(list({ open: ['pm-a'] }), ['d1', 'd2', 'm1', 'r1']);
  assert.deepEqual(list({ open: ['pm-a'], dropped: ['pm-a'] }), ['d1', 'a1', 'd2', 'm1', 'r1', 'c1']);
  assert.deepEqual(list({ open: ['pm-b'], dropped: ['pm-b'] }), []);
  assert.deepEqual(endedList(boardGroups(input.tasks), true).map(t => t.id), ['d1', 'a1', 'd2', 'm1', 'r1', 'c1']);
  const shown = g({ open: ['pm-a'], dropped: ['pm-a'] }), node = shown.rows.find(r => r.type === 'ended');
  assert.deepEqual([node.count, node.dropped, node.showDropped], [4, 2, true]);
  // The opened list hangs on one straight guide from the node to its last row: no wire per task.
  assert.equal(shown.wires.length, g({}).wires.length);
  const [guide] = shown.guides, last = shown.rows.filter(r => r.entry).at(-1);
  assert.equal(shown.guides.length, 1);
  assert.equal(guide.y, node.y + node.h);
  assert.equal(guide.y + guide.h, last.y + last.h / 2);
  assert.ok(guide.x > node.x && guide.x < last.x);
});

test('an opened ended list groups by day: today, yesterday, then each date, the undated last', () => {
  const tasks = [{ id: 'a', updated: '2026-11-15 00:54' }, { id: 'b', updated: '2026-11-15 00:10' },
    { id: 'c', updated: '2026-11-14 22:29' }, { id: 'd', updated: '2026-11-13 09:46' }, { id: 'e', updated: '2026-10-31 23:44' }, { id: 'f' }];
  for (const [lang, titles] of [['zh', ['今天', '昨天 · 11-14', '11-13', '10-31', '更早']],
    ['en', ['Today', 'Yesterday · 11-14', '11-13', '10-31', 'Earlier']]]) {
    const days = endedDays(tasks, '2026-11-15', lang);
    assert.deepEqual(days.map(d => d.title), titles);
    assert.deepEqual(days.map(d => d.tasks.map(t => t.id)), [['a', 'b'], ['c'], ['d'], ['e'], ['f']]);
  }
  assert.equal(previousDay('2026-11-01'), '2026-10-31');
  assert.equal(previousDay('2026-01-01'), '2025-12-31');
  assert.equal(endedTime('2026-11-14 22:29', '2026-11-15'), '11-14 22:29');
  const input = board([...tasks].reverse().map(t => ({ ...t, status: 'done' })));
  const rows = layout(input, 980, 640, 1, false, { open: ['pm-a'], today: '2026-11-15' }).rows;
  assert.deepEqual(rows.filter(r => r.type === 'day' || r.entry).map(r => r.entry ? `${r.task} ${r.time}` : r.title),
    ['今天', 'a 00:54', 'b 00:10', '昨天 · 11-14', 'c 22:29', '11-13', 'd 09:46', '10-31', 'e 23:44', '更早', 'f ']);
});
