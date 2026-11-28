import { View, div, svg, image } from 'gpui-kit';
import { v_flex, h_flex, Popup } from 'gpui-base';
import { theme, home, appHome, exec, readTextFile, watchFolder, layout, run, terminals, agents, panes, spaces, shared, setShared, openOverlay, keys, window } from 'herdr';
import { foldReviews, allPmRows, splitArchived, archivedDay, remotePmStates, track, age, listHeight, listSizeSpec, herdrListsState, herdrListsBadge, herdrListsShortcut, drawerTipParts, HERDR_LISTS_ID, underNav, LEDGER_HOME_SH, focusPlan, opensProject, projectShared, contextShort, contextLabel, pmContextLevel, pmContextTip } from './model.js';
import { execPython } from './python.js';

// Like pm-nav, the list reads the ledger through the original pm-dash bundle.
const PM_SCRIPT = '/mods/pm-dash/skill/scripts/pm.py';
// A PM's row opens its project view (pm-project), named through shared('pm-project') (projectShared).
const STAGE = 'pm-stage', WORK = 'work', PROJECT = 'pm-project', BOARD = 'pm-board';
// Threads archiving would pause (pm-dash's archiveThreads): the popup's height counts them.
const OPEN = ['blocked', 'in_progress', 'review', 'proposed'];
const SPINNER = 'mods/workspace-chrome/spinner.svg', DUDU = 'mods/pm-list/dudu.svg';

