import { View, div, svg } from 'gpui-kit';
import { v_flex, h_flex } from 'gpui-base';
import { theme, home, exec, watchFolder, layout, focused, run } from 'herdr';
import { summary, focusKey, shouldReturnToWork, WRITE_REMOTE_CACHE } from './model.js';

const PM_SCRIPT = '/.claude/skills/pm/scripts/pm.py';
const STAGE = 'pm-stage', BOARD = 'pm-board', WORK = 'work';

const STRINGS = {
  en: {
    summary: (p, n) => `${p} ${p === 1 ? 'project' : 'projects'} · ${n} in progress`,
    readError: 'Read failed', loading: 'Loading…', blocked: n => `${n} blocked`,
    retry: error => `Could not read summary. Retrying in 10 seconds: ${error}`, board: 'Board',
  },
  zh: {
    summary: (p, n) => `${p} 项目 · ${n} 进行中`,
    readError: '读取失败', loading: '读取中…', blocked: n => `${n} 阻塞`,
    retry: error => `摘要读取失败，10 秒后重试：${error}`, board: '看板',
  },
};
function word(lang, key, ...args) {
  const value = STRINGS[lang === 'zh' ? 'zh' : 'en'][key];
  return typeof value === 'function' ? value(...args) : value;
}

function find(node, id) {
  if (node?.id === id) return node;
  for (const child of node?.children ?? []) {
    const found = find(child, id);
    if (found) return found;
  }
  return null;
}
export default class PmNav extends View {
  init(_props, cx) {
    this.counts = null;
    this.localState = { pms: [], tasks: [], events: [] }; this.remoteStates = {};
    this.error = '';
    this.boardShown = false;
    this.focus = null;
    this.compact = false;
    this.refresh(cx);
    this.refreshRemote(cx);
    cx.timer.every(15000, cx => this.refreshRemote(cx));
    cx.timer.every(10000, cx => this.refresh(cx));
    cx.spawn(async cx => {
      try {
        for (;;) { await watchFolder(home() + '/.claude/pm/tasks'); this.refresh(cx); }
      } catch (_) { /* The 10-second fallback also covers a missing tasks directory. */ }
    });
  }
  refresh(cx) {
    if (this.loading) { this.again = true; return; }
    this.loading = true;
    cx.spawn(async cx => {
      try {
        const r = await exec('python3', [home() + PM_SCRIPT, 'state']);
        if (r.code !== 0) throw new Error(r.stderr || `pm.py: ${r.code}`);
        const state = JSON.parse(r.stdout);
        if (!Array.isArray(state.pms) || !Array.isArray(state.tasks)) throw new Error('state is missing pms/tasks arrays');
        this.localState = { ...state, events: state.events || [] };
        this.publish(cx);
        this.error = '';
      } catch (e) { this.error = String(e); }
      finally {
        this.loading = false;
        cx.notify();
        if (this.again) { this.again = false; this.refresh(cx); }
      }
    });
  }
  refreshRemote(cx) {
    if (this.remoteLoading) return;
    this.remoteLoading = true;
    cx.spawn(async cx => {
      try {
        const result = await exec('hc', ['machine', 'ls', '--json'], { timeout: 4000 });
        if (result.code !== 0) return;
        const listing = JSON.parse(result.stdout);
        const machines = Array.isArray(listing) ? listing : listing?.machines;
        if (!Array.isArray(machines)) return;
        const names = [...new Set(machines.filter(m => m.state === 'connected' && typeof m.name === 'string' && m.name).map(m => m.name))];
        // Disconnects remove rows; a transient read failure retains the last good snapshot.
        for (const name of Object.keys(this.remoteStates)) if (!names.includes(name)) delete this.remoteStates[name];
        await Promise.all(names.map(async name => {
          try {
            const r = await exec('hc', ['exec', '--on', name, 'python3 ~/.claude/skills/pm/scripts/pm.py state'], { timeout: 4000 });
            if (r.code !== 0) return;
            const state = JSON.parse(r.stdout);
            if (['pms', 'tasks', 'events'].every(k => Array.isArray(state[k]))) this.remoteStates[name] = state;
          } catch (_) { /* One unavailable machine must not interrupt the others. */ }
        }));
        this.publish(cx);
        try {
          await exec('python3', ['-c', WRITE_REMOTE_CACHE, home() + '/.claude/pm/cache/remote-states.json',
            JSON.stringify(this.remoteStates), String(Date.now())], { timeout: 4000 });
        } catch (_) { /* Cache writes are best effort; the sidebar is already updated. */ }
      } catch (_) { /* Discovery failures leave the last good board intact. */ }
      finally { this.remoteLoading = false; }
    });
  }
  publish(cx) {
    this.counts = summary(this.localState, this.remoteStates);
    this.lang = this.localState.lang;
    cx.notify();
  }
  render() {
    const textFor = (key, ...args) => word(this.lang, key, ...args);
    const t = theme(), stage = find(layout(), STAGE);
    const shown = stage?.active === BOARD, focus = focusKey(focused());
    const returnToWork = shouldReturnToWork(shown, this.boardShown, focus, this.focus);
    // Opening the board establishes a fresh baseline. Only later navigation
    // returns to work; live layout/focus data already triggers render, no polling.
    // Re-selecting the same item has no observable focus change. nextCommand()
    // only receives commands addressed to this mod, not other sidebar clicks.
    this.boardShown = shown;
    this.focus = focus;
    if (returnToWork) run('layout.select', { stack: STAGE, child: WORK });
    const on = shown && !returnToWork, n = this.counts;
    const text = n ? textFor('summary', n.projects, n.active) : this.error ? textFor('readError') : textFor('loading');
    const detail = `${text}${n?.blocked ? ` · ${textFor('blocked', n.blocked)}` : ''}`;
    const toggleBoard = () => {
      const current = find(layout(), STAGE);
      if (current) run('layout.select', { stack: STAGE, child: current.active === BOARD ? WORK : BOARD });
      else run('mod.open', { name: 'pm-dash' });
    };
    const root = v_flex().id('pm-nav-root').size_full().min_w(0).min_h(0).overflow_hidden()
      .bg(t.chrome).text_size(13).text_color(t.foreground)
      .on_size_change((size, cx) => {
        const compact = size.width < 120;
        if (compact !== this.compact) { this.compact = compact; cx.notify(); }
      });
    if (this.compact) {
      return root.items_center().justify_center()
        .child(h_flex().id('pm-board-link').relative().size(32).flex_none().rounded(8).items_center().justify_center()
          .cursor_pointer().when(on, el => el.bg(t.selected)).when(!on, el => el.hover(s => s.bg(t.hover)))
          .tooltip(`PM · ${textFor('board')}\n${detail}${this.error ? `\n${textFor('retry', this.error)}` : ''}`)
          .on_click(toggleBoard)
          .child(svg('mods/pm-nav/dudu.svg').size(22).text_color(t.foreground))
          .when(Boolean(n?.blocked), el => el.child(div().absolute().top(1).right(1).size(6).rounded(3).bg(t.blocked))));
    }
    const tail = h_flex().flex_1().min_w(0).gap(3).justify_end().items_center().text_size(11.5).text_color(t.dim)
      .child(div().min_w(0).truncate().child(text));
    if (n?.blocked) tail.child(div().flex_none().text_color(t.blocked).child(`· ${textFor('blocked', n.blocked)}`));
    if (this.error && n) tail.child(div().flex_none().text_color(t.blocked).child('!'));
    return root
      .child(h_flex().h(31).flex_none().pl(16).pr(10).items_center().text_size(11.5).text_color(t.dim).gap(6)
        .child(svg('mods/pm-nav/dudu.svg').size(14).text_color(t.foreground)).child('PM'))
      .child(div().px(8).child(h_flex().id('pm-board-link').h(30).px(8).gap(9).rounded(8).items_center()
        .cursor_pointer().when(on, el => el.bg(t.selected)).when(!on, el => el.hover(s => s.bg(t.hover)))
        .tooltip(this.error ? textFor('retry', this.error) : detail)
        .on_click(toggleBoard)
        .child(div().flex_none().child(textFor('board'))).child(tail)));
  }
}
