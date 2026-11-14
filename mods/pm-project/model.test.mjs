import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from './model.js';
import * as dash from '../pm-dash/model.js';
import * as list from '../pm-list/model.js';

const { timeline, parseConversation, waitingCount, settlePending, bellTarget, answerText, lead, turns, newestReply } = model;

const ev = (at, type, fields = {}) => ({ at: `2026-11-13 ${at}`, type, ...fields });
const thread = (at, task, status, text, extra = {}) => ev(at, 'thread', { task, title: `old ${task}`, status, by: 'hc:t2h', text, ...extra });

test('threads group by adjacency and show what each task is now', () => {
  const events = [
    ev('09:00:00', 'user', { text: '开干！' }),
    thread('09:00:10', 'a', 'in_progress', 'registered (in_progress)'),
    thread('09:00:11', 'b', 'in_progress', 'registered (in_progress)'),
    thread('09:00:12', 'a', 'in_progress', 'dispatched'),          // a later entry does not add a row
    ev('09:00:13', 'agent', { by: 'hc:t5', text: 'hidden in this version' }),
    thread('09:00:14', 'c', 'proposed', 'registered (proposed)'),
    ev('09:01:00', 'pm', { text: '好，开了**三个**线程。' }),
    thread('09:02:00', 'd', 'in_progress', 'registered'),
  ];
  const tasks = [
    { id: 'a', title: '项目对话落盘', status: 'review', latest: 'status=review, commit=2799326; 真实会话端到端跑通' },
    { id: 'b', title: '项目视图 mod', status: 'in_progress', latest: '正在出设计稿' },
    { id: 'c', title: 'Merged one', status: 'merged', latest: 'status=merged', cleanup: true },
  ];
  const items = timeline(events, tasks, { today: '2026-11-13' });
  assert.deepEqual(items.map(i => i.kind), ['day', 'user', 'threads', 'pm', 'threads']);
  assert.equal(items[0].today, true);
  const rows = items[2].rows;
  assert.deepEqual(rows.map(r => r.task), ['a', 'b', 'c']);
  // The ledger now, not the event: status, title and latest log (without its status prefix).
  assert.deepEqual(rows[0], { task: 'a', status: 'review', cleanup: false, title: '项目对话落盘',
    latest: '真实会话端到端跑通', waiting: false, tone: 'review', closed: false });
  assert.equal(rows[1].waiting, false);
  assert.equal(rows[1].tone, 'running');
  assert.equal(rows[2].tone, 'quiet');
  assert.equal(rows[2].waiting, false);
  assert.deepEqual(rows.map(r => r.closed), [false, false, true]);   // work that is over shows as one quiet line
  // A task the ledger no longer lists keeps its newest event here.
  assert.deepEqual(items[4].rows[0], { task: 'd', status: 'in_progress', cleanup: false, title: 'old d',
    latest: 'registered', waiting: false, tone: 'running', closed: false });
  assert.equal(items[3].text, '好，开了**三个**线程。');
  // A reply that is one short paragraph is shown whole: nothing to fold.
  assert.deepEqual([items[3].lead, items[3].long], ['好，开了三个线程。', false]);
});

