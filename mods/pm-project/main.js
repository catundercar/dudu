import { View, div, svg, image } from 'gpui-kit';
import { v_flex, h_flex, TextView, TextareaState, Textarea, ScrollHandle } from 'gpui-base';
import { theme, home, appHome, exec, readTextFile, watchFolder, layout, run, terminals, agents, shared } from 'herdr';
import {
  word, timeline, parseConversation, settlePending, waitingCount, bellTarget, answerText, clock, dayLabel, shortPath,
  diffArgv, sendArgv, pmRow, taskRow, terminalFor, terminalTargetFor, cleanTaskLog, statusLabel, tone, turns, newestReply,
  withAlpha, solidText, isDarkTheme, viewMarkdown, LEDGER_HOME_SH, EVENT_LIMIT,
} from './model.js';

// The project view reads the ledger through the original pm-dash bundle, like pm-list.
const PM_SCRIPT = '/mods/pm-dash/skill/scripts/pm.py';
const STAGE = 'pm-stage', WORK = 'work';
// pm-list names the project to show here: shared('pm-project') = {pm: <PM name>}.
const SHARED = 'pm-project';
const ICON = name => `mods/pm-project/${name}.svg`;
const COLUMN = 680, PANEL = 360, FADE = { duration: 180, easing: 'ease-out' };
// How many renders the view keeps asking for the end after the blocks last changed
// height. Counted in renders, not milliseconds: a window that draws few frames (in the
// background, or covered) keeps following until its last reply has its full height.
const SETTLE = 3;
// The design's dark lift, `0 10px 28px rgba(0,0,0,.28)`, built from stacked rounded
// layers since only preset shadows exist: each layer grows the box by one sixth-quantile
// of the blur's gaussian (sigma 14), and six of them composite to .28 black. The layer
// that would sit wholly behind the box is left out.
const LIFT = { y: 10, grow: [-9, -3, 3, 9, 19], alpha: 1 - .72 ** (1 / 6) };

const iso = date => {
  const pad = n => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
};

export default class PmProject extends View {
  init(_props, cx) {
    this.state = { pms: [], tasks: [] };
    this.events = []; this.pending = []; this.seq = 0;
    this.error = ''; this.logError = '';
    this.pmName = ''; this.logPath = '';
    this.ledgerHome = ''; this.watching = {};
    this.thread = ''; this.threadTask = null; this.panelOpen = false; this.threadError = '';
    this.seen = null; this.count = 0; this.settle = 0; this.away = false;
    this.unfolded = new Map(); this.newest = '';
    this.scroll = ScrollHandle.new();
    this.input = TextareaState.new({ rows: 1 });
    this.input.set_auto_grow(1, 6);
    this.input.on('change', (_e, cx) => {
      const had = Boolean(this.draft?.trim());
      this.draft = this.input.value();
      if (had !== Boolean(this.draft.trim())) cx.notify();
    });
    // Enter sends (the key handler below catches it first); Shift+Enter stays a new line.
    this.input.on('submit', (e, cx) => { if (!e?.shift) this.sendMain(cx); });
    this.threadInput = TextareaState.new({ rows: 1 });
    this.threadInput.set_auto_grow(1, 4);
    this.threadInput.on('change', (_e, cx) => {
      const had = Boolean(this.threadDraft?.trim());
      this.threadDraft = this.threadInput.value();
      if (had !== Boolean(this.threadDraft.trim())) cx.notify();
    });
    this.threadInput.on('submit', (e, cx) => { if (!e?.shift) this.sendThread(cx); });
    cx.spawn(async cx => {
      // Until the first state reports `home`, apply pm.py's rule without waiting for it.
      let fallback = home() + '/.dudu';
      try {
        const r = await exec('sh', ['-c', LEDGER_HOME_SH]);
        if (r.code === 0 && r.stdout.trim()) fallback = r.stdout.trim();
      } catch (_) { /* Keep the default. */ }
      if (!this.ledgerHome) this.setLedgerHome(fallback, cx);
    });
    this.refresh(cx);
    cx.timer.every(10000, cx => this.refresh(cx));
  }

