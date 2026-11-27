// The Projects page (list and archived), the header over a board, and the two dialogs this mod
// opens as overlays of itself: props {dialog: 'new'} and {dialog: 'archive', pm: <PM name>}.
import { div, svg } from 'gpui-kit';
import { v_flex, h_flex, InputState, Input, Scrollbar } from 'gpui-base';
import { home, appHome, exec, run, props, closeOverlay, layout, shared, setShared, spaces, pickFolder, notify, window as appWindow } from 'herdr';
import {
  word, withAlpha, solidText, countChips, projectCards, pageTotals, unclaimedBlocked, archiveThreads, archivedDay, age, folderName,
  ledgerOpen, startArgv, projectName, agentName, KINDS, lastPmLine, lostSummary, undeliveredSummary, formatTaskNumber, windowControlButtons,
} from './model.js';
import { execPython } from './python.js';

const PM_SCRIPT = '/mods/pm-dash/skill/scripts/pm.py';
const STAGE = 'pm-stage', BOARD = 'pm-board', PROJECT = 'pm-project';
const ICON = name => `mods/pm-dash/${name}.svg`;
const SPINNER = 'mods/workspace-chrome/spinner.svg';
// The page and the board read shared('pm-dash') = {view: 'list' | 'board' | 'archived', project: <PM name>}.
export const PAGE = 'pm-dash';

function find(node, id) {
  if (node?.id === id) return node;
  for (const child of node?.children ?? []) {
    const found = find(child, id);
    if (found) return found;
  }
  return null;
}
function select(child) {
  if (find(layout(), STAGE)) run('layout.select', { stack: STAGE, child });
}
export function page() {
  const value = shared(PAGE);
  return value && typeof value === 'object' ? value : {};
}
export function showPage(view) { setShared(PAGE, { view, project: '' }); select(BOARD); }
// A remote project (its card's key is "<machine>/<name>") opens too: pm-project reads it from that machine.
export function openProject(pm, machine = '', thread = '') {
  const payload = { pm };
  if (machine) payload.machine = machine;
  if (thread) { payload.thread = thread; payload.jumpSeq = Date.now(); }
  setShared(PROJECT, payload);
  select(PROJECT);
}
const shortPath = path => {
  const p = String(path || ''), h = home();
  return h && (p === h || p.startsWith(h + '/')) ? '~' + p.slice(h.length) : p;
};
const script = () => appHome() + PM_SCRIPT;
const failure = r => (r.stderr || r.stdout || '').trim().split('\n').pop() || `pm.py: ${r.code}`;

// The dialog sizes: the archive popup grows with the threads it lists.
export function archivePopup(pm, threads) {
  return { mod: 'pm-dash', props: { dialog: 'archive', pm }, kind: 'popup', width: 340,
    height: (threads ? 250 : 210) + Math.min(6, threads) * 24 };
}
export const NEW_DIALOG = { mod: 'pm-dash', props: { dialog: 'new' }, kind: 'dialog', width: 520, height: 520 };

// ---- small pieces -----------------------------------------------------------------

// pm-board's block has window_drag: a left press that reaches it moves the window, and a double-click
// maximizes it. So only a header's blank space and its words let presses through; its controls and
// the page under it keep theirs (Herdr's own bars do the same), still taking the keyboard as the
// page's root does for a press anywhere on it.
export const keepPress = (v, el) => el.on_mouse_down('left', (_e, cx) => { v.keys?.focus(); cx.stop_propagation(); });