const STRINGS = {
  en: { blocked: 'Needs you', working: 'Working', done: 'Done', idle: 'Idle', unknown: 'Status unknown: it reports none',
    unregistered: 'Not in this ledger. Click shows its terminal.',
    away: 'Not in the desktop app. Start it here, then run pm.py claim.',
    project: "Not in the desktop app. Click opens the project's space.", readError: 'Could not read the ledger',
    view: "Click opens the project's conversation", notDesktop: 'Not in the desktop app',
    rename: 'Rename project',
    archive: 'Archive project', archived: n => `Archived ${n}`, archivedRow: 'Archived. Click shows the archived projects',
    spacesAndAgents: 'Spaces & Agents', hideSpacesAgents: 'Hide' },
  zh: { blocked: '等你', working: '工作中', done: '已完成', idle: '空闲', unknown: '状态未知：它不上报状态',
    unregistered: '台账里没有它。点击打开它的终端。',
    away: '这个 PM 不在桌面里。在桌面里启动它，再运行 pm.py claim。',
    project: '这个 PM 不在桌面里。点击打开项目的 space。', readError: '台账读取失败',
    view: '点击打开这个项目的对话', notDesktop: '这个 PM 不在桌面里',
    rename: '重命名项目',
    archive: '归档项目', archived: n => `已归档 ${n}`, archivedRow: '已归档。点击查看已归档的项目',
    spacesAndAgents: 'Spaces & Agents', hideSpacesAgents: '收起' },
};
const word = (lang, key, ...args) => {
  const value = STRINGS[lang === 'zh' ? 'zh' : 'en'][key];
  return typeof value === 'function' ? value(...args) : value;
};

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
    this.loading = false; this.again = false;
    this.compact = false; this.narrow = false;
    this.ledgerHome = '';
    this.watchingCache = '';
    this.remoteSig = undefined;
    this.hover = null;
    this.drawerHover = false;
    try { this.folded = localStorage.getItem('archived-open') !== 'true'; } catch (_) { this.folded = true; }
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
  // Other machines: what pm-nav last read over hc (it writes the cache, this only reads).
  async readRemoteCache(path = this.ledgerHome) {
    const base = String(path || '').trim().replace(/[\\/]+$/, '');
    if (!base) return;
    const cached = await readTextFile(base + '/cache/remote-states.json').catch(() => null);
    this.remote = remotePmStates(cached);
  }
  // Watch <ledger home>/cache so pm-nav's remote-states.json updates reach the list right away.
  watchCache(path, cx) {
    const base = String(path || '').trim().replace(/[\\/]+$/, '');
    if (!base || this.watchingCache === base || typeof watchFolder !== 'function') return;
    this.watchingCache = base;
    cx.spawn(async cx => {
      try {
        while (this.ledgerHome === path && this.watchingCache === base) {
          await watchFolder(base + '/cache');
          if (this.ledgerHome === path) {
            await this.readRemoteCache(path);
            cx.notify();
          }
        }
      } catch (_) { /* Absent cache dir until first write: re-armed on next refresh or remoteSig wake. */ }
      finally { if (this.watchingCache === base) this.watchingCache = ''; }
    });
  }
  // PM records live in <ledger home>/pms; the 10-second read covers a missing folder.
  setLedgerHome(path, cx) {
    if (typeof path !== 'string' || !path || path === this.ledgerHome) return;
    this.ledgerHome = path;
    this.watchingCache = '';
    // Populate remote projects from cache immediately, even before local `pm.py state` returns.
    cx.spawn(async cx => {
      await this.readRemoteCache(path);
      cx.notify();
    });
    this.watchCache(path, cx);
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
        const r = await execPython(exec, [appHome() + PM_SCRIPT, 'state']);
        if (r.code !== 0) throw new Error(r.stderr || `pm.py: ${r.code}`);
        const state = JSON.parse(r.stdout);
        if (!Array.isArray(state.pms)) throw new Error('state is missing the pms array');
        this.state = state;
        this.setLedgerHome(state.home, cx);
        this.error = '';
      } catch (e) { this.error = String(e); }
      finally {
        // Always refresh remote cache even if local `pm.py state` failed so remote projects
        // stay registered instead of falling back to "Not in this ledger".
        const base = this.ledgerHome || home() + '/.dudu';
        await this.readRemoteCache(base);
        if (this.ledgerHome) this.watchCache(this.ledgerHome, cx);
        this.loading = false;
        cx.notify();
        if (this.again) { this.again = false; this.refresh(cx); }
      }
    });
  }
  // The block grows with the list: resize this mod's own layout node to fit.
  // Compared with the node's size now, so a reloaded layout is fitted again;
  // asked once per (size, wanted) pair, so a clamped size does not ask on every render.
  fit(count, header, herdrState = null) {
    const node = find(layout(), n => n.content?.mod === 'pm-list');
    if (!node?.id) return;
    const spec = listSizeSpec(count, this.compact, header, herdrState);
    if ('weight' in spec) {
      const ask = `w:${node.size?.px ?? ''}:${node.size?.weight ?? ''}>${spec.weight}`;
      if ((node.size?.weight === spec.weight && !('px' in (node.size || {}))) || this.asked === ask) return;
      this.asked = ask;
      run('layout.resize', { id: node.id, weight: spec.weight });
      return;
    }
    const px = spec.px, ask = `p:${node.size?.px ?? ''}:${node.size?.weight ?? ''}>${px}`;
    if (node.size?.px === px || this.asked === ask) return;
    this.asked = ask;
    run('layout.resize', { id: node.id, px });
  }
  // A PM opens in the project view when the layout has one, on this computer or another machine
  // (pm-project reads that machine's ledger); only an older layout focuses its terminal.
  viewable(row) {
    return opensProject(row, find(layout(), n => n.id === STAGE));
  }
  open(row) {
    const stage = find(layout(), n => n.id === STAGE);
    if (this.viewable(row)) {
      setShared(PROJECT, projectShared(row));
      if (stage.active !== PROJECT) run('layout.select', { stack: STAGE, child: PROJECT });
      return;
    }
    if (!row.terminal) return;
    const plan = focusPlan(row.terminal.address, terminals(), [...panes().map(p => p.terminal), ...agents().map(a => a.address)]);
    // Nowhere to show it: nothing moves, since showing work would reveal whatever space is active.
    if (!plan.focus) return;
    run('pane.focus', { terminal: plan.focus });
    // Re-clicking the focused PM changes no focus, so pm-nav would leave the board (or a project) up.
    if (stage && stage.active !== WORK) run('layout.select', { stack: STAGE, child: WORK });
    if (plan.peek) run('terminal.peek', { terminal: plan.peek });
  }
  // Renaming opens pm-dash's rename dialog for this local project.
  rename(row) {
    openOverlay({ mod: 'pm-dash', props: { dialog: 'rename', pm: row.key }, kind: 'dialog', width: 420, height: 224 });
  }
  // Archiving asks first: pm-dash's popup, by the pointer, lists the threads it would pause.
  archive(row) {
    const tasks = row.machine ? (this.remote[row.machine]?.tasks || []) : (this.state.tasks || []);
    const pmKey = row.machine && row.key.startsWith(`${row.machine}/`) ? row.key.slice(row.machine.length + 1) : row.key;
    const threads = foldReviews(tasks).filter(t => t.pm === pmKey && OPEN.includes(t.status)).length;
    const props = row.machine ? { dialog: 'archive', pm: row.key, machine: row.machine } : { dialog: 'archive', pm: row.key };
    openOverlay({ mod: 'pm-dash', props, kind: 'popup', width: 340,
      height: (threads ? 250 : 210) + Math.min(6, threads) * 24 });
  }
  // The Projects page's archived list, where a project comes back.
  showArchived() {
    setShared('pm-dash', { view: 'archived', project: '' });
    if (find(layout(), n => n.id === STAGE)) run('layout.select', { stack: STAGE, child: BOARD });
  }
  // A row's status as a mark before its name: spinner, dot or ring; a "?" when the terminal reports none.
  lead(t, status) {
    if (status === 'working') return svg(SPINNER).size(12).mx(1).flex_none().text_color(t.working).spin(900);
    if (status === 'unknown') return div().flex_none().text_size(10.5).font_semibold().text_color(t.dim).child('?');
    const dot = div().flex_none().size(7).mx(3).rounded_full();
    return status === 'blocked' ? dot.bg(t.blocked) : status === 'done' ? dot.bg(t.done) : dot.border(1.5).border_color(t.idle ?? t.dim);
  }
  // The status is a mark, never a word, except the small "needs you" badge.
  mark(t, status, lang) {
    if (status === 'working') return svg(SPINNER).size(12).mx(1).flex_none().text_color(t.working).spin(900);
    if (status === 'unknown') return div().flex_none().w(14).text_size(10.5).font_semibold().text_color(t.dim).child('?');
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
    const remoteSig = typeof shared === 'function' ? shared('pm-remote-cache') : undefined;
    if (remoteSig !== undefined && remoteSig !== this.remoteSig) {
      this.remoteSig = remoteSig;
      if (typeof cx?.timer?.after === 'function') {
        cx.timer.after(0, cx => {
          const base = this.ledgerHome || home() + '/.dudu';
          this.readRemoteCache(base).then(() => {
            if (this.ledgerHome) this.watchCache(this.ledgerHome, cx);
            cx.notify();
          });
        });
      }
    }
    const t = theme(), lang = this.state.lang, now = Date.now(), live = agents(), terms = terminals();
    const all = allPmRows(this.state, this.remote, terms, live), { active: rows, archived } = splitArchived(all);
    const changed = track(this.changed, all, now);
    if (changed !== this.changed) {
      this.changed = changed;
      try { localStorage.setItem('changed', JSON.stringify(changed)); } catch (_) { /* Ages restart from the ledger. */ }
    }
    // Right under pm-nav the PM title above is the list's heading.
    const curLayout = layout();
    const headed = !underNav(curLayout);
    const herdrState = herdrListsState(curLayout);
    const herdrBadge = herdrState.present ? herdrListsBadge(typeof spaces === 'function' ? spaces() : [], live) : null;
    // The archived fold is a row of its own, and its projects are rows while it is open (not on the rail).
    const extra = this.compact || !archived.length ? 0 : 1 + (this.folded ? 0 : archived.length);
    this.fit(rows.length + extra, headed, herdrState);
    // The rail: the same rule as pm-nav, by this block's own width.
    const root = v_flex().id('pm-list-root').size_full().min_w(0).min_h(0).overflow_hidden()
      .bg(t.chrome).text_size(13).text_color(t.foreground)
      .on_size_change((size, cx) => {
        const compact = size.width < 120, narrow = size.width > 0 && size.width < 220;
        if (compact !== this.compact || narrow !== this.narrow) {
          this.compact = compact; this.narrow = narrow; cx.notify();
        }
      });
    // A project shows in its conversation (pm-project) or on its own board (pm-dash scoped to it).
    const stage = find(curLayout, n => n.id === STAGE);
    const viewing = stage?.active === PROJECT ? shared(PROJECT)?.pm : stage?.active === BOARD ? shared('pm-dash')?.project || null : null;
    const tip = row => [row.machine ? `${row.label} · ${row.machine}` : row.label, word(lang, row.status),
      pmContextTip(row.contextTokens, lang, row.compactTokens ?? row.rotateTokens),
      row.unregistered ? word(lang, 'unregistered')
        : this.viewable(row) ? [!row.exact && word(lang, 'notDesktop'), word(lang, 'view')].filter(Boolean).join('\n')
        : !row.exact && word(lang, row.terminal ? 'project' : 'away')].filter(Boolean).join('\n');
    // Keys match across machines: a remote PM's is "<machine>/<name>" here, in pm-project and on the board.
    const focused = row => viewing ? row.key === viewing
      : row.exact && live.some(a => a.address === row.terminal.address && a.focused);
    const base = (row, el) => el.id(`pm-${row.key}`).flex_none().items_center()
      .when(focused(row), el => el.bg(t.selected)).hover(s => s.bg(t.hover))
      .when(Boolean(row.terminal) || this.viewable(row), el => el.cursor_pointer().on_click(() => this.open(row)))
      .tooltip(tip(row));
    const drawerDotColor = herdrBadge?.tone === 'blocked' ? t.blocked : (t.working ?? t.ansi2 ?? t.accent);
    const activeLayout = typeof shared === 'function' ? String(shared('layout') || 'dudu') : 'dudu';
    const platform = typeof window === 'function' ? (window()?.platform || 'macos') : 'macos';
    const drawerShortcut = herdrState.present
      ? herdrListsShortcut(typeof keys === 'function' ? keys() : [], activeLayout, platform)
      : '';
    const tipParts = drawerTipParts({ hidden: herdrState.hidden, badge: herdrBadge, lang, compact: this.compact, shortcut: drawerShortcut });
    const onDrawerHover = (over, cx) => {
      if (this.drawerHover !== over) { this.drawerHover = over; cx.notify(); }
    };
    const toggleDrawer = (_e, cx) => {
      this.drawerHover = false;
      run('layout.toggle', { id: HERDR_LISTS_ID });
      cx?.notify?.();
    };
    const drawerTipAnchor = () => {
      if (!this.drawerHover) return null;
      const tipBg = [t.popover, t.raised, t.surface].find(c => c && c !== t.chrome) || t.raised;
      const kbdBg = [t.hover, t.surface, t.chrome].find(c => c && c !== tipBg) || t.hover;
      const tipCard = h_flex().id('pm-herdr-lists-tip-card').flex_none().items_center().gap(8)
        .px(9).py(5).rounded(8).bg(tipBg).shadow_md()
        .child(h_flex().flex_none().items_center().gap(5).text_size(11.5).whitespace_nowrap()
          .child(div().id('pm-herdr-lists-tip-text').text_color(t.foreground).child(tipParts.text))
          .when(Boolean(tipParts.activeText), el => el
            .child(div().text_color(t.dim).child('·'))
            .child(div().id('pm-herdr-lists-tip-active').font_medium().text_color(drawerDotColor).child(tipParts.activeText))))
        .when(Boolean(tipParts.shortcut), el => el
          .child(h_flex().id('pm-herdr-lists-shortcut').flex_none().h(18).px(5).rounded(4)
            .items_center().justify_center().bg(kbdBg)
            .text_size(10.5).font_medium().text_color(t.muted).whitespace_nowrap()
            .child(tipParts.shortcut)));
      return div().id('pm-herdr-lists-tip-anchor').absolute().left(this.compact ? 6 : 8).top(-4).w(0).h(0)
        .child(Popup.new('pm-herdr-lists-tip', div().w(0).h(0)).anchor('bottom_left').content(tipCard));
    };
    if (this.compact) {
      const tipAnchor = herdrState.present ? drawerTipAnchor() : null;
      return root.py(6)
        .child(v_flex().id('pm-list-rows').flex_1().min_h(0).overflow_y_scrollbar().children(rows.map(row =>
          base(row, h_flex()).h(28).gap(4).justify_center()
            .child(this.agentIcon(t, row.program))
            .child(h_flex().w(14).flex_none().justify_center().child(this.mark(t, row.status, lang))))))
        .when(herdrState.present, el => el.child(h_flex().relative().pt(4).flex_none().justify_center()
          .child(h_flex().id('pm-herdr-lists-toggle').relative().w(32).h(24).rounded(6).items_center().justify_center()
            .cursor_pointer().text_color(this.drawerHover || !herdrState.hidden ? t.foreground : t.dim)
            .when(!herdrState.hidden, d => d.bg(t.raised))
            .when(this.drawerHover, d => d.bg(t.hover))
            .hover(s => s.bg(t.hover).text_color(t.foreground))
            .on_hover(onDrawerHover)
            .accessibility_label(tipParts.a11y)
            .on_click(toggleDrawer)
            .child(svg(herdrState.hidden ? 'mods/pm-list/chevron.svg' : 'mods/pm-list/chevron-down.svg').size(11).flex_none())
            .when(herdrState.hidden && Boolean(herdrBadge?.active), d => d.child(div().absolute().top(3).right(4).size(5).rounded_full().bg(drawerDotColor))))
          .when(Boolean(tipAnchor), d => d.child(tipAnchor))));
    }
    const header = h_flex().px(16).pt(8).h(30).flex_none().gap(6).items_center().text_size(11).font_medium().text_color(t.dim)
      .child('PM').child(String(rows.length))
      .when(Boolean(this.error), el => el.child(div().id('pm-list-error').text_color(t.blocked)
        .tooltip(`${word(lang, 'readError')}: ${this.error}`).child('!')));
    const hovered = row => this.hover === row.key;
    const onHover = row => (over, cx) => {
      if (over) this.hover = row.key; else if (this.hover === row.key) this.hover = null;
      cx.notify();
    };
    const list = v_flex().id('pm-list-rows').flex_1().min_h(0).px(8).pb(rows.length || extra ? 6 : 0).overflow_y_scrollbar()
      .children(rows.map(row => {
        const at = this.changed[row.key]?.at, local = !row.machine;
        const canAct = !row.unregistered && hovered(row);
        const ctxLevel = pmContextLevel(row.contextTokens, row.compactTokens ?? row.rotateTokens);
        const ctxColor = ctxLevel === 'over' || ctxLevel === 'near' ? (t.ansi3 || t.accent || t.dim) : t.dim;
        const shortCtx = Boolean(this.narrow) || Boolean(row.machine) || row.waiting > 0;
        const ctxText = shortCtx ? contextShort(row.contextTokens) : contextLabel(row.contextTokens, lang);
        return base(row, h_flex()).px(8).h(30).rounded(8).gap(9).on_hover(onHover(row))
          .child(h_flex().w(14).flex_none().justify_center().child(this.lead(t, row.status)))
          .child(div().flex_1().min_w(0).truncate().text_color(['idle', 'unknown'].includes(row.status) ? t.muted : t.foreground).child(row.label))
          .when(Boolean(row.machine), el => el.child(div().flex_none().text_size(10).text_color(t.dim).child(row.machine)))
          .when(row.waiting > 0, el => el.child(h_flex().flex_none().min_w(18).h(18).px(5).rounded(9).items_center()
            .justify_center().bg(t.blocked + '2e').text_color(t.blocked).text_size(11).font_semibold().child(String(row.waiting))))
          .when(Boolean(ctxText) && !canAct, el => el.child(div().id(`pm-context-${row.key}`).flex_none()
            .text_size(11).text_color(ctxColor).child(ctxText)))
          // Pointing at a registered project offers archive (and rename on local) in place of the time.
          .when(canAct, el => el.child(h_flex().gap(2).flex_none().items_center()
            .when(local, el2 => el2.child(h_flex().id(`rename-${row.key}`).size(22).flex_none().rounded(6).items_center()
              .justify_center().cursor_pointer().text_color(t.muted).bg(t.raised).hover(s => s.text_color(t.foreground))
              .tooltip(word(lang, 'rename')).accessibility_label(word(lang, 'rename'))
              .on_click((_e, cx) => { cx.stop_propagation(); this.rename(row); })
              .child(svg('mods/pm-list/pencil.svg').size(12))))
            .child(h_flex().id(`archive-${row.key}`).size(22).flex_none().rounded(6).items_center()
              .justify_center().cursor_pointer().text_color(t.muted).bg(t.raised).hover(s => s.text_color(t.foreground))
              .tooltip(word(lang, 'archive')).accessibility_label(word(lang, 'archive'))
              .on_click((_e, cx) => { cx.stop_propagation(); this.archive(row); })
              .child(svg('mods/pm-list/archive.svg').size(13)))))
          .when(Boolean(at) && !canAct, el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(age(now - at, lang))));
      }))
      .when(archived.length > 0, el => el.child(h_flex().id('pm-archived-fold').px(8).h(30).gap(6).rounded(8).items_center()
        .cursor_pointer().text_size(12).text_color(t.dim).hover(s => s.text_color(t.foreground))
        .on_click((_e, cx) => {
          this.folded = !this.folded;
          try { localStorage.setItem('archived-open', String(!this.folded)); } catch (_) { /* Folded next time. */ }
          cx.notify();
        })
        .child(svg(this.folded ? 'mods/pm-list/chevron.svg' : 'mods/pm-list/chevron-down.svg').size(12).flex_none())
        .child(word(lang, 'archived', archived.length))))
      .when(archived.length > 0 && !this.folded, el => el.children(archived.map(row => h_flex().id(`pm-archived-${row.key}`)
        .px(8).h(30).gap(9).rounded(8).items_center().cursor_pointer().text_color(t.muted).hover(s => s.bg(t.hover))
        .tooltip(word(lang, 'archivedRow')).on_click(() => this.showArchived())
        .child(h_flex().w(14).flex_none().justify_center().child(svg('mods/pm-list/archive.svg').size(13).text_color(t.dim)))
        .child(div().flex_1().min_w(0).truncate().child(row.label))
        .child(div().flex_none().text_size(11).text_color(t.dim).child(archivedDay(row.archived))))));
    const drawerActive = this.drawerHover || !herdrState.hidden;
    const tipAnchor = herdrState.present ? drawerTipAnchor() : null;
    const drawerRow = herdrState.present
      ? div().relative().px(8).pt(2).pb(6).flex_none()
          .child(h_flex().id('pm-herdr-lists-toggle').h(30).px(8).gap(7).rounded(8).items_center().cursor_pointer()
            .when(!herdrState.hidden, el => el.bg(this.drawerHover ? t.hover : t.raised))
            .when(herdrState.hidden && this.drawerHover, el => el.bg(t.hover))
            .hover(s => s.bg(t.hover))
            .on_hover(onDrawerHover)
            .accessibility_label(tipParts.a11y)
            .on_click(toggleDrawer)
            .child(svg(herdrState.hidden ? 'mods/pm-list/chevron.svg' : 'mods/pm-list/chevron-down.svg')
              .size(11).flex_none().text_color(drawerActive ? t.foreground : t.dim))
            .child(div().flex_1().min_w(0).truncate().text_size(12).font_medium()
              .text_color(drawerActive ? t.foreground : t.muted).child(word(lang, 'spacesAndAgents')))
            .when(herdrState.hidden && Boolean(herdrBadge?.total), el => el
              .child(div().id('pm-herdr-lists-count').flex_none().text_size(11).text_color(this.drawerHover ? t.muted : t.dim).child(String(herdrBadge.total)))
              .when(Boolean(herdrBadge?.active), sub => sub
                .child(div().flex_none().text_size(11).text_color(t.dim).child('·'))
                .child(div().id('pm-herdr-lists-active').flex_none().text_size(11).font_medium().text_color(drawerDotColor).child(String(herdrBadge.active)))
                .child(div().size(6).flex_none().rounded_full().bg(drawerDotColor))))
            .when(!herdrState.hidden, el => el.child(div().id('pm-herdr-lists-hide').flex_none().text_size(11)
              .text_color(this.drawerHover ? t.foreground : t.dim)
              .child(word(lang, 'hideSpacesAgents')))))
          .when(Boolean(tipAnchor), el => el.child(tipAnchor))
      : null;
    return root.when(headed, el => el.child(header)).child(list).when(Boolean(drawerRow), el => el.child(drawerRow));
  }
}
