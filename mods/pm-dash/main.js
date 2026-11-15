import { View, div, svg, PathBuilder } from 'gpui-kit';
import { v_flex, h_flex, Scrollbar, Popup } from 'gpui-base';
import { theme, home, appHome, exec, readTextFile, watchFolder, terminals, agents, panes, run, props, closeOverlay, openOverlay, layout as desktopLayout } from 'herdr';
import { setupState, fitBoard, withAlpha, solidText, isDarkTheme, cleanTaskLog, hoverCardPosition, newEvents, pmId, taskId, eventText, terminalFor, terminalTargetFor, focusPlan, pmColor, counts, wireFlows, word, label, taskStatusText, mergeStates, cachedRemoteStates, LEDGER_HOME_SH, remoteStateCommand, pmStatusText, scopeState, archiveThreads, disconnected, escapeTarget, DROPPED, endedTime } from './model.js';
import { page, pageView, pageHeader, projectHeader, keepPress, dialogView, initDialog, restoreProject, readLines, archivePopup, NEW_DIALOG, openProject, showPage } from './projects.js';

import { FlowLayer, boardVisible } from './flow.js';

// Keep the full mods/<name>/ prefix: Herdr rewrites it when cloning this mod.
const MOD_FOLDER = 'mods/pm-dash/';
const STAGE = 'pm-stage', WORK = 'work';

function findMod(node, mod) {
  if (node?.content?.mod === mod) return node;
  for (const child of node?.children ?? []) {
    const found = findMod(child, mod);
    if (found) return found;
  }
  return null;
}

