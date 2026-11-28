import test from 'node:test';
import { summary, waitingCount, navText, estimateTextWidth, focusKey, shouldReturnToWork, ENSURE_DIR_PY, remoteCacheSig, WRITE_REMOTE_CACHE } from '../pm-nav/model.js';
import * as nav from '../pm-nav/model.js';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { setupState, shouldRecheckSetup, layout, boardFrame, fitBoard, withAlpha, solidText, isDarkTheme, cleanTaskLog, hoverCardPosition, tooltipLayout, mergeStates, cachedRemoteStates, newEvents, pointAt, terminalFor, terminalTargetFor, focusPlan, pmId, taskId, counts, eventText, word, label, taskSteps, taskDependencies, taskNumber, formatTaskNumber, DROPPED, disconnected, isClosedTask, taskStatusText, pmColor, wireFlows, reviewWorking, sampleWire, arcHops, PACKET_SPEED, PACKET_STEP, LEDGER_HOME_SH, PM_SCRIPTS, remoteStateCommand, pmStatusText, scopeState, projectCards, projectCounts, countChips, pageTotals, unclaimedBlocked, startArgv, folderName, ledgerOpen, lastPmLine, boardGroups, endedList, endedDays, endedTime, previousDay, TOKENS_EXPANDED_KEY, readTokensExpanded, writeTokensExpanded, parseTokenAnalytics, formatTokens, formatUsd, formatPct, formatCompactInt, selectTokenScope, filterTokenSlice, sparklineBars, KINDS, AGENT_NAMES, remotePmArgv, REMOTE_PROBE_SH, REMOTE_LIST_DIRS_SH, REMOTE_MKDIR_SH, parseRemoteProbe, parseRemoteDirs, normalizeMachines, initialMachineForDialog, addFolderEntry, removeFolderEntry, canSubmitNewProject, shouldCloseSpaceAfterArchive, resolveRestoreSpace } from './model.js';
import { renderStepsCard, renderDepsCard } from './steps.js';

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

test('shouldRecheckSetup only rechecks while missing or outdated and neither busy nor already checking', () => {
  assert.equal(shouldRecheckSetup('missing'), true);
  assert.equal(shouldRecheckSetup('outdated'), true);
  assert.equal(shouldRecheckSetup('missing', false, false), true);
  assert.equal(shouldRecheckSetup('outdated', false, false), true);
  for (const status of [null, undefined, '', 'ready', 'unknown']) {
    assert.equal(shouldRecheckSetup(status), false, String(status));
    assert.equal(shouldRecheckSetup(status, false, false), false, String(status));
  }
  for (const status of ['missing', 'outdated']) {
    assert.equal(shouldRecheckSetup(status, true, false), false, `${status} busy`);
    assert.equal(shouldRecheckSetup(status, false, true), false, `${status} checking`);
    assert.equal(shouldRecheckSetup(status, true, true), false, `${status} busy+checking`);
  }
});

test('recheckSetupIfNeeded auto-updates when external install completes and stops once ready', async () => {
  const calls = [], commands = [];
  let status = setupSummary(), refreshed = 0, notified = 0;
  let releaseCheck = null;
  const board = modWithIO('./main.js', {
    appHome: () => '/app home', home: () => '/test home', setupState, shouldRecheckSetup, word,
    run: name => commands.push(name),
    exec: async (program, args) => {
      calls.push({ program, args });
      if (releaseCheck) await new Promise(resolve => { releaseCheck = resolve; });
      return { code: 0, stdout: JSON.stringify(status) };
    },
  });
  board.state = { lang: 'en' };
  board.setupStatus = null; board.setupBusy = false; board.setupChecking = false;
  board.refresh = () => { refreshed++; };
  const { cx, drain } = asyncContext();
  cx.notify = () => { notified++; };

  // Null/loading: no subprocess.
  board.recheckSetupIfNeeded(cx);
  await drain();
  assert.equal(calls.length, 0);

  // Missing and unchanged: checks once, does not refresh/notify/broadcast.
  board.setupStatus = 'missing';
  board.recheckSetupIfNeeded(cx);
  await drain();
  assert.equal(calls.length, 1);
  assert.equal(board.setupStatus, 'missing');
  assert.equal(board.setupChecking, false);
  assert.equal(refreshed, 0);
  assert.equal(notified, 0);
  assert.deepEqual(commands, []);

  // Guard against overlapping runs while a check is in flight.
  releaseCheck = () => {};
  status = setupSummary(['claude'], ['claude']);
  board.recheckSetupIfNeeded(cx);
  board.recheckSetupIfNeeded(cx);
  assert.equal(board.setupChecking, true);
  assert.equal(calls.length, 2);
  releaseCheck();
  releaseCheck = null;
  await drain();
  assert.equal(board.setupStatus, 'ready');
  assert.equal(board.setupChecking, false);
  assert.equal(refreshed, 1);
  assert.equal(notified, 1);
  assert.deepEqual(commands, ['pm-nav.setup-changed']);

  // Once ready: zero subprocess overhead.
  board.recheckSetupIfNeeded(cx);
  await drain();
  assert.equal(calls.length, 2);

  // Outdated -> ready also refreshes, notifies, and informs pm-nav.
  board.setupStatus = 'outdated';
  board.recheckSetupIfNeeded(cx);
  await drain();
  assert.equal(calls.length, 3);
  assert.equal(board.setupStatus, 'ready');
  assert.equal(refreshed, 2);
  assert.equal(notified, 2);
  assert.deepEqual(commands, ['pm-nav.setup-changed', 'pm-nav.setup-changed']);
});

// Exercise async setup/IO decisions without starting Herdr or executing Python.
// python.js stands in as the Python found being python3 (its own tests are below).
const PYTHON3 = { execPython: (run, args, options) => run('python3', args, options), NO_PYTHON: 'no-python',
  appWindow: () => ({ platform: 'macos' }) };
