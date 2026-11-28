// The Projects page (list and archived), the header over a board, and the dialogs this mod
// opens as overlays of itself: props {dialog: 'new'}, {dialog: 'rename', pm: <PM name>}, and {dialog: 'archive', pm: <PM name>}.
import { div, svg } from 'gpui-kit';
import { v_flex, h_flex, InputState, Input, Scrollbar } from 'gpui-base';
import { home, appHome, exec, run, props, closeOverlay, layout, shared, setShared, spaces, panes, terminals, knownAgents, pickFolder, readTextFile, notify, window as appWindow } from 'herdr';
import {
  word, withAlpha, solidText, countChips, projectCards, pageTotals, unclaimedBlocked, archiveThreads, archivedDay, age, folderName,
  ledgerOpen, startArgv, renameArgv, validateProjectName, projectName, agentName, KINDS, lastPmLine, lostSummary, undeliveredSummary, formatTaskNumber, windowControlButtons,
  remotePmArgv, REMOTE_PROBE_SH, REMOTE_LIST_DIRS_SH, REMOTE_MKDIR_SH, LOCAL_GIT_PROBE_SH,
  parseRemoteProbe, parseRemoteDirs, normalizeMachines, initialMachineForDialog, addFolderEntry, removeFolderEntry,
  canSubmitNewProject, stripMachinePrefix, qualifyForMachine, shouldCloseSpaceAfterArchive, resolveRestoreSpace,
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
export function archivePopup(pm, threads, machine = '') {
  const popupProps = machine ? { dialog: 'archive', pm, machine } : { dialog: 'archive', pm };
  return { mod: 'pm-dash', props: popupProps, kind: 'popup', width: 340,
    height: (threads ? 250 : 210) + Math.min(6, threads) * 24 };
}
export function renameDialogSpec(pm) {
  return { mod: 'pm-dash', props: { dialog: 'rename', pm }, kind: 'dialog', width: 420, height: 224 };
}
export const NEW_DIALOG = { mod: 'pm-dash', props: { dialog: 'new' }, kind: 'dialog', width: 560, height: 580 };

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

// The header over one project's board: its name and folder, and the single chat icon back to its conversation.
export function projectHeader(v, pm, t) {
  const lang = v.state.lang;
  const winControls = windowControlsBar(v, t, { divider: true });
  return h_flex().h(56).flex_none().pl(28).pr(winControls ? 14 : 28).gap(10).items_center().border_b(1).border_color(t.border)
    .child(div().flex_none().text_size(15).font_semibold().child(projectName(pm) || 'PM'))
    .when(!pm?.machine, el => el.child(keepPress(v, iconButton(v, 'project-rename', 'pencil', word(lang, 'renameProject'),
      () => v.openRename(pm.name), t, { size: 26, glyph: 13, placement: 'below-left' }))))
    .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(12).text_color(t.dim).child(shortPath(pm?.repo)))
    .child(keepPress(v, iconButton(v, 'project-view-chat', 'chat', word(lang, 'switchToChat'),
      () => openProject(pm.name, pm.machine), t, { size: 32, glyph: 16, placement: 'below-right' })))
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
    .when(hovered, el => el.child(h_flex().gap(2).p(2).rounded(9).bg(t.raised)
      .child(iconButton(v, `open-${c.key}`, 'open', word(lang, 'openProject'), () => openProject(c.key, c.machine), t))
      .when(local, el2 => el2.child(iconButton(v, `rename-${c.key}`, 'pencil', word(lang, 'renameProject'), () => v.openRename(c.key), t)))
      .child(iconButton(v, `archive-${c.key}`, 'archive', word(lang, 'archiveProject'), () => v.openArchive(c.key, c.machine), t))))
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
        .when(Boolean(c.machine), el => el.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(c.machine)))
        .child(div().min_w(0).truncate().font_family('monospace').text_size(12.5).text_color(t.dim).child(shortPath(c.repo))))
      .child(div().truncate().text_size(13).text_color(t.dim).child(paused)))
    .when(hovered || busy, el => el.child(h_flex().gap(6).items_center().flex_none()
      .when(local, el2 => el2.child(iconButton(v, `rename-archived-${c.key}`, 'pencil', word(lang, 'renameProject'), () => v.openRename(c.key), t)))
      .child(h_flex().id(`restore-${c.key}`).h(28).px(10).gap(6).flex_none().rounded(8)
        .items_center().bg(t.raised).text_size(13).text_color(t.foreground).cursor_pointer().hover(s => s.bg(t.hover))
        .opacity(busy ? .5 : 1).accessibility_label(word(lang, 'restore'))
        .on_click((_e, cx) => v.restore(c, cx))
        .child(icon('restore', 14)).child(word(lang, 'restore')))))
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

const sleep = (cx, ms) => (cx?.timer?.after ? new Promise(resolve => cx.timer.after(ms, resolve)) : Promise.resolve());

function randomHex32() {
  if (globalThis.crypto?.getRandomValues) {
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  }
  let out = '';
  while (out.length < 32) out += Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, '0');
  return out.slice(0, 32);
}

function mapKnownAgents(list) {
  if (!Array.isArray(list)) return null;
  const installed = new Set();
  for (const item of list) {
    if (!item?.installed) continue;
    const raw = String(item.key || item.run?.[0] || '').toLowerCase();
    if (raw.includes('claude')) installed.add('claude');
    else if (raw === 'agy' || raw.includes('antigravity')) installed.add('agy');
    else if (raw.includes('codex')) installed.add('codex');
    else if (raw === 'pi' || raw.endsWith('/pi')) installed.add('pi');
  }
  return installed;
}