  // One watcher per folder; a different ledger home arms new ones and the old ones stop at their next wake.
  watch(path, onChange, cx) {
    if (!path || this.watching[path]) return;
    const home = this.ledgerHome;
    this.watching[path] = true;
    cx.spawn(async cx => {
      try {
        while (this.ledgerHome === home) {
          const changed = await watchFolder(path);
          if (this.ledgerHome === home) onChange(changed, cx);
        }
      } catch (_) { /* A missing folder: the 10-second refresh arms it again. */ }
      finally { delete this.watching[path]; }
    });
  }
  setLedgerHome(path, cx) {
    if (typeof path !== 'string' || !path || path === this.ledgerHome) return;
    this.ledgerHome = path;
    this.watching = {};
    this.arm(cx);
  }
  arm(cx) {
    if (!this.ledgerHome) return;
    this.watch(this.ledgerHome + '/tasks', (_paths, cx) => this.refresh(cx), cx);
    // The conversation logs live in <ledger home>/projects/<project>/; the folder appears with the first event.
    this.watch(this.ledgerHome + '/projects', (paths, cx) => {
      if (!this.logPath || paths.some(p => p === this.logPath || !p.endsWith('.jsonl'))) this.readLog(cx);
    }, cx);
  }

  refresh(cx) {
    if (this.loading) { this.again = true; return; }
    this.loading = true;
    cx.spawn(async cx => {
      try {
        const r = await exec('python3', [appHome() + PM_SCRIPT, 'state']);
        if (r.code !== 0) throw new Error(r.stderr || `pm.py: ${r.code}`);
        const state = JSON.parse(r.stdout);
        if (!Array.isArray(state.pms) || !Array.isArray(state.tasks)) throw new Error('state is missing pms/tasks arrays');
        this.state = state;
        this.error = '';
        this.setLedgerHome(state.home, cx);
        this.arm(cx);
      } catch (e) { this.error = String(e); }
      finally {
        this.loading = false;
        this.readLog(cx);
        this.readThread(cx);
        cx.notify();
        if (this.again) { this.again = false; this.refresh(cx); }
      }
    });
  }

  // The last events of the selected project's log. `tail` keeps the read small however long the log grows.
  readLog(cx) {
    const pm = this.pm(), path = pm?.conversation || '';
    if (path !== this.logPath) { this.logPath = path; this.events = []; }
    if (!path) { cx.notify(); return; }
    if (this.logLoading) { this.logAgain = true; return; }
    this.logLoading = true;
    cx.spawn(async cx => {
      try {
        const r = await exec('sh', ['-c', 'test -f "$1" || exit 0; tail -n "$2" "$1"', 'sh', path, String(EVENT_LIMIT * 2)]);
        if (r.code !== 0) throw new Error(r.stderr || `tail: ${r.code}`);
        if (path === this.logPath) {
          this.events = parseConversation(r.stdout);
          this.pending = settlePending(this.pending, this.events);
          this.logError = '';
        }
      } catch (e) { this.logError = String(e); }
      finally {
        this.logLoading = false;
        cx.notify();
        if (this.logAgain) { this.logAgain = false; this.readLog(cx); }
      }
    });
  }

  // The open thread's whole ledger entry: its log, branch, worktree and base.
  readThread(cx) {
    const id = this.thread;
    if (!id || !this.ledgerHome) return;
    cx.spawn(async cx => {
      try {
        const text = await readTextFile(`${this.ledgerHome}/tasks/${id}.json`);
        if (id === this.thread) this.threadTask = text ? JSON.parse(text) : null;
      } catch (_) { /* Keep what is shown. */ }
      cx.notify();
    });
  }

  pm() {
    return this.state.pms.find(p => p.name === this.pmName) || null;
  }
  pmTerminal() {
    const row = pmRow(this.pm());
    return row ? terminalFor(row, terminals()) || null : null;
  }
  threadTerminal() {
    const task = this.threadTask || this.state.tasks.find(t => t.id === this.thread);
    return task ? terminalFor(taskRow(task), terminals()) || null : null;
  }

