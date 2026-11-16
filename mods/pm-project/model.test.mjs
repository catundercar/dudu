import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from './model.js';
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
  // The old PM still open after the rotation (labeled pm.retired, or still pm=dudu but not the current
  // one): passed over for the current PM, so the thread is not shown on a tab inviting talk to the old PM.
  const kept = terms.map(t => (t.address === 't52' ? { ...t, labels: { 'pm.retired': 'dudu' } } : t))
    .concat({ address: 't5p', state: 'live', labels: { pm: 'dudu' } });
  assert.deepEqual(model.focusPlan('t5h', kept, [...paned, 't5p'], 't5p'), { focus: 't5p', peek: 't5h' });
  assert.deepEqual(model.focusPlan('t5h', terms.concat(kept.at(-1)), [...paned, 't5p'], 't5p'), { focus: 't5p', peek: 't5h' });
  // A retired PM without a current one with a pane: nothing, rather than its tab.
  assert.deepEqual(model.focusPlan('t5h', kept, paned, 't5p'), { focus: '', peek: '' });
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

test('a PM that handed over is nobody to talk to', () => {
  // After `pm.py rotate`: t3k is the PM; the old PM's terminal t3b is still alive in the project folder, labeled pm.retired.
  const claude = { key: 'claude', name: 'Claude Code', agent: true };
  const terms = [
    { address: 't3k', state: 'live', cwd: '/r/dudu', labels: { pm: 'dudu' }, program: claude },
    { address: 't3b', state: 'live', cwd: '/r/dudu', labels: { 'pm.retired': 'dudu' }, program: claude },
    { address: 't1h', state: 'live', cwd: '/r/dudu', labels: {}, program: claude },
  ];
  const live = [{ address: 't3b', status: 'idle', title: 'PM 会话接替交接', tab: 'tb1', program: claude, seq: 9 },
    { address: 't1h', status: 'working', title: '改项目视图', tab: 'tb2', program: claude, seq: 5 },
    { address: 't3k', status: 'working', title: 'PM', tab: 'tb3', program: claude, seq: 7 }];
  const pm = { name: 'pm-dudu', project: 'dudu', repo: '/r/dudu', worktrees: '/w/dudu', pane: 'hc:t3k' };
  // Not a session in the side panel (a click there would open it, and its box would write to it).
  assert.deepEqual(threadList(pm, [], [], terms, live, []).sessions.map(row => row.address), ['t1h']);
  // The project's messages and quick answers go to the PM now, never to the old one.
  assert.equal(model.terminalFor(model.pmRow(pm), terms).address, 't3k');
  // A registration that still names the old terminal finds no PM in it, by its pane or by the project folder.
  const stale = model.pmRow({ ...pm, pane: 'hc:t3b' }), gone = terms.filter(term => term.address !== 't3k');
  assert.equal(model.terminalFor(stale, gone), undefined);
  assert.equal(model.terminalTargetFor(stale, gone).terminal.address, 't1h');
  assert.equal(model.terminalTargetFor(stale, [terms[1]]).terminal, undefined);
  // A task the old PM kept on its own terminal has no terminal: its thread box is off, not wired to the old PM.
  assert.equal(model.terminalFor(model.taskRow({ id: 'dudu-y', pane: 'hc:t3b' }), terms), undefined);
  // Without the label (a rotation by an older pm.py) the old terminal is an ordinary session of the project.
  const unlabeled = terms.map(term => (term.address === 't3b' ? { ...term, labels: {} } : term));
  assert.deepEqual(threadList(pm, [], [], unlabeled, live, []).sessions.map(row => row.address), ['t1h', 't3b']);
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
  // The tab that shows a thread's changes is named in the view's language.
  assert.deepEqual([model.word('en', 'diffTab', 'dev/x'), model.word('zh', 'diffTab', 'dev/x')], ['diff dev/x', '改动 dev/x']);
});

test('copied helpers stay identical to pm-dash and pm-list', () => {
  for (const name of ['cleanTaskLog', 'terminalFor', 'terminalTargetFor', 'focusPlan', 'withAlpha', 'isDarkTheme', 'solidText']) {
    assert.equal(model[name].toString(), dash[name].toString(), name);
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
    ['rev', 'review', 'review', true],
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
  assert.deepEqual(reattachArgv('/app/pm.py', 'dudu-x'),
    ['-u', 'HC_TERMINAL_ID', '-u', 'HERDR_PANE_ID', 'python3', '/app/pm.py', 'reattach', 'dudu-x']);
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
  // Open ones in the thread list's order (review, working, disconnected), then those that are over.
  assert.deepEqual(parts.map(row => [row.task, row.group]),
    [['d-esc', 'review'], ['d-label', 'working'], ['d-gone', 'offline'], ['d-effort', 'finished']]);
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
  // One row: the reviewed task, in review, with the review riding on it.
  assert.deepEqual(tasks.map(t => t.id), ['drag', 'jump']);
  assert.equal(tasks[0].review, review);
  const open = threadList(pm, tasks, [], [], []).open;
  assert.deepEqual(open.map(r => [r.task, r.group, r.status]), [['drag', 'review', 'review'], ['jump', 'working', 'in_progress']]);
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
  // A task that is in progress while its review is open reads as in review, as pm.py counts it.
  assert.deepEqual([row([task('in_progress'), review('in_progress')]).group, nav.summary({ pms: [pm], tasks: [task('in_progress'), review('in_progress')] }).active], ['review', 0]);
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
  assert.deepEqual(model.sendArgv(model.onMachine('t73', 'box'), 'hi'), ['-u', 'HC_TERMINAL_ID', 'hc', 'send', '--', 'box/t73', 'hi']);

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
  const blank = new Proxy(function () {}, { get: (_, key) => (key === Symbol.toPrimitive ? () => 0 : blank), apply: () => blank });
  const stubs = { View: class {}, projectRef: model.projectRef, machineView: model.machineView, onMachine: model.onMachine,
    remotePmArgv: model.remotePmArgv, sendArgv: model.sendArgv, pmRow: model.pmRow, terminalFor: model.terminalFor,
    terminals: () => [{ address: 't73', state: 'live', labels: { pm: 'dudu' } }, { address: 'box/t73', state: 'live', labels: { pm: 'dudu' } }],
    agents: () => [], panes: () => [],
    exec: async (command, args, options) => { calls.push([command, args, options]); return { code: 0, stdout: '', stderr: '' }; },
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
  // The log's tail and the thread's file come from that machine (exec / readTextFile `on`).
  assert.deepEqual(calls.slice(1).map(c => [c[0], c[2]?.on]).sort(), [['read', 'box'], ['sh', 'box']]);
  assert.equal(calls.find(c => c[0] === 'read')[1], '/Users/x/.claude/pm/tasks/dudu-a.json');
  // Before that machine's ledger is read, the view has no project from another one's state.
  assert.equal(Object.assign(view, { stateFor: '' }).pm(), null);
});