const icon = (name, size = 16) => svg(ICON(name)).size(size).flex_none();
const tipWrap = (v, key, el, tip, t, opts) => (v?.withTip ? v.withTip(key, el, tip, t, opts) : el);
function iconButton(v, id, name, tip, action, t, { size = 28, glyph = 16, on = false, placement = 'above-right' } = {}) {
  return tipWrap(v, id, h_flex().id(id).size(size).flex_none().rounded(7).items_center().justify_center().cursor_pointer()
    .text_color(on ? t.foreground : t.muted).when(on, el => el.bg(t.raised))
    .hover(s => s.bg(t.hover).text_color(t.foreground)).accessibility_label(tip)
    .on_click((_e, cx) => { cx.stop_propagation(); action(cx); })
    .child(icon(name, glyph)), tip, t, { placement });
}
// Two or more views of one thing: each an icon and a word, the shown one raised.
export function segmented(id, options, active, t) {
  return h_flex().id(id).flex_none().h(34).p(3).gap(2).rounded(10).border_1().border_color(t.border)
    .children(options.map(([key, glyph, text, action]) => h_flex().id(`${id}-${key}`).h(26).px(10).gap(6).rounded(7)
      .items_center().text_size(13).cursor_pointer()
      .when(key === active, el => el.bg(t.raised).text_color(t.foreground).font_medium())
      .when(key !== active, el => el.text_color(t.muted).hover(s => s.text_color(t.foreground))
        .on_click((_e, cx) => action(cx)))
      .accessibility_label(text)
      .child(icon(glyph, 14)).child(text)));
}
// A status as the agents list marks it: spinner, dot or ring.
function mark(status, t, size = 8) {
  if (status === 'working') return svg(SPINNER).size(size + 6).flex_none().text_color(t.working ?? t.ansi2).spin(900);
  const dot = div().flex_none().size(size).rounded_full();
  if (status === 'blocked') return dot.bg(t.blocked);
  if (status === 'done') return dot.bg(t.done ?? t.accent);
  return dot.border(1.5).border_color(t.idle ?? t.dim);
}
const badge = (n, t) => h_flex().flex_none().min_w(18).h(18).px(5).rounded(9).items_center().justify_center()
  .bg(withAlpha(t.blocked, .18)).text_color(t.blocked).text_size(11).font_semibold().child(String(n));

// ---- the page header -------------------------------------------------------------

export function windowControlsBar(v, t, { divider = true } = {}) {
  let win = null;
  try { win = appWindow?.(); } catch (_) { win = null; }
  let overlay = false;
  try { overlay = Boolean(props?.()?.overlay); } catch (_) { overlay = false; }
  const buttons = typeof windowControlButtons === 'function'
    ? windowControlButtons(win, { overlay })
    : [];
  if (!Array.isArray(buttons) || !buttons.length) return null;
  const lang = v?.state?.lang;
  const stop = (_e, cx) => { v?.keys?.focus?.(); cx.stop_propagation(); };
  const row = h_flex().id('pm-window-controls').flex_none().gap(2).items_center();
  if (divider) row.child(div().w(1).h(16).mx(4).flex_none().bg(t.border));
  for (const b of buttons) {
    const label = word(lang, b.labelKey);
    const content = b.icon ? svg(b.icon).size(b.iconSize).flex_none() : b.glyph;
    row.child(h_flex().id(b.id).w(30).h(28).flex_none().rounded(6).items_center().justify_center()
      .cursor_pointer().text_color(t.muted).accessibility_label(label)
      .hover(s => (b.danger ? s.bg('#e81123').text_color('#ffffff') : s.bg(t.hover).text_color(t.foreground)))
      .on_mouse_down('left', stop)
      .on_click((_e, cx) => { cx.stop_propagation(); run(b.command); })
      .child(content));
  }
  return row;
}

export function pageHeader(v, view, t) {
  const lang = v.state.lang, text = (k, ...a) => word(lang, k, ...a);
  const winControls = windowControlsBar(v, t, { divider: true });
  return h_flex().flex_none().w_full().pl(44).pr(winControls ? 14 : 44).pt(28).pb(view === 'board' ? 12 : 0).gap(6).items_center()
    .child(div().flex_1().min_w(0).text_size(24).font_semibold().child(text('projectsTitle')))
    .child(keepPress(v, segmented('page-view', [
      ['list', 'list', text('listView'), () => showPage('list')],
      ['board', 'board', text('boardView'), () => showPage('board')],
    ], view === 'board' ? 'board' : 'list', t)))
    .child(keepPress(v, tipWrap(v, 'page-new', h_flex().id('page-new').ml(8).size(32).flex_none().rounded(16).items_center().justify_center().cursor_pointer()
      .bg(t.foreground).text_color(t.canvas).hover(s => s.opacity(.88))
      .accessibility_label(text('newProject'))
      .on_click(() => v.openNew())
      .child(icon('plus', 16)), text('newProject'), t, { placement: 'below-right' })))
    .when(Boolean(winControls), el => el.child(winControls));
}