function defaultKindFromConfig(text, installedSet = null) {
  try {
    const cfg = JSON.parse(text || '{}');
    const pm = cfg?.pm || {};
    const direct = String(pm.kind || '').trim().toLowerCase();
    if (KINDS.includes(direct)) return direct;
    const profName = String(pm.profile || '').trim();
    const profKind = String(cfg?.profiles?.[profName]?.kind || '').trim().toLowerCase();
    if (KINDS.includes(profKind)) return profKind;
  } catch (_) { /* ignore */ }
  if (installedSet && !installedSet.has('claude')) {
    const first = KINDS.find(k => installedSet.has(k));
    if (first) return first;
  }
  return 'claude';
}

async function loadMachineAgents(v, machine, cx) {
  const key = machine || '';
  if (key in v.agentStatus) return;
  try {
    const list = typeof knownAgents === 'function' ? await knownAgents({ on: key || null }) : null;
    v.agentStatus[key] = mapKnownAgents(list);
  } catch (_) {
    v.agentStatus[key] = null;
  }
  cx.notify();
}

async function probeRemoteMachine(v, machine, cx) {
  if (!machine) return;
  const prev = v.machineProbe[machine];
  if (prev?.loading) return;
  v.machineProbe[machine] = { ...(prev || {}), loading: true, error: '' };
  cx.notify();
  try {
    const r = await exec('sh', ['-c', REMOTE_PROBE_SH, 'sh'], { on: machine, timeout: 6000 });
    if (r.code !== 0) throw new Error(failure(r));
    const parsed = parseRemoteProbe(r.stdout);
    let remoteState = null;
    if (parsed.pmScript) {
      try {
        const sr = await exec(...remotePmArgv(['state']), { on: machine, timeout: 10000 });
        if (sr.code === 0) remoteState = JSON.parse(sr.stdout);
      } catch (_) { /* optional ledger hints */ }
    }
    let defaultKind = '';
    if (parsed.ledgerHome && typeof readTextFile === 'function') {
      try {
        const cfgText = await readTextFile(`${parsed.ledgerHome}/config.json`, { on: machine });
        if (cfgText) defaultKind = defaultKindFromConfig(cfgText, v.agentStatus[machine] || null);
      } catch (_) { /* optional default kind */ }
    }
    v.machineProbe[machine] = {
      ...parsed,
      state: remoteState,
      defaultKind,
      loading: false,
      error: parsed.pmScript ? '' : word(v.local.lang, 'remotePmMissing', machine),
    };
    if (v.form.machine === machine && defaultKind && !v.kindTouched) v.form.kind = defaultKind;
  } catch (e) {
    v.machineProbe[machine] = { loading: false, pmScript: '', home: '', error: String(e?.message || e) };
  }
  cx.notify();
}

function selectMachine(v, machine, cx) {
  if (v.form.machine === machine || v.busy) return;
  v.form.machine = machine;
  v.form.folders = [];
  v.remotePath = '';
  v.remoteCheck = null;
  v.picker = { open: false, loading: false, error: '', base: '', home: '', entries: [] };
  v.failure = '';
  v.remotePathInput?.set_value?.('');
  v.remotePathInput?.set_placeholder?.(machine ? word(v.local.lang, 'enterRemotePath', machine) : '');
  const probe = v.machineProbe[machine];
  if (!v.kindTouched) {
    if (probe?.defaultKind) v.form.kind = probe.defaultKind;
    else if (!machine && v.localDefaultKind) v.form.kind = v.localDefaultKind;
  }
  cx.notify();
  if (machine) {
    probeRemoteMachine(v, machine, cx);
    loadMachineAgents(v, machine, cx);
  }
}

function applyAutoProjectName(v, folderPath) {
  if (v.nameTouched || v.form.name.trim()) return;
  const auto = folderName(folderPath);
  if (!auto) return;
  v.form.name = auto;
  v.nameInput?.set_value?.(auto);
}

