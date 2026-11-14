import { View, div, svg, image } from 'gpui-kit';
import { v_flex, h_flex } from 'gpui-base';
import { theme, home, appHome, exec, readTextFile, watchFolder, layout, run, terminals, agents, shared, setShared } from 'herdr';
import { pmRows, remotePmStates, track, age, listHeight, LEDGER_HOME_SH } from './model.js';

// Like pm-nav, the list reads the ledger through the original pm-dash bundle.
const PM_SCRIPT = '/mods/pm-dash/skill/scripts/pm.py';
// A local PM's row opens its project view (pm-project), named through shared('pm-project').
const STAGE = 'pm-stage', WORK = 'work', PROJECT = 'pm-project';
const SPINNER = 'mods/workspace-chrome/spinner.svg', DUDU = 'mods/pm-list/dudu.svg';

const STRINGS = {
  en: { blocked: 'Needs you', working: 'Working', done: 'Done', idle: 'Idle',
    away: 'Not in the desktop app. Start it here, then run pm.py claim.',
    project: "Not in the desktop app. Click opens the project's space.", readError: 'Could not read the ledger',
    view: "Click opens the project's conversation", notDesktop: 'Not in the desktop app' },
  zh: { blocked: '等你', working: '工作中', done: '已完成', idle: '空闲',
    away: '这个 PM 不在桌面里。在桌面里启动它，再运行 pm.py claim。',
    project: '这个 PM 不在桌面里。点击打开项目的 space。', readError: '台账读取失败',
    view: '点击打开这个项目的对话', notDesktop: '这个 PM 不在桌面里' },
};
const word = (lang, key) => STRINGS[lang === 'zh' ? 'zh' : 'en'][key];

function find(node, test) {
  if (node && test(node)) return node;
  for (const child of node?.children ?? []) {
    const found = find(child, test);
    if (found) return found;
  }
  return null;
}