// The header over one project's board: its name and folder, and the way back to its conversation.
export function projectHeader(v, pm, t) {
  const lang = v.state.lang;
  const winControls = windowControlsBar(v, t, { divider: true });
  return h_flex().h(56).flex_none().pl(28).pr(winControls ? 14 : 28).gap(10).items_center().border_b(1).border_color(t.border)
    .child(div().flex_none().text_size(15).font_semibold().child(projectName(pm) || 'PM'))
    .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(12).text_color(t.dim).child(shortPath(pm?.repo)))
    .child(keepPress(v, segmented('project-view', [
      ['chat', 'chat', word(lang, 'chatView'), () => openProject(pm.name, pm.machine)],
      ['board', 'board', word(lang, 'boardView'), () => {}],
    ], 'board', t)))
    .when(Boolean(winControls), el => el.child(winControls));
}

// ---- the list ------------------------------------------------------------------------

function line(card, lang, t) {
  if (!card.line.length) {
    const idle = !countChips(card.counts).length;
    return div().truncate().text_size(13.5).text_color(t.dim).child(idle ? word(lang, 'idlePm') : '');
  }
  return h_flex().min_w(0).overflow_hidden().text_size(13.5).text_color(t.muted)
    .children(card.line.map((piece, i) => div().flex_none().whitespace_nowrap()
      .when(i === card.line.length - 1, el => el.flex_shrink_1().min_w(0).truncate())
      .when(Boolean(piece.link), el => el.text_color(t.accent))
      .child(piece.text)));
}

function card(v, c, t, now) {
  const lang = v.state.lang, hovered = v.hoverCard === c.key, local = !c.machine;
  const chips = countChips(c.counts);
  const lostText = lostSummary(lang, c.lost);
  const undelText = undeliveredSummary(lang, c.undelivered);
  const meta = h_flex().gap(12).items_center().text_size(12).text_color(t.dim)
    .when(Boolean(c.agent), el => el.child(div().child(c.agent)))
    .when(Boolean(c.machine), el => el.child(div().font_family('monospace').child(c.machine)))
    .when(Boolean(lostText), el => el.child(div().id(`lost-${c.key}`).text_color(t.ansi3 ?? t.accent).child(lostText)))
    .when(Boolean(undelText), el => el.child(div().id(`undelivered-${c.key}`).text_color(t.ansi3 ?? t.blocked).child(undelText)))
    .children(chips.map(([k, n]) => div().when(k === 'waiting', el => el.text_color(t.blocked)).child(word(lang, `count_${k}`, n))))
    .when(!chips.length && !lostText && !undelText && c.line.length > 0, el => el.child(div().child(word(lang, 'noOpen'))));
  const right = h_flex().flex_none().gap(8).items_center().text_size(12).text_color(t.dim)
    .when(hovered && local, el => el.child(h_flex().gap(2).p(2).rounded(9).bg(t.raised)
      .child(iconButton(v, `open-${c.key}`, 'open', word(lang, 'openProject'), () => openProject(c.key), t))
      .child(iconButton(v, `archive-${c.key}`, 'archive', word(lang, 'archiveProject'), () => v.openArchive(c.key), t))))
    .when(c.counts.waiting > 0 && !hovered, el => el.child(badge(c.counts.waiting, t)))
    .when(c.at > 0, el => el.child(div().child(age(Math.max(0, now - c.at), lang))));
  const remoteTip = !local ? word(lang, 'remoteProject') : '';
  const rowEl = h_flex().id(`card-${c.key}`).w_full().px(14).py(16).gap(14).items_start().rounded(12)
    .when(hovered, el => el.bg(t.surface))
    .on_hover((over, cx) => {
      if (over) v.hoverCard = c.key; else if (v.hoverCard === c.key) v.hoverCard = null;
      if (remoteTip) {
        const tk = `tip:card-${c.key}`;
        if (over) v.hoverTip = tk; else if (v.hoverTip === tk) v.hoverTip = '';
      }
      cx.notify();
    })
    .cursor_pointer().on_click(() => openProject(c.key, c.machine))
    .child(h_flex().size(34).flex_none().rounded(9).bg(t.raised).items_center().justify_center().child(mark(c.status, t, 9)))
    .child(v_flex().flex_1().min_w(0).gap(5)
      .child(h_flex().gap(10).items_baseline()
        .child(div().flex_none().text_size(16).font_semibold().child(c.name))
        .child(div().min_w(0).truncate().font_family('monospace').text_size(12.5).text_color(t.dim).child(shortPath(c.repo))))
      .child(line(c, lang, t))
      .child(meta))
    .child(right);
  return remoteTip ? tipWrap(v, `card-${c.key}`, rowEl, remoteTip, t, { placement: 'above-left', noHover: true }) : rowEl;
}

