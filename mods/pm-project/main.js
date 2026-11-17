import { View, div, svg, image } from 'gpui-kit';
import { v_flex, h_flex, TextView, TextareaState, Textarea, ScrollHandle } from 'gpui-base';
import { theme, home, appHome, exec, readTextFile, watchFolder, layout, run, terminals, agents, panes, spaces, shared, setShared, window as appWindow } from 'herdr';
import {
  word, timeline, parseConversation, settlePending, answeredTasks, markAnswered, bellStops, bellNext, bellCount, bellThread, detailQuestion, askKey, timelineRows, rowOf, riseAfterWheel, riseAfterJump, answerText, clock, dayLabel, shortPath,
  diffArgv, sendArgv, withoutTerminalEnv, SEND_ENV, REATTACH_ENV, pmRow, taskRow, terminalFor, terminalTargetFor, focusPlan, cleanTaskLog, statusLabel, tone, turns, newestReply, threadList,
  disconnected, terminalAction, reattachArgv, engineLabel, engineTip, engineChip, wasEscalated, endedEngine, escapeStep,
  subThreads, parentThread, foldParts, PARTS_LIMIT, foldReviews, reviewRow, threadFor,
  age, eventTime, workingTasks, threadLink, logText, draftKey, draftText, readDrafts, keepDraft,
  draftFiles, withFiles, withoutFile, notFiles, pickedPaths, addFiles, messageText, afterSend, fileName, isImage, pasteName, pasteDir, pastesIn, uploadSteps, landedPath, sentFiles,
  heldFiles, sentLeftovers, staleArgv, staleFiles,
  CHOOSE_FILES, SAVE_CLIPBOARD_IMAGE, PANEL_WIDTH, panelWidth, draggedWidth, readPanelWidth, keepPressHandler,
  withAlpha, solidText, isDarkTheme, viewMarkdown, LEDGER_HOME_SH, EVENT_LIMIT,
  projectRef, machineView, onMachine, remotePmArgv,
} from './model.js';
import { execPython } from './python.js';

// The project view reads the ledger through the original pm-dash bundle, like pm-list.
const PM_SCRIPT = '/mods/pm-dash/skill/scripts/pm.py';
const STAGE = 'pm-stage', WORK = 'work', BOARD = 'pm-board';
// pm-list names the project to show here: shared('pm-project') = {pm: <PM name>}, or for a PM on
// another machine {pm: '<machine>/<PM name>', machine} (see projectRef).
const SHARED = 'pm-project';
const ICON = name => `mods/pm-project/${name}.svg`;
const SPINNER = 'mods/workspace-chrome/spinner.svg';
const COLUMN = 680, FADE = { duration: 180, easing: 'ease-out' };
// The space above the first row of the conversation and after its last.
const TAIL = 28;
// From this width the conversation column and the side panel fit side by side, so the panel rests open.
const WIDE = COLUMN + PANEL_WIDTH + 2 * 28;
// Where the panel's dragged width is kept, in this mod's localStorage.
const PANEL_KEY = 'panelWidth';
// The layout's block has window_drag: a left press that reaches it moves the window, and a double-click
// maximizes it. So only the header's blank space and its words let presses through; its controls,
// the conversation, the message boxes and the side panel keep theirs (Herdr's own bars do the same).
// `keyboard`: the page's focus handle, given the keyboard on the press (see keepPressHandler).
const keepPress = (el, keyboard = null) => el.on_mouse_down('left', keepPressHandler(keyboard));
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

function findStage(node) {
  if (node?.id === STAGE) return node;
  for (const child of node?.children ?? []) {
    const found = findStage(child);
    if (found) return found;
  }
  return null;
}