// Runs in init when this copy is a dialog: what it reads and the form's state.
export function initDialog(v, cx) {
  const p = props();
  v.dialog = p.dialog; v.dialogPm = p.pm || '';
  v.dialogMachine = p.machine || (v.dialogPm.includes('/') ? v.dialogPm.split('/', 1)[0] : '');
  v.dialogSourcePm = v.dialogMachine && v.dialogPm.startsWith(`${v.dialogMachine}/`)
    ? v.dialogPm.slice(v.dialogMachine.length + 1)
    : v.dialogPm;
  v.local = { lang: 'en', pms: [], tasks: [], events: [] }; v.loaded = false; v.busy = false; v.failure = '';
  v.handle = cx.focus_handle(); v.handle.focus();
  v.form = { machine: '', folders: [], name: '', kind: 'claude' };
  v.machines = []; v.machinesLoaded = false; v.agentStatus = {}; v.machineProbe = {};
  v.remotePath = ''; v.remoteCheck = null;
  v.picker = { open: false, loading: false, error: '', base: '', home: '', entries: [] };
  v.nameTouched = false; v.kindTouched = false; v.localDefaultKind = ''; v.renameDirty = false;
  if (v.dialog === 'new') {
    v.nameInput = InputState.new({ value: '' });
    v.nameInput.on('change', (_e, cx) => {
      v.form.name = v.nameInput.value();
      v.nameTouched = Boolean(v.form.name.trim());
      v.failure = '';
      cx.notify();
    });
    v.remotePathInput = InputState.new({ value: '' });
    v.remotePathInput.on('change', (_e, cx) => {
      v.remotePath = v.remotePathInput.value();
      v.remoteCheck = null;
      v.failure = '';
      cx.notify();
    });
    v.remotePathInput.on('submit', (_e, cx) => addRemotePath(v, cx));
    // Only ⌘↵ submits (the dialog's key handler): Enter alone in the name does not.
  } else if (v.dialog === 'rename') {
    v.renameInput = InputState.new({ value: '' });
    v.renameInput.on('change', (_e, cx) => { v.renameDirty = true; v.form.name = v.renameInput.value(); v.failure = ''; cx.notify(); });
    v.renameInput.on('submit', (_e, cx) => submitRename(v, cx));
  }
  cx.spawn(async cx => {
    const statePromise = v.dialog === 'archive' && v.dialogMachine
      ? exec(...remotePmArgv(['state']), { on: v.dialogMachine, timeout: 10000 }).catch(() => null)
      : execPython(exec, [script(), 'state']).catch(() => null);
    const machinesPromise = v.dialog === 'new'
      ? exec('hc', ['machine', 'ls', '--json'], { timeout: 4000 }).catch(() => null)
      : Promise.resolve(null);
    const localAgentsPromise = v.dialog === 'new'
      ? loadMachineAgents(v, '', cx)
      : Promise.resolve();
    const [r, mr] = await Promise.all([statePromise, machinesPromise, localAgentsPromise]);
    if (r?.code === 0) {
      try { v.local = JSON.parse(r.stdout); } catch (_) { /* ignore */ }
    }
    if (v.dialog === 'new') {
      if (mr?.code === 0) {
        try { v.machines = normalizeMachines(JSON.parse(mr.stdout)); } catch (_) { v.machines = []; }
      }
      v.machinesLoaded = true;
      if (v.local?.home && typeof readTextFile === 'function') {
        try {
          const cfgText = await readTextFile(`${v.local.home}/config.json`);
          if (cfgText) {
            v.localDefaultKind = defaultKindFromConfig(cfgText, v.agentStatus[''] || null);
            if (!v.kindTouched && !v.form.machine) v.form.kind = v.localDefaultKind;
          }
        } catch (_) { /* optional */ }
      }
      const initialMachine = initialMachineForDialog(v.machines, spaces());
      if (initialMachine) {
        selectMachine(v, initialMachine, cx);
      } else {
        v.nameInput?.focus?.();
      }
    } else if (v.dialog === 'rename' && !v.renameDirty) {
      const pm = (v.local.pms || []).find(item => item.name === v.dialogPm);
      if (pm) {
        v.form.name = projectName(pm);
        v.renameInput?.set_value?.(v.form.name);
      }
      v.renameInput?.focus?.();
    }
    v.loaded = true; cx.notify();
  });
}
const close = () => closeOverlay(props().overlay);

function chooseFolder(v, cx) {
  cx.spawn(async cx => {
    try {
      const folder = await pickFolder({ prompt: word(v.local.lang, 'chooseFolder').replace('…', '') });
      if (!folder) return;
      let entry = { path: folder, git: false, branch: '' };
      try {
        const probe = await exec('sh', ['-c', LOCAL_GIT_PROBE_SH, 'sh', folder], { timeout: 3000 });
        if (probe.code === 0) {
          const dir = parseRemoteProbe(probe.stdout).dirs[0];
          if (dir?.exists) entry = dir;
        }
      } catch (_) { /* keep basic folder entry */ }
      v.form.folders = addFolderEntry(v.form.folders, entry);
      applyAutoProjectName(v, entry.path);
      v.failure = '';
    } catch (e) { v.failure = String(e?.message || e); }
    cx.notify();
  });
}

function probeRemotePath(v, rawPath, cx, { addIfExists = false } = {}) {
  const machine = v.form.machine, trimmed = String(rawPath || '').trim();
  if (!machine || !trimmed) return;
  v.remoteCheck = { raw: trimmed, exists: false, path: trimmed, git: false, branch: '', checking: true, creating: false };
  v.failure = '';
  cx.notify();
  cx.spawn(async cx => {
    try {
      const r = await exec('sh', ['-c', REMOTE_PROBE_SH, 'sh', trimmed], { on: machine, timeout: 5000 });
      if (r.code !== 0) throw new Error(failure(r));
      const parsed = parseRemoteProbe(r.stdout);
      const dir = parsed.dirs[0] || { exists: false, raw: trimmed, path: trimmed, git: false, branch: '' };
      if (v.machineProbe[machine]) {
        v.machineProbe[machine] = { ...v.machineProbe[machine], home: parsed.home || v.machineProbe[machine].home, pmScript: parsed.pmScript || v.machineProbe[machine].pmScript };
      }
      if (dir.exists) {
        if (addIfExists) {
          v.form.folders = addFolderEntry(v.form.folders, dir);
          applyAutoProjectName(v, dir.path);
          v.remotePath = '';
          v.remotePathInput?.set_value?.('');
          v.remoteCheck = null;
        } else {
          v.remoteCheck = { ...dir, checking: false, creating: false };
        }
      } else {
        v.remoteCheck = { ...dir, exists: false, checking: false, creating: false };
      }
    } catch (e) {
      v.remoteCheck = null;
      v.failure = String(e?.message || e);
    }
    cx.notify();
  });
}

function addRemotePath(v, cx) {
  probeRemotePath(v, v.remotePath, cx, { addIfExists: true });
}