function archivedCard(v, c, t) {
  const lang = v.state.lang, hovered = v.hoverCard === c.key, busy = v.restoring === c.key, local = !c.machine;
  const paused = c.paused.length ? word(lang, 'pausedLine', c.paused.length, c.paused.join(' · ')) : word(lang, 'nothingPaused');
  return h_flex().id(`archived-${c.key}`).w_full().px(14).py(12).gap(14).items_center().rounded(12)
    .when(hovered, el => el.bg(t.surface))
    .on_hover((over, cx) => {
      if (over) v.hoverCard = c.key; else if (v.hoverCard === c.key) v.hoverCard = null;
      cx.notify();
    })
    .child(v_flex().flex_1().min_w(0).gap(4)
      .child(h_flex().gap(10).items_baseline()
        .child(div().flex_none().text_size(15).font_semibold().text_color(t.muted).child(c.name))
        .child(div().min_w(0).truncate().font_family('monospace').text_size(12.5).text_color(t.dim).child(shortPath(c.repo))))
      .child(div().truncate().text_size(13).text_color(t.dim).child(paused)))
    .when((hovered || busy) && local, el => el.child(h_flex().id(`restore-${c.key}`).h(28).px(10).gap(6).flex_none().rounded(8)
      .items_center().bg(t.raised).text_size(13).text_color(t.foreground).cursor_pointer().hover(s => s.bg(t.hover))
      .opacity(busy ? .5 : 1).accessibility_label(word(lang, 'restore'))
      .on_click((_e, cx) => v.restore(c, cx))
      .child(icon('restore', 14)).child(word(lang, 'restore'))))
    .child(div().flex_none().text_size(12).text_color(t.dim).child(word(lang, 'archivedOn', archivedDay(c.archived))));
}

// view: 'list' or 'archived'.
export function pageView(v, view, t) {
  const lang = v.state.lang, text = (k, ...a) => word(lang, k, ...a), now = Date.now();
  const { active, archived } = projectCards(v.allState, v.lines, v.today());
  const body = v_flex().w_full().max_w(1100).px(30).pb(28);
  if (view === 'archived') {
    body.child(h_flex().id('back').px(14).pt(28).gap(4).items_center().text_size(13).text_color(t.muted).cursor_pointer()
      .hover(s => s.text_color(t.foreground)).on_click(() => showPage('list'))
      .child(icon('back', 13)).child(text('backToProjects')))
      .child(div().px(14).pt(10).text_size(24).font_semibold().child(text('archivedTitle')))
      .child(div().px(14).pt(6).pb(16).text_size(13).text_color(t.muted).child(text('archivedSummary', archived.length)))
      .children(archived.map(c => archivedCard(v, c, t)));
  } else {
    const total = pageTotals(active, v.allState);
    const unclaimed = unclaimedBlocked(v.allState);
    body.child(div().px(14).pt(4).pb(18).text_size(13).text_color(t.muted)
      .child(text('pageSummary', total.projects, total.working, total.waiting)))
      .children(active.map((c, i) => v_flex().w_full()
        .when(i > 0, el => el.child(div().mx(14).h(1).bg(v.hoverCard === c.key || v.hoverCard === active[i - 1].key ? t.canvas : t.border)))
        .child(card(v, c, t, now))))
      .when(!active.length, el => el.child(div().px(14).py(16).text_color(t.dim).child(text('noProjects'))))
      .when(unclaimed.count > 0, el => el.child(tipWrap(v, 'unclaimed-blocked', h_flex().id('unclaimed-blocked').mt(14).mx(14).px(12).py(10).gap(10)
        .rounded(10).bg(t.surface).items_center().cursor_pointer().hover(s => s.bg(t.raised))
        .accessibility_label(text('unclaimedBlocked', unclaimed.count))
        .on_click(() => showPage('board'))
        .child(icon('alert', 15).text_color(t.ansi3 ?? t.muted))
        .child(div().flex_none().text_size(13).font_medium().text_color(t.foreground)
          .child(text('unclaimedBlocked', unclaimed.count)))
        .child(div().flex_1().min_w(0).truncate().text_size(12.5).text_color(t.dim)
          .child(unclaimed.tasks.slice(0, 3).map(x => x.title || x.sourceId || x.id).join(' · ')))
        .child(icon('chevron', 12).text_color(t.muted)), text('unclaimedTip'), t, { placement: 'above-left' })))
      .when(archived.length > 0, el => el.child(h_flex().id('to-archived').mt(18).mx(14).gap(8).items_center()
        .text_size(13).text_color(t.muted).cursor_pointer().hover(s => s.text_color(t.foreground))
        .on_click(() => showPage('archived'))
        .child(icon('archive', 15)).child(text('archivedN', archived.length)).child(icon('chevron', 12))));
  }
  const root = v_flex().id('pm-projects').size_full().min_w(0).min_h(0).bg(t.canvas).text_color(t.foreground).text_size(14);
  if (view !== 'archived') root.child(pageHeader(v, 'list', t).pb(6));
  else {
    const winControls = windowControlsBar(v, t, { divider: false });
    if (winControls) {
      root.child(h_flex().id('pm-archived-header').h(42).w_full().flex_none().pr(14).items_center().justify_end().child(winControls));
    }
  }
  return root.child(keepPress(v, div().relative().flex_1().min_h(0).w_full())
    .child(div().id('projects-scroll').size_full().overflow_y_scroll().child(body))
    .child(Scrollbar.new('projects-scroll').absolute().inset_0()));
}