test('a long reply folds to its opening', () => {
  const report = '四处修复已合并进 `main`（8f297d3）并装好，检查都通过：\n- **编号列表：** 改了。\n- **阴影：** 加了。\n\n还等你决定的：\n- 通知要不要带声音？';
  assert.deepEqual(lead(report), { text: '四处修复已合并进 main（8f297d3）并装好，检查都通过：', more: true });
  // A reply that opens with a list, a heading or a table gives its first line.
  assert.deepEqual(lead('## 验收结果\n\n都通过。'), { text: '验收结果', more: true });
  assert.deepEqual(lead('1. [看板](http://x/y) 改好了\n2. 铃铛也改了'), { text: '看板 改好了', more: true });
  assert.equal(lead('| 项目 | 结果 |\n|---|---|\n| 头像 | 通过 |').text, '项目 结果');
  // A long first paragraph stops at a sentence end; without one in reach, at the limit.
  const long = `${'第一句说明了情况。'.repeat(3)}${'后面还有很长的一段话'.repeat(30)}。`;
  assert.deepEqual(lead(long, 40), { text: '第一句说明了情况。第一句说明了情况。第一句说明了情况。', more: true });
  assert.deepEqual(lead('a'.repeat(50), 20), { text: `${'a'.repeat(20)}…`, more: true });
  assert.deepEqual(lead('  好的。 '), { text: '好的。', more: false });
  const items = timeline([ev('09:00:00', 'pm', { text: report })], [], { today: '2026-11-13' });
  assert.deepEqual([items[1].lead, items[1].long], ['四处修复已合并进 main（8f297d3）并装好，检查都通过：', true]);
});

test('a coordinator turn is its reply, then what it did on the way', () => {
  const items = timeline([
    ev('09:00:00', 'user', { text: '开干！' }),
    thread('09:00:10', 'a', 'in_progress', 'dispatched'),
    ev('09:00:20', 'decision', { text: '按设计稿实现' }),
    ev('09:00:30', 'pm', { text: '派出去了。' }),
    thread('09:05:00', 'b', 'review', 'worker reported'),
    ev('09:05:30', 'pm', { text: 'b 做完了，我在审。' }),
    ev('09:05:40', 'pm', { text: '审完了。' }),
  ], [], { today: '2026-11-13', typing: true });
  const blocks = turns(items);
  assert.deepEqual(blocks.map(b => b.kind === 'turn' ? b.parts.map(p => p.kind).join('+') : b.kind),
    ['day', 'user', 'pm+threads+decision', 'pm+threads', 'pm', 'typing']);
  assert.deepEqual(blocks[2].index, [2, 3, 4]);          // each part's place in `items`, for the bell's jump
  assert.equal(newestReply(items), items[7].key);
  assert.equal(newestReply(items.slice(0, 2)), '');
});

test('threads that got no reply of their own do not stand beside an avatar alone', () => {
  const shape = blocks => blocks.map(b => b.kind === 'turn' ? `${b.bare ? 'bare:' : ''}${b.parts.map(p => p.kind).join('+')}` : b.kind);
  const items = timeline([
    thread('08:59:00', 'z', 'in_progress', 'registered by a worker'),     // before anything was said
    ev('09:00:00', 'user', { text: '开干！' }),
    ev('09:00:30', 'pm', { text: '派出去了。' }),
    thread('09:01:00', 'a', 'in_progress', 'dispatched'),                   // after the reply, then the user speaks
    ev('09:02:00', 'user', { text: '好' }),
    ev('09:02:30', 'pm', { text: '嗯。' }),
    thread('09:03:00', 'b', 'in_progress', 'dispatched'),                   // the newest: the reply is still to come
  ], [], { today: '2026-11-13', typing: true });
  const blocks = turns(items);
  assert.deepEqual(shape(blocks), ['day', 'bare:threads', 'user', 'pm+threads', 'user', 'pm', 'bare:threads', 'typing']);
  assert.deepEqual(blocks[3].index, [3, 4]);
});