function createRemoteFolder(v, rawPath, cx) {
  const machine = v.form.machine, target = String(rawPath || '').trim();
  if (!machine || !target || v.remoteCheck?.creating) return;
  v.remoteCheck = { ...(v.remoteCheck || { raw: target, path: target }), creating: true };
  v.failure = '';
  cx.notify();
  cx.spawn(async cx => {
    try {
      const r = await exec('sh', ['-c', REMOTE_MKDIR_SH, 'sh', target], { on: machine, timeout: 5000 });
      if (r.code !== 0) throw new Error(failure(r));
      const createdPath = r.stdout.trim() || v.remoteCheck?.path || target;
      v.form.folders = addFolderEntry(v.form.folders, { path: createdPath, git: false, branch: '' });
      applyAutoProjectName(v, createdPath);
      v.remotePath = '';
      v.remotePathInput?.set_value?.('');
      v.remoteCheck = null;
    } catch (e) {
      if (v.remoteCheck) v.remoteCheck.creating = false;
      v.failure = String(e?.message || e);
    }
    cx.notify();
  });
}

function openRemotePicker(v, prefix, cx) {
  const machine = v.form.machine;
  if (!machine) return;
  v.picker = { ...v.picker, open: true, loading: true, error: '' };
  cx.notify();
  cx.spawn(async cx => {
    try {
      const target = String(prefix ?? (v.remotePath.trim() || v.machineProbe[machine]?.home || '~'));
      const r = await exec('sh', ['-c', REMOTE_LIST_DIRS_SH, 'sh', target], { on: machine, timeout: 5000 });
      if (r.code !== 0) throw new Error(failure(r));
      const parsed = parseRemoteDirs(r.stdout);
      v.picker = { open: true, loading: false, error: '', base: parsed.base, home: parsed.home, entries: parsed.entries };
    } catch (e) {
      v.picker = { ...v.picker, open: true, loading: false, error: String(e?.message || e) };
    }
    cx.notify();
  });
}

function pickRemoteEntry(v, entry, cx) {
  v.form.folders = addFolderEntry(v.form.folders, entry);
  applyAutoProjectName(v, entry.path);
  v.remotePath = '';
  v.remotePathInput?.set_value?.('');
  v.remoteCheck = null;
  v.picker = { ...v.picker, open: false };
  cx.notify();
}

async function attachRemoteSpace(cx, machine, terminal, displayName, slug, { reuseSpaceId = '' } = {}) {
  const qTerm = qualifyForMachine(terminal, machine);
  const existing = resolveRestoreSpace({ machine, spaceId: reuseSpaceId, spaces: spaces() });
  const bareSpId = existing.reuse ? stripMachinePrefix(existing.qualifiedSpaceId, machine) : `sp${randomHex32()}`;
  const bareTbId = `tb${randomHex32()}`;
  await exec('hc', ['label', qTerm, `herdr.space=${bareSpId}`, `herdr.tab=${bareTbId}`], { timeout: 6000 });
  const qSpaceId = qualifyForMachine(bareSpId, machine);
  let matchedSpace = null;
  for (let i = 0; i < 16; i++) {
    matchedSpace = spaces().find(s => s?.id === qSpaceId);
    if (matchedSpace) break;
    await sleep(cx, 150);
  }
  if (matchedSpace && !existing.reuse) {
    run('space.rename', { id: qSpaceId, name: displayName });
  }
  if (matchedSpace) {
    const tab = (matchedSpace.tabs || []).find(tb => tb?.id === qualifyForMachine(bareTbId, machine))
      || (matchedSpace.tabs || []).at(-1);
    if (tab?.id) run('tab.rename', { id: tab.id, name: `PM-${displayName}` });
  }
  if (slug) {
    await exec(...remotePmArgv(['project', 'set-space', slug, bareSpId, '--space-name', displayName]), { on: machine, timeout: 10000 })
      .catch(() => null);
  }
  return bareSpId;
}

function submitNew(v, cx) {
  const machine = v.form.machine || '';
  const probeErr = machine ? (v.machineProbe[machine]?.error || '') : '';
  if (!canSubmitNewProject(v.form, { busy: v.busy, remoteReady: !probeErr })) return;
  v.busy = true; v.failure = ''; cx.notify();
  cx.spawn(async cx => {
    try {
      const name = String(v.form.name || '').trim();
      if (!machine) {
        const r = await execPython(exec, startArgv(script(), v.form, { json: true }), { timeout: 120000 });
        if (r.code !== 0) throw new Error(failure(r));
        let pmKey = '';
        try {
          const parsed = JSON.parse(r.stdout);
          pmKey = parsed?.name || '';
        } catch (_) { pmKey = ''; }
        if (!pmKey) {
          const s = await execPython(exec, [script(), 'state']);
          const pms = s.code === 0 ? JSON.parse(s.stdout).pms || [] : [];
          const hit = pms.find(p => projectName(p) === name || p.project === name);
          pmKey = hit?.name || '';
        }
        if (pmKey) openProject(pmKey);
        close();
        return;
      }
      const remoteArgs = startArgv('', v.form, { noAppSpace: true, json: true }).slice(1);
      const r = await exec(...remotePmArgv(remoteArgs), { on: machine, timeout: 120000 });
      if (r.code !== 0) throw new Error(failure(r));
      const created = JSON.parse(r.stdout || '{}');
      const displayName = created.display_name || name;
      await attachRemoteSpace(cx, machine, created.terminal, displayName, created.slug);
      run('pm-nav.refresh-remote');
      if (created.name) openProject(`${machine}/${created.name}`, machine);
      close();
    } catch (e) { v.failure = String(e?.message || e); v.busy = false; cx.notify(); }
  });
}