// ---- the dialogs --------------------------------------------------------------------

// Runs in init when this copy is a dialog: what it reads and the form's state.
export function initDialog(v, cx) {
  const p = props();
  v.dialog = p.dialog; v.dialogPm = p.pm || '';
  v.local = { pms: [], tasks: [], events: [] }; v.loaded = false; v.busy = false; v.failure = '';
  v.handle = cx.focus_handle(); v.handle.focus();
  v.form = { repo: '', name: '', kind: 'claude', space: 'new' };
  if (v.dialog === 'new') {
    v.nameInput = InputState.new({ value: '' });
    v.nameInput.on('change', (_e, cx) => { v.form.name = v.nameInput.value(); cx.notify(); });
    // Only ⌘↵ submits (the dialog's key handler): Enter alone in the name does not.
  }
  cx.spawn(async cx => {
    try {
      const r = await execPython(exec, [script(), 'state']);
      if (r.code === 0) v.local = JSON.parse(r.stdout);
    } catch (_) { /* The dialog still works; it shows no ledger hints. */ }
    v.loaded = true; cx.notify();
  });
}
const close = () => closeOverlay(props().overlay);

function chooseFolder(v, cx) {
  cx.spawn(async cx => {
    try {
      const folder = await pickFolder({ prompt: word(v.local.lang, 'chooseFolder').replace('…', '') });
      if (!folder) return;
      // The name follows the folder until someone types their own.
      if (!v.form.name.trim() || v.form.name === folderName(v.form.repo)) {
        v.form.name = folderName(folder); v.nameInput.set_value(v.form.name);
      }
      v.form.repo = folder; v.failure = '';
    } catch (e) { v.failure = String(e?.message || e); }
    cx.notify();
  });
}

function submitNew(v, cx) {
  if (v.busy || !v.form.repo) return;
  v.busy = true; v.failure = ''; cx.notify();
  cx.spawn(async cx => {
    try {
      const r = await execPython(exec, startArgv(script(), v.form), { timeout: 120000 });
      if (r.code !== 0) throw new Error(failure(r));
      // The new PM's name, as the ledger now has it: its project view opens.
      const s = await execPython(exec, [script(), 'state']);
      const pms = s.code === 0 ? JSON.parse(s.stdout).pms || [] : [];
      const repo = v.form.repo.replace(/\/+$/, ''), name = v.form.name.trim() || folderName(repo);
      const pm = pms.find(p => String(p.repo || '').replace(/\/+$/, '') === repo) || pms.find(p => p.project === name);
      if (pm) openProject(pm.name);
      close();
    } catch (e) { v.failure = String(e?.message || e); v.busy = false; cx.notify(); }
  });
}

function confirmArchive(v, cx) {
  const pm = v.local.pms.find(p => p.name === v.dialogPm);
  if (v.busy || !pm) return;
  v.busy = true; v.failure = ''; cx.notify();
  cx.spawn(async cx => {
    try {
      // By folder: two projects may share a name.
      const r = await execPython(exec, [script(), 'archive', pm.repo || projectName(pm)], { timeout: 60000 });
      if (r.code !== 0) throw new Error(failure(r));
      // A view of this project has nothing to show now: back to the Projects list.
      const stage = find(layout(), STAGE);
      if ((stage?.active === PROJECT && shared(PROJECT)?.pm === pm.name) || page().project === pm.name) showPage('list');
      close();
    } catch (e) { v.failure = String(e?.message || e); v.busy = false; cx.notify(); }
  });
}