export default class PmDash extends View {
  init(_props, cx) {
    this.state = { pms: [], tasks: [], events: [] };
    // Opened as one of its own dialogs (new project, archive): only what the dialog needs.
    if (props()?.dialog) { initDialog(this, cx); return; }
    // The Projects page: every project merged (allState), the PM's newest sentence per local project
    // (lines), and which board shows (scope: one project's PM name, or '' for all of them).
    this.allState = this.state; this.lines = {}; this.scope = ''; this.hoverCard = null;
    // The ended nodes, by PM name: opened in place, showing their abandoned tasks, under the pointer.
    this.endedOpen = new Set(); this.showDropped = new Set(); this.hoverEnded = null;
    // The page's keyboard, for Esc: taken each time the stage turns to this page, and on a click in it.
    this.keys = cx.focus_handle(); this.onStage = false;
    this.setupStatus = null; this.setupError = ''; this.setupBusy = false; this.setupDone = false;
    this.localState = this.state; this.remoteStates = {};
    this.primed = false; this.size = { width: 980, height: 640 };
    this.queue = []; this.recent = []; this.replayIndex = 0; this.auto = false;
    this.flowLayer = cx.new(FlowLayer);
    this.flowKey = ''; this.hoverTask = null;
    this.shownStatus = {}; this.shownLive = {}; this.hoverPm = null;
    this.shown = {}; this.statuses = {}; this.tags = {}; this.nudges = {};
    this.serial = 0; this.trip = null; this.lastEvent = Date.now();
    this.packetFinished = token => this.finishTrip?.(token);
    // Keep the parent async context in its own task. Child hops never notify it;
    // only a completed event wakes this task to commit the row text/status.
    cx.spawn(async cx => {
      for (;;) {
        const token = await new Promise(resolve => { this.finishTrip = resolve; });
        if (this.trip?.token === token) this.land(cx);
      }
    });
    cx.spawn(async cx => { await this.checkSetup(); cx.notify(); });
    this.ledgerHome = ''; this.homeKnown = new Promise(resolve => { this.resolveHome = resolve; });
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
    cx.spawn(async cx => {
      try {
        const cached = cachedRemoteStates(await readTextFile(await this.homeKnown + '/cache/remote-states.json'));
        if (cached) { this.remoteStates = cached; this.publish(cx); }
      } catch (_) { /* An absent, unreadable or invalid cache does not block live reads. */ }
      // Start live reads after restoration so a late cache cannot replace them.
      this.refreshRemote(cx);
      cx.timer.every(5000, cx => this.refreshRemote(cx));
    });
    cx.timer.every(10000, cx => this.refresh(cx));
    this.armIdle(cx);
  }
  // Watch <ledger home>/tasks. A different home (the first state correcting the
  // fallback, or PM_HOME changing) arms a new watcher; the old one stops at its next wake.
  setLedgerHome(path, cx) {
    if (typeof path !== 'string' || !path || path === this.ledgerHome) return;
    this.ledgerHome = path; this.resolveHome(path);
    cx.spawn(async cx => {
      try {
        while (this.ledgerHome === path) {
          await watchFolder(path + '/tasks');
          if (this.ledgerHome === path) this.refresh(cx);
        }
      } catch (_) { /* Missing folder/watch failure: the 10s fallback remains active. */ }
    });
  }
  text(key, ...args) { return word(this.state.lang, key, ...args); }
  today() {
    const d = new Date(), pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }
  openNew() { openOverlay(NEW_DIALOG); }
  openArchive(pm) { openOverlay(archivePopup(pm, archiveThreads(this.localState, pm).length)); }
  restore(card, cx) { restoreProject(this, card, cx); }
  // Another board (all projects, or one): its rows start over, with no packets for what was already there.
  rescope(scope, cx) {
    this.scope = scope; this.primed = false; this.queue = []; this.trip = null; this.serial++;
    this.shown = {}; this.shownStatus = {}; this.shownLive = {}; this.statuses = {}; this.hoverTask = null; this.hoverPm = null;
    this.endedOpen.clear(); this.hoverEnded = null;
    this.publish(cx);
  }
  async checkSetup() {
    try {
      const result = await exec('python3', [appHome() + '/' + MOD_FOLDER + 'setup.py', '--status', '--claude-home', home() + '/.claude']);
      if (result.code !== 0) throw new Error(result.stderr || result.stdout || `setup.py: ${result.code}`);
      const status = JSON.parse(result.stdout);
      this.setupStatus = setupState(status); this.setupError = status.error || '';
    } catch (error) { this.setupStatus = 'missing'; this.setupError = String(error); }
  }
  setUp(cx) {
    if (this.setupBusy) return;
    this.setupBusy = true; this.setupError = ''; this.setupDone = false; cx.notify();
    cx.spawn(async cx => {
      try {
        const result = await exec('python3', [appHome() + '/' + MOD_FOLDER + 'setup.py', '--claude-home', home() + '/.claude']);
        if (result.code !== 0) throw new Error(result.stderr || result.stdout || `setup.py: ${result.code}`);
        await this.checkSetup();
        this.setupDone = this.setupStatus === 'ready';
        if (!this.setupDone && !this.setupError) this.setupError = this.text('setupIncomplete');
        if (this.setupDone) this.refresh(cx);
      } catch (error) { this.setupError = String(error); }
      finally { this.setupBusy = false; run('pm-nav.setup-changed'); cx.notify(); }
    });
  }
  setupButton(t, label, quiet = false) {
    return div().id('pm-setup-action').px(quiet ? 8 : 18).py(quiet ? 4 : 9).rounded(8).flex_none()
      .text_size(13).font_semibold().cursor_pointer()
      .bg(quiet ? t.surface : t.foreground).text_color(quiet ? t.foreground : solidText(t.foreground, t))
      .opacity(this.setupBusy ? .5 : 1)
      .on_click((_event, cx) => this.setUp(cx)).child(this.text(this.setupBusy ? 'settingUp' : label));
  }
  setupView(t) {
    const block = v_flex().w_full().max_w(480).flex_none().p(28).gap(16).rounded(20).bg(t.surface).items_center()
      .child(svg('mods/pm-dash/dudu.svg').size(36).text_color(t.foreground))
      .child(div().text_size(22).font_semibold().child(this.text('setupTitle')));
    if (this.setupStatus === null) block.child(div().text_color(t.muted).child(this.text('checkingSetup')));
    else {
      block.child(div().w_full().whitespace_normal().line_height('20px').text_color(t.muted).child(this.text('setupDescription')));
      if (this.setupError) block.child(div().w_full().whitespace_normal().text_color(t.blocked).child(this.setupError));
      block.child(this.setupButton(t, 'setup'));
    }
    return v_flex().id('setup-root').size_full().min_w(0).min_h(0).bg(t.canvas).text_color(t.foreground).text_size(13)
      .child(keepPress(this, v_flex().id('setup-scroll')).size_full().overflow_scroll().p(24)
        .child(v_flex().w_full().flex_1().items_center().justify_center().child(block)));
  }
  geometry() {
    return fitBoard(this.state, this.size.width, this.size.height,
      this.measuredWidth === this.size.width ? this.fixedHeight : undefined,
      { open: [...this.endedOpen], dropped: [...this.showDropped], today: this.today() });
  }
  // The ended node's preview shows while the pointer is on a folded node.
  peeking() { return this.hoverEnded !== null && !this.endedOpen.has(this.hoverEnded); }
  toggle(set, pm, cx) {
    if (set.has(pm)) set.delete(pm); else set.add(pm);
    cx.notify();
  }
  refresh(cx) {
    if (this.loading) { this.again = true; return; }
    this.loading = true;
    cx.spawn(async cx => {
      try {
        const result = await exec('python3', [appHome() + '/' + MOD_FOLDER + 'skill/scripts/pm.py', 'state']);
        if (result.code !== 0) throw new Error(result.stderr || `pm.py: ${result.code}`);
        const next = JSON.parse(result.stdout);
        if (!['pms', 'tasks', 'events'].every(k => Array.isArray(next[k]))) throw new Error('state is missing pms/tasks/events arrays');
        this.localState = next; this.error = '';
        this.setLedgerHome(next.home, cx);
        this.publish(cx);
        if (!page().project && page().view !== 'board') { this.lines = await readLines(next.pms); cx.notify(); }
      } catch (e) { this.error = String(e); cx.notify(); }
      finally {
        this.loading = false;
        if (this.again) { this.again = false; this.refresh(cx); }
      }
    });
  }
  refreshRemote(cx) {
    if (this.remoteLoading || (!props()?.overlay && !boardVisible(desktopLayout()))) return;
    this.remoteLoading = true;
    cx.spawn(async cx => {
      try {
        const result = await exec('hc', ['machine', 'ls', '--json'], { timeout: 4000 });
        if (result.code !== 0) return;
        const listing = JSON.parse(result.stdout);
        const machines = Array.isArray(listing) ? listing : listing?.machines;
        if (!Array.isArray(machines) || (!props()?.overlay && !boardVisible(desktopLayout()))) return;
        const names = [...new Set(machines.filter(m => m.state === 'connected' && typeof m.name === 'string' && m.name).map(m => m.name))];
        // Disconnects remove rows; a transient read failure retains the last good snapshot.
        for (const name of Object.keys(this.remoteStates)) if (!names.includes(name)) delete this.remoteStates[name];
        await Promise.all(names.map(async name => {
          try {
            const r = await exec('hc', ['exec', '--on', name, remoteStateCommand()], { timeout: 4000 });
            if (r.code !== 0) return;
            const state = JSON.parse(r.stdout);
            if (['pms', 'tasks', 'events'].every(k => Array.isArray(state[k]))) this.remoteStates[name] = state;
          } catch (_) { /* One unavailable machine must not interrupt the others. */ }
        }));
        this.publish(cx);
      } catch (_) { /* Discovery failures leave the last good board intact. */ }
      finally { this.remoteLoading = false; }
    });
  }
  publish(cx) {
    this.allState = mergeStates(this.localState, this.remoteStates);
    const next = scopeState(this.allState, this.scope);
    const known = new Set([...this.state.pms, ...this.state.tasks, ...this.state.events].map(row => row.machine));
    const fresh = newEvents(this.primed ? this.state : null, next).filter(e => known.has(e.machine));
    this.state = next; this.primed = true;
    this.recent = next.events.slice(-12);
    if (fresh.length) {
      this.lastEvent = Date.now(); this.replayIndex = 0;
      if (this.trip?.replay) { this.serial++; this.trip = null; }
      this.queue.push(...fresh); this.armIdle(cx);
    }
    // Hold both task and PM text until all announced events for that row arrive.
    const pending = [...this.queue, ...(this.trip && !this.trip.replay ? [this.trip.event] : [])];
    for (const row of this.geometry().rows) {
      const held = pending.some(e => row.id === taskId(e.task) || row.id === pmId(e.pm));
      if (!held) { this.shown[row.id] = row.latest || ''; this.shownStatus[row.id] = row.status; }
      else if (!(row.id in this.shown)) { this.shown[row.id] = ''; this.shownStatus[row.id] = row.status; }
    }
    this.next(cx); cx.notify();
  }
  armIdle(cx) {
    this.idleTimer?.cancel();
    this.idleTimer = cx.timer.after(20000, cx => this.next(cx));
  }
  tag(id, status, cx, nudge = false) {
    const tag = { text: label(this.state.lang, status) }; this.tags[id] = tag;
    if (nudge) {
      this.nudges[id] = 6;
      cx.timer.after(90, cx => { this.nudges[id] = 0; cx.notify(); });
    }
    cx.timer.after(220, cx => {
      if (this.tags[id] === tag) { delete this.tags[id]; cx.notify(); }
    });
  }
  next(cx) {
    if (this.trip) return;
    const replay = !this.queue.length;
    if (replay && (!this.auto || Date.now() - this.lastEvent < 20000 || !this.recent.length)) return;
    const event = replay ? this.recent[this.replayIndex++ % this.recent.length] : this.queue.shift();
    // A task's route: its bundle's trunk, then its own branch; an ended task's, the ended node's line.
    const g = this.geometry(), chat = pmId(event.pm), task = (event.task && g.routes[taskId(event.task)]) || [];
    const routes = event.kind === 'prompt' || event.kind === 'reply' ? [chat] :
      event.kind === 'dispatch' && event.by === 'user' ? [chat, ...task] : task;
    const valid = routes.filter(id => g.wires.some(w => w.id === id));
    const reverse = event.kind === 'reply' || event.kind === 'report';
    if (reverse) valid.reverse(); // Back toward the PM: the branch first, then the trunk.
    this.trip = { event, replay, routes: valid, reverse, token: ++this.serial };
    if (!valid.length) { this.land(cx); return; }
    cx.notify();
  }
  land(cx) {
    const tr = this.trip;
    if (!tr) return;
    const e = tr.event;
    if (!tr.replay) {
      if (e.task) this.shown[taskId(e.task)] = eventText(e, this.state.lang);
      this.shown[pmId(e.pm)] = eventText(e, this.state.lang);
      if (e.task) {
        const row = this.state.tasks.find(t => t.id === e.task);
        this.shownStatus[taskId(e.task)] = e.status || this.shownStatus[taskId(e.task)] || row?.status;
      }
    }
    // A review's event (mergeStates) tags its task with what the review is, and leaves the task's status.
    if (e.task) this.tag(taskId(e.task), e.review || e.status, cx);
    else this.tag(pmId(e.pm), e.status, cx);
    this.trip = null; cx.notify();
    cx.timer.after(400, cx => this.next(cx));
  }
  presentation(row, terms, live) {
    const { terminal, exact } = row.type ? terminalTargetFor(row, terms) : { terminal: null, exact: false };
    const actual = exact ? live.find(a => a.address === terminal.address)?.status || terminal.status || 'unknown' :
      row.type === 'task' ? row.worker || row.status : row.status;
    const pending = [...this.queue, ...(this.trip && !this.trip.replay ? [this.trip.event] : [])];
    const held = pending.some(e => row.id === taskId(e.task) || row.id === pmId(e.pm));
    if (!held || !(row.id in this.shownLive)) this.shownLive[row.id] = actual;
    if (!held) this.shownStatus[row.id] = row.status;
    return { ...row, terminal, terminalExact: exact, status: this.shownStatus[row.id] || row.status, live: this.shownLive[row.id] };
  }
  projectColor(name, t) {
    const pm = this.state.pms.find(p => (p.name || '') === (name || ''));
    // Source names keep project colors stable across machines and languages;
    // orphan task groups use the mockup's neutral color.
    return pm ? t[pmColor(pm.project || (pm.sourceName ?? pm.name))] : t.dim;
  }
  dim(name) { return this.hoverPm !== null && this.hoverPm !== (name || '') ? .35 : 1; }
  dot(color, solid, _t, size = 8) {
    return div().w(size).h(size).flex_none().rounded(size / 2)
      .when(solid, el => el.bg(color))
      .when(!solid, el => el.border(1).border_color(color));
  }
  taskPill(row, t, scale, maxWidth, id = `status:${row.id}`) {
    const px = n => n * scale, font = n => Math.max(10, px(n));
    const waiting = !row.cleanup && row.status === 'blocked' && !row.answered;
    const running = !row.cleanup && row.status === 'in_progress' && !disconnected(row);
    const review = !row.cleanup && row.status === 'review';
    const color = waiting ? t.blocked : review ? t.accent : running ? t.ansi2 : t.dim;
    return div().id(id).max_w(maxWidth).flex_shrink_0().truncate()
      .px(px(8)).py(px(2)).rounded(px(10)).text_size(font(11.5)).font_semibold()
      .line_height(`${Math.max(12, px(18))}px`)
      .text_color(waiting ? solidText(color, t) : row.cleanup ? t.muted : color)
      .when(waiting, el => el.bg(color))
      .when(running, el => el.bg(withAlpha(t.ansi2, .15)))
      .opacity(this.tags[row.id] ? .4 : 1).transition('opacity', 180)
      .child(running ? label(this.state.lang, 'in_progress') : taskStatusText(this.state.lang, row));
  }
  hoverBounds(key, bounds, cx) {
    const previous = this[key];
    if (previous && ['x', 'y', 'width', 'height'].every(k => previous[k] === bounds[k])) return;
    this[key] = bounds;
    if (this.hoverTask || this.peeking()) cx.notify();
  }
  taskInfoCard(row, g, t) {
    if (!this.stageBounds || !this.boardBounds) return null;
    const scale = g.scale, px = n => n * scale, font = n => Math.max(10, px(n));
    const viewport = { top: this.boardBounds.y - this.stageBounds.y,
      bottom: this.boardBounds.y + this.boardBounds.height - this.stageBounds.y };
    const width = Math.min(px(520), row.w), details = cleanTaskLog(row.latest);
    const pm = this.state.pms.find(p => p.name === row.pm);
    const project = pm?.project || row.project || (pm?.sourceName ?? pm?.name) || this.text('unassigned');
    const metadata = [project, row.branch, details.commit, row.updated].filter(Boolean).join(' · ');
    const key = JSON.stringify([row.id, row.title, row.status, row.cleanup, row.live, row.latest, metadata,
      Boolean(row.terminal), width, scale, g.height, viewport.top, viewport.bottom]);
    if (this.hoverMeasure?.key !== key) {
      this.hoverMeasure = { key, serial: (this.hoverMeasure?.serial || 0) + 1, height: 0, textHeight: 0 };
    }
    const measured = this.hoverMeasure;
    const headingHeight = Math.max(16, px(22)), metaHeight = Math.max(12, px(16));
    const hintHeight = Math.max(12, px(14)), lineHeight = Math.max(15, px(19));
    const fixed = px(24) + headingHeight + metaHeight + px(16) + (row.terminal ? hintHeight + px(8) : 0);
    const position = hoverCardPosition(row, g.height, viewport, measured.height || fixed + lineHeight * 4, scale);
    if (!position) return null;
    const bodyHeight = Math.min(4, Math.max(0, Math.floor((position.h - fixed + .001) / lineHeight))) * lineHeight;
    const fill = [t.raised, t.popover, t.selected].find(color => color && color !== t.surface) || t.raised;
    const textColor = withAlpha(t.foreground, .85);
    const card = v_flex().id(`task-info:${measured.serial}`).w(position.w).max_h(position.h).flex_none()
      .rounded(px(12)).px(px(14)).py(px(12)).gap(px(8)).bg(fill).overflow_hidden()
      .on_size_change((size, cx) => {
        if (this.hoverMeasure === measured && Math.abs(size.height - measured.height) > .5) {
          measured.height = size.height; cx.notify();
        }
      })
      .child(h_flex().h(headingHeight).flex_none().gap(px(8)).items_center()
        .child(this.taskPill(row, t, scale, (position.w - px(28)) * .55, `info-status:${row.id}`))
        .child(div().flex_1().min_w(0).truncate().text_size(font(13)).font_semibold().text_color(t.foreground).child(row.title)))
      .child(div().h(metaHeight).flex_none().line_height(`${metaHeight}px`).truncate()
        .text_size(font(11)).text_color(t.muted).child(metadata))
      .child(div().relative().flex_none().max_h(bodyHeight).overflow_hidden()
        .child(div().id(`task-log:${measured.serial}`).w_full().flex_none().whitespace_normal()
          .text_size(font(12.5)).line_height(`${lineHeight}px`).text_color(textColor)
          .on_size_change((size, cx) => {
            if (this.hoverMeasure === measured && Math.abs(size.height - measured.textHeight) > .5) {
              measured.textHeight = size.height; cx.notify();
            }
          }).child(details.text || this.text('noLogs')))
        // The kit has no multiline clamp. Clip native wrapping at four lines
        // and cover the last few glyphs with an ellipsis only on real overflow.
        .when(bodyHeight > 0 && measured.textHeight > bodyHeight + .5, el => el.child(div().absolute().right(0).bottom(0)
          .h(lineHeight).line_height(`${lineHeight}px`).pl(px(4)).bg(fill).text_color(textColor).text_size(font(12.5)).child('…'))))
      .when(Boolean(row.terminal), el => el.child(div().h(hintHeight).flex_none().line_height(`${hintHeight}px`)
        .text_size(font(11)).text_color(t.dim).child(this.text('openTerminal'))));
    // A zero-height anchor lives in the scrolled stage. Popup supplies only
    // the floating paint layer; it owns no click, focus or dismissal handler.
    // The card itself has no pointer handlers, so leaving the row closes it.
    return Popup.new(`task-info-popup:${row.id}`, div().w(position.w).h(0))
      .absolute().left(position.x).top(position.y).w(position.w).h(0).anchor('top_left').content(card);
  }
  // The ended node's preview: its newest few, right-aligned under (or over) the node like a task's card.
  endedPeek(row, g, t) {
    if (!this.stageBounds || !this.boardBounds) return null;
    const scale = g.scale, px = n => n * scale, font = n => Math.max(10, px(n)), today = this.today();
    const viewport = { top: this.boardBounds.y - this.stageBounds.y,
      bottom: this.boardBounds.y + this.boardBounds.height - this.stageBounds.y };
    const line = Math.max(18, px(24)), more = Math.max(16, px(22)), pad = px(8);
    const position = hoverCardPosition(row, g.height, viewport, pad * 2 + row.peek.length * line + more, scale);
    if (!position) return null;
    const width = Math.min(px(360), row.w);
    const fill = [t.raised, t.popover, t.selected].find(color => color && color !== t.surface) || t.raised;
    const card = v_flex().id(`ended-peek:${row.pm}`).w(width).max_h(position.h).flex_none().px(px(6)).py(pad)
      .rounded(px(12)).bg(fill).overflow_hidden();
    for (const task of row.peek) {
      card.child(h_flex().h(line).flex_none().px(px(8)).gap(px(10)).items_center().text_size(font(12.5))
        .child(div().flex_1().min_w(0).truncate().text_color(t.foreground).child(task.title || task.sourceId || task.id))
        .child(div().flex_none().text_color(t.muted)
          .child([taskStatusText(this.state.lang, task), endedTime(task.updated, today)].filter(Boolean).join(' · '))));
    }
    card.child(div().h(more).flex_none().line_height(`${more}px`).px(px(8)).text_size(font(11.5)).text_color(t.dim)
      .child(this.text('endedMore', row.count)));
    return Popup.new(`ended-peek-popup:${row.pm}`, div().w(width).h(0))
      .absolute().left(row.x + row.w - width).top(position.y).w(width).h(0).anchor('top_left').content(card);
  }
  bundleColor(status, t) {
    return status === 'blocked' ? t.blocked : status === 'review' ? t.accent : status === 'in_progress' ? t.ansi2 : t.muted;
  }
  // What the board draws around the ledger's rows: a bundle's heading and fork, the ended node, its day headings.
  bundleRow(row, t, scale) {
    const px = n => n * scale, font = n => Math.max(10, px(n)), pm = row.pm;
    if (row.type === 'label') return h_flex().absolute().left(row.x).top(row.y).h(row.h).gap(px(6)).items_center()
      .text_size(font(11.5)).opacity(this.dim(pm)).transition('opacity', 160)
      .child(div().font_semibold().text_color(this.bundleColor(row.status, t)).child(row.title))
      .child(div().text_color(t.dim).child(String(row.count)));
    if (row.type === 'junction') return div().absolute().left(row.x).top(row.y + row.h / 2 - row.w / 2).w(row.w).h(row.w)
      .rounded(row.w / 2).bg(this.projectColor(pm, t)).opacity((row.flows ? 1 : .5) * this.dim(pm)).transition('opacity', 160);
    if (row.type === 'day') return div().absolute().left(row.x).top(row.y).h(row.h).line_height(`${row.h}px`)
      .text_size(font(11)).text_color(t.dim).opacity(this.dim(pm)).child(row.title);
    // The ended node: a filled block, never an outline. Click opens it in place; the eye shows the abandoned.
    const tip = this.text(row.showDropped ? 'hideDropped' : 'showDropped', row.dropped);
    return h_flex().id(row.id).absolute().left(row.x).top(row.y).w(row.w).h(row.h).pl(px(12)).pr(px(8)).gap(px(10))
      .items_center().rounded(px(10)).bg(t.raised).text_size(font(13)).text_color(t.muted).cursor_pointer()
      .opacity(this.dim(pm)).transition('opacity', 160)
      .on_hover((over, cx) => {
        if (over) this.hoverEnded = pm;
        else if (this.hoverEnded === pm) this.hoverEnded = null;
        cx.notify();
      })
      .on_click((_e, cx) => this.toggle(this.endedOpen, pm, cx))
      .child(svg('mods/pm-dash/check.svg').size(px(15)).flex_none().text_color(t.muted))
      .child(div().flex_none().font_semibold().text_color(t.foreground).child(this.text('endedCount', row.count)))
      .child(div().flex_1().min_w(0).truncate().text_size(font(12.5)).text_color(t.dim)
        .child(row.recent.length ? this.text('endedRecent', row.recent.join(' · ')) : ''))
      .when(row.dropped > 0, el => el.child(h_flex().id(`dropped:${pm}`).flex_none().gap(px(4)).px(px(6)).py(px(3))
        .rounded(px(6)).items_center().text_size(font(11.5)).text_color(row.showDropped ? t.foreground : t.dim)
        .when(row.showDropped, el => el.bg(t.surface)).hover(s => s.bg(t.surface))
        .tooltip(tip).accessibility_label(tip)
        .on_click((_e, cx) => {
          cx.stop_propagation();
          if (!this.showDropped.has(pm)) this.endedOpen.add(pm); // Shown where they are: in the opened list.
          this.toggle(this.showDropped, pm, cx);
        })
        .child(svg(`mods/pm-dash/${row.showDropped ? 'eye' : 'eye-off'}.svg`).size(px(14)).flex_none()
          .text_color(row.showDropped ? t.foreground : t.dim))
        .child(String(row.dropped))))
      .child(svg(`mods/pm-dash/${row.open ? 'chevron-down' : 'chevron'}.svg`).size(px(14)).flex_none().text_color(t.muted));
  }
  row(row, t, cx, total, scale) {
    const px = n => n * scale, font = n => Math.max(10, px(n));
    if (['label', 'junction', 'ended', 'day'].includes(row.type)) return this.bundleRow(row, t, scale);
    const dark = !row.type && isDarkTheme(t);
    if (!row.type) return v_flex().absolute().left(row.x).top(row.y).w(row.w).h(row.h)
      .rounded(px(20)).bg(dark ? t.raised : t.foreground).text_color(dark ? t.foreground : t.background).px(px(12)).py(px(12))
      .items_center().justify_center().gap(px(4))
      // Numeric line_height means a font multiplier, so use explicit pixels.
      .child(svg('mods/pm-dash/dudu.svg').size(px(28)).flex_none().text_color(dark ? t.foreground : t.background))
      .child(div().h(px(24)).line_height(`${px(24)}px`).flex_none().whitespace_nowrap().text_size(font(18)).font_bold().child('dudu'))
      .child(div().h(Math.max(12, px(18))).line_height(`${Math.max(12, px(18))}px`).flex_none().whitespace_nowrap()
        .text_size(font(12)).text_color(dark ? t.muted : t.background).opacity(dark ? 1 : .62).child(this.text('allProjects')))
      .child(div().h(Math.max(12, px(16)) + px(6)).line_height(`${Math.max(12, px(16))}px`).flex_none()
        .whitespace_nowrap().mt(px(4)).px(px(11)).py(px(3)).rounded(px(12)).text_size(font(11)).font_semibold()
        .when(total.waiting > 0, el => el.bg(t.blocked).text_color(solidText(t.blocked, t)))
        .when(!total.waiting, el => el.opacity(.62))
        .child(total.waiting ? this.text('waiting', total.waiting) : this.text('nothingWaiting')));
    const pm = row.type === 'pm' ? row.name : row.pm, color = this.projectColor(pm, t);
    const signature = `${row.status || ''}/${row.live || ''}`;
    if (this.statuses[row.id] !== signature) {
      const before = this.statuses[row.id]; this.statuses[row.id] = signature;
      if (before !== undefined) {
        const blocked = row.status === 'blocked' || row.live === 'blocked';
        this.tag(row.id, row.status, cx, blocked && !before.split('/').includes('blocked'));
      }
    }
    const working = row.live === 'working';
    let el = h_flex().id(row.id).absolute().left(row.x).top(row.y).w(row.w).h(row.h)
      .px(px(12)).gap(px(10)).items_center().rounded(px(12)).text_size(font(13))
      .line_height(`${Math.max(12, px(18))}px`).opacity(this.dim(pm)).transition('opacity', 160);
    if (row.type === 'pm') {
      const away = !row.terminalExact;
      const statusColor = working ? t.ansi2 : t.muted;
      el = el.when(!away, el => el.bg(t.surface))
        .when(away, el => el.tooltip(this.text(row.terminal ? 'pmProjectFallback' : 'pmDesktopMissing')))
        .child(div().absolute().left(px(-3)).top(row.h / 2 - px(3)).w(px(6)).h(px(6)).rounded(px(3)).bg(color))
        .on_hover((over, cx) => {
          if (over) this.hoverPm = row.name || '';
          else if (this.hoverPm === (row.name || '')) this.hoverPm = null;
          cx.notify();
        })
        .child(h_flex().w(px(28)).h(px(28)).flex_none().rounded(px(8))
          .bg(away ? withAlpha(color, .16) : color).text_color(away ? color : solidText(color, t))
          .items_center().justify_center().font_bold().child([...row.title][0]?.toUpperCase() || '?'))
        .child(v_flex().flex_1().min_w(0).gap(px(1))
          .child(h_flex().gap(px(4)).items_center()
            .child(div().id(`title:${row.id}`).relative().left(px(this.nudges[row.id] || 0))
              .spring('left', { response: 320, damping: .35 }).flex_1().min_w(0).truncate().text_size(font(13.5))
              .text_color(away ? t.muted : t.foreground).font_weight(away ? 500 : 600).child(row.title))
            .when(Boolean(row.machineNumber), el => el.child(div().flex_none().text_size(font(10))
              .font_family('monospace').text_color(t.dim).child(String(row.machineNumber)))))
          .child(h_flex().id(`status:${row.id}`).gap(px(5)).items_center().text_size(font(11.5)).text_color(statusColor)
            .opacity(this.tags[row.id] ? .4 : 1).transition('opacity', 180)
            .child(this.dot(working ? t.ansi2 : t.dim, true, t, px(6)))
            .child(div().flex_1().min_w(0).truncate().child(pmStatusText(this.state.lang, row)))))
        .when(row.waiting > 0, el => el.child(h_flex().min_w(px(20)).h(Math.max(14, px(20))).px(px(6))
          .flex_none().rounded(px(10)).items_center().justify_center().text_size(font(11.5)).font_bold()
          .bg(t.blocked).text_color(solidText(t.blocked, t)).child(String(row.waiting))));
    } else {
      const waiting = !row.cleanup && row.status === 'blocked' && !row.answered;
      const running = !row.cleanup && row.status === 'in_progress' && !disconnected(row);
      const review = !row.cleanup && row.status === 'review';
      const statusColor = waiting ? t.blocked : review ? t.accent : running ? t.ansi2 : t.dim;
      el = el.on_hover((over, cx) => {
        if (over) this.hoverTask = row.task;
        else if (this.hoverTask === row.task) this.hoverTask = null;
        cx.notify();
      }).on_mouse_move((_event, cx) => {
        // Scrolling dismisses the old card; a fresh pointer position can open
        // the current row even if native hover stayed on the same element.
        if (this.hoverTask !== row.task) { this.hoverTask = row.task; cx.notify(); }
      });
      if (row.entry) {
        // An opened ended list's row, hung on the list's guide 8px to its left (layout).
        const dropped = DROPPED.includes(row.status);
        el = el.px(px(8)).rounded(px(6)).text_size(font(12.5)).text_color(t.muted)
          .child(div().absolute().left(-10.5).top(row.h / 2 - 2.5).w(5).h(5).rounded(2.5).bg(t.dim))
          .child(div().id(`title:${row.id}`).flex_1().min_w(0).truncate()
            .when(dropped, el => el.line_through().text_color(t.dim)).child(row.title))
          .when(Boolean(row.branch) && row.w >= 360, el => el.child(div().max_w(Math.min(130, row.w * .22)).truncate()
            .px(px(6)).rounded(px(5)).bg(t.raised).font_family('monospace').text_size(font(11)).opacity(.7).child(row.branch)))
          .child(div().flex_none().font_family('monospace').text_size(font(11)).text_color(t.dim).child(row.time || ''))
          .child(div().id(`status:${row.id}`).flex_none().text_size(font(11.5)).text_color(t.dim)
            .opacity(this.tags[row.id] ? .4 : 1).transition('opacity', 180).child(taskStatusText(this.state.lang, row)));
        if (row.terminal) el = el.cursor_pointer().hover(s => s.bg(t.surface)).on_click(() => this.openTerminal(row));
        return el;
      }
      el = el.rounded(px(8)).bg(waiting ? withAlpha(t.blocked, .12) : t.surface)
        .child(this.dot(statusColor, waiting || running || review, t, px(8)))
        // Nudge only the title: row edges and packet endpoints stay aligned.
        .child(div().id(`title:${row.id}`).relative().left(px(this.nudges[row.id] || 0)).spring('left', { response: 320, damping: .35 })
          .flex_1().min_w(0).truncate().font_weight(waiting ? 600 : 400)
          .text_color(waiting || running ? t.foreground : row.status === 'proposed' ? t.dim : t.muted).child(row.title));
      if (row.branch && row.w >= 360) el = el.child(div().max_w(Math.min(130, row.w * .22)).truncate().px(px(6)).py(px(2)).rounded(px(5))
        .bg(t.raised).text_color(t.muted).font_family('monospace').text_size(font(11)).opacity(waiting || running ? 1 : .7).child(row.branch));
      el = el.child(this.taskPill(row, t, scale, row.w * .48));
    }
    if (row.terminal) el = el.cursor_pointer().hover(s => s.bg(t.raised)).on_click(() => this.openTerminal(row));
    return el;
  }
  openTerminal(row) {
    // A task's fallback is its project's current PM, by the PM's own terminal (never a folder match).
    const terms = terminals(), pm = row.type === 'task' && this.state.pms.find(p => p.name === row.pm);
    const plan = focusPlan(row.terminal.address, terms, [...panes().map(p => p.terminal), ...agents().map(a => a.address)],
      pm ? terminalFor({ ...pm, type: 'pm' }, terms)?.address || '' : '');
    // Nowhere to show it: nothing moves, since showing work would reveal whatever space is active.
    if (!plan.focus) return;
    run('pane.focus', { terminal: plan.focus });
    const overlay = props()?.overlay;
    if (overlay) closeOverlay(overlay);
    else run('layout.select', { stack: STAGE, child: WORK });
    if (plan.peek) run('terminal.peek', { terminal: plan.peek });
  }
  eventLine(e) {
    const task = this.state.tasks.find(t => t.id === e.task);
    const text = eventText(e, this.state.lang);
    const said = e.review ? `${label(this.state.lang, e.review)}${text ? `: ${text}` : ''}` : text;
    return task ? this.text('line', task.title, said || taskStatusText(this.state.lang, task)) : said;
  }
  render(cx) {
    if (this.dialog) return dialogView(this, theme());
    const onStage = !props()?.overlay && boardVisible(desktopLayout());
    if (onStage && !this.onStage) cx.timer.after(0, () => this.keys.focus());
    this.onStage = onStage;
    // Esc, one layer a press (escapeTarget). A dialog over the page has the keyboard: its Esc closes only it.
    return v_flex().id('pm-dash-keys').size_full().min_w(0).min_h(0).track_focus(this.keys)
      .on_mouse_down('left', () => this.keys.focus())
      .on_key_down((e, cx) => {
        const to = e.keystroke === 'escape' ? escapeTarget(this.onStage, page(),
          { hoverCard: Boolean(this.hoverTask) || this.peeking(), ended: this.endedOpen.size > 0 }) : null;
        if (!to) return;
        cx.stop_propagation();
        if (to.hoverCard) { this.hoverTask = null; this.hoverEnded = null; cx.notify(); }
        else if (to.ended) { this.endedOpen.clear(); cx.notify(); }
        else if (to.project) openProject(to.project);
        else if (to.view) showPage(to.view);
        // The same way back as a second Projects click; without pm-nav there is none, so the workspace.
        else if (findMod(desktopLayout(), 'pm-nav')) run('pm-nav.back');
        else run('layout.select', { stack: STAGE, child: WORK });
      })
      .child(this.content(cx));
  }
  content(cx) {
    if (this.setupStatus === null || this.setupStatus === 'missing') return this.setupView(theme());
    const t = theme(), view = page(), scope = view.project || '';
    if (scope !== this.scope) cx.timer.after(0, cx => this.rescope(scope, cx));
    if (!scope && view.view !== 'board') {
      // No board on screen: its flow layer stops ticking (a packet in flight starts again with the board).
      if (this.flowKey !== 'page') {
        this.flowKey = 'page'; this.flowUpdate?.cancel();
        this.flowUpdate = cx.timer.after(0, () => this.flowLayer.set_props({ overlay: false, wires: [], packet: null,
          geometry: [], onComplete: this.packetFinished }));
      }
      return pageView(this, view.view === 'archived' ? 'archived' : 'list', t);
    }
    const pm = scope && this.allState.pms.find(p => p.name === scope);
    return v_flex().id('pm-page').size_full().min_w(0).min_h(0).bg(t.canvas).text_color(t.foreground)
      .child(pm ? projectHeader(this, pm, t) : pageHeader(this, 'board', t))
      .child(this.board(cx));
  }
  board(cx) {
    const g = this.geometry(), terms = terminals(), live = agents(), t = theme();
    const px = n => n * g.scale, font = n => Math.max(10, px(n));
    const rows = g.rows.map(r => ['label', 'junction', 'ended', 'day'].includes(r.type) ? r : this.presentation(r, terms, live));
    for (const row of rows) if (row.type === 'junction') row.flows = wireFlows(row, rows);
    const total = counts({ lang: this.state.lang, pms: this.state.pms, tasks: rows.filter(r => r.type === 'task').map(r => ({...r, worker:r.live})) });
    for (const pm of rows.filter(r => r.type === 'pm')) {
      pm.waiting = rows.filter(r => r.type === 'task' && (r.pm || '') === (pm.name || '') && r.status === 'blocked' && !r.answered).length;
    }
    const stage = div().id('board-stage').relative().w(g.width).h(g.height).flex_none()
      .on_mouse_move((event, cx) => this.hoverBounds('stageBounds', event.bounds, cx));
    for (const [text, x] of [[this.text('projects'), g.pmX], [this.text('tasks'), g.taskX]]) {
      stage.child(div().absolute().left(x).top(0).h(px(18)).line_height(`${px(18)}px`)
        .text_size(font(11.5)).text_color(t.dim).child(text));
    }
    for (const machine of g.machines) {
      stage.child(div().absolute().left(machine.x).top(machine.y).w(machine.w).h(machine.h).px(px(6))
        .line_height(`${machine.h}px`).rounded(px(5)).bg(t.raised).text_color(t.muted)
        .font_family('monospace').text_size(font(11)).truncate().tooltip(machine.label).child(machine.label));
    }
    const tr = this.trip, flowing = [];
    for (const wire of g.wires) {
      if (wireFlows(wire, rows)) {
        flowing.push({ id: wire.id, points: wire.points, color: this.projectColor(wire.pm, t), opacity: this.dim(wire.pm) });
        continue;
      }
      // The ended node's line is neutral and never flows.
      const p = wire.points, b = PathBuilder.stroke(wire.ended ? 1.3 : 1.6).move_to(...p[0]);
      b.cubic_bezier_to(...p[3], ...p[1], ...p[2]);
      stage.child(window.paint_path(b.build(), wire.ended ? t.dim : this.projectColor(wire.pm, t))
        .id(`wire:${wire.id}`).absolute().left(0).top(0).size_full().opacity(.5 * this.dim(wire.pm)).transition('opacity', 160));
    }
    // An opened ended list hangs on one straight guide, not a wire per task.
    for (const guide of g.guides) {
      stage.child(div().absolute().left(guide.x - .5).top(guide.y).w(1).h(guide.h).bg(t.dim)
        .opacity(.5 * this.dim(guide.pm)).transition('opacity', 160));
    }
    const flowProps = { overlay: Boolean(props()?.overlay), wires: flowing,
      packet: tr ? { token: tr.token, routes: tr.routes, reverse: tr.reverse,
        color: this.projectColor(tr.event.pm, t), opacity: this.dim(tr.event.pm), background: t.canvas } : null,
      geometry: g.wires.map(wire => ({ id: wire.id, points: wire.points })) };
    const flowKey = JSON.stringify(flowProps);
    if (flowKey !== this.flowKey) {
      this.flowKey = flowKey;
      // Coalesce parent changes without putting the flow timer on the parent.
      this.flowUpdate?.cancel();
      this.flowUpdate = cx.timer.after(0, () => this.flowLayer.set_props({ ...flowProps, onComplete: this.packetFinished }));
    }
    stage.child(this.flowLayer);
    for (const row of rows) stage.child(this.row(row, t, cx, total, g.scale));
    const legend = h_flex().absolute().left(0).top(g.bodyBottom + px(12)).gap(px(14)).items_center().text_size(font(11.5)).text_color(t.dim);
    for (const [key, color] of [['inDesktop', t.muted], ['notDesktop', t.raised]]) {
      legend.child(h_flex().gap(px(6)).items_center().child(div().w(px(10)).h(px(10)).rounded(px(3)).bg(color)).child(this.text(key)));
    }
    stage.child(legend);
    const hovered = rows.find(row => row.type === 'task' && row.task === this.hoverTask);
    if (hovered) {
      const info = this.taskInfoCard(hovered, g, t);
      if (info) stage.child(info);
    }
    const peek = this.peeking() && rows.find(row => row.type === 'ended' && row.pm === this.hoverEnded);
    if (peek && peek.peek?.length) {
      const card = this.endedPeek(peek, g, t);
      if (card) stage.child(card);
    }

    const small = g.frame.width < 800;
    const stats = h_flex().h(52).px(6).flex_none().rounded(12).bg(t.surface).items_center();
    const values = [[total.running, this.text('running'), total.running ? t.ansi2 : t.dim],
      [total.review, this.text('review'), t.accent], [total.blocked, this.text('blocked'), t.blocked]];
    for (const [i, [value, text, color]] of values.entries()) {
      stats.child(h_flex().relative().px(small ? 8 : 16).gap(small ? 4 : 7).items_baseline()
        .when(i > 0, el => el.child(div().absolute().left(0).top(2).bottom(2).w(1).bg(t.border)))
        .child(div().text_size(small ? 20 : 24).font_bold().text_color(color).child(String(value)))
        .child(div().text_size(small ? 11 : 12).text_color(t.muted).child(text)));
    }
    const feed = v_flex().id('board-feed').flex_none().gap(0)
      .when(g.frame.wide, el => el.w(g.frame.feedWidth).border_l(1).border_color(t.border).pl(28))
      .when(!g.frame.wide, el => el.w(g.width).border_t(1).border_color(t.border).pt(12))
      .on_size_change((size, cx) => {
        if (this.feedHeight === undefined || Math.abs(size.height - this.feedHeight) > .5) {
          this.feedHeight = size.height; cx.notify();
        }
      })
      .child(div().flex_none().text_size(12).font_semibold().mb(6).child(this.text('recent')));
    const events = this.state.events.slice(-5).reverse();
    if (tr?.replay && !events.some(e => e.key === tr.event.key)) events.push(tr.event);
    for (const e of events) {
      const current = tr?.event.key === e.key, color = this.projectColor(e.pm, t);
      const pm = this.state.pms.find(p => p.name === e.pm);
      feed.child(h_flex().id(`event:${e.key}`).h(g.frame.wide ? 30 : 24).flex_none().px(8).gap(8).items_center().rounded(6)
        .when(current, el => el.bg(t.raised)).text_color(current ? t.foreground : t.muted)
        .child(this.dot(color, true, t, 6))
        .child(div().max_w(g.frame.wide ? 95 : 160).truncate().flex_shrink_0().text_size(12).font_semibold().text_color(t.foreground)
          .child(pm?.project || (pm?.sourceName ?? pm?.name) || this.text('noPm')))
        .child(div().flex_1().min_w(0).truncate().text_size(12)
          .child(`${current && tr.replay ? this.text('replay') : ''}${this.eventLine(e)}`)));
    }
    if (!events.length) feed.child(div().text_size(12).text_color(t.dim).child(this.text('noEvents')));
    const toggle = h_flex().id('replay-toggle').flex_none().gap(8).items_center().cursor_pointer().px(6).py(4).rounded(6)
      .hover(s => s.bg(t.raised)).child(div().text_size(12.5).text_color(t.muted).child(this.text('idleReplay')))
      .child(div().relative().w(30).h(18).rounded(9).bg(this.auto ? t.foreground : t.border)
        .child(div().id('replay-thumb').absolute().left(this.auto ? 14 : 2).top(2).w(14).h(14).rounded(7)
          .bg(t.surface).transition('left', 160)))
      .on_click((_e,cx) => {
        this.auto = !this.auto;
        if (!this.auto && this.trip?.replay) { this.serial++; this.trip = null; }
        this.next(cx); cx.notify();
      });
    const main = (g.frame.wide ? h_flex().gap(g.frame.gap).items_start() : v_flex().gap(16))
      .flex_none().mt(20).child(stage).child(feed);
    const card = v_flex().id('board-card').w(g.frame.width).flex_none().px(g.frame.inset).py(g.frame.wide ? 26 : 24).bg(t.canvas)
      .on_size_change((size, cx) => {
        // Wide feed shares the graph's height; bottom feed belongs to fixed
        // chrome. Measure wrapping text, not a guessed count of header lines.
        const fixed = size.height - (g.frame.wide ? Math.max(g.height, this.feedHeight || 0) : g.height);
        if (this.measuredWidth !== this.size.width || this.fixedHeight === undefined || Math.abs(fixed - this.fixedHeight) > .5) {
          this.measuredWidth = this.size.width; this.fixedHeight = fixed; cx.notify();
        }
      })
      .child(h_flex().h(24).flex_none().justify_between().items_center()
        .child(h_flex().flex_1().min_w(0).gap(8).items_center()
          .child(div().text_size(12.5).font_semibold().child(this.text('board')))
          .child(this.dot(this.error ? t.blocked : this.primed ? t.ansi2 : t.dim, true, t, 7))
          .child(div().flex_1().min_w(0).truncate().text_size(12.5).text_color(t.muted)
            .child(this.error ? this.text('readError') : this.primed ? this.text('live') : this.text('loading'))))
        .child(toggle))
      .when(this.setupStatus === 'outdated', el => el.child(h_flex().mt(8).gap(8).items_center()
        .child(div().flex_1().min_w(0).text_size(12.5).text_color(t.muted).child(this.text('setupOutdated')))
        .child(this.setupButton(t, 'update', true))))
      .when(Boolean(this.setupError || this.setupDone), el => el.child(div().mt(8).whitespace_normal().text_size(12.5)
        .text_color(this.setupError ? t.blocked : t.muted).child(this.setupError || this.text('setupDone'))))
      .child(h_flex().flex_none().mt(14).gap(small ? 12 : 24).items_start().justify_between()
        .child(v_flex().flex_1().min_w(0).gap(6)
          .child(h_flex().flex_wrap().gap(5).text_size(small ? 16 : 22).font_semibold()
            .child(div().child(this.text('summaryLead', this.state.pms.length, total.running)))
            .child(div().text_color(total.waiting ? t.blocked : t.foreground).child(this.text('summaryWaiting', total.waiting))))
          .child(div().h(36).overflow_hidden().whitespace_normal().text_size(13.5).line_height('18px').text_color(t.muted).child(total.conclusion)))
        .child(stats))
      .child(main);
    return keepPress(this, v_flex().id('root')).w_full().flex_1().min_h(0).bg(t.canvas).text_color(t.foreground).text_size(13)
      .on_mouse_move((event, cx) => this.hoverBounds('boardBounds', event.bounds, cx))
      .on_size_change((size,cx) => { if (size.width !== this.size.width || size.height !== this.size.height) { this.size=size; this.hoverTask=null; this.hoverEnded=null; cx.notify(); } })
      .child(div().relative().flex_1().min_h(0).min_w(0).w_full()
        .child(div().id('scroll').size_full().overflow_scroll()
          .on_scroll_wheel((_event, cx) => { if (this.hoverTask || this.hoverEnded !== null) { this.hoverTask=null; this.hoverEnded=null; cx.notify(); } }).child(card))
        .child(Scrollbar.new('scroll').absolute().inset_0().mode('always')));
  }
}