function submitRename(v, cx) {
  const pm = (v.local.pms || []).find(p => p.name === v.dialogPm);
  if (v.busy || !pm) return;
  const check = validateProjectName(v.form.name, v.local.lang, { pms: v.local.pms, currentPm: pm.name });
  if (!check.ok) { v.failure = check.error; cx.notify(); return; }
  if (check.name === projectName(pm)) { close(); return; }
  v.busy = true; v.failure = ''; cx.notify();
  cx.spawn(async cx => {
    try {
      const r = await execPython(exec, renameArgv(script(), pm, check.name), { timeout: 30000 });
      if (r.code !== 0) throw new Error(failure(r));
      close();
    } catch (e) { v.failure = String(e?.message || e); v.busy = false; cx.notify(); }
  });
}

function confirmArchive(v, cx) {
  const machine = v.dialogMachine || '';
  const targetPmName = machine ? v.dialogSourcePm : v.dialogPm;
  const pm = (v.local.pms || []).find(p => p.name === targetPmName);
  if (v.busy || !pm) return;
  v.busy = true; v.failure = ''; cx.notify();
  cx.spawn(async cx => {
    try {
      const target = pm.slug || pm.repo || projectName(pm) || pm.name;
      if (!machine) {
        const r = await execPython(exec, [script(), 'archive', target, '--json'], { timeout: 60000 });
        if (r.code !== 0) throw new Error(failure(r));
      } else {
        const r = await exec(...remotePmArgv(['archive', target, '--json']), { on: machine, timeout: 60000 });
        if (r.code !== 0) throw new Error(failure(r));
        let archivedOut = {};
        try { archivedOut = JSON.parse(r.stdout || '{}'); } catch (_) { archivedOut = {}; }
        const closeCheck = shouldCloseSpaceAfterArchive({
          machine,
          spaceId: archivedOut.space_id || pm.space_id || '',
          pmTerminal: archivedOut.terminal || pm.terminal || '',
          spaces: spaces(),
          terminals: terminals(),
        });
        if (closeCheck.close && closeCheck.spaceId) {
          run('space.close', { id: closeCheck.spaceId, confirmed: true });
        }
        run('pm-nav.refresh-remote');
      }
      // A view of this project has nothing to show now: back to the Projects list.
      const stage = find(layout(), STAGE);
      if ((stage?.active === PROJECT && shared(PROJECT)?.pm === v.dialogPm) || page().project === v.dialogPm) showPage('list');
      close();
    } catch (e) { v.failure = String(e?.message || e); v.busy = false; cx.notify(); }
  });
}

// Restoring from the archived list: the ledger's word, then a fresh read (supports local and remote).
export function restoreProject(v, c, cx) {
  if (v.restoring) return;
  v.restoring = c.key; cx.notify();
  cx.spawn(async cx => {
    try {
      const target = c.slug || c.repo || c.sourceName || c.name;
      if (!c.machine) {
        const r = await execPython(exec, [script(), 'restore', target, '--json'], { timeout: 60000 });
        if (r.code !== 0) throw new Error(failure(r));
      } else {
        const r = await exec(...remotePmArgv(['restore', target, '--no-app-space', '--json']), { on: c.machine, timeout: 120000 });
        if (r.code !== 0) throw new Error(failure(r));
        const restored = JSON.parse(r.stdout || '{}');
        if (restored.terminal) {
          await attachRemoteSpace(cx, c.machine, restored.terminal, restored.display_name || c.name, restored.slug || target, {
            reuseSpaceId: restored.space_id || c.spaceId || '',
          });
        }
        run('pm-nav.refresh-remote');
        v.refreshRemote?.(cx);
      }
    } catch (e) {
      notify({ title: word(v.state.lang, 'restore'), body: word(v.state.lang, 'failedAction', String(e?.message || e)), level: 'error' });
    }
    v.restoring = ''; v.refresh(cx); cx.notify();
  });
}

function field(label, t, child, rightHint = '') {
  return v_flex().gap(7)
    .child(h_flex().gap(8).items_baseline()
      .child(div().text_size(12.5).font_medium().text_color(t.muted).child(label))
      .child(div().flex_1())
      .when(Boolean(rightHint), el => el.child(div().text_size(11.5).text_color(t.dim).child(rightHint))))
    .child(child);
}

function choice(id, options, chosen, pick, t, { onDisabledHover } = {}) {
  return h_flex().id(id).w_full().h(38).p(3).gap(3).rounded(10).border_1().border_color(t.border).bg(t.background)
    .children(options.map(([key, text, dot, opts]) => {
      const disabled = Boolean(opts?.disabled), dimmed = Boolean(opts?.dimmed);
      const btn = h_flex().id(`${id}-${key}`).flex_1().min_w(0).h_full().px(8).gap(6).rounded(7)
        .items_center().justify_center().text_size(13)
        .when(key === chosen, el => el.bg(t.raised).text_color(t.foreground).font_medium())
        .when(key !== chosen && !disabled && !dimmed, el => el.text_color(t.muted).hover(s => s.text_color(t.foreground)))
        .when(disabled || dimmed, el => el.text_color(t.dim).opacity(disabled ? .55 : .72))
        .when(!disabled, el => el.cursor_pointer().on_click((_e, cx) => { pick(key); cx.notify(); }))
        .when(Boolean(dot), el => el.child(div().size(7).flex_none().rounded_full().bg(key === chosen || opts?.alwaysColorDot ? dot : t.dim)))
        .child(div().min_w(0).truncate().child(text));
      return opts?.tip && onDisabledHover ? onDisabledHover(`${id}-${key}`, btn, opts.tip) : btn;
    }));
}

