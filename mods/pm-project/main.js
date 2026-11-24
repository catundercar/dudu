import { View, div, svg, image } from 'gpui-kit';
import { v_flex, h_flex, TextView, TextareaState, Textarea, InputState, Input, ScrollHandle, Scrollbar, Popup } from 'gpui-base';
import { theme, home, appHome, exec, readTextFile, writeTextFile, watchFolder, layout, run, terminals, agents, panes, spaces, shared, setShared, props, openOverlay, closeOverlay, window as appWindow } from 'herdr';
import {
  word, timeline, parseConversation, settlePending, answeredTasks, markAnswered, bellStops, bellNext, bellCount, bellThread, detailQuestion, askKey, timelineRows, rowOf, rowOfKey, blockIndexForKey, riseAfterWheel, riseAfterJump, answerText, clock, dayLabel, shortPath,
  sendArgv, makeClientMsgId, projectSendArgv, projectInterruptArgv, rotatePmArgs,
  readScreenArgv, pmLiveStatus, pmTurnWorking, pmActivityView, pmSessionKey, pmCanReceive,
  createAsyncGate, tryEnterAsyncGate, finishAsyncGate, computeClockOffsetMs, eventTimeUtcMs,
  isDialogOrDraftSendError, isTargetGoneSendError, isQueueableSendError, reconcilePendingSends, classifyPmDialog, pmBlockedBannerText,
  QUEUE_KEY, readQueuedSends, keepQueuedSends, restoreQueuedPending, RESEND_VERIFY_WAIT_MS, logKey,
  mergeReceipts, settledReceiptIndices, findReceiptMatch, findCoalescedReceiptMatches, confirmReceiptBubble,
  withoutTerminalEnv, SEND_ENV, REATTACH_ENV, pmRow, taskRow, terminalFor, terminalTargetFor, focusPlan, cleanTaskLog, statusLabel, tone, turns, newestReply, threadList,
  disconnected, isClosedTask, closedDetailText, closedTip, terminalAction, reattachArgv,
  pmStartState, startPmArgs, startPmArgv, lostShown, mergeDismissedLost, lostSummary, bringBackSteps,
  engineLabel, engineTip, engineChip, wasEscalated, endedEngine, escapeStep, searchShortcutLabel,
  subThreads, parentThread, foldParts, PARTS_LIMIT, foldReviews, threadFor,
  taskTree, taskSteps, taskDependencies, threadAgents, resolveAgentProgram, AGENT_WINDOW_MAX, normalizeAgentWindowSize, nextAgentWindowSize, agentWindowDimensions, agentWindowTerminalAddresses, agentWindowOpen, toggleAgentWindow, focusAgentWindow, closeAgentWindow, setAgentWindowOverlay, toggleAgentWindowMode, setAgentWindowSize, reconcileAgentWindows, resolveHelperResultPath,
  age, eventTime, workingTasks, reviewWorking, taskNumber, formatTaskNumber, threadLink, resolveThreadRef, decorateThreadLinks, logText, draftKey, draftText, readDrafts, keepDraft,
  validInputTokens, draftTokens, projectFilesArgv, parseRefLink, parseMentionSpans, splitMentionSegments,
  detectMentionQuery, parseGitLsFiles, indexRepoFiles, buildMentionMenu, REPO_FILES_LIMIT, MENTION_KEY_BINDINGS, SEARCH_KEY_BINDINGS,
  plainTextToHtml, markdownToPlain, extractClipboardQuote, withQuote, withoutQuote, quotePreviewLine, quoteCardPreview,
  splitMarkdownParagraphs, locateQuoteRange, quoteScope, quoteScopeLabel, quoteScopeTip,
  formatQuotedMessage, splitQuotedMessage, draftQuotes, selectionToolbarState,
  draftFiles, withFiles, withoutFile, notFiles, pickedPaths, addFiles, messageText, afterSend, fileName, isImage, pasteName, pasteDir, pastesIn, uploadSteps, landedPath, sentFiles,
  heldFiles, sentLeftovers, staleArgv, staleFiles,
  CHOOSE_FILES, SAVE_CLIPBOARD_IMAGE, PANEL_WIDTH, panelWidth, draggedWidth, readPanelWidth, keepPressHandler,
  withAlpha, solidText, isDarkTheme, viewMarkdown, LEDGER_HOME_SH, EVENT_LIMIT, LOG_LIMIT,
  projectRef, machineView, onMachine, remotePmArgv,
  projectSlug, isOldPmCommand, isReplacedLogError, projectEventsArgv, projectLogArgv,
  freshEventWindow, appendEventWindow, prependEventWindow, keepThreadLog, heldThreadLog, timelineAnchor, findAnchorBlock,
  DOC_INITIAL_BYTES, DOC_MAX_BYTES, SAVE_INLINE_BYTES, REMOTE_CHUNK_BYTES, REMOTE_MKTEMP_ARGV, remoteAppendChunkArgv, chunkUtf8Text,
  MEMORY_TOPICS, PROJECT_MEMORY_TYPES, PERSONAL_MEMORY_TYPES, LIBRARY_DROP_TEXT_EXT,
  projectLibraryArgv, projectMemoryArgv, projectFileArgv, projectSaveArgv, projectDeleteArgv,
  projectRestoreArgv, projectHistoryArgv, projectAddArgv, projectRetopicArgv, adoptCandidateArgv,
  parseVersionConflict, isLibraryRelevantChange, isMemoryRelevantChange, contextKey,
  validLibraryPayload, validMemoryPayload, formatBytes, formatHistoryStamp, contextDay,
  contextShowMode, contextFileError, isWritableDoc, libraryDocTitle, topicLabel, memoryTypeLabel,
  libraryGroups, memoryGroups, searchLibrary, searchMemory, makeDocCacheEntry, isFreshDocEntry,
  makeDocFailEntry, isFreshDocFailure, reconcileDocCache, reconcileDocFailures, keepDocCache,
  documentView, resolveContextLink, markdownChunks, parseFrontmatter, buildMemoryMarkdown,
  memoryFromDroppedFile, slugifyMemoryName, uniqueMemorySlug, retopicPlan,
  SESSION_LIMIT, SESSION_POLL_LOCAL_MS, SESSION_POLL_REMOTE_MS,
  contextTokens, contextShort, contextLabel, pmContextLevel, pmContextTip, workerContextTip,
  isMissingSessionModule, isQuietNoSession, isReplacedSessionError, knownUnsupportedSession, projectSessionArgv,
  takeSessionWindow, trimSessionWindow, workedDuration, sessionTurns,
  CHANGE_DIFF_LIMIT, CHANGE_TIMEOUT_LOCAL_MS, CHANGE_TIMEOUT_REMOTE_MS,
  projectChangeArgv, changeDiffKey, createChangeState, openChangeView, closeChangeView,
  enterChangeFiles, enterChangeFileDiff, stepBackChangeView, appendDiffPage, toggleDiffHunk, toggleAllDiffHunks,
  tooltipLayout, pendingSignature, hostLiveSignature,
} from './model.js';
import { execPython } from './python.js';
import { renderThreadChangeView } from './change_view.js';
import {
  buildProjectSearch, stepSearchSelection, stepSearchScope, stepSearchEscape, renderProjectSearchOverlay,
} from './search.js';
import { renderStepsCard, renderDepsCard, treeBranchList } from './steps.js';

// The project view reads the ledger through the original pm-dash bundle, like pm-list.
const PM_SCRIPT = '/mods/pm-dash/skill/scripts/pm.py';
const STAGE = 'pm-stage', WORK = 'work', BOARD = 'pm-board';
const PARA_HOVER_SHOW_MS = 120, PARA_HOVER_HIDE_MS = 80;
// pm-list names the project to show here: shared('pm-project') = {pm: <PM name>}, or for a PM on
// another machine {pm: '<machine>/<PM name>', machine} (see projectRef).
const SHARED = 'pm-project';
// Split layout: pm-project-header (window_drag block) and pm-project-body (selectable body block)
// coordinate through these two shared keys without duplicating pm.py polling.
const HEADER_STATE = 'pm-project-header-state';
const HEADER_ACTION = 'pm-project-header-action';
const ICON = name => `mods/pm-project/${name}.svg`;
const SPINNER = 'mods/workspace-chrome/spinner.svg';
const STEP_ICONS = {
  checkMark: ICON('check-mark'),
  treeBranch: ICON('tree-branch'),
  expand: ICON('expand'),
  chevron: ICON('chevron'),
  windowPop: ICON('window-pop'),
  spinner: SPINNER,
};
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
    const p = typeof props === 'function' ? props() : null;
    if (p?.agentWindow === 'titlebar' || p?.agentWindow === 'chat') { this.initAgentWindow(p, cx); return; }
    if (p?.header) { this.initHeaderOnly(cx); return; }
    this.bodyOnly = Boolean(p?.body);
    this.lastHeaderState = '';
    this.lastHeaderActionSeq = 0;
    this.ringAction = null;
    this.state = { pms: [], tasks: [] };
    this.events = []; this.logReceipts = []; this.logTurn = null; this.clockOffsetMs = 0; this.serverNowMs = 0; this.serverNowAt = 0;
    this.pending = []; this.pendingByPm = new Map(); this.seq = 0; this.pastes = [];
    this.flushingQueue = false; this.flushingQueueAt = 0; this.queueTimer = false; this.confirmTimer = false; this.lastLogReadAt = 0; this.confirmLogProbes = new Set();
    this.refreshGate = createAsyncGate(); this.logGate = createAsyncGate();
    this.interruptingPm = ''; this.rotatingPm = ''; this.turnTickTimer = false; this._lastPmLiveEdge = ''; this.edgeReadTimer = false;
    this.noProjectSendFor = '';
    this.pmDialog = null; this.pmDialogLoading = false; this.pmDialogAt = 0; this.pmSendBlockError = '';
    this.error = ''; this.logError = '';
    // pmName: the project's key as shared names it; machine: the machine it is on ('' here), whose
    // ledger `state` then is (stateFor: the machine the state was read from; remoteHome: its ledger home).
    this.pmName = ''; this.logPath = ''; this.logSlug = ''; this.machine = ''; this.stateFor = null; this.remoteHome = '';
    this.remoteNoProject = ''; this.logState = null; this.earlierLoading = false; this.earlierError = ''; this.earlierAnchor = null;
    this.ledgerHome = ''; this.watching = {};
    // The side panel: the thread list while it rests, one thread's detail while `detail` is on.
    // listShown: what the header's icon asked for; until then the list shows when the window is wide.
    this.thread = ''; this.threadTask = null; this.detail = false; this.threadError = '';
    this.threadLog = null; this.threadLogKept = []; this.threadEarlierLoading = false; this.threadEarlierError = ''; this.threadAnchor = null;
    this.threadLogExpanded = false;
    this.epicOverrides = new Map();
    this.expandedDone = new Set();
    this.substepsToggle = {};
    this.hoverKey = '';
    this.hoverCardOver = '';
    this.hoverHideTimer = null;
    this.highlightThread = '';
    this.highlightTimer = null;
    this.pendingScrollThread = '';
    this.lastJumpSeq = 0;
    this.agentWindows = [];
    this.winSession = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    this.lastWinEventSeq = 0;
    this.agentWindowSlot = 0;
    // Worker session conversation ("对话" tab in the thread panel).
    this.threadTab = 'log'; this.remoteNoSession = '';
    this.change = createChangeState(); this.remoteNoChange = '';
    this.threadSession = null; this.threadSessionState = ''; this.threadSessionTask = ''; this.threadSessionStale = false;
    this.threadSessionLoading = false; this.threadSessionAgain = false; this.threadSessionError = '';
    this.threadSessionEarlierLoading = false; this.threadSessionEarlierError = ''; this.threadSessionAnchor = null;
    this.sessionToolsOpen = new Set(); this.sessionBriefsOpen = new Set();
    this.sessionAway = false; this.sessionCount = 0; this.sessionSettle = 0;
    this.sessionSent = []; this.lastThreadSendAt = 0; this.lastSessionReadAt = 0;
    // Library & Memory side panel tabs (editable docs/memories, read-only research/instructions).
    this.sideTab = 'threads'; this.remoteNoLibrary = ''; this.remoteNoMemory = '';
    this.librarySlug = ''; this.libraryRoots = []; this.libraryFiles = [];
    this.libraryRead = false; this.libraryProbed = false; this.libraryStale = false;
    this.libraryLoading = false; this.libraryAgain = false; this.libraryError = '';
    this.libraryClosed = new Set(); this.libraryQuery = '';
    this.libraryDropBusy = ''; this.libraryDropError = '';
    this.memorySlug = ''; this.memoryData = null;
    this.memoryRead = false; this.memoryStale = false;
    this.memoryLoading = false; this.memoryAgain = false; this.memoryError = '';
    this.memoryFoldOverrides = new Map();
    this.memoryProjectOpen = true; this.memoryPersonalOpen = false; this.memoryCandidatesOpen = false;
    this.memoryQuery = ''; this.memoryBusy = ''; this.memoryNoticeError = '';
    this.activeDoc = null; this.docCache = new Map(); this.docFailed = new Map();
    this.docLoading = ''; this.docError = ''; this.docShownBytes = DOC_INITIAL_BYTES;
    this.docFindOpen = false; this.docFindQuery = ''; this.docJumpQuery = ''; this.docFindJump = false; this.docMatchPos = 0;
    this.editingDoc = null; this.retopicOpen = false; this.retopicSaving = false; this.retopicError = '';
    this.confirmDeleteKey = ''; this.deleteBusy = ''; this.deleteError = ''; this.deletedBanner = null;
    this.historyView = null;
    // reattaching: the thread whose `pm.py reattach` runs; reattachError: {id, text} of the last that failed.
    this.reattaching = ''; this.reattachError = null;
    // startingPm: project key while `pm.py start` runs; bringBackOpen / bringingBack: lost-agents recovery card.
    this.startingPm = ''; this.startPmError = null;
    this.bringBackOpen = false; this.bringingBack = false; this.bringBackProgress = null;
    this.listShown = null; this.wide = false; this.measured = false;
    this.panelMounted = false; this.panelHideTimer = null;
    this.fadingKeys = null; this.fadeClearTimer = null;
    this._timelineCache = null; this._taskTreeCache = null; this._mdLinkCache = null; this._taskNumIndex = null;
    this._blockKeySet = null;
    this._renderTerms = null; this._renderTermsMachine = null;
    this._renderLive = null; this._renderLiveMachine = null;
    this._renderProjTasks = null; this._renderSpacesTabs = null;
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
    this.bell = null; this.flash = ''; this.flashTone = 'blocked'; this.flashSeq = 0;
    this.jumpTarget = null; this.lastBlocks = []; this.lastTopOffset = 0;
    this.unfolded = new Map(); this.newest = ''; this.atWork = new Set();
    this.scroll = ScrollHandle.new();
    this.threadListScroll = ScrollHandle.new();
    this.threadScroll = ScrollHandle.new();
    this.sessionScroll = ScrollHandle.new();
    this.libraryScroll = ScrollHandle.new();
    this.memoryScroll = ScrollHandle.new();
    this.docScroll = ScrollHandle.new();
    this.historyScroll = ScrollHandle.new();
    this.changeScroll = ScrollHandle.new();
    this.mentionScroll = ScrollHandle.new();
    this.searchScroll = ScrollHandle.new();
    this.searchOpen = false;
    this.searchQuery = '';
    this.searchScope = 'all';
    this.searchIndex = 0;
    this.searchKey = '';
    this.searchConsumedKey = false;
    this.mention = null;
    this.mentionDismissed = null;
    this.mentionConsumedKey = false;
    this.mentionPicking = false;
    this.repoFilesSlug = ''; this.repoFilesRepo = ''; this.repoFiles = [];
    this.repoFilesRead = false; this.repoFilesLoading = false; this.repoFilesAgain = false;
    this.repoFilesError = ''; this.repoFilesTruncated = false; this.repoFilesAt = 0;
    this.pathCopiedAt = 0;
    this.quotes = []; this.quoteSeq = 0; this.hoveredMsg = ''; this.hoverClipboard = null; this.selectionBar = null;
    this.hoveredPara = ''; this.pendingHoverPara = ''; this.paraHoverShowTimer = null; this.paraHoverHideTimer = null; this.paraHoverSeq = 0; this.flashPara = '';
    this.paraCache = new Map();
    this.lastBlocks = []; this.lastTopOffset = 0; this.lastHeights = []; this.lastTall = 0;
    if (typeof cx.bind_keys === 'function') {
      cx.bind_keys([
        ...(Array.isArray(MENTION_KEY_BINDINGS) ? MENTION_KEY_BINDINGS : []),
        ...(Array.isArray(SEARCH_KEY_BINDINGS) ? SEARCH_KEY_BINDINGS : []),
      ]);
    }
    // The page's keyboard, for Esc (escapeStep): taken each time the stage turns to this page; typing:
    // which box ('main' | 'thread' | ...) holds the keyboard, from the boxes' focus and blur.
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
      const content = this.boxContent(this.input);
      this.draft = content.text;
      this.typed(this.mainKey, content.text, content.tokens);
      const changedMention = this.syncMention('main', cx);
      if (had !== Boolean(this.draft.trim()) || changedMention) cx.notify();
    });
    // Enter sends (the key handler below catches it first); Shift+Enter stays a new line.
    this.input.on('submit', (e, cx) => {
      if (e?.shift || this.mentionConsumedKey) return;
      if (this.mentionOpenFor('main')) {
        this.consumeMentionKey(cx);
        this.acceptMention('main', cx);
        return;
      }
      this.sendMain(cx);
    });
    // A paste that found no text: the clipboard's image, if it holds one, becomes an attachment.
    this.input.on('paste_other', (_e, cx) => this.pasteImage('main', cx));
    this.input.on('focus', (_e, cx) => {
      this.typing = 'main';
      if (this.syncMention('main', cx)) cx?.notify?.();
    });
    this.input.on('blur', (_e, cx) => {
      if (this.typing === 'main') this.typing = '';
      cx?.timer?.after(150, cx => {
        if (!this.mentionPicking && this.typing !== 'main' && this.mention?.which === 'main') {
          this.mention = null;
          cx.notify();
        }
      });
    });
    this.threadInput = TextareaState.new({ rows: 1 });
    this.threadInput.set_auto_grow(1, 4);
    this.threadInput.on('change', (_e, cx) => {
      const had = Boolean(this.threadDraft?.trim());
      const content = this.boxContent(this.threadInput);
      this.threadDraft = content.text;
      this.typed(this.threadKey, content.text, content.tokens);
      const changedMention = this.syncMention('thread', cx);
      if (had !== Boolean(this.threadDraft.trim()) || changedMention) cx.notify();
    });
    this.threadInput.on('submit', (e, cx) => {
      if (e?.shift || this.mentionConsumedKey) return;
      if (this.mentionOpenFor('thread')) {
        this.consumeMentionKey(cx);
        this.acceptMention('thread', cx);
        return;
      }
      this.sendThread(cx);
    });
    this.threadInput.on('paste_other', (_e, cx) => this.pasteImage('thread', cx));
    this.threadInput.on('focus', (_e, cx) => {
      this.typing = 'thread';
      if (this.syncMention('thread', cx)) cx?.notify?.();
    });
    this.threadInput.on('blur', (_e, cx) => {
      if (this.typing === 'thread') this.typing = '';
      cx?.timer?.after(150, cx => {
        if (!this.mentionPicking && this.typing !== 'thread' && this.mention?.which === 'thread') {
          this.mention = null;
          cx.notify();
        }
      });
    });
    this.libraryInput = InputState.new();
    this.libraryInput.on('change', (_e, cx) => {
      this.libraryQuery = this.libraryInput.value();
      cx.notify();
    });
    this.libraryInput.on('focus', () => { this.typing = 'librarySearch'; });
    this.libraryInput.on('blur', () => { if (this.typing === 'librarySearch') this.typing = ''; });
    this.memoryInput = InputState.new();
    this.memoryInput.on('change', (_e, cx) => {
      this.memoryQuery = this.memoryInput.value();
      cx.notify();
    });
    this.memoryInput.on('focus', () => { this.typing = 'memorySearch'; });
    this.memoryInput.on('blur', () => { if (this.typing === 'memorySearch') this.typing = ''; });
    this.docFindInput = InputState.new();
    this.docFindInput.on('change', (_e, cx) => {
      this.docFindQuery = this.docFindInput.value();
      this.docMatchPos = 0;
      this.docFindJump = true;
      cx.notify();
    });
    this.docFindInput.on('focus', () => { this.typing = 'docFind'; });
    this.docFindInput.on('blur', () => { if (this.typing === 'docFind') this.typing = ''; });
    this.docNameInput = InputState.new();
    this.docNameInput.on('change', (_e, cx) => { cx.notify(); });
    this.docNameInput.on('focus', () => { this.typing = 'docName'; });
    this.docNameInput.on('blur', () => { if (this.typing === 'docName') this.typing = ''; });
    this.memDescInput = InputState.new();
    this.memDescInput.on('change', (_e, cx) => { cx.notify(); });
    this.memDescInput.on('focus', () => { this.typing = 'memDesc'; });
    this.memDescInput.on('blur', () => { if (this.typing === 'memDesc') this.typing = ''; });
    this.docEditorInput = TextareaState.new({ rows: 14 });
    this.docEditorInput.set_soft_wrap(true);
    this.docEditorInput.on('change', (_e, cx) => { cx.notify(); });
    this.docEditorInput.on('focus', () => { this.typing = 'docEditor'; });
    this.docEditorInput.on('blur', () => { if (this.typing === 'docEditor') this.typing = ''; });
    this.searchInput = InputState.new();
    this.searchInput.on('change', (_e, cx) => {
      this.searchQuery = this.searchInput.value();
      this.searchIndex = 0;
      this.searchKey = '';
      this.searchScroll?.scroll_to_item?.(0);
      cx.notify();
    });
    this.searchInput.on('submit', (_e, cx) => {
      if (this.searchConsumedKey) return;
      this.consumeSearchKey(cx);
      this.acceptProjectSearch(cx);
    });
    this.searchInput.on('focus', () => { this.typing = 'projectSearch'; });
    this.searchInput.on('blur', () => { if (this.typing === 'projectSearch') this.typing = ''; });
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
    cx.timer.every(SESSION_POLL_LOCAL_MS, cx => { if (this.shouldPollThreadSession()) this.readThreadSession(cx); });
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
    // The conversation logs, project documents and project memories live in <ledger home>/projects/<project>/.
    this.watch(this.ledgerHome + '/projects', (paths, cx) => {
      if (!this.machine && (!this.logPath || paths.some(p => p === this.logPath || !p.endsWith('.jsonl')))) this.readLog(cx);
      const slug = projectSlug(this.pm());
      if (!this.machine && isLibraryRelevantChange(paths, { ledgerHome: this.ledgerHome, slug })) {
        this.onLocalLibraryChange(cx);
      }
      if (!this.machine && isMemoryRelevantChange('project', paths, { ledgerHome: this.ledgerHome, slug })) {
        this.onLocalMemoryChange('memory', cx);
      }
    }, cx);
    this.watch(this.ledgerHome + '/memory', (paths, cx) => {
      if (!this.machine && isMemoryRelevantChange('personal', paths, { ledgerHome: this.ledgerHome })) {
        this.onLocalMemoryChange('personal', cx);
      }
    }, cx);
  }

  _enterGate(prop, now, maxBusyMs) {
    let gate = this[prop];
    if (!gate || typeof gate.seq !== 'number') {
      gate = { seq: 0, activeToken: 0, busy: false, deadline: 0, again: false };
      this[prop] = gate;
    }
    const entered = tryEnterAsyncGate(gate, now, maxBusyMs);
    if (typeof entered === 'number') return entered;
    const stamp = Number(now) || 0;
    if (gate.busy && stamp < gate.deadline) { gate.again = true; return 0; }
    const token = ++gate.seq;
    gate.activeToken = token;
    gate.busy = true;
    gate.deadline = stamp + maxBusyMs;
    gate.again = false;
    return token;
  }

  _leaveGate(prop, token) {
    const gate = this[prop];
    if (!gate || typeof gate.seq !== 'number') return { rerun: false, busy: false };
    const finished = finishAsyncGate(gate, token);
    if (typeof finished === 'boolean') return { rerun: finished, busy: Boolean(gate.busy) };
    if (token !== gate.activeToken) return { rerun: false, busy: Boolean(gate.busy) };
    const rerun = Boolean(gate.again);
    gate.busy = false;
    gate.activeToken = 0;
    gate.deadline = 0;
    gate.again = false;
    return { rerun, busy: false };
  }

  isPmWorking(pmTerm, live, activeTurn) {
    const w = pmTurnWorking(pmTerm, live, activeTurn);
    return typeof w === 'boolean' ? w : pmLiveStatus(pmTerm, live) === 'working';
  }

  refresh(cx) {
    const now = this.nowMs();
    const token = this._enterGate('refreshGate', now, 18000);
    if (!token) { this.again = true; return; }
    this.loading = true;
    const machine = this.machine;
    cx.spawn(async cx => {
      try {
        // A project on another machine is read there, through herdr-core (its folders cannot be watched
        // from here: the 10-second read + live status edge trigger keeps it current).
        const r = machine ? await exec(...remotePmArgv(['state']), { on: machine, timeout: 15000 })
          : await execPython(exec, [appHome() + PM_SCRIPT, 'state'], { timeout: 15000 });
        if (r.code !== 0) throw new Error(r.stderr || `pm.py: ${r.code}`);
        const state = JSON.parse(r.stdout);
        if (!Array.isArray(state.pms) || !Array.isArray(state.tasks)) throw new Error('state is missing pms/tasks arrays');
        if (machine === this.machine) {
          const gotAt = this.nowMs();
          this.state = state; this.stateFor = machine;
          const off = computeClockOffsetMs(state, gotAt);
          this.clockOffsetMs = typeof off === 'number' && Number.isFinite(off) ? off : 0;
          if (Number(state.server_now_ms) > 0) {
            this.serverNowMs = Number(state.server_now_ms);
            this.serverNowAt = gotAt;
          }
          this.error = '';
          if (machine) this.remoteHome = typeof state.home === 'string' ? state.home : '';
          else { this.setLedgerHome(state.home, cx); this.arm(cx); }
          if (this.pending?.length) this.reconcilePending(cx);
        }
      } catch (e) { if (machine === this.machine) this.error = String(e?.message || e).trim(); }
      finally {
        const { rerun, busy } = this._leaveGate('refreshGate', token);
        if (!busy) this.loading = false;
        this.readLog(cx);
        this.readThread(cx);
        if ((this.machine && !this.libraryProbed) ||
            (this.libraryVisible() && (Boolean(this.machine) || !this.libraryRead || this.libraryStale))) {
          this.readLibrary(cx);
        }
        if (this.memoryVisible() && (Boolean(this.machine) || !this.memoryRead || this.memoryStale)) {
          this.readMemory(cx);
        }
        cx.notify();
        if (rerun || this.again) { this.again = false; this.refresh(cx); }
      }
    });
  }

  runProject(args, { timeout = 15000 } = {}) {
    return this.machine
      ? exec(...remotePmArgv(args), { on: this.machine, timeout })
      : execPython(exec, [appHome() + PM_SCRIPT, ...args], { timeout });
  }

  runProjectWrite(args, { timeout = 30000 } = {}) {
    if (this.machine) return exec(...remotePmArgv(args), { on: this.machine, timeout });
    if (this.hostPlatform() === 'windows') return execPython(exec, [appHome() + PM_SCRIPT, ...args], { timeout });
    return exec(...withoutTerminalEnv(['python3', appHome() + PM_SCRIPT, ...args], {
      platform: this.hostPlatform(), unset: REATTACH_ENV,
    }), { timeout });
  }

  // Reads the selected project's conversation: the newest byte-anchored window first, then only what was
  // appended after `logState.offset` so earlier windows paged into stay intact. Falls back to `tail` when
  // a remote machine runs an older pm.py that lacks `project events`.
  readLog(cx) {
    const pm = this.pm(), path = pm?.conversation || '', slug = projectSlug(pm), on = this.where();
    if (path !== this.logPath || slug !== this.logSlug) {
      this.logPath = path; this.logSlug = slug;
      this.logState = null; this.events = []; this.logReceipts = []; this.logTurn = null; this.pastes = [];
      this.lastLogReadAt = 0; this.confirmLogProbes = new Set();
      this.earlierLoading = false; this.earlierError = ''; this.earlierAnchor = null;
    }
    if (!path || !slug) { this.lastLogReadAt = this.nowMs(); this.reconcilePending(cx); this.notifySafe(cx); return; }
    const startedAt = this.nowMs();
    const token = this._enterGate('logGate', startedAt, 18000);
    if (!token) { this.logAgain = true; return; }
    this.logLoading = true;
    const machine = this.machine;
    cx.spawn(async cx => {
      try {
        let fallback = Boolean(machine && this.remoteNoProject === machine);
        if (!fallback) {
          const after = this.logState ? this.logState.offset : null;
          const r = await this.runProject(projectEventsArgv(slug, { after, limit: EVENT_LIMIT }));
          if (r.code !== 0) {
            if (machine && isOldPmCommand(r)) {
              this.remoteNoProject = machine;
              this.logState = null;
              fallback = true;
            } else {
              throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim());
            }
          } else {
            const raw = String(r.stdout || '').trim();
            const got = raw ? JSON.parse(raw) : { events: [], from: 0, offset: 0, earlier: false };
            if (path === this.logPath && slug === this.logSlug && machine === this.machine) {
              const gotAt = this.nowMs();
              this.logState = after != null ? appendEventWindow(this.logState, got) : freshEventWindow(got);
              this.events = this.logState.events;
              this.logReceipts = Array.isArray(got.receipts) ? got.receipts : [];
              if (got.turn && typeof got.turn === 'object') this.logTurn = got.turn;
              if (Number(got.server_now_ms) > 0) {
                this.serverNowMs = Number(got.server_now_ms);
                this.serverNowAt = gotAt;
              }
              if (got.server_tz || got.server_now_ms) {
                const off = computeClockOffsetMs({
                  now: this.state?.now || '',
                  server_now_ms: got.server_now_ms,
                  server_tz: got.server_tz,
                }, gotAt);
                if (typeof off === 'number' && Number.isFinite(off) && (off || !this.clockOffsetMs)) {
                  this.clockOffsetMs = off;
                }
              }
              if (got.more) this.logAgain = true;
            }
          }
        }
        if (fallback) {
          const r = await exec('sh', ['-c', 'test -f "$1" || exit 0; tail -n "$2" "$1"', 'sh', path, String(EVENT_LIMIT * 2)], on);
          if (r.code !== 0) throw new Error(r.stderr || `tail: ${r.code}`);
          if (path === this.logPath && machine === this.machine) this.events = parseConversation(r.stdout);
        }
        if (path === this.logPath && machine === this.machine) {
          this.logError = '';
          this.lastLogReadAt = this.nowMs();
          // Which log this read is of: a read of another project's (or machine's) log proves nothing here.
          const log = logKey(machine, path, slug);
          this.logFresh = { log, from: Math.max(this.logFresh?.log === log ? this.logFresh.from : 0, startedAt) };
          this.reconcilePending(cx, { fromReadLog: true });
          // The screenshots pasted into this project, for the messages the log has with image marks
          // (kept here for a project on another machine too, see pasteFolder).
          const dir = this.pasteFolder(pm);
          try {
            const ls = dir ? await exec('sh', ['-c', 'cd "$1" 2>/dev/null && ls -1 || true', 'sh', dir]) : null;
            if (path === this.logPath && ls?.code === 0) this.pastes = pastesIn(dir, ls.stdout);
          } catch (_) { /* Marks then show without their screenshots. */ }
        }
      } catch (e) { if (path === this.logPath && machine === this.machine) this.logError = String(e?.message || e); }
      finally {
        const { rerun, busy } = this._leaveGate('logGate', token);
        if (!busy) this.logLoading = false;
        cx.notify();
        if (rerun || this.logAgain) { this.logAgain = false; this.readLog(cx); }
      }
    });
  }

  // Paging backward through `conversation.jsonl` by byte offset `logState.from`, keeping the reader's place.
  loadEarlierEvents(blocks, cx) {
    const pm = this.pm(), slug = this.logSlug, path = this.logPath, machine = this.machine;
    if (!pm || !slug || !this.logState?.earlier || this.earlierLoading) return;
    const anchor = timelineAnchor(blocks);
    const visibleCount = events => timeline(events, this.state.tasks, { pm: pm.name, taskNumbers: this.state.task_numbers })
      .reduce((n, item) => n + (item.kind === 'threads' ? item.rows.length : 1), 0);
    const beforeCount = visibleCount(this.events);
    this.earlierLoading = true;
    this.earlierError = '';
    this.rest(Math.max(this.rise || 0, this.tall || this.high || 1));
    cx.notify();
    cx.spawn(async cx => {
      try {
        let rounds = 0;
        while (rounds < 5 && this.logState?.earlier && path === this.logPath && slug === this.logSlug && machine === this.machine) {
          rounds++;
          const askedFrom = this.logState.from;
          const r = await this.runProject(projectEventsArgv(slug, { before: askedFrom, limit: EVENT_LIMIT }));
          if (r.code !== 0) {
            const msg = (r.stderr || r.stdout || `pm.py: ${r.code}`).trim();
            if (machine && isOldPmCommand(r)) {
              this.remoteNoProject = machine;
              this.logState = { ...this.logState, earlier: false };
              return;
            }
            if (isReplacedLogError(msg)) {
              this.logState = null;
              this.readLog(cx);
              return;
            }
            throw new Error(msg.split('\n').pop());
          }
          const got = JSON.parse(r.stdout);
          if (path !== this.logPath || slug !== this.logSlug || machine !== this.machine) return;
          this.logState = prependEventWindow(this.logState, askedFrom, got);
          this.events = this.logState.events;
          if (visibleCount(this.events) > beforeCount || !this.logState.earlier) break;
        }
        if (path === this.logPath && machine === this.machine) {
          this.rest(Math.max(this.rise || 0, this.tall || this.high || 1));
          if (anchor) this.earlierAnchor = { anchor, left: SETTLE };
        }
      } catch (e) {
        if (path === this.logPath && machine === this.machine) this.earlierError = String(e?.message || e).trim();
      } finally {
        if (path === this.logPath && machine === this.machine) this.earlierLoading = false;
        cx.notify();
      }
    });
  }

  // The open thread's ledger entry (branch, worktree, base, options), paginated log, and session transcript.
  readThread(cx) {
    const id = this.thread, home = this.machine ? this.remoteHome : this.ledgerHome, on = this.where();
    if (!id) return;
    if (home) {
      cx.spawn(async cx => {
        try {
          const text = await readTextFile(`${home}/tasks/${id}.json`, on);
          if (id === this.thread) {
            this.threadTask = text ? JSON.parse(text) : null;
            this.syncThreadSession(cx);
          }
        } catch (_) { /* Keep what is shown. */ }
        cx.notify();
      });
    }
    this.readThreadLog(cx);
    this.syncThreadSession(cx);
  }

  readThreadLog(cx) {
    const id = this.thread, machine = this.machine;
    if (!id || !this.detail || (machine && this.remoteNoProject === machine)) return;
    if (this.threadLogLoading) { this.threadLogAgain = true; return; }
    this.threadLogLoading = true;
    cx.spawn(async cx => {
      try {
        const r = await this.runProject(projectLogArgv(id, { limit: LOG_LIMIT }));
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.remoteNoProject = machine;
            if (id === this.thread && machine === this.machine) { this.threadLog = null; this.threadLogKept = []; }
          }
          return;
        }
        const page = JSON.parse(r.stdout);
        if (id === this.thread && machine === this.machine && Array.isArray(page?.entries)) {
          this.threadLogKept = keepThreadLog(this.threadLogKept, page);
          this.threadLog = heldThreadLog(page, this.threadLogKept);
        }
      } catch (_) { /* Keep threadTask fallback. */ }
      finally {
        this.threadLogLoading = false;
        cx.notify();
        if (this.threadLogAgain) { this.threadLogAgain = false; this.readThreadLog(cx); }
      }
    });
  }

  loadEarlierThreadLog(cx) {
    const id = this.thread, machine = this.machine, before = this.threadLog?.earlier ?? 0;
    if (!id || !(before > 0) || this.threadEarlierLoading) return;
    const anchorN = this.threadLog?.entries?.[0]?.n ?? null;
    this.threadEarlierLoading = true;
    this.threadEarlierError = '';
    cx.notify();
    cx.spawn(async cx => {
      try {
        const r = await this.runProject(projectLogArgv(id, { before, limit: LOG_LIMIT }));
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.remoteNoProject = machine;
            if (id === this.thread && machine === this.machine) { this.threadLog = null; this.threadLogKept = []; }
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const page = JSON.parse(r.stdout);
        if (id === this.thread && machine === this.machine && Array.isArray(page?.entries)) {
          this.threadLogKept = keepThreadLog(this.threadLogKept, page);
          if (this.threadLog) {
            this.threadLog = page.total < this.threadLog.total
              ? heldThreadLog(page, this.threadLogKept) : heldThreadLog(this.threadLog, this.threadLogKept);
          }
          if (anchorN != null) this.threadAnchor = { n: anchorN, left: SETTLE };
        }
      } catch (e) {
        if (id === this.thread && machine === this.machine) this.threadEarlierError = String(e?.message || e).trim();
      } finally {
        if (id === this.thread && machine === this.machine) this.threadEarlierLoading = false;
        cx.notify();
      }
    });
  }

  resetThreadSession() {
    this.threadSession = null;
    this.threadSessionState = '';
    this.threadSessionTask = '';
    this.threadSessionStale = false;
    this.threadSessionError = '';
    this.threadSessionEarlierLoading = false;
    this.threadSessionEarlierError = '';
    this.threadSessionAnchor = null;
    this.sessionToolsOpen = new Set();
    this.sessionBriefsOpen = new Set();
    this.sessionAway = false;
    this.sessionCount = 0;
    this.sessionSettle = 0;
    this.lastSessionReadAt = 0;
  }

  sessionSupported() {
    return !(this.machine && (this.remoteNoProject === this.machine || this.remoteNoSession === this.machine));
  }

  currentThreadPair() {
    const id = this.thread;
    const stateTask = (this.tasks || this.state?.tasks || []).find(x => x.id === id)
      || (this.state?.tasks || []).find(x => x.id === id) || null;
    const task = { ...stateTask, ...this.threadTask };
    return { stateTask, task };
  }

  threadIsLive(stateTask, task) {
    const status = (stateTask?.review ? stateTask.status : task?.status) || '';
    if (this.threadTerminal()) return true;
    return ['in_progress', 'review', 'blocked'].includes(status) && !stateTask?.offline;
  }

  sessionTabAvailable(stateTask, task) {
    if (!this.sessionSupported() || knownUnsupportedSession(task)) return false;
    if (this.threadSessionTask === this.thread) {
      if (this.threadSessionState === 'unavailable') return false;
      if (this.threadSessionState === 'ready') return true;
      if (this.threadSessionState === 'error') {
        return Boolean(this.threadSession) || contextTokens(stateTask?.context_tokens) > 0 || task?.session?.kind === 'claude';
      }
    }
    return contextTokens(stateTask?.context_tokens) > 0 || task?.session?.kind === 'claude';
  }

  activeThreadTab(stateTask, task) {
    return (this.threadTab === 'session' && this.sessionTabAvailable(stateTask, task)) ? 'session' : 'log';
  }

  selectThreadTab(tab, cx) {
    const { stateTask, task } = this.currentThreadPair();
    if (tab === 'session' && !this.sessionTabAvailable(stateTask, task)) return;
    const freshForThread = !this.threadSession || this.threadSession.taskId !== this.thread;
    this.threadTab = tab === 'session' ? 'session' : 'log';
    if (this.threadTab === 'session') {
      if (freshForThread) {
        this.sessionAway = false;
        this.sessionSettle = SETTLE;
      }
      if (freshForThread || this.threadSessionStale || this.threadIsLive(stateTask, task)) {
        this.readThreadSession(cx);
      }
    }
    cx.notify();
  }

  shouldPollThreadSession() {
    // Fast 4-second tail polling is local-only; remote sessions follow a slower cadence on `refresh`
    // (at most every `SESSION_POLL_REMOTE_MS`) so remote `exec` never runs faster than the main refresh.
    if (!this.onStage || !this.detail || !this.thread || this.machine) return false;
    const { stateTask, task } = this.currentThreadPair();
    if (this.activeThreadTab(stateTask, task) !== 'session') return false;
    if (this.threadSessionTask === this.thread && this.threadSessionState === 'unavailable') return false;
    const recentlySent = Boolean(this.lastThreadSendAt && Date.now() - this.lastThreadSendAt < 15000);
    return recentlySent || Boolean(this.atWork?.has(this.thread)) || Boolean(this.threadTerminal());
  }

  syncThreadSession(cx) {
    const id = this.thread;
    if (!id || !this.detail) return;
    const { stateTask, task } = this.currentThreadPair();
    if (!this.sessionSupported() || knownUnsupportedSession(task)) {
      if (knownUnsupportedSession(task) && this.threadSessionTask !== id) {
        this.threadSessionTask = id;
        this.threadSessionState = 'unavailable';
      }
      return;
    }
    const knownFromState = contextTokens(stateTask?.context_tokens) > 0;
    const wantSession = (this.threadTab === 'session') && (knownFromState || task?.session?.kind === 'claude' || this.threadSessionTask !== id || this.threadSessionState === 'ready');
    if (wantSession) {
      const freshOrStale = !this.threadSession || this.threadSession.taskId !== id || this.threadSessionStale;
      const recentlySent = Boolean(this.lastThreadSendAt && Date.now() - this.lastThreadSendAt < 15000);
      const remoteDue = !this.machine || freshOrStale || recentlySent
        || (Date.now() - (this.lastSessionReadAt || 0) >= SESSION_POLL_REMOTE_MS);
      if ((freshOrStale || this.threadIsLive(stateTask, task)) && remoteDue) {
        this.readThreadSession(cx);
      }
      return;
    }
    // On the Log tab: if `state` already reports `context_tokens`, we already know the Conversation tab is
    // available without spawning `pm.py project session` until the user opens that tab. Only probe when
    // `state` has no `context_tokens` (e.g. an older closed task off the board, or a session not yet indexed).
    if (knownFromState) {
      if (this.threadSession && this.threadSession.taskId === id && this.threadSession.context !== contextTokens(stateTask.context_tokens)) {
        this.threadSessionStale = true;
      }
      if (this.threadSessionState === 'unavailable' && this.threadSessionTask === id) {
        this.threadSessionState = '';
        this.threadSessionTask = '';
      }
      return;
    }
    // Wait until tasks/<id>.json settles when opening a local/remote thread with an existing home, unless
    // no home is known yet (so we avoid probing an agy/codex closed task whose worker kind is in its file).
    const home = this.machine ? this.remoteHome : this.ledgerHome;
    if (!stateTask && home && !this.threadTask && this.threadSessionTask !== id) return;
    if (this.threadSessionTask !== id) {
      if (task?.status === 'proposed' && !task?.session) {
        this.threadSessionTask = id;
        this.threadSessionState = 'unavailable';
        return;
      }
      this.readThreadSession(cx);
    }
  }

  readThreadSession(cx) {
    const id = this.thread, machine = this.machine;
    if (!id || !this.detail || !this.sessionSupported()) return;
    const { task } = this.currentThreadPair();
    if (knownUnsupportedSession(task)) {
      this.threadSessionTask = id;
      this.threadSessionState = 'unavailable';
      return;
    }
    if (this.threadSessionLoading) { this.threadSessionAgain = true; return; }
    this.threadSessionLoading = true;
    this.lastSessionReadAt = Date.now();
    if (this.threadSessionTask !== id) {
      this.threadSessionTask = id;
      this.threadSessionState = 'loading';
    }
    cx.spawn(async cx => {
      try {
        const held = this.threadSession?.taskId === id ? this.threadSession : null;
        const after = held ? held.offset : null;
        const r = await this.runProject(projectSessionArgv(id, { after, limit: SESSION_LIMIT }));
        if (r.code !== 0) {
          if (id !== this.thread || machine !== this.machine) return;
          // Only mark `remoteNoSession`: a remote pm.py that already has `project events/log` (or `context`)
          // but predates `project session` (`invalid choice: 'session'`) must keep paging and Context intact.
          if (machine && isOldPmCommand(r)) {
            this.remoteNoSession = machine;
            this.resetThreadSession();
            return;
          }
          if (isMissingSessionModule(r)) {
            if (machine) this.remoteNoSession = machine;
            this.threadSession = null;
            this.threadSessionTask = id;
            this.threadSessionState = 'unavailable';
            this.threadSessionError = '';
            return;
          }
          if (isQuietNoSession(r)) {
            this.threadSession = null;
            this.threadSessionTask = id;
            this.threadSessionState = 'unavailable';
            this.threadSessionError = '';
            return;
          }
          const msg = (r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop();
          if (after != null && isReplacedSessionError(msg)) {
            this.threadSession = null;
            this.threadSessionAgain = true;
            return;
          }
          throw new Error(msg);
        }
        const raw = String(r.stdout || '').trim();
        if (id !== this.thread || machine !== this.machine) return;
        if (!raw) {
          if (!held) {
            this.threadSessionTask = id;
            this.threadSessionState = 'unavailable';
          }
          return;
        }
        const got = JSON.parse(raw);
        if (!got || typeof got !== 'object' || !Array.isArray(got.items) || typeof got.id !== 'string') {
          if (!held) {
            this.threadSessionTask = id;
            this.threadSessionState = 'unavailable';
          }
          return;
        }
        let next = takeSessionWindow(held, got, after != null ? 'after' : 'end', { taskId: id });
        if (next && !this.sessionAway && !this.threadSessionEarlierLoading) {
          next = trimSessionWindow(next);
        }
        this.threadSession = next;
        this.threadSessionTask = id;
        this.threadSessionState = 'ready';
        this.threadSessionStale = false;
        this.threadSessionError = '';
        if (got.more) this.threadSessionAgain = true;
      } catch (e) {
        if (id === this.thread && machine === this.machine) {
          this.threadSessionTask = id;
          this.threadSessionState = this.threadSession ? 'ready' : 'error';
          this.threadSessionError = String(e?.message || e).trim();
        }
      } finally {
        this.threadSessionLoading = false;
        cx.notify();
        if (this.threadSessionAgain) { this.threadSessionAgain = false; this.readThreadSession(cx); }
      }
    });
  }

  loadEarlierThreadSession(turns, cx) {
    const id = this.thread, machine = this.machine, held = this.threadSession;
    if (!id || !held || held.taskId !== id || !held.earlier || this.threadSessionEarlierLoading) return;
    const anchorKey = turns?.[0]?.key || null;
    const beforeTurnCount = Array.isArray(turns) ? turns.length : 0;
    this.threadSessionEarlierLoading = true;
    this.threadSessionEarlierError = '';
    this.sessionAway = true;
    this.sessionSettle = 0;
    cx.notify();
    cx.spawn(async cx => {
      try {
        let rounds = 0;
        while (rounds < 5 && this.threadSession?.taskId === id && this.threadSession.earlier && id === this.thread && machine === this.machine) {
          rounds++;
          const askedFrom = this.threadSession.from;
          const r = await this.runProject(projectSessionArgv(id, { before: askedFrom, limit: SESSION_LIMIT }));
          if (r.code !== 0) {
            if (id !== this.thread || machine !== this.machine) return;
            const msg = (r.stderr || r.stdout || `pm.py: ${r.code}`).trim();
            if (machine && (isOldPmCommand(r) || isMissingSessionModule(r))) {
              this.remoteNoSession = machine;
              this.threadSession = { ...this.threadSession, earlier: false };
              return;
            }
            if (isReplacedSessionError(msg)) {
              this.threadSession = null;
              this.readThreadSession(cx);
              return;
            }
            throw new Error(msg.split('\n').pop());
          }
          const got = JSON.parse(r.stdout);
          if (id !== this.thread || machine !== this.machine || this.threadSession?.taskId !== id) return;
          this.threadSession = takeSessionWindow(this.threadSession, got, 'before', { taskId: id, askedFrom });
          const nextTurns = sessionTurns(this.threadSession?.items || [], { lang: this.lang, sent: this.sessionSent });
          if (nextTurns.length > beforeTurnCount || !this.threadSession.earlier) break;
        }
        if (id === this.thread && machine === this.machine && anchorKey) {
          this.threadSessionAnchor = { key: anchorKey, left: SETTLE };
        }
      } catch (e) {
        if (id === this.thread && machine === this.machine) {
          this.threadSessionEarlierError = String(e?.message || e).trim();
        }
      } finally {
        if (id === this.thread && machine === this.machine) this.threadSessionEarlierLoading = false;
        cx.notify();
      }
    });
  }

  librarySupported() {
    return !(this.machine && (this.remoteNoProject === this.machine || this.remoteNoLibrary === this.machine));
  }

  memorySupported() {
    return this.librarySupported() && !(this.machine && this.remoteNoMemory === this.machine);
  }

  libraryVisible() {
    return !this.detail && this.listResting() && this.sideTab === 'library' && this.librarySupported();
  }

  memoryVisible() {
    return !this.detail && this.listResting() && this.sideTab === 'memory' && this.memorySupported();
  }

  syncVisibleSideTab(cx) {
    if (this.libraryVisible() && (!this.libraryRead || this.libraryStale)) this.readLibrary(cx);
    if (this.memoryVisible() && (!this.memoryRead || this.memoryStale)) this.readMemory(cx);
  }

  allKnownFiles() {
    return [...(this.libraryFiles || []), ...(this.memoryData?.files || [])];
  }

  findDocMeta(root, path) {
    if (root === 'memory' || root === 'personal') {
      return (this.memoryData?.files || []).find(f => f.root === root && f.path === path) || null;
    }
    return (this.libraryFiles || []).find(f => f.root === root && f.path === path) || null;
  }

  dropCachePrefix(prefixes) {
    for (const map of [this.docCache, this.docFailed]) {
      if (!(map instanceof Map)) continue;
      for (const k of [...map.keys()]) {
        if (prefixes.some(p => k.startsWith(p))) map.delete(k);
      }
    }
  }

  onLocalLibraryChange(cx) {
    if (this.machine) return;
    this.dropCachePrefix(['docs/', 'research/']);
    if (this.libraryVisible()) {
      this.libraryStale = false;
      this.readLibrary(cx);
    } else {
      this.libraryStale = true;
    }
  }

  onLocalMemoryChange(root, cx) {
    if (this.machine) return;
    this.dropCachePrefix([`${root}/`]);
    if (this.memoryVisible()) {
      this.memoryStale = false;
      this.readMemory(cx);
    } else {
      this.memoryStale = true;
    }
  }

  resetLibraryDocState() {
    this.docCache = new Map();
    this.docFailed = new Map();
    this.docLoading = '';
    this.docError = '';
    this.activeDoc = null;
    this.editingDoc = null;
    this.confirmDeleteKey = '';
    this.retopicOpen = false;
    this.historyView = null;
  }

  readLibrary(cx) {
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    if (slug !== this.librarySlug) {
      this.librarySlug = slug;
      this.libraryRoots = [];
      this.libraryFiles = [];
      this.libraryRead = false;
      this.libraryProbed = false;
      this.libraryStale = false;
      this.libraryError = '';
      if (this.activeDoc?.tab === 'library') this.activeDoc = null;
      if (this.editingDoc?.tab === 'library') this.editingDoc = null;
      if (this.historyView?.tab === 'library') this.historyView = null;
    }
    if (!pm || !slug || !this.librarySupported()) {
      if (!this.librarySupported() && (this.sideTab === 'library' || this.sideTab === 'memory')) this.sideTab = 'threads';
      cx.notify();
      return;
    }
    if (this.libraryLoading) { this.libraryAgain = true; return; }
    this.libraryLoading = true;
    this.libraryProbed = true;
    cx.spawn(async cx => {
      try {
        const r = await this.runProject(projectLibraryArgv(slug));
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.remoteNoLibrary = machine;
            this.remoteNoMemory = machine;
            if (machine === this.machine) {
              this.libraryError = '';
              if (this.sideTab === 'library' || this.sideTab === 'memory') this.sideTab = 'threads';
            }
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const raw = String(r.stdout || '').trim();
        const got = raw ? JSON.parse(raw) : { roots: [], files: [] };
        if (slug === this.librarySlug && machine === this.machine) {
          const parsed = validLibraryPayload(got);
          this.libraryRoots = parsed.roots;
          this.libraryFiles = parsed.files;
          const all = this.allKnownFiles();
          this.docCache = reconcileDocCache(this.docCache, all);
          this.docFailed = reconcileDocFailures(this.docFailed, all);
          this.libraryRead = true;
          this.libraryStale = false;
          this.libraryError = '';
          if (this.sideTab === 'library') {
            this.prefetchLibraryDocs(cx);
            if (this.activeDoc?.tab === 'library' && !this.editingDoc) {
              const openKey = contextKey(this.activeDoc);
              const openMeta = this.findDocMeta(this.activeDoc.root, this.activeDoc.path);
              const cached = this.docCache.get(openKey);
              const failed = this.docFailed.get(openKey);
              if (!isFreshDocEntry(cached, openMeta) && !isFreshDocFailure(failed, openMeta)) {
                this.readDoc(this.activeDoc.root, this.activeDoc.path, cx, { force: true, background: true });
              }
            }
          }
        }
      } catch (e) {
        if (slug === this.librarySlug && machine === this.machine) {
          this.libraryError = String(e?.message || e).trim();
        }
      } finally {
        this.libraryLoading = false;
        cx.notify();
        if (this.libraryAgain) { this.libraryAgain = false; this.readLibrary(cx); }
      }
    });
  }

  readMemory(cx) {
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    if (slug !== this.memorySlug) {
      this.memorySlug = slug;
      this.memoryData = null;
      this.memoryRead = false;
      this.memoryStale = false;
      this.memoryError = '';
      if (this.activeDoc?.tab === 'memory') this.activeDoc = null;
      if (this.editingDoc?.tab === 'memory') this.editingDoc = null;
      if (this.historyView?.tab === 'memory') this.historyView = null;
    }
    if (!pm || !slug || !this.memorySupported()) {
      if (!this.memorySupported() && this.sideTab === 'memory') this.sideTab = 'threads';
      cx.notify();
      return;
    }
    if (this.memoryLoading) { this.memoryAgain = true; return; }
    this.memoryLoading = true;
    cx.spawn(async cx => {
      try {
        const r = await this.runProject(projectMemoryArgv(slug));
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.remoteNoMemory = machine;
            if (machine === this.machine) {
              this.memoryError = '';
              if (this.sideTab === 'memory') this.sideTab = 'threads';
            }
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const raw = String(r.stdout || '').trim();
        const got = raw ? JSON.parse(raw) : {};
        if (slug === this.memorySlug && machine === this.machine) {
          this.memoryData = validMemoryPayload(got);
          const all = this.allKnownFiles();
          this.docCache = reconcileDocCache(this.docCache, all);
          this.docFailed = reconcileDocFailures(this.docFailed, all);
          this.memoryRead = true;
          this.memoryStale = false;
          this.memoryError = '';
          if (this.sideTab === 'memory' && this.activeDoc?.tab === 'memory' && !this.editingDoc) {
            const openKey = contextKey(this.activeDoc);
            const openMeta = this.findDocMeta(this.activeDoc.root, this.activeDoc.path);
            const cached = this.docCache.get(openKey);
            const failed = this.docFailed.get(openKey);
            if (!isFreshDocEntry(cached, openMeta) && !isFreshDocFailure(failed, openMeta)) {
              this.readDoc(this.activeDoc.root, this.activeDoc.path, cx, { force: true, background: true });
            }
          }
        }
      } catch (e) {
        if (slug === this.memorySlug && machine === this.machine) {
          this.memoryError = String(e?.message || e).trim();
        }
      } finally {
        this.memoryLoading = false;
        cx.notify();
        if (this.memoryAgain) { this.memoryAgain = false; this.readMemory(cx); }
      }
    });
  }

  // Prefetches small editable documents (`docs`) once Library is shown so search matches their body text.
  prefetchLibraryDocs(cx) {
    const slug = this.librarySlug, machine = this.machine;
    if (!slug || !this.librarySupported()) return;
    let count = 0;
    for (const f of this.libraryFiles || []) {
      if (count >= 6) break;
      if (f.root !== 'docs' || f.kind === 'folder' || f.archive || f.size > 65536 || contextShowMode(f, f.path) !== 'text') continue;
      count++;
      const key = contextKey(f);
      if (isFreshDocEntry(this.docCache.get(key), f) || isFreshDocFailure(this.docFailed.get(key), f)) continue;
      const snapMeta = f;
      cx.spawn(async cx => {
        try {
          const r = await this.runProject(projectFileArgv(slug, 'docs', f.path));
          if (r.code !== 0) {
            if (slug === this.librarySlug && machine === this.machine) {
              const errLine = (r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop();
              const friendly = contextFileError(this.lang || this.state?.lang, errLine, { isMemory: false });
              this.docFailed?.set(key, makeDocFailEntry(friendly, snapMeta));
            }
            return;
          }
          const got = JSON.parse(r.stdout);
          if (slug === this.librarySlug && machine === this.machine && typeof got?.text === 'string') {
            this.docFailed?.delete(key);
            this.docCache = keepDocCache(this.docCache, key, makeDocCacheEntry(got, snapMeta));
            if (this.libraryQuery.trim()) cx.notify();
          }
        } catch (_) { /* On-demand read still works when clicked. */ }
      });
    }
  }

  readDoc(root, path, cx, { force = false, background = false } = {}) {
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    if (!pm || !slug || !root || !path || (root !== 'repo' && !this.librarySupported())) return;
    const key = `${root}/${path}`;
    const meta = this.findDocMeta(root, path);
    const mode = contextShowMode(meta, path);
    if (mode !== 'text') {
      this.docLoading = '';
      this.docError = '';
      cx.notify();
      return;
    }
    if (!force && isFreshDocEntry(this.docCache.get(key), meta)) {
      this.docLoading = '';
      this.docError = '';
      this.docFailed?.delete(key);
      cx.notify();
      return;
    }
    const existingFail = this.docFailed?.get(key);
    if (!force && isFreshDocFailure(existingFail, meta)) {
      this.docLoading = '';
      this.docError = existingFail.error;
      cx.notify();
      return;
    }
    if (force) this.docFailed?.delete(key);
    const snapMeta = meta || null;
    const hasCached = Boolean(this.docCache.get(key));
    if (!background || !hasCached) {
      this.docLoading = key;
      this.docError = '';
      cx.notify();
    }
    cx.spawn(async cx => {
      try {
        let got = null;
        const r = await this.runProject(projectFileArgv(slug, root, path));
        if (r.code !== 0) {
          const errText = `${r.stderr || ''}\n${r.stdout || ''}`;
          if (root === 'repo' && machine && (isOldPmCommand(r) || /invalid choice.*repo|invalid document root/i.test(errText)) && pm.repo) {
            const chk = await exec('git', ['--literal-pathspecs', '-C', pm.repo, 'ls-files', '-z', '--error-unmatch', '--', path], { ...this.where(), timeout: 10000 });
            if (chk.code !== 0 || !parseGitLsFiles(chk.stdout).includes(path)) throw new Error(`no such document: ${key}`);
            const rawText = await readTextFile(`${pm.repo}/${path}`, this.where());
            if (rawText == null) throw new Error(`no such document: ${key}`);
            if (rawText.includes('\0')) throw new Error('not a text file');
            got = { text: rawText, size: rawText.length, version: '' };
          } else if (machine && isOldPmCommand(r)) {
            this.remoteNoLibrary = machine;
            this.remoteNoMemory = machine;
            if (machine === this.machine && (this.sideTab === 'library' || this.sideTab === 'memory')) this.sideTab = 'threads';
            return;
          } else {
            throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
          }
        } else {
          got = JSON.parse(r.stdout);
        }
        if (projectSlug(this.pm()) === slug && machine === this.machine && typeof got?.text === 'string') {
          this.docFailed?.delete(key);
          this.docCache = keepDocCache(this.docCache, key, makeDocCacheEntry(got, snapMeta));
          if (this.activeDoc && `${this.activeDoc.root}/${this.activeDoc.path}` === key) this.docError = '';
        }
      } catch (e) {
        if (projectSlug(this.pm()) === slug && machine === this.machine) {
          const friendly = contextFileError(this.lang || this.state?.lang, e?.message || e, {
            isMemory: root === 'memory' || root === 'personal',
            isRepo: root === 'repo',
          });
          this.docFailed?.set(key, makeDocFailEntry(friendly, snapMeta));
          if (this.activeDoc && `${this.activeDoc.root}/${this.activeDoc.path}` === key) {
            this.docError = friendly;
          }
        }
      } finally {
        if (this.docLoading === key) this.docLoading = '';
        cx.notify();
      }
    });
  }

  openDoc(target, cx, opts = {}) {
    if (!target?.root || !target?.path) return;
    const tab = target.tab || (target.root === 'memory' || target.root === 'personal' ? 'memory' : 'library');
    const key = `${target.root}/${target.path}`;
    const currentKey = this.activeDoc ? `${this.activeDoc.root}/${this.activeDoc.path}` : '';
    if (currentKey !== key) {
      this.docShownBytes = DOC_INITIAL_BYTES;
      this.docError = '';
      this.docFindOpen = false;
      this.docFindQuery = '';
      this.docMatchPos = 0;
      this.docFindInput?.set_value('');
    }
    this.confirmDeleteKey = '';
    this.deleteError = '';
    this.retopicOpen = false;
    this.retopicError = '';
    this.editingDoc = null;
    this.historyView = null;
    this.sideTab = tab;
    this.activeDoc = { tab, root: target.root, path: target.path };
    const q = String((opts?.jumpQuery !== undefined ? opts.jumpQuery : (tab === 'memory' ? this.memoryQuery : this.libraryQuery)) || '').trim();
    this.docJumpQuery = q;
    this.docFindJump = Boolean(q);
    this.readDoc(target.root, target.path, cx);
  }

  closeActiveDoc(cx) {
    const wasRepo = this.activeDoc?.root === 'repo';
    this.activeDoc = null;
    this.docError = '';
    this.docFindOpen = false;
    this.docFindQuery = '';
    this.docJumpQuery = '';
    this.docMatchPos = 0;
    this.confirmDeleteKey = '';
    this.deleteError = '';
    this.retopicOpen = false;
    this.retopicError = '';
    this.editingDoc = null;
    this.docFindInput?.set_value('');
    if (wasRepo && !this.librarySupported() && this.sideTab === 'library') this.sideTab = 'threads';
    if (this.typing === 'docFind') this.keyFocus?.focus();
    cx.notify();
  }

  selectSideTab(tab, cx) {
    if (tab === 'library' && !this.librarySupported()) return;
    if (tab === 'memory' && !this.memorySupported()) return;
    this.sideTab = tab;
    this.detail = false;
    this.resetThreadChange();
    this.confirmDeleteKey = '';
    this.retopicOpen = false;
    if (tab === 'library') {
      if (this.machine || !this.libraryRead || this.libraryStale) this.readLibrary(cx);
      else this.prefetchLibraryDocs(cx);
    } else if (tab === 'memory') {
      if (this.machine || !this.memoryRead || this.memoryStale) this.readMemory(cx);
    }
    cx.notify();
  }

  followDocLink(url, cx) {
    const rel = resolveContextLink(this.activeDoc, url, this.allKnownFiles());
    if (rel) { this.openDoc(rel, cx); return; }
    this.followLink(url, cx);
  }

  async saveProjectText(slug, root, path, text, { ifVersion = null } = {}) {
    const byteLen = new TextEncoder().encode(text).length;
    if (byteLen > SAVE_INLINE_BYTES) {
      if (!this.machine && this.ledgerHome) {
        const tmp = `${this.ledgerHome}/.pm-edit-${Date.now()}-${Math.random().toString(36).slice(2, 8)}.tmp`;
        await writeTextFile(tmp, text, null);
        try {
          return await this.runProjectWrite(projectSaveArgv(slug, root, path, { fromFile: tmp, ifVersion }));
        } finally {
          await exec('rm', ['-f', '--', tmp], { timeout: 10000 }).catch(() => {});
        }
      }
      if (this.machine || this.hostPlatform() !== 'windows') {
        const on = this.where();
        const mk = await exec(...REMOTE_MKTEMP_ARGV, { ...on, timeout: 15000 });
        const tmp = String(mk.stdout || '').trim();
        if (mk.code !== 0 || !tmp) {
          return { code: mk.code || 1, stdout: mk.stdout || '', stderr: mk.stderr || 'mktemp failed' };
        }
        try {
          for (const chunk of chunkUtf8Text(text, REMOTE_CHUNK_BYTES)) {
            const w = await exec(...remoteAppendChunkArgv(tmp, chunk), { ...on, timeout: 15000 });
            if (w.code !== 0) return w;
          }
          return await this.runProjectWrite(projectSaveArgv(slug, root, path, { fromFile: tmp, ifVersion }));
        } finally {
          await exec('rm', ['-f', '--', tmp], { ...on, timeout: 10000 }).catch(() => {});
        }
      }
    }
    return this.runProjectWrite(projectSaveArgv(slug, root, path, { text, ifVersion }));
  }

  startNewDoc(tab, cx) {
    this.confirmDeleteKey = '';
    this.retopicOpen = false;
    this.historyView = null;
    this.deletedBanner = null;
    if (tab === 'memory') {
      this.editingDoc = {
        mode: 'create',
        tab: 'memory',
        root: 'memory',
        path: '',
        layer: 'project',
        type: 'project',
        topic: 'architecture',
        version: '',
        originalName: '',
        originalDesc: '',
        originalText: '',
        originalType: 'project',
        originalTopic: 'architecture',
        existingRaw: '',
        saving: false,
        error: '',
        conflict: null,
      };
      this.docNameInput?.set_value('');
      this.memDescInput?.set_value('');
      this.docEditorInput?.set_value('');
      cx.timer?.after(0, () => this.docNameInput?.focus());
    } else {
      this.editingDoc = {
        mode: 'create',
        tab: 'library',
        root: 'docs',
        path: '',
        version: '',
        originalName: '',
        originalText: '',
        saving: false,
        error: '',
        conflict: null,
      };
      this.docNameInput?.set_value('');
      this.docEditorInput?.set_value('');
      cx.timer?.after(0, () => this.docNameInput?.focus());
    }
    cx.notify();
  }

  startEditDoc(cx) {
    const docRef = this.activeDoc;
    if (!docRef) return;
    const key = `${docRef.root}/${docRef.path}`;
    const meta = this.findDocMeta(docRef.root, docRef.path);
    const cached = this.docCache.get(key);
    if (!meta || !isWritableDoc(meta) || !cached) return;
    this.confirmDeleteKey = '';
    this.retopicOpen = false;
    const isMem = docRef.tab === 'memory' || docRef.root === 'memory' || docRef.root === 'personal';
    const version = cached.version || meta.version || '';
    if (isMem) {
      const parsed = parseFrontmatter(cached.text);
      const f = parsed.fields;
      const desc = (f.description || meta.description || '').trim();
      const layer = docRef.root === 'personal' ? 'personal' : 'project';
      const type = f.type || meta.type || (layer === 'personal' ? 'user' : 'project');
      const topic = f.topic || meta.topic || 'architecture';
      const body = parsed.body === desc ? '' : parsed.body;
      this.editingDoc = {
        mode: 'edit',
        tab: 'memory',
        root: docRef.root,
        path: docRef.path,
        layer,
        type,
        topic,
        version,
        originalName: meta.name || fileName(docRef.path).replace(/\.md$/i, ''),
        originalDesc: desc,
        originalText: body,
        originalType: type,
        originalTopic: topic,
        existingRaw: cached.text,
        saving: false,
        error: '',
        conflict: null,
      };
      this.memDescInput?.set_value(desc);
      this.docEditorInput?.set_value(body);
      cx.timer?.after(0, () => this.docEditorInput?.focus());
    } else {
      this.editingDoc = {
        mode: 'edit',
        tab: 'library',
        root: docRef.root,
        path: docRef.path,
        version,
        originalName: docRef.path,
        originalText: cached.text,
        saving: false,
        error: '',
        conflict: null,
      };
      this.docEditorInput?.set_value(cached.text);
      cx.timer?.after(0, () => this.docEditorInput?.focus());
    }
    cx.notify();
  }

  cancelEditDoc(cx) {
    this.editingDoc = null;
    if (this.typing === 'docEditor' || this.typing === 'docName' || this.typing === 'memDesc') {
      this.keyFocus?.focus();
    }
    cx.notify();
  }

  editorDirty() {
    const ed = this.editingDoc;
    if (!ed) return false;
    const bodyNow = this.docEditorInput?.value() ?? '';
    if (ed.tab === 'memory') {
      const descNow = this.memDescInput?.value() ?? '';
      const nameNow = ed.mode === 'create' ? (this.docNameInput?.value() ?? '').trim() : ed.originalName;
      return bodyNow !== ed.originalText || descNow !== ed.originalDesc || nameNow !== ed.originalName
        || ed.type !== ed.originalType || ed.topic !== ed.originalTopic;
    }
    const nameNow = ed.mode === 'create' ? (this.docNameInput?.value() ?? '').trim() : ed.originalName;
    return bodyNow !== ed.originalText || nameNow !== ed.originalName;
  }

  async saveEditingDoc(cx, { overwrite = false } = {}) {
    const ed = this.editingDoc;
    const slug = projectSlug(this.pm());
    if (!ed || !slug || ed.saving) return;
    const lang = this.lang;
    let root = ed.root;
    let relPath = ed.path;
    let payloadText = this.docEditorInput?.value() ?? '';
    if (ed.tab === 'library') {
      if (ed.mode === 'create') {
        let name = String(this.docNameInput?.value() ?? '').trim().replace(/^\/+/, '');
        if (!name || name.includes('..')) {
          ed.error = word(lang, 'saveFailed', word(lang, 'docNamePlaceholder'));
          cx.notify();
          return;
        }
        if (!name.includes('.')) name += '.md';
        relPath = name;
      }
    } else {
      root = ed.layer === 'personal' ? 'personal' : 'memory';
      const rawName = ed.mode === 'create' ? (this.docNameInput?.value() ?? '').trim() : ed.originalName;
      const memSlug = ed.mode === 'create' ? slugifyMemoryName(rawName) : ed.originalName;
      const desc = String(this.memDescInput?.value() ?? '').trim();
      if (!memSlug) {
        ed.error = word(lang, 'saveFailed', word(lang, 'memNamePlaceholder'));
        cx.notify();
        return;
      }
      if (!desc) {
        ed.error = word(lang, 'saveFailed', word(lang, 'memDescPlaceholder'));
        cx.notify();
        return;
      }
      relPath = `${memSlug}.md`;
      payloadText = buildMemoryMarkdown({
        name: memSlug,
        description: desc,
        type: ed.type,
        topic: ed.topic,
        body: payloadText,
        existingRaw: ed.existingRaw,
      });
    }

    ed.saving = true;
    ed.error = '';
    ed.conflict = null;
    cx.notify();
    const ifVersion = overwrite ? null : (ed.mode === 'create' ? 'new' : (ed.version || null));
    try {
      const r = await this.saveProjectText(slug, root, relPath, payloadText, { ifVersion });
      const conflict = parseVersionConflict(r);
      if (conflict) {
        if (this.editingDoc === ed) {
          ed.conflict = conflict;
          ed.saving = false;
        }
        cx.notify();
        return;
      }
      if (r.code !== 0) {
        throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
      }
      const key = `${root}/${relPath}`;
      this.docCache.delete(key);
      this.docFailed.delete(key);
      if (this.editingDoc === ed) {
        this.editingDoc = null;
        this.activeDoc = { tab: ed.tab, root, path: relPath };
      }
      if (this.typing === 'docEditor' || this.typing === 'docName' || this.typing === 'memDesc') {
        this.keyFocus?.focus();
      }
      if (ed.tab === 'memory') this.readMemory(cx);
      else this.readLibrary(cx);
      this.readDoc(root, relPath, cx, { force: true });
    } catch (e) {
      if (this.editingDoc === ed) {
        ed.error = word(lang, 'saveFailed', String(e?.message || e).trim());
        ed.saving = false;
      }
    }
    cx.notify();
  }

  async reloadConflictDoc(cx) {
    const ed = this.editingDoc;
    const slug = projectSlug(this.pm());
    if (!ed || !slug) return;
    try {
      const r = await this.runProject(projectFileArgv(slug, ed.root, ed.path));
      if (r.code !== 0) throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim());
      const got = JSON.parse(r.stdout);
      const text = String(got?.text ?? '');
      const version = String(got?.version || '');
      if (this.editingDoc !== ed) return;
      ed.version = version;
      ed.conflict = null;
      ed.error = '';
      if (ed.tab === 'memory') {
        const parsed = parseFrontmatter(text);
        const f = parsed.fields;
        const desc = (f.description || '').trim();
        const body = parsed.body === desc ? '' : parsed.body;
        ed.existingRaw = text;
        ed.originalDesc = desc;
        ed.originalText = body;
        ed.type = f.type || ed.type;
        ed.topic = f.topic || ed.topic;
        ed.originalType = ed.type;
        ed.originalTopic = ed.topic;
        this.memDescInput?.set_value(desc);
        this.docEditorInput?.set_value(body);
      } else {
        ed.originalText = text;
        this.docEditorInput?.set_value(text);
      }
      this.docCache = keepDocCache(this.docCache, `${ed.root}/${ed.path}`, makeDocCacheEntry(got, this.findDocMeta(ed.root, ed.path)));
    } catch (e) {
      if (this.editingDoc === ed) ed.error = word(this.lang, 'docReadError', String(e?.message || e));
    }
    cx.notify();
  }

  async applyRetopic(nextTopic, nextType, cx) {
    const docRef = this.activeDoc;
    const slug = projectSlug(this.pm());
    if (!docRef || !slug || this.retopicSaving) return;
    const meta = this.findDocMeta(docRef.root, docRef.path);
    if (!meta) return;
    const plan = retopicPlan(meta, { nextTopic, nextType });
    if (plan.topic === meta.topic && plan.type === meta.type) {
      this.retopicOpen = false;
      cx.notify();
      return;
    }
    this.retopicSaving = true;
    this.retopicError = '';
    cx.notify();
    try {
      const r = await this.runProjectWrite(projectRetopicArgv(slug, meta.name, {
        topic: plan.topic,
        type: plan.type,
        personal: meta.layer === 'personal',
      }));
      if (r.code !== 0) throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
      this.retopicOpen = false;
      const key = `${docRef.root}/${docRef.path}`;
      this.docCache.delete(key);
      this.readMemory(cx);
      this.readDoc(docRef.root, docRef.path, cx, { force: true });
    } catch (e) {
      this.retopicError = word(this.lang, 'retopicFailed', String(e?.message || e).trim());
    } finally {
      this.retopicSaving = false;
      cx.notify();
    }
  }

  async deleteActiveDoc(cx) {
    const docRef = this.activeDoc;
    const slug = projectSlug(this.pm());
    if (!docRef || !slug || this.deleteBusy) return;
    const key = `${docRef.root}/${docRef.path}`;
    const meta = this.findDocMeta(docRef.root, docRef.path);
    const cached = this.docCache.get(key);
    const ifVersion = cached?.version || meta?.version || null;
    this.deleteBusy = key;
    this.deleteError = '';
    cx.notify();
    try {
      const r = await this.runProjectWrite(projectDeleteArgv(slug, docRef.root, docRef.path, { ifVersion }));
      if (r.code !== 0) throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
      this.docCache.delete(key);
      this.docFailed.delete(key);
      this.confirmDeleteKey = '';
      this.deletedBanner = {
        tab: docRef.tab,
        root: docRef.root,
        path: docRef.path,
        name: meta?.name || fileName(docRef.path),
      };
      this.activeDoc = null;
      if (docRef.tab === 'memory') this.readMemory(cx);
      else this.readLibrary(cx);
    } catch (e) {
      this.deleteError = word(this.lang, 'deleteFailed', String(e?.message || e).trim());
    } finally {
      this.deleteBusy = '';
      cx.notify();
    }
  }

  async undoDeletedBanner(cx) {
    const banner = this.deletedBanner;
    const slug = projectSlug(this.pm());
    if (!banner || !slug) return;
    this.deletedBanner = null;
    cx.notify();
    try {
      const r = await this.runProjectWrite(projectRestoreArgv(slug, banner.root, banner.path));
      if (r.code !== 0) throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
      if (banner.tab === 'memory') this.readMemory(cx);
      else this.readLibrary(cx);
    } catch (e) {
      if (banner.tab === 'memory') this.memoryNoticeError = word(this.lang, 'restoreFailed', String(e?.message || e));
      else this.libraryDropError = word(this.lang, 'restoreFailed', String(e?.message || e));
    }
    cx.notify();
  }

  async openHistory(tab, root, path, scope, cx) {
    const slug = projectSlug(this.pm());
    if (!slug) return;
    this.confirmDeleteKey = '';
    this.retopicOpen = false;
    const hv = { tab, scope, root, path, items: [], loading: true, error: '', restoring: '' };
    this.historyView = hv;
    cx.notify();
    try {
      const roots = tab === 'memory' && scope === 'all' ? ['memory', 'personal'] : [root];
      const results = await Promise.all(roots.map(r => this.runProject(projectHistoryArgv(slug, r, scope === 'item' ? path : ''))));
      const items = [];
      for (const res of results) {
        if (res.code !== 0) throw new Error((res.stderr || res.stdout || `pm.py: ${res.code}`).trim().split('\n').pop());
        const parsed = JSON.parse(res.stdout || '{}');
        if (Array.isArray(parsed.items)) items.push(...parsed.items);
      }
      items.sort((a, b) => String(b.version || '').localeCompare(String(a.version || '')) || String(a.path || '').localeCompare(String(b.path || '')));
      if (this.historyView === hv) {
        hv.items = items;
        hv.loading = false;
      }
    } catch (e) {
      if (this.historyView === hv) {
        hv.error = word(this.lang, 'historyReadError', String(e?.message || e).trim());
        hv.loading = false;
      }
    }
    cx.notify();
  }

  closeHistory(cx) {
    this.historyView = null;
    cx.notify();
  }

  async restoreHistoryItem(item, cx) {
    const hv = this.historyView;
    const slug = projectSlug(this.pm());
    if (!hv || !slug || !item || hv.restoring) return;
    hv.restoring = `${item.root}/${item.path}@${item.version}`;
    hv.error = '';
    cx.notify();
    try {
      const r = await this.runProjectWrite(projectRestoreArgv(slug, item.root, item.path, { version: item.version }));
      if (r.code !== 0) throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
      const key = `${item.root}/${item.path}`;
      this.docCache.delete(key);
      this.docFailed.delete(key);
      if (this.historyView === hv) this.historyView = null;
      if (hv.tab === 'memory') this.readMemory(cx);
      else this.readLibrary(cx);
      if (this.activeDoc && `${this.activeDoc.root}/${this.activeDoc.path}` === key) {
        this.readDoc(item.root, item.path, cx, { force: true });
      }
    } catch (e) {
      if (this.historyView === hv) {
        hv.error = word(this.lang, 'restoreFailed', String(e?.message || e).trim());
        hv.restoring = '';
      }
    }
    cx.notify();
  }

  async handleCandidate(cand, drop, cx) {
    const pm = this.pm();
    const slug = projectSlug(pm);
    const repo = pm?.repo || (this.ledgerHome && slug ? `${this.ledgerHome}/projects/${slug}` : '');
    if (!repo || !cand || this.memoryBusy) return;
    this.memoryBusy = cand.path;
    this.memoryNoticeError = '';
    cx.notify();
    try {
      const target = `${cand.worker}/${cand.name}`;
      const r = await this.runProjectWrite(adoptCandidateArgv(repo, target, { drop }));
      if (r.code !== 0) throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
      this.readMemory(cx);
    } catch (e) {
      this.memoryNoticeError = String(e?.message || e).trim();
    } finally {
      this.memoryBusy = '';
      cx.notify();
    }
  }

  pickLibraryFiles(cx) {
    cx.spawn(async cx => {
      try {
        const r = await exec('osascript', ['-e', CHOOSE_FILES], { timeout: 600000 });
        if (r.code !== 0) {
          if (/-128/.test(r.stderr)) return;
          throw new Error((r.stderr || r.stdout).trim() || `osascript: ${r.code}`);
        }
        await this.dropLibraryFiles(pickedPaths(r.stdout), cx);
      } catch (e) {
        this.libraryDropError = String(e?.message || e).trim();
        cx.notify();
      }
    });
  }

  uniqueDocName(baseName) {
    const taken = new Set((this.libraryFiles || []).filter(f => f.root === 'docs').map(f => f.path.toLowerCase()));
    if (!taken.has(baseName.toLowerCase())) return baseName;
    const dot = baseName.lastIndexOf('.');
    const stem = dot > 0 ? baseName.slice(0, dot) : baseName;
    const ext = dot > 0 ? baseName.slice(dot) : '';
    let n = 2;
    while (taken.has(`${stem}-${n}${ext}`.toLowerCase())) n++;
    return `${stem}-${n}${ext}`;
  }

  async dropLibraryFiles(paths, cx) {
    const slug = projectSlug(this.pm());
    if (!slug) return;
    const list = withFiles([], paths);
    const rejected = notFiles(paths);
    if (rejected.length) {
      this.libraryDropError = word(this.lang, 'notAFile', rejected.map(p => fileName(String(p))).join(', '));
    } else {
      this.libraryDropError = '';
    }
    if (!list.length) { cx.notify(); return; }
    for (const p of list) {
      const name = fileName(p);
      this.libraryDropBusy = name;
      cx.notify();
      try {
        if (this.machine) {
          const ext = name.includes('.') ? name.split('.').pop().toLowerCase() : '';
          if (!LIBRARY_DROP_TEXT_EXT.has(ext)) {
            throw new Error(word(this.lang, 'remoteDropTextOnly', this.machine));
          }
          const text = await readTextFile(p);
          if (text == null || text.includes('\0') || new TextEncoder().encode(text).length > DOC_MAX_BYTES) {
            throw new Error(word(this.lang, 'remoteDropTextOnly', this.machine));
          }
          const dest = this.uniqueDocName(name);
          const r = await this.saveProjectText(slug, 'docs', dest, text, { ifVersion: 'new' });
          if (r.code !== 0) throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        } else {
          const r = await this.runProjectWrite(projectAddArgv(slug, p));
          if (r.code !== 0) throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
      } catch (e) {
        this.libraryDropError = word(this.lang, 'addFileFailed', name, String(e?.message || e).trim());
      }
    }
    this.libraryDropBusy = '';
    this.readLibrary(cx);
    cx.notify();
  }

  async dropMemoryFiles(paths, cx) {
    const slug = projectSlug(this.pm());
    if (!slug) return;
    const list = withFiles([], paths);
    const rejected = notFiles(paths);
    this.memoryNoticeError = rejected.length
      ? word(this.lang, 'notAFile', rejected.map(p => fileName(String(p))).join(', '))
      : '';
    if (!list.length) { cx.notify(); return; }
    const taken = new Set(
      (this.memoryData?.files || [])
        .filter(f => f.root === 'memory' || f.layer === 'project')
        .map(f => String(f.name || fileName(f.path).replace(/\.md$/i, '')).toLowerCase()),
    );
    for (const p of list) {
      const name = fileName(p);
      if (!/\.(md|markdown|txt|text)$/i.test(name)) {
        this.memoryNoticeError = word(this.lang, 'memoryDropMdOnly');
        continue;
      }
      this.memoryBusy = name;
      cx.notify();
      try {
        const raw = await readTextFile(p);
        if (raw == null || raw.includes('\0')) throw new Error(word(this.lang, 'docNotText'));
        const baseSlug = memoryFromDroppedFile(name, raw).slug;
        let chosenSlug = baseSlug;
        let r = null;
        for (let attempt = 0; attempt < 20; attempt++) {
          chosenSlug = uniqueMemorySlug(baseSlug, taken);
          const built = memoryFromDroppedFile(name, raw, { slug: chosenSlug });
          r = await this.saveProjectText(slug, 'memory', `${chosenSlug}.md`, built.text, { ifVersion: 'new' });
          if (parseVersionConflict(r)) {
            taken.add(chosenSlug.toLowerCase());
            continue;
          }
          break;
        }
        if (!r || r.code !== 0) throw new Error((r?.stderr || r?.stdout || `pm.py: ${r?.code}`).trim().split('\n').pop());
        taken.add(chosenSlug.toLowerCase());
      } catch (e) {
        this.memoryNoticeError = word(this.lang, 'addFileFailed', name, String(e?.message || e).trim());
      }
    }
    this.memoryBusy = '';
    this.readMemory(cx);
    cx.notify();
  }

  pm() {
    if (this.stateFor !== this.machine) return null;
    const name = projectRef({ pm: this.pmName, machine: this.machine }).name;
    return this.state.pms.find(p => p.name === name) || null;
  }
  // exec/readTextFile's options for the project's machine; {} here.
  where() { return this.machine ? { on: this.machine } : {}; }
  // The terminals and agents as the project's machine sees them (machineView).
  terms() {
    if (this._renderTerms && this._renderTermsMachine === this.machine) return this._renderTerms;
    return machineView(terminals(), this.machine);
  }
  live() {
    if (this._renderLive && this._renderLiveMachine === this.machine) return this._renderLive;
    return machineView(agents(), this.machine);
  }
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
  runPmCommand(args, { timeout = 150000 } = {}) {
    if (this.machine) return exec(...remotePmArgv(args), { on: this.machine, timeout });
    if (this.hostPlatform() === 'windows') return execPython(exec, [appHome() + PM_SCRIPT, ...args], { timeout });
    const argv = args[0] === 'reattach' && args.length === 2
      ? reattachArgv(appHome() + PM_SCRIPT, args[1])
      : ['python3', appHome() + PM_SCRIPT, ...args];
    return exec(...withoutTerminalEnv(argv, { platform: this.hostPlatform(), unset: REATTACH_ENV }), { timeout });
  }
  // The reattach icon: pm.py brings the thread's agent back (its session resumed, or a new agent given
  // the thread's context) in a terminal under the PM, and the ledger then names that terminal.
  reattach(cx) {
    const id = this.thread;
    if (!id || this.reattaching || this.bringingBack) return;
    this.reattaching = id; this.reattachError = null;
    cx.spawn(async cx => {
      try {
        const r = await this.runPmCommand(['reattach', id]);
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
  // Start a fresh PM session for the current offline project (`pm.py start --repo <repo>`).
  startPm(cx) {
    const pm = this.pm(), pmKey = this.pmName;
    if (!pm || !pm.repo || this.startingPm || this.bringingBack) return;
    const stayOnProject = findStage(layout())?.active === 'pm-project';
    this.startingPm = pmKey;
    this.startPmError = null;
    cx.spawn(async cx => {
      try {
        const argv = this.machine || this.hostPlatform() === 'windows'
          ? startPmArgs(pm)
          : startPmArgv(appHome() + PM_SCRIPT, pm).slice(2);
        const r = await this.runPmCommand(argv);
        if (r.code !== 0) throw new Error(String(r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        if (stayOnProject && this.pmName === pmKey && findStage(layout())) {
          run('layout.select', { stack: STAGE, child: 'pm-project' });
        }
      } catch (e) {
        this.startPmError = { pm: pmKey, text: String(e?.message || e) };
      } finally {
        if (this.startingPm === pmKey) this.startingPm = '';
        this.refresh(cx);
        cx.notify();
      }
    });
    cx.notify();
  }
  lostStorageKey(pmKey = this.pmName) {
    return pmKey ? `lostSeen:${pmKey}` : '';
  }
  keptDismissedLost(pmKey = this.pmName) {
    const key = this.lostStorageKey(pmKey);
    if (!key) return '';
    try { return String(localStorage.getItem(key) || ''); } catch (_) { return ''; }
  }
  dismissLost(pm, cx) {
    const key = this.lostStorageKey(this.pmName), lostKey = pm?.lost?.key || '';
    if (key && lostKey) {
      const merged = mergeDismissedLost(this.keptDismissedLost(this.pmName), lostKey);
      try { localStorage.setItem(key, merged); } catch (_) { /* Ephemeral when storage is unavailable. */ }
    }
    this.bringBackOpen = false;
    this.bringBackProgress = null;
    cx.notify();
  }
  openBringBack(pm, cx) {
    if (!pm?.lost) return;
    const steps = bringBackSteps(this.lang, pm.lost, pm.project || pm.name).map(s => ({ ...s, state: 'pending', error: '' }));
    if (!steps.length) return;
    this.bringBackOpen = true;
    this.bringBackProgress = { pmKey: this.pmName, key: String(pm.lost.key || ''), steps };
    cx.notify();
  }
  closeBringBack(cx) {
    if (this.bringingBack) return;
    this.bringBackOpen = false;
    this.bringBackProgress = null;
    cx.notify();
  }
  runBringBack(cx) {
    const pm = this.pm(), pmKey = this.pmName;
    if (!pm || this.bringingBack || this.startingPm) return;
    let progress = this.bringBackProgress && this.bringBackProgress.pmKey === pmKey ? this.bringBackProgress : null;
    if (!progress || !progress.steps?.length) {
      const steps = bringBackSteps(this.lang, pm.lost, pm.project || pm.name).map(s => ({ ...s, state: 'pending', error: '' }));
      if (!steps.length) return;
      progress = { pmKey, key: String(pm.lost?.key || ''), steps };
      this.bringBackProgress = progress;
    } else {
      for (const s of progress.steps) {
        if (s.state === 'failed') { s.state = 'pending'; s.error = ''; }
      }
    }
    const stayOnProject = findStage(layout())?.active === 'pm-project';
    this.bringingBack = true;
    this.bringBackOpen = true;
    this.startPmError = null;
    cx.spawn(async cx => {
      try {
        for (const step of progress.steps) {
          if (step.state === 'done') continue;
          step.state = 'running';
          step.error = '';
          cx.notify();
          if (step.kind === 'pm') {
            if (this.pmName === pmKey && this.pmTerminal()) {
              step.state = 'done';
              continue;
            }
            const r = await this.runPmCommand(startPmArgs(pm));
            const out = `${r.stderr || ''}\n${r.stdout || ''}`;
            if (r.code !== 0 && !/already exists/i.test(out)) {
              step.state = 'failed';
              step.error = String(r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop();
              break;
            }
            step.state = 'done';
            if (stayOnProject && this.pmName === pmKey && findStage(layout())) {
              run('layout.select', { stack: STAGE, child: 'pm-project' });
            }
          } else {
            const r = await this.runPmCommand(['reattach', step.id]);
            const out = `${r.stderr || ''}\n${r.stdout || ''}`;
            if (r.code !== 0 && !/is not offline/i.test(out)) {
              step.state = 'failed';
              step.error = String(r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop();
            } else {
              step.state = 'done';
            }
          }
          cx.notify();
        }
      } catch (e) {
        const cur = progress.steps.find(s => s.state === 'running');
        if (cur) { cur.state = 'failed'; cur.error = String(e?.message || e); }
      } finally {
        this.bringingBack = false;
        this.refresh(cx);
        if (progress.steps.every(s => s.state === 'done')) {
          cx.timer?.after(600, cx => {
            if (!this.bringingBack && this.bringBackProgress === progress) {
              this.bringBackOpen = false;
              this.bringBackProgress = null;
              cx.notify();
            }
          });
        }
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
  keep(key, text, files, tokens = undefined, quotes = undefined) {
    const stored = this.drafts();
    this.store(stored, keepDraft(stored, key, text, Date.now(), files, tokens, quotes));
  }
  store(stored, next) {
    if (next === stored) return;
    try { localStorage.setItem('drafts', JSON.stringify(next)); } catch (_) { /* Nowhere to keep it. */ }
  }
  // What a box holds is its draft. A box emptied while its words are on their way is not: that
  // draft stays until the send has worked.
  typed(key, text, tokens = undefined) {
    if (!text.trim() && this.outgoing.get(key)) return;
    this.keep(key, text, undefined, tokens);
  }
  boxContent(box) {
    if (!box) return { text: '', tokens: [] };
    if (typeof box.content === 'function') {
      const c = box.content();
      if (c && typeof c.text === 'string') return { text: c.text, tokens: Array.isArray(c.tokens) ? c.tokens : [] };
    }
    return { text: String(box.value?.() ?? ''), tokens: [] };
  }
  // Around a send of a box's words: the draft goes only once they went out, and only if it still
  // is those words. Words that did not go out stay the draft, or are it again when the box's draft
  // is empty (nothing newer was typed there).
  leaving(key) {
    if (key) this.outgoing.set(key, (this.outgoing.get(key) || 0) + 1);
  }
  // sent: {text, files, quotes?}, what went out of the box.
  landed(key, sent, ok) {
    if (!key) return;
    this.outgoing.set(key, Math.max(0, (this.outgoing.get(key) || 0) - 1));
    this.settleDraft(key, sent, ok);
  }
  // The draft after words of it went (ok) or came back (!ok); see afterSend.
  settleDraft(key, sent, ok) {
    if (!key) return;
    const drafts = this.drafts();
    const next = afterSend(
      { text: draftText(drafts, key), files: draftFiles(drafts, key), quotes: draftQuotes(drafts, key) },
      sent,
      ok,
    );
    if (next) this.keep(key, next.text, next.files, undefined, next.quotes ?? []);
  }
  // Text into a box, with optional inline tokens, cursor after it and nothing selected.
  fill(box, text, tokens = []) {
    const valid = validInputTokens(text, tokens);
    if (valid.length && typeof box.content === 'function') {
      try { box.set_value({ text, tokens: valid }); }
      catch (_) { box.set_value(text); }
    } else {
      box.set_value(text);
    }
    box.set_selected_range({ start: text.length, end: text.length });
  }
  // The project's box takes the draft kept for the project that shows now; no thread is open.
  showMainDraft() {
    this.mainKey = draftKey('pm', this.pmName);
    const drafts = this.drafts();
    this.draft = draftText(drafts, this.mainKey);
    this.files = draftFiles(drafts, this.mainKey);
    this.quotes = draftQuotes(drafts, this.mainKey);
    this.fill(this.input, this.draft, draftTokens(drafts, this.mainKey));
    this.showThreadDraft('');
  }
  showThreadDraft(id) {
    this.threadKey = draftKey('thread', id && onMachine(id, this.machine));
    const drafts = this.drafts();
    this.threadDraft = draftText(drafts, this.threadKey);
    this.threadFiles = draftFiles(drafts, this.threadKey);
    this.fill(this.threadInput, this.threadDraft, draftTokens(drafts, this.threadKey));
  }

  // ---- @ mentions: lazy sources, menu controller, token insertion & click navigation ----
  readRepoFiles(cx) {
    const pm = this.pm(), slug = projectSlug(pm), repo = pm?.repo || '', machine = this.machine;
    if (slug !== this.repoFilesSlug || repo !== this.repoFilesRepo) {
      this.repoFilesSlug = slug;
      this.repoFilesRepo = repo;
      this.repoFiles = [];
      this.repoFilesRead = false;
      this.repoFilesError = '';
      this.repoFilesTruncated = false;
      this.repoFilesAt = 0;
    }
    if (!pm || !slug) return;
    if (this.repoFilesLoading) { this.repoFilesAgain = true; return; }
    this.repoFilesLoading = true;
    cx.spawn(async cx => {
      try {
        let paths = [];
        let truncated = false;
        if (!machine && repo) {
          const r = await exec('git', ['-C', repo, 'ls-files', '-z'], { timeout: 10000 });
          if (r.code === 0) {
            const parsed = parseGitLsFiles(r.stdout);
            truncated = parsed.length > REPO_FILES_LIMIT;
            paths = parsed.slice(0, REPO_FILES_LIMIT);
          } else {
            const pr = await this.runProject(projectFilesArgv(slug));
            if (pr.code !== 0) throw new Error((pr.stderr || pr.stdout || r.stderr || `files: ${pr.code}`).trim().split('\n').pop());
            const got = JSON.parse(pr.stdout || '{}');
            paths = Array.isArray(got.files) ? got.files : [];
            truncated = Boolean(got.truncated);
          }
        } else {
          const pr = await this.runProject(projectFilesArgv(slug));
          if (pr.code === 0) {
            const got = JSON.parse(pr.stdout || '{}');
            paths = Array.isArray(got.files) ? got.files : [];
            truncated = Boolean(got.truncated);
          } else if (machine && isOldPmCommand(pr) && repo) {
            const r = await exec('git', ['-C', repo, 'ls-files', '-z'], { on: machine, timeout: 15000 });
            if (r.code !== 0) throw new Error((r.stderr || r.stdout || `git: ${r.code}`).trim().split('\n').pop());
            const parsed = parseGitLsFiles(r.stdout);
            truncated = parsed.length > REPO_FILES_LIMIT;
            paths = parsed.slice(0, REPO_FILES_LIMIT);
          } else {
            throw new Error((pr.stderr || pr.stdout || `pm.py: ${pr.code}`).trim().split('\n').pop());
          }
        }
        if (projectSlug(this.pm()) === slug && (this.pm()?.repo || '') === repo && machine === this.machine) {
          this.repoFiles = indexRepoFiles(paths);
          this.repoFilesTruncated = truncated;
          this.repoFilesRead = true;
          this.repoFilesError = '';
          this.repoFilesAt = Date.now();
        }
      } catch (e) {
        if (projectSlug(this.pm()) === slug && machine === this.machine) {
          this.repoFilesError = String(e?.message || e).trim();
        }
      } finally {
        this.repoFilesLoading = false;
        cx.notify();
        if (this.repoFilesAgain) { this.repoFilesAgain = false; this.readRepoFiles(cx); }
      }
    });
  }

  ensureMentionSources(cx) {
    if (!this.libraryRead && !this.libraryLoading && this.librarySupported()) {
      this.readLibrary(cx);
    }
    const staleFiles = !this.repoFilesRead || (this.repoFilesAt && Date.now() - this.repoFilesAt > 30_000);
    if (!this.repoFilesLoading && staleFiles) {
      this.readRepoFiles(cx);
    }
  }

  mentionBox(which) {
    return which === 'thread' ? this.threadInput : this.input;
  }

  mentionOpenFor(which) {
    return Boolean(this.mention && this.mention.which === which && this.typing === which);
  }

  consumeMentionKey(cx) {
    this.mentionConsumedKey = true;
    Promise.resolve().then(() => { this.mentionConsumedKey = false; });
    cx?.timer?.after?.(0, () => { this.mentionConsumedKey = false; });
  }

  syncMention(which, cx) {
    const box = this.mentionBox(which);
    if (!box) return false;
    const content = this.boxContent(box);
    const sel = typeof box.selected_range === 'function'
      ? box.selected_range()
      : { start: content.text.length, end: content.text.length };
    if (!sel || sel.start !== sel.end) {
      const had = this.mention?.which === which;
      if (had) this.mention = null;
      return had;
    }
    const dismissedAt = this.mentionDismissed?.which === which ? this.mentionDismissed.atPos : null;
    const trigger = detectMentionQuery(content.text, sel.start, content.tokens, dismissedAt);
    if (!trigger) {
      if (this.mentionDismissed?.which === which) {
        const stillSameAt = detectMentionQuery(content.text, sel.start, content.tokens, null);
        if (!stillSameAt || stillSameAt.start !== this.mentionDismissed.atPos) this.mentionDismissed = null;
      }
      const had = this.mention?.which === which;
      if (had) this.mention = null;
      return had;
    }
    const sameAnchor = this.mention?.which === which && this.mention.start === trigger.start;
    const category = sameAnchor ? this.mention.category : 'all';
    const queryChanged = !sameAnchor || this.mention.query !== trigger.query;
    this.mention = {
      which,
      start: trigger.start,
      end: trigger.end,
      query: trigger.query,
      category,
      index: queryChanged ? 0 : (this.mention?.index || 0),
      key: queryChanged ? '' : (this.mention?.key || ''),
    };
    this.ensureMentionSources(cx);
    return true;
  }

  mentionMenuFor(which) {
    if (!this.mention || this.mention.which !== which) return null;
    const pm = this.pm();
    const threads = pm ? threadList(pm, this.tasks || this.state.tasks, this.events, this.terms(), this.live(), spaces().flatMap(s => s.tabs || []), this.lang) : { open: [], sessions: [], finished: [] };
    const menu = buildMentionMenu({
      lang: this.lang,
      category: this.mention.category,
      query: this.mention.query,
      threads,
      tasks: this.tasks || this.state.tasks,
      taskNumbers: this.state.task_numbers,
      libraryFiles: this.libraryFiles,
      repoFiles: this.repoFiles,
      excludeThread: which === 'thread' ? this.thread : '',
      filesLoading: this.repoFilesLoading,
      filesError: this.repoFilesError,
      libraryLoading: this.libraryLoading,
      libraryError: this.libraryError,
    });
    let index = 0;
    if (menu.items.length) {
      if (this.mention.key) {
        const found = menu.items.findIndex(it => it.key === this.mention.key);
        index = found >= 0 ? found : Math.min(this.mention.index || 0, menu.items.length - 1);
      } else {
        index = Math.max(0, Math.min(this.mention.index || 0, menu.items.length - 1));
      }
    }
    return { ...menu, index };
  }

  moveMention(which, delta, cx) {
    const menu = this.mentionMenuFor(which);
    if (!menu || !menu.items.length) return;
    const n = menu.items.length;
    const next = ((menu.index + delta) % n + n) % n;
    this.mention = { ...this.mention, index: next, key: menu.items[next].key };
    const scrollIdx = menu.dividerBefore >= 0 && next >= menu.dividerBefore ? next + 1 : next;
    this.mentionScroll?.scroll_to_item?.(scrollIdx);
    cx.notify();
  }

  acceptMention(which, cx) {
    const menu = this.mentionMenuFor(which);
    if (!menu || !menu.items.length) return;
    const row = menu.items[menu.index];
    if (row) this.pickMention(which, row, cx);
  }

  escapeMention(which, cx) {
    if (!this.mention || this.mention.which !== which) return false;
    if (this.mention.category !== 'all') {
      this.mention = { ...this.mention, category: 'all', index: 0, key: '' };
      this.mentionScroll?.scroll_to_item?.(0);
    } else {
      this.mentionDismissed = { which, atPos: this.mention.start };
      this.mention = null;
    }
    cx.notify();
    return true;
  }

  pickMention(which, row, cx) {
    const box = this.mentionBox(which);
    if (!box || !row) return;
    this.mentionPicking = true;
    Promise.resolve().then(() => { this.mentionPicking = false; });
    cx?.timer?.after?.(0, () => { this.mentionPicking = false; });
    if (row.rowKind === 'category') {
      const m = this.mention;
      this.mention = {
        which,
        start: m?.start ?? 0,
        end: (m?.start ?? 0) + 1,
        query: '',
        category: row.category,
        index: 0,
        key: '',
      };
      if (m && m.end > m.start + 1 && typeof box.set_selected_range === 'function' && typeof box.replace === 'function') {
        box.set_selected_range({ start: m.start + 1, end: m.end });
        box.replace('');
      }
      this.ensureMentionSources(cx);
      box.focus?.();
      cx.notify();
      return;
    }
    const content = this.boxContent(box);
    const sel = typeof box.selected_range === 'function'
      ? box.selected_range()
      : { start: content.text.length, end: content.text.length };
    const liveTrigger = detectMentionQuery(content.text, sel.start, content.tokens, null);
    const range = liveTrigger
      ? { start: liveTrigger.start, end: liveTrigger.end }
      : (this.mention ? { start: this.mention.start, end: this.mention.end } : null);
    if (!range) return;
    this.mention = null;
    this.mentionDismissed = null;
    if (typeof box.replace_range_with_token === 'function') {
      box.replace_range_with_token(range, row.token);
      const after = this.boxContent(box);
      const pos = typeof box.selected_range === 'function' ? box.selected_range().end : range.start + row.token.text.length;
      const nextChar = after.text[pos];
      if (!nextChar || !/\s/.test(nextChar)) {
        box.replace?.(' ');
      }
    } else {
      const before = content.text.slice(0, range.start);
      const after = content.text.slice(range.end);
      const pad = !after || !/\s/.test(after[0]) ? ' ' : '';
      box.set_value(`${before}${row.token.text}${pad}${after}`);
    }
    const updated = this.boxContent(box);
    if (which === 'thread') {
      this.threadDraft = updated.text;
      this.typed(this.threadKey, updated.text, updated.tokens);
    } else {
      this.draft = updated.text;
      this.typed(this.mainKey, updated.text, updated.tokens);
    }
    box.focus?.();
    cx.notify();
  }

  openMentionRef(targetOrToken, cx) {
    let ref = null;
    if (targetOrToken && typeof targetOrToken === 'object') {
      if (targetOrToken.kind && targetOrToken.target) {
        ref = targetOrToken;
      } else {
        if (typeof targetOrToken.text === 'string') {
          ref = parseMentionSpans(targetOrToken.text)[0] || null;
        }
        if (!ref && typeof targetOrToken.id === 'string') {
          ref = parseRefLink(targetOrToken.id);
        }
      }
    } else if (typeof targetOrToken === 'string') {
      ref = parseRefLink(targetOrToken);
    }
    if (!ref) return false;
    if (ref.kind === 'thread') {
      const id = resolveThreadRef(this.projectTasks(), ref.target, this.state.task_numbers, {
        retiredParts: this.state.retired_parts, events: this.events,
      });
      if (id && !(this.detail && this.thread === id)) this.openThread(id, cx);
      else if (id && !this.listResting()) { this.listShown = true; cx.notify(); }
      return true;
    }
    if (ref.kind === 'session') {
      this.focusTerminal(ref.target);
      return true;
    }
    if (ref.kind === 'library') {
      if (!this.listResting()) this.listShown = true;
      this.detail = false;
      this.resetThreadChange();
      this.openDoc({ root: ref.root, path: ref.path }, cx);
      return true;
    }
    if (ref.kind === 'file') {
      this.openRepoFile(ref.path || ref.target, cx);
      return true;
    }
    return false;
  }

  openRepoFile(relPath, cx) {
    if (!relPath) return;
    if (!this.listResting()) this.listShown = true;
    this.detail = false;
    this.resetThreadChange();
    this.openDoc({ tab: 'library', root: 'repo', path: relPath }, cx);
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
  // Project composer delivery: uploads remote attachments first, then sends via idempotent
  // `pm.py project send <slug> --msg-id <id>` (atomically logging to conversation.jsonl on the host),
  // falling back transparently to `this.send` if a remote peer runs an older `pm.py`.
  async deliverProject(address, words, files, { msgId = '', question = '', slug = '' } = {}) {
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
    const peerKey = this.machine || '__local__';
    let sendReply = null;
    const inlineOk = msgId && slug && this.noProjectSendFor !== peerKey && chunkUtf8Text(message, SAVE_INLINE_BYTES).length <= 1;
    if (inlineOk) {
      const r = await this.runProjectWrite(
        projectSendArgv(slug, { msgId, target: onMachine(address, this.machine), text: message, question }),
        { timeout: 45000 },
      );
      if (r.code !== 0) {
        if (isOldPmCommand(r)) {
          this.noProjectSendFor = peerKey;
          await this.send(address, message);
        } else {
          throw new Error((r.stderr || r.stdout).trim() || `pm.py project send: ${r.code}`);
        }
      } else {
        const outStr = String(r.stdout || '').trim();
        if (outStr.startsWith('{')) {
          try { sendReply = JSON.parse(outStr); } catch (_) { sendReply = null; }
        }
        if (sendReply && sendReply.status === 'queued') {
          throw new Error(sendReply.reason || 'pm is blocked');
        }
      }
    } else {
      await this.send(address, message);
    }
    for (const step of steps) uploaded.delete(step.key);
    return { message, reply: sendReply };
  }
  activePmTurn() {
    const pm = this.pm();
    return this.logTurn || (pm?.turn && typeof pm.turn === 'object' ? pm.turn : null);
  }
  interruptPm(cx) {
    const pm = this.pm(), slug = projectSlug(pm), pmKey = this.pmName;
    if (!pm || !slug || this.interruptingPm === pmKey) return;
    this.interruptingPm = pmKey;
    this.notifySafe(cx);
    cx.spawn(async cx => {
      try {
        await this.runProjectWrite(projectInterruptArgv(slug), { timeout: 15000 });
      } catch (_) { /* Best-effort interrupt; user can still open terminal or rotate. */ }
      finally {
        if (this.interruptingPm === pmKey) this.interruptingPm = '';
        this.refresh(cx);
        this.notifySafe(cx);
      }
    });
  }
  rotatePmFromStall(cx) {
    const pm = this.pm(), repo = pm?.repo || '', pmKey = this.pmName;
    if (!pm || !repo || this.rotatingPm === pmKey) return;
    this.rotatingPm = pmKey;
    this.notifySafe(cx);
    cx.spawn(async cx => {
      try {
        const reason = this.lang === 'zh' ? '从无响应轮次恢复' : 'Recover from unresponsive turn';
        await this.runProjectWrite(rotatePmArgs(repo, reason), { timeout: 30000 });
      } catch (_) { /* Rotation errors show on next refresh if offline. */ }
      finally {
        if (this.rotatingPm === pmKey) this.rotatingPm = '';
        this.refresh(cx);
        this.notifySafe(cx);
      }
    });
  }
  // The project box's unsettled sends in localStorage, keyed by PM name (survives mod reload / app
  // restart; see QUEUE_KEY for what is kept of each).
  queuedStore() {
    try { return readQueuedSends(localStorage.getItem(QUEUE_KEY)); } catch (_) { return {}; }
  }
  saveQueue(pmName, list) {
    if (!pmName) return;
    const stored = this.queuedStore();
    const next = keepQueuedSends(stored, pmName, list);
    if (next === stored) return;
    try {
      if (Object.keys(next).length) localStorage.setItem(QUEUE_KEY, JSON.stringify(next));
      else localStorage.removeItem(QUEUE_KEY);
    } catch (_) { /* Storage unavailable. */ }
  }
  hydrateQueue(pmName) {
    if (!pmName) return [];
    const byPm = this.pendingByPm ||= new Map();
    const saved = this.queuedStore()[pmName] || [];
    const { pending, maxId } = restoreQueuedPending(saved, byPm.get(pmName) || [], this.nowMs());
    if (maxId > (this.seq || 0)) this.seq = maxId;
    byPm.set(pmName, pending);
    return pending;
  }
  // Probe the PM terminal's active screen (read-only) when it is blocked or a send was queued so the
  // UI can explain which dialog is holding up delivery. Throttled while the PM remains blocked.
  probePmDialog(cx, force = false) {
    const pmTerm = this.pmTerminal(), pmName = this.pmName;
    if (!pmTerm?.address || !pmName || this.pmDialogLoading) return;
    const now = Date.now();
    if (!force && this.pmDialog?.pm === pmName && this.pmDialog?.address === pmTerm.address && now - this.pmDialogAt < 2500) return;
    this.pmDialogLoading = true;
    this.pmDialogAt = now;
    const target = onMachine(pmTerm.address, this.machine);
    cx.spawn(async cx => {
      try {
        const r = await exec(...withoutTerminalEnv(readScreenArgv(target), {
          platform: this.hostPlatform(), unset: SEND_ENV,
        }), { timeout: 6000 });
        if (this.pmName !== pmName) return;
        const screen = r.code === 0 ? String(r.stdout || '') : '';
        const status = pmLiveStatus(this.pmTerminal(), this.live());
        const dialog = classifyPmDialog(screen, this.pmSendBlockError, status);
        this.pmDialog = { pm: pmName, address: pmTerm.address, screen, dialog };
      } catch (_) {
        if (this.pmName === pmName) {
          const status = pmLiveStatus(this.pmTerminal(), this.live());
          this.pmDialog = { pm: pmName, address: pmTerm.address, screen: '', dialog: classifyPmDialog('', this.pmSendBlockError, status) };
        }
      } finally {
        this.pmDialogLoading = false;
        this.notifySafe(cx);
      }
    });
  }
  nowMs() {
    return typeof this._now === 'function' ? this._now() : Date.now();
  }
  // When the newest finished read of the shown project's own log began (0: none yet): what a resend
  // being checked waits on (reconcilePendingSends' logFreshFrom).
  freshLogFrom() {
    const pm = this.pm();
    const log = logKey(this.machine, pm?.conversation || '', projectSlug(pm));
    return this.logFresh?.log === log ? this.logFresh.from : 0;
  }
  notifySafe(cx) {
    if (cx?.notify && cx?.phase?.() !== 'render') cx.notify();
  }
  isPmStarting() {
    return this.startingPm === this.pmName || Boolean(
      this.bringingBack &&
      this.bringBackProgress?.pmKey === this.pmName &&
      this.bringBackProgress.steps?.some(s => s.kind === 'pm' && s.state === 'running'),
    );
  }
  // Recent PM user-message receipts from both `pm.py state` and `pm.py project events`.
  pmReceipts() {
    const fromLog = Array.isArray(this.logReceipts) ? this.logReceipts : [];
    const fromState = Array.isArray(this.pm()?.receipts) ? this.pm().receipts : [];
    if (!fromLog.length) return fromState;
    if (!fromState.length) return fromLog;
    return mergeReceipts(fromState, fromLog);
  }
  reconcilePending(cx, { fromReadLog = false, forceLogReady = false } = {}) {
    if (!Array.isArray(this.pending) || !this.pending.length) return;
    const now = this.nowMs();
    const pmTerm = this.pmTerminal();
    const pmAddress = pmTerm?.address || '';
    const pmSession = pmSessionKey(pmTerm, this.pm());
    const pmWorking = this.isPmWorking(pmTerm, this.live(), this.activePmTurn());
    const logReady = Boolean(forceLogReady || fromReadLog || (!this.logLoading && !this.logError && this.lastLogReadAt > 0));
    const res = reconcilePendingSends(this.pending, this.events, {
      now,
      pmAddress,
      pmSession,
      pmWorking,
      pmStarting: this.isPmStarting(),
      flushingQueue: Boolean(this.flushingQueue),
      logReady,
      remote: Boolean(this.machine),
      lang: this.lang,
      logFreshFrom: this.freshLogFrom(),
      receipts: this.pmReceipts(),
      clockOffsetMs: this.clockOffsetMs || 0,
    });
    const changed = res.pending !== this.pending;
    if (changed) {
      this.pending = res.pending;
      if (this.pmName) {
        (this.pendingByPm ||= new Map()).set(this.pmName, this.pending);
        this.saveQueue(this.pmName, this.pending);
      }
    }
    for (const s of res.settled) {
      if (s.timedOut && s.draftKey) {
        this.landed(s.draftKey, { text: s.words, files: s.files, quotes: s.quotes || [] }, true);
      }
      this.cleanSent(s.files, s.id);
    }
    for (const c of res.confirmed || []) {
      if ((c.wasTimedOut || c.wasFailed) && c.draftKey) {
        this.landed(c.draftKey, { text: c.words, files: c.files, quotes: c.quotes || [] }, true);
      }
      this.cleanSent(c.files, c.id);
    }
    for (const f of res.failed) {
      if (f.draftKey) {
        const drafts = this.drafts();
        const restored = afterSend(
          { text: draftText(drafts, f.draftKey), files: draftFiles(drafts, f.draftKey), quotes: draftQuotes(drafts, f.draftKey) },
          { text: f.words ?? '', files: f.files || [], quotes: f.quotes || [] },
          false,
        );
        if (restored) this.keep(f.draftKey, restored.text, restored.files, undefined, restored.quotes ?? []);
      }
    }
    if (res.requeued.length > 0 && cx) {
      if (pmTerm && pmCanReceive(pmLiveStatus(pmTerm, this.live()))) this.flushQueue(cx);
      else this.scheduleQueueFlush(cx);
    }
    if (res.needsFollowup && cx) this.scheduleConfirmCheck(cx);
    if (changed && !fromReadLog) this.notifySafe(cx);
  }
  scheduleConfirmCheck(cx) {
    if (!cx?.timer?.after || this.confirmTimer) return;
    const needsWatch = (this.pending || []).some(p =>
      p && !p.failed && !p.received && (p.verifying || (!p.queued && (p.deliveredAt > 0 || p.inFlight)) || (p.queued && p.swapWaitSince > 0)));
    if (!needsWatch) return;
    const delay = 1500;
    const scheduledAt = this.nowMs();
    this.confirmTimer = true;
    cx.timer.after(delay, cx => {
      this.confirmTimer = false;
      const now = this.nowMs();
      if (now - scheduledAt < Math.min(200, delay)) return;
      const pmTerm = this.pmTerminal();
      const pmAddress = pmTerm?.address || '';
      const pmSession = pmSessionKey(pmTerm, this.pm());
      const pmWorking = this.isPmWorking(pmTerm, this.live(), this.activePmTurn());
      const probes = (this.confirmLogProbes ||= new Set());
      let wantFreshLog = false;
      for (const p of this.pending || []) {
        // A resend waits on a log read begun after it was asked for.
        // Past RESEND_VERIFY_WAIT_MS it waits no more (a log that cannot be read): reconcile resends.
        if (p?.verifying && !p.failed) {
          const since = Number(p.verifySince) || 0;
          if (this.freshLogFrom() < since && now - since < RESEND_VERIFY_WAIT_MS) wantFreshLog = true;
          continue;
        }
        if (!p || p.failed || p.queued || p.inFlight || !(p.deliveredAt > 0)) continue;
        const swapped = Boolean(
          (p.sentTo && pmAddress !== p.sentTo) ||
          (p.sentSession && pmSession && p.sentSession !== pmSession),
        );
        const idleLimit = this.machine ? 20000 : 12000;
        const idleRef = Number(p.idleSince) || 0;
        const due = swapped || (!pmWorking && idleRef > 0 && now - idleRef >= idleLimit);
        if (due) {
          const probeKey = `${p.id}:${p.deliveredAt}:${swapped ? 'swap' : 'timeout'}`;
          if (!probes.has(probeKey) && (this.lastLogReadAt || 0) < now - 500) {
            probes.add(probeKey);
            wantFreshLog = true;
          }
        } else if (now - p.deliveredAt >= 1200 && (this.lastLogReadAt || 0) < p.deliveredAt) {
          wantFreshLog = true;
        }
      }
      if (wantFreshLog) {
        const beforeAt = this.lastLogReadAt || 0;
        this.readLog(cx);
        // When readLog spawned an async fetch, its completion runs reconcilePending(fromReadLog: true);
        // when readLog is synchronous or a test stub (`!this.logLoading`), reconcile immediately.
        if (!this.logLoading && (this.lastLogReadAt || 0) === beforeAt) {
          this.reconcilePending(cx, { forceLogReady: !this.logError });
        } else {
          this.scheduleConfirmCheck(cx);
        }
        return;
      }
      this.reconcilePending(cx, { forceLogReady: !this.logLoading && !this.logError });
    });
  }
  scheduleQueueFlush(cx) {
    if (this.queueTimer || !this.pending.some(p => p.queued && !p.failed)) return;
    this.queueTimer = true;
    cx.timer.after(1500, cx => {
      this.queueTimer = false;
      this.reconcilePending(cx, { forceLogReady: !this.logLoading && !this.logError });
      const pmTerm = this.pmTerminal();
      const status = pmLiveStatus(pmTerm, this.live());
      if (pmTerm && pmCanReceive(status) && this.pending.some(p => p.queued && !p.failed)) {
        this.flushQueue(cx);
      } else if (this.pending.some(p => p.queued && !p.failed)) {
        if (pmTerm && !pmCanReceive(status)) this.probePmDialog(cx);
        this.scheduleQueueFlush(cx);
      }
    });
  }
  flushQueue(cx) {
    const checkNow = this.nowMs();
    if (this.flushingQueue && checkNow - (this.flushingQueueAt || 0) < 50000) return;
    const pmTerm = this.pmTerminal();
    if (!pmTerm) {
      if (this.pending.some(p => p.queued && !p.failed)) this.scheduleQueueFlush(cx);
      return;
    }
    const status = pmLiveStatus(pmTerm, this.live());
    if (!pmCanReceive(status)) {
      this.probePmDialog(cx);
      this.scheduleQueueFlush(cx);
      return;
    }
    const nextIdx = this.pending.findIndex(p => p.queued && !p.failed);
    if (nextIdx < 0) return;
    // Preserve strict FIFO across a PM terminal swap: if an earlier bubble was sent to the old PM
    // terminal and hasn't been confirmed or re-queued yet, reconcile it against the log first so it
    // never gets overtaken by `next`.
    const curSession = pmSessionKey(pmTerm, this.pm());
    const earlierSwapped = this.pending.slice(0, nextIdx).some(p =>
      p && !p.failed && !p.queued && !p.inFlight && p.deliveredAt > 0 &&
      ((p.sentTo && p.sentTo !== pmTerm.address) || (p.sentSession && curSession && p.sentSession !== curSession)));
    if (earlierSwapped) {
      const beforeAt = this.lastLogReadAt || 0;
      this.readLog(cx);
      if (!this.logLoading && (this.lastLogReadAt || 0) === beforeAt) {
        this.reconcilePending(cx, { forceLogReady: !this.logError });
      } else {
        this.scheduleConfirmCheck(cx);
        this.scheduleQueueFlush(cx);
      }
      return;
    }
    const next = this.pending[nextIdx];
    const now = this.nowMs();
    const inFlightSession = pmSessionKey(pmTerm, this.pm());
    this.pending = this.pending.map(p => p.id === next.id
      ? { ...p, queued: false, inFlight: true, inFlightAt: now, inFlightTo: pmTerm.address, inFlightSession, swapWaitSince: 0 } : p);
    if (this.pmName) {
      (this.pendingByPm ||= new Map()).set(this.pmName, this.pending);
      this.saveQueue(this.pmName, this.pending);
    }
    this.deliverBubble(next, pmTerm, cx);
    this.notifySafe(cx);
  }
  deliverBubble(bubble, terminal, cx) {
    const pmName = this.pmName;
    const slug = projectSlug(this.pm());
    const sentSession = pmSessionKey(terminal, this.pm());
    const flushStamp = this.nowMs();
    this.flushingQueue = true;
    this.flushingQueueAt = flushStamp;
    cx.spawn(async cx => {
      let requeued = false;
      let targetChanged = false;
      try {
        const res = await this.deliverProject(terminal.address, bubble.said, bubble.files, {
          msgId: bubble.msgId || '',
          question: bubble.question || '',
          slug,
        });
        const serverReply = res?.reply;
        const now = this.nowMs();
        const curTerm = this.pmName === pmName ? this.pmTerminal() : terminal;
        const curSession = this.pmName === pmName ? pmSessionKey(curTerm, this.pm()) : sentSession;
        const pmWorking = this.pmName === pmName ? this.isPmWorking(curTerm, this.live(), this.activePmTurn()) : false;
        const swappedDuringSend = this.pmName === pmName && (
          (curTerm?.address || '') !== terminal.address ||
          Boolean(sentSession && curSession && curSession !== sentSession)
        );
        const byPm = this.pendingByPm ||= new Map();
        const cur = this.pmName === pmName ? this.pending : (byPm.get(pmName) || []);
        const serverLogged = Boolean(serverReply?.ok && serverReply.status === 'delivered' && Number(serverReply.offset) > 0);
        const cleared = cur.map(p => p.id === bubble.id ? (p.received ? p : (serverLogged
          ? confirmReceiptBubble(p, Number(serverReply.at_ms) || now, now)
          : {
            ...p,
            queued: false,
            inFlight: false,
            inFlightAt: 0,
            sentTo: terminal.address,
            sentSession,
            deliveredAt: now,
            idleSince: pmWorking ? 0 : now,
            swapDetectedAt: swappedDuringSend ? now : 0,
            swapWaitSince: 0,
            inFlightTo: '',
            inFlightSession: '',
            unsure: false,
            lastError: '',
          })) : p);
        byPm.set(pmName, cleared);
        this.saveQueue(pmName, cleared);
        if (this.pmName === pmName) {
          this.pending = cleared;
          this.pmSendBlockError = '';
          this.pmDialog = null;
          this.landed(bubble.draftKey, { text: bubble.words, files: bubble.files, quotes: bubble.quotes || [] }, true);
        }
      } catch (e) {
        const msg = String(e.message || e);
        const now = this.nowMs();
        const curTerm = this.pmName === pmName ? this.pmTerminal() : null;
        const curStatus = curTerm ? pmLiveStatus(curTerm, this.live()) : '';
        const pmSwappedOrGone = !e?.upload && this.pmName === pmName &&
          (isTargetGoneSendError(e) || (curTerm?.address || '') !== terminal.address);
        const dialogOrDraft = isDialogOrDraftSendError(e) || Boolean(curTerm && !pmCanReceive(curStatus));
        const attempts = (Number(bubble.attempts) || 0) + 1;
        const transientRetry = !pmSwappedOrGone && (dialogOrDraft || (isQueueableSendError(e) && attempts <= 1));
        const byPm = this.pendingByPm ||= new Map();
        const list = this.pmName === pmName ? this.pending : (byPm.get(pmName) || []);
        if (list.some(p => p.id === bubble.id && p.received)) {
          // PM receipt already confirmed this message before `hc send` finished/errored: never requeue or fail.
        } else if (pmSwappedOrGone) {
          requeued = true;
          targetChanged = Boolean(curTerm && curTerm.address !== terminal.address);
          const updated = list.map(p => p.id === bubble.id ? {
            ...p,
            queued: true,
            inFlight: false,
            inFlightAt: 0,
            failed: '',
            lastError: msg,
            swapWaitSince: curTerm ? 0 : (p.swapWaitSince || now),
            attempts: 0,
          } : p);
          byPm.set(pmName, updated);
          this.saveQueue(pmName, updated);
          if (this.pmName === pmName) this.pending = updated;
        } else if (transientRetry) {
          requeued = true;
          const updated = list.map(p => p.id === bubble.id ? {
            ...p,
            queued: true,
            inFlight: false,
            inFlightAt: 0,
            failed: '',
            attempts: dialogOrDraft ? 0 : attempts,
          } : p);
          byPm.set(pmName, updated);
          this.saveQueue(pmName, updated);
          if (this.pmName === pmName) {
            this.pending = updated;
            this.pmSendBlockError = msg;
            this.pmDialog = { pm: pmName, address: terminal.address, screen: this.pmDialog?.screen || '', dialog: classifyPmDialog(this.pmDialog?.screen || '', msg, curStatus) };
          }
        } else {
          const updated = list.map(p => p.id === bubble.id ? {
            ...p,
            queued: false,
            inFlight: false,
            inFlightAt: 0,
            deliveredAt: 0,
            failed: msg,
            failedAt: now,
            ...(e.upload ? { upload: true } : {}),
          } : p);
          byPm.set(pmName, updated);
          this.saveQueue(pmName, updated);
          if (this.pmName === pmName) {
            this.pending = updated;
            this.landed(bubble.draftKey, { text: bubble.words, files: bubble.files, quotes: bubble.quotes || [] }, false);
          }
        }
      } finally {
        if (this.flushingQueueAt === flushStamp) this.flushingQueue = false;
      }
      this.notifySafe(cx);
      if (this.pmName === pmName) {
        if (requeued) {
          if (targetChanged) {
            this.flushQueue(cx);
          } else {
            if (this.pmTerminal()) this.probePmDialog(cx, true);
            this.scheduleQueueFlush(cx);
          }
        } else {
          this.readLog(cx);
          cx.timer?.after?.(600, liveCx => { if (this.pmName === pmName) this.readLog(liveCx); });
          this.scheduleConfirmCheck(cx);
          if (this.pending.some(p => p.queued && !p.failed)) this.flushQueue(cx);
        }
      } else if (this.pending.some(p => p.queued && !p.failed)) {
        this.flushQueue(cx);
      }
    });
  }
  // The bubble shows at once; the same line in the log replaces it.
  // `question` tags a quick answer so its options stay disabled while it is in flight.
  // files: the box's attachments, sent as the message's last lines (see messageText).
  // to: the title of the question the box's words answer (see answering): they go out after its 【title】.
  // quotes: quoted message excerpts attached above the box; serialized with provenance for the PM.
  say(text, cx, question, files = [], to = '', quotes = []) {
    text = String(text || '').trim();
    files = question ? [] : withFiles([], files);
    const quoteList = question ? [] : withQuote([], ...(Array.isArray(quotes) ? quotes : []));
    if (!text && !files.length && !quoteList.length) return false;
    const said = formatQuotedMessage(quoteList, text, { to });
    const message = messageText(said, files, word(this.lang, 'attachments')), terminal = this.pmTerminal();
    const pmStarting = this.isPmStarting();
    if (!message || (!terminal && !pmStarting)) return false;
    // words: the box's own words, without the title, which is what its draft holds.
    const key = question ? '' : this.mainKey;
    const now = this.nowMs();
    const status = pmLiveStatus(terminal, this.live());
    const mustQueue = !terminal || !pmCanReceive(status) || this.flushingQueue || this.pending.some(p => p.queued && !p.failed);
    const id = ++this.seq;
    const rawMsgId = makeClientMsgId(now, id);
    const bubble = {
      id,
      msgId: typeof rawMsgId === 'string' ? rawMsgId : '',
      text: message,
      said,
      words: text,
      to,
      files,
      quotes: quoteList,
      sentAt: now,
      question,
      draftKey: key,
      queued: mustQueue,
      inFlight: !mustQueue,
      ...(mustQueue ? (terminal ? {} : { swapWaitSince: now })
        : { inFlightAt: now, inFlightTo: terminal.address, inFlightSession: pmSessionKey(terminal, this.pm()) }),
    };
    // The bubble is kept in storage until it settles (QUEUE_KEY), so a reload shows it again and does
    // not send it twice; its words then leave the box's draft, or a reload would offer them a second
    // time. A bubble that fails gives them back (landed, reconcilePending). A quick answer was never a draft.
    this.leaving(key);
    this.pending = [...this.pending, bubble];
    (this.pendingByPm ||= new Map()).set(this.pmName, this.pending);
    this.saveQueue(this.pmName, this.pending);
    this.settleDraft(key, { text, files, quotes: quoteList }, true);
    // The user's own words, typed or picked on a question, are the end of the conversation: the view goes there.
    this.follow();
    this.notifySafe(cx);
    if (mustQueue) {
      if (terminal && !pmCanReceive(status)) this.probePmDialog(cx, true);
      this.scheduleQueueFlush(cx);
    } else {
      this.deliverBubble(bubble, terminal, cx);
    }
    return true;
  }
  sendMain(cx) {
    if (this.say(this.input.value(), cx, undefined, this.files, this.answering?.title, this.quotes)) {
      this.input.set_value(''); this.draft = ''; this.files = []; this.quotes = []; this.selectionBar = null; this.answering = null;
      if (this.mention?.which === 'main') this.mention = null;
      if (this.mentionDismissed?.which === 'main') this.mentionDismissed = null;
      this.notifySafe(cx);
    }
  }
  // The "own words" row of a question card: the project's box answers that card, and takes the keyboard.
  answerInOwnWords(item, cx) {
    this.answering = { key: item.key, title: item.title, task: item.task || '', ...(taskNumber(item) ? { number: taskNumber(item) } : {}) };
    this.input.focus();
    cx.notify();
  }
  // A failed bubble: clicking sends it again; never drops the bubble if the PM is still offline.
  // One that timed out may have reached the PM after all: it first checks a fresh read of the log
  // and settles as delivered when the log has it, else goes out again (reconcilePendingSends).
  retry(id, cx) {
    const bubble = this.pending.find(p => p.id === id);
    if (!bubble || bubble.received) return;
    if (!bubble.upload && (!bubble.failed || bubble.timedOut)) {
      const receipts = this.pmReceipts();
      const clockOffsetMs = this.clockOffsetMs || 0;
      const used = settledReceiptIndices(receipts, this.events, { clockOffsetMs });
      for (const p of this.pending) {
        if (p?.received) findReceiptMatch(p, receipts, used, { clockOffsetMs });
      }
      const coalesced = findCoalescedReceiptMatches(this.pending, receipts, used, { clockOffsetMs });
      const hit = (coalesced instanceof Map ? coalesced.get(bubble) : null) || findReceiptMatch(bubble, receipts, used, { clockOffsetMs });
      if (hit) {
        const now = this.nowMs();
        this.pending = this.pending.map(p => p.id === id ? confirmReceiptBubble(p, hit.atMs, now) : p);
        if (this.pmName) {
          (this.pendingByPm ||= new Map()).set(this.pmName, this.pending);
          this.saveQueue(this.pmName, this.pending);
        }
        if (bubble.draftKey) {
          this.landed(bubble.draftKey, { text: bubble.words, files: bubble.files, quotes: bubble.quotes || [] }, true);
        }
        this.cleanSent(bubble.files, bubble.id);
        this.notifySafe(cx);
        return;
      }
    }
    if (!this.pmTerminal() && !this.isPmStarting()) {
      this.pending = this.pending.map(p => p.id === id ? { ...p, failed: word(this.lang, 'offline') } : p);
      if (this.pmName) (this.pendingByPm ||= new Map()).set(this.pmName, this.pending);
      this.notifySafe(cx);
      return;
    }
    if (bubble.timedOut) {
      const now = this.nowMs();
      this.pending = this.pending.map(p => p.id === id ? {
        ...p, failed: '', failedAt: 0, timedOut: false, verifying: true, verifySince: now,
        queued: false, inFlight: false, deliveredAt: 0, idleSince: 0,
      } : p);
      if (this.pmName) {
        (this.pendingByPm ||= new Map()).set(this.pmName, this.pending);
        this.saveQueue(this.pmName, this.pending);
      }
      // Its words went back to the draft when it timed out; they are on their way again.
      this.settleDraft(bubble.draftKey, { text: bubble.words, files: bubble.files, quotes: bubble.quotes || [] }, true);
      this.readLog(cx);
      this.scheduleConfirmCheck(cx);
      this.notifySafe(cx);
      return;
    }
    const prev = this.pending;
    this.pending = prev.filter(p => p.id !== id);
    if (!this.say(bubble.words ?? bubble.text, cx, bubble.question, bubble.files, bubble.to, bubble.quotes || [])) {
      this.pending = prev;
      this.notifySafe(cx);
    }
  }
  sendThread(cx) {
    const text = this.threadInput.value().trim(), files = this.threadFiles, terminal = this.threadTerminal(), key = this.threadKey;
    const message = messageText(text, files, word(this.lang, 'attachments'));
    if (!message || !terminal) return;
    const targetThread = this.thread;
    if (text) this.sessionSent = [...(this.sessionSent || []).slice(-19), text];
    this.lastThreadSendAt = Date.now();
    this.sessionAway = false;
    this.leaving(key);
    this.threadInput.set_value(''); this.threadDraft = ''; this.threadFiles = []; this.threadError = '';
    if (this.mention?.which === 'thread') this.mention = null;
    if (this.mentionDismissed?.which === 'thread') this.mentionDismissed = null;
    cx.spawn(async cx => {
      try {
        await this.deliver(terminal.address, text, files);
        this.landed(key, { text, files }, true);
        this.cleanSent(files);
        if (this.detail && this.thread === targetThread && this.threadTab === 'session') {
          cx.timer?.after(800, cx => {
            if (this.detail && this.thread === targetThread) this.readThreadSession(cx);
          });
        }
      }
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

  projectTasks() {
    if (this._renderProjTasks) return this._renderProjTasks;
    const list = this.tasks || foldReviews(this.state.tasks);
    const pmName = this.pm()?.name || '';
    const listLen = list.length;
    const listFirst = listLen ? list[0] : null, listLast = listLen ? list[listLen - 1] : null;
    const c = this._projTasksCache;
    if (c && c.list === list && c.listLen === listLen && c.listFirst === listFirst && c.listLast === listLast && c.pmName === pmName) {
      if (this._inRender) this._renderProjTasks = c.res;
      return c.res;
    }
    const mine = pmName ? list.filter(t => t && (t.pm || '') === pmName) : list;
    const res = mine.length ? mine : list;
    this._projTasksCache = { list, listLen, listFirst, listLast, pmName, res };
    if (this._inRender) this._renderProjTasks = res;
    return res;
  }
  resetRenderCaches() {
    this._timelineCache = null;
    this._taskTreeCache = null;
    this._mdLinkCache = null;
    this._taskNumIndex = null;
    this._projTasksCache = null;
    this._blockKeySet = null;
    this.fadingKeys = null;
    this.fadeClearTimer?.cancel?.();
    this.fadeClearTimer = null;
  }
  taskNumberIndex() {
    if (this._renderTaskNumIdx) return this._renderTaskNumIdx;
    const list = this.tasks || this.state.tasks || [];
    const retired = this.state.retired_parts || [];
    const taskNumbers = this.state.task_numbers || null;
    const listLen = list.length, retiredLen = retired.length;
    const listFirst = listLen ? list[0] : null, listLast = listLen ? list[listLen - 1] : null;
    const retiredFirst = retiredLen ? retired[0] : null, retiredLast = retiredLen ? retired[retiredLen - 1] : null;
    const c = this._taskNumIndex;
    if (c && c.list === list && c.listLen === listLen && c.listFirst === listFirst && c.listLast === listLast
      && c.retired === retired && c.retiredLen === retiredLen && c.retiredFirst === retiredFirst && c.retiredLast === retiredLast
      && c.taskNumbers === taskNumbers) {
      if (this._inRender) this._renderTaskNumIdx = c;
      return c;
    }
    const listMap = new Map();
    for (let i = 0; i < listLen; i++) {
      const t = list[i];
      if (t?.id && !listMap.has(t.id)) listMap.set(t.id, taskNumber(t) || 0);
    }
    const retiredMap = new Map();
    for (let i = 0; i < retiredLen; i++) {
      const t = retired[i];
      if (t?.id && !retiredMap.has(t.id)) retiredMap.set(t.id, taskNumber(t) || 0);
    }
    const next = { list, listLen, listFirst, listLast, retired, retiredLen, retiredFirst, retiredLast, taskNumbers, listMap, retiredMap };
    this._taskNumIndex = next;
    if (this._inRender) this._renderTaskNumIdx = next;
    return next;
  }
  taskNumberFor(idOrObj) {
    if (!idOrObj) return 0;
    if (typeof idOrObj === 'object') return taskNumber(idOrObj) || this.taskNumberFor(idOrObj.id || idOrObj.task || idOrObj.target || '');
    const id = String(idOrObj);
    const idx = this.taskNumberIndex();
    let num = 0;
    if (idx.listMap.has(id)) num = idx.listMap.get(id);
    else if (idx.retiredMap.has(id)) num = idx.retiredMap.get(id);
    else if (this.threadTask?.id === id) num = taskNumber(this.threadTask) || 0;
    return num || taskNumber(this.state.task_numbers?.[id]);
  }
  formattedPmMarkdown(rawMd, projTasks = null) {
    const src = String(rawMd ?? '');
    if (!src) return '';
    // Fast path: without `](thread:`, decorateThreadLinks is a no-op and viewMarkdown is pure (cached in model.js).
    if (!src.includes('](thread:')) return viewMarkdown(src);
    let map = this._renderMdLinkMap;
    if (!map) {
      const tasks = projTasks || this.projectTasks();
      const taskNumbers = this.state.task_numbers || null;
      const retiredParts = this.state.retired_parts || [];
      const events = Array.isArray(this.events) ? this.events : [];
      const evLen = events.length;
      const evFirst = evLen ? events[0] : null;
      const evLast = evLen ? events[evLen - 1] : null;
      const tLen = tasks.length;
      const tFirst = tLen ? tasks[0] : null;
      const tLast = tLen ? tasks[tLen - 1] : null;
      const rLen = retiredParts.length;
      const rFirst = rLen ? retiredParts[0] : null;
      const rLast = rLen ? retiredParts[rLen - 1] : null;
      const c = this._mdLinkCache;
      const valid = Boolean(c
        && c.pmName === this.pmName
        && c.tasks === tasks && c.tasksLen === tLen && c.tasksFirst === tFirst && c.tasksLast === tLast
        && c.taskNumbers === taskNumbers
        && c.retiredParts === retiredParts && c.retiredLen === rLen && c.retiredFirst === rFirst && c.retiredLast === rLast
        && c.events === events && c.eventsLen === evLen && c.eventsFirst === evFirst && c.eventsLast === evLast);
      if (!valid) {
        this._mdLinkCache = {
          pmName: this.pmName,
          tasks, tasksLen: tLen, tasksFirst: tFirst, tasksLast: tLast,
          taskNumbers,
          retiredParts, retiredLen: rLen, retiredFirst: rFirst, retiredLast: rLast,
          events, eventsLen: evLen, eventsFirst: evFirst, eventsLast: evLast,
          map: new Map(),
        };
      }
      map = this._mdLinkCache.map;
      if (this._inRender) this._renderMdLinkMap = map;
    }
    let hit = map.get(src);
    if (hit !== undefined) return hit;
    const tasks = projTasks || this.projectTasks();
    hit = viewMarkdown(decorateThreadLinks(src, tasks, this.state.task_numbers || null, {
      retiredParts: this.state.retired_parts || [], events: Array.isArray(this.events) ? this.events : [],
    }));
    if (map.size >= 512) map.delete(map.keys().next().value);
    map.set(src, hit);
    return hit;
  }
  resolveTimelineData(pm, today, typingNow) {
    const events = Array.isArray(this.events) ? this.events : [];
    const tasks = Array.isArray(this.state?.tasks) ? this.state.tasks : [];
    const taskNumbers = this.state?.task_numbers || null;
    const pending = Array.isArray(this.pending) ? this.pending : [];
    const pastes = Array.isArray(this.pastes) ? this.pastes : [];
    const pmName = pm?.name || '';
    const pmPane = pm?.pane || '';
    const pmCountsWaiting = Number.isFinite(pm?.counts?.waiting) ? pm.counts.waiting : null;
    const typing = Boolean(typingNow);
    const evLen = events.length;
    const evFirst = evLen ? events[0] : null;
    const evLast = evLen ? events[evLen - 1] : null;
    const evLastText = evLast?.text;
    const evLastStatus = evLast?.status;
    const tLen = tasks.length;
    const tFirst = tLen ? tasks[0] : null;
    const tLast = tLen ? tasks[tLen - 1] : null;
    const paLen = pastes.length;
    const paLast = paLen ? pastes[paLen - 1] : null;
    const clockOffsetMs = this.clockOffsetMs || 0;
    const pendingSig = pendingSignature(pending);
    const c = this._timelineCache;
    if (c
      && c.pmName === pmName && c.pmPane === pmPane && c.pmCountsWaiting === pmCountsWaiting && c.today === today && c.typing === typing
      && c.clockOffsetMs === clockOffsetMs
      && c.events === events && c.eventsLen === evLen && c.eventsFirst === evFirst && c.eventsLast === evLast
      && c.eventsLastText === evLastText && c.eventsLastStatus === evLastStatus
      && c.tasks === tasks && c.tasksLen === tLen && c.tasksFirst === tFirst && c.tasksLast === tLast
      && c.taskNumbers === taskNumbers
      && c.pendingSig === pendingSig
      && c.pastes === pastes && c.pastesLen === paLen && c.pastesLast === paLast) {
      return c;
    }
    const items = timeline(events, tasks, {
      pending, today, typing, pastes, pm: pmName, pmPane, taskNumbers, clockOffsetMs,
    });
    const stops = bellStops(items, tasks, pm);
    const blocks = timelineRows(turns(items, pmPane));
    const blockKeySet = new Set();
    for (let i = 0; i < blocks.length; i++) {
      const b = blocks[i];
      if (b?.key) blockKeySet.add(b.key);
      if (Array.isArray(b?.parts)) {
        for (let j = 0; j < b.parts.length; j++) {
          const pk = b.parts[j]?.key;
          if (pk) blockKeySet.add(pk);
        }
      }
    }
    const newest = newestReply(items);
    const keys = items.map(i => i.key);
    const answered = answeredTasks(items);
    const foldedTasks = foldReviews(markAnswered(tasks, answered));
    const waiting = bellCount(pm, tasks, answered);
    const next = {
      pmName, pmPane, pmCountsWaiting, today, typing, clockOffsetMs,
      events, eventsLen: evLen, eventsFirst: evFirst, eventsLast: evLast,
      eventsLastText: evLastText, eventsLastStatus: evLastStatus,
      tasks, tasksLen: tLen, tasksFirst: tFirst, tasksLast: tLast,
      taskNumbers,
      pendingSig,
      pastes, pastesLen: paLen, pastesLast: paLast,
      items, stops, blocks, blockKeySet, newest, keys, answered, foldedTasks, waiting,
    };
    this._timelineCache = next;
    return next;
  }
  resolveTaskTree(pm, allTasks, termsNow, liveNow, tabsNow, lang, alreadyFolded = false) {
    const tasks = Array.isArray(allTasks) ? allTasks : [];
    const events = Array.isArray(this.events) ? this.events : [];
    const retiredParts = Array.isArray(this.state?.retired_parts) ? this.state.retired_parts : [];
    const pmName = pm?.name || '';
    const pmProject = pm?.project || '';
    const pmPane = pm?.pane || '';
    const pmRepo = pm?.repo || '';
    const pmWorktrees = pm?.worktrees || '';
    const evLen = events.length;
    const evFirst = evLen ? events[0] : null;
    const evLast = evLen ? events[evLen - 1] : null;
    const tLen = tasks.length;
    const tFirst = tLen ? tasks[0] : null;
    const tLast = tLen ? tasks[tLen - 1] : null;
    const rLen = retiredParts.length;
    const rFirst = rLen ? retiredParts[0] : null;
    const rLast = rLen ? retiredParts[rLen - 1] : null;
    const hostSig = hostLiveSignature(termsNow, liveNow, tabsNow);
    const pmHelpers = pm?.helpers;
    const c = this._taskTreeCache;
    if (c
      && c.pmName === pmName && c.pmProject === pmProject && c.pmPane === pmPane && c.pmRepo === pmRepo && c.pmWorktrees === pmWorktrees
      && c.lang === lang && c.alreadyFolded === alreadyFolded
      && c.tasks === tasks && c.tasksLen === tLen && c.tasksFirst === tFirst && c.tasksLast === tLast
      && c.events === events && c.eventsLen === evLen && c.eventsFirst === evFirst && c.eventsLast === evLast
      && c.retiredParts === retiredParts && c.retiredLen === rLen && c.retiredFirst === rFirst && c.retiredLast === rLast
      && c.hostSig === hostSig && c.pmHelpers === pmHelpers) {
      return c.tree;
    }
    const tree = taskTree(pm, tasks, events, {
      terms: termsNow, live: liveNow, tabs: tabsNow, lang, retiredParts, alreadyFolded,
    });
    this._taskTreeCache = {
      pmName, pmProject, pmPane, pmRepo, pmWorktrees, lang, alreadyFolded,
      tasks, tasksLen: tLen, tasksFirst: tFirst, tasksLast: tLast,
      events, eventsLen: evLen, eventsFirst: evFirst, eventsLast: evLast,
      retiredParts, retiredLen: rLen, retiredFirst: rFirst, retiredLast: rLast,
      hostSig, pmHelpers, tree,
    };
    return tree;
  }
  listResting() { return this.listShown ?? this.wide; }
  openThread(id, cx, { forceOpen = false } = {}) {
    // A review thread is shown in the task it reviews (foldReviews), and `#42` resolves in project scope.
    id = resolveThreadRef(this.projectTasks(), id, this.state.task_numbers, {
      retiredParts: this.state.retired_parts, events: this.events,
    });
    this.clearHoverNow(cx);
    if (!forceOpen && this.thread === id && this.detail) { this.detail = false; this.resetThreadChange(); this.syncVisibleSideTab(cx); cx.notify(); return; }
    if (this.thread !== id) {
      this.threadTask = null; this.threadError = ''; this.showThreadDraft(id);
      this.threadLog = null; this.threadLogKept = []; this.threadEarlierLoading = false; this.threadEarlierError = ''; this.threadAnchor = null;
      this.threadLogExpanded = false;
      this.resetThreadSession();
      this.resetThreadChange();
    }
    this.thread = id;
    this.detail = true;
    this.readThread(cx);
    cx.notify();
  }
  jumpToThread(id, cx) {
    if (!id) return;
    const allTasks = this.tasks || foldReviews(this.state.tasks);
    const resolved = threadFor(allTasks, id);
    const target = allTasks.find(t => t.id === resolved) || (Array.isArray(this.state.tasks) ? this.state.tasks.find(t => t.id === resolved) : null);
    if (target?.pm && this.pmName && target.pm !== this.pmName) {
      this.clearHoverNow(cx);
      setShared(SHARED, {
        pm: target.pm,
        ...(this.machine ? { machine: this.machine } : {}),
        thread: resolved,
        jumpSeq: Date.now(),
      });
      return;
    }
    this.epicOverrides = this.epicOverrides || new Map();
    this.expandedDone = this.expandedDone || new Set();
    const byId = new Map(allTasks.map(t => [t.id, t]));
    const seen = new Set([resolved]);
    let cur = target;
    while (cur?.parent && !seen.has(cur.parent)) {
      seen.add(cur.parent);
      this.epicOverrides.set(cur.parent, true);
      if (['done', 'merged', 'released', 'abandoned', 'cancelled'].includes(target?.status)) {
        this.expandedDone.add(`epic:${cur.parent}`);
      }
      cur = byId.get(cur.parent);
    }
    this.sideTab = 'threads';
    this.listShown = true;
    this.highlightThread = resolved;
    this.pendingScrollThread = resolved;
    this.highlightTimer?.cancel?.();
    this.highlightTimer = cx.timer?.after?.(2200, cx => {
      if (this.highlightThread === resolved) { this.highlightThread = ''; cx.notify(); }
    });
    this.openThread(resolved, cx, { forceOpen: true });
  }
  jumpToDependency(dep, cx) {
    if (!dep || !dep.clickable) return;
    if (dep.pm && this.pmName && dep.pm !== this.pmName) {
      this.clearHoverNow(cx);
      setShared(SHARED, {
        pm: dep.pm,
        ...(dep.machine ? { machine: dep.machine } : this.machine ? { machine: this.machine } : {}),
        thread: dep.sourceId || dep.id,
        jumpSeq: Date.now(),
      });
      return;
    }
    this.jumpToThread(dep.sourceId || dep.id, cx);
  }
  // A link in a reply or doc: a thread/library/file/session pointer opens in place; a web address goes to the browser.
  followLink(url, cx) {
    if (this.openMentionRef(url, cx)) return;
    if (/^https?:\/\//i.test(String(url || ''))) cx.open_url(url);
  }
  // The header's icon: shows the thread list, or puts the panel away whatever it shows.
  togglePanel(cx) {
    this.listShown = !(this.listResting() || this.detail);
    this.detail = false;
    this.resetThreadChange();
    if (!this.listShown && ['librarySearch', 'memorySearch', 'docFind', 'docEditor', 'docName', 'memDesc'].includes(this.typing)) {
      this.keyFocus?.focus();
    }
    this.syncVisibleSideTab(cx);
    cx.notify();
  }
  // ---- Unified project search (Interface I) ---------------------------------
  consumeSearchKey(cx) {
    this.searchConsumedKey = true;
    Promise.resolve().then(() => { this.searchConsumedKey = false; });
    cx?.timer?.after?.(0, () => { this.searchConsumedKey = false; });
  }

  ensureSearchSources(cx) {
    if (this.memorySupported() && !this.memoryRead && !this.memoryLoading) this.readMemory(cx);
    if (this.librarySupported() && !this.libraryRead && !this.libraryLoading) this.readLibrary(cx);
  }

  openProjectSearch(cx, { scope = '' } = {}) {
    if (!this.pm()) return;
    this.hoverKey = '';
    this.mention = null;
    this.searchOpen = true;
    if (scope) this.searchScope = scope;
    else if (!this.searchScope) this.searchScope = 'all';
    this.searchIndex = 0;
    this.searchKey = '';
    this.searchScroll?.scroll_to_item?.(0);
    this.ensureSearchSources(cx);
    cx?.timer?.after?.(0, () => {
      this.searchInput?.focus?.();
      const q = String(this.searchQuery || '');
      if (q && typeof this.searchInput?.set_selected_range === 'function') {
        this.searchInput.set_selected_range({ start: 0, end: q.length });
      }
    });
    cx?.notify?.();
  }

  closeProjectSearch(cx, { restoreFocus = true } = {}) {
    if (!this.searchOpen) return;
    this.searchOpen = false;
    if (restoreFocus || this.typing === 'projectSearch') this.keyFocus?.focus?.();
    cx?.notify?.();
  }

  toggleProjectSearch(cx) {
    if (this.searchOpen) this.closeProjectSearch(cx);
    else this.openProjectSearch(cx);
  }

  setSearchScope(scope, cx) {
    this.searchScope = scope || 'all';
    this.searchIndex = 0;
    this.searchKey = '';
    this.searchScroll?.scroll_to_item?.(0);
    this.searchInput?.focus?.();
    cx?.notify?.();
  }

  currentProjectSearch(pm = this.pm(), items = this.items || [], today = iso(new Date())) {
    const allTasks = this.tasks || foldReviews(this.state?.tasks || []);
    return buildProjectSearch({
      pm,
      tasks: allTasks,
      stateEvents: this.state?.events || [],
      events: this.events || [],
      items,
      threadId: this.thread || '',
      threadLog: this.threadLog || null,
      retiredParts: this.state?.retired_parts || [],
      memoryData: this.memoryData || null,
      libraryFiles: this.libraryFiles || [],
      docCache: this.docCache || null,
      librarySupported: this.librarySupported(),
      memorySupported: this.memorySupported(),
      lang: this.lang || this.state?.lang || 'en',
      today,
      query: this.searchQuery || '',
      scope: this.searchScope || 'all',
    });
  }

  moveProjectSearch(delta, cx) {
    const res = this.currentProjectSearch();
    if (!res.flat.length) return;
    const next = stepSearchSelection(res.flat, this.searchIndex || 0, this.searchKey || '', delta);
    this.searchIndex = next.index;
    this.searchKey = next.key;
    // Account for group headers above the selected row when scrolling.
    let itemSlot = next.index;
    for (const g of res.groups) {
      if (next.index >= g.startIndex) itemSlot++;
    }
    this.searchScroll?.scroll_to_item?.(itemSlot);
    cx?.notify?.();
  }

  cycleProjectSearchScope(delta, cx) {
    const res = this.currentProjectSearch();
    const nextScope = stepSearchScope(this.searchScope || 'all', res.scopes, delta);
    this.setSearchScope(nextScope, cx);
  }

  acceptProjectSearch(cx) {
    const res = this.currentProjectSearch();
    if (!res.flat.length) return;
    const cur = stepSearchSelection(res.flat, this.searchIndex || 0, this.searchKey || '', 0);
    const hit = res.flat[cur.index];
    if (hit) this.pickProjectSearchHit(hit, cx);
  }

  escapeProjectSearch(cx) {
    const step = stepSearchEscape({ query: this.searchQuery || '', scope: this.searchScope || 'all' });
    if (step.action === 'clear') {
      this.searchQuery = '';
      this.searchIndex = 0;
      this.searchKey = '';
      this.searchInput?.set_value?.('');
      this.searchScroll?.scroll_to_item?.(0);
      this.searchInput?.focus?.();
      cx?.notify?.();
      return;
    }
    if (step.action === 'resetScope') {
      this.setSearchScope('all', cx);
      return;
    }
    this.closeProjectSearch(cx);
  }

  revealThread(id, cx) {
    const resolved = threadFor(this.tasks || foldReviews(this.state?.tasks || []), id);
    if (!resolved) return;
    this.hoverKey = '';
    if (this.thread === resolved && this.detail) {
      if (this.isThreadChangeOpen()) this.closeThreadChange(cx);
      if (!this.listResting()) { this.listShown = true; cx?.notify?.(); }
      return;
    }
    this.openThread(resolved, cx);
  }

  jumpToConversationItem(itemKey, cx) {
    if (!itemKey) return;
    const items = this.items || [];
    const targetItem = items.find(i => i.key === itemKey);
    if (targetItem?.kind === 'pm' && targetItem.long) {
      this.unfolded.set(itemKey, true);
    }
    const seq = (this.flashSeq || 0) + 1;
    this.flashSeq = seq;
    this.flash = itemKey;
    this.flashTone = 'accent';
    cx?.timer?.after?.(1800, cx => {
      if (this.flashSeq === seq && this.flash === itemKey) {
        this.flash = '';
        cx?.notify?.();
      }
    });
    const blocks = this.lastBlocks || [];
    const topOffset = this.lastTopOffset || 0;
    const row = rowOfKey(blocks, itemKey);
    if (row >= 0) {
      const heights = blocks.map(b => this.heights.get(b.key) || 0);
      const tall = this.tall || this.high || 1;
      this.rest(riseAfterJump(this.rise || 0, heights, row, tall, TAIL));
      this.jumpTarget = { key: itemKey, left: SETTLE };
      this.scroll?.scroll_to_item?.(topOffset + row);
    }
    cx?.notify?.();
  }

  pickProjectSearchHit(hit, cx) {
    if (!hit) return;
    if (hit.kind === 'more') {
      this.setSearchScope(hit.scope, cx);
      return;
    }
    const q = String(this.searchQuery || '').trim();
    this.closeProjectSearch(cx, { restoreFocus: true });
    if (hit.kind === 'thread') {
      this.revealThread(hit.task, cx);
      return;
    }
    if (hit.kind === 'message' || hit.kind === 'decisionEvent') {
      this.jumpToConversationItem(hit.itemKey, cx);
      return;
    }
    if (hit.kind === 'memory') {
      if (!this.listResting()) this.listShown = true;
      this.detail = false;
      this.resetThreadChange();
      this.openDoc({ tab: 'memory', root: hit.root, path: hit.path }, cx, { jumpQuery: q });
      return;
    }
    if (hit.kind === 'library') {
      if (!this.listResting()) this.listShown = true;
      this.detail = false;
      this.resetThreadChange();
      this.openDoc({ tab: 'library', root: hit.root, path: hit.path }, cx, { jumpQuery: q });
    }
  }

  handleKeyDown(e, cx) {
    const ks = e?.keystroke || '';
    if (ks === 'cmd-k' || ks === 'ctrl-k') {
      cx.stop_propagation?.();
      this.toggleProjectSearch(cx);
      return;
    }
    if (ks === 'cmd-f' || ks === 'ctrl-f') {
      const onLib = this.libraryVisible() || (this.activeDoc?.root === 'repo' && this.sideTab === 'library' && this.listResting() && !this.detail);
      const onMem = this.memoryVisible();
      const onSide = onLib || onMem;
      const curTab = onLib ? 'library' : onMem ? 'memory' : '';
      const hasDoc = onSide && this.activeDoc?.tab === curTab && !this.editingDoc && !this.historyView;
      if (hasDoc && !this.searchOpen) {
        cx.stop_propagation?.();
        this.docFindOpen = true;
        if (!this.docFindQuery && this.docJumpQuery) {
          this.docFindQuery = this.docJumpQuery;
          this.docFindInput?.set_value(this.docJumpQuery);
        }
        this.docMatchPos = 0;
        this.docFindJump = Boolean(this.docFindQuery?.trim?.());
        cx.timer?.after?.(0, () => this.docFindInput?.focus?.());
        cx.notify?.();
        return;
      }
      cx.stop_propagation?.();
      this.openProjectSearch(cx);
      return;
    }
    this.escape(e, cx);
  }

  projectSearchOverlay(pm, items, t, today, cx) {
    const lang = this.lang || this.state?.lang || 'en';
    const result = this.currentProjectSearch(pm, items, today);
    const cur = stepSearchSelection(result.flat, this.searchIndex || 0, this.searchKey || '', 0);
    this.searchIndex = cur.index;
    this.searchKey = cur.key;
    return renderProjectSearchOverlay({
      ui: {
        div, svg, v_flex, h_flex, Input, Scrollbar,
        icon: (name, size) => this.icon(name, size),
        iconButton: (id, name, tip, action, themeObj, size) => this.iconButton(id, name, tip, action, themeObj, size),
        threadMark: (row, themeObj) => this.threadMark(row, themeObj),
        memoryTypeColor: (type, themeObj) => this.memoryTypeColor(type, themeObj),
        SPINNER,
      },
      theme: t,
      lang,
      query: this.searchQuery || '',
      scope: result.activeScope,
      inputState: this.searchInput,
      scrollHandle: this.searchScroll,
      result,
      selectedIndex: cur.index,
      memoryLoading: Boolean(this.memoryLoading && !this.memoryRead),
      libraryLoading: Boolean(this.libraryLoading && !this.libraryRead),
      earlierEvents: Boolean(this.logState?.earlier),
      earlierLoading: Boolean(this.earlierLoading),
      earlierError: this.earlierError || '',
      oldRemote: Boolean(this.machine && this.remoteNoProject === this.machine),
      actions: {
        onClose: cx => this.closeProjectSearch(cx),
        onClear: cx => {
          this.searchQuery = '';
          this.searchIndex = 0;
          this.searchKey = '';
          this.searchInput?.set_value?.('');
          this.searchScroll?.scroll_to_item?.(0);
          this.searchInput?.focus?.();
          cx?.notify?.();
        },
        onScope: (scope, cx) => this.setSearchScope(scope, cx),
        onPick: (hit, cx) => this.pickProjectSearchHit(hit, cx),
        onMove: (delta, cx) => this.moveProjectSearch(delta, cx),
        onCycleScope: (delta, cx) => this.cycleProjectSearchScope(delta, cx),
        onAccept: cx => this.acceptProjectSearch(cx),
        onEscape: cx => this.escapeProjectSearch(cx),
        onLoadEarlier: cx => this.loadEarlierEvents(this.lastBlocks || [], cx),
        onKeyDown: (e, cx) => {
          if (!this.searchOpen || this.searchConsumedKey) return;
          const ks = e?.keystroke || '';
          if (ks === 'up') { cx.stop_propagation?.(); this.consumeSearchKey(cx); this.moveProjectSearch(-1, cx); }
          else if (ks === 'down') { cx.stop_propagation?.(); this.consumeSearchKey(cx); this.moveProjectSearch(1, cx); }
          else if (ks === 'tab') { cx.stop_propagation?.(); this.consumeSearchKey(cx); this.cycleProjectSearchScope(1, cx); }
          else if (ks === 'shift-tab') { cx.stop_propagation?.(); this.consumeSearchKey(cx); this.cycleProjectSearchScope(-1, cx); }
          else if (ks === 'enter') { cx.stop_propagation?.(); this.consumeSearchKey(cx); this.acceptProjectSearch(cx); }
          else if (ks === 'escape') { cx.stop_propagation?.(); this.consumeSearchKey(cx); this.escapeProjectSearch(cx); }
        },
      },
    });
  }

  // Esc, one layer a press: @ mention submenu -> @ mention menu -> project search -> answer card -> delete confirm -> dirty box blur -> editor -> retopic -> search -> agent small windows -> history -> bringBack -> change view (diff -> files -> commits) -> thread detail -> open doc -> narrow panel.
  escape(e, cx) {
    if (e.keystroke !== 'escape') return;
    if (this.mentionConsumedKey || this.searchConsumedKey) { cx.stop_propagation?.(); return; }
    const composerBox = this.typing === 'thread' ? this.threadInput : this.typing === 'main' ? this.input : null;
    const composerTyping = Boolean(composerBox?.value().trim());
    const onLib = this.libraryVisible() || (this.activeDoc?.root === 'repo' && this.sideTab === 'library' && this.listResting() && !this.detail);
    const onMem = this.memoryVisible();
    const onSide = onLib || onMem;
    const curTab = onLib ? 'library' : onMem ? 'memory' : '';
    const hasDoc = onSide && this.activeDoc?.tab === curTab;
    const hasEdit = onSide && this.editingDoc?.tab === curTab;
    const hasHistory = onSide && this.historyView?.tab === curTab;
    const editorFocused = ['docEditor', 'docName', 'memDesc'].includes(this.typing);
    const editorTyping = hasEdit && editorFocused && this.editorDirty();
    const inDocFind = onSide && hasDoc && !hasEdit && !hasHistory && this.docFindOpen;
    const tabQuery = onLib ? this.libraryQuery : onMem ? this.memoryQuery : '';
    const searchTyping = onLib ? 'librarySearch' : 'memorySearch';
    const inTabSearch = onSide && !hasDoc && !hasEdit && !hasHistory &&
      (this.typing === searchTyping || Boolean(tabQuery?.trim()));
    const mentionOpen = Boolean(this.mention && this.typing === this.mention.which);
    const step = escapeStep({
      mentionSub: mentionOpen && this.mention.category !== 'all',
      mention: mentionOpen,
      projectSearch: Boolean(this.searchOpen),
      selectionBar: Boolean(this.selectionBar),
      answering: Boolean(this.answering) && this.typing !== 'thread',
      confirmDelete: onSide && hasDoc && Boolean(this.confirmDeleteKey),
      typing: composerTyping || editorTyping,
      editing: hasEdit,
      retopic: onSide && hasDoc && Boolean(this.retopicOpen),
      search: inDocFind || inTabSearch,
      agentWindows: this.agentWindows,
      history: hasHistory,
      bringBack: Boolean(this.bringBackOpen && !this.bringingBack),
      change: this.isThreadChangeOpen(),
      detail: this.detail,
      doc: hasDoc,
      listOpen: !this.wide && this.listResting(),
    });
    if (!step) {
      if (this.hoverKey) { this.clearHoverNow(cx); cx.stop_propagation?.(); }
      return;
    }
    cx.stop_propagation?.();
    this.clearHoverNow(null);
    if (step === 'mentionSub' || step === 'mention') { this.escapeMention(this.mention.which, cx); return; }
    if (step === 'projectSearch') { this.escapeProjectSearch(cx); return; }
    if (step === 'selectionBar') { this.selectionBar = null; cx.notify(); return; }
    if (step === 'answer') this.answering = null;
    else if (step === 'confirmDelete') this.confirmDeleteKey = '';
    else if (step === 'blur') this.keyFocus.focus();
    else if (step === 'edit') { this.cancelEditDoc(cx); return; }
    else if (step === 'retopic') this.retopicOpen = false;
    else if (step === 'agentWindow') { this.closeTopAgentWindow(cx); return; }
    else if (step === 'bringBack') { this.closeBringBack(cx); return; }
    else if (step === 'change') { this.stepBackThreadChange(cx); return; }
    else if (step === 'search') {
      if (inDocFind) {
        if (this.docFindQuery.trim()) { this.docFindQuery = ''; this.docFindInput?.set_value(''); }
        else { this.docFindOpen = false; this.keyFocus.focus(); }
      } else if (tabQuery?.trim()) {
        if (onLib) { this.libraryQuery = ''; this.libraryInput?.set_value(''); }
        else { this.memoryQuery = ''; this.memoryInput?.set_value(''); }
      } else {
        this.keyFocus.focus();
      }
    } else if (step === 'history') { this.closeHistory(cx); return; }
    else if (step === 'detail') { this.detail = false; this.resetThreadChange(); this.syncVisibleSideTab(cx); }
    else if (step === 'doc') { this.closeActiveDoc(cx); return; }
    else {
      this.listShown = false;
      if (['librarySearch', 'memorySearch', 'docFind', 'docEditor', 'docName', 'memDesc'].includes(this.typing)) {
        this.keyFocus?.focus();
      }
    }
    if (step === 'detail' && this.typing === 'thread') this.keyFocus.focus();
    cx.notify();
  }

  // ---- Thread change view (Interface H — called by detail panel) ----
  threadChangeSupported() {
    return !(this.machine && (this.remoteNoProject === this.machine || this.remoteNoChange === this.machine));
  }

  isThreadChangeOpen() {
    return Boolean(this.change?.open && this.change?.taskId === this.thread);
  }

  resetThreadChange() {
    this.change = createChangeState();
  }

  openThreadChange(cx) {
    if (!this.thread || !this.threadChangeSupported()) return;
    this.change = openChangeView(this.change, this.thread);
    this.changeScroll?.scroll_to_item?.(0);
    this.readThreadChangeSummary(cx);
    cx.notify();
  }

  closeThreadChange(cx) {
    this.change = closeChangeView(this.change);
    cx.notify();
  }

  toggleThreadChange(cx) {
    if (this.isThreadChangeOpen()) this.closeThreadChange(cx);
    else this.openThreadChange(cx);
  }

  stepBackThreadChange(cx) {
    const res = stepBackChangeView(this.change);
    if (!res.handled) return false;
    this.change = res.state;
    this.changeScroll?.scroll_to_item?.(0);
    cx.notify();
    return true;
  }

  threadChangeButton(_task, t) {
    if (!this.threadChangeSupported()) return null;
    const open = this.isThreadChangeOpen();
    return this.winIconBtn(
      'thread-diff',
      'diff',
      word(this.lang, open ? 'changeClose' : 'diff'),
      cx => this.toggleThreadChange(cx),
      t,
      14,
      open,
    );
  }

  readThreadChangeSummary(cx, { force = false } = {}) {
    const id = this.thread, machine = this.machine, slug = projectSlug(this.pm());
    if (!id || !slug || !this.threadChangeSupported()) return;
    if (!force && this.change?.taskId === id && this.change.summary && !this.change.summaryError) return;
    const seq = (this.change?.reqSeq || 0) + 1;
    this.change = { ...this.change, taskId: id, summaryLoading: true, summaryError: '', reqSeq: seq };
    cx.notify();
    cx.spawn(async cx => {
      try {
        const timeout = machine ? CHANGE_TIMEOUT_REMOTE_MS : CHANGE_TIMEOUT_LOCAL_MS;
        const r = await this.runProject(projectChangeArgv(slug, id), { timeout });
        if (id !== this.thread || machine !== this.machine || this.change?.taskId !== id) return;
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.remoteNoChange = machine;
            this.resetThreadChange();
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const got = JSON.parse(String(r.stdout || '').trim());
        this.change = { ...this.change, summary: got, summaryLoading: false, summaryError: '' };
      } catch (e) {
        if (id === this.thread && machine === this.machine && this.change?.taskId === id) {
          this.change = { ...this.change, summaryLoading: false, summaryError: String(e?.message || e).trim() };
        }
      } finally {
        cx.notify();
      }
    });
  }

  pickChangeAll(cx) {
    this.change = enterChangeFiles(this.change, { scope: 'all' });
    this.changeScroll?.scroll_to_item?.(0);
    cx.notify();
  }

  pickChangeCommit(commitMeta, cx) {
    const hash = String(commitMeta?.hash || '');
    if (!hash) return;
    this.change = enterChangeFiles(this.change, { scope: 'commit', commitHash: hash, commitMeta });
    this.changeScroll?.scroll_to_item?.(0);
    if (!this.change.commitCache?.[hash]) this.readThreadChangeCommit(hash, cx);
    else cx.notify();
  }

  readThreadChangeCommit(hash, cx) {
    const id = this.thread, machine = this.machine, slug = projectSlug(this.pm());
    if (!id || !slug || !hash || !this.threadChangeSupported()) return;
    this.change = { ...this.change, commitLoading: true, commitError: '' };
    cx.notify();
    cx.spawn(async cx => {
      try {
        const timeout = machine ? CHANGE_TIMEOUT_REMOTE_MS : CHANGE_TIMEOUT_LOCAL_MS;
        const r = await this.runProject(projectChangeArgv(slug, id, { commit: hash }), { timeout });
        if (id !== this.thread || machine !== this.machine || this.change?.taskId !== id) return;
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.remoteNoChange = machine;
            this.resetThreadChange();
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const got = JSON.parse(String(r.stdout || '').trim());
        const commitCache = { ...(this.change.commitCache || {}), [hash]: got };
        this.change = {
          ...this.change,
          commitCache,
          ...(this.change.commitHash === hash ? { commitData: got, commitLoading: false, commitError: '' } : {}),
        };
      } catch (e) {
        if (id === this.thread && machine === this.machine && this.change?.taskId === id && this.change?.commitHash === hash) {
          this.change = { ...this.change, commitLoading: false, commitError: String(e?.message || e).trim() };
        }
      } finally {
        cx.notify();
      }
    });
  }

  pickChangeFile(fileMeta, cx) {
    const path = String(fileMeta?.path || '');
    if (!path) return;
    const scope = this.change?.scope || 'all';
    const commitHash = scope === 'commit' ? (this.change?.commitHash || '') : '';
    this.change = enterChangeFileDiff(this.change, fileMeta);
    this.changeScroll?.scroll_to_item?.(0);
    const key = changeDiffKey(scope, commitHash, path);
    if (!this.change.diffCache?.[key]) this.readThreadChangeDiff({ scope, commitHash, path, offset: 0 }, cx);
    else cx.notify();
  }

  readThreadChangeDiff({ scope, commitHash, path, offset = 0 }, cx) {
    const id = this.thread, machine = this.machine, slug = projectSlug(this.pm());
    if (!id || !slug || !path || !this.threadChangeSupported()) return;
    const key = changeDiffKey(scope, commitHash, path);
    const isMore = offset > 0;
    this.change = {
      ...this.change,
      diffLoading: !isMore,
      diffLoadingMore: isMore,
      diffError: '',
    };
    cx.notify();
    cx.spawn(async cx => {
      try {
        const timeout = machine ? CHANGE_TIMEOUT_REMOTE_MS : CHANGE_TIMEOUT_LOCAL_MS;
        const r = await this.runProject(projectChangeArgv(slug, id, {
          commit: scope === 'commit' ? commitHash : '',
          file: path,
          offset,
          limit: CHANGE_DIFF_LIMIT,
        }), { timeout });
        if (id !== this.thread || machine !== this.machine || this.change?.taskId !== id) return;
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.remoteNoChange = machine;
            this.resetThreadChange();
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const got = JSON.parse(String(r.stdout || '').trim());
        const prev = offset > 0 ? this.change.diffCache?.[key] : null;
        const merged = appendDiffPage(prev, got);
        const diffCache = { ...(this.change.diffCache || {}), [key]: merged };
        const onSame = changeDiffKey(this.change.scope, this.change.commitHash, this.change.filePath) === key;
        this.change = {
          ...this.change,
          diffCache,
          ...(onSame ? { diffData: merged, diffLoading: false, diffLoadingMore: false, diffError: '' } : {}),
        };
      } catch (e) {
        const onSame = id === this.thread && machine === this.machine && this.change?.taskId === id
          && changeDiffKey(this.change?.scope, this.change?.commitHash, this.change?.filePath) === key;
        if (onSame) {
          this.change = { ...this.change, diffLoading: false, diffLoadingMore: false, diffError: String(e?.message || e).trim() };
        }
      } finally {
        cx.notify();
      }
    });
  }

  loadMoreThreadChangeDiff(cx) {
    const d = this.change?.diffData;
    if (!d?.has_more || this.change.diffLoading || this.change.diffLoadingMore) return;
    this.readThreadChangeDiff({
      scope: this.change.scope,
      commitHash: this.change.commitHash,
      path: this.change.filePath,
      offset: d.next_offset ?? (d.lines?.length || 0),
    }, cx);
  }

  refreshThreadChange(cx) {
    if (!this.change?.open) return;
    const level = this.change.level;
    if (level === 'diff' && this.change.filePath) {
      const key = changeDiffKey(this.change.scope, this.change.commitHash, this.change.filePath);
      const diffCache = { ...(this.change.diffCache || {}) };
      delete diffCache[key];
      this.change = { ...this.change, diffCache, diffData: null };
      this.readThreadChangeDiff({
        scope: this.change.scope,
        commitHash: this.change.commitHash,
        path: this.change.filePath,
        offset: 0,
      }, cx);
      return;
    }
    if (level === 'files' && this.change.scope === 'commit' && this.change.commitHash) {
      const commitCache = { ...(this.change.commitCache || {}) };
      delete commitCache[this.change.commitHash];
      this.change = { ...this.change, commitCache, commitData: null };
      this.readThreadChangeCommit(this.change.commitHash, cx);
      return;
    }
    this.change = { ...this.change, summary: null, commitCache: {}, diffCache: {} };
    this.readThreadChangeSummary(cx, { force: true });
  }

  threadChangeView(t, width, cx, task = null, today = iso(new Date())) {
    const curTask = task || this.currentThreadPair().task;
    return renderThreadChangeView({
      ui: {
        div, svg, v_flex, h_flex,
        icon: (name, size = 16) => this.icon(name, size),
        iconButton: (id, name, tip, action, th, size = 16, tipOpts = null) => this.iconButton(id, name, tip, action, th, size, tipOpts || { panel: true, placement: 'below-right' }),
        withTip: (key, el, tip, opts = null) => this.withTip(key, el, tip, t, { panel: true, ...(opts || {}) }),
        pill: (text, color) => this.pill(text, color),
        keepPress: (el, kb = null) => keepPress(el, kb),
        SPINNER,
      },
      theme: t,
      lang: this.lang,
      today,
      width,
      state: this.change,
      task: curTask,
      scrollHandle: this.changeScroll,
      actions: {
        onBack: cx => this.stepBackThreadChange(cx),
        onRefresh: cx => this.refreshThreadChange(cx),
        onPickAll: cx => this.pickChangeAll(cx),
        onPickCommit: (c, cx) => this.pickChangeCommit(c, cx),
        onPickFile: (f, cx) => this.pickChangeFile(f, cx),
        onToggleHunk: (hunkId, cx) => {
          this.change = { ...this.change, foldedHunks: toggleDiffHunk(this.change?.foldedHunks, hunkId) };
          cx.notify();
        },
        onToggleAllHunks: (hunks, cx) => {
          this.change = { ...this.change, foldedHunks: toggleAllDiffHunks(this.change?.foldedHunks, hunks) };
          cx.notify();
        },
        onLoadMore: cx => this.loadMoreThreadChangeDiff(cx),
        onToggleBaseMerges: cx => {
          this.change = { ...this.change, showBaseMerges: !this.change?.showBaseMerges };
          cx.notify();
        },
      },
    });
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
  // Bounded, auto-wrapping, panel/window-clamped hover tooltip anchored to its trigger.
  // Replaces GPUI's unbounded single-line native .tooltip(text).
  withTip(key, el, tip, t, opts = {}) {
    if (tip == null || tip === '') return el;
    const text = typeof tip === 'string' ? tip.trim() : String(tip).trim();
    if (!text) return el;
    const tipKey = `tip:${key}`;
    const active = this.hoverKey === tipKey;
    const target = el.on_hover((over, cx) => {
      if (over) {
        if (this.hoverKey !== tipKey) { this.hoverKey = tipKey; cx.notify(); }
      } else if (this.hoverKey === tipKey) {
        this.hoverKey = '';
        cx.notify();
      }
    });
    if (!active) {
      if (!opts.wrap) return target;
      const box = div().relative();
      if (opts.flex1) box.flex_1().min_w(0);
      else if (opts.full) box.w_full().min_w(0);
      else if (opts.flexNone) box.flex_none();
      return box.child(target);
    }
    const panelW = opts.panel ? panelWidth(this.panelWant, this.viewWidth) : 0;
    const layout = tooltipLayout(text, {
      panelWidth: panelW,
      viewWidth: this.viewWidth || 0,
      maxWidth: opts.maxWidth,
      maxLines: opts.maxLines,
      placement: opts.placement || (opts.panel ? 'above-left' : 'below-left'),
    });
    const wrapBox = () => {
      const box = div().relative();
      if (opts.flex1) box.flex_1().min_w(0);
      else if (opts.full) box.w_full().min_w(0);
      else if (opts.flexNone) box.flex_none();
      return box;
    };
    if (!layout) return opts.wrap ? wrapBox().child(target) : target;
    const fill = [t.raised, t.popover, t.surface].find(c => c && c !== t.chrome) || t.raised;
    const card = v_flex().w(layout.width).max_w(layout.maxWidth).max_h(layout.maxHeight)
      .px(9).py(6).rounded(8).bg(fill).border_1().border_color(t.border).shadow_lg().overflow_hidden()
      .children(layout.lines.map(line => div().w_full().whitespace_normal()
        .text_size(layout.fontSize).line_height(`${layout.lineHeight}px`)
        .text_color(t.foreground).child(line)));
    const anchor = div().id(`hover-tip-anchor-${key}`).absolute().w(0).h(0);
    if (layout.pos.left !== undefined) anchor.left(layout.pos.left);
    if (layout.pos.right !== undefined) anchor.right(layout.pos.right);
    if (layout.pos.top !== undefined) anchor.top(layout.pos.top);
    if (layout.pos.bottom !== undefined) anchor.bottom(layout.pos.bottom);
    anchor.child(Popup.new(`hover-tip-${key}`, div().w(0).h(0)).anchor(layout.anchor).content(card));
    return opts.wrap ? wrapBox().child(target).child(anchor) : target.relative().child(anchor);
  }
  // An icon with a quiet hover fill; inert and dimmed when it has nothing to do.
  iconButton(id, name, tip, action, t, size = 16, tipOpts = {}) {
    return this.withTip(id, h_flex().id(id).size(32).flex_none().rounded(9).items_center().justify_center().text_color(t.muted)
      .accessibility_label(tip)
      .when(Boolean(action), el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
        .on_click((_e, cx) => { this.hoverKey = ''; action(cx); }))
      .when(!action, el => el.opacity(.4))
      .child(this.icon(name, size)), tip, t, { placement: 'below-right', ...tipOpts });
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
  // Settled items skip the transition wrapper so GPUI doesn't track hundreds of idle transitions.
  fade(el, key, cx) {
    const fresh = Boolean(this.seen && !this.seen.has(key));
    if (fresh) {
      (this.fadingKeys ||= new Set()).add(key);
      if (!this.fading) {
        this.fading = true;
        cx.timer.after(16, cx => {
          this.fading = false;
          this.seen = new Set(this.keys);
          this.fadeClearTimer?.cancel?.();
          this.fadeClearTimer = cx.timer.after(260, () => { this.fadingKeys = null; this.fadeClearTimer = null; });
          cx.notify();
        });
      }
      return el.opacity(0).transition('opacity', FADE);
    }
    if (this.fadingKeys?.has(key)) return el.opacity(1).transition('opacity', FADE);
    return el;
  }

  // An attached file: its kind as an icon and its name, the whole path under the pointer. `remove`
  // gives it a quiet ×; in a sent bubble it has none.
  fileCard(id, path, t, remove, tipOpts = {}) {
    const name = fileName(path);
    return this.withTip(id, h_flex().id(id).h(26).max_w(220).flex_none().pl(8).pr(remove ? 3 : 9).gap(6).rounded(8).items_center()
      .bg(t.raised).text_size(12).text_color(t.muted).accessibility_label(name)
      .child(this.icon(isImage(path) ? 'image' : 'file', 13))
      .child(div().min_w(0).truncate().text_color(t.foreground).child(name))
      .when(Boolean(remove), el => el.child(this.withTip(`${id}-x`, h_flex().id(`${id}-x`).size(20).flex_none().rounded(6).items_center()
        .justify_center().cursor_pointer().text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
        .accessibility_label(word(this.lang, 'removeFile', name))
        .on_click((_e, cx) => { cx.stop_propagation(); remove(cx); })
        .child(this.icon('close', 11)), word(this.lang, 'removeFile', name), t, { placement: 'above-right', ...tipOpts }))),
      path, t, { placement: 'above-left', ...tipOpts });
  }

  mentionRefIcon(kind, target = '') {
    if (kind === 'thread') return 'hook';
    if (kind === 'session') return 'agent';
    if (kind === 'library') {
      if (target.startsWith('research/')) return 'report';
      if (target.startsWith('instructions/')) return 'lock';
      return 'file';
    }
    return isImage(target) ? 'image' : 'file';
  }

  inputMentionChip(tokCtx, t) {
    const tok = tokCtx?.token || {};
    const parsed = parseMentionSpans(tok.text || '')[0] || parseRefLink(tok.id || '');
    const kind = parsed?.kind || 'file';
    const target = parsed?.target || tok.id || '';
    const label = tok.label || (parsed ? `@${parsed.label || fileName(target) || target}` : tok.text || tok.id || '@');
    const chipNum = kind === 'thread' ? formatTaskNumber(this.taskNumberFor(target)) : '';
    const showNum = Boolean(chipNum) && !new RegExp(`^@?${chipNum}(?![0-9])`).test(label);
    const iconName = this.mentionRefIcon(kind, target);
    const tip = word(this.lang, 'mentionOpenRef', target || label);
    return this.withTip(`mention-tok-${target || label}`, h_flex().h(19).max_w(220).px(6).gap(4).rounded(6).items_center().cursor_pointer()
      .bg(tokCtx?.selected ? withAlpha(t.accent, .28) : withAlpha(t.accent, .14))
      .border_1().border_color(tokCtx?.selected ? t.accent : withAlpha(t.accent, .32))
      .text_size(12.5).font_medium().text_color(t.foreground)
      .accessibility_label(label)
      .child(this.icon(iconName, 11.5).text_color(t.accent))
      .when(showNum, el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.muted).child(chipNum)))
      .child(div().min_w(0).truncate().child(label)), tip, t, { placement: 'above-left' });
  }

  mentionRowMark(row, t) {
    if (row.rowKind === 'category') {
      return h_flex().size(22).flex_none().rounded(7).items_center().justify_center()
        .bg(t.raised)
        .child(this.icon(row.icon, 13).text_color(t.muted));
    }
    if (row.kind === 'thread') {
      return h_flex().gap(5).items_center().flex_none()
        .child(h_flex().size(22).flex_none().rounded(7).items_center().justify_center()
          .bg(t.surface).border_1().border_color(t.border)
          .child(this.icon('hook', 12).text_color(row.dimmed ? t.dim : t.muted)))
        .child(this.threadMark(row, t));
    }
    if (row.kind === 'session') {
      const iconEl = !row.program?.icon ? this.icon('agent', 13).text_color(t.dim)
        : row.program.tint ? svg(row.program.icon).size(13).flex_none().text_color(t.foreground)
        : image(row.program.icon).size(13).flex_none();
      return h_flex().gap(5).items_center().flex_none()
        .child(h_flex().size(22).flex_none().rounded(7).items_center().justify_center()
          .bg(t.surface).border_1().border_color(t.border)
          .child(iconEl))
        .child(this.sessionMark(row.sessionStatus, t));
    }
    const glyph = row.kind === 'file' && isImage(row.path) ? 'image' : row.icon;
    return h_flex().size(22).flex_none().rounded(7).items_center().justify_center()
      .bg(t.surface).border_1().border_color(t.border)
      .child(this.icon(glyph, 13).text_color(t.muted));
  }

  mentionPopup(id, which, menu, t) {
    const lang = this.lang;
    const cardW = id === 'say-thread' ? Math.max(240, Math.min(360, panelWidth(this.panelWant, this.viewWidth) - 40)) : 360;
    const children = [];
    if (menu.mode === 'category') {
      children.push(h_flex().id(`${id}-mention-header`).h(28).px(8).pb(4).gap(6).items_center().border_b(1).border_color(t.border)
        .child(this.withTip(`${id}-mention-back`, h_flex().id(`${id}-mention-back`).size(22).flex_none().rounded(6).items_center().justify_center()
          .cursor_pointer().text_color(t.muted).hover(s => s.bg(t.hover).text_color(t.foreground))
          .accessibility_label(word(lang, 'mentionBack'))
          .on_mouse_down('left', (e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); this.mentionPicking = true; cx?.timer?.after?.(250, () => { this.mentionPicking = false; }); })
          .on_click((e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); this.escapeMention(which, cx); })
          .child(this.icon('back', 12)), word(lang, 'mentionBack'), t, { panel: id === 'say-thread', placement: 'above-left' }))
        .child(div().flex_1().min_w(0).truncate().text_size(12).font_semibold().text_color(t.foreground).child(menu.title))
        .when(menu.category === 'files' && this.repoFilesTruncated, el => el.child(div().flex_none().text_size(10.5).text_color(t.dim)
          .child(word(lang, 'mentionFilesTruncated', REPO_FILES_LIMIT)))));
    }
    if (menu.items.length > 0) {
      const listChildren = [];
      menu.items.forEach((row, i) => {
        if (i === menu.dividerBefore) {
          listChildren.push(div().my(4).mx(8).h(1).bg(t.border));
        }
        const selected = i === menu.index;
        const tip = row.rowKind === 'category' ? row.label : (row.subtitle ? `${row.label} · ${row.subtitle}` : row.label);
        const rowEl = h_flex().id(`${id}-mention-row-${i}`).h(32).mx(4).px(8).gap(8).rounded(8).items_center().cursor_pointer()
          .when(selected, el => el.bg(t.raised))
          .when(!selected, el => el.hover(s => s.bg(t.hover)))
          .accessibility_label(tip)
          .on_mouse_down('left', (e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); this.mentionPicking = true; cx?.timer?.after?.(250, () => { this.mentionPicking = false; }); })
          .on_click((e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); this.pickMention(which, row, cx); })
          .child(this.mentionRowMark(row, t));
        if (row.rowKind === 'category') {
          rowEl
            .child(div().flex_1().min_w(0).truncate().text_size(13).font_medium().text_color(t.foreground).child(row.label))
            .child(div().flex_none().text_size(11.5).text_color(t.dim).child(String(row.count)))
            .child(this.icon('chevron', 12).text_color(t.dim));
        } else {
          const rowNum = row.kind === 'thread' ? formatTaskNumber(taskNumber(row) || this.taskNumberFor(row.target)) : '';
          rowEl
            .child(h_flex().flex_1().min_w(0).gap(6).items_center()
              .when(Boolean(rowNum), el => el.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(rowNum)))
              .child(div().min_w(0).truncate().text_size(13).font_medium()
                .text_color(row.dimmed ? t.muted : t.foreground)
                .when(!row.subtitle, s => s.flex_1())
                .when(Boolean(row.subtitle), s => s.max_w(190))
                .child(row.label))
              .when(Boolean(row.subtitle), el => el.child(div().flex_1().min_w(0).truncate().text_size(11.5).text_color(t.dim).child(row.subtitle))))
            .child(div().flex_none().text_size(11).text_color(t.dim).child(row.typeLabel));
        }
        listChildren.push(this.withTip(`${id}-mention-row-${i}`, rowEl, tip, t, { panel: id === 'say-thread', placement: 'above-left' }));
      });
      children.push(v_flex().id(`${id}-mention-list`).max_h(280).pt(menu.mode === 'category' ? 4 : 0).overflow_y_scrollbar()
        .track_scroll(this.mentionScroll)
        .children(listChildren));
    } else if (menu.error) {
      const msg = menu.category === 'files' ? word(lang, 'mentionFilesError', menu.error) : menu.error;
      children.push(div().id(`${id}-mention-error`).px(10).py(8).whitespace_normal().text_size(12).text_color(t.blocked).child(msg));
    } else if (menu.loading) {
      const msg = menu.category === 'files' ? word(lang, 'mentionLoadingFiles') : word(lang, 'libraryLoading');
      children.push(h_flex().id(`${id}-mention-loading`).px(10).py(8).gap(6).items_center().text_size(12).text_color(t.dim)
        .child(svg(SPINNER).size(12).flex_none().spin(900)).child(msg));
    } else if (menu.emptyText) {
      children.push(div().id(`${id}-mention-empty`).px(10).py(8).text_size(12.5).text_color(t.dim).child(menu.emptyText));
    }
    return v_flex().id(`${id}-mention-card`).w(cardW).mb(6).py(6).rounded(12).bg(t.surface)
      .border_1().border_color(t.border).shadow_lg()
      .on_mouse_down('left', (e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); })
      .children(children);
  }

  bindSelectableText(viewEl, source = null) {
    viewEl?.selectable?.(true);
    if (source && !globalThis.__diagnostics) {
      const onSel = viewEl?.['on_selection_change'];
      if (typeof onSel === 'function') {
        onSel.call(viewEl, (sel, cx) => this.onTextSelection(source, sel, cx));
      }
    }
    return viewEl;
  }

  // Do not put `.min_w(0)` or left-mouse-down `stop_propagation()` (`keepPress`) on this wrapper:
  // 1) Inside a shrink-to-fit column (`v_flex` user bubble) probed under Taffy's MinContent pass,
  //    `min_w(0)` clamps cross-axis space to `Definite(0)`, causing GPUI's TextLayout to wrap to
  //    1 char/line and return that cached size on the MaxContent pass.
  // 2) Herdr's ShellRoot paints TextSelectionLayer before mod content; stopping mouse_down
  //    propagation in bubble phase prevents TextSelectionLayer from starting drag-selection.
  // Horizontal flex callers (`h_flex`) add `.flex_1().min_w(0)` at the call site instead.
  selectableText(id, text, source = null, mono = false) {
    const raw = String(text ?? '');
    const viewEl = typeof TextView?.html === 'function'
      ? TextView.html(id, plainTextToHtml(raw))
      : TextView.markdown(id, raw);
    this.bindSelectableText(viewEl, source);
    return div().max_w_full().cursor_text()
      .when(mono, el => el.font_family('monospace'))
      .child(viewEl);
  }

  readClipboard(cx) {
    return typeof cx?.read_from_clipboard === 'function' ? String(cx.read_from_clipboard() || '') : '';
  }

  setHoveredMsg(key, hovered, cx) {
    const next = hovered ? key : (this.hoveredMsg === key ? '' : this.hoveredMsg);
    if (next === this.hoveredMsg) return;
    this.hoveredMsg = next;
    this.hoverClipboard = next ? this.readClipboard(cx) : null;
    if (!hovered && ((this.hoveredPara || '').startsWith(`${key}#p`) || (this.pendingHoverPara || '').startsWith(`${key}#p`))) {
      this.clearParaHoverNow(null);
    }
    cx?.notify?.();
  }

  clearParaHoverNow(cx) {
    this.paraHoverShowTimer?.cancel?.();
    this.paraHoverShowTimer = null;
    this.paraHoverHideTimer?.cancel?.();
    this.paraHoverHideTimer = null;
    this.paraHoverSeq = (this.paraHoverSeq || 0) + 1;
    this.pendingHoverPara = '';
    const had = Boolean(this.hoveredPara);
    this.hoveredPara = '';
    if (had && cx?.notify && cx?.phase?.() !== 'render') cx.notify();
  }

  setHoveredPara(paraKey, hovered, cx) {
    if (!paraKey) return;
    if (hovered) {
      this.paraHoverHideTimer?.cancel?.();
      this.paraHoverHideTimer = null;
      if (this.hoveredPara === paraKey) {
        this.paraHoverShowTimer?.cancel?.();
        this.paraHoverShowTimer = null;
        this.pendingHoverPara = '';
        return;
      }
      this.paraHoverShowTimer?.cancel?.();
      this.paraHoverShowTimer = null;
      const seq = (this.paraHoverSeq = (this.paraHoverSeq || 0) + 1);
      const had = Boolean(this.hoveredPara);
      if (had) this.hoveredPara = '';
      this.pendingHoverPara = paraKey;
      this.paraHoverShowTimer = cx?.timer?.after?.(PARA_HOVER_SHOW_MS, cx => {
        this.paraHoverShowTimer = null;
        if (this.paraHoverSeq === seq && this.pendingHoverPara === paraKey) {
          this.hoveredPara = paraKey;
          this.pendingHoverPara = '';
          cx?.notify?.();
        }
      }) || null;
      if (had) cx?.notify?.();
      return;
    }
    if (this.pendingHoverPara === paraKey) {
      this.paraHoverShowTimer?.cancel?.();
      this.paraHoverShowTimer = null;
      this.paraHoverSeq = (this.paraHoverSeq || 0) + 1;
      this.pendingHoverPara = '';
    }
    if (this.hoveredPara === paraKey) {
      this.paraHoverHideTimer?.cancel?.();
      this.paraHoverHideTimer = null;
      const seq = (this.paraHoverSeq = (this.paraHoverSeq || 0) + 1);
      this.paraHoverHideTimer = cx?.timer?.after?.(PARA_HOVER_HIDE_MS, cx => {
        this.paraHoverHideTimer = null;
        if (this.paraHoverSeq === seq && this.hoveredPara === paraKey) {
          this.hoveredPara = '';
          cx?.notify?.();
        }
      }) || null;
    }
  }

  messageSource(kind, key, rawText, at, today) {
    const author = word(this.lang, kind === 'user' ? 'quoteAuthorYou' : kind === 'question' ? 'quoteAuthorQuestion' : 'quoteAuthorPm');
    return { key, kind, rawText: String(rawText ?? ''), at: String(at || ''), time: at ? clock(at, today) : '', author };
  }

  quoteButton(source, t, { whole = false } = {}) {
    const tip = word(this.lang, whole ? 'quoteWholeMessage' : 'quoteMessage');
    return this.withTip(`quote-btn-${source.key}`, keepPress(h_flex().id(`quote-btn-${source.key}`)).size(24).flex_none().rounded(7).items_center().justify_center()
      .bg(t.surface).border_1().border_color(t.border).text_color(t.muted).cursor_pointer()
      .hover(s => s.bg(t.hover).text_color(t.foreground))
      .accessibility_label(tip)
      .on_click((e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); this.hoverKey = ''; this.quoteFromMessage(source, cx); })
      .child(this.icon('quote', 12.5)), tip, t, { placement: 'above-right' });
  }

  paragraphQuoteButton(source, para, t, { placement = 'above-right' } = {}) {
    const tip = word(this.lang, 'quoteParagraph');
    const btnId = `para-quote-btn-${source.key}-${para.index}`;
    return this.withTip(btnId, keepPress(h_flex().id(btnId)).size(22).flex_none().rounded(6).items_center().justify_center()
      .bg(t.surface).border_1().border_color(t.border).text_color(t.muted).cursor_pointer()
      .hover(s => s.bg(t.hover).border_color(withAlpha(t.accent, .55)).text_color(t.foreground))
      .accessibility_label(tip)
      .on_click((e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); this.hoverKey = ''; this.quoteFromParagraph(source, para, cx); })
      .child(this.icon('quote-paragraph', 12)), tip, t, { placement });
  }

  quoteScopeStyle(q, t) {
    const scope = quoteScope(q);
    const dark = isDarkTheme(t);
    if (scope === 'selection') {
      return {
        icon: 'quote',
        bar: t.accent,
        pillBg: withAlpha(t.accent, dark ? .24 : .16),
        pillText: t.accent,
        strong: true,
      };
    }
    if (scope === 'paragraph') {
      return {
        icon: 'quote-paragraph',
        bar: withAlpha(t.accent, .6),
        pillBg: withAlpha(t.accent, dark ? .15 : .10),
        pillText: t.accent,
        strong: false,
      };
    }
    return {
      icon: 'quote',
      bar: withAlpha(t.muted, .55),
      pillBg: withAlpha(t.muted, dark ? .18 : .12),
      pillText: t.muted,
      strong: false,
    };
  }

  quoteScopeBadge(q, t, id = '') {
    const st = this.quoteScopeStyle(q, t);
    const badge = h_flex().h(17).px(5).rounded(4).flex_none().items_center()
      .bg(st.pillBg).text_color(st.pillText).text_size(10.5)
      .when(st.strong, el => el.font_medium())
      .child(quoteScopeLabel(this.lang, q));
    return id ? badge.id(id) : badge;
  }

  paraGapTop(prevKind, kind) {
    if (!prevKind) return 0;
    if (kind === 'heading') return 10;
    if (prevKind === 'heading') return 3;
    if (prevKind === 'list-item' && kind === 'list-item') return 1;
    return 6;
  }

  cachedParagraphs(text) {
    const raw = String(text ?? '');
    if (!raw || !raw.includes('\n')) return null;
    const cache = (this.paraCache ||= new Map());
    let hit = cache.get(raw);
    if (!hit) {
      const blocks = splitMarkdownParagraphs(raw);
      const multi = blocks.filter(x => x.quotable).length >= 2;
      hit = { blocks, multi };
      if (cache.size >= 256) cache.delete(cache.keys().next().value);
      cache.set(raw, hit);
    }
    return hit;
  }

  decorateQuoteMarkdown(md) {
    const src = String(md ?? '');
    if (!src || !src.includes('](thread:')) return src;
    return decorateThreadLinks(src, this.projectTasks(), this.state.task_numbers || null, {
      retiredParts: this.state.retired_parts || [],
      events: Array.isArray(this.events) ? this.events : [],
    });
  }

  quoteFromMessage(source, cx) {
    if (!source) return false;
    const clip = this.readClipboard(cx);
    const baseline = (this.hoveredMsg === source.key && this.hoverClipboard !== null) ? this.hoverClipboard : clip;
    const displayText = this.decorateQuoteMarkdown(source.rawText);
    const picked = extractClipboardQuote(clip, source.rawText, { baseline, displayText });
    if (!picked.text) return false;
    if (picked.exact && this.hoveredMsg === source.key) this.hoverClipboard = clip;
    const range = picked.exact ? locateQuoteRange(source.rawText, picked.text) : null;
    this.addQuote({
      id: `${source.key}#${picked.exact ? 'sel' : 'all'}#${++this.quoteSeq}`,
      targetKey: source.key,
      kind: source.kind,
      author: source.author,
      at: source.at,
      time: source.time,
      text: picked.text,
      scope: picked.exact ? 'selection' : 'message',
      exact: picked.exact,
      ...(range ? { range } : {}),
    }, cx);
    return true;
  }

  quoteFromParagraph(source, para, cx) {
    if (!source || (!para?.text && !para?.markdown)) return false;
    let text = para.text || '';
    if (para.kind !== 'code' && typeof para.markdown === 'string' && para.markdown.includes('](thread:')) {
      const decorated = this.decorateQuoteMarkdown(para.markdown);
      text = markdownToPlain(decorated) || decorated.trim() || text;
    }
    if (!text) return false;
    this.addQuote({
      id: `${source.key}#p${para.index}#${++this.quoteSeq}`,
      targetKey: source.key,
      kind: source.kind,
      author: source.author,
      at: source.at,
      time: source.time,
      text,
      scope: 'paragraph',
      range: { start: para.start, end: para.end, paragraph: para.index, kind: para.kind },
    }, cx);
    return true;
  }

  addQuote(quote, cx) {
    const next = withQuote(this.quotes, quote);
    if (next === this.quotes) return;
    this.quotes = next;
    this.selectionBar = null;
    if (this.mainKey) this.keep(this.mainKey, this.draft, this.files, undefined, this.quotes);
    this.input?.focus?.();
    cx?.notify?.();
  }

  removeQuote(id, cx) {
    this.quotes = withoutQuote(this.quotes, id);
    if (this.mainKey) this.keep(this.mainKey, this.draft, this.files, undefined, this.quotes);
    cx?.notify?.();
  }

  // Seam invoked when Herdr TextView emits native selection changes (`{ text, bounds, range? }`).
  onTextSelection(source, selection, cx) {
    const resolved = (!selection?.range && source?.rawText && selection?.text)
      ? { ...selection, range: locateQuoteRange(source.rawText, selection.text) }
      : selection;
    this.selectionBar = selectionToolbarState(resolved, source);
    cx?.notify?.();
  }

  acceptSelectionQuote(cx) {
    if (!this.selectionBar) return false;
    const { text, source, range } = this.selectionBar;
    this.addQuote({
      id: `${source.key}#sel#${++this.quoteSeq}`,
      targetKey: source.key,
      kind: source.kind,
      author: source.author || word(this.lang, source.kind === 'user' ? 'quoteAuthorYou' : source.kind === 'question' ? 'quoteAuthorQuestion' : 'quoteAuthorPm'),
      at: source.at,
      time: source.time,
      text,
      scope: 'selection',
      exact: true,
      ...(range ? { range } : {}),
    }, cx);
    return true;
  }

  selectionPopover(t) {
    if (!this.selectionBar) return null;
    const quoteTip = word(this.lang, 'quoteSelectionAction');
    const closeTip = word(this.lang, 'dismissNotice');
    return keepPress(h_flex().id('selection-quote-bar')).px(6).py(4).gap(4).rounded(10).items_center()
      .bg(t.surface).border_1().border_color(t.border).shadow_md()
      .child(this.withTip('selection-quote-btn', h_flex().id('selection-quote-btn').size(26).rounded(7).items_center().justify_center()
        .cursor_pointer().text_color(t.foreground).hover(s => s.bg(t.hover))
        .accessibility_label(quoteTip)
        .on_click((e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); this.acceptSelectionQuote(cx); })
        .child(this.icon('quote', 13)), quoteTip, t, { placement: 'above-left' }))
      .child(this.withTip('selection-quote-close', h_flex().id('selection-quote-close').size(22).rounded(6).items_center().justify_center()
        .cursor_pointer().text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
        .accessibility_label(closeTip)
        .on_click((e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); this.selectionBar = null; cx?.notify?.(); })
        .child(this.icon('close', 11)), closeTip, t, { placement: 'above-right' }));
  }

  jumpToMessage(targetKey, cx, range = null) {
    const blocks = this.lastBlocks || [];
    const row = blockIndexForKey(blocks, targetKey);
    if (row < 0) return false;
    const part = blocks[row]?.parts?.find(p => p?.key === targetKey);
    if (part?.kind === 'pm' && part.long) this.unfolded.set(targetKey, true);
    this.flash = targetKey;
    const paraFlashKey = Number.isInteger(range?.paragraph) && range.paragraph >= 0 ? `${targetKey}#p${range.paragraph}` : '';
    this.flashPara = paraFlashKey;
    cx?.timer?.after?.(1500, cx => {
      let changed = false;
      if (this.flash === targetKey) { this.flash = ''; changed = true; }
      if (paraFlashKey && this.flashPara === paraFlashKey) { this.flashPara = ''; changed = true; }
      if (changed) cx?.notify?.();
    });
    this.rest(riseAfterJump(this.rise, this.lastHeights || [], row, this.lastTall || this.high, TAIL));
    this.scroll?.scroll_to_item?.((this.lastTopOffset || 0) + row);
    cx?.notify?.();
    return true;
  }

  renderMentionText(idPrefix, text, t, cx, source = null) {
    const parsed = splitMentionSegments(text);
    if (!parsed.hasMentions) return this.selectableText(`${idPrefix}-txt`, text, source);
    const rows = [];
    let groupLines = [];
    let groupStart = 0;
    const flushGroup = () => {
      if (!groupLines.length) return;
      const joined = groupLines.join('\n');
      rows.push(this.selectableText(`${idPrefix}-g-${groupStart}`, joined || ' ', source));
      groupLines = [];
    };
    parsed.lines.forEach((line, li) => {
      if (!line.hasMentions) {
        if (!groupLines.length) groupStart = li;
        groupLines.push(line.segments[0]?.text || '');
        return;
      }
      flushGroup();
      rows.push(h_flex().w_full().flex_wrap().items_center().gap_x(3).gap_y(3).children(line.segments.map((seg, si) => {
        if (seg.type === 'text') {
          return this.selectableText(`${idPrefix}-t-${li}-${si}`, seg.text, source);
        }
        const segNum = seg.kind === 'thread' ? formatTaskNumber(this.taskNumberFor(seg.target)) : '';
        const showSegNum = Boolean(segNum) && !new RegExp(`^@?${segNum}(?![0-9])`).test(seg.label || '');
        const tip = word(this.lang, 'mentionOpenRef', seg.target);
        return this.withTip(`${idPrefix}-m-${li}-${si}`, h_flex().id(`${idPrefix}-m-${li}-${si}`).h(21).max_w_full().px(6).gap(4).rounded(6).items_center().cursor_pointer()
          .bg(withAlpha(t.accent, .14)).border_1().border_color(withAlpha(t.accent, .32))
          .hover(s => s.bg(withAlpha(t.accent, .24)))
          .accessibility_label(`@${seg.label}`)
          .on_click((e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); this.openMentionRef(seg, cx); })
          .child(this.icon(this.mentionRefIcon(seg.kind, seg.target), 11.5).text_color(t.accent))
          .when(showSegNum, el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.muted).child(segNum)))
          .child(div().min_w(0).truncate().text_size(12.5).font_medium().text_color(t.foreground).child(`@${seg.label}`)),
          tip, t, { panel: idPrefix.startsWith('session-'), placement: 'above-left' });
      })));
    });
    flushGroup();
    return v_flex().w_full().gap(2).children(rows);
  }

  composer(id, state, draft, enabled, placeholder, offlineTip, onSend, t, radius, raised = false, cx = null) {
    const which = id === 'say' ? 'main' : 'thread', files = this.filesOf(which);
    const quotes = which === 'main' ? (this.quotes || []) : [];
    const ready = enabled && Boolean(draft?.trim() || files.length || quotes.length);
    const failed = this.attachError && this.attachError.key === this.keyOf(which) ? this.attachError.text : '';
    const mentionOpen = enabled && this.mentionOpenFor(which);
    const menu = mentionOpen ? this.mentionMenuFor(which) : null;
    // The project's box answering a question card: a small mark of that card's thread above the words,
    // whose close icon (or Esc) stops it; the placeholder asks for the answer.
    const answering = which === 'main' ? this.answering : null;
    if (answering) placeholder = word(this.lang, 'ownAnswer');
    const ansNum = formatTaskNumber(taskNumber(answering) || this.taskNumberFor(answering?.task || answering?.key?.replace?.(/^ask:/, '')));
    const inPanel = id === 'say-thread';
    const mark = answering ? h_flex().pt(8).pr(10).child(this.withTip(`${id}-answering`, h_flex().id(`${id}-answering`).h(24).max_w(320).pl(8).pr(3)
      .gap(6).rounded(8).items_center().bg(t.raised).text_size(12).text_color(t.muted)
      .accessibility_label(word(this.lang, 'answeringTo', answering.title))
      .child(this.icon('pencil', 12))
      .when(Boolean(ansNum), el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(ansNum)))
      .child(div().min_w(0).truncate().text_color(t.foreground).child(answering.title))
      .child(this.withTip(`${id}-answering-x`, h_flex().id(`${id}-answering-x`).size(18).flex_none().rounded(6).items_center().justify_center()
        .cursor_pointer().text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
        .accessibility_label(word(this.lang, 'stopAnswering'))
        .on_click((_e, cx) => { cx.stop_propagation(); this.answering = null; this.input.focus(); cx.notify(); })
        .child(this.icon('close', 10)), word(this.lang, 'stopAnswering'), t, { panel: inPanel, placement: 'above-right' })),
      word(this.lang, 'answeringTo', answering.title), t, { panel: inPanel, placement: 'above-left' })) : null;
    const quoteBar = quotes.length ? v_flex().id(`${id}-quotes`).w_full().pt(8).pr(10).gap(4)
      .when(quotes.length > 3, el => el.max_h(116).overflow_y_scrollbar())
      .children(quotes.map((q, qi) => {
        const from = word(this.lang, 'quoteFrom', q.author || word(this.lang, 'quoteAuthorPm'), q.time);
        const scopeTip = quoteScopeTip(this.lang, q);
        const st = this.quoteScopeStyle(q, t);
        const tip = [`${from} · ${scopeTip}`, q.text].filter(Boolean).join('\n');
        return this.withTip(`${id}-quote-${qi}`, h_flex().id(`${id}-quote-${qi}`).w_full().h(28).pl(9).pr(4).gap(6).rounded(8).items_center()
          .bg(t.raised).border_l(2).border_color(st.bar)
          .accessibility_label(tip)
          .cursor_pointer().hover(s => s.bg(t.hover))
          .on_click((_e, cx) => this.jumpToMessage(q.targetKey, cx, q.range))
          .child(this.icon(st.icon, 12).flex_none().text_color(t.muted))
          .child(this.quoteScopeBadge(q, t, `${id}-quote-scope-${qi}`))
          .child(div().flex_1().min_w(0).truncate().text_size(12).text_color(t.foreground).child(quotePreviewLine(q.text)))
          .child(this.withTip(`${id}-quote-x-${qi}`, h_flex().id(`${id}-quote-x-${qi}`).size(18).flex_none().rounded(6).items_center().justify_center()
            .cursor_pointer().text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
            .accessibility_label(word(this.lang, 'quoteRemove'))
            .on_click((e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); this.removeQuote(q.id, cx); })
            .child(this.icon('close', 10)), word(this.lang, 'quoteRemove'), t, { panel: inPanel, placement: 'above-right' })),
          tip, t, { panel: inPanel, placement: 'above-left' });
      })) : null;
    // The placeholder sits under the textarea while it is empty (its words change with the project and language).
    const hint = div().absolute().left(0).top(11).right(0).truncate().text_size(14).text_color(t.dim).child(placeholder);
    const field = enabled
      ? div().relative().flex_1().min_w(0).py(11).when(!draft, el => el.child(hint))
        .child(Textarea.new(state).w_full().text_size(14).text_color(t.foreground)
          .token((tokCtx, _cx) => this.inputMentionChip(tokCtx, t))
          .on_token_click((ev, cx) => { if (ev?.token) this.openMentionRef(ev.token, cx); }))
      : div().flex_1().min_w(0).py(11).text_size(14).text_color(t.dim).truncate().child(placeholder);
    // The files go above the words, as in the bubble they are sent in; one that did not attach is a red mark there.
    const cards = files.length || failed ? h_flex().flex_wrap().gap(6).pt(8).pr(10)
      .children(files.map((path, i) => this.fileCard(`${id}-file-${i}`, path, t, cx => this.detach(which, path, cx), { panel: inPanel })))
      .when(Boolean(failed), el => el.child(this.withTip(`${id}-attach-error`, h_flex().id(`${id}-attach-error`).h(26).px(9).rounded(8).items_center()
        .bg(withAlpha(t.blocked, .14)).text_color(t.blocked).text_size(12.5).font_semibold()
        .accessibility_label(word(this.lang, 'attachFailed', failed))
        .child('!'), word(this.lang, 'attachFailed', failed), t, { panel: inPanel, placement: 'above-left' }))) : null;
    // A project on another machine takes files too: its tooltip says they are copied there on sending.
    const clipTip = this.machine ? word(this.lang, 'remoteAttach', this.machine) : word(this.lang, 'attach');
    const clip = this.withTip(`${id}-attach`, h_flex().id(`${id}-attach`).size(32).mb(6).flex_none().rounded(9).items_center().justify_center()
      .text_color(t.muted).accessibility_label(clipTip)
      .when(enabled, el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
        .on_click((_e, cx) => this.pickFiles(which, cx)))
      .child(this.icon('clip', 16)), clipTip, t, { panel: inPanel, placement: 'above-right' });
    // The box keeps its presses without the page's keyboard: its textarea takes the keyboard itself.
    const boxRaw = keepPress(v_flex().id(id)).w_full().pl(16).pr(6).py(4).rounded(radius)
      .bg(t.surface).border_1().border_color(enabled ? t.input || t.border : t.border)
      .when(!enabled, el => el.opacity(.6).cursor_not_allowed())
      .when(Boolean(menu), el => el.key_context('PmMentionOpen')
        .on_action('pm-mention-up', (_e, cx) => { cx.stop_propagation?.(); this.consumeMentionKey(cx); this.moveMention(which, -1, cx); })
        .on_action('pm-mention-down', (_e, cx) => { cx.stop_propagation?.(); this.consumeMentionKey(cx); this.moveMention(which, 1, cx); })
        .on_action('pm-mention-accept', (_e, cx) => { cx.stop_propagation?.(); this.consumeMentionKey(cx); this.acceptMention(which, cx); })
        .on_action('pm-mention-escape', (_e, cx) => { cx.stop_propagation?.(); this.consumeMentionKey(cx); this.escapeMention(which, cx); }))
      .on_key_down((e, cx) => {
        if (!enabled) return;
        if (this.mentionOpenFor(which) && !this.mentionConsumedKey) {
          if (e.keystroke === 'up') { cx.stop_propagation?.(); this.consumeMentionKey(cx); this.moveMention(which, -1, cx); return; }
          if (e.keystroke === 'down') { cx.stop_propagation?.(); this.consumeMentionKey(cx); this.moveMention(which, 1, cx); return; }
          if (e.keystroke === 'tab' || e.keystroke === 'enter') { cx.stop_propagation?.(); this.consumeMentionKey(cx); this.acceptMention(which, cx); return; }
          if (e.keystroke === 'escape') { cx.stop_propagation?.(); this.consumeMentionKey(cx); this.escapeMention(which, cx); return; }
        }
        if (e.keystroke === 'enter' && !this.mentionConsumedKey) { cx.stop_propagation?.(); onSend(cx); }
      })
      // Files dragged from Finder (or anywhere) onto the box.
      .when(enabled, el => el.on_drop((e, cx) => this.attach(this.keyOf(which), e?.paths || [], cx)))
      .when(Boolean(mark), el => el.child(mark))
      .when(Boolean(quoteBar), el => el.child(quoteBar))
      .when(Boolean(cards), el => el.child(cards))
      .child(h_flex().w_full().items_end().gap(2)
      .child(field)
      .child(clip)
      .child(this.withTip(`${id}-send`, h_flex().id(`${id}-send`).size(44).flex_none().items_center().justify_center()
        .when(ready, el => el.cursor_pointer().on_click((_e, cx) => onSend(cx)))
        .accessibility_label(word(this.lang, id === 'say' ? 'send' : 'sendThread'))
        .child(h_flex().size(30).rounded(15).items_center().justify_center()
          .bg(ready ? t.solid : t.raised).text_color(ready ? t.solid_foreground : t.muted)
          .child(this.icon('send', 15))), enabled ? word(this.lang, id === 'say' ? 'send' : 'sendThread') : offlineTip, t, { panel: inPanel, placement: 'above-right' })));
    const box = !enabled ? this.withTip(`${id}-offline`, boxRaw, offlineTip, t, { panel: inPanel, placement: 'above-left' }) : boxRaw;
    const surface = raised ? this.lift(box, t, radius) : box;
    return Popup.new(`${id}-mention-popup`, surface).anchor('bottom_left')
      .when(Boolean(menu), el => el.content(this.mentionPopup(id, which, menu, t)));
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
    const numText = formatTaskNumber(taskNumber(row) || this.taskNumberFor(row.task));
    const tip = [statusLabel(this.lang, row.status, row.cleanup, row.offline, row.answered, Boolean(row.termClosed)), numText ? `${numText} ${row.title}` : row.title].join(' · ');
    return this.withTip(`thread-${row.task}`, h_flex().id(`thread-${row.task}`).h(24).gap(8).items_center().cursor_pointer().text_size(13)
      .text_color(selected ? t.foreground : row.closed ? t.dim : t.muted).hover(s => s.text_color(t.foreground))
      .accessibility_label(tip)
      .on_click((_e, cx) => this.openThread(row.task, cx))
      .child(svg(ICON('hook')).size(14).flex_none().text_color(t.dim))
      .when(Boolean(numText), el => el.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(numText)))
      .child(div().min_w(0).truncate().child(row.title))
      // In progress: the dots breathe only while its own worker is at work, and rest dim otherwise.
      .when(row.tone === 'running', el => el.child(atWork.has(row.task) ? this.workingDots(t)
        : h_flex().flex_none().gap(3).items_center().opacity(.4).children([0, 1, 2].map(() => div().size(4).rounded_full().bg(t.muted)))))
      .when(row.tone === 'blocked' || row.tone === 'review', el => el.child(div().flex_none().size(6).rounded_full()
        .bg(this.toneColor(row.tone, t)))), tip, t, { placement: 'above-left' });
  }
  // The name of a thread the reply under it is about.
  aboutLine(item, t) {
    const selected = this.detail && this.thread === item.task;
    const numText = formatTaskNumber(taskNumber(item) || this.taskNumberFor(item.task));
    return this.withTip(`about-${item.key}`, h_flex().id(`about-${item.key}`).h(20).gap(8).items_center().cursor_pointer().text_size(12.5)
      .text_color(selected ? t.foreground : t.dim).hover(s => s.text_color(t.foreground))
      .accessibility_label(item.title)
      .on_click((_e, cx) => this.openThread(item.task, cx))
      .child(svg(ICON('hook-up')).size(14).flex_none().text_color(t.dim))
      .when(Boolean(numText), el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(numText)))
      .child(div().min_w(0).truncate().child(item.title)), word(this.lang, 'openThread'), t, { placement: 'above-left' });
  }

  // The coordinator asking: a quiet card with the thread's name, the question, and its answers as
  // rows (a letter, the answer, why, and a mark on the one the coordinator recommends). Picking one
  // sends it and leaves that row alone with a check; a question answered in the user's own words
  // keeps only its text. A question that waits ends with one more row, its "own words": a pencil
  // and a prompt, which sets the project's box to answer this card (see answering).
  question(item, t, cx, today = '') {
    // Stale worker blocked card taken over / resolved by the PM: collapse to a quiet single-line strip
    // so the user never sees a dead error card or tries to answer something already handled.
    if (item.handledByPm && !item.open && item.chosen < 0 && !item.answered) {
      return this.withTip(`handled-${item.key}`, h_flex().id(`handled-${item.key}`).max_w(560).px(10).py(5).gap(6).rounded(8).items_center()
        .border_1().border_color(t.border)
        .child(this.icon('check', 13).flex_none().text_color(t.dim))
        .child(this.withTip(`ask-${item.key}`, h_flex().id(`ask-${item.key}`).gap(4).items_center().min_w(0).cursor_pointer().text_size(12)
          .text_color(t.muted).hover(s => s.text_color(t.foreground))
          .accessibility_label(item.title)
          .on_click((_e, cx) => this.openThread(item.task, cx))
          .child(div().min_w(0).truncate().child(item.title)).child(this.icon('chevron', 12)), word(this.lang, 'openThread'), t, { placement: 'above-left' }))
        .child(div().flex_none().text_size(11.5).text_color(t.dim).child('·'))
        .child(div().flex_none().text_size(11.5).text_color(t.dim).child(word(this.lang, 'handledByPm'))),
        item.text || word(this.lang, 'handledByPm'), t, { placement: 'above-left' });
    }
    // Answered in the user's own words (item.answered, see answeredTasks): settled as a picked one is,
    // its answer is the bubble after it.
    const picked = item.chosen >= 0, asking = item.open && !picked && !item.answered;
    const rows = picked ? [this.optionRow(item, item.chosen, t, true)] : asking ? this.answerRows(item, t) : [];
    const qSource = item.text ? this.messageSource('question', item.key, item.text, item.at, today) : null;
    const hovered = Boolean(qSource && this.hoveredMsg === item.key);
    const qParsed = qSource ? this.cachedParagraphs(item.text) : null;
    const qBlocks = qParsed?.blocks || [];
    const qMulti = Boolean(qParsed?.multi);
    const qDark = isDarkTheme(t);
    // The thread's name opens the thread; its color is the row's, so it brightens under the pointer.
    const numText = formatTaskNumber(taskNumber(item) || this.taskNumberFor(item.task));
    const name = this.withTip(`ask-${item.key}`, h_flex().id(`ask-${item.key}`).gap(4).items_center().cursor_pointer().text_size(12)
      .text_color(t.dim).hover(s => s.text_color(t.foreground))
      .accessibility_label(item.title)
      .on_click((_e, cx) => this.openThread(item.task, cx))
      .when(Boolean(numText), el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(numText)))
      .child(div().min_w(0).truncate().child(item.title)).child(this.icon('chevron', 12)), word(this.lang, 'openThread'), t, { placement: 'above-left' });
    const qBody = qMulti
      ? v_flex().w_full().children(qBlocks.map((seg, bi) => {
          const mt = this.paraGapTop(bi > 0 ? qBlocks[bi - 1].kind : '', seg.kind);
          if (!seg.quotable) {
            return div().w_full().when(mt > 0, el => el.mt(mt)).child(this.selectableText(`q-txt-${item.key}-b${bi}`, seg.markdown, qSource).w_full().text_color(asking ? t.foreground : t.muted));
          }
          const paraKey = `${item.key}#p${seg.index}`;
          const paraActive = this.hoveredPara === paraKey;
          const paraFlashed = this.flashPara === paraKey;
          return h_flex().id(`para-${item.key}-${seg.index}`).w_full().when(mt > 0, el => el.mt(mt)).items_start().gap(4)
            .pl(6).pr(2).py(2).rounded(6).border_l(2)
            .border_color(paraFlashed ? t.accent : paraActive ? withAlpha(t.accent, .5) : '#00000000')
            .when(paraFlashed, el => el.bg(withAlpha(t.accent, qDark ? .14 : .10)))
            .when(!paraFlashed && paraActive, el => el.bg(withAlpha(t.foreground, qDark ? .04 : .035)))
            .on_hover((over, cx) => this.setHoveredPara(paraKey, over, cx))
            .child(this.selectableText(`q-txt-${item.key}-p${seg.index}`, seg.markdown, qSource).flex_1().min_w(0).text_color(asking ? t.foreground : t.muted))
            .child(h_flex().id(`para-quote-slot-${item.key}-${seg.index}`).w(22).h(22).flex_none().justify_end()
              .when(paraActive, el => el.child(this.paragraphQuoteButton(qSource, seg, t))));
        }))
      : this.selectableText(`q-txt-${item.key}`, item.text, qSource).w_full().text_color(asking ? t.foreground : t.muted);
    const card = v_flex().id(`question-msg-${item.key}`).w_full().p(6).gap(2).rounded(14).border_1()
      .when(Boolean(qSource), el => el.on_hover((h, cx) => this.setHoveredMsg(item.key, h, cx)))
      .child(v_flex().px(10).pt(6).pb(rows.length ? 6 : 4).gap(3)
        .child(h_flex().w_full().min_h(24).items_center().justify_between().gap(6)
          .child(name)
          .when(hovered, el => el.child(this.quoteButton(qSource, t, { whole: qMulti }))))
        .child(qBody))
      .children(rows);
    // A question that waits is a lifted surface with the message box's border; one that is settled
    // is an outline on the canvas, so the two differ in a light theme too.
    // The one the bell just went to has the bell's color around it for a moment; search jumps use accent.
    const edge = this.flash === item.key ? (this.flashTone === 'accent' ? t.accent : t.blocked) : asking ? t.input || t.border : t.border;
    return div().w_full().max_w(560).child(asking ? this.lift(card.bg(t.surface).border_color(edge), t, 14)
      : card.border_color(edge));
  }

  // A question's answers, while it waits (a card's, or a thread detail's, see threadQuestion): its options
  // as rows, then its "own words" row. q: {key, title, options, notes, recommended, recommendedIndex?}; at: a prefix for
  // the rows' ids, as one question can show in the conversation and in its thread's detail at once.
  answerRows(q, t, at = '') {
    return [...q.options.map((_o, i) => this.optionRow(q, i, t, false, at)), this.ownRow(q, t, at)];
  }
  // One answer: a letter, the answer, why, and a highlighted treatment on the one the coordinator recommends.
  // Picking it sends answerText(title, option) tagged with the question's key; the picked one keeps a check.
  optionRow(q, i, t, chosen = false, at = '') {
    const sending = this.pending.some(p => p.question === q.key && !p.failed);
    const live = Boolean(this.pmTerminal()) && !sending;
    const recIdx = Number.isInteger(q.recommendedIndex) ? q.recommendedIndex : 0;
    const rec = Boolean(q.recommended) && i === recIdx;
    const row = h_flex().id(`${at}opt-${q.key}-${i}`).px(10).py(9).gap(12).rounded(10).items_center()
      .when(rec && !chosen, el => el.bg(withAlpha(t.accent, .08)).border_1().border_color(withAlpha(t.accent, .28)))
      .child(h_flex().size(28).flex_none().rounded(7).items_center().justify_center()
        .bg(chosen ? t.hover : rec ? withAlpha(t.accent, .18) : t.raised)
        .text_size(12.5).font_medium().text_color(rec && !chosen ? t.accent : t.muted).child(String.fromCharCode(65 + i)))
      .child(v_flex().flex_1().min_w(0).gap(1)
        .child(h_flex().gap(8).items_center()
          .child(div().min_w(0).whitespace_normal().text_color(t.foreground).when(rec && !chosen, el => el.font_medium()).child(q.options[i]))
          .when(rec, el => el.child(h_flex().flex_none().h(18).px(6).rounded(5).items_center()
            .bg(withAlpha(t.accent, .16)).text_color(t.accent).text_size(11).font_medium().child(word(this.lang, 'recommended')))))
        .when(Boolean(q.notes[i]), el => el.child(div().whitespace_normal().text_size(12.5).text_color(t.muted).child(q.notes[i]))));
    if (chosen) return row.bg(t.raised).child(this.icon('check', 16).text_color(t.muted));
    if (!live) return this.withTip(`${at}opt-${q.key}-${i}`, row.opacity(.5), word(this.lang, sending ? 'sending' : 'offline'), t, { panel: Boolean(at), placement: 'above-left' });
    return row.cursor_pointer().hover(s => s.bg(rec ? withAlpha(t.accent, .14) : t.hover))
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
    return !this.pmTerminal() ? this.withTip(`${at}own-${q.key}`, own.opacity(.5), word(this.lang, 'offline'), t, { panel: Boolean(at), placement: 'above-left' })
      : own.cursor_pointer().when(on, el => el.bg(t.raised)).hover(s => s.bg(t.hover))
        .on_click((_e, cx) => this.answerInOwnWords(q, cx));
  }

  // What one item of a coordinator turn looks like.
  turnPart(item, t, cx, today = '') {
    if (item.kind === 'pm') {
      const pmSource = this.messageSource('pm', item.key, item.text, item.at, today);
      const hovered = this.hoveredMsg === item.key;
      const flashed = this.flash === item.key;
      const dark = isDarkTheme(t);
      const open = !item.long || (this.unfolded.has(item.key) ? this.unfolded.get(item.key) : item.key === this.newest);
      let multiPara = false;
      let bodyNode;
      if (!open) {
        // Selectable folded opening beside a separate expand icon control so drag-selecting does not toggle unfold.
        bodyNode = h_flex().w_full().pt(3).gap(6).items_end()
          .child(this.selectableText(`lead-${item.key}`, item.lead, pmSource).flex_1().min_w(0).text_size(14).text_color(t.foreground))
          .child(this.withTip(`unfold-${item.key}`, keepPress(h_flex().id(`unfold-${item.key}`)).px(4).flex_none().cursor_pointer()
            .text_color(t.dim).hover(s => s.text_color(t.foreground))
            .accessibility_label(word(this.lang, 'unfold'))
            .on_click((_e, cx) => { this.unfolded.set(item.key, true); cx.notify(); })
            .child(h_flex().h(21).flex_none().items_center().child(this.icon('expand', 15))), word(this.lang, 'unfold'), t, { placement: 'above-right' }));
      } else {
        // Split canonical raw `item.text` BEFORE decorating thread links so paragraph `{ start, end }`
        // coordinates stay in the exact same coordinate system as `locateQuoteRange` and future #1335 selections.
        const rawText = String(item.text ?? '');
        const tasks = this.projectTasks();
        const parsed = this.cachedParagraphs(rawText);
        const paraBlocks = parsed?.blocks || [];
        multiPara = Boolean(parsed?.multi);
        let wholeNode;
        if (!multiPara) {
          const md = this.formattedPmMarkdown(rawText, tasks);
          wholeNode = div().w_full().pt(3).cursor_text().text_size(14).text_color(t.foreground)
            .child(this.bindSelectableText(
              TextView.markdown(`md-${item.key}`, md).on_link_click((url, cx) => this.followLink(url, cx)),
              pmSource,
            ));
        } else {
          wholeNode = v_flex().w_full().pt(3).children(paraBlocks.map((seg, bi) => {
            const mt = this.paraGapTop(bi > 0 ? paraBlocks[bi - 1].kind : '', seg.kind);
            const displayMd = this.formattedPmMarkdown(seg.markdown, tasks);
            if (!seg.quotable) {
              return div().w_full().when(mt > 0, el => el.mt(mt))
                .child(TextView.markdown(`md-${item.key}-b${bi}`, displayMd));
            }
            const paraKey = `${item.key}#p${seg.index}`;
            const paraActive = this.hoveredPara === paraKey;
            const paraFlashed = this.flashPara === paraKey;
            return h_flex().id(`para-${item.key}-${seg.index}`).w_full().when(mt > 0, el => el.mt(mt)).items_start().gap(4)
              .pl(6).pr(2).py(2).rounded(6).border_l(2)
              .border_color(paraFlashed ? t.accent : paraActive ? withAlpha(t.accent, .5) : '#00000000')
              .when(paraFlashed, el => el.bg(withAlpha(t.accent, dark ? .14 : .10)))
              .when(!paraFlashed && paraActive, el => el.bg(withAlpha(t.foreground, dark ? .04 : .035)))
              .on_hover((over, cx) => this.setHoveredPara(paraKey, over, cx))
              .child(div().flex_1().min_w(0).cursor_text().text_size(14).text_color(t.foreground)
                .child(this.bindSelectableText(
                  TextView.markdown(`md-${item.key}-p${seg.index}`, displayMd).on_link_click((url, cx) => this.followLink(url, cx)),
                  pmSource,
                )))
              .child(h_flex().id(`para-quote-slot-${item.key}-${seg.index}`).w(22).h(22).flex_none().justify_end()
                .when(paraActive, el => el.child(this.paragraphQuoteButton(pmSource, seg, t))));
          }));
        }
        // A long reply shows its opening paragraph until it is opened. The newest one is open, and so
        // stays every reply that arrived while this project was on screen: history folds, the live
        // conversation does not move under the reader.
        bodyNode = (!item.long || item.key === this.newest)
          ? wholeNode
          : v_flex().w_full().child(wholeNode)
            .child(h_flex().child(this.withTip(`fold-${item.key}`, keepPress(h_flex().id(`fold-${item.key}`)).pr(8).cursor_pointer()
              .text_color(t.dim).hover(s => s.text_color(t.foreground))
              .accessibility_label(word(this.lang, 'fold'))
              .on_click((_e, cx) => { this.unfolded.set(item.key, false); cx.notify(); })
              .child(h_flex().h(21).flex_none().items_center().child(this.icon('collapse', 15))), word(this.lang, 'fold'), t, { placement: 'above-left' })));
      }
      return h_flex().id(`pm-msg-${item.key}`).w_full().items_start().gap(6)
        .when(flashed && !this.flashPara, el => el.px(10).py(6).rounded(10)
          .bg(withAlpha(t.accent, dark ? .14 : .10))
          .border_1().border_color(withAlpha(t.accent, .55)))
        .on_hover((h, cx) => this.setHoveredMsg(item.key, h, cx))
        .child(div().flex_1().min_w(0).child(bodyNode))
        .child(h_flex().id(`pm-quote-slot-${item.key}`).w(24).h(26).flex_none().pt(2).justify_end()
          .when(hovered, el => el.child(this.quoteButton(pmSource, t, { whole: open && multiPara }))));
    }
    if (item.kind === 'decision') {
      const flashed = this.flash === item.key;
      const decEl = h_flex().id(`decision-${item.key}`).gap(7).items_center().text_size(12.5)
        .text_color(flashed ? t.foreground : t.dim)
        .when(flashed, el => el.px(8).py(4).rounded(8)
          .bg(withAlpha(t.accent, isDarkTheme(t) ? .16 : .11))
          .border_1().border_color(withAlpha(t.accent, .55)))
        .child(this.icon('check', 14).when(flashed, ic => ic.text_color(t.accent)))
        .child(this.selectableText(`dec-txt-${item.key}`, item.text).flex_1().min_w(0));
      return item.quote ? this.withTip(`decision-${item.key}`, decEl, `“${item.quote}”`, t, { placement: 'above-left' }) : decEl;
    }
    if (item.kind === 'threads') return v_flex().w_full().children(item.rows.map(row => this.threadLine(row, t, this.atWork)));
    if (item.kind === 'about') return this.aboutLine(item, t);
    if (item.kind === 'question') return this.question(item, t, cx, today);
    // typing: the coordinator is at work (quiet live activity + stall recovery actions).
    const pmTermNow = this.pmTerminal();
    const rawActView = pmActivityView(this.lang, {
      turn: this.activePmTurn(),
      working: this.isPmWorking(pmTermNow, this.live(), this.activePmTurn()),
      pendingSending: this.pending.some(p => !p.failed && !p.queued && !p.received),
      nowMs: this.nowMs(),
      serverNowMs: this.serverNowMs || 0,
      receivedAtMs: this.serverNowAt || 0,
    });
    const actView = rawActView && typeof rawActView === 'object'
      ? rawActView
      : { mode: 'dots', label: '', stalled: false, canInterrupt: false, canRotate: false };
    const dotsEl = h_flex().gap(5).items_center().flex_none().loop('opacity', { from: .35, to: 1, period: 1400 })
      .children([0, 1, 2].map(() => div().size(6).rounded(3).bg(actView.stalled ? t.blocked : t.muted)));
    if (!actView.label && !actView.canInterrupt && !actView.canRotate) {
      return h_flex().id('pm-typing-line').h(28).items_center().child(dotsEl);
    }
    const interrupting = this.interruptingPm === this.pmName;
    const rotating = this.rotatingPm === this.pmName;
    const intTip = word(this.lang, interrupting ? 'interruptingPmTip' : 'interruptPmTip');
    const rotTip = word(this.lang, rotating ? 'rotatingPmTip' : 'rotatePmTip');
    const openTip = word(this.lang, 'openPm');
    return h_flex().id('pm-typing-line').w_full().min_h(28).gap(8).items_center()
      .child(dotsEl)
      .child(div().id('pm-typing-label').flex_1().min_w(0).truncate().text_size(12.5)
        .text_color(actView.stalled ? t.blocked : t.dim)
        .child(actView.label))
      .when(Boolean(actView.canInterrupt || actView.canRotate), el => el.child(h_flex().id('pm-typing-actions').flex_none().gap(4).items_center()
        .when(Boolean(actView.canInterrupt && pmTermNow), a => a.child(this.withTip('pm-interrupt-btn',
          h_flex().id('pm-interrupt-btn').size(24).rounded(7).items_center().justify_center()
            .text_color(actView.stalled ? t.blocked : t.muted).accessibility_label(intTip)
            .when(!interrupting, btn => btn.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
              .on_click((_e, clickCx) => this.interruptPm(clickCx)))
            .child(interrupting ? svg(SPINNER).size(13).flex_none().text_color(t.muted).spin(900) : this.icon('stop', 14)),
          intTip, t, { placement: 'above-right' })))
        .when(Boolean(actView.canRotate && this.pm()?.repo), a => a.child(this.withTip('pm-rotate-btn',
          h_flex().id('pm-rotate-btn').size(24).rounded(7).items_center().justify_center()
            .text_color(t.muted).accessibility_label(rotTip)
            .when(!rotating, btn => btn.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
              .on_click((_e, clickCx) => this.rotatePmFromStall(clickCx)))
            .child(rotating ? svg(SPINNER).size(13).flex_none().text_color(t.muted).spin(900) : this.icon('refresh', 14)),
          rotTip, t, { placement: 'above-right' })))
        .when(Boolean(pmTermNow), a => a.child(this.withTip('pm-open-term-btn',
          h_flex().id('pm-open-term-btn').size(24).rounded(7).items_center().justify_center()
            .text_color(t.muted).accessibility_label(openTip).cursor_pointer()
            .hover(s => s.bg(t.hover).text_color(t.foreground))
            .on_click(() => this.show(pmTermNow.address))
            .child(this.icon('terminal', 14)),
          openTip, t, { placement: 'above-right' })))));
  }

  // Quiet icon at the top of the conversation column when earlier events stand before the current window.
  earlierControl(blocks, t) {
    const lang = this.lang, busy = this.earlierLoading, err = this.earlierError;
    const tip = busy ? word(lang, 'loadingEarlier') : err ? word(lang, 'earlierFailed', err) : word(lang, 'earlierMessages');
    return h_flex().w_full().pb(6).justify_center().items_center()
      .child(this.withTip('conversation-earlier', h_flex().id('conversation-earlier').size(28).rounded(9).items_center().justify_center()
        .text_color(err ? t.blocked : t.dim).accessibility_label(tip)
        .when(!busy, el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(err ? t.blocked : t.foreground))
          .on_click((_e, cx) => this.loadEarlierEvents(blocks, cx)))
        .child(busy ? svg(SPINNER).size(14).flex_none().text_color(t.muted).spin(900) : this.icon('earlier', 15)), tip, t, { placement: 'below-left' }));
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
      const { quotes: msgQuotes, text: bodyText } = splitQuotedMessage(b.text || '');
      const userSource = (bodyText || b.text) ? this.messageSource('user', b.key, bodyText || b.text, b.at, today) : null;
      const hovered = Boolean(userSource && this.hoveredMsg === b.key);
      const flashed = this.flash === b.key;
      const dark = isDarkTheme(t);
      const knownBlocks = this.lastBlocks || [];
      const uParsed = (userSource && bodyText) ? this.cachedParagraphs(bodyText) : null;
      const uBlocks = uParsed?.blocks || [];
      const uMulti = Boolean(uParsed?.multi);
      const userBody = !bodyText ? null : uMulti
        ? v_flex().max_w_full().children(uBlocks.map((seg, bi) => {
            const mt = this.paraGapTop(bi > 0 ? uBlocks[bi - 1].kind : '', seg.kind);
            if (!seg.quotable) {
              return div().max_w_full().when(mt > 0, el => el.mt(mt))
                .child(this.renderMentionText(`bubble-${b.key}-b${bi}`, seg.markdown, t, cx, userSource));
            }
            const paraKey = `${b.key}#p${seg.index}`;
            const paraActive = this.hoveredPara === paraKey;
            const paraFlashed = this.flashPara === paraKey;
            return h_flex().id(`para-${b.key}-${seg.index}`).max_w_full().when(mt > 0, el => el.mt(mt)).items_start().justify_between().gap(4)
              .pl(5).pr(2).py(2).rounded(6).border_l(2)
              .border_color(paraFlashed ? t.accent : paraActive ? withAlpha(t.accent, .5) : '#00000000')
              .when(paraFlashed, el => el.bg(withAlpha(t.accent, dark ? .16 : .11)))
              .when(!paraFlashed && paraActive, el => el.bg(withAlpha(t.foreground, dark ? .05 : .04)))
              .on_hover((over, cx) => this.setHoveredPara(paraKey, over, cx))
              .child(this.renderMentionText(`bubble-${b.key}-p${seg.index}`, seg.markdown, t, cx, userSource))
              .child(h_flex().id(`para-quote-slot-${b.key}-${seg.index}`).w(22).h(22).flex_none().justify_end()
                .when(paraActive, el => el.child(this.paragraphQuoteButton(userSource, seg, t))));
          }))
        : this.renderMentionText(`bubble-${b.key}`, bodyText, t, cx, userSource);
      const quotePreviewW = msgQuotes.length > 0
        ? Math.max(180, Math.min(410, Math.floor((this.viewWidth
          ? Math.min(COLUMN, Math.max(260, this.viewWidth - (this.listShown && this.wide ? panelWidth(this.panelWant, this.viewWidth) : 0) - 64))
          : COLUMN) * 0.72) - 52))
        : 0;
      const el = v_flex().max_w('72%').px(14).py(10).gap(8).rounded_tl(18).rounded_tr(18).rounded_bl(18).rounded_br(6)
        .bg(flashed && !this.flashPara ? withAlpha(t.accent, dark ? .20 : .13) : t.raised).text_color(t.foreground)
        .when(msgQuotes.length > 0, el => el.child(v_flex().id(`bubble-quotes-${b.key}`).w_full().gap(5)
          .children(msgQuotes.map((q, qi) => {
            const from = word(this.lang, 'quoteFrom', q.author || word(this.lang, 'quoteAuthorPm'), q.time);
            const scopeTip = quoteScopeTip(this.lang, q);
            const st = this.quoteScopeStyle(q, t);
            const canJump = Boolean(q.targetKey && (this._blockKeySet ? this._blockKeySet.has(q.targetKey) : blockIndexForKey(knownBlocks, q.targetKey) >= 0));
            const tip = `${canJump ? word(this.lang, 'quoteJump') : word(this.lang, 'quoteJumpMissing')}\n${from} · ${scopeTip}: ${q.text}`;
            const preview = quoteCardPreview(q.text, { maxLines: 3, maxWidthPx: quotePreviewW, fontSize: 12.5 });
            return this.withTip(`bubble-quote-${b.key}-${qi}`, v_flex().id(`bubble-quote-${b.key}-${qi}`).w_full().px(9).py(6).gap(2).rounded(9)
              .bg(t.surface).border_l(2).border_color(st.bar)
              .accessibility_label(tip)
              .when(canJump, qel => qel.cursor_pointer().hover(s => s.bg(t.hover))
                .on_click((e, cx) => { e?.stop_propagation?.(); cx?.stop_propagation?.(); this.jumpToMessage(q.targetKey, cx, q.range); }))
              .child(h_flex().gap(5).items_center().text_size(11).text_color(t.dim)
                .child(this.icon(st.icon, 11).flex_none())
                .child(div().min_w(0).truncate().child(from))
                .child(this.quoteScopeBadge(q, t, `bubble-quote-scope-${b.key}-${qi}`)))
              .child(v_flex().w_full().children(preview.lines.map(line =>
                div().w_full().truncate().text_size(12.5).line_height('18px').text_color(t.muted).child(line)))),
            tip, t, { placement: 'above-right' });
          }))))
        .when(Boolean(userBody), el => el.child(userBody))
        .when(files.length > 0, el => el.child(h_flex().flex_wrap().gap(6)
          .children(files.map((path, i) => this.fileCard(`sent-${b.key}-${i}`, path, t).bg(t.surface)))));
      const bubbleEl = el.id(`bubble-${b.key}`).when(b.pending, el => el.opacity(.65))
        .when(flashed && !this.flashPara, el => el.border(1.5).border_color(t.accent))
        .when((!flashed || Boolean(this.flashPara)) && !dark && !b.failed, el => el.border_1().border_color(t.border))
        .when((!flashed || Boolean(this.flashPara)) && Boolean(b.failed), el => el.border_1().border_color(withAlpha(t.blocked, .6)));
      const bubbleId = Number(b.key.split(':')[1]);
      // A timed-out bubble may have arrived: its state says so on its own, without "not sent:".
      const failedLine = b.unconfirmed ? b.failed : word(this.lang, 'failed', b.failed);
      const row = h_flex().id(`user-msg-${b.key}`).w_full().justify_end().gap(6).items_center()
        .on_hover((h, cx) => this.setHoveredMsg(b.key, h, cx))
        .when(Boolean(b.failed), row => row.child(this.withTip(`retry-${b.key}`, h_flex().id(`retry-${b.key}`).size(24).rounded(12).items_center()
          .justify_center().text_color(t.blocked).cursor_pointer().hover(s => s.bg(t.hover))
          .accessibility_label(word(this.lang, 'retrySend'))
          .on_click((_e, cx) => this.retry(bubbleId, cx))
          .child(this.icon('refresh', 13.5)), `${word(this.lang, 'retrySend')} · ${failedLine}`, t, { placement: 'above-right' })))
        .when(hovered, row => row.child(this.quoteButton(userSource, t, { whole: uMulti })))
        .child(b.pending
          ? this.withTip(`bubble-${b.key}`, bubbleEl, word(this.lang, b.checking ? 'checkingSent' : 'sending'), t, { placement: 'above-right' })
          : b.queued
            ? this.withTip(`bubble-${b.key}`, bubbleEl.opacity(.82), word(this.lang, 'queuedTip'), t, { placement: 'above-right' })
            : bubbleEl);
      if (b.queued) {
        return v_flex().w_full().items_end().gap(4).child(row)
          .child(this.withTip(`queued-${b.key}`, h_flex().id(`queued-${b.key}`).gap(5).items_center().text_size(11.5).text_color(t.muted)
            .child(div().size(5).rounded_full().bg(t.blocked))
            .child(word(this.lang, 'queued')), word(this.lang, 'queuedTip'), t, { placement: 'above-right' }));
      }
      if (!b.failed) return row;
      const errId = b.upload ? `upload-error-${b.key}` : `failed-${b.key}`;
      return v_flex().w_full().items_end().gap(4).child(row)
        .child(h_flex().id(errId).max_w('72%').gap(5).items_center().cursor_pointer()
          .text_size(11.5).text_color(t.blocked).hover(s => s.opacity(.85))
          .on_click((_e, cx) => this.retry(bubbleId, cx))
          .child(div().size(5).flex_none().rounded_full().bg(t.blocked))
          .child(div().min_w(0).whitespace_normal().child(failedLine)));
    }
    // One row of a coordinator turn (see timelineRows). The names of the threads a reply is about sit
    // close above it; the turn's other parts follow on rows of their own, under the avatar's column.
    const part = item => this.fade(this.turnPart(item, t, cx, today), item.key, cx);
    // The avatar arrives with its turn's first part, not a frame before it.
    return h_flex().w_full().items_start().gap(12)
      .child(b.first && !b.bare ? this.fade(this.avatar(t), b.parts[0].key, cx) : div().w(28).flex_none())
      .child(v_flex().flex_1().min_w(0).gap(2).children(b.parts.map(part)));
  }

  initHeaderOnly(cx) {
    this.headerOnly = true;
    this.lang = 'en';
    this.keyFocus = cx.focus_handle();
    this.headerActionSeq = 0;
  }

  emitHeaderAction(kind, session, extra = {}) {
    if (!session) return;
    this.headerActionSeq = ((this.headerActionSeq || 0) + 1) % 1000;
    setShared(HEADER_ACTION, {
      session,
      seq: Date.now() * 1000 + this.headerActionSeq,
      kind,
      ...extra,
    });
  }

  publishHeaderState(data) {
    const serialized = JSON.stringify(data);
    if (serialized === this.lastHeaderState) return;
    this.lastHeaderState = serialized;
    setShared(HEADER_STATE, data);
  }

  syncHeaderAction(cx) {
    const act = shared(HEADER_ACTION);
    if (!act || act.session !== this.winSession || !act.seq || act.seq === this.lastHeaderActionSeq) return;
    this.lastHeaderActionSeq = act.seq;
    cx.timer?.after?.(0, cx => this.handleHeaderAction(act, cx));
  }

  handleHeaderAction(act, cx) {
    if (!act) return;
    if (act.kind === 'escape') {
      this.escape({ keystroke: 'escape' }, cx);
      this.keyFocus?.focus();
    } else if (act.kind === 'key' && act.keystroke) {
      this.handleKeyDown({ keystroke: act.keystroke }, cx);
      if (act.keystroke === 'escape') this.keyFocus?.focus();
    } else if (act.kind === 'toggle-search') {
      this.toggleProjectSearch(cx);
    } else if (act.kind === 'bell') {
      const row = this.ringAction?.(cx);
      if (typeof row === 'number' && row >= 0) this.scroll.scroll_to_item(row);
      this.keyFocus?.focus();
    } else if (act.kind === 'focus-pm') {
      const terminal = this.pmTerminal();
      if (terminal?.address) this.focusTerminal(terminal.address);
    } else if (act.kind === 'start-pm') {
      this.startPm(cx);
      this.keyFocus?.focus();
    } else if (act.kind === 'toggle-panel') {
      this.togglePanel(cx);
      this.keyFocus?.focus();
    }
  }

  buildHeaderData(pm, waiting, hasRing) {
    const lang = this.lang;
    const terminal = pm ? terminalTargetFor(pmRow(pm), this.terms()).terminal : null;
    const pmCtx = contextTokens(pm?.context_tokens);
    const compactTokens = pm?.compact_tokens ?? this.state?.compact_tokens ?? this.state?.rotate_tokens;
    const pmStart = pmStartState(pm, terminal, this.startingPm === this.pmName
      || Boolean(this.bringingBack && this.bringBackProgress?.pmKey === this.pmName
        && this.bringBackProgress.steps?.some(s => s.kind === 'pm' && s.state === 'running')));
    const pmOfflineTip = pmStart === 'archived' ? word(lang, 'pmOfflineArchived')
      : (pmStart === 'tui' || pmStart === 'tui_live') ? word(lang, 'pmOfflineTui')
      : pmStart === 'missing_repo' ? word(lang, 'pmOfflineMissingRepo')
      : word(lang, 'noPmTerminal');
    const panelOpen = Boolean(this.listResting() || this.detail);
    return {
      session: this.winSession,
      pmName: this.pmName,
      lang,
      hasPm: Boolean(pm),
      title: pm?.project || pm?.name || 'PM',
      pathText: this.machine ? `${this.machine} · ${pm?.repo || ''}` : shortPath(pm?.repo, home()),
      pmCtx,
      pmCtxLevel: pmContextLevel(pmCtx, compactTokens),
      pmCtxText: contextLabel(lang, pmCtx),
      pmCtxTip: pmContextTip(lang, pmCtx, compactTokens),
      errorTip: (this.error || this.logError) ? `${word(lang, 'readError')}: ${this.logError || this.error}` : '',
      searchOpen: Boolean(this.searchOpen),
      searchTip: word(lang, 'searchProjectTip', searchShortcutLabel(this.hostPlatform())),
      waiting,
      hasRing,
      bellTip: waiting ? word(lang, 'waitingCount', waiting) : word(lang, 'nothingWaiting'),
      pmStart,
      pmOfflineTip,
      panelOpen,
      panelTip: word(lang, panelOpen
        ? (this.librarySupported() ? 'hideSidePanel' : 'hideThreads')
        : (this.librarySupported() ? 'showSidePanel' : 'showThreads')),
    };
  }

  renderHeaderBar(data, actions, t, { standalone = true } = {}) {
    const lang = data.lang || this.lang;
    // In standalone mode (inside full-height pm-project), withTip renders bounded floating cards.
    // In split 56px header-block mode, use native GPUI tooltips so they float outside the 56px block.
    const tipWrap = (key, el, tip, opts = {}) => (standalone
      ? this.withTip(key, el, tip, t, { placement: 'below-right', ...opts })
      : (tip ? el.tooltip(tip) : el));
    const hdrIconBtn = (id, name, tip, action, size = 16) => (standalone
      ? this.iconButton(id, name, tip, action, t, size)
      : h_flex().id(id).size(32).flex_none().rounded(9).items_center().justify_center().text_color(t.muted)
        .tooltip(tip).accessibility_label(tip)
        .when(Boolean(action), el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
          .on_click((_e, cx) => action(cx)))
        .when(!action, el => el.opacity(.4))
        .child(this.icon(name, size)));
    const searchBtn = hdrIconBtn('pm-search', 'search', data.searchTip, cx => actions.onToggleSearch?.(cx), 16)
      .when(Boolean(data.searchOpen), el => el.bg(t.raised).text_color(t.foreground));
    const bell = tipWrap('bell', h_flex().id('bell').relative().size(32).flex_none().rounded(10).items_center().justify_center()
      .text_color(t.muted).accessibility_label(data.bellTip)
      .when(Boolean(actions.onBell), el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
        .on_click((_e, cx) => actions.onBell(cx)))
      .child(this.icon('bell', 17))
      .when(data.waiting > 0, el => el.child(h_flex().absolute().top(-3).right(-5).min_w(18).h(18).px(4).rounded(9)
        .items_center().justify_center().bg(t.blocked).border(2).border_color(t.canvas)
        .text_color(solidText(t.blocked, t)).text_size(10.5).font_semibold().child(String(data.waiting)))),
      data.bellTip);
    const warnColor = t.ansi3 || t.accent;
    const pmCtxEl = !data.pmCtx ? null
      : data.pmCtxLevel === 'over'
        ? tipWrap('pm-context', h_flex().id('pm-context').flex_none().h(22).px(8).rounded(7).items_center().whitespace_nowrap()
          .bg(withAlpha(warnColor, .14)).text_color(warnColor).text_size(12).font_medium()
          .accessibility_label(data.pmCtxTip).child(data.pmCtxText), data.pmCtxTip)
        : tipWrap('pm-context', div().id('pm-context').flex_none().whitespace_nowrap().text_size(12)
          .when(data.pmCtxLevel === 'near', el => el.font_medium())
          .text_color(data.pmCtxLevel === 'near' ? warnColor : t.dim)
          .accessibility_label(data.pmCtxTip).child(data.pmCtxText), data.pmCtxTip, { wrap: true, flexNone: true });
    const pmControl = data.pmStart === 'online'
      ? hdrIconBtn('pm-terminal', 'terminal', word(lang, 'openPm'), () => actions.onOpenPm())
      : data.pmStart === 'starting'
        ? tipWrap('pm-start', h_flex().id('pm-start').size(32).flex_none().rounded(9).items_center().justify_center().text_color(t.muted)
          .accessibility_label(word(lang, 'startingPm'))
          .child(svg(SPINNER).size(15).flex_none().spin(900)), word(lang, 'startingPm'))
        : data.pmStart === 'startable'
          ? hdrIconBtn('pm-start', 'play', word(lang, 'startPm'), cx => actions.onStartPm(cx))
          : hdrIconBtn('pm-terminal', 'terminal', data.pmOfflineTip, null);
    // Key the panel toggle button's element id by open/closed state so GPUI discards any cached or
    // pending WaitingForShow tooltip closure when the panel flips while the cursor stays on the button.
    const panelBtnId = data.panelOpen ? 'pm-threads-open' : 'pm-threads-closed';
    const base = h_flex().id('pm-project-header-bar');
    const bar = (standalone ? base.h(56).flex_none() : base.size_full().bg(t.canvas).text_size(14).text_color(t.foreground))
      .px(28).gap(10).items_center().border_b(1).border_color(t.border);
    return bar
      .child(div().flex_none().text_size(15).font_semibold().child(data.title))
      .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(12).text_color(t.dim)
        .child(data.pathText))
      .when(Boolean(pmCtxEl), el => el.child(pmCtxEl))
      .when(Boolean(data.errorTip), el => el.child(tipWrap('read-error', div().id('read-error').text_color(t.blocked)
        .child('!'), data.errorTip, { wrap: true, flexNone: true })))
      .child(keepPress(this.views(t, data.pmName, lang), this.keyFocus))
      .child(keepPress(h_flex().id('pm-header-controls').gap(4).items_center(), this.keyFocus)
        .child(searchBtn)
        .child(bell)
        .child(pmControl)
        .child(hdrIconBtn(panelBtnId, 'panel', data.panelTip, cx => actions.onTogglePanel(cx))));
  }

  renderHeaderOnly(_cx) {
    const t = theme();
    const s = shared(HEADER_STATE);
    const activeRef = shared(SHARED);
    const onKeyDown = (e, cx) => {
      const ks = e?.keystroke || '';
      if (ks === 'escape' && s?.session) {
        this.emitHeaderAction('escape', s.session);
        cx.stop_propagation?.();
      } else if ((ks === 'cmd-k' || ks === 'ctrl-k' || ks === 'cmd-f' || ks === 'ctrl-f') && s?.session) {
        this.emitHeaderAction('key', s.session, { keystroke: ks });
        cx.stop_propagation?.();
      }
    };
    if (!s || !s.hasPm || (activeRef?.pm && s.pmName && s.pmName !== activeRef.pm)) {
      return h_flex().id('pm-project-header-bar').size_full().bg(t.canvas)
        .track_focus(this.keyFocus).on_key_down(onKeyDown);
    }
    this.lang = s.lang || this.lang || 'en';
    return this.renderHeaderBar(s, {
      onToggleSearch: () => this.emitHeaderAction('toggle-search', s.session),
      onBell: s.hasRing ? () => this.emitHeaderAction('bell', s.session) : null,
      onOpenPm: () => this.emitHeaderAction('focus-pm', s.session),
      onStartPm: () => this.emitHeaderAction('start-pm', s.session),
      onTogglePanel: () => this.emitHeaderAction('toggle-panel', s.session),
    }, t, { standalone: false })
      .track_focus(this.keyFocus)
      .on_key_down(onKeyDown);
  }

  // ring: null while nothing waits, else what a click on the bell calls: it names the row to go to
  // (-1: none, as when it opened a thread instead).
  header(pm, waiting, ring, t) {
    const terminal = pm ? terminalTargetFor(pmRow(pm), this.terms()).terminal : null;
    const data = this.buildHeaderData(pm, waiting, Boolean(ring));
    return this.renderHeaderBar(data, {
      onToggleSearch: cx => this.toggleProjectSearch(cx),
      onBell: ring ? cx => {
        const row = ring(cx);
        if (row >= 0) this.scroll.scroll_to_item(row);
      } : null,
      onOpenPm: () => { if (terminal) this.focusTerminal(terminal.address); },
      onStartPm: cx => this.startPm(cx),
      onTogglePanel: cx => this.togglePanel(cx),
    }, t, { standalone: true });
  }

  lostNotice(pm, t) {
    const lang = this.lang, lost = pm?.lost;
    const summary = lostSummary(lang, lost);
    const rawSteps = bringBackSteps(lang, lost, pm?.project || pm?.name);
    const namesTip = rawSteps.map(s => s.title).filter(Boolean).join(' · ');
    if (!this.bringBackOpen && !this.bringingBack) {
      if (!summary) return null;
      return keepPress(h_flex().id('lost-banner'), this.keyFocus).w_full().pl(14).pr(6).py(5).gap(10).rounded(12).items_center()
        .bg(t.surface).border_1().border_color(t.border)
        .child(div().size(7).flex_none().rounded_full().bg(t.ansi3 || t.accent))
        .child(namesTip
          ? this.withTip('lost-names', div().w_full().truncate().text_size(13).text_color(t.foreground).child(summary), namesTip, t, { placement: 'below-left', wrap: true, flex1: true })
          : div().flex_1().min_w(0).truncate().text_size(13).text_color(t.foreground).child(summary))
        .child(h_flex().flex_none().gap(2).items_center()
          .child(this.iconButton('lost-open', 'reattach', word(lang, 'bringAllBack'), cx => this.openBringBack(pm, cx), t, 15))
          .child(this.iconButton('lost-dismiss', 'close', word(lang, 'bringBackDismiss'), cx => this.dismissLost(pm, cx), t, 14)));
    }
    const steps = this.bringBackProgress?.pmKey === this.pmName && this.bringBackProgress.steps?.length
      ? this.bringBackProgress.steps
      : rawSteps.map(s => ({ ...s, state: 'pending', error: '' }));
    if (!steps.length) return null;
    const hasFailed = steps.some(s => s.state === 'failed');
    const allDone = steps.every(s => s.state === 'done');
    const hintKey = steps.some(s => s.kind === 'pm') ? 'bringBackHintWithPm' : 'bringBackHintThreads';
    const runControl = this.bringingBack
      ? this.withTip('lost-run', h_flex().id('lost-run').size(32).flex_none().rounded(9).items_center().justify_center().text_color(t.muted)
        .accessibility_label(word(lang, 'bringingBack'))
        .child(svg(SPINNER).size(15).flex_none().spin(900)), word(lang, 'bringingBack'), t, { placement: 'below-right' })
      : allDone
        ? h_flex().id('lost-done').size(32).flex_none().rounded(9).items_center().justify_center()
          .text_color(t.ansi2 || t.accent).child(this.icon('check', 16))
        : this.iconButton('lost-run', hasFailed ? 'reattach' : 'play',
          word(lang, hasFailed ? 'bringBackRetry' : 'bringBackStart'), cx => this.runBringBack(cx), t, 15);
    const stepRow = s => {
      const mark = s.state === 'running' ? svg(SPINNER).size(13).flex_none().text_color(t.working ?? t.ansi2).spin(900)
        : s.state === 'done' ? this.icon('check', 13).text_color(t.ansi2 ?? t.accent)
        : s.state === 'failed' ? div().text_size(12).font_semibold().text_color(t.blocked).child('!')
        : div().size(8).rounded_full().border(1.5).border_color(t.dim);
      const stepNum = s.kind === 'thread' ? formatTaskNumber(taskNumber(s) || this.taskNumberFor(s.id)) : '';
      return h_flex().id(`lost-step-${s.key}`).px(6).py(3).gap(9).rounded(7).items_start()
        .child(h_flex().h(18).w(16).flex_none().items_center().justify_center().child(mark))
        .child(v_flex().flex_1().min_w(0).gap(1)
          .child(h_flex().gap(8).items_center()
            .when(Boolean(stepNum), el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(stepNum)))
            .child(div().flex_1().min_w(0).truncate().text_size(12.5)
              .text_color(s.state === 'done' ? t.muted : t.foreground).child(s.title))
            .when(Boolean(s.address), el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(s.address))))
          .when(Boolean(s.error), el => el.child(div().whitespace_normal().text_size(11.5).text_color(t.blocked).child(s.error))));
    };
    return keepPress(v_flex().id('lost-card'), this.keyFocus).w_full().pl(14).pr(8).py(8).gap(6).rounded(14)
      .bg(t.surface).border_1().border_color(t.border)
      .child(h_flex().gap(10).items_center()
        .child(v_flex().flex_1().min_w(0).gap(1)
          .child(div().truncate().text_size(13).font_medium().text_color(t.foreground).child(summary || word(lang, 'bringingBack')))
          .child(div().truncate().text_size(11.5).text_color(t.dim).child(word(lang, hintKey))))
        .child(h_flex().flex_none().gap(2).items_center()
          .child(runControl)
          .child(this.iconButton('lost-close', 'close', word(lang, 'bringBackCollapse'),
            this.bringingBack ? null : cx => this.closeBringBack(cx), t, 14))))
      .child(v_flex().gap(2).children(steps.map(stepRow)));
  }

  pmBlockedBar(text, t) {
    const lang = this.lang;
    const pmTerm = this.pmTerminal();
    return h_flex().id('pm-blocked-bar').w_full().pl(14).pr(6).py(4).gap(10).rounded(12).items_center()
      .bg(t.surface).border_1().border_color(withAlpha(t.blocked, .45))
      .child(div().size(6).flex_none().rounded_full().bg(t.blocked))
      .child(div().flex_1().min_w(0).whitespace_normal().text_size(12.5).text_color(t.foreground).child(text))
      .when(Boolean(pmTerm), el => el.child(this.iconButton('pm-blocked-open', 'terminal', word(lang, 'openPm'),
        cx => this.open(pmTerm, cx), t, 14)));
  }

  offlinePmBar(pmStart, t) {
    const lang = this.lang;
    const err = this.startPmError?.pm === this.pmName ? this.startPmError.text : '';
    const busy = pmStart === 'starting';
    const control = busy
      ? this.withTip('pm-offline-start', h_flex().id('pm-offline-start').size(28).flex_none().rounded(8).items_center().justify_center().text_color(t.muted)
        .accessibility_label(word(lang, 'startingPm'))
        .child(svg(SPINNER).size(14).flex_none().spin(900)), word(lang, 'startingPm'), t, { placement: 'below-right' })
      : pmStart === 'startable'
        ? this.iconButton('pm-offline-start', 'play', word(lang, 'startPm'), cx => this.startPm(cx), t, 14)
        : null;
    return h_flex().id('pm-offline-bar').w_full().pl(14).pr(6).py(4).gap(10).rounded(12).items_center()
      .bg(t.surface).border_1().border_color(err ? withAlpha(t.blocked, .5) : t.border)
      .child(div().size(6).flex_none().rounded_full().bg(err ? t.blocked : t.dim))
      .child(div().flex_1().min_w(0).whitespace_normal().text_size(12.5).text_color(err ? t.blocked : t.muted)
        .child(err ? word(lang, 'startPmFailed', err) : word(lang, busy ? 'startingPm' : 'pmOfflineStartable')))
      .when(Boolean(control), el => el.child(control));
  }

  // Conversation | Board. The board is pm-dash's, scoped to this project: shared('pm-dash').project.
  views(t, pmName = this.pmName, lang = this.lang) {
    const option = (key, text, action) => h_flex().id(`view-${key}`).h(26).px(10).gap(6).rounded(7).items_center()
      .text_size(13).accessibility_label(text)
      .when(!action, el => el.bg(t.raised).text_color(t.foreground).font_medium())
      .when(Boolean(action), el => el.cursor_pointer().text_color(t.muted).hover(s => s.text_color(t.foreground))
        .on_click(action))
      .child(this.icon(key, 14)).child(text);
    return h_flex().id('project-view').flex_none().h(34).p(3).gap(2).rounded(10).border_1().border_color(t.border)
      .child(option('chat', word(lang, 'chatView'), null))
      .child(option('board', word(lang, 'boardView'), () => {
        setShared('pm-dash', { view: 'board', project: pmName });
        run('layout.select', { stack: STAGE, child: BOARD });
      }));
  }

  // A session's status as the app's agents list marks it: spinner, dot or ring, never a word.
  sessionMark(status, t) {
    if (status === 'working') return svg(SPINNER).size(12).flex_none().text_color(t.working ?? t.ansi2).spin(900);
    const dot = div().flex_none().size(7).rounded_full();
    return status === 'blocked' ? dot.bg(t.blocked) : status === 'done' ? dot.bg(t.done ?? t.accent) : dot.border(1.5).border_color(t.idle ?? t.dim);
  }

  // What a thread is now, as a mark: an arc that turns while its worker is at work, a blue spinning
  // outer arc with an inner dot while a reviewer is actively running (static double ring while waiting
  // for PM verdict or after review ends), a red double ring while waiting, a dim double ring when
  // paused, a bare ring when queued, a small dim ring once it is over.
  threadMark(row, t) {
    const ring = color => h_flex().size(14).flex_none().rounded_full().items_center().justify_center().border(1.5).border_color(color);
    if (row.group === 'working') {
      if (row.reviewing || row.status === 'review') {
        if (row.reviewWorking) {
          return h_flex().relative().size(14).flex_none().items_center().justify_center()
            .child(svg(SPINNER).size(14).absolute().left(0).top(0).text_color(t.accent).spin(900))
            .child(div().size(5).rounded_full().bg(t.accent));
        }
        return ring(t.accent).child(div().size(5.5).rounded_full().bg(t.accent));
      }
      if (row.working) return svg(SPINNER).size(14).flex_none().text_color(t.ansi2 ?? t.working).spin(900);
      return svg(SPINNER).size(14).flex_none().text_color(row.postGate ? (t.working ?? t.ansi3 ?? t.accent) : t.dim);
    }
    return row.group === 'offline' ? this.icon('unplug', 14).text_color(t.dim)
      : row.group === 'finished' ? div().size(9).flex_none().rounded_full().border(1.5).border_color(t.dim)
      : row.group === 'parked' ? ring(t.dim)
        : row.group === 'paused' ? ring(t.dim).child(div().size(6).rounded_full().bg(t.dim))
          : ring(this.toneColor(row.tone, t)).child(div().size(6).rounded_full().bg(this.toneColor(row.tone, t)));
  }

  // Smooth cubic Bezier branch connectors (no right angles): each item carries a smooth curve from the
  // vertical stem to its row, and every non-last item continues the stem down to the next sibling.
  treeBranchList(items, opts = {}) {
    return treeBranchList({ div, svg, v_flex }, items, { ...opts, treeBranchIcon: ICON('tree-branch') });
  }

  agentStatusMark(status, t, role = '') {
    if (status === 'working') {
      return svg(SPINNER).size(10).flex_none().text_color(role === 'review' ? t.accent : (t.ansi2 ?? t.working)).spin(900);
    }
    if (status === 'blocked') return div().size(6.5).flex_none().rounded_full().bg(t.blocked);
    if (status === 'done') return div().size(6.5).flex_none().rounded_full().bg(t.accent);
    return div().size(6.5).flex_none().rounded_full().border(1.4).border_color(t.dim);
  }

  // Render an agent's own program icon (matching Herdr's Agents list), falling back to our generic agent glyph.
  agentProgramIcon(program, size, t, dimmed = false) {
    if (program?.icon) {
      return program.tint
        ? svg(program.icon).size(size).flex_none().text_color(dimmed ? t.dim : t.foreground)
        : image(program.icon).size(size).flex_none();
    }
    return this.icon('agent', size).text_color(dimmed ? t.dim : t.muted);
  }

  clearHoverNow(cx) {
    this.hoverHideTimer?.cancel?.();
    this.hoverHideTimer = null;
    const had = Boolean(this.hoverKey) || Boolean(this.hoverCardOver);
    this.hoverKey = '';
    this.hoverCardOver = '';
    if (had && cx?.notify && cx?.phase?.() !== 'render') cx.notify();
  }

  enterHover(key, cx) {
    this.hoverHideTimer?.cancel?.();
    this.hoverHideTimer = null;
    if (this.hoverKey !== key) {
      this.hoverKey = key;
      this.hoverCardOver = '';
      cx.notify();
    }
  }

  leaveHover(key, cx) {
    if (!key || this.hoverKey !== key || this.hoverCardOver === key) return;
    this.hoverHideTimer?.cancel?.();
    this.hoverHideTimer = cx.timer?.after?.(180, cx => {
      this.hoverHideTimer = null;
      if (this.hoverKey === key && this.hoverCardOver !== key) {
        this.hoverKey = '';
        cx.notify();
      }
    }) || null;
  }

  enterHoverCard(key, cx) {
    this.hoverHideTimer?.cancel?.();
    this.hoverHideTimer = null;
    this.hoverCardOver = key;
    if (this.hoverKey !== key) {
      this.hoverKey = key;
      cx.notify();
    }
  }

  leaveHoverCard(key, cx) {
    if (this.hoverCardOver === key) this.hoverCardOver = '';
    this.leaveHover(key, cx);
  }

  wrapHoverCard(key, rowEl, buildCard, t) {
    const active = this.hoverKey === key;
    if (!active) return div().relative().w_full().child(rowEl);
    const cardEl = buildCard();
    return div().relative().w_full().child(rowEl)
      .when(Boolean(cardEl), box => box.child(
        div().id(`hover-card-anchor-${key}`).absolute().left(-16).top(0).w(0).h(0).child(
          Popup.new(`hover-card-${key}`, div().w(0).h(0))
            .anchor('top_right')
            .content(div().id(`hover-card-body-${key}`)
              .on_hover((over, cx) => {
                if (over) this.enterHoverCard(key, cx);
                else this.leaveHoverCard(key, cx);
              })
              .child(cardEl)),
        ),
      ));
  }

  threadHoverCard(task, row, steps, deps, chip, ctxLabel, t, lang) {
    const fill = [t.raised, t.popover, t.surface].find(c => c && c !== t.chrome) || t.raised;
    const status = statusLabel(lang, row.status, Boolean(task?.cleanup), Boolean(row.offline), Boolean(row.answered), Boolean(row.closed));
    const numTag = formatTaskNumber(taskNumber(row) || taskNumber(task) || this.taskNumberFor(row.task));
    const showDeps = Boolean(deps?.showAsWaiting);
    const hasSteps = !showDeps && Boolean(steps?.steps?.length);
    const metaParts = [
      numTag,
      row.closed ? word(lang, 'closedReattach') : (!(showDeps || hasSteps) ? status : ''),
      row.branch,
      chip ? `${chip.label}${chip.up ? ' ↑' : ''}` : '',
      ctxLabel,
    ].filter(Boolean);
    const metaText = metaParts.join(' · ');
    const clean = cleanTaskLog(task?.latest);
    const rawLog = (row.latest || clean.text || '').replace(/\s+/g, ' ').trim();
    const isWorking = !row.offline && row.group === 'working';
    const depsCard = showDeps ? renderDepsCard({
      ui: { div, svg, h_flex, v_flex },
      deps, theme: t, lang, icons: STEP_ICONS,
      compact: true, framed: false,
      rowIdPrefix: `hover-dep-${row.task}`,
      headerMeta: metaText,
      onSelect: (dep, cx) => this.jumpToDependency(dep, cx),
    }) : null;
    const stepsCard = !depsCard && hasSteps ? renderStepsCard({
      ui: { div, svg, h_flex, v_flex },
      steps, theme: t, lang, icons: STEP_ICONS,
      compact: true, framed: false,
      headerMeta: metaText,
      spinning: isWorking, reviewSpinning: Boolean(row.reviewWorking), subSpinning: isWorking,
    }) : null;
    const hasBody = Boolean(depsCard || stepsCard);
    if (!hasBody && !metaText && !rawLog) return null;
    return v_flex().w(300).px(11).py(9).gap(6).rounded(10)
      .bg(fill).border_1().border_color(t.border).shadow_lg()
      .when(Boolean(depsCard), card => card.child(depsCard))
      .when(Boolean(stepsCard), card => card.child(stepsCard))
      .when(!hasBody && Boolean(metaText), card => card.child(
        div().truncate().font_family('monospace').text_size(10.5).text_color(t.dim).child(metaText),
      ))
      .when(Boolean(rawLog), card => card.child(
        div().when(hasBody || Boolean(metaText), el => el.pt(5).border_t(1).border_color(withAlpha(t.border, .6)))
          .child(div().truncate().text_size(11).line_height('15px').text_color(t.muted).child(rawLog)),
      ));
  }

  epicHoverCard(node, t, lang) {
    const fill = [t.raised, t.popover, t.surface].find(c => c && c !== t.chrome) || t.raised;
    const s = node.summary || {};
    const countsText = [
      s.waiting > 0 ? word(lang, 'sumWaiting', s.waiting) : '',
      s.review > 0 ? word(lang, 'sumReview', s.review) : '',
      s.working > 0 ? word(lang, 'sumWorking', s.working) : '',
      s.offline > 0 ? word(lang, 'sumOffline', s.offline) : '',
      (s.paused || 0) + (s.parked || 0) > 0 ? word(lang, 'sumQueued', (s.paused || 0) + (s.parked || 0)) : '',
      s.done > 0 ? word(lang, 'sumDone', s.done) : '',
    ].filter(Boolean).join(' · ');
    const epicNum = formatTaskNumber(node);
    const activeNum = formatTaskNumber(node.activeChild);
    const activeText = node.activeChild ? `${word(lang, 'activePrefix')}${activeNum ? `${activeNum} ` : ''}${node.activeChild.title}` : '';
    const sub = activeText || node.latest || '';
    if (!epicNum && !countsText && !sub) return null;
    return v_flex().w(288).px(11).py(9).gap(4).rounded(10)
      .bg(fill).border_1().border_color(t.border).shadow_lg()
      .when(Boolean(epicNum) || Boolean(countsText), card => card.child(h_flex().gap(6).items_center()
        .when(Boolean(epicNum), rowEl => rowEl.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(epicNum)))
        .when(Boolean(countsText), rowEl => rowEl.child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(11).text_color(t.accent).child(countsText)))))
      .when(Boolean(sub), card => card.child(div().whitespace_normal().text_size(11.5).text_color(t.muted).child(sub)));
  }

  agentHoverCard(ag, isOpen, t, lang) {
    const fill = [t.raised, t.popover, t.surface].find(c => c && c !== t.chrome) || t.raised;
    const ctxText = ag.contextTokens ? contextLabel(lang, ag.contextTokens) : '';
    const state = ag.ended ? (ag.status === 'done' ? word(lang, 'agentState_done') : word(lang, 'agentWindowEnded'))
      : word(lang, `agentState_${ag.status}`);
    // A helper serving the task says what it does (Merging · working) before its model.
    const doing = ag.purpose ? ag.nameSuffix : '';
    const meta = [doing, state, ag.model ? `${ag.model}${ag.up ? ' ↑' : ''}` : '', ctxText].filter(Boolean).join(' · ');
    const summary = ag.ended && ag.summary ? ag.summary : '';
    const hint = word(lang, isOpen ? 'closeAgentWindow' : 'openAgentWindow');
    return v_flex().w(268).px(11).py(9).gap(4).rounded(10)
      .bg(fill).border_1().border_color(t.border).shadow_lg()
      .child(div().truncate().font_family('monospace').text_size(11).text_color(t.accent).child(`${ag.roleLabel} · ${ag.name}`))
      .when(Boolean(meta), card => card.child(div().truncate().text_size(11.5).text_color(t.foreground).child(meta)))
      .when(Boolean(summary), card => card.child(div().text_size(11.5).line_height('16px').text_color(t.muted).max_h(48).overflow_hidden().child(summary)))
      .child(div().truncate().text_size(11).text_color(t.dim).child(hint));
  }

  // ---- In-Project floating agent small windows (openOverlay({ kind: 'window' })) ----------------

  agentWindowSlotPos(slot, width = 520) {
    const wide = this.viewWidth || 1280;
    const panelW = (this.listResting() || this.detail) ? panelWidth(this.panelWant, wide) : 0;
    const stageW = Math.max(540, wide - panelW);
    const w = Number(width) || 520;
    const baseX = Math.max(48, Math.round(stageW - w - 36));
    const off = (slot % 2) * 34;
    return { x: Math.max(32, baseX - off), y: 82 + off * 2 };
  }

  rememberedAgentWindowSize() {
    return normalizeAgentWindowSize(typeof shared === 'function' ? shared('pm-project-agent-window-size') : '');
  }

  syncAgentWindowTerminals() {
    if (typeof setShared !== 'function') return;
    const next = agentWindowTerminalAddresses(this.agentWindows, this.machine);
    const prev = typeof shared === 'function' ? shared('pm-project-win-terminals') : null;
    if (Array.isArray(prev) && prev.length === next.length && prev.every((v, i) => v === next[i])) return;
    setShared('pm-project-win-terminals', next);
  }

  overlayWindowSpec(entry, slot) {
    const isTerm = entry.mode === 'terminal' && Boolean(entry.address);
    const appAddr = onMachine(entry.address, this.machine);
    const size = normalizeAgentWindowSize(entry.size || this.rememberedAgentWindowSize());
    const dims = agentWindowDimensions(isTerm ? 'terminal' : 'chat', size, {
      maxWidth: this.viewWidth ? Math.round(this.viewWidth * 0.92) : 0,
    });
    const pos = this.agentWindowSlotPos(slot, dims.width);
    const baseProps = {
      agentWindow: isTerm ? 'titlebar' : 'chat',
      key: entry.key,
      role: entry.role,
      roleLabel: entry.roleLabel || word(this.lang, `agentRole_${entry.role || 'worker'}`),
      taskId: entry.taskId,
      threadNumber: entry.threadNumber || 0,
      targetId: entry.targetId,
      name: entry.name,
      threadTitle: entry.threadTitle,
      address: entry.address,
      appAddress: appAddr,
      model: entry.model || '',
      up: Boolean(entry.up),
      contextLabel: entry.contextLabel || '',
      canSwitchMode: Boolean(entry.canSwitchMode && entry.address),
      ended: Boolean(entry.ended),
      kind: entry.kind || '',
      program: entry.program || null,
      resultPath: entry.resultPath || '',
      summary: entry.summary || '',
      prompt: entry.prompt || '',
      forcedMode: Boolean(entry.forcedMode),
      lang: this.lang,
      machine: this.machine,
      ledgerHome: this.ledgerHome,
      remoteHome: this.remoteHome,
      slug: projectSlug(this.pm()),
      session: this.winSession,
      mode: isTerm ? 'terminal' : 'chat',
      size,
    };
    if (isTerm) {
      return {
        kind: 'window',
        key: `pm-agent:${entry.key}`,
        width: dims.width,
        height: dims.height,
        at: pos,
        layout: {
          type: 'column',
          background: 'background',
          children: [
            { type: 'block', size: { px: 36 }, content: { mod: 'pm-project', props: baseProps } },
            { type: 'block', content: { terminal: appAddr } },
          ],
        },
      };
    }
    return {
      mod: 'pm-project',
      props: baseProps,
      kind: 'window',
      key: `pm-agent:${entry.key}`,
      width: dims.width,
      height: dims.height,
      at: pos,
    };
  }

  openOrReplaceAgentOverlay(entry, { forcedMode = false } = {}) {
    if (typeof openOverlay !== 'function') return;
    const isTerm = entry.mode === 'terminal' && Boolean(entry.address);
    // Publish floating terminal addresses before opening a terminal overlay so pm-nav recognizes
    // clicks inside it immediately; when leaving terminal mode, clear after openOverlay replaces it.
    if (isTerm) this.syncAgentWindowTerminals();
    const slot = this.agentWindowSlot++;
    const ovId = openOverlay(this.overlayWindowSpec({ ...entry, forcedMode }, slot));
    if (ovId) this.agentWindows = setAgentWindowOverlay(this.agentWindows, entry.key, ovId);
    if (!isTerm) this.syncAgentWindowTerminals();
  }

  toggleAgentSmallWindow(spec, cx) {
    if (!spec?.key) return;
    const sizedSpec = spec.size ? spec : { ...spec, size: this.rememberedAgentWindowSize() };
    const res = toggleAgentWindow(this.agentWindows, sizedSpec, { max: AGENT_WINDOW_MAX });
    this.agentWindows = res.windows;
    if (res.action === 'close') {
      if (res.closed?.overlayId && typeof closeOverlay === 'function') closeOverlay(res.closed.overlayId);
      this.syncAgentWindowTerminals();
    } else if (res.action === 'open') {
      if (res.evicted?.overlayId && typeof closeOverlay === 'function') closeOverlay(res.evicted.overlayId);
      this.openOrReplaceAgentOverlay(res.opened);
    }
    cx?.notify?.();
  }

  closeTopAgentWindow(cx) {
    const res = closeAgentWindow(this.agentWindows);
    this.agentWindows = res.windows;
    if (res.closed?.overlayId && typeof closeOverlay === 'function') closeOverlay(res.closed.overlayId);
    this.syncAgentWindowTerminals();
    cx?.notify?.();
  }

  closeOverlayIds(ids, cx = null, { defer = false, onAfter = null } = {}) {
    const list = (ids || []).filter(Boolean);
    const runClose = () => {
      if (typeof closeOverlay === 'function') {
        for (const id of list) closeOverlay(id);
      }
      onAfter?.();
    };
    if (!list.length && !onAfter) return;
    const shouldDefer = defer || cx?.phase?.() === 'render';
    if (shouldDefer && typeof cx?.timer?.after === 'function') {
      cx.timer.after(0, runClose);
    } else {
      runClose();
    }
  }

  closeAllAgentWindows(cx = null, { defer = false } = {}) {
    const ids = (this.agentWindows || []).map(w => w?.overlayId).filter(Boolean);
    const had = (this.agentWindows || []).length > 0;
    this.agentWindows = [];
    this.closeOverlayIds(ids, cx, { defer, onAfter: had ? () => this.syncAgentWindowTerminals() : null });
  }

  handleWinEvent(ev, cx) {
    if (!ev || ev.session !== this.winSession) return;
    if (ev.kind === 'focus') {
      this.agentWindows = focusAgentWindow(this.agentWindows, ev.key);
      cx.notify();
    } else if (ev.kind === 'close') {
      const res = closeAgentWindow(this.agentWindows, ev.key);
      this.agentWindows = res.windows;
      if (res.closed?.overlayId && typeof closeOverlay === 'function') closeOverlay(res.closed.overlayId);
      this.syncAgentWindowTerminals();
      cx.notify();
    } else if (ev.kind === 'mode') {
      const sw = toggleAgentWindowMode(this.agentWindows, ev.key, ev.mode || '');
      this.agentWindows = sw.windows;
      if (sw.changed && sw.window) {
        this.openOrReplaceAgentOverlay(sw.window, { forcedMode: Boolean(ev.forcedMode) });
      }
      cx.notify();
    } else if (ev.kind === 'size') {
      const sw = setAgentWindowSize(this.agentWindows, ev.key, ev.size || '');
      this.agentWindows = sw.windows;
      if (sw.changed && sw.window) {
        if (typeof setShared === 'function') setShared('pm-project-agent-window-size', sw.window.size);
        this.openOrReplaceAgentOverlay(sw.window);
      }
      cx.notify();
    } else if (ev.kind === 'locate' && ev.taskId) {
      if (!(this.detail && this.thread === ev.taskId)) this.openThread(ev.taskId, cx);
      else {
        if (this.isThreadChangeOpen()) this.closeThreadChange(cx);
        if (!this.listResting()) { this.listShown = true; cx.notify(); }
      }
    }
  }

  syncWinEvents(cx) {
    this.agentWindows = this.agentWindows || [];
    // Reconcile terminal-mode small windows whose underlying terminal has exited:
    // close their floating overlays so dead terminal windows do not stay stranded on screen.
    if (this.agentWindows.length) {
      const liveSet = new Set(this.terms().filter(x => x.state === 'live').map(x => x.address));
      const rec = reconcileAgentWindows(this.agentWindows, liveSet);
      if (rec.closed.length) {
        this.agentWindows = rec.windows;
        this.closeOverlayIds(rec.closed.map(w => w?.overlayId), cx, { defer: true, onAfter: () => this.syncAgentWindowTerminals() });
      }
    }
    const ev = shared('pm-project-win-event');
    if (ev && ev.session === this.winSession && ev.seq && ev.seq !== this.lastWinEventSeq) {
      this.lastWinEventSeq = ev.seq;
      cx.timer?.after?.(0, cx => this.handleWinEvent(ev, cx));
    }
  }

  emitWinEvent(kind, extra = {}) {
    const p = this.winProps;
    if (!p?.session || !p?.key) return;
    setShared('pm-project-win-event', {
      session: p.session,
      seq: Date.now() * 1000 + Math.floor(Math.random() * 1000),
      kind,
      key: p.key,
      taskId: p.taskId || '',
      overlayId: (typeof props === 'function' ? props()?.overlay : '') || '',
      ...extra,
    });
  }

  initAgentWindow(p, cx) {
    this.agentWindow = p.agentWindow;
    this.winProps = p;
    this.lang = p.lang || 'en';
    this.machine = p.machine || '';
    this.ledgerHome = p.ledgerHome || '';
    this.remoteHome = p.remoteHome || '';
    this.winFocus = cx.focus_handle();
    if (p.agentWindow !== 'chat') return;
    this.winScroll = ScrollHandle.new();
    this.winToolsOpen = new Set();
    this.winBriefsOpen = new Set();
    this.winSent = [];
    this.winSession = null;
    this.winSessionState = '';
    this.winSessionError = '';
    this.winHelperDoc = null;
    this.winHelperError = '';
    this.winFallbackLog = null;
    this.winDraft = '';
    this.winTyping = false;
    this.winSendError = '';
    this.winAutoSwitched = false;
    if (p.address) {
      this.winInput = TextareaState.new({ rows: 1 });
      this.winInput.set_auto_grow(1, 4);
      this.winInput.on('change', (_e, cx) => {
        const next = String(this.winInput.value?.() ?? '');
        const had = Boolean(this.winDraft.trim());
        this.winDraft = next;
        if (had !== Boolean(next.trim())) cx.notify();
      });
      this.winInput.on('submit', (e, cx) => {
        if (e?.shift) return;
        this.sendAgentWindowMessage(cx);
      });
      this.winInput.on('focus', (_e, cx) => { this.winTyping = true; cx?.notify?.(); });
      this.winInput.on('blur', (_e, cx) => { this.winTyping = false; cx?.notify?.(); });
    }
    this.loadAgentWindowContent(cx);
    if (!this.machine && p.address) {
      cx.timer.every(SESSION_POLL_LOCAL_MS, cx => {
        if (this.agentWindow === 'chat' && !this.winProps?.ended) this.loadAgentWindowContent(cx, { poll: true });
      });
    }
  }

  loadAgentWindowContent(cx, { poll = false } = {}) {
    const p = this.winProps;
    if (!p) return;
    if (p.role === 'helper') {
      const path = resolveHelperResultPath(p.resultPath, {
        ledgerHome: this.machine ? this.remoteHome : this.ledgerHome,
        slug: p.slug || '',
        homeDir: this.machine ? '' : (typeof home === 'function' ? home() : ''),
      });
      if (path && !this.winHelperLoading) {
        this.winHelperLoading = true;
        cx.spawn(async cx => {
          try {
            const text = await readTextFile(path, this.where());
            if (text != null) { this.winHelperDoc = text; this.winHelperError = ''; }
          } catch (e) {
            if (!poll) this.winHelperError = String(e?.message || e).trim();
          } finally {
            this.winHelperLoading = false;
            cx.notify();
          }
        });
      }
      if (p.kind !== 'claude' || !p.address) return;
    }
    if (!p.targetId || p.role === 'helper' && p.kind !== 'claude') return;
    if (this.winSessionLoading) return;
    this.winSessionLoading = true;
    if (!this.winSessionState) this.winSessionState = 'loading';
    cx.spawn(async cx => {
      try {
        const after = this.winSession?.offset ?? null;
        const r = await this.runProject(projectSessionArgv(p.targetId, { after, limit: SESSION_LIMIT }));
        if (r.code !== 0) {
          if (isMissingSessionModule(r) || isQuietNoSession(r) || isOldPmCommand(r)) {
            this.winSessionState = 'unavailable';
            if (p.address && !p.forcedMode && !this.winAutoSwitched) {
              this.winAutoSwitched = true;
              this.emitWinEvent('mode', { mode: 'terminal', forcedMode: false });
              return;
            }
            await this.loadWinFallbackTask(p);
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const raw = String(r.stdout || '').trim();
        const got = raw ? JSON.parse(raw) : null;
        if (!got || typeof got !== 'object' || !Array.isArray(got.items)) {
          this.winSessionState = 'unavailable';
          if (p.address && !p.forcedMode && !this.winAutoSwitched) {
            this.winAutoSwitched = true;
            this.emitWinEvent('mode', { mode: 'terminal', forcedMode: false });
            return;
          }
          await this.loadWinFallbackTask(p);
          return;
        }
        let next = takeSessionWindow(this.winSession, got, after != null ? 'after' : 'end', { taskId: p.targetId });
        if (next) next = trimSessionWindow(next);
        this.winSession = next;
        this.winSessionState = 'ready';
        this.winSessionError = '';
      } catch (e) {
        this.winSessionState = this.winSession ? 'ready' : 'error';
        this.winSessionError = String(e?.message || e).trim();
      } finally {
        this.winSessionLoading = false;
        cx.notify();
      }
    });
  }

  async loadWinFallbackTask(p) {
    const homeDir = this.machine ? this.remoteHome : this.ledgerHome;
    if (!homeDir || !p.targetId) return;
    try {
      const raw = await readTextFile(`${homeDir}/tasks/${p.targetId}.json`, this.where());
      if (!raw) return;
      const doc = JSON.parse(raw);
      this.winFallbackLog = {
        brief: String(doc?.brief || ''),
        log: Array.isArray(doc?.log) ? doc.log.slice(-5) : [],
      };
    } catch (_) { /* Fallback stays optional. */ }
  }

  sendAgentWindowMessage(cx) {
    const p = this.winProps;
    const text = String(this.winInput?.value?.() ?? '').trim();
    if (!text || !p?.address) return;
    const addr = p.appAddress || onMachine(p.address, this.machine);
    this.winSent = [...(this.winSent || []).slice(-19), text];
    this.winInput.set_value('');
    this.winDraft = '';
    this.winSendError = '';
    cx.notify();
    cx.spawn(async cx => {
      try {
        const r = await exec(...withoutTerminalEnv(sendArgv(addr, text), {
          platform: this.hostPlatform(), unset: SEND_ENV,
        }), { timeout: 20000 });
        if (r.code !== 0) throw new Error((r.stderr || r.stdout).trim() || `hc send: ${r.code}`);
        cx.timer?.after?.(700, cx => this.loadAgentWindowContent(cx, { poll: true }));
      } catch (e) {
        this.winSendError = String(e?.message || e).trim();
      }
      cx.notify();
    });
  }

  winIconBtn(id, iconName, tip, onClick, t, size = 14, active = false, tipOpts = {}) {
    return this.withTip(id, h_flex().id(id).size(24).flex_none().rounded(6).items_center().justify_center()
      .text_color(active ? t.accent : t.muted)
      .when(active, el => el.bg(withAlpha(t.accent, .14)))
      .accessibility_label(tip)
      .on_mouse_down('left', (_e, cx) => cx.stop_propagation())
      .when(Boolean(onClick), el => el.cursor_pointer()
        .hover(s => active ? s.bg(withAlpha(t.accent, .2)) : s.bg(t.hover).text_color(t.foreground))
        .on_click((_e, cx) => { cx.stop_propagation(); this.hoverKey = ''; onClick(cx); }))
      .when(!onClick, el => el.opacity(.4))
      .child(this.icon(iconName, size)), tip, t, { panel: true, placement: 'below-right', ...tipOpts });
  }

  renderAgentWindowTitlebar(t, cx) {
    const p = this.winProps || {};
    const lang = this.lang || 'en';
    const isTerm = this.agentWindow === 'titlebar' || p.mode === 'terminal';
    const appAddr = p.appAddress || onMachine(p.address, this.machine);
    const liveAgent = appAddr ? agents().find(a => a.address === appAddr) || null : null;
    const liveTerm = appAddr ? terminals().find(x => x.address === appAddr) || null : null;
    const liveStatus = appAddr
      ? (liveAgent?.status || liveTerm?.status || (p.ended ? 'done' : 'working'))
      : (p.ended ? 'done' : 'idle');
    const winProgram = resolveAgentProgram(liveTerm, liveAgent, p.kind) || p.program || null;
    const meta = [p.model ? `${p.model}${p.up ? ' ↑' : ''}` : '', p.contextLabel || ''].filter(Boolean).join(' · ');
    const numTag = formatTaskNumber(p.threadNumber);
    const titleLabel = p.roleLabel && p.name ? `${p.roleLabel} · ${p.name}` : (p.name || p.roleLabel || 'agent');
    const ov = (typeof props === 'function' ? props()?.overlay : '') || '';
    const curSize = normalizeAgentWindowSize(p.size);
    const nextSize = nextAgentWindowSize(curSize);
    const curSizeLabel = curSize.toUpperCase();
    const nextSizeLabel = nextSize.toUpperCase();
    const sizeBtnTip = word(lang, 'windowSizeTip', curSizeLabel, nextSizeLabel);
    const sizeBtn = this.withTip(`win-size-${p.key || 'x'}`, h_flex().id(`win-size-${p.key || 'x'}`)
      .h(24).min_w(24).px(5).flex_none().rounded(6).items_center().justify_center()
      .text_color(t.muted).cursor_pointer()
      .hover(s => s.bg(t.hover).text_color(t.foreground))
      .accessibility_label(sizeBtnTip)
      .on_mouse_down('left', (_e, cx) => cx.stop_propagation())
      .on_click((_e, cx) => { cx.stop_propagation(); this.hoverKey = ''; this.emitWinEvent('size', { size: nextSize }); })
      .child(div().font_family('monospace').text_size(10.5).font_semibold().child(curSizeLabel)),
      sizeBtnTip, t, { panel: true, placement: 'below-right' });
    return h_flex().id(`win-titlebar-${p.key || 'x'}`).w_full().h(36).flex_none().pl(12).pr(8).gap(8).items_center()
      .bg(t.surface).border_b(1).border_color(t.border)
      .on_mouse_down('left', () => this.emitWinEvent('focus'))
      .child(this.agentStatusMark(liveStatus, t, p.role))
      .child(this.agentProgramIcon(winProgram, 13, t, Boolean(p.ended)))
      .child(div().flex_none().text_size(12.5).font_semibold().text_color(t.foreground).child(titleLabel))
      .when(Boolean(numTag), el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(numTag)))
      .when(Boolean(p.threadTitle), el => el.child(div().flex_1().min_w(0).truncate().text_size(11.5).text_color(t.dim).child(p.threadTitle)))
      .when(!p.threadTitle, el => el.child(div().flex_1()))
      .when(Boolean(meta), el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.muted).child(meta)))
      .child(h_flex().flex_none().gap(2).items_center()
        .when(Boolean(p.canSwitchMode && p.address), el => el.child(this.winIconBtn(
          `win-mode-${p.key || 'x'}`,
          isTerm ? 'chat' : 'terminal',
          word(lang, isTerm ? 'switchToChat' : 'switchToTerminal'),
          () => this.emitWinEvent('mode', { mode: isTerm ? 'chat' : 'terminal', forcedMode: true }),
          t, 13.5,
        )))
        .child(sizeBtn)
        .when(Boolean(p.taskId), el => el.child(this.winIconBtn(
          `win-locate-${p.key || 'x'}`,
          'hook-up',
          word(lang, 'locateThread'),
          () => this.emitWinEvent('locate', { taskId: p.taskId }),
          t, 13.5,
        )))
        .child(this.winIconBtn(
          `win-close-${p.key || 'x'}`,
          'close',
          word(lang, 'closeAgentWindow'),
          () => { this.emitWinEvent('close'); if (ov && typeof closeOverlay === 'function') closeOverlay(ov); },
          t, 13,
        )));
  }

  renderAgentWindow(cx) {
    const t = theme();
    if (this.agentWindow === 'titlebar') return this.renderAgentWindowTitlebar(t, cx);
    const p = this.winProps || {};
    const lang = this.lang || 'en';
    const today = iso(new Date());
    const ov = (typeof props === 'function' ? props()?.overlay : '') || '';
    const turns = this.winSession ? sessionTurns(this.winSession.items, { lang, sent: this.winSent }) : [];
    const worked = this.winSession && !this.winSession.earlier ? workedDuration(lang, this.winSession.started, this.winSession.ended) : '';

    const bodyChildren = [];
    if (p.role === 'helper') {
      if (p.prompt) {
        bodyChildren.push(v_flex().w_full().items_end().gap(3)
          .child(div().max_w('90%').px(11).py(7).rounded_tl(12).rounded_tr(12).rounded_bl(12).rounded_br(4)
            .bg(t.raised).text_size(12.5).text_color(t.foreground).whitespace_normal().child(p.prompt)));
      }
      if (this.winHelperDoc) {
        bodyChildren.push(v_flex().w_full().gap(6).children(markdownChunks(this.winHelperDoc).map((chunk, ci) =>
          div().w_full().text_size(12.5).text_color(t.foreground)
            .child(TextView.markdown(`win-helper-md-${ci}`, chunk).selectable(true)))));
      } else if (p.summary) {
        bodyChildren.push(div().w_full().whitespace_normal().text_size(12.5).text_color(t.foreground).child(p.summary));
      } else if (turns.length) {
        // Live Claude helper transcript falls through below.
      } else if (this.winHelperError) {
        bodyChildren.push(div().text_size(12).text_color(t.blocked).whitespace_normal().child(this.winHelperError));
      } else {
        bodyChildren.push(div().text_size(12.5).text_color(t.dim).child(word(lang, p.address ? 'helperRunningTerm' : 'helperNoConclusion')));
      }
    }

    if (turns.length) {
      turns.forEach((turn, idx) => {
        if (turn.role === 'user') {
          const open = this.winBriefsOpen.has(turn.key);
          const shownText = turn.long && !open ? turn.preview : turn.text;
          const metaWords = [turn.from, clock(turn.at, today)].filter(Boolean).join(' · ');
          bodyChildren.push(v_flex().w_full().items_end().gap(3)
            .child(v_flex().max_w('90%').px(11).py(7).gap(5).rounded_tl(12).rounded_tr(12).rounded_bl(12).rounded_br(4)
              .bg(t.raised).text_size(12.5).text_color(t.foreground)
              .when(Boolean(shownText), el => el.child(div().whitespace_normal().child(shownText)))
              .when(Boolean(turn.long), el => el.child(h_flex().gap(4).items_center().cursor_pointer()
                .text_size(11).text_color(t.dim).hover(s => s.text_color(t.foreground))
                .on_click((_e, cx) => {
                  if (this.winBriefsOpen.has(turn.key)) this.winBriefsOpen.delete(turn.key);
                  else this.winBriefsOpen.add(turn.key);
                  cx.notify();
                })
                .child(this.icon(open ? 'collapse' : 'expand', 12))
                .child(word(lang, open ? 'fold' : 'unfoldMessage')))))
            .when(Boolean(metaWords), el => el.child(div().text_size(10.5).text_color(t.dim).child(metaWords))));
          return;
        }
        const isFirstAssistant = turns.findIndex(x => x.role === 'assistant') === idx;
        bodyChildren.push(v_flex().w_full().gap(5)
          .when(Boolean(isFirstAssistant && worked), el => el.child(div().text_size(11).text_color(t.dim).child(worked)))
          .children(turn.parts.map(part => {
            if (part.kind === 'text') {
              return v_flex().w_full().gap(5).children(markdownChunks(part.text).map((chunk, ci) =>
                div().w_full().text_size(12.5).text_color(t.foreground)
                  .child(TextView.markdown(`win-md-${part.key}-${ci}`, chunk).selectable(true))));
            }
            const open = this.winToolsOpen.has(part.key);
            return v_flex().w_full().gap(4)
              .child(h_flex().id(`win-tools-${part.key}`).min_h(24).px(8).py(3).gap(6).rounded(6).items_center()
                .cursor_pointer().bg(t.surface).hover(s => s.bg(t.hover))
                .on_click((_e, cx) => {
                  if (this.winToolsOpen.has(part.key)) this.winToolsOpen.delete(part.key);
                  else this.winToolsOpen.add(part.key);
                  cx.notify();
                })
                .child(this.icon(open ? 'expand' : 'chevron', 11).text_color(t.dim))
                .child(div().flex_1().min_w(0).truncate().text_size(11.8).text_color(t.muted).child(part.label)))
              .when(open, el => el.child(v_flex().ml(6).pl(8).gap(4).border_l(1).border_color(t.border)
                .children(part.calls.map(c => v_flex().gap(1)
                  .child(div().font_family('monospace').text_size(11).text_color(c.error ? t.blocked : t.muted).child(`${c.name} ${c.input || ''}`))
                  .when(Boolean(c.output), x => x.child(div().whitespace_normal().font_family('monospace').text_size(10.5).text_color(t.dim).child(c.output)))))));
          })));
      });
    } else if (p.role !== 'helper') {
      if (this.winSessionState === 'loading') {
        bodyChildren.push(h_flex().gap(6).items_center().text_size(12).text_color(t.dim)
          .child(svg(SPINNER).size(13).flex_none().spin(900)).child(word(lang, 'sessionLoading')));
      } else if (this.winSessionError) {
        bodyChildren.push(div().text_size(12).text_color(t.blocked).whitespace_normal().child(this.winSessionError));
      } else if (this.winFallbackLog) {
        if (this.winFallbackLog.brief) {
          bodyChildren.push(v_flex().w_full().items_end()
            .child(div().max_w('90%').px(11).py(7).rounded_tl(12).rounded_tr(12).rounded_bl(12).rounded_br(4)
              .bg(t.raised).text_size(12).text_color(t.foreground).whitespace_normal().child(this.winFallbackLog.brief)));
        }
        for (const e of this.winFallbackLog.log) {
          bodyChildren.push(div().text_size(12).text_color(t.muted).whitespace_normal().child(logText(lang, e?.text, true)));
        }
      } else {
        bodyChildren.push(div().text_size(12).text_color(t.dim).whitespace_normal()
          .child(word(lang, p.address ? 'agentSessionFallback' : 'sessionEmpty')));
      }
    }

    const ready = Boolean(this.winDraft?.trim());
    const composer = p.address && this.winInput ? keepPress(h_flex().id(`win-composer-${p.key}`).mx(10).mb(10).pl(12).pr(6).py(5)
      .gap(6).rounded(11).items_end().bg(t.surface).border_1().border_color(this.winTyping ? t.accent : t.border))
      .child(div().relative().flex_1().min_w(0).py(4)
        .when(!this.winDraft, el => el.child(div().absolute().left(0).top(4).right(0).truncate().text_size(12.5).text_color(t.dim).child(word(lang, 'sayAgent'))))
        .child(Textarea.new(this.winInput).w_full().text_size(12.5).text_color(t.foreground)))
      .child(h_flex().id(`win-send-${p.key}`).size(26).flex_none().rounded(13).items_center().justify_center()
        .bg(ready ? t.solid : t.raised).text_color(ready ? t.solid_foreground : t.muted)
        .when(ready, el => el.cursor_pointer().on_click((_e, cx) => this.sendAgentWindowMessage(cx)))
        .child(this.icon('send', 13))) : null;

    return v_flex().id(`agent-win-${p.key || 'x'}`).size_full().min_w(0).min_h(0)
      .bg(t.canvas).text_color(t.foreground).track_focus(this.winFocus)
      .on_key_down((e, cx) => {
        if (e.keystroke !== 'escape') return;
        cx.stop_propagation();
        if (this.winTyping && this.winDraft.trim()) {
          this.winFocus.focus();
          this.winTyping = false;
          cx.notify();
          return;
        }
        this.emitWinEvent('close');
        if (ov && typeof closeOverlay === 'function') closeOverlay(ov);
      })
      .child(this.renderAgentWindowTitlebar(t, cx))
      .child(v_flex().id(`win-body-${p.key || 'x'}`).flex_1().min_h(0).px(14).py(12).gap(10).overflow_y_scrollbar()
        .track_scroll(this.winScroll)
        .on_mouse_down('left', (_e, cx) => { cx.stop_propagation(); this.winFocus.focus(); })
        .children(bodyChildren))
      .when(Boolean(this.winSendError), el => el.child(div().px(12).pb(4).text_size(11).text_color(t.blocked).child(this.winSendError)))
      .when(Boolean(composer), el => el.child(composer));
  }

  close() {
    if (!this.agentWindow) this.closeAllAgentWindows();
  }

  // The threads the open task was split into, under its status: a row each (its mark, its title,
  // its status), opening that thread as a row of the thread list does. Past PARTS_LIMIT the rest
  // fold behind an expand mark with how many more; opened, they scroll in a box of their own and a
  // collapse mark folds them again, so the log keeps its room.
  partsList(parts, t) {
    const lang = this.lang, open = this.partsOpen === this.thread;
    const { shown, more } = foldParts(parts, open);
    const rows = shown.map(row => {
      const gone = row.offline && row.group !== 'offline' ? (row.closed ? closedTip(lang, row.closed) : word(lang, 'disconnected'))
        : (row.closed ? closedTip(lang, row.closed) : '');
      const label = statusLabel(lang, row.status, row.cleanup, row.offline, row.answered, Boolean(row.closed));
      const numText = formatTaskNumber(taskNumber(row) || this.taskNumberFor(row.task));
      const ctxText = contextLabel(lang, row.contextTokens), ctxCompact = contextShort(row.contextTokens);
      const tip = [label, gone, ctxText, numText ? `${numText} ${row.title}` : row.title].filter(Boolean).join(' · ');
      return this.withTip(`part-${row.task}`, h_flex().id(`part-${row.task}`).h(30).px(8).gap(9).rounded(8).items_center().cursor_pointer()
        .hover(s => s.bg(t.hover)).accessibility_label(tip)
        .on_click((_e, cx) => this.openThread(row.task, cx))
        .child(h_flex().w(16).flex_none().items_center().justify_center().child(this.threadMark(row, t)))
        .when(Boolean(numText), el => el.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(numText)))
        .child(div().flex_1().min_w(0).truncate().text_size(13)
          .text_color(['parked', 'paused', 'offline', 'finished'].includes(row.group) ? t.muted : t.foreground).child(row.title))
        .when(Boolean(ctxCompact), el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(ctxCompact)))
        .child(div().flex_none().text_size(11).text_color(t.dim).child(label)), tip, t, { panel: true, placement: 'above-left' });
    });
    const toggle = (id, mark, tip, value) => this.withTip(id, h_flex().id(id).h(26).px(8).gap(9).rounded(8).items_center().cursor_pointer()
      .text_size(12).text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
      .accessibility_label(tip)
      .on_click((_e, cx) => { this.partsOpen = value; cx.notify(); })
      .child(h_flex().w(16).flex_none().items_center().justify_center().child(this.icon(mark, 14)))
      .when(Boolean(more), el => el.child(div().child(tip))), tip, t, { panel: true, placement: 'above-left' });
    const folding = open && parts.length > PARTS_LIMIT;
    return v_flex().flex_none()
      .child(h_flex().h(22).px(8).gap(6).items_center().text_size(11).font_medium().text_color(t.dim)
        .child(word(lang, 'subThreads')).child(String(parts.length)))
      .child(folding ? v_flex().id('thread-parts').max_h(30 * PARTS_LIMIT).overflow_y_scrollbar().children(rows)
        : v_flex().children(rows))
      .when(more > 0, el => el.child(toggle('parts-more', 'expand', word(lang, 'moreParts', more), this.thread)))
      .when(folding, el => el.child(toggle('parts-fold', 'collapse', word(lang, 'fold'), '')));
  }

  // The panel at rest: Threads task tree (container epics + single-line threads + agent sub-rows + unified fold + hover card).
  threadsPanel(pm, t, width) {
    this.agentWindows = this.agentWindows || [];
    this.epicOverrides = this.epicOverrides || new Map();
    this.expandedDone = this.expandedDone || new Set();
    const lang = this.lang;
    const alreadyFolded = Boolean(this.tasks);
    const allTasks = this.tasks || this.state.tasks;
    const termsNow = this.terms(), liveNow = this.live();
    const tabsNow = this._renderSpacesTabs || (this._renderSpacesTabs = spaces().flatMap(s => s.tabs || []));
    const tree = this.resolveTaskTree(pm, allTasks, termsNow, liveNow, tabsNow, lang, alreadyFolded);
    const byId = new Map(allTasks.map(x => [x.id, x]));
    let logs = null;
    const logsFor = taskId => {
      if (!logs) {
        logs = new Map();
        for (const e of Array.isArray(this.state.events) ? this.state.events : []) {
          if (e?.task) { if (!logs.has(e.task)) logs.set(e.task, []); logs.get(e.task).push(e); }
        }
      }
      return logs.get(taskId) || [];
    };
    const buildRowHoverCard = (task, row, ctxLabel) => {
      const chipSource = task || endedEngine(this.state.ended_engines, row.task);
      const chip = chipSource ? engineChip(lang, { ...chipSource, log: logsFor(row.task) }) : null;
      const steps = task ? taskSteps(task, { lang }) : null;
      const deps = task ? taskDependencies(task, allTasks, { terms: termsNow, live: liveNow }) : null;
      return this.threadHoverCard(task, row, steps, deps, chip, ctxLabel, t, lang);
    };
    const now = Date.now();
    const wireColor = t.input || t.border;
    const lead = el => h_flex().w(16).flex_none().items_center().justify_center().child(el);

    const agentSubRow = (ag, dimmed = false) => {
      const open = agentWindowOpen(this.agentWindows, ag.key);
      const hoverKey = `agent:${ag.key}`;
      const hovered = this.hoverKey === hoverKey;
      const label = ag.nameSuffix || ag.roleLabel;
      const row = h_flex().id(`agent-row-${ag.key}`).h(22).px(7).gap(6).rounded(6).items_center().cursor_pointer()
        .when(open, el => el.bg(withAlpha(t.accent, .14)))
        .when(!open, el => el.hover(s => s.bg(t.hover)))
        .accessibility_label(`${ag.roleLabel} · ${ag.name}`)
        .on_hover((over, cx) => {
          if (over) this.enterHover(hoverKey, cx);
          else this.leaveHover(hoverKey, cx);
        })
        .on_click((_e, cx) => {
          cx.stop_propagation();
          this.clearHoverNow(cx);
          this.toggleAgentSmallWindow(ag, cx);
        })
        .child(h_flex().w(12).flex_none().items_center().justify_center().child(this.agentStatusMark(ag.status, t, ag.role)))
        .child(this.agentProgramIcon(ag.program, 13, t, dimmed || ag.ended))
        .child(div().flex_1().min_w(0).truncate().text_size(11.8)
          .text_color(open ? t.foreground : dimmed || ag.ended ? t.muted : t.foreground)
          .when(!dimmed && !ag.ended, el => el.font_medium())
          .child(label))
        .when(open || hovered, el => el.child(this.icon('window-pop', 12).text_color(t.accent)));
      return this.wrapHoverCard(hoverKey, row, () => this.agentHoverCard(ag, open, t, lang), t);
    };

    const doneFoldRow = (foldId, count, expanded, onToggle) => h_flex().id(foldId).h(20).px(6).gap(4).rounded(5)
      .items_center().cursor_pointer().text_size(11).text_color(t.dim).opacity(.88)
      .hover(s => s.bg(t.hover).text_color(t.muted).opacity(1))
      .on_click((_e, cx) => { cx.stop_propagation(); this.clearHoverNow(null); onToggle(cx); })
      .child(this.icon(expanded ? 'expand' : 'chevron', 10).text_color(t.dim))
      .child(word(lang, 'foldedDone', count));

    const summaryPills = (s, epicId) => {
      if (!s) return null;
      const items = [];
      if (s.waiting > 0) items.push({ key: 'waiting', color: t.blocked, solid: true, count: s.waiting, bg: withAlpha(t.blocked, .16) });
      if (s.review > 0) items.push({ key: 'review', color: t.accent, solid: true, count: s.review, bg: withAlpha(t.accent, .14) });
      if (s.working > 0) items.push({ key: 'working', color: t.ansi2 ?? t.working, solid: true, count: s.working, bg: withAlpha(t.ansi2 ?? t.working, .13) });
      if (s.offline > 0) items.push({ key: 'offline', color: t.dim, solid: true, count: s.offline, bg: t.surface });
      const queued = (s.paused || 0) + (s.parked || 0);
      if (queued > 0) items.push({ key: 'queued', color: t.dim, solid: false, count: queued, bg: t.surface });
      if (s.done > 0) items.push({ key: 'done', color: t.dim, solid: true, count: s.done, bg: t.surface });
      if (!items.length) return null;
      return h_flex().id(`epic-summary-${epicId}`).flex_none().gap(4).items_center()
        .children(items.map(it => h_flex().h(18).px(5).gap(4).rounded(5).items_center().bg(it.bg)
          .text_size(11).font_medium().text_color(it.solid && it.key !== 'done' && it.key !== 'offline' ? it.color : t.muted)
          .child(div().size(6).rounded_full()
            .when(it.solid, d => d.bg(it.color).when(it.key === 'done', x => x.opacity(.65)))
            .when(!it.solid, d => d.border(1.3).border_color(it.color)))
          .child(String(it.count))));
    };

    const renderSingleThread = (node, { hideEndedFold = false } = {}) => {
      const task = byId.get(node.task);
      const at = eventTime(node.updated);
      const ageText = at > 0 ? age(Math.max(0, now - at), lang) : '';
      const mutedTitle = ['parked', 'paused', 'offline', 'finished'].includes(node.group);
      const pill = node.plan?.pill || '';
      const pillBg = node.postGate ? withAlpha(t.working ?? t.ansi3 ?? t.accent, .14)
        : node.reviewing ? withAlpha(t.accent, .14) : t.surface;
      const pillFg = node.postGate ? (t.working ?? t.ansi3 ?? t.accent)
        : node.reviewing ? t.accent : t.dim;
      const ctxLabel = node.contextTokens ? contextLabel(lang, node.contextTokens) : '';
      const numText = formatTaskNumber(taskNumber(node) || taskNumber(task) || this.taskNumberFor(node.task));
      const hoverKey = `task:${node.task}`;
      const litRow = this.highlightThread === node.task;

      const titleRow = h_flex().id(`list-${node.task}`).min_h(28).px(8).py(3).gap(7).rounded(7).items_center().cursor_pointer()
        .when(litRow, el => el.bg(withAlpha(t.accent, .16)).border_1().border_color(withAlpha(t.accent, .45)))
        .when(!litRow, el => el.hover(s => s.bg(t.hover)))
        .accessibility_label(numText ? `${numText} ${node.title}` : node.title)
        .on_hover((over, cx) => {
          if (over) this.enterHover(hoverKey, cx);
          else this.leaveHover(hoverKey, cx);
        })
        .on_click((_e, cx) => {
          this.clearHoverNow(cx);
          this.openThread(node.task, cx);
        })
        .child(lead(this.threadMark(node, t)))
        .when(Boolean(numText), el => el.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(numText)))
        .child(div().flex_1().min_w(0).truncate().text_size(13)
          .font_weight(mutedTitle ? 400 : 500)
          .text_color(mutedTitle ? t.muted : t.foreground)
          .child(node.title))
        .when(Boolean(pill), el => el.child(div().id(`list-steps-${node.task}`).flex_none().h(17).px(5).rounded(4)
          .bg(pillBg).text_color(pillFg).font_family('monospace').text_size(10.5).line_height('17px')
          .child(pill)))
        .when(Boolean(ageText), el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(ageText)));

      const activeAgents = node.agents?.active || [];
      const endedAgents = hideEndedFold ? [] : (node.agents?.ended || []);
      const hasAgentFold = endedAgents.length > 0;
      const foldKey = `agents:${node.task}`;
      const foldOpen = hasAgentFold && this.expandedDone.has(foldKey);

      const branchItems = [];
      for (const ag of activeAgents) branchItems.push(agentSubRow(ag, false));
      if (hasAgentFold) {
        branchItems.push(doneFoldRow(`fold-done-agents-${node.task}`, endedAgents.length, foldOpen, cx => {
          if (this.expandedDone.has(foldKey)) this.expandedDone.delete(foldKey);
          else this.expandedDone.add(foldKey);
          cx.notify();
        }));
        if (foldOpen) {
          for (const ag of endedAgents) branchItems.push(agentSubRow(ag, true));
        }
      }

      return v_flex().w_full().gap(1)
        .child(this.wrapHoverCard(hoverKey, titleRow, () => buildRowHoverCard(task, node, ctxLabel), t))
        .when(branchItems.length > 0, box => box.child(div().pl(8).pb(2)
          .child(this.treeBranchList(branchItems, { indent: 17, stemX: 5.6, curveSize: 16, strokeW: 1.2, curveStart: 3.2, gap: 1, wireColor }))));
    };

    const renderFinishedSubRow = row => {
      const at = eventTime(row.updated);
      const ageText = at > 0 ? age(Math.max(0, now - at), lang) : '';
      const hoverKey = `task:${row.task}`;
      const task = byId.get(row.task);
      const ctxLabel = row.contextTokens ? contextLabel(lang, row.contextTokens) : '';
      const numText = formatTaskNumber(taskNumber(row) || taskNumber(task) || this.taskNumberFor(row.task));
      const litRow = this.highlightThread === row.task;
      const el = h_flex().id(`list-${row.task}`).h(25).px(8).gap(7).rounded(7).items_center().cursor_pointer()
        .text_size(12.2).text_color(litRow ? t.foreground : t.muted)
        .when(litRow, x => x.bg(withAlpha(t.accent, .16)).border_1().border_color(withAlpha(t.accent, .45)))
        .when(!litRow, x => x.hover(s => s.bg(t.hover).text_color(t.foreground)))
        .accessibility_label(numText ? `${numText} ${row.title}` : row.title)
        .on_hover((over, cx) => {
          if (over) this.enterHover(hoverKey, cx);
          else this.leaveHover(hoverKey, cx);
        })
        .on_click((_e, cx) => { this.clearHoverNow(cx); this.openThread(row.task, cx); })
        .child(lead(div().size(9).rounded_full().border(1.5).border_color(t.dim)))
        .when(Boolean(numText), x => x.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(numText)))
        .child(div().flex_1().min_w(0).truncate().child(row.title))
        .when(Boolean(ageText), x => x.child(div().flex_none().text_size(11).text_color(t.dim).child(ageText)));
      return this.wrapHoverCard(hoverKey, el, () => buildRowHoverCard(task, row, ctxLabel), t);
    };

    const renderNode = (node, inEpic = false) => {
      const isParent = node.container || node.children.length > 0 || node.finishedChildren.length > 0;
      if (!isParent) return renderSingleThread(node, { hideEndedFold: inEpic });

      const defaultOpen = Boolean(node.summary && (node.summary.waiting > 0 || node.summary.review > 0 || node.summary.working > 0 || node.group === 'waiting'));
      const open = this.epicOverrides.has(node.task) ? this.epicOverrides.get(node.task) : defaultOpen;
      const toggleEpic = cx => { this.clearHoverNow(null); this.epicOverrides.set(node.task, !open); cx.notify(); };

      const childItems = [];
      if (open) {
        for (const ch of node.children) childItems.push(renderNode(ch, true));

        // Single unified lightweight fold entry at the tail of the epic: merges finished subtasks + ended agents of active children.
        const isSubParent = ch => ch.container || ch.children.length > 0 || ch.finishedChildren.length > 0;
        const ownEnded = node.container ? [] : (node.agents?.ended || []);
        const endedChildAgents = [
          ...ownEnded,
          ...node.children.filter(ch => !isSubParent(ch)).flatMap(ch => ch.agents?.ended || []),
        ];
        const tailDoneCount = node.finishedChildren.length + endedChildAgents.length;
        if (tailDoneCount > 0) {
          const foldKey = `epic:${node.task}`;
          const foldOpen = this.expandedDone.has(foldKey);
          childItems.push(doneFoldRow(`fold-done-${node.task}`, tailDoneCount, foldOpen, cx => {
            if (this.expandedDone.has(foldKey)) this.expandedDone.delete(foldKey);
            else this.expandedDone.add(foldKey);
            cx.notify();
          }));
          if (foldOpen) {
            for (const fc of node.finishedChildren) childItems.push(renderFinishedSubRow(fc));
            for (const ag of endedChildAgents) childItems.push(agentSubRow(ag, true));
          }
        }
      }

      if (node.container) {
        const hoverKey = `epic:${node.task}`;
        const pills = summaryPills(node.summary, node.task);
        const epicNum = formatTaskNumber(taskNumber(node) || taskNumber(byId.get(node.task)) || this.taskNumberFor(node.task));
        const hdr = h_flex().id(`epic-${node.task}`).min_h(30).px(8).py(4).gap(7).rounded(8).items_center().cursor_pointer()
          .hover(s => s.bg(t.hover))
          .accessibility_label(epicNum ? `${epicNum} ${node.title}` : node.title)
          .on_hover((over, cx) => {
            if (over) this.enterHover(hoverKey, cx);
            else this.leaveHover(hoverKey, cx);
          })
          .on_click((_e, cx) => toggleEpic(cx))
          .child(h_flex().w(16).flex_none().items_center().justify_center().text_color(t.muted)
            .child(this.icon(open ? 'expand' : 'chevron', 13)))
          .when(Boolean(epicNum), el => el.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(epicNum)))
          .child(div().flex_1().min_w(0).truncate().text_size(13).font_semibold().text_color(t.foreground).child(node.title))
          .when(Boolean(pills), el => el.child(pills));
        return v_flex().w_full().gap(2)
          .child(this.wrapHoverCard(hoverKey, hdr, () => this.epicHoverCard(node, t, lang), t))
          .when(open && childItems.length > 0, box => box.child(div().pl(8)
            .child(this.treeBranchList(childItems, { indent: 20, stemX: 7, curveSize: 20, strokeW: 1.5, curveStart: 4, gap: 2, wireColor }))));
      }

      // Non-container parent thread (has own worker + sub-tasks): keep single-line thread row + fold toggle.
      const ownSelf = { ...node, agents: { ...node.agents, ended: [] } };
      return v_flex().w_full().gap(2)
        .child(h_flex().w_full().items_center().gap(2)
          .child(h_flex().id(`epic-${node.task}`).size(20).flex_none().rounded(5).items_center().justify_center()
            .cursor_pointer().text_color(t.muted).hover(s => s.bg(t.hover).text_color(t.foreground))
            .on_click((_e, cx) => toggleEpic(cx))
            .child(this.icon(open ? 'expand' : 'chevron', 12)))
          .child(div().flex_1().min_w(0).child(renderSingleThread(ownSelf, { hideEndedFold: true }))))
        .when(open && childItems.length > 0, box => box.child(div().pl(14)
          .child(this.treeBranchList(childItems, { indent: 20, stemX: 7, curveSize: 20, strokeW: 1.5, curveStart: 4, gap: 2, wireColor }))));
    };

    const groupEl = (key, title, count, rows) => v_flex().gap(2)
      .child(h_flex().h(22).px(8).gap(6).items_center().text_size(11).font_medium().text_color(t.dim)
        .child(title).child(String(count)))
      .children(rows);

    const openGroupEls = tree.groups.map(g => groupEl(g.key, g.title, g.count, g.nodes.map(n => renderNode(n, false))));

    const sessions = tree.sessions.map(row => {
      const icon = !row.program?.icon ? this.icon('agent', 16).text_color(t.dim)
        : row.program.tint ? svg(row.program.icon).size(16).flex_none().text_color(t.foreground) : image(row.program.icon).size(16).flex_none();
      const state = `${word(lang, `session_${row.status}`)} · ${row.address}`;
      return this.withTip(`session-${row.address}`, h_flex().id(`session-${row.address}`).h(30).px(8).gap(8).rounded(8).items_center().cursor_pointer()
        .hover(s => s.bg(t.hover))
        .accessibility_label(`${row.label} · ${state}`)
        .on_click(() => this.focusTerminal(row.address))
        .child(lead(icon))
        .child(h_flex().flex_1().min_w(0).gap(8).items_baseline()
          .child(div().flex_1().min_w(0).truncate().text_size(13).text_color(row.status === 'idle' ? t.muted : t.foreground).child(row.label))
          .child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(row.address)))
        .child(h_flex().w(14).flex_none().justify_center().child(this.sessionMark(row.status, t))),
        [row.label, state, word(lang, 'openSession')].join('\n'), t, { panel: true, placement: 'above-left' });
    });

    const finished = tree.finished.map(row => renderFinishedSubRow(row));
    const sections = [...openGroupEls];
    if (sessions.length) sections.push(groupEl('groupSessions', word(lang, 'groupSessions'), sessions.length, sessions));
    if (finished.length) sections.push(groupEl('groupFinished', word(lang, 'groupFinished'), finished.length, finished));

    if (this.pendingScrollThread && this.threadListScroll) {
      const hasTask = n => n && (n.task === this.pendingScrollThread ||
        (n.children || []).some(hasTask) || (n.finishedChildren || []).some(hasTask));
      let sectionIdx = tree.groups.findIndex(g => g.nodes.some(hasTask));
      if (sectionIdx < 0 && tree.finished.some(r => r.task === this.pendingScrollThread)) {
        sectionIdx = openGroupEls.length + (sessions.length ? 1 : 0);
      }
      if (sectionIdx >= 0) this.threadListScroll.scroll_to_item(sectionIdx);
      this.pendingScrollThread = '';
    }

    return v_flex().w(width).h_full().flex_none().pt(12).bg(t.chrome).border_l(1).border_color(t.border)
      .on_hover((over, cx) => { if (!over && this.hoverKey) this.leaveHover(this.hoverKey, cx); })
      .child(this.sideHeader(t, width))
      .child(v_flex().id('thread-list').flex_1().min_h(0).px(12).pt(8).pb(16).gap(12).overflow_y_scrollbar()
        .when(Boolean(this.threadListScroll), el => el.track_scroll(this.threadListScroll))
        .on_scroll_wheel((_e, cx) => { if (this.hoverKey) this.clearHoverNow(cx); })
        .children(sections.length ? sections : [div().px(8).text_size(13).text_color(t.dim).child(word(lang, 'noThreads'))]));
  }

  sideHeader(t, width = PANEL_WIDTH) {
    const lang = this.lang;
    if (!this.librarySupported()) {
      return h_flex().h(32).flex_none().px(20).items_center().text_size(15).font_semibold().child(word(lang, 'threads'));
    }
    const compact = width < 300;
    const active = this.sideTab === 'library' ? 'library'
      : (this.sideTab === 'memory' && this.memorySupported()) ? 'memory' : 'threads';
    const tab = (key, glyph, label) => this.withTip(`panel-tab-${key}`, h_flex().id(`panel-tab-${key}`).h(26).px(compact ? 6 : 9).gap(compact ? 3 : 5)
      .rounded(7).items_center().text_size(compact ? 12 : 12.5).accessibility_label(label)
      .when(key === active, el => el.bg(t.raised).text_color(t.foreground).font_medium())
      .when(key !== active, el => el.cursor_pointer().text_color(t.muted).hover(s => s.text_color(t.foreground))
        .on_click((_e, cx) => this.selectSideTab(key, cx)))
      .child(this.icon(glyph, compact ? 12.5 : 13.5)).child(label), label, t, { panel: true, placement: 'below-left' });
    return h_flex().h(34).flex_none().px(compact ? 12 : 16).items_center()
      .child(h_flex().id('panel-tabs').h(32).p(2).gap(2).rounded(9).border_1().border_color(t.border)
        .child(tab('threads', 'list', word(lang, 'threads')))
        .child(tab('library', 'library', word(lang, 'libraryTab')))
        .when(this.memorySupported(), el => el.child(tab('memory', 'memory', word(lang, 'memoryTab')))));
  }

  searchBox(id, state, query, placeholder, onClear, t) {
    const lang = this.lang;
    const hint = div().absolute().left(0).top(6).right(0).truncate().text_size(12.5).text_color(t.dim).child(placeholder);
    return keepPress(h_flex().id(id)).w_full().h(32).px(9).gap(7).rounded(9).items_center()
      .bg(t.surface).border_1().border_color(t.input || t.border)
      .child(this.icon('search', 14).text_color(t.dim))
      .child(div().relative().flex_1().min_w(0).h(28).when(!query, el => el.child(hint))
        .child(Input.new(state).w_full().h(28).items_center().text_size(12.5).text_color(t.foreground)))
      .when(Boolean(query), el => el.child(this.withTip(`${id}-clear`, h_flex().id(`${id}-clear`).size(20).flex_none().rounded(6).items_center()
        .justify_center().cursor_pointer().text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
        .accessibility_label(word(lang, 'clearSearch'))
        .on_click((_e, cx) => { cx.stop_propagation(); onClear(cx); })
        .child(this.icon('close', 11)), word(lang, 'clearSearch'), t, { panel: true, placement: 'below-right' })));
  }

  memoryTypeColor(type, t) {
    if (type === 'feedback') return t.ansi2 || t.accent;
    if (type === 'reference') return t.ansi4 || t.muted;
    if (type === 'user') return t.ansi3 || t.accent;
    if (type === 'pitfall') return t.dim || t.muted;
    return t.accent;
  }

  deletedBannerBar(tab, t) {
    const banner = this.deletedBanner;
    if (!banner || banner.tab !== tab) return null;
    const lang = this.lang;
    return h_flex().id('deleted-banner').mx(16).mt(6).px(10).py(5).gap(8).rounded(8).items_center()
      .bg(t.surface).border_1().border_color(t.border)
      .child(div().flex_1().min_w(0).truncate().text_size(12).text_color(t.muted).child(word(lang, 'deletedNotice', banner.name)))
      .child(this.iconButton('deleted-undo', 'restore', word(lang, 'undoDelete'), cx => this.undoDeletedBanner(cx), t, 14))
      .child(this.iconButton('deleted-dismiss', 'close', word(lang, 'dismissNotice'), cx => { this.deletedBanner = null; cx.notify(); }, t, 12));
  }

  libraryRow(row, t) {
    const lang = this.lang;
    if (row.folder) {
      return this.withTip(`lib-folder-${row.key}`, h_flex().id(`lib-folder-${row.key}`).h(28).pl(8 + row.depth * 14).pr(8).gap(7).rounded(8).items_center()
        .cursor_pointer().hover(s => s.bg(t.hover))
        .accessibility_label(`${row.name} · ${row.kindLabel}`)
        .on_click((_e, cx) => {
          if (this.libraryClosed.has(row.key)) this.libraryClosed.delete(row.key);
          else this.libraryClosed.add(row.key);
          cx.notify();
        })
        .child(h_flex().w(14).flex_none().items_center().justify_center().text_color(t.dim)
          .child(this.icon(row.open ? 'expand' : 'chevron', 12)))
        .child(this.icon('folder', 14).text_color(t.muted))
        .child(div().flex_1().min_w(0).truncate().text_size(13).text_color(t.foreground).child(row.name))
        .child(div().flex_none().text_size(11).text_color(t.dim).child(row.kindLabel)),
        `${row.root}/${row.path} · ${row.kindLabel}`, t, { panel: true, placement: 'above-left' });
    }
    const isImg = /^(png|jpe?g|gif|webp|bmp|avif)$/i.test(row.file?.kind || '');
    const glyphName = row.root === 'research' ? 'report' : isImg ? 'image' : 'file';
    const tip = [`${row.root}/${row.path}`, row.kindLabel, row.size, row.desc].filter(Boolean).join(' · ');
    const srcTip = row.task ? word(lang, 'openSourceThread', row.taskTitle || row.task) : '';
    return this.withTip(`lib-doc-${row.key}`, h_flex().id(`lib-doc-${row.key}`).pl(8 + row.depth * 14).pr(6).py(6).gap(9).rounded(8).items_start()
      .cursor_pointer().hover(s => s.bg(t.hover)).accessibility_label(tip)
      .when(row.archive, el => el.opacity(.75))
      .on_click((_e, cx) => this.openDoc({ tab: 'library', root: row.root, path: row.path }, cx))
      .child(h_flex().h(19).w(16).flex_none().items_center().justify_center().child(this.icon(glyphName, 14).text_color(t.dim)))
      .child(v_flex().flex_1().min_w(0).gap(1)
        .child(h_flex().gap(7).items_center()
          .child(div().flex_1().min_w(0).truncate().text_size(13).font_medium()
            .text_color(row.readable && !row.archive ? t.foreground : t.muted).child(row.title))
          .when(Boolean(row.published), el => el.child(div().flex_none().text_size(10.5).text_color(t.dim)
            .child(word(lang, 'publishedLabel'))))
          .when(row.root === 'docs', el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(row.kindLabel)))
          .when(Boolean(row.modified), el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(row.modified))))
        .when(Boolean(row.desc), el => el.child(div().truncate().text_size(12).text_color(t.dim).child(row.desc))))
      .when(Boolean(row.task), el => el.child(this.withTip(`lib-thread-${row.key}`, h_flex().id(`lib-thread-${row.key}`).size(24).flex_none().rounded(7).items_center()
        .justify_center().cursor_pointer().text_color(t.dim).hover(s => s.bg(t.raised).text_color(t.foreground))
        .accessibility_label(srcTip)
        .on_click((e, cx) => { e?.stop_propagation?.(); cx.stop_propagation?.(); this.openThread(row.task, cx); })
        .child(this.icon('hook-up', 13)), srcTip, t, { panel: true, placement: 'above-right' }))),
      tip, t, { panel: true, placement: 'above-left' });
  }

  memoryRow(row, t) {
    const tip = [`${row.root}/${row.path}`, row.typeLabel, row.topicLabel, row.desc].filter(Boolean).join(' · ');
    return this.withTip(`mem-doc-${row.key}`, h_flex().id(`mem-doc-${row.key}`).pl(8 + row.depth * 14).pr(8).py(6).gap(9).rounded(8).items_start()
      .cursor_pointer().hover(s => s.bg(t.hover)).accessibility_label(tip)
      .when(row.dimmed, el => el.opacity(.78))
      .on_click((_e, cx) => this.openDoc({ tab: 'memory', root: row.root, path: row.path }, cx))
      .child(h_flex().h(19).w(16).flex_none().items_center().justify_center()
        .child(div().size(7).rounded_full().bg(this.memoryTypeColor(row.type, t))))
      .child(v_flex().flex_1().min_w(0).gap(1)
        .child(h_flex().gap(6).items_center()
          .child(div().flex_1().min_w(0).truncate().text_size(13).font_medium()
            .text_color(row.dimmed ? t.muted : t.foreground).child(row.title))
          .child(div().flex_none().text_size(11).text_color(t.dim).child(row.typeLabel))
          .when(Boolean(row.modified), el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(row.modified))))
        .when(Boolean(row.desc), el => el.child(div().truncate().text_size(12).text_color(t.dim).child(row.desc)))),
      tip, t, { panel: true, placement: 'above-left' });
  }

  docDetailView(t, today) {
    const lang = this.lang;
    const docRef = this.activeDoc;
    const isRepo = docRef.root === 'repo';
    const key = `${docRef.root}/${docRef.path}`;
    const meta = this.findDocMeta(docRef.root, docRef.path);
    const ext = docRef.path.includes('.') ? docRef.path.split('.').pop().toLowerCase() : '';
    const docMeta = meta || (ext ? { ...docRef, kind: ext } : docRef);
    const mode = contextShowMode(meta, docRef.path);
    const cached = this.docCache.get(key);
    const loading = this.docLoading === key && !cached;
    const findQuery = this.docFindOpen ? this.docFindQuery : this.docJumpQuery;
    const vm = cached && mode === 'text'
      ? documentView(docMeta, cached.text, { lang, today, shownBytes: this.docShownBytes, findQuery })
      : null;
    const writable = meta ? isWritableDoc(meta) : (docRef.root === 'docs' || docRef.root === 'memory' || docRef.root === 'personal');
    const backTip = word(lang, isRepo ? 'docBackRepo' : docRef.tab === 'memory' ? 'docBackMemory' : 'docBackLibrary');
    const headerTitle = vm ? vm.title : (meta ? libraryDocTitle(meta) : fileName(docRef.path));
    const copiedPath = isRepo && this.pathCopiedAt && Date.now() - this.pathCopiedAt < 1800;

    const matchList = vm?.matchIndices || [];
    const safeMatchPos = matchList.length ? ((this.docMatchPos % matchList.length) + matchList.length) % matchList.length : 0;

    const topBar = h_flex().flex_none().px(14).pt(6).pb(6).gap(3).items_center().border_b(1).border_color(t.border)
      .child(this.iconButton('doc-back', 'back', backTip, cx => this.closeActiveDoc(cx), t, 15))
      .child(div().flex_1().min_w(0).truncate().text_size(13.5).font_semibold().child(headerTitle))
      .when(isRepo, el => el.child(this.iconButton('doc-copy-path', copiedPath ? 'check' : 'clip',
        word(lang, copiedPath ? 'mentionPathCopied' : 'mentionCopyPath'), cx => {
          cx.write_to_clipboard?.(docRef.path);
          this.pathCopiedAt = Date.now();
          cx.notify();
          cx.timer?.after?.(1800, cx => { this.pathCopiedAt = 0; cx.notify(); });
        }, t, 14)))
      .when(Boolean(meta?.task), el => el.child(this.iconButton('doc-source-thread', 'hook-up',
        word(lang, 'openSourceThread', meta.task_title || meta.task), cx => this.openThread(meta.task, cx), t, 14)))
      .when(Boolean(vm), el => el.child(this.withTip('doc-find-toggle', h_flex().id('doc-find-toggle').size(30).flex_none().rounded(8).items_center()
        .justify_center().cursor_pointer()
        .text_color(this.docFindOpen ? t.foreground : t.muted)
        .when(this.docFindOpen, s => s.bg(t.raised))
        .hover(s => s.bg(t.hover).text_color(t.foreground))
        .accessibility_label(word(lang, 'findInDoc'))
        .on_click((_e, cx) => {
          this.docFindOpen = !this.docFindOpen;
          if (this.docFindOpen) {
            if (!this.docFindQuery && this.docJumpQuery) {
              this.docFindQuery = this.docJumpQuery;
              this.docFindInput?.set_value(this.docJumpQuery);
            }
            this.docMatchPos = 0;
            this.docFindJump = Boolean(this.docFindQuery.trim());
            cx.timer.after(0, () => this.docFindInput?.focus());
          } else {
            this.docFindQuery = '';
            this.docMatchPos = 0;
            this.docFindInput?.set_value('');
          }
          cx.notify();
        })
        .child(this.icon('search', 14)), word(lang, 'findInDoc'), t, { panel: true, placement: 'below-right' })))
      .when(Boolean(writable && vm), el => el.child(this.iconButton('doc-edit', 'pencil',
        word(lang, 'editDoc'), cx => this.startEditDoc(cx), t, 14)))
      .when(Boolean(writable), el => el.child(this.iconButton('doc-history', 'history',
        word(lang, 'docHistory'), cx => this.openHistory(docRef.tab, docRef.root, docRef.path, 'item', cx), t, 14)))
      .when(Boolean(writable), el => el.child(this.iconButton('doc-delete', 'trash',
        word(lang, 'deleteItem'), cx => {
          this.confirmDeleteKey = this.confirmDeleteKey === key ? '' : key;
          this.deleteError = '';
          cx.notify();
        }, t, 14)));

    const deleteBar = this.confirmDeleteKey === key ? h_flex().id('doc-delete-bar').flex_none().mx(16).mt(6).px(10).py(5)
      .gap(8).rounded(8).items_center().bg(withAlpha(t.blocked, .12)).border_1().border_color(withAlpha(t.blocked, .35))
      .child(div().flex_1().min_w(0).whitespace_normal().text_size(12).text_color(t.foreground)
        .child(word(lang, 'confirmDeleteHint')))
      .child(this.deleteBusy === key
        ? svg(SPINNER).size(14).flex_none().spin(900)
        : this.iconButton('doc-delete-confirm', 'check', word(lang, 'confirmDelete'), cx => this.deleteActiveDoc(cx), t, 14)
            .text_color(t.blocked))
      .child(this.iconButton('doc-delete-cancel', 'close', word(lang, 'cancelDelete'), cx => {
        this.confirmDeleteKey = ''; this.deleteError = ''; cx.notify();
      }, t, 13)) : null;

    const findBar = this.docFindOpen && vm ? v_flex().flex_none().px(16).pt(8).gap(4)
      .child(this.searchBox('doc-find-box', this.docFindInput, this.docFindQuery, word(lang, 'findPlaceholder'), cx => {
        this.docFindQuery = '';
        this.docMatchPos = 0;
        this.docFindInput.set_value('');
        this.docFindInput.focus();
        cx.notify();
      }, t))
      .when(Boolean(this.docFindQuery.trim()), el => el.child(h_flex().px(2).gap(6).items_center()
        .child(div().flex_1().text_size(11.5).text_color(vm.matchCount ? t.muted : t.dim)
          .child(vm.matchCount
            ? (matchList.length > 1 ? `${word(lang, 'findMatches', vm.matchCount)} · ${word(lang, 'findProgress', safeMatchPos + 1, matchList.length)}`
              : word(lang, 'findMatches', vm.matchCount))
            : word(lang, 'noFindMatches')))
        .when(matchList.length > 1, sub => sub
          .child(this.iconButton('doc-find-prev', 'up', word(lang, 'findPrevMatch'), cx => {
            this.docMatchPos = (safeMatchPos - 1 + matchList.length) % matchList.length;
            this.docFindJump = true;
            cx.notify();
          }, t, 12))
          .child(this.iconButton('doc-find-next', 'expand', word(lang, 'findNextMatch'), cx => {
            this.docMatchPos = (safeMatchPos + 1) % matchList.length;
            this.docFindJump = true;
            cx.notify();
          }, t, 12))))) : null;

    const topicPill = vm?.isMemory && !vm.isPersonal ? this.withTip('doc-retopic-toggle', h_flex().id('doc-retopic-toggle').h(22).px(8).gap(4).rounded(7).items_center()
      .bg(t.surface).border_1().border_color(this.retopicOpen ? t.accent : t.border)
      .text_size(11.5).text_color(t.muted).cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
      .accessibility_label(word(lang, 'retopicTip'))
      .on_click((_e, cx) => { this.retopicOpen = !this.retopicOpen; this.retopicError = ''; cx.notify(); })
      .child(this.icon('folder', 11.5)).child(vm.topicLabel), word(lang, 'retopicTip'), t, { panel: true, placement: 'below-left' }) : null;

    const typePill = vm
      ? (() => {
          const base = this.pill(vm.isMemory ? `${vm.layerLabel} · ${vm.typeLabel}` : vm.typeLabel,
            vm.isMemory ? this.memoryTypeColor(vm.type, t) : t.muted);
          if (!vm.isMemory || !vm.isPersonal) return base;
          return this.withTip('doc-retopic-toggle', h_flex().id('doc-retopic-toggle').rounded(99).cursor_pointer()
            .when(this.retopicOpen, el => el.border_1().border_color(t.accent))
            .accessibility_label(word(lang, 'retopicTip'))
            .on_click((_e, cx) => { this.retopicOpen = !this.retopicOpen; this.retopicError = ''; cx.notify(); })
            .child(base), word(lang, 'retopicTip'), t, { panel: true, placement: 'below-left' });
        })()
      : null;

    const metaRow = h_flex().flex_wrap().gap(6).items_center().text_size(11.5).text_color(t.dim)
      .when(Boolean(vm?.readOnly), el => el.child(h_flex().h(22).px(8).gap(4).rounded(7).items_center()
        .bg(t.surface).border_1().border_color(t.border).text_color(t.muted)
        .child(this.icon('lock', 11)).child(word(lang, 'readOnly'))))
      .when(Boolean(typePill), el => el.child(typePill))
      .when(Boolean(topicPill), el => el.child(topicPill))
      .when(Boolean(vm?.expired), el => el.child(this.pill(word(lang, 'memExpired'), t.blocked)))
      .when(Boolean(vm?.modified || meta?.modified), el => el.child(div().child(vm?.modified || '')))
      .when(Boolean(meta?.size || cached?.size), el => el.child(div().child(formatBytes(meta?.size ?? cached?.size ?? 0))))
      .when(Boolean(vm?.byLabel), el => el.child(div().child(vm.byLabel)));

    const retopicPicker = this.retopicOpen && vm?.isMemory && meta ? (() => {
      const allowedTypes = vm.isPersonal ? PERSONAL_MEMORY_TYPES : PROJECT_MEMORY_TYPES;
      const chip = (id, active, label, onClick) => h_flex().id(id).h(22).px(8).rounded(7).items_center()
        .text_size(11.5).cursor_pointer()
        .when(active, el => el.bg(withAlpha(t.accent, .18)).text_color(t.accent).font_medium())
        .when(!active, el => el.bg(t.raised).text_color(t.muted).hover(s => s.bg(t.hover).text_color(t.foreground)))
        .on_click(onClick)
        .child(label);
      return v_flex().id('doc-retopic-picker').w_full().p(8).gap(6).rounded(10).bg(t.surface).border_1().border_color(t.border)
        .when(!vm.isPersonal, el => el.child(h_flex().flex_wrap().gap(5)
          .children(MEMORY_TOPICS.map(tid => chip(`retopic-${tid}`, vm.topic === tid, topicLabel(lang, tid),
            (_e, cx) => this.applyRetopic(tid, '', cx))))))
        .child(h_flex().flex_wrap().gap(5)
          .children(allowedTypes.map(ty => chip(`retype-${ty}`, vm.type === ty, memoryTypeLabel(lang, ty),
            (_e, cx) => this.applyRetopic('', ty, cx)))))
        .when(Boolean(this.retopicError), el => el.child(div().text_size(11.5).text_color(t.blocked).whitespace_normal()
          .child(this.retopicError)));
    })() : null;

    const srcNum = vm?.sourceTask ? formatTaskNumber(this.taskNumberFor(vm.sourceTask)) : '';
    const sourceLinkRow = vm?.sourceTask ? this.withTip('doc-source-row', h_flex().id('doc-source-row').gap(6).items_center().cursor_pointer()
      .text_size(12).text_color(t.muted).hover(s => s.text_color(t.foreground))
      .on_click((_e, cx) => this.openThread(vm.sourceTask, cx))
      .child(this.icon('hook-up', 12.5))
      .when(Boolean(srcNum), el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(srcNum)))
      .child(div().min_w(0).truncate().child(vm.sourceTaskTitle || vm.sourceTask)),
      word(lang, 'openSourceThread', vm.sourceTaskTitle || vm.sourceTask), t, { panel: true, placement: 'above-left' }) : null;

    const provenance = vm?.isMemory && (vm.quotes.length || vm.verified || vm.checked || vm.expires)
      ? v_flex().w_full().p(10).gap(4).rounded(10).bg(t.surface).border_1().border_color(t.border).text_size(12).text_color(t.muted)
        .children(vm.quotes.map(q => div().whitespace_normal().text_color(t.foreground).child(word(lang, 'memQuote', q))))
        .when(Boolean(vm.quoteStatus), el => el.child(div().text_size(11.5)
          .text_color(vm.quoteStatus === 'checked' ? (t.ansi2 || t.accent) : t.dim)
          .child(word(lang, vm.quoteStatus === 'checked' ? 'memQuoteChecked' : 'memQuoteUnchecked'))))
        .when(Boolean(vm.verified), el => el.child(div().whitespace_normal().child(vm.verified)))
        .when(Boolean(vm.checked || vm.expires), el => el.child(div().text_size(11.5).text_color(t.dim)
          .child([vm.checked, vm.expires].filter(Boolean).join(' · '))))
      : null;

    const matchedSet = new Set(matchList);
    const highlightActive = Boolean(findQuery && String(findQuery).trim() && matchedSet.size);
    const bodyChildren = [];
    bodyChildren.push(div().font_family('monospace').text_size(11).text_color(t.dim).whitespace_normal()
      .child(isRepo ? docRef.path : `${docRef.root} / ${docRef.path.split('/').join(' / ')}`));
    bodyChildren.push(metaRow);
    if (retopicPicker) bodyChildren.push(retopicPicker);
    if (sourceLinkRow) bodyChildren.push(sourceLinkRow);
    if (this.deleteError) bodyChildren.push(div().text_size(12).text_color(t.blocked).whitespace_normal().child(this.deleteError));
    if (provenance) bodyChildren.push(provenance);

    const chunkStartIndex = bodyChildren.length;
    if (loading) {
      bodyChildren.push(h_flex().pt(8).gap(8).items_center().text_size(12.5).text_color(t.dim)
        .child(svg(SPINNER).size(14).flex_none().spin(900)).child(word(lang, 'docLoading')));
    } else if (mode === 'large') {
      bodyChildren.push(div().pt(6).whitespace_normal().text_size(12.5).text_color(t.muted).child(word(lang, 'docTooLarge')));
    } else if (mode === 'binary') {
      bodyChildren.push(div().pt(6).whitespace_normal().text_size(12.5).text_color(t.muted).child(word(lang, 'docNotText')));
    } else if (this.docError) {
      bodyChildren.push(h_flex().pt(6).gap(8).items_start()
        .child(div().flex_1().min_w(0).whitespace_normal().text_size(12.5).text_color(t.blocked).child(this.docError))
        .child(this.iconButton('doc-retry', 'reattach', word(lang, 'docRetry'),
          cx => this.readDoc(docRef.root, docRef.path, cx, { force: true }), t, 14)));
    } else if (vm) {
      vm.chunks.forEach((chunk, idx) => {
        const hit = highlightActive && matchedSet.has(idx);
        bodyChildren.push(div().id(`doc-chunk-${key}-${idx}`).w_full().text_size(13.5).text_color(t.foreground)
          .when(hit, el => el.pl(8).border_l(2).border_color(t.accent))
          .child(TextView.markdown(`doc-md-${key}-${idx}`, chunk).selectable(true)
            .on_link_click((url, cx) => this.followDocLink(url, cx))));
      });
      if (vm.remainingBytes > 0) {
        const moreTip = word(lang, 'docShowMore', vm.remainingLabel);
        bodyChildren.push(this.withTip('doc-show-more', h_flex().id('doc-show-more').h(30).px(10).gap(7).rounded(8).items_center().cursor_pointer()
          .text_size(12.5).text_color(t.muted).hover(s => s.bg(t.hover).text_color(t.foreground))
          .accessibility_label(moreTip)
          .on_click((_e, cx) => {
            this.docShownBytes = Math.max(this.docShownBytes, (cached?.text?.length || 0) - vm.remainingBytes) + DOC_INITIAL_BYTES;
            cx.notify();
          })
          .child(this.icon('expand', 14)).child(moreTip), moreTip, t, { panel: true, placement: 'above-left' }));
      }
    }

    if (this.docFindJump && vm && matchList.length) {
      this.docFindJump = false;
      this.docScroll.scroll_to_item(chunkStartIndex + matchList[safeMatchPos]);
    } else if (this.docFindJump && vm) {
      this.docFindJump = false;
    }

    return v_flex().flex_1().min_h(0)
      .child(topBar)
      .when(Boolean(deleteBar), el => el.child(deleteBar))
      .when(Boolean(findBar), el => el.child(findBar))
      .child(v_flex().id('doc-detail-body').flex_1().min_h(0).px(18).pt(10).pb(20).gap(10).overflow_y_scrollbar()
        .track_scroll(this.docScroll)
        .children(bodyChildren));
  }

  docEditView(t, cx) {
    const lang = this.lang;
    const ed = this.editingDoc;
    const isMem = ed.tab === 'memory';
    const title = ed.mode === 'create'
      ? word(lang, isMem ? 'newMemory' : 'newDoc')
      : (isMem ? ed.originalName : fileName(ed.path));
    const saveControl = ed.saving
      ? this.withTip('doc-edit-save', h_flex().id('doc-edit-save').size(32).flex_none().rounded(9).items_center().justify_center()
          .accessibility_label(word(lang, 'savingEdit'))
          .child(svg(SPINNER).size(14).flex_none().spin(900)), word(lang, 'savingEdit'), t, { panel: true, placement: 'below-right' })
      : this.iconButton('doc-edit-save', 'check', word(lang, 'saveEdit'), cx => this.saveEditingDoc(cx), t, 15, { panel: true, placement: 'below-right' });
    const topBar = h_flex().flex_none().px(14).pt(6).pb(6).gap(4).items_center().border_b(1).border_color(t.border)
      .child(this.iconButton('doc-edit-cancel', 'close', word(lang, 'cancelEdit'), cx => this.cancelEditDoc(cx), t, 14))
      .child(div().flex_1().min_w(0).truncate().text_size(13.5).font_semibold().child(title))
      .child(saveControl);

    const chip = (id, active, label, onClick) => h_flex().id(id).h(22).px(8).rounded(7).items_center()
      .text_size(11.5).cursor_pointer()
      .when(active, el => el.bg(withAlpha(t.accent, .18)).text_color(t.accent).font_medium())
      .when(!active, el => el.bg(t.surface).border_1().border_color(t.border).text_color(t.muted).hover(s => s.bg(t.hover).text_color(t.foreground)))
      .on_click(onClick)
      .child(label);

    const inputRow = (id, state, val, placeholder) => {
      const hint = div().absolute().left(0).top(6).right(0).truncate().text_size(12.5).text_color(t.dim).child(placeholder);
      return keepPress(h_flex().id(id)).w_full().h(32).px(9).rounded(9).items_center()
        .bg(t.surface).border_1().border_color(t.input || t.border)
        .child(div().relative().flex_1().min_w(0).h(28).when(!val, el => el.child(hint))
          .child(Input.new(state).w_full().h(28).items_center().text_size(12.5).text_color(t.foreground)));
    };

    const allowedTypes = ed.layer === 'personal' ? PERSONAL_MEMORY_TYPES : PROJECT_MEMORY_TYPES;

    return v_flex().id('doc-edit-view').flex_1().min_h(0)
      .on_key_down((e, cx) => {
        if (e.keystroke === 'cmd-s' || e.keystroke === 'ctrl-s') {
          cx.stop_propagation();
          this.saveEditingDoc(cx);
        }
      })
      .child(topBar)
      .when(Boolean(ed.conflict), el => el.child(h_flex().id('doc-conflict-bar').mx(16).mt(8).px(10).py(6).gap(6)
        .rounded(8).items_center().bg(withAlpha(t.blocked, .12)).border_1().border_color(withAlpha(t.blocked, .35))
        .child(div().flex_1().min_w(0).whitespace_normal().text_size(12).text_color(t.foreground)
          .child(word(lang, 'conflictNotice')))
        .child(this.iconButton('doc-conflict-reload', 'reattach', word(lang, 'conflictReload'), cx => this.reloadConflictDoc(cx), t, 14))
        .child(this.iconButton('doc-conflict-overwrite', 'check', word(lang, 'conflictOverwrite'),
          cx => this.saveEditingDoc(cx, { overwrite: true }), t, 14).text_color(t.blocked))))
      .when(Boolean(ed.error), el => el.child(div().px(16).pt(6).whitespace_normal().text_size(12).text_color(t.blocked)
        .child(ed.error)))
      .child(v_flex().flex_1().min_h(0).px(16).pt(10).pb(16).gap(8)
        .when(!isMem && ed.mode === 'create', el => el.child(
          inputRow('doc-edit-name', this.docNameInput, this.docNameInput.value(), word(lang, 'docNamePlaceholder')),
        ))
        .when(isMem && ed.mode === 'create', el => el.child(h_flex().gap(6).items_center()
          .child(chip('mem-layer-project', ed.layer !== 'personal', word(lang, 'memLayerProject'), (_e, cx) => {
            ed.layer = 'project'; ed.root = 'memory';
            if (!PROJECT_MEMORY_TYPES.includes(ed.type)) ed.type = 'project';
            cx.notify();
          }))
          .child(chip('mem-layer-personal', ed.layer === 'personal', word(lang, 'memLayerUser'), (_e, cx) => {
            ed.layer = 'personal'; ed.root = 'personal';
            if (!PERSONAL_MEMORY_TYPES.includes(ed.type)) ed.type = 'user';
            if (ed.topic === 'pitfalls') ed.topic = 'workflow';
            cx.notify();
          }))))
        .when(isMem && ed.mode === 'create', el => el.child(
          inputRow('mem-edit-name', this.docNameInput, this.docNameInput.value(), word(lang, 'memNamePlaceholder')),
        ))
        .when(isMem, el => el.child(h_flex().flex_wrap().gap(5)
          .children(allowedTypes.map(ty => chip(`edit-type-${ty}`, ed.type === ty, memoryTypeLabel(lang, ty), (_e, cx) => {
            const next = retopicPlan({ layer: ed.layer, type: ed.type, topic: ed.topic }, { nextType: ty });
            ed.type = next.type;
            ed.topic = next.topic;
            cx.notify();
          })))))
        .when(isMem && ed.layer !== 'personal', el => el.child(h_flex().flex_wrap().gap(5)
          .children(MEMORY_TOPICS.map(tid => chip(`edit-topic-${tid}`, ed.topic === tid, topicLabel(lang, tid), (_e, cx) => {
            const next = retopicPlan({ layer: ed.layer, type: ed.type, topic: ed.topic }, { nextTopic: tid });
            ed.type = next.type;
            ed.topic = next.topic;
            cx.notify();
          })))))
        .when(isMem, el => el.child(
          inputRow('mem-edit-desc', this.memDescInput, this.memDescInput.value(), word(lang, 'memDescPlaceholder')),
        ))
        .child(keepPress(v_flex().id('doc-editor-box')).flex_1().min_h(160).w_full().p(10).rounded(10)
          .bg(t.surface).border_1().border_color(t.input || t.border)
          .child(div().relative().flex_1().min_h(0).w_full()
            .when(!this.docEditorInput.value(), el => el.child(div().absolute().left(0).top(0).right(0).truncate()
              .text_size(13).text_color(t.dim).child(word(lang, isMem ? 'memBodyPlaceholder' : 'docBodyPlaceholder'))))
            .child(Textarea.new(this.docEditorInput).w_full().h_full().min_h(140).text_size(13).text_color(t.foreground)))));
  }

  historySubView(t, today, cx) {
    const lang = this.lang;
    const hv = this.historyView;
    const currentYear = String(today || '').slice(0, 4);
    const title = hv.scope === 'item' && hv.path
      ? `${fileName(hv.path)} · ${word(lang, 'historyTitle')}`
      : word(lang, 'historyTitle');
    const topBar = h_flex().flex_none().px(14).pt(6).pb(6).gap(4).items_center().border_b(1).border_color(t.border)
      .child(this.iconButton('history-back', 'back', word(lang, 'close'), cx => this.closeHistory(cx), t, 15))
      .child(div().flex_1().min_w(0).truncate().text_size(13.5).font_semibold().child(title));

    let body;
    if (hv.loading && !hv.items.length) {
      body = [h_flex().px(8).pt(4).gap(8).items_center().text_size(12.5).text_color(t.dim)
        .child(svg(SPINNER).size(14).flex_none().spin(900)).child(word(lang, 'historyLoading'))];
    } else if (hv.error) {
      body = [div().px(8).whitespace_normal().text_size(12.5).text_color(t.blocked).child(hv.error)];
    } else if (!hv.items.length) {
      body = [div().px(8).text_size(12.5).text_color(t.dim).child(word(lang, 'historyEmpty'))];
    } else {
      body = hv.items.map((item, i) => {
        const busy = hv.restoring === `${item.root}/${item.path}@${item.version}`;
        const whyLabel = word(lang, item.why === 'deleted' || item.why === 'forgotten' ? 'historyWhyDeleted' : 'historyWhyReplaced');
        const label = item.name || item.path;
        const layerText = item.root === 'personal' ? word(lang, 'memLayerUser')
          : item.root === 'memory' ? word(lang, 'memLayerProject') : '';
        return h_flex().id(`history-item-${i}`).px(8).py(6).gap(8).rounded(8).items_start()
          .hover(s => s.bg(t.hover))
          .child(v_flex().flex_1().min_w(0).gap(2)
            .child(h_flex().gap(6).items_center()
              .child(div().flex_1().min_w(0).truncate().text_size(13).font_medium().text_color(t.foreground).child(label))
              .when(Boolean(layerText), el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(layerText)))
              .child(div().flex_none().text_size(11).text_color(item.why === 'deleted' || item.why === 'forgotten' ? t.blocked : t.dim)
                .child(whyLabel))
              .child(div().flex_none().text_size(11).text_color(t.dim).child(formatHistoryStamp(item.version, currentYear))))
            .when(Boolean(item.description), el => el.child(div().truncate().text_size(12).text_color(t.dim).child(item.description))))
          .child(busy
            ? h_flex().size(28).flex_none().items_center().justify_center().child(svg(SPINNER).size(13).flex_none().spin(900))
            : this.iconButton(`history-restore-${i}`, 'restore', word(lang, 'restoreVersion'),
                cx => this.restoreHistoryItem(item, cx), t, 14));
      });
    }

    return v_flex().id('history-view').flex_1().min_h(0)
      .child(topBar)
      .child(v_flex().id('history-list').flex_1().min_h(0).px(12).pt(8).pb(16).gap(4).overflow_y_scrollbar()
        .track_scroll(this.historyScroll)
        .children(body));
  }

  libraryPanel(pm, t, width, today, cx) {
    const lang = this.lang;
    const currentYear = String(today || '').slice(0, 4);
    const wrap = child => v_flex().id('library-panel').w(width).h_full().flex_none().pt(12).bg(t.chrome)
      .border_l(1).border_color(t.border)
      .on_drop((e, cx) => this.dropLibraryFiles(e?.paths || [], cx))
      .child(this.sideHeader(t, width))
      .child(child);

    if (this.historyView?.tab === 'library') return wrap(this.historySubView(t, today, cx));
    if (this.editingDoc?.tab === 'library') return wrap(this.docEditView(t, cx));
    if (this.activeDoc?.tab === 'library') return wrap(this.docDetailView(t, today));

    const q = String(this.libraryQuery || '').trim();
    const groups = q ? [] : libraryGroups(this.libraryFiles, this.libraryClosed, lang, currentYear);
    const hits = q ? searchLibrary(this.libraryFiles, q, this.docCache, lang, currentYear) : [];
    const hasAnyRows = groups.some(sec => sec.rows.length > 0);
    const groupEl = sec => v_flex().gap(1)
      .child(h_flex().h(26).px(8).gap(6).items_center().text_size(11).font_medium().text_color(t.dim)
        .child(sec.title).child(String(sec.count))
        .when(sec.readOnly, el => el.child(div().flex_1())
          .child(h_flex().gap(3).items_center().text_size(10.5).text_color(t.dim)
            .child(this.icon('lock', 10)).child(word(lang, 'readOnly')))))
      .children(sec.rows.length
        ? sec.rows.map(r => this.libraryRow(r, t))
        : (sec.id === 'docs' ? [div().px(8).py(4).text_size(12).text_color(t.dim).child(word(lang, 'libraryDropHint'))] : []));

    let listChildren;
    if (this.libraryLoading && !this.libraryRead && !this.libraryFiles.length) {
      listChildren = [h_flex().px(8).pt(4).gap(8).items_center().text_size(13).text_color(t.dim)
        .child(svg(SPINNER).size(14).flex_none().spin(900)).child(word(lang, 'libraryLoading'))];
    } else if (this.libraryError && !this.libraryRead && !this.libraryFiles.length) {
      listChildren = [div().px(8).whitespace_normal().text_size(12.5).text_color(t.blocked)
        .child(word(lang, 'libraryReadError', this.libraryError))];
    } else if (q) {
      listChildren = hits.length
        ? [v_flex().gap(1).children(hits.map(r => this.libraryRow(r, t)))]
        : [div().px(8).text_size(13).text_color(t.dim).child(word(lang, 'libraryNoMatches'))];
    } else {
      listChildren = hasAnyRows
        ? groups.map(groupEl)
        : [div().px(8).whitespace_normal().text_size(13).text_color(t.dim).child(word(lang, 'libraryEmpty'))];
    }

    const toolbar = h_flex().flex_none().px(16).pt(8).pb(4).gap(4).items_center()
      .child(div().flex_1().min_w(0).child(this.searchBox('library-search', this.libraryInput, this.libraryQuery, word(lang, 'searchLibrary'), cx => {
        this.libraryQuery = '';
        this.libraryInput.set_value('');
        this.libraryInput.focus();
        cx.notify();
      }, t)))
      .child(this.iconButton('library-new-doc', 'plus', word(lang, 'newDoc'), cx => this.startNewDoc('library', cx), t, 15))
      .child(this.iconButton('library-add-file', 'upload', word(lang, 'addFiles'), cx => this.pickLibraryFiles(cx), t, 15))
      .child(this.iconButton('library-history', 'history', word(lang, 'docHistory'),
        cx => this.openHistory('library', 'docs', '', 'all', cx), t, 15));

    return v_flex().id('library-panel').w(width).h_full().flex_none().pt(12).bg(t.chrome).border_l(1).border_color(t.border)
      .on_drop((e, cx) => this.dropLibraryFiles(e?.paths || [], cx))
      .child(this.sideHeader(t, width))
      .child(toolbar)
      .when(Boolean(this.deletedBanner?.tab === 'library'), el => el.child(this.deletedBannerBar('library', t)))
      .when(Boolean(this.libraryDropBusy), el => el.child(h_flex().px(20).pb(4).gap(6).items_center().text_size(11.5).text_color(t.dim)
        .child(svg(SPINNER).size(12).flex_none().spin(900)).child(word(lang, 'addingFiles', this.libraryDropBusy))))
      .when(Boolean(this.libraryDropError), el => el.child(h_flex().px(20).pb(4).gap(6).items_start()
        .child(div().flex_1().min_w(0).whitespace_normal().text_size(11.5).text_color(t.blocked).child(this.libraryDropError))
        .child(this.iconButton('library-drop-err-close', 'close', word(lang, 'dismissNotice'),
          cx => { this.libraryDropError = ''; cx.notify(); }, t, 11))))
      .when(Boolean(this.libraryError && this.libraryRead), el => el.child(div().px(20).pb(4).whitespace_normal()
        .text_size(11.5).text_color(t.blocked).child(word(lang, 'libraryStale', this.libraryError))))
      .child(v_flex().id('library-list').flex_1().min_h(0).px(12).pt(4).pb(16).gap(12).overflow_y_scrollbar()
        .track_scroll(this.libraryScroll)
        .children(listChildren));
  }

  memoryPanel(pm, t, width, today, cx) {
    const lang = this.lang;
    const currentYear = String(today || '').slice(0, 4);
    const wrap = child => v_flex().id('memory-panel').w(width).h_full().flex_none().pt(12).bg(t.chrome)
      .border_l(1).border_color(t.border)
      .on_drop((e, cx) => this.dropMemoryFiles(e?.paths || [], cx))
      .child(this.sideHeader(t, width))
      .child(child);

    if (this.historyView?.tab === 'memory') return wrap(this.historySubView(t, today, cx));
    if (this.editingDoc?.tab === 'memory') return wrap(this.docEditView(t, cx));
    if (this.activeDoc?.tab === 'memory') return wrap(this.docDetailView(t, today));

    const q = String(this.memoryQuery || '').trim();
    const groups = !q && this.memoryData
      ? memoryGroups(this.memoryData, {
          foldOverrides: this.memoryFoldOverrides,
          projectOpen: this.memoryProjectOpen,
          personalOpen: this.memoryPersonalOpen,
          candidatesOpen: this.memoryCandidatesOpen,
        }, lang, currentYear)
      : null;
    const hits = q && this.memoryData ? searchMemory(this.memoryData, q, this.docCache, lang, currentYear) : [];

    const topicBlock = topic => v_flex().gap(1).when(topic.dimmed, el => el.opacity(.82))
      .child(h_flex().id(`mem-topic-${topic.id}`).h(28).pl(8).pr(8).gap(7).rounded(8).items_center()
        .cursor_pointer().hover(s => s.bg(t.hover)).accessibility_label(`${topic.title} · ${topic.count}`)
        .on_click((_e, cx) => {
          this.memoryFoldOverrides.set(topic.key, !topic.open);
          cx.notify();
        })
        .child(h_flex().w(14).flex_none().items_center().justify_center().text_color(t.dim)
          .child(this.icon(topic.open ? 'expand' : 'chevron', 12)))
        .child(this.icon('folder', 14).text_color(topic.dimmed ? t.dim : t.muted))
        .child(div().flex_1().min_w(0).truncate().text_size(13)
          .text_color(topic.dimmed ? t.muted : t.foreground).child(topic.title))
        .child(div().flex_none().text_size(11).text_color(t.dim).child(String(topic.count))))
      .when(topic.open, el => el.children(topic.rows.map(r => this.memoryRow(r, t))));

    const candidatesBlock = cands => v_flex().pt(4).gap(2).border_t(1).border_color(t.border).opacity(.82)
      .child(h_flex().id('mem-candidates').h(28).px(8).gap(7).rounded(8).items_center()
        .cursor_pointer().hover(s => s.bg(t.hover)).accessibility_label(`${cands.title} · ${cands.count}`)
        .on_click((_e, cx) => { this.memoryCandidatesOpen = !this.memoryCandidatesOpen; cx.notify(); })
        .child(h_flex().w(14).flex_none().items_center().justify_center().text_color(t.dim)
          .child(this.icon(cands.open ? 'expand' : 'chevron', 12)))
        .child(this.icon('folder', 14).text_color(t.dim))
        .child(div().flex_1().min_w(0).truncate().text_size(13).text_color(t.muted).child(cands.title))
        .child(div().flex_none().text_size(11).text_color(t.dim).child(String(cands.count))))
      .when(cands.open, el => el.children(cands.rows.map(c => h_flex().id(`mem-cand-${c.path}`).pl(22).pr(6).py(5).gap(6)
        .rounded(8).items_start().hover(s => s.bg(t.hover))
        .child(v_flex().flex_1().min_w(0).gap(1)
          .child(h_flex().gap(6).items_center()
            .child(div().flex_1().min_w(0).truncate().text_size(12.5).font_medium().text_color(t.foreground).child(c.name))
            .child(div().flex_none().text_size(11).text_color(t.dim).child(c.worker)))
          .when(Boolean(c.description), el => el.child(div().truncate().text_size(12).text_color(t.dim).child(c.description))))
        .child(this.iconButton(`cand-adopt-${c.path}`, 'check', word(lang, 'candidateAdopt'),
          cx => this.handleCandidate(c, false, cx), t, 13))
        .child(this.iconButton(`cand-drop-${c.path}`, 'trash', word(lang, 'candidateDiscard'),
          cx => this.handleCandidate(c, true, cx), t, 13)))));

    let listChildren;
    if (this.memoryLoading && !this.memoryRead && !this.memoryData) {
      listChildren = [h_flex().px(8).pt(4).gap(8).items_center().text_size(13).text_color(t.dim)
        .child(svg(SPINNER).size(14).flex_none().spin(900)).child(word(lang, 'memoryLoading'))];
    } else if (this.memoryError && !this.memoryRead && !this.memoryData) {
      listChildren = [div().px(8).whitespace_normal().text_size(12.5).text_color(t.blocked)
        .child(word(lang, 'memoryReadError', this.memoryError))];
    } else if (q) {
      listChildren = hits.length
        ? [v_flex().gap(1).children(hits.map(r => this.memoryRow(r, t)))]
        : [div().px(8).text_size(13).text_color(t.dim).child(word(lang, 'memoryNoMatches'))];
    } else if (!groups || (!groups.project.count && !groups.personal.count && !groups.candidates.count)) {
      listChildren = [div().px(8).text_size(13).text_color(t.dim).child(word(lang, 'memoryEmpty'))];
    } else {
      listChildren = [];
      if (groups.project.count > 0) {
        listChildren.push(v_flex().gap(2)
          .child(h_flex().id('mem-section-project').h(26).px(8).gap(6).rounded(7).items_center().cursor_pointer()
            .hover(s => s.bg(t.hover)).text_size(11).font_medium().text_color(t.dim)
            .on_click((_e, cx) => { this.memoryProjectOpen = !this.memoryProjectOpen; cx.notify(); })
            .child(this.icon(groups.project.open ? 'expand' : 'chevron', 11))
            .child(groups.project.title).child(String(groups.project.count)))
          .when(groups.project.open, el => el
            .children(groups.project.primaryTopics.map(topicBlock))
            .when(groups.project.foldedTopics.length > 0, sub => sub.child(v_flex().pt(4).gap(2)
              .border_t(1).border_color(t.border)
              .children(groups.project.foldedTopics.map(topicBlock))))));
      }
      if (groups.candidates.count > 0) {
        listChildren.push(candidatesBlock(groups.candidates));
      }
      if (groups.personal.count > 0) {
        listChildren.push(v_flex().pt(4).gap(2).border_t(1).border_color(t.border)
          .child(h_flex().id('mem-section-personal').h(26).px(8).gap(6).rounded(7).items_center().cursor_pointer()
            .hover(s => s.bg(t.hover)).text_size(11).font_medium().text_color(t.dim)
            .on_click((_e, cx) => { this.memoryPersonalOpen = !this.memoryPersonalOpen; cx.notify(); })
            .child(this.icon(groups.personal.open ? 'expand' : 'chevron', 11))
            .child(groups.personal.title).child(String(groups.personal.count)))
          .when(groups.personal.open, el => el.children(groups.personal.rows.map(r => this.memoryRow(r, t)))));
      }
    }

    const toolbar = h_flex().flex_none().px(16).pt(8).pb(4).gap(4).items_center()
      .child(div().flex_1().min_w(0).child(this.searchBox('memory-search', this.memoryInput, this.memoryQuery, word(lang, 'searchMemory'), cx => {
        this.memoryQuery = '';
        this.memoryInput.set_value('');
        this.memoryInput.focus();
        cx.notify();
      }, t)))
      .child(this.iconButton('memory-new', 'plus', word(lang, 'newMemory'), cx => this.startNewDoc('memory', cx), t, 15))
      .child(this.iconButton('memory-history', 'history', word(lang, 'docHistory'),
        cx => this.openHistory('memory', 'memory', '', 'all', cx), t, 15));

    return v_flex().id('memory-panel').w(width).h_full().flex_none().pt(12).bg(t.chrome).border_l(1).border_color(t.border)
      .on_drop((e, cx) => this.dropMemoryFiles(e?.paths || [], cx))
      .child(this.sideHeader(t, width))
      .child(toolbar)
      .when(Boolean(this.deletedBanner?.tab === 'memory'), el => el.child(this.deletedBannerBar('memory', t)))
      .when(Boolean(this.memoryBusy), el => el.child(h_flex().px(20).pb(4).gap(6).items_center().text_size(11.5).text_color(t.dim)
        .child(svg(SPINNER).size(12).flex_none().spin(900)).child(word(lang, 'addingFiles', this.memoryBusy))))
      .when(Boolean(this.memoryNoticeError), el => el.child(h_flex().px(20).pb(4).gap(6).items_start()
        .child(div().flex_1().min_w(0).whitespace_normal().text_size(11.5).text_color(t.blocked).child(this.memoryNoticeError))
        .child(this.iconButton('memory-err-close', 'close', word(lang, 'dismissNotice'),
          cx => { this.memoryNoticeError = ''; cx.notify(); }, t, 11))))
      .when(Boolean(this.memoryError && this.memoryRead), el => el.child(div().px(20).pb(4).whitespace_normal()
        .text_size(11.5).text_color(t.blocked).child(word(lang, 'memoryStale', this.memoryError))))
      .child(v_flex().id('memory-list').flex_1().min_h(0).px(12).pt(4).pb(16).gap(10).overflow_y_scrollbar()
        .track_scroll(this.memoryScroll)
        .children(listChildren));
  }

  threadSessionView(t, today, cx) {
    const lang = this.lang;
    const held = this.threadSession?.taskId === this.thread ? this.threadSession : null;
    const turns = held ? sessionTurns(held.items, { lang, sent: this.sessionSent }) : [];
    const showEarlier = Boolean(held?.earlier || this.threadSessionEarlierLoading || this.threadSessionEarlierError);
    const worked = held && !held.earlier ? workedDuration(lang, held.started, held.ended) : '';
    const toolsOpen = (this.sessionToolsOpen ||= new Set());
    const briefsOpen = (this.sessionBriefsOpen ||= new Set());
    const workerWorking = Boolean(this.atWork?.has(this.thread));

    const earlierRow = showEarlier ? (() => {
      const busy = this.threadSessionEarlierLoading, err = this.threadSessionEarlierError;
      const tip = busy ? word(lang, 'loadingEarlierSession')
        : err ? word(lang, 'earlierSessionFailed', err) : word(lang, 'earlierSession');
      return h_flex().w_full().pb(4).justify_center().items_center()
        .child(this.withTip('thread-session-earlier', h_flex().id('thread-session-earlier').size(26).rounded(8).items_center().justify_center()
          .text_color(err ? t.blocked : t.dim).accessibility_label(tip)
          .when(!busy, el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(err ? t.blocked : t.foreground))
            .on_click((_e, cx) => this.loadEarlierThreadSession(turns, cx)))
          .child(busy ? svg(SPINNER).size(13).flex_none().text_color(t.muted).spin(900) : this.icon('earlier', 14)), tip, t, { panel: true, placement: 'below-left' }));
    })() : null;

    const renderTurn = (turn, idx) => {
      if (turn.role === 'user') {
        const files = turn.files || [];
        const open = briefsOpen.has(turn.key);
        const shownText = turn.long && !open ? turn.preview : turn.text;
        const metaWords = [turn.from, clock(turn.at, today)].filter(Boolean).join(' · ');
        const bubble = v_flex().id(`session-user-${turn.key}`).max_w('90%').px(12).py(8).gap(6)
          .rounded_tl(14).rounded_tr(14).rounded_bl(14).rounded_br(5)
          .bg(t.raised).text_color(t.foreground)
          .when(!isDarkTheme(t), el => el.border_1().border_color(t.border))
          .when(Boolean(shownText), el => el.child(this.renderMentionText(`session-msg-${turn.key}`, shownText, t, cx).text_size(13)))
          .when(Boolean(turn.long), el => el.child(this.withTip(`session-brief-${turn.key}`, h_flex().id(`session-brief-${turn.key}`).gap(4).items_center().cursor_pointer()
            .text_size(11.5).text_color(t.dim).hover(s => s.text_color(t.foreground))
            .accessibility_label(word(lang, open ? 'fold' : 'unfoldMessage'))
            .on_click((_e, cx) => {
              if (briefsOpen.has(turn.key)) briefsOpen.delete(turn.key);
              else briefsOpen.add(turn.key);
              cx.notify();
            })
            .child(this.icon(open ? 'collapse' : 'expand', 13))
            .child(word(lang, open ? 'fold' : 'unfoldMessage')), word(lang, open ? 'fold' : 'unfoldMessage'), t, { panel: true, placement: 'above-right' })))
          .when(files.length > 0, el => el.child(h_flex().flex_wrap().gap(6)
            .children(files.map((path, fi) => this.fileCard(`session-file-${turn.key}-${fi}`, path, t).bg(t.surface)))));
        return v_flex().id(`session-turn-${turn.key}`).w_full().items_end().gap(3)
          .child(bubble)
          .when(Boolean(metaWords), el => el.child(div().text_size(11).text_color(t.dim).child(metaWords)));
      }

      const isFirstAssistant = turns.findIndex(x => x.role === 'assistant') === idx;
      const isLastTurn = idx === turns.length - 1;
      const partEls = turn.parts.map(part => {
        if (part.kind === 'text') {
          const chunks = markdownChunks(part.text);
          return v_flex().w_full().gap(6).children(chunks.map((chunk, ci) =>
            div().w_full().text_size(13).text_color(t.foreground)
              .child(TextView.markdown(`session-md-${part.key}-${ci}`, chunk).selectable(true)
                .on_link_click((url, cx) => this.followLink(url, cx)))));
        }
        const open = toolsOpen.has(part.key);
        const head = this.withTip(`session-tools-${part.key}`, h_flex().id(`session-tools-${part.key}`).min_h(26).px(8).py(4).gap(6).rounded(7).items_center()
          .cursor_pointer().bg(t.surface).border_1().border_color(t.border).hover(s => s.bg(t.hover))
          .accessibility_label(part.label)
          .on_click((_e, cx) => {
            if (toolsOpen.has(part.key)) toolsOpen.delete(part.key);
            else toolsOpen.add(part.key);
            cx.notify();
          })
          .child(this.icon(open ? 'expand' : 'chevron', 12).text_color(t.dim))
          .child(div().flex_1().min_w(0).truncate().text_size(12).text_color(t.muted).child(part.label))
          .when(part.errors > 0, el => el.child(div().flex_none().text_size(11).font_medium().text_color(t.blocked)
            .child(word(lang, 'toolErrors', part.errors)))), part.label, t, { panel: true, placement: 'above-left' });
        if (!open) return head;
        const body = v_flex().id(`session-tools-body-${part.key}`).ml(6).pl(10).py(2).gap(5).border_l(1).border_color(t.border)
          .children(part.calls.map((call, ci) => v_flex().id(`session-call-${part.key}-${ci}`).gap(1)
            .child(h_flex().gap(6).items_start()
              .child(div().flex_none().font_family('monospace').text_size(11.5).font_medium()
                .text_color(call.error ? t.blocked : t.muted).child(call.name))
              .when(Boolean(call.input), el => el.child(this.selectableText(`session-call-in-${part.key}-${ci}`, call.input, null, true).flex_1().min_w(0)
                .text_size(11.5).text_color(t.foreground))))
            .when(Boolean(call.output), el => el.child(this.selectableText(`session-call-out-${part.key}-${ci}`, call.output, null, true).w_full()
              .text_size(11).text_color(call.error ? t.blocked : t.dim)))));
        return v_flex().w_full().gap(4).child(head).child(body);
      });

      const footTime = clock(turn.at, today);
      return v_flex().id(`session-turn-${turn.key}`).w_full().gap(6)
        .when(Boolean(isFirstAssistant && worked), el => el.child(div().text_size(11).text_color(t.dim).child(worked)))
        .children(partEls)
        .when(Boolean(footTime || (isLastTurn && workerWorking)), el => el.child(h_flex().gap(8).items_center()
          .when(Boolean(footTime), sub => sub.child(div().font_family('monospace').text_size(11).text_color(t.dim).child(footTime)))
          .when(Boolean(isLastTurn && workerWorking), sub => sub.child(this.workingDots(t)))));
    };

    const children = [];
    if (earlierRow) children.push(earlierRow);
    if (this.threadSessionError && held) {
      children.push(div().id('thread-session-stale').whitespace_normal().text_size(11.5).text_color(t.blocked)
        .child(word(lang, 'sessionStale', this.threadSessionError)));
    }
    const turnStartIndex = children.length;
    if (this.threadSessionLoading && !held) {
      children.push(h_flex().pt(6).gap(8).items_center().text_size(12.5).text_color(t.dim)
        .child(svg(SPINNER).size(14).flex_none().spin(900)).child(word(lang, 'sessionLoading')));
    } else if (this.threadSessionError && !held) {
      children.push(div().pt(6).whitespace_normal().text_size(12.5).text_color(t.blocked)
        .child(word(lang, 'sessionStale', this.threadSessionError)));
    } else if (held?.unknown?.length && !turns.length) {
      children.push(div().id('thread-session-unknown').pt(6).whitespace_normal().text_size(12.5).text_color(t.muted)
        .child(word(lang, 'sessionUnknown')));
    } else if (held && !turns.length) {
      children.push(div().id('thread-session-empty').pt(6).text_size(12.5).text_color(t.dim)
        .child(word(lang, 'sessionEmpty')));
    } else {
      turns.forEach((turn, idx) => children.push(renderTurn(turn, idx)));
    }
    // Bottom spacer so scroll_to_item(endIndex) reveals the end of a tall final turn cleanly.
    const endMarkerIndex = children.length;
    children.push(div().flex_none().h(4));

    if (turns.length !== (this.sessionCount || 0)) {
      if (turns.length > (this.sessionCount || 0) && !this.sessionAway) this.sessionSettle = SETTLE;
      this.sessionCount = turns.length;
    }
    if (this.threadSessionAnchor && turns.length) {
      const idx = turns.findIndex(x => x.key === this.threadSessionAnchor.key);
      this.threadSessionAnchor.left--;
      if (idx >= 0) this.sessionScroll?.scroll_to_item(turnStartIndex + idx);
      if (this.threadSessionAnchor.left <= 0 || idx < 0) this.threadSessionAnchor = null;
      else if (cx && !this.sessionTicking) {
        this.sessionTicking = true;
        cx.timer.after(16, cx => { this.sessionTicking = false; cx.notify(); });
      }
    } else if (turns.length && (this.sessionSettle || 0) > 0) {
      this.sessionSettle--;
      this.sessionScroll?.scroll_to_item(endMarkerIndex);
      if (cx && !this.sessionTicking) {
        this.sessionTicking = true;
        cx.timer.after(16, cx => { this.sessionTicking = false; cx.notify(); });
      }
    }

    return v_flex().id('thread-session').flex_1().min_h(0).py(2).gap(12).overflow_y_scrollbar()
      .when(Boolean(this.sessionScroll), el => el.track_scroll(this.sessionScroll))
      .on_scroll_wheel(e => {
        if (e.delta.y) {
          this.threadSessionAnchor = null;
          if (e.delta.y > 0) { this.sessionAway = true; this.sessionSettle = 0; }
          else if (e.delta.y < -12) this.sessionAway = false;
        }
      })
      .children(children);
  }

  panel(t, today, width, cx) {
    this.agentWindows = this.agentWindows || [];
    this.substepsToggle = this.substepsToggle || {};
    const lang = this.lang;
    const allTasks = this.tasks || this.state.tasks;
    const stateTask = allTasks.find(x => x.id === this.thread);
    const task = { ...stateTask, ...this.threadTask };
    if (this.isThreadChangeOpen()) return this.threadChangeView(t, width, cx, task, today);
    const terminal = this.threadTerminal();
    const program = terminal?.program;
    // Offline: what `pm.py state` says of the task now (the ledger file does not carry it).
    const offline = Boolean(stateTask?.offline) && !terminal, quiet = disconnected({ ...task, offline });
    const closedInfo = offline ? (stateTask?.closed || (isClosedTask({ ...task, offline }) ? task.closed : null)) : null;
    // A task with a folded review reads as the list shows it (foldReviews), not as its ledger file says.
    const status = (stateTask?.review ? stateTask.status : task.status) || '', answered = Boolean(stateTask?.answered);
    const tn = tone(status, Boolean(stateTask?.cleanup), offline, answered);
    const engine = engineLabel(task);
    const sessionCtx = this.threadSession?.taskId === this.thread ? contextTokens(this.threadSession.context) : 0;
    const workerCtx = sessionCtx || contextTokens(stateTask?.context_tokens) || contextTokens(task?.context_tokens);
    const workerCtxText = contextLabel(lang, workerCtx);
    const closedDetail = closedInfo ? closedTip(lang, closedInfo) : (offline && !quiet ? word(lang, 'disconnected') : '');
    const log = this.threadLog ? this.threadLog.entries : (Array.isArray(task.log) ? task.log : []).slice(-LOG_LIMIT);
    const earlierLogCount = this.threadLog?.earlier || 0;
    const showEarlierLog = earlierLogCount > 0 || this.threadEarlierLoading || Boolean(this.threadEarlierError);
    // Waiting for the user: its question at the top, answered here as its card would be.
    const asks = stateTask ? detailQuestion(stateTask, this.state.tasks.find(x => x.id === this.thread), this.threadTask,
      this.items || []) : null;
    // Split into sub-threads: they are listed under its status, and it links back from each of them.
    const parts = subThreads(allTasks, this.thread, this.terms(), this.live(), lang, this.state.retired_parts);
    const parent = parentThread(this.state.tasks, { ...task, id: this.thread });
    // Two-layer plan & sub-agents (`worker`, `review`, `helpers`).
    const planTask = stateTask ? { ...task, ...stateTask, id: this.thread } : { ...task, id: this.thread };
    const steps = taskSteps(planTask, { lang });
    const agentsInfo = threadAgents(planTask, {
      terms: this.terms(), live: this.live(), pmPane: this.pm()?.pane || '', lang, container: parts.length > 0,
      pmHelpers: this.pm()?.helpers,
    });
    const reviewAgent = agentsInfo.all.find(a => a.role === 'review') || null;
    const primaryAgent = agentsInfo.all.find(a => a.role === 'worker') || agentsInfo.active[0] || agentsInfo.all[0] || null;
    const reviewOpen = status === 'review' ||
      Boolean(stateTask?.review && !['done', 'merged', 'released', 'abandoned', 'cancelled', 'paused', 'proposed'].includes(stateTask.review.status));
    const reviewActive = reviewWorking(planTask, this.terms(), this.live());
    const detailGroup = offline ? 'offline'
      : ['done', 'released', 'merged', 'abandoned', 'cancelled'].includes(status) ? 'finished'
        : status === 'blocked' && !answered ? 'waiting'
          : status === 'proposed' ? 'parked'
            : status === 'paused' ? 'paused'
              : 'working';
    const markRow = {
      group: detailGroup,
      status,
      tone: tn,
      working: Boolean(terminal) && status === 'in_progress' && !offline,
      reviewing: reviewOpen,
      reviewWorking: reviewActive,
      postGate: steps.postGate,
    };
    const statusText = statusLabel(lang, status, Boolean(stateTask?.cleanup), offline, answered, Boolean(closedInfo));
    const statusTipParts = [
      statusText,
      closedDetail,
      engine ? `${engine}${wasEscalated(task) ? ' ↑' : ''}` : '',
      workerCtxText,
    ].filter(Boolean);
    const statusTip = statusTipParts.join(' · ');

    // Topbar action: toggle primary agent small window in Project (or reattach when disconnected & reattachable).
    const does = terminalAction(terminal, { offline, pane: task.pane }, this.reattaching === this.thread, parts.length);
    const reattachTip = closedInfo ? word(lang, 'reattachClosed', closedDetailText(lang, closedInfo)) : word(lang, 'reattach');
    const primaryOpen = Boolean(primaryAgent && agentWindowOpen(this.agentWindows, primaryAgent.key));
    const windowOrTerminalIcon = does === 'reattaching'
      ? this.withTip('thread-terminal', h_flex().id('thread-terminal').size(28).flex_none().rounded(8).items_center().justify_center().text_color(t.muted)
        .accessibility_label(word(lang, 'reattaching'))
        .child(svg(SPINNER).size(14).flex_none().spin(900)), word(lang, 'reattaching'), t, { panel: true, placement: 'below-right' })
      : does === 'reattach'
        ? this.winIconBtn('thread-terminal', 'reattach', reattachTip, cx => this.reattach(cx), t)
        : primaryAgent
          ? this.winIconBtn('thread-terminal', 'window-pop',
            primaryOpen ? word(lang, 'closeAgentWindow') : word(lang, 'detailOpenWindow'),
            cx => this.toggleAgentSmallWindow(primaryAgent, cx), t, 14, primaryOpen)
          : terminal && !this.terminalPlace(terminal.address).focus
            ? this.winIconBtn('thread-terminal', 'terminal', word(lang, 'terminalNowhere'), null, t)
            : this.winIconBtn('thread-terminal', 'terminal', terminal ? word(lang, 'openTerminal') : word(lang, 'threadOffline'),
              terminal ? () => this.focusTerminal(terminal.address) : null, t);
    const showWindowAction = does !== 'hidden' || Boolean(primaryAgent);
    const diffBtn = this.threadChangeButton(task, t);
    const actions = h_flex().gap(2).items_center().flex_none()
      .when(showWindowAction, el => el.child(windowOrTerminalIcon))
      .when(Boolean(diffBtn), el => el.child(diffBtn))
      .child(this.winIconBtn('thread-close', 'close', word(lang, 'close'), cx => {
        this.detail = false;
        this.resetThreadChange();
        this.syncVisibleSideTab(cx);
        cx.notify();
      }, t));

    const threadNum = formatTaskNumber(taskNumber(task) || taskNumber(stateTask) || this.taskNumberFor(this.thread));
    const headerBar = h_flex().id('thread-topbar').gap(6).items_center()
      .child(this.winIconBtn('thread-back', 'back', word(lang, 'backToThreads'), cx => {
        this.detail = false;
        this.resetThreadChange();
        this.syncVisibleSideTab(cx);
        cx.notify();
      }, t, 14, false, { placement: 'below-left' }))
      .child(this.withTip('thread-status', h_flex().id('thread-status').size(18).flex_none().items_center().justify_center()
        .accessibility_label(statusTip)
        .child(this.threadMark(markRow, t)), statusTip, t, { panel: true, placement: 'below-left' }))
      .when(Boolean(threadNum), el => el.child(div().id('thread-number').flex_none().font_family('monospace').text_size(12.5).text_color(t.dim).child(threadNum)))
      .child(this.withTip('thread-title', div().id('thread-title').w_full().truncate().text_size(14.5).font_semibold()
        .text_color(t.foreground)
        .child(task.title || this.thread), [threadNum ? `${threadNum} ${task.title || this.thread}` : (task.title || this.thread), statusTip].filter(Boolean).join(' · '),
        t, { panel: true, placement: 'below-left', wrap: true, flex1: true }))
      .child(actions);

    const hasSubmeta = Boolean(task.branch || parent || (closedInfo && !quiet));
    const parentNum = formatTaskNumber(parent);
    const submetaBar = hasSubmeta ? h_flex().flex_wrap().gap(8).items_center().pl(4).text_size(11.5).text_color(t.dim)
      .when(Boolean(task.branch), el => el.child(this.withTip('thread-branch', div().id('thread-branch').font_family('monospace')
        .child(task.branch), workerCtxText || task.branch, t, { panel: true, placement: 'below-left', wrap: true, flexNone: true })))
      .when(Boolean(closedInfo && !quiet), el => el.child(this.withTip('thread-closed-pill', div().id('thread-closed-pill')
        .child(word(lang, 'closedReattach')), closedTip(lang, closedInfo), t, { panel: true, placement: 'below-left', wrap: true, flexNone: true })))
      .when(Boolean(parent), el => el.child(this.withTip('thread-parent', h_flex().id('thread-parent').gap(4).items_center().cursor_pointer()
        .text_color(t.dim).hover(s => s.text_color(t.foreground))
        .accessibility_label(word(lang, 'partOf', parent.title))
        .on_click((_e, cx) => this.openThread(parent.task, cx))
        .child(svg(ICON('hook-up')).size(11.5).flex_none())
        .when(Boolean(parentNum), el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(parentNum)))
        .child(div().min_w(0).truncate().child(word(lang, 'partOf', parent.title))), word(lang, 'openThread'), t, { panel: true, placement: 'below-left' }))) : null;
    const hasSessionTab = this.sessionTabAvailable(stateTask, task);
    const activeTab = this.activeThreadTab(stateTask, task);
    const tabItem = (key, glyph, label, dot = false) => h_flex().id(`thread-tab-${key}`).h(25).px(10).gap(6).rounded(7).items_center()
      .text_size(12.5).accessibility_label(label)
      .when(key === activeTab, el => el.bg(t.raised).text_color(t.foreground).font_medium())
      .when(key !== activeTab, el => el.cursor_pointer().text_color(t.muted).hover(s => s.text_color(t.foreground))
        .on_click((_e, cx) => this.selectThreadTab(key, cx)))
      .child(this.icon(glyph, 13.5)).child(label)
      .when(Boolean(dot), el => el.child(div().size(5).rounded_full().bg(t.blocked)));
    const tabBar = hasSessionTab ? h_flex().flex_none().items_center()
      .child(h_flex().id('thread-tabs').h(31).p(2).gap(2).rounded(9).border_1().border_color(t.border)
        .child(tabItem('log', 'list', word(lang, 'threadLogTab'), activeTab === 'session' && Boolean(asks)))
        .child(tabItem('session', 'chat', word(lang, 'threadSessionTab')))) : null;

    // Prerequisite dependencies card ("Waiting" / "等待"), clickable to jump to prerequisite threads.
    const deps = taskDependencies(planTask, allTasks, { terms: this.terms(), live: this.live() });
    const detailUi = {
      div, svg, h_flex, v_flex,
      withTip: (key, el, tipText, opts) => this.withTip(key, el, tipText, t, { panel: true, ...(opts || {}) }),
    };
    const depsCard = deps ? renderDepsCard({
      ui: detailUi,
      deps,
      theme: t,
      lang,
      icons: STEP_ICONS,
      compact: false,
      framed: true,
      cardId: 'thread-deps-card',
      rowIdPrefix: 'dep-item',
      onSelect: (dep, cx) => this.jumpToDependency(dep, cx),
    }) : null;

    // Two-layer Steps card: outer plan + folded/auto-expanded sub-steps with smooth Bezier connectors.
    const planCard = (!deps?.showAsWaiting || steps.hasPlan) ? renderStepsCard({
      ui: detailUi,
      steps,
      theme: t,
      lang,
      icons: STEP_ICONS,
      compact: false,
      framed: true,
      cardId: 'thread-plan-card',
      stepIdPrefix: 'plan-step',
      spinning: !offline && detailGroup === 'working',
      reviewSpinning: reviewActive,
      subSpinning: !offline,
      isSubOpen: s => {
        const tKey = `${this.thread}:${s.index}`;
        return (tKey in this.substepsToggle) ? Boolean(this.substepsToggle[tKey]) : s.state === 'doing';
      },
      onToggleSub: (s, cx) => {
        const tKey = `${this.thread}:${s.index}`;
        const cur = (tKey in this.substepsToggle) ? Boolean(this.substepsToggle[tKey]) : s.state === 'doing';
        this.substepsToggle[tKey] = !cur;
        cx.notify();
      },
      canClickReview: Boolean(reviewAgent),
      reviewOpen: Boolean(reviewAgent && agentWindowOpen(this.agentWindows, reviewAgent.key)),
      onClickReview: cx => this.toggleAgentSmallWindow(reviewAgent, cx),
    }) : null;

    let bodyEl;
    if (activeTab === 'session') {
      bodyEl = this.threadSessionView(t, today, cx);
    } else {
      const visibleLog = this.threadLogExpanded ? log : log.slice(-3);
      const canExpandRecent = log.length > 3;
      const earlierLogRow = showEarlierLog && (this.threadLogExpanded || !canExpandRecent) ? (() => {
        const busy = this.threadEarlierLoading, err = this.threadEarlierError;
        const tip = busy ? word(lang, 'loadingEarlierLog')
          : err ? word(lang, 'earlierLogFailed', err) : word(lang, 'earlierLog', earlierLogCount);
        return h_flex().relative().pb(8).items_center()
          .when(visibleLog.length > 0, el => el.child(div().absolute().left(3).top(12).bottom(0).w(1).bg(t.border)))
          .child(div().absolute().left(1).top(9.5).size(5).rounded_full().border_1().border_color(t.border).bg(t.chrome))
          .child(this.withTip('thread-log-earlier', h_flex().id('thread-log-earlier').ml(13).size(24).rounded(7).items_center().justify_center()
            .text_color(err ? t.blocked : t.dim).accessibility_label(tip)
            .when(!busy, el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(err ? t.blocked : t.foreground))
              .on_click((_e, cx) => this.loadEarlierThreadLog(cx)))
            .child(busy ? svg(SPINNER).size(13).flex_none().text_color(t.muted).spin(900) : this.icon('earlier', 14)), tip, t, { panel: true, placement: 'below-left' }));
      })() : null;
      const entries = visibleLog.length ? visibleLog.map((entry, i) => {
        const first = i === 0, latest = i === visibleLog.length - 1;
        const lineAbove = !first || Boolean(earlierLogRow), lineBelow = !latest;
        const entryText = logText(lang, entry.text, true);
        if (!this.threadLogExpanded) {
          return this.withTip(`thread-entry-${entry.n ?? i}`, h_flex().id(`thread-entry-${entry.n ?? i}`).relative().h(22).pl(16).gap(8).items_center()
            .when(lineAbove && lineBelow, el => el.child(div().absolute().left(3).top(0).bottom(0).w(1).bg(t.border)))
            .when(!lineAbove && lineBelow, el => el.child(div().absolute().left(3).top(11).bottom(0).w(1).bg(t.border)))
            .when(lineAbove && !lineBelow, el => el.child(div().absolute().left(3).top(0).h(11).w(1).bg(t.border)))
            .child(div().absolute().left(.5).top(8).size(6).rounded_full().bg(latest ? t.accent : t.border))
            .child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(clock(entry.at, today)))
            .child(div().flex_1().min_w(0).truncate().text_size(12.2)
              .text_color(latest ? t.foreground : t.muted).child(entryText)), entryText, t, { panel: true, placement: 'above-left' });
        }
        return v_flex().id(`thread-entry-${entry.n ?? i}`).relative().pl(16).pb(latest ? 2 : 12).gap(2)
          .when(lineAbove && lineBelow, el => el.child(div().absolute().left(3).top(0).bottom(0).w(1).bg(t.border)))
          .when(!lineAbove && lineBelow, el => el.child(div().absolute().left(3).top(10).bottom(0).w(1).bg(t.border)))
          .when(lineAbove && !lineBelow, el => el.child(div().absolute().left(3).top(0).h(10).w(1).bg(t.border)))
          .child(div().absolute().left(0).top(7).size(7).rounded_full().bg(latest ? t.accent : t.border))
          .child(div().font_family('monospace').text_size(11.5).text_color(t.dim).child(clock(entry.at, today)))
          .child(this.selectableText(`thread-log-txt-${this.thread}-${entry.n ?? i}`, entryText).w_full()
            .text_size(12.5).text_color(latest ? t.foreground : t.muted));
      }) : [div().pl(16).text_size(12.5).text_color(t.dim).child(word(lang, 'noLog'))];
      if (this.threadAnchor && visibleLog.length) {
        const idx = visibleLog.findIndex(e => e.n === this.threadAnchor.n);
        this.threadAnchor.left--;
        if (idx >= 0) this.threadScroll.scroll_to_item((earlierLogRow ? 1 : 0) + idx);
        if (this.threadAnchor.left <= 0 || idx < 0) this.threadAnchor = null;
        else if (cx && !this.threadTicking) {
          this.threadTicking = true;
          cx.timer.after(16, cx => { this.threadTicking = false; cx.notify(); });
        }
      }
      const logHeader = canExpandRecent ? h_flex().pb(4).items_center().justify_end()
        .child(h_flex().id('thread-log-toggle').h(20).px(6).rounded(5).items_center().cursor_pointer()
          .text_size(11).text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
          .on_click((_e, cx) => { this.threadLogExpanded = !this.threadLogExpanded; cx.notify(); })
          .child(this.threadLogExpanded ? word(lang, 'collapseLog') : word(lang, 'showAllLog', log.length))) : null;
      bodyEl = v_flex().id('thread-log').flex_1().min_h(0).py(2).overflow_y_scrollbar()
        .track_scroll(this.threadScroll)
        .on_scroll_wheel((e, cx) => {
          if (e.delta.y) this.threadAnchor = null;
          if (this.hoverKey) { this.hoverKey = ''; cx.notify(); }
        })
        .when(Boolean(logHeader), el => el.child(logHeader))
        .when(Boolean(earlierLogRow), el => el.child(earlierLogRow))
        .children(entries);
    }

    return v_flex().w(width).h_full().flex_none().px(18).pt(12).pb(16).gap(12)
      .bg(t.chrome).border_l(1).border_color(t.border)
      .child(headerBar)
      .when(Boolean(submetaBar), el => el.child(submetaBar))
      .when(Boolean(tabBar), el => el.child(tabBar))
      .when(activeTab === 'log' && Boolean(asks), el => el.child(v_flex().id('thread-question').flex_none().max_h(320).overflow_y_scrollbar()
        .mx(-10).gap(2)
        .when(Boolean(asks.text), el => el.child(this.selectableText(`thread-ask-${this.thread}`, logText(lang, asks.text, true)).px(10).pb(6).w_full()
          .text_size(13.5).text_color(t.foreground)))
        .children(this.answerRows(asks, t, 'thread-'))))
      .when(activeTab === 'log' && Boolean(depsCard), el => el.child(depsCard))
      .when(activeTab === 'log' && Boolean(planCard), el => el.child(planCard))
      .when(activeTab === 'log' && parts.length > 0, el => el.child(this.partsList(parts, t)))
      .child(bodyEl)
      .when(Boolean(this.threadError), el => el.child(div().text_size(12).text_color(t.blocked).whitespace_normal()
        .child(word(lang, 'failed', this.threadError))))
      .when(this.reattachError?.id === this.thread && !terminal, el => el.child(div().text_size(12).text_color(t.blocked)
        .whitespace_normal().child(word(lang, 'reattachFailed', this.reattachError.text))))
      .child(this.composer('say-thread', this.threadInput, this.threadDraft, Boolean(terminal), word(lang, 'sayThread'),
        word(lang, 'threadOffline'), cx => this.sendThread(cx), t, 14, false, cx));
  }

  render(cx) {
    if (this.agentWindow === 'titlebar' || this.agentWindow === 'chat') return this.renderAgentWindow(cx);
    if (this.headerOnly) return this.renderHeaderOnly(cx);
    const t = theme();
    this.lang = this.state.lang;
    const lang = this.lang;
    const rawRef = shared(SHARED);
    const ref = projectRef(rawRef), wanted = ref.key;
    if (ref.machine !== this.machine) {
      // A project on another machine (or back here): that machine's ledger, read now.
      // The language stays until that ledger gives its own.
      this.closeAllAgentWindows(cx, { defer: true });
      this.machine = ref.machine; this.state = { pms: [], tasks: [], lang: this.state.lang }; this.stateFor = null;
      this.error = ''; this.logError = ''; this.remoteHome = ''; this.remoteNoProject = '';
      this.remoteNoLibrary = ''; this.remoteNoMemory = ''; this.remoteNoSession = ''; this.remoteNoChange = '';
      this.logSlug = ''; this.logState = null; this.logReceipts = []; this.logTurn = null; this.clockOffsetMs = 0; this.serverNowMs = 0; this.serverNowAt = 0; this.noProjectSendFor = '';
      this.earlierLoading = false; this.earlierError = ''; this.earlierAnchor = null;
      this.threadLog = null; this.threadLogKept = []; this.threadEarlierLoading = false; this.threadEarlierError = ''; this.threadAnchor = null;
      this.threadLogExpanded = false;
      this.epicOverrides = new Map(); this.expandedDone = new Set(); this.substepsToggle = {}; this.clearHoverNow(null); this.highlightThread = ''; this.pendingScrollThread = '';
      this.resetThreadSession();
      this.resetThreadChange();
      this.librarySlug = ''; this.libraryRoots = []; this.libraryFiles = []; this.libraryRead = false; this.libraryProbed = false; this.libraryStale = false; this.libraryError = '';
      this.libraryDropBusy = ''; this.libraryDropError = '';
      this.memorySlug = ''; this.memoryData = null; this.memoryRead = false; this.memoryStale = false; this.memoryError = '';
      this.memoryBusy = ''; this.memoryNoticeError = ''; this.deletedBanner = null;
      this.mention = null; this.mentionDismissed = null;
      this.searchOpen = false; this.searchQuery = ''; this.searchScope = 'all'; this.searchIndex = 0; this.searchKey = '';
      this.jumpTarget = null; this.flash = ''; this.flashPara = ''; this.flashTone = 'blocked';
      this.quotes = []; this.hoveredMsg = ''; this.hoverClipboard = null; this.selectionBar = null; this.lastBlocks = [];
      this.clearParaHoverNow(null);
      this.repoFilesSlug = ''; this.repoFilesRepo = ''; this.repoFiles = []; this.repoFilesRead = false; this.repoFilesLoading = false; this.repoFilesAgain = false; this.repoFilesError = ''; this.repoFilesTruncated = false; this.repoFilesAt = 0;
      this.resetLibraryDocState();
      this.resetRenderCaches();
      if (!this.bringingBack) { this.bringBackOpen = false; this.bringBackProgress = null; }
      cx.timer.after(0, cx => { this.searchInput?.set_value(''); this.refresh(cx); });
    }
    if (wanted !== this.pmName) {
      // Another project: its own log, no bubbles or panel from the last one.
      this.closeAllAgentWindows(cx, { defer: true });
      const byPm = this.pendingByPm ||= new Map();
      if (this.pmName) byPm.set(this.pmName, this.pending);
      this.pmName = wanted; this.events = []; this.logReceipts = []; this.logTurn = null; this.pending = this.hydrateQueue(wanted); this.detail = false; this.thread = ''; this.threadTask = null;
      this.pmDialog = null; this.pmSendBlockError = ''; this.pmDialogAt = 0; this.lastLogReadAt = 0; this.confirmLogProbes = new Set();
      this.logSlug = ''; this.logState = null; this.earlierLoading = false; this.earlierError = ''; this.earlierAnchor = null;
      this.threadLog = null; this.threadLogKept = []; this.threadEarlierLoading = false; this.threadEarlierError = ''; this.threadAnchor = null;
      this.threadLogExpanded = false;
      this.epicOverrides = new Map(); this.expandedDone = new Set(); this.substepsToggle = {}; this.clearHoverNow(null); this.highlightThread = ''; this.pendingScrollThread = '';
      this.resetThreadSession();
      this.resetThreadChange();
      this.librarySlug = ''; this.libraryRoots = []; this.libraryFiles = []; this.libraryRead = false; this.libraryProbed = false; this.libraryStale = false; this.libraryError = '';
      this.libraryQuery = ''; this.libraryDropBusy = ''; this.libraryDropError = '';
      this.memorySlug = ''; this.memoryData = null; this.memoryRead = false; this.memoryStale = false; this.memoryError = '';
      this.memoryQuery = ''; this.memoryBusy = ''; this.memoryNoticeError = ''; this.deletedBanner = null;
      this.docFindOpen = false; this.docFindQuery = ''; this.docJumpQuery = ''; this.docMatchPos = 0;
      this.mention = null; this.mentionDismissed = null;
      this.searchOpen = false; this.searchQuery = ''; this.searchScope = 'all'; this.searchIndex = 0; this.searchKey = '';
      this.jumpTarget = null;
      this.quotes = []; this.hoveredMsg = ''; this.hoverClipboard = null; this.selectionBar = null; this.lastBlocks = [];
      this.clearParaHoverNow(null);
      this.repoFilesSlug = ''; this.repoFilesRepo = ''; this.repoFiles = []; this.repoFilesRead = false; this.repoFilesLoading = false; this.repoFilesAgain = false; this.repoFilesError = ''; this.repoFilesTruncated = false; this.repoFilesAt = 0;
      this.resetLibraryDocState();
      this.resetRenderCaches();
      this.seen = null; this.count = 0; this.settle = 0; this.away = false; this.rise = 0; this.heights = new Map();
      this.unfolded = new Map(); this.newest = '';
      this.bell = null; this.flash = ''; this.flashPara = ''; this.flashTone = 'blocked'; this.answering = null;
      if (!this.bringingBack) { this.bringBackOpen = false; this.bringBackProgress = null; }
      cx.timer.after(0, cx => {
        this.searchInput?.set_value('');
        this.libraryInput?.set_value('');
        this.memoryInput?.set_value('');
        this.docFindInput?.set_value('');
        this.docNameInput?.set_value('');
        this.memDescInput?.set_value('');
        this.docEditorInput?.set_value('');
        this.showMainDraft();
        this.readLog(cx);
        if (this.machine || this.sideTab === 'library') this.readLibrary(cx);
        if (this.sideTab === 'memory') this.readMemory(cx);
      });
    }
    const onStage = findStage(layout())?.active === 'pm-project';
    if (onStage && !this.onStage) cx.timer.after(0, () => this.keyFocus.focus());
    if (!onStage && this.onStage) { this.clearHoverNow(null); this.clearParaHoverNow(null); this.searchOpen = false; this.closeAllAgentWindows(cx, { defer: true }); }
    this.onStage = onStage;
    if (rawRef?.thread && rawRef?.jumpSeq && rawRef.jumpSeq !== this.lastJumpSeq) {
      this.lastJumpSeq = rawRef.jumpSeq;
      const jumpId = String(rawRef.thread);
      cx.timer?.after?.(0, cx => this.jumpToThread(jumpId, cx));
    }
    this.syncWinEvents(cx);
    this.syncHeaderAction(cx);
    const root = h_flex().id('pm-project-root').relative().size_full().min_w(0).min_h(0).overflow_hidden()
      .bg(t.canvas).text_size(14).text_color(t.foreground)
      .track_focus(this.keyFocus).on_key_down((e, cx) => this.handleKeyDown(e, cx))
      .on_mouse_move((e, cx) => this.gripMove(e, cx))
      .on_mouse_up('left', (_e, cx) => this.gripUp(cx))
      .on_hover((hovered, cx) => {
        if (!hovered) {
          this.gripUp(cx);
          this.clearParaHoverNow(cx);
          if (this.hoverKey) { this.hoverKey = ''; cx.notify(); }
        }
      })
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
      this.ringAction = null;
      if (this.bodyOnly) this.publishHeaderState({ session: this.winSession, pmName: this.pmName, hasPm: false, lang });
      // A project on another machine says what it waits for, or why it cannot be read: never a blank page.
      const remote = this.machine && this.stateFor !== this.machine;
      const note = remote ? (this.error ? word(lang, 'remoteError', this.machine, this.error) : word(lang, 'remoteLoading', this.machine))
        : this.pmName && this.state.pms.length ? word(lang, 'noProject') : word(lang, 'pick');
      // No header here: nothing on the page moves the window.
      return keepPress(root, this.keyFocus).items_center().justify_center().child(div().max_w(360).text_color(t.dim).whitespace_normal().child(note));
    }
    const now = new Date(), today = iso(now), yesterday = iso(new Date(now.getTime() - 86400000));
    if (this.pmName && !(this.hydratedQueues ||= new Set()).has(this.pmName)) {
      this.hydratedQueues.add(this.pmName);
      this.pending = this.hydrateQueue(this.pmName);
    }
    this._inRender = true;
    this._renderTerms = machineView(terminals(), this.machine);
    this._renderTermsMachine = this.machine;
    this._renderLive = machineView(agents(), this.machine);
    this._renderLiveMachine = this.machine;
    this._renderProjTasks = null;
    this._renderSpacesTabs = null;
    this._renderTaskNumIdx = null;
    this._renderMdLinkMap = null;
    try {
    const pmTerm = this.pmTerminal();
    const pmStatus = pmLiveStatus(pmTerm, this.live());
    const activeTurn = this.activePmTurn();
    const working = this.isPmWorking(pmTerm, this.live(), activeTurn);
    // Live terminal edge trigger: when a remote or local PM transitions out of `working` or advances `turn`,
    // immediately debounce an incremental `readLog` so the reply appears in ~150ms instead of waiting 10s.
    const edgePrefix = `${this.machine}\0${this.pmName}\0${pmTerm?.address || ''}`;
    const prevEdge = this._lastPmLiveEdge || '';
    const nextEdge = `${edgePrefix}\0${pmStatus}\0${pmTerm?.turn || 0}`;
    if (prevEdge && prevEdge !== nextEdge && prevEdge.startsWith(`${edgePrefix}\0`)) {
      const [, , , prevStatus, prevTurnStr] = prevEdge.split('\0');
      const turnAdvanced = (Number(pmTerm?.turn) || 0) > (Number(prevTurnStr) || 0);
      const finishedWorking = prevStatus === 'working' && pmStatus !== 'working';
      if ((turnAdvanced || finishedWorking) && !this.edgeReadTimer && cx?.timer?.after) {
        this.edgeReadTimer = true;
        const targetPm = this.pmName;
        cx.timer.after(150, liveCx => {
          this.edgeReadTimer = false;
          if (this.pmName === targetPm) this.readLog(liveCx);
        });
      }
    }
    this._lastPmLiveEdge = nextEdge;
    const needsTurnTick = working && onStage && Boolean(activeTurn && (Number(activeTurn.started_ms) > 0 || activeTurn.activity));
    if (needsTurnTick && !this.turnTickTimer && cx?.timer?.after) {
      this.turnTickTimer = true;
      const scheduledAt = this.nowMs();
      cx.timer.after(1000, liveCx => {
        this.turnTickTimer = false;
        if (this.nowMs() >= scheduledAt + 500 && this.onStage && this.isPmWorking(this.pmTerminal(), this.live(), this.activePmTurn())) {
          liveCx.notify();
        }
      });
    }
    const queuedCount = this.pending.filter(p => p.queued && !p.failed && !p.received).length;
    const hasUnconfirmed = this.pending.some(p => !p.failed && !p.received && (p.verifying || (!p.queued && (p.deliveredAt > 0 || p.inFlight)) || (p.queued && p.swapWaitSince > 0)));
    if (hasUnconfirmed) this.scheduleConfirmCheck(cx);
    const inRenderPhase = cx?.phase?.() === 'render' && Boolean(cx?.spawn);
    if (pmTerm && !pmCanReceive(pmStatus)) {
      if (inRenderPhase) cx.spawn(async taskCx => this.probePmDialog(taskCx));
      else this.probePmDialog(cx);
    } else if (pmTerm && pmCanReceive(pmStatus)) {
      if (this.pmDialog?.pm === this.pmName && !queuedCount && !this.pmSendBlockError) this.pmDialog = null;
      if (queuedCount > 0 && !this.flushingQueue && !this.flushDeferred) {
        if (inRenderPhase) {
          this.flushDeferred = true;
          cx.spawn(async taskCx => {
            this.flushDeferred = false;
            this.flushQueue(taskCx);
          });
        } else {
          this.flushQueue(cx);
        }
      }
    } else if (!pmTerm && queuedCount > 0) {
      this.scheduleQueueFlush(cx);
    }
    const typingNow = Boolean(working) || this.pending.some(p => !p.failed && !p.queued && !p.received);
    const tl = this.resolveTimelineData(pm, today, typingNow);
    const { items, stops, blocks, newest, keys, foldedTasks, waiting } = tl;
    this.items = items;
    this._blockKeySet = tl.blockKeySet;
    // The box answers a question only while it still waits (a card, or a thread's without one, under
    // askKey): answered meanwhile, or asked anew, it lets go.
    if (this.answering && !stops.some(s => (s.thread ? askKey(s.thread) : s.key) === this.answering.key)) this.answering = null;
    this.atWork = workingTasks(this.terms(), this.live());
    if (this.newest && newest !== this.newest && !this.unfolded.has(this.newest)) this.unfolded.set(this.newest, true);
    this.newest = newest;
    // Fade only what arrives after the first read of this project.
    this.keys = keys;
    if (!this.seen && this.events.length) this.seen = new Set(this.keys);
    const showEarlier = Boolean(this.logState?.earlier || this.earlierLoading || this.earlierError);
    const topOffset = showEarlier ? 1 : 0;
    this.lastBlocks = blocks;
    this.lastTopOffset = topOffset;
    // Follow the end of the conversation as it grows, including the first read after opening a
    // project, but only for a reader who is at the end: one who scrolled up, or went to a question
    // with the bell, stays there (`away`, see leave) until they say something or scroll back down.
    if (blocks.length !== this.count) {
      if (blocks.length > this.count && blocks.length && !this.away) this.follow();
      this.count = blocks.length;
    }
    if (this.jumpTarget && blocks.length) {
      const jumpRow = rowOfKey(blocks, this.jumpTarget.key);
      this.jumpTarget.left--;
      if (jumpRow >= 0) this.scroll.scroll_to_item(topOffset + jumpRow);
      if (this.jumpTarget.left <= 0 || jumpRow < 0) this.jumpTarget = null;
      else if (!this.ticking) { this.ticking = true; cx.timer.after(16, cx => { this.ticking = false; cx.notify(); }); }
    } else if (this.earlierAnchor && blocks.length) {
      const anchorRow = findAnchorBlock(blocks, this.earlierAnchor.anchor);
      this.earlierAnchor.left--;
      if (anchorRow >= 0) this.scroll.scroll_to_item(topOffset + anchorRow);
      if (this.earlierAnchor.left <= 0 || anchorRow < 0) this.earlierAnchor = null;
      else if (!this.ticking) { this.ticking = true; cx.timer.after(16, cx => { this.ticking = false; cx.notify(); }); }
    } else if (blocks.length && this.settle > 0) {
      // The end marker after the last block: revealing it bottom-aligns the end of a long
      // reply, where revealing the reply itself would rest at its top.
      this.settle--;
      this.scroll.scroll_to_item(topOffset + blocks.length);
      if (!this.ticking) { this.ticking = true; cx.timer.after(16, cx => { this.ticking = false; cx.notify(); }); }
    }
    const heights = blocks.map(b => this.heights.get(b.key) || 0), tall = this.tall || this.high;
    this.lastBlocks = blocks;
    this.lastTopOffset = topOffset;
    this.lastHeights = heights;
    this.lastTall = tall;
    // The bell's number is the tasks that wait (see bellCount); a click steps through the places they show.
    // What the user answered no longer waits (see answeredTasks): not on the bell, nor in the side panel.
    // A review thread is no row of its own: it rides on the task it reviews (foldReviews).
    this.tasks = foldedTasks;
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
      const seq = (this.flashSeq || 0) + 1;
      this.flashSeq = seq;
      this.flash = key;
      this.flashTone = 'blocked';
      cx.timer.after(1500, cx => { if (this.flashSeq === seq && this.flash === key) { this.flash = ''; cx.notify(); } });
      cx.notify();
      // Where the jump leaves the reader, by the rows' heights: none of it when the row is in view.
      const row = rowOf(blocks, items[next.at]);
      if (row >= 0) this.rest(riseAfterJump(this.rise, heights, row, tall, TAIL));
      return row >= 0 ? topOffset + row : -1;
    } : null;
    const center = el => h_flex().w_full().justify_center().px(28).child(div().w_full().min_w(0).max_w(COLUMN).child(el));
    // Rows carry their own space above (22 px between blocks, 12 px between the rows of one turn).
    const above = (b, n) => (n === 0 ? 0 : b.kind === 'turn' && !b.first ? 12 : 22);
    // Scrolling up lets go of the end, scrolling down comes back to it (wheel y > 0 moves toward the
    // top): see riseAfterWheel. The area's content is its top padding, the rows and the end marker.
    const room = TAIL + (showEarlier ? 34 : 0) + heights.reduce((sum, h) => sum + h, 0) + TAIL - tall;
    const body = v_flex().id('pm-project-timeline').flex_1().min_h(0).pt(TAIL).overflow_y_scrollbar()
      .track_scroll(this.scroll)
      .on_size_change(size => { this.tall = size.height; })
      .on_scroll_wheel(e => {
        if (e.delta.y) {
          this.jumpTarget = null;
          this.earlierAnchor = null;
          this.selectionBar = null;
          this.rest(riseAfterWheel(this.rise, e.delta.y, room, tall));
        }
      })
      .when(showEarlier, el => el.child(center(this.earlierControl(blocks, t))))
      .children(blocks.length ? blocks.map((b, n) => center(this.block(b, t, today, yesterday, cx)).pt(above(b, n))
        .id(`block-${b.key}`).on_size_change((size, cx) => {
          if (this.heights.get(b.key) === size.height) return;
          this.heights.set(b.key, size.height);
          this.resized(cx);
        }))
        : [center(div().text_color(t.dim).child(word(lang, 'empty')))])
      // The end marker is the column's bottom padding.
      .child(div().flex_none().h(TAIL));
    const pmStart = pmStartState(pm, pmTerm, this.startingPm === this.pmName
      || Boolean(this.bringingBack && this.bringBackProgress?.pmKey === this.pmName
        && this.bringBackProgress.steps?.some(s => s.kind === 'pm' && s.state === 'running')));
    const offlineTip = pmStart === 'archived' ? word(lang, 'pmOfflineArchived')
      : (pmStart === 'tui' || pmStart === 'tui_live') ? word(lang, 'pmOfflineTui')
      : pmStart === 'missing_repo' ? word(lang, 'pmOfflineMissingRepo')
      : word(lang, 'offline');
    if (!pm.lost && !this.bringingBack && this.bringBackOpen
        && (!this.bringBackProgress || !this.bringBackProgress.steps?.some(s => s.state === 'failed'))) {
      this.bringBackOpen = false;
      this.bringBackProgress = null;
    }
    const showLost = Boolean(this.bringingBack || this.bringBackOpen || lostShown(pm.lost, this.keptDismissedLost()));
    const lostEl = showLost ? this.lostNotice(pm, t) : null;
    const showOfflinePmBar = !pmTerm && (pmStart === 'startable' || pmStart === 'starting' || this.startPmError?.pm === this.pmName);
    const activeDialog = pmTerm
      ? (this.pmDialog?.pm === this.pmName && this.pmDialog?.dialog
        ? this.pmDialog.dialog
        : classifyPmDialog('', this.pmSendBlockError, pmStatus))
      : null;
    const pmBlockedText = pmTerm ? pmBlockedBannerText(lang, activeDialog, queuedCount) : '';
    const selectionBar = this.selectionPopover(t);
    const footer = v_flex().w_full().gap(8)
      .when(Boolean(selectionBar), el => el.child(h_flex().w_full().justify_end().child(selectionBar)))
      .when(showOfflinePmBar, el => el.child(this.offlinePmBar(pmStart, t)))
      .when(Boolean(pmBlockedText), el => el.child(this.pmBlockedBar(pmBlockedText, t)))
      .child(this.composer('say', this.input, this.draft, Boolean(pmTerm || this.isPmStarting()), word(lang, 'say', pm.project || pm.name),
        offlineTip, cx => this.sendMain(cx), t, 16, true, cx));
    this.ringAction = ring;
    if (this.bodyOnly) this.publishHeaderState(this.buildHeaderData(pm, waiting, Boolean(ring)));
    const main = v_flex().flex_1().min_w(0).h_full()
      .when(!this.bodyOnly, el => el.child(this.header(pm, waiting, ring, t)))
      .when(Boolean(lostEl), el => el.child(center(lostEl).pt(12)))
      .child(body)
      .child(keepPress(center(footer).pb(20).pt(4), this.keyFocus));
    // The side panel slides from the right edge. At rest it is the thread list (when the window is
    // wide, or the header's icon asked for it); a thread's detail takes its place while one is open,
    // and stays drawn while a panel that rests closed slides shut, then unmounts once closed so
    // hidden panels don't rebuild task trees or thread rows on every render.
    // Its left edge drags to set its width (kept for later, see panelWidth); the edge shows as a thin
    // line under the pointer, and a drag follows the pointer without the slide.
    const resting = this.listResting(), open = resting || this.detail;
    const width = panelWidth(this.panelWant, this.viewWidth), dragging = Boolean(this.panelDrag);
    if (open) {
      this.panelMounted = true;
      if (this.panelHideTimer) { this.panelHideTimer.cancel?.(); this.panelHideTimer = null; }
    } else if (this.panelMounted) {
      if (!this.measured || dragging || !cx?.timer?.after) {
        this.panelMounted = false;
      } else if (!this.panelHideTimer) {
        this.panelHideTimer = cx.timer.after(220, cx => {
          this.panelHideTimer = null;
          if (!(this.listResting() || this.detail)) {
            this.panelMounted = false;
            cx.notify();
          }
        }) || null;
      }
    }
    const showLibrary = this.sideTab === 'library' && (this.librarySupported() || this.activeDoc?.root === 'repo');
    const showMemory = this.sideTab === 'memory' && this.memorySupported();
    const content = (open || this.panelMounted)
      ? (this.detail || (!resting && this.thread && !showLibrary && !showMemory)
        ? this.panel(t, today, width, cx)
        : showLibrary ? this.libraryPanel(pm, t, width, today, cx)
        : showMemory ? this.memoryPanel(pm, t, width, today, cx)
        : this.threadsPanel(pm, t, width))
      : null;
    const lit = dragging || this.gripLit;
    const grip = h_flex().id('panel-grip').absolute().left(0).top(0).h_full().w(6).cursor_col_resize()
      .accessibility_label(word(lang, 'resizePanel'))
      .on_hover((hovered, cx) => { if (hovered !== this.gripLit) { this.gripLit = hovered; cx.notify(); } })
      .on_mouse_down('left', (e, cx) => this.gripDown(e, cx))
      .child(div().w(2).h_full().bg(lit ? withAlpha(t.accent, dragging ? .9 : .6) : withAlpha(t.accent, 0)));
    const panel = h_flex().id('pm-project-panel').relative().h_full().flex_none().overflow_hidden().justify_end()
      .w(open ? width : 0)
      .when(this.measured && !dragging, el => el.transition('width', { duration: 200, easing: 'ease-out' }))
      .when(Boolean(content), el => el.child(content))
      .when(open, el => el.child(grip));
    return root.child(main).child(panel)
      .when(Boolean(this.searchOpen), el => el.child(this.projectSearchOverlay(pm, items, t, today, cx)));
    } finally {
      this._inRender = false;
      this._renderTerms = null;
      this._renderTermsMachine = null;
      this._renderLive = null;
      this._renderLiveMachine = null;
      this._renderProjTasks = null;
      this._renderSpacesTabs = null;
      this._renderTaskNumIdx = null;
      this._renderMdLinkMap = null;
    }
  }
}
