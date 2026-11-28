import { View, div, svg } from 'gpui-kit';
import { v_flex, h_flex } from 'gpui-base';
import { theme, home, appHome, exec, readTextFile, writeTextFile, watchFolder, nextCommand, layout, focused, run, shared, setShared, openOverlay, window } from 'herdr';
import { summary, navText, estimateTextWidth, focusKey, isOverlayTerminalFocus, shouldReturnToWork, initialStageChild, pageBefore, pageBack, projectKeys, ENSURE_DIR_PY, remoteCacheSig, WRITE_REMOTE_CACHE, LEDGER_HOME_SH, remoteStateCommand, needsRailUnfold, navHeight, shouldWriteRemoteCache, showsSummary } from './model.js';
import { execPython } from './python.js';
import { createErrorLogger } from './error_log.js';

// The sidebar deliberately depends on the original pm-dash bundle.
const PM_SCRIPT = '/mods/pm-dash/skill/scripts/pm.py';
const SETUP_SCRIPT = '/mods/pm-dash/setup.py';
const STAGE = 'pm-stage', BOARD = 'pm-board', WORK = 'work', PROJECT = 'pm-project';
// The block holds the entry row alone; it fits itself to that, as pm-list does.
const HEIGHT = 40;
// pm-dash's new-project dialog (its own overlay mode).
const NEW_DIALOG = { mod: 'pm-dash', props: { dialog: 'new' }, kind: 'dialog', width: 560, height: 580 };