function newDialog(v, t) {
  const lang = v.local.lang, text = (k, ...a) => word(lang, k, ...a), f = v.form;
  const machine = f.machine || '';
  const connectedCount = v.machines.filter(m => m.connected).length;
  const probe = machine ? v.machineProbe[machine] : null;
  const ledgerState = machine && probe?.state ? probe.state : v.local;
  const effName = f.name.trim() || folderName(f.folders[0]?.path || '');
  const open = ledgerOpen(ledgerState, effName, f.folders);
  const ready = canSubmitNewProject(f, { busy: v.busy, remoteReady: !probe?.error });

  const machineRight = !v.machines.length ? ''
    : machine && probe?.loading ? text('checkingPath')
    : machine && probe?.pmScript ? text('machineConnected')
    : connectedCount > 0 ? text('remoteConnectedCount', connectedCount)
    : '';
  const machineRow = v.machines.length ? field(text('machine'), t, choice('new-machine', [
    ['local', text('localMachine'), null, {}],
    ...v.machines.map(m => [
      m.name,
      m.name,
      m.connected ? (t.ansi2 || t.working) : t.dim,
      {
        disabled: !m.connected,
        alwaysColorDot: m.connected,
        tip: !m.connected ? text('machineOfflineTip', m.name, m.state) : '',
      },
    ]),
  ], machine || 'local', key => selectMachine(v, key === 'local' ? '' : key, v._lastCx || { notify() {} }), t, {
    onDisabledHover: (id, el, tip) => tipWrap(v, id, el, tip, t, { placement: 'above-left' }),
  }), machineRight) : null;

  const foldersRight = f.folders.length ? text('foldersLinkedCount', f.folders.length) : text('foldersZeroHint');
  const folderList = v_flex().gap(6).children(f.folders.map((entry, idx) => {
    const gitColor = t.ansi2 || t.working || t.accent;
    const badgeText = entry.git ? (entry.branch ? `git · ${entry.branch}` : 'git') : text('folderBadge');
    return h_flex().id(`folder-row-${idx}`).h(36).px(10).gap(8).rounded(9).border_1().border_color(t.border).bg(t.background).items_center()
      .child(icon('folder', 14).text_color(t.muted))
      .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(12.5).text_color(t.foreground)
        .child(machine ? entry.path : shortPath(entry.path)))
      .child(div().flex_none().px(6).py(2).rounded(5).bg(t.raised).text_size(11).text_color(t.muted).child(entry.alias))
      .child(div().flex_none().px(6).py(2).rounded(5)
        .bg(entry.git ? withAlpha(gitColor, .14) : t.raised)
        .text_color(entry.git ? gitColor : t.dim)
        .font_family('monospace').text_size(11).child(badgeText))
      .child(iconButton(v, `remove-folder-${idx}`, 'close', text('removeFolder'), () => {
        v.form.folders = removeFolderEntry(v.form.folders, entry.path);
      }, t, { size: 22, glyph: 11, placement: 'above-right' }));
  }));

  const localAddRow = h_flex().id('new-add-folder').h(36).px(10).gap(8).rounded(9).items_center().cursor_pointer()
    .border_1().border_color(t.border).bg(t.surface).hover(s => s.bg(t.hover))
    .on_click((_e, cx) => chooseFolder(v, cx))
    .child(icon('folder-plus', 14).text_color(t.muted))
    .child(div().flex_1().min_w(0).truncate().text_size(13).text_color(f.folders.length ? t.muted : t.dim)
      .child(f.folders.length ? text('addFolder') : text('noFoldersLinked')))
    .child(div().text_size(11.5).text_color(t.dim).child(text('addFolder')));

  const warnColor = t.ansi3 || t.blocked;
  const remoteAddRow = v_flex().gap(6)
    .child(h_flex().id('remote-path-box').h(38).pl(10).pr(4).gap(6).rounded(9).items_center()
      .border_1().border_color(v.remoteCheck?.exists === false ? warnColor : (t.input || t.border)).bg(t.background)
      .child(icon('folder-plus', 14).text_color(t.muted))
      .child(Input.new(v.remotePathInput).flex_1().min_w(0).h_full().items_center().font_family('monospace').text_size(12.5).text_color(t.foreground))
      .when(Boolean(v.remotePath.trim()), el => el.child(h_flex().id('remote-add-btn').h(28).px(10).flex_none().rounded(6)
        .items_center().bg(t.raised).hover(s => s.bg(t.hover)).cursor_pointer().text_size(12).font_medium().text_color(t.foreground)
        .on_click((_e, cx) => addRemotePath(v, cx))
        .child(v.remoteCheck?.checking ? text('checkingPath') : text('add'))))
      .child(h_flex().id('remote-browse-btn').h(28).px(9).gap(5).flex_none().rounded(6).items_center().cursor_pointer()
        .bg(v.picker.open ? withAlpha(t.accent, .18) : t.raised)
        .text_color(v.picker.open ? t.accent : t.muted)
        .hover(s => s.bg(t.hover).text_color(t.foreground))
        .on_click((_e, cx) => {
          if (v.picker.open) { v.picker.open = false; cx.notify(); }
          else openRemotePicker(v, undefined, cx);
        })
        .child(icon('folder', 12)).child(div().text_size(12).child(text('browse')))))
    .when(Boolean(v.remoteCheck && !v.remoteCheck.checking && !v.remoteCheck.exists), el => el.child(
      h_flex().id('remote-not-found').px(10).py(7).gap(8).rounded(8).items_center()
        .bg(withAlpha(warnColor, .12)).border_1().border_color(withAlpha(warnColor, .35))
        .child(icon('alert', 13).text_color(warnColor))
        .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(12).text_color(t.foreground)
          .child(`${v.remoteCheck.path} · ${text('notFound')}`))
        .child(h_flex().id('remote-create-folder').h(24).px(9).flex_none().rounded(6).items_center().cursor_pointer()
          .bg(t.solid).text_color(t.solid_foreground).text_size(11.5).font_medium().hover(s => s.opacity(.88))
          .on_click((_e, cx) => createRemoteFolder(v, v.remoteCheck.raw || v.remoteCheck.path, cx))
          .child(v.remoteCheck.creating ? text('creatingFolder') : text('createRemoteFolder')))))
    .when(v.picker.open, el => {
      const parentDir = v.picker.base && v.picker.base !== '/' ? (v.picker.base.replace(/\/+$/, '').split('/').slice(0, -1).join('/') || '/') : '';
      return v_flex().id('remote-picker').rounded(10).border_1().border_color(t.border).bg(t.surface).overflow_hidden()
        .child(h_flex().h(30).px(10).gap(8).items_center().border_b(1).border_color(t.border)
          .when(Boolean(parentDir), b => b.child(h_flex().id('remote-picker-up').px(6).py(2).rounded(5).bg(t.raised)
            .text_size(11).text_color(t.muted).cursor_pointer().hover(s => s.text_color(t.foreground))
            .on_click((_e, cx) => openRemotePicker(v, parentDir, cx)).child(text('remotePickerUp'))))
          .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(11.5).text_color(t.muted)
            .child(v.picker.base || '~'))
          .child(div().flex_none().text_size(11).text_color(t.dim).child(text('remotePickerHint'))))
        .child(div().relative().w_full().max_h(150).child(
          div().id('remote-picker-scroll').w_full().max_h(150).overflow_y_scroll()
            .child(v_flex().p(4).gap(2)
              .when(v.picker.loading, b => b.child(div().px(8).py(8).text_size(12).text_color(t.dim).child(text('checkingPath'))))
              .when(!v.picker.loading && Boolean(v.picker.error), b => b.child(div().px(8).py(8).text_size(12).text_color(t.blocked).child(v.picker.error)))
              .when(!v.picker.loading && !v.picker.error && !v.picker.entries.length, b => b.child(div().px(8).py(8).text_size(12).text_color(t.dim).child(text('remotePickerEmpty'))))
              .when(!v.picker.loading && !v.picker.error, b => b.children(v.picker.entries.map((entry, idx) =>
                h_flex().id(`remote-dir-${idx}`).h(30).px(8).gap(8).rounded(6).items_center().cursor_pointer().hover(s => s.bg(t.hover))
                  .on_click((_e, cx) => openRemotePicker(v, entry.path, cx))
                  .child(icon('folder', 13).text_color(t.muted))
                  .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(12).text_color(t.foreground).child(entry.name))
                  .when(entry.git, g => g.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.ansi2 || t.muted)
                    .child(entry.branch ? `git · ${entry.branch}` : 'git')))
                  .child(h_flex().id(`remote-dir-add-${idx}`).h(22).px(7).flex_none().rounded(5).bg(t.raised)
                    .items_center().text_size(11).font_medium().text_color(t.foreground).cursor_pointer()
                    .hover(s => s.bg(t.solid).text_color(t.solid_foreground))
                    .on_click((_e, cx) => { cx.stop_propagation(); pickRemoteEntry(v, entry, cx); })
                    .child(text('add'))))))))
          .child(Scrollbar.new('remote-picker-scroll').absolute().inset_0()));
    });

  const hint = open.length ? h_flex().px(10).py(7).gap(8).rounded(8).bg(withAlpha(t.accent, .1)).items_start().text_size(12).text_color(t.muted)
    .child(h_flex().h(17).items_center().child(icon('alert', 13).text_color(t.accent)))
    .child(div().flex_1().min_w(0).whitespace_normal().line_height('17px')
      .child(text('ledgerOpen', effName, open.length, open.slice(0, 3).map(x => x.title).join('、')))) : null;

  const installed = v.agentStatus[machine] || null;
  const kindColors = { claude: t.ansi3, agy: t.accent, codex: t.ansi2, pi: t.muted };
  const nameHint = !f.folders.length ? text('readyZeroFolders') : effName ? text('spacePreview', effName, machine) : '';
  const managerHint = probe?.defaultKind ? `${probe.defaultKind}` : '';

  const formBody = v_flex().gap(14)
    .when(Boolean(machineRow), el => el.child(machineRow))
    .child(field(machine ? text('foldersOnMachine', machine) : text('folders'), t, v_flex().gap(6)
      .when(f.folders.length > 0, el => el.child(folderList))
      .child(machine ? remoteAddRow : localAddRow)
      .when(Boolean(hint), el => el.child(hint)), foldersRight))
    .child(field(text('name'), t, Input.new(v.nameInput).h(38).px(12).items_center().rounded(9).border_1()
      .border_color(t.input || t.border).bg(t.background).text_size(14).text_color(t.foreground), nameHint))
    .child(field(text('manager'), t, choice('new-kind', KINDS.map(k => {
      const missing = Boolean(installed && !installed.has(k));
      const labelText = missing ? `${agentName(k)} · ${text('notInstalled')}` : agentName(k);
      return [k, labelText, kindColors[k] || t.dim, { dimmed: missing, alwaysColorDot: !missing }];
    }), f.kind, k => { v.kindTouched = true; f.kind = k; }, t), managerHint))
    .when(Boolean(probe?.error), el => el.child(div().whitespace_normal().text_size(12).text_color(t.blocked).child(probe.error)))
    .when(Boolean(v.failure), el => el.child(div().whitespace_normal().text_size(12).text_color(t.blocked)
      .child(text('failedAction', v.failure))));

  return v_flex().size_full().p(22).gap(14).bg(t.popover).text_color(t.foreground).text_size(14)
    .child(h_flex().flex_none().items_center()
      .child(div().flex_1().text_size(17).font_semibold().child(text('newProject')))
      .child(iconButton(v, 'new-close', 'close', text('cancel'), close, t, { placement: 'below-right' })))
    .child(div().relative().flex_1().min_h(0).w_full()
      .child(div().id('new-dialog-scroll').size_full().overflow_y_scroll().child(formBody))
      .child(Scrollbar.new('new-dialog-scroll').absolute().inset_0()))
    .child(h_flex().flex_none().gap(10).items_center().pt(6).border_t(1).border_color(t.border)
      .child(div().flex_1().min_w(0).truncate().text_size(12).text_color(t.dim)
        .child(v.busy ? text('creating') : text('dedicatedSpaceHint', effName, machine)))
      .child(div().flex_none().text_size(12).text_color(t.dim).child('⌘↵'))
      .child(tipWrap(v, 'new-submit', h_flex().id('new-submit').size(34).flex_none().rounded(17).items_center().justify_center()
        .bg(ready ? t.solid : t.raised).text_color(ready ? t.solid_foreground : t.muted)
        .accessibility_label(text('create'))
        .when(ready, el => el.cursor_pointer().on_click((_e, cx) => submitNew(v, cx)))
        .child(v.busy ? svg(SPINNER).size(15).spin(900) : icon('send', 15)), text('create'), t, { placement: 'above-right' })));
}