// Restoring from the archived list: the ledger's word, then a fresh read.
export function restoreProject(v, c, cx) {
  if (v.restoring) return;
  v.restoring = c.key; cx.notify();
  cx.spawn(async cx => {
    try {
      const r = await execPython(exec, [script(), 'restore', c.repo || c.name], { timeout: 60000 });
      if (r.code !== 0) throw new Error(failure(r));
    } catch (e) {
      notify({ title: word(v.state.lang, 'restore'), body: word(v.state.lang, 'failedAction', String(e?.message || e)), level: 'error' });
    }
    v.restoring = ''; v.refresh(cx); cx.notify();
  });
}

function field(label, t, child) {
  return v_flex().gap(8).child(div().text_size(13).text_color(t.muted).child(label)).child(child);
}
function choice(id, options, chosen, pick, t) {
  return h_flex().id(id).w_full().h(40).p(3).gap(2).rounded(10).border_1().border_color(t.border).bg(t.background)
    .children(options.map(([key, text, dot]) => h_flex().id(`${id}-${key}`).flex_1().min_w(0).h_full().gap(7).rounded(7)
      .items_center().justify_center().text_size(13.5).cursor_pointer()
      .when(key === chosen, el => el.bg(t.raised).text_color(t.foreground).font_medium())
      .when(key !== chosen, el => el.text_color(t.muted).hover(s => s.text_color(t.foreground)))
      .on_click((_e, cx) => { pick(key); cx.notify(); })
      .when(Boolean(dot), el => el.child(div().size(8).flex_none().rounded(2).bg(key === chosen ? dot : t.dim)))
      .child(div().min_w(0).truncate().child(text))));
}

function newDialog(v, t) {
  const lang = v.local.lang, text = (k, ...a) => word(lang, k, ...a), f = v.form;
  const name = f.name.trim() || folderName(f.repo), open = ledgerOpen(v.local, name);
  const here = spaces().find(s => s.active)?.name || '';
  const ready = Boolean(f.repo) && !v.busy;
  const folderRow = h_flex().id('new-folder').h(40).px(12).gap(10).rounded(10).items_center().cursor_pointer()
    .border_1().border_color(t.input || t.border).bg(t.background).hover(s => s.bg(t.hover))
    .on_click((_e, cx) => chooseFolder(v, cx))
    .child(icon('folder', 15).text_color(t.muted))
    .child(div().flex_1().min_w(0).truncate().text_size(14).text_color(f.repo ? t.foreground : t.dim)
      .child(f.repo ? shortPath(f.repo) : text('chooseFolder')))
    .child(div().text_size(14).text_color(t.muted).child('···'));
  const hint = open.length ? h_flex().gap(8).items_start().text_size(12.5).text_color(t.muted)
    .child(h_flex().h(18).items_center().child(icon('alert', 13).text_color(t.blocked)))
    .child(div().flex_1().min_w(0).whitespace_normal().line_height('18px')
      .child(text('ledgerOpen', name, open.length, open.slice(0, 3).map(x => x.title).join('、')))) : null;
  return v_flex().size_full().p(24).gap(18).bg(t.popover).text_color(t.foreground).text_size(14)
    .child(h_flex().items_center()
      .child(div().flex_1().text_size(17).font_semibold().child(text('newProject')))
      .child(iconButton(v, 'new-close', 'close', text('cancel'), close, t, { placement: 'below-right' })))
    .child(field(text('folder'), t, v_flex().gap(8).child(folderRow).when(Boolean(hint), el => el.child(hint))))
    .child(field(text('name'), t, Input.new(v.nameInput).h(40).px(12).items_center().rounded(10).border_1()
      .border_color(t.input || t.border).bg(t.background).text_size(14).text_color(t.foreground)))
    .child(field(text('manager'), t, choice('new-kind', KINDS.map(k => [k, agentName(k), k === 'claude' ? t.ansi3 : null]),
      f.kind, k => { f.kind = k; }, t)))
    .child(field(text('place'), t, choice('new-space', [['new', text('newSpace', name || '…')],
      ...(here ? [['current', text('currentSpace', here)]] : [])], f.space, k => { f.space = k; }, t)))
    .child(div().flex_1())
    .when(Boolean(v.failure), el => el.child(div().whitespace_normal().text_size(12.5).text_color(t.blocked)
      .child(text('failedAction', v.failure))))
    .child(h_flex().gap(10).items_center()
      .child(div().flex_1().min_w(0).text_size(12.5).text_color(t.dim).child(v.busy ? text('creating') : text('placeHint')))
      .child(div().text_size(12).text_color(t.dim).child('⌘↵'))
      .child(tipWrap(v, 'new-submit', h_flex().id('new-submit').size(36).flex_none().rounded(18).items_center().justify_center()
        .bg(ready ? t.solid : t.raised).text_color(ready ? t.solid_foreground : t.muted)
        .accessibility_label(text('create'))
        .when(ready, el => el.cursor_pointer().on_click((_e, cx) => submitNew(v, cx)))
        .child(v.busy ? svg(SPINNER).size(15).spin(900) : icon('send', 15)), text('create'), t, { placement: 'above-right' })));
}

