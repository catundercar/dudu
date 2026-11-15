import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from './model.js';
import * as dash from '../pm-dash/model.js';
import * as list from '../pm-list/model.js';

const { timeline, parseConversation, waitingCount, settlePending, bellTarget, answerText, lead, turns, newestReply, threadList, sessionLabel, questionOnly, age, workingTasks, threadLink } = model;

// The timeline without the thread-name labels (`about`), for the tests that are not about them.
const plain = items => items.filter(i => i.kind !== 'about');

const ev = (at, type, fields = {}) => ({ at: `2026-11-13 ${at}`, type, ...fields });
const thread = (at, task, status, text, extra = {}) => ev(at, 'thread', { task, title: `old ${task}`, status, by: 'hc:t2h', text, ...extra });

test('threads group by adjacency and show what each task is now', () => {
  const events = [
    ev('09:00:00', 'user', { text: '开干！' }),
    thread('09:00:10', 'a', 'in_progress', 'registered (in_progress)'),
    thread('09:00:11', 'b', 'in_progress', 'registered (in_progress)'),
    thread('09:00:12', 'a', 'in_progress', 'dispatched'),          // a later entry adds no row, only a label of what reported
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
  assert.deepEqual(items.map(i => i.kind), ['day', 'user', 'threads', 'about', 'pm', 'threads']);
  assert.deepEqual([items[3].task, items[3].title], ['a', '项目对话落盘']);
  assert.equal(items[0].today, true);
  const rows = items[2].rows;
  assert.deepEqual(rows.map(r => r.task), ['a', 'b', 'c']);        // one group, across the label in between
  // The ledger now, not the event: status, title and latest log (without its status prefix).
  assert.deepEqual(rows[0], { task: 'a', status: 'review', cleanup: false, title: '项目对话落盘',
    latest: '真实会话端到端跑通', waiting: false, tone: 'review', closed: false });
  assert.equal(rows[1].waiting, false);
  assert.equal(rows[1].tone, 'running');
  assert.equal(rows[2].tone, 'quiet');
  assert.equal(rows[2].waiting, false);
  assert.deepEqual(rows.map(r => r.closed), [false, false, true]);   // work that is over shows as one quiet line
  // A task the ledger no longer lists keeps its newest event here.
  assert.deepEqual(items[5].rows[0], { task: 'd', status: 'in_progress', cleanup: false, title: 'old d',
    latest: 'registered', waiting: false, tone: 'running', closed: false });
  assert.equal(items[4].text, '好，开了**三个**线程。');
  // A reply that is one short paragraph is shown whole: nothing to fold.
  assert.deepEqual([items[4].lead, items[4].long], ['好，开了三个线程。', false]);
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

test('a reply carries the names of the threads the coordinator wrote about', () => {
  const shape = blocks => blocks.map(b => b.kind !== 'turn' ? b.kind
    : `${b.bare ? 'bare:' : ''}${b.parts.map(p => p.kind === 'about' ? `about(${p.task})` : p.kind).join('+')}`);
  const worker = (at, task, status, text) => thread(at, task, status, text, { by: 'hc:t9' });   // `thread` writes as hc:t2h, the PM here
  const said = (at, text, by = 'hc:t2h') => ev(at, 'pm', { text, ...(by ? { by } : {}) });
  const events = [
    ev('09:00:00', 'user', { text: '开干！' }),
    thread('09:00:10', 'a', 'in_progress', 'dispatched'),
    thread('09:00:11', 'a', 'in_progress', 'brief sent'),              // its row is in this turn: no name too
    said('09:00:30', '派出去了。'),
    worker('09:05:00', 'a', 'review', 'worker reported'),              // a worker's entry names nothing…
    thread('09:05:10', 'a', 'merged', 'status=merged'),                // …the PM's does, once per thread
    thread('09:05:11', 'a', 'merged', 'retired'),
    thread('09:05:20', 'b', 'in_progress', 'dispatched'),
    said('09:05:30', 'a 合并了，b 派出去了。'),
    ev('09:06:00', 'user', { text: '录入官方清单了吗？' }),
    worker('09:06:10', 'b', 'in_progress', 'halfway'),                 // logged while the user asked something else
    said('09:06:30', '还没收录。'),
    thread('09:07:00', 'b', 'blocked', 'status=blocked; 用哪个？', { options: ['甲', '乙'] }),
    said('09:07:10', 'b 要你定一件事。'),                               // the question card carries b's name
    worker('09:08:00', 'b', 'in_progress', 'more progress'),            // no reply of its own, then the user speaks
    ev('09:09:00', 'user', { text: '好' }),
    said('09:09:30', '嗯。', 'hc:t3b'),                                 // another session spoke: hc:t2h's entry is not its own
    thread('09:10:00', 'a', 'merged', 'a note'),
    said('09:10:10', '顺手记了一笔。', 'hc:t3b'),
    thread('09:11:00', 'a', 'merged', 'note from the PM, mid-turn'),    // the newest: no reply yet, nothing to name
  ];
  const items = timeline(events, [], { today: '2026-11-13', typing: true });
  assert.deepEqual(shape(turns(items)), ['day', 'user', 'pm+threads', 'about(a)+pm+threads', 'user', 'pm', 'pm+question',
    'user', 'pm', 'pm', 'typing']);
  // A log from before replies recorded who spoke: the PM's pane now stands in.
  const old = timeline([thread('09:00:00', 'a', 'in_progress', 'dispatched'), said('09:00:30', '派了。', ''),
    thread('09:05:00', 'a', 'merged', 'status=merged'), said('09:05:30', '合了。', '')], []);
  assert.deepEqual(shape(turns(old, 'hc:t2h')), ['day', 'pm+threads', 'about(a)+pm']);
  assert.deepEqual(shape(turns(old, 'hc:t3b')), ['day', 'pm+threads', 'pm']);
  assert.deepEqual(shape(turns(old)), ['day', 'pm+threads', 'pm']);
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
  const all = timeline(events, tasks, { today: '2026-11-13' }), items = plain(all);
  assert.deepEqual(items.map(i => i.kind), ['day', 'threads', 'question', 'threads', 'question', 'decision']);
  assert.deepEqual({ ...items[2], key: undefined }, { at: '2026-11-13 09:05:00', kind: 'question', key: undefined, task: 'h',
    title: '协调者去手', text: '开工前要你定一件事：技能改动交给线程吗？', open: true, options: ['交给线程', '仍由 PM 改'],
    notes: ['', ''], recommended: false, chosen: -1 });
  assert.equal(items[1].rows[0].waiting, true);
  assert.deepEqual(items[4].options, []);
  assert.equal(items[4].open, true);
  assert.deepEqual(items[5], { at: '2026-11-13 09:09:00', kind: 'decision', key: 'decision:2026-11-13 09:09:00:',
    text: 'PM 的后续方向做成 Projects 形态', quote: '开干！' });
  assert.equal(all[bellTarget(all)], items[4]);
  assert.equal(answerText('协调者去手', '交给线程'), '【协调者去手】交给线程');

  // Answered (the task moved on), or asked again later: only the newest question of a waiting task is open.
  const answered = timeline(events, [{ ...tasks[0], status: 'in_progress' }, { ...tasks[1], status: 'in_progress' }]);
  assert.deepEqual(answered.filter(i => i.kind === 'question').map(i => i.open), [false, false]);

  // An option can say why, and the first can be the coordinator's pick. Picking one shows at once
  // (the bubble still being sent), and stays once the quick answer is in the log.
  const asking = [thread('10:00:00', 'k', 'in_progress', 'x'), thread('10:01:00', 'k', 'blocked', '计数放在哪？',
    { options: ['Redis', '', '内存'], option_notes: ['一份共享的计数', 'dropped with its option', ''], recommended: true })];
  const waitingOn = [{ id: 'k', title: '限流', status: 'blocked' }];
  const card = timeline(asking, waitingOn).find(i => i.kind === 'question');
  assert.deepEqual([card.options, card.notes, card.recommended, card.chosen], [['Redis', '内存'], ['一份共享的计数', ''], true, -1]);
  const sending = timeline(asking, waitingOn, { pending: [{ id: 1, text: '【限流】内存', sentAt: 0, question: card.key }] });
  assert.equal(sending.find(i => i.kind === 'question').chosen, 1);
  const failed = timeline(asking, waitingOn, { pending: [{ id: 1, text: '【限流】内存', sentAt: 0, question: card.key, failed: 'no' }] });
  assert.equal(failed.find(i => i.kind === 'question').chosen, -1);
  const logged = timeline([...asking, ev('10:02:00', 'user', { text: ' 【限流】Redis ' }), thread('10:03:00', 'k', 'in_progress', '用户选了 Redis')],
    [{ id: 'k', title: '限流', status: 'in_progress' }]).find(i => i.kind === 'question');
  assert.deepEqual([logged.open, logged.chosen], [false, 0]);
  // An answer in the user's own words picks nothing.
  assert.equal(timeline([...asking, ev('10:02:00', 'user', { text: '用 Redis 吧' })], waitingOn).find(i => i.kind === 'question').chosen, -1);
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

test('a task that enters the log as a question is that question alone', () => {
  // `pm.py new --status blocked --option …`: the coordinator asks; there is no work to show a row for.
  const events = [thread('09:00:00', 'sound', 'blocked', 'PM 的通知要不要带声音？', { options: ['带声音', '不带声音'] }),
    thread('09:00:00', 'push', 'blocked', '要不要推到 GitHub？')];
  const waiting = timeline(events, [{ id: 'sound', title: '通知声音', status: 'blocked' }, { id: 'push', title: '推送', status: 'blocked' }]);
  assert.deepEqual(waiting.map(i => [i.kind, i.open]), [['day', undefined], ['question', true], ['question', true]]);
  assert.equal(bellTarget(waiting), 2);
  // Answered and closed: still one line each, not a finished-thread line beside it.
  const answered = timeline([...events, thread('09:30:00', 'sound', 'done', 'status=done; 用户：不带声音')],
    [{ id: 'sound', title: '通知声音', status: 'done' }, { id: 'push', title: '推送', status: 'released' }]);
  assert.deepEqual(plain(answered).map(i => [i.kind, i.open]), [['day', undefined], ['question', false], ['question', false]]);
  assert.deepEqual([...questionOnly([...events, thread('09:30:00', 'sound', 'done', 'x')])].sort(), ['push', 'sound']);

  // A task that entered blocked and then became work gets its row where the work starts, showing what it is now.
  const worked = [...events, thread('09:40:00', 'push', 'blocked', 'still asking'), thread('09:50:00', 'push', 'in_progress', '开始推'),
    thread('09:55:00', 'push', 'merged', 'status=merged')];
  const later = plain(timeline(worked, [{ id: 'sound', title: '通知声音', status: 'blocked' }, { id: 'push', title: '推送', status: 'merged' }]));
  assert.deepEqual(later.map(i => i.kind), ['day', 'question', 'question', 'threads']);
  assert.equal(later[3].at, '2026-11-13 09:50:00');
  assert.deepEqual(later[3].rows.map(r => [r.task, r.status, r.closed]), [['push', 'merged', true]]);
  assert.deepEqual([...questionOnly(worked)], ['sound']);
  // Blocked straight to closed stays a question; a task that starts as work is never one, whatever blocks it later.
  assert.deepEqual([...questionOnly([thread('09:00:00', 'w', 'in_progress', 'x'), thread('09:01:00', 'w', 'blocked', 'y'),
    thread('09:02:00', 'w', 'done', 'z')])], []);
});

test('an abandoned thread has no line; a question it asked stays', () => {
  const events = [
    ev('09:00:00', 'user', { text: '试一下通知' }),
    thread('09:01:00', 't', 'in_progress', 'dispatched to toast-test', { title: 'Toast test (ignore)' }),
    thread('09:02:00', 'a', 'in_progress', 'dispatched'),
    thread('09:03:00', 'q', 'in_progress', 'started'),
    thread('09:04:00', 'q', 'blocked', '推不推？', { options: ['推', '不推'] }),
    thread('09:05:00', 't', 'abandoned', 'retired: removed worktree'),
    thread('09:06:00', 'q', 'abandoned', 'status=abandoned'),
    ev('09:07:00', 'pm', { text: '测试线程清掉了。', by: 'hc:t2h' }),
  ];
  const items = timeline(events, [], { today: '2026-11-13' });
  assert.deepEqual(items.map(i => i.kind), ['day', 'user', 'threads', 'question', 'pm']);
  assert.deepEqual(items[2].rows.map(r => r.task), ['a']);
  // The question is what was said; it can no longer be answered.
  assert.deepEqual([items[3].task, items[3].text, items[3].open], ['q', '推不推？', false]);
  // The reply that closed them carries no name of a thread that is not shown.
  assert.deepEqual(turns(items, 'hc:t2h').filter(b => b.kind === 'turn').flatMap(b => b.parts.map(p => p.kind)), ['pm', 'threads', 'question']);
  // The ledger's word counts over the log's: a task abandoned after the log's last entry for it.
  assert.deepEqual(timeline(events, [{ id: 'a', title: 'A', status: 'abandoned' }]).map(i => i.kind), ['day', 'user', 'question', 'pm']);
});

test('the side panel lists what is open, who works in the project, and what ended last', () => {
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/r/dudu/', worktrees: '/h/.herdr/worktrees/dudu', pane: 'hc:t3b' };
  const tasks = [
    { id: 'c', pm: 'pm-dudu', title: 'C', status: 'proposed', pane: 'hc:t1h', updated: '2026-11-13 09:27', latest: '' },
    { id: 'a', pm: 'pm-dudu', title: 'A', status: 'in_progress', updated: '2026-11-13 10:00', latest: 'status=in_progress; wiring', branch: 'dev/a' },
    { id: 'b', pm: 'pm-dudu', title: 'B', status: 'blocked', updated: '2026-11-13 08:00', latest: '要你定' },
    { id: 'd', pm: 'pm-dudu', title: 'D', status: 'merged', updated: '2026-11-13 09:00', cleanup: true },
    { id: 'p', pm: 'pm-dudu', title: 'P', status: 'paused', updated: '2026-11-13 07:00', latest: '等上游' },
    { id: 'x', pm: 'pm-other', title: 'X', status: 'in_progress', updated: '2026-11-13 11:00' },
  ];
  const events = [thread('08:00:00', 'e', 'merged', 'status=merged'), thread('08:10:00', 'f', 'in_progress', 'started'),
    thread('08:30:00', 'f', 'done', 'status=done'), thread('08:40:00', 'a', 'in_progress', 'dispatched'),
    ev('08:50:00', 'pm', { text: 'hi' })];
  const claude = { key: 'claude', name: 'Claude Code', icon: 'icons/claude.svg', tint: false, agent: true };
  const terms = [
    { address: 't3b', state: 'live', cwd: '/r/dudu', labels: { pm: 'dudu' } },                              // the PM
    { address: 't1h', state: 'live', cwd: '/r/dudu', labels: {} },                                         // the user's own session
    { address: 't40', state: 'live', cwd: '/h/.herdr/worktrees/dudu/dev-a', labels: { task: 'a' }, status: 'working' }, // A's worker
    { address: 't41', state: 'live', cwd: '/h/.herdr/worktrees/dudu/dev-e', labels: { task: 'e' } },          // a worker whose task ended
    { address: 't2t', state: 'live', cwd: '/r/dudu/mods' },
    { address: 't50', state: 'live', cwd: '/r/dudu-other' },                                               // another folder
    { address: 't60', state: 'finished', cwd: '/r/dudu' },
    { address: 'dev/t1', state: 'live', cwd: '/r/dudu' },                                                  // another machine
  ];
  const live = [
    { address: 't3b', status: 'working', title: '✳ PM', tab: 'tb0', program: claude, seq: 20 },
    { address: 't2t', status: 'idle', title: '⠂ something else', tab: 'tb3', program: claude, seq: 3 },
    { address: 't1h', status: 'working', title: '✳ PM 主对话上下文腐蚀', tab: 'tb1', program: claude, seq: 5 },
    { address: 't40', status: 'working', title: 'A', tab: 'tb4', program: claude, seq: 8 },
    { address: 't41', status: 'weird', title: 'Claude Code', tab: 'tb2', program: claude, seq: 9 },
    { address: 't50', status: 'idle', title: 'elsewhere', tab: 'tb5', program: claude, seq: 1 },
    { address: 't60', status: 'idle', title: 'gone', tab: 'tb6', program: claude, seq: 1 },
    { address: 'dev/t1', status: 'idle', title: 'remote', tab: 'dev/tb1', program: claude, seq: 1 },
  ];
  const tabs = [{ id: 'tb1', name: 'Claude Code', named: true }, { id: 'tb2', name: '2', named: false }, { id: 'tb3', name: 'ios', named: true }];
  const list = threadList(pm, tasks, events, terms, live, tabs);
  assert.deepEqual(list.open, [
    { task: 'b', title: 'B', status: 'blocked', tone: 'blocked', waiting: true, group: 'waiting', latest: '要你定',
      updated: '2026-11-13 08:00', branch: '', working: false },
    { task: 'a', title: 'A', status: 'in_progress', tone: 'running', waiting: false, group: 'working', latest: 'wiring',
      updated: '2026-11-13 10:00', branch: 'dev/a', working: true },
    { task: 'p', title: 'P', status: 'paused', tone: 'quiet', waiting: false, group: 'paused', latest: '等上游', updated: '2026-11-13 07:00',
      branch: '', working: false },
    { task: 'c', title: 'C', status: 'proposed', tone: 'quiet', waiting: false, group: 'parked', latest: '', updated: '2026-11-13 09:27',
      branch: '', working: false },
  ]);
  // Only a task's own worker, at work now, makes it move: not a finished or remote terminal, not one that rests.
  assert.deepEqual([...workingTasks(terms, live)], ['a']);
  assert.deepEqual([...workingTasks([{ address: 't1', state: 'live', labels: { task: 'x' }, status: 'working' },
    { address: 't2', state: 'finished', labels: { task: 'y' }, status: 'working' },
    { address: 'dev/t3', state: 'live', labels: { task: 'z' }, status: 'working' },
    { address: 't4', state: 'live', labels: { task: 'w' }, status: 'working' }], [{ address: 't4', status: 'idle' }])], ['x']);
  // Working first, then the most recently changed; a session that registered a task itself (t1h holds C) is still a session.
  assert.deepEqual(list.sessions, [
    { address: 't1h', status: 'working', program: claude, label: 'PM 主对话上下文腐蚀' },   // the tab is named after the program
    { address: 't41', status: 'idle', program: claude, label: 'Claude Code' },           // the title only repeats the program
    { address: 't2t', status: 'idle', program: claude, label: 'ios' },                   // a tab someone named
  ]);
  assert.deepEqual(list.finished, [
    { task: 'd', title: 'D', status: 'merged', cleanup: true },
    { task: 'f', title: 'old f', status: 'done', cleanup: false },
    { task: 'e', title: 'old e', status: 'merged', cleanup: false },
  ]);
  // No more than the newest few that ended; nothing without a PM's project folders.
  const many = Array.from({ length: 9 }, (_, i) => thread(`08:0${i}:00`, `m${i}`, 'done', 'x'));
  assert.deepEqual(threadList(pm, [], many).finished.map(r => r.task), ['m8', 'm7', 'm6', 'm5', 'm4', 'm3']);
  assert.deepEqual(threadList({ name: 'pm-x' }, tasks, [], terms, live, tabs), { open: [], sessions: [], finished: [] });
  // An answered question is not a thread that ended (a still-open one is listed as open: it waits for the user);
  // one that became work is.
  const asked = [thread('07:00:00', 'q1', 'blocked', '要不要？'), thread('07:10:00', 'q1', 'done', 'status=done; 用户：要'),
    thread('07:20:00', 'q2', 'blocked', '推吗？'), thread('07:30:00', 'q2', 'in_progress', '在推'), thread('07:40:00', 'q2', 'released', 'ok'),
    thread('07:50:00', 'w', 'done', 'x')];
  assert.deepEqual(threadList(pm, [{ id: 'q1', pm: 'pm-dudu', title: 'Q1', status: 'done', updated: '2026-11-13 07:10' }], asked)
    .finished.map(r => r.task), ['w', 'q2']);

  // A thread that was given up is not listed, whether the log or the ledger says so, and takes none of the six places.
  const dropped = [thread('07:00:00', 'k', 'in_progress', 'started'), thread('07:10:00', 'k', 'abandoned', 'status=abandoned; superseded'),
    thread('07:20:00', 'l', 'done', 'x'), thread('07:30:00', 'n', 'merged', 'x')];
  assert.deepEqual(threadList(pm, [{ id: 't', pm: 'pm-dudu', title: 'Toast test (ignore)', status: 'abandoned', updated: '2026-11-13 09:00' },
    { id: 'n', pm: 'pm-dudu', title: 'N', status: 'abandoned', updated: '2026-11-13 09:10' }], dropped).finished.map(r => r.task), ['l']);
  assert.deepEqual(threadList(pm, [], [...many, thread('08:09:00', 'z', 'abandoned', 'x')]).finished.map(r => r.task),
    ['m8', 'm7', 'm6', 'm5', 'm4', 'm3']);

  // Names as the agents list reads them.
  assert.equal(sessionLabel({ title: '~/project/repos/dudu', program: claude }), 'Claude Code');
  assert.equal(sessionLabel({ title: '✳ me@host: ~', program: claude }), 'Claude Code');
  assert.equal(sessionLabel({ title: 'claude', program: claude, address: 't9' }), 'Claude Code');
  assert.equal(sessionLabel({ title: '', address: 't9' }), 't9');
  // Two agents in one named tab keep their own titles.
  const pair = threadList(pm, [], [], [{ address: 't1', state: 'live', cwd: '/r/dudu' }, { address: 't2', state: 'live', cwd: '/r/dudu' }],
    [{ address: 't1', status: 'idle', title: 'one', tab: 'tb3', program: claude, seq: 2 },
      { address: 't2', status: 'idle', title: 'two', tab: 'tb3', program: claude, seq: 1 }], tabs);
  assert.deepEqual(pair.sessions.map(r => r.label), ['one', 'two']);
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

test('a thread named as a link in a reply leads to that thread', () => {
  assert.equal(threadLink('thread:dudu-dev-thread-links'), 'dudu-dev-thread-links');
  assert.equal(threadLink(' Thread://dudu-x.2/ '), 'dudu-x.2');                    // as a renderer may hand it back
  assert.equal(threadLink('thread:%E7%9C%8B%E6%9D%BF-fix-2'), '看板-fix-2');        // a project folder in any script
  for (const other of ['https://herdr.dev/layouts', 'thread:', 'thread:../pms/dudu', 'thread:..%2Fpms%2Fdudu', 'thread:a/b',
    'thread:.hidden', 'thread:a..b', 'thread:%E0%A4%A', 'threads:x', '', null]) {
    assert.equal(threadLink(other), '', String(other));
  }
  // Folded, a reply shows the name without the link; open, the markdown keeps it for the renderer.
  const reply = '一件好了，一件还在做。\n\n- [线程列表](thread:dudu-list)：已合并。\n- [提问卡片](thread:dudu-card)：在审。';
  assert.deepEqual(lead('[线程列表](thread:dudu-list)合并了，已装好。'), { text: '线程列表合并了，已装好。', more: false });
  assert.deepEqual(lead(reply), { text: '一件好了，一件还在做。', more: true });
  assert.equal(model.viewMarkdown(reply), reply);
});

test('ages read as in the PM list', () => {
  assert.deepEqual([0, 59_000, 60_000, 3_600_000 * 3, 86_400_000 * 2].map(age), ['<1m', '<1m', '1m', '3h', '2d']);
  assert.equal(model.age.toString(), list.age.toString());
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
