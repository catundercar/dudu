import { View, div, svg } from 'gpui-kit';
import { v_flex, h_flex } from 'gpui-base';
import { theme, home, appHome, exec, watchFolder, nextCommand, layout, focused, run, shared, setShared, openOverlay } from 'herdr';
import { summary, navText, estimateTextWidth, focusKey, isOverlayTerminalFocus, shouldReturnToWork, pageBefore, pageBack, projectKeys, WRITE_REMOTE_CACHE, LEDGER_HOME_SH, remoteStateCommand } from './model.js';
import { execPython } from './python.js';

// The sidebar deliberately depends on the original pm-dash bundle.
const PM_SCRIPT = '/mods/pm-dash/skill/scripts/pm.py';
const SETUP_SCRIPT = '/mods/pm-dash/setup.py';
const STAGE = 'pm-stage', BOARD = 'pm-board', WORK = 'work', PROJECT = 'pm-project';
// The block holds the entry row alone; it fits itself to that, as pm-list does.
const HEIGHT = 40;
// pm-dash's new-project dialog (its own overlay mode).
const NEW_DIALOG = { mod: 'pm-dash', props: { dialog: 'new' }, kind: 'dialog', width: 520, height: 520 };

const STRINGS = {
  en: {
    summary: (p, n) => `${p} ${p === 1 ? 'project' : 'projects'} · ${n} in progress`,
    readError: 'Read failed', loading: 'Loading…', blocked: n => `${n} need you`,
    retry: error => `Could not read summary. Retrying in 10 seconds: ${error}`, board: 'Projects',
    setup: 'Set up', newProject: 'New project',
  },
  zh: {
    summary: (p, n) => `${p} 项目 · ${n} 进行中`,
    readError: '读取失败', loading: '读取中…', blocked: n => `${n} 等你`,
    retry: error => `摘要读取失败，10 秒后重试：${error}`, board: 'Projects',
    setup: '未设置', newProject: '新建项目',
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
function findMod(node, mod) {
  if (node?.content?.mod === mod) return node;
  for (const child of node?.children ?? []) {
    const found = findMod(child, mod);
    if (found) return found;
  }
  return null;
}
// The Projects page is on when the stage shows the board child with no one project's board in it.
function projectsShown() {
  return find(layout(), STAGE)?.active === BOARD && !shared('pm-dash')?.project;
}
export default class PmNav extends View {
  init(_props, cx) {
    this.counts = null;
    this.localState = { pms: [], tasks: [], events: [] }; this.remoteStates = {};
    this.error = '';
    this.setupAvailable = false;
    this.boardShown = false;
    // The page the Projects page covers (pageBefore), kept while the Projects page is up.
    this.covered = null;
    this.awayShown = false;
    this.focus = null;
    this.compact = false;
    this.width = 120;
    this.checkSetup(cx);
    this.ledgerHome = '';
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
    this.refreshRemote(cx);
    cx.timer.every(15000, cx => this.refreshRemote(cx));
    cx.timer.every(10000, cx => this.refresh(cx));
    cx.spawn(async cx => {
      for (;;) {
        const command = await nextCommand();
        if (command === 'setup-changed') this.checkSetup(cx);
        // pm-dash's Esc on the Projects page: what a second Projects click does.
        else if (command === 'back' && projectsShown()) this.toggleBoard();
      }
    });
  }
  // Watch <ledger home>/tasks; a different home arms a new watcher and the old one stops at its next wake.
  setLedgerHome(path, cx) {
    if (typeof path !== 'string' || !path || path === this.ledgerHome) return;
    this.ledgerHome = path;
    cx.spawn(async cx => {
      try {
        while (this.ledgerHome === path) {
          await watchFolder(path + '/tasks');
          if (this.ledgerHome === path) this.refresh(cx);
        }
      } catch (_) { /* The 10-second fallback also covers a missing tasks directory. */ }
    });
  }
  // Resize this block to the entry row (layouts made before it held a "PM" heading above).
  fit() {
    const node = findMod(layout(), 'pm-nav');
    if (!node?.size || node.size.px === HEIGHT || this.asked === node.size.px) return;
    this.asked = node.size.px;
    run('layout.resize', { id: node.id, px: HEIGHT });
  }
  checkSetup(cx) {
    if (this.checkingSetup) { this.setupAgain = true; return; }
    this.checkingSetup = true;
    cx.spawn(async cx => {
      try {
        const result = await execPython(exec, [appHome() + SETUP_SCRIPT, '--status', '--claude-home', home() + '/.claude']);
        if (result.code !== 0) throw new Error(result.stderr || `setup.py: ${result.code}`);
        const status = JSON.parse(result.stdout);
        // Any agent with the skill counts; the board itself offers Set up or Update.
        this.setupAvailable = Array.isArray(status.summary?.installed) && status.summary.installed.length > 0;
      } catch (_) { this.setupAvailable = false; }
      finally {
        this.checkingSetup = false; cx.notify();
        if (this.setupAgain) { this.setupAgain = false; this.checkSetup(cx); }
      }
    });
  }
  refresh(cx) {
    if (this.loading) { this.again = true; return; }
    this.loading = true;
    cx.spawn(async cx => {
      try {
        const r = await execPython(exec, [appHome() + PM_SCRIPT, 'state']);
        if (r.code !== 0) throw new Error(r.stderr || `pm.py: ${r.code}`);
        const state = JSON.parse(r.stdout);
        if (!Array.isArray(state.pms) || !Array.isArray(state.tasks)) throw new Error('state is missing pms/tasks arrays');
        this.localState = { ...state, events: state.events || [] };
        this.setLedgerHome(state.home, cx);
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
    const startedNow = Date.now();
    if (this.remoteLoading && startedNow - (this.remoteLoadingAt || 0) < 18000) return;
    this.remoteLoading = true;
    this.remoteLoadingAt = startedNow;
    cx.spawn(async cx => {
      try {
        const result = await exec('hc', ['machine', 'ls', '--json'], { timeout: 6000 });
        if (result.code !== 0) return;
        const listing = JSON.parse(result.stdout);
        const machines = Array.isArray(listing) ? listing : listing?.machines;
        if (!Array.isArray(machines)) return;
        const names = [...new Set(machines.filter(m => m.state === 'connected' && typeof m.name === 'string' && m.name).map(m => m.name))];
        // Disconnects remove rows; a transient read failure retains the last good snapshot.
        for (const name of Object.keys(this.remoteStates)) if (!names.includes(name)) delete this.remoteStates[name];
        await Promise.all(names.map(async name => {
          try {
            const r = await exec('hc', ['exec', '--on', name, remoteStateCommand()], { timeout: 10000 });
            if (r.code !== 0) return;
            const state = JSON.parse(r.stdout);
            if (['pms', 'tasks', 'events'].every(k => Array.isArray(state[k]))) this.remoteStates[name] = state;
          } catch (_) { /* One unavailable machine must not interrupt the others. */ }
        }));
        this.publish(cx);
        try {
          if (this.setupAvailable && this.ledgerHome) {
            await execPython(exec, ['-c', WRITE_REMOTE_CACHE, this.ledgerHome + '/cache/remote-states.json',
              JSON.stringify(this.remoteStates), String(Date.now())], { timeout: 4000 });
          }
        } catch (_) { /* Cache writes are best effort; the sidebar is already updated. */ }
      } catch (_) { /* Discovery failures leave the last good board intact. */ }
      finally { if (this.remoteLoadingAt === startedNow) this.remoteLoading = false; }
    });
  }
  publish(cx) {
    this.counts = summary(this.localState, this.remoteStates);
    this.lang = this.localState.lang;
    cx.notify();
  }
  // The Projects entry: open the Projects page, or from it go back to the page it covered.
  toggleBoard() {
    const current = find(layout(), STAGE), page = shared('pm-dash') || {};
    if (!current) { run('mod.open', { name: 'pm-dash' }); return; }
    if (projectsShown()) {
      // Back to the page it covered: a project's conversation or board, the workspace otherwise.
      const back = pageBack(this.covered, (current.children ?? []).map(c => c.id), projectKeys(this.localState, this.remoteStates));
      this.covered = null;
      if (back.child === PROJECT) setShared(PROJECT, back.machine ? { pm: back.pm, machine: back.machine } : { pm: back.pm });
      if (back.child === BOARD) setShared('pm-dash', { view: 'board', project: back.pm });
      run('layout.select', { stack: STAGE, child: back.child });
      return;
    }
    // From a project's board or elsewhere: the Projects page, as list or board as it was last.
    this.covered = pageBefore(current.active, shared(PROJECT), page);
    setShared('pm-dash', { view: page.view === 'board' ? 'board' : 'list', project: '' });
    run('layout.select', { stack: STAGE, child: BOARD });
  }
  render(cx) {
    const textFor = (key, ...args) => word(this.lang, key, ...args);
    const t = theme(), stage = find(layout(), STAGE);
    // Away: the board or a project view (pm-project) covers the workspace; a later focus change returns to it.
    // The Projects page is on when the board child shows it, not one project's board.
    const shown = projectsShown();
    const away = Boolean(stage?.active) && stage.active !== WORK;
    const curFocused = focused();
    const focus = focusKey(curFocused);
    const overlayFocus = away && isOverlayTerminalFocus(curFocused, shared('pm-project-win-terminals'));
    this.fit();
    const returnToWork = shouldReturnToWork(away, this.awayShown, focus, this.focus, { overlayFocus });
    if (shown !== this.boardShown) cx.timer.after(0, cx => this.checkSetup(cx));
    // Opening the board establishes a fresh baseline. Only later navigation
    // returns to work; live layout/focus data already triggers render, no polling.
    // Re-selecting the same item has no observable focus change. nextCommand()
    // only receives commands addressed to this mod, not other sidebar clicks.
    // Leaving the Projects page by any way ends what it covered; a later opening records afresh.
    if (this.boardShown && !shown) this.covered = null;
    this.boardShown = shown;
    this.awayShown = away;
    // Keep the last non-overlay workspace focus as baseline so closing a floating agent
    // terminal window (which restores focus to the underlying pane) does not return to work.
    if (!overlayFocus) this.focus = focus;
    if (returnToWork) run('layout.select', { stack: STAGE, child: WORK });
    const on = shown && !returnToWork, n = this.setupAvailable ? this.counts : null;
    const error = this.setupAvailable ? this.error : '';
    const text = !this.setupAvailable ? textFor('setup') : n ? textFor('summary', n.projects, n.active) : error ? textFor('readError') : textFor('loading');
    const detail = `${textFor('board')} · ${text}${n?.blocked ? ` · ${textFor('blocked', n.blocked)}` : ''}`;
    const plus = size => h_flex().id('pm-new-project').size(size).flex_none().rounded(7).items_center().justify_center()
      .cursor_pointer().text_color(t.muted).hover(s => s.bg(t.hover).text_color(t.foreground))
      .tooltip(textFor('newProject')).accessibility_label(textFor('newProject'))
      .on_click((_e, cx) => { cx.stop_propagation(); openOverlay(NEW_DIALOG); })
      .child(svg('mods/pm-nav/plus.svg').size(15));
    const root = v_flex().id('pm-nav-root').size_full().min_w(0).min_h(0).overflow_hidden()
      .bg(t.chrome).text_size(13).text_color(t.foreground)
      .on_size_change((size, cx) => {
        const compact = size.width < 120;
        if (size.width !== this.width || compact !== this.compact) {
          this.width = size.width; this.compact = compact; cx.notify();
        }
      });
    if (this.compact) {
      return root.items_center().justify_center()
        .child(h_flex().id('pm-board-link').relative().size(32).flex_none().rounded(8).items_center().justify_center()
          .cursor_pointer().when(on, el => el.bg(t.selected)).when(!on, el => el.hover(s => s.bg(t.hover)))
          .tooltip(`${detail}${error ? `\n${textFor('retry', error)}` : ''}`)
          .on_click(() => this.toggleBoard())
          .child(svg('mods/pm-nav/grid.svg').size(18).text_color(t.foreground))
          .when(Boolean(n?.blocked), el => el.child(div().absolute().top(1).right(1).size(6).rounded(3).bg(t.blocked))));
    }
    // Icon, title, the count, "+": the count gets what is left (16px icon, gaps, 24px "+", padding).
    const room = this.width - 20 - 16 - 8 - estimateTextWidth(textFor('board'), 13) - 8 - 24 - 14 - (error && n ? 10 : 0);
    const count = n ? navText(n, this.lang, room) : text;
    return root.px(10).py(3)
      .child(h_flex().id('pm-board-link').h(34).pl(10).pr(5).gap(8).rounded(8).items_center()
        .cursor_pointer().when(on, el => el.bg(t.selected)).when(!on, el => el.hover(s => s.bg(t.hover)))
        .tooltip(`${detail}${error ? `\n${textFor('retry', error)}` : ''}`)
        .on_click(() => this.toggleBoard())
        .child(svg('mods/pm-nav/grid.svg').size(16).flex_none().text_color(t.foreground))
        .child(div().flex_none().whitespace_nowrap().font_semibold().child(textFor('board')))
        .child(h_flex().flex_1().min_w(0).justify_end().items_center().text_size(12).text_color(t.dim)
          .child(div().flex_none().whitespace_nowrap().child(count))
          .when(Boolean(error && n), el => el.child(div().flex_none().ml(3).text_color(t.blocked).child('!'))))
        .child(plus(24)));
  }
}