  send(address, text) {
    return exec('env', sendArgv(address, text), { timeout: 20000 }).then(r => {
      if (r.code !== 0) throw new Error((r.stderr || r.stdout).trim() || `hc send: ${r.code}`);
    });
  }
  // The bubble shows at once; the same line in the log replaces it.
  // `question` tags a quick answer so its options stay disabled while it is in flight.
  say(text, cx, question) {
    text = String(text || '').trim();
    const terminal = this.pmTerminal();
    if (!text || !terminal) return false;
    const bubble = { id: ++this.seq, text, sentAt: Date.now(), question };
    this.pending = [...this.pending, bubble];
    cx.notify();
    cx.spawn(async cx => {
      try { await this.send(terminal.address, text); }
      catch (e) { this.pending = this.pending.map(p => p.id === bubble.id ? { ...p, failed: String(e.message || e) } : p); }
      cx.notify();
      this.readLog(cx);
    });
    return true;
  }
  sendMain(cx) {
    if (this.say(this.input.value(), cx)) { this.input.set_value(''); this.draft = ''; }
  }
  // A failed bubble: clicking sends it again.
  retry(id, cx) {
    const bubble = this.pending.find(p => p.id === id);
    if (!bubble) return;
    this.pending = this.pending.filter(p => p.id !== id);
    this.say(bubble.text, cx, bubble.question);
  }
  sendThread(cx) {
    const text = this.threadInput.value().trim(), terminal = this.threadTerminal();
    if (!text || !terminal) return;
    this.threadInput.set_value(''); this.threadDraft = ''; this.threadError = '';
    cx.spawn(async cx => {
      try { await this.send(terminal.address, text); }
      catch (e) { this.threadError = String(e.message || e); this.threadInput.set_value(text); this.threadDraft = text; }
      cx.notify();
    });
    cx.notify();
  }

  openThread(id, cx) {
    if (this.thread === id && this.panelOpen) { this.panelOpen = false; cx.notify(); return; }
    if (this.thread !== id) { this.threadTask = null; this.threadError = ''; this.threadInput.set_value(''); this.threadDraft = ''; }
    this.thread = id;
    this.panelOpen = true;
    this.readThread(cx);
    cx.notify();
  }
  // A scroll request is used once, after the next layout, and a reply that is still
  // reaching its full height pushes the end out again. So following asks for the end
  // marker on every render until no block has changed height for SETTLE renders; a
  // block that changes height (markdown settling, the panel narrowing the column, a
  // turn gaining a part) starts that count again, unless the reader scrolled up.
  follow() { this.away = false; this.settle = SETTLE; }
  resized(cx) {
    if (this.away || !this.pmName) return;
    this.settle = SETTLE;
    cx.notify();
  }
  focusTerminal(address) {
    run('agent.focus', { terminal: address });
    run('layout.select', { stack: STAGE, child: WORK });
  }

  // ---- pieces ---------------------------------------------------------------

  icon(name, size = 16) {
    return svg(ICON(name)).size(size).flex_none();
  }
  // An icon with a quiet hover fill; inert and dimmed when it has nothing to do.
  iconButton(id, name, tip, action, t, size = 16) {
    return h_flex().id(id).size(32).flex_none().rounded(9).items_center().justify_center().text_color(t.muted)
      .tooltip(tip).accessibility_label(tip)
      .when(Boolean(action), el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
        .on_click((_e, cx) => action(cx)))
      .when(!action, el => el.opacity(.4))
      .child(this.icon(name, size));
  }
  avatar(t) {
    return h_flex().size(28).flex_none().rounded(9).items_center().justify_center()
      .bg(t.surface).border_1().border_color(t.border)
      .child(svg(ICON('dudu')).size(15).text_color(t.foreground));
  }
  // The soft drop shadow under cards and the message box: the design's lift on a dark
  // canvas (a preset there darkens the canvas by about 1/255), the lighter preset on a light one.
  lift(el, t, radius) {
    if (!isDarkTheme(t)) return el.shadow_lg();
    const black = withAlpha('#000000', LIFT.alpha);
    return div().relative().w_full()
      .children(LIFT.grow.map(d => div().absolute().left(-d).right(-d).top(LIFT.y - d).bottom(-LIFT.y - d)
        .rounded(Math.max(0, radius + d)).bg(black)))
      .child(el);
  }
  toneColor(tn, t) {
    return tn === 'blocked' ? t.blocked : tn === 'review' ? t.accent : tn === 'running' ? t.ansi2 : t.dim;
  }
  // A status dot with a soft halo, as in the design.
  dot(color, t, solid = true) {
    return h_flex().size(14).flex_none().rounded_full().items_center().justify_center()
      .when(solid, el => el.bg(withAlpha(color, .18)))
      .child(div().size(8).rounded_full().when(solid, el => el.bg(color))
        .when(!solid, el => el.border(1.5).border_color(color)));
  }
  pill(text, color) {
    return h_flex().flex_none().h(22).px(8).rounded(7).items_center().whitespace_nowrap()
      .bg(withAlpha(color, .14)).text_color(color).text_size(12).font_medium().child(text);
  }
  // New items fade in: drawn transparent once, then opaque with a short transition.
  fade(el, key, cx) {
    const fresh = this.seen && !this.seen.has(key);
    if (fresh && !this.fading) {
      this.fading = true;
      cx.timer.after(16, cx => { this.fading = false; this.seen = new Set(this.keys); cx.notify(); });
    }
    return el.opacity(fresh ? 0 : 1).transition('opacity', FADE);
  }