test('the event that blocks a task becomes the coordinator asking, with quick answers while it waits', () => {
  const events = [
    thread('09:00:00', 'h', 'in_progress', 'registered'),
    thread('09:05:00', 'h', 'blocked', 'status=blocked; 开工前要你定一件事：技能改动交给线程吗？', { options: ['交给线程', ' 仍由 PM 改 ', ''] }),
    thread('09:06:00', 'h', 'blocked', 'still waiting'),             // already blocked: not a new question
    thread('09:07:00', 'q', 'in_progress', 'registered'),
    thread('09:08:00', 'q', 'blocked', 'status=blocked; 名字用哪个？'),  // no options: the user types the answer
    ev('09:09:00', 'decision', { text: 'PM 的后续方向做成 Projects 形态', quote: '开干！' }),
  ];
  const tasks = [{ id: 'h', title: '协调者去手', status: 'blocked', latest: 'still waiting' },
    { id: 'q', title: '命名', status: 'blocked', latest: '名字用哪个？' }];
  const items = timeline(events, tasks, { today: '2026-11-13' });
  assert.deepEqual(items.map(i => i.kind), ['day', 'threads', 'question', 'threads', 'question', 'decision']);
  assert.deepEqual({ ...items[2], key: undefined }, { at: '2026-11-13 09:05:00', kind: 'question', key: undefined, task: 'h',
    title: '协调者去手', text: '开工前要你定一件事：技能改动交给线程吗？', open: true, options: ['交给线程', '仍由 PM 改'] });
  assert.equal(items[1].rows[0].waiting, true);
  assert.deepEqual(items[4].options, []);
  assert.equal(items[4].open, true);
  assert.deepEqual(items[5], { at: '2026-11-13 09:09:00', kind: 'decision', key: 'decision:2026-11-13 09:09:00:',
    text: 'PM 的后续方向做成 Projects 形态', quote: '开干！' });
  assert.equal(bellTarget(items), 4);
  assert.equal(answerText('协调者去手', '交给线程'), '【协调者去手】交给线程');

  // Answered (the task moved on), or asked again later: only the newest question of a waiting task is open.
  const answered = timeline(events, [{ ...tasks[0], status: 'in_progress' }, { ...tasks[1], status: 'in_progress' }]);
  assert.deepEqual(answered.filter(i => i.kind === 'question').map(i => i.open), [false, false]);
  assert.equal(bellTarget(answered), -1);
  const again = timeline([...events, thread('09:10:00', 'h', 'in_progress', 'answered'),
    thread('09:11:00', 'h', 'blocked', 'status=blocked; 还有一件', { options: ['好'] })], tasks);
  assert.deepEqual(again.filter(i => i.kind === 'question' && i.task === 'h').map(i => [i.text, i.open]),
    [['开工前要你定一件事：技能改动交给线程吗？', false], ['还有一件', true]]);
  // A blocked task with no open question: the bell falls back to its thread row.
  const blocked = timeline([thread('09:00:00', 'r', 'in_progress', 'x')], [{ id: 'r', title: 'R', status: 'blocked' }]);
  assert.equal(bellTarget(blocked), 1);
  // Review is the PM's job: a review task alone gives the bell nothing.
  const review = timeline([thread('09:00:00', 'r', 'in_progress', 'x')], [{ id: 'r', title: 'R', status: 'review' }]);
  assert.equal(review[1].rows[0].waiting, false);
  assert.equal(bellTarget(review), -1);
});

test('the waiting count uses the board rule, task by task under each PM', () => {
  const state = {
    lang: 'en',
    pms: [{ name: 'pm-dudu', project: 'dudu' }, { name: 'pm-wb', project: 'wb' }],
    tasks: [
      { id: '1', pm: 'pm-dudu', status: 'blocked' }, { id: '2', pm: 'pm-dudu', status: 'review' },
      { id: '3', pm: 'pm-dudu', status: 'in_progress' }, { id: '4', pm: 'pm-wb', status: 'review' },
      { id: '5', pm: 'pm-dudu', status: 'merged', cleanup: true }, { id: '6', pm: 'pm-wb', status: 'paused' },
    ],
  };
  assert.equal(waitingCount(state, 'pm-dudu'), 1);
  assert.equal(waitingCount(state, 'pm-wb'), 0);
  assert.equal(waitingCount(state, 'pm-none'), 0);
  // The board's own total is the sum of the per-PM counts.
  assert.equal(waitingCount(state, 'pm-dudu') + waitingCount(state, 'pm-wb'), dash.counts(state).waiting);
  // A project's rows say "waiting" for exactly the tasks the count includes.
  const items = timeline(state.tasks.filter(t => t.pm === 'pm-dudu').map((t, i) => thread(`09:0${i}:00`, t.id, 'in_progress', 'x')),
    state.tasks);
  assert.equal(items[1].rows.filter(r => r.waiting).length, waitingCount(state, 'pm-dudu'));
  assert.equal(waitingCount({}, 'pm-dudu'), 0);
});