export default class PmList extends View {
  init(_props, cx) {
    this.state = { pms: [], events: [] }; this.remote = {};
    this.error = '';
    this.compact = false;
    this.ledgerHome = '';
    try { this.changed = JSON.parse(localStorage.getItem('changed') ?? '{}') || {}; } catch (_) { this.changed = {}; }
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
    cx.timer.every(30000, cx => cx.notify()); // "3m" ages without a new read.
  }
  // PM records live in <ledger home>/pms; the 10-second read covers a missing folder.
  setLedgerHome(path, cx) {
    if (typeof path !== 'string' || !path || path === this.ledgerHome) return;
    this.ledgerHome = path;
    cx.spawn(async cx => {
      try {
        while (this.ledgerHome === path) {
          await watchFolder(path + '/pms');
          if (this.ledgerHome === path) this.refresh(cx);
        }
      } catch (_) { /* Polling continues. */ }
    });
  }
  refresh(cx) {
    if (this.loading) { this.again = true; return; }
    this.loading = true;
    cx.spawn(async cx => {
      try {
        const r = await exec('python3', [appHome() + PM_SCRIPT, 'state']);
        if (r.code !== 0) throw new Error(r.stderr || `pm.py: ${r.code}`);
        const state = JSON.parse(r.stdout);
        if (!Array.isArray(state.pms)) throw new Error('state is missing the pms array');
        this.state = state;
        this.setLedgerHome(state.home, cx);
        this.error = '';
        // Other machines: what pm-nav last read over hc (it writes the cache, this only reads).
        const cached = this.ledgerHome && await readTextFile(this.ledgerHome + '/cache/remote-states.json').catch(() => null);
        this.remote = remotePmStates(cached);
      } catch (e) { this.error = String(e); }
      finally {
        this.loading = false;
        cx.notify();
        if (this.again) { this.again = false; this.refresh(cx); }
      }
    });
  }
  // The block grows with the list: resize this mod's own layout node to fit.
  // Compared with the node's size now, so a reloaded layout is fitted again;
  // asked once per (size, wanted) pair, so a clamped size does not ask on every render.
  fit(count) {
    const node = find(layout(), n => n.content?.mod === 'pm-list');
    const px = listHeight(count, this.compact), ask = `${node?.size?.px}>${px}`;
    if (!node?.id || node.size?.px === px || this.asked === ask) return;
    this.asked = ask;
    run('layout.resize', { id: node.id, px });
  }
  // A local PM opens in the project view when the layout has one; a remote PM (or an older layout) focuses its terminal.
  viewable(row) {
    return !row.machine && Boolean(find(layout(), n => n.id === STAGE)?.children?.some(c => c.id === PROJECT));
  }
  open(row) {
    const stage = find(layout(), n => n.id === STAGE);
    if (this.viewable(row)) {
      setShared(PROJECT, { pm: row.key });
      if (stage.active !== PROJECT) run('layout.select', { stack: STAGE, child: PROJECT });
      return;
    }
    if (!row.terminal) return;
    run('agent.focus', { terminal: row.terminal.address });
    // Re-clicking the focused PM changes no focus, so pm-nav would leave the board (or a project) up.
    if (stage && stage.active !== WORK) run('layout.select', { stack: STAGE, child: WORK });
  }
  // The status is a mark, never a word, except the small "needs you" badge.
  mark(t, status, lang) {
    if (status === 'working') return svg(SPINNER).size(12).mx(1).flex_none().text_color(t.working).spin(900);
    if (status === 'blocked') {
      const badge = div().flex_none().h(16).rounded(4).flex().items_center().justify_center()
        .bg(t.blocked + '26').text_color(t.blocked).text_size(10).font_semibold();
      return this.compact ? badge.w(14).child('!') : badge.px(5).child(word(lang, 'blocked'));
    }
    const dot = div().flex_none().size(7).mx(3).rounded_full();
    return status === 'done' ? dot.bg(t.done) : dot.border(1.5).border_color(t.idle ?? t.dim);
  }
  // The terminal's program picture when the PM is in the desktop, else the dudu mark.
  agentIcon(t, program) {
    const pic = !program?.icon ? svg(DUDU).text_color(t.dim)
      : program.tint ? svg(program.icon).text_color(t.foreground) : image(program.icon);
    return pic.w(16).h(16).flex_none();
  }
  render(cx) {
    const t = theme(), lang = this.state.lang, now = Date.now(), live = agents();
    const rows = pmRows(this.state, this.remote, terminals(), live);
    const changed = track(this.changed, rows, now);
    if (changed !== this.changed) {
      this.changed = changed;
      try { localStorage.setItem('changed', JSON.stringify(changed)); } catch (_) { /* Ages restart from the ledger. */ }
    }
    this.fit(rows.length);
    // The rail: the same rule as pm-nav, by this block's own width.
    const root = v_flex().id('pm-list-root').size_full().min_w(0).min_h(0).overflow_hidden()
      .bg(t.chrome).text_size(13).text_color(t.foreground)
      .on_size_change((size, cx) => {
        const compact = size.width < 120;
        if (compact !== this.compact) { this.compact = compact; cx.notify(); }
      });
    const stage = find(layout(), n => n.id === STAGE), viewing = stage?.active === PROJECT ? shared(PROJECT)?.pm : null;
    const tip = row => [row.machine ? `${row.label} · ${row.machine}` : row.label, word(lang, row.status),
      this.viewable(row) ? [!row.exact && word(lang, 'notDesktop'), word(lang, 'view')].filter(Boolean).join('\n')
        : !row.exact && word(lang, row.terminal ? 'project' : 'away')].filter(Boolean).join('\n');
    const focused = row => viewing ? row.key === viewing && !row.machine
      : row.exact && live.some(a => a.address === row.terminal.address && a.focused);
    const base = (row, el) => el.id(`pm-${row.key}`).flex_none().items_center()
      .when(focused(row), el => el.bg(t.selected)).hover(s => s.bg(t.hover))
      .when(Boolean(row.terminal) || this.viewable(row), el => el.cursor_pointer().on_click(() => this.open(row)))
      .tooltip(tip(row));
    if (this.compact) {
      return root.py(6).child(v_flex().id('pm-list-rows').flex_1().min_h(0).overflow_y_scrollbar().children(rows.map(row =>
        base(row, h_flex()).h(28).gap(4).justify_center()
          .child(this.agentIcon(t, row.program))
          .child(h_flex().w(14).flex_none().justify_center().child(this.mark(t, row.status, lang))))));
    }
    const header = h_flex().px(16).pt(8).h(30).flex_none().gap(6).items_center().text_size(11).font_medium().text_color(t.dim)
      .child('PM').child(String(rows.length))
      .when(Boolean(this.error), el => el.child(div().id('pm-list-error').text_color(t.blocked)
        .tooltip(`${word(lang, 'readError')}: ${this.error}`).child('!')));
    const list = v_flex().id('pm-list-rows').flex_1().min_h(0).px(8).pb(rows.length ? 6 : 0).overflow_y_scrollbar()
      .children(rows.map(row => {
        const at = this.changed[row.key]?.at;
        return base(row, h_flex()).px(8).h(30).rounded(8).gap(9)
          .child(this.agentIcon(t, row.program))
          .child(div().flex_1().min_w(0).truncate().text_color(row.status === 'idle' ? t.muted : t.foreground).child(row.label))
          .when(Boolean(row.machine), el => el.child(div().flex_none().text_size(10).text_color(t.dim).child(row.machine)))
          .when(Boolean(at), el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(age(now - at))))
          .child(this.mark(t, row.status, lang));
      }));
    return root.child(header).child(list);
  }
}