  composer(id, state, draft, enabled, placeholder, offlineTip, onSend, t, radius, raised = false) {
    const ready = enabled && Boolean(draft?.trim());
    // The placeholder sits under the textarea while it is empty (its words change with the project and language).
    const hint = div().absolute().left(0).top(11).right(0).truncate().text_size(14).text_color(t.dim).child(placeholder);
    const field = enabled
      ? div().relative().flex_1().min_w(0).py(11).when(!draft, el => el.child(hint))
        .child(Textarea.new(state).w_full().text_size(14).text_color(t.foreground))
      : div().flex_1().min_w(0).py(11).text_size(14).text_color(t.dim).truncate().child(placeholder);
    const box = h_flex().id(id).w_full().items_end().gap(8).pl(16).pr(6).py(4).rounded(radius)
      .bg(t.surface).border_1().border_color(enabled ? t.input || t.border : t.border)
      .when(!enabled, el => el.opacity(.6).cursor_not_allowed().tooltip(offlineTip))
      .on_key_down((e, cx) => {
        if (enabled && e.keystroke === 'enter') { cx.stop_propagation(); onSend(cx); }
      })
      .child(field)
      .child(h_flex().id(`${id}-send`).size(44).flex_none().items_center().justify_center()
        .when(ready, el => el.cursor_pointer().on_click((_e, cx) => onSend(cx)))
        .tooltip(enabled ? word(this.lang, id === 'say' ? 'send' : 'sendThread') : offlineTip)
        .child(h_flex().size(30).rounded(15).items_center().justify_center()
          .bg(ready ? t.solid : t.raised).text_color(ready ? t.solid_foreground : t.muted)
          .child(this.icon('send', 15))));
    return raised ? this.lift(box, t, radius) : box;
  }

  threadRow(row, first, t) {
    const color = this.toneColor(row.tone, t), selected = this.panelOpen && this.thread === row.task;
    const tip = [statusLabel(this.lang, row.status, row.cleanup), row.title].join(' · ');
    return h_flex().id(`thread-${row.task}`).relative().h(48).pl(16).pr(12).gap(12).items_center().cursor_pointer()
      .when(selected, el => el.bg(t.selected)).when(!selected, el => el.hover(s => s.bg(t.hover)))
      .tooltip(tip)
      .on_click((_e, cx) => this.openThread(row.task, cx))
      .when(!first, el => el.child(div().absolute().top(0).left(0).right(0).h(1).bg(t.border)))
      .child(this.dot(color, t, row.tone !== 'quiet'))
      .child(div().flex_none().max_w('45%').truncate().font_medium()
        .text_color(row.tone === 'quiet' ? t.muted : t.foreground).child(row.title))
      .child(div().flex_1().min_w(0).truncate().text_size(13).text_color(t.muted).child(row.latest))
      .when(row.waiting, el => el.child(this.pill(word(this.lang, 'waiting'), color)))
      .child(this.icon('chevron', 14).text_color(t.dim));
  }

  // A thread whose work is over: its mark and title, dim until the pointer is on it. A click opens its panel.
  closedRow(row, t) {
    const selected = this.panelOpen && this.thread === row.task;
    const tip = [statusLabel(this.lang, row.status, row.cleanup), row.title].join(' · ');
    // The ring starts where a decision line's check icon does, and so does the title.
    return h_flex().id(`thread-${row.task}`).h(24).gap(7).items_center().cursor_pointer().text_size(12.5)
      .text_color(selected ? t.foreground : t.dim).hover(s => s.text_color(t.foreground))
      .tooltip(tip).accessibility_label(tip)
      .on_click((_e, cx) => this.openThread(row.task, cx))
      .child(h_flex().w(14).h(14).pl(1).flex_none().items_center()
        .child(div().size(9).rounded_full().border(1.5).border_color(t.dim)))
      .child(div().flex_1().min_w(0).truncate().child(row.title));
  }