test('a sent message shows at once and gives way to the same line in the log', () => {
  const sentAt = new Date('2026-11-13T09:00:05').getTime();
  const pending = [{ id: 1, text: '把连线改成曲线', sentAt }, { id: 2, text: 'second', sentAt }];
  let items = timeline([ev('09:00:00', 'user', { text: '早' })], [], { pending, typing: true });
  assert.deepEqual(items.slice(-3).map(i => [i.kind, i.text, i.pending]),
    [['user', '把连线改成曲线', true], ['user', 'second', true], ['typing', undefined, undefined]]);
  // An older line with the same words does not settle it; the logged one does (whitespace aside).
  const log = [ev('08:58:00', 'user', { text: 'second' }), ev('09:00:06', 'user', { text: ' 把连线改成曲线\n' })];
  const left = settlePending(pending, log);
  assert.deepEqual(left.map(p => p.id), [2]);
  items = timeline(log, [], { pending: left });
  assert.deepEqual(items.filter(i => i.kind === 'user').map(i => [i.text, Boolean(i.pending)]),
    [['second', false], ['把连线改成曲线', false], ['second', true]]);
  // One logged line settles one bubble; nothing to settle keeps the same array.
  const twice = [{ id: 3, text: 'ok', sentAt }, { id: 4, text: 'ok', sentAt }];
  assert.deepEqual(settlePending(twice, [ev('09:00:07', 'user', { text: 'ok' })]).map(p => p.id), [4]);
  assert.equal(settlePending(pending, []), pending);
  // A failed send stays, marked, and is never settled.
  const failed = [{ id: 5, text: 'ok', sentAt, failed: 'busy' }];
  assert.equal(settlePending(failed, [ev('09:00:07', 'user', { text: 'ok' })]), failed);
  assert.deepEqual(timeline([], [], { pending: failed }).map(i => [i.kind, i.pending, i.failed]), [['user', false, 'busy']]);
});

test('the log is read as its last 200 events, skipping lines that are not events', () => {
  const lines = ['null', '[]', 'not json', '{"type": 3}', ...Array.from({ length: 205 }, (_, i) => JSON.stringify({ type: 'user', text: String(i) })), '{"type":"pm","te'];
  const events = parseConversation(lines.join('\n'));
  assert.equal(events.length, 200);
  assert.equal(events[0].text, '5');
  assert.equal(events.at(-1).text, '204');
  assert.deepEqual(parseConversation(''), []);
  assert.deepEqual(parseConversation(null), []);
  // Days get their own divider; empty texts are not drawn.
  const items = timeline([{ at: '2026-11-12 23:59:00', type: 'pm', text: 'late' }, ev('00:00:01', 'pm', { text: '  ' }),
    ev('00:01:00', 'user', { text: 'early' })], [], { today: '2026-11-13' });
  assert.deepEqual(items.map(i => [i.kind, i.date ?? i.text]), [['day', '2026-11-12'], ['pm', 'late'], ['day', '2026-11-13'], ['user', 'early']]);
});

