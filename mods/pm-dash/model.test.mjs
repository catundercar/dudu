import test from 'node:test';
import { summary, focusKey, shouldReturnToWork, WRITE_REMOTE_CACHE } from '../pm-nav/model.js';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { layout, boardFrame, fitBoard, withAlpha, solidText, isDarkTheme, cleanTaskLog, hoverCardPosition, mergeStates, cachedRemoteStates, newEvents, pointAt, terminalFor, counts, eventText, word, taskStatusText, pmColor, wireFlows, sampleWire, arcHops, PACKET_SPEED, PACKET_STEP } from './model.js';

test('task status text shows cleanup in both languages and preserves false or missing behavior', () => {
  for (const [lang, cleanupText, mergedText, releasedText, workingText, blockedText, reviewText] of [
    ['en', 'Merged · not retired', 'Merged', 'Released', 'Working…', 'Blocked · Waiting for you', 'Review · Waiting for you'],
    ['zh', '已合并 · 待回收', '已合并', '已发布', '工作中…', '阻塞 · 等你', '待审 · 等你'],
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
    const rows = layout(merged).rows.filter(row => row.type === 'task');
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
    assert.equal(g.rows.length,6); assert.equal(g.wires.length,5);
    for (const wire of g.wires) {
      const a = g.rows.find(r => r.id === wire.from), b = g.rows.find(r => r.id === wire.to);
      assert.deepEqual(pointAt(wire.points,0), {x:a.x+a.w,y:a.y+a.h/2});
      assert.deepEqual(pointAt(wire.points,1), {x:b.x,y:b.y+b.h/2});
      assert.ok(b.x+b.w <= w); assert.ok(b.y+b.h <= g.height);
    }
    const tasks = g.rows.filter(r => r.type === 'task');
    assert.equal(tasks[0].y,g.bodyTop);
    assert.equal(tasks[0].h,w >= 1300 ? 36 : 32);
    assert.equal(tasks[1].y,tasks[0].y + tasks[0].h);
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

test('normal and wide geometry use the mockup column widths and contiguous task groups', () => {
  for (const [width, wide, hubWidth, pmX, pmWidth, taskX, rowHeight] of [
    [1164, false, 148, 232, 214, 490, 32],
    [1462, true, 176, 326, 260, 670, 36],
  ]) {
    const g = layout(state, width, 900, 1, wide);
    assert.equal(g.rows[0].w, hubWidth);
    assert.equal(g.pmX, pmX);
    assert.equal(g.taskX, taskX);
    assert.ok(g.rows.filter(r => r.type === 'pm').every(r => r.w === pmWidth));
    assert.ok(g.rows.filter(r => r.type === 'task').every(r => r.h === rowHeight));
    for (const group of g.taskGroups) {
      const tasks = g.rows.filter(r => r.type === 'task' && (r.pm || '') === group.pm);
      assert.equal(tasks[0].y, group.y);
      assert.equal(tasks.at(-1).y + tasks.at(-1).h, group.y + group.h);
      assert.ok(tasks.every(r => r.x === group.x && r.w === group.w));
      assert.deepEqual(tasks.map(r => r.first), tasks.map((_, i) => i === 0));
      assert.equal(group.h, tasks.length * rowHeight);
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

test('each task retains its own curved route at the group left edge at every scale', () => {
  const input = { pms: [{ name: 'a' }], tasks: Array.from({ length: 9 }, (_, i) => ({ id: String(i), pm: 'a' })), events: [] };
  for (const width of [560, 980, 1462]) {
    for (const scale of [.6, .8, 1]) {
      const g = layout(input, width, 300, scale), group = g.taskGroups[0];
      const wires = g.wires.filter(w => w.to.startsWith('task:'));
      assert.equal(wires.length, input.tasks.length);
      assert.equal(new Set(wires.map(w => w.to)).size, input.tasks.length);
      const first = g.rows.find(r => r.type === 'task'), last = g.rows.at(-1);
      assert.equal(group.y, first.y);
      assert.ok(Math.abs(group.y + group.h - last.y - last.h) < 1e-8);
      for (const wire of wires) {
        const row = g.rows.find(r => r.id === wire.to), pm = g.rows.find(r => r.id === wire.from);
        assert.deepEqual(wire.points[0], [pm.x + pm.w, pm.y + pm.h / 2]);
        assert.deepEqual(wire.points[3], [group.x, row.y + row.h / 2]);
        assert.equal(wire.points[1][1], wire.points[0][1]);
        assert.equal(wire.points[2][1], wire.points[3][1]);
        assert.ok(wire.points[1][0] > wire.points[0][0] && wire.points[2][0] < wire.points[3][0]);
      }
    }
  }
});

test('urgency order is stable within each PM and machine and never mutates the ledger', () => {
  const statuses = ['paused', 'review', 'in_progress', 'blocked', 'proposed', 'review', 'in_progress', 'merged'];
  const input = { pms: [{ name: 'a' }, { name: 'empty' }], tasks: statuses.map((status, i) => ({
    id: String(i), pm: 'a', status, cleanup: status === 'merged',
  })), events: [] };
  const state = mergeStates(input, { 'remote-a': input, 'remote-b': input });
  const original = structuredClone(state), g = layout(state);
  for (const group of g.taskGroups) {
    assert.deepEqual(g.rows.filter(r => r.type === 'task' && r.pm === group.pm).map(r => r.sourceId), ['1', '3', '5', '2', '6', '0', '4', '7']);
  }
  assert.equal(g.taskGroups.length, 3); // Empty PMs do not draw an empty container.
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
  assert.deepEqual(summary({pms:[{},{}],tasks:[
    {status:'in_progress',worker:'blocked'}, {status:'in_progress'},
    {status:'blocked'}, {status:'review',worker:'working'}, {status:'merged'}, {status:'paused'}
  ]}), {projects:2,active:2,blocked:1});
  assert.deepEqual(summary({pms:[],tasks:[]}), {projects:0,active:0,blocked:0});
});

test('dashboard counts waiting work and running workers without counting idle or closed work', () => {
  const result = counts({lang:'zh',pms:[{name:'pm-a',project:'Alpha'}],tasks:[
    {pm:'pm-a',status:'review',worker:'working'}, {pm:'pm-a',status:'blocked'},
    {pm:'pm-a',status:'in_progress',worker:'working'}, {status:'in_progress',worker:'idle'},
    {status:'merged',worker:'working'}, {status:'paused',worker:'working'}
  ]});
  assert.deepEqual(result, {running:1,review:1,blocked:1,waiting:2,conclusion:'Alpha 有 2 件事等你。'});
  assert.deepEqual(counts({lang:'zh',pms:[],tasks:[]}), {running:0,review:0,blocked:0,waiting:0,conclusion:'现在没有等你的事。'});
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
  const input = {pms:[{name:'pm-a',project:'Alpha'}],tasks:[{pm:'pm-a',status:'review'}]};
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