function archiveDialog(v, t) {
  const lang = v.local.lang, text = (k, ...a) => word(lang, k, ...a);
  const pm = v.local.pms.find(p => p.name === v.dialogPm);
  const threads = archiveThreads(v.local, v.dialogPm);
  const ready = Boolean(pm) && !v.busy;
  return v_flex().size_full().px(16).py(14).gap(10).bg(t.popover).text_color(t.foreground).text_size(13)
    .child(h_flex().gap(8).items_center()
      .child(icon('archive', 15))
      .child(div().flex_1().min_w(0).truncate().text_size(15).font_semibold().child(text('archiveTitle', pm ? projectName(pm) : '…'))))
    .child(div().whitespace_normal().line_height('20px').text_color(t.muted).child(text(threads.length ? 'archiveLead' : 'archiveNone')))
    .when(threads.length > 0, el => el.child(v_flex().gap(4).children(threads.slice(0, 6).map(x => {
      const xNum = formatTaskNumber(x);
      return h_flex().h(20).gap(10).items_center()
        .child(div().w(42).flex_none().text_size(12.5).text_color(x.status === 'blocked' ? t.blocked : t.dim).child(text(`thread_${x.status}`)))
        .when(Boolean(xNum), rowEl => rowEl.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(xNum)))
        .child(div().flex_1().min_w(0).truncate().child(x.title || x.id));
    }))))
    .child(div().whitespace_normal().line_height('20px').text_color(t.muted).child(text('archiveKeep')))
    .when(Boolean(v.failure), el => el.child(div().whitespace_normal().text_size(12).text_color(t.blocked).child(text('failedAction', v.failure))))
    .child(div().flex_1())
    .child(h_flex().gap(8).justify_end().items_center()
      .child(h_flex().id('archive-cancel').h(32).px(12).rounded(8).items_center().cursor_pointer().text_color(t.muted)
        .hover(s => s.bg(t.hover).text_color(t.foreground)).on_click(close).child(text('cancel')))
      .child(h_flex().id('archive-confirm').h(32).px(12).gap(6).rounded(8).items_center()
        .bg(t.solid).text_color(t.solid_foreground).font_semibold().opacity(ready ? 1 : .5)
        .when(ready, el => el.cursor_pointer().hover(s => s.opacity(.88)).on_click((_e, cx) => confirmArchive(v, cx)))
        .child(v.busy ? svg(SPINNER).size(14).spin(900) : icon('archive', 14)).child(text('archive'))));
}

export function dialogView(v, t) {
  return div().id('pm-dialog').size_full().track_focus(v.handle)
    .on_key_down((e, cx) => {
      if (e.keystroke === 'escape') close();
      else if (e.keystroke === 'cmd-enter') (v.dialog === 'new' ? submitNew : confirmArchive)(v, cx);
      else return;
      cx.stop_propagation();
    })
    .child(v.dialog === 'new' ? newDialog(v, t) : archiveDialog(v, t));
}

// The PM's newest sentence for each local project's card: the end of its conversation log.
export async function readLines(pms) {
  const lines = {};
  await Promise.all(pms.filter(pm => pm.conversation).map(async pm => {
    try {
      const r = await exec('sh', ['-c', 'test -f "$1" || exit 0; tail -n 200 "$1"', 'sh', pm.conversation]);
      if (r.code === 0) lines[pm.name] = lastPmLine(r.stdout);
    } catch (_) { /* That card shows no sentence. */ }
  }));
  return lines;
}