  question(item, t, cx) {
    const thread = h_flex().id(`ask-${item.key}`).flex_none().h(22).px(8).gap(6).rounded(7).items_center().bg(t.raised)
      .text_size(13).font_medium().whitespace_nowrap().cursor_pointer().hover(s => s.bg(t.hover))
      .on_click((_e, cx) => this.openThread(item.task, cx))
      .child(div().size(6).rounded(3).bg(item.open ? t.blocked : t.dim)).child(item.title);
    const block = v_flex().gap(8)
      .child(h_flex().items_start().gap(8).child(thread)
        .child(div().flex_1().min_w(0).whitespace_normal().text_color(item.open ? t.foreground : t.muted).child(item.text)));
    const sending = this.pending.some(p => p.question === item.key && !p.failed);
    const live = Boolean(this.pmTerminal()) && !sending;
    if (!item.open || !item.options.length) return block;
    return block.child(h_flex().flex_wrap().gap(8).children(item.options.map((option, i) =>
      h_flex().id(`opt-${item.key}-${i}`).h(30).px(12).rounded(9).items_center().bg(t.raised).border_1().border_color(t.border)
        .text_size(13).font_medium().text_color(t.foreground)
        .when(live, el => el.cursor_pointer().hover(s => s.bg(t.hover).border_color(t.input || t.border))
          .on_click((_e, cx) => this.say(answerText(item.title, option), cx, item.key)))
        .when(!live, el => el.opacity(.5).tooltip(word(this.lang, sending ? 'sending' : 'offline')))
        .child(option))));
  }

  // What one item of a coordinator turn looks like.
  turnPart(item, t, cx) {
    if (item.kind === 'pm') {
      const whole = () => div().w_full().pt(3).text_size(14).text_color(t.foreground)
        .child(TextView.markdown(`md-${item.key}`, viewMarkdown(item.text)).selectable(true));
      if (!item.long) return whole();
      // A long reply shows its opening paragraph until it is opened. The newest one is open, and so
      // stays every reply that arrived while this project was on screen: history folds, the live
      // conversation does not move under the reader.
      const open = this.unfolded.has(item.key) ? this.unfolded.get(item.key) : item.key === this.newest;
      const set = value => cx => { this.unfolded.set(item.key, value); cx.notify(); };
      // The mark's color is its row's: it brightens when the pointer is anywhere on the row.
      const mark = name => h_flex().h(21).flex_none().items_center().child(this.icon(name, 15));
      if (open) {
        // The newest reply has nothing to fold back to; an older one folds with the mark at its end.
        if (item.key === this.newest) return whole();
        return v_flex().w_full().child(whole())
          .child(h_flex().child(h_flex().id(`fold-${item.key}`).pr(8).cursor_pointer()
            .text_color(t.dim).hover(s => s.text_color(t.foreground))
            .tooltip(word(this.lang, 'fold')).accessibility_label(word(this.lang, 'fold'))
            .on_click((_e, cx) => set(false)(cx)).child(mark('collapse'))));
      }
      // The opening as reply text with the mark right after it. The row wraps: an opening that fills
      // the column takes a line of its own and the mark goes under it at the left, where an open
      // reply has its fold mark; after a short opening the mark stays at its last word.
      return h_flex().w_full().pt(3).child(h_flex().id(`unfold-${item.key}`).min_w(0).max_w('100%').flex_wrap()
        .gap_x(6).items_end().cursor_pointer()
        .text_color(t.dim).hover(s => s.text_color(t.foreground))
        .tooltip(word(this.lang, 'unfold')).accessibility_label(word(this.lang, 'unfold'))
        .on_click((_e, cx) => set(true)(cx))
        .child(div().min_w(0).max_w('100%').whitespace_normal().text_size(14).text_color(t.foreground).child(item.lead))
        .child(mark('expand')));
    }
    if (item.kind === 'decision') {
      return h_flex().id(`decision-${item.key}`).gap(7).items_center().text_size(12.5).text_color(t.dim)
        .when(Boolean(item.quote), el => el.tooltip(`“${item.quote}”`))
        .child(this.icon('check', 14)).child(div().flex_1().min_w(0).whitespace_normal().child(item.text));
    }
    if (item.kind === 'threads') {
      // Open work is a card of rows; a thread that is over is one quiet line.
      const open = item.rows.filter(row => !row.closed), over = item.rows.filter(row => row.closed);
      const card = () => this.lift(v_flex().w_full().rounded(14).overflow_hidden().bg(t.surface).border_1().border_color(t.border)
        .children(open.map((row, i) => this.threadRow(row, i === 0, t))), t, 14);
      if (!over.length) return card();
      return v_flex().w_full().gap(4).when(open.length > 0, el => el.child(card()).child(div().h(4)))
        .children(over.map(row => this.closedRow(row, t)));
    }
    if (item.kind === 'question') return this.question(item, t, cx);
    // typing: the only looping motion here.
    return h_flex().h(28).gap(5).items_center().loop('opacity', { from: .35, to: 1, period: 1400 })
      .children([0, 1, 2].map(() => div().size(6).rounded(3).bg(t.muted)));
  }