export default class PmProject extends View {
  init(_props, cx) {
    this.state = { pms: [], tasks: [] };
    this.events = []; this.pending = []; this.seq = 0; this.pastes = [];
    this.error = ''; this.logError = '';
    // pmName: the project's key as shared names it; machine: the machine it is on ('' here), whose
    // ledger `state` then is (stateFor: the machine the state was read from; remoteHome: its ledger home).
    this.pmName = ''; this.logPath = ''; this.machine = ''; this.stateFor = null; this.remoteHome = '';
    this.ledgerHome = ''; this.watching = {};
    // The side panel: the thread list while it rests, one thread's detail while `detail` is on.
    // listShown: what the header's icon asked for; until then the list shows when the window is wide.
    this.thread = ''; this.threadTask = null; this.detail = false; this.threadError = '';
    // reattaching: the thread whose `pm.py reattach` runs; reattachError: {id, text} of the last that failed.
    this.reattaching = ''; this.reattachError = null;
    this.listShown = null; this.wide = false; this.measured = false;
    // panelWant: the width the reader dragged the panel to (null: the default), kept in localStorage;
    // panelDrag: {x, width} at the press while its edge is being dragged; viewWidth: the whole view's
    // width; gripLit: the pointer is on the edge, which then shows.
    this.panelWant = this.keptPanelWidth(); this.panelDrag = null; this.viewWidth = 0; this.gripLit = false;
    this.seen = null; this.count = 0; this.settle = 0; this.away = false;
    // rise: how far above the end the reader is, in px, as the view keeps count of it (see riseAfterWheel);
    // heights: each row's measured height by its key; tall: the scroll area's height (the whole
    // view's, `high`, until the area reports its own).
    this.rise = 0; this.heights = new Map(); this.tall = 0; this.high = 0;
    // bell: where the last click on the bell went (see bellNext); flash: the item it points at, for a moment.
    this.bell = null; this.flash = '';
    this.unfolded = new Map(); this.newest = ''; this.atWork = new Set();
    this.scroll = ScrollHandle.new();
    // The page's keyboard, for Esc (escapeStep): taken each time the stage turns to this page; typing:
    // which box ('main' | 'thread') holds the keyboard, from the boxes' focus and blur.
    this.keyFocus = cx.focus_handle(); this.onStage = false; this.typing = '';
    // What is typed and not sent yet lives in localStorage, not here: this view is built anew
    // whenever a file of the mod is saved (an install does that) and when the app starts.
    // mainKey/threadKey name whose draft each box holds; a box's key and text change together.
    // outgoing: per key, how many sends of that box's words are on their way.
    this.mainKey = ''; this.threadKey = ''; this.outgoing = new Map();
    // files/threadFiles: each box's attachments, kept with its draft. attachError: {key, text}: the
    // last that failed, shown on the box of that draft.
    this.files = []; this.threadFiles = []; this.attachError = null; this.pasted = { stamp: '', n: 0 };
    // answering: {key, title} of the question card the project's box answers in the user's own words
    // (its "own words" row was clicked): what it sends then starts with the card's 【title】 (answerText),
    // so it counts as that card's answer. Only this project's box; another project starts without it.
    this.answering = null;
    this.input = TextareaState.new({ rows: 1 });
    this.input.set_auto_grow(1, 6);
    this.input.on('change', (_e, cx) => {
      const had = Boolean(this.draft?.trim());
      this.draft = this.input.value();
      this.typed(this.mainKey, this.draft);
      if (had !== Boolean(this.draft.trim())) cx.notify();
    });
    // Enter sends (the key handler below catches it first); Shift+Enter stays a new line.
    this.input.on('submit', (e, cx) => { if (!e?.shift) this.sendMain(cx); });
    // A paste that found no text: the clipboard's image, if it holds one, becomes an attachment.
    this.input.on('paste_other', (_e, cx) => this.pasteImage('main', cx));
    this.input.on('focus', () => { this.typing = 'main'; });
    this.input.on('blur', () => { if (this.typing === 'main') this.typing = ''; });
    this.threadInput = TextareaState.new({ rows: 1 });
    this.threadInput.set_auto_grow(1, 4);
    this.threadInput.on('change', (_e, cx) => {
      const had = Boolean(this.threadDraft?.trim());
      this.threadDraft = this.threadInput.value();
      this.typed(this.threadKey, this.threadDraft);
      if (had !== Boolean(this.threadDraft.trim())) cx.notify();
    });
    this.threadInput.on('submit', (e, cx) => { if (!e?.shift) this.sendThread(cx); });
    this.threadInput.on('paste_other', (_e, cx) => this.pasteImage('thread', cx));
    this.threadInput.on('focus', () => { this.typing = 'thread'; });
    this.threadInput.on('blur', () => { if (this.typing === 'thread') this.typing = ''; });
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
    const machine = this.machine;
    cx.spawn(async cx => {
      try {
        // A project on another machine is read there, through herdr-core (its folders cannot be watched
        // from here: the 10-second read keeps it current).
        const r = machine ? await exec(...remotePmArgv(['state']), { on: machine, timeout: 15000 })
          : await execPython(exec, [appHome() + PM_SCRIPT, 'state']);
        if (r.code !== 0) throw new Error(r.stderr || `pm.py: ${r.code}`);
        const state = JSON.parse(r.stdout);
        if (!Array.isArray(state.pms) || !Array.isArray(state.tasks)) throw new Error('state is missing pms/tasks arrays');
        if (machine === this.machine) {
          this.state = state; this.stateFor = machine;
          this.error = '';
          if (machine) this.remoteHome = typeof state.home === 'string' ? state.home : '';
          else { this.setLedgerHome(state.home, cx); this.arm(cx); }
        }
      } catch (e) { if (machine === this.machine) this.error = String(e?.message || e).trim(); }
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
    const pm = this.pm(), path = pm?.conversation || '', on = this.where();
    if (path !== this.logPath) { this.logPath = path; this.events = []; this.pastes = []; }
    if (!path) { cx.notify(); return; }
    if (this.logLoading) { this.logAgain = true; return; }
    this.logLoading = true;
    cx.spawn(async cx => {
      try {
        const r = await exec('sh', ['-c', 'test -f "$1" || exit 0; tail -n "$2" "$1"', 'sh', path, String(EVENT_LIMIT * 2)], on);
        if (r.code !== 0) throw new Error(r.stderr || `tail: ${r.code}`);
        if (path === this.logPath) {
          this.events = parseConversation(r.stdout);
          this.pending = settlePending(this.pending, this.events);
          // The screenshots pasted into this project, for the messages the log has with image marks
          // (kept here for a project on another machine too, see pasteFolder).
          const dir = this.pasteFolder(pm);
          try {
            const ls = dir ? await exec('sh', ['-c', 'cd "$1" 2>/dev/null && ls -1 || true', 'sh', dir]) : null;
            if (path === this.logPath && ls?.code === 0) this.pastes = pastesIn(dir, ls.stdout);
          } catch (_) { /* Marks then show without their screenshots. */ }
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
    const id = this.thread, home = this.machine ? this.remoteHome : this.ledgerHome, on = this.where();
    if (!id || !home) return;
    cx.spawn(async cx => {
      try {
        const text = await readTextFile(`${home}/tasks/${id}.json`, on);
        if (id === this.thread) this.threadTask = text ? JSON.parse(text) : null;
      } catch (_) { /* Keep what is shown. */ }
      cx.notify();
    });
  }

  pm() {
    if (this.stateFor !== this.machine) return null;
    const name = projectRef({ pm: this.pmName, machine: this.machine }).name;
    return this.state.pms.find(p => p.name === name) || null;
  }
  // exec/readTextFile's options for the project's machine; {} here.
  where() { return this.machine ? { on: this.machine } : {}; }
  // The terminals and agents as the project's machine sees them (machineView).
  terms() { return machineView(terminals(), this.machine); }
  live() { return machineView(agents(), this.machine); }
  pmTerminal() {
    const row = pmRow(this.pm());
    return row ? terminalFor(row, this.terms()) || null : null;
  }
  threadTerminal() {
    const task = this.threadTask || this.state.tasks.find(t => t.id === this.thread);
    return task ? terminalFor(taskRow(task), this.terms()) || null : null;
  }
  // Herdr's window.platform: "windows" | "macos" | "linux". Used so send/put/reattach skip Unix `env -u`.
  hostPlatform() {
    try { return appWindow()?.platform || ''; } catch (_) { return ''; }
  }
  // The reattach icon: pm.py brings the thread's agent back (its session resumed, or a new agent given
  // the thread's context) in a terminal under the PM, and the ledger then names that terminal.
  reattach(cx) {
    const id = this.thread;
    if (!id || this.reattaching) return;
    this.reattaching = id; this.reattachError = null;
    cx.spawn(async cx => {
      try {
        let r;
        if (this.machine) {
          r = await exec(...remotePmArgv(['reattach', id]), { on: this.machine, timeout: 150000 });
        } else if (this.hostPlatform() === 'windows') {
          // No `env -u` and no guaranteed `python3` on Windows: the same finder setup uses.
          r = await execPython(exec, [appHome() + PM_SCRIPT, 'reattach', id], { timeout: 150000 });
        } else {
          r = await exec(...withoutTerminalEnv(reattachArgv(appHome() + PM_SCRIPT, id), {
            platform: this.hostPlatform(), unset: REATTACH_ENV,
          }), { timeout: 150000 });
        }
        if (r.code !== 0) throw new Error(String(r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
      } catch (e) {
        this.reattachError = { id, text: String(e.message || e) };
      } finally {
        this.reattaching = '';
        this.refresh(cx);
        cx.notify();
      }
    });
    cx.notify();
  }

  // ---- the side panel's width: its left edge drags (see panelWidth) ----------
  keptPanelWidth() {
    try { return readPanelWidth(localStorage.getItem(PANEL_KEY)); } catch (_) { return null; }
  }
  keepPanelWidth(width) {
    try {
      if (width == null) localStorage.removeItem(PANEL_KEY);
      else localStorage.setItem(PANEL_KEY, String(width));
    } catch (_) { /* Nowhere to keep it: it holds until the view is built anew. */ }
  }
  // A press on the edge starts a drag; a double-click puts the default width back.
  gripDown(e, cx) {
    if (e.click_count >= 2) {
      this.panelDrag = null; this.panelWant = null; this.keepPanelWidth(null);
    } else {
      this.panelDrag = { x: e.position.x, width: panelWidth(this.panelWant, this.viewWidth) };
    }
    cx.notify();
  }
  // The pointer anywhere over the view moves the edge while a drag is on.
  gripMove(e, cx) {
    if (!this.panelDrag) return;
    const width = draggedWidth(this.panelDrag, e.position.x, this.viewWidth);
    if (width !== this.panelWant) { this.panelWant = width; cx.notify(); }
  }
  // Released, or the pointer left the view (where a release would not be heard): the width stays.
  gripUp(cx) {
    if (!this.panelDrag) return;
    const moved = this.panelWant !== null && this.panelWant !== this.panelDrag.width;
    this.panelDrag = null;
    if (moved) this.keepPanelWidth(this.panelWant);
    cx.notify();
  }

  // The drafts as storage has them now. Read each time, never kept here: another view of this mod
  // writes the same store (a second window; the build from before a reload finishing its send).
  drafts() {
    try { return readDrafts(localStorage.getItem('drafts')); } catch (_) { return {}; }
  }
  // Files a box's text as its draft, on disk at once (a reload gives no warning). Only that box's
  // entry changes, in the store as it is now.
  keep(key, text, files) {
    const stored = this.drafts();
    this.store(stored, keepDraft(stored, key, text, Date.now(), files));
  }
  store(stored, next) {
    if (next === stored) return;
    try { localStorage.setItem('drafts', JSON.stringify(next)); } catch (_) { /* Nowhere to keep it. */ }
  }
  // What a box holds is its draft. A box emptied while its words are on their way is not: that
  // draft stays until the send has worked.
  typed(key, text) {
    if (!text.trim() && this.outgoing.get(key)) return;
    this.keep(key, text);
  }
  // Around a send of a box's words: the draft goes only once they went out, and only if it still
  // is those words. Words that did not go out stay the draft, or are it again when the box's draft
  // is empty (nothing newer was typed there).
  leaving(key) {
    if (key) this.outgoing.set(key, (this.outgoing.get(key) || 0) + 1);
  }
  // sent: {text, files}, what went out of the box.
  landed(key, sent, ok) {
    if (!key) return;
    this.outgoing.set(key, Math.max(0, (this.outgoing.get(key) || 0) - 1));
    const drafts = this.drafts();
    const next = afterSend({ text: draftText(drafts, key), files: draftFiles(drafts, key) }, sent, ok);
    if (next) this.keep(key, next.text, next.files);
  }
  // Text into a box, with the cursor after it and nothing selected: the next key adds to it.
  fill(box, text) {
    box.set_value(text);
    box.set_selected_range({ start: text.length, end: text.length });
  }
  // The project's box takes the draft kept for the project that shows now; no thread is open.
  showMainDraft() {
    this.mainKey = draftKey('pm', this.pmName);
    const drafts = this.drafts();
    this.draft = draftText(drafts, this.mainKey);
    this.files = draftFiles(drafts, this.mainKey);
    this.fill(this.input, this.draft);
    this.showThreadDraft('');
  }
  showThreadDraft(id) {
    this.threadKey = draftKey('thread', id && onMachine(id, this.machine));
    const drafts = this.drafts();
    this.threadDraft = draftText(drafts, this.threadKey);
    this.threadFiles = draftFiles(drafts, this.threadKey);
    this.fill(this.threadInput, this.threadDraft);
  }

  // ---- attachments: which is 'main' (the project's box) or 'thread' ----------
  // Each change goes to a draft by its key, named when it started: a picker or a paste that ends
  // after the box moved to another project or thread still lands in the draft it was made for.
  filesOf(which) { return which === 'thread' ? this.threadFiles : this.files; }
  keyOf(which) { return which === 'thread' ? this.threadKey : this.mainKey; }
  // The box that shows the draft `key` now, or ''.
  boxFor(key) { return !key ? '' : key === this.threadKey ? 'thread' : key === this.mainKey ? 'main' : ''; }
  // Files into the draft `key` as stored, beside its stored words and files (a box emptied by a send
  // on its way still has that send as its draft), and into its box when it shows. What is not a
  // file is named by the red mark.
  attach(key, paths, cx) {
    // On another machine's project the files stay paths here until a send copies them there (deliver).
    if (!key) return;
    const rejected = notFiles(paths);
    if (rejected.length) this.attachError = { key, text: word(this.lang, 'notAFile', rejected.map(p => fileName(String(p))).join(', ')) };
    else if (this.attachError?.key === key) this.attachError = null;
    const stored = this.drafts();
    this.store(stored, addFiles(stored, key, paths, Date.now()));
    const which = this.boxFor(key);
    if (which === 'thread') this.threadFiles = withFiles(this.threadFiles, paths);
    else if (which === 'main') this.files = withFiles(this.files, paths);
    cx.notify();
  }
  detach(which, path, cx) {
    const key = this.keyOf(which), stored = this.drafts();
    if (which === 'thread') this.threadFiles = withoutFile(this.threadFiles, path);
    else this.files = withoutFile(this.files, path);
    this.store(stored, keepDraft(stored, key, draftText(stored, key), Date.now(), withoutFile(draftFiles(stored, key), path)));
    cx.notify();
  }
  failedAttach(key, e, cx) {
    this.attachError = { key, text: String(e?.message || e).trim() };
    cx.notify();
  }
  // The clipboard's image saved in the project's attachments folder; a clipboard without one leaves
  // the box as it was (the paste had no text either).
  pasteImage(which, cx) {
    const key = this.keyOf(which), dir = this.pasteFolder(this.pm());
    if (!dir) { this.failedAttach(key, word(this.lang, 'noPasteFolder'), cx); return; }
    if (this.machine) this.prune();
    const now = new Date(), stamp = pasteName(now);
    this.pasted = { stamp, n: this.pasted.stamp === stamp ? this.pasted.n + 1 : 1 };
    const path = `${dir}/${pasteName(now, this.pasted.n)}`;
    cx.spawn(async cx => {
      try {
        const r = await exec('osascript', ['-e', SAVE_CLIPBOARD_IMAGE, path, dir], { timeout: 20000 });
        if (r.code !== 0) throw new Error((r.stderr || r.stdout).trim() || `osascript: ${r.code}`);
        if (r.stdout.trim() === 'saved') this.attach(key, [path], cx);
      } catch (e) { this.failedAttach(key, e, cx); }
    });
  }
  // Where a screenshot pasted into this project is saved here (pasteDir): beside its log, or for a
  // project on another machine in this computer's ledger home until a send copies it there.
  pasteFolder(pm) {
    const name = projectRef({ pm: this.pmName, machine: this.machine }).name;
    return pasteDir(pm, { machine: this.machine, name, home: this.ledgerHome });
  }
  // What waits here for another machine and is a week old goes when something new is put there
  // (staleArgv); what a box or a bubble still holds stays. Nothing to report: it is tidying.
  prune() {
    const home = this.ledgerHome;
    if (!home) return;
    exec(staleArgv(home)[0], staleArgv(home).slice(1), { timeout: 20000 }).then(r => {
      const stale = staleFiles(r.stdout, heldFiles(this.drafts(), this.pending));
      if (stale.length) return exec('rm', ['-rf', '--', ...stale], { timeout: 20000 });
    }).catch(() => {});
  }
  // After a send to another machine went: its pasted screenshots there are no longer kept here,
  // unless a box or another bubble (not `except`, the one that went) still holds them.
  cleanSent(files, except) {
    if (!this.machine) return;
    const held = heldFiles(this.drafts(), (this.pending || []).filter(p => p.id !== except));
    const gone = sentLeftovers(files, this.pasteFolder(this.pm()), held);
    if (gone.length) exec('rm', ['-f', '--', ...gone], { timeout: 20000 }).catch(() => {});
  }
  // The paperclip: the system's file picker, several files at once. Cancelling it is no error.
  pickFiles(which, cx) {
    const key = this.keyOf(which);
    cx.spawn(async cx => {
      try {
        const r = await exec('osascript', ['-e', CHOOSE_FILES], { timeout: 600000 });
        if (r.code !== 0) {
          if (/-128/.test(r.stderr)) return;
          throw new Error((r.stderr || r.stdout).trim() || `osascript: ${r.code}`);
        }
        this.attach(key, pickedPaths(r.stdout), cx);
        const box = this.boxFor(key);
        if (box) (box === 'thread' ? this.threadInput : this.input).focus();
      } catch (e) { this.failedAttach(key, e, cx); }
    });
  }

  // `hc send` reaches a terminal on another machine by its "<machine>/<id>" address.
  // Windows: bare `hc` (no Unix `env -u`); elsewhere: `env -u HC_TERMINAL_ID hc send …`.
  send(address, text) {
    return exec(...withoutTerminalEnv(sendArgv(onMachine(address, this.machine), text), {
      platform: this.hostPlatform(), unset: SEND_ENV,
    }), { timeout: 20000 }).then(r => {
      if (r.code !== 0) throw new Error((r.stderr || r.stdout).trim() || `hc send: ${r.code}`);
    });
  }
  // `words` and `files` to the terminal `address` (as the project's machine sees it). On another
  // machine each file is first copied beside that terminal (uploadSteps) and the message names where
  // it landed there; a file that did not go stops the send with an error that names it (`upload` set).
  // Resolves with the message that went.
  // A file whose name hc put would garble goes as a renamed copy (uploadName), made in a folder of
  // this send's own beside the pasted screenshots and removed once the copies went or failed. A file
  // already copied there by an earlier try of the same send (this.uploaded) is not copied again.
  async deliver(address, words, files) {
    const landed = new Map(), uploaded = this.uploaded ||= new Map();
    const folder = this.machine ? this.pasteFolder(this.pm()) : '';
    const stage = folder ? `${folder}/sending-${Date.now()}-${this.sending = (this.sending || 0) + 1}` : '';
    const steps = uploadSteps(files, address, this.machine, { uploaded, stage });
    if (steps.some(step => step.copy)) this.prune();
    try {
      for (const step of steps) {
        if (step.landed) { landed.set(step.path, step.landed); continue; }
        try {
          if (step.copy) {
            const r = await exec('sh', ['-c', 'mkdir -p "$1" && cp -- "$2" "$3"', 'sh', stage, step.path, step.copy], { timeout: 60000 });
            if (r.code !== 0) throw new Error((r.stderr || r.stdout).trim() || `cp: ${r.code}`);
          }
          const where = landedPath(await exec(...withoutTerminalEnv(step.argv, {
            platform: this.hostPlatform(), unset: SEND_ENV,
          }), { timeout: 120000 }));
          uploaded.set(step.key, where);
          landed.set(step.path, where);
        } catch (e) {
          const error = new Error(word(this.lang, 'uploadFailed', fileName(step.path), this.machine, String(e.message || e).trim()));
          error.upload = true;
          throw error;
        }
      }
    } finally {
      if (steps.some(step => step.copy)) await exec('rm', ['-rf', '--', stage], { timeout: 20000 }).catch(() => {});
    }
    const message = messageText(words, sentFiles(files, landed), word(this.lang, 'attachments'));
    await this.send(address, message);
    for (const step of steps) uploaded.delete(step.key);
    return message;
  }
  // The bubble shows at once; the same line in the log replaces it.
  // `question` tags a quick answer so its options stay disabled while it is in flight.
  // files: the box's attachments, sent as the message's last lines (see messageText).
  // to: the title of the question the box's words answer (see answering): they go out after its 【title】.
  say(text, cx, question, files = [], to = '') {
    text = String(text || '').trim();
    files = question ? [] : withFiles([], files);
    if (!text && !files.length) return false;
    const said = to ? answerText(to, text) : text;
    const message = messageText(said, files, word(this.lang, 'attachments')), terminal = this.pmTerminal();
    if (!message || !terminal) return false;
    // words: the box's own words, without the title, which is what its draft holds.
    const bubble = { id: ++this.seq, text: message, words: text, to, files, sentAt: Date.now(), question };
    // Typed words stay the box's draft until they went out (a failed bubble is only in memory, and a
    // reload can come while they are on their way); a quick answer was never a draft.
    const key = question ? '' : this.mainKey;
    this.leaving(key);
    this.pending = [...this.pending, bubble];
    // The user's own words, typed or picked on a question, are the end of the conversation: the view goes there.
    this.follow();
    cx.notify();
    cx.spawn(async cx => {
      try { await this.deliver(terminal.address, said, files); this.landed(key, { text, files }, true); this.cleanSent(files, bubble.id); }
      catch (e) {
        this.pending = this.pending.map(p => p.id === bubble.id ? { ...p, failed: String(e.message || e), ...(e.upload ? { upload: true } : {}) } : p);
        this.landed(key, { text, files }, false);
      }
      cx.notify();
      this.readLog(cx);
    });
    return true;
  }
  sendMain(cx) {
    if (this.say(this.input.value(), cx, undefined, this.files, this.answering?.title)) {
      this.input.set_value(''); this.draft = ''; this.files = []; this.answering = null;
    }
  }
  // The "own words" row of a question card: the project's box answers that card, and takes the keyboard.
  answerInOwnWords(item, cx) {
    this.answering = { key: item.key, title: item.title };
    this.input.focus();
    cx.notify();
  }
  // A failed bubble: clicking sends it again.
  retry(id, cx) {
    const bubble = this.pending.find(p => p.id === id);
    if (!bubble) return;
    this.pending = this.pending.filter(p => p.id !== id);
    this.say(bubble.words ?? bubble.text, cx, bubble.question, bubble.files, bubble.to);
  }
  sendThread(cx) {
    const text = this.threadInput.value().trim(), files = this.threadFiles, terminal = this.threadTerminal(), key = this.threadKey;
    const message = messageText(text, files, word(this.lang, 'attachments'));
    if (!message || !terminal) return;
    this.leaving(key);
    this.threadInput.set_value(''); this.threadDraft = ''; this.threadFiles = []; this.threadError = '';
    cx.spawn(async cx => {
      try { await this.deliver(terminal.address, text, files); this.landed(key, { text, files }, true); this.cleanSent(files); }
      catch (e) {
        this.landed(key, { text, files }, false);
        // Back into the box when it still is that thread's and nothing was typed there since; files
        // attached meanwhile were added to the stored draft, so it holds them too.
        if (key === this.threadKey) {
          this.threadError = String(e.message || e);
          if (!this.threadInput.value()) this.showThreadDraft(this.thread);
        }
      }
      cx.notify();
    });
    cx.notify();
  }

  listResting() { return this.listShown ?? this.wide; }
  openThread(id, cx) {
    // A review thread is shown in the task it reviews (foldReviews).
    id = threadFor(this.tasks || foldReviews(this.state.tasks), id);
    if (this.thread === id && this.detail) { this.detail = false; cx.notify(); return; }
    if (this.thread !== id) { this.threadTask = null; this.threadError = ''; this.showThreadDraft(id); }
    this.thread = id;
    this.detail = true;
    this.readThread(cx);
    cx.notify();
  }
  // A link in a reply: a thread's name opens that thread in the side panel (and leaves it open when
  // it already is); a web address goes to the browser, as it would without this handler.
  followLink(url, cx) {
    const id = threadFor(this.tasks || foldReviews(this.state.tasks), threadLink(url));
    if (id) {
      if (!(this.detail && this.thread === id)) this.openThread(id, cx);
    } else if (/^https?:\/\//i.test(String(url || ''))) cx.open_url(url);
  }
  // The header's icon: shows the thread list, or puts the panel away whatever it shows.
  togglePanel(cx) {
    this.listShown = !(this.listResting() || this.detail);
    this.detail = false;
    cx.notify();
  }
  // Esc, one layer a press: the project's box stops answering a question card (unless the thread's
  // box has the keyboard); then words in the focused box only let go of the keyboard; then the open
  // thread's detail closes (as its close icon does); then a list slid open over a narrow window.
  escape(e, cx) {
    if (e.keystroke !== 'escape') return;
    const box = this.typing === 'thread' ? this.threadInput : this.typing === 'main' ? this.input : null;
    const step = escapeStep({ answering: Boolean(this.answering) && this.typing !== 'thread',
      typing: Boolean(box?.value().trim()), detail: this.detail, listOpen: !this.wide && this.listResting() });
    if (!step) return;
    cx.stop_propagation();
    if (step === 'answer') this.answering = null;
    else if (step === 'blur') this.keyFocus.focus();
    else if (step === 'detail') this.detail = false;
    else this.listShown = false;
    // The thread's box goes with its detail: the keyboard comes back to the page.
    if (step === 'detail' && this.typing === 'thread') this.keyFocus.focus();
    cx.notify();
  }
  // A scroll request is used once, after the next layout, and a reply that is still
  // reaching its full height pushes the end out again. So following asks for the end
  // marker on every render until no block has changed height for SETTLE renders; a
  // block that changes height (markdown settling, the panel narrowing the column, a
  // turn gaining a part) starts that count again, unless the reader scrolled up.
  follow() { this.away = false; this.rise = 0; this.settle = SETTLE; }
  // The count of how far above the end the reader is changed (the wheel, or a jump from the bell).
  // While it is above zero (`away`), what arrives does not pull the view down; back at zero the
  // view follows from the next row on.
  rest(rise) {
    this.rise = rise;
    this.away = rise > 0;
    if (this.away) this.settle = 0;
  }
  resized(cx) {
    if (this.away || !this.pmName) return;
    this.settle = SETTLE;
    cx.notify();
  }
  // Where a terminal can be shown (focusPlan): over its own pane, an ancestor's, or this project's PM's.
  // `address` as the project's machine names it (see machineView); the plan's are the app's.
  terminalPlace(address) {
    return focusPlan(onMachine(address, this.machine), terminals(), [...panes().map(p => p.terminal), ...agents().map(a => a.address)],
      onMachine(this.pmTerminal()?.address || '', this.machine));
  }
  // With nowhere to show it, nothing moves: showing work would reveal another project's space.
  focusTerminal(address) {
    const plan = this.terminalPlace(address);
    if (!plan.focus) return;
    run('pane.focus', { terminal: plan.focus });
    run('layout.select', { stack: STAGE, child: WORK });
    if (plan.peek) run('terminal.peek', { terminal: plan.peek });
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

  // An attached file: its kind as an icon and its name, the whole path under the pointer. `remove`
  // gives it a quiet ×; in a sent bubble it has none.
  fileCard(id, path, t, remove) {
    const name = fileName(path);
    return h_flex().id(id).h(26).max_w(220).flex_none().pl(8).pr(remove ? 3 : 9).gap(6).rounded(8).items_center()
      .bg(t.raised).text_size(12).text_color(t.muted).tooltip(path).accessibility_label(name)
      .child(this.icon(isImage(path) ? 'image' : 'file', 13))
      .child(div().min_w(0).truncate().text_color(t.foreground).child(name))
      .when(Boolean(remove), el => el.child(h_flex().id(`${id}-x`).size(20).flex_none().rounded(6).items_center()
        .justify_center().cursor_pointer().text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
        .tooltip(word(this.lang, 'removeFile', name)).accessibility_label(word(this.lang, 'removeFile', name))
        .on_click((_e, cx) => { cx.stop_propagation(); remove(cx); })
        .child(this.icon('close', 11))));
  }

  composer(id, state, draft, enabled, placeholder, offlineTip, onSend, t, radius, raised = false) {
    const which = id === 'say' ? 'main' : 'thread', files = this.filesOf(which);
    const ready = enabled && Boolean(draft?.trim() || files.length);
    const failed = this.attachError && this.attachError.key === this.keyOf(which) ? this.attachError.text : '';
    // The project's box answering a question card: a small mark of that card's thread above the words,
    // whose close icon (or Esc) stops it; the placeholder asks for the answer.
    const answering = which === 'main' ? this.answering : null;
    if (answering) placeholder = word(this.lang, 'ownAnswer');
    const mark = answering ? h_flex().pt(8).pr(10).child(h_flex().id(`${id}-answering`).h(24).max_w(320).pl(8).pr(3)
      .gap(6).rounded(8).items_center().bg(t.raised).text_size(12).text_color(t.muted)
      .tooltip(word(this.lang, 'answeringTo', answering.title)).accessibility_label(word(this.lang, 'answeringTo', answering.title))
      .child(this.icon('pencil', 12))
      .child(div().min_w(0).truncate().text_color(t.foreground).child(answering.title))
      .child(h_flex().id(`${id}-answering-x`).size(18).flex_none().rounded(6).items_center().justify_center()
        .cursor_pointer().text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
        .tooltip(word(this.lang, 'stopAnswering')).accessibility_label(word(this.lang, 'stopAnswering'))
        .on_click((_e, cx) => { cx.stop_propagation(); this.answering = null; this.input.focus(); cx.notify(); })
        .child(this.icon('close', 10)))) : null;
    // The placeholder sits under the textarea while it is empty (its words change with the project and language).
    const hint = div().absolute().left(0).top(11).right(0).truncate().text_size(14).text_color(t.dim).child(placeholder);
    const field = enabled
      ? div().relative().flex_1().min_w(0).py(11).when(!draft, el => el.child(hint))
        .child(Textarea.new(state).w_full().text_size(14).text_color(t.foreground))
      : div().flex_1().min_w(0).py(11).text_size(14).text_color(t.dim).truncate().child(placeholder);
    // The files go above the words, as in the bubble they are sent in; one that did not attach is a red mark there.
    const cards = files.length || failed ? h_flex().flex_wrap().gap(6).pt(8).pr(10)
      .children(files.map((path, i) => this.fileCard(`${id}-file-${i}`, path, t, cx => this.detach(which, path, cx))))
      .when(Boolean(failed), el => el.child(h_flex().id(`${id}-attach-error`).h(26).px(9).rounded(8).items_center()
        .bg(withAlpha(t.blocked, .14)).text_color(t.blocked).text_size(12.5).font_semibold()
        .tooltip(word(this.lang, 'attachFailed', failed)).accessibility_label(word(this.lang, 'attachFailed', failed))
        .child('!'))) : null;
    // A project on another machine takes files too: its tooltip says they are copied there on sending.
    const clipTip = this.machine ? word(this.lang, 'remoteAttach', this.machine) : word(this.lang, 'attach');
    const clip = h_flex().id(`${id}-attach`).size(32).mb(6).flex_none().rounded(9).items_center().justify_center()
      .text_color(t.muted).tooltip(clipTip).accessibility_label(clipTip)
      .when(enabled, el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
        .on_click((_e, cx) => this.pickFiles(which, cx)))
      .child(this.icon('clip', 16));
    // The box keeps its presses without the page's keyboard: its textarea takes the keyboard itself.
    const box = keepPress(v_flex().id(id)).w_full().pl(16).pr(6).py(4).rounded(radius)
      .bg(t.surface).border_1().border_color(enabled ? t.input || t.border : t.border)
      .when(!enabled, el => el.opacity(.6).cursor_not_allowed().tooltip(offlineTip))
      .on_key_down((e, cx) => {
        if (enabled && e.keystroke === 'enter') { cx.stop_propagation(); onSend(cx); }
      })
      // Files dragged from Finder (or anywhere) onto the box.
      .when(enabled, el => el.on_drop((e, cx) => this.attach(this.keyOf(which), e?.paths || [], cx)))
      .when(Boolean(mark), el => el.child(mark))
      .when(Boolean(cards), el => el.child(cards))
      .child(h_flex().w_full().items_end().gap(2)
      .child(field)
      .child(clip)
      .child(h_flex().id(`${id}-send`).size(44).flex_none().items_center().justify_center()
        .when(ready, el => el.cursor_pointer().on_click((_e, cx) => onSend(cx)))
        .tooltip(enabled ? word(this.lang, id === 'say' ? 'send' : 'sendThread') : offlineTip)
        .accessibility_label(word(this.lang, id === 'say' ? 'send' : 'sendThread'))
        .child(h_flex().size(30).rounded(15).items_center().justify_center()
          .bg(ready ? t.solid : t.raised).text_color(ready ? t.solid_foreground : t.muted)
          .child(this.icon('send', 15)))));
    return raised ? this.lift(box, t, radius) : box;
  }

  // Three small dots that breathe: this thread is being worked on.
  workingDots(t) {
    return h_flex().flex_none().gap(3).items_center().loop('opacity', { from: .3, to: 1, period: 1400 })
      .children([0, 1, 2].map(() => div().size(4).rounded_full().bg(t.muted)));
  }
  // A thread where it starts in the conversation: a hook, its name, and a mark of what it is now
  // (three dots while it is in progress, a dot in the status color while it waits or is in review,
  // nothing once it is over). Quiet until the pointer is on it; a click opens it in the side panel.
  threadLine(row, t, atWork) {
    const selected = this.detail && this.thread === row.task;
    const tip = [statusLabel(this.lang, row.status, row.cleanup, row.offline, row.answered), row.title].join(' · ');
    return h_flex().id(`thread-${row.task}`).h(24).gap(8).items_center().cursor_pointer().text_size(13)
      .text_color(selected ? t.foreground : row.closed ? t.dim : t.muted).hover(s => s.text_color(t.foreground))
      .tooltip(tip).accessibility_label(tip)
      .on_click((_e, cx) => this.openThread(row.task, cx))
      .child(svg(ICON('hook')).size(14).flex_none().text_color(t.dim))
      .child(div().min_w(0).truncate().child(row.title))
      // In progress: the dots breathe only while its own worker is at work, and rest dim otherwise.
      .when(row.tone === 'running', el => el.child(atWork.has(row.task) ? this.workingDots(t)
        : h_flex().flex_none().gap(3).items_center().opacity(.4).children([0, 1, 2].map(() => div().size(4).rounded_full().bg(t.muted)))))
      .when(row.tone === 'blocked' || row.tone === 'review', el => el.child(div().flex_none().size(6).rounded_full()
        .bg(this.toneColor(row.tone, t))));
  }
  // The name of a thread the reply under it is about.
  aboutLine(item, t) {
    const selected = this.detail && this.thread === item.task;
    return h_flex().id(`about-${item.key}`).h(20).gap(8).items_center().cursor_pointer().text_size(12.5)
      .text_color(selected ? t.foreground : t.dim).hover(s => s.text_color(t.foreground))
      .tooltip(word(this.lang, 'openThread')).accessibility_label(item.title)
      .on_click((_e, cx) => this.openThread(item.task, cx))
      .child(svg(ICON('hook-up')).size(14).flex_none().text_color(t.dim))
      .child(div().min_w(0).truncate().child(item.title));
  }

  // The coordinator asking: a quiet card with the thread's name, the question, and its answers as
  // rows (a letter, the answer, why, and a mark on the one the coordinator recommends). Picking one
  // sends it and leaves that row alone with a check; a question answered in the user's own words
  // keeps only its text. A question that waits ends with one more row, its "own words": a pencil
  // and a prompt, which sets the project's box to answer this card (see answering).
  question(item, t, cx) {
    // Answered in the user's own words (item.answered, see answeredTasks): settled as a picked one is,
    // its answer is the bubble after it.
    const picked = item.chosen >= 0, asking = item.open && !picked && !item.answered;
    const rows = picked ? [this.optionRow(item, item.chosen, t, true)] : asking ? this.answerRows(item, t) : [];
    // The thread's name opens the thread; its color is the row's, so it brightens under the pointer.
    const name = h_flex().id(`ask-${item.key}`).gap(4).items_center().cursor_pointer().text_size(12)
      .text_color(t.dim).hover(s => s.text_color(t.foreground))
      .tooltip(word(this.lang, 'openThread')).accessibility_label(item.title)
      .on_click((_e, cx) => this.openThread(item.task, cx))
      .child(div().min_w(0).truncate().child(item.title)).child(this.icon('chevron', 12));
    const card = v_flex().w_full().p(6).gap(2).rounded(14).border_1()
      .child(v_flex().px(10).pt(6).pb(rows.length ? 6 : 4).gap(3)
        .child(h_flex().child(name))
        .child(div().whitespace_normal().text_color(asking ? t.foreground : t.muted).child(item.text)))
      .children(rows);
    // A question that waits is a lifted surface with the message box's border; one that is settled
    // is an outline on the canvas, so the two differ in a light theme too.
    // The one the bell just went to has the bell's color around it for a moment.
    const edge = this.flash === item.key ? t.blocked : asking ? t.input || t.border : t.border;
    return div().w_full().max_w(560).child(asking ? this.lift(card.bg(t.surface).border_color(edge), t, 14)
      : card.border_color(edge));
  }

  // A question's answers, while it waits (a card's, or a thread detail's, see threadQuestion): its options
  // as rows, then its "own words" row. q: {key, title, options, notes, recommended}; at: a prefix for
  // the rows' ids, as one question can show in the conversation and in its thread's detail at once.
  answerRows(q, t, at = '') {
    return [...q.options.map((_o, i) => this.optionRow(q, i, t, false, at)), this.ownRow(q, t, at)];
  }
  // One answer: a letter, the answer, why, and a mark on the one the coordinator recommends. Picking it
  // sends answerText(title, option) tagged with the question's key; the picked one keeps a check.
  optionRow(q, i, t, chosen = false, at = '') {
    const sending = this.pending.some(p => p.question === q.key && !p.failed);
    const live = Boolean(this.pmTerminal()) && !sending;
    const row = h_flex().id(`${at}opt-${q.key}-${i}`).px(10).py(9).gap(12).rounded(10).items_center()
      .child(h_flex().size(28).flex_none().rounded(7).items_center().justify_center().bg(chosen ? t.hover : t.raised)
        .text_size(12.5).font_medium().text_color(t.muted).child(String.fromCharCode(65 + i)))
      .child(v_flex().flex_1().min_w(0).gap(1)
        .child(h_flex().gap(8).items_center()
          .child(div().min_w(0).whitespace_normal().text_color(t.foreground).child(q.options[i]))
          .when(q.recommended && i === 0, el => el.child(h_flex().flex_none().h(18).px(6).rounded(5).items_center()
            .bg(withAlpha(t.accent, .14)).text_color(t.accent).text_size(11).font_medium().child(word(this.lang, 'recommended')))))
        .when(Boolean(q.notes[i]), el => el.child(div().whitespace_normal().text_size(12.5).text_color(t.muted).child(q.notes[i]))));
    if (chosen) return row.bg(t.raised).child(this.icon('check', 16).text_color(t.muted));
    if (!live) return row.opacity(.5).tooltip(word(this.lang, sending ? 'sending' : 'offline'));
    return row.cursor_pointer().hover(s => s.bg(t.hover))
      .on_click((_e, cx) => this.say(answerText(q.title, q.options[i]), cx, q.key));
  }
  // The "own words" row: a pencil and a prompt, which sets the project's box to answer this question
  // (see answering). Already answering it: a click only gives the box the keyboard again.
  ownRow(q, t, at = '') {
    const on = this.answering?.key === q.key;
    const own = h_flex().id(`${at}own-${q.key}`).px(10).py(9).gap(12).rounded(10).items_center()
      .accessibility_label(word(this.lang, 'ownAnswer'))
      .child(h_flex().size(28).flex_none().rounded(7).items_center().justify_center().bg(on ? t.hover : t.raised)
        .text_color(on ? t.foreground : t.muted).child(this.icon('pencil', 14)))
      .child(div().flex_1().min_w(0).truncate().text_color(on ? t.foreground : t.muted).child(word(this.lang, 'ownAnswer')));
    return !this.pmTerminal() ? own.opacity(.5).tooltip(word(this.lang, 'offline'))
      : own.cursor_pointer().when(on, el => el.bg(t.raised)).hover(s => s.bg(t.hover))
        .on_click((_e, cx) => this.answerInOwnWords(q, cx));
  }

  // What one item of a coordinator turn looks like.
  turnPart(item, t, cx) {
    if (item.kind === 'pm') {
      // A reply's words are selectable and take the keyboard themselves (copy): kept, not refocused.
      const whole = () => keepPress(div()).w_full().pt(3).text_size(14).text_color(t.foreground)
        .child(TextView.markdown(`md-${item.key}`, viewMarkdown(item.text)).selectable(true)
          .on_link_click((url, cx) => this.followLink(url, cx)));
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
    if (item.kind === 'threads') return v_flex().w_full().children(item.rows.map(row => this.threadLine(row, t, this.atWork)));
    if (item.kind === 'about') return this.aboutLine(item, t);
    if (item.kind === 'question') return this.question(item, t, cx);
    // typing: the coordinator is at work.
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
      // The files it carried are cards under its words (or alone, when it was only files).
      const files = b.files || [];
      const el = v_flex().max_w('72%').px(14).py(10).gap(8).rounded_tl(18).rounded_tr(18).rounded_bl(18).rounded_br(6)
        .bg(t.raised).text_color(t.foreground)
        .when(Boolean(b.text), el => el.child(div().whitespace_normal().child(b.text)))
        .when(files.length > 0, el => el.child(h_flex().flex_wrap().gap(6)
          .children(files.map((path, i) => this.fileCard(`sent-${b.key}-${i}`, path, t).bg(t.surface)))));
      const row = h_flex().w_full().justify_end().gap(6).items_center()
        .when(Boolean(b.failed), row => row.child(h_flex().id(`retry-${b.key}`).size(22).rounded(11).items_center()
          .justify_center().text_color(t.blocked).cursor_pointer().hover(s => s.bg(t.hover))
          .tooltip(word(this.lang, 'failed', b.failed)).on_click((_e, cx) => this.retry(Number(b.key.split(':')[1]), cx))
          .child(div().text_size(13).font_semibold().child('!'))))
        .child(el.id(`bubble-${b.key}`).when(b.pending, el => el.opacity(.65).tooltip(word(this.lang, 'sending')))
          .when(!isDarkTheme(t) && !b.failed, el => el.border_1().border_color(t.border))
          .when(Boolean(b.failed), el => el.border_1().border_color(withAlpha(t.blocked, .6))));
      // A file that was not copied to the project's machine is said in words under the bubble, not
      // only in the retry mark's tooltip: the message did not go at all.
      if (!(b.failed && b.upload)) return row;
      return v_flex().w_full().items_end().gap(4).child(row)
        .child(div().id(`upload-error-${b.key}`).max_w('72%').text_size(12).text_color(t.blocked).whitespace_normal()
          .child(word(this.lang, 'failed', b.failed)));
    }
    // One row of a coordinator turn (see timelineRows). The names of the threads a reply is about sit
    // close above it; the turn's other parts follow on rows of their own, under the avatar's column.
    const part = item => this.fade(this.turnPart(item, t, cx), item.key, cx);
    // The avatar arrives with its turn's first part, not a frame before it.
    return h_flex().w_full().items_start().gap(12)
      .child(b.first && !b.bare ? this.fade(this.avatar(t), b.parts[0].key, cx) : div().w(28).flex_none())
      .child(v_flex().flex_1().min_w(0).gap(2).children(b.parts.map(part)));
  }

  // ring: null while nothing waits, else what a click on the bell calls: it names the row to go to
  // (-1: none, as when it opened a thread instead).
  header(pm, waiting, ring, t) {
    const terminal = pm ? terminalTargetFor(pmRow(pm), this.terms()).terminal : null;
    const bellTip = waiting ? word(this.lang, 'waitingCount', waiting) : word(this.lang, 'nothingWaiting');
    const bell = h_flex().id('bell').relative().size(32).flex_none().rounded(10).items_center().justify_center()
      .text_color(t.muted).tooltip(bellTip).accessibility_label(bellTip)
      .when(Boolean(ring), el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
        .on_click((_e, cx) => {
          const row = ring(cx);
          if (row >= 0) this.scroll.scroll_to_item(row);
        }))
      .child(this.icon('bell', 17))
      .when(waiting > 0, el => el.child(h_flex().absolute().top(-3).right(-5).min_w(18).h(18).px(4).rounded(9)
        .items_center().justify_center().bg(t.blocked).border(2).border_color(t.canvas)
        .text_color(solidText(t.blocked, t)).text_size(10.5).font_semibold().child(String(waiting))));
    return h_flex().h(56).flex_none().px(28).gap(10).items_center().border_b(1).border_color(t.border)
      .child(div().flex_none().text_size(15).font_semibold().child(pm?.project || pm?.name || 'PM'))
      .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(12).text_color(t.dim)
        .child(this.machine ? `${this.machine} · ${pm?.repo || ''}` : shortPath(pm?.repo, home())))
      .when(Boolean(this.error || this.logError), el => el.child(div().id('read-error').text_color(t.blocked)
        .tooltip(`${word(this.lang, 'readError')}: ${this.logError || this.error}`).child('!')))
      .child(keepPress(this.views(t), this.keyFocus))
      .child(keepPress(h_flex().gap(4).items_center(), this.keyFocus)
        .child(bell)
        .child(this.iconButton('pm-terminal', 'terminal', terminal ? word(this.lang, 'openPm') : word(this.lang, 'noPmTerminal'),
          terminal ? () => this.focusTerminal(terminal.address) : null, t))
        .child(this.iconButton('pm-threads', 'panel', word(this.lang, this.listResting() || this.detail ? 'hideThreads' : 'showThreads'),
          cx => this.togglePanel(cx), t)));
  }

  // Conversation | Board. The board is pm-dash's, scoped to this project: shared('pm-dash').project.
  views(t) {
    const option = (key, text, action) => h_flex().id(`view-${key}`).h(26).px(10).gap(6).rounded(7).items_center()
      .text_size(13).accessibility_label(text)
      .when(!action, el => el.bg(t.raised).text_color(t.foreground).font_medium())
      .when(Boolean(action), el => el.cursor_pointer().text_color(t.muted).hover(s => s.text_color(t.foreground))
        .on_click(action))
      .child(this.icon(key, 14)).child(text);
    return h_flex().id('project-view').flex_none().h(34).p(3).gap(2).rounded(10).border_1().border_color(t.border)
      .child(option('chat', word(this.lang, 'chatView'), null))
      .child(option('board', word(this.lang, 'boardView'), () => {
        setShared('pm-dash', { view: 'board', project: this.pmName });
        run('layout.select', { stack: STAGE, child: BOARD });
      }));
  }

  // A session's status as the app's agents list marks it: spinner, dot or ring, never a word.
  sessionMark(status, t) {
    if (status === 'working') return svg(SPINNER).size(12).flex_none().text_color(t.working ?? t.ansi2).spin(900);
    const dot = div().flex_none().size(7).rounded_full();
    return status === 'blocked' ? dot.bg(t.blocked) : status === 'done' ? dot.bg(t.done ?? t.accent) : dot.border(1.5).border_color(t.idle ?? t.dim);
  }

  // What a thread is now, as a mark: an arc that turns while its worker is at work, a ring with a
  // core in the status color while it waits for the user or is in review, a dim ring with a dim
  // core when paused, a bare ring when not started, a small dim ring once it is over.
  threadMark(row, t) {
    const ring = color => h_flex().size(14).flex_none().rounded_full().items_center().justify_center().border(1.5).border_color(color);
    return row.group === 'working'
      ? (row.working ? svg(SPINNER).size(14).flex_none().text_color(t.working ?? t.ansi2).spin(900)
        : svg(SPINNER).size(14).flex_none().text_color(t.dim))
      // Its terminal is gone: an unplugged plug, as quiet as a thread not started.
      : row.group === 'offline' ? this.icon('unplug', 14).text_color(t.dim)
      : row.group === 'finished' ? div().size(9).flex_none().rounded_full().border(1.5).border_color(t.dim)
      : row.group === 'parked' ? ring(t.dim)
        : row.group === 'paused' ? ring(t.dim).child(div().size(6).rounded_full().bg(t.dim))
          : ring(this.toneColor(row.tone, t)).child(div().size(6).rounded_full().bg(this.toneColor(row.tone, t)));
  }

  // The threads the open task was split into, under its status: a row each (its mark, its title,
  // its status), opening that thread as a row of the thread list does. Past PARTS_LIMIT the rest
  // fold behind an expand mark with how many more; opened, they scroll in a box of their own and a
  // collapse mark folds them again, so the log keeps its room.
  partsList(parts, t) {
    const lang = this.lang, open = this.partsOpen === this.thread;
    const { shown, more } = foldParts(parts, open);
    const rows = shown.map(row => {
      const gone = row.offline && row.group !== 'offline' ? word(lang, 'disconnected') : '';
      const label = statusLabel(lang, row.status, row.cleanup, row.offline, row.answered);
      const tip = [label, gone, row.title].filter(Boolean).join(' · ');
      return h_flex().id(`part-${row.task}`).h(30).px(8).gap(9).rounded(8).items_center().cursor_pointer()
        .hover(s => s.bg(t.hover)).tooltip(tip).accessibility_label(tip)
        .on_click((_e, cx) => this.openThread(row.task, cx))
        .child(h_flex().w(16).flex_none().items_center().justify_center().child(this.threadMark(row, t)))
        .child(div().flex_1().min_w(0).truncate().text_size(13)
          .text_color(['parked', 'paused', 'offline', 'finished'].includes(row.group) ? t.muted : t.foreground).child(row.title))
        .child(div().flex_none().text_size(11).text_color(t.dim).child(label));
    });
    const toggle = (id, mark, tip, value) => h_flex().id(id).h(26).px(8).gap(9).rounded(8).items_center().cursor_pointer()
      .text_size(12).text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
      .tooltip(tip).accessibility_label(tip)
      .on_click((_e, cx) => { this.partsOpen = value; cx.notify(); })
      .child(h_flex().w(16).flex_none().items_center().justify_center().child(this.icon(mark, 14)))
      .when(Boolean(more), el => el.child(div().child(tip)));
    const folding = open && parts.length > PARTS_LIMIT;
    return v_flex().flex_none()
      .child(h_flex().h(22).px(8).gap(6).items_center().text_size(11).font_medium().text_color(t.dim)
        .child(word(lang, 'subThreads')).child(String(parts.length)))
      .child(folding ? v_flex().id('thread-parts').max_h(30 * PARTS_LIMIT).overflow_y_scrollbar().children(rows)
        : v_flex().children(rows))
      .when(more > 0, el => el.child(toggle('parts-more', 'expand', word(lang, 'moreParts', more), this.thread)))
      .when(folding, el => el.child(toggle('parts-fold', 'collapse', word(lang, 'fold'), '')));
  }

  // The task's review thread, under its status: its mark, its status and latest report, and the
  // terminal icon that opens the reviewer's terminal (dim once that terminal is gone).
  reviewLine(row, terminal, t) {
    const lang = this.lang, label = statusLabel(lang, row.status, false, row.offline, row.answered);
    return v_flex().flex_none()
      .child(h_flex().h(22).px(8).gap(6).items_center().text_size(11).font_medium().text_color(t.dim)
        .child(word(lang, 'reviewThread')))
      .child(h_flex().id('thread-review').px(8).py(4).gap(9).items_start()
        .tooltip([label, row.title].join(' · ')).accessibility_label([label, row.title].join(' · '))
        .child(h_flex().h(19).w(16).flex_none().items_center().justify_center().child(this.threadMark(row, t)))
        .child(v_flex().flex_1().min_w(0).gap(1)
          .child(div().text_size(13).text_color(row.group === 'finished' ? t.muted : t.foreground).child(label))
          .when(Boolean(row.latest), el => el.child(div().whitespace_normal().text_size(12).text_color(t.dim).child(row.latest))))
        .child(this.iconButton('thread-review-terminal', 'terminal',
          terminal ? word(lang, 'openReviewTerminal') : word(lang, 'threadOffline'),
          terminal ? () => this.focusTerminal(terminal.address) : null, t, 15)));
  }

  // The panel at rest: what is open in this project, who is working in it, and what ended last.
  threadsPanel(pm, t, width) {
    const lang = this.lang;
    const list = threadList(pm, this.tasks || this.state.tasks, this.events, this.terms(), this.live(), spaces().flatMap(s => s.tabs || []), lang);
    const group = (key, rows) => v_flex()
      .child(h_flex().h(26).px(8).gap(6).items_center().text_size(11).font_medium().text_color(t.dim)
        .child(word(lang, key)).child(String(rows.length)))
      .children(rows);
    // Every row starts with a 16px box for its mark, so the groups' marks and words line up.
    const lead = el => h_flex().w(16).flex_none().items_center().justify_center().child(el);
    // The marks sit on the title's line (19px), not the middle of a row with several lines.
    const onTitle = el => h_flex().h(19).flex_none().items_center().child(el);
    const stateMark = row => this.threadMark(row, t);
    const now = Date.now();
    // What each thread's worker runs as, quietly after its title (the detail's label, see engineChip). The tip
    // reads the dispatch reason from the ledger log as the state lists it. At the narrowest panel the title
    // keeps room and the label says only the model. A thread off the board (retired) has its worker's mark in
    // the state's ended_engines instead.
    const byId = new Map((this.tasks || this.state.tasks).map(x => [x.id, x]));
    const logs = new Map();
    for (const e of Array.isArray(this.state.events) ? this.state.events : []) {
      if (e?.task) { if (!logs.has(e.task)) logs.set(e.task, []); logs.get(e.task).push(e); }
    }
    const narrow = width < 300;
    const engineMark = id => {
      const task = byId.get(id) || endedEngine(this.state.ended_engines, id);
      const chip = task ? engineChip(lang, { ...task, log: logs.get(id) || [] }) : null;
      if (!chip) return null;
      return h_flex().id(`engine-${id}`).flex_none().gap(3).items_center().text_size(11).text_color(t.dim).opacity(.85)
        .tooltip(chip.tip).accessibility_label(chip.tip)
        .child(div().whitespace_nowrap().child(narrow ? chip.name : chip.label))
        .when(chip.up, el => el.child(this.icon('up', 10)))
        .when(Boolean(chip.advisor), el => el.child(h_flex().id(`advisor-${id}`).items_center()
          .tooltip(word(lang, 'engineAdvisor', chip.advisor)).accessibility_label(word(lang, 'engineAdvisor', chip.advisor))
          .child(this.icon('advisor', 10))));
    };
    const openRow = row => {
      // One that waits or is in review keeps its group; that its terminal is gone shows under the pointer.
      const gone = row.offline && row.group !== 'offline' ? word(lang, 'disconnected') : '';
      const at = eventTime(row.updated), tip = [statusLabel(lang, row.status, false, row.offline, row.answered), gone, row.title].filter(Boolean).join(' · ');
      const engine = engineMark(row.task);
      return h_flex().id(`list-${row.task}`).px(8).py(7).gap(9).rounded(8).items_start().cursor_pointer()
        .hover(s => s.bg(t.hover)).tooltip(tip).accessibility_label(tip)
        .on_click((_e, cx) => this.openThread(row.task, cx))
        .child(onTitle(lead(stateMark(row))))
        .child(v_flex().flex_1().min_w(0).gap(1)
          .child(h_flex().gap(8).items_baseline()
            .child(div().flex_1().min_w(0).truncate().text_size(13.5).font_medium()
              .text_color(['parked', 'paused', 'offline'].includes(row.group) ? t.muted : t.foreground).child(row.title))
            .when(Boolean(engine), el => el.child(engine))
            .when(at > 0, el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(age(Math.max(0, now - at), lang)))))
          // What it waits for is read whole; a step of work is one line.
          .when(Boolean(row.latest), el => el.child(row.waiting
            ? div().whitespace_normal().text_size(12).text_color(t.muted).child(row.latest)
            : div().truncate().text_size(12).text_color(t.dim).child(row.latest)))
          .when(Boolean(row.branch), el => el.child(h_flex().pt(3).gap(6).items_center().text_color(t.dim)
            .child(svg(ICON('hook')).size(12).flex_none())
            .child(div().min_w(0).truncate().font_family('monospace').text_size(11).child(row.branch)))));
    };
    const byGroup = ['waiting', 'review', 'working', 'offline', 'paused', 'parked']
      .map(key => [`group_${key}`, list.open.filter(row => row.group === key).map(openRow)]);
    const sessions = list.sessions.map(row => {
      const icon = !row.program?.icon ? this.icon('agent', 16).text_color(t.dim)
        : row.program.tint ? svg(row.program.icon).size(16).flex_none().text_color(t.foreground) : image(row.program.icon).size(16).flex_none();
      const state = `${word(lang, `session_${row.status}`)} · ${row.address}`;
      return h_flex().id(`session-${row.address}`).h(32).px(8).gap(9).rounded(8).items_center().cursor_pointer()
        .hover(s => s.bg(t.hover))
        .tooltip([row.label, state, word(lang, 'openSession')].join('\n')).accessibility_label(`${row.label} · ${state}`)
        .on_click(() => this.focusTerminal(row.address))
        .child(lead(icon))
        // The name and the smaller monospace address share a baseline.
        .child(h_flex().flex_1().min_w(0).gap(9).items_baseline()
          .child(div().flex_1().min_w(0).truncate().text_size(13.5).text_color(row.status === 'idle' ? t.muted : t.foreground).child(row.label))
          .child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(row.address)))
        .child(h_flex().w(14).flex_none().justify_center().child(this.sessionMark(row.status, t)));
    });
    // What ended: the conversation's quiet line (a ring and the title), in this list's columns.
    const finished = list.finished.map(row => {
      const tip = [statusLabel(lang, row.status, row.cleanup), row.title].join(' · '), engine = engineMark(row.task);
      return h_flex().id(`list-${row.task}`).h(28).px(8).gap(9).rounded(8).items_center().cursor_pointer().text_size(12.5)
        .text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
        .tooltip(tip).accessibility_label(tip)
        .on_click((_e, cx) => this.openThread(row.task, cx))
        .child(lead(div().size(9).rounded_full().border(1.5).border_color(t.dim)))
        .child(div().flex_1().min_w(0).truncate().child(row.title))
        .when(Boolean(engine), el => el.child(engine));
    });
    const groups = [...byGroup, ['groupSessions', sessions], ['groupFinished', finished]]
      .filter(([, rows]) => rows.length).map(([key, rows]) => group(key, rows));
    return v_flex().w(width).h_full().flex_none().pt(12).bg(t.chrome).border_l(1).border_color(t.border)
      .child(h_flex().h(32).flex_none().px(20).items_center().text_size(15).font_semibold().child(word(lang, 'threads')))
      .child(v_flex().id('thread-list').flex_1().min_h(0).px(12).pt(8).pb(16).gap(12).overflow_y_scrollbar()
        .children(groups.length ? groups : [div().px(8).text_size(13).text_color(t.dim).child(word(lang, 'noThreads'))]));
  }

  panel(t, today, width) {
    const lang = this.lang;
    const stateTask = (this.tasks || this.state.tasks).find(x => x.id === this.thread);
    const task = { ...stateTask, ...this.threadTask };
    const terminal = this.threadTerminal();
    const program = terminal?.program;
    // Offline: what `pm.py state` says of the task now (the ledger file does not carry it).
    const offline = Boolean(stateTask?.offline) && !terminal, quiet = disconnected({ ...task, offline });
    // A task with a folded review reads as the list shows it (foldReviews), not as its ledger file says.
    const status = (stateTask?.review ? stateTask.status : task.status) || '', answered = Boolean(stateTask?.answered);
    const tn = tone(status, Boolean(stateTask?.cleanup), offline, answered);
    // The diff opens a terminal here; a thread on another machine has its branch there.
    const argv = this.machine ? null : diffArgv(task), engine = engineLabel(task);
    const log = (Array.isArray(task.log) ? task.log : []).slice(-60);
    // Waiting for the user: its question at the top, answered here as its card would be (with or without one
    // in the conversation; a waiting review's when one is folded in, see detailQuestion).
    const asks = stateTask ? detailQuestion(stateTask, this.state.tasks.find(x => x.id === this.thread), this.threadTask,
      this.items || []) : null;
    // Split into sub-threads: they are listed under its status, and it links back from each of them.
    const parts = subThreads(this.tasks || this.state.tasks, this.thread, this.terms(), this.live(), lang, this.state.retired_parts);
    const parent = parentThread(this.state.tasks, { ...task, id: this.thread });
    // Its review thread (foldReviews): its status and latest report, and its reviewer's terminal.
    const review = reviewRow(stateTask, this.terms(), this.live(), lang);
    const reviewTerminal = review ? terminalFor(taskRow(stateTask.review), this.terms()) || null : null;
    // The terminal icon opens the thread's terminal; with that terminal gone it reattaches the thread.
    // A task that never had a terminal and was split into sub-threads shows none.
    const does = terminalAction(terminal, { offline, pane: task.pane }, this.reattaching === this.thread, parts.length);
    const terminalIcon = does === 'reattaching'
      ? h_flex().id('thread-terminal').size(32).flex_none().rounded(9).items_center().justify_center().text_color(t.muted)
        .tooltip(word(lang, 'reattaching')).accessibility_label(word(lang, 'reattaching'))
        .child(svg(SPINNER).size(15).flex_none().spin(900))
      : does === 'reattach' ? this.iconButton('thread-terminal', 'reattach', word(lang, 'reattach'), cx => this.reattach(cx), t)
        : terminal && !this.terminalPlace(terminal.address).focus
          ? this.iconButton('thread-terminal', 'terminal', word(lang, 'terminalNowhere'), null, t)
          : this.iconButton('thread-terminal', 'terminal', terminal ? word(lang, 'openTerminal') : word(lang, 'threadOffline'),
            terminal ? () => this.focusTerminal(terminal.address) : null, t);
    const actions = h_flex().gap(2).items_center()
      .when(does !== 'hidden', el => el.child(terminalIcon))
      .child(this.iconButton('thread-diff', 'diff', argv ? word(lang, 'diff') : word(lang, this.machine ? 'remoteDiff' : 'noDiff'), argv ? () => {
        run('terminal.open', { argv, folder: argv[2], place: 'tab', name: word(lang, 'diffTab', task.branch) });
        run('layout.select', { stack: STAGE, child: WORK });
      } : null, t))
      .child(this.iconButton('thread-close', 'close', word(lang, 'close'), cx => { this.detail = false; cx.notify(); }, t));
    const meta = h_flex().flex_wrap().gap(8).items_center().text_size(12).text_color(t.dim)
      .when(Boolean(status), el => el.child(this.pill(statusLabel(lang, status, Boolean(stateTask?.cleanup), offline, answered),
        tn === 'quiet' ? t.muted : this.toneColor(tn, t))))
      // Waiting or in review with its terminal gone: the status stays, and a quiet word says the rest.
      .when(offline && !quiet, el => el.child(this.pill(word(lang, 'disconnected'), t.muted)))
      .when(Boolean(task.branch), el => el.child(div().font_family('monospace').child(task.branch)))
      .when(Boolean(terminal), el => el.child(h_flex().id('thread-agent').gap(5).items_center()
        .tooltip(word(lang, 'agent', program?.name || 'agent', terminal.address))
        .child(!program?.icon ? this.icon('agent', 14) : program.tint ? svg(program.icon).size(14).text_color(t.dim)
          : image(program.icon).size(14))
        .child(div().font_family('monospace').child(terminal.address))))
      // What the worker runs as, quietly beside its agent (a small up arrow once escalated); hover says why.
      .when(Boolean(engine), el => el.child(h_flex().id('thread-engine').gap(3).items_center().text_color(t.dim)
        .opacity(.85).tooltip(engineTip(lang, task)).accessibility_label(engineTip(lang, task))
        .when(wasEscalated(task), el => el.child(this.icon('up', 11)))
        .child(div().whitespace_nowrap().child(engine))));
    const entries = log.length ? log.map((entry, i) => {
      const latest = i === log.length - 1;
      return v_flex().relative().pl(18).gap(2)
        .child(div().absolute().left(0).top(7).size(7).rounded_full().bg(latest ? t.accent : t.border))
        .child(div().font_family('monospace').text_size(12).text_color(t.dim).child(clock(entry.at, today)))
        .child(div().whitespace_normal().text_size(13).text_color(latest ? t.foreground : t.muted)
          .child(logText(lang, entry.text, true)));
    }) : [div().pl(18).text_size(13).text_color(t.dim).child(word(lang, 'noLog'))];
    const timelineEl = v_flex().id('thread-log').flex_1().min_h(0).overflow_y_scrollbar()
      .child(v_flex().relative().gap(16).py(2)
        .child(div().absolute().left(3).top(10).bottom(10).w(1).bg(t.border))
        .children(entries));
    return v_flex().w(width).h_full().flex_none().px(20).pt(12).pb(20).gap(18)
      .bg(t.chrome).border_l(1).border_color(t.border)
      .child(h_flex().gap(2).items_center()
        .child(div().flex_1().min_w(0).truncate().text_size(15).font_semibold().child(task.title || this.thread))
        .child(actions))
      .child(meta)
      .when(Boolean(parent), el => el.child(h_flex().id('thread-parent').gap(5).items_center().cursor_pointer()
        .text_size(12).text_color(t.dim).hover(s => s.text_color(t.foreground))
        .tooltip(word(lang, 'openThread')).accessibility_label(word(lang, 'partOf', parent.title))
        .on_click((_e, cx) => this.openThread(parent.task, cx))
        .child(svg(ICON('hook-up')).size(12).flex_none())
        .child(div().min_w(0).truncate().child(word(lang, 'partOf', parent.title)))))
      .when(Boolean(asks), el => el.child(v_flex().id('thread-question').flex_none().max_h(360).overflow_y_scrollbar()
        .mx(-10).gap(2)
        .when(Boolean(asks.text), el => el.child(div().px(10).pb(6).whitespace_normal().text_size(14)
          .text_color(t.foreground).child(logText(lang, asks.text, true))))
        .children(this.answerRows(asks, t, 'thread-'))))
      .when(Boolean(review), el => el.child(this.reviewLine(review, reviewTerminal, t)))
      .when(parts.length > 0, el => el.child(this.partsList(parts, t)))
      .child(timelineEl)
      .when(Boolean(this.threadError), el => el.child(div().text_size(12).text_color(t.blocked).whitespace_normal()
        .child(word(lang, 'failed', this.threadError))))
      .when(this.reattachError?.id === this.thread && !terminal, el => el.child(div().text_size(12).text_color(t.blocked)
        .whitespace_normal().child(word(lang, 'reattachFailed', this.reattachError.text))))
      .child(this.composer('say-thread', this.threadInput, this.threadDraft, Boolean(terminal), word(lang, 'sayThread'),
        word(lang, 'threadOffline'), cx => this.sendThread(cx), t, 14));
  }

  render(cx) {
    const t = theme();
    this.lang = this.state.lang;
    const lang = this.lang;
    const ref = projectRef(shared(SHARED)), wanted = ref.key;
    if (ref.machine !== this.machine) {
      // A project on another machine (or back here): that machine's ledger, read now.
      // The language stays until that ledger gives its own.
      this.machine = ref.machine; this.state = { pms: [], tasks: [], lang: this.state.lang }; this.stateFor = null;
      this.error = ''; this.logError = ''; this.remoteHome = '';
      cx.timer.after(0, cx => this.refresh(cx));
    }
    if (wanted !== this.pmName) {
      // Another project: its own log, no bubbles or panel from the last one.
      this.pmName = wanted; this.events = []; this.pending = []; this.detail = false; this.thread = ''; this.threadTask = null;
      this.seen = null; this.count = 0; this.settle = 0; this.away = false; this.rise = 0; this.heights = new Map();
      this.unfolded = new Map(); this.newest = '';
      this.bell = null; this.flash = ''; this.answering = null;
      cx.timer.after(0, cx => { this.showMainDraft(); this.readLog(cx); });
    }
    const onStage = findStage(layout())?.active === 'pm-project';
    if (onStage && !this.onStage) cx.timer.after(0, () => this.keyFocus.focus());
    this.onStage = onStage;
    const root = h_flex().id('pm-project-root').size_full().min_w(0).min_h(0).overflow_hidden()
      .bg(t.canvas).text_size(14).text_color(t.foreground)
      .track_focus(this.keyFocus).on_key_down((e, cx) => this.escape(e, cx))
      .on_mouse_move((e, cx) => this.gripMove(e, cx))
      .on_mouse_up('left', (_e, cx) => this.gripUp(cx))
      .on_hover((hovered, cx) => { if (!hovered) this.gripUp(cx); })
      .on_size_change((size, cx) => {
        const wide = size.width >= WIDE;
        this.high = size.height;
        if (wide !== this.wide) { this.wide = wide; cx.notify(); }
        // The panel's width is fitted to the view's (see panelWidth).
        if (size.width !== this.viewWidth) { this.viewWidth = size.width; cx.notify(); }
        // The first measure places the panel; only later changes slide.
        if (!this.measuring) { this.measuring = true; cx.timer.after(60, cx => { this.measured = true; cx.notify(); }); }
      });
    const pm = this.pm();
    if (!pm) {
      // A project on another machine says what it waits for, or why it cannot be read: never a blank page.
      const remote = this.machine && this.stateFor !== this.machine;
      const note = remote ? (this.error ? word(lang, 'remoteError', this.machine, this.error) : word(lang, 'remoteLoading', this.machine))
        : this.pmName && this.state.pms.length ? word(lang, 'noProject') : word(lang, 'pick');
      // No header here: nothing on the page moves the window.
      return keepPress(root, this.keyFocus).items_center().justify_center().child(div().max_w(360).text_color(t.dim).whitespace_normal().child(note));
    }
    const now = new Date(), today = iso(now), yesterday = iso(new Date(now.getTime() - 86400000));
    const pmTerm = this.pmTerminal();
    const working = pmTerm && this.live().find(a => a.address === pmTerm.address)?.status === 'working';
    const items = timeline(this.events, this.state.tasks, {
      pending: this.pending, today, typing: Boolean(working) || this.pending.some(p => !p.failed), pastes: this.pastes || [],
      pm: pm.name,
    });
    this.items = items;
    // Where the bell goes: each waiting task's card, or the thread of one that has none (see bellStops).
    const stops = bellStops(items, this.state.tasks, pm);
    // The box answers a question only while it still waits (a card, or a thread's without one, under
    // askKey): answered meanwhile, or asked anew, it lets go.
    if (this.answering && !stops.some(s => (s.thread ? askKey(s.thread) : s.key) === this.answering.key)) this.answering = null;
    const blocks = timelineRows(turns(items, pm.pane || ''));
    this.atWork = workingTasks(this.terms(), this.live());
    const newest = newestReply(items);
    if (this.newest && newest !== this.newest && !this.unfolded.has(this.newest)) this.unfolded.set(this.newest, true);
    this.newest = newest;
    // Fade only what arrives after the first read of this project.
    this.keys = items.map(i => i.key);
    if (!this.seen && this.events.length) this.seen = new Set(this.keys);
    // Follow the end of the conversation as it grows, including the first read after opening a
    // project, but only for a reader who is at the end: one who scrolled up, or went to a question
    // with the bell, stays there (`away`, see leave) until they say something or scroll back down.
    if (blocks.length !== this.count) {
      if (blocks.length > this.count && blocks.length && !this.away) this.follow();
      this.count = blocks.length;
    }
    // The end marker after the last block: revealing it bottom-aligns the end of a long
    // reply, where revealing the reply itself would rest at its top.
    if (blocks.length && this.settle > 0) {
      this.settle--;
      this.scroll.scroll_to_item(blocks.length);
      if (!this.ticking) { this.ticking = true; cx.timer.after(16, cx => { this.ticking = false; cx.notify(); }); }
    }
    const heights = blocks.map(b => this.heights.get(b.key) || 0), tall = this.tall || this.high;
    // The bell's number is the tasks that wait (see bellCount); a click steps through the places they show.
    // What the user answered no longer waits (see answeredTasks): not on the bell, nor in the side panel.
    const answered = answeredTasks(items);
    // A review thread is no row of its own: it rides on the task it reviews (foldReviews).
    this.tasks = foldReviews(markAnswered(this.state.tasks, answered));
    const waiting = bellCount(pm, this.state.tasks, answered);
    // The card it goes to is marked for a moment: it may already be on screen, where nothing would move.
    // A task without a card: its thread's detail opens, which asks it (threadQuestion).
    const ring = stops.length ? cx => {
      const next = bellNext(stops, this.bell);
      this.bell = { key: next.key, seen: stops.map(s => s.key) };
      if (next.thread) {
        const id = bellThread(next, this.tasks || foldReviews(this.state.tasks), this.detail ? this.thread : '');
        if (id) this.openThread(id, cx);
        return -1;
      }
      const key = next.key;
      this.flash = key;
      cx.timer.after(1500, cx => { if (this.flash === key) { this.flash = ''; cx.notify(); } });
      cx.notify();
      // Where the jump leaves the reader, by the rows' heights: none of it when the row is in view.
      const row = rowOf(blocks, items[next.at]);
      if (row >= 0) this.rest(riseAfterJump(this.rise, heights, row, tall, TAIL));
      return row;
    } : null;
    const center = el => h_flex().w_full().justify_center().px(28).child(div().w_full().max_w(COLUMN).child(el));
    // Rows carry their own space above (22 px between blocks, 12 px between the rows of one turn).
    const above = (b, n) => (n === 0 ? 0 : b.kind === 'turn' && !b.first ? 12 : 22);
    // Scrolling up lets go of the end, scrolling down comes back to it (wheel y > 0 moves toward the
    // top): see riseAfterWheel. The area's content is its top padding, the rows and the end marker.
    const room = TAIL + heights.reduce((sum, h) => sum + h, 0) + TAIL - tall;
    const body = keepPress(v_flex().id('pm-project-timeline'), this.keyFocus).flex_1().min_h(0).pt(TAIL).overflow_y_scrollbar()
      .track_scroll(this.scroll)
      .on_size_change(size => { this.tall = size.height; })
      .on_scroll_wheel(e => { if (e.delta.y) this.rest(riseAfterWheel(this.rise, e.delta.y, room, tall)); })
      .children(blocks.length ? blocks.map((b, n) => center(this.block(b, t, today, yesterday, cx)).pt(above(b, n))
        .id(`block-${b.key}`).on_size_change((size, cx) => { this.heights.set(b.key, size.height); this.resized(cx); }))
        : [center(div().text_color(t.dim).child(word(lang, 'empty')))])
      // The end marker is the column's bottom padding.
      .child(div().flex_none().h(TAIL));
    const main = v_flex().flex_1().min_w(0).h_full()
      .child(this.header(pm, waiting, ring, t))
      .child(body)
      .child(keepPress(center(this.composer('say', this.input, this.draft, Boolean(pmTerm), word(lang, 'say', pm.project || pm.name),
        word(lang, 'offline'), cx => this.sendMain(cx), t, 16, true)).pb(20).pt(4), this.keyFocus));
    // The side panel slides from the right edge. At rest it is the thread list (when the window is
    // wide, or the header's icon asked for it); a thread's detail takes its place while one is open,
    // and stays drawn while a panel that rests closed slides shut.
    // Its left edge drags to set its width (kept for later, see panelWidth); the edge shows as a thin
    // line under the pointer, and a drag follows the pointer without the slide.
    const resting = this.listResting(), open = resting || this.detail;
    const width = panelWidth(this.panelWant, this.viewWidth), dragging = Boolean(this.panelDrag);
    const content = this.detail || (!resting && this.thread) ? this.panel(t, today, width) : this.threadsPanel(pm, t, width);
    const lit = dragging || this.gripLit;
    const grip = h_flex().id('panel-grip').absolute().left(0).top(0).h_full().w(6).cursor_col_resize()
      .accessibility_label(word(lang, 'resizePanel'))
      .on_hover((hovered, cx) => { if (hovered !== this.gripLit) { this.gripLit = hovered; cx.notify(); } })
      .on_mouse_down('left', (e, cx) => this.gripDown(e, cx))
      .child(div().w(2).h_full().bg(lit ? withAlpha(t.accent, dragging ? .9 : .6) : withAlpha(t.accent, 0)));
    const panel = keepPress(h_flex().relative().h_full(), this.keyFocus).flex_none().overflow_hidden().justify_end()
      .w(open ? width : 0)
      .when(this.measured && !dragging, el => el.transition('width', { duration: 200, easing: 'ease-out' }))
      .child(content)
      .when(open, el => el.child(grip));
    return root.child(main).child(panel);
  }
}