test('commands, clocks and paths', () => {
  assert.deepEqual(model.diffArgv({ worktree: '/w', repo: '/r', base: 'main', branch: 'dev/x' }), ['git', '-C', '/w', 'diff', 'main...dev/x']);
  assert.deepEqual(model.diffArgv({ repo: '/r', branch: 'dev/x' }), ['git', '-C', '/r', 'diff', 'main...dev/x']);
  assert.equal(model.diffArgv({ repo: '/r' }), null);
  assert.deepEqual(model.sendArgv('t2h', 'hi'), ['-u', 'HC_TERMINAL_ID', 'hc', 'send', '--', 't2h', 'hi']);
  assert.deepEqual(model.sendArgv('t2h', '- item'), ['-u', 'HC_TERMINAL_ID', 'hc', 'send', '--', 't2h', '- item']);
  assert.equal(model.clock('2026-11-13 09:08', '2026-11-13'), '09:08');
  assert.equal(model.clock('2026-11-12 23:01:09', '2026-11-13'), '11-12 23:01');
  assert.equal(model.shortPath('/Users/me/project/dudu', '/Users/me'), '~/project/dudu');
  assert.equal(model.shortPath('/Users/meow', '/Users/me'), '/Users/meow');
  assert.equal(model.statusLabel('zh', 'review'), '审查中');
  assert.equal(model.statusLabel('en', 'merged', true), 'Merged · not retired');
  assert.equal(model.word('zh', 'waitingCount', 1), '1 件事等你');
  assert.equal(model.word('en', 'waitingCount', 2), '2 items waiting for you');
});

test('the PM and thread terminals are found as on the board', () => {
  const terms = [
    { address: 't2h', state: 'live', labels: { pm: 'dudu' } },
    { address: 't9', state: 'live', labels: { task: 'dudu-x' }, parent: 't2h' },
    { address: 'dev/t1', state: 'live', labels: { pm: 'dudu' } },
  ];
  const pm = model.pmRow({ name: 'pm-dudu', project: 'dudu', repo: '/r', pane: 'hc:t2h' });
  assert.equal(model.terminalFor(pm, terms).address, 't2h');
  assert.equal(model.terminalFor(model.taskRow({ id: 'dudu-x', pane: 'hc:t2h' }), terms).address, 't9');
  // A task recorded on its PM's pane, with no worker of its own, has no terminal.
  assert.equal(model.terminalFor(model.taskRow({ id: 'dudu-y', pane: 'hc:t2h' }), terms), undefined);
});

test('copied helpers stay identical to pm-dash and pm-list', () => {
  for (const name of ['cleanTaskLog', 'terminalFor', 'terminalTargetFor', 'withAlpha', 'isDarkTheme', 'solidText']) {
    assert.equal(model[name].toString(), dash[name].toString(), name);
  }
  assert.equal(model.terminalFor.toString(), list.terminalFor.toString());
  assert.equal(model.LEDGER_HOME_SH, dash.LEDGER_HOME_SH);
});

test('a paragraph after a sub-list leaves its item, so the next item keeps its number', () => {
  // Herdr 0.1.15 draws a marker for that paragraph: 1, 1, 2, 2.
  const reply = [
    '1. **Check:** four things:', '   - layout', '   - bell', '', '   It also sends a test line.',
    '2. **Notify:** the script is ready:', '   - a worker', '', '   **Not covered:** clicking it.',
    '3. Push?', '4. Clean up?',
  ].join('\n');
  assert.equal(model.viewMarkdown(reply), [
    '1. **Check:** four things:', '   - layout', '   - bell', '', 'It also sends a test line.', '',
    '2. **Notify:** the script is ready:', '   - a worker', '', '**Not covered:** clicking it.', '',
    '3. Push?', '4. Clean up?',
  ].join('\n'));
  // What already renders right is left alone: plain lists, a paragraph after a
  // paragraph, a line that continues a sub-item, code blocks, wider markers.
  for (const text of [
    '1. a\n2. b\n3. c\n4. d',
    '1. Publish.\n\n   Then announce.\n2. Done.',
    '- a\n  - b\n  lazy\n- c',
    '1. a\n   ```\n   - x\n\n   y\n   ```\n2. b',
    '10. a\n    - b\n\n11. c',
    'Intro\n\n- a\n\nOutro',
  ]) assert.equal(model.viewMarkdown(text), text);
  assert.equal(model.viewMarkdown('10. a\n    - b\n\n    after\n11. c'), '10. a\n    - b\n\nafter\n\n11. c');
  assert.equal(model.viewMarkdown(''), '');
});