  block(b, t, today, yesterday, cx) {
    if (b.kind === 'day') {
      const line = () => div().flex_1().h(1).bg(t.border);
      return h_flex().w_full().gap(12).items_center().text_size(12).text_color(t.dim)
        .child(line()).child(dayLabel(this.lang, b.date, today, yesterday)).child(line());
    }
    if (b.kind === 'user') {
      const el = div().max_w('72%').px(14).py(10).rounded_tl(18).rounded_tr(18).rounded_bl(18).rounded_br(6)
        .bg(t.raised).text_color(t.foreground).whitespace_normal().child(b.text);
      return h_flex().w_full().justify_end().gap(6).items_center()
        .when(Boolean(b.failed), row => row.child(h_flex().id(`retry-${b.key}`).size(22).rounded(11).items_center()
          .justify_center().text_color(t.blocked).cursor_pointer().hover(s => s.bg(t.hover))
          .tooltip(word(this.lang, 'failed', b.failed)).on_click((_e, cx) => this.retry(Number(b.key.split(':')[1]), cx))
          .child(div().text_size(13).font_semibold().child('!'))))
        .child(el.id(`bubble-${b.key}`).when(b.pending, el => el.opacity(.65).tooltip(word(this.lang, 'sending')))
          .when(!isDarkTheme(t) && !b.failed, el => el.border_1().border_color(t.border))
          .when(Boolean(b.failed), el => el.border_1().border_color(withAlpha(t.blocked, .6))));
    }
    return h_flex().w_full().items_start().gap(12)
      .child(b.bare ? div().w(28).flex_none() : this.avatar(t))
      .child(v_flex().flex_1().min_w(0).gap(12).children(b.parts.map(item => this.fade(this.turnPart(item, t, cx), item.key, cx))));
  }