function archiveDialog(v, t) {
  const lang = v.local.lang, text = (k, ...a) => word(lang, k, ...a);
  const targetPmName = v.dialogMachine ? v.dialogSourcePm : v.dialogPm;
  const pm = (v.local.pms || []).find(p => p.name === targetPmName);
  const threads = archiveThreads(v.local, targetPmName);
  const ready = Boolean(pm) && !v.busy;
  return v_flex().size_full().px(16).py(14).gap(10).bg(t.popover).text_color(t.foreground).text_size(13)
    .child(h_flex().gap(8).items_center()
      .child(icon('archive', 15))
      .child(div().flex_1().min_w(0).truncate().text_size(15).font_semibold().child(text('archiveTitle', pm ? projectName(pm) : '…')))
      .when(Boolean(v.dialogMachine), el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(v.dialogMachine))))
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

function renameDialog(v, t) {
  const lang = v.local.lang, text = (k, ...a) => word(lang, k, ...a);
  const pm = (v.local.pms || []).find(p => p.name === v.dialogPm);
  const check = pm ? validateProjectName(v.form.name, lang, { pms: v.local.pms, currentPm: pm.name }) : { ok: false, error: '' };
  const ready = Boolean(pm) && check.ok && !v.busy;
  return v_flex().size_full().p(20).gap(14).bg(t.popover).text_color(t.foreground).text_size(14)
    .child(h_flex().items_center().gap(8)
      .child(icon('pencil', 15).text_color(t.muted))
      .child(div().flex_1().min_w(0).truncate().text_size(16).font_semibold()
        .child(pm ? text('renameTitle', projectName(pm)) : text('renameProject')))
      .child(iconButton(v, 'rename-close', 'close', text('cancel'), close, t, { placement: 'below-right' })))
    .child(v_flex().gap(6)
      .child(Input.new(v.renameInput).h(40).px(12).items_center().rounded(10).border_1()
        .border_color(v.failure ? t.blocked : (t.input || t.border)).bg(t.background).text_size(14).text_color(t.foreground))
      .child(div().whitespace_normal().text_size(12).text_color(v.failure ? t.blocked : t.dim)
        .child(v.failure || text('renameHint'))))
    .child(div().flex_1())
    .child(h_flex().gap(8).justify_end().items_center()
      .child(h_flex().id('rename-cancel').h(32).px(12).rounded(8).items_center().cursor_pointer().text_color(t.muted)
        .hover(s => s.bg(t.hover).text_color(t.foreground)).on_click(close).child(text('cancel')))
      .child(h_flex().id('rename-confirm').h(32).px(14).gap(6).rounded(8).items_center()
        .bg(ready ? t.solid : t.raised).text_color(ready ? t.solid_foreground : t.muted).font_semibold().opacity(v.busy ? .6 : 1)
        .when(ready, el => el.cursor_pointer().hover(s => s.opacity(.88)).on_click((_e, cx) => submitRename(v, cx)))
        .when(v.busy, el => el.child(svg(SPINNER).size(14).spin(900)))
        .child(v.busy ? text('saving') : text('save'))));
}

export function dialogView(v, t, cx) {
  if (cx) v._lastCx = cx;
  const submit = v.dialog === 'new' ? submitNew : v.dialog === 'rename' ? submitRename : confirmArchive;
  const content = v.dialog === 'new' ? newDialog(v, t) : v.dialog === 'rename' ? renameDialog(v, t) : archiveDialog(v, t);
  return div().id('pm-dialog').size_full().track_focus(v.handle)
    .on_key_down((e, cx) => {
      if (e.keystroke === 'escape') {
        if (v.dialog === 'new' && v.picker?.open) { v.picker.open = false; cx.notify(); }
        else close();
      } else if (e.keystroke === 'cmd-enter') submit(v, cx);
      else return;
      cx.stop_propagation();
    })
    .child(content);
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
