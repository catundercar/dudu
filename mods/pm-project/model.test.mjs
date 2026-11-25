import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from './model.js';
import * as changeView from './change_view.js';
import * as searchMod from './search.js';
import * as stepsView from './steps.js';
import * as dash from '../pm-dash/model.js';
import * as list from '../pm-list/model.js';
import * as nav from '../pm-nav/model.js';

const { timeline, parseConversation, settlePending, bellTargets, bellStops, bellNext, threadQuestion, detailQuestion, askKey, foldReviews, bellThread, waitingCount, bellCount, answeredTasks, markAnswered, timelineRows, rowOf, riseAfterWheel, riseAfterJump, answerText, lead, turns, newestReply, threadList, sessionLabel, questionOnly, age, workingTasks, threadLink, logText, draftKey, draftText, readDrafts, keepDraft, DRAFT_LIMIT } = model;

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
  // The bell can go to both questions, the newest first.
  assert.deepEqual(bellTargets(all).map(i => all[i]), [items[4], items[2]]);
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
  assert.deepEqual(bellTargets(answered), []);
  const again = timeline([...events, thread('09:10:00', 'h', 'in_progress', 'answered'),
    thread('09:11:00', 'h', 'blocked', 'status=blocked; 还有一件', { options: ['好'] })], tasks);
  assert.deepEqual(again.filter(i => i.kind === 'question' && i.task === 'h').map(i => [i.text, i.open]),
    [['开工前要你定一件事：技能改动交给线程吗？', false], ['还有一件', true]]);
  // A blocked task with no open question has no card: the bell opens its thread (whose detail asks it).
  const blockedTasks = [{ id: 'r', title: 'R', status: 'blocked' }];
  const blocked = timeline([thread('09:00:00', 'r', 'in_progress', 'x')], blockedTasks);
  assert.deepEqual([bellTargets(blocked), bellStops(blocked, blockedTasks)], [[], [{ key: 'thread:r', thread: 'r' }]]);
  // Review is the PM's job: a review task alone gives the bell nothing.
  const review = timeline([thread('09:00:00', 'r', 'in_progress', 'x')], [{ id: 'r', title: 'R', status: 'review' }]);
  assert.equal(review[1].rows[0].waiting, false);
  assert.deepEqual(bellTargets(review), []);
});

test("the bell's number is the tasks that wait, not the places it can go", () => {
  // Three blocked tasks without a question shown share one thread group, but no card: the bell opens each one's thread.
  const pm = { name: 'pm-a' };
  const tasks = ['r', 's', 'u'].map(id => ({ id, title: id, status: 'blocked', pm: 'pm-a' }));
  const items = timeline(['r', 's', 'u'].map((id, n) => thread(`09:0${n}:00`, id, 'in_progress', 'x')), tasks);
  assert.deepEqual(bellStops(items, tasks, pm).map(s => s.thread), ['r', 's', 'u']);
  assert.deepEqual(bellStops(items, [...tasks, { id: 'v', status: 'blocked', pm: 'pm-b' }], pm).length, 3);
  assert.equal(waitingCount(pm, tasks), 3);
  assert.equal(threadList(pm, tasks, []).open.filter(r => r.group === 'waiting').length, 3);
  // Another project's tasks, and tasks that do not wait, are not this one's number.
  assert.equal(waitingCount(pm, [...tasks, { id: 'v', status: 'blocked', pm: 'pm-b' }, { id: 'w', status: 'review', pm: 'pm-a' }]), 3);
  assert.equal(waitingCount(null, null), 0);
  // pm.py's counts.waiting, when it gives one, is the number: the sidebar's badge shows the same.
  assert.equal(waitingCount({ ...pm, counts: { waiting: 4 } }, tasks), 4);
  assert.equal(waitingCount({ ...pm, counts: { waiting: 0 } }, tasks), 0);
  // An answer the coordinator has not taken in yet does not count: the bell goes down at once, before pm.py reads it.
  const asking = [thread('09:00:00', 'k', 'blocked', '限流用什么？', { options: ['Redis', '内存'] })];
  const k = [{ id: 'k', title: '限流', status: 'blocked', pm: 'pm-a' }];
  const held = timeline([...asking, ev('09:01:00', 'user', { text: answerText('限流', 'Redis') })], k);
  assert.deepEqual([[...answeredTasks(held)], bellTargets(held)], [['k'], []]);
  assert.equal(bellCount({ ...pm, counts: { waiting: 1 } }, k, answeredTasks(held)), 0);
  assert.equal(bellCount(pm, k, answeredTasks(held)), 0);
  // Once pm.py marks it answered, its count already leaves it out: it is not taken off twice.
  assert.equal(bellCount({ ...pm, counts: { waiting: 0 } }, [{ ...k[0], answered: true }], answeredTasks(held)), 0);
  assert.equal(waitingCount(pm, [{ ...k[0], answered: true }]), 0);
  assert.equal(threadList(pm, markAnswered(k, answeredTasks(held)), []).open.filter(r => r.group === 'waiting').length, 0);
});

test("a question card answered in the user's own words is answered, with or without options", () => {
  // The card's "own words" row sends the box's words after the card's 【title】 (answerText), as a
  // plain message: no `question` tag, files allowed. That alone makes the card answered.
  const pm = { name: 'pm-a' };
  const task = { id: 'k', title: '限流', status: 'blocked', pm: 'pm-a' };
  for (const options of [['Redis', '内存'], []]) {
    const asked = [thread('09:00:00', 'k', 'in_progress', 'x'), thread('09:01:00', 'k', 'blocked', '计数放在哪？', { options })];
    const said = answerText('限流', '都不要，先不限流');
    const look = opts => {
      const items = timeline(opts.events || asked, [task], opts), answered = answeredTasks(items);
      const card = items.find(i => i.kind === 'question');
      return { answered: [...answered], card: [card.open, card.chosen, Boolean(card.answered)], targets: bellTargets(items).length,
        bell: bellCount(pm, [task], answered), waiting: threadList(pm, markAnswered([task], answered), []).open.filter(r => r.group === 'waiting').length };
    };
    const waits = { answered: [], card: [true, -1, false], targets: 1, bell: 1, waiting: 1 };
    const quiet = { answered: ['k'], card: [true, -1, true], targets: 0, bell: 0, waiting: 0 };
    assert.deepEqual(look({}), waits);
    // In the log, or still on its way (with an attachment line after it): answered, no option picked.
    assert.deepEqual(look({ events: [...asked, ev('09:02:00', 'user', { text: said })] }), quiet);
    // Sent with a pasted screenshot, the log has its image mark first (pm.py's answered_tasks reads it the same).
    assert.deepEqual(look({ events: [...asked, ev('09:02:00', 'user', { text: `[Image #1]${said}` })] }), quiet);
    assert.deepEqual(look({ pending: [{ id: 1, text: `${said}\n\n附件：\n/tmp/a.png`, sentAt: 0 }] }), quiet);
    // The bubble shows the words as sent, title and all, as a quick answer's does.
    const bubble = timeline([...asked, ev('09:02:00', 'user', { text: said })], [task]).find(i => i.kind === 'user');
    assert.equal(bubble.text, '【限流】都不要，先不限流');
    // Not sent, or the same words without the title: it still waits.
    assert.deepEqual(look({ pending: [{ id: 1, text: said, sentAt: 0, failed: 'no' }] }), waits);
    assert.deepEqual(look({ events: [...asked, ev('09:02:00', 'user', { text: '都不要，先不限流' })] }), waits);
  }
});

test('a blocked task the conversation never shows asks in its thread, and its 【ledger title】 answers it', () => {
  // As appkit on 2026-11-15: a task blocked on 10-25, before the conversation log, under the project's old
  // name; the log has no thread event of it, so no card. It waits, and the bell opens its thread instead.
  const pm = { name: 'pm-appkit' };
  const ledger = { id: 'wb-ax', title: '辅助功能授权', project: 'OldName', status: 'blocked', pm: 'pm-appkit',
    latest: 'status=blocked; 要不要给 appkit 开辅助功能权限？' };
  const file = { ...ledger, options: ['现在开', '先不开'], option_notes: ['要重启一次', ''], recommended: true, log: [
    { at: '2026-10-25 10:00', by: 'hc:t9', text: 'registered (in_progress)' },
    { at: '2026-10-25 10:30', by: 'hc:t9', text: 'status=blocked; 要不要给 appkit 开辅助功能权限？' }] };
  const other = { id: 'x', title: '辅助功能授权', status: 'blocked', pm: 'pm-other' };   // another project, the same title
  const events = [thread('09:00:00', 'k', 'in_progress', 'x'), ev('09:01:00', 'pm', { text: '在做。', by: 'hc:t3b' })];
  const look = (opts = {}) => {
    const tasks = [ledger, other], items = timeline(opts.events || events, tasks, { pm: pm.name, ...opts });
    const answered = answeredTasks(items), marked = markAnswered(tasks, answered);
    return { items, answered: [...answered], bell: bellCount(pm, tasks, answered),
      stops: bellStops(items, tasks, pm), asks: threadQuestion({ ...marked[0], ...file }, items) };
  };
  // Waiting: no card in the conversation; the bell opens its thread; the detail asks the ledger's question.
  const waits = look();
  assert.equal(waits.items.some(i => i.kind === 'question'), false);
  assert.deepEqual([waits.answered, waits.bell, waits.stops], [[], 1, [{ key: 'thread:wb-ax', thread: 'wb-ax' }]]);
  assert.deepEqual(waits.asks, { key: askKey('wb-ax'), title: '辅助功能授权', text: '要不要给 appkit 开辅助功能权限？',
    options: ['现在开', '先不开'], notes: ['要重启一次', ''], recommended: true });
  // Answered with its 【ledger title】: in the log, picked on its way (tagged with its key), or in the user's own words.
  const quiet = r => [r.answered, r.bell, r.stops.length, r.asks];
  assert.deepEqual(quiet(look({ events: [...events, ev('09:02:00', 'user', { text: answerText('辅助功能授权', '现在开') })] })),
    [['wb-ax'], 0, 0, null]);
  assert.deepEqual(quiet(look({ pending: [{ id: 1, text: answerText('辅助功能授权', '先不开'), sentAt: 0, question: askKey('wb-ax') }] })),
    [['wb-ax'], 0, 0, null]);
  assert.deepEqual(quiet(look({ pending: [{ id: 1, text: '【辅助功能授权】等我回家再开\n\n附件：\n/tmp/a.png', sentAt: 0 }] })),
    [['wb-ax'], 0, 0, null]);
  // Not sent, words that name nothing, or another project's title: it still waits.
  assert.deepEqual(look({ pending: [{ id: 1, text: '【辅助功能授权】现在开', sentAt: 0, question: askKey('wb-ax'), failed: 'no' }] }).bell, 1);
  assert.deepEqual(look({ events: [...events, ev('09:02:00', 'user', { text: '现在开' })] }).stops.length, 1);
  assert.deepEqual(look({ pm: 'pm-other', events: [...events, ev('09:02:00', 'user', { text: '【辅助功能授权】开' })] }).answered, ['x']);
  // pm.py's `answered` (it read the log first): the detail asks nothing more.
  assert.equal(threadQuestion({ ...ledger, ...file, answered: true }, events), null);

  // A note and nothing to pick: the detail shows the note, and only the own-words answer goes with it.
  const bare = { id: 'n', title: 'Window drag', status: 'blocked', pm: 'pm-appkit', latest: 'needs a decision on drag regions' };
  assert.deepEqual(threadQuestion(bare, []), { key: askKey('n'), title: 'Window drag', text: 'needs a decision on drag regions',
    options: [], notes: [], recommended: false });
  // Blocked with no note of its own: its latest entry.
  assert.equal(threadQuestion({ ...bare, log: [{ text: 'status=blocked' }, { text: '等用户看一下' }] }, []).text, '等用户看一下');
  // Not waiting: nothing to ask.
  assert.equal(threadQuestion({ ...bare, status: 'in_progress' }, []), null);

  // A task with a card in the conversation asks that card's question, under its key; once picked, nothing.
  const asked = [thread('09:00:00', 'k', 'blocked', '计数放在哪？', { options: ['Redis', '内存'] })];
  const k = { id: 'k', title: '限流', status: 'blocked', pm: 'pm-appkit' };
  const items = timeline(asked, [k]), card = items.find(i => i.kind === 'question');
  assert.deepEqual(threadQuestion(k, items), { key: card.key, title: '限流', text: '计数放在哪？', options: ['Redis', '内存'],
    notes: ['', ''], recommended: false });
  assert.deepEqual(bellStops(items, [k], pm), [{ key: card.key, at: items.indexOf(card) }]);
  assert.equal(threadQuestion(k, timeline([...asked, ev('09:01:00', 'user', { text: '【限流】Redis' })], [k])), null);
});

test('a blocked task without a card is answered only after the ledger asked, and a note does not ask again', () => {
  // asked_at: when the ledger last asked (pm.py state). Its question is older than the events shown.
  const pm = { name: 'pm-a' };
  const task = { id: 'w', title: '窗口', status: 'blocked', pm: 'pm-a', asked_at: '2026-11-13 10:00', latest: 'status=blocked; 要不要拖动？' };
  const look = events => {
    const items = timeline(events, [task], { pm: 'pm-a' }), answered = answeredTasks(items);
    return { answered: [...answered], cards: items.filter(i => i.kind === 'question').length, stops: bellStops(items, [task], pm).length,
      bell: bellCount(pm, [task], answered) };
  };
  const answer = ev('10:05:00', 'user', { text: '【窗口】先不做' });
  // Said before the ledger asked (an answer to an older question of that title, say in another project's log): not this one.
  assert.deepEqual(look([ev('09:00:00', 'user', { text: '【窗口】先不做' })]), { answered: [], cards: 0, stops: 1, bell: 1 });
  assert.deepEqual(look([answer]), { answered: ['w'], cards: 0, stops: 0, bell: 0 });
  // A note on it afterwards (pm.py log, update --note: the log shows it blocked, asking nothing): still answered, no card.
  const noted = thread('10:10:00', 'w', 'blocked', '等用户回家再开', { title: '窗口' });
  assert.deepEqual(look([answer, noted]), { answered: ['w'], cards: 0, stops: 0, bell: 0 });
  // A new status=blocked asks again: a card, unanswered.
  const again = thread('10:10:00', 'w', 'blocked', 'status=blocked; 还有一件', { title: '窗口' });
  assert.deepEqual(look([answer, again]), { answered: [], cards: 1, stops: 1, bell: 1 });
  // Registered blocked in the log (its first event, no later than the ledger's question): that is the question.
  const registered = thread('10:00:00', 'w', 'blocked', '要不要拖动？', { title: '窗口' });
  assert.deepEqual(look([registered]).cards, 1);
});

test("a thread whose review waits asks the review's question, not its own answered one", () => {
  // The task's own log has an old status=blocked the user answered long ago; its review is blocked now.
  const own = { id: 'p', title: '拖窗口', status: 'in_progress', pm: 'pm-a', latest: 'doing it' };
  const review = { id: 'p-review', title: '审查拖窗口', status: 'blocked', pm: 'pm-a', review_of: 'p', latest: 'status=blocked; 合并前要不要再跑一遍？' };
  const file = { ...own, log: [{ at: '2026-11-13 08:00', text: 'status=blocked; 用哪个 API？' }, { at: '2026-11-13 09:00', text: 'doing it' }] };
  const folded = foldReviews([own, review]).find(t => t.id === 'p');
  assert.equal(folded.status, 'blocked');
  const asks = detailQuestion(folded, own, file, []);
  assert.deepEqual([asks.key, asks.text], [askKey('p-review'), '合并前要不要再跑一遍？']);
  // The same key the bell stops at, so answering it in the box's own words is kept (see bellStops).
  assert.deepEqual(bellStops([], [own, review], { name: 'pm-a' }), [{ key: 'thread:p-review', thread: 'p-review' }]);
  // The bell opens the task it reviews, and a second click, with that detail open, leaves it open.
  const stop = bellStops([], [own, review], { name: 'pm-a' })[0], list = foldReviews([own, review]);
  assert.deepEqual([bellThread(stop, list), bellThread(stop, list, 'p'), bellThread(stop, list, 'q')], ['p', '', 'p']);
  assert.equal(bellThread({ key: 'k', at: 3 }, list), '');
  // The review answered: nothing to ask; the task itself blocked: its own question.
  assert.equal(detailQuestion(foldReviews([own, { ...review, answered: true }]).find(t => t.id === 'p'), own, file, []), null);
  const blocked = { ...own, status: 'blocked' };
  assert.equal(detailQuestion(foldReviews([blocked, review]).find(t => t.id === 'p'), blocked, { ...file, status: 'blocked' }, []).key, askKey('p'));
});

test('an answered question waits for the coordinator, not for the user, until it asks again', () => {
  const pm = { name: 'pm-a' };
  const task = { id: 'k', title: '限流', status: 'blocked', pm: 'pm-a', latest: '计数放在哪？' };
  const asked = [thread('09:00:00', 'k', 'in_progress', 'x'), thread('09:01:00', 'k', 'blocked', '计数放在哪？', { options: ['Redis', '内存'] })];
  const look = (events, tasks = [task], opts = {}) => {
    const items = timeline(events, tasks, opts), answered = answeredTasks(items);
    const row = threadList(pm, markAnswered(tasks, answered), events).open[0];
    const line = items.find(i => i.kind === 'threads').rows[0];
    return { answered: [...answered], bell: bellCount(pm, tasks, answered), targets: bellTargets(items).length,
      row: [row.group, row.waiting, row.tone, model.statusLabel('zh', row.status, false, false, row.answered)],
      line: [line.waiting, line.tone, Boolean(line.answered)] };
  };
  // Not answered: it waits as before.
  assert.deepEqual(look(asked), { answered: [], bell: 1, targets: 1, row: ['waiting', true, 'blocked', '阻塞'], line: [true, 'blocked', false] });
  // A picked option (in the log, or still on its way) or words that start with its 【title】: answered, quietly.
  const quiet = { answered: ['k'], bell: 0, targets: 0, row: ['working', false, 'quiet', '已回答'], line: [false, 'quiet', true] };
  const picked = [...asked, ev('09:02:00', 'user', { text: answerText('限流', 'Redis') })];
  assert.deepEqual(look(picked), quiet);
  const card = timeline(asked, [task]).find(i => i.kind === 'question');
  assert.deepEqual(look(asked, [task], { pending: [{ id: 1, text: '【限流】内存', sentAt: 0, question: card.key }] }), quiet);
  assert.deepEqual(look([...asked, ev('09:02:00', 'user', { text: '【限流】先用内存，以后再换' })]), quiet);
  // Not sent, or words that name no question: still waiting.
  assert.deepEqual(look(asked, [task], { pending: [{ id: 1, text: '【限流】内存', sentAt: 0, question: card.key, failed: 'no' }] }).bell, 1);
  assert.deepEqual(look([...asked, ev('09:02:00', 'user', { text: '用 Redis 吧' })]).bell, 1);
  // A reply of the coordinator in between changes nothing: it is answered until the coordinator moves the task on.
  assert.deepEqual(look([...picked, ev('09:03:00', 'pm', { text: '收到，稍等。', by: 'hc:t3b' })]), quiet);
  // The coordinator moved it on: it shows what it is now.
  const moved = [...picked, thread('09:04:00', 'k', 'in_progress', '用户选 Redis')];
  assert.deepEqual(look(moved, [{ ...task, status: 'in_progress' }]).row, ['working', false, 'running', '进行中']);
  // Blocked again, a new question: it waits again, and the earlier answer does not answer it.
  const again = [...moved, thread('09:05:00', 'k', 'blocked', 'Redis 连哪个实例？', { options: ['本机', '集群'] })];
  assert.deepEqual(look(again), { answered: [], bell: 1, targets: 1, row: ['waiting', true, 'blocked', '阻塞'], line: [true, 'blocked', false] });
  assert.deepEqual(look([...again, ev('09:06:00', 'user', { text: answerText('限流', '集群') })]), quiet);
  // Asked again while still blocked (`update --status blocked`, or new --option): a new card, and it waits again.
  for (const ask of [thread('09:04:00', 'k', 'blocked', 'status=blocked; Redis 连哪个实例？', { options: ['本机', '集群'] }),
    thread('09:04:00', 'k', 'blocked', 'status=blocked; Redis 连哪个实例？'), thread('09:04:00', 'k', 'blocked', '连哪个？', { options: ['本机', '集群'] })]) {
    const reasked = [...picked, ask];
    assert.deepEqual(look(reasked), { answered: [], bell: 1, targets: 1, row: ['waiting', true, 'blocked', '阻塞'], line: [true, 'blocked', false] });
    const cards = timeline(reasked, [task]).filter(i => i.kind === 'question');
    assert.deepEqual(cards.map(c => [c.open, c.chosen]), [[false, 0], [true, -1]]);
    assert.deepEqual(look([...reasked, ev('09:05:00', 'user', { text: answerText('限流', '集群') })]), quiet);
  }
  // A plain note on the blocked task asks nothing: still answered.
  assert.deepEqual(look([...picked, thread('09:04:00', 'k', 'blocked', '已转给 worker')]), quiet);
  assert.deepEqual([model.asksAgain({ text: 'status=blocked; x' }), model.asksAgain({ text: 'x', options: ['', ' '] }), model.asksAgain({ text: 'status=blockedx' })],
    [true, false, false]);
  // pm.py's `answered` (an answer older than the events shown) is answered too.
  const marked = { ...task, answered: true };
  const fromLedger = timeline([thread('09:00:00', 'k', 'in_progress', 'x')], [marked]);
  assert.deepEqual([[...answeredTasks(fromLedger)], bellTargets(fromLedger), fromLedger[1].rows[0].tone], [['k'], [], 'quiet']);
  assert.deepEqual(look(asked, [marked]).row, ['working', false, 'quiet', '已回答']);
  // The words, both languages; Answered is only ever a blocked task's.
  assert.equal(model.statusLabel('en', 'blocked', false, false, true), 'Answered');
  assert.equal(model.statusLabel('zh', 'blocked', false, false, true), '已回答');
  assert.equal(model.statusLabel('zh', 'review', false, false, true), '审查中');
  assert.equal(model.tone('blocked', false, false, true), 'quiet');
  assert.equal(model.tone('blocked'), 'blocked');
});

test('a task that enters the log as a question is that question alone', () => {
  // `pm.py new --status blocked --option …`: the coordinator asks; there is no work to show a row for.
  const events = [thread('09:00:00', 'sound', 'blocked', 'PM 的通知要不要带声音？', { options: ['带声音', '不带声音'] }),
    thread('09:00:00', 'push', 'blocked', '要不要推到 GitHub？')];
  const waiting = timeline(events, [{ id: 'sound', title: '通知声音', status: 'blocked' }, { id: 'push', title: '推送', status: 'blocked' }]);
  assert.deepEqual(waiting.map(i => [i.kind, i.open]), [['day', undefined], ['question', true], ['question', true]]);
  assert.deepEqual(bellTargets(waiting), [2, 1]);
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

test('the bell steps through what waits, and leaves out what the coordinator is reading the answer to', () => {
  // Three questions at once, as on 2026-11-13; one more task is blocked from before the events shown.
  const asked = [
    thread('23:00:00', 'old', 'in_progress', 'started'),
    thread('23:23:24', 'sound', 'blocked', 'PM 的通知要不要带声音？', { title: '通知声音', options: ['带声音', '不带声音'] }),
    thread('23:23:25', 'push', 'blocked', '要不要推到 GitHub 并装到 MBP？', { title: '推送', options: ['推并装', '先不推'] }),
    thread('23:23:26', 'clear', 'blocked', '要不要清掉 PM-superagent？', { title: '清理', options: ['清掉', '留着'] }),
    ev('23:23:30', 'pm', { text: '有三件事等你定。', by: 'hc:t3b' }),
  ];
  const blocked = id => ({ id, pm: 'pm-dudu', title: { sound: '通知声音', push: '推送', clear: '清理', old: '旧的一件' }[id], status: 'blocked' });
  const state = { tasks: ['old', 'sound', 'push', 'clear'].map(blocked) };
  const bell = (events, tasks = state.tasks, opts = {}) => {
    const items = timeline(events, tasks, opts), stops = bellStops(items, tasks, { name: 'pm-dudu' });
    return { items, held: [...answeredTasks(items)].sort(), stops, targets: bellTargets(items), at: stops.map(s => s.thread || items[s.at].task) };
  };
  // Nothing answered: every blocked task can be reached, newest first; the old one, with no card, by opening its
  // thread. The bell's number is how many places it can go to.
  const first = bell(asked);
  assert.deepEqual([first.held, first.at], [[], ['clear', 'push', 'sound', 'old']]);
  // Click after click: the newest, then the next older one, and round again after the oldest.
  const visit = (b, clicks, last = null) => {
    const seen = [];
    for (let n = 0; n < clicks; n++) {
      const next = bellNext(b.stops, last);
      last = { key: next.key, seen: b.stops.map(s => s.key) };
      seen.push(next.thread || b.items[next.at].task);
    }
    return { seen, last };
  };
  assert.deepEqual(visit(first, 6).seen, ['clear', 'push', 'sound', 'old', 'clear', 'push']);
  assert.equal(bellNext([], null), null);
  assert.deepEqual(first.stops.at(-1), { key: 'thread:old', thread: 'old' });

  // The user went to the first and picked one of its answers: at once (the bubble is still on its way) that question
  // is in the coordinator's hands, the bell no longer counts it, and the next click goes on to the next one.
  const one = visit(first, 1);
  const card = first.items.find(i => i.kind === 'question' && i.task === 'clear');
  const picking = bell(asked, state.tasks, { pending: [{ id: 1, text: '【清理】清掉', sentAt: 0, question: card.key }] });
  assert.deepEqual([picking.held, picking.at], [['clear'], ['push', 'sound', 'old']]);
  assert.equal(bellCount({ name: 'pm-dudu' }, state.tasks, answeredTasks(picking.items)), 3);
  assert.deepEqual(visit(picking, 4, one.last).seen, ['push', 'sound', 'old', 'push']);
  // The same once the quick answer is in the log; the other questions still wait (it answered only its own).
  const picked = [...asked, ev('23:30:00', 'user', { text: '【清理】清掉' })];
  assert.deepEqual([bell(picked).held, bell(picked).at], [['clear'], ['push', 'sound', 'old']]);
  // A quick answer that could not be sent answered nothing.
  assert.equal(bell(asked, state.tasks, { pending: [{ id: 1, text: '【清理】清掉', sentAt: 0, question: card.key, failed: 'no terminal' }] }).stops.length, 4);
  // The coordinator replied and the task is still blocked: still answered; it waits again only once asked again.
  const replied = bell([...picked, ev('23:31:00', 'pm', { text: '在处理了。', by: 'hc:t3b' })]);
  assert.deepEqual([replied.held, replied.at], [['clear'], ['push', 'sound', 'old']]);

  // Words of the user's own name no question, so they hold none: they may be about something else ("also rename
  // the button"), and even an answer to all three ("推并装，superagent 清掉，不带声音") is not known to be one.
  const said = bell([...asked, ev('03:12:04', 'user', { text: '推并装，superagent 清掉，不带声音' })]);
  assert.deepEqual([said.held, said.at], [[], ['clear', 'push', 'sound', 'old']]);
  // Words that start with a question's 【title】 answer that question, typed as well as picked, in the log or on their way.
  const byName = bell([...asked, ev('03:12:04', 'user', { text: '【推送】推并装，另外把按钮改个名' })]);
  assert.deepEqual([byName.held, byName.at], [['push'], ['clear', 'sound', 'old']]);
  assert.deepEqual(bell(asked, state.tasks, { pending: [{ id: 2, text: '【通知声音】不要声音', sentAt: 0 }] }).held, ['sound']);
  // The coordinator took one answer and closed its task; the others wait on.
  const tookOne = bell([...asked, ev('03:12:04', 'user', { text: '【推送】推并装' }), thread('03:15:32', 'push', 'released', 'ok'),
    ev('03:15:40', 'pm', { text: '推了。', by: 'hc:t3b' })], [blocked('old'), blocked('sound'), { ...blocked('push'), status: 'released' }, blocked('clear')]);
  assert.deepEqual([tookOne.held, tookOne.at], [[], ['clear', 'sound', 'old']]);
  // A question that arrives after the last click: the bell starts at the newest again, not where it was.
  const more = [...asked, thread('23:40:00', 'name', 'blocked', '叫什么？', { title: '命名' })];
  const grown = bell(more, [...state.tasks, { ...blocked('name'), title: '命名' }]);
  assert.deepEqual(visit(grown, 2, visit(first, 2).last).seen, ['name', 'clear']);
  // Each question is a row of its own in the scroll area, though the three were asked in one turn: the bell
  // can only ask for a row, and a turn as one tall row would be the same place for all three.
  const rows = timelineRows(turns(first.items, 'hc:t3b'));
  assert.deepEqual(rows.map(r => [r.kind, r.first, r.parts?.map(p => p.kind).join('+')]), [
    ['day', undefined, undefined], ['turn', true, 'pm'], ['turn', false, 'threads'], ['turn', false, 'question'],
    ['turn', false, 'question'], ['turn', false, 'question']]);
  assert.deepEqual(first.targets.map(i => rowOf(rows, first.items[i])), [5, 4, 3]);
  assert.equal(new Set(rows.map(r => r.key)).size, rows.length);
  assert.equal(rowOf(rows, first.items[0]), -1);          // a day is no part of a turn
  // Thread names stay with their reply on the turn's first row; a turn without a reply starts with its first part.
  const named = timeline([thread('09:00:00', 'a', 'in_progress', 'x'), ev('09:01:00', 'pm', { text: '开了', by: 'hc:t3b' }),
    thread('09:02:00', 'a', 'review', 'status=review', { by: 'hc:t3b' }), ev('09:03:00', 'pm', { text: 'A 待审', by: 'hc:t3b' }),
    thread('09:04:00', 'b', 'in_progress', 'y')], []);
  assert.deepEqual(timelineRows(turns(named, 'hc:t3b')).map(r => [r.first, r.bare, r.parts?.map(p => p.kind).join('+')]), [
    [undefined, undefined, undefined], [true, false, 'pm'], [false, false, 'threads'], [true, false, 'about+pm'], [true, true, 'threads']]);
  // One thing waiting: every click goes to it.
  const single = bell([asked[1], asked[4]], [blocked('sound')]);
  assert.deepEqual([visit(single, 3).seen, single.stops.length], [['sound', 'sound', 'sound'], 1]);
});

test('the view keeps count of how far above the end the reader is, and errs toward following', () => {
  const view = 800;
  // The wheel: up leaves the end, down comes back three times as fast.
  assert.equal(riseAfterWheel(0, 300, 2000, view), 300);
  assert.equal(riseAfterWheel(300, -60, 2000, view), 120);
  assert.equal(riseAfterWheel(300, -100, 2000, view), 0);
  assert.equal(riseAfterWheel(0, -500, 2000, view), 0);
  // Where nothing can move, nothing is counted: a conversation shorter than the area, or the top.
  assert.equal(riseAfterWheel(0, 500, 0, view), 0);
  assert.equal(riseAfterWheel(0, 500, -300, view), 0);
  assert.equal(riseAfterWheel(350, 1000, 400, view), 400);
  // Never more than two screens, however far up the reader went: one long scroll down is back at the end.
  assert.equal(riseAfterWheel(0, 9000, 20000, view), 1600);
  assert.equal(riseAfterWheel(1600, -540, 20000, view), 0);

  // A jump from the bell. Rows of 100, 200, 300, 150 and 120 px, 28 px after the last, in an area of 500.
  const heights = [100, 200, 300, 150, 120], jump = (rise, at) => riseAfterJump(rise, heights, at, 500, 28);
  // From the end: the last rows are in view, so nothing moves and the reader is still at the end.
  assert.deepEqual([jump(0, 4), jump(0, 3)], [0, 0]);
  // A row above the area comes to its top: the reader is that far from the end.
  assert.deepEqual([jump(0, 2), jump(0, 1), jump(0, 0)], [98, 298, 398]);
  // From up there: a row in view moves nothing, one below comes to the area's bottom, and the last row is the end.
  assert.deepEqual([jump(398, 1), jump(398, 0), jump(398, 3), jump(398, 4)], [398, 398, 148, 0]);
  // Heights not measured yet (the first frames): a jump counts as a screen, except to the last row.
  assert.deepEqual([riseAfterJump(0, [100, 0, 300], 0, 500, 28), riseAfterJump(0, [100, 0, 300], 2, 500, 28)], [500, 0]);
  assert.deepEqual([riseAfterJump(40, [100, 200], 0, 0, 28), riseAfterJump(40, [100, 200], 1, 0, 28)], [40, 40]);
  assert.equal(riseAfterJump(0, [100, 200], 0, 0, 28), 1);
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

test('a thread row says it waits for exactly the tasks the board counts as waiting', () => {
  const state = {
    lang: 'en',
    pms: [{ name: 'pm-dudu', project: 'dudu' }, { name: 'pm-wb', project: 'wb' }],
    tasks: [
      { id: '1', pm: 'pm-dudu', status: 'blocked' }, { id: '2', pm: 'pm-dudu', status: 'review' },
      { id: '3', pm: 'pm-dudu', status: 'in_progress' }, { id: '4', pm: 'pm-wb', status: 'review' },
      { id: '5', pm: 'pm-dudu', status: 'merged', cleanup: true }, { id: '6', pm: 'pm-wb', status: 'paused' },
    ],
  };
  // Blocked only (review is the PM's job), as on the board.
  const items = timeline(state.tasks.map((t, i) => thread(`09:0${i}:00`, t.id, 'in_progress', 'x')), state.tasks);
  assert.deepEqual(items[1].rows.filter(r => r.waiting).map(r => r.task), ['1']);
  assert.equal(items[1].rows.filter(r => r.waiting).length, dash.counts(state).waiting);
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
  assert.deepEqual(model.sendArgv('t2h', 'hi'), ['hc', 'send', '--', 't2h', 'hi']);
  assert.deepEqual(model.sendArgv('t2h', '- item'), ['hc', 'send', '--', 't2h', '- item']);
  // Unix keeps env -u so the PM hook records the person; Windows has no env and runs hc bare.
  assert.deepEqual(model.withoutTerminalEnv(model.sendArgv('t2h', 'hi')),
    ['env', ['-u', 'HC_TERMINAL_ID', 'hc', 'send', '--', 't2h', 'hi']]);
  assert.deepEqual(model.withoutTerminalEnv(model.sendArgv('t2h', 'hi'), { platform: 'windows' }),
    ['hc', ['send', '--', 't2h', 'hi']]);
  assert.deepEqual(model.withoutTerminalEnv(model.putArgv('dev/t1', 'a.png'), { platform: 'windows' }),
    ['hc', ['put', '--json', '--', 'dev/t1', 'a.png']]);
  assert.deepEqual(model.withoutTerminalEnv(model.reattachArgv('/app/pm.py', 'x'), { unset: model.REATTACH_ENV }),
    ['env', ['-u', 'HC_TERMINAL_ID', '-u', 'HERDR_PANE_ID', 'python3', '/app/pm.py', 'reattach', 'x']]);
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

// 2026-11-15: the thread「审查：标题栏拖动窗口」(t5h, a sub-agent of the dudu PM t52, made a moment
// before and without a pane of its own) opened OldName, the appkit PM's space, whose
// t5c/t5g sit next to it by address. The terminal was found right; agent.focus on a paneless
// terminal switched no tab, so showing the work column revealed the space that happened to be active.
const t52Program = terms => terms.find(t => t.address === 't52').program;
function windowDragIncident() {
  const claude = { key: 'claude', name: 'Claude Code', agent: true };
  const terms = [
    { address: 't52', state: 'live', labels: { pm: 'dudu' }, program: claude },
    { address: 't5c', state: 'live', labels: { pm: 'appkit' }, program: claude },
    { address: 't5g', state: 'live', labels: { task: 'appkit-pairing-redesign' }, parent: 't5c', program: claude },
    { address: 't5h', state: 'live', labels: { task: 'dudu-window-drag-review', where: 'pm-hub / PM-dudu' }, parent: 't52', program: claude },
  ];
  // Each PM has a pane in its own space; neither sub-agent has one, so agents() lists neither.
  const panes = [{ pane: 'p1', terminal: 't52', space: 'pm-hub' }, { pane: 'p2', terminal: 't5c', space: 'OldName' }];
  const agents = [{ address: 't52', pane: 'p1', space_name: 'pm-hub', status: 'working' },
    { address: 't5c', pane: 'p2', space_name: 'OldName', status: 'done' }];
  const task = { id: 'dudu-window-drag-review', pane: 'hc:t5h', status: 'in_progress' };
  return { terms, panes, agents, task, paned: [...panes.map(p => p.terminal), ...agents.map(a => a.address)] };
}

test('a thread on a sub-agent without a pane opens that terminal over its own PM\'s space, never another project\'s', () => {
  const { terms, paned, task } = windowDragIncident();
  const terminal = model.terminalFor(model.taskRow(task), terms);
  assert.equal(terminal.address, 't5h');
  assert.equal(model.terminalAction(terminal, { offline: false, pane: task.pane }), 'open');
  // Its PM's pane comes up (pm-hub), then t5h is peeked over it — the way Herdr's agents list opens one.
  assert.deepEqual(model.focusPlan('t5h', terms, paned), { focus: 't52', peek: 't5h' });
  // Order does not matter, and the neighbour by address is never involved.
  assert.deepEqual(model.focusPlan('t5h', [...terms].reverse(), [...paned].reverse()), { focus: 't52', peek: 't5h' });
  assert.deepEqual(model.focusPlan('t5g', terms, paned), { focus: 't5c', peek: 't5g' });
  // Once it has a pane it is focused there; a PM with a pane is focused as itself.
  assert.deepEqual(model.focusPlan('t5h', terms, [...paned, 't5h']), { focus: 't5h', peek: '' });
  assert.deepEqual(model.focusPlan('t52', terms, paned), { focus: 't52', peek: '' });
  // No pane up its chain (its PM rotated out and closed; a worker started with --outlive-parent goes on):
  // it is peeked over its project's current PM, when that one has a pane.
  const rotated = terms.map(t => (t.address === 't52' ? { ...t, state: 'exited' } : t)).concat(
    { address: 't5p', state: 'live', labels: { pm: 'dudu' }, program: t52Program(terms) });
  assert.deepEqual(model.focusPlan('t5h', rotated, ['t5c', 't5p'], 't5p'), { focus: 't5p', peek: 't5h' });
  // Another PM terminal still labeled pm=dudu (not the current `home` t5p): passed over for the current PM,
  // so the thread is not shown on a tab inviting talk to the old PM.
  const otherPmTerms = terms.concat({ address: 't5p', state: 'live', labels: { pm: 'dudu' } });
  assert.deepEqual(model.focusPlan('t5h', otherPmTerms, [...paned, 't5p'], 't5p'), { focus: 't5p', peek: 't5h' });
  // Another PM terminal without a current one with a pane: nothing, rather than its tab.
  assert.deepEqual(model.focusPlan('t5h', otherPmTerms, paned, 't5p'), { focus: '', peek: '' });
  // A live ancestor that is no PM comes first (a worker's own sub-agent): the current PM is the fallback only.
  const nested = [{ address: 't52', labels: { pm: 'dudu' } }, { address: 't5q', parent: 't52', labels: { task: 'dudu-a' } },
    { address: 't5r', parent: 't5q' }];
  assert.deepEqual(model.focusPlan('t5r', nested, ['t52', 't5q'], 't52'), { focus: 't5q', peek: 't5r' });
  // The current PM as the ancestor is used as it is.
  assert.deepEqual(model.focusPlan('t5h', terms, paned, 't52'), { focus: 't52', peek: 't5h' });
  // Neither has a pane (or a cycle, or nothing asked): nothing at all — no peek over whatever space is active.
  const nothing = { focus: '', peek: '' };
  assert.deepEqual(model.focusPlan('t5h', rotated, ['t5c'], 't5p'), nothing);
  assert.deepEqual(model.focusPlan('t5h', rotated, ['t5c']), nothing);
  assert.deepEqual(model.focusPlan('t5h', [{ address: 't5h', parent: 't5x' }, { address: 't5x', parent: 't5h' }], ['t5c']), nothing);
  assert.deepEqual(model.focusPlan('', terms, paned), nothing);
});

test('the thread\'s terminal icon runs pane.focus on its PM, shows work, then peeks the thread — no agent.focus', async () => {
  const { terms, panes, agents, task } = windowDragIncident();
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '').replace('export default class PmProject extends View', 'return class');
  const calls = [];
  const View = class {};
  const stubs = { focusPlan: model.focusPlan, onMachine: model.onMachine, terminals: () => terms, panes: () => panes, agents: () => agents,
    run: (name, args) => calls.push([name, args]) };
  // Every other import is a do-nothing stand-in: only the click's own commands matter here.
  const blank = new Proxy(function () {}, { get: (_, key) => (key === Symbol.toPrimitive ? () => 0 : blank), apply: () => blank });
  const scope = new Proxy({ View, ...stubs }, {
    has: (target, name) => name in target || !(name in globalThis),
    get: (target, name) => (name in target ? target[name] : name === Symbol.unscopables ? undefined : blank),
  });
  const Mod = new Function('scope', `with (scope) { ${source} }`)(scope);
  const view = pm => Object.assign(Object.create(Mod.prototype), { pmTerminal: () => (pm ? { address: pm } : null) });
  view('t52').focusTerminal(model.terminalFor(model.taskRow(task), terms).address);
  assert.deepEqual(calls, [['pane.focus', { terminal: 't52' }], ['layout.select', { stack: 'pm-stage', child: 'work' }],
    ['terminal.peek', { terminal: 't5h' }]]);
  assert.ok(!calls.some(([, args]) => ['t5c', 't5g'].includes(args.terminal)));
  // Its PM closed after a rotation: shown over the project's current PM t5p.
  calls.length = 0;
  terms[0] = { ...terms[0], state: 'exited' };
  panes.splice(0, 1, { pane: 'p3', terminal: 't5p', space: 'pm-hub' });
  agents.splice(0, 1, { address: 't5p', pane: 'p3' });
  view('t5p').focusTerminal('t5h');
  assert.deepEqual(calls.map(([name, args]) => [name, args.terminal || args.child]),
    [['pane.focus', 't5p'], ['layout.select', 'work'], ['terminal.peek', 't5h']]);
  // No PM with a pane either: nothing runs, the stage stays.
  calls.length = 0;
  view('').focusTerminal('t5h');
  assert.deepEqual(calls, []);
});

test('sessions list excludes PM terminals and exited terminals, while keeping unlabelled project sessions', () => {
  const claude = { key: 'claude', name: 'Claude Code', agent: true };
  const terms = [
    { address: 't3k', state: 'live', cwd: '/r/dudu', labels: { pm: 'dudu' }, program: claude },
    { address: 't3b', state: 'exited', cwd: '/r/dudu', labels: {}, program: claude },
    { address: 't1h', state: 'live', cwd: '/r/dudu', labels: {}, program: claude },
  ];
  const live = [{ address: 't3b', status: 'idle', title: 'Old PM', tab: 'tb1', program: claude, seq: 9 },
    { address: 't1h', status: 'working', title: '改项目视图', tab: 'tb2', program: claude, seq: 5 },
    { address: 't3k', status: 'working', title: 'PM', tab: 'tb3', program: claude, seq: 7 }];
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', worktrees: '/w/dudu', pane: 'hc:t3k' };
  assert.deepEqual(threadList(pm, [], [], terms, live, []).sessions.map(row => row.address), ['t1h']);
  assert.equal(model.terminalFor(model.pmRow(pm), terms).address, 't3k');
  // Another live terminal without the `pm` label is an ordinary project session.
  const unlabeled = terms.map(term => (term.address === 't3b' ? { ...term, state: 'live', labels: {} } : term));
  assert.deepEqual(threadList(pm, [], [], unlabeled, live, []).sessions.map(row => row.address), ['t1h', 't3b']);
  const stale = model.pmRow({ ...pm, pane: 'hc:t3b' }), gone = terms.filter(term => term.address !== 't3k');
  assert.equal(model.terminalFor(stale, gone), undefined);
  assert.equal(model.terminalTargetFor(stale, gone).terminal.address, 't1h');
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

test('a draft is kept per box as it is typed and read back when the view starts again', () => {
  const main = draftKey('pm', 'pm-dudu'), thread = draftKey('thread', 'dudu-x');
  assert.deepEqual([main, thread, draftKey('pm', ''), draftKey('thread', '')], ['pm:pm-dudu', 'thread:dudu-x', '', '']);
  // Typing: each change replaces the box's draft; another box keeps its own.
  let drafts = keepDraft({}, main, '这个问', 1000);
  drafts = keepDraft(drafts, main, '这个问题\n第二行 ', 2000);
  drafts = keepDraft(drafts, thread, 'only for the thread', 3000);
  assert.deepEqual(drafts, { [main]: { text: '这个问题\n第二行 ', at: 2000 }, [thread]: { text: 'only for the thread', at: 3000 } });
  // What is written is what a new view reads: the text comes back exactly, per box.
  const again = readDrafts(JSON.stringify(drafts));
  assert.deepEqual(again, drafts);
  assert.deepEqual([draftText(again, main), draftText(again, thread), draftText(again, draftKey('pm', 'pm-other')), draftText(again, '')],
    ['这个问题\n第二行 ', 'only for the thread', '', '']);
  // Nothing new, nothing to write: the same object comes back.
  assert.equal(keepDraft(drafts, main, '这个问题\n第二行 ', 9000), drafts);
  assert.equal(keepDraft(drafts, '', 'no box', 9000), drafts);
  assert.equal(keepDraft(drafts, draftKey('pm', 'pm-other'), ' \n', 9000), drafts);
  // Sent (or emptied): that box's draft goes, the other stays.
  const sent = keepDraft(drafts, main, '', 4000);
  assert.deepEqual(sent, { [thread]: { text: 'only for the thread', at: 3000 } });
  assert.deepEqual(keepDraft(sent, thread, '  \n ', 5000), {});
  assert.deepEqual(keepDraft(sent, thread, null, 5000), {});
  // The newest few stay: a thread that ended with words in its box does not grow the store for ever.
  let many = {};
  for (let i = 0; i < DRAFT_LIMIT + 5; i++) many = keepDraft(many, draftKey('thread', `t${i}`), `draft ${i}`, i);
  assert.equal(Object.keys(many).length, DRAFT_LIMIT);
  assert.deepEqual([draftText(many, 'thread:t4'), draftText(many, 'thread:t5'), draftText(many, `thread:t${DRAFT_LIMIT + 4}`)],
    ['', 'draft 5', `draft ${DRAFT_LIMIT + 4}`]);
  // A store that is missing, torn or of another shape reads as no drafts, and entries without words are dropped.
  for (const bad of [null, undefined, '', '{"pm:x":', 'null', '[1]', '"text"', '7']) assert.deepEqual(readDrafts(bad), {});
  assert.deepEqual(readDrafts('{"pm:a":{"text":"hi"},"pm:b":{"text":"  "},"pm:c":"bare","pm:d":null,"pm:e":{"text":7}}'),
    { 'pm:a': { text: 'hi', at: 0 } });
});

test('a box\'s attachments: added once each, removed one by one, and only real paths', () => {
  const { withFiles, withoutFile, fileName, isImage, pasteName, attachmentsDir } = model;
  let files = withFiles([], ['/Users/me/Desktop/shot.png', '/Users/me/a b/报告.pdf']);
  // Dropping the same file again, or a second drop with a new one: each path once, in the order it came.
  files = withFiles(files, ['/Users/me/Desktop/shot.png', '/tmp/x/log.txt']);
  assert.deepEqual(files, ['/Users/me/Desktop/shot.png', '/Users/me/a b/报告.pdf', '/tmp/x/log.txt']);
  // What is not a file's absolute path does not attach: a relative one, a folder's trailing slash, a command.
  assert.deepEqual(withFiles(files, ['', 'shot.png', '/clear', '/model opus', '/tmp/dir/', null, 7]), files);
  assert.deepEqual(withoutFile(files, '/Users/me/a b/报告.pdf'), ['/Users/me/Desktop/shot.png', '/tmp/x/log.txt']);
  assert.deepEqual(withoutFile(files, '/not/there'), files);
  assert.deepEqual([fileName('/Users/me/a b/报告.pdf'), isImage('/a/b/shot.PNG'), isImage('/a/b/notes.md')], ['报告.pdf', true, false]);
  const at = new Date(2026, 10, 14, 9, 3, 7);
  assert.deepEqual([pasteName(at), pasteName(at, 2)], ['paste-20261114-090307.png', 'paste-20261114-090307-2.png']);
  assert.equal(attachmentsDir({ conversation: '/Users/me/.dudu/projects/dudu/conversation.jsonl' }), '/Users/me/.dudu/projects/dudu/attachments');
  assert.equal(attachmentsDir({}), '');
});

test('a message carries its files as its last lines, and its bubble shows them as files', () => {
  const { messageText, splitMessage, sameMessage } = model;
  const files = ['/Users/me/Desktop/shot.png', '/Users/me/a b/报告.pdf'];
  const sent = messageText('  这个按钮错位了\n看截图  ', files);
  assert.equal(sent, '这个按钮错位了\n看截图\n\n/Users/me/Desktop/shot.png\n/Users/me/a b/报告.pdf');
  // Files alone: a line before them, so the message does not start with "/" (a command to the agent).
  assert.equal(messageText('', files), `Attachments:\n${files.join('\n')}`);
  assert.equal(messageText('', files, model.word('zh', 'attachments')), `附件：\n${files.join('\n')}`);
  for (const lang of ['en', 'zh']) {
    assert.deepEqual(splitMessage(messageText('', files, model.word(lang, 'attachments'))), { text: '', files });
  }
  assert.equal(messageText(' hi ', []), 'hi');
  assert.equal(messageText(' ', []), '');
  assert.deepEqual(splitMessage(sent), { text: '这个按钮错位了\n看截图', files });
  assert.deepEqual(splitMessage(files.join('\n')), { text: '', files });
  // Paths that are part of the words stay words; a slash command is not a file.
  for (const words of ['see /Users/me/x.txt', '改这个：\n/Users/me/x.txt', '/clear', 'hi']) {
    assert.deepEqual(splitMessage(words), { text: words, files: [] });
  }
  // In the timeline: the bubble's words without the paths, and the files beside them; pending or logged alike.
  const items = timeline([ev('09:00:00', 'user', { text: sent })], [], { pending: [{ id: 1, text: messageText('', files, '附件：'), sentAt: 0 }] });
  assert.deepEqual(items.filter(i => i.kind === 'user').map(i => [i.text, i.files]), [['这个按钮错位了\n看截图', files], ['', files]]);
  // A sent message is found in the log as sent, or with its images recorded as Claude Code marks them.
  assert.ok(sameMessage(sent, sent));
  assert.ok(sameMessage('这个按钮错位了\n看截图\n\n[Image #1]\n/Users/me/a b/报告.pdf', sent));
  assert.ok(sameMessage('Attachments:\n[Image #1]', messageText('', ['/Users/me/Desktop/shot.png'])));
  assert.ok(sameMessage('[Image #1]', messageText('', ['/Users/me/Desktop/shot.png'], '附件：')));
  // A name may start or end with a space: the path goes out and comes back as it is.
  const spaced = ['/Users/me/ odd name .png'];
  assert.deepEqual(splitMessage(messageText('hi', spaced)), { text: 'hi', files: spaced });
  assert.ok(!sameMessage('别的话\n\n[Image #1]', sent));
  assert.ok(!sameMessage('这个按钮错位了', '这个按钮错位了吗'));
  const at = model.eventTime('2026-11-13 09:00:00');
  assert.deepEqual(settlePending([{ id: 1, text: sent, sentAt: at }], [ev('09:00:01', 'user', { text: '这个按钮错位了\n看截图\n\n[Image #1] [Image #2]' })]), []);
});

test('a message sent with a pasted screenshot settles on the log line that has its image mark before the words', () => {
  const { messageText, sameMessage, pastesIn } = model;
  const dir = '/Users/me/.pm/projects/dudu/attachments';
  const shot = `${dir}/paste-20261113-085958.png`, shot2 = `${dir}/paste-20261113-085959.png`;
  const at = model.eventTime('2026-11-13 09:00:00');
  const one = messageText('这里的展示是不是需要再设计一下', [shot]);
  const two = messageText('两张图', [shot, shot2]);
  assert.ok(sameMessage('[Image #3]这里的展示是不是需要再设计一下', one));
  assert.ok(sameMessage('[Image #1] 这里的展示是不是需要再设计一下', one));
  assert.ok(sameMessage('[Image #1][Image #2]两张图', two));
  assert.ok(!sameMessage('[Image #3]别的话', one));
  assert.deepEqual(settlePending([{ id: 1, text: one, sentAt: at }], [ev('09:00:01', 'user', { text: '[Image #3]这里的展示是不是需要再设计一下' })]), []);
  assert.deepEqual(settlePending([{ id: 2, text: two, sentAt: at }], [ev('09:00:01', 'user', { text: '[Image #1][Image #2]两张图' })]), []);
  // Plain words settle as before; a mark does not make other words match.
  assert.deepEqual(settlePending([{ id: 3, text: 'ok', sentAt: at }], [ev('09:00:01', 'user', { text: 'ok' })]), []);
  assert.equal(settlePending([{ id: 4, text: 'ok', sentAt: at }], [ev('09:00:01', 'user', { text: '[Image #1]ok吗' })]).length, 1);
  // Shown once, without the mark, with the screenshot pasted for it as its file.
  const names = ['paste-20261113-085958.png', 'paste-20261113-085959.png', 'paste-20261113-090100.png', 'notes.txt'].join('\n');
  const pastes = pastesIn(dir, names);
  assert.deepEqual(pastes, [shot, shot2, `${dir}/paste-20261113-090100.png`]);
  const users = events => timeline(events, [], { pastes }).filter(i => i.kind === 'user').map(i => [i.text, i.files]);
  assert.deepEqual(users([ev('09:00:01', 'user', { text: '[Image #3]这里的展示是不是需要再设计一下' })]),
    [['这里的展示是不是需要再设计一下', [shot2]]]);
  assert.deepEqual(users([ev('09:00:01', 'user', { text: '[Image #1][Image #2]两张图' })]), [['两张图', [shot, shot2]]]);
  // Each message takes the screenshots pasted since the one before it; one pasted later is not its.
  assert.deepEqual(users([ev('08:59:58', 'user', { text: '[Image #1]a' }), ev('09:00:01', 'user', { text: '[Image #2]b' })]),
    [['a', [shot]], ['b', [shot2]]]);
  // No screenshot to be found: the mark goes, the words stay; a message of marks alone keeps them.
  assert.deepEqual(users([ev('08:00:00', 'user', { text: '[Image #1] 又有BUG!' })]), [['又有BUG!', undefined]]);
  assert.deepEqual(users([ev('08:00:00', 'user', { text: '[Image #1]' })]), [['[Image #1]', undefined]]);
  assert.deepEqual(users([ev('09:00:00', 'user', { text: '[Image #1]' })]), [['', [shot2]]]);
  // A screenshot another message carries as a path is that message's.
  assert.deepEqual(users([ev('08:59:59', 'user', { text: messageText('x', [shot2]) }), ev('09:00:01', 'user', { text: '[Image #1]y' })]),
    [['x', [shot2]], ['y', [shot]]]);
  // Plain messages show as before.
  assert.deepEqual(users([ev('09:00:01', 'user', { text: 'hi' })]), [['hi', undefined]]);
  assert.deepEqual(pastesIn('', names), []);
});

test('what the picker and a drop give is attached as given, and what is not a file is named', () => {
  const { pickedPaths, notFiles, withFiles } = model;
  // osascript: one path a line, a blank line at the end; a name with spaces at either end stays whole.
  const out = '/Users/me/ lead.txt\n/Users/me/trail .png \n/Users/me/a b/c.pdf\n\n';
  assert.deepEqual(pickedPaths(out), ['/Users/me/ lead.txt', '/Users/me/trail .png ', '/Users/me/a b/c.pdf']);
  assert.deepEqual(withFiles([], pickedPaths(out)), pickedPaths(out));
  assert.deepEqual(pickedPaths(''), []);
  assert.deepEqual(notFiles(['/Users/me/a.png', 'relative.png', '/clear', '/tmp/dir/']), ['relative.png', '/clear', '/tmp/dir/']);
  assert.deepEqual(notFiles(undefined), []);
});

test('files attached go into the draft they were meant for, as it is stored', () => {
  const { addFiles, draftFiles, afterSend, messageText } = model;
  const main = draftKey('pm', 'pm-dudu'), other = draftKey('thread', 'dudu-x'), shot = '/a/att/paste-1.png', late = '/a/att/paste-2.png';
  // A picker or paste that ends after the user moved to another thread still fills the draft it started for.
  let drafts = keepDraft({}, other, 'thread words', 1000);
  drafts = addFiles(drafts, main, [shot], 2000);
  assert.deepEqual([draftFiles(drafts, main), draftText(drafts, other), draftFiles(drafts, other)], [[shot], 'thread words', []]);
  // A send on its way: the box shows nothing, its draft is still what went out. A file attached then
  // joins that draft instead of replacing it ...
  drafts = keepDraft(drafts, main, '看这张', 3000, [shot]);
  drafts = addFiles(drafts, main, [late], 4000);
  assert.deepEqual([draftText(drafts, main), draftFiles(drafts, main)], ['看这张', [shot, late]]);
  assert.equal(addFiles(drafts, main, [late], 5000), drafts);
  // ... so a failed send loses nothing, and one that worked leaves only the late file.
  const sent = { text: '看这张', files: [shot] }, stored = { text: draftText(drafts, main), files: draftFiles(drafts, main) };
  assert.equal(afterSend(stored, sent, false), null);
  assert.deepEqual(afterSend(stored, sent, true), { text: '', files: [late] });
  assert.equal(messageText(stored.text, stored.files), `看这张\n\n${shot}\n${late}`);
});

test('a draft keeps its files with its words, through a reload and around a send', () => {
  const { draftFiles, afterSend } = model;
  const main = draftKey('pm', 'pm-dudu'), shot = '/Users/me/.dudu/projects/dudu/attachments/paste-20261114-090307.png';
  // Files alone are a draft; typing keeps them; attaching keeps the words.
  let drafts = keepDraft({}, main, '', 1000, [shot]);
  assert.deepEqual(drafts, { [main]: { text: '', at: 1000, files: [shot] } });
  drafts = keepDraft(drafts, main, '看这张', 2000);
  assert.deepEqual(drafts, { [main]: { text: '看这张', at: 2000, files: [shot] } });
  assert.equal(keepDraft(drafts, main, '看这张', 3000, [shot]), drafts);
  // What a new view reads (the mod reloaded): the words and the files.
  const again = readDrafts(JSON.stringify(drafts));
  assert.deepEqual([draftText(again, main), draftFiles(again, main)], ['看这张', [shot]]);
  assert.deepEqual(readDrafts('{"pm:a":{"files":["/a/b.png","nope"]},"pm:b":{"text":" ","files":[]},"pm:c":{"text":"x","files":"bad"}}'),
    { 'pm:a': { text: '', at: 0, files: ['/a/b.png'] }, 'pm:c': { text: 'x', at: 0 } });
  // The last file removed with no words left: no draft.
  assert.deepEqual(keepDraft(keepDraft(drafts, main, '', 4000), main, '', 5000, []), {});
  // Sent and it worked: the words and the files that went are gone, a file attached since stays.
  const sent = { text: '看这张', files: [shot] };
  assert.deepEqual(afterSend({ text: '看这张', files: [shot] }, sent, true), { text: '', files: [] });
  assert.deepEqual(afterSend({ text: '看这张', files: [shot, '/a/new.png'] }, sent, true), { text: '', files: ['/a/new.png'] });
  assert.deepEqual(afterSend({ text: '又写了', files: [] }, sent, true), null);
  // Not sent: an empty box gets it all back; anything typed or attached since stays as it is.
  assert.deepEqual(afterSend({ text: '', files: [] }, sent, false), sent);
  assert.equal(afterSend({ text: '', files: ['/a/new.png'] }, sent, false), null);
  assert.equal(afterSend({ text: '又写了', files: [] }, sent, false), null);
});

test('ages read as in the PM list', () => {
  const spans = [0, 59_000, 60_000, 3_600_000 * 3, 86_400_000 * 2];
  assert.deepEqual(spans.map(ms => age(ms)), ['<1m', '<1m', '1m', '3h', '2d']);
  assert.deepEqual(spans.map(ms => age(ms, 'zh')), ['刚刚', '刚刚', '1 分钟', '3 小时', '2 天']);
  assert.deepEqual(spans.map(ms => age(ms, 'zh')), spans.map(ms => list.age(ms, 'zh')));
  assert.equal(model.age.toString(), list.age.toString());
});

test('the thread panel reads the ledger\'s own log lines in the view\'s language', () => {
  const both = (text, whole) => [logText('en', text, whole), logText('zh', text, whole)];
  // A change of fields with a note is the note, in the list and in the thread's log alike.
  assert.deepEqual(both('status=review, commit=57961f9; 一个提交，测试都过'), ['一个提交，测试都过', '一个提交，测试都过']);
  assert.deepEqual(both('status=blocked; 计数放在哪？', true), ['计数放在哪？', '计数放在哪？']);
  assert.deepEqual(both('brief=/b/x.md; 任务书已写好', true), ['任务书已写好', '任务书已写好']);
  assert.deepEqual(both('status=done; 用户：不带声音。a=b, c'), ['用户：不带声音。a=b, c', '用户：不带声音。a=b, c']);
  // Only changes: nothing under a row of the list (its group says it); spelled out in the thread's log.
  assert.deepEqual(both('status=merged, commit=253e5f0'), ['', '']);
  assert.deepEqual(both('status=merged, commit=253e5f0', true), ['status=merged, commit=253e5f0', '状态改为已合并，提交 253e5f0']);
  assert.deepEqual(both('branch=dev/panel-zh', true), ['branch=dev/panel-zh', '分支 dev/panel-zh']);
  assert.deepEqual(both('status=in_progress', true), ['status=in_progress', '状态改为进行中']);
  assert.deepEqual(both('status=review，commit=abc；', true), ['status=review, commit=abc', '状态改为审查中，提交 abc']);
  assert.equal(logText('zh', 'owner=pm, pane=hc:t3, base=main, brief=/b/x.md, release=abb2ae4', true), '负责 pm，终端 hc:t3，基线 main，任务书 /b/x.md，发布 abb2ae4');
  // The lines pm.py writes by itself.
  assert.deepEqual(both('registered (in_progress)'), ['registered (in_progress)', '登记（进行中）']);
  assert.deepEqual(both('dispatched to toast-test (claude opus)'), ['dispatched to toast-test (claude opus)', '派给 toast-test（claude opus）']);
  assert.equal(logText('zh', 'retired: removed terminal hc:t2j, worktree /w/dudu/dev-x, branch dev/x'), '已回收：终端 hc:t2j、工作树 /w/dudu/dev-x、分支 dev/x');
  assert.equal(logText('zh', 'retired: removed nothing'), '已回收：没有要清理的');
  assert.equal(logText('zh', 'retired: removed worktree /w/x; branch dev/x is kept: checked out in /w/y'), '已回收：工作树 /w/x；分支 dev/x 保留：在 /w/y 检出着');
  assert.equal(logText('zh', 'retired: removed nothing; branch dev/x is kept: git refused to delete it'), '已回收：没有要清理的；分支 dev/x 保留：git 拒绝删除');
  assert.equal(logText('zh', 'retired: worktree and branch dev/old'), '已回收：工作树和分支 dev/old');
  assert.equal(logText('en', 'retired: removed nothing', true), 'retired: removed nothing');
  // What a person or an agent wrote stays as written, also when it only begins like one of those.
  for (const text of ['用户：隐藏废弃任务', 'dispatched to x same worker (codex, hc t13); user said so', 'registered the hook (twice)', 'retired: see the note', 'a=b; c']) {
    assert.deepEqual(both(text, true), [text, text]);
  }
  assert.deepEqual([logText('zh', null), logText('zh', '  '), logText('en', undefined, true)], ['', '', '']);
  // The list's line under an open thread goes through it.
  const pm = { name: 'pm-dudu', repo: '/r/dudu' };
  const tasks = [{ id: 'a', pm: 'pm-dudu', title: 'A', status: 'in_progress', latest: 'dispatched to a (codex)' },
    { id: 'b', pm: 'pm-dudu', title: 'B', status: 'review', latest: 'status=review, commit=abc' }];
  assert.deepEqual(threadList(pm, tasks, [], [], [], [], 'zh').open.map(r => r.latest), ['', '派给 a（codex）']);
  assert.deepEqual(threadList(pm, tasks, []).open.map(r => r.latest), ['', 'dispatched to a (codex)']);
});

test('copied helpers stay identical to pm-dash and pm-list', async () => {
  const { readFileSync } = await import('node:fs');
  for (const name of ['cleanTaskLog', 'terminalFor', 'terminalTargetFor', 'focusPlan', 'withAlpha', 'isDarkTheme', 'solidText', 'inferStepAnchor', 'parsePlanItems', 'taskSteps', 'isPostGateTask', 'taskDependencies', 'taskNumber', 'formatTaskNumber']) {
    assert.equal(model[name].toString(), dash[name].toString(), name);
  }
  assert.equal(model.STEP_LABEL_UNITS, dash.STEP_LABEL_UNITS);
  assert.deepEqual(Object.keys(model.PLAN_STRINGS.en), Object.keys(dash.PLAN_STRINGS.en));
  assert.deepEqual(Object.keys(model.PLAN_STRINGS.zh), Object.keys(dash.PLAN_STRINGS.zh));
  for (const file of ['steps.js', 'check-mark.svg', 'tree-branch.svg']) {
    assert.equal(
      readFileSync(new URL(`./${file}`, import.meta.url), 'utf8'),
      readFileSync(new URL(`../pm-dash/${file}`, import.meta.url), 'utf8'),
      `${file} must stay byte-for-byte identical between pm-project and pm-dash`,
    );
  }
  assert.equal(model.terminalFor.toString(), list.terminalFor.toString());
  assert.equal(model.focusPlan.toString(), list.focusPlan.toString());
  // The bell, the sidebar's project badge (pm-list) and pm-nav's total count what waits alike.
  assert.equal(model.waitingCount.toString(), list.waitingCount.toString());
  assert.equal(model.waitingCount.toString(), nav.waitingCount.toString());
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

test('a thread whose terminal is gone reads as disconnected, apart from the work going on', () => {
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/r/dudu' };
  const tasks = [
    { id: 'run', pm: 'pm-dudu', title: 'Run', status: 'in_progress', updated: '2026-11-13 10:00' },
    { id: 'dead', pm: 'pm-dudu', title: 'Dead', status: 'in_progress', updated: '2026-11-13 11:00', offline: true },
    { id: 'asks', pm: 'pm-dudu', title: 'Asks', status: 'blocked', updated: '2026-11-13 09:00', offline: true },
    { id: 'rev', pm: 'pm-dudu', title: 'Rev', status: 'review', updated: '2026-11-13 08:00', offline: true },
    { id: 'idle', pm: 'pm-dudu', title: 'Idle', status: 'proposed', updated: '2026-11-13 07:00' },
  ];
  // Its worker's terminal label alone does not make it work going on.
  const terms = [{ address: 't40', state: 'live', labels: { task: 'dead' }, status: 'working' }];
  const open = threadList(pm, tasks, [], terms, []).open;
  assert.deepEqual(open.map(r => [r.task, r.group, r.tone, Boolean(r.offline)]), [
    ['asks', 'waiting', 'blocked', true],  // what waits for the user keeps waiting, in the bell's group
    ['rev', 'working', 'review', true],    // review stays inside Working with review tone
    ['run', 'working', 'running', false],
    ['dead', 'offline', 'quiet', true],    // after the work going on, before what is not started
    ['idle', 'parked', 'quiet', false],
  ]);
  assert.equal(open.find(r => r.task === 'dead').working, false);
  assert.equal(open.filter(r => r.group === 'waiting').length, model.waitingCount(pm, tasks));
  assert.equal(model.word('zh', 'group_offline'), '已断开');
  assert.equal(model.word('en', 'group_offline'), 'Disconnected');

  // The words: Disconnected for work in progress only; what waits or is in review says so still.
  assert.equal(model.statusLabel('zh', 'in_progress', false, true), '已断开');
  assert.equal(model.statusLabel('en', 'in_progress', false, true), 'Disconnected');
  assert.equal(model.statusLabel('zh', 'blocked', false, true), '阻塞');
  assert.equal(model.statusLabel('zh', 'in_progress'), '进行中');
  assert.equal(model.tone('in_progress', false, true), 'quiet');
  assert.equal(model.tone('review', false, true), 'review');

  // The conversation's thread row: no dots, and the quiet word under the pointer.
  const items = timeline([thread('09:00:00', 'dead', 'in_progress', 'registered')], tasks);
  const row = items.find(i => i.kind === 'threads').rows[0];
  assert.deepEqual([row.tone, row.offline, model.statusLabel('zh', row.status, row.cleanup, row.offline)], ['quiet', true, '已断开']);
});

test("the thread panel's terminal icon opens the terminal, or reattaches a thread whose terminal is gone", () => {
  const { terminalAction, reattachArgv } = model;
  assert.equal(terminalAction({ address: 't9' }, { offline: true }), 'open');  // a live terminal wins
  assert.equal(terminalAction(null, { offline: true }), 'reattach');
  assert.equal(terminalAction(null, { offline: true }, true), 'reattaching');
  assert.equal(terminalAction(null, { offline: false }), 'none');            // nothing known to bring back
  assert.equal(terminalAction(null, null), 'none');
  assert.deepEqual(reattachArgv('/app/pm.py', 'dudu-x'), ['python3', '/app/pm.py', 'reattach', 'dudu-x']);
  assert.match(model.word('zh', 'reattach'), /^接回/);
  assert.equal(model.word('zh', 'reattachFailed', 'x'), '没接回：x');
});

test('a task split into sub-threads lists them, and each links back to it', () => {
  const { subThreads, parentThread, terminalAction } = model;
  const tasks = [
    { id: 'd-whole', title: '派发时选模型', status: 'in_progress', pane: '', updated: '2026-11-15 00:36' },
    { id: 'd-effort', title: 'claude effort', status: 'merged', parent: 'd-whole', cleanup: true, updated: '2026-11-15 01:00' },
    { id: 'd-label', title: '档位标签', status: 'in_progress', parent: 'd-whole', pane: 'hc:t7', updated: '2026-11-15 01:20' },
    { id: 'd-esc', title: '升档', status: 'review', parent: 'd-whole', pane: 'hc:t8', updated: '2026-11-15 01:10' },
    { id: 'd-gone', title: '断开的', status: 'in_progress', parent: 'd-whole', pane: 'hc:t9', offline: true, updated: '2026-11-15 01:30' },
    { id: 'd-other', title: '别的', status: 'in_progress', updated: '2026-11-15 01:40' },  // an older task: no parent
  ];
  const terms = [{ address: 't7', state: 'live', status: 'working', labels: { task: 'd-label' } }];
  const parts = subThreads(tasks, 'd-whole', terms, [], 'zh');
  // Open ones in the thread list's order (working with review first, then running, then disconnected), then those that are over.
  assert.deepEqual(parts.map(row => [row.task, row.group]),
    [['d-esc', 'working'], ['d-label', 'working'], ['d-gone', 'offline'], ['d-effort', 'finished']]);
  assert.equal(parts[1].working, true);
  assert.deepEqual([parts[3].status, parts[3].cleanup, parts[3].tone], ['merged', true, 'quiet']);
  assert.deepEqual(subThreads(tasks, 'd-other'), []);
  assert.deepEqual(subThreads(tasks, ''), []);
  assert.deepEqual(subThreads(null, 'd-whole'), []);
  // Each part's panel links back to the task; one without a parent, or whose parent is off the board, has none.
  assert.deepEqual(parentThread(tasks, tasks[2]), { task: 'd-whole', title: '派发时选模型' });
  assert.equal(parentThread(tasks, tasks[5]), null);
  assert.equal(parentThread(tasks, { id: 'x', parent: 'gone' }), null);
  assert.equal(parentThread(tasks, { id: 'x', parent: 'x' }), null);
  assert.equal(model.word('zh', 'partOf', '派发时选模型'), '属于 派发时选模型');
  // The task that never had a terminal shows no terminal icon once it has parts; otherwise as before.
  assert.equal(terminalAction(null, { offline: false, pane: '' }, false, parts.length), 'hidden');
  assert.equal(terminalAction(null, { offline: false, pane: '' }, false, 0), 'none');
  assert.equal(terminalAction(null, { offline: false }, false, 2), 'hidden');          // an old task without the field
  assert.equal(terminalAction(null, { offline: false, pane: 'hc:t3' }, false, 2), 'none'); // it had one
  assert.equal(terminalAction(null, { offline: true, pane: 'hc:t3' }, false, 2), 'reattach');
  assert.equal(terminalAction({ address: 't3' }, { pane: '' }, false, 2), 'open');
  // Parts already retired come apart in the state (`retired_parts`): listed as over, once each.
  const retired = [{ id: 'd-old', title: '早合并的', status: 'merged', parent: 'd-whole', retired: true, updated: '2026-11-15 00:50' },
    { id: 'd-effort', title: 'claude effort', status: 'merged', parent: 'd-whole', retired: true },
    { id: 'd-else', title: '别人的', status: 'merged', parent: 'd-other', retired: true }];
  const all = subThreads(tasks, 'd-whole', terms, [], 'zh', retired);
  assert.deepEqual(all.map(row => row.task), ['d-esc', 'd-label', 'd-gone', 'd-effort', 'd-old']);
  assert.deepEqual([all[4].group, all[4].cleanup], ['finished', false]);
  assert.deepEqual(subThreads([tasks[0]], 'd-whole', [], [], 'zh', retired).map(row => row.task), ['d-old', 'd-effort']);
  assert.equal(terminalAction(null, { pane: '' }, false, subThreads([tasks[0]], 'd-whole', [], [], 'zh', retired).length), 'hidden');
  // `pm.py update --parent` reads in the thread's log.
  assert.equal(model.logText('zh', 'parent=d-whole', true), '属于 d-whole');
  assert.equal(model.logText('zh', 'parent=d-whole'), '');
});

test('the engine label names the worker briefly, and nothing for a task from before profiles', () => {
  const { engineLabel, modelName } = model;
  const w = worker => ({ engine: worker });
  assert.equal(engineLabel(w({ profile: 'hard', kind: 'claude', model: 'opus', effort: 'xhigh', advisor: 'fable' })), 'Opus·xhigh+Fable');
  assert.equal(engineLabel(w({ profile: 'light', kind: 'claude', model: 'sonnet', effort: 'medium', advisor: '' })), 'Sonnet·medium');
  assert.equal(engineLabel(w({ profile: 'standard', kind: 'claude', model: 'opus', effort: '', advisor: '' })), 'Opus');
  assert.equal(engineLabel(w({ profile: 'deep', kind: 'claude', model: 'claude-fable-5-2', effort: 'high' })), 'Fable 5.2·high');
  assert.equal(engineLabel(w({ kind: 'codex', model: 'gpt-5', effort: 'high' })), 'Codex·high');
  assert.equal(engineLabel(w({ kind: 'claude' })), 'Claude');
  assert.equal(engineLabel(w({ kind: 'claude', model: 'opus', advisor: 'claude-fable-5-2' })), 'Opus+Fable');
  // The task file's `worker` object serves as well; the state's `worker` (an agent status word) does not.
  assert.equal(engineLabel({ worker: { kind: 'claude', model: 'sonnet' } }), 'Sonnet');
  assert.equal(engineLabel({ engine: {}, worker: 'working' }), null);
  assert.equal(engineLabel({ engine: { profile: '', kind: '', model: '', effort: '', advisor: '' } }), null);
  assert.equal(engineLabel({}), null);
  assert.equal(engineLabel(null), null);
  assert.equal(modelName('claude-opus-5-5'), 'Opus 5.5');
  assert.equal(modelName('claude-opus-4-1-20250805'), 'Opus 4.1');
  assert.equal(modelName('us.anthropic.claude-sonnet-5-5-v1:0'), 'Sonnet 5.5');
  assert.equal(modelName('opus[1m]'), 'Opus');
  assert.equal(modelName('haiku'), 'Haiku');
  assert.equal(modelName('gpt-5'), 'Gpt-5');
  assert.equal(modelName(''), '');
});

test('hovering the engine label gives the profile, the dispatch reason, escalations and review rounds', () => {
  const { engineTip, engineReason, wasEscalated } = model;
  // As the ledger has them (dudu-engine-label, dudu-escalate on 2026-11-15).
  const standard = {
    worker: { profile: 'standard', kind: 'claude', model: 'opus', effort: '', advisor: '' }, escalations: [], rounds: 0,
    log: [{ at: '2026-11-15 01:00', by: 'hc:t48', text: 'dispatched to engine-label (standard: claude opus)' },
      { at: '2026-11-15 01:01', by: 'hc:t48', text: 'standard：普通 mod UI' }],
  };
  assert.equal(engineReason(standard), '普通 mod UI');
  assert.equal(engineTip('zh', standard), '档位：standard\n理由：普通 mod UI\n评审轮数：0');
  assert.equal(engineTip('en', standard), 'Profile: standard\nWhy: 普通 mod UI\nReview rounds: 0');
  assert.equal(wasEscalated(standard), false);

  const escalated = {
    engine: { profile: 'hard', kind: 'claude', model: 'opus', effort: 'xhigh', advisor: 'fable' }, rounds: 2,
    escalations: [{ from: 'light', to: 'standard', why: '评审没过：漏了离线状态', at: '2026-11-15 02:00' },
      { from: 'standard', to: 'hard', why: '', at: '2026-11-15 03:00' }],
    log: [{ text: 'light：改一行文案' }, { text: 'hard: 两轮没过，换 hard' }, { text: 'status=review, commit=abc' }],
  };
  assert.equal(wasEscalated(escalated), true);
  assert.equal(engineReason(escalated), '两轮没过，换 hard', 'the reason written for the profile it runs on now');
  assert.equal(engineTip('zh', escalated),
    '档位：hard\n理由：两轮没过，换 hard\n升级 light → standard：评审没过：漏了离线状态\n升级 standard → hard\n评审轮数：2');
  assert.equal(engineTip('en', escalated).split('\n')[2], 'Escalated light → standard: 评审没过：漏了离线状态');

  // A side written as a worker record is said by its profile, or its label; odd entries are left out.
  const records = { engine: { kind: 'codex', effort: 'high' },
    escalations: [{ from: { kind: 'claude', model: 'sonnet' }, to: { profile: 'hard' }, why: 'x' }, null, {}] };
  assert.equal(engineTip('en', records), 'Escalated Sonnet → hard: x');
  // No profile and nothing else to say: the label itself.
  assert.equal(engineTip('en', { engine: { kind: 'codex', effort: 'high' } }), 'Codex·high');
  assert.equal(engineReason({ engine: { kind: 'codex' }, log: [{ text: 'codex: x' }] }), '');
  assert.equal(engineTip('zh', { engine: {} }), '');
  assert.equal(wasEscalated({}), false);
});

test('a thread list row carries the label without its advisor, the model alone when narrow, and the same tip', () => {
  const { engineChip, engineTip } = model;
  // As `pm.py state` lists them: the worker under `engine`, its escalations and rounds beside it.
  const hard = { engine: { profile: 'hard', kind: 'claude', model: 'opus', effort: 'xhigh', advisor: 'fable' }, rounds: 1,
    escalations: [{ from: 'standard', to: 'hard', why: '两轮没过' }], log: [{ text: 'hard：跨文件状态机' }] };
  assert.deepEqual(engineChip('zh', hard), { label: 'Opus·xhigh', name: 'Opus', advisor: 'Fable', up: true,
    tip: engineTip('zh', hard) });
  assert.deepEqual(engineChip('en', { engine: { profile: 'light', kind: 'claude', model: 'sonnet', effort: 'medium', advisor: '' } }),
    { label: 'Sonnet·medium', name: 'Sonnet', advisor: '', up: false, tip: 'Profile: light' });
  // No effort given: the default is said, still the model alone when narrow. A review thread's worker is its reviewer.
  const standard = { engine: { profile: 'standard', kind: 'claude', model: 'opus', effort: '', advisor: '' } };
  assert.deepEqual([engineChip('zh', standard).label, engineChip('zh', standard).name], ['Opus·默认', 'Opus']);
  assert.equal(engineChip('en', { engine: { profile: '', kind: 'claude', model: 'fable', effort: '', advisor: '' } }).label, 'Fable·default');
  assert.equal(engineChip('en', { engine: { kind: 'codex', model: 'gpt-5', effort: 'high', advisor: 'claude-fable-5-2' } }).advisor, 'Fable');
  // Entered by hand, or from before profiles: nothing.
  assert.equal(engineChip('zh', { engine: {}, worker: 'working' }), null);
  assert.equal(engineChip('zh', { id: 'x' }), null);
});

test('an ended thread off the board is labeled from the state\'s ended_engines', () => {
  const { engineChip, endedEngine } = model;
  // As `pm.py state` keeps them for retired tasks (dudu-pm-light-review was escalated once).
  const marks = { 'dudu-pm-light-review': { profile: 'hard', kind: 'claude', model: 'opus', effort: 'xhigh', advisor: 'fable', escalated: 1 },
    'dudu-ops-basics': { profile: 'standard', kind: 'claude', model: 'opus' } };
  assert.deepEqual(engineChip('zh', endedEngine(marks, 'dudu-pm-light-review')),
    { label: 'Opus·xhigh', name: 'Opus', advisor: 'Fable', up: true, tip: '档位：hard\n升级过 1 次' });
  assert.equal(engineChip('en', endedEngine(marks, 'dudu-pm-light-review')).tip, 'Profile: hard\nEscalated 1 time');
  assert.deepEqual(engineChip('zh', endedEngine(marks, 'dudu-ops-basics')),
    { label: 'Opus·默认', name: 'Opus', advisor: '', up: false, tip: '档位：standard' });
  // Not kept (an older thread, or a state from before): no label.
  assert.equal(endedEngine(marks, 'dudu-old'), null);
  assert.equal(endedEngine(undefined, 'dudu-ops-basics'), null);
  assert.equal(endedEngine({ toString: 'x' }, 'toString'), null);
});

test('past six sub-threads the rest fold behind how many more there are', () => {
  const { foldParts, PARTS_LIMIT, word } = model;
  const rows = n => Array.from({ length: n }, (_x, i) => ({ task: `p${i}` }));
  assert.equal(PARTS_LIMIT, 6);
  assert.deepEqual(foldParts(rows(6)), { shown: rows(6), more: 0 });
  assert.deepEqual(foldParts(rows(9)), { shown: rows(6), more: 3 });
  assert.deepEqual(foldParts(rows(9), true), { shown: rows(9), more: 0 });
  assert.deepEqual(foldParts(null), { shown: [], more: 0 });
  assert.equal(word('zh', 'moreParts', 3), '还有 3 条');
  assert.equal(word('en', 'moreParts', 3), '3 more');
});

test('Esc on the conversation page goes back one layer a press', () => {
  const { escapeStep } = model;
  // Words in the focused box: only let go of the keyboard, whatever is open.
  assert.equal(escapeStep({ typing: true, detail: true, listOpen: true }), 'blur');
  assert.equal(escapeStep({ typing: true }), 'blur');
  // Then the thread's detail, back to the list; then a list slid open over a narrow window.
  assert.equal(escapeStep({ detail: true, listOpen: true }), 'detail');
  assert.equal(escapeStep({ detail: true }), 'detail');
  assert.equal(escapeStep({ listOpen: true }), 'list');
  // Answering a question card in the box's own words: that stops first, whatever else is open.
  assert.equal(escapeStep({ answering: true, typing: true, detail: true, listOpen: true }), 'answer');
  assert.equal(escapeStep({ answering: true }), 'answer');
  // Nothing open: the conversation is the top, the key goes on.
  assert.equal(escapeStep({}), null);
  assert.equal(escapeStep(), null);
});

test('the side panel keeps the width it was dragged to, within its limits', () => {
  const { panelWidth, draggedWidth, readPanelWidth, PANEL_WIDTH, PANEL_MIN, TALK_MIN, word } = model;
  assert.deepEqual([PANEL_WIDTH, PANEL_MIN, TALK_MIN], [360, 260, 360]);
  // Nothing dragged: the default; before the view is measured, the width as asked.
  assert.equal(panelWidth(null, 1400), 360);
  assert.equal(panelWidth(null), 360);
  assert.equal(panelWidth(500), 500);
  // A dragged width holds where it fits, and is fitted where it does not.
  assert.equal(panelWidth(480, 1400), 480);
  assert.equal(panelWidth(120, 1400), 260);
  assert.equal(panelWidth(1200, 1400), 1040);
  // A narrow window: the conversation keeps 360 and the panel gives way, down to its own minimum.
  assert.equal(panelWidth(null, 670), 310);
  assert.equal(panelWidth(480, 700), 340);
  assert.equal(panelWidth(480, 500), 260);
  // Narrower than the panel's minimum: never wider than the view.
  assert.equal(panelWidth(null, 200), 200);
  // Junk asks for the default.
  assert.equal(panelWidth(NaN, 1400), 360);
  assert.equal(panelWidth(-40, 1400), 360);
  // Dragging the left edge left widens the panel, right narrows it, within the same limits.
  const drag = { x: 1000, width: 360 };
  assert.equal(draggedWidth(drag, 900, 1400), 460);
  assert.equal(draggedWidth(drag, 1050, 1400), 310);
  assert.equal(draggedWidth(drag, 1300, 1400), 260);
  assert.equal(draggedWidth(drag, 100, 1400), 1040);
  assert.equal(draggedWidth(drag, 999.4, 1400), 361);
  // What storage holds: a positive number, else nothing kept.
  assert.equal(readPanelWidth('420'), 420);
  assert.equal(readPanelWidth('420.6'), 421);
  assert.equal(readPanelWidth(null), null);
  assert.equal(readPanelWidth(''), null);
  assert.equal(readPanelWidth('wide'), null);
  assert.equal(readPanelWidth('0'), null);
  assert.equal(word('zh', 'resizePanel'), '拖动调整侧栏宽度，双击恢复默认宽度');
});

test('a kept press stops before the window drag and gives the page the keyboard', () => {
  const { keepPressHandler } = model;
  const calls = [];
  const cx = { stop_propagation: () => calls.push('stop') };
  const keyboard = { focus: () => calls.push('focus') };
  keepPressHandler(keyboard)({ button: 'left', click_count: 1 }, cx);
  assert.deepEqual(calls, ['focus', 'stop']);
  // A message box or a reply's words take the keyboard themselves: the press is only kept.
  calls.length = 0;
  keepPressHandler(null)({ button: 'left', click_count: 2 }, cx);
  assert.deepEqual(calls, ['stop']);
});

test('a review thread is folded into the task it reviews, and counts once', () => {
  const { foldReviews, reviewRow, threadFor } = model;
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/r/dudu' };
  const drag = { id: 'drag', pm: 'pm-dudu', title: '标题栏拖动窗口', status: 'review', updated: '2026-11-15 02:50', offline: true };
  const review = { id: 'drag-review', pm: 'pm-dudu', title: '审查：标题栏拖动窗口', status: 'in_progress',
    review_of: 'drag', pane: 'hc:t9', latest: '开始审查', updated: '2026-11-15 02:55' };
  const jump = { id: 'jump', pm: 'pm-dudu', title: '终端图标跳错项目', status: 'in_progress', updated: '2026-11-15 03:00' };
  const tasks = foldReviews([drag, review, jump]);
  // One row: the reviewed task, inside Working with reviewing flag and review tone, with the review riding on it.
  assert.deepEqual(tasks.map(t => t.id), ['drag', 'jump']);
  assert.equal(tasks[0].review, review);
  const open = threadList(pm, tasks, [], [], []).open;
  assert.deepEqual(open.map(r => [r.task, r.group, r.status]), [['drag', 'working', 'review'], ['jump', 'working', 'in_progress']]);
  assert.equal(open[0].reviewing, true);
  assert.equal(open[0].tone, 'review');
  // Its panel shows the review: its status, its latest report; links and lines to the review open the task.
  const terms = [{ address: 't9', state: 'live', labels: { task: 'drag-review' }, status: 'working' }];
  const row = reviewRow(tasks[0], terms, [], 'zh');
  assert.deepEqual([row.task, row.group, row.working, row.latest], ['drag-review', 'working', true, '开始审查']);
  assert.equal(model.terminalFor(model.taskRow(tasks[0].review), terms).address, 't9');
  assert.equal(threadFor(tasks, model.threadLink('thread:drag-review')), 'drag');
  assert.equal(threadFor(tasks, 'jump'), 'jump');
  assert.equal(reviewRow(tasks[1]), null);
  // The review over: the task reads as its own status again, and the review is listed as finished.
  const after = foldReviews([{ ...drag, status: 'in_progress', offline: false }, { ...review, status: 'done' }]);
  assert.deepEqual(threadList(pm, after, [], [], []).open.map(r => [r.task, r.group]), [['drag', 'working']]);
  assert.equal(threadList(pm, after, [], [], []).finished.length, 0);
  assert.equal(reviewRow(after[0]).group, 'finished');
  // The board, the Projects page and pm-nav count the work once.
  const state = { lang: 'zh', pms: [pm], tasks: [drag, review, jump], events: [
    { key: 'e1', at: '2026-11-15 02:56', task: 'drag-review', pm: 'pm-dudu', status: 'done', text: 'status=done' }] };
  const merged = dash.mergeStates(state);
  assert.deepEqual(merged.tasks.map(t => t.id), ['drag', 'jump']);
  // On the board the review's event is the task's only as what the review says: no status of the task's
  // (its card does not turn Done), and the feed does not read status=done.
  assert.deepEqual([merged.events[0].task, merged.events[0].status, merged.events[0].review, merged.events[0].text], ['drag', '', 'reviewed', '']);
  const started = dash.mergeStates({ ...state, events: [{ key: 'e0', at: '2026-11-15 02:55', task: 'drag-review', pm: 'pm-dudu', status: 'in_progress', text: '开始审查' }] });
  assert.deepEqual([started.events[0].status, started.events[0].review, started.events[0].text], ['', 'review', '开始审查']);
  assert.equal(dash.label('zh', 'reviewed'), '审查有结果');
  assert.deepEqual(dash.projectCounts(pm, merged.tasks), { working: 1, waiting: 0, review: 1, proposed: 0, merged_today: 0 });
  assert.equal(dash.counts(merged).review, 1);
  assert.equal(dash.archiveThreads(state, 'pm-dudu').length, 2);
  assert.equal(nav.summary(state).active, 1);
  // The reviewed task gone from the ledger: the review stays a row of its own, so it is not lost.
  const alone = foldReviews([review, jump]);
  assert.deepEqual(alone.map(t => t.id), ['drag-review', 'jump']);
  assert.equal(threadList(pm, alone, [], [], []).open.length, 2);
  assert.equal(threadFor(alone, 'drag-review'), 'drag-review');
  assert.equal(nav.summary({ ...state, tasks: [review, jump] }).active, 2);
  // pm-dash, pm-nav and pm-list fold alike; an empty entry is skipped, not thrown on.
  for (const copy of [dash, nav, list]) assert.equal(model.foldReviews.toString(), copy.foldReviews.toString());
  assert.deepEqual(foldReviews([null, drag, undefined, review]).map(t => t.id), ['drag']);
});

test('a folded review reads as its task: what it waits for, its terminal, and its end', () => {
  const { foldReviews } = model;
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/r/dudu' };
  const task = (status, extra = {}) => ({ id: 'dudu-drag', pm: 'pm-dudu', title: '标题栏拖动窗口', status, updated: '2026-11-15 03:00', ...extra });
  const review = (status, extra = {}) => ({ id: 'dudu-drag-review', pm: 'pm-dudu', title: '审查：标题栏拖动窗口', status,
    review_of: 'dudu-drag', pane: 'hc:t9', updated: '2026-11-15 03:10', ...extra });
  const row = tasks => threadList(pm, foldReviews(tasks), [], [], []).open[0];
  // A review that asks the user: the task waits, on the bell and in the counts, until it is answered.
  const asks = foldReviews([task('review'), review('blocked')]);
  assert.deepEqual([row([task('review'), review('blocked')]).group, asks[0].status], ['waiting', 'blocked']);
  assert.equal(waitingCount(pm, asks), 1);
  assert.equal(nav.waitingCount(pm, foldReviews([task('review'), review('blocked')])), 1);
  const answered = foldReviews(markAnswered([task('review'), review('blocked')], new Set(['dudu-drag-review'])));
  assert.deepEqual([answered[0].answered, waitingCount(pm, answered), row([task('review'), review('blocked', { answered: true })]).group], [true, 0, 'working']);
  // bellCount keeps optimistic local-answered subtraction with folded reviews, and never double-subtracts a shadowed review.
  const pmCounted = { ...pm, counts: { waiting: 1 } };
  assert.equal(model.bellCount(pmCounted, [task('review'), review('blocked')], new Set(['dudu-drag-review'])), 0);
  assert.equal(model.bellCount(pmCounted, [task('blocked'), review('blocked')], new Set(['dudu-drag-review'])), 1);
  assert.equal(model.bellCount(pmCounted, [task('blocked'), review('blocked')], new Set(['dudu-drag'])), 0);
  // Older pm.py without counts folds reviews before counting the bell.
  assert.equal(model.bellCount(pm, [task('blocked'), review('blocked')], new Set()), 1);
  // A task that is in progress while its review is open reads as in review inside Working, as pm.py counts it.
  assert.deepEqual([row([task('in_progress'), review('in_progress')]).group, nav.summary({ pms: [pm], tasks: [task('in_progress'), review('in_progress')] }).active], ['working', 0]);
  assert.equal(row([task('in_progress'), review('in_progress')]).status, 'review');
  // The task over (done, abandoned) while its review is still open: nothing of it is in review, so the
  // review stays a row of its own; once the review is over too it folds in again.
  for (const status of ['done', 'abandoned']) {
    assert.deepEqual(foldReviews([task(status), review('in_progress')]).map(t => [t.id, t.status, Boolean(t.review)]),
      [['dudu-drag', status, false], ['dudu-drag-review', 'in_progress', false]]);
    assert.deepEqual(threadList(pm, foldReviews([task(status), review('in_progress')]), [], [], []).open.map(r => r.task), ['dudu-drag-review']);
    assert.deepEqual(foldReviews([task(status), review('done')]).map(t => t.id), ['dudu-drag']);
  }
  // Both paused, or a paused review: the task's own status.
  assert.equal(row([task('paused'), review('paused')]).group, 'paused');
  assert.equal(row([task('in_progress'), review('paused')]).group, 'working');

  // The reviewer's live terminal is the task's, not a session of its own.
  const terms = [{ address: 't9', state: 'live', cwd: '/r/dudu', labels: { task: 'dudu-drag-review' }, status: 'working' }];
  const live = [{ address: 't9', status: 'working', tab: 1 }];
  const list = threadList(pm, foldReviews([task('review'), review('in_progress')]), [], terms, live);
  assert.deepEqual([list.sessions.length, list.open.length], [0, 1]);
  // Without its review folded in, that same terminal is a session (the case the rule above changes).
  assert.equal(threadList(pm, [task('review')], [], terms, live).sessions.length, 1);

  // Over: the log names the review, without review_of (as pm.py records it); it is no row of its own.
  const events = [
    { at: '2026-11-15 02:59:00', type: 'thread', task: 'dudu-drag', title: '标题栏拖动窗口', status: 'in_progress', by: 'hc:t5k', text: '派给 window-drag' },
    { at: '2026-11-15 03:10:00', type: 'thread', task: 'dudu-drag-review', title: '审查：标题栏拖动窗口', status: 'in_progress', by: 'hc:t5k', text: '开始审查' },
    { at: '2026-11-15 03:20:00', type: 'thread', task: 'dudu-drag-review', title: '审查：标题栏拖动窗口', status: 'done', by: 'hc:t5r', text: 'status=done; 无阻塞' },
  ];
  assert.deepEqual(threadList(pm, foldReviews([task('review'), review('done')]), events).finished, []);
  // Retired with its task, both gone from the board: the task's row is the one that ended.
  const merged = [...events, { at: '2026-11-15 03:30:00', type: 'thread', task: 'dudu-drag', title: '标题栏拖动窗口', status: 'merged', by: 'hc:t5k', text: 'status=merged' }];
  assert.deepEqual(threadList(pm, [], merged).finished.map(r => r.task), ['dudu-drag']);
  // A review whose task the log never names stays a row of its own.
  assert.deepEqual(threadList(pm, [], events.slice(1)).finished.map(r => r.task), ['dudu-drag-review']);
});

test("a project on another machine: its key, its terminals as that machine names them, pm.py run there", async () => {
  assert.deepEqual(model.projectRef({ pm: 'box/pm-dudu', machine: 'box' }), { key: 'box/pm-dudu', machine: 'box', name: 'pm-dudu' });
  assert.deepEqual(model.projectRef({ pm: 'pm-dudu' }), { key: 'pm-dudu', machine: '', name: 'pm-dudu' });
  // A machine that does not prefix the key is not trusted: the key is read as a local PM's.
  assert.deepEqual(model.projectRef({ pm: 'pm-dudu', machine: 'box' }), { key: 'pm-dudu', machine: '', name: 'pm-dudu' });
  assert.deepEqual(model.projectRef(null), { key: '', machine: '', name: '' });

  // The ledger there says hc:t73; this app lists that terminal as box/t73, beside a local t73 of another PM.
  const terms = [{ address: 't73', state: 'live', labels: { pm: 'other' } },
    { address: 'box/t73', state: 'live', labels: { pm: 'dudu' } },
    { address: 'box/t9', state: 'live', parent: 'box/t73', labels: { task: 'dudu-a' } },
    { address: 'vps/t73', state: 'live', labels: { pm: 'dudu' } }];
  const seen = model.machineView(terms, 'box');
  assert.deepEqual(seen.map(t => [t.address, t.parent ?? '']), [['t73', ''], ['t9', 't73']]);
  assert.equal(model.machineView(terms, ''), terms);
  const pm = { name: 'pm-dudu', project: 'dudu', pane: 'hc:t73' };
  assert.equal(model.terminalFor(model.pmRow(pm), seen).address, 't73');
  assert.equal(model.terminalFor(model.taskRow({ id: 'dudu-a', pane: 'hc:t9' }), seen).address, 't9');
  // Focused and sent to by the app's own address again.
  assert.equal(model.onMachine('t73', 'box'), 'box/t73');
  assert.equal(model.onMachine('t73', ''), 't73');
  assert.equal(model.onMachine('', 'box'), '');
  assert.deepEqual(model.sendArgv(model.onMachine('t73', 'box'), 'hi'), ['hc', 'send', '--', 'box/t73', 'hi']);

  // remotePmArgv: the first pm.py found under that machine's home, with the arguments as given.
  assert.deepEqual(model.PM_SCRIPTS, dash.PM_SCRIPTS);
  const { execFileSync } = await import('node:child_process');
  const { mkdtempSync, mkdirSync, writeFileSync, rmSync } = await import('node:fs');
  const { tmpdir } = await import('node:os');
  const { join, dirname } = await import('node:path');
  const dir = mkdtempSync(join(tmpdir(), 'pm-remote-'));
  try {
    const script = join(dir, model.PM_SCRIPTS[1]);
    mkdirSync(dirname(script), { recursive: true });
    writeFileSync(script, 'import json, os, sys\nprint(json.dumps([sys.argv[1:], os.environ.get("HC_TERMINAL_ID")]))\n');
    const [command, args] = model.remotePmArgv(['reattach', 'a "b" $c']);
    const out = execFileSync(command, args, { env: { HOME: dir, PATH: process.env.PATH, HC_TERMINAL_ID: 't1' }, encoding: 'utf8' });
    assert.deepEqual(JSON.parse(out), [['reattach', 'a "b" $c'], null]);
    rmSync(script);
    assert.throws(() => execFileSync(command, args, { env: { HOME: dir, PATH: process.env.PATH }, stdio: 'pipe' }), /pm.py not found/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("a remote project's view reads that machine's ledger and sends to its terminals by their app address", async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '').replace('export default class PmProject extends View', 'return class');
  const calls = [];
  let drafts = null, failSend = false;
  const blank = new Proxy(function () {}, { get: (_, key) => (key === Symbol.toPrimitive ? () => 0 : blank), apply: () => blank });
  const stubs = { View: class {}, projectRef: model.projectRef, machineView: model.machineView, onMachine: model.onMachine,
    remotePmArgv: model.remotePmArgv, sendArgv: model.sendArgv, withoutTerminalEnv: model.withoutTerminalEnv,
    SEND_ENV: model.SEND_ENV, REATTACH_ENV: model.REATTACH_ENV, pmRow: model.pmRow, terminalFor: model.terminalFor,
    pasteDir: model.pasteDir, uploadSteps: model.uploadSteps, landedPath: model.landedPath, sentFiles: model.sentFiles,
    heldFiles: model.heldFiles, sentLeftovers: model.sentLeftovers, staleArgv: model.staleArgv, staleFiles: model.staleFiles,
    localStorage: { getItem: () => drafts }, readDrafts: model.readDrafts,
    messageText: model.messageText, word: model.word, fileName: model.fileName,
    appWindow: () => ({ platform: 'macos' }),
    terminals: () => [{ address: 't73', state: 'live', labels: { pm: 'dudu' } }, { address: 'box/t73', state: 'live', labels: { pm: 'dudu' } }],
    agents: () => [], panes: () => [],
    exec: async (command, args, options) => {
      calls.push([command, args, options]);
      const put = args?.indexOf('put') ?? -1;
      if (failSend && args?.includes('send')) return { code: 1, stdout: '', stderr: 'no terminal' };
      if (command === 'find') return { code: 0, stdout: '/here/attachments/box/pm-dudu/paste-20261101-101500.png\n/here/attachments/box/pm-dudu/paste-20261116-101500.png\n', stderr: '' };
      if (put < 0) return { code: 0, stdout: '', stderr: '' };
      const name = model.fileName(args[args.length - 1]);
      if (name.startsWith('huge')) return { code: 2, stdout: '{"error":{"message":"too big to send to box (16 MB at most)"}}', stderr: '' };
      return { code: 0, stdout: `{"bytes":1,"path":"/home/x/.local/state/herdr-core/default/files/t73/${name}"}`, stderr: '' };
    },
    readTextFile: async (path, options) => { calls.push(['read', path, options]); return null; } };
  const scope = new Proxy(stubs, {
    has: (target, name) => name in target || !(name in globalThis),
    get: (target, name) => (name in target ? target[name] : name === Symbol.unscopables ? undefined : blank),
  });
  const Mod = new Function('scope', `with (scope) { ${source} }`)(scope);
  const pm = { name: 'pm-dudu', project: 'dudu', pane: 'hc:t73', conversation: '/Users/x/.claude/pm/projects/dudu/conversation.jsonl' };
  const view = Object.assign(Object.create(Mod.prototype), { machine: 'box', pmName: 'box/pm-dudu', stateFor: 'box',
    state: { pms: [pm], tasks: [] }, remoteHome: '/Users/x/.claude/pm', ledgerHome: '/here', thread: 'dudu-a', pending: [] });
  const cx = { spawn: f => f(cx), notify() {} };
  assert.equal(view.pm(), pm);
  assert.equal(view.pmTerminal().address, 't73');
  await view.send(view.pmTerminal().address, 'hi');
  view.readLog(cx); view.readThread(cx);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.deepEqual(calls[0], ['env', ['-u', 'HC_TERMINAL_ID', 'hc', 'send', '--', 'box/t73', 'hi'], { timeout: 20000 }]);
  // The log's tail and the thread's file come from that machine (exec / readTextFile `on`); the
  // screenshots pasted for it are kept here, in this computer's ledger home.
  assert.deepEqual(calls.slice(1).map(c => [c[0], c[2]?.on]).sort(), [['read', 'box'], ['sh', undefined], ['sh', 'box']]);
  assert.equal(calls.find(c => c[0] === 'sh' && !c[2]?.on)[1].at(-1), '/here/attachments/box/pm-dudu');
  assert.equal(calls.find(c => c[0] === 'read')[1], '/Users/x/.claude/pm/tasks/dudu-a.json');
  // Files go to that machine first, beside the PM's terminal there, and the message names where they landed.
  calls.length = 0;
  const shot = '/here/attachments/box/pm-dudu/paste-20261116-101500.png', doc = '/Users/me/Desktop/a b.txt';
  const went = await view.deliver('t73', '看图', [shot, doc]);
  const there = name => `/home/x/.local/state/herdr-core/default/files/t73/${name}`;
  const envHc = argv => model.withoutTerminalEnv(argv)[1];
  assert.deepEqual(calls.map(c => c[1]), [envHc(model.putArgv('box/t73', shot)), envHc(model.putArgv('box/t73', doc)),
    envHc(model.sendArgv('box/t73', `看图\n\n${there('paste-20261116-101500.png')}\n${there('a b.txt')}`))]);
  assert.equal(went, `看图\n\n${there('paste-20261116-101500.png')}\n${there('a b.txt')}`);
  // Windows Desktop: bare hc, never `env -u` (no usable env there).
  calls.length = 0;
  const win = Object.assign(Object.create(Mod.prototype), view, { hostPlatform: () => 'windows' });
  await win.send('t73', 'hi');
  assert.deepEqual(calls[0], ['hc', ['send', '--', 'box/t73', 'hi'], { timeout: 20000 }]);
  calls.length = 0;
  await win.deliver('t73', '看图', [shot]);
  assert.deepEqual(calls.map(c => [c[0], c[1]]), [
    ['hc', ['put', '--json', '--', 'box/t73', shot]],
    ['hc', ['send', '--', 'box/t73', `看图\n\n${there('paste-20261116-101500.png')}`]],
  ]);
  // A file that does not go stops the send: nothing reaches the terminal, and the error names the file and machine.
  calls.length = 0;
  await assert.rejects(view.deliver('t73', 'x', [shot, '/Users/me/huge.png']),
    e => e.upload === true && /huge\.png was not copied to box: too big to send to box/.test(e.message));
  assert.ok(!calls.some(c => c[1].includes('send')));
  // A name hc put would garble goes as a renamed copy, made in a folder of this send's own that is removed after.
  calls.length = 0;
  const zh = '/Users/me/Desktop/设计稿 v2.png';
  const sentZh = await view.deliver('t73', '', [zh]);
  const copy = calls.find(c => c[0] === 'sh');
  assert.match(copy[1][3], /^\/here\/attachments\/box\/pm-dudu\/sending-\d+-\d+$/);
  assert.equal(copy[1][4], zh);
  assert.match(model.fileName(copy[1][5]), /^image-\d{8}-\d{6}-1-v2\.png$/);
  const putZh = calls.find(c => c[1].includes('put'));
  assert.equal(putZh[1].at(-1), copy[1][5]);
  assert.ok(calls.some(c => c[0] === 'rm' && c[1].join(' ') === `-rf -- ${copy[1][3]}`), 'the folder of copies is removed');
  assert.ok(calls.some(c => c[0] === 'find'), 'putting a copy there tidies what is a week old');
  // The message names the copy where it landed: an ASCII name, no "_" for the characters hc would have dropped.
  assert.equal(sentZh.split('\n').at(-1), there(model.fileName(copy[1][5])));
  assert.ok(!sentZh.includes('_'), sentZh);
  // A send whose second file failed, sent again: the first is not copied again, its landed path is named.
  calls.length = 0;
  // (the shot went with the failed send above, so this one, failing the same way, copies only huge.png)
  await assert.rejects(view.deliver('t73', 'x', [shot, '/Users/me/huge.png']), e => e.upload === true);
  assert.deepEqual(calls.filter(c => c[1].includes('put')).map(c => c[1].at(-1)), ['/Users/me/huge.png']);
  calls.length = 0;
  const retried = await view.deliver('t73', 'x', [shot, '/Users/me/ok.png']);
  assert.deepEqual(calls.map(c => c[1]), [envHc(model.putArgv('box/t73', '/Users/me/ok.png')),
    envHc(model.sendArgv('box/t73', `x\n\n${there('paste-20261116-101500.png')}\n${there('ok.png')}`))]);
  assert.equal(retried, `x\n\n${there('paste-20261116-101500.png')}\n${there('ok.png')}`);
  // The same when the files all went and the message itself did not: sent again, only the message goes.
  failSend = true;
  await assert.rejects(view.deliver('t73', 'y', [shot]));
  failSend = false;
  calls.length = 0;
  await view.deliver('t73', 'y', [shot]);
  assert.deepEqual(calls.map(c => c[1]), [envHc(model.sendArgv('box/t73', `y\n\n${there('paste-20261116-101500.png')}`))]);
  // Once it went, the next send of that file copies it again (nothing is remembered past a send).
  calls.length = 0;
  await view.deliver('t73', 'y', [shot]);
  assert.equal(calls.filter(c => c[1].includes('put')).length, 1);
  // After a send went, its pasted screenshots are removed here; the person's own files and held ones are not.
  calls.length = 0;
  const shot2 = '/here/attachments/box/pm-dudu/paste-20261116-101600.png';
  drafts = JSON.stringify({ 'thread:box/dudu-a': { text: '', at: Date.now(), files: [shot2] } });
  view.pending = [{ id: 7, files: [shot] }];
  view.cleanSent([shot, doc, shot2], 7);
  assert.deepEqual(calls.map(c => c[1]), [['-f', '--', shot]]);
  // The week-old ones go when a screenshot is pasted, except what a box still holds.
  calls.length = 0;
  drafts = JSON.stringify({ 'pm:box/pm-dudu': { text: '', at: Date.now(), files: ['/here/attachments/box/pm-dudu/paste-20261116-101500.png'] } });
  view.prune();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.deepEqual(calls.map(c => [c[0], c[1]]), [['find', ['/here/attachments', '-mindepth', '3', '-mmin', '+10080']],
    ['rm', ['-rf', '--', '/here/attachments/box/pm-dudu/paste-20261101-101500.png']]]);
  view.pending = [];
  drafts = null;
  // A local project's files go as they are: no copy, the message names them here.
  calls.length = 0;
  await Object.assign(Object.create(Mod.prototype), { machine: '' }).deliver('t73', '看图', [shot]);
  assert.deepEqual(calls.map(c => c[1]), [envHc(model.sendArgv('t73', `看图\n\n${shot}`))]);
  // Before that machine's ledger is read, the view has no project from another one's state.
  assert.equal(Object.assign(view, { stateFor: '' }).pm(), null);
});

test('a message to a project on another machine first copies each file beside its terminal there, then names where it landed', () => {
  const { uploadSteps, putArgv, landedPath, sentFiles, messageText, splitMessage, sameMessage, pasteDir } = model;
  const shot = '/Users/me/.claude/pm/attachments/dev/dudu/paste-20261116-101500.png', doc = '/Users/me/Desktop/my notes.txt';
  // One `hc put` per file, each once, to the terminal as "<machine>/<address>", never through the shell.
  const steps = uploadSteps([shot, doc, shot], 't7p', 'dev');
  assert.deepEqual(steps, [
    { path: shot, key: `dev/t7p\n${shot}`, argv: ['hc', 'put', '--json', '--', 'dev/t7p', shot] },
    { path: doc, key: `dev/t7p\n${doc}`, argv: ['hc', 'put', '--json', '--', 'dev/t7p', doc] },
  ]);
  assert.deepEqual(putArgv('dev/t1', '-x.png').slice(-3), ['--', 'dev/t1', '-x.png']);
  // A project here sends its files as they are: nothing to copy.
  assert.deepEqual(uploadSteps([shot], 't7p', ''), []);
  assert.deepEqual(uploadSteps([], 't7p', 'dev'), []);
  // What hc put printed is where the file is on that machine (hc's real output, from a run against a second core).
  const there = '/home/me/.local/state/herdr-core/default/files/t7p/paste-20261116-101500.png';
  const there2 = '/home/me/.local/state/herdr-core/default/files/t7p/my_notes.txt';
  assert.equal(landedPath({ code: 0, stdout: `{"bytes":12,"path":"${there}"}\n`, stderr: '' }), there);
  // A failure throws hc's own words, so the bubble can say why.
  assert.throws(() => landedPath({ code: 2, stdout: '{"error":{"hint":"see `hc schema`","kind":"invalid_params","message":"too big to send to dev (16 MB at most)"}}', stderr: '' }),
    /too big to send to dev \(16 MB at most\)/);
  assert.throws(() => landedPath({ code: 3, stdout: '', stderr: '{"error":{"kind":"not_found","message":"no terminal \\"t9\\""}}' }), /no terminal "t9"/);
  assert.throws(() => landedPath({ code: 255, stdout: '', stderr: 'ssh: connect to host dev: Connection refused' }), /Connection refused/);
  assert.throws(() => landedPath({ code: 0, stdout: 'ok', stderr: '' }), /ok/);
  assert.throws(() => landedPath({ code: 0, stdout: '{"path":"relative.png"}', stderr: '' }));
  // The message names the remote paths, in the order the files were attached; the bubble (local paths) settles on its log line.
  const landed = new Map([[shot, there], [doc, there2]]);
  assert.deepEqual(sentFiles([shot, doc], landed), [there, there2]);
  assert.deepEqual(sentFiles([shot, doc], new Map([[shot, there]])), [there, doc]);
  const sent = messageText('看这张', sentFiles([shot, doc], landed));
  assert.equal(sent, `看这张\n\n${there}\n${there2}`);
  assert.deepEqual(splitMessage(sent), { text: '看这张', files: [there, there2] });
  assert.ok(sameMessage(sent, messageText('看这张', [shot, doc])));
  assert.deepEqual(settlePending([{ id: 1, text: messageText('看这张', [shot, doc]), sentAt: model.eventTime('2026-11-16 10:15:00') }],
    [{ at: '2026-11-16 10:15:02', type: 'user', text: sent }]), []);
  assert.equal(messageText('', sentFiles([shot], landed), '附件：'), `附件：\n${there}`);
  // A pasted screenshot of a remote project waits in this computer's ledger home; a local one beside its log.
  assert.equal(pasteDir(null, { machine: 'dev', name: 'dudu', home: '/Users/me/.claude/pm' }), '/Users/me/.claude/pm/attachments/dev/dudu');
  assert.equal(pasteDir(null, { machine: 'dev', name: 'dudu', home: '' }), '');
  assert.equal(pasteDir({ conversation: '/Users/me/.claude/pm/projects/dudu/conversation.jsonl' }, { home: '/x' }), '/Users/me/.claude/pm/projects/dudu/attachments');
  // A send whose file did not go is a failed bubble that says so in words (upload), unlike any other failure.
  const items = timeline([], [], { pending: [{ id: 2, text: messageText('看', [shot]), sentAt: 0, failed: 'paste.png 没传到 dev：x', upload: true },
    { id: 3, text: 'hi', sentAt: 0, failed: 'hc send: 1' }, { id: 4, text: 'yo', sentAt: 0, upload: true }] });
  const users = items.filter(i => i.kind === 'user');
  assert.deepEqual(users.map(u => Boolean(u.upload)), [true, false, false]);
  assert.equal(model.word('zh', 'uploadFailed', 'a.png', 'dev', 'too big'), 'a.png 没传到 dev：too big');
  assert.match(model.word('zh', 'remoteAttach', 'dev'), /传到 dev/);
});

test("a file whose name hc put would garble goes to another machine as a renamed copy, named so in the message", () => {
  const { uploadName, uploadSteps, putArgv, uploadKey } = model;
  const at = new Date(2026, 10, 16, 22, 15, 14);
  // hc put makes each non-ASCII character "_": 设计稿 v2.png landed as ____v2.png. A readable ASCII name instead.
  assert.equal(uploadName('设计稿 v2.png', at), 'image-20261116-221514-1-v2.png');
  assert.equal(uploadName('截图.PNG', at, 3), 'image-20261116-221514-3.PNG');
  assert.equal(uploadName('会议纪要.pdf', at, 2), 'file-20261116-221514-2.pdf');
  assert.equal(uploadName('说明', at), 'file-20261116-221514-1');
  assert.equal(uploadName('报告.文档', at), 'file-20261116-221514-1');
  assert.equal(uploadName('Café menu 2.jpg', at), 'image-20261116-221514-1-Caf-menu-2.jpg');
  // An ASCII name goes as it is (hc's own "_" for a space is still readable).
  assert.equal(uploadName('my notes.txt', at), '');
  assert.equal(uploadName('paste-20261116-221514.png', at), '');
  const stage = '/here/attachments/dev/dudu/sending-1-1';
  const zh = '/Users/me/Desktop/设计稿 v2.png', zh2 = '/Users/me/Desktop/图.jpg', plain = '/Users/me/Desktop/a b.txt';
  const steps = uploadSteps([zh, plain, zh2], 't7p', 'dev', { stage, at });
  assert.deepEqual(steps.map(s => [s.path, s.copy || '', s.argv.at(-1)]), [
    [zh, `${stage}/image-20261116-221514-1-v2.png`, `${stage}/image-20261116-221514-1-v2.png`],
    [plain, '', plain],
    [zh2, `${stage}/image-20261116-221514-2.jpg`, `${stage}/image-20261116-221514-2.jpg`],
  ]);
  assert.deepEqual(steps[0].argv, putArgv('dev/t7p', `${stage}/image-20261116-221514-1-v2.png`));
  // Without a folder to copy into, the file goes as it is (its name garbled, but it goes).
  assert.equal(uploadSteps([zh], 't7p', 'dev', { at }).at(0).argv.at(-1), zh);
  // A file already copied there by an earlier try of the same send is not copied again: its landed path is used.
  const there = '/home/me/.local/state/herdr-core/default/files/t7p/image-20261116-221514-1-v2.png';
  const uploaded = new Map([[uploadKey('t7p', 'dev', zh), there]]);
  const again = uploadSteps([zh, zh2], 't7p', 'dev', { stage, at, uploaded });
  assert.deepEqual(again[0], { path: zh, key: uploadKey('t7p', 'dev', zh), landed: there });
  assert.equal(again[1].copy, `${stage}/image-20261116-221514-1.jpg`);
  // Keyed by the terminal there: another terminal, or the same address on another machine, gets its own copy.
  assert.ok(uploadSteps([zh], 't9', 'dev', { stage, at, uploaded })[0].argv);
  assert.ok(uploadSteps([zh], 't7p', 'box', { stage, at, uploaded })[0].argv);
});

test("what waits here for another machine goes once sent, or after a week, unless a box or a bubble still holds it", () => {
  const { heldFiles, sentLeftovers, staleArgv, staleFiles, STALE_MINUTES } = model;
  const dir = '/here/attachments/dev/dudu', shot = `${dir}/paste-20261116-101500.png`, shot2 = `${dir}/paste-20261116-101600.png`;
  const mine = '/Users/me/Desktop/a.png';
  const drafts = { 'pm:dev/pm-dudu': { text: '', at: 1, files: [shot2] }, 'thread:x': { text: 'hi', at: 2 } };
  const held = heldFiles(drafts, [{ id: 1, files: [mine] }, { id: 2 }]);
  assert.deepEqual([...held].sort(), [mine, shot2].sort());
  // Sent: the pasted screenshots in the paste folder go; the person's own files never; nor what is still held.
  assert.deepEqual(sentLeftovers([shot, mine, shot2], dir, held), [shot]);
  assert.deepEqual(sentLeftovers([shot], '', held), []);
  assert.deepEqual(sentLeftovers([`${dir}x/paste.png`], dir), []);
  // A week: what find lists under <home>/attachments, past the machine and project folders.
  assert.equal(STALE_MINUTES, 10080);
  assert.deepEqual(staleArgv('/here'), ['find', '/here/attachments', '-mindepth', '3', '-mmin', '+10080']);
  assert.deepEqual(staleFiles(`${shot}\n${shot2}\n${dir}/sending-1-1\n\nfind: x: No such file\n`, held), [shot, `${dir}/sending-1-1`]);
  assert.deepEqual(staleFiles(''), []);
});

test('projectSlug derives the ledger slug across conversation paths, PM names and mixed-case projects', () => {
  const { projectSlug, projectEventsArgv, projectLogArgv, EVENT_LIMIT, LOG_LIMIT } = model;
  assert.equal(projectSlug({ name: 'pm-appkit', project: 'AppKit', conversation: '/Users/me/.claude/pm/projects/appkit/conversation.jsonl' }), 'appkit');
  assert.equal(projectSlug({ name: 'pm-_sandbox', project: '_sandbox', conversation: '/Users/me/.claude/pm/projects/_sandbox/conversation.jsonl' }), '_sandbox');
  assert.equal(projectSlug({ name: 'pm-_sandbox', project: '_sandbox', conversation: '' }), '_sandbox');
  assert.equal(projectSlug({ project: '_My_Repo!' }), '_my_repo');
  assert.equal(projectSlug({ project: '---' }), 'project');
  assert.equal(projectSlug({ name: 'pm-dudu', project: 'dudu', conversation: '' }), 'dudu');
  assert.equal(projectSlug({ project: 'My Cool Repo!' }), 'my-cool-repo');
  assert.equal(projectSlug(null), '');
  assert.equal(projectSlug({}), '');
  assert.deepEqual(projectEventsArgv('dudu'), ['project', 'events', 'dudu', '--limit', String(EVENT_LIMIT)]);
  assert.deepEqual(projectEventsArgv('dudu', { before: 4096, limit: 50 }), ['project', 'events', 'dudu', '--before', '4096', '--limit', '50']);
  assert.deepEqual(projectEventsArgv('dudu', { after: 8192 }), ['project', 'events', 'dudu', '--after', '8192', '--limit', String(EVENT_LIMIT)]);
  assert.deepEqual(projectLogArgv('dudu-proj-a'), ['project', 'log', 'dudu-proj-a', '--limit', String(LOG_LIMIT)]);
  assert.deepEqual(projectLogArgv('dudu-proj-a', { before: 60, limit: 30 }), ['project', 'log', 'dudu-proj-a', '--before', '60', '--limit', '30']);
});

test('paging back through conversation windows keeps concurrent tail appends and resets cleanly when replaced', () => {
  const { freshEventWindow, appendEventWindow, prependEventWindow } = model;
  const e = (n, offset) => ({ at: `2026-11-20 10:00:${String(n).padStart(2, '0')}`, type: n % 2 ? 'pm' : 'user', text: `m${n}`, offset });
  // Initial window [3, 4], bytes 300..500, with earlier messages before 300.
  let state = freshEventWindow({ events: [e(3, 400), e(4, 500), null, { bad: 1 }], from: 300, offset: 500, earlier: true });
  assert.deepEqual([state.events.map(x => x.text), state.from, state.offset, state.earlier], [['m3', 'm4'], 300, 500, true]);

  // While the user asks for --before 300, a new event m5 arrives at the tail (--after 500 -> 600).
  const askedFrom = state.from;
  state = appendEventWindow(state, { events: [e(4, 500), e(5, 600)], from: 500, offset: 600, earlier: true });
  assert.deepEqual([state.events.map(x => x.text), state.from, state.offset, state.earlier], [['m3', 'm4', 'm5'], 300, 600, true]);

  // Now the --before 300 response arrives with [1, 2]: both the earlier page AND m5 stay, with no duplicates.
  state = prependEventWindow(state, askedFrom, { events: [e(1, 200), e(2, 300)], from: 100, offset: 300, earlier: true });
  assert.deepEqual([state.events.map(x => x.text), state.from, state.offset, state.earlier], [['m1', 'm2', 'm3', 'm4', 'm5'], 100, 600, true]);

  // Final page reaches the start of the log (`from: 0, earlier: false`).
  state = prependEventWindow(state, 100, { events: [e(0, 100)], from: 0, offset: 100, earlier: false });
  assert.deepEqual([state.events.map(x => x.text), state.from, state.offset, state.earlier], [['m0', 'm1', 'm2', 'm3', 'm4', 'm5'], 0, 600, false]);

  // If the log was replaced on disk (`reset: true`), the incremental read adopts the new window and drops stale before-pages.
  const replaced = appendEventWindow(state, { events: [e(9, 80)], from: 0, offset: 80, earlier: false, reset: true });
  assert.deepEqual([replaced.events.map(x => x.text), replaced.from, replaced.offset, replaced.earlier], [['m9'], 0, 80, false]);
  assert.equal(prependEventWindow(replaced, 100, { events: [e(0, 100)], from: 0, offset: 100, earlier: false }), replaced);
});

test('thread log pagination merges earlier pages with newly appended entries by index n', () => {
  const { keepThreadLog, heldThreadLog } = model;
  const entry = n => ({ n, at: '2026-11-20 11:00', by: 'hc:t1', text: `entry ${n}` });
  const range = (a, b) => Array.from({ length: b - a }, (_, i) => entry(a + i));

  // Newest 60 of 130 entries: [70..129], earlier = 70.
  const newest1 = { entries: range(70, 130), earlier: 70, total: 130 };
  let kept = keepThreadLog([], newest1);
  let shown = heldThreadLog(newest1, kept);
  assert.deepEqual([shown.entries.length, shown.entries[0].n, shown.earlier, shown.total], [60, 70, 70, 130]);

  // Load earlier page before 70 -> [10..69].
  const older1 = { entries: range(10, 70), earlier: 10, total: 130 };
  kept = keepThreadLog(kept, older1);
  shown = heldThreadLog(shown, kept);
  assert.deepEqual([shown.entries.length, shown.entries[0].n, shown.earlier], [120, 10, 10]);

  // Worker appends 3 new entries (total 133); refresh reads newest 60 ([73..132]). Earlier pages [10..72] stay!
  const newest2 = { entries: range(73, 133), earlier: 73, total: 133 };
  kept = keepThreadLog(kept, newest2);
  shown = heldThreadLog(newest2, kept);
  assert.deepEqual([shown.entries.length, shown.entries[0].n, shown.entries.at(-1).n, shown.earlier, shown.total], [123, 10, 132, 10, 133]);

  // Final earlier page before 10 -> [0..9]: reaches n=0 (`earlier: 0`).
  const older2 = { entries: range(0, 10), earlier: 0, total: 133 };
  kept = keepThreadLog(kept, older2);
  shown = heldThreadLog(shown, kept);
  assert.deepEqual([shown.entries.length, shown.entries[0].n, shown.entries.at(-1).n, shown.earlier], [133, 0, 132, 0]);

  // Recreated shorter task clears stale entries.
  const fresh = { entries: range(0, 2), earlier: 0, total: 2 };
  kept = keepThreadLog(kept, fresh);
  assert.deepEqual(heldThreadLog(fresh, kept), fresh);
});

test('old remote pm.py is detected without surfacing an error, and scroll anchors skip shifting day headers', () => {
  const { isOldPmCommand, isReplacedLogError, timelineAnchor, findAnchorBlock, word } = model;
  assert.equal(isOldPmCommand({ code: 2, stderr: "pm.py: error: argument cmd: invalid choice: 'project' (choose from 'new', 'state')" }), true);
  assert.equal(isOldPmCommand({ code: 2, stderr: 'pm.py: error: unrecognized arguments: --after' }), true);
  assert.equal(isOldPmCommand({ code: 1, stderr: 'Permission denied: conversation.jsonl' }), false);
  assert.equal(isOldPmCommand({ code: 0, stdout: '{}' }), false);
  assert.equal(isReplacedLogError('conversation log is shorter than 9000: it was replaced'), true);
  assert.equal(isReplacedLogError('no line ends at byte 42'), true);
  assert.equal(isReplacedLogError('ssh: connect timeout'), false);
  assert.equal(word('zh', 'earlierLog', 12), '往前翻更早的 12 条记录');
  assert.equal(word('en', 'earlierLog', 1), 'Show 1 earlier entry');

  // Day divider at the top of the old window moves up when earlier messages from the same day arrive;
  // timelineAnchor anchors on the first real message/turn so the reader stays right above it.
  const late = [ev('14:30:00', 'user', { text: '下午好' }), ev('14:30:10', 'pm', { text: '你好！', by: 'hc:t1' })];
  const beforeBlocks = timelineRows(turns(timeline(late, [], { today: '2026-11-13' }), 'hc:t1'));
  const anchor = timelineAnchor(beforeBlocks);
  assert.equal(anchor.kind, 'user');
  const withMorning = [
    ev('09:00:00', 'user', { text: '早上好' }),
    ev('09:01:00', 'pm', { text: '早！', by: 'hc:t1' }),
    ...late,
  ];
  const afterBlocks = timelineRows(turns(timeline(withMorning, [], { today: '2026-11-13' }), 'hc:t1'));
  // afterBlocks: [0] day:2026-11-13, [1] user 09:00, [2] pm 09:01, [3] user 14:30, [4] pm 14:30:10
  assert.equal(findAnchorBlock(afterBlocks, anchor), 3);
});

test('PmProject view pages conversation and thread logs to the start, and hides earlier quietly on old remote pm.py', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '').replace('export default class PmProject extends View', 'return class');
  const calls = [];
  let oldRemote = false;
  const blank = new Proxy(function () {}, { get: (_, key) => (key === Symbol.toPrimitive ? () => 0 : blank), apply: () => blank });
  const stubs = {
    View: class {}, ...model,
    execPython: async (_exec, argv, opts) => stubs.exec('python3', argv, opts),
    appHome: () => '/app', home: () => '/Users/me',
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    appWindow: () => ({ platform: 'macos' }),
    terminals: () => [], agents: () => [], panes: () => [], spaces: () => [],
    exec: async (command, args, options) => {
      calls.push([command, args, options]);
      const joined = (args || []).join(' ');
      if (oldRemote && args?.includes('project')) {
        return { code: 2, stdout: '', stderr: "pm.py: error: argument cmd: invalid choice: 'project'" };
      }
      if (joined.includes('tail -n')) {
        return { code: 0, stdout: '{"at":"2026-11-20 10:00:00","type":"user","text":"tail-fallback"}\n', stderr: '' };
      }
      if (args?.includes('events')) {
        if (args.includes('--before')) {
          return { code: 0, stdout: JSON.stringify({ events: [{ at: '2026-11-20 09:00:00', type: 'user', text: 'oldest', offset: 100 }], from: 0, offset: 100, earlier: false }), stderr: '' };
        }
        if (args.includes('--after')) {
          return { code: 0, stdout: JSON.stringify({ events: [{ at: '2026-11-20 10:05:00', type: 'pm', text: 'appended', offset: 300 }], from: 200, offset: 300, earlier: true, more: false, reset: false }), stderr: '' };
        }
        return { code: 0, stdout: JSON.stringify({ events: [{ at: '2026-11-20 10:00:00', type: 'user', text: 'recent', offset: 200 }], from: 100, offset: 200, earlier: true }), stderr: '' };
      }
      if (args?.includes('log')) {
        if (args.includes('--before')) {
          return { code: 0, stdout: JSON.stringify({ entries: [{ n: 0, at: '2026-11-20 09:00', by: 'user', text: 'first log' }], earlier: 0, total: 2 }), stderr: '' };
        }
        return { code: 0, stdout: JSON.stringify({ entries: [{ n: 1, at: '2026-11-20 10:00', by: 'pm', text: 'latest log' }], earlier: 1, total: 2 }), stderr: '' };
      }
      return { code: 0, stdout: '', stderr: '' };
    },
    readTextFile: async () => JSON.stringify({ id: 'dudu-a', log: [{ at: '2026-11-20 10:00', by: 'pm', text: 'file log' }] }),
  };
  const scope = new Proxy(stubs, {
    has: (target, name) => name in target || !(name in globalThis),
    get: (target, name) => (name in target ? target[name] : name === Symbol.unscopables ? undefined : blank),
  });
  const Mod = new Function('scope', `with (scope) { ${source} }`)(scope);
  const pm = { name: 'pm-dudu', project: 'dudu', conversation: '/here/projects/dudu/conversation.jsonl' };
  const cx = { spawn: f => f(cx), notify() {} };
  const view = Object.assign(Object.create(Mod.prototype), {
    machine: '', pmName: 'pm-dudu', stateFor: '', state: { pms: [pm], tasks: [{ id: 'dudu-a', pm: 'pm-dudu', status: 'in_progress' }] },
    ledgerHome: '/here', remoteHome: '', remoteNoProject: '', logPath: '', logSlug: '', logState: null,
    events: [], pending: [], pastes: [], items: [], thread: '', detail: false, outgoing: new Map(),
    input: { set_value() {}, set_selected_range() {} }, threadInput: { set_value() {}, set_selected_range() {} },
    scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} },
  });

  // 1. Initial load + incremental append + paging backward to the start.
  view.readLog(cx);
  await new Promise(r => setTimeout(r, 10));
  assert.equal(view.logState.earlier, true);
  assert.deepEqual(view.events.map(e => e.text), ['recent']);

  view.readLog(cx); // --after 200
  await new Promise(r => setTimeout(r, 10));
  assert.deepEqual(view.events.map(e => e.text), ['recent', 'appended']);
  assert.equal(view.logState.earlier, true);

  view.loadEarlierEvents(model.timelineRows(model.turns(model.timeline(view.events, []))), cx);
  await new Promise(r => setTimeout(r, 10));
  assert.deepEqual(view.events.map(e => e.text), ['oldest', 'recent', 'appended']);
  assert.equal(view.logState.earlier, false);

  // 2. Thread log pagination to entry 0.
  view.openThread('dudu-a', cx);
  await new Promise(r => setTimeout(r, 10));
  assert.equal(view.threadLog.earlier, 1);
  view.loadEarlierThreadLog(cx);
  await new Promise(r => setTimeout(r, 10));
  assert.deepEqual([view.threadLog.entries.map(e => e.text), view.threadLog.earlier], [['first log', 'latest log'], 0]);

  // 3. Remote machine with old pm.py: hides earlier, falls back to tail / task file, sets no logError.
  oldRemote = true;
  const remoteView = Object.assign(Object.create(Mod.prototype), {
    ...view, machine: 'dev', pmName: 'dev/pm-dudu', stateFor: 'dev', remoteHome: '/remote', remoteNoProject: '',
    logPath: '', logSlug: '', logState: null, events: [], logError: '', thread: '', detail: false,
    threadLog: null, threadLogKept: [], threadEarlierError: '',
  });
  remoteView.readLog(cx);
  await new Promise(r => setTimeout(r, 10));
  assert.equal(remoteView.remoteNoProject, 'dev');
  assert.equal(remoteView.logError, '');
  assert.equal(remoteView.logState, null);
  assert.deepEqual(remoteView.events.map(e => e.text), ['tail-fallback']);

  remoteView.openThread('dudu-a', cx);
  await new Promise(r => setTimeout(r, 10));
  assert.equal(remoteView.threadLog, null);
  assert.equal(remoteView.threadEarlierError, '');

  // 4. Full render() and panel() passes with earlier controls idle, loading, errored and settling anchors.
  const scrolled = [], threadScrolled = [];
  const themeObj = {
    canvas: '#111111', surface: '#181818', raised: '#222222', chrome: '#161616', hover: '#2a2a2a',
    border: '#333333', input: '#3a3a3a', foreground: '#eeeeee', background: '#111111',
    muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', accent_foreground: '#ffffff',
    blocked: '#ff5f56', ansi2: '#27c93f', solid: '#eeeeee', solid_foreground: '#111111',
  };
  const renderCx = {
    spawn: f => f(renderCx), notify() {},
    timer: { after() {}, every() {} },
  };
  view.theme = () => themeObj;
  stubs.theme = () => themeObj;
  stubs.shared = () => ({ pm: 'pm-dudu' });
  stubs.layout = () => ({ id: 'pm-stage', active: 'pm-project' });
  view.scroll = { scroll_to_item: i => scrolled.push(i) };
  view.threadScroll = { scroll_to_item: i => threadScrolled.push(i) };
  view.keyFocus = { focus() {} };
  view.heights = new Map();
  view.unfolded = new Map();
  view.atWork = new Set();
  view.files = []; view.threadFiles = [];
  view.seen = null;
  view.count = 0; view.settle = 0; view.away = true; view.rise = 120;
  view.logState = { events: view.events, from: 100, offset: 300, earlier: true };
  view.detail = true;
  view.thread = 'dudu-a';
  view.threadLog = { entries: [{ n: 10, at: '2026-11-20 10:00', by: 'pm', text: 'latest' }], earlier: 10, total: 11 };
  const curBlocks = model.timelineRows(model.turns(model.timeline(view.events, view.state.tasks)));
  view.earlierAnchor = { anchor: model.timelineAnchor(curBlocks), left: 1 };
  view.threadAnchor = { n: 10, left: 1 };

  view.render(renderCx);
  // topOffset is 1 (earlierControl is child 0); curBlocks[0] is day divider, curBlocks[1] is oldest user message -> index 1 + 1 = 2.
  assert.deepEqual(scrolled, [2]);
  // earlierLogRow is child 0, entry n=10 is at index 0 -> 1 + 0 = 1.
  assert.deepEqual(threadScrolled, [1]);

  // Loading and error states also render without throwing.
  for (const [loading, err] of [[true, ''], [false, 'disk busy']]) {
    view.earlierLoading = loading; view.earlierError = err;
    view.threadEarlierLoading = loading; view.threadEarlierError = err;
    view.render(renderCx);
  }

  // 5. Regression: loadEarlierEvents does not over-fetch a second page when `this.items` contains pending/typing items.
  oldRemote = false;
  let beforeFetches = 0;
  const origExec = stubs.exec;
  stubs.exec = async (command, args, options) => {
    if (args?.includes('events') && args.includes('--before')) {
      beforeFetches++;
      const step = beforeFetches;
      return {
        code: 0,
        stdout: JSON.stringify({
          events: [{ at: `2026-11-20 08:0${step}:00`, type: 'user', text: `page-${step}`, offset: 100 - step * 10 }],
          from: step === 1 ? 50 : 0,
          offset: 100 - (step - 1) * 10,
          earlier: step === 1, // still true after page 1, so over-fetching would pull page 2!
        }),
        stderr: '',
      };
    }
    return origExec(command, args, options);
  };
  const typingView = Object.assign(Object.create(Mod.prototype), {
    ...view, machine: '', pmName: 'pm-dudu', stateFor: '', remoteNoProject: '',
    earlierLoading: false, earlierError: '', earlierAnchor: null,
    rise: 0, away: false, tall: 600, high: 680, // dragged scrollbar to top (rise was still 0)
    events: [{ at: '2026-11-20 10:00:00', type: 'user', text: 'recent', offset: 200 }],
    logPath: '/here/projects/dudu/conversation.jsonl', logSlug: 'dudu',
    logState: { events: [{ at: '2026-11-20 10:00:00', type: 'user', text: 'recent', offset: 200 }], from: 100, offset: 200, earlier: true },
  });
  // Inflate `this.items` with both `pending` and `typing` (+2 items over pure `events` timeline).
  typingView.items = model.timeline(typingView.events, [], { pending: [{ id: 1, text: 'on the way', sentAt: Date.now() }], typing: true });
  typingView.loadEarlierEvents(model.timelineRows(model.turns(typingView.items)), cx);
  await new Promise(r => setTimeout(r, 15));
  assert.equal(beforeFetches, 1, 'must stop after 1 earlier page even while PM is typing and a bubble is pending');
  assert.deepEqual(typingView.events.map(e => e.text), ['page-1', 'recent']);
  // Paging back raises `rise` to at least viewport height so a gentle downward scroll does not clear `away`.
  assert.equal(typingView.rise, 600);
  assert.equal(typingView.away, true);
  typingView.rest(model.riseAfterWheel(typingView.rise, -30, 2000, typingView.tall));
  assert.equal(typingView.rise, 510);
  assert.equal(typingView.away, true);

  // 6. Regression: switching thread A -> B while A's readThreadLog is in flight still fetches B's log and earlier count.
  let releaseA;
  const gateA = new Promise(resolve => { releaseA = resolve; });
  stubs.exec = async (command, args, options) => {
    if (args?.includes('log')) {
      const target = args[args.indexOf('log') + 1];
      if (target === 'dudu-a') {
        await gateA;
        return { code: 0, stdout: JSON.stringify({ entries: [{ n: 5, at: '2026-11-20 10:00', by: 'pm', text: 'log A' }], earlier: 5, total: 6 }), stderr: '' };
      }
      if (target === 'dudu-b') {
        return { code: 0, stdout: JSON.stringify({ entries: [{ n: 12, at: '2026-11-20 10:05', by: 'pm', text: 'log B' }], earlier: 12, total: 13 }), stderr: '' };
      }
    }
    return origExec(command, args, options);
  };
  const switchView = Object.assign(Object.create(Mod.prototype), {
    ...typingView, state: { pms: [pm], tasks: [{ id: 'dudu-a', pm: 'pm-dudu', status: 'in_progress' }, { id: 'dudu-b', pm: 'pm-dudu', status: 'in_progress' }] },
    thread: '', detail: false, threadTask: null, threadLog: null, threadLogKept: [], threadLogLoading: false, threadLogAgain: false,
  });
  switchView.openThread('dudu-a', cx);     // starts readThreadLog('dudu-a'), suspended on gateA
  assert.equal(switchView.threadLogLoading, true);
  switchView.openThread('dudu-b', cx);     // switches to B while A is still loading -> sets threadLogAgain = true
  assert.equal(switchView.thread, 'dudu-b');
  assert.equal(switchView.threadLogAgain, true);
  releaseA();
  await new Promise(r => setTimeout(r, 20));
  assert.equal(switchView.threadLog?.earlier, 12, 'thread B log and earlier entry must load immediately after A finishes');
  assert.deepEqual(switchView.threadLog?.entries.map(e => e.text), ['log B']);
});

test('i18n parity: en & zh share all keys, panel strings use Library/Memory (never Context), and all 6 topics + 5 types are translated', () => {
  const { STRINGS, word, MEMORY_TOPICS, PROJECT_MEMORY_TYPES, PERSONAL_MEMORY_TYPES, topicLabel, memoryTypeLabel } = model;
  const enKeys = Object.keys(STRINGS.en).sort();
  const zhKeys = Object.keys(STRINGS.zh).sort();
  assert.deepEqual(enKeys, zhKeys, 'en and zh STRINGS must have identical keys');
  assert.equal(word(undefined, 'libraryTab'), 'Library', 'English is the default language');
  assert.equal(word('zh', 'libraryTab'), 'Library', 'Chinese interface also calls it Library');
  assert.equal(word('en', 'memoryTab'), 'Memory');
  assert.equal(word('zh', 'memoryTab'), 'Memory');

  // Panel-facing strings must not say "Context" (token usage keys like contextUsage keep Context/上下文).
  const tokenKeys = new Set(['contextUsage', 'pmContextNormal', 'pmContextNear', 'pmContextOver', 'workerContextTip']);
  for (const lang of ['en', 'zh']) {
    for (const key of enKeys) {
      if (tokenKeys.has(key)) continue;
      const val = STRINGS[lang][key];
      const text = typeof val === 'function' ? val('ERR', 'ARG', 'THIRD') : String(val);
      assert.equal(/\bcontext\b/i.test(text), false, `STRINGS.${lang}.${key} still mentions Context: ${text}`);
    }
  }

  // All 6 fixed memory topics in both languages.
  assert.deepEqual(MEMORY_TOPICS.map(t => topicLabel('en', t)), [
    'Product & architecture', 'Interface & interaction', 'Collaboration & dispatch',
    'Environment & release', 'Reference', 'Engineering pitfalls',
  ]);
  assert.deepEqual(MEMORY_TOPICS.map(t => topicLabel('zh', t)), [
    '产品与架构', '界面与交互', '协作与派活', '环境与发版', '参考', '工程踩坑',
  ]);

  // All 5 memory types in both languages.
  const allTypes = [...new Set([...PROJECT_MEMORY_TYPES, ...PERSONAL_MEMORY_TYPES])];
  assert.deepEqual(allTypes.map(t => [t, memoryTypeLabel('en', t), memoryTypeLabel('zh', t)]), [
    ['project', 'Decision', '决定'],
    ['feedback', 'Feedback', '做法'],
    ['reference', 'Reference', '参考'],
    ['pitfall', 'Pitfall', '踩坑'],
    ['user', 'User', '关于你'],
  ]);
});

test('libraryGroups & memoryGroups organize allow-listed docs, research, instructions, decisions archive, 6 topics & folded pitfalls/personal', () => {
  const {
    libraryGroups, memoryGroups, projectLibraryArgv, projectMemoryArgv, projectFileArgv,
    projectSaveArgv, projectDeleteArgv, projectRestoreArgv, projectHistoryArgv, projectAddArgv,
    projectRetopicArgv, isOldPmCommand,
  } = model;
  assert.deepEqual(projectLibraryArgv('dudu'), ['project', 'library', 'dudu']);
  assert.deepEqual(projectMemoryArgv('dudu'), ['project', 'memory', 'dudu']);
  assert.deepEqual(projectFileArgv('dudu', 'docs', '-weird.md'), ['project', 'file', '--root', 'docs', '--', 'dudu', '-weird.md']);
  assert.deepEqual(projectSaveArgv('dudu', 'memory', 'my-rule.md', { text: '---\nname: my-rule\n---\n', ifVersion: 'v1' }),
    ['project', 'save', '--root', 'memory', '--text=---\nname: my-rule\n---\n', '--if-version=v1', '--', 'dudu', 'my-rule.md']);
  assert.deepEqual(projectDeleteArgv('dudu', 'docs', 'a.md', { ifVersion: 'v1' }),
    ['project', 'delete', '--root', 'docs', '--if-version=v1', '--', 'dudu', 'a.md']);
  assert.deepEqual(projectRestoreArgv('dudu', 'docs', 'a.md', { version: '20261121-100000' }),
    ['project', 'restore', '--root', 'docs', '--version=20261121-100000', '--', 'dudu', 'a.md']);
  assert.deepEqual(projectHistoryArgv('dudu', 'memory'), ['project', 'history', '--root', 'memory', '--', 'dudu']);
  assert.deepEqual(projectAddArgv('dudu', '/tmp/spec.pdf'), ['project', 'add', '--', 'dudu', '/tmp/spec.pdf']);
  assert.deepEqual(projectRetopicArgv('dudu', 'r1', { topic: 'ui', type: 'project' }),
    ['project', 'retopic', '--topic=ui', '--type=project', '--', 'dudu', 'r1']);
  assert.equal(isOldPmCommand({ code: 2, stderr: "pm.py: error: argument project_cmd: invalid choice: 'library'" }), true);
  assert.equal(isOldPmCommand({ code: 2, stderr: "pm.py: error: argument project_cmd: invalid choice: 'memory'" }), true);
  assert.equal(isOldPmCommand({ code: 2, stderr: "pm.py: error: argument project_cmd: invalid choice: 'file'" }), true);

  const libFiles = [
    { root: 'docs', path: 'spec.md', kind: 'md', size: 2048, modified: '2026-11-21T12:00:00Z', show: 'text', writable: true, version: 'v-spec' },
    { root: 'docs', path: 'decisions.md', kind: 'md', size: 18500, modified: '2026-11-19T08:00:00Z', show: 'text', writable: false, archive: true, hidden: false, entries: 16 },
    { root: 'docs', path: 'notes', kind: 'folder', size: 0, modified: '2026-11-21T09:00:00Z', writable: true },
    { root: 'docs', path: 'notes/design.md', kind: 'md', size: 512, modified: '2026-11-21T09:00:00Z', show: 'text', writable: true },
    { root: 'research', path: 'evidence/library-design/README.md', kind: 'md', size: 46000, modified: '2026-11-21T21:55:00Z', show: 'text', writable: false,
      title: '项目 Library 与 Memory 架构调研', summary: 'Library 只放文档与调研报告。', task: 'dudu-library-design', task_title: '调研：Library 该收什么' },
    { root: 'research', path: 'evidence/no-h1-topic/README.md', kind: 'md', size: 500, modified: '2026-11-20T10:00:00Z', show: 'text', writable: false },
    { root: 'instructions', path: 'CLAUDE.md', kind: 'md', size: 1200, modified: '2026-11-20T10:00:00Z', show: 'text', writable: false, title: 'Project Rules' },
  ];

  const groups = libraryGroups(libFiles, new Set(), 'zh', '2026');
  assert.deepEqual(groups.map(g => [g.id, g.title, g.count, g.readOnly]), [
    ['docs', '项目文档', 3, false],
    ['research', '调研报告', 2, true],
    ['instructions', '仓库说明', 1, true],
  ]);
  assert.deepEqual(groups[0].rows.map(r => [r.key, r.depth, r.kindLabel, r.writable]), [
    ['docs/notes', 0, '1 项', false],
    ['docs/notes/design.md', 1, 'Markdown', true],
    ['docs/spec.md', 0, 'Markdown', true],
    ['docs/decisions.md', 0, '历史归档 · 16 条', false],
  ]);
  assert.deepEqual(groups[1].rows.map(r => [r.title, r.task, r.readOnly]), [
    ['项目 Library 与 Memory 架构调研', 'dudu-library-design', true],
    ['no-h1-topic', '', true],
  ]);
  assert.deepEqual(groups[2].rows.map(r => [r.title, r.readOnly]), [['CLAUDE.md', true]]);

  const afterArchive = libraryGroups(libFiles.map(f => (f.path === 'decisions.md' ? { ...f, hidden: true } : f)), new Set(), 'zh', '2026');
  assert.equal(afterArchive[0].count, 2);
  assert.equal(afterArchive[0].rows.some(r => r.path === 'decisions.md'), false);

  const collapsed = libraryGroups(libFiles, new Set(['docs/notes']), 'en', '2026');
  assert.equal(collapsed[0].count, 3);
  assert.deepEqual(collapsed[0].rows.map(r => r.key), ['docs/notes', 'docs/spec.md', 'docs/decisions.md']);

  const memPayload = {
    topics: model.MEMORY_TOPICS.map(id => ({ id, folded: id === 'pitfalls' })),
    files: [
      { layer: 'project', root: 'memory', path: 'lib-split.md', name: 'lib-split', type: 'project', topic: 'ui',
        description: 'Library 只放文档和调研报告', modified: '2026-11-22T01:00:00Z' },
      { layer: 'project', root: 'memory', path: 'parallel.md', name: 'parallel', type: 'feedback', topic: 'workflow',
        description: 'Run independent threads in parallel', modified: '2026-11-21T09:00:00Z' },
      { layer: 'project', root: 'memory', path: 'osc-trap.md', name: 'osc-trap', type: 'pitfall', topic: 'pitfalls',
        description: 'OSC 7501 uses colon separator', modified: '2026-11-22T02:00:00Z' },
      { layer: 'personal', root: 'personal', path: 'reply-in-chinese.md', name: 'reply-in-chinese', type: 'feedback', topic: 'workflow',
        description: 'Always reply in Chinese', modified: '2026-11-15T03:00:00Z' },
    ],
    candidates: [
      { worker: 'w1', name: 'shell-du', path: 'w1/shell-du.md', type: 'project', description: 'du is aliased to dust', modified: '2026-11-21T10:00:00Z' },
    ],
    history: { project: 2, personal: 1 },
  };
  const mgZh = memoryGroups(memPayload, {}, 'zh', '2026');
  assert.equal(mgZh.project.open, true);
  assert.equal(mgZh.project.count, 3);
  assert.deepEqual(mgZh.project.primaryTopics.map(t => [t.id, t.title, t.open, t.dimmed]), [
    ['ui', '界面与交互', true, false],
    ['workflow', '协作与派活', true, false],
  ]);
  assert.deepEqual(mgZh.project.foldedTopics.map(t => [t.id, t.title, t.open, t.dimmed]), [
    ['pitfalls', '工程踩坑', false, true],
  ]);
  assert.equal(mgZh.project.foldedTopics[0].rows[0].typeLabel, '踩坑');
  assert.equal(mgZh.candidates.open, false);
  assert.equal(mgZh.candidates.dimmed, true);
  assert.equal(mgZh.personal.open, false);
  assert.equal(mgZh.personal.count, 1);
  assert.equal(mgZh.personal.rows[0].typeLabel, '做法');
});

test('searchLibrary, searchMemory (>64KB documentView find), frontmatter builders, retopicPlan, and escapeStep', () => {
  const {
    searchLibrary, searchMemory, documentView, parseFrontmatter, buildMemoryMarkdown,
    memoryFromDroppedFile, retopicPlan, resolveContextLink, escapeStep, keepDocCache,
  } = model;
  const libFiles = [
    { root: 'docs', path: 'decisions.md', kind: 'md', size: 500, modified: '2026-11-20T08:00:00Z', show: 'text', writable: false, archive: true, hidden: false },
    { root: 'research', path: 'evidence/at-mention/README.md', kind: 'md', size: 1200, modified: '2026-11-21T18:00:00Z', show: 'text', writable: false,
      title: '输入框的 @ 设计', summary: '参考 Cursor 设计行内胶囊', task: 'dudu-cursor' },
  ];
  let cache = keepDocCache(new Map(), 'docs/decisions.md', {
    text: '- 2026-11-10 连线只用直线和曲线，不要直角线 — 用户原话：「不要有直角线」\n',
    size: 90,
  });

  const hitsLib = searchLibrary(libFiles, '直角线', cache, 'zh', '2026');
  assert.equal(hitsLib.length, 1);
  assert.equal(hitsLib[0].key, 'docs/decisions.md');
  assert.match(hitsLib[0].desc, /不要直角线/);
  assert.equal(searchLibrary(libFiles, '行内胶囊', cache, 'zh', '2026')[0].title, '输入框的 @ 设计');

  // SearchMemory searches across folded pitfalls and folded personal memories too.
  const memPayload = {
    files: [
      { layer: 'project', root: 'memory', path: 'osc-trap.md', name: 'osc-trap', type: 'pitfall', topic: 'pitfalls',
        description: 'OSC 7501 uses colon separator', modified: '2026-11-22T02:00:00Z' },
      { layer: 'personal', root: 'personal', path: 'reply-in-chinese.md', name: 'reply-in-chinese', type: 'feedback', topic: 'workflow',
        description: 'Always reply to the user in Chinese', modified: '2026-11-15T03:00:00Z' },
    ],
  };
  const hitsPitfall = searchMemory(memPayload, 'colon', cache, 'en', '2026');
  assert.deepEqual(hitsPitfall.map(h => [h.key, h.typeLabel, h.topicLabel]), [
    ['memory/osc-trap.md', 'Pitfall', 'Engineering pitfalls'],
  ]);
  const hitsPersonal = searchMemory(memPayload, 'chinese reply', cache, 'zh', '2026');
  assert.deepEqual(hitsPersonal.map(h => [h.key, h.layerLabel, h.typeLabel]), [
    ['personal/reply-in-chinese.md', '个人记忆', '做法'],
  ]);

  // Frontmatter + memory documentView + buildMemoryMarkdown preserving quote/verified/extra.
  const memRaw = [
    '---',
    'name: render-check-gates-merge',
    'description: "渲染检查只在合并动到界面 mod 时必跑"',
    'metadata:',
    '  node_type: memory',
    '  custom_tag: keep-me',
    '  type: project',
    '  topic: ops',
    '  modified: 2026-11-21T18:16:37.000Z',
    '  by: "pm"',
    '  quote: "同意 / 加"',
    '  quote_checked: true',
    '  verified: "tests/render_check.py"',
    '  checked: 2026-11-21',
    '  expires: 2026-11-10',
    '---',
    '',
    '渲染检查只在合并动到界面 mod 时必跑',
    '',
  ].join('\n');
  const parsed = parseFrontmatter(memRaw);
  assert.equal(parsed.hasFrontmatter, true);
  assert.equal(parsed.fields.by, 'pm');
  assert.equal(parsed.extra.custom_tag, 'keep-me');
  const vmMem = documentView({ root: 'memory', path: 'render-check-gates-merge.md', kind: 'memory' }, memRaw, { lang: 'zh', today: '2026-11-21' });
  assert.equal(vmMem.isMemory, true);
  assert.equal(vmMem.topicLabel, '环境与发版');
  assert.deepEqual(vmMem.quotes, ['同意', '加']);
  assert.equal(vmMem.quoteStatus, 'checked');
  assert.equal(vmMem.expired, true);
  assert.equal(vmMem.chunks.length, 1, 'identical description and body must not render twice');

  const rebuilt = buildMemoryMarkdown({
    name: 'render-check-gates-merge',
    description: '更新后的摘要',
    type: 'feedback',
    topic: 'workflow',
    body: '详细做法正文',
    existingRaw: memRaw,
  });
  const reparsed = parseFrontmatter(rebuilt);
  assert.equal(reparsed.fields.description, '更新后的摘要');
  assert.equal(reparsed.fields.type, 'feedback');
  assert.equal(reparsed.fields.topic, 'workflow');
  assert.equal(reparsed.fields.quote, '同意 / 加');
  assert.equal(reparsed.fields.verified, 'tests/render_check.py');
  assert.equal(reparsed.extra.custom_tag, 'keep-me');
  assert.equal(reparsed.body, '详细做法正文');

  // Dropped plain markdown note converts cleanly into a valid memory file.
  const dropped = memoryFromDroppedFile('My New Rule.md', '# Keep lines curved\n\nDetails here.\n');
  assert.equal(dropped.slug, 'my-new-rule');
  assert.equal(parseFrontmatter(dropped.text).fields.description, 'Keep lines curved');

  // Retopic coupling rules for pitfall <-> pitfalls.
  assert.deepEqual(retopicPlan({ layer: 'project', type: 'project', topic: 'ui' }, { nextTopic: 'pitfalls' }),
    { topic: 'pitfalls', type: 'pitfall' });
  assert.deepEqual(retopicPlan({ layer: 'project', type: 'pitfall', topic: 'pitfalls' }, { nextTopic: 'ui' }),
    { topic: 'ui', type: 'project' });
  assert.deepEqual(retopicPlan({ layer: 'project', type: 'pitfall', topic: 'pitfalls' }, { nextType: 'feedback' }),
    { topic: 'workflow', type: 'feedback' });

  // Bug 5b regression: >64KB document Find MUST search beyond the initially expanded 64KB slice!
  const lines = Array.from({ length: 1600 }, (_, i) =>
    `- 2026-11-${String((i % 28) + 1).padStart(2, '0')} 第 ${i} 条：${i === 1520 ? '隐藏在九万字节之后的罕见标记词XYZ' : '常规项目记录内容占位填充'.repeat(4)}`);
  const bigDoc = lines.join('\n');
  assert.ok(bigDoc.length > 90_000, `expected >90KB doc, got ${bigDoc.length}`);
  const vmCollapsed = documentView({ root: 'docs', path: 'big.md', kind: 'md' }, bigDoc, { lang: 'zh', today: '2026-11-21', shownBytes: model.DOC_INITIAL_BYTES });
  assert.ok(vmCollapsed.remainingBytes > 20_000, 'default view starts truncated at ~64KB');
  const vmTailFind = documentView({ root: 'docs', path: 'big.md', kind: 'md' }, bigDoc, {
    lang: 'zh', today: '2026-11-21', shownBytes: model.DOC_INITIAL_BYTES, findQuery: '罕见标记词XYZ',
  });
  assert.equal(vmTailFind.matchCount, 1, 'find must hit keyword past 64KB boundary');
  assert.equal(vmTailFind.matchIndices.length, 1);
  const hitChunk = vmTailFind.chunks[vmTailFind.matchIndices[0]];
  assert.match(hitChunk, /罕见标记词XYZ/, 'chunks expand to include matched chunk past 64KB');

  // Relative link resolution inside docs/research/memory.
  assert.deepEqual(
    resolveContextLink({ root: 'research', path: 'evidence/a/README.md' }, '../at-mention/README.md', libFiles),
    { root: 'research', path: 'evidence/at-mention/README.md' },
  );
  assert.equal(resolveContextLink({ root: 'docs', path: 'decisions.md' }, 'https://example.com', libFiles), null);

  // Esc steps cleanly: answer -> confirmDelete -> blur -> edit -> retopic -> search -> history -> doc -> listOpen.
  assert.equal(escapeStep({ confirmDelete: true, typing: true, editing: true, doc: true }), 'confirmDelete');
  assert.equal(escapeStep({ typing: true, editing: true, doc: true }), 'blur');
  assert.equal(escapeStep({ editing: true, doc: true }), 'edit');
  assert.equal(escapeStep({ retopic: true, doc: true }), 'retopic');
  assert.equal(escapeStep({ search: true, history: true, doc: true }), 'search');
  assert.equal(escapeStep({ history: true, doc: true }), 'history');
  assert.equal(escapeStep({ doc: true, listOpen: true }), 'doc');

  // uniqueMemorySlug respects pm.py's 40-char limit, deduplicates collisions, and updates frontmatter `name:`.
  assert.equal(model.MEMORY_SLUG_MAX, 40);
  assert.equal(model.uniqueMemorySlug('fresh-rule', new Set(['other-rule'])), 'fresh-rule');
  assert.equal(model.uniqueMemorySlug('fresh-rule', new Set(['fresh-rule'])), 'fresh-rule-2');
  assert.equal(model.uniqueMemorySlug('fresh-rule', new Set(['fresh-rule', 'fresh-rule-2'])), 'fresh-rule-3');
  const maxBase = `${'a'.repeat(38)}-z`; // length 40; slice(0, 38) leaves trailing '-' that must strip before '-2'
  const capped = model.uniqueMemorySlug(maxBase, new Set([maxBase]));
  assert.equal(capped.length <= 40, true);
  assert.equal(capped.endsWith('--2'), false);
  assert.equal(capped, `${'a'.repeat(38)}-2`);
  const droppedOverride = model.memoryFromDroppedFile('lib-split.md', 'Body line', { slug: 'lib-split-2' });
  assert.equal(droppedOverride.slug, 'lib-split-2');
  assert.match(droppedOverride.text, /^---\nname: lib-split-2\n/);

  // chunkUtf8Text splits without breaking surrogate pairs/emojis and keeps every chunk <= maxBytes.
  assert.deepEqual(model.chunkUtf8Text(''), []);
  const multi = `${'界'.repeat(7)}🚀${'a'.repeat(5)}🎉${'中'.repeat(6)}`;
  const smallChunks = model.chunkUtf8Text(multi, 10);
  assert.equal(smallChunks.join(''), multi, 'chunks must reconstruct exact original text');
  for (const ch of smallChunks) {
    assert.ok(new TextEncoder().encode(ch).length <= 10, 'each small chunk <= maxBytes');
    assert.equal(ch, ch.toWellFormed(), 'must never split surrogate pairs');
  }
  const bigMixed = `${'测'.repeat(20000)}🚀${'x'.repeat(80000)}`; // >140KB UTF-8
  const remoteChunks = model.chunkUtf8Text(bigMixed, model.REMOTE_CHUNK_BYTES);
  assert.ok(remoteChunks.length >= 3, 'splits >140KB text into multiple <=48KB chunks');
  assert.equal(remoteChunks.join(''), bigMixed);
  for (const ch of remoteChunks) {
    assert.ok(new TextEncoder().encode(ch).length <= model.REMOTE_CHUNK_BYTES);
    assert.equal(ch, ch.toWellFormed());
  }
});

test('Library & Memory pure rules: unknown-extension text vs binary, Bug 5a failure freshness, cache invalidation, and watch noise filtering', () => {
  // 1) Unknown extensions (`verify.before-ui-only`) are treated as readable text candidates and judged on read;
  //    only known images/SVGs and > DOC_MAX_BYTES are pre-filtered.
  const unknownTextMeta = { root: 'docs', path: 'verify.before-ui-only', kind: 'before-ui-only', size: 120, modified: '2026-11-21T10:00:00Z' };
  const unknownBinMeta = { root: 'docs', path: 'data.bin', kind: 'bin', size: 64, modified: '2026-11-21T10:00:00Z' };
  const imageMeta = { root: 'docs', path: 'shots/board.png', kind: 'png', size: 500, modified: '2026-11-21T10:00:00Z', show: 'image' };
  const svgMeta = { root: 'docs', path: 'logo.svg', kind: 'svg', size: 200, modified: '2026-11-21T10:00:00Z' };
  const hugeMeta = { root: 'docs', path: 'huge.log', kind: 'log', size: model.DOC_MAX_BYTES + 1, modified: '2026-11-21T10:00:00Z' };
  assert.equal(model.contextShowMode(unknownTextMeta), 'text');
  assert.equal(model.contextReadable(unknownTextMeta), true);
  assert.equal(model.contextShowMode(unknownBinMeta), 'text', 'binary with unknown show is judged by reading content');
  assert.equal(model.contextShowMode(imageMeta), 'binary');
  assert.equal(model.contextShowMode(svgMeta), 'binary');
  assert.equal(model.contextShowMode(hugeMeta), 'large');

  // 2) Cache freshness & Bug 5a failure freshness pure rules (version, modified, size, missing).
  const d1 = { root: 'docs', path: 'spec.md', kind: 'md', size: 40, modified: '2026-11-21T10:00:00Z', version: 'v1', show: 'text' };
  const d1VerChanged = { ...d1, version: 'v2' };
  const d1ModChanged = { ...d1, modified: '2026-11-21T10:05:00Z', version: '' };
  const d1SizeChanged = { ...d1, size: 55, version: '' };
  const cache = model.keepDocCache(new Map(), 'docs/spec.md', model.makeDocCacheEntry({ text: '旧方案', size: 9, version: 'v1' }, d1));
  assert.equal(model.reconcileDocCache(cache, [d1]).has('docs/spec.md'), true);
  assert.equal(model.reconcileDocCache(cache, [d1VerChanged]).has('docs/spec.md'), false);
  assert.equal(model.reconcileDocCache(cache, [d1ModChanged]).has('docs/spec.md'), false,
    'falls back to modified/size invalidation when meta lacks version');
  const cacheNoVer = model.keepDocCache(new Map(), 'docs/spec.md', model.makeDocCacheEntry({ text: '旧方案', size: 9 }, { ...d1, version: '' }));
  assert.equal(model.reconcileDocCache(cacheNoVer, [d1ModChanged]).has('docs/spec.md'), false);
  assert.equal(model.reconcileDocCache(cacheNoVer, [d1SizeChanged]).has('docs/spec.md'), false);
  assert.equal(model.reconcileDocCache(cache, []).has('docs/spec.md'), false);
  assert.deepEqual(model.searchLibrary([d1VerChanged], '旧方案', cache, 'zh', '2026'), [], 'stale cached text must not match search');

  const failMeta = { root: 'docs', path: 'broken.md', kind: 'md', size: 100, modified: '2026-11-21T10:00:00Z', version: 'f1', show: 'text' };
  const fails = new Map([['docs/broken.md', model.makeDocFailEntry('read error', failMeta)]]);
  assert.equal(model.isFreshDocFailure(fails.get('docs/broken.md'), failMeta), true);
  assert.equal(model.isFreshDocFailure(fails.get('docs/broken.md'), { ...failMeta, version: 'f2' }), false);
  assert.equal(model.reconcileDocFailures(fails, [failMeta]).has('docs/broken.md'), true);
  assert.equal(model.reconcileDocFailures(fails, [{ ...failMeta, version: 'f2' }]).has('docs/broken.md'), false);
  assert.equal(model.reconcileDocFailures(fails, []).has('docs/broken.md'), false, 'disappeared doc drops non-missing failure');
  const missingFails = new Map([['docs/gone.md', model.makeDocFailEntry('missing', null)]]);
  assert.equal(model.reconcileDocFailures(missingFails, []).has('docs/gone.md'), true);
  assert.equal(model.reconcileDocFailures(missingFails, [{ root: 'docs', path: 'gone.md', kind: 'md', size: 12, modified: '2026-11-21T10:00:00Z' }]).has('docs/gone.md'), false);

  // 3) Local watch relevance filtering ignores noisy ledger writes and accepts docs/memory changes.
  const opts = { ledgerHome: '/here', slug: 'dudu' };
  for (const noisy of [
    '/here/projects/dudu/turn-cause.json',
    '/here/projects/dudu/taken-in.json',
    '/here/projects/dudu/takeover.json',
    '/here/projects/dudu/pm-settings.json',
    '/here/projects/dudu/schedules.json',
    '/here/projects/dudu/dudu-attachments.json',
    '/here/projects/dudu/delivered.json',
    '/here/projects/dudu/deliver.lock',
    '/here/projects/dudu/conversation.jsonl',
    '/here/projects/dudu/attachments/paste-1.png',
    '/here/projects/dudu/memory/.lock',
    '/here/projects/dudu/memory/.history/old.md',
    '/here/projects/other/docs/spec.md',
  ]) {
    assert.equal(model.isLibraryRelevantChange([noisy], opts), false, `expected library ignored: ${noisy}`);
  }
  assert.equal(model.isLibraryRelevantChange(['/here/projects/dudu/decisions.md'], opts), true);
  assert.equal(model.isLibraryRelevantChange(['/here/projects/dudu/docs/spec.md'], opts), true);
  assert.equal(model.isMemoryRelevantChange('project', ['/here/projects/dudu/memory/.lock'], opts), false);
  assert.equal(model.isMemoryRelevantChange('project', ['/here/projects/dudu/memory/m1.md'], opts), true);
  assert.equal(model.isMemoryRelevantChange('personal', ['/here/memory/.lock'], opts), false);
  assert.equal(model.isMemoryRelevantChange('personal', ['/here/memory/reply-in-chinese.md'], opts), true);
});

test('PmProject Library & Memory tabs: i18n, browsing, editing, conflicts, delete/undo, history/restore, drag-drop, Esc, Bug 5a/5b, and watches', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '').replace('export default class PmProject extends View', 'return class');

  const blank = new Proxy(function () {}, { get: (_, key) => (key === Symbol.toPrimitive ? () => 0 : blank), apply: () => blank });
  const nodes = new Map();
  const makeEl = () => {
    const rec = { id: '', texts: [], kids: [], clicks: null, tips: [], icons: [] };
    const allTexts = r => [...r.texts, ...r.kids.flatMap(allTexts)];
    const proxy = new Proxy(function () {}, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') {
            if (typeof args[0] === 'string') rec.texts.push(args[0]);
            else if (args[0]?.__rec) rec.kids.push(args[0].__rec);
            if (args[0]?.__svg) rec.icons.push(args[0].__svg);
          } else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) {
              if (typeof k === 'string') rec.texts.push(k);
              else if (k?.__rec) rec.kids.push(k.__rec);
            }
          } else if (key === 'on_click') { rec.clicks = args[0]; }
          else if (key === 'tooltip') { rec.tips.push(args[0]); }
          else if (key === 'when') { if (args[0]) args[1](proxy); }
          return proxy;
        };
      },
      apply: () => proxy,
    });
    rec.allTexts = () => allTexts(rec);
    return proxy;
  };
  const svgStub = path => { const el = makeEl(); el.__svg = path; return el; };

  let oldRemoteMode = false;
  let decisionsHidden = false;
  let forceConflictOnce = false;
  let brokenVer = 'broken-v1';
  let specVer = 1;
  let execCalls = [];
  const watchers = new Map();
  const bigDocBody = `${Array.from({ length: 1300 }, (_, i) => `Line ${i}: filler content for >64KB chunking check.`).join('\n')}\n\n## Tail\nNEEDLE_AT_END\n`;

  const docsStore = new Map([
    ['docs/spec.md', { text: '# Spec v1\nInitial plan', version: 'v1', modified: '2026-11-21T10:00:00Z' }],
    ['docs/decisions.md', { text: '# Decisions\n- 2026-11-18 Picked split tabs', version: 'dec1', modified: '2026-11-20T10:00:00Z', archive: true, entries: 16 }],
    ['docs/big.md', { text: bigDocBody, version: 'big1', modified: '2026-11-21T11:00:00Z' }],
    ['docs/broken.md', { fail: 'permission denied', version: 'broken-v1', modified: '2026-11-21T11:30:00Z' }],
    ['docs/data.bin', { binary: true, version: 'bin1', modified: '2026-11-21T11:40:00Z' }],
    ['research/library-design/README.md', {
      text: '# Library First-Principles Design\nExecutive summary here.\n',
      title: 'Library First-Principles Design',
      summary: 'Design comparison and split proposal',
      task: 'dudu-lib-res',
      task_title: '调研 Library 设计',
      published: true,
      version: 'res1',
      modified: '2026-11-21T12:00:00Z',
    }],
    ['instructions/CLAUDE.md', { text: '# Repo Instructions\nBe safe.\n', title: 'Repo instructions', version: 'ins1', modified: '2026-11-19T09:00:00Z' }],
  ]);

  const memStore = new Map([
    ['memory/lib-split.md', {
      layer: 'project', root: 'memory', path: 'lib-split.md', name: 'lib-split',
      type: 'project', topic: 'architecture', description: 'Library only holds docs & reports',
      text: '---\nname: lib-split\ndescription: "Library only holds docs & reports"\ntype: project\ntopic: architecture\nby: user\nquote: "Library 只放文档和调研报告"\nquote_checked: true\n---\n\nSplit body.',
      version: 'm1v1', modified: '2026-11-21T12:00:00Z',
    }],
    ['memory/seat-quirk.md', {
      layer: 'project', root: 'memory', path: 'seat-quirk.md', name: 'seat-quirk',
      type: 'pitfall', topic: 'pitfalls', description: 'Unwrap double dash when spawning seat',
      text: '---\nname: seat-quirk\ndescription: "Unwrap double dash when spawning seat"\ntype: pitfall\ntopic: pitfalls\n---\n\nUse unwrap_seat_argv.',
      version: 'p1v1', modified: '2026-11-21T08:00:00Z',
    }],
    ['personal/reply-zh.md', {
      layer: 'personal', root: 'personal', path: 'reply-zh.md', name: 'reply-zh',
      type: 'user', topic: '', description: 'Always reply in Chinese',
      text: '---\nname: reply-zh\ndescription: "Always reply in Chinese"\ntype: user\n---\n\nAlways reply in Chinese.',
      version: 'u1v1', modified: '2026-11-20T09:00:00Z',
    }],
  ]);

  let candidatesStore = [
    { worker: 'tw1', name: 'cand-rule', path: 'tw1/cand-rule.md', type: 'feedback', description: 'Candidate lesson', modified: '2026-11-21T13:00:00Z' },
    { worker: 'tw2', name: 'cand-drop', path: 'tw2/cand-drop.md', type: 'pitfall', description: 'Noise candidate', modified: '2026-11-21T12:30:00Z' },
  ];
  const bigRemotePayload = `${'中文🚀'.repeat(18000)}TAIL_MARKER\n`; // ~180KB UTF-8
  const historyStore = [];
  const remoteTmpFiles = new Map();
  let remoteTmpSeq = 0;
  let shellCalls = [];
  const droppedTextFiles = new Map([
    ['/Users/me/notes/remote-doc.md', '# Dropped Remote\nHello remote'],
    ['/Users/me/notes/remote-big.md', bigRemotePayload],
    ['/Users/me/notes/mem-note.txt', 'Keep diffs tiny and focused.\nExtra line for memory body.'],
    ['/Users/me/notes/lib-split.md', '# Colliding Rule\nMust not overwrite lib-split.md.'],
    ['/Users/me/notes/race-note.md', '# Race Rule\nStale memoryData must bump to race-note-2.md.'],
    ['/Users/me/notes/a/batch-dup.md', 'First batch note'],
    ['/Users/me/notes/b/batch-dup.txt', 'Second batch note'],
  ]);

  const extractPmArgs = (cmd, args = []) => {
    if (cmd === 'sh' && args[0] === '-c' && args[2] === 'sh' && args[1]?.includes('pm.py')) return args.slice(3);
    const pyIdx = args.findIndex(a => String(a).endsWith('/pm.py'));
    return pyIdx >= 0 ? args.slice(pyIdx + 1) : null;
  };
  const flagVal = (pmArgs, prefix) => {
    const hit = pmArgs.find(a => a.startsWith(prefix));
    return hit ? hit.slice(prefix.length) : '';
  };

  const stubs = {
    View: class {}, ...model,
    div: makeEl, h_flex: makeEl, v_flex: makeEl, svg: svgStub,
    TextView: { markdown: (_id, text) => makeEl().child(String(text || '')), html: (_id, html) => makeEl().child(String(html || '')) },
    Input: { new: () => makeEl() }, Textarea: { new: () => makeEl() },
    InputState: { new: () => makeEl() }, TextareaState: { new: () => makeEl() },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) },
    Scrollbar: { vertical: id => makeEl().id(`scrollbar:${id}`) },
    execPython: async (_exec, argv, opts) => stubs.exec('python3', argv, opts),
    appHome: () => '/app', home: () => '/Users/me',
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    appWindow: () => ({ platform: 'macos' }),
    terminals: () => [], agents: () => [], panes: () => [], spaces: () => [],
    theme: () => ({
      canvas: '#111111', surface: '#181818', raised: '#222222', chrome: '#161616', hover: '#2a2a2a',
      border: '#333333', input: '#3a3a3a', foreground: '#eeeeee', background: '#111111',
      muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', accent_foreground: '#ffffff',
      blocked: '#ff5f56', ansi2: '#27c93f', ansi3: '#e5a93c', ansi4: '#6699ff',
      solid: '#eeeeee', solid_foreground: '#111111',
    }),
    shared: () => ({ pm: 'pm-dudu' }),
    layout: () => ({ id: 'pm-stage', active: 'pm-project' }),
    watchFolder: path => new Promise(resolve => { watchers.set(path, resolve); }),
    readTextFile: async path => (droppedTextFiles.has(path) ? droppedTextFiles.get(path) : null),
    writeTextFile: async () => {},
    exec: async (command, args = [], opts2) => {
      if (command === 'sh' && args[0] === '-c' && args[1]?.includes('mktemp')) {
        const tmp = `/tmp/pm-edit.${++remoteTmpSeq}`;
        remoteTmpFiles.set(tmp, '');
        shellCalls.push({ command, kind: 'mktemp', tmp, on: opts2?.on || '', args });
        return { code: 0, stdout: `${tmp}\n`, stderr: '' };
      }
      if (command === 'sh' && args[0] === '-c' && args[1]?.startsWith('printf ') && args[2] === 'sh') {
        const tmp = args[3];
        const chunk = args[4];
        remoteTmpFiles.set(tmp, (remoteTmpFiles.get(tmp) || '') + chunk);
        shellCalls.push({ command, kind: 'append', tmp, bytes: new TextEncoder().encode(chunk).length, on: opts2?.on || '' });
        return { code: 0, stdout: '', stderr: '' };
      }
      if (command === 'rm') {
        const sep = args.indexOf('--');
        const tmp = sep >= 0 ? args[sep + 1] : args[args.length - 1];
        remoteTmpFiles.delete(tmp);
        shellCalls.push({ command, kind: 'rm', tmp, on: opts2?.on || '' });
        return { code: 0, stdout: '', stderr: '' };
      }
      const pmArgs = extractPmArgs(command, args);
      if (!pmArgs) return { code: 0, stdout: '', stderr: '' };
      execCalls.push({ command, pmArgs, on: opts2?.on || '' });

      if (pmArgs[0] === 'adopt') {
        const drop = pmArgs.includes('--drop');
        const target = pmArgs[pmArgs.indexOf('--') + 1];
        if (!drop) {
          const cand = candidatesStore.find(c => `${c.worker}/${c.name}` === target);
          if (cand) {
            memStore.set(`memory/${cand.name}.md`, {
              layer: 'project', root: 'memory', path: `${cand.name}.md`, name: cand.name,
              type: cand.type, topic: cand.type === 'pitfall' ? 'pitfalls' : 'workflow',
              description: cand.description,
              text: `---\nname: ${cand.name}\ndescription: "${cand.description}"\ntype: ${cand.type}\ntopic: ${cand.type === 'pitfall' ? 'pitfalls' : 'workflow'}\n---\n`,
              version: 'adopted-v1', modified: '2026-11-21T13:10:00Z',
            });
          }
        }
        candidatesStore = candidatesStore.filter(c => `${c.worker}/${c.name}` !== target);
        return { code: 0, stdout: '{}', stderr: '' };
      }

      if (pmArgs[0] !== 'project') return { code: 0, stdout: '{}', stderr: '' };
      const sub = pmArgs[1];
      if (oldRemoteMode && ['library', 'memory', 'file', 'save', 'delete', 'restore', 'history', 'add', 'retopic'].includes(sub)) {
        return { code: 2, stdout: '', stderr: `pm.py: error: argument project_cmd: invalid choice: '${sub}'` };
      }
      if (sub === 'library') {
        const files = [];
        for (const [k, v] of docsStore.entries()) {
          const [root, ...rest] = k.split('/');
          const rel = rest.join('/');
          files.push({
            root, path: rel, kind: rel.endsWith('.bin') ? 'bin' : 'md',
            size: v.text ? v.text.length : 16, modified: v.modified || '2026-11-21T10:00:00Z',
            version: k === 'docs/broken.md' ? brokenVer : v.version,
            ...(k === 'docs/decisions.md' ? { archive: true, hidden: decisionsHidden, entries: v.entries, writable: false } : {}),
            ...(v.title ? { title: v.title } : {}),
            ...(v.summary ? { summary: v.summary } : {}),
            ...(v.task ? { task: v.task, task_title: v.task_title, published: v.published } : {}),
            writable: root === 'docs' && k !== 'docs/decisions.md',
            show: k === 'docs/data.bin' ? undefined : 'text',
          });
        }
        return {
          code: 0,
          stdout: JSON.stringify({ project: 'dudu', roots: [{ id: 'docs', writable: true }, { id: 'research', writable: false }, { id: 'instructions', writable: false }], files }),
          stderr: '',
        };
      }
      if (sub === 'memory') {
        const files = [...memStore.values()].map(m => ({
          layer: m.layer, root: m.root, path: m.path, name: m.name, type: m.type, topic: m.topic,
          description: m.description, modified: m.modified, size: m.text.length, version: m.version, writable: true,
        }));
        return {
          code: 0,
          stdout: JSON.stringify({
            project: 'dudu',
            topics: model.MEMORY_TOPICS.map(id => ({ id, folded: id === 'pitfalls' })),
            files,
            candidates: candidatesStore,
            history: { project: historyStore.filter(h => h.root === 'memory').length, personal: historyStore.filter(h => h.root === 'personal').length },
          }),
          stderr: '',
        };
      }
      if (sub === 'file') {
        const root = pmArgs[pmArgs.indexOf('--root') + 1];
        const path = pmArgs[pmArgs.indexOf('--') + 2];
        const key = `${root}/${path}`;
        const entry = docsStore.get(key) || memStore.get(key);
        if (!entry) return { code: 1, stdout: '', stderr: `not found: ${key}\n` };
        if (entry.binary) return { code: 1, stdout: '', stderr: 'error: not a text file\n' };
        if (entry.fail) return { code: 1, stdout: '', stderr: `${entry.fail}\n` };
        return { code: 0, stdout: JSON.stringify({ root, path, text: entry.text, size: entry.text.length, version: entry.version }), stderr: '' };
      }
      if (sub === 'save') {
        const root = pmArgs[pmArgs.indexOf('--root') + 1];
        const sep = pmArgs.indexOf('--');
        const path = pmArgs[sep + 2];
        const ifVersion = flagVal(pmArgs, '--if-version=');
        const fromPath = flagVal(pmArgs, '--from=');
        const text = fromPath
          ? (remoteTmpFiles.has(fromPath) ? remoteTmpFiles.get(fromPath) : bigDocBody)
          : flagVal(pmArgs, '--text=');
        const key = `${root}/${path}`;
        const existing = docsStore.get(key) || memStore.get(key);
        if (ifVersion === 'new' && existing) {
          return { code: 4, stdout: JSON.stringify({ error: 'conflict', current_version: existing.version || 'exists' }), stderr: '' };
        }
        if (forceConflictOnce && ifVersion && ifVersion !== 'new') {
          forceConflictOnce = false;
          return { code: 4, stdout: JSON.stringify({ error: 'version conflict', current_version: 'v-remote-latest', expected_version: ifVersion }), stderr: '' };
        }
        const newVer = `sv${++specVer}`;
        if (root === 'docs') {
          const prev = docsStore.get(key);
          if (prev) historyStore.unshift({ root, path, version: prev.version, why: 'replaced', text: prev.text });
          docsStore.set(key, { text, version: newVer, modified: `2026-11-21T14:0${specVer}:00Z` });
        } else {
          const prev = memStore.get(key);
          if (prev) historyStore.unshift({ root, path, name: prev.name, description: prev.description, version: prev.version, why: 'replaced', text: prev.text, layer: prev.layer, type: prev.type, topic: prev.topic });
          const parsed = model.parseFrontmatter(text);
          const f = parsed.fields;
          const layer = root === 'personal' ? 'personal' : 'project';
          memStore.set(key, {
            layer, root, path, name: f.name || path.replace(/\.md$/, ''), type: f.type || 'project',
            topic: f.topic || 'architecture', description: f.description || '', text, version: newVer, modified: '2026-11-21T14:00:00Z',
          });
        }
        return { code: 0, stdout: JSON.stringify({ root, path, version: newVer }), stderr: '' };
      }
      if (sub === 'delete') {
        const root = pmArgs[pmArgs.indexOf('--root') + 1];
        const path = pmArgs[pmArgs.indexOf('--') + 2];
        const key = `${root}/${path}`;
        const prev = docsStore.get(key) || memStore.get(key);
        if (!prev) return { code: 1, stdout: '', stderr: 'not found' };
        historyStore.unshift({ root, path, name: prev.name || path, description: prev.description || '', version: prev.version, why: 'deleted', ...prev });
        docsStore.delete(key);
        memStore.delete(key);
        return { code: 0, stdout: JSON.stringify({ deleted: path }), stderr: '' };
      }
      if (sub === 'history') {
        const root = pmArgs[pmArgs.indexOf('--root') + 1];
        const sep = pmArgs.indexOf('--');
        const path = pmArgs[sep + 2] || '';
        const items = historyStore.filter(h => h.root === root && (!path || h.path === path));
        return { code: 0, stdout: JSON.stringify({ items }), stderr: '' };
      }
      if (sub === 'restore') {
        const root = pmArgs[pmArgs.indexOf('--root') + 1];
        const path = pmArgs[pmArgs.indexOf('--') + 2];
        const ver = flagVal(pmArgs, '--version=');
        const snap = historyStore.find(h => h.root === root && h.path === path && (!ver || h.version === ver));
        if (!snap) return { code: 1, stdout: '', stderr: 'no snapshot' };
        const key = `${root}/${path}`;
        if (root === 'docs') docsStore.set(key, { text: snap.text, version: `res-${snap.version}`, modified: '2026-11-21T15:00:00Z' });
        else memStore.set(key, { layer: snap.layer || (root === 'personal' ? 'personal' : 'project'), root, path, name: snap.name, type: snap.type || 'project', topic: snap.topic || 'architecture', description: snap.description || '', text: snap.text, version: `res-${snap.version}`, modified: '2026-11-21T15:00:00Z' });
        return { code: 0, stdout: JSON.stringify({ restored: path }), stderr: '' };
      }
      if (sub === 'retopic') {
        const name = pmArgs[pmArgs.indexOf('--') + 2];
        const personal = pmArgs.includes('--personal');
        const topic = flagVal(pmArgs, '--topic=');
        const type = flagVal(pmArgs, '--type=');
        const key = `${personal ? 'personal' : 'memory'}/${name}.md`;
        const entry = memStore.get(key);
        if (!entry) return { code: 1, stdout: '', stderr: 'missing memory' };
        entry.type = type || entry.type;
        if (!personal) entry.topic = entry.type === 'pitfall' ? 'pitfalls' : (topic || entry.topic);
        entry.version = `rt${++specVer}`;
        return { code: 0, stdout: JSON.stringify({ name, topic: entry.topic, type: entry.type }), stderr: '' };
      }
      if (sub === 'add') {
        const src = pmArgs[pmArgs.indexOf('--') + 2];
        const base = src.split('/').pop();
        docsStore.set(`docs/${base}`, { text: '# Local Added\nAdded from drop', version: `add${++specVer}`, modified: '2026-11-21T15:05:00Z' });
        return { code: 0, stdout: JSON.stringify({ path: base }), stderr: '' };
      }
      return { code: 0, stdout: JSON.stringify({ events: [], from: 0, offset: 0, earlier: false }), stderr: '' };
    },
  };

  const scope = new Proxy(stubs, {
    has: (target, name) => name in target || !(name in globalThis),
    get: (target, name) => (name in target ? target[name] : name === Symbol.unscopables ? undefined : blank),
  });
  const Mod = new Function('scope', `with (scope) { ${source} }`)(scope);
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/work/dudu', conversation: '/here/projects/dudu/conversation.jsonl' };
  let stopped = 0;
  const cx = { spawn: f => f(cx), notify() {}, timer: { after() {}, every() {} }, stop_propagation() { stopped++; } };
  const makeInput = (init = '') => {
    let v = init;
    return { value: () => v, set_value: s => { v = String(s ?? ''); }, set_selected_range() {}, focus() {} };
  };
  const docScrolled = [];
  const makeView = extra => {
    const v = Object.assign(Object.create(Mod.prototype), {
      machine: '', pmName: 'pm-dudu', stateFor: '', state: { pms: [pm], tasks: [{ id: 'dudu-lib-res', pm: 'pm-dudu', title: '调研 Library 设计', status: 'review' }], lang: 'zh' },
      ledgerHome: '/here', watching: {}, remoteHome: '', remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '',
      logPath: '/here/projects/dudu/conversation.jsonl', logSlug: 'dudu', logState: null, events: [], pending: [], pastes: [], items: [],
      thread: '', threadTask: null, detail: false, threadTab: 'log', outgoing: new Map(), files: [], threadFiles: [],
      sideTab: 'threads', librarySlug: '', libraryRoots: [], libraryFiles: [], libraryRead: false, libraryProbed: false, libraryStale: false,
      libraryLoading: false, libraryAgain: false, libraryError: '', libraryClosed: new Set(), libraryQuery: '', libraryDropBusy: '', libraryDropError: '',
      memorySlug: '', memoryData: null, memoryRead: false, memoryStale: false, memoryLoading: false, memoryAgain: false, memoryError: '',
      memoryFoldOverrides: new Map(), memoryProjectOpen: true, memoryPersonalOpen: false, memoryCandidatesOpen: false, memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
      activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '', docShownBytes: model.DOC_INITIAL_BYTES,
      docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
      editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
      confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
      input: makeInput(), threadInput: makeInput(), libraryInput: makeInput(), memoryInput: makeInput(), docFindInput: makeInput(),
      docNameInput: makeInput(), memDescInput: makeInput(), docEditorInput: makeInput(),
      scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
      libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item: i => docScrolled.push(i) }, historyScroll: { scroll_to_item() {} },
      heights: new Map(), unfolded: new Map(), atWork: new Set(),
      wide: true, listShown: true, measured: true, viewWidth: 1200, high: 800, tall: 700, count: 0, settle: 0, away: false, rise: 0,
      typing: '',
      ...extra,
    });
    v.keyFocus = { focus() { v.typing = ''; } };
    return v;
  };

  // (a) Library tab i18n (zh & en both say "Library"), research H1 title + source thread jump, archive decisions.md & read-only enforcement.
  const view = makeView();
  view.selectSideTab('library', cx);
  await new Promise(r => setTimeout(r, 20));
  assert.equal(view.libraryRead, true);
  assert.equal(view.docCache.has('docs/spec.md'), true, 'prefetches small writable docs for search');
  assert.equal(view.docCache.has('docs/decisions.md'), false, 'does not eagerly prefetch archive');

  nodes.clear();
  view.render(cx);
  assert.deepEqual(nodes.get('panel-tab-library')?.texts, ['Library'], 'Chinese UI also labels the tab Library');
  assert.deepEqual(nodes.get('panel-tab-memory')?.texts, ['Memory']);
  assert.match(nodes.get('lib-doc-research/library-design/README.md')?.allTexts().join(' ') || '', /Library First-Principles Design/);
  assert.equal((nodes.get('lib-doc-research/library-design/README.md')?.allTexts().join(' ') || '').includes('README.md'), false,
    'research row shows report title instead of README.md');
  assert.equal(nodes.has('lib-thread-research/library-design/README.md'), true, 'research row renders source-thread icon');
  assert.equal(nodes.has('lib-doc-docs/decisions.md'), true, 'non-hidden decisions.md appears as archive');

  // Switch to English UI and verify i18n switch.
  view.state.lang = 'en';
  nodes.clear();
  view.render(cx);
  assert.deepEqual(nodes.get('panel-tab-library')?.texts, ['Library']);
  assert.deepEqual(nodes.get('panel-tab-memory')?.texts, ['Memory']);
  assert.match(nodes.get('library-panel')?.allTexts().join(' ') || '', /Documents.*Research reports.*Instructions/);

  // Hide decisions.md once migrated on backend -> removed from main list.
  decisionsHidden = true;
  view.readLibrary(cx);
  await new Promise(r => setTimeout(r, 20));
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('lib-doc-docs/decisions.md'), false, 'hidden decisions.md is omitted from main Library list');
  decisionsHidden = false;
  view.readLibrary(cx);
  await new Promise(r => setTimeout(r, 20));

  // Source-thread icon opens thread detail; closing returns cleanly.
  nodes.clear();
  view.render(cx);
  nodes.get('lib-thread-research/library-design/README.md')?.clicks(null, cx);
  assert.equal(view.thread, 'dudu-lib-res');
  assert.equal(view.detail, true);
  view.detail = false;

  // Opening read-only research, instruction, or archive decisions.md never shows edit/history/delete icons.
  for (const roTarget of [
    { tab: 'library', root: 'research', path: 'library-design/README.md' },
    { tab: 'library', root: 'instructions', path: 'CLAUDE.md' },
    { tab: 'library', root: 'docs', path: 'decisions.md' },
  ]) {
    view.openDoc(roTarget, cx);
    await new Promise(r => setTimeout(r, 15));
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.has('doc-edit'), false, `${roTarget.root}/${roTarget.path} must not offer edit`);
    assert.equal(nodes.has('doc-history'), false, `${roTarget.root}/${roTarget.path} must not offer history`);
    assert.equal(nodes.has('doc-delete'), false, `${roTarget.root}/${roTarget.path} must not offer delete`);
    assert.match(nodes.get('doc-detail-body')?.allTexts().join(' ') || '', /Read-only/);
  }
  view.closeActiveDoc(cx);

  // (b) Bug 5b: >64KB document Find expands matching chunks past 64KB, scrolls to match, and Show More advances past expanded chunk.
  view.openDoc({ tab: 'library', root: 'docs', path: 'big.md' }, cx);
  await new Promise(r => setTimeout(r, 20));
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('doc-show-more'), true, '>64KB doc initially slices at 64KB');
  docScrolled.length = 0;
  view.docFindOpen = true;
  view.docFindQuery = 'NEEDLE_AT_END';
  view.docFindJump = true;
  nodes.clear();
  view.render(cx);
  assert.match(nodes.get('doc-detail-body')?.allTexts().join(' ') || '', /NEEDLE_AT_END/, 'Find expands >64KB slice to reveal end match');
  assert.equal(docScrolled.length > 0, true, 'scrolls to matched chunk in >64KB doc');

  // Search earlier match in big.md where remainingBytes > 0 and click doc-show-more.
  view.docFindQuery = 'Line 100';
  view.docShownBytes = 10000;
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('doc-show-more'), true);
  const shownBefore = view.docShownBytes;
  nodes.get('doc-show-more')?.clicks(null, cx);
  assert.equal(view.docShownBytes >= shownBefore + model.DOC_INITIAL_BYTES, true);
  view.docFindOpen = false;
  view.docFindQuery = '';
  view.closeActiveDoc(cx);

  // (c) Edit/save, exit-4 conflict reload & overwrite, delete confirm + undo banner, history + restore.
  view.openDoc({ tab: 'library', root: 'docs', path: 'spec.md' }, cx);
  await new Promise(r => setTimeout(r, 15));
  view.startEditDoc(cx);
  assert.equal(view.editingDoc?.path, 'spec.md');
  view.docEditorInput.set_value('# Spec edited');

  // Dirty focused editor Esc: blurs first, second Esc cancels edit.
  view.typing = 'docEditor';
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(view.typing, '', 'first Esc blurs dirty focused editor');
  assert.ok(view.editingDoc, 'stays in edit mode after first Esc blur');
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(view.editingDoc, null, 'second Esc exits edit mode');

  // Re-enter edit and hit exit-4 conflict -> reload -> overwrite save.
  view.startEditDoc(cx);
  view.docEditorInput.set_value('# Spec conflict edit');
  forceConflictOnce = true;
  await view.saveEditingDoc(cx);
  assert.ok(view.editingDoc?.conflict, 'exit 4 sets conflict banner');
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('doc-conflict-bar'), true);
  assert.equal(nodes.has('doc-conflict-reload'), true);
  assert.equal(nodes.has('doc-conflict-overwrite'), true);
  await view.saveEditingDoc(cx, { overwrite: true });
  await new Promise(r => setTimeout(r, 15));
  assert.equal(view.editingDoc, null, 'overwrite clears editing state and saves');
  assert.equal(view.docCache.get('docs/spec.md')?.text, '# Spec conflict edit');

  // Reload from conflict path also works cleanly.
  view.startEditDoc(cx);
  docsStore.set('docs/spec.md', { text: '# Disk newer', version: 'v-disk', modified: '2026-11-21T14:30:00Z' });
  await view.reloadConflictDoc(cx);
  assert.equal(view.docEditorInput.value(), '# Disk newer');
  assert.equal(view.editingDoc?.version, 'v-disk');
  view.cancelEditDoc(cx);

  // Delete requires confirmation bar -> confirm -> shows deletedBanner -> undo restores.
  nodes.clear();
  view.render(cx);
  nodes.get('doc-delete')?.clicks(null, cx);
  assert.equal(view.confirmDeleteKey, 'docs/spec.md');
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('doc-delete-bar'), true);
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(view.confirmDeleteKey, '', 'Esc cancels delete confirmation first');

  nodes.get('doc-delete')?.clicks(null, cx);
  await view.deleteActiveDoc(cx);
  assert.equal(docsStore.has('docs/spec.md'), false);
  assert.equal(view.activeDoc, null);
  assert.equal(view.deletedBanner?.path, 'spec.md');
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('deleted-banner'), true);
  await view.undoDeletedBanner(cx);
  assert.equal(docsStore.has('docs/spec.md'), true, 'undo restores deleted doc from history');

  // Open History view -> Esc closes -> open again & restore version.
  await view.openHistory('library', 'docs', '', 'all', cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('history-view'), true);
  assert.equal(nodes.has('history-item-0'), true);
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(view.historyView, null);
  await view.openHistory('library', 'docs', '', 'all', cx);
  await view.restoreHistoryItem(view.historyView.items[0], cx);
  assert.equal(view.historyView, null, 'restoring closes history view and refreshes');

  // Drag-and-drop onto Library (local uses `project add`; rejects folders).
  await view.dropLibraryFiles(['/Users/me/notes/local-dropped.md'], cx);
  assert.equal(docsStore.has('docs/local-dropped.md'), true);

  // (d) Memory tab: folded dimmed pitfalls, folded personal, folded candidates (adopt/discard), retopic, personal no fake topic, search folded.
  view.state.lang = 'zh';
  view.selectSideTab('memory', cx);
  await new Promise(r => setTimeout(r, 20));
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('mem-doc-memory/lib-split.md'), true, 'project architecture topic expanded by default');
  assert.equal(nodes.has('mem-doc-memory/seat-quirk.md'), false, 'engineering pitfalls folded by default');
  assert.equal(nodes.has('mem-doc-personal/reply-zh.md'), false, 'personal memory folded by default');
  assert.equal(nodes.has('mem-candidates'), true, 'candidates folder rendered');
  assert.equal(nodes.has('mem-cand-tw1/cand-rule.md'), false, 'candidates folded by default');

  // Unfold candidates -> adopt one, discard one -> uses pm.repo!
  nodes.get('mem-candidates')?.clicks(null, cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('cand-adopt-tw1/cand-rule.md'), true);
  await view.handleCandidate(candidatesStore[0], false, cx);
  assert.equal(memStore.has('memory/cand-rule.md'), true);
  assert.equal(execCalls.some(c => c.pmArgs[0] === 'adopt' && c.pmArgs[2] === '/work/dudu'), true, 'adopt passes pm.repo');
  await view.handleCandidate(candidatesStore[0], true, cx);
  assert.equal(candidatesStore.length, 0);

  // Search Memory finds folded pitfall & personal memory!
  view.memoryQuery = 'spawning seat';
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('mem-doc-memory/seat-quirk.md'), true, 'Memory search matches folded pitfalls');
  view.memoryQuery = 'Chinese';
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('mem-doc-personal/reply-zh.md'), true, 'Memory search matches folded personal memory');
  view.memoryQuery = '';

  // Personal memory detail has NO fake project topic pill, but CAN open retype picker (`doc-retopic-toggle`).
  view.openDoc({ tab: 'memory', root: 'personal', path: 'reply-zh.md' }, cx);
  await new Promise(r => setTimeout(r, 15));
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('doc-retopic-toggle'), true, 'personal memory exposes retype toggle');
  assert.equal((nodes.get('doc-detail-body')?.allTexts().join(' ') || '').includes('产品与架构'), false,
    'personal memory must never show a fake project topic label');
  nodes.get('doc-retopic-toggle')?.clicks(null, cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('doc-retopic-picker'), true);
  await view.applyRetopic('', 'feedback', cx);
  assert.equal(memStore.get('personal/reply-zh.md')?.type, 'feedback');
  view.closeActiveDoc(cx);

  // Project memory retopic coupling (`project` -> `pitfall` moves to `pitfalls`; `pitfalls` -> `ui` resets type from `pitfall`).
  view.openDoc({ tab: 'memory', root: 'memory', path: 'lib-split.md' }, cx);
  await new Promise(r => setTimeout(r, 15));
  await view.applyRetopic('', 'pitfall', cx);
  assert.equal(memStore.get('memory/lib-split.md')?.type, 'pitfall');
  assert.equal(memStore.get('memory/lib-split.md')?.topic, 'pitfalls');
  await view.applyRetopic('ui', '', cx);
  assert.equal(memStore.get('memory/lib-split.md')?.topic, 'ui');
  assert.notEqual(memStore.get('memory/lib-split.md')?.type, 'pitfall');
  view.closeActiveDoc(cx);

  // Drop valid & invalid files into Memory, plus collision deduplication (`lib-split` -> `lib-split-2`),
  // stale-list race recovery (`race-note` on disk unseen in `memoryData` -> `race-note-2`), and multi-file batch collisions.
  await view.dropMemoryFiles(['/Users/me/notes/mem-note.txt'], cx);
  assert.equal(memStore.has('memory/mem-note.md'), true);
  await view.dropMemoryFiles(['/Users/me/notes/shot.png'], cx);
  assert.equal(view.memoryNoticeError, model.word('zh', 'memoryDropMdOnly'));

  const originalLibSplitText = memStore.get('memory/lib-split.md')?.text;
  view.readMemory(cx);
  await new Promise(r => setTimeout(r, 15));
  await view.dropMemoryFiles(['/Users/me/notes/lib-split.md'], cx);
  assert.equal(memStore.get('memory/lib-split.md')?.text, originalLibSplitText, 'must NEVER overwrite existing lib-split.md');
  assert.equal(memStore.has('memory/lib-split-2.md'), true, 'deduplicates dropped file to lib-split-2.md');
  assert.match(memStore.get('memory/lib-split-2.md')?.text || '', /^---\nname: lib-split-2\n/, 'updates frontmatter name to deduplicated slug');

  // Disk already has `race-note.md` that `view.memoryData` has not seen yet -> `--if-version=new` triggers exit 4 and retries `-2`.
  memStore.set('memory/race-note.md', {
    layer: 'project', root: 'memory', path: 'race-note.md', name: 'race-note',
    type: 'project', topic: 'architecture', description: 'Original on disk',
    text: '---\nname: race-note\ndescription: "Original on disk"\n---\n', version: 'disk-v1', modified: '2026-11-21T13:50:00Z',
  });
  await view.dropMemoryFiles(['/Users/me/notes/race-note.md'], cx);
  assert.equal(memStore.get('memory/race-note.md')?.description, 'Original on disk', 'must not overwrite unseen on-disk memory');
  assert.equal(memStore.has('memory/race-note-2.md'), true, 'exit 4 triggers retry with race-note-2.md');

  await view.dropMemoryFiles(['/Users/me/notes/a/batch-dup.md', '/Users/me/notes/b/batch-dup.txt'], cx);
  assert.equal(memStore.has('memory/batch-dup.md'), true);
  assert.equal(memStore.has('memory/batch-dup-2.md'), true);

  // (e) Esc ignored when side panel is collapsed (`!listResting()`), then steps cleanly once shown.
  view.openDoc({ tab: 'memory', root: 'memory', path: 'lib-split.md' }, cx);
  await new Promise(r => setTimeout(r, 15));
  view.docFindOpen = true;
  view.docFindQuery = 'Split';
  view.listShown = false; // collapsed on wide viewport
  stopped = 0;
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(stopped, 0, 'Esc must not intercept when side panel is hidden');
  assert.equal(view.docFindQuery, 'Split');
  view.wide = false; view.listShown = null; // collapsed on narrow viewport
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(stopped, 0);
  view.listShown = true;
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(stopped, 1);
  assert.equal(view.docFindQuery, '');

  // (f) Bug 5a on remote machine: errored doc does NOT re-fetch or flash `docLoading` across repeated readLibrary polls
  //     until its metadata (`version`) changes or Retry (`doc-retry`) is clicked.
  const remote = makeView({ machine: 'dev', pmName: 'dev/pm-dudu', stateFor: 'dev', sideTab: 'library' });
  remote.readLibrary(cx);
  await new Promise(r => setTimeout(r, 15));
  remote.openDoc({ tab: 'library', root: 'docs', path: 'broken.md' }, cx);
  await new Promise(r => setTimeout(r, 15));
  assert.ok(remote.docError, 'initial open surfaces error');
  assert.equal(remote.docLoading, '');
  execCalls = [];
  let loadingFlashSeen = false;
  const origNotify = cx.notify;
  cx.notify = () => { if (remote.docLoading === 'docs/broken.md') loadingFlashSeen = true; origNotify(); };
  remote.readLibrary(cx);
  await new Promise(r => setTimeout(r, 15));
  remote.readLibrary(cx);
  await new Promise(r => setTimeout(r, 15));
  cx.notify = origNotify;
  assert.equal(loadingFlashSeen, false, 'Bug 5a: repeated polls must not flash docLoading for unchanged errored doc');
  assert.equal(execCalls.filter(c => c.pmArgs[1] === 'file' && c.pmArgs.includes('broken.md')).length, 0,
    'Bug 5a: repeated polls must not re-fetch unchanged errored doc');

  // Once remote doc metadata changes & recovers, next poll re-fetches!
  brokenVer = 'broken-v2';
  docsStore.set('docs/broken.md', { text: '# Recovered!', version: 'broken-v2', modified: '2026-11-21T16:00:00Z' });
  remote.readLibrary(cx);
  await new Promise(r => setTimeout(r, 20));
  assert.equal(remote.docCache.get('docs/broken.md')?.text, '# Recovered!');

  // Remote text-file drop uses `project save` instead of `project add`; >60KB uses chunked remote temp file (--from), never --text=.
  await remote.dropLibraryFiles(['/Users/me/notes/remote-doc.md'], cx);
  assert.equal(docsStore.get('docs/remote-doc.md')?.text, '# Dropped Remote\nHello remote');

  shellCalls = [];
  execCalls = [];
  await remote.dropLibraryFiles(['/Users/me/notes/remote-big.md'], cx);
  assert.equal(docsStore.get('docs/remote-big.md')?.text, bigRemotePayload, 'remote >60KB save must write exact full payload');
  const bigSaveCalls = execCalls.filter(c => c.pmArgs[0] === 'project' && c.pmArgs[1] === 'save');
  assert.equal(bigSaveCalls.length, 1);
  assert.equal(bigSaveCalls[0].on, 'dev');
  assert.equal(bigSaveCalls[0].pmArgs.some(a => a.startsWith('--text=')), false, 'remote >60KB must NEVER pass --text= single arg');
  assert.equal(bigSaveCalls[0].pmArgs.some(a => a.startsWith('--from=/tmp/pm-edit.')), true, 'remote >60KB passes --from=<tmp>');
  const appends = shellCalls.filter(s => s.kind === 'append');
  assert.ok(appends.length >= 3, 'remote >60KB chunks payload across multiple printf calls');
  for (const ap of appends) {
    assert.equal(ap.on, 'dev');
    assert.ok(ap.bytes <= model.REMOTE_CHUNK_BYTES, `remote chunk must stay <= ${model.REMOTE_CHUNK_BYTES} bytes`);
  }
  assert.equal(shellCalls.some(s => s.kind === 'rm' && s.on === 'dev'), true, 'cleans up remote temp file');
  assert.equal(remoteTmpFiles.size, 0, 'all remote temp files deleted after save');

  // Verify cleanup also runs if remote `project save --from=<tmp>` exits 4 (conflict).
  forceConflictOnce = true;
  shellCalls = [];
  const conflictRes = await remote.saveProjectText('dudu', 'docs', 'remote-big.md', bigRemotePayload, { ifVersion: 'stale-v' });
  assert.equal(conflictRes.code, 4);
  assert.equal(shellCalls.some(s => s.kind === 'rm' && s.on === 'dev'), true, 'cleans up remote temp file on exit 4 conflict');
  assert.equal(remoteTmpFiles.size, 0);

  // Old remote pm.py gracefully hides Library & Memory tabs without error banner.
  oldRemoteMode = true;
  const oldRemote = makeView({ machine: 'old', pmName: 'old/pm-dudu', stateFor: 'old', sideTab: 'library' });
  oldRemote.readLibrary(cx);
  await new Promise(r => setTimeout(r, 15));
  assert.equal(oldRemote.remoteNoLibrary, 'old');
  assert.equal(oldRemote.remoteNoMemory, 'old');
  assert.equal(oldRemote.sideTab, 'threads');
  assert.equal(oldRemote.libraryError, '');
  oldRemoteMode = false;

  // (g) Local `arm()` watch discipline: ignores remote views, ignores noisy ledger writes,
  //     marks `libraryStale`/`memoryStale` without spawning subprocesses while on `threads`.
  watchers.clear();
  remote.arm(cx);
  execCalls = [];
  watchers.get('/here/projects')?.(['/here/projects/dudu/decisions.md']);
  watchers.get('/here/memory')?.(['/here/memory/reply-zh.md']);
  await new Promise(r => setTimeout(r, 15));
  assert.equal(execCalls.length, 0, 'local folder watch must not fire remote calls');

  watchers.clear();
  const local = makeView({ sideTab: 'library' });
  local.arm(cx);
  local.readLibrary(cx);
  await new Promise(r => setTimeout(r, 15));
  local.selectSideTab('threads', cx);
  execCalls = [];
  watchers.get('/here/projects')?.([
    '/here/projects/dudu/turn-cause.json',
    '/here/projects/dudu/taken-in.json',
    '/here/projects/dudu/conversation.jsonl',
  ]);
  await new Promise(r => setTimeout(r, 15));
  assert.equal(execCalls.filter(c => c.pmArgs[1] === 'library' || c.pmArgs[1] === 'memory' || c.pmArgs[1] === 'file').length, 0,
    'noisy ledger files must not trigger Library/Memory subprocesses');
  assert.equal(local.libraryStale, false);

  watchers.get('/here/projects')?.(['/here/projects/dudu/docs/spec.md']);
  await new Promise(r => setTimeout(r, 15));
  assert.equal(execCalls.filter(c => c.pmArgs[1] === 'library' || c.pmArgs[1] === 'file').length, 0,
    'must not spawn Library subprocesses while on threads tab');
  assert.equal(local.libraryStale, true);
  local.selectSideTab('library', cx);
  await new Promise(r => setTimeout(r, 20));
  assert.equal(local.libraryStale, false);
});

test('real pm.py subprocess integration: library, memory, save with YAML --- & -weird.md, retopic, delete, history, and restore', async () => {
  const { mkdtempSync, mkdirSync, writeFileSync, rmSync } = await import('node:fs');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const { execFileSync } = await import('node:child_process');

  const tmpLedger = mkdtempSync(join(tmpdir(), 'pm-lib-int-'));
  const tmpRepo = join(tmpLedger, 'repo-dudu');
  const pmScript = new URL('../pm-dash/skill/scripts/pm.py', import.meta.url).pathname;
  const runPm = args => JSON.parse(execFileSync('python3', [pmScript, ...args], {
    env: { ...process.env, PM_HOME: tmpLedger, HERDR_PANE_ID: '', HC_TERMINAL_ID: '' },
    encoding: 'utf8',
  }));
  try {
    mkdirSync(join(tmpLedger, 'pms'), { recursive: true });
    mkdirSync(join(tmpLedger, 'tasks'), { recursive: true });
    mkdirSync(join(tmpLedger, 'projects', 'dudu', 'docs'), { recursive: true });
    mkdirSync(join(tmpLedger, 'projects', 'dudu', 'memory'), { recursive: true });
    mkdirSync(tmpRepo, { recursive: true });
    writeFileSync(join(tmpLedger, 'pms', 'dudu.json'), JSON.stringify({ name: 'pm-dudu', project: 'dudu', repo: tmpRepo }));
    writeFileSync(join(tmpRepo, 'CLAUDE.md'), '# Repo Rules\nAlways test.\n');
    writeFileSync(join(tmpLedger, 'projects', 'dudu', 'decisions.md'), '- 2026-11-20 archived decision\n');
    writeFileSync(join(tmpLedger, 'projects', 'dudu', 'docs', '-weird.md'), '# Dash file\nInitial.\n');

    // 1. Library payload includes docs (-weird.md + archive decisions.md) and repo instructions (CLAUDE.md).
    const lib = runPm(model.projectLibraryArgv('dudu'));
    assert.equal(lib.files.some(f => f.root === 'docs' && f.path === '-weird.md'), true);
    assert.equal(lib.files.some(f => f.root === 'docs' && f.path === 'decisions.md' && f.archive === true), true);
    assert.equal(lib.files.some(f => f.root === 'instructions' && f.path === 'CLAUDE.md' && f.writable === false), true);

    // 2. Read `-weird.md` and save updated text via `projectSaveArgv`.
    const f0 = runPm(model.projectFileArgv('dudu', 'docs', '-weird.md'));
    assert.equal(f0.path, '-weird.md');
    runPm(model.projectSaveArgv('dudu', 'docs', '-weird.md', { text: '# Dash file\nUpdated.\n', ifVersion: f0.version }));
    const f1 = runPm(model.projectFileArgv('dudu', 'docs', '-weird.md'));
    assert.equal(f1.text, '# Dash file\nUpdated.\n');

    // 3. Save new YAML frontmatter memory starting with `---` (verifies `--text=---\n...` never trips argparse).
    const memMd = model.buildMemoryMarkdown({
      name: 'yaml-safe',
      description: 'Save frontmatter safely',
      type: 'project',
      topic: 'architecture',
      body: 'Details here.',
    });
    runPm(model.projectSaveArgv('dudu', 'memory', 'yaml-safe.md', { text: memMd, ifVersion: 'new' }));
    const memList = runPm(model.projectMemoryArgv('dudu'));
    assert.equal(memList.files.some(f => f.name === 'yaml-safe' && f.topic === 'architecture'), true);

    // 4. Retopic to pitfall -> moves into `pitfalls` and updates type to `pitfall`.
    runPm(model.projectRetopicArgv('dudu', 'yaml-safe', { topic: 'pitfalls', type: 'pitfall' }));
    const memAfterRetopic = runPm(model.projectMemoryArgv('dudu'));
    const rtItem = memAfterRetopic.files.find(f => f.name === 'yaml-safe');
    assert.equal(rtItem?.type, 'pitfall');
    assert.equal(rtItem?.topic, 'pitfalls');

    // 5. Delete -> History -> Restore roundtrip on docs `-weird.md`.
    runPm(model.projectDeleteArgv('dudu', 'docs', '-weird.md', { ifVersion: f1.version }));
    const libAfterDel = runPm(model.projectLibraryArgv('dudu'));
    assert.equal(libAfterDel.files.some(f => f.root === 'docs' && f.path === '-weird.md'), false);
    const hist = runPm(model.projectHistoryArgv('dudu', 'docs', '-weird.md'));
    assert.equal(hist.items.length >= 1, true);
    runPm(model.projectRestoreArgv('dudu', 'docs', '-weird.md', { version: hist.items[0].version }));
    const fRestored = runPm(model.projectFileArgv('dudu', 'docs', '-weird.md'));
    assert.equal(fRestored.text, '# Dash file\nUpdated.\n');

    // 6. Chunked temp-file roundtrip via real `sh` (REMOTE_MKTEMP_ARGV + remoteAppendChunkArgv) + real `pm.py --from`.
    const hugeUtf8Doc = `---\n# Header\n${'中文🚀'.repeat(18000)}\nTAIL\n`;
    const tmpFile = execFileSync(model.REMOTE_MKTEMP_ARGV[0], model.REMOTE_MKTEMP_ARGV[1], { encoding: 'utf8' }).trim();
    try {
      for (const ch of model.chunkUtf8Text(hugeUtf8Doc, model.REMOTE_CHUNK_BYTES)) {
        const [shCmd, shArgs] = model.remoteAppendChunkArgv(tmpFile, ch);
        execFileSync(shCmd, shArgs, { encoding: 'utf8' });
      }
      runPm(model.projectSaveArgv('dudu', 'docs', 'chunked-utf8.md', { fromFile: tmpFile, ifVersion: 'new' }));
      const fChunked = runPm(model.projectFileArgv('dudu', 'docs', 'chunked-utf8.md'));
      assert.equal(fChunked.text, hugeUtf8Doc);
    } finally {
      execFileSync('rm', ['-f', '--', tmpFile]);
    }

    // 7. Real `pm.py` rejects `--if-version=new` overwrite of existing memory (`yaml-safe`) with exit 4 and allows deduplicated `-2`.
    let exitCode = 0;
    try {
      execFileSync('python3', [pmScript, ...model.projectSaveArgv('dudu', 'memory', 'yaml-safe.md', { text: memMd, ifVersion: 'new' })], {
        env: { ...process.env, PM_HOME: tmpLedger, HERDR_PANE_ID: '', HC_TERMINAL_ID: '' },
        encoding: 'utf8',
      });
    } catch (err) {
      exitCode = err.status;
    }
    assert.equal(exitCode, 4, 'real pm.py refuses to overwrite existing memory when --if-version=new');
    const dedupSlug = model.uniqueMemorySlug('yaml-safe', new Set(['yaml-safe']));
    const memMd2 = model.memoryFromDroppedFile('yaml-safe.md', 'New copy body', { slug: dedupSlug }).text;
    runPm(model.projectSaveArgv('dudu', 'memory', `${dedupSlug}.md`, { text: memMd2, ifVersion: 'new' }));
    const finalMems = runPm(model.projectMemoryArgv('dudu'));
    assert.equal(finalMems.files.some(f => f.name === 'yaml-safe-2'), true);
  } finally {
    rmSync(tmpLedger, { recursive: true, force: true });
  }
});

test('context usage and worker session pure model: tokens, handover levels, window joins, trimming, and turn folding', () => {
  const {
    contextTokens, contextShort, contextLabel, pmContextLevel, pmContextTip, workerContextTip,
    knownUnsupportedSession, isOldPmCommand, isMissingSessionModule, isQuietNoSession, isReplacedSessionError,
    projectSessionArgv, joinSessionItems, takeSessionWindow, trimSessionWindow,
    unwrapSessionText, briefPreview, toolsSummary, workedDuration, sessionTurns,
    threadList, subThreads, reviewRow, foldReviews,
  } = model;

  // 1) Context usage formatting & omission of 0 / missing values.
  for (const empty of [undefined, null, 0, -1, false, true, '5000']) {
    assert.equal(contextTokens(empty), 0);
    assert.equal(contextShort(empty), '');
    assert.equal(contextLabel('zh', empty), '');
    assert.equal(pmContextLevel(empty), 'none');
    assert.equal(workerContextTip('zh', empty), '');
  }
  assert.equal(contextLabel('zh', 123_012), '上下文 123k');
  assert.equal(contextLabel('en', 123_012), 'Context 123k');
  assert.equal(contextLabel('zh', 800), '上下文 800');
  // Strict `>` against `compact_tokens` (over strictly above limit, near strictly above 80%).
  assert.equal(pmContextLevel(160_000), 'normal');
  assert.equal(pmContextLevel(160_001), 'near');
  assert.equal(pmContextLevel(200_000), 'near');
  assert.equal(pmContextLevel(200_001), 'over');
  assert.equal(pmContextLevel(250_000, 350_000), 'normal');
  assert.equal(pmContextLevel(280_001, 350_000), 'near');
  assert.equal(pmContextLevel(350_001, 350_000), 'over');
  assert.match(pmContextTip('zh', 180_000), /接近 200k 压缩阈值/);
  assert.match(pmContextTip('zh', 215_000), /已超 200k 压缩阈值/);
  assert.match(pmContextTip('zh', 360_000, 350_000), /已超 350k 压缩阈值/);
  assert.match(pmContextTip('en', 360_000, 350_000), /over 350k compact threshold/);
  assert.match(workerContextTip('zh', 42_050), /42,050 tokens/);

  // Propagation onto threadList (open & finished), subThreads, and reviewRow without polluting tasks lacking tokens.
  const pm = { name: 'pm-dudu' };
  const rawTasks = [
    { id: 't-claude', pm: 'pm-dudu', title: 'Claude worker', status: 'in_progress', context_tokens: 64_200 },
    { id: 't-agy', pm: 'pm-dudu', title: 'Agy worker', status: 'in_progress', engine: { kind: 'agy' } },
    { id: 't-rev-target', pm: 'pm-dudu', title: 'Reviewed', status: 'review', context_tokens: 91_000 },
    { id: 't-rev-target-review', pm: 'pm-dudu', title: 'Review', status: 'in_progress', review_of: 't-rev-target', context_tokens: 38_400 },
    { id: 't-part', pm: 'pm-dudu', title: 'Sub-part', status: 'done', parent: 't-claude', context_tokens: 19_100 },
    { id: 't-done', pm: 'pm-dudu', title: 'Done Claude', status: 'merged', updated: '2026-11-21 12:00', context_tokens: 112_000 },
    { id: 't-done-noctx', pm: 'pm-dudu', title: 'Done Agy', status: 'merged', updated: '2026-11-21 11:00' },
  ];
  const folded = foldReviews(rawTasks);
  const tl = threadList(pm, folded, [], [], [], [], 'zh');
  const openById = Object.fromEntries(tl.open.map(r => [r.task, r]));
  assert.equal(openById['t-claude'].contextTokens, 64_200);
  assert.equal(openById['t-agy'].contextTokens, undefined);
  assert.equal(openById['t-rev-target'].contextTokens, 91_000);
  const rev = reviewRow(folded.find(t => t.id === 't-rev-target'), [], [], 'zh');
  assert.equal(rev.contextTokens, 38_400);
  const parts = subThreads(folded, 't-claude', [], [], 'zh');
  assert.equal(parts[0].contextTokens, 19_100);
  const finById = Object.fromEntries(tl.finished.map(r => [r.task, r]));
  assert.equal(finById['t-done'].contextTokens, 112_000);
  assert.equal(finById['t-done-noctx'].contextTokens, undefined);

  // 2) Unsupported agent & CLI error classification.
  assert.equal(knownUnsupportedSession({ engine: { kind: 'agy' } }), true);
  assert.equal(knownUnsupportedSession({ engine: { kind: 'codex' }, session: { kind: 'claude', id: 'old' } }), true);
  assert.equal(knownUnsupportedSession({ engine: { kind: 'claude' } }), false);
  assert.equal(knownUnsupportedSession({ session: { kind: 'pi', id: 'p1' } }), true);
  assert.equal(knownUnsupportedSession({}), false);
  assert.equal(isOldPmCommand({ code: 2, stderr: "pm.py: error: argument project_cmd: invalid choice: 'session'" }), true);
  assert.equal(isMissingSessionModule({ code: 1, stderr: 'pm_sessions.py is missing beside pm.py' }), true);
  assert.equal(isQuietNoSession({ code: 1, stderr: "session kind 'agy' is not supported" }), true);
  assert.equal(isQuietNoSession({ code: 1, stderr: 'no session found for task dudu-x' }), true);
  assert.equal(isQuietNoSession({ code: 1, stderr: 'transcript not found for task dudu-x' }), true);
  assert.equal(isQuietNoSession({ code: 1, stderr: 'no unambiguous Claude session found for task dudu-x' }), true);
  assert.equal(isQuietNoSession({ code: 255, stderr: 'ssh: connect to host box: Connection refused' }), false);
  assert.equal(isReplacedSessionError('the transcript is shorter than that: it was replaced'), true);
  assert.deepEqual(projectSessionArgv('dudu-e', { before: 4096, limit: 80 }), ['project', 'session', 'dudu-e', '--before', '4096', '--limit', '80']);
  assert.deepEqual(projectSessionArgv('dudu-e', { after: 8192, limit: 80 }), ['project', 'session', 'dudu-e', '--after', '8192', '--limit', '80']);

  // 3) Session window merging, orphan tool_result joining across windows, and line-boundary trimming.
  const win1 = {
    kind: 'claude', id: 'sid-1', started: '2026-11-21T10:00:00.000Z', ended: '2026-11-21T10:05:00.000Z',
    items: [
      { type: 'result', id: 'call-older', output: 'joined across page!', error: false, offset: 250 },
      { type: 'user', at: '2026-11-21T10:02:00.000Z', text: '<hc from="t1">请检查代码\n\n/tmp/shot.png</hc>', offset: 300 },
      { type: 'text', at: '2026-11-21T10:02:05.000Z', text: '正在检查。', offset: 400 },
      { type: 'tool', id: 'call-tail', at: '2026-11-21T10:02:06.000Z', name: 'Bash', input: 'npm test', output: '', error: false, offset: 400 },
    ],
    from: 200, offset: 400, earlier: true, more: false, reset: false, context: 52_000,
  };
  let held = takeSessionWindow(null, win1, 'end', { taskId: 'dudu-e' });
  assert.equal(held.context, 52_000);
  assert.equal(held.earlier, true);

  // Incremental `--after 400` brings tool_result for `call-tail` plus assistant conclusion.
  held = takeSessionWindow(held, {
    kind: 'claude', id: 'sid-1', started: '', ended: '2026-11-21T10:06:30.000Z',
    items: [
      { type: 'result', id: 'call-tail', output: '1 fail', error: true, offset: 500 },
      { type: 'tool', id: 'call-read', at: '2026-11-21T10:06:10.000Z', name: 'Read', input: '~/repo/main.js', output: 'ok', error: false, offset: 550 },
      { type: 'text', at: '2026-11-21T10:06:30.000Z', text: '修好了！', offset: 600 },
    ],
    from: 400, offset: 600, earlier: true, more: false, reset: false, context: 68_000,
  }, 'after', { taskId: 'dudu-e' });
  assert.equal(held.context, 68_000);
  const tailCall = held.items.find(i => i.id === 'call-tail');
  assert.deepEqual([tailCall.output, tailCall.error], ['1 fail', true]);

  // Backward `--before 200` brings `call-older` and joins the orphan result that stood at byte 250!
  held = takeSessionWindow(held, {
    kind: 'claude', id: 'sid-1', started: '', ended: '',
    items: [
      { type: 'user', at: '2026-11-21T10:00:00.000Z', text: '<hc from="t1">' + '任务书行\n'.repeat(12) + '</hc>', offset: 100 },
      { type: 'tool', id: 'call-older', at: '2026-11-21T10:01:00.000Z', name: 'Grep', input: 'context_tokens', output: '', error: false, offset: 200 },
    ],
    from: 0, offset: 200, earlier: false, more: false, reset: false,
  }, 'before', { taskId: 'dudu-e', askedFrom: 200 });
  assert.equal(held.earlier, false);
  assert.equal(held.from, 0);
  const olderCall = held.items.find(i => i.id === 'call-older');
  assert.equal(olderCall.output, 'joined across page!');

  // Turn formatting: unwraps <hc>, folds long brief, extracts trailing file path, folds consecutive tools with error count.
  const turns = sessionTurns(held.items, { lang: 'zh' });
  assert.equal(turns.length, 4);
  assert.equal(turns[0].role, 'user');
  assert.equal(turns[0].from, 'PM');
  assert.equal(turns[0].long, true);
  assert.equal(turns[1].role, 'assistant');
  assert.equal(turns[1].parts[0].label, '搜了 1 次');
  assert.deepEqual([turns[2].role, turns[2].text, turns[2].files], ['user', '请检查代码', ['/tmp/shot.png']]);
  assert.equal(turns[3].role, 'assistant');
  assert.deepEqual(turns[3].parts.map(p => p.kind), ['text', 'tools', 'text']);
  assert.equal(turns[3].parts[1].label, '跑了 1 条命令，读了 1 个文件');
  assert.equal(turns[3].parts[1].errors, 1);
  assert.equal(workedDuration('zh', held.started, held.ended), '干了 6 分 30 秒');
  assert.equal(workedDuration('en', held.started, held.ended), 'Worked 6m 30s');
  assert.equal(toolsSummary('en', [{ name: 'Edit' }, { name: 'WebFetch' }, { name: 'CustomTool' }]),
    'Edited 1 file, Checked web 1 time, Used 1 other tool');
  assert.deepEqual(unwrapSessionText('<pasted_content>你好<system-reminder>ignore</system-reminder></pasted_content>'),
    { text: '你好', fromAgent: false });
  assert.equal(briefPreview('短消息').long, false);

  // trimSessionWindow cuts only between lines (never splitting items that share an `offset`).
  const manyItems = [
    { type: 'text', text: 'a', offset: 100 },
    { type: 'tool', id: '1', name: 'Read', offset: 200 },
    { type: 'tool', id: '2', name: 'Bash', offset: 200 }, // shares offset 200!
    { type: 'text', text: 'b', offset: 300 },
    { type: 'text', text: 'c', offset: 400 },
  ];
  const trimmed = trimSessionWindow({ ...held, items: manyItems, from: 0, earlier: false }, 3, 0);
  assert.equal(trimmed.from, 200);
  assert.equal(trimmed.earlier, true);
  assert.deepEqual(trimmed.items.map(i => i.offset), [300, 400]);
});

test('PmProject renders context usage, loads/pages worker session tab, folds tools, and degrades quietly for agy/old-remote/missing sessions', async () => {
  const { readFileSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } = await import('node:fs');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const { execFileSync } = await import('node:child_process');

  // 1) End-to-end against real `pm.py project session` in a temporary ledger + temporary HOME!
  const tmpRoot = mkdtempSync(join(tmpdir(), 'pm-proj-e-'));
  try {
    const fakeHome = join(tmpRoot, 'home');
    const fakeLedger = join(tmpRoot, 'ledger');
    const wt = join(tmpRoot, 'wt');
    mkdirSync(wt, { recursive: true });
    mkdirSync(join(fakeLedger, 'tasks'), { recursive: true });
    mkdirSync(join(fakeLedger, 'pms'), { recursive: true });
    const folderName = wt.replace(/[^A-Za-z0-9]/g, '-');
    const claudeDir = join(fakeHome, '.claude', 'projects', folderName);
    mkdirSync(claudeDir, { recursive: true });
    const sid = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
    const transcriptLines = [
      JSON.stringify({ type: 'user', timestamp: '2026-11-21T14:00:00.000Z', message: { content: '<hc from="t1">请实现线程 E 界面</hc>' } }),
      JSON.stringify({
        type: 'assistant', timestamp: '2026-11-21T14:01:00.000Z',
        message: {
          content: [
            { type: 'text', text: '先查看现有代码。' },
            { type: 'tool_use', id: 'tu_1', name: 'Read', input: { file_path: `${fakeHome}/repo/main.js` } },
          ],
          usage: { input_tokens: 300, cache_read_input_tokens: 45_000 },
        },
      }),
      JSON.stringify({
        type: 'user', timestamp: '2026-11-21T14:01:02.000Z',
        message: { content: [{ type: 'tool_result', tool_use_id: 'tu_1', content: 'export default class PmProject {}' }] },
      }),
      JSON.stringify({
        type: 'assistant', timestamp: '2026-11-21T14:03:00.000Z',
        message: {
          content: [{ type: 'text', text: '已完成修改并通过检查。' }],
          usage: { input_tokens: 500, cache_read_input_tokens: 76_000 },
        },
      }),
    ];
    writeFileSync(join(claudeDir, `${sid}.jsonl`), transcriptLines.join('\n') + '\n');
    writeFileSync(join(fakeLedger, 'tasks', 'dudu-e.json'), JSON.stringify({
      id: 'dudu-e', title: '用量与对话界面', project: 'dudu', repo: wt, worktree: wt,
      status: 'review', worker: { kind: 'claude', model: 'opus' },
      session: { kind: 'claude', id: sid },
      log: [{ at: '2026-11-21 09:05', by: 'hc:tw1', text: 'status=review; 完成' }],
    }));
    writeFileSync(join(fakeLedger, 'tasks', 'dudu-agy.json'), JSON.stringify({
      id: 'dudu-agy', title: 'Carbon 任务', project: 'dudu', repo: wt, worktree: wt,
      status: 'in_progress', worker: { kind: 'agy', model: 'gemini-4-carbon-high' },
      log: [{ at: '2026-11-21 09:00', by: 'hc:tw2', text: 'dispatched' }],
    }));

    const pmScript = new URL('../pm-dash/skill/scripts/pm.py', import.meta.url).pathname;
    const childEnv = { PATH: process.env.PATH || '', HOME: fakeHome, PM_HOME: fakeLedger };
    const pageNewest = JSON.parse(execFileSync('python3', [pmScript, ...model.projectSessionArgv('dudu-e', { limit: 2 })], {
      env: childEnv, encoding: 'utf8',
    }));
    assert.equal(pageNewest.earlier, true);
    assert.equal(pageNewest.context, 76_500);
    const pageOlder = JSON.parse(execFileSync('python3', [pmScript, ...model.projectSessionArgv('dudu-e', { before: pageNewest.from, limit: 10 })], {
      env: childEnv, encoding: 'utf8',
    }));
    assert.equal(pageOlder.earlier, false);

    // 2) Mount PmProject and verify UI element IDs, zero-subprocess discipline, tool fold toggle, earlier paging, and agy/old-remote degradation.
    const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
      .replace(/^import [\s\S]*?;$/gm, '').replace('export default class PmProject extends View', 'return class');
    let sessionCalls = 0;
    let oldRemote = false;
    const nodes = new Map();
    const makeEl = () => {
      const rec = { id: '', texts: [], kids: [], clicks: null, hover: null, wheel: null, tips: [] };
      const allTexts = r => [...r.texts, ...r.kids.flatMap(allTexts)];
      const proxy = new Proxy(function () {}, {
        get: (_, key) => {
          if (key === Symbol.toPrimitive) return () => 0;
          if (key === '__rec') return rec;
          return (...args) => {
            if (key === 'id') {
              rec.id = String(args[0]);
              nodes.set(rec.id, rec);
            } else if (key === 'child' && typeof args[0] === 'string') {
              rec.texts.push(args[0]);
            } else if (key === 'child' && args[0]?.__rec) {
              rec.kids.push(args[0].__rec);
            } else if (key === 'content' && args[0]?.__rec) {
              rec.kids.push(args[0].__rec);
            } else if (key === 'children' && Array.isArray(args[0])) {
              for (const k of args[0]) {
                if (typeof k === 'string') rec.texts.push(k);
                else if (k?.__rec) rec.kids.push(k.__rec);
              }
            } else if (key === 'on_click') {
              rec.clicks = args[0];
            } else if (key === 'on_hover') {
              rec.hover = args[0];
            } else if (key === 'on_scroll_wheel') {
              rec.wheel = args[0];
            } else if (key === 'tooltip') {
              rec.tips.push(args[0]);
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
    const stubs = {
      View: class {}, ...model, ...stepsView,
      div: makeEl, h_flex: makeEl, v_flex: makeEl, svg: makeEl, image: makeEl,
      TextView: { markdown: (_id, md) => { const p = makeEl(); p.child(md); return p; }, html: (_id, h) => { const p = makeEl(); p.child(h); return p; } },
      Textarea: { new: () => makeEl() },
      Input: { new: () => makeEl() },
      Popup: { new: (id, trigger) => makeEl().id(id).child(trigger) },
      execPython: async (_exec, argv, opts) => stubs.exec('python3', argv, opts),
      appHome: () => '/app', home: () => fakeHome,
      localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
      appWindow: () => ({ platform: 'macos' }),
      terminals: () => [], agents: () => [], panes: () => [], spaces: () => [],
      theme: () => ({
        canvas: '#111111', surface: '#181818', raised: '#222222', chrome: '#161616', hover: '#2a2a2a',
        border: '#333333', input: '#3a3a3a', foreground: '#eeeeee', background: '#111111',
        muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', accent_foreground: '#ffffff',
        blocked: '#ff5f56', ansi2: '#27c93f', ansi3: '#f5a623', solid: '#eeeeee', solid_foreground: '#111111',
      }),
      shared: () => ({ pm: 'pm-dudu' }),
      layout: () => ({ id: 'pm-stage', active: 'pm-project' }),
      exec: async (_command, args) => {
        if (args?.includes('session')) {
          sessionCalls++;
          if (oldRemote) {
            return { code: 2, stdout: '', stderr: "pm.py: error: argument project_cmd: invalid choice: 'session'" };
          }
          if (args.includes('--before')) {
            return { code: 0, stdout: JSON.stringify(pageOlder), stderr: '' };
          }
          return { code: 0, stdout: JSON.stringify(pageNewest), stderr: '' };
        }
        if (args?.includes('log')) {
          const logPage = oldRemote
            ? { entries: [{ n: 5, at: '2026-11-21 09:05', by: 'hc:tw1', text: 'status=in_progress; working' }], earlier: 5, total: 6 }
            : { entries: [{ n: 0, at: '2026-11-21 09:05', by: 'hc:tw1', text: 'status=review; 完成' }], earlier: 0, total: 1 };
          return { code: 0, stdout: JSON.stringify(logPage), stderr: '' };
        }
        return { code: 0, stdout: JSON.stringify({ events: [], from: 0, offset: 0, earlier: false }), stderr: '' };
      },
      readTextFile: async path => {
        if (path.endsWith('/dudu-e.json')) return readFileSync(join(fakeLedger, 'tasks', 'dudu-e.json'), 'utf8');
        if (path.endsWith('/dudu-agy.json')) return readFileSync(join(fakeLedger, 'tasks', 'dudu-agy.json'), 'utf8');
        return null;
      },
    };
    const scope = new Proxy(stubs, {
      has: (target, name) => name in target || !(name in globalThis),
      get: (target, name) => (name in target ? target[name] : name === Symbol.unscopables ? undefined : makeEl()),
    });
    const Mod = new Function('scope', `with (scope) { ${source} }`)(scope);
    const pmRec = { name: 'pm-dudu', project: 'dudu', repo: wt, conversation: join(fakeLedger, 'projects/dudu/conversation.jsonl'), context_tokens: 205_000 };
    const stateTasks = [
      { id: 'dudu-e', pm: 'pm-dudu', title: '用量与对话界面', status: 'review', branch: 'dev/proj-e', engine: { kind: 'claude', model: 'opus' }, context_tokens: 76_500, updated: '2026-11-21 09:05' },
      { id: 'dudu-agy', pm: 'pm-dudu', title: 'Carbon 任务', status: 'in_progress', branch: 'dev/agy', engine: { kind: 'agy', model: 'gemini-4-carbon-high' }, updated: '2026-11-21 09:00' },
    ];
    const sessionScrolled = [];
    const cx = { spawn: f => f(cx), notify() {}, timer: { after() {}, every() {} }, stop_propagation() {} };
    const makeInput = () => ({ value: () => '', set_value() {}, set_selected_range() {}, focus() {} });
    const view = Object.assign(Object.create(Mod.prototype), {
      machine: '', pmName: 'pm-dudu', stateFor: '', state: { pms: [pmRec], tasks: stateTasks, lang: 'zh' },
      ledgerHome: fakeLedger, watching: {}, remoteHome: '', remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '',
      logPath: pmRec.conversation, logSlug: 'dudu', logState: null, events: [], pending: [], pastes: [], items: [],
      thread: '', detail: false, threadTab: 'log', outgoing: new Map(), files: [], threadFiles: [],
      sideTab: 'threads', librarySlug: '', libraryRoots: [], libraryFiles: [], libraryRead: false, libraryProbed: false, libraryStale: false,
      libraryClosed: new Set(), libraryQuery: '', libraryDropBusy: '', libraryDropError: '',
      memorySlug: '', memoryData: null, memoryRead: false, memoryStale: false, memoryFoldOverrides: new Map(),
      memoryProjectOpen: true, memoryPersonalOpen: false, memoryCandidatesOpen: false, memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
      activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '', docShownBytes: model.DOC_INITIAL_BYTES,
      docMatchPos: 0, editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
      confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
      input: makeInput(), threadInput: makeInput(), libraryInput: makeInput(), memoryInput: makeInput(), docFindInput: makeInput(),
      docNameInput: makeInput(), memDescInput: makeInput(), docEditorInput: makeInput(),
      scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item: i => sessionScrolled.push(i) },
      libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
      keyFocus: { focus() {} }, heights: new Map(), unfolded: new Map(), atWork: new Set(),
      wide: true, listShown: null, viewWidth: 1280, high: 800, tall: 700, count: 0, settle: 0, away: false, rise: 0,
    });

    // (a) Resting view: PM header shows "上下文 205k" pill; 1-line thread rows keep secondary context in hover card (Claude worker shows "上下文 77k", agy worker omits context).
    nodes.clear();
    view.render(cx);
    assert.deepEqual(nodes.get('pm-context')?.texts, ['上下文 205k']);
    assert.equal(nodes.has('list-dudu-e'), true);
    nodes.get('list-dudu-e').hover(true, cx);
    nodes.clear();
    view.render(cx);
    assert.match(nodes.get('hover-card-task:dudu-e')?.allTexts().join(' ') || '', /上下文 77k/);
    nodes.get('list-dudu-agy').hover(true, cx);
    nodes.clear();
    view.render(cx);
    assert.doesNotMatch(nodes.get('hover-card-task:dudu-agy')?.allTexts().join(' ') || '', /上下文/);
    view.hoverKey = '';

    // (b) Open Claude thread on default Log tab: `#thread-tabs` shows and `#thread-status` carries `上下文 77k` tooltip immediately from `state`, with 0 `project session` calls!
    sessionCalls = 0;
    view.openThread('dudu-e', cx);
    await new Promise(r => setTimeout(r, 15));
    nodes.clear();
    view.render(cx);
    assert.equal(sessionCalls, 0, 'opening on Log tab when state already has context_tokens must not spawn project session');
    assert.equal(nodes.has('thread-tabs'), true);
    nodes.get('thread-status')?.hover?.(true, cx);
    nodes.clear();
    view.render(cx);
    assert.match(nodes.get('hover-tip-thread-status')?.allTexts().join(' ') || '', /上下文 77k/);
    view.hoverKey = '';

    // (c) Switch to Conversation tab ("对话"): fetches newest window, shows `#thread-session` and `#thread-session-earlier`.
    view.selectThreadTab('session', cx);
    await new Promise(r => setTimeout(r, 15));
    assert.equal(sessionCalls, 1);
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.has('thread-session'), true);
    assert.equal(nodes.has('thread-session-earlier'), true);

    // (d) Page backward ("更早"): loads older window with Read tool call, hides `#thread-session-earlier` once from=0, and toggles tool fold open!
    nodes.get('thread-session-earlier').clicks({}, cx);
    await new Promise(r => setTimeout(r, 15));
    assert.equal(view.threadSession.earlier, false);
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.has('thread-session-earlier'), false);
    assert.ok(sessionScrolled.length > 0, 'earlier paging anchors scroll position');
    const toolFoldId = [...nodes.keys()].find(id => id.startsWith('session-tools-g:'));
    assert.ok(toolFoldId, 'assistant tool call group is rendered folded');
    assert.equal([...nodes.keys()].some(id => id.startsWith('session-tools-body-')), false);
    nodes.get(toolFoldId).clicks({}, cx);
    nodes.clear();
    view.render(cx);
    assert.equal([...nodes.keys()].some(id => id.startsWith('session-tools-body-')), true, 'clicking tool fold expands tool call details');

    // (e) Switch to `dudu-agy` (Antigravity worker): spawns 0 `project session` calls, hides `#thread-tabs`, shows `#thread-log`, no error!
    sessionCalls = 0;
    view.openThread('dudu-agy', cx);
    await new Promise(r => setTimeout(r, 15));
    nodes.clear();
    view.render(cx);
    assert.equal(sessionCalls, 0, 'non-Claude worker must not spawn project session');
    assert.equal(nodes.has('thread-tabs'), false);
    nodes.get('thread-status')?.hover?.(true, cx);
    nodes.clear();
    view.render(cx);
    assert.doesNotMatch(nodes.get('hover-tip-thread-status')?.allTexts().join(' ') || '', /上下文/);
    view.hoverKey = '';
    assert.equal(nodes.has('thread-log'), true);
    assert.equal(view.threadSessionError, '');

    // (f) Partial-upgrade remote `pm.py` (like dev at c14b051: has `project events`, `project log`, and `project library`,
    //     but lacks `project session` -> `invalid choice: 'session'`):
    //     probing a Claude thread ONLY sets `remoteNoSession`, keeping `remoteNoProject === ''`, earlier paging, and Library tab intact!
    oldRemote = true;
    stubs.shared = () => ({ pm: 'dev/pm-dudu', machine: 'dev' });
    const remoteView = Object.assign(Object.create(Mod.prototype), {
      ...view, machine: 'dev', pmName: 'dev/pm-dudu', stateFor: 'dev', remoteHome: fakeLedger, tasks: null,
      remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '',
      logState: { events: [{ at: '2026-11-21 09:00:00', type: 'user', text: 'hi', offset: 100 }], from: 50, offset: 100, earlier: true },
      events: [{ at: '2026-11-21 09:00:00', type: 'user', text: 'hi', offset: 100 }],
      thread: '', detail: false, threadTab: 'log',
    });
    // Task on dev without context_tokens in state (older pm.py), so opening it triggers background probe `project session`.
    remoteView.state = {
      pms: [pmRec],
      tasks: [{ id: 'dudu-e', pm: 'pm-dudu', title: '用量与对话界面', status: 'in_progress', branch: 'dev/proj-e', engine: { kind: 'claude', model: 'opus' } }],
      lang: 'zh',
    };
    remoteView.threadLog = { entries: [{ n: 5, at: '2026-11-21 09:05', by: 'hc:tw1', text: 'status=in_progress; working' }], earlier: 5, total: 6 };
    remoteView.openThread('dudu-e', cx);
    await new Promise(r => setTimeout(r, 20));
    assert.equal(remoteView.remoteNoSession, 'dev', 'marks session unsupported on dev');
    assert.equal(remoteView.remoteNoProject, '', 'must NOT disable project events/log paging on dev');
    assert.equal(remoteView.remoteNoLibrary, '', 'must NOT disable Library tab on dev');
    assert.equal(remoteView.librarySupported(), true, 'Library tab remains supported on dev');
    assert.equal(remoteView.threadSessionError, '');
    nodes.clear();
    remoteView.render(cx);
    assert.equal(nodes.has('thread-tabs'), false, 'hides Conversation tab on dev');
    assert.equal(nodes.has('conversation-earlier'), true, 'keeps conversation earlier paging on dev');
    assert.equal(nodes.has('thread-log-earlier'), true, 'keeps thread log earlier paging on dev');

    // Close thread detail on dev -> resting side panel still shows `#panel-tabs` with Library tab!
    remoteView.detail = false;
    nodes.clear();
    remoteView.render(cx);
    assert.equal(nodes.has('panel-tab-library'), true, 'Library tab stays visible in resting side panel on dev');

    // (g) Remote polling rate: when `project session` IS supported on a remote machine and `对话` is open on a working thread,
    //     `shouldPollThreadSession()` is false (never runs on the 4s local timer) and `syncThreadSession()` throttles background
    //     reads to `SESSION_POLL_REMOTE_MS` (>= 20s, slower than the 10s main refresh).
    oldRemote = false;
    sessionCalls = 0;
    const liveRemote = Object.assign(Object.create(Mod.prototype), {
      ...remoteView, tasks: null, onStage: true, remoteNoSession: '', detail: true, thread: 'dudu-e', threadTab: 'session',
      lastThreadSendAt: 0, lastSessionReadAt: 0,
      state: {
        compact_tokens: 400_000,
        pms: [{ ...pmRec, context_tokens: 250_000 }],
        tasks: [{ id: 'dudu-e', pm: 'pm-dudu', title: '远程任务', status: 'in_progress', engine: { kind: 'claude', model: 'opus' }, context_tokens: 76_500 }],
        lang: 'zh',
      },
    });
    liveRemote.resetThreadSession();
    assert.equal(liveRemote.shouldPollThreadSession(), false, '4s fast timer never polls remote sessions');
    liveRemote.syncThreadSession(cx); // initial load on opening Conversation tab
    await new Promise(r => setTimeout(r, 15));
    assert.equal(sessionCalls, 1);
    liveRemote.syncThreadSession(cx); // 10s main refresh arrives before 20s remote cooldown -> skipped!
    await new Promise(r => setTimeout(r, 15));
    assert.equal(sessionCalls, 1, '10s refresh does not re-exec remote session before SESSION_POLL_REMOTE_MS');
    liveRemote.lastSessionReadAt = Date.now() - model.SESSION_POLL_REMOTE_MS - 10;
    liveRemote.syncThreadSession(cx); // 20s elapsed -> refreshes remote session once
    await new Promise(r => setTimeout(r, 15));
    assert.equal(sessionCalls, 2);
    // Also verify custom `compact_tokens: 400_000` in header tip on liveRemote (250k is normal under 400k, not 'over'!).
    nodes.clear();
    liveRemote.render(cx);
    nodes.get('pm-context')?.hover?.(true, cx);
    nodes.clear();
    liveRemote.render(cx);
    assert.match(nodes.get('hover-tip-pm-context')?.allTexts().join(' ') || '', /400k/);
    liveRemote.hoverKey = '';
    // Per-PM `compact_tokens` (e.g. Codex/pi 220k) wins over top-level `state.compact_tokens` (200k), so 210k is 'near' not 'over'.
    liveRemote.state = {
      ...liveRemote.state,
      compact_tokens: 200_000,
      pms: [{ ...pmRec, agent: 'codex', context_tokens: 210_000, compact_tokens: 220_000 }],
    };
    nodes.clear();
    liveRemote.render(cx);
    nodes.get('pm-context')?.hover?.(true, cx);
    nodes.clear();
    liveRemote.render(cx);
    assert.match(nodes.get('hover-tip-pm-context')?.allTexts().join(' ') || '', /接近 220k 压缩阈值/);
    liveRemote.hoverKey = '';
  } finally {
    rmSync(tmpRoot, { recursive: true, force: true });
  }
});

test('Interface F: Start offline PM, bring back lost agents, and closed-can-reattach thread states (en & zh)', async () => {
  // 1) Pure model checks: closed vs disconnected, pmStartState, lostShown / mergeDismissedLost, lostSummary, bringBackSteps, escapeStep.
  const closedTask = {
    id: 'dudu-rep', pm: 'pm-dudu', title: '空闲已关线程', status: 'review', branch: 'dev/rep',
    offline: true, pane: 'hc:tw2',
    closed: { pane: 'hc:tw2', at: '2026-11-21 10:30', why: 'workers.close_reported' },
  };
  const closedIp = {
    id: 'dudu-ip-closed', pm: 'pm-dudu', title: '主动关掉的进行中', status: 'in_progress',
    offline: true, pane: 'hc:tw3',
    closed: { pane: 'hc:tw3', at: '2026-11-21 10:40', why: 'killed' },
  };
  const crashedIp = {
    id: 'dudu-crashed', pm: 'pm-dudu', title: '重启丢失线程', status: 'in_progress', branch: 'dev/crash',
    offline: true, pane: 'hc:tw4',
  };
  assert.equal(model.isClosedTask(closedTask), true);
  assert.equal(model.isClosedTask({ ...closedTask, pane: 'hc:new' }), false);
  assert.equal(model.isClosedTask(crashedIp), false);
  assert.equal(model.statusLabel('zh', 'in_progress', false, true, false, true), '已关闭，可重连');
  assert.equal(model.statusLabel('en', 'in_progress', false, true, false, true), 'Closed · can reattach');
  assert.equal(model.statusLabel('zh', 'in_progress', false, true, false, false), '已断开');
  assert.equal(model.closedTip('zh', closedTask.closed), '已关闭，可重连（汇报后空闲关闭 · 2026-11-21 10:30）');
  assert.equal(model.closedTip('en', closedTask.closed), 'Closed · can reattach (idle after report, 2026-11-21 10:30)');

  assert.equal(model.pmStartState({ name: 'pm-dudu', repo: '/r/dudu', runtime: 'hc', repo_ok: true }, { address: 't1' }), 'online');
  assert.equal(model.pmStartState({ name: 'pm-dudu', repo: '/r/dudu', runtime: 'hc', repo_ok: true }, null, true), 'starting');
  assert.equal(model.pmStartState({ name: 'pm-dudu', repo: '/r/dudu', runtime: 'hc', repo_ok: true }, null), 'startable');
  assert.equal(model.pmStartState({ name: 'pm-dudu', repo: '/r/dudu' }, null), 'startable'); // older remote pm.py without runtime/repo_ok
  assert.equal(model.pmStartState({ name: 'pm-dudu', repo: '/r/dudu', archived: '2026-11-01' }, null), 'archived');
  assert.equal(model.pmStartState({ name: 'pm-dudu', repo: '/r/dudu', pane: 'w1:p2', status: 'idle' }, null), 'tui_live');
  assert.equal(model.pmStartState({ name: 'pm-dudu', repo: '/r/dudu', repo_ok: false }, null), 'missing_repo');
  assert.deepEqual(model.startPmArgv('/app/pm.py', { repo: '/r/dudu', agent: 'codex' }),
    ['python3', '/app/pm.py', 'start', '--repo', '/r/dudu', '--kind', 'codex']);

  const lost = {
    pm: { address: 'tpm', how: 'server_stop' },
    threads: [
      { id: 'dudu-crashed', title: '重启丢失线程', address: 'tw4', how: 'server_stop' },
      { id: 'dudu-b', title: '第二个线程', address: 'tw5', how: 'exited' },
    ],
    restart: true,
    key: 'pm@tpm;dudu-crashed@tw4;dudu-b@tw5',
  };
  assert.equal(model.lostSummary('zh', lost), '重启后 PM 和 2 个 agent 没回来');
  assert.equal(model.lostSummary('en', lost), 'PM and 2 agents did not come back after restart');
  assert.equal(model.lostSummary('zh', { ...lost, restart: false, pm: null, threads: [lost.threads[0]] }), '1 个 agent 停了，没在运行');
  assert.equal(model.lostSummary('en', { ...lost, restart: false, pm: null, threads: [lost.threads[0]] }), '1 agent stopped running');
  assert.equal(model.lostShown(lost, ''), true);
  const dismissed = model.mergeDismissedLost('', lost.key);
  assert.equal(model.lostShown(lost, dismissed), false);
  // A newly lost thread causes the banner to appear again.
  assert.equal(model.lostShown({ ...lost, key: `${lost.key};dudu-new@tw9` }, dismissed), true);
  assert.equal(model.escapeStep({ bringBack: true, detail: true }), 'bringBack');

  const listZh = model.threadList({ name: 'pm-dudu', repo: '/r/dudu' }, [closedTask, closedIp, crashedIp], [], [], [], [], 'zh');
  assert.equal(listZh.open.find(r => r.task === 'dudu-rep').closed.why, 'workers.close_reported');
  assert.equal(listZh.open.find(r => r.task === 'dudu-crashed').closed, undefined);

  // 2) Mount PmProject and verify Header `#pm-start`, `#pm-offline-bar`, `#lost-banner` -> `#lost-card` -> sequential execution & Esc, and closed thread pills in EN & ZH.
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '').replace('export default class PmProject extends View', 'return class');
  const nodes = new Map();
  const execCalls = [];
  const storage = new Map();
  const prevStorage = globalThis.localStorage;
  globalThis.localStorage = {
    getItem: k => (storage.has(k) ? storage.get(k) : null),
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k),
  };
  try {
    const makeEl = () => {
      const rec = { id: '', texts: [], kids: [], clicks: null, hover: null, tips: [], icons: [] };
      const allTexts = r => [...r.texts, ...r.kids.flatMap(allTexts)];
      const proxy = new Proxy(function () {}, {
        get: (_, key) => {
          if (key === Symbol.toPrimitive) return () => 0;
          if (key === '__rec') return rec;
          if (key === '__allTexts') return () => allTexts(rec);
          return (...args) => {
            if (key === 'id') {
              rec.id = String(args[0]);
              nodes.set(rec.id, rec);
            } else if (key === 'child') {
              if (typeof args[0] === 'string') rec.texts.push(args[0]);
              else if (args[0]?.__rec) rec.kids.push(args[0].__rec);
              if (args[0]?.__svg) rec.icons.push(args[0].__svg);
            } else if (key === 'content') {
              if (args[0]?.__rec) rec.kids.push(args[0].__rec);
            } else if (key === 'children' && Array.isArray(args[0])) {
              for (const k of args[0]) {
                if (typeof k === 'string') rec.texts.push(k);
                else if (k?.__rec) rec.kids.push(k.__rec);
              }
            } else if (key === 'on_click') {
              rec.clicks = args[0];
            } else if (key === 'on_hover') {
              rec.hover = args[0];
            } else if (key === 'tooltip') {
              rec.tips.push(args[0]);
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
    const svgStub = path => {
      const el = makeEl();
      el.__svg = path;
      return el;
    };
    let liveTerms = [];
    const stubs = {
      View: class {}, div: makeEl, v_flex: makeEl, h_flex: makeEl, svg: svgStub, image: makeEl,
      TextView: { markdown: (_id, text) => makeEl().child(String(text || '')), html: (_id, html) => makeEl().child(String(html || '')) },
      TextareaState: { new: () => ({ set_auto_grow() {}, on() {}, value: () => '', set_value() {}, set_selected_range() {}, focus() {} }) },
      Textarea: { new: () => makeEl() },
      Popup: { new: (id, trigger) => makeEl().id(id).child(trigger) },
      InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, focus() {} }) },
      Input: { new: () => makeEl() },
      ScrollHandle: { new: () => ({ scroll_to_item() {} }) },
      Scrollbar: { vertical: id => makeEl().id(`scrollbar:${id}`) },
      theme: () => ({
        canvas: '#111111', background: '#111111', surface: '#1a1a1a', raised: '#222222', chrome: '#161616',
        border: '#333333', input: '#333333', foreground: '#eeeeee', muted: '#aaaaaa', dim: '#777777',
        hover: '#2a2a2a', accent: '#4488ff', blocked: '#ff5555', solid: '#eeeeee', solid_foreground: '#111111',
        ansi2: '#44cc66', ansi3: '#e5a93c', ansi4: '#6699ff',
      }),
      home: () => '/Users/test', appHome: () => '/app',
      exec: async (cmd, args) => {
        execCalls.push([cmd, args]);
        if (args.includes('start')) {
          liveTerms = [{ address: 'tpm_new', state: 'live', labels: { pm: 'dudu' } }];
        } else if (args.includes('reattach')) {
          const tid = args[args.indexOf('reattach') + 1];
          liveTerms = [...liveTerms, { address: `t_${tid}`, state: 'live', labels: { task: tid } }];
        }
        return { code: 0, stdout: '', stderr: '' };
      },
      execPython: async () => ({ code: 0, stdout: '{}', stderr: '' }),
      readTextFile: async () => '',
      watchFolder: () => new Promise(() => {}),
      layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
      run: () => {},
      terminals: () => liveTerms, agents: () => [], panes: () => [], spaces: () => [],
      shared: () => ({ pm: 'pm-dudu' }), setShared: () => {},
      props: () => ({}), openOverlay: () => 'ov-1', closeOverlay: () => {},
      appWindow: () => ({ platform: 'macos' }),
      ...model, ...stepsView,
    };
    const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
    const cx = {
      focus_handle: () => ({ focus() {} }),
      spawn: fn => { fn(cx); },
      timer: { after: () => {}, every: () => {} },
      notify: () => {},
      stop_propagation: () => {},
    };
    const pmOffline = {
      name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', pane: 'hc:tpm', runtime: 'hc', repo_ok: true,
      agent: 'claude', status: 'offline', lost,
    };
    const view = Object.assign(Object.create(Mod.prototype), {
      state: { pms: [pmOffline], tasks: [closedTask, closedIp, crashedIp], events: [], lang: 'zh' },
      events: [], pending: [], seq: 0, pastes: [], error: '', logError: '',
      pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
      remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
      earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '', watching: {},
      thread: '', threadTask: null, detail: false, threadError: '', threadLog: null, threadLogKept: [],
      threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null,
      threadTab: 'log', sideTab: 'threads', librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: true,
      libraryProbed: true, libraryStale: false, libraryLoading: false, libraryAgain: false, libraryError: '',
      libraryClosed: new Set(), libraryQuery: '', libraryDropBusy: '', libraryDropError: '',
      memorySlug: 'dudu', memoryData: null, memoryRead: false, memoryStale: false, memoryLoading: false, memoryAgain: false, memoryError: '',
      memoryFoldOverrides: new Map(), memoryProjectOpen: true, memoryPersonalOpen: false, memoryCandidatesOpen: false,
      memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
      activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '',
      docShownBytes: model.DOC_INITIAL_BYTES, docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
      editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
      confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
      reattaching: '', reattachError: null, startingPm: '', startPmError: null,
      bringBackOpen: false, bringingBack: false, bringBackProgress: null,
      listShown: true, wide: true, measured: true, panelWant: null, panelDrag: null, viewWidth: 1280, gripLit: false,
      seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
      bell: null, flash: '', unfolded: new Map(), newest: '', atWork: new Set(),
      scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
      libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
      keyFocus: { focus() {} }, onStage: true, typing: '', mainKey: 'pm:pm-dudu', threadKey: '', outgoing: new Map(),
      files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
      input: stubs.TextareaState.new(), threadInput: stubs.TextareaState.new(),
      libraryInput: stubs.InputState.new(), memoryInput: stubs.InputState.new(), docFindInput: stubs.InputState.new(),
      docNameInput: stubs.InputState.new(), memDescInput: stubs.InputState.new(), docEditorInput: stubs.TextareaState.new(),
      refresh: () => {},
    });
    view.resetThreadSession();

    // (a) Offline PM + lost banner + closed thread row in Chinese (`zh`) and English (`en`).
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.has('pm-start'), true, 'header shows Start PM play icon when PM is offline');
    assert.equal(nodes.has('pm-offline-bar'), true, 'offline PM bar shows above composer');
    assert.equal(nodes.has('pm-offline-start'), true, 'offline PM bar has play icon action');
    assert.equal(nodes.has('lost-banner'), true, 'lost agents banner shows');
    nodes.get('list-dudu-rep').hover(true, cx);
    nodes.clear();
    view.render(cx);
    assert.match(nodes.get('hover-card-task:dudu-rep')?.allTexts().join(' ') || '', /已关闭，可重连/);

    view.state.lang = 'en';
    nodes.clear();
    view.render(cx);
    assert.match(nodes.get('hover-card-task:dudu-rep')?.allTexts().join(' ') || '', /Closed · can reattach/);
    assert.match(nodes.get('lost-banner')?.allTexts().join(' ') || '', /PM and 2 agents did not come back after restart/);
    view.hoverKey = '';

    // (b) Open closed review thread in detail -> shows `Closed · can reattach` pill and reattach icon!
    view.thread = 'dudu-rep';
    view.detail = true;
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.has('thread-terminal'), true);
    assert.deepEqual(nodes.get('thread-closed-pill')?.texts, ['Closed · can reattach']);
    nodes.get('thread-terminal')?.hover?.(true, cx);
    nodes.clear();
    view.render(cx);
    assert.match(nodes.get('hover-tip-thread-terminal')?.allTexts().join(' ') || '', /idle after report/);
    view.hoverKey = '';

    // (c) Expand `#lost-banner` -> `#lost-card`, test `Esc` collapses `#lost-card` before closing `detail`, then execute `lost-run`!
    nodes.get('lost-open').clicks({}, cx);
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.has('lost-card'), true);
    assert.equal(nodes.has('lost-step-pm'), true);
    assert.equal(nodes.has('lost-step-thread:dudu-crashed'), true);
    assert.equal(nodes.has('lost-step-thread:dudu-b'), true);

    view.escape({ keystroke: 'escape' }, cx);
    assert.equal(view.bringBackOpen, false, 'Esc folds bring-back card first');
    assert.equal(view.detail, true, 'thread detail stays open after first Esc');

    // Re-open and run bring-back: starts PM first, then reattaches both lost threads in order!
    view.openBringBack(pmOffline, cx);
    execCalls.length = 0;
    nodes.clear();
    view.render(cx);
    nodes.get('lost-run').clicks({}, cx);
    await new Promise(r => setTimeout(r, 25));
    assert.deepEqual(execCalls.map(([, args]) => args.slice(args.indexOf('/app/mods/pm-dash/skill/scripts/pm.py') + 1)), [
      ['start', '--repo', '/r/dudu', '--kind', 'claude'],
      ['reattach', 'dudu-crashed'],
      ['reattach', 'dudu-b'],
    ]);
    assert.deepEqual(view.bringBackProgress.steps.map(s => s.state), ['done', 'done', 'done']);

    // (d) Dismissing `#lost-banner` stores the key in localStorage and hides `#lost-banner` until a new lost key arrives.
    liveTerms = [];
    view.bringBackOpen = false;
    view.bringBackProgress = null;
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.has('lost-banner'), true);
    nodes.get('lost-dismiss').clicks({}, cx);
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.has('lost-banner'), false, 'dismissed lost key hides banner');
  } finally {
    globalThis.localStorage = prevStorage;
  }
});

test('mention links, query detection, 20k repo index, and en/zh menu builder', () => {
  const {
    detectMentionQuery, formatMentionLink, parseRefLink, parseMentionSpans, splitMentionSegments,
    parseGitLsFiles, indexRepoFiles, buildMentionMenu, escapeStep,
    keepDraft, readDrafts, draftTokens, validInputTokens,
  } = model;

  // Trigger detection across boundaries, IME spaces, tokens, and email addresses.
  assert.deepEqual(detectMentionQuery('@', 1), { start: 0, end: 1, query: '' });
  assert.deepEqual(detectMentionQuery('看 @th', 5), { start: 2, end: 5, query: 'th' });
  assert.deepEqual(detectMentionQuery('参考@线程', 5), { start: 2, end: 5, query: '线程' });
  assert.deepEqual(detectMentionQuery('@xian cheng', 11), { start: 0, end: 11, query: 'xian cheng' });
  assert.equal(detectMentionQuery('@ ', 2), null);
  assert.equal(detectMentionQuery('a@b.com', 7), null);
  assert.equal(detectMentionQuery('@x', 2, [], 0), null);
  const tokStr = '[@A](thread:t-1) @f';
  const tokSpans = [{ range: { start: 0, end: 16 }, token: { id: 'thread:t-1', text: '[@A](thread:t-1)', label: '@A' } }];
  assert.equal(detectMentionQuery(tokStr, 5, tokSpans), null);
  assert.deepEqual(detectMentionQuery(tokStr, tokStr.length, tokSpans), { start: 17, end: 19, query: 'f' });

  // Markdown pointer encoding/decoding and security filtering.
  const spaceLink = formatMentionLink({ kind: 'file', target: 'docs/my file (v2).md', label: 'my [file].md' });
  assert.equal(spaceLink, '[@my (file).md](file:docs/my%20file%20%28v2%29.md)');
  const spans = parseMentionSpans(`Compare ${spaceLink} with [@Spec](library:docs/spec.md) and [@Mem](library:project/memory/r1.md)`);
  assert.deepEqual(spans.map(s => [s.kind, s.target, s.root, s.path]), [
    ['file', 'docs/my file (v2).md', undefined, 'docs/my file (v2).md'],
    ['library', 'docs/spec.md', 'docs', 'spec.md'],
    ['library', 'memory/r1.md', 'memory', 'r1.md'],
  ]);
  assert.equal(parseRefLink('library:repo/secret.txt'), null);
  assert.equal(parseRefLink('file:../secret'), null);
  assert.equal(parseRefLink('file:.git/HEAD'), null);
  const segs = splitMentionSegments('Check [@A](thread:t1) & [@B](file:a.js)\nLine 2');
  assert.equal(segs.hasMentions, true);
  assert.equal(segs.lines[0].segments.filter(s => s.type === 'mention').length, 2);
  assert.equal(segs.lines[1].hasMentions, false);

  // `-z` git ls-files parsing and 20,000-file search speed.
  assert.deepEqual(parseGitLsFiles('./README.md\0.git/HEAD\0docs/中文 note.md\0README.md\0'), ['README.md', 'docs/中文 note.md']);
  const bigPaths = Array.from({ length: 20_000 }, (_, i) => `src/mod${Math.floor(i / 200)}/file_${i}.js`);
  bigPaths[12345] = 'mods/pm-project/mention-engine.js';
  const indexed = indexRepoFiles(bigPaths);
  assert.equal(indexed.length, 20_000);

  const threads = {
    open: [
      { task: 't-run', title: 'Streaming parser', group: 'working', working: true, tone: 'running', branch: 'dev/stream', status: 'in_progress' },
      { task: 't-rev', title: 'Mention UI', group: 'review', tone: 'review', branch: 'dev/at', status: 'review' },
      { task: 't-paused', title: 'Paused work', group: 'paused', tone: 'quiet', status: 'paused' },
    ],
    sessions: [
      { address: 'hc:tw1', label: 'helper', status: 'working', program: { name: 'codex' } },
    ],
    finished: [
      { task: 't-done', title: 'Done work', status: 'merged' },
    ],
  };
  const libraryFiles = [
    { root: 'docs', path: 'spec.md', title: 'Design Spec', kind: 'md' },
    { root: 'research', path: 'at-mention/README.md', kind: 'md', title: 'At Mention Study', summary: 'Cursor research' },
    { root: 'instructions', path: 'CLAUDE.md', kind: 'md' },
    { root: 'docs', path: 'decisions.md', archive: true, hidden: true },
  ];

  // English Level 1 menu + active threads.
  const enRoot = buildMentionMenu({ lang: 'en', category: 'all', query: '', threads, tasks: [{ id: 't-run', agent: 'codex' }], libraryFiles, repoFiles: indexed, excludeThread: 't-rev' });
  assert.equal(enRoot.mode, 'root');
  assert.deepEqual(enRoot.items.slice(0, 3).map(i => [i.category, i.label, i.count]), [
    ['threads', 'Threads', 4],
    ['library', 'Library', 3],
    ['files', 'Files', 20_000],
  ]);
  assert.equal(enRoot.dividerBefore, 3);
  assert.deepEqual(enRoot.items.slice(3).map(i => i.key), ['thread:t-run', 'session:hc:tw1']);

  // Chinese Level 1 & Level 2 & empty states.
  const zhRoot = buildMentionMenu({ lang: 'zh', category: 'all', query: '', threads, libraryFiles, repoFiles: indexed });
  assert.deepEqual(zhRoot.items.slice(0, 3).map(i => i.label), ['线程', 'Library', '文件']);
  const zhFilesEmpty = buildMentionMenu({ lang: 'zh', category: 'files', query: '', threads: { open: [], sessions: [], finished: [] }, libraryFiles: [], repoFiles: [] });
  assert.equal(zhFilesEmpty.title, '文件');
  assert.equal(zhFilesEmpty.emptyText, '没有找到仓库文件');
  const enLibEmpty = buildMentionMenu({ lang: 'en', category: 'library', query: '', threads: { open: [], sessions: [], finished: [] }, libraryFiles: [], repoFiles: [] });
  assert.equal(enLibEmpty.emptyText, 'No Library documents');

  // 20k flat global search performance & ranking.
  const t0 = performance.now();
  const flat = buildMentionMenu({ lang: 'en', category: 'all', query: 'mention-engine', threads, libraryFiles, repoFiles: indexed });
  const elapsed = performance.now() - t0;
  assert.equal(flat.mode, 'search');
  assert.equal(flat.items[0]?.target, 'mods/pm-project/mention-engine.js');
  assert.equal(elapsed < 500, true, `20k search took ${elapsed}ms`);

  // Escape step priority.
  assert.equal(escapeStep({ mentionSub: true, mention: true, answering: true }), 'mentionSub');
  assert.equal(escapeStep({ mention: true, answering: true }), 'mention');

  // Draft token round-trip and validation.
  const goodSpan = { range: { start: 3, end: 19 }, token: { id: 'thread:t-run', text: '[@Run](thread:t-run)', label: '@Run' } };
  const body = `hi [@Run](thread:t-run) ok`;
  const fixedSpan = { range: { start: 3, end: 23 }, token: { id: 'thread:t-run', text: '[@Run](thread:t-run)', label: '@Run' } };
  assert.equal(validInputTokens(body, [goodSpan, fixedSpan]).length, 1);
  const kept = keepDraft({}, 'pm:dudu', body, 1000, [], [fixedSpan]);
  const reloaded = readDrafts(JSON.stringify(kept));
  assert.deepEqual(draftTokens(reloaded, 'pm:dudu'), [fixedSpan]);
});

test('at-mention key bindings override multi-line Textarea Input context via GPUI descendant selector', () => {
  const { MENTION_KEY_BINDINGS } = model;
  for (const keystroke of ['up', 'down', 'tab', 'enter', 'escape']) {
    const desc = MENTION_KEY_BINDINGS.find(b => b.keystroke === keystroke && b.context === 'PmMentionOpen > Input');
    assert.ok(desc, `missing descendant binding for ${keystroke}`);
    const anc = MENTION_KEY_BINDINGS.find(b => b.keystroke === keystroke && b.context === 'PmMentionOpen');
    assert.ok(anc, `missing ancestor fallback binding for ${keystroke}`);
    assert.equal(desc.action, anc.action);
  }

  // Mirror GPUI's KeyBindingContextPredicate::depth_of & Keymap::bindings_for_input precedence:
  // deepest matched context depth wins; ties resolved by latest registered binding index.
  const evalPred = (pred, slice) => {
    const cur = slice[slice.length - 1];
    if (!cur) return false;
    if (pred.includes('>')) {
      const [parent, child] = pred.split('>').map(s => s.trim());
      for (let i = 0; i < slice.length - 1; i++) {
        if (slice[i].includes(parent) && slice[slice.length - 1].includes(child)) return true;
      }
      return false;
    }
    return cur.includes(pred.trim());
  };
  const depthOf = (pred, stack) => {
    for (let d = stack.length; d >= 1; d--) {
      if (evalPred(pred, stack.slice(0, d))) return d;
    }
    return null;
  };
  const resolve = (bindings, keystroke, stack) => {
    const hits = [];
    bindings.forEach((b, ix) => {
      if (b.keystroke !== keystroke) return;
      const depth = b.context ? depthOf(b.context, stack) : stack.length;
      if (depth !== null) hits.push({ depth, ix, action: b.action });
    });
    hits.sort((a, b) => b.depth - a.depth || b.ix - a.ix);
    return hits[0]?.action || null;
  };

  // gpui_base registers Input bindings at startup before pm-project init().
  const inputDefaults = [
    { keystroke: 'up', action: 'input::MoveUp', context: 'Input' },
    { keystroke: 'down', action: 'input::MoveDown', context: 'Input' },
    { keystroke: 'tab', action: 'input::IndentInline', context: 'Input' },
    { keystroke: 'enter', action: 'input::Enter', context: 'Input' },
    { keystroke: 'escape', action: 'input::Escape', context: 'Input' },
  ];
  const openStack = [['Root'], ['PmMentionOpen'], ['Input']];
  const closedStack = [['Root'], ['Input']];

  // Regression proof: ancestor-only `PmMentionOpen` loses to leaf `Input` (depth 2 < depth 3).
  const legacyBindings = [...inputDefaults, ...MENTION_KEY_BINDINGS.filter(b => b.context === 'PmMentionOpen')];
  assert.equal(resolve(legacyBindings, 'down', openStack), 'input::MoveDown');
  assert.equal(resolve(legacyBindings, 'up', openStack), 'input::MoveUp');

  // Fix: `PmMentionOpen > Input` matches at leaf depth 3 and overrides gpui_base's Input bindings while open.
  const fixedBindings = [...inputDefaults, ...MENTION_KEY_BINDINGS];
  assert.equal(resolve(fixedBindings, 'up', openStack), 'pm-mention-up');
  assert.equal(resolve(fixedBindings, 'down', openStack), 'pm-mention-down');
  assert.equal(resolve(fixedBindings, 'tab', openStack), 'pm-mention-accept');
  assert.equal(resolve(fixedBindings, 'enter', openStack), 'pm-mention-accept');
  assert.equal(resolve(fixedBindings, 'escape', openStack), 'pm-mention-escape');

  // When @ popup is closed, normal multi-line Textarea navigation resumes.
  assert.equal(resolve(fixedBindings, 'up', closedStack), 'input::MoveUp');
  assert.equal(resolve(fixedBindings, 'down', closedStack), 'input::MoveDown');
  assert.equal(resolve(fixedBindings, 'tab', closedStack), 'input::IndentInline');
});

test('PmProject @ mention popup, inline tokens, navigation, routing, and local/remote repo files (en & zh)', async () => {
  const fs = await import('node:fs');
  const raw = fs.readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const source = `${raw
    .replace(/^\s*import\s+[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/export\s+default\s+class\s+/, 'class ')}\nreturn PmProject;`;

  const nodes = new Map();
  const popups = new Map();
  const tokenProps = new Map();
  const actionsByCtx = new Map();
  const allTexts = rec => [...rec.texts, ...rec.kids.flatMap(allTexts)];
  const makeEl = () => {
    const rec = { id: '', texts: [], kids: [], tips: [], clicks: null, mouseDowns: [], keyDowns: [], actions: new Map(), ctx: '', content: null, tokenFn: null, tokenClickFn: null };
    const proxy = new Proxy(() => proxy, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        if (key === '__allTexts') return () => allTexts(rec);
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') { if (typeof args[0] === 'string') rec.texts.push(args[0]); else if (args[0]?.__rec) rec.kids.push(args[0].__rec); }
          else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) { if (typeof k === 'string') rec.texts.push(k); else if (k?.__rec) rec.kids.push(k.__rec); }
          }
          else if (key === 'content' && args[0]?.__rec) rec.kids.push(args[0].__rec);
          else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'on_mouse_down') rec.mouseDowns.push(args[1] || args[0]);
          else if (key === 'on_key_down') rec.keyDowns.push(args[0]);
          else if (key === 'key_context') { rec.ctx = args[0]; actionsByCtx.set(rec.ctx, rec.actions); }
          else if (key === 'on_action') { rec.actions.set(args[0], args[1]); }
          else if (key === 'token') { rec.tokenFn = args[0]; }
          else if (key === 'on_token_click') { rec.tokenClickFn = args[0]; }
          else if (key === 'tooltip') rec.tips.push(args[0]);
          else if (key === 'content') rec.content = args[0];
          else if (key === 'when') { if (args[0]) args[1](proxy); }
          return proxy;
        };
      },
      apply: () => proxy,
    });
    rec.allTexts = () => allTexts(rec);
    return proxy;
  };

  const makeBox = () => {
    let text = '';
    let tokens = [];
    let sel = { start: 0, end: 0 };
    const handlers = {};
    const shiftAfter = (pos, delta) => {
      tokens = tokens
        .filter(s => !(s.range.start < pos && pos < s.range.end))
        .map(s => (s.range.start >= pos ? { ...s, range: { start: s.range.start + delta, end: s.range.end + delta } } : s));
    };
    return {
      __fire(ev, payload, cx) { for (const fn of handlers[ev] || []) fn(payload, cx); },
      __type(str, cx) {
        const prevEnd = sel.end;
        const nextText = text.slice(0, sel.start) + str + text.slice(sel.end);
        shiftAfter(sel.start, str.length - (prevEnd - sel.start));
        text = nextText;
        sel = { start: sel.start + str.length, end: sel.start + str.length };
        this.__fire('change', {}, cx);
      },
      on(ev, fn) { (handlers[ev] ||= []).push(fn); return true; },
      value: () => text,
      content: () => ({ text, tokens: tokens.map(s => ({ range: { ...s.range }, token: { ...s.token } })) }),
      tokens: () => tokens.map(s => ({ range: { ...s.range }, token: { ...s.token } })),
      selected_range: () => ({ ...sel }),
      set_selected_range: r => { sel = { start: r.start, end: r.end }; },
      replace(rep) {
        const r = String(rep ?? '');
        const delta = r.length - (sel.end - sel.start);
        shiftAfter(sel.start, delta);
        text = text.slice(0, sel.start) + r + text.slice(sel.end);
        sel = { start: sel.start + r.length, end: sel.start + r.length };
      },
      replace_range_with_token(range, tok) {
        const lenDelta = tok.text.length - (range.end - range.start);
        tokens = tokens.filter(s => s.range.end <= range.start || s.range.start >= range.end)
          .map(s => (s.range.start >= range.end ? { ...s, range: { start: s.range.start + lenDelta, end: s.range.end + lenDelta } } : s));
        text = text.slice(0, range.start) + tok.text + text.slice(range.end);
        const span = { range: { start: range.start, end: range.start + tok.text.length }, token: { ...tok } };
        tokens.push(span);
        tokens.sort((a, b) => a.range.start - b.range.start);
        sel = { start: span.range.end, end: span.range.end };
      },
      set_value(next) {
        if (next && typeof next === 'object') {
          for (const s of next.tokens || []) {
            assert.equal(next.text.slice(s.range.start, s.range.end), s.token.text);
          }
          text = next.text;
          tokens = (next.tokens || []).map(s => ({ range: { ...s.range }, token: { ...s.token } }));
          sel = { start: text.length, end: text.length };
        } else {
          text = String(next ?? '');
          tokens = [];
          sel = { start: text.length, end: text.length };
        }
      },
      set_auto_grow() {},
      set_soft_wrap() {},
      focus() {},
    };
  };

  let nextBoxKind = 'main';
  const sentCmds = [];
  const execLog = [];
  const ranActions = [];
  const clipboard = [];
  let remoteOldPm = false;
  const repoFilesData = {
    local: 'README.md\0src/app.js\0mods/pm-project/main.js\0',
    remotePm: JSON.stringify({ project: 'dudu', files: ['remote/only.ts'], truncated: false }),
    remoteGit: 'fallback/legacy.rs\0',
  };
  const stubs = {
    View: class {}, ...model,
    div: makeEl, h_flex: makeEl, v_flex: makeEl, svg: makeEl, image: makeEl,
    TextView: { markdown: (_id, md) => makeEl().child(String(md || '')), html: (_id, html) => makeEl().child(String(html || '')) },
    TextareaState: { new: () => makeBox() },
    Textarea: {
      new: st => {
        const el = makeEl();
        tokenProps.set(st, el.__rec);
        return el;
      },
    },
    InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, focus() {} }) },
    Input: { new: () => makeEl() },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) },
    Scrollbar: { vertical: id => makeEl().id(`scrollbar:${id}`) },
    Popup: {
      new: (id, trigger) => {
        const el = makeEl().id(id).child(trigger);
        popups.set(id, el.__rec);
        return el;
      },
    },
    theme: () => ({
      canvas: '#111111', surface: '#181818', raised: '#222222', chrome: '#161616', hover: '#2a2a2a',
      border: '#333333', input: '#3a3a3a', foreground: '#eeeeee', background: '#111111',
      muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', accent_foreground: '#ffffff',
      blocked: '#ff5f56', ansi2: '#27c93f', ansi3: '#f5a623', solid: '#eeeeee', solid_foreground: '#111111',
    }),
    home: () => '/Users/test', appHome: () => '/app',
    exec: async (cmd, args) => {
      execLog.push([cmd, args]);
      if (cmd === 'git' && args.includes('ls-files')) {
        if (args.includes('--error-unmatch')) {
          const rel = args[args.length - 1];
          if (rel === 'fallback/legacy.rs') return { code: 0, stdout: 'fallback/legacy.rs\0', stderr: '' };
          return { code: 1, stdout: '', stderr: `error: pathspec '${rel}' did not match any file(s) known to git` };
        }
        const isRemote = args.includes('box') || (args.includes('ls-files') && args.includes('/remote/dudu'));
        return { code: 0, stdout: isRemote ? repoFilesData.remoteGit : repoFilesData.local, stderr: '' };
      }
      if (cmd === 'ssh') {
        const joined = args.join(' ');
        if (joined.includes('--error-unmatch')) {
          if (joined.includes('fallback/legacy.rs')) return { code: 0, stdout: 'fallback/legacy.rs\0', stderr: '' };
          return { code: 1, stdout: '', stderr: 'error: pathspec did not match any file(s) known to git' };
        }
        if (joined.includes('ls-files')) return { code: 0, stdout: repoFilesData.remoteGit, stderr: '' };
      }
      if (args?.includes('send')) {
        sentCmds.push(args);
        return { code: 0, stdout: '', stderr: '' };
      }
      if (args?.includes('library')) {
        return { code: 0, stdout: JSON.stringify({ files: [{ root: 'docs', path: 'spec.md', title: 'Architecture Spec', kind: 'md', size: 30 }] }), stderr: '' };
      }
      if (args?.includes('files')) {
        if (remoteOldPm) return { code: 2, stdout: '', stderr: "pm.py: error: argument project_cmd: invalid choice: 'files'" };
        return { code: 0, stdout: repoFilesData.remotePm, stderr: '' };
      }
      if (args?.includes('file')) {
        if (args.includes('repo')) {
          if (remoteOldPm) return { code: 1, stdout: '', stderr: "invalid document root: 'repo'" };
          const p = args[args.length - 1];
          return { code: 0, stdout: JSON.stringify({ text: `# ${p}\n\nRepo content`, size: 20, version: '' }), stderr: '' };
        }
        return { code: 0, stdout: JSON.stringify({ text: '# Architecture Spec\n\nDetails', size: 28, version: 'v1' }), stderr: '' };
      }
      if (args?.includes('events')) {
        return { code: 0, stdout: JSON.stringify({ events: [], from: 0, offset: 0, earlier: false }), stderr: '' };
      }
      return { code: 0, stdout: JSON.stringify({ pms: [], tasks: [] }), stderr: '' };
    },
    execPython: async (_exec, argv, opts) => stubs.exec('python3', argv, opts),
    readTextFile: async path => (path.includes('legacy.rs') ? '// legacy\n' : path.includes('.env') || path.includes('settings.local.json') ? 'SECRET=1\n' : ''),
    writeTextFile: async () => {},
    watchFolder: () => new Promise(() => {}),
    layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run: (act, arg) => ranActions.push([act, arg]),
    terminals: () => [
      { address: 'tpm', state: 'live', labels: { pm: 'dudu' } },
      { address: 'tw1', state: 'live', labels: { task: 't-a' } },
    ],
    agents: () => [], panes: () => [{ terminal: 'tpm' }, { terminal: 'tw1' }], spaces: () => [],
    shared: () => ({ pm: 'pm-dudu' }), setShared: () => {},
    appWindow: () => ({ platform: 'macos' }),
    ...stepsView,
  };

  const prevStorage = globalThis.localStorage;
  const storeMap = new Map();
  globalThis.localStorage = { getItem: k => storeMap.get(k) ?? null, setItem: (k, v) => storeMap.set(k, String(v)), removeItem: k => storeMap.delete(k) };
  try {
    const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
    const boundKeys = [];
    const initView = Object.assign(Object.create(Mod.prototype), { keptPanelWidth: () => null, refresh: () => {} });
    initView.init({}, {
      bind_keys: b => boundKeys.push(...b),
      focus_handle: () => ({ focus() {} }),
      spawn: () => {},
      timer: { after: () => {}, every: () => {} },
      notify() {},
    });
    assert.deepEqual(boundKeys, [...model.MENTION_KEY_BINDINGS, ...model.SEARCH_KEY_BINDINGS],
      'PmProject.init registers PmMentionOpen > Input and PmSearchOpen > Input bindings');
    const scrollItems = [];
    const cx = {
      focus_handle: () => ({ focus() {} }),
      spawn: fn => fn(cx),
      timer: { after: () => {}, every: () => {} },
      notify() {},
      stop_propagation() {},
      write_to_clipboard: s => clipboard.push(s),
    };
    const pmLocal = { name: 'pm-dudu', project: 'dudu', repo: '/work/dudu', pane: 'hc:tpm', runtime: 'hc', status: 'live' };
    const view = Object.assign(Object.create(Mod.prototype), {
      state: { pms: [pmLocal], tasks: [{ id: 't-a', pm: 'pm-dudu', title: 'Alpha Thread', status: 'in_progress', branch: 'dev/a', pane: 'hc:tw1' }], events: [], lang: 'en' },
      events: [], pending: [], seq: 0, pastes: [], error: '', logError: '',
      pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
      remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
      earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '/here', watching: {},
      thread: '', threadTask: null, detail: false, threadError: '', threadLog: null, threadLogKept: [],
      threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null, threadTab: 'log', sideTab: 'threads',
      librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: false, libraryProbed: true, libraryStale: false,
      libraryLoading: false, libraryAgain: false, libraryError: '', libraryClosed: new Set(), libraryQuery: '',
      libraryDropBusy: '', libraryDropError: '', memorySlug: '', memoryData: null, memoryRead: false, memoryStale: false,
      memoryLoading: false, memoryAgain: false, memoryError: '', memoryFoldOverrides: new Map(), memoryProjectOpen: true,
      memoryPersonalOpen: false, memoryCandidatesOpen: false, memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
      activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '', docShownBytes: model.DOC_INITIAL_BYTES,
      docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
      editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
      confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
      reattaching: '', reattachError: null, startingPm: '', startPmError: null,
      bringBackOpen: false, bringingBack: false, bringBackProgress: null,
      listShown: true, wide: true, measured: true, viewWidth: 1280, panelWant: null, panelDrag: null, gripLit: false,
      seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
      bell: null, flash: '', unfolded: new Map(), newest: '', atWork: new Set(),
      scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
      libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
      mentionScroll: { scroll_to_item: i => scrollItems.push(i) }, mention: null, mentionDismissed: null, mentionConsumedKey: false, mentionPicking: false,
      repoFilesSlug: '', repoFilesRepo: '', repoFiles: [], repoFilesRead: false, repoFilesLoading: false, repoFilesAgain: false,
      repoFilesError: '', repoFilesTruncated: false, repoFilesAt: 0, pathCopiedAt: 0,
      keyFocus: { focus() { view.typing = ''; } }, onStage: true, typing: 'main', mainKey: 'pm:pm-dudu', threadKey: '',
      outgoing: new Map(), files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
      input: makeBox(), threadInput: makeBox(), libraryInput: stubs.InputState.new(), memoryInput: stubs.InputState.new(),
      docFindInput: stubs.InputState.new(), docNameInput: stubs.InputState.new(), memDescInput: stubs.InputState.new(),
      docEditorInput: stubs.TextareaState.new(), refresh: () => {},
    });
    view.resetThreadSession();
    const wireBox = (box, which) => {
      box.on('change', (_e, cx) => {
        const c = view.boxContent(box);
        if (which === 'thread') { view.threadDraft = c.text; view.typed(view.threadKey, c.text, c.tokens); }
        else { view.draft = c.text; view.typed(view.mainKey, c.text, c.tokens); }
        view.syncMention(which, cx);
      });
      box.on('submit', (e, cx) => {
        if (e?.shift || view.mentionConsumedKey) return;
        if (view.mentionOpenFor(which)) { view.consumeMentionKey(cx); view.acceptMention(which, cx); return; }
        if (which === 'thread') view.sendThread(cx); else view.sendMain(cx);
      });
    };
    wireBox(view.input, 'main');
    wireBox(view.threadInput, 'thread');

    // (1) Typing '@' triggers Level-1 popup; verify English & Chinese labels + local git ls-files load.
    view.input.__type('@', cx);
    await new Promise(r => setTimeout(r, 15));
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.has('say-mention-card'), true);
    assert.deepEqual(nodes.get('say-mention-row-0')?.allTexts(), ['Threads', '1']);
    assert.deepEqual(nodes.get('say-mention-row-1')?.allTexts(), ['Library', '1']);
    assert.deepEqual(nodes.get('say-mention-row-2')?.allTexts(), ['Files', '3']);

    view.state.lang = 'zh';
    nodes.clear();
    view.render(cx);
    assert.deepEqual(nodes.get('say-mention-row-0')?.allTexts(), ['线程', '1']);
    assert.deepEqual(nodes.get('say-mention-row-2')?.allTexts(), ['文件', '3']);

    // (2) Down & Up wrap across candidates while popup is open, scrolling list and keeping PmMentionOpen context; Esc pops Level 2 -> Level 1 -> closed.
    assert.equal(nodes.get('say')?.ctx, 'PmMentionOpen');
    assert.equal(view.mention?.index, 0);
    nodes.get('say')?.actions.get('pm-mention-up')({}, cx);
    assert.equal(view.mention?.index, 3, 'Up from index 0 wraps to last item');
    assert.ok(scrollItems.length > 0, 'arrow navigation scrolls mention list');
    nodes.get('say')?.actions.get('pm-mention-down')({}, cx);
    assert.equal(view.mention?.index, 0, 'Down wraps back to 0');
    nodes.get('say')?.actions.get('pm-mention-down')({}, cx);
    nodes.get('say')?.actions.get('pm-mention-down')({}, cx);
    assert.equal(view.mention?.index, 2);
    await Promise.resolve();
    nodes.get('say')?.actions.get('pm-mention-accept')({}, cx);
    await Promise.resolve();
    assert.equal(view.mention?.category, 'files');
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.has('say-mention-header'), true);
    assert.deepEqual(nodes.get('say-mention-header')?.allTexts(), ['文件']);

    view.escape({ keystroke: 'escape' }, cx);
    assert.equal(view.mention?.category, 'all', 'first Esc pops Level 2 back to Level 1');
    await Promise.resolve();
    view.escape({ keystroke: 'escape' }, cx);
    assert.equal(view.mention, null, 'second Esc closes popup keeping focus and draft');
    assert.equal(view.typing, 'main');
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.get('say')?.ctx, '', 'closing popup drops PmMentionOpen context so Textarea arrows resume');

    // (3) Type space + '@README' -> flat search; Enter inserts inline token; chip click opens read-only repo preview & copy-path works.
    view.input.__type(' @README', cx);
    const flatMenu = view.mentionMenuFor('main');
    assert.equal(flatMenu.mode, 'search');
    assert.equal(flatMenu.items[0]?.target, 'README.md');
    view.input.__fire('submit', {}, cx);
    await Promise.resolve();
    const contentAfterPick = view.input.content();
    assert.equal(contentAfterPick.tokens.length, 1);
    assert.equal(contentAfterPick.text, '@ [@README.md](file:README.md) ');
    // Chip renderer produces '@README.md' chip and click opens repo file preview.
    nodes.clear();
    view.render(cx);
    const chipRec = tokenProps.get(view.input).tokenFn({ token: contentAfterPick.tokens[0].token, selected: false }, cx).__rec;
    assert.deepEqual(chipRec.allTexts(), ['@README.md']);
    tokenProps.get(view.input).tokenClickFn({ token: contentAfterPick.tokens[0].token }, cx);
    await new Promise(r => setTimeout(r, 15));
    assert.deepEqual(view.activeDoc, { tab: 'library', root: 'repo', path: 'README.md' });
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.has('doc-copy-path'), true);
    nodes.get('doc-copy-path').clicks({}, cx);
    assert.deepEqual(clipboard, ['README.md']);
    nodes.clear();
    view.render(cx);
    view.hoverKey = 'tip:doc-copy-path';
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.get('hover-tip-doc-copy-path')?.allTexts().join(' '), '已复制路径');
    view.hoverKey = '';

    // (4) @mention thread in main composer STILL routes to PM terminal (not worker) with pointer intact.
    view.input.set_value('');
    view.draft = '';
    view.input.__type('Ask @Alpha', cx);
    nodes.clear();
    view.render(cx);
    nodes.get('say')?.actions.get('pm-mention-accept')({}, cx);
    await Promise.resolve();
    assert.equal(view.input.value(), 'Ask [@Alpha Thread](thread:t-a) ');
    view.input.__fire('submit', {}, cx);
    await new Promise(r => setTimeout(r, 10));
    assert.equal(sentCmds.length, 1);
    assert.equal(sentCmds[0].includes('tpm'), true, 'main composer routes @thread mention to PM');
    assert.equal(sentCmds[0].includes('Ask [@Alpha Thread](thread:t-a)'), true);
    assert.equal(view.draft, '');
    assert.equal(view.input.tokens().length, 0);

    // Bubble renders clickable mention chip for the sent pending message -> opens thread detail.
    nodes.clear();
    view.render(cx);
    const sentChip = [...nodes.entries()].find(([k]) => k.startsWith('bubble-') && k.includes('-m-0-'));
    assert.ok(sentChip, 'sent user bubble renders inline clickable chip');
    sentChip[1].clicks({}, cx);
    assert.equal(view.detail, true);
    assert.equal(view.thread, 't-a');

    // (5) `say-thread` moves mention highlight on Down/Up, inserts Library mention and routes to worker terminal; `followLink` handles all schemes.
    view.threadKey = 'thread:t-a';
    view.typing = 'thread';
    view.threadInput.__type('@', cx);
    nodes.clear();
    view.render(cx);
    assert.equal(nodes.get('say-thread')?.ctx, 'PmMentionOpen');
    assert.equal(view.mention?.index, 0);
    nodes.get('say-thread')?.actions.get('pm-mention-down')({}, cx);
    assert.equal(view.mention?.index, 1, 'thread composer arrow action moves selection down');
    nodes.get('say-thread')?.actions.get('pm-mention-up')({}, cx);
    assert.equal(view.mention?.index, 0, 'thread composer arrow action moves selection up');
    view.threadInput.set_value('');
    view.threadInput.__type('See @spec', cx);
    view.acceptMention('thread', cx);
    await Promise.resolve();
    view.sendThread(cx);
    await new Promise(r => setTimeout(r, 10));
    assert.equal(sentCmds[1].includes('tw1'), true);
    assert.equal(sentCmds[1].includes('See [@spec.md](library:docs/spec.md)'), true);

    view.followLink('library:docs/spec.md', cx);
    await new Promise(r => setTimeout(r, 10));
    assert.deepEqual(view.activeDoc, { tab: 'library', root: 'docs', path: 'spec.md' });
    view.followLink('session:tw1', cx);
    assert.equal(ranActions.some(([a, arg]) => a === 'pane.focus' && arg.terminal === 'tw1'), true);

    // (6) Remote project uses `pm.py project files` and falls back to remote `git ls-files -z` when remote pm.py is older.
    view.machine = 'box';
    view.stateFor = 'box';
    view.repoFilesRead = false;
    view.readRepoFiles(cx);
    await new Promise(r => setTimeout(r, 15));
    assert.deepEqual(view.repoFiles.map(f => f.path), ['remote/only.ts']);

    remoteOldPm = true;
    view.state.pms = [{ ...pmLocal, machine: 'box', repo: '/remote/dudu' }];
    view.repoFilesRead = false;
    view.readRepoFiles(cx);
    await new Promise(r => setTimeout(r, 15));
    assert.deepEqual(view.repoFiles.map(f => f.path), ['fallback/legacy.rs']);
    assert.equal(execLog.some(([cmd, args]) => (cmd === 'git' || cmd === 'ssh') && args.join(' ').includes('ls-files') && args.join(' ').includes('--others')), false,
      'repo file listing must query git-tracked files only (never --others)');

    // Old-remote repo preview fallback also checks `git ls-files --error-unmatch` before reading!
    for (const secretPath of ['.env', '.claude/settings.local.json']) {
      view.openRepoFile(secretPath, cx);
      await new Promise(r => setTimeout(r, 15));
      assert.equal(view.docCache.has(`repo/${secretPath}`), false, `old remote refuses gitignored/untracked ${secretPath}`);
      assert.ok(view.docError, `old remote sets error for untracked ${secretPath}`);
    }
    view.openRepoFile('fallback/legacy.rs', cx);
    await new Promise(r => setTimeout(r, 15));
    assert.equal(view.docCache.get('repo/fallback/legacy.rs')?.text, '// legacy\n');
  } finally {
    globalThis.localStorage = prevStorage;
  }
});

test('Threads 3: review inside Working, intra-group ordering, and taskTree container epics / cycle / orphan handling', () => {
  const { OPEN_GROUPS, taskTree } = model;
  assert.deepEqual(OPEN_GROUPS, ['waiting', 'working', 'offline', 'paused', 'parked']);
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', pane: 'hc:tpm' };
  const tasks = [
    // Container epic with stale rotated-PM pane & offline=true (must NOT become offline or show worker!)
    { id: 'epic-lib', pm: 'pm-dudu', title: '专题：Context / Library', status: 'in_progress', pane: 'hc:old_pm', offline: true, updated: '2026-11-21 10:00' },
    { id: 'lib-design', pm: 'pm-dudu', title: '设计调研', status: 'review', parent: 'epic-lib', updated: '2026-11-21 14:00',
      plan: ['[x] 调研', '[>] 审查', '[ ] 归档'] },
    { id: 'lib-docs', pm: 'pm-dudu', title: '公开文档', status: 'in_progress', parent: 'epic-lib', pane: 'hc:tw1', updated: '2026-11-21 12:00',
      engine: { kind: 'agy', model: 'carbon' } },
    { id: 'lib-ui', pm: 'pm-dudu', title: 'Library UI', status: 'proposed', parent: 'epic-lib', updated: '2026-11-21 09:00' },
    { id: 'lib-a', pm: 'pm-dudu', title: '子任务 A', status: 'merged', parent: 'epic-lib', cleanup: true, updated: '2026-11-21 08:00' },
    { id: 'lib-drop', pm: 'pm-dudu', title: '废弃子任务', status: 'abandoned', parent: 'epic-lib', updated: '2026-11-21 08:30' },
    // Worker-parent (has own branch & engine -> container: false)
    { id: 'feat-main', pm: 'pm-dudu', title: '主功能分支', status: 'in_progress', branch: 'dev/feat', pane: 'hc:tw2',
      engine: { kind: 'claude', model: 'opus' }, updated: '2026-11-21 12:30' },
    { id: 'feat-sub', pm: 'pm-dudu', title: '拆分小步', status: 'blocked', parent: 'feat-main', updated: '2026-11-21 12:40' },
    // Standalone threads testing ordering inside Working: postGate -> review -> answered -> in_progress
    { id: 't-ip', pm: 'pm-dudu', title: '普通进行中', status: 'in_progress', pane: 'hc:tw3', updated: '2026-11-21 15:00' },
    { id: 't-ans', pm: 'pm-dudu', title: '已答待推进', status: 'blocked', answered: true, updated: '2026-11-21 14:00' },
    { id: 't-rev', pm: 'pm-dudu', title: '审查中线程', status: 'review', updated: '2026-11-21 13:00' },
    { id: 't-post', pm: 'pm-dudu', title: '接口 E 装机', status: 'in_progress', offline: true, updated: '2026-11-21 07:00',
      plan: ['[x] 实现接口', '[x] 独立审查', '[x] 合进 main', '[>] 装到 MBP'] },
    // Container epic whose child is unanswered blocked -> bubbles up to Waiting on you
    { id: 'epic-wait', pm: 'pm-dudu', title: '专题：等拍板', status: 'in_progress', updated: '2026-11-21 06:00' },
    { id: 'wait-child', pm: 'pm-dudu', title: '等定案子任务', status: 'blocked', parent: 'epic-wait', updated: '2026-11-21 16:00' },
    // Orphan child whose parent is closed (promoted to root)
    { id: 'closed-parent', pm: 'pm-dudu', title: '已完父任务', status: 'done', updated: '2026-11-21 05:00' },
    { id: 'orphan-open', pm: 'pm-dudu', title: '孤儿进行中', status: 'in_progress', parent: 'closed-parent', updated: '2026-11-21 04:00' },
    // Cycle protection
    { id: 'cyc-a', pm: 'pm-dudu', title: '环 A', status: 'in_progress', parent: 'cyc-b', updated: '2026-11-21 03:00' },
    { id: 'cyc-b', pm: 'pm-dudu', title: '环 B', status: 'in_progress', parent: 'cyc-a', updated: '2026-11-21 03:01' },
  ];
  const retiredParts = [
    { id: 'lib-a', pm: 'pm-dudu', title: '子任务 A', status: 'merged', parent: 'epic-lib', retired: true, updated: '2026-11-21 08:00' },
    { id: 'lib-b', pm: 'pm-dudu', title: '已回收子任务 B', status: 'done', parent: 'epic-lib', retired: true, updated: '2026-11-21 07:30' },
  ];
  const terms = [
    { address: 'tpm', state: 'live', cwd: '/r/dudu', labels: { pm: 'dudu' } },
    { address: 'tw1', state: 'live', cwd: '/r/dudu', labels: { task: 'lib-docs' }, status: 'working' },
    { address: 'tw2', state: 'live', cwd: '/r/dudu', labels: { task: 'feat-main' }, status: 'working' },
    { address: 'tw3', state: 'live', cwd: '/r/dudu', labels: { task: 't-ip' }, status: 'working' },
    { address: 'th1', state: 'live', cwd: '/r/dudu', labels: { helper: 'scan', 'helper.of': 'lib-docs' }, status: 'working' },
  ];
  const live = [
    { address: 'tw1', status: 'working', tab: 't1', seq: 1 },
    { address: 'th1', status: 'working', tab: 't2', seq: 2 },
  ];
  const snapshot = structuredClone(tasks);
  const tree = taskTree(pm, tasks, [], { terms, live, lang: 'zh', retiredParts });
  assert.deepEqual(tasks, snapshot, 'taskTree never mutates input tasks');
  // Live helper of an open task is excluded from standalone Sessions
  assert.deepEqual(tree.sessions, []);
  assert.deepEqual(tree.groups.map(g => g.id), ['waiting', 'working']);
  // epic-wait bubbled to waiting because wait-child is blocked
  const waitNodes = tree.groups[0].nodes;
  assert.deepEqual(waitNodes.map(n => n.task), ['epic-wait']);
  assert.equal(waitNodes[0].container, true);
  assert.equal(waitNodes[0].summary.waiting, 1);
  // Working group order: postGate -> review (epic-lib has review child, t-rev is review) -> answered (t-ans) -> in_progress (t-ip, feat-main, orphan-open, cyc-a)
  const workNodes = tree.groups[1].nodes;
  assert.deepEqual(workNodes.map(n => n.task), ['t-post', 'epic-lib', 't-rev', 't-ans', 't-ip', 'feat-main', 'orphan-open', 'cyc-a']);
  assert.equal(workNodes[0].postGate, true);
  assert.equal(workNodes[0].offline, undefined, 'postGate task stays in Working rather than Disconnected');
  assert.equal(workNodes[0].plan.pill, '3/4 · 装到 MBP');

  const epicLib = workNodes[1];
  assert.equal(epicLib.container, true);
  assert.equal(epicLib.working, false);
  assert.equal(epicLib.offline, undefined);
  assert.equal(epicLib.tone, 'quiet');
  assert.deepEqual(epicLib.agents, { active: [], ended: [], all: [], endedCount: 0, endedSummary: '' });
  assert.deepEqual(epicLib.children.map(c => c.task), ['lib-design', 'lib-docs', 'lib-ui']);
  assert.deepEqual(epicLib.finishedChildren.map(c => c.task), ['lib-a', 'lib-b']); // deduplicated lib-a, excludes lib-drop
  assert.deepEqual(epicLib.summary, { waiting: 0, review: 1, working: 1, offline: 0, paused: 0, parked: 1, done: 2 });
  assert.equal(epicLib.activeChild.task, 'lib-design');

  const featMain = workNodes.find(n => n.task === 'feat-main');
  assert.equal(featMain.container, false);
  assert.equal(featMain.agents.active.length, 1);
  assert.equal(featMain.children[0].task, 'feat-sub');
  // Cycle broken cleanly without dropping nodes
  const cycA = workNodes.find(n => n.task === 'cyc-a');
  assert.deepEqual(cycA.children.map(c => c.task), ['cyc-b']);
  assert.ok(tree.flatOpen.some(n => n.task === 'lib-docs'));
});

test('Threads 3: taskSteps merges outer plan and subplan across all 4 shapes, multi-round folding, and legacy fallback', () => {
  const { inferStepAnchor, parsePlanItems, taskSteps } = model;

  // Anchor detection guards against negation and distinguishes 审阅 vs 审查
  assert.equal(inferStepAnchor('合进 main（pm.py land）'), 'merge');
  assert.equal(inferStepAnchor('保留在 dev/ledger-backup 挂分支待你验收（不合 main）'), 'custom');
  assert.equal(inferStepAnchor('Hold in worktree (no merge)'), 'custom');
  assert.equal(inferStepAnchor('独立代码审查'), 'review');
  assert.equal(inferStepAnchor('免代码审查'), 'custom');
  assert.equal(inferStepAnchor('等你审阅定稿'), 'custom');
  assert.equal(inferStepAnchor('实现快照备份与清理脚本'), 'work');
  assert.equal(inferStepAnchor('自定义后置步 @merge'), 'merge');
  assert.equal(inferStepAnchor('同步安装到 MBP 并跑全量测试'), 'custom');
  assert.equal(inferStepAnchor('安装依赖并实现接口'), 'work');
  assert.equal(inferStepAnchor('审查并合进 main'), 'merge');
  assert.equal(inferStepAnchor('等你审查定稿'), 'custom');
  assert.equal(inferStepAnchor('自定义步骤 @none'), 'custom');
  assert.equal(inferStepAnchor('实现代码审查功能'), 'work');
  assert.equal(inferStepAnchor('审查并修复回归问题'), 'work');
  assert.equal(inferStepAnchor('Review and fix flaky test'), 'work');
  assert.equal(inferStepAnchor('审查并与用户确认'), 'custom');
  assert.equal(inferStepAnchor('Review with the user'), 'custom');
  assert.equal(inferStepAnchor('Independent code review'), 'review');
  assert.equal(inferStepAnchor('合进前做一次安全审查 @review'), 'review');

  // Exact alignment with main pm.py strict_cases (tight review inference)
  const strictCases = [
    ['实现审查面板', 'work'],
    ['Fix review panel layout', 'work'],
    ['Design review with user', 'work'],
    ['Review with user', 'custom'],
    ['审查并修改问题', 'work'],
    ['Review and implement fixes', 'work'],
    ['独立代码审查', 'review'],
    ['独立复审（提交后自动拉起）', 'review'],
    ['Independent code review (auto-started)', 'review'],
    ['Re-review', 'review'],
    ['审查', 'review'],
    ['实现审查面板 @review', 'review'],
    ['独立代码审查 @custom', 'custom'],
  ];
  for (const [text, expected] of strictCases) {
    assert.equal(inferStepAnchor(text), expected, text);
    assert.equal(parsePlanItems(text)[0].anchor, expected, text);
  }

  // Input format flexibility (semicolon string, array of strings, {steps} object, bare @tag steps)
  assert.deepEqual(parsePlanItems('[x] 第一步; [>] 第二步 @work; [ ] 独立审查').map(s => [s.text, s.state, s.anchor]), [
    ['第一步', 'done', 'custom'],
    ['第二步', 'doing', 'work'],
    ['独立审查', 'todo', 'review'],
  ]);
  assert.deepEqual(parsePlanItems('[>] @review; @none').map(s => [s.text, s.state, s.anchor]), [
    ['Review', 'doing', 'review'],
  ]);
  assert.equal(parsePlanItems({ steps: [{ title: 'Build API', done: true }] })[0].state, 'done');
  assert.equal(parsePlanItems(null).length, 0);

  // Unanchored review-word object step defaults to custom (yielding noReview=true when no explicit @review)
  assert.equal(parsePlanItems([{ text: '独立代码审查', state: 'todo' }])[0].anchor, 'custom');
  assert.equal(taskSteps({
    status: 'in_progress',
    plan: [{ text: '实现', state: 'doing', anchor: 'work' }, { text: '独立代码审查', state: 'todo' }],
  }).noReview, true);

  // Object-form steps store explicit anchor (custom stays custom; missing anchor also defaults custom without re-inference)
  const objPlan = parsePlanItems([
    { text: '分支实现', state: 'done', anchor: 'work' },
    { text: '独立审查', state: 'todo', anchor: 'review' },
    { text: '合进 main', state: 'todo', anchor: 'merge' },
    { text: '同步安装到 MBP 并跑全量测试', state: 'doing', anchor: 'custom' },
    { text: '实现后置收尾', state: 'todo' },
  ]);
  assert.deepEqual(objPlan.map(s => [s.anchor, s.explicitAnchor]), [
    ['work', true],
    ['review', true],
    ['merge', true],
    ['custom', true],
    ['custom', false],
  ]);

  // Object-form trailing custom step without anchor stays postGate=true, carries shortText pill, and stays in Working when offline
  const objPostTask = {
    id: 'obj-post',
    pm: 'pm-dudu',
    title: '对象步骤 post-gate',
    status: 'in_progress',
    offline: true,
    updated: '2026-11-21 15:30',
    plan: [
      { text: '分支实现与单测', state: 'done', anchor: 'work' },
      { text: '独立审查', state: 'done', anchor: 'review' },
      { text: '合进 main', state: 'done', anchor: 'merge' },
      { text: '同步安装到 MBP 并跑全量测试', state: 'doing' },
    ],
  };
  const objPostSteps = taskSteps(objPostTask, { lang: 'zh' });
  assert.equal(objPostSteps.postGate, true);
  assert.equal(objPostSteps.pill, '3/4 · 同步安装到 MBP 并跑全量…');
  const objPostTree = model.taskTree({ name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', pane: 'hc:tpm' }, [objPostTask], [], { lang: 'zh' });
  assert.deepEqual(objPostTree.groups.map(g => g.id), ['working']);
  assert.equal(objPostTree.groups[0].nodes[0].postGate, true);
  assert.equal(objPostTree.groups[0].nodes[0].offline, undefined);

  // Unanswered blocked with completed work never marks next @review step doing unless an active reviewer exists
  const blockedPlan = [
    { text: '实现', state: 'done', anchor: 'work' },
    { text: '独立审查', state: 'todo', anchor: 'review' },
    { text: '合进 main', state: 'todo', anchor: 'merge' },
  ];
  const blockedNoRev = taskSteps({ status: 'blocked', plan: blockedPlan }, { lang: 'zh' });
  assert.deepEqual(blockedNoRev.steps.map(s => s.state), ['done', 'todo', 'todo']);
  assert.equal(blockedNoRev.activeStep, null);

  const blockedPausedRev = taskSteps({ status: 'blocked', review: { id: 't-rev', status: 'paused' }, plan: blockedPlan }, { lang: 'zh' });
  assert.deepEqual(blockedPausedRev.steps.map(s => s.state), ['done', 'todo', 'todo']);
  assert.equal(blockedPausedRev.activeStep, null);

  const blockedStaleDoingRev = taskSteps({
    status: 'blocked',
    plan: [{ text: '实现', state: 'done', anchor: 'work' }, { text: '独立审查', state: 'doing', anchor: 'review' }],
  }, { lang: 'zh' });
  assert.deepEqual(blockedStaleDoingRev.steps.map(s => s.state), ['done', 'todo']);
  assert.equal(blockedStaleDoingRev.activeStep, null);

  const blockedLiveRev = taskSteps({ status: 'blocked', review: { id: 't-rev', status: 'blocked' }, plan: blockedPlan }, { lang: 'zh' });
  assert.deepEqual(blockedLiveRev.steps.map(s => s.state), ['done', 'doing', 'todo']);
  assert.equal(blockedLiveRev.activeStep?.anchor, 'review');

  // Shape A: Design-only (no code review step, no merge step) -> reporting review advances to sign-off without inventing steps
  const shapeA = taskSteps({
    status: 'review',
    plan: [
      '[x] 隔离私有 Herdr 真机探针验证 API 可行性',
      '[>] 出中英双语交互稿并起本地预览（@work）',
      '[ ] 等你审阅定稿（确认后直接归档）',
    ],
    subplan: [
      '[x] 任务树、下挂 agents 与小窗开关',
      '[>] 更新 README 与截图',
    ],
  }, { lang: 'zh' });
  assert.equal(shapeA.steps.length, 3);
  assert.deepEqual(shapeA.steps.map(s => s.state), ['done', 'done', 'doing']);
  assert.equal(shapeA.steps[1].substeps[1].state, 'done', 'residual doing substep closed when work advances');
  assert.equal(shapeA.noReview, true);
  assert.equal(shapeA.autoReview, false);
  assert.equal(shapeA.postGate, false);
  assert.equal(shapeA.progress, '2/3');

  // Shape B: Held on branch (no merge) — paused keeps recorded states
  const shapeB = taskSteps({
    status: 'paused',
    plan: ['[x] 实现快照备份与清理脚本', '[x] 独立审查核对', '[>] 保留在 dev/ledger-backup 挂分支待你验收（不合 main）'],
    subplan: ['[x] 快照打包', '[x] 清理校验'],
  }, { lang: 'zh' });
  assert.deepEqual(shapeB.steps.map(s => s.state), ['done', 'done', 'doing']);
  assert.equal(shapeB.paused, true);
  assert.equal(shapeB.postGate, false);
  assert.equal(shapeB.pill, '2/3');

  // Shape C: Merge-only + multi-round rework & folding
  const reworkR2 = taskSteps({
    status: 'in_progress',
    rounds: 1,
    plan: ['[x] 初稿脱敏', '[ ] 全量译为英文', '[>] 独立复审', '[ ] 合进 main'],
    subplan: ['[>] 修复英文索引'],
  }, { lang: 'zh' });
  assert.deepEqual(reworkR2.steps.map(s => s.state), ['done', 'doing', 'todo', 'todo']);
  assert.equal(reworkR2.round, 2);
  assert.equal(reworkR2.foldedRounds, 1);
  assert.equal(reworkR2.foldedLabel, '第1轮');
  assert.equal(reworkR2.steps[1].round, 2);
  assert.equal(reworkR2.rail[0].text, '第1轮');

  const reviewR3 = taskSteps({
    status: 'review',
    rounds: 3,
    plan: ['[x] 初稿脱敏', '[x] 全量译为英文', '[ ] 独立复审', '[ ] 合进 main'],
  }, { lang: 'en' });
  assert.equal(reviewR3.round, 3);
  assert.equal(reviewR3.foldedRounds, 2);
  assert.equal(reviewR3.foldedLabel, 'R1–2');
  assert.equal(reviewR3.steps[2].state, 'doing');
  assert.equal(reviewR3.steps[2].round, 3);

  // Shape D: Landed into main with trailing install step -> stays active as postGate, NO false Round 2!
  const shapeDPost = taskSteps({
    status: 'in_progress',
    rounds: 1,
    landed: true,
    plan: ['[x] 派出对齐', '[>] 分支实现与单测', '独立代码审查', '合进 main（pm.py land）', '同步安装到本机与 MBP'],
    subplan: ['[x] 白名单数据源（排除探针目录）', '[>] 跑通全部 42 条单元测试并确认'],
  }, { lang: 'zh' });
  assert.deepEqual(shapeDPost.steps.map(s => s.state), ['done', 'done', 'done', 'done', 'doing']);
  assert.equal(shapeDPost.postGate, true);
  assert.equal(shapeDPost.foldedRounds, 0, 'does not treat rounds=1 after merge as Round 2 rework');
  assert.equal(shapeDPost.pill, '4/5 · 同步安装到本机与 MBP');
  assert.equal(shapeDPost.steps[1].subProgress.done, 2);
  // Secondary parenthetical notes & long labels stay compact in shortText while preserving full tip/note for hover
  assert.equal(shapeDPost.steps[3].shortText, '合进 main');
  assert.equal(shapeDPost.steps[3].note, 'pm.py land');
  assert.equal(shapeDPost.steps[3].tip, '合进 main（pm.py land）');
  assert.equal(shapeDPost.steps[4].tip, '');
  assert.equal(shapeDPost.steps[1].substeps[0].shortText, '白名单数据源');
  assert.equal(shapeDPost.steps[1].substeps[0].note, '排除探针目录');
  assert.equal(shapeDPost.steps[1].substeps[0].tip, '白名单数据源（排除探针目录）');
  assert.ok(shapeDPost.steps[1].substeps[1].shortText.endsWith('…'));
  assert.equal(shapeDPost.steps[1].substeps[1].tip, '跑通全部 42 条单元测试并确认');

  // ASCII display-width clipping respects STEP_LABEL_UNITS
  const asciiClipped = taskSteps({
    status: 'in_progress',
    plan: ['Audit 5 whitelisted roots & ignore rules (see README)'],
  }, { lang: 'en' });
  assert.equal(asciiClipped.steps[0].shortText, 'Audit 5 whitelisted root…');
  assert.equal(asciiClipped.steps[0].note, 'see README');
  assert.equal(asciiClipped.steps[0].tip, 'Audit 5 whitelisted roots & ignore rules (see README)');

  // Done closes all steps
  const shapeDDone = taskSteps({ status: 'done', plan: shapeDPost.steps.map(s => s.text) }, { lang: 'en' });
  assert.equal(shapeDDone.done, 5);
  assert.equal(shapeDDone.postGate, false);

  // Legacy task without plan -> minimal 2 or 3 steps, never guesses merge/install
  const legacyWork = taskSteps({ status: 'in_progress' }, { lang: 'zh' });
  assert.equal(legacyWork.hasPlan, false);
  assert.equal(legacyWork.pill, '');
  assert.deepEqual(legacyWork.steps.map(s => [s.text, s.state]), [['执行', 'doing'], ['完成', 'todo']]);

  const legacyRev = taskSteps({ status: 'review' }, { lang: 'en' });
  assert.deepEqual(legacyRev.steps.map(s => [s.text, s.state]), [['Work', 'done'], ['Review', 'doing'], ['Done', 'todo']]);
});

test('Threads 3: threadAgents, agentDefaultMode, floating small window toggle & Escape stack', () => {
  const {
    threadAgents, agentDefaultMode, AGENT_WINDOW_MAX,
    normalizeAgentWindowSize, nextAgentWindowSize, agentWindowDimensions, agentWindowTerminalAddresses, setAgentWindowSize,
    agentWindowOpen, toggleAgentWindow, focusAgentWindow, closeAgentWindow, setAgentWindowOverlay, toggleAgentWindowMode, reconcileAgentWindows,
    escapeStep, word,
  } = model;

  assert.equal(AGENT_WINDOW_MAX, 2);
  assert.equal(normalizeAgentWindowSize(''), 'm');
  assert.equal(normalizeAgentWindowSize('L'), 'l');
  assert.equal(normalizeAgentWindowSize('invalid'), 'm');
  assert.equal(nextAgentWindowSize('s'), 'm');
  assert.equal(nextAgentWindowSize('m'), 'l');
  assert.equal(nextAgentWindowSize('l'), 's');
  assert.deepEqual(agentWindowDimensions('chat', 's'), { width: 420, height: 340 });
  assert.deepEqual(agentWindowDimensions('terminal', 'm'), { width: 540, height: 380 });
  assert.deepEqual(agentWindowDimensions('terminal', 'l'), { width: 800, height: 540 });
  assert.deepEqual(agentWindowDimensions('terminal', 'l', { maxWidth: 640, maxHeight: 400 }), { width: 640, height: 400 });
  assert.deepEqual(agentWindowDimensions('chat', 's', { maxWidth: 200, maxHeight: 100 }), { width: 360, height: 260 });

  assert.deepEqual(agentWindowTerminalAddresses([
    { key: 'w1', mode: 'chat', address: 't1' },
    { key: 'w2', mode: 'terminal', address: 't2' },
    { key: 'w3', mode: 'terminal', address: 't1' },
    { key: 'w4', mode: 'terminal', address: '' },
  ]), ['t1', 't2']);
  assert.deepEqual(agentWindowTerminalAddresses([
    { key: 'w2', mode: 'terminal', address: 't2' },
    { key: 'w3', mode: 'terminal', address: 'mbp/t2' },
  ], 'mbp'), ['mbp/t2']);

  let sizedWins = toggleAgentWindow([], { key: 'w1', mode: 'terminal', address: 't1' }).windows;
  assert.equal(sizedWins[0].size, 'm');
  let swSize = setAgentWindowSize(sizedWins, 'w1');
  assert.equal(swSize.changed, true);
  assert.equal(swSize.window.size, 'l');
  sizedWins = swSize.windows;
  assert.equal(setAgentWindowSize(sizedWins, 'w1', 'l').changed, false);
  swSize = setAgentWindowSize(sizedWins, 'w1', 's');
  assert.equal(swSize.changed, true);
  assert.equal(swSize.window.size, 's');
  assert.equal(agentDefaultMode({ role: 'worker', kind: 'claude', address: 't1' }), 'chat');
  assert.equal(agentDefaultMode({ role: 'worker', kind: 'agy', address: 't2' }), 'terminal');
  assert.equal(agentDefaultMode({ role: 'helper', kind: 'agy', address: 't3', ended: false }), 'terminal');
  assert.equal(agentDefaultMode({ role: 'helper', kind: 'agy', ended: true, resultPath: '/tmp/scan.md' }), 'chat');

  // Single active worker still gets 1 compact row
  const single = threadAgents(
    { id: 't-one', title: '单 worker', status: 'in_progress', pane: 'hc:t1', engine: { kind: 'agy', model: 'carbon' }, context_tokens: 68_000 },
    { terms: [{ address: 't1', state: 'live', status: 'working', labels: { task: 't-one' } }], lang: 'zh' },
  );
  assert.equal(single.active.length, 1);
  assert.equal(single.active[0].role, 'worker');
  assert.equal(single.active[0].defaultMode, 'terminal');
  assert.equal(single.active[0].contextLabel, '68k');

  // Multi-agent thread: worker + review + ledger/live helpers deduplicated
  const multi = threadAgents(
    {
      id: 'dudu-lib', title: 'Library 后端', status: 'review', pane: 'hc:tw',
      engine: { profile: 'hard', kind: 'agy', model: 'carbon' }, escalations: [{ from: 'standard', to: 'hard' }], context_tokens: 84_000,
      review: { id: 'dudu-lib-review', status: 'in_progress', pane: 'hc:tr', engine: { kind: 'claude', model: 'opus' }, context_tokens: 41_000 },
      helpers: [
        { name: 'scan-pitfalls', terminal: 'th1', status: 'running', kind: 'agy', model: 'neon', result: '/tmp/scan.md', live_state: 'working' },
        { name: 'stale-helper', terminal: 'th_dead', status: 'running', offline: true, kind: 'agy', model: 'neon', result: '/tmp/stale.md' },
        { name: 'old-check', terminal: 'th0', status: 'done', kind: 'agy', model: 'neon', result: '/tmp/old.md', summary: 'ok' },
      ],
    },
    {
      terms: [
        { address: 'tw', state: 'live', status: 'working', labels: { task: 'dudu-lib' } },
        { address: 'tr', state: 'live', status: 'working', labels: { task: 'dudu-lib-review' } },
        { address: 'th1', state: 'live', status: 'working', labels: { helper: 'scan-pitfalls', 'helper.of': 'dudu-lib' } },
        { address: 'th2', state: 'live', status: 'idle', labels: { helper: 'live-only', 'helper.of': 'dudu-lib' }, program: { key: 'claude' } },
      ],
      lang: 'zh',
    },
  );
  assert.deepEqual(multi.active.map(a => [a.role, a.name, a.defaultMode]), [
    ['worker', 'dudu-lib', 'terminal'],
    ['review', 'dudu-lib-review', 'chat'],
    ['helper', 'scan-pitfalls', 'terminal'],
    ['helper', 'live-only', 'chat'],
  ]);
  assert.equal(multi.active[0].up, true);
  assert.equal(multi.endedCount, 2);
  assert.equal(multi.ended[0].defaultMode, 'chat');
  assert.equal(multi.endedSummary, '2 已结束 · Agy');

  // Paused thread puts agents into ended with summary
  const paused = threadAgents(
    { id: 'bk', title: '备份', status: 'paused', pane: 'hc:tb', engine: { kind: 'claude', model: 'opus' }, context_tokens: 131_000,
      review: { id: 'bk-review', status: 'done', engine: { kind: 'claude', model: 'opus' }, context_tokens: 38_000 } },
    { lang: 'en' },
  );
  assert.equal(paused.active.length, 0);
  assert.equal(paused.endedCount, 2);
  assert.equal(paused.endedSummary, '2 ended · Opus · 131k');

  // Small window toggle state machine (cap 2, toggle same row closes, LRU eviction, focus, mode switch)
  let wins = [];
  const a1 = multi.active[0], a2 = multi.active[1], a3 = multi.active[2];
  let r = toggleAgentWindow(wins, a1);
  wins = r.windows;
  assert.equal(r.action, 'open');
  assert.equal(agentWindowOpen(wins, a1.key), true);

  // Toggle same agent closes it without killing
  r = toggleAgentWindow(wins, a1);
  wins = r.windows;
  assert.equal(r.action, 'close');
  assert.equal(r.closed.key, a1.key);
  assert.equal(wins.length, 0);

  // Open 2 windows, focus a1 (so a2 becomes oldest unfocused), then open a3 -> evicts a2!
  wins = toggleAgentWindow(wins, a1).windows;
  wins = toggleAgentWindow(wins, a2).windows;
  wins = focusAgentWindow(wins, a1.key);
  assert.deepEqual(wins.map(w => w.key), [a2.key, a1.key]);
  r = toggleAgentWindow(wins, a3);
  wins = r.windows;
  assert.equal(r.evicted.key, a2.key);
  assert.deepEqual(wins.map(w => w.key), [a1.key, a3.key]);

  // Overlay id update & mode switch
  wins = setAgentWindowOverlay(wins, a1.key, 'ov-1');
  assert.equal(wins[0].overlayId, 'ov-1');
  const sw = toggleAgentWindowMode(wins, a1.key);
  assert.equal(sw.changed, true);
  assert.equal(sw.window.mode, 'chat');
  const blockedSw = toggleAgentWindowMode(toggleAgentWindow([], paused.ended[0]).windows, paused.ended[0].key, 'terminal');
  assert.equal(blockedSw.changed, false);

  // Reconciling exited terminal-mode windows returns them for closeOverlay while keeping live & chat windows
  const recInput = [
    { key: 'worker:t1', mode: 'terminal', address: 'tw', overlayId: 'ov-term-live' },
    { key: 'helper:t1:th1', mode: 'terminal', address: 'th1', overlayId: 'ov-term-exited' },
    { key: 'review:t1-r', mode: 'chat', address: 'tr', overlayId: 'ov-chat-exited' },
  ];
  const rec = reconcileAgentWindows(recInput, new Set(['tw']));
  assert.deepEqual(rec.closed.map(w => w.overlayId), ['ov-term-exited']);
  assert.deepEqual(rec.windows.map(w => w.key), ['worker:t1', 'review:t1-r']);
  assert.equal(reconcileAgentWindows(rec.windows, new Set(['tw'])).windows, rec.windows);

  // Close topmost via Esc stack (editing/retopic/search exit before floating agent small windows)
  assert.equal(escapeStep({ typing: true, agentWindows: wins, detail: true }), 'blur');
  assert.equal(escapeStep({ editing: true, agentWindows: wins }), 'edit');
  assert.equal(escapeStep({ retopic: true, agentWindows: wins }), 'retopic');
  assert.equal(escapeStep({ search: true, agentWindows: wins }), 'search');
  assert.equal(escapeStep({ agentWindows: wins, history: true, bringBack: true, detail: true, doc: true, listOpen: true }), 'agentWindow');
  assert.equal(escapeStep({ agentWindow: true, detail: true }), 'agentWindow');
  let c = closeAgentWindow(wins);
  assert.equal(c.closed.key, a3.key);
  c = closeAgentWindow(c.windows);
  assert.equal(c.closed.key, a1.key);
  assert.equal(escapeStep({ agentWindows: c.windows, detail: true, listOpen: true }), 'detail');
  assert.equal(escapeStep({ agentWindows: c.windows, detail: false, listOpen: true }), 'list');

  // All centralized PLAN_STRINGS and THREAD_STRINGS keys present in both en and zh
  const centralizedKeys = [
    ...Object.keys(model.PLAN_STRINGS.en),
    ...Object.keys(model.THREAD_STRINGS.en),
  ];
  assert.ok(centralizedKeys.includes('planAutoReviewTip'));
  assert.ok(centralizedKeys.includes('planNoReviewTip'));
  for (const key of centralizedKeys) {
    for (const lang of ['en', 'zh']) {
      const val = typeof model.STRINGS[lang][key] === 'function' ? word(lang, key, 2, 5, 'step') : word(lang, key);
      assert.ok(val && val !== key, `missing ${lang}.${key}`);
    }
  }
});

test('Quote reply (Option A): plain HTML, clipboard matching, multi-quote serialization, drafts, jump lookup & i18n', () => {
  const {
    escapeHtml, plainTextToHtml, markdownToPlain, extractClipboardQuote,
    isQuotableSelection, QUOTE_MIN_SELECTION_CHARS,
    withQuote, withoutQuote, quotePreviewLine, QUOTE_LIMIT,
    formatQuotedMessage, splitQuotedMessage, draftQuotes, readDrafts, keepDraft, afterSend,
    splitMessage, messageText, sameMessage, blockIndexForKey, selectionToolbarState, escapeStep, timeline, turns, timelineRows, word,
  } = model;

  // (1) HTML escaping & Markdown-to-plain conversion
  assert.equal(escapeHtml(`a < b & "c" 'd'`), 'a &lt; b &amp; &quot;c&quot; &#39;d&#39;');
  assert.equal(plainTextToHtml('line 1\n<tag>'), '<span>line 1<br/>&lt;tag&gt;</span>');
  const mdSample = [
    '# Heading',
    '',
    'See **bold**, `code`, and [@Alpha](thread:t-a).',
    '',
    '| ColA | ColB |',
    '| --- | --- |',
    '| **Cell1** | `Cell2` |',
    '',
    '```js',
    'const x = 1;',
    '```',
  ].join('\n');
  const plain = markdownToPlain(mdSample);
  assert.ok(plain.includes('Heading'));
  assert.ok(plain.includes('See bold, code, and @Alpha.'));
  assert.ok(plain.includes('Cell1 Cell2'));
  assert.ok(plain.includes('const x = 1;'));
  assert.equal(plain.includes('```'), false);

  // (2) Clipboard substring matching vs whole-message fallback, freshness baseline & min-length guard
  assert.equal(QUOTE_MIN_SELECTION_CHARS, 4);
  for (const shortOrBlank of ['', '   ', 'ok', 'foo', '123', '好', '好的', '----', 'a .']) {
    assert.equal(isQuotableSelection(shortOrBlank), false, `reject short/blank selection ${JSON.stringify(shortOrBlank)}`);
  }
  for (const validSel of ['main', '四个汉字', 'a b', 'CellA CellB']) {
    assert.equal(isQuotableSelection(validSel), true, `accept valid selection ${JSON.stringify(validSel)}`);
  }

  assert.deepEqual(extractClipboardQuote('code, and @Alpha', mdSample), { text: 'code, and @Alpha', exact: true });
  assert.deepEqual(extractClipboardQuote('Cell1   Cell2', mdSample), { text: 'Cell1   Cell2', exact: true });
  // Stale clipboard equal to hover baseline (even if it matches the message) falls back to whole message
  assert.equal(extractClipboardQuote('main', 'Check main and ok before merge', { baseline: 'main' }).exact, false);
  assert.equal(extractClipboardQuote('ok', 'Check main and ok before merge', { baseline: 'ok' }).exact, false);
  assert.equal(extractClipboardQuote('code, and @Alpha', mdSample, { baseline: 'code, and @Alpha' }).exact, false);
  assert.equal(extractClipboardQuote('Cell1 Cell2\r\n', mdSample, { baseline: 'Cell1 Cell2' }).exact, false);
  // Freshly copied short single tokens (< 4 chars, including markdown wrappers) fall back to whole message
  for (const shortClip of ['ok', 'foo', '**ok**', '`ok`', '好的']) {
    assert.equal(
      extractClipboardQuote(shortClip, 'Check ok foo and 好的 here', { baseline: '' }).exact,
      false,
      `short fresh clip ${JSON.stringify(shortClip)} falls back to whole message`,
    );
  }
  // Freshly copied >= 4 chars or multi-word phrase matches exact substring
  assert.deepEqual(extractClipboardQuote('code, and @Alpha', mdSample, { baseline: 'old' }), { text: 'code, and @Alpha', exact: true });
  assert.deepEqual(extractClipboardQuote('四个汉字', '这里有四个汉字可引用', { baseline: '' }), { text: '四个汉字', exact: true });
  assert.deepEqual(extractClipboardQuote('main', 'Switch to main branch', { baseline: 'old' }), { text: 'main', exact: true });
  assert.deepEqual(extractClipboardQuote('a b', 'Prefix a b suffix', { baseline: '' }), { text: 'a b', exact: true });

  const whole = extractClipboardQuote('unrelated clipboard text', mdSample, { maxChars: 60 });
  assert.equal(whole.exact, false);
  assert.equal(whole.text.length <= 61, true);
  const emptyClip = extractClipboardQuote('', 'Short raw text');
  assert.deepEqual(emptyClip, { text: 'Short raw text', exact: false });

  // (3) Multi-quote stacking, deduping, limit, and preview truncation
  let qs = [];
  qs = withQuote(qs, { id: 'q1', targetKey: 'pm:1:', author: 'PM', time: '09:00', text: 'First excerpt', exact: true });
  qs = withQuote(qs, { id: 'q2', targetKey: 'pm:1:', author: 'PM', time: '09:00', text: 'First excerpt', exact: true });
  assert.equal(qs.length, 1, 'identical (targetKey, text) deduplicated');
  qs = withQuote(qs, { id: 'q3', targetKey: 'pm:1:', author: 'PM', time: '09:00', text: 'Second excerpt from same reply', exact: true });
  assert.equal(qs.length, 2, 'distinct excerpts from same message stay stacked');
  qs = withoutQuote(qs, 'q1');
  assert.deepEqual(qs.map(q => q.id), ['q3']);
  for (let i = 0; i < QUOTE_LIMIT + 3; i++) {
    qs = withQuote(qs, { id: `bulk-${i}`, targetKey: `pm:${i}:`, author: 'PM', time: '09:00', text: `Quote #${i}` });
  }
  assert.equal(qs.length, QUOTE_LIMIT);
  assert.equal(quotePreviewLine('  line one\n\nline two  ', 12), 'line one li…');

  // (4) Wire format round-trip (single, multi, multiline, attachments, answerText prefix, @mentions, plain blockquote preservation)
  const qA = { id: 'a', targetKey: 'pm:2026-11-22 09:00:00:', author: 'PM', time: '09:00', text: 'Paragraph 1\n\nParagraph 2' };
  const qB = { id: 'b', targetKey: 'user:2026-11-21 18:10:00:', author: '你', time: '11-21 18:10', text: 'Earlier point (with parens)' };
  const wireMulti = formatQuotedMessage([qA, qB], 'Check [@spec.md](library:docs/spec.md)');
  const parsedMulti = splitQuotedMessage(wireMulti);
  assert.equal(parsedMulti.quotes.length, 2);
  assert.equal(parsedMulti.quotes[0].targetKey, 'pm:2026-11-22 09:00:00:');
  assert.equal(parsedMulti.quotes[0].author, 'PM');
  assert.equal(parsedMulti.quotes[0].time, '09:00');
  assert.equal(parsedMulti.quotes[0].text, 'Paragraph 1\n\nParagraph 2');
  assert.equal(parsedMulti.quotes[1].targetKey, 'user:2026-11-21 18:10:00:');
  assert.equal(parsedMulti.quotes[1].author, '你');
  assert.equal(parsedMulti.quotes[1].time, '11-21 18:10');
  assert.equal(parsedMulti.quotes[1].text, 'Earlier point (with parens)');
  assert.equal(parsedMulti.text, 'Check [@spec.md](library:docs/spec.md)');

  // Quote-only message + attachment path round-trips through splitMessage without path collision
  const wireWithFile = messageText(formatQuotedMessage([qA], ''), ['/tmp/shot.png'], word('en', 'attachments'));
  const splitFile = splitMessage(wireWithFile);
  assert.deepEqual(splitFile.files, ['/tmp/shot.png']);
  const splitFileQuotes = splitQuotedMessage(splitFile.text);
  assert.equal(splitFileQuotes.quotes.length, 1);
  assert.equal(splitFileQuotes.text, '');
  assert.equal(sameMessage('[Image #1]\n\n' + formatQuotedMessage([qA], ''), wireWithFile), true);

  // Regular user markdown blockquote is NOT stripped as structured quote provenance
  assert.deepEqual(splitQuotedMessage('> Just a regular markdown quote\n\nReply body'), {
    quotes: [],
    text: '> Just a regular markdown quote\n\nReply body',
  });

  // Question answer + quotes keeps 【Title】 at start so timeline marks question answered
  const wireAns = formatQuotedMessage([qA], 'Use Redis', { to: 'Rate Limit' });
  assert.equal(wireAns.startsWith('【Rate Limit】\n> [↩ PM · 09:00](quote:'), true);
  const parsedAns = splitQuotedMessage(wireAns);
  assert.equal(parsedAns.quotes.length, 1);
  assert.equal(parsedAns.text, '【Rate Limit】Use Redis');
  const qItems = timeline(
    [
      { at: '2026-11-22 09:00:00', type: 'pm', text: 'Options' },
      { at: '2026-11-22 09:01:00', type: 'thread', task: 't-rl', status: 'blocked', text: 'Which backend?' },
      { at: '2026-11-22 09:02:00', type: 'user', text: wireAns },
    ],
    [{ id: 't-rl', pm: 'pm-dudu', title: 'Rate Limit', status: 'blocked', updated: '2026-11-22 09:01' }],
    { pm: 'pm-dudu', today: '2026-11-22' },
  );
  assert.equal(qItems.find(i => i.kind === 'question')?.answered, true);
  const rows = timelineRows(turns(qItems));
  assert.equal(blockIndexForKey(rows, 'pm:2026-11-22 09:00:00:'), 1);
  assert.equal(blockIndexForKey(rows, 'question:2026-11-22 09:01:00:t-rl'), 2);
  assert.equal(blockIndexForKey(rows, 'user:2026-11-22 09:02:00:'), 3);
  assert.equal(blockIndexForKey(rows, 'missing:key'), -1);

  // (5) Draft storage persistence & selective send cleanup
  let drafts = keepDraft({}, 'pm:dudu', '', 1000, [], undefined, [qA]);
  assert.equal(draftQuotes(drafts, 'pm:dudu').length, 1);
  // Typing text without touching quotes preserves quotes
  drafts = keepDraft(drafts, 'pm:dudu', 'My reply', 1001, []);
  const reloadedDrafts = readDrafts(JSON.stringify(drafts));
  assert.equal(draftQuotes(reloadedDrafts, 'pm:dudu').length, 1);
  assert.deepEqual(afterSend({ text: 'My reply', files: [], quotes: [qA, qB] }, { text: 'My reply', files: [], quotes: [qA] }, true), {
    text: '',
    files: [],
    quotes: [{ kind: 'pm', at: '', ...qB }],
  });
  assert.deepEqual(afterSend({ text: '', files: [], quotes: [] }, { text: '', files: [], quotes: [qA] }, false), {
    text: '',
    files: [],
    quotes: [{ kind: 'pm', at: '', ...qA }],
  });

  // (6) Future selection toolbar seam & Escape order
  assert.equal(selectionToolbarState({ text: '   ' }, { key: 'pm:1:' }), null);
  assert.equal(selectionToolbarState({ text: 'picked' }, null), null);
  const seam = selectionToolbarState({ text: 'picked slice', bounds: { x: 10, y: 20, width: 80, height: 18 } }, { key: 'pm:1:', kind: 'pm', author: 'PM', time: '09:00' });
  assert.deepEqual(seam, { text: 'picked slice', bounds: { x: 10, y: 20, width: 80, height: 18 }, source: { key: 'pm:1:', kind: 'pm', author: 'PM', at: '', time: '09:00' } });
  assert.equal(escapeStep({ mentionSub: true, selectionBar: true }), 'mentionSub');
  assert.equal(escapeStep({ mention: true, selectionBar: true }), 'mention');
  assert.equal(escapeStep({ selectionBar: true, answering: true, typing: true }), 'selectionBar');

  // (7) en (default) & zh strings for all quote keys
  for (const key of ['quoteMessage', 'quoteSelection', 'quoteRemove', 'quoteJump', 'quoteJumpMissing', 'quoteFrom', 'quoteAuthorPm', 'quoteAuthorYou', 'quoteAuthorQuestion', 'quoteCount', 'quoteSelectionAction']) {
    for (const lang of ['en', 'zh']) {
      const val = typeof model.STRINGS[lang][key] === 'function'
        ? (key === 'quoteFrom' ? word(lang, key, 'PM', '09:00') : word(lang, key, 2))
        : word(lang, key);
      assert.ok(val && val !== key, `missing ${lang}.${key}`);
    }
  }
});

test('PmProject selectable conversation, window_drag isolation, hover quote, multi-quote bar, send provenance & jump-back (en & zh)', async () => {
  const fs = await import('node:fs');
  const raw = fs.readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const source = `${raw
    .replace(/^\s*import\s+[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/export\s+default\s+class\s+/, 'class ')}\nreturn PmProject;`;

  const nodes = new Map();
  const textViews = new Map();
  const decodeHtml = h => String(h ?? '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/?span>/gi, '')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&');
  const allTexts = rec => [...rec.texts, ...rec.kids.flatMap(allTexts)];
  const makeEl = (extra = {}) => {
    const rec = { id: '', texts: [], kids: [], tips: [], clicks: null, hovers: [], mouseDowns: [], selectable: false, cursorText: false, onSel: null, onLink: null, ...extra };
    const proxy = new Proxy(() => proxy, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        if (key === '__allTexts') return () => allTexts(rec);
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') { if (typeof args[0] === 'string') rec.texts.push(args[0]); else if (args[0]?.__rec) rec.kids.push(args[0].__rec); }
          else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) { if (typeof k === 'string') rec.texts.push(k); else if (k?.__rec) rec.kids.push(k.__rec); }
          }
          else if (key === 'content' && args[0]?.__rec) rec.kids.push(args[0].__rec);
          else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'on_hover') rec.hovers.push(args[0]);
          else if (key === 'on_mouse_down') rec.mouseDowns.push(args[1] || args[0]);
          else if (key === 'selectable') rec.selectable = args[0] === undefined ? true : Boolean(args[0]);
          else if (key === 'cursor_text') rec.cursorText = true;
          else if (key === 'on_selection_change') rec.onSel = args[0];
          else if (key === 'on_link_click') rec.onLink = args[0];
          else if (key === 'tooltip') rec.tips.push(args[0]);
          else if (key === 'when') { if (args[0]) args[1](proxy); }
          return proxy;
        };
      },
      apply: () => proxy,
    });
    rec.allTexts = () => allTexts(rec);
    return proxy;
  };

  const makeBox = () => {
    let text = '';
    const handlers = {};
    return {
      on(ev, fn) { (handlers[ev] ||= []).push(fn); return true; },
      value: () => text,
      content: () => ({ text, tokens: [] }),
      selected_range: () => ({ start: text.length, end: text.length }),
      set_selected_range() {},
      set_value(next) { text = typeof next === 'object' ? String(next.text || '') : String(next ?? ''); },
      set_auto_grow() {}, set_soft_wrap() {}, focus() {},
      __type(str) { text += str; },
    };
  };

  let clipText = '';
  const sentCmds = [];
  const scrolledTo = [];
  let focusCalls = 0;
  const timers = [];
  const stubs = {
    View: class {}, ...model,
    div: () => makeEl(), h_flex: () => makeEl(), v_flex: () => makeEl(), svg: () => makeEl(), image: () => makeEl(),
    TextView: {
      markdown: (id, md) => {
        const el = makeEl({ tvKind: 'markdown', tvId: id, raw: String(md ?? '') }).child(String(md ?? ''));
        textViews.set(id, el.__rec);
        return el;
      },
      html: (id, html) => {
        const el = makeEl({ tvKind: 'html', tvId: id, raw: String(html ?? '') }).child(decodeHtml(html));
        textViews.set(id, el.__rec);
        return el;
      },
    },
    TextareaState: { new: () => makeBox() },
    Textarea: { new: () => makeEl() },
    InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, focus() {} }) },
    Input: { new: () => makeEl() },
    ScrollHandle: { new: () => ({ scroll_to_item: i => scrolledTo.push(i) }) },
    Popup: { new: (id, trigger) => makeEl().id(id).child(trigger) },
    theme: () => ({
      canvas: '#111111', surface: '#181818', raised: '#222222', chrome: '#161616', hover: '#2a2a2a',
      border: '#333333', input: '#3a3a3a', foreground: '#eeeeee', background: '#111111',
      muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', accent_foreground: '#ffffff',
      blocked: '#ff5f56', ansi2: '#27c93f', ansi3: '#f5a623', solid: '#eeeeee', solid_foreground: '#111111',
    }),
    home: () => '/Users/test', appHome: () => '/app',
    exec: async (_cmd, args) => {
      if (args?.includes('send')) sentCmds.push(args);
      return { code: 0, stdout: JSON.stringify({ events: [], from: 0, offset: 0, earlier: false }), stderr: '' };
    },
    execPython: async (_exec, argv, opts) => stubs.exec('python3', argv, opts),
    readTextFile: async () => '', writeTextFile: async () => {}, watchFolder: () => new Promise(() => {}),
    layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run() {},
    terminals: () => [{ address: 'tpm', state: 'live', labels: { pm: 'dudu' } }],
    agents: () => [], panes: () => [{ terminal: 'tpm' }], spaces: () => [],
    shared: () => ({ pm: 'pm-dudu' }), setShared() {},
    appWindow: () => ({ platform: 'macos' }),
  };

  const prevStorage = globalThis.localStorage;
  const storeMap = new Map();
  globalThis.localStorage = { getItem: k => storeMap.get(k) ?? null, setItem: (k, v) => storeMap.set(k, String(v)), removeItem: k => storeMap.delete(k) };
  try {
    const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
    const cx = {
      focus_handle: () => ({ focus() { focusCalls++; } }),
      spawn: fn => fn(cx),
      timer: { after: (ms, fn) => { timers.push({ ms, fn }); } },
      notify() {},
      stop_propagation() {},
      read_from_clipboard: () => clipText,
    };
    const today = (() => {
      const d = new Date(), p = n => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    })();
    const at = t => `${today} ${t}`;
    const longPm = 'First paragraph of older reply.\n\nSecond paragraph only visible when unfolded.';
    const tablePm = 'Summary:\n\n| Key | Value |\n| --- | --- |\n| **CellA** | `CellB` |';
    const pmLocal = { name: 'pm-dudu', project: 'dudu', repo: '/work/dudu', pane: 'hc:tpm', runtime: 'hc', status: 'live' };
    const view = Object.assign(Object.create(Mod.prototype), {
      state: { pms: [pmLocal], tasks: [{ id: 't-q', pm: 'pm-dudu', title: 'Choice', status: 'blocked', updated: at('09:01') }], events: [], lang: 'en' },
      events: [
        { at: at('09:00:00'), type: 'pm', text: longPm },
        { at: at('09:01:00'), type: 'thread', task: 't-q', status: 'blocked', text: 'Pick one option' },
        { at: at('09:02:00'), type: 'user', text: 'User asks about [@spec](library:docs/spec.md) details' },
        { at: at('09:03:00'), type: 'decision', text: 'Use Option A for quoting' },
        { at: at('09:04:00'), type: 'pm', text: tablePm },
      ],
      pending: [], seq: 0, pastes: [], error: '', logError: '',
      pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
      remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
      earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '/here', watching: {},
      thread: '', threadTask: null, detail: false, threadError: '', threadLog: null, threadLogKept: [],
      threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null, threadTab: 'log', sideTab: 'threads',
      librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: false, libraryProbed: true, libraryStale: false,
      libraryLoading: false, libraryAgain: false, libraryError: '', libraryClosed: new Set(), libraryQuery: '',
      libraryDropBusy: '', libraryDropError: '', memorySlug: '', memoryData: null, memoryRead: false, memoryStale: false,
      memoryLoading: false, memoryAgain: false, memoryError: '', memoryFoldOverrides: new Map(), memoryProjectOpen: true,
      memoryPersonalOpen: false, memoryCandidatesOpen: false, memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
      activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '', docShownBytes: model.DOC_INITIAL_BYTES,
      docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
      editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
      confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
      reattaching: '', reattachError: null, startingPm: '', startPmError: null,
      bringBackOpen: false, bringingBack: false, bringBackProgress: null,
      listShown: true, wide: true, measured: true, viewWidth: 1280, panelWant: null, panelDrag: null, gripLit: false,
      seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
      bell: null, flash: '', unfolded: new Map(), newest: '', atWork: new Set(),
      scroll: { scroll_to_item: i => scrolledTo.push(i) }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
      libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
      mentionScroll: { scroll_to_item() {} }, mention: null, mentionDismissed: null, mentionConsumedKey: false, mentionPicking: false,
      repoFilesSlug: '', repoFilesRepo: '', repoFiles: [], repoFilesRead: false, repoFilesLoading: false, repoFilesAgain: false,
      repoFilesError: '', repoFilesTruncated: false, repoFilesAt: 0, pathCopiedAt: 0,
      quotes: [], quoteSeq: 0, hoveredMsg: '', hoverClipboard: null, selectionBar: null, lastBlocks: [], lastTopOffset: 0, lastHeights: [], lastTall: 0,
      keyFocus: { focus() { focusCalls++; view.typing = ''; } }, onStage: true, typing: 'main', mainKey: 'pm:pm-dudu', threadKey: '',
      outgoing: new Map(), files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
      input: makeBox(), threadInput: makeBox(), libraryInput: stubs.InputState.new(), memoryInput: stubs.InputState.new(),
      docFindInput: stubs.InputState.new(), docNameInput: stubs.InputState.new(), memDescInput: stubs.InputState.new(),
      docEditorInput: stubs.TextareaState.new(), refresh: () => {},
    });
    view.resetThreadSession();

    const rerender = () => { nodes.clear(); textViews.clear(); view.render(cx); };
    rerender();

    // (1) Every conversation text element is selectable TextView, and neither selectable text nor its
    //     timeline/bubble ancestors register left mouse_down stop_propagation (which would kill ShellRoot's TextSelectionLayer).
    for (const tvId of [
      `lead-pm:${at('09:00:00')}:`,
      `q-txt-question:${at('09:01:00')}:t-q`,
      `bubble-user:${at('09:02:00')}:-t-0-0`,
      `dec-txt-decision:${at('09:03:00')}:`,
      `md-pm:${at('09:04:00')}:-p0`,
      `md-pm:${at('09:04:00')}:-p1`,
    ]) {
      assert.equal(textViews.get(tvId)?.selectable, true, `${tvId} is selectable`);
    }
    const pmWrap = nodes.get(`pm-msg-pm:${at('09:04:00')}:`);
    assert.ok(pmWrap);
    assert.equal(pmWrap.mouseDowns.length, 0, 'PM reply wrapper does not block TextSelectionLayer');
    const bubbleWrapper = nodes.get(`bubble-user:${at('09:02:00')}:`);
    assert.equal(bubbleWrapper.mouseDowns.length, 0, 'user bubble does not block TextSelectionLayer');
    const timelineEl = nodes.get('pm-project-timeline');
    assert.equal(timelineEl.mouseDowns.length, 0, 'timeline does not block TextSelectionLayer');
    const panelEl = nodes.get('pm-project-panel');
    assert.equal(panelEl.mouseDowns.length, 0, 'side panel does not block TextSelectionLayer');

    // (2) Hovering PM reply snapshots clipboard: stale clipboard (already in clipboard before hover) & <4-char clip fall back to whole message; fresh post-hover copy matches exact substring
    const foldKey = `pm:${at('09:00:00')}:`;
    const tableKey = `pm:${at('09:04:00')}:`;
    clipText = 'First paragraph of older reply.'; // already in clipboard BEFORE hovering foldKey!
    nodes.get(`pm-msg-${foldKey}`).hovers.forEach(fn => fn(true, cx));
    assert.equal(view.hoverClipboard, 'First paragraph of older reply.');
    rerender();
    view.hoverKey = `tip:quote-btn-${foldKey}`;
    rerender();
    assert.equal(nodes.get(`hover-tip-quote-btn-${foldKey}`)?.allTexts().join(' '), 'Quote');
    view.hoverKey = '';
    rerender();
    nodes.get(`quote-btn-${foldKey}`).clicks({ stop_propagation() {} }, cx);
    assert.equal(view.quotes.length, 1);
    assert.equal(Boolean(view.quotes[0].exact), false, 'stale matching clipboard from before hover falls back to whole message');
    assert.equal(view.quotes[0].targetKey, foldKey);
    assert.ok(view.quotes[0].text.includes('First paragraph of older reply.'));

    // Hovering tableKey: newly copied 3-char token ('Key') falls back to whole message; newly copied 'CellA CellB' after hover matches exact!
    clipText = 'unrelated';
    nodes.get(`pm-msg-${tableKey}`).hovers.forEach(fn => fn(true, cx));
    rerender();
    clipText = 'Key';
    nodes.get(`quote-btn-${tableKey}`).clicks({ stop_propagation() {} }, cx);
    assert.equal(view.quotes.length, 2);
    assert.equal(Boolean(view.quotes[1].exact), false, 'newly copied <4-char token falls back to whole message');
    view.removeQuote(view.quotes[1].id, cx);
    assert.equal(view.quotes.length, 1);

    clipText = 'CellA CellB';
    nodes.get(`quote-btn-${tableKey}`).clicks({ stop_propagation() {} }, cx);
    assert.equal(view.quotes.length, 2);
    assert.equal(view.quotes[1].exact, true);
    assert.equal(view.quotes[1].text, 'CellA CellB');

    // Leaving hover clears baseline; re-hovering with the same clipboard treats it as stale again
    nodes.get(`pm-msg-${tableKey}`).hovers.forEach(fn => fn(false, cx));
    assert.equal(view.hoverClipboard, null);
    nodes.get(`pm-msg-${tableKey}`).hovers.forEach(fn => fn(true, cx));
    assert.equal(view.hoverClipboard, 'CellA CellB');
    rerender();
    nodes.get(`quote-btn-${tableKey}`).clicks({ stop_propagation() {} }, cx);
    assert.equal(view.quotes.length, 3);
    assert.equal(Boolean(view.quotes[2].exact), false, 'unchanged clipboard after re-hover falls back to whole message');
    view.removeQuote(view.quotes[2].id, cx);
    assert.equal(view.quotes.length, 2);

    // Also hover & quote user bubble
    const userKey = `user:${at('09:02:00')}:`;
    nodes.get(`user-msg-${userKey}`).hovers.forEach(fn => fn(true, cx));
    rerender();
    assert.equal(nodes.has(`quote-btn-${userKey}`), true);
    clipText = 'about @spec details';
    nodes.get(`quote-btn-${userKey}`).clicks({ stop_propagation() {} }, cx);
    assert.equal(view.quotes.length, 3);
    assert.equal(view.quotes[2].text, 'about @spec details');

    // Multi-quote bar renders above textarea; removing middle quote leaves 2 quotes; drafts persist on reload
    rerender();
    assert.equal(nodes.has('say-quotes'), true);
    assert.equal(nodes.has('say-quote-0'), true);
    assert.equal(nodes.has('say-quote-1'), true);
    assert.equal(nodes.has('say-quote-2'), true);
    view.hoverKey = 'tip:say-quote-x-1';
    rerender();
    assert.equal(nodes.get('hover-tip-say-quote-x-1')?.allTexts().join(' '), 'Remove quote');
    view.hoverKey = '';
    rerender();
    nodes.get('say-quote-x-1').clicks({ stop_propagation() {} }, cx);
    assert.equal(view.quotes.length, 2);
    view.quotes = [];
    view.showMainDraft();
    assert.equal(view.quotes.length, 2, 'quotes survive draft reload');

    // Switch to zh: UI strings & provenance follow config lang
    view.state.lang = 'zh';
    view.hoverKey = 'tip:say-quote-x-0';
    rerender();
    assert.equal(nodes.get('hover-tip-say-quote-x-0')?.allTexts().join(' '), '移除引用');
    view.hoverKey = '';
    rerender();
    nodes.get(`pm-msg-${tableKey}`).hovers.forEach(fn => fn(true, cx));
    view.hoverKey = `tip:quote-btn-${tableKey}`;
    rerender();
    assert.equal(nodes.get(`hover-tip-quote-btn-${tableKey}`)?.allTexts().join(' '), '引用整条消息');
    view.hoverKey = '';
    rerender();

    // (3) Send with quotes -> sends formatted provenance + body to PM terminal, clears quotes, shows clickable bubble-quote cards
    view.input.__type('Here is my reply');
    view.draft = view.input.value();
    view.sendMain(cx);
    await new Promise(r => setTimeout(r, 10));
    assert.equal(sentCmds.length, 1);
    const wire = sentCmds[0][sentCmds[0].length - 1];
    assert.ok(wire.includes(`(quote:${encodeURIComponent(foldKey)})`));
    assert.ok(wire.includes('Here is my reply'));
    assert.equal(view.quotes.length, 0);

    // Log receives sent message; bubble renders clickable quote card pointing back to folded reply -> click unfolds, scrolls & flashes!
    view.pending = [];
    view.events = [...view.events, { at: at('09:05:00'), type: 'user', text: wire }];
    rerender();
    const sentUserKey = `user:${at('09:05:00')}:`;
    const quoteCard = nodes.get(`bubble-quote-${sentUserKey}-0`);
    assert.ok(quoteCard, 'sent user bubble renders clickable quote card');
    view.hoverKey = `tip:bubble-quote-${sentUserKey}-0`;
    rerender();
    assert.ok((nodes.get(`hover-tip-bubble-quote-${sentUserKey}-0`)?.allTexts().join(' ') || '').includes('跳回原文'));
    view.hoverKey = '';
    rerender();
    scrolledTo.length = 0;
    nodes.get(`bubble-quote-${sentUserKey}-0`).clicks({ stop_propagation() {} }, cx);
    assert.equal(view.unfolded.get(foldKey), true, 'clicking quote unfolds folded target reply');
    assert.equal(view.flash, foldKey, 'clicking quote flashes target message');
    assert.ok(scrolledTo.length > 0, 'clicking quote scrolls to target row');

    // (4) Extension seam: future TextView selection event shows icon-only selection bar (zh & en), Esc dismisses, click adds quote
    const selTv = textViews.get(`md-${tableKey}-p0`);
    assert.equal(typeof selTv?.onSel, 'function', 'when Herdr exposes on_selection_change, TextView wires selection seam');
    view.onTextSelection({ key: tableKey, kind: 'pm', author: 'PM', at: at('09:04:00'), time: '09:04' }, { text: 'Summary slice', bounds: { x: 20, y: 30, width: 50, height: 18 } }, cx);
    view.hoverKey = 'tip:selection-quote-btn';
    rerender();
    assert.equal(nodes.get('hover-tip-selection-quote-btn')?.allTexts().join(' '), '引用所选');
    view.state.lang = 'en';
    rerender();
    assert.equal(nodes.get('hover-tip-selection-quote-btn')?.allTexts().join(' '), 'Quote selection');
    view.hoverKey = '';
    view.escape({ keystroke: 'escape' }, cx);
    assert.equal(view.selectionBar, null, 'Esc clears selection bar first');
    view.onTextSelection({ key: tableKey, kind: 'pm', author: 'PM', at: at('09:04:00'), time: '09:04' }, { text: 'Summary slice' }, cx);
    rerender();
    nodes.get('selection-quote-btn').clicks({ stop_propagation() {} }, cx);
    assert.equal(view.quotes.length, 1);
    assert.equal(view.quotes[0].text, 'Summary slice');
    assert.equal(view.quotes[0].exact, true);
  } finally {
    globalThis.localStorage = prevStorage;
  }
});

test('Interface H: change view pure state machine, hunk grouping, pagination, escapeStep & i18n', () => {
  const {
    CHANGE_STRINGS, word, projectChangeArgv, isOldPmCommand, escapeStep,
    createChangeState, openChangeView, closeChangeView, enterChangeFiles, enterChangeFileDiff,
    stepBackChangeView, appendDiffPage, groupDiffHunks, toggleDiffHunk, toggleAllDiffHunks,
    splitFilePath, changeStateMessage, formatCommitDate,
  } = model;

  // Argv builders & old remote detection
  assert.deepEqual(projectChangeArgv('dudu', 't-1'), ['project', 'change', 'dudu', 't-1']);
  assert.deepEqual(projectChangeArgv('dudu', 't-1', { commit: 'abc1234', file: 'src/a.js', offset: 400, limit: 200 }),
    ['project', 'change', 'dudu', 't-1', '--commit', 'abc1234', '--file', 'src/a.js', '--offset', '400', '--limit', '200']);
  assert.deepEqual(projectChangeArgv('dudu', 't-1', { commitsLimit: 50 }),
    ['project', 'change', 'dudu', 't-1', '--commits-limit', '50']);
  assert.equal(isOldPmCommand({ code: 2, stderr: "pm.py: error: argument project_cmd: invalid choice: 'change'" }), true);

  // Esc ordering: change sits below search/agentWindow/bringBack and above detail/doc/listOpen
  assert.equal(escapeStep({ bringBack: true, change: true, detail: true }), 'bringBack');
  assert.equal(escapeStep({ search: true, change: true, detail: true }), 'search');
  assert.equal(escapeStep({ agentWindows: 1, change: true, detail: true }), 'agentWindow');
  assert.equal(escapeStep({ change: true, detail: true, doc: true, listOpen: true }), 'change');
  assert.equal(escapeStep({ change: false, detail: true, listOpen: true }), 'detail');

  // 3-level state machine + 1-level-back stepping
  let st = openChangeView(createChangeState(), 't-1');
  assert.equal(st.open, true);
  assert.equal(st.level, 'commits');
  st = enterChangeFiles(st, { scope: 'commit', commitHash: 'aaa1111' });
  assert.equal(st.level, 'files');
  assert.equal(st.scope, 'commit');
  st = enterChangeFileDiff(st, { path: 'src/app.js', status: 'M' });
  assert.equal(st.level, 'diff');
  assert.equal(st.filePath, 'src/app.js');

  let back = stepBackChangeView(st);
  assert.equal(back.handled, true);
  assert.equal(back.state.level, 'files');
  back = stepBackChangeView(back.state);
  assert.equal(back.handled, true);
  assert.equal(back.state.level, 'commits');
  back = stepBackChangeView(back.state);
  assert.equal(back.handled, true);
  assert.equal(back.state.open, false);
  assert.equal(stepBackChangeView(back.state).handled, false);
  assert.equal(closeChangeView(st).open, false);

  // Pagination append & hunk grouping/folding
  const page1 = { offset: 0, limit: 2, total_lines: 4, has_more: true, next_offset: 2, truncated: false, truncated_lines: false,
    lines: [{ kind: 'hunk', text: '@@ -1,2 +1,3 @@' }, { kind: 'ctx', text: 'a', old_line: 1, new_line: 1 }] };
  const page2 = { offset: 2, limit: 2, total_lines: 4, has_more: false, next_offset: null, truncated: false, truncated_lines: true,
    lines: [{ kind: 'del', text: 'b', old_line: 2 }, { kind: 'add', text: 'b2', new_line: 2 }] };
  const merged = appendDiffPage(page1, page2);
  assert.equal(merged.lines.length, 4);
  assert.equal(merged.has_more, false);
  assert.equal(merged.truncated_lines, true);

  const grouped = groupDiffHunks([{ kind: 'meta', text: 'rename from old.js' }, ...merged.lines]);
  assert.equal(grouped.meta.length, 1);
  assert.equal(grouped.hunks.length, 1);
  assert.equal(grouped.hunks[0].insertions, 1);
  assert.equal(grouped.hunks[0].deletions, 1);

  let folded = toggleDiffHunk({}, 'hunk-0');
  assert.equal(folded['hunk-0'], true);
  folded = toggleDiffHunk(folded, 'hunk-0');
  assert.equal(Boolean(folded['hunk-0']), false);
  folded = toggleAllDiffHunks({}, grouped.hunks);
  assert.equal(folded['hunk-0'], true);
  assert.deepEqual(toggleAllDiffHunks(folded, grouped.hunks), {});

  assert.deepEqual(splitFilePath('mods/pm-project/main.js'), { dir: 'mods/pm-project', name: 'main.js' });
  assert.deepEqual(splitFilePath('README.md'), { dir: '', name: 'README.md' });
  assert.equal(formatCommitDate('2026-11-22T09:15:00-05:00', '2026-11-22'), '09:15');
  assert.equal(formatCommitDate('2026-11-21T09:15:00-05:00', '2026-11-22'), '11-21 09:15');

  // En & zh CHANGE_STRINGS parity and non-ok messages
  assert.deepEqual(Object.keys(CHANGE_STRINGS.en).sort(), Object.keys(CHANGE_STRINGS.zh).sort());
  for (const state of ['no_branch', 'branch_deleted', 'empty', 'base_missing', 'no_repo', 'not_git', 'no_git']) {
    const enMsg = changeStateMessage('en', { state, branch: 'dev/x', base: 'main' });
    const zhMsg = changeStateMessage('zh', { state, branch: 'dev/x', base: 'main' });
    assert.ok(enMsg.length > 0 && zhMsg.length > 0 && enMsg !== zhMsg);
  }

  // Dynamic line-number column width scales cleanly for 4+ digit files and obsolete helpers are removed
  assert.equal(model.diffLineNumWidth([]), 27);
  assert.equal(model.diffLineNumWidth([{ old_line: 999, new_line: 100 }]), 27);
  assert.equal(model.diffLineNumWidth([{ old_line: 1000, new_line: 20 }]), 34);
  assert.equal(model.diffLineNumWidth([{ new_line: 12345 }]), 42);
  assert.equal(model.diffLineNumWidth([{ old_line: 100000 }]), 49);
  assert.equal(model.diffArgv, undefined);
  assert.equal(model.STRINGS.en.noDiff, undefined);
  assert.equal(model.STRINGS.en.diffTab, undefined);
  assert.equal(model.STRINGS.en.remoteDiff, undefined);
});

test('PmProject Change View: 3-level drill-down, hunk folding, pagination, Esc stack, remote & deleted-branch fallback (en & zh)', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '').replace('export default class PmProject extends View', 'return class');

  const nodes = new Map();
  const allTexts = rec => [...rec.texts, ...rec.kids.flatMap(allTexts)];
  const makeEl = () => {
    const rec = { id: '', texts: [], kids: [], clicks: null, tips: [], bg: null, w: null, svgs: [] };
    const proxy = new Proxy(function () {}, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') {
            if (typeof args[0] === 'string') rec.texts.push(args[0]);
            else if (args[0]?.__rec) rec.kids.push(args[0].__rec);
          } else if (key === 'children') {
            for (const c of args[0] || []) if (c?.__rec) rec.kids.push(c.__rec);
          } else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'tooltip') rec.tips.push(String(args[0] || ''));
          else if (key === 'bg') rec.bg = args[0];
          else if (key === 'w') rec.w = args[0];
          else if (key === 'when' && args[0]) return args[1](proxy) || proxy;
          return proxy;
        };
      },
    });
    return proxy;
  };
  const blank = new Proxy(function () {}, { get: (_, key) => (key === Symbol.toPrimitive ? () => 0 : blank), apply: () => blank });
  const execCalls = [];
  let mode = 'branch'; // 'branch' | 'deleted' | 'no_branch' | 'old_remote'
  const hash1 = '1111111111111111111111111111111111111111';
  const hashM = 'mmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmm'.replace(/m/g, 'a');
  const hash2 = '2222222222222222222222222222222222222222';
  const stubs = {
    View: class {},
    ...model,
    ...stepsView,
    renderThreadChangeView: changeView.renderThreadChangeView,
    TextView: { markdown: (_id, md) => makeEl().child(md) },
    Textarea: { new: () => makeEl() },
    Input: { new: () => makeEl() },
    Popup: { new: (id, trigger) => makeEl().id(id).child(trigger) },
    execPython: async (_exec, argv, opts) => stubs.exec('python3', argv, opts),
    div: makeEl, v_flex: makeEl, h_flex: makeEl,
    svg: path => { const el = makeEl(); el.__rec.svgs.push(String(path || '')); return el; },
    image: makeEl,
    appHome: () => '/app', home: () => '/Users/me',
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    appWindow: () => ({ platform: 'macos' }),
    terminals: () => [], agents: () => [], panes: () => [], spaces: () => [],
    theme: () => ({
      background: '#111111', chrome: '#181818', surface: '#202020', raised: '#282828', hover: '#303030',
      border: '#383838', foreground: '#eeeeee', muted: '#bbbbbb', dim: '#888888',
      accent: '#5599ff', blocked: '#ee5555', ansi1: '#ee5555', ansi2: '#44bb66', ansi3: '#ddaa44',
    }),
    layout: () => ({ id: 'root', children: [{ id: 'pm-stage', active: 'pm-project', children: [] }] }),
    shared: () => ({ pm: 'pm-dudu' }),
    readTextFile: async () => JSON.stringify({ id: 'dudu-h', branch: 'dev/h', base: 'main', status: 'review' }),
    exec: async (command, args, options) => {
      execCalls.push({ command, args, options });
      if (mode === 'old_remote' && args?.includes('change')) {
        return { code: 2, stdout: '', stderr: "pm.py: error: argument project_cmd: invalid choice: 'change'" };
      }
      const hasCommit = args.includes('--commit') ? args[args.indexOf('--commit') + 1] : '';
      const hasFile = args.includes('--file') ? args[args.indexOf('--file') + 1] : '';
      const offset = args.includes('--offset') ? Number(args[args.indexOf('--offset') + 1]) : 0;
      if (hasFile) {
        const commitObj = hasCommit === hashM
          ? { hash: hashM, short: 'aaaaaaa', subject: "Merge branch 'main'", author: 'Alice', date: '2026-11-22T00:42:00-05:00', files: 1, insertions: 2, deletions: 1, merge: true, merges_base: true }
          : null;
        if (offset === 0) {
          return { code: 0, stderr: '', stdout: JSON.stringify({
            state: 'ok', project: 'dudu', task: 'dudu-h', branch: 'dev/h', base: 'main',
            commit: commitObj,
            file: { path: hasFile, old_path: null, status: 'M', insertions: 2, deletions: 1, binary: false },
            binary: false, offset: 0, limit: 400, total_lines: 5, has_more: true, next_offset: 3,
            truncated: false, truncated_lines: false,
            lines: [
              { kind: 'hunk', text: '@@ -1,2 +1,3 @@' },
              { kind: 'del', text: 'old line', old_line: 1 },
              { kind: 'add', text: 'new line', new_line: 1 },
            ],
          }) };
        }
        return { code: 0, stderr: '', stdout: JSON.stringify({
          state: 'ok', project: 'dudu', task: 'dudu-h', branch: 'dev/h', base: 'main',
          commit: commitObj,
          file: { path: hasFile, old_path: null, status: 'M', insertions: 2, deletions: 1, binary: false },
          binary: false, offset: 3, limit: 400, total_lines: 5, has_more: false, next_offset: null,
          truncated: false, truncated_lines: false,
          lines: [
            { kind: 'hunk', text: '@@ -12344,1 +12345,2 @@' },
            { kind: 'add', text: 'second hunk line', new_line: 12345 },
          ],
        }) };
      }
      if (hasCommit) {
        const isBaseMerge = hasCommit === hashM;
        return { code: 0, stderr: '', stdout: JSON.stringify({
          state: 'ok', project: 'dudu', task: 'dudu-h', branch: 'dev/h', base: 'main',
          commit: {
            hash: hasCommit, short: hasCommit.slice(0, 7),
            subject: isBaseMerge ? "Merge branch 'main'" : 'feat: add change view',
            author: 'Alice', date: '2026-11-22T00:40:00-05:00',
            files: 1, insertions: 2, deletions: 1, merge: isBaseMerge, merges_base: isBaseMerge,
          },
          files: [{ path: 'mods/pm-project/change_view.js', old_path: null, status: 'M', insertions: 2, deletions: 1, binary: false }],
          insertions: 2, deletions: 1,
        }) };
      }
      if (mode === 'deleted') {
        return { code: 0, stderr: '', stdout: JSON.stringify({
          state: 'branch_deleted', message: 'Branch dev/h is no longer in the repository.',
          project: 'dudu', task: 'dudu-h', branch: 'dev/h', base: 'main',
          commits: [], more_commits: false, files: [], insertions: 0, deletions: 0, uncommitted: -1,
          recorded_commit: { hash: hash2, short: '2222222', subject: 'merge dev/h', author: 'Alice', date: '2026-11-22T00:45:00-05:00', files: 1, insertions: 2, deletions: 1 },
        }) };
      }
      if (mode === 'no_branch') {
        return { code: 0, stderr: '', stdout: JSON.stringify({
          state: 'no_branch', message: 'This thread has no branch recorded.',
          project: 'dudu', task: 'dudu-h', branch: '', base: 'main',
          commits: [], more_commits: false, files: [], insertions: 0, deletions: 0, uncommitted: -1, recorded_commit: null,
        }) };
      }
      return { code: 0, stderr: '', stdout: JSON.stringify({
        state: 'ok', message: '', project: 'dudu', task: 'dudu-h', branch: 'dev/h', base: 'main',
        commits: [
          { hash: hashM, short: 'aaaaaaa', subject: "Merge branch 'main'", author: 'Alice', date: '2026-11-22T00:42:00-05:00', files: 3, insertions: 20, deletions: 5, merge: true, merges_base: true },
          { hash: hash1, short: '1111111', subject: 'feat: add change view', author: 'Alice', date: '2026-11-22T00:40:00-05:00', files: 1, insertions: 2, deletions: 1, merge: false, merges_base: false },
        ],
        more_commits: false,
        files: [
          { path: 'mods/pm-project/change_view.js', old_path: null, status: 'M', insertions: 2, deletions: 1, binary: false },
          { path: 'assets/logo.png', old_path: null, status: 'A', insertions: 0, deletions: 0, binary: true },
        ],
        insertions: 2, deletions: 1, uncommitted: 2, recorded_commit: null,
      }) };
    },
  };
  const scope = new Proxy(stubs, {
    has: (target, name) => name in target || !(name in globalThis),
    get: (target, name) => (name in target ? target[name] : name === Symbol.unscopables ? undefined : blank),
  });
  const Mod = new Function('scope', `with (scope) { ${source} }`)(scope);
  const cx = { spawn: f => f(cx), notify() {}, stop_propagation() {}, timer: { after() {} } };
  const pm = { name: 'pm-dudu', project: 'dudu', conversation: '/here/projects/dudu/conversation.jsonl' };
  const view = Object.assign(Object.create(Mod.prototype), {
    machine: '', pmName: 'pm-dudu', stateFor: '',
    state: { lang: 'zh', pms: [pm], tasks: [{ id: 'dudu-h', title: '改动视图', pm: 'pm-dudu', branch: 'dev/h', base: 'main', status: 'review' }] },
    lang: 'zh', events: [], pending: [], pastes: [], items: [], wide: false, listShown: true,
    files: [], threadFiles: [], draft: '', threadDraft: '',
    input: { value: () => '', set_value() {}, set_selected_range() {} },
    threadInput: { value: () => '', set_value() {}, set_selected_range() {} },
    thread: 'dudu-h', threadTask: null, detail: true, outgoing: new Map(),
    change: model.createChangeState(), remoteNoChange: '',
    scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, changeScroll: { scroll_to_item() {} },
    keyFocus: { focus() {} }, terms: () => [], live: () => [],
  });
  const renderPanel = () => { nodes.clear(); return view.panel(stubs.theme(), '2026-11-22', 360, cx).__rec; };

  // 1. Detail panel has thread-diff button; click opens Change View (commits level).
  renderPanel();
  assert.ok(nodes.has('thread-diff'));
  nodes.get('thread-diff').clicks(null, cx);
  await new Promise(r => setTimeout(r, 15));
  let root = renderPanel();
  assert.equal(root.id, 'thread-change-view');
  assert.ok(nodes.has('change-refresh'));
  assert.ok(nodes.get('change-refresh').kids.some(k => k.svgs.some(s => s.endsWith('/refresh.svg'))), 'refresh uses refresh.svg, not reattach');
  assert.ok(nodes.has('change-uncommitted'));
  assert.ok(nodes.has('change-scope-all'));
  assert.ok(nodes.has('change-commit-1111111'));
  assert.equal(nodes.has('change-commit-aaaaaaa'), false, 'base-merge commits are folded by default');
  assert.ok(nodes.has('change-base-merges-toggle'));
  assert.ok(allTexts(nodes.get('change-base-merges-toggle')).some(s => s.includes('1 次合并 main')));
  nodes.get('change-base-merges-toggle').clicks(null, cx);
  root = renderPanel();
  assert.ok(nodes.has('change-commit-aaaaaaa'), 'expanding toggle reveals base-merge commit');
  assert.ok(allTexts(nodes.get('change-commit-aaaaaaa')).some(s => s.includes('合并 main')));
  nodes.get('change-commit-aaaaaaa').clicks(null, cx);
  await new Promise(r => setTimeout(r, 15));
  root = renderPanel();
  assert.ok(nodes.has('change-merge-note'), 'merge commit files view explains first-parent source');
  assert.ok(allTexts(nodes.get('change-merge-note')).some(s => s.includes('合并 main')));
  nodes.get('change-file-0').clicks(null, cx);
  await new Promise(r => setTimeout(r, 15));
  root = renderPanel();
  assert.ok(nodes.has('change-merge-note'), 'merge commit diff view explains first-parent source');
  view.stepBackThreadChange(cx);
  view.stepBackThreadChange(cx);
  root = renderPanel();
  assert.ok(allTexts(root).some(s => s.includes('分支整体改动')));

  // 2. Click commit -> files level; click file -> diff level; verify colored add/del + hunk fold + load more.
  nodes.get('change-commit-1111111').clicks(null, cx);
  await new Promise(r => setTimeout(r, 15));
  root = renderPanel();
  assert.equal(view.change.level, 'files');
  assert.ok(nodes.has('change-file-0'));

  nodes.get('change-file-0').clicks(null, cx);
  await new Promise(r => setTimeout(r, 15));
  root = renderPanel();
  assert.equal(view.change.level, 'diff');
  assert.ok(nodes.has('change-line-0-0'), 'add/del lines rendered');
  assert.ok(nodes.get('change-line-0-0').bg, 'del line has tinted background');
  assert.ok(nodes.get('change-line-0-1').bg, 'add line has tinted background');
  assert.ok(nodes.has('change-load-more'), 'pagination button shown when has_more=true');

  // Toggle hunk folded & back
  nodes.get('change-hunk-head-0').clicks(null, cx);
  renderPanel();
  assert.equal(nodes.has('change-line-0-0'), false, 'folded hunk hides lines');
  nodes.get('change-toggle-all').clicks(null, cx);
  renderPanel();
  assert.ok(nodes.has('change-line-0-0'), 'toggle-all expands all hunks');

  // Load more lines & verify local timeout (30s) and dynamic 5-digit line number column width
  const localChangeCall = execCalls.find(c => c.command === 'python3' && c.args.includes('change'));
  assert.equal(localChangeCall?.options?.timeout, model.CHANGE_TIMEOUT_LOCAL_MS);
  nodes.get('change-load-more').clicks(null, cx);
  await new Promise(r => setTimeout(r, 15));
  renderPanel();
  assert.ok(nodes.has('change-hunk-1'), 'second page appends hunk 1');
  assert.equal(nodes.has('change-load-more'), false);
  assert.equal(nodes.get('change-line-1-0').kids[0].w, 42);
  assert.equal(nodes.get('change-line-1-0').kids[1].w, 42);

  // 3. Esc steps back one level at a time: diff -> files -> commits -> detail -> narrow list.
  const pressEsc = () => view.escape({ keystroke: 'escape' }, cx);
  pressEsc();
  assert.equal(view.change.open, true);
  assert.equal(view.change.level, 'files');
  pressEsc();
  assert.equal(view.change.open, true);
  assert.equal(view.change.level, 'commits');
  pressEsc();
  assert.equal(view.change.open, false);
  assert.equal(view.detail, true);
  pressEsc();
  assert.equal(view.detail, false);

  // 4. Deleted branch with recorded_commit fallback (English UI).
  mode = 'deleted';
  view.lang = 'en';
  view.state.lang = 'en';
  view.detail = true;
  view.resetThreadChange();
  view.openThreadChange(cx);
  await new Promise(r => setTimeout(r, 15));
  root = renderPanel();
  assert.ok(allTexts(root).some(s => s.includes('no longer in the repository')));
  assert.ok(nodes.has('change-recorded-commit'));
  nodes.get('change-recorded-commit').clicks(null, cx);
  await new Promise(r => setTimeout(r, 15));
  renderPanel();
  assert.equal(view.change.level, 'files');
  assert.ok(nodes.has('change-file-0'));

  // 5. No branch explanation.
  mode = 'no_branch';
  view.resetThreadChange();
  view.openThreadChange(cx);
  await new Promise(r => setTimeout(r, 15));
  root = renderPanel();
  assert.ok(allTexts(root).some(s => s.includes('no branch recorded')));

  // 6. Remote project runs through remotePmArgv (`{ on: 'mbp' }`), and old remote hides diff quietly.
  mode = 'branch';
  view.machine = 'mbp';
  view.stateFor = 'mbp';
  view.pmName = 'mbp/pm-dudu';
  view.remoteNoChange = '';
  view.resetThreadChange();
  view.openThreadChange(cx);
  await new Promise(r => setTimeout(r, 15));
  const remoteCall = execCalls.find(c => c.options?.on === 'mbp' && c.command === 'sh' && c.args.includes('change'));
  assert.ok(remoteCall, 'remote project runs project change via remotePmArgv');
  assert.equal(remoteCall.options?.timeout, model.CHANGE_TIMEOUT_REMOTE_MS);

  mode = 'old_remote';
  view.resetThreadChange();
  view.openThreadChange(cx);
  await new Promise(r => setTimeout(r, 15));
  assert.equal(view.isThreadChangeOpen(), false);
  assert.equal(view.remoteNoChange, 'mbp');
  renderPanel();
  assert.equal(nodes.has('thread-diff'), false, 'old remote pm.py quietly hides thread-diff icon');
});

test('real pm.py subprocess integration: project change commits, files, paginated diff, and deleted branch', async () => {
  const { execFileSync } = await import('node:child_process');
  const { mkdtempSync, mkdirSync, writeFileSync, rmSync } = await import('node:fs');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const { fileURLToPath } = await import('node:url');

  const tmp = mkdtempSync(join(tmpdir(), 'pm-proj-h-'));
  const pmHome = join(tmp, 'ledger');
  const repo = join(tmp, 'repo');
  const pmPy = fileURLToPath(new URL('../pm-dash/skill/scripts/pm.py', import.meta.url));
  const env = { ...process.env, PM_HOME: pmHome };
  delete env.HERDR_PANE_ID;
  delete env.HC_TERMINAL_ID;

  try {
    mkdirSync(join(pmHome, 'pms'), { recursive: true });
    mkdirSync(join(pmHome, 'tasks'), { recursive: true });
    mkdirSync(repo, { recursive: true });

    const git = (...args) => execFileSync('git', [
      '-C', repo, '-c', 'user.name=Tester', '-c', 'user.email=tester@example.com', '-c', 'commit.gpgsign=false', ...args,
    ], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();

    git('init', '-b', 'main');
    writeFileSync(join(repo, 'app.txt'), 'a\nb\n', 'utf8');
    git('add', '-A');
    git('commit', '-m', 'init');

    git('checkout', '-b', 'dev/h');
    writeFileSync(join(repo, 'app.txt'), 'a\nb2\nc\n', 'utf8');
    writeFileSync(join(repo, 'long.txt'), Array.from({ length: 25 }, (_, i) => `row-${i}`).join('\n') + '\n', 'utf8');
    git('add', '-A');
    git('commit', '-m', 'feat: add long file');
    const c1 = git('rev-parse', 'HEAD');
    git('checkout', 'main');

    writeFileSync(join(pmHome, 'pms', 'demo.json'), JSON.stringify({ name: 'pm-demo', project: 'demo', repo }));
    writeFileSync(join(pmHome, 'tasks', 'demo-1.json'), JSON.stringify({
      id: 'demo-1', title: 'Demo change', project: 'demo', repo, branch: 'dev/h', base: 'main', commit: c1, status: 'review',
    }));

    const runPm = (...args) => JSON.parse(execFileSync('python3', [pmPy, 'project', 'change', 'demo', 'demo-1', ...args], { env, encoding: 'utf8' }));
    const ov = runPm();
    assert.equal(ov.state, 'ok');
    assert.equal(ov.commits[0].hash, c1);
    assert.deepEqual(ov.files.map(f => f.path).sort(), ['app.txt', 'long.txt']);

    const p1 = runPm('--file', 'long.txt', '--offset', '0', '--limit', '10');
    assert.equal(p1.lines.length, 10);
    assert.equal(p1.has_more, true);
    const p2 = runPm('--file', 'long.txt', '--offset', String(p1.next_offset), '--limit', '20');
    assert.equal(p2.has_more, false);
    assert.equal(p1.lines.length + p2.lines.length, p1.total_lines);

    git('branch', '-D', 'dev/h');
    const deleted = runPm();
    assert.equal(deleted.state, 'branch_deleted');
    assert.equal(deleted.recorded_commit.hash, c1);
    const recDiff = runPm('--commit', c1, '--file', 'app.txt');
    assert.ok(recDiff.lines.some(l => l.kind === 'add' && l.text === 'b2'));
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test('Threads 4 model helpers: resolveHelperResultPath and window entry display metadata', () => {
  const { resolveHelperResultPath, toggleAgentWindow, threadAgents } = model;
  assert.equal(resolveHelperResultPath('results/h1.md', { ledgerHome: '/tmp/ledger', slug: 'dudu' }),
    '/tmp/ledger/projects/dudu/results/h1.md');
  assert.equal(resolveHelperResultPath('~/.dudu/projects/dudu/results/h1.md', { ledgerHome: '/tmp/ledger', slug: 'dudu' }),
    '/tmp/ledger/projects/dudu/results/h1.md');
  assert.equal(resolveHelperResultPath('/abs/path/h1.md', { ledgerHome: '/tmp/ledger', slug: 'dudu' }),
    '/abs/path/h1.md');
  assert.equal(resolveHelperResultPath('', { ledgerHome: '/tmp/ledger', slug: 'dudu' }), '');

  const agents = threadAgents({
    id: 't1', title: 'Impl', status: 'in_progress', pane: 'hc:tw1',
    engine: { kind: 'claude', model: 'opus' }, context_tokens: 45_000,
    helpers: [{ id: 'h1', status: 'done', summary: 'Checked logs', prompt: 'Check logs', result: 'results/h1.md' }],
  }, { terms: [{ address: 'tw1', state: 'live', labels: { task: 't1' }, program: { key: 'claude' } }], lang: 'en' });
  const winOpen = toggleAgentWindow([], agents.all.find(a => a.role === 'helper'));
  assert.equal(winOpen.opened.summary, 'Checked logs');
  assert.equal(winOpen.opened.prompt, 'Check logs');
  assert.equal(winOpen.opened.resultPath, 'results/h1.md');
  assert.equal(winOpen.opened.roleLabel, 'helper');
});

test('Threads 4 UI: epic groups, smooth Bezier wires, hover cards, detail two-layer steps, agent small windows & Esc stack (en & zh)', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '')
    .replace('export default class PmProject extends View', 'return class');

  const nodes = new Map();
  const overlayCalls = [];
  const closedOverlays = [];
  const runCalls = [];
  let sharedMap = { 'pm-project': { pm: 'pm-dudu' } };
  let winProps = {};

  const makeEl = () => {
    const rec = { id: '', texts: [], kids: [], clicks: null, hover: null, wheel: null, keyDown: null, tips: [], svgs: [], _svg: '', sizes: [], bg: '', textColor: '' };
    const allTexts = r => [...r.texts, ...r.kids.flatMap(allTexts)];
    const allSvgs = r => [...r.svgs, ...r.kids.flatMap(allSvgs)];
    const proxy = new Proxy(function () {}, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        if (key === '__svg') return rec._svg;
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
          } else if (key === 'size') rec.sizes.push(args[0]);
          else if (key === 'bg') rec.bg = args[0];
          else if (key === 'text_color') rec.textColor = args[0];
          else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'on_hover') rec.hover = args[0];
          else if (key === 'on_scroll_wheel') rec.wheel = args[0];
          else if (key === 'on_key_down') rec.keyDown = args[0];
          else if (key === 'tooltip') rec.tips.push(args[0]);
          else if (key === 'when' && args[0]) args[1](proxy);
          return proxy;
        };
      },
      apply: () => proxy,
    });
    rec.allTexts = () => allTexts(rec);
    rec.allSvgs = () => allSvgs(rec);
    return proxy;
  };
  const svgStub = path => {
    const el = makeEl();
    if (path) {
      el.__rec._svg = String(path);
      el.__rec.svgs.push(String(path));
    }
    return el;
  };
  let nextOv = 1;
  let sessionMode = 'ok';
  const liveTerms = [
    { address: 'tw1', state: 'live', labels: { task: 't1' }, program: { key: 'claude', name: 'Claude Code' } },
    { address: 'tr1', state: 'live', labels: { task: 't1-review' }, program: { key: 'codex', name: 'Codex' } },
    { address: 'ts1', state: 'live', labels: { task: 't_single' }, program: { key: 'claude', name: 'Claude Code' } },
  ];
  const stubs = {
    View: class {}, ...model, ...stepsView,
    div: makeEl, h_flex: makeEl, v_flex: makeEl, image: makeEl, svg: svgStub,
    TextView: { markdown: (_id, md) => makeEl().child(String(md || '')) },
    TextareaState: { new: () => ({ _h: {}, set_auto_grow() {}, on(k, f) { this._h[k] = f; }, value: () => '', set_value() {}, set_selected_range() {}, focus() {} }) },
    Textarea: { new: () => makeEl() },
    InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, focus() {} }) },
    Input: { new: () => makeEl() },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) },
    Scrollbar: { vertical: id => makeEl().id(`scrollbar:${id}`) },
    Popup: { new: (id, trig) => makeEl().id(id).child(trig) },
    execPython: async (_exec, argv, opts) => stubs.exec('python3', argv, opts),
    theme: () => ({
      canvas: '#111111', surface: '#181818', raised: '#222222', chrome: '#161616', hover: '#2a2a2a', popover: '#222222',
      border: '#333333', input: '#3a3a3a', foreground: '#eeeeee', background: '#111111',
      muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', accent_foreground: '#ffffff',
      blocked: '#ff5f56', ansi2: '#27c93f', ansi3: '#f5a623', solid: '#eeeeee', solid_foreground: '#111111',
      working: '#e5a93c',
    }),
    home: () => '/Users/test', appHome: () => '/app',
    appWindow: () => ({ platform: 'macos' }),
    terminals: () => liveTerms, agents: () => liveTerms.map(t => ({ address: t.address, status: 'working' })),
    panes: () => [{ pane: 'hc:tpm', terminal: 'tpm', space: 'pm-hub' }],
    spaces: () => [{ id: 'pm-hub', tabs: [] }],
    shared: k => sharedMap[k],
    setShared: (k, v) => { sharedMap[k] = v; },
    props: () => winProps,
    openOverlay: spec => {
      const id = `ov-${nextOv++}`;
      overlayCalls.push({ id, spec });
      return id;
    },
    closeOverlay: id => { closedOverlays.push(id); },
    layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run: (cmd, args) => { runCalls.push([cmd, args]); },
    watchFolder: () => new Promise(() => {}),
    readTextFile: async p => {
      if (p.endsWith('results/h1.md')) return '# Helper Conclusion\n\nAll checks verified cleanly.';
      return '';
    },
    exec: async (_cmd, args) => {
      if (args?.includes('session')) {
        if (sessionMode === 'unavailable') return { code: 2, stdout: '', stderr: "invalid choice: 'session'" };
        return {
          code: 0,
          stdout: JSON.stringify({
            items: [{ timestamp: '2026-11-21T10:00:00Z', type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: 'Working on render pass.' }] } }],
            from: 0, offset: 1, earlier: false,
          }),
          stderr: '',
        };
      }
      if (args?.includes('send')) return { code: 0, stdout: '', stderr: '' };
      return { code: 0, stdout: JSON.stringify({ events: [], from: 0, offset: 0, earlier: false }), stderr: '' };
    },
  };

  const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
  const timers = [];
  const makeTimer = fn => {
    const entry = { fn, cancelled: false, cancel() { this.cancelled = true; } };
    timers.push(entry);
    return entry;
  };
  const cx = {
    focus_handle: () => ({ focus() {} }),
    spawn: fn => fn(cx),
    timer: { after: (_ms, fn) => makeTimer(fn), every: () => {} },
    notify: () => {},
    stop_propagation: () => {},
  };
  const makeInput = () => ({ value: () => '', set_value() {}, set_selected_range() {}, focus() {}, on() {}, set_auto_grow() {} });

  const tasks = [
    { id: 'ep1', pm: 'pm-dudu', title: 'Threads Epic', status: 'in_progress', updated: '2026-11-21 10:00', epic: true },
    {
      id: 't1', pm: 'pm-dudu', parent: 'ep1', title: 'Render left tree and detail', status: 'review',
      branch: 'dev/t1', pane: 'hc:tw1', updated: '2026-11-21 10:05',
      engine: { kind: 'claude', model: 'opus' }, context_tokens: 52_000,
      plan: ['[x] Align design', '[>] Build UI views', 'Code review', 'Land to main'],
      subplan: ['[x] Task tree rows', '[>] Detail steps card'],
      review: { id: 't1-review', status: 'in_progress', engine: { kind: 'codex', model: 'gpt-5' }, context_tokens: 18_000 },
      helpers: [{ name: 'h1', status: 'done', summary: 'Spec confirmed', prompt: 'Check spec', result: 'results/h1.md' }],
      latest: 'Ready for UI check',
      log: [
        { n: 1, at: '2026-11-21 09:00', text: 'Started analysis' },
        { n: 2, at: '2026-11-21 09:20', text: 'Added SVGs' },
        { n: 3, at: '2026-11-21 09:40', text: 'Updated panel' },
        { n: 4, at: '2026-11-21 10:05', text: 'status=review; Ready for UI check' },
      ],
    },
    { id: 't_done', pm: 'pm-dudu', parent: 'ep1', title: 'Initial types', status: 'done', updated: '2026-11-21 08:00' },
    {
      id: 't_single', pm: 'pm-dudu', title: 'Single worker thread', status: 'in_progress',
      pane: 'hc:ts1', updated: '2026-11-21 10:02', engine: { kind: 'claude', model: 'sonnet' },
      plan: ['[x] Scaffold', '[>] Verify'],
      subplan: ['[x] Init', '[>] Run checks'],
    },
  ];
  const view = Object.assign(Object.create(Mod.prototype), {
    state: { pms: [{ name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', pane: 'hc:tpm' }], tasks, events: [], lang: 'en' },
    events: [], pending: [], seq: 0, pastes: [], error: '', logError: '',
    pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
    remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
    earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '/tmp/ledger', watching: {},
    thread: '', threadTask: null, detail: false, threadError: '', threadLog: null, threadLogKept: [],
    threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null, threadLogExpanded: false,
    epicOverrides: new Map(), expandedDone: new Set(), substepsToggle: {}, hoverKey: '',
    agentWindows: [], winSession: 'sess-1', lastWinEventSeq: 0, agentWindowSlot: 0,
    threadTab: 'log', sideTab: 'threads', librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: true,
    libraryProbed: true, libraryStale: false, libraryLoading: false, libraryAgain: false, libraryError: '',
    libraryClosed: new Set(), libraryQuery: '', libraryDropBusy: '', libraryDropError: '',
    memorySlug: 'dudu', memoryData: null, memoryRead: false, memoryStale: false, memoryLoading: false, memoryAgain: false, memoryError: '',
    memoryFoldOverrides: new Map(), memoryProjectOpen: true, memoryPersonalOpen: false, memoryCandidatesOpen: false,
    memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
    activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '',
    docShownBytes: model.DOC_INITIAL_BYTES, docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
    editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
    confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
    reattaching: '', reattachError: null, startingPm: '', startPmError: null,
    bringBackOpen: false, bringingBack: false, bringBackProgress: null,
    listShown: true, wide: true, measured: true, panelWant: null, panelDrag: null, viewWidth: 1280, gripLit: false,
    seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
    bell: null, flash: '', unfolded: new Map(), newest: '', atWork: new Set(),
    scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
    libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
    keyFocus: { focus() {} }, onStage: true, typing: '', mainKey: 'pm:pm-dudu', threadKey: '', outgoing: new Map(),
    files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
    input: makeInput(), threadInput: makeInput(), libraryInput: makeInput(), memoryInput: makeInput(), docFindInput: makeInput(),
    docNameInput: makeInput(), memDescInput: makeInput(), docEditorInput: makeInput(),
    refresh: () => {},
  });
  view.resetThreadSession();

  // 1) Left Threads tree: epic + colored summary + smooth Bezier wires + 1-line threads + agent sub-rows + unified done fold
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('epic-ep1'), true, 'container epic row rendered');
  assert.equal(nodes.has('epic-summary-ep1'), true, 'epic colored summary pills rendered');
  assert.equal(nodes.has('list-t1'), true, 'epic child thread row rendered');
  assert.deepEqual(nodes.get('list-steps-t1')?.texts, ['2/4'], 'reviewing step counts Build UI views done + Code review doing (2/4)');
  assert.equal(nodes.has('agent-row-worker:t1'), true, 'worker agent sub-row rendered');
  assert.equal(nodes.has('agent-row-review:t1-review'), true, 'reviewer agent sub-row rendered');
  assert.equal(nodes.has('agent-row-worker:t_single'), true, 'single-worker thread still renders 1 compact agent row');
  assert.equal(nodes.has('fold-done-ep1'), true, 'unified tail fold merges finished subtask + ended helper');
  assert.equal(nodes.has('fold-done-agents-t1'), false, 'epic child does not render a duplicate agent fold');
  assert.deepEqual(nodes.get('fold-done-ep1')?.texts, ['2 done']);
  assert.equal(nodes.has('list-t_done'), false, 'finished subtask hidden while fold collapsed');
  assert.equal(nodes.has('agent-row-helper:t1:h1#0'), false, 'ended helper hidden while fold collapsed');
  assert.ok(nodes.get('thread-list').allSvgs().some(s => s.endsWith('tree-branch.svg')), 'smooth Bezier SVG branch connector used');

  // Expand unified fold -> reveals BOTH finished subtask and ended helper; toggle epic collapses children
  nodes.get('fold-done-ep1').clicks({}, cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('list-t_done'), true);
  assert.equal(nodes.has('agent-row-helper:t1:h1#0'), true);
  nodes.get('epic-ep1').clicks({}, cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('list-t1'), false, 'collapsing epic hides child subtree');
  nodes.get('epic-ep1').clicks({}, cx);
  nodes.clear();
  view.render(cx);

  // 2) Hover cards on epic, thread, and agent rows; cleared on leave / scroll
  const hasAnyClick = r => Boolean(r?.clicks) || (r?.kids || []).some(hasAnyClick);
  nodes.get('list-t1').hover(true, cx);
  nodes.clear();
  view.render(cx);
  const t1HoverNode = nodes.get('hover-card-task:t1');
  const t1Hover = t1HoverNode?.allTexts().join(' ') || '';
  assert.match(t1Hover, /Steps/);
  assert.match(t1Hover, /2\/4/);
  assert.match(t1Hover, /dev\/t1/);
  assert.match(t1Hover, /Opus/);
  assert.match(t1Hover, /Context 52k/);
  assert.match(t1Hover, /Ready for UI check/);
  assert.match(t1Hover, /Build UI views/);
  assert.match(t1Hover, /Code review/);
  assert.match(t1Hover, /Land to main/);
  assert.doesNotMatch(t1Hover, /→/, 'hover card uses vertical steps, never arrow chains');
  assert.match(t1Hover, /2\/2/, 'done step folds its completed substeps into 2/2 badge');
  assert.doesNotMatch(t1Hover, /Task tree rows/, 'done step substeps stay folded in hover card');
  assert.equal(hasAnyClick(t1HoverNode), false, 'hover card is strictly read-only');
  assert.equal(t1HoverNode.allSvgs().some(s => s.endsWith('check-mark.svg')), true, 'uses same check-mark icon as detail Steps card');
  assert.equal(t1HoverNode.allSvgs().some(s => s.endsWith('spinner.svg')), true, 'uses same spinner icon as detail Steps card');
  assert.equal(t1HoverNode.allSvgs().some(s => s.endsWith('window-pop.svg')), false, 'read-only hover card omits window toggle icon');

  // Doing step expands its substeps with smooth Bezier branch connectors; long step names are never truncated
  tasks[3].plan = ['[x] Scaffold initial framework', '[>] Verify full hover card step title without clipping'];
  tasks[3].latest = 'Line one of log\nLine two collapsed';
  nodes.get('list-t_single').hover(true, cx);
  nodes.clear();
  view.render(cx);
  const singleHoverNode = nodes.get('hover-card-task:t_single');
  const singleHover = singleHoverNode?.allTexts().join(' ') || '';
  assert.match(singleHover, /Verify full hover card step title without clipping/, 'long step names are never truncated');
  assert.match(singleHover, /Init/, 'doing step expands its substeps');
  assert.match(singleHover, /Run checks/, 'doing step shows active substep');
  assert.match(singleHover, /Line one of log Line two collapsed/, 'multiline log collapses onto a single line');
  assert.equal(singleHoverNode.allSvgs().some(s => s.endsWith('tree-branch.svg')), true, 'expanded substeps use smooth Bezier branch connectors');
  assert.equal(hasAnyClick(singleHoverNode), false, 'doing hover card is strictly read-only');
  tasks[3].plan = ['[x] Scaffold', '[>] Verify'];
  delete tasks[3].latest;

  // Chinese hover card uses zh Steps header and labels
  view.state.lang = 'zh';
  nodes.get('list-t1').hover(true, cx);
  nodes.clear();
  view.render(cx);
  const t1ZhHover = nodes.get('hover-card-task:t1')?.allTexts().join(' ') || '';
  assert.match(t1ZhHover, /步骤/);
  assert.match(t1ZhHover, /自动审/);
  view.state.lang = 'en';

  nodes.get('agent-row-review:t1-review').hover(true, cx);
  nodes.clear();
  view.render(cx);
  assert.match(nodes.get('hover-card-agent:review:t1-review')?.allTexts().join(' ') || '', /Codex/);
  assert.match(nodes.get('hover-card-agent:review:t1-review')?.allTexts().join(' ') || '', /Context 18k/);
  nodes.get('thread-list').wheel({ delta: { y: 5 } }, cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('hover-card-agent:review:t1-review'), false, 'scroll clears hover card');

  // 3) Agent small-window open / close / cap-2 / LRU eviction (no terminal.peek!)
  nodes.get('agent-row-worker:t1').clicks({}, cx); // Claude worker -> chat window
  nodes.get('agent-row-review:t1-review').clicks({}, cx); // Codex reviewer -> terminal window layout
  assert.equal(overlayCalls.length, 2);
  assert.equal(overlayCalls[0].spec.kind, 'window');
  assert.equal(overlayCalls[0].spec.props.agentWindow, 'chat');
  assert.equal(overlayCalls[1].spec.kind, 'window');
  assert.equal(overlayCalls[1].spec.layout.children[1].content.terminal, 'tr1');
  assert.deepEqual(sharedMap['pm-project-win-terminals'], ['tr1'], 'opening a terminal-mode agent window publishes its address to shared');
  assert.equal(runCalls.some(([cmd]) => cmd === 'terminal.peek'), false, 'never jumps to Spaces via terminal.peek');

  // Re-click open worker closes it without killing; re-open 2 + add 3rd evicts LRU!
  nodes.get('agent-row-worker:t1').clicks({}, cx);
  assert.deepEqual(closedOverlays, ['ov-1']);
  nodes.get('agent-row-worker:t1').clicks({}, cx); // now [review:ov-2, worker:ov-3]
  view.agentWindows = model.focusAgentWindow(view.agentWindows, 'review:t1-review'); // review is newest -> worker(ov-3) is LRU!
  nodes.get('agent-row-worker:t_single').clicks({}, cx); // evicts worker:t1 (ov-3)
  assert.equal(closedOverlays.includes('ov-3'), true);
  assert.equal(view.agentWindows.length, 2);

  // 4) Minimalist Detail view: topbar + two-layer steps (done substeps folded by default, doing auto-expanded) + recent 3 single-line logs + clickable review step
  nodes.get('list-t1').clicks({}, cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('thread-back'), true);
  assert.equal(nodes.has('thread-status'), true);
  assert.equal(nodes.has('thread-title'), true);
  assert.equal(nodes.has('thread-terminal'), true);
  assert.equal(nodes.get('thread-terminal').kids[0]?.sizes[0], 14, 'detail window toggle icon uses numeric size 14');
  assert.equal(nodes.get('thread-terminal').textColor, '#aaaaaa', 'closed primary window uses muted icon tint');
  assert.equal(nodes.get('thread-terminal').bg, '');
  assert.equal(nodes.has('thread-diff'), true);
  assert.equal(nodes.has('thread-close'), true);
  assert.equal(nodes.has('thread-plan-card'), true);
  assert.equal(nodes.has('substep-fold-1'), true);
  assert.equal(nodes.has('plan-substep-1-0'), false, 'done step folds substeps by default');
  nodes.get('substep-fold-1').clicks({}, cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('plan-substep-1-0'), true, 'clicking substep fold expands folded substeps');
  assert.equal(nodes.has('plan-substep-1-1'), true);

  // Check doing step auto-expansion and active window topbar highlight on t_single (navigate back via #thread-back, click #list-t_single), then return to t1
  nodes.get('thread-back').clicks({}, cx);
  assert.equal(view.detail, false, '#thread-back returns to Threads list');
  nodes.clear();
  view.render(cx);
  nodes.get('list-t_single').clicks({}, cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.get('thread-terminal').kids[0]?.sizes[0], 14);
  assert.equal(nodes.get('thread-terminal').textColor, '#4f8cff', 'open primary window highlights topbar button in accent');
  assert.equal(nodes.get('thread-terminal').bg, model.withAlpha('#4f8cff', .14));
  assert.equal(nodes.has('plan-substep-1-0'), true, 'doing step auto-expands substeps');
  assert.equal(nodes.has('plan-substep-1-1'), true);
  nodes.get('substep-fold-1').clicks({}, cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('plan-substep-1-0'), false, 'clicking active substep fold collapses it');
  nodes.get('thread-back').clicks({}, cx);
  nodes.clear();
  view.render(cx);
  nodes.get('list-t1').clicks({}, cx);
  nodes.clear();
  view.render(cx);

  // Recent 3 log lines by default, toggle shows all 4
  assert.equal(nodes.has('thread-entry-0'), false, 'oldest 1st entry hidden in recent-3 view');
  assert.equal(nodes.has('thread-entry-4'), true);
  nodes.get('thread-log-toggle').clicks({}, cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('thread-entry-0'), false);
  assert.equal(nodes.has('thread-entry-1'), true, 'expanding log shows all 4 entries');

  // Clicking review step (#plan-step-2) in detail toggles reviewer small window (`review:t1-review` is currently open -> closes!)
  assert.equal(model.agentWindowOpen(view.agentWindows, 'review:t1-review'), true);
  nodes.get('plan-step-2').clicks({}, cx);
  assert.equal(model.agentWindowOpen(view.agentWindows, 'review:t1-review'), false);

  // 5) Small window standalone view (helper conclusion, chat transcript + mode auto-fallback + shared event bus)
  const helperProps = {
    agentWindow: 'chat', key: 'helper:h1', role: 'helper', roleLabel: 'helper', taskId: 't1',
    name: 'h1', threadTitle: 'Render left tree and detail', address: '', ended: true,
    resultPath: 'results/h1.md', summary: 'Spec confirmed', prompt: 'Check spec',
    lang: 'en', ledgerHome: '/tmp/ledger', slug: 'dudu', session: 'sess-1',
  };
  winProps = helperProps;
  const hWin = new Mod();
  hWin.init(null, cx);
  await new Promise(r => setTimeout(r, 15));
  nodes.clear();
  hWin.render(cx);
  assert.match(nodes.get('agent-win-helper:h1')?.allTexts().join(' ') || '', /Helper Conclusion/);
  assert.match(nodes.get('agent-win-helper:h1')?.allTexts().join(' ') || '', /Check spec/);

  // Unparseable Claude live session automatically falls back to terminal mode via shared event bus
  sessionMode = 'unavailable';
  winProps = {
    agentWindow: 'chat', key: 'worker:t_single', role: 'worker', roleLabel: 'worker',
    taskId: 't_single', targetId: 't_single', name: 't_single', threadTitle: 'Single worker thread',
    address: 'ts1', kind: 'claude', canSwitchMode: true, overlay: 'ov-4', lang: 'en', session: 'sess-1',
  };
  const cWin = new Mod();
  cWin.init(null, cx);
  await new Promise(r => setTimeout(r, 15));
  assert.equal(sharedMap['pm-project-win-event']?.kind, 'mode');
  assert.equal(sharedMap['pm-project-win-event']?.mode, 'terminal');
  winProps = {};
  view.syncWinEvents(cx);
  if (timers.length) {
    const last = timers.pop();
    if (!last.cancelled) last.fn(cx);
  }
  assert.equal(view.agentWindows.find(w => w.key === 'worker:t_single')?.mode, 'terminal');
  assert.deepEqual(sharedMap['pm-project-win-terminals'], ['ts1'], 'switching a window to terminal mode adds it to shared floating terminals');

  // Clicking the size toggle button in the floating window titlebar cycles M -> L, remembers size in shared, and re-opens overlay with larger dimensions
  winProps = {
    agentWindow: 'titlebar', key: 'worker:t_single', role: 'worker', roleLabel: 'worker',
    taskId: 't_single', targetId: 't_single', name: 't_single', threadTitle: 'Single worker thread',
    address: 'ts1', kind: 'claude', mode: 'terminal', size: 'm', canSwitchMode: true, overlay: 'ov-4', lang: 'en', session: 'sess-1',
  };
  const tbWin = new Mod();
  tbWin.init(null, cx);
  nodes.clear();
  tbWin.render(cx);
  const sizeBtn = nodes.get('win-size-worker:t_single');
  assert.ok(sizeBtn, 'floating window titlebar renders S/M/L size toggle button');
  assert.equal(sizeBtn.allTexts().join(''), 'M');
  const prevOverlayCount = overlayCalls.length;
  sizeBtn.clicks({}, cx);
  assert.equal(sharedMap['pm-project-win-event']?.kind, 'size');
  assert.equal(sharedMap['pm-project-win-event']?.size, 'l');
  winProps = {};
  view.syncWinEvents(cx);
  if (timers.length) {
    const last = timers.pop();
    if (!last.cancelled) last.fn(cx);
  }
  assert.equal(sharedMap['pm-project-agent-window-size'], 'l', 'chosen window size is persisted in shared');
  assert.equal(overlayCalls.length, prevOverlayCount + 1);
  assert.equal(overlayCalls[overlayCalls.length - 1].spec.width, 800);
  assert.equal(overlayCalls[overlayCalls.length - 1].spec.height, 540);
  assert.equal(overlayCalls[overlayCalls.length - 1].spec.key, 'pm-agent:worker:t_single');

  // Exited terminal-mode small window auto-closes its overlay via deferred closeOverlay (never synchronously inside render); chat-mode window stays closeable via Esc/re-click
  const exitedTermOv = view.agentWindows.find(w => w.key === 'worker:t_single')?.overlayId;
  assert.ok(exitedTermOv);
  view.agentWindows = [
    ...view.agentWindows,
    { key: 'worker:t1', mode: 'chat', address: 'tw1', overlayId: 'ov-chat-keep' },
  ];
  liveTerms[2].state = 'finished'; // ts1 exits
  liveTerms[0].state = 'finished'; // tw1 exits, but worker:t1 is in chat mode
  closedOverlays.length = 0;
  timers.length = 0;
  view.syncWinEvents(cx);
  assert.deepEqual(closedOverlays, [], 'syncWinEvents must defer closeOverlay out of render phase');
  assert.ok(timers.length > 0, 'syncWinEvents schedules timer to close exited overlay');
  while (timers.length) {
    const t = timers.shift();
    if (!t.cancelled) t.fn(cx);
  }
  assert.deepEqual(closedOverlays, [exitedTermOv], 'exited terminal-mode overlay must be closed via closeOverlay');
  assert.deepEqual(sharedMap['pm-project-win-terminals'], [], 'closing exited terminal-mode overlay clears shared floating terminals');
  assert.equal(model.agentWindowOpen(view.agentWindows, 'worker:t_single'), false);
  assert.equal(model.agentWindowOpen(view.agentWindows, 'worker:t1'), true, 'chat-mode window stays open after exit and remains closeable');
  view.escape({ keystroke: 'escape' }, cx);
  assert.deepEqual(closedOverlays, [exitedTermOv, 'ov-chat-keep'], 'Esc still closes remaining chat-mode window');
  assert.equal(view.agentWindows.length, 0);
  delete sharedMap['pm-project-agent-window-size'];
  liveTerms[0].state = 'live';
  liveTerms[2].state = 'live';

  // 6) Esc stack one level per press: dirty draft blur -> small window -> detail -> narrow list
  const origInputVal = view.input.value;
  view.input.value = () => 'wip draft';
  view.keyFocus.focus = () => { view.typing = ''; };
  view.typing = 'main';
  view.wide = false;
  view.listShown = true;
  view.agentWindows = [{ key: 'worker:t_single', overlayId: 'ov-5' }];
  const esc = { keystroke: 'escape' };
  view.escape(esc, cx); // blurs dirty draft
  assert.equal(view.typing, '');
  assert.equal(view.agentWindows.length, 1);
  view.input.value = origInputVal;
  view.escape(esc, cx); // closes small window
  assert.equal(view.agentWindows.length, 0);
  assert.equal(view.detail, true);
  view.escape(esc, cx); // closes detail
  assert.equal(view.detail, false);
  assert.equal(view.listShown, true);
  view.escape(esc, cx); // closes narrow list
  assert.equal(view.listShown, false);

  // 7) Chinese (`zh`) UI i18n check in list & detail
  view.state.lang = 'zh';
  view.wide = true;
  view.listShown = true;
  view.detail = false;
  view.expandedDone.clear();
  nodes.clear();
  view.render(cx);
  assert.deepEqual(nodes.get('fold-done-ep1')?.texts, ['2 已完']);
  nodes.get('list-t1').clicks({}, cx);
  nodes.clear();
  view.render(cx);
  assert.match(nodes.get('thread-plan-card')?.allTexts().join(' ') || '', /步骤/);
  assert.match(nodes.get('thread-log-toggle')?.allTexts().join(' ') || '', /只看最近 3 条|展开全部/);

  // 8) Proposed task with depends_on: hover card shows "Waiting"/"等待" list + "Ready to dispatch"/"可以派了",
  // stays open while pointer crosses from row into card, clicking a prerequisite reveals/highlights & opens detail,
  // and right-side detail shows the same clickable Waiting list (en & zh).
  const depWaiting = {
    id: 't_dep_wait', pm: 'pm-dudu', title: 'Wait on prereqs', status: 'proposed', updated: '2026-11-21 10:10',
    depends_on: ['t_done', 't1'],
    deps: [
      { id: 't_done', title: 'Initial types', state: 'met', status: 'done', reason: 'done' },
      { id: 't1', title: 'Render left tree and detail', state: 'waiting', status: 'review', reason: 'review' },
    ],
    ready: false,
    latest: 'Waiting for prereqs before dispatch',
  };
  const depReady = {
    id: 't_dep_ready', pm: 'pm-dudu', title: 'Ready queued task', status: 'proposed', updated: '2026-11-21 10:12',
    depends_on: ['t_done'],
    deps: [{ id: 't_done', title: 'Initial types', state: 'met', status: 'done', reason: 'done' }],
    ready: true,
  };
  tasks.push(depWaiting, depReady);
  view.state.lang = 'en';
  view.detail = false;
  view.thread = '';
  view.epicOverrides.set('ep1', false); // Collapse ep1 to verify jump expands ancestor epic & finished fold!
  view.expandedDone.clear();
  view.threadListScroll = { scrolled: [], scroll_to_item(i) { this.scrolled.push(i); } };
  timers.length = 0;

  // Render list & hover t_dep_wait
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('list-t_dep_wait'), true);
  nodes.get('list-t_dep_wait').hover(true, cx);
  nodes.clear();
  view.render(cx);
  const depHoverNode = nodes.get('hover-card-task:t_dep_wait');
  const depHoverText = depHoverNode?.allTexts().join(' ') || '';
  assert.match(depHoverText, /Waiting/);
  assert.match(depHoverText, /1\/2/);
  assert.match(depHoverText, /Initial types/);
  assert.match(depHoverText, /Render left tree and detail/);
  assert.doesNotMatch(depHoverText, /Ready to dispatch/);
  assert.equal(depHoverNode.allSvgs().some(s => s.endsWith('check-mark.svg')), true, 'met prerequisite shows check-mark');
  assert.equal(depHoverNode.allSvgs().some(s => s.endsWith('window-pop.svg')), false, 'hover card still forbids window-pop action');

  // Pointer leaves row -> grace timer scheduled, card stays open while pointer enters card body
  nodes.get('list-t_dep_wait').hover(false, cx);
  assert.equal(view.hoverKey, 'task:t_dep_wait', 'leaving row does not immediately destroy hover card');
  assert.ok(timers.length > 0, 'grace hide timer scheduled');
  const hideTimer1 = timers.at(-1);
  nodes.get('hover-card-body-task:t_dep_wait').hover(true, cx);
  assert.equal(hideTimer1.cancelled, true, 'entering hover card cancels grace hide timer');
  assert.equal(view.hoverKey, 'task:t_dep_wait');

  // Leaving card body schedules grace timer which dismisses card when fired
  nodes.get('hover-card-body-task:t_dep_wait').hover(false, cx);
  const hideTimer2 = timers.at(-1);
  assert.equal(view.hoverKey, 'task:t_dep_wait');
  hideTimer2.fn(cx);
  assert.equal(view.hoverKey, '', 'card dismisses cleanly once grace timer expires outside row and card');

  // Re-open hover card and click met prerequisite (`t_done` inside collapsed ep1 finishedChildren)
  nodes.get('list-t_dep_wait').hover(true, cx);
  nodes.clear();
  view.render(cx);
  assert.ok(nodes.get('hover-dep-t_dep_wait-t_done')?.clicks, 'prerequisite row in hover card is clickable');
  nodes.get('hover-dep-t_dep_wait-t_done').clicks({}, cx);
  assert.equal(view.hoverKey, '', 'clicking prerequisite dismisses hover card');
  assert.equal(view.detail, true, 'opens right-side detail of prerequisite');
  assert.equal(view.thread, 't_done');
  assert.equal(view.epicOverrides.get('ep1'), true, 'expands collapsed ancestor epic');
  assert.equal(view.expandedDone.has('epic:ep1'), true, 'expands finished fold for completed prerequisite');
  assert.equal(view.highlightThread, 't_done', 'highlights target prerequisite in list');

  // Back to list -> target prerequisite is revealed, highlighted, and scrolled into view
  view.detail = false;
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('list-t_done'), true);
  assert.equal(nodes.get('list-t_done').bg, model.withAlpha('#4f8cff', .16), 'jumped row carries accent highlight');
  assert.ok(view.threadListScroll.scrolled.length > 0, 'list scrolled toward jumped prerequisite');

  // All-met proposed task shows "Ready to dispatch" (en) and "可以派了" (zh) in hover card & detail view
  nodes.get('list-t_dep_ready').hover(true, cx);
  nodes.clear();
  view.render(cx);
  assert.match(nodes.get('hover-card-task:t_dep_ready')?.allTexts().join(' ') || '', /Ready to dispatch/);
  assert.match(nodes.get('hover-card-task:t_dep_ready')?.allTexts().join(' ') || '', /1\/1/);

  // Open detail of t_dep_wait -> shows #thread-deps-card (clickable jump to t1) and hides fallback Work/Done card
  view.openThread('t_dep_wait', cx);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('thread-deps-card'), true, 'detail view renders Waiting card');
  assert.equal(nodes.has('thread-plan-card'), false, 'proposed task without explicit plan omits fallback Steps card');
  assert.match(nodes.get('thread-deps-card')?.allTexts().join(' ') || '', /Waiting/);
  assert.ok(nodes.get('dep-item-t1')?.clicks, 'detail Waiting row is clickable');
  nodes.get('dep-item-t1').clicks({}, cx);
  assert.equal(view.thread, 't1', 'clicking detail Waiting row jumps to prerequisite thread');
  assert.equal(view.detail, true);

  // Chinese i18n for Waiting & Ready to dispatch in detail and hover card
  view.state.lang = 'zh';
  view.openThread('t_dep_ready', cx);
  nodes.clear();
  view.render(cx);
  const zhDepsDetail = nodes.get('thread-deps-card')?.allTexts().join(' ') || '';
  assert.match(zhDepsDetail, /等待/);
  assert.match(zhDepsDetail, /可以派了/);

  // Incoming shared jump request (from Board hover card click) reveals & opens target thread
  view.detail = false;
  view.thread = '';
  timers.length = 0;
  sharedMap['pm-project'] = { pm: 'pm-dudu', thread: 't1', jumpSeq: 99999 };
  nodes.clear();
  view.render(cx);
  const jumpCb = timers.pop();
  jumpCb.fn(cx);
  assert.equal(view.thread, 't1');
  assert.equal(view.detail, true);
  assert.equal(view.highlightThread, 't1');

  // 9) Task numbers rendered across UI surfaces in en & zh, and omitted for unnumbered legacy/remote peers
  view.highlightThread = '';
  view.epicOverrides.delete('ep1');
  sharedMap['pm-project'] = { pm: 'pm-dudu' };
  tasks[0].number = 10;
  tasks[1].number = 42;
  tasks[2].number = 41;
  tasks.push({ id: 't_blk', pm: 'pm-dudu', title: 'Blocked q', status: 'blocked', number: 43, updated: '2026-11-21 10:06' });
  // tasks[3] (t_single) deliberately has NO `number` to verify legacy/old remote peer compatibility.
  view.state.task_numbers = { ep1: 10, t1: 42, t_done: 41, t_blk: 43, t_hist: 9 };
  view.events = [
    { type: 'user', at: '2026-11-21 09:00:00', text: 'Inspect [@Render left tree and detail](thread:t1) first' },
    { type: 'thread', at: '2026-11-21 09:00:05', task: 't_blk', status: 'blocked', title: 'Blocked q', text: 'Need decision?', options: ['Yes', 'No'] },
    { type: 'thread', at: '2026-11-21 09:01:00', task: 't_single', status: 'in_progress', title: 'Single worker thread', text: 'working' },
    { type: 'pm', at: '2026-11-21 09:02:00', by: 'hc:tpm', text: 'See [Epic](thread:ep1), [Hist](thread:#9), and `[ignore](thread:t1)`.' },
  ];
  liveTerms.push({ address: 'tpm', state: 'live', labels: { pm: 'dudu' }, program: { key: 'claude', name: 'Claude Code' } });
  view.typing = 'main';
  view.answering = { key: 'question:2026-11-21 09:00:05:t_blk', task: 't_blk', title: 'Blocked q', number: 43 };
  view.mention = { which: 'main', start: 0, query: '42', category: 'all', key: '', index: 0 };
  view.wide = true;
  view.listShown = true;
  view.detail = false;
  view.hoverKey = 'task:t1';
  view.state.lang = 'en';
  nodes.clear();
  view.render(cx);
  assert.ok(nodes.get('epic-ep1')?.allTexts().includes('#10'), 'container epic shows #10');
  assert.ok(nodes.get('list-t1')?.allTexts().includes('#42'), 'thread row shows #42');
  assert.match(nodes.get('hover-card-task:t1')?.allTexts().join(' ') || '', /#42/, 'hover card displays #42');
  assert.equal(nodes.get('list-t_single')?.allTexts().some(s => /^#\d+/.test(s)), false, 'unnumbered peer renders no # badge');
  assert.ok(nodes.get('say-answering')?.allTexts().includes('#43'), 'answering pill shows #43');
  assert.ok(nodes.get('ask-question:2026-11-21 09:00:05:t_blk')?.allTexts().includes('#43'), 'question card shows #43');
  assert.ok(nodes.get('say-mention-row-0')?.allTexts().includes('#42'), '@ mention candidate row shows #42');
  const tlText = nodes.get('pm-project-timeline')?.allTexts().join(' ') || '';
  assert.match(tlText, /#42 .*@Render left tree and detail|@Render left tree and detail/, 'sent user mention chip rendered');
  assert.ok(nodes.get('pm-project-timeline')?.allTexts().includes('#42'), 'timeline renders #42 badge on mention/question');
  assert.match(tlText, /\[#10 Epic\]\(thread:ep1\)/);
  assert.match(tlText, /\[#9 Hist\]\(thread:#9\)/);
  assert.match(tlText, /`\[ignore\]\(thread:t1\)`/);

  // Switch to Chinese and open detail view for #42 (`#42` resolves via openThread + detail header/parent show #42/#10)
  view.state.lang = 'zh';
  view.detail = false;
  view.thread = '';
  view.hoverKey = '';
  view.typing = '';
  view.openThread('#42', cx);
  assert.equal(view.thread, 't1', 'openThread resolves #42 reference');
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.get('thread-number')?.texts?.[0], '#42', 'detail header shows #42');
  assert.ok(nodes.get('thread-parent')?.allTexts().includes('#10'), 'parent submeta link shows #10');
});

test('task numbers: model helpers, @ search, link decoration, and old-peer compatibility', () => {
  assert.equal(model.INTERNAL_PROJECT_FILES.has('task-seq.json'), true);
  assert.equal(model.taskNumber({ number: 42 }), 42);
  assert.equal(model.taskNumber({ num: 7 }), 7);
  for (const bad of [0, -3, '42', true, null, undefined, {}, { number: 0 }]) {
    assert.equal(model.taskNumber(bad), null);
    assert.equal(model.formatTaskNumber(bad), '');
  }
  assert.equal(model.formatTaskNumber(42), '#42');
  assert.equal(model.threadLink('thread:#42'), '#42');
  assert.equal(model.threadLink('thread:dudu#42-review'), 'dudu#42-review');

  const tasks = [
    { id: 'dudu-a', project: 'dudu', pm: 'pm-dudu', title: 'Auth fix', status: 'in_progress', number: 12, updated: '2026-11-21 10:00' },
    { id: 'dudu-b', project: 'dudu', pm: 'pm-dudu', title: 'Legacy work', status: 'done', updated: '2026-11-21 09:00' },
  ];
  assert.equal(model.resolveThreadRef(tasks, '#12'), 'dudu-a');
  assert.equal(model.resolveThreadRef(tasks, '99', { 'dudu-old': 99, 'other-old': 99 }, {
    events: [{ type: 'thread', task: 'dudu-old' }],
  }), 'dudu-old');
  assert.equal(model.resolveThreadRef([], '99', { 'dudu-old': 99, 'other-old': 99 }), '99');

  const md = [
    'See [Auth](thread:dudu-a), [#12 Auth](thread:dudu-a), [Legacy](thread:dudu-b), and `[keep](thread:dudu-a)`.',
    '```',
    '[fenced](thread:dudu-a)',
    '```',
  ].join('\n');
  const decorated = model.decorateThreadLinks(md, tasks);
  assert.match(decorated, /\[#12 Auth\]\(thread:dudu-a\), \[#12 Auth\]\(thread:dudu-a\)/);
  assert.match(decorated, /\[Legacy\]\(thread:dudu-b\)/);
  assert.match(decorated, /`\[keep\]\(thread:dudu-a\)`/);
  assert.match(decorated, /\[fenced\]\(thread:dudu-a\)/);

  // `@42` and `@#42` rank numbered thread first
  const tList = model.threadList({ name: 'pm-dudu' }, tasks, []);
  const m1 = model.buildMentionMenu({ query: '#12', threads: tList, tasks });
  assert.equal(m1.items[0]?.target, 'dudu-a');
  assert.equal(m1.items[0]?.number, 12);
  const m2 = model.buildMentionMenu({ query: '12', threads: tList, tasks });
  assert.equal(m2.items[0]?.target, 'dudu-a');
  // Unnumbered legacy row omits `number`
  assert.equal('number' in tList.finished[0], false);
  const agents = model.threadAgents({ id: 'dudu-a', title: 'Auth', status: 'in_progress', number: 12, pane: 'hc:t1' },
    { terms: [{ address: 't1', state: 'live', labels: { task: 'dudu-a' } }] });
  assert.equal(agents.all[0]?.threadNumber, 12);
});

test('taskDependencies resolves live prerequisite states, ready flag, broken deps, and remote namespaces', () => {
  const { taskDependencies } = model;
  const all = [
    { id: 'd-done', title: 'Done dep', status: 'merged', pm: 'pm-dudu' },
    { id: 'd-work', title: 'Working dep', status: 'in_progress', pm: 'pm-dudu' },
    { id: 'd-rev', title: 'Review dep', status: 'review', pm: 'pm-dudu', review: { id: 'd-rev-r', status: 'in_progress' } },
    { id: 'd-blk', title: 'Blocked dep', status: 'blocked', pm: 'pm-dudu' },
    { id: 'd-abn', title: 'Dropped dep', status: 'abandoned', pm: 'pm-dudu' },
    { id: 'box/d-rem', sourceId: 'd-rem', machine: 'box', title: 'Remote done', status: 'done', pm: 'box/pm-dudu' },
  ];
  const terms = [{ address: 'tr', state: 'live', labels: { task: 'd-rev-r' } }];
  const live = [{ address: 'tr', status: 'working' }];

  const waiting = taskDependencies({ id: 'q1', status: 'proposed', depends_on: ['d-done', 'd-work', 'd-rev', 'd-blk'] }, all, { terms, live });
  assert.equal(waiting.showAsWaiting, true);
  assert.equal(waiting.ready, false);
  assert.equal(waiting.progress, '1/4');
  assert.equal(waiting.items[0].isMet, true);
  assert.equal(waiting.items[1].isWorking, true);
  assert.equal(waiting.items[2].isReview, true);
  assert.equal(waiting.items[2].isReviewWorking, true);
  assert.equal(waiting.items[3].isBlocked, true);

  const ready = taskDependencies({ id: 'q2', status: 'proposed', depends_on: ['d-done'] }, all);
  assert.equal(ready.ready, true);
  assert.equal(ready.allMet, true);
  assert.equal(ready.progress, '1/1');

  const started = taskDependencies({ id: 'q3', status: 'in_progress', depends_on: ['d-done'] }, all);
  assert.equal(started.showAsWaiting, false);
  assert.equal(started.ready, false);

  const broken = taskDependencies({ id: 'q4', status: 'proposed', depends_on: ['d-abn', 'd-missing'] }, all);
  assert.equal(broken.broken, true);
  assert.equal(broken.items[0].state, 'abandoned');
  assert.equal(broken.items[0].clickable, true);
  assert.equal(broken.items[1].state, 'missing');
  assert.equal(broken.items[1].clickable, false);

  const remote = taskDependencies({ id: 'box/q5', machine: 'box', status: 'proposed', depends_on: ['d-rem'] }, all);
  assert.equal(remote.ready, true);
  assert.equal(remote.items[0].title, 'Remote done');
  assert.equal(remote.items[0].pm, 'box/pm-dudu');
});

test('reviewWorking distinguishes active reviewer from waiting-for-PM / finished / idle / offline states', () => {
  const mkReview = (overrides = {}) => ({
    id: 't1-review', review_of: 't1', status: 'in_progress', pane: 'hc:tr1', ...overrides,
  });
  const mkTask = (overrides = {}) => ({
    id: 't1', pm: 'pm-dudu', title: 'Fix ring', status: 'review', pane: 'hc:tw1', updated: '2026-11-22 01:00',
    review: mkReview(), ...overrides,
  });

  // Active reviewer via live terminal label or pane -> moves
  const termByLabel = { address: 'tr1', state: 'live', status: 'idle', labels: { task: 't1-review' } };
  const termByPane = { address: 'tr1', state: 'live', status: 'working', labels: {} };
  assert.equal(model.reviewWorking(mkTask(), [termByLabel], [{ address: 'tr1', status: 'working' }]), true);
  assert.equal(model.reviewWorking(mkTask(), [termByPane], []), true);
  assert.equal(model.reviewWorking(mkTask({ review: mkReview({ pane: '', worker: 'working' }) }), [], []), true);

  // Reviewer terminal present but idle / done / blocked -> static
  assert.equal(model.reviewWorking(mkTask(), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], [{ address: 'tr1', status: 'idle' }]), false);
  assert.equal(model.reviewWorking(mkTask(), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], [{ address: 'tr1', status: 'done' }]), false);
  assert.equal(model.reviewWorking(mkTask(), [{ address: 'tr1', state: 'live', status: 'working', labels: { task: 't1-review' } }], [{ address: 'tr1', status: 'blocked' }]), false);

  // Waiting for PM verdict (no review thread attached) -> static
  assert.equal(model.reviewWorking(mkTask({ review: undefined }), [termByPane], [{ address: 'tr1', status: 'working' }]), false);

  // Review already ended / paused / proposed / blocked / offline -> static
  for (const rStatus of ['done', 'merged', 'released', 'abandoned', 'cancelled', 'paused', 'proposed', 'blocked']) {
    assert.equal(model.reviewWorking(mkTask({ review: mkReview({ status: rStatus }) }), [termByPane], [{ address: 'tr1', status: 'working' }]), false, `review status ${rStatus} stays static`);
  }
  assert.equal(model.reviewWorking(mkTask({ review: mkReview({ offline: true }) }), [termByPane], [{ address: 'tr1', status: 'working' }]), false);

  // Task itself is not in review or is cleanup -> static
  assert.equal(model.reviewWorking(mkTask({ status: 'in_progress' }), [termByPane], [{ address: 'tr1', status: 'working' }]), false);
  assert.equal(model.reviewWorking(mkTask({ status: 'blocked' }), [termByPane], [{ address: 'tr1', status: 'working' }]), false);
  assert.equal(model.reviewWorking(mkTask({ cleanup: true }), [termByPane], [{ address: 'tr1', status: 'working' }]), false);

  // Propagation through threadList, taskTree, and subThreads
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/r/dudu' };
  const activeTask = mkTask({ id: 't-active', review: mkReview({ id: 't-active-review', review_of: 't-active', pane: 'hc:tr-act' }) });
  const waitingPmTask = mkTask({ id: 't-wait', review: undefined, pane: 'hc:tw2' });
  const doneRevTask = mkTask({ id: 't-done-rev', review: mkReview({ id: 't-done-rev-review', review_of: 't-done-rev', status: 'done', pane: 'hc:tr-done' }) });
  const terms = [
    { address: 'tr-act', state: 'live', status: 'working', labels: { task: 't-active-review' } },
    { address: 'tr-done', state: 'live', status: 'working', labels: { task: 't-done-rev-review' } },
  ];
  const live = [
    { address: 'tr-act', status: 'working' },
    { address: 'tr-done', status: 'working' },
  ];
  const list = model.threadList(pm, [activeTask, waitingPmTask, doneRevTask], [], terms, live, [], 'en');
  const byTask = new Map(list.open.map(r => [r.task, r]));
  assert.equal(byTask.get('t-active')?.reviewWorking, true);
  assert.equal(byTask.get('t-wait')?.reviewWorking, undefined);
  assert.equal(byTask.get('t-done-rev')?.reviewWorking, undefined);

  const tree = model.taskTree(pm, [
    { id: 't-active', pm: 'pm-dudu', title: 'Active review', status: 'review', pane: 'hc:tw1', updated: '2026-11-22 01:00' },
    { id: 't-active-review', pm: 'pm-dudu', title: 'Review', status: 'in_progress', review_of: 't-active', pane: 'hc:tr-act', updated: '2026-11-22 01:01' },
    { id: 't-wait', pm: 'pm-dudu', title: 'Wait PM', status: 'review', pane: 'hc:tw2', updated: '2026-11-22 00:59' },
  ], [], { terms, live, lang: 'en' });
  const treeMap = new Map(tree.flatOpen.map(n => [n.task, n]));
  assert.equal(treeMap.get('t-active')?.reviewWorking, true);
  assert.equal(treeMap.get('t-wait')?.reviewWorking, undefined);
});
test('PmProject selectableText & bubble layout invariants prevent 1-char-per-line collapse across all TextView sites', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^\s*import\b[\s\S]*?;\s*$/gm, '')
    .replace(/export\s+default\s+class\s+PmProject\b/, 'class PmProject') + '\nreturn PmProject;\n';

  const nodes = new Map();
  const tvWrappers = new Map();
  const textViews = new Map();
  const makeEl = (tag, extra = {}) => {
    const rec = {
      tag, id: '', kids: [], texts: [], styles: [],
      selectable: false, cursorText: false, hovers: [], mouseDowns: [],
      ...extra,
    };
    const proxy = new Proxy(() => proxy, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') {
            if (typeof args[0] === 'string') rec.texts.push(args[0]);
            else if (args[0]?.__rec) {
              rec.kids.push(args[0].__rec);
              if (args[0].__rec.tvId) tvWrappers.set(args[0].__rec.tvId, rec);
            }
          } else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) {
              if (typeof k === 'string') rec.texts.push(k);
              else if (k?.__rec) {
                rec.kids.push(k.__rec);
                if (k.__rec.tvId) tvWrappers.set(k.__rec.tvId, rec);
              }
            }
          } else if (key === 'selectable') rec.selectable = args[0] === undefined ? true : Boolean(args[0]);
          else if (key === 'cursor_text') rec.cursorText = true;
          else if (key === 'on_hover') rec.hovers.push(args[0]);
          else if (key === 'on_mouse_down') rec.mouseDowns.push(args[1] || args[0]);
          else if (key === 'when') { if (args[0]) args[1](proxy); }
          else if (['w', 'w_full', 'h', 'min_w', 'max_w', 'max_w_full', 'flex_1', 'flex_none', 'absolute'].includes(key)) {
            rec.styles.push([key, ...args]);
          }
          return proxy;
        };
      },
      apply: () => proxy,
    });
    return proxy;
  };
  const hasStyle = (rec, name, ...vals) => rec?.styles?.some(s => s[0] === name && vals.every((v, i) => s[i + 1] === v));
  const hasAnyStyle = (rec, name) => rec?.styles?.some(s => s[0] === name);

  const makeBox = () => ({ on() { return true; }, value: () => '', content: () => ({ text: '', tokens: [] }), selected_range: () => ({ start: 0, end: 0 }), set_selected_range() {}, set_value() {}, set_auto_grow() {}, set_soft_wrap() {}, focus() {} });
  const stubs = {
    View: class {}, ...model, ...changeView, ...searchMod, ...stepsView,
    div: () => makeEl('div'), h_flex: () => makeEl('h_flex'), v_flex: () => makeEl('v_flex'), svg: () => makeEl('svg'), image: () => makeEl('image'),
    TextView: {
      markdown: (id, md) => { const el = makeEl('tv_md', { tvId: id, raw: String(md ?? '') }); textViews.set(id, el.__rec); return el; },
      html: (id, html) => { const el = makeEl('tv_html', { tvId: id, raw: String(html ?? '') }); textViews.set(id, el.__rec); return el; },
    },
    TextareaState: { new: () => makeBox() }, Textarea: { new: () => makeEl('textarea') },
    InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, focus() {} }) }, Input: { new: () => makeEl('input') },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) },
    Popup: { new: (_id, trigger) => makeEl('popup').child(trigger) },
    theme: () => ({
      canvas: '#111111', surface: '#181818', raised: '#222222', chrome: '#161616', hover: '#2a2a2a',
      border: '#333333', input: '#3a3a3a', foreground: '#eeeeee', background: '#111111',
      muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', accent_foreground: '#ffffff',
      blocked: '#ff5f56', ansi2: '#27c93f', ansi3: '#f5a623', solid: '#eeeeee', solid_foreground: '#111111',
    }),
    home: () => '/Users/test', appHome: () => '/app',
    exec: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    execPython: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    readTextFile: async () => '', writeTextFile: async () => {}, watchFolder: () => new Promise(() => {}),
    layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run() {},
    terminals: () => [{ address: 'tpm', state: 'live', labels: { pm: 'dudu' } }, { address: 'tw1', state: 'live', labels: { task: 't-1' } }],
    agents: () => [], panes: () => [{ terminal: 'tpm' }], spaces: () => [],
    shared: () => ({ pm: 'pm-dudu' }), setShared() {},
    appWindow: () => ({ platform: 'macos' }),
  };

  const prevStorage = globalThis.localStorage;
  const storeMap = new Map();
  globalThis.localStorage = { getItem: k => storeMap.get(k) ?? null, setItem: (k, v) => storeMap.set(k, String(v)), removeItem: k => storeMap.delete(k) };
  try {
    const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
    const cx = { focus_handle: () => ({ focus() {} }), spawn() {}, timer: { after() {} }, notify() {}, stop_propagation() {}, read_from_clipboard: () => '' };
    const today = (() => { const d = new Date(), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; })();
    const at = t => `${today} ${t}`;
    const pmLocal = { name: 'pm-dudu', project: 'dudu', repo: '/work/dudu', pane: 'hc:tpm', runtime: 'hc', status: 'live' };
    const userKey = `user:${at('09:02:00')}:`;
    const view = Object.assign(Object.create(Mod.prototype), {
      state: {
        pms: [pmLocal],
        tasks: [{ id: 't-1', pm: 'pm-dudu', title: 'Task 1', status: 'blocked', pane: 'hc:tw1', updated: at('09:01'), log: [{ n: 1, at: at('09:01:00'), text: 'Detailed log line' }] }],
        events: [], lang: 'zh',
      },
      events: [
        { at: at('09:00:00'), type: 'pm', text: 'First paragraph.\n\nSecond paragraph.' },
        { at: at('09:01:00'), type: 'thread', task: 't-1', status: 'blocked', text: 'Pick one option' },
        { at: at('09:02:00'), type: 'user', text: 'autoDream 等重构之后再做.' },
        { at: at('09:03:00'), type: 'decision', text: 'Use auto-fit bubble width' },
        { at: at('09:04:00'), type: 'pm', text: 'Latest PM reply.' },
      ],
      pending: [], seq: 0, pastes: [], error: '', logError: '',
      pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
      remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
      earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '/here', watching: {},
      thread: 't-1', threadTask: { id: 't-1', title: 'Task 1', status: 'blocked', pane: 'hc:tw1' }, detail: true,
      threadError: '', threadLog: { entries: [{ n: 1, at: at('09:01:00'), text: 'Expanded log entry text' }], earlier: 0 },
      threadLogKept: [], threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null, threadLogExpanded: true,
      threadTab: 'log', sideTab: 'threads',
      librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: false, libraryProbed: true, libraryStale: false,
      libraryLoading: false, libraryAgain: false, libraryError: '', libraryClosed: new Set(), libraryQuery: '', libraryDropBusy: '', libraryDropError: '',
      memorySlug: 'dudu', memoryData: null, memoryRead: false, memoryStale: false, memoryError: '',
      memoryLoading: false, memoryAgain: false, memoryFoldOverrides: new Map(), memoryProjectOpen: true,
      memoryPersonalOpen: false, memoryCandidatesOpen: false, memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
      activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '', docShownBytes: model.DOC_INITIAL_BYTES,
      docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
      editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
      confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
      reattaching: '', reattachError: null, startingPm: '', startPmError: null,
      bringBackOpen: false, bringingBack: false, bringBackProgress: null,
      listShown: true, wide: true, measured: true, viewWidth: 1280, panelWant: null, panelDrag: null, gripLit: false,
      seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
      bell: null, flash: '', unfolded: new Map(), newest: '', atWork: new Set(),
      scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
      libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} },
      historyScroll: { scroll_to_item() {} }, mentionScroll: { scroll_to_item() {} },
      mention: null, mentionDismissed: null, mentionConsumedKey: false, mentionPicking: false,
      repoFilesSlug: '', repoFilesRepo: '', repoFiles: [], repoFilesRead: false, repoFilesLoading: false, repoFilesAgain: false,
      repoFilesError: '', repoFilesTruncated: false, repoFilesAt: 0, pathCopiedAt: 0,
      quotes: [], quoteSeq: 0, hoveredMsg: userKey, hoverClipboard: null, selectionBar: null, lastBlocks: [], lastTopOffset: 0, lastHeights: [], lastTall: 0,
      keyFocus: { focus() {} }, onStage: true, typing: '', mainKey: 'pm:pm-dudu', threadKey: '',
      outgoing: new Map(), files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
      input: makeBox(), threadInput: makeBox(), libraryInput: stubs.InputState.new(), memoryInput: stubs.InputState.new(),
      docFindInput: stubs.InputState.new(), docNameInput: stubs.InputState.new(), memDescInput: stubs.InputState.new(),
      docEditorInput: stubs.TextareaState.new(), refresh: () => {},
    });
    view.resetThreadSession();

    const rerender = () => { nodes.clear(); tvWrappers.clear(); textViews.clear(); view.render(cx); };
    rerender();

    // (1) User bubble: auto-fit width (no fixed w), keeps max_w('72%'), keeps quote button & selectable TextView,
    //     and its selectableText wrapper must NOT set min_w(0) (which collapses shrink-to-fit v_flex to 1 char/line).
    const bubble = nodes.get(`bubble-${userKey}`);
    assert.ok(bubble, 'user bubble rendered');
    assert.equal(hasStyle(bubble, 'max_w', '72%'), true, 'user bubble keeps max_w(72%)');
    assert.equal(hasAnyStyle(bubble, 'w'), false, 'user bubble does not hardcode fixed width');
    assert.ok(nodes.get(`quote-btn-${userKey}`), 'hover quote button stays beside user bubble');
    const userTvId = `bubble-${userKey}-txt`;
    assert.equal(textViews.get(userTvId)?.selectable, true, 'user bubble text remains selectable');
    const userWrap = tvWrappers.get(userTvId);
    assert.ok(userWrap, 'user bubble selectableText wrapper exists');
    assert.equal(hasStyle(userWrap, 'max_w_full'), true, 'user bubble text wrapper keeps max_w_full for wrapping');
    assert.equal(hasAnyStyle(userWrap, 'min_w'), false, 'user bubble text wrapper must NOT set min_w(0)');
    assert.equal(userWrap.mouseDowns.length, 0, 'selectableText wrapper must NOT stop mouse_down propagation');
    assert.equal(bubble.mouseDowns.length, 0, 'user bubble must NOT stop mouse_down propagation');
    assert.equal(nodes.get('pm-project-timeline')?.mouseDowns?.length, 0, 'timeline must NOT stop mouse_down propagation');
    assert.equal(nodes.get('pm-project-panel')?.mouseDowns?.length, 0, 'side panel must NOT stop mouse_down propagation');

    // (2) Timeline center column wrapper sets min_w(0) so outer h_flex skips MinContent probing into rows.
    const blockEl = nodes.get(`block-${userKey}`);
    assert.ok(blockEl && blockEl.kids.length === 1, 'timeline block wraps inner column');
    const innerCol = blockEl.kids[0];
    assert.equal(hasStyle(innerCol, 'w_full'), true);
    assert.equal(hasStyle(innerCol, 'min_w', 0), true, 'center column sets min_w(0)');
    assert.equal(hasStyle(innerCol, 'max_w', 680), true, 'center column keeps max_w(COLUMN)');

    // (3) Horizontal flex selectableText sites keep explicit flex_1().min_w(0); full-width block sites keep w_full().
    for (const tvId of [`lead-pm:${at('09:00:00')}:`, `dec-txt-decision:${at('09:03:00')}:`]) {
      const wrap = tvWrappers.get(tvId);
      assert.equal(hasStyle(wrap, 'flex_1'), true, `${tvId} keeps flex_1`);
      assert.equal(hasStyle(wrap, 'min_w', 0), true, `${tvId} keeps explicit min_w(0) in h_flex`);
    }
    for (const tvId of [`q-txt-question:${at('09:01:00')}:t-1`, `thread-ask-t-1`, `thread-log-txt-t-1-1`]) {
      const wrap = tvWrappers.get(tvId);
      assert.equal(hasStyle(wrap, 'w_full'), true, `${tvId} stretches across its block container`);
    }

    // (4) Thread session tab: user bubble has auto-fit max_w('90%') without min_w(0); tool input has flex_1().min_w(0); tool output has w_full().
    view.threadTab = 'session';
    view.threadSessionTask = 't-1';
    view.threadSessionState = 'ready';
    view.threadSession = {
      taskId: 't-1',
      items: [
        { type: 'user', at: at('09:05:00'), text: 'autoDream 等重构之后再做.', offset: 1 },
        { type: 'tool', at: at('09:05:10'), name: 'Bash', input: 'https://example.com/very/long/tool/input', output: 'tool output line', offset: 2 },
      ],
      earlier: false,
    };
    const toolTurn = model.sessionTurns(view.threadSession.items, { lang: 'zh' }).find(x => x.role === 'assistant');
    const toolPartKey = toolTurn?.parts?.find(p => p.kind === 'tools')?.key;
    assert.ok(toolPartKey, 'session tool part exists');
    view.sessionToolsOpen = new Set([toolPartKey]);
    rerender();

    const sessBubble = [...nodes.values()].find(n => n.id.startsWith('session-user-'));
    assert.ok(sessBubble, 'session user bubble rendered');
    assert.equal(hasStyle(sessBubble, 'max_w', '90%'), true, 'session user bubble keeps max_w(90%)');
    assert.equal(hasAnyStyle(sessBubble, 'w'), false, 'session user bubble does not hardcode fixed width');
    const sessUserTvId = [...textViews.keys()].find(id => id.startsWith('session-msg-'));
    assert.ok(sessUserTvId && textViews.get(sessUserTvId)?.selectable, 'session user text is selectable');
    assert.equal(hasAnyStyle(tvWrappers.get(sessUserTvId), 'min_w'), false, 'session user text wrapper omits min_w(0)');

    const callInTvId = `session-call-in-${toolPartKey}-0`;
    assert.equal(hasStyle(tvWrappers.get(callInTvId), 'flex_1'), true, 'session tool input keeps flex_1');
    assert.equal(hasStyle(tvWrappers.get(callInTvId), 'min_w', 0), true, 'session tool input keeps explicit min_w(0) in h_flex');
    const callOutTvId = `session-call-out-${toolPartKey}-0`;
    assert.equal(hasStyle(tvWrappers.get(callOutTvId), 'w_full'), true, 'session tool output keeps w_full');

    // (5) PM reply quote button sits in a dedicated non-overlapping right slot (not absolute over text).
    const pmKey = `pm:${at('09:04:00')}:`;
    view.hoveredMsg = pmKey;
    rerender();
    const pmMsg = nodes.get(`pm-msg-${pmKey}`);
    assert.equal(pmMsg?.tag, 'h_flex', 'PM reply row is h_flex with text + reserved quote slot');
    const quoteSlot = nodes.get(`pm-quote-slot-${pmKey}`);
    assert.ok(quoteSlot, 'PM reply reserves dedicated quote slot');
    assert.equal(hasStyle(quoteSlot, 'w', 24), true, 'PM quote slot reserves 24px width');
    assert.equal(hasStyle(quoteSlot, 'h', 26), true, 'PM quote slot reserves 26px height to prevent hover jitter');
    assert.equal(hasStyle(quoteSlot, 'flex_none'), true, 'PM quote slot does not shrink');
    assert.equal(hasAnyStyle(quoteSlot, 'absolute'), false, 'PM quote slot does not float over text');
    assert.ok(nodes.get(`quote-btn-${pmKey}`), 'PM hover quote button renders inside slot');
  } finally {
    globalThis.localStorage = prevStorage;
  }
});

test('PmProject split header and body instances coordinate via shared state and actions', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^\s*import\b[\s\S]*?;\s*$/gm, '')
    .replace(/export\s+default\s+class\s+PmProject\b/, 'class PmProject') + '\nreturn PmProject;\n';

  const nodes = new Map();
  const sharedMap = new Map([['pm-project', { pm: 'pm-dudu' }]]);
  const runCalls = [];
  let activeProps = null;
  const makeEl = (tag) => {
    const rec = { tag, id: '', kids: [], texts: [], styles: [], clicks: [], mouseDowns: [], keyDowns: [], tips: [] };
    const proxy = new Proxy(() => proxy, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') {
            if (typeof args[0] === 'string') rec.texts.push(args[0]);
            else if (args[0]?.__rec) rec.kids.push(args[0].__rec);
          } else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) {
              if (typeof k === 'string') rec.texts.push(k);
              else if (k?.__rec) rec.kids.push(k.__rec);
            }
          } else if (key === 'on_click') rec.clicks.push(args[0]);
          else if (key === 'on_mouse_down') rec.mouseDowns.push(args[1] || args[0]);
          else if (key === 'on_key_down') rec.keyDowns.push(args[0]);
          else if (key === 'tooltip') rec.tips.push(String(args[0]));
          else if (key === 'when') {
            if (args[0]) args[1](proxy);
          } else rec.styles.push([key, args]);
          return proxy;
        };
      },
    });
    return proxy;
  };
  const makeBox = () => ({ value: () => '', set_value() {}, focus() {}, on() {}, set_auto_grow() {}, set_soft_wrap() {}, set_placeholder() {} });
  const stubs = {
    View: class {},
    div: () => makeEl('div'),
    svg: () => makeEl('svg'),
    image: () => makeEl('image'),
    v_flex: () => makeEl('v_flex'),
    h_flex: () => makeEl('h_flex'),
    TextView: {
      markdown: () => makeEl('TextView.markdown'),
      html: () => makeEl('TextView.html'),
    },
    TextareaState: { new: () => makeBox() },
    Textarea: { new: () => makeEl('Textarea') },
    InputState: { new: () => makeBox() },
    Input: { new: () => makeEl('Input') },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) },
    Popup: { new: (_id, trigger) => makeEl('Popup').child(trigger) },
    theme: () => ({
      canvas: '#111111', chrome: '#181818', surface: '#222222', raised: '#282828', border: '#333333', input: '#333333',
      hover: '#3a3a3a', foreground: '#eeeeee', background: '#111111', muted: '#999999', dim: '#777777',
      accent: '#66ccff', accent_foreground: '#ffffff', blocked: '#ff6666',
      working: '#66cc66', ansi2: '#66cc66', ansi3: '#ffcc66', ansi4: '#6699ff',
    }),
    home: () => '/Users/test',
    appHome: () => '/tmp/app',
    exec: async () => ({ code: 0, stdout: '', stderr: '' }),
    readTextFile: async () => '',
    writeTextFile: async () => {},
    watchFolder: async () => [],
    layout: () => ({ id: 'root', children: [{ id: 'pm-stage', active: 'pm-project' }] }),
    run: (cmd, args) => runCalls.push([cmd, args]),
    terminals: () => [{ address: 't-pm', state: 'live', labels: { pm: 'pm-dudu' } }],
    agents: () => [],
    panes: () => [],
    spaces: () => [],
    shared: key => sharedMap.get(key) ?? null,
    setShared: (key, val) => sharedMap.set(key, val),
    props: () => activeProps,
    openOverlay: () => '',
    closeOverlay: () => {},
    appWindow: () => ({}),
    execPython: async () => ({}),
    ...model,
    ...changeView,
    ...searchMod,
    ...stepsView,
  };
  const PmProject = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
  const pendingTimers = [];
  const flushImmediate = () => {
    for (let i = 0; i < pendingTimers.length; ) {
      if (pendingTimers[i].ms === 0) pendingTimers.splice(i, 1)[0].fn(cx);
      else i++;
    }
  };
  const cx = {
    notify() {},
    focus_handle: () => ({ focus() {} }),
    timer: { after: (ms, fn) => pendingTimers.push({ ms, fn }), every() {} },
    spawn() {},
  };

  const prevStorage = globalThis.localStorage;
  globalThis.localStorage = { getItem: () => null, setItem() {} };
  try {
    // (1) Body-only instance omits inline header bar and publishes header state to shared store.
    activeProps = { body: true };
    const bodyView = new PmProject();
    bodyView.init({}, cx);
    bodyView.pmName = 'pm-dudu';
    bodyView.stateFor = '';
    bodyView.winSession = 'sess-split-1';
    bodyView.wide = true;
    bodyView.listShown = true;
    bodyView.state = {
      lang: 'zh',
      pms: [{ name: 'pm-dudu', project: 'dudu', repo: '/Users/test/dudu', pane: 'hc:t-pm', context_tokens: 42000 }],
      tasks: [{ id: 't-1', pm: 'pm-dudu', title: 'Task 1', status: 'blocked', question: 'Q?', updated: '2026-11-22 09:00' }],
    };
    bodyView.events = [
      { type: 'thread', at: '2026-11-22 09:01:00', task: 't-1', status: 'blocked', text: 'Q?' },
    ];
    nodes.clear();
    bodyView.render(cx);
    assert.equal(nodes.has('pm-project-header-bar'), false, 'body-only instance omits inline header');
    const published = sharedMap.get('pm-project-header-state');
    assert.equal(published?.hasPm, true);
    assert.equal(published?.title, 'dudu');
    assert.equal(published?.waiting, 1);
    assert.equal(published?.hasRing, true);
    assert.equal(published?.pmStart, 'online');

    // (2) Header-only instance renders draggable bar (no keepPress on bar itself, keepPress on controls) and emits actions.
    activeProps = { header: true };
    const headerView = new PmProject();
    headerView.init({}, cx);
    assert.equal(headerView.headerOnly, true);
    nodes.clear();
    headerView.render(cx);
    const headerBar = nodes.get('pm-project-header-bar');
    assert.ok(headerBar, 'header-only instance renders header bar');
    assert.equal(headerBar.styles.some(s => s[0] === 'size_full'), true, 'header-only bar fills its layout block');
    assert.equal(headerBar.mouseDowns.length, 0, 'header bar lets blank-space mouse_down reach window_drag');
    assert.ok(nodes.get('project-view')?.mouseDowns?.length > 0, 'views switcher stops window_drag');
    assert.ok(nodes.get('pm-header-controls')?.mouseDowns?.length > 0, 'header controls stop window_drag');

    // Clicking toggle-panel in header emits action that body executes, returns focus, updates panelTip & swaps button id so GPUI drops cached tooltip.
    let bodyFocusCount = 0;
    bodyView.keyFocus = { focus() { bodyFocusCount++; } };
    assert.equal(bodyView.listShown, true);
    assert.ok(nodes.get('pm-threads-open'), 'open panel button uses open-state id');
    assert.equal(nodes.get('pm-threads-open').tips[0], model.word('zh', 'hideSidePanel'));
    nodes.get('pm-threads-open').clicks[0]({}, cx);
    assert.equal(sharedMap.get('pm-project-header-action')?.kind, 'toggle-panel');
    pendingTimers.length = 0;
    bodyView.render(cx);
    flushImmediate();
    assert.equal(bodyView.listShown, false, 'body instance toggled side panel from header action');
    assert.equal(bodyFocusCount, 1, 'body regains keyboard focus after header toggle-panel');
    bodyView.render(cx);
    assert.equal(sharedMap.get('pm-project-header-state')?.panelOpen, false);
    assert.equal(sharedMap.get('pm-project-header-state')?.panelTip, model.word('zh', 'showSidePanel'));
    nodes.clear();
    headerView.render(cx);
    assert.ok(nodes.get('pm-threads-closed'), 'closed panel button swaps to closed-state id');
    assert.equal(nodes.get('pm-threads-closed').tips[0], model.word('zh', 'showSidePanel'));

    // Clicking bell in header emits action that body executes (flashes waiting question and returns focus).
    nodes.get('bell').clicks[0]({}, cx);
    assert.equal(sharedMap.get('pm-project-header-action')?.kind, 'bell');
    pendingTimers.length = 0;
    bodyView.render(cx);
    flushImmediate();
    assert.ok(bodyView.flash, 'body instance ran bell ring from header action');
    assert.equal(bodyFocusCount, 2, 'body regains keyboard focus after header bell');

    // Pressing Esc while header holds focus forwards escape to body and closes one layer (narrow open panel).
    bodyView.wide = false;
    bodyView.listShown = true;
    bodyView.render(cx);
    nodes.clear();
    headerView.render(cx);
    const hdrBar = nodes.get('pm-project-header-bar');
    assert.ok(hdrBar.keyDowns.length > 0, 'header bar tracks Esc key');
    let stopped = false;
    hdrBar.keyDowns[0]({ keystroke: 'escape' }, { ...cx, stop_propagation() { stopped = true; } });
    assert.equal(stopped, true, 'header stops Esc propagation once forwarded');
    assert.equal(sharedMap.get('pm-project-header-action')?.kind, 'escape');
    pendingTimers.length = 0;
    bodyView.render(cx);
    flushImmediate();
    assert.equal(bodyView.listShown, false, 'forwarded Esc closed narrow side panel in body');
    assert.equal(bodyFocusCount, 3, 'body regains keyboard focus after forwarded Esc');
  } finally {
    globalThis.localStorage = prevStorage;
  }
});

test('question cards highlight non-first recommended option and settle worker blocked cards handled by PM', () => {
  const pm = { name: 'pm-dudu', pane: 'hc:t160' };

  // 1. recommended_index > 0 is preserved on both timeline cards and threadQuestion; index 0 keeps no extra key.
  const recEvents = [
    thread('09:00:00', 'q-nonfirst', 'blocked', 'status=blocked; 这份设计稿怎么处理？', {
      by: 'hc:t160',
      options: ['先留在暂存', '建任务继续做', '直接删掉'],
      option_notes: ['不动现有内容', '派 worker 实现', ''],
      recommended: true,
      recommended_index: 1,
    }),
  ];
  const recTask = {
    id: 'q-nonfirst', title: 'autoDream 设计稿', status: 'blocked', pm: 'pm-dudu',
    options: ['先留在暂存', '建任务继续做', '直接删掉'],
    option_notes: ['不动现有内容', '派 worker 实现', ''],
    recommended: true, recommended_index: 1,
  };
  const recItems = timeline(recEvents, [recTask], { pm: pm.name, pmPane: pm.pane });
  const recCard = recItems.find(i => i.kind === 'question');
  assert.equal(recCard.open, true);
  assert.equal(recCard.recommended, true);
  assert.equal(recCard.recommendedIndex, 1);
  assert.equal(recCard.handledByPm, undefined);
  assert.equal(threadQuestion(recTask, recItems).recommendedIndex, 1);
  assert.equal(threadQuestion(recTask, []).recommendedIndex, 1);

  // 2. Worker reports blocked (dirty main checkout), then PM handles it (sends message / updates to in_progress
  //    with handled_by='pm') and posts a PM question card: worker's old card is closed + marked handledByPm.
  const events = [
    thread('01:49:00', 'dudu-at', 'in_progress', 'dispatched', { by: 'hc:t160' }),
    thread('01:50:00', 'dudu-at', 'blocked', 'status=blocked; pm.py land 返回 exit 2：主检出有未提交改动', { by: 'hc:t22' }),
    thread('01:51:00', 'dudu-at', 'in_progress', 'status=in_progress; PM 已处理（已发消息给 worker）：主检出已清理，重新 land', {
      by: 'hc:t160', handled_by: 'pm',
    }),
    thread('01:51:10', 'dudu-auto', 'blocked', 'status=blocked; 这份 autoDream 设计稿怎么处理？', {
      by: 'hc:t160', options: ['建任务继续做', '先留在暂存'], recommended: true,
    }),
    ev('01:51:20', 'pm', { text: '主检出已清理，我让 worker 重新合并了。', by: 'hc:t160' }),
  ];
  const tasks = [
    { id: 'dudu-at', title: '项目输入框 @', status: 'in_progress', pm: 'pm-dudu' },
    { id: 'dudu-auto', title: 'autoDream 设计稿', status: 'blocked', pm: 'pm-dudu' },
  ];
  const items = timeline(events, tasks, { pm: pm.name, pmPane: pm.pane });
  const qCards = items.filter(i => i.kind === 'question');
  assert.equal(qCards.length, 2);
  assert.equal(qCards[0].task, 'dudu-at');
  assert.equal(qCards[0].open, false);
  assert.equal(qCards[0].handledByPm, true);
  assert.equal(qCards[1].task, 'dudu-auto');
  assert.equal(qCards[1].open, true);
  assert.equal(qCards[1].handledByPm, undefined);
  // Only the PM's open question counts in bell targets / stops.
  assert.deepEqual(bellTargets(items).map(i => items[i].task), ['dudu-auto']);
  assert.deepEqual(bellStops(items, tasks, pm).map(s => s.key), [qCards[1].key]);

  // 3. Worker blocked card superseded by a structured PM question on the same task -> old worker card is handledByPm.
  const superseded = timeline([
    thread('02:00:00', 'dudu-x', 'in_progress', 'dispatched', { by: 'hc:t160' }),
    thread('02:01:00', 'dudu-x', 'blocked', 'status=blocked; raw worker error', { by: 'hc:t33' }),
    thread('02:02:00', 'dudu-x', 'blocked', 'status=blocked; 选哪个方案？', { by: 'hc:t160', options: ['A', 'B'], recommended: true }),
  ], [{ id: 'dudu-x', title: '任务 X', status: 'blocked', pm: 'pm-dudu' }], { pm: pm.name, pmPane: pm.pane });
  const supCards = superseded.filter(i => i.kind === 'question');
  assert.equal(supCards[0].open, false);
  assert.equal(supCards[0].handledByPm, true);
  assert.equal(supCards[1].open, true);
  assert.equal(supCards[1].handledByPm, undefined);

  // 4. PM question answered directly in terminal (user spoke without 【title】 prefix, then PM closed task)
  //    closes the card without falsely marking handledByPm.
  const termAnswered = timeline([
    thread('03:00:00', 'dudu-q', 'blocked', 'status=blocked; 要不要现在推？', { by: 'hc:t160', options: ['推', '先不'] }),
    ev('03:01:00', 'user', { text: '先不推' }),
    thread('03:01:10', 'dudu-q', 'done', 'status=done; 用户说先不推', { by: 'hc:t160' }),
  ], [{ id: 'dudu-q', title: '推送确认', status: 'done', pm: 'pm-dudu' }], { pm: pm.name, pmPane: pm.pane });
  const termCard = termAnswered.find(i => i.kind === 'question');
  assert.equal(termCard.open, false);
  assert.equal(termCard.handledByPm, undefined);

  // 5. Bilingual labels exist for handledByPm.
  assert.equal(model.word('en', 'handledByPm'), 'Handled by PM');
  assert.equal(model.word('zh', 'handledByPm'), 'PM 已处理');
});

test('PM send queue helpers, dialog classifier, and settlePending protection (en & zh)', () => {
  // Status & receivability
  assert.equal(model.pmLiveStatus({ address: 't1', status: 'idle' }, [{ address: 't1', status: 'blocked' }]), 'blocked');
  assert.equal(model.pmCanReceive('idle'), true);
  assert.equal(model.pmCanReceive('working'), true);
  assert.equal(model.pmCanReceive('done'), true);
  assert.equal(model.pmCanReceive('blocked'), false);
  assert.equal(model.pmCanReceive('error'), false);

  // Queueable vs permanent send errors
  assert.equal(model.isQueueableSendError(new Error('t160 is blocked: read it, then answer with hc send or hc keys')), true);
  assert.equal(model.isQueueableSendError('t160 is blocked (question)'), true);
  assert.equal(model.isQueueableSendError('waiting for unsent draft'), true);
  assert.equal(model.isQueueableSendError('hc send timed out'), true);
  assert.equal(model.isQueueableSendError('terminal t160 not found'), false);
  assert.equal(model.isQueueableSendError('t160 has exited'), false);
  assert.equal(model.isQueueableSendError(Object.assign(new Error('is blocked'), { upload: true })), false);

  // Known dialog classification from screen tail and/or send error
  assert.deepEqual(
    model.classifyPmDialog('Some header\n❯ Option A\nEnter to select · ↑/↓ to navigate · Esc to cancel', '', 'blocked'),
    { kind: 'question', labelKey: 'pmBlockedQuestion' },
  );
  assert.deepEqual(
    model.classifyPmDialog('', 't160 is blocked (question)', 'blocked'),
    { kind: 'question', labelKey: 'pmBlockedQuestion' },
  );
  assert.deepEqual(
    model.classifyPmDialog('Bash command\nDo you want to proceed?\n1. Yes\n2. No', '', 'blocked'),
    { kind: 'permission', labelKey: 'pmBlockedPermission' },
  );
  assert.deepEqual(
    model.classifyPmDialog('Quick safety check\nDo you trust the files in this folder?', '', 'blocked'),
    { kind: 'trust', labelKey: 'pmBlockedTrust' },
  );
  assert.deepEqual(
    model.classifyPmDialog('Update available! Run upgrade now or skip until next version', '', 'blocked'),
    { kind: 'update', labelKey: 'pmBlockedUpdate' },
  );
  assert.deepEqual(
    model.classifyPmDialog('Hooks need review before continuing', '', 'blocked'),
    { kind: 'hook_review', labelKey: 'pmBlockedHook' },
  );
  assert.deepEqual(
    model.classifyPmDialog('Please log in to continue', '', 'blocked'),
    { kind: 'auth', labelKey: 'pmBlockedAuth' },
  );
  assert.deepEqual(
    model.classifyPmDialog('429 rate limit exceeded', '', 'blocked'),
    { kind: 'quota', labelKey: 'pmBlockedQuota' },
  );
  assert.deepEqual(
    model.classifyPmDialog('', 't160 has an unsent draft', 'idle'),
    { kind: 'draft', labelKey: 'pmBlockedDraft' },
  );
  assert.deepEqual(
    model.classifyPmDialog('unrecognized prompt', '', 'blocked'),
    { kind: 'unknown', labelKey: 'pmBlockedUnknown' },
  );
  assert.equal(model.classifyPmDialog('ready prompt', '', 'idle'), null);

  // Stale scrollback lines above the active bottom 18 lines must NOT trigger false dialog match.
  const oldScrollback = ['Do you trust the files in this folder?', ...Array.from({ length: 22 }, (_, i) => `normal log line ${i}`)].join('\n');
  assert.deepEqual(model.classifyPmDialog(oldScrollback, '', 'blocked'), { kind: 'unknown', labelKey: 'pmBlockedUnknown' });

  // Banner wording in EN & ZH
  const qDialog = { kind: 'question', labelKey: 'pmBlockedQuestion' };
  assert.equal(model.pmBlockedBannerText('en', qDialog, 0), 'PM is waiting on a terminal question dialog');
  assert.equal(model.pmBlockedBannerText('en', qDialog, 2), 'PM is waiting on a terminal question dialog · 2 messages queued, will send automatically');
  assert.equal(model.pmBlockedBannerText('zh', qDialog, 1), 'PM 正停在终端提问对话框上 · 1 条消息排队中，恢复后自动送达');
  assert.equal(model.pmBlockedBannerText('zh', null, 2), '2 条消息排队中，PM 可接收时自动送达');

  // settlePending never swallows an unsent queued bubble even if an identical message is already in events.
  const queued = [{ id: 1, text: '好', sentAt: 1000, queued: true }];
  assert.equal(settlePending(queued, [ev('09:00:00', 'user', { text: '好' })]).length, 1);

  // timeline marks queued pending items with queued: true, pending: false.
  const tl = timeline([], [], { pending: queued });
  assert.equal(tl[0].queued, true);
  assert.equal(tl[0].pending, false);
});

test('PmProject composer queues messages while PM is blocked, shows dialog reason, and auto-delivers FIFO on unblock', async () => {
  const { readFileSync } = await import('node:fs');
  const mainSrc = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const source = mainSrc
    .replace(/^import[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/export\s+default\s+class\s+(\w+)/, 'class $1')
    + '\nreturn PmProject;\n';

  const nodes = new Map();
  const elProxy = (tag) => {
    const node = {
      tag, idVal: '', texts: [], kids: [], clicks: null, tooltipVal: '',
      id(v) { this.idVal = String(v); nodes.set(this.idVal, this); return p; },
      child(c) { if (c != null) this.kids.push(c); if (typeof c === 'string') this.texts.push(c); return p; },
      children(arr) { for (const c of arr || []) this.child(c); return p; },
      when(cond, fn) { return cond ? fn(p) : p; },
      on_click(fn) { this.clicks = fn; return p; },
      tooltip(v) { this.tooltipVal = String(v); return p; },
      allTexts() {
        const out = [...this.texts];
        for (const c of this.kids) if (c && typeof c.allTexts === 'function') out.push(...c.allTexts());
        return out;
      },
    };
    const p = new Proxy(node, {
      get(target, prop) {
        if (prop in target) return target[prop];
        return () => p;
      },
    });
    return p;
  };

  let pmStatus = 'blocked';
  let pmScreen = 'Choose an option:\n❯ Create task (Recommended)\n  Keep stashed\nEnter to select · ↑/↓ to navigate · Esc to cancel';
  let sendBehavior = 'ok';
  const sentMessages = [];
  const readCalls = [];

  const stubs = {
    ...model,
    View: class {},
    div: () => elProxy('div'),
    svg: () => elProxy('svg'),
    image: () => elProxy('image'),
    v_flex: () => elProxy('v_flex'),
    h_flex: () => elProxy('h_flex'),
    TextView: { markdown: () => elProxy('md') },
    Textarea: { new: () => elProxy('textarea') },
    TextareaState: class {},
    Input: { new: () => elProxy('input') },
    InputState: class {},
    ScrollHandle: class {},
    Popup: { new: (_id, base) => base },
    theme: () => ({
      background: '#111', surface: '#181818', raised: '#222', hover: '#2a2a2a', border: '#333', input: '#444',
      foreground: '#eee', muted: '#999', dim: '#666', accent: '#60a5fa', blocked: '#f59e0b', done: '#22c55e',
      solid: '#eee', solid_foreground: '#111',
    }),
    home: () => '/tmp',
    appHome: () => '/tmp/herdr-app',
    readTextFile: async () => '',
    writeTextFile: async () => {},
    watchFolder: async () => new Promise(() => {}),
    layout: () => ({}),
    run: () => {},
    terminals: () => [{ address: 'tpm', state: 'live', status: pmStatus, labels: { pm: 'pm-dudu' }, cwd: '/r/dudu' }],
    agents: () => [{ address: 'tpm', status: pmStatus }],
    panes: () => [],
    spaces: () => [],
    shared: () => ({ pm: 'pm-dudu' }),
    setShared: () => {},
    props: () => ({}),
    openOverlay: () => '',
    closeOverlay: () => {},
    appWindow: () => ({}),
    pythonArgv: args => ['python3', ...args],
    execPython: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    exec: async (_cmd, args) => {
      const list = Array.isArray(args) ? args : [];
      if (list.includes('read')) {
        readCalls.push(list);
        return { code: 0, stdout: pmScreen, stderr: '' };
      }
      if (list.includes('send')) {
        const text = list[list.length - 1];
        if (sendBehavior === 'blocked_perm') {
          return { code: 1, stdout: '', stderr: 'tpm is blocked (permission)' };
        }
        sentMessages.push(text);
        return { code: 0, stdout: '', stderr: '' };
      }
      return { code: 0, stdout: '{}', stderr: '' };
    },
  };

  const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
  const timers = [];
  const spawns = [];
  const cx = {
    focus_handle: () => ({ focus() {} }),
    spawn: fn => { const p = Promise.resolve(fn(cx)); spawns.push(p); return p; },
    timer: { after: (_ms, fn) => { timers.push(fn); }, every: () => {} },
    notify: () => {},
    stop_propagation: () => {},
  };
  const drainSpawns = async () => {
    for (let i = 0; i < 6; i++) {
      await Promise.all(spawns.splice(0));
      await new Promise(r => setTimeout(r, 0));
    }
  };
  let boxVal = '';
  const makeInput = () => ({ value: () => boxVal, set_value(v) { boxVal = v; }, set_selected_range() {}, focus() {}, on() {}, set_auto_grow() {} });

  const view = Object.assign(Object.create(Mod.prototype), {
    state: { pms: [{ name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', pane: 'hc:tpm' }], tasks: [], events: [], lang: 'zh' },
    events: [], pending: [], pendingByPm: new Map(), seq: 0, pastes: [], error: '', logError: '',
    flushingQueue: false, queueTimer: false, pmDialog: null, pmDialogLoading: false, pmDialogAt: 0, pmSendBlockError: '',
    pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
    remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
    earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '/tmp/ledger', watching: {},
    thread: '', threadTask: null, detail: false, threadError: '', threadLog: null, threadLogKept: [],
    threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null, threadLogExpanded: false,
    epicOverrides: new Map(), expandedDone: new Set(), substepsToggle: {}, hoverKey: '',
    agentWindows: [], winSession: 'sess-1', lastWinEventSeq: 0, agentWindowSlot: 0,
    threadTab: 'log', sideTab: 'threads', librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: true,
    libraryProbed: true, libraryStale: false, libraryLoading: false, libraryAgain: false, libraryError: '',
    libraryClosed: new Set(), libraryQuery: '', libraryDropBusy: '', libraryDropError: '',
    memorySlug: 'dudu', memoryData: null, memoryRead: false, memoryStale: false, memoryLoading: false, memoryAgain: false, memoryError: '',
    memoryFoldOverrides: new Map(), memoryProjectOpen: true, memoryPersonalOpen: false, memoryCandidatesOpen: false,
    memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
    activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '',
    docShownBytes: model.DOC_INITIAL_BYTES, docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
    editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
    confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
    reattaching: '', reattachError: null, startingPm: '', startPmError: null,
    bringBackOpen: false, bringingBack: false, bringBackProgress: null,
    listShown: false, wide: true, measured: true, panelWant: null, panelDrag: null, viewWidth: 1280, gripLit: false,
    seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
    bell: null, flash: '', unfolded: new Map(), newest: '', atWork: new Set(),
    scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
    libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
    keyFocus: { focus() {} }, onStage: true, typing: '', mainKey: 'pm:pm-dudu', threadKey: '', outgoing: new Map(),
    files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
    input: makeInput(), threadInput: makeInput(), libraryInput: makeInput(), memoryInput: makeInput(), docFindInput: makeInput(),
    docNameInput: makeInput(), memDescInput: makeInput(), docEditorInput: makeInput(),
    refresh: () => {},
    readLog: () => {},
  });

  // 1) PM is blocked on a terminal question dialog -> banner explains the exact dialog reason.
  nodes.clear();
  view.render(cx);
  await drainSpawns();
  assert.ok(readCalls.length >= 1, 'probes PM terminal screen when blocked');
  nodes.clear();
  view.render(cx);
  const barText1 = nodes.get('pm-blocked-bar')?.allTexts().join(' ') || '';
  assert.match(barText1, /PM 正停在终端提问对话框上/);

  // 2) User sends two messages while PM is blocked -> both queue FIFO (zero hc send calls), marked "排队中", never lost.
  boxVal = '第一条消息';
  view.sendMain(cx);
  boxVal = '第二条消息';
  view.sendMain(cx);
  await drainSpawns();
  assert.deepEqual(sentMessages, [], 'must not fire hc send while PM is blocked');
  assert.equal(view.pending.length, 2);
  assert.equal(view.pending.every(p => p.queued && !p.failed), true);
  nodes.clear();
  view.render(cx);
  assert.match(nodes.get('pm-blocked-bar')?.allTexts().join(' ') || '', /2 条消息排队中/);
  assert.match(nodes.get(`queued-pending:${view.pending[0].id}`)?.allTexts().join(' ') || '', /排队中/);
  assert.match(nodes.get(`queued-pending:${view.pending[1].id}`)?.allTexts().join(' ') || '', /排队中/);

  // 3) PM becomes idle -> render immediately flushes both queued messages in FIFO order and clears banner.
  pmStatus = 'idle';
  nodes.clear();
  view.render(cx);
  await drainSpawns();
  assert.deepEqual(sentMessages, ['第一条消息', '第二条消息']);
  assert.equal(view.pending.every(p => !p.queued && !p.failed), true);
  nodes.clear();
  view.render(cx);
  assert.equal(nodes.has('pm-blocked-bar'), false, 'banner disappears once PM is idle and queue is empty');

  // 4) Race: PM looked idle, user sends a message, hc send rejects with "blocked (permission)" ->
  //    transitions seamlessly to queued (not failed), shows permission reason, and auto-delivers on retry!
  view.pending = [];
  sentMessages.length = 0;
  sendBehavior = 'blocked_perm';
  pmScreen = 'Bash command\nDo you want to proceed?\n1. Yes\n2. No';
  boxVal = '继续吧';
  view.sendMain(cx);
  await drainSpawns();
  assert.equal(view.pending.length, 1);
  assert.equal(view.pending[0].queued, true);
  assert.equal(Boolean(view.pending[0].failed), false);
  nodes.clear();
  view.render(cx);
  assert.match(nodes.get('pm-blocked-bar')?.allTexts().join(' ') || '', /权限确认/);

  // Next retry tick succeeds -> auto-delivers without user clicking retry!
  sendBehavior = 'ok';
  while (timers.length) {
    const fn = timers.shift();
    fn(cx);
    await drainSpawns();
  }
  assert.deepEqual(sentMessages, ['继续吧']);
  assert.equal(view.pending[0].queued, false);
  assert.equal(Boolean(view.pending[0].failed), false);
});

test('queued messages persist across mod reload / app restart and clear once delivered', async () => {
  // Pure model persistence helpers
  assert.deepEqual(model.readQueuedSends('not-json'), {});
  const stored1 = model.keepQueuedSends({}, 'pm-dudu', [
    { id: 1, text: '第一条', said: '第一条', words: '第一条', to: '', files: [], sentAt: 100, draftKey: 'pm:pm-dudu', queued: true },
    { id: 2, text: '已失败', said: '已失败', words: '已失败', to: '', files: [], sentAt: 200, draftKey: 'pm:pm-dudu', queued: false, failed: 'gone' },
  ]);
  assert.equal(stored1['pm-dudu'].length, 1);
  assert.equal(stored1['pm-dudu'][0].text, '第一条');
  const roundTrip = model.readQueuedSends(JSON.stringify(stored1));
  assert.equal(roundTrip['pm-dudu'].length, 1);
  assert.equal(roundTrip['pm-dudu'][0].queued, true);
  // Clearing all queued items deletes the PM key
  const cleared = model.keepQueuedSends(roundTrip, 'pm-dudu', [
    { id: 1, text: '第一条', queued: false, inFlight: false },
  ]);
  assert.deepEqual(cleared, {});

  // End-to-end PmProject reload test using shared localStorage
  const { readFileSync } = await import('node:fs');
  const mainSrc = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const source = mainSrc
    .replace(/^import[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/export\s+default\s+class\s+(\w+)/, 'class $1')
    + '\nreturn PmProject;\n';

  const backing = new Map();
  const fakeStorage = {
    getItem: k => (backing.has(k) ? backing.get(k) : null),
    setItem: (k, v) => { backing.set(k, String(v)); },
    removeItem: k => { backing.delete(k); },
  };
  const elProxy = () => {
    const node = {
      texts: [], kids: [],
      child(c) { if (c != null) this.kids.push(c); if (typeof c === 'string') this.texts.push(c); return p; },
      children(arr) { for (const c of arr || []) this.child(c); return p; },
      when(cond, fn) { return cond ? fn(p) : p; },
    };
    const p = new Proxy(node, { get(t, k) { return k in t ? t[k] : () => p; } });
    return p;
  };
  let pmStatus = 'blocked';
  const sentMessages = [];
  const stubs = {
    ...model,
    localStorage: fakeStorage,
    View: class {},
    div: elProxy, svg: elProxy, image: elProxy, v_flex: elProxy, h_flex: elProxy,
    TextView: { markdown: elProxy }, Textarea: { new: elProxy }, TextareaState: class {},
    Input: { new: elProxy }, InputState: class {}, ScrollHandle: class {}, Popup: { new: (_id, base) => base },
    theme: () => ({
      background: '#111', surface: '#181818', raised: '#222', hover: '#2a2a2a', border: '#333', input: '#444',
      foreground: '#eee', muted: '#999', dim: '#666', accent: '#60a5fa', blocked: '#f59e0b', done: '#22c55e',
      solid: '#eee', solid_foreground: '#111',
    }),
    home: () => '/tmp', appHome: () => '/tmp/herdr-app',
    readTextFile: async () => '', writeTextFile: async () => {}, watchFolder: async () => new Promise(() => {}),
    layout: () => ({}), run: () => {},
    terminals: () => [{ address: 'tpm', state: 'live', status: pmStatus, labels: { pm: 'pm-dudu' }, cwd: '/r/dudu' }],
    agents: () => [{ address: 'tpm', status: pmStatus }],
    panes: () => [], spaces: () => [], shared: () => ({ pm: 'pm-dudu' }), setShared: () => {}, props: () => ({}),
    openOverlay: () => '', closeOverlay: () => {}, appWindow: () => ({}),
    pythonArgv: args => ['python3', ...args],
    execPython: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    exec: async (_cmd, args) => {
      const list = Array.isArray(args) ? args : [];
      if (list.includes('read')) return { code: 0, stdout: 'Enter to select · ↑/↓ to navigate', stderr: '' };
      if (list.includes('send')) { sentMessages.push(list[list.length - 1]); return { code: 0, stdout: '', stderr: '' }; }
      return { code: 0, stdout: '{}', stderr: '' };
    },
  };
  const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
  const spawns = [];
  const cx = {
    focus_handle: () => ({ focus() {} }),
    spawn: fn => { const p = Promise.resolve(fn(cx)); spawns.push(p); return p; },
    timer: { after: () => {}, every: () => {} },
    notify: () => {}, stop_propagation: () => {},
  };
  const drainSpawns = async () => {
    for (let i = 0; i < 6; i++) {
      await Promise.all(spawns.splice(0));
      await new Promise(r => setTimeout(r, 0));
    }
  };
  let boxVal = '';
  const makeView = () => Object.assign(Object.create(Mod.prototype), {
    state: { pms: [{ name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', pane: 'hc:tpm' }], tasks: [], events: [], lang: 'zh' },
    events: [], pending: [], pendingByPm: new Map(), seq: 0, pastes: [], error: '', logError: '',
    flushingQueue: false, queueTimer: false, pmDialog: null, pmDialogLoading: false, pmDialogAt: 0, pmSendBlockError: '',
    pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
    remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
    earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '/tmp/ledger', watching: {},
    thread: '', threadTask: null, detail: false, threadError: '', threadLog: null, threadLogKept: [],
    threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null, threadLogExpanded: false,
    epicOverrides: new Map(), expandedDone: new Set(), substepsToggle: {}, hoverKey: '',
    agentWindows: [], winSession: 'sess-1', lastWinEventSeq: 0, agentWindowSlot: 0,
    threadTab: 'log', sideTab: 'threads', librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: true,
    libraryProbed: true, libraryStale: false, libraryLoading: false, libraryAgain: false, libraryError: '',
    libraryClosed: new Set(), libraryQuery: '', libraryDropBusy: '', libraryDropError: '',
    memorySlug: 'dudu', memoryData: null, memoryRead: false, memoryStale: false, memoryLoading: false, memoryAgain: false, memoryError: '',
    memoryFoldOverrides: new Map(), memoryProjectOpen: true, memoryPersonalOpen: false, memoryCandidatesOpen: false,
    memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
    activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '',
    docShownBytes: model.DOC_INITIAL_BYTES, docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
    editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
    confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
    reattaching: '', reattachError: null, startingPm: '', startPmError: null,
    bringBackOpen: false, bringingBack: false, bringBackProgress: null,
    listShown: false, wide: true, measured: true, panelWant: null, panelDrag: null, viewWidth: 1280, gripLit: false,
    seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
    bell: null, flash: '', unfolded: new Map(), newest: '', atWork: new Set(),
    scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
    libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
    keyFocus: { focus() {} }, onStage: true, typing: '', mainKey: 'pm:pm-dudu', threadKey: '', outgoing: new Map(),
    files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
    input: { value: () => boxVal, set_value(v) { boxVal = v; }, set_selected_range() {}, focus() {}, on() {}, set_auto_grow() {} },
    threadInput: { value: () => '', set_value() {}, set_selected_range() {}, focus() {}, on() {}, set_auto_grow() {} },
    libraryInput: { value: () => '', set_value() {}, set_selected_range() {}, focus() {}, on() {}, set_auto_grow() {} },
    memoryInput: { value: () => '', set_value() {}, set_selected_range() {}, focus() {}, on() {}, set_auto_grow() {} },
    docFindInput: { value: () => '', set_value() {}, set_selected_range() {}, focus() {}, on() {}, set_auto_grow() {} },
    docNameInput: { value: () => '', set_value() {}, set_selected_range() {}, focus() {}, on() {}, set_auto_grow() {} },
    memDescInput: { value: () => '', set_value() {}, set_selected_range() {}, focus() {}, on() {}, set_auto_grow() {} },
    docEditorInput: { value: () => '', set_value() {}, set_selected_range() {}, focus() {}, on() {}, set_auto_grow() {} },
    refresh: () => {}, readLog: () => {},
  });

  // Instance 1: queue 2 messages while PM is blocked -> persisted to localStorage.
  const view1 = makeView();
  boxVal = '重启前排队一';
  view1.sendMain(cx);
  boxVal = '重启前排队二';
  view1.sendMain(cx);
  await drainSpawns();
  const savedBefore = model.readQueuedSends(fakeStorage.getItem(model.QUEUE_KEY));
  assert.deepEqual(savedBefore['pm-dudu'].map(x => x.text), ['重启前排队一', '重启前排队二']);

  // Instance 2 (simulating mod reload / app restart): fresh empty memory, hydrates from localStorage!
  const view2 = makeView();
  view2.render(cx);
  await drainSpawns();
  assert.deepEqual(view2.pending.map(x => [x.text, x.queued]), [['重启前排队一', true], ['重启前排队二', true]]);
  assert.deepEqual(sentMessages, []);

  // PM unblocks -> Instance 2 delivers both FIFO; they stay stored as sent until the log has them,
  // then storage clears.
  pmStatus = 'idle';
  view2.render(cx);
  await drainSpawns();
  assert.deepEqual(sentMessages, ['重启前排队一', '重启前排队二']);
  assert.deepEqual(model.readQueuedSends(fakeStorage.getItem(model.QUEUE_KEY))['pm-dudu'].map(x => x.stage), ['delivered', 'delivered']);
  view2.events = [
    { at: '2099-01-01 00:00:00', type: 'user', text: '重启前排队一' },
    { at: '2099-01-01 00:00:00', type: 'user', text: '重启前排队二' },
  ];
  view2.reconcilePending(cx, { forceLogReady: true });
  assert.equal(fakeStorage.getItem(model.QUEUE_KEY), null);
});

test('tooltipMaxWidth, wrapTooltipText, clampTooltipRect, and tooltipLayout bound width, wrap/truncate lines, and stay in panel/window', () => {
  // Width cap: <= 420px even in wide panels/windows, and bounded to panel/viewport minus margins.
  assert.equal(model.tooltipMaxWidth({ panelWidth: 600, viewWidth: 1600 }), 420);
  assert.equal(model.tooltipMaxWidth({ panelWidth: 360, viewWidth: 1280 }), 328);
  assert.equal(model.tooltipMaxWidth({ panelWidth: 0, viewWidth: 280 }), 248);
  assert.equal(model.tooltipMaxWidth({ maxWidth: 900, viewWidth: 1920 }), 420);

  // Short labels stay compact and unwrapped.
  const shortLayout = model.tooltipLayout('关闭', { panelWidth: 360, viewWidth: 1280 });
  assert.equal(shortLayout.truncated, false);
  assert.deepEqual(shortLayout.lines, ['关闭']);
  assert.ok(shortLayout.width >= model.TOOLTIP_MIN_WIDTH && shortLayout.width <= 100);

  // Long CJK + English log entry (like the reported overflow bug) wraps and truncates at maxLines with ellipsis.
  const longLog = '用户补充真正的问题：「当时造成的问题是，我在 project 这边手动输入的无法发送。」——PM 停在 AskUserQuestion 的终端对话框上时，项目输入框的消息发不进去 (hc send 等不到可输入状态)。所以：1) AskUserQuestion 这类会把 PM 终端卡在对话框上的工具，钩子应拦下 (deny 并提示改用问题卡)，不要让 PM 进入阻塞对话框；2) 项目输入框在 PM 暂时不能接收时，消息不能丢也不能看似发不出：显示“排队中”，等 PM 空闲后自动补发。';
  const logLayout = model.tooltipLayout(longLog, { panelWidth: 360, viewWidth: 1280, placement: 'above-left' });
  assert.ok(logLayout.width <= 328 && logLayout.maxWidth <= 328 && logLayout.maxWidth <= 420);
  assert.equal(logLayout.lines.length, model.TOOLTIP_MAX_LINES);
  assert.equal(logLayout.truncated, true);
  assert.ok(logLayout.lines[logLayout.lines.length - 1].endsWith('…'));
  assert.equal(logLayout.anchor, 'bottom_left');
  assert.deepEqual(logLayout.pos, { left: 0, top: -model.TOOLTIP_GAP });

  // Explicit newlines and long unbroken paths/tokens wrap cleanly without overflowing.
  const multi = model.wrapTooltipText('abc1234\nfeat(ui): very-long-unbroken-segment-/Users/dev/.herdr/worktrees/dudu/dev-log-tooltip-overflow/mods/pm-project/main.js', 240, { maxLines: 4 });
  assert.ok(multi.lines.length >= 2 && multi.lines.length <= 4);

  // Placement mapping for topbar/right-aligned controls.
  const topLeft = model.tooltipLayout('Title', { panelWidth: 360, placement: 'below-left' });
  assert.equal(topLeft.anchor, 'top_left');
  assert.deepEqual(topLeft.pos, { left: 0, bottom: -model.TOOLTIP_GAP });
  const topRight = model.tooltipLayout('Close', { panelWidth: 360, placement: 'below-right' });
  assert.equal(topRight.anchor, 'top_right');
  assert.deepEqual(topRight.pos, { right: 0, bottom: -model.TOOLTIP_GAP });

  // Boundary clamping: flips above->below near top edge and clamps X inside panel bounds.
  const panelBounds = { x: 920, y: 0, w: 360, h: 700 };
  const nearTop = model.clampTooltipRect(
    { x: 930, y: 12, w: 320, h: 24 },
    { w: 300, h: 80 },
    panelBounds,
    { placement: 'above-left' },
  );
  assert.equal(nearTop.placement, 'below-left');
  assert.ok(nearTop.y >= 36, 'flips below trigger when above would clip top edge');
  assert.ok(nearTop.x >= panelBounds.x + model.TOOLTIP_MARGIN);
  assert.ok(nearTop.x + nearTop.w <= panelBounds.x + panelBounds.w - model.TOOLTIP_MARGIN);

  // Boundary clamping: flips below->above near bottom edge and clamps right-aligned card inside panel.
  const nearBottom = model.clampTooltipRect(
    { x: 1240, y: 660, w: 24, h: 24 },
    { w: 280, h: 80 },
    panelBounds,
    { placement: 'below-right' },
  );
  assert.equal(nearBottom.placement, 'above-right');
  assert.ok(nearBottom.y + nearBottom.h <= panelBounds.y + panelBounds.h - model.TOOLTIP_MARGIN);
  assert.ok(nearBottom.x >= panelBounds.x + model.TOOLTIP_MARGIN);
  assert.ok(nearBottom.x + nearBottom.w <= panelBounds.x + panelBounds.w - model.TOOLTIP_MARGIN);
});

test('PmProject thread detail renders bounded wrapped Popup hover tips for log rows, steps, and topbar with zero native tooltips', async () => {
  const nodes = new Map();
  const nativeTips = [];
  const makeEl = (tag) => {
    const rec = {
      tag, id: '', texts: [], kids: [], hover: null, wheel: null, keyDown: null,
      w: null, maxW: null, anchor: null, whitespaceNormal: false, content: null,
      allTexts() {
        const out = [...this.texts];
        if (this.content) out.push(...this.content.allTexts());
        for (const k of this.kids) if (k && typeof k.allTexts === 'function') out.push(...k.allTexts());
        return out;
      },
    };
    const proxy = new Proxy({}, {
      get(_t, key) {
        if (key === '__rec') return rec;
        if (key === 'then') return undefined;
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0] || ''); nodes.set(rec.id, rec); }
          else if (key === 'tooltip') nativeTips.push(args[0]);
          else if (key === 'w') rec.w = args[0];
          else if (key === 'max_w') rec.maxW = args[0];
          else if (key === 'anchor') rec.anchor = args[0];
          else if (key === 'whitespace_normal') rec.whitespaceNormal = true;
          else if (key === 'on_hover') rec.hover = args[0];
          else if (key === 'on_scroll_wheel') rec.wheel = args[0];
          else if (key === 'on_key_down') rec.keyDown = args[0];
          else if (key === 'when') { if (args[0]) args[1](proxy); }
          else if (key === 'content') { rec.content = args[0]?.__rec || null; }
          else if (key === 'child') {
            const c = args[0];
            if (typeof c === 'string') rec.texts.push(c);
            else if (c?.__rec) rec.kids.push(c.__rec);
          } else if (key === 'children') {
            for (const c of (args[0] || [])) {
              if (typeof c === 'string') rec.texts.push(c);
              else if (c?.__rec) rec.kids.push(c.__rec);
            }
          }
          return proxy;
        };
      },
    });
    return proxy;
  };
  const stub = (name) => Object.assign((...a) => makeEl(name), {
    new: (id, trigger) => {
      const p = makeEl(name);
      if (id) p.id(id);
      if (trigger) p.child(trigger);
      return p;
    },
    markdown: (id, t) => makeEl('md').id(id).child(t),
    html: (id, t) => makeEl('html').id(id).child(t),
  });
  const baseUrl = new URL('./main.js', import.meta.url).href;
  const loaderSrc = `
    export async function load(url, ctx, next) {
      if (url === 'mock:gpui-kit') return { format: 'module', shortCircuit: true, source: 'export class View {} export const div = (...a) => globalThis.__tipKit.div(...a), svg = (...a) => globalThis.__tipKit.svg(...a), image = (...a) => globalThis.__tipKit.image(...a);' };
      if (url === 'mock:gpui-base') return { format: 'module', shortCircuit: true, source: 'export const v_flex = (...a) => globalThis.__tipKit.v_flex(...a), h_flex = (...a) => globalThis.__tipKit.h_flex(...a), TextView = { markdown: (...a) => globalThis.__tipKit.TextView.markdown(...a), html: (...a) => globalThis.__tipKit.TextView.html(...a) }, TextareaState = { new: (...a) => globalThis.__tipKit.TextareaState.new(...a) }, Textarea = { new: (...a) => globalThis.__tipKit.Textarea.new(...a) }, InputState = { new: (...a) => globalThis.__tipKit.InputState.new(...a) }, Input = { new: (...a) => globalThis.__tipKit.Input.new(...a) }, ScrollHandle = { new: (...a) => globalThis.__tipKit.ScrollHandle.new(...a) }, Scrollbar = { vertical: (...a) => globalThis.__tipKit.div(...a), new: (...a) => globalThis.__tipKit.div(...a) }, Popup = { new: (...a) => globalThis.__tipKit.Popup.new(...a) };' };
      if (url === 'mock:herdr') return { format: 'module', shortCircuit: true, source: 'export const theme = () => ({ canvas: "#111111", background: "#111111", chrome: "#161616", surface: "#1c1c1c", raised: "#242424", popover: "#262626", border: "#333333", input: "#333333", foreground: "#eeeeee", muted: "#aaaaaa", dim: "#777777", accent: "#44aaff", blocked: "#ff5555", working: "#44cc44", ansi2: "#44cc44", ansi3: "#ffaa00", hover: "#2a2a2a", solid: "#eeeeee", solid_foreground: "#111111" }), home = () => "/tmp", appHome = () => "/tmp", exec = async () => ({ code: 0, stdout: "", stderr: "" }), readTextFile = async () => "", writeTextFile = async () => {}, watchFolder = () => ({ cancel() {} }), layout = () => ({ active: "pm-project", children: [] }), run = () => {}, terminals = () => [], agents = () => [], panes = () => [], spaces = () => [], shared = () => ({ pm: "pm-dudu", machine: "" }), setShared = () => {}, props = () => ({}), openOverlay = () => {}, closeOverlay = () => {}, window = () => ({ platform: "macos", set_title() {} });' };
      return next(url, ctx);
    }
    export async function resolve(spec, ctx, next) {
      if (spec === 'gpui-kit') return { url: 'mock:gpui-kit', shortCircuit: true };
      if (spec === 'gpui-base') return { url: 'mock:gpui-base', shortCircuit: true };
      if (spec === 'herdr') return { url: 'mock:herdr', shortCircuit: true };
      return next(spec, ctx);
    }
  `;
  const { register } = await import('node:module');
  register('data:text/javascript,' + encodeURIComponent(loaderSrc));
  const stateStub = () => new Proxy({
    set_value() {}, value: () => '', focus() {}, is_focused: () => false,
  }, { get: (o, k) => (k in o ? o[k] : () => {}) });
  globalThis.__tipKit = {
    div: stub('div'), svg: stub('svg'), image: stub('image'),
    v_flex: stub('v_flex'), h_flex: stub('h_flex'),
    TextView: stub('TextView'), Textarea: stub('Textarea'), Input: stub('Input'), Popup: stub('Popup'),
    TextareaState: { new: stateStub },
    InputState: { new: stateStub },
    ScrollHandle: { new: () => ({ scroll_to_item() {}, offset: () => ({ x: 0, y: 0 }) }) },
  };
  const { default: PmProject } = await import(`${baseUrl}?tooltip-test=${Date.now()}`);
  const cx = { notify() {}, spawn() {}, timer: { after() { return { cancel() {} }; }, every() { return { cancel() {} }; } }, focus_handle: () => ({ focus() {}, is_focused: () => false }), stop_propagation() {} };
  const view = new PmProject();
  view.init({}, cx);
  view.viewWidth = 1280;
  view.wide = true;
  view.panelWant = 360;
  view.machine = '';
  view.stateFor = '';
  view.pmName = 'pm-dudu';
  view.detail = true;
  view.thread = 'dudu-long-log';
  const longEntry = '用户补充真正的问题：「当时造成的问题是，我在 project 这边手动输入的无法发送。」——PM 停在 AskUserQuestion 的终端对话框上时，项目输入框的消息发不进去 (hc send 等不到可输入状态)。所以：1) AskUserQuestion 这类会把 PM 终端卡在对话框上的工具，钩子应拦下 (deny 并提示改用问题卡)，不要让 PM 进入阻塞对话框；2) 项目输入框在 PM 暂时不能接收时，消息不能丢也不能看似发不出：显示“排队中”，等 PM 空闲后自动补发。';
  view.state = {
    lang: 'zh',
    pms: [{ name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', context_tokens: 120000 }],
    tasks: [{
      id: 'dudu-long-log',
      pm: 'pm-dudu',
      title: 'PM 提问显示成问题卡，并且很长的标题也要在面板宽度内换行而不是横穿窗口',
      status: 'in_progress',
      branch: 'dev/pm-question-cards',
      plan: '[>] 实现与单测 — 包含非常长的步骤说明文字，悬停时应自动换行并限制在面板宽度内; [ ] 审查',
      log: [
        { n: 1, at: '2026-11-22T01:54:00', text: 'registered (in_progress)' },
        { n: 2, at: '2026-11-22T01:55:00', text: longEntry },
      ],
    }],
  };
  view.threadTask = view.state.tasks[0];
  view.threadLog = { entries: view.state.tasks[0].log, earlier: 0 };

  // Initial render: zero native .tooltip() calls anywhere.
  nodes.clear();
  nativeTips.length = 0;
  view.render(cx);
  assert.equal(nativeTips.length, 0, 'PmProject must not emit unbounded native .tooltip() calls');

  // Hovering long log row opens bounded, wrapped, truncated Popup anchored above-left inside the 360px panel.
  assert.ok(nodes.has('thread-entry-2'), `expected thread-entry-2, got: ${[...nodes.keys()].join(', ')}`);
  nodes.get('thread-entry-2').hover(true, cx);
  nodes.clear();
  view.render(cx);
  const logPop = nodes.get('hover-tip-thread-entry-2');
  assert.ok(logPop && logPop.content, 'log row hover renders Popup card');
  assert.equal(logPop.anchor, 'bottom_left');
  assert.ok(logPop.content.w <= 328 && logPop.content.maxW <= 328, `card width (${logPop.content.w}) must stay within 360px panel`);
  assert.ok(logPop.content.kids.length >= 2 && logPop.content.kids.length <= model.TOOLTIP_MAX_LINES, 'long log wraps across multiple bounded lines');
  assert.ok(logPop.content.kids.every(k => k.whitespaceNormal), 'wrapped lines enable whitespace_normal');
  assert.ok(logPop.allTexts().at(-1).endsWith('…'), 'overflowing log tip truncates with ellipsis');

  // Scrolling thread log dismisses the hover tooltip.
  nodes.get('thread-log').wheel({ delta: { y: -20 } }, cx);
  assert.equal(view.hoverKey, '');

  // Hovering topbar title anchors below-left (`top_left`) and topbar close anchors below-right (`top_right`).
  nodes.clear();
  view.render(cx);
  nodes.get('thread-title').hover(true, cx);
  nodes.clear();
  view.render(cx);
  const titlePop = nodes.get('hover-tip-thread-title');
  assert.ok(titlePop && titlePop.content);
  assert.equal(titlePop.anchor, 'top_left');
  assert.ok(titlePop.content.maxW <= 328);

  nodes.get('thread-close').hover(true, cx);
  nodes.clear();
  view.render(cx);
  const closePop = nodes.get('hover-tip-thread-close');
  assert.ok(closePop && closePop.content);
  assert.equal(closePop.anchor, 'top_right');
  assert.equal(nativeTips.length, 0, 'even with hover tips open, zero native .tooltip() calls are emitted');
  delete globalThis.__tipKit;
});

test('resolveAgentProgram, threadAgents, Threads sub-rows, and agent window titlebar use program icon with generic agent.svg fallback (never terminal.svg)', async () => {
  const claudeProg = { key: 'claude', name: 'Claude Code', icon: 'icons/claude.svg', tint: true, shell: false, agent: true };
  const codexProg = { key: 'codex', name: 'Codex', icon: 'icons/codex.png', tint: false, shell: false, agent: true };
  const shellProg = { key: 'shell', name: 'zsh', icon: 'icons/shell.svg', tint: true, shell: true, agent: false };

  const task = {
    id: 't-icons',
    pm: 'pm-dudu',
    title: 'Icon test',
    status: 'in_progress',
    pane: 'hc:tw1',
    engine: { kind: 'claude' },
    review: { id: 't-icons-rev', review_of: 't-icons', status: 'in_progress', pane: 'hc:tr1', engine: { kind: 'codex' } },
    helpers: [
      { name: 'ended-claude', kind: 'claude-code', status: 'done' },
      { name: 'unknown-helper', kind: 'custom-bot', status: 'done' },
    ],
  };
  const terms = [
    { address: 'tw1', state: 'live', status: 'working', labels: { task: 't-icons' }, program: claudeProg },
    { address: 'tr1', state: 'live', status: 'working', labels: { task: 't-icons-rev' }, program: codexProg },
    { address: 'th1', state: 'live', status: 'working', labels: { 'helper.of': 't-icons', helper: 'shell-helper' }, program: shellProg },
  ];
  const info = model.threadAgents(task, { terms, live: [], lang: 'en' });
  const byKey = new Map(info.all.map(a => [a.key, a]));
  assert.deepEqual(byKey.get('worker:t-icons')?.program, { key: 'claude', name: 'Claude Code', icon: 'icons/claude.svg', tint: true });
  assert.deepEqual(byKey.get('review:t-icons-rev')?.program, { key: 'codex', name: 'Codex', icon: 'icons/codex.png', tint: false });
  assert.deepEqual(byKey.get('helper:t-icons:ended-claude#0')?.program, { key: 'claude', name: 'Claude Code', icon: 'icons/claude.svg', tint: true }, 'ended claude-code helper reuses catalog icon');
  assert.equal(byKey.get('helper:t-icons:unknown-helper#1')?.program, null, 'unknown helper falls back to generic agent icon');
  assert.equal(byKey.get('helper:t-icons:th1')?.program, null, 'shell program is ignored so terminal/shell icon is not used');

  // Verify UI rendering in Threads list sub-rows & agent small window titlebar.
  const nodes = new Map();
  const makeEl = (tag, src = '') => {
    const rec = {
      tag, src, id: '', kids: [],
      collectSrcs() {
        const out = this.src ? [`${this.tag}:${this.src}`] : [];
        for (const k of this.kids) if (k && typeof k.collectSrcs === 'function') out.push(...k.collectSrcs());
        return out;
      },
    };
    const proxy = new Proxy({}, {
      get(_t, key) {
        if (key === '__rec') return rec;
        if (key === 'then') return undefined;
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0] || ''); nodes.set(rec.id, rec); }
          else if (key === 'when') { if (args[0]) args[1](proxy); }
          else if (key === 'child') { if (args[0]?.__rec) rec.kids.push(args[0].__rec); }
          else if (key === 'children') { for (const c of (args[0] || [])) if (c?.__rec) rec.kids.push(c.__rec); }
          return proxy;
        };
      },
    });
    return proxy;
  };
  const stub = (name) => Object.assign((...a) => makeEl(name, typeof a[0] === 'string' ? a[0] : ''), {
    new: (id, trigger) => { const p = makeEl(name); if (id) p.id(id); if (trigger) p.child(trigger); return p; },
    markdown: (id) => makeEl('md').id(id),
    html: (id) => makeEl('html').id(id),
  });
  const stateStub = () => new Proxy({ set_value() {}, value: () => '', focus() {}, is_focused: () => false }, { get: (o, k) => (k in o ? o[k] : () => {}) });
  globalThis.__tipKit = {
    div: stub('div'), svg: stub('svg'), image: stub('image'),
    v_flex: stub('v_flex'), h_flex: stub('h_flex'),
    TextView: stub('TextView'), Textarea: stub('Textarea'), Input: stub('Input'), Popup: stub('Popup'),
    TextareaState: { new: stateStub },
    InputState: { new: stateStub },
    ScrollHandle: { new: () => ({ scroll_to_item() {}, offset: () => ({ x: 0, y: 0 }) }) },
  };
  const baseUrl = new URL('./main.js', import.meta.url).href;
  const { default: PmProject } = await import(`${baseUrl}?agent-icon-test=${Date.now()}`);
  const cx = { notify() {}, spawn() {}, timer: { after() { return { cancel() {} }; }, every() { return { cancel() {} }; } }, focus_handle: () => ({ focus() {}, is_focused: () => false }), stop_propagation() {} };
  const view = new PmProject();
  view.init({}, cx);
  view.viewWidth = 1280; view.wide = true; view.panelWant = 360; view.machine = ''; view.stateFor = ''; view.pmName = 'pm-dudu';
  view.terms = () => terms;
  view.live = () => [];
  view.state = {
    lang: 'en',
    pms: [{ name: 'pm-dudu', project: 'dudu', repo: '/r/dudu' }],
    tasks: [task, task.review],
  };

  nodes.clear();
  view.render(cx);
  const workerSrcs = nodes.get('agent-row-worker:t-icons')?.collectSrcs() || [];
  assert.ok(workerSrcs.includes('svg:icons/claude.svg'), `worker row should render claude svg, got ${workerSrcs}`);
  assert.ok(!workerSrcs.some(s => s.includes('terminal.svg')), 'worker row must not render terminal.svg');
  const reviewSrcs = nodes.get('agent-row-review:t-icons-rev')?.collectSrcs() || [];
  assert.ok(reviewSrcs.includes('image:icons/codex.png'), `review row should render codex image, got ${reviewSrcs}`);
  const fallbackSrcs = nodes.get('agent-row-helper:t-icons:th1')?.collectSrcs() || [];
  assert.ok(fallbackSrcs.includes('svg:mods/pm-project/agent.svg'), `fallback helper row should render generic agent.svg, got ${fallbackSrcs}`);
  assert.ok(!fallbackSrcs.some(s => s.includes('terminal.svg')), 'fallback helper row must not render terminal.svg');

  // Agent small window titlebar shows program icon (and generic agent.svg fallback).
  const winView = new PmProject();
  winView.agentWindow = 'titlebar';
  winView.lang = 'en';
  winView.winProps = { key: 'worker:t-icons', role: 'worker', roleLabel: 'worker', name: 't-icons', program: claudeProg };
  nodes.clear();
  winView.render(cx);
  assert.ok((nodes.get('win-titlebar-worker:t-icons')?.collectSrcs() || []).includes('svg:icons/claude.svg'));
  winView.winProps = { key: 'worker:fallback', role: 'worker', roleLabel: 'worker', name: 'fallback', program: null };
  nodes.clear();
  winView.render(cx);
  assert.ok((nodes.get('win-titlebar-worker:fallback')?.collectSrcs() || []).includes('svg:mods/pm-project/agent.svg'));
  delete globalThis.__tipKit;
});

test('Interface I pure search engine: i18n, highlightSegments, threads (#num & logs), messages, decisions dedup, library, scope & Esc helpers', () => {
  const {
    SEARCH_STRINGS, taskNumber, formatTaskNumber, rowOfKey, highlightSegments, windowAroundMatch,
    searchShortcutLabel, escapeStep, buildMentionMenu, timeline, timelineRows, turns,
  } = model;
  const {
    searchProjectThreads, searchProjectMessages, searchProjectDecisions, searchProjectLibrary,
    buildProjectSearch, stepSearchSelection, stepSearchScope, stepSearchEscape,
  } = searchMod;

  // 1) SEARCH_STRINGS en/zh parity
  assert.deepEqual(Object.keys(SEARCH_STRINGS.en).sort(), Object.keys(SEARCH_STRINGS.zh).sort());
  assert.equal(searchShortcutLabel('macos'), '⌘K');
  assert.equal(searchShortcutLabel('linux'), 'Ctrl+K');

  // 2) taskNumber / formatTaskNumber / rowOfKey
  assert.equal(taskNumber({ number: 42 }), 42);
  assert.equal(taskNumber({ num: 7 }), 7);
  assert.equal(taskNumber({ number: 0 }), null);
  assert.equal(formatTaskNumber({ number: 42 }), '#42');
  assert.equal(formatTaskNumber({}), '');

  // 3) highlightSegments (case-insensitive, multi-term, overlap merge, CJK)
  const segs1 = highlightSegments('Fix Search in SearchBar', ['search']);
  assert.deepEqual(segs1, [
    { text: 'Fix ', match: false },
    { text: 'Search', match: true },
    { text: ' in ', match: false },
    { text: 'Search', match: true },
    { text: 'Bar', match: false },
  ]);
  const segs2 = highlightSegments('统一项目搜索入口', ['项目', '项目搜索']);
  assert.deepEqual(segs2, [
    { text: '统一', match: false },
    { text: '项目搜索', match: true },
    { text: '入口', match: false },
  ]);
  assert.equal(segs2.map(s => s.text).join(''), '统一项目搜索入口');

  const longWin = windowAroundMatch('前导文本很长很长 '.repeat(12) + '关键命中词在后面' + ' 结尾文本'.repeat(4), ['关键命中词'], 48, 14);
  assert.match(longWin, /^…/);
  assert.match(longWin, /关键命中词/);

  // 4) escapeStep ordering with projectSearch
  assert.equal(escapeStep({ mention: true, projectSearch: true }), 'mention');
  assert.equal(escapeStep({ projectSearch: true, answering: true }), 'projectSearch');

  // 5) @ mention supports #42 & 42 when task carries number
  const mentionThreads = {
    open: [{ task: 't-search', title: 'Project Search', status: 'in_progress', group: 'working', tone: 'running', branch: 'dev/search' }],
    sessions: [],
    finished: [{ task: 't-old', title: 'Old Task', status: 'done' }],
  };
  const mentionTasks = [
    { id: 't-search', number: 42, title: 'Project Search', status: 'in_progress' },
    { id: 't-old', num: 15, title: 'Old Task', status: 'done' },
  ];
  const mNum = buildMentionMenu({ lang: 'zh', query: '#42', threads: mentionThreads, tasks: mentionTasks });
  assert.equal(mNum.items[0]?.target, 't-search');
  assert.match(mNum.items[0]?.subtitle || '', /#42/);

  // 6) searchProjectThreads: #number, title, recent logs (latest, stateEvents, events, threadLog), review folding, abandoned excluded
  const pm = { name: 'pm-dudu', project: 'dudu' };
  const tasks = [
    { id: 't-1', pm: 'pm-dudu', number: 42, title: 'Interface I 搜索', status: 'in_progress', branch: 'dev/i', latest: 'Implementing palette', updated: '2026-11-22 01:40' },
    { id: 't-2', pm: 'pm-dudu', number: 43, title: 'Sidebar Polish', status: 'review', latest: 'status=review; ready', updated: '2026-11-22 01:30' },
    { id: 't-2-review', pm: 'pm-dudu', title: 'Review Sidebar Polish', status: 'in_progress', review_of: 't-2', latest: 'checked icons ok', updated: '2026-11-22 01:35' },
    { id: 't-3', pm: 'pm-dudu', number: 12, title: 'Abandoned Spike', status: 'abandoned', latest: 'dropped', updated: '2026-11-20 10:00' },
  ];
  const stateEvents = [{ task: 't-1', text: 'status=in_progress; added fuzzy highlight', at: '2026-11-22 01:38' }];
  const convEvents = [
    { at: '2026-11-21 09:00:00', type: 'user', text: '请开始做 [@Interface I](thread:t-1) 的统一搜索' },
    { at: '2026-11-21 09:01:00', type: 'pm', text: '收到，准备从第一性原理设计搜索。' },
    { at: '2026-11-21 09:02:00', type: 'decision', text: '使用 Cmd+K 统一项目搜索入口', quote: '不要做三套搜索' },
    { at: '2026-11-21 09:03:00', type: 'decision', text: '临时测试决定只保留在对话', quote: '试一下' },
    { at: '2026-11-21 09:04:00', type: 'thread', task: 't-1', status: 'in_progress', title: 'Interface I 搜索', text: 'earlier milestone log' },
    { at: '2026-11-21 09:05:00', type: 'thread', task: 't-2', status: 'blocked', title: 'Sidebar Polish', text: 'Pick layout style?', options: ['Compact', 'Spacious'] },
  ];
  const threadLog = { entries: [{ n: 1, at: '2026-11-22 01:10', text: 'detail log uniqueToken99' }] };

  const byHash = searchProjectThreads({ pm, tasks, stateEvents, events: convEvents, query: '#42', lang: 'en' });
  assert.equal(byHash.length, 1);
  assert.equal(byHash[0].task, 't-1');
  assert.equal(byHash[0].numTag, '#42');

  const byBareNum = searchProjectThreads({ pm, tasks, stateEvents, events: convEvents, query: '42', lang: 'en' });
  assert.equal(byBareNum[0]?.task, 't-1');

  const byThreadLog = searchProjectThreads({
    pm, tasks, stateEvents, events: convEvents, threadId: 't-1', threadLog, query: 'uniqueToken99', lang: 'en',
  });
  assert.equal(byThreadLog.length, 1);
  assert.equal(byThreadLog[0].matchInLog, true);
  assert.match(byThreadLog[0].snippet, /uniqueToken99/);

  const byReviewLog = searchProjectThreads({ pm, tasks, stateEvents, events: convEvents, query: 'icons ok', lang: 'en' });
  assert.equal(byReviewLog[0]?.task, 't-2', 'folded review log attributes to parent task');

  assert.equal(searchProjectThreads({ pm, tasks, query: 'Abandoned Spike', lang: 'en' }).length, 0);

  // 7) searchProjectMessages & rowOfKey
  const items = timeline(convEvents, tasks, { today: '2026-11-21', pm: 'pm-dudu' });
  const rows = timelineRows(turns(items, ''));
  const msgHits = searchProjectMessages({ items, lang: 'zh', today: '2026-11-21', query: '统一搜索' });
  assert.equal(msgHits.length, 1);
  assert.equal(msgHits[0].speaker, '你');
  assert.ok(rowOfKey(rows, msgHits[0].itemKey) >= 0);
  const qHits = searchProjectMessages({ items, lang: 'en', today: '2026-11-21', query: 'Spacious' });
  assert.equal(qHits.length, 1);
  assert.equal(qHits[0].msgKind, 'question');

  // 8) searchProjectDecisions: Memory tiers + conversation decision dedup
  const memoryData = {
    files: [
      { layer: 'project', root: 'memory', path: 'unified-search.md', name: 'unified-search', type: 'project', topic: 'ui',
        description: '使用 Cmd+K 统一项目搜索入口', quote: '不要做三套搜索', modified: '2026-11-22T01:00:00Z' },
      { layer: 'project', root: 'memory', path: 'search-pitfall.md', name: 'search-pitfall', type: 'pitfall', topic: 'pitfalls',
        description: 'Avoid Cmd+K conflict with terminal search', modified: '2026-11-21T08:00:00Z' },
    ],
  };
  const decHits = searchProjectDecisions({ memoryData, items, lang: 'zh', currentYear: '2026', today: '2026-11-21', query: '搜索' });
  assert.equal(decHits[0].kind, 'memory');
  assert.equal(decHits[0].title, 'unified-search');
  assert.equal(decHits.some(h => h.kind === 'decisionEvent' && h.title.includes('统一项目搜索入口')), false,
    'conversation decision duplicated in memory must be deduplicated');

  const convOnlyDec = searchProjectDecisions({ memoryData, items, lang: 'zh', currentYear: '2026', today: '2026-11-21', query: '临时测试决定' });
  assert.equal(convOnlyDec.length, 1);
  assert.equal(convOnlyDec[0].kind, 'decisionEvent');

  // 9) searchProjectLibrary + buildProjectSearch + navigation helpers
  const libraryFiles = [
    { root: 'docs', path: 'search-spec.md', kind: 'md', size: 420, modified: '2026-11-22T00:10:00Z', title: '统一搜索设计' },
  ];
  assert.equal(searchProjectLibrary({ libraryFiles, lang: 'zh', currentYear: '2026', query: '搜索设计' }).length, 1);

  const built = buildProjectSearch({
    pm, tasks, stateEvents, events: convEvents, items, memoryData, libraryFiles,
    lang: 'zh', today: '2026-11-21', query: '搜索', scope: 'all',
  });
  assert.ok(built.groups.some(g => g.id === 'threads'));
  assert.ok(built.groups.some(g => g.id === 'messages'));
  assert.ok(built.groups.some(g => g.id === 'decisions'));
  assert.ok(built.groups.some(g => g.id === 'library'));
  assert.equal(built.earliestLoadedDate, '11-21');

  const manyMsgs = Array.from({ length: 9 }, (_, i) => ({
    kind: 'pm', key: `pm:2026-11-21 10:0${i}:00:`, at: `2026-11-21 10:0${i}:00`, text: `needle hit ${i}`,
  }));
  const capped = buildProjectSearch({ pm, tasks: [], events: [], items: manyMsgs, lang: 'en', today: '2026-11-21', query: 'needle', scope: 'all' });
  assert.equal(capped.groups[0].items.filter(x => x.kind !== 'more').length, 6);
  assert.equal(capped.groups[0].items.at(-1)?.kind, 'more');
  assert.equal(capped.groups[0].items.at(-1)?.total, 9);

  assert.equal(stepSearchSelection(built.flat, 0, built.flat[0].key, -1).index, built.flat.length - 1);
  assert.equal(stepSearchScope('all', built.scopes, 1), 'threads');
  assert.equal(stepSearchScope('all', built.scopes, -1), 'library');
  assert.deepEqual(stepSearchEscape({ query: 'abc', scope: 'threads' }), { action: 'clear' });
  assert.deepEqual(stepSearchEscape({ query: '', scope: 'threads' }), { action: 'resetScope' });
  assert.deepEqual(stepSearchEscape({ query: '', scope: 'all' }), { action: 'close' });
});

test('PmProject Interface I Project Search UI: entry, shortcuts, lazy load, highlights, jumps, earlier load-more & Esc stack (en & zh)', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '').replace('export default class PmProject extends View', 'return class');

  const nodes = new Map();
  const actionsByCtx = new Map();
  const timers = [];
  const scrolled = [];
  const searchScrolled = [];
  let execCalls = [];
  let memReads = 0;
  let libReads = 0;
  let docReads = 0;
  let platform = 'macos';
  let oldRemote = false;

  const allTexts = rec => [...rec.texts, ...rec.kids.flatMap(allTexts)];
  const makeEl = () => {
    const rec = { id: '', texts: [], kids: [], tips: [], clicks: null, mouseDowns: [], keyDowns: [], actions: new Map(), ctx: '', svgs: [] };
    const proxy = new Proxy(() => proxy, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        if (key === '__allTexts') return () => allTexts(rec);
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') { if (typeof args[0] === 'string') rec.texts.push(args[0]); else if (args[0]?.__rec) rec.kids.push(args[0].__rec); }
          else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) { if (typeof k === 'string') rec.texts.push(k); else if (k?.__rec) rec.kids.push(k.__rec); }
          }
          else if (key === 'content' && args[0]?.__rec) rec.kids.push(args[0].__rec);
          else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'on_mouse_down') rec.mouseDowns.push(args[1] || args[0]);
          else if (key === 'on_key_down') rec.keyDowns.push(args[0]);
          else if (key === 'key_context') { rec.ctx = args[0]; actionsByCtx.set(rec.ctx, rec.actions); }
          else if (key === 'on_action') rec.actions.set(args[0], args[1]);
          else if (key === 'tooltip') rec.tips.push(args[0]);
          else if (key === 'when') { if (args[0]) args[1](proxy); return proxy; }
          return proxy;
        };
      },
      apply: () => proxy,
    });
    rec.allTexts = () => allTexts(rec);
    return proxy;
  };

  let curTyping = '';
  const makeInput = name => {
    let val = '';
    const handlers = {};
    return {
      on(ev, fn) { (handlers[ev] ||= []).push(fn); return true; },
      value: () => val,
      set_value(v) { val = typeof v === 'object' ? String(v?.text ?? '') : String(v ?? ''); },
      set_selected_range() {},
      selected_range: () => ({ start: val.length, end: val.length }),
      content: () => ({ text: val, tokens: [] }),
      tokens: () => [],
      focus() { curTyping = name; for (const fn of handlers.focus || []) fn({}, cx); },
      __type(v, c) { val = String(v ?? ''); for (const fn of handlers.change || []) fn({}, c); },
      __submit(c) { for (const fn of handlers.submit || []) fn({}, c); },
      set_auto_grow() {}, set_soft_wrap() {},
    };
  };

  const baseEvents = [
    { at: '2026-11-21 09:00:00', type: 'user', text: '看看统一项目搜索的边界情况' },
    { at: '2026-11-21 09:01:00', type: 'pm', text: '长回复第一段导语说明，这是一个比较长的段落用于确保回复处于折叠状态以便测试自动展开效果。' + '补充细节。'.repeat(25) + '\n\n- 详细条款里提到 alphaToken 应该在跳转时自动展开。' },
    { at: '2026-11-21 09:02:00', type: 'decision', text: '只在对话里的决定 betaDecision', quote: '直接记住' },
    { at: '2026-11-21 09:05:00', type: 'pm', text: '最新一条回复。' },
  ];
  const earlierBatch = [
    { at: '2026-11-19 08:30:00', type: 'user', text: '更早历史消息里的 gammaEarlier 需求' },
  ];

  const statePayload = {
    pms: [{ name: 'pm-dudu', project: 'dudu', repo: '/repo', conversation: '/here/projects/dudu/conversation.jsonl', status: 'idle' }],
    tasks: [
      { id: 't-search', pm: 'pm-dudu', number: 42, title: 'Search Palette', status: 'in_progress', latest: 'status=in_progress; ready for UI', updated: '2026-11-22 01:00' },
      { id: 't-other', pm: 'pm-dudu', number: 7, title: 'Other Thread', status: 'review', latest: 'done review', updated: '2026-11-21 12:00' },
    ],
    events: [{ task: 't-search', text: 'added highlight logic', at: '2026-11-22 00:55' }],
    lang: 'zh',
    home: '/here',
  };

  const memoryPayload = {
    project: 'dudu',
    layers: ['project', 'personal'],
    topics: [{ id: 'ui', folded: false }, { id: 'pitfalls', folded: true }],
    types: ['project', 'feedback', 'reference', 'pitfall'],
    files: [
      { layer: 'project', root: 'memory', path: 'esc-rule.md', name: 'esc-rule', type: 'project', topic: 'ui',
        description: 'Esc 统一退一层设计决定', modified: '2026-11-21T10:00:00Z', version: 'v1' },
    ],
    candidates: [],
    history: {},
  };

  const libraryPayload = {
    roots: ['docs'],
    files: [
      { root: 'docs', path: 'arch.md', kind: 'md', size: 180, modified: '2026-11-21T09:00:00Z', version: 'l1', title: '架构文档' },
    ],
  };

  const blank = new Proxy(function () {}, { get: (_, key) => (key === Symbol.toPrimitive ? () => 0 : blank), apply: () => blank });
  const boundKeys = [];
  let searchInputRef = null;
  let inputIdx = 0;
  let curSharedVal = { pm: 'pm-dudu' };

  const stubs = {
    View: class {},
    ...model,
    ...searchMod,
    ...stepsView,
    renderThreadChangeView: changeView.renderThreadChangeView,
    div: makeEl, h_flex: makeEl, v_flex: makeEl,
    svg: path => { const el = makeEl(); el.__rec.svgs.push(String(path || '')); return el; },
    image: makeEl,
    TextView: { markdown: (_id, md) => makeEl().child(String(md || '')) },
    Textarea: { new: () => makeEl() }, Input: { new: () => makeEl() }, Popup: { new: (id, trig) => makeEl().id(id).child(trig) },
    TextareaState: { new: () => makeInput('textarea') },
    InputState: { new: () => { const inp = makeInput(`input-${++inputIdx}`); searchInputRef = inp; return inp; } },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) },
    Scrollbar: { vertical: id => makeEl().id(`scrollbar:${id}`) },
    execPython: async (_exec, argv, opts) => stubs.exec('python3', argv, opts),
    appHome: () => '/app', home: () => '/Users/me',
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    appWindow: () => ({ platform }),
    terminals: () => [], agents: () => [], panes: () => [], spaces: () => [],
    theme: () => ({
      canvas: '#111111', surface: '#181818', raised: '#222222', chrome: '#161616', hover: '#2a2a2a',
      border: '#333333', input: '#3a3a3a', foreground: '#eeeeee', background: '#111111',
      muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', blocked: '#ff5f56', ansi2: '#27c93f', ansi3: '#e5a93c', ansi4: '#6699ff',
      solid: '#eeeeee', solid_foreground: '#111111', popover: '#1c1c1c',
    }),
    shared: () => curSharedVal,
    layout: () => ({ id: 'root', children: [{ id: 'pm-stage', active: 'pm-project', children: [] }] }),
    watchFolder: () => new Promise(() => {}),
    readTextFile: async path => {
      if (path.endsWith('t-search.json')) return JSON.stringify(statePayload.tasks[0]);
      if (path.endsWith('t-other.json')) return JSON.stringify(statePayload.tasks[1]);
      return null;
    },
    writeTextFile: async () => {},
    exec: async (command, args = []) => {
      execCalls.push([command, ...args]);
      if (args.includes('state')) return { code: 0, stdout: JSON.stringify(statePayload), stderr: '' };
      if (args.includes('events')) {
        if (oldRemote) return { code: 2, stdout: '', stderr: "pm.py: error: argument project_cmd: invalid choice: 'events'" };
        if (args.includes('--after')) {
          return { code: 0, stdout: JSON.stringify({ events: [], from: 500, offset: 1200, earlier: true }), stderr: '' };
        }
        if (args.includes('--before')) {
          return { code: 0, stdout: JSON.stringify({ events: earlierBatch, from: 0, offset: 500, earlier: false }), stderr: '' };
        }
        return { code: 0, stdout: JSON.stringify({ events: baseEvents, from: 500, offset: 1200, earlier: true }), stderr: '' };
      }
      if (args.includes('memory')) { memReads++; return { code: 0, stdout: JSON.stringify(memoryPayload), stderr: '' }; }
      if (args.includes('library')) { libReads++; return { code: 0, stdout: JSON.stringify(libraryPayload), stderr: '' }; }
      if (args.includes('file')) {
        docReads++;
        const pathArg = args[args.length - 1];
        const text = pathArg === 'esc-rule.md'
          ? '---\nname: esc-rule\ntype: project\ntopic: ui\ndescription: Esc 统一退一层设计决定\n---\n详情正文说明。'
          : '# 架构文档\n\n详细架构正文。';
        return { code: 0, stdout: JSON.stringify({ text, size: text.length, version: 'v1' }), stderr: '' };
      }
      if (args.includes('log')) return { code: 0, stdout: JSON.stringify({ entries: [], total: 0, earlier: 0 }), stderr: '' };
      return { code: 0, stdout: '', stderr: '' };
    },
    run: () => {},
    openOverlay: () => 'ov-1',
    closeOverlay: () => {},
    setShared: () => {},
    props: () => ({}),
    ...(Object.fromEntries(['View', 'div', 'h_flex', 'v_flex'].map(k => [k, blank]))),
  };
  stubs.View = class {};
  stubs.div = makeEl;
  stubs.h_flex = makeEl;
  stubs.v_flex = makeEl;

  const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
  const cx = {
    notify() {},
    stop_propagation() {},
    spawn(fn) { Promise.resolve().then(() => fn(cx)).catch(() => {}); },
    focus_handle: () => ({ focus() { curTyping = ''; } }),
    bind_keys: list => { boundKeys.push(...list); return list.length; },
    timer: {
      after(ms, fn) { timers.push({ ms, fn }); },
      every() {},
    },
  };

  const view = new Mod();
  view.init(null, cx);
  searchInputRef = view.searchInput;
  view.scroll = { scroll_to_item: i => scrolled.push(i) };
  view.searchScroll = { scroll_to_item: i => searchScrolled.push(i) };
  view.docScroll = { scroll_to_item() {} };
  view.keyFocus = { focus() { curTyping = ''; view.typing = ''; } };
  // First render sets view.pmName so readLog loads the project's events
  view.render(cx);
  await new Promise(r => setTimeout(r, 30));
  while (timers.length) timers.shift().fn(cx);
  await new Promise(r => setTimeout(r, 30));
  while (timers.length) timers.shift().fn(cx);
  await new Promise(r => setTimeout(r, 30));

  // Verify PmSearchOpen keybindings were registered
  assert.ok(boundKeys.some(b => b.context === 'PmSearchOpen' && b.action === 'pm-search-accept'));
  assert.ok(boundKeys.some(b => b.context === 'PmSearchOpen' && b.action === 'pm-search-scope-next'));

  // 1) Header search icon button + shortcut tooltip (macOS -> ⌘K, Linux -> Ctrl+K)
  nodes.clear();
  view.hoverKey = 'tip:pm-search';
  view.render(cx);
  assert.ok(nodes.has('pm-search'));
  assert.match(nodes.get('hover-tip-pm-search')?.allTexts().join(' ') || '', /⌘K/);
  platform = 'linux';
  nodes.clear();
  view.render(cx);
  assert.match(nodes.get('hover-tip-pm-search')?.allTexts().join(' ') || '', /Ctrl\+K/);
  view.hoverKey = '';
  platform = 'macos';

  // 2) Open via header click or cmd-k -> lazy one-time memory & library read
  execCalls = [];
  nodes.get('pm-search').clicks({}, cx);
  assert.equal(view.searchOpen, true);
  await new Promise(r => setTimeout(r, 30));
  assert.equal(memReads, 1);
  assert.equal(libReads, 1);

  // Typing does zero extra subprocesses and highlights matches
  execCalls = [];
  searchInputRef.__type('#42', cx);
  nodes.clear();
  view.render(cx);
  assert.equal(execCalls.length, 0, 'filtering while typing must not spawn subprocesses');
  const row0 = nodes.get('project-search-row-0');
  assert.ok(row0, 'should show thread #42 hit');
  assert.match(row0.allTexts().join(''), /#42/);
  assert.match(row0.allTexts().join(''), /Search Palette/);

  // 3) Click thread hit -> closes search & opens right detail (does not toggle closed if clicked again)
  row0.clicks({}, cx);
  assert.equal(view.searchOpen, false);
  assert.equal(view.detail, true);
  assert.equal(view.thread, 't-search');
  view.revealThread('t-search', cx);
  assert.equal(view.detail, true, 'revealThread must keep detail open');

  // 4) Reopen with cmd-k, search long folded PM reply -> jump unfolds, scrolls & flashes with accent, then clears on timer
  nodes.get('pm-project-root').keyDowns[0]({ keystroke: 'cmd-k' }, cx);
  assert.equal(view.searchOpen, true);
  searchInputRef.__type('alphaToken', cx);
  nodes.clear();
  view.render(cx);
  assert.ok(nodes.get('project-search-row-0'), 'should match folded long PM reply');
  scrolled.length = 0;
  nodes.get('project-search-row-0').clicks({}, cx);
  assert.equal(view.searchOpen, false);
  const flashItem = view.items.find(i => (i.text || '').includes('alphaToken'));
  assert.ok(flashItem);
  assert.equal(flashItem.long, true);
  assert.equal(view.unfolded.get(flashItem.key), true, 'folded PM reply must unfold on jump');
  assert.equal(view.flash, flashItem.key);
  assert.equal(view.flashTone, 'accent');
  assert.ok(scrolled.length > 0, 'scroll_to_item must be called on message jump');
  assert.equal(view.away, true, 'jumping to an earlier message must keep away=true');
  const flashTimer = timers.find(t => t.ms === 1800);
  assert.ok(flashTimer);
  flashTimer.fn(cx);
  assert.equal(view.flash, '');

  // 5) Search Memory decision -> opens Memory tab entry directly with docJumpQuery highlight; cmd-f inside open doc opens In-Doc Find
  view.openProjectSearch(cx);
  searchInputRef.__type('退一层', cx);
  nodes.clear();
  view.render(cx);
  const memRow = nodes.get('project-search-row-0');
  assert.ok(memRow);
  memRow.clicks({}, cx);
  await new Promise(r => setTimeout(r, 20));
  assert.equal(view.searchOpen, false);
  assert.equal(view.detail, false);
  assert.equal(view.sideTab, 'memory');
  assert.equal(view.activeDoc?.path, 'esc-rule.md');
  assert.equal(view.docJumpQuery, '退一层');
  // cmd-f while viewing a doc opens In-Doc Find rather than Project Search
  nodes.get('pm-project-root').keyDowns[0]({ keystroke: 'cmd-f' }, cx);
  assert.equal(view.docFindOpen, true);
  assert.equal(view.searchOpen, false);
  // cmd-k always opens Project Search even when viewing a doc
  nodes.get('pm-project-root').keyDowns[0]({ keystroke: 'cmd-k' }, cx);
  assert.equal(view.searchOpen, true);

  // 6) Loaded-only footer & Load Earlier (Interface A reuse) refreshes results in place while keeping search open
  searchInputRef.__type('gammaEarlier', cx);
  nodes.clear();
  view.render(cx);
  assert.ok(nodes.get('project-search-empty'), 'earlier message not loaded yet');
  assert.ok(nodes.get('project-search-footer')?.allTexts().join(' ').includes('仅搜已加载对话'));
  assert.ok(nodes.get('project-search-load-earlier'));
  nodes.get('project-search-load-earlier').clicks({}, cx);
  await new Promise(r => setTimeout(r, 30));
  assert.equal(view.searchOpen, true, 'search remains open after loading earlier');
  nodes.clear();
  view.render(cx);
  assert.ok(nodes.get('project-search-row-0'), 'gammaEarlier appears after loading earlier');
  assert.match(nodes.get('project-search-row-0').allTexts().join(''), /gammaEarlier/);

  // 7) Keyboard navigation + Esc layer-by-layer unwind (clear query -> reset scope -> close search -> clear docFind -> close docFind)
  view.setSearchScope('messages', cx);
  assert.equal(view.searchScope, 'messages');
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(view.searchQuery, '');
  assert.equal(view.searchOpen, true);
  assert.equal(view.searchScope, 'messages');
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(view.searchScope, 'all');
  assert.equal(view.searchOpen, true);
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(view.searchOpen, false);
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(view.docFindQuery, '');
  view.escape({ keystroke: 'escape' }, cx);
  assert.equal(view.docFindOpen, false);

  // 8) Exercise PmSearchOpen actions, user bubble jump, conversation decision jump, and library jump
  view.openProjectSearch(cx);
  searchInputRef.__type('边界情况', cx);
  nodes.clear();
  view.render(cx);
  const searchActions = actionsByCtx.get('PmSearchOpen');
  assert.ok(searchActions?.get('pm-search-down'));
  assert.ok(searchActions?.get('pm-search-scope-next'));
  assert.ok(searchActions?.get('pm-search-accept'));
  searchActions.get('pm-search-scope-next')({}, cx);
  assert.equal(view.searchScope, 'threads');
  searchActions.get('pm-search-scope-prev')({}, cx);
  assert.equal(view.searchScope, 'all');
  searchActions.get('pm-search-down')({}, cx);
  nodes.clear();
  view.render(cx);
  searchActions.get('pm-search-accept')({}, cx);
  assert.equal(view.searchOpen, false);
  const userItem = view.items.find(i => i.kind === 'user' && (i.text || '').includes('边界情况'));
  assert.ok(userItem);
  assert.equal(view.flash, userItem.key);
  assert.equal(view.flashTone, 'accent');

  // Conversation-only decision jump
  view.openProjectSearch(cx);
  searchInputRef.__type('betaDecision', cx);
  nodes.clear();
  view.render(cx);
  nodes.get('project-search-row-0').clicks({}, cx);
  const decItem = view.items.find(i => i.kind === 'decision' && (i.text || '').includes('betaDecision'));
  assert.ok(decItem);
  assert.equal(view.flash, decItem.key);
  assert.equal(view.flashTone, 'accent');

  // Library doc jump
  view.openProjectSearch(cx);
  searchInputRef.__type('架构文档', cx);
  nodes.clear();
  view.render(cx);
  nodes.get('project-search-row-0').clicks({}, cx);
  await new Promise(r => setTimeout(r, 20));
  assert.equal(view.sideTab, 'library');
  assert.equal(view.activeDoc?.path, 'arch.md');
  assert.equal(view.docJumpQuery, '架构文档');

  // 9) English i18n check + old-remote graceful degradation
  curSharedVal = { pm: 'box/pm-dudu', machine: 'box' };
  oldRemote = true;
  view.render(cx);
  await new Promise(r => setTimeout(r, 30));
  while (timers.length) timers.shift().fn(cx);
  await new Promise(r => setTimeout(r, 30));
  view.state = { ...statePayload, lang: 'en' };
  view.remoteNoProject = 'box';
  view.events = [...baseEvents];
  view.logState = null;
  view.earlierLoading = false;
  view.earlierError = '';
  view.openProjectSearch(cx);
  searchInputRef.__type('betaDecision', cx);
  nodes.clear();
  view.render(cx);
  assert.match(nodes.get('project-search-footer')?.allTexts().join(' ') || '', /Searching recent loaded messages only/);
  assert.ok(nodes.get('project-search-row-0'), 'conversation-only decision still found on old remote');
  assert.ok(docReads >= 1);
});

test('Project Search overlay uses auto-height overflow_y_scroll (not overflow_y_scrollbar/flex_1), flex_none rows, paired Scrollbar, and no duplicate footer tooltip', () => {
  const nodes = new Map();
  const scrollbars = [];
  const makeEl = () => {
    const rec = { id: '', methods: [], args: new Map(), texts: [], kids: [], tips: [] };
    const proxy = new Proxy(() => proxy, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        return (...args) => {
          rec.methods.push(key);
          (rec.args.get(key) || rec.args.set(key, []).get(key)).push(args);
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') {
            if (typeof args[0] === 'string') rec.texts.push(args[0]);
            else if (args[0]?.__rec) rec.kids.push(args[0].__rec);
          }
          else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) {
              if (typeof k === 'string') rec.texts.push(k);
              else if (k?.__rec) rec.kids.push(k.__rec);
            }
          }
          else if (key === 'tooltip') rec.tips.push(args[0]);
          else if (key === 'when') { if (args[0]) args[1](proxy); return proxy; }
          return proxy;
        };
      },
      apply: () => proxy,
    });
    return proxy;
  };
  const ui = {
    div: makeEl,
    svg: makeEl,
    v_flex: makeEl,
    h_flex: makeEl,
    Input: { new: makeEl },
    Scrollbar: { vertical: id => { scrollbars.push(id); return makeEl().id(`sb:${id}`); } },
    icon: makeEl,
    iconButton: (id, _name, tip) => makeEl().id(id).tooltip(tip),
    threadMark: makeEl,
    memoryTypeColor: () => '#4f8cff',
    SPINNER: 'spinner.svg',
  };
  const themeObj = {
    canvas: '#111111', surface: '#181818', raised: '#222222', chrome: '#161616', hover: '#2a2a2a',
    border: '#333333', input: '#3a3a3a', foreground: '#eeeeee', background: '#111111',
    muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', blocked: '#ff5f56', popover: '#1c1c1c',
  };
  const result = searchMod.buildProjectSearch({
    pm: { name: 'pm-dudu', project: 'dudu' },
    tasks: [
      { id: 'dudu-a', pm: 'pm-dudu', number: 1, title: '紧急 Bug：气泡折叠', status: 'in_progress', latest: 'working', updated: '2026-11-22 02:00' },
    ],
    events: [{ at: '2026-11-22 01:00:00', type: 'user', text: '测试紧急消息' }],
    items: [{ kind: 'user', key: 'u:1', text: '测试紧急消息', at: '2026-11-22 01:00:00' }],
    memoryData: {
      files: [{ layer: 'project', root: 'memory', path: 'board.md', name: 'board-flat-fill-style', type: 'project',
        description: '组内按紧急程度排', modified: '2026-11-12T00:00:00Z' }],
    },
    libraryFiles: [{ root: 'docs', path: 'guide.md', kind: 'md', size: 100, modified: '2026-11-20T00:00:00Z', title: '紧急手册' }],
    lang: 'en',
    today: '2026-11-22',
    query: '紧急',
    scope: 'all',
  });

  searchMod.renderProjectSearchOverlay({
    ui,
    theme: themeObj,
    lang: 'en',
    query: '紧急',
    scope: 'all',
    inputState: {},
    scrollHandle: { scroll_to_item() {} },
    result,
    selectedIndex: 0,
    earlierEvents: true,
    actions: {},
  });

  const resultsNode = nodes.get('project-search-results');
  assert.ok(resultsNode, 'project-search-results container must exist');
  assert.ok(resultsNode.methods.includes('overflow_y_scroll'), 'must use overflow_y_scroll so auto-height card does not collapse');
  assert.ok(!resultsNode.methods.includes('overflow_y_scrollbar'), 'must not use overflow_y_scrollbar inside auto-height overlay card');
  assert.ok(!resultsNode.methods.includes('flex_1'), 'must not set flex_1 (flex-basis: 0) inside auto-height overlay card');
  assert.deepEqual(resultsNode.args.get('min_h'), [[0]]);
  assert.deepEqual(resultsNode.args.get('flex_shrink'), [[1]]);
  assert.deepEqual(resultsNode.args.get('max_h'), [[440]]);
  assert.deepEqual(scrollbars, ['project-search-results'], 'vertical Scrollbar must pair with project-search-results by id');

  // Every group header and result row must be flex_none so rows never squish vertically when overflowing max_h
  assert.ok(resultsNode.kids.length >= 8, 'expected 4 group headers + 4 hit rows');
  for (const kid of resultsNode.kids) {
    assert.ok(kid.methods.includes('flex_none'), `child ${kid.id} inside scroll results must be flex_none`);
  }

  // Footer loaded-only text must NOT duplicate itself as a tooltip, while the Load Earlier icon button keeps its hover tip
  const collectTips = rec => [...rec.tips, ...rec.kids.flatMap(collectTips)];
  const footer = nodes.get('project-search-footer');
  assert.ok(footer);
  const footerTips = collectTips(footer);
  assert.ok(!footerTips.some(tip => String(tip).includes('Loaded messages only')),
    `footer loaded-only text must not repeat in a tooltip, got: ${JSON.stringify(footerTips)}`);
  assert.deepEqual(nodes.get('project-search-load-earlier')?.tips, ['Load earlier messages']);
});

test('render safety: no render-phase notify/closeOverlay, no stale cx, null summaryPills safe, findBar intact, Popup styles on anchor, diagnostics guard', async () => {
  const { readFileSync } = await import('node:fs');
  const mainSrc = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const body = mainSrc
    .replace(/^\s*import\s+[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/export\s+default\s+class\s+PmProject\s+extends\s+View/, 'class PmProject');

  const nodes = new Map();
  const popups = new Map();
  const closedOverlays = [];
  const timers = [];
  const makeEl = (tag, initId = '') => {
    const rec = { tag, id: initId, props: {}, texts: [], kids: [], content: null, clicks: null, mouseDowns: [] };
    const allTexts = r => [...r.texts, ...(r.content ? allTexts(r.content) : []), ...r.kids.flatMap(allTexts)];
    const proxy = new Proxy(() => proxy, {
      get(_t, key) {
        if (key === '__rec') return rec;
        if (key === 'then') return undefined;
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') {
            if (args[0] == null) throw new TypeError('child(value) expects an element, a string, or an entity');
            if (typeof args[0] === 'string') rec.texts.push(args[0]);
            else if (args[0]?.__rec) rec.kids.push(args[0].__rec);
          } else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) {
              if (k == null) throw new TypeError('children contains null/undefined');
              if (typeof k === 'string') rec.texts.push(k);
              else if (k?.__rec) rec.kids.push(k.__rec);
            }
          } else if (key === 'content') {
            rec.content = args[0]?.__rec || null;
          } else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'on_mouse_down') rec.mouseDowns.push(args[1] || args[0]);
          else if (key === 'when') {
            if (args[0]) return args[1](proxy);
          } else {
            rec.props[key] = args.length <= 1 ? (args.length === 0 ? true : args[0]) : args;
          }
          return proxy;
        };
      },
    });
    rec.allTexts = () => allTexts(rec);
    return proxy;
  };

  let stageActive = 'pm-project';
  let sharedProject = { pm: 'pm-dudu' };
  let injectZeroSummaryEpic = false;
  const makeBox = () => {
    let val = '';
    return {
      on() {}, value: () => val, content: () => ({ text: val, tokens: [] }),
      selected_range: () => ({ start: val.length, end: val.length }),
      set_selected_range() {}, set_value(v) { val = typeof v === 'object' ? String(v.text || '') : String(v ?? ''); },
      set_auto_grow() {}, set_soft_wrap() {}, focus() {}, is_focused: () => false,
    };
  };

  const stubs = {
    View: class {},
    div: () => makeEl('div'),
    svg: () => makeEl('svg'),
    image: () => makeEl('image'),
    v_flex: () => makeEl('v_flex'),
    h_flex: () => makeEl('h_flex'),
    TextareaState: { new: () => makeBox() },
    Textarea: { new: () => makeEl('Textarea') },
    InputState: { new: () => makeBox() },
    Input: { new: () => makeEl('Input') },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) },
    Scrollbar: { new: () => makeEl('Scrollbar') },
    Popup: { new: (id, trigger) => { const el = makeEl('Popup', id); el.__rec.trigger = trigger?.__rec || null; popups.set(id, el.__rec); return el; } },
    TextView: {
      markdown: id => makeEl('TextView', id),
      html: id => makeEl('TextView', id),
    },
    theme: () => ({
      canvas: '#111113', background: '#111113', surface: '#1b1b1f', chrome: '#16161a',
      popover: '#222228', raised: '#27272d', hover: '#2c2c34', selected: '#30303a',
      border: '#2e2e36', input: '#3a3a44', foreground: '#f2f2f5', muted: '#a0a0aa', dim: '#6b6b76',
      accent: '#4da3ff', solid: '#f2f2f5', solid_foreground: '#111113',
      blocked: '#ff6b6b', working: '#4cd964', done: '#4da3ff', idle: '#6b6b76',
      ansi1: '#ff6b6b', ansi2: '#4cd964', ansi3: '#ffcc00', ansi4: '#4da3ff', ansi5: '#bf5af2', ansi6: '#5ac8fa',
    }),
    home: () => '/tmp', appHome: () => '/tmp/app',
    exec: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    readTextFile: async () => null, writeTextFile: async () => null, watchFolder: () => new Promise(() => {}),
    layout: () => ({ id: 'pm-stage', active: stageActive, children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run: () => {}, terminals: () => [], agents: () => [], panes: () => [], spaces: () => [],
    shared: key => key === 'pm-project' ? sharedProject : null,
    setShared: () => {},
    props: () => ({}),
    openOverlay: () => 'ov-x',
    closeOverlay: id => closedOverlays.push(id),
    appWindow: () => ({ platform: 'macos' }),
    execPython: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    ...model,
    taskTree: (...args) => {
      const tree = model.taskTree(...args);
      if (injectZeroSummaryEpic && tree.groups.length) {
        tree.groups[0].nodes.unshift({
          task: 'epic-zero', title: 'Zero Summary Epic', status: 'in_progress', tone: 'running',
          waiting: false, group: 'working', latest: '', updated: '2026-11-22 01:00', branch: '',
          working: false, parent: '', container: true, finishedChildren: [],
          summary: { waiting: 0, review: 0, working: 0, offline: 0, paused: 0, parked: 0, done: 0 },
          activeChild: null, agents: { active: [], ended: [], all: [], endedCount: 0, endedSummary: '' },
          children: [],
        });
      }
      return tree;
    },
    ...stepsView,
    ...changeView,
    ...searchMod,
  };

  const Mod = new Function(...Object.keys(stubs), `${body}\nreturn PmProject;`)(...Object.values(stubs));
  const view = new Mod();
  const mkCx = (phase = 'event', { stale = false } = {}) => ({
    phase: () => phase,
    notify() {
      if (stale) throw new Error('stale cx: needs a live host call');
      if (phase === 'render') throw new Error('cx.notify() is not allowed during the render phase');
    },
    spawn(fn) {
      if (stale) throw new Error('stale cx: needs a live host call');
      return fn(mkCx('task'));
    },
    stop_propagation() {},
    focus_handle: () => ({ focus() {}, is_focused: () => false }),
    timer: {
      after(ms, fn) {
        if (stale) throw new Error('stale cx: needs a live host call');
        const t = { ms, fn, cancelled: false, cancel() { this.cancelled = true; } };
        timers.push(t);
        return t;
      },
      every() { return { cancel() {} }; },
    },
  });

  const liveCx = mkCx('event');
  const prevStorage = globalThis.localStorage;
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
  try {
    view.init({}, liveCx);
    view.state = {
      lang: 'zh',
      pms: [{ name: 'pm-dudu', project: 'dudu', repo: '/tmp/dudu' }],
      tasks: [
        { id: 'epic-empty', pm: 'pm-dudu', title: 'Empty Epic', status: 'in_progress', updated: '2026-11-22 01:00' },
        { id: 't-child', pm: 'pm-dudu', title: 'Normal Task', status: 'in_progress', latest: 'working on fix', updated: '2026-11-22 01:05' },
      ],
      events: [],
    };
    view.pmName = 'pm-dudu';
    view.stateFor = '';
    view.onStage = true;
    view.wide = true;
    view.viewWidth = 1280;
    view.hoverKey = 'task:t-child';
    view.hoverCardOver = 'task:t-child';
    view.agentWindows = [{ key: 'worker:t-child', overlayId: 'ov-leave-1' }];

    // 1. P0: Leaving pm-project stage during render() with active hoverKey must NOT call cx.notify() or sync closeOverlay()
    stageActive = 'work';
    timers.length = 0;
    closedOverlays.length = 0;
    assert.doesNotThrow(() => view.render(mkCx('render')), 'leaving stage during render must never call cx.notify()');
    assert.equal(view.hoverKey, '');
    assert.equal(view.hoverCardOver, '');
    assert.equal(view.onStage, false);
    assert.deepEqual(closedOverlays, [], 'closeAllAgentWindows during render must defer closeOverlay');
    while (timers.length) {
      const t = timers.shift();
      if (!t.cancelled) t.fn(liveCx);
    }
    assert.deepEqual(closedOverlays, ['ov-leave-1'], 'deferred closeOverlay runs in timer callback');

    // Direct guard on clearHoverNow(renderCx)
    view.hoverKey = 'task:t-child';
    assert.doesNotThrow(() => view.clearHoverNow(mkCx('render')), 'clearHoverNow guards against render-phase cx.notify');
    assert.equal(view.hoverKey, '');

    // 2. P1 #3: Empty-summary container epic in threadsPanel must NOT pass null into .child()
    stageActive = 'pm-project';
    injectZeroSummaryEpic = true;
    view.state.tasks = [
      { id: 't-active', pm: 'pm-dudu', title: 'Active task', status: 'in_progress', latest: 'running', updated: '2026-11-22 01:02' },
    ];
    view.hoverKey = 'task:t-active';
    nodes.clear();
    popups.clear();
    assert.doesNotThrow(() => view.render(mkCx('render')), 'epic with all-zero summary pills must not throw on .child(null)');
    assert.ok(nodes.has('epic-epic-zero'), 'zero-summary container epic rendered cleanly');
    assert.equal(nodes.has('epic-summary-epic-zero'), false, 'zero-summary container epic omits summaryPills');
    injectZeroSummaryEpic = false;

    // 3. P2 #6: wrapHoverCard puts layout styles on outer anchor div, NOT on Popup.new(...)
    const hoverPopup = popups.get('hover-card-task:t-active');
    const hoverAnchor = nodes.get('hover-card-anchor-task:t-active');
    assert.ok(hoverPopup, 'hover Popup is mounted');
    assert.ok(hoverAnchor, 'hover anchor wrapper div is mounted');
    assert.equal(hoverPopup.props.absolute, undefined, 'Popup must not have .absolute() chained');
    assert.equal(hoverPopup.props.left, undefined, 'Popup must not have .left() chained');
    assert.equal(hoverPopup.props.top, undefined, 'Popup must not have .top() chained');
    assert.equal(hoverAnchor.props.absolute, true);
    assert.equal(hoverAnchor.props.left, -16);
    assert.equal(hoverAnchor.props.top, 0);

    // 4. P1 #2 + P2 #5: docDetailView source-thread clicks use fresh event cx (not stale render cx), and findBar keeps searchBox when query is non-empty
    const staleRenderCx = mkCx('render', { stale: true });
    view.sideTab = 'library';
    view.libraryRead = true;
    view.libraryFiles = [{
      root: 'research', path: 'report.md', name: 'report.md', title: 'Report',
      task: 't-active', task_title: 'Active task', kind: 'md', size: 120,
    }];
    view.activeDoc = { tab: 'library', root: 'research', path: 'report.md' };
    view.docCache.set('research/report.md', {
      text: `---\ntask: t-active\ntask_title: Active task\n---\n\nFirst paragraph with needle.\n\n${'padding line for chunking.\n\n'.repeat(260)}Second paragraph with needle.`,
      size: 7200,
    });
    view.docFindOpen = true;
    view.docFindQuery = 'needle';
    nodes.clear();
    view.docDetailView(stubs.theme(), '2026-11-22', staleRenderCx);

    // P2 #5: findBar must keep search box AND show match count
    assert.ok(nodes.has('doc-find-box'), 'doc-find-box must remain visible after typing a non-empty query');
    assert.ok(nodes.has('doc-find-prev') && nodes.has('doc-find-next'), 'match navigation buttons render alongside search box');

    // P1 #2: both source-thread buttons must work with live event cx even though render cx is stale
    let opened = [];
    const origOpenThread = view.openThread.bind(view);
    view.openThread = (id, cx) => {
      assert.equal(cx, liveCx, 'click callback must pass event cx, not stale render cx');
      cx.notify();
      opened.push(id);
    };
    assert.ok(nodes.get('doc-source-thread')?.clicks, 'topBar doc-source-thread click wired');
    assert.ok(nodes.get('doc-source-row')?.clicks, 'body doc-source-row click wired');
    assert.doesNotThrow(() => nodes.get('doc-source-thread').clicks({}, liveCx));
    assert.doesNotThrow(() => nodes.get('doc-source-row').clicks({}, liveCx));
    assert.deepEqual(opened, ['t-active', 't-active']);
    view.openThread = origOpenThread;

    // 5. P1 #2 (extra from repo audit): mentionPopup on_mouse_down uses event cx, not stale render cx
    nodes.clear();
    const menu = {
      mode: 'category', category: 'threads', title: 'Threads', index: 0, dividerBefore: -1,
      items: [{ rowKind: 'item', kind: 'thread', label: 'Active task', typeLabel: 'Thread', task: 't-active', group: 'working', status: 'in_progress' }],
    };
    view.mentionPopup('say', 'main', menu, stubs.theme());
    assert.ok(nodes.get('say-mention-back')?.mouseDowns.length > 0);
    assert.ok(nodes.get('say-mention-row-0')?.mouseDowns.length > 0);
    assert.doesNotThrow(() => nodes.get('say-mention-back').mouseDowns[0]({}, liveCx));
    assert.doesNotThrow(() => nodes.get('say-mention-row-0').mouseDowns[0]({}, liveCx));

    // 6. P2 #7: bindSelectableText does not probe on_selection_change when globalThis.__diagnostics is true
    let probedInDiag = false;
    const diagProxy = new Proxy({ selectable() { return diagProxy; } }, {
      get(target, prop) {
        if (prop === 'on_selection_change') {
          probedInDiag = true;
          throw new Error("unknown element method 'on_selection_change'");
        }
        return target[prop];
      },
    });
    const prevDiag = globalThis.__diagnostics;
    globalThis.__diagnostics = true;
    try {
      assert.doesNotThrow(() => view.bindSelectableText(diagProxy, { key: 'k1' }));
      assert.equal(probedInDiag, false, 'must not probe on_selection_change while __diagnostics is active');
    } finally {
      globalThis.__diagnostics = prevDiag;
    }
  } finally {
    globalThis.localStorage = prevStorage;
  }
});

test('reconcilePendingSends, pmTurnWorking, queue persistence with quotes, and chronological timeline order', () => {
  // 1. pmTurnWorking distinguishes real foreground turn from background shell ("1 shell still running")
  assert.equal(model.pmTurnWorking({ address: 't1', status: 'working', report: { state: 'working' } }, []), true);
  assert.equal(model.pmTurnWorking({ address: 't1', status: 'working', report: { state: 'working', msg: '1 shell still running' } }, []), false);
  assert.equal(model.pmTurnWorking({ address: 't1', status: 'working', report: { state: 'working', msg: '2 shells still running' } }, []), false);
  assert.equal(model.pmTurnWorking({ address: 't1', status: 'done' }, []), false);

  // 2. Herdr exec timeout ("env took longer than 20 s and was stopped") & target-gone classification
  assert.equal(model.isQueueableSendError('env took longer than 20 s and was stopped'), true);
  assert.equal(model.isDialogOrDraftSendError('env took longer than 20 s and was stopped'), false);
  assert.equal(model.isDialogOrDraftSendError('t182 is blocked (permission)'), true);
  assert.equal(model.isDialogOrDraftSendError('waiting for unsent draft'), true);
  assert.equal(model.isTargetGoneSendError('terminal t160 not found'), true);
  assert.equal(model.isTargetGoneSendError('t160 has exited'), true);
  assert.equal(model.isTargetGoneSendError('t160 is finished'), true);
  assert.equal(model.isTargetGoneSendError(Object.assign(new Error('t160 not found'), { upload: true })), false);

  // 3. Queued send persistence preserves quotes and attachments across reload
  const q1 = { id: 'pm:1#all#1', targetKey: 'pm:2026-11-22 04:19:33:', kind: 'pm', author: 'PM', time: '04:19', text: '方案出来我先拿给你看' };
  const saidQuoted = model.formatQuotedMessage([q1], '重构方案按 fable 的建议来即可');
  const fullText = model.messageText(saidQuoted, ['/tmp/paste-1.png'], '附件：');
  const saved = model.keepQueuedSends({}, 'pm-dudu', [{
    id: 2, text: fullText, said: saidQuoted, words: '重构方案按 fable 的建议来即可', to: '',
    files: ['/tmp/paste-1.png'], quotes: [q1], sentAt: 1700000000000, draftKey: 'pm:pm-dudu',
    queued: true, requeuedFromSend: true,
  }]);
  const restored = model.readQueuedSends(JSON.stringify(saved));
  assert.equal(restored['pm-dudu'].length, 1);
  assert.equal(restored['pm-dudu'][0].quotes.length, 1);
  assert.equal(restored['pm-dudu'][0].quotes[0].text, '方案出来我先拿给你看');
  assert.deepEqual(restored['pm-dudu'][0].files, ['/tmp/paste-1.png']);
  assert.equal(restored['pm-dudu'][0].requeuedFromSend, true);

  // 4. Unconfirmed send times out cleanly when PM is idle, waits while PM is genuinely working, and settles on user event
  const t0 = model.eventTime('2026-11-22 04:20:45');
  const sentBubble = {
    id: 1, text: '第一条消息\n\n/tmp/paste-20261122-041940.png', said: '第一条消息', words: '第一条消息',
    files: ['/tmp/paste-20261122-041940.png'], sentAt: t0, deliveredAt: t0, sentTo: 't182', idleSince: t0,
    queued: false, inFlight: false,
  };
  // Before 12s: stays pending, requests followup
  const rEarly = model.reconcilePendingSends([sentBubble], [], { now: t0 + 5000, pmAddress: 't182', pmWorking: false, logReady: true, lang: 'zh' });
  assert.equal(rEarly.failed.length, 0);
  assert.equal(rEarly.needsFollowup, true);
  assert.equal(Boolean(rEarly.pending[0].failed), false);

  // At 12s while logReady is false: waits for fresh log read before failing
  const rWaitLog = model.reconcilePendingSends([sentBubble], [], { now: t0 + 12500, pmAddress: 't182', pmWorking: false, logReady: false, lang: 'zh' });
  assert.equal(rWaitLog.failed.length, 0);
  assert.equal(rWaitLog.needsFollowup, true);

  // At 12s with logReady true and no user event in conversation.jsonl: marks failed in Chinese & English
  const rTimeoutZh = model.reconcilePendingSends([sentBubble], [], { now: t0 + 12500, pmAddress: 't182', pmWorking: false, logReady: true, lang: 'zh' });
  assert.equal(rTimeoutZh.failed.length, 1);
  assert.equal(rTimeoutZh.pending[0].timedOut, true);
  assert.match(rTimeoutZh.pending[0].failed, /已送到 PM 终端，但对话里一直没记下这条/);
  const rTimeoutEn = model.reconcilePendingSends([sentBubble], [], { now: t0 + 12500, pmAddress: 't182', pmWorking: false, logReady: true, lang: 'en' });
  assert.match(rTimeoutEn.pending[0].failed, /Delivered to the PM terminal, but it never showed up in the conversation/);

  // Late log write AFTER confirmation timeout still settles the timedOut failed bubble so it never
  // duplicates beside the logged message or gets re-sent twice!
  const rLateLogAfterTimeout = model.reconcilePendingSends(
    rTimeoutZh.pending,
    [{ at: '2026-11-22 04:22:30', type: 'user', text: '第一条消息\n\n/tmp/paste-20261122-041940.png' }],
    { now: t0 + 105000, pmAddress: 't182', pmWorking: false, logReady: true, lang: 'zh' },
  );
  assert.equal(rLateLogAfterTimeout.pending.length, 0, 'timedOut failed bubble settles once late user event lands in log');
  assert.equal(rLateLogAfterTimeout.settled.length, 1);

  // While PM is genuinely working on a long turn (> 90s, e.g. 180s in Claude Code input queue):
  // NEVER fails on a 90s cap while PM is busy; only starts idle countdown once PM finishes its turn.
  const workingBubble = { ...sentBubble, idleSince: 0 };
  const rMidTurn30s = model.reconcilePendingSends([workingBubble], [], { now: t0 + 30000, pmAddress: 't182', pmWorking: true, logReady: true, lang: 'zh' });
  assert.equal(rMidTurn30s.failed.length, 0);
  assert.equal(rMidTurn30s.pending[0].idleSince, 0);
  const rLongTurn180s = model.reconcilePendingSends([workingBubble], [], { now: t0 + 180000, pmAddress: 't182', pmWorking: true, logReady: true, lang: 'zh' });
  assert.equal(rLongTurn180s.failed.length, 0, 'must not fail at >90s while PM is actively working');
  assert.equal(rLongTurn180s.pending[0].idleSince, 0);

  // keepQueuedSends keeps an inFlight item as inFlight, never as queued (a reload must not send it again)
  const keptInFlight = model.readQueuedSends(JSON.stringify(model.keepQueuedSends({}, 'pm-dudu', [
    { id: 9, text: '发送中', said: '发送中', words: '发送中', queued: false, inFlight: true, inFlightAt: t0, inFlightTo: 't182', sentAt: t0 },
  ])))['pm-dudu'];
  assert.equal(keptInFlight[0].stage, 'inFlight');
  assert.equal(keptInFlight[0].queued, false, 'inFlight sends must not persist as queued across reload');

  // 5. PM terminal swap (t160 -> t182) & in-seat session swap notice:
  //    - Unlogged bubble re-queues for t182 (no loss)
  //    - Logged bubble settles without re-queuing (no duplicate)
  const swapBubble = { ...sentBubble, sentTo: 't160' };
  const rSwapLogged = model.reconcilePendingSends(
    [swapBubble],
    [{ at: '2026-11-22 04:20:46', type: 'user', text: '[Image #1]第一条消息' }],
    { now: t0 + 3000, pmAddress: 't182', pmWorking: false, logReady: true, lang: 'zh' },
  );
  assert.equal(rSwapLogged.pending.length, 0, 'already logged before old PM died -> settled, never duplicated');
  assert.equal(rSwapLogged.requeued.length, 0);
  assert.equal(rSwapLogged.settled.length, 1);

  const rSwapUnlogged = model.reconcilePendingSends(
    [swapBubble],
    [{ at: '2026-11-22 04:20:47', type: 'pm', text: 'PM session swapped; taken over from the ledger.', by: 'hc:t182', notice: true }],
    { now: t0 + 3000, pmAddress: 't182', pmWorking: false, logReady: true, lang: 'zh' },
  );
  assert.equal(rSwapUnlogged.requeued.length, 1, 'unlogged when old PM died -> re-queued for new PM');
  assert.equal(rSwapUnlogged.pending[0].queued, true);
  assert.equal(rSwapUnlogged.pending[0].requeuedFromSend, true);
  // Late hook flush from dying PM still settles requeuedFromSend bubble before duplicate send
  assert.equal(
    model.settlePending(rSwapUnlogged.pending, [{ at: '2026-11-22 04:20:46', type: 'user', text: '第一条消息\n\n/tmp/paste-20261122-041940.png' }]).length,
    0,
  );

  // In-seat session swap on the SAME terminal (t182 -> t182 with genuine swap notice or changed seat session) re-queues unlogged bubble
  const rSeatSwap = model.reconcilePendingSends(
    [sentBubble],
    [{ at: '2026-11-22 04:20:50', type: 'pm', text: 'PM session swapped (manual); taken over from the ledger.', by: 'hc:t182', notice: true }],
    { now: t0 + 6000, pmAddress: 't182', pmWorking: false, logReady: true, lang: 'zh' },
  );
  assert.equal(rSeatSwap.requeued.length, 1);
  assert.equal(rSeatSwap.pending[0].queued, true);

  // Rotate timeout-cancelled or resumed-same-session notice on the SAME terminal (`t5`, PM busy or idle)
  // MUST NOT re-queue (PM never actually swapped, preventing duplicate send to the same PM!)
  const bubbleOnT5 = { ...sentBubble, sentTo: 't5', idleSince: 0 };
  const rCancelledZh = model.reconcilePendingSends(
    [bubbleOnT5],
    [{
      at: '2026-11-22 04:21:00',
      type: 'pm',
      by: 'hc:t5',
      notice: true,
      text: '座位 hc:t5 里的当前 PM 会话在轮换 10 分钟后还在跑（它这一轮），已取消这次轮换，保留当前会话继续工作。',
    }],
    { now: t0 + 15000, pmAddress: 't5', pmWorking: true, logReady: true, lang: 'zh' },
  );
  assert.equal(rCancelledZh.requeued.length, 0, 'cancelled rotation notice on same terminal must NOT re-queue');
  assert.equal(rCancelledZh.pending[0].queued, false);

  const rCancelledEn = model.reconcilePendingSends(
    [bubbleOnT5],
    [{
      at: '2026-11-22 04:21:00',
      type: 'pm',
      by: 'hc:t5',
      notice: true,
      text: 'The outgoing PM session in hc:t5 still ran (its turn) 10 min after rotate, so the rotation was cancelled and the current session stays.',
    }],
    { now: t0 + 15000, pmAddress: 't5', pmWorking: true, logReady: true, lang: 'en' },
  );
  assert.equal(rCancelledEn.requeued.length, 0, 'English cancelled rotation notice on same terminal must NOT re-queue');

  const rResumedSame = model.reconcilePendingSends(
    [bubbleOnT5],
    [{
      at: '2026-11-22 04:21:00',
      type: 'pm',
      by: 'hc:t5',
      notice: true,
      text: '新的 PM 会话没能启动（退出码 1），已在 PM 座位里恢复原来的 claude 会话（sid-1）接着做。',
    }],
    { now: t0 + 15000, pmAddress: 't5', pmWorking: true, logReady: true, lang: 'zh' },
  );
  assert.equal(rResumedSame.requeued.length, 0, 'fallback resume of same session must NOT re-queue without session change');

  // Notice whose `by` differs from `sentTo` (`hc:t9` !== `hc:t5`) DOES re-queue even before pmAddress updates
  const rByChanged = model.reconcilePendingSends(
    [bubbleOnT5],
    [{ at: '2026-11-22 04:21:00', type: 'pm', by: 'hc:t9', notice: true, text: 'notice from replacement terminal' }],
    { now: t0 + 15000, pmAddress: 't5', pmWorking: true, logReady: true, lang: 'zh' },
  );
  assert.equal(rByChanged.requeued.length, 1, 'notice from a different terminal (by !== sentTo) re-queues');

  // Explicit seat session identity (`pmSessionKey`): stays un-requeued while outgoing fg pid still runs,
  // and re-queues as soon as seat child pid changes (`fg:101 -> fg:202`)!
  assert.equal(model.pmSessionKey({ address: 't5', pid: 100, foreground: { pid: 101, argv: ['claude'] }, labels: { 'pm.seat': '1' } }), 'fg:101');
  assert.equal(model.pmSessionKey({ address: 't5', pid: 100, foreground: { pid: 100, argv: ['python3', 'pm.py', 'seat'] }, labels: { 'pm.seat': '1' } }), '');
  const bubbleWithSession = { ...bubbleOnT5, sentSession: 'fg:101' };
  const rQueuedSwapStillOldPid = model.reconcilePendingSends(
    [bubbleWithSession],
    [{ at: '2026-11-22 04:20:50', type: 'pm', by: 'hc:t5', notice: true, text: 'PM 会话已切换（原因：手动换会话），已从台账接手。' }],
    { now: t0 + 5000, pmAddress: 't5', pmSession: 'fg:101', pmWorking: true, logReady: true, lang: 'zh' },
  );
  assert.equal(rQueuedSwapStillOldPid.requeued.length, 0, 'must not re-send to outgoing fg:101 before seat actually spawns successor');
  const rSeatPidChanged = model.reconcilePendingSends(
    [bubbleWithSession],
    [],
    { now: t0 + 8000, pmAddress: 't5', pmSession: 'fg:202', pmWorking: false, logReady: true, lang: 'zh' },
  );
  assert.equal(rSeatPidChanged.requeued.length, 1, 're-queues once seat foreground session pid changes fg:101 -> fg:202');

  // Swap wait timeout when PM stays gone past PM_SWAP_WAIT_MS
  const waitingGone = { ...rSwapUnlogged.pending[0], swapWaitSince: t0 };
  const rGoneFail = model.reconcilePendingSends([waitingGone], [], { now: t0 + model.PM_SWAP_WAIT_MS + 500, pmAddress: '', pmStarting: false, lang: 'zh' });
  assert.equal(rGoneFail.failed.length, 1);
  assert.match(rGoneFail.pending[0].failed, /PM 会话已停止/);

  // 6. Chronological timeline placement: unconfirmed or failed bubbles from 04:20 stay BEFORE 04:29 "等重构完."
  const b1At = model.eventTime('2026-11-22 04:20:45');
  const b2At = model.eventTime('2026-11-22 04:21:10');
  const events0420 = [
    { at: '2026-11-22 04:19:33', type: 'pm', text: '本机的台账已经迁好了。', by: 'hc:t182' },
    { at: '2026-11-22 04:29:15', type: 'user', text: '等重构完.' },
    { at: '2026-11-22 04:29:23', type: 'pm', text: '好，等重构完再做。', by: 'hc:t182' },
  ];
  const stuckOrFailed = [
    { id: 1, text: '1. 大任务的状态是不是没有自动更新机制\n\n/tmp/paste-20261122-041940.png', sentAt: b1At, failed: 'PM 未确认收到，点此重发' },
    { id: 2, text: saidQuoted, sentAt: b2At, failed: 'PM 未确认收到，点此重发' },
  ];
  const ordered = timeline(events0420, [], { pending: stuckOrFailed, today: '2026-11-22' });
  assert.deepEqual(
    ordered.map(i => [i.kind, i.key, Boolean(i.failed)]),
    [
      ['day', 'day:2026-11-22', false],
      ['pm', 'pm:2026-11-22 04:19:33:', false],
      ['user', 'pending:1', true],
      ['user', 'pending:2', true],
      ['user', 'user:2026-11-22 04:29:15:', false],
      ['pm', 'pm:2026-11-22 04:29:23:', false],
    ],
    '04:20 bubbles stay anchored before 04:29 messages instead of jumping to the bottom',
  );
});

test('PmProject end-to-end: render-phase flushQueue safety, unconfirmed timeout + retry, attachment + quote, and PM terminal replacement', async () => {
  const { readFileSync } = await import('node:fs');
  const mainSrc = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const body = mainSrc
    .replace(/^import[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/export\s+default\s+class\s+(\w+)/, 'class $1');

  const nodes = new Map();
  const makeEl = tag => {
    const rec = { tag, id: '', texts: [], kids: [], clicks: null, content: null };
    const collect = n => {
      const out = [...n.texts];
      if (n.content) out.push(...collect(n.content));
      for (const k of n.kids) out.push(...collect(k));
      return out;
    };
    const proxy = new Proxy({}, {
      get(_t, key) {
        if (key === '__rec') return rec;
        if (key === 'then') return undefined;
        if (key === 'allTexts') return () => collect(rec);
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, proxy); }
          else if (key === 'child') {
            if (typeof args[0] === 'string') rec.texts.push(args[0]);
            else if (args[0]?.__rec) rec.kids.push(args[0].__rec);
          } else if (key === 'children' && Array.isArray(args[0])) {
            for (const c of args[0]) {
              if (typeof c === 'string') rec.texts.push(c);
              else if (c?.__rec) rec.kids.push(c.__rec);
            }
          } else if (key === 'content') rec.content = args[0]?.__rec || null;
          else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'when') { if (args[0]) return args[1](proxy); }
          return proxy;
        };
      },
    });
    return proxy;
  };

  let fakeNow = model.eventTime('2026-11-22 04:20:45');
  const fmtAt = ms => {
    const d = new Date(ms);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  };

  let pmTerms = [{ address: 't160', state: 'live', status: 'blocked', report: { state: 'blocked' }, labels: { pm: 'dudu' }, cwd: '/r/dudu' }];
  let logEvents = [{ at: '2026-11-22 04:19:33', type: 'pm', text: '本机的台账已经迁好了。', by: 'hc:t160', offset: 100 }];
  let logFails = false;
  const pmReceipts = [];
  const stateReceipts = [];
  const sentCalls = [];
  let onSendHook = null;

  const backing = new Map();
  const fakeStorage = {
    getItem: k => (backing.has(k) ? backing.get(k) : null),
    setItem: (k, v) => { backing.set(k, String(v)); },
    removeItem: k => { backing.delete(k); },
  };

  const stubs = {
    ...model,
    ...stepsView,
    ...changeView,
    ...searchMod,
    localStorage: fakeStorage,
    View: class {},
    div: () => makeEl('div'), svg: () => makeEl('svg'), image: () => makeEl('image'),
    v_flex: () => makeEl('v_flex'), h_flex: () => makeEl('h_flex'),
    TextView: { markdown: () => makeEl('TextView'), html: () => makeEl('TextView') },
    Textarea: { new: () => makeEl('Textarea') },
    TextareaState: {
      new: () => {
        let v = '';
        return {
          on() {}, value: () => v, content: () => ({ text: v, tokens: [] }),
          selected_range: () => ({ start: v.length, end: v.length }),
          set_selected_range() {}, set_value(x) { v = typeof x === 'object' ? String(x.text || '') : String(x ?? ''); },
          set_auto_grow() {}, set_soft_wrap() {}, focus() {},
        };
      },
    },
    Input: { new: () => makeEl('Input') },
    InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, set_selected_range() {}, focus() {} }) },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) },
    Scrollbar: { new: () => makeEl('Scrollbar') },
    Popup: { new: (_id, trigger) => trigger || makeEl('Popup') },
    theme: () => ({
      canvas: '#111113', background: '#111113', surface: '#1b1b1f', chrome: '#16161a',
      popover: '#222228', raised: '#27272d', hover: '#2c2c34', selected: '#30303a',
      border: '#2e2e36', input: '#3a3a44', foreground: '#f2f2f5', muted: '#a0a0aa', dim: '#6b6b76',
      accent: '#4da3ff', solid: '#f2f2f5', solid_foreground: '#111113',
      blocked: '#ff6b6b', working: '#4cd964', done: '#4da3ff', idle: '#6b6b76',
    }),
    home: () => '/tmp', appHome: () => '/tmp/app',
    readTextFile: async () => null, writeTextFile: async () => null, watchFolder: () => new Promise(() => {}),
    layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run: () => {},
    terminals: () => pmTerms,
    agents: () => pmTerms.filter(t => t.state === 'live' && t.status).map(t => ({ address: t.address, status: t.status })),
    panes: () => [], spaces: () => [],
    shared: key => (key === 'pm-project' ? { pm: 'pm-dudu' } : null),
    setShared: () => {}, props: () => ({}),
    openOverlay: () => '', closeOverlay: () => {}, appWindow: () => ({ platform: 'macos' }),
    execPython: async (_exec, args) => {
      if (args.includes('events') && logFails) return { code: 1, stdout: '', stderr: 'pm.py: cannot read the log' };
      if (args.includes('events')) {
        const afterIdx = args.indexOf('--after');
        const after = afterIdx >= 0 ? Number(args[afterIdx + 1]) : null;
        const evs = after != null ? logEvents.filter(e => (e.offset || 0) > after) : logEvents;
        const maxOff = logEvents.reduce((m, e) => Math.max(m, e.offset || 0), 0);
        return { code: 0, stdout: JSON.stringify({ events: evs, from: 0, offset: maxOff, earlier: false, ...(pmReceipts.length ? { receipts: [...pmReceipts] } : {}) }), stderr: '' };
      }
      if (args.includes('state')) {
        return {
          code: 0,
          stdout: JSON.stringify({
            home: '/tmp/ledger',
            lang: 'zh',
            pms: [{ name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', pane: pmTerms[0] ? `hc:${pmTerms[0].address}` : 'hc:t160', conversation: '/tmp/ledger/projects/dudu/conversation.jsonl', ...(stateReceipts.length ? { receipts: [...stateReceipts] } : {}) }],
            tasks: [],
          }),
          stderr: '',
        };
      }
      return { code: 0, stdout: '{}', stderr: '' };
    },
    exec: async (_cmd, args) => {
      const list = Array.isArray(args) ? args : [];
      if (list.includes('read')) return { code: 0, stdout: '❯ ', stderr: '' };
      if (list.includes('send')) {
        const target = list[list.length - 2];
        const text = list[list.length - 1];
        sentCalls.push({ target, text });
        if (onSendHook) return await onSendHook(target, text);
        return { code: 0, stdout: '', stderr: '' };
      }
      return { code: 0, stdout: '', stderr: '' };
    },
  };

  const Mod = new Function(...Object.keys(stubs), `${body}\nreturn PmProject;`)(...Object.values(stubs));
  const timers = [];
  const mkCx = phase => ({
    phase: () => phase,
    notify() {
      if (phase === 'render') throw new Error('cx.notify() is not allowed during the render phase');
    },
    spawn(fn) {
      return Promise.resolve().then(() => fn(mkCx('task')));
    },
    stop_propagation() {},
    focus_handle: () => ({ focus() {}, is_focused: () => false }),
    timer: {
      after(ms, fn) {
        const t = { ms, fn, cancelled: false, cancel() { this.cancelled = true; } };
        timers.push(t);
        return t;
      },
      every() { return { cancel() {} }; },
    },
  });
  const drain = async () => {
    for (let i = 0; i < 10; i++) {
      await new Promise(r => setTimeout(r, 0));
    }
  };
  const stepTime = async ms => {
    fakeNow += ms;
    const due = timers.splice(0);
    for (const t of due) {
      if (!t.cancelled) t.fn(mkCx('task'));
    }
    await drain();
  };

  const eventCx = mkCx('event');
  const renderCx = mkCx('render');
  const view = new Mod();
  view._now = () => fakeNow;
  view.init({}, eventCx);
  await drain();
  assert.doesNotThrow(() => view.render(renderCx));
  await stepTime(100);
  timers.length = 0;

  // --- Part A: Render-phase flushQueue must NOT throw cx.notify() or orphan bubbles in Sending… ---
  const shotPath = '/tmp/ledger/projects/dudu/attachments/paste-20261122-041940.png';
  const quoteItem = { id: 'q1', targetKey: 'pm:2026-11-22 04:19:33:', kind: 'pm', author: 'PM', time: '04:19', text: '本机的台账已经迁好了。' };
  view.input.set_value('1. 大任务的状态是不是没有自动更新机制');
  view.files = [shotPath];
  view.sendMain(eventCx);

  fakeNow += 2000;
  view.input.set_value('重构方案按 fable 的建议来即可');
  view.quotes = [quoteItem];
  view.sendMain(eventCx);
  await drain();
  assert.equal(view.pending.length, 2);
  assert.equal(view.pending.every(p => p.queued), true);
  assert.equal(sentCalls.length, 0, 'both queued while PM is blocked');

  // PM flips to done (e.g. /auto-mode-setup swallows hc send without logging to conversation.jsonl)
  // Herdr triggers render(renderCx) directly before any timer fires!
  pmTerms = [{ address: 't182', state: 'live', status: 'done', report: { state: 'done' }, labels: { pm: 'dudu' }, cwd: '/r/dudu' }];
  assert.doesNotThrow(() => view.render(renderCx), 'render(renderCx) with queued messages must never call cx.notify() synchronously');
  await drain();
  assert.equal(sentCalls.length, 2, 'both queued messages actually invoked hc send in FIFO order instead of being orphaned');
  assert.match(sentCalls[0].text, /paste-20261122-041940\.png/);
  assert.match(sentCalls[1].text, /重构方案按 fable 的建议来即可/);

  // --- Part B: Swallowed hc send (exit 0, not in conversation.jsonl) times out to failed & stays chronologically ordered ---
  await stepTime(13000);
  await stepTime(1500);
  assert.equal(view.pending.length, 2);
  assert.match(view.pending[0].failed, /已送到 PM 终端，但对话里一直没记下这条/);
  assert.match(view.pending[1].failed, /已送到 PM 终端，但对话里一直没记下这条/);

  // Later message ("等重构完.") sends immediately without being blocked, logs to conversation.jsonl, and renders AFTER the 04:20 failed bubbles
  fakeNow = model.eventTime('2026-11-22 04:29:15');
  onSendHook = async (_target, text) => {
    logEvents.push({ at: fmtAt(fakeNow), type: 'user', text, offset: logEvents.length * 100 + 200 });
    return { code: 0, stdout: '', stderr: '' };
  };
  view.input.set_value('等重构完.');
  view.sendMain(eventCx);
  await drain();
  assert.equal(view.pending.length, 2, '"等重构完." settled cleanly while the two failed bubbles stay retryable');

  nodes.clear();
  assert.doesNotThrow(() => view.render(renderCx));
  const userBlocks = (view.lastBlocks || []).filter(b => b.kind === 'user').map(b => b.key);
  assert.deepEqual(userBlocks, ['pending:1', 'pending:2', 'user:2026-11-22 04:29:15:'], 'failed 04:20 bubbles stay above 04:29 message');
  assert.ok(nodes.has('retry-pending:1') && nodes.has('failed-pending:1'), 'failed bubble renders retry icon and error caption');

  // Clicking retry while PM is offline keeps the bubble instead of deleting it; clicking retry once PM is online resends & settles
  pmTerms = [];
  nodes.get('retry-pending:1').__rec.clicks({}, eventCx);
  assert.equal(view.pending.length, 2, 'retry while offline never drops the failed bubble');

  pmTerms = [{ address: 't182', state: 'live', status: 'idle', report: { state: 'idle' }, labels: { pm: 'dudu' }, cwd: '/r/dudu' }];
  fakeNow += 2000;
  nodes.clear();
  view.render(renderCx);
  nodes.get('retry-pending:1').__rec.clicks({}, eventCx);
  await drain();
  assert.equal(view.pending.length, 1, 'retried attachment bubble delivered and settled once logged');
  assert.equal(view.pending[0].id, 2);
  nodes.clear();
  view.render(renderCx);
  nodes.get('retry-pending:2').__rec.clicks({}, eventCx);
  await drain();
  assert.equal(view.pending.length, 0, 'retried quoted bubble delivered with quote intact and settled');
  assert.match(sentCalls.at(-1).text, /↩ PM · 04:19/);

  // --- Part C: PM terminal replaced mid-send (t182 killed -> t190 started) delivers unlogged bubbles to t190 in strict FIFO without loss or duplication ---
  sentCalls.length = 0;
  fakeNow = model.eventTime('2026-11-22 04:35:00');
  let resolveFirstSend;
  let callNum = 0;
  onSendHook = (target, text) => {
    callNum++;
    if (callNum === 1) {
      // First send to t182 exits 0 right before t182 is killed (never logged to conversation.jsonl!)
      return new Promise(resolve => { resolveFirstSend = () => resolve({ code: 0, stdout: '', stderr: '' }); });
    }
    if (target === 't182') {
      // t182 already died!
      return Promise.resolve({ code: 1, stdout: '', stderr: 'terminal t182 has exited' });
    }
    // Delivered to replacement PM t190 -> logged in conversation.jsonl!
    logEvents.push({ at: fmtAt(fakeNow), type: 'user', text, offset: logEvents.length * 100 + 500 });
    return Promise.resolve({ code: 0, stdout: '', stderr: '' });
  };

  view.input.set_value('换终端消息一');
  view.sendMain(eventCx);
  fakeNow += 500;
  view.input.set_value('换终端消息二');
  view.sendMain(eventCx);
  await new Promise(r => setTimeout(r, 0));
  // While msg1 is in flight to t182 and msg2 is queued:
  // msg1 (inFlight) MUST NOT be in localStorage[QUEUE_KEY] (so reload mid-send never duplicates it),
  // whereas msg2 (queued) IS persisted in localStorage[QUEUE_KEY].
  const midSendStored = model.readQueuedSends(fakeStorage.getItem(model.QUEUE_KEY));
  assert.deepEqual(
    (midSendStored['pm-dudu'] || []).map(x => [x.text, x.stage]),
    [['换终端消息一', 'inFlight'], ['换终端消息二', 'queued']],
    'the inFlight message persists as inFlight (a reload waits for the log, never re-sends it); the queued one as queued',
  );
  // t182 is killed and replaced by t190!
  pmTerms = [{ address: 't190', state: 'live', status: 'idle', report: { state: 'idle' }, labels: { pm: 'dudu' }, cwd: '/r/dudu' }];
  logEvents.push({
    at: fmtAt(fakeNow),
    type: 'pm',
    text: 'PM session swapped (session recovery); taken over from the ledger.',
    by: 'hc:t190',
    notice: true,
    offset: logEvents.length * 100 + 500,
  });
  resolveFirstSend();
  await drain();
  await stepTime(1600);
  await stepTime(1600);

  const toT190 = sentCalls.filter(c => c.target === 't190').map(c => c.text);
  assert.deepEqual(toT190, ['换终端消息一', '换终端消息二'], 'both unconfirmed messages re-deliver to replacement PM t190 in exact FIFO order');
  assert.equal(view.pending.length, 0, 'both messages settle once replacement PM logs them');

  // --- Part D: Late log arrival after confirmation timeout automatically clears the failed bubble (no duplicate) ---
  onSendHook = async () => ({ code: 0, stdout: '', stderr: '' });
  pmTerms = [{ address: 't190', state: 'live', status: 'working', report: { state: 'working' }, labels: { pm: 'dudu' }, cwd: '/r/dudu' }];
  view.input.set_value('长回合排队消息');
  view.sendMain(eventCx);
  await drain();
  assert.deepEqual(model.readQueuedSends(fakeStorage.getItem(model.QUEUE_KEY))['pm-dudu'].map(x => x.stage), ['delivered'],
    'a sent, unconfirmed message stays in storage as delivered (never as queued) until the log has it');
  // 120s (>90s) while PM is actively working -> must NOT mark failed!
  await stepTime(120000);
  assert.equal(Boolean(view.pending[0]?.failed), false, 'does not time out at >90s while PM is actively working');
  // PM becomes idle without logging -> after 12s marks failed (`timedOut: true`)
  pmTerms = [{ address: 't190', state: 'live', status: 'idle', report: { state: 'idle' }, labels: { pm: 'dudu' }, cwd: '/r/dudu' }];
  await stepTime(1600);
  await stepTime(13000);
  await stepTime(1600);
  assert.match(view.pending[0]?.failed || '', /已送到 PM 终端，但对话里一直没记下这条/);
  assert.equal(view.pending[0]?.timedOut, true);
  // Late log write lands in conversation.jsonl -> readLog settles & removes the failed bubble!
  logEvents.push({ at: fmtAt(fakeNow), type: 'user', text: '长回合排队消息', offset: logEvents.length * 100 + 900 });
  view.readLog(eventCx);
  await drain();
  assert.equal(view.pending.length, 0, 'timed-out failed bubble disappears once late log write arrives');
  assert.equal(fakeStorage.getItem(model.QUEUE_KEY), null, 'storage clears once nothing is unsettled');

  // --- Part E: resending a timed-out bubble checks the log first ---
  const timeOut = async text => {
    view.input.set_value(text);
    view.sendMain(eventCx);
    await drain();
    await stepTime(1600);
    await stepTime(13000);
    await stepTime(1600);
    const b = view.pending.find(p => p.words === text);
    assert.equal(b?.timedOut, true);
    return b;
  };
  const sentOf = text => sentCalls.filter(c => c.text === text).length;
  // (1) The PM got it and logged it after the timeout: the resend click marks it delivered, sends nothing.
  const late = await timeOut('其实已经收到了');
  logEvents.push({ at: fmtAt(fakeNow), type: 'user', text: '其实已经收到了', offset: logEvents.length * 100 + 900 });
  view.retry(late.id, eventCx);
  await drain();
  assert.equal(view.pending.length, 0, 'found in the log -> settled as delivered');
  assert.equal(sentOf('其实已经收到了'), 1, 'never sent a second time');
  // (2) Not in the log: while checking it shows as on its way, then goes out once more and settles.
  const lost = await timeOut('真的没收到');
  onSendHook = async (_target, text) => {
    logEvents.push({ at: fmtAt(fakeNow), type: 'user', text, offset: logEvents.length * 100 + 900 });
    return { code: 0, stdout: '', stderr: '' };
  };
  view.retry(lost.id, eventCx);
  const checking = model.timeline(view.events, [], { pending: view.pending }).find(i => i.key === `pending:${lost.id}`);
  assert.equal(checking?.checking, true);
  assert.equal(checking?.pending, true);
  await drain();
  await stepTime(1600);
  await stepTime(1600);
  assert.equal(sentOf('真的没收到'), 2, 'resent exactly once after the log came back without it');
  assert.equal(view.pending.length, 0, 'the resend settles once logged');

  // --- Part F: a resend being checked when the log cannot be read, and after switching projects ---
  // (1) The log read keeps failing: the check gives up after RESEND_VERIFY_WAIT_MS and resends, never stuck.
  onSendHook = async () => ({ code: 0, stdout: '', stderr: '' });
  const unreadable = await timeOut('日志读不到');
  logFails = true;
  view.retry(unreadable.id, eventCx);
  await drain();
  for (let waited = 0; waited < model.RESEND_VERIFY_WAIT_MS + 4000; waited += 1600) await stepTime(1600);
  assert.equal(sentOf('日志读不到'), 2, 'resent once the check window passed without a readable log');
  assert.equal(view.pending.find(p => p.words === '日志读不到')?.verifying ?? false, false, 'not stuck checking');
  logFails = false;
  logEvents.push({ at: fmtAt(fakeNow), type: 'user', text: '日志读不到', offset: logEvents.length * 100 + 900 });
  view.readLog(eventCx);
  await drain();
  assert.equal(view.pending.length, 0, 'settles once the log can be read again');

  // (2) A fresh read of another project's log proves nothing about this project's: the check waits.
  const other = await timeOut('换项目再回来');
  view.retry(other.id, eventCx);
  const since = view.pending.find(p => p.id === other.id).verifySince;
  view.logFresh = { log: model.logKey('', '/tmp/ledger/projects/other/conversation.jsonl', 'other'), from: since + 5000 };
  view.events = [];
  assert.equal(view.freshLogFrom(), 0);
  view.reconcilePending(eventCx, { forceLogReady: true });
  assert.equal(view.pending.find(p => p.id === other.id)?.verifying, true, 'not resent on the strength of another log');
  assert.equal(sentOf('换项目再回来'), 1);
  // Its own project's log, read after the click, has it: delivered, still sent once.
  logEvents.push({ at: fmtAt(fakeNow), type: 'user', text: '换项目再回来', offset: logEvents.length * 100 + 900 });
  view.readLog(eventCx);
  await drain();
  assert.equal(view.pending.length, 0);
  assert.equal(sentOf('换项目再回来'), 1);

  // --- Part G: PM receipt prevents duplicate resend when conversation.jsonl has not flushed yet (#234) ---
  // (1) Message timed out while conversation.jsonl was still empty; PM wrote a receipt (exposed via
  //     `pm.py project events`). Clicking Resend checks receipts and confirms it without sending again.
  onSendHook = async () => ({ code: 0, stdout: '', stderr: '' });
  const race1 = await timeOut('竞态消息一：日志未落盘但回执已写');
  assert.equal(sentOf('竞态消息一：日志未落盘但回执已写'), 1);
  pmReceipts.push({ at: fmtAt(fakeNow), at_ms: fakeNow, text: '竞态消息一：日志未落盘但回执已写', digest: 'd1' });
  view.retry(race1.id, eventCx);
  await drain();
  await stepTime(1600);
  assert.equal(sentOf('竞态消息一：日志未落盘但回执已写'), 1, 'receipt in project events blocks duplicate resend');
  const confirmed1 = view.pending.find(p => p.id === race1.id);
  assert.equal(confirmed1?.received, true, 'bubble stays visible as receipt-confirmed until log catches up');
  assert.equal(Boolean(confirmed1?.failed), false);
  const tl1 = model.timeline(view.events, [], { pending: view.pending }).find(i => i.key === `pending:${race1.id}`);
  assert.equal(tl1?.pending, false, 'receipt-confirmed bubble does not show Sending…');
  assert.equal(tl1?.received, true);
  // Clicking retry again on a receipt-confirmed bubble is a strict no-op.
  view.retry(race1.id, eventCx);
  await drain();
  assert.equal(sentOf('竞态消息一：日志未落盘但回执已写'), 1);
  // Once conversation.jsonl finally catches up, the receipt-confirmed bubble settles cleanly.
  logEvents.push({ at: fmtAt(fakeNow), type: 'user', text: '竞态消息一：日志未落盘但回执已写', offset: logEvents.length * 100 + 900 });
  view.readLog(eventCx);
  await drain();
  assert.equal(view.pending.length, 0, 'receipt-confirmed bubble settles once conversation.jsonl arrives');

  // (2) Receipt already present via `pm.py state` before clicking Resend: retry() blocks immediately without sending.
  const race2 = await timeOut('竞态消息二：state 回执拦截重发');
  assert.equal(sentOf('竞态消息二：state 回执拦截重发'), 1);
  stateReceipts.push({ at: fmtAt(fakeNow), at_ms: fakeNow, text: '竞态消息二：state 回执拦截重发', digest: 'd2' });
  // Simulate state already having the receipt on pm before retry click (e.g. from refresh or direct state).
  view.state = {
    ...view.state,
    pms: view.state.pms.map(p => ({ ...p, receipts: [...stateReceipts] })),
  };
  view.retry(race2.id, eventCx);
  await drain();
  assert.equal(sentOf('竞态消息二：state 回执拦截重发'), 1, 'state receipt immediately blocks duplicate resend');
  assert.equal(view.pending.find(p => p.id === race2.id)?.received, true);
  logEvents.push({ at: fmtAt(fakeNow), type: 'user', text: '竞态消息二：state 回执拦截重发', offset: logEvents.length * 100 + 900 });
  view.readLog(eventCx);
  await drain();
  assert.equal(view.pending.length, 0);

  // (3) When `project events` omits `receipts`, stale `logReceipts` are cleared.
  assert.ok(view.logReceipts.length > 0);
  pmReceipts.length = 0;
  view.readLog(eventCx);
  await drain();
  assert.deepEqual(view.logReceipts, [], 'logReceipts clears when project events omits receipts');

  // (4) Non-timeout failed bubble (`hc send` exited non-zero) is NOT swallowed by an existing receipt on retry().
  stateReceipts.length = 0;
  onSendHook = async () => ({ code: 1, stdout: '', stderr: 'hc send: synthetic failure' });
  view.input.set_value('普通失败不吞');
  view.sendMain(eventCx);
  await drain();
  const failedNormal = view.pending.find(p => p.words === '普通失败不吞');
  assert.ok(failedNormal?.failed && !failedNormal.timedOut);
  pmReceipts.push({ at: fmtAt(fakeNow), at_ms: fakeNow, text: '普通失败不吞', digest: 'nf' });
  view.logReceipts = [...pmReceipts];
  onSendHook = async (_target, text) => {
    logEvents.push({ at: fmtAt(fakeNow), type: 'user', text, offset: logEvents.length * 100 + 900 });
    return { code: 0, stdout: '', stderr: '' };
  };
  view.retry(failedNormal.id, eventCx);
  await drain();
  await stepTime(1600);
  assert.equal(sentOf('普通失败不吞'), 2, 'non-timeout send failure resends instead of being swallowed by receipt');
  assert.equal(view.pending.length, 0);
});

test('Paragraph-level quoting: splitMarkdownParagraphs, three quote scopes, #1335 range seam, wire round-trip & i18n', () => {
  const {
    splitMarkdownParagraphs, locateQuoteRange, quoteScope, quoteScopeLabel, quoteScopeTip,
    withQuote, quotePreviewLine, formatQuotedMessage, splitQuotedMessage, selectionToolbarState, word,
  } = model;

  // (1) Paragraph splitting across all markdown constructs
  const realReply = [
    '## 重构第 3a 刀验收',
    '',
    '重构第 3a 刀（#220）的 worker 报做完了，等审查。',
    '',
    '- **搬了什么**：台账存储、项目、对话、任务、看板这 6 个模块。',
    '  - 附带说明：保持调用方式兼容',
    '- **测试结果**：单测、安全网测试、安装测试全过。',
    '',
    '1. 第一步跑 `node --test`',
    '2. 第二步跑 `render_check.py`',
    '',
    '> 注意：这条行为依赖新版协议。',
    '> 需要在主仓库放截图。',
    '',
    '```js',
    'function keepIndent() {',
    '  return 42;',
    '}',
    '```',
    '',
    '| 检查项 | 状态 |',
    '| --- | --- |',
    '| 单测 | 通过 |',
    '',
    '---',
    '',
    '还有一件等你的事：Windows 上那几个 mod 看不懂的问题。',
  ].join('\n');

  const blocks = splitMarkdownParagraphs(realReply);
  assert.deepEqual(
    blocks.map(b => [b.kind, b.index, b.quotable]),
    [
      ['heading', 0, true],
      ['paragraph', 1, true],
      ['list-item', 2, true],
      ['list-item', 3, true],
      ['list-item', 4, true],
      ['list-item', 5, true],
      ['blockquote', 6, true],
      ['code', 7, true],
      ['table', 8, true],
      ['hr', -1, false],
      ['paragraph', 9, true],
    ],
  );
  // Exact character offset invariants for every block
  for (const b of blocks) {
    assert.equal(realReply.slice(b.start, b.end), b.markdown, `exact offset slice for ${b.kind}#${b.index}`);
  }
  // Nested sub-item stays attached to its top-level list item
  assert.ok(blocks[2].markdown.includes('附带说明：保持调用方式兼容'));
  assert.equal(blocks[3].markdown, '- **测试结果**：单测、安全网测试、安装测试全过。');
  // Ordered list items keep their own numbers
  assert.equal(blocks[4].markdown, '1. 第一步跑 `node --test`');
  assert.equal(blocks[5].markdown, '2. 第二步跑 `render_check.py`');
  // Code block preserves indentation inside `text` and strips fence in preview
  assert.ok(blocks[7].text.includes('  return 42;'));
  assert.equal(quotePreviewLine(blocks[7].text, 60), 'function keepIndent() { return 42; }');
  // Table stays atomic
  assert.ok(blocks[8].markdown.includes('| 单测 | 通过 |'));
  // Empty / blank input
  assert.deepEqual(splitMarkdownParagraphs('   \n\n  '), []);
  // Setext heading + tilde fence + nested code fence inside list item
  const tricky = [
    'Setext Title',
    '============',
    '',
    '- item with fence',
    '',
    '  ```py',
    '  x = 1',
    '  ```',
    '- next item',
    '',
    '~~~sh',
    'echo hi',
    '~~~',
  ].join('\n');
  const trickyBlocks = splitMarkdownParagraphs(tricky);
  assert.deepEqual(trickyBlocks.map(b => b.kind), ['heading', 'list-item', 'list-item', 'code']);
  assert.ok(trickyBlocks[1].markdown.includes('x = 1'));

  // (2) locateQuoteRange resolves arbitrary substring offsets & enclosing paragraph
  const rangeHit = locateQuoteRange(realReply, '单测、安全网测试、安装测试全过');
  assert.ok(rangeHit);
  assert.equal(realReply.slice(rangeHit.start, rangeHit.end), '单测、安全网测试、安装测试全过');
  assert.equal(rangeHit.paragraph, 3);
  assert.equal(rangeHit.kind, 'list-item');

  // (3) Three quote scopes: message, paragraph, selection — unified via withQuote & formatQuotedMessage
  const qMsg = {
    id: 'm1', targetKey: 'pm:2026-11-22 08:14:28:', kind: 'pm', author: 'PM', time: '08:14',
    text: '重构第 3a 刀（#220）的 worker 报做完了，等审查。', scope: 'message',
  };
  const qPara = {
    id: 'p1', targetKey: 'pm:2026-11-22 08:14:28:', kind: 'pm', author: 'PM', time: '08:14',
    text: blocks[3].text, scope: 'paragraph',
    range: { start: blocks[3].start, end: blocks[3].end, paragraph: blocks[3].index, kind: blocks[3].kind },
  };
  const qSel = {
    id: 's1', targetKey: 'pm:2026-11-22 08:14:28:', kind: 'pm', author: 'PM', time: '08:14',
    text: '单测、安全网测试、安装测试全过', scope: 'selection', exact: true, range: rangeHit,
  };

  // Multi-arg withQuote stacks all three without dropping any
  const stacked = withQuote([], qMsg, qPara, qSel);
  assert.equal(stacked.length, 3);
  assert.deepEqual(stacked.map(quoteScope), ['message', 'paragraph', 'selection']);
  // Re-adding the same paragraph deduplicates
  assert.equal(withQuote(stacked, { ...qPara, id: 'p1-dup' }).length, 3);

  // Wire format distinguishes all three for both PM readers and splitQuotedMessage
  const wire = formatQuotedMessage(stacked, '按这三点处理');
  assert.ok(wire.includes('> [↩ PM · 08:14](quote:pm%3A2026-11-22%2008%3A14%3A28%3A)\n'), 'whole-message header');
  assert.ok(wire.includes(`> [↩ PM · 08:14 · ¶4](quote:pm%3A2026-11-22%2008%3A14%3A28%3A#scope=paragraph&p=3&r=${blocks[3].start}-${blocks[3].end})\n`), 'paragraph header with 1-based ¶4 & range');
  assert.ok(wire.includes(`> [↩ PM · 08:14 · excerpt](quote:pm%3A2026-11-22%2008%3A14%3A28%3A#scope=selection&p=3&r=${rangeHit.start}-${rangeHit.end})\n`), 'selection header with excerpt & range');

  // Round-trip through splitQuotedMessage preserves targetKey, author, time, scope, exact, and range
  const parsed = splitQuotedMessage(wire);
  assert.equal(parsed.text, '按这三点处理');
  assert.equal(parsed.quotes.length, 3);
  assert.deepEqual(parsed.quotes.map(q => [q.targetKey, q.author, q.time, q.scope]), [
    ['pm:2026-11-22 08:14:28:', 'PM', '08:14', 'message'],
    ['pm:2026-11-22 08:14:28:', 'PM', '08:14', 'paragraph'],
    ['pm:2026-11-22 08:14:28:', 'PM', '08:14', 'selection'],
  ]);
  assert.deepEqual(parsed.quotes[1].range, { start: blocks[3].start, end: blocks[3].end, paragraph: 3 });
  assert.deepEqual(parsed.quotes[2].range, { start: rangeHit.start, end: rangeHit.end, paragraph: 3 });
  assert.equal(parsed.quotes[2].exact, true);

  // (4) Future #1335 arbitrary selection seam carries range without changing quote schema
  const selState = selectionToolbarState(
    { text: '安全网测试', bounds: { x: 10, y: 20, width: 60, height: 18 }, range: { start: 80, end: 85, paragraph: 3 } },
    { key: 'pm:2026-11-22 08:14:28:', kind: 'pm', author: 'PM', time: '08:14' },
  );
  assert.deepEqual(selState.range, { start: 80, end: 85, paragraph: 3 });

  // (5) Localized labels & tooltips in both en and zh
  assert.deepEqual([quoteScopeLabel('en', qMsg), quoteScopeLabel('en', qPara), quoteScopeLabel('en', qSel)], ['Full', '¶4', 'Excerpt']);
  assert.deepEqual([quoteScopeLabel('zh', qMsg), quoteScopeLabel('zh', qPara), quoteScopeLabel('zh', qSel)], ['整条', '第 4 段', '片段']);
  assert.equal(quoteScopeTip('en', qPara), 'Paragraph 4');
  assert.equal(quoteScopeTip('zh', qPara), '第 4 段');
  for (const key of ['quoteWholeMessage', 'quoteParagraph', 'quoteScopeMessage', 'quoteScopeParagraph', 'quoteScopeParagraphTip', 'quoteScopeSelection']) {
    for (const lang of ['en', 'zh']) {
      const val = typeof model.STRINGS[lang][key] === 'function' ? word(lang, key, 1) : word(lang, key);
      assert.ok(val && val !== key, `missing ${lang}.${key}`);
    }
  }
});

test('PmProject UI: paragraph hover dwell anti-flicker, paragraph quote button, 3-scope cards, multi-quote send & paragraph flash (en & zh)', async () => {
  const fs = await import('node:fs');
  const raw = fs.readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const source = `${raw
    .replace(/^\s*import\s+[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/export\s+default\s+class\s+/, 'class ')}\nreturn PmProject;`;

  const nodes = new Map();
  const textViews = new Map();
  const allTexts = rec => [...rec.texts, ...rec.kids.flatMap(allTexts)];
  const makeEl = (extra = {}) => {
    const rec = { id: '', texts: [], kids: [], styles: [], clicks: null, hovers: [], mouseDowns: [], selectable: false, ...extra };
    const proxy = new Proxy(() => proxy, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        if (key === '__allTexts') return () => allTexts(rec);
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') { if (typeof args[0] === 'string') rec.texts.push(args[0]); else if (args[0]?.__rec) rec.kids.push(args[0].__rec); }
          else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) { if (typeof k === 'string') rec.texts.push(k); else if (k?.__rec) rec.kids.push(k.__rec); }
          }
          else if (key === 'content' && args[0]?.__rec) rec.kids.push(args[0].__rec);
          else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'on_hover') rec.hovers.push(args[0]);
          else if (key === 'on_mouse_down') rec.mouseDowns.push(args[1] || args[0]);
          else if (key === 'selectable') rec.selectable = args[0] === undefined ? true : Boolean(args[0]);
          else if (key === 'when') { if (args[0]) args[1](proxy); }
          else rec.styles.push([key, ...args]);
          return proxy;
        };
      },
      apply: () => proxy,
    });
    rec.allTexts = () => allTexts(rec);
    return proxy;
  };

  let clipText = '';
  const sentCmds = [];
  const scrolledTo = [];
  const timers = [];
  const stubs = {
    View: class {}, ...model,
    div: () => makeEl(), h_flex: () => makeEl(), v_flex: () => makeEl(), svg: () => makeEl(), image: () => makeEl(),
    TextView: {
      markdown: (id, md) => {
        const el = makeEl({ tvKind: 'markdown', tvId: id, raw: String(md ?? '') }).child(String(md ?? ''));
        textViews.set(id, el.__rec);
        return el;
      },
      html: (id, html) => {
        const el = makeEl({ tvKind: 'html', tvId: id, raw: String(html ?? '') }).child(String(html ?? ''));
        textViews.set(id, el.__rec);
        return el;
      },
    },
    TextareaState: {
      new: () => {
        let text = '';
        return {
          on() {}, value: () => text, content: () => ({ text, tokens: [] }),
          selected_range: () => ({ start: text.length, end: text.length }),
          set_selected_range() {}, set_value(next) { text = typeof next === 'object' ? String(next.text || '') : String(next ?? ''); },
          set_auto_grow() {}, set_soft_wrap() {}, focus() {},
        };
      },
    },
    Textarea: { new: () => makeEl() },
    InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, focus() {} }) },
    Input: { new: () => makeEl() },
    ScrollHandle: { new: () => ({ scroll_to_item: i => scrolledTo.push(i) }) },
    Scrollbar: { new: () => makeEl() },
    Popup: { new: (id, trigger) => makeEl().id(id).child(trigger) },
    theme: () => ({
      canvas: '#111111', surface: '#181818', raised: '#222222', chrome: '#161616', hover: '#2a2a2a',
      border: '#333333', input: '#3a3a3a', foreground: '#eeeeee', background: '#111111',
      muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', accent_foreground: '#ffffff',
      blocked: '#ff5f56', ansi2: '#27c93f', ansi3: '#f5a623', solid: '#eeeeee', solid_foreground: '#111111',
    }),
    home: () => '/Users/test', appHome: () => '/app',
    exec: async (_cmd, args) => {
      if (args?.includes('send')) sentCmds.push(args);
      return { code: 0, stdout: JSON.stringify({ events: [], from: 0, offset: 0, earlier: false }), stderr: '' };
    },
    execPython: async (_exec, argv, opts) => stubs.exec('python3', argv, opts),
    readTextFile: async () => '', writeTextFile: async () => {}, watchFolder: () => new Promise(() => {}),
    layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run() {},
    terminals: () => [{ address: 'tpm', state: 'live', labels: { pm: 'dudu' } }],
    agents: () => [], panes: () => [{ terminal: 'tpm' }], spaces: () => [],
    shared: () => ({ pm: 'pm-dudu' }), setShared() {},
    appWindow: () => ({ platform: 'macos' }),
  };

  const prevStorage = globalThis.localStorage;
  const storeMap = new Map();
  globalThis.localStorage = { getItem: k => storeMap.get(k) ?? null, setItem: (k, v) => storeMap.set(k, String(v)), removeItem: k => storeMap.delete(k) };
  try {
    const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
    const cx = {
      phase: () => 'event',
      focus_handle: () => ({ focus() {} }),
      spawn: fn => fn(cx),
      timer: {
        after: (ms, fn) => {
          const entry = { ms, fn, cancelled: false, cancel() { this.cancelled = true; } };
          timers.push(entry);
          return entry;
        },
      },
      notify() {},
      stop_propagation() {},
      read_from_clipboard: () => clipText,
    };
    const flushTimers = () => {
      const batch = timers.splice(0);
      for (const t of batch) if (!t.cancelled) t.fn(cx);
    };
    const today = (() => {
      const d = new Date(), p = n => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    })();
    const at = t => `${today} ${t}`;
    const longPm = [
      '重构第 3a 刀已经做完，等审查。',
      '',
      '- **搬了什么**：台账存储、项目、对话、任务这几个模块。',
      '- **测试结果**：单测、安全网测试、安装测试全过。',
    ].join('\n');
    const multiUser = '第一点：保留整条引用。\n\n第二点：深浅色都清楚。';
    const pmLocal = { name: 'pm-dudu', project: 'dudu', repo: '/work/dudu', pane: 'hc:tpm', runtime: 'hc', status: 'live' };
    const view = Object.assign(Object.create(Mod.prototype), {
      state: { pms: [pmLocal], tasks: [], events: [], lang: 'zh' },
      events: [
        { at: at('09:00:00'), type: 'user', text: multiUser },
        { at: at('09:01:00'), type: 'pm', text: longPm },
      ],
      pending: [], seq: 0, pastes: [], error: '', logError: '',
      pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
      remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
      earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '/here', watching: {},
      thread: '', threadTask: null, detail: false, threadError: '', threadLog: null, threadLogKept: [],
      threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null, threadTab: 'log', sideTab: 'threads',
      librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: false, libraryProbed: true, libraryStale: false,
      libraryLoading: false, libraryAgain: false, libraryError: '', libraryClosed: new Set(), libraryQuery: '',
      libraryDropBusy: '', libraryDropError: '', memorySlug: '', memoryData: null, memoryRead: false, memoryStale: false,
      memoryLoading: false, memoryAgain: false, memoryError: '', memoryFoldOverrides: new Map(), memoryProjectOpen: true,
      memoryPersonalOpen: false, memoryCandidatesOpen: false, memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
      activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '', docShownBytes: model.DOC_INITIAL_BYTES,
      docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
      editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
      confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
      reattaching: '', reattachError: null, startingPm: '', startPmError: null,
      bringBackOpen: false, bringingBack: false, bringBackProgress: null,
      listShown: true, wide: true, measured: true, viewWidth: 1280, panelWant: null, panelDrag: null, gripLit: false,
      seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
      bell: null, flash: '', flashPara: '', unfolded: new Map(), newest: '', atWork: new Set(),
      scroll: { scroll_to_item: i => scrolledTo.push(i) }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
      libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
      mentionScroll: { scroll_to_item() {} }, mention: null, mentionDismissed: null, mentionConsumedKey: false, mentionPicking: false,
      repoFilesSlug: '', repoFilesRepo: '', repoFiles: [], repoFilesRead: false, repoFilesLoading: false, repoFilesAgain: false,
      repoFilesError: '', repoFilesTruncated: false, repoFilesAt: 0, pathCopiedAt: 0,
      quotes: [], quoteSeq: 0, hoveredMsg: '', hoverClipboard: null, selectionBar: null,
      hoveredPara: '', pendingHoverPara: '', paraHoverShowTimer: null, paraHoverHideTimer: null, paraHoverSeq: 0,
      lastBlocks: [], lastTopOffset: 0, lastHeights: [], lastTall: 0,
      keyFocus: { focus() {} }, onStage: true, typing: 'main', mainKey: 'pm:pm-dudu', threadKey: '',
      outgoing: new Map(), files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
      input: stubs.TextareaState.new(), threadInput: stubs.TextareaState.new(), libraryInput: stubs.InputState.new(), memoryInput: stubs.InputState.new(),
      docFindInput: stubs.InputState.new(), docNameInput: stubs.InputState.new(), memDescInput: stubs.InputState.new(),
      docEditorInput: stubs.TextareaState.new(), refresh: () => {},
    });
    view.resetThreadSession();

    const rerender = () => { nodes.clear(); textViews.clear(); view.render(cx); };
    rerender();

    const pmKey = `pm:${at('09:01:00')}:`;
    const userKey = `user:${at('09:00:00')}:`;

    // (1) Multi-paragraph PM reply renders 3 paragraph rows, all selectable and never blocking TextSelectionLayer
    for (const idx of [0, 1, 2]) {
      assert.ok(nodes.has(`para-${pmKey}-${idx}`), `para row ${idx} rendered`);
      assert.equal(nodes.get(`para-${pmKey}-${idx}`).mouseDowns.length, 0, 'para row does not block TextSelectionLayer');
      assert.equal(textViews.get(`md-${pmKey}-p${idx}`)?.selectable, true, `para ${idx} TextView selectable`);
      assert.equal(nodes.has(`para-quote-btn-${pmKey}-${idx}`), false, `para ${idx} button hidden before hover`);
    }
    // Multi-paragraph user bubble renders 2 hoverable paragraphs without min_w(0) on shrink-to-fit text
    assert.ok(nodes.has(`para-${userKey}-0`) && nodes.has(`para-${userKey}-1`));

    // (2) Fast sweep across paragraphs (< dwell delay) flashes ZERO paragraph icons
    nodes.get(`para-${pmKey}-0`).hovers.forEach(fn => fn(true, cx));
    nodes.get(`para-${pmKey}-0`).hovers.forEach(fn => fn(false, cx));
    nodes.get(`para-${pmKey}-1`).hovers.forEach(fn => fn(true, cx));
    nodes.get(`para-${pmKey}-1`).hovers.forEach(fn => fn(false, cx));
    flushTimers();
    assert.equal(view.hoveredPara, '', 'fast pass-through sweep shows zero paragraph icons');

    // (3) Dwelling on paragraph 2 activates ONLY paragraph 2's icon (zh & en tooltips)
    nodes.get(`pm-msg-${pmKey}`).hovers.forEach(fn => fn(true, cx));
    nodes.get(`para-${pmKey}-2`).hovers.forEach(fn => fn(true, cx));
    assert.equal(view.hoveredPara, '', 'not shown synchronously before dwell timer');
    flushTimers();
    assert.equal(view.hoveredPara, `${pmKey}#p2`);
    rerender();
    assert.equal(nodes.has(`para-quote-btn-${pmKey}-2`), true);
    assert.equal(nodes.has(`para-quote-btn-${pmKey}-0`), false);
    assert.equal(nodes.has(`para-quote-btn-${pmKey}-1`), false);
    view.hoverKey = `tip:para-quote-btn-${pmKey}-2`;
    rerender();
    assert.equal(nodes.get(`hover-tip-para-quote-btn-${pmKey}-2`)?.allTexts().join(' '), '引用此段');
    view.state.lang = 'en';
    rerender();
    assert.equal(nodes.get(`hover-tip-para-quote-btn-${pmKey}-2`)?.allTexts().join(' '), 'Quote paragraph');
    view.state.lang = 'zh';
    view.hoverKey = '';
    rerender();

    // (4) Click paragraph 2 quote button -> adds paragraph quote, then stack whole-message + clipboard selection quotes
    nodes.get(`para-quote-btn-${pmKey}-2`).clicks({ stop_propagation() {} }, cx);
    assert.equal(view.quotes.length, 1);
    assert.equal(view.quotes[0].scope, 'paragraph');
    assert.equal(view.quotes[0].range.paragraph, 2);
    assert.equal(view.quotes[0].author, 'PM');
    assert.equal(view.quotes[0].time, '09:01');
    assert.equal(view.quotes[0].targetKey, pmKey);

    // Whole-message quote via outer button (stale clipboard -> whole message)
    clipText = '';
    nodes.get(`quote-btn-${pmKey}`).clicks({ stop_propagation() {} }, cx);
    assert.equal(view.quotes.length, 2);
    assert.equal(view.quotes[1].scope, 'message');

    // Clipboard exact selection quote via outer button
    clipText = '台账存储、项目、对话、任务';
    nodes.get(`quote-btn-${pmKey}`).clicks({ stop_propagation() {} }, cx);
    assert.equal(view.quotes.length, 3);
    assert.equal(view.quotes[2].scope, 'selection');
    assert.equal(view.quotes[2].exact, true);

    // Composer quote bar renders distinct scope badges in zh & en
    rerender();
    assert.deepEqual(
      [0, 1, 2].map(i => nodes.get(`say-quote-scope-${i}`)?.allTexts().join('')),
      ['第 3 段', '整条', '片段'],
    );
    view.state.lang = 'en';
    rerender();
    assert.deepEqual(
      [0, 1, 2].map(i => nodes.get(`say-quote-scope-${i}`)?.allTexts().join('')),
      ['¶3', 'Full', 'Excerpt'],
    );
    view.state.lang = 'zh';
    rerender();

    // (5) Send all 3 stacked quotes -> ALL THREE arrive in wire message & render in sent bubble with distinct badges
    view.input.set_value('分别回应这三处');
    view.draft = view.input.value();
    view.sendMain(cx);
    await new Promise(r => setTimeout(r, 10));
    assert.equal(sentCmds.length, 1);
    const wire = sentCmds[0][sentCmds[0].length - 1];
    assert.ok(wire.includes('¶3'), 'wire contains paragraph quote marker');
    assert.ok(wire.includes('excerpt'), 'wire contains selection quote marker');
    assert.equal(model.splitQuotedMessage(wire).quotes.length, 3, 'all 3 stacked quotes preserved on send');

    // Sent bubble renders 3 distinct quote cards; clicking paragraph card flashes that specific paragraph!
    view.pending = [];
    view.events = [...view.events, { at: at('09:02:00'), type: 'user', text: wire }];
    rerender();
    const sentKey = `user:${at('09:02:00')}:`;
    assert.deepEqual(
      [0, 1, 2].map(i => nodes.get(`bubble-quote-scope-${sentKey}-${i}`)?.allTexts().join('')),
      ['第 3 段', '整条', '片段'],
    );
    scrolledTo.length = 0;
    nodes.get(`bubble-quote-${sentKey}-0`).clicks({ stop_propagation() {} }, cx);
    assert.equal(view.flash, pmKey);
    assert.equal(view.flashPara, `${pmKey}#p2`, 'clicking paragraph quote flashes that exact paragraph');
    assert.ok(scrolledTo.length > 0);
  } finally {
    globalThis.localStorage = prevStorage;
  }
});

test('Review fixes: quoteCardPreview bounds lines with natural ellipsis & PM paragraph/selection share canonical raw coordinates across decorated #num thread links', async () => {
  const { quoteCardPreview, locateQuoteRange, splitMarkdownParagraphs } = model;

  // (1) quoteCardPreview: short text keeps full content without ellipsis; long whole-message preview caps to maxLines with clean boundary + ellipsis
  const shortPrev = quoteCardPreview('重构第 3b 刀（#221）也交了，现在等审查。', { maxLines: 3, maxWidthPx: 360 });
  assert.equal(shortPrev.truncated, false);
  assert.equal(shortPrev.lines.length, 1);
  assert.equal(shortPrev.text.endsWith('…'), false);

  const longZh = '重构第 3b 刀（#221）也交了，现在等审查。这一刀做了什么：把问题卡、计划、依赖、父子任务这几块代码从 pm.py 搬了出来，44 个函数原样搬走，只有 2 个改了引用写法。新写了父任务自动收尾的判断规则。现在只有规则本身，还没接到实际流程里，所以暂时不会改变任何行为。';
  const clampedZh = quoteCardPreview(longZh, { maxLines: 3, maxWidthPx: 360, fontSize: 12.5 });
  assert.equal(clampedZh.truncated, true);
  assert.equal(clampedZh.lines.length, 3, 'caps to maxLines=3');
  assert.equal(clampedZh.lines[2].endsWith('…'), true, 'always ends with ellipsis when truncated');
  assert.equal(/[,，、:：;；]…$/.test(clampedZh.lines[2]), false, 'does not leave dangling weak punctuation before ellipsis');

  const longEn = 'The refactor split the ledger storage, conversation log, and project board modules cleanly without changing behavior across all eighty replay commands and verification tests.';
  const clampedEn = quoteCardPreview(longEn, { maxLines: 2, maxWidthPx: 300, fontSize: 12.5 });
  assert.equal(clampedEn.truncated, true);
  assert.equal(clampedEn.lines.length, 2);
  assert.equal(clampedEn.lines[1].endsWith('…'), true);
  // Last word before ellipsis must be a complete token from the source (not chopped mid-word)
  const lastWord = clampedEn.lines[1].slice(0, -1).split(/\s+/).at(-1).replace(/[.,;:!?]+$/, '');
  assert.ok(longEn.split(/\s+/).some(w => w.replace(/[.,;:!?]+$/, '') === lastWord), `clean word boundary before ellipsis: got "${lastWord}" in "${clampedEn.lines[1]}"`);

  // (2) Coordinate alignment: raw PM message with [title](thread:...) decorated as [#221 title](thread:...)
  const rawWithLink = [
    '进展：[重构 3b](thread:t-221) 已经交审，准备合并。',
    '',
    '- **搬了什么**：台账存储、项目、对话这几个模块。',
    '- **验证结果**：单测与回放全部通过。',
  ].join('\n');
  const rawParas = splitMarkdownParagraphs(rawWithLink);
  assert.equal(rawParas.length, 3);
  assert.equal(rawWithLink.slice(rawParas[1].start, rawParas[1].end), rawParas[1].markdown);

  // locateQuoteRange on plain text AFTER a decorated link matches rawWithLink coordinates directly
  const exactInP1 = locateQuoteRange(rawWithLink, '台账存储、项目、对话');
  assert.ok(exactInP1);
  assert.equal(rawWithLink.slice(exactInP1.start, exactInP1.end), '台账存储、项目、对话');
  assert.equal(exactInP1.paragraph, rawParas[1].index);
  assert.ok(exactInP1.start >= rawParas[1].start && exactInP1.end <= rawParas[1].end);

  // locateQuoteRange also maps rendered plain-text selection (with stripped **bold** or decorated #221 prefix) back to canonical raw coordinates!
  const renderedBoldSel = locateQuoteRange(rawWithLink, '搬了什么：台账存储');
  assert.ok(renderedBoldSel, 'maps stripped bold markdown back to raw offsets');
  assert.equal(renderedBoldSel.paragraph, 1);
  assert.ok(renderedBoldSel.start >= rawParas[1].start && renderedBoldSel.end <= rawParas[1].end);
  const renderedDecoratedLinkSel = locateQuoteRange(rawWithLink, '进展：#221 重构 3b 已经交审');
  assert.ok(renderedDecoratedLinkSel, 'maps #num-decorated thread link selection back to raw offsets');
  assert.equal(renderedDecoratedLinkSel.paragraph, 0);
  assert.equal(renderedDecoratedLinkSel.start, 0);

  // (3) End-to-end PmProject test: clicking paragraph quote on a PM message with [title](thread:...) uses canonical raw offsets (NOT shifted by +5 from "#221 "), while display TextView still renders "[#221 重构 3b]"!
  const fs = await import('node:fs');
  const rawMain = fs.readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const source = `${rawMain
    .replace(/^\s*import\s+[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/export\s+default\s+class\s+/, 'class ')}\nreturn PmProject;`;

  const nodes = new Map();
  const textViews = new Map();
  const allTexts = rec => [...rec.texts, ...rec.kids.flatMap(allTexts)];
  const makeEl = (extra = {}) => {
    const rec = { id: '', texts: [], kids: [], clicks: null, hovers: [], ...extra };
    const proxy = new Proxy(() => proxy, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') { if (typeof args[0] === 'string') rec.texts.push(args[0]); else if (args[0]?.__rec) rec.kids.push(args[0].__rec); }
          else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) { if (typeof k === 'string') rec.texts.push(k); else if (k?.__rec) rec.kids.push(k.__rec); }
          }
          else if (key === 'content' && args[0]?.__rec) rec.kids.push(args[0].__rec);
          else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'on_hover') rec.hovers.push(args[0]);
          else if (key === 'when') { if (args[0]) args[1](proxy); }
          return proxy;
        };
      },
      apply: () => proxy,
    });
    rec.allTexts = () => allTexts(rec);
    return proxy;
  };
  let clipText = '';
  const stubs = {
    View: class {}, ...model,
    div: () => makeEl(), h_flex: () => makeEl(), v_flex: () => makeEl(), svg: () => makeEl(), image: () => makeEl(),
    TextView: {
      markdown: (id, md) => { const el = makeEl({ raw: String(md ?? '') }).child(String(md ?? '')); textViews.set(id, el.__rec); return el; },
      html: (id, html) => { const el = makeEl({ raw: String(html ?? '') }).child(String(html ?? '')); textViews.set(id, el.__rec); return el; },
    },
    TextareaState: { new: () => ({ on() {}, value: () => '', content: () => ({ text: '', tokens: [] }), selected_range: () => ({ start: 0, end: 0 }), set_selected_range() {}, set_value() {}, set_auto_grow() {}, set_soft_wrap() {}, focus() {} }) },
    Textarea: { new: () => makeEl() }, InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, focus() {} }) }, Input: { new: () => makeEl() },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) }, Scrollbar: { new: () => makeEl() }, Popup: { new: (id, trigger) => makeEl().id(id).child(trigger) },
    theme: () => ({
      canvas: '#111', surface: '#181818', raised: '#222', chrome: '#161616', hover: '#2a2a2a',
      border: '#333', input: '#3a3a3a', foreground: '#eee', background: '#111',
      muted: '#aaa', dim: '#777', accent: '#4f8cff', accent_foreground: '#fff',
      blocked: '#ff5f56', ansi2: '#27c93f', ansi3: '#f5a623', solid: '#eee', solid_foreground: '#111',
    }),
    home: () => '/Users/test', appHome: () => '/app',
    exec: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    execPython: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    readTextFile: async () => '', writeTextFile: async () => {}, watchFolder: () => new Promise(() => {}),
    layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run() {}, terminals: () => [{ address: 'tpm', state: 'live', labels: { pm: 'dudu' } }],
    agents: () => [], panes: () => [{ terminal: 'tpm' }], spaces: () => [],
    shared: () => ({ pm: 'pm-dudu' }), setShared() {}, appWindow: () => ({ platform: 'macos' }),
  };
  const prevStorage = globalThis.localStorage;
  const storeMap = new Map();
  globalThis.localStorage = { getItem: k => storeMap.get(k) ?? null, setItem: (k, v) => storeMap.set(k, String(v)), removeItem: k => storeMap.delete(k) };
  try {
    const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
    const timers = [];
    const cx = {
      phase: () => 'event', focus_handle: () => ({ focus() {} }), spawn: fn => fn(cx),
      timer: { after: (ms, fn) => { const t = { ms, fn, cancelled: false, cancel() { this.cancelled = true; } }; timers.push(t); return t; } },
      notify() {}, stop_propagation() {}, read_from_clipboard: () => clipText,
    };
    const today = (() => { const d = new Date(), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; })();
    const at = t => `${today} ${t}`;
    const pmKey = `pm:${at('09:10:00')}:`;
    const pmLocal = { name: 'pm-dudu', project: 'dudu', repo: '/work/dudu', pane: 'hc:tpm', runtime: 'hc', status: 'live' };
    const view = Object.assign(Object.create(Mod.prototype), {
      state: { pms: [pmLocal], tasks: [{ id: 't-221', pm: 'pm-dudu', title: '重构 3b', number: 221, status: 'review', updated: at('09:09') }], task_numbers: { 't-221': 221 }, events: [], lang: 'zh' },
      events: [{ at: at('09:10:00'), type: 'pm', text: rawWithLink }],
      pending: [], seq: 0, pastes: [], error: '', logError: '',
      pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
      remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
      earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '/here', watching: {},
      thread: '', threadTask: null, detail: false, threadError: '', threadLog: null, threadLogKept: [],
      threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null, threadTab: 'log', sideTab: 'threads',
      librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: false, libraryProbed: true, libraryStale: false,
      libraryLoading: false, libraryAgain: false, libraryError: '', libraryClosed: new Set(), libraryQuery: '',
      libraryDropBusy: '', libraryDropError: '', memorySlug: '', memoryData: null, memoryRead: false, memoryStale: false,
      memoryLoading: false, memoryAgain: false, memoryError: '', memoryFoldOverrides: new Map(), memoryProjectOpen: true,
      memoryPersonalOpen: false, memoryCandidatesOpen: false, memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
      activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '', docShownBytes: model.DOC_INITIAL_BYTES,
      docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
      editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
      confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
      reattaching: '', reattachError: null, startingPm: '', startPmError: null,
      bringBackOpen: false, bringingBack: false, bringBackProgress: null,
      listShown: true, wide: true, measured: true, viewWidth: 1280, panelWant: null, panelDrag: null, gripLit: false,
      seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
      bell: null, flash: '', flashPara: '', unfolded: new Map(), newest: '', atWork: new Set(),
      scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
      libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
      mentionScroll: { scroll_to_item() {} }, mention: null, mentionDismissed: null, mentionConsumedKey: false, mentionPicking: false,
      repoFilesSlug: '', repoFilesRepo: '', repoFiles: [], repoFilesRead: false, repoFilesLoading: false, repoFilesAgain: false,
      repoFilesError: '', repoFilesTruncated: false, repoFilesAt: 0, pathCopiedAt: 0,
      quotes: [], quoteSeq: 0, hoveredMsg: pmKey, hoverClipboard: '', selectionBar: null,
      hoveredPara: `${pmKey}#p1`, pendingHoverPara: '', paraHoverShowTimer: null, paraHoverHideTimer: null, paraHoverSeq: 0, paraCache: new Map(),
      lastBlocks: [], lastTopOffset: 0, lastHeights: [], lastTall: 0,
      keyFocus: { focus() {} }, onStage: true, typing: 'main', mainKey: 'pm:pm-dudu', threadKey: '',
      outgoing: new Map(), files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
      input: stubs.TextareaState.new(), threadInput: stubs.TextareaState.new(), libraryInput: stubs.InputState.new(), memoryInput: stubs.InputState.new(),
      docFindInput: stubs.InputState.new(), docNameInput: stubs.InputState.new(), memDescInput: stubs.InputState.new(),
      docEditorInput: stubs.TextareaState.new(), refresh: () => {},
    });
    view.resetThreadSession();

    view.render(cx);
    // Display markdown STILL decorates paragraph 0 with `#221 `
    assert.ok(textViews.get(`md-${pmKey}-p0`)?.raw.includes('[#221 重构 3b](thread:t-221)'), 'display markdown keeps #221 decoration');

    // Clicking paragraph 1 quote button yields canonical rawWithLink coordinates (NOT shifted by +5!)
    nodes.get(`para-quote-btn-${pmKey}-1`).clicks({ stop_propagation() {} }, cx);
    // Clicking whole-message quote button after copying a substring inside paragraph 1 yields exact coordinates in the SAME rawWithLink coordinate space!
    clipText = '台账存储、项目、对话';
    nodes.get(`quote-btn-${pmKey}`).clicks({ stop_propagation() {} }, cx);

    assert.equal(view.quotes.length, 2);
    const paraQ = view.quotes[0];
    const selQ = view.quotes[1];
    assert.equal(paraQ.scope, 'paragraph');
    assert.equal(selQ.scope, 'selection');
    assert.equal(paraQ.range.start, rawParas[1].start, 'paragraph start equals canonical raw offset (0 drift despite #221 link in p0)');
    assert.equal(paraQ.range.end, rawParas[1].end, 'paragraph end equals canonical raw offset');
    assert.equal(rawWithLink.slice(paraQ.range.start, paraQ.range.end), rawParas[1].markdown);
    assert.equal(rawWithLink.slice(selQ.range.start, selQ.range.end), '台账存储、项目、对话');
    assert.equal(selQ.range.paragraph, paraQ.range.paragraph, 'exact selection & paragraph agree on paragraph index');
    assert.ok(selQ.range.start >= paraQ.range.start && selQ.range.end <= paraQ.range.end, 'exact selection range lies strictly inside paragraph range in canonical raw coordinates');
  } finally {
    globalThis.localStorage = prevStorage;
  }
});

test('send-confirm follow-ups: unsettled sends survive a reload, resend checks the log, wording, session key', () => {
  const t0 = model.eventTime('2026-11-22 10:00:00');
  const base = { said: 'x', words: 'x', to: '', files: [], draftKey: 'pm:pm-dudu' };
  // (3) Every unsettled stage is kept with where it got to; a failed one is not (its words went back to the draft).
  const stored = model.keepQueuedSends({}, 'pm-dudu', [
    { ...base, id: 1, text: '排队', sentAt: t0, queued: true },
    { ...base, id: 2, text: '发送中', sentAt: t0 + 1, queued: false, inFlight: true, inFlightAt: t0 + 5, inFlightTo: 't182', inFlightSession: 'fg:10504' },
    { ...base, id: 3, text: '已送达未确认', sentAt: t0 + 2, queued: false, deliveredAt: t0 + 6, sentTo: 't182', sentSession: 'fg:10504', idleSince: t0 + 7 },
    { ...base, id: 4, text: '核对中', sentAt: t0 + 3, queued: false, verifying: true, verifySince: t0 + 8 },
    { ...base, id: 5, text: '失败', sentAt: t0 + 4, queued: false, failed: 'boom' },
  ]);
  const read = model.readQueuedSends(JSON.stringify(stored))['pm-dudu'];
  assert.deepEqual(read.map(x => [x.text, x.stage, x.queued]),
    [['排队', 'queued', true], ['发送中', 'inFlight', false], ['已送达未确认', 'delivered', false], ['核对中', 'verifying', false]]);
  // Entries from before stages were stored read back as queued.
  assert.equal(model.readQueuedSends(JSON.stringify({ p: [{ id: 1, text: 'old', queued: true }] })).p[0].stage, 'queued');

  const now = t0 + 60000;
  const { pending } = model.restoreQueuedPending(read, [], now);
  const by = Object.fromEntries(pending.map(p => [p.text, p]));
  assert.equal(by['排队'].queued, true);
  // A send under way at reload comes back sent-but-unsure toward where it was going: it waits for the log, never re-sends by itself.
  assert.deepEqual([by['发送中'].queued, by['发送中'].inFlight, by['发送中'].deliveredAt, by['发送中'].sentTo, by['发送中'].sentSession, by['发送中'].unsure],
    [false, false, t0 + 5, 't182', 'fg:10504', true]);
  assert.deepEqual([by['已送达未确认'].queued, by['已送达未确认'].deliveredAt, by['已送达未确认'].idleSince, by['已送达未确认'].sentTo], [false, t0 + 6, 0, 't182']);
  assert.deepEqual([by['核对中'].verifying, by['核对中'].verifySince], [true, now]);
  // Restoring again over what is in memory adds nothing twice.
  assert.equal(model.restoreQueuedPending(read, pending, now).pending.length, 4);

  // The restored sends settle against the log: nothing is sent again for the ones it has.
  const logged = [{ at: '2026-11-22 10:00:01', type: 'user', text: '发送中' }, { at: '2026-11-22 10:00:01', type: 'user', text: '已送达未确认' }];
  const r1 = model.reconcilePendingSends(pending, logged, { now: now + 100, pmAddress: 't182', pmSession: 'fg:10504', logReady: true, logFreshFrom: now + 50, lang: 'zh' });
  assert.deepEqual(r1.settled.map(p => p.text).sort(), ['发送中', '已送达未确认'].sort());
  assert.deepEqual(r1.requeued.map(p => p.text), ['核对中'], 'the resend being checked was not in a fresh log -> goes out');
  // An unsure one the log never gets times out with its own words.
  const unsure = pending.find(p => p.text === '发送中');
  const r2 = model.reconcilePendingSends([{ ...unsure, idleSince: now }], [], { now: now + 13000, pmAddress: 't182', pmSession: 'fg:10504', logReady: true, lang: 'zh' });
  assert.equal(r2.failed[0].failed, model.word('zh', 'unsureSend'));
  assert.equal(r2.failed[0].timedOut, true);

  // (1) A resend waits for a log read that began after the click.
  const v = { ...base, id: 7, text: '重发前核对', sentAt: t0, verifying: true, verifySince: now };
  const stale = model.reconcilePendingSends([v], [], { now: now + 500, pmAddress: 't182', logReady: true, logFreshFrom: now - 1, lang: 'zh' });
  assert.equal(stale.requeued.length, 0);
  assert.equal(stale.needsFollowup, true);
  assert.equal(stale.pending[0].verifying, true, 'a log read begun before the click proves nothing');
  const has = model.reconcilePendingSends([v], [{ at: '2026-11-22 10:00:30', type: 'user', text: '重发前核对' }],
    { now: now + 500, pmAddress: 't182', logReady: true, logFreshFrom: now + 10, lang: 'zh' });
  assert.deepEqual([has.pending.length, has.settled.length, has.requeued.length], [0, 1, 0], 'in the log (written after the timeout) -> delivered, not sent');
  const old = model.reconcilePendingSends([v], [{ at: '2026-11-22 09:50:00', type: 'user', text: '重发前核对' }],
    { now: now + 500, pmAddress: 't182', logReady: true, logFreshFrom: now + 10, lang: 'zh' });
  assert.equal(old.requeued.length, 1, 'the same words said before this message was sent do not count');
  assert.equal(old.requeued[0].queued, true);
  assert.equal(old.requeued[0].requeuedFromSend, true);
  const unreadable = model.reconcilePendingSends([v], [], { now: now + model.RESEND_VERIFY_WAIT_MS, pmAddress: 't182', logReady: false, lang: 'zh' });
  assert.equal(unreadable.requeued.length, 1, 'a log that cannot be read does not hold back the resend the user asked for');

  // (4) The timed-out state says what is known, with no "not sent:" in front of it, in both languages.
  assert.equal(model.word('zh', 'unconfirmedSend'), '已送到 PM 终端，但对话里一直没记下这条');
  assert.equal(model.word('en', 'unconfirmedSend'), 'Delivered to the PM terminal, but it never showed up in the conversation');
  for (const lang of ['zh', 'en']) {
    for (const k of ['unconfirmedSend', 'unsureSend', 'checkingSent']) assert.ok(model.word(lang, k) && model.word(lang, k) !== k, `${lang}.${k}`);
    assert.doesNotMatch(model.word(lang, 'unconfirmedSend'), /没发出去|Not sent|未确认|did not confirm/i);
  }
  const items = model.timeline([], [], { pending: [
    { id: 1, text: 'a', sentAt: t0, failed: model.word('zh', 'unconfirmedSend'), timedOut: true },
    { id: 2, text: 'b', sentAt: t0, failed: 'hc send: boom' },
    { id: 3, text: 'c', sentAt: t0, verifying: true, verifySince: t0 },
  ] }).filter(i => i.kind === 'user');
  assert.deepEqual(items.map(i => [Boolean(i.unconfirmed), Boolean(i.checking), i.pending]), [[true, false, false], [false, false, false], [false, true, true]]);

  // (2) Measured 2026-11-22: Claude Code, Codex and pi run their tools without the terminal (no tty, own
  // process group), so the foreground stays the agent while a tool runs, and the session key holds.
  const pmTerm = { address: 't182', pid: 10387, labels: { 'pm.seat': '1' }, foreground: { pid: 10504, argv: ['claude', '--model', 'opus'] } };
  assert.equal(model.pmSessionKey(pmTerm), 'fg:10504');
  assert.equal(model.pmSessionKey({ ...pmTerm, status: { state: 'working' } }), 'fg:10504');
  assert.equal(model.pmSessionKey({ ...pmTerm, foreground: { pid: 10387, argv: ['python3', '/x/pm.py', 'seat'] } }), '', 'seat holding the tty between sessions');
});

test('render-perf caches: invalidation on message/quote/send-state/task/lang/theme/host updates, delayed panel unmount, lazy hover card & taskNumberFor precedence', async () => {
  const fs = await import('node:fs');
  const stepsMod = await import('./steps.js');
  const rawMain = fs.readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const source = `${rawMain
    .replace(/^\s*import\s+[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/export\s+default\s+class\s+/, 'class ')}\nreturn PmProject;`;

  let curTheme = {
    canvas: '#fafafa', surface: '#ffffff', raised: '#f4f4f6', chrome: '#f7f7f8', popover: '#ffffff',
    hover: '#ececef', border: '#e2e2e7', input: '#d4d4db', foreground: '#18181b', muted: '#52525b',
    dim: '#71717a', accent: '#2563eb', blocked: '#dc2626', solid: '#18181b', solid_foreground: '#ffffff',
    ansi2: '#16a34a', ansi3: '#d97706', working: '#16a34a', background: '#ffffff',
  };
  let curTerms = [{ address: 't-pm', state: 'live', status: 'idle', cwd: '/work/dudu', labels: { pm: 'dudu' } }];
  let curAgents = [{ address: 't-pm', status: 'idle', tab: 'tab1', seq: 1 }];
  let curSpaces = [{ id: 'sp1', tabs: [{ id: 'tab1', name: 'dudu', named: true }] }];
  const nodes = new Map();
  const textViews = new Map();
  const allTexts = rec => [...rec.texts, ...rec.kids.flatMap(allTexts)];
  const makeEl = (extra = {}) => {
    const rec = { id: '', bgColor: '', texts: [], kids: [], clicks: null, hovers: [], ...extra };
    const proxy = new Proxy(() => proxy, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'bg') { rec.bgColor = args[0]; }
          else if (key === 'child') { if (typeof args[0] === 'string') rec.texts.push(args[0]); else if (args[0]?.__rec) rec.kids.push(args[0].__rec); }
          else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) { if (typeof k === 'string') rec.texts.push(k); else if (k?.__rec) rec.kids.push(k.__rec); }
          }
          else if (key === 'content' && args[0]?.__rec) rec.kids.push(args[0].__rec);
          else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'on_hover') rec.hovers.push(args[0]);
          else if (key === 'when') { if (args[0]) args[1](proxy); }
          return proxy;
        };
      },
      apply: () => proxy,
    });
    rec.allTexts = () => allTexts(rec);
    return proxy;
  };
  const stubs = {
    View: class {}, ...model, ...stepsMod,
    div: () => makeEl(), h_flex: () => makeEl(), v_flex: () => makeEl(), svg: () => makeEl(), image: () => makeEl(),
    TextView: {
      markdown: (id, md) => { const el = makeEl({ raw: String(md ?? '') }).child(String(md ?? '')); textViews.set(id, el.__rec); return el; },
      html: (id, html) => { const el = makeEl({ raw: String(html ?? '') }).child(String(html ?? '')); textViews.set(id, el.__rec); return el; },
    },
    TextareaState: { new: () => ({ on() {}, value: () => '', content: () => ({ text: '', tokens: [] }), selected_range: () => ({ start: 0, end: 0 }), set_selected_range() {}, set_value() {}, set_auto_grow() {}, set_soft_wrap() {}, focus() {} }) },
    Textarea: { new: () => makeEl() }, InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, focus() {} }) }, Input: { new: () => makeEl() },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) }, Scrollbar: { new: () => makeEl() }, Popup: { new: (id, trigger) => makeEl().id(id).child(trigger) },
    theme: () => curTheme,
    home: () => '/Users/test', appHome: () => '/app',
    exec: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    execPython: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    readTextFile: async () => '', writeTextFile: async () => {}, watchFolder: () => new Promise(() => {}),
    layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run() {}, terminals: () => curTerms, agents: () => curAgents, panes: () => [{ terminal: 't-pm' }], spaces: () => curSpaces,
    shared: () => ({ pm: 'pm-dudu' }), setShared() {}, props: () => null, openOverlay() {}, closeOverlay() {},
    appWindow: () => ({ platform: 'macos' }),
    renderThreadChangeView: () => makeEl(),
    buildProjectSearch: () => ({ groups: [], flat: [] }), stepSearchSelection: () => 0, stepSearchScope: () => 'all',
    stepSearchEscape: () => ({}), renderProjectSearchOverlay: () => makeEl(),
  };
  const prevStorage = globalThis.localStorage;
  const store = new Map();
  globalThis.localStorage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) };
  try {
    const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
    const timers = [];
    const cx = {
      phase: () => 'event', focus_handle: () => ({ focus() {} }), spawn: fn => fn(cx),
      timer: {
        after: (ms, fn) => {
          const t = { ms, fn, cancelled: false, cancel() { this.cancelled = true; } };
          timers.push(t);
          return t;
        },
      },
      notify() {}, stop_propagation() {}, read_from_clipboard: () => '',
    };
    const today = (() => { const d = new Date(), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; })();
    const at = s => `${today} ${s}`;
    const pmRec = { name: 'pm-dudu', project: 'dudu', repo: '/work/dudu', pane: 'hc:t-pm', runtime: 'hc', status: 'live' };
    const mkTask = (overrides = {}) => ({
      id: 'dudu-perf', pm: 'pm-dudu', project: 'dudu', title: '渲染性能', number: 235,
      status: 'in_progress', updated: at('10:00:00'), plan: '[x] 量基线; [>] 做缓存; [ ] 验截图',
      latest: '量完基线', ...overrides,
    });
    const view = Object.assign(Object.create(Mod.prototype), {
      state: { pms: [pmRec], tasks: [mkTask()], task_numbers: { 'dudu-perf': 235 }, retired_parts: [], events: [], lang: 'zh' },
      events: [
        { at: at('10:00:00'), type: 'pm', text: '第一段：进度见 [渲染性能](thread:dudu-perf)。\n\n第二段：继续推进缓存失效测试。' },
      ],
      pending: [], seq: 0, pastes: [], error: '', logError: '',
      pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
      remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
      earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '/here', watching: {},
      thread: '', threadTask: null, detail: false, threadError: '', threadLog: null, threadLogKept: [],
      threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null, threadTab: 'log', sideTab: 'threads',
      librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: false, libraryProbed: true, libraryStale: false,
      libraryLoading: false, libraryAgain: false, libraryError: '', libraryClosed: new Set(), libraryQuery: '',
      libraryDropBusy: '', libraryDropError: '', memorySlug: '', memoryData: null, memoryRead: false, memoryStale: false,
      memoryLoading: false, memoryAgain: false, memoryError: '', memoryFoldOverrides: new Map(), memoryProjectOpen: true,
      memoryPersonalOpen: false, memoryCandidatesOpen: false, memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
      activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '', docShownBytes: model.DOC_INITIAL_BYTES,
      docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
      editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
      confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
      reattaching: '', reattachError: null, startingPm: '', startPmError: null,
      bringBackOpen: false, bringingBack: false, bringBackProgress: null,
      listShown: true, wide: true, measured: true, viewWidth: 1280, panelWant: null, panelDrag: null, gripLit: false,
      panelMounted: false, panelHideTimer: null, fadingKeys: null, fadeClearTimer: null,
      _timelineCache: null, _taskTreeCache: null, _mdLinkCache: null, _taskNumIndex: null, _projTasksCache: null, _blockKeySet: null,
      seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
      bell: null, flash: '', flashPara: '', unfolded: new Map(), newest: '', atWork: new Set(),
      scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
      libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
      mentionScroll: { scroll_to_item() {} }, mention: null, mentionDismissed: null, mentionConsumedKey: false, mentionPicking: false,
      repoFilesSlug: '', repoFilesRepo: '', repoFiles: [], repoFilesRead: false, repoFilesLoading: false, repoFilesAgain: false,
      repoFilesError: '', repoFilesTruncated: false, repoFilesAt: 0, pathCopiedAt: 0,
      quotes: [], quoteSeq: 0, hoveredMsg: '', hoverClipboard: '', selectionBar: null,
      hoveredPara: '', pendingHoverPara: '', paraHoverShowTimer: null, paraHoverHideTimer: null, paraHoverSeq: 0, paraCache: new Map(),
      lastBlocks: [], lastTopOffset: 0, lastHeights: [], lastTall: 0,
      keyFocus: { focus() {} }, onStage: true, typing: '', mainKey: 'pm:pm-dudu', threadKey: '',
      outgoing: new Map(), files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
      input: stubs.TextareaState.new(), threadInput: stubs.TextareaState.new(), libraryInput: stubs.InputState.new(), memoryInput: stubs.InputState.new(),
      docFindInput: stubs.InputState.new(), docNameInput: stubs.InputState.new(), memDescInput: stubs.InputState.new(),
      docEditorInput: stubs.TextareaState.new(), refresh: () => {},
    });
    view.resetThreadSession();

    const rerender = () => { nodes.clear(); textViews.clear(); view.render(cx); };

    // 1. Steady render hits timeline, taskTree, and markdown caches (same object references).
    rerender();
    const tl1 = view._timelineCache;
    const tt1 = view._taskTreeCache?.tree;
    const mdMap1 = view._mdLinkCache?.map;
    assert.ok(tl1 && tt1 && mdMap1, 'all three caches populated on first render');
    assert.ok(textViews.get(`md-pm:${at('10:00:00')}:-p0`)?.raw.includes('[#235 渲染性能](thread:dudu-perf)'));
    assert.equal(nodes.has('hover-card-body-task:dudu-perf'), false, 'hover card stays unbuilt until hovered');

    view.hoveredMsg = `pm:${at('10:00:00')}:`;
    rerender();
    assert.equal(view._timelineCache, tl1, 'message hover reuses timeline cache');
    assert.equal(view._taskTreeCache.tree, tt1, 'message hover reuses taskTree cache');
    assert.equal(view._mdLinkCache.map, mdMap1, 'message hover reuses decorated markdown cache');

    // 2. Lazy hover card builds on demand without invalidating taskTree cache.
    view.hoverKey = 'task:dudu-perf';
    rerender();
    assert.equal(view._taskTreeCache.tree, tt1, 'hovering a thread row still reuses taskTree cache');
    assert.ok(nodes.get('hover-card-body-task:dudu-perf')?.allTexts().join(' ').includes('做缓存'), 'lazy hover card renders current steps');
    view.hoverKey = '';

    // 3. Message update invalidates timeline cache immediately.
    view.events = [...view.events, { at: at('10:01:00'), type: 'pm', text: '新消息到达' }];
    rerender();
    assert.notEqual(view._timelineCache, tl1, 'new event invalidates timeline cache');
    assert.ok(textViews.get(`md-pm:${at('10:01:00')}:`)?.raw.includes('新消息到达'));

    // 4. Send-state transitions (including in-place mutation of pending item + quoted pending message) invalidate timeline cache!
    const quotedText = model.formatQuotedMessage([{
      targetKey: `pm:${at('10:00:00')}:`, kind: 'pm', author: 'PM', time: '10:00', text: '第一段：进度见 渲染性能。',
      scope: 'paragraph', range: { start: 0, end: 10, paragraph: 0, kind: 'paragraph' },
    }], '收到');
    const pItem = { id: 1, text: quotedText, sentAt: Date.now(), queued: false, inFlight: true };
    view.pending = [pItem];
    rerender();
    const tlSending = view._timelineCache;
    assert.ok(nodes.has('bubble-quotes-pending:1'), 'quoted pending bubble renders quote card');
    assert.equal(view.items.find(i => i.key === 'pending:1')?.pending, true);
    // In-place state transitions: sending -> timedOut failed -> verifying/checking -> queued -> settled
    pItem.inFlight = false;
    pItem.timedOut = true;
    pItem.failed = model.word('zh', 'unconfirmedSend');
    rerender();
    assert.notEqual(view._timelineCache, tlSending, 'in-place pending timeout invalidates timeline cache');
    assert.equal(view.items.find(i => i.key === 'pending:1')?.unconfirmed, true);
    assert.ok(nodes.has('failed-pending:1'), 'failed banner appears immediately');

    pItem.failed = '';
    pItem.timedOut = false;
    pItem.verifying = true;
    rerender();
    assert.equal(view.items.find(i => i.key === 'pending:1')?.checking, true, 'checking/verifying transition invalidates cache');

    pItem.verifying = false;
    pItem.queued = true;
    curAgents = [{ address: 't-pm', status: 'blocked', tab: 'tab1', seq: 1 }];
    rerender();
    assert.ok(nodes.has('queued-pending:1'), 'queued transition invalidates cache');
    curAgents = [{ address: 't-pm', status: 'idle', tab: 'tab1', seq: 1 }];

    view.pending = [];
    rerender();
    assert.equal(nodes.has('bubble-pending:1'), false, 'settled send clears bubble immediately');

    // 5. Task number update invalidates decorated markdown cache AND taskNumberFor index!
    view.state = {
      ...view.state,
      tasks: [mkTask({ number: 999 })],
      task_numbers: { 'dudu-perf': 999 },
    };
    rerender();
    assert.equal(view.taskNumberFor('dudu-perf'), 999);
    assert.ok(textViews.get(`md-pm:${at('10:00:00')}:-p0`)?.raw.includes('[#999 渲染性能](thread:dudu-perf)'), 'updated #num refreshes cached markdown');

    // 6. Language switch invalidates taskTree group titles & UI labels immediately.
    const tlBeforeLang = view._timelineCache;
    view.state = { ...view.state, lang: 'en' };
    rerender();
    assert.equal(view._taskTreeCache.lang, 'en');
    assert.equal(view._taskTreeCache.tree.groups[0].title, model.word('en', 'group_working'), 'lang switch updates taskTree group titles');
    assert.equal(view._timelineCache, tlBeforeLang, 'lang-independent timeline data can stay cached while rendered labels switch');
    assert.ok(nodes.get('thread-list')?.allTexts().includes(model.word('en', 'group_working')), 'panel shows English group heading');

    // 7. Theme switch updates rendered colors immediately while caches stay warm.
    const prevCanvas = nodes.get('pm-project-root')?.bgColor;
    curTheme = { ...curTheme, canvas: '#111214', surface: '#1b1c20', raised: '#22242a', chrome: '#16171b', foreground: '#f4f4f5' };
    rerender();
    assert.notEqual(nodes.get('pm-project-root')?.bgColor, prevCanvas);
    assert.equal(nodes.get('pm-project-root')?.bgColor, '#111214', 'theme switch paints dark canvas immediately');

    // 8. Live terminal / agent status change invalidates taskTree cache immediately.
    const ttBeforeLive = view._taskTreeCache.tree;
    curTerms = [...curTerms, { address: 't-w1', state: 'live', status: 'working', cwd: '/work/dudu', labels: { task: 'dudu-perf' } }];
    curAgents = [...curAgents, { address: 't-w1', status: 'working', tab: 'tab1', seq: 2 }];
    rerender();
    assert.notEqual(view._taskTreeCache.tree, ttBeforeLive, 'live agent/terminal change invalidates taskTree cache');
    assert.equal(view._taskTreeCache.tree.flatOpen[0].working, true);

    // 9. Side panel delayed unmount: stays mounted during 200ms slide-out, unmounts once 220ms timer fires,
    //    and re-opening before 220ms cancels the unmount timer.
    assert.equal(view.panelMounted, true);
    assert.ok(nodes.has('thread-list'), 'panel content mounted while open');
    view.listShown = false;
    view.wide = false;
    rerender();
    assert.equal(view.panelMounted, true, 'panel content stays mounted during slide-out transition');
    assert.ok(nodes.has('thread-list'), 'panel content still drawn during transition');
    const hideTimer = timers.filter(t => t.ms === 220 && !t.cancelled).pop();
    assert.ok(hideTimer, '220ms delayed unmount timer armed');
    // Re-open before timer fires -> cancels timer and stays mounted
    view.listShown = true;
    rerender();
    assert.equal(hideTimer.cancelled, true, 're-opening cancels delayed unmount timer');
    // Close again and let timer fire -> unmounts cleanly
    view.listShown = false;
    rerender();
    const hideTimer2 = timers.filter(t => t.ms === 220 && !t.cancelled).pop();
    assert.ok(hideTimer2);
    hideTimer2.fn(cx);
    assert.equal(view.panelMounted, false);
    rerender();
    assert.equal(nodes.has('thread-list'), false, 'closed panel skips building threadsPanel once unmounted');

    // 10. taskNumberFor O(1) index preserves exact precedence: object > tasks > retired_parts > threadTask > task_numbers.
    view.tasks = [{ id: 'a', number: 10 }, { id: 'no-num' }];
    view.state = {
      ...view.state,
      tasks: view.tasks,
      retired_parts: [{ id: 'a', number: 20 }, { id: 'b', number: 30 }],
      task_numbers: { a: 40, b: 50, c: 60, 'no-num': 70 },
    };
    view.threadTask = { id: 'c', number: 35 };
    assert.equal(view.taskNumberFor({ id: 'a', number: 99 }), 99, 'object number wins');
    assert.equal(view.taskNumberFor('a'), 10, 'tasks list beats retired_parts and task_numbers');
    assert.equal(view.taskNumberFor('b'), 30, 'retired_parts beats task_numbers');
    assert.equal(view.taskNumberFor('c'), 35, 'threadTask beats task_numbers');
    assert.equal(view.taskNumberFor('no-num'), 70, 'task without number in list falls back to task_numbers');

    // 11. taskTree({ alreadyFolded: true }) matches standard taskTree output exactly.
    const rawTasks = [
      mkTask({ id: 't1', status: 'in_progress', number: 1 }),
      { id: 't1-review', pm: 'pm-dudu', review_of: 't1', status: 'in_progress', title: 'review t1', updated: at('10:02:00') },
      mkTask({ id: 't2', status: 'done', number: 2 }),
    ];
    const tNormal = model.taskTree(pmRec, rawTasks, view.events, { terms: curTerms, live: curAgents, lang: 'zh' });
    const tPre = model.taskTree(pmRec, model.foldReviews(rawTasks), view.events, { terms: curTerms, live: curAgents, lang: 'zh', alreadyFolded: true });
    assert.deepEqual(tPre, tNormal, 'alreadyFolded taskTree matches standard taskTree');
  } finally {
    globalThis.localStorage = prevStorage;
  }
});

test('cache-key alignment guard: Proxy read audit catches any field read by taskTree/timeline/render that hostLiveSignature or pendingSignature omits', async () => {
  const fs = await import('node:fs');
  const stepsMod = await import('./steps.js');
  const rawMain = fs.readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const source = `${rawMain
    .replace(/^\s*import\s+[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/export\s+default\s+class\s+/, 'class ')}\nreturn PmProject;`;

  // Recursive Proxy that records every leaf property path accessed on an input record.
  const isPlainObj = v => Boolean(v) && typeof v === 'object' && !Array.isArray(v);
  const trackObj = (obj, prefix, reads) => {
    if (!isPlainObj(obj)) return obj;
    return new Proxy(obj, {
      get(target, prop, receiver) {
        if (typeof prop !== 'string') return Reflect.get(target, prop, receiver);
        if (prop === 'toJSON' || prop === 'valueOf' || prop === 'toString' || prop === 'constructor' || prop === 'then') {
          return Reflect.get(target, prop, receiver);
        }
        const val = Reflect.get(target, prop, receiver);
        const path = `${prefix}.${prop}`;
        if (isPlainObj(val)) return trackObj(val, path, reads);
        reads.add(path);
        return val;
      },
    });
  };
  const trackList = (arr, prefix, reads) => arr.map(item => trackObj(item, prefix, reads));

  const today = (() => { const d = new Date(), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; })();
  const at = s => `${today} ${s}`;
  const makeFixture = () => ({
    pm: {
      name: 'pm-dudu', project: 'dudu', repo: '/work/dudu', worktrees: '/wt/dudu',
      pane: 'hc:t-pm', runtime: 'hc', status: 'live', counts: { waiting: 1 },
    },
    tasks: [
      {
        id: 't-main', pm: 'pm-dudu', project: 'dudu', title: 'Main task', number: 241,
        status: 'review', updated: at('11:00:00'), pane: 'hc:t-w1',
        helpers: [
          { name: 'h-ledger', status: 'running', terminal: 't-h1', kind: 'claude' },
        ],
      },
      {
        id: 't-main-review', pm: 'pm-dudu', project: 'dudu', review_of: 't-main',
        title: 'Review main', status: 'in_progress', updated: at('11:01:00'), pane: 'hc:t-rev',
      },
      {
        id: 't-blocked', pm: 'pm-dudu', project: 'dudu', title: 'Waiting task', number: 242,
        status: 'blocked', updated: at('11:02:00'),
      },
    ],
    events: [
      { at: at('11:00:00'), type: 'thread', task: 't-main', status: 'in_progress', title: 'Main task' },
      { at: at('11:02:00'), type: 'thread', task: 't-blocked', status: 'blocked', title: 'Waiting task', text: 'Pick one?', options: ['A', 'B'] },
    ],
    terms: [
      { address: 't-pm', state: 'live', status: 'idle', cwd: '/work/dudu', context_tokens: 12000, program: { key: 'claude', name: 'Claude', icon: 'claude.svg', tint: true, shell: false }, labels: { pm: 'dudu' } },
      { address: 't-w1', state: 'live', status: 'working', cwd: '/wt/dudu/w1', context_tokens: 45000, program: { key: 'codex', name: 'Codex', icon: 'codex.png', tint: false, shell: false }, labels: { task: 't-main' } },
      { address: 't-rev', state: 'live', status: 'working', cwd: '/wt/dudu/rev', context_tokens: 32000, program: { key: 'claude', name: 'Claude', icon: 'claude.svg', tint: true, shell: false }, labels: { task: 't-main-review' } },
      { address: 't-h1', state: 'live', status: 'working', cwd: '/work/dudu', context_tokens: 9000, program: { key: 'claude', name: 'Claude', icon: 'claude.svg', tint: true, shell: false }, labels: { 'helper.of': 't-main', helper: 'h-ledger' } },
      { address: 't-h2', state: 'live', status: 'working', cwd: '/work/dudu', context_tokens: 6000, program: { key: 'agy', name: 'Antigravity', icon: 'agy.svg', tint: true, shell: false }, labels: { 'helper.of': 't-main', helper: 'research-a' } },
      { address: 't-sess', state: 'live', status: 'idle', cwd: '/work/dudu', context_tokens: 0, program: { key: 'codex', name: 'Codex', icon: 'codex.png', tint: false, shell: false }, labels: {} },
      { address: 't-sh', state: 'live', status: 'idle', cwd: '/work/dudu', context_tokens: 0, program: { key: 'zsh', name: 'zsh', icon: 'sh.svg', tint: true, shell: true }, labels: {} },
    ],
    live: [
      { address: 't-pm', status: 'idle', tab: 'tab1', seq: 1, title: 'PM', app: 'claude-code', program: { key: 'claude', name: 'Claude', icon: 'claude.svg', tint: true, shell: false } },
      { address: 't-w1', status: 'working', tab: 'tab1', seq: 2, title: 'Worker', app: 'codex', program: { key: 'codex', name: 'Codex', icon: 'codex.png', tint: false, shell: false } },
      { address: 't-rev', status: 'working', tab: 'tab1', seq: 3, title: 'Reviewer', app: 'claude-code', program: { key: 'claude', name: 'Claude', icon: 'claude.svg', tint: true, shell: false } },
      { address: 't-h2', status: 'working', tab: 'tab1', seq: 4, title: 'Helper', app: 'antigravity', program: { key: 'agy', name: 'Antigravity', icon: 'agy.svg', tint: true, shell: false } },
      { address: 't-sess', status: 'idle', tab: 'tab2', seq: 5, title: 'Free session', app: 'codex', program: { key: 'codex', name: 'Codex', icon: 'codex.png', tint: false, shell: false } },
      { address: 't-sh', status: 'idle', tab: 'tab3', seq: 6, title: 'Shell', app: 'zsh', program: { key: 'zsh', name: 'zsh', icon: 'sh.svg', tint: true, shell: true } },
    ],
    tabs: [
      { id: 'tab1', name: 'dudu', named: true },
      { id: 'tab2', name: 'Scratchpad', named: true },
      { id: 'tab3', name: 'zsh', named: false },
    ],
    pending: [
      { id: 1, text: 'hello queued', sentAt: Date.now() - 3000, deliveredAt: 0, queued: true, inFlight: false, timedOut: false, verifying: false, failed: '', upload: false, question: '' },
      { id: 2, text: '【Waiting task】A', sentAt: Date.now() - 2000, deliveredAt: Date.now() - 1500, queued: false, inFlight: false, timedOut: true, verifying: false, failed: 'unconfirmed', upload: true, question: `question:${at('11:02:00')}:t-blocked` },
      { id: 3, text: 'verifying send', sentAt: Date.now() - 1000, deliveredAt: 0, queued: false, inFlight: true, timedOut: false, verifying: true, failed: '', upload: false, question: '' },
    ],
  });

  // (1) Proxy audit: every field of terms/live/tabs read by taskTree() + PmProject.render() MUST be read by hostLiveSignature().
  const f1 = makeFixture();
  const computeReads = new Set();
  const sigReads = new Set();
  model.taskTree(f1.pm, f1.tasks, f1.events, {
    terms: trackList(f1.terms, 'term', computeReads),
    live: trackList(f1.live, 'live', computeReads),
    tabs: trackList(f1.tabs, 'tab', computeReads),
    lang: 'zh',
  });
  model.hostLiveSignature(
    trackList(f1.terms, 'term', sigReads),
    trackList(f1.live, 'live', sigReads),
    trackList(f1.tabs, 'tab', sigReads),
  );
  const missingHostInTaskTree = [...computeReads].filter(p => !sigReads.has(p));
  assert.deepEqual(missingHostInTaskTree, [], `taskTree read host fields missing from hostLiveSignature: ${missingHostInTaskTree.join(', ')}`);
  for (const expected of ['term.labels.helper', 'term.program.key', 'term.program.tint', 'term.program.shell', 'term.context_tokens', 'live.app', 'live.program.key', 'tab.named']) {
    assert.ok(computeReads.has(expected), `Proxy audit fixture exercises ${expected}`);
    assert.ok(sigReads.has(expected), `hostLiveSignature covers ${expected}`);
  }

  // (2) Proxy audit: every field of pending read by timeline() MUST be read by pendingSignature().
  const pendComputeReads = new Set();
  const pendSigReads = new Set();
  model.timeline(f1.events, f1.tasks, {
    pending: trackList(f1.pending, 'pending', pendComputeReads),
    today, typing: false, pastes: [], pm: f1.pm.name, pmPane: f1.pm.pane,
  });
  model.pendingSignature(trackList(f1.pending, 'pending', pendSigReads));
  const missingPending = [...pendComputeReads].filter(p => !pendSigReads.has(p));
  assert.deepEqual(missingPending, [], `timeline read pending fields missing from pendingSignature: ${missingPending.join(', ')}`);

  // (3) Mutation sensitivity: mutating ANY tracked host field must change hostLiveSignature().
  const baseHostSig = model.hostLiveSignature(f1.terms, f1.live, f1.tabs);
  const hostMutations = [
    ['term.address', f => { f.terms[4].address = 't-h2-new'; }],
    ['term.state', f => { f.terms[4].state = 'dead'; }],
    ['term.status', f => { f.terms[4].status = 'idle'; }],
    ['term.cwd', f => { f.terms[5].cwd = '/work/other'; }],
    ['term.context_tokens', f => { f.terms[4].context_tokens = 18000; }],
    ['term.program.key', f => { f.terms[4].program.key = 'codex'; }],
    ['term.program.name', f => { f.terms[4].program.name = 'Other'; }],
    ['term.program.icon', f => { f.terms[4].program.icon = 'other.svg'; }],
    ['term.program.tint', f => { f.terms[4].program.tint = false; }],
    ['term.program.shell', f => { f.terms[4].program.shell = true; }],
    ['term.labels.task', f => { f.terms[1].labels.task = 't-other'; }],
    ['term.labels.pm', f => { f.terms[0].labels.pm = 'other-pm'; }],
    ['term.labels.helper.of', f => { f.terms[4].labels['helper.of'] = 't-other'; }],
    ['term.labels.helper', f => { f.terms[4].labels.helper = 'research-b'; }],
    ['live.address', f => { f.live[4].address = 't-sess-2'; }],
    ['live.status', f => { f.live[4].status = 'working'; }],
    ['live.tab', f => { f.live[4].tab = 'tab1'; }],
    ['live.seq', f => { f.live[4].seq = 99; }],
    ['live.title', f => { f.live[4].title = 'Renamed session'; }],
    ['live.app', f => { f.live[3].app = 'claude-code'; }],
    ['live.program.key', f => { f.live[4].program.key = 'claude'; }],
    ['live.program.name', f => { f.live[4].program.name = 'Claude'; }],
    ['live.program.icon', f => { f.live[4].program.icon = 'c.svg'; }],
    ['live.program.tint', f => { f.live[4].program.tint = true; }],
    ['live.program.shell', f => { f.live[4].program.shell = true; }],
    ['tab.id', f => { f.tabs[1].id = 'tab2-new'; }],
    ['tab.name', f => { f.tabs[1].name = 'Renamed tab'; }],
    ['tab.named', f => { f.tabs[1].named = false; }],
  ];
  for (const [label, mutate] of hostMutations) {
    const copy = makeFixture();
    mutate(copy);
    assert.notEqual(
      model.hostLiveSignature(copy.terms, copy.live, copy.tabs),
      baseHostSig,
      `hostLiveSignature must change when ${label} changes`,
    );
  }

  // (4) Full PmProject.render() Proxy audit + live helper label / pm.project / pm.counts.waiting invalidation!
  const nodes = new Map();
  const allTexts = rec => [...rec.texts, ...rec.kids.flatMap(allTexts)];
  const makeEl = (extra = {}) => {
    const rec = { id: '', texts: [], kids: [], clicks: null, hovers: [], ...extra };
    const proxy = new Proxy(() => proxy, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') { if (typeof args[0] === 'string') rec.texts.push(args[0]); else if (args[0]?.__rec) rec.kids.push(args[0].__rec); }
          else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) { if (typeof k === 'string') rec.texts.push(k); else if (k?.__rec) rec.kids.push(k.__rec); }
          }
          else if (key === 'content' && args[0]?.__rec) rec.kids.push(args[0].__rec);
          else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'on_hover') rec.hovers.push(args[0]);
          else if (key === 'when') { if (args[0]) args[1](proxy); }
          return proxy;
        };
      },
      apply: () => proxy,
    });
    rec.allTexts = () => allTexts(rec);
    return proxy;
  };
  const renderFix = makeFixture();
  let curTerms = renderFix.terms;
  let curLive = renderFix.live;
  let curSpaces = [{ id: 'sp1', tabs: renderFix.tabs }];
  const stubs = {
    View: class {}, ...model, ...stepsMod,
    div: () => makeEl(), h_flex: () => makeEl(), v_flex: () => makeEl(), svg: () => makeEl(), image: () => makeEl(),
    TextView: { markdown: (_id, md) => makeEl().child(String(md ?? '')), html: (_id, html) => makeEl().child(String(html ?? '')) },
    TextareaState: { new: () => ({ on() {}, value: () => '', content: () => ({ text: '', tokens: [] }), selected_range: () => ({ start: 0, end: 0 }), set_selected_range() {}, set_value() {}, set_auto_grow() {}, set_soft_wrap() {}, focus() {} }) },
    Textarea: { new: () => makeEl() }, InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, focus() {} }) }, Input: { new: () => makeEl() },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) }, Scrollbar: { new: () => makeEl() }, Popup: { new: (id, trigger) => makeEl().id(id).child(trigger) },
    theme: () => ({
      canvas: '#fafafa', surface: '#fff', raised: '#f4f4f6', chrome: '#f7f7f8', popover: '#fff',
      hover: '#ececef', border: '#e2e2e7', input: '#d4d4db', foreground: '#18181b', muted: '#52525b',
      dim: '#71717a', accent: '#2563eb', blocked: '#dc2626', solid: '#18181b', solid_foreground: '#fff',
      ansi2: '#16a34a', ansi3: '#d97706', working: '#16a34a', background: '#fff',
    }),
    home: () => '/Users/test', appHome: () => '/app',
    exec: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    execPython: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    readTextFile: async () => '', writeTextFile: async () => {}, watchFolder: () => new Promise(() => {}),
    layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run() {}, terminals: () => curTerms, agents: () => curLive, panes: () => [{ terminal: 't-pm' }], spaces: () => curSpaces,
    shared: () => ({ pm: 'pm-dudu' }), setShared() {}, props: () => null, openOverlay() {}, closeOverlay() {},
    appWindow: () => ({ platform: 'macos' }),
    renderThreadChangeView: () => makeEl(),
    buildProjectSearch: () => ({ groups: [], flat: [] }), stepSearchSelection: () => 0, stepSearchScope: () => 'all',
    stepSearchEscape: () => ({}), renderProjectSearchOverlay: () => makeEl(),
  };
  const prevStorage = globalThis.localStorage;
  const store = new Map();
  globalThis.localStorage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) };
  try {
    const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
    const cx = {
      phase: () => 'event', focus_handle: () => ({ focus() {} }), spawn: fn => fn(cx),
      timer: { after: () => ({ cancel() {} }) }, notify() {}, stop_propagation() {}, read_from_clipboard: () => '',
    };
    const view = Object.assign(Object.create(Mod.prototype), {
      state: { pms: [renderFix.pm], tasks: renderFix.tasks, task_numbers: { 't-main': 241, 't-blocked': 242 }, retired_parts: [], events: [], lang: 'zh' },
      events: renderFix.events, pending: [], seq: 0, pastes: [], error: '', logError: '',
      pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
      remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
      earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '/here', watching: {},
      thread: '', threadTask: null, detail: false, threadError: '', threadLog: null, threadLogKept: [],
      threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null, threadTab: 'log', sideTab: 'threads',
      librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: false, libraryProbed: true, libraryStale: false,
      libraryLoading: false, libraryAgain: false, libraryError: '', libraryClosed: new Set(), libraryQuery: '',
      libraryDropBusy: '', libraryDropError: '', memorySlug: '', memoryData: null, memoryRead: false, memoryStale: false,
      memoryLoading: false, memoryAgain: false, memoryError: '', memoryFoldOverrides: new Map(), memoryProjectOpen: true,
      memoryPersonalOpen: false, memoryCandidatesOpen: false, memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
      activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '', docShownBytes: model.DOC_INITIAL_BYTES,
      docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
      editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
      confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
      reattaching: '', reattachError: null, startingPm: '', startPmError: null,
      bringBackOpen: false, bringingBack: false, bringBackProgress: null,
      listShown: true, wide: true, measured: true, viewWidth: 1280, panelWant: null, panelDrag: null, gripLit: false,
      panelMounted: false, panelHideTimer: null, fadingKeys: null, fadeClearTimer: null,
      _timelineCache: null, _taskTreeCache: null, _mdLinkCache: null, _taskNumIndex: null, _projTasksCache: null, _blockKeySet: null,
      seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
      bell: null, flash: '', flashPara: '', unfolded: new Map(), newest: '', atWork: new Set(),
      scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
      libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
      mentionScroll: { scroll_to_item() {} }, mention: null, mentionDismissed: null, mentionConsumedKey: false, mentionPicking: false,
      repoFilesSlug: '', repoFilesRepo: '', repoFiles: [], repoFilesRead: false, repoFilesLoading: false, repoFilesAgain: false,
      repoFilesError: '', repoFilesTruncated: false, repoFilesAt: 0, pathCopiedAt: 0,
      quotes: [], quoteSeq: 0, hoveredMsg: '', hoverClipboard: '', selectionBar: null,
      hoveredPara: '', pendingHoverPara: '', paraHoverShowTimer: null, paraHoverHideTimer: null, paraHoverSeq: 0, paraCache: new Map(),
      hoverKey: 'agent:helper:t-main:t-h2',
      lastBlocks: [], lastTopOffset: 0, lastHeights: [], lastTall: 0,
      keyFocus: { focus() {} }, onStage: true, typing: '', mainKey: 'pm:pm-dudu', threadKey: '',
      outgoing: new Map(), files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
      input: stubs.TextareaState.new(), threadInput: stubs.TextareaState.new(), libraryInput: stubs.InputState.new(), memoryInput: stubs.InputState.new(),
      docFindInput: stubs.InputState.new(), docNameInput: stubs.InputState.new(), memDescInput: stubs.InputState.new(),
      docEditorInput: stubs.TextareaState.new(), refresh: () => {},
    });
    view.resetThreadSession();

    // Render with Proxy-tracked terms/live/tabs while hovering helper agent row so agentSubRow + agentHoverCard + sessionRow all run.
    const renderReads = new Set();
    curTerms = trackList(renderFix.terms, 'term', renderReads);
    curLive = trackList(renderFix.live, 'live', renderReads);
    curSpaces = [{ id: 'sp1', tabs: trackList(renderFix.tabs, 'tab', renderReads) }];
    nodes.clear();
    view.render(cx);
    // Exclude non-taskTree reads (`term.labels.pm.seat` is only read outside taskTree, if ever); verify every taskTree-rendered field is in hostLiveSignature!
    const missingInRender = [...renderReads].filter(p => !sigReads.has(p));
    assert.deepEqual(missingInRender, [], `PmProject.render() read host fields missing from hostLiveSignature: ${missingInRender.join(', ')}`);
    assert.ok(nodes.get('agent-row-helper:t-main:t-h2')?.allTexts().includes('research-a'), 'initial helper label suffix renders research-a');

    // Changing ONLY labels.helper on t-h2 must invalidate _taskTreeCache and immediately show the new suffix!
    const prevTree = view._taskTreeCache.tree;
    curTerms = renderFix.terms.map(t => (t.address === 't-h2' ? { ...t, labels: { ...t.labels, helper: 'research-b' } } : t));
    curLive = renderFix.live;
    curSpaces = [{ id: 'sp1', tabs: renderFix.tabs }];
    nodes.clear();
    view.render(cx);
    assert.notEqual(view._taskTreeCache.tree, prevTree, 'labels.helper update invalidates _taskTreeCache');
    assert.ok(nodes.get('agent-row-helper:t-main:t-h2')?.allTexts().includes('research-b'), 'helper row suffix updates immediately to research-b');
    assert.equal(nodes.get('agent-row-helper:t-main:t-h2')?.allTexts().includes('research-a'), false, 'stale helper suffix research-a is gone');

    // Changing ONLY term.context_tokens on t-h2 must invalidate _taskTreeCache and update the hover card context label!
    const prevTree2 = view._taskTreeCache.tree;
    curTerms = curTerms.map(t => (t.address === 't-h2' ? { ...t, context_tokens: 88000 } : t));
    nodes.clear();
    view.render(cx);
    assert.notEqual(view._taskTreeCache.tree, prevTree2, 'term.context_tokens update invalidates _taskTreeCache');
    assert.equal(view._taskTreeCache.tree.flatOpen.find(n => n.task === 't-main')?.agents?.active?.find(a => a.address === 't-h2')?.contextTokens, 88000);

    // Changing ONLY pm.counts.waiting (keeping tasks reference intact) must invalidate _timelineCache and update waiting count!
    const prevTl = view._timelineCache;
    view.state = { ...view.state, pms: [{ ...renderFix.pm, counts: { waiting: 4 } }] };
    nodes.clear();
    view.render(cx);
    assert.notEqual(view._timelineCache, prevTl, 'pm.counts.waiting update invalidates _timelineCache');
    assert.equal(view._timelineCache.waiting, 4, 'updated pm.counts.waiting reflected immediately');

    // Changing ONLY pm.project must invalidate _taskTreeCache!
    const prevTree3 = view._taskTreeCache.tree;
    view.state = { ...view.state, pms: [{ ...renderFix.pm, project: 'dudu-renamed', counts: { waiting: 4 } }] };
    nodes.clear();
    view.render(cx);
    assert.notEqual(view._taskTreeCache.tree, prevTree3, 'pm.project update invalidates _taskTreeCache');
  } finally {
    globalThis.localStorage = prevStorage;
  }
});

test('quote preview preserves task numbers (#233) across paragraph, whole-message, clipboard selection, and @mention quotes in zh & en', async () => {
  const fs = await import('node:fs');
  const stepsMod = await import('./steps.js');
  const rawMain = fs.readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const source = `${rawMain
    .replace(/^\s*import\s+[\s\S]*?from\s+['"][^'"]+['"];\s*$/gm, '')
    .replace(/export\s+default\s+class\s+/, 'class ')}\nreturn PmProject;`;

  // (1) Model unit checks: decorateThreadLinks + retiredParts + extractClipboardQuote with displayText
  const tasks = [{ id: 'dudu-233', pm: 'pm-dudu', title: '主任务', number: 233, status: 'in_progress' }];
  const retired = [{ id: 'dudu-190', pm: 'pm-dudu', title: '已归档子任务', number: 190, status: 'merged' }];
  const decoratedRetired = model.decorateThreadLinks('参考 [已归档子任务](thread:dudu-190)', tasks, null, { retiredParts: retired });
  assert.equal(decoratedRetired, '参考 [#190 已归档子任务](thread:dudu-190)', 'decorateThreadLinks resolves number from retiredParts even without taskNumbers');

  const rawMsg = '性能测试新消息 #5：已完成第一轮排查，详见 [主任务](thread:dudu-233)。';
  const dispMsg = model.decorateThreadLinks(rawMsg, tasks, { 'dudu-233': 233 });
  assert.equal(dispMsg, '性能测试新消息 #5：已完成第一轮排查，详见 [#233 主任务](thread:dudu-233)。');
  const wholePick = model.extractClipboardQuote('', rawMsg, { baseline: '', displayText: dispMsg });
  assert.equal(wholePick.exact, false);
  assert.equal(wholePick.text, '性能测试新消息 #5：已完成第一轮排查，详见 #233 主任务。');
  const selPick = model.extractClipboardQuote('详见 #233 主任务', rawMsg, { baseline: '', displayText: dispMsg });
  assert.equal(selPick.exact, true, 'clipboard selection copied from rendered #233 link matches as exact selection');
  assert.equal(selPick.text, '详见 #233 主任务');
  const rawSelPick = model.extractClipboardQuote('已完成第一轮排查，详见 主任务', rawMsg, { baseline: '', displayText: dispMsg });
  assert.equal(rawSelPick.exact, true, 'clipboard selection copied from undecorated/folded text still matches');
  // Already-numbered link must never double up to "#233 #233"
  const alreadyNumRaw = '已含编号：[#233 主任务](thread:dudu-233)。';
  const alreadyNumDisp = model.decorateThreadLinks(alreadyNumRaw, tasks, { 'dudu-233': 233 });
  assert.equal(model.extractClipboardQuote('', alreadyNumRaw, { baseline: '', displayText: alreadyNumDisp }).text, '已含编号：#233 主任务。');

  // (2) End-to-end PmProject test in BOTH Chinese (zh) and English (en)
  const nodes = new Map();
  const allTexts = rec => [...rec.texts, ...rec.kids.flatMap(allTexts)];
  const makeEl = (extra = {}) => {
    const rec = { id: '', texts: [], kids: [], clicks: null, hovers: [], ...extra };
    const proxy = new Proxy(() => proxy, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        return (...args) => {
          if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
          else if (key === 'child') { if (typeof args[0] === 'string') rec.texts.push(args[0]); else if (args[0]?.__rec) rec.kids.push(args[0].__rec); }
          else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) { if (typeof k === 'string') rec.texts.push(k); else if (k?.__rec) rec.kids.push(k.__rec); }
          }
          else if (key === 'content' && args[0]?.__rec) rec.kids.push(args[0].__rec);
          else if (key === 'on_click') rec.clicks = args[0];
          else if (key === 'on_hover') rec.hovers.push(args[0]);
          else if (key === 'when') { if (args[0]) args[1](proxy); }
          return proxy;
        };
      },
      apply: () => proxy,
    });
    rec.allTexts = () => allTexts(rec);
    return proxy;
  };
  let clipText = '';
  const stubs = {
    View: class {}, ...model, ...stepsMod,
    div: () => makeEl(), h_flex: () => makeEl(), v_flex: () => makeEl(), svg: () => makeEl(), image: () => makeEl(),
    TextView: { markdown: (_id, md) => makeEl().child(String(md ?? '')), html: (_id, html) => makeEl().child(String(html ?? '')) },
    TextareaState: { new: () => ({ on() {}, value: () => '', content: () => ({ text: '', tokens: [] }), selected_range: () => ({ start: 0, end: 0 }), set_selected_range() {}, set_value() {}, set_auto_grow() {}, set_soft_wrap() {}, focus() {} }) },
    Textarea: { new: () => makeEl() }, InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, focus() {} }) }, Input: { new: () => makeEl() },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) }, Scrollbar: { new: () => makeEl() }, Popup: { new: (id, trigger) => makeEl().id(id).child(trigger) },
    theme: () => ({
      canvas: '#fafafa', surface: '#fff', raised: '#f4f4f6', chrome: '#f7f7f8', popover: '#fff',
      hover: '#ececef', border: '#e2e2e7', input: '#d4d4db', foreground: '#18181b', muted: '#52525b',
      dim: '#71717a', accent: '#2563eb', blocked: '#dc2626', solid: '#18181b', solid_foreground: '#fff',
      ansi2: '#16a34a', ansi3: '#d97706', working: '#16a34a', background: '#fff',
    }),
    home: () => '/Users/test', appHome: () => '/app',
    exec: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    execPython: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    readTextFile: async () => '', writeTextFile: async () => {}, watchFolder: () => new Promise(() => {}),
    layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run() {}, terminals: () => [{ address: 'tpm', state: 'live', status: 'idle', labels: { pm: 'dudu' } }],
    agents: () => [], panes: () => [{ terminal: 'tpm' }], spaces: () => [],
    shared: () => ({ pm: 'pm-dudu' }), setShared() {}, props: () => null, openOverlay() {}, closeOverlay() {},
    appWindow: () => ({ platform: 'macos' }),
    renderThreadChangeView: () => makeEl(),
    buildProjectSearch: () => ({ groups: [], flat: [] }), stepSearchSelection: () => 0, stepSearchScope: () => 'all',
    stepSearchEscape: () => ({}), renderProjectSearchOverlay: () => makeEl(),
  };
  const prevStorage = globalThis.localStorage;
  const store = new Map();
  globalThis.localStorage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) };
  try {
    const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
    const cx = {
      phase: () => 'event', focus_handle: () => ({ focus() {} }), spawn: fn => fn(cx),
      timer: { after: () => ({ cancel() {} }) }, notify() {}, stop_propagation() {}, read_from_clipboard: () => clipText,
    };
    const today = (() => { const d = new Date(), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; })();
    const at = s => `${today} ${s}`;
    const pmKey = `pm:${at('11:10:00')}:`;
    const userKey = `user:${at('11:11:00')}:`;
    const pmRaw = [
      '性能测试新消息 #5：已完成第一轮排查，详见 [主任务](thread:dudu-233)。',
      '',
      '第二段：已同步检查 [缓存修复](thread:dudu-241) 与 [已归档子任务](thread:dudu-190)。',
    ].join('\n');
    const userRaw = '帮我跟进 [@主任务](thread:dudu-233) 的进度';
    const rawParas = model.splitMarkdownParagraphs(pmRaw);
    const pmLocal = { name: 'pm-dudu', project: 'dudu', repo: '/work/dudu', pane: 'hc:tpm', runtime: 'hc', status: 'live' };

    for (const lang of ['zh', 'en']) {
      clipText = '';
      const view = Object.assign(Object.create(Mod.prototype), {
        state: {
          pms: [pmLocal],
          tasks: [
            { id: 'dudu-233', pm: 'pm-dudu', title: '主任务', number: 233, status: 'in_progress', updated: at('11:09:00') },
            { id: 'dudu-241', pm: 'pm-dudu', title: '缓存修复', number: 241, status: 'in_progress', updated: at('11:09:30') },
          ],
          retired_parts: [{ id: 'dudu-190', pm: 'pm-dudu', title: '已归档子任务', number: 190, status: 'merged', updated: at('10:00:00') }],
          task_numbers: { 'dudu-233': 233, 'dudu-241': 241 },
          events: [], lang,
        },
        events: [
          { at: at('11:10:00'), type: 'pm', text: pmRaw },
          { at: at('11:11:00'), type: 'user', text: userRaw },
        ],
        pending: [], seq: 0, pastes: [], error: '', logError: '',
        pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '', remoteHome: '',
        remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '', logState: null,
        earlierLoading: false, earlierError: '', earlierAnchor: null, ledgerHome: '/here', watching: {},
        thread: '', threadTask: null, detail: false, threadError: '', threadLog: null, threadLogKept: [],
        threadEarlierLoading: false, threadEarlierError: '', threadAnchor: null, threadTab: 'log', sideTab: 'threads',
        librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: false, libraryProbed: true, libraryStale: false,
        libraryLoading: false, libraryAgain: false, libraryError: '', libraryClosed: new Set(), libraryQuery: '',
        libraryDropBusy: '', libraryDropError: '', memorySlug: '', memoryData: null, memoryRead: false, memoryStale: false,
        memoryLoading: false, memoryAgain: false, memoryError: '', memoryFoldOverrides: new Map(), memoryProjectOpen: true,
        memoryPersonalOpen: false, memoryCandidatesOpen: false, memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
        activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '', docShownBytes: model.DOC_INITIAL_BYTES,
        docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
        editingDoc: null, retopicOpen: false, retopicSaving: false, retopicError: '',
        confirmDeleteKey: '', deleteBusy: '', deleteError: '', deletedBanner: null, historyView: null,
        reattaching: '', reattachError: null, startingPm: '', startPmError: null,
        bringBackOpen: false, bringingBack: false, bringBackProgress: null,
        listShown: true, wide: true, measured: true, viewWidth: 1280, panelWant: null, panelDrag: null, gripLit: false,
        panelMounted: false, panelHideTimer: null, fadingKeys: null, fadeClearTimer: null,
        _timelineCache: null, _taskTreeCache: null, _mdLinkCache: null, _taskNumIndex: null, _projTasksCache: null, _blockKeySet: null,
        seen: null, count: 0, settle: 0, away: false, rise: 0, heights: new Map(), tall: 700, high: 700,
        bell: null, flash: '', flashPara: '', unfolded: new Map(), newest: '', atWork: new Set(),
        scroll: { scroll_to_item() {} }, threadScroll: { scroll_to_item() {} }, sessionScroll: { scroll_to_item() {} },
        libraryScroll: { scroll_to_item() {} }, memoryScroll: { scroll_to_item() {} }, docScroll: { scroll_to_item() {} }, historyScroll: { scroll_to_item() {} },
        mentionScroll: { scroll_to_item() {} }, mention: null, mentionDismissed: null, mentionConsumedKey: false, mentionPicking: false,
        repoFilesSlug: '', repoFilesRepo: '', repoFiles: [], repoFilesRead: false, repoFilesLoading: false, repoFilesAgain: false,
        repoFilesError: '', repoFilesTruncated: false, repoFilesAt: 0, pathCopiedAt: 0,
        quotes: [], quoteSeq: 0, hoveredMsg: pmKey, hoverClipboard: '', selectionBar: null,
        hoveredPara: `${pmKey}#p0`, pendingHoverPara: '', paraHoverShowTimer: null, paraHoverHideTimer: null, paraHoverSeq: 0, paraCache: new Map(),
        lastBlocks: [], lastTopOffset: 0, lastHeights: [], lastTall: 0,
        keyFocus: { focus() {} }, onStage: true, typing: '', mainKey: 'pm:pm-dudu', threadKey: '',
        outgoing: new Map(), files: [], threadFiles: [], attachError: null, pasted: { stamp: '', n: 0 }, answering: null,
        input: stubs.TextareaState.new(), threadInput: stubs.TextareaState.new(), libraryInput: stubs.InputState.new(), memoryInput: stubs.InputState.new(),
        docFindInput: stubs.InputState.new(), docNameInput: stubs.InputState.new(), memDescInput: stubs.InputState.new(),
        docEditorInput: stubs.TextareaState.new(), refresh: () => {},
      });
      view.resetThreadSession();

      // A. Paragraph quote on p0 (contains literal #5 + decorated #233)
      nodes.clear();
      view.render(cx);
      nodes.get(`para-quote-btn-${pmKey}-0`).clicks({ stop_propagation() {} }, cx);
      assert.equal(view.quotes.length, 1, `[${lang}] paragraph quote added`);
      assert.equal(view.quotes[0].text, '性能测试新消息 #5：已完成第一轮排查，详见 #233 主任务。', `[${lang}] paragraph quote keeps #5 and #233`);
      assert.equal(view.quotes[0].range.start, rawParas[0].start, `[${lang}] canonical raw start offset preserved`);
      assert.equal(view.quotes[0].range.end, rawParas[0].end, `[${lang}] canonical raw end offset preserved`);

      // B. Whole-message quote on PM message (contains #233, #241, and retired #190)
      nodes.get(`quote-btn-${pmKey}`).clicks({ stop_propagation() {} }, cx);
      assert.equal(view.quotes.length, 2, `[${lang}] whole-message quote added`);
      assert.ok(view.quotes[1].text.includes('#233 主任务'), `[${lang}] whole-message quote keeps #233`);
      assert.ok(view.quotes[1].text.includes('#241 缓存修复'), `[${lang}] whole-message quote keeps #241`);
      assert.ok(view.quotes[1].text.includes('#190 已归档子任务'), `[${lang}] whole-message quote keeps retired #190`);

      // C. Clipboard selection quote with rendered "#233 主任务"
      clipText = '详见 #233 主任务';
      nodes.get(`quote-btn-${pmKey}`).clicks({ stop_propagation() {} }, cx);
      assert.equal(view.quotes.length, 3, `[${lang}] selection quote added`);
      assert.equal(view.quotes[2].scope, 'selection', `[${lang}] recognized as exact selection`);
      assert.equal(view.quotes[2].text, '详见 #233 主任务', `[${lang}] selection quote keeps #233`);
      assert.equal(view.quotes[2].range?.paragraph, 0, `[${lang}] selection range maps to canonical p0`);

      // D. User message with thread @mention preserves #233
      clipText = '';
      view.hoveredMsg = userKey;
      view.hoverClipboard = '';
      nodes.clear();
      view.render(cx);
      nodes.get(`quote-btn-${userKey}`).clicks({ stop_propagation() {} }, cx);
      assert.equal(view.quotes.length, 4, `[${lang}] user @mention message quote added`);
      assert.equal(view.quotes[3].text, '帮我跟进 #233 @主任务 的进度', `[${lang}] user @mention quote keeps #233`);

      // E. Composer quote bar renders #233 in all 4 quote preview lines
      nodes.clear();
      view.render(cx);
      for (let i = 0; i < 4; i++) {
        const previewTexts = nodes.get(`say-quote-${i}`)?.allTexts().join(' ') || '';
        assert.ok(previewTexts.includes('#233'), `[${lang}] composer quote bar row ${i} renders #233: got "${previewTexts}"`);
      }
      assert.equal(
        nodes.get('say-quote-scope-0')?.allTexts().join(''),
        lang === 'zh' ? '第 1 段' : '¶1',
        `[${lang}] scope badge localized`,
      );

      // F. Sent message wire round-trip & sent bubble quote cards render #233 in both zh & en
      const wire = model.formatQuotedMessage(view.quotes, lang === 'zh' ? '收到' : 'Got it');
      assert.ok(wire.includes('#233 主任务'), `[${lang}] wire message keeps #233`);
      const sentAt = at('11:12:00');
      const sentKey = `user:${sentAt}:`;
      view.quotes = [];
      view.events = [...view.events, { at: sentAt, type: 'user', text: wire }];
      nodes.clear();
      view.render(cx);
      for (let i = 0; i < 4; i++) {
        const cardTexts = nodes.get(`bubble-quote-${sentKey}-${i}`)?.allTexts().join(' ') || '';
        assert.ok(cardTexts.includes('#233'), `[${lang}] sent bubble quote card ${i} renders #233: got "${cardTexts}"`);
      }
    }
  } finally {
    globalThis.localStorage = prevStorage;
  }
});

// Real ledger shapes (2026-11-23, task #259 dudu-dudu-pm-py-p2-4b): `pm.py approve --via helper` starts a helper the
// PM owns (`pm.helpers`, `helper.of` = the PM) and links it to the task only by `for_task` in the ledger and the
// `helper.task` terminal label. Threads used to list it as a loose session instead of under its task.
test('Threads: a PM-owned merge helper hangs under the task it serves, says Merging, and folds when done', () => {
  const { threadAgents, taskTree, pmHelperTask, helperPurpose, helperTaskOf, hostLiveSignature, word } = model;
  const task = {
    id: 'dudu-dudu-pm-py-p2-4b', title: 'pm.py 重构第二轮 4b：Helpers 服务', project: 'dudu', status: 'in_progress',
    pane: 'hc:t1f9', number: 259, pm: 'pm-dudu', engine: { profile: 'neon-medium', kind: 'agy', model: 'gemini-4-neon-medium' },
  };
  const landPrompt = 'PM approved merging task dudu-dudu-pm-py-p2-4b (dev/pmlib-p2-4b-helpers -> main). Execute the following: '
    + '- PM note: 按用户决定不逐刀审查；worker 全套检查通过 1. Run merge & checks: `python3 /Users/dev/.claude/skills …';
  const running = {
    name: 'land-dudu-dudu-pm-py-p2-4b', terminal: 't1fm', pane: 'hc:t1fm', parent: 't182', owner: 'pm-dudu', status: 'running',
    profile: 'neon-medium', kind: 'agy', model: 'gemini-4-neon-medium', effort: '',
    result: '/Users/dev/.dudu/projects/dudu/helpers/pm/land-dudu-dudu-pm-py-p2-4b.md', summary: '', prompt: landPrompt,
    started: '2026-11-23 05:59:35', ended: '', offline: false, live_state: 'working',
  };
  const otherDone = {
    name: 'render-error-logs', terminal: 't1aa', status: 'done', owner: 'pm-dudu', kind: 'agy', prompt: 'look at render errors',
    summary: 'x', ended: '2026-11-22 10:00',
  };
  const helperTerm = {
    address: 't1fm', state: 'live', status: 'working', cwd: '/Users/dev/project/repos/dudu', program: { key: 'agy', name: 'Antigravity', icon: 'agy.svg' },
    labels: { helper: 'land-dudu-dudu-pm-py-p2-4b', 'helper.mode': 'exec', 'helper.of': 'pm-dudu', 'helper.project': 'dudu', 'helper.task': 'dudu-dudu-pm-py-p2-4b' },
  };
  const workerTerm = { address: 't1f9', state: 'live', status: 'idle', cwd: '/Users/dev/.herdr/worktrees/dudu/dev-pmlib-p2-4b-helpers', labels: { task: task.id } };
  const terms = [workerTerm, helperTerm];

  assert.equal(helperTaskOf(helperTerm), task.id);
  assert.equal(helperTaskOf({ labels: { 'helper.of': 'dudu-lib' } }), 'dudu-lib');
  assert.equal(helperPurpose(running), 'land');
  assert.equal(helperPurpose({ name: 'triage-dudu-x' }), 'triage');
  assert.equal(helperPurpose(otherDone), '');
  assert.equal(pmHelperTask(running, terms), task.id, 'label on its live terminal');
  assert.equal(pmHelperTask({ ...running, for_task: 'dudu-other' }, terms), 'dudu-other', 'ledger for_task wins');
  assert.equal(pmHelperTask(otherDone, terms), '', 'a PM helper not serving a task stays off');
  // Terminal gone (ended): the pm.py-written prompt names the task; the zh/en triage prompts too.
  assert.equal(pmHelperTask({ ...running, status: 'done' }, []), task.id);
  assert.equal(pmHelperTask({ name: 'triage-dudu-x', prompt: 'Triage stuck worker terminal hc:t9 for task dudu-x (标题).\n' }, []), 'dudu-x');
  assert.equal(pmHelperTask({ name: 'triage-dudu-x', prompt: '排查卡住的 worker 终端 hc:t9（任务 dudu-x：标题）。' }, []), 'dudu-x');
  assert.equal(pmHelperTask({ name: 'notes', prompt: landPrompt }, []), '', 'no land-/triage- name, no prose guess');
  // A reused address on another helper does not lend its label.
  assert.equal(pmHelperTask({ ...running, status: 'done', prompt: '' },
    [{ address: 't1fm', state: 'live', labels: { helper: 'someone-else', 'helper.task': 'dudu-zzz' } }]), '');

  // Running: hangs under the task after its worker, says what it does, opens its small window (agy: terminal).
  for (const lang of ['zh', 'en']) {
    const info = threadAgents(task, { terms, live: [], lang, pmHelpers: [otherDone, running] });
    assert.deepEqual(info.active.map(a => a.role), ['worker', 'helper']);
    const h = info.active[1];
    assert.equal(h.name, 'land-dudu-dudu-pm-py-p2-4b');
    assert.equal(h.nameSuffix, lang === 'zh' ? '合并中' : 'Merging');
    assert.equal(h.purpose, 'land');
    assert.equal(h.status, 'working');
    assert.equal(h.address, 't1fm');
    assert.equal(h.defaultMode, 'terminal');
    assert.equal(h.canSwitchMode, true);
    assert.equal(h.model, info.active[0].model, 'same model chip as a worker on that profile');
    assert.equal(info.ended.length, 0, 'the unrelated PM helper is not this task’s');
    assert.equal(word(lang, `agentState_${h.status}`), lang === 'zh' ? '在做' : 'working');
  }
  // Without the ledger record (state not refreshed yet) the live label alone still hangs it there.
  const liveOnly = threadAgents(task, { terms, live: [], lang: 'zh' });
  assert.deepEqual(liveOnly.active.map(a => [a.role, a.nameSuffix, a.status]), [['worker', '', 'idle'], ['helper', '合并中', 'working']]);
  // Idle helper (waiting on a check) says idle.
  const idle = threadAgents(task, { terms: [workerTerm, { ...helperTerm, status: 'idle' }], live: [], lang: 'en', pmHelpers: [running] });
  assert.equal(idle.active[1].status, 'idle');
  // Done (terminal gone): folds into the ended row with its conclusion; label turns to the noun.
  const done = { ...running, status: 'done', live_state: undefined, ended: '2026-11-23 06:05',
    summary: 'dudu-dudu-pm-py-p2-4b 已合并至 main（合并提交 71900a6），7 项检查全部通过；已自动回收终端 hc:t1f9、worktree 及分支。' };
  const after = threadAgents(task, { terms: [workerTerm], live: [], lang: 'zh', pmHelpers: [done] });
  assert.deepEqual(after.active.map(a => a.role), ['worker']);
  assert.equal(after.ended.length, 1);
  assert.equal(after.ended[0].nameSuffix, '合并');
  assert.equal(after.ended[0].status, 'done');
  assert.match(after.ended[0].summary, /已合并至 main/);
  assert.equal(after.ended[0].defaultMode, 'chat', 'ended helper opens on its conclusion');

  // Done with custom name and no terminal: `for_task` from `pm.py state` still attaches it without name/prompt guessing.
  const customDone = {
    name: 'verify-build', terminal: 't1zz', status: 'done', owner: 'pm-dudu', kind: 'agy',
    prompt: 'run checks after rebase', summary: 'all checks passed', ended: '2026-11-23 06:10',
    for_task: task.id,
  };
  assert.equal(pmHelperTask(customDone, []), task.id);
  const afterCustom = threadAgents(task, { terms: [workerTerm], live: [], lang: 'en', pmHelpers: [customDone] });
  assert.equal(afterCustom.ended.length, 1);
  assert.equal(afterCustom.ended[0].name, 'verify-build');
  assert.equal(afterCustom.ended[0].nameSuffix, 'verify-build');
  assert.equal(afterCustom.ended[0].summary, 'all checks passed');

  // taskTree: the helper is under the task's row, not a loose session row.
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/Users/dev/project/repos/dudu', pane: 'hc:t182', helpers: [otherDone, running] };
  const live = [
    { address: 't1fm', status: 'working', tab: 'tab-h', seq: 9, program: { key: 'agy', name: 'Antigravity', icon: 'agy.svg' } },
    { address: 't1f9', status: 'idle', tab: 'tab-w', seq: 8 },
  ];
  const tree = taskTree(pm, [task], [], { terms, live, lang: 'zh' });
  assert.equal(tree.sessions.length, 0, 'the merge helper is not listed as a separate session');
  const node = tree.groups.flatMap(g => g.nodes).find(n => n.task === task.id);
  assert.deepEqual(node.agents.active.map(a => [a.role, a.nameSuffix]), [['worker', ''], ['helper', '合并中']]);
  // Live PM helper linked only by `for_task` (terminal has no `helper.task` label) is also excluded from loose sessions.
  const noLabelTerm = { ...helperTerm, labels: { helper: 'land-dudu-dudu-pm-py-p2-4b', 'helper.of': 'pm-dudu' } };
  const pmWithForTask = { ...pm, helpers: [otherDone, { ...running, for_task: task.id }] };
  const treeForTask = taskTree(pmWithForTask, [task], [], { terms: [workerTerm, noLabelTerm], live, lang: 'zh' });
  assert.equal(treeForTask.sessions.length, 0, 'for_task excludes the live helper from loose sessions');
  const nodeForTask = treeForTask.groups.flatMap(g => g.nodes).find(n => n.task === task.id);
  assert.deepEqual(nodeForTask.agents.active.map(a => [a.role, a.nameSuffix]), [['worker', ''], ['helper', '合并中']]);
  // Reused terminal address after hc restart: an ended or stale for_task helper must not hide a loose session or
  // a different general PM helper now running on the same address.
  const reusedLooseTerm = {
    address: 't1fm', state: 'live', status: 'working', cwd: '/Users/dev/project/repos/dudu',
    program: { key: 'claude', name: 'Claude', icon: 'claude.svg' }, labels: {},
  };
  const pmEndedReuse = { ...pm, helpers: [{ ...done, for_task: task.id }] };
  const treeEndedReuse = taskTree(pmEndedReuse, [task], [], { terms: [workerTerm, reusedLooseTerm], live, lang: 'zh' });
  assert.deepEqual(treeEndedReuse.sessions.map(s => s.address), ['t1fm'], 'ended helper must not hide reused loose session');
  const pmStaleRunningReuse = { ...pm, helpers: [{ ...running, for_task: task.id }] };
  const treeStaleReuse = taskTree(pmStaleRunningReuse, [task], [], { terms: [workerTerm, reusedLooseTerm], live, lang: 'zh' });
  assert.deepEqual(treeStaleReuse.sessions.map(s => s.address), ['t1fm'], 'mismatched helper label must not hide reused loose session');
  const generalHelperTerm = {
    address: 't1fm', state: 'live', status: 'working', cwd: '/Users/dev/project/repos/dudu',
    program: { key: 'agy', name: 'Antigravity', icon: 'agy.svg' },
    labels: { helper: 'pm-general', 'helper.of': 'pm-dudu' },
  };
  const pmGeneralReuse = {
    ...pm,
    helpers: [
      { ...done, for_task: task.id },
      { name: 'pm-general', terminal: 't1fm', status: 'running', owner: 'pm-dudu', kind: 'agy', offline: false },
    ],
  };
  const treeGeneralReuse = taskTree(pmGeneralReuse, [task], [], { terms: [workerTerm, generalHelperTerm], live, lang: 'zh' });
  assert.deepEqual(treeGeneralReuse.sessions.map(s => s.address), ['t1fm'], 'reused address for general PM helper stays visible');
  // Render cache sees the label.
  assert.notEqual(hostLiveSignature(terms), hostLiveSignature([workerTerm, { ...helperTerm, labels: { ...helperTerm.labels, 'helper.task': '' } }]));
});

test('PM receipt confirmation: prevents duplicate resend before conversation.jsonl writes (#234)', () => {
  const t0 = model.eventTime('2026-11-23 20:00:00');
  const base = { said: '修一下', words: '修一下', to: '', files: [], draftKey: 'pm:pm-dudu' };

  // 1. Delivered bubble confirmed by receipt before conversation.jsonl has any user event.
  const delivered = { ...base, id: 1, text: '修一下', sentAt: t0, queued: false, deliveredAt: t0 + 200, sentTo: 't182', sentSession: 'fg:100', idleSince: t0 + 200 };
  const receipt = { at: '2026-11-23 20:00:01', at_ms: t0 + 500, text: '修一下', digest: 'abc' };
  const r1 = model.reconcilePendingSends([delivered], [], {
    now: t0 + 15000, pmAddress: 't182', pmSession: 'fg:100', logReady: true, receipts: [receipt], lang: 'zh',
  });
  assert.equal(r1.failed.length, 0, 'receipt prevents confirmation timeout');
  assert.equal(r1.requeued.length, 0);
  assert.equal(r1.confirmed.length, 1);
  assert.equal(r1.pending[0].received, true);
  assert.equal(r1.pending[0].failed, '');
  assert.equal(r1.needsFollowup, false);

  // 2. Verifying resend after timeout: fresh log still empty, but receipt exists -> confirm, never requeue!
  const verifying = { ...base, id: 2, text: '修一下', sentAt: t0, verifying: true, verifySince: t0 + 20000 };
  const r2 = model.reconcilePendingSends([verifying], [], {
    now: t0 + 21000, pmAddress: 't182', logReady: true, logFreshFrom: t0 + 20500, receipts: [receipt], lang: 'zh',
  });
  assert.equal(r2.requeued.length, 0, 'verifying resend with receipt must never requeue');
  assert.equal(r2.confirmed.length, 1);
  assert.equal(r2.pending[0].received, true);

  // 3. PM swapped before conversation.jsonl flushed, but outgoing PM wrote receipt -> confirm, do NOT requeue to new PM!
  const swapped = { ...base, id: 3, text: '修一下', sentAt: t0, deliveredAt: t0 + 200, sentTo: 't182', sentSession: 'fg:100' };
  const r3 = model.reconcilePendingSends([swapped], [], {
    now: t0 + 5000, pmAddress: 't190', pmSession: 'fg:200', logReady: true, receipts: [receipt], lang: 'zh',
  });
  assert.equal(r3.requeued.length, 0, 'receipt prevents duplicate re-delivery across PM swap');
  assert.equal(r3.confirmed.length, 1);
  assert.equal(r3.pending[0].received, true);

  // 4. Stale receipt from before sentAt does NOT confirm a newly sent message with the same text.
  const oldReceipt = { at: '2026-11-23 19:50:00', at_ms: t0 - 600000, text: '修一下', digest: 'old' };
  const r4 = model.reconcilePendingSends([verifying], [], {
    now: t0 + 21000, pmAddress: 't182', logReady: true, logFreshFrom: t0 + 20500, receipts: [oldReceipt], lang: 'zh',
  });
  assert.equal(r4.confirmed.length, 0);
  assert.equal(r4.requeued.length, 1, 'stale receipt before sentAt does not block legitimate resend');

  // 5. Unsent queued bubble is NOT swallowed by a receipt; one receipt only confirms one bubble.
  const unsentQueued = { ...base, id: 4, text: '修一下', sentAt: t0 + 100, queued: true };
  const r5 = model.reconcilePendingSends([unsentQueued], [], {
    now: t0 + 1000, pmAddress: 't182', logReady: true, receipts: [receipt], lang: 'zh',
  });
  assert.equal(r5.confirmed.length, 0, 'unsent queued bubble must not be swallowed by receipt');
  assert.equal(r5.pending[0].queued, true);

  const dupA = { ...base, id: 5, text: '修一下', sentAt: t0, deliveredAt: t0 + 100, sentTo: 't182' };
  const dupB = { ...base, id: 6, text: '修一下', sentAt: t0 + 100, deliveredAt: t0 + 200, sentTo: 't182' };
  const r6 = model.reconcilePendingSends([dupA, dupB], [], {
    now: t0 + 1000, pmAddress: 't182', logReady: true, receipts: [receipt], lang: 'zh',
  });
  assert.equal(r6.confirmed.length, 1, 'a single receipt confirms at most one pending bubble');
  assert.equal(r6.pending[0].received, true);
  assert.equal(Boolean(r6.pending[1].received), false);

  // 6. Image/attachment receipt matching (`[Image #1]` vs file path) and truncated long receipt matching.
  const withImg = { id: 7, text: model.messageText('看图', ['/tmp/a.png']), sentAt: t0, deliveredAt: t0 + 100, files: ['/tmp/a.png'] };
  const imgReceipt = { at: '2026-11-23 20:00:01', at_ms: t0 + 300, text: '[Image #1] 看图' };
  assert.ok(model.findReceiptMatch(withImg, [imgReceipt]), 'image-mark receipt matches attachment bubble');

  const longWords = '😀'.repeat(4500);
  const longReceipt = { at: '2026-11-23 20:00:01', at_ms: t0 + 300, text: '😀'.repeat(4000), len: 4500, truncated: true };
  assert.ok(model.findReceiptMatch({ id: 8, text: longWords, sentAt: t0 }, [longReceipt]),
    'truncated emoji receipt matches by Unicode code-point length, not UTF-16 length');
  assert.equal(model.INTERNAL_PROJECT_FILES.has('receipts.json'), true, 'receipts.json is an internal project file');
  assert.equal(model.INTERNAL_PROJECT_FILES.has('agy-transcript.json'), true, 'agy-transcript.json is an internal project file');

  // 7. Non-timeout failed bubble (`hc send` failed/offline) must NEVER be swallowed by a receipt.
  const failedSend = { ...base, id: 9, text: '修一下', sentAt: t0, failed: 'hc send: offline', timedOut: false };
  const r7 = model.reconcilePendingSends([failedSend], [], {
    now: t0 + 5000, pmAddress: 't182', logReady: true, receipts: [receipt], lang: 'zh',
  });
  assert.equal(r7.confirmed.length, 0, 'non-timeout send failure must not be confirmed by receipt');
  assert.equal(r7.pending[0].failed, 'hc send: offline');

  // 8. Settled receipts deducted: same text sent twice — 1st settles against evFirst, 2nd is verifying.
  //    The 1st message's receipt is deducted by evFirst, so the 2nd message is NOT falsely confirmed.
  const evFirst = { at: '2026-11-23 20:00:01', type: 'user', text: '继续' };
  const recFirst = { at: '2026-11-23 20:00:01', at_ms: t0 + 1500, text: '继续', digest: 'c1' };
  assert.deepEqual([...model.settledReceiptIndices([recFirst], [evFirst])], [0], 'logged event deducts its matching receipt');
  const firstDelivered = { ...base, id: 100, text: '继续', sentAt: t0 + 1000, deliveredAt: t0 + 1100, sentTo: 't182' };
  const secondVerifying = { ...base, id: 10, text: '继续', sentAt: t0 + 1200, verifying: true, verifySince: t0 + 15000 };
  const r8 = model.reconcilePendingSends([firstDelivered, secondVerifying], [evFirst], {
    now: t0 + 16000, pmAddress: 't182', logReady: true, logFreshFrom: t0 + 15500, receipts: [recFirst], lang: 'zh',
  });
  assert.equal(r8.settled.length, 1, 'first message settles against its logged event');
  assert.equal(r8.confirmed.length, 0, 'receipt already settled in events must be deducted');
  assert.equal(r8.requeued.length, 1, 'second duplicate message resends when only the first had a receipt');

  // 9. Strict at_ms window: rapid repeat within 3s ("好" at t0, then "好" at t0+1000ms) must NOT match
  //    the earlier message's receipt (at_ms = t0+200ms < sentAt = t0+1000ms).
  const recEarly = { at: '2026-11-23 20:00:00', at_ms: t0 + 200, text: '好', digest: 'ok1' };
  const rapidSecond = { ...base, id: 11, text: '好', sentAt: t0 + 1000, deliveredAt: t0 + 1050, sentTo: 't182', sentSession: 'fg:100' };
  const r9 = model.reconcilePendingSends([rapidSecond], [], {
    now: t0 + 1500, pmAddress: 't190', pmSession: 'fg:200', logReady: true, receipts: [recEarly], lang: 'zh',
  });
  assert.equal(r9.confirmed.length, 0, 'receipt with at_ms < sentAt must not swallow a rapid follow-up');
  assert.equal(r9.requeued.length, 1, 'rapid follow-up requeues on swap when its own receipt is absent');

  // 10. Existing `received` bubble reserves its receipt AND uses strict window in settlePending so an
  //     earlier identical event (e.g. 30s ago) does NOT prematurely settle and drop the unlogged bubble.
  const earlierEv = { at: '2026-11-23 19:59:30', type: 'user', text: '修一下' };
  const receivedBubble = r1.pending[0];
  const r10 = model.reconcilePendingSends([receivedBubble], [earlierEv], {
    now: t0 + 20000, pmAddress: 't182', logReady: true, receipts: [receipt], lang: 'zh',
  });
  assert.equal(r10.settled.length, 0, 'older identical event (30s ago) must not prematurely settle a receipt-confirmed bubble');
  assert.equal(r10.pending.length, 1);

  // 11. Timeline rendering, pendingSignature, storage, and eventual settlement when log arrives.
  const tlItem = model.timeline([], [], { pending: [receivedBubble] }).find(i => i.key === 'pending:1');
  assert.equal(tlItem.pending, false);
  assert.equal(tlItem.failed, '');
  assert.equal(tlItem.received, true);
  assert.notEqual(model.pendingSignature([delivered]), model.pendingSignature([receivedBubble]));
  assert.deepEqual(model.keepQueuedSends({}, 'pm-dudu', [receivedBubble]), {}, 'receipt-confirmed bubble is not saved back to resend queue');

  const settledLater = model.reconcilePendingSends([receivedBubble], [earlierEv, { at: '2026-11-23 20:00:01', type: 'user', text: '修一下' }], {
    now: t0 + 25000, pmAddress: 't182', logReady: true, receipts: [receipt], lang: 'zh',
  });
  assert.equal(settledLater.pending.length, 0);
  assert.equal(settledLater.settled.length, 1);
});

test('cross-timezone (UTC+8 viewer vs UTC-5 host, 13h skew): zero duplicate bubbles, zero false red errors, and accurate ordering', () => {
  // Simulate viewer on MBP (where eventTime parses naive timestamps) reading a remote host 13 hours behind (-46,800,000 ms).
  const sendUtcMs = 1795491005000;
  // Naive local string on remote host (`22:30:05`) would parse 13h EARLIER on a UTC+8 viewer (`eventTime(remoteAt) = sendUtcMs - 13h`).
  const remoteStateNow = '2026-11-23 22:30:05';
  const simulatedViewerParsedNow = model.eventTime(remoteStateNow);
  // Synthesize the true server UTC ms such that `eventTime(remoteStateNow) - serverNowMs === -13h` regardless of test runner's OS TZ!
  const thirteenHoursMs = 13 * 3600 * 1000;
  const serverNowMs = simulatedViewerParsedNow + thirteenHoursMs;
  const clockOffsetMs = model.computeClockOffsetMs({ now: remoteStateNow, server_now_ms: serverNowMs }, serverNowMs + 80);
  assert.equal(clockOffsetMs, -thirteenHoursMs, 'exact -13h timezone offset derived from (now, server_now_ms) independent of RTT');

  // 1) Pre-upgrade event WITHOUT `at_ms` or `msg_id`: `eventTimeUtcMs` calibrates `-13h` naive string back to exact `serverNowMs`!
  const legacyRemoteEvent = { at: '2026-11-23 22:30:06', type: 'user', text: '远程发消息不重影' };
  assert.equal(model.eventTimeUtcMs(legacyRemoteEvent, clockOffsetMs), serverNowMs + 1000);

  const pendingBubble = {
    id: 1,
    text: '远程发消息不重影',
    sentAt: serverNowMs,
    deliveredAt: serverNowMs + 200,
    received: true,
    receiptAt: serverNowMs + 400,
  };
  // Without clockOffsetMs (old broken behavior), eventTime is 13h < minAt -> failed to settle!
  // With clockOffsetMs, settles immediately -> ZERO duplicate bubbles!
  const reconciled = model.reconcilePendingSends([pendingBubble], [legacyRemoteEvent], {
    now: serverNowMs + 2000,
    pmAddress: 't182',
    logReady: true,
    clockOffsetMs,
    lang: 'zh',
  });
  assert.equal(reconciled.pending.length, 0, 'cross-timezone receipt-confirmed bubble settles cleanly with zero duplicate bubble');
  assert.equal(reconciled.settled.length, 1);

  // 2) Reverse direction (+13h skew, UTC-5 viewer reading UTC+8 host): PM reply from 5 minutes BEFORE send must NOT
  //    falsely trigger `turnEndedAfter` and time out a message sent during a long working turn!
  const plusOffset = thirteenHoursMs;
  const hostTrueNow = simulatedViewerParsedNow - plusOffset;
  const calcPlusOffset = model.computeClockOffsetMs({ now: remoteStateNow, server_now_ms: hostTrueNow }, hostTrueNow);
  assert.equal(calcPlusOffset, plusOffset);
  const oldReplyOnUtc8 = { at: '2026-11-23 22:25:00', type: 'pm', by: 'hc:t182', text: '五分钟前的上一轮回复' };
  const midTurnBubble = { id: 2, text: '长思考中途补充', sentAt: hostTrueNow, deliveredAt: hostTrueNow + 100, sentTo: 't182' };
  const midRes = model.reconcilePendingSends([midTurnBubble], [oldReplyOnUtc8], {
    now: hostTrueNow + 25_000,
    pmAddress: 't182',
    pmWorking: true,
    logReady: true,
    remote: true,
    clockOffsetMs: calcPlusOffset,
    lang: 'zh',
  });
  assert.equal(midRes.failed.length, 0, '+13h host timestamp must not falsely satisfy turnEndedAfter while PM is working');

  // 3) Causal `msg_id` settles instantaneously even with arbitrary clock corruption and identical text.
  const bCausal = { id: 3, msgId: 'u-causal-42', text: '好', sentAt: sendUtcMs, deliveredAt: sendUtcMs + 50 };
  const evCausal = { seq: 9, at: '1999-01-01 00:00:00', at_ms: 915148800000, type: 'user', msg_id: 'u-causal-42', text: '好' };
  assert.equal(model.settlePending([bCausal], [evCausal]).length, 0, 'msg_id settles regardless of physical timestamps');
});

test('busy-turn multi-message coalescing: when agy merges 2+ queued user messages with newline, receipts and settlePending match all bubbles', () => {
  const t0 = model.eventTime('2026-11-23 21:00:00');
  const b1 = { id: 1, text: '先别动 UI 样式', sentAt: t0, deliveredAt: t0 + 100, sentTo: 't182' };
  const b2 = { id: 2, text: '顺便把跨时区单测也跑一遍', sentAt: t0 + 1500, deliveredAt: t0 + 1600, sentTo: 't182' };

  // 1) Coalesced receipt in `receipts.json` confirms BOTH pending bubbles immediately (neither times out red or resends).
  const mergedReceipt = {
    at: '2026-11-23 21:00:05',
    at_ms: t0 + 5000,
    text: '先别动 UI 样式\n顺便把跨时区单测也跑一遍',
    digest: 'merged-1',
  };
  const rConfirm = model.reconcilePendingSends([b1, b2], [], {
    now: t0 + 25_000,
    pmAddress: 't182',
    pmWorking: false,
    logReady: true,
    receipts: [mergedReceipt],
    lang: 'zh',
  });
  assert.equal(rConfirm.failed.length, 0, 'neither coalesced bubble may fail with unconfirmedSend');
  assert.equal(rConfirm.confirmed.length, 2, 'single coalesced receipt confirms both constituent bubbles');
  assert.equal(rConfirm.pending.every(p => p.received), true);

  // 2) Coalesced `user` event in `conversation.jsonl` (including blank line separator or attachment `[Image #1]` mark) settles ALL constituent bubbles!
  const mergedEvent = {
    at: '2026-11-23 21:00:05',
    at_ms: t0 + 5000,
    type: 'user',
    text: '先别动 UI 样式\n\n顺便把跨时区单测也跑一遍',
  };
  const rSettle = model.reconcilePendingSends(rConfirm.pending, [mergedEvent], {
    now: t0 + 26_000,
    pmAddress: 't182',
    logReady: true,
    receipts: [mergedReceipt],
    lang: 'zh',
  });
  assert.equal(rSettle.pending.length, 0, 'coalesced conversation event settles both pending bubbles');
  assert.equal(rSettle.settled.length, 2);

  // 3) Attachment + follow-up text coalesced into `[Image #1] 看图\n右上角对齐一下`.
  const bImg = { id: 3, text: model.messageText('看图', ['/tmp/paste-1.png']), files: ['/tmp/paste-1.png'], sentAt: t0, deliveredAt: t0 + 100 };
  const bFollow = { id: 4, text: '右上角对齐一下', sentAt: t0 + 800, deliveredAt: t0 + 900 };
  const coalescedImgEv = { at: '2026-11-23 21:00:03', at_ms: t0 + 3000, type: 'user', text: '[Image #1] 看图\n右上角对齐一下' };
  assert.equal(model.settlePending([bImg, bFollow], [coalescedImgEv]).length, 0);

  // 4) Unsent `queued` bubble or partial non-exhaustive text must NEVER be swallowed by coalesced matching.
  const bUnsent = { id: 5, text: '顺便把跨时区单测也跑一遍', sentAt: t0 + 2000, queued: true };
  assert.equal(model.settlePending([b1, bUnsent], [mergedEvent]).length, 2, 'unsent queued bubble must not participate in coalesced settlement');
  const nonExhaustiveEv = { at: '2026-11-23 21:00:05', at_ms: t0 + 5000, type: 'user', text: '先别动 UI 样式\n顺便把跨时区单测也跑一遍\n还有第三句未知的话' };
  assert.equal(model.settlePending([b1, b2], [nonExhaustiveEv]).length, 2, 'non-exhaustive partition must not falsely settle subset');
});

test('PM observability & recovery: pmTurnWorking, pmActivityView, AsyncGate, and pm_pi_compact Stop hook bridge', async () => {
  // 1) Background-shell-only `working` never shows stuck `• • •`
  const termShells = { address: 't182', status: 'working', report: { state: 'working', msg: '2 shells still running' } };
  assert.equal(model.pmTurnWorking(termShells, [{ address: 't182', status: 'working' }]), false);
  const termAgyBg = { address: 't182', status: 'working', report: { state: 'working', msg: '' } };
  assert.equal(model.pmTurnWorking(termAgyBg, [{ address: 't182', status: 'working' }], { phase: 'idle', bg_shells: 1 }), false);
  assert.equal(model.pmTurnWorking(termAgyBg, [{ address: 't182', status: 'working' }], { phase: 'working', bg_shells: 0 }), true);

  // 2) Quiet live activity view: dots <3s -> tool summary -> 90s slow (interrupt) -> 300s stalled (interrupt + rotate)
  const baseMs = 1795491000000;
  const vShort = model.pmActivityView('zh', {
    turn: { phase: 'working', started_ms: baseMs, last_activity_ms: baseMs },
    working: true,
    nowMs: baseMs + 1500,
    serverNowMs: baseMs + 1500,
  });
  assert.equal(vShort.mode, 'dots');
  assert.equal(vShort.label, '');

  const vTool = model.pmActivityView('zh', {
    turn: { phase: 'working', started_ms: baseMs, last_activity_ms: baseMs + 10_000, activity: { kind: 'tool', tool: 'Bash', summary: 'pm.py diff #301' } },
    working: true,
    nowMs: baseMs + 14_000,
    serverNowMs: baseMs + 14_000,
  });
  assert.equal(vTool.mode, 'working');
  assert.match(vTool.label, /正在运行 pm\.py diff #301 · 14s/);
  assert.equal(vTool.canInterrupt, false);

  const vSlow = model.pmActivityView('zh', {
    turn: { phase: 'working', started_ms: baseMs, last_activity_ms: baseMs, activity: { kind: 'tool', tool: 'Bash', summary: 'git fetch' } },
    working: true,
    nowMs: baseMs + 95_000,
    serverNowMs: baseMs + 95_000,
  });
  assert.equal(vSlow.mode, 'slow');
  assert.equal(vSlow.canInterrupt, true);
  assert.equal(vSlow.canRotate, false);

  const vStalled = model.pmActivityView('zh', {
    turn: { phase: 'stalled', started_ms: baseMs, last_activity_ms: baseMs, activity: { kind: 'tool', tool: 'Bash', summary: 'sleep 999' } },
    working: true,
    nowMs: baseMs + 305_000,
    serverNowMs: baseMs + 305_000,
  });
  assert.equal(vStalled.mode, 'stalled');
  assert.equal(vStalled.canInterrupt, true);
  assert.equal(vStalled.canRotate, true);

  // 3) AsyncGate preempts hung RPC past deadline and ignores stale completions
  const gate = model.createAsyncGate();
  const tok1 = model.tryEnterAsyncGate(gate, 1000, 5000);
  assert.equal(tok1, 1);
  assert.equal(model.tryEnterAsyncGate(gate, 3000, 5000), 0, 'blocked before deadline');
  assert.equal(gate.again, true);
  const tok2 = model.tryEnterAsyncGate(gate, 7000, 5000);
  assert.equal(tok2, 2, 'preempts hung promise after deadline');
  assert.equal(model.finishAsyncGate(gate, tok1), false, 'stale token ignored');
  assert.equal(gate.busy, true);
  assert.equal(model.finishAsyncGate(gate, tok2), false);
  assert.equal(gate.busy, false);

  // 4) `pm_pi_compact.js` bridges `agent_end` to `pm.py hook-turn` asynchronously
  const piExt = await import('../pm-dash/skill/scripts/pm_pi_compact.js');
  const spawned = [];
  const handlers = new Map();
  piExt.default(
    { on(ev, fn) { handlers.set(ev, fn); }, sendMessage() {} },
    {
      instructions: 'rules',
      spawnHook(cmd, args, _opts) {
        let written = '';
        spawned.push({ cmd, args, get stdin() { return written; } });
        return {
          stdin: { on() {}, end(s) { written = s; } },
          unref() { spawned[spawned.length - 1].unreffed = true; },
        };
      },
    },
  );
  handlers.get('agent_end')(
    { messages: [{ role: 'user', content: 'hi' }, { role: 'assistant', content: [{ type: 'text', text: 'pi 回复完成' }] }] },
    { cwd: '/repo/demo', getContextUsage: () => ({ tokens: 1000 }) },
  );
  assert.equal(spawned.length, 1);
  assert.equal(spawned[0].unreffed, true);
  assert.equal(JSON.parse(spawned[0].stdin).last_assistant_message, 'pi 回复完成');
});

test('Steps card subplan rows bound long notes so titles are never squeezed or overlapped', () => {
  const mkTracker = () => {
    const nodes = new Map();
    const tips = [];
    const makeEl = kind => {
      const rec = { kind, id: '', styles: [], texts: [], kids: [] };
      const proxy = new Proxy(() => proxy, {
        get: (_, key) => {
          if (key === Symbol.toPrimitive) return () => 0;
          if (key === '__rec') return rec;
          return (...args) => {
            if (key === 'id') { rec.id = String(args[0]); nodes.set(rec.id, rec); }
            else if (key === 'child') {
              if (typeof args[0] === 'string') rec.texts.push(args[0]);
              else if (args[0]?.__rec) rec.kids.push(args[0].__rec);
            } else if (key === 'children' && Array.isArray(args[0])) {
              for (const k of args[0]) {
                if (typeof k === 'string') rec.texts.push(k);
                else if (k?.__rec) rec.kids.push(k.__rec);
              }
            } else if (key === 'when') {
              if (args[0]) args[1](proxy);
            } else {
              rec.styles.push([key, args]);
            }
            return proxy;
          };
        },
        apply: () => proxy,
      });
      return proxy;
    };
    const hasStyle = (rec, name, val) => rec.styles.some(([k, a]) => k === name && (val === undefined ? true : a[0] === val));
    const ui = {
      div: () => makeEl('div'),
      svg: () => makeEl('svg'),
      h_flex: () => makeEl('h_flex'),
      v_flex: () => makeEl('v_flex'),
      withTip: (key, el, text, opts) => { tips.push({ key, text, opts }); return el; },
    };
    return { nodes, tips, ui, hasStyle };
  };

  const longNote = '统一校验所有写入入口并补充长备注回归测试，防止挤垮左侧标题并溢出卡片右边界';
  const rawSub = `实现后端根治方案（${longNote}）`;
  const steps = model.taskSteps({
    status: 'in_progress',
    plan: [
      { text: '实现后端根治', state: 'doing', right: 'very-long-right-meta-label-that-must-not-overflow-the-step-card' },
      { text: '验证发布', state: 'todo' },
    ],
    subplan: [
      `[>] ${rawSub}`,
      '[ ] 补充单测（覆盖边界）',
    ],
  }, { lang: 'zh' });

  assert.equal(steps.steps[0].substeps[0].shortText, '实现后端根治方案');
  assert.equal(steps.steps[0].substeps[0].note, longNote);
  assert.equal(steps.steps[0].substeps[0].tip, rawSub);

  const theme = {
    surface: '#ffffff', raised: '#f4f4f6', hover: '#ececef', border: '#e2e2e7', input: '#d4d4db',
    foreground: '#18181b', muted: '#52525b', dim: '#71717a', accent: '#2563eb', ansi2: '#16a34a', working: '#16a34a',
  };
  const icons = { checkMark: 'check.svg', spinner: 'spin.svg', treeBranch: 'branch.svg', expand: 'exp.svg', chevron: 'chev.svg', windowPop: 'pop.svg' };

  // 1) Detail card (interactive, compact=false)
  const detail = mkTracker();
  stepsView.renderStepsCard({
    ui: detail.ui,
    steps,
    theme,
    lang: 'zh',
    icons,
    compact: false,
    framed: true,
    cardId: 'thread-plan-card',
    stepIdPrefix: 'plan-step',
    isSubOpen: () => true,
  });

  const subRow = detail.nodes.get('plan-substep-0-0');
  assert.ok(subRow, 'substep row renders');
  assert.equal(detail.hasStyle(subRow, 'w_full'), true, 'substep row fills container width');
  assert.equal(detail.hasStyle(subRow, 'min_w', 0), true, 'substep row sets min_w(0)');
  assert.equal(detail.hasStyle(subRow, 'overflow_hidden'), true, 'substep row clips overflow');

  const [markBox, titleBox, noteBox] = subRow.kids;
  assert.ok(markBox && titleBox && noteBox, 'substep row has mark, title, and note children');
  assert.equal(detail.hasStyle(titleBox, 'flex_1'), true, 'substep title keeps flex_1');
  assert.equal(detail.hasStyle(titleBox, 'min_w', 0), true, 'substep title keeps min_w(0)');
  assert.equal(detail.hasStyle(titleBox, 'whitespace_normal'), true, 'substep title wraps cleanly');
  assert.deepEqual(titleBox.texts, ['实现后端根治方案']);

  assert.equal(detail.hasStyle(noteBox, 'flex_none'), false, 'substep note container must NOT use flex_none');
  assert.equal(detail.hasStyle(noteBox, 'min_w', 0), true, 'substep note container sets min_w(0)');
  assert.equal(detail.hasStyle(noteBox, 'max_w', '40%'), true, 'substep note container caps width at 40%');
  assert.equal(detail.hasStyle(noteBox, 'flex_shrink_1'), true, 'substep note container shrinks when tight');
  assert.equal(detail.hasStyle(noteBox, 'overflow_hidden'), true, 'substep note container clips overflow');
  const noteText = noteBox.kids[0];
  assert.ok(noteText, 'note container has text child');
  assert.equal(detail.hasStyle(noteText, 'min_w', 0), true, 'note text sets min_w(0)');
  assert.equal(detail.hasStyle(noteText, 'truncate'), true, 'note text truncates with ellipsis');
  assert.deepEqual(noteText.texts, [longNote]);

  const subTip = detail.tips.find(x => x.key === 'plan-substep-0-0');
  assert.ok(subTip, 'substep with long note registers tooltip for full text');
  assert.equal(subTip.text, rawSub);
  assert.equal(subTip.opts?.wrap, true, 'substep tooltip wraps outside overflow_hidden row');
  assert.equal(subTip.opts?.full, true, 'substep tooltip wrapper stays full width');

  // Outer step row & rightMeta also guard against overflow/squeeze
  const stepRow = detail.nodes.get('plan-step-0');
  assert.ok(stepRow);
  assert.equal(detail.hasStyle(stepRow, 'w_full'), true);
  assert.equal(detail.hasStyle(stepRow, 'min_w', 0), true);
  assert.equal(detail.hasStyle(stepRow, 'overflow_hidden'), true);
  const rightMetaBox = stepRow.kids.find(k => k.kids.some(c => c.texts.includes('very-long-right-meta-label-that-must-not-overflow-the-step-card')));
  assert.ok(rightMetaBox, 'outer step rightMeta box renders');
  assert.equal(detail.hasStyle(rightMetaBox, 'flex_none'), false, 'outer step rightMeta must NOT use flex_none');
  assert.equal(detail.hasStyle(rightMetaBox, 'max_w', '40%'), true);
  assert.equal(detail.hasStyle(rightMetaBox, 'overflow_hidden'), true);
  assert.equal(detail.hasStyle(rightMetaBox.kids[0], 'truncate'), true);

  // 2) Compact hover card (compact=true) applies the same note bounding rules
  const compact = mkTracker();
  stepsView.renderStepsCard({
    ui: compact.ui,
    steps,
    theme,
    lang: 'zh',
    icons,
    compact: true,
    framed: false,
    stepIdPrefix: 'hover-step',
  });
  const compactSub = compact.nodes.get('plan-substep-0-0');
  assert.ok(compactSub, 'compact hover substep renders');
  assert.equal(compact.hasStyle(compactSub, 'min_w', 0), true);
  assert.equal(compact.hasStyle(compactSub, 'overflow_hidden'), true);
  assert.equal(compact.hasStyle(compactSub.kids[2], 'max_w', '40%'), true);
  assert.equal(compact.hasStyle(compactSub.kids[2].kids[0], 'truncate'), true);
});

test('parseRefLink resolves file:// repo & ledger docs, #L anchors, doc:/library:, relative .md, remote/Windows paths, and leaves https/thread intact', () => {
  const { parseRefLink } = model;
  const ctx = { repo: '/work/dudu', ledgerHome: '/Users/me/.dudu', slug: 'dudu' };

  // (a) file:// pointing to repo text/Markdown files (with and without #L anchors, localhost, encoded chars)
  assert.deepEqual(
    parseRefLink('file:///work/dudu/docs/design/auto-dream.md', ctx),
    { kind: 'file', target: 'docs/design/auto-dream.md', path: 'docs/design/auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('file:///work/dudu/docs/design/auto-dream.md#L10-L20', ctx),
    { kind: 'file', target: 'docs/design/auto-dream.md', path: 'docs/design/auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('file://localhost/work/dudu/mods/pm-project/main.js#L42', ctx),
    { kind: 'file', target: 'mods/pm-project/main.js', path: 'mods/pm-project/main.js' },
  );
  assert.deepEqual(
    parseRefLink('file:///work/dudu/docs/%E8%AE%BE%E8%AE%A1/my%20doc.md?raw=1#L5', ctx),
    { kind: 'file', target: 'docs/设计/my doc.md', path: 'docs/设计/my doc.md' },
  );

  // (b) file:// pointing to current project ledger docs/, docs/research/, decisions.md, memory/, personal memory
  assert.deepEqual(
    parseRefLink('file:///Users/me/.dudu/projects/dudu/docs/auto-dream.md', ctx),
    { kind: 'library', target: 'docs/auto-dream.md', root: 'docs', path: 'auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('file:///Users/me/.dudu/projects/dudu/docs/sub/spec.md#L1-L8', ctx),
    { kind: 'library', target: 'docs/sub/spec.md', root: 'docs', path: 'sub/spec.md' },
  );
  assert.deepEqual(
    parseRefLink('file:///Users/me/.dudu/projects/dudu/docs/research/auto-dream.md#L3', ctx),
    { kind: 'library', target: 'research/docs/research/auto-dream.md', root: 'research', path: 'docs/research/auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('file:///Users/me/.dudu/projects/dudu/decisions.md', ctx),
    { kind: 'library', target: 'docs/decisions.md', root: 'docs', path: 'decisions.md' },
  );
  assert.deepEqual(
    parseRefLink('file:///Users/me/.dudu/projects/dudu/memory/rule.md', ctx),
    { kind: 'library', target: 'memory/rule.md', root: 'memory', path: 'rule.md' },
  );
  assert.deepEqual(
    parseRefLink('file:///Users/me/.dudu/memory/pref.md', ctx),
    { kind: 'library', target: 'personal/pref.md', root: 'personal', path: 'pref.md' },
  );
  // Fallback ledgerHome inferred from conversation path when ledgerHome is empty
  assert.deepEqual(
    parseRefLink('file:///srv/.dudu/projects/dudu/docs/auto-dream.md', {
      repo: '/srv/dudu', ledgerHome: '', slug: 'dudu', conversation: '/srv/.dudu/projects/dudu/conversation.jsonl',
    }),
    { kind: 'library', target: 'docs/auto-dream.md', root: 'docs', path: 'auto-dream.md' },
  );

  // (c) doc:, library:, and repo-relative .md links
  assert.deepEqual(
    parseRefLink('doc:auto-dream.md', ctx),
    { kind: 'library', target: 'docs/auto-dream.md', root: 'docs', path: 'auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('doc:docs/auto-dream.md#L10', ctx),
    { kind: 'library', target: 'docs/auto-dream.md', root: 'docs', path: 'auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('doc:docs/research/auto-dream.md', ctx),
    { kind: 'library', target: 'research/docs/research/auto-dream.md', root: 'research', path: 'docs/research/auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('doc:research/auto-dream.md', ctx),
    { kind: 'library', target: 'research/docs/research/auto-dream.md', root: 'research', path: 'docs/research/auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('library:docs/research/auto-dream.md#overview', ctx),
    { kind: 'library', target: 'research/docs/research/auto-dream.md', root: 'research', path: 'docs/research/auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('docs/design/auto-dream.md', ctx),
    { kind: 'file', target: 'docs/design/auto-dream.md', path: 'docs/design/auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('./docs/design/auto-dream.md#L10-L20', ctx),
    { kind: 'file', target: 'docs/design/auto-dream.md', path: 'docs/design/auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('README.markdown', ctx),
    { kind: 'file', target: 'README.markdown', path: 'README.markdown' },
  );

  // Cross-machine remote & Windows paths
  const remoteCtx = { repo: '/home/dev/dudu', ledgerHome: '/home/dev/.dudu', slug: 'dudu' };
  assert.deepEqual(
    parseRefLink('file:///home/dev/dudu/docs/design/auto-dream.md#L1-L15', remoteCtx),
    { kind: 'file', target: 'docs/design/auto-dream.md', path: 'docs/design/auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('file:///home/dev/.dudu/projects/dudu/docs/auto-dream.md', remoteCtx),
    { kind: 'library', target: 'docs/auto-dream.md', root: 'docs', path: 'auto-dream.md' },
  );
  const winCtx = { repo: 'c:\\work\\dudu', ledgerHome: 'C:\\Users\\dev\\.dudu', slug: 'dudu' };
  assert.deepEqual(
    parseRefLink('file:///C:/work/dudu/docs/design/auto-dream.md#L9', winCtx),
    { kind: 'file', target: 'docs/design/auto-dream.md', path: 'docs/design/auto-dream.md' },
  );
  assert.deepEqual(
    parseRefLink('file:///C:/Users/dev/.dudu/projects/dudu/docs/note.md', winCtx),
    { kind: 'library', target: 'docs/note.md', root: 'docs', path: 'note.md' },
  );

  // Security boundaries & non-doc links must NOT be intercepted
  assert.equal(parseRefLink('https://example.com/docs/auto-dream.md#L10', ctx), null);
  assert.equal(parseRefLink('http://localhost:3000/README.md', ctx), null);
  assert.equal(parseRefLink('file:///Users/me/.dudu/projects/other/docs/secret.md', ctx), null);
  assert.equal(parseRefLink('file:///etc/passwd', ctx), null);
  assert.equal(parseRefLink('file:///work/dudu/.git/HEAD', ctx), null);
  assert.equal(parseRefLink('file:///work/dudu/../secret.md', ctx), null);
  assert.equal(parseRefLink('doc:repo/secret.md', ctx), null);
  assert.equal(parseRefLink('../outside.md', ctx), null);
  assert.equal(parseRefLink('/abs/no-scheme.md', ctx), null);
  assert.equal(parseRefLink('#heading', ctx), null);
  assert.equal(parseRefLink('docs/not-markdown.txt', ctx), null);
  assert.deepEqual(parseRefLink('thread:dudu-doc-link-open-in-sidebar', ctx), { kind: 'thread', target: 'dudu-doc-link-open-in-sidebar' });
});

test('PmProject followLink opens file://, doc:, and relative .md links in right sidebar Library (local & remote) without intercepting https/thread', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import\b[\s\S]*?;\s*$/gm, '')
    .replace(/export\s+default\s+class\s+PmProject/, 'class PmProject') + '\nreturn PmProject;';

  const openedUrls = [];
  const fileCalls = [];
  const stubs = {
    View: class {}, ...model,
    div: () => ({}), h_flex: () => ({}), v_flex: () => ({}), svg: () => ({}), image: () => ({}),
    TextView: { markdown: () => ({}), html: () => ({}) },
    TextareaState: { new: () => ({ on() {}, value: () => '', set_value() {}, set_selected_range() {}, set_auto_grow() {}, set_soft_wrap() {}, focus() {} }) },
    Textarea: { new: () => ({}) },
    InputState: { new: () => ({ on() {}, value: () => '', set_value() {}, focus() {} }) },
    Input: { new: () => ({}) },
    ScrollHandle: { new: () => ({ scroll_to_item() {} }) },
    Popup: { new: () => ({}) },
    theme: () => ({}), home: () => '/Users/me', appHome: () => '/app',
    exec: async (_cmd, args, opts) => {
      const a = Array.isArray(args) ? args : [];
      fileCalls.push({ args: a, on: opts?.on || '' });
      const idx = a.indexOf('file');
      if (idx >= 0) return { code: 0, stdout: JSON.stringify({ text: '# Auto Dream\n', size: 13, version: 'v1' }), stderr: '' };
      return { code: 0, stdout: '{}', stderr: '' };
    },
    execPython: async (_exec, argv, opts) => stubs.exec('python3', argv, opts),
    readTextFile: async () => '', writeTextFile: async () => {}, watchFolder: () => new Promise(() => {}),
    layout: () => ({ id: 'pm-stage', active: 'pm-project', children: [{ id: 'work' }, { id: 'pm-project' }] }),
    run() {}, terminals: () => [], agents: () => [], panes: () => [], spaces: () => [],
    shared: () => ({ pm: 'pm-dudu' }), setShared() {}, props: () => ({}),
    openOverlay() {}, closeOverlay() {}, appWindow: () => ({ platform: 'macos' }),
  };

  const Mod = new Function(...Object.keys(stubs), source)(...Object.values(stubs));
  const cx = {
    spawn: fn => fn(cx),
    timer: { after: () => {}, every: () => {} },
    notify() {},
    open_url: url => openedUrls.push(url),
  };
  const pmLocal = { name: 'pm-dudu', project: 'dudu', repo: '/work/dudu', pane: 'hc:tpm', runtime: 'hc', status: 'live' };
  const view = Object.assign(Object.create(Mod.prototype), {
    state: { pms: [pmLocal], tasks: [{ id: 't-a', pm: 'pm-dudu', title: 'Alpha', status: 'in_progress' }], events: [], lang: 'zh' },
    events: [], pmName: 'pm-dudu', logPath: '', logSlug: 'dudu', machine: '', stateFor: '',
    ledgerHome: '/Users/me/.dudu', remoteHome: '', remoteNoProject: '', remoteNoLibrary: '', remoteNoMemory: '', remoteNoSession: '',
    thread: '', threadTask: null, detail: true, threadError: '', threadLog: null, threadLogKept: [],
    threadTab: 'log', change: model.createChangeState(), sideTab: 'threads',
    librarySlug: 'dudu', libraryRoots: [], libraryFiles: [], libraryRead: true, libraryProbed: true, libraryStale: false,
    libraryQuery: '', memoryQuery: '',
    activeDoc: null, docCache: new Map(), docFailed: new Map(), docLoading: '', docError: '', docShownBytes: model.DOC_INITIAL_BYTES,
    docFindOpen: false, docFindQuery: '', docJumpQuery: '', docFindJump: false, docMatchPos: 0,
    editingDoc: null, retopicOpen: false, retopicError: '', confirmDeleteKey: '', deleteError: '', historyView: null,
    listShown: false, wide: true, docFindInput: { set_value() {} },
    threadInput: stubs.TextareaState.new(), threadKey: '', threadFiles: [], threadDraft: '',
    readThread() {}, syncThreadSession() {},
  });

  // 1) Local file:// repo doc with #L anchor expands collapsed sidebar, exits thread detail, switches to Library, opens root:'repo'
  view.followLink('file:///work/dudu/docs/design/auto-dream.md#L10-L20', cx);
  await new Promise(r => setTimeout(r, 15));
  assert.equal(view.listShown, true, 'sidebar auto-expands');
  assert.equal(view.detail, false, 'thread detail closes');
  assert.equal(view.sideTab, 'library', 'switches to Library tab');
  assert.deepEqual(view.activeDoc, { tab: 'library', root: 'repo', path: 'docs/design/auto-dream.md' });
  assert.equal(view.docCache.get('repo/docs/design/auto-dream.md')?.text, '# Auto Dream\n');
  assert.equal(openedUrls.length, 0);

  // 2) Local file:// ledger docs/ and docs/research/
  view.listShown = false;
  view.sideTab = 'threads';
  view.followLink('file:///Users/me/.dudu/projects/dudu/docs/auto-dream.md', cx);
  await new Promise(r => setTimeout(r, 15));
  assert.equal(view.listShown, true);
  assert.equal(view.sideTab, 'library');
  assert.deepEqual(view.activeDoc, { tab: 'library', root: 'docs', path: 'auto-dream.md' });

  view.followLink('file:///Users/me/.dudu/projects/dudu/docs/research/auto-dream.md', cx);
  await new Promise(r => setTimeout(r, 15));
  assert.deepEqual(view.activeDoc, { tab: 'library', root: 'research', path: 'docs/research/auto-dream.md' });

  // 3) doc: and repo-relative .md links
  view.followLink('doc:notes.md', cx);
  await new Promise(r => setTimeout(r, 15));
  assert.deepEqual(view.activeDoc, { tab: 'library', root: 'docs', path: 'notes.md' });

  view.followLink('docs/design/auto-dream.md', cx);
  await new Promise(r => setTimeout(r, 15));
  assert.deepEqual(view.activeDoc, { tab: 'library', root: 'repo', path: 'docs/design/auto-dream.md' });

  // 4) Remote machine uses remote pm.repo and remoteHome
  fileCalls.length = 0;
  view.machine = 'box';
  view.stateFor = 'box';
  view.remoteHome = '/srv/.dudu';
  view.state.pms = [{ ...pmLocal, machine: 'box', repo: '/srv/dudu' }];
  view.listShown = false;
  view.followLink('file:///srv/dudu/docs/design/remote-spec.md#L5-L12', cx);
  await new Promise(r => setTimeout(r, 15));
  assert.equal(view.listShown, true);
  assert.deepEqual(view.activeDoc, { tab: 'library', root: 'repo', path: 'docs/design/remote-spec.md' });
  assert.equal(fileCalls.some(c => c.on === 'box'), true, 'remote repo doc reads on remote machine');

  view.followLink('file:///srv/.dudu/projects/dudu/docs/remote-note.md', cx);
  await new Promise(r => setTimeout(r, 15));
  assert.deepEqual(view.activeDoc, { tab: 'library', root: 'docs', path: 'remote-note.md' });

  // 5) Normal https:// still opens in external browser; thread:<id> still opens thread detail
  const prevDoc = view.activeDoc;
  view.followLink('https://example.com/docs/auto-dream.md', cx);
  assert.deepEqual(openedUrls, ['https://example.com/docs/auto-dream.md']);
  assert.deepEqual(view.activeDoc, prevDoc);

  view.followLink('thread:t-a', cx);
  assert.equal(view.detail, true);
  assert.equal(view.thread, 't-a');
});

test('validMemoryPayload preserves dream and returns null for legacy payloads without dream', () => {
  const legacy = model.validMemoryPayload({ files: [], candidates: [], history: { project: 0, personal: 0 } });
  assert.equal(legacy.dream, null);

  const neverRun = model.validMemoryPayload({
    files: [],
    candidates: [],
    history: { project: 0, personal: 0 },
    dream: { auto: false, running: false, last_at: '', summary: null, failures: 0, pending: 0 },
  });
  assert.deepEqual(neverRun.dream, {
    auto: false,
    running: false,
    last_at: '',
    summary: null,
    failures: 0,
    pending: 0,
  });

  const withSummary = model.validMemoryPayload({
    files: [],
    candidates: [],
    dream: {
      auto: true,
      running: false,
      last_at: '2026-11-23 02:13:10',
      summary: { merged: 2, removed: 3, forgotten: 1, adopted: 2, dropped: 1, refused: 1, flags: 2 },
      failures: 0,
      pending: 14,
    },
  });
  assert.deepEqual(withSummary.dream, {
    auto: true,
    running: false,
    last_at: '2026-11-23 02:13:10',
    summary: { merged: 2, removed: 3, forgotten: 1, adopted: 2, dropped: 1, refused: 1, flags: 2 },
    failures: 0,
    pending: 14,
  });
});

test('formatDreamStatus formats running, last-run with summary/flags, pending, and empty states in en and zh', () => {
  assert.equal(model.formatDreamStatus(null, 'en'), '');
  assert.equal(model.formatDreamStatus(null, 'zh'), '');

  // Never consolidated and nothing pending -> hidden
  const clean = { auto: false, running: false, last_at: '', summary: null, failures: 0, pending: 0 };
  assert.equal(model.formatDreamStatus(clean, 'en'), '');
  assert.equal(model.formatDreamStatus(clean, 'zh'), '');

  // 1. Running
  const running = { auto: false, running: true, last_at: '2026-11-23 02:13:10', summary: null, failures: 0, pending: 5 };
  assert.equal(model.formatDreamStatus(running, 'en'), 'Consolidating…');
  assert.equal(model.formatDreamStatus(running, 'zh'), '整理中…');

  // 2. Last consolidated with summary & flags (3 hours ago)
  const now3h = model.eventTime('2026-11-23 05:13:10');
  const ran = {
    auto: false,
    running: false,
    last_at: '2026-11-23 02:13:10',
    summary: { merged: 2, removed: 3, forgotten: 1, adopted: 2, dropped: 1, refused: 1, flags: 2 },
    failures: 0,
    pending: 0,
  };
  assert.equal(
    model.formatDreamStatus(ran, 'zh', now3h),
    '上次整理 3 小时前 · 合并 2 · 收编 2 · 归档 1 · 2 条待你看',
  );
  assert.equal(
    model.formatDreamStatus(ran, 'en', now3h),
    'Last consolidated 3h ago · merged 2 · adopted 2 · archived 1 · 2 to review',
  );

  // Just now (<1m) and empty summary
  const now20s = model.eventTime('2026-11-23 02:13:30');
  const ranQuiet = {
    auto: false,
    running: false,
    last_at: '2026-11-23 02:13:10',
    summary: { merged: 0, removed: 0, forgotten: 0, adopted: 0, dropped: 0, refused: 0, flags: 0 },
    failures: 0,
    pending: 0,
  };
  assert.equal(model.formatDreamStatus(ranQuiet, 'zh', now20s), '上次整理 刚刚');
  assert.equal(model.formatDreamStatus(ranQuiet, 'en', now20s), 'Last consolidated just now');

  // 3. Never consolidated with pending > 0
  const pending = { auto: false, running: false, last_at: '', summary: null, failures: 0, pending: 14 };
  assert.equal(model.formatDreamStatus(pending, 'zh'), '14 条待整理');
  assert.equal(model.formatDreamStatus(pending, 'en'), '14 pending consolidation');
});

test('memoryPanel renders #memory-dream-status only when dream line is non-empty and hides it on legacy null', async () => {
  const { readFileSync } = await import('node:fs');
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*?;$/gm, '')
    .replace('export default class PmProject extends View', 'return class');
  const nodes = new Map();
  const makeEl = () => {
    const rec = { id: '', texts: [], kids: [] };
    const allTexts = r => [...r.texts, ...r.kids.flatMap(allTexts)];
    const proxy = new Proxy(function () {}, {
      get: (_, key) => {
        if (key === Symbol.toPrimitive) return () => 0;
        if (key === '__rec') return rec;
        return (...args) => {
          if (key === 'id') {
            rec.id = String(args[0]);
            nodes.set(rec.id, rec);
          } else if (key === 'child' && typeof args[0] === 'string') {
            rec.texts.push(args[0]);
          } else if (key === 'child' && args[0]?.__rec) {
            rec.kids.push(args[0].__rec);
          } else if (key === 'children' && Array.isArray(args[0])) {
            for (const k of args[0]) {
              if (typeof k === 'string') rec.texts.push(k);
              else if (k?.__rec) rec.kids.push(k.__rec);
            }
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
  const stubs = {
    View: class {}, ...model, ...stepsView,
    div: makeEl, h_flex: makeEl, v_flex: makeEl, svg: makeEl, image: makeEl,
    Input: { new: () => makeEl() },
    Popup: { new: (id, trigger) => makeEl().id(id).child(trigger) },
  };
  const scope = new Proxy(stubs, {
    has: (target, name) => name in target || !(name in globalThis),
    get: (target, name) => (name in target ? target[name] : name === Symbol.unscopables ? undefined : makeEl()),
  });
  const Mod = new Function('scope', `with (scope) { ${source} }`)(scope);
  const themeObj = {
    canvas: '#111111', surface: '#181818', raised: '#222222', chrome: '#161616', hover: '#2a2a2a',
    border: '#333333', input: '#3a3a3a', foreground: '#eeeeee', background: '#111111',
    muted: '#aaaaaa', dim: '#777777', accent: '#4f8cff', accent_foreground: '#ffffff',
    blocked: '#ff5f56', ansi2: '#27c93f', ansi3: '#f5a623', solid: '#eeeeee', solid_foreground: '#111111',
  };
  const makeInput = () => ({ value: () => '', set_value() {}, set_selected_range() {}, focus() {} });
  const cx = { notify() {}, stop_propagation() {} };
  const pmRec = { name: 'pm-dudu', project: 'dudu', repo: '/work/dudu' };
  const view = Object.assign(Object.create(Mod.prototype), {
    state: { pms: [pmRec], tasks: [], lang: 'zh' },
    lang: 'zh',
    pmName: 'pm-dudu', sideTab: 'memory', clockOffsetMs: 0,
    memorySlug: 'dudu', memoryRead: true, memoryStale: false, memoryLoading: false, memoryError: '',
    memoryFoldOverrides: new Map(), memoryProjectOpen: true, memoryPersonalOpen: false, memoryCandidatesOpen: false,
    memoryQuery: '', memoryBusy: '', memoryNoticeError: '',
    activeDoc: null, editingDoc: null, historyView: null, deletedBanner: null, docCache: new Map(),
    memoryInput: makeInput(), memoryScroll: { scroll_to_item() {} },
    memoryData: model.validMemoryPayload({ files: [], candidates: [], history: { project: 0, personal: 0 } }),
  });

  // 1. Legacy payload without `dream` -> #memory-dream-status absent
  nodes.clear();
  view.memoryPanel(pmRec, themeObj, 340, '2026-11-24', cx);
  assert.equal(nodes.has('memory-panel'), true);
  assert.equal(nodes.has('memory-dream-status'), false);

  // 2. Running state -> #memory-dream-status rendered
  view.memoryData = model.validMemoryPayload({
    files: [], candidates: [], history: { project: 0, personal: 0 },
    dream: { auto: false, running: true, last_at: '', summary: null, failures: 0, pending: 4 },
  });
  nodes.clear();
  view.memoryPanel(pmRec, themeObj, 340, '2026-11-24', cx);
  assert.equal(nodes.has('memory-dream-status'), true);
  assert.deepEqual(nodes.get('memory-dream-status').allTexts(), ['整理中…']);

  // 3. Pending state in English -> #memory-dream-status rendered in English
  view.state.lang = 'en';
  view.lang = 'en';
  view.memoryData = model.validMemoryPayload({
    files: [], candidates: [], history: { project: 0, personal: 0 },
    dream: { auto: false, running: false, last_at: '', summary: null, failures: 0, pending: 9 },
  });
  nodes.clear();
  view.memoryPanel(pmRec, themeObj, 340, '2026-11-24', cx);
  assert.equal(nodes.has('memory-dream-status'), true);
  assert.deepEqual(nodes.get('memory-dream-status').allTexts(), ['9 pending consolidation']);
});

test('projectTasksArgv builds CLI args and clamps limit/offset', () => {
  assert.deepEqual(
    model.projectTasksArgv('dudu'),
    ['project', 'tasks', 'dudu', '--status', 'finished', '--offset', '0', '--limit', String(model.TASKS_PAGE_LIMIT)],
  );
  assert.deepEqual(
    model.projectTasksArgv('dudu', { status: 'all', q: ' #218 ', offset: 30, limit: 200 }),
    ['project', 'tasks', 'dudu', '--status', 'all', '--q', '#218', '--offset', '30', '--limit', '100'],
  );
  assert.equal(model.isOldPmCommand({ code: 2, stderr: "error: argument project_cmd: invalid choice: 'tasks'" }), true);
});

test('parseProjectTasksPage, normalizeProjectTaskRow and mergeFinishedRows handle pagination and deduplication', () => {
  assert.equal(model.parseProjectTasksPage(null), null);
  const page = model.parseProjectTasksPage({
    tasks: [
      { id: 'dudu-218', number: 218, title: 'History search', status: 'merged', branch: 'dev/history', updated: '2026-11-20 10:00', commit: 'abc1234' },
      { id: 'dudu-198', number: 198, title: 'Older task', status: 'done', branch: 'dev/older', updated: '2026-11-18 10:00' },
    ],
    total: 42,
    offset: 0,
    limit: 30,
    more: true,
  });
  assert.equal(page.total, 42);
  assert.equal(page.more, true);
  assert.equal(page.tasks.length, 2);

  const row = model.normalizeProjectTaskRow(page.tasks[0]);
  assert.equal(row.task, 'dudu-218');
  assert.equal(row.number, 218);
  assert.equal(row.group, 'finished');
  assert.equal(row.tone, 'quiet');
  assert.equal(row.commit, 'abc1234');

  const merged = model.mergeFinishedRows(
    [{ task: 'dudu-218', number: 218, title: 'History search', status: 'merged', group: 'finished', updated: '2026-11-20 10:00' }],
    page.tasks.map(t => model.normalizeProjectTaskRow(t)),
  );
  assert.deepEqual(merged.map(r => r.task), ['dudu-218', 'dudu-198']);
});

test('filterLocalThreads falls back locally by #number, title, and branch while skipping abandoned/review/question-only', () => {
  const pm = { name: 'pm-dudu' };
  const tasks = [
    { id: 'dudu-218', pm: 'pm-dudu', number: 218, title: 'Threads history search', status: 'merged', branch: 'dev/threads-history', updated: '2026-11-20 10:00' },
    { id: 'dudu-301', pm: 'pm-dudu', number: 301, title: 'Wire animation', status: 'in_progress', branch: 'dev/wires', updated: '2026-11-22 10:00' },
    { id: 'dudu-drop', pm: 'pm-dudu', number: 205, title: 'Dropped history', status: 'abandoned', branch: 'dev/drop', updated: '2026-11-21 10:00' },
    { id: 'dudu-218-review', pm: 'pm-dudu', number: 219, title: 'Review #218', status: 'done', review_of: 'dudu-218', updated: '2026-11-20 11:00' },
  ];
  const events = [
    { type: 'thread', task: 'dudu-q', status: 'blocked', title: 'Question about history', at: '2026-11-19 10:00' },
    { type: 'thread', task: 'dudu-q', status: 'done', title: 'Question about history', at: '2026-11-19 10:05' },
    { type: 'thread', task: 'dudu-198', number: 198, status: 'merged', title: 'Legacy history', at: '2026-11-15 10:00' },
  ];

  assert.deepEqual(model.filterLocalThreads(pm, tasks, events, '#218').map(r => r.task), ['dudu-218']);
  assert.deepEqual(model.filterLocalThreads(pm, tasks, events, '198').map(r => r.task), ['dudu-198']);
  assert.deepEqual(model.filterLocalThreads(pm, tasks, events, 'dev/wires').map(r => r.task), ['dudu-301']);
  assert.deepEqual(model.filterLocalThreads(pm, tasks, events, 'history').map(r => r.task), ['dudu-218', 'dudu-198']);

  assert.equal(model.word('en', 'searchThreads'), 'Search Threads…');
  assert.equal(model.word('zh', 'searchThreads'), '搜索线程…');
  assert.equal(model.word('en', 'loadMoreFinished', 12), 'Show more (12 more)');
  assert.equal(model.word('zh', 'loadMoreFinished', 12), '显示更多（还有 12 条）');
});

test('repo_docs: libraryGroups 4-section layout, single docs/ shell strip, large-tree folding, superseded_by ordering, and legacy fallback', () => {
  const payload = {
    roots: [
      { id: 'docs', writable: true },
      { id: 'repo_docs', writable: false, truncated: true, total: 210 },
      { id: 'research', writable: false },
      { id: 'instructions', writable: false },
    ],
    files: [
      { root: 'docs', path: 'active.md', kind: 'md', size: 100, modified: '2026-11-20T10:00:00Z', writable: true, title: 'Active note' },
      { root: 'docs', path: 'auto-dream-draft.md', kind: 'md', size: 200, modified: '2026-11-24T10:00:00Z', writable: true, title: 'Draft', superseded_by: 'docs/design/auto-dream.md' },
      { root: 'docs', path: 'decisions.md', kind: 'md', size: 50, modified: '2026-11-25T10:00:00Z', writable: false, archive: true, entries: 3 },
      { root: 'repo_docs', path: 'docs/design', kind: 'folder', size: 0, modified: '2026-11-24T09:00:00Z', writable: false },
      { root: 'repo_docs', path: 'docs/design/auto-dream.md', kind: 'md', size: 1024, modified: '2026-11-24T09:00:00Z', writable: false, title: 'autoDream 定稿', task: 'dudu-auto-dream', task_title: 'autoDream 设计' },
      { root: 'repo_docs', path: 'docs/guide.md', kind: 'md', size: 512, modified: '2026-11-20T09:00:00Z', writable: false, title: '使用指南' },
      { root: 'research', path: 'published/library-design.md', kind: 'md', size: 800, modified: '2026-11-19T09:00:00Z', writable: false, title: 'Library Design', published: true },
      { root: 'instructions', path: 'CLAUDE.md', kind: 'md', size: 400, modified: '2026-11-21T09:00:00Z', writable: false },
    ],
  };

  const groups = model.libraryGroups(payload, new Set(), 'zh', '2026');
  assert.deepEqual(groups.map(g => g.id), ['docs', 'repo_docs', 'research', 'instructions']);

  // Superseded ledger draft sinks below active docs (even when newer), but stays above archive decisions.md.
  const docsPaths = groups[0].rows.map(r => r.path);
  assert.deepEqual(docsPaths, ['active.md', 'auto-dream-draft.md', 'decisions.md']);
  assert.equal(groups[0].rows[1].supersededBy, 'docs/design/auto-dream.md');

  // Repo docs group: read-only, truncated metadata preserved, redundant `docs/` shell stripped visually.
  const rd = groups[1];
  assert.equal(rd.title, '仓库文档');
  assert.equal(rd.readOnly, true);
  assert.equal(rd.writable, false);
  assert.equal(rd.truncated, true);
  assert.equal(rd.total, 210);
  assert.equal(rd.shown, 2);
  assert.deepEqual(rd.rows.map(r => [r.folder ? 'dir' : 'file', r.depth, r.name, r.path]), [
    ['dir', 0, 'design', 'docs/design'],
    ['file', 1, 'auto-dream.md', 'docs/design/auto-dream.md'],
    ['file', 0, 'guide.md', 'docs/guide.md'],
  ]);
  assert.equal(rd.rows[0].open, true);
  assert.equal(rd.rows[1].desc, 'autoDream 定稿');
  assert.equal(rd.rows[1].task, 'dudu-auto-dream');
  assert.equal(model.isWritableDoc(rd.rows[1].file), false);

  // Large tree (> 15 files): design folder stays open by default, non-design subfolder defaults closed.
  const manyFiles = [
    { root: 'repo_docs', path: 'docs/design/spec.md', kind: 'md', size: 100, modified: '2026-11-24T00:00:00Z', writable: false },
    ...Array.from({ length: 16 }, (_, i) => ({
      root: 'repo_docs', path: `docs/guides/g-${i}.md`, kind: 'md', size: 100, modified: '2026-11-20T00:00:00Z', writable: false,
    })),
  ];
  const largeGroups = model.libraryGroups(manyFiles, new Set(), 'en', '2026');
  const rdRows = largeGroups.find(g => g.id === 'repo_docs').rows;
  const designDir = rdRows.find(r => r.folder && r.path === 'docs/design');
  const guidesDir = rdRows.find(r => r.folder && r.path === 'docs/guides');
  assert.equal(designDir.open, true);
  assert.equal(guidesDir.open, false);
  // Toggling key in `closed` opens a defaultClosed folder.
  const toggledRows = model.libraryGroups(manyFiles, new Set(['repo_docs/docs/guides']), 'en', '2026')
    .find(g => g.id === 'repo_docs').rows;
  assert.equal(toggledRows.find(r => r.folder && r.path === 'docs/guides').open, true);

  // Legacy remote without repo_docs degrades gracefully (no repo_docs section).
  const legacyGroups = model.libraryGroups({
    roots: [{ id: 'docs', writable: true }, { id: 'instructions', writable: false }],
    files: [{ root: 'instructions', path: 'CLAUDE.md', kind: 'md', size: 100, modified: '2026-11-20T00:00:00Z', writable: false }],
  }, new Set(), 'en', '2026');
  assert.deepEqual(legacyGroups.map(g => g.id), ['docs', 'instructions']);
});

test('repo_docs: @mention deduplicates repoFiles, ranks repo doc above superseded draft, and searchLibrary demotes superseded drafts', () => {
  const libraryFiles = [
    { root: 'docs', path: 'auto-dream-draft.md', kind: 'md', size: 200, modified: '2026-11-24T12:00:00Z', writable: true, title: 'autoDream draft', superseded_by: 'docs/design/auto-dream.md' },
    { root: 'repo_docs', path: 'docs/design/auto-dream.md', kind: 'md', size: 800, modified: '2026-11-24T09:00:00Z', writable: false, title: 'autoDream design' },
    { root: 'instructions', path: 'CLAUDE.md', kind: 'md', size: 300, modified: '2026-11-21T09:00:00Z', writable: false },
  ];
  const repoFiles = ['docs/design/auto-dream.md', 'CLAUDE.md', 'src/auto-dream-helper.py'];

  // Global @ search: repo_docs ranks first, superseded draft ranks behind & dimmed, duplicate file: entry omitted.
  const globalMenu = model.buildMentionMenu({
    query: 'auto-dream',
    category: 'all',
    libraryFiles,
    repoFiles,
    lang: 'en',
  });
  const keys = globalMenu.items.map(i => i.key);
  assert.equal(keys[0], 'library:repo_docs/docs/design/auto-dream.md');
  assert.ok(keys.includes('library:docs/auto-dream-draft.md'));
  assert.ok(!keys.includes('file:docs/design/auto-dream.md'));
  assert.ok(keys.indexOf('library:repo_docs/docs/design/auto-dream.md') < keys.indexOf('library:docs/auto-dream-draft.md'));
  const draftItem = globalMenu.items.find(i => i.key === 'library:docs/auto-dream-draft.md');
  assert.equal(draftItem.dimmed, true);

  // Explicit @ -> Files submenu keeps all repo files including docs/design/auto-dream.md.
  const filesMenu = model.buildMentionMenu({
    query: 'auto-dream',
    category: 'files',
    libraryFiles,
    repoFiles,
    lang: 'en',
  });
  assert.ok(filesMenu.items.some(i => i.key === 'file:docs/design/auto-dream.md'));

  // searchLibrary ranks repo doc ahead of superseded draft and propagates supersededBy.
  const hits = model.searchLibrary(libraryFiles, 'auto-dream', null, 'en', '2026');
  assert.deepEqual(hits.map(h => h.key), ['repo_docs/docs/design/auto-dream.md', 'docs/auto-dream-draft.md']);
  assert.equal(hits[1].supersededBy, 'docs/design/auto-dream.md');

  // documentView exposes supersededBy.
  const vm = model.documentView(libraryFiles[0], '# Draft\n\nBody.', { lang: 'en', today: '2026-11-24' });
  assert.equal(vm.supersededBy, 'docs/design/auto-dream.md');
});

test('repo_docs: resolveContextLink handles intra-root, research cross-root, and repo source fallback', () => {
  const files = [
    { root: 'repo_docs', path: 'docs/README.md', kind: 'md', size: 100, modified: '2026-11-24T00:00:00Z' },
    { root: 'repo_docs', path: 'docs/design/auto-dream.md', kind: 'md', size: 100, modified: '2026-11-24T00:00:00Z' },
    { root: 'research', path: 'docs/research/library-design.md', kind: 'md', size: 100, modified: '2026-11-20T00:00:00Z', published: 'published/library-design.md' },
    { root: 'research', path: 'published/at-mention.md', kind: 'md', size: 100, modified: '2026-11-20T00:00:00Z', published: true },
  ];
  const fromReadme = { root: 'repo_docs', path: 'docs/README.md' };
  assert.deepEqual(model.resolveContextLink(fromReadme, 'design/auto-dream.md', files),
    { root: 'repo_docs', path: 'docs/design/auto-dream.md' });
  assert.deepEqual(model.resolveContextLink(fromReadme, 'research/library-design.md', files),
    { root: 'research', path: 'docs/research/library-design.md' });
  assert.deepEqual(model.resolveContextLink(fromReadme, 'research/at-mention.md', files),
    { root: 'research', path: 'published/at-mention.md' });
  assert.deepEqual(model.resolveContextLink(fromReadme, '../mods/pm-project/model.js', files),
    { root: 'repo', path: 'mods/pm-project/model.js' });
  assert.equal(model.resolveContextLink(fromReadme, '../../outside.md', files), null);
});