  header(pm, waiting, target, t) {
    const terminal = pm ? terminalTargetFor(pmRow(pm), terminals()).terminal : null;
    const bellTip = waiting ? word(this.lang, 'waitingCount', waiting) : word(this.lang, 'nothingWaiting');
    const bell = h_flex().id('bell').relative().size(32).flex_none().rounded(10).items_center().justify_center()
      .text_color(t.muted).tooltip(bellTip).accessibility_label(bellTip)
      .when(target >= 0, el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
        .on_click(() => { this.away = true; this.settle = 0; this.scroll.scroll_to_item(target); }))
      .child(this.icon('bell', 17))
      .when(waiting > 0, el => el.child(h_flex().absolute().top(-3).right(-5).min_w(18).h(18).px(4).rounded(9)
        .items_center().justify_center().bg(t.blocked).border(2).border_color(t.canvas)
        .text_color(solidText(t.blocked, t)).text_size(10.5).font_semibold().child(String(waiting))));
    return h_flex().h(56).flex_none().px(28).gap(10).items_center().border_b(1).border_color(t.border)
      .child(div().flex_none().text_size(15).font_semibold().child(pm?.project || pm?.name || 'PM'))
      .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(12).text_color(t.dim)
        .child(shortPath(pm?.repo, home())))
      .when(Boolean(this.error || this.logError), el => el.child(div().id('read-error').text_color(t.blocked)
        .tooltip(`${word(this.lang, 'readError')}: ${this.logError || this.error}`).child('!')))
      .child(h_flex().gap(4).items_center()
        .child(bell)
        .child(this.iconButton('pm-terminal', 'terminal', terminal ? word(this.lang, 'openPm') : word(this.lang, 'noPmTerminal'),
          terminal ? () => this.focusTerminal(terminal.address) : null, t)));
  }

  panel(t, today) {
    const lang = this.lang;
    const stateTask = this.state.tasks.find(x => x.id === this.thread);
    const task = { ...stateTask, ...this.threadTask };
    const terminal = this.threadTerminal();
    const program = terminal?.program;
    const status = task.status || '', tn = tone(status, Boolean(stateTask?.cleanup));
    const argv = diffArgv(task);
    const log = (Array.isArray(task.log) ? task.log : []).slice(-60);
    const actions = h_flex().gap(2).items_center()
      .child(this.iconButton('thread-terminal', 'terminal', terminal ? word(lang, 'openTerminal') : word(lang, 'threadOffline'),
        terminal ? () => this.focusTerminal(terminal.address) : null, t))
      .child(this.iconButton('thread-diff', 'diff', argv ? word(lang, 'diff') : word(lang, 'noDiff'), argv ? () => {
        run('terminal.open', { argv, folder: argv[2], place: 'tab', name: `diff ${task.branch}` });
        run('layout.select', { stack: STAGE, child: WORK });
      } : null, t))
      .child(this.iconButton('thread-close', 'close', word(lang, 'close'), cx => { this.panelOpen = false; cx.notify(); }, t));
    const meta = h_flex().flex_wrap().gap(8).items_center().text_size(12).text_color(t.dim)
      .when(Boolean(status), el => el.child(this.pill(statusLabel(lang, status, Boolean(stateTask?.cleanup)),
        tn === 'quiet' ? t.muted : this.toneColor(tn, t))))
      .when(Boolean(task.branch), el => el.child(div().font_family('monospace').child(task.branch)))
      .when(Boolean(terminal), el => el.child(h_flex().id('thread-agent').gap(5).items_center()
        .tooltip(word(lang, 'agent', program?.name || 'agent', terminal.address))
        .child(!program?.icon ? this.icon('agent', 14) : program.tint ? svg(program.icon).size(14).text_color(t.dim)
          : image(program.icon).size(14))
        .child(div().font_family('monospace').child(terminal.address))));
    const entries = log.length ? log.map((entry, i) => {
      const latest = i === log.length - 1;
      return v_flex().relative().pl(18).gap(2)
        .child(div().absolute().left(0).top(7).size(7).rounded_full().bg(latest ? t.accent : t.border))
        .child(div().font_family('monospace').text_size(12).text_color(t.dim).child(clock(entry.at, today)))
        .child(div().whitespace_normal().text_size(13).text_color(latest ? t.foreground : t.muted)
          .child(cleanTaskLog(entry.text).text || entry.text || ''));
    }) : [div().pl(18).text_size(13).text_color(t.dim).child(word(lang, 'noLog'))];
    const timelineEl = v_flex().id('thread-log').flex_1().min_h(0).overflow_y_scrollbar()
      .child(v_flex().relative().gap(16).py(2)
        .child(div().absolute().left(3).top(10).bottom(10).w(1).bg(t.border))
        .children(entries));
    return v_flex().w(PANEL).h_full().flex_none().px(20).pt(12).pb(20).gap(18)
      .bg(t.chrome).border_l(1).border_color(t.border)
      .child(h_flex().gap(2).items_center()
        .child(div().flex_1().min_w(0).truncate().text_size(15).font_semibold().child(task.title || this.thread))
        .child(actions))
      .child(meta)
      .child(timelineEl)
      .when(Boolean(this.threadError), el => el.child(div().text_size(12).text_color(t.blocked).whitespace_normal()
        .child(word(lang, 'failed', this.threadError))))
      .child(this.composer('say-thread', this.threadInput, this.threadDraft, Boolean(terminal), word(lang, 'sayThread'),
        word(lang, 'threadOffline'), cx => this.sendThread(cx), t, 14));
  }

  render(cx) {
    const t = theme();
    this.lang = this.state.lang;
    const lang = this.lang;
    const wanted = shared(SHARED)?.pm || '';
    if (wanted !== this.pmName) {
      // Another project: its own log, no bubbles or panel from the last one.
      this.pmName = wanted; this.events = []; this.pending = []; this.panelOpen = false; this.thread = ''; this.threadTask = null;
      this.seen = null; this.count = 0; this.settle = 0; this.away = false; this.unfolded = new Map(); this.newest = '';
      cx.timer.after(0, cx => this.readLog(cx));
    }
    const root = h_flex().id('pm-project-root').size_full().min_w(0).min_h(0).overflow_hidden()
      .bg(t.canvas).text_size(14).text_color(t.foreground);
    const pm = this.pm();
    if (!pm) {
      const note = this.pmName && this.state.pms.length ? word(lang, 'noProject') : word(lang, 'pick');
      return root.items_center().justify_center().child(div().max_w(360).text_color(t.dim).whitespace_normal().child(note));
    }
    const now = new Date(), today = iso(now), yesterday = iso(new Date(now.getTime() - 86400000));
    const pmTerm = this.pmTerminal();
    const working = pmTerm && agents().find(a => a.address === pmTerm.address)?.status === 'working';
    const items = timeline(this.events, this.state.tasks, {
      pending: this.pending, today, typing: Boolean(working) || this.pending.some(p => !p.failed),
    });
    const blocks = turns(items);
    const newest = newestReply(items);
    if (this.newest && newest !== this.newest && !this.unfolded.has(this.newest)) this.unfolded.set(this.newest, true);
    this.newest = newest;
    // Fade only what arrives after the first read of this project.
    this.keys = items.map(i => i.key);
    if (!this.seen && this.events.length) this.seen = new Set(this.keys);
    // Follow the end of the conversation as it grows, including the first read after opening a project.
    if (blocks.length !== this.count) {
      if (blocks.length > this.count && blocks.length) this.follow();
      this.count = blocks.length;
    }
    // The end marker after the last block: revealing it bottom-aligns the end of a long
    // reply, where revealing the reply itself would rest at its top.
    if (blocks.length && this.settle > 0) {
      this.settle--;
      this.scroll.scroll_to_item(blocks.length);
      if (!this.ticking) { this.ticking = true; cx.timer.after(16, cx => { this.ticking = false; cx.notify(); }); }
    }
    const target = bellTarget(items), targetBlock = target < 0 ? -1 : blocks.findIndex(b => b.index.includes(target));
    const waiting = waitingCount(this.state, pm.name);
    const center = el => h_flex().w_full().justify_center().px(28).child(div().w_full().max_w(COLUMN).child(el));
    // Scrolling up lets go of the end until the next block arrives (wheel y > 0 moves toward the top).
    const body = v_flex().id('pm-project-timeline').flex_1().min_h(0).pt(28).gap(22).overflow_y_scrollbar()
      .track_scroll(this.scroll)
      .on_scroll_wheel(e => { if (e.delta.y > 0) { this.away = true; this.settle = 0; } })
      .children(blocks.length ? blocks.map(b => center(this.block(b, t, today, yesterday, cx))
        .id(`block-${b.key}`).on_size_change((_size, cx) => this.resized(cx)))
        : [center(div().text_color(t.dim).child(word(lang, 'empty')))])
      // With the gap above it, the end marker is the column's 28 px bottom padding.
      .child(div().flex_none().h(6));
    const main = v_flex().flex_1().min_w(0).h_full()
      .child(this.header(pm, waiting, targetBlock, t))
      .child(body)
      .child(center(this.composer('say', this.input, this.draft, Boolean(pmTerm), word(lang, 'say', pm.project || pm.name),
        word(lang, 'offline'), cx => this.sendMain(cx), t, 16, true)).pb(20).pt(4));
    // The thread panel slides open from the right edge; it keeps its content while it closes.
    const panel = h_flex().h_full().flex_none().overflow_hidden().justify_end()
      .w(this.panelOpen ? PANEL : 0).transition('width', { duration: 200, easing: 'ease-out' })
      .when(Boolean(this.thread), el => el.child(this.panel(t, today)));
    return root.child(main).child(panel);
  }
}
