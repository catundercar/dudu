import { View, div, svg, image } from 'gpui-kit';
import { v_flex, h_flex, TextView, TextareaState, Textarea, InputState, Input, ScrollHandle, Scrollbar, Popup } from 'gpui-base';
import { theme, home, appHome, exec, readTextFile, writeTextFile, watchFolder, nextCommand, layout, run, terminals, agents, panes, spaces, shared, setShared, props, openOverlay, closeOverlay, pickFolder, window as appWindow } from 'herdr';
import {
  word, timeline, parseConversation, settlePending, answeredTasks, markAnswered, bellStops, bellNext, bellCount, bellThread, detailQuestion, askKey, timelineRows, rowOf, rowOfKey, blockIndexForKey, riseAfterWheel, riseAfterJump, answerText, clock, dayLabel, shortPath,
  terminalSendArgv, rejectsOption, SEND_WAIT_SECONDS, makeClientMsgId, projectSendArgv, projectInterruptArgv, rotatePmArgs,
  readScreenArgv, pmLiveStatus, pmTurnWorking, pmActivityView, recoveryStepLabel, incidentRowView, pmBusyComposerView, queuedReasonText, formatPmActionFeedback, pmSessionKey, pmCanReceive, deliveryLineView, inboxSignature,
  createAsyncGate, tryEnterAsyncGate, finishAsyncGate, computeClockOffsetMs, eventTimeUtcMs,
  isDialogOrDraftSendError, isTargetGoneSendError, isQueueableSendError, reconcilePendingSends, classifyPmDialog, pmBlockedBannerText, undeliveredBannerText,
  QUEUE_KEY, readQueuedSends, keepQueuedSends, restoreQueuedPending, RESEND_VERIFY_WAIT_MS, logKey,
  mergeReceipts, receiptsFromTurn2Inbox, settledReceiptIndices, findReceiptMatch, findCoalescedReceiptMatches, confirmReceiptBubble,
  withoutTerminalEnv, SEND_ENV, REATTACH_ENV, pmRow, taskRow, terminalFor, terminalTargetFor, focusPlan, pmKeepPlan, pmKeepFollowUp, projectName, pmTabNameFor, cleanTaskLog, statusLabel, tone, turns, newestReply, threadList,
  disconnected, isClosedTask, closedDetailText, closedTip, terminalAction, reattachArgv,
  pmStartState, startPmArgs, startPmArgv, lostShown, mergeDismissedLost, lostSummary, bringBackSteps,
  engineLabel, engineTip, engineChip, wasEscalated, endedEngine, escapeStep, searchShortcutLabel,
  subThreads, parentThread, foldParts, PARTS_LIMIT, foldReviews, threadFor,
  taskTree, taskSteps, taskDependencies, formatDepRef, threadAgents, threadAgentLayout, inlineAgentBadgeParts, inlineAgentBadgeText, agentActionLabel, resolveAgentProgram, AGENT_WINDOW_MAX, normalizeAgentWindowSize, nextAgentWindowSize, agentWindowDimensions, agentWindowTerminalAddresses, agentWindowOpen, toggleAgentWindow, focusAgentWindow, closeAgentWindow, setAgentWindowOverlay, toggleAgentWindowMode, setAgentWindowSize, reconcileAgentWindows, resolveHelperResultPath,
  age, eventTime, workingTasks, reviewWorking, taskNumber, formatTaskNumber, threadLink, resolveThreadRef, decorateThreadLinks, logText, compactLogLine, draftKey, draftText, readDrafts, keepDraft,
  validInputTokens, draftTokens, projectFilesArgv, parseRefLink, parseMentionSpans, splitMentionSegments,
  projectFoldersLsArgv, projectFoldersAddArgv, projectFoldersRemoveArgv, projectFoldersRenameAliasArgv, projectSetSpaceArgv,
  REMOTE_PROBE_SH, REMOTE_LIST_DIRS_SH, REMOTE_MKDIR_SH, parseRemoteProbe, parseRemoteDirs,
  folderName, projectFolders, foldersSignature, headerFoldersView, activeThreadsInFolder, threadFolderBadge,
  detectMentionQuery, parseGitLsFiles, indexRepoFiles, buildMentionMenu, REPO_FILES_LIMIT, MENTION_KEY_BINDINGS, SEARCH_KEY_BINDINGS,
  plainTextToHtml, markdownToPlain, extractClipboardQuote, withQuote, withoutQuote, quotePreviewLine, quoteCardPreview,
  splitMarkdownParagraphs, locateQuoteRange, quoteScope, quoteScopeLabel, quoteScopeTip,
  formatQuotedMessage, splitQuotedMessage, draftQuotes, selectionToolbarState,
  draftFiles, withFiles, withoutFile, notFiles, pickedPaths, addFiles, messageText, afterSend, fileName, isImage, pasteName, pasteDir, pastesIn, uploadSteps, landedPath, sentFiles,
  heldFiles, sentLeftovers, staleArgv, staleFiles,
  CHOOSE_FILES, SAVE_CLIPBOARD_IMAGE, PANEL_WIDTH, PANEL_MIN, panelWidth, draggedWidth, readPanelWidth, keepPressHandler,
  SPLIT_WIDE_MIN, SPLIT_MEDIUM_MIN, SPLIT_CARD_MARGIN_R, SPLIT_GRIP_OVERHANG,
  resolvePanelMode, resolveSplitLayout, readPanelSizes, updatePanelSizes, resetPanelModeSize,
  withAlpha, solidText, isDarkTheme, tonalSurfaces, viewMarkdown, LEDGER_HOME_SH, EVENT_LIMIT, LOG_LIMIT,
  projectRef, machineView, onMachine, remotePmArgv,
  projectSlug, isOldPmCommand, isReplacedLogError, projectEventsArgv, projectLogArgv,
  FINISHED_LIMIT, TASKS_PAGE_LIMIT, projectTasksArgv, parseProjectTasksPage, normalizeProjectTaskRow, mergeFinishedRows, filterLocalThreads,
  freshEventWindow, appendEventWindow, prependEventWindow, keepThreadLog, heldThreadLog, timelineAnchor, findAnchorBlock,
  DOC_INITIAL_BYTES, DOC_MAX_BYTES, SAVE_INLINE_BYTES, REMOTE_CHUNK_BYTES, REMOTE_MKTEMP_ARGV, remoteAppendChunkArgv, chunkUtf8Text, utf8ByteLength,
  MEMORY_TOPICS, PROJECT_MEMORY_TYPES, PERSONAL_MEMORY_TYPES, LIBRARY_DROP_TEXT_EXT,
  projectLibraryArgv, projectMemoryArgv, projectFileArgv, projectSaveArgv, projectDeleteArgv,
  projectRestoreArgv, projectHistoryArgv, projectAddArgv, projectRetopicArgv, adoptCandidateArgv,
  parseVersionConflict, isLibraryRelevantChange, isMemoryRelevantChange, contextKey,
  validLibraryPayload, validMemoryPayload, formatDreamStatus, formatBytes, formatHistoryStamp, contextDay,
  contextShowMode, contextFileError, isWritableDoc, libraryDocTitle, topicLabel, memoryTypeLabel,
  libraryGroups, memoryGroups, searchLibrary, searchMemory, makeDocCacheEntry, isFreshDocEntry,
  makeDocFailEntry, isFreshDocFailure, reconcileDocCache, reconcileDocFailures, keepDocCache,
  documentView, resolveContextLink, markdownChunks, parseFrontmatter, buildMemoryMarkdown,
  INLINE_IMAGE_CACHE_DIR, INLINE_IMAGE_MAX_BYTES, INLINE_IMAGE_REMOTE_MAX_BYTES,
  IMAGE_REVALIDATE_LOCAL_MS, IMAGE_REVALIDATE_REMOTE_MS, IMAGE_LIGHTBOX_REVALIDATE_MS, IMAGE_FAIL_BACKOFF_MS,
  isPreviewableImage, resolveImageTarget, extractInlineImageRefs, rewriteMarkdownImagesForDisplay,
  fitImageBox, stageLocalImageArgv, readRemoteImageArgv, writeStagedImageArgv,
  statLocalImagesArgv, statRemoteImagesArgv, isImageEntryFresh, needsImageRevalidate, isImageFailActive, reconcileImageCache,
  LIGHTBOX_TOOLBAR_HEIGHT, LIGHTBOX_CANVAS_PADDING, createImageLightboxState,
  computeLightboxLayout, stepLightboxZoom, toggleLightboxFitActual, cycleLightboxZoomPreset,
  applyLightboxPinch, resolveSystemPreviewPath, systemOpenFileArgv, imageLightboxOverlaySpec,
  autoOpenEventKey, extractAutoOpenDocRefs, seedAutoOpenState, markAutoOpenHistory, pickAutoOpenTarget,
  memoryFromDroppedFile, slugifyMemoryName, uniqueMemorySlug, retopicPlan,
  SESSION_LIMIT, SESSION_POLL_LOCAL_MS, SESSION_POLL_REMOTE_MS,
  contextTokens, contextShort, contextLabel, pmContextLevel, pmContextTip, workerContextTip,
  isMissingSessionModule, isUnsupportedSessionError, isQuietNoSession, isReplacedSessionError,
  supportedSessionKind, taskSessionKind, knownUnsupportedSession,
  sessionTabAvailable, wantThreadSession, projectSessionArgv,
  takeSessionWindow, trimSessionWindow, workedDuration, sessionTurns,
  CHANGE_DIFF_LIMIT, CHANGE_TIMEOUT_LOCAL_MS, CHANGE_TIMEOUT_REMOTE_MS,
  projectChangeArgv, changeDiffKey, createChangeState, openChangeView, closeChangeView,
  enterChangeFiles, enterChangeFileDiff, stepBackChangeView, appendDiffPage, toggleDiffHunk, toggleAllDiffHunks,
  tooltipLayout, pendingSignature, hostLiveSignature, windowControlButtons,
  SIDE_TABS_KEY, SIDE_TABS_MAX, sideTabKey, threadTabStripLabel, createSideTabsState,
  openSideTab, activateSideTab, showSideIndex, toggleSideIndex,
  closeSideTab, closeOtherSideTabs, closeRightSideTabs, closeAllSideTabs,
  updateSideTab, upgradeDraftTab, cycleSideTab,
  readSideTabsStore, hydrateProjectTabs, serializeProjectTabs,
  estimateSideTabWidth, computeSideTabOverflow,
} from './model.js';
import { execPython } from './python.js';
import { createErrorLogger } from './error_log.js';
import { renderThreadChangeView } from './change_view.js';
import {
  buildProjectSearch, stepSearchSelection, stepSearchScope, stepSearchEscape, renderProjectSearchOverlay,
} from './search.js';
import { renderStepsCard, renderDepsCard } from './steps.js';

// The project view reads the ledger through the original pm-dash bundle, like pm-list.
const PM_SCRIPT = '/mods/pm-dash/skill/scripts/pm.py';
const STAGE = 'pm-stage', WORK = 'work', BOARD = 'pm-board';
const PARA_HOVER_SHOW_MS = 120, PARA_HOVER_HIDE_MS = 80;
const HOVER_CARD_OPEN_MS = 650, HOVER_CARD_SWAP_MS = 80, HOVER_CARD_LEAVE_MS = 300;
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
const WIDE = SPLIT_WIDE_MIN;
// Where the panel's dragged width is kept, in this mod's localStorage.
const PANEL_KEY = 'panelWidth';
const PANEL_SIZES_KEY = 'panelSizes';
// Retained child pane owners, keyed by scalar ownerId so cx.new(Class, { ownerId }) passes HostValue checks.
const PANE_OWNERS = new Map();
let paneOwnerSeq = 0;

function canUseChildEntity(cx) {
  if (!cx || typeof cx.new !== 'function') return false;
  if (cx.__isBlankProxy === true) return false;
  if (typeof cx.__nonExistentProbeForEntityCheck__ !== 'undefined') return false;
  return true;
}

function isRealEntity(ent) {
  return Boolean(
    ent
    && typeof ent === 'object'
    && typeof ent.set_props === 'function'
    && typeof ent.release === 'function'
    && typeof ent.__nonExistentProbeForEntityCheck__ === 'undefined',
  );
}

class ConversationPaneView extends View {
  init(p) {
    this.ownerId = p?.ownerId || '';
  }
  render(cx) {
    const owner = PANE_OWNERS.get(this.ownerId);
    if (!owner) return div().flex_1().min_w(0).h_full();
    return owner.renderConversationPane(cx);
  }
}

class SideSplitPaneView extends View {
  init(p) {
    this.ownerId = p?.ownerId || '';
  }
  render(cx) {
    const owner = PANE_OWNERS.get(this.ownerId);
    if (!owner) return div().w_full().h_full();
    return owner.renderSideSplitPane(cx);
  }
}
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
    if (p?.imageLightbox) { this.initImageLightbox(p, cx); return; }
    if (p?.agentWindow === 'titlebar' || p?.agentWindow === 'chat') { this.initAgentWindow(p, cx); return; }
    if (p?.header) { this.initHeaderOnly(cx); return; }
    this.bodyOnly = Boolean(p?.body);
    this.lastHeaderState = '';
    this.lastHeaderActionSeq = 0;
    this.ringAction = null;
    this.state = { pms: [], tasks: [] };
    this.events = []; this.logReceipts = []; this.logTurn = null; this.logTurn2 = null; this.logSupervised = undefined; this.clockOffsetMs = 0; this.serverNowMs = 0; this.serverNowAt = 0;
    this.pending = []; this.pendingByPm = new Map(); this.seq = 0; this.pastes = [];
    this.flushingQueue = false; this.flushingQueueAt = 0; this.queueTimer = false; this.confirmTimer = false; this.lastLogReadAt = 0; this.confirmLogProbes = new Set();
    this.refreshGate = createAsyncGate(); this.logGate = createAsyncGate();
    this.interruptingPm = ''; this.rotatingPm = ''; this.pmActionFeedback = null; this.turnTickTimer = false; this._lastPmLiveEdge = ''; this.edgeReadTimer = false;
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
    this.hoverPendingKey = '';
    this.hoverCardOver = '';
    this.hoverShowTimer = null;
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
    this.sideTab = 'threads'; this.remoteNoLibrary = ''; this.remoteNoMemory = ''; this.remoteNoTasks = '';
    this.threadsQuery = ''; this.threadsSearchTimer = null; this.threadsSearchSeq = 0;
    this.threadsSearchRows = []; this.threadsSearchTotal = 0; this.threadsSearchOffset = 0;
    this.threadsSearchMore = false; this.threadsSearchLoading = false; this.threadsSearchError = '';
    this.threadsSearchLocal = false;
    this.finishedExtra = []; this.finishedTotal = null; this.finishedOffset = 0;
    this.finishedMore = true; this.finishedLoading = false; this.finishedError = ''; this.finishedSeq = 0;
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
    this.imageCache = new Map(); this.imageLoading = new Set(); this.imageFailed = new Map();
    this._imageQueue = new Map(); this._imageFlushScheduled = false;
    this._imageStatQueue = new Map(); this._imageStatScheduled = false; this._imageStatRunning = new Set();
    this.imageLightbox = null; this.lightboxOverlayId = ''; this.lightboxOverlayMode = false;
    this.lightboxViewport = { width: 0, height: 0 }; this.lightboxOpeningExternal = false;
    this.inlineFilterOpen = false;
    this._sideTabStripW = 0;
    this.autoOpenSeenByLog = new Map();
    this.docLoading = ''; this.docError = ''; this.docShownBytes = DOC_INITIAL_BYTES;
    this.docFindOpen = false; this.docFindQuery = ''; this.docJumpQuery = ''; this.docFindJump = false; this.docMatchPos = 0;
    this.editingDoc = null; this.retopicOpen = false; this.retopicSaving = false; this.retopicError = '';
    this.confirmDeleteKey = ''; this.deleteBusy = ''; this.deleteError = ''; this.deletedBanner = null;
    this.historyView = null;
    // Right sidebar unified multi-tab workspace state.
    this.tabState = createSideTabsState();
    this.tabHandles = new Map();
    this.hoveredTabId = '';
    this.confirmCloseTabId = '';
    this.tabMenu = null;
    this.tabLimitBanner = '';
    this.hydratedTabProjects = new Set();
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
    // panelSizes: dual-mode persisted widths ({ compactPx, splitRatio }), migrated from legacy panelWidth;
    // panelDrag: {x, width, mode, moved} at the press while its edge is being dragged;
    // viewWidth: the whole view's width; gripLit: the pointer is on the edge, which then shows.
    this._shellCx = cx;
    this.panelSizes = this.keptPanelSizes();
    this.panelWant = this.keptPanelWidth();
    this.panelDrag = null; this.panelDragWidth = null; this.viewWidth = 0; this.gripLit = false;
    this.panelTransitioning = false; this.panelTransitionTimer = null; this._panelLockWidth = null;
    this._lastPanelTargetWidth = null; this._lastPanelOpen = false;
    this._panelOpenedFromClosed = false; this._panelPrevTab = 'threads';
    this._sideViewKey = ''; this._sideFading = false; this._sideFadeTimer = null;
    this._shellOnlyRender = false; this._lastLayout = null; this._syncPanesScheduled = false;
    this._paneOwnerId = `pm-pane-${++paneOwnerSeq}`;
    PANE_OWNERS.set(this._paneOwnerId, this);
    this._convEntity = null;
    this._sideEntity = null;
    if (canUseChildEntity(cx) === true) {
      try {
        const conv = cx.new(ConversationPaneView, { ownerId: this._paneOwnerId });
        const side = cx.new(SideSplitPaneView, { ownerId: this._paneOwnerId });
        if (isRealEntity(conv) === true && isRealEntity(side) === true) {
          this._convEntity = conv;
          this._sideEntity = side;
        } else {
          conv?.release?.();
          side?.release?.();
        }
      } catch (_) {
        this._convEntity = null;
        this._sideEntity = null;
      }
    }
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
    this.tabStripScroll = ScrollHandle.new();
    this.mentionScroll = ScrollHandle.new();
    this.searchScroll = ScrollHandle.new();
    this.lightboxScroll = ScrollHandle.new();
    this.lightboxFocus = cx.focus_handle();
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
    this.mentionTasksQuery = '';
    this.mentionTasksRows = [];
    this.mentionTasksLoading = false;
    this.mentionTasksSeq = 0;
    this.mentionTasksTimer = null;
    this.repoFilesSlug = ''; this.repoFilesRepo = ''; this.repoFilesSig = ''; this.repoFiles = [];
    this.repoFilesRead = false; this.repoFilesLoading = false; this.repoFilesAgain = false;
    this.repoFilesError = ''; this.repoFilesTruncated = false; this.repoFilesAt = 0;
    this.foldersOpen = false;
    this.foldersLive = null; this.foldersLiveSlug = '';
    this.foldersLoading = false; this.foldersBusy = '';
    this.foldersError = ''; this.foldersUnsupported = '';
    this.foldersEditingAlias = null;
    this.foldersConfirmRemove = null;
    this.foldersRemoteOpen = false; this.foldersRemotePath = '';
    this.foldersRemoteCheck = null;
    this.foldersRemotePicker = { open: false, loading: false, error: '', base: '', home: '', entries: [] };
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
      if (had !== Boolean(this.draft.trim()) || changedMention) this.notifyPanes(cx, { shell: false, conv: true });
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
          this.resetMentionTasks();
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
          this.resetMentionTasks();
          cx.notify();
        }
      });
    });
    this.threadsInput = InputState.new();
    this.threadsInput.on('change', (_e, cx) => {
      this.threadsQuery = this.threadsInput.value();
      this.scheduleThreadsSearch(cx);
    });
    this.threadsInput.on('focus', (_e, cx) => { this.typing = 'threadsSearch'; this.notifyPanes(cx, { shell: false, side: true }); });
    this.threadsInput.on('blur', (_e, cx) => { if (this.typing === 'threadsSearch') { this.typing = ''; this.notifyPanes(cx, { shell: false, side: true }); } });
    this.libraryInput = InputState.new();
    this.libraryInput.on('change', (_e, cx) => {
      this.libraryQuery = this.libraryInput.value();
      cx.notify();
    });
    this.libraryInput.on('focus', (_e, cx) => { this.typing = 'librarySearch'; this.notifyPanes(cx, { shell: false, side: true }); });
    this.libraryInput.on('blur', (_e, cx) => { if (this.typing === 'librarySearch') { this.typing = ''; this.notifyPanes(cx, { shell: false, side: true }); } });
    this.memoryInput = InputState.new();
    this.memoryInput.on('change', (_e, cx) => {
      this.memoryQuery = this.memoryInput.value();
      cx.notify();
    });
    this.memoryInput.on('focus', (_e, cx) => { this.typing = 'memorySearch'; this.notifyPanes(cx, { shell: false, side: true }); });
    this.memoryInput.on('blur', (_e, cx) => { if (this.typing === 'memorySearch') { this.typing = ''; this.notifyPanes(cx, { shell: false, side: true }); } });
    this.docFindInput = InputState.new();
    this.docFindInput.on('change', (_e, cx) => {
      this.docFindQuery = this.docFindInput.value();
      this.docMatchPos = 0;
      this.docFindJump = true;
      this.syncActiveTabFind();
      this.notifyPanes(cx, { shell: false, side: true });
    });
    this.docFindInput.on('focus', () => { this.typing = 'docFind'; });
    this.docFindInput.on('blur', () => { if (this.typing === 'docFind') this.typing = ''; });
    this.docNameInput = InputState.new();
    this.docNameInput.on('change', (_e, cx) => {
      this.syncActiveTabDirty();
      this.notifyPanes(cx, { shell: false, side: true });
    });
    this.docNameInput.on('focus', () => { this.typing = 'docName'; });
    this.docNameInput.on('blur', () => { if (this.typing === 'docName') this.typing = ''; });
    this.memDescInput = InputState.new();
    this.memDescInput.on('change', (_e, cx) => {
      this.syncActiveTabDirty();
      this.notifyPanes(cx, { shell: false, side: true });
    });
    this.memDescInput.on('focus', () => { this.typing = 'memDesc'; });
    this.memDescInput.on('blur', () => { if (this.typing === 'memDesc') this.typing = ''; });
    this.docEditorInput = TextareaState.new({ rows: 14 });
    this.docEditorInput.set_soft_wrap(true);
    this.docEditorInput.on('change', (_e, cx) => {
      this.syncActiveTabDirty();
      this.notifyPanes(cx, { shell: false, side: true });
    });
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
    this.folderAliasInput = InputState.new();
    this.folderAliasInput.on('change', () => {
      if (this.foldersEditingAlias) this.foldersEditingAlias.value = this.folderAliasInput.value();
    });
    this.folderAliasInput.on('submit', (_e, cx) => {
      this.commitRenameFolderAlias(cx);
    });
    this.folderAliasInput.on('focus', () => { this.typing = 'folderAlias'; });
    this.folderAliasInput.on('blur', () => { if (this.typing === 'folderAlias') this.typing = ''; });
    this.folderRemoteInput = InputState.new();
    this.folderRemoteInput.on('change', (_e, cx) => {
      this.foldersRemotePath = this.folderRemoteInput.value();
      this.foldersRemoteCheck = null;
      this.foldersError = '';
      cx?.notify?.();
    });
    this.folderRemoteInput.on('submit', (_e, cx) => {
      this.probeRemoteFolderPath(this.foldersRemotePath, cx, { addIfExists: true });
    });
    this.folderRemoteInput.on('focus', () => { this.typing = 'folderRemote'; });
    this.folderRemoteInput.on('blur', (_e, cx) => {
      if (this.typing === 'folderRemote') this.typing = '';
      if (this.machine && this.foldersRemoteOpen && String(this.foldersRemotePath || '').trim() && !this.foldersRemoteCheck) {
        this.probeRemoteFolderPath(this.foldersRemotePath, cx, { addIfExists: false });
      }
    });
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
    if (!this.__renderCheckOwnsCommands && typeof nextCommand === 'function' && typeof cx?.spawn === 'function') {
      cx.spawn(async cmdCx => {
        for (;;) {
          let command;
          try { command = await nextCommand(); } catch (_) { break; }
          this.handleModCommand(command, cmdCx);
        }
      });
    }
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
    this.watch(this.ledgerHome + '/pms', (_paths, cx) => this.refresh(cx), cx);
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
    this.watchRepoDocs(cx);
  }
  watchRepoDocs(cx) {
    if (this.machine || !this.ledgerHome) return;
    const repo = String(this.pm()?.repo || '').replace(/\/+$/, '');
    if (!repo) return;
    for (const sub of ['docs', 'doc']) {
      this.watch(`${repo}/${sub}`, (_paths, cx) => {
        if (!this.machine) this.onLocalLibraryChange(cx);
      }, cx);
    }
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

  logModError(source, error) {
    if (typeof createErrorLogger !== 'function') return;
    if (!this.errorLogger) {
      this.errorLogger = createErrorLogger({
        mod: 'pm-project',
        exec,
        getLedgerHome: () => this.ledgerHome || (home() + '/.dudu'),
      });
    }
    this.errorLogger.record(source, error);
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
          const curPm = this.pm();
          const curSlug = projectSlug(curPm);
          if (curSlug) {
            const mergedSig = state.tasks
              .filter(t => t && t.status === 'merged' && (t.project === curSlug || projectSlug({ repo: t.repo }) === curSlug))
              .map(t => String(t.id || '')).sort().join(',');
            if (this.mergedSigSlug === curSlug && this.mergedSig !== mergedSig) {
              this.dropCachePrefix(['repo_docs/']);
              this.libraryStale = true;
              this.repoFilesRead = false;
            }
            this.mergedSigSlug = curSlug;
            this.mergedSig = mergedSig;
          }
          if (this.pending?.length) this.reconcilePending(cx);
        }
      } catch (e) {
        if (machine === this.machine) {
          this.error = String(e?.message || e).trim();
          this.logModError(machine ? `refresh:${machine}` : 'refresh', e);
        }
      }
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
      this.logState = null; this.events = []; this.logReceipts = []; this.logTurn = null; this.logTurn2 = null; this.logSupervised = undefined; this.pastes = [];
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
              if (Array.isArray(got.events) && got.events.length > 0 && this.imageCache?.size) {
                const pref = `${machine || 'local'}|${slug}|`;
                for (const [k, entry] of this.imageCache.entries()) {
                  if (k.startsWith(pref) && entry) this.imageCache.set(k, { ...entry, checkedAt: 0 });
                }
              }
              this.logReceipts = Array.isArray(got.receipts) ? got.receipts : [];
              if (got.turn && typeof got.turn === 'object') this.logTurn = got.turn;
              if (got.turn2 && typeof got.turn2 === 'object') this.logTurn2 = got.turn2;
              if (typeof got.supervised === 'boolean') this.logSupervised = got.supervised;
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
          this.maybeAutoOpenFromEvents(log, cx);
          // The screenshots pasted into this project, for the messages the log has with image marks
          // (kept here for a project on another machine too, see pasteFolder).
          const dir = this.pasteFolder(pm);
          try {
            const ls = dir ? await exec('sh', ['-c', 'cd "$1" 2>/dev/null && ls -1 || true', 'sh', dir]) : null;
            if (path === this.logPath && ls?.code === 0) this.pastes = pastesIn(dir, ls.stdout);
          } catch (_) { /* Marks then show without their screenshots. */ }
        }
      } catch (e) {
        if (path === this.logPath && machine === this.machine) {
          this.logError = String(e?.message || e);
          this.logModError(machine ? `readLog:${machine}` : 'readLog', e);
        }
      }
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
          this.markEarlierEventsSeen(logKey(machine, path, slug), got?.events || []);
          if (visibleCount(this.events) > beforeCount || !this.logState.earlier) break;
        }
        if (path === this.logPath && machine === this.machine) {
          this.rest(Math.max(this.rise || 0, this.tall || this.high || 1));
          if (anchor) this.earlierAnchor = { anchor, left: SETTLE };
        }
      } catch (e) {
        if (path === this.logPath && machine === this.machine) {
          this.earlierError = String(e?.message || e).trim();
          this.logModError(machine ? `loadEarlier:${machine}` : 'loadEarlier', e);
        }
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

  resetThreadsHistoryState() {
    this.threadsSearchTimer?.cancel?.();
    this.threadsSearchTimer = null;
    this.threadsSearchSeq = (this.threadsSearchSeq || 0) + 1;
    this.threadsQuery = '';
    this.threadsSearchRows = [];
    this.threadsSearchTotal = 0;
    this.threadsSearchOffset = 0;
    this.threadsSearchMore = false;
    this.threadsSearchLoading = false;
    this.threadsSearchError = '';
    this.threadsSearchLocal = false;
    this.finishedSeq = (this.finishedSeq || 0) + 1;
    this.finishedExtra = [];
    this.finishedTotal = null;
    this.finishedOffset = 0;
    this.finishedMore = true;
    this.finishedLoading = false;
    this.finishedError = '';
    this.resetMentionTasks();
  }

  tasksQuerySupported() {
    return !(this.machine && (this.remoteNoProject === this.machine || this.remoteNoTasks === this.machine));
  }

  scheduleThreadsSearch(cx) {
    this.threadsSearchTimer?.cancel?.();
    this.threadsSearchTimer = null;
    const q = String(this.threadsQuery || '').trim();
    if (!q) {
      this.threadsSearchSeq = (this.threadsSearchSeq || 0) + 1;
      this.threadsSearchRows = [];
      this.threadsSearchTotal = 0;
      this.threadsSearchOffset = 0;
      this.threadsSearchMore = false;
      this.threadsSearchLoading = false;
      this.threadsSearchError = '';
      this.threadsSearchLocal = false;
      cx.notify();
      return;
    }
    this.threadsSearchError = '';
    if (!this.tasksQuerySupported()) {
      this.runThreadsSearch(cx, { append: false });
      return;
    }
    this.threadsSearchLoading = true;
    cx.notify();
    if (typeof cx?.timer?.after === 'function') {
      this.threadsSearchTimer = cx.timer.after(180, cx => {
        this.threadsSearchTimer = null;
        this.runThreadsSearch(cx, { append: false });
      });
    } else {
      this.runThreadsSearch(cx, { append: false });
    }
  }

  runThreadsSearch(cx, { append = false } = {}) {
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    const q = String(this.threadsQuery || '').trim();
    if (!pm || !slug || !q) {
      this.threadsSearchLoading = false;
      cx.notify();
      return;
    }
    const runLocal = () => {
      const allTasks = this.tasks || this.state.tasks;
      const rows = filterLocalThreads(pm, allTasks, this.events, q, {
        retiredParts: this.state.retired_parts,
        taskNumbers: this.state.task_numbers,
      });
      this.threadsSearchRows = rows;
      this.threadsSearchTotal = rows.length;
      this.threadsSearchOffset = rows.length;
      this.threadsSearchMore = false;
      this.threadsSearchLoading = false;
      this.threadsSearchError = '';
      this.threadsSearchLocal = true;
      cx.notify();
    };
    if (!this.tasksQuerySupported()) {
      runLocal();
      return;
    }
    if (append && (this.threadsSearchLoading || !this.threadsSearchMore)) return;
    const seq = append ? (this.threadsSearchSeq || 0) : ++this.threadsSearchSeq;
    const offset = append ? (this.threadsSearchOffset || 0) : 0;
    this.threadsSearchLoading = true;
    this.threadsSearchError = '';
    this.threadsSearchLocal = false;
    cx.notify();
    cx.spawn(async cx => {
      try {
        const r = await this.runProject(projectTasksArgv(slug, { status: 'all', q, offset, limit: TASKS_PAGE_LIMIT }));
        if (seq !== this.threadsSearchSeq || machine !== this.machine || q !== String(this.threadsQuery || '').trim()) return;
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.remoteNoTasks = machine;
            runLocal();
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const page = parseProjectTasksPage(JSON.parse(r.stdout || '{}'));
        if (!page) throw new Error('invalid tasks response');
        const rows = page.tasks.map(t => normalizeProjectTaskRow(t)).filter(Boolean);
        this.threadsSearchRows = append ? mergeFinishedRows(this.threadsSearchRows, rows) : rows;
        this.threadsSearchTotal = page.total;
        this.threadsSearchOffset = offset + page.tasks.length;
        this.threadsSearchMore = page.more;
        this.threadsSearchError = '';
      } catch (e) {
        if (seq === this.threadsSearchSeq && machine === this.machine) {
          this.threadsSearchError = String(e?.message || e).trim();
        }
      } finally {
        if (seq === this.threadsSearchSeq && machine === this.machine) {
          this.threadsSearchLoading = false;
          cx.notify();
        }
      }
    });
  }

  loadMoreFinished(cx) {
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    if (!pm || !slug || this.finishedLoading || !this.finishedMore || !this.tasksQuerySupported()) return;
    const seq = ++this.finishedSeq;
    const offset = this.finishedTotal == null ? 0 : (this.finishedOffset || 0);
    this.finishedLoading = true;
    this.finishedError = '';
    cx.notify();
    cx.spawn(async cx => {
      try {
        const r = await this.runProject(projectTasksArgv(slug, { status: 'finished', offset, limit: TASKS_PAGE_LIMIT }));
        if (seq !== this.finishedSeq || machine !== this.machine || slug !== projectSlug(this.pm())) return;
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.remoteNoTasks = machine;
            this.finishedMore = false;
            this.finishedError = '';
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const page = parseProjectTasksPage(JSON.parse(r.stdout || '{}'));
        if (!page) throw new Error('invalid tasks response');
        const rows = page.tasks.map(t => normalizeProjectTaskRow(t)).filter(Boolean);
        this.finishedExtra = mergeFinishedRows(this.finishedExtra, rows);
        this.finishedTotal = page.total;
        this.finishedOffset = offset + page.tasks.length;
        this.finishedMore = page.more;
        this.finishedError = '';
      } catch (e) {
        if (seq === this.finishedSeq && machine === this.machine) {
          this.finishedError = String(e?.message || e).trim();
        }
      } finally {
        if (seq === this.finishedSeq && machine === this.machine) {
          this.finishedLoading = false;
          cx.notify();
        }
      }
    });
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
    return sessionTabAvailable({
      sessionSupported: this.sessionSupported(),
      stateTask,
      task,
      threadId: this.thread,
      sessionTask: this.threadSessionTask,
      sessionState: this.threadSessionState,
      hasSession: Boolean(this.threadSession),
    });
  }

  activeThreadTab(stateTask, task) {
    return (this.threadTab === 'session' && this.sessionTabAvailable(stateTask, task)) ? 'session' : 'log';
  }

  selectThreadTab(tab, cx) {
    const { stateTask, task } = this.currentThreadPair();
    if (tab === 'session' && !this.sessionTabAvailable(stateTask, task)) return;
    const freshForThread = !this.threadSession || this.threadSession.taskId !== this.thread;
    this.threadTab = tab === 'session' ? 'session' : 'log';
    const active = this.activeSideTab();
    if (active && active.kind === 'thread') {
      this.tabState = updateSideTab(this.sideTabsState(), active.id, { threadTab: this.threadTab }).state;
      this.persistSideTabs();
    }
    if (this.threadTab === 'session') {
      if (freshForThread) {
        this.sessionAway = false;
        this.sessionSettle = SETTLE;
      }
      if (freshForThread || this.threadSessionStale || this.threadIsLive(stateTask, task)) {
        this.readThreadSession(cx);
      }
    }
    this.notifyPanes(cx, { shell: false, side: true });
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
    if (!this.sessionSupported() || knownUnsupportedSession(task, stateTask)) {
      if (knownUnsupportedSession(task, stateTask) && this.threadSessionTask !== id) {
        this.threadSessionTask = id;
        this.threadSessionState = 'unavailable';
      }
      return;
    }
    const knownFromState = contextTokens(stateTask?.context_tokens) > 0;
    const knownSupported = supportedSessionKind(taskSessionKind(stateTask, task));
    const wantSession = wantThreadSession({
      threadTab: this.threadTab,
      stateTask,
      task,
      threadId: id,
      sessionTask: this.threadSessionTask,
      sessionState: this.threadSessionState,
    });
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
    // On the Log tab: if `state` already reports `context_tokens` (or this is a local thread with a
    // known supported runtime such as Claude / agy), we already know the Conversation tab is available
    // without spawning `pm.py project session` until the user opens that tab. Remote machines without
    // `context_tokens` still probe once so an older remote `pm.py` can set `remoteNoSession`.
    if (knownFromState || (!this.machine && knownSupported)) {
      if (knownFromState && this.threadSession && this.threadSession.taskId === id && this.threadSession.context !== contextTokens(stateTask.context_tokens)) {
        this.threadSessionStale = true;
      }
      if (this.threadSessionState === 'unavailable' && this.threadSessionTask === id) {
        this.threadSessionState = '';
        this.threadSessionTask = '';
      }
      return;
    }
    // Wait until tasks/<id>.json settles when opening a local/remote thread with an existing home, unless
    // no home is known yet (so we avoid probing an unsupported closed task whose worker kind is in its file).
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
    const { stateTask, task } = this.currentThreadPair();
    if (knownUnsupportedSession(task, stateTask)) {
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
            const pair = this.currentThreadPair();
            const keepTabEmpty = !isUnsupportedSessionError(r)
              && supportedSessionKind(taskSessionKind(pair.stateTask, pair.task))
              && pair.task?.status !== 'proposed';
            this.threadSession = null;
            this.threadSessionTask = id;
            this.threadSessionState = keepTabEmpty ? 'empty' : 'unavailable';
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
    this.dropCachePrefix(['docs/', 'repo_docs/', 'research/']);
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
    this.inlineFilterOpen = false;
    this.historyView = null;
  }

  readLibrary(cx) {
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    if (slug !== this.librarySlug) {
      const prevSlug = this.librarySlug;
      this.librarySlug = slug;
      this.libraryRoots = [];
      this.libraryFiles = [];
      this.libraryRead = false;
      this.libraryProbed = false;
      this.libraryStale = false;
      this.libraryError = '';
      if (prevSlug) {
        if (this.activeDoc?.tab === 'library') this.activeDoc = null;
        if (this.editingDoc?.tab === 'library') this.editingDoc = null;
        if (this.historyView?.tab === 'library') this.historyView = null;
      }
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
          this.imageCache = reconcileImageCache(this.imageCache, all, { machine: machine || 'local', slug });
          this.libraryRead = true;
          this.libraryStale = false;
          this.libraryError = '';
          this.reconcileMissingTabs('library');
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
          this.imageCache = reconcileImageCache(this.imageCache, all, { machine: machine || 'local', slug });
          this.memoryRead = true;
          this.memoryStale = false;
          this.memoryError = '';
          this.reconcileMissingTabs('memory');
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

  // Prefetches small active documents (`docs` and `repo_docs`) locally once Library is shown so search matches body text.
  prefetchLibraryDocs(cx) {
    const slug = this.librarySlug, machine = this.machine;
    if (!slug || machine || !this.librarySupported()) return;
    const candidates = (this.libraryFiles || [])
      .filter(f => (f.root === 'docs' || f.root === 'repo_docs')
        && f.kind !== 'folder' && !f.archive && !f.superseded_by
        && f.size <= 65536 && contextShowMode(f, f.path) === 'text')
      .sort((a, b) => String(b.modified || '').localeCompare(String(a.modified || '')))
      .slice(0, 8);
    for (const f of candidates) {
      const key = contextKey(f);
      if (isFreshDocEntry(this.docCache.get(key), f) || isFreshDocFailure(this.docFailed.get(key), f)) continue;
      const snapMeta = f;
      cx.spawn(async cx => {
        try {
          const r = await this.runProject(projectFileArgv(slug, f.root, f.path));
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

  // ---- Inline & side-tab image previews (safe local + remote staging into appHome cache) ----
  markEarlierEventsSeen(log, earlierEvents) {
    if (!log || !Array.isArray(earlierEvents) || !earlierEvents.length) return;
    const byLog = (this.autoOpenSeenByLog ||= new Map());
    const state = byLog.get(log);
    if (state) markAutoOpenHistory(state, earlierEvents);
  }

  maybeAutoOpenFromEvents(log, cx) {
    if (!log || !Array.isArray(this.events)) return;
    const byLog = (this.autoOpenSeenByLog ||= new Map());
    let state = byLog.get(log);
    if (!state) {
      // Seed baseline with all events already present when this project first loads so history never replays.
      byLog.set(log, seedAutoOpenState(this.events));
      return;
    }
    const activeTab = typeof this.activeSideTab === 'function' ? this.activeSideTab() : null;
    const editingDirty = Boolean((this.editingDoc && this.editorDirty?.()) || activeTab?.dirty);
    const res = pickAutoOpenTarget(this.events, this.docLinkContext(), {
      seenKeys: state.seen,
      minSeq: state.minSeq,
      minAt: state.minAt,
      tasks: this.projectTasks(),
      editingDirty,
    });
    for (const k of res.newKeys) state.seen.add(k);
    if (!res.target) return;
    this.openDoc({ tab: res.target.tab, root: res.target.root, path: res.target.path }, cx);
  }

  imageCacheKey(target) {
    const slug = projectSlug(this.pm());
    return `${this.machine || 'local'}|${slug}|${target?.key || ''}`;
  }

  imagePreviewState(target, cx) {
    if (!target) return { status: 'error', error: 'invalid path' };
    const cache = (this.imageCache ||= new Map());
    const failedMap = (this.imageFailed ||= new Map());
    const loadingSet = (this.imageLoading ||= new Set());
    const queue = (this._imageQueue ||= new Map());
    const cKey = this.imageCacheKey(target);
    const meta = this.findDocMeta(target.root, target.path);
    const version = meta?.version || '';
    const now = Date.now();
    const failed = failedMap.get(cKey);
    const cached = cache.get(cKey);
    if (cached) {
      if (!isImageEntryFresh(cached, { version })) {
        if (!isImageFailActive(failed, { version, now }) && !loadingSet.has(cKey) && cx?.timer?.after) {
          queue.set(cKey, { target, force: true, background: true });
          if (!this._imageFlushScheduled) {
            this._imageFlushScheduled = true;
            cx.timer.after(0, liveCx => this.flushImageQueue(liveCx));
          }
        }
        return { status: 'ready', entry: cached };
      }
      if (needsImageRevalidate(cached, now, { remote: Boolean(this.machine) }) && cx?.timer?.after) {
        this.scheduleImageRevalidate(target, cKey, cx);
      }
      return { status: 'ready', entry: cached };
    }
    if (isImageFailActive(failed, { version, now })) {
      return { status: 'error', error: failed.error || 'failed' };
    }
    if (!loadingSet.has(cKey) && cx?.timer?.after) {
      queue.set(cKey, { target, force: false, background: false });
      if (!this._imageFlushScheduled) {
        this._imageFlushScheduled = true;
        cx.timer.after(0, liveCx => this.flushImageQueue(liveCx));
      }
    }
    return { status: 'loading' };
  }

  scheduleImageRevalidate(target, cKey, cx) {
    if (!target?.baseDir || !target?.relPath) return;
    const loadingSet = (this.imageLoading ||= new Set());
    const statRunning = (this._imageStatRunning ||= new Set());
    if (loadingSet.has(cKey) || statRunning.has(cKey)) return;
    const statQueue = (this._imageStatQueue ||= new Map());
    statQueue.set(cKey, target);
    if (!this._imageStatScheduled && cx?.timer?.after) {
      this._imageStatScheduled = true;
      cx.timer.after(0, liveCx => this.flushImageStatQueue(liveCx));
    }
  }

  flushImageStatQueue(cx) {
    this._imageStatScheduled = false;
    const statQueue = (this._imageStatQueue ||= new Map());
    if (!statQueue.size) return;
    const batch = Array.from(statQueue.entries());
    statQueue.clear();
    const statRunning = (this._imageStatRunning ||= new Set());
    const machine = this.machine;
    const items = [];
    const byKey = new Map();
    for (const [cKey, target] of batch) {
      if (statRunning.has(cKey) || this.imageLoading?.has(cKey)) continue;
      statRunning.add(cKey);
      byKey.set(cKey, target);
      items.push({ key: cKey, baseDir: target.baseDir, relPath: target.relPath });
    }
    if (!items.length || !cx?.spawn) {
      for (const [cKey] of batch) statRunning.delete(cKey);
      return;
    }
    cx.spawn(async liveCx => {
      try {
        const r = machine
          ? await exec(...statRemoteImagesArgv(items), { on: machine, timeout: 10000 })
          : await execPython(exec, statLocalImagesArgv(items), { timeout: 10000 });
        const now = Date.now();
        if (r.code !== 0) {
          for (const cKey of byKey.keys()) {
            const entry = this.imageCache?.get(cKey);
            if (entry) this.imageCache.set(cKey, { ...entry, checkedAt: now, stale: false });
          }
          return;
        }
        const parsed = JSON.parse(String(r.stdout || '').trim());
        const results = parsed?.items && typeof parsed.items === 'object' ? parsed.items : {};
        for (const [cKey, target] of byKey.entries()) {
          const entry = this.imageCache?.get(cKey);
          if (!entry) continue;
          const info = results[cKey];
          if (info?.ok) {
            const diskMtime = Number(info.mtime_ns) || 0;
            const diskSize = Number(info.size) || 0;
            const changed = !isImageEntryFresh(entry, { mtimeNs: diskMtime, size: diskSize });
            const meta = this.findDocMeta(target.root, target.path);
            const version = meta?.version || '';
            const failed = this.imageFailed?.get(cKey);
            if (changed && !isImageFailActive(failed, { version, mtimeNs: diskMtime, size: diskSize, now })) {
              this.loadImagePreview(target, liveCx, { force: true, background: true, diskMtimeNs: diskMtime, diskSize });
            } else {
              this.imageCache.set(cKey, {
                ...entry,
                ...(changed ? {} : { mtimeNs: diskMtime || entry.mtimeNs || 0 }),
                checkedAt: now,
                stale: false,
              });
            }
          } else {
            this.imageCache.set(cKey, { ...entry, checkedAt: now, stale: false });
          }
        }
      } catch (_) {
        const now = Date.now();
        for (const cKey of byKey.keys()) {
          const entry = this.imageCache?.get(cKey);
          if (entry) this.imageCache.set(cKey, { ...entry, checkedAt: now, stale: false });
        }
      } finally {
        for (const cKey of byKey.keys()) statRunning.delete(cKey);
      }
    });
  }

  flushImageQueue(cx) {
    this._imageFlushScheduled = false;
    const queue = (this._imageQueue ||= new Map());
    if (!queue.size) return;
    const batch = Array.from(queue.values());
    queue.clear();
    for (const item of batch) {
      if (item && item.target) {
        this.loadImagePreview(item.target, cx, {
          force: Boolean(item.force),
          background: Boolean(item.background),
          diskMtimeNs: Number(item.diskMtimeNs) || 0,
          diskSize: Number(item.diskSize) || 0,
        });
      } else {
        this.loadImagePreview(item, cx);
      }
    }
  }

  loadImagePreview(target, cx, { force = false, background = false, diskMtimeNs = 0, diskSize = 0 } = {}) {
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    if (!pm || !slug || !target?.baseDir || !target?.relPath) return;
    const cache = (this.imageCache ||= new Map());
    const failedMap = (this.imageFailed ||= new Map());
    const loadingSet = (this.imageLoading ||= new Set());
    const cKey = this.imageCacheKey(target);
    const meta = this.findDocMeta(target.root, target.path);
    const version = meta?.version || '';
    if (!force) {
      const cached = cache.get(cKey);
      if (cached && isImageEntryFresh(cached, { version })) return;
      if (loadingSet.has(cKey)) return;
    } else {
      if (loadingSet.has(cKey)) return;
      if (background) {
        if (isImageFailActive(failedMap.get(cKey), { version, mtimeNs: diskMtimeNs, size: diskSize, now: Date.now() })) return;
      } else {
        failedMap.delete(cKey);
      }
    }
    loadingSet.add(cKey);
    if (force && !background) cx?.notify?.();
    const cacheDir = `${appHome()}/${INLINE_IMAGE_CACHE_DIR}`;
    cx.spawn(async liveCx => {
      let succeeded = false;
      const recordFailure = errMsg => {
        const failAt = Date.now();
        this.imageFailed.set(cKey, {
          error: String(errMsg || 'failed'),
          at: failAt,
          version,
          mtimeNs: Number(diskMtimeNs) || 0,
          size: Number(diskSize) || 0,
        });
        const existing = this.imageCache.get(cKey);
        if (existing) {
          this.imageCache.set(cKey, { ...existing, checkedAt: failAt, stale: false });
        }
      };
      try {
        let parsed = null;
        let remoteMtimeNs = 0;
        if (!machine) {
          const r = await execPython(exec, stageLocalImageArgv(target.baseDir, target.relPath, cacheDir, {
            relPrefix: INLINE_IMAGE_CACHE_DIR,
            maxBytes: INLINE_IMAGE_MAX_BYTES,
          }), { timeout: 15000 });
          if (r.code !== 0) throw new Error((r.stderr || r.stdout || `exit ${r.code}`).trim());
          parsed = JSON.parse(String(r.stdout || '').trim());
        } else {
          const [cmd, args] = readRemoteImageArgv(target.baseDir, target.relPath, {
            maxBytes: INLINE_IMAGE_REMOTE_MAX_BYTES,
          });
          const r = await exec(cmd, args, { on: machine, timeout: 25000 });
          if (r.code !== 0) throw new Error((r.stderr || r.stdout || `exit ${r.code}`).trim());
          const remote = JSON.parse(String(r.stdout || '').trim());
          remoteMtimeNs = Number(remote?.mtime_ns) || 0;
          if (!remote?.ok) {
            parsed = remote;
          } else {
            const tmpB64 = `${appHome()}/.pm-img-${remote.hash}-${Date.now()}.b64.tmp`;
            await writeTextFile(tmpB64, String(remote.b64 || ''), null);
            const wr = await execPython(exec, writeStagedImageArgv(cacheDir, remote.hash, remote.ext, tmpB64, {
              relPrefix: INLINE_IMAGE_CACHE_DIR,
            }), { timeout: 15000 });
            if (wr.code !== 0) throw new Error((wr.stderr || wr.stdout || `exit ${wr.code}`).trim());
            parsed = JSON.parse(String(wr.stdout || '').trim());
          }
        }
        if (parsed?.ok && parsed.rel) {
          succeeded = true;
          this.imageFailed.delete(cKey);
          const nextEntry = {
            rel: parsed.rel,
            width: Number(parsed.width) || 0,
            height: Number(parsed.height) || 0,
            size: Number(parsed.size) || 0,
            hash: String(parsed.hash || ''),
            mtimeNs: Number(parsed.mtime_ns) || remoteMtimeNs || 0,
            checkedAt: Date.now(),
            stale: false,
            version,
          };
          this.imageCache.set(cKey, nextEntry);
          if (this.imageLightbox && this.imageLightbox.key === target.key) {
            this.imageLightbox = {
              ...this.imageLightbox,
              rel: nextEntry.rel,
              width: nextEntry.width,
              height: nextEntry.height,
              size: nextEntry.size,
              hash: nextEntry.hash,
              mtimeNs: nextEntry.mtimeNs,
            };
          }
        } else {
          recordFailure(parsed?.error || 'failed');
        }
      } catch (e) {
        recordFailure(e?.message || e || 'failed');
      } finally {
        this.imageLoading.delete(cKey);
        if (succeeded || !background) {
          this.notifyPanes(liveCx, { shell: Boolean(this.imageLightbox), conv: true, side: true });
        }
      }
    });
  }

  renderInlineImagePreviews(keyPrefix, rawText, t, cx, { maxWidth = 520, maxHeight = 280 } = {}) {
    const refs = extractInlineImageRefs(rawText, this.docLinkContext());
    if (!refs.length) return null;
    const lang = this.lang;
    const splitLay = this._lastLayout || this.currentSplitLayout();
    const openInlineW = (this.isPanelOpen() && splitLay.layoutKind === 'inline') ? splitLay.slotWidth : 0;
    const colW = this.viewWidth ? Math.min(COLUMN, Math.max(240, this.viewWidth - openInlineW - 80)) : COLUMN;
    const effectiveMaxW = Math.max(180, Math.min(maxWidth, colW - 48));
    const cards = refs.map((ref, idx) => {
      const id = `img-prev-${keyPrefix}-${idx}`;
      const st = this.imagePreviewState(ref, cx);
      if (st.status === 'ready') {
        const box = fitImageBox(st.entry.width, st.entry.height, { maxWidth: effectiveMaxW, maxHeight });
        const tip = `${word(lang, 'imageZoomLightbox')} · ${ref.name}`;
        const card = v_flex().id(id).w(box.width + 2).rounded(10).overflow_hidden()
          .border_1().border_color(t.border).bg(t.surface).cursor_pointer()
          .hover(s => s.border_color(withAlpha(t.accent, .55)))
          .accessibility_label(tip)
          .on_click((_e, clickCx) => this.openImageLightbox(ref, st.entry, clickCx))
          .child(image(st.entry.rel).w(box.width).h(box.height))
          .child(h_flex().w_full().px(8).py(5).gap(6).items_center().justify_between()
            .bg(withAlpha(t.raised, .75)).border_t_1().border_color(t.border)
            .child(h_flex().min_w(0).flex_1().gap(5).items_center()
              .child(this.icon('image', 12).flex_none().text_color(t.dim))
              .child(div().min_w(0).truncate().text_size(11.5).text_color(t.muted).child(ref.name)))
            .child(h_flex().flex_none().gap(5).items_center()
              .child(div().flex_none().text_size(11).text_color(t.dim)
                .child(word(lang, 'imageDimensions', st.entry.width, st.entry.height)))
              .child(this.icon('zoom-in', 11.5).flex_none().text_color(t.dim))));
        return this.withTip(id, card, tip, t, { placement: 'above-left' });
      }
      if (st.status === 'loading') {
        return h_flex().id(id).h(32).px(10).gap(7).rounded(8).items_center()
          .bg(t.surface).border_1().border_color(t.border).text_size(12).text_color(t.dim)
          .child(svg(SPINNER).size(13).flex_none().spin(900))
          .child(div().min_w(0).truncate().child(ref.name));
      }
      const errTip = `${st.error === 'too large' ? word(lang, 'imageTooLarge') : word(lang, 'imageLoadFailed')} · ${ref.name}`;
      const chip = h_flex().id(id).h(30).px(9).gap(6).rounded(8).items_center().cursor_pointer()
        .bg(t.surface).border_1().border_color(t.border).text_size(12).text_color(t.dim)
        .hover(s => s.bg(t.hover).text_color(t.muted))
        .on_click((_e, clickCx) => {
          this.loadImagePreview(ref, clickCx, { force: true });
          this.openDoc({ tab: 'library', root: ref.root, path: ref.path }, clickCx);
        })
        .child(this.icon('image', 13).flex_none())
        .child(div().min_w(0).truncate().child(ref.name));
      return this.withTip(id, chip, errTip, t, { placement: 'above-left' });
    });
    return v_flex().id(`img-strip-${keyPrefix}`).w_full().mt(8).gap(8).items_start().children(cards);
  }

  // ---- Full-window image lightbox (zoom, 2D scroll & system preview) ----
  initImageLightbox(p, cx) {
    this.lightboxOverlayMode = true;
    this.lightboxOverlayId = String(p?.overlay || '');
    this.imageLightbox = createImageLightboxState(p.imageLightbox || {});
    this.lang = this.imageLightbox.lang || 'en';
    this.machine = this.imageLightbox.machine || '';
    this.lightboxFocus = cx.focus_handle();
    this.lightboxScroll = ScrollHandle.new();
    this.lightboxViewport = { width: 0, height: 0 };
    this.viewWidth = 0;
    this.hoverKey = '';
    this.hoverPendingKey = '';
    this.hoverCardOver = '';
    this.hoverShowTimer = null;
    this.hoverHideTimer = null;
    cx.timer?.after?.(0, () => this.lightboxFocus?.focus?.());
    this.refreshLightboxImageIfChanged(cx);
  }

  refreshLightboxImageIfChanged(cx) {
    const lb = this.imageLightbox;
    if (!lb?.baseDir || !lb?.relPath || this.machine || !cx?.spawn) return;
    const key = lb.key || `${lb.root}/${lb.path}`;
    const cacheDir = `${appHome()}/${INLINE_IMAGE_CACHE_DIR}`;
    cx.spawn(async liveCx => {
      try {
        const sr = await execPython(exec, statLocalImagesArgv([{ key, baseDir: lb.baseDir, relPath: lb.relPath }]), { timeout: 8000 });
        if (sr.code !== 0) return;
        const statParsed = JSON.parse(String(sr.stdout || '').trim());
        const info = statParsed?.items?.[key];
        if (!info?.ok) return;
        const diskMtime = Number(info.mtime_ns) || 0;
        const diskSize = Number(info.size) || 0;
        if (isImageEntryFresh(lb, { mtimeNs: diskMtime, size: diskSize })) return;
        const r = await execPython(exec, stageLocalImageArgv(lb.baseDir, lb.relPath, cacheDir, {
          relPrefix: INLINE_IMAGE_CACHE_DIR,
          maxBytes: INLINE_IMAGE_MAX_BYTES,
        }), { timeout: 15000 });
        if (r.code !== 0) return;
        const parsed = JSON.parse(String(r.stdout || '').trim());
        if (parsed?.ok && parsed.rel && this.imageLightbox) {
          this.imageLightbox = {
            ...this.imageLightbox,
            rel: parsed.rel,
            width: Number(parsed.width) || this.imageLightbox.width,
            height: Number(parsed.height) || this.imageLightbox.height,
            size: Number(parsed.size) || this.imageLightbox.size,
            hash: String(parsed.hash || ''),
            mtimeNs: Number(parsed.mtime_ns) || diskMtime || 0,
          };
          liveCx.notify?.();
        }
      } catch (_) { /* Keep current lightbox image. */ }
    });
  }

  openImageLightbox(target, entry, cx) {
    if (!target && !entry?.rel) return;
    this.hoverKey = '';
    const lang = this.lang || this.state?.lang || 'en';
    const cKey = target ? this.imageCacheKey(target) : '';
    const freshEntry = (cKey && this.imageCache?.get(cKey)) || entry;
    if (target && cKey && cx?.timer?.after && needsImageRevalidate(freshEntry, Date.now(), { remote: Boolean(this.machine), minAgeMs: IMAGE_LIGHTBOX_REVALIDATE_MS })) {
      this.scheduleImageRevalidate(target, cKey, cx);
    }
    const absPath = resolveSystemPreviewPath({
      target,
      entry: freshEntry,
      appHomeDir: typeof appHome === 'function' ? appHome() : '',
      machine: this.machine || '',
    });
    const payload = createImageLightboxState({
      rel: freshEntry?.rel || '',
      width: freshEntry?.width || 0,
      height: freshEntry?.height || 0,
      size: freshEntry?.size || 0,
      mtimeNs: freshEntry?.mtimeNs || 0,
      hash: freshEntry?.hash || '',
      name: target?.name || fileName(target?.path || target?.relPath || ''),
      root: target?.root || '',
      path: target?.path || '',
      baseDir: target?.baseDir || '',
      relPath: target?.relPath || '',
      ext: target?.ext || '',
      key: target?.key || '',
      machine: this.machine || '',
      absPath,
      lang,
      mode: 'fit',
      scale: 1,
    });
    if (this.lightboxOverlayId && typeof closeOverlay === 'function') {
      closeOverlay(this.lightboxOverlayId);
      this.lightboxOverlayId = '';
    }
    const ovId = typeof openOverlay === 'function' ? openOverlay(imageLightboxOverlaySpec(payload)) : '';
    if (ovId) {
      this.lightboxOverlayId = ovId;
      this.imageLightbox = null;
      return;
    }
    this.imageLightbox = payload;
    this.lightboxViewport = {
      width: this.viewWidth || 0,
      height: Math.max(0, (this.high || 0) - LIGHTBOX_TOOLBAR_HEIGHT),
    };
    cx?.timer?.after?.(0, () => this.lightboxFocus?.focus?.());
    this.notifyPanes(cx, { shell: true, conv: false, side: false });
  }

  closeImageLightbox(cx, { restoreFocus = true } = {}) {
    this.hoverKey = '';
    if (this.lightboxOverlayMode) {
      const ovId = this.lightboxOverlayId || (typeof props === 'function' ? String(props()?.overlay || '') : '');
      if (ovId && typeof closeOverlay === 'function') {
        closeOverlay(ovId);
      }
      this.imageLightbox = null;
      return;
    }
    if (this.lightboxOverlayId && typeof closeOverlay === 'function') {
      closeOverlay(this.lightboxOverlayId);
      this.lightboxOverlayId = '';
    }
    if (!this.imageLightbox) return;
    this.imageLightbox = null;
    if (restoreFocus) this.keyFocus?.focus?.();
    this.notifyPanes(cx, { shell: true, conv: false, side: false });
  }

  currentLightboxLayout() {
    const lb = this.imageLightbox;
    const vpW = this.lightboxViewport?.width || this.viewWidth || 960;
    const vpH = this.lightboxViewport?.height || Math.max(240, (this.high || 688) - LIGHTBOX_TOOLBAR_HEIGHT);
    return computeLightboxLayout({
      naturalW: lb?.width || 0,
      naturalH: lb?.height || 0,
      viewportW: vpW,
      viewportH: vpH,
      mode: lb?.mode || 'fit',
      scale: lb?.scale || 1,
      padding: LIGHTBOX_CANVAS_PADDING,
    });
  }

  notifyLightbox(cx) {
    if (this.lightboxOverlayMode) {
      cx?.notify?.();
    } else {
      this.notifyPanes(cx, { shell: true, conv: false, side: false });
    }
  }

  stepLightboxZoomBy(direction, cx) {
    if (!this.imageLightbox) return;
    const lay = this.currentLightboxLayout();
    this.imageLightbox = stepLightboxZoom(this.imageLightbox, direction, lay.fitScale);
    this.notifyLightbox(cx);
  }

  setLightboxFit(cx) {
    if (!this.imageLightbox) return;
    const lay = this.currentLightboxLayout();
    this.imageLightbox = { ...this.imageLightbox, mode: 'fit', scale: lay.fitScale };
    this.notifyLightbox(cx);
  }

  setLightboxActual(cx) {
    if (!this.imageLightbox) return;
    this.imageLightbox = { ...this.imageLightbox, mode: 'scale', scale: 1 };
    this.notifyLightbox(cx);
  }

  toggleLightboxFitActual(cx) {
    if (!this.imageLightbox) return;
    const lay = this.currentLightboxLayout();
    this.imageLightbox = toggleLightboxFitActual(this.imageLightbox, lay.fitScale);
    this.notifyLightbox(cx);
  }

  cycleLightboxZoom(cx) {
    if (!this.imageLightbox) return;
    const lay = this.currentLightboxLayout();
    this.imageLightbox = cycleLightboxZoomPreset(this.imageLightbox, lay.fitScale);
    this.notifyLightbox(cx);
  }

  openImageInSystem(target, entry, cx, { inLightbox = false } = {}) {
    const filePath = (inLightbox && this.imageLightbox?.absPath)
      || resolveSystemPreviewPath({
        target,
        entry,
        appHomeDir: typeof appHome === 'function' ? appHome() : '',
        machine: inLightbox ? (this.imageLightbox?.machine || '') : (this.machine || ''),
      });
    const platform = (typeof appWindow === 'function' ? appWindow()?.platform : '') || 'macos';
    const spec = systemOpenFileArgv(filePath, platform);
    if (!spec) return;
    const [cmd, args] = spec;
    if (inLightbox && this.imageLightbox) {
      this.imageLightbox = { ...this.imageLightbox, error: '' };
      this.notifyLightbox(cx);
    }
    cx.spawn(async liveCx => {
      try {
        const r = await exec(cmd, args, { timeout: 10000 });
        if (r && r.code !== 0) {
          throw new Error((r.stderr || r.stdout || `exit ${r.code}`).trim());
        }
      } catch (e) {
        if (inLightbox && this.imageLightbox) {
          this.imageLightbox = {
            ...this.imageLightbox,
            error: word(this.lang || 'en', 'imageOpenExternalFailed', String(e?.message || e || 'error')),
          };
          this.notifyLightbox(liveCx);
        }
      }
    });
  }

  handleLightboxKeyDown(e, cx) {
    if (!this.imageLightbox) return false;
    const ks = String(e?.keystroke || '').toLowerCase();
    if (ks === 'escape') {
      cx?.stop_propagation?.();
      this.closeImageLightbox(cx);
      return true;
    }
    if (ks === '=' || ks === '+' || ks === 'shift-=' || ks === 'cmd-=' || ks === 'cmd-+' || ks === 'ctrl-=' || ks === 'ctrl-+') {
      cx?.stop_propagation?.();
      this.stepLightboxZoomBy(1, cx);
      return true;
    }
    if (ks === '-' || ks === 'cmd--' || ks === 'ctrl--') {
      cx?.stop_propagation?.();
      this.stepLightboxZoomBy(-1, cx);
      return true;
    }
    if (ks === '0' || ks === 'cmd-0' || ks === 'ctrl-0') {
      cx?.stop_propagation?.();
      this.setLightboxFit(cx);
      return true;
    }
    if (ks === '1' || ks === 'cmd-1' || ks === 'ctrl-1') {
      cx?.stop_propagation?.();
      this.setLightboxActual(cx);
      return true;
    }
    if (ks === 'o' || ks === 'cmd-o' || ks === 'ctrl-o') {
      cx?.stop_propagation?.();
      this.openImageInSystem(this.imageLightbox, { rel: this.imageLightbox.rel }, cx, { inLightbox: true });
      return true;
    }
    return false;
  }

  lightboxIconBtn(id, name, tip, action, t, { size = 14, active = false } = {}) {
    return this.withTip(id, h_flex().id(id).size(28).flex_none().rounded(7).items_center().justify_center()
      .text_color(active ? t.accent : t.muted)
      .when(active, el => el.bg(withAlpha(t.accent, .16)))
      .accessibility_label(tip)
      .on_mouse_down('left', (_e, cx) => cx.stop_propagation?.())
      .when(Boolean(action), el => el.cursor_pointer()
        .hover(s => active ? s.bg(withAlpha(t.accent, .22)) : s.bg(t.hover).text_color(t.foreground))
        .on_click((_e, cx) => { cx.stop_propagation?.(); this.hoverKey = ''; action(cx); }))
      .when(!action, el => el.opacity(.35))
      .child(this.icon(name, size)), tip, t, { placement: 'below-right' });
  }

  renderImageLightbox(cx, { inProject = false } = {}) {
    const t = theme();
    const dark = isDarkTheme(t);
    const lb = this.imageLightbox;
    const lang = this.lang || lb?.lang || this.state?.lang || 'en';
    if (!lb) return v_flex().size_full();
    const lay = this.currentLightboxLayout();
    const openPath = lb.absPath || resolveSystemPreviewPath({
      target: lb,
      entry: { rel: lb.rel },
      appHomeDir: typeof appHome === 'function' ? appHome() : '',
      machine: lb.machine || '',
    });
    const toggleId = lay.isFit ? 'lightbox-zoom-actual' : 'lightbox-zoom-fit';
    const toggleIcon = lay.isFit ? 'zoom-actual' : 'zoom-fit';
    const toggleTip = word(lang, lay.isFit ? 'imageZoomActual' : 'imageZoomFit');
    const percentTip = word(lang, 'imageZoomCycle');
    const percentBtn = this.withTip('lightbox-zoom-percent', h_flex().id('lightbox-zoom-percent').min_w(48).h(26).px(7)
      .flex_none().rounded(7).items_center().justify_center().cursor_pointer()
      .bg(t.raised).border_1().border_color(withAlpha(t.border, .8))
      .font_family('monospace').text_size(11.5).text_color(t.foreground)
      .hover(s => s.bg(t.hover).border_color(withAlpha(t.accent, .5)))
      .accessibility_label(percentTip)
      .on_mouse_down('left', (_e, mCx) => mCx.stop_propagation?.())
      .on_click((_e, cCx) => { cCx.stop_propagation?.(); this.hoverKey = ''; this.cycleLightboxZoom(cCx); })
      .child(`${lay.percent}%`), percentTip, t, { placement: 'below-right' });

    const topBar = h_flex().id('image-lightbox-toolbar').h(LIGHTBOX_TOOLBAR_HEIGHT).w_full().flex_none()
      .px(14).gap(10).items_center().justify_between()
      .bg(t.chrome || t.surface).border_b(1).border_color(withAlpha(t.border, .85))
      .on_mouse_down('left', (_e, mCx) => { mCx.stop_propagation?.(); this.lightboxFocus?.focus?.(); })
      .on_click((_e, cCx) => cCx.stop_propagation?.())
      .child(h_flex().min_w(0).flex_1().gap(8).items_center()
        .child(this.icon('image', 14).flex_none().text_color(t.muted))
        .child(div().min_w(0).truncate().text_size(13).font_medium().text_color(t.foreground).child(lb.name))
        .when(lb.width > 0 && lb.height > 0, el => el.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim)
          .child(word(lang, 'imageDimensions', lb.width, lb.height))))
        .when(lb.size > 0, el => el.child(div().flex_none().text_size(11.5).text_color(t.dim).child(formatBytes(lb.size))))
        .when(Boolean(lb.error), el => el.child(div().min_w(0).truncate().text_size(11.5).text_color(t.blocked).child(lb.error))))
      .child(h_flex().id('image-lightbox-actions').flex_none().gap(4).items_center()
        .child(this.lightboxIconBtn('lightbox-zoom-out', 'minus', word(lang, 'imageZoomOut'),
          lay.canZoomOut ? cCx => this.stepLightboxZoomBy(-1, cCx) : null, t, { size: 13.5 }))
        .child(percentBtn)
        .child(this.lightboxIconBtn('lightbox-zoom-in', 'plus', word(lang, 'imageZoomIn'),
          lay.canZoomIn ? cCx => this.stepLightboxZoomBy(1, cCx) : null, t, { size: 13.5 }))
        .child(this.lightboxIconBtn(toggleId, toggleIcon, toggleTip,
          cCx => this.toggleLightboxFitActual(cCx), t, { size: 14, active: !lay.isFit }))
        .child(div().w(1).h(16).mx(3).flex_none().bg(t.border))
        .child(this.lightboxIconBtn('lightbox-open-external', 'external-open', word(lang, 'imageOpenExternal'),
          openPath ? cCx => this.openImageInSystem(lb, { rel: lb.rel }, cCx, { inLightbox: true }) : null, t, { size: 14 }))
        .child(this.lightboxIconBtn('lightbox-close', 'close', word(lang, 'imageCloseLightbox'),
          cCx => this.closeImageLightbox(cCx), t, { size: 14 })));

    const stage = v_flex().id('image-lightbox-viewport').relative().flex_1().min_h(0).min_w(0).w_full()
      .on_size_change((size, sCx) => {
        const w = Math.round(size?.width || 0);
        const h = Math.round(size?.height || 0);
        if (w <= 0 || h <= 0) return;
        const prev = this.lightboxViewport || { width: 0, height: 0 };
        if (Math.abs(w - prev.width) > 1 || Math.abs(h - prev.height) > 1) {
          this.lightboxViewport = { width: w, height: h };
          if (this.lightboxOverlayMode) this.viewWidth = w;
          this.notifyLightbox(sCx);
        }
      })
      .on_pinch((e, pCx) => {
        if (!this.imageLightbox || !e) return;
        const curLay = this.currentLightboxLayout();
        const next = applyLightboxPinch(this.imageLightbox, e.delta, curLay.fitScale);
        if (next !== this.imageLightbox) {
          this.imageLightbox = next;
          this.notifyLightbox(pCx);
        }
      });

    if (!lb.rel) {
      stage.items_center().justify_center()
        .on_click((_e, cCx) => { cCx.stop_propagation?.(); this.closeImageLightbox(cCx); })
        .child(h_flex().gap(8).items_center().px(14).py(10).rounded(10)
          .bg(t.surface).border_1().border_color(t.border).text_size(12.5).text_color(t.muted)
          .on_mouse_down('left', (_e, mCx) => mCx.stop_propagation?.())
          .on_click((_e, cCx) => cCx.stop_propagation?.())
          .child(div().child(lb.error === 'too large' ? word(lang, 'imageTooLarge') : word(lang, 'imageLoadFailed'))));
    } else {
      const frame = div().id('image-lightbox-frame').flex_none().w(lay.width).h(lay.height)
        .rounded(lay.scrollable ? 4 : 8).overflow_hidden()
        .bg(t.surface).border_1().border_color(withAlpha(t.border, .75)).shadow_md()
        .cursor_pointer()
        .on_mouse_down('left', (e, mCx) => {
          mCx.stop_propagation?.();
          this.lightboxFocus?.focus?.();
          if ((e?.click_count || 0) >= 2) this.toggleLightboxFitActual(mCx);
        })
        .on_click((_e, cCx) => cCx.stop_propagation?.())
        .child(image(lb.rel).w(lay.width).h(lay.height));

      const canvas = v_flex().id('image-lightbox-canvas').flex_none()
        .w(lay.canvasWidth).h(lay.canvasHeight)
        .pl(lay.padLeft).pt(lay.padTop)
        .child(frame);

      const scrollArea = div().id('image-lightbox-scroll').size_full().overflow_scroll()
        .when(Boolean(this.lightboxScroll), el => el.track_scroll(this.lightboxScroll))
        .on_click((_e, cCx) => { cCx.stop_propagation?.(); this.closeImageLightbox(cCx); })
        .child(canvas);

      stage.child(scrollArea)
        .when(Boolean(Scrollbar?.new), el => el.child(
          Scrollbar.new('image-lightbox-scroll').absolute().inset_0().mode(lay.scrollable ? 'always' : 'hover'),
        ));
    }

    const hintBar = h_flex().id('image-lightbox-hint').h(26).w_full().flex_none().px(14)
      .items_center().justify_center()
      .bg(t.chrome || t.surface).border_t(1).border_color(withAlpha(t.border, .65))
      .on_mouse_down('left', (_e, mCx) => mCx.stop_propagation?.())
      .on_click((_e, cCx) => cCx.stop_propagation?.())
      .child(div().truncate().text_size(11).text_color(t.dim).child(word(lang, 'imageLightboxHint')));

    const container = inProject
      ? v_flex().id('image-lightbox-backdrop').absolute().left(0).right(0).top(0).bottom(0)
      : v_flex().id('image-lightbox-backdrop').size_full().rounded(12).overflow_hidden()
          .border_1().border_color(withAlpha(t.border, .85)).shadow_lg();

    return container
      .bg(withAlpha(dark ? (t.canvas || '#0d0f12') : (t.background || '#f8f9fb'), dark ? .96 : .97))
      .text_size(13).text_color(t.foreground)
      .on_mouse_down('left', (_e, mCx) => mCx.stop_propagation?.())
      .on_hover((over, hCx) => {
        if (!over && this.hoverKey) {
          this.hoverKey = '';
          this.notifyLightbox(hCx);
        }
      })
      .when(Boolean(this.lightboxFocus), el => el.track_focus(this.lightboxFocus))
      .on_key_down((e, kCx) => this.handleLightboxKeyDown(e, kCx))
      .child(topBar)
      .child(stage)
      .child(hintBar);
  }

  // ---- Right Sidebar Multi-Tab Workspace Controller -------------------------
  sideTabsState() {
    return (this.tabState ||= createSideTabsState());
  }
  hasSideTabs() {
    return this.sideTabsState().tabs.length > 0;
  }
  activeSideTab() {
    const st = this.sideTabsState();
    return st.activeId ? (st.tabs.find(t => t.id === st.activeId) || null) : null;
  }
  openTabKeys() {
    const out = new Set();
    for (const t of this.sideTabsState().tabs) {
      if (t?.key) out.add(t.key);
    }
    return out;
  }
  ensureTabHandles(tabId, kind) {
    if (!tabId) return null;
    const map = (this.tabHandles ||= new Map());
    let h = map.get(tabId);
    if (!h) {
      h = kind === 'thread'
        ? { log: ScrollHandle.new(), session: ScrollHandle.new(), change: ScrollHandle.new() }
        : { doc: ScrollHandle.new(), history: ScrollHandle.new() };
      map.set(tabId, h);
    }
    return h;
  }
  tabScrollHandle(slot) {
    const tab = this.activeSideTab();
    const h = tab ? this.tabHandles?.get(tab.id) : null;
    if (h?.[slot]) return h[slot];
    if (slot === 'doc') return this.docScroll;
    if (slot === 'history') return this.historyScroll;
    if (slot === 'log') return this.threadScroll;
    if (slot === 'session') return this.sessionScroll;
    if (slot === 'change') return this.changeScroll;
    return null;
  }
  releaseTabHandles(tabId) {
    if (!tabId || !this.tabHandles) return;
    const h = this.tabHandles.get(tabId);
    if (h) {
      for (const sh of Object.values(h)) {
        try { sh?.release?.(); } catch (_) { /* ignore */ }
      }
      this.tabHandles.delete(tabId);
    }
  }
  releaseAllTabHandles() {
    if (!this.tabHandles) return;
    for (const h of this.tabHandles.values()) {
      for (const sh of Object.values(h)) {
        try { sh?.release?.(); } catch (_) { /* ignore */ }
      }
    }
    this.tabHandles.clear();
  }
  scrollTabIntoView(tabId) {
    const idx = this.sideTabsState().tabs.findIndex(t => t.id === tabId);
    if (idx >= 0) this.tabStripScroll?.scroll_to_item?.(idx);
  }
  persistSideTabs(pmName = this.pmName) {
    if (!pmName) return;
    try {
      const store = readSideTabsStore(localStorage.getItem(SIDE_TABS_KEY));
      const serialized = serializeProjectTabs(store, pmName, this.sideTabsState());
      localStorage.setItem(SIDE_TABS_KEY, serialized);
    } catch (_) { /* ignore storage errors */ }
  }
  hydrateSideTabs(pmName, cx) {
    this.releaseAllTabHandles();
    this.confirmCloseTabId = '';
    this.tabMenu = null;
    this.tabLimitBanner = '';
    this.hoveredTabId = '';
    if (!pmName) {
      this.tabState = createSideTabsState();
      return;
    }
    let hydrated = createSideTabsState();
    try {
      const store = readSideTabsStore(localStorage.getItem(SIDE_TABS_KEY));
      hydrated = hydrateProjectTabs(store, pmName);
    } catch (_) { hydrated = createSideTabsState(); }
    this.tabState = hydrated;
    for (const t of hydrated.tabs) this.ensureTabHandles(t.id, t.kind);
    const active = this.activeSideTab();
    if (active) {
      this.restoreActiveTabInputs(active, cx);
      this.scrollTabIntoView(active.id);
    }
  }
  reconcileMissingTabs(scope) {
    const st = this.sideTabsState();
    if (!st.tabs.length) return;
    const known = new Set(this.allKnownFiles().map(f => contextKey(f)));
    let changed = false;
    const nextTabs = st.tabs.map(t => {
      if (t.kind !== 'doc') return t;
      const inScope = scope === 'memory'
        ? (t.root === 'memory' || t.root === 'personal')
        : (t.root === 'docs' || t.root === 'repo_docs' || t.root === 'research' || t.root === 'instructions');
      if (!inScope) return t;
      const missing = !known.has(`${t.root}/${t.path}`);
      if (Boolean(t.missing) !== missing) {
        changed = true;
        return { ...t, missing };
      }
      return t;
    });
    if (changed) {
      this.tabState = { ...st, tabs: nextTabs };
      this.persistSideTabs();
    }
  }
  syncActiveTabFind() {
    const tab = this.activeSideTab();
    if (!tab || (tab.kind !== 'doc' && tab.kind !== 'draft')) return;
    this.tabState = updateSideTab(this.sideTabsState(), tab.id, {
      find: {
        open: Boolean(this.docFindOpen),
        query: this.docFindQuery || '',
        jumpQuery: this.docJumpQuery || '',
        matchPos: this.docMatchPos || 0,
      },
    }).state;
  }
  syncActiveTabDirty() {
    const tab = this.activeSideTab();
    if (!tab || (tab.kind !== 'doc' && tab.kind !== 'draft')) return;
    if (!this.editingDoc) return;
    const dirty = this.editorDirty();
    const draftSnap = {
      ...this.editingDoc,
      draftName: this.docNameInput?.value?.() ?? '',
      draftDesc: this.memDescInput?.value?.() ?? '',
      draftBody: this.docEditorInput?.value?.() ?? '',
    };
    this.editingDoc = draftSnap;
    this.tabState = updateSideTab(this.sideTabsState(), tab.id, {
      mode: 'edit',
      editDraft: draftSnap,
      dirty,
    }).state;
  }
  snapshotActiveTabInputs() {
    const tab = this.activeSideTab();
    if (!tab) return;
    if (tab.kind === 'thread') {
      this.tabState = updateSideTab(this.sideTabsState(), tab.id, {
        threadTab: this.threadTab || 'log',
        change: this.change || createChangeState(),
        logExpanded: Boolean(this.threadLogExpanded),
        cachedTask: this.threadTask,
        cachedLog: this.threadLog,
        cachedSession: this.threadSession,
        cachedSessionState: this.threadSessionState,
        cachedToolsOpen: this.sessionToolsOpen ? new Set(this.sessionToolsOpen) : new Set(),
        cachedBriefsOpen: this.sessionBriefsOpen ? new Set(this.sessionBriefsOpen) : new Set(),
      }).state;
      return;
    }
    const isEditing = Boolean(this.editingDoc);
    const isHistory = Boolean(this.historyView && this.historyView.scope === 'item');
    const editSnap = isEditing ? {
      ...this.editingDoc,
      draftName: this.docNameInput?.value?.() ?? '',
      draftDesc: this.memDescInput?.value?.() ?? '',
      draftBody: this.docEditorInput?.value?.() ?? '',
    } : null;
    if (editSnap) this.editingDoc = editSnap;
    const dirty = isEditing ? this.editorDirty() : false;
    this.tabState = updateSideTab(this.sideTabsState(), tab.id, {
      mode: isEditing ? 'edit' : isHistory ? 'history' : 'read',
      shownBytes: this.docShownBytes || DOC_INITIAL_BYTES,
      find: {
        open: Boolean(this.docFindOpen),
        query: this.docFindQuery || '',
        jumpQuery: this.docJumpQuery || '',
        matchPos: this.docMatchPos || 0,
      },
      editDraft: editSnap,
      history: isHistory ? this.historyView : null,
      dirty,
    }).state;
  }
  restoreActiveTabInputs(tab, cx) {
    this.confirmDeleteKey = '';
    this.deleteError = '';
    this.retopicOpen = false;
    this.retopicError = '';
    if (!tab) {
      this.detail = false;
      this.activeDoc = null;
      this.editingDoc = null;
      this.historyView = null;
      this.docError = '';
      this.docFindOpen = false;
      this.docFindQuery = '';
      this.docJumpQuery = '';
      this.docMatchPos = 0;
      this.docFindInput?.set_value?.('');
      return;
    }
    if (tab.kind === 'thread') {
      const changedThread = this.thread !== tab.taskId;
      this.detail = true;
      this.thread = tab.taskId;
      this.activeDoc = null;
      this.editingDoc = null;
      this.historyView = null;
      this.threadTab = tab.threadTab || 'log';
      this.change = tab.change || createChangeState();
      this.threadLogExpanded = Boolean(tab.logExpanded);
      if (changedThread) {
        this.threadTask = tab.cachedTask ?? null;
        this.threadError = '';
        this.threadLog = tab.cachedLog ?? null;
        this.threadLogKept = [];
        this.threadEarlierLoading = false;
        this.threadEarlierError = '';
        this.threadAnchor = null;
        if (tab.cachedSession && tab.cachedSession.taskId === tab.taskId) {
          this.threadSession = tab.cachedSession;
          this.threadSessionState = tab.cachedSessionState || 'ready';
          this.threadSessionTask = tab.taskId;
          this.sessionToolsOpen = tab.cachedToolsOpen ? new Set(tab.cachedToolsOpen) : new Set();
          this.sessionBriefsOpen = tab.cachedBriefsOpen ? new Set(tab.cachedBriefsOpen) : new Set();
        } else {
          this.resetThreadSession();
        }
        this.showThreadDraft(tab.taskId);
      }
      if (cx) {
        this.readThread(cx);
        if (this.threadTab === 'session') this.syncThreadSession(cx);
      }
      return;
    }
    this.detail = false;
    const docTab = tab.tab || (tab.root === 'memory' || tab.root === 'personal' ? 'memory' : 'library');
    this.sideTab = docTab;
    this.activeDoc = tab.kind === 'doc' ? { tab: docTab, root: tab.root, path: tab.path } : null;
    this.docShownBytes = tab.shownBytes || DOC_INITIAL_BYTES;
    this.docError = '';
    const f = tab.find || {};
    this.docFindOpen = Boolean(f.open);
    this.docFindQuery = f.query || '';
    this.docJumpQuery = f.jumpQuery || '';
    this.docMatchPos = f.matchPos || 0;
    this.docFindInput?.set_value?.(this.docFindQuery);
    if (tab.mode === 'edit' && tab.editDraft) {
      this.editingDoc = tab.editDraft;
      this.historyView = null;
      this.docNameInput?.set_value?.(tab.editDraft.draftName ?? tab.editDraft.originalName ?? '');
      this.memDescInput?.set_value?.(tab.editDraft.draftDesc ?? tab.editDraft.originalDesc ?? '');
      this.docEditorInput?.set_value?.(tab.editDraft.draftBody ?? tab.editDraft.originalText ?? '');
    } else if (tab.mode === 'history' && tab.history) {
      this.editingDoc = null;
      this.historyView = tab.history;
    } else {
      this.editingDoc = null;
      this.historyView = null;
      if (tab.kind === 'doc' && cx) this.readDoc(tab.root, tab.path, cx);
    }
  }
  activateTab(tabId, cx) {
    const st = this.sideTabsState();
    if (!tabId) return;
    if (st.activeId === tabId) {
      this.tabMenu = null;
      this.scrollTabIntoView(tabId);
      this.notifyPanes(cx, { shell: false, side: true });
      return;
    }
    this.snapshotActiveTabInputs();
    this.confirmCloseTabId = '';
    this.tabMenu = null;
    this.inlineFilterOpen = false;
    const res = activateSideTab(this.sideTabsState(), tabId);
    if (!res.activated) return;
    this.tabState = res.state;
    this.ensureTabHandles(res.tab.id, res.tab.kind);
    this.restoreActiveTabInputs(res.tab, cx);
    this.scrollTabIntoView(res.tab.id);
    this.persistSideTabs();
    this.notifyPanes(cx, { shell: false, side: true });
  }
  showIndexView(cx, { toggle = false } = {}) {
    this.snapshotActiveTabInputs();
    this.confirmCloseTabId = '';
    this.tabMenu = null;
    const res = toggle ? toggleSideIndex(this.sideTabsState()) : showSideIndex(this.sideTabsState());
    this.tabState = res.state;
    const active = this.activeSideTab();
    this.restoreActiveTabInputs(active, cx);
    if (active) this.scrollTabIntoView(active.id);
    else this.syncVisibleSideTab(cx);
    this.persistSideTabs();
    this.notifyPanes(cx, { shell: false, side: true });
  }
  cycleTab(delta, cx) {
    if (!this.hasSideTabs()) return;
    this.snapshotActiveTabInputs();
    this.confirmCloseTabId = '';
    this.tabMenu = null;
    const res = cycleSideTab(this.sideTabsState(), delta);
    if (!res.activated) return;
    this.tabState = res.state;
    this.ensureTabHandles(res.tab.id, res.tab.kind);
    this.restoreActiveTabInputs(res.tab, cx);
    this.scrollTabIntoView(res.tab.id);
    this.persistSideTabs();
    this.notifyPanes(cx, { shell: false, side: true });
  }
  closeTab(tabId, cx, { force = false } = {}) {
    if (!tabId) return;
    this.snapshotActiveTabInputs();
    const prevCount = this.sideTabsState().tabs.length;
    const res = closeSideTab(this.sideTabsState(), tabId, { force });
    if (res.needsConfirm) {
      this.tabState = res.state;
      this.confirmCloseTabId = tabId;
      this.tabMenu = null;
      this.restoreActiveTabInputs(this.activeSideTab(), cx);
      this.scrollTabIntoView(tabId);
      this.notifyPanes(cx, { shell: false, side: true });
      return;
    }
    this.confirmCloseTabId = '';
    this.tabMenu = null;
    this.tabLimitBanner = '';
    if (res.closed) this.releaseTabHandles(res.closed.id);
    this.tabState = res.state;
    this.persistSideTabs();
    if (this.tabState.tabs.length === 0) {
      if (this._panelOpenedFromClosed) {
        this.restoreActiveTabInputs(null, cx);
        this.closeSidePanel(cx);
        return;
      }
      this.restoreActiveTabInputs(null, cx);
      this.syncVisibleSideTab(cx);
      this.notifyPanes(cx, { shell: true, conv: true, side: true });
      return;
    }
    const nextActive = this.activeSideTab();
    this.restoreActiveTabInputs(nextActive, cx);
    if (nextActive) this.scrollTabIntoView(nextActive.id);
    const crossedMode = (prevCount > 0) !== (this.tabState.tabs.length > 0);
    this.notifyPanes(cx, crossedMode ? { shell: true, conv: true, side: true } : { shell: false, side: true });
  }
  closeOtherTabs(keepTabId, cx) {
    this.snapshotActiveTabInputs();
    this.tabMenu = null;
    this.tabLimitBanner = '';
    const res = closeOtherSideTabs(this.sideTabsState(), keepTabId);
    for (const c of res.closed) this.releaseTabHandles(c.id);
    this.tabState = res.state;
    if (res.skippedDirtyIds.length > 0) {
      const act = activateSideTab(this.tabState, res.skippedDirtyIds[0]);
      this.tabState = act.state;
      this.confirmCloseTabId = res.skippedDirtyIds[0];
    } else {
      this.confirmCloseTabId = '';
    }
    this.restoreActiveTabInputs(this.activeSideTab(), cx);
    if (this.tabState.activeId) this.scrollTabIntoView(this.tabState.activeId);
    this.persistSideTabs();
    this.notifyPanes(cx, { shell: false, side: true });
  }
  closeRightTabs(fromTabId, cx) {
    this.snapshotActiveTabInputs();
    this.tabMenu = null;
    this.tabLimitBanner = '';
    const res = closeRightSideTabs(this.sideTabsState(), fromTabId);
    for (const c of res.closed) this.releaseTabHandles(c.id);
    this.tabState = res.state;
    if (res.skippedDirtyIds.length > 0) {
      const act = activateSideTab(this.tabState, res.skippedDirtyIds[0]);
      this.tabState = act.state;
      this.confirmCloseTabId = res.skippedDirtyIds[0];
    } else {
      this.confirmCloseTabId = '';
    }
    this.restoreActiveTabInputs(this.activeSideTab(), cx);
    if (this.tabState.activeId) this.scrollTabIntoView(this.tabState.activeId);
    this.persistSideTabs();
    this.notifyPanes(cx, { shell: false, side: true });
  }
  closeAllTabs(cx) {
    this.snapshotActiveTabInputs();
    this.tabMenu = null;
    this.tabLimitBanner = '';
    const prevCount = this.sideTabsState().tabs.length;
    const res = closeAllSideTabs(this.sideTabsState());
    for (const c of res.closed) this.releaseTabHandles(c.id);
    this.tabState = res.state;
    if (res.skippedDirtyIds.length > 0) {
      const act = activateSideTab(this.tabState, res.skippedDirtyIds[0]);
      this.tabState = act.state;
      this.confirmCloseTabId = res.skippedDirtyIds[0];
    } else {
      this.confirmCloseTabId = '';
    }
    const nextActive = this.activeSideTab();
    this.restoreActiveTabInputs(nextActive, cx);
    if (nextActive) this.scrollTabIntoView(nextActive.id);
    else this.syncVisibleSideTab(cx);
    this.persistSideTabs();
    const crossedMode = (prevCount > 0) !== (this.tabState.tabs.length > 0);
    this.notifyPanes(cx, crossedMode ? { shell: true, conv: true, side: true } : { shell: false, side: true });
  }

  openDoc(target, cx, opts = {}) {
    if (!target?.root || !target?.path) return;
    this.panelClosing = false;
    const wasOpen = this.isPanelOpen();
    const prevTabCount = this.sideTabsState().tabs.length;
    if (!wasOpen) {
      this._panelOpenedFromClosed = true;
      this.listShown = true;
    } else if (!this.listResting()) {
      this.listShown = true;
    }
    const tab = target.tab || (target.root === 'memory' || target.root === 'personal' ? 'memory' : 'library');
    if (target.root === 'repo' && this.sideTab && this.sideTab !== 'library') {
      this._panelPrevTab = this.sideTab;
    }
    this.snapshotActiveTabInputs();
    this.tabMenu = null;
    this.confirmCloseTabId = '';
    const meta = this.findDocMeta(target.root, target.path);
    const title = meta ? libraryDocTitle(meta) : fileName(target.path);
    const res = openSideTab(this.sideTabsState(), {
      kind: 'doc',
      tab,
      root: target.root,
      path: target.path,
      title,
    }, { insertAdjacent: Boolean(opts?.insertAdjacent) });
    if (res.blocked) {
      this.tabLimitBanner = word(this.lang, 'sideTabLimitDirty');
      this.notifyPanes(cx, { shell: false, side: true });
      return;
    }
    this.tabLimitBanner = '';
    if (res.evicted) this.releaseTabHandles(res.evicted.id);
    this.tabState = res.state;
    this.ensureTabHandles(res.tab.id, 'doc');
    const q = String((opts?.jumpQuery !== undefined ? opts.jumpQuery : (tab === 'memory' ? this.memoryQuery : this.libraryQuery)) || '').trim();
    if (q) {
      this.tabState = updateSideTab(this.tabState, res.tab.id, t => ({
        find: { ...(t.find || {}), jumpQuery: q },
      })).state;
    }
    const active = this.activeSideTab();
    this.restoreActiveTabInputs(active, cx);
    this.docJumpQuery = q;
    this.docFindJump = Boolean(q);
    this.scrollTabIntoView(res.tab.id);
    this.persistSideTabs();
    if (isPreviewableImage(target.path)) {
      const imgTarget = resolveImageTarget(target, this.docLinkContext());
      if (imgTarget) this.loadImagePreview(imgTarget, cx);
    }
    const crossedMode = !wasOpen || prevTabCount === 0;
    this.notifyPanes(cx, crossedMode ? { shell: true, conv: true, side: true } : { shell: false, side: true });
  }

  closeActiveDoc(cx, { fromEscape = false } = {}) {
    const active = this.activeSideTab();
    if (active && (active.kind === 'doc' || active.kind === 'draft')) {
      if (fromEscape) {
        if (this._panelOpenedFromClosed && this.sideTabsState().tabs.length === 1) {
          if (this.typing === 'docFind') this.keyFocus?.focus();
          this.closeSidePanel(cx);
          return;
        }
        if (this.typing === 'docFind') this.keyFocus?.focus();
        this.showIndexView(cx);
        return;
      }
      this.showIndexView(cx);
      return;
    }
    if (fromEscape && this._panelOpenedFromClosed) {
      if (this.typing === 'docFind') this.keyFocus?.focus();
      this.closeSidePanel(cx);
      return;
    }
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
    if (wasRepo) {
      if (!this.librarySupported() && this.sideTab === 'library') this.sideTab = 'threads';
      else if (this._panelPrevTab && this._panelPrevTab !== 'library') this.sideTab = this._panelPrevTab;
    }
    if (!fromEscape) {
      this.listShown = true;
      this._panelOpenedFromClosed = false;
    }
    if (this.typing === 'docFind') this.keyFocus?.focus();
    this.notifyPanes(cx, { shell: true, conv: true, side: true });
  }

  selectSideTab(tab, cx) {
    if (tab === 'library' && !this.librarySupported()) return;
    if (tab === 'memory' && !this.memorySupported()) return;
    this.panelClosing = false;
    this.sideTab = tab;
    this._panelPrevTab = tab;
    this._panelOpenedFromClosed = false;
    if (this.hasSideTabs() && this.sideTabsState().activeId !== null) {
      this.snapshotActiveTabInputs();
      this.tabState = showSideIndex(this.sideTabsState()).state;
      this.restoreActiveTabInputs(null, cx);
      this.persistSideTabs();
    } else {
      this.detail = false;
      this.resetThreadChange();
    }
    this.confirmDeleteKey = '';
    this.retopicOpen = false;
    this.inlineFilterOpen = false;
    if (tab === 'library') {
      if (this.machine || !this.libraryRead || this.libraryStale) this.readLibrary(cx);
      else this.prefetchLibraryDocs(cx);
    } else if (tab === 'memory') {
      if (this.machine || !this.memoryRead || this.memoryStale) this.readMemory(cx);
    }
    this.notifyPanes(cx, { shell: true, conv: true, side: true });
  }

  followDocLink(url, cx) {
    const rel = resolveContextLink(this.activeDoc, url, this.allKnownFiles());
    if (rel?.root === 'repo') { this.openDoc({ tab: 'library', root: 'repo', path: rel.path }, cx, { insertAdjacent: true }); return; }
    if (rel) { this.openDoc(rel, cx, { insertAdjacent: true }); return; }
    this.followLink(url, cx);
  }

  async saveProjectText(slug, root, path, text, { ifVersion = null } = {}) {
    const byteLen = utf8ByteLength(text);
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
    this.inlineFilterOpen = false;
    this.historyView = null;
    this.deletedBanner = null;
    this.confirmCloseTabId = '';
    this.tabMenu = null;
    this.snapshotActiveTabInputs();
    const wasOpen = this.isPanelOpen();
    const prevTabCount = this.sideTabsState().tabs.length;
    if (!wasOpen) {
      this._panelOpenedFromClosed = true;
      this.listShown = true;
    }
    const isMem = tab === 'memory';
    const ed = isMem ? {
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
      draftName: '',
      draftDesc: '',
      draftBody: '',
      saving: false,
      error: '',
      conflict: null,
    } : {
      mode: 'create',
      tab: 'library',
      root: 'docs',
      path: '',
      version: '',
      originalName: '',
      originalText: '',
      draftName: '',
      draftBody: '',
      saving: false,
      error: '',
      conflict: null,
    };
    const res = openSideTab(this.sideTabsState(), {
      kind: 'draft',
      tab: isMem ? 'memory' : 'library',
      root: ed.root,
      title: word(this.lang, isMem ? 'newMemory' : 'newDoc'),
      editDraft: ed,
    });
    if (res.blocked) {
      this.tabLimitBanner = word(this.lang, 'sideTabLimitDirty');
      this.notifyPanes(cx, { shell: false, side: true });
      return;
    }
    this.tabLimitBanner = '';
    if (res.evicted) this.releaseTabHandles(res.evicted.id);
    this.tabState = res.state;
    this.ensureTabHandles(res.tab.id, 'draft');
    this.restoreActiveTabInputs(res.tab, cx);
    this.scrollTabIntoView(res.tab.id);
    cx.timer?.after(0, () => this.docNameInput?.focus());
    this.panelClosing = false;
    const crossedMode = !wasOpen || prevTabCount === 0;
    this.notifyPanes(cx, crossedMode ? { shell: true, conv: true, side: true } : { shell: false, side: true });
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
    this.inlineFilterOpen = false;
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
        draftDesc: desc,
        draftBody: body,
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
        draftBody: cached.text,
        saving: false,
        error: '',
        conflict: null,
      };
      this.docEditorInput?.set_value(cached.text);
      cx.timer?.after(0, () => this.docEditorInput?.focus());
    }
    const active = this.activeSideTab();
    if (active && active.kind === 'doc') {
      this.tabState = updateSideTab(this.sideTabsState(), active.id, {
        mode: 'edit',
        editDraft: this.editingDoc,
        dirty: false,
      }).state;
    }
    this.panelClosing = false;
    this.notifyPanes(cx, { shell: true, conv: true, side: true });
  }

  cancelEditDoc(cx) {
    const active = this.activeSideTab();
    if (active && active.kind === 'draft') {
      if (this.typing === 'docEditor' || this.typing === 'docName' || this.typing === 'memDesc') {
        this.keyFocus?.focus();
      }
      this.closeTab(active.id, cx, { force: !this.editorDirty() });
      return;
    }
    if (active && active.kind === 'doc') {
      this.tabState = updateSideTab(this.sideTabsState(), active.id, {
        mode: 'read',
        editDraft: null,
        dirty: false,
      }).state;
    }
    this.editingDoc = null;
    this.confirmCloseTabId = '';
    if (this.typing === 'docEditor' || this.typing === 'docName' || this.typing === 'memDesc') {
      this.keyFocus?.focus();
    }
    this.notifyPanes(cx, { shell: true, conv: true, side: true });
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

  async saveEditingDoc(cx, { overwrite = false, closeTabAfter = false } = {}) {
    const ed = this.editingDoc;
    const slug = projectSlug(this.pm());
    if (!ed || !slug || ed.saving) return;
    const activeTabAtStart = this.activeSideTab();
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
    const targetTabId = activeTabAtStart?.id || null;
    try {
      const r = await this.saveProjectText(slug, root, relPath, payloadText, { ifVersion });
      const conflict = parseVersionConflict(r);
      if (conflict) {
        ed.conflict = conflict;
        ed.saving = false;
        this.notifyPanes(cx, { shell: false, side: true });
        return;
      }
      if (r.code !== 0) {
        throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
      }
      const key = `${root}/${relPath}`;
      this.docCache.delete(key);
      this.docFailed.delete(key);
      ed.saving = false;
      const curState = this.sideTabsState();
      const prevActiveId = curState.activeId;
      const stillActive = Boolean(this.editingDoc === ed && (!targetTabId || prevActiveId === targetTabId));
      let savedTabId = targetTabId;
      if (targetTabId && curState.tabs.some(t => t.id === targetTabId)) {
        if (activeTabAtStart.kind === 'draft') {
          const up = upgradeDraftTab(curState, targetTabId, {
            root, path: relPath, tab: ed.tab, title: fileName(relPath),
          });
          if (up.removedDraftId) this.releaseTabHandles(up.removedDraftId);
          let nextState = up.state;
          if (!stillActive && prevActiveId !== targetTabId && (prevActiveId === null || nextState.tabs.some(t => t.id === prevActiveId))) {
            nextState = { ...nextState, activeId: prevActiveId };
          }
          this.tabState = nextState;
          if (up.tab) {
            savedTabId = up.tab.id;
            this.ensureTabHandles(up.tab.id, 'doc');
          }
        } else {
          this.tabState = updateSideTab(curState, targetTabId, {
            mode: 'read', dirty: false, editDraft: null,
          }).state;
        }
        this.persistSideTabs();
      }
      if (this.confirmCloseTabId && (this.confirmCloseTabId === targetTabId || this.confirmCloseTabId === savedTabId)) {
        this.confirmCloseTabId = '';
      }
      if (this.editingDoc === ed) {
        this.editingDoc = null;
        this.activeDoc = { tab: ed.tab, root, path: relPath };
        if (this.typing === 'docEditor' || this.typing === 'docName' || this.typing === 'memDesc') {
          this.keyFocus?.focus();
        }
      }
      if (ed.tab === 'memory') this.readMemory(cx);
      else this.readLibrary(cx);
      this.readDoc(root, relPath, cx, { force: true });
      if (closeTabAfter && savedTabId && this.sideTabsState().tabs.some(t => t.id === savedTabId)) {
        this.closeTab(savedTabId, cx, { force: true });
        return;
      }
    } catch (e) {
      ed.error = word(lang, 'saveFailed', String(e?.message || e).trim());
      ed.saving = false;
    }
    this.notifyPanes(cx, { shell: false, side: true });
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
      const deletedTab = this.sideTabsState().tabs.find(t => t.kind === 'doc' && t.root === docRef.root && t.path === docRef.path);
      if (deletedTab) {
        this.closeTab(deletedTab.id, cx, { force: true });
      } else {
        this.activeDoc = null;
      }
      if (docRef.tab === 'memory') this.readMemory(cx);
      else this.readLibrary(cx);
    } catch (e) {
      this.deleteError = word(this.lang, 'deleteFailed', String(e?.message || e).trim());
    } finally {
      this.deleteBusy = '';
      this.notifyPanes(cx, { shell: true, conv: true, side: true });
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
    this.inlineFilterOpen = false;
    const hv = { tab, scope, root, path, items: [], loading: true, error: '', restoring: '' };
    this.panelClosing = false;
    this.historyView = hv;
    const active = this.activeSideTab();
    if (scope === 'item' && active && active.kind === 'doc') {
      this.tabState = updateSideTab(this.sideTabsState(), active.id, { mode: 'history', history: hv }).state;
    }
    this.notifyPanes(cx, { shell: true, conv: true, side: true });
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
    this.notifyPanes(cx, { shell: false, side: true });
  }

  closeHistory(cx) {
    const active = this.activeSideTab();
    if (active && active.mode === 'history') {
      this.tabState = updateSideTab(this.sideTabsState(), active.id, { mode: 'read', history: null }).state;
    }
    this.historyView = null;
    this.notifyPanes(cx, { shell: true, conv: true, side: true });
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
    this.notifyPanes(cx, { shell: true, conv: true, side: true });
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
          if (text == null || text.includes('\0') || utf8ByteLength(text) > DOC_MAX_BYTES) {
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
  // Start a fresh PM session for the current offline project (`pm.py start --repo <repo>` or `--name <name>` for 0 folders).
  startPm(cx) {
    const pm = this.pm(), pmKey = this.pmName;
    const hasZeroFolders = Array.isArray(pm?.folders) && pm.folders.length === 0;
    if (!pm || (!pm.repo && !hasZeroFolders) || this.startingPm || this.bringingBack) return;
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
    const steps = bringBackSteps(this.lang, pm.lost, projectName(pm) || pm.name).map(s => ({ ...s, state: 'pending', error: '' }));
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
      const steps = bringBackSteps(this.lang, pm.lost, projectName(pm) || pm.name).map(s => ({ ...s, state: 'pending', error: '' }));
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

  // ---- the side panel's dual-mode width: its left edge drags -----------------
  keptPanelWidth() {
    try { return readPanelWidth(localStorage.getItem(PANEL_KEY)); } catch (_) { return null; }
  }
  keepPanelWidth(width) {
    try {
      if (width == null) localStorage.removeItem(PANEL_KEY);
      else localStorage.setItem(PANEL_KEY, String(width));
    } catch (_) { /* Nowhere to keep it: it holds until the view is built anew. */ }
  }
  keptPanelSizes() {
    try {
      return readPanelSizes(localStorage.getItem(PANEL_SIZES_KEY), localStorage.getItem(PANEL_KEY));
    } catch (_) {
      return { compactPx: null, splitRatio: null };
    }
  }
  keepPanelSizes(sizes) {
    try {
      if (!sizes || (sizes.compactPx == null && sizes.splitRatio == null)) {
        localStorage.removeItem(PANEL_SIZES_KEY);
      } else {
        localStorage.setItem(PANEL_SIZES_KEY, JSON.stringify({
          compactPx: sizes.compactPx ?? null,
          splitRatio: sizes.splitRatio ?? null,
        }));
      }
    } catch (_) { /* Nowhere to keep it: it holds until the view is built anew. */ }
  }
  currentPanelMode() {
    const onLib = this.sideTab === 'library' && (this.librarySupported() || this.activeDoc?.root === 'repo');
    const onMem = this.sideTab === 'memory' && this.memorySupported();
    const curTab = onLib ? 'library' : onMem ? 'memory' : '';
    const hasDoc = Boolean(curTab && this.activeDoc?.tab === curTab);
    const hasEdit = Boolean(curTab && this.editingDoc?.tab === curTab);
    const hasHistory = Boolean(curTab && this.historyView?.tab === curTab);
    return resolvePanelMode({
      tabCount: this.sideTabsState().tabs.length,
      detail: Boolean(this.detail),
      activeDoc: hasDoc,
      editingDoc: hasEdit,
      historyView: hasHistory,
      changeOpen: this.isThreadChangeOpen(),
    });
  }
  currentSplitLayout() {
    const mode = this.currentPanelMode();
    const base = resolveSplitLayout({
      mode,
      sizes: this.panelSizes || { compactPx: null, splitRatio: null },
      viewWidth: this.viewWidth || 0,
    });
    if (this.panelDrag && this.panelDragWidth != null && base.layoutKind === 'inline') {
      const cardWidth = this.panelDragWidth;
      const slotWidth = cardWidth + SPLIT_CARD_MARGIN_R + SPLIT_GRIP_OVERHANG;
      const v = this.viewWidth > 0 ? this.viewWidth : 1280;
      const leftWidth = Math.max(0, Math.round(v - slotWidth));
      const conversationPadX = leftWidth >= 760 ? 28 : leftWidth >= 520 ? 20 : 16;
      return { ...base, cardWidth, slotWidth, conversationPadX };
    }
    return base;
  }
  notifyShell(cx) {
    this._shellOnlyRender = true;
    const hostCx = this._shellCx || cx;
    try { hostCx?.notify?.(); } catch (_) { cx?.notify?.(); }
  }
  notifyPanes(cx, { shell = true, conv = false, side = false } = {}) {
    const hostCx = this._shellCx || cx;
    if (shell) {
      this._shellOnlyRender = true;
      try { hostCx?.notify?.(); } catch (_) { cx?.notify?.(); }
    }
    if (conv && this._convEntity) {
      try { (cx || hostCx)?.notify?.(this._convEntity); } catch (_) { hostCx?.notify?.(this._convEntity); }
    }
    if (side && this._sideEntity) {
      try { (cx || hostCx)?.notify?.(this._sideEntity); } catch (_) { hostCx?.notify?.(this._sideEntity); }
    }
    if (!shell && !this._convEntity && !this._sideEntity) {
      cx?.notify?.();
    }
  }
  isPanelOpen() {
    if (this.panelClosing) return false;
    if (this.hasSideTabs()) return Boolean(this.listResting());
    return Boolean(this.listResting() || this.detail);
  }
  _clearClosedSideState() {
    this.panelClosing = false;
    this.detail = false;
    this.resetThreadChange();
    this.activeDoc = null;
    this.editingDoc = null;
    this.historyView = null;
    this.docFindOpen = false;
    this.docFindQuery = '';
    this.docJumpQuery = '';
    this.docMatchPos = 0;
    this.confirmDeleteKey = '';
    this.deleteError = '';
    this.retopicOpen = false;
    this.retopicError = '';
    this._panelOpenedFromClosed = false;
  }
  _activeInnerLockWidth() {
    const open = this.isPanelOpen();
    const isSlideOpenClose = !open || this._panelSlideFromZero === true;
    if (isSlideOpenClose || this.panelTransitioning !== true || Boolean(this.panelDrag)) return 0;
    const lock = Number(this._panelLockWidth);
    return lock > 0 ? Math.max(200, Math.round(lock - 2)) : 0;
  }
  sideScrollBody(el) {
    const lockW = this._activeInnerLockWidth();
    if (!lockW) return el;
    return div().flex_1().min_h(0).w_full().overflow_hidden()
      .child(v_flex().w(lockW).h_full().flex_none().child(el));
  }
  closeSidePanel(cx) {
    this.listShown = false;
    this._panelOpenedFromClosed = false;
    this.tabMenu = null;
    this.clearHoverNow(null);
    if (['thread', 'threadsSearch', 'librarySearch', 'memorySearch', 'docFind', 'docEditor', 'docName', 'memDesc'].includes(this.typing)) {
      this.keyFocus?.focus();
    }
    if (this.hasSideTabs()) {
      // Multi-tab workspace: closing the panel hides it while preserving all open tabs & unsaved drafts.
      this.snapshotActiveTabInputs();
      this.persistSideTabs();
      if (this.measured && !this.panelDrag && cx?.timer?.after) {
        this.panelClosing = true;
      } else {
        this.panelClosing = false;
      }
      this.notifyPanes(cx, { shell: true, conv: true, side: true });
      return;
    }
    const hasSplitContent = Boolean(this.detail || this.activeDoc || this.editingDoc || this.historyView || this.isThreadChangeOpen());
    if (hasSplitContent && this.measured && !this.panelDrag && cx?.timer?.after) {
      // Keep current detail/doc mounted while the card slides out to 0px; clear after slide finishes.
      this.panelClosing = true;
    } else {
      this._clearClosedSideState();
    }
    this.notifyPanes(cx, { shell: true, conv: true, side: true });
  }
  // A press on the edge starts a drag; a double-click puts the default width for the current mode back.
  gripDown(e, cx) {
    cx?.stop_propagation?.();
    const mode = this.currentPanelMode();
    const lay = this.currentSplitLayout();
    if (e.click_count >= 2) {
      this.panelDrag = null;
      this.panelDragWidth = null;
      this.panelSizes = resetPanelModeSize(this.panelSizes, mode);
      this.keepPanelSizes(this.panelSizes);
      this.panelWant = null;
      this.notifyPanes(cx, { shell: true, side: true, conv: true });
      return;
    }
    this.panelDrag = { x: e.position.x, width: lay.cardWidth, mode, moved: false };
    this.panelDragWidth = lay.cardWidth;
    this.notifyShell(cx);
  }
  // The pointer anywhere over the view moves the edge while a drag is on.
  gripMove(e, cx) {
    if (!this.panelDrag) return;
    const v = this.viewWidth > 0 ? this.viewWidth : 1200;
    const maxByView = Math.max(PANEL_MIN, Math.round(v - 380));
    const isSplit = this.panelDrag.mode === 'split';
    const maxPx = isSplit ? Math.min(880, maxByView) : Math.min(500, maxByView);
    const minPx = isSplit ? Math.min(360, maxPx) : PANEL_MIN;
    const raw = this.panelDrag.width + this.panelDrag.x - e.position.x;
    const width = Math.round(Math.max(minPx, Math.min(raw, maxPx)));
    if (width !== this.panelDragWidth) {
      const prev = this.panelDragWidth ?? this.panelDrag.width;
      this.panelDragWidth = width;
      this.panelDrag.moved = true;
      this.panelWant = width;
      const crossedCompact = !isSplit && ((prev < 300) !== (width < 300));
      if (crossedCompact) this.notifyPanes(cx, { shell: true, side: true });
      else this.notifyShell(cx);
    }
  }
  // Released, or the pointer left the view (where a release would not be heard): the width stays.
  gripUp(cx) {
    if (!this.panelDrag) return;
    const drag = this.panelDrag;
    const finalW = this.panelDragWidth;
    this.panelDrag = null;
    this.panelDragWidth = null;
    if (drag.moved && finalW != null) {
      this.panelSizes = updatePanelSizes(this.panelSizes, drag.mode, finalW, this.viewWidth);
      this.keepPanelSizes(this.panelSizes);
    }
    this.notifyPanes(cx, { shell: true, side: true });
    if (!this.away) this.resized(cx);
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
    const folders = projectFolders(pm);
    const sig = foldersSignature(pm);
    if (slug !== this.repoFilesSlug || repo !== this.repoFilesRepo || sig !== this.repoFilesSig) {
      this.repoFilesSlug = slug;
      this.repoFilesRepo = repo;
      this.repoFilesSig = sig;
      this.repoFiles = [];
      this.repoFilesRead = false;
      this.repoFilesError = '';
      this.repoFilesTruncated = false;
      this.repoFilesAt = 0;
    }
    if (!pm || !slug) return;
    if (Array.isArray(pm.folders) && pm.folders.length === 0) {
      this.repoFiles = [];
      this.repoFilesTruncated = false;
      this.repoFilesRead = true;
      this.repoFilesError = '';
      this.repoFilesAt = Date.now();
      cx?.notify?.();
      return;
    }
    if (this.repoFilesLoading) { this.repoFilesAgain = true; return; }
    this.repoFilesLoading = true;
    cx.spawn(async cx => {
      try {
        let paths = [];
        let truncated = false;
        const singleLocalGit = !machine && folders.length === 1 && folders[0].git !== false && repo;
        if (singleLocalGit) {
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
          } else if (machine && isOldPmCommand(pr) && folders.length <= 1 && repo) {
            const r = await exec('git', ['-C', repo, 'ls-files', '-z'], { on: machine, timeout: 15000 });
            if (r.code !== 0) throw new Error((r.stderr || r.stdout || `git: ${r.code}`).trim().split('\n').pop());
            const parsed = parseGitLsFiles(r.stdout);
            truncated = parsed.length > REPO_FILES_LIMIT;
            paths = parsed.slice(0, REPO_FILES_LIMIT);
          } else {
            throw new Error((pr.stderr || pr.stdout || `pm.py: ${pr.code}`).trim().split('\n').pop());
          }
        }
        const curPm = this.pm();
        if (projectSlug(curPm) === slug && foldersSignature(curPm) === sig && machine === this.machine) {
          this.repoFiles = indexRepoFiles(paths, folders);
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

  resetMentionTasks() {
    this.mentionTasksTimer?.cancel?.();
    this.mentionTasksTimer = null;
    this.mentionTasksSeq = (this.mentionTasksSeq || 0) + 1;
    this.mentionTasksQuery = '';
    this.mentionTasksRows = [];
    this.mentionTasksLoading = false;
  }

  ensureMentionSources(cx) {
    if (!this.libraryRead && !this.libraryLoading && this.librarySupported()) {
      this.readLibrary(cx);
    }
    const staleFiles = !this.repoFilesRead || (this.repoFilesAt && Date.now() - this.repoFilesAt > 30_000);
    if (!this.repoFilesLoading && staleFiles) {
      this.readRepoFiles(cx);
    }
    const m = this.mention;
    const cat = m?.category || 'all';
    const q = String(m?.query || '').trim();
    if (!m || (cat !== 'all' && cat !== 'threads') || !q) {
      if (this.mentionTasksTimer || this.mentionTasksLoading || this.mentionTasksQuery || this.mentionTasksRows?.length) {
        this.resetMentionTasks();
      }
      return;
    }
    if (q === this.mentionTasksQuery) return;
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    if (!pm || !slug || !this.tasksQuerySupported()) {
      this.resetMentionTasks();
      return;
    }
    this.mentionTasksTimer?.cancel?.();
    this.mentionTasksTimer = null;
    const seq = ++this.mentionTasksSeq;
    this.mentionTasksQuery = q;
    this.mentionTasksLoading = true;
    const runQuery = runCx => {
      if (seq !== this.mentionTasksSeq || machine !== this.machine || slug !== projectSlug(this.pm())) return;
      const liveQ = String(this.mention?.query || '').trim();
      if (!this.mention || liveQ !== q) return;
      runCx.spawn(async spawnCx => {
        try {
          const r = await this.runProject(projectTasksArgv(slug, { status: 'all', q, offset: 0, limit: TASKS_PAGE_LIMIT }));
          if (seq !== this.mentionTasksSeq || machine !== this.machine || slug !== projectSlug(this.pm())) return;
          if (r.code !== 0) {
            if (machine && isOldPmCommand(r)) this.remoteNoTasks = machine;
            return;
          }
          const page = parseProjectTasksPage(JSON.parse(r.stdout || '{}'));
          if (!page) return;
          this.mentionTasksRows = page.tasks.map(t => normalizeProjectTaskRow(t)).filter(Boolean);
        } catch (_) {
          // Keep local matches quietly on error.
        } finally {
          if (seq === this.mentionTasksSeq && machine === this.machine) {
            this.mentionTasksLoading = false;
            this.notifyPanes(spawnCx, { shell: false, conv: true, side: this.mention?.which === 'thread' });
          }
        }
      });
    };
    if (typeof cx?.timer?.after === 'function') {
      this.mentionTasksTimer = cx.timer.after(150, timerCx => {
        this.mentionTasksTimer = null;
        runQuery(timerCx);
      });
    } else {
      runQuery(cx);
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
      if (had) { this.mention = null; this.resetMentionTasks(); }
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
      if (had) { this.mention = null; this.resetMentionTasks(); }
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
    const allTasks = this.tasks || this.state.tasks || [];
    const projectTasks = pm ? allTasks.filter(t => (t.pm || '') === (pm.name || '')) : [];
    const threads = pm ? threadList(pm, allTasks, this.events, this.terms(), this.live(), spaces().flatMap(s => s.tabs || []), this.lang) : { open: [], sessions: [], finished: [] };
    const menu = buildMentionMenu({
      lang: this.lang,
      category: this.mention.category,
      query: this.mention.query,
      threads,
      tasks: projectTasks,
      extraThreads: [...(this.finishedExtra || []), ...(this.mentionTasksRows || [])],
      threadsLoading: Boolean(this.mentionTasksLoading),
      taskNumbers: this.state.task_numbers,
      libraryFiles: this.libraryFiles,
      repoFiles: this.repoFiles,
      folders: projectFolders(pm),
      foldersEmpty: Boolean(Array.isArray(pm?.folders) && pm.folders.length === 0),
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
      this.resetMentionTasks();
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
    this.resetMentionTasks();
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

  docLinkContext() {
    const pm = this.pm();
    return {
      repo: pm?.repo || '',
      folders: projectFolders(pm),
      ledgerHome: this.machine ? this.remoteHome : this.ledgerHome,
      slug: projectSlug(pm),
      conversation: pm?.conversation || '',
    };
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
          ref = parseRefLink(targetOrToken.id, this.docLinkContext());
        }
      }
    } else if (typeof targetOrToken === 'string') {
      ref = parseRefLink(targetOrToken, this.docLinkContext());
    }
    if (!ref) return false;
    if (ref.kind === 'thread') {
      const id = resolveThreadRef(this.projectTasks(), ref.target, this.state.task_numbers, {
        retiredParts: this.state.retired_parts, events: this.events,
      });
      if (id && !(this.detail && this.thread === id)) this.openThread(id, cx);
      else if (id && !this.listResting()) {
        this.panelClosing = false;
        this.listShown = true;
        this.notifyPanes(cx, { shell: true, conv: true, side: true });
      }
      return true;
    }
    if (ref.kind === 'session') {
      this.focusTerminal(ref.target);
      return true;
    }
    if (ref.kind === 'library') {
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

  // The user's words into the terminal `address` (as the project's machine names it): `pm.py send
  // --as-user` where the project lives, which queues them for that terminal's one typist and comes
  // back at once (an error when the terminal is not running). A long text goes by a staged file.
  // Nothing here types into a terminal itself.
  // `wait`: typed before pm.py answers, so a failure comes back here as an error (the agent window
  // with no thread: there is nowhere else it would show). A pm.py on the project's machine older than
  // `--as-user` is asked again without it rather than leaving the box unable to send.
  async send(address, text, { task = '', wait = false } = {}) {
    const timeout = wait ? (2 * SEND_WAIT_SECONDS + 30) * 1000 : 45000;  // the lease wait, then the hc send
    const go = async what => {
      const r = await this.runProjectWrite(terminalSendArgv(address, { ...what, task, wait }), { timeout });
      return rejectsOption(r, '--as-user')
        ? this.runProjectWrite(terminalSendArgv(address, { ...what, task, wait, asUser: false }), { timeout })
        : r;
    };
    const r = utf8ByteLength(text) > SAVE_INLINE_BYTES
      ? await this.withStagedText(text, tmp => go({ fromFile: tmp }), 'pm.py send')
      : await go({ text });
    if (r.code !== 0) throw new Error((r.stderr || r.stdout).trim() || `pm.py send: ${r.code}`);
  }
  // `run(path)` with `text` in a temporary file pm.py can read where it runs: under the ledger home
  // here, or a mktemp file written in chunks on the project's machine; removed afterwards.
  async withStagedText(text, run, what = 'pm.py project send') {
    if (!this.machine && this.ledgerHome) {
      const tmp = `${this.ledgerHome}/.pm-send-${Date.now()}-${Math.random().toString(36).slice(2, 8)}.tmp`;
      await writeTextFile(tmp, text, null);
      try {
        return await run(tmp);
      } finally {
        await exec('rm', ['-f', '--', tmp], { timeout: 10000 }).catch(() => {});
      }
    }
    const on = this.where();
    const mk = await exec(...REMOTE_MKTEMP_ARGV, { ...on, timeout: 15000 });
    const tmp = String(mk.stdout || '').trim();
    if (mk.code !== 0 || !tmp) {
      throw new Error(mk.stderr || `mktemp failed for large ${what}`);
    }
    try {
      for (const chunk of chunkUtf8Text(text, REMOTE_CHUNK_BYTES)) {
        const w = await exec(...remoteAppendChunkArgv(tmp, chunk), { ...on, timeout: 15000 });
        if (w.code !== 0) throw new Error((w.stderr || w.stdout || 'chunk write failed').trim());
      }
      return await run(tmp);
    } finally {
      await exec('rm', ['-f', '--', tmp], { ...on, timeout: 10000 }).catch(() => {});
    }
  }
  // `words` and `files` to the terminal `address` (as the project's machine sees it). On another
  // machine each file is first copied beside that terminal (uploadSteps) and the message names where
  // it landed there; a file that did not go stops the send with an error that names it (`upload` set).
  // Resolves with the message that went.
  // A file whose name hc put would garble goes as a renamed copy (uploadName), made in a folder of
  // this send's own beside the pasted screenshots and removed once the copies went or failed. A file
  // already copied there by an earlier try of the same send (this.uploaded) is not copied again.
  async deliver(address, words, files, { task = '' } = {}) {
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
    await this.send(address, message, { task });
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
    const effSlug = slug || projectSlug(this.pm());
    const effMsgId = msgId || makeClientMsgId(this.nowMs(), (this.seq = (this.seq || 0) + 1));
    const peerKey = this.machine || '__local__';
    // `runProjectWrite` runs `pm.py` on `this.machine`, where the terminal's own address is `address` (no `<machine>/` prefix).
    const target = String(address || '');
    let sendReply = null;
    if (!effSlug || this.noProjectSendFor === peerKey) {
      await this.send(address, message);
    } else {
      const byteLen = utf8ByteLength(message);
      const r = byteLen > SAVE_INLINE_BYTES
        ? await this.withStagedText(message, tmp => this.runProjectWrite(
          projectSendArgv(effSlug, { msgId: effMsgId, target, fromFile: tmp, question }),
          { timeout: 45000 },
        ))
        : await this.runProjectWrite(
          projectSendArgv(effSlug, { msgId: effMsgId, target, text: message, question }),
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
      }
    }
    for (const step of steps) uploaded.delete(step.key);
    return { message, reply: sendReply };
  }
  activePmTurn() {
    const pm = this.pm();
    return this.logTurn || (pm?.turn && typeof pm.turn === 'object' ? pm.turn : null);
  }
  // The §3.9 line for a logged message's mailbox state, worded for the PM's agent and whether it works now.
  deliveryLine(delivery) {
    const pm = this.pm();
    const term = this.pmTerminal();
    const pmWorking = term ? this.isPmWorking(term, this.live(), this.activePmTurn()) : false;
    return deliveryLineView(this.lang, delivery, { pmWorking, agentKind: pm?.agent || '' });
  }
  activePmTurn2() {
    const pm = this.pm();
    return this.logTurn2 || (pm?.turn2 && typeof pm.turn2 === 'object' ? pm.turn2 : null);
  }
  activePmSupervised() {
    if (typeof this.logSupervised === 'boolean') return this.logSupervised;
    const pm = this.pm();
    if (typeof pm?.supervised === 'boolean') return pm.supervised;
    const t2 = this.activePmTurn2();
    return typeof t2?.supervised === 'boolean' ? t2.supervised : undefined;
  }
  setPmActionFeedback(pmKey, action, res, cx) {
    const rawFb = typeof formatPmActionFeedback === 'function'
      ? formatPmActionFeedback(this.lang, action, res)
      : null;
    const text = rawFb && typeof rawFb.text === 'string' ? rawFb.text : '';
    const tone = rawFb && typeof rawFb.tone === 'string' ? rawFb.tone : 'info';
    if (!text) return;
    const stamp = this.nowMs();
    this.pmActionFeedback = { pm: pmKey, action, text, tone, at: stamp };
    const ttlMs = tone === 'info' ? 12000 : 20000;
    if (cx?.timer?.after) {
      cx.timer.after(ttlMs, liveCx => {
        if (this.pmActionFeedback?.at === stamp && this.pmActionFeedback?.pm === pmKey) {
          this.pmActionFeedback = null;
          this.notifyPanes(liveCx, { shell: false, conv: true });
        }
      });
    }
  }
  interruptPm(cx, { sendDraftAfter = false } = {}) {
    const pm = this.pm(), slug = projectSlug(pm), pmKey = this.pmName;
    if (!pm || !slug || this.interruptingPm === pmKey) return;
    this.interruptingPm = pmKey;
    if (this.pmActionFeedback?.pm === pmKey) this.pmActionFeedback = null;
    this.notifySafe(cx);
    cx.spawn(async cx => {
      try {
        const r = await this.runProjectWrite(projectInterruptArgv(slug), { timeout: 15000 });
        this.setPmActionFeedback(pmKey, 'interrupt', r || {}, cx);
        if (sendDraftAfter && this.pmName === pmKey) {
          const hasDraft = Boolean(this.input?.value?.().trim() || this.files?.length || this.quotes?.length);
          if (hasDraft) this.sendMain(cx);
        }
      } catch (e) {
        this.setPmActionFeedback(pmKey, 'interrupt', { error: String(e?.message || e || 'interrupt failed') }, cx);
      }
      finally {
        if (this.interruptingPm === pmKey) this.interruptingPm = '';
        this.refresh(cx);
        this.notifySafe(cx);
      }
    });
  }
  preemptAndSendMain(cx) {
    this.interruptPm(cx, { sendDraftAfter: true });
  }
  rotatePmFromStall(cx) {
    const pm = this.pm(), repo = pm?.repo || '', pmKey = this.pmName;
    if (!pm || !repo || this.rotatingPm === pmKey) return;
    this.rotatingPm = pmKey;
    if (this.pmActionFeedback?.pm === pmKey) this.pmActionFeedback = null;
    this.notifySafe(cx);
    cx.spawn(async cx => {
      try {
        const reason = this.lang === 'zh' ? '从无响应轮次恢复' : 'Recover from unresponsive turn';
        const r = await this.runProjectWrite(rotatePmArgs(repo, reason), { timeout: 30000 });
        this.setPmActionFeedback(pmKey, 'rotate', r || {}, cx);
      } catch (e) {
        this.setPmActionFeedback(pmKey, 'rotate', { error: String(e?.message || e || 'rotate failed') }, cx);
      }
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
    if (cx?.phase?.() === 'render') return;
    if (this._convEntity || this._sideEntity) {
      this.notifyPanes(cx, { shell: false, conv: true, side: true });
    } else if (cx?.notify) {
      cx.notify();
    }
  }
  isPmStarting() {
    return this.startingPm === this.pmName || Boolean(
      this.bringingBack &&
      this.bringBackProgress?.pmKey === this.pmName &&
      this.bringBackProgress.steps?.some(s => s.kind === 'pm' && s.state === 'running'),
    );
  }
  // Recent PM user-message receipts: `turn2.inbox` (`consumed`/`answered`) plus 1-version compat `receipts`.
  pmReceipts() {
    const fromInbox = receiptsFromTurn2Inbox(this.activePmTurn2());
    const fromLog = Array.isArray(this.logReceipts) ? this.logReceipts : [];
    const fromState = Array.isArray(this.pm()?.receipts) ? this.pm().receipts : [];
    return mergeReceipts(fromInbox, mergeReceipts(fromState, fromLog));
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
      turn2: this.activePmTurn2(),
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
      const hasServerQueued = this.pending.some(p => p.queued && !p.failed && p.serverQueued);
      if (hasServerQueued && !this.logLoading) this.readLog(cx);
      this.reconcilePending(cx, { forceLogReady: !this.logLoading && !this.logError });
      const pmTerm = this.pmTerminal();
      const status = pmLiveStatus(pmTerm, this.live());
      if (pmTerm && pmCanReceive(status) && this.pending.some(p => p.queued && !p.failed && !p.serverQueued)) {
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
    const nextIdx = this.pending.findIndex(p => p.queued && !p.failed && !p.serverQueued);
    if (nextIdx < 0) {
      if (this.pending.some(p => p.queued && !p.failed && p.serverQueued)) this.scheduleQueueFlush(cx);
      return;
    }
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
      let serverQueuedReply = false;
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
        const isServerAccepted = Boolean(serverReply?.ok && serverReply.status === 'accepted');
        const isServerQueued = Boolean(
          serverReply?.ok && (serverReply.status === 'queued' || (isServerAccepted && String(serverReply.reason || '').trim())),
        );
        const serverLogged = Boolean(
          serverReply?.ok && (serverReply.status === 'delivered' || isServerAccepted) && Number(serverReply.offset) > 0,
        );
        if (isServerQueued) {
          serverQueuedReply = true;
          requeued = true;
          const reason = String(serverReply.reason || '');
          const updated = cur.map(p => p.id === bubble.id ? (p.received ? p : {
            ...p,
            queued: true,
            serverQueued: true,
            requeuedFromSend: true,
            queuedReason: reason,
            inFlight: false,
            inFlightAt: 0,
            inFlightTo: '',
            inFlightSession: '',
            failed: '',
            failedAt: 0,
            lastError: '',
          }) : p);
          byPm.set(pmName, updated);
          this.saveQueue(pmName, updated);
          if (this.pmName === pmName) {
            this.pending = updated;
            // MSG-5: Accepted by backend outbox — keep draft cleared (do not restore) and show queued reason.
            this.landed(bubble.draftKey, { text: bubble.words, files: bubble.files, quotes: bubble.quotes || [] }, true);
          }
        } else {
          const cleared = cur.map(p => p.id === bubble.id ? (p.received ? p : (serverLogged
            ? confirmReceiptBubble(p, Number(serverReply.at_ms) || now, now)
            : {
              ...p,
              queued: false,
              serverQueued: false,
              queuedReason: '',
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
          // PM receipt already confirmed this message before `pm.py project send` finished/errored: never requeue or fail.
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
          if (serverQueuedReply) {
            this.scheduleQueueFlush(cx);
          } else if (targetChanged) {
            this.flushQueue(cx);
          } else {
            if (this.pmTerminal()) this.probePmDialog(cx, true);
            this.scheduleQueueFlush(cx);
          }
        } else {
          this.readLog(cx);
          cx.timer?.after?.(600, liveCx => { if (this.pmName === pmName) this.readLog(liveCx); });
          this.scheduleConfirmCheck(cx);
          if (this.pending.some(p => p.queued && !p.failed && !p.serverQueued)) this.flushQueue(cx);
        }
      } else if (this.pending.some(p => p.queued && !p.failed && !p.serverQueued)) {
        this.flushQueue(cx);
      }
    });
  }
  // The bubble shows at once; the same line in the log replaces it.
  // `question` tags a quick answer so its options stay disabled while it is in flight.
  // files: the box's attachments, sent as the message's last lines (see messageText).
  // to: the title of the question the box's words answer (see answering): they go out after its 【title】.
  // quotes: quoted message excerpts attached above the box; serialized with provenance for the PM.
  say(text, cx, question, files = [], to = '', quotes = [], opts = {}) {
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
    const mustQueue = !terminal || !pmCanReceive(status) || this.flushingQueue || this.pending.some(p => p.queued && !p.failed && !p.serverQueued);
    const id = ++this.seq;
    const reusedMsgId = typeof opts?.msgId === 'string' && opts.msgId.trim() ? opts.msgId.trim() : '';
    const rawMsgId = reusedMsgId || makeClientMsgId(now, id);
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
      if (this.mention?.which === 'main') { this.mention = null; this.resetMentionTasks(); }
      if (this.mentionDismissed?.which === 'main') this.mentionDismissed = null;
      this.notifySafe(cx);
    }
  }
  // The "own words" row of a question card: the project's box answers that card, and takes the keyboard.
  answerInOwnWords(item, cx) {
    this.answering = { key: item.key, title: item.title, task: item.task || '', ...(taskNumber(item) ? { number: taskNumber(item) } : {}) };
    this.input.focus();
    this.notifyPanes(cx, { shell: false, conv: true, side: true });
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
    if (!this.say(bubble.words ?? bubble.text, cx, bubble.question, bubble.files, bubble.to, bubble.quotes || [], { msgId: bubble.msgId || '' })) {
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
    if (this.mention?.which === 'thread') { this.mention = null; this.resetMentionTasks(); }
    if (this.mentionDismissed?.which === 'thread') this.mentionDismissed = null;
    cx.spawn(async cx => {
      try {
        await this.deliver(terminal.address, text, files, { task: targetThread || '' });
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
    const raw = String(rawMd ?? '');
    if (!raw) return '';
    const src = raw.includes('![') ? rewriteMarkdownImagesForDisplay(raw, this.docLinkContext()) : raw;
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
    // The mailbox rows (turn2.inbox): where each logged message is, for the line under it (§3.9).
    const inbox = this.activePmTurn2()?.inbox;
    const inboxSig = inboxSignature(inbox);
    const c = this._timelineCache;
    if (c
      && c.pmName === pmName && c.pmPane === pmPane && c.pmCountsWaiting === pmCountsWaiting && c.today === today && c.typing === typing
      && c.clockOffsetMs === clockOffsetMs
      && c.events === events && c.eventsLen === evLen && c.eventsFirst === evFirst && c.eventsLast === evLast
      && c.eventsLastText === evLastText && c.eventsLastStatus === evLastStatus
      && c.tasks === tasks && c.tasksLen === tLen && c.tasksFirst === tFirst && c.tasksLast === tLast
      && c.taskNumbers === taskNumbers
      && c.pendingSig === pendingSig && c.inboxSig === inboxSig
      && c.pastes === pastes && c.pastesLen === paLen && c.pastesLast === paLast) {
      return c;
    }
    const items = timeline(events, tasks, {
      pending, today, typing, pastes, pm: pmName, pmPane, taskNumbers, clockOffsetMs, inbox,
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
      pendingSig, inboxSig,
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
  openThread(id, cx, { forceOpen = false, insertAdjacent = false } = {}) {
    // A review thread is shown in the task it reviews (foldReviews), and `#42` resolves in project scope.
    id = resolveThreadRef(this.projectTasks(), id, this.state.task_numbers, {
      retiredParts: this.state.retired_parts, events: this.events,
    });
    if (!id) return;
    this.clearHoverNow(cx);
    this.panelClosing = false;
    const wasOpen = this.isPanelOpen();
    const prevTabCount = this.sideTabsState().tabs.length;
    if (!wasOpen) {
      this._panelOpenedFromClosed = true;
      this.listShown = true;
    } else if (!this.listResting()) {
      this.listShown = true;
    }
    this.snapshotActiveTabInputs();
    this.tabMenu = null;
    this.confirmCloseTabId = '';
    const allTasks = this.tasks || this.state.tasks || [];
    const foundTask = allTasks.find(x => x.id === id)
      || (this.finishedExtra || []).find(r => r.task === id)
      || (this.threadsSearchRows || []).find(r => r.task === id);
    const title = foundTask?.title || id;
    const res = openSideTab(this.sideTabsState(), {
      kind: 'thread',
      taskId: id,
      title,
    }, { insertAdjacent: Boolean(insertAdjacent) });
    if (res.blocked) {
      this.tabLimitBanner = word(this.lang, 'sideTabLimitDirty');
      this.notifyPanes(cx, { shell: false, side: true });
      return;
    }
    this.tabLimitBanner = '';
    if (res.evicted) this.releaseTabHandles(res.evicted.id);
    this.tabState = res.state;
    this.ensureTabHandles(res.tab.id, 'thread');
    this.restoreActiveTabInputs(this.activeSideTab(), cx);
    this.scrollTabIntoView(res.tab.id);
    this.persistSideTabs();
    const crossedMode = !wasOpen || prevTabCount === 0;
    this.notifyPanes(cx, crossedMode ? { shell: true, conv: true, side: true } : { shell: false, side: true });
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
    const currentlyOpen = this.isPanelOpen();
    if (currentlyOpen) {
      this.closeSidePanel(cx);
      return;
    }
    this.panelClosing = false;
    this.listShown = true;
    this._panelOpenedFromClosed = false;
    if (this.hasSideTabs()) {
      const active = this.activeSideTab();
      if (active) this.restoreActiveTabInputs(active, cx);
      else this.syncVisibleSideTab(cx);
    } else {
      this.detail = false;
      this.resetThreadChange();
      this.syncVisibleSideTab(cx);
    }
    this.notifyPanes(cx, { shell: true, conv: true, side: true });
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
    this.resetMentionTasks();
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
    this.notifyPanes(cx, { shell: true, conv: true, side: false });
  }

  closeProjectSearch(cx, { restoreFocus = true } = {}) {
    if (!this.searchOpen) return;
    this.searchOpen = false;
    if (restoreFocus || this.typing === 'projectSearch') this.keyFocus?.focus?.();
    this.notifyPanes(cx, { shell: true, conv: true, side: false });
  }

  toggleProjectSearch(cx) {
    if (this.searchOpen) this.closeProjectSearch(cx);
    else this.openProjectSearch(cx);
  }

  handleModCommand(command, cx) {
    if (command === 'search') return this.handleSearchCommand(cx);
    return false;
  }

  handleSearchCommand(cx) {
    if (findStage(layout())?.active !== 'pm-project') return false;
    if (this.imageLightbox) return false;
    if (!this.pm()) return false;
    this.toggleProjectSearch(cx);
    return true;
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
      this.openDoc({ tab: 'memory', root: hit.root, path: hit.path }, cx, { jumpQuery: q });
      return;
    }
    if (hit.kind === 'library') {
      this.openDoc({ tab: 'library', root: hit.root, path: hit.path }, cx, { jumpQuery: q });
    }
  }

  handleKeyDown(e, cx) {
    if (this.imageLightbox && this.handleLightboxKeyDown(e, cx)) return;
    const ks = e?.keystroke || '';
    if (ks === 'cmd-k' || ks === 'ctrl-k') {
      cx.stop_propagation?.();
      this.toggleProjectSearch(cx);
      return;
    }
    if (this.isPanelOpen() && this.hasSideTabs()) {
      if (ks === 'cmd-shift-]' || ks === 'ctrl-shift-]') {
        cx.stop_propagation?.();
        this.cycleTab(1, cx);
        return;
      }
      if (ks === 'cmd-shift-[' || ks === 'ctrl-shift-[') {
        cx.stop_propagation?.();
        this.cycleTab(-1, cx);
        return;
      }
      if (ks === 'cmd-shift-w' || ks === 'ctrl-shift-w') {
        const activeId = this.sideTabsState().activeId;
        if (activeId) {
          cx.stop_propagation?.();
          this.closeTab(activeId, cx);
          return;
        }
      }
    }
    if (ks === 'cmd-f' || ks === 'ctrl-f') {
      const activeTab = this.activeSideTab();
      const onLib = this.libraryVisible() || (this.activeDoc?.root === 'repo' && this.sideTab === 'library' && this.listResting() && !this.detail);
      const onMem = this.memoryVisible();
      const onSide = onLib || onMem;
      const curTab = onLib ? 'library' : onMem ? 'memory' : '';
      const hasDoc = ((activeTab?.kind === 'doc' && this.isPanelOpen()) || (onSide && this.activeDoc?.tab === curTab))
        && !this.editingDoc && !this.historyView && !['main', 'thread'].includes(this.typing);
      if (hasDoc && !this.searchOpen) {
        cx.stop_propagation?.();
        this.docFindOpen = true;
        if (!this.docFindQuery && this.docJumpQuery) {
          this.docFindQuery = this.docJumpQuery;
          this.docFindInput?.set_value(this.docJumpQuery);
        }
        this.docMatchPos = 0;
        this.docFindJump = Boolean(this.docFindQuery?.trim?.());
        this.syncActiveTabFind();
        cx.timer?.after?.(0, () => this.docFindInput?.focus?.());
        this.notifyPanes(cx, { shell: false, side: true });
        return;
      }
      cx.stop_propagation?.();
      this.openProjectSearch(cx);
      return;
    }
    if (ks === '/' && !this.typing && !this.searchOpen && !this.mention && this.isPanelOpen() && !this.activeSideTab() && !this.detail && !this.activeDoc && !this.editingDoc && !this.historyView) {
      cx.stop_propagation?.();
      this.openInlineFilter(cx);
      return;
    }
    this.escape(e, cx);
  }

  activeIndexTabKey() {
    if (this.sideTab === 'library' && this.librarySupported()) return 'library';
    if (this.sideTab === 'memory' && this.memorySupported()) return 'memory';
    return 'threads';
  }

  isInlineFilterVisible(tabKey) {
    if (tabKey === 'library') return Boolean((this.inlineFilterOpen && this.activeIndexTabKey() === 'library') || String(this.libraryQuery || '').trim());
    if (tabKey === 'memory') return Boolean((this.inlineFilterOpen && this.activeIndexTabKey() === 'memory') || String(this.memoryQuery || '').trim());
    return Boolean((this.inlineFilterOpen && this.activeIndexTabKey() === 'threads') || String(this.threadsQuery || '').trim());
  }

  openInlineFilter(cx) {
    this.inlineFilterOpen = true;
    const key = this.activeIndexTabKey();
    const input = key === 'library' ? this.libraryInput : key === 'memory' ? this.memoryInput : this.threadsInput;
    cx?.timer?.after?.(0, () => input?.focus?.());
    this.notifyPanes(cx, { shell: false, side: true });
  }

  closeInlineFilter(cx, { clear = true } = {}) {
    this.inlineFilterOpen = false;
    if (clear) {
      const key = this.activeIndexTabKey();
      if (key === 'library') {
        this.libraryQuery = '';
        this.libraryInput?.set_value?.('');
      } else if (key === 'memory') {
        this.memoryQuery = '';
        this.memoryInput?.set_value?.('');
      } else {
        this.threadsQuery = '';
        this.threadsInput?.set_value?.('');
        this.scheduleThreadsSearch(cx);
      }
    }
    this.keyFocus?.focus?.();
    this.notifyPanes(cx, { shell: false, side: true });
  }

  inlineFilterBar(tabKey, id, state, query, placeholder, onClear, t, { focused = false } = {}) {
    const lang = this.lang;
    const surf = tonalSurfaces(t);
    const hint = div().absolute().left(0).top(4).right(0).truncate().text_size(12).text_color(t.dim).child(placeholder);
    return keepPress(h_flex().id(id)).w_full().h(30).px(12).gap(6).flex_none().items_center()
      .bg(t.background)
      .border_b(1).border_color(focused ? withAlpha(t.accent, .48) : surf.hairline)
      .child(div().relative().flex_1().min_w(0).h(24).when(!query, el => el.child(hint))
        .child(Input.new(state).w_full().h(24).items_center().text_size(12).text_color(t.foreground)))
      .when(Boolean(query), el => el.child(this.withTip(`${id}-clear`, h_flex().id(`${id}-clear`).size(18).flex_none().rounded(5).items_center()
        .justify_center().cursor_pointer().text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
        .accessibility_label(word(lang, 'clearSearch'))
        .on_click((_e, cx) => { cx.stop_propagation(); onClear(cx); })
        .child(this.icon('close', 10.5)), word(lang, 'clearSearch'), t, { panel: true, placement: 'below-right' })))
      .child(div().flex_none().font_family('monospace').text_size(10.5).text_color(t.dim).child(word(lang, 'inlineFilterHint')));
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
    const onThreads = !onSide && !this.detail && this.listResting();
    const tabQuery = onLib ? this.libraryQuery : onMem ? this.memoryQuery : onThreads ? this.threadsQuery : '';
    const searchTyping = onLib ? 'librarySearch' : onMem ? 'memorySearch' : 'threadsSearch';
    const inTabSearch = ((onSide && !hasDoc && !hasEdit && !hasHistory) || onThreads) &&
      (this.typing === searchTyping || Boolean(tabQuery?.trim()) || Boolean(this.inlineFilterOpen));
    const mentionOpen = Boolean(this.mention && this.typing === this.mention.which);
    const activeTab = this.activeSideTab();
    const step = escapeStep({
      imageLightbox: Boolean(this.imageLightbox),
      mentionSub: mentionOpen && this.mention.category !== 'all',
      mention: mentionOpen,
      projectSearch: Boolean(this.searchOpen),
      foldersPopover: Boolean(this.foldersOpen),
      tabMenu: Boolean(this.tabMenu),
      selectionBar: Boolean(this.selectionBar),
      answering: Boolean(this.answering) && this.typing !== 'thread',
      confirmDelete: onSide && hasDoc && Boolean(this.confirmDeleteKey),
      confirmCloseDirty: Boolean(this.confirmCloseTabId),
      typing: composerTyping || editorTyping,
      editing: hasEdit,
      retopic: onSide && hasDoc && Boolean(this.retopicOpen),
      search: inDocFind || inTabSearch,
      agentWindows: this.agentWindows,
      history: hasHistory,
      bringBack: Boolean(this.bringBackOpen && !this.bringingBack),
      change: this.isThreadChangeOpen(),
      activeTab: Boolean(activeTab && this.isPanelOpen()),
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
    if (step === 'imageLightbox') { this.closeImageLightbox(cx); return; }
    if (step === 'mentionSub' || step === 'mention') { this.escapeMention(this.mention.which, cx); return; }
    if (step === 'projectSearch') { this.escapeProjectSearch(cx); return; }
    if (step === 'foldersPopover') {
      if (this.foldersEditingAlias) { this.foldersEditingAlias = null; this.keyFocus?.focus?.(); }
      else if (this.foldersRemotePicker?.open) { this.foldersRemotePicker = { ...this.foldersRemotePicker, open: false }; }
      else if (this.foldersRemoteOpen) { this.foldersRemoteOpen = false; this.foldersRemoteCheck = null; }
      else if (this.foldersConfirmRemove) { this.foldersConfirmRemove = null; }
      else { this.closeFoldersPopover(cx); return; }
      cx.notify();
      return;
    }
    if (step === 'tabMenu') { this.tabMenu = null; this.notifyPanes(cx, { shell: false, side: true }); return; }
    if (step === 'selectionBar') { this.selectionBar = null; cx.notify(); return; }
    if (step === 'answer') this.answering = null;
    else if (step === 'confirmDelete') this.confirmDeleteKey = '';
    else if (step === 'confirmCloseDirty') { this.confirmCloseTabId = ''; this.notifyPanes(cx, { shell: false, side: true }); return; }
    else if (step === 'blur') this.keyFocus.focus();
    else if (step === 'edit') { this.cancelEditDoc(cx); return; }
    else if (step === 'retopic') this.retopicOpen = false;
    else if (step === 'agentWindow') { this.closeTopAgentWindow(cx); return; }
    else if (step === 'bringBack') { this.closeBringBack(cx); return; }
    else if (step === 'change') { this.stepBackThreadChange(cx); return; }
    else if (step === 'search') {
      if (inDocFind) {
        if (this.docFindQuery.trim()) { this.docFindQuery = ''; this.docFindInput?.set_value(''); this.syncActiveTabFind(); }
        else { this.docFindOpen = false; this.syncActiveTabFind(); this.keyFocus.focus(); }
      } else if (tabQuery?.trim()) {
        if (onLib) { this.libraryQuery = ''; this.libraryInput?.set_value(''); }
        else if (onMem) { this.memoryQuery = ''; this.memoryInput?.set_value(''); }
        else { this.threadsQuery = ''; this.threadsInput?.set_value(''); this.scheduleThreadsSearch(cx); }
        this.inlineFilterOpen = false;
        this.keyFocus.focus();
      } else {
        this.inlineFilterOpen = false;
        this.keyFocus.focus();
      }
    } else if (step === 'history') { this.closeHistory(cx); return; }
    else if (step === 'activeTab') {
      if (this.typing === 'thread' || this.typing === 'docFind') this.keyFocus?.focus();
      if (this._panelOpenedFromClosed && this.sideTabsState().tabs.length === 1) {
        this.closeSidePanel(cx);
        return;
      }
      this.showIndexView(cx);
      return;
    }
    else if (step === 'detail') {
      if (this._panelOpenedFromClosed) {
        if (this.typing === 'thread') this.keyFocus?.focus();
        this.closeSidePanel(cx);
        return;
      }
      this.detail = false;
      this.resetThreadChange();
      this.syncVisibleSideTab(cx);
    }
    else if (step === 'doc') { this.closeActiveDoc(cx, { fromEscape: true }); return; }
    else {
      this.listShown = false;
      this._panelOpenedFromClosed = false;
      if (['threadsSearch', 'librarySearch', 'memorySearch', 'docFind', 'docEditor', 'docName', 'memDesc'].includes(this.typing)) {
        this.keyFocus?.focus();
      }
    }
    if (step === 'detail' && this.typing === 'thread') this.keyFocus.focus();
    this.notifyPanes(cx, { shell: true, conv: true, side: true });
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
    this.notifyPanes(cx, { shell: true, side: true });
  }

  closeThreadChange(cx) {
    this.change = closeChangeView(this.change);
    this.notifyPanes(cx, { shell: true, side: true });
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
    this.notifyPanes(cx, { shell: true, side: true });
    return true;
  }

  threadChangeButton(_task, t) {
    if (!this.threadChangeSupported()) return null;
    const open = this.isThreadChangeOpen();
    return this.splitIconBtn(
      'thread-diff',
      'diff',
      word(this.lang, open ? 'changeClose' : 'diff'),
      cx => this.toggleThreadChange(cx),
      t,
      14,
      open,
      { placement: 'below-right' },
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
        splitIconBtn: (id, name, tip, action, th, size = 14, active = false, tipOpts = null) => this.splitIconBtn(id, name, tip, action, th, size, active, tipOpts || { panel: true, placement: 'below-right' }),
        lockScrollBody: el => this.sideScrollBody(el),
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
      scrollHandle: this.tabScrollHandle('change'),
      inTabBar: this.hasSideTabs(),
      actions: {
        onBack: cx => this.stepBackThreadChange(cx),
        onClose: null,
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
    cx?.notify?.();
  }
  // Where a terminal can be shown (focusPlan): over its own pane, an ancestor's, or this project's PM's.
  // `address` as the project's machine names it (see machineView); the plan's are the app's.
  terminalPlace(address) {
    return focusPlan(onMachine(address, this.machine), terminals(), [...panes().map(p => p.terminal), ...agents().map(a => a.address)],
      onMachine(this.pmTerminal()?.address || '', this.machine));
  }
  // With nowhere to show it, nothing moves: showing work would reveal another project's space.
  // When focusing this project's own live PM that has no pane, place it into a tab in this project's
  // space first (`space.select` or `space.new`, then `terminal.keep`) so another project's space is
  // never revealed.
  focusTerminal(address) {
    const plan = this.terminalPlace(address);
    const pm = typeof this.pm === 'function' ? this.pm() : null;
    const pmTerm = typeof this.pmTerminal === 'function' ? this.pmTerminal() : null;
    const curSpaces = spaces();
    if (plan.focus) {
      const targetAddr = onMachine(address, this.machine || '');
      const pmAddr = onMachine(pmTerm?.address || '', this.machine || '');
      if (targetAddr && pmAddr && targetAddr === pmAddr && pm?.space_id) {
        const wantId = onMachine(pm.space_id, this.machine || '');
        const bound = (curSpaces || []).find(s => s?.id === wantId || s?.id === pm.space_id);
        if (bound?.id) run('space.select', { id: bound.id });
      }
      run('pane.focus', { terminal: plan.focus });
      run('layout.select', { stack: STAGE, child: WORK });
      if (plan.peek) run('terminal.peek', { terminal: plan.peek });
      return;
    }
    const keepSteps = pmKeepPlan(address, {
      pm,
      pmTerminal: pmTerm,
      machine: this.machine || '',
      spaces: curSpaces,
      panes: panes(),
    });
    if (!Array.isArray(keepSteps) || !keepSteps.length) return;
    const prevSpaceIds = new Set((curSpaces || []).map(s => s?.id).filter(Boolean));
    const createdSpace = keepSteps[0]?.[0] === 'space.new';
    for (const [cmd, args] of keepSteps) run(cmd, args);
    const pmAddr = onMachine(pmTerm?.address || '', this.machine || '');
    if (pmAddr) {
      this._pendingPmKeep = { terminal: pmAddr, tabName: pmTabNameFor(pm), createdSpace, prevSpaceIds, at: Date.now() };
    }
  }
  reconcilePendingPmKeep() {
    const pending = this._pendingPmKeep;
    if (!pending) return;
    if (Date.now() - pending.at > 15000) {
      this._pendingPmKeep = null;
      return;
    }
    const curSpaces = spaces();
    const curPanes = panes();
    const followUp = pmKeepFollowUp(pending, curSpaces, curPanes);
    if (!Array.isArray(followUp)) return;
    this._pendingPmKeep = null;
    for (const [cmd, args] of followUp) run(cmd, args);
    if (pending.createdSpace) {
      const pm = typeof this.pm === 'function' ? this.pm() : null;
      const slug = projectSlug(pm);
      const pmPane = (curPanes || []).find(p => p?.terminal === pending.terminal);
      const hostSpace = pmPane?.tab
        ? (curSpaces || []).find(sp => (sp?.tabs || []).some(tb => tb?.id && tb.id === pmPane.tab))
        : null;
      const rawSpId = String(hostSpace?.id || '');
      const prefix = this.machine ? `${this.machine}/` : '';
      const bareSpId = prefix && rawSpId.startsWith(prefix) ? rawSpId.slice(prefix.length) : rawSpId;
      if (slug && bareSpId && typeof this.runProject === 'function') {
        this.runProject(projectSetSpaceArgv(slug, bareSpId, { spaceName: projectName(pm) })).catch(() => null);
      }
    }
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
      if (opts.flexNone) box.flex_none();
      return box.child(target);
    }
    const panelW = opts.panel ? (this._lastLayout?.cardWidth || this.currentSplitLayout().cardWidth) : 0;
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
      if (opts.flexNone) box.flex_none();
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
  // Unified 28x28 icon button for the 44px split card top bar.
  splitIconBtn(id, name, tip, action, t, size = 14, active = false, tipOpts = {}) {
    return this.withTip(id, h_flex().id(id).size(28).flex_none().rounded(7).items_center().justify_center()
      .text_color(active ? t.accent : t.muted)
      .when(active, el => el.bg(withAlpha(t.accent, .14)))
      .accessibility_label(tip)
      .on_mouse_down('left', (_e, cx) => cx.stop_propagation())
      .when(Boolean(action), el => el.cursor_pointer()
        .hover(s => active ? s.bg(withAlpha(t.accent, .2)) : s.bg(t.hover).text_color(t.foreground))
        .on_click((_e, cx) => { cx.stop_propagation(); this.hoverKey = ''; action(cx); }))
      .when(!action, el => el.opacity(.4))
      .child(this.icon(name, size)), tip, t, { panel: true, placement: 'below-right', ...tipOpts });
  }
  // Unified 44px single-row split card top bar (or 36px Row 2 contextual sub-bar when compactBar=true).
  renderSplitTopBar({
    id = 'split-topbar',
    backId = 'split-back',
    backIcon = 'back',
    onBack,
    backTip,
    leading = null,
    titleId = 'split-title',
    title = '',
    titleTip = '',
    actions = null,
    closeId = 'split-close',
    onClose,
    closeTip,
    compactBar = false,
    titleMuted = false,
    t,
  }) {
    const lang = this.lang;
    const titleEl = div().id(titleId).w_full().truncate()
      .text_size(compactBar ? (titleMuted ? 11.5 : 12.5) : 13.5)
      .when(!titleMuted, el => el.font_semibold())
      .text_color(titleMuted ? t.dim : t.foreground)
      .child(title);
    const titleNode = titleTip
      ? this.withTip(titleId, titleEl, titleTip, t, { panel: true, placement: 'below-left', wrap: true, flex1: true })
      : div().flex_1().min_w(0).child(titleEl);
    const closeBtn = onClose
      ? this.splitIconBtn(closeId, 'close', closeTip || word(lang, 'closeSidePanel'), onClose, t, 14, false, { placement: 'below-right' })
      : null;
    return h_flex().id(id).h(compactBar ? 36 : 44).w_full().flex_none().px(12).gap(6).items_center()
      .bg(t.background)
      .border_b(1).border_color(withAlpha(t.border, compactBar ? .5 : .7))
      .when(Boolean(onBack), el => el.child(
        this.splitIconBtn(backId, backIcon, backTip || word(lang, 'close'), onBack, t, compactBar ? 13 : 14, false, { placement: 'below-left' }),
      ))
      .when(Boolean(leading), el => el.child(leading))
      .child(titleNode)
      .child(h_flex().flex_none().gap(2).items_center()
        .when(Boolean(actions), el => el.child(actions))
        .when(Boolean(actions && closeBtn), el => el.child(div().w(4).flex_none()))
        .when(Boolean(closeBtn), el => el.child(closeBtn)));
  }

  sideTabIcon(tab) {
    if (tab.kind === 'thread') return 'hook';
    if (tab.root === 'memory' || tab.root === 'personal' || tab.tab === 'memory') return 'memory';
    if (tab.root === 'research') return 'report';
    if (isPreviewableImage(tab.path)) return 'image';
    return 'file';
  }

  sideTabLabel(tab) {
    if (tab.kind === 'thread') {
      const allTasks = this.tasks || this.state.tasks || [];
      const st = allTasks.find(x => x.id === tab.taskId);
      const num = formatTaskNumber(taskNumber(st) || this.taskNumberFor(tab.taskId));
      const base = st?.title || tab.title || tab.taskId;
      return num ? `${num} ${base}` : base;
    }
    if (tab.kind === 'draft') {
      const draftName = tab.editDraft?.draftName?.trim?.();
      return draftName || tab.title || word(this.lang, tab.tab === 'memory' ? 'newMemory' : 'newDoc');
    }
    const meta = this.findDocMeta(tab.root, tab.path);
    return (meta ? libraryDocTitle(meta) : '') || tab.title || fileName(tab.path);
  }

  sideTabStripInfo(tab) {
    if (tab.kind === 'thread') {
      const allTasks = this.tasks || this.state.tasks || [];
      const st = allTasks.find(x => x.id === tab.taskId);
      const num = taskNumber(st) || this.taskNumberFor(tab.taskId);
      return threadTabStripLabel({ number: num, title: st?.title || tab.title, taskId: tab.taskId });
    }
    return { text: this.sideTabLabel(tab), compact: false };
  }

  sideTabThreadDot(tab, t) {
    const allTasks = this.tasks || this.state.tasks || [];
    const st = allTasks.find(x => x.id === tab.taskId);
    const status = String(st?.status || '');
    const dark = isDarkTheme(t);
    const doneColor = t.ansi2 ?? t.done ?? t.accent;
    const workColor = t.working ?? t.ansi3 ?? t.accent;
    if (['done', 'released', 'merged', 'abandoned', 'cancelled'].includes(status)) {
      return div().size(6.5).flex_none().rounded_full().bg(doneColor);
    }
    if (status === 'blocked' && !st?.answered) {
      return div().size(6.5).flex_none().rounded_full().bg(t.blocked);
    }
    if (status === 'review' || Boolean(st?.review && !['done', 'merged', 'released', 'abandoned', 'cancelled', 'paused', 'proposed'].includes(st.review.status))) {
      return div().size(6.5).flex_none().rounded_full().bg(t.accent);
    }
    if (status === 'proposed') {
      return div().size(6.5).flex_none().rounded_full().border(1.25).border_color(withAlpha(t.muted, dark ? .58 : .68));
    }
    if (status === 'paused' || Boolean(st?.offline)) {
      return div().size(6.5).flex_none().rounded_full().bg(t.dim);
    }
    if (status === 'in_progress' || (status === 'blocked' && Boolean(st?.answered))) {
      return div().size(6.5).flex_none().rounded_full().bg(workColor);
    }
    return div().size(6.5).flex_none().rounded_full().bg(t.muted);
  }

  // Plan B unified 40px right-panel header track:
  // Frameless directory links (Threads / Library / Memory) + optional divider + open detail tabs (#NNN / doc)
  // with a single subtle ~7% soft mist chip on whichever item is active, real +N overflow only when tabs exceed
  // strip width, zero [≡] button, zero duplicate × close button, zero second magnifying glass.
  sideHeaderBar(t, width, cx) {
    const lang = this.lang;
    const surf = tonalSurfaces(t);
    const dark = surf.dark;
    const st = this.sideTabsState();
    const tabs = st.tabs;
    const activeId = st.activeId;
    const narrow = width < 440;
    const menuBg = [t.raised, t.popover, t.surface].find(c => c && c !== t.chrome) || t.raised;

    const inDetailView = Boolean(activeId !== null || this.detail || this.activeDoc || this.editingDoc || this.historyView);
    const activeDirKey = this.activeIndexTabKey();
    const compactDir = width < 320;
    const dirTabs = this.librarySupported()
      ? [
          { key: 'threads', label: word(lang, 'threads') },
          { key: 'library', label: word(lang, 'libraryTab') },
          ...(this.memorySupported() ? [{ key: 'memory', label: word(lang, 'memoryTab') }] : []),
        ]
      : [{ key: 'threads', label: word(lang, 'threads') }];

    const dirEls = dirTabs.map(item => {
      const isDirActive = !inDetailView && item.key === activeDirKey;
      return this.withTip(`panel-tab-${item.key}`, h_flex().id(`panel-tab-${item.key}`).flex_none().h(26)
        .px(compactDir ? 7 : 9).rounded(6).items_center().justify_center()
        .text_size(compactDir ? 12 : 12.5).accessibility_label(item.label)
        .when(isDirActive, el => el.bg(surf.softChip).text_color(t.foreground).font_medium())
        .when(!isDirActive, el => el.cursor_pointer().text_color(t.muted)
          .hover(s => s.bg(surf.softChipHover).text_color(t.foreground))
          .on_mouse_down('left', (_e, mCx) => mCx.stop_propagation())
          .on_click((_e, cCx) => { cCx.stop_propagation(); this.selectSideTab(item.key, cCx); }))
        .child(item.label), item.label, t, { panel: true, placement: 'below-left' });
    });

    const showLibraryActions = !inDetailView && activeDirKey === 'library' && this.librarySupported();
    const showMemoryActions = !inDetailView && activeDirKey === 'memory' && this.memorySupported();
    const rightActions = showLibraryActions
      ? h_flex().id('library-header-actions').flex_none().gap(2).items_center()
          .child(this.splitIconBtn('library-new-doc', 'plus', word(lang, 'newDoc'), cCx => this.startNewDoc('library', cCx), t, 14))
          .child(this.splitIconBtn('library-add-file', 'upload', word(lang, 'addFiles'), cCx => this.pickLibraryFiles(cCx), t, 14))
          .child(this.splitIconBtn('library-history', 'history', word(lang, 'docHistory'),
            cCx => this.openHistory('library', 'docs', '', 'all', cCx), t, 14))
      : showMemoryActions
        ? h_flex().id('memory-header-actions').flex_none().gap(2).items_center()
            .child(this.splitIconBtn('memory-new', 'plus', word(lang, 'newMemory'), cCx => this.startNewDoc('memory', cCx), t, 14))
            .child(this.splitIconBtn('memory-history', 'history', word(lang, 'docHistory'),
              cCx => this.openHistory('memory', 'memory', '', 'all', cCx), t, 14))
        : null;

    // Estimate available strip width before first on_size_change measurement so frame 1 never flickers.
    const dirEstW = dirTabs.reduce((sum, item) => sum + estimateSideTabWidth({ text: item.label, compact: false }, { narrow: true }), 0)
      + Math.max(0, dirTabs.length - 1) * 2;
    const rightEstW = showLibraryActions ? 92 : showMemoryActions ? 62 : 0;
    const fallbackStripW = Math.max(80, (Number(width) || PANEL_WIDTH) - 24 - dirEstW - (tabs.length ? 15 : 0) - rightEstW);
    const effectiveStripW = this._sideTabStripW > 0 ? this._sideTabStripW : fallbackStripW;
    const overflowInfo = computeSideTabOverflow({
      tabs,
      activeId,
      stripWidth: effectiveStripW,
      narrow,
      stripInfoOf: tab => this.sideTabStripInfo(tab),
    });
    const visibleIdSet = new Set(overflowInfo.visibleIds);
    const visibleTabs = tabs.filter(tab => visibleIdSet.has(tab.id));

    const menuRow = (id, label, onClick, { danger = false, disabled = false } = {}) => h_flex().id(id)
      .w_full().h(26).px(8).gap(6).rounded(6).items_center()
      .text_size(12).text_color(danger ? t.blocked : disabled ? t.dim : t.foreground)
      .when(!disabled, el => el.cursor_pointer().hover(s => s.bg(t.hover))
        .on_mouse_down('left', (_e, mCx) => mCx.stop_propagation())
        .on_click((_e, cCx) => { cCx.stop_propagation(); onClick(cCx); }))
      .child(div().flex_1().min_w(0).truncate().child(label));

    const stripItems = [];
    for (let i = 0; i < visibleTabs.length; i++) {
      const tab = visibleTabs[i];
      const fullIdx = tabs.findIndex(x => x.id === tab.id);
      const isActive = tab.id === activeId;
      const isHovered = this.hoveredTabId === tab.id;
      const label = this.sideTabLabel(tab);
      const strip = this.sideTabStripInfo(tab);
      const isThread = tab.kind === 'thread';
      const showClose = isActive || isHovered;
      const tailEl = showClose
        ? h_flex().id(`side-tab-close-${tab.id}`).size(16).flex_none().rounded(4).items_center().justify_center()
            .cursor_pointer().text_color(t.muted).hover(s => s.bg(t.hover).text_color(t.foreground))
            .accessibility_label(word(lang, 'sideTabClose'))
            .on_mouse_down('left', (_e, mCx) => mCx.stop_propagation())
            .on_click((_e, cCx) => { cCx.stop_propagation(); this.closeTab(tab.id, cCx); })
            .child(this.icon('close', 10))
        : tab.dirty
          ? h_flex().size(16).flex_none().items_center().justify_center()
              .child(div().id(`side-tab-dirty-${tab.id}`).size(6).rounded_full().bg(t.accent))
          : (strip.compact ? null : div().size(16).flex_none());

      const ctxOpen = this.tabMenu?.kind === 'context' && this.tabMenu.tabId === tab.id;
      const hasRight = fullIdx >= 0 && fullIdx < tabs.length - 1;
      const hasOthers = tabs.length > 1;
      const ctxPopup = ctxOpen ? Popup.new(`tab-ctx-menu-${tab.id}`, div().w(0).h(0)).anchor('top_left')
        .content(keepPress(v_flex().id('tab-ctx-menu').w(188).p(4).gap(2).rounded(9)
          .bg(menuBg).border_1().border_color(t.border).shadow_lg(), this.keyFocus)
          .child(menuRow('tab-ctx-close', word(lang, 'sideTabClose'), cCx => this.closeTab(tab.id, cCx)))
          .child(menuRow('tab-ctx-others', word(lang, 'sideTabCloseOthers'), cCx => this.closeOtherTabs(tab.id, cCx), { disabled: !hasOthers }))
          .child(menuRow('tab-ctx-right', word(lang, 'sideTabCloseRight'), cCx => this.closeRightTabs(tab.id, cCx), { disabled: !hasRight }))
          .child(menuRow('tab-ctx-all', word(lang, 'sideTabCloseAll'), cCx => this.closeAllTabs(cCx), { danger: true }))
          .when(tab.kind === 'doc' && Boolean(tab.path), el => el
            .child(div().w_full().h(1).my(2).bg(t.border))
            .child(menuRow('tab-ctx-copy', word(lang, 'sideTabCopyPath'), cCx => {
              cCx.write_to_clipboard?.(tab.path);
              this.tabMenu = null;
              this.notifyPanes(cCx, { shell: false, side: true });
            })))) : null;

      // Full-title preview tooltip on hovering an inactive compact `#NNN` thread tab.
      const tabTipPopup = (!isActive && isHovered && !ctxOpen && strip.compact && label && label !== strip.text)
        ? Popup.new(`side-tab-tip-${tab.id}`, div().w(0).h(0)).anchor('top_left')
            .content(v_flex().max_w(260).px(9).py(5.5).rounded(8).bg(menuBg).border_1().border_color(t.border).shadow_lg()
              .child(div().whitespace_normal().text_size(11.5).line_height('16px').text_color(t.foreground).child(label)))
        : null;

      const leadGlyph = isThread
        ? h_flex().size(12).flex_none().items_center().justify_center().child(this.sideTabThreadDot(tab, t))
        : this.icon(this.sideTabIcon(tab), 12.5).text_color(isActive ? t.foreground : t.dim);

      const tabEl = h_flex().id(`side-tab-${tab.id}`).relative().h(26).px(strip.compact ? 7.5 : 8).gap(5).rounded(6)
        .flex_none().items_center().cursor_pointer()
        .when(strip.compact, el => el.min_w(0).max_w(120))
        .when(!strip.compact, el => el.min_w(narrow ? 72 : 84).max_w(narrow ? 124 : 156))
        .accessibility_label(tab.dirty ? word(lang, 'sideTabDirtyHint', label) : label)
        .when(isActive, el => el.bg(surf.softChip).text_color(t.foreground).font_medium())
        .when(!isActive, el => el.text_color(t.muted).hover(s => s.bg(surf.softChipHover).text_color(t.foreground)))
        .when(Boolean(tab.missing), el => el.opacity(.6))
        .on_hover((over, hCx) => {
          const next = over ? tab.id : (this.hoveredTabId === tab.id ? '' : this.hoveredTabId);
          if (next !== this.hoveredTabId) {
            this.hoveredTabId = next;
            this.notifyPanes(hCx, { shell: false, side: true });
          }
        })
        .on_mouse_down('left', (_e, mCx) => mCx.stop_propagation())
        .on_mouse_down('middle', (_e, mCx) => { mCx.stop_propagation(); this.closeTab(tab.id, mCx); })
        .on_mouse_down('right', (_e, mCx) => {
          mCx.stop_propagation();
          this.tabMenu = ctxOpen ? null : { kind: 'context', tabId: tab.id };
          this.notifyPanes(mCx, { shell: false, side: true });
        })
        .on_click((_e, cCx) => { cCx.stop_propagation(); this.activateTab(tab.id, cCx); })
        .child(leadGlyph)
        .when(strip.compact, el => el.child(div().flex_none().font_family('monospace').text_size(12).child(strip.text)))
        .when(!strip.compact, el => el.child(div().flex_1().min_w(0).truncate().text_size(12).child(strip.text)))
        .when(Boolean(tailEl), el => el.child(tailEl))
        .when(Boolean(ctxPopup), el => el.child(div().absolute().left(0).bottom(0).w(0).h(0).child(ctxPopup)))
        .when(Boolean(tabTipPopup), el => el.child(div().absolute().left(0).bottom(-4).w(0).h(0).child(tabTipPopup)));

      stripItems.push(tabEl);
    }

    const overflowOpen = this.tabMenu?.kind === 'overflow';
    const overflowPopup = overflowOpen ? Popup.new('side-tab-overflow-menu', div().w(0).h(0)).anchor('top_right')
      .content(keepPress(v_flex().id('side-tab-overflow-popup').w(248).max_h(360).p(4).gap(2).rounded(10)
        .bg(menuBg).border_1().border_color(t.border).shadow_lg(), this.keyFocus)
        .child(v_flex().w_full().max_h(260).gap(1).overflow_y_scrollbar()
          .children(tabs.map(tab => {
            const isAct = tab.id === activeId;
            const lbl = this.sideTabLabel(tab);
            const rowGlyph = tab.kind === 'thread'
              ? h_flex().size(12.5).flex_none().items_center().justify_center().child(this.sideTabThreadDot(tab, t))
              : this.icon(this.sideTabIcon(tab), 12.5).text_color(isAct ? t.accent : t.dim);
            return h_flex().id(`overflow-tab-${tab.id}`).w_full().h(28).px(8).gap(6).rounded(7)
              .items_center().cursor_pointer()
              .when(isAct, el => el.bg(surf.softChip).text_color(t.foreground).font_medium())
              .when(!isAct, el => el.text_color(t.muted).hover(s => s.bg(t.hover).text_color(t.foreground)))
              .on_mouse_down('left', (_e, mCx) => mCx.stop_propagation())
              .on_click((_e, cCx) => { cCx.stop_propagation(); this.activateTab(tab.id, cCx); })
              .child(rowGlyph)
              .child(div().flex_1().min_w(0).truncate().text_size(12).child(lbl))
              .when(Boolean(tab.dirty), el => el.child(div().size(6).flex_none().rounded_full().bg(t.accent)))
              .child(h_flex().id(`overflow-close-${tab.id}`).size(18).flex_none().rounded(5).items_center().justify_center()
                .text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
                .on_mouse_down('left', (_e, mCx) => mCx.stop_propagation())
                .on_click((_e, cCx) => { cCx.stop_propagation(); this.closeTab(tab.id, cCx); })
                .child(this.icon('close', 10)));
          })))
        .child(div().w_full().h(1).my(2).bg(t.border))
        .when(Boolean(activeId && tabs.length > 1), el => el.child(
          menuRow('overflow-close-others', word(lang, 'sideTabCloseOthers'), cCx => this.closeOtherTabs(activeId, cCx)),
        ))
        .child(menuRow('overflow-close-all', word(lang, 'sideTabCloseAll'), cCx => this.closeAllTabs(cCx), { danger: true }))) : null;

    const overflowBtn = overflowInfo.overflow
      ? h_flex().id('side-tab-overflow').relative().h(26).px(6).gap(2).rounded(6).flex_none()
          .items_center().cursor_pointer().text_size(11.5)
          .when(overflowOpen, el => el.bg(surf.softChip).text_color(t.foreground))
          .when(!overflowOpen, el => el.text_color(t.muted).hover(s => s.bg(surf.softChipHover).text_color(t.foreground)))
          .accessibility_label(word(lang, 'sideTabsOverflowTip', overflowInfo.hiddenCount))
          .on_mouse_down('left', (_e, mCx) => mCx.stop_propagation())
          .on_click((_e, cCx) => {
            cCx.stop_propagation();
            this.tabMenu = overflowOpen ? null : { kind: 'overflow' };
            this.notifyPanes(cCx, { shell: false, side: true });
          })
          .child(word(lang, 'sideTabsOverflow', overflowInfo.hiddenCount))
          .child(this.icon('expand', 10))
          .when(Boolean(overflowPopup), el => el.child(div().absolute().right(0).bottom(0).w(0).h(0).child(overflowPopup)))
      : null;

    const tabStripEl = tabs.length > 0
      ? h_flex().id('side-tab-strip').flex_1().min_w(0).h(40).gap(3).items_center().overflow_hidden()
          .on_size_change((size, sCx) => {
            const w = Math.round(Number(size?.width) || 0);
            if (w > 0 && Math.abs(w - (this._sideTabStripW || 0)) >= 2) {
              this._sideTabStripW = w;
              this.notifyPanes(sCx, { shell: false, side: true });
            }
          })
          .children(stripItems)
      : div().flex_1().min_w(0);

    return h_flex().id('side-header').h(40).w_full().flex_none().px(10).gap(4).items_center()
      .bg(t.background)
      .border_b(1).border_color(surf.hairline)
      .child(h_flex().id('panel-tabs').flex_none().h(28).gap(2).items_center().children(dirEls))
      .when(tabs.length > 0, el => el.child(div().id('side-header-divider').w(1).h(14).mx(4).flex_none()
        .bg(withAlpha(t.border, dark ? .55 : .7))))
      .child(tabStripEl)
      .when(Boolean(overflowBtn), el => el.child(overflowBtn))
      .when(Boolean(rightActions), el => el.child(rightActions));
  }

  sideTabBanners(t, cx) {
    const lang = this.lang;
    const active = this.activeSideTab();
    const out = [];
    if (this.confirmCloseTabId && active && this.confirmCloseTabId === active.id) {
      out.push(h_flex().id('side-tab-dirty-bar').flex_none().mx(12).mt(6).px(10).py(5).gap(6).rounded(8).items_center()
        .bg(withAlpha(t.blocked, .12)).border_1().border_color(withAlpha(t.blocked, .35))
        .child(div().flex_1().min_w(0).whitespace_normal().text_size(12).text_color(t.foreground)
          .child(word(lang, 'sideTabDirtyWarning')))
        .child(this.iconButton('side-tab-dirty-save', 'check', word(lang, 'sideTabSaveAndClose'),
          cx => this.saveEditingDoc(cx, { closeTabAfter: true }), t, 14))
        .child(this.iconButton('side-tab-dirty-discard', 'trash', word(lang, 'sideTabDiscardAndClose'),
          cx => this.closeTab(active.id, cx, { force: true }), t, 14).text_color(t.blocked))
        .child(this.iconButton('side-tab-dirty-cancel', 'close', word(lang, 'sideTabCancelClose'),
          cx => { this.confirmCloseTabId = ''; this.notifyPanes(cx, { shell: false, side: true }); }, t, 13)));
    }
    if (this.tabLimitBanner) {
      out.push(h_flex().id('side-tab-limit-bar').flex_none().mx(12).mt(6).px(10).py(5).gap(6).rounded(8).items_center()
        .bg(withAlpha(t.blocked, .12)).border_1().border_color(withAlpha(t.blocked, .35))
        .child(div().flex_1().min_w(0).whitespace_normal().text_size(12).text_color(t.foreground)
          .child(this.tabLimitBanner))
        .child(this.iconButton('side-tab-limit-dismiss', 'close', word(lang, 'dismissNotice'),
          cx => { this.tabLimitBanner = ''; this.notifyPanes(cx, { shell: false, side: true }); }, t, 12)));
    }
    if (this.deletedBanner && active) {
      const delBar = this.deletedBannerBar(this.deletedBanner.tab, t);
      if (delBar) out.push(delBar);
    }
    return out;
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
    const sideW = this._lastLayout?.cardWidth || this.currentSplitLayout().cardWidth;
    const cardW = id === 'say-thread' ? Math.max(240, Math.min(360, sideW - 40)) : 360;
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
          const surf = tonalSurfaces(t);
          const folderAlias = row.kind === 'file' ? String(row.folderAlias || '').trim() : '';
          rowEl
            .child(h_flex().flex_1().min_w(0).gap(6).items_center()
              .when(Boolean(rowNum), el => el.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(rowNum)))
              .child(div().min_w(0).truncate().text_size(13).font_medium()
                .text_color(row.dimmed ? t.muted : t.foreground)
                .when(!row.subtitle, s => s.flex_1())
                .when(Boolean(row.subtitle), s => s.max_w(180))
                .child(row.label))
              .when(Boolean(row.subtitle), el => el.child(div().flex_1().min_w(0).truncate().text_size(11.5).text_color(t.dim).child(row.subtitle))))
            .when(Boolean(folderAlias), el => el.child(h_flex().id(`${id}-mention-folder-${i}`).h(18).px(5.5).rounded(4.5).flex_none()
              .items_center().bg(surf.pillMuted).font_family('monospace').text_size(10.5).text_color(t.muted).child(folderAlias)))
            .when(!folderAlias, el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(row.typeLabel)));
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
      const msg = menu.loadingText || (menu.category === 'files'
        ? word(lang, 'mentionLoadingFiles')
        : menu.category === 'threads'
          ? word(lang, 'threadsSearching')
          : word(lang, 'libraryLoading'));
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
        pillBg: withAlpha(t.accent, dark ? .24 : .16),
        pillText: t.accent,
        strong: true,
      };
    }
    if (scope === 'paragraph') {
      return {
        icon: 'quote-paragraph',
        pillBg: withAlpha(t.accent, dark ? .15 : .10),
        pillText: t.accent,
        strong: false,
      };
    }
    return {
      icon: 'quote',
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
        .on_click((_e, cx) => { cx.stop_propagation(); this.answering = null; this.input.focus(); this.notifyPanes(cx, { shell: false, conv: true, side: true }); })
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
          .bg(t.raised).border_1().border_color(t.border)
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
      .on_click((_e, cx) => this.openThread(row.task, cx, { insertAdjacent: true }))
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
            .pl(6).pr(2).py(2).rounded(6)
            .when(paraFlashed, el => el.bg(withAlpha(t.accent, qDark ? .14 : .10)))
            .when(!paraFlashed && paraActive, el => el.bg(withAlpha(t.foreground, qDark ? .04 : .035)))
            .on_hover((over, cx) => this.setHoveredPara(paraKey, over, cx))
            .child(this.selectableText(`q-txt-${item.key}-p${seg.index}`, seg.markdown, qSource).flex_1().min_w(0).text_color(asking ? t.foreground : t.muted))
            .child(h_flex().id(`para-quote-slot-${item.key}-${seg.index}`).w(22).h(22).flex_none().justify_end()
              .when(paraActive, el => el.child(this.paragraphQuoteButton(qSource, seg, t))));
        }))
      : this.selectableText(`q-txt-${item.key}`, item.text, qSource).w_full().text_color(asking ? t.foreground : t.muted);
    const qImages = this.renderInlineImagePreviews(`q-${item.key}`, item.text, t, cx, { maxWidth: 480, maxHeight: 240 });
    const card = v_flex().id(`question-msg-${item.key}`).w_full().p(6).gap(2).rounded(14).border_1()
      .when(Boolean(qSource), el => el.on_hover((h, cx) => this.setHoveredMsg(item.key, h, cx)))
      .child(v_flex().px(10).pt(6).pb(rows.length ? 6 : 4).gap(3)
        .child(h_flex().w_full().min_h(24).items_center().justify_between().gap(6)
          .child(name)
          .when(hovered, el => el.child(this.quoteButton(qSource, t, { whole: qMulti }))))
        .child(qBody)
        .when(Boolean(qImages), el => el.child(qImages)))
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
              .pl(6).pr(2).py(2).rounded(6)
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
        const pmImages = this.renderInlineImagePreviews(`pm-${item.key}`, rawText, t, cx, { maxWidth: 520, maxHeight: 280 });
        const contentNode = pmImages ? v_flex().w_full().child(wholeNode).child(pmImages) : wholeNode;
        // A long reply shows its opening paragraph until it is opened. The newest one is open, and so
        // stays every reply that arrived while this project was on screen: history folds, the live
        // conversation does not move under the reader.
        bodyNode = (!item.long || item.key === this.newest)
          ? contentNode
          : v_flex().w_full().child(contentNode)
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
    // typing: the coordinator is at work (quiet live activity + always-on interrupt + §3.9 mapping).
    const pmTermNow = this.pmTerminal();
    const rawActView = pmActivityView(this.lang, {
      turn: this.activePmTurn(),
      turn2: this.activePmTurn2(),
      supervised: this.activePmSupervised(),
      working: this.isPmWorking(pmTermNow, this.live(), this.activePmTurn()),
      pendingSending: this.pending.some(p => !p.failed && !p.queued && !p.received),
      nowMs: this.nowMs(),
      serverNowMs: this.serverNowMs || 0,
      receivedAtMs: this.serverNowAt || 0,
      agentKind: this.pm()?.agent || '',
    });
    const actView = rawActView && typeof rawActView === 'object'
      ? rawActView
      : { mode: 'dots', label: '', preamble: '', tooltip: '', tone: 'neutral', stalled: false, canInterrupt: false, canRotate: false, canOpenTerminal: false };
    const dotsColor = actView.stalled ? t.blocked : actView.tone === 'warn' ? (t.ansi3 || t.blocked) : actView.unknown ? t.dim : t.muted;
    const dotsEl = h_flex().gap(5).items_center().flex_none().loop('opacity', { from: .35, to: 1, period: 1400 })
      .children([0, 1, 2].map(() => div().size(6).rounded(3).bg(dotsColor)));
    const hasActions = Boolean(
      (actView.canInterrupt && pmTermNow)
      || (actView.canRotate && this.pm()?.repo)
      || (actView.canOpenTerminal && pmTermNow)
    );
    if (!actView.label && !hasActions) {
      return h_flex().id('pm-typing-line').h(28).items_center().child(dotsEl);
    }
    const interrupting = this.interruptingPm === this.pmName;
    const rotating = this.rotatingPm === this.pmName;
    const intTip = word(this.lang, interrupting ? 'interruptingPmTip' : 'interruptPmTip');
    const rotTip = word(this.lang, rotating ? 'rotatingPmTip' : 'rotatePmTip');
    const openTip = word(this.lang, 'openPm');
    const labelTextColor = actView.stalled ? t.blocked : actView.tone === 'warn' ? (t.ansi3 || t.foreground) : t.dim;
    const displayLabel = actView.preamble && actView.mode === 'working' && actView.label && !actView.label.includes(actView.preamble)
      ? `${actView.preamble} · ${actView.label}`
      : actView.label;
    const labelNode = displayLabel
      ? div().id('pm-typing-label').flex_1().min_w(0).truncate().text_size(12.5)
        .text_color(labelTextColor)
        .child(displayLabel)
      : div().flex_1().min_w(0);
    const labelWithTip = (displayLabel && actView.tooltip)
      ? this.withTip('pm-typing-label', labelNode, actView.tooltip, t, { placement: 'above-left' })
      : labelNode;
    return h_flex().id('pm-typing-line').w_full().min_h(28).gap(8).items_center()
      .child(dotsEl)
      .child(labelWithTip)
      .when(hasActions, el => el.child(h_flex().id('pm-typing-actions').flex_none().gap(4).items_center()
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
        .when(Boolean(actView.canOpenTerminal && pmTermNow), a => a.child(this.withTip('pm-open-term-btn',
          h_flex().id('pm-open-term-btn').size(24).rounded(7).items_center().justify_center()
            .text_color(t.muted).accessibility_label(openTip).cursor_pointer()
            .hover(s => s.bg(t.hover).text_color(t.foreground))
            .on_click(() => this.focusTerminal(pmTermNow.address))
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
    if (b.kind === 'incident') {
      const iv = incidentRowView(this.lang, b);
      const dark = isDarkTheme(t);
      const flatLabel = String(iv.label || '').replace(/\s+/g, ' ').trim();
      const rowId = `incident-${b.key}`;
      if (iv.tone === 'muted' || iv.tone === 'resolved') {
        const quietRow = h_flex().id(rowId).w_full().items_center().gap(6).px(8).py(4)
          .text_size(12).text_color(t.dim)
          .child(this.icon(iv.icon, 12).flex_none().text_color(t.muted))
          .child(div().flex_1().min_w(0).truncate().child(flatLabel));
        return iv.tooltip ? this.withTip(rowId, quietRow, iv.tooltip, t, { placement: 'above-left' }) : quietRow;
      }
      if (iv.tone === 'alert') {
        const alertRow = h_flex().id(rowId).w_full().items_start().gap(8).px(12).py(9).rounded(10)
          .bg(withAlpha(t.blocked, dark ? .14 : .09)).border_1().border_color(withAlpha(t.blocked, .45))
          .text_size(12.5).text_color(t.foreground)
          .child(this.icon(iv.icon, 13.5).flex_none().text_color(t.blocked))
          .child(div().flex_1().min_w(0).whitespace_normal().child(flatLabel));
        return iv.tooltip ? this.withTip(rowId, alertRow, iv.tooltip, t, { placement: 'above-left' }) : alertRow;
      }
      const recRow = h_flex().id(rowId).w_full().items_start().gap(8).px(12).py(8).rounded(10)
        .bg(t.raised).border_1().border_color(t.border)
        .text_size(12.5).text_color(t.muted)
        .child(this.icon(iv.icon, 13).flex_none().text_color(t.muted))
        .child(div().flex_1().min_w(0).whitespace_normal().child(flatLabel));
      return iv.tooltip ? this.withTip(rowId, recRow, iv.tooltip, t, { placement: 'above-left' }) : recRow;
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
              .pl(5).pr(2).py(2).rounded(6)
              .when(paraFlashed, el => el.bg(withAlpha(t.accent, dark ? .16 : .11)))
              .when(!paraFlashed && paraActive, el => el.bg(withAlpha(t.foreground, dark ? .05 : .04)))
              .on_hover((over, cx) => this.setHoveredPara(paraKey, over, cx))
              .child(this.renderMentionText(`bubble-${b.key}-p${seg.index}`, seg.markdown, t, cx, userSource))
              .child(h_flex().id(`para-quote-slot-${b.key}-${seg.index}`).w(22).h(22).flex_none().justify_end()
                .when(paraActive, el => el.child(this.paragraphQuoteButton(userSource, seg, t))));
          }))
        : this.renderMentionText(`bubble-${b.key}`, bodyText, t, cx, userSource);
      const splitLay = this._lastLayout || this.currentSplitLayout();
      const openInlineW = (this.isPanelOpen() && splitLay.layoutKind === 'inline') ? splitLay.slotWidth : 0;
      const quotePreviewW = msgQuotes.length > 0
        ? Math.max(180, Math.min(410, Math.floor((this.viewWidth
          ? Math.min(COLUMN, Math.max(260, this.viewWidth - openInlineW - 64))
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
              .bg(t.surface).border_1().border_color(t.border)
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
      const rawQueuedReason = b.queued && b.queuedReason && typeof queuedReasonText === 'function'
        ? queuedReasonText(this.lang, b.queuedReason)
        : '';
      const queuedReason = typeof rawQueuedReason === 'string' ? rawQueuedReason : '';
      const isDraftReason = String(b.queuedReason || '').toLowerCase() === 'waiting_quiet_or_draft';
      const queuedLabel = isDraftReason
        ? queuedReason
        : (queuedReason ? `${word(this.lang, 'queued')} · ${queuedReason}` : word(this.lang, 'queued'));
      const queuedTip = queuedReason ? `${queuedReason} · ${word(this.lang, 'queuedTip')}` : word(this.lang, 'queuedTip');
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
            ? this.withTip(`bubble-${b.key}`, bubbleEl.opacity(.82), queuedTip, t, { placement: 'above-right' })
            : bubbleEl);
      if (b.queued) {
        return v_flex().w_full().items_end().gap(4).child(row)
          .child(this.withTip(`queued-${b.key}`, h_flex().id(`queued-${b.key}`).gap(5).items_center().text_size(11.5).text_color(t.muted)
            .child(div().size(5).rounded_full().bg(t.blocked))
            .child(queuedLabel), queuedTip, t, { placement: 'above-right' }));
      }
      // A logged message still on its way through the PM's mailbox (§3.9): sending → queued (why) → delivered,
      // waiting → read; gone once answered. Only a failed one is red.
      const delivery = (!b.pending && !b.failed && b.delivery) ? this.deliveryLine(b.delivery) : null;
      if (delivery) {
        const dot = delivery.failed ? t.blocked : delivery.queued ? t.blocked : delivery.read ? t.accent : t.muted;
        return v_flex().w_full().items_end().gap(4).child(row)
          .child(h_flex().id(`delivery-${b.key}`).max_w('72%').gap(5).items_center().text_size(11.5)
            .text_color(delivery.failed ? t.blocked : t.muted)
            .accessibility_label(delivery.label)
            .child(div().size(5).flex_none().rounded_full().bg(dot))
            .child(div().min_w(0).whitespace_normal().child(delivery.label)));
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
    } else if (act.kind === 'toggle-folders') {
      this.toggleFoldersPopover(cx);
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
    const panelOpen = this.isPanelOpen();
    const bgShellsCount = Number(this.activePmTurn2()?.bg_shells?.count ?? this.activePmTurn()?.bg_shells ?? 0) || 0;
    const pmTerminalTip = bgShellsCount > 0 ? word(lang, 'openPmBgShells', bgShellsCount) : word(lang, 'openPm');
    const foldersView = headerFoldersView(pm, { machine: this.machine, homeDir: home(), lang });
    return {
      session: this.winSession,
      pmName: this.pmName,
      lang,
      hasPm: Boolean(pm),
      isRemote: Boolean(this.machine),
      title: projectName(pm) || 'PM',
      renameTip: word(lang, 'renameProject'),
      pathText: this.machine ? `${this.machine} · ${pm?.repo || ''}` : shortPath(pm?.repo, home()),
      foldersView,
      foldersOpen: Boolean(this.foldersOpen),
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
      pmTerminalTip,
      pmOfflineTip,
      panelOpen,
      panelTip: word(lang, panelOpen
        ? (this.librarySupported() ? 'hideSidePanel' : 'hideThreads')
        : (this.librarySupported() ? 'showSidePanel' : 'showThreads')),
    };
  }

  renderWindowControls(t, lang, { divider = true } = {}) {
    let win = null;
    try { win = appWindow?.(); } catch (_) { win = null; }
    let overlay = false;
    try { overlay = Boolean(props?.()?.overlay); } catch (_) { overlay = false; }
    const buttons = typeof windowControlButtons === 'function'
      ? windowControlButtons(win, { overlay })
      : [];
    if (!Array.isArray(buttons) || !buttons.length) return null;
    const stop = (_e, cx) => cx.stop_propagation();
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
    const boardBtn = hdrIconBtn('view-board', 'board', word(lang, 'switchToBoard'), () => {
      setShared('pm-dash', { view: 'board', project: data.pmName });
      run('layout.select', { stack: STAGE, child: BOARD });
    }, 16);
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
      ? hdrIconBtn('pm-terminal', 'terminal', data.pmTerminalTip || word(lang, 'openPm'), () => actions.onOpenPm())
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
    const panelBtn = hdrIconBtn(panelBtnId, 'panel', data.panelTip, cx => actions.onTogglePanel(cx))
      .when(Boolean(data.panelOpen), el => el.bg(t.raised).text_color(t.foreground));
    const base = h_flex().id('pm-project-header-bar');
    const bar = (standalone ? base.h(56).flex_none() : base.size_full().bg(t.canvas).text_size(14).text_color(t.foreground))
      .pl(28).pr(14).gap(10).items_center();
    const winControls = this.renderWindowControls(t, lang, { divider: true });
    const renameTip = data.renameTip || word(lang, 'renameProject');
    const renameBtn = (!data.isRemote && actions.onRename)
      ? keepPress(
        tipWrap('pm-project-rename', h_flex().id('pm-project-rename').size(26).flex_none().rounded(7).items_center().justify_center()
          .cursor_pointer().text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
          .accessibility_label(renameTip)
          .on_click((_e, cx) => { cx.stop_propagation(); actions.onRename(cx); })
          .child(this.icon('pencil', 13)),
        renameTip, { placement: 'below-left' }),
        this.keyFocus)
      : null;
    const surf = tonalSurfaces(t);
    const fv = data.foldersView || (data.pathText
      ? { count: 1, mode: 'single', primaryLabel: data.pathText, extraCount: 0, tooltip: word(lang, 'workspaceFoldersTip', 1) }
      : { count: 0, mode: 'empty', primaryLabel: word(lang, 'addFolderShort'), extraCount: 0, tooltip: word(lang, 'workspaceFoldersEmptyTip') });
    const foldersPillEl = h_flex().id('pm-header-folders').h(26).px(7).gap(5).rounded(7).items_center().min_w(0)
      .when(Boolean(actions.onToggleFolders), el => el.cursor_pointer()
        .when(data.foldersOpen, s => s.bg(surf.softChip))
        .hover(s => s.bg(t.hover))
        .on_click((_e, cx) => { cx.stop_propagation(); actions.onToggleFolders(cx); }))
      .accessibility_label(fv.tooltip || fv.primaryLabel)
      .child(this.icon(fv.mode === 'empty' ? 'folder-plus' : 'folder', 13.5)
        .text_color(data.foldersOpen ? t.foreground : (fv.mode === 'empty' ? t.dim : t.muted)))
      .when(fv.mode === 'empty', el => el.child(div().min_w(0).truncate().text_size(12)
        .text_color(data.foldersOpen ? t.foreground : t.dim).child(`+ ${fv.primaryLabel}`)))
      .when(fv.mode !== 'empty', el => el.child(div().min_w(0).truncate().font_family('monospace').text_size(12)
        .text_color(data.foldersOpen ? t.foreground : t.muted).child(fv.primaryLabel)))
      .when(fv.mode === 'multi' && fv.extraCount > 0, el => el
        .child(h_flex().id('pm-header-folders-extra').h(18).px(5.5).rounded(5).flex_none().items_center()
          .bg(withAlpha(t.accent, surf.dark ? .16 : .12))
          .font_family('monospace').text_size(11).font_medium().text_color(t.accent)
          .child(`+${fv.extraCount}`))
        .child(this.icon('expand', 9.5).text_color(data.foldersOpen ? t.muted : t.dim)));
    const foldersTrigger = div().flex_1().min_w(0).flex().items_center()
      .child(keepPress(tipWrap('pm-header-folders', foldersPillEl, fv.tooltip || '', { placement: 'below-left', flexNone: false }), this.keyFocus));
    return bar
      .child(div().flex_none().text_size(15).font_semibold().child(data.title))
      .when(Boolean(renameBtn), el => el.child(renameBtn))
      .child(foldersTrigger)
      .when(Boolean(pmCtxEl), el => el.child(pmCtxEl))
      .when(Boolean(data.errorTip), el => el.child(tipWrap('read-error', div().id('read-error').text_color(t.blocked)
        .child('!'), data.errorTip, { wrap: true, flexNone: true })))
      .child(keepPress(h_flex().id('pm-header-controls').gap(4).items_center(), this.keyFocus)
        .child(boardBtn)
        .child(searchBtn)
        .child(bell)
        .child(pmControl)
        .child(panelBtn))
      .when(Boolean(winControls), el => el.child(winControls));
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
      } else if ((ks === 'cmd-k' || ks === 'ctrl-k' || ks === 'cmd-f' || ks === 'ctrl-f' || ks === '/') && s?.session) {
        this.emitHeaderAction('key', s.session, { keystroke: ks });
        cx.stop_propagation?.();
      }
    };
    if (!s || !s.hasPm || (activeRef?.pm && s.pmName && s.pmName !== activeRef.pm)) {
      const winControls = this.renderWindowControls(t, this.lang || 'en', { divider: false });
      return h_flex().id('pm-project-header-bar').size_full().bg(t.canvas)
        .when(Boolean(winControls), el => el.pr(14).items_center().justify_end().child(winControls))
        .track_focus(this.keyFocus).on_key_down(onKeyDown);
    }
    this.lang = s.lang || this.lang || 'en';
    return this.renderHeaderBar(s, {
      onRename: s.isRemote ? null : () => openOverlay({ mod: 'pm-dash', props: { dialog: 'rename', pm: s.pmName }, kind: 'dialog', width: 420, height: 224 }),
      onToggleFolders: () => this.emitHeaderAction('toggle-folders', s.session),
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
      onRename: this.machine ? null : () => openOverlay({ mod: 'pm-dash', props: { dialog: 'rename', pm: this.pmName }, kind: 'dialog', width: 420, height: 224 }),
      onToggleFolders: cx => this.toggleFoldersPopover(cx),
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

  // ---- Equal-status Workspace folders popover ----

  resetFoldersPopoverState() {
    this.foldersOpen = false;
    this.foldersLive = null;
    this.foldersLiveSlug = '';
    this.foldersLoading = false;
    this.foldersBusy = '';
    this.foldersError = '';
    this.foldersUnsupported = '';
    this.foldersEditingAlias = null;
    this.foldersConfirmRemove = null;
    this.foldersRemoteOpen = false;
    this.foldersRemotePath = '';
    this.foldersRemoteCheck = null;
    this.foldersRemotePicker = { open: false, loading: false, error: '', base: '', home: '', entries: [] };
  }

  toggleFoldersPopover(cx) {
    if (this.foldersOpen) {
      this.closeFoldersPopover(cx);
      return;
    }
    this.foldersOpen = true;
    this.foldersError = '';
    this.foldersEditingAlias = null;
    this.foldersConfirmRemove = null;
    this.foldersRemoteOpen = false;
    this.foldersRemoteCheck = null;
    this.foldersRemotePicker = { open: false, loading: false, error: '', base: '', home: '', entries: [] };
    this.refreshLiveFolders(cx);
    this.notifyPanes(cx, { shell: true, conv: true });
  }

  closeFoldersPopover(cx) {
    if (!this.foldersOpen) return;
    this.foldersOpen = false;
    this.foldersEditingAlias = null;
    this.foldersConfirmRemove = null;
    this.foldersRemoteOpen = false;
    this.foldersRemoteCheck = null;
    this.foldersRemotePicker = { ...this.foldersRemotePicker, open: false };
    this.foldersError = '';
    this.keyFocus?.focus?.();
    this.notifyPanes(cx, { shell: true, conv: true });
  }

  refreshLiveFolders(cx) {
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    if (!pm || !slug) return;
    this.foldersLoading = true;
    cx?.notify?.();
    cx?.spawn?.(async cx => {
      try {
        const r = await this.runProject(projectFoldersLsArgv(slug));
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            if (projectSlug(this.pm()) === slug && machine === this.machine) {
              this.foldersUnsupported = word(this.lang, 'remoteFoldersUnsupported', machine);
            }
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const parsed = JSON.parse(r.stdout || '{}');
        if (projectSlug(this.pm()) === slug && machine === this.machine && Array.isArray(parsed.folders)) {
          this.foldersLive = parsed.folders;
          this.foldersLiveSlug = slug;
          this.foldersUnsupported = '';
        }
      } catch (e) {
        if (projectSlug(this.pm()) === slug && machine === this.machine) {
          this.foldersError = String(e?.message || e).trim();
        }
      } finally {
        this.foldersLoading = false;
        cx.notify();
      }
    });
  }

  applyFoldersMutationResult(slug, folders, cx) {
    const nextList = Array.isArray(folders) ? folders : [];
    this.foldersLive = nextList;
    this.foldersLiveSlug = slug;
    if (Array.isArray(this.state?.pms)) {
      this.state.pms = this.state.pms.map(item => {
        if (projectSlug(item) !== slug) return item;
        return {
          ...item,
          folders: nextList,
          repo: nextList[0]?.path || '',
          repo_ok: true,
        };
      });
    }
    this.dropCachePrefix(['repo/']);
    this.repoFilesRead = false;
    this.repoFilesSig = '';
    this.foldersError = '';
    this.foldersUnsupported = '';
    this.refresh(cx);
    this.readRepoFiles(cx);
    this.refreshLiveFolders(cx);
    this.notifyPanes(cx, { shell: true, conv: true, side: true });
  }

  addWorkspaceFolder(rawPath, cx, { clearRemote = false } = {}) {
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    const folderPath = String(rawPath || '').trim();
    if (!pm || !slug || !folderPath || this.foldersBusy) return;
    this.foldersBusy = 'add';
    this.foldersError = '';
    cx?.notify?.();
    cx?.spawn?.(async cx => {
      try {
        const r = await this.runProjectWrite(projectFoldersAddArgv(slug, folderPath));
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.foldersUnsupported = word(this.lang, 'remoteFoldersUnsupported', machine);
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const parsed = JSON.parse(r.stdout || '{}');
        if (projectSlug(this.pm()) === slug && machine === this.machine) {
          if (clearRemote) {
            this.foldersRemotePath = '';
            this.folderRemoteInput?.set_value?.('');
            this.foldersRemoteCheck = null;
            this.foldersRemoteOpen = false;
            this.foldersRemotePicker = { ...this.foldersRemotePicker, open: false };
          }
          this.applyFoldersMutationResult(slug, parsed.folders, cx);
        }
      } catch (e) {
        if (projectSlug(this.pm()) === slug && machine === this.machine) {
          this.foldersError = String(e?.message || e).trim();
        }
      } finally {
        this.foldersBusy = '';
        cx.notify();
      }
    });
  }

  chooseLocalFolder(cx) {
    if (typeof pickFolder !== 'function' || this.foldersBusy) return;
    cx?.spawn?.(async cx => {
      try {
        const picked = await pickFolder({ prompt: word(this.lang, 'addFolder').replace(/[….]$/, '') });
        if (picked) this.addWorkspaceFolder(picked, cx);
      } catch (e) {
        this.foldersError = String(e?.message || e).trim();
        cx.notify();
      }
    });
  }

  requestRemoveFolder(folder, cx) {
    if (!folder || this.foldersBusy) return;
    const active = activeThreadsInFolder(this.projectTasks(), folder);
    if (active.length > 0) {
      this.foldersConfirmRemove = { alias: folder.alias, path: folder.path, count: active.length };
      this.foldersEditingAlias = null;
      this.foldersError = '';
      cx?.notify?.();
      return;
    }
    this.removeWorkspaceFolder(folder, { force: false }, cx);
  }

  removeWorkspaceFolder(folder, { force = false } = {}, cx) {
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    if (!pm || !slug || !folder || this.foldersBusy) return;
    const target = folder.alias || folder.path;
    this.foldersBusy = `remove:${target}`;
    this.foldersError = '';
    cx?.notify?.();
    cx?.spawn?.(async cx => {
      try {
        const r = await this.runProjectWrite(projectFoldersRemoveArgv(slug, target, { force }));
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.foldersUnsupported = word(this.lang, 'remoteFoldersUnsupported', machine);
            return;
          }
          const errText = (r.stderr || r.stdout || `pm.py: ${r.code}`).trim();
          if (!force && /--force/i.test(errText)) {
            const countMatch = /(\d+)\s+(?:active|个进行中)/.exec(errText);
            this.foldersConfirmRemove = {
              alias: folder.alias,
              path: folder.path,
              count: countMatch ? Number(countMatch[1]) : 1,
            };
            return;
          }
          throw new Error(errText.split('\n').pop());
        }
        const parsed = JSON.parse(r.stdout || '{}');
        if (projectSlug(this.pm()) === slug && machine === this.machine) {
          this.foldersConfirmRemove = null;
          this.applyFoldersMutationResult(slug, parsed.folders, cx);
        }
      } catch (e) {
        if (projectSlug(this.pm()) === slug && machine === this.machine) {
          this.foldersError = String(e?.message || e).trim();
        }
      } finally {
        this.foldersBusy = '';
        cx.notify();
      }
    });
  }

  startRenameFolderAlias(folder, cx) {
    if (!folder || this.foldersBusy) return;
    const current = String(folder.alias || '');
    this.foldersConfirmRemove = null;
    this.foldersError = '';
    this.foldersEditingAlias = { target: current, original: current, value: current };
    this.folderAliasInput?.set_value?.(current);
    cx?.timer?.after?.(0, () => this.folderAliasInput?.focus?.());
    cx?.notify?.();
  }

  commitRenameFolderAlias(cx) {
    const ed = this.foldersEditingAlias;
    const pm = this.pm(), slug = projectSlug(pm), machine = this.machine;
    if (!ed || !pm || !slug || this.foldersBusy) return;
    const nextAlias = String(this.folderAliasInput?.value?.() ?? ed.value ?? '').trim();
    if (!nextAlias || nextAlias === ed.original) {
      this.foldersEditingAlias = null;
      this.keyFocus?.focus?.();
      cx?.notify?.();
      return;
    }
    this.foldersBusy = `rename:${ed.target}`;
    this.foldersError = '';
    cx?.notify?.();
    cx?.spawn?.(async cx => {
      try {
        const r = await this.runProjectWrite(projectFoldersRenameAliasArgv(slug, ed.target, nextAlias));
        if (r.code !== 0) {
          if (machine && isOldPmCommand(r)) {
            this.foldersUnsupported = word(this.lang, 'remoteFoldersUnsupported', machine);
            return;
          }
          throw new Error((r.stderr || r.stdout || `pm.py: ${r.code}`).trim().split('\n').pop());
        }
        const parsed = JSON.parse(r.stdout || '{}');
        if (projectSlug(this.pm()) === slug && machine === this.machine) {
          this.foldersEditingAlias = null;
          this.keyFocus?.focus?.();
          this.applyFoldersMutationResult(slug, parsed.folders, cx);
        }
      } catch (e) {
        if (projectSlug(this.pm()) === slug && machine === this.machine) {
          this.foldersError = String(e?.message || e).trim();
        }
      } finally {
        this.foldersBusy = '';
        cx.notify();
      }
    });
  }

  probeRemoteFolderPath(rawPath, cx, { addIfExists = false } = {}) {
    const machine = this.machine;
    const trimmed = String(rawPath || '').trim();
    if (!machine || !trimmed) return;
    this.foldersRemoteCheck = { raw: trimmed, exists: false, path: trimmed, git: false, branch: '', checking: true, creating: false };
    this.foldersError = '';
    cx?.notify?.();
    cx?.spawn?.(async cx => {
      try {
        const r = await exec('sh', ['-c', REMOTE_PROBE_SH, 'sh', trimmed], { on: machine, timeout: 5000 });
        if (r.code !== 0) throw new Error((r.stderr || r.stdout || `probe: ${r.code}`).trim().split('\n').pop());
        const parsed = parseRemoteProbe(r.stdout);
        const dir = parsed.dirs[0] || { exists: false, raw: trimmed, path: trimmed, git: false, branch: '' };
        if (dir.exists) {
          if (addIfExists) {
            this.foldersRemoteCheck = null;
            this.addWorkspaceFolder(dir.path, cx, { clearRemote: true });
          } else {
            this.foldersRemoteCheck = { ...dir, checking: false, creating: false };
          }
        } else {
          this.foldersRemoteCheck = { ...dir, exists: false, checking: false, creating: false };
        }
      } catch (e) {
        this.foldersRemoteCheck = null;
        this.foldersError = String(e?.message || e).trim();
      } finally {
        cx.notify();
      }
    });
  }

  createRemoteFolderPath(rawPath, cx) {
    const machine = this.machine;
    const target = String(rawPath || '').trim();
    if (!machine || !target || this.foldersRemoteCheck?.creating) return;
    this.foldersRemoteCheck = { ...(this.foldersRemoteCheck || { raw: target, path: target }), creating: true };
    this.foldersError = '';
    cx?.notify?.();
    cx?.spawn?.(async cx => {
      try {
        const r = await exec('sh', ['-c', REMOTE_MKDIR_SH, 'sh', target], { on: machine, timeout: 5000 });
        if (r.code !== 0) throw new Error((r.stderr || r.stdout || `mkdir: ${r.code}`).trim().split('\n').pop());
        const createdPath = r.stdout.trim() || this.foldersRemoteCheck?.path || target;
        this.foldersRemoteCheck = null;
        this.addWorkspaceFolder(createdPath, cx, { clearRemote: true });
      } catch (e) {
        if (this.foldersRemoteCheck) this.foldersRemoteCheck.creating = false;
        this.foldersError = String(e?.message || e).trim();
        cx.notify();
      }
    });
  }

  openRemoteFolderPicker(prefix, cx) {
    const machine = this.machine;
    if (!machine) return;
    this.foldersRemotePicker = { ...this.foldersRemotePicker, open: true, loading: true, error: '' };
    cx?.notify?.();
    cx?.spawn?.(async cx => {
      try {
        const target = String(prefix ?? (String(this.foldersRemotePath || '').trim() || '~'));
        const r = await exec('sh', ['-c', REMOTE_LIST_DIRS_SH, 'sh', target], { on: machine, timeout: 5000 });
        if (r.code !== 0) throw new Error((r.stderr || r.stdout || `ls: ${r.code}`).trim().split('\n').pop());
        const parsed = parseRemoteDirs(r.stdout);
        this.foldersRemotePicker = { open: true, loading: false, error: '', base: parsed.base, home: parsed.home, entries: parsed.entries };
      } catch (e) {
        this.foldersRemotePicker = { ...this.foldersRemotePicker, open: true, loading: false, error: String(e?.message || e).trim() };
      } finally {
        cx.notify();
      }
    });
  }

  renderFoldersPopover(pm, t, cx) {
    const lang = this.lang;
    const surf = tonalSurfaces(t);
    const slug = projectSlug(pm);
    const folders = (this.foldersLiveSlug === slug && Array.isArray(this.foldersLive))
      ? this.foldersLive
      : projectFolders(pm);
    const gitCount = folders.filter(f => f.git).length;
    const popoverBg = [t.popover, t.surface, t.raised].find(Boolean) || t.surface;
    const homeDir = home();
    const stop = (_e, clickCx) => clickCx?.stop_propagation?.();
    const parentOf = p => {
      const clean = String(p || '').replace(/\/+$/, '');
      if (!clean || clean === '/') return '/';
      const idx = clean.lastIndexOf('/');
      return idx <= 0 ? '/' : clean.slice(0, idx);
    };

    const rowEls = [];
    if (!folders.length) {
      rowEls.push(h_flex().id('folders-empty-row').h(38).px(10).gap(8).rounded(8).items_center().bg(surf.well)
        .child(this.icon('folder-plus', 14).text_color(t.dim))
        .child(div().flex_1().min_w(0).text_size(12).text_color(t.dim).child(word(lang, 'noFoldersLinked'))));
    } else {
      folders.forEach((f, idx) => {
        const isEditing = this.foldersEditingAlias?.target === f.alias;
        const isConfirming = this.foldersConfirmRemove?.alias === f.alias;
        const isBusy = this.foldersBusy === `remove:${f.alias}` || this.foldersBusy === `rename:${f.alias}`;
        const pathLabel = this.machine ? f.path : shortPath(f.path, homeDir);
        const badgeText = f.exists === false
          ? word(lang, 'folderMissing')
          : f.git
            ? (f.default_branch ? `git · ${f.default_branch}` : 'git')
            : word(lang, 'folderBadgeNonGit');

        const row = h_flex().id(`folder-row-${idx}`).min_h(34).px(8).py(4).gap(8).rounded(8).items_center()
          .bg(surf.well)
          .child(this.icon('folder', 13.5).text_color(f.exists === false ? t.blocked : t.muted))
          .when(isEditing, el => el
            .child(h_flex().flex_none().w(124).h(24).px(6).rounded(6).items_center()
              .bg(t.background).border_1().border_color(withAlpha(t.accent, .55))
              .child(Input.new(this.folderAliasInput).w_full().h(20).items_center().font_family('monospace').text_size(11.5).text_color(t.foreground)))
            .child(this.iconButton(`folder-alias-save-${idx}`, 'check', word(lang, 'saveEdit'),
              clickCx => this.commitRenameFolderAlias(clickCx), t, 12))
            .child(this.iconButton(`folder-alias-cancel-${idx}`, 'close', word(lang, 'cancel'),
              clickCx => { this.foldersEditingAlias = null; this.keyFocus?.focus?.(); clickCx.notify(); }, t, 11)))
          .when(!isEditing, el => el
            .child(this.withTip(`folder-alias-${idx}`,
              h_flex().id(`folder-alias-${idx}`).h(22).px(6.5).rounded(5.5).flex_none().items_center().cursor_pointer()
                .bg(surf.pillMuted).hover(s => s.bg(t.hover))
                .accessibility_label(word(lang, 'folderAliasRenameTip'))
                .on_click((_e, clickCx) => { clickCx.stop_propagation(); this.startRenameFolderAlias(f, clickCx); })
                .child(div().max_w(120).truncate().font_family('monospace').text_size(11.5).font_medium()
                  .text_color(t.foreground).child(f.alias)),
              word(lang, 'folderAliasRenameTip'), t, { placement: 'above-left' })))
          .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(11.5)
            .text_color(f.exists === false ? t.blocked : t.muted).child(pathLabel))
          .child(h_flex().h(20).px(6).rounded(5).flex_none().items_center()
            .bg(f.exists === false ? withAlpha(t.blocked, surf.dark ? .15 : .10) : surf.pillMuted)
            .font_family('monospace').text_size(10.5)
            .text_color(f.exists === false ? t.blocked : t.dim)
            .child(badgeText))
          .child(isBusy
            ? h_flex().size(24).flex_none().items_center().justify_center().child(svg(SPINNER).size(12).flex_none().spin(900))
            : this.withTip(`folder-remove-${idx}`,
              h_flex().id(`folder-remove-${idx}`).size(24).flex_none().rounded(6).items_center().justify_center()
                .cursor_pointer().text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
                .accessibility_label(word(lang, 'unlinkFolderTip'))
                .on_click((_e, clickCx) => { clickCx.stop_propagation(); this.requestRemoveFolder(f, clickCx); })
                .child(this.icon('close', 11.5)),
              word(lang, 'unlinkFolderTip'), t, { placement: 'above-right' }));

        rowEls.push(row);

        if (isConfirming) {
          rowEls.push(h_flex().id(`folder-remove-confirm-bar-${idx}`).px(10).py(6).gap(8).rounded(8).items_center()
            .bg(withAlpha(t.blocked, surf.dark ? .12 : .08))
            .child(div().flex_1().min_w(0).whitespace_normal().text_size(11.5).text_color(t.foreground)
              .child(word(lang, 'unlinkFolderActiveWarn', f.alias, this.foldersConfirmRemove.count)))
            .child(h_flex().id(`folder-remove-cancel-${idx}`).h(22).px(8).rounded(6).flex_none().items_center()
              .cursor_pointer().bg(surf.well).hover(s => s.bg(t.hover))
              .text_size(11.5).text_color(t.muted)
              .on_click((_e, clickCx) => { clickCx.stop_propagation(); this.foldersConfirmRemove = null; clickCx.notify(); })
              .child(word(lang, 'cancel')))
            .child(h_flex().id(`folder-remove-confirm-${idx}`).h(22).px(8).rounded(6).flex_none().items_center()
              .cursor_pointer().bg(t.blocked).hover(s => s.opacity(.9))
              .text_size(11.5).font_medium().text_color(solidText(t.blocked, t))
              .on_click((_e, clickCx) => { clickCx.stop_propagation(); this.removeWorkspaceFolder(f, { force: true }, clickCx); })
              .child(word(lang, 'unlinkAnyway'))));
        }
      });
    }

    const remotePanel = (this.machine && this.foldersRemoteOpen) ? v_flex().id('folder-remote-add-panel').gap(6).pt(2)
      .child(h_flex().gap(6).items_center()
        .child(div().relative().flex_1().min_w(0).h(28).px(8).rounded(7).bg(surf.well).border_1()
          .border_color(this.typing === 'folderRemote' ? withAlpha(t.accent, .5) : surf.hairline)
          .flex().items_center()
          .when(!this.foldersRemotePath, el => el.child(div().absolute().left(8).right(8).truncate()
            .text_size(11.5).text_color(t.dim).child(word(lang, 'enterRemotePath', this.machine))))
          .child(Input.new(this.folderRemoteInput).w_full().h(22).items_center().font_family('monospace').text_size(11.5).text_color(t.foreground)))
        .child(h_flex().id('folder-remote-browse').h(28).px(9).gap(4).rounded(7).flex_none().items_center()
          .cursor_pointer().bg(surf.softChip).hover(s => s.bg(t.hover))
          .text_size(11.5).text_color(t.muted)
          .on_click((_e, clickCx) => { clickCx.stop_propagation(); this.openRemoteFolderPicker(this.foldersRemotePath || '~', clickCx); })
          .child(word(lang, 'browseRemote', this.machine)))
        .child(h_flex().id('folder-remote-add').h(28).px(10).rounded(7).flex_none().items_center()
          .cursor_pointer().bg(withAlpha(t.accent, surf.dark ? .22 : .14)).hover(s => s.bg(withAlpha(t.accent, .28)))
          .text_size(11.5).font_medium().text_color(t.accent)
          .on_click((_e, clickCx) => { clickCx.stop_propagation(); this.probeRemoteFolderPath(this.foldersRemotePath, clickCx, { addIfExists: true }); })
          .child(word(lang, 'addBtn'))))
      .when(Boolean(this.foldersRemoteCheck && !this.foldersRemoteCheck.checking && !this.foldersRemoteCheck.exists), el => el
        .child(h_flex().id('folder-remote-missing').px(9).py(6).gap(8).rounded(7).items_center()
          .bg(withAlpha(t.ansi3 || t.blocked, surf.dark ? .12 : .09))
          .child(div().flex_1().min_w(0).truncate().text_size(11.5).text_color(t.foreground)
            .child(word(lang, 'folderNotFoundRemote', this.machine)))
          .child(h_flex().id('folder-remote-create').h(22).px(8).rounded(6).flex_none().items_center()
            .cursor_pointer().bg(surf.softChip).hover(s => s.bg(t.hover))
            .text_size(11.5).font_medium().text_color(t.foreground)
            .on_click((_e, clickCx) => { clickCx.stop_propagation(); this.createRemoteFolderPath(this.foldersRemoteCheck.raw || this.foldersRemotePath, clickCx); })
            .child(word(lang, 'createRemoteFolder')))))
      .when(Boolean(this.foldersRemotePicker?.open), el => {
        const pk = this.foldersRemotePicker;
        return v_flex().id('folder-remote-picker').rounded(8).p(6).gap(4).bg(surf.well).border_1().border_color(surf.hairline)
          .child(h_flex().h(24).px(4).gap(6).items_center()
            .when(Boolean(pk.base && pk.base !== '/'), row => row
              .child(h_flex().id('folder-remote-up').h(20).px(6).rounded(5).flex_none().items_center()
                .cursor_pointer().bg(surf.pillMuted).hover(s => s.bg(t.hover))
                .font_family('monospace').text_size(11).text_color(t.muted)
                .on_click((_e, clickCx) => { clickCx.stop_propagation(); this.openRemoteFolderPicker(parentOf(pk.base), clickCx); })
                .child('..')))
            .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(11).text_color(t.dim).child(pk.base || '~'))
            .child(this.iconButton('folder-remote-picker-close', 'close', word(lang, 'close'),
              clickCx => { this.foldersRemotePicker = { ...pk, open: false }; clickCx.notify(); }, t, 11)))
          .when(pk.loading, row => row.child(h_flex().px(6).py(4).gap(6).items_center().text_size(11.5).text_color(t.dim)
            .child(svg(SPINNER).size(11).spin(900)).child('…')))
          .when(Boolean(pk.error), row => row.child(div().px(6).py(4).text_size(11.5).text_color(t.blocked).child(pk.error)))
          .when(!pk.loading && !pk.error, row => row.child(v_flex().max_h(150).gap(2).overflow_y_scrollbar()
            .children((pk.entries || []).slice(0, 40).map((ent, j) => h_flex().id(`folder-remote-entry-${j}`)
              .h(26).px(6).gap(6).rounded(6).items_center().hover(s => s.bg(t.hover))
              .child(h_flex().flex_1().min_w(0).gap(6).items_center().cursor_pointer()
                .on_click((_e, clickCx) => { clickCx.stop_propagation(); this.openRemoteFolderPicker(ent.path, clickCx); })
                .child(this.icon('folder', 12.5).text_color(t.muted))
                .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(11.5).text_color(t.foreground).child(ent.name)))
              .when(ent.git, badge => badge.child(div().flex_none().px(5).h(18).rounded(4).bg(surf.pillMuted)
                .flex().items_center().font_family('monospace').text_size(10).text_color(t.dim)
                .child(ent.branch ? `git · ${ent.branch}` : 'git')))
              .child(h_flex().id(`folder-remote-pick-${j}`).h(20).px(6).rounded(5).flex_none().items_center()
                .cursor_pointer().bg(surf.softChip).hover(s => s.bg(t.hover))
                .text_size(11).text_color(t.foreground)
                .on_click((_e, clickCx) => { clickCx.stop_propagation(); this.addWorkspaceFolder(ent.path, clickCx, { clearRemote: true }); })
                .child(word(lang, 'addBtn')))))));
      }) : null;

    const errMsg = this.foldersUnsupported || this.foldersError;
    const addLabel = this.machine ? word(lang, 'addFolderOn', this.machine) : word(lang, 'addFolder');
    const popW = Math.min(460, Math.max(300, (this.viewWidth || 640) - 48));

    return div().id('pm-folders-overlay').absolute().inset(0)
      .child(div().id('pm-folders-backdrop').absolute().inset(0)
        .on_mouse_down('left', (_e, clickCx) => { clickCx.stop_propagation(); this.closeFoldersPopover(clickCx); }))
      .child(v_flex().id('pm-folders-popover').absolute().top(this.bodyOnly ? 6 : 52).left(24)
        .w(popW).rounded(12).p(12).gap(8).bg(popoverBg).border_1().border_color(surf.hairline).shadow_lg()
        .on_mouse_down('left', stop)
        .child(h_flex().w_full().min_w(0).gap(8).items_center().justify_between()
          .child(h_flex().gap(6).items_center()
            .child(div().text_size(12.5).font_semibold().text_color(t.foreground)
              .child(word(lang, 'workspaceFolders', folders.length)))
            .when(this.foldersLoading, el => el.child(svg(SPINNER).size(11).flex_none().spin(900))))
          .child(div().min_w(0).truncate().text_size(11).text_color(t.dim)
            .child(word(lang, 'workspaceFoldersSub'))))
        .child(v_flex().id('pm-folders-list').w_full().gap(4).children(rowEls))
        .when(Boolean(remotePanel), el => el.child(remotePanel))
        .when(Boolean(errMsg), el => el.child(h_flex().id('pm-folders-error').px(8).py(5).gap(6).rounded(7).items_center()
          .bg(withAlpha(t.blocked, surf.dark ? .14 : .09))
          .child(div().flex_1().min_w(0).whitespace_normal().text_size(11.5).text_color(t.blocked).child(errMsg))
          .child(this.iconButton('pm-folders-err-close', 'close', word(lang, 'dismissNotice'),
            clickCx => { this.foldersError = ''; clickCx.notify(); }, t, 11))))
        .child(h_flex().w_full().min_w(0).pt(2).gap(8).items_center().justify_between()
          .child(gitCount >= 2
            ? div().flex_1().min_w(0).truncate().font_family('monospace').text_size(10.5).text_color(t.dim)
              .child(word(lang, 'multiGitDispatchHint', gitCount))
            : div().flex_1())
          .child(h_flex().id('folder-add-btn').h(26).px(9).gap(5).rounded(7).flex_none().items_center()
            .cursor_pointer().bg(surf.softChip).hover(s => s.bg(t.hover))
            .text_size(12).font_medium().text_color(t.foreground)
            .on_click((_e, clickCx) => {
              clickCx.stop_propagation();
              if (this.machine) {
                this.foldersRemoteOpen = !this.foldersRemoteOpen;
                this.foldersError = '';
                if (this.foldersRemoteOpen) cx?.timer?.after?.(0, () => this.folderRemoteInput?.focus?.());
                clickCx.notify();
              } else {
                this.chooseLocalFolder(clickCx);
              }
            })
            .child(this.foldersBusy === 'add'
              ? svg(SPINNER).size(12).flex_none().spin(900)
              : this.icon('folder-plus', 13).text_color(t.muted))
            .child(addLabel))));
  }

  lostNotice(pm, t) {
    const lang = this.lang, lost = pm?.lost;
    const summary = lostSummary(lang, lost);
    const rawSteps = bringBackSteps(lang, lost, projectName(pm) || pm?.name);
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
        () => this.focusTerminal(pmTerm.address), t, 14)));
  }

  pmUndeliveredBar(text, t) {
    const lang = this.lang;
    const pmTerm = this.pmTerminal();
    const accent = t.ansi3 || t.blocked;
    return h_flex().id('pm-undelivered-bar').w_full().pl(14).pr(6).py(4).gap(10).rounded(12).items_center()
      .bg(t.surface).border_1().border_color(withAlpha(accent, .45))
      .child(div().size(6).flex_none().rounded_full().bg(accent))
      .child(div().flex_1().min_w(0).whitespace_normal().text_size(12.5).text_color(t.foreground).child(text))
      .when(Boolean(pmTerm), el => el.child(this.iconButton('pm-undelivered-open', 'terminal', word(lang, 'openPm'),
        () => this.focusTerminal(pmTerm.address), t, 14)));
  }

  pmBusyBar(busyView, t, cx) {
    const busy = Boolean(busyView.interrupting);
    const preemptBtn = this.withTip('pm-preempt-btn',
      h_flex().id('pm-preempt-btn').size(22).flex_none().rounded(6).items_center().justify_center()
        .text_color(t.muted)
        .accessibility_label(busyView.actionLabel)
        .when(!busy, el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(t.foreground))
          .on_click((_e, clickCx) => this.preemptAndSendMain(clickCx || cx)))
        .child(busy ? svg(SPINNER).size(12).flex_none().text_color(t.muted).spin(900) : this.icon('stop', 12)),
      busyView.actionLabel, t, { placement: 'above-right' });
    return h_flex().id('pm-busy-bar').w_full().pl(10).pr(4).py(2).gap(6).rounded(9).items_center()
      .bg(t.surface).border_1().border_color(t.border)
      .child(div().size(5).flex_none().rounded_full().bg(t.dim))
      .child(div().id('pm-busy-text').flex_1().min_w(0).truncate().text_size(11.5).text_color(t.dim)
        .child(busyView.text))
      .child(preemptBtn);
  }

  pmActionFeedbackBar(fb, t, cx) {
    const lang = this.lang;
    const isErr = fb.tone === 'error' || fb.tone === 'warn';
    const accent = fb.tone === 'error' ? t.blocked : fb.tone === 'warn' ? (t.ansi3 || t.blocked) : t.dim;
    return h_flex().id('pm-action-feedback-bar').w_full().pl(14).pr(6).py(4).gap(10).rounded(12).items_center()
      .bg(t.surface).border_1().border_color(isErr ? withAlpha(accent, .45) : t.border)
      .child(div().size(6).flex_none().rounded_full().bg(accent))
      .child(div().flex_1().min_w(0).whitespace_normal().text_size(12.5)
        .text_color(isErr ? t.foreground : t.dim).child(fb.text))
      .child(this.iconButton('pm-action-feedback-close', 'close', word(lang, 'close'),
        clickCx => { this.pmActionFeedback = null; this.notifyPanes(clickCx || cx, { shell: false, conv: true }); }, t, 12));
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

  // What a thread is now, as a mark (Plan B: crisp solid rings & smooth spinners, zero dashed jagged circles):
  // - waiting: coral-red ring + inner dot (bullseye)
  // - review: ice-blue double ring (outer arc spins while reviewer actively works; static ring + dot while awaiting verdict)
  // - working: amber partial-arc spinner over subtle ring (spins while worker/helper actively works)
  // - paused: muted circle with || pause bars
  // - parked (not started): fine solid muted ring (zero border_dashed)
  // - finished: emerald green circle-check
  // - offline: unplug icon
  threadMark(row, t) {
    const dark = isDarkTheme(t);
    const ring = (color, sz = 14, bw = 1.5) => h_flex().size(sz).flex_none().rounded_full().items_center().justify_center().border(bw).border_color(color);
    const trackColor = withAlpha(t.border, dark ? .52 : .7);
    const arcRing = (color, spin) => h_flex().relative().size(14).flex_none().items_center().justify_center()
      .child(div().size(14).rounded_full().border(1.25).border_color(trackColor))
      .child(svg(SPINNER).size(14).absolute().left(0).top(0).text_color(color).when(spin, s => s.spin(900)));
    if (row.group === 'review' || (row.group === 'working' && (row.reviewing || row.status === 'review'))) {
      if (row.reviewWorking) {
        return h_flex().relative().size(14).flex_none().items_center().justify_center()
          .child(div().size(14).rounded_full().border(1.25).border_color(withAlpha(t.accent, .28)))
          .child(svg(SPINNER).size(14).absolute().left(0).top(0).text_color(t.accent).spin(900))
          .child(div().size(4.5).rounded_full().bg(t.accent));
      }
      return ring(t.accent, 14, 1.4).child(div().size(4.5).rounded_full().bg(t.accent));
    }
    if (row.group === 'working') {
      const workColor = t.working ?? t.ansi3 ?? t.accent;
      return arcRing(row.working || row.postGate ? workColor : t.dim, Boolean(row.working));
    }
    if (row.group === 'offline') return this.icon('unplug', 13.5).text_color(t.dim);
    if (row.group === 'finished') return this.icon('check', 13.5).flex_none().text_color(t.ansi2 ?? t.done ?? t.accent);
    if (row.group === 'parked') {
      return div().size(11).flex_none().rounded_full().border(1.25).border_color(withAlpha(t.muted, dark ? .48 : .58));
    }
    if (row.group === 'paused') {
      return ring(t.dim, 13.5, 1.35).gap(2)
        .child(div().w(1.5).h(5).rounded(1).bg(t.dim))
        .child(div().w(1.5).h(5).rounded(1).bg(t.dim));
    }
    const c = this.toneColor(row.tone, t);
    return ring(c).child(div().size(5.5).rounded_full().bg(c));
  }

  agentStatusMark(status, t, role = '', { compact = false } = {}) {
    const workColor = t.working ?? t.ansi3 ?? t.accent;
    if (status === 'working') {
      if (compact) return div().size(6).flex_none().rounded_full().bg(role === 'review' ? t.accent : workColor);
      return svg(SPINNER).size(10).flex_none().text_color(role === 'review' ? t.accent : workColor).spin(900);
    }
    const sz = compact ? 6 : 6.5;
    if (status === 'blocked') return div().size(sz).flex_none().rounded_full().bg(t.blocked);
    if (status === 'done') return div().size(sz).flex_none().rounded_full().bg(t.ansi2 ?? t.done ?? t.accent);
    return div().size(sz).flex_none().rounded_full().border(1.4).border_color(t.dim);
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
    this.hoverShowTimer?.cancel?.();
    this.hoverShowTimer = null;
    this.hoverHideTimer?.cancel?.();
    this.hoverHideTimer = null;
    this.hoverPendingKey = '';
    const had = Boolean(this.hoverKey) || Boolean(this.hoverCardOver);
    this.hoverKey = '';
    this.hoverCardOver = '';
    if (had && cx?.notify && cx?.phase?.() !== 'render') cx.notify();
  }

  enterHover(key, cx) {
    this.hoverHideTimer?.cancel?.();
    this.hoverHideTimer = null;
    if (!key) return;
    if (this.hoverKey === key) {
      this.hoverShowTimer?.cancel?.();
      this.hoverShowTimer = null;
      this.hoverPendingKey = '';
      return;
    }
    if (this.hoverPendingKey === key && this.hoverShowTimer) return;
    this.hoverShowTimer?.cancel?.();
    this.hoverShowTimer = null;
    this.hoverPendingKey = key;
    const delay = this.hoverKey ? HOVER_CARD_SWAP_MS : HOVER_CARD_OPEN_MS;
    if (cx?.timer?.after) {
      this.hoverShowTimer = cx.timer.after(delay, tCx => {
        this.hoverShowTimer = null;
        if (this.hoverPendingKey === key) {
          this.hoverPendingKey = '';
          this.hoverKey = key;
          this.hoverCardOver = '';
          tCx?.notify?.();
        }
      }) || null;
    } else {
      this.hoverPendingKey = '';
      this.hoverKey = key;
      this.hoverCardOver = '';
      cx?.notify?.();
    }
  }

  leaveHover(key, cx) {
    if (!key) return;
    if (this.hoverPendingKey === key) {
      this.hoverShowTimer?.cancel?.();
      this.hoverShowTimer = null;
      this.hoverPendingKey = '';
    }
    if (this.hoverKey !== key || this.hoverCardOver === key) return;
    this.hoverHideTimer?.cancel?.();
    this.hoverHideTimer = cx.timer?.after?.(HOVER_CARD_LEAVE_MS, cx => {
      this.hoverHideTimer = null;
      if (this.hoverKey === key && this.hoverCardOver !== key) {
        this.hoverKey = '';
        cx.notify();
      }
    }) || null;
  }

  enterHoverCard(key, cx) {
    this.hoverShowTimer?.cancel?.();
    this.hoverShowTimer = null;
    this.hoverHideTimer?.cancel?.();
    this.hoverHideTimer = null;
    this.hoverPendingKey = '';
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
    const isReview = !showDeps && (row.group === 'review' || row.reviewing || row.status === 'review');
    const hasSteps = !showDeps && Boolean(steps?.steps?.length);
    const folderAlias = threadFolderBadge(row.folderAlias ? row : task, projectFolders(this.pm()));
    const metaParts = [
      row.closed ? word(lang, 'closedReattach') : (!(showDeps || hasSteps || isReview) ? status : ''),
      folderAlias,
      row.branch,
      task?.pane ? String(task.pane) : '',
      chip ? `${chip.label}${chip.up ? ' ↑' : ''}` : '',
      ctxLabel,
    ].filter(Boolean);
    const metaText = metaParts.join(' · ');
    const clean = cleanTaskLog(task?.latest);
    const rawLog = (row.latest || clean.text || '').replace(/\s+/g, ' ').trim();
    const isWorking = !row.offline && (row.group === 'working' || row.group === 'review');
    const firstUnmet = showDeps ? (deps.items || []).find(it => !it.isMet) : null;
    const firstUnmetRef = firstUnmet ? formatDepRef(firstUnmet, id => this.taskNumberFor(id)) : '';
    const depsCard = showDeps ? renderDepsCard({
      ui: { div, svg, h_flex, v_flex },
      deps, theme: t, lang, icons: STEP_ICONS,
      compact: true, framed: false,
      rowIdPrefix: `hover-dep-${row.task}`,
      titleText: numTag ? `${word(lang, 'depsTitle')} ${numTag}` : word(lang, 'depsTitle'),
      headerMeta: metaText,
      footerText: firstUnmetRef ? word(lang, 'depsAutoUnblock', firstUnmetRef) : '',
      onSelect: (dep, cx) => this.jumpToDependency(dep, cx),
    }) : null;
    const stepsCard = !depsCard && hasSteps ? renderStepsCard({
      ui: { div, svg, h_flex, v_flex },
      steps, theme: t, lang, icons: STEP_ICONS,
      compact: true, framed: false,
      titleText: numTag ? `${word(lang, 'planTitle')} ${numTag}` : word(lang, 'planTitle'),
      headerMeta: metaText,
      progressColor: isReview ? t.accent : (t.working ?? t.ansi3 ?? t.accent),
      hidePolicy: true,
      spinning: isWorking, reviewSpinning: Boolean(row.reviewWorking), subSpinning: isWorking,
    }) : null;
    const reviewHeader = !depsCard && !stepsCard && isReview ? h_flex().w_full().min_w(0).gap(6).items_center()
      .child(div().flex_none().text_size(12).font_semibold().text_color(t.foreground)
        .child(numTag ? `${word(lang, 'reviewTitle')} ${numTag}` : word(lang, 'reviewTitle')))
      .when(Boolean(row.branch), el => el.child(div().flex_1().min_w(0).truncate()
        .font_family('monospace').text_size(10.5).text_color(t.dim).child(`· ${row.branch}`)))
      .when(!row.branch, el => el.child(div().flex_1().min_w(0)))
      .when(Boolean(row.reviewModel || chip?.label), el => el.child(div().flex_none()
        .font_family('monospace').text_size(11).font_medium().text_color(t.accent)
        .child(row.reviewModel || chip.label))) : null;
    const hasBody = Boolean(depsCard || stepsCard || reviewHeader);
    if (!hasBody && !metaText && !rawLog) return null;
    return v_flex().w(308).px(12).py(10).gap(6).rounded(10)
      .bg(fill).border_1().border_color(t.border).shadow_lg()
      .when(Boolean(depsCard), card => card.child(depsCard))
      .when(Boolean(stepsCard), card => card.child(stepsCard))
      .when(Boolean(reviewHeader), card => card.child(reviewHeader))
      .when(!hasBody && Boolean(metaText), card => card.child(
        div().truncate().font_family('monospace').text_size(10.5).text_color(t.dim)
          .child(numTag ? `${numTag} · ${metaText}` : metaText),
      ))
      .when(Boolean(rawLog), card => card.child(
        div().when(Boolean(depsCard || stepsCard) || (!reviewHeader && Boolean(metaText)), el => el.pt(5).border_t(1).border_color(withAlpha(t.border, .6)))
          .child(div().whitespace_normal().text_size(11.5).line_height('16px')
            .text_color(reviewHeader ? t.foreground : t.muted).child(rawLog)),
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
    const modelInfo = (ag.modelBadge && ag.model && !ag.modelBadge.toLowerCase().includes(ag.model.toLowerCase()))
      ? `${ag.model} · ${ag.modelBadge}`
      : (ag.modelBadge || ag.model);
    const meta = [doing, state, modelInfo ? `${modelInfo}${ag.up ? ' ↑' : ''}` : '', ctxText].filter(Boolean).join(' · ');
    const summary = ag.ended && ag.summary ? ag.summary : '';
    const hint = word(lang, isOpen ? 'closeAgentWindow' : 'openAgentWindow');
    const headTitle = ag.displayName
      ? [ag.displayName, ag.actionLabel || ag.roleLabel, ag.role === 'helper' && ag.name && !ag.purpose ? ag.name : ''].filter(Boolean).join(' · ')
      : `${ag.roleLabel} · ${ag.name}`;
    return v_flex().w(268).px(11).py(9).gap(4).rounded(10)
      .bg(fill).border_1().border_color(t.border).shadow_lg()
      .child(div().truncate().font_family('monospace').text_size(11).text_color(t.accent).child(headTitle))
      .when(Boolean(meta), card => card.child(div().truncate().text_size(11.5).text_color(t.foreground).child(meta)))
      .when(Boolean(summary), card => card.child(div().text_size(11.5).line_height('16px').text_color(t.muted).max_h(48).overflow_hidden().child(summary)))
      .child(div().truncate().text_size(11).text_color(t.dim).child(hint));
  }

  // ---- In-Project floating agent small windows (openOverlay({ kind: 'window' })) ----------------

  agentWindowSlotPos(slot, width = 520) {
    const wide = this.viewWidth || 1280;
    const lay = this.currentSplitLayout();
    const panelW = (this.isPanelOpen() && lay.layoutKind === 'inline') ? lay.slotWidth : 0;
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
      displayName: entry.displayName || '',
      action: entry.action || '',
      actionLabel: entry.actionLabel || '',
      taskId: entry.taskId,
      threadNumber: entry.threadNumber || 0,
      targetId: entry.targetId,
      name: entry.name,
      threadTitle: entry.threadTitle,
      address: entry.address,
      appAddress: appAddr,
      model: entry.modelBadge || entry.model || '',
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
    this.winSent = [...(this.winSent || []).slice(-19), text];
    this.winInput.set_value('');
    this.winDraft = '';
    this.winSendError = '';
    cx.notify();
    cx.spawn(async cx => {
      try {
        // The terminal's address as the project's machine names it: pm.py runs there.
        await this.send(p.address, text, { task: p.taskId || '', wait: !p.taskId });
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
    const liveStatus = p.ended
      ? 'done'
      : (appAddr
        ? (liveAgent?.status || (liveTerm?.state === 'live' ? liveTerm?.status : '') || 'working')
        : 'idle');
    const winProgram = resolveAgentProgram(liveTerm, liveAgent, p.kind) || p.program || null;
    const meta = [p.model ? `${p.model}${p.up ? ' ↑' : ''}` : '', p.contextLabel || ''].filter(Boolean).join(' · ');
    const numTag = formatTaskNumber(p.threadNumber);
    const liveAction = p.action ? agentActionLabel(lang, p.action, liveStatus, { ended: Boolean(p.ended) }) : (p.actionLabel || '');
    const titleLabel = p.displayName
      ? (liveAction ? `${p.displayName} · ${liveAction}` : p.displayName)
      : (p.roleLabel && p.name ? `${p.roleLabel} · ${p.name}` : (p.name || p.roleLabel || 'agent'));
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

  renderSessionQuestionPart(part, t, lang, { prefix = 'session', compact = false } = {}) {
    const qs = Array.isArray(part.questions) && part.questions.length ? part.questions : [];
    const unanswered = !part.output;
    const textSize = compact ? 12 : 12.5;
    const optSize = compact ? 11.5 : 12;
    const subSize = compact ? 10.5 : 11;
    const card = v_flex().id(`${prefix}-question-${part.key}`).w_full().px(10).py(8).gap(6).rounded(8)
      .bg(t.surface).border_1().border_color(unanswered ? t.blocked : t.border);
    card.child(h_flex().w_full().gap(6).items_center()
      .child(div().flex_none().size(6).rounded(3).bg(unanswered ? t.blocked : t.dim))
      .child(div().text_size(subSize).font_semibold().text_color(unanswered ? t.blocked : t.muted)
        .child(word(lang, 'sessionQuestionLabel')))
      .child(div().flex_1().min_w(0).truncate().font_family('monospace').text_size(subSize).text_color(t.dim)
        .child(part.name || 'AskUserQuestion')));
    qs.forEach((q, qi) => {
      const qBox = v_flex().id(`${prefix}-question-${part.key}-${qi}`).w_full().gap(4);
      if (q.header) {
        qBox.child(div().w_full().whitespace_normal().text_size(textSize).font_semibold().text_color(t.foreground)
          .child(q.header));
      }
      if (q.question && q.question !== q.header) {
        qBox.child(div().w_full().whitespace_normal().text_size(textSize).text_color(t.foreground)
          .child(q.question));
      }
      if (Array.isArray(q.options) && q.options.length > 0) {
        const optList = v_flex().w_full().gap(3).pl(2);
        q.options.forEach((opt, oi) => {
          optList.child(v_flex().id(`${prefix}-question-opt-${part.key}-${qi}-${oi}`).w_full().px(8).py(4).gap(1)
            .rounded(6).bg(t.raised)
            .child(div().w_full().whitespace_normal().text_size(optSize).font_medium().text_color(t.foreground)
              .child(`${oi + 1}. ${opt.label}`))
            .when(Boolean(opt.description), el => el.child(div().w_full().whitespace_normal()
              .text_size(subSize).text_color(t.dim).child(opt.description))));
        });
        qBox.child(optList);
      }
      card.child(qBox);
    });
    if (part.output) {
      card.child(div().id(`${prefix}-question-out-${part.key}`).w_full().pt(4).border_t(1).border_color(t.border)
        .whitespace_normal().text_size(subSize).text_color(part.error ? t.blocked : t.dim)
        .child(`${word(lang, 'sessionQuestionAnswered')}: ${part.output}`));
    } else {
      card.child(div().id(`${prefix}-question-hint-${part.key}`).w_full().pt(2)
        .whitespace_normal().text_size(subSize).text_color(t.dim)
        .child(word(lang, 'sessionQuestionTerminalHint')));
    }
    return card;
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
            if (part.kind === 'question') {
              return this.renderSessionQuestionPart(part, t, lang, { prefix: 'win', compact: true });
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
    if (this.panelHideTimer) { this.panelHideTimer.cancel?.(); this.panelHideTimer = null; }
    if (this.panelTransitionTimer) { this.panelTransitionTimer.cancel?.(); this.panelTransitionTimer = null; }
    if (this._sideFadeTimer) { this._sideFadeTimer.cancel?.(); this._sideFadeTimer = null; }
    if (this.hoverShowTimer) { this.hoverShowTimer.cancel?.(); this.hoverShowTimer = null; }
    if (this.hoverHideTimer) { this.hoverHideTimer.cancel?.(); this.hoverHideTimer = null; }
    if (this._paneOwnerId) {
      PANE_OWNERS.delete(this._paneOwnerId);
      this._paneOwnerId = '';
    }
    try { this._convEntity?.release?.(); } catch (_) { /* already released */ }
    try { this._sideEntity?.release?.(); } catch (_) { /* already released */ }
    this._convEntity = null;
    this._sideEntity = null;
    this.releaseAllTabHandles?.();
    try { this.tabStripScroll?.release?.(); } catch (_) { /* already released */ }
  }

  // The threads the open task was split into, under its status: a row each (its mark, its title,
  // its status), opening that thread as a row of the thread list does. Past PARTS_LIMIT the rest
  // fold behind an expand mark with how many more; opened, they scroll in a box of their own and a
  // collapse mark folds them again, so the log keeps its room.
  partsList(parts, t) {
    const lang = this.lang, open = this.partsOpen === this.thread;
    const surf = tonalSurfaces(t);
    const { shown, more } = foldParts(parts, open);
    const rows = shown.map(row => {
      const gone = row.offline && row.group !== 'offline' ? (row.closed ? closedTip(lang, row.closed) : word(lang, 'disconnected'))
        : (row.closed ? closedTip(lang, row.closed) : '');
      const label = statusLabel(lang, row.status, row.cleanup, row.offline, row.answered, Boolean(row.closed));
      const numText = formatTaskNumber(taskNumber(row) || this.taskNumberFor(row.task));
      const ctxText = contextLabel(lang, row.contextTokens), ctxCompact = contextShort(row.contextTokens);
      const tip = [label, gone, ctxText, numText ? `${numText} ${row.title}` : row.title].filter(Boolean).join(' · ');
      return this.withTip(`part-${row.task}`, h_flex().id(`part-${row.task}`).h(28).px(6).gap(7).rounded(6).items_center().cursor_pointer()
        .hover(s => s.bg(t.hover)).accessibility_label(tip)
        .on_click((_e, cx) => this.openThread(row.task, cx, { insertAdjacent: true }))
        .child(h_flex().w(16).flex_none().items_center().justify_center().child(this.threadMark(row, t)))
        .when(Boolean(numText), el => el.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(numText)))
        .child(div().flex_1().min_w(0).truncate().text_size(12.5)
          .text_color(['parked', 'paused', 'offline', 'finished'].includes(row.group) ? t.muted : t.foreground).child(row.title))
        .when(Boolean(ctxCompact), el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(ctxCompact)))
        .child(div().flex_none().text_size(11).text_color(t.dim).child(label)), tip, t, { panel: true, placement: 'above-left' });
    });
    const toggle = (id, mark, tip, value) => this.withTip(id, h_flex().id(id).h(24).px(6).gap(7).rounded(6).items_center().cursor_pointer()
      .text_size(11.5).text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
      .accessibility_label(tip)
      .on_click((_e, cx) => { this.partsOpen = value; cx.notify(); })
      .child(h_flex().w(16).flex_none().items_center().justify_center().child(this.icon(mark, 13)))
      .when(Boolean(more), el => el.child(div().child(tip))), tip, t, { panel: true, placement: 'above-left' });
    const folding = open && parts.length > PARTS_LIMIT;
    const rowsBox = folding
      ? v_flex().id('thread-parts').w_full().min_w(0).max_h(30 * PARTS_LIMIT).p(3).gap(1.5).rounded(6).bg(surf.podWell).overflow_y_scrollbar().children(rows)
      : v_flex().id('thread-parts').w_full().min_w(0).p(3).gap(1.5).rounded(6).bg(surf.podWell).children(rows);
    return v_flex().id('thread-parts-card').w_full().min_w(0).flex_none().rounded(10).p(8).gap(6).bg(surf.pod)
      .child(h_flex().w_full().min_w(0).pl(4).pr(4).gap(6).items_center()
        .child(div().text_size(11.5).font_semibold().text_color(t.muted).child(word(lang, 'subThreads')))
        .child(div().font_family('monospace').text_size(11).text_color(t.dim).child(String(parts.length))))
      .child(rowsBox)
      .when(more > 0, el => el.child(toggle('parts-more', 'expand', word(lang, 'moreParts', more), this.thread)))
      .when(folding, el => el.child(toggle('parts-fold', 'collapse', word(lang, 'fold'), '')));
  }

  // The panel at rest: Plan B Tonal Craft — merged frameless topbar, tonal concentric pods (no tree wires),
  // crisp solid rings & spinners, inline single-worker + flex-wrap multi-agent identity chips, and calm hover cards.
  threadsPanel(pm, t, width) {
    this.agentWindows = this.agentWindows || [];
    this.epicOverrides = this.epicOverrides || new Map();
    this.expandedDone = this.expandedDone || new Set();
    const lang = this.lang;
    const surf = tonalSurfaces(t);
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
    const lead = el => h_flex().w(16).flex_none().items_center().justify_center().child(el);
    const openBadge = () => h_flex().h(18).px(5.5).rounded(5).flex_none().items_center()
      .bg(withAlpha(t.accent, surf.dark ? .14 : .12))
      .text_size(10.5).font_medium().text_color(t.accent)
      .child(word(lang, 'sideTabOpened'));
    const reviewPill = () => h_flex().h(18).px(5.5).rounded(5).flex_none().items_center()
      .bg(withAlpha(t.accent, surf.dark ? .10 : .09))
      .text_size(10.5).text_color(t.accent)
      .child(word(lang, 'reviewBadge'));

    const agentChip = (ag, dimmed = false, { wrapHover = false } = {}) => {
      const open = agentWindowOpen(this.agentWindows, ag.key);
      const hoverKey = `agent:${ag.key}`;
      const hovered = this.hoverKey === hoverKey;
      const primaryName = ag.displayName || ag.roleLabel;
      const actionText = ag.actionLabel || '';
      const hasCustomHelperSlug = ag.role === 'helper' && Boolean(ag.nameSuffix) && !ag.purpose && ag.nameSuffix !== ag.roleLabel;
      const modelText = ag.modelBadge || ag.model || '';
      const accLabel = [primaryName, actionText, hasCustomHelperSlug ? ag.nameSuffix : '', modelText].filter(Boolean).join(' · ');
      const chip = h_flex().id(`agent-row-${ag.key}`).h(22).px(7).gap(4.5).rounded(5.5).flex_none().max_w_full()
        .items_center().cursor_pointer()
        .when(open, el => el.bg(surf.chipOpen).border_1().border_color(surf.chipOpenBorder))
        .when(!open, el => el.bg(surf.chip).hover(s => s.bg(surf.chipHover)))
        .when(dimmed || ag.ended, el => el.opacity(.78))
        .accessibility_label(accLabel)
        .on_hover((over, cx) => {
          if (over) this.enterHover(hoverKey, cx);
          else this.leaveHover(hoverKey, cx);
        })
        .on_click((_e, cx) => {
          cx.stop_propagation();
          this.clearHoverNow(cx);
          this.toggleAgentSmallWindow(ag, cx);
        })
        .child(h_flex().w(8).flex_none().items_center().justify_center().child(this.agentStatusMark(ag.status, t, ag.role, { compact: true })))
        .child(this.agentProgramIcon(ag.program, 11, t, dimmed || ag.ended))
        .child(div().flex_none().text_size(11)
          .text_color(open ? t.foreground : dimmed || ag.ended ? t.muted : t.foreground)
          .when(!dimmed && !ag.ended, x => x.font_medium())
          .child(primaryName))
        .when(Boolean(actionText), el => el
          .child(div().flex_none().text_size(10.5).text_color(t.dim).child('·'))
          .child(div().flex_none().text_size(11)
            .text_color(open ? t.accent : dimmed || ag.ended ? t.dim : t.muted)
            .child(actionText)))
        .when(hasCustomHelperSlug, el => el
          .child(div().flex_none().text_size(10.5).text_color(t.dim).child('·'))
          .child(div().flex_none().max_w(96).truncate().text_size(10.5)
            .text_color(open ? t.foreground : t.dim)
            .child(ag.nameSuffix)))
        .when(Boolean(modelText), el => el
          .child(div().flex_none().text_size(10.5).text_color(t.dim).child('·'))
          .child(div().flex_none().max_w(96).truncate().font_family('monospace').text_size(10.5)
            .text_color(open ? t.accent : t.dim)
            .child(modelText)))
        .when(open || hovered, el => el.child(this.icon('window-pop', 10.5).flex_none().text_color(t.accent)));
      return wrapHover ? this.wrapHoverCard(hoverKey, chip, () => this.agentHoverCard(ag, open, t, lang), t) : chip;
    };

    const doneFoldRow = (foldId, count, expanded, onToggle) => h_flex().id(foldId).h(22).px(6).gap(5).rounded(5)
      .items_center().cursor_pointer().text_size(11).text_color(t.dim).opacity(.88)
      .hover(s => s.bg(t.hover).text_color(t.muted).opacity(1))
      .on_click((_e, cx) => { cx.stop_propagation(); this.clearHoverNow(null); onToggle(cx); })
      .child(this.icon(expanded ? 'expand' : 'chevron', 10).text_color(t.dim))
      .child(word(lang, 'foldedDone', count));

    const summaryPills = (s, epicId) => {
      if (!s) return null;
      const items = [];
      const workColor = t.working ?? t.ansi3 ?? t.accent;
      const doneColor = t.ansi2 ?? t.done ?? t.dim;
      if (s.waiting > 0) items.push({ key: 'waiting', color: t.blocked, solid: true, count: s.waiting, bg: withAlpha(t.blocked, .14), active: true });
      if (s.review > 0) items.push({ key: 'review', color: t.accent, solid: true, count: s.review, bg: withAlpha(t.accent, .12), active: true });
      if (s.working > 0) items.push({ key: 'working', color: workColor, solid: true, count: s.working, bg: withAlpha(workColor, .12), active: true });
      if (s.offline > 0) items.push({ key: 'offline', color: t.dim, solid: true, count: s.offline, bg: surf.well, active: false });
      const queued = (s.paused || 0) + (s.parked || 0);
      if (queued > 0) items.push({ key: 'queued', color: t.muted, solid: false, count: queued, bg: surf.well, active: false });
      if (s.done > 0) items.push({ key: 'done', color: doneColor, solid: true, count: s.done, bg: surf.well, active: false });
      if (!items.length) return null;
      const allNeutral = items.every(it => !it.active);
      if (allNeutral && items.length > 1) {
        const segs = [];
        items.forEach((it, idx) => {
          if (idx > 0) segs.push(div().text_size(10).text_color(t.dim).child('·'));
          segs.push(h_flex().gap(3.5).items_center()
            .child(div().size(5.5).rounded_full()
              .when(it.solid, d => d.bg(it.color).when(it.key === 'done', x => x.opacity(.8)))
              .when(!it.solid, d => d.border(1.25).border_color(withAlpha(it.color, .65))))
            .child(div().font_family('monospace').text_size(10.5).text_color(t.muted).child(String(it.count))));
        });
        return h_flex().id(`epic-summary-${epicId}`).flex_none().h(18).px(6).gap(5).rounded(5.5).items_center()
          .bg(surf.well).children(segs);
      }
      return h_flex().id(`epic-summary-${epicId}`).flex_none().gap(4).items_center()
        .children(items.map(it => h_flex().h(18).px(5.5).gap(4).rounded(5.5).items_center().bg(it.bg)
          .font_family('monospace').text_size(10.5).font_medium().text_color(it.active ? it.color : t.muted)
          .child(div().size(5.5).rounded_full()
            .when(it.solid, d => d.bg(it.color).when(it.key === 'done', x => x.opacity(.8)))
            .when(!it.solid, d => d.border(1.25).border_color(withAlpha(it.color, .65))))
          .child(String(it.count))));
    };

    const openTabs = this.openTabKeys();
    const projFolders = projectFolders(pm);
    const folderPill = (id, alias) => h_flex().id(id).h(17).px(5).max_w(84).rounded(4.5).flex_none().items_center()
      .bg(surf.pillMuted)
      .child(div().min_w(0).truncate().font_family('monospace').text_size(10).text_color(t.muted).child(alias));
    const renderSingleThread = (node, { hideEndedFold = false, inEpic = false } = {}) => {
      const task = byId.get(node.task);
      const folderAlias = threadFolderBadge(node.folderAlias ? node : task, projFolders);
      const at = eventTime(node.updated);
      const ageText = at > 0 ? age(Math.max(0, now - at), lang) : '';
      const mutedTitle = ['parked', 'paused', 'offline', 'finished'].includes(node.group);
      const isReview = node.group === 'review' || (node.group === 'working' && (node.reviewing || node.status === 'review'));
      const pill = node.plan?.pill || '';
      const ctxLabel = node.contextTokens ? contextLabel(lang, node.contextTokens) : '';
      const numText = formatTaskNumber(taskNumber(node) || taskNumber(task) || this.taskNumberFor(node.task));
      const hoverKey = `task:${node.task}`;
      const litRow = this.highlightThread === node.task || this.hoverKey === hoverKey;
      const isOpened = openTabs.has(sideTabKey({ kind: 'thread', taskId: node.task }));

      const { inlineWorker, subAgents, ended: rawEnded } = threadAgentLayout(node.agents);
      const endedAgents = hideEndedFold ? [] : rawEnded;
      const hasSubChips = subAgents.length > 0;
      const inlineHoverKey = inlineWorker ? `agent:${inlineWorker.key}` : '';
      const inlineOpen = Boolean(inlineWorker && agentWindowOpen(this.agentWindows, inlineWorker.key));
      const inlineHovered = Boolean(inlineHoverKey && this.hoverKey === inlineHoverKey);
      let inlineChipEl = null;
      if (inlineWorker) {
        const badgeParts = inlineAgentBadgeParts(inlineWorker, width, { inEpic });
        const inlineTipLabel = [inlineWorker.displayName || inlineWorker.roleLabel, inlineWorker.actionLabel, inlineWorker.modelBadge || inlineWorker.model].filter(Boolean).join(' · ');
        inlineChipEl = h_flex()
          .id(`agent-inline-${inlineWorker.key}`)
          .h(20).px(6).gap(4).rounded(5.5).flex_none().items_center().cursor_pointer()
          .when(inlineOpen, el => el.bg(surf.chipOpen).border_1().border_color(surf.chipOpenBorder))
          .when(!inlineOpen, el => el.bg(surf.chip).hover(s => s.bg(surf.chipHover)))
          .accessibility_label(inlineTipLabel)
          .on_hover((over, cx) => {
            if (over) this.enterHover(inlineHoverKey, cx);
            else this.leaveHover(inlineHoverKey, cx);
          })
          .on_click((_e, cx) => {
            cx.stop_propagation();
            this.clearHoverNow(cx);
            this.toggleAgentSmallWindow(inlineWorker, cx);
          })
          .child(this.agentProgramIcon(inlineWorker.program, 11, t, false))
          .when(Boolean(badgeParts.name), el => el.child(div().flex_none().text_size(11).font_medium()
            .text_color(inlineOpen ? t.foreground : t.muted).child(badgeParts.name)))
          .when(Boolean(badgeParts.action), el => el
            .child(div().flex_none().text_size(10.5).text_color(t.dim).child('·'))
            .child(div().flex_none().text_size(11)
              .text_color(inlineOpen ? t.accent : t.muted).child(badgeParts.action)))
          .when(Boolean(badgeParts.model), el => el
            .when(Boolean(badgeParts.name || badgeParts.action), x => x.child(div().flex_none().text_size(10.5).text_color(t.dim).child('·')))
            .child(div().flex_none().font_family('monospace').text_size(10.5)
              .text_color(inlineOpen ? t.accent : t.dim).child(badgeParts.model)))
          .when(inlineOpen || inlineHovered, el => el.child(this.icon('window-pop', 10.5).flex_none().text_color(t.accent)));
      }

      // Clean trailing metadata per status:
      // - review (inside Working): soft `In review` / `待审` badge (plus fallback reviewer model if no active chip)
      // - working: plain monospace step fraction (fallback to age)
      // - parked (not started): tonal `waits #N` / `等 #N` micro-pill if unmet dep, else quiet `queued` / `排队`
      // - waiting/paused/offline: age
      let rightMetaText = ageText;
      let rightMetaId = '';
      let rightMetaPill = false;
      if (isReview) {
        rightMetaText = !hasSubChips && node.reviewModel ? node.reviewModel : '';
      } else if (node.group === 'working') {
        if (pill) { rightMetaText = pill; rightMetaId = `list-steps-${node.task}`; }
        else rightMetaText = ageText;
      } else if (node.group === 'parked') {
        const depInfo = task ? taskDependencies(task, allTasks, { terms: termsNow, live: liveNow }) : null;
        const firstUnmet = depInfo?.items?.find(it => !it.isMet);
        const unmetRef = firstUnmet ? formatDepRef(firstUnmet, id => this.taskNumberFor(id)) : '';
        if (unmetRef) {
          rightMetaText = word(lang, 'waitsDep', unmetRef);
          rightMetaPill = true;
        } else {
          rightMetaText = word(lang, 'queuedLabel');
        }
      }

      const titleRow = h_flex().w_full().min_h(22).gap(7).items_center()
        .child(lead(this.threadMark(node, t)))
        .when(Boolean(numText), el => el.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(numText)))
        .when(Boolean(folderAlias), el => el.child(folderPill(`list-folder-${node.task}`, folderAlias)))
        .child(div().flex_1().min_w(0).truncate().text_size(13)
          .font_weight(mutedTitle ? 400 : 500)
          .text_color(mutedTitle ? t.muted : t.foreground)
          .child(node.title))
        .when(Boolean(inlineChipEl), el => el.child(inlineChipEl))
        .when(isOpened, el => el.child(openBadge()))
        .when(isReview, el => el.child(reviewPill()))
        .when(Boolean(rightMetaText) && rightMetaPill, el => el.child(h_flex()
          .when(Boolean(rightMetaId), d => d.id(rightMetaId))
          .h(18).px(6).rounded(5).flex_none().items_center().bg(surf.pillMuted)
          .font_family('monospace').text_size(10.5).text_color(t.muted)
          .child(rightMetaText)))
        .when(Boolean(rightMetaText) && !rightMetaPill, el => el.child(div()
          .when(Boolean(rightMetaId), d => d.id(rightMetaId))
          .flex_none().font_family('monospace').text_size(11).text_color(t.dim)
          .child(rightMetaText)));

      const cardBg = litRow
        ? t.hover
        : hasSubChips
          ? surf.card
          : '';

      const itemCard = v_flex().id(`list-${node.task}`).w_full()
        .px(inEpic ? 6 : 8).py(hasSubChips ? 6 : 4.5).gap(hasSubChips ? 5 : 0)
        .rounded(inEpic ? 6 : 8).cursor_pointer()
        .when(Boolean(cardBg), el => el.bg(cardBg))
        .hover(s => s.bg(t.hover))
        .accessibility_label(numText ? `${numText} ${node.title}` : node.title)
        .on_hover((over, cx) => {
          if (over) {
            const onChildAgent = (inlineHoverKey && (this.hoverKey === inlineHoverKey || this.hoverPendingKey === inlineHoverKey))
              || subAgents.some(ag => this.hoverKey === `agent:${ag.key}` || this.hoverPendingKey === `agent:${ag.key}`);
            if (!onChildAgent) this.enterHover(hoverKey, cx);
          } else {
            this.leaveHover(hoverKey, cx);
          }
        })
        .on_click((_e, cx) => {
          this.clearHoverNow(cx);
          this.openThread(node.task, cx);
        })
        .child(titleRow)
        .when(hasSubChips, box => box.child(
          h_flex().w_full().min_w(0).pl(23).flex_wrap().gap(6).items_center()
            .children(subAgents.map(ag => agentChip(ag, false, { wrapHover: false }))),
        ));

      const hasAgentFold = endedAgents.length > 0;
      const foldKey = `agents:${node.task}`;
      const foldOpen = hasAgentFold && this.expandedDone.has(foldKey);

      const endedItems = [];
      if (hasAgentFold) {
        endedItems.push(doneFoldRow(`fold-done-agents-${node.task}`, endedAgents.length, foldOpen, cx => {
          if (this.expandedDone.has(foldKey)) this.expandedDone.delete(foldKey);
          else this.expandedDone.add(foldKey);
          cx.notify();
        }));
        if (foldOpen) {
          for (const ag of endedAgents) endedItems.push(agentChip(ag, true, { wrapHover: true }));
        }
      }

      const hoveredSubAgent = subAgents.find(ag => this.hoverKey === `agent:${ag.key}`);
      const rowWrap = (inlineWorker && this.hoverKey === inlineHoverKey)
        ? this.wrapHoverCard(inlineHoverKey, itemCard, () => this.agentHoverCard(inlineWorker, inlineOpen, t, lang), t)
        : hoveredSubAgent
          ? this.wrapHoverCard(`agent:${hoveredSubAgent.key}`, itemCard, () => this.agentHoverCard(hoveredSubAgent, agentWindowOpen(this.agentWindows, hoveredSubAgent.key), t, lang), t)
          : this.wrapHoverCard(hoverKey, itemCard, () => buildRowHoverCard(task, node, ctxLabel), t);

      return v_flex().w_full().gap(1)
        .child(rowWrap)
        .when(endedItems.length > 0, box => box.child(div().pl(23).pb(2)
          .child(v_flex().gap(2).children(endedItems))));
    };

    const renderFinishedSubRow = (row, { inEpic = false } = {}) => {
      const at = eventTime(row.updated);
      const ageText = at > 0 ? age(Math.max(0, now - at), lang) : '';
      const hoverKey = `task:${row.task}`;
      const task = byId.get(row.task);
      const folderAlias = threadFolderBadge(row.folderAlias ? row : task, projFolders);
      const ctxLabel = row.contextTokens ? contextLabel(lang, row.contextTokens) : '';
      const numText = formatTaskNumber(taskNumber(row) || taskNumber(task) || this.taskNumberFor(row.task));
      const litRow = this.highlightThread === row.task || this.hoverKey === hoverKey;
      const isOpened = openTabs.has(sideTabKey({ kind: 'thread', taskId: row.task }));
      const doneColor = t.ansi2 ?? t.done ?? t.accent;
      const commitHash = String(row.commit || '').trim();
      const rowBg = litRow ? t.hover : '';
      const el = h_flex().id(`list-${row.task}`).min_h(28).px(inEpic ? 6 : 8).py(4).gap(7).rounded(inEpic ? 6 : 8).items_center().cursor_pointer()
        .text_size(13).text_color(litRow ? t.foreground : t.muted)
        .when(Boolean(rowBg), x => x.bg(rowBg))
        .hover(s => s.bg(t.hover).text_color(t.foreground))
        .accessibility_label(numText ? `${numText} ${row.title}` : row.title)
        .on_hover((over, cx) => {
          if (over) this.enterHover(hoverKey, cx);
          else this.leaveHover(hoverKey, cx);
        })
        .on_click((_e, cx) => { this.clearHoverNow(cx); this.openThread(row.task, cx); })
        .child(lead(this.icon('check', 13.5).flex_none().text_color(doneColor)))
        .when(Boolean(numText), x => x.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(numText)))
        .when(Boolean(folderAlias), x => x.child(folderPill(`list-folder-${row.task}`, folderAlias)))
        .child(div().flex_1().min_w(0).truncate().child(row.title))
        .when(isOpened, x => x.child(openBadge()))
        .when(Boolean(commitHash), x => x.child(div().flex_none().font_family('monospace').text_size(11)
          .text_color(withAlpha(doneColor, surf.dark ? .82 : .92)).child(commitHash)))
        .when(!commitHash && Boolean(ageText), x => x.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(ageText)));
      return this.wrapHoverCard(hoverKey, el, () => buildRowHoverCard(task, row, ctxLabel), t);
    };

    const renderNode = (node, inEpic = false) => {
      const isParent = node.container || node.children.length > 0 || node.finishedChildren.length > 0;
      if (!isParent) return renderSingleThread(node, { hideEndedFold: inEpic, inEpic });

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
            for (const fc of node.finishedChildren) childItems.push(renderFinishedSubRow(fc, { inEpic: true }));
            for (const ag of endedChildAgents) childItems.push(agentChip(ag, true, { wrapHover: true }));
          }
        }
      }

      const hasExpandedChildren = open && childItems.length > 0;

      if (node.container) {
        const hoverKey = `epic:${node.task}`;
        const pills = summaryPills(node.summary, node.task);
        const epicNum = formatTaskNumber(taskNumber(node) || taskNumber(byId.get(node.task)) || this.taskNumberFor(node.task));
        const hdr = h_flex().id(`epic-${node.task}`).min_h(28).px(hasExpandedChildren ? 6 : 8).py(3.5).gap(7)
          .rounded(hasExpandedChildren ? 6 : 8).items_center().cursor_pointer()
          .hover(s => s.bg(t.hover))
          .accessibility_label(epicNum ? `${epicNum} ${node.title}` : node.title)
          .on_hover((over, cx) => {
            if (over) this.enterHover(hoverKey, cx);
            else this.leaveHover(hoverKey, cx);
          })
          .on_click((_e, cx) => toggleEpic(cx))
          .child(h_flex().w(16).flex_none().items_center().justify_center().text_color(t.muted)
            .child(this.icon(open ? 'expand' : 'chevron', 12.5)))
          .when(Boolean(epicNum), el => el.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(epicNum)))
          .child(div().flex_1().min_w(0).truncate().text_size(13).font_semibold().text_color(t.foreground).child(node.title))
          .when(Boolean(pills), el => el.child(pills));

        if (!hasExpandedChildren) {
          return v_flex().w_full()
            .child(this.wrapHoverCard(hoverKey, hdr, () => this.epicHoverCard(node, t, lang), t));
        }
        // Plan B Tonal Group Pod: concentric outer R=10 + p=4 -> inner recessed child well r=6 (zero tree wires!)
        return v_flex().id(`epic-pod-${node.task}`).w_full().p(4).gap(4).rounded(10).bg(surf.pod)
          .child(this.wrapHoverCard(hoverKey, hdr, () => this.epicHoverCard(node, t, lang), t))
          .child(v_flex().id(`epic-children-${node.task}`).w_full().p(3).gap(1).rounded(6).bg(surf.podWell)
            .children(childItems));
      }

      // Non-container parent thread (has own worker + sub-tasks): concentric tonal pod when expanded, zero tree wires.
      const ownSelf = { ...node, agents: { ...node.agents, ended: [] } };
      const parentHead = h_flex().w_full().items_center().gap(2)
        .child(h_flex().id(`epic-${node.task}`).size(20).flex_none().rounded(5).items_center().justify_center()
          .cursor_pointer().text_color(t.muted).hover(s => s.bg(t.hover).text_color(t.foreground))
          .on_click((_e, cx) => toggleEpic(cx))
          .child(this.icon(open ? 'expand' : 'chevron', 12)))
        .child(div().flex_1().min_w(0).child(renderSingleThread(ownSelf, { hideEndedFold: true, inEpic: hasExpandedChildren || inEpic })));
      if (!hasExpandedChildren) return v_flex().w_full().child(parentHead);
      return v_flex().id(`epic-pod-${node.task}`).w_full().p(4).gap(4).rounded(10).bg(surf.pod)
        .child(parentHead)
        .child(v_flex().id(`epic-children-${node.task}`).w_full().p(3).gap(1).rounded(6).bg(surf.podWell)
          .children(childItems));
    };

    const groupCountColor = key => (
      key === 'group_waiting' ? t.blocked
        : key === 'group_review' ? t.accent
          : key === 'group_working' ? (t.working ?? t.ansi3 ?? t.accent)
            : key === 'groupFinished' ? (t.ansi2 ?? t.done ?? t.accent)
              : t.muted
    );
    const groupEl = (key, title, count, rows) => v_flex().gap(3)
      .child(h_flex().h(22).px(8).gap(6).items_center().text_size(11.5).font_medium().text_color(t.dim)
        .child(title)
        .child(div().font_semibold().text_color(groupCountColor(key)).child(String(count))))
      .children(rows);

    const openGroupEls = tree.groups.map(g => groupEl(g.key, g.title, g.count, g.nodes.map(n => renderNode(n, false))));

    const sessions = tree.sessions.map(row => {
      const icon = !row.program?.icon ? this.icon('agent', 15).text_color(t.dim)
        : row.program.tint ? svg(row.program.icon).size(15).flex_none().text_color(t.foreground) : image(row.program.icon).size(15).flex_none();
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

    const mergedFinished = this.finishedExtra?.length ? mergeFinishedRows(tree.finished, this.finishedExtra) : tree.finished;
    const finished = mergedFinished.map(row => renderFinishedSubRow(row));
    const canLoadMoreFinished = this.tasksQuerySupported() && this.finishedMore &&
      (this.finishedTotal != null ? mergedFinished.length < this.finishedTotal : tree.finished.length >= FINISHED_LIMIT);
    if (this.finishedLoading) {
      finished.push(h_flex().id('finished-load-more').h(26).px(8).gap(7).rounded(7).items_center()
        .text_size(12).text_color(t.dim)
        .child(lead(svg(SPINNER).size(12).flex_none().spin(900)))
        .child(word(lang, 'loadingMoreFinished')));
    } else if (this.finishedError) {
      finished.push(h_flex().id('finished-load-more').min_h(26).px(8).py(3).gap(7).rounded(7).items_center().cursor_pointer()
        .text_size(11.8).text_color(t.blocked).hover(s => s.bg(t.hover))
        .on_click((_e, cx) => this.loadMoreFinished(cx))
        .child(div().flex_1().min_w(0).whitespace_normal().child(word(lang, 'finishedMoreError', this.finishedError))));
    } else if (canLoadMoreFinished) {
      const rest = this.finishedTotal != null ? Math.max(0, this.finishedTotal - mergedFinished.length) : 0;
      finished.push(h_flex().id('finished-load-more').h(26).px(8).gap(7).rounded(7).items_center().cursor_pointer()
        .text_size(12).text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
        .accessibility_label(word(lang, 'loadMoreFinished', rest))
        .on_click((_e, cx) => this.loadMoreFinished(cx))
        .child(lead(this.icon('expand', 12).text_color(t.dim)))
        .child(word(lang, 'loadMoreFinished', rest)));
    }
    const finishedCount = this.finishedTotal != null ? Math.max(this.finishedTotal, mergedFinished.length) : mergedFinished.length;
    const sections = [...openGroupEls];
    if (sessions.length) sections.push(groupEl('groupSessions', word(lang, 'groupSessions'), sessions.length, sessions));
    if (finished.length) sections.push(groupEl('groupFinished', word(lang, 'groupFinished'), finishedCount, finished));

    if (this.pendingScrollThread && this.threadListScroll) {
      const hasTask = n => n && (n.task === this.pendingScrollThread ||
        (n.children || []).some(hasTask) || (n.finishedChildren || []).some(hasTask));
      let sectionIdx = tree.groups.findIndex(g => g.nodes.some(hasTask));
      if (sectionIdx < 0 && mergedFinished.some(r => r.task === this.pendingScrollThread)) {
        sectionIdx = openGroupEls.length + (sessions.length ? 1 : 0);
      }
      if (sectionIdx >= 0) this.threadListScroll.scroll_to_item(sectionIdx);
      this.pendingScrollThread = '';
    }

    const q = String(this.threadsQuery || '').trim();
    const filterEl = this.isInlineFilterVisible('threads')
      ? this.inlineFilterBar('threads', 'threads-search', this.threadsInput, this.threadsQuery, word(lang, 'filterThreads'), cx => {
          this.threadsQuery = '';
          this.threadsInput?.set_value('');
          this.scheduleThreadsSearch(cx);
          this.threadsInput?.focus();
        }, t, { focused: this.typing === 'threadsSearch' })
      : null;

    const renderSearchRow = row => {
      const at = eventTime(row.updated);
      const ageText = at > 0 ? age(Math.max(0, now - at), lang) : '';
      const task = byId.get(row.task);
      const numText = formatTaskNumber(taskNumber(row) || taskNumber(task) || this.taskNumberFor(row.task));
      const muted = row.group === 'finished' || row.group === 'parked' || row.group === 'paused';
      const litRow = this.highlightThread === row.task;
      const isOpened = openTabs.has(sideTabKey({ kind: 'thread', taskId: row.task }));
      const rowBg = litRow ? t.hover : '';
      return h_flex().id(`threads-hit-${row.task}`).min_h(28).px(8).py(4).gap(7).rounded(8).items_center().cursor_pointer()
        .text_size(12.5).text_color(litRow ? t.foreground : muted ? t.muted : t.foreground)
        .when(Boolean(rowBg), x => x.bg(rowBg))
        .hover(s => s.bg(t.hover).text_color(t.foreground))
        .accessibility_label(numText ? `${numText} ${row.title}` : row.title)
        .on_click((_e, cx) => { this.clearHoverNow(cx); this.openThread(row.task, cx); })
        .child(lead(this.threadMark(row, t)))
        .when(Boolean(numText), x => x.child(div().flex_none().font_family('monospace').text_size(11.5).text_color(t.dim).child(numText)))
        .child(div().flex_1().min_w(0).truncate().font_weight(muted ? 400 : 500).child(row.title))
        .when(isOpened, x => x.child(openBadge()))
        .when(Boolean(ageText), x => x.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(ageText)));
    };

    let listChildren;
    if (q) {
      const rows = this.threadsSearchRows || [];
      if (this.threadsSearchLoading && !rows.length) {
        listChildren = [h_flex().px(8).pt(4).gap(8).items_center().text_size(13).text_color(t.dim)
          .child(svg(SPINNER).size(14).flex_none().spin(900)).child(word(lang, 'threadsSearching'))];
      } else if (this.threadsSearchError && !rows.length) {
        listChildren = [div().px(8).whitespace_normal().text_size(12.5).text_color(t.blocked)
          .child(word(lang, 'threadsSearchError', this.threadsSearchError))];
      } else if (!rows.length) {
        listChildren = [div().px(8).text_size(13).text_color(t.dim).child(word(lang, 'threadsNoMatches'))];
      } else {
        const hitEls = rows.map(r => renderSearchRow(r));
        if (this.threadsSearchLoading) {
          hitEls.push(h_flex().id('threads-search-more').h(26).px(8).gap(7).rounded(7).items_center()
            .text_size(12).text_color(t.dim)
            .child(lead(svg(SPINNER).size(12).flex_none().spin(900)))
            .child(word(lang, 'loadingMoreFinished')));
        } else if (this.threadsSearchMore) {
          const rest = Math.max(0, (this.threadsSearchTotal || 0) - rows.length);
          hitEls.push(h_flex().id('threads-search-more').h(26).px(8).gap(7).rounded(7).items_center().cursor_pointer()
            .text_size(12).text_color(t.dim).hover(s => s.bg(t.hover).text_color(t.foreground))
            .accessibility_label(word(lang, 'loadMoreFinished', rest))
            .on_click((_e, cx) => this.runThreadsSearch(cx, { append: true }))
            .child(lead(this.icon('expand', 12).text_color(t.dim)))
            .child(word(lang, 'loadMoreFinished', rest)));
        }
        listChildren = [v_flex().gap(2).children(hitEls)];
      }
    } else {
      listChildren = sections.length ? sections : [div().px(8).text_size(13).text_color(t.dim).child(word(lang, 'noThreads'))];
    }

    return v_flex().w_full().h_full().min_w(0)
      .on_hover((over, cx) => { if (!over && (this.hoverKey || this.hoverPendingKey)) this.leaveHover(this.hoverKey || this.hoverPendingKey, cx); })
      .when(Boolean(filterEl), el => el.child(filterEl))
      .child(this.sideScrollBody(v_flex().id('thread-list').flex_1().min_h(0).px(10).pt(8).pb(16).gap(14).overflow_y_scrollbar()
        .when(Boolean(this.threadListScroll), el => el.track_scroll(this.threadListScroll))
        .on_scroll_wheel((_e, cx) => { if (this.hoverKey || this.hoverPendingKey) this.clearHoverNow(cx); })
        .children(listChildren)));
  }

  sideHeader(t, width = PANEL_WIDTH, { inTabBar = false, searchEl = null } = {}) {
    const lang = this.lang;
    const surf = tonalSurfaces(t);
    const closeBtn = inTabBar ? null
      : this.splitIconBtn('panel-close', 'close', word(lang, 'closeSidePanel'), cx => this.closeSidePanel(cx), t, 14, false, { placement: 'below-right' });
    const hVal = inTabBar ? 38 : 44;
    if (!this.librarySupported()) {
      return h_flex().id('side-header').h(hVal).w_full().flex_none().px(12).gap(8).items_center()
        .bg(t.background)
        .border_b(1).border_color(surf.hairline)
        .child(div().flex_none().text_size(inTabBar ? 13 : 14).font_semibold().text_color(t.foreground).child(word(lang, 'threads')))
        .when(Boolean(searchEl), el => el.child(div().flex_1().min_w(0).child(searchEl)))
        .when(!searchEl, el => el.child(div().flex_1()))
        .when(Boolean(closeBtn), el => el.child(closeBtn));
    }
    const compact = width < 300;
    const tightTabs = Boolean(searchEl) && width < 420;
    const tabs = [
      { key: 'threads', label: word(lang, 'threads') },
      { key: 'library', label: word(lang, 'libraryTab') },
      ...(this.memorySupported() ? [{ key: 'memory', label: word(lang, 'memoryTab') }] : []),
    ];
    const active = this.sideTab === 'library' ? 'library'
      : (this.sideTab === 'memory' && this.memorySupported()) ? 'memory' : 'threads';
    const tab = item => this.withTip(`panel-tab-${item.key}`, h_flex().id(`panel-tab-${item.key}`).flex_none().h(24)
      .px(compact ? 7 : tightTabs ? 8 : 10)
      .rounded(6).items_center().justify_center().text_size(compact || tightTabs ? 12 : 12.5).accessibility_label(item.label)
      .when(item.key === active, el => el.bg(surf.segActive).when(!surf.dark, e => e.shadow_xs()).text_color(t.foreground).font_medium())
      .when(item.key !== active, el => el.cursor_pointer().text_color(t.muted).hover(s => s.text_color(t.foreground))
        .on_click((_e, cx) => this.selectSideTab(item.key, cx)))
      .child(item.label), item.label, t, { panel: true, placement: 'below-left' });
    return h_flex().id('side-header').h(hVal).w_full().flex_none().px(10).gap(8).items_center()
      .bg(t.background)
      .border_b(1).border_color(surf.hairline)
      .child(h_flex().id('panel-tabs').flex_none().h(30).p(3).gap(2).rounded(9)
        .bg(surf.well).items_center()
        .children(tabs.map(tab)))
      .when(Boolean(searchEl), el => el.child(div().flex_1().min_w(0).child(searchEl)))
      .when(!searchEl, el => el.child(div().flex_1()))
      .when(Boolean(closeBtn), el => el.child(closeBtn));
  }

  searchBox(id, state, query, placeholder, onClear, t, { compact = false, focused = false } = {}) {
    const lang = this.lang;
    const surf = tonalSurfaces(t);
    const boxH = compact ? 30 : 32;
    const inputH = compact ? 26 : 28;
    const hint = div().absolute().left(0).top(compact ? 4 : 5).right(0).truncate().text_size(12).text_color(t.dim).child(placeholder);
    return keepPress(h_flex().id(id)).w_full().h(boxH).px(9).gap(6).rounded(9).items_center()
      .bg(surf.well)
      .border_1().border_color(focused ? withAlpha(t.accent, .42) : withAlpha(t.border, 0))
      .child(this.icon('search', 13.5).text_color(t.dim))
      .child(div().relative().flex_1().min_w(0).h(inputH).when(!query, el => el.child(hint))
        .child(Input.new(state).w_full().h(inputH).items_center().text_size(12).text_color(t.foreground)))
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
    const isOpened = this.openTabKeys().has(sideTabKey({ kind: 'doc', root: row.root, path: row.path }));
    const tip = [`${row.root}/${row.path}`, row.kindLabel, row.size, row.desc].filter(Boolean).join(' · ');
    const srcTip = row.task ? word(lang, 'openSourceThread', row.taskTitle || row.task) : '';
    return this.withTip(`lib-doc-${row.key}`, h_flex().id(`lib-doc-${row.key}`).pl(8 + row.depth * 14).pr(6).py(6).gap(9).rounded(8).items_start()
      .cursor_pointer().hover(s => s.bg(t.hover)).accessibility_label(tip)
      .when(Boolean(row.archive || row.supersededBy), el => el.opacity(.75))
      .on_click((_e, cx) => this.openDoc({ tab: 'library', root: row.root, path: row.path }, cx))
      .child(h_flex().h(19).w(16).flex_none().items_center().justify_center().child(this.icon(glyphName, 14).text_color(isOpened ? t.accent : t.dim)))
      .child(v_flex().flex_1().min_w(0).gap(1)
        .child(h_flex().gap(7).items_center()
          .child(div().flex_1().min_w(0).truncate().text_size(13).font_medium()
            .text_color(row.readable && !row.archive && !row.supersededBy ? t.foreground : t.muted).child(row.title))
          .when(isOpened, el => el.child(div().flex_none().text_size(10.5).text_color(t.accent).child(word(lang, 'sideTabOpened'))))
          .when(Boolean(row.supersededBy), el => el.child(div().flex_none().text_size(10.5).text_color(t.dim)
            .child(word(lang, 'supersededLabel'))))
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
    const lang = this.lang;
    const isOpened = this.openTabKeys().has(sideTabKey({ kind: 'doc', root: row.root, path: row.path }));
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
          .when(isOpened, el => el.child(div().flex_none().text_size(10.5).text_color(t.accent).child(word(lang, 'sideTabOpened'))))
          .child(div().flex_none().text_size(11).text_color(t.dim).child(row.typeLabel))
          .when(Boolean(row.modified), el => el.child(div().flex_none().text_size(11).text_color(t.dim).child(row.modified))))
        .when(Boolean(row.desc), el => el.child(div().truncate().text_size(12).text_color(t.dim).child(row.desc)))),
      tip, t, { panel: true, placement: 'above-left' });
  }

  docDetailView(t, today, width = PANEL_WIDTH, cx = null) {
    const lang = this.lang;
    const docRef = this.activeDoc;
    const inTabBar = this.hasSideTabs();
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
    const showCopyPath = isRepo || docRef.root === 'repo_docs';
    const copiedPath = showCopyPath && this.pathCopiedAt && Date.now() - this.pathCopiedAt < 1800;

    const matchList = vm?.matchIndices || [];
    const safeMatchPos = matchList.length ? ((this.docMatchPos % matchList.length) + matchList.length) % matchList.length : 0;

    const docImgTarget = mode === 'binary' && isPreviewableImage(docRef.path)
      ? resolveImageTarget(docRef, this.docLinkContext())
      : null;
    const docImgState = docImgTarget ? this.imagePreviewState(docImgTarget, cx) : null;
    const docImgReady = Boolean(docImgTarget && docImgState?.status === 'ready');
    const docImgOpenPath = docImgReady
      ? resolveSystemPreviewPath({
          target: docImgTarget,
          entry: docImgState.entry,
          appHomeDir: typeof appHome === 'function' ? appHome() : '',
          machine: this.machine || '',
        })
      : '';

    const fullPathLabel = isRepo || docRef.root === 'repo_docs' ? docRef.path : `${docRef.root} / ${docRef.path.split('/').join(' / ')}`;
    const titleTip = [headerTitle, fullPathLabel, vm?.modified || meta?.modified || ''].filter(Boolean).join('\n');
    const docActions = h_flex().flex_none().gap(2).items_center()
      .when(docImgReady, el => el
        .child(this.splitIconBtn('doc-img-zoom', 'zoom-in', word(lang, 'imageZoomLightbox'),
          clickCx => this.openImageLightbox(docImgTarget, docImgState.entry, clickCx), t, 14))
        .when(Boolean(docImgOpenPath), sub => sub.child(this.splitIconBtn('doc-img-open-external', 'external-open',
          word(lang, 'imageOpenExternal'),
          clickCx => this.openImageInSystem(docImgTarget, docImgState.entry, clickCx), t, 14))))
      .when(showCopyPath, el => el.child(this.splitIconBtn('doc-copy-path', copiedPath ? 'check' : 'clip',
        word(lang, copiedPath ? 'mentionPathCopied' : 'mentionCopyPath'), cx => {
          cx.write_to_clipboard?.(docRef.path);
          this.pathCopiedAt = Date.now();
          cx.notify();
          cx.timer?.after?.(1800, cx => { this.pathCopiedAt = 0; cx.notify(); });
        }, t, 14)))
      .when(Boolean(meta?.task), el => el.child(this.splitIconBtn('doc-source-thread', 'hook-up',
        word(lang, 'openSourceThread', meta.task_title || meta.task), cx => this.openThread(meta.task, cx, { insertAdjacent: true }), t, 14)))
      .when(Boolean(vm), el => el.child(this.splitIconBtn('doc-find-toggle', 'search', word(lang, 'findInDoc'), cx => {
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
        this.syncActiveTabFind();
        this.notifyPanes(cx, { shell: false, side: true });
      }, t, 14, this.docFindOpen)))
      .when(Boolean(writable && vm), el => el.child(this.splitIconBtn('doc-edit', 'pencil',
        word(lang, 'editDoc'), cx => this.startEditDoc(cx), t, 14)))
      .when(Boolean(writable), el => el.child(this.splitIconBtn('doc-history', 'history',
        word(lang, 'docHistory'), cx => this.openHistory(docRef.tab, docRef.root, docRef.path, 'item', cx), t, 14)))
      .when(Boolean(writable), el => el.child(this.splitIconBtn('doc-delete', 'trash',
        word(lang, 'deleteItem'), cx => {
          this.confirmDeleteKey = this.confirmDeleteKey === key ? '' : key;
          this.deleteError = '';
          cx.notify();
        }, t, 14)));
    const contextTitle = inTabBar
      ? (width < 440 ? fileName(docRef.path) : fullPathLabel)
      : headerTitle;
    const topBar = this.renderSplitTopBar({
      id: inTabBar ? 'side-context-bar' : 'doc-topbar',
      backId: 'doc-back',
      onBack: inTabBar ? null : (cx => this.closeActiveDoc(cx)),
      backTip,
      leading: vm?.readOnly
        ? this.withTip('doc-readonly-lock', h_flex().id('doc-readonly-lock').size(18).flex_none().items_center().justify_center()
            .text_color(t.dim).child(this.icon('lock', 12)), word(lang, 'readOnly'), t, { panel: true, placement: 'below-left' })
        : null,
      titleId: 'doc-title',
      title: contextTitle,
      titleTip,
      actions: docActions,
      closeId: 'split-close',
      onClose: null,
      compactBar: true,
      titleMuted: inTabBar,
      t,
    });

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
      .on_click((_e, cx) => this.openThread(vm.sourceTask, cx, { insertAdjacent: true }))
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

    const supersededTarget = docRef.root === 'docs' ? (meta?.superseded_by || vm?.supersededBy || '') : '';
    const supersededBar = supersededTarget ? v_flex().id('doc-superseded-bar').w_full().p(10).gap(6).rounded(10)
      .bg(withAlpha(t.accent, .1)).border_1().border_color(withAlpha(t.accent, .28))
      .child(div().whitespace_normal().text_size(12).text_color(t.foreground)
        .child(word(lang, 'supersededBanner', supersededTarget)))
      .child(h_flex().gap(8).items_center()
        .child(h_flex().id('doc-open-superseded').h(24).px(9).gap(5).rounded(7).items_center().cursor_pointer()
          .bg(withAlpha(t.accent, .18)).text_size(11.5).font_medium().text_color(t.accent)
          .hover(s => s.bg(withAlpha(t.accent, .28)))
          .on_click((_e, cx) => this.openDoc({ tab: 'library', root: 'repo_docs', path: supersededTarget }, cx, { insertAdjacent: true }))
          .child(this.icon('hook-up', 11.5))
          .child(word(lang, 'openSupersededTarget')))
        .when(writable, el => el.child(this.deleteBusy === key
          ? svg(SPINNER).size(14).flex_none().spin(900)
          : h_flex().id('doc-archive-draft').h(24).px(9).gap(5).rounded(7).items_center().cursor_pointer()
              .bg(t.raised).text_size(11.5).text_color(t.muted)
              .hover(s => s.bg(t.hover).text_color(t.foreground))
              .on_click((_e, cx) => this.deleteActiveDoc(cx))
              .child(this.icon('history', 11.5))
              .child(word(lang, 'archiveDraft'))))) : null;

    const matchedSet = new Set(matchList);
    const highlightActive = Boolean(findQuery && String(findQuery).trim() && matchedSet.size);
    const bodyChildren = [];
    bodyChildren.push(metaRow);
    if (supersededBar) bodyChildren.push(supersededBar);
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
      if (docImgTarget) {
        if (docImgState?.status === 'ready') {
          const box = fitImageBox(docImgState.entry.width, docImgState.entry.height, {
            maxWidth: Math.max(240, Math.min(640, width - 56)),
            maxHeight: 640,
          });
          const zoomTip = word(lang, 'imageZoomLightbox');
          const imgFrame = div().id(`doc-img-preview-${key}`).w(box.width + 2).rounded(10).overflow_hidden()
            .border_1().border_color(t.border).bg(t.surface).cursor_pointer()
            .hover(s => s.border_color(withAlpha(t.accent, .55)))
            .accessibility_label(zoomTip)
            .on_click((_e, clickCx) => this.openImageLightbox(docImgTarget, docImgState.entry, clickCx))
            .child(image(docImgState.entry.rel).w(box.width).h(box.height));
          bodyChildren.push(v_flex().id(`doc-img-wrap-${key}`).w_full().pt(4).gap(8).items_start()
            .child(this.withTip(`doc-img-preview-${key}`, imgFrame, zoomTip, t, { panel: true, placement: 'above-left' }))
            .child(h_flex().w(box.width + 2).max_w_full().gap(8).items_center().justify_between()
              .child(h_flex().gap(10).items_center().text_size(11.5).text_color(t.dim)
                .child(word(lang, 'imageDimensions', docImgState.entry.width, docImgState.entry.height))
                .when(docImgState.entry.size > 0, el => el.child(formatBytes(docImgState.entry.size))))
              .child(h_flex().gap(2).items_center()
                .child(this.splitIconBtn('doc-img-body-zoom', 'zoom-in', zoomTip,
                  clickCx => this.openImageLightbox(docImgTarget, docImgState.entry, clickCx), t, 13.5, false, { placement: 'above-right' }))
                .when(Boolean(docImgOpenPath), el => el.child(this.splitIconBtn('doc-img-body-open', 'external-open',
                  word(lang, 'imageOpenExternal'),
                  clickCx => this.openImageInSystem(docImgTarget, docImgState.entry, clickCx), t, 13.5, false, { placement: 'above-right' }))))));
        } else if (docImgState?.status === 'loading') {
          bodyChildren.push(h_flex().pt(8).gap(8).items_center().text_size(12.5).text_color(t.dim)
            .child(svg(SPINNER).size(14).flex_none().spin(900)).child(word(lang, 'imageLoading')));
        } else {
          const errMsg = docImgState?.error === 'too large' ? word(lang, 'imageTooLarge') : word(lang, 'imageLoadFailed');
          bodyChildren.push(h_flex().pt(6).gap(8).items_center()
            .child(div().flex_1().min_w(0).whitespace_normal().text_size(12.5).text_color(t.muted).child(errMsg))
            .child(this.iconButton('doc-img-retry', 'reattach', word(lang, 'docRetry'),
              clickCx => this.loadImagePreview(docImgTarget, clickCx, { force: true }), t, 14)));
        }
      } else {
        bodyChildren.push(div().pt(6).whitespace_normal().text_size(12.5).text_color(t.muted).child(word(lang, 'docNotText')));
      }
    } else if (this.docError) {
      const curTab = this.activeSideTab();
      bodyChildren.push(h_flex().pt(6).gap(8).items_start()
        .child(div().flex_1().min_w(0).whitespace_normal().text_size(12.5).text_color(t.blocked).child(this.docError))
        .child(this.iconButton('doc-retry', 'reattach', word(lang, 'docRetry'),
          cx => this.readDoc(docRef.root, docRef.path, cx, { force: true }), t, 14))
        .when(Boolean(curTab), el => el.child(this.iconButton('doc-error-close-tab', 'close', word(lang, 'sideTabClose'),
          cx => this.closeTab(curTab.id, cx, { force: true }), t, 13))));
    } else if (vm) {
      vm.chunks.forEach((chunk, idx) => {
        const hit = highlightActive && matchedSet.has(idx);
        bodyChildren.push(div().id(`doc-chunk-${key}-${idx}`).w_full().text_size(13.5).text_color(t.foreground)
          .when(hit, el => el.px(8).py(4).rounded(6).bg(withAlpha(t.accent, isDarkTheme(t) ? .14 : .10)))
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

    const docScrollHandle = this.tabScrollHandle('doc');
    if (this.docFindJump && vm && matchList.length) {
      this.docFindJump = false;
      docScrollHandle?.scroll_to_item?.(chunkStartIndex + matchList[safeMatchPos]);
    } else if (this.docFindJump && vm) {
      this.docFindJump = false;
    }

    return v_flex().flex_1().min_h(0)
      .child(topBar)
      .when(Boolean(deleteBar), el => el.child(deleteBar))
      .when(Boolean(findBar), el => el.child(findBar))
      .child(this.sideScrollBody(v_flex().id('doc-detail-body').flex_1().min_h(0).px(24).pt(14).pb(28).items_center().overflow_y_scrollbar()
        .when(Boolean(docScrollHandle), el => el.track_scroll(docScrollHandle))
        .child(v_flex().w_full().max_w(680).gap(10).children(bodyChildren))));
  }

  docEditView(t, cx) {
    const lang = this.lang;
    const ed = this.editingDoc;
    const isMem = ed.tab === 'memory';
    const title = ed.mode === 'create'
      ? word(lang, isMem ? 'newMemory' : 'newDoc')
      : (isMem ? ed.originalName : fileName(ed.path));
    const saveControl = ed.saving
      ? this.withTip('doc-edit-save', h_flex().id('doc-edit-save').size(28).flex_none().rounded(7).items_center().justify_center()
          .accessibility_label(word(lang, 'savingEdit'))
          .child(svg(SPINNER).size(14).flex_none().spin(900)), word(lang, 'savingEdit'), t, { panel: true, placement: 'below-right' })
      : this.splitIconBtn('doc-edit-save', 'check', word(lang, 'saveEdit'), cx => this.saveEditingDoc(cx), t, 14, false, { placement: 'below-right' });
    const inTabBar = this.hasSideTabs();
    const topBar = this.renderSplitTopBar({
      id: 'doc-edit-topbar',
      backId: 'doc-edit-cancel',
      onBack: cx => this.cancelEditDoc(cx),
      backTip: word(lang, 'cancelEdit'),
      titleId: 'doc-edit-title',
      title,
      actions: saveControl,
      closeId: 'split-close',
      onClose: null,
      compactBar: true,
      t,
    });

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
      .child(this.sideScrollBody(v_flex().flex_1().min_h(0).px(16).pt(10).pb(16).gap(8)
        .when(!isMem && ed.mode === 'create', el => el.child(
          inputRow('doc-edit-name', this.docNameInput, this.docNameInput.value(), word(lang, 'docNamePlaceholder')),
        ))
        .when(isMem && ed.mode === 'create', el => el.child(h_flex().gap(6).items_center()
          .child(chip('mem-layer-project', ed.layer !== 'personal', word(lang, 'memLayerProject'), (_e, cx) => {
            ed.layer = 'project'; ed.root = 'memory';
            if (!PROJECT_MEMORY_TYPES.includes(ed.type)) ed.type = 'project';
            this.syncActiveTabDirty();
            this.notifyPanes(cx, { shell: false, side: true });
          }))
          .child(chip('mem-layer-personal', ed.layer === 'personal', word(lang, 'memLayerUser'), (_e, cx) => {
            ed.layer = 'personal'; ed.root = 'personal';
            if (!PERSONAL_MEMORY_TYPES.includes(ed.type)) ed.type = 'user';
            if (ed.topic === 'pitfalls') ed.topic = 'workflow';
            this.syncActiveTabDirty();
            this.notifyPanes(cx, { shell: false, side: true });
          }))))
        .when(isMem && ed.mode === 'create', el => el.child(
          inputRow('mem-edit-name', this.docNameInput, this.docNameInput.value(), word(lang, 'memNamePlaceholder')),
        ))
        .when(isMem, el => el.child(h_flex().flex_wrap().gap(5)
          .children(allowedTypes.map(ty => chip(`edit-type-${ty}`, ed.type === ty, memoryTypeLabel(lang, ty), (_e, cx) => {
            const next = retopicPlan({ layer: ed.layer, type: ed.type, topic: ed.topic }, { nextType: ty });
            ed.type = next.type;
            ed.topic = next.topic;
            this.syncActiveTabDirty();
            this.notifyPanes(cx, { shell: false, side: true });
          })))))
        .when(isMem && ed.layer !== 'personal', el => el.child(h_flex().flex_wrap().gap(5)
          .children(MEMORY_TOPICS.map(tid => chip(`edit-topic-${tid}`, ed.topic === tid, topicLabel(lang, tid), (_e, cx) => {
            const next = retopicPlan({ layer: ed.layer, type: ed.type, topic: ed.topic }, { nextTopic: tid });
            ed.type = next.type;
            ed.topic = next.topic;
            this.syncActiveTabDirty();
            this.notifyPanes(cx, { shell: false, side: true });
          })))))
        .when(isMem, el => el.child(
          inputRow('mem-edit-desc', this.memDescInput, this.memDescInput.value(), word(lang, 'memDescPlaceholder')),
        ))
        .child(keepPress(v_flex().id('doc-editor-box')).flex_1().min_h(160).w_full().p(10).rounded(10)
          .bg(t.surface).border_1().border_color(t.input || t.border)
          .child(div().relative().flex_1().min_h(0).w_full()
            .when(!this.docEditorInput.value(), el => el.child(div().absolute().left(0).top(0).right(0).truncate()
              .text_size(13).text_color(t.dim).child(word(lang, isMem ? 'memBodyPlaceholder' : 'docBodyPlaceholder'))))
            .child(Textarea.new(this.docEditorInput).w_full().h_full().min_h(140).text_size(13).text_color(t.foreground))))));
  }

  historySubView(t, today, cx) {
    const lang = this.lang;
    const hv = this.historyView;
    const currentYear = String(today || '').slice(0, 4);
    const title = hv.scope === 'item' && hv.path
      ? `${fileName(hv.path)} · ${word(lang, 'historyTitle')}`
      : word(lang, 'historyTitle');
    const inTabBar = this.hasSideTabs();
    const topBar = this.renderSplitTopBar({
      id: 'history-topbar',
      backId: 'history-back',
      onBack: cx => this.closeHistory(cx),
      backTip: word(lang, 'close'),
      titleId: 'history-title',
      title,
      closeId: 'split-close',
      onClose: null,
      compactBar: true,
      t,
    });

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

    const histScrollHandle = this.tabScrollHandle('history');
    return v_flex().id('history-view').flex_1().min_h(0)
      .child(topBar)
      .child(this.sideScrollBody(v_flex().id('history-list').flex_1().min_h(0).px(12).pt(8).pb(16).gap(4).overflow_y_scrollbar()
        .when(Boolean(histScrollHandle), el => el.track_scroll(histScrollHandle))
        .children(body)));
  }

  libraryPanel(pm, t, width, today, cx) {
    const lang = this.lang;
    const currentYear = String(today || '').slice(0, 4);
    const wrapSub = child => v_flex().id('library-panel').w_full().h_full().min_w(0)
      .on_drop((e, cx) => this.dropLibraryFiles(e?.paths || [], cx))
      .child(child);

    if (this.historyView?.tab === 'library') return wrapSub(this.historySubView(t, today, cx));
    if (this.editingDoc?.tab === 'library') return wrapSub(this.docEditView(t, cx));
    if (this.activeDoc?.tab === 'library') return wrapSub(this.docDetailView(t, today, width, cx));

    const q = String(this.libraryQuery || '').trim();
    const groups = q ? [] : libraryGroups({ roots: this.libraryRoots, files: this.libraryFiles }, this.libraryClosed, lang, currentYear);
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
        : (sec.id === 'docs' ? [div().px(8).py(4).text_size(12).text_color(t.dim).child(word(lang, 'libraryDropHint'))] : []))
      .when(Boolean(sec.id === 'repo_docs' && sec.truncated), el => el.child(
        div().px(8).py(4).text_size(11).text_color(t.dim).whitespace_normal()
          .child(word(lang, 'repoDocsTruncated', sec.shown, sec.total))));

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

    const filterEl = this.isInlineFilterVisible('library')
      ? this.inlineFilterBar('library', 'library-search', this.libraryInput, this.libraryQuery, word(lang, 'filterLibrary'), cx => {
          this.libraryQuery = '';
          this.libraryInput.set_value('');
          this.libraryInput.focus();
          cx.notify();
        }, t, { focused: this.typing === 'librarySearch' })
      : null;

    return v_flex().id('library-panel').w_full().h_full().min_w(0)
      .on_drop((e, cx) => this.dropLibraryFiles(e?.paths || [], cx))
      .when(Boolean(filterEl), el => el.child(filterEl))
      .when(Boolean(this.deletedBanner?.tab === 'library'), el => el.child(this.deletedBannerBar('library', t)))
      .when(Boolean(this.libraryDropBusy), el => el.child(h_flex().px(16).pb(4).gap(6).items_center().text_size(11.5).text_color(t.dim)
        .child(svg(SPINNER).size(12).flex_none().spin(900)).child(word(lang, 'addingFiles', this.libraryDropBusy))))
      .when(Boolean(this.libraryDropError), el => el.child(h_flex().px(16).pb(4).gap(6).items_start()
        .child(div().flex_1().min_w(0).whitespace_normal().text_size(11.5).text_color(t.blocked).child(this.libraryDropError))
        .child(this.iconButton('library-drop-err-close', 'close', word(lang, 'dismissNotice'),
          cx => { this.libraryDropError = ''; cx.notify(); }, t, 11))))
      .when(Boolean(this.libraryError && this.libraryRead), el => el.child(div().px(16).pb(4).whitespace_normal()
        .text_size(11.5).text_color(t.blocked).child(word(lang, 'libraryStale', this.libraryError))))
      .child(this.sideScrollBody(v_flex().id('library-list').flex_1().min_h(0).px(10).pt(4).pb(16).gap(12).overflow_y_scrollbar()
        .track_scroll(this.libraryScroll)
        .children(listChildren)));
  }

  memoryPanel(pm, t, width, today, cx) {
    const lang = this.lang;
    const currentYear = String(today || '').slice(0, 4);
    const wrapSub = child => v_flex().id('memory-panel').w_full().h_full().min_w(0)
      .on_drop((e, cx) => this.dropMemoryFiles(e?.paths || [], cx))
      .child(child);

    if (this.historyView?.tab === 'memory') return wrapSub(this.historySubView(t, today, cx));
    if (this.editingDoc?.tab === 'memory') return wrapSub(this.docEditView(t, cx));
    if (this.activeDoc?.tab === 'memory') return wrapSub(this.docDetailView(t, today, width, cx));

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

    const filterEl = this.isInlineFilterVisible('memory')
      ? this.inlineFilterBar('memory', 'memory-search', this.memoryInput, this.memoryQuery, word(lang, 'filterMemory'), cx => {
          this.memoryQuery = '';
          this.memoryInput.set_value('');
          this.memoryInput.focus();
          cx.notify();
        }, t, { focused: this.typing === 'memorySearch' })
      : null;

    const dreamLine = formatDreamStatus(this.memoryData?.dream, lang, Date.now(), this.clockOffsetMs || 0);

    return v_flex().id('memory-panel').w_full().h_full().min_w(0)
      .on_drop((e, cx) => this.dropMemoryFiles(e?.paths || [], cx))
      .when(Boolean(filterEl), el => el.child(filterEl))
      .when(Boolean(dreamLine), el => el.child(div().id('memory-dream-status').px(16).pt(6).pb(4).truncate().text_size(11.5).text_color(t.dim).child(dreamLine)))
      .when(Boolean(this.deletedBanner?.tab === 'memory'), el => el.child(this.deletedBannerBar('memory', t)))
      .when(Boolean(this.memoryBusy), el => el.child(h_flex().px(16).pb(4).gap(6).items_center().text_size(11.5).text_color(t.dim)
        .child(svg(SPINNER).size(12).flex_none().spin(900)).child(word(lang, 'addingFiles', this.memoryBusy))))
      .when(Boolean(this.memoryNoticeError), el => el.child(h_flex().px(16).pb(4).gap(6).items_start()
        .child(div().flex_1().min_w(0).whitespace_normal().text_size(11.5).text_color(t.blocked).child(this.memoryNoticeError))
        .child(this.iconButton('memory-err-close', 'close', word(lang, 'dismissNotice'),
          cx => { this.memoryNoticeError = ''; cx.notify(); }, t, 11))))
      .when(Boolean(this.memoryError && this.memoryRead), el => el.child(div().px(16).pb(4).whitespace_normal()
        .text_size(11.5).text_color(t.blocked).child(word(lang, 'memoryStale', this.memoryError))))
      .child(this.sideScrollBody(v_flex().id('memory-list').flex_1().min_h(0).px(10).pt(4).pb(16).gap(10).overflow_y_scrollbar()
        .track_scroll(this.memoryScroll)
        .children(listChildren)));
  }

  threadSessionView(t, today, cx) {
    const lang = this.lang;
    const surf = tonalSurfaces(t);
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
        if (part.kind === 'question') {
          return this.renderSessionQuestionPart(part, t, lang, { prefix: 'session' });
        }
        const open = toolsOpen.has(part.key);
        const head = this.withTip(`session-tools-${part.key}`, h_flex().id(`session-tools-${part.key}`).min_h(26).px(8).py(4).gap(6).rounded(7).items_center()
          .cursor_pointer().bg(surf.pod).hover(s => s.bg(t.hover))
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
        const body = v_flex().id(`session-tools-body-${part.key}`).px(10).py(6).gap(5).rounded(6).bg(surf.podWell)
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
    if (this.threadSessionLoading && !held && this.threadSessionState !== 'empty') {
      children.push(h_flex().pt(6).gap(8).items_center().text_size(12.5).text_color(t.dim)
        .child(svg(SPINNER).size(14).flex_none().spin(900)).child(word(lang, 'sessionLoading')));
    } else if (this.threadSessionError && !held) {
      children.push(div().pt(6).whitespace_normal().text_size(12.5).text_color(t.blocked)
        .child(word(lang, 'sessionStale', this.threadSessionError)));
    } else if (held?.unknown?.length && !turns.length) {
      children.push(div().id('thread-session-unknown').pt(6).whitespace_normal().text_size(12.5).text_color(t.muted)
        .child(word(lang, 'sessionUnknown')));
    } else if ((held && !turns.length) || this.threadSessionState === 'empty') {
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

    const sessScroll = this.tabScrollHandle('session');
    return v_flex().id('thread-session').flex_1().min_h(0).py(2).gap(12).overflow_y_scrollbar()
      .when(Boolean(sessScroll), el => el.track_scroll(sessScroll))
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
    const historyRow = !stateTask
      ? (this.finishedExtra || []).find(r => r.task === this.thread) || (this.threadsSearchRows || []).find(r => r.task === this.thread)
      : null;
    const fallbackTask = historyRow
      ? { id: historyRow.task, number: historyRow.number, title: historyRow.title, status: historyRow.status, branch: historyRow.branch, commit: historyRow.commit, landed: historyRow.landed, updated: historyRow.updated, parent: historyRow.parent }
      : null;
    const task = { ...fallbackTask, ...stateTask, ...this.threadTask };
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
          : status === 'review' ? 'review'
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
      ? this.withTip('thread-terminal', h_flex().id('thread-terminal').size(28).flex_none().rounded(7).items_center().justify_center().text_color(t.muted)
        .accessibility_label(word(lang, 'reattaching'))
        .child(svg(SPINNER).size(14).flex_none().spin(900)), word(lang, 'reattaching'), t, { panel: true, placement: 'below-right' })
      : does === 'reattach'
        ? this.splitIconBtn('thread-terminal', 'reattach', reattachTip, cx => this.reattach(cx), t)
        : primaryAgent
          ? this.splitIconBtn('thread-terminal', 'window-pop',
            primaryOpen ? word(lang, 'closeAgentWindow') : word(lang, 'detailOpenWindow'),
            cx => this.toggleAgentSmallWindow(primaryAgent, cx), t, 14, primaryOpen)
          : terminal && !this.terminalPlace(terminal.address).focus
            ? this.splitIconBtn('thread-terminal', 'terminal', word(lang, 'terminalNowhere'), null, t)
            : this.splitIconBtn('thread-terminal', 'terminal', terminal ? word(lang, 'openTerminal') : word(lang, 'threadOffline'),
              terminal ? () => this.focusTerminal(terminal.address) : null, t);
    const showWindowAction = does !== 'hidden' || Boolean(primaryAgent);
    const diffBtn = this.threadChangeButton(task, t);
    const actions = (showWindowAction || Boolean(diffBtn))
      ? h_flex().gap(2).items_center().flex_none()
          .when(showWindowAction, el => el.child(windowOrTerminalIcon))
          .when(Boolean(diffBtn), el => el.child(diffBtn))
      : null;

    const surf = tonalSurfaces(t);
    const threadNum = formatTaskNumber(taskNumber(task) || taskNumber(stateTask) || this.taskNumberFor(this.thread));
    const fullTitle = task.title || this.thread;
    const titleTip = [threadNum ? `${threadNum} ${fullTitle}` : fullTitle, statusTip].filter(Boolean).join(' · ');
    const inTabBar = this.hasSideTabs();
    const statusDotEl = this.withTip('thread-status', h_flex().id('thread-status').size(18).flex_none().items_center().justify_center()
      .accessibility_label(statusTip)
      .child(this.threadMark(markRow, t)), statusTip, t, { panel: true, placement: 'below-left' });

    const hasSessionTab = this.sessionTabAvailable(stateTask, task);
    const activeTab = this.activeThreadTab(stateTask, task);
    const tabItem = (key, glyph, label, dot = false) => h_flex().id(`thread-tab-${key}`).h(22).px(8).gap(4.5).rounded(6).items_center()
      .text_size(11.5).accessibility_label(label)
      .when(key === activeTab, el => el.bg(surf.softChip).text_color(t.foreground).font_medium())
      .when(key !== activeTab, el => el.cursor_pointer().text_color(t.muted).hover(s => s.bg(surf.softChipHover).text_color(t.foreground))
        .on_click((_e, cx) => this.selectThreadTab(key, cx)))
      .child(this.icon(glyph, 12)).child(label)
      .when(Boolean(dot), el => el.child(div().size(5).rounded_full().bg(t.blocked)));
    const tabBar = hasSessionTab ? h_flex().id('thread-tabs').flex_none().h(24).gap(2).items_center()
      .child(tabItem('log', 'list', word(lang, 'threadLogTab'), activeTab === 'session' && Boolean(asks)))
      .child(tabItem('session', 'chat', word(lang, 'threadSessionTab'))) : null;

    const parentNum = formatTaskNumber(parent);
    const statusBadge = reviewOpen
      ? h_flex().h(19).px(6).rounded(5).flex_none().items_center().bg(withAlpha(t.accent, surf.dark ? .13 : .10))
          .text_size(10.5).font_medium().text_color(t.accent).child(word(lang, 'reviewBadge'))
      : detailGroup === 'waiting'
        ? h_flex().h(19).px(6).rounded(5).flex_none().items_center().bg(withAlpha(t.blocked, surf.dark ? .14 : .11))
            .text_size(10.5).font_medium().text_color(t.blocked).child(statusText)
        : null;
    const projFolders = projectFolders(this.pm());
    const folderAlias = threadFolderBadge(task, projFolders);
    const folderPath = folderAlias ? (projFolders.find(f => f.alias === folderAlias)?.path || '') : '';
    const hasMetaChips = Boolean((inTabBar && threadNum) || statusBadge || folderAlias || task.branch || engine || (closedInfo && !quiet) || parent);
    const metaStrip = hasMetaChips ? h_flex().flex_1().min_w(0).flex_wrap().gap(5).items_center()
      .when(inTabBar && Boolean(threadNum), el => el.child(h_flex().id('thread-number').h(19).px(5.5).rounded(5).flex_none()
        .items_center().bg(surf.pillMuted).font_family('monospace').text_size(11).text_color(t.muted).child(threadNum)))
      .when(Boolean(statusBadge), el => el.child(statusBadge))
      .when(Boolean(folderAlias), el => el.child(this.withTip('thread-folder', h_flex().id('thread-folder').h(19).px(6).gap(4).rounded(5)
        .flex_none().max_w(140).items_center().bg(surf.pillMuted)
        .child(this.icon('folder', 11).text_color(t.dim))
        .child(div().min_w(0).truncate().font_family('monospace').text_size(11).text_color(t.muted).child(folderAlias)),
        word(lang, 'folderAliasTip', folderAlias, folderPath), t, { panel: true, placement: 'below-left', wrap: true, flexNone: true })))
      .when(Boolean(task.branch), el => el.child(this.withTip('thread-branch', h_flex().id('thread-branch').h(19).px(6).rounded(5)
        .flex_none().max_w(240).items_center().bg(surf.well)
        .child(div().min_w(0).truncate().font_family('monospace').text_size(11).text_color(t.muted).child(task.branch)),
        workerCtxText ? `${task.branch} · ${workerCtxText}` : task.branch, t, { panel: true, placement: 'below-left', wrap: true, flexNone: true })))
      .when(Boolean(engine), el => el.child(h_flex().h(19).px(5.5).rounded(5).flex_none().items_center().bg(surf.pillMuted)
        .font_family('monospace').text_size(10.5).text_color(t.dim)
        .child(`${engine}${wasEscalated(task) ? ' ↑' : ''}`)))
      .when(Boolean(closedInfo && !quiet), el => el.child(this.withTip('thread-closed-pill', h_flex().id('thread-closed-pill').h(19).px(6).rounded(5)
        .flex_none().items_center().bg(withAlpha(t.blocked, surf.dark ? .13 : .10))
        .text_size(10.5).text_color(t.blocked).child(word(lang, 'closedReattach')),
        closedTip(lang, closedInfo), t, { panel: true, placement: 'below-left', wrap: true, flexNone: true })))
      .when(Boolean(parent), el => el.child(this.withTip('thread-parent', h_flex().id('thread-parent').h(19).px(6).gap(4).rounded(5)
        .max_w(240).items_center().cursor_pointer().bg(surf.pillMuted).text_color(t.muted)
        .hover(s => s.bg(t.hover).text_color(t.foreground))
        .accessibility_label(word(lang, 'partOf', parent.title))
        .on_click((_e, cx) => this.openThread(parent.task, cx, { insertAdjacent: true }))
        .child(svg(ICON('hook-up')).size(11).flex_none())
        .when(Boolean(parentNum), el => el.child(div().flex_none().font_family('monospace').text_size(10.5).text_color(t.dim).child(parentNum)))
        .child(div().min_w(0).truncate().text_size(11).child(word(lang, 'partOf', parent.title))),
        word(lang, 'openThread'), t, { panel: true, placement: 'below-left' }))) : null;

    const inlineTabInMeta = width >= 440 && Boolean(tabBar) && Boolean(metaStrip);
    let headerBar;
    if (inTabBar) {
      // Plan B unified frameless info header: title appears ONCE cleanly (tab bar carries only `#NNN`),
      // actions sit flush at top-right, and branch / parent / view-switcher nest tightly below with zero border_b.
      const titleEl = div().id('thread-title').w_full().whitespace_normal()
        .text_size(14.5).line_height('20px').font_semibold().text_color(t.foreground)
        .child(fullTitle);
      const titleNode = this.withTip('thread-title', titleEl, titleTip, t, { panel: true, placement: 'below-left', wrap: true, flex1: true });
      headerBar = v_flex().id('thread-topbar').w_full().min_w(0).flex_none().px(16).pt(12).pb(4).gap(7)
        .child(h_flex().w_full().min_w(0).gap(8).items_start()
          .child(h_flex().h(20).flex_none().items_center().child(statusDotEl))
          .child(titleNode)
          .when(Boolean(actions), el => el.child(h_flex().h(20).flex_none().items_center().child(actions))))
        .when(Boolean(metaStrip || tabBar), el => el.child(v_flex().id('thread-subbar').w_full().min_w(0).pl(26).gap(6)
          .when(inlineTabInMeta, row => row.child(h_flex().w_full().min_w(0).gap(8).items_center().justify_between()
            .child(metaStrip)
            .child(tabBar)))
          .when(!inlineTabInMeta && Boolean(metaStrip), row => row.child(metaStrip))
          .when(!inlineTabInMeta && Boolean(tabBar), row => row.child(h_flex().w_full().items_center().child(tabBar)))));
    } else {
      const leadingEl = h_flex().flex_none().gap(5).items_center()
        .child(statusDotEl)
        .when(Boolean(threadNum), el => el.child(div().id('thread-number').flex_none().font_family('monospace').text_size(12.5).text_color(t.dim).child(threadNum)));
      headerBar = this.renderSplitTopBar({
        id: 'thread-topbar',
        backId: 'thread-back',
        onBack: cx => {
          this.panelClosing = false;
          this.detail = false;
          this.resetThreadChange();
          this.listShown = true;
          this.sideTab = 'threads';
          this._panelOpenedFromClosed = false;
          this.syncVisibleSideTab(cx);
          this.notifyPanes(cx, { shell: true, conv: true, side: true });
        },
        backTip: word(lang, 'backToThreads'),
        leading: leadingEl,
        titleId: 'thread-title',
        title: fullTitle,
        titleTip,
        actions,
        closeId: 'thread-close',
        onClose: null,
        closeTip: word(lang, 'closeSidePanel'),
        compactBar: true,
        t,
      });
    }

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

    // Two-layer Steps card: Plan B tonal pod with clean recessed sub-step wells (zero tree wires).
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
        return h_flex().w_full().min_w(0).flex_none().pb(2).items_center()
          .child(this.withTip('thread-log-earlier', h_flex().id('thread-log-earlier').h(22).px(7).gap(5).rounded(6).items_center()
            .bg(surf.well).text_size(11).text_color(err ? t.blocked : t.dim).accessibility_label(tip)
            .when(!busy, el => el.cursor_pointer().hover(s => s.bg(t.hover).text_color(err ? t.blocked : t.foreground))
              .on_click((_e, cx) => this.loadEarlierThreadLog(cx)))
            .child(busy ? svg(SPINNER).size(12).flex_none().text_color(t.muted).spin(900) : this.icon('earlier', 12.5))
            .child(tip), tip, t, { panel: true, placement: 'below-left' }));
      })() : null;
      const dotMuted = withAlpha(t.muted || t.dim, surf.dark ? .42 : .52);
      const entries = visibleLog.length ? visibleLog.map((entry, i) => {
        const latest = i === visibleLog.length - 1;
        const entryText = logText(lang, entry.text, true);
        if (!this.threadLogExpanded) {
          const compactText = compactLogLine(entryText);
          return this.withTip(`thread-entry-${entry.n ?? i}`, h_flex().id(`thread-entry-${entry.n ?? i}`).w_full().min_w(0).flex_none()
            .min_h(26).px(7).py(3).gap(8).rounded(6).items_center().overflow_hidden()
            .when(latest, el => el.bg(surf.podWell))
            .when(!latest, el => el.hover(s => s.bg(t.hover)))
            .child(div().size(5.5).flex_none().rounded_full().bg(latest ? t.accent : dotMuted))
            .child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(clock(entry.at, today)))
            .child(div().flex_1().min_w(0).overflow_hidden().truncate().text_size(12.2)
              .text_color(latest ? t.foreground : t.muted).child(compactText)), entryText, t, { panel: true, placement: 'above-left', wrap: true, full: true, flexNone: true });
        }
        return v_flex().id(`thread-entry-${entry.n ?? i}`).w_full().min_w(0).flex_none().px(8).py(6).gap(3).rounded(6)
          .when(latest, el => el.bg(surf.podWell))
          .child(h_flex().gap(6).items_center()
            .child(div().size(5.5).flex_none().rounded_full().bg(latest ? t.accent : dotMuted))
            .child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(clock(entry.at, today))))
          .child(this.selectableText(`thread-log-txt-${this.thread}-${entry.n ?? i}`, entryText).w_full().min_w(0)
            .text_size(12.5).text_color(latest ? t.foreground : t.muted));
      }) : [div().px(6).py(4).text_size(12).text_color(t.dim).child(word(lang, 'noLog'))];
      const logScrollHandle = this.tabScrollHandle('log');
      if (this.threadAnchor && visibleLog.length) {
        const idx = visibleLog.findIndex(e => e.n === this.threadAnchor.n);
        this.threadAnchor.left--;
        if (idx >= 0) logScrollHandle?.scroll_to_item?.((earlierLogRow ? 1 : 0) + idx);
        if (this.threadAnchor.left <= 0 || idx < 0) this.threadAnchor = null;
        else if (cx && !this.threadTicking) {
          this.threadTicking = true;
          cx.timer.after(16, cx => { this.threadTicking = false; cx.notify(); });
        }
      }
      const logPodHeader = h_flex().w_full().min_w(0).flex_none().pl(4).pr(4).gap(6).items_center()
        .child(div().flex_none().text_size(11.5).font_semibold().text_color(t.muted).child(word(lang, 'threadLogTab')))
        .when(log.length > 0, el => el.child(div().flex_none().font_family('monospace').text_size(11).text_color(t.dim).child(String(log.length))))
        .child(div().flex_1().min_w(0))
        .when(canExpandRecent, el => el.child(h_flex().id('thread-log-toggle').h(19).px(6).rounded(5).flex_none()
          .items_center().cursor_pointer().bg(surf.well).text_size(10.5).text_color(t.muted)
          .hover(s => s.bg(t.hover).text_color(t.foreground))
          .on_click((_e, cx) => { this.threadLogExpanded = !this.threadLogExpanded; cx.notify(); })
          .child(this.threadLogExpanded ? word(lang, 'collapseLog') : word(lang, 'showAllLog', log.length))));
      const logList = v_flex().id('thread-log').w_full().min_w(0).flex_1().min_h(0).gap(2).overflow_y_scrollbar()
        .when(Boolean(logScrollHandle), el => el.track_scroll(logScrollHandle))
        .on_scroll_wheel((e, cx) => {
          if (e.delta.y) this.threadAnchor = null;
          if (this.hoverKey) { this.hoverKey = ''; cx.notify(); }
        })
        .when(Boolean(earlierLogRow), el => el.child(earlierLogRow))
        .children(entries);
      bodyEl = v_flex().id('thread-log-card').w_full().min_w(0).flex_1().min_h(0).rounded(10).p(8).gap(6).bg(surf.pod)
        .child(logPodHeader)
        .child(logList);
    }

    return v_flex().w_full().h_full().min_w(0)
      .child(headerBar)
      .child(this.sideScrollBody(v_flex().w_full().min_w(0).flex_1().min_h(0).px(16).pt(inTabBar ? 6 : 10).pb(14).gap(10)
        .when(!inTabBar && inlineTabInMeta, el => el.child(h_flex().id('thread-subbar').min_h(28).flex_none().gap(10).items_center().justify_between()
          .child(tabBar)
          .child(div().flex_1().min_w(0).child(h_flex().w_full().justify_end().child(metaStrip)))))
        .when(!inTabBar && !inlineTabInMeta && Boolean(metaStrip), el => el.child(metaStrip))
        .when(!inTabBar && !inlineTabInMeta && Boolean(tabBar), el => el.child(tabBar))
        .when(activeTab === 'log' && Boolean(asks), el => el.child(v_flex().id('thread-question').w_full().min_w(0).flex_none().max_h(320).overflow_y_scrollbar()
          .rounded(10).p(10).gap(4).bg(withAlpha(t.blocked, surf.dark ? .085 : .06))
          .when(Boolean(asks.text), el => el.child(this.selectableText(`thread-ask-${this.thread}`, logText(lang, asks.text, true)).px(4).pb(4).w_full()
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
          word(lang, 'threadOffline'), cx => this.sendThread(cx), t, 14, false, cx))));
  }

  currentSideViewKey() {
    const activeTab = this.activeSideTab();
    const tabPrefix = activeTab ? `tab:${activeTab.id}:` : (this.hasSideTabs() ? 'tab:index:' : '');
    if (this.detail) {
      if (this.isThreadChangeOpen()) return `${tabPrefix}change:${this.thread}:${this.change?.level || 'commits'}:${this.change?.filePath || ''}`;
      return `${tabPrefix}detail:${this.thread}:${this.threadTab || 'log'}`;
    }
    const onLib = this.sideTab === 'library' && (this.librarySupported() || this.activeDoc?.root === 'repo');
    const onMem = this.sideTab === 'memory' && this.memorySupported();
    const curTab = onLib ? 'library' : onMem ? 'memory' : 'threads';
    if (this.historyView?.tab === curTab) return `${tabPrefix}history:${curTab}:${this.historyView.path || ''}`;
    if (this.editingDoc?.tab === curTab) return `${tabPrefix}edit:${curTab}:${this.editingDoc.path || ''}`;
    if (this.activeDoc?.tab === curTab) return `${tabPrefix}doc:${curTab}:${this.activeDoc.root}/${this.activeDoc.path}`;
    return `${tabPrefix}list:${curTab}`;
  }

  buildPanelShell(pm, t, today, cx, { open, layout, dragging, inlineSide = null } = {}) {
    const lang = this.lang;
    const dark = isDarkTheme(t);
    const cardWidth = layout.cardWidth;
    const slotWidth = layout.slotWidth;
    const isSheet = layout.layoutKind === 'sheet';
    const showContent = open || this.panelMounted;
    const sideNode = showContent ? (inlineSide || this._sideEntity) : null;

    if (isSheet) {
      if (!showContent) {
        return h_flex().id('pm-project-panel').h_full().flex_none().w(0).overflow_hidden();
      }
      return h_flex().id('pm-panel-sheet-layer').absolute().inset(0).overflow_hidden()
        .child(div().id('pm-panel-backdrop').flex_1().h_full()
          .bg(withAlpha('#000000', dark ? .42 : .22))
          .opacity(open ? 1 : 0)
          .when(this.measured, el => el.transition('opacity', { duration: 180, easing: 'ease-out' }))
          .on_click((_e, clickCx) => this.closeSidePanel(clickCx)))
        .child(keepPress(h_flex().id('pm-project-panel').relative().h_full().flex_none().overflow_hidden().justify_start()
          .pr(SPLIT_CARD_MARGIN_R).pb(10)
          .w(open ? cardWidth + SPLIT_CARD_MARGIN_R : 0)
          .when(this.measured && !dragging, el => el.transition('width', { duration: 180, easing: 'ease-out' }))
          .when(Boolean(sideNode), el => el.child(sideNode)), this.keyFocus));
    }

    const lit = dragging || this.gripLit;
    const grip = div().id('panel-grip').absolute().left(0).top(0).bottom(10).w(10).cursor_col_resize()
      .accessibility_label(word(lang, 'resetPanelWidthTip'))
      .on_hover((hovered, hoverCx) => {
        if (hovered !== this.gripLit) {
          this.gripLit = hovered;
          this.notifyShell(hoverCx);
        }
      })
      .on_mouse_down('left', (e, downCx) => this.gripDown(e, downCx))
      .child(div().absolute().left(0).right(0).top(12).bottom(12)
        .opacity(lit ? 1 : 0)
        .when(this.measured, el => el.transition('opacity', { duration: 120, easing: 'ease-out' }))
        .child(div().absolute().left(4).top(0).bottom(0).w(2).rounded(1)
          .bg(withAlpha(t.accent, dragging ? .9 : .55)))
        .child(h_flex().size_full().items_center().justify_center()
          .child(div().w(3).h(28).rounded(2).bg(dragging ? t.accent : t.muted))));

    return h_flex().id('pm-project-panel').relative().h_full().flex_none().overflow_hidden().justify_start()
      .pl(SPLIT_GRIP_OVERHANG).pr(SPLIT_CARD_MARGIN_R).pb(10)
      .w(open ? slotWidth : 0)
      .when(this.measured && !dragging, el => el.transition('width', { duration: 180, easing: 'ease-out' }))
      .when(Boolean(sideNode), el => el.child(sideNode))
      .when(open, el => el.child(grip));
  }

  renderConversationPane(cx) {
    const pm = this.pm();
    const t = theme();
    if (!pm) return v_flex().flex_1().min_w(0).h_full();
    const lang = this.lang || this.state?.lang || 'en';
    const now = new Date(), today = iso(now), yesterday = iso(new Date(now.getTime() - 86400000));
    const alreadyInRender = Boolean(this._inRender);
    if (!alreadyInRender) {
      this._inRender = true;
      this._renderTerms = machineView(terminals(), this.machine);
      this._renderTermsMachine = this.machine;
      this._renderLive = machineView(agents(), this.machine);
      this._renderLiveMachine = this.machine;
      this._renderProjTasks = null;
      this._renderSpacesTabs = null;
      this._renderTaskNumIdx = null;
      this._renderMdLinkMap = null;
    }
    try {
      const pmTerm = this.pmTerminal();
      const pmStatus = pmLiveStatus(pmTerm, this.live());
      const activeTurn = this.activePmTurn();
      const working = this.isPmWorking(pmTerm, this.live(), activeTurn);
      // FS-16: Self-sustaining 1-second tick inside conversation pane render so dual-entity mode never freezes elapsed time.
      const needsTurnTick = working && Boolean(this.onStage) && Boolean(activeTurn && (Number(activeTurn.started_ms) > 0 || activeTurn.activity));
      if (needsTurnTick && !this.turnTickTimer && cx?.timer?.after) {
        this.turnTickTimer = true;
        const scheduledAt = this.nowMs();
        cx.timer.after(1000, liveCx => {
          this.turnTickTimer = false;
          if (this.nowMs() >= scheduledAt + 500 && Boolean(this.onStage) && this.isPmWorking(this.pmTerminal(), this.live(), this.activePmTurn())) {
            this.notifyPanes(liveCx, { shell: false, conv: true });
          }
        });
      }
      const queuedCount = this.pending.filter(p => p.queued && !p.failed && !p.received).length;
      const pendingSending = this.pending.some(p => !p.failed && !p.queued && !p.received);
      const convActView = pmTerm
        ? pmActivityView(lang, {
          turn: activeTurn,
          turn2: this.activePmTurn2(),
          supervised: this.activePmSupervised(),
          working,
          pendingSending,
          nowMs: this.nowMs(),
          serverNowMs: this.serverNowMs || 0,
          receivedAtMs: this.serverNowAt || 0,
          agentKind: pm.agent || '',
        })
        : null;
      const typingNow = Boolean(convActView?.active) || Boolean(working) || pendingSending;
      const tl = this.resolveTimelineData(pm, today, typingNow);
      const { items, stops, blocks, newest, keys, foldedTasks, waiting } = tl;
      this.items = items;
      this._blockKeySet = tl.blockKeySet;
      if (this.answering && !stops.some(s => (s.thread ? askKey(s.thread) : s.key) === this.answering.key)) this.answering = null;
      this.atWork = workingTasks(this.terms(), this.live());
      if (this.newest && newest !== this.newest && !this.unfolded.has(this.newest)) this.unfolded.set(this.newest, true);
      this.newest = newest;
      this.keys = keys;
      if (!this.seen && this.events.length) this.seen = new Set(this.keys);
      const showEarlier = Boolean(this.logState?.earlier || this.earlierLoading || this.earlierError);
      const topOffset = showEarlier ? 1 : 0;
      this.lastBlocks = blocks;
      this.lastTopOffset = topOffset;
      if (blocks.length !== this.count) {
        if (blocks.length > this.count && blocks.length && !this.away) this.follow();
        this.count = blocks.length;
      }
      if (this.jumpTarget && blocks.length) {
        const jumpRow = rowOfKey(blocks, this.jumpTarget.key);
        this.jumpTarget.left--;
        if (jumpRow >= 0) this.scroll.scroll_to_item(topOffset + jumpRow);
        if (this.jumpTarget.left <= 0 || jumpRow < 0) this.jumpTarget = null;
        else if (!this.ticking) { this.ticking = true; cx.timer.after(16, liveCx => { this.ticking = false; liveCx.notify(); }); }
      } else if (this.earlierAnchor && blocks.length) {
        const anchorRow = findAnchorBlock(blocks, this.earlierAnchor.anchor);
        this.earlierAnchor.left--;
        if (anchorRow >= 0) this.scroll.scroll_to_item(topOffset + anchorRow);
        if (this.earlierAnchor.left <= 0 || anchorRow < 0) this.earlierAnchor = null;
        else if (!this.ticking) { this.ticking = true; cx.timer.after(16, liveCx => { this.ticking = false; liveCx.notify(); }); }
      } else if (blocks.length && this.settle > 0) {
        this.settle--;
        this.scroll.scroll_to_item(topOffset + blocks.length);
        if (!this.ticking) { this.ticking = true; cx.timer.after(16, liveCx => { this.ticking = false; liveCx.notify(); }); }
      }
      const heights = blocks.map(b => this.heights.get(b.key) || 0), tall = this.tall || this.high;
      this.lastBlocks = blocks;
      this.lastTopOffset = topOffset;
      this.lastHeights = heights;
      this.lastTall = tall;
      this.tasks = foldedTasks;
      const ring = stops.length ? ringCx => {
        const next = bellNext(stops, this.bell);
        this.bell = { key: next.key, seen: stops.map(s => s.key) };
        if (next.thread) {
          const id = bellThread(next, this.tasks || foldReviews(this.state.tasks), this.detail ? this.thread : '');
          if (id) this.openThread(id, ringCx);
          return -1;
        }
        const key = next.key;
        const seq = (this.flashSeq || 0) + 1;
        this.flashSeq = seq;
        this.flash = key;
        this.flashTone = 'blocked';
        ringCx.timer.after(1500, tCx => { if (this.flashSeq === seq && this.flash === key) { this.flash = ''; tCx.notify(); } });
        ringCx.notify();
        const row = rowOf(blocks, items[next.at]);
        if (row >= 0) this.rest(riseAfterJump(this.rise, heights, row, tall, TAIL));
        return row >= 0 ? topOffset + row : -1;
      } : null;
      const layout = this._lastLayout || this.currentSplitLayout();
      const padX = layout.conversationPadX || 28;
      const center = el => h_flex().w_full().justify_center().px(padX).child(div().w_full().min_w(0).max_w(COLUMN).child(el));
      const above = (b, n) => (n === 0 ? 0 : b.kind === 'turn' && !b.first ? 12 : 22);
      const room = TAIL + (showEarlier ? 34 : 0) + heights.reduce((sum, h) => sum + h, 0) + TAIL - tall;
      const body = v_flex().id('pm-project-timeline').flex_1().min_h(0).pt(TAIL).overflow_y_scrollbar()
        .track_scroll(this.scroll)
        .on_size_change((size, sizeCx) => {
          const prev = this.tall;
          this.tall = size.height;
          if (prev > 0 && size.height !== prev && !this.panelDrag && this.panelTransitioning !== true) {
            this.resized(sizeCx);
          }
        })
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
          .id(`block-${b.key}`).on_size_change((size, sizeCx) => {
            if (this.heights.get(b.key) === size.height) return;
            this.heights.set(b.key, size.height);
            if (Boolean(this.panelDrag) || this.panelTransitioning === true) return;
            this.resized(sizeCx);
          }))
          : [center(div().text_color(t.dim).child(word(lang, 'empty')))])
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
      const rawUndelivered = pm.undelivered && typeof undeliveredBannerText === 'function'
        ? undeliveredBannerText(lang, pm.undelivered)
        : '';
      const pmUndeliveredText = typeof rawUndelivered === 'string' ? rawUndelivered : '';
      const actionFeedback = this.pmActionFeedback?.pm === this.pmName && this.pmActionFeedback?.text
        ? this.pmActionFeedback
        : null;
      const hasMainDraft = Boolean(this.draft?.trim() || this.input?.value?.()?.trim() || this.files?.length || this.quotes?.length);
      const pmBusyView = (pmTerm && !showOfflinePmBar && !pmBlockedText)
        ? pmBusyComposerView(lang, {
          actView: convActView,
          turn2: this.activePmTurn2(),
          working,
          interrupting: this.interruptingPm === this.pmName,
          agentKind: pm.agent || '',
          hasDraft: hasMainDraft,
          queuedCount,
        })
        : null;
      const selectionBar = this.selectionPopover(t);
      const footer = v_flex().w_full().gap(6)
        .when(Boolean(selectionBar), el => el.child(h_flex().w_full().justify_end().child(selectionBar)))
        .when(showOfflinePmBar, el => el.child(this.offlinePmBar(pmStart, t)))
        .when(Boolean(actionFeedback), el => el.child(this.pmActionFeedbackBar(actionFeedback, t, cx)))
        .when(Boolean(pmUndeliveredText), el => el.child(this.pmUndeliveredBar(pmUndeliveredText, t)))
        .when(Boolean(pmBlockedText), el => el.child(this.pmBlockedBar(pmBlockedText, t)))
        .when(Boolean(pmBusyView), el => el.child(this.pmBusyBar(pmBusyView, t, cx)))
        .child(this.composer('say', this.input, this.draft, Boolean(pmTerm || this.isPmStarting()), word(lang, 'say', projectName(pm) || pm.name),
          offlineTip, sendCx => this.sendMain(sendCx), t, 16, true, cx));
      this.ringAction = ring;
      if (this.bodyOnly) this.publishHeaderState(this.buildHeaderData(pm, waiting, Boolean(ring)));
      return v_flex().flex_1().min_w(0).h_full()
        .when(!this.bodyOnly, el => el.child(this.header(pm, waiting, ring, t)))
        .when(Boolean(lostEl), el => el.child(center(lostEl).flex_none().pt(12)))
        .child(body)
        .child(keepPress(center(footer).flex_none().pb(20).pt(4), this.keyFocus));
    } finally {
      if (!alreadyInRender) {
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

  renderSideSplitPane(cx) {
    const pm = this.pm();
    const t = theme();
    if (!pm) return v_flex().w_full().h_full();
    const today = iso(new Date());
    const open = this.isPanelOpen();
    if (!open && !this.panelMounted) return v_flex().w_full().h_full();
    const layout = this._lastLayout || this.currentSplitLayout();
    const width = layout.cardWidth;
    const alreadyInRender = Boolean(this._inRender);
    if (!alreadyInRender) {
      this._inRender = true;
      this._renderTerms = machineView(terminals(), this.machine);
      this._renderTermsMachine = this.machine;
      this._renderLive = machineView(agents(), this.machine);
      this._renderLiveMachine = this.machine;
      this._renderProjTasks = null;
      this._renderSpacesTabs = null;
      this._renderTaskNumIdx = null;
      this._renderMdLinkMap = null;
    }
    try {
      const hasTabs = this.hasSideTabs();
      const activeTab = this.activeSideTab();
      const showLibrary = this.sideTab === 'library' && (this.librarySupported() || this.activeDoc?.root === 'repo');
      const showMemory = this.sideTab === 'memory' && this.memorySupported();
      const inner = (hasTabs && !activeTab)
        ? (showLibrary ? this.libraryPanel(pm, t, width, today, cx)
          : showMemory ? this.memoryPanel(pm, t, width, today, cx)
          : this.threadsPanel(pm, t, width))
        : this.detail
          ? this.panel(t, today, width, cx)
          : showLibrary ? this.libraryPanel(pm, t, width, today, cx)
          : showMemory ? this.memoryPanel(pm, t, width, today, cx)
          : this.threadsPanel(pm, t, width);

      // Sub-view 120ms ease-out opacity transition when switching between List / Doc / Thread Detail / Diff.
      const nextViewKey = this.currentSideViewKey();
      let fadeOpacity = null;
      if (this.measured && open && this._sideViewKey && this._sideViewKey !== nextViewKey && cx?.timer?.after) {
        this._sideViewKey = nextViewKey;
        this._sideFading = 'start';
        fadeOpacity = 0;
        this._sideFadeTimer?.cancel?.();
        this._sideFadeTimer = cx.timer.after(16, tCx => {
          this._sideFading = 'end';
          this.notifyPanes(tCx, { shell: false, side: true });
          this._sideFadeTimer = tCx.timer.after(140, doneCx => {
            this._sideFading = false;
            this._sideFadeTimer = null;
            this.notifyPanes(doneCx, { shell: false, side: true });
          }) || null;
        }) || null;
      } else {
        this._sideViewKey = nextViewKey;
        if (this._sideFading === 'start') fadeOpacity = 0;
        else if (this._sideFading === 'end') fadeOpacity = 1;
      }

      // Outer card geometry:
      // - Open/Close slide (0 <-> W): fixed width so left border & rounded corners stay visible from frame 1.
      // - Same-open resize (compact <-> split): w_full() outer card keeps topbars (and right-edge close button)
      //   flush to both edges on every frame, while each sub-view's scrollable body locks width via sideScrollBody().
      const isSlideOpenClose = !open || this._panelSlideFromZero === true;
      const bodyWrap = v_flex().flex_1().min_h(0).w_full().min_w(0).child(inner);
      const styledBody = fadeOpacity !== null
        ? bodyWrap.opacity(fadeOpacity).transition('opacity', { duration: 120, easing: 'ease-out' })
        : bodyWrap;
      const banners = hasTabs ? this.sideTabBanners(t, cx) : [];

      const card = v_flex().id('side-split-card').h_full().rounded(12).overflow_hidden()
        .bg(t.background).border_1().border_color(t.border)
        .when(!isDarkTheme(t), el => el.shadow_xs())
        .when(isSlideOpenClose, el => el.w(width).flex_none())
        .when(!isSlideOpenClose, el => el.w_full().min_w(0))
        .child(this.sideHeaderBar(t, width, cx))
        .when(banners.length > 0, el => el.children(banners))
        .child(styledBody);

      return keepPress(card, this.keyFocus);
    } finally {
      if (!alreadyInRender) {
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

  render(cx) {
    if (this.lightboxOverlayMode) return this.renderImageLightbox(cx);
    if (this.agentWindow === 'titlebar' || this.agentWindow === 'chat') return this.renderAgentWindow(cx);
    if (this.headerOnly) return this.renderHeaderOnly(cx);
    const t = theme();
    this.lang = this.state.lang;
    const lang = this.lang;
    const rawRef = shared(SHARED);
    const ref = projectRef(rawRef), wanted = ref.key;
    const shellOnly = this._shellOnlyRender === true;
    this._shellOnlyRender = false;
    if (ref.machine !== this.machine) {
      // A project on another machine (or back here): that machine's ledger, read now.
      // The language stays until that ledger gives its own.
      this.closeAllAgentWindows(cx, { defer: true });
      this.machine = ref.machine; this.state = { pms: [], tasks: [], lang: this.state.lang }; this.stateFor = null;
      this.error = ''; this.logError = ''; this.remoteHome = ''; this.remoteNoProject = '';
      this.remoteNoLibrary = ''; this.remoteNoMemory = ''; this.remoteNoSession = ''; this.remoteNoChange = ''; this.remoteNoTasks = '';
      this.logSlug = ''; this.logState = null; this.logReceipts = []; this.logTurn = null; this.logTurn2 = null; this.logSupervised = undefined; this.pmActionFeedback = null; this.clockOffsetMs = 0; this.serverNowMs = 0; this.serverNowAt = 0; this.noProjectSendFor = '';
      this.earlierLoading = false; this.earlierError = ''; this.earlierAnchor = null;
      this.threadLog = null; this.threadLogKept = []; this.threadEarlierLoading = false; this.threadEarlierError = ''; this.threadAnchor = null;
      this.threadLogExpanded = false;
      this.epicOverrides = new Map(); this.expandedDone = new Set(); this.substepsToggle = {}; this.clearHoverNow(null); this.highlightThread = ''; this.pendingScrollThread = '';
      this.resetThreadSession();
      this.resetThreadChange();
      this.resetThreadsHistoryState();
      this.librarySlug = ''; this.libraryRoots = []; this.libraryFiles = []; this.libraryRead = false; this.libraryProbed = false; this.libraryStale = false; this.libraryError = '';
      this.libraryDropBusy = ''; this.libraryDropError = '';
      this.memorySlug = ''; this.memoryData = null; this.memoryRead = false; this.memoryStale = false; this.memoryError = '';
      this.memoryBusy = ''; this.memoryNoticeError = ''; this.deletedBanner = null;
      this.mention = null; this.mentionDismissed = null;
      this.searchOpen = false; this.searchQuery = ''; this.searchScope = 'all'; this.searchIndex = 0; this.searchKey = '';
      this.inlineFilterOpen = false;
      this.imageLightbox = null;
      if (this.lightboxOverlayId) { this.closeOverlayIds([this.lightboxOverlayId], cx, { defer: true }); this.lightboxOverlayId = ''; }
      this.jumpTarget = null; this.flash = ''; this.flashPara = ''; this.flashTone = 'blocked';
      this.quotes = []; this.hoveredMsg = ''; this.hoverClipboard = null; this.selectionBar = null; this.lastBlocks = [];
      this.clearParaHoverNow(null);
      this.repoFilesSlug = ''; this.repoFilesRepo = ''; this.repoFilesSig = ''; this.repoFiles = []; this.repoFilesRead = false; this.repoFilesLoading = false; this.repoFilesAgain = false; this.repoFilesError = ''; this.repoFilesTruncated = false; this.repoFilesAt = 0;
      this.resetFoldersPopoverState();
      this.resetLibraryDocState();
      this.resetRenderCaches();
      if (!this.bringingBack) { this.bringBackOpen = false; this.bringBackProgress = null; }
      cx.timer.after(0, cx => {
        this.searchInput?.set_value('');
        if (findStage(layout())?.active === 'pm-project') this.keyFocus?.focus?.();
        this.refresh(cx);
      });
    }
    if (wanted !== this.pmName) {
      // Another project: its own log, no bubbles or panel from the last one.
      if (this.pmName) {
        this.snapshotActiveTabInputs();
        this.persistSideTabs(this.pmName);
      }
      this.releaseAllTabHandles();
      this.tabState = createSideTabsState();
      this.confirmCloseTabId = ''; this.tabMenu = null; this.tabLimitBanner = ''; this.hoveredTabId = '';
      this.closeAllAgentWindows(cx, { defer: true });
      const byPm = this.pendingByPm ||= new Map();
      if (this.pmName) byPm.set(this.pmName, this.pending);
      this.pmName = wanted; this.events = []; this.logReceipts = []; this.logTurn = null; this.logTurn2 = null; this.logSupervised = undefined; this.pmActionFeedback = null; this.pending = this.hydrateQueue(wanted); this.detail = false; this.thread = ''; this.threadTask = null;
      this.pmDialog = null; this.pmSendBlockError = ''; this.pmDialogAt = 0; this.lastLogReadAt = 0; this.confirmLogProbes = new Set();
      this.logSlug = ''; this.logState = null; this.earlierLoading = false; this.earlierError = ''; this.earlierAnchor = null;
      this.threadLog = null; this.threadLogKept = []; this.threadEarlierLoading = false; this.threadEarlierError = ''; this.threadAnchor = null;
      this.threadLogExpanded = false;
      this.epicOverrides = new Map(); this.expandedDone = new Set(); this.substepsToggle = {}; this.clearHoverNow(null); this.highlightThread = ''; this.pendingScrollThread = '';
      this.resetThreadSession();
      this.resetThreadChange();
      this.resetThreadsHistoryState();
      this.librarySlug = ''; this.libraryRoots = []; this.libraryFiles = []; this.libraryRead = false; this.libraryProbed = false; this.libraryStale = false; this.libraryError = '';
      this.libraryQuery = ''; this.libraryDropBusy = ''; this.libraryDropError = '';
      this.memorySlug = ''; this.memoryData = null; this.memoryRead = false; this.memoryStale = false; this.memoryError = '';
      this.memoryQuery = ''; this.memoryBusy = ''; this.memoryNoticeError = ''; this.deletedBanner = null;
      this.docFindOpen = false; this.docFindQuery = ''; this.docJumpQuery = ''; this.docMatchPos = 0;
      this.mention = null; this.mentionDismissed = null;
      this.searchOpen = false; this.searchQuery = ''; this.searchScope = 'all'; this.searchIndex = 0; this.searchKey = '';
      this.inlineFilterOpen = false;
      this.imageLightbox = null;
      if (this.lightboxOverlayId) { this.closeOverlayIds([this.lightboxOverlayId], cx, { defer: true }); this.lightboxOverlayId = ''; }
      this.jumpTarget = null;
      this.quotes = []; this.hoveredMsg = ''; this.hoverClipboard = null; this.selectionBar = null; this.lastBlocks = [];
      this.clearParaHoverNow(null);
      this.repoFilesSlug = ''; this.repoFilesRepo = ''; this.repoFilesSig = ''; this.repoFiles = []; this.repoFilesRead = false; this.repoFilesLoading = false; this.repoFilesAgain = false; this.repoFilesError = ''; this.repoFilesTruncated = false; this.repoFilesAt = 0;
      this.resetFoldersPopoverState();
      this.resetLibraryDocState();
      this.resetRenderCaches();
      this.seen = null; this.count = 0; this.settle = 0; this.away = false; this.rise = 0; this.heights = new Map();
      this.unfolded = new Map(); this.newest = '';
      this.bell = null; this.flash = ''; this.flashPara = ''; this.flashTone = 'blocked'; this.answering = null;
      this._panelOpenedFromClosed = false; this._sideViewKey = '';
      if (!this.bringingBack) { this.bringBackOpen = false; this.bringBackProgress = null; }
      cx.timer.after(0, cx => {
        this.searchInput?.set_value('');
        this.threadsInput?.set_value('');
        this.libraryInput?.set_value('');
        this.memoryInput?.set_value('');
        this.docFindInput?.set_value('');
        this.docNameInput?.set_value('');
        this.memDescInput?.set_value('');
        this.docEditorInput?.set_value('');
        this.folderAliasInput?.set_value('');
        this.folderRemoteInput?.set_value('');
        this.showMainDraft();
        this.hydrateSideTabs(wanted, cx);
        this.readLog(cx);
        if (this.machine || this.sideTab === 'library') this.readLibrary(cx);
        if (this.sideTab === 'memory') this.readMemory(cx);
        if (findStage(layout())?.active === 'pm-project') this.keyFocus?.focus?.();
        this.notifyPanes(cx, { shell: true, conv: true, side: true });
      });
    }
    const onStage = findStage(layout())?.active === 'pm-project';
    if (onStage && !this.onStage) cx.timer.after(0, () => this.keyFocus.focus());
    if (!onStage && this.onStage) {
      this.clearHoverNow(null); this.clearParaHoverNow(null); this.searchOpen = false;
      this.resetFoldersPopoverState();
      this.imageLightbox = null;
      if (this.lightboxOverlayId) { this.closeOverlayIds([this.lightboxOverlayId], cx, { defer: true }); this.lightboxOverlayId = ''; }
      this.closeAllAgentWindows(cx, { defer: true });
    }
    this.onStage = onStage;
    if (rawRef?.thread && rawRef?.jumpSeq && rawRef.jumpSeq !== this.lastJumpSeq) {
      this.lastJumpSeq = rawRef.jumpSeq;
      this._pendingJumpThread = String(rawRef.thread);
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
          if (this.hoverKey) { this.hoverKey = ''; this.notifyPanes(cx, { shell: false, conv: true, side: true }); }
        }
      })
      .on_size_change((size, cx) => {
        const wide = size.width >= SPLIT_WIDE_MIN;
        this.high = size.height;
        let changed = false;
        if (wide !== this.wide) { this.wide = wide; changed = true; }
        if (size.width !== this.viewWidth) { this.viewWidth = size.width; changed = true; }
        if (changed) this.notifyPanes(cx, { shell: true, conv: true, side: true });
        // The first measure places the panel; only later changes slide.
        if (!this.measuring) { this.measuring = true; cx.timer.after(60, tCx => { this.measured = true; this.notifyShell(tCx); }); }
      });
    const pm = this.pm();
    if (!pm) {
      this.ringAction = null;
      if (this.bodyOnly) this.publishHeaderState({ session: this.winSession, pmName: this.pmName, hasPm: false, lang });
      const remote = this.machine && this.stateFor !== this.machine;
      const note = remote ? (this.error ? word(lang, 'remoteError', this.machine, this.error) : word(lang, 'remoteLoading', this.machine))
        : this.pmName && this.state.pms.length ? word(lang, 'noProject') : word(lang, 'pick');
      const winControls = this.bodyOnly ? null : this.renderWindowControls(t, lang, { divider: false });
      if (winControls) {
        return root.child(v_flex().size_full().min_w(0).min_h(0)
          .child(h_flex().id('pm-project-header-bar').h(56).w_full().flex_none().pr(14).items_center().justify_end().child(winControls))
          .child(keepPress(v_flex().flex_1().min_h(0).w_full().items_center().justify_center(), this.keyFocus)
            .child(div().max_w(360).text_color(t.dim).whitespace_normal().child(note))));
      }
      return keepPress(root, this.keyFocus).items_center().justify_center().child(div().max_w(360).text_color(t.dim).whitespace_normal().child(note));
    }
    const now = new Date(), today = iso(now);
    const splitLayout = this.currentSplitLayout();
    this._lastLayout = splitLayout;
    const open = this.isPanelOpen();
    const dragging = Boolean(this.panelDrag);

    // Track open/close & compact <-> split width transitions to gate resized() and lock inner text width.
    const targetWidth = open ? splitLayout.cardWidth : 0;
    const prevTarget = this._lastPanelTargetWidth;
    const prevOpen = Boolean(this._lastPanelOpen);
    if (this.measured && !dragging && prevTarget !== null && Math.abs(targetWidth - prevTarget) > 2) {
      this.panelTransitioning = true;
      this._panelSlideFromZero = !prevOpen && open;
      this._panelLockWidth = open ? splitLayout.cardWidth : prevTarget;
      this.panelTransitionTimer?.cancel?.();
      this.panelTransitionTimer = cx?.timer?.after?.(200, liveCx => {
        this.panelTransitionTimer = null;
        this.panelTransitioning = false;
        this._panelSlideFromZero = false;
        this._panelLockWidth = null;
        this.notifyPanes(liveCx, { shell: true, side: true });
        if (!this.away) this.resized(liveCx);
      }) || null;
    } else if (dragging) {
      this._panelSlideFromZero = false;
    }
    this._lastPanelTargetWidth = targetWidth;
    this._lastPanelOpen = open;

    if (open) {
      this.panelMounted = true;
      if (this.panelHideTimer) { this.panelHideTimer.cancel?.(); this.panelHideTimer = null; }
    } else if (this.panelMounted) {
      if (!this.measured || dragging || !cx?.timer?.after) {
        this.panelMounted = false;
        if (this.panelClosing) {
          if (this.hasSideTabs()) this.panelClosing = false;
          else this._clearClosedSideState();
        }
      } else if (!this.panelHideTimer) {
        this.panelHideTimer = cx.timer.after(220, liveCx => {
          this.panelHideTimer = null;
          if (!this.isPanelOpen()) {
            this.panelMounted = false;
            if (this.panelClosing) {
              if (this.hasSideTabs()) this.panelClosing = false;
              else this._clearClosedSideState();
            }
            this.notifyPanes(liveCx, { shell: true, conv: true, side: true });
          }
        }) || null;
      }
    }

    // Fast path for shell-only updates (drag move, grip hover, transition timers) when retained child Entities are active:
    // zero JS rebuild of the conversation timeline or side split content tree.
    if (shellOnly && this._convEntity && this._sideEntity && !this.searchOpen && !this.imageLightbox && !this.foldersOpen) {
      const mainSlot = v_flex().id('pm-main-slot').flex_1().min_w(0).h_full().child(this._convEntity);
      const panelEl = this.buildPanelShell(pm, t, today, cx, { open, layout: splitLayout, dragging });
      return root.child(mainSlot).child(panelEl);
    }

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
      const queuedCount = this.pending.filter(p => p.queued && !p.failed && !p.received).length;
      const localQueuedCount = this.pending.filter(p => p.queued && !p.failed && !p.received && !p.serverQueued).length;
      const hasUnconfirmed = this.pending.some(p => !p.failed && !p.received && (p.verifying || (!p.queued && (p.deliveredAt > 0 || p.inFlight)) || (p.queued && p.swapWaitSince > 0)));
      if (hasUnconfirmed) this.scheduleConfirmCheck(cx);
      const inRenderPhase = cx?.phase?.() === 'render' && Boolean(cx?.spawn);
      if (this._pendingPmKeep && !this._reconcilingPmKeep) {
        if (inRenderPhase) {
          this._reconcilingPmKeep = true;
          cx.spawn(async () => {
            try { this.reconcilePendingPmKeep(); }
            finally { this._reconcilingPmKeep = false; }
          });
        } else {
          this.reconcilePendingPmKeep();
        }
      }
      if (pmTerm && !pmCanReceive(pmStatus)) {
        if (inRenderPhase) cx.spawn(async taskCx => this.probePmDialog(taskCx));
        else this.probePmDialog(cx);
      } else if (pmTerm && pmCanReceive(pmStatus)) {
        if (this.pmDialog?.pm === this.pmName && !queuedCount && !this.pmSendBlockError) this.pmDialog = null;
        if (localQueuedCount > 0 && !this.flushingQueue && !this.flushDeferred) {
          if (inRenderPhase) {
            this.flushDeferred = true;
            cx.spawn(async taskCx => {
              this.flushDeferred = false;
              this.flushQueue(taskCx);
            });
          } else {
            this.flushQueue(cx);
          }
        } else if (queuedCount > 0) {
          this.scheduleQueueFlush(cx);
        }
      } else if (!pmTerm && queuedCount > 0) {
        this.scheduleQueueFlush(cx);
      }

      if (this._convEntity && this._sideEntity) {
        if (!shellOnly && !dragging && !this._syncPanesScheduled && cx?.timer?.after) {
          this._syncPanesScheduled = true;
          cx.timer.after(0, liveCx => {
            this._syncPanesScheduled = false;
            this.notifyPanes(liveCx, { shell: false, conv: true, side: true });
          });
        }
        const mainSlot = v_flex().id('pm-main-slot').flex_1().min_w(0).h_full().child(this._convEntity);
        const panelEl = this.buildPanelShell(pm, t, today, cx, { open, layout: splitLayout, dragging });
        if (this._pendingJumpThread) {
          const jumpId = this._pendingJumpThread;
          this._pendingJumpThread = '';
          cx.timer?.after?.(0, liveCx => this.jumpToThread(jumpId, liveCx));
        }
        return root.child(mainSlot).child(panelEl)
          .when(Boolean(this.foldersOpen), el => el.child(this.renderFoldersPopover(pm, t, cx)))
          .when(Boolean(this.searchOpen), el => el.child(this.projectSearchOverlay(pm, this.items || [], t, today, cx)))
          .when(Boolean(this.imageLightbox), el => el.child(this.renderImageLightbox(cx, { inProject: true })));
      }

      const mainEl = this.renderConversationPane(cx);
      const inlineSide = (open || this.panelMounted) ? this.renderSideSplitPane(cx) : null;
      const panelEl = this.buildPanelShell(pm, t, today, cx, { open, layout: splitLayout, dragging, inlineSide });
      if (this._pendingJumpThread) {
        const jumpId = this._pendingJumpThread;
        this._pendingJumpThread = '';
        cx.timer?.after?.(0, liveCx => this.jumpToThread(jumpId, liveCx));
      }
      return root.child(mainEl).child(panelEl)
        .when(Boolean(this.foldersOpen), el => el.child(this.renderFoldersPopover(pm, t, cx)))
        .when(Boolean(this.searchOpen), el => el.child(this.projectSearchOverlay(pm, this.items || [], t, today, cx)))
        .when(Boolean(this.imageLightbox), el => el.child(this.renderImageLightbox(cx, { inProject: true })));
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