const STRINGS = {
  en: {
    summary: (p, n) => `${p} ${p === 1 ? 'project' : 'projects'} · ${n} in progress`,
    readError: 'Read failed', loading: 'Loading…', blocked: n => `${n} need you`,
    retry: error => `Could not read summary. Retrying in 10 seconds: ${error}`, board: 'Projects',
    setup: 'Set up', newProject: 'New project', expandSidebar: 'Expand sidebar',
  },
  zh: {
    summary: (p, n) => `${p} 项目 · ${n} 进行中`,
    readError: '读取失败', loading: '读取中…', blocked: n => `${n} 等你`,
    retry: error => `摘要读取失败，10 秒后重试：${error}`, board: 'Projects',
    setup: '未设置', newProject: '新建项目', expandSidebar: '展开侧栏',
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
    this.stageRestored = false;
    this.restoringStage = null;
    this.stageSeen = null;
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
        else if (command === 'refresh-remote') this.refreshRemote(cx);
        // pm-dash's Esc on the Projects page: what a second Projects click does.
        else if (command === 'back' && projectsShown()) this.toggleBoard();
      }
    });
  }
  // Watch <ledger home>/tasks and /pms; a different home arms new watchers and the old ones stop at their next wake.
  setLedgerHome(path, cx) {
    if (typeof path !== 'string' || !path || path === this.ledgerHome) return;
    this.ledgerHome = path;
    this.remoteCacheExists = undefined;
    if (Object.keys(this.remoteStates || {}).length > 0) {
      cx.spawn(async () => { await this.syncRemoteCache(); });
    }
    for (const sub of ['/tasks', '/pms']) {
      cx.spawn(async cx => {
        try {
          while (this.ledgerHome === path) {
            await watchFolder(path + sub);
            if (this.ledgerHome === path) this.refresh(cx);
          }
        } catch (_) { /* The 10-second fallback also covers a missing directory. */ }
      });
    }
  }
  // Resize this block to the entry row (or taller on macOS collapsed rail when showing `»` unfold above Projects).
  fit(showUnfold = false) {
    const node = findMod(layout(), 'pm-nav');
    const want = navHeight(this.compact, showUnfold);
    const ask = `${node?.size?.px}>${want}`;
    if (!node?.size || node.size.px === want || this.asked === ask) return;
    this.asked = ask;
    run('layout.resize', { id: node.id, px: want });
  }
  unfoldSidebar() {
    setShared('sidebar.collapsed', false);
    run('layout.resize', { id: 'sidebar', px: shared('sidebar.width') ?? 268 });
  }
  logModError(source, error) {
    if (typeof createErrorLogger !== 'function') return;
    if (!this.errorLogger) {
      this.errorLogger = createErrorLogger({
        mod: 'pm-nav',
        exec,
        getLedgerHome: () => this.ledgerHome || (home() + '/.dudu'),
      });
    }
    this.errorLogger.record(source, error);
  }
  checkSetup(cx) {
    if (this.checkingSetup) { this.setupAgain = true; return; }
    this.checkingSetup = true;
    const wasAvailable = this.setupAvailable;
    cx.spawn(async cx => {
      try {
        const result = await execPython(exec, [appHome() + SETUP_SCRIPT, '--status', '--claude-home', home() + '/.claude']);
        if (result.code !== 0) throw new Error(result.stderr || `setup.py: ${result.code}`);
        const status = JSON.parse(result.stdout);
        // Any agent with the skill counts; the board itself offers Set up or Update.
        this.setupAvailable = Array.isArray(status.summary?.installed) && status.summary.installed.length > 0;
        if (!wasAvailable && this.setupAvailable && Object.keys(this.remoteStates || {}).length > 0) {
          await this.syncRemoteCache();
        }
      } catch (e) { this.setupAvailable = false; this.logModError('checkSetup', e); }
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
      } catch (e) { this.error = String(e); this.logModError('refresh', e); }
      finally {
        this.loading = false;
        cx.notify();
        if (this.again) { this.again = false; this.refresh(cx); }
      }
    });
  }
  async writeRemoteCache(at = Date.now()) {
    if (!this.ledgerHome) return false;
    const base = String(this.ledgerHome).trim().replace(/[\\/]+$/, '');
    if (!base) return false;
    const dir = `${base}/cache`;
    const cachePath = `${dir}/remote-states.json`;
    if (!shouldWriteRemoteCache(this.setupAvailable, this.remoteStates, this.remoteCacheExists)) {
      // Before Set up with nothing remote: write nothing, unless a cache from earlier needs emptying.
      if (this.remoteCacheExists === undefined && typeof readTextFile === 'function') {
        this.remoteCacheExists = (await readTextFile(cachePath).catch(() => null)) !== null;
      }
      if (!this.remoteCacheExists) return false;
    }
    this.remoteCacheExists = true;
    const payload = JSON.stringify(this.remoteStates || {});
    if (typeof writeTextFile === 'function') {
      const tmpPath = `${dir}/.remote-states-in-${at}-${Math.random().toString(36).slice(2, 8)}.tmp`;
      try {
        await writeTextFile(tmpPath, payload, null);
      } catch (_) {
        const mk = await execPython(exec, ['-c', ENSURE_DIR_PY, dir], { timeout: 4000 });
        if (mk.code !== 0) throw new Error((mk.stderr || mk.stdout || `mkdir: ${mk.code}`).trim());
        await writeTextFile(tmpPath, payload, null);
      }
      const r = await execPython(exec, ['-c', WRITE_REMOTE_CACHE, cachePath, '--from-file', tmpPath, String(at)], { timeout: 8000 });
      if (r.code !== 0) throw new Error((r.stderr || r.stdout || `writeRemoteCache: ${r.code}`).trim());
      return true;
    }
    const r = await execPython(exec, ['-c', WRITE_REMOTE_CACHE, cachePath, payload, String(at)], { timeout: 8000 });
    if (r.code !== 0) throw new Error((r.stderr || r.stdout || `writeRemoteCache: ${r.code}`).trim());
    return true;
  }
  async syncRemoteCache() {
    try {
      if (await this.writeRemoteCache()) {
        if (typeof setShared === 'function' && typeof remoteCacheSig === 'function') {
          const sig = remoteCacheSig(this.remoteStates);
          if (typeof shared !== 'function' || shared('pm-remote-cache') !== sig) {
            setShared('pm-remote-cache', sig);
          }
        }
      }
    } catch (e) {
      this.logModError('writeRemoteCache', e);
    }
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
        await this.syncRemoteCache();
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
    const t = theme(), curLayout = layout(), stage = find(curLayout, STAGE);
    const showUnfold = needsRailUnfold(curLayout, typeof window === 'function' ? window() : null);
    let restore = null;
    if (stage && !this.stageRestored) {
      this.stageRestored = true;
      this.stageSeen = stage.active ?? null;
      restore = initialStageChild(stage, shared(STAGE), shared(PROJECT));
      if (restore) {
        this.restoringStage = restore;
        run('layout.select', { stack: STAGE, child: restore });
      }
    } else if (stage && this.restoringStage) {
      if (stage.active === this.restoringStage || stage.active !== this.stageSeen) {
        this.restoringStage = null;
      }
    }
    // Away: the board or a project view (pm-project) covers the workspace; a later focus change returns to it.
    // The Projects page is on when the board child shows it, not one project's board.
    const shown = projectsShown();
    const away = Boolean(stage?.active) && stage.active !== WORK;
    const curFocused = focused();
    const focus = focusKey(curFocused);
    const overlayFocus = away && isOverlayTerminalFocus(curFocused, shared('pm-project-win-terminals'));
    this.fit(showUnfold);
    const returnToWork = !restore && !this.restoringStage && shouldReturnToWork(away, this.awayShown, focus, this.focus, { overlayFocus });
    if (shown !== this.boardShown) cx.timer.after(0, cx => this.checkSetup(cx));
    // Opening the board establishes a fresh baseline. Only later navigation
    // returns to work; live layout/focus data already triggers render, no polling.
    // Re-selecting the same item has no observable focus change. nextCommand()
    // only receives commands addressed to this mod, not other sidebar clicks.
    // Leaving the Projects page by any way ends what it covered; a later opening records afresh.
    if (this.boardShown && !shown) this.covered = null;
    this.boardShown = shown;
    this.awayShown = restore || this.restoringStage ? false : away;
    // Keep the last non-overlay workspace focus as baseline so closing a floating agent
    // terminal window (which restores focus to the underlying pane) does not return to work.
    if (!overlayFocus) this.focus = focus;
    if (returnToWork) run('layout.select', { stack: STAGE, child: WORK });
    if (stage && !this.restoringStage) {
      const nextStage = returnToWork ? WORK : stage.active;
      if (nextStage && shared(STAGE)?.child !== nextStage) setShared(STAGE, { child: nextStage });
      this.stageSeen = stage.active ?? null;
    }
    const on = shown && !returnToWork, counted = showsSummary(this.setupAvailable, this.counts);
    const n = counted ? this.counts : null;
    const error = counted || this.setupAvailable ? this.error : '';
    const text = !counted && !this.setupAvailable ? textFor('setup') : n ? textFor('summary', n.projects, n.active) : error ? textFor('readError') : textFor('loading');
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
      const unfoldBtn = showUnfold
        ? h_flex().id('pm-sidebar-unfold').w(32).h(26).flex_none().rounded(7).items_center().justify_center()
            .cursor_pointer().text_size(13).text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
            .tooltip(textFor('expandSidebar')).accessibility_label(textFor('expandSidebar'))
            .on_click(() => this.unfoldSidebar())
            .child('»')
        : null;
      return root.items_center().justify_center().gap(showUnfold ? 4 : 0)
        .when(Boolean(unfoldBtn), el => el.child(unfoldBtn))
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