function modWithIO(file, bindings) {
  // pm-nav's main.js imports its model by name: bind what the test does not stand in for.
  bindings = { ...PYTHON3, ...(file.includes('pm-nav') ? { shouldWriteRemoteCache: nav.shouldWriteRemoteCache, showsSummary: nav.showsSummary } : {}), ...bindings };
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

test('sidebar writes no cache before Set up with nothing remote, but caches other machines without Set up', async () => {
  const calls = [];
  let machines = [];
  const sidebar = modWithIO('../pm-nav/main.js', {
    home: () => '/test home', WRITE_REMOTE_CACHE, remoteStateCommand: nav.remoteStateCommand,
    exec: async (program, args) => {
      calls.push({ program, args });
      if (args[0] === 'machine') return { code: 0, stdout: JSON.stringify(machines) };
      return { code: 0, stdout: JSON.stringify({ pms: [{ name: 'pm-dudu' }], tasks: [], events: [] }) };
    },
  });
  sidebar.remoteStates = {}; sidebar.publish = () => {};
  const { cx, drain } = asyncContext();
  sidebar.setupAvailable = false; sidebar.ledgerHome = '/test home/.dudu';
  sidebar.refreshRemote(cx);
  await drain();
  assert.deepEqual(calls.map(call => call.program), ['hc']);
  sidebar.setupAvailable = true;
  sidebar.refreshRemote(cx);
  await drain();
  assert.deepEqual(calls.map(call => call.program), ['hc', 'hc', 'python3']);
  assert.equal(calls[2].args[2], '/test home/.dudu/cache/remote-states.json');
  // Windows host: Set up unavailable here (skill folder unreadable), another machine connected.
  calls.length = 0; sidebar.setupAvailable = false; sidebar.remoteCacheExists = undefined; machines = [{ name: 'box', state: 'connected' }];
  sidebar.refreshRemote(cx);
  await drain();
  assert.deepEqual(calls.map(call => call.program), ['hc', 'hc', 'python3']);
  assert.ok(calls[2].args[3].includes('pm-dudu'));
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
    // The watcher follows `home`; repeating the same home keeps one watcher per subdir, a new one re-arms.
    mod.ledgerHome = '';
    mod.setLedgerHome('/test home/.dudu', cx);
    mod.setLedgerHome('/test home/.dudu', cx);
    await Promise.resolve();
    assert.deepEqual(watched, ['/test home/.dudu/tasks', '/test home/.dudu/pms'], file);
    wakes.shift()(); // /tasks change
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(refreshed, 1, file);
    assert.deepEqual(watched, ['/test home/.dudu/tasks', '/test home/.dudu/pms', '/test home/.dudu/tasks'], file);
    wakes.shift()(); // /pms change (e.g. project rename)
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(refreshed, 2, file);
    assert.deepEqual(watched, ['/test home/.dudu/tasks', '/test home/.dudu/pms', '/test home/.dudu/tasks', '/test home/.dudu/pms'], file);
    mod.setLedgerHome('/test home/.claude/pm', cx);
    await Promise.resolve();
    assert.deepEqual(watched.slice(-2), ['/test home/.claude/pm/tasks', '/test home/.claude/pm/pms'], file);
    wakes.shift()(); // old /tasks watcher wakes once more, then stops without refreshing
    wakes.shift()(); // old /pms watcher wakes once more, then stops without refreshing
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(refreshed, 2, file);
    assert.equal(watched.length, 6, file);
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
    // Migrated install: ~/.claude/pm symlinks to ~/.dudu -> ~/.dudu is canonical.
    rmSync(join(dir, '.claude/pm'), { recursive: true, force: true });
    mkdirSync(join(dir, '.dudu'), { recursive: true });
    execFileSync('ln', ['-s', `${dir}/.dudu`, `${dir}/.claude/pm`]);
    assert.equal(home(), `${dir}/.dudu`);
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

test('hover card floats beside the task column so adjacent rows stay uncovered', () => {
  const rows = [0, 1, 2, 3].map(i => ({ id: `task:t${i}`, x: 460, y: 100 + i * 36, w: 600, h: 32 }));
  const row = rows[1], original = { ...row };
  const card = hoverCardPosition(row, 600, { top: 0, bottom: 600 }, 160, 1, { columnX: 460, stageWidth: 1060, rows });
  assert.deepEqual(card, { x: 54, y: 136, w: 400, h: 160, side: 'left' });
  // Zero overlap with every row in the task column, including the rows directly above and below.
  for (const r of rows) assert.ok(card.x + card.w <= r.x - 6, `${card.x + card.w} overlaps ${r.id}`);
  // Near the bottom of the stage or viewport, y clamps upward while staying beside the row.
  assert.deepEqual(hoverCardPosition({ ...row, y: 450 }, 550, { top: 0, bottom: 900 }, 160),
    { x: 54, y: 390, w: 400, h: 160, side: 'left' });
  assert.deepEqual(hoverCardPosition({ ...row, y: 500 }, 1000, { top: 100, bottom: 600 }, 160),
    { x: 54, y: 440, w: 400, h: 160, side: 'left' });
  // An indented opened-ended entry clears the whole task column and its guide line.
  const entry = hoverCardPosition({ x: 486, y: 220, w: 574, h: 26 }, 600, { top: 0, bottom: 600 }, 120, 1, { columnX: 460 });
  assert.equal(entry.x + entry.w, 454);
  // A 1-task board whose stage is shorter than one card uses the scroll viewport instead of truncating.
  assert.equal(hoverCardPosition({ x: 354, y: 50, w: 570, h: 32 }, 122, { top: 0, bottom: 600 }, 154).h, 154);
  // When the left side is too narrow, a wide right margin fits on the right before touching vertical neighbors.
  assert.deepEqual(hoverCardPosition({ x: 80, y: 100, w: 240, h: 32 }, 600, { top: 0, bottom: 600 }, 140, 1, { stageWidth: 680 }),
    { x: 326, y: 100, w: 354, h: 140, side: 'right' });
  assert.deepEqual(row, original);
});

test('hover card scaling preserves its gap and scrolling translates both visibility and placement', () => {
  const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`);
  for (const scale of [.6, .8, 1]) {
    const row = { x: 490, y: 100 * scale, w: 600, h: 32 * scale };
    const card = hoverCardPosition(row, 800 * scale, { top: 0, bottom: 800 * scale }, 160 * scale, scale);
    close(row.x - (card.x + card.w), 6 * scale);
    close(card.w, 400 * scale);
    close(card.h, 160 * scale);
    close(card.y, row.y);
    assert.equal(card.side, 'left');
  }
  const row = { x: 490, y: 400, w: 600, h: 32 };
  for (const [stageY, expectedY] of [[200, 360], [-100, 400]]) {
    const viewport = { top: 100 - stageY, bottom: 700 - stageY };
    const card = hoverCardPosition(row, 1000, viewport, 140);
    assert.equal(card.side, 'left');
    assert.ok(stageY + card.y >= 100 && stageY + card.y + card.h <= 700);
    close(card.y, expectedY);
  }
  assert.equal(hoverCardPosition(row, 1000, { top: 432, bottom: 800 }, 140), null);
  assert.equal(hoverCardPosition(row, 1000, { top: 0, bottom: 400 }, 140), null);
});

test('vertical fallback avoids neighbor rows and refuses to draw sliver cards below minHeight', () => {
  // Too narrow on both left and right: falls back above/below, choosing the unobstructed side first.
  const topRow = { id: 'task:a', x: 80, y: 140, w: 300, h: 32 };
  const bottomRow = { id: 'task:b', x: 80, y: 176, w: 300, h: 32 };
  const rows = [topRow, bottomRow];
  const above = hoverCardPosition(topRow, 500, { top: 0, bottom: 500 }, 100, 1, { stageWidth: 420, rows, minHeight: 70 });
  assert.deepEqual(above, { x: 80, y: 34, w: 300, h: 100, side: 'above' });
  const below = hoverCardPosition(bottomRow, 500, { top: 0, bottom: 500 }, 100, 1, { stageWidth: 420, rows, minHeight: 70 });
  assert.deepEqual(below, { x: 80, y: 214, w: 300, h: 100, side: 'below' });
  // When neither side fits in a tiny viewport, constrain to the larger side without covering its own row.
  for (const [y, side, expectedY, height] of [[60, 'below', 86, 74], [90, 'above', 0, 84]]) {
    const row = { x: 80, y, w: 210, h: 20 };
    const card = hoverCardPosition(row, 160, { top: 0, bottom: 160 }, 180, 1, { stageWidth: 300 });
    assert.deepEqual(card, { x: 80, y: expectedY, w: 210, h: height, side });
    assert.ok(card.y >= 0 && card.y + card.h <= 160);
    assert.ok(side === 'above' ? card.y + card.h + 6 <= row.y : card.y >= row.y + row.h + 6);
  }
  // Never return a 0-height or empty sliver card when available space is smaller than minHeight.
  assert.equal(hoverCardPosition({ x: 80, y: 60, w: 210, h: 20 }, 160, { top: 0, bottom: 160 }, 180, 1,
    { stageWidth: 300, minHeight: 80 }), null);
  assert.equal(hoverCardPosition({ x: 490, y: 0, w: 210, h: 32 }, 40, { top: 0, bottom: 40 }, 180, 1,
    { minHeight: 80 }), null);
  assert.equal(hoverCardPosition({ x: 0, y: 0, w: 210, h: 32 }, 32, { top: 0, bottom: 32 }, 180), null);
});

test('taskInfoCard withholds Popup until offscreen probe measures, resists zoom=0.9 shrink, and clears on leave', () => {
  const makeEl = (tag, extra = {}) => {
    const node = { tag, props: { ...extra }, children: [], handlers: {} };
    const chain = new Proxy({}, {
      get(_t, prop) {
        if (prop === '__node') return node;
        if (prop === 'child') return c => { node.children.push(c?.__node || c); return chain; };
        if (prop === 'children') return cs => { for (const c of cs) node.children.push(c?.__node || c); return chain; };
        if (prop === 'content') return c => { node.content = c?.__node || c; return chain; };
        if (prop === 'when') return (cond, fn) => cond ? fn(chain) : chain;
        if (prop.startsWith('on_')) return fn => { node.handlers[prop] = fn; return chain; };
        return (...args) => { node.props[prop] = args.length <= 1 ? args[0] : args; return chain; };
      },
    });
    return chain;
  };
  const findById = (n, prefix) => {
    if (!n || typeof n !== 'object') return null;
    if (String(n.props?.id || '').startsWith(prefix)) return n;
    for (const c of [...(n.children || []), ...(n.content ? [n.content] : [])]) {
      const hit = findById(c, prefix);
      if (hit) return hit;
    }
    return null;
  };
  const collectHandlers = (n, name, out = []) => {
    if (!n || typeof n !== 'object') return out;
    if (n.handlers?.[name]) out.push(n.handlers[name]);
    for (const c of [...(n.children || []), ...(n.content ? [n.content] : [])]) collectHandlers(c, name, out);
    return out;
  };
  const view = modWithIO('./main.js', {
    div: () => makeEl('div'), v_flex: () => makeEl('v_flex'), h_flex: () => makeEl('h_flex'),
    svg: () => makeEl('svg'), PathBuilder: { stroke: () => ({ move_to: () => ({ cubic_bezier_to() {}, build: () => ({}) }) }) },
    Scrollbar: { new: () => makeEl('scrollbar') },
    Popup: { new: (id, trigger) => makeEl('Popup', { id, trigger: trigger?.__node || trigger }) },
    theme: () => ({ canvas: '#111113', background: '#111113', surface: '#1b1b1f', raised: '#27272d',
      foreground: '#f2f2f5', muted: '#a0a0aa', dim: '#6b6b76', border: '#2e2e36',
      accent: '#4da3ff', blocked: '#ff6b6b', ansi1: '#ff6b6b', ansi2: '#4cd964',
      ansi3: '#ffcc00', ansi4: '#4da3ff', ansi5: '#bf5af2', ansi6: '#5ac8fa' }),
    home: () => '/h', appHome: () => '/a', exec: async () => ({ code: 0, stdout: '' }),
    readTextFile: async () => '', watchFolder: async () => {}, terminals: () => [], agents: () => [], panes: () => [],
    run: () => {}, props: () => ({}), closeOverlay: () => {}, openOverlay: () => {}, desktopLayout: () => ({}),
    setupState, fitBoard, withAlpha, solidText, isDarkTheme, cleanTaskLog, hoverCardPosition, newEvents,
    pmId, taskId, eventText, terminalFor, terminalTargetFor, focusPlan, pmColor, counts, projectCounts,
    wireFlows, reviewWorking, word, label, taskStatusText, isClosedTask, taskSteps, taskDependencies, taskNumber, formatTaskNumber, mergeStates, cachedRemoteStates, LEDGER_HOME_SH, remoteStateCommand,
    pmStatusText, scopeState, archiveThreads: () => [], disconnected, escapeTarget: () => null, DROPPED, endedTime,
    page: () => ({ view: 'board', project: 'pm-dudu' }), pageView: () => makeEl('page'),
    pageHeader: () => makeEl('header'), projectHeader: () => makeEl('header'), keepPress: (_v, el) => el,
    dialogView: () => makeEl('dialog'), initDialog: () => {}, restoreProject: () => {}, readLines: async () => ({}),
    archivePopup: () => ({}), NEW_DIALOG: {}, openProject: () => {}, showPage: () => {},
    FlowLayer: class {}, boardVisible: () => true, renderStepsCard, renderDepsCard,
    renderTokenPulsePill: () => makeEl('div'), renderTokenShelf: () => makeEl('div'),
    readTokensExpanded, writeTokensExpanded, parseTokenAnalytics,
  });
  let notifications = 0;
  const cx = { notify() { notifications++; }, timer: { after() { return { cancel() {} }; }, every() {} } };
  view.state = {
    lang: 'zh', project: 'pm-dudu',
    pms: [{ name: 'pm-dudu', project: 'dudu' }],
    tasks: [
      { id: 't1', pm: 'pm-dudu', title: '任务一', status: 'in_progress', latest: '第一行日志\n第二行日志', updated: '2026-11-21 22:00' },
      { id: 't2', pm: 'pm-dudu', title: '任务二', status: 'in_progress', latest: '相邻行', updated: '2026-11-21 22:01' },
    ],
    events: [],
  };
  view.size = { width: 1651, height: 921 };
  view.shown = {}; view.shownStatus = {}; view.shownLive = {}; view.statuses = {}; view.tags = {}; view.nudges = {};
  view.queue = []; view.endedOpen = new Set(); view.showDropped = new Set(); view.hoverEnded = null; view.hoverPm = null;
  view.flowLayer = { set_props() {} };
  globalThis.window = { paint_path: () => makeEl('path') };
  try {
    const g = view.geometry();
    const zoom = 0.9;
    // Simulate Herdr zoom=0.9: bounds are 0.9x stage kit units.
    view.boardBounds = { x: 248, y: 56, width: view.size.width * zoom, height: view.size.height * zoom };
    view.stageBounds = { x: 280, y: 210, width: g.width * zoom, height: g.height * zoom };
    view.hoverTask = 't1';

    // Frame 1 (unmeasured): must NOT mount Popup; mounts only hidden zero-size probe.
    const first = view.board(cx).__node;
    assert.equal(findById(first, 'task-info-popup:'), null);
    const probe = findById(first, 'task-log-probe:');
    assert.ok(probe, 'offscreen text probe is mounted on frame 1');
    const innerWidth = probe.props.w;
    // Report zoomed 2-line height (0.9x), just as GPUI on_size_change does when zoom=0.9.
    const lineHeight = Math.max(15, 19 * g.scale);
    probe.handlers.on_size_change({ width: innerWidth * zoom, height: lineHeight * 2 * zoom }, cx);
    assert.equal(notifications, 1);

    // Frame 2 (measured): Popup renders beside the row, with positioning on outer anchor (not on Popup) and ZERO on_size_change on the card.
    const second = view.board(cx).__node;
    const popup = findById(second, 'task-info-popup:task:t1');
    const anchor = findById(second, 'task-info-anchor:task:t1');
    assert.ok(popup, 'Popup is mounted once measured');
    assert.ok(anchor, 'outer anchor wrapper div is mounted');
    assert.equal(popup.props.absolute, undefined, 'Popup must not have .absolute() chained');
    assert.equal(popup.props.left, undefined, 'Popup must not have .left() chained');
    assert.equal(popup.props.top, undefined, 'Popup must not have .top() chained');
    assert.equal(collectHandlers(popup, 'on_size_change').length, 0);
    const initialMaxH = popup.content.props.max_h;
    assert.ok(initialMaxH > lineHeight * 2, `card height ${initialMaxH} holds header, metadata and 2 log lines`);
    assert.ok(anchor.props.left + anchor.props.w <= g.taskX - 6 * g.scale + 1e-6, 'card floats to the left of the task column');

    // Frame 3: re-rendering keeps the exact same height without shrinking.
    const third = view.board(cx).__node;
    assert.equal(findById(third, 'task-info-popup:task:t1').content.props.max_h, initialMaxH);

    // Moving pointer into the gap between t1 and t2 on stage immediately clears hoverTask.
    const stageNode = findById(third, 'board-stage');
    const t1Row = g.rows.find(r => r.task === 't1');
    stageNode.handlers.on_mouse_move({
      bounds: view.stageBounds,
      position: { x: view.stageBounds.x + (t1Row.x + 20) * zoom, y: view.stageBounds.y + (t1Row.y + t1Row.h + 2) * zoom },
    }, cx);
    assert.equal(view.hoverTask, null);

    // Leaving the root/stage clears hoverTask and hoverEnded immediately.
    view.hoverTask = 't1'; view.hoverEnded = 'pm-dudu';
    second.handlers.on_hover(false, cx);
    assert.equal(view.hoverTask, null);
    assert.equal(view.hoverEnded, null);
  } finally {
    delete globalThis.window;
  }
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
      ['blocked', 'in_progress', 'proposed', 'paused']);
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

test('dashboard counts use unified pm.py rules: claimed waiting, in-progress not offline, and separate unclaimed blocked', () => {
  const result = counts({lang:'zh',pms:[{name:'pm-a',project:'Alpha'}],tasks:[
    {pm:'pm-a',status:'review',worker:'working'}, {pm:'pm-a',status:'blocked'},
    {pm:'pm-a',status:'in_progress',worker:'idle'}, {pm:'pm-a',status:'in_progress',offline:true},
    {status:'in_progress',worker:'working'}, {status:'blocked',title:'孤儿阻塞'},
    {pm:'pm-a',status:'merged',worker:'working'}, {pm:'pm-a',status:'paused',worker:'working'}
  ]});
  assert.deepEqual(result, {running:1,review:1,blocked:1,waiting:1,unclaimed:1,conclusion:'Alpha 有 1 件事等你。'});
  // Review is the PM's job: a review task alone waits for nobody.
  assert.deepEqual(counts({lang:'zh',pms:[{name:'pm-a',project:'Alpha'}],tasks:[{pm:'pm-a',status:'review'}]}),
    {running:0,review:1,blocked:0,waiting:0,unclaimed:0,conclusion:'现在没有等你的事。'});
  assert.deepEqual(counts({lang:'zh',pms:[],tasks:[]}), {running:0,review:0,blocked:0,waiting:0,unclaimed:0,conclusion:'现在没有等你的事。'});
  // A blocked task the user has answered (pm.py's `answered`) waits for the PM: not counted, as on the bell.
  assert.deepEqual(counts({lang:'zh',pms:[{name:'pm-a',project:'Alpha'}],tasks:[{pm:'pm-a',status:'blocked',answered:true}]}),
    {running:0,review:0,blocked:0,waiting:0,unclaimed:0,conclusion:'现在没有等你的事。'});
  assert.equal(projectCounts({ name: 'pm-a' }, [{ pm: 'pm-a', status: 'blocked', answered: true }, { pm: 'pm-a', status: 'blocked' }]).waiting, 1);
  // Prefers pm.py's top-level `state.counts` when present, and merges local new + remote old states consistently.
  const localNew = {
    lang: 'zh',
    pms: [{ name: 'pm-a', project: 'Alpha', counts: { working: 2, waiting: 1, review: 1, proposed: 0, merged_today: 0 } }],
    tasks: [{ id: 'u1', pm: '', title: '无主任务', status: 'blocked' }],
    events: [],
    counts: { projects: 1, working: 2, waiting: 1, review: 1, proposed: 0, merged_today: 0, unclaimed_blocked: 1 },
  };
  const remoteOld = {
    pms: [{ name: 'pm-b', project: 'Beta' }, { name: 'pm-z', project: 'Old', archived: '2026-11-01' }],
    tasks: [
      { id: 'b1', pm: 'pm-b', status: 'in_progress', offline: false },
      { id: 'b2', pm: 'pm-b', status: 'in_progress', offline: true },
      { id: 'b3', pm: 'pm-b', status: 'blocked' },
      { id: 'z1', pm: 'pm-z', status: 'blocked' },
      { id: 'u2', pm: '', title: '远端无主', status: 'blocked' },
    ],
    events: [],
  };
  const merged = mergeStates(localNew, { dev: remoteOld });
  assert.deepEqual(merged.counts, { projects: 2, working: 3, waiting: 2, review: 1, proposed: 0, merged_today: 0, unclaimed_blocked: 2 });
  const boardCounts = counts(merged);
  const navCounts = summary(localNew, { dev: remoteOld });
  const { active } = projectCards(merged);
  const overview = pageTotals(active, merged);
  // Every overview surface agrees on waiting (2), working (3), and unclaimed blocked (2).
  assert.deepEqual([boardCounts.running, navCounts.active, overview.working], [3, 3, 3]);
  assert.deepEqual([boardCounts.waiting, navCounts.blocked, overview.waiting], [2, 2, 2]);
  assert.deepEqual([boardCounts.unclaimed, overview.unclaimed, unclaimedBlocked(merged).count], [2, 2, 2]);
  assert.deepEqual(unclaimedBlocked(merged).tasks.map(t => t.title), ['无主任务', '远端无主']);
  // Single-project board scopes counts to that project with unclaimed = 0.
  const scoped = scopeState(merged, 'pm-a');
  assert.deepEqual([counts(scoped).running, counts(scoped).waiting, counts(scoped).unclaimed], [2, 1, 0]);
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

test('the pm layout hides every agent notice of an agent the PM or a worker dispatched', async () => {
  const { isWorkerNotice, isHiddenNotice } = await import('../pm-toast/model.js');
  const terms = [
    { address: 't1', state: 'live', labels: { pm: 'demo' } }, // the PM itself
    { address: 't9', state: 'live', parent: 't1', labels: { task: 'demo-fix' } }, // a task worker
    { address: 't10', state: 'live', parent: 't9', labels: { helper: 'h1', 'helper.of': 'demo-fix', 'helper.project': 'demo' } }, // worker helper
    { address: 't11', state: 'live', labels: { helper: 'h2', 'helper.of': 'demo-fix' } }, // helper whose parent worker terminal was removed
    { address: 't12', state: 'live', parent: 't1', labels: { helper: 'h3', 'helper.of': 'pm-demo' } }, // PM helper
    { address: 't13', state: 'live', parent: 't9' }, // unlabelled sub-agent spawned by a task worker
    { address: 't5', state: 'live', parent: 't1' }, // the PM's sub-agent without a task
    { address: 'box/t2', state: 'live', labels: { pm: 'api' } },
    { address: 'box/t4', state: 'live', parent: 'box/t2' },
    { address: 'box/t15', state: 'live', labels: { 'helper.of': 'api-fix' } },
    { address: 'old/t1', state: 'live', labels: { 'pm.retired': 'api' } }, // older peer rotated-out PM
    { address: 'old/t2', state: 'live', parent: 'old/t1' }, // unlabelled worker/sub-agent under legacy retired PM
    { address: 't3', state: 'live' }, // an agent the person started
    { address: 't6', state: 'live', parent: 't3' }, // its own sub-agent
    { address: 't8', state: 'live', parent: 't404' }, // parent not listed
    { address: 'c1', state: 'live', parent: 'c2' }, // cycle guard
    { address: 'c2', state: 'live', parent: 'c1' },
  ];
  const notice = (terminal, title = 'Claude Code finished') =>
    ({ title, body: 'demo / 1', level: 'success', action: { name: 'agent.focus', args: { terminal } }, overlay: 'o1' });
  for (const address of ['t9', 't10', 't11', 't12', 't13', 't5', 'box/t4', 'box/t15', 'old/t2']) {
    for (const title of ['Claude Code finished', 'Codex needs you']) {
      assert.equal(isWorkerNotice(notice(address, title), terms), true, `${address} ${title}`);
      assert.equal(isHiddenNotice(notice(address, title), terms), true, `${address} ${title}`);
    }
  }
  // The PM's own notices (including right after a swap or legacy pm.retired), the person's own agents, cycles, and unknown terminals show (fail open).
  for (const address of ['t1', 'box/t2', 'old/t1', 't3', 't6', 't8', 'c1', 't404', '', undefined]) {
    for (const title of ['Claude Code finished', 'Codex needs you']) {
      assert.equal(isWorkerNotice(notice(address, title), terms), false, `${address} ${title}`);
      assert.equal(isHiddenNotice(notice(address, title), terms), false, `${address} ${title}`);
    }
  }
  assert.equal(isWorkerNotice(notice('t9'), null), false);
  assert.equal(isWorkerNotice(notice('t9'), [{ address: 't1', labels: { pm: '' } }, { address: 't9', parent: 't1' }]), false);
  assert.equal(isWorkerNotice({ ...notice('t9'), action: { name: 'pane.focus', args: { terminal: 't9' } } }, terms), false);
  for (const props of [null, undefined, {}, { title: 'x finished' }]) assert.equal(isWorkerNotice(props, terms), false);
  const source = readFileSync(new URL('../pm-toast/main.js', import.meta.url), 'utf8');
  assert.match(source, /this\.hidden = isWorkerNotice\(p, workers\)/);
});

test('terminal matching skips exited terminals and requires live pm or folder match', () => {
  const exited = { address: 't3b', state: 'exited', cwd: '/r/dudu', labels: { pm: 'dudu' } };
  const pm = { type: 'pm', name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', pane: 'hc:t3b' };
  assert.equal(terminalFor(pm, [exited]), undefined);
  assert.equal(terminalTargetFor(pm, [exited]).terminal, undefined);
  assert.equal(terminalFor({ type: 'task', task: 'dudu-y', pane: 'hc:t3b' }, [exited]), undefined);
  const next = { address: 't3k', state: 'live', cwd: '/r/dudu', labels: { pm: 'dudu' } };
  assert.equal(terminalFor(pm, [exited, next]), next);
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

test('the new-project form runs pm.py start with 0..N equal folders, name, agy/claude/codex/pi, and no --space', () => {
  const script = '/app/mods/pm-dash/skill/scripts/pm.py';
  assert.deepEqual(KINDS, ['claude', 'agy', 'codex', 'pi']);
  assert.equal(AGENT_NAMES.agy, 'agy');
  assert.deepEqual(startArgv(script, { folders: [{ path: '/Users/x/project/repos/homenet', alias: 'homenet' }], name: '', kind: 'claude' }),
    [script, 'start', '--folder', '/Users/x/project/repos/homenet', '--name', 'homenet', '--kind', 'claude']);
  assert.deepEqual(startArgv(script, { folders: [{ path: '/r/a' }, { path: '/r/b' }], name: ' home net ', kind: 'agy' }, { noAppSpace: true, json: true }),
    [script, 'start', '--folder', '/r/a', '--folder', '/r/b', '--name', 'home net', '--kind', 'agy', '--no-app-space', '--json']);
  assert.deepEqual(startArgv(script, { folders: [], name: 'Q3 Planning', kind: 'pi' }),
    [script, 'start', '--name', 'Q3 Planning', '--kind', 'pi']);
  assert.equal(folderName('/r/homenet/'), 'homenet');
  const open = ledgerOpen({ tasks: [{ project: 'homenet', status: 'blocked' }, { project: 'HomeNet', status: 'paused' },
    { project: 'homenet', status: 'merged' }, { project: 'other', status: 'blocked' }] }, 'homenet', ['/tmp/homenet']);
  assert.equal(open.length, 2);

  // Equal folders helper: no primary role, auto-disambiguates duplicate dir names, any folder removable down to 0
  let fs = addFolderEntry([], { path: '/a/api', git: true, branch: 'main' });
  fs = addFolderEntry(fs, { path: '/b/api', git: false });
  assert.equal(fs.length, 2);
  assert.deepEqual(fs.map(f => f.alias), ['api', 'b-api']);
  assert.equal('primary' in fs[0], false);
  fs = removeFolderEntry(fs, '/a/api');
  fs = removeFolderEntry(fs, '/b/api');
  assert.deepEqual(fs, []);

  // Zero-folder submit allowed when name is non-empty
  assert.equal(canSubmitNewProject({ folders: [], name: 'Plan', machine: '' }), true);
  assert.equal(canSubmitNewProject({ folders: [], name: '   ', machine: '' }), false);
  assert.equal(canSubmitNewProject({ folders: [], name: 'Plan', machine: 'dev' }, { remoteReady: false }), false);

  // Machine normalization & active remote space preselection
  const machines = normalizeMachines({ machines: [{ name: 'mbp', state: 'unreachable' }, { name: 'dev', state: 'connected' }] });
  assert.deepEqual(machines.map(m => [m.name, m.connected]), [['dev', true], ['mbp', false]]);
  assert.equal(initialMachineForDialog(machines, [{ id: 'dev/sp1', active: true, machine: 'dev' }]), 'dev');
  assert.equal(initialMachineForDialog(machines, [{ id: 'mbp/sp1', active: true, machine: 'mbp' }]), '');

  // Probe & remote dir parsing
  const probe = parseRemoteProbe('HOME\t/home/dev\nPM\t/home/dev/.dudu/pm.py\nLEDGER\t/home/dev/.dudu\nDIR\t1\t~/repo\t/home/dev/repo\t1\tmain\nDIR\t0\t~/miss\t/home/dev/miss\t0\t\n');
  assert.equal(probe.home, '/home/dev');
  assert.equal(probe.dirs[0].git, true);
  assert.equal(probe.dirs[0].branch, 'main');
  assert.equal(probe.dirs[1].exists, false);
  const dirs = parseRemoteDirs('BASE\t/home/dev/repos\t/home/dev\nENTRY\tzeta\t/home/dev/repos/zeta\t0\t\nENTRY\talpha\t/home/dev/repos/alpha\t1\tmain\n');
  assert.deepEqual(dirs.entries.map(e => e.name), ['alpha', 'zeta']);

  // D1 space close & restore space reuse helpers (fail-closed semantics)
  // Remote space: closes only when only PM (and optionally confirmed finished terminals) remain.
  assert.deepEqual(shouldCloseSpaceAfterArchive({
    machine: 'dev', spaceId: 'sp1', pmTerminal: 't1',
    spaces: [{ id: 'dev/sp1', tabs: [{ id: 'dev/tb1', panes: 1, terminals: [{ terminal: 'dev/t1' }] }] }],
    terminals: [],
  }), { close: true, spaceId: 'dev/sp1' });
  assert.deepEqual(shouldCloseSpaceAfterArchive({
    machine: 'dev', spaceId: 'sp1', pmTerminal: 't1',
    spaces: [{ id: 'dev/sp1', tabs: [{ id: 'dev/tb1', panes: 1, terminals: [{ terminal: 'dev/t1' }] }, { id: 'dev/tb2', panes: 1, terminals: [{ terminal: 'dev/t2' }] }] }],
    terminals: [{ address: 'dev/t2', state: 'finished' }],
  }), { close: true, spaceId: 'dev/sp1' });
  // Remote space with non-PM terminal (even if program.shell: true, remote foreground process is unknown) -> keep Space!
  assert.deepEqual(shouldCloseSpaceAfterArchive({
    machine: 'dev', spaceId: 'sp1', pmTerminal: 't1',
    spaces: [{ id: 'dev/sp1', tabs: [{ id: 'dev/tb1', panes: 1, terminals: [{ terminal: 'dev/t1' }] }, { id: 'dev/tb2', panes: 1, terminals: [{ terminal: 'dev/t2' }] }] }],
    terminals: [{ address: 'dev/t2', state: 'live', status: 'idle', program: { shell: true } }],
  }), { close: false, spaceId: 'dev/sp1' });
  // Missing terminal from terminals() list (remote & local) -> fail-closed (close: false)!
  assert.deepEqual(shouldCloseSpaceAfterArchive({
    machine: 'dev', spaceId: 'sp1', pmTerminal: 't1',
    spaces: [{ id: 'dev/sp1', tabs: [{ id: 'dev/tb1', panes: 1, terminals: [{ terminal: 'dev/t1' }] }, { id: 'dev/tb2', panes: 1, terminals: [{ terminal: 'dev/t_unseen' }] }] }],
    terminals: [],
  }), { close: false, spaceId: 'dev/sp1' });
  assert.deepEqual(shouldCloseSpaceAfterArchive({
    machine: '', spaceId: 'sp1', pmTerminal: 't1',
    spaces: [{ id: 'sp1', tabs: [{ id: 'tb1', panes: 1, terminals: [{ terminal: 't1' }] }, { id: 'tb2', panes: 1, terminals: [{ terminal: 't_missing' }] }] }],
    terminals: [],
  }), { close: false, spaceId: 'sp1' });
  // Unknown state / missing terminal address -> fail-closed (close: false)!
  assert.deepEqual(shouldCloseSpaceAfterArchive({
    machine: '', spaceId: 'sp1', pmTerminal: 't1',
    spaces: [{ id: 'sp1', tabs: [{ id: 'tb1', panes: 1, terminals: [{ terminal: 't1' }] }, { id: 'tb2', panes: 1, terminals: [{ terminal: 't2' }] }] }],
    terminals: [{ address: 't2', status: 'idle', program: { shell: true } }],
  }), { close: false, spaceId: 'sp1' });
  assert.deepEqual(shouldCloseSpaceAfterArchive({
    machine: '', spaceId: 'sp1', pmTerminal: 't1',
    spaces: [{ id: 'sp1', tabs: [{ id: 'tb1', panes: 1, terminals: [{}] }] }],
    terminals: [],
  }), { close: false, spaceId: 'sp1' });
  // Local space with confirmed idle shell closes; active non-shell keeps
  assert.deepEqual(shouldCloseSpaceAfterArchive({
    machine: '', spaceId: 'sp1', pmTerminal: 't1',
    spaces: [{ id: 'sp1', tabs: [{ id: 'tb1', panes: 1, terminals: [{ terminal: 't1' }] }, { id: 'tb2', panes: 1, terminals: [{ terminal: 't2' }] }] }],
    terminals: [{ address: 't2', state: 'live', status: 'idle', program: { shell: true } }],
  }), { close: true, spaceId: 'sp1' });
  assert.deepEqual(shouldCloseSpaceAfterArchive({
    machine: '', spaceId: 'sp1', pmTerminal: 't1',
    spaces: [{ id: 'sp1', tabs: [{ id: 'tb1', panes: 1, terminals: [{ terminal: 't1' }] }, { id: 'tb2', panes: 1, terminals: [{ terminal: 't2' }] }] }],
    terminals: [{ address: 't2', state: 'live', status: 'idle', program: { shell: false } }],
  }), { close: false, spaceId: 'sp1' });
  // Copy polish: empty project name omits `…` and Machine hint avoids `hc exec --on` debug string
  assert.equal(word('en', 'dedicatedSpaceHint', '', '').includes('…'), false);
  assert.equal(word('zh', 'dedicatedSpaceHint', '', 'dev').includes('…'), false);
  assert.equal(word('en', 'machineConnected'), 'Connected');
  assert.equal(word('zh', 'machineConnected'), '已连接');
  assert.deepEqual(resolveRestoreSpace({ machine: 'dev', spaceId: 'sp1', spaces: [{ id: 'dev/sp1' }] }),
    { reuse: true, qualifiedSpaceId: 'dev/sp1' });
  assert.deepEqual(resolveRestoreSpace({ machine: 'dev', spaceId: 'sp1', spaces: [] }),
    { reuse: false, qualifiedSpaceId: '' });
  assert.equal(remotePmArgv(['start', '--name', 'x'])[0], 'sh');
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
    ['in_progress', ['r1', 'w1', 'w2', 'w3']], ['paused', ['p1']], ['later', ['x']]]);
  const g = layout(input, 980);
  assert.deepEqual(g.rows.filter(r => r.type === 'label').map(r => `${r.title} ${r.count}`), ['等你 1', '进行中 4', '暂停 1', 'later 1']);
  // A single task's bundle is one line from the PM; the four in Working (1 review + 3 in progress) share one trunk.
  assert.deepEqual(g.wires.map(w => w.id), ['task:b1', 'trunk:pm-a:in_progress', 'task:r1', 'task:w1', 'task:w2', 'task:w3', 'task:p1', 'task:x']);
  assert.deepEqual(g.routes['task:w2'], ['trunk:pm-a:in_progress', 'task:w2']);
  assert.deepEqual(g.routes['task:r1'], ['trunk:pm-a:in_progress', 'task:r1']);
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

// ---- Finding Python (python.js) ----------------------------------------------
import * as py from './python.js';

// A machine as exec sees it: programs[name](args) gives a result; a missing name rejects as exec does.
const fakeMachine = programs => {
  const calls = [];
  const run = async (command, args, options) => {
    calls.push([command, ...args]);
    if (!programs[command]) throw new Error(`${command}: not found`);
    return programs[command](args, options);
  };
  return { run, calls };
};
const realPython = (major, minor, executable) => args =>
  args.includes(py.PYTHON_PROBE) ? { code: 0, stdout: `pm-python ${major} ${minor} ${executable}\n`, stderr: '' }
    : { code: 0, stdout: `ran ${args.join(' ')}`, stderr: '' };
// Windows' python/python3 app execution aliases when no Python is installed.
const storeStub = () => ({ code: 9009, stdout: '',
  stderr: 'Python was not found; run without arguments to install from the Microsoft Store, or disable this shortcut from Settings > Apps > Advanced app settings > App execution aliases.\r\n' });

test('findPython skips the Microsoft Store stubs and finds nothing on a machine with only them', async () => {
  const m = fakeMachine({ python3: storeStub, python: storeStub });
  assert.equal(await py.findPython(m.run), null);
  assert.deepEqual(m.calls.map(c => c[0]), ['python3', 'py', 'python']); // py absent: asked, rejected, skipped
});

test('findPython takes py -3 when the launcher is the only Python', async () => {
  const m = fakeMachine({ python3: storeStub, python: storeStub, py: realPython(3, 12, 'C:\\Python312\\python.exe') });
  assert.deepEqual(await py.findPython(m.run),
    { command: 'py', args: ['-3'], version: [3, 12], executable: 'C:\\Python312\\python.exe' });
  assert.deepEqual(m.calls[1], ['py', '-3', '-c', py.PYTHON_PROBE]);
});

test('findPython takes python3 first, as macOS and Linux always did', async () => {
  const m = fakeMachine({ python3: realPython(3, 9, '/usr/bin/python3'), py: realPython(3, 12, 'x'), python: realPython(3, 12, 'y') });
  assert.equal((await py.findPython(m.run)).command, 'python3');
  assert.equal(m.calls.length, 1);
});

test('findPython finds nothing when no candidate exists, and passes over a Python older than 3.8', async () => {
  assert.equal(await py.findPython(fakeMachine({}).run), null);
  const old = fakeMachine({ python3: realPython(3, 6, '/usr/bin/python3'), python: realPython(3, 11, 'C:/P/python.exe') });
  assert.equal((await py.findPython(old.run)).command, 'python');
  assert.ok(py.recentEnough([3, 8]) && py.recentEnough([4, 0]) && !py.recentEnough([3, 7]) && !py.recentEnough([2, 7]));
  // A program that prints something else, or a stub that exits 0, is not taken for Python.
  assert.equal(py.probeAnswer({ code: 0, stdout: 'Python was not found', stderr: '' }), null);
});

test('execPython runs the script with the Python found, and says no-python when there is none', async () => {
  py.forgetPython();
  const none = fakeMachine({ python3: storeStub });
  await assert.rejects(py.execPython(none.run, ['pm.py', 'state']), { message: py.NO_PYTHON });
  // A miss is not remembered: Python installed (and Herdr restarted) is found on the next call.
  const later = fakeMachine({ py: realPython(3, 13, 'C:/py.exe') });
  assert.equal((await py.execPython(later.run, ['pm.py', 'state'])).stdout, 'ran -3 pm.py state');
  assert.deepEqual(later.calls.at(-1), ['py', '-3', 'pm.py', 'state']);
  // A hit is: no second probe.
  const asked = later.calls.length;
  await py.execPython(later.run, ['pm.py', 'state']);
  assert.deepEqual(later.calls.slice(asked), [['py', '-3', 'pm.py', 'state']]);
  py.forgetPython();
});

test('a stranded pending findPython probe does not wedge subsequent execPython calls', async () => {
  py.forgetPython();
  // Simulate a layout switch / mod reload stranding the first view's exec task: its Promise never settles.
  const strandedRun = () => new Promise(() => {});
  const stranded = py.execPython(strandedRun, ['pm.py', 'state']);
  let strandedSettled = false;
  stranded.then(() => { strandedSettled = true; }, () => { strandedSettled = true; });

  // A new view instance calls execPython with a healthy exec: it must probe fresh and succeed.
  const healthy = fakeMachine({ python3: realPython(3, 12, '/usr/bin/python3') });
  const result = await py.execPython(healthy.run, ['pm.py', 'state']);
  assert.equal(result.stdout, 'ran pm.py state');
  assert.equal(strandedSettled, false);
  // Once resolved, subsequent calls reuse the cached Python without re-probing.
  const afterProbe = healthy.calls.length;
  await py.execPython(healthy.run, ['setup.py', '--status']);
  assert.deepEqual(healthy.calls.slice(afterProbe), [['python3', 'setup.py', '--status']]);
  py.forgetPython();
});

test("findPython finds this machine's python3 through a real exec", async () => {
  const run = async (command, args) => {
    try { return { code: 0, stdout: execFileSync(command, args, { encoding: 'utf8' }), stderr: '' }; }
    catch (e) { if (e.code === 'ENOENT') throw e; return { code: e.status ?? 1, stdout: String(e.stdout || ''), stderr: String(e.stderr || '') }; }
  };
  const found = await py.findPython(run);
  assert.equal(found.command, 'python3');
  assert.ok(py.recentEnough(found.version) && found.executable);
});

test('python.js never caches an unresolved Promise across dropped view execs', async () => {
  py.forgetPython();
  // First caller's `run` hangs forever (simulating Herdr dropping an exec Promise on layout switch / view close).
  const hungRun = () => new Promise(() => {});
  void py.python(hungRun);
  // Second caller's `run` must still resolve independently instead of deadlocking behind `hungRun`.
  const live = fakeMachine({ python3: realPython(3, 12, '/usr/bin/python3') });
  const out = await py.execPython(live.run, ['pm.py', 'state']);
  assert.equal(out.stdout, 'ran pm.py state');
  py.forgetPython();
});

test('every mod that runs pm.py carries the same python.js, and the card explains a missing Python', () => {
  const here = dirname(new URL(import.meta.url).pathname);
  const source = readFileSync(join(here, 'python.js'), 'utf8');
  for (const mod of ['pm-nav', 'pm-list', 'pm-project']) assert.equal(readFileSync(join(here, '..', mod, 'python.js'), 'utf8'), source, mod);
  // No mod runs python3 by name on this machine any more (another machine's shell lines still may).
  for (const mod of ['pm-dash', 'pm-nav', 'pm-list', 'pm-project']) {
    for (const file of readdirSync(join(here, '..', mod)).filter(f => f.endsWith('.js'))) {
      assert.doesNotMatch(readFileSync(join(here, '..', mod, file), 'utf8'), /exec\(\s*['"]python/, `${mod}/${file}`);
    }
  }
  for (const lang of ['en', 'zh']) {
    for (const key of ['noPython', 'noPythonWindows']) {
      assert.match(word(lang, key), /Python 3/);
      assert.doesNotMatch(word(lang, key), /Microsoft Store|ms-windows-store/);
    }
    assert.match(word(lang, 'noPythonWindows'), /winget install Python\.Python\.3\.12/);
    assert.match(word(lang, 'noPythonWindows'), /python\.org/);
    assert.match(word(lang, 'noPythonWindows'), new RegExp(word(lang, 'setup')));
  }
});

test('without Python the setup card asks for one instead of showing the Store message, and Set up asks again', async () => {
  let found = false;
  const calls = [];
  const board = modWithIO('./main.js', {
    appHome: () => '/app home', home: () => '/test home', setupState, word, run: () => {}, exec: null,
    execPython: async (_run, args) => {
      calls.push(args);
      if (!found) throw new Error('no-python');
      return { code: 0, stdout: JSON.stringify(setupSummary(['claude'], ['claude'])) };
    },
  });
  board.state = { lang: 'zh' };
  board.refresh = () => {};
  await board.checkSetup();
  assert.equal(board.setupStatus, 'missing');
  assert.equal(board.noPython, true);
  assert.equal(board.setupError, '');
  const { cx, drain } = asyncContext();
  board.setUp(cx); await drain();
  assert.equal(board.noPython, true);
  assert.equal(board.setupError, '');
  found = true; // installed, Herdr restarted: the next Set up finds it
  board.setUp(cx); await drain();
  assert.equal(board.noPython, false);
  assert.equal(board.setupStatus, 'ready');
  assert.equal(board.setupDone, true);
});

test('board status and project cards distinguish closed-can-reattach from disconnected and surface lost agents', async () => {
  const { isClosedTask, lostSummary } = await import('./model.js');
  const closedIp = { status: 'in_progress', offline: true, pane: 'hc:t2', closed: { pane: 'hc:t2', at: '2026-11-21 10:00', why: 'idle-workers --close' } };
  const crashedIp = { status: 'in_progress', offline: true, pane: 'hc:t3' };
  const closedRev = { status: 'review', offline: true, pane: 'hc:t4', closed: { pane: 'hc:t4', why: 'workers.close_reported' } };
  const staleClosed = { status: 'in_progress', offline: true, pane: 'hc:t9', closed: { pane: 'hc:t2', why: 'killed' } };

  assert.equal(isClosedTask(closedIp), true);
  assert.equal(isClosedTask(crashedIp), false);
  assert.equal(isClosedTask(staleClosed), false);

  assert.equal(taskStatusText('en', closedIp), 'Closed · can reattach');
  assert.equal(taskStatusText('zh', closedIp), '已关闭，可重连');
  assert.equal(taskStatusText('en', crashedIp), 'Disconnected');
  assert.equal(taskStatusText('zh', crashedIp), '已断开');
  assert.equal(taskStatusText('en', closedRev), 'Review · closed');
  assert.equal(taskStatusText('zh', closedRev), '待审 · 已关闭');

  const lost = { pm: { address: 't1', how: 'server_stop' }, threads: [{ id: 'a', title: 'A', address: 't2', how: 'server_stop' }], restart: true, key: 'pm@t1;a@t2' };
  assert.equal(lostSummary('zh', lost), '重启后 PM 和 1 个 agent 没回来');
  assert.equal(lostSummary('en', lost), 'PM and 1 agent did not come back');
  const cards = projectCards({
    pms: [
      { name: 'pm-dudu', project: 'dudu', lost, undelivered: { count: 2, waiting_seconds: 900, state: 'unknown', deliverer_running: true } },
      { name: 'pm-old', project: 'old', archived: '2026-11-01', lost, undelivered: { count: 1, waiting_seconds: 900, state: 'offline', deliverer_running: false } },
    ],
    tasks: [],
    events: [],
  });
  assert.deepEqual(cards.active[0].lost, lost);
  assert.equal(cards.archived[0].lost, undefined);
  assert.equal(cards.active[0].undelivered.count, 2);
  assert.equal(cards.archived[0].undelivered, undefined);
  const { undeliveredSummary } = await import('./model.js');
  assert.equal(undeliveredSummary('en', cards.active[0].undelivered), '2 undelivered (15m)');
  assert.equal(undeliveredSummary('zh', cards.active[0].undelivered), '2 条未送达（15 分钟）');
  assert.equal(undeliveredSummary('en', null), '');
  // A user message past its SLA with no batch waiting (`count` 0) still shows; both add up.
  assert.equal(undeliveredSummary('en', { count: 0, messages: 1, waiting_seconds: 180, message_reason: 'blocked_prompt' }),
    '1 undelivered (3m)');
  assert.equal(undeliveredSummary('en', { count: 2, messages: 1, waiting_seconds: 900 }), '3 undelivered (15m)');
});

test('board bundles merge review and answered tasks into Working ordered by post-gate -> review -> answered -> in_progress', async () => {
  const { BUNDLES, taskSteps, isPostGateTask, PLAN_STRINGS, STEP_LABEL_UNITS } = await import('./model.js');
  assert.equal(STEP_LABEL_UNITS, 24);
  assert.deepEqual(Object.keys(PLAN_STRINGS.en), Object.keys(PLAN_STRINGS.zh));
  assert.deepEqual(BUNDLES, ['blocked', 'in_progress', 'proposed', 'paused']);
  const tasks = [
    { id: 'ip-old', status: 'in_progress', updated: '2026-11-21 10:00' },
    { id: 'ip-new', status: 'in_progress', updated: '2026-11-21 12:00' },
    { id: 'ans', status: 'blocked', answered: true, updated: '2026-11-21 11:00' },
    { id: 'rev-old', status: 'review', updated: '2026-11-21 09:00' },
    { id: 'rev-new', status: 'review', updated: '2026-11-21 13:00' },
    { id: 'post', status: 'in_progress', updated: '2026-11-21 08:00',
      plan: ['[x] 实现接口', '[x] 独立审查', '[x] 合进 main', '[>] 装到 MBP'] },
    { id: 'wait', status: 'blocked', updated: '2026-11-21 07:00' },
  ];
  assert.equal(isPostGateTask(tasks.find(t => t.id === 'post')), true);
  assert.equal(isPostGateTask(tasks.find(t => t.id === 'ip-new')), false);
  const grouped = boardGroups(tasks);
  assert.deepEqual(grouped.bundles.map(b => [b.status, b.tasks.map(t => t.id)]), [
    ['blocked', ['wait']],
    ['in_progress', ['post', 'rev-new', 'rev-old', 'ans', 'ip-new', 'ip-old']],
  ]);

  const postSteps = taskSteps(tasks.find(t => t.id === 'post'), { lang: 'zh' });
  assert.equal(postSteps.pill, '3/4 · 装到 MBP');
  assert.equal(postSteps.postGate, true);
  const objPostTask = {
    id: 'obj-post',
    status: 'in_progress',
    offline: true,
    plan: [
      { text: '实现接口', state: 'done', anchor: 'work' },
      { text: '独立审查', state: 'done', anchor: 'review' },
      { text: '合进 main', state: 'done', anchor: 'merge' },
      { text: '同步安装到 MBP 并跑全量测试', state: 'doing', anchor: 'custom' },
    ],
  };
  assert.equal(isPostGateTask(objPostTask), true);
  const objPostSteps = taskSteps(objPostTask, { lang: 'zh' });
  assert.equal(objPostSteps.postGate, true);
  assert.equal(objPostSteps.pill, '3/4 · 同步安装到 MBP 并跑全量…');

  const blockedPlan = [
    { text: '实现', state: 'done', anchor: 'work' },
    { text: '独立审查', state: 'todo', anchor: 'review' },
    { text: '合进 main', state: 'todo', anchor: 'merge' },
  ];
  assert.deepEqual(taskSteps({ status: 'blocked', plan: blockedPlan }, { lang: 'zh' }).steps.map(s => s.state), ['done', 'todo', 'todo']);
  assert.deepEqual(taskSteps({ status: 'blocked', review: { id: 'r1', status: 'in_progress' }, plan: blockedPlan }, { lang: 'zh' }).steps.map(s => s.state), ['done', 'doing', 'todo']);
  assert.equal(taskSteps({ id: 'legacy', status: 'review' }, { lang: 'zh' }).pill, '');
  const reviewSteps = taskSteps({
    id: 'lib',
    status: 'review',
    rounds: 1,
    plan: ['[x] 派出对齐', '[>] 分支实现与单测', '独立代码审查', '合进 main（pm.py land）', '同步安装到本机与 MBP'],
  }, { lang: 'zh' });
  assert.equal(reviewSteps.pill, '2/5');
  assert.equal(reviewSteps.rail.length, 5);
  assert.equal(reviewSteps.steps[3].shortText, '合进 main');
  assert.equal(reviewSteps.steps[3].note, 'pm.py land');
  assert.equal(reviewSteps.steps[3].tip, '合进 main（pm.py land）');
  assert.equal(word('zh', 'reviewing'), '审查中');
  assert.equal(word('en', 'reviewing'), 'Reviewing');
  assert.equal(word('zh', 'planTitle'), '步骤');
  assert.equal(word('en', 'planTitle'), 'Steps');
});

test('Board UI renders Reviewing inside Working bundle, step progress chips, postGate amber pill, and hover stage rail (en & zh)', async () => {
  const { readFileSync } = await import('node:fs');
  const dashModel = await import('./model.js');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '')
    .replace('export default class PmDash extends View', 'return class');

  const nodes = new Map();
  const makeEl = () => {
    const rec = { id: '', texts: [], kids: [], hover: null, clicks: null, sizeChange: null };
    const allTexts = r => [...r.texts, ...r.kids.flatMap(allTexts)];
    const proxy = new Proxy(function () {}, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        return (...args) => {
          if (key === 'id') {
            rec.id = String(args[0]);
            nodes.set(rec.id, rec);
          } else if (key === 'child') {
            if (typeof args[0] === 'string') rec.texts.push(args[0]);
            else if (args[0]?.__rec) rec.kids.push(args[0].__rec);
          } else if (key === 'content' && args[0]?.__rec) {
            rec.kids.push(args[0].__rec);
          } else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) {
              if (typeof k === 'string') rec.texts.push(k);
              else if (k?.__rec) rec.kids.push(k.__rec);
            }
          } else if (key === 'on_hover') {
            rec.hover = args[0];
          } else if (key === 'on_click') {
            rec.clicks = args[0];
          } else if (key === 'on_size_change') {
            rec.sizeChange = args[0];
          } else if (key === 'when') {
            if (args[0]) args[1](proxy);
          }
          return proxy;
        };
      },
      apply: () => proxy,
    });
    rec.allTexts = () => allTexts(rec);
    return proxy;
  };
  const blankFn = () => makeEl();
  const svgStub = path => {
    const el = makeEl();
    if (path) el.__rec.texts.push(`[svg:${path}]`);
    return el;
  };
  const openedProjects = [];
  const stubs = {
    View: class {}, ...dashModel, renderStepsCard, renderDepsCard,
    div: makeEl, v_flex: makeEl, h_flex: makeEl, svg: svgStub, PathBuilder: { moveTo: () => makeEl() },
    Scrollbar: { vertical: blankFn },
    Popup: { new: (id, trig) => makeEl().id(id).child(trig) },
    FlowLayer: class {},
    boardVisible: () => true,
    page: '', pageView: blankFn, pageHeader: blankFn, projectHeader: blankFn, keepPress: blankFn, dialogView: blankFn,
    initDialog: () => {}, restoreProject: () => {}, readLines: async () => [], archivePopup: blankFn,
    NEW_DIALOG: 'new', openProject: (...args) => openedProjects.push(args), showPage: () => {},
    execPython: async () => ({ code: 0, stdout: '{}', stderr: '' }), NO_PYTHON: 'no_python',
    theme: () => ({
      canvas: '#111111', background: '#111111', surface: '#1a1a1a', raised: '#222222', popover: '#222222', selected: '#2a2a2a',
      border: '#333333', input: '#3a3a3a',
      foreground: '#eeeeee', muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', accent_foreground: '#ffffff',
      blocked: '#ff5f56', ansi2: '#27c93f', ansi3: '#f5a623', ansi4: '#6699ff', ansi5: '#c678dd', ansi6: '#56b6c2', ansi1: '#e06c75',
    }),
    home: () => '/Users/test', appHome: () => '/app', exec: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    readTextFile: async () => '', appWindow: () => ({}), watchFolder: () => new Promise(() => {}),
    terminals: () => [
      { address: 'tw1', state: 'live', labels: { task: 'ip-steps' } },
      { address: 'tw2', state: 'live', labels: { task: 'post-task' } },
      { address: 'tw3', state: 'live', labels: { task: 'rev-task' } },
    ],
    agents: () => [], panes: () => [], run: () => {}, props: () => ({}), closeOverlay: () => {}, openOverlay: () => {},
    desktopLayout: () => ({}),
  };
  const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
  const timers = [];
  const cx = {
    focus_handle: () => ({ focus() {} }),
    spawn: () => {},
    timer: {
      after(_ms, fn) {
        const entry = { fn, cancelled: false, cancel() { this.cancelled = true; } };
        timers.push(entry);
        return entry;
      },
      every() {},
    },
    notify() {},
    stop_propagation() {},
  };
  const tasks = [
    {
      id: 'ip-steps', pm: 'pm-dudu', project: 'dudu', title: 'Render UI', status: 'in_progress', updated: '2026-11-21 10:00',
      branch: 'dev/render-ui',
      plan: ['[x] Align design', '[>] Build panel with complete untruncated step title', 'Code review', 'Merge'],
      subplan: ['[x] Left rows', '[>] Detail steps'],
      latest: 'status=in_progress, commit=abc1234; wiring steps view\nsecond line collapsed',
    },
    {
      id: 'post-task', pm: 'pm-dudu', project: 'dudu', title: 'Deploy to host', status: 'in_progress', updated: '2026-11-21 11:00',
      plan: ['[x] Implement', '[x] Review', '[x] Merge', '[>] Install on MBP'],
    },
    {
      id: 'rev-task', pm: 'pm-dudu', project: 'dudu', title: 'At-mention fix', status: 'review', updated: '2026-11-21 12:00',
      plan: ['[x] Code', '[>] Independent review', 'Merge'],
      subplan: ['[x] Parser', '[x] Popup menu'],
    },
  ];
  const view = Object.assign(Object.create(Mod.prototype), {
    state: { pms: [{ name: 'pm-dudu', project: 'dudu', status: 'idle', repo: '/r/dudu' }], tasks, events: [], lang: 'en' },
    allState: { pms: [], tasks: [], events: [] }, lines: {}, scope: 'pm-dudu', hoverCard: null,
    endedOpen: new Set(), showDropped: new Set(), hoverEnded: null,
    keys: cx.focus_handle(), onStage: true, size: { width: 1280, height: 720 },
    queue: [], recent: [], replayIndex: 0, auto: false, flowLayer: { set() {} }, flowKey: '',
    hoverTask: null, hoverMeasure: null, shownStatus: {}, shownLive: {}, hoverPm: null,
    shown: {}, statuses: {}, tags: {}, nudges: {}, serial: 0, trip: null,
    text(k, ...a) { return dashModel.word(this.state.lang, k, ...a); },
    today: () => '2026-11-21',
    peeking: () => false,
    tag() {},
  });

  const g = view.geometry();
  view.boardBounds = { x: 0, y: 0, width: view.size.width, height: view.size.height };
  view.stageBounds = { x: 0, y: 0, width: g.width, height: g.height };
  const drawn = g.rows.map(r => view.presentation(r, stubs.terminals(), []));
  for (const r of drawn) view.row(r, stubs.theme(), cx, { waiting: 0 }, g.scale);

  assert.deepEqual(nodes.get('status:task:rev-task')?.texts, ['Reviewing']);
  assert.deepEqual(nodes.get('steps:task:ip-steps')?.texts, ['1/4']);
  assert.deepEqual(nodes.get('steps:task:rev-task')?.texts, ['1/3']);
  assert.deepEqual(nodes.get('steps:task:post-task')?.texts, ['3/4 · Install on MBP']);
  assert.equal(nodes.has('status:task:post-task'), false, 'postGate in_progress suppresses redundant In progress badge');

  // Hover card shows compact vertical Steps component: doing step expands substeps, done step folds substeps,
  // long step names are never truncated, latest log is single-line, and card is read-only.
  view.hoverMeasure = null;
  const targetRow = drawn.find(r => r.task === 'ip-steps');
  view.taskInfoCard(targetRow, g, stubs.theme(), drawn);
  const probe = [...nodes.entries()].find(([id]) => id.startsWith('task-log-probe:'))?.[1];
  assert.ok(probe?.sizeChange, 'offscreen measurement probe attached');
  probe.sizeChange({ width: 220, height: 150 }, cx);
  nodes.clear();
  view.taskInfoCard(targetRow, g, stubs.theme(), drawn);
  const stepsText = nodes.get('info-steps:task:ip-steps')?.allTexts().join(' ') || '';
  assert.match(stepsText, /Steps/);
  assert.match(stepsText, /dev\/render-ui/);
  assert.match(stepsText, /1\/4/);
  assert.match(stepsText, /Align design/);
  assert.match(stepsText, /Build panel with complete untruncated step title/, 'long step name is not truncated');
  assert.match(stepsText, /Left rows/, 'doing step expands substeps');
  assert.match(stepsText, /Detail steps/, 'doing step shows active substep');
  assert.match(stepsText, /check-mark\.svg/);
  assert.match(stepsText, /spinner\.svg/);
  assert.doesNotMatch(stepsText, /tree-branch\.svg/, 'Plan B substeps drop curved tree-branch wires');
  assert.doesNotMatch(stepsText, /→/, 'no arrow chain in hover card');
  assert.doesNotMatch(stepsText, /window-pop\.svg/, 'read-only hover card omits window toggle');
  assert.equal(nodes.get('info-log:task:ip-steps')?.allTexts().join(' '), 'wiring steps view second line collapsed');

  // Review task folds completed substeps on the done work step (`2/2` pill, substep text hidden)
  view.hoverMeasure = null;
  const revRow = drawn.find(r => r.task === 'rev-task');
  view.taskInfoCard(revRow, g, stubs.theme(), drawn);
  const revProbe = [...nodes.entries()].find(([id]) => id.startsWith('task-log-probe:'))?.[1];
  revProbe.sizeChange({ width: 220, height: 120 }, cx);
  nodes.clear();
  view.taskInfoCard(revRow, g, stubs.theme(), drawn);
  const revStepsText = nodes.get('info-steps:task:rev-task')?.allTexts().join(' ') || '';
  assert.match(revStepsText, /2\/2/, 'completed work step folds substeps into 2/2 badge');
  assert.doesNotMatch(revStepsText, /Popup menu/, 'done step substeps stay folded');

  // Chinese i18n parity in board rows and hover card
  view.state.lang = 'zh';
  nodes.clear();
  const zhG = view.geometry();
  const zhDrawn = zhG.rows.map(x => view.presentation(x, stubs.terminals(), []));
  for (const r of zhDrawn) view.row(r, stubs.theme(), cx, { waiting: 0 }, zhG.scale);
  assert.deepEqual(nodes.get('status:task:rev-task')?.texts, ['审查中']);
  view.hoverMeasure = null;
  const zhRow = zhDrawn.find(r => r.task === 'ip-steps');
  view.taskInfoCard(zhRow, zhG, stubs.theme(), zhDrawn);
  const zhProbe = [...nodes.entries()].find(([id]) => id.startsWith('task-log-probe:'))?.[1];
  zhProbe.sizeChange({ width: 220, height: 150 }, cx);
  nodes.clear();
  view.taskInfoCard(zhRow, zhG, stubs.theme(), zhDrawn);
  const zhStepsText = nodes.get('info-steps:task:ip-steps')?.allTexts().join(' ') || '';
  assert.match(zhStepsText, /步骤/);
  assert.match(zhStepsText, /自动审/);

  // Task numbers on board rows, ended rows, taskInfoCard, and eventLine (omitted on unnumbered peers)
  assert.equal(taskNumber({ number: 7 }), 7);
  assert.equal(formatTaskNumber({ number: 7 }), '#7');
  assert.equal(formatTaskNumber({}), '');
  tasks[0].number = 7;
  tasks.push({ id: 'done-num', pm: 'pm-dudu', project: 'dudu', title: 'Done numbered', status: 'done', number: 5, updated: '2026-11-21 09:00' });
  view.state.tasks = tasks;
  view.state.lang = 'en';
  view.hoverMeasure = null;
  nodes.clear();
  const numG = view.geometry();
  const numDrawn = numG.rows.map(x => view.presentation(x, stubs.terminals(), []));
  for (const r of numDrawn) view.row(r, stubs.theme(), cx, { waiting: 0 }, numG.scale);
  assert.ok(nodes.get('title:task:ip-steps'));
  const ipRow = numDrawn.find(r => r.task === 'ip-steps');
  view.taskInfoCard(ipRow, numG, stubs.theme(), numDrawn);
  const numProbe = [...nodes.entries()].find(([id]) => id.startsWith('task-log-probe:'))?.[1];
  numProbe.sizeChange({ width: 220, height: 150 }, cx);
  nodes.clear();
  view.taskInfoCard(ipRow, numG, stubs.theme(), numDrawn);
  const endedNode = numDrawn.find(r => r.type === 'ended');
  view.endedPeek(endedNode, numG, stubs.theme(), numDrawn);
  assert.match(view.eventLine({ task: 'ip-steps', text: 'updated' }), /#7 Render UI/);
  assert.doesNotMatch(view.eventLine({ task: 'rev-task', text: 'updated' }), /#\d+/);
  // Check board hover card renders #7 for numbered task
  assert.equal(nodes.has('task-info-popup:task:ip-steps'), true);
  assert.match(nodes.get('info-steps:task:ip-steps')?.allTexts().join(' ') || '', /#7/);

  // Proposed task with depends_on on Board: shows Waiting list + Ready to dispatch (en & zh),
  // persists across row->card transition via grace timer + card hover, and clicking jumps via openProject.
  tasks.push(
    { id: 'done-pre', pm: 'pm-dudu', project: 'dudu', title: 'Base schema', status: 'merged', updated: '2026-11-21 09:00' },
    {
      id: 'prop-wait', pm: 'pm-dudu', project: 'dudu', title: 'Queued feature', status: 'proposed', updated: '2026-11-21 12:10',
      depends_on: ['done-pre', 'rev-task'],
      deps: [
        { id: 'done-pre', title: 'Base schema', state: 'met', status: 'merged', reason: 'merged' },
        { id: 'rev-task', title: 'At-mention fix', state: 'waiting', status: 'review', reason: 'review' },
      ],
      ready: false,
      latest: 'Waiting for Base schema & At-mention fix',
    },
    {
      id: 'prop-ready', pm: 'pm-dudu', project: 'dudu', title: 'Ready feature', status: 'proposed', updated: '2026-11-21 12:12',
      depends_on: ['done-pre'],
      deps: [{ id: 'done-pre', title: 'Base schema', state: 'met', status: 'merged', reason: 'merged' }],
      ready: true,
    },
  );
  view.state.lang = 'en';
  const depG = view.geometry();
  const depDrawn = depG.rows.map(x => view.presentation(x, stubs.terminals(), []));
  const waitRow = depDrawn.find(r => r.task === 'prop-wait');
  const readyRow = depDrawn.find(r => r.task === 'prop-ready');
  view.hoverTask = 'prop-wait';
  view.hoverMeasure = null;
  nodes.clear();
  view.taskInfoCard(waitRow, depG, stubs.theme(), depDrawn, stubs.terminals(), []);
  const waitProbe = [...nodes.entries()].find(([id]) => id.startsWith('task-log-probe:'))?.[1];
  waitProbe.sizeChange({ width: 220, height: 130 }, cx);
  nodes.clear();
  view.taskInfoCard(waitRow, depG, stubs.theme(), depDrawn, stubs.terminals(), []);
  const waitText = nodes.get('info-deps:task:prop-wait')?.allTexts().join(' ') || '';
  assert.match(waitText, /Waiting/);
  assert.match(waitText, /1\/2/);
  assert.match(waitText, /Base schema/);
  assert.match(waitText, /At-mention fix/);
  assert.match(waitText, /check-mark\.svg/);
  assert.match(waitText, /chevron\.svg/);

  // Leaving row does not immediately wipe interactive hover card; entering card cancels timer; clicking dep jumps!
  timers.length = 0;
  view.leaveTaskHover('prop-wait', cx);
  assert.equal(view.hoverTask, 'prop-wait');
  assert.ok(timers.length > 0);
  const boardHideTimer = timers.at(-1);
  nodes.get('task-info-card:task:prop-wait').hover(true, cx);
  assert.equal(boardHideTimer.cancelled, true, 'entering board hover card cancels hide timer');
  nodes.get('info-dep-task:prop-wait-rev-task').clicks({}, cx);
  assert.equal(view.hoverTask, null, 'clicking prerequisite clears hover');
  assert.deepEqual(openedProjects, [['pm-dudu', '', 'rev-task']], 'clicking Board prerequisite opens project & jumps to task');

  // All-met proposed task shows Ready to dispatch (en) & 可以派了 (zh)
  view.hoverTask = 'prop-ready';
  view.hoverMeasure = null;
  nodes.clear();
  view.taskInfoCard(readyRow, depG, stubs.theme(), depDrawn, stubs.terminals(), []);
  const readyProbe = [...nodes.entries()].find(([id]) => id.startsWith('task-log-probe:'))?.[1];
  readyProbe.sizeChange({ width: 220, height: 110 }, cx);
  nodes.clear();
  view.taskInfoCard(readyRow, depG, stubs.theme(), depDrawn, stubs.terminals(), []);
  assert.match(nodes.get('info-deps:task:prop-ready')?.allTexts().join(' ') || '', /Ready to dispatch/);

  view.state.lang = 'zh';
  view.hoverMeasure = null;
  nodes.clear();
  view.taskInfoCard(readyRow, depG, stubs.theme(), depDrawn, stubs.terminals(), []);
  const zhReadyProbe = [...nodes.entries()].find(([id]) => id.startsWith('task-log-probe:'))?.[1];
  zhReadyProbe.sizeChange({ width: 220, height: 110 }, cx);
  nodes.clear();
  view.taskInfoCard(readyRow, depG, stubs.theme(), depDrawn, stubs.terminals(), []);
  const zhReadyText = nodes.get('info-deps:task:prop-ready')?.allTexts().join(' ') || '';
  assert.match(zhReadyText, /等待/);
  assert.match(zhReadyText, /可以派了/);
});

test('reviewWorking gates blue review spinner on active reviewer only (local & remote)', () => {
  const mkRev = (overrides = {}) => ({
    id: 't1-review', review_of: 't1', status: 'in_progress', pane: 'hc:tr1', ...overrides,
  });
  const mkTask = (overrides = {}) => ({
    id: 't1', pm: 'pm-dudu', title: 'Review motion', status: 'review', pane: 'hc:tw1', review: mkRev(), ...overrides,
  });

  // Active local reviewer -> true
  assert.equal(reviewWorking(mkTask(), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], []), true);
  assert.equal(reviewWorking(mkTask(), [{ address: 'tr1', state: 'live', status: 'idle', labels: { task: 't1-review' } }], [{ address: 'tr1', status: 'working' }]), true);
  // Active remote reviewer (machine namespace inherited from task) -> true
  const remoteTask = mkTask({ id: 'mbp/t1', sourceId: 't1', machine: 'mbp', review: mkRev({ id: 't1-review', pane: 'hc:tr9' }) });
  assert.equal(reviewWorking(remoteTask, [{ address: 'mbp/tr9', state: 'live', status: 'working', labels: { task: 't1-review' } }], []), true);
  assert.equal(reviewWorking(remoteTask, [{ address: 'tr9', state: 'live', status: 'working', labels: { task: 't1-review' } }], []), false);
  // Fallback to review.worker when terminal is not in desktop
  assert.equal(reviewWorking(mkTask({ review: mkRev({ pane: '', worker: 'working' }) }), [], []), true);
  assert.equal(reviewWorking(mkTask({ review: mkRev({ pane: '', worker: 'idle' }) }), [], []), false);

  // Static cases: waiting for PM (no review), review done/paused/blocked/offline, reviewer idle/done, non-review task
  assert.equal(reviewWorking(mkTask({ review: undefined }), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], []), false);
  assert.equal(reviewWorking(mkTask({ review: mkRev({ status: 'done' }) }), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], []), false);
  assert.equal(reviewWorking(mkTask({ review: mkRev({ status: 'paused' }) }), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], []), false);
  assert.equal(reviewWorking(mkTask({ review: mkRev({ status: 'blocked' }) }), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], []), false);
  assert.equal(reviewWorking(mkTask({ review: mkRev({ offline: true }) }), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], []), false);
  assert.equal(reviewWorking(mkTask(), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], [{ address: 'tr1', status: 'idle' }]), false);
  assert.equal(reviewWorking(mkTask(), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], [{ address: 'tr1', status: 'done' }]), false);
  assert.equal(reviewWorking(mkTask({ status: 'in_progress' }), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], []), false);
  assert.equal(reviewWorking(mkTask({ cleanup: true }), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], []), false);
});

test('render safety: pm-dash taskInfoCard guards null renderStepsCard, Popup styles on anchor, render-phase clearHover safe, word() fallback', () => {
  // word() has both steps.js tips and falls back to key for unknown keys
  assert.equal(word('en', 'detailReviewStepTip'), 'Click to toggle review window');
  assert.equal(word('zh', 'detailReviewStepTip'), '点击开关审查小窗');
  assert.equal(word('en', 'substepsFoldTip', 2, 4), '2/4 sub-steps');
  assert.equal(word('zh', 'substepsFoldTip', 2, 4), '2/4 个子步骤');
  assert.equal(word('en', 'unknownFallbackKey'), 'unknownFallbackKey');
  assert.equal(label('en', ''), 'Unknown');
  assert.equal(label('en', null), 'Unknown');

  const makeEl = (tag, extra = {}) => {
    const node = { tag, props: { ...extra }, children: [], handlers: {} };
    const chain = new Proxy({}, {
      get(_t, prop) {
        if (prop === '__node') return node;
        if (prop === 'child') return c => {
          if (c == null) throw new TypeError('child(value) expects an element, a string, or an entity');
          node.children.push(c?.__node || c);
          return chain;
        };
        if (prop === 'children') return cs => {
          for (const c of cs) {
            if (c == null) throw new TypeError('children contains null/undefined');
            node.children.push(c?.__node || c);
          }
          return chain;
        };
        if (prop === 'content') return c => { node.content = c?.__node || c; return chain; };
        if (prop === 'when') return (cond, fn) => cond ? fn(chain) : chain;
        if (prop.startsWith('on_')) return fn => { node.handlers[prop] = fn; return chain; };
        return (...args) => { node.props[prop] = args.length <= 1 ? (args.length === 0 ? true : args[0]) : args; return chain; };
      },
    });
    return chain;
  };
  const findById = (n, prefix) => {
    if (!n || typeof n !== 'object') return null;
    if (String(n.props?.id || '').startsWith(prefix)) return n;
    for (const c of [...(n.children || []), ...(n.content ? [n.content] : [])]) {
      const hit = findById(c, prefix);
      if (hit) return hit;
    }
    return null;
  };

  let visible = false;
  const view = modWithIO('./main.js', {
    div: () => makeEl('div'), v_flex: () => makeEl('v_flex'), h_flex: () => makeEl('h_flex'),
    svg: () => makeEl('svg'), PathBuilder: { stroke: () => ({ move_to: () => ({ cubic_bezier_to() {}, build: () => ({}) }) }) },
    Scrollbar: { new: () => makeEl('scrollbar') },
    Popup: { new: (id, trigger) => makeEl('Popup', { id, trigger: trigger?.__node || trigger }) },
    theme: () => ({ canvas: '#111113', background: '#111113', surface: '#1b1b1f', raised: '#27272d',
      foreground: '#f2f2f5', muted: '#a0a0aa', dim: '#6b6b76', border: '#2e2e36',
      accent: '#4da3ff', blocked: '#ff6b6b', ansi1: '#ff6b6b', ansi2: '#4cd964',
      ansi3: '#ffcc00', ansi4: '#4da3ff', ansi5: '#bf5af2', ansi6: '#5ac8fa' }),
    home: () => '/h', appHome: () => '/a', exec: async () => ({ code: 0, stdout: '' }),
    readTextFile: async () => '', watchFolder: async () => {}, terminals: () => [], agents: () => [], panes: () => [],
    run: () => {}, props: () => ({}), closeOverlay: () => {}, openOverlay: () => {}, desktopLayout: () => ({}),
    setupState, fitBoard, withAlpha, solidText, isDarkTheme, cleanTaskLog, hoverCardPosition, newEvents,
    pmId, taskId, eventText, terminalFor, terminalTargetFor, focusPlan, pmColor, counts, projectCounts,
    wireFlows, reviewWorking, word, label, taskStatusText, isClosedTask, formatTaskNumber, tooltipLayout,
    taskSteps: () => ({ steps: [], progress: '0/0' }),
    taskDependencies, mergeStates, cachedRemoteStates, LEDGER_HOME_SH, remoteStateCommand,
    pmStatusText, scopeState, archiveThreads: () => [], disconnected, escapeTarget: () => null, DROPPED, endedTime,
    page: () => ({ view: 'board', project: 'pm-dudu' }), pageView: () => makeEl('page'),
    pageHeader: () => makeEl('header'), projectHeader: () => makeEl('header'), keepPress: (_v, el) => el,
    dialogView: () => makeEl('dialog'), initDialog: () => {}, restoreProject: () => {}, readLines: async () => ({}),
    archivePopup: () => ({}), NEW_DIALOG: {}, openProject: () => {}, showPage: () => {},
    FlowLayer: class {}, boardVisible: () => visible, renderStepsCard, renderDepsCard,
  });

  view.state = {
    lang: 'en', project: 'pm-dudu',
    pms: [{ name: 'pm-dudu', project: 'dudu' }],
    tasks: [
      { id: 't-empty-steps', pm: 'pm-dudu', title: 'No Steps Task', status: 'in_progress', latest: 'just a log', updated: '2026-11-22 01:00' },
      { id: 't-completely-empty', pm: 'pm-dudu', title: 'Bare Task', status: 'in_progress', latest: '', updated: '2026-11-22 01:01' },
    ],
    events: [],
  };
  view.allState = view.state;
  view.size = { width: 1280, height: 720 };
  view.setupStatus = 'ready';
  view.scope = 'pm-dudu';
  view.keys = { focus() {} };
  view.shown = {}; view.shownStatus = {}; view.shownLive = {}; view.statuses = {}; view.tags = {}; view.nudges = {};
  view.queue = []; view.endedOpen = new Set(); view.showDropped = new Set(); view.hoverEnded = null; view.hoverPm = null;
  view.flowLayer = { set_props() {} };

  const g = view.geometry();
  view.boardBounds = { x: 0, y: 0, width: view.size.width, height: view.size.height };
  view.stageBounds = { x: 0, y: 0, width: g.width, height: g.height };
  const drawn = g.rows.map(r => view.presentation(r, [], []));

  // taskInfoCard with empty steps & a log line: must not throw on .child(null)
  const logRow = drawn.find(r => r.task === 't-empty-steps');
  assert.doesNotThrow(() => view.taskInfoCard(logRow, g, { raised: '#27272d', surface: '#1b1b1f', border: '#2e2e36', dim: '#6b6b76', muted: '#a0a0aa' }, drawn));

  // taskInfoCard with empty steps, no metaText, no logLine: returns null cleanly
  const bareRow = drawn.find(r => r.task === 't-completely-empty');
  assert.equal(view.taskInfoCard(bareRow, g, { raised: '#27272d', surface: '#1b1b1f', border: '#2e2e36', dim: '#6b6b76', muted: '#a0a0aa' }, drawn), null);

  // endedPeek puts positioning on outer anchor div, NOT on Popup
  const endedRow = { type: 'ended', pm: 'pm-dudu', x: g.taskX, y: Math.max(40, g.height - 60), w: 200, h: 32, count: 2,
    peek: [{ id: 'd1', title: 'Done 1', status: 'merged', updated: '2026-11-22 00:00' }] };
  const peekTree = view.endedPeek(endedRow, g, { raised: '#27272d', surface: '#1b1b1f', foreground: '#fff', muted: '#aaa', dim: '#666' }, drawn).__node;
  const peekPopup = findById(peekTree, 'ended-peek-popup:pm-dudu');
  const peekAnchor = findById(peekTree, 'ended-peek-anchor:pm-dudu');
  assert.ok(peekPopup && peekAnchor);
  assert.equal(peekPopup.props.absolute, undefined, 'endedPeek Popup must not chain .absolute()');
  assert.equal(peekPopup.props.left, undefined, 'endedPeek Popup must not chain .left()');
  assert.equal(peekAnchor.props.absolute, true);

  // Leaving stage during render() clears hover state & cancels timer without calling cx.notify()
  let cancelled = false;
  view.onStage = true;
  view.hoverTask = 't-empty-steps';
  view.hoverTaskCard = 't-empty-steps';
  view.hoverTaskInteractive = true;
  view.hoverTaskTimer = { cancel() { cancelled = true; } };
  const renderCx = {
    phase: () => 'render',
    notify() { throw new Error('cx.notify() forbidden in render'); },
    timer: { after() { return { cancel() {} }; } },
  };
  assert.doesNotThrow(() => view.clearHover(renderCx, true, true));
  assert.equal(cancelled, true);
  assert.equal(view.hoverTask, null);
  assert.equal(view.hoverTaskCard, null);

  // withTip puts positioning on outer anchor div, NOT on Popup.new(...)
  view.hoverTip = 'tip:sample';
  const tipTree = view.withTip('sample', makeEl('div', { id: 'sample-trigger' }), 'A long tooltip message', {
    raised: '#27272d', popover: '#222', surface: '#1b1b1f', canvas: '#111', border: '#333', foreground: '#fff',
  }).__node;
  const tipPopup = findById(tipTree, 'hover-tip-sample');
  const tipAnchor = findById(tipTree, 'hover-tip-anchor-sample');
  assert.ok(tipPopup && tipAnchor);
  assert.equal(tipPopup.props.absolute, undefined, 'withTip Popup must not chain .absolute()');
  assert.equal(tipPopup.props.left, undefined, 'withTip Popup must not chain .left()');
  assert.equal(tipAnchor.props.absolute, true);
});

test('pm-dash tooltipMaxWidth, wrapTooltipText, clampTooltipRect, and tooltipLayout bound width and clamp within viewport', async () => {
  const m = await import('./model.js');
  assert.equal(m.tooltipMaxWidth({ viewWidth: 1400 }), 420);
  assert.equal(m.tooltipMaxWidth({ viewWidth: 320 }), 288);
  const longTip = m.word('en', 'unclaimedTip') + ' ' + m.word('zh', 'unclaimedTip') + ' ' + 'x'.repeat(260);
  const lay = m.tooltipLayout(longTip, { viewWidth: 380, placement: 'below-right' });
  assert.ok(lay.width <= 348 && lay.maxWidth <= 348 && lay.maxWidth <= m.TOOLTIP_MAX_WIDTH);
  assert.equal(lay.lines.length, m.TOOLTIP_MAX_LINES);
  assert.equal(lay.truncated, true);
  assert.ok(lay.lines.at(-1).endsWith('…'));
  assert.equal(lay.anchor, 'top_right');

  const clamped = m.clampTooltipRect(
    { x: 350, y: 10, w: 20, h: 20 },
    { w: 240, h: 60 },
    { x: 0, y: 0, w: 380, h: 500 },
    { placement: 'above-right' },
  );
  assert.equal(clamped.placement, 'below-right');
  assert.ok(clamped.x >= m.TOOLTIP_MARGIN && clamped.x + clamped.w <= 380 - m.TOOLTIP_MARGIN);
  assert.ok(clamped.y >= 30);
});

test('pm-dash windowControlButtons maps Windows/Linux/macOS and overlay states', async () => {
  const m = await import('./model.js');
  // macOS or missing buttons: empty list
  assert.deepEqual(m.windowControlButtons(null), []);
  assert.deepEqual(m.windowControlButtons(undefined), []);
  assert.deepEqual(m.windowControlButtons({ platform: 'macos', buttons: false, maximized: false }), []);
  assert.deepEqual(m.windowControlButtons({ platform: 'windows', buttons: true, maximized: false }, { overlay: true }), []);

  // Windows unmaximized
  const winNorm = m.windowControlButtons({ platform: 'windows', buttons: true, maximized: false });
  assert.equal(winNorm.length, 3);
  assert.deepEqual(winNorm.map(b => [b.id, b.command, b.icon, b.danger, b.labelKey]), [
    ['win-minimize', 'window.minimize', 'mods/tabs/win-min.svg', false, 'windowMinimize'],
    ['win-maximize', 'window.maximize', 'mods/tabs/win-max.svg', false, 'windowMaximize'],
    ['win-close', 'window.close', 'mods/tabs/win-close.svg', true, 'windowClose'],
  ]);

  // Windows maximized switches to win-restore.svg
  const winMax = m.windowControlButtons({ platform: 'windows', buttons: true, maximized: true });
  assert.equal(winMax[1].icon, 'mods/tabs/win-restore.svg');
  assert.equal(winMax[1].labelKey, 'windowRestore');

  // Linux fallback glyphs and pane close icon
  const linuxNorm = m.windowControlButtons({ platform: 'linux', buttons: true, maximized: false });
  assert.deepEqual(linuxNorm.map(b => [b.id, b.command, b.icon, b.glyph, b.iconSize]), [
    ['win-minimize', 'window.minimize', null, '−', 16],
    ['win-maximize', 'window.maximize', null, '□', 16],
    ['win-close', 'window.close', 'mods/pane/close.svg', '', 13],
  ]);
  const linuxMax = m.windowControlButtons({ platform: 'linux', buttons: true, maximized: true });
  assert.equal(linuxMax[1].labelKey, 'windowRestore');

  for (const lang of ['en', 'zh']) {
    for (const k of ['windowMinimize', 'windowMaximize', 'windowRestore', 'windowClose']) {
      assert.ok(m.word(lang, k) && m.word(lang, k) !== k);
    }
  }
});

test('pm-dash renders window controls on Windows/Linux headers (Board/Projects/Archived/Setup) and omits them on macOS and overlays', async () => {
  const m = await import('./model.js');
  const makeEl = (tag, init = {}) => {
    const node = { tag, id: null, children: [], handlers: {}, hoverStyle: null, ...init };
    const proxy = new Proxy(node, {
      get(target, prop) {
        if (prop === '__node') return target;
        if (prop === 'id') return v => { target.id = v; return proxy; };
        if (prop === 'child') return c => { if (c != null) target.children.push(c?.__node ?? c); return proxy; };
        if (prop === 'children') return arr => { for (const c of arr || []) if (c != null) target.children.push(c?.__node ?? c); return proxy; };
        if (prop === 'when') return (cond, fn) => (cond ? fn(proxy) : proxy);
        if (prop === 'on_click') return fn => { target.handlers.click = fn; return proxy; };
        if (prop === 'on_mouse_down') return (btn, fn) => { target.handlers[`mousedown:${btn}`] = fn; return proxy; };
        if (prop === 'hover') return fn => {
          const style = {};
          const sp = new Proxy(style, {
            get(st, p) { return v => { st[p] = v; return sp; }; },
          });
          fn(sp);
          target.hoverStyle = style;
          return proxy;
        };
        if (prop in target) return target[prop];
        return () => proxy;
      },
    });
    return proxy;
  };
  const findById = (n, id) => {
    if (!n || typeof n !== 'object') return null;
    if (n.id === id) return n;
    for (const c of n.children || []) {
      const f = findById(c, id);
      if (f) return f;
    }
    return null;
  };
  const collectSvgs = (n, out = []) => {
    if (!n || typeof n !== 'object') return out;
    if (n.tag === 'svg' && n.src) out.push(n.src);
    for (const c of n.children || []) collectSvgs(c, out);
    return out;
  };

  let curWin = { platform: 'windows', buttons: true, maximized: false };
  let curProps = {};
  const ran = [];
  const projectsSrc = readFileSync(new URL('./projects.js', import.meta.url), 'utf8')
    .replace(/^import\b[\s\S]*?;\s*$/gm, '')
    .replace(/^export\s+/gm, '')
    + '\nreturn { pageHeader, projectHeader, pageView, windowControlsBar, keepPress };';
  const pBindings = {
    ...m,
    div: () => makeEl('div'),
    h_flex: () => makeEl('h_flex'),
    v_flex: () => makeEl('v_flex'),
    svg: src => makeEl('svg', { src }),
    InputState: { new: () => ({ on() {}, value: () => '', set_value() {} }) },
    Input: { new: () => makeEl('input') },
    Scrollbar: { new: () => makeEl('scrollbar') },
    home: () => '/Users/me',
    appHome: () => '/app',
    exec: async () => ({ code: 0, stdout: '{}' }),
    execPython: async () => ({ code: 0, stdout: '{}' }),
    run: cmd => ran.push(cmd),
    props: () => curProps,
    closeOverlay: () => {},
    layout: () => ({ id: 'pm-stage', children: [] }),
    shared: () => ({}),
    setShared: () => {},
    spaces: () => [],
    pickFolder: async () => '',
    notify: () => {},
    appWindow: () => curWin,
  };
  const proj = new Function(...Object.keys(pBindings), projectsSrc)(...Object.values(pBindings));
  const theme = {
    canvas: '#111', surface: '#1b1b1f', raised: '#27272d', border: '#333', hover: '#2a2a32',
    foreground: '#fff', muted: '#aaa', dim: '#666', blocked: '#e55', accent: '#6cf',
  };
  const fakeView = {
    state: { lang: 'en' },
    allState: { pms: [], tasks: [], events: [] },
    lines: {},
    today: () => '2026-11-24',
    keys: { focus() {} },
    openNew() {},
  };

  // 1. Windows unmaximized: pageHeader (board/list), projectHeader, archived pageView all show controls
  const boardHdr = proj.pageHeader(fakeView, 'board', theme).__node;
  const ctrl = findById(boardHdr, 'pm-window-controls');
  assert.ok(ctrl, 'pageHeader renders pm-window-controls on Windows');
  const minBtn = findById(ctrl, 'win-minimize');
  const maxBtn = findById(ctrl, 'win-maximize');
  const closeBtn = findById(ctrl, 'win-close');
  assert.ok(minBtn && maxBtn && closeBtn);
  assert.deepEqual(collectSvgs(ctrl), ['mods/tabs/win-min.svg', 'mods/tabs/win-max.svg', 'mods/tabs/win-close.svg']);
  assert.equal(closeBtn.hoverStyle?.bg, '#e81123');
  assert.equal(closeBtn.hoverStyle?.text_color, '#ffffff');

  // Mouse down stops propagation (prevents window_drag); click invokes window.* commands
  let stopped = 0;
  const fakeCx = { stop_propagation() { stopped++; } };
  minBtn.handlers['mousedown:left']({}, fakeCx);
  minBtn.handlers.click({}, fakeCx);
  maxBtn.handlers.click({}, fakeCx);
  closeBtn.handlers.click({}, fakeCx);
  assert.equal(stopped, 4);
  assert.deepEqual(ran, ['window.minimize', 'window.maximize', 'window.close']);

  // 2. Windows maximized: icon switches to win-restore.svg on projectHeader & archived view
  curWin = { platform: 'windows', buttons: true, maximized: true };
  const projHdr = proj.projectHeader(fakeView, { name: 'pm-dudu', project: 'dudu', repo: '/work/dudu' }, theme).__node;
  assert.ok(collectSvgs(findById(projHdr, 'pm-window-controls')).includes('mods/tabs/win-restore.svg'));
  const archView = proj.pageView(fakeView, 'archived', theme).__node;
  assert.ok(findById(archView, 'pm-archived-header'));
  assert.ok(findById(archView, 'pm-window-controls'));

  // 3. Setup view in main.js renders setup-header with window controls on Windows
  const dash = modWithIO('./main.js', {
    ...pBindings,
    windowControlsBar: proj.windowControlsBar,
    keepPress: proj.keepPress,
    Popup: { new: () => makeEl('popup') },
    PathBuilder: { stroke: () => ({ move_to() {}, cubic_bezier_to() {}, build: () => ({}) }) },
    FlowLayer: class {},
    boardVisible: () => true,
    renderStepsCard: () => makeEl('div'),
    renderDepsCard: () => makeEl('div'),
    theme: () => theme,
    readTextFile: async () => '',
    watchFolder: () => new Promise(() => {}),
    terminals: () => [],
    agents: () => [],
    panes: () => [],
    openOverlay: () => {},
    desktopLayout: () => ({}),
  });
  dash.state = { lang: 'en', pms: [], tasks: [], events: [] };
  dash.setupStatus = 'missing';
  dash.keys = { focus() {} };
  const setupWin = dash.setupView(theme).__node;
  assert.ok(findById(setupWin, 'setup-header'));
  assert.ok(findById(setupWin, 'pm-window-controls'));

  // 4. macOS (buttons: false): zero window controls rendered anywhere
  curWin = { platform: 'macos', buttons: false, maximized: false };
  assert.equal(findById(proj.pageHeader(fakeView, 'board', theme).__node, 'pm-window-controls'), null);
  assert.equal(findById(proj.projectHeader(fakeView, { name: 'pm-dudu' }, theme).__node, 'pm-window-controls'), null);
  assert.equal(findById(proj.pageView(fakeView, 'archived', theme).__node, 'pm-archived-header'), null);
  assert.equal(findById(dash.setupView(theme).__node, 'setup-header'), null);

  // 5. Overlay mode on Windows: omitted
  curWin = { platform: 'windows', buttons: true, maximized: false };
  curProps = { overlay: 'ov-1' };
  assert.equal(findById(proj.pageHeader(fakeView, 'board', theme).__node, 'pm-window-controls'), null);
  assert.equal(findById(dash.setupView(theme).__node, 'setup-header'), null);
});

test('board token analytics helpers: formatting, scope, chart buckets, breakdown, persistence, Esc, and i18n', async () => {
  const { escapeTarget } = await import('./model.js');
  // 1. Formatting
  assert.equal(formatTokens(0), '0');
  assert.equal(formatTokens(842), '842');
  assert.equal(formatTokens(12400), '12.4K');
  assert.equal(formatTokens(520300000), '520.3M');
  assert.equal(formatTokens(6740000000), '6.74B');
  assert.equal(formatUsd(0), '$0.00');
  assert.equal(formatUsd(0.002), '<$0.01');
  assert.equal(formatUsd(1234.5), '$1,234.50');
  assert.equal(formatPct(0.9716, 2), '97.16%');
  assert.equal(formatPct(0.9716, 0), '97%');
  assert.equal(formatCompactInt(2105), '2,105');

  // 2. Persistence defaults collapsed (false) and survives missing/throwing localStorage
  const map = new Map();
  const fakeStorage = { getItem: k => (map.has(k) ? map.get(k) : null), setItem: (k, v) => map.set(k, String(v)) };
  assert.equal(readTokensExpanded(fakeStorage), false);
  writeTokensExpanded(fakeStorage, true);
  assert.equal(map.get(TOKENS_EXPANDED_KEY), '1');
  assert.equal(readTokensExpanded(fakeStorage), true);
  writeTokensExpanded(fakeStorage, false);
  assert.equal(readTokensExpanded(fakeStorage), false);
  assert.equal(readTokensExpanded({ getItem() { throw new Error('denied'); } }), false);
  writeTokensExpanded({ setItem() { throw new Error('quota'); } }, true);

  // 3. parseTokenAnalytics & selectTokenScope
  assert.equal(parseTokenAnalytics('not json'), null);
  assert.equal(parseTokenAnalytics(JSON.stringify({ version: 2, projects: {} })), null);
  const sample = {
    version: 1,
    scan_ms: 6,
    projects: {
      __all__: {
        ranges: {
          today: {
            range: 'today',
            bucket_mode: 'hour',
            kpi: {
              total_tokens: 3000000, input_tokens: 200000, output_tokens: 100000, cache_read_tokens: 2500000, cache_write_tokens: 200000,
              prompt_tokens: 2900000, requests: 20, errors: 1, tasks: 2, sessions: 3, cost_usd: 12.5, cache_savings_usd: 25.0,
              cache_hit_rate: 0.862, by_agent_hit_rate: { claude: 0.9, agy: 0.8 }, by_agent_requests: { claude: 12, agy: 8 },
            },
            buckets: [
              {
                key: '08:00', label: '08:00', total_tokens: 1000000, cost_usd: 4.0, requests: 8,
                by_agent_tokens: { claude: 600000, agy: 400000 },
                by_agent_cost: { claude: 3.0, agy: 1.0 },
                by_agent_requests: { claude: 5, agy: 3 },
                advisor_tokens: 150000, advisor_cost: 1.2,
              },
              {
                key: '09:00', label: '09:00', total_tokens: 2000000, cost_usd: 8.5, requests: 12,
                by_agent_tokens: { claude: 1400000, agy: 600000 },
                by_agent_cost: { claude: 6.5, agy: 2.0 },
                by_agent_requests: { claude: 7, agy: 5 },
                advisor_tokens: 0, advisor_cost: 0,
              },
            ],
            by_model: [
              { model: 'claude-opus-5-5', agent: 'claude', is_advisor: false, requests: 10, total_tokens: 1850000, input_tokens: 100000, output_tokens: 50000, cache_read_tokens: 1500000, cache_write_tokens: 200000, cache_write_available: true, cache_hit_rate: 0.83, cost_usd: 8.3 },
              { model: 'claude-fable-5-2', agent: 'claude', is_advisor: true, requests: 2, total_tokens: 150000, input_tokens: 50000, output_tokens: 10000, cache_read_tokens: 90000, cache_write_tokens: 0, cache_write_available: true, cache_hit_rate: 0.64, cost_usd: 1.2 },
              { model: 'gemini-4-neon-high', agent: 'agy', is_advisor: false, requests: 8, total_tokens: 1000000, input_tokens: 50000, output_tokens: 40000, cache_read_tokens: 910000, cache_write_tokens: 0, cache_write_available: false, cache_hit_rate: 0.95, cost_usd: 3.0 },
            ],
            by_task: [
              { id: 'dudu-1', number: 1, title: 'Task 1', project: 'dudu', pm: 'pm-dudu', role: 'worker', agents: ['claude', 'agy'], models: ['claude-opus-5-5'], requests: 15, total_tokens: 2200000, work_tokens: 1600000, review_tokens: 600000, cost_usd: 10.0, work_cost_usd: 7.5, review_cost_usd: 2.5, share: 0.733, by_agent: { claude: 1400000, agy: 800000 }, by_agent_cost: { claude: 7.5, agy: 2.5 }, by_agent_requests: { claude: 9, agy: 6 } },
              { id: 'pm:dudu', number: 0, title: 'dudu · PM', project: 'dudu', pm: 'pm-dudu', role: 'pm', agents: ['claude'], models: ['claude-opus-5-5'], requests: 5, total_tokens: 800000, work_tokens: 800000, review_tokens: 0, cost_usd: 2.5, work_cost_usd: 2.5, review_cost_usd: 0, share: 0.267, by_agent: { claude: 800000 }, by_agent_cost: { claude: 2.5 }, by_agent_requests: { claude: 5 } },
            ],
            by_agent: [
              { agent: 'claude', label: 'Claude Code', requests: 12, errors: 1, sessions: 2, tasks: 1, total_tokens: 2000000, input_tokens: 150000, output_tokens: 60000, cache_read_tokens: 1590000, cache_write_tokens: 200000, cache_write_available: true, cache_hit_rate: 0.82, cost_usd: 9.5, cache_savings_usd: 20.0 },
              { agent: 'agy', label: 'Antigravity (agy)', requests: 8, errors: 0, sessions: 1, tasks: 1, total_tokens: 1000000, input_tokens: 50000, output_tokens: 40000, cache_read_tokens: 910000, cache_write_tokens: 0, cache_write_available: false, cache_hit_rate: 0.95, cost_usd: 3.0, cache_savings_usd: 5.0 },
              { agent: 'codex', label: 'Codex CLI', requests: 0, errors: 0, sessions: 0, tasks: 0, total_tokens: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, cache_write_available: true, cache_hit_rate: 0, cost_usd: 0, cache_savings_usd: 0 },
              { agent: 'pi', label: 'pi Agent', requests: 0, errors: 0, sessions: 0, tasks: 0, total_tokens: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, cache_write_available: true, cache_hit_rate: 0, cost_usd: 0, cache_savings_usd: 0 },
            ],
          },
        },
      },
      dudu: { pm_name: 'pm-dudu', project: 'dudu', ranges: { today: { kpi: { total_tokens: 3000000, requests: 20, cost_usd: 12.5, cache_hit_rate: 0.862 }, buckets: [], by_model: [], by_task: [], by_agent: [] } } },
    },
  };
  assert.ok(parseTokenAnalytics(JSON.stringify(sample)));
  assert.equal(selectTokenScope(sample, '', []).key, '__all__');
  assert.equal(selectTokenScope(sample, 'pm-dudu', [{ name: 'pm-dudu', project: 'dudu' }]).key, 'dudu');
  assert.equal(selectTokenScope(sample, 'pm-missing', [{ name: 'pm-missing', project: 'missing' }]).ranges, null);

  // 4. filterTokenSlice & sparklineBars
  const allSlice = sample.projects.__all__.ranges.today;
  const fAll = filterTokenSlice(allSlice, { agent: 'all', metric: 'tokens', dim: 'task' });
  assert.equal(fAll.maxBucket, 2000000);
  assert.equal(fAll.peakBucket.key, '09:00');
  assert.deepEqual(fAll.buckets[0].segments.map(s => [s.key, s.value]), [['claude', 450000], ['fable', 150000], ['agy', 400000]]);
  assert.equal(fAll.rows[0].id, 'dudu-1');

  const fAgy = filterTokenSlice(allSlice, { agent: 'agy', metric: 'cost', dim: 'model' });
  assert.equal(fAgy.kpi.total_tokens, 1000000);
  assert.equal(fAgy.rows.length, 1);
  assert.equal(fAgy.rows[0].cache_write_available, false);

  // PM summary & breakdown preservation (both backwards-compatible fallback and explicit pm object)
  assert.equal(fAll.pm.total_tokens, 800000);
  assert.equal(fAll.pm.cost_usd, 2.5);
  const { selectBreakdownRows } = await import('./model.js');
  const sliceWithPm = {
    ...allSlice,
    pm: {
      total_tokens: 800000, input_tokens: 50000, output_tokens: 20000, cache_read_tokens: 700000, cache_write_tokens: 30000,
      requests: 5, sessions: 1, cost_usd: 2.5, share: 0.267, agents: ['claude'], models: ['claude-opus-5-5'],
      by_agent: { claude: { total_tokens: 800000, input_tokens: 50000, output_tokens: 20000, cache_read_tokens: 700000, cache_write_tokens: 30000, requests: 5, sessions: 1, cost_usd: 2.5, models: ['claude-opus-5-5'] } },
    },
    by_task: [
      ...Array.from({ length: 7 }, (_, i) => ({
        id: `dudu-big-${i}`, number: i + 1, title: `Big ${i}`, project: 'dudu', pm: 'pm-dudu', role: 'worker',
        agents: ['agy'], models: ['gemini-4-neon-high'], requests: 10, total_tokens: 5000000 - i * 100000,
        work_tokens: 5000000 - i * 100000, review_tokens: 0, cost_usd: 4.0, share: 0.12,
        by_agent: { agy: 5000000 - i * 100000 }, by_agent_cost: { agy: 4.0 }, by_agent_requests: { agy: 10 },
      })),
      {
        id: 'pm:dudu', number: 0, title: 'dudu · PM', project: 'dudu', pm: 'pm-dudu', role: 'pm',
        agents: ['claude'], models: ['claude-opus-5-5'], requests: 5, total_tokens: 800000,
        input_tokens: 50000, output_tokens: 20000, cache_read_tokens: 700000, cache_write_tokens: 30000,
        work_tokens: 800000, review_tokens: 0, cost_usd: 2.5, share: 0.05,
        by_agent: { claude: 800000 }, by_agent_cost: { claude: 2.5 }, by_agent_requests: { claude: 5 },
        by_agent_io: { claude: { input_tokens: 50000, output_tokens: 20000, cache_read_tokens: 700000, cache_write_tokens: 30000, models: ['claude-opus-5-5'] } },
      },
    ],
  };
  const fPmAll = filterTokenSlice(sliceWithPm, { agent: 'all', metric: 'tokens', dim: 'task' });
  const visibleRows = selectBreakdownRows(fPmAll.rows, 'task', 6);
  assert.equal(visibleRows.length, 6);
  assert.ok(visibleRows.some(r => r.id === 'pm:dudu'), 'PM row must stay visible even when > 6 larger tasks exist');
  const fPmClaude = filterTokenSlice(sliceWithPm, { agent: 'claude', metric: 'tokens', dim: 'task' });
  assert.equal(fPmClaude.pm.total_tokens, 800000);
  assert.equal(fPmClaude.rows.length, 1);
  assert.equal(fPmClaude.rows[0].input_tokens, 50000);
  const fPmAgy = filterTokenSlice(sliceWithPm, { agent: 'agy', metric: 'tokens', dim: 'task' });
  assert.equal(fPmAgy.pm.total_tokens, 0);

  const spark = sparklineBars(allSlice.buckets, 12);
  assert.equal(spark.length, 12);
  assert.equal(spark[11], 1);
  assert.equal(spark[10], 0.5);
  assert.equal(spark[0], 0);

  // 5. escapeTarget folds expanded tokens shelf before leaving board
  assert.deepEqual(escapeTarget(true, { view: 'board', project: 'pm-dudu' }, { tokens: true }), { tokens: true });
  assert.deepEqual(escapeTarget(true, { view: 'board', project: '' }, { tokens: true }), { tokens: true });
  assert.deepEqual(escapeTarget(true, { view: 'board', project: 'pm-dudu' }, { hoverCard: true, tokens: true }), { hoverCard: true });
  assert.deepEqual(escapeTarget(true, { view: 'list', project: '' }, { tokens: true }), { back: true });

  // 6. EN & ZH i18n keys
  for (const lang of ['en', 'zh']) {
    for (const k of ['tokUsage', 'tokAnalytics', 'tokRangeToday', 'tokRange7d', 'tokRange30d', 'tokRangeAll',
      'tokAgentAll', 'tokDimModel', 'tokDimTask', 'tokDimAgent', 'tokMetricTokens', 'tokMetricCost',
      'tokMetricRequests', 'tokKpiTotal', 'tokKpiReqs', 'tokKpiCost', 'tokKpiHit', 'tokCacheWriteUnavail', 'tokAdapterReady',
      'tokPmInline', 'tokPmCostSub', 'tokPmAgentSub', 'tokPmModelSub']) {
      assert.ok(word(lang, k, '1M', '$1', '10%'), `${lang}.${k} should exist`);
    }
  }

  // 7. fitBoard scale invariance (token shelf sits outside fixedHeight)
  const boardState = { lang: 'en', pms: [{ name: 'pm-dudu', project: 'dudu', status: 'working' }], tasks: [{ id: 't1', pm: 'pm-dudu', title: 'Task', status: 'in_progress', updated: '2026-11-27 12:00' }], events: [] };
  const g1 = fitBoard(boardState, 1280, 720, 160);
  const g2 = fitBoard(boardState, 1280, 720, 160);
  assert.equal(g1.scale, g2.scale);
});

test('board refreshTokens applies exponential backoff on failure so board renders never loop spawning Python', async () => {
  const makeEl = () => {
    const proxy = new Proxy({}, { get: (_t, prop) => (prop === '__node' ? {} : () => proxy) });
    return proxy;
  };
  let calls = 0;
  let nextResp = { code: 1, stderr: 'boom' };
  const scheduledTimers = [];
  const view = modWithIO('./main.js', {
    div: () => makeEl(), v_flex: () => makeEl(), h_flex: () => makeEl(), svg: () => makeEl(),
    PathBuilder: { stroke: () => ({ move_to: () => ({ cubic_bezier_to() {}, build: () => ({}) }) }) },
    Scrollbar: { new: () => makeEl() }, Popup: { new: () => makeEl() },
    theme: () => ({ canvas: '#111', background: '#111', surface: '#1b1b1f', raised: '#27272d',
      foreground: '#fff', muted: '#aaa', dim: '#666', border: '#333', accent: '#4da3ff', blocked: '#ff6b6b',
      ansi1: '#ff6b6b', ansi2: '#4cd964', ansi3: '#ffcc00', ansi4: '#4da3ff', ansi5: '#bf5af2', ansi6: '#5ac8fa' }),
    home: () => '/h', appHome: () => '/a',
    execPython: async () => { calls++; if (nextResp instanceof Error) throw nextResp; return nextResp; },
    exec: async () => ({ code: 0, stdout: '' }),
    readTextFile: async () => '', watchFolder: async () => {}, terminals: () => [], agents: () => [], panes: () => [],
    run: () => {}, props: () => ({}), closeOverlay: () => {}, openOverlay: () => {}, desktopLayout: () => ({}),
    setupState, fitBoard, withAlpha, solidText, isDarkTheme, cleanTaskLog, hoverCardPosition, newEvents,
    pmId, taskId, eventText, terminalFor, terminalTargetFor, focusPlan, pmColor, counts, projectCounts,
    wireFlows, reviewWorking, word, label, taskStatusText, isClosedTask, taskSteps, taskDependencies, taskNumber, formatTaskNumber, mergeStates, cachedRemoteStates, LEDGER_HOME_SH, remoteStateCommand,
    pmStatusText, scopeState, archiveThreads: () => [], disconnected, escapeTarget: () => null, DROPPED, endedTime,
    page: () => ({ view: 'board', project: 'pm-dudu' }), pageView: () => makeEl(),
    pageHeader: () => makeEl(), projectHeader: () => makeEl(), keepPress: (_v, el) => el,
    dialogView: () => makeEl(), initDialog: () => {}, restoreProject: () => {}, readLines: async () => ({}),
    archivePopup: () => ({}), NEW_DIALOG: {}, openProject: () => {}, showPage: () => {},
    FlowLayer: class {}, boardVisible: () => true, renderStepsCard, renderDepsCard,
    renderTokenPulsePill: () => makeEl(), renderTokenShelf: () => makeEl(),
    readTokensExpanded, writeTokensExpanded, parseTokenAnalytics,
  });
  const pending = [];
  const cx = {
    notify() {},
    spawn(task) { pending.push(task(cx)); },
    timer: {
      after(_ms, fn) { scheduledTimers.push(fn); return { cancel() {} }; },
      every() {},
    },
  };
  const drainAll = async () => {
    while (scheduledTimers.length || pending.length) {
      while (scheduledTimers.length) scheduledTimers.shift()(cx);
      while (pending.length) await pending.shift();
    }
  };
  view.state = { lang: 'en', project: 'pm-dudu', pms: [{ name: 'pm-dudu', project: 'dudu' }], tasks: [], events: [] };
  view.size = { width: 1200, height: 800 };
  view.tokensFetchedAt = 0; view.tokensLoading = false; view.tokensRetryAfter = 0; view.tokensFailedCount = 0; view.tokensScheduled = false;
  view.shown = {}; view.shownStatus = {}; view.shownLive = {}; view.statuses = {}; view.tags = {}; view.nudges = {};
  view.queue = []; view.endedOpen = new Set(); view.showDropped = new Set(); view.hoverEnded = null; view.hoverPm = null;
  view.flowLayer = { set_props() {} };
  globalThis.window = { paint_path: () => makeEl() };

  // Multiple board() renders before timer runs only schedule once, and failure sets tokensFetchedAt + backoff.
  view.board(cx);
  view.board(cx);
  assert.equal(view.tokensScheduled, true);
  await drainAll();
  assert.equal(view.tokensScheduled, false);
  assert.equal(calls, 1);
  assert.ok(view.tokensFetchedAt > 0);
  assert.equal(view.tokensFailedCount, 1);
  assert.ok(view.tokensRetryAfter > Date.now());

  // Re-rendering board() or calling non-forced refreshTokens() during backoff does NOT spawn Python again.
  view.board(cx);
  view.refreshTokens(cx);
  await drainAll();
  assert.equal(calls, 1);

  // Manual force refresh bypasses backoff; thrown error (e.g., NO_PYTHON) increments backoff safely.
  nextResp = new Error('no-python');
  view.refreshTokens(cx, { force: true });
  await drainAll();
  assert.equal(calls, 2);
  assert.equal(view.tokensFailedCount, 2);

  // Subsequent forced success resets backoff counters.
  nextResp = { code: 0, stdout: JSON.stringify({ version: 1, projects: { __all__: { ranges: {} } } }) };
  view.refreshTokens(cx, { force: true });
  await drainAll();
  assert.equal(calls, 3);
  assert.equal(view.tokensFailedCount, 0);
  assert.equal(view.tokensRetryAfter, 0);
  assert.equal(view.tokenData?.version, 1);
});

// ---- Persistent mod error log (error_log.js) ---------------------------------
import * as errorLog from './error_log.js';

test('error_log.js is identical across pm-dash, pm-nav and pm-project and wired into each main.js', () => {
  const here = dirname(new URL(import.meta.url).pathname);
  const source = readFileSync(join(here, 'error_log.js'), 'utf8');
  for (const mod of ['pm-nav', 'pm-project']) {
    assert.equal(readFileSync(join(here, '..', mod, 'error_log.js'), 'utf8'), source, mod);
  }
  for (const mod of ['pm-dash', 'pm-nav', 'pm-project']) {
    const main = readFileSync(join(here, '..', mod, 'main.js'), 'utf8');
    assert.match(main, /import \{ createErrorLogger \} from '\.\/error_log\.js';/, mod);
    assert.match(main, /this\.logModError\(/, mod);
  }
});

test('error_log.js formats local timestamps, normalizes errors, throttles duplicates, and rotates log file', async () => {
  const tmp = mkdtempSync(join(tmpdir(), 'dudu-mod-errlog-'));
  try {
    let clock = new Date(2026, 10, 28, 1, 30, 5, 42).getTime();
    assert.equal(errorLog.formatLocalTimestamp(clock), '2026-11-28 01:30:05.042');
    assert.equal(errorLog.normalizeErrorMessage(new Error('  line1\n\tline2  ')), 'line1 line2');
    assert.equal(errorLog.normalizeErrorMessage(''), '');
    assert.equal(errorLog.normalizeErrorMessage('x'.repeat(20), 10), 'xxxxxxxxx…');

    const realExec = async (cmd, args) => {
      const stdout = execFileSync(cmd, args, { encoding: 'utf8' });
      return { code: 0, stdout, stderr: '' };
    };
    const execPy = (run, args, opts) => run('python3', args, opts);
    const logger = errorLog.createErrorLogger({
      mod: 'pm-project',
      exec: realExec,
      execPy,
      getLedgerHome: () => tmp,
      now: () => clock,
      throttleMs: 60_000,
      maxLines: 5,
      maxBytes: 4096,
    });

    // First error is recorded; identical error within throttleMs is suppressed.
    assert.equal(logger.record('refresh', new Error('pm.py: 1\nboom')), true);
    clock += 10_000;
    assert.equal(logger.record('refresh', new Error('pm.py: 1 boom')), false);
    clock += 10_000;
    assert.equal(logger.record('refresh', 'pm.py: 1 boom'), false);

    // Different message on same source flushes the suppressed repeat count of the previous error
    // before recording the new error, and keeps the previous error's throttle window active.
    clock += 5_000;
    assert.equal(logger.record('refresh', 'timeout'), true);
    // Interleaved A within its original 60s window is still throttled (prevents A/B flapping spam).
    clock += 5_000;
    assert.equal(logger.record('refresh', 'pm.py: 1 boom'), false);

    // Same original message on a different source is recorded immediately.
    assert.equal(logger.record('readLog', 'pm.py: 1 boom'), true);

    // After throttle window passes, repeated identical error is logged again with its repeat count.
    clock += 65_000;
    assert.equal(logger.record('refresh', 'timeout'), true);
    clock += 5_000;
    assert.equal(logger.record('refresh', 'timeout'), false);
    clock += 65_000;
    assert.equal(logger.record('refresh', 'timeout'), true);

    await logger.flush();
    const logPath = join(tmp, 'cache', 'mod-errors.log');
    const lines = readFileSync(logPath, 'utf8').trim().split('\n');
    // maxLines is 5, so the 6 emitted lines keep the newest 5:
    // [flushed (repeated 2x) pm.py: 1 boom, timeout, readLog pm.py: 1 boom, flushed (repeated 1x) pm.py: 1 boom, timeout, (repeated 1x) timeout] -> tail 5
    assert.equal(lines.length, 5);
    assert.match(lines[0], /\[pm-project\] \[refresh\] timeout$/);
    assert.match(lines[1], /\[pm-project\] \[readLog\] pm\.py: 1 boom$/);
    assert.match(lines[2], /\[pm-project\] \[refresh\] \(repeated 1x\) pm\.py: 1 boom$/);
    assert.match(lines[3], /\[pm-project\] \[refresh\] timeout$/);
    assert.match(lines[4], /\[pm-project\] \[refresh\] \(repeated 1x\) timeout$/);

    // Explicit A/A/B interleaving check with large maxLines verifies the first flushed repeat count too.
    const tmp2 = mkdtempSync(join(tmpdir(), 'dudu-mod-errlog-ab-'));
    try {
      let c2 = new Date(2026, 10, 28, 2, 0, 0, 0).getTime();
      const logger2 = errorLog.createErrorLogger({
        mod: 'pm-nav', exec: realExec, execPy, getLedgerHome: () => tmp2,
        now: () => c2, throttleMs: 60_000, maxLines: 20, maxBytes: 4096,
      });
      assert.equal(logger2.record('refresh', 'errA'), true);
      c2 += 5_000;
      assert.equal(logger2.record('refresh', 'errA'), false);
      c2 += 5_000;
      assert.equal(logger2.record('refresh', 'errA'), false);
      c2 += 5_000;
      assert.equal(logger2.record('refresh', 'errB'), true);
      await logger2.flush();
      const abLines = readFileSync(join(tmp2, 'cache', 'mod-errors.log'), 'utf8').trim().split('\n');
      assert.equal(abLines.length, 3);
      assert.match(abLines[0], /\[pm-nav\] \[refresh\] errA$/);
      assert.match(abLines[1], /\[pm-nav\] \[refresh\] \(repeated 2x\) errA$/);
      assert.match(abLines[2], /\[pm-nav\] \[refresh\] errB$/);
    } finally {
      rmSync(tmp2, { recursive: true, force: true });
    }

    // Line rotation caps at maxLines (5) and leaves no temp files behind.
    for (let i = 0; i < 6; i++) {
      clock += 1000;
      logger.record('refresh', `err-${i}`);
    }
    await logger.flush();
    const rotated = readFileSync(logPath, 'utf8').trim().split('\n');
    assert.equal(rotated.length, 5);
    assert.match(rotated[0], /err-1$/);
    assert.match(rotated[4], /err-5$/);
    const cacheEntries = readdirSync(join(tmp, 'cache'));
    assert.equal(cacheEntries.filter(f => f.startsWith('.mod-errors-') && f !== '.mod-errors.lock').length, 0);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test('error_log.js swallows write failures and never throws or blocks callers', async () => {
  let attempts = 0;
  const logger = errorLog.createErrorLogger({
    mod: 'pm-dash',
    exec: async () => { attempts += 1; throw new Error('EACCES'); },
    execPy: (run, args, opts) => run('python3', args, opts),
    getLedgerHome: () => '/nonexistent/readonly',
    throttleMs: 0,
  });
  assert.equal(logger.record('refresh', new Error('disk offline')), true);
  assert.equal(logger.record('refreshTokens', 'bad json'), true);
  await assert.doesNotReject(() => logger.flush());
  assert.ok(attempts >= 1);
});

test('Plan B projectHeader replaces Conversation|Board capsule with single chat icon back to pm-project', async () => {
  const dash = await import('./model.js');
  const source = readFileSync(new URL('./projects.js', import.meta.url), 'utf8')
    .replace(/^import[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/^export\s+/gm, '');
  const rendered = new Map();
  const runs = [];
  const sharedWrites = [];
  const makeEl = (tag) => {
    const rec = { tag, id: '', svgs: [], texts: [], click: null };
    const p = new Proxy(rec, {
      get(target, prop) {
        if (prop === '__rec') return target;
        if (prop === 'id') return v => { target.id = v; rendered.set(v, target); return p; };
        if (prop === 'child') return c => { if (typeof c === 'string') target.texts.push(c); return p; };
        if (prop === 'children') return arr => { for (const c of arr || []) if (typeof c === 'string') target.texts.push(c); return p; };
        if (prop === 'when') return (cond, fn) => (cond ? fn(p) : p);
        if (prop === 'on_click') return fn => { target.click = fn; return p; };
        return () => p;
      },
    });
    return p;
  };
  const bindings = {
    ...dash,
    div: () => makeEl('div'), v_flex: () => makeEl('v_flex'), h_flex: () => makeEl('h_flex'),
    svg: path => { const el = makeEl('svg'); el.__rec.svgs.push(path); return el; },
    InputState: {}, Input: {}, Scrollbar: {},
    home: () => '/Users/alice', appHome: () => '/Users/alice/.config/herdr-app',
    exec: async () => ({ code: 0, stdout: '' }), execPython: async () => ({ code: 0, stdout: '' }),
    run: (cmd, args) => runs.push([cmd, args]), props: () => ({}), closeOverlay: () => {},
    layout: () => ({ id: 'pm-stage', active: 'pm-board', children: [{ id: 'work' }, { id: 'pm-board' }, { id: 'pm-project' }] }),
    shared: () => ({}), setShared: (k, v) => sharedWrites.push([k, v]), spaces: () => [],
    pickFolder: async () => null, notify: () => {}, appWindow: () => ({ platform: 'macos', buttons: false }),
  };
  const { projectHeader } = new Function(...Object.keys(bindings), `${source}\nreturn { projectHeader };`)(...Object.values(bindings));
  const t = { border: '#333', foreground: '#eee', muted: '#999', dim: '#666', raised: '#222', hover: '#2a2a2a' };
  const v = { state: { lang: 'zh' }, keys: { focus() {} } };
  projectHeader(v, { name: 'pm-dudu', project: 'dudu', repo: '/Users/alice/repos/dudu' }, t);
  assert.equal(rendered.has('project-view'), false, 'segmented Conversation|Board capsule is removed');
  assert.ok(rendered.get('project-view-chat'), 'single chat icon button renders in project board header');
  rendered.get('project-view-chat').click({}, { stop_propagation() {} });
  assert.deepEqual(sharedWrites.at(-1), ['pm-project', { pm: 'pm-dudu' }]);
  assert.deepEqual(runs.at(-1), ['layout.select', { stack: 'pm-stage', child: 'pm-project' }]);
});

test('pm-dash displays project display_name/space_name over folder basename and supports project rename dialog', async () => {
  const dash = await import('./model.js');
  const { projectName, validateProjectName, renameArgv, projectCards, layout, counts, selectTokenScope, ledgerOpen } = dash;

  const pmCustom = { name: 'pm-web', project: 'webapp-dir', display_name: '前端工作台', repo: '/Users/alice/webapp-dir' };
  const pmLegacy = { name: 'pm-api', project: 'api-dir', space_name: 'API Gateway', repo: '/Users/alice/api-dir' };
  const pmPlain = { name: 'pm-ops', project: 'ops', repo: '/Users/alice/ops' };
  assert.equal(projectName(pmCustom), '前端工作台');
  assert.equal(projectName(pmLegacy), 'API Gateway');
  assert.equal(projectName(pmPlain), 'ops');

  // Validation: empty, control chars, >80, duplicate across other projects, allow case-only on self.
  assert.equal(validateProjectName('   ', 'zh', { pms: [pmCustom, pmLegacy], currentPm: pmCustom }).ok, false);
  assert.equal(validateProjectName('bad\nname', 'en', { pms: [pmCustom, pmLegacy], currentPm: pmCustom }).ok, false);
  assert.equal(validateProjectName('a'.repeat(81), 'en', { pms: [pmCustom, pmLegacy], currentPm: pmCustom }).ok, false);
  assert.equal(validateProjectName('api gateway', 'en', { pms: [pmCustom, pmLegacy], currentPm: pmCustom }).ok, false);
  assert.deepEqual(validateProjectName('  前端工作台 v2  ', 'zh', { pms: [pmCustom, pmLegacy], currentPm: pmCustom }), { ok: true, name: '前端工作台 v2', error: '' });
  assert.deepEqual(validateProjectName('api gateway', 'en', { pms: [pmCustom, pmLegacy], currentPm: pmLegacy }), { ok: true, name: 'api gateway', error: '' });
  assert.deepEqual(renameArgv('/app/pm.py', pmCustom, '新名字'), ['/app/pm.py', 'project', 'rename', '/Users/alice/webapp-dir', '新名字']);
  assert.deepEqual(renameArgv('/app/pm.py', 'pm-web', '新名字'), ['/app/pm.py', 'project', 'rename', 'pm-web', '新名字']);

  const state = {
    pms: [pmCustom, { ...pmLegacy, archived: '2026-11-20' }],
    tasks: [{ id: 't1', pm: 'pm-web', project: 'webapp-dir', title: 'Fix', status: 'blocked', updated: '2026-11-28 04:00' }],
    events: [],
  };
  const cards = projectCards(state);
  assert.equal(cards.active[0].name, '前端工作台');
  assert.equal(cards.archived[0].name, 'API Gateway');
  const laid = layout(state, 1100, 700, 1);
  assert.equal(laid.rows.find(r => r.type === 'pm' && r.name === 'pm-web')?.title, '前端工作台');
  assert.match(counts(state).conclusion, /前端工作台/);
  const tokData = { projects: { __all__: { ranges: {} }, 'pm-web': { project_name: 'webapp-dir', ranges: {} } } };
  assert.equal(selectTokenScope(tokData, 'pm-web', state.pms).label, '前端工作台');
  assert.equal(ledgerOpen(state, '全新显示名', '/Users/alice/webapp-dir').length, 1);

  // projects.js UI: projectHeader shows display_name + rename button; renameDialog validates & calls pm.py project rename.
  const source = readFileSync(new URL('./projects.js', import.meta.url), 'utf8')
    .replace(/^import[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/^export\s+/gm, '');
  const rendered = new Map();
  const execCalls = [];
  let closedOverlay = false;
  const makeEl = (tag) => {
    const rec = { tag, id: '', texts: [], click: null };
    const p = new Proxy(rec, {
      get(target, prop) {
        if (prop === '__rec') return target;
        if (prop === 'id') return v => { target.id = v; rendered.set(v, target); return p; };
        if (prop === 'child') return c => { if (typeof c === 'string') target.texts.push(c); return p; };
        if (prop === 'children') return arr => { for (const c of arr || []) if (typeof c === 'string') target.texts.push(c); return p; };
        if (prop === 'when') return (cond, fn) => (cond ? fn(p) : p);
        if (prop === 'on_click') return fn => { target.click = fn; return p; };
        return () => p;
      },
    });
    return p;
  };
  let inputVal = '';
  const bindings = {
    ...dash,
    div: () => makeEl('div'), v_flex: () => makeEl('v_flex'), h_flex: () => makeEl('h_flex'),
    svg: () => makeEl('svg'),
    InputState: { new: () => ({ set_value: v => { inputVal = v; }, value: () => inputVal, focus() {}, on() {}, set_placeholder() {} }) },
    Input: { new: () => makeEl('Input') },
    Scrollbar: {},
    home: () => '/Users/alice', appHome: () => '/app',
    exec: async () => ({ code: 0, stdout: '' }),
    execPython: async (_exec, args) => {
      execCalls.push(args);
      if (args[1] === 'state') return { code: 0, stdout: JSON.stringify({ lang: 'zh', pms: [pmCustom, pmLegacy], tasks: [], events: [] }) };
      return { code: 0, stdout: JSON.stringify({ ok: true }) };
    },
    run: () => {}, props: () => ({ dialog: 'rename', pm: 'pm-web' }),
    closeOverlay: () => { closedOverlay = true; },
    layout: () => ({ id: 'pm-stage', active: 'pm-board', children: [{ id: 'pm-board' }, { id: 'pm-project' }] }),
    shared: () => ({}), setShared: () => {}, spaces: () => [],
    pickFolder: async () => null, notify: () => {}, appWindow: () => ({ platform: 'macos', buttons: false }),
  };
  const mod = new Function(...Object.keys(bindings), `${source}\nreturn { projectHeader, initDialog, dialogView, submitRename, renameDialogSpec };`)(...Object.values(bindings));
  const t = { border: '#333', foreground: '#eee', muted: '#999', dim: '#666', raised: '#222', hover: '#2a2a2a', chrome: '#111', surface: '#1a1a1a', accent: '#58a6ff', blocked: '#f85149' };
  const openedOverlays = [];
  const v = {
    state: { lang: 'zh', pms: [pmCustom, pmLegacy], tasks: [] },
    local: { lang: 'zh', pms: [pmCustom, pmLegacy], tasks: [] },
    keys: { focus() {} },
    openRename: pm => openedOverlays.push(pm),
  };
  mod.projectHeader(v, pmCustom, t);
  assert.ok(rendered.get('project-rename'), 'local project board header renders rename icon button');
  rendered.get('project-rename').click({}, { stop_propagation() {} });
  assert.deepEqual(openedOverlays, ['pm-web']);
  assert.deepEqual(mod.renameDialogSpec('pm-web'), { mod: 'pm-dash', props: { dialog: 'rename', pm: 'pm-web' }, kind: 'dialog', width: 420, height: 224 });

  const { cx, drain } = asyncContext();
  cx.subscribe = () => {};
  cx.focus_handle = () => ({ focus() {} });
  mod.initDialog(v, cx);
  await drain();
  mod.dialogView(v, t, cx);
  assert.equal(inputVal, '前端工作台');
  inputVal = '前端总台';
  v.form.name = '前端总台';
  mod.submitRename(v, cx);
  await drain();
  assert.deepEqual(execCalls.at(-1), ['/app/mods/pm-dash/skill/scripts/pm.py', 'project', 'rename', '/Users/alice/webapp-dir', '前端总台']);
  assert.equal(closedOverlay, true);
});

test('Slice 2 projects.js New project dialog: Machine preselect, 0..N equal folders, agy, remote picker/mkdir & remote archive/restore', async () => {
  const dash = await import('./model.js');
  const source = readFileSync(new URL('./projects.js', import.meta.url), 'utf8')
    .replace(/^import[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/^export\s+/gm, '');

  const makeHarness = (overrides = {}) => {
    const rendered = new Map();
    const execCalls = [];
    const pyCalls = [];
    const runCalls = [];
    const openedProjects = [];
    const openedArchives = [];
    const states = {
      name: '',
      remotePath: '',
      spaces: overrides.spaces || [],
      terminals: overrides.terminals || [],
      machines: overrides.machines ?? { machines: [{ name: 'dev', state: 'connected' }, { name: 'mbp', state: 'unreachable' }] },
      probeDirs: overrides.probeDirs || { '/home/dev/repos/api': { exists: true, git: true, branch: 'main' } },
      listDirs: overrides.listDirs || 'BASE\t/home/dev/repos\t/home/dev\nENTRY\tapi\t/home/dev/repos/api\t1\tmain\nENTRY\tdocs\t/home/dev/repos/docs\t0\t\n',
    };
    const makeEl = (tag) => {
      const rec = { tag, id: '', texts: [], click: null, hover: null };
      const p = new Proxy(rec, {
        get(target, prop) {
          if (prop === '__rec') return target;
          if (prop === 'id') return v => { target.id = v; rendered.set(v, target); return p; };
          if (prop === 'child') return c => { if (typeof c === 'string') target.texts.push(c); return p; };
          if (prop === 'children') return arr => { for (const c of arr || []) if (typeof c === 'string') target.texts.push(c); return p; };
          if (prop === 'when') return (cond, fn) => (cond ? fn(p) : p);
          if (prop === 'on_click') return fn => { target.click = fn; return p; };
          if (prop === 'on_hover') return fn => { target.hover = fn; return p; };
          return () => p;
        },
      });
      return p;
    };
    let inputIndex = 0;
    let closedOverlay = false;
    const bindings = {
      ...dash,
      div: () => makeEl('div'), v_flex: () => makeEl('v_flex'), h_flex: () => makeEl('h_flex'),
      svg: () => makeEl('svg'),
      InputState: {
        new: () => {
          const idx = inputIndex++;
          const key = idx === 0 ? 'name' : 'remotePath';
          const handlers = {};
          return {
            set_value: v => { states[key] = v; },
            value: () => states[key],
            focus() {},
            set_placeholder() {},
            on: (ev, fn) => { handlers[ev] = fn; },
            trigger: (ev, cx) => handlers[ev]?.({}, cx),
          };
        },
      },
      Input: { new: () => makeEl('Input') },
      Scrollbar: { new: () => makeEl('Scrollbar') },
      home: () => '/Users/alice', appHome: () => '/app',
      exec: async (cmd, args, opts) => {
        execCalls.push({ cmd, args, opts });
        if (cmd === 'hc' && args[0] === 'machine' && args[1] === 'ls') {
          return { code: 0, stdout: JSON.stringify(states.machines), stderr: '' };
        }
        if (cmd === 'hc' && args[0] === 'label') {
          const spArg = args.find(a => String(a).startsWith('herdr.space='));
          const tbArg = args.find(a => String(a).startsWith('herdr.tab='));
          const spId = spArg ? String(spArg).slice('herdr.space='.length) : 'sp-remote-1';
          const tbId = tbArg ? String(tbArg).slice('herdr.tab='.length) : 'tb-1';
          const qSp = `dev/${spId}`;
          const prev = states.spaces.find(s => s.id === qSp);
          if (prev) {
            prev.tabs = [...(prev.tabs || []), { id: `dev/${tbId}`, terminals: [{ terminal: args[1] }] }];
          } else {
            states.spaces = [{ id: qSp, name: 'NewDev', tabs: [{ id: `dev/${tbId}`, terminals: [{ terminal: args[1] }] }] }];
          }
          return { code: 0, stdout: '{}', stderr: '' };
        }
        if (cmd === 'sh' && args[0] === '-c') {
          const scriptStr = String(args[1] || '');
          if (scriptStr.includes('mkdir -p')) {
            const p = args[3];
            states.probeDirs[p] = { exists: true, git: false, branch: '' };
            return { code: 0, stdout: p + '\n', stderr: '' };
          }
          if (scriptStr.includes('ENTRY\\t')) {
            return { code: 0, stdout: states.listDirs, stderr: '' };
          }
          if (scriptStr.includes('LEDGER\\t')) {
            const paths = args.slice(3);
            const lines = ['HOME\t/home/dev', 'PM\t/home/dev/.dudu/pm.py', 'LEDGER\t/home/dev/.dudu'];
            for (const p of paths) {
              const info = states.probeDirs[p];
              lines.push(info?.exists
                ? `DIR\t1\t${p}\t${p}\t${info.git ? 1 : 0}\t${info.branch || ''}`
                : `DIR\t0\t${p}\t${p}\t0\t`);
            }
            return { code: 0, stdout: lines.join('\n') + '\n', stderr: '' };
          }
          if (scriptStr.includes('env -u HC_TERMINAL_ID')) {
            const pmArgs = args.slice(3);
            if (pmArgs[0] === 'state') return { code: 0, stdout: JSON.stringify({ lang: 'en', pms: [{ name: 'pm-api', slug: 'api', space_id: 'sp1', terminal: 't1', display_name: 'API' }], tasks: [{ id: 't1', pm: 'pm-api', title: 'Task 1', status: 'in_progress' }], events: [] }), stderr: '' };
            if (pmArgs[0] === 'start') return { code: 0, stdout: JSON.stringify({ ok: true, slug: 'remote-plan', name: 'pm-remote-plan', display_name: 'Remote Plan', terminal: 't77', cwd: '/home/dev/repos/api' }), stderr: '' };
            if (pmArgs[0] === 'project' && pmArgs[1] === 'set-space') return { code: 0, stdout: JSON.stringify({ ok: true }), stderr: '' };
            if (pmArgs[0] === 'archive') return { code: 0, stdout: JSON.stringify({ ok: true, slug: 'api', space_id: 'sp1', terminal: 't1' }), stderr: '' };
            if (pmArgs[0] === 'restore') return { code: 0, stdout: JSON.stringify({ ok: true, slug: 'api', name: 'pm-api', display_name: 'API', terminal: 't88', space_id: 'sp1' }), stderr: '' };
          }
        }
        return { code: 0, stdout: '', stderr: '' };
      },
      execPython: async (_exec, args) => {
        pyCalls.push(args);
        if (args[1] === 'state') return { code: 0, stdout: JSON.stringify({ lang: 'en', home: '/Users/alice/.dudu', pms: [], tasks: [], events: [] }), stderr: '' };
        if (args[1] === 'start') return { code: 0, stdout: JSON.stringify({ ok: true, slug: 'zero-plan', name: 'pm-zero-plan' }), stderr: '' };
        return { code: 0, stdout: JSON.stringify({ ok: true }), stderr: '' };
      },
      run: (name, args) => runCalls.push([name, args]),
      props: () => overrides.props || { dialog: 'new' },
      closeOverlay: () => { closedOverlay = true; },
      layout: () => ({ id: 'pm-stage', active: 'pm-board', children: [{ id: 'pm-board' }, { id: 'pm-project' }] }),
      shared: () => ({}), setShared: (k, val) => { if (k === 'pm-project') openedProjects.push(val); },
      spaces: () => states.spaces,
      panes: () => [],
      terminals: () => states.terminals,
      knownAgents: async () => [{ key: 'claude', installed: true, run: ['claude'] }, { key: 'agy', installed: true, run: ['agy'] }, { key: 'codex', installed: true, run: ['codex'] }, { key: 'pi', installed: false, run: ['pi'] }],
      pickFolder: async () => null,
      readTextFile: async () => null,
      notify: () => {},
      appWindow: () => ({ platform: 'macos', buttons: false }),
    };
    const mod = new Function(...Object.keys(bindings), `${source}\nreturn { initDialog, dialogView, pageView, restoreProject, NEW_DIALOG, archivePopup };`)(...Object.values(bindings));
    return { mod, rendered, execCalls, pyCalls, runCalls, openedProjects, openedArchives, states, getClosed: () => closedOverlay };
  };

  const t = { border: '#333', input: '#444', popover: '#181818', background: '#111', foreground: '#eee', muted: '#999', dim: '#666', raised: '#222', hover: '#2a2a2a', chrome: '#111', surface: '#1a1a1a', canvas: '#141414', accent: '#58a6ff', blocked: '#f85149', ansi2: '#3fb950', ansi3: '#d29922', solid: '#eee', solid_foreground: '#111' };

  // 1. No remote machines configured: Machine row hidden, Where row completely removed, 0-folder submit works with agy
  const h1 = makeHarness({ machines: { machines: [] } });
  const { cx: cx1, drain: drain1 } = asyncContext();
  cx1.focus_handle = () => ({ focus() {} });
  cx1.stop_propagation = () => {};
  const v1 = {};
  h1.mod.initDialog(v1, cx1);
  await drain1();
  h1.mod.dialogView(v1, t, cx1);
  assert.equal(h1.rendered.get('new-machine'), undefined, 'Machine row hidden when no remote machines exist');
  assert.equal(h1.rendered.get('new-space'), undefined, 'Where row is completely removed');
  assert.ok(h1.rendered.get('new-kind-agy'), 'Manager includes agy');
  v1.form.name = 'Zero Plan';
  v1.form.kind = 'agy';
  h1.mod.dialogView(v1, t, cx1);
  h1.rendered.get('new-submit').click({}, cx1);
  await drain1();
  assert.deepEqual(h1.pyCalls.at(-1), ['/app/mods/pm-dash/skill/scripts/pm.py', 'start', '--name', 'Zero Plan', '--kind', 'agy', '--json']);
  assert.equal(h1.getClosed(), true);

  // 2. Active remote space preselects `dev`, supports Not found -> Create folder, Browse picker drill-down + Add, and 2-phase submit without space.select
  const h2 = makeHarness({ spaces: [{ id: 'dev/sp0', active: true, machine: 'dev', tabs: [] }] });
  const { cx: cx2, drain: drain2 } = asyncContext();
  cx2.focus_handle = () => ({ focus() {} });
  cx2.stop_propagation = () => {};
  const v2 = {};
  h2.mod.initDialog(v2, cx2);
  await drain2();
  assert.equal(v2.form.machine, 'dev', 'active space on dev auto-selects dev machine');
  h2.mod.dialogView(v2, t, cx2);
  assert.ok(h2.rendered.get('new-machine-dev'), 'Machine selector renders dev');

  // Missing remote path -> Not found -> Create folder
  h2.states.remotePath = '/home/dev/repos/new-dir';
  v2.remotePath = '/home/dev/repos/new-dir';
  h2.mod.dialogView(v2, t, cx2);
  h2.rendered.get('remote-add-btn').click({}, cx2);
  await drain2();
  h2.mod.dialogView(v2, t, cx2);
  assert.ok(h2.rendered.get('remote-not-found'), 'Missing remote path shows Not found banner');
  assert.ok(h2.rendered.get('remote-create-folder'), 'Shows Create folder button');
  h2.rendered.get('remote-create-folder').click({}, cx2);
  await drain2();
  assert.equal(v2.form.folders.length, 1);
  assert.equal(v2.form.folders[0].path, '/home/dev/repos/new-dir');

  // Remote subfolder picker -> Add equal second folder (no primary badge)
  h2.mod.dialogView(v2, t, cx2);
  h2.rendered.get('remote-browse-btn').click({}, cx2);
  await drain2();
  h2.mod.dialogView(v2, t, cx2);
  assert.ok(h2.rendered.get('remote-picker'), 'Remote subfolder picker opens');
  h2.rendered.get('remote-dir-add-0').click({}, cx2);
  assert.equal(v2.form.folders.length, 2);
  assert.deepEqual(v2.form.folders.map(f => f.alias), ['new-dir', 'api']);

  // Submit remote project: Stage 1 --no-app-space --json, Stage 2 hc label + set-space, NO space.select
  h2.mod.dialogView(v2, t, cx2);
  h2.rendered.get('new-submit').click({}, cx2);
  await drain2();
  assert.ok(h2.execCalls.some(c => c.cmd === 'hc' && c.args[0] === 'label' && c.args[1] === 'dev/t77'));
  assert.ok(h2.runCalls.some(([name]) => name === 'space.rename'));
  assert.ok(h2.runCalls.some(([name]) => name === 'tab.rename'));
  assert.equal(h2.runCalls.some(([name]) => name === 'space.select'), false, 'D4: must never call space.select on create');
  assert.deepEqual(h2.openedProjects[0], { pm: 'dev/pm-remote-plan', machine: 'dev' });

  // 3. Remote cards & archived cards allow Archive & Restore; confirmArchive closes idle remote Space via D1
  const h3 = makeHarness({
    props: { dialog: 'archive', pm: 'dev/pm-api', machine: 'dev' },
    spaces: [{ id: 'dev/sp1', name: 'API', tabs: [{ id: 'dev/tb1', panes: 1, terminals: [{ terminal: 'dev/t1' }] }] }],
  });
  const listView = {
    state: { lang: 'en' },
    allState: { pms: [{ name: 'dev/pm-api', sourceName: 'pm-api', slug: 'api', display_name: 'API', machine: 'dev', repo: '/home/dev/repos/api', space_id: 'sp1', status: 'idle' }], tasks: [], events: [] },
    lines: {}, hoverCard: 'dev/pm-api', restoring: '', today: () => '2026-11-28',
    keys: { focus() {} }, openNew() {}, openRename() {}, openArchive: (k, m) => h3.openedArchives.push([k, m]), restore() {},
  };
  const { cx: cx3, drain: drain3 } = asyncContext();
  cx3.focus_handle = () => ({ focus() {} });
  cx3.stop_propagation = () => {};
  h3.mod.pageView(listView, 'list', t);
  assert.ok(h3.rendered.get('archive-dev/pm-api'), 'hovered remote active card renders archive icon button');
  h3.rendered.get('archive-dev/pm-api').click({}, cx3);
  assert.deepEqual(h3.openedArchives, [['dev/pm-api', 'dev']]);

  const v3 = {};
  h3.mod.initDialog(v3, cx3);
  await drain3();
  h3.mod.dialogView(v3, t, cx3);
  h3.rendered.get('archive-confirm').click({}, cx3);
  await drain3();
  assert.ok(h3.runCalls.some(([name, arg]) => name === 'space.close' && arg?.id === 'dev/sp1' && arg?.confirmed === true));

  // Fail-closed: remote space with an extra unseen terminal (empty terminals()) keeps Space without calling space.close
  const h4 = makeHarness({
    props: { dialog: 'archive', pm: 'dev/pm-api', machine: 'dev' },
    spaces: [{ id: 'dev/sp2', name: 'API2', tabs: [{ id: 'dev/tb1', panes: 1, terminals: [{ terminal: 'dev/t1' }] }, { id: 'dev/tb2', panes: 1, terminals: [{ terminal: 'dev/t_unseen' }] }] }],
    terminals: [],
  });
  const { cx: cx4, drain: drain4 } = asyncContext();
  cx4.focus_handle = () => ({ focus() {} });
  cx4.stop_propagation = () => {};
  const v4 = {};
  h4.mod.initDialog(v4, cx4);
  await drain4();
  h4.mod.dialogView(v4, t, cx4);
  h4.rendered.get('archive-confirm').click({}, cx4);
  await drain4();
  assert.equal(h4.runCalls.some(([name]) => name === 'space.close'), false, 'fail-closed: unseen non-PM terminal must keep Space');

  // Remote archived card renders Restore button and triggers Stage 1 + Stage 2 restore
  listView.allState.pms[0].archived = '2026-11-28';
  listView.hoverCard = null;
  h3.rendered.clear();
  listView.hoverCard = 'dev/pm-api';
  h3.mod.pageView(listView, 'archived', t);
  assert.ok(h3.rendered.get('restore-dev/pm-api'), 'remote archived card renders Restore button');
  await h3.mod.restoreProject({ state: { lang: 'en' }, restoring: '', refresh() {}, refreshRemote() {} }, { key: 'dev/pm-api', sourceName: 'pm-api', slug: 'api', name: 'API', machine: 'dev', spaceId: 'sp1' }, cx3);
  await drain3();
  assert.ok(h3.execCalls.some(c => c.cmd === 'hc' && c.args[0] === 'label' && c.args[1] === 'dev/t88'));
});

test('WRITE_REMOTE_CACHE --from-file writes 200KB+ remote state atomically, skips unchanged, and removes staging file', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pm-remote-cache-file-'));
  try {
    const cacheDir = join(dir, 'cache with spaces');
    const path = join(cacheDir, 'remote-states.json');
    const bigPad = 'x'.repeat(210_000);
    const remote = { pms: [{ name: 'pm-dudu', project: 'dudu', helpers: bigPad }], tasks: [], events: [] };
    const states = { '198.51.100.10': remote };
    const writeFromFile = (value, at, name = '.remote-states-in.tmp') => {
      mkdirSync(cacheDir, { recursive: true });
      const staged = join(cacheDir, name);
      writeFileSync(staged, JSON.stringify(value), 'utf8');
      execFileSync('python3', ['-c', WRITE_REMOTE_CACHE, path, '--from-file', staged, String(at)]);
    };
    writeFromFile(states, 1_000_000);
    const original = readFileSync(path, 'utf8'), modified = statSync(path).mtimeMs;
    assert.ok(original.length > 210_000);
    assert.deepEqual(cachedRemoteStates(original, 1_000_000), states);
    assert.deepEqual(readdirSync(cacheDir), ['remote-states.json'], 'staging temp file is removed after commit');

    // Unchanged remote state skips rewriting target and still cleans up staging file.
    writeFromFile({ '198.51.100.10': { events: [], tasks: [], pms: remote.pms } }, 2_000_000, '.remote-states-in-2.tmp');
    assert.equal(readFileSync(path, 'utf8'), original);
    assert.equal(statSync(path).mtimeMs, modified);
    assert.deepEqual(readdirSync(cacheDir), ['remote-states.json']);

    // Corrupt staging JSON still cleans up staging file and fails cleanly without touching target.
    const badStaged = join(cacheDir, '.remote-states-bad.tmp');
    writeFileSync(badStaged, '{broken', 'utf8');
    assert.throws(() => execFileSync('python3', ['-c', WRITE_REMOTE_CACHE, path, '--from-file', badStaged, '2000001'], { stdio: 'pipe' }));
    assert.deepEqual(readdirSync(cacheDir), ['remote-states.json']);
    assert.equal(readFileSync(path, 'utf8'), original);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('pm-nav stages 200KB+ remote cache via writeTextFile to bypass Windows 32KB argv limit and publishes remoteCacheSig', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'pm-nav-win-remote-'));
  try {
    const winHome = join(dir, 'win-ledger');
    const calls = [], sharedWrites = [], logged = [];
    const sharedStore = new Map();
    const bigRemoteState = {
      pms: [
        { name: 'pm-dudu', project: 'dudu', pane: 'hc:t1k6', status: 'idle', helpers: 'h'.repeat(200_000) },
        { name: 'pm-nova', project: 'Nova', pane: 'hc:t2', status: 'idle' },
        { name: 'pm-issues', project: 'issues', pane: 'hc:t3', status: 'idle' },
      ],
      tasks: [],
      events: [],
    };
    let allowCacheWrite = true;
    const navView = modWithIO('../pm-nav/main.js', {
      home: () => dir, appHome: () => dir,
      ENSURE_DIR_PY, remoteCacheSig, WRITE_REMOTE_CACHE, remoteStateCommand: nav.remoteStateCommand,
      shared: k => sharedStore.get(k),
      setShared: (k, v) => { sharedStore.set(k, v); sharedWrites.push([k, v]); },
      writeTextFile: async (path, text) => {
        if (!allowCacheWrite) throw new Error('disk full');
        // Mirror Herdr's writeTextFile: fails if parent directory does not exist yet.
        writeFileSync(path, text, 'utf8');
        return null;
      },
      exec: async (program, args, options) => {
        const cmdLineLen = [program, ...args].join(' ').length;
        // Enforce Windows CreateProcessW 32,767-char command-line limit.
        if (cmdLineLen > 32_767) {
          throw new Error(`WinError 206: command line too long (${cmdLineLen} chars)`);
        }
        calls.push({ program, args, options });
        if (program === 'hc' && args[0] === 'machine') {
          return { code: 0, stdout: JSON.stringify({ machines: [{ name: '198.51.100.10', state: 'connected' }] }) };
        }
        if (program === 'hc' && args[0] === 'exec') {
          return { code: 0, stdout: JSON.stringify(bigRemoteState) };
        }
        if (program === 'python3' && args[0] === '-c') {
          execFileSync('python3', args, { stdio: 'pipe' });
          return { code: 0, stdout: '', stderr: '' };
        }
        if (program === 'python3' && args[0].endsWith('setup.py')) {
          return { code: 0, stdout: JSON.stringify(setupSummary(['claude'], ['claude'])) };
        }
        return { code: 0, stdout: '{}' };
      },
    });
    navView.remoteStates = {};
    navView.localState = { pms: [], tasks: [], events: [] };
    navView.publish = () => {};
    navView.logModError = (src, err) => logged.push([src, String(err)]);
    navView.ledgerHome = winHome;
    const { cx, drain } = asyncContext();

    // Case 1: Set up not available here (Windows host: the skill folder is unreadable) — another
    // machine's projects need no local Set up, so remote-states.json is written right away.
    navView.setupAvailable = false;
    navView.refreshRemote(cx);
    await drain();
    assert.equal(Object.keys(navView.remoteStates).length, 1);
    assert.equal(sharedWrites.length, 1);

    navView.checkSetup(cx);
    await drain();
    assert.equal(navView.setupAvailable, true);
    const cachePath = join(winHome, 'cache', 'remote-states.json');
    const written = JSON.parse(readFileSync(cachePath, 'utf8'));
    assert.deepEqual(written.states['198.51.100.10'].pms.map(p => p.name), ['pm-dudu', 'pm-nova', 'pm-issues']);
    assert.deepEqual(readdirSync(join(winHome, 'cache')), ['remote-states.json']);
    assert.deepEqual(sharedWrites, [['pm-remote-cache', '198.51.100.10:pm-dudu:0,pm-issues:0,pm-nova:0']]);
    assert.ok(calls.some(c => c.program === 'python3' && c.args[3] === '--from-file'), 'uses --from-file instead of argv JSON');

    // Unchanged project set does not re-write shared('pm-remote-cache') on subsequent polls.
    navView.refreshRemote(cx);
    await drain();
    assert.equal(sharedWrites.length, 1);

    // Case 2: writeRemoteCache errors are logged via logModError instead of silently swallowed.
    allowCacheWrite = false;
    navView.refreshRemote(cx);
    await drain();
    assert.equal(logged.length, 1);
    assert.equal(logged[0][0], 'writeRemoteCache');
    assert.match(logged[0][1], /disk full/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('pm-dash warms remote cache and refreshes with 6s/10s timeouts when becoming visible on stage', async () => {
  const execCalls = [];
  let visible = false, focused = false;
  const scheduled = [];
  const remoteState = { pms: [{ name: 'pm-dudu', project: 'dudu' }], tasks: [], events: [] };
  const board = modWithIO('./main.js', {
    home: () => '/h', appHome: () => '/a',
    FlowLayer: class {},
    boardVisible: () => visible,
    desktopLayout: () => ({ id: 'pm-stage', active: visible ? 'pm-board' : 'work' }),
    props: () => ({}),
    readTextFile: async path => (path === '/h/.dudu/cache/remote-states.json'
      ? JSON.stringify({ at: Date.now(), states: { '198.51.100.10': remoteState } })
      : null),
    cachedRemoteStates, remoteStateCommand, mergeStates, scopeState,
    exec: async (program, args, options) => {
      execCalls.push({ program, args, options });
      if (args[0] === 'machine') return { code: 0, stdout: JSON.stringify([{ name: '198.51.100.10', state: 'connected' }]) };
      return { code: 0, stdout: JSON.stringify(remoteState) };
    },
    v_flex: () => { const p = new Proxy({}, { get: () => () => p }); return p; },
    theme: () => ({}),
  });
  board.dialog = null;
  board.onStage = false;
  board.ledgerHome = '/h/.dudu';
  board.homeKnown = Promise.resolve('/h/.dudu');
  board.localState = { pms: [], tasks: [], events: [] };
  board.remoteStates = {};
  board.keys = { focus() { focused = true; } };
  board.content = () => ({});
  board.publish = () => {};
  const { cx, drain } = asyncContext();
  cx.timer = { after: (_ms, fn) => scheduled.push(fn) };

  // Transition false -> true schedules focus, warmRemoteCache, and refreshRemote.
  visible = true;
  board.render(cx);
  assert.equal(scheduled.length, 1);
  scheduled.shift()(cx);
  await drain();
  assert.equal(focused, true);
  assert.deepEqual(Object.keys(board.remoteStates), ['198.51.100.10']);
  assert.equal(execCalls[0].options?.timeout, 6000);
  assert.equal(execCalls[1].options?.timeout, 10000);
});

test('remote sh scripts expand ~/ cleanly in real /bin/sh without creating literal ~ directories', () => {
  const fakeHome = mkdtempSync(join(tmpdir(), 'pm-dash-tilde-'));
  try {
    mkdirSync(join(fakeHome, 'proj', 'repo'), { recursive: true });
    mkdirSync(join(fakeHome, 'my dir', 'sub'), { recursive: true });
    const env = { ...process.env, HOME: fakeHome };
    const probeOut = execFileSync('/bin/sh', ['-c', REMOTE_PROBE_SH, 'sh', '~/proj/repo', '~/my dir/sub', '~/missing/dir'], { env, encoding: 'utf8' });
    const probed = parseRemoteProbe(probeOut);
    assert.equal(probed.home, fakeHome);
    assert.equal(probed.dirs.length, 3);
    assert.equal(probed.dirs[0].exists, true);
    assert.equal(probed.dirs[0].path, realpathSync(join(fakeHome, 'proj', 'repo')));
    assert.equal(probed.dirs[1].exists, true);
    assert.equal(probed.dirs[1].path, realpathSync(join(fakeHome, 'my dir', 'sub')));
    assert.equal(probed.dirs[2].exists, false);
    assert.equal(probed.dirs[2].path, join(fakeHome, 'missing/dir'));

    const dirsOut = execFileSync('/bin/sh', ['-c', REMOTE_LIST_DIRS_SH, 'sh', '~/proj'], { env, encoding: 'utf8' });
    const listed = parseRemoteDirs(dirsOut);
    assert.equal(listed.base, realpathSync(join(fakeHome, 'proj')));
    assert.deepEqual(listed.entries.map(e => e.name), ['repo']);

    const createdOut = execFileSync('/bin/sh', ['-c', REMOTE_MKDIR_SH, 'sh', '~/new proj/sub'], { env, encoding: 'utf8' }).trim();
    assert.equal(createdOut, realpathSync(join(fakeHome, 'new proj', 'sub')));
    assert.throws(() => statSync(join(fakeHome, '~')));
  } finally {
    rmSync(fakeHome, { recursive: true, force: true });
  }
});

test('setupCoversPage: Set up missing covers the page only when no other machine has projects', async () => {
  const { setupCoversPage } = await import('./model.js');
  const remote = { pms: [{ name: 'pm-dudu', machine: '198.51.100.10' }] };
  assert.equal(setupCoversPage('missing', { pms: [] }), true);
  assert.equal(setupCoversPage(null, undefined), true);
  assert.equal(setupCoversPage('missing', remote), false);
  assert.equal(setupCoversPage(null, remote), false);
  assert.equal(setupCoversPage('ready', { pms: [] }), false);
  assert.equal(setupCoversPage('outdated', { pms: [] }), false);
});
