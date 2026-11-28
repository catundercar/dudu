// Pure parts of the project view: the conversation log turned into a timeline,
// the waiting count, optimistic bubbles, and the words in both languages.

export const STEP_LABEL_UNITS = 24; // ~12 CJK chars or 24 ASCII chars for short step labels
export const PLAN_STRINGS = {
  en: {
    reviewing: 'Reviewing',
    planTitle: 'Steps',
    planProgress: (done, total) => `${done}/${total}`,
    planAutoReview: 'Auto-review',
    planAutoReviewTip: 'Auto-starts an independent reviewer on commit',
    planNoReview: 'No review',
    planNoReviewTip: 'No code review in this task plan',
    planRound: n => `R${n}`,
    planFoldedRounds: n => n === 1 ? 'R1' : `R1–${n}`,
    planFallbackWork: 'Work',
    planFallbackReview: 'Review',
    planFallbackDone: 'Done',
    planPostStep: (done, total, step) => `${done}/${total} · ${step}`,
    depsTitle: 'Waiting',
    depsReady: 'Ready to dispatch',
    depsJumpTip: title => `Open ${title}`,
    depsAbandoned: 'Abandoned',
    depsMissing: 'Missing',
    substepsFoldTip: (done, total) => `${done}/${total} sub-steps`,
    detailReviewStepTip: 'Click to toggle review window',
  },
  zh: {
    reviewing: '审查中',
    planTitle: '步骤',
    planProgress: (done, total) => `${done}/${total}`,
    planAutoReview: '自动审',
    planAutoReviewTip: '提交后自动拉起独立审查',
    planNoReview: '免审',
    planNoReviewTip: '本任务计划不含代码审查',
    planRound: n => `第${n}轮`,
    planFoldedRounds: n => n === 1 ? '第1轮' : `第1-${n}轮`,
    planFallbackWork: '执行',
    planFallbackReview: '审查',
    planFallbackDone: '完成',
    planPostStep: (done, total, step) => `${done}/${total} · ${step}`,
    depsTitle: '等待',
    depsReady: '可以派了',
    depsJumpTip: title => `跳转到 ${title}`,
    depsAbandoned: '已放弃',
    depsMissing: '不存在',
    substepsFoldTip: (done, total) => `${done}/${total} 个子步骤`,
    detailReviewStepTip: '点击开关审查小窗',
  },
};

export const THREAD_STRINGS = {
  en: {
    sumWaiting: n => `${n} waiting`,
    sumReview: n => `${n} reviewing`,
    sumWorking: n => `${n} working`,
    sumOffline: n => `${n} offline`,
    sumPaused: n => `${n} paused`,
    sumQueued: n => `${n} queued`,
    sumDone: n => `${n} done`,
    endedAgents: n => `${n} ended`,
    doneSubtasks: n => `${n} done`,
    activePrefix: 'Active: ',
    agentRole_worker: 'worker',
    agentRole_review: 'review',
    agentRole_helper: 'helper',
    backToThreads: 'Threads',
    openDetailTip: 'Open steps & detail',
    closeAgentWindow: 'Close window (Esc · agent keeps running)',
    openAgentWindow: 'Toggle agent window (agent keeps running)',
    switchToTerminal: 'Live terminal',
    switchToChat: 'Conversation view',
    locateThread: 'Reveal thread',
    sayAgent: 'Message this agent…',
    foldedDone: n => `${n} done`,
    showAllLog: n => `Show all (${n})`,
    collapseLog: 'Show recent 3',
    helperConclusion: 'Conclusion',
    helperNoConclusion: 'No conclusion written yet',
    helperRunningTerm: 'Running in terminal',
    helperDoing_land: 'Merging',
    helperDid_land: 'Merge',
    helperDoing_triage: 'Diagnosing',
    helperDid_triage: 'Diagnosis',
    agentState_working: 'working',
    agentState_idle: 'idle',
    agentState_blocked: 'needs you',
    agentState_done: 'done',
    agentState_ended: 'ended',
    agentWindowEnded: 'Agent ended',
    agentWindowOffline: 'Agent terminal is offline',
    substepsFoldTip: (done, total) => `${done}/${total} sub-steps`,
    detailOpenWindow: 'Toggle worker window',
    detailReviewStepTip: 'Click to toggle review window',
    agentSessionFallback: 'Session transcript unavailable; switch to live terminal.',
    windowSizeTip: (cur, next) => `Window size: ${cur} (click for ${next})`,
    waitsDep: ref => `waits ${ref}`,
    queuedLabel: 'queued',
    reviewBadge: 'In review',
    reviewTitle: 'Review',
    readOnlyLabel: 'read-only',
    reviewerSubLabel: 'reviewer',
    depsAutoUnblock: ref => `Auto-unblocks once ${ref} lands on main.`,
  },
  zh: {
    sumWaiting: n => `${n} 等你`,
    sumReview: n => `${n} 审查`,
    sumWorking: n => `${n} 在做`,
    sumOffline: n => `${n} 断开`,
    sumPaused: n => `${n} 暂停`,
    sumQueued: n => `${n} 待办`,
    sumDone: n => `${n} 已完`,
    endedAgents: n => `${n} 已结束`,
    doneSubtasks: n => `${n} 已完成`,
    activePrefix: '在做：',
    agentRole_worker: 'worker',
    agentRole_review: '审查',
    agentRole_helper: 'helper',
    backToThreads: '线程',
    openDetailTip: '查看步骤与详情',
    closeAgentWindow: '收起小窗（Esc · 不结束进程）',
    openAgentWindow: '开关小窗（不结束进程）',
    switchToTerminal: '切到终端',
    switchToChat: '切到对话',
    locateThread: '定位线程',
    sayAgent: '只对这个 agent 说…',
    foldedDone: n => `${n} 已完`,
    showAllLog: n => `展开全部 (${n})`,
    collapseLog: '只看最近 3 条',
    helperConclusion: '结论',
    helperNoConclusion: '暂无结论输出',
    helperRunningTerm: '终端运行中',
    helperDoing_land: '合并中',
    helperDid_land: '合并',
    helperDoing_triage: '排查中',
    helperDid_triage: '排查',
    agentState_working: '在做',
    agentState_idle: '空闲',
    agentState_blocked: '等你',
    agentState_done: '已完成',
    agentState_ended: '已结束',
    agentWindowEnded: 'agent 已结束',
    agentWindowOffline: 'agent 终端已离线',
    substepsFoldTip: (done, total) => `${done}/${total} 个子步骤`,
    detailOpenWindow: '开关 worker 小窗',
    detailReviewStepTip: '点击开关审查小窗',
    agentSessionFallback: '暂无可解析会话，可切到原生终端查看。',
    windowSizeTip: (cur, next) => `窗口尺寸：${cur}（点击切到 ${next}）`,
    waitsDep: ref => `等 ${ref}`,
    queuedLabel: '排队',
    reviewBadge: '待审',
    reviewTitle: '审查',
    readOnlyLabel: '只读',
    reviewerSubLabel: 'reviewer',
    depsAutoUnblock: ref => `${ref} 合入 main 后自动解除。`,
  },
};

export const CHANGE_STRINGS = {
  en: {
    changeTitle: 'Changes',
    changeBackDetail: 'Back to thread (Esc)',
    changeBackCommits: 'Back to commits (Esc)',
    changeBackFiles: 'Back to files (Esc)',
    changeClose: 'Back to thread detail',
    changeRefresh: 'Refresh changes',
    changeLoading: 'Reading changes…',
    changeLoadingFiles: 'Reading files…',
    changeLoadingDiff: 'Reading diff…',
    changeAllTitle: 'All branch changes',
    changeAllScope: 'All changes',
    changeCommitsCount: n => `${n} ${n === 1 ? 'commit' : 'commits'}`,
    changeFilesCount: n => `${n} ${n === 1 ? 'file' : 'files'}`,
    changeMoreCommits: 'Older commits omitted; all branch changes include them.',
    changeMergeBadge: 'Merge',
    changeMergeBaseBadge: base => `Merge ${base}`,
    changeBaseMergesFold: (n, base) => `${n} ${n === 1 ? 'merge' : 'merges'} from ${base}`,
    changeMergeBaseNote: base => `Merge from ${base}: stats and diff show changes brought in from ${base} (vs first parent).`,
    changeMergeNote: 'Merge commit: stats and diff show changes brought in by this merge (vs first parent).',
    changeUncommitted: n => `${n} uncommitted ${n === 1 ? 'file' : 'files'} in worktree (not shown below)`,
    changeNoBranch: 'This thread has no branch recorded.',
    changeBranchDeleted: b => `Branch ${b} is no longer in the repository (likely merged and deleted).`,
    changeEmpty: (b, base) => `Branch ${b} has no commits ahead of ${base}.`,
    changeBaseMissing: b => `Could not find the base branch for ${b} in the repository.`,
    changeNoRepo: 'Project repository was not found on this machine.',
    changeNotGit: 'Project folder is not a git repository.',
    changeNoGit: 'git is not installed on this machine.',
    changeRecordedHint: 'Recorded commit on this thread:',
    changeNoFiles: 'No files changed.',
    changeBinaryFile: 'Binary file — text diff is not shown.',
    changeNoDiffLines: 'No text line changes in this file.',
    changeTruncatedBytes: 'Diff exceeded 2 MB and was truncated.',
    changeTruncatedLines: 'Some very long lines were shortened.',
    changeLoadMore: n => `Load more (${n} ${n === 1 ? 'line' : 'lines'} remaining)`,
    changeLoadingMore: 'Loading more lines…',
    changeLinesShown: (shown, total) => `${shown} / ${total} lines`,
    changeCollapseAll: 'Collapse all hunks',
    changeExpandAll: 'Expand all hunks',
    changeFoldHunk: 'Collapse hunk',
    changeUnfoldHunk: 'Expand hunk',
    changeBinaryBadge: 'BIN',
    changeError: err => `Could not read changes: ${err}`,
    changeStatus_A: 'Added',
    changeStatus_M: 'Modified',
    changeStatus_D: 'Deleted',
    changeStatus_R: 'Renamed',
    changeStatus_C: 'Copied',
    changeStatus_T: 'Type changed',
  },
  zh: {
    changeTitle: '改动',
    changeBackDetail: '返回线程详情（Esc）',
    changeBackCommits: '返回提交列表（Esc）',
    changeBackFiles: '返回文件列表（Esc）',
    changeClose: '返回线程详情',
    changeRefresh: '刷新改动',
    changeLoading: '正在读取改动…',
    changeLoadingFiles: '正在读取文件列表…',
    changeLoadingDiff: '正在读取 diff…',
    changeAllTitle: '分支整体改动',
    changeAllScope: '整体改动',
    changeCommitsCount: n => `${n} 个提交`,
    changeFilesCount: n => `${n} 个文件`,
    changeMoreCommits: '更早的提交未列出；整体改动中包含它们。',
    changeMergeBadge: '合并',
    changeMergeBaseBadge: base => `合并 ${base}`,
    changeBaseMergesFold: (n, base) => `${n} 次合并 ${base}`,
    changeMergeBaseNote: base => `合并 ${base} 的提交：统计与 diff 显示从 ${base} 合入的改动（相对第一父提交）。`,
    changeMergeNote: '合并提交：统计与 diff 显示此次合并引入的改动（相对第一父提交）。',
    changeUncommitted: n => `工作树里还有 ${n} 个未提交改动（不在下面）`,
    changeNoBranch: '这条线程还没有记录分支。',
    changeBranchDeleted: b => `分支 ${b} 已不在仓库中（通常已合并并删除）。`,
    changeEmpty: (b, base) => `分支 ${b} 相对 ${base} 还没有新提交。`,
    changeBaseMissing: b => `仓库里找不到分支 ${b} 的基准分支。`,
    changeNoRepo: '这台机器上找不到项目仓库目录。',
    changeNotGit: '项目目录不是 git 仓库。',
    changeNoGit: '这台机器上没有安装 git。',
    changeRecordedHint: '可查看这条线程记下的提交：',
    changeNoFiles: '没有文件改动。',
    changeBinaryFile: '二进制文件，不展示文本 diff。',
    changeNoDiffLines: '该文件没有文本行改动。',
    changeTruncatedBytes: 'Diff 超过 2 MB 上限，已截断。',
    changeTruncatedLines: '部分超长行已截断显示。',
    changeLoadMore: n => `继续加载（剩余 ${n} 行）`,
    changeLoadingMore: '正在加载更多行…',
    changeLinesShown: (shown, total) => `已显示 ${shown} / ${total} 行`,
    changeCollapseAll: '折叠全部代码段',
    changeExpandAll: '展开全部代码段',
    changeFoldHunk: '折叠此代码段',
    changeUnfoldHunk: '展开此代码段',
    changeBinaryBadge: '二进制',
    changeError: err => `读取改动失败：${err}`,
    changeStatus_A: '新增',
    changeStatus_M: '修改',
    changeStatus_D: '删除',
    changeStatus_R: '重命名',
    changeStatus_C: '复制',
    changeStatus_T: '类型变更',
  },
};

export const SEARCH_STRINGS = {
  en: {
    searchProject: 'Search project',
    searchProjectTip: sc => `Search project (${sc})`,
    searchProjectPlaceholder: 'Search threads, #number, messages, decisions…',
    searchCloseTip: 'Close search (Esc)',
    searchScopeAll: 'All',
    searchScopeThreads: 'Threads',
    searchScopeMessages: 'Messages',
    searchScopeDecisions: 'Decisions',
    searchScopeLibrary: 'Library',
    searchGroupThreads: 'Threads',
    searchGroupMessages: 'Messages',
    searchGroupDecisions: 'Decisions & Memory',
    searchGroupLibrary: 'Library',
    searchRecentThreads: 'Recent threads',
    searchRecentDecisions: 'Recent decisions',
    searchShowAll: n => `Show all ${n}`,
    searchNoMatches: 'No matches in loaded project data.',
    searchNoMatchesEarlier: 'Try loading earlier messages below to search further back.',
    searchEmptyHint: 'Type to search threads, #number, messages, and decisions.',
    searchLoadedOnly: since => since ? `Loaded messages only (since ${since})` : 'Searching loaded messages only',
    searchLoadEarlier: 'Load earlier messages',
    searchLoadingEarlier: 'Loading earlier messages…',
    searchLoadEarlierFailed: err => `Failed to load earlier: ${err} (click to retry)`,
    searchRemotePartial: 'Searching recent loaded messages only',
    searchMsgYou: 'You',
    searchMsgPm: 'PM',
    searchMsgQuestion: 'Question',
    searchDecisionEvent: 'In conversation',
    searchNavHint: '↑↓ move · ↵ open · Tab filter · Esc back',
    searchNavHintShort: '↑↓ · ↵ · Tab · Esc',
    searchLogMatch: 'Log',
  },
  zh: {
    searchProject: '搜索项目',
    searchProjectTip: sc => `搜索项目（${sc}）`,
    searchProjectPlaceholder: '搜索线程、#编号、对话消息、决定…',
    searchCloseTip: '关闭搜索（Esc）',
    searchScopeAll: '全部',
    searchScopeThreads: '线程',
    searchScopeMessages: '消息',
    searchScopeDecisions: '决定',
    searchScopeLibrary: 'Library',
    searchGroupThreads: '线程',
    searchGroupMessages: '消息',
    searchGroupDecisions: '决定与记忆',
    searchGroupLibrary: 'Library',
    searchRecentThreads: '最近线程',
    searchRecentDecisions: '最近决定',
    searchShowAll: n => `查看全部 ${n} 条`,
    searchNoMatches: '已加载的项目数据中没有匹配结果。',
    searchNoMatchesEarlier: '可点击下方加载更早的对话继续搜索。',
    searchEmptyHint: '输入关键词搜索线程、#编号、对话消息与决定。',
    searchLoadedOnly: since => since ? `仅搜已加载对话（自 ${since} 起）` : '仅搜已加载的对话',
    searchLoadEarlier: '加载更早的对话',
    searchLoadingEarlier: '正在加载更早的对话…',
    searchLoadEarlierFailed: err => `加载更早对话失败：${err}（点击重试）`,
    searchRemotePartial: '仅搜最近已加载的对话',
    searchMsgYou: '你',
    searchMsgPm: 'PM',
    searchMsgQuestion: '提问',
    searchDecisionEvent: '对话中的决定',
    searchNavHint: '↑↓ 选择 · ↵ 打开 · Tab 筛选 · Esc 返回',
    searchNavHintShort: '↑↓ · ↵ · Tab · Esc',
    searchLogMatch: '日志',
  },
};

export const STRINGS = {
  en: {
    you: 'You', waiting: 'Waiting for you', waitingCount: n => `${n} ${n === 1 ? 'item' : 'items'} waiting for you`,
    nothingWaiting: 'Nothing waiting for you',
    openPm: 'Open the PM terminal', noPmTerminal: 'The PM is not in the desktop app',
    startPm: 'Start PM session (from handover)', startingPm: 'Starting PM session…',
    startPmFailed: error => `Could not start PM: ${error}`,
    pmOfflineStartable: 'PM session is not running · start a new session from handover',
    pmOfflineArchived: 'This project is archived; restore it from Projects → Archived.',
    pmOfflineTui: 'This PM is registered in Herdr TUI, not the desktop app.',
    pmOfflineMissingRepo: 'Project folder is missing on this machine.',
    chatView: 'Conversation', boardView: 'Board',
    say: name => `Message the ${name} coordinator…`, sayThread: 'Message only this thread…',
    send: 'Send', sendThread: 'Send to this thread',
    offline: 'No PM session of this project is running in the desktop app. Start it with the play icon.',
    threadOffline: 'This thread has no live terminal',
    subThreads: 'Split into', partOf: title => `Part of ${title}`, moreParts: n => `${n} more`,
    reviewThread: 'Review', openReviewTerminal: "Open the reviewer's terminal",
    disconnected: 'Disconnected', group_offline: 'Disconnected',
    closedReattach: 'Closed · can reattach',
    closedWhy_workers_close_reported: 'idle after report',
    closedWhy_idle_workers: 'idle cleanup',
    closedWhy_workers_close_on_close: 'task closed',
    closedWhy_retire: 'retired',
    closedWhy_killed: 'terminal closed',
    closedDetail: detail => detail ? `Closed · can reattach (${detail})` : 'Closed · can reattach',
    reattach: "Reattach: resume this thread's agent session, or start a new agent with its brief and ledger log",
    reattachClosed: detail => detail
      ? `Closed (${detail}) — reattach: resume this thread's agent session, or start a new agent with its brief and ledger log`
      : "Reattach: resume this thread's agent session, or start a new agent with its brief and ledger log",
    reattaching: 'Reattaching…', reattachFailed: error => `Not reattached: ${error}`,
    bringAllBack: 'Review & bring all back',
    bringBackStart: 'Start all now',
    bringBackRetry: 'Retry remaining',
    bringingBack: 'Bringing back…',
    bringBackDismiss: 'Dismiss',
    bringBackCollapse: 'Collapse (Esc)',
    bringBackHintWithPm: 'Starts the PM first, then reattaches each thread under it.',
    bringBackHintThreads: 'Reattaches each thread under the project PM.',
    bringBackPmStep: name => `${name} PM (from handover)`,
    openTerminal: 'Open its terminal', terminalNowhere: 'Its terminal is in no pane, and neither is its PM: nowhere to open it',
    diff: 'See the changes', close: 'Close',
    resizePanel: 'Drag to resize the side panel; double-click for its default width',
    sending: 'Sending…', queued: 'Queued', queuedTip: 'Waiting for PM to be ready — will send automatically',
    queuedReasonStarting: 'PM session is starting',
    queuedReasonInflight: 'Waiting for previous message',
    queuedReasonFifo: 'Waiting for earlier queued messages',
    queuedReasonBlocked: 'PM terminal is waiting on a prompt',
    queuedReasonError: 'PM terminal reported an error',
    queuedReasonDraft: 'Queued (unsent draft in terminal)',
    queuedReasonWorking: 'Waiting for PM turn to finish',
    queuedReasonOffline: 'Waiting for PM session',
    queuedReasonDisconnected: 'Waiting for remote machine reconnect',
    queuedReasonTimeout: 'Reconciling delivery status',
    queuedReasonNewSession: 'Sending again to the new PM session',
    queuedReasonTypist: 'Waiting for another message to finish typing',
    queuedReasonCarried: 'Carried over from before the update',
    queuedReasonRetryUnstarted: 'Sending again: the PM did not start on it',
    queuedReasonRetryInterrupted: 'Sending again: its turn was interrupted',
    queuedReasonRetryErrored: 'Sending again: its turn hit an error',
    queuedReasonUnsupported: 'This PM cannot receive this kind of message',
    queuedReasonOther: 'Waiting to be sent',
    turnInterrupted: 'its turn was interrupted',
    turnErrored: 'its turn hit an error',
    bubbleStateAccepted: 'Queued',
    bubbleStateSending: 'Sending…',
    bubbleStateTyped: 'Delivered',
    bubbleStateTypedStep: 'Delivered, it reads it after this step',
    bubbleStateTypedTurn: 'Delivered, it reads it after this turn',
    bubbleStateConsumed: 'Read',
    bubbleStateAnswered: 'Answered',
    bubbleStateFailed: 'Failed',
    pmUndeliveredMessages: (n, dur, detail) => `${n} ${n === 1 ? 'message' : 'messages'} not typed into the PM for ${dur}${detail ? ` (${detail})` : ''}`,
    queuedSummary: n => n === 1 ? '1 message queued, will send automatically' : `${n} messages queued, will send automatically`,
    pmQueuedOnly: n => n === 1 ? '1 message queued — will send when PM can receive' : `${n} messages queued — will send when PM can receive`,
    pmBlockedQuestion: 'PM is waiting on a terminal question dialog',
    pmBlockedPermission: 'PM is waiting for a permission confirmation in its terminal',
    pmBlockedTrust: 'PM is waiting on a folder trust dialog in its terminal',
    pmBlockedUpdate: 'PM is waiting on a CLI update prompt in its terminal',
    pmBlockedHook: 'PM is waiting on a hook or MCP approval dialog in its terminal',
    pmBlockedAuth: 'PM needs login or authentication in its terminal',
    pmBlockedQuota: 'PM hit a rate limit or quota prompt in its terminal',
    pmBlockedDraft: 'PM terminal has an unsent draft — clear or send it there',
    pmBlockedUnknown: 'PM terminal is waiting on an interactive prompt',
    pmUndelivered: (n, dur, detail) => `${n} pending ${n === 1 ? 'event' : 'events'} undelivered for ${dur}${detail ? ` (${detail})` : ''}`,
    delivererStopped: 'deliverer not running',
    // A bubble the send put into the PM's terminal that the conversation never recorded; and one whose
    // send never finished (stuck, or the view reloaded mid-send), so nobody knows whether it went.
    unconfirmedSend: 'Delivered to the PM terminal, but it never showed up in the conversation',
    unsureSend: 'Sending never finished; the PM may not have it',
    checkingSent: 'Checking whether the PM already has it…',
    pmOfflineFailed: 'PM session stopped before receiving this message — click to resend',
    retrySend: 'Resend',
    pmTurnThinking: dur => `Thinking · ${dur}`,
    pmTurnPreamble: (text, dur) => `${text} · ${dur}`,
    pmTurnLongGen: dur => `Writing a long piece · ${dur}`,
    pmTurnTool: (summary, dur) => `Running ${summary} · ${dur}`,
    pmTurnToolSlow: (summary, dur) => summary ? `Foreground command running for ${dur}: ${summary}` : `Foreground command running for ${dur}`,
    pmTurnToolSuspect: summary => summary ? `Command may be waiting for input: ${summary}` : 'Command may be waiting for input',
    pmTurnRetrying: attempt => attempt ? `Model service retrying (attempt ${attempt})` : 'Model service retrying',
    pmTurnBlocked: kind => kind ? `Waiting for you in the terminal: ${kind}` : 'Waiting for you in the terminal',
    pmTurnRecovering: step => step ? `Recovering: ${step}` : 'Recovering…',
    incidentRecovering: step => step ? `Auto-recovering: ${step}` : 'Auto-recovering…',
    incidentRecovered: detail => detail ? `Recovered · ${detail}` : 'Recovered',
    incidentFolded: detail => detail ? `Auto-recovered · ${detail}` : 'Auto-recovered',
    incidentNotified: detail => detail ? `Needs your attention: ${detail}` : 'Needs your attention',
    recoveryStep_interrupt_tool: 'interrupting hung command',
    recoveryStep_interrupt_turn: 'interrupting current step',
    recoveryStep_continue_turn: 'resuming turn',
    recoveryStep_nudge_enter: 'nudging terminal',
    recoveryStep_retype_submitted: 'resending message',
    recoveryStep_restart_seat: 'restarting PM session',
    recoveryStep_switch_profile: 'switching fallback model',
    recoveryStep_classify_screen: 'checking terminal screen',
    recoveryStep_waiting_draft: 'waiting for draft to clear',
    recoveryStep_notify_user: 'waiting for you',
    recoveryStep_unblock_safe_dialog: 'dismissing terminal prompt',
    pmTurnSlow: (detail, dur) => detail ? `Waiting on ${detail} · ${dur}` : `Still working · ${dur}`,
    pmTurnStalled: (detail, dur) => detail ? `Unresponsive for ${dur} · ${detail}` : `Unresponsive for ${dur}`,
    pmTurnStalledEvidence: (dur, evidence) => evidence ? `Unresponsive for ${dur} (${evidence})` : `Unresponsive for ${dur}`,
    pmEvidencePtyFrozen: 'screen unchanged for 45s',
    pmEvidenceNoStep: 'no new step for 4m',
    pmEvidenceToolHard: 'foreground command exceeded hard budget',
    pmEvidenceToolInput: 'command may be waiting for input',
    pmEvidenceSubmitted: 'turn did not start after submit',
    pmEvidenceUpstream: 'model service timed out',
    pmTurnTotalTip: dur => `Total turn duration: ${dur}`,
    openPmBgShells: n => `Open PM terminal (${n} background ${n === 1 ? 'command' : 'commands'})`,
    pmBusyTimingStep: 'this step',
    pmBusyTimingTurn: 'this turn',
    pmBusyActThinking: 'thinking',
    pmBusyActLongGen: 'writing a long piece',
    pmBusyActRetrying: 'waiting on model service retry',
    pmBusyActRunning: summary => `running ${summary}`,
    pmBusyComposer: (activity, timing) => `Coordinator is ${activity}; your message will be seen after ${timing}`,
    pmBusyComposerQueued: (activity, timing, n) => `Coordinator is ${activity}; ${n > 1 ? `${n} queued messages` : 'queued message'} will be seen after ${timing}`,
    pmPreemptAction: 'Interrupt and handle this first',
    pmPreemptQueuedAction: 'Interrupt and handle queued message',
    pmTurnUnknown: 'Status unknown, reconnecting…',
    interruptPmTip: 'Interrupt current step (keeps PM session)',
    interruptingPmTip: 'Interrupting…',
    interruptStopped: 'Interrupted current step',
    interruptStillWorking: 'Interrupt did not stop the current step',
    interruptExited: 'PM process exited',
    interruptUnknown: 'Interrupt sent (outcome unknown)',
    interruptFailed: error => `Interrupt failed: ${error}`,
    rotatePmTip: 'Start a fresh PM session from handover',
    rotatingPmTip: 'Switching to a fresh PM session…',
    rotateSucceeded: 'Switched to a fresh PM session',
    rotateFailed: error => `Switch session failed: ${error}`,
    failed: error => `Not sent: ${error}`, decision: 'Decision',
    pick: 'Pick a project in the PM list to open its conversation.', noProject: 'This PM is no longer in the ledger.',
    remoteLoading: machine => `Reading the project from ${machine}…`,
    remoteError: (machine, error) => `Could not read the project from ${machine}. Is that machine connected in Herdr, with the pm skill installed there?\n${error}`,
    remoteAttach: machine => `Attach files (or drop them here, or paste a screenshot); they are copied to ${machine} when the message is sent`,
    empty: 'Nothing said in this project yet.', readError: 'Could not read the conversation',
    today: 'Today', yesterday: 'Yesterday', noLog: 'No log yet', agent: (program, address) => `${program} · terminal ${address}`,
    unfold: 'Show the whole reply', fold: 'Fold',
    threads: 'Threads', showThreads: 'Show the threads', hideThreads: 'Hide the threads',
    group_waiting: 'Waiting on you', group_review: 'In review', group_working: 'Working', group_paused: 'Paused',
    group_parked: 'Not started',
    groupSessions: 'Sessions', groupFinished: 'Finished', recommended: 'Recommended', handledByPm: 'Handled by PM', openThread: 'Open this thread',
    ownAnswer: 'Answer in your own words…', answeringTo: title => `Answering ${title}`, stopAnswering: 'Stop answering this question (Esc)',
    noThreads: 'No threads in this project yet.', openSession: 'Click opens this session',
    session_working: 'Working', session_blocked: 'Needs you', session_done: 'Done', session_idle: 'Idle',
    in_progress: 'In progress', blocked: 'Blocked', answered: 'Answered', review: 'Review', paused: 'Paused', proposed: 'Proposed',
    merged: 'Merged', released: 'Released', done: 'Done', abandoned: 'Abandoned', cleanup: 'Merged · not retired',
    attach: 'Attach files (or drop them here, or paste a screenshot)', removeFile: name => `Remove ${name}`,
    attachFailed: error => `Could not attach: ${error}`, attachments: 'Attachments:',
    uploadFailed: (name, machine, error) => `${name} was not copied to ${machine}: ${error}`,
    notAFile: names => `not a file: ${names}`, noPasteFolder: 'this project has no conversation log yet, so a pasted image has nowhere to be kept',
    engineProfile: name => `Profile: ${name}`, engineWhy: why => `Why: ${why}`, engineRounds: n => `Review rounds: ${n}`,
    engineEscalatedTimes: n => `Escalated ${n} time${n === 1 ? '' : 's'}`,
    engineEscalated: (from, to, why) => `Escalated ${from} → ${to}${why ? `: ${why}` : ''}`,
    engineAdvisor: name => `Advisor: ${name}`, effortDefault: 'default',
    earlierMessages: 'Show earlier messages', loadingEarlier: 'Reading earlier messages…',
    earlierFailed: error => `Could not read earlier messages: ${error} (click to retry)`,
    earlierLog: n => `Show ${n} earlier ${n === 1 ? 'entry' : 'entries'}`, loadingEarlierLog: 'Reading earlier log…',
    earlierLogFailed: error => `Could not read earlier log: ${error} (click to retry)`,
    libraryTab: 'Library',
    memoryTab: 'Memory',
    showSidePanel: 'Show side panel', hideSidePanel: 'Hide side panel',
    windowMinimize: 'Minimize', windowMaximize: 'Maximize', windowRestore: 'Restore', windowClose: 'Close',
    searchLibrary: 'Search Library…', searchMemory: 'Search Memory…', searchThreads: 'Search Threads…', clearSearch: 'Clear search',
    threadsSearching: 'Searching threads…',
    threadsNoMatches: 'No matching threads.',
    threadsSearchError: err => `Could not search threads: ${err}`,
    loadMoreFinished: rest => rest > 0 ? `Show more (${rest} more)` : 'Show more',
    loadingMoreFinished: 'Loading more…',
    finishedMoreError: err => `Could not load more: ${err} (click to retry)`,
    findInDoc: 'Find in document', findPlaceholder: 'Find in document…',
    findMatches: n => `${n} ${n === 1 ? 'match' : 'matches'}`, noFindMatches: 'No matches',
    findPrevMatch: 'Previous match', findNextMatch: 'Next match',
    findProgress: (cur, total) => `${cur} / ${total}`,
    libraryGroupDocs: 'Documents', libraryGroupRepoDocs: 'Repo docs', libraryGroupResearch: 'Research reports', libraryGroupInstructions: 'Instructions',
    supersededLabel: 'Superseded',
    supersededBanner: path => `Finalized in repo: ${path}`,
    openSupersededTarget: 'Open repo doc',
    archiveDraft: 'Archive draft (kept in history)',
    repoDocsTruncated: (shown, total) => `Showing ${shown} of ${total} repo docs (use @Files for the rest)`,
    libraryLoading: 'Reading Library…',
    libraryEmpty: 'No Library documents yet. Drop files here or create one.',
    libraryDropHint: 'Drop files here to add to Documents',
    libraryNoMatches: 'No matching documents or reports.',
    libraryReadError: error => `Could not read Library: ${error}`,
    libraryStale: error => `Could not refresh Library: ${error}`,
    memoryLoading: 'Reading Memory…',
    memoryEmpty: 'No memories yet.',
    memoryNoMatches: 'No matching memories.',
    memoryReadError: error => `Could not read Memory: ${error}`,
    memoryStale: error => `Could not refresh Memory: ${error}`,
    dreamRunning: 'Consolidating…',
    dreamLastAgo: when => `Last consolidated ${when}`,
    dreamJustNow: 'just now',
    dreamAgo: dur => `${dur} ago`,
    dreamMerged: n => `merged ${n}`,
    dreamAdopted: n => `adopted ${n}`,
    dreamArchived: n => `archived ${n}`,
    dreamFlags: n => `${n} to review`,
    dreamPending: n => `${n} pending consolidation`,
    memoryGroupProject: 'Project memory', memoryGroupPersonal: 'Personal memory', memoryGroupCandidates: 'Candidates',
    topic_architecture: 'Product & architecture',
    topic_ui: 'Interface & interaction',
    topic_workflow: 'Collaboration & dispatch',
    topic_ops: 'Environment & release',
    topic_reference: 'Reference',
    topic_pitfalls: 'Engineering pitfalls',
    readOnly: 'Read-only',
    archiveLabel: 'Archive',
    archiveEntries: n => `${n} ${n === 1 ? 'entry' : 'entries'}`,
    publishedLabel: 'Published',
    openSourceThread: title => `Open source thread: ${title}`,
    docLoading: 'Reading document…',
    docNotText: 'Binary or image file; not shown as text here.',
    docTooLarge: 'File exceeds 1 MB and is not read whole here.',
    imageOpenPreview: 'Open image preview',
    imageZoomLightbox: 'Zoom image',
    imageZoomIn: 'Zoom in (+)',
    imageZoomOut: 'Zoom out (-)',
    imageZoomFit: 'Fit to window (0)',
    imageZoomActual: 'Actual size 100% (1)',
    imageZoomCycle: 'Cycle zoom (Fit / 100% / 150% / 200%)',
    imageOpenExternal: 'Open in system preview',
    imageCloseLightbox: 'Close preview (Esc)',
    imageOpenExternalFailed: err => `Could not open in system preview: ${err}`,
    imageLightboxHint: 'Scroll to pan · Double-click Fit / 100% · Esc to close',
    imageLoading: 'Loading image…',
    imageLoadFailed: 'Image preview unavailable',
    imageTooLarge: 'Image is too large to preview here.',
    imageDimensions: (w, h) => `${w} × ${h}`,
    docNotFound: 'Document is no longer in Library.',
    memNotFound: 'Memory is no longer found.',
    docReadError: error => `Could not read document: ${error}`,
    docBackLibrary: 'Back to Library',
    docBackMemory: 'Back to Memory',
    docRetry: 'Retry reading document',
    docShowMore: rest => `Show more (${rest} remaining)`,
    memLayerProject: 'Project', memLayerUser: 'Personal',
    memType_project: 'Decision', memType_feedback: 'Feedback', memType_reference: 'Reference', memType_pitfall: 'Pitfall', memType_user: 'User',
    memBy: who => `By ${who === 'user' ? 'you' : who}`,
    memQuote: q => `“${q}”`,
    memQuoteChecked: 'Verified in log', memQuoteUnchecked: 'Not matched in log',
    memVerified: how => `Basis: ${how}`,
    memChecked: date => `Checked ${date}`,
    memExpires: date => `Expires ${date}`, memExpired: 'Expired',
    candidateAdopt: 'Adopt into project memory',
    candidateDiscard: 'Discard candidate',
    newDoc: 'New document', newMemory: 'New memory',
    addFiles: 'Add files to Library (or drop files here)',
    addingFiles: name => `Adding ${name}…`,
    addFileFailed: (name, error) => `Could not add ${name}: ${error}`,
    remoteDropTextOnly: machine => `Only text files up to 1 MB can be dropped to remote machine ${machine}.`,
    memoryDropMdOnly: 'Drop Markdown or text files (.md, .txt) into Memory.',
    editDoc: 'Edit', saveEdit: 'Save (⌘S)', savingEdit: 'Saving…', cancelEdit: 'Cancel editing (Esc)',
    docNamePlaceholder: 'filename.md', docBodyPlaceholder: 'Write document content…',
    memNamePlaceholder: 'short-english-slug', memDescPlaceholder: 'One-sentence summary…', memBodyPlaceholder: 'Details (optional)…',
    saveFailed: error => `Could not save: ${error}`,
    conflictNotice: 'Changed on disk since it was opened.',
    conflictReload: 'Reload latest version',
    conflictOverwrite: 'Overwrite with your edits',
    retopicTip: 'Move to another topic or type',
    retopicFailed: error => `Could not update topic: ${error}`,
    deleteItem: 'Delete (kept in history)',
    confirmDeleteHint: 'Delete? Recoverable from history.',
    confirmDelete: 'Confirm delete',
    cancelDelete: 'Cancel (Esc)',
    deleteFailed: error => `Could not delete: ${error}`,
    deletedNotice: name => `Deleted ${name}`,
    undoDelete: 'Restore deleted item',
    dismissNotice: 'Dismiss',
    docHistory: 'History & recovery',
    historyTitle: 'History',
    historyLoading: 'Reading history…',
    historyEmpty: 'No saved history yet.',
    historyReadError: error => `Could not read history: ${error}`,
    historyWhyDeleted: 'Deleted',
    historyWhyReplaced: 'Replaced',
    restoreVersion: 'Restore this version',
    restoringVersion: 'Restoring…',
    restoreFailed: error => `Could not restore: ${error}`,
    kindDecisions: 'Decisions', kindHandover: 'Handover', kindMemoryIndex: 'Memory index',
    kindImage: 'Image', kindFile: 'File', kindFolderCount: n => `${n} ${n === 1 ? 'item' : 'items'}`,
    contextUsage: s => `Context ${s}`,
    pmContextNormal: (s, cap) => cap ? `Context ${s} (compact above ${cap})` : `Context ${s}`,
    pmContextNear: (s, cap) => `Context ${s} · approaching ${cap} compaction`,
    pmContextOver: (s, cap) => `Context ${s} · over ${cap} compact threshold`,
    workerContextTip: n => `Session context: ${n.toLocaleString('en-US')} tokens`,
    threadLogTab: 'Log', threadSessionTab: 'Conversation',
    sessionLoading: 'Reading conversation…',
    sessionEmpty: 'No messages in this session yet.',
    sessionUnknown: 'Could not read this session transcript; the agent format may have changed.',
    sessionStale: error => `Could not refresh conversation: ${error}`,
    earlierSession: 'Show earlier messages', loadingEarlierSession: 'Reading earlier messages…',
    earlierSessionFailed: error => `Could not read earlier messages: ${error} (click to retry)`,
    unfoldMessage: 'Show whole message',
    toolRunBash: n => `Ran ${n} ${n === 1 ? 'command' : 'commands'}`,
    toolRunRead: n => `Read ${n} ${n === 1 ? 'file' : 'files'}`,
    toolRunEdit: n => `Edited ${n} ${n === 1 ? 'file' : 'files'}`,
    toolRunSearch: n => `Searched ${n} ${n === 1 ? 'time' : 'times'}`,
    toolRunAgent: n => `Ran ${n} ${n === 1 ? 'subtask' : 'subtasks'}`,
    toolRunWeb: n => `Checked web ${n} ${n === 1 ? 'time' : 'times'}`,
    toolRunOther: n => `Used ${n} ${n === 1 ? 'other tool' : 'other tools'}`,
    toolRunTools: n => `Used ${n} ${n === 1 ? 'tool' : 'tools'}`,
    toolErrors: n => `${n} failed`,
    sessionQuestionLabel: 'Question',
    sessionQuestionTerminalHint: 'Waiting on a terminal prompt? Switch to terminal in the top-right to respond.',
    sessionQuestionAnswered: 'Response',
    workedHours: (h, m) => `Worked ${h}h ${m}m`,
    workedMinutes: (m, s) => `Worked ${m}m ${s}s`,
    workedSeconds: s => `Worked ${s}s`,
    ...PLAN_STRINGS.en,
    ...THREAD_STRINGS.en,
    mentionThreads: 'Threads',
    mentionLibrary: 'Library',
    mentionFiles: 'Files',
    mentionBack: 'Back (Esc)',
    mentionTypeThread: 'Thread',
    mentionTypeSession: 'Session',
    mentionTypeDoc: 'Document',
    mentionTypeRepoDoc: 'Repo doc',
    mentionTypeResearch: 'Research',
    mentionTypeInstructions: 'Instructions',
    mentionTypeMemory: 'Memory',
    mentionTypeFile: 'File',
    mentionEmpty: 'No matches',
    mentionEmptyThreads: 'No threads in this project',
    mentionEmptyLibrary: 'No Library documents',
    mentionEmptyFiles: 'No repository files found',
    mentionLoadingFiles: 'Loading repository files…',
    mentionFilesError: error => `Could not list repository files: ${error}`,
    mentionFilesTruncated: n => `Indexed first ${n.toLocaleString('en-US')} files`,
    mentionOpenRef: target => `Open ${target}`,
    mentionCopyPath: 'Copy path',
    mentionPathCopied: 'Path copied',
    docBackRepo: 'Close file preview',
    repoFileNotFound: 'File is no longer in the repository.',
    quoteMessage: 'Quote',
    quoteWholeMessage: 'Quote whole message',
    quoteParagraph: 'Quote paragraph',
    quoteSelection: 'Quote copied selection',
    quoteScopeMessage: 'Full',
    quoteScopeParagraph: n => (Number.isInteger(n) && n >= 0 ? `¶${n + 1}` : 'Paragraph'),
    quoteScopeParagraphTip: n => (Number.isInteger(n) && n >= 0 ? `Paragraph ${n + 1}` : 'Paragraph'),
    quoteScopeSelection: 'Excerpt',
    quoteRemove: 'Remove quote',
    quoteJump: 'Jump to original message',
    quoteJumpMissing: 'Original message is earlier in the log',
    quoteFrom: (author, time) => (time ? `${author} · ${time}` : author),
    quoteAuthorPm: 'PM',
    quoteAuthorYou: 'You',
    quoteAuthorQuestion: 'Question',
    quoteCount: n => `${n} ${n === 1 ? 'quote' : 'quotes'}`,
    quoteSelectionAction: 'Quote selection',
    closeSidePanel: 'Close side panel',
    resetPanelWidthTip: 'Drag to resize; double-click to reset this view’s width',
    sideTabsIndex: 'Browse Threads / Library / Memory',
    sideTabsAll: n => `${n} open tabs`,
    sideTabClose: 'Close tab',
    sideTabCloseOthers: 'Close other tabs',
    sideTabCloseRight: 'Close tabs to the right',
    sideTabCloseAll: 'Close all tabs',
    sideTabDirtyHint: name => `Unsaved changes in ${name}`,
    sideTabDirtyWarning: 'Unsaved changes will be lost on close.',
    sideTabSaveAndClose: 'Save & close',
    sideTabDiscardAndClose: 'Discard & close',
    sideTabCancelClose: 'Cancel (Esc)',
    sideTabLimitDirty: 'All 12 open tabs have unsaved edits; save or close one first.',
    sideTabOpened: 'Open',
    sideTabCopyPath: 'Copy path',
    sideTabMissing: 'No longer exists',
    switchToBoard: 'Switch to Board',
    renameProject: 'Rename project',
    filterThreads: 'Filter Threads…',
    filterLibrary: 'Filter Library…',
    filterMemory: 'Filter Memory…',
    inlineFilterHint: 'Esc',
    sideTabsOverflow: n => `+${n}`,
    sideTabsOverflowTip: n => `${n} more open tabs`,
    workspaceFolders: n => `Workspace folders (${n})`,
    workspaceFoldersSub: 'All folders equal · click alias to rename',
    workspaceFoldersEmptyTip: 'Link 0 or more workspace folders',
    workspaceFoldersTip: n => `${n} workspace ${n === 1 ? 'folder' : 'folders'} · click to manage`,
    addFolder: 'Add folder…',
    addFolderShort: 'Add folder',
    addFolderOn: m => `Add folder on ${m}…`,
    noFoldersLinked: 'No folders linked yet',
    folderAliasRenameTip: 'Click to rename alias',
    unlinkFolderTip: 'Unlink folder (keeps files on disk)',
    unlinkFolderActiveWarn: (alias, n) => `${n} active ${n === 1 ? 'thread still runs' : 'threads still run'} in “${alias}”. Unlink anyway?`,
    unlinkAnyway: 'Unlink',
    cancel: 'Cancel',
    folderBadgeNonGit: 'folder',
    folderMissing: 'missing',
    multiGitDispatchHint: n => `${n} git repos · pass --folder <alias> on dispatch`,
    enterRemotePath: m => `Path on ${m}, e.g. ~/project/repo…`,
    browseRemote: m => `Browse ${m}`,
    browseRemoteTip: m => `Browse folders on ${m}`,
    folderNotFoundRemote: m => `Directory does not exist on ${m}`,
    createRemoteFolder: 'Create folder',
    addBtn: 'Add',
    remoteFoldersUnsupported: m => `Update pm.py on ${m} to manage workspace folders`,
    mentionFilesMultiTitle: n => `Files · ${n} folders`,
    mentionEmptyFilesNoFolders: 'No workspace folders linked yet',
    folderAliasTip: (alias, path) => (path ? `Folder ${alias} · ${path}` : `Folder ${alias}`),
    ...CHANGE_STRINGS.en,
    ...SEARCH_STRINGS.en,
  },
  zh: {
    you: '你', waiting: '等你', waitingCount: n => `${n} 件事等你`, nothingWaiting: '没有等你的事',
    openPm: '打开 PM 终端', noPmTerminal: 'PM 不在桌面里',
    startPm: '启动 PM 会话（从交接记录接手）', startingPm: '正在启动 PM 会话…',
    startPmFailed: error => `没能启动 PM：${error}`,
    pmOfflineStartable: 'PM 会话未在运行 · 点启动图标从交接记录接手',
    pmOfflineArchived: '这个项目已归档；在 Projects → 已归档 里恢复。',
    pmOfflineTui: '这个 PM 注册在 Herdr TUI 里，不在桌面里。',
    pmOfflineMissingRepo: '这台机器上找不到项目目录。',
    chatView: '对话', boardView: '看板',
    say: name => `对 ${name} 的协调者说…`, sayThread: '只对这个线程说…',
    send: '发送', sendThread: '发给这个线程',
    offline: '这个项目没有在桌面里运行的 PM 会话。点启动图标启动它。',
    threadOffline: '这个线程没有在线的终端',
    subThreads: '拆出的子线程', partOf: title => `属于 ${title}`, moreParts: n => `还有 ${n} 条`,
    reviewThread: '审查', openReviewTerminal: '打开审查终端',
    disconnected: '已断开', group_offline: '已断开',
    closedReattach: '已关闭，可重连',
    closedWhy_workers_close_reported: '汇报后空闲关闭',
    closedWhy_idle_workers: '空闲清理',
    closedWhy_workers_close_on_close: '随任务收起',
    closedWhy_retire: '回收时关闭',
    closedWhy_killed: '手动关闭终端',
    closedDetail: detail => detail ? `已关闭，可重连（${detail}）` : '已关闭，可重连',
    reattach: '接回：恢复这个线程的 agent 会话；找不到会话就新开一个，把任务书和台账记录交给它',
    reattachClosed: detail => detail
      ? `已关闭（${detail}）——接回：恢复这个线程的 agent 会话；找不到会话就新开一个，把任务书和台账记录交给它`
      : '接回：恢复这个线程的 agent 会话；找不到会话就新开一个，把任务书和台账记录交给它',
    reattaching: '正在接回…', reattachFailed: error => `没接回：${error}`,
    bringAllBack: '查看并全部带回',
    bringBackStart: '开始全部带回',
    bringBackRetry: '重试未完成的项',
    bringingBack: '正在带回…',
    bringBackDismiss: '不用带回，收起这一行',
    bringBackCollapse: '收起（Esc）',
    bringBackHintWithPm: '先启动 PM，再把线程逐个接回它下面。',
    bringBackHintThreads: '把这些线程逐个接回项目 PM 下面。',
    bringBackPmStep: name => `${name} PM（从交接记录接手）`,
    openTerminal: '打开终端', terminalNowhere: '它的终端不在任何窗格里，PM 也不在，没有地方打开它',
    diff: '看改动', close: '收起',
    resizePanel: '拖动调整侧栏宽度，双击恢复默认宽度',
    sending: '正在发送…', queued: '排队中', queuedTip: '等待 PM 可接收后自动送达',
    queuedReasonStarting: 'PM 会话正在启动',
    queuedReasonInflight: '等待上一条消息送达',
    queuedReasonFifo: '等待前面的排队消息',
    queuedReasonBlocked: 'PM 终端正停在交互提示上',
    queuedReasonError: 'PM 终端报告了错误',
    queuedReasonDraft: '排队中（终端有未发草稿）',
    queuedReasonWorking: '等待 PM 当前轮次结束',
    queuedReasonOffline: '等待 PM 会话恢复',
    queuedReasonDisconnected: '等待远程机器重连',
    queuedReasonTimeout: '正在核对投递状态',
    queuedReasonNewSession: '换了 PM 会话，重新发送',
    queuedReasonTypist: '等另一条消息打完',
    queuedReasonCarried: '更新前没送出，接着发送',
    queuedReasonRetryUnstarted: 'PM 没接住，重新发送',
    queuedReasonRetryInterrupted: '那一轮被打断，重新发送',
    queuedReasonRetryErrored: '那一轮出错，重新发送',
    queuedReasonUnsupported: '这个 PM 收不了这类消息',
    queuedReasonOther: '等待发送',
    turnInterrupted: '那一轮被打断',
    turnErrored: '那一轮出错',
    bubbleStateAccepted: '排队中',
    bubbleStateSending: '发送中',
    bubbleStateTyped: '已送达',
    bubbleStateTypedStep: '已送达，等它做完这一步',
    bubbleStateTypedTurn: '已送达，等它答完这一轮',
    bubbleStateConsumed: '已读到',
    bubbleStateAnswered: '已回复',
    bubbleStateFailed: '发送失败',
    pmUndeliveredMessages: (n, dur, detail) => `${n} 条消息已等待 ${dur}未打进 PM 终端${detail ? `（${detail}）` : ''}`,
    queuedSummary: n => `${n} 条消息排队中，恢复后自动送达`,
    pmQueuedOnly: n => `${n} 条消息排队中，PM 可接收时自动送达`,
    pmBlockedQuestion: 'PM 正停在终端提问对话框上',
    pmBlockedPermission: 'PM 正等待终端里的权限确认',
    pmBlockedTrust: 'PM 正停在终端目录信任确认框上',
    pmBlockedUpdate: 'PM 正停在终端升级提示框上',
    pmBlockedHook: 'PM 正停在终端钩子或 MCP 审批框上',
    pmBlockedAuth: 'PM 需要在终端重新登录鉴权',
    pmBlockedQuota: 'PM 遇到了配额或限流提示',
    pmBlockedDraft: 'PM 终端里有未发送的草稿，清掉或发完后会自动送达',
    pmBlockedUnknown: 'PM 终端正停在交互提示上',
    pmUndelivered: (n, dur, detail) => `${n} 条事件已等待 ${dur}未能送达 PM${detail ? `（${detail}）` : ''}`,
    delivererStopped: '投递器未运行',
    unconfirmedSend: '已送到 PM 终端，但对话里一直没记下这条',
    unsureSend: '发送没有结束，PM 可能没收到',
    checkingSent: '正在核对 PM 是否已收到…',
    pmOfflineFailed: 'PM 会话已停止，未能收到此消息，点此重发',
    retrySend: '重新发送',
    pmTurnThinking: dur => `正在思考 · ${dur}`,
    pmTurnPreamble: (text, dur) => `${text} · ${dur}`,
    pmTurnLongGen: dur => `正在生成较长内容 · ${dur}`,
    pmTurnTool: (summary, dur) => `正在运行 ${summary} · ${dur}`,
    pmTurnToolSlow: (summary, dur) => summary ? `前台命令已运行 ${dur}：${summary}` : `前台命令已运行 ${dur}`,
    pmTurnToolSuspect: summary => summary ? `命令可能在等输入：${summary}` : '命令可能在等输入',
    pmTurnRetrying: attempt => attempt ? `模型服务重试中（第 ${attempt} 次）` : '模型服务重试中',
    pmTurnBlocked: kind => kind ? `等你在终端确认：${kind}` : '等你在终端确认',
    pmTurnRecovering: step => step ? `正在自动恢复：${step}` : '正在自动恢复…',
    incidentRecovering: step => step ? `正在自动恢复：${step}` : '正在自动恢复…',
    incidentRecovered: detail => detail ? `已自动恢复 · ${detail}` : '已自动恢复',
    incidentFolded: detail => detail ? `已自动恢复 · ${detail}` : '已自动恢复',
    incidentNotified: detail => detail ? `需要你介入：${detail}` : '需要你介入',
    recoveryStep_interrupt_tool: '打断卡住的前台命令',
    recoveryStep_interrupt_turn: '打断当前步骤',
    recoveryStep_continue_turn: '续上本轮',
    recoveryStep_nudge_enter: '轻推终端启动',
    recoveryStep_retype_submitted: '重发本条消息',
    recoveryStep_restart_seat: '重启 PM 会话',
    recoveryStep_switch_profile: '切换到备用模型',
    recoveryStep_classify_screen: '检查终端屏幕',
    recoveryStep_waiting_draft: '等待终端草稿清空',
    recoveryStep_notify_user: '等待你处理',
    recoveryStep_unblock_safe_dialog: '处理安全终端提示',
    pmTurnSlow: (detail, dur) => detail ? `等待返回：${detail} · ${dur}` : `仍在处理 · ${dur}`,
    pmTurnStalled: (detail, dur) => detail ? `已连续 ${dur} 无响应 · ${detail}` : `已连续 ${dur} 无响应`,
    pmTurnStalledEvidence: (dur, evidence) => evidence ? `无响应 ${dur}（依据：${evidence}）` : `无响应 ${dur}`,
    pmEvidencePtyFrozen: '屏幕 45 秒未变',
    pmEvidenceNoStep: '4 分钟没有新的一步',
    pmEvidenceToolHard: '前台命令超过硬预算',
    pmEvidenceToolInput: '命令可能在等输入',
    pmEvidenceSubmitted: '发出后未开始执行',
    pmEvidenceUpstream: '模型服务超时',
    pmTurnTotalTip: dur => `本轮总耗时：${dur}`,
    openPmBgShells: n => `打开 PM 终端（${n} 个后台命令）`,
    pmBusyTimingStep: '做完这一步',
    pmBusyTimingTurn: '答完这一轮',
    pmBusyActThinking: '思考',
    pmBusyActLongGen: '生成较长内容',
    pmBusyActRetrying: '等待模型服务重试',
    pmBusyActRunning: summary => `运行 ${summary}`,
    pmBusyComposer: (activity, timing) => `协调者正在${activity}；这条消息会在它${timing}后被看到`,
    pmBusyComposerQueued: (activity, timing, n) => `协调者正在${activity}；${n > 1 ? `${n} 条排队消息` : '排队消息'}会在它${timing}后被看到`,
    pmPreemptAction: '打断它，先处理这条',
    pmPreemptQueuedAction: '打断它，先处理排队消息',
    pmTurnUnknown: '状态未知，正在重连…',
    interruptPmTip: '打断当前耗时操作（保留 PM 会话）',
    interruptingPmTip: '正在打断…',
    interruptStopped: '已打断当前操作',
    interruptStillWorking: '打断没有生效（仍在运行）',
    interruptExited: 'PM 进程已退出',
    interruptUnknown: '已发送打断（结果未知）',
    interruptFailed: error => `打断失败：${error}`,
    rotatePmTip: '换新会话从台账接手',
    rotatingPmTip: '正在切换新会话接手…',
    rotateSucceeded: '已切换新会话接手',
    rotateFailed: error => `换新会话失败：${error}`,
    failed: error => `没发出去：${error}`, decision: '决定',
    pick: '在 PM 列表里点一个项目，打开它的对话。', noProject: '台账里已经没有这个 PM。',
    remoteLoading: machine => `正在从 ${machine} 读取这个项目…`,
    remoteError: (machine, error) => `读不到 ${machine} 上的这个项目。确认这台机器在 Herdr 里已连接，并装了 pm 技能。\n${error}`,
    remoteAttach: machine => `添加附件（也可以把文件拖进来，或粘贴截图）；发送时会先传到 ${machine}`,
    empty: '这个项目还没有对话。', readError: '对话记录读取失败',
    today: '今天', yesterday: '昨天', noLog: '暂无日志', agent: (program, address) => `${program} · 终端 ${address}`,
    unfold: '展开全文', fold: '收起',
    threads: '线程', showThreads: '显示线程列表', hideThreads: '收起线程列表',
    group_waiting: '等你', group_review: '审查中', group_working: '进行中', group_paused: '暂停', group_parked: '未开始',
    groupSessions: '对话', groupFinished: '已结束', recommended: '推荐', handledByPm: 'PM 已处理', openThread: '打开这个线程',
    ownAnswer: '用自己的话回答…', answeringTo: title => `回答 ${title}`, stopAnswering: '不回答这个问题了（Esc）',
    noThreads: '这个项目还没有线程。', openSession: '点击打开这个对话',
    session_working: '工作中', session_blocked: '等你', session_done: '已完成', session_idle: '空闲',
    in_progress: '进行中', blocked: '阻塞', answered: '已回答', review: '审查中', paused: '暂停', proposed: '提议',
    merged: '已合并', released: '已发布', done: '完成', abandoned: '放弃', cleanup: '已合并 · 待回收',
    attach: '添加附件（也可以把文件拖进来，或粘贴截图）', removeFile: name => `移除 ${name}`,
    attachFailed: error => `附件没加上：${error}`, attachments: '附件：',
    uploadFailed: (name, machine, error) => `${name} 没传到 ${machine}：${error}`,
    notAFile: names => `不是文件：${names}`, noPasteFolder: '这个项目还没有对话记录，贴的图没有地方存',
    engineProfile: name => `档位：${name}`, engineWhy: why => `理由：${why}`, engineRounds: n => `评审轮数：${n}`,
    engineEscalatedTimes: n => `升级过 ${n} 次`,
    engineEscalated: (from, to, why) => `升级 ${from} → ${to}${why ? `：${why}` : ''}`,
    engineAdvisor: name => `顾问：${name}`, effortDefault: '默认',
    earlierMessages: '往前翻更早的对话', loadingEarlier: '正在读取更早的对话…',
    earlierFailed: error => `没读到更早的对话：${error}（点击重试）`,
    earlierLog: n => `往前翻更早的 ${n} 条记录`, loadingEarlierLog: '正在读取更早的记录…',
    earlierLogFailed: error => `没读到更早的记录：${error}（点击重试）`,
    libraryTab: 'Library',
    memoryTab: 'Memory',
    showSidePanel: '显示侧栏', hideSidePanel: '收起侧栏',
    windowMinimize: '最小化', windowMaximize: '最大化', windowRestore: '还原', windowClose: '关闭',
    searchLibrary: '搜索 Library…', searchMemory: '搜索 Memory…', searchThreads: '搜索线程…', clearSearch: '清除搜索',
    threadsSearching: '正在搜索线程…',
    threadsNoMatches: '没有匹配的线程。',
    threadsSearchError: err => `搜索线程失败：${err}`,
    loadMoreFinished: rest => rest > 0 ? `显示更多（还有 ${rest} 条）` : '显示更多',
    loadingMoreFinished: '正在加载更多…',
    finishedMoreError: err => `加载更多失败：${err}（点击重试）`,
    findInDoc: '在文档内查找', findPlaceholder: '在当前文档里查找…',
    findMatches: n => `${n} 处匹配`, noFindMatches: '无匹配',
    findPrevMatch: '上一处匹配', findNextMatch: '下一处匹配',
    findProgress: (cur, total) => `${cur} / ${total}`,
    libraryGroupDocs: '项目文档', libraryGroupRepoDocs: '仓库文档', libraryGroupResearch: '调研报告', libraryGroupInstructions: '仓库说明',
    supersededLabel: '已定稿',
    supersededBanner: path => `已在仓库定稿：${path}`,
    openSupersededTarget: '查看定稿',
    archiveDraft: '归档草稿（留存历史）',
    repoDocsTruncated: (shown, total) => `已展示 ${shown} / ${total} 篇仓库文档（其余可用 @Files 检索）`,
    libraryLoading: '正在读取 Library…',
    libraryEmpty: '还没有 Library 资料，拖文件进来或点 + 新建。',
    libraryDropHint: '拖文件到这里添加到项目文档',
    libraryNoMatches: '没有匹配的文档或调研报告。',
    libraryReadError: error => `读取 Library 失败：${error}`,
    libraryStale: error => `刷新 Library 失败：${error}`,
    memoryLoading: '正在读取 Memory…',
    memoryEmpty: '还没有记忆。',
    memoryNoMatches: '没有匹配的记忆。',
    memoryReadError: error => `读取 Memory 失败：${error}`,
    memoryStale: error => `刷新 Memory 失败：${error}`,
    dreamRunning: '整理中…',
    dreamLastAgo: when => `上次整理 ${when}`,
    dreamJustNow: '刚刚',
    dreamAgo: dur => `${dur}前`,
    dreamMerged: n => `合并 ${n}`,
    dreamAdopted: n => `收编 ${n}`,
    dreamArchived: n => `归档 ${n}`,
    dreamFlags: n => `${n} 条待你看`,
    dreamPending: n => `${n} 条待整理`,
    memoryGroupProject: '项目记忆', memoryGroupPersonal: '个人记忆', memoryGroupCandidates: '待审候选',
    topic_architecture: '产品与架构',
    topic_ui: '界面与交互',
    topic_workflow: '协作与派活',
    topic_ops: '环境与发版',
    topic_reference: '参考',
    topic_pitfalls: '工程踩坑',
    readOnly: '只读',
    archiveLabel: '历史归档',
    archiveEntries: n => `${n} 条`,
    publishedLabel: '已公开',
    openSourceThread: title => `跳回来源线程：${title}`,
    docLoading: '正在读取文档…',
    docNotText: '二进制或图片文件，不在面板内按文本展开。',
    docTooLarge: '文件超过 1 MB，不在面板内整篇读取。',
    imageOpenPreview: '打开原图预览',
    imageZoomLightbox: '全屏放大查看',
    imageZoomIn: '放大（+）',
    imageZoomOut: '缩小（-）',
    imageZoomFit: '适应窗口（0）',
    imageZoomActual: '100% 原图（1）',
    imageZoomCycle: '切换缩放（适应窗口 / 100% / 150% / 200%）',
    imageOpenExternal: '用系统应用打开原图',
    imageCloseLightbox: '关闭预览（Esc）',
    imageOpenExternalFailed: err => `无法用系统应用打开：${err}`,
    imageLightboxHint: '滚轮/双指平移细节 · 双击切换适应/100% · Esc 关闭',
    imageLoading: '正在加载图片…',
    imageLoadFailed: '无法加载图片预览',
    imageTooLarge: '图片过大，无法在此预览。',
    imageDimensions: (w, h) => `${w} × ${h}`,
    docNotFound: '这份资料已经不在 Library 里。',
    memNotFound: '这条记忆已经不存在。',
    docReadError: error => `读取文档失败：${error}`,
    docBackLibrary: '返回 Library',
    docBackMemory: '返回 Memory',
    docRetry: '重试读取',
    docShowMore: rest => `继续展开（剩余 ${rest}）`,
    memLayerProject: '项目记忆', memLayerUser: '个人记忆',
    memType_project: '决定', memType_feedback: '做法', memType_reference: '参考', memType_pitfall: '踩坑', memType_user: '关于你',
    memBy: who => `写入：${who === 'user' ? '你' : who}`,
    memQuote: q => `「${q}」`,
    memQuoteChecked: '原话已核对', memQuoteUnchecked: '原话未对上',
    memVerified: how => `依据：${how}`,
    memChecked: date => `确认于 ${date}`,
    memExpires: date => `到期 ${date}`, memExpired: '已过期',
    candidateAdopt: '收编进项目记忆',
    candidateDiscard: '丢弃候选',
    newDoc: '新建文档', newMemory: '新建记忆',
    addFiles: '添加文件到 Library（也可直接拖文件进来）',
    addingFiles: name => `正在添加 ${name}…`,
    addFileFailed: (name, error) => `添加 ${name} 失败：${error}`,
    remoteDropTextOnly: machine => `远程机器 ${machine} 仅支持拖入 1 MB 以内的文本文件。`,
    memoryDropMdOnly: 'Memory 仅支持拖入 Markdown 或文本文件（.md、.txt）。',
    editDoc: '编辑', saveEdit: '保存（⌘S）', savingEdit: '正在保存…', cancelEdit: '取消编辑（Esc）',
    docNamePlaceholder: '文件名.md', docBodyPlaceholder: '输入文档内容…',
    memNamePlaceholder: '英文短横线名，如 my-rule', memDescPlaceholder: '一句话摘要…', memBodyPlaceholder: '详细说明（可选）…',
    saveFailed: error => `保存失败：${error}`,
    conflictNotice: '打开后已被修改。',
    conflictReload: '重新加载最新版',
    conflictOverwrite: '覆盖保存',
    retopicTip: '调整主题分组或类型',
    retopicFailed: error => `调整分组失败：${error}`,
    deleteItem: '删除（保留在历史中可恢复）',
    confirmDeleteHint: '确认删除？可从历史恢复。',
    confirmDelete: '确认删除',
    cancelDelete: '取消（Esc）',
    deleteFailed: error => `删除失败：${error}`,
    deletedNotice: name => `已删除 ${name}`,
    undoDelete: '撤销删除并恢复',
    dismissNotice: '关闭提示',
    docHistory: '历史与恢复',
    historyTitle: '历史记录',
    historyLoading: '正在读取历史…',
    historyEmpty: '还没有历史记录。',
    historyReadError: error => `读取历史失败：${error}`,
    historyWhyDeleted: '已删除',
    historyWhyReplaced: '已替换',
    restoreVersion: '恢复此版本',
    restoringVersion: '正在恢复…',
    restoreFailed: error => `恢复失败：${error}`,
    kindDecisions: '项目决定', kindHandover: '交接记录', kindMemoryIndex: '记忆索引',
    kindImage: '图片', kindFile: '文件', kindFolderCount: n => `${n} 项`,
    contextUsage: s => `上下文 ${s}`,
    pmContextNormal: (s, cap) => cap ? `上下文 ${s}（压缩阈值 ${cap}）` : `上下文 ${s}`,
    pmContextNear: (s, cap) => `上下文 ${s} · 接近 ${cap} 压缩阈值`,
    pmContextOver: (s, cap) => `上下文 ${s} · 已超 ${cap} 压缩阈值`,
    workerContextTip: n => `会话上下文：${n.toLocaleString('en-US')} tokens`,
    threadLogTab: '记录', threadSessionTab: '对话',
    sessionLoading: '正在读取对话…',
    sessionEmpty: '还没有对话内容。',
    sessionUnknown: '读不懂这份会话记录，可能是 agent 更新后格式变了。',
    sessionStale: error => `刷新对话失败：${error}`,
    earlierSession: '往前翻更早的对话', loadingEarlierSession: '正在读取更早的对话…',
    earlierSessionFailed: error => `没读到更早的对话：${error}（点击重试）`,
    unfoldMessage: '展开全文',
    toolRunBash: n => `跑了 ${n} 条命令`,
    toolRunRead: n => `读了 ${n} 个文件`,
    toolRunEdit: n => `改了 ${n} 个文件`,
    toolRunSearch: n => `搜了 ${n} 次`,
    toolRunAgent: n => `派了 ${n} 个子任务`,
    toolRunWeb: n => `查了 ${n} 次网页`,
    toolRunOther: n => `用了 ${n} 次别的工具`,
    toolRunTools: n => `用了 ${n} 次工具`,
    toolErrors: n => `${n} 处报错`,
    sessionQuestionLabel: '向你提问',
    sessionQuestionTerminalHint: '若停在终端交互菜单，可点右上角切到终端操作。',
    sessionQuestionAnswered: '回复',
    workedHours: (h, m) => `干了 ${h} 小时 ${m} 分`,
    workedMinutes: (m, s) => `干了 ${m} 分 ${s} 秒`,
    workedSeconds: s => `干了 ${s} 秒`,
    ...PLAN_STRINGS.zh,
    ...THREAD_STRINGS.zh,
    mentionThreads: '线程',
    mentionLibrary: 'Library',
    mentionFiles: '文件',
    mentionBack: '返回（Esc）',
    mentionTypeThread: '线程',
    mentionTypeSession: '会话',
    mentionTypeDoc: '文档',
    mentionTypeRepoDoc: '仓库文档',
    mentionTypeResearch: '调研',
    mentionTypeInstructions: '说明',
    mentionTypeMemory: '记忆',
    mentionTypeFile: '文件',
    mentionEmpty: '没有匹配项',
    mentionEmptyThreads: '这个项目还没有线程',
    mentionEmptyLibrary: '没有 Library 文档',
    mentionEmptyFiles: '没有找到仓库文件',
    mentionLoadingFiles: '正在读取仓库文件…',
    mentionFilesError: error => `读取仓库文件失败：${error}`,
    mentionFilesTruncated: n => `仅索引前 ${n.toLocaleString('en-US')} 个文件`,
    mentionOpenRef: target => `打开 ${target}`,
    mentionCopyPath: '复制路径',
    mentionPathCopied: '已复制路径',
    docBackRepo: '关闭文件预览',
    repoFileNotFound: '仓库里找不到这个文件。',
    quoteMessage: '引用',
    quoteWholeMessage: '引用整条消息',
    quoteParagraph: '引用此段',
    quoteSelection: '引用已复制的选中段落',
    quoteScopeMessage: '整条',
    quoteScopeParagraph: n => (Number.isInteger(n) && n >= 0 ? `第 ${n + 1} 段` : '段落'),
    quoteScopeParagraphTip: n => (Number.isInteger(n) && n >= 0 ? `第 ${n + 1} 段` : '段落'),
    quoteScopeSelection: '片段',
    quoteRemove: '移除引用',
    quoteJump: '跳回原文',
    quoteJumpMissing: '原消息在更早的对话记录里',
    quoteFrom: (author, time) => (time ? `${author} · ${time}` : author),
    quoteAuthorPm: 'PM',
    quoteAuthorYou: '你',
    quoteAuthorQuestion: '提问',
    quoteCount: n => `${n} 段引用`,
    quoteSelectionAction: '引用所选',
    closeSidePanel: '关闭侧栏',
    resetPanelWidthTip: '拖动调整分栏宽度，双击恢复当前视图默认宽度',
    sideTabsIndex: '浏览线程 / Library / Memory',
    sideTabsAll: n => `已打开 ${n} 个标签页`,
    sideTabClose: '关闭标签页',
    sideTabCloseOthers: '关闭其他标签页',
    sideTabCloseRight: '关闭右侧标签页',
    sideTabCloseAll: '关闭全部标签页',
    sideTabDirtyHint: name => `${name} 有未保存的修改`,
    sideTabDirtyWarning: '未保存的修改将在关闭后丢失。',
    sideTabSaveAndClose: '保存并关闭',
    sideTabDiscardAndClose: '放弃修改并关闭',
    sideTabCancelClose: '取消（Esc）',
    sideTabLimitDirty: '已打开的 12 个标签页均含未保存修改，请先保存或关闭一个。',
    sideTabOpened: '已打开',
    sideTabCopyPath: '复制路径',
    sideTabMissing: '文件已不存在',
    switchToBoard: '切换到看板',
    renameProject: '重命名项目',
    filterThreads: '筛选线程…',
    filterLibrary: '筛选资料库…',
    filterMemory: '筛选记忆…',
    inlineFilterHint: 'Esc',
    sideTabsOverflow: n => `+${n}`,
    sideTabsOverflowTip: n => `还有 ${n} 个已打开标签`,
    workspaceFolders: n => `关联文件夹（${n}）`,
    workspaceFoldersSub: '全部目录平权 · 点击别名重命名',
    workspaceFoldersEmptyTip: '关联 0 个或多个工作区文件夹',
    workspaceFoldersTip: n => `已关联 ${n} 个文件夹 · 点击管理`,
    addFolder: '添加文件夹…',
    addFolderShort: '添加文件夹',
    addFolderOn: m => `在 ${m} 添加文件夹…`,
    noFoldersLinked: '暂未关联文件夹',
    folderAliasRenameTip: '点击修改别名',
    unlinkFolderTip: '解除关联（不删除盘上文件）',
    unlinkFolderActiveWarn: (alias, n) => `「${alias}」下仍有 ${n} 个进行中线程，确定解除关联？`,
    unlinkAnyway: '确认解绑',
    cancel: '取消',
    folderBadgeNonGit: '目录',
    folderMissing: '不存在',
    multiGitDispatchHint: n => `含 ${n} 个 Git 仓库 · 派发需指定 --folder <alias>`,
    enterRemotePath: m => `${m} 上的路径，如 ~/project/repo…`,
    browseRemote: m => `浏览 ${m}`,
    browseRemoteTip: m => `浏览 ${m} 上的文件夹`,
    folderNotFoundRemote: m => `${m} 上不存在该目录`,
    createRemoteFolder: '新建此目录',
    addBtn: '添加',
    remoteFoldersUnsupported: m => `请更新 ${m} 上的 pm.py 以管理关联文件夹`,
    mentionFilesMultiTitle: n => `文件 · ${n} 个文件夹`,
    mentionEmptyFilesNoFolders: '暂未关联文件夹',
    folderAliasTip: (alias, path) => (path ? `仓库 ${alias} · ${path}` : `仓库 ${alias}`),
    ...CHANGE_STRINGS.zh,
    ...SEARCH_STRINGS.zh,
  },
};
export function word(lang, key, ...args) {
  const value = STRINGS[lang === 'zh' ? 'zh' : 'en'][key];
  return typeof value === 'function' ? value(...args) : value ?? key;
}

export const EVENT_LIMIT = 200;
export const LOG_LIMIT = 60;
export const WAITING = ['blocked'];
// Work that is over: its thread is one quiet line in the conversation, not a card row.
export const CLOSED = ['merged', 'released', 'done', 'abandoned'];
// Work that was given up (a proposal another task replaced, a test run) is not shown among the
// threads: no line in the conversation, no place in the side panel. A question it asked stays in
// the conversation, and a link that names it still opens it.
const GIVEN_UP = 'abandoned';
// A task in one of these has work to show. One that enters the log `blocked` and never reaches any
// of them is only the coordinator asking (`pm.py new --status blocked`, then closed with the answer).
const WORK = ['in_progress', 'review', 'paused', 'proposed'];

// The tasks in these events that are only a question: the question line stands for them, so they
// get no thread row in the conversation and are not listed among the threads that ended.
export function questionOnly(events) {
  const first = new Map(), worked = new Set();
  for (const e of events || []) {
    if (e.type !== 'thread' || !e.task) continue;
    if (!first.has(e.task)) first.set(e.task, e.status);
    if (WORK.includes(e.status)) worked.add(e.task);
  }
  return new Set([...first].filter(([task, status]) => status === 'blocked' && !worked.has(task)).map(([task]) => task));
}

// A ledger entry that asks the user a question: `pm.py update --status blocked` (its text says
// status=blocked, also while the task already was blocked) or one that offers quick answers (--option).
// A task entering blocked from another status asks too (see timeline). The same rule as pm.py's asks_again.
export function asksAgain(e) {
  return /\bstatus=blocked\b/.test(String(e?.text || '')) || (Array.isArray(e?.options) && e.options.some(o => squash(o)));
}

// The last `limit` events of conversation.jsonl text. Lines that are not JSON
// objects (a torn last line, a stray `null`) are skipped, as pm.py does.
export function parseConversation(text, limit = EVENT_LIMIT) {
  const events = [];
  for (const line of String(text || '').split('\n')) {
    if (!line.trim()) continue;
    try {
      const event = JSON.parse(line);
      if (event && typeof event === 'object' && !Array.isArray(event) && typeof event.type === 'string') events.push(event);
    } catch (_) { /* not an event */ }
  }
  return events.slice(-limit);
}

// 'blocked' | 'review' | 'running' | 'quiet': which status color a thread gets. A blocked task the
// user has answered (see answeredTasks) is quiet: it waits for the coordinator, not for the user.
export function tone(status, cleanup = false, offline = false, answered = false) {
  if (cleanup || (offline && status === 'in_progress') || (answered && status === 'blocked')) return 'quiet';
  if (status === 'blocked') return 'blocked';
  if (status === 'review') return 'review';
  return status === 'in_progress' ? 'running' : 'quiet';
}

export function statusLabel(lang, status, cleanup = false, offline = false, answered = false, closed = false) {
  if (cleanup) return word(lang, 'cleanup');
  if (answered && status === 'blocked') return word(lang, 'answered');
  if (disconnected({ status, offline })) return word(lang, closed ? 'closedReattach' : 'disconnected');
  return word(lang, status || 'in_progress');
}

// A task `pm.py state` marks offline is open work whose terminal is gone. One in progress then reads as
// Disconnected (or Closed · can reattach when ended on purpose), quietly, not as work going on; one that
// waits for the user or is in review keeps saying so.
export function disconnected(task) {
  return Boolean(task?.offline) && (task.status || 'in_progress') === 'in_progress';
}

// True when an offline task's terminal was ended on purpose (`closed` from `pm.py state`, matching `pane`).
export function isClosedTask(task) {
  if (!task?.offline || !task?.closed || typeof task.closed !== 'object' || Array.isArray(task.closed)) return false;
  return !task.closed.pane || !task.pane || task.closed.pane === task.pane;
}

export function closedDetailText(lang, closed) {
  if (!closed || typeof closed !== 'object') return '';
  const rawWhy = String(closed.why || '').trim();
  const whyKey = rawWhy === 'workers.close_reported' ? 'closedWhy_workers_close_reported'
    : rawWhy === 'idle-workers --close' ? 'closedWhy_idle_workers'
    : rawWhy === 'workers.close_on_close' ? 'closedWhy_workers_close_on_close'
    : rawWhy === 'retire' ? 'closedWhy_retire'
    : rawWhy === 'killed' ? 'closedWhy_killed' : '';
  const why = whyKey ? word(lang, whyKey) : rawWhy;
  const at = String(closed.at || '').trim();
  return [why, at].filter(Boolean).join(lang === 'zh' ? ' · ' : ', ');
}

export function closedTip(lang, closed) {
  return word(lang, 'closedDetail', closedDetailText(lang, closed));
}

// What the header / offline bar can do for the project's PM session:
// 'online' | 'starting' | 'startable' | 'archived' | 'tui_live' | 'tui' | 'missing_repo' | 'none'.
export function pmStartState(pm, terminal, starting = false) {
  if (terminal) return 'online';
  if (starting) return 'starting';
  if (!pm || typeof pm !== 'object') return 'none';
  if (pm.archived) return 'archived';
  const runtime = pm.runtime || (pm.pane && !String(pm.pane).startsWith('hc:') ? 'tui' : '');
  if (runtime === 'tui') return pm.status && pm.status !== 'offline' ? 'tui_live' : 'tui';
  const hasExplicitZero = Array.isArray(pm.folders) && pm.folders.length === 0;
  if (pm.repo_ok === false || (!pm.repo && !hasExplicitZero)) return 'missing_repo';
  return 'startable';
}

export function startPmArgs(pm) {
  if (pm?.repo) {
    const args = ['start', '--repo', String(pm.repo)];
    if (pm?.agent) args.push('--kind', String(pm.agent));
    return args;
  }
  const slug = String(pm?.slug || '').trim();
  const args = slug ? ['start', '--slug', slug] : ['start', '--name', projectName(pm)];
  if (pm?.agent) args.push('--kind', String(pm.agent));
  return args;
}

export function startPmArgv(script, pm) {
  return ['python3', script, ...startPmArgs(pm)];
}

// Agents that did not come back (`pm.lost` from `pm.py state`): shown until dismissed for that loss key,
// and shown again whenever any new lost item appears in `lost.key`.
export function lostShown(lost, dismissed = '') {
  if (!lost || typeof lost !== 'object') return false;
  const hasPm = Boolean(lost.pm && typeof lost.pm === 'object');
  const threads = Array.isArray(lost.threads) ? lost.threads : [];
  if (!hasPm && !threads.length) return false;
  const key = String(lost.key || '');
  if (!key || !dismissed) return true;
  const seen = new Set(String(dismissed).split(';').filter(Boolean));
  return key.split(';').filter(Boolean).some(part => !seen.has(part));
}

export function mergeDismissedLost(dismissed, key) {
  const parts = [...String(dismissed || '').split(';'), ...String(key || '').split(';')].filter(Boolean);
  return [...new Set(parts)].slice(-64).join(';');
}

export function lostSummary(lang, lost) {
  if (!lost || typeof lost !== 'object') return '';
  const hasPm = Boolean(lost.pm && typeof lost.pm === 'object');
  const n = Array.isArray(lost.threads) ? lost.threads.length : 0;
  if (!hasPm && !n) return '';
  const restart = Boolean(lost.restart);
  if (lang === 'zh') {
    if (hasPm && n) return restart ? `重启后 PM 和 ${n} 个 agent 没回来` : `PM 和 ${n} 个 agent 停了，没在运行`;
    if (hasPm) return restart ? '重启后 PM 没回来' : 'PM 停了，没在运行';
    return restart ? `重启后 ${n} 个 agent 没回来` : `${n} 个 agent 停了，没在运行`;
  }
  const agentsWord = n === 1 ? '1 agent' : `${n} agents`;
  if (hasPm && n) return restart ? `PM and ${agentsWord} did not come back after restart` : `PM and ${agentsWord} stopped running`;
  if (hasPm) return restart ? 'PM did not come back after restart' : 'PM stopped running';
  return restart ? `${agentsWord} did not come back after restart` : `${agentsWord} stopped running`;
}

export function bringBackSteps(lang, lost, projectLabel = '') {
  if (!lost || typeof lost !== 'object') return [];
  const steps = [];
  if (lost.pm && typeof lost.pm === 'object') {
    steps.push({
      key: 'pm',
      kind: 'pm',
      id: '',
      address: String(lost.pm.address || ''),
      title: word(lang, 'bringBackPmStep', projectLabel || 'Project'),
    });
  }
  for (const th of Array.isArray(lost.threads) ? lost.threads : []) {
    if (!th?.id) continue;
    const num = taskNumber(th);
    steps.push({
      key: `thread:${th.id}`,
      kind: 'thread',
      id: String(th.id),
      ...(num ? { number: num } : {}),
      address: String(th.address || ''),
      title: String(th.title || th.id),
    });
  }
  return steps;
}

// What the thread panel's terminal icon does: 'open' the thread's live terminal; 'reattach' an offline
// thread (pm.py reattach); 'reattaching' while that runs; 'none' when there is nothing to do; 'hidden'
// (no icon at all) for a task that never had a terminal (no pane) and was split into sub-threads
// (`parts` of them): its work is done there, and they are listed in its panel.
export function terminalAction(terminal, task, busy = false, parts = 0) {
  if (terminal) return 'open';
  if (busy) return 'reattaching';
  if (task?.offline) return 'reattach';
  return !task?.pane && parts > 0 ? 'hidden' : 'none';
}

// `pm.py reattach <id>` as the project view runs it: without this app's terminal identity, so the
// ledger records the user as the one who reattached (as a send does). Pass through
// withoutTerminalEnv (and on Windows, prefer execPython instead of a bare `python3`).
export function reattachArgv(script, id) {
  return ['python3', script, 'reattach', id];
}

export const squash = text => String(text || '').replace(/\s+/g, ' ').trim();

export function searchShortcutLabel(platform = '') {
  return platform === 'macos' ? '⌘K' : 'Ctrl+K';
}

// Bounded FIFO cache helper for pure string/value transforms (O(1) eviction, never thrashes).
function fifoCacheGetSet(cache, key, compute, max = 512) {
  let hit = cache.get(key);
  if (hit !== undefined || cache.has(key)) return hit;
  hit = compute();
  if (cache.size >= max) cache.delete(cache.keys().next().value);
  cache.set(key, hit);
  return hit;
}

const EVENT_TIME_CACHE = new Map();
// "2026-11-13 09:08:12" (pm.py's local time) as ms in this viewer's timezone.
export function eventTime(at) {
  const key = String(at || '');
  if (!key) return 0;
  return fifoCacheGetSet(EVENT_TIME_CACHE, key, () => {
    const ms = new Date(key.replace(' ', 'T')).getTime();
    return Number.isFinite(ms) ? ms : 0;
  }, 512);
}

// Compute the timezone/clock offset (in ms) between `eventTime(server.now)` (parsed in viewer's local
// timezone) and UTC epoch milliseconds (`server_now_ms` when present, else `clientNowMs`).
// Example: viewer at UTC+8 reading a UTC-5 server's `now = "2026-11-23 22:30:05"` yields `-46_800_000` (-13h),
// completely independent of network RTT when `server_now_ms` is present.
export function computeClockOffsetMs(meta, clientNowMs = Date.now()) {
  if (!meta || typeof meta !== 'object') return 0;
  const serverNowMs = Number(meta.server_now_ms);
  const nowStr = typeof meta.now === 'string' ? meta.now.trim() : '';
  if (nowStr && Number.isFinite(serverNowMs) && serverNowMs > 0) {
    const parsedViewer = eventTime(nowStr);
    if (parsedViewer > 0) return parsedViewer - Math.floor(serverNowMs / 1000) * 1000;
  }
  const tz = typeof meta.server_tz === 'string' ? meta.server_tz.trim() : '';
  const mTz = /^([+-])(\d\d):?(\d\d)$/.exec(tz);
  if (mTz) {
    const serverOffsetMin = (mTz[1] === '-' ? -1 : 1) * (Number(mTz[2]) * 60 + Number(mTz[3]));
    const viewerOffsetMin = -new Date(clientNowMs).getTimezoneOffset();
    return (serverOffsetMin - viewerOffsetMin) * 60_000;
  }
  if (nowStr && Number.isFinite(clientNowMs) && clientNowMs > 0) {
    const parsedViewer = eventTime(nowStr);
    if (parsedViewer > 0) {
      const diff = parsedViewer - clientNowMs;
      // Snap pre-upgrade remote servers (lacking server_now_ms) to 15-min timezone boundaries when >= 10m apart.
      if (Math.abs(diff) >= 10 * 60_000) return Math.round(diff / (15 * 60_000)) * (15 * 60_000);
    }
  }
  return 0;
}

// Canonical UTC epoch timestamp (ms) of a ledger event or receipt, immune to viewer/server timezone skew.
export function eventTimeUtcMs(e, clockOffsetMs = 0) {
  if (!e || typeof e !== 'object') return 0;
  const explicit = Number(e.at_ms);
  if (Number.isFinite(explicit) && explicit > 0) return explicit;
  const rawAt = typeof e.at === 'string' ? e.at.trim() : '';
  if (!rawAt) return 0;
  if (typeof e.tz === 'string' && /^[+-]\d\d:?\d\d$/.test(e.tz.trim())) {
    const isoWithTz = `${rawAt.replace(' ', 'T')}${e.tz.trim()}`;
    const parsed = Date.parse(isoWithTz);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
  }
  const naive = eventTime(rawAt);
  if (!(naive > 0)) return 0;
  return naive - (Number(clockOffsetMs) || 0);
}

// Match an ordered subsequence of >= 2 eligible pending bubbles against a single coalesced text
// (e.g. when `agy` or Claude Code merges multiple queued inputs sent during a busy PM turn with `\n`).
export function matchCoalescedBubbles(loggedText, candidates, { truncated = false } = {}) {
  const raw = String(loggedText ?? '');
  if (!raw.trim() || !Array.isArray(candidates) || candidates.length < 2) return null;
  const lines = raw.replace(/\r\n/g, '\n').split('\n');
  while (lines.length && !lines[0].trim()) lines.shift();
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  const n = lines.length;
  if (n < 2 || n > 240) return null;

  const memo = new Map();
  const solve = (lineIdx, candStart, pickedCount) => {
    while (lineIdx < n && !lines[lineIdx].trim()) lineIdx++;
    if (lineIdx >= n) return pickedCount >= 2 ? [] : null;
    const stateKey = `${lineIdx}:${candStart}:${pickedCount > 0 ? 1 : 0}`;
    if (memo.has(stateKey)) return memo.get(stateKey);
    for (let endLine = lineIdx + 1; endLine <= n; endLine++) {
      const seg = lines.slice(lineIdx, endLine).join('\n').trim();
      if (!seg) continue;
      let rem = endLine;
      while (rem < n && !lines[rem].trim()) rem++;
      const isLastSeg = rem >= n;
      for (let ci = candStart; ci < candidates.length; ci++) {
        const cand = candidates[ci];
        const ok = isLastSeg && truncated
          ? sameReceiptMessage({ text: seg, truncated: true }, cand.text)
          : sameMessage(seg, cand.text);
        if (!ok) continue;
        const rest = solve(rem, ci + 1, pickedCount + 1);
        if (rest !== null) {
          const ans = [cand, ...rest];
          memo.set(stateKey, ans);
          return ans;
        }
      }
    }
    memo.set(stateKey, null);
    return null;
  };
  return solve(0, 0, 0);
}

function pendingMinAtMs(p) {
  const strictWindow = Boolean(p.timedOut || p.verifying || p.received || (p.queued && p.requeuedFromSend));
  return p.received
    ? Math.floor((Number(p.receiptAt) || Number(p.sentAt) || 0) / 1000) * 1000
    : strictWindow
      ? Math.floor((Number(p.sentAt) || 0) / 1000) * 1000 - 2000
      : (Number(p.sentAt) || 0) - 60000;
}

function bubbleMatchesCausalId(p, obj) {
  const id = p?.msgId ? String(p.msgId) : '';
  if (!id || !obj || typeof obj !== 'object') return false;
  if (obj.msg_id && String(obj.msg_id) === id) return true;
  if (Array.isArray(obj.msg_ids) && obj.msg_ids.some(x => String(x) === id)) return true;
  return false;
}

// True when `obj` explicitly belongs to a different `msg_id` / `msg_ids` than `p.msgId` (MSG-6).
function hasDifferentCausalId(p, obj) {
  const id = p?.msgId ? String(p.msgId) : '';
  if (!id || !obj || typeof obj !== 'object') return false;
  if (obj.msg_id) return String(obj.msg_id) !== id;
  if (Array.isArray(obj.msg_ids) && obj.msg_ids.length > 0) {
    return !obj.msg_ids.some(x => String(x) === id);
  }
  return false;
}

// Messages sent from the view show at once and give way to the same message in the log:
// 1) Causal `msg_id` / `msg_ids` match (zero clock assumptions across any timezone);
// 2) 1-to-1 text/attachment match within UTC-calibrated window (`eventTimeUtcMs`), skipping events carrying a different `msg_id`;
// 3) N-to-1 ordered line-partition match when an agent coalesced 2+ queued messages into one user turn.
export function settlePending(pending, events, { clockOffsetMs = 0 } = {}) {
  const src = Array.isArray(pending) ? pending : [];
  const evList = Array.isArray(events) ? events : [];
  if (!src.length || !evList.length) return pending;
  const settledSet = new Set();
  const usedEvents = new Set();

  // Pass 1: Causal `msg_id` / `msg_ids` match (a multi-id event can settle all constituent bubbles).
  for (let n = 0; n < evList.length; n++) {
    const e = evList[n];
    if (!e || e.type !== 'user') continue;
    if (!e.msg_id && !Array.isArray(e.msg_ids)) continue;
    let matchedAny = false;
    for (const p of src) {
      if (!p || settledSet.has(p)) continue;
      if ((p.failed && !p.timedOut) || (p.queued && !p.requeuedFromSend && !p.serverQueued)) continue;
      if (bubbleMatchesCausalId(p, e)) {
        settledSet.add(p);
        matchedAny = true;
        if (e.msg_id && !Array.isArray(e.msg_ids)) break;
      }
    }
    if (matchedAny) usedEvents.add(n);
  }

  // Pass 2: 1-to-1 text + UTC timestamp match (never match an event carrying a different `msg_id`, MSG-6).
  for (const p of src) {
    if (!p || settledSet.has(p)) continue;
    if ((p.failed && !p.timedOut) || (p.queued && !p.requeuedFromSend && !p.serverQueued)) continue;
    const minAt = pendingMinAtMs(p);
    const i = evList.findIndex((e, n) => !usedEvents.has(n) && e?.type === 'user' && !hasDifferentCausalId(p, e) &&
      sameMessage(e.text, p.text) && eventTimeUtcMs(e, clockOffsetMs) >= minAt);
    if (i < 0) continue;
    usedEvents.add(i);
    settledSet.add(p);
  }

  // Pass 3: N-to-1 coalesced multi-message match (when PM merged 2+ queued inputs with `\n`).
  const remainingCount = src.reduce((acc, p) => acc + (p && !settledSet.has(p) ? 1 : 0), 0);
  if (remainingCount >= 2) {
    for (let n = 0; n < evList.length; n++) {
      if (usedEvents.has(n)) continue;
      const e = evList[n];
      if (!e || e.type !== 'user' || !String(e.text || '').includes('\n')) continue;
      const evMs = eventTimeUtcMs(e, clockOffsetMs);
      if (!(evMs > 0)) continue;
      const eligible = src.filter(p =>
        p && !settledSet.has(p) &&
        !((p.failed && !p.timedOut) || (p.queued && !p.requeuedFromSend && !p.serverQueued)) &&
        !hasDifferentCausalId(p, e) &&
        evMs >= pendingMinAtMs(p),
      );
      if (eligible.length < 2) continue;
      const group = matchCoalescedBubbles(e.text, eligible);
      if (group && group.length >= 2) {
        usedEvents.add(n);
        for (const hit of group) settledSet.add(hit);
      }
    }
  }

  if (!settledSet.size) return pending;
  return src.filter(p => !settledSet.has(p));
}

// The opening of a PM reply as plain text: what the conversation shows while the reply is folded.
// {text, more}: `more` is false when the opening is the whole reply. The opening is the first
// paragraph up to where a list, table, heading, quote or code block starts (or the first line of
// one), without markdown marks. `limit` only guards against a reply that is one endless paragraph:
// past it the opening is cut at a sentence end.
const STRUCTURE = /^\s*([-*+]|\d{1,9}[.)]|#{1,6}|>)\s|^\s*\||^ *(`{3,}|~{3,})/;
const LEAD_CACHE = new Map();
export function lead(text, limit = 400) {
  const raw = String(text || '');
  const key = `${limit}\0${raw}`;
  return fifoCacheGetSet(LEAD_CACHE, key, () => {
    const body = raw.trim();
    const blocks = body.split(/\n[ \t]*\n/), lines = blocks[0].split('\n');
    const taken = [lines[0]];
    if (!STRUCTURE.test(lines[0])) for (const next of lines.slice(1)) { if (STRUCTURE.test(next)) break; taken.push(next); }
    const line = squash(taken.join(' ').replace(/^\s*(#{1,6}|>|[-*+]|\d{1,9}[.)])\s+/, '').replace(/^ *(`{3,}|~{3,}).*$/, '')
      .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\*\*|__|`/g, '').replace(/\|/g, ' '));
    let cut = line;
    if (line.length > limit) {
      const head = line.slice(0, limit);
      const stop = Math.max(...['。', '！', '？', '；', '. ', '! ', '? ', '; '].map(mark => head.lastIndexOf(mark)));
      cut = stop >= limit / 2 ? head.slice(0, stop + 1).trim() : `${head.trimEnd()}…`;
    }
    return { text: cut, more: cut !== line || taken.length < lines.length || blocks.length > 1 };
  }, 512);
}

// Task numbers (`#42`) assigned per project; absent on review threads and older remote peers.
// pm-project and pm-dash keep identical copies of `taskNumber` and `formatTaskNumber`.
export function taskNumber(value) {
  const raw = value && typeof value === 'object' ? (value.number ?? value.num) : value;
  return Number.isInteger(raw) && raw > 0 ? raw : null;
}

export function formatTaskNumber(value) {
  const num = taskNumber(value);
  return num ? `#${num}` : '';
}

// A reply can name a thread as a link, `[name](thread:<task id>)`. The task id of such a link's
// address, or '' for any other address and for an id that could not be a ledger file's name.
export function threadLink(url) {
  const found = /^thread:(?:\/\/)?([^?\s]+)$/i.exec(String(url || '').trim());
  if (!found) return '';
  let id = found[1].replace(/\/+$/, '');
  try { id = decodeURIComponent(id); } catch (_) { return ''; }
  if (/^(?:[a-z0-9][a-z0-9._-]*#)?#?[1-9][0-9]*(?:-review)?$/i.test(id)) return id;
  // A task id is its project's folder name and a slug: letters and digits of any script, spaces, . _ -
  return /^[\p{L}\p{N}][\p{L}\p{N} ._-]*$/u.test(id) && !id.includes('..') ? id : '';
}

export function resolveThreadRef(tasks, ref, taskNumbers = null, { retiredParts = [], events = [] } = {}) {
  const raw = String(ref || '').trim();
  if (!raw) return '';
  const list = Array.isArray(tasks) ? tasks : [];
  const direct = threadFor(list, raw);
  if (list.some(t => t?.id === direct)) return direct;
  const m = /^(?:([a-z0-9][a-z0-9._-]*)#)?#?([1-9][0-9]*)(-review)?$/i.exec(raw);
  if (!m) return direct;
  const proj = (m[1] || '').toLowerCase();
  const num = Number(m[2]);
  const isRev = Boolean(m[3]);
  const matchesProj = t => !proj || String(t.project || '').toLowerCase() === proj;
  const hit = list.find(t => taskNumber(t) === num && matchesProj(t));
  if (hit) return hit.id;
  if (proj) return direct;
  const partsList = Array.isArray(retiredParts) ? retiredParts : [];
  const retiredHit = partsList.find(t => t?.id && taskNumber(t) === num);
  if (retiredHit) return isRev ? threadFor(list, retiredHit.id) : retiredHit.id;
  if (taskNumbers && typeof taskNumbers === 'object') {
    const seenIds = new Set();
    for (const ev of Array.isArray(events) ? events : []) {
      if (ev?.task) seenIds.add(String(ev.task));
    }
    for (const tid of seenIds) {
      if (taskNumber(taskNumbers[tid]) === num) return isRev ? threadFor(list, tid) : tid;
    }
    const globalHits = Object.entries(taskNumbers).filter(([, n]) => taskNumber(n) === num).map(([tid]) => tid);
    if (globalHits.length === 1) return isRev ? threadFor(list, globalHits[0]) : globalHits[0];
  }
  return direct;
}

export function decorateThreadLinks(markdown, tasks = [], taskNumbers = null, opts = undefined) {
  const src = String(markdown || '');
  if (!src.includes('](thread:')) return src;
  const numById = new Map();
  if (taskNumbers && typeof taskNumbers === 'object') {
    for (const [id, n] of Object.entries(taskNumbers)) {
      const num = taskNumber(n);
      if (num) numById.set(id, num);
    }
  }
  for (const t of Array.isArray(opts?.retiredParts) ? opts.retiredParts : []) {
    if (!t?.id) continue;
    const num = taskNumber(t);
    if (num) numById.set(t.id, num);
  }
  for (const t of Array.isArray(tasks) ? tasks : []) {
    if (!t?.id) continue;
    const num = taskNumber(t);
    if (num) numById.set(t.id, num);
  }
  const rewriteOutsideCode = chunk => chunk.replace(/\[([^\]\r\n]+)\]\((thread:[^)\s]+)\)/gi, (full, label, url) => {
    const cleanLabel = String(label || '').trim();
    if (!cleanLabel) return full;
    const target = threadLink(url);
    if (!target) return full;
    const resolved = resolveThreadRef(tasks, target, taskNumbers, opts);
    const num = numById.get(resolved) || numById.get(target)
      || (() => { const m = /^(?:[a-z0-9][a-z0-9._-]*#)?#?([1-9][0-9]*)(?:-review)?$/i.exec(target); return m ? Number(m[1]) : 0; })();
    if (!num) return full;
    const bare = cleanLabel.replace(/^@/, '').trim();
    if (new RegExp(`^#?${num}(?![0-9])`).test(bare)) return full;
    return `[#${num} ${label}](${url})`;
  });
  let out = '', inFence = false, fence = '';
  for (const line of src.split('\n')) {
    const fMatch = /^\s*(`{3,}|~{3,})/.exec(line);
    if (fMatch) {
      if (!inFence) { inFence = true; fence = fMatch[1][0]; }
      else if (fMatch[1][0] === fence) { inFence = false; fence = ''; }
      out += (out ? '\n' : '') + line;
      continue;
    }
    if (inFence) { out += (out ? '\n' : '') + line; continue; }
    // Preserve inline backtick code spans untouched while decorating prose links.
    const parts = line.split(/(`[^`]*`)/g);
    const rewritten = parts.map((p, i) => (i % 2 === 1 ? p : rewriteOutsideCode(p))).join('');
    out += (out ? '\n' : '') + rewritten;
  }
  return out;
}

// Drafts: what is typed into a message box and not sent yet. The view keeps them in localStorage
// as they change, so a reload of the mod (any save of its files) or a restart of the app loses
// nothing. One per box: the project's ('pm:<PM name>') and each thread's ('thread:<task id>').
// Stored as {key: {text, at, files?}} with `at` in ms; only the newest DRAFT_LIMIT are kept.
// files: the box's attachments, absolute paths (see withFiles); a draft can be files alone.
export const DRAFT_LIMIT = 40;
export const draftKey = (kind, id) => (id ? `${kind}:${id}` : '');
export const draftText = (drafts, key) => (key && drafts?.[key]?.text) || '';
export const draftFiles = (drafts, key) => (key && Array.isArray(drafts?.[key]?.files) ? drafts[key].files : []);
export function validInputTokens(text, tokens) {
  const str = String(text ?? '');
  if (!Array.isArray(tokens) || !tokens.length || !str) return [];
  const clean = [];
  for (const span of tokens) {
    if (!span || typeof span !== 'object') continue;
    const start = span.range?.start, end = span.range?.end;
    const tok = span.token;
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || start >= end || end > str.length) continue;
    if (!tok || typeof tok !== 'object' || typeof tok.id !== 'string' || !tok.id || typeof tok.text !== 'string' || !tok.text) continue;
    if (str.slice(start, end) !== tok.text) continue;
    const label = typeof tok.label === 'string' && tok.label ? tok.label : undefined;
    clean.push({ range: { start, end }, token: label !== undefined ? { id: tok.id, text: tok.text, label } : { id: tok.id, text: tok.text } });
  }
  clean.sort((a, b) => a.range.start - b.range.start || a.range.end - b.range.end);
  const out = [];
  let prevEnd = 0;
  for (const span of clean) {
    if (span.range.start < prevEnd) continue;
    prevEnd = span.range.end;
    out.push(span);
  }
  return out;
}
export const draftTokens = (drafts, key) => (key ? validInputTokens(draftText(drafts, key), drafts?.[key]?.tokens) : []);
const sameTokens = (a, b) => a.length === b.length && a.every((s, i) =>
  s.range.start === b[i].range.start && s.range.end === b[i].range.end &&
  s.token.id === b[i].token.id && s.token.text === b[i].token.text && s.token.label === b[i].token.label);
export const QUOTE_LIMIT = 8;
export const QUOTE_SCOPES = ['message', 'paragraph', 'selection'];

// Unified range anchor for both paragraph quotes and arbitrary character selections (future #1335).
export function normalizeQuoteRange(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const start = Number(raw.start);
  const end = Number(raw.end);
  const hasOffsets = Number.isInteger(start) && start >= 0 && Number.isInteger(end) && end >= start;
  const paragraph = Number.isInteger(raw.paragraph) && raw.paragraph >= 0 ? raw.paragraph : undefined;
  const kind = typeof raw.kind === 'string' && raw.kind.trim() ? raw.kind.trim() : undefined;
  if (!hasOffsets && paragraph === undefined) return null;
  return {
    ...(hasOffsets ? { start, end } : {}),
    ...(paragraph !== undefined ? { paragraph } : {}),
    ...(kind ? { kind } : {}),
  };
}

export function quoteScope(q) {
  if (!q || typeof q !== 'object') return 'message';
  if (q.scope === 'selection' || q.exact) return 'selection';
  if (q.scope === 'paragraph') return 'paragraph';
  return 'message';
}

export function quoteScopeLabel(lang, q) {
  const scope = quoteScope(q);
  if (scope === 'selection') return word(lang, 'quoteScopeSelection');
  if (scope === 'paragraph') return word(lang, 'quoteScopeParagraph', q?.range?.paragraph);
  return word(lang, 'quoteScopeMessage');
}

export function quoteScopeTip(lang, q) {
  const scope = quoteScope(q);
  if (scope === 'selection') return word(lang, 'quoteScopeSelection');
  if (scope === 'paragraph') return word(lang, 'quoteScopeParagraphTip', q?.range?.paragraph);
  return word(lang, 'quoteScopeMessage');
}

const sameQuoteRange = (a, b) => {
  if (!a && !b) return true;
  if (!a || !b) return false;
  return a.start === b.start && a.end === b.end && a.paragraph === b.paragraph && (a.kind || '') === (b.kind || '');
};

export function normalizeQuote(q) {
  if (!q || typeof q !== 'object') return null;
  const text = String(q.text ?? '').replace(/\r\n?/g, '\n').trim();
  if (!text) return null;
  const targetKey = String(q.targetKey ?? '').trim();
  const kind = String(q.kind || 'pm');
  const author = String(q.author || '');
  const at = String(q.at || '');
  const time = String(q.time || '');
  const id = String(q.id || `${targetKey || 'msg'}#${text.slice(0, 24)}`);
  const explicitScope = QUOTE_SCOPES.includes(q.scope) ? q.scope : '';
  const isSelection = explicitScope === 'selection' || Boolean(q.exact);
  const scope = isSelection ? 'selection' : explicitScope;
  const range = normalizeQuoteRange(q.range);
  return {
    id,
    targetKey,
    kind,
    author,
    at,
    time,
    text,
    ...(scope ? { scope } : {}),
    ...(isSelection ? { exact: true } : {}),
    ...(range ? { range } : {}),
  };
}
function normalizeQuotes(list) {
  const out = [];
  const seen = new Set();
  for (const item of Array.isArray(list) ? list : []) {
    const q = normalizeQuote(item);
    if (!q) continue;
    const rangeTag = q.range && Number.isInteger(q.range.start) ? `${q.range.start}:${q.range.end}` : '';
    const dedupeKey = `${q.targetKey}\0${quoteScope(q)}\0${rangeTag}\0${q.text}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    out.push(q);
    if (out.length >= QUOTE_LIMIT) break;
  }
  return out;
}
export const draftQuotes = (drafts, key) => (key ? normalizeQuotes(drafts?.[key]?.quotes) : []);
const sameQuotes = (a, b) => a.length === b.length && a.every((q, i) =>
  q.id === b[i].id && q.targetKey === b[i].targetKey && q.kind === b[i].kind &&
  q.author === b[i].author && q.at === b[i].at && q.time === b[i].time &&
  q.text === b[i].text && quoteScope(q) === quoteScope(b[i]) && sameQuoteRange(q.range, b[i].range));
// The stored JSON as drafts; text that is not such an object reads as none.
export function readDrafts(text) {
  try {
    const raw = JSON.parse(text);
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
    return Object.fromEntries(Object.entries(raw).flatMap(([key, draft]) => {
      if (!draft || typeof draft !== 'object' || (draft.text !== undefined && typeof draft.text !== 'string')) return [];
      const words = draft.text?.trim() ? draft.text : '', files = withFiles([], draft.files);
      const tokens = validInputTokens(words, draft.tokens);
      const quotes = normalizeQuotes(draft.quotes);
      if (!words && !files.length && !quotes.length) return [];
      return [[key, { text: words, at: Number(draft.at) || 0, ...(files.length ? { files } : {}), ...(tokens.length ? { tokens } : {}), ...(quotes.length ? { quotes } : {}) }]];
    }));
  } catch (_) { return {}; }
}
// The drafts with the box `key` holding `text`, the attachments `files`, optional inline `tokens`,
// and optional `quotes` (both unchanged when omitted); a box without words, files, or quotes has no draft.
// Returns `drafts` itself when nothing changes, so the caller writes only what is new.
export function keepDraft(drafts, key, text, now, files = draftFiles(drafts, key), tokens = undefined, quotes = undefined) {
  text = String(text ?? '');
  if (!text.trim()) text = '';
  files = withFiles([], files);
  const prevTokens = draftTokens(drafts, key);
  const nextTokens = tokens === undefined ? validInputTokens(text, prevTokens) : validInputTokens(text, tokens);
  const prevQuotes = draftQuotes(drafts, key);
  const nextQuotes = quotes === undefined ? prevQuotes : normalizeQuotes(quotes);
  if (!key || (draftText(drafts, key) === text && sameFiles(draftFiles(drafts, key), files) &&
      sameTokens(prevTokens, nextTokens) && sameQuotes(prevQuotes, nextQuotes))) {
    return drafts;
  }
  const { [key]: _old, ...rest } = drafts;
  if (!text && !files.length && !nextQuotes.length) return rest;
  const kept = Object.entries({
    ...rest,
    [key]: {
      text,
      at: now,
      ...(files.length ? { files } : {}),
      ...(nextTokens.length ? { tokens: nextTokens } : {}),
      ...(nextQuotes.length ? { quotes: nextQuotes } : {}),
    },
  });
  return Object.fromEntries(kept.length > DRAFT_LIMIT ? kept.sort((a, b) => b[1].at - a[1].at).slice(0, DRAFT_LIMIT) : kept);
}

// Attachments. A file goes with a message as its absolute path: dropped on a message box, picked
// with the paperclip, or a pasted screenshot saved in the project's attachments folder. The message
// carries them as its last lines, one path a line, after a blank line (see messageText); the agent
// that reads it opens the files, an image as an image.
// A path is absolute and names something below a folder: "/clear" or "/model opus" is a command.
// A name may start or end with spaces, so a path is never trimmed.
const PATH = /^\/[^/\s]+\/[^\n]*[^/\n]$/;
const isPath = path => typeof path === 'string' && PATH.test(path);
const sameFiles = (a, b) => a.length === b.length && a.every((path, i) => path === b[i]);
// `files` with `added` after them: each path once, in the order it first came; what is not a path is left out.
export function withFiles(files, added = []) {
  const out = [];
  for (const path of [...(Array.isArray(files) ? files : []), ...(Array.isArray(added) ? added : [])]) {
    if (isPath(path) && !out.includes(path)) out.push(path);
  }
  return out;
}
export const withoutFile = (files, path) => (files || []).filter(f => f !== path);
// What of `paths` (dropped or picked) cannot attach: not a file's absolute path.
export const notFiles = paths => (Array.isArray(paths) ? paths : []).filter(path => !isPath(path));
// The picker's output as paths: one a line, kept exactly as written (a name may end in a space).
export const pickedPaths = out => String(out ?? '').split('\n').filter(line => line !== '');
// The drafts with `paths` added to the box `key`'s files as they are stored, its words as stored:
// the box may show less than its draft (words on their way are still the draft until they went out).
export function addFiles(drafts, key, paths, now) {
  return keepDraft(drafts, key, draftText(drafts, key), now, withFiles(draftFiles(drafts, key), paths));
}
// The line before the paths of a message that is only files, in either language: a message that
// starts with "/" would be read as a command by the agent's prompt.
const FILES_ONLY = [STRINGS.en.attachments, STRINGS.zh.attachments];
// What a box sends: its words, then its files after a blank line; files alone after `label`.
export function messageText(text, files = [], label = FILES_ONLY[0]) {
  const words = String(text ?? '').trim(), paths = withFiles([], files);
  if (!paths.length) return words;
  return words ? `${words}\n\n${paths.join('\n')}` : `${label}\n${paths.join('\n')}`;
}
// A message as {text, files}: the paths at its end come off as its files (all of it may be paths,
// or the files-only label and paths). Paths that run on from the words without a blank line are words.
export function splitMessage(message) {
  const whole = String(message ?? '').replace(/^\s*\n|\n\s*$/g, '');
  const lines = whole.split('\n');
  let at = lines.length;
  while (at > 0 && isPath(lines[at - 1])) at--;
  const files = () => withFiles([], lines.slice(at));
  if (at === lines.length) return { text: whole.trim(), files: [] };
  if (at === 0 || (at === 1 && FILES_ONLY.includes(lines[0].trim()))) return { text: '', files: files() };
  if (lines[at - 1].trim()) return { text: whole.trim(), files: [] };
  return { text: lines.slice(0, at).join('\n').trim(), files: files() };
}
// Claude Code may record an image sent with a message as an "[Image #3]" mark in place of its path,
// before the words ("[Image #3]看这里") or on a line of its own. How many a message has, and the
// message without them.
const IMAGE_MARK = /\[Image #\d+\][ \t]*/g;
const imageMarks = message => (String(message ?? '').match(IMAGE_MARK) || []).length;
const withoutMarks = message => String(message ?? '').replace(IMAGE_MARK, '');
// A message's words, for telling which sent message a logged one is: its last lines that are paths
// are not words, nor are image marks.
function wordsOf(message) {
  const lines = withoutMarks(message).split('\n');
  while (lines.length && (!lines[lines.length - 1].trim() || isPath(lines[lines.length - 1]))) lines.pop();
  const words = squash(lines.join('\n'));
  return FILES_ONLY.includes(words) ? '' : words;
}
// Whether a logged message is the one a pending bubble sent. One with files may be logged with its
// images as marks, so its words decide.
export const sameMessage = (logged, sent) => squash(logged) === squash(sent) ||
  (splitMessage(sent).files.length > 0 && wordsOf(logged) === wordsOf(sent));
// A file's name, for its card.
export const fileName = path => String(path || '').split('/').filter(Boolean).pop() || String(path || '');
const IMAGE = /\.(png|jpe?g|gif|webp|heic|tiff?|bmp|svg)$/i;
export const isImage = path => IMAGE.test(String(path || ''));
// A pasted screenshot's file in the attachments folder: paste-20261114-093012.png, -2 for a second one that second.
export function pasteName(date, n = 1) {
  return `paste-${timeStamp(date)}${n > 1 ? `-${n}` : ''}.png`;
}
// 20261114-093012: a moment in a file name, this computer's time.
function timeStamp(date) {
  const pad = (v, w = 2) => String(v).padStart(w, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}
// The project's attachments folder, beside its conversation log: <ledger>/projects/<project>/attachments.
export function attachmentsDir(pm) {
  const log = String(pm?.conversation || '');
  return log.includes('/') ? `${log.slice(0, log.lastIndexOf('/'))}/attachments` : '';
}
// Where a screenshot pasted into a project is kept on this computer: the project's attachments folder,
// or for a project on another machine (whose log is there), <ledger home here>/attachments/<machine>/<name>
// until its message is sent (see uploadSteps). '' when there is nowhere yet.
export function pasteDir(pm, { machine = '', name = '', home = '' } = {}) {
  if (!machine) return attachmentsDir(pm);
  return home && name ? `${home}/attachments/${machine}/${name}` : '';
}
// When a pasted screenshot was saved, from its name (see pasteName): [ms, n], or null for another file.
const PASTE = /(?:^|\/)paste-(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)(?:-(\d+))?\.png$/;
function pasteTime(path) {
  const m = PASTE.exec(String(path || ''));
  if (!m) return null;
  const [y, mo, d, h, mi, s] = m.slice(1, 7).map(Number);
  return [new Date(y, mo - 1, d, h, mi, s).getTime(), Number(m[7] || 1)];
}
// The pasted screenshots among `names` (an `ls` of the attachments folder `dir`), as paths.
export const pastesIn = (dir, names) => (dir ? String(names ?? '').split('\n').filter(n => pasteTime(n)).map(n => `${dir}/${n}`) : []);
// A logged message with image marks and no paths shows the screenshots pasted for it: the newest of
// `pastes` saved since the message before it with marks (at most PASTE_WINDOW before it), one per
// mark, that no other message carries. Without such screenshots the marks just do not show.
const PASTE_WINDOW = 30 * 60000;
function pastedFiles(events, pastes, carried) {
  if (!Array.isArray(pastes) || !pastes.length) return new Map();
  const pool = pastes.map(path => ({ path, when: pasteTime(path) }))
    .filter(p => p.when && !carried.has(p.path)).sort((a, b) => a.when[0] - b.when[0] || a.when[1] - b.when[1]);
  if (!pool.length) return new Map();
  const out = new Map();
  let since = 0;
  for (const e of events) {
    if (e.type !== 'user') continue;
    const marks = imageMarks(e.text);
    if (!marks) continue;
    const at = eventTime(e.at), from = Math.max(since, at - PASTE_WINDOW);
    since = at;
    if (splitMessage(withoutMarks(e.text)).files.length) continue;
    const fits = pool.filter(p => !p.taken && p.when[0] > from && p.when[0] <= at).slice(-marks);
    for (const p of fits) p.taken = true;
    if (fits.length) out.set(e, fits.map(p => p.path));
  }
  return out;
}
// A box's draft after a send of `sent` ({text, files}) came back, or null when it stays as stored.
// Gone once sent: the words if they still are the box's draft, and the files that went. Not sent:
// the draft is what went out again when the box has been left empty, else what was typed since.
export function afterSend(stored, sent, ok) {
  const text = stored?.text || '', files = stored?.files || [], quotes = normalizeQuotes(stored?.quotes);
  const sentQuotes = normalizeQuotes(sent?.quotes);
  if (!ok) {
    return text.trim() || files.length || quotes.length
      ? null
      : { text: sent.text, files: sent.files || [], ...(sentQuotes.length ? { quotes: sentQuotes } : {}) };
  }
  const sentIds = new Set(sentQuotes.map(q => q.id));
  const sentKeys = new Set(sentQuotes.map(q => `${q.targetKey}\0${q.text}`));
  const nextQuotes = quotes.filter(q => !sentIds.has(q.id) && !sentKeys.has(`${q.targetKey}\0${q.text}`));
  const next = {
    text: text.trim() === sent.text ? '' : text,
    files: files.filter(f => !(sent.files || []).includes(f)),
    ...(quotes.length || sentQuotes.length ? { quotes: nextQuotes } : {}),
  };
  return next.text === text && next.files.length === files.length && nextQuotes.length === quotes.length ? null : next;
}
// The picker, shown by osascript: the chosen files' paths one a line; nothing when it is cancelled.
export const CHOOSE_FILES = 'set picked to choose file with multiple selections allowed\n' +
  'set out to ""\nrepeat with f in picked\nset out to out & POSIX path of f & linefeed\nend repeat\nreturn out';
// The clipboard's image saved as a PNG at argv's path (item 1) in argv's folder (item 2), by
// osascript: prints "saved", or "none" when the clipboard holds no image, without making the folder.
// A TIFF image, as some apps copy, is converted with sips; its temporary file goes either way.
export const SAVE_CLIPBOARD_IMAGE = [
  'on run argv',
  'set target to item 1 of argv',
  'set fmt to "png"',
  'try',
  'set img to the clipboard as «class PNGf»',
  'on error',
  'try',
  'set img to the clipboard as TIFF picture',
  'set fmt to "tiff"',
  'on error',
  'return "none"',
  'end try',
  'end try',
  'do shell script "mkdir -p " & quoted form of (item 2 of argv)',
  'set outPath to target',
  'if fmt is "tiff" then set outPath to target & ".tiff"',
  'set f to open for access POSIX file outPath with write permission',
  'try',
  'set eof f to 0',
  'write img to f',
  'close access f',
  'on error e',
  'close access f',
  'do shell script "rm -f " & quoted form of outPath',
  'error e',
  'end try',
  'if fmt is "tiff" then do shell script "s=0; sips -s format png " & quoted form of outPath & " --out " & quoted form of target & " >/dev/null || s=$?; rm -f " & quoted form of outPath & "; exit $s"',
  'return "saved"',
  'end run',
].join('\n');

// What a quick answer sends as the user's turn.
export function answerText(title, option) {
  return `【${title}】${option}`;
}

// What a blocked task without a question card in the conversation is asked under (threadQuestion):
// a quick answer from its thread's detail carries it, and timeline() marks words that answer it so.
const ASK = 'ask:';
export const askKey = id => `${ASK}${id}`;

// The timeline, oldest first. Kinds:
//   day       a date divider
//   user      the user's words (right bubble); files: the paths it ended with (see splitMessage);
//             pending/failed for an unconfirmed one; `answers`: the
//             key of the question it answers, when it says so: a quick answer, or words that start
//             with the question's 【title】 (absent otherwise: other words name no question)
//   pm        the coordinator's reply (markdown): {text, lead, long, by}; a long one folds to its lead;
//             by: the session that spoke ('' in logs from before replies recorded it)
//   threads   adjacent thread rows: {rows: [{task, title, status, latest, waiting, tone, cleanup, closed, answered}]};
//             answered (only when true): blocked, and the user answered it (see answeredTasks);
//             a task that is abandoned now has no row and no `about`
//   about     a later ledger entry of a thread that already showed: {task, title, by (who wrote
//             it)}. turns() keeps the ones the coordinator wrote, to name what its reply is about.
//   question  the event that blocked a task, or asked again (asksAgain): {task, title, text, options, notes, recommended, open,
//             chosen}. notes: a line of explanation per option ('' for none); recommended: the first
//             option is the coordinator's pick; chosen: the option the user picked (its place in
//             options, from a quick answer in the log or one still being sent), else -1; answered
//             (only when true): open, and the user answered it (see answeredTasks). A task that
//             enters the log blocked (the coordinator asking) is this alone; it gets its thread row
//             where it first becomes work, if it ever does.
//   decision  a recorded decision
//   typing    the coordinator is working
// tasks: `pm.py state` tasks; a task's row shows what it is now, falling back to
// its newest event here once the ledger no longer lists it. `agent` events are not shown.
// A task blocked in the ledger that the events never show asked (its question is older than the log,
// or than the events shown) has no card; words said after the ledger asked (`asked_at`, see pm.py's
// asked_at) that start with its 【title】 still answer it: the user item then `answers` askKey(task)
// (see threadQuestion, where such a task is asked). A task's first event asks unless the ledger asked
// before it: a note on a question asked earlier (`pm.py log`) is no new question. pm: the project's
// name: only its tasks count so (tasks of other projects can share a title). The same rule as pm.py's
// answered_tasks.
export function timeline(events, tasks = [], { pending = [], typing = false, today = '', pastes = [], pm = '', pmPane = '', taskNumbers = null, clockOffsetMs = 0, inbox = [] } = {}) {
  const inboxRows = inboxByMsgId(inbox);
  const byId = new Map((tasks || []).map(t => [t.id, t]));
  const numOf = (id, ev) => taskNumber(byId.get(id)) || taskNumber(ev) || taskNumber(taskNumbers?.[id]);
  const newest = new Map();
  for (const e of events) if (e.type === 'thread' && e.task) newest.set(e.task, e);
  const nowCache = new Map();
  const now = id => {
    let cached = nowCache.get(id);
    if (cached !== undefined) return cached;
    const t = byId.get(id), last = newest.get(id) || {};
    const num = numOf(id, last);
    const status = t?.status || last.status || '', cleanup = Boolean(t?.cleanup), offline = disconnected({ ...t, status });
    const termClosed = isClosedTask({ ...t, status, offline: Boolean(t?.offline) }) ? t.closed : null;
    const answered = !cleanup && status === 'blocked' && Boolean(t?.answered);
    cached = { ...(num ? { number: num } : {}), status, cleanup, ...(offline ? { offline } : {}), ...(termClosed ? { termClosed } : {}), ...(answered ? { answered } : {}), title: t?.title || last.title || id,
      latest: cleanTaskLog(t ? t.latest : last.text).text, waiting: !cleanup && WAITING.includes(status) && !answered,
      tone: tone(status, cleanup, offline, answered), closed: CLOSED.includes(status) };
    nowCache.set(id, cached);
    return cached;
  };
  const items = [], shown = new Set(), asked = new Set(), before = new Map(), keys = new Map(), questions = [], questionMeta = new Map(), incidentsByKey = new Map(), incidentsById = new Map();
  const hasPastes = Array.isArray(pastes) && pastes.length > 0;
  const carried = hasPastes
    ? new Set([...events.filter(e => e.type === 'user'), ...(pending || [])]
      .flatMap(e => splitMessage(withoutMarks(e.text)).files))
    : null;
  const pasted = hasPastes ? pastedFiles(events, pastes, carried) : new Map();
  // A thread event that asks the user (see above); was: the task's status before it, undefined at its first.
  const minute = at => String(at || '').slice(0, 16), askedAt = id => String(byId.get(id)?.asked_at || '');
  const asking = (e, was) => e.status === 'blocked' && (was === undefined
    ? asksAgain(e) || !(askedAt(e.task) && minute(e.at) > askedAt(e.task)) : was !== 'blocked' || asksAgain(e));
  const seen = new Map(), shownAsking = new Set();
  for (const e of events) {
    if (e.type !== 'thread' || !e.task) continue;
    if (asking(e, seen.get(e.task))) shownAsking.add(e.task);
    seen.set(e.task, e.status);
  }
  // The blocked tasks without a card (see above): {key, title, at: when the ledger asked}.
  const cardless = (tasks || []).filter(t => t?.id && t.status === 'blocked' && !t.cleanup && !shownAsking.has(t.id)
    && (!pm || t.pm === pm)).map(t => ({ key: askKey(t.id), title: now(t.id).title, at: askedAt(t.id) }));
  // The newest question so far whose 【title】 the user's words start with; then the ones without a card,
  // asked before the words were said (at: when they were; none for words on their way).
  const addressed = (said, at = '') => {
    for (let qi = questions.length - 1; qi >= 0; qi--) {
      const q = questions[qi];
      if (q.title && said.startsWith(squash(answerText(q.title, '')))) return q;
    }
    const minAt = at ? minute(at) : '';
    for (let ci = cardless.length - 1; ci >= 0; ci--) {
      const q = cardless[ci];
      if ((!minAt || !q.at || minAt >= q.at) && q.title && said.startsWith(squash(answerText(q.title, '')))) return q;
    }
    return undefined;
  };
  let day = '';
  const localStamp = ms => {
    const d = new Date(ms);
    if (!Number.isFinite(d.getTime())) return '';
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  };
  const ensureDay = date => {
    if (date && date !== day) {
      day = date;
      items.push({ kind: 'day', key: `day:${date}`, date, today: date === today });
    }
  };
  const key = (e, kind) => {
    const base = `${kind}:${e.at || ''}:${e.task || ''}`;
    const n = keys.get(base) || 0;
    keys.set(base, n + 1);
    return n ? `${base}:${n}` : base;
  };
  const eventDay = e => {
    const explicitMs = Number(e?.at_ms);
    if (Number.isFinite(explicitMs) && explicitMs > 0) {
      const ls = localStamp(explicitMs);
      if (ls) return ls.slice(0, 10);
    }
    if (clockOffsetMs && e?.at) {
      const utcMs = eventTimeUtcMs(e, clockOffsetMs);
      if (utcMs > 0) {
        const ls = localStamp(utcMs);
        if (ls) return ls.slice(0, 10);
      }
    }
    return String(e?.at || '').slice(0, 10);
  };
  const push = (e, item) => {
    ensureDay(eventDay(e));
    const pushed = { at: e.at || '', ...(Number(e.at_ms) > 0 ? { at_ms: Number(e.at_ms) } : {}), ...item };
    items.push(pushed);
    return pushed;
  };
  const pendingList = Array.isArray(pending) ? pending : [];
  const placedPending = new Set();
  const pendingAnchorMs = p => {
    if (!p || p.queued) return 0;
    const ms = Number(p.receiptAt) || Number(p.deliveredAt) || Number(p.sentAt) || 0;
    return Number.isFinite(ms) && ms > 0 ? ms : 0;
  };
  const pushPendingItem = p => {
    placedPending.add(p);
    const answers = p.question || addressed(squash(p.text))?.key;
    const { text, files } = splitMessage(p.text);
    items.push({ kind: 'user', key: `pending:${p.id}`, text, pending: !p.failed && !p.queued && !p.received,
      ...(p.queued ? { queued: true } : {}), ...(p.queuedReason ? { queuedReason: String(p.queuedReason) } : {}),
      ...(p.received ? { received: true } : {}), failed: p.failed || '',
      // unconfirmed: it may well have arrived (see unconfirmedSend), so no "not sent" before it;
      // checking: a resend checking the log first (reconcilePendingSends).
      ...(p.failed && p.timedOut ? { unconfirmed: true } : {}), ...(p.verifying && !p.failed ? { checking: true } : {}),
      ...(files.length ? { files } : {}), ...(answers ? { answers } : {}), ...(p.failed && p.upload ? { upload: true } : {}) });
    // A quick answer on its way already shows as the picked option.
    const asking = p.question && !p.failed ? questions.find(q => q.key === p.question) : null;
    if (asking && asking.chosen < 0) asking.chosen = asking.options.findIndex(o => squash(answerText(asking.title, o)) === squash(p.text));
  };
  // Precompute local cutoff timestamps once per anchored pending bubble so the hot events loop stays
  // O(1) with zero Date parsing across 200+ events during GPUI's 50ms render budget.
  const anchoredPending = [];
  for (const p of pendingList) {
    const anchor = pendingAnchorMs(p);
    if (anchor > 0) {
      const cutoffMs = anchor + 5000;
      const cutoffAt = localStamp(cutoffMs);
      anchoredPending.push({ p, cutoffMs, cutoffAt, date: cutoffAt.slice(0, 10) });
    }
  }
  if (anchoredPending.length > 1) anchoredPending.sort((a, b) => a.cutoffMs - b.cutoffMs);
  let anchoredIdx = 0;
  const flushPendingBefore = ev => {
    if (anchoredIdx >= anchoredPending.length) return;
    const rawAt = typeof ev === 'string' ? ev : ev?.at;
    const hasUtc = Boolean(ev && typeof ev === 'object' && (Number(ev.at_ms) > 0 || clockOffsetMs));
    const stamp = String(rawAt || '');
    if (!stamp && !hasUtc) return;
    const standard = !hasUtc && /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(stamp);
    let evMs = -1;
    while (anchoredIdx < anchoredPending.length) {
      const cur = anchoredPending[anchoredIdx];
      // Sent or failed bubbles stay anchored at when they were sent instead of sliding after
      // messages logged >5s later; UTC ms avoids 13-hour cross-timezone mis-ordering.
      const after = standard && cur.cutoffAt
        ? stamp > cur.cutoffAt
        : ((evMs < 0 ? (evMs = hasUtc ? eventTimeUtcMs(ev, clockOffsetMs) : eventTime(stamp)) : evMs) > cur.cutoffMs);
      if (!after) break;
      anchoredIdx++;
      ensureDay(cur.date);
      pushPendingItem(cur.p);
    }
  };
  for (let eventIndex = 0; eventIndex < events.length; eventIndex++) {
    const e = events[eventIndex];
    if (e.type === 'user' || e.type === 'pm') {
      if (!squash(e.text)) continue;
      if (anchoredIdx < anchoredPending.length) flushPendingBefore(e);
      // A message that was only images keeps its marks when no screenshot is found for it.
      const bare = e.type === 'user' ? withoutMarks(e.text) : e.text;
      const said = pasted.has(e) || wordsOf(bare) || splitMessage(bare).files.length ? bare : e.text;
      const item = { kind: e.type, key: key(e, e.type), text: String(said).trim() };
      if (e.type === 'user') {
        // A quick answer in the log marks the option it picked, on the newest question that offered it.
        const words = squash(said);
        let hit = null, hitIdx = -1;
        for (let qi = questions.length - 1; qi >= 0; qi--) {
          const q = questions[qi];
          if (q.chosen >= 0) continue;
          const idx = q.options.findIndex(o => squash(answerText(q.title, o)) === words);
          if (idx >= 0) { hit = q; hitIdx = idx; break; }
        }
        if (hit) { hit.chosen = hitIdx; item.answers = hit.key; }
        else { const named = addressed(words, e.at); if (named) item.answers = named.key; }
        // The files it carried show as cards in its bubble, not as lines of paths; its image marks
        // as the screenshots pasted for it.
        const { text, files } = splitMessage(said);
        if (files.length) { item.text = text; item.files = files; }
        else if (pasted.has(e)) { item.text = FILES_ONLY.includes(text) ? '' : text; item.files = pasted.get(e); }
        // Where it is in the PM's mailbox (§3.9): logged at accept, so the log line alone does not say it was sent.
        const row = e.msg_id ? inboxRows.get(String(e.msg_id)) : undefined;
        const rowState = String(row?.state || '');
        if (row && rowState && !['answered', 'superseded', 'expired'].includes(rowState)) {
          item.delivery = {
            state: rowState, hold_reason: String(row.hold_reason || ''), last_error: String(row.last_error || ''),
            sending: Boolean(row.sending), attempts: Number(row.attempts) || 0,
          };
        }
      }
      if (e.type === 'pm') {
        const opening = lead(item.text);
        item.lead = opening.text; item.long = opening.more; item.by = String(e.by || '');
      }
      push(e, item);
    } else if (e.type === 'decision') {
      const decText = squash(e.text);
      if (decText) {
        if (anchoredIdx < anchoredPending.length) flushPendingBefore(e);
        push(e, { kind: 'decision', key: key(e, 'decision'), text: decText, quote: squash(e.quote) });
      }
    } else if (e.type === 'event' && e.source === 'pm-incident') {
      const incId = String(e.incident_id || '').trim();
      const rawKey = String(e.key || '').trim();
      const incKey = rawKey || incId || key(e, 'incident');
      const fields = {
        incidentId: incId,
        incidentClass: String(e.incident_class || e.class || ''),
        status: String(e.status || 'open'),
        stage: Number(e.stage) || 0,
        step: String(e.step || ''),
        folded: Boolean(e.folded),
        reason: String(e.reason || ''),
        error: String(e.error || ''),
        suggestedProfile: String(e.suggested_profile || ''),
        text: squash(e.text || ''),
      };
      const existing = (incId && incidentsById.get(incId))
        || (rawKey && incidentsByKey.get(rawKey))
        || incidentsByKey.get(incKey);
      if (existing) {
        Object.assign(existing, {
          at: e.at || existing.at,
          ...(Number(e.at_ms) > 0 ? { at_ms: Number(e.at_ms) } : {}),
          ...fields,
          incidentId: incId || existing.incidentId || '',
          count: (existing.count || 1) + 1,
        });
        if (incId) incidentsById.set(incId, existing);
        if (rawKey) incidentsByKey.set(rawKey, existing);
        incidentsByKey.set(incKey, existing);
      } else {
        if (anchoredIdx < anchoredPending.length) flushPendingBefore(e);
        const incItem = push(e, {
          kind: 'incident',
          key: `incident:${incKey}`,
          incidentKey: incKey,
          count: 1,
          ...fields,
        });
        if (incId) incidentsById.set(incId, incItem);
        if (rawKey) incidentsByKey.set(rawKey, incItem);
        incidentsByKey.set(incKey, incItem);
      }
    } else if (e.type === 'thread' && e.task) {
      if (anchoredIdx < anchoredPending.length) flushPendingBefore(e);
      const known = before.has(e.task);
      if (!known && asking(e, undefined)) asked.add(e.task);
      const was = before.get(e.task);
      before.set(e.task, e.status);
      const gone = now(e.task).status === GIVEN_UP;
      // A task that entered as a question waits for its row until it is work.
      if (!gone && !shown.has(e.task) && (!asked.has(e.task) || WORK.includes(e.status))) {
        shown.add(e.task);
        const row = { task: e.task, ...now(e.task) };
        // Rows stay one group across the labels of threads that reported in between.
        let at = items.length - 1;
        while (at >= 0 && items[at].kind === 'about') at--;
        const last = items[at];
        if (last?.kind === 'threads' && eventDay(e) === day) last.rows.push(row);
        else push(e, { kind: 'threads', key: key(e, 'threads'), rows: [row] });
      } else if (known && !gone) {
        const cur = now(e.task);
        push(e, { kind: 'about', key: key(e, 'about'), task: e.task, ...(cur.number ? { number: cur.number } : {}), title: cur.title, by: String(e.by || '') });
      }
      if (asking(e, was)) {
        const cur = now(e.task);
        const offered = (Array.isArray(e.options) ? e.options : [])
          .map((option, i) => [squash(option), squash(Array.isArray(e.option_notes) ? e.option_notes[i] : '')]).filter(([option]) => option);
        const recIdx = Number.isInteger(e.recommended_index) && e.recommended_index >= 0 && e.recommended_index < offered.length
          ? e.recommended_index
          : (Boolean(e.recommended) && offered.length > 0 ? 0 : -1);
        const qItem = push(e, { kind: 'question', key: key(e, 'question'), task: e.task, ...(cur.number ? { number: cur.number } : {}), title: cur.title,
          text: cleanTaskLog(e.text).text, open: false, options: offered.map(([option]) => option),
          notes: offered.map(([, why]) => why), recommended: recIdx >= 0,
          ...(recIdx > 0 ? { recommendedIndex: recIdx } : {}), chosen: -1 });
        questions.push(qItem);
        questionMeta.set(qItem.key, { by: String(e.by || ''), eventIndex });
      }
    }
  }
  // Only a task's latest question, while the task still waits, can be answered.
  const answered = new Set();
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item.kind !== 'question' || answered.has(item.task)) continue;
    answered.add(item.task);
    item.open = now(item.task).status === 'blocked';
  }
  for (const p of pendingList) {
    if (!placedPending.has(p)) pushPendingItem(p);
  }
  // What the user answered waits for the coordinator now: its question and its rows say so, and no longer wait.
  const held = answeredTasks(items);
  const userAnsweredKeys = new Set(items.filter(i => i.kind === 'user' && !i.failed && i.answers).map(i => i.answers));
  for (const item of items) {
    if (item.kind === 'question' && item.open && held.has(item.task)) item.answered = true;
    if (item.kind === 'question' && !item.open && item.chosen < 0 && !item.answered && !userAnsweredKeys.has(item.key)) {
      const meta = questionMeta.get(item.key);
      if (meta) {
        const qBy = meta.by;
        const workerAsked = Boolean(qBy) && qBy !== 'user' && (!pmPane || qBy !== pmPane);
        let sawUserAfter = false, handled = false;
        for (let j = meta.eventIndex + 1; j < events.length; j++) {
          const le = events[j];
          if (le.type === 'user' && squash(le.text)) sawUserAfter = true;
          if (le.type !== 'thread' || le.task !== item.task) continue;
          const leBy = String(le.by || '');
          const resolves = le.status !== 'blocked' || asksAgain(le);
          if (le.handled_by === 'pm') { handled = true; break; }
          if (workerAsked && resolves && (!leBy || leBy !== qBy)) { handled = true; break; }
          if (pmPane && leBy === pmPane && resolves && !sawUserAfter) { handled = true; break; }
        }
        if (handled) item.handledByPm = true;
      }
    }
    if (item.kind !== 'threads') continue;
    for (const row of item.rows) {
      if (held.has(row.task) && row.status === 'blocked' && !row.cleanup) Object.assign(row, { answered: true, waiting: false, tone: 'quiet' });
    }
  }
  if (typing) items.push({ kind: 'typing', key: 'typing' });
  return items;
}

// Timeline items in blocks: a day divider, a user bubble, or a coordinator turn {kind: 'turn', parts,
// index} drawn beside one avatar. A turn ends with the coordinator's reply. Its parts, in order: the
// names of the threads the reply is about, the reply, then what the coordinator did on the way to it
// (new threads, questions, decisions), as a message with its attachments. The working dots are a
// turn of their own. `index` lists the places in `items` of the block's parts.
// A reply is about the threads the coordinator itself wrote a ledger entry for in that turn: one name
// per thread, none for a thread whose row or question is in the same turn. A worker's entry names
// nothing (it may have logged while the user asked about something else), and without a reply there
// is nothing to name. The coordinator is the session that spoke the reply; a reply from before that
// was recorded counts as `pmPane`'s, the PM's pane now.
export function turns(items, pmPane = '') {
  const out = [];
  items.forEach((item, index) => {
    const last = out[out.length - 1];
    if (item.kind === 'day' || item.kind === 'user' || item.kind === 'incident') out.push({ ...item, index: [index] });
    else if (last?.kind === 'turn' && !last.said && item.kind !== 'typing') {
      last.parts.push(item); last.index.push(index); last.said = item.kind === 'pm';
    } else {
      out.push({ kind: 'turn', key: `turn:${item.key}`, parts: [item], index: [index],
        said: item.kind === 'pm' || item.kind === 'typing' });
    }
  });
  // Parts that got no reply of their own (the user spoke first, or a day ended) join the turn right
  // before them; with no turn there they stand without an avatar (`bare`), as the newest ones do
  // while the coordinator is still working toward its reply.
  const kept = [];
  const tail = out.filter(b => b.parts?.[0]?.kind !== 'typing').pop();
  for (const block of out) {
    const before = kept[kept.length - 1];
    if (block.kind === 'turn' && !block.said) {
      if (block !== tail && before?.kind === 'turn' && before.said) {
        // The earlier reply was not about these: only what stands on its own moves over.
        block.parts.forEach((part, i) => {
          if (part.kind !== 'about') { before.parts.push(part); before.index.push(block.index[i]); }
        });
        continue;
      }
      block.bare = true;
    }
    kept.push(block);
  }
  for (const block of kept) {
    if (block.kind !== 'turn') continue;
    const reply = block.parts.find(p => p.kind === 'pm');
    const coordinator = reply ? reply.by || pmPane : '';
    // Threads this turn already shows: a new row, or a question card that carries the name.
    const here = new Set(block.parts.flatMap(p => p.kind === 'threads' ? p.rows.map(row => row.task) : p.kind === 'question' ? [p.task] : []));
    const named = new Set();
    const about = block.parts.filter(p => p.kind === 'about' && coordinator && p.by === coordinator &&
      !here.has(p.task) && !named.has(p.task) && named.add(p.task));
    block.parts = [...about, ...block.parts.filter(p => p.kind === 'pm'), ...block.parts.filter(p => p.kind !== 'pm' && p.kind !== 'about')];
  }
  return kept.filter(block => block.kind !== 'turn' || block.parts.length);
}

// The newest reply is read whole; older long ones fold until the user opens them.
export function newestReply(items) {
  for (let i = items.length - 1; i >= 0; i--) if (items[i].kind === 'pm') return items[i].key;
  return '';
}

// A session's name as the app's agents list gives it, so the two lists read alike: the tab's name
// when someone named the tab, else the agent's own title when it says something (not the program's
// name, a folder or user@host), else the program's name. `tab`: {name, named} or null.
export function sessionLabel(agent, tab) {
  const program = agent?.program?.name || '';
  if (tab?.named && tab.name && tab.name !== program) return tab.name;
  const raw = String(agent?.title || '');
  const title = raw.replace(/^[^\p{L}\p{N}]+/u, '').trim();           // without a leading status glyph
  const folder = /^[^\p{L}\p{N}~/]*([~/]|[A-Za-z]:\\)/.test(raw);
  const telling = title && title !== program && title.toLowerCase() !== agent?.program?.key && !folder && !title.includes('@');
  return telling ? title : program || agent?.address || '';
}

// What the side panel lists for one project while no thread is open there:
//   open      the PM's tasks that are not over, most pressing first:
//             {task, title, status, group, tone, waiting, latest, working (its own worker is at work),
//             offline (only when its terminal is gone), answered (only when true: blocked, and the user
//             answered it; tasks: see markAnswered), updated, branch, reviewing?, postGate?, plan?};
//             group: 'waiting' (blocked) | 'working' (in_progress, review, answered, or postGate) |
//             'offline' (in progress, its terminal gone) | 'paused' | 'parked' (proposed), in that order
//   sessions  the agents in the window whose folder is the project's or one of its worktrees, except
//             the PM and the workers/helpers of open tasks (`task`, `helper.of` or `helper.task` labels:
//             their task's row stands for them):
//             {address, label, status, program}; the app's order: needs you, done, working, idle
//   finished  the newest FINISHED_LIMIT threads that are over: {task, title, status, cleanup};
//             an answered question (see questionOnly) is not one, nor is an abandoned task
// tasks: `pm.py state` tasks; events: the conversation log; terms: terminals(); live: agents();
// tabs: every space's tabs ({id, name, named}); lang: the view's language, for `latest` (see logText).
export const FINISHED_LIMIT = 6;
export const OPEN_GROUPS = ['waiting', 'working', 'offline', 'paused', 'parked'];
const GROUP = { blocked: 'waiting', review: 'working', in_progress: 'working', paused: 'paused' };

function shortCommit(t) {
  const raw = String(t?.landed?.commit || t?.landed?.sha || t?.commit || t?.merge_commit || '').trim();
  if (!raw) return '';
  const m = /^[0-9a-f]{7,40}$/i.exec(raw);
  return m ? raw.slice(0, 7) : '';
}

const termStatusWord = s => (typeof s === 'string' ? s : (s && typeof s === 'object' ? String(s.state || '') : ''));

// The tasks whose own worker or task-serving helper is at work now: a live terminal on this computer
// labeled with the task (`task`, `helper.task`, or a worker's `helper.of`) and reporting `working`.
// Only these move on screen (dots in the conversation, the arc in the panel).
export function workingTasks(terms = [], live = []) {
  const ids = new Set();
  for (const term of terms || []) {
    if (!term || term.state !== 'live' || !term.address || term.address.includes('/')) continue;
    const lb = term.labels;
    const helperOf = lb?.['helper.of'];
    const task = lb?.task || lb?.['helper.task'] || (helperOf && !String(helperOf).startsWith('pm-') ? helperOf : '');
    if (!task) continue;
    const liveEntry = (live || []).find(a => a.address === term.address);
    const status = termStatusWord(liveEntry?.status) || termStatusWord(term.status);
    if (status === 'working') ids.add(task);
  }
  return ids;
}

// True when a task has an actively working worker or helper right now (by label, pane, helper list,
// or state fallback when no live terminal record is present).
function taskWorking(task, atWork, terms = [], live = []) {
  if (!task || typeof task !== 'object') return false;
  if (atWork?.has(task.id)) return true;
  const term = terminalFor(taskRow(task), terms || []);
  if (term && !String(term.address || '').includes('/')) {
    const liveEntry = (live || []).find(a => a.address === term.address);
    const status = termStatusWord(liveEntry?.status) || termStatusWord(term.status);
    if (status === 'working') return true;
  } else if (!term && task.worker === 'working') {
    return true;
  }
  if (Array.isArray(task.helpers)) {
    for (const h of task.helpers) {
      if (!h || typeof h !== 'object' || h.status !== 'running' || h.offline || h.live_state === 'offline') continue;
      const hAddr = String(h.terminal || h.pane || '').replace(/^hc:/, '');
      const hTerm = hAddr ? (terms || []).find(x => x?.address === hAddr) : null;
      if (hTerm) {
        if (hTerm.state !== 'live' || String(hTerm.address || '').includes('/')) continue;
        const liveEntry = (live || []).find(a => a.address === hTerm.address);
        const status = termStatusWord(liveEntry?.status) || termStatusWord(hTerm.status);
        if (status === 'working') return true;
      } else if (h.live_state === 'working') {
        return true;
      }
    }
  }
  return false;
}

// True when a task in review has a live reviewer actively working right now.
// Stays false while waiting for PM verdict (no active review thread, or review already ended/done),
// when the reviewer is offline/idle/blocked/paused/proposed, or when the task is not in review.
export function reviewWorking(task, terms = [], live = []) {
  if (!task || typeof task !== 'object' || task.cleanup) return false;
  if (task.status !== 'review') return false;
  const r = task.review;
  if (!r || typeof r !== 'object' || !r.id) return false;
  if (r.status !== 'in_progress' || r.offline) return false;
  const rRow = {
    type: 'task',
    task: r.id,
    sourceId: r.sourceId ?? r.id,
    pane: r.pane,
    machine: r.machine ?? task.machine ?? '',
  };
  const rTerm = terminalFor(rRow, terms || []);
  if (rTerm) {
    const liveEntry = (live || []).find(a => a.address === rTerm.address);
    const status = termStatusWord(liveEntry?.status) || termStatusWord(rTerm.status);
    return status === 'working';
  }
  return r.worker === 'working';
}
const SESSION_RANK = { blocked: 4, done: 3, working: 2, idle: 1 };
// A blocked task the user has answered (see markAnswered) waits for the coordinator: among the work going on.
const answeredRow = t => t.status === 'blocked' && Boolean(t.answered);
const openRank = t => {
  if (t.status === 'blocked' && !answeredRow(t)) return 0;
  if (isPostGateTask(t)) return 1;
  if (t.status === 'review') return 2;
  if (answeredRow(t)) return 3;
  if (t.status === 'in_progress' && !disconnected(t)) return 4;
  if (disconnected(t)) return 5;
  if (t.status === 'paused') return 6;
  return 7;
};
const openRow = (t, lang, atWork, terms = [], live = []) => {
  const num = taskNumber(t);
  const ctx = contextTokens(t.context_tokens);
  const closed = isClosedTask(t) ? t.closed : null;
  const steps = t.plan ? taskSteps(t, { lang }) : null;
  const postGate = Boolean(steps?.postGate);
  const isOffline = !postGate && disconnected(t);
  const group = isOffline ? 'offline' : answeredRow(t) || postGate ? 'working' : GROUP[t.status] || 'parked';
  const rowTone = postGate ? 'running' : tone(t.status, false, Boolean(t.offline), answeredRow(t));
  const revWorking = reviewWorking(t, terms, live);
  const reviewModel = t.status === 'review' ? (formatAgentModelEffort(t.review || t).model || '') : '';
  return { task: t.id, ...(num ? { number: num } : {}), title: t.title || t.id, status: t.status || '',
    tone: rowTone,
    waiting: WAITING.includes(t.status) && !answeredRow(t), ...(answeredRow(t) ? { answered: true } : {}),
    group,
    ...(t.status === 'review' ? { reviewing: true } : {}),
    ...(revWorking ? { reviewWorking: true } : {}),
    ...(reviewModel ? { reviewModel } : {}),
    ...(postGate ? { postGate: true } : {}),
    ...(steps?.hasPlan ? { plan: { done: steps.done, total: steps.total, progress: steps.progress, pill: steps.pill, postGate: steps.postGate } } : {}),
    latest: logText(lang, t.latest), updated: String(t.updated || ''), ...(!postGate && t.offline ? { offline: true } : {}),
    ...(closed ? { closed } : {}),
    ...(t.folder_alias ? { folderAlias: String(t.folder_alias) } : {}),
    branch: String(t.branch || ''), working: !isOffline && group === 'working' && taskWorking(t, atWork, terms, live),
    ...(ctx ? { contextTokens: ctx } : {}) };
};

// The threads a task was split into (`pm.py state` tasks whose `parent` is `id`), as the side panel's
// rows (see threadList's open), open ones first in the list's order, then those that are over
// (group 'finished', with cleanup). Each is still its own row in the thread list too.
// retired: the state's `retired_parts`, sub-threads gone from the board (merged and retired); they are
// over, and a task listed in both counts once.
export function subThreads(tasks, id, terms = [], live = [], lang = 'en', retired = []) {
  if (!id) return [];
  const atWork = workingTasks(terms, live);
  const seen = new Set();
  const allTasks = [...(Array.isArray(tasks) ? tasks : []), ...(Array.isArray(retired) ? retired : [])];
  const parts = allTasks
    .filter(t => t?.id && t.id !== id && t.parent === id && !seen.has(t.id) && seen.add(t.id));
  const newest = (a, b) => String(b.updated || '').localeCompare(String(a.updated || ''));
  const open = sortChildTasks(parts.filter(t => !CLOSED.includes(t.status)), allTasks)
    .map(t => openRow(t, lang, atWork, terms, live));
  const over = parts.filter(t => CLOSED.includes(t.status)).sort(newest)
    .map(t => {
      const num = taskNumber(t);
      const ctx = contextTokens(t.context_tokens);
      return { task: t.id, ...(num ? { number: num } : {}), title: t.title || t.id, status: t.status, tone: 'quiet', group: 'finished',
        cleanup: Boolean(t.cleanup), updated: String(t.updated || ''), ...(ctx ? { contextTokens: ctx } : {}) };
    });
  return [...open, ...over];
}

// The sub-threads the panel shows: past PARTS_LIMIT the rest fold behind a row that says how many
// more there are (`more`), until it is opened (`open`).
export const PARTS_LIMIT = 6;
export function foldParts(parts, open = false, limit = PARTS_LIMIT) {
  const rows = Array.isArray(parts) ? parts : [];
  if (open || rows.length <= limit) return { shown: rows, more: 0 };
  return { shown: rows.slice(0, limit), more: rows.length - limit };
}

// The review thread folded into a task (foldReviews), for that task's side panel: a row as the thread
// list's (its mark, status and latest report; group 'finished' once it is over), or null without one.
export function reviewRow(task, terms = [], live = [], lang = 'en') {
  const r = task?.review;
  if (!r?.id) return null;
  const ctx = contextTokens(r.context_tokens);
  const row = !CLOSED.includes(r.status) ? openRow(r, lang, workingTasks(terms, live), terms, live)
    : { task: r.id, ...(taskNumber(r) ? { number: taskNumber(r) } : {}), title: r.title || r.id, status: r.status, tone: 'quiet', group: 'finished',
      latest: logText(lang, r.latest), updated: String(r.updated || ''), ...(ctx ? { contextTokens: ctx } : {}) };
  // A reviewer's report can be long: its opening, as a reply's is shown folded.
  return { ...row, latest: row.latest ? lead(row.latest, 160).text : '' };
}
// The thread a link or a line opens: a review thread folded into its task opens that task.
export function threadFor(tasks, id) {
  return (Array.isArray(tasks) ? tasks : []).find(t => t?.review?.id === id)?.id || id;
}

// The task a thread was split from, for the side panel's link back: {task, title}, or null when it
// has none or that task is not in `pm.py state` (closed and gone from the board).
export function parentThread(tasks, task) {
  const id = task?.parent;
  const found = id && id !== task.id ? (Array.isArray(tasks) ? tasks : []).find(t => t?.id === id) : null;
  const num = taskNumber(found);
  return found ? { task: found.id, ...(num ? { number: num } : {}), title: found.title || found.id } : null;
}
const trimFolder = path => typeof path === 'string' && path ? path.replace(/\/+$/, '') || '/' : '';
function threadSessionsAndFinished(pm, mine, openIds, events, terms = [], live = [], tabs = []) {
  const local = (terms || []).filter(x => x.state === 'live' && x.address && !x.address.includes('/'));
  const roots = [...new Set([
    ...projectFolders(pm).map(f => trimFolder(f.path)),
    trimFolder(pm?.repo),
    trimFolder(pm?.worktrees),
  ].filter(Boolean))];
  const within = cwd => roots.some(root => cwd === root || cwd.startsWith(root === '/' ? root : `${root}/`));
  const pmAddress = pm ? terminalFor(pmRow(pm), terms || [])?.address : '';
  const pmHelperTasks = new Map();
  for (const h of Array.isArray(pm?.helpers) ? pm.helpers : []) {
    if (!h || typeof h !== 'object') continue;
    if (h.status !== 'running' || h.offline || h.live_state === 'offline') continue;
    const addr = String(h.terminal || h.pane || '').replace(/^hc:/, '');
    if (!addr) continue;
    const hName = String(h.name || '');
    const term = local.find(x => x.address === addr);
    if (!term || !term.labels?.helper || (hName && term.labels.helper !== hName)) continue;
    const ft = pmHelperTask(h, terms);
    if (ft) pmHelperTasks.set(addr, ft);
    else pmHelperTasks.delete(addr);
  }
  const found = (live || []).flatMap(agent => {
    const term = local.find(x => x.address === agent.address);
    if (!term || !within(trimFolder(term.cwd))) return [];
    if (term.address === pmAddress || term.labels?.pm || openIds.has(term.labels?.task) || openIds.has(term.labels?.['helper.of']) ||
      openIds.has(term.labels?.['helper.task']) || openIds.has(pmHelperTasks.get(term.address))) return [];
    return [{ agent, term }];
  });
  const perTab = new Map();
  for (const { agent } of found) perTab.set(agent.tab, (perTab.get(agent.tab) || 0) + 1);
  const tabOf = new Map((tabs || []).map(tab => [tab.id, tab]));
  const sessions = found.map(({ agent, term }) => ({
    address: agent.address, status: SESSION_RANK[agent.status] ? agent.status : 'idle', program: agent.program || term.program || null,
    // Two agents in one tab cannot both carry the tab's name.
    label: sessionLabel(agent, perTab.get(agent.tab) > 1 ? null : tabOf.get(agent.tab)), seq: Number(agent.seq) || 0,
  })).sort((a, b) => SESSION_RANK[b.status] - SESSION_RANK[a.status] || b.seq - a.seq)
    .map(({ seq, ...row }) => row);

  const byId = new Map(mine.map(t => [t.id, t]));
  const over = new Map(), questions = questionOnly(events);
  const ended = status => CLOSED.includes(status) && status !== GIVEN_UP;
  // A review's own events (the log names it, not what it reviews): folded into its task, not a row. The
  // log carries no review_of: a `<id>-review` whose <id> is a thread here or in the log is one.
  const named = new Set([...byId.keys(), ...(events || []).map(e => e.task)]);
  const folded = new Set(mine.filter(t => t.review?.id).map(t => t.review.id));
  const review = id => folded.has(id) || (/-review$/.test(id) && named.has(id.slice(0, -'-review'.length)));
  for (const e of events || []) {
    if (e.type !== 'thread' || !e.task || questions.has(e.task) || review(e.task)) continue;
    const t = byId.get(e.task), status = t?.status || e.status || '';
    if (ended(status)) {
      const num = taskNumber(t) || taskNumber(e);
      const ctx = contextTokens(t?.context_tokens);
      const commit = shortCommit(t) || shortCommit(e);
      over.set(e.task, { task: e.task, ...(num ? { number: num } : {}), title: t?.title || e.title || e.task, status, cleanup: Boolean(t?.cleanup),
        ...(t?.folder_alias ? { folderAlias: String(t.folder_alias) } : {}),
        at: String(e.at || ''), ...(commit ? { commit } : {}), ...(ctx ? { contextTokens: ctx } : {}) });
    } else over.delete(e.task);
  }
  for (const t of mine) {
    if (ended(t.status) && !over.has(t.id) && !questions.has(t.id)) {
      const num = taskNumber(t);
      const ctx = contextTokens(t.context_tokens);
      const commit = shortCommit(t);
      over.set(t.id, { task: t.id, ...(num ? { number: num } : {}), title: t.title || t.id, status: t.status, cleanup: Boolean(t.cleanup),
        ...(t.folder_alias ? { folderAlias: String(t.folder_alias) } : {}),
        at: String(t.updated || ''), ...(commit ? { commit } : {}), ...(ctx ? { contextTokens: ctx } : {}) });
    }
  }
  const finished = [...over.values()].sort((a, b) => b.at.localeCompare(a.at)).slice(0, FINISHED_LIMIT)
    .map(({ at, ...row }) => row);
  return { sessions, finished };
}

export function threadList(pm, tasks, events, terms = [], live = [], tabs = [], lang = 'en') {
  const mine = (Array.isArray(tasks) ? tasks : []).filter(t => (t.pm || '') === (pm?.name || ''));
  const atWork = workingTasks(terms, live);
  // A thread in progress whose terminal is gone is listed apart, after the work going on.
  const rank = openRank;
  const open = mine.filter(t => !CLOSED.includes(t.status))
    .sort((a, b) => rank(a) - rank(b) || String(b.updated || '').localeCompare(String(a.updated || '')))
    .map(t => openRow(t, lang, atWork, terms, live));
  // A folded review's worker is part of its task's row too (foldReviews).
  const openIds = new Set([...open.map(row => row.task), ...mine.filter(t => t.review?.id).map(t => t.review.id)]);
  const { sessions, finished } = threadSessionsAndFinished(pm, mine, openIds, events, terms, live, tabs);
  return { open, sessions, finished };
}

// A PM reply as markdown the app's renderer numbers right. Herdr 0.1.15's TextView
// gives a paragraph that follows a sub-list its own list marker, so
//   1. Do this:\n   - a\n\n   Then that.\n2. Next
// shows 1, 1, 2, 2 (fixed upstream in gpui-component fe2e4bcf). Such a paragraph,
// and the rest of its top-level item, moves out to the left edge; the list then
// resumes at the next item's own number (a list keeps its start).
const ITEM = /^( {0,3})([-*+]|\d{1,9}[.)])( +|$)/;
const MARKER = /^([-*+]|\d{1,9}[.)])(\s|$)/;
const FENCE = /^ *(`{3,}|~{3,})/;
const indentOf = line => /^ */.exec(line)[0].length;
const VIEW_MD_CACHE = new Map();
export function viewMarkdown(text) {
  const src = String(text || '');
  if (!src) return '';
  return fifoCacheGetSet(VIEW_MD_CACHE, src, () => {
    const out = [];
    let item = null, sub = false, lifting = false, blank = false, fence = '';
    for (const line of src.split('\n')) {
      const lift = l => lifting ? l.slice(Math.min(item.content, indentOf(l))) : l;
      if (fence) {
        out.push(lift(line));
        if (line.trim().startsWith(fence)) fence = '';
        continue;
      }
      if (!line.trim()) { out.push(lift(line)); blank = true; continue; }
      const indent = indentOf(line), inside = item && indent >= item.content;
      const top = !inside && ITEM.exec(line);
      if (top) {
        if (lifting && out.length && out[out.length - 1].trim()) out.push('');
        // Text starts after the marker's spaces; none, or more than four, count as one.
        const [, lead, marker, gap] = top;
        item = { content: lead.length + marker.length + (gap.length && gap.length <= 4 ? gap.length : 1) };
        sub = false; lifting = false; blank = false;
        out.push(line);
        continue;
      }
      if (inside) {
        const rest = line.slice(item.content);
        const opens = FENCE.exec(rest);
        if (opens && indentOf(rest) < 4) { fence = opens[1]; sub = false; }
        else if (indentOf(rest) === 0 && MARKER.test(rest)) sub = true;
        else if (indentOf(rest) === 0) {
          if (blank && sub && !lifting) lifting = true;
          sub = false;
        }
        out.push(lift(line));
      } else {
        if (item && blank) { item = null; lifting = false; sub = false; }
        const opens = FENCE.exec(line);
        if (opens) fence = opens[1];
        out.push(line);
      }
      blank = false;
    }
    return out.join('\n');
  }, 512);
}

// Where the bell scrolls: the latest open question, else the latest thread
// group holding a waiting row; -1 when nothing waits.
// What the conversation's scroll area holds, top to bottom: the blocks of turns(), with each
// coordinator turn cut into rows. The area can only be asked to reveal one of its own children, and
// the bell goes to one question, so a question must be such a child and not a part inside a tall
// turn. A turn's first row carries the avatar beside the thread names and the reply (beside its first
// part when it has neither); every further part is a row of its own under it.
// A turn's row: {kind: 'turn', key, parts, first, bare}; a day or a bubble stays the block it was.
export function timelineRows(blocks) {
  return blocks.flatMap(block => {
    if (block.kind !== 'turn') return [block];
    const head = block.parts.filter(p => p.kind === 'about' || p.kind === 'pm');
    const groups = [...(head.length ? [head] : []), ...block.parts.filter(p => !head.includes(p)).map(p => [p])];
    return groups.map((parts, n) => ({ kind: 'turn', key: n ? `${block.key}/${parts[0].key}` : block.key, parts,
      first: n === 0, bare: Boolean(block.bare) }));
  });
}
// The row that holds `item` (one of the timeline's items), or -1.
export const rowOf = (rows, item) => rows.findIndex(row => row.parts?.includes(item));
// The timeline block index that renders a given item key (user bubble, PM reply, question card, or decision), or -1.
export function blockIndexForKey(blocks, key) {
  if (!key || !Array.isArray(blocks)) return -1;
  return blocks.findIndex(b => b?.key === key || Boolean(b?.parts?.some(p => p?.key === key)));
}

export function rowOfKey(rows, key) {
  if (!Array.isArray(rows) || !key) return -1;
  return rows.findIndex(row => row.key === key || Boolean(row.parts?.some(p => p.key === key)));
}

// The view follows the end of the conversation only for a reader who is at the end, and it cannot
// read where the scroll area rests. So it keeps count of how far above the end the reader is, in px
// (`rise`; 0 is the end), from what it does know: the wheel, each row's height and the area's height.
// The count errs toward following, since a reader wrongly taken to be away misses what arrives below.
// After the wheel moved by `dy` (> 0 is toward the top). room: how far the area can scroll at all
// (its content minus its height); view: its height. Going up never counts past what can be scrolled
// (a short conversation, or the top, does not move) nor past two screens; coming down takes off three
// times the distance, which also absorbs what the count missed (a dragged scrollbar, a key).
export function riseAfterWheel(rise, dy, room, view) {
  if (dy > 0) return Math.max(0, Math.min(rise + dy, room, 2 * view));
  return Math.max(0, rise + 3 * dy);
}
// After the scroll area was asked to reveal row `at` (the bell): it moves the least that shows the
// row, and not at all when the row is in view. heights: every row's height, top to bottom; tail: the
// space after the last row. With a height still unknown, a jump counts as a screen, except to the
// last row (the reader at the end has it in view).
export function riseAfterJump(rise, heights, at, view, tail = 0) {
  if (!(view > 0) || heights.some(h => !(h > 0))) return at >= heights.length - 1 ? rise : Math.max(rise, view || 1);
  // Distances from the end of the content: the row's lower and upper edge, and the area's (rise, rise + view).
  const low = heights.slice(at + 1).reduce((sum, h) => sum + h, tail), high = low + heights[at];
  if (high > rise + view) return Math.max(0, high - view);   // above the area: its top comes to the area's top
  if (low >= rise) return rise;                              // in view: nothing moves
  return low <= tail ? 0 : low;                              // below it: its bottom comes to the area's bottom (the last row: the end)
}

// The blocked tasks the user has answered, as task ids: the task's open question (its newest one, asked
// when the task last entered blocked or asked again, see asksAgain) was answered: an option picked on
// it (`chosen`, from the log or on its way) or words that name it (`answers`: a quick answer, or words
// that start with its 【title】). A row or question timeline() marked answered counts too (pm.py's
// `answered`, for a question older than the events shown). The task then waits for the coordinator,
// not for the user, until the coordinator moves it on; a reply in between changes nothing. A new
// question (the task asking again) is unanswered. Words that name no question answer none: they may
// be about something else. A blocked task without a card is answered by words that name it
// (askKey, see timeline).
export function answeredTasks(items) {
  const answers = new Set(items.filter(i => i.kind === 'user' && !i.failed && i.answers).map(i => i.answers));
  const out = new Set([...answers].filter(key => key.startsWith(ASK)).map(key => key.slice(ASK.length)));
  for (const i of items) {
    if (i.kind === 'question' && i.open && (i.answered || i.chosen >= 0 || answers.has(i.key))) out.add(i.task);
    else if (i.kind === 'threads') for (const r of i.rows) if (r.answered) out.add(r.task);
  }
  return out;
}

// `tasks` (pm.py state's) with `answered: true` on the blocked ones in `answered` (see answeredTasks):
// the side panel shows what the conversation already knows, before pm.py has read it.
export function markAnswered(tasks, answered) {
  return (Array.isArray(tasks) ? tasks : []).map(t => t?.status === 'blocked' && !t.answered && answered.has(t.id) ? { ...t, answered: true } : t);
}

// The question cards that wait for the user, as places in `items`, newest first: a task's open question,
// unless the user answered it (see answeredTasks).
export function bellTargets(items) {
  const out = [];
  for (let i = items.length - 1; i >= 0; i--) if (items[i].kind === 'question' && items[i].open && !items[i].answered) out.push(i);
  return out;
}

// Where the bell goes, one stop per task that waits for the user, in click order: its question card
// ({key, at: its place in `items`}, see bellTargets), newest first; then, for a waiting task with no
// card in the conversation (asked before the events shown, or before the log), its thread
// ({key, thread: the task's id}), whose detail asks it (threadQuestion). tasks: `pm.py state` tasks,
// the ones of `pm` (the project) that are blocked and not answered, as waitingCount counts them.
export function bellStops(items, tasks = [], pm = null) {
  const cards = bellTargets(items).map(at => ({ key: items[at].key, at }));
  const asked = new Set(items.filter(i => i.kind === 'question' && i.open).map(i => i.task));
  const answered = answeredTasks(items);
  const threads = (Array.isArray(tasks) ? tasks : []).filter(t => t?.status === 'blocked' && !t.answered && !t.cleanup
    && (!pm || t.pm === pm.name) && !asked.has(t.id) && !answered.has(t.id))
    .map(t => ({ key: `thread:${t.id}`, thread: t.id }));
  return [...cards, ...threads];
}

// What waits for the user in a project: its tasks that are blocked and not answered (pm.py marks a task
// `answered`, see answered_tasks there), one each, whether or not the conversation shows where. It is
// the project's badge in the sidebar and on the board: a copy of pm-list's waitingCount (a mod cannot
// import from another mod's folder; model.test.mjs checks the copies stay identical), so pm.py's
// counts.waiting when it gives one, else the PM's blocked tasks not answered (an older pm.py).
export function waitingCount(pm, tasks) {
  if (Number.isFinite(pm?.counts?.waiting)) return pm.counts.waiting;
  return (Array.isArray(tasks) ? tasks : []).filter(t => t?.pm === pm?.name && t.status === 'blocked' && !t.answered).length;
}

// The bell's number: waitingCount, less the tasks the conversation shows answered (see answeredTasks)
// that pm.py has not read yet, so a picked answer takes the bell down at once. Review threads fold
// with their task first so answering a review (or a shadowed review) matches pm.py's folded counts.
export function bellCount(pm, tasks, answered) {
  const raw = Array.isArray(tasks) ? tasks : [];
  const folded = foldReviews(raw);
  const base = waitingCount(pm, folded);
  if (!answered?.size) return base;
  const before = folded.filter(t => t?.pm === pm?.name && t.status === 'blocked' && !t.answered).length;
  const after = foldReviews(markAnswered(raw, answered))
    .filter(t => t?.pm === pm?.name && t.status === 'blocked' && !t.answered).length;
  return Math.max(0, base - Math.max(0, before - after));
}

// The stop (see bellStops) the next click on the bell goes to, null when nothing waits. `last` is what
// the click before left: {key: the stop it went to, seen: the keys of the stops then}. Clicks step
// through the stops in order and start over after the last. They also start over at the first when
// something waits that did not at the last click.
export function bellNext(stops, last) {
  if (!stops.length) return null;
  const known = last && stops.every(s => last.seen.includes(s.key));
  const at = known ? last.seen.indexOf(last.key) : -1;
  return (at >= 0 && stops.find(s => last.seen.indexOf(s.key) > at)) || stops[0];
}

// What an open thread's detail asks while its task waits for the user (blocked, not answered), null
// otherwise: {key, title, text, options, notes, recommended}, answered as a question card is (a quick
// answer sends answerText(title, option) tagged `key`; the user's own words go after the 【title】).
// A task with a question card in the conversation asks that card's question, under its key. One
// without (see bellStops) asks what its ledger file says: the entry that last made it blocked (its
// note), else its latest entry, and the quick answers the task offers; under askKey(task).
// task: the thread's ledger file over its `pm.py state` task (`answered`, see markAnswered).
export function threadQuestion(task, items = []) {
  if (!task?.id || task.status !== 'blocked' || task.answered || task.cleanup) return null;
  const card = [...items].reverse().find(i => i.kind === 'question' && i.task === task.id && i.open);
  if (card) {
    return card.answered || card.chosen >= 0 ? null : { key: card.key, title: card.title, text: card.text,
      options: card.options, notes: card.notes, recommended: card.recommended,
      ...(card.recommendedIndex > 0 ? { recommendedIndex: card.recommendedIndex } : {}) };
  }
  const log = Array.isArray(task.log) ? task.log : [];
  const asking = [...log].reverse().find(e => /\bstatus\s*=\s*blocked\b/.test(String(e?.text || '')));
  const latest = log.length ? log[log.length - 1].text : task.latest;
  const text = cleanTaskLog(asking?.text).text || cleanTaskLog(latest).text;
  const offered = (Array.isArray(task.options) ? task.options : [])
    .map((option, i) => [squash(option), squash(Array.isArray(task.option_notes) ? task.option_notes[i] : '')]).filter(([o]) => o);
  const recIdx = Number.isInteger(task.recommended_index) && task.recommended_index >= 0 && task.recommended_index < offered.length
    ? task.recommended_index
    : (Boolean(task.recommended) && offered.length > 0 ? 0 : -1);
  return { key: askKey(task.id), title: task.title || task.id, text, options: offered.map(([o]) => o),
    notes: offered.map(([, why]) => why), recommended: recIdx >= 0,
    ...(recIdx > 0 ? { recommendedIndex: recIdx } : {}) };
}

// The thread a bell stop (see bellStops) opens: a review's is the task it reviews (threadFor; tasks
// as the list shows them, foldReviews); '' when that detail is already open (shown), as a second
// click must not close it.
export function bellThread(stop, tasks, shown = '') {
  const id = stop?.thread ? threadFor(tasks, stop.thread) : '';
  return id && id !== shown ? id : '';
}

// What an open thread's detail asks (see threadQuestion). folded: the thread as the list shows it
// (foldReviews, markAnswered); own: its own `pm.py state` task; file: its ledger file, once read. A
// task whose review waits shows as blocked (foldReviews): the question is then the review's, not one
// of the task's own older ones, which were answered.
export function detailQuestion(folded, own, file, items = []) {
  if (!folded?.id) return null;
  if (folded.review?.status === 'blocked' && folded.status === 'blocked' && own?.status !== 'blocked') return threadQuestion(folded.review, items);
  const status = (folded.review ? folded.status : file?.status || folded.status) || '';
  return threadQuestion({ ...folded, ...(file || {}), id: folded.id, status, answered: Boolean(folded.answered), cleanup: folded.cleanup }, items);
}

// "09:08" today, else "11-12 09:08"; log entries ("YYYY-MM-DD HH:MM") and events alike.
export function clock(at, today) {
  const text = String(at || '');
  const time = text.slice(11, 16);
  return text.slice(0, 10) === today ? time : `${text.slice(5, 10)} ${time}`.trim();
}

export function dayLabel(lang, date, today, yesterday) {
  if (date === today) return word(lang, 'today');
  if (date === yesterday) return word(lang, 'yesterday');
  return date;
}

// "~/project/repos/dudu" for a folder under home.
export function shortPath(path, home) {
  const p = String(path || '');
  return home && (p === home || p.startsWith(home + '/')) ? '~' + p.slice(home.length) : p;
}

// The pm.py argv of the thread box and the agent window: the user's own words into a worker, reviewer
// or helper terminal (`address` as the project's machine names it). `pm.py send --as-user` queues
// them in that terminal's mailbox and its one typist types them as written (no `[from …]` line);
// nothing here types into a terminal itself. `task`: the thread it belongs to (a send that does not
// go in is noted there). A long text goes as `fromFile`. `--` keeps a text starting with "-" (a
// Markdown list) from parsing as an option.
// `asUser: false`: for a pm.py older than `--as-user` on the project's machine (the words then go with its
// `[from …]` line). `wait`: typed before pm.py answers (no thread to note a later failure on), so an
// error comes back to the caller; `--timeout` bounds the hc send.
export function terminalSendArgv(address, { text = null, fromFile = null, task = '', asUser = true, wait = false } = {}) {
  const args = ['send'];
  if (asUser) args.push('--as-user');
  if (task) args.push('--task', String(task));
  if (wait) args.push('--wait', '--timeout', String(SEND_WAIT_SECONDS));
  if (fromFile != null) return [...args, '--file', String(fromFile), '--', String(address)];
  return [...args, '--', String(address), String(text ?? '')];
}

export const SEND_WAIT_SECONDS = 60;

// Whether pm.py refused an option it does not know (argparse: "unrecognized arguments: --as-user"): a
// machine whose pm.py is older than this app.
export function rejectsOption(result, option) {
  if (!result || result.code === 0) return false;
  const text = `${result.stderr || ''}\n${result.stdout || ''}`;
  const at = text.search(/unrecognized arguments:/i);
  return at >= 0 && text.slice(at).split('\n')[0].split(/\s+/).includes(String(option));
}

export function makeClientMsgId(now = Date.now(), seq = 1) {
  const ts = Math.max(0, Math.floor(Number(now) || Date.now())).toString(36);
  const s = Math.max(1, Math.floor(Number(seq) || 1)).toString(36);
  const rand = Math.random().toString(36).slice(2, 8) || '000000';
  return `u-${ts}-${s}-${rand}`;
}

// Put optional positional `target` before flags and pass payload via `--text=`/`--from=` (no `--`) so
// both newer `pm.py` and older Python <3.12 argparse `project send` subparsers accept normal and `-`-prefixed text.
export function projectSendArgv(slug, { msgId, target = '', text = null, fromFile = null, question = '' } = {}) {
  const args = ['project', 'send', String(slug)];
  if (target) args.push(String(target));
  args.push('--msg-id', String(msgId));
  if (question) args.push('--question', String(question));
  if (fromFile != null) {
    args.push(`--from=${String(fromFile)}`);
    return args;
  }
  args.push(`--text=${String(text ?? '')}`);
  return args;
}

export function projectInterruptArgv(slug) {
  return ['project', 'interrupt', String(slug)];
}

export function rotatePmArgs(repo, reason = '') {
  const args = ['rotate', '--repo', String(repo || '')];
  if (reason) args.push('--reason', String(reason));
  return args;
}

export function readScreenArgv(address) {
  return ['hc', 'read', '--', address];
}

// Live status of the PM's terminal: 'working' | 'blocked' | 'error' | 'idle' | 'done' | ''.
export function pmLiveStatus(pmTerm, live = []) {
  if (!pmTerm?.address) return '';
  return String((live || []).find(a => a.address === pmTerm.address)?.status || pmTerm.status || '');
}

// True when the PM's foreground agent turn is actively running (excluding background-shell-only
// status reports like "1 shell still running" or `pm.turn.phase === 'idle'` with `bg_shells > 0`).
// When the live PM terminal reports no status at all, fall back to pm.py's turn record (`pm-turn.json`).
export function pmTurnWorking(pmTerm, live = [], turn = null) {
  const liveStatus = pmLiveStatus(pmTerm, live);
  if (liveStatus === 'working') {
    const msg = String(pmTerm?.report?.msg || '');
    if (/\bshells?\s+still\s+running\b/i.test(msg)) return false;
    if (turn && typeof turn === 'object' && turn.phase === 'idle' && Number(turn.bg_shells) > 0) return false;
    return true;
  }
  if (pmTerm?.address && !liveStatus && turn && typeof turn === 'object') {
    return turn.phase === 'working' || turn.phase === 'stalled';
  }
  return false;
}

export const PM_SOFT_STALL_MS = 90_000;
export const PM_HARD_STALL_MS = 300_000;

export function formatTurnDuration(ms) {
  const totalSec = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
  if (totalSec < 60) return `${totalSec}s`;
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  if (mins < 60) return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins > 0 ? `${hrs}h ${remMins}m` : `${hrs}h`;
}

export const PM_SNAPSHOT_STALE_MS = 15_000;

function clipSingleLine(text, maxLen = 72) {
  const flat = String(text || '').replace(/\s+/g, ' ').trim();
  if (!flat) return '';
  return flat.length > maxLen ? `${flat.slice(0, maxLen - 1)}…` : flat;
}

function stallEvidenceLabel(lang, healthReason, detail) {
  const r = String(healthReason || '').trim().toLowerCase();
  if (r === 'pty_frozen') return word(lang, 'pmEvidencePtyFrozen');
  if (r === 'no_step_timeout') return word(lang, 'pmEvidenceNoStep');
  if (r === 'tool_hard_budget') return word(lang, 'pmEvidenceToolHard');
  if (r === 'tool_waiting_input') return word(lang, 'pmEvidenceToolInput');
  if (r === 'submitted_timeout') return word(lang, 'pmEvidenceSubmitted');
  if (r === 'upstream_timeout') return word(lang, 'pmEvidenceUpstream');
  return clipSingleLine(detail || healthReason || '', 52);
}

function extractRetryAttempt(act, healthReason) {
  const sources = [
    String(act?.summary || ''),
    String(healthReason || ''),
  ];
  for (const src of sources) {
    const m = src.match(/(?:retry\s*[:#]?\s*|attempt\s*|第\s*)(\d+)/i);
    if (m) return Number(m[1]) || 0;
  }
  return 0;
}

function agentSteersMidTurn(agentKind) {
  const norm = String(agentKind || '').trim().toLowerCase();
  return norm === 'claude' || norm === 'claude-code' || norm === 'codex';
}

export function recoveryStepLabel(lang, rawStep) {
  const step = clipSingleLine(rawStep || '', 56);
  if (!step) return '';
  const strKey = `recoveryStep_${step}`;
  if (Object.prototype.hasOwnProperty.call(STRINGS.en, strKey)) return word(lang, strKey);
  return step;
}

const INCIDENT_PREFIX_RE = /^(?:auto-recovered\s*(?:\(|·)|recovered\s+(?:from\b|·)|recovery stopped\s*\(|needs your attention[:\s]|auto-recovering[:\s]|recovering\s*(?:\(|:)|已自动恢复|已从「|自动恢复需要|需要你介入|正在自动恢复)/i;

export function incidentRowView(lang, item) {
  const status = String(item?.status || 'open').trim().toLowerCase();
  const folded = status === 'resolved' && Boolean(item?.folded);
  const stepLabel = recoveryStepLabel(lang, item?.step || '');
  const rawDetail = String(item?.text || '').replace(/\s+/g, ' ').trim()
    || [item?.incidentClass, item?.reason, item?.error].filter(Boolean).join(' · ');
  const detail = clipSingleLine(rawDetail, 120);
  const hasPrefix = INCIDENT_PREFIX_RE.test(detail);
  const norm = s => String(s || '').replace(/\s+/g, ' ').trim();
  const extraTip = (label, { truncatedRow = false } = {}) => {
    const nLabel = norm(label);
    const nRaw = norm(rawDetail);
    if (!nRaw) return '';
    if (nRaw !== detail) return nRaw;
    if (nRaw === nLabel || nLabel.includes(nRaw)) {
      return truncatedRow && nLabel.length > 80 ? nRaw : '';
    }
    return nRaw;
  };
  if (folded) {
    const label = hasPrefix ? detail : word(lang, 'incidentFolded', detail);
    return { label, detail, tooltip: extraTip(label, { truncatedRow: true }), tone: 'muted', folded: true, icon: 'check' };
  }
  if (status === 'resolved') {
    const label = hasPrefix ? detail : word(lang, 'incidentRecovered', detail);
    return { label, detail, tooltip: extraTip(label, { truncatedRow: true }), tone: 'resolved', folded: false, icon: 'check' };
  }
  if (status === 'notified') {
    const label = hasPrefix ? detail : word(lang, 'incidentNotified', detail);
    return { label, detail, tooltip: extraTip(label), tone: 'alert', folded: false, icon: 'bell' };
  }
  const label = stepLabel
    ? word(lang, 'incidentRecovering', stepLabel)
    : (hasPrefix ? detail : word(lang, 'incidentRecovering', detail));
  return {
    label,
    detail,
    tooltip: extraTip(label),
    tone: 'recovering',
    folded: false,
    icon: 'refresh',
  };
}

// Pure view-model for the quiet single-line coordinator activity indicator at the bottom of the timeline (§3.9).
// Maps backend `turn2` + `supervised` + snapshot age strictly to the §3.9 table; zero local threshold invention (FS-13).
export function pmActivityView(lang, {
  turn = null,
  turn2 = null,
  supervised = undefined,
  working = false,
  pendingSending = false,
  nowMs = Date.now(),
  serverNowMs = 0,
  receivedAtMs = 0,
  snapshotAgeMs = null,
  agentKind = '',
} = {}) {
  const v2Turn = turn2?.turn && typeof turn2.turn === 'object' ? turn2.turn : null;
  const effTurn = turn && typeof turn === 'object' ? turn : null;
  const effPhase = String(v2Turn?.phase || effTurn?.phase || '');
  const effHealth = String(v2Turn?.health || effTurn?.health || '');
  const bgShells = Number(turn2?.bg_shells?.count ?? effTurn?.bg_shells ?? 0) || 0;
  const resolvedKind = String(turn2?.session?.agent_kind || agentKind || '').trim().toLowerCase();
  const steersMidTurn = agentSteersMidTurn(resolvedKind);

  const base = {
    active: false,
    mode: 'idle',
    label: '',
    preamble: '',
    tooltip: '',
    tone: 'neutral',
    slow: false,
    stalled: false,
    unknown: false,
    canInterrupt: false,
    canRotate: false,
    canOpenTerminal: false,
    bgShells,
    steersMidTurn,
    activityShort: '',
  };

  // §3.9 Row 1: `supervised: false` or snapshot > 15s stale -> Status unknown, reconnecting… (openTerminal icon).
  const isSupervised = supervised === false || turn2?.supervised === false ? false : true;
  const computedAgeMs = Number.isFinite(snapshotAgeMs)
    ? Math.max(0, Number(snapshotAgeMs))
    : (Number(receivedAtMs) > 0 && Number(nowMs) > Number(receivedAtMs)
      ? Math.max(0, Number(nowMs) - Number(receivedAtMs))
      : (Number.isFinite(turn2?.beat_age_ms) ? Number(turn2.beat_age_ms) : 0));
  const snapshotStale = computedAgeMs > PM_SNAPSHOT_STALE_MS;

  if ((!isSupervised || effHealth === 'unknown' || snapshotStale) && effPhase !== 'offline') {
    return {
      ...base,
      active: true,
      mode: 'unknown',
      label: word(lang, 'pmTurnUnknown'),
      tone: 'muted',
      unknown: true,
      canOpenTerminal: true,
    };
  }

  // §3.9 Row 13: `idle` with background shells -> hide activity row (bgShells surfaced in header terminal tooltip).
  if (effPhase === 'idle' && !pendingSending) {
    return { ...base, active: false, mode: 'idle', bgShells };
  }

  // §3.9 Row 10: `blocked` (even when `working` is false) -> Waiting for you in the terminal + openTerminal.
  if (effPhase === 'blocked') {
    const kindText = clipSingleLine(v2Turn?.activity?.summary || v2Turn?.health_reason || '', 48);
    return {
      ...base,
      active: true,
      mode: 'blocked',
      label: word(lang, 'pmTurnBlocked', kindText),
      tone: 'warn',
      canOpenTerminal: true,
    };
  }

  // §3.9 Row 11: `recovering` -> Recovering: <step> + openTerminal.
  if (effPhase === 'recovering') {
    const rawStep = v2Turn?.activity?.summary || turn2?.incident?.step_name || v2Turn?.health_reason || '';
    const stepText = recoveryStepLabel(lang, rawStep);
    return {
      ...base,
      active: true,
      mode: 'recovering',
      label: word(lang, 'pmTurnRecovering', stepText),
      tone: 'neutral',
      canOpenTerminal: true,
    };
  }

  const active = Boolean(working || pendingSending || (v2Turn && ['submitted', 'generating', 'tool', 'waiting_upstream'].includes(effPhase)));
  if (!active || effPhase === 'offline' || effPhase === 'starting') {
    return { ...base, active: false, mode: 'idle', bgShells };
  }

  // §3.9 Row 2: `submitted` -> dots only, no icons.
  if (effPhase === 'submitted') {
    if (effHealth === 'stalled') {
      const refNowSub = Number(serverNowMs) > 0
        ? Number(serverNowMs) + (Number(receivedAtMs) > 0 ? Math.max(0, nowMs - Number(receivedAtMs)) : 0)
        : nowMs;
      const sinceMs = Number(v2Turn?.phase_since_ms || v2Turn?.started_ms) || 0;
      const dur = formatTurnDuration(sinceMs > 0 ? Math.max(0, refNowSub - sinceMs) : 0);
      const evidence = stallEvidenceLabel(lang, v2Turn?.health_reason, '');
      return {
        ...base,
        active: true,
        mode: 'stalled',
        label: word(lang, 'pmTurnStalledEvidence', dur, evidence),
        tone: 'stalled',
        stalled: true,
        canInterrupt: true,
        canRotate: true,
        canOpenTerminal: true,
      };
    }
    return { ...base, active: true, mode: 'dots', label: '', canInterrupt: false };
  }

  if (!effTurn && !v2Turn) {
    return { ...base, active: true, mode: 'dots', label: '', canInterrupt: Boolean(working) };
  }

  const srcTurn = v2Turn || effTurn;
  const refNow = Number(serverNowMs) > 0
    ? Number(serverNowMs) + (Number(receivedAtMs) > 0 ? Math.max(0, nowMs - Number(receivedAtMs)) : 0)
    : nowMs;
  const startedMs = Number(v2Turn?.started_ms ?? effTurn?.started_ms) || 0;
  const phaseSinceMs = Number(v2Turn?.phase_since_ms ?? startedMs) || startedMs;
  const lastProgressMs = Number(v2Turn?.last_progress_ms ?? effTurn?.last_activity_ms) || startedMs;
  const elapsedMs = startedMs > 0
    ? Math.max(Number(effTurn?.elapsed_ms) || 0, refNow - startedMs)
    : (Number(effTurn?.elapsed_ms) || 0);
  const idleForMs = lastProgressMs > 0
    ? Math.max(Number(effTurn?.idle_for_ms) || 0, refNow - lastProgressMs)
    : (Number(effTurn?.idle_for_ms) || 0);
  const totalTip = elapsedMs > 0 ? word(lang, 'pmTurnTotalTip', formatTurnDuration(elapsedMs)) : '';

  const act = (v2Turn?.activity && typeof v2Turn.activity === 'object' ? v2Turn.activity : null)
    || (effTurn?.activity && typeof effTurn.activity === 'object' ? effTurn.activity : null);
  const isToolPhase = effPhase === 'tool'
    || (!v2Turn && Boolean(act && (act.kind === 'tool' || (!act.kind && (act.tool || act.summary)))));
  const rawSummary = isToolPhase ? String(act?.summary || act?.tool || '').trim() : '';
  const detail = clipSingleLine(rawSummary, 52);
  const preamble = clipSingleLine(act?.preamble || '', 80);

  // FS-13: Trust backend `stalled` / `slow` / `suspect` strictly; never extrapolate past thresholds locally.
  const stalled = Boolean(effHealth === 'stalled' || effTurn?.stalled || effPhase === 'stalled');
  const suspect = !stalled && effHealth === 'suspect';
  const slow = !stalled && !suspect && Boolean(effHealth === 'slow' || effTurn?.slow);

  // §3.9 Row 12: `health: stalled` -> Unresponsive <dur> (<evidence>) + interrupt, rotate, openTerminal.
  if (stalled) {
    const dur = formatTurnDuration(idleForMs);
    const evidence = stallEvidenceLabel(lang, v2Turn?.health_reason, detail);
    return {
      ...base,
      active: true,
      mode: 'stalled',
      label: word(lang, 'pmTurnStalledEvidence', dur, evidence),
      preamble,
      tooltip: totalTip,
      tone: 'stalled',
      stalled: true,
      canInterrupt: true,
      canRotate: true,
      canOpenTerminal: true,
      activityShort: detail ? word(lang, 'pmBusyActRunning', clipSingleLine(rawSummary, 32)) : word(lang, 'pmBusyActThinking'),
    };
  }

  // §3.9 Row 9: `waiting_upstream` -> Model service retrying (attempt N) + interrupt.
  if (effPhase === 'waiting_upstream') {
    const attempt = extractRetryAttempt(act, v2Turn?.health_reason);
    return {
      ...base,
      active: true,
      mode: 'waiting_upstream',
      label: word(lang, 'pmTurnRetrying', attempt),
      preamble,
      tooltip: totalTip,
      tone: 'neutral',
      slow: true,
      canInterrupt: true,
      activityShort: word(lang, 'pmBusyActRetrying'),
    };
  }

  // §3.9 Rows 6, 7, 8: `tool` phase (ok / slow / suspect). Duration is THIS command's duration!
  if (isToolPhase) {
    const cmdSinceMs = Number(act?.since_ms) || (v2Turn ? phaseSinceMs : 0) || startedMs;
    const cmdElapsedMs = v2Turn
      ? (cmdSinceMs > 0 ? Math.max(0, refNow - cmdSinceMs) : elapsedMs)
      : (slow ? idleForMs : elapsedMs);
    const cmdDur = formatTurnDuration(cmdElapsedMs);
    const actShort = detail ? word(lang, 'pmBusyActRunning', clipSingleLine(rawSummary, 32)) : word(lang, 'pmBusyActThinking');
    if (suspect) {
      return {
        ...base,
        active: true,
        mode: 'suspect',
        label: word(lang, 'pmTurnToolSuspect', detail),
        preamble,
        tooltip: totalTip,
        tone: 'neutral',
        slow: true,
        canInterrupt: true,
        canOpenTerminal: true,
        activityShort: actShort,
      };
    }
    if (slow) {
      return {
        ...base,
        active: true,
        mode: 'slow',
        label: word(lang, 'pmTurnToolSlow', detail, cmdDur),
        preamble,
        tooltip: totalTip,
        tone: 'neutral',
        slow: true,
        canInterrupt: true,
        canOpenTerminal: true,
        activityShort: actShort,
      };
    }
    return {
      ...base,
      active: true,
      mode: 'working',
      label: detail ? word(lang, 'pmTurnTool', detail, cmdDur) : word(lang, 'pmTurnThinking', cmdDur),
      preamble,
      tone: 'neutral',
      canInterrupt: true,
      activityShort: actShort,
    };
  }

  // §3.9 Row 5: `generating`, `slow` -> Writing a long piece · <dur> (neutral color, interrupt).
  if (slow) {
    const dur = formatTurnDuration(idleForMs);
    return {
      ...base,
      active: true,
      mode: 'slow',
      label: word(lang, 'pmTurnLongGen', dur),
      preamble,
      tooltip: totalTip,
      tone: 'neutral',
      slow: true,
      canInterrupt: true,
      activityShort: word(lang, 'pmBusyActLongGen'),
    };
  }

  // §3.9 Rows 3 & 4: `generating`, `ok` (< 3s -> dots + interrupt; >= 3s or preamble -> preamble/Thinking · dur + interrupt).
  const genDurMs = v2Turn && phaseSinceMs > 0 ? Math.max(0, refNow - phaseSinceMs) : elapsedMs;
  if (genDurMs < 3000 && !preamble) {
    return {
      ...base,
      active: true,
      mode: 'dots',
      label: '',
      preamble: '',
      tone: 'neutral',
      canInterrupt: true,
      activityShort: word(lang, 'pmBusyActThinking'),
    };
  }
  const dur = formatTurnDuration(genDurMs);
  return {
    ...base,
    active: true,
    mode: 'working',
    label: preamble ? word(lang, 'pmTurnPreamble', preamble, dur) : word(lang, 'pmTurnThinking', dur),
    preamble,
    tone: 'neutral',
    canInterrupt: true,
    activityShort: preamble ? clipSingleLine(preamble, 36) : word(lang, 'pmBusyActThinking'),
  };
}

// Pure view-model for the compact busy-coordinator bar above the main composer (§3.8 O-e, D3).
// Shown only when the coordinator is busy AND there is either an unsent draft in the composer
// or at least one queued/waiting user message (client pending queue or server mailbox).
export function pmBusyComposerView(lang, {
  actView = null,
  turn2 = null,
  working = false,
  interrupting = false,
  agentKind = '',
  hasDraft = false,
  queuedCount = 0,
} = {}) {
  const mode = String(actView?.mode || '');
  const busy = Boolean(
    actView?.active
    && !actView?.unknown
    && mode !== 'idle'
    && mode !== 'blocked'
    && mode !== 'recovering'
    && (actView?.canInterrupt || working)
  );
  if (!busy) return null;
  const inboxQueued = Array.isArray(turn2?.inbox)
    ? turn2.inbox.filter(row => {
      if (!row || typeof row !== 'object' || row.kind !== 'user') return false;
      const st = String(row.state || 'accepted').toLowerCase();
      return st === 'accepted' || st === 'typed';
    }).length
    : 0;
  const totalQueued = Math.max(0, Number(queuedCount) || 0) + inboxQueued;
  const draft = Boolean(hasDraft);
  if (!draft && totalQueued === 0) return null;
  const resolvedKind = String(turn2?.session?.agent_kind || agentKind || '').trim().toLowerCase();
  const steers = resolvedKind ? agentSteersMidTurn(resolvedKind) : Boolean(actView?.steersMidTurn);
  const timing = word(lang, steers ? 'pmBusyTimingStep' : 'pmBusyTimingTurn');
  const activity = String(actView?.activityShort || '').trim() || word(lang, 'pmBusyActThinking');
  return {
    text: draft
      ? word(lang, 'pmBusyComposer', activity, timing)
      : word(lang, 'pmBusyComposerQueued', activity, timing, totalQueued),
    actionLabel: word(lang, interrupting ? 'interruptingPmTip' : (draft ? 'pmPreemptAction' : 'pmPreemptQueuedAction')),
    steersMidTurn: steers,
    interrupting: Boolean(interrupting),
    hasDraft: draft,
    queuedCount: totalQueued,
  };
}

// Human-readable bilingual label for why `pm.py project send` returned `status: "queued"` (MSG-5, §3.9).
export function queuedReasonText(lang, reason = '') {
  const raw = String(reason || '').trim();
  if (!raw) return '';
  const low = raw.toLowerCase();
  if (low === 'starting') return word(lang, 'queuedReasonStarting');
  if (low === 'inflight' || low === 'typing') return word(lang, 'queuedReasonInflight');
  if (low === 'fifo') return word(lang, 'queuedReasonFifo');
  if (low === 'waiting_quiet_or_draft') return word(lang, 'queuedReasonDraft');
  if (low === 'blocked_prompt' || low === 'pm is blocked') return word(lang, 'queuedReasonBlocked');
  if (low === 'pm is error') return word(lang, 'queuedReasonError');
  if (low === 'pm_working' || low === 'blackbox_cooldown' || low === 'mid_turn_buffered' || low === 'held') {
    return word(lang, 'queuedReasonWorking');
  }
  if (low === 'endpoint_gone' || low === 'no_endpoint') return word(lang, 'queuedReasonOffline');
  if (low === 'machine_disconnected') return word(lang, 'queuedReasonDisconnected');
  if (low === 'timeout_uncertain') return word(lang, 'queuedReasonTimeout');
  // The mailbox's own codes (pmlib/messaging, events/supervisor): never shown raw under a message.
  if (low === 'waiting_turn_leave_working') return word(lang, 'queuedReasonWorking');
  if (low === 'epoch_requeued') return word(lang, 'queuedReasonNewSession');
  if (low === 'typist_busy') return word(lang, 'queuedReasonTypist');
  if (low === 'migrated_inflight' || low === 'migrated_outbox' || low === 'recovered') return word(lang, 'queuedReasonCarried');
  if (low === 'retry_unstarted') return word(lang, 'queuedReasonRetryUnstarted');
  if (low === 'retry_after_interrupted') return word(lang, 'queuedReasonRetryInterrupted');
  if (low === 'retry_after_errored') return word(lang, 'queuedReasonRetryErrored');
  if (low === 'unsupported') return word(lang, 'queuedReasonUnsupported');
  if (low === 'turn_interrupted') return word(lang, 'turnInterrupted');
  if (low === 'turn_errored') return word(lang, 'turnErrored');
  const dialog = classifyPmDialog('', raw, '');
  if (dialog?.labelKey) return word(lang, dialog.labelKey);
  // Any other bare code (lower_snake_case) is internal: say it waits, not what the code is called. Words (an hc
  // error message) are shown as they are.
  if (/^[a-z0-9_.:-]+$/.test(raw) && !/\s/.test(raw)) return word(lang, 'queuedReasonOther');
  return raw;
}

// §3.9 bubble states: where a logged user message is in the PM's mailbox, as the thin line under it.
// sending → queued (why) → delivered, waiting for it to finish this step / this turn → read → (gone once
// answered: the reply is right below). Only `failed` is red. `pmWorking`/`steersMidTurn` pick the delivered
// wording: an agent that reads mid-turn (Claude Code) reads it after the current step, one that does not (agy)
// after the turn.
export function bubbleLifecycleView(lang, item = {}, { pmWorking = false, steersMidTurn = true } = {}) {
  const state = String(item?.state || 'accepted').toLowerCase();
  const reason = String(item?.hold_reason || item?.reason || item?.queuedReason || '').trim();
  if (state === 'failed') {
    const detail = queuedReasonText(lang, String(item?.last_error || reason || ''));
    return { state: 'failed', label: detail ? `${word(lang, 'bubbleStateFailed')}: ${detail}` : word(lang, 'bubbleStateFailed'), failed: true };
  }
  if (state === 'answered' || state === 'superseded' || state === 'expired') {
    return { state: 'answered', label: word(lang, 'bubbleStateAnswered'), settled: true };
  }
  if (state === 'consumed') {
    return { state: 'consumed', label: word(lang, 'bubbleStateConsumed'), read: true };
  }
  if (state === 'typed') {
    const key = pmWorking ? (steersMidTurn ? 'bubbleStateTypedStep' : 'bubbleStateTypedTurn') : 'bubbleStateTyped';
    return { state: 'typed', label: word(lang, key), typed: true };
  }
  const detail = queuedReasonText(lang, reason);
  if (reason.toLowerCase() === 'waiting_quiet_or_draft') {
    return { state: 'queued', label: detail, queued: true, hasDraft: true };
  }
  if (item?.sending) {
    return { state: 'sending', label: word(lang, 'bubbleStateSending'), sending: true };
  }
  return {
    state: 'queued',
    label: detail ? `${word(lang, 'bubbleStateAccepted')} · ${detail}` : word(lang, 'bubbleStateAccepted'),
    queued: true,
    hasDraft: false,
  };
}

// The line under a logged user message (`item.delivery` from `timeline`), worded for the PM's agent kind.
export function deliveryLineView(lang, delivery, { pmWorking = false, agentKind = '' } = {}) {
  if (!delivery || typeof delivery !== 'object') return null;
  const view = bubbleLifecycleView(lang, delivery, {
    pmWorking: Boolean(pmWorking),
    steersMidTurn: agentKind ? agentSteersMidTurn(agentKind) : true,
  });
  return view.settled ? null : view;
}

// The mailbox rows (`turn2.inbox`) of user messages by msg_id, for `timeline({ inbox })`.
export function inboxByMsgId(inbox) {
  const map = new Map();
  for (const row of Array.isArray(inbox) ? inbox : []) {
    if (!row || typeof row !== 'object' || row.kind !== 'user') continue;
    const id = String(row.id || '').trim();
    if (id) map.set(id, row);
  }
  return map;
}

// A cheap signature of the rows that change what the timeline shows (cache key in resolveTimelineData).
export function inboxSignature(inbox) {
  let sig = '';
  for (const row of Array.isArray(inbox) ? inbox : []) {
    if (!row || row.kind !== 'user') continue;
    sig += `\x1e${row.id || ''}\x1f${row.state || ''}\x1f${row.hold_reason || row.reason || ''}\x1f${row.sending ? 1 : 0}`;
  }
  return sig;
}

// Format bilingual user-visible feedback for interrupt / rotate recovery actions (RS-1).
export function formatPmActionFeedback(lang, action, { code = 0, stdout = '', stderr = '', error = '' } = {}) {
  const act = action === 'rotate' ? 'rotate' : 'interrupt';
  const errText = String(error || '').trim() || (code !== 0 ? (String(stderr || stdout || '').trim() || `exit ${code}`) : '');
  if (errText) {
    return {
      tone: 'error',
      text: word(lang, act === 'rotate' ? 'rotateFailed' : 'interruptFailed', errText),
    };
  }
  if (act === 'rotate') {
    return { tone: 'info', text: word(lang, 'rotateSucceeded') };
  }
  let parsed = null;
  const out = String(stdout || '').trim();
  if (out.startsWith('{')) {
    try { parsed = JSON.parse(out); } catch (_) { parsed = null; }
  }
  const outcome = String(parsed?.outcome || 'unknown').toLowerCase();
  if (outcome === 'stopped') return { tone: 'info', text: word(lang, 'interruptStopped') };
  if (outcome === 'still_working') return { tone: 'warn', text: word(lang, 'interruptStillWorking') };
  if (outcome === 'exited') return { tone: 'warn', text: word(lang, 'interruptExited') };
  return { tone: 'info', text: word(lang, 'interruptUnknown') };
}

// Bounded async gate preventing hung HostModule `exec` Promises (e.g. across layout switches or dropped
// remote sockets) from locking `refresh` / `readLog` / `flushQueue` forever.
export function createAsyncGate() {
  return { busy: false, seq: 0, deadlineAt: 0, again: false };
}

export function tryEnterAsyncGate(gate, nowMs, timeoutMs) {
  const g = gate || createAsyncGate();
  if (g.busy && nowMs < g.deadlineAt) {
    g.again = true;
    return 0;
  }
  g.busy = true;
  g.again = false;
  g.seq = (g.seq || 0) + 1;
  g.deadlineAt = nowMs + Math.max(1000, Number(timeoutMs) || 15000);
  return g.seq;
}

export function finishAsyncGate(gate, token) {
  if (!gate || gate.seq !== token) return false;
  gate.busy = false;
  gate.deadlineAt = 0;
  const rerun = Boolean(gate.again);
  gate.again = false;
  return rerun;
}

// Identity of the active agent session inside `pmTerm` (e.g. `fg:<pid>` for the child agent process
// inside `pm.py seat`), returning '' while `pm.py seat` transiently holds the TTY between sessions.
// The foreground pid is the agent itself for its whole session: measured 2026-11-22 with `hc get`
// sampled every 0.3s, Claude Code, Codex and pi run their tools (Bash, `!` commands) with no
// controlling tty in a process group of their own, so a running tool never shows as a new session.
export function pmSessionKey(pmTerm, pm = null) {
  if (!pmTerm) return '';
  if (pmTerm.sessionId) return String(pmTerm.sessionId);
  const fgPid = Number(pmTerm.foreground?.pid) || 0;
  const rootPid = Number(pmTerm.pid) || 0;
  if (fgPid > 0) {
    if (rootPid > 0 && fgPid === rootPid && pmTerm.labels?.['pm.seat']) return '';
    const fgArgv = Array.isArray(pmTerm.foreground?.argv) ? pmTerm.foreground.argv.map(String) : [];
    const isSeatWrapper = fgArgv.some((a, i) =>
      /(?:^|[\\/])pm\.py$/i.test(a) && (fgArgv[i + 1] === 'seat' || (fgArgv[i + 1] === '--home' && fgArgv[i + 3] === 'seat')));
    if (isSeatWrapper) return '';
    return `fg:${fgPid}`;
  }
  const sid = pm?.agent_session?.id || pm?.session;
  return sid ? `sid:${sid}` : '';
}

const PM_NON_SWAP_NOTICE_RE = /rotation was cancelled|current session stays|was resumed in the PM seat|已取消这次轮换|保留当前会话|恢复原来的[\s\S]{0,40}会话/i;
const PM_SWAP_NOTICE_RE = /PM session swapped|fresh PM session was started|PM\s*会话已切换|重开新会话/i;
export function isPmSessionSwapNotice(event) {
  if (!event || event.type !== 'pm' || !event.notice) return false;
  if (event.swapped === false || event.cancelled || event.resumed) return false;
  if (event.swapped === true) return true;
  const text = String(event.text || '');
  if (!text || PM_NON_SWAP_NOTICE_RE.test(text)) return false;
  return PM_SWAP_NOTICE_RE.test(text);
}

function noticeTargetAddr(by) {
  const raw = String(by || '').trim();
  if (!raw || raw === 'user' || raw.startsWith('pm.py')) return '';
  return raw.startsWith('hc:') ? raw.slice(3) : raw;
}

// Whether the PM terminal can accept a new message right now (not blocked on a dialog or error).
export function pmCanReceive(status) {
  return status !== 'blocked' && status !== 'error';
}

// Whether a send failure is transient (PM terminal blocked on a dialog, unsent terminal draft,
// timeout or core restart) so the message should stay queued and deliver automatically once ready.
const DIALOG_OR_DRAFT_SEND_RE = /\bis blocked\b|\bunsent draft\b|\bhas a draft\b|\bwaiting for\b.*\bdraft\b/i;
const QUEUEABLE_SEND_RE = /\bis blocked\b|\bunsent draft\b|\bhas a draft\b|\bwaiting for\b.*\bdraft\b|\btimed out\b|\btimeout\b|\btook longer than\b[\s\S]*\band was stopped\b|\bcore is restarting\b|\bunavailable\b|\bstill_working\b/i;
const PERMANENT_SEND_RE = /\bnot found\b|\bno such terminal\b|\bexited\b|\bfinished\b|\bgone\b|\bis offline\b/i;
export function isDialogOrDraftSendError(error) {
  if (!error || error.upload) return false;
  const msg = String(typeof error === 'string' ? error : error.message || error);
  return Boolean(msg) && !PERMANENT_SEND_RE.test(msg) && DIALOG_OR_DRAFT_SEND_RE.test(msg);
}
export function isTargetGoneSendError(error) {
  if (!error || error.upload) return false;
  const msg = String(typeof error === 'string' ? error : error.message || error);
  return Boolean(msg) && PERMANENT_SEND_RE.test(msg);
}
export function isQueueableSendError(error) {
  if (!error || error.upload) return false;
  const msg = String(typeof error === 'string' ? error : error.message || error);
  if (!msg || PERMANENT_SEND_RE.test(msg)) return false;
  return QUEUEABLE_SEND_RE.test(msg);
}

export const SEND_CONFIRM_IDLE_MS = 12_000;
export const SEND_CONFIRM_REMOTE_IDLE_MS = 20_000;
export const SEND_INFLIGHT_STUCK_MS = 35_000;
export const SEND_INFLIGHT_REMOTE_UPLOAD_MS = 150_000;
export const PM_SWAP_WAIT_MS = 25_000;
export const RESEND_VERIFY_WAIT_MS = 15_000;
// Which conversation log a read was of: the machine, the log's path and the project's slug.
export function logKey(machine, path, slug) {
  return path && slug ? `${machine || ''}\n${path}\n${slug}` : '';
}

// Receipt timestamp in ms: prefers `at_ms` written by the PM hook, falls back to UTC-calibrated `at`.
export function receiptTime(r, clockOffsetMs = 0) {
  if (!r || typeof r !== 'object') return 0;
  const ms = Number(r.at_ms);
  if (Number.isFinite(ms) && ms > 0) return ms;
  return eventTimeUtcMs(r, clockOffsetMs);
}

// Unicode code-point count matching Python's `len(str)` (astral chars/emoji count as 1, not 2 UTF-16 units).
export function codePointLength(str) {
  let n = 0;
  for (const _ of String(str || '')) n++;
  return n;
}

// Whether a PM receipt (written at UserPromptSubmit before conversation.jsonl) matches a sent bubble.
export function sameReceiptMessage(receipt, sent) {
  if (!receipt || typeof receipt !== 'object') return false;
  const rText = String(receipt.text ?? '');
  if (!rText) return false;
  if (!receipt.truncated) return sameMessage(rText, sent);
  const normSent = squash(sent);
  const normRec = squash(rText);
  if (normSent.startsWith(normRec) && (!receipt.len || codePointLength(normSent) === Number(receipt.len))) return true;
  return splitMessage(sent).files.length > 0 && wordsOf(sent).startsWith(wordsOf(rText));
}

// Project `turn2.inbox` entries (`consumed` / `answered` `chat.user` items) into synthetic PM receipts
// so UserPromptSubmit / consumption confirms bubbles immediately without relying on `receipts.json`.
export function receiptsFromTurn2Inbox(turn2) {
  const inbox = Array.isArray(turn2?.inbox) ? turn2.inbox : [];
  const out = [];
  for (const item of inbox) {
    if (!item || typeof item !== 'object') continue;
    if (item.kind !== 'user') continue;
    if (item.state !== 'consumed' && item.state !== 'answered') continue;
    const msgId = String(item.id || '').trim();
    if (!msgId) continue;
    const rawMs = Number(item.consumed_ms || item.answered_ms || item.typed_ms || item.accepted_ms || 0);
    out.push({
      msg_id: msgId,
      at_ms: Number.isFinite(rawMs) && rawMs > 0 ? rawMs : 0,
      from_inbox: true,
    });
  }
  return out;
}

// Merge receipts from `turn2.inbox`, `pm.py state`, and `pm.py project events`, deduplicating identical entries.
export function mergeReceipts(a = [], b = []) {
  const out = [];
  const seen = new Set();
  for (const list of [a, b]) {
    if (!Array.isArray(list)) continue;
    for (const r of list) {
      if (!r || typeof r !== 'object') continue;
      const key = r.msg_id ? `id:${r.msg_id}` : `${receiptTime(r)}\0${r.digest || r.text || ''}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(r);
    }
  }
  return out;
}

// Indices of receipts already accounted for by logged `user` events in `events`, so a newly sent
// duplicate-text message cannot falsely match an earlier message's already-settled receipt.
export function settledReceiptIndices(receipts = [], events = [], { clockOffsetMs = 0 } = {}) {
  const used = new Set();
  if (!Array.isArray(receipts) || !receipts.length || !Array.isArray(events) || !events.length) return used;
  const usedEvents = new Set();
  for (let ei = 0; ei < events.length; ei++) {
    const e = events[ei];
    if (!e || e.type !== 'user') continue;
    const eMs = eventTimeUtcMs(e, clockOffsetMs);
    for (let i = 0; i < receipts.length; i++) {
      if (used.has(i)) continue;
      const r = receipts[i];
      if (!r || typeof r !== 'object') continue;
      if (e.msg_id && (r.msg_id === e.msg_id || (Array.isArray(r.msg_ids) && r.msg_ids.includes(e.msg_id)))) {
        used.add(i);
        usedEvents.add(ei);
        if (r.msg_id) break;
        continue;
      }
      if (!(eMs > 0) || !sameReceiptMessage(r, e.text)) continue;
      const rMs = receiptTime(r, clockOffsetMs);
      if (!(rMs > 0)) continue;
      const rSecMs = Math.floor(rMs / 1000) * 1000;
      if (eMs >= rSecMs - 2000 && eMs <= rMs + 60_000) {
        used.add(i);
        usedEvents.add(ei);
        break;
      }
    }
  }
  // Also deduct coalesced receipts accounted for by 2+ consecutive individual user events in `events`.
  const unconsumedUserEvents = events
    .map((e, ei) => ({ e, ei }))
    .filter(({ e, ei }) => e?.type === 'user' && !usedEvents.has(ei))
    .map(({ e }) => ({ text: e.text, atMs: eventTimeUtcMs(e, clockOffsetMs) }));
  if (unconsumedUserEvents.length >= 2) {
    for (let i = 0; i < receipts.length; i++) {
      if (used.has(i)) continue;
      const r = receipts[i];
      if (!r || typeof r !== 'object' || !String(r.text || '').includes('\n')) continue;
      const rMs = receiptTime(r, clockOffsetMs);
      if (!(rMs > 0)) continue;
      const rSecMs = Math.floor(rMs / 1000) * 1000;
      const elig = unconsumedUserEvents.filter(u => u.atMs >= rSecMs - 10_000 && u.atMs <= rMs + 60_000);
      if (elig.length >= 2 && matchCoalescedBubbles(r.text, elig, { truncated: Boolean(r.truncated) })) {
        used.add(i);
      }
    }
  }
  return used;
}

// Find the first unused PM receipt that confirms `bubble` was received at or after `bubble.sentAt`.
export function findReceiptMatch(bubble, receipts = [], used = null, { clockOffsetMs = 0 } = {}) {
  if (!bubble || !Array.isArray(receipts) || !receipts.length) return null;
  const sentAt = Number(bubble.sentAt) || 0;
  for (let i = 0; i < receipts.length; i++) {
    if (used?.has(i)) continue;
    const r = receipts[i];
    if (!r || typeof r !== 'object') continue;
    const causalHit = bubbleMatchesCausalId(bubble, r);
    if (!causalHit && hasDifferentCausalId(bubble, r)) continue;
    if (!causalHit && !sameReceiptMessage(r, bubble.text)) continue;
    const hasMs = Number.isFinite(Number(r.at_ms)) && Number(r.at_ms) > 0;
    const rMs = hasMs ? Number(r.at_ms) : eventTimeUtcMs(r, clockOffsetMs);
    if (!causalHit && sentAt > 0) {
      const minAt = hasMs ? sentAt : Math.floor(sentAt / 1000) * 1000;
      if (!(rMs >= minAt)) continue;
    }
    if (used && (!Array.isArray(r.msg_ids) || r.msg_ids.length <= 1)) used.add(i);
    return { index: i, receipt: r, atMs: rMs };
  }
  return null;
}

// Confirm 2+ queued/delivered pending bubbles that an agent coalesced into a single `\n`-joined receipt.
export function findCoalescedReceiptMatches(bubbles = [], receipts = [], used = null, { clockOffsetMs = 0 } = {}) {
  const hits = new Map();
  if (!Array.isArray(bubbles) || bubbles.length < 2 || !Array.isArray(receipts) || !receipts.length) return hits;
  for (let i = 0; i < receipts.length; i++) {
    if (used?.has(i)) continue;
    const r = receipts[i];
    if (!r || typeof r !== 'object' || !String(r.text || '').includes('\n')) continue;
    const hasMs = Number.isFinite(Number(r.at_ms)) && Number(r.at_ms) > 0;
    const rMs = hasMs ? Number(r.at_ms) : eventTimeUtcMs(r, clockOffsetMs);
    const eligible = bubbles.filter(b => {
      if (!b || hits.has(b) || b.received || b.upload || (b.failed && !b.timedOut) || (b.queued && !b.requeuedFromSend && !b.serverQueued)) return false;
      if (hasDifferentCausalId(b, r)) return false;
      const sentAt = Number(b.sentAt) || 0;
      if (sentAt <= 0) return true;
      const minAt = hasMs ? sentAt : Math.floor(sentAt / 1000) * 1000;
      return rMs >= minAt;
    });
    if (eligible.length < 2) continue;
    const group = matchCoalescedBubbles(r.text, eligible, { truncated: Boolean(r.truncated) });
    if (group && group.length >= 2) {
      if (used) used.add(i);
      for (const b of group) hits.set(b, { index: i, receipt: r, atMs: rMs });
    }
  }
  return hits;
}

// Transition a pending/failed/verifying bubble to receipt-confirmed: stays visible until
// conversation.jsonl catches up and settles it, but never shows "Sending…", never fails, and
// can never be re-sent.
export function confirmReceiptBubble(p, atMs = 0, now = Date.now()) {
  return {
    ...p,
    received: true,
    receiptAt: Number(atMs) > 0 ? Number(atMs) : (Number(p.receiptAt) || now),
    queued: false,
    inFlight: false,
    inFlightAt: 0,
    inFlightTo: '',
    inFlightSession: '',
    verifying: false,
    verifySince: 0,
    failed: '',
    failedAt: 0,
    timedOut: false,
    unsure: false,
    deliveredAt: 0,
    idleSince: 0,
    swapDetectedAt: 0,
    swapWaitSince: 0,
  };
}

// Reconcile pending user bubbles against conversation events, PM receipts, PM session/terminal swaps, and
// delivery confirmation timeouts:
// - Logged `user` events settle matching bubbles (including bubbles previously marked `timedOut` or `received`,
//   so a late log write never leaves a duplicate failed bubble beside the real message).
// - `turn2.inbox` (`consumed` / `answered` items, with 1-version `receipts` compatibility fallback)
//   immediately confirms matching bubbles (`received: true`), preventing timeout/swap requeue/manual resend
//   duplicates even when `conversation.jsonl` has not flushed or refreshed yet.
// - Unconfirmed bubbles sent to a PM terminal/session that swapped before logging re-queue for the
//   new PM once `logReady` confirms the outgoing PM did not write them to `conversation.jsonl`.
// - Unconfirmed bubbles wait while the PM is actively working on a foreground turn (e.g. queued in
//   Claude Code's input buffer during a long turn), and mark `failed` (`timedOut: true`) only once
//   the PM has been idle for `confirmIdleMs` without logging receipt.
// - Bubbles queued while waiting for a vanished PM terminal fail cleanly if no replacement PM
//   comes online within `PM_SWAP_WAIT_MS`.
// - A timed-out bubble the user asked to resend is `verifying` first: it goes out again only once
//   a log read that started after the click (`logFreshFrom >= verifySince`) still lacks both a logged
//   event and a PM receipt; when either has it, nothing is sent twice. A log that cannot be read within
//   RESEND_VERIFY_WAIT_MS does not hold the resend the user asked for.
export function reconcilePendingSends(pending, events = [], {
  now = Date.now(),
  pmAddress = '',
  pmSession = '',
  pmWorking = false,
  pmStarting = false,
  flushingQueue = false,
  logReady = true,
  remote = false,
  lang = 'en',
  logFreshFrom = 0,
  receipts = [],
  turn2 = null,
  clockOffsetMs = 0,
  confirmIdleMs = remote ? SEND_CONFIRM_REMOTE_IDLE_MS : SEND_CONFIRM_IDLE_MS,
  swapWaitMs = PM_SWAP_WAIT_MS,
} = {}) {
  const base = settlePending(pending, events, { clockOffsetMs });
  if (!base?.length) {
    return { pending: base, settled: (pending || []).filter(p => !base?.includes(p)), confirmed: [], requeued: [], failed: [], needsFollowup: false };
  }
  const settled = (pending || []).filter(p => !base.includes(p));
  const confirmed = [];
  const requeued = [];
  const failed = [];
  const inboxReceipts = receiptsFromTurn2Inbox(turn2);
  const receiptList = inboxReceipts.length
    ? mergeReceipts(inboxReceipts, receipts)
    : (Array.isArray(receipts) ? receipts : []);
  const usedReceipts = settledReceiptIndices(receiptList, events, { clockOffsetMs });
  if (receiptList.length > 0) {
    for (const p of base) {
      if (p?.received) findReceiptMatch(p, receiptList, usedReceipts, { clockOffsetMs });
    }
  }
  const coalescedHits = receiptList.length > 0
    ? findCoalescedReceiptMatches(base, receiptList, usedReceipts, { clockOffsetMs })
    : new Map();
  let changed = base !== pending;
  let needsFollowup = false;

  const next = base.map(p => {
    if (!p) return p;
    if (p.received) return p;

    // Receipt confirmation: if PM already recorded receipt for this sent bubble, confirm it at once
    // and never time out, swap-requeue, or resend (even if conversation.jsonl has not caught up yet).
    // Never swallow unsent queued bubbles or non-timeout send failures (`pm.py project send` exited non-zero).
    const canConfirmByReceipt = !p.upload && !(p.failed && !p.timedOut) && (!p.queued || Boolean(p.requeuedFromSend) || Boolean(p.serverQueued));
    if (canConfirmByReceipt && receiptList.length > 0) {
      const hit = coalescedHits.get(p) || findReceiptMatch(p, receiptList, usedReceipts, { clockOffsetMs });
      if (hit) {
        changed = true;
        const updated = confirmReceiptBubble(p, hit.atMs, now);
        confirmed.push({ ...updated, wasTimedOut: Boolean(p.timedOut), wasFailed: Boolean(p.failed) });
        return updated;
      }
    }

    if (p.failed) return p;

    // 0. Resend asked for a timed-out bubble: the log was not in it (settlePending above), so send.
    if (p.verifying) {
      const since = Number(p.verifySince) || 0;
      if ((logReady && logFreshFrom > 0 && logFreshFrom >= since) || now - since >= RESEND_VERIFY_WAIT_MS) {
        changed = true;
        const updated = {
          ...p,
          verifying: false,
          verifySince: 0,
          queued: true,
          inFlight: false,
          requeuedFromSend: true,
          deliveredAt: 0,
          idleSince: 0,
          sentTo: '',
          sentSession: '',
          unsure: false,
          attempts: 0,
        };
        requeued.push(updated);
        return updated;
      }
      needsFollowup = true;
      return p;
    }

    // 1. Queued bubble waiting for a replacement PM terminal after the previous PM vanished.
    if (p.queued) {
      if (p.swapWaitSince > 0) {
        if (pmAddress) {
          changed = true;
          return { ...p, swapWaitSince: 0 };
        }
        if (pmStarting) {
          needsFollowup = true;
          if (p.swapWaitSince !== now) {
            changed = true;
            return { ...p, swapWaitSince: now };
          }
          return p;
        }
        if (now - p.swapWaitSince >= swapWaitMs) {
          changed = true;
          const updated = {
            ...p,
            queued: false,
            inFlight: false,
            swapWaitSince: 0,
            failed: p.lastError || word(lang, 'pmOfflineFailed'),
            failedAt: now,
          };
          failed.push(updated);
          return updated;
        }
        needsFollowup = true;
      }
      return p;
    }

    // 2. Orphaned inFlight safety net (e.g. an unexpected host throw or dropped Promise skipped deliverBubble cleanup).
    if (p.inFlight) {
      const started = Number(p.inFlightAt) || Number(p.sentAt) || 0;
      const limit = remote && p.files?.length ? SEND_INFLIGHT_REMOTE_UPLOAD_MS : SEND_INFLIGHT_STUCK_MS;
      const hardLimit = limit + 15_000;
      if (started > 0 && !pmWorking && ((!flushingQueue && now - started >= limit) || now - started >= hardLimit)) {
        changed = true;
        const updated = {
          ...p,
          queued: false,
          inFlight: false,
          inFlightAt: 0,
          failed: word(lang, 'unsureSend'),
          failedAt: now,
          timedOut: true,
        };
        failed.push(updated);
        return updated;
      }
      if (started > 0) needsFollowup = true;
      return p;
    }

    // 3. Sent (`pm.py project send` exited 0), awaiting `user` event confirmation in `conversation.jsonl`.
    const deliveredAt = Number(p.deliveredAt) || 0;
    if (!(deliveredAt > 0)) return p;

    const terminalSwapped = Boolean(p.sentTo && pmAddress !== p.sentTo);
    const deliveredSecMs = Math.floor(deliveredAt / 1000) * 1000;
    const freshNotices = (events || []).filter(e =>
      e?.type === 'pm' && Boolean(e.notice) &&
      eventTimeUtcMs(e, clockOffsetMs) >= deliveredSecMs &&
      (!p.swapHandledAt || eventTimeUtcMs(e, clockOffsetMs) > p.swapHandledAt));
    const noticeTargetSwapped = Boolean(p.sentTo) && freshNotices.some(e => {
      const byAddr = noticeTargetAddr(e.by);
      return Boolean(byAddr && byAddr !== p.sentTo);
    });
    const hasKnownSessions = Boolean(p.sentSession && pmSession);
    const hasSwapNotice = freshNotices.some(isPmSessionSwapNotice);
    const seatSessionSwapped = hasKnownSessions
      ? p.sentSession !== pmSession
      : hasSwapNotice;

    if (terminalSwapped || noticeTargetSwapped || seatSessionSwapped) {
      if (!logReady) {
        needsFollowup = true;
        if (!p.swapDetectedAt) {
          changed = true;
          return { ...p, swapDetectedAt: now };
        }
        return p;
      }
      changed = true;
      const updated = {
        ...p,
        queued: true,
        inFlight: false,
        requeuedFromSend: true,
        deliveredAt: 0,
        sentTo: '',
        sentSession: '',
        idleSince: 0,
        swapDetectedAt: 0,
        swapHandledAt: now,
        swapWaitSince: pmAddress ? 0 : now,
        unsure: false,
        attempts: 0,
      };
      requeued.push(updated);
      if (!pmAddress) needsFollowup = true;
      return updated;
    }

    const turnEndedAfter = (events || []).some(e =>
      e?.type === 'pm' && !e.notice &&
      (!p.sentTo || !e.by || e.by === `hc:${p.sentTo}`) &&
      eventTimeUtcMs(e, clockOffsetMs) >= deliveredAt + 3000);
    const busyTurn = pmWorking && !turnEndedAfter;
    const idleSince = busyTurn ? 0 : (Number(p.idleSince) > 0 ? Number(p.idleSince) : now);
    const idleExpired = !busyTurn && idleSince > 0 && now - idleSince >= confirmIdleMs;

    if (idleExpired) {
      if (!logReady) {
        needsFollowup = true;
        if (idleSince !== (p.idleSince || 0)) {
          changed = true;
          return { ...p, idleSince };
        }
        return p;
      }
      changed = true;
      const updated = {
        ...p,
        queued: false,
        inFlight: false,
        deliveredAt: 0,
        idleSince: 0,
        failed: word(lang, p.unsure ? 'unsureSend' : 'unconfirmedSend'),
        failedAt: now,
        timedOut: true,
      };
      failed.push(updated);
      return updated;
    }

    needsFollowup = true;
    if (idleSince !== (p.idleSince || 0) || p.swapDetectedAt) {
      changed = true;
      return { ...p, idleSince, swapDetectedAt: 0 };
    }
    return p;
  });

  return {
    pending: changed ? next : base,
    settled,
    confirmed,
    requeued,
    failed,
    needsFollowup,
  };
}

// Classify why a PM terminal is currently unable to receive from its active bottom screen lines
// (never stale scrollback) and/or the latest send error. Returns `{ kind, labelKey }` or null.
const BOX_BORDER_RE = /^[\s─━═│┃╭╮╰╯┌┐└┘├┤┬┴┼]+$/;
const PM_QUOTA_RE = /(rate.?limit|quota.?exceeded|insufficient_quota|usage.?limit|hit your limit|too many requests|\b429\b|credits? exhausted|out of credits|billing limit|overloaded_error|capacity exceeded|配额|限流)/i;
const PM_AUTH_RE = /(not logged in|please log ?in|authentication failed|invalid api key|unauthorized|\b401\b|token expired|sign in to continue|login required|未登录|鉴权失败)/i;
const PM_HOOK_RE = /(hook[s]?\s+needs?\s+review|review\s+hook|new mcp server|use this mcp server|approve mcp)/i;
const PM_QUESTION_RE = /(AskUserQuestion|request_user_input|chat about this|submit answers|\bchoose 1-\d+|\benter to select\b[\s\S]{0,160}(?:↑\/↓|tab|esc|type something|arrow))/i;
const PM_PERM_RE = /(\bdo you want to (?:proceed|run|allow|execute|create|edit|delete|remove|apply)\b|\b(?:allow|approve)\s+(?:this\s+)?(?:command|tool|bash|edit|write|once)\b|\b(?:run|execute)\s+(?:this\s+)?(?:command|bash|shell)\b|\bpermission\s+required\b|\brequires?\s+(?:your\s+)?(?:approval|permission)\b)/i;
const PM_TRUST_RE = /(trust this folder|do you trust the files|trust the contents of this directory|quick safety check)/i;
const PM_UPDATE_RE = /(update available|new version available|upgrade now|skip until next version|update now)/i;

export function classifyPmDialog(screen = '', sendError = '', liveStatus = '') {
  const err = String(sendError || '');
  const lines = String(screen || '').split(/\r?\n/).map(l => l.trim()).filter(l => l && !BOX_BORDER_RE.test(l));
  const tail = lines.slice(-18).join('\n');

  if (/\bis blocked\s*\(\s*question\s*\)/i.test(err)) return { kind: 'question', labelKey: 'pmBlockedQuestion' };
  if (/\bis blocked\s*\(\s*permission\s*\)/i.test(err)) return { kind: 'permission', labelKey: 'pmBlockedPermission' };
  if (/\bis blocked\s*\(\s*auth\s*\)/i.test(err)) return { kind: 'auth', labelKey: 'pmBlockedAuth' };
  if (/\bunsent draft\b|\bhas a draft\b|\bwaiting for\b.*\bdraft\b/i.test(err)) return { kind: 'draft', labelKey: 'pmBlockedDraft' };

  if (tail) {
    if (PM_QUOTA_RE.test(tail)) return { kind: 'quota', labelKey: 'pmBlockedQuota' };
    if (PM_AUTH_RE.test(tail)) return { kind: 'auth', labelKey: 'pmBlockedAuth' };
    if (PM_HOOK_RE.test(tail)) return { kind: 'hook_review', labelKey: 'pmBlockedHook' };
    if (PM_QUESTION_RE.test(tail)) return { kind: 'question', labelKey: 'pmBlockedQuestion' };
    if (PM_PERM_RE.test(tail)) return { kind: 'permission', labelKey: 'pmBlockedPermission' };
    if (PM_TRUST_RE.test(tail)) return { kind: 'trust', labelKey: 'pmBlockedTrust' };
    if (PM_UPDATE_RE.test(tail)) return { kind: 'update', labelKey: 'pmBlockedUpdate' };
  }

  if (liveStatus === 'blocked' || liveStatus === 'error' || /\bis blocked\b/i.test(err)) {
    return { kind: 'unknown', labelKey: 'pmBlockedUnknown' };
  }
  return null;
}

export function pmBlockedBannerText(lang, dialog, queuedCount = 0) {
  if (dialog?.labelKey) {
    const base = word(lang, dialog.labelKey);
    return queuedCount > 0 ? `${base} · ${word(lang, 'queuedSummary', queuedCount)}` : base;
  }
  return queuedCount > 0 ? word(lang, 'pmQueuedOnly', queuedCount) : '';
}

// The banner over the conversation when something waits too long for the PM (`pm.undelivered` from state):
// a batch of events, and/or mailbox messages past their delivery SLA (`messages`, the `alert.undelivered`
// route's ui outlet).
export function undeliveredBannerText(lang, undelivered) {
  if (!undelivered || typeof undelivered !== 'object') return '';
  const count = Number(undelivered.count) || 0;
  const messages = Number(undelivered.messages) || 0;
  if (count <= 0 && messages <= 0) return '';
  const secs = Math.max(60, Number(undelivered.waiting_seconds) || 0);
  const dur = age(secs * 1000, lang);
  const state = String(undelivered.state || '').trim();
  const parts = [];
  if (state) parts.push(lang === 'zh' ? `状态=${state}` : `state=${state}`);
  if (undelivered.deliverer_running === false) parts.push(word(lang, 'delivererStopped'));
  const sep = lang === 'zh' ? '，' : ', ';
  const out = [];
  if (count > 0) out.push(word(lang, 'pmUndelivered', count, dur, parts.join(sep)));
  if (messages > 0) {
    const why = queuedReasonText(lang, String(undelivered.message_reason || ''));
    out.push(word(lang, 'pmUndeliveredMessages', messages, dur, (count > 0 ? [why] : [why, ...parts]).filter(Boolean).join(sep)));
  }
  return out.join(lang === 'zh' ? '；' : '; ');
}

// Persistent storage for the project composer's messages that are not settled yet
// (`localStorage[QUEUE_KEY]`), keyed by PM name, so a mod reload or app restart neither loses nor
// re-sends them. Every bubble short of failed is kept, with where it got to:
//   queued     not sent yet: delivers once the PM can receive
//   inFlight   the send had started (inFlightTo/inFlightSession: where to); whether it finished is
//              unknown after a reload, so it comes back as sent and unsure, never sent again blindly
//   delivered  the send exited 0 (deliveredAt, sentTo, sentSession): waits for the log as before
//   verifying  a resend asked for after a timeout, waiting on a fresh log read (reconcilePendingSends)
// A failed bubble is not kept: its words went back to the box's draft.
export const QUEUE_KEY = 'queued_sends';
export const QUEUE_LIMIT = 40;
export const QUEUE_PM_LIMIT = 20;

const SEND_STAGES = ['queued', 'inFlight', 'delivered', 'verifying'];
function sendStage(p) {
  if (p.received) return '';
  if (p.verifying) return 'verifying';
  if (p.inFlight) return 'inFlight';
  if (!p.queued && Number(p.deliveredAt) > 0) return 'delivered';
  return p.queued ? 'queued' : '';
}
const numOr0 = v => Number(v) > 0 ? Number(v) : 0;
// The fields of a stage, as stored and as read back.
function stageFields(stage, item) {
  if (stage === 'inFlight') {
    return { inFlightAt: numOr0(item.inFlightAt), inFlightTo: String(item.inFlightTo ?? ''), inFlightSession: String(item.inFlightSession ?? '') };
  }
  if (stage === 'delivered') {
    return { deliveredAt: numOr0(item.deliveredAt), sentTo: String(item.sentTo ?? ''), sentSession: String(item.sentSession ?? ''), ...(item.unsure ? { unsure: true } : {}) };
  }
  if (stage === 'verifying') return { verifySince: numOr0(item.verifySince) };
  return {};
}

export function readQueuedSends(text) {
  try {
    const raw = JSON.parse(text);
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
    const out = {};
    for (const [pmName, list] of Object.entries(raw)) {
      if (!pmName || !Array.isArray(list)) continue;
      const clean = [];
      for (const item of list) {
        if (!item || typeof item !== 'object') continue;
        const msg = String(item.text ?? '').trim();
        const said = String(item.said ?? item.words ?? item.text ?? '').trim();
        const files = withFiles([], item.files);
        const quotes = normalizeQuotes(item.quotes);
        if (!msg && !files.length && !quotes.length) continue;
        // Entries written before stages were kept are all queued.
        const stage = SEND_STAGES.includes(item.stage) ? item.stage : 'queued';
        clean.push({
          id: Number.isInteger(item.id) && item.id > 0 ? item.id : clean.length + 1,
          ...(item.msgId ? { msgId: String(item.msgId) } : {}),
          text: msg || messageText(said, files),
          said,
          words: String(item.words ?? '').trim(),
          to: String(item.to ?? ''),
          files,
          ...(quotes.length ? { quotes } : {}),
          sentAt: Number(item.sentAt) || 0,
          question: item.question ? String(item.question) : undefined,
          draftKey: String(item.draftKey ?? ''),
          ...(item.requeuedFromSend ? { requeuedFromSend: true } : {}),
          ...(item.serverQueued ? { serverQueued: true } : {}),
          ...(item.queuedReason ? { queuedReason: String(item.queuedReason) } : {}),
          stage,
          ...stageFields(stage, item),
          queued: stage === 'queued',
        });
      }
      if (clean.length) out[pmName] = clean.slice(-QUEUE_LIMIT);
    }
    return out;
  } catch (_) {
    return {};
  }
}

export function keepQueuedSends(stored, pmName, pending) {
  if (!pmName) return stored || {};
  const base = stored && typeof stored === 'object' && !Array.isArray(stored) ? stored : {};
  const items = (Array.isArray(pending) ? pending : [])
    .filter(p => p && !p.failed && sendStage(p))
    .slice(-QUEUE_LIMIT)
    .map(p => {
      const quotes = normalizeQuotes(p.quotes);
      const stage = sendStage(p);
      return {
        id: p.id,
        ...(p.msgId ? { msgId: String(p.msgId) } : {}),
        text: p.text,
        said: p.said ?? p.words ?? p.text,
        words: p.words ?? '',
        to: p.to ?? '',
        files: withFiles([], p.files),
        ...(quotes.length ? { quotes } : {}),
        sentAt: Number(p.sentAt) || 0,
        ...(p.question ? { question: p.question } : {}),
        draftKey: p.draftKey ?? '',
        ...(p.requeuedFromSend ? { requeuedFromSend: true } : {}),
        ...(p.serverQueued ? { serverQueued: true } : {}),
        ...(p.queuedReason ? { queuedReason: String(p.queuedReason) } : {}),
        stage,
        ...stageFields(stage, p),
        queued: stage === 'queued',
      };
    });
  const rest = { ...base };
  if (!items.length) delete rest[pmName];
  else rest[pmName] = items;
  const entries = Object.entries(rest);
  const trimmed = entries.length > QUEUE_PM_LIMIT ? Object.fromEntries(entries.slice(-QUEUE_PM_LIMIT)) : rest;
  return JSON.stringify(trimmed) === JSON.stringify(base) ? base : trimmed;
}

// The stored bubbles back as pending ones (see QUEUE_KEY), after `existing`. now: when the view came
// back. A send that was under way comes back as sent but unsure (deliveredAt: when it started), so it
// waits for the log, then times out as unsure and is resent only on a click, which checks the log
// first. Sent ones wait for the log afresh (idleSince 0). A resend being checked checks again.
export function restoreQueuedPending(saved, existing = [], now = Date.now()) {
  const cur = Array.isArray(existing) ? [...existing] : [];
  const seen = new Set(cur.map(p => p.msgId ? `id:${p.msgId}` : `${p.sentAt || 0}\n${p.text || ''}`));
  let maxId = cur.reduce((m, p) => Math.max(m, Number(p?.id) || 0), 0);
  for (const item of Array.isArray(saved) ? saved : []) {
    const sig = item.msgId ? `id:${item.msgId}` : `${item.sentAt || 0}\n${item.text || ''}`;
    if (seen.has(sig)) continue;
    seen.add(sig);
    const id = Number.isInteger(item.id) && item.id > 0 && !cur.some(p => p.id === item.id) ? item.id : ++maxId;
    maxId = Math.max(maxId, id);
    const { stage, inFlightAt, inFlightTo, inFlightSession, ...rest } = item;
    const bubble = { ...rest, id };
    if (stage === 'inFlight') {
      Object.assign(bubble, { queued: false, inFlight: false, unsure: true, idleSince: 0,
        deliveredAt: inFlightAt || Number(item.sentAt) || now, sentTo: inFlightTo || '', sentSession: inFlightSession || '' });
    } else if (stage === 'delivered') {
      Object.assign(bubble, { queued: false, inFlight: false, idleSince: 0, deliveredAt: Number(item.deliveredAt) || now });
    } else if (stage === 'verifying') {
      Object.assign(bubble, { queued: false, inFlight: false, verifying: true, verifySince: now });
    } else {
      bubble.queued = true;
    }
    cur.push(bubble);
  }
  return { pending: cur, maxId };
}

// Keys dropped (Unix `env -u`) so a send / put / reattach is not attributed to a terminal.
export const SEND_ENV = ['HC_TERMINAL_ID'];
export const REATTACH_ENV = ['HC_TERMINAL_ID', 'HERDR_PANE_ID'];

// herdr's exec has no env option ({ cwd, on, timeout } only). On Unix, wrap with `env -u KEY…` so
// HC_TERMINAL_ID / HERDR_PANE_ID are not inherited. Windows Desktop has no usable `env`, so run the
// program as-is (the app process does not set those marks). Returns [command, args] for exec.
export function withoutTerminalEnv(argv, { platform = '', unset = SEND_ENV } = {}) {
  const args = Array.isArray(argv) ? argv.filter(a => a != null).map(String) : [];
  if (!args.length) return ['hc', []];
  if (platform === 'windows') return [args[0], args.slice(1)];
  const drop = (Array.isArray(unset) ? unset : SEND_ENV).flatMap(k => ['-u', String(k)]);
  return ['env', drop.concat(args)];
}

// ---- attachments for a terminal on another machine ----------------------------------
// An attached file is a path on this computer, which an agent on another machine cannot open. So a
// message to a terminal there first sends each file beside that terminal with `hc put`: herdr-core
// carries it over the machine's own connection, it lands in that machine's
// ~/.local/state/herdr-core/<session>/files/<terminal>/ (its name kept, `-2` for a second of the same
// name) and `hc put --json` prints {path}. The message then names those paths. Here (machine ''):
// nothing to send, the files go as they are.
export function putArgv(address, path) {
  return ['hc', 'put', '--json', '--', address, path];
}
// hc put keeps a file's name, but each character outside ASCII becomes "_" ("设计稿 v2.png" landed as
// "____v2.png"). Such a file goes as a copy named here: image-<time>-<n>, or file-… for what is not an
// image, then the ASCII words of its name, then its extension ("设计稿 v2.png" → image-20261116-221514-1-v2.png).
// '' for a name that is ASCII already: it goes as it is.
export function uploadName(name, at = new Date(), n = 1) {
  name = String(name ?? '');
  if (!/[^\x20-\x7e]/.test(name)) return '';
  const dot = name.lastIndexOf('.'), ext = dot > 0 && /^[A-Za-z0-9]{1,10}$/.test(name.slice(dot + 1)) ? name.slice(dot + 1) : '';
  const words = ((ext ? name.slice(0, dot) : name).match(/[A-Za-z0-9]+/g) || []).join('-').slice(0, 32).replace(/-+$/, '');
  return `${isImage(name) ? 'image' : 'file'}-${timeStamp(at)}-${n}${words ? `-${words}` : ''}${ext ? `.${ext}` : ''}`;
}
// A file already copied to a terminal there, by the terminal's app address and the file's path here:
// the key of `uploaded`, which keeps where it landed until its message went (a send sent again after a
// later file failed does not copy it twice).
export const uploadKey = (address, machine, path) => `${onMachine(address, machine)}\n${path}`;
// For a message to the terminal `address` (as the machine sees it) on `machine`: one step per file,
// {path: the file here, key (uploadKey), and either landed: where `uploaded` says it already is there,
// or argv: putArgv for withoutTerminalEnv / exec that sends it, with copy: the renamed copy it sends
// (uploadName) in the folder `stage`, to be made first}. [] for a terminal here.
export function uploadSteps(files, address, machine = '', { uploaded = null, stage = '', at = new Date() } = {}) {
  if (!machine || !address) return [];
  const to = onMachine(address, machine);
  let n = 0;
  return withFiles([], files).map(path => {
    const key = uploadKey(address, machine, path), landed = uploaded?.get(key);
    if (landed) return { path, key, landed };
    const name = stage ? uploadName(fileName(path), at, n + 1) : '';
    if (!name) return { path, key, argv: putArgv(to, path) };
    n++;
    return { path, key, copy: `${stage}/${name}`, argv: putArgv(to, `${stage}/${name}`) };
  });
}
// Where a file landed, from `hc put --json`'s ExecResult; throws its error otherwise (the words of
// hc's {"error":{"message"}} when it printed one).
export function landedPath(result) {
  const out = String(result?.stdout ?? '').trim(), err = String(result?.stderr ?? '').trim();
  let json = null;
  for (const text of [out, err]) {
    try { json = JSON.parse(text); break; } catch (_) { /* not JSON */ }
  }
  if (result?.code === 0 && isPath(json?.path)) return json.path;
  throw new Error(json?.error?.message || err || out || `hc put: ${result?.code}`);
}
// The files of a message as they are named to the terminal: each one's landed path, else its own.
export const sentFiles = (files, landed = new Map()) => withFiles([], (files || []).map(path => landed.get(path) || path));

// What waits here for another machine, in <ledger home>/attachments/<machine>/<project> (pasteDir), is
// only kept until it went: a pasted screenshot is removed once its message was sent, and anything
// there older than a week (left by a send that never went) when something new is put there. Not what
// a box's draft or a failed bubble still holds: those are sent later.
export const STALE_MINUTES = 7 * 24 * 60;
// The files of every stored draft and every bubble still here (pending: [{files}]).
export function heldFiles(drafts, pending = []) {
  const held = new Set();
  for (const d of Object.values(drafts || {})) for (const path of d?.files || []) held.add(path);
  for (const p of pending || []) for (const path of p?.files || []) held.add(path);
  return held;
}
// Of a sent message's files, those to remove: the ones in the paste folder `dir` no box or bubble still holds.
export const sentLeftovers = (files, dir, held = new Set()) =>
  dir ? withFiles([], files).filter(path => path.startsWith(`${dir}/`) && !held.has(path)) : [];
// `find` of what is older than a week under <home>/attachments: each machine's projects' files, and a
// send's folder of renamed copies left behind (see uploadSteps).
export const staleArgv = home => ['find', `${home}/attachments`, '-mindepth', '3', '-mmin', `+${STALE_MINUTES}`];
// That find's output as paths to remove, without the held ones.
export const staleFiles = (out, held = new Set()) => String(out ?? '').split('\n').filter(path => isPath(path) && !held.has(path));

// ---- a project on another machine ------------------------------------------------
// shared('pm-project') names the project: {pm, machine?}. A remote PM is keyed "<machine>/<name>" (as
// pm-list keys its row and pm-dash names it on the board); `name` is its name in that machine's ledger.
export function projectRef(value) {
  const key = typeof value?.pm === 'string' ? value.pm : '';
  const machine = typeof value?.machine === 'string' && key.startsWith(`${value.machine}/`) ? value.machine : '';
  return { key, machine, name: machine ? key.slice(machine.length + 1) : key };
}

// What a remote project's view reads is that machine's: its ledger (`pm.py state` there), its log and
// task files, through Herdr's exec/readTextFile `on`. Its terminals and agents are shown to the rest
// of the view as that machine sees them (machineView: its own only, addresses without "<machine>/"),
// so the ledger's panes and labels match as they do at home; an address goes back out with its
// prefix (onMachine) to be focused or sent to. Local items (machine '') pass as they are.
export function machineView(items, machine = '') {
  const list = Array.isArray(items) ? items : [];
  if (!machine) return list;
  const prefix = `${machine}/`, strip = a => typeof a === 'string' && a.startsWith(prefix) ? a.slice(prefix.length) : a;
  return list.filter(x => typeof x?.address === 'string' && x.address.startsWith(prefix))
    .map(x => ({ ...x, address: strip(x.address), ...(x.parent ? { parent: strip(x.parent) } : {}) }));
}
export const onMachine = (address, machine = '') => (machine && address ? `${machine}/${address}` : address);

// A copy of pm-dash's PM_SCRIPTS (model.test.mjs checks): where pm.py lives on another machine.
export const PM_SCRIPTS = ['.config/herdr-app/mods/pm-dash/skill/scripts/pm.py', '.claude/skills/pm/scripts/pm.py',
  '.codex/skills/pm/scripts/pm.py', '.pi/agent/skills/pm/scripts/pm.py'];
// `pm.py <args>` on another machine, as exec's [command, args]: the first pm.py found there, run
// without a terminal identity (as reattachArgv); args are passed as they are, never through the shell.
export function remotePmArgv(args, scripts = PM_SCRIPTS) {
  return ['sh', ['-c', `for f in ${scripts.map(path => `"$HOME/${path}"`).join(' ')}; do ` +
    'if [ -f "$f" ]; then exec env -u HC_TERMINAL_ID -u HERDR_PANE_ID python3 "$f" "$@"; fi; done; ' +
    'echo "pm.py not found" >&2; exit 127', 'sh', ...args]];
}

export const REMOTE_PROBE_SH = [
  'printf "HOME\\t%s\\n" "$HOME"',
  'pm_found=""',
  `for rel in ${PM_SCRIPTS.join(' ')}; do if [ -f "$HOME/$rel" ]; then pm_found="$HOME/$rel"; break; fi; done`,
  'printf "PM\\t%s\\n" "$pm_found"',
  'if [ -n "$PM_HOME" ]; then ledger="$PM_HOME"; elif [ -d "$HOME/.claude/pm" ] && ! [ "$HOME/.claude/pm" -ef "$HOME/.dudu" ]; then ledger="$HOME/.claude/pm"; else ledger="$HOME/.dudu"; fi',
  'printf "LEDGER\\t%s\\n" "$ledger"',
  'for raw in "$@"; do',
  '  p="$raw"; case "$p" in "~") p="$HOME";; "~/"*) p="$HOME/${p#??}";; esac',
  '  if [ -d "$p" ]; then',
  '    resolved=$(cd "$p" 2>/dev/null && pwd -P) || resolved="$p"',
  '    is_git=0; branch=""',
  '    if command -v git >/dev/null 2>&1 && git -C "$resolved" rev-parse --is-inside-work-tree >/dev/null 2>&1; then',
  '      is_git=1; branch=$(git -C "$resolved" symbolic-ref --short HEAD 2>/dev/null || git -C "$resolved" rev-parse --short HEAD 2>/dev/null || true)',
  '    fi',
  '    printf "DIR\\t1\\t%s\\t%s\\t%s\\t%s\\n" "$raw" "$resolved" "$is_git" "$branch"',
  '  else',
  '    printf "DIR\\t0\\t%s\\t%s\\t0\\t\\n" "$raw" "$p"',
  '  fi',
  'done',
].join('\n');

export const REMOTE_LIST_DIRS_SH = [
  'target="${1:-$HOME}"',
  'case "$target" in "") target="$HOME";; "~") target="$HOME";; "~/"*) target="$HOME/${target#??}";; esac',
  'if [ ! -d "$target" ]; then parent=$(dirname "$target"); if [ -d "$parent" ]; then target="$parent"; else target="$HOME"; fi; fi',
  'cur=$(cd "$target" 2>/dev/null && pwd -P) || cur="$target"',
  'printf "BASE\\t%s\\t%s\\n" "$cur" "$HOME"',
  'for d in "$cur"/*/; do',
  '  [ -d "$d" ] || continue',
  '  base=$(basename "$d")',
  '  case "$base" in .*|node_modules|target|__pycache__) continue;; esac',
  '  full="${cur%/}/$base"',
  '  is_git=0; branch=""',
  '  if command -v git >/dev/null 2>&1 && git -C "$full" rev-parse --is-inside-work-tree >/dev/null 2>&1; then',
  '    is_git=1; branch=$(git -C "$full" symbolic-ref --short HEAD 2>/dev/null || git -C "$full" rev-parse --short HEAD 2>/dev/null || true)',
  '  fi',
  '  printf "ENTRY\\t%s\\t%s\\t%s\\t%s\\n" "$base" "$full" "$is_git" "$branch"',
  'done',
].join('\n');

export const REMOTE_MKDIR_SH = [
  'p="$1"',
  'case "$p" in "~") p="$HOME";; "~/"*) p="$HOME/${p#??}";; esac',
  'mkdir -p "$p" && resolved=$(cd "$p" && pwd -P) && printf "%s\\n" "$resolved"',
].join('\n');

export function parseRemoteProbe(stdout) {
  const out = { home: '', pmScript: '', ledgerHome: '', dirs: [] };
  for (const line of String(stdout || '').split('\n')) {
    if (!line) continue;
    const parts = line.split('\t');
    if (parts[0] === 'HOME') out.home = parts[1] || '';
    else if (parts[0] === 'PM') out.pmScript = parts[1] || '';
    else if (parts[0] === 'LEDGER') out.ledgerHome = parts[1] || '';
    else if (parts[0] === 'DIR') {
      out.dirs.push({
        exists: parts[1] === '1',
        raw: parts[2] || '',
        path: parts[3] || parts[2] || '',
        git: parts[4] === '1',
        branch: parts[5] || '',
      });
    }
  }
  return out;
}

export function parseRemoteDirs(stdout) {
  const out = { base: '', home: '', entries: [] };
  for (const line of String(stdout || '').split('\n')) {
    if (!line) continue;
    const parts = line.split('\t');
    if (parts[0] === 'BASE') {
      out.base = parts[1] || '';
      out.home = parts[2] || '';
    } else if (parts[0] === 'ENTRY') {
      out.entries.push({
        name: parts[1] || '',
        path: parts[2] || '',
        git: parts[3] === '1',
        branch: parts[4] || '',
      });
    }
  }
  out.entries.sort((a, b) => Number(b.git) - Number(a.git) || a.name.localeCompare(b.name));
  return out;
}

// A PM from `pm.py state` as a row the terminal lookup understands (as pm-list builds it).
export function pmRow(pm) {
  return pm ? { ...pm, type: 'pm', machine: '', sourceName: pm.name } : null;
}

// A ledger task (or a state task) as a row the terminal lookup understands.
export function taskRow(task) {
  return task ? { ...task, type: 'task', task: task.id, machine: '' } : null;
}

// What a thread's worker runs as (the task file's `worker`, `pm.py state`'s `engine`: {profile, kind, model,
// effort, advisor}); {} or nothing for a task dispatched before profiles.
export function taskEngine(task) {
  const of = [task?.engine, task?.worker].find(x => x && typeof x === 'object' && !Array.isArray(x)) || {};
  return ['profile', 'kind', 'model', 'effort', 'advisor'].some(k => of[k]) ? of : null;
}

// A model ID as people say it: opus → Opus, claude-fable-5-2 → Fable 5.2, claude-opus-4-1-20250805 → Opus 4.1,
// us.anthropic.claude-sonnet-5-5-v1:0 → Sonnet 5.5; anything else as it is, its first letter raised.
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
export function modelName(id) {
  const raw = String(id || '').trim().replace(/\[.*\]$/, '');
  const m = raw.toLowerCase().match(/(?:^|[.\/])(?:claude-)?(opus|sonnet|haiku|fable)((?:-\d{1,2})*)(?:-\d{8})?(?:-v\d+(?::\d+)?)?$/);
  if (!m) return raw && cap(raw);
  return cap(m[1]) + (m[2] ? ` ${m[2].slice(1).split('-').join('.')}` : '');
}

// The quiet label beside the thread's agent icon: Opus·xhigh, Sonnet·medium, Opus, Opus·xhigh+Fable, Codex·high.
// Claude's workers are named by model; another program by its own name. Null: nothing known, no label.
export function engineLabel(task) {
  const e = taskEngine(task);
  if (!e) return null;
  const kind = String(e.kind || 'claude');
  const name = kind === 'claude' ? modelName(e.model) || 'Claude' : cap(kind);
  return name + (e.effort ? `·${e.effort}` : '') + (e.advisor ? `+${modelName(e.advisor).split(' ')[0]}` : '');
}

const EFFORT_SHORT = {
  xhigh: 'xhigh',
  'extra-high': 'xhigh',
  extra_high: 'xhigh',
  max: 'max',
  high: 'high',
  medium: 'med',
  med: 'med',
  low: 'low',
  minimal: 'min',
  min: 'min',
};
const EFFORT_SUFFIX_RE = /[-_](xhigh|extra-high|extra_high|max|high|medium|med|low|minimal|min)$/i;
const GENERIC_PROFILES = new Set(['light', 'standard', 'hard', 'deep']);

function normalizeShortEffort(raw) {
  const s = String(raw || '').trim().toLowerCase();
  if (!s || s === 'default') return '';
  return EFFORT_SHORT[s] || s;
}

function stripEffortSuffix(raw) {
  const s = String(raw || '').trim();
  const m = EFFORT_SUFFIX_RE.exec(s);
  if (!m) return { base: s, effort: '' };
  return { base: s.slice(0, m.index), effort: normalizeShortEffort(m[1]) };
}

function compactModelShortName(rawModel) {
  const cleaned = String(rawModel || '').trim().replace(/\[.*\]$/, '');
  if (!cleaned) return '';
  const leaf = cleaned.replace(/^[^/]+\//, '').replace(/^(?:us|eu|global)\.[a-z0-9_-]+\./i, '');
  const low = leaf.toLowerCase();
  if (/(?:^|[-_.])orchestrator(?:[-_.]|$)/.test(low)) return 'Orchestrator';
  const claude = low.match(/^(?:claude-)?(opus|sonnet|haiku|fable)(?:-\d{1,2})*(?:-\d{8})?(?:-v\d+(?::\d+)?)?$/);
  if (claude) return cap(claude[1]);
  const codename = low.match(/^(?:gemini(?:-[\d.]+)?-)?(neon|carbon)$/);
  if (codename) return cap(codename[1]);
  const gemini = low.match(/^gemini(?:-[\d.]+)?-(pro|flash(?:-lite)?|ultra)$/);
  if (gemini) return gemini[1].startsWith('flash') ? gemini[1].split('-').map(cap).join(' ') : `Gemini ${cap(gemini[1])}`;
  const gpt = low.match(/^gpt-([a-z0-9.]+(?:-[a-z0-9.]+)?)$/);
  if (gpt) return `GPT-${gpt[1]}`;
  if (/^o\d+(?:-[a-z0-9]+)?$/.test(low)) return low;
  return cap(leaf);
}

// Compact readable model + effort formatter for Threads inline badges and compact agent sub-rows:
// Opus·xhigh, Neon·high, Neon·med, Carbon·high, Sonnet·med, GPT-5·high, Orchestrator.
// Extracts effort from explicit `effort`, model suffix (e.g. `gemini-4-neon-high`, `claude-opus-5-5-medium`),
// or profile suffix (e.g. `opus-high`, `neon-medium`), with graceful fallback to profile or kind.
export function formatAgentModelEffort(source, fallbackKind = '') {
  const isDirect = source && typeof source === 'object' && !Array.isArray(source) &&
    !('engine' in source) && !('worker' in source) &&
    ['profile', 'kind', 'model', 'effort', 'advisor'].some(k => source[k]);
  const e = isDirect ? source : taskEngine(source);
  const kind = String(e?.kind || fallbackKind || '').trim();
  const profile = String(e?.profile || '').trim();
  const rawModel = String(e?.model || '').trim().replace(/\[.*\]$/, '');

  let effort = normalizeShortEffort(e?.effort);
  let baseModel = rawModel;
  const fromModel = stripEffortSuffix(rawModel);
  if (fromModel.effort) {
    baseModel = fromModel.base;
    if (!effort) effort = fromModel.effort;
  }
  const fromProfile = stripEffortSuffix(profile);
  if (!effort && fromProfile.effort) effort = fromProfile.effort;

  let model = compactModelShortName(baseModel);
  if (!model && fromProfile.base && !GENERIC_PROFILES.has(fromProfile.base.toLowerCase())) {
    model = compactModelShortName(fromProfile.base);
  }
  if (!model && kind) model = cap(kind);
  if (!model && profile) model = cap(profile);
  if (!model) return { model: '', effort: '', label: '' };
  return { model, effort, label: effort ? `${model}·${effort}` : model };
}

// The task's escalations ({from, to, why, at}), in order; anything not shaped so is left out.
export function escalations(task) {
  return (Array.isArray(task?.escalations) ? task.escalations : []).filter(x => x && (x.from || x.to));
}

// How many times it was escalated: its escalations, or, for a thread off the board, the count the state keeps
// (`escalated`, see endedEngine).
const timesEscalated = task => escalations(task).length || Math.max(0, Math.floor(Number(task?.escalated) || 0));

// Escalated at least once: the label gets a small up arrow.
export const wasEscalated = task => timesEscalated(task) > 0;

// A thread off the board (retired, or ended a day ago) as engineChip reads it: its mark in the state's
// `ended_engines` ({task id: {profile, kind, model, effort, advisor, escalated}}, see pm.py engine_mark),
// or null without one.
export function endedEngine(marks, id) {
  const mark = marks && typeof marks === 'object' && Object.hasOwn(marks, id) ? marks[id] : null;
  if (!mark || typeof mark !== 'object' || Array.isArray(mark)) return null;
  const { escalated, ...engine } = mark;
  return { engine, escalated };
}

// One side of an escalation: a profile name, or a worker record ({profile, model, …}) said by its profile or label.
const stepName = side => (side && typeof side === 'object' ? side.profile || engineLabel({ engine: side }) : side) || '?';

// The reason the PM wrote when dispatching: the latest log note "<profile>：<why>" (or "<profile>: <why>").
export function engineReason(task) {
  const profile = taskEngine(task)?.profile;
  if (!profile) return '';
  const said = text => {
    const m = String(text || '').match(/^\s*([^\s:：]+)\s*[：:]\s*(.+)$/s);
    return m && m[1].toLowerCase() === String(profile).toLowerCase() ? m[2].trim() : '';
  };
  return (Array.isArray(task.log) ? task.log : []).map(e => said(e?.text)).filter(Boolean).pop() || '';
}

// What hovering the label says, one line each: the profile, the dispatch reason, each escalation, review rounds.
export function engineTip(lang, task) {
  const e = taskEngine(task);
  if (!e) return '';
  const lines = [];
  if (e.profile) lines.push(word(lang, 'engineProfile', e.profile));
  const why = engineReason(task);
  if (why) lines.push(word(lang, 'engineWhy', why));
  for (const x of escalations(task)) lines.push(word(lang, 'engineEscalated', stepName(x.from), stepName(x.to), x.why || ''));
  if (!escalations(task).length && wasEscalated(task)) lines.push(word(lang, 'engineEscalatedTimes', timesEscalated(task)));
  if (Number.isInteger(task.rounds) || /^\d+$/.test(task.rounds ?? '')) lines.push(word(lang, 'engineRounds', Number(task.rounds)));
  return lines.join('\n') || engineLabel(task);
}

// The thread list's quiet label for a row: the label without its advisor (an icon marks one), its effort said
// even when the worker runs on the default (Opus·default), the model alone
// for the narrowest panel, the advisor's short name, whether it was escalated, and the detail's tip.
// Null: nothing known (a thread entered by hand, the user's own session), so no label and no room kept.
export function engineChip(lang, task) {
  const e = taskEngine(task);
  if (!e) return null;
  const plain = { ...e, advisor: '' };
  return { label: engineLabel({ engine: { ...plain, effort: e.effort || word(lang, 'effortDefault') } }), name: engineLabel({ engine: { ...plain, effort: '' } }),
    advisor: e.advisor ? modelName(e.advisor).split(' ')[0] : '', up: wasEscalated(task), tip: engineTip(lang, task) };
}

// How long ago, in the largest whole unit: "<1m", "5m", "3h", "2d"; in a Chinese view "刚刚",
// "5 分钟", "3 小时", "2 天" (pm-list's rule; model.test.mjs keeps the copy identical).
const UNITS = [[86400000, 'd', '天'], [3600000, 'h', '小时'], [60000, 'm', '分钟']];
export function age(ms, lang) {
  const unit = UNITS.find(([size]) => ms >= size), zh = lang === 'zh';
  if (!unit) return zh ? '刚刚' : '<1m';
  return zh ? `${Math.floor(ms / unit[0])} ${unit[2]}` : `${Math.floor(ms / unit[0])}${unit[1]}`;
}

// A ledger log line as the thread panel shows it.
// A line that starts with changed fields (`pm.py update`: "status=review, commit=abc; <note>") is
// its note. One that is only such changes is '' (the list: the row's group already says it), or,
// with `whole`, the changes spelled out (the thread's log, where every entry shows).
// pm.py also writes a few lines by itself, in English: a registration, a dispatch, a retire. In a
// Chinese view these and the field names read as Chinese. What a person or an agent wrote is shown
// as written.
const LOG_FIELDS = 'title|status|owner|workspace|pane|agent|branch|worktree|base|brief|commit|release|parent';
const LOG_FIELD = new RegExp(`^(${LOG_FIELDS})\\s*=\\s*`);
const LOG_FIELD_END = new RegExp(`[,，]\\s*(?=(?:${LOG_FIELDS})\\s*=)|[;；]\\s*|$`);
const FIELD_ZH = { title: '标题', status: '状态改为', owner: '负责', workspace: '工作区', pane: '终端', agent: 'agent',
  branch: '分支', worktree: '工作树', base: '基线', brief: '任务书', commit: '提交', release: '发布', parent: '属于' };
const RETIRED_ZH = { terminal: '终端', worktree: '工作树', branch: '分支' };
export function compactLogLine(text) {
  return typeof text === 'string'
    ? text.replace(/\r?\n+/g, ' ').replace(/\s{2,}/g, ' ').trim()
    : '';
}

export function logText(lang, text, whole = false) {
  const zh = lang === 'zh';
  let rest = typeof text === 'string' ? text.trim() : '';
  const fields = [];
  for (let found = LOG_FIELD.exec(rest); found; found = LOG_FIELD.exec(rest)) {
    const after = rest.slice(found[0].length), end = LOG_FIELD_END.exec(after);
    fields.push([found[1], after.slice(0, end.index).trim()]);
    rest = after.slice(end.index + end[0].length);
    if (/^[;；]/.test(end[0])) break;
  }
  if (fields.length) {
    if (rest.trim() || !whole) return rest.trim();
    return zh ? fields.map(([key, value]) => (key === 'status' ? `${FIELD_ZH.status}${word('zh', value)}` : `${FIELD_ZH[key]} ${value}`)).join('，')
      : fields.map(([key, value]) => `${key}=${value}`).join(', ');
  }
  if (!zh) return rest;
  let found = /^registered \((\w+)\)$/.exec(rest);
  if (found) return `登记（${word('zh', found[1])}）`;
  found = /^dispatched to (\S+) \(([^()]*)\)$/.exec(rest);
  if (found) return `派给 ${found[1]}（${found[2]}）`;
  found = /^retired: worktree and branch (\S+)$/.exec(rest);
  if (found) return `已回收：工作树和分支 ${found[1]}`;
  found = /^retired: removed (.+?)(?:; branch (\S+) is kept: (.+))?$/.exec(rest);
  if (!found) return rest;
  const removed = found[1] === 'nothing' ? '没有要清理的' : found[1].split(', ')
    .map(item => item.replace(/^(terminal|worktree|branch) /, (_all, kind) => `${RETIRED_ZH[kind]} `)).join('、');
  const why = (found[3] || '').replace(/^checked out in (.+)$/, '在 $1 检出着').replace(/^git refused to delete it$/, 'git 拒绝删除');
  return `已回收：${removed}${found[2] ? `；分支 ${found[2]} 保留：${why}` : ''}`;
}

// Copies of pm-dash/model.js (a mod cannot import from another mod's folder);
// model.test.mjs checks that they stay identical.
export const LEDGER_HOME_SH = 'if [ -n "$PM_HOME" ]; then printf %s "$PM_HOME"; ' +
  'elif [ -d "$HOME/.claude/pm" ] && ! [ "$HOME/.claude/pm" -ef "$HOME/.dudu" ]; then printf %s "$HOME/.claude/pm"; else printf %s "$HOME/.dudu"; fi';
export function cleanTaskLog(latest) {
  const text = typeof latest === 'string' ? latest.trim() : '';
  const prefix = /^status\s*=\s*[\w-]+(?:\s*[,;，；]\s*commit\s*=\s*([^\s,;，；]+))?\s*(?:[,;，；]\s*|$)/.exec(text);
  return { text: prefix ? text.slice(prefix[0].length).trim() : text, commit: prefix?.[1] || '' };
}
// Live terminals on the row's machine (`''` means local, so no `machine/` prefix).
function liveTerminalsFor(row, terms) {
  const machine = row.machine || '';
  return terms.filter(t => t.state === 'live' &&
    (machine ? t.address?.startsWith(`${machine}/`) : !t.address?.includes('/')));
}
export function terminalFor(row, terms) {
  const machine = row.machine || '';
  const candidates = liveTerminalsFor(row, terms);
  const key = row.type === 'pm' ? 'pm' : 'task';
  const value = row.type === 'pm' ? row.project || (row.sourceName ?? row.name)?.replace(/^pm-/, '') : row.sourceId ?? row.task;
  // Prefer a labeled child over a recorded parent pane (tasks may share their PM's pane).
  const labeled = candidates.find(t => value && t.labels?.[key] === value);
  const pane = row.pane?.startsWith('hc:') ? row.pane.slice(3) : '';
  const address = machine ? `${machine}/${pane}` : pane;
  return labeled || (pane ? candidates.find(t => t.address === address &&
    // A task recorded on its PM's pane must not borrow that PM's live status.
    (row.type === 'pm' || (!t.labels?.pm && (!t.labels?.task || t.labels.task === value)))) : undefined);
}
export function terminalTargetFor(row, terms) {
  const exact = terminalFor(row, terms);
  if (exact) return { terminal: exact, exact: true };
  const folder = path => typeof path === 'string' && path ? path.replace(/\/+$/, '') || '/' : '';
  const repo = folder(row.repo);
  const candidates = row.type === 'pm' && repo ? liveTerminalsFor(row, terms)
    .filter(t => t.address && folder(t.cwd) === repo) : [];
  candidates.sort((a, b) => Number(Boolean(b.program?.agent)) - Number(Boolean(a.program?.agent)) ||
    (a.address < b.address ? -1 : a.address > b.address ? 1 : 0));
  return { terminal: candidates[0], exact: false };
}
// How a click brings a terminal up. One with a pane: pane.focus, which shows its own space and tab.
// A sub-agent without a pane (Herdr's agents list peeks those) is peeked over the tab of the nearest
// terminal up its parent chain that has a pane and is not a retired PM, else over its project's current
// PM (`home`): a worker that outlived a PM rotated out (closed, or still open but retired). With neither, nothing: no pane is focused and the work
// column is not shown, since that would reveal whatever space was active — another project's.
// agent.focus is not used: on a paneless terminal it changes no tab (t5h opened OldName).
// `paned`: the addresses that have a pane (panes()' terminals, agents()' addresses).
export function focusPlan(address, terms, paned, home = '') {
  const none = { focus: '', peek: '' };
  if (!address) return none;
  const has = new Set(paned.filter(Boolean));
  if (has.has(address)) return { focus: address, peek: '' };
  const byAddress = new Map(terms.map(t => [t.address, t]));
  // Another PM terminal up the chain (`home` is the project's current PM) is passed over:
  // shown on its tab, the thread would invite talking to the wrong PM.
  const otherPm = t => Boolean(home && t?.labels?.pm && t.address !== home);
  const seen = new Set([address]);
  for (let up = byAddress.get(address)?.parent; up && !seen.has(up); up = byAddress.get(up)?.parent) {
    if (has.has(up) && !otherPm(byAddress.get(up))) return { focus: up, peek: address };
    seen.add(up);
  }
  return home && has.has(home) ? { focus: home, peek: address } : none;
}

const normDir = path => (typeof path === 'string' && path ? path.replace(/\/+$/, '') || '/' : '');
const inDir = (path, root) => {
  const p = normDir(path), r = normDir(root);
  return Boolean(p && r && (p === r || p.startsWith(r === '/' ? '/' : `${r}/`)));
};

export const folderName = path => String(path || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '';

export function projectFolders(pm) {
  if (!pm || typeof pm !== 'object') return [];
  if (Array.isArray(pm.folders)) {
    const out = [];
    for (const raw of pm.folders) {
      if (!raw || typeof raw !== 'object') continue;
      const path = String(raw.path || '').trim();
      if (!path) continue;
      const alias = String(raw.alias || '').trim() || folderName(path) || 'folder';
      out.push({
        path,
        alias,
        git: Boolean(raw.git),
        default_branch: String(raw.default_branch || ''),
        exists: raw.exists !== false,
      });
    }
    return out;
  }
  const repo = String(pm.repo || '').trim();
  if (!repo) return [];
  return [{
    path: repo,
    alias: folderName(repo) || 'repo',
    git: true,
    default_branch: '',
    exists: pm.repo_ok !== false,
  }];
}

export function foldersSignature(pm) {
  return projectFolders(pm).map(f => `${f.alias}\0${f.path}`).join('\n');
}

export function headerFoldersView(pm, { machine = '', homeDir = '', lang = 'en' } = {}) {
  const folders = projectFolders(pm);
  const count = folders.length;
  if (count === 0) {
    return {
      count: 0,
      mode: 'empty',
      primaryLabel: machine ? `${machine} · ${word(lang, 'addFolderShort')}` : word(lang, 'addFolderShort'),
      extraCount: 0,
      folders,
      tooltip: word(lang, 'workspaceFoldersEmptyTip'),
    };
  }
  const firstLabel = machine ? `${machine} · ${folders[0].path}` : shortPath(folders[0].path, homeDir);
  if (count === 1) {
    return {
      count: 1,
      mode: 'single',
      primaryLabel: firstLabel,
      extraCount: 0,
      folder: folders[0],
      folders,
      tooltip: word(lang, 'workspaceFoldersTip', 1),
    };
  }
  return {
    count,
    mode: 'multi',
    primaryLabel: firstLabel,
    extraCount: count - 1,
    folders,
    tooltip: word(lang, 'workspaceFoldersTip', count),
  };
}

const FOLDER_ACTIVE_STATUSES = new Set(['blocked', 'in_progress', 'review', 'proposed', 'paused']);

export function activeThreadsInFolder(tasks, folder) {
  if (!Array.isArray(tasks) || !folder) return [];
  const alias = String(folder.alias || '').trim();
  const fPath = normDir(folder.path || '');
  return tasks.filter(t => {
    if (!t || !FOLDER_ACTIVE_STATUSES.has(t.status)) return false;
    const tAlias = String(t.folder_alias || t.folderAlias || '').trim();
    const tRepo = normDir(t.repo || '');
    return Boolean((alias && tAlias === alias) || (fPath && tRepo && tRepo === fPath));
  });
}

export function threadFolderBadge(taskOrRow, folders = []) {
  const alias = String(taskOrRow?.folder_alias || taskOrRow?.folderAlias || '').trim();
  if (!alias) return '';
  const list = Array.isArray(folders) ? folders : [];
  if (list.length >= 2) return alias;
  if (list.length === 1 && list[0]?.alias && list[0].alias !== alias) return alias;
  return '';
}

// Which open space belongs to this project on `machine`, or null when none does.
// Never falls back to another project's space (even the currently active one):
// terminal.keep on an unrelated space would put the PM tab into that project and expose it.
export function projectSpaceFor(pm, spaceList, paneList = [], machine = '', pmTerm = null) {
  const wantMachine = String(machine || '');
  const same = (spaceList || []).filter(s => s && s.id && String(s.machine || '') === wantMachine);
  if (!same.length) return null;
  const explicitSpaceId = String(pm?.space_id || '').trim();
  if (explicitSpaceId) {
    const qualified = onMachine(explicitSpaceId, wantMachine);
    const hit = same.find(s => s.id === qualified || s.id === explicitSpaceId);
    if (hit) return hit;
  }
  const labelled = String(pmTerm?.labels?.['herdr.space'] || '').trim();
  if (labelled) {
    const qualified = onMachine(labelled, wantMachine);
    const hit = same.find(s => s.id === qualified || s.id === labelled);
    if (hit) return hit;
  }
  const repoRoots = [...new Set([
    ...projectFolders(pm).map(f => normDir(f.path)),
    normDir(pm?.repo),
  ].filter(Boolean))];
  const worktrees = normDir(pm?.worktrees);
  if (repoRoots.length) {
    const byFolder = same.find(s => repoRoots.includes(normDir(s.folder)));
    if (byFolder) return byFolder;
  }
  if (repoRoots.length || worktrees) {
    const tabToSpace = new Map();
    for (const s of same) {
      for (const tab of s.tabs || []) {
        if (tab?.id) tabToSpace.set(tab.id, s);
      }
    }
    if (repoRoots.length) {
      for (const p of paneList || []) {
        if (p?.tab && repoRoots.includes(normDir(p.cwd)) && tabToSpace.has(p.tab)) return tabToSpace.get(p.tab);
      }
    }
    for (const p of paneList || []) {
      if (p?.tab && tabToSpace.has(p.tab) && (repoRoots.some(r => inDir(p.cwd, r)) || inDir(p.cwd, worktrees))) {
        return tabToSpace.get(p.tab);
      }
    }
    const bySubFolder = same.find(s => repoRoots.some(r => inDir(s.folder, r)) || inDir(s.folder, worktrees));
    if (bySubFolder) return bySubFolder;
  }
  const names = new Set([pm?.display_name, pm?.space_name, pm?.project].map(v => String(v || '').trim()).filter(Boolean));
  if (names.size) {
    const byName = same.find(s => names.has(String(s.name || '').trim())
      && (!s.folder || !repoRoots.length || repoRoots.some(r => inDir(s.folder, r))));
    if (byName) return byName;
  }
  return null;
}

export function projectName(pm) {
  return String(pm?.display_name || pm?.space_name || pm?.project || '').trim()
    || String(pm?.sourceName || pm?.name || '').replace(/^pm-/, '');
}

export function pmTabNameFor(pm) {
  const base = String(pm?.display_name || pm?.space_name || pm?.project || '').trim()
    || normDir(pm?.repo).split('/').filter(Boolean).pop()
    || '';
  return base ? `PM-${base}` : '';
}

// Recovery plan when focusing this project's live PM terminal that currently has no pane.
// Returns Herdr commands (`[name, args]`) to put it in a tab of THIS project's own space and
// switch to work — never exposing another project's space — or [] when not applicable.
// Note: `terminal.keep` applies asynchronously (`pending: true`), so `pane.focus`, `tab.rename`,
// and closing any default empty shell tab from `space.new` run in `pmKeepFollowUp` once the pane lands.
export function pmKeepPlan(address, { pm = null, pmTerminal = null, machine = '', spaces = [], panes = [] } = {}) {
  const target = onMachine(address, machine);
  const pmAddr = onMachine(pmTerminal?.address || '', machine);
  if (!target || !pmAddr || target !== pmAddr) return [];
  const space = projectSpaceFor(pm, spaces, panes, machine, pmTerminal);
  if (space) {
    return [
      ['space.select', { id: space.id }],
      ['terminal.keep', { terminal: pmAddr, place: 'tab' }],
      ['layout.select', { stack: 'pm-stage', child: 'work' }],
    ];
  }
  const name = String(pm?.display_name || pm?.space_name || pm?.project || '').trim();
  const folder = String(pm?.repo || '').trim();
  if (!name && !folder) return [];
  const spaceArgs = { machine: String(machine || '') };
  if (name) spaceArgs.name = name;
  if (folder) spaceArgs.folder = folder;
  return [
    ['space.new', spaceArgs],
    ['terminal.keep', { terminal: pmAddr, place: 'tab' }],
    ['layout.select', { stack: 'pm-stage', child: 'work' }],
  ];
}

// Follow-up commands once an async `terminal.keep` pane appears in `panes()`:
// rename the newly created unnamed tab to `PM-<project>`, focus the PM pane, and—when `space.new`
// was just issued to host this PM—close the empty default shell tab `space.new` spawned alongside it.
// Returns null while the PM pane has not yet landed.
export function pmKeepFollowUp(pending, spaceList = [], paneList = []) {
  if (!pending?.terminal) return null;
  const pmPane = (paneList || []).find(p => p?.terminal === pending.terminal);
  if (!pmPane) return null;
  const cmds = [];
  const allSpaces = spaceList || [];
  let hostSpace = null;
  let pmTab = null;
  for (const sp of allSpaces) {
    for (const tab of sp?.tabs || []) {
      if (tab?.id && tab.id === pmPane.tab) {
        hostSpace = sp;
        pmTab = tab;
        break;
      }
    }
    if (pmTab) break;
  }
  if (pending.tabName && pmPane.tab && (!pmTab || (!pmTab.named && pmTab.name !== pending.tabName))) {
    cmds.push(['tab.rename', { id: pmPane.tab, name: pending.tabName }]);
  }
  cmds.push(['pane.focus', { terminal: pending.terminal }]);
  if (pending.createdSpace && hostSpace && !pending.prevSpaceIds?.has(hostSpace.id)) {
    const tabs = hostSpace.tabs || [];
    if (tabs.length === 2) {
      const other = tabs.find(t => t?.id && t.id !== pmPane.tab);
      if (other && !other.named && other.panes === 1) {
        const otherPanes = (paneList || []).filter(p => p?.tab === other.id);
        if (otherPanes.length === 1 && otherPanes[0]?.program?.shell === true) {
          cmds.push(['tab.close', { id: other.id }]);
        }
      }
    }
  }
  return cmds;
}
export function withAlpha(color, opacity) {
  const hex = color.slice(1), rgb = hex.length === 3 ? [...hex].map(c => c + c).join('') : hex.slice(0, 6);
  const alpha = hex.length === 8 ? parseInt(hex.slice(6), 16) : 255;
  return `#${rgb}${Math.round(alpha * opacity).toString(16).padStart(2, '0')}`;
}

function luminance(color) {
  const hex = color.slice(1), rgb = hex.length === 3 ? [...hex].map(c => c + c).join('') : hex;
  return [0, 2, 4].reduce((n, offset, i) => {
    const c = parseInt(rgb.slice(offset, offset + 2), 16) / 255;
    return n + (c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4) * [.2126, .7152, .0722][i];
  }, 0);
}

// herdr.theme() exposes color tokens, unlike gpui-base's Theme.is_dark.
export function isDarkTheme(theme) {
  return luminance(theme.foreground) > luminance(theme.background);
}

export function mixHex(baseColor, targetColor, ratio) {
  const parse = c => {
    if (typeof c !== 'string' || !c.startsWith('#')) return null;
    const h = c.slice(1);
    const hex = h.length === 3 ? [...h].map(x => x + x).join('') : h.slice(0, 6);
    if (!/^[0-9a-f]{6}$/i.test(hex)) return null;
    return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
  };
  const a = parse(baseColor), b = parse(targetColor);
  if (!a || !b) return baseColor || targetColor || '#000000';
  const r = Math.max(0, Math.min(1, Number(ratio) || 0));
  const ch = i => Math.round(a[i] + (b[i] - a[i]) * r).toString(16).padStart(2, '0');
  return `#${ch(0)}${ch(1)}${ch(2)}`;
}

// Micro-surface tonal ladder derived from active theme tokens (Plan B: Tonal Layering).
// Dark themes step cleanly from recessed well -> panel base -> elevated pod/card without border boxes;
// light themes step cleanly in the opposite direction while preserving contrast.
export function tonalSurfaces(t) {
  const dark = isDarkTheme({
    foreground: t?.foreground || '#eeeeee',
    background: t?.background || t?.surface || '#111318',
  });
  const bg = t?.background || t?.surface || (dark ? '#111318' : '#ffffff');
  const surface = t?.surface || (dark ? '#1a1d24' : '#f7f6f3');
  const accent = t?.accent || '#58a6ff';
  const fg = t?.foreground || (dark ? '#eeeeee' : '#1e1f22');
  const border = t?.border || (dark ? '#333333' : '#dedcd5');
  if (dark) {
    const sameSurface = surface.toLowerCase() === bg.toLowerCase();
    const pod = sameSurface ? mixHex(bg, '#ffffff', 0.045) : mixHex(bg, surface, 0.42);
    const card = sameSurface ? mixHex(bg, '#ffffff', 0.055) : mixHex(bg, surface, 0.52);
    return {
      dark: true,
      well: mixHex(bg, '#000000', 0.36),
      tabBar: mixHex(bg, '#000000', 0.18),
      pod,
      podWell: mixHex(bg, '#000000', 0.24),
      card,
      chip: mixHex(bg, '#000000', 0.30),
      chipHover: mixHex(bg, '#ffffff', 0.065),
      chipOpen: withAlpha(accent, 0.16),
      chipOpenBorder: withAlpha(accent, 0.34),
      segActive: t.raised || mixHex(bg, '#ffffff', 0.10),
      softChip: withAlpha(fg, 0.075),
      softChipHover: withAlpha(fg, 0.045),
      pillMuted: withAlpha(fg, 0.065),
      hairline: withAlpha(border, 0.42),
    };
  }
  return {
    dark: false,
    well: mixHex(bg, '#000000', 0.055),
    tabBar: surface,
    pod: mixHex(bg, '#000000', 0.03),
    podWell: bg,
    card: mixHex(bg, '#000000', 0.032),
    chip: mixHex(bg, '#000000', 0.055),
    chipHover: mixHex(bg, '#000000', 0.09),
    chipOpen: withAlpha(accent, 0.12),
    chipOpenBorder: withAlpha(accent, 0.30),
    segActive: bg,
    softChip: withAlpha(fg, 0.068),
    softChipHover: withAlpha(fg, 0.04),
    pillMuted: withAlpha(fg, 0.06),
    hairline: withAlpha(border, 0.65),
  };
}

// Use only supplied theme tokens, choosing their higher-contrast foreground
// for each solid fill rather than assuming white also works in a dark theme.
export function solidText(fill, theme) {
  const bg = luminance(fill);
  const contrast = color => { const fg = luminance(color); return (Math.max(bg, fg) + .05) / (Math.min(bg, fg) + .05); };
  return [theme.foreground, theme.background, theme.surface, theme.accent_foreground]
    .filter(Boolean).reduce((best, color) => contrast(color) > contrast(best) ? color : best);
}

// What Esc does on a project's conversation page, one layer a press. The project's box answering a
// question card in the user's own words (answering) stops answering first, its words kept; then a box
// being typed in that holds words (typing) lets go of the keyboard and nothing else, so a press never
// takes a draft off screen; then inline editing, retopic, or search exits before closing an open
// agent small window (one at a time without killing its process); then history / bringBack overlays,
// an open thread's detail, or doc preview; then a thread list the header's icon slid open over a
// narrow window (listOpen) closes. Otherwise nothing:
// the conversation is the top (its board is pm-dash's page, which goes back here by itself).
export function escapeStep({
  imageLightbox = false,
  mentionSub = false,
  mention = false,
  projectSearch = false,
  foldersPopover = false,
  tabMenu = false,
  selectionBar = false,
  answering = false,
  confirmDelete = false,
  confirmCloseDirty = false,
  typing = false,
  editing = false,
  retopic = false,
  search = false,
  agentWindow = false,
  agentWindows = 0,
  history = false,
  bringBack = false,
  change = false,
  activeTab = false,
  detail = false,
  doc = false,
  listOpen = false,
} = {}) {
  if (imageLightbox) return 'imageLightbox';
  if (mentionSub) return 'mentionSub';
  if (mention) return 'mention';
  if (projectSearch) return 'projectSearch';
  if (foldersPopover) return 'foldersPopover';
  if (tabMenu) return 'tabMenu';
  if (selectionBar) return 'selectionBar';
  if (answering) return 'answer';
  if (confirmDelete) return 'confirmDelete';
  if (confirmCloseDirty) return 'confirmCloseDirty';
  if (typing) return 'blur';
  if (editing) return 'edit';
  if (retopic) return 'retopic';
  if (search) return 'search';
  const hasAgentWindow = Boolean(agentWindow) || (Array.isArray(agentWindows) ? agentWindows.length > 0 : Number(agentWindows) > 0);
  if (hasAgentWindow) return 'agentWindow';
  if (history) return 'history';
  if (bringBack) return 'bringBack';
  if (change) return 'change';
  if (activeTab) return 'activeTab';
  if (detail) return 'detail';
  if (doc) return 'doc';
  if (listOpen) return 'list';
  return null;
}

// The side panel's width. The reader drags the edge between it and the conversation; the width
// they leave it at is kept (per viewer, in the view's localStorage) and holds across projects and
// restarts. However wide they asked for, the panel stays at least PANEL_MIN and leaves the
// conversation at least TALK_MIN; a window too narrow for both keeps the panel's minimum and the
// conversation takes what is left. Never wider than the view, so nothing scrolls sideways.
export const PANEL_WIDTH = 360, PANEL_MIN = 260, TALK_MIN = 360;

// `want`: the width asked for (null: the default); `view`: the whole view's width (0 before it is measured).
export function panelWidth(want, view = 0) {
  const asked = Number.isFinite(want) && want > 0 ? want : PANEL_WIDTH;
  const width = Math.round(Math.max(PANEL_MIN, Math.min(asked, view > 0 ? view - TALK_MIN : asked)));
  return view > 0 ? Math.min(width, Math.round(view)) : width;
}

// Where a drag of the panel's left edge leaves its width: `drag` is {x, width} at the press, `x` the
// pointer now; moving left widens the panel. Fitted to the view as panelWidth fits it.
export function draggedWidth(drag, x, view = 0) {
  return panelWidth(drag.width + drag.x - x, view);
}

// The kept width as storage has it: a positive number, or null for the default (nothing kept, or junk).
export function readPanelWidth(text) {
  if (text == null || String(text).trim() === '') return null;
  const n = Number(text);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : null;
}

// Dual-mode adaptive split layout (compact list vs split reader/detail/diff).
export const SPLIT_WIDE_MIN = 1080;
export const SPLIT_MEDIUM_MIN = 700;
export const SPLIT_CARD_MARGIN_R = 10;
export const SPLIT_GRIP_OVERHANG = 5;
export const SPLIT_RATIO_MIN = 0.30;
export const SPLIT_RATIO_MAX = 0.66;

function clampPanel(value, min, max) {
  if (max < min) return max;
  return Math.max(min, Math.min(value, max));
}

export function resolvePanelMode({
  tabCount = 0,
  detail = false,
  activeDoc = false,
  editingDoc = false,
  historyView = false,
  changeOpen = false,
} = {}) {
  return (Number(tabCount) > 0 || detail || activeDoc || editingDoc || historyView || changeOpen) ? 'split' : 'compact';
}

export function readPanelSizes(jsonText, legacyWidthText = null) {
  if (jsonText != null && String(jsonText).trim() !== '') {
    try {
      const parsed = JSON.parse(String(jsonText));
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        const rawCompact = Number(parsed.compactPx);
        const compactPx = parsed.compactPx != null && Number.isFinite(rawCompact) && rawCompact > 0
          ? Math.round(clampPanel(rawCompact, PANEL_MIN, 500))
          : null;
        const rawRatio = Number(parsed.splitRatio);
        const splitRatio = parsed.splitRatio != null && Number.isFinite(rawRatio) && rawRatio > 0 && rawRatio < 1
          ? Math.round(clampPanel(rawRatio, SPLIT_RATIO_MIN, SPLIT_RATIO_MAX) * 10000) / 10000
          : null;
        return { compactPx, splitRatio };
      }
    } catch (_) { /* fall through to legacy migration */ }
  }
  const legacy = readPanelWidth(legacyWidthText);
  if (legacy != null) {
    if (legacy <= 400) {
      return { compactPx: Math.max(PANEL_MIN, legacy), splitRatio: null };
    }
    const migratedRatio = clampPanel(legacy / 1200, 0.34, 0.62);
    return { compactPx: null, splitRatio: Math.round(migratedRatio * 10000) / 10000 };
  }
  return { compactPx: null, splitRatio: null };
}

export function updatePanelSizes(sizes, mode, draggedPx, viewWidth = 0) {
  const prev = sizes && typeof sizes === 'object' ? sizes : { compactPx: null, splitRatio: null };
  const px = Number(draggedPx);
  if (!Number.isFinite(px) || px <= 0) {
    return { compactPx: prev.compactPx ?? null, splitRatio: prev.splitRatio ?? null };
  }
  const v = Number.isFinite(viewWidth) && viewWidth > 0 ? viewWidth : 1200;
  const maxByView = Math.max(PANEL_MIN, Math.round(v - 380));
  if (mode === 'split') {
    const maxPx = Math.min(880, maxByView);
    const minPx = Math.min(360, maxPx);
    const clampedPx = Math.round(clampPanel(px, minPx, maxPx));
    const ratio = clampPanel(clampedPx / v, SPLIT_RATIO_MIN, SPLIT_RATIO_MAX);
    return {
      compactPx: prev.compactPx ?? null,
      splitRatio: Math.round(ratio * 10000) / 10000,
    };
  }
  const maxPx = Math.min(500, maxByView);
  const clampedPx = Math.round(clampPanel(px, PANEL_MIN, maxPx));
  return {
    compactPx: clampedPx,
    splitRatio: prev.splitRatio ?? null,
  };
}

export function resetPanelModeSize(sizes, mode) {
  const prev = sizes && typeof sizes === 'object' ? sizes : { compactPx: null, splitRatio: null };
  if (mode === 'split') {
    return { compactPx: prev.compactPx ?? null, splitRatio: null };
  }
  return { compactPx: null, splitRatio: prev.splitRatio ?? null };
}

export function resolveSplitLayout({
  mode = 'compact',
  sizes = null,
  viewWidth = 0,
  wideOverride = null,
} = {}) {
  const hasView = Number.isFinite(viewWidth) && viewWidth > 0;
  const v = hasView ? viewWidth : 1280;
  const wide = wideOverride != null ? Boolean(wideOverride) : (hasView ? v >= SPLIT_WIDE_MIN : true);

  if (hasView && v < SPLIT_MEDIUM_MIN) {
    const maxSheet = Math.max(200, Math.round(v - 16));
    const cardWidth = Math.min(maxSheet, Math.max(240, Math.min(Math.round(v - 48), 460)));
    const conversationPadX = v >= 520 ? 20 : 16;
    return {
      layoutKind: 'sheet',
      cardWidth,
      slotWidth: cardWidth,
      conversationPadX,
      wide: false,
    };
  }

  const maxByView = Math.max(PANEL_MIN, Math.round(v - 380));
  let cardWidth;
  if (mode === 'split') {
    const savedRatio = sizes && Number.isFinite(Number(sizes.splitRatio)) && Number(sizes.splitRatio) > 0
      ? clampPanel(Number(sizes.splitRatio), SPLIT_RATIO_MIN, SPLIT_RATIO_MAX)
      : null;
    if (savedRatio != null) {
      const maxPx = Math.min(880, maxByView);
      const minPx = Math.min(360, maxPx);
      cardWidth = Math.round(clampPanel(Math.round(v * savedRatio), minPx, maxPx));
    } else if (v >= SPLIT_WIDE_MIN) {
      cardWidth = Math.min(760, Math.max(440, Math.min(Math.round(v * 0.47), Math.round(v - 520))));
    } else {
      cardWidth = Math.round(clampPanel(Math.round(v * 0.48), 380, maxByView));
    }
  } else {
    const savedCompact = sizes && Number.isFinite(Number(sizes.compactPx)) && Number(sizes.compactPx) > 0
      ? Math.round(Number(sizes.compactPx))
      : null;
    if (savedCompact != null) {
      const maxPx = Math.min(500, maxByView);
      cardWidth = Math.round(clampPanel(savedCompact, PANEL_MIN, maxPx));
    } else if (v >= SPLIT_WIDE_MIN) {
      cardWidth = Math.round(clampPanel(Math.round(v * 0.27), 320, 368));
    } else {
      cardWidth = Math.round(clampPanel(Math.round(v * 0.27), 280, Math.min(340, maxByView)));
    }
  }

  const slotWidth = cardWidth + SPLIT_CARD_MARGIN_R + SPLIT_GRIP_OVERHANG;
  const leftWidth = hasView ? Math.max(0, Math.round(v - slotWidth)) : 760;
  const conversationPadX = leftWidth >= 760 ? 28 : leftWidth >= 520 ? 20 : 16;

  return {
    layoutKind: 'inline',
    cardWidth,
    slotWidth,
    conversationPadX,
    wide,
  };
}

// The page's block has window_drag: a left press that reaches it moves the window, and a double-click
// maximizes it. The page keeps every press but those on its header's blank space and words, with this
// handler. Stopping the press also stops the root's own focus-on-press, so `keyboard` (the page's
// focus handle) is given the keyboard here instead, for Esc; where something pressed takes the keyboard
// itself (a message box, a reply's selectable words), the press is kept with no handle.
export function keepPressHandler(keyboard) {
  return (_e, cx) => {
    if (keyboard) keyboard.focus();
    cx.stop_propagation();
  };
}

// A review thread (`pm.py review`: a task with `review_of`) is part of the task it reviews: it leaves
// the list and rides on that task as `review`, so one piece of work is one row and counts once. While
// the review is open the task reads as what the review is: waiting on the user (blocked, with the
// review's `answered`) when the review asks, else in review; a task that itself waits on the user, or
// is paused, or a paused review, leaves the task's own status. A review whose task is not in the list
// stays a row of its own, so nothing goes missing, and so does an open review of a task that is over
// (done, abandoned: nothing of it is in review). pm.py's counts use the same rule (folded_status).
// pm-project, pm-dash, pm-nav and pm-list keep identical copies (pm-project's model.test.mjs checks).
export function foldReviews(tasks) {
  const list = (Array.isArray(tasks) ? tasks : []).filter(Boolean);
  const over = status => ['merged', 'released', 'done', 'abandoned'].includes(status);
  const byId = new Map(list.map(t => [t.id, t]));
  const reviews = new Map(list.filter(t => t.review_of && t.review_of !== t.id && byId.has(t.review_of) &&
    (over(t.status) || !over(byId.get(t.review_of).status))).map(t => [t.review_of, t]));
  if (!reviews.size) return list;
  const fold = (t, r) => {
    const quiet = over(r.status) || r.status === 'paused' || ['blocked', 'paused'].includes(t.status);
    if (quiet) return { ...t, review: r };
    return r.status === 'blocked' ? { ...t, review: r, status: 'blocked', answered: Boolean(r.answered) } : { ...t, review: r, status: 'review' };
  };
  return list.filter(t => !(t.review_of && reviews.get(t.review_of) === t))
    .map(t => reviews.has(t.id) ? fold(t, reviews.get(t.id)) : t);
}

// ---- paging through earlier project conversation and thread logs -------------------------
const SLUG_SHAPE = /^[a-z0-9_][a-z0-9_-]*$/;

// Canonical slug of a project from its `pm.py state` entry: the folder of its conversation log,
// else its PM name without `pm-`, else its project name slugified as pm.py's project_slug.
export function projectSlug(pm) {
  if (!pm || typeof pm !== 'object') return '';
  if (typeof pm.slug === 'string' && SLUG_SHAPE.test(pm.slug)) return pm.slug;
  const conv = String(pm.conversation || '').replace(/\\/g, '/');
  const m = /(?:^|\/)projects\/([^/]+)\/conversation\.jsonl$/.exec(conv);
  if (m && SLUG_SHAPE.test(m[1])) return m[1];
  const fromName = String(pm.name || '').replace(/^pm-/, '');
  if (SLUG_SHAPE.test(fromName)) return fromName;
  const slug = String(pm.project || '').toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 28);
  return slug || (pm.project || pm.name || pm.repo ? 'project' : '');
}

// An older pm.py (for example on a remote machine not yet updated) exits non-zero when asked for `project …`.
export function isOldPmCommand(result) {
  if (!result || result.code === 0) return false;
  const text = `${result.stderr || ''}\n${result.stdout || ''}`;
  return /invalid choice:\s*['"]?(?:project|events|log|tasks|context|library|memory|file|files|save|delete|restore|history|add|retopic|session|change|send|interrupt|folders|set-space)['"]?|unknown (?:project )?command|unrecognized arguments/i.test(text);
}

export const TASKS_PAGE_LIMIT = 30;

export function projectTasksArgv(slug, { status = 'finished', q = '', offset = 0, limit = TASKS_PAGE_LIMIT } = {}) {
  const args = ['project', 'tasks', String(slug), '--status', String(status || 'finished')];
  const query = String(q || '').trim();
  if (query) args.push('--q', query);
  args.push('--offset', String(Math.max(0, Number(offset) || 0)));
  args.push('--limit', String(Math.max(1, Math.min(100, Number(limit) || TASKS_PAGE_LIMIT))));
  return args;
}

export function parseProjectTasksPage(raw) {
  if (!raw || typeof raw !== 'object' || !Array.isArray(raw.tasks)) return null;
  const tasks = raw.tasks.filter(t => t && typeof t === 'object' && typeof t.id === 'string' && t.id);
  const total = Math.max(tasks.length, Number(raw.total) || 0);
  const offset = Math.max(0, Number(raw.offset) || 0);
  const limit = Math.max(1, Number(raw.limit) || TASKS_PAGE_LIMIT);
  const more = Boolean(raw.more);
  return { tasks, total, offset, limit, more };
}

export function normalizeProjectTaskRow(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const id = String(raw.id || raw.task || '').trim();
  if (!id) return null;
  const status = String(raw.status || '');
  const isClosed = CLOSED.includes(status);
  const group = isClosed ? 'finished' : (GROUP[status] || 'parked');
  const num = taskNumber(raw);
  return {
    task: id,
    ...(num ? { number: num } : {}),
    title: String(raw.title || id),
    status,
    tone: isClosed ? 'quiet' : tone(status),
    group,
    cleanup: Boolean(raw.cleanup),
    updated: String(raw.updated || ''),
    branch: String(raw.branch || ''),
    parent: String(raw.parent || ''),
    ...(raw.folder_alias ? { folderAlias: String(raw.folder_alias) } : {}),
    ...(raw.commit ? { commit: String(raw.commit) } : {}),
    ...(raw.landed && typeof raw.landed === 'object' ? { landed: raw.landed } : {}),
    ...(raw.retired ? { retired: true } : {}),
  };
}

export function mergeFinishedRows(baseRows, extraRows) {
  const out = [];
  const seen = new Set();
  for (const row of [...(Array.isArray(baseRows) ? baseRows : []), ...(Array.isArray(extraRows) ? extraRows : [])]) {
    const id = row?.task || row?.id || '';
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(row.task ? row : normalizeProjectTaskRow(row));
  }
  return out.filter(Boolean);
}

function localTaskMatchesQuery(row, query) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return true;
  const tid = String(row.task || row.id || '').toLowerCase();
  const title = String(row.title || '').toLowerCase();
  const branch = String(row.branch || '').toLowerCase();
  const num = taskNumber(row);
  const hashNum = num ? `#${num}` : '';
  const haystack = `${hashNum} ${tid} ${title} ${branch}`;
  for (const tok of q.split(/\s+/)) {
    if (!tok) continue;
    if (/^#\d+$/.test(tok)) {
      const want = Number(tok.slice(1));
      if (num === want || title.includes(tok) || tid.includes(tok)) continue;
      return false;
    }
    if (/^\d+$/.test(tok)) {
      const want = Number(tok);
      if (num === want || tid.includes(tok) || title.includes(tok) || branch.includes(tok)) continue;
      return false;
    }
    if (!haystack.includes(tok)) return false;
  }
  return true;
}

export function filterLocalThreads(pm, tasks, events, query, { retiredParts = [], taskNumbers = null } = {}) {
  const pmName = pm?.name || '';
  const questions = questionOnly(events);
  const byId = new Map();
  const add = raw => {
    if (!raw || typeof raw !== 'object') return;
    const id = String(raw.id || raw.task || '').trim();
    if (!id || raw.review_of || questions.has(id)) return;
    if (String(raw.status || '') === GIVEN_UP) return;
    if (pmName && raw.pm && raw.pm !== pmName) return;
    const num = taskNumber(raw) || (taskNumbers && taskNumber(taskNumbers[id])) || 0;
    const prev = byId.get(id);
    if (!prev || String(raw.updated || '') > String(prev.updated || '')) {
      byId.set(id, normalizeProjectTaskRow({ ...raw, id, ...(num ? { number: num } : {}) }));
    }
  };
  for (const t of Array.isArray(tasks) ? tasks : []) add(t);
  for (const t of Array.isArray(retiredParts) ? retiredParts : []) add(t);
  const named = new Set([...byId.keys(), ...(Array.isArray(events) ? events.map(e => e?.task).filter(Boolean) : [])]);
  for (const e of Array.isArray(events) ? events : []) {
    if (e?.type !== 'thread' || !e.task || questions.has(e.task)) continue;
    if (/-review$/.test(e.task) && named.has(e.task.slice(0, -'-review'.length))) continue;
    if (String(e.status || '') === GIVEN_UP) { byId.delete(e.task); continue; }
    if (byId.has(e.task)) continue;
    const num = taskNumber(e) || (taskNumbers && taskNumber(taskNumbers[e.task])) || 0;
    byId.set(e.task, normalizeProjectTaskRow({
      id: e.task, title: e.title || e.task, status: e.status || '', updated: String(e.at || ''),
      ...(num ? { number: num } : {}),
    }));
  }
  return [...byId.values()]
    .filter(r => r && localTaskMatchesQuery(r, query))
    .sort((a, b) => String(b.updated || '').localeCompare(String(a.updated || '')) || a.task.localeCompare(b.task));
}

// A `--before` byte anchor that no longer matches the file on disk (the log was replaced or rewritten).
export function isReplacedLogError(text) {
  return /was replaced|shorter than|no line ends at byte/i.test(String(text || ''));
}

export function projectEventsArgv(slug, { before = null, after = null, limit = EVENT_LIMIT } = {}) {
  const args = ['project', 'events', String(slug)];
  if (before != null) args.push('--before', String(before));
  else if (after != null) args.push('--after', String(after));
  args.push('--limit', String(limit));
  return args;
}

export function projectLogArgv(id, { before = null, limit = LOG_LIMIT } = {}) {
  const args = ['project', 'log', String(id)];
  if (before != null) args.push('--before', String(before));
  args.push('--limit', String(limit));
  return args;
}

function validEventList(events) {
  return (Array.isArray(events) ? events : [])
    .filter(e => e && typeof e === 'object' && !Array.isArray(e) && typeof e.type === 'string');
}

// Initial window of a project's conversation log, anchored by byte offsets `from` (start) and `offset` (end).
export function freshEventWindow(win) {
  return {
    events: validEventList(win?.events),
    from: Math.max(0, Number(win?.from) || 0),
    offset: Math.max(0, Number(win?.offset) || 0),
    earlier: Boolean(win?.earlier),
  };
}

// Appends newly written events (`--after <held.offset>`) without disturbing earlier pages (`from`, `earlier`).
// When the log file was replaced (`delta.reset`), starts over from the fresh window `delta` carries.
export function appendEventWindow(held, delta) {
  if (!held || delta?.reset) return freshEventWindow(delta);
  const incoming = validEventList(delta?.events);
  const seen = new Set(held.events.map(e => e.offset).filter(Number.isFinite));
  const added = incoming.filter(e => !(Number.isFinite(e.offset) && (e.offset <= held.offset || seen.has(e.offset))));
  const nextOffset = Math.max(held.offset, Number(delta?.offset) || 0);
  if (!added.length && nextOffset === held.offset) return held;
  return { events: [...held.events, ...added], from: held.from, offset: nextOffset, earlier: held.earlier };
}

// Prepends an earlier window (`--before <askedFrom>`) in front of `held`, keeping any events appended meanwhile.
export function prependEventWindow(held, askedFrom, older) {
  if (!held || held.from !== askedFrom) return held;
  const incoming = validEventList(older?.events);
  const seen = new Set(held.events.map(e => e.offset).filter(Number.isFinite));
  const prepended = incoming.filter(e => !(Number.isFinite(e.offset) && seen.has(e.offset)));
  return {
    events: [...prepended, ...held.events],
    from: Math.max(0, Number(older?.from) || 0),
    offset: held.offset,
    earlier: Boolean(older?.earlier),
  };
}

// Merges a thread log page's entries (`{n, at, by, text}`) into `kept` by 0-based index `n`.
// If the task was recreated with fewer entries than previously seen, discards the old entries.
export function keepThreadLog(kept, page) {
  const prev = Array.isArray(kept) ? kept : [];
  const total = Number(page?.total) || 0;
  const base = prev.some(e => e.n >= total) ? [] : prev;
  const byN = new Map(base.map(e => [e.n, e]));
  let changed = byN.size !== prev.length;
  for (const e of Array.isArray(page?.entries) ? page.entries : []) {
    if (e && Number.isInteger(e.n) && e.n >= 0 && !byN.has(e.n)) {
      byN.set(e.n, e);
      changed = true;
    }
  }
  return changed ? [...byN.values()].sort((a, b) => a.n - b.n) : prev;
}

// Joins contiguous earlier entries from `kept` onto `newest` (`{entries, earlier, total}`) without gaps.
export function heldThreadLog(newest, kept) {
  if (!newest || !Array.isArray(newest.entries)) return null;
  const total = Number(newest.total) || 0;
  const byN = new Map((Array.isArray(kept) ? kept : []).filter(e => e.n < total).map(e => [e.n, e]));
  let first = newest.entries.length ? newest.entries[0].n : (Number(newest.earlier) || 0);
  const before = [];
  while (first > 0 && byN.has(first - 1)) before.unshift(byN.get(--first));
  if (!before.length && first === (Number(newest.earlier) || 0)) return newest;
  return { entries: [...before, ...newest.entries], earlier: first, total };
}

// Identifies the oldest content row before loading earlier messages (skipping the top `day` divider,
// which moves further up once earlier events from the same date are prepended).
export function timelineAnchor(blocks) {
  for (const b of Array.isArray(blocks) ? blocks : []) {
    if (!b || b.kind === 'day') continue;
    if (b.kind === 'user') return { kind: 'user', key: b.key, at: b.at || '', text: b.text || '' };
    if (b.kind === 'turn' && Array.isArray(b.parts) && b.parts.length) {
      const p = b.parts.find(x => x.kind === 'pm' || x.kind === 'question' || x.kind === 'decision' || x.kind === 'threads') || b.parts[0];
      return { kind: p.kind, key: p.key, at: p.at || '', text: p.text || '', task: p.task || p.rows?.[0]?.task || '' };
    }
  }
  return null;
}

export function findAnchorBlock(blocks, anchor) {
  if (!anchor || !Array.isArray(blocks)) return -1;
  const byKey = blocks.findIndex(b => b && (b.key === anchor.key || b.parts?.some(p => p.key === anchor.key)));
  if (byKey >= 0) return byKey;
  return blocks.findIndex(b => {
    if (!b || b.kind === 'day') return false;
    if (anchor.kind === 'user') return b.kind === 'user' && b.at === anchor.at && (b.text || '') === anchor.text;
    return b.kind === 'turn' && b.parts?.some(p => p.kind === anchor.kind && (p.at || '') === anchor.at &&
      (anchor.task ? (p.task || p.rows?.[0]?.task || '') === anchor.task : (p.text || '') === anchor.text));
  });
}

// ---- Library & Memory panels: allow-listed docs/research/instructions, topics/types, search, edit & chunking ----
export const DOC_MAX_BYTES = 1_000_000;
export const DOC_INITIAL_BYTES = 64_000;
export const DOC_CHUNK_BYTES = 6_000;
export const DOC_CACHE_LIMIT = 32;
export const LIBRARY_ROOTS = new Set(['docs', 'repo_docs', 'research', 'instructions']);
export const MEMORY_ROOTS = new Set(['memory', 'personal']);
export const ALL_DOC_ROOTS = new Set(['docs', 'repo_docs', 'research', 'instructions', 'memory', 'personal', 'project', 'user', 'repo']);
const REPO_DOCS_DESIGN_SEGMENTS = new Set(['design', 'specs', 'spec', 'adr', 'decisions', 'rfcs', 'rfc', 'architecture']);
export const MEMORY_TOPICS = ['architecture', 'ui', 'workflow', 'ops', 'reference', 'pitfalls'];
export const DEFAULT_FOLDED_TOPICS = new Set(['pitfalls']);
export const PROJECT_MEMORY_TYPES = ['project', 'feedback', 'reference', 'pitfall'];
export const PERSONAL_MEMORY_TYPES = ['user', 'feedback', 'reference'];
export const DEFAULT_TYPE_TOPIC = {
  pitfall: 'pitfalls',
  reference: 'reference',
  feedback: 'workflow',
  user: 'workflow',
  project: 'architecture',
};
export const LIBRARY_DROP_TEXT_EXT = new Set([
  'md', 'markdown', 'txt', 'text', 'log', 'json', 'jsonl', 'ndjson',
  'csv', 'tsv', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'xml',
  'html', 'htm', 'css', 'js', 'mjs', 'cjs', 'ts', 'tsx', 'jsx',
  'py', 'go', 'rs', 'rb', 'java', 'kt', 'swift', 'c', 'h', 'cc',
  'cpp', 'hpp', 'cs', 'php', 'lua', 'sh', 'bash', 'zsh', 'fish',
  'ps1', 'bat', 'sql', 'diff', 'patch', 'tex', 'rst', 'org', 'adoc',
  'mod', 'sum', 'lock',
]);

export function projectLibraryArgv(slug) {
  return ['project', 'library', String(slug)];
}

export function projectMemoryArgv(slug) {
  return ['project', 'memory', String(slug)];
}

export function projectFileArgv(slug, root, path) {
  return ['project', 'file', '--root', String(root), '--', String(slug), String(path)];
}

export function projectSaveArgv(slug, root, path, { text = null, fromFile = null, ifVersion = null } = {}) {
  const args = ['project', 'save', '--root', String(root)];
  if (fromFile != null) args.push(`--from=${String(fromFile)}`);
  else args.push(`--text=${String(text ?? '')}`);
  if (ifVersion) args.push(`--if-version=${String(ifVersion)}`);
  args.push('--', String(slug), String(path));
  return args;
}

export function projectDeleteArgv(slug, root, path, { ifVersion = null, why = '' } = {}) {
  const args = ['project', 'delete', '--root', String(root)];
  if (ifVersion) args.push(`--if-version=${String(ifVersion)}`);
  if (why) args.push(`--why=${String(why)}`);
  args.push('--', String(slug), String(path));
  return args;
}

export function projectRestoreArgv(slug, root, path, { version = '' } = {}) {
  const args = ['project', 'restore', '--root', String(root)];
  if (version) args.push(`--version=${String(version)}`);
  args.push('--', String(slug), String(path));
  return args;
}

export function projectHistoryArgv(slug, root, path = '') {
  const args = ['project', 'history', '--root', String(root), '--', String(slug)];
  if (path) args.push(String(path));
  return args;
}

export function projectAddArgv(slug, source, { folder = '', name = '', replace = false } = {}) {
  const args = ['project', 'add'];
  if (folder) args.push(`--folder=${String(folder)}`);
  if (name) args.push(`--name=${String(name)}`);
  if (replace) args.push('--replace');
  args.push('--', String(slug), String(source));
  return args;
}

export function projectRetopicArgv(slug, name, { topic = '', type = '', personal = false } = {}) {
  const args = ['project', 'retopic'];
  if (topic) args.push(`--topic=${String(topic)}`);
  if (type) args.push(`--type=${String(type)}`);
  if (personal) args.push('--personal');
  args.push('--', String(slug), String(name));
  return args;
}

export function adoptCandidateArgv(repo, candidate, { drop = false } = {}) {
  const args = ['adopt', '--repo', String(repo)];
  if (drop) args.push('--drop');
  args.push('--', String(candidate));
  return args;
}

export const SAVE_INLINE_BYTES = 60_000;
export const REMOTE_CHUNK_BYTES = 48_000;
export const REMOTE_MKTEMP_ARGV = ['sh', ['-c', 'd="${TMPDIR:-/tmp}"; mktemp "${d%/}/pm-edit.XXXXXX"']];
export function remoteAppendChunkArgv(tmpPath, chunk) {
  return ['sh', ['-c', 'printf "%s" "$2" >> "$1"', 'sh', String(tmpPath), String(chunk)]];
}
export function utf8ByteLength(text) {
  const s = String(text ?? '');
  let bytes = 0;
  for (let i = 0; i < s.length;) {
    const cp = s.codePointAt(i);
    bytes += cp <= 0x7f ? 1 : cp <= 0x7ff ? 2 : cp <= 0xffff ? 3 : 4;
    i += cp > 0xffff ? 2 : 1;
  }
  return bytes;
}
export function chunkUtf8Text(text, maxBytes = REMOTE_CHUNK_BYTES) {
  const s = String(text ?? '');
  if (!s) return [];
  const cap = Math.max(4, Number(maxBytes) || REMOTE_CHUNK_BYTES);
  const chunks = [];
  let start = 0;
  let bytes = 0;
  for (let i = 0; i < s.length;) {
    const cp = s.codePointAt(i);
    const step = cp > 0xffff ? 2 : 1;
    const cpBytes = cp <= 0x7f ? 1 : cp <= 0x7ff ? 2 : cp <= 0xffff ? 3 : 4;
    if (bytes + cpBytes > cap && i > start) {
      chunks.push(s.slice(start, i));
      start = i;
      bytes = 0;
    }
    bytes += cpBytes;
    i += step;
  }
  if (start < s.length) chunks.push(s.slice(start));
  return chunks;
}
export function parseVersionConflict(result) {
  if (!result || result.code !== 4) return null;
  for (const raw of [result.stdout, result.stderr]) {
    const text = String(raw || '').trim();
    if (!text) continue;
    try {
      const parsed = JSON.parse(text);
      if (parsed && parsed.error === 'conflict') {
        return { conflict: true, message: String(parsed.message || ''), current: String(parsed.current || '') };
      }
    } catch (_) { /* try next */ }
  }
  return { conflict: true, message: String(result.stderr || result.stdout || '').trim(), current: '' };
}

export const INTERNAL_PROJECT_FILES = new Set([
  'conversation.jsonl', 'receipts.json', 'receipts.lock', 'delivered.json', 'delivered.lock', 'deliver.lock',
  'turn-cause.json', 'taken-in.json', 'takeover.json', 'pm-settings.json',
  'schedules.json', 'dudu-attachments.json', 'task-seq.json', 'agy-transcript.json',
  'pm-turn.json', 'pm-turn.lock', 'pm-turn-journal.jsonl', 'pm-turn-journal.1.jsonl', 'pm-turn.beat',
  'applied-reports.json', 'applied-reports.lock', 'applied-reports.jsonl', 'applied-reports.0001.jsonl', 'mailboxes',
]);

function splitProjectRel(raw, ledgerHome, slug) {
  const norm = p => String(p || '').replace(/\\/g, '/').replace(/\/+$/, '');
  const home = norm(ledgerHome);
  const p = norm(raw);
  if (!p) return null;
  if (home && p === `${home}/projects`) return [];
  const projPrefix = home ? `${home}/projects/${slug}` : '';
  let rel = '';
  if (projPrefix) {
    if (p === projPrefix) return [];
    if (!p.startsWith(`${projPrefix}/`)) return null;
    rel = p.slice(projPrefix.length + 1);
  } else {
    const m = /(?:^|\/)projects\/([^/]+)(?:\/(.*))?$/.exec(p);
    if (!m || m[1] !== slug) return null;
    if (!m[2]) return [];
    rel = m[2];
  }
  return rel.split('/').filter(Boolean);
}

export function isLibraryRelevantChange(paths, { ledgerHome = '', slug = '' } = {}) {
  const list = Array.isArray(paths) ? paths : [];
  if (!list.length || !slug) return false;
  return list.some(raw => {
    const parts = splitProjectRel(raw, ledgerHome, slug);
    if (!parts) return false;
    if (!parts.length) return true;
    if (parts.some(seg => seg.startsWith('.'))) return false;
    const lastLow = parts[parts.length - 1].toLowerCase();
    if (lastLow.endsWith('.lock') || lastLow.endsWith('.tmp')) return false;
    const top = parts[0].toLowerCase();
    if (parts.length === 1) return top === 'decisions.md' || top === 'library.json' || top === 'research-sources.json' || top === 'docs' || top === 'research';
    return top === 'docs' || top === 'research';
  });
}

export function isMemoryRelevantChange(layer, paths, { ledgerHome = '', slug = '' } = {}) {
  const list = Array.isArray(paths) ? paths : [];
  if (!list.length) return false;
  const norm = p => String(p || '').replace(/\\/g, '/').replace(/\/+$/, '');
  const home = norm(ledgerHome);
  if (layer === 'project') {
    if (!slug) return false;
    return list.some(raw => {
      const parts = splitProjectRel(raw, ledgerHome, slug);
      if (!parts) return false;
      if (!parts.length) return true;
      if (parts[0].toLowerCase() !== 'memory') return false;
      if (parts.some(seg => seg.startsWith('.'))) return false;
      const lastLow = parts[parts.length - 1].toLowerCase();
      return !lastLow.endsWith('.lock') && !lastLow.endsWith('.tmp');
    });
  }
  if (layer === 'personal' || layer === 'user') {
    const memPrefix = home ? `${home}/memory` : '';
    return list.some(raw => {
      const p = norm(raw);
      if (!p) return false;
      let rel = '';
      if (memPrefix) {
        if (p === memPrefix) return true;
        if (!p.startsWith(`${memPrefix}/`)) return false;
        rel = p.slice(memPrefix.length + 1);
      } else {
        const m = /(?:^|\/)memory(?:\/(.*))?$/.exec(p);
        if (!m) return false;
        if (!m[1]) return true;
        rel = m[1];
      }
      const parts = rel.split('/').filter(Boolean);
      if (!parts.length) return true;
      if (parts.some(seg => seg.startsWith('.'))) return false;
      const lastLow = parts[parts.length - 1].toLowerCase();
      return !lastLow.endsWith('.lock') && !lastLow.endsWith('.tmp');
    });
  }
  return false;
}

export function isContextRelevantChange(root, paths, { ledgerHome = '', slug = '' } = {}) {
  const list = Array.isArray(paths) ? paths : [];
  if (!list.length) return false;
  const norm = p => String(p || '').replace(/\\/g, '/').replace(/\/+$/, '');
  const home = norm(ledgerHome);
  if (root === 'project') {
    if (!slug) return false;
    const base = home ? `${home}/projects` : '';
    return list.some(raw => {
      const p = norm(raw);
      if (base && p === base) return true;
      const parts = splitProjectRel(raw, ledgerHome, slug);
      if (!parts) return false;
      if (!parts.length) return true;
      if (parts.some(seg => seg.startsWith('.'))) return false;
      const lastLow = parts[parts.length - 1].toLowerCase();
      if (lastLow === 'conversation.jsonl' || lastLow.endsWith('.lock') || lastLow.endsWith('.tmp')) return false;
      if (parts[0].toLowerCase() === 'attachments' || parts[0].toLowerCase() === 'mailboxes') return false;
      if (/^(?:applied-reports|pm-turn-journal)\./i.test(lastLow)) return false;
      if (parts.length === 1 && INTERNAL_PROJECT_FILES.has(parts[0].toLowerCase())) return false;
      return true;
    });
  }
  if (root === 'user') return isMemoryRelevantChange('personal', list, { ledgerHome });
  return false;
}

export const contextKey = file => (file?.root && file?.path ? `${file.root}/${file.path}` : '');

function validDocItem(f) {
  if (!f || typeof f !== 'object' || !ALL_DOC_ROOTS.has(f.root)) return null;
  if (typeof f.path !== 'string' || !f.path || typeof f.kind !== 'string') return null;
  return {
    root: f.root,
    path: f.path,
    kind: f.kind,
    size: Math.max(0, Number(f.size) || 0),
    modified: String(f.modified || ''),
    ...(f.version ? { version: String(f.version) } : {}),
    ...(f.writable !== undefined ? { writable: Boolean(f.writable) } : {}),
    ...(f.type ? { type: String(f.type) } : {}),
    ...(f.topic ? { topic: String(f.topic) } : {}),
    ...(f.title ? { title: String(f.title) } : {}),
    ...(f.summary ? { summary: String(f.summary) } : {}),
    ...(f.description ? { description: String(f.description) } : {}),
    ...(f.show !== undefined ? { show: String(f.show) } : {}),
    ...(f.source ? { source: String(f.source) } : {}),
    ...(f.task ? { task: String(f.task) } : {}),
    ...(f.task_title ? { task_title: String(f.task_title) } : {}),
    ...(f.archive ? { archive: true } : {}),
    ...(f.hidden ? { hidden: true } : {}),
    ...(Number.isFinite(f.entries) ? { entries: Number(f.entries) } : {}),
    ...(f.published !== undefined ? { published: f.published } : {}),
    ...(f.superseded_by ? { superseded_by: String(f.superseded_by) } : {}),
  };
}

export function validLibraryPayload(raw) {
  const roots = Array.isArray(raw?.roots) ? raw.roots.filter(r => r && typeof r.id === 'string') : [];
  const rawFiles = Array.isArray(raw) ? raw : Array.isArray(raw?.files) ? raw.files : [];
  const files = rawFiles.map(validDocItem).filter(f => f && LIBRARY_ROOTS.has(f.root));
  return { roots, files };
}

export function validMemoryPayload(raw) {
  const topicsRaw = Array.isArray(raw?.topics) ? raw.topics : [];
  const topics = topicsRaw.length
    ? topicsRaw.filter(t => t && typeof t.id === 'string').map(t => ({ id: t.id, folded: Boolean(t.folded) }))
    : MEMORY_TOPICS.map(id => ({ id, folded: DEFAULT_FOLDED_TOPICS.has(id) }));
  const types = Array.isArray(raw?.types) ? raw.types.filter(t => t && typeof t.id === 'string') : [];
  const layers = Array.isArray(raw?.layers) ? raw.layers.filter(l => l && typeof l.id === 'string') : [];
  const rawFiles = Array.isArray(raw?.files) ? raw.files : [];
  const files = rawFiles
    .filter(f => f && typeof f === 'object' && typeof f.path === 'string' && f.path)
    .map(f => {
      const layer = f.layer === 'personal' || f.root === 'personal' ? 'personal' : 'project';
      const root = f.root === 'personal' || layer === 'personal' ? 'personal' : 'memory';
      const type = String(f.type || (layer === 'personal' ? 'user' : 'project'));
      const topic = String(f.topic || DEFAULT_TYPE_TOPIC[type] || 'architecture');
      return {
        layer,
        root,
        path: String(f.path),
        kind: 'memory',
        name: String(f.name || fileName(f.path).replace(/\.md$/i, '')),
        type,
        topic,
        description: String(f.description || ''),
        modified: String(f.modified || ''),
        size: Math.max(0, Number(f.size) || 0),
        by: String(f.by || ''),
        version: String(f.version || ''),
        writable: f.writable !== false,
        show: 'text',
        ...(f.quote ? { quote: String(f.quote) } : {}),
        ...(f.quote_checked ? { quote_checked: String(f.quote_checked) } : {}),
        ...(f.verified ? { verified: String(f.verified) } : {}),
        ...(f.task ? { task: String(f.task) } : {}),
        ...(f.expires ? { expires: String(f.expires) } : {}),
        ...(f.checked ? { checked: String(f.checked) } : {}),
        ...(f.topic_inferred ? { topic_inferred: true } : {}),
        ...(Number.isFinite(f.stale_days) ? { stale_days: Number(f.stale_days) } : {}),
        ...(f.expired ? { expired: true } : {}),
      };
    });
  const candidates = (Array.isArray(raw?.candidates) ? raw.candidates : [])
    .filter(c => c && typeof c === 'object' && typeof c.name === 'string' && c.name)
    .map(c => ({
      worker: String(c.worker || ''),
      name: String(c.name),
      path: String(c.path || `${c.worker || 'worker'}/${c.name}.md`),
      type: String(c.type || 'project'),
      description: String(c.description || ''),
      modified: String(c.modified || ''),
    }));
  const history = {
    project: Math.max(0, Number(raw?.history?.project) || 0),
    personal: Math.max(0, Number(raw?.history?.personal) || 0),
  };
  const rawDream = raw?.dream && typeof raw.dream === 'object' ? raw.dream : null;
  const rawSum = rawDream?.summary && typeof rawDream.summary === 'object' ? rawDream.summary : null;
  const dream = rawDream ? {
    auto: Boolean(rawDream.auto),
    running: Boolean(rawDream.running),
    last_at: String(rawDream.last_at || ''),
    summary: rawSum ? {
      merged: Math.max(0, Number(rawSum.merged) || 0),
      removed: Math.max(0, Number(rawSum.removed) || 0),
      forgotten: Math.max(0, Number(rawSum.forgotten) || 0),
      adopted: Math.max(0, Number(rawSum.adopted) || 0),
      dropped: Math.max(0, Number(rawSum.dropped) || 0),
      refused: Math.max(0, Number(rawSum.refused) || 0),
      flags: Math.max(0, Number(rawSum.flags) || 0),
    } : null,
    failures: Math.max(0, Number(rawDream.failures) || 0),
    pending: Math.max(0, Number(rawDream.pending) || 0),
  } : null;
  return { topics, types, layers, files, candidates, history, dream };
}

export function formatDreamStatus(dream, lang = 'en', nowMs = Date.now(), clockOffsetMs = 0) {
  if (!dream || typeof dream !== 'object') return '';
  if (dream.running) return word(lang, 'dreamRunning');
  const lastAt = String(dream.last_at || '').trim();
  if (lastAt) {
    const parsed = eventTime(lastAt);
    let when = lastAt;
    if (parsed > 0 && Number.isFinite(nowMs)) {
      const elapsed = Math.max(0, nowMs - (parsed - (Number(clockOffsetMs) || 0)));
      when = elapsed < 60_000 ? word(lang, 'dreamJustNow') : word(lang, 'dreamAgo', age(elapsed, lang));
    }
    const parts = [word(lang, 'dreamLastAgo', when)];
    const sum = dream.summary && typeof dream.summary === 'object' ? dream.summary : null;
    if (sum) {
      if (sum.merged > 0) parts.push(word(lang, 'dreamMerged', sum.merged));
      if (sum.adopted > 0) parts.push(word(lang, 'dreamAdopted', sum.adopted));
      if (sum.forgotten > 0) parts.push(word(lang, 'dreamArchived', sum.forgotten));
      if (sum.flags > 0) parts.push(word(lang, 'dreamFlags', sum.flags));
    }
    return parts.join(' · ');
  }
  const pending = Math.max(0, Number(dream.pending) || 0);
  if (pending > 0) return word(lang, 'dreamPending', pending);
  return '';
}

export function formatBytes(bytes) {
  const n = Math.max(0, Number(bytes) || 0);
  if (n < 1024) return `${Math.round(n)} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(n >= 10240 ? 0 : 1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

export function contextDay(iso, currentYear = '') {
  const s = String(iso || '').trim();
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) return s.slice(0, 10);
  return !currentYear || m[1] === currentYear ? `${m[2]}-${m[3]}` : `${m[1]}-${m[2]}-${m[3]}`;
}

export function formatHistoryStamp(stamp, currentYear = '') {
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/.exec(String(stamp || '').trim());
  if (!m) return String(stamp || '');
  const date = !currentYear || m[1] === currentYear ? `${m[2]}-${m[3]}` : `${m[1]}-${m[2]}-${m[3]}`;
  return `${date} ${m[4]}:${m[5]}`;
}

export function researchFallbackTitle(path) {
  let clean = String(path || '').replace(/^(?:evidence|docs\/research|published)\//i, '');
  if (!clean) return '';
  if (/(?:^|\/)README\.md$/i.test(clean)) {
    const parts = clean.split('/').filter(Boolean);
    return parts.length >= 2 ? parts[parts.length - 2] : clean.replace(/\.md$/i, '');
  }
  return clean.replace(/\.(md|markdown)$/i, '');
}

export function libraryDocTitle(file) {
  if (!file) return '';
  if (file.root === 'research') return String(file.title || '').trim() || researchFallbackTitle(file.path) || fileName(file.path);
  if (file.root === 'instructions') return String(file.path || '');
  return fileName(file.path || '');
}

export function contextDocTitle(file) {
  if (!file) return '';
  if (file.kind === 'memory' || file.root === 'memory' || file.root === 'personal') {
    return String(file.name || fileName(file.path || '').replace(/\.md$/i, ''));
  }
  if (file.root === 'research' || file.root === 'instructions') return libraryDocTitle(file);
  return fileName(file.path || '');
}

export function memoryTypeLabel(lang, type) {
  const key = `memType_${type || 'project'}`;
  const got = word(lang, key);
  return got === key ? String(type || '') : got;
}

export function topicLabel(lang, topic) {
  const key = `topic_${topic || 'architecture'}`;
  const got = word(lang, key);
  return got === key ? String(topic || '') : got;
}

export function contextKindLabel(lang, file, count = 0) {
  if (!file) return word(lang, 'kindFile');
  if (file.kind === 'folder') return word(lang, 'kindFolderCount', count);
  if (file.kind === 'memory') return memoryTypeLabel(lang, file.type || 'project');
  if (file.archive) {
    return file.entries
      ? `${word(lang, 'archiveLabel')} · ${word(lang, 'archiveEntries', file.entries)}`
      : word(lang, 'archiveLabel');
  }
  const base = fileName(file.path);
  if (base === 'MEMORY.md') return word(lang, 'kindMemoryIndex');
  if ((file.root === 'project' || file.root === 'docs') && file.path === 'decisions.md') return word(lang, 'kindDecisions');
  if (file.root === 'project' && file.path === 'handover.md') return word(lang, 'kindHandover');
  if (file.kind === 'md' || file.kind === 'markdown') return 'Markdown';
  if (/^(png|jpe?g|gif|webp|bmp|avif)$/i.test(file.kind)) return word(lang, 'kindImage');
  return file.kind && file.kind !== 'file' && /^[a-z0-9]{1,8}$/i.test(file.kind) ? file.kind.toUpperCase() : word(lang, 'kindFile');
}

const NON_TEXT_EXT = /\.(png|jpe?g|gif|webp|bmp|avif|svg|pdf)$/i;

export function contextShowMode(file, path = '') {
  const p = String(file?.path || path || '');
  if (file?.show === 'image' || NON_TEXT_EXT.test(p)) return 'binary';
  if (file && Number(file.size) > DOC_MAX_BYTES) return 'large';
  return 'text';
}

export function contextReadable(file) {
  if (!file || file.kind === 'folder') return false;
  return contextShowMode(file, file.path) === 'text';
}

export function isWritableDoc(file) {
  if (!file || file.kind === 'folder') return false;
  if (file.archive) return false;
  if (file.root === 'repo_docs' || file.root === 'research' || file.root === 'instructions' || file.root === 'repo') return false;
  if (file.writable !== undefined) return Boolean(file.writable);
  return file.root === 'docs' || file.root === 'memory' || file.root === 'personal';
}

export function contextFileError(lang, error, { isMemory = false, isRepo = false } = {}) {
  const msg = String(error || '').trim();
  if (/not a text file/i.test(msg)) return word(lang, 'docNotText');
  if (/too large/i.test(msg)) return word(lang, 'docTooLarge');
  if (/no such document|no memory|no project/i.test(msg)) {
    return word(lang, isRepo ? 'repoFileNotFound' : isMemory ? 'memNotFound' : 'docNotFound');
  }
  return word(lang, 'docReadError', msg);
}

function unquoteScalar(raw) {
  const s = String(raw ?? '').trim();
  if (s.length >= 2 && s.startsWith('"') && s.endsWith('"')) {
    try {
      const v = JSON.parse(s);
      if (typeof v === 'string') return v;
    } catch (_) { /* fall through */ }
    return s.slice(1, -1);
  }
  if (s.length >= 2 && s.startsWith("'") && s.endsWith("'")) return s.slice(1, -1).replace(/''/g, "'");
  return s;
}

const KNOWN_FRONTMATTER_KEYS = new Set([
  'name', 'description', 'node_type', 'type', 'topic', 'modified', 'by', 'quote', 'quote_checked', 'verified', 'checked', 'expires', 'task',
]);

// Parses YAML-style frontmatter (`--- ... ---`), flattening top-level and `metadata:` indented fields.
export function parseFrontmatter(text) {
  const raw = String(text ?? '');
  const normalized = raw.replace(/\r\n/g, '\n');
  if (!normalized.startsWith('---\n')) return { hasFrontmatter: false, fields: {}, extra: {}, body: raw };
  const closeAt = normalized.indexOf('\n---', 3);
  if (closeAt < 0) return { hasFrontmatter: false, fields: {}, extra: {}, body: raw };
  const afterFence = closeAt + 4;
  if (afterFence < normalized.length && normalized[afterFence] !== '\n') {
    return { hasFrontmatter: false, fields: {}, extra: {}, body: raw };
  }
  const head = normalized.slice(4, closeAt);
  const body = normalized.slice(afterFence < normalized.length ? afterFence + 1 : afterFence).replace(/^\n+/, '').replace(/\s+$/, '');
  const fields = {};
  const extra = {};
  let inMeta = false;
  for (const line of head.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const colon = trimmed.indexOf(':');
    if (colon <= 0) continue;
    const key = trimmed.slice(0, colon).trim();
    const val = trimmed.slice(colon + 1);
    const top = line[0] !== ' ' && line[0] !== '\t';
    if (top) inMeta = key === 'metadata' && !val.trim();
    if (!top && !inMeta) continue;
    if (top && inMeta) continue;
    const parsedVal = unquoteScalar(val);
    fields[key] = parsedVal;
    if (!top && !KNOWN_FRONTMATTER_KEYS.has(key)) extra[key] = parsedVal;
  }
  return { hasFrontmatter: true, fields, extra, body };
}

const MEMORY_META_OUT = ['modified', 'by', 'quote', 'quote_checked', 'verified', 'checked', 'expires', 'task'];
const MEMORY_BARE_KEYS = new Set(['node_type', 'type', 'topic', 'modified', 'quote_checked', 'checked', 'expires']);

export const MEMORY_SLUG_MAX = 40;

export function slugifyMemoryName(raw) {
  return String(raw || '')
    .toLowerCase()
    .replace(/\.md$/i, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, MEMORY_SLUG_MAX)
    .replace(/-+$/, '');
}

export function uniqueMemorySlug(baseSlug, taken) {
  const base = slugifyMemoryName(baseSlug) || 'memory';
  const used = new Set();
  if (taken) {
    for (const item of taken) used.add(String(item || '').toLowerCase());
  }
  if (!used.has(base)) return base;
  for (let n = 2; ; n++) {
    const suffix = `-${n}`;
    const prefix = base.slice(0, Math.max(1, MEMORY_SLUG_MAX - suffix.length)).replace(/-+$/, '') || 'm';
    const cand = `${prefix}${suffix}`;
    if (!used.has(cand)) return cand;
  }
}

export function buildMemoryMarkdown({ name, description, type, topic, body, existingRaw = '' }) {
  const parsed = existingRaw ? parseFrontmatter(existingRaw) : { hasFrontmatter: false, fields: {}, extra: {} };
  const prev = parsed.fields || {};
  const slug = slugifyMemoryName(name) || prev.name || 'memory';
  const desc = squash(description) || squash(prev.description) || slug;
  const cleanBody = String(body ?? '').replace(/\r\n/g, '\n').trim() || desc;
  const metaEntries = [['node_type', 'memory']];
  for (const [k, v] of Object.entries(parsed.extra || {})) {
    if (v) metaEntries.push([k, v]);
  }
  metaEntries.push(['type', String(type || prev.type || 'project')]);
  metaEntries.push(['topic', String(topic || prev.topic || DEFAULT_TYPE_TOPIC[type] || 'architecture')]);
  for (const k of MEMORY_META_OUT) {
    if (prev[k]) metaEntries.push([k, prev[k]]);
  }
  const lines = [
    '---',
    `name: ${slug}`,
    `description: ${JSON.stringify(desc)}`,
    'metadata:',
    ...metaEntries.map(([k, v]) => `  ${k}: ${MEMORY_BARE_KEYS.has(k) ? String(v) : JSON.stringify(String(v))}`),
    '---',
    '',
    cleanBody,
    '',
  ];
  return lines.join('\n');
}

export function memoryFromDroppedFile(fileNameRaw, rawText, { layer = 'project', topic = 'architecture', type = 'project', slug: slugOverride = '' } = {}) {
  const text = String(rawText ?? '').replace(/\r\n/g, '\n');
  const stem = fileName(fileNameRaw).replace(/\.(md|markdown|txt|text)$/i, '');
  const slug = slugifyMemoryName(slugOverride) || slugifyMemoryName(stem) || `memory-${Date.now().toString(36)}`;
  const parsed = parseFrontmatter(text);
  if (parsed.hasFrontmatter && parsed.fields.description) {
    const chosenType = parsed.fields.type || (layer === 'personal' ? 'user' : type);
    const chosenTopic = parsed.fields.topic || topic;
    return {
      slug,
      text: buildMemoryMarkdown({
        name: slug,
        description: parsed.fields.description,
        type: chosenType,
        topic: chosenTopic,
        body: parsed.body,
        existingRaw: text,
      }),
    };
  }
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
  const first = (lines[0] || slug).replace(/^#+\s*/, '').trim();
  const desc = first.slice(0, 180) || slug;
  return {
    slug,
    text: buildMemoryMarkdown({
      name: slug,
      description: desc,
      type: layer === 'personal' ? 'user' : type,
      topic,
      body: text.trim() || desc,
    }),
  };
}

export function retopicPlan(mem, { nextTopic = '', nextType = '' } = {}) {
  if (!mem) return { topic: '', type: '' };
  const isPersonal = mem.layer === 'personal' || mem.root === 'personal';
  if (isPersonal) {
    const allowed = PERSONAL_MEMORY_TYPES;
    const type = nextType && allowed.includes(nextType) ? nextType : mem.type;
    const topic = nextTopic && nextTopic !== 'pitfalls' ? nextTopic : (mem.topic || DEFAULT_TYPE_TOPIC[type] || 'workflow');
    return { topic, type };
  }
  let type = nextType || mem.type || 'project';
  let topic = nextTopic || mem.topic || DEFAULT_TYPE_TOPIC[type] || 'architecture';
  if (nextTopic === 'pitfalls' && !nextType) {
    type = 'pitfall';
  } else if (nextType === 'pitfall') {
    topic = 'pitfalls';
  } else if (nextTopic && nextTopic !== 'pitfalls' && type === 'pitfall') {
    type = 'project';
  } else if (nextType && nextType !== 'pitfall' && topic === 'pitfalls') {
    topic = DEFAULT_TYPE_TOPIC[type] || 'architecture';
  }
  return { topic, type };
}

function docRank(file, dir) {
  if (dir === '' && file.archive) return 99;
  if (file.kind === 'folder') return 0;
  if (file.superseded_by) return 50;
  return 1;
}

function buildDocsRows(items, closed, lang, currentYear) {
  const visible = items.filter(f => !(f.archive && f.hidden));
  const childrenOf = dir => visible.filter(f => {
    if (!dir) return !f.path.includes('/');
    return f.path.startsWith(`${dir}/`) && !f.path.slice(dir.length + 1).includes('/');
  });
  const rows = [];
  const walk = (dir, depth) => {
    const here = childrenOf(dir);
    here.sort((a, b) => {
      const ra = docRank(a, dir), rb = docRank(b, dir);
      if (ra !== rb) return ra - rb;
      if (a.kind === 'folder') return a.path.localeCompare(b.path);
      return String(b.modified || '').localeCompare(String(a.modified || '')) || a.path.localeCompare(b.path);
    });
    for (const f of here) {
      const key = contextKey(f);
      const folder = f.kind === 'folder';
      const count = folder ? childrenOf(f.path).length : 0;
      const open = folder ? !closed.has(key) : false;
      const title = libraryDocTitle(f);
      rows.push({
        key,
        depth,
        folder,
        open,
        name: fileName(f.path),
        title,
        desc: f.title && f.title !== title ? f.title : '',
        kindLabel: contextKindLabel(lang, f, count),
        modified: contextDay(f.modified, currentYear),
        size: folder ? '' : formatBytes(f.size),
        readable: contextReadable(f),
        writable: isWritableDoc(f),
        readOnly: !folder && !isWritableDoc(f),
        archive: Boolean(f.archive),
        supersededBy: f.superseded_by || '',
        entries: f.entries || 0,
        root: f.root,
        path: f.path,
        file: f,
        count,
      });
      if (folder && open) walk(f.path, depth + 1);
    }
  };
  walk('', 0);
  return rows;
}

function isDesignFolderPath(path) {
  return String(path || '').split('/').some(seg => REPO_DOCS_DESIGN_SEGMENTS.has(seg.toLowerCase()));
}

function buildRepoDocsRows(items, closed, lang, currentYear) {
  const fileItems = items.filter(f => f.kind !== 'folder');
  if (!fileItems.length) return [];
  // Strip redundant leading `docs/` or `doc/` shell visually unless it collides with another file's path
  // or the project uses multi-prefix monorepo includes (e.g. `packages/core/docs/...`).
  const hasMultiPrefixInclude = fileItems.some(f => {
    const segs = f.path.split('/');
    return segs.length >= 3 && segs[0] !== 'docs' && segs[0] !== 'doc';
  });
  const stripShell = !hasMultiPrefixInclude && (() => {
    const seen = new Set();
    for (const f of fileItems) {
      const v = f.path.replace(/^(?:docs|doc)\//, '');
      if (!v || seen.has(v)) return false;
      seen.add(v);
    }
    return true;
  })();

  const folderMap = new Map();
  const childrenByParent = new Map();
  const addChild = (parentKey, node) => {
    let list = childrenByParent.get(parentKey);
    if (!list) { list = []; childrenByParent.set(parentKey, list); }
    list.push(node);
  };

  for (const f of fileItems) {
    const stripped = stripShell && /^(?:docs|doc)\//.test(f.path);
    const visualPath = stripped ? f.path.replace(/^(?:docs|doc)\//, '') : f.path;
    const shellPrefix = stripped ? f.path.slice(0, f.path.indexOf('/') + 1) : '';
    const vParts = visualPath.split('/');
    let parentKey = '';
    for (let i = 0; i < vParts.length - 1; i++) {
      const vDir = vParts.slice(0, i + 1).join('/');
      if (!folderMap.has(vDir)) {
        const realPath = shellPrefix + vDir;
        const folderNode = {
          kind: 'folder',
          vDir,
          name: vParts[i],
          realPath,
          key: `repo_docs/${realPath}`,
          design: isDesignFolderPath(realPath),
        };
        folderMap.set(vDir, folderNode);
        addChild(parentKey, folderNode);
      }
      parentKey = vDir;
    }
    addChild(parentKey, { kind: 'file', file: f });
  }

  const largeTree = fileItems.length > 15;
  const rows = [];
  const walk = (parentKey, depth) => {
    const here = childrenByParent.get(parentKey) || [];
    here.sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === 'folder' ? -1 : 1;
      if (a.kind === 'folder') {
        if (a.design !== b.design) return a.design ? -1 : 1;
        return a.name.localeCompare(b.name);
      }
      return String(b.file.modified || '').localeCompare(String(a.file.modified || ''))
        || a.file.path.localeCompare(b.file.path);
    });
    for (const node of here) {
      if (node.kind === 'folder') {
        const count = (childrenByParent.get(node.vDir) || []).length;
        const defaultClosed = largeTree && !node.design;
        const open = defaultClosed ? closed.has(node.key) : !closed.has(node.key);
        const syntheticFile = { root: 'repo_docs', path: node.realPath, kind: 'folder', writable: false };
        rows.push({
          key: node.key,
          depth,
          folder: true,
          open,
          defaultClosed,
          name: node.name,
          title: node.name,
          desc: '',
          kindLabel: contextKindLabel(lang, syntheticFile, count),
          modified: '',
          size: '',
          readable: false,
          writable: false,
          readOnly: true,
          archive: false,
          root: 'repo_docs',
          path: node.realPath,
          file: syntheticFile,
          count,
        });
        if (open) walk(node.vDir, depth + 1);
      } else {
        const f = node.file;
        const title = libraryDocTitle(f);
        const desc = f.title && f.title !== title ? f.title : (f.summary || '');
        rows.push({
          key: contextKey(f),
          depth,
          folder: false,
          open: false,
          name: fileName(f.path),
          title,
          desc,
          kindLabel: contextKindLabel(lang, f),
          modified: contextDay(f.modified, currentYear),
          size: formatBytes(f.size),
          readable: contextReadable(f),
          writable: false,
          readOnly: true,
          archive: false,
          task: f.task || '',
          taskTitle: f.task_title || '',
          root: 'repo_docs',
          path: f.path,
          file: f,
          count: 0,
        });
      }
    }
  };
  walk('', 0);
  return rows;
}

// Organizes Library items into allow-listed sections:
// 1. Documents (`docs`, editable, with non-hidden `decisions.md` archive at the end)
// 2. Repo docs (`repo_docs`, read-only curated design docs and guides from the repository)
// 3. Research reports (`research`, read-only, H1 title + summary + source thread link)
// 4. Instructions (`instructions`, read-only repo files like CLAUDE.md / AGENTS.md)
export function libraryGroups(rawFiles, closed = new Set(), lang = 'en', currentYear = '') {
  const { roots, files } = validLibraryPayload(rawFiles);
  const closedSet = closed instanceof Set ? closed : new Set(closed || []);
  const docsItems = files.filter(f => f.root === 'docs');
  const repoDocsItems = files.filter(f => f.root === 'repo_docs');
  const researchItems = files.filter(f => f.root === 'research').sort((a, b) =>
    String(b.modified || '').localeCompare(String(a.modified || '')) || a.path.localeCompare(b.path));
  const instrItems = files.filter(f => f.root === 'instructions').sort((a, b) => a.path.localeCompare(b.path));

  const sections = [];
  const docsRows = buildDocsRows(docsItems, closedSet, lang, currentYear);
  const docsFileCount = docsItems.filter(f => f.kind !== 'folder' && !(f.archive && f.hidden)).length;
  sections.push({
    id: 'docs',
    title: word(lang, 'libraryGroupDocs'),
    count: docsFileCount,
    writable: true,
    readOnly: false,
    rows: docsRows,
  });
  const repoDocsFileCount = repoDocsItems.filter(f => f.kind !== 'folder').length;
  if (repoDocsFileCount > 0) {
    const rdRoot = roots.find(r => r.id === 'repo_docs') || null;
    sections.push({
      id: 'repo_docs',
      title: word(lang, 'libraryGroupRepoDocs'),
      count: repoDocsFileCount,
      shown: repoDocsFileCount,
      total: Number(rdRoot?.total) || repoDocsFileCount,
      truncated: Boolean(rdRoot?.truncated),
      writable: false,
      readOnly: true,
      rows: buildRepoDocsRows(repoDocsItems, closedSet, lang, currentYear),
    });
  }
  if (researchItems.length) {
    sections.push({
      id: 'research',
      title: word(lang, 'libraryGroupResearch'),
      count: researchItems.length,
      writable: false,
      readOnly: true,
      rows: researchItems.map(f => ({
        key: contextKey(f),
        depth: 0,
        folder: false,
        open: false,
        name: fileName(f.path),
        title: libraryDocTitle(f),
        desc: f.summary || f.description || '',
        kindLabel: word(lang, 'libraryGroupResearch'),
        modified: contextDay(f.modified, currentYear),
        size: formatBytes(f.size),
        readable: contextReadable(f),
        writable: false,
        readOnly: true,
        task: f.task || '',
        taskTitle: f.task_title || '',
        published: Boolean(f.published),
        source: f.source || '',
        root: f.root,
        path: f.path,
        file: f,
        count: 0,
      })),
    });
  }
  if (instrItems.length) {
    sections.push({
      id: 'instructions',
      title: word(lang, 'libraryGroupInstructions'),
      count: instrItems.length,
      writable: false,
      readOnly: true,
      rows: instrItems.map(f => {
        const title = libraryDocTitle(f);
        return {
          key: contextKey(f),
          depth: 0,
          folder: false,
          open: false,
          name: fileName(f.path),
          title,
          desc: f.title && f.title !== title ? f.title : '',
          kindLabel: contextKindLabel(lang, f),
          modified: contextDay(f.modified, currentYear),
          size: formatBytes(f.size),
          readable: contextReadable(f),
          writable: false,
          readOnly: true,
          root: f.root,
          path: f.path,
          file: f,
          count: 0,
        };
      }),
    });
  }
  return sections;
}

function buildMemoryRow(m, lang, currentYear, depth = 1) {
  const layerLabel = word(lang, m.layer === 'personal' ? 'memLayerUser' : 'memLayerProject');
  const typeLabel = memoryTypeLabel(lang, m.type);
  return {
    key: contextKey(m),
    depth,
    name: m.name,
    title: m.name,
    desc: m.description || '',
    type: m.type,
    typeLabel,
    topic: m.topic,
    topicLabel: topicLabel(lang, m.topic),
    layer: m.layer,
    layerLabel,
    kindLabel: typeLabel,
    modified: contextDay(m.modified, currentYear),
    size: formatBytes(m.size),
    readable: true,
    writable: m.writable !== false,
    expired: Boolean(m.expired),
    staleDays: m.stale_days || 0,
    dimmed: m.type === 'pitfall' || Boolean(m.expired),
    root: m.root,
    path: m.path,
    file: m,
  };
}

// Organizes Memory page data:
// - Project memory (expanded by default) with 6 fixed topics: primary topics expanded, `pitfalls` separated, dimmed, folded
// - Optional Candidates folder (dimmed, folded by default, shown only when non-empty)
// - Personal memory (collapsed by default)
export function memoryGroups(rawPayload, {
  foldOverrides = new Map(),
  projectOpen = true,
  personalOpen = false,
  candidatesOpen = false,
} = {}, lang = 'en', currentYear = '') {
  const payload = validMemoryPayload(rawPayload);
  const overrides = foldOverrides instanceof Map ? foldOverrides : new Map(foldOverrides || []);
  const byModifiedDesc = (a, b) => String(b.modified || '').localeCompare(String(a.modified || '')) || a.name.localeCompare(b.name);
  const projectFiles = payload.files.filter(f => f.layer === 'project').sort(byModifiedDesc);
  const personalFiles = payload.files.filter(f => f.layer === 'personal').sort(byModifiedDesc);

  const primaryTopics = [];
  const foldedTopics = [];
  for (const t of payload.topics) {
    const items = projectFiles.filter(f => f.topic === t.id);
    if (!items.length) continue;
    const topicKey = `topic:${t.id}`;
    const open = overrides.has(topicKey) ? Boolean(overrides.get(topicKey)) : !t.folded;
    const group = {
      id: t.id,
      key: topicKey,
      title: topicLabel(lang, t.id),
      count: items.length,
      open,
      dimmed: Boolean(t.folded),
      rows: items.map(m => buildMemoryRow(m, lang, currentYear, 1)),
    };
    if (t.folded) foldedTopics.push(group);
    else primaryTopics.push(group);
  }
  const knownTopics = new Set(payload.topics.map(t => t.id));
  const extraFiles = projectFiles.filter(f => !knownTopics.has(f.topic));
  if (extraFiles.length) {
    const topicKey = 'topic:other';
    primaryTopics.push({
      id: 'other',
      key: topicKey,
      title: topicLabel(lang, 'architecture'),
      count: extraFiles.length,
      open: overrides.has(topicKey) ? Boolean(overrides.get(topicKey)) : true,
      dimmed: false,
      rows: extraFiles.map(m => buildMemoryRow(m, lang, currentYear, 1)),
    });
  }

  return {
    project: {
      id: 'project',
      title: word(lang, 'memoryGroupProject'),
      count: projectFiles.length,
      open: Boolean(projectOpen),
      primaryTopics,
      foldedTopics,
    },
    candidates: {
      id: 'candidates',
      title: word(lang, 'memoryGroupCandidates'),
      count: payload.candidates.length,
      open: Boolean(candidatesOpen),
      dimmed: true,
      rows: payload.candidates.map(c => ({
        ...c,
        typeLabel: memoryTypeLabel(lang, c.type),
        modified: contextDay(c.modified, currentYear),
      })),
    },
    personal: {
      id: 'personal',
      title: word(lang, 'memoryGroupPersonal'),
      count: personalFiles.length,
      open: Boolean(personalOpen),
      rows: personalFiles.map(m => buildMemoryRow(m, lang, currentYear, 0)),
    },
    historyCounts: payload.history,
  };
}

export function searchTerms(query) {
  return String(query ?? '').toLowerCase().split(/\s+/).filter(Boolean);
}

export function excerptAround(text, terms, around = 38) {
  const flat = squash(text);
  if (!flat) return '';
  const low = flat.toLowerCase();
  const hits = (terms || []).map(t => low.indexOf(t)).filter(i => i >= 0).sort((a, b) => a - b);
  const at = hits[0] ?? 0;
  const start = Math.max(0, at - around);
  const end = Math.min(flat.length, at + around * 2);
  return (start > 0 ? '…' : '') + flat.slice(start, end).trim() + (end < flat.length ? '…' : '');
}

export function highlightSegments(text, terms) {
  const str = String(text ?? '');
  const list = [...new Set((Array.isArray(terms) ? terms : searchTerms(terms))
    .map(t => String(t || '').toLowerCase()).filter(Boolean))];
  if (!str) return [];
  if (!list.length) return [{ text: str, match: false }];
  const low = str.toLowerCase();
  if (low.length !== str.length) return [{ text: str, match: false }];
  const intervals = [];
  for (const term of list) {
    let from = 0;
    while (from < low.length) {
      const idx = low.indexOf(term, from);
      if (idx < 0) break;
      intervals.push([idx, idx + term.length]);
      from = idx + Math.max(1, term.length);
    }
  }
  if (!intervals.length) return [{ text: str, match: false }];
  intervals.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
  const merged = [];
  for (const iv of intervals) {
    const prev = merged[merged.length - 1];
    if (prev && iv[0] <= prev[1]) {
      if (iv[1] > prev[1]) prev[1] = iv[1];
    } else {
      merged.push([iv[0], iv[1]]);
    }
  }
  const out = [];
  let pos = 0;
  for (const [start, end] of merged) {
    if (start > pos) out.push({ text: str.slice(pos, start), match: false });
    out.push({ text: str.slice(start, end), match: true });
    pos = end;
  }
  if (pos < str.length) out.push({ text: str.slice(pos), match: false });
  return out;
}

export function windowAroundMatch(text, terms, maxChars = 96, around = 32) {
  const flat = squash(text);
  if (!flat) return '';
  if (flat.length <= maxChars) return flat;
  const list = Array.isArray(terms) ? terms : searchTerms(terms);
  const low = flat.toLowerCase();
  const hits = list.map(t => low.indexOf(t)).filter(i => i >= 0).sort((a, b) => a - b);
  const at = hits[0] ?? -1;
  if (at < 0 || at < Math.floor(maxChars * 0.6)) {
    return `${flat.slice(0, maxChars).trimEnd()}…`;
  }
  return excerptAround(flat, list, around);
}

export function searchLibrary(rawFiles, query, docCache = null, lang = 'en', currentYear = '') {
  const terms = searchTerms(query);
  if (!terms.length) return [];
  const { files } = validLibraryPayload(rawFiles);
  const list = files.filter(f => f.kind !== 'folder' && !(f.archive && f.hidden));
  const scored = [];
  for (const f of list) {
    const key = contextKey(f);
    const title = libraryDocTitle(f);
    const kind = f.root === 'research'
      ? word(lang, 'libraryGroupResearch')
      : f.root === 'repo_docs'
        ? word(lang, 'libraryGroupRepoDocs')
        : contextKindLabel(lang, f);
    const entry = docCache instanceof Map ? docCache.get(key) : null;
    const cached = isFreshDocEntry(entry, f) ? entry.text : '';
    const body = cached ? parseFrontmatter(cached).body : '';
    const titleHay = `${title} ${f.path}`.toLowerCase();
    const metaDesc = f.summary || f.description || (f.title && f.title !== title ? f.title : '');
    const descHay = `${metaDesc} ${f.task_title || ''} ${f.task || ''} ${kind}`.toLowerCase();
    const fullHay = `${titleHay} ${descHay} ${body.toLowerCase()}`;
    if (!terms.every(term => fullHay.includes(term))) continue;

    const inTitle = terms.every(term => titleHay.includes(term));
    const inDesc = terms.every(term => `${titleHay} ${descHay}`.includes(term));
    const rank = (inTitle ? 0 : inDesc ? 1 : 2) + (f.superseded_by ? 1 : 0);
    let desc = metaDesc;
    if (!inDesc && body) desc = excerptAround(body, terms);
    else if (desc && terms.some(term => desc.toLowerCase().includes(term)) && desc.length > 90) desc = excerptAround(desc, terms);
    scored.push({
      rank,
      modified: String(f.modified || ''),
      row: {
        key,
        depth: 0,
        folder: false,
        open: false,
        name: fileName(f.path),
        title,
        desc,
        kindLabel: kind,
        modified: contextDay(f.modified, currentYear),
        size: formatBytes(f.size),
        readable: contextReadable(f),
        writable: isWritableDoc(f),
        readOnly: !isWritableDoc(f),
        archive: Boolean(f.archive),
        supersededBy: f.superseded_by || '',
        entries: f.entries || 0,
        task: f.task || '',
        taskTitle: f.task_title || '',
        published: Boolean(f.published),
        root: f.root,
        path: f.path,
        file: f,
        count: 0,
      },
    });
  }
  scored.sort((a, b) => a.rank - b.rank || b.modified.localeCompare(a.modified) || a.row.key.localeCompare(b.row.key));
  return scored.map(x => x.row);
}

export function searchMemory(rawPayload, query, docCache = null, lang = 'en', currentYear = '') {
  const terms = searchTerms(query);
  if (!terms.length) return [];
  const { files } = validMemoryPayload(rawPayload);
  const scored = [];
  for (const m of files) {
    const key = contextKey(m);
    const typeLbl = memoryTypeLabel(lang, m.type);
    const topicLbl = topicLabel(lang, m.topic);
    const layerLbl = word(lang, m.layer === 'personal' ? 'memLayerUser' : 'memLayerProject');
    const entry = docCache instanceof Map ? docCache.get(key) : null;
    const cached = isFreshDocEntry(entry, m) ? entry.text : '';
    const body = cached ? parseFrontmatter(cached).body : '';
    const titleHay = `${m.name} ${m.path}`.toLowerCase();
    const descHay = `${m.description} ${m.topic} ${topicLbl} ${m.type} ${typeLbl} ${layerLbl} ${m.quote || ''} ${m.verified || ''} ${m.by || ''}`.toLowerCase();
    const fullHay = `${titleHay} ${descHay} ${body.toLowerCase()}`;
    if (!terms.every(term => fullHay.includes(term))) continue;

    const inTitle = terms.every(term => titleHay.includes(term));
    const inDesc = terms.every(term => `${titleHay} ${descHay}`.includes(term));
    const rank = inTitle ? 0 : inDesc ? 1 : 2;
    const row = buildMemoryRow(m, lang, currentYear, 0);
    if (!inDesc && body) row.desc = excerptAround(body, terms);
    else if (row.desc && terms.some(term => row.desc.toLowerCase().includes(term)) && row.desc.length > 90) row.desc = excerptAround(row.desc, terms);
    scored.push({ rank, modified: String(m.modified || ''), row });
  }
  scored.sort((a, b) => a.rank - b.rank || b.modified.localeCompare(a.modified) || a.row.key.localeCompare(b.row.key));
  return scored.map(x => x.row);
}

export function makeDocCacheEntry(got, meta = null) {
  const text = String(got?.text ?? '');
  const size = Number(got?.size) || text.length;
  const version = String(got?.version || meta?.version || '');
  return meta
    ? { text, size, version, modified: String(meta.modified || ''), metaSize: Number(meta.size) }
    : { text, size, version, modified: null, metaSize: null };
}

export function isFreshDocEntry(entry, meta = null) {
  if (!entry || typeof entry.text !== 'string') return false;
  if (!meta) return true;
  if (entry.version && meta.version) return entry.version === String(meta.version);
  if (entry.modified === undefined && entry.metaSize === undefined) return true;
  return entry.modified === String(meta.modified || '') && entry.metaSize === Number(meta.size);
}

export function makeDocFailEntry(error, meta = null) {
  return {
    error: String(error || ''),
    missing: !meta,
    version: String(meta?.version || ''),
    modified: String(meta?.modified || ''),
    metaSize: meta ? Number(meta.size) : null,
  };
}

export function isFreshDocFailure(entry, meta = null) {
  if (!entry || typeof entry.error !== 'string') return false;
  if (!meta) return Boolean(entry.missing);
  if (entry.missing) return false;
  if (entry.version && meta.version) return entry.version === String(meta.version);
  return entry.modified === String(meta.modified || '') && entry.metaSize === Number(meta.size);
}

export function reconcileDocCache(cache, files) {
  const next = new Map();
  if (!(cache instanceof Map) || !cache.size) return next;
  const byKey = new Map(
    (Array.isArray(files) ? files : []).map(validDocItem).filter(f => f && f.kind !== 'folder').map(f => [contextKey(f), f]),
  );
  for (const [k, entry] of cache.entries()) {
    const meta = byKey.get(k);
    if (meta && isFreshDocEntry(entry, meta)) next.set(k, entry);
  }
  return next;
}

export function reconcileDocFailures(failures, files) {
  const next = new Map();
  if (!(failures instanceof Map) || !failures.size) return next;
  const byKey = new Map(
    (Array.isArray(files) ? files : []).map(validDocItem).filter(f => f && f.kind !== 'folder').map(f => [contextKey(f), f]),
  );
  for (const [k, entry] of failures.entries()) {
    const meta = byKey.get(k) || null;
    if (isFreshDocFailure(entry, meta)) next.set(k, entry);
  }
  return next;
}

export function keepDocCache(cache, key, entry, limit = DOC_CACHE_LIMIT) {
  const next = new Map(cache instanceof Map ? cache : []);
  if (!key) return next;
  next.delete(key);
  next.set(key, entry);
  while (next.size > limit) {
    const oldest = next.keys().next().value;
    next.delete(oldest);
  }
  return next;
}

// Splits Markdown into bounded fence-safe chunks so long files (decisions.md, specs) render smoothly
// and in-document find can jump to the matching block.
export function markdownChunks(text, maxChars = DOC_CHUNK_BYTES) {
  const prepared = viewMarkdown(String(text ?? '').replace(/\r\n/g, '\n')).trim();
  if (!prepared) return [];
  const lines = prepared.split('\n');
  const chunks = [];
  let buf = [];
  let len = 0;
  let fence = '';
  const flush = () => {
    const joined = buf.join('\n').trim();
    if (joined) chunks.push(joined);
    buf = [];
    len = 0;
  };
  const softMin = Math.max(1200, Math.floor(maxChars * 0.55));
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    if (fence) {
      buf.push(line);
      len += line.length + 1;
      if (trimmed.startsWith(fence)) fence = '';
      continue;
    }
    const opens = FENCE.exec(line);
    if (opens) {
      if (len >= softMin) flush();
      fence = opens[1];
      buf.push(line);
      len += line.length + 1;
      continue;
    }
    const isHeading = /^#{1,4}\s/.test(line);
    const isTopList = /^(?:[-*+]|\d{1,9}[.)])\s/.test(line);
    const prevBlank = buf.length > 0 && !buf[buf.length - 1].trim();
    const inTable = trimmed.startsWith('|') && buf.length > 0 && buf[buf.length - 1].trim().startsWith('|');
    if (!inTable && ((isHeading && len >= 900) || (prevBlank && len >= softMin) || (isTopList && len >= Math.min(1400, maxChars)) || len >= maxChars * 2)) {
      flush();
    }
    buf.push(line);
    len += line.length + 1;
  }
  flush();
  return chunks;
}

export function codeChunks(text, ext = '', maxChars = DOC_CHUNK_BYTES) {
  const clean = String(text ?? '').replace(/\r\n/g, '\n').replace(/\n+$/, '');
  if (!clean) return [];
  const langTag = /^[a-z0-9_+-]{1,16}$/i.test(ext) && ext !== 'file' && ext !== 'text' && ext !== 'txt' ? ext.toLowerCase() : '';
  const lines = clean.split('\n');
  const out = [];
  let buf = [];
  let len = 0;
  const wrap = part => {
    const runs = (part.match(/`+/g) || []).map(s => s.length);
    const ticks = '`'.repeat(Math.max(3, ...runs.map(n => n + 1)));
    return `${ticks}${langTag}\n${part}\n${ticks}`;
  };
  for (const line of lines) {
    if (buf.length > 0 && len + line.length + 1 > maxChars) {
      out.push(wrap(buf.join('\n')));
      buf = [];
      len = 0;
    }
    buf.push(line);
    len += line.length + 1;
  }
  if (buf.length) out.push(wrap(buf.join('\n')));
  return out;
}

function sliceOnLineBoundary(text, maxChars) {
  if (!maxChars || text.length <= maxChars) return { shown: text, rest: 0 };
  const nl = text.lastIndexOf('\n', maxChars);
  const cut = nl >= Math.floor(maxChars * 0.5) ? nl : maxChars;
  return { shown: text.slice(0, cut), rest: text.length - cut };
}

// Pure view-model for reading one Library document or Memory entry (supports full-file >64KB find).
export function documentView(file, rawText, { lang = 'en', today = '', shownBytes = DOC_INITIAL_BYTES, findQuery = '' } = {}) {
  const path = String(file?.path || '');
  const title = contextDocTitle(file || { path });
  const currentYear = String(today || '').slice(0, 4);
  const parsed = parseFrontmatter(rawText);
  const f = parsed.fields;
  const isMemory = file?.kind === 'memory' || file?.root === 'memory' || file?.root === 'personal'
    || (parsed.hasFrontmatter && (f.node_type === 'memory' || Boolean(f.description && (f.type || f.by || f.quote || f.verified))));
  const rawBody = isMemory || (parsed.hasFrontmatter && /\.(md|markdown)$/i.test(path)) ? parsed.body : String(rawText ?? '');
  const leadText = isMemory ? (f.description || file?.description || '').trim() : '';
  const distinctBody = isMemory && rawBody.trim() === leadText ? '' : rawBody;
  const combinedSource = isMemory
    ? [leadText, distinctBody].filter(Boolean).join('\n\n')
    : distinctBody;

  const baseSlice = sliceOnLineBoundary(combinedSource, shownBytes);
  let rest = baseSlice.rest;
  const isMarkdown = isMemory || /\.(md|markdown)$/i.test(path);
  const ext = (path.includes('.') ? path.split('.').pop() : '') || file?.kind || '';
  const chunker = text => (isMarkdown ? markdownChunks(text) : codeChunks(text, ext));
  let chunks = chunker(baseSlice.shown);

  const terms = searchTerms(findQuery);
  let matchIndices = [];
  let matchCount = 0;
  if (terms.length) {
    if (rest > 0) {
      const fullChunks = chunker(combinedSource);
      const fullMatches = fullChunks.flatMap((c, i) => (terms.every(term => c.toLowerCase().includes(term)) ? [i] : []));
      if (fullMatches.length) {
        const lastHit = fullMatches[fullMatches.length - 1];
        const take = Math.min(fullChunks.length, Math.max(chunks.length, lastHit + 1));
        chunks = fullChunks.slice(0, take);
        rest = take >= fullChunks.length ? 0 : fullChunks.slice(take).reduce((n, c) => n + c.length, 0);
        matchIndices = fullMatches;
        const lineHits = combinedSource.split('\n').filter(l => terms.every(term => l.toLowerCase().includes(term))).length;
        matchCount = Math.max(matchIndices.length, lineHits);
      }
    } else {
      matchIndices = chunks.flatMap((c, i) => (terms.every(term => c.toLowerCase().includes(term)) ? [i] : []));
      const lineHits = matchIndices.length
        ? baseSlice.shown.split('\n').filter(l => terms.every(term => l.toLowerCase().includes(term))).length
        : 0;
      matchCount = Math.max(matchIndices.length, lineHits);
    }
  }

  const quotes = isMemory && f.quote ? f.quote.split(' / ').map(q => q.trim()).filter(Boolean) : [];
  const quoteStatus = isMemory && quotes.length
    ? (f.quote_checked === 'true' ? 'checked' : f.quote_checked === 'false' ? 'unchecked' : '')
    : '';
  const expires = isMemory && f.expires ? String(f.expires).slice(0, 10) : '';
  const expired = Boolean(expires && today && expires < today.slice(0, 10));
  const isPersonal = file?.layer === 'personal' || file?.root === 'personal' || file?.root === 'user';
  const memType = isMemory ? (f.type || file?.type || (isPersonal ? 'user' : 'project')) : '';
  const memTopic = isMemory && !isPersonal ? (f.topic || file?.topic || DEFAULT_TYPE_TOPIC[memType] || 'architecture') : '';
  const writable = isWritableDoc(file);

  return {
    title,
    isMemory,
    isMarkdown,
    isPersonal,
    writable,
    readOnly: !writable,
    layerLabel: isPersonal ? word(lang, 'memLayerUser') : word(lang, 'memLayerProject'),
    type: memType,
    typeLabel: isMemory ? memoryTypeLabel(lang, memType) : contextKindLabel(lang, file),
    topic: memTopic,
    topicLabel: isMemory && !isPersonal ? topicLabel(lang, memTopic) : '',
    description: leadText,
    bodyText: rawBody,
    modified: contextDay(f.modified || file?.modified || '', currentYear),
    byLabel: isMemory && f.by ? word(lang, 'memBy', f.by) : '',
    quotes,
    quoteStatus,
    verified: isMemory && f.verified ? word(lang, 'memVerified', f.verified) : '',
    checked: isMemory && f.checked ? word(lang, 'memChecked', String(f.checked).slice(0, 10)) : '',
    expires: expires ? word(lang, 'memExpires', expires) : '',
    expired,
    sourceTask: file?.task ? String(file.task) : '',
    sourceTaskTitle: file?.task_title ? String(file.task_title) : '',
    published: Boolean(file?.published),
    supersededBy: file?.superseded_by ? String(file.superseded_by) : '',
    chunks,
    matchIndices,
    matchCount,
    remainingBytes: rest,
    remainingLabel: rest > 0 ? formatBytes(rest) : '',
  };
}

// Resolves a relative link clicked inside a Library or Memory Markdown document
// to `{root, path}` when that file is in the known files list, else null.
export function resolveContextLink(currentDoc, url, files) {
  const raw = String(url || '').trim();
  if (!raw || /^[a-z][a-z0-9+.-]*:/i.test(raw) || raw.startsWith('#') || raw.startsWith('/')) return null;
  let clean = raw.split(/[?#]/)[0];
  try { clean = decodeURIComponent(clean); } catch (_) { return null; }
  const root = currentDoc?.root || 'docs';
  const dirParts = String(currentDoc?.path || '').split('/');
  dirParts.pop();
  for (const seg of clean.split('/')) {
    if (!seg || seg === '.') continue;
    if (seg === '..') {
      if (!dirParts.length) return null;
      dirParts.pop();
    } else {
      dirParts.push(seg);
    }
  }
  const resolved = dirParts.join('/');
  if (!resolved) return null;
  const list = (Array.isArray(files) ? files : []).map(validDocItem).filter(Boolean);
  const hit = list.find(f => f.kind !== 'folder' && f.root === root && f.path === resolved);
  if (hit) return { root: hit.root, path: hit.path };
  if (root === 'repo_docs') {
    if (resolved.startsWith('docs/research/')) {
      const pubRel = `published/${resolved.slice('docs/research/'.length)}`;
      const resHit = list.find(f => f.kind !== 'folder' && f.root === 'research'
        && (f.published === pubRel || f.path === pubRel));
      if (resHit) return { root: 'research', path: resHit.path };
    }
    return { root: 'repo', path: resolved };
  }
  return null;
}

// ---- context usage & worker session conversation (`pm.py state` context_tokens, `pm.py project session`) ----

export const DEFAULT_COMPACT_TOKENS = 200_000;
export const DEFAULT_ROTATE_TOKENS = DEFAULT_COMPACT_TOKENS;
export const SESSION_LIMIT = 120, SESSION_KEEP = 600, SESSION_SLACK = 200;
export const SESSION_POLL_LOCAL_MS = 4_000, SESSION_POLL_REMOTE_MS = 20_000;

export function resolveCompactTokens(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value > 0 ? Math.floor(value) : 0;
  return DEFAULT_COMPACT_TOKENS;
}
export const resolveRotateTokens = resolveCompactTokens;

export function contextTokens(value) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

export function contextShort(tokens) {
  const n = contextTokens(tokens);
  if (!n) return '';
  return n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
}

export function contextLabel(lang, tokens) {
  const short = contextShort(tokens);
  return short ? word(lang, 'contextUsage', short) : '';
}

// Matches `pm.py` (`COMPACT_TOKENS`): 'over' strictly above `compact_tokens`, 'near' strictly above 80%.
export function pmContextLevel(tokens, compactTokens = DEFAULT_COMPACT_TOKENS) {
  const n = contextTokens(tokens), limit = resolveCompactTokens(compactTokens);
  if (!n) return 'none';
  if (!limit) return 'normal';
  if (n > limit) return 'over';
  return n > Math.floor(limit * 0.8) ? 'near' : 'normal';
}

export function pmContextTip(lang, tokens, compactTokens = DEFAULT_COMPACT_TOKENS) {
  const short = contextShort(tokens), limit = resolveCompactTokens(compactTokens);
  if (!short) return '';
  const cap = contextShort(limit);
  if (!limit || !cap) return word(lang, 'pmContextNormal', short, '');
  const level = pmContextLevel(tokens, limit);
  if (level === 'over') return word(lang, 'pmContextOver', short, cap);
  if (level === 'near') return word(lang, 'pmContextNear', short, cap);
  return word(lang, 'pmContextNormal', short, cap);
}

export function workerContextTip(lang, tokens) {
  const n = contextTokens(tokens);
  return n ? word(lang, 'workerContextTip', n) : '';
}

export function isMissingSessionModule(result) {
  if (!result || result.code === 0) return false;
  return /pm_sessions\.py is missing/i.test(`${result.stderr || ''}\n${result.stdout || ''}`);
}

export function isUnsupportedSessionError(result) {
  if (!result || result.code === 0) return false;
  return /is not supported/i.test(`${result.stderr || ''}\n${result.stdout || ''}`);
}

export function isQuietNoSession(result) {
  if (!result || result.code === 0) return false;
  const text = `${result.stderr || ''}\n${result.stdout || ''}`;
  return /is not supported|no session (?:found|recorded)|transcript not found|no unambiguous \w+ session|no task |not a task id/i.test(text);
}

export function isReplacedSessionError(text) {
  return /was replaced|shorter than|no line of the transcript starts at byte/i.test(String(text || ''));
}

// Runtimes whose session transcripts `pm.py project session` can read.
export const SUPPORTED_SESSION_KINDS = Object.freeze(new Set(['claude', 'agy']));

export function normalizeSessionKind(kind) {
  const k = String(kind || '').trim().toLowerCase();
  return k === 'antigravity' ? 'agy' : k;
}

export function supportedSessionKind(kind) {
  return SUPPORTED_SESSION_KINDS.has(normalizeSessionKind(kind));
}

// Effective runtime kind of a thread: current worker's kind first (`engine.kind`, `worker.kind`,
// or top-level `kind`), falling back to a recorded `session.kind` when no worker kind is set.
export function taskSessionKind(stateTask, task = null) {
  const fromTask = taskEngine(task)?.kind || (typeof task?.kind === 'string' ? task.kind : '');
  const fromState = taskEngine(stateTask)?.kind || (typeof stateTask?.kind === 'string' ? stateTask.kind : '');
  const active = normalizeSessionKind(fromTask || fromState);
  if (active) return active;
  const fromTaskSession = task?.session && typeof task.session === 'object' ? task.session.kind : '';
  const fromStateSession = stateTask?.session && typeof stateTask.session === 'object' ? stateTask.session.kind : '';
  return normalizeSessionKind(fromTaskSession || fromStateSession);
}

// True when the task's current worker is known to be an agent runtime whose transcripts
// `pm.py project session` does not read (e.g. `codex`, `pi`), so no subprocess needs to be spawned.
export function knownUnsupportedSession(task, stateTask = null) {
  const kind = taskSessionKind(stateTask, task);
  return Boolean(kind && !supportedSessionKind(kind));
}

// Whether the thread detail panel should show the Log / Conversation switcher.
export function sessionTabAvailable({
  sessionSupported = true,
  stateTask = null,
  task = null,
  threadId = '',
  sessionTask = '',
  sessionState = '',
  hasSession = false,
} = {}) {
  if (!sessionSupported || knownUnsupportedSession(task, stateTask)) return false;
  const knownSupported = supportedSessionKind(taskSessionKind(stateTask, task));
  const hasTokens = contextTokens(stateTask?.context_tokens) > 0;
  if (sessionTask && sessionTask === threadId) {
    if (sessionState === 'unavailable') return false;
    if (sessionState === 'ready' || sessionState === 'empty') return true;
    if (sessionState === 'loading' || sessionState === 'error') {
      return Boolean(hasSession || hasTokens || knownSupported);
    }
  }
  return Boolean(hasTokens || knownSupported);
}

// Whether `syncThreadSession` should actively read/poll the thread's session transcript now.
export function wantThreadSession({
  threadTab = 'log',
  stateTask = null,
  task = null,
  threadId = '',
  sessionTask = '',
  sessionState = '',
} = {}) {
  if (threadTab !== 'session') return false;
  const hasTokens = contextTokens(stateTask?.context_tokens) > 0;
  const knownSupported = supportedSessionKind(taskSessionKind(stateTask, task));
  return Boolean(
    hasTokens
    || knownSupported
    || sessionTask !== threadId
    || sessionState === 'ready'
    || sessionState === 'empty'
  );
}

export function projectSessionArgv(id, { before = null, after = null, limit = SESSION_LIMIT } = {}) {
  const args = ['project', 'session', String(id)];
  if (before != null) args.push('--before', String(before));
  else if (after != null) args.push('--after', String(after));
  args.push('--limit', String(limit));
  return args;
}

function validSessionItems(items) {
  return (Array.isArray(items) ? items : [])
    .filter(item => item && typeof item === 'object' && !Array.isArray(item) && typeof item.type === 'string');
}

// Joins two adjacent stretches of a session (`older` then `newer`): an orphan `result` in `newer` whose
// `tool` call is in `older` attaches its output and error onto that `tool` call instead of standing alone.
export function joinSessionItems(older, newer) {
  const left = validSessionItems(older), right = validSessionItems(newer);
  const calls = new Map();
  left.forEach((item, idx) => { if (item.type === 'tool' && item.id) calls.set(item.id, idx); });
  const out = [...left];
  const rest = [];
  let attached = false;
  for (const item of right) {
    const idx = item.type === 'result' && item.id ? calls.get(item.id) : undefined;
    if (idx === undefined) {
      rest.push(item);
      continue;
    }
    out[idx] = { ...out[idx], output: String(item.output ?? ''), error: Boolean(item.error) };
    calls.delete(item.id);
    attached = true;
  }
  return attached || rest.length ? [...out, ...rest] : left;
}

// Updates held session state after an answer from `pm.py project session` (`asked`: 'end' | 'after' | 'before').
export function takeSessionWindow(held, got, asked, { taskId = '', askedFrom = -1 } = {}) {
  if (!got || typeof got !== 'object' || Array.isArray(got) || !Array.isArray(got.items) || typeof got.id !== 'string') {
    return held;
  }
  const items = validSessionItems(got.items);
  const targetTask = taskId || held?.taskId || '';
  if (asked === 'end' || got.reset || !held || held.id !== got.id || (targetTask && held.taskId !== targetTask)) {
    if (asked === 'before') return held;
    return {
      taskId: targetTask,
      kind: String(got.kind || 'claude'),
      id: got.id,
      items,
      from: Math.max(0, Number(got.from) || 0),
      offset: Math.max(0, Number(got.offset) || 0),
      earlier: Boolean(got.earlier),
      started: String(got.started || ''),
      ended: String(got.ended || ''),
      context: contextTokens(got.context),
      unknown: Array.isArray(got.unknown) && got.unknown.length ? got.unknown.map(String) : null,
    };
  }
  if (asked === 'after') {
    if (Number(got.from) !== held.offset) return held;
    const nextOffset = Math.max(held.offset, Number(got.offset) || 0);
    if (!items.length && nextOffset === held.offset && !contextTokens(got.context)) return held;
    return {
      ...held,
      items: joinSessionItems(held.items, items),
      offset: nextOffset,
      ended: String(got.ended || held.ended || ''),
      started: String(held.started || got.started || ''),
      context: contextTokens(got.context) || held.context,
      unknown: items.length ? null : held.unknown,
    };
  }
  if (held.from !== askedFrom || Number(got.offset) !== held.from) return held;
  return {
    ...held,
    items: joinSessionItems(items, held.items),
    from: Math.max(0, Number(got.from) || 0),
    earlier: Boolean(got.earlier),
    context: held.context || contextTokens(got.context),
  };
}

// Bounds held items while the reader rests at the newest end, cutting only on JSONL line boundaries (`offset`).
export function trimSessionWindow(held, keep = SESSION_KEEP, slack = SESSION_SLACK) {
  if (!held || !Array.isArray(held.items)) return held;
  const n = held.items.length;
  if (n <= keep + slack) return held;
  let cut = n - keep;
  while (cut < n && held.items[cut].offset === held.items[cut - 1].offset) cut++;
  const from = Number(held.items[cut - 1]?.offset);
  if (cut >= n || !Number.isFinite(from)) return held;
  return { ...held, items: held.items.slice(cut), from, earlier: true };
}

// Converts an RFC3339/ISO session timestamp ("2026-11-16T14:45:00.000Z") into local "YYYY-MM-DD HH:MM:SS"
// so `clock(at, today)` formats local time consistently with ledger events.
export function sessionLocalTime(at) {
  const raw = String(at || '').trim();
  if (!raw) return '';
  if (/^\d{4}-\d\d-\d\d \d\d:\d\d/.test(raw)) return raw;
  const d = new Date(raw);
  if (!Number.isFinite(d.getTime())) return raw;
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function unwrapSessionText(raw) {
  const str = String(raw ?? '');
  const fromAgent = /<hc\b[^>]*>/i.test(str);
  const text = str
    .replace(/<\/?pasted_content[^>]*>/gi, '')
    .replace(/<\/?hc[^>]*>/gi, '')
    .replace(/<system-reminder>[\s\S]*?<\/system-reminder>/gi, '')
    .trim();
  return { text, fromAgent };
}

export function briefPreview(text, maxChars = 320, maxLines = 6) {
  const whole = String(text ?? '').trim();
  const lines = whole.split('\n');
  if (whole.length <= 380 && lines.length <= 7) return { preview: whole, long: false };
  let cut = lines.slice(0, maxLines).join('\n');
  if (cut.length > maxChars) cut = cut.slice(0, maxChars);
  return { preview: `${cut.trimEnd()}…`, long: true };
}

const QUESTION_TOOL_RE = /^(?:AskUserQuestion|request_user_input|ask_user|ask_question)$/i;

export function isQuestionTool(name) {
  return QUESTION_TOOL_RE.test(String(name || '').trim());
}

function normalizeQuestionItem(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const header = String(raw.header ?? raw.title ?? '').trim();
  const question = String(raw.question ?? raw.prompt ?? '').trim();
  const rawOpts = Array.isArray(raw.options) ? raw.options : [];
  const options = [];
  for (const o of rawOpts) {
    if (typeof o === 'string') {
      const label = o.trim();
      if (label) options.push({ label, description: '' });
    } else if (o && typeof o === 'object') {
      const label = String(o.label ?? o.title ?? o.text ?? '').trim();
      const description = String(o.description ?? o.why ?? '').trim();
      if (label) options.push({ label, description });
    }
  }
  if (!header && !question && !options.length) return null;
  return { header, question: question || header, options };
}

function unescapeJsonFragment(s) {
  return String(s || '').replace(/\\(["\\/nrt])/g, (_, ch) => (
    ch === 'n' ? '\n' : ch === 'r' ? '\r' : ch === 't' ? '\t' : ch
  ));
}

export function extractToolQuestions(item) {
  if (!item || typeof item !== 'object') return [];
  if (Array.isArray(item.questions) && item.questions.length) {
    const out = item.questions.map(normalizeQuestionItem).filter(Boolean);
    if (out.length) return out;
  }
  const rawInput = String(item.input || '').trim();
  if (!rawInput) return [];
  if (rawInput.startsWith('{')) {
    try {
      const parsed = JSON.parse(rawInput);
      if (parsed && typeof parsed === 'object') {
        const list = Array.isArray(parsed.questions) && parsed.questions.length ? parsed.questions : [parsed];
        const out = list.map(normalizeQuestionItem).filter(Boolean);
        if (out.length) return out;
      }
    } catch (_) {
      // Truncated JSON from an older remote pm.py (300-char SUMMARY_MAX): extract visible fields best-effort.
      const headerMatch = rawInput.match(/"(?:header|title)"\s*:\s*"((?:[^"\\]|\\.)*)"/);
      const qMatch = rawInput.match(/"(?:question|prompt)"\s*:\s*"((?:[^"\\]|\\.)*)"/);
      const opts = [];
      const optRe = /"(?:label|text)"\s*:\s*"((?:[^"\\]|\\.)*)"(?:\s*,\s*"(?:description|why)"\s*:\s*"((?:[^"\\]|\\.)*)")?/g;
      let m;
      while ((m = optRe.exec(rawInput)) !== null) {
        const label = unescapeJsonFragment(m[1]).trim();
        const description = m[2] ? unescapeJsonFragment(m[2]).trim() : '';
        if (label) opts.push({ label, description });
      }
      const header = headerMatch ? unescapeJsonFragment(headerMatch[1]).trim() : '';
      const question = qMatch ? unescapeJsonFragment(qMatch[1]).trim() : '';
      if (header || question || opts.length) {
        return [{ header, question: question || header, options: opts }];
      }
    }
  }
  return [{ header: '', question: rawInput, options: [] }];
}

export function toolsSummary(lang, calls) {
  const list = Array.isArray(calls) ? calls : [];
  if (!list.length) return '';
  const names = list.map(c => String(c?.name || ''));
  const groups = [
    [/^(?:Bash|run_command)$/i, 'toolRunBash'],
    [/^(?:Read|read_file)$/i, 'toolRunRead'],
    [/^(?:Edit|Write|MultiEdit|NotebookEdit|edit_file|write_file)$/i, 'toolRunEdit'],
    [/^(?:Grep|Glob|grep_search|find_by_name)$/i, 'toolRunSearch'],
    [/^(?:Agent|Task|invoke_subagent)$/i, 'toolRunAgent'],
    [/^(?:Web|search_web)/i, 'toolRunWeb'],
  ];
  const parts = [];
  let rest = names.length;
  for (const [pattern, key] of groups) {
    const n = names.filter(name => pattern.test(name)).length;
    if (n > 0) {
      parts.push(word(lang, key, n));
      rest -= n;
    }
  }
  if (rest > 0) parts.push(word(lang, parts.length ? 'toolRunOther' : 'toolRunTools', rest));
  return parts.join(lang === 'zh' ? '，' : ', ');
}

export function workedDuration(lang, started, ended) {
  const ms = Date.parse(String(ended || '')) - Date.parse(String(started || ''));
  if (!Number.isFinite(ms) || ms <= 0) return '';
  const totalSec = Math.round(ms / 1000);
  if (totalSec <= 0) return '';
  const h = Math.floor(totalSec / 3600), m = Math.floor((totalSec % 3600) / 60), s = totalSec % 60;
  if (h > 0) return word(lang, 'workedHours', h, m);
  if (m > 0) return word(lang, 'workedMinutes', m, s);
  return word(lang, 'workedSeconds', s);
}

// Groups transcript items into readable user bubbles and assistant turns whose consecutive tool calls fold.
export function sessionTurns(items, { lang = 'en', sent = [] } = {}) {
  const list = validSessionItems(items);
  const sentList = Array.isArray(sent) ? sent : [];
  const out = [];
  let lineOffset = -1, nth = 0;
  list.forEach((item, idx) => {
    const hasOff = Number.isFinite(item.offset);
    nth = hasOff && item.offset === lineOffset ? nth + 1 : 0;
    lineOffset = hasOff ? item.offset : -1;
    const itemId = hasOff ? `${item.offset}.${nth}` : String(idx);
    if (item.type === 'result') return;
    if (item.type === 'user') {
      const { text: unwrapped, fromAgent } = unwrapSessionText(item.text);
      const clean = withoutMarks(unwrapped).trim();
      const rawBody = clean || unwrapped;
      if (!rawBody) return;
      const { text, files } = splitMessage(rawBody);
      if (!text && !files.length) return;
      const isUserSent = !fromAgent && sentList.some(s => sameMessage(rawBody, s));
      const from = isUserSent ? word(lang, 'you') : fromAgent ? 'PM' : '';
      const { preview, long } = briefPreview(text);
      out.push({
        key: `u:${itemId}`,
        role: 'user',
        at: sessionLocalTime(item.at),
        from,
        text,
        preview,
        long,
        ...(files.length ? { files } : {}),
      });
      return;
    }
    let last = out[out.length - 1];
    if (!last || last.role !== 'assistant') {
      last = { key: `a:${itemId}`, role: 'assistant', at: sessionLocalTime(item.at), parts: [] };
      out.push(last);
    }
    if (item.at) last.at = sessionLocalTime(item.at);
    if (item.type === 'text') {
      const text = String(item.text || '').trim();
      if (!text) return;
      const prev = last.parts[last.parts.length - 1];
      if (prev && prev.kind === 'text') {
        prev.text = `${prev.text}\n\n${text}`;
      } else {
        last.parts.push({ kind: 'text', key: `t:${itemId}`, text });
      }
      return;
    }
    if (item.type === 'tool') {
      if (isQuestionTool(item.name)) {
        last.parts.push({
          kind: 'question',
          key: `q:${itemId}`,
          id: String(item.id || `${itemId}`),
          name: String(item.name || 'AskUserQuestion'),
          questions: extractToolQuestions(item),
          output: String(item.output || ''),
          error: Boolean(item.error),
        });
        return;
      }
      const call = {
        id: String(item.id || `${itemId}`),
        name: String(item.name || 'tool'),
        input: String(item.input || ''),
        output: String(item.output || ''),
        error: Boolean(item.error),
      };
      const prev = last.parts[last.parts.length - 1];
      if (prev && prev.kind === 'tools') {
        prev.calls.push(call);
        prev.errors = prev.calls.filter(c => c.error).length;
        prev.label = toolsSummary(lang, prev.calls);
      } else {
        const calls = [call];
        last.parts.push({
          kind: 'tools',
          key: `g:${itemId}`,
          calls,
          errors: call.error ? 1 : 0,
          label: toolsSummary(lang, calls),
        });
      }
    }
  });
  return out.filter(turn => turn.role === 'user' || turn.parts.length > 0);
}

// ---- @ mentions in project & thread composers: links, trigger detection, repo file index & menu ----

export const MENTION_CATEGORIES = ['threads', 'library', 'files'];
export const REPO_FILES_LIMIT = 20_000;
const MENTION_SCHEMES = new Set(['thread', 'library', 'file', 'session']);
const MENTION_LINK_RE = /\[@([^\]\n]+)\]\((thread|library|file|session):([^)\s\n]+)\)/g;
const LEGACY_LIBRARY_ROOTS = { project: 'docs', user: 'personal' };

export function projectFilesArgv(slug, { limit = REPO_FILES_LIMIT } = {}) {
  return ['project', 'files', String(slug), '--limit', String(limit)];
}

export function projectFoldersLsArgv(slug) {
  return ['project', 'folders', 'ls', String(slug)];
}

export function projectFoldersAddArgv(slug, path, { alias = '' } = {}) {
  const args = ['project', 'folders', 'add', String(slug), String(path)];
  const cleanAlias = String(alias || '').trim();
  if (cleanAlias) args.push('--alias', cleanAlias);
  return args;
}

export function projectFoldersRemoveArgv(slug, target, { force = false } = {}) {
  const args = ['project', 'folders', 'remove', String(slug), String(target)];
  if (force) args.push('--force');
  return args;
}

export function projectFoldersRenameAliasArgv(slug, target, newAlias) {
  return ['project', 'folders', 'rename-alias', String(slug), String(target), String(newAlias)];
}

export function projectSetSpaceArgv(slug, spaceId, { spaceName = '' } = {}) {
  const args = ['project', 'set-space', String(slug), String(spaceId)];
  const name = String(spaceName || '').trim();
  if (name) args.push('--space-name', name);
  return args;
}

export function encodeRefTarget(target) {
  return String(target ?? '').replace(/[% ()<>\r\n\\]/g, ch => {
    const code = ch.charCodeAt(0);
    return `%${code.toString(16).toUpperCase().padStart(2, '0')}`;
  });
}

function decodeRefTarget(raw) {
  try { return decodeURIComponent(String(raw ?? '')); } catch (_) { return ''; }
}

export function sanitizeMentionLabel(label) {
  return String(label ?? '').replace(/[\r\n]+/g, ' ').replace(/\[/g, '(').replace(/\]/g, ')').trim();
}

export function formatMentionLink({ kind, target, label }) {
  const cleanLabel = sanitizeMentionLabel(label || target) || String(target || '');
  return `[@${cleanLabel}](${kind}:${encodeRefTarget(target)})`;
}

function normalizeFsPath(p) {
  const raw = String(p ?? '').trim();
  if (!raw || raw.includes('\0')) return '';
  let norm = raw.replace(/\\/g, '/').replace(/\/{2,}/g, '/');
  if (/^\/[A-Za-z]:\//.test(norm)) norm = norm.slice(1);
  if (/^[a-z]:\//.test(norm)) norm = norm[0].toUpperCase() + norm.slice(1);
  if (norm.length > 1 && !/^[A-Za-z]:\/$/.test(norm)) norm = norm.replace(/\/+$/, '');
  return norm;
}

function stripBasePrefix(filePath, baseDir) {
  const file = normalizeFsPath(filePath);
  const base = normalizeFsPath(baseDir);
  if (!file || !base) return '';
  const prefix = base.endsWith('/') ? base : `${base}/`;
  if (!file.startsWith(prefix)) return '';
  return file.slice(prefix.length);
}

function validRelParts(rel, { allowGit = false } = {}) {
  if (!rel || rel.startsWith('/') || rel.endsWith('/')) return null;
  const parts = rel.split('/');
  if (parts.some(p => !p || p === '.' || p === '..' || (!allowGit && p === '.git'))) return null;
  return parts;
}

function normalizeLibraryRootPath(root, path) {
  let r = root, p = path;
  if (r === 'project' && p.startsWith('memory/')) {
    r = 'memory';
    p = p.slice('memory/'.length);
  } else if (LEGACY_LIBRARY_ROOTS[r]) {
    r = LEGACY_LIBRARY_ROOTS[r];
  }
  if (!ALL_DOC_ROOTS.has(r) || r === 'repo') return null;
  if (r === 'docs' && /^research\/.+/i.test(p)) {
    r = 'research';
    p = `docs/research/${p.slice('research/'.length)}`;
  } else if (r === 'research' && !p.includes('/') && /\.(?:md|markdown)$/i.test(p)) {
    p = `docs/research/${p}`;
  }
  if (!validRelParts(p, { allowGit: true })) return null;
  return { kind: 'library', target: `${r}/${p}`, root: r, path: p };
}

function inferLedgerHome(ctx) {
  const direct = normalizeFsPath(ctx?.ledgerHome || '');
  if (direct) return direct;
  const conv = normalizeFsPath(ctx?.conversation || '');
  const slug = String(ctx?.slug || '').trim();
  if (conv && slug) {
    const marker = `/projects/${slug}/`;
    const idx = conv.lastIndexOf(marker);
    if (idx > 0) return conv.slice(0, idx);
  }
  return '';
}

function resolveAbsoluteFileRef(absPath, ctx) {
  if (!ctx || typeof ctx !== 'object') return null;
  const norm = normalizeFsPath(absPath);
  if (!norm) return null;
  const segs = norm.split('/');
  if (segs.includes('..')) return null;

  const ledgerHome = inferLedgerHome(ctx);
  const slug = String(ctx.slug || '').trim();
  if (ledgerHome && slug && !slug.includes('/') && !slug.includes('..')) {
    const projRel = stripBasePrefix(norm, `${ledgerHome}/projects/${slug}`);
    if (projRel) {
      const parts = validRelParts(projRel, { allowGit: true });
      if (!parts) return null;
      if (parts[0] === 'docs' && parts.length >= 2) {
        if (parts[1].toLowerCase() === 'research' && parts.length >= 3) {
          const rPath = `docs/research/${parts.slice(2).join('/')}`;
          return { kind: 'library', target: `research/${rPath}`, root: 'research', path: rPath };
        }
        const dPath = parts.slice(1).join('/');
        return { kind: 'library', target: `docs/${dPath}`, root: 'docs', path: dPath };
      }
      if (parts.length === 1 && parts[0] === 'decisions.md') {
        return { kind: 'library', target: 'docs/decisions.md', root: 'docs', path: 'decisions.md' };
      }
      if (parts[0] === 'research' && parts.length === 3 && parts[2] === 'README.md') {
        const rPath = `${parts[1]}/${parts[2]}`;
        return { kind: 'library', target: `research/${rPath}`, root: 'research', path: rPath };
      }
      if (parts[0] === 'memory' && parts.length === 2 && parts[1].endsWith('.md') && parts[1] !== 'MEMORY.md') {
        return { kind: 'library', target: `memory/${parts[1]}`, root: 'memory', path: parts[1] };
      }
      return null;
    }
    const personalRel = stripBasePrefix(norm, `${ledgerHome}/memory`);
    if (personalRel) {
      const parts = validRelParts(personalRel, { allowGit: true });
      if (parts && parts.length === 1 && parts[0].endsWith('.md') && parts[0] !== 'MEMORY.md') {
        return { kind: 'library', target: `personal/${parts[0]}`, root: 'personal', path: parts[0] };
      }
      return null;
    }
  }

  const foldersList = Array.isArray(ctx.folders) ? ctx.folders : [];
  if (foldersList.length >= 2) {
    for (const f of foldersList) {
      const rel = stripBasePrefix(norm, f?.path || '');
      if (rel && validRelParts(rel)) {
        const target = `${f.alias || folderName(f.path)}/${rel}`;
        return { kind: 'file', target, path: target };
      }
    }
  }
  const repoRel = stripBasePrefix(norm, ctx.repo || '');
  if (repoRel) {
    if (!validRelParts(repoRel)) return null;
    return { kind: 'file', target: repoRel, path: repoRel };
  }
  return null;
}

export function parseRefLink(url, ctx = null) {
  const raw = String(url || '').trim();
  if (!raw) return null;
  const schemeMatch = /^([a-z][a-z0-9+.-]*):(.*)$/i.exec(raw);
  if (!schemeMatch) {
    if (raw.startsWith('#') || raw.startsWith('/') || raw.startsWith('?')) return null;
    const noFrag = raw.split(/[?#]/)[0];
    const decoded = decodeRefTarget(noFrag);
    if (!decoded || decoded.includes('\0') || decoded.includes('\\')) return null;
    const clean = decoded.replace(/^(?:\.\/)+/, '');
    if (!/\.(?:md|markdown)$/i.test(clean) || !validRelParts(clean)) return null;
    return { kind: 'file', target: clean, path: clean };
  }
  const kind = schemeMatch[1].toLowerCase();
  if (kind === 'thread') {
    const id = threadLink(raw);
    return id ? { kind: 'thread', target: id } : null;
  }
  if (kind === 'session') {
    const rest = schemeMatch[2].replace(/^\/\//, '');
    const decoded = decodeRefTarget(rest);
    if (!decoded || decoded.includes('\0') || decoded.includes('\\')) return null;
    if (!/^[^\s/]+(?:\/[^\s/]+)?$/.test(decoded) || decoded.includes('..')) return null;
    return { kind: 'session', target: decoded };
  }
  if (kind === 'library' || kind === 'doc') {
    const noFrag = schemeMatch[2].split(/[?#]/)[0].replace(/^\/\//, '');
    const decoded = decodeRefTarget(noFrag);
    if (!decoded || decoded.includes('\0') || decoded.includes('\\')) return null;
    const slash = decoded.indexOf('/');
    if (kind === 'library') {
      if (slash <= 0) return null;
      return normalizeLibraryRootPath(decoded.slice(0, slash), decoded.slice(slash + 1));
    }
    if (slash > 0) {
      const head = decoded.slice(0, slash);
      const tail = decoded.slice(slash + 1);
      if (head === 'repo') return null;
      if (ALL_DOC_ROOTS.has(head) || LEGACY_LIBRARY_ROOTS[head]) {
        return normalizeLibraryRootPath(head, tail);
      }
    }
    return normalizeLibraryRootPath('docs', decoded);
  }
  if (kind === 'file') {
    const noFrag = schemeMatch[2].split(/[?#]/)[0];
    const absMatch = /^\/\/(?:localhost|127\.0\.0\.1)?(\/.*)$/i.exec(noFrag);
    if (absMatch) {
      const decoded = decodeRefTarget(absMatch[1]);
      if (!decoded || decoded.includes('\0')) return null;
      return resolveAbsoluteFileRef(decoded, ctx);
    }
    const rest = noFrag.replace(/^\/\//, '');
    const decoded = decodeRefTarget(rest);
    if (!decoded || decoded.includes('\0') || decoded.includes('\\')) return null;
    if (!validRelParts(decoded)) return null;
    return { kind: 'file', target: decoded, path: decoded };
  }
  return null;
}

// ---- Inline image preview parsing, safe path resolution & staging ----
const PREVIEWABLE_IMAGE_EXT = /\.(png|jpe?g|webp|gif)$/i;
export const INLINE_IMAGE_MAX_PER_MSG = 6;
export const INLINE_IMAGE_MAX_BYTES = 12 * 1024 * 1024;
export const INLINE_IMAGE_REMOTE_MAX_BYTES = 6 * 1024 * 1024;
export const INLINE_IMAGE_CACHE_DIR = 'cache/pm-images';

export const isPreviewableImage = path => PREVIEWABLE_IMAGE_EXT.test(String(path || '').trim());

// Maps a parsed library/file ref into a strictly-contained { key, root, path, baseDir, relPath, ext }
// descriptor for image staging, or null if disallowed or outside project/Library/repo.
export function resolveImageTarget(ref, ctx = null) {
  if (!ref || typeof ref !== 'object' || !ctx || typeof ctx !== 'object') return null;
  const root = ref.kind === 'file' ? 'repo' : String(ref.root || '').trim();
  const path = String(ref.path || ref.target || '').trim();
  if (!root || !path || !isPreviewableImage(path)) return null;
  const extMatch = /\.([a-z0-9]+)$/i.exec(path);
  const ext = extMatch ? extMatch[1].toLowerCase() : '';
  if (!ext) return null;

  const ledgerHome = inferLedgerHome(ctx);
  const slug = String(ctx.slug || '').trim();
  const validSlug = Boolean(slug && !slug.includes('/') && !slug.includes('\\') && !slug.includes('..') && slug !== '.');

  if (root === 'docs') {
    if (!ledgerHome || !validSlug) return null;
    const parts = validRelParts(path);
    if (!parts || parts.some(p => p.startsWith('.')) || parts[0].toLowerCase() === 'research') return null;
    const normPath = parts.join('/');
    return {
      key: `docs/${normPath}`,
      root: 'docs',
      path: normPath,
      baseDir: `${ledgerHome}/projects/${slug}/docs`,
      relPath: normPath,
      ext,
    };
  }
  if (root === 'project') {
    if (!ledgerHome || !validSlug) return null;
    const parts = validRelParts(path);
    if (!parts || parts.some(p => p.startsWith('.')) || parts[0] !== 'docs' || parts.length < 2) return null;
    const normPath = parts.join('/');
    return {
      key: `docs/${parts.slice(1).join('/')}`,
      root: 'docs',
      path: parts.slice(1).join('/'),
      baseDir: `${ledgerHome}/projects/${slug}`,
      relPath: normPath,
      ext,
    };
  }
  if (root === 'research') {
    if (!ledgerHome || !validSlug) return null;
    const parts = validRelParts(path);
    if (!parts || parts.some(p => p.startsWith('.')) || parts[0] !== 'docs' || parts[1]?.toLowerCase() !== 'research' || parts.length < 3) return null;
    const normPath = parts.join('/');
    return {
      key: `research/${normPath}`,
      root: 'research',
      path: normPath,
      baseDir: `${ledgerHome}/projects/${slug}/docs/research`,
      relPath: parts.slice(2).join('/'),
      ext,
    };
  }
  if (root === 'repo' || root === 'repo_docs') {
    const repo = normalizeFsPath(ctx.repo || '');
    if (!repo) return null;
    const parts = validRelParts(path, { allowGit: true });
    if (!parts || parts.includes('.git')) return null;
    const normPath = parts.join('/');
    return {
      key: `${root}/${normPath}`,
      root,
      path: normPath,
      baseDir: repo,
      relPath: normPath,
      ext,
    };
  }
  return null;
}

function stripMarkdownLinkTarget(raw) {
  let s = String(raw || '').trim();
  if (!s) return '';
  if (s.startsWith('<')) {
    const close = s.indexOf('>');
    if (close > 1) return s.slice(1, close).trim();
  }
  // Drop optional markdown link title: (url "title") or (url 'title')
  const titleMatch = /^(\S+)\s+["'(]/.exec(s);
  if (titleMatch) s = titleMatch[1];
  return s;
}

const MD_IMAGE_OR_LINK_RE = /(!?)\[([^\]\r\n]*)\]\(([^)\r\n]+)\)/g;
const BARE_IMAGE_REF_RE = /\b((?:library|doc|file):[^\s)\]>,"'`]+)/gi;

// Extracts deduplicated, safely-resolved inline image references from markdown text
// (PM replies and question card bodies), skipping fenced code blocks and inline code spans.
export function extractInlineImageRefs(markdown, ctx = null, { limit = INLINE_IMAGE_MAX_PER_MSG } = {}) {
  const src = String(markdown || '');
  if (!src || !ctx || typeof ctx !== 'object') return [];
  const cap = Math.max(0, Number(limit) || 0);
  if (cap === 0) return [];

  const byKey = new Map();
  const order = [];
  const pushCandidate = (rawUrl, altText, isMarkdownImage) => {
    const url = stripMarkdownLinkTarget(rawUrl);
    if (!url) return;
    const parsed = parseRefLink(url, ctx);
    if (!parsed || (parsed.kind !== 'library' && parsed.kind !== 'file')) return;
    const target = resolveImageTarget(parsed, ctx);
    if (!target) return;
    const label = String(altText || '').trim();
    const existing = byKey.get(target.key);
    if (existing) {
      if (!existing.alt && label) existing.alt = label;
      if (isMarkdownImage) existing.isMarkdownImage = true;
      return;
    }
    if (order.length >= cap) return;
    const item = {
      ...target,
      url,
      alt: label,
      name: fileName(target.path),
      isMarkdownImage: Boolean(isMarkdownImage),
    };
    byKey.set(target.key, item);
    order.push(item);
  };

  const scanProse = chunk => {
    const covered = [];
    MD_IMAGE_OR_LINK_RE.lastIndex = 0;
    let m;
    while ((m = MD_IMAGE_OR_LINK_RE.exec(chunk)) !== null) {
      covered.push([m.index, m.index + m[0].length]);
      pushCandidate(m[3], m[2], m[1] === '!');
    }
    BARE_IMAGE_REF_RE.lastIndex = 0;
    while ((m = BARE_IMAGE_REF_RE.exec(chunk)) !== null) {
      const start = m.index, end = start + m[0].length;
      if (covered.some(([a, b]) => start >= a && end <= b)) continue;
      const cleaned = m[1].replace(/[.,;:!?。，；：！？）)]+$/, '');
      pushCandidate(cleaned, '', false);
    }
  };

  let inFence = false, fence = '';
  for (const line of src.split('\n')) {
    const fMatch = /^\s*(`{3,}|~{3,})/.exec(line);
    if (fMatch) {
      if (!inFence) { inFence = true; fence = fMatch[1][0]; }
      else if (fMatch[1][0] === fence) { inFence = false; fence = ''; }
      continue;
    }
    if (inFence) continue;
    const parts = line.split(/(`[^`]*`)/g);
    for (let i = 0; i < parts.length; i += 2) {
      if (parts[i]) scanProse(parts[i]);
    }
  }
  return order;
}

// Rewrites `![alt](library:...|file:...)` for previewable images into clickable `[alt || name](url)`
// links so GPUI TextView.markdown renders clean prose while the inline preview renders below.
export function rewriteMarkdownImagesForDisplay(markdown, ctx = null) {
  const src = String(markdown || '');
  if (!src.includes('![') || !ctx || typeof ctx !== 'object') return src;
  const rewriteChunk = chunk => chunk.replace(/!\[([^\]\r\n]*)\]\(([^)\r\n]+)\)/g, (full, alt, rawTarget) => {
    const url = stripMarkdownLinkTarget(rawTarget);
    const parsed = parseRefLink(url, ctx);
    if (!parsed || (parsed.kind !== 'library' && parsed.kind !== 'file')) return full;
    const target = resolveImageTarget(parsed, ctx);
    if (!target) return full;
    const label = String(alt || '').trim() || fileName(target.path);
    return `[${label}](${url})`;
  });
  let out = '', inFence = false, fence = '';
  for (const line of src.split('\n')) {
    const fMatch = /^\s*(`{3,}|~{3,})/.exec(line);
    if (fMatch) {
      if (!inFence) { inFence = true; fence = fMatch[1][0]; }
      else if (fMatch[1][0] === fence) { inFence = false; fence = ''; }
      out += (out ? '\n' : '') + line;
      continue;
    }
    if (inFence) { out += (out ? '\n' : '') + line; continue; }
    const parts = line.split(/(`[^`]*`)/g);
    const rewritten = parts.map((p, i) => (i % 2 === 1 ? p : rewriteChunk(p))).join('');
    out += (out ? '\n' : '') + rewritten;
  }
  return out;
}

// Computes aspect-ratio-preserving display dimensions inside (maxWidth, maxHeight) without upscaling.
export function fitImageBox(naturalW, naturalH, { maxWidth = 480, maxHeight = 280 } = {}) {
  const mw = Math.max(48, Math.floor(Number(maxWidth) || 480));
  const mh = Math.max(48, Math.floor(Number(maxHeight) || 280));
  const nw = Number(naturalW) || 0;
  const nh = Number(naturalH) || 0;
  if (nw <= 0 || nh <= 0) {
    return { width: Math.min(mw, 240), height: Math.min(mh, 140) };
  }
  const scale = Math.min(1, mw / nw, mh / nh);
  return {
    width: Math.max(1, Math.round(nw * scale)),
    height: Math.max(1, Math.round(nh * scale)),
  };
}

const IMAGE_PROBE_PY_COMMON = `
import os, sys, stat, json, hashlib, struct, base64

ALLOWED = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}

def fail(msg):
  print(json.dumps({'ok': False, 'error': msg}, ensure_ascii=False))
  sys.exit(0)

def walk_safe(base_dir, rel_path):
  if not base_dir or not rel_path or '\\x00' in rel_path or '\\\\' in rel_path:
    fail('invalid path')
  parts = [p for p in rel_path.split('/') if p]
  if not parts or rel_path.startswith('/') or any(p in ('.', '..') or p == '.git' for p in parts):
    fail('invalid path')
  ext = os.path.splitext(parts[-1])[1].lower()
  if ext not in ALLOWED:
    fail('unsupported image format')
  base_real = os.path.realpath(base_dir)
  cur = base_dir
  if hasattr(os, 'O_NOFOLLOW'):
    dir_fd = os.open(base_dir, os.O_RDONLY)
    try:
      for seg in parts[:-1]:
        nxt = os.open(seg, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        os.close(dir_fd)
        dir_fd = nxt
        if not stat.S_ISDIR(os.fstat(dir_fd).st_mode):
          fail('not a file')
      fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_BINARY', 0), dir_fd=dir_fd)
    finally:
      os.close(dir_fd)
    return fd, ext
  for seg in parts:
    cur = os.path.join(cur, seg)
    if os.path.islink(cur):
      fail('symlink refused')
  cur_real = os.path.realpath(cur)
  if cur_real != base_real and not cur_real.startswith(base_real + os.sep):
    fail('outside root')
  fd = os.open(cur_real, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
  return fd, ext

def probe_dims(data, ext):
  n = len(data)
  if data.startswith(b'\\x89PNG\\r\\n\\x1a\\n') and n >= 24:
    w, h = struct.unpack('>II', data[16:24])
    return (w, h) if w > 0 and h > 0 else None
  if (data.startswith(b'GIF87a') or data.startswith(b'GIF89a')) and n >= 10:
    w, h = struct.unpack('<HH', data[6:10])
    return (w, h) if w > 0 and h > 0 else None
  if data.startswith(b'RIFF') and n >= 30 and data[8:12] == b'WEBP':
    tag = data[12:16]
    if tag == b'VP8 ' and n >= 30:
      w = struct.unpack('<H', data[26:28])[0] & 0x3FFF
      h = struct.unpack('<H', data[28:30])[0] & 0x3FFF
      return (w, h) if w > 0 and h > 0 else None
    if tag == b'VP8L' and n >= 25:
      bits = struct.unpack('<I', data[21:25])[0]
      w = (bits & 0x3FFF) + 1
      h = ((bits >> 14) & 0x3FFF) + 1
      return (w, h) if w > 0 and h > 0 else None
    if tag == b'VP8X' and n >= 30:
      w = 1 + int.from_bytes(data[24:27], 'little')
      h = 1 + int.from_bytes(data[27:30], 'little')
      return (w, h) if w > 0 and h > 0 else None
    return None
  if data.startswith(b'\\xff\\xd8'):
    i = 2
    while i + 4 <= n:
      while i < n and data[i] == 0xFF:
        i += 1
      if i >= n:
        break
      marker = data[i]
      i += 1
      if marker in (0xD8, 0xD9, 0x01) or (0xD0 <= marker <= 0xD7):
        continue
      if i + 2 > n:
        break
      seg_len = struct.unpack('>H', data[i:i+2])[0]
      if seg_len < 2 or i + seg_len > n:
        break
      if (0xC0 <= marker <= 0xCF) and marker not in (0xC4, 0xC8, 0xCC) and seg_len >= 7:
        h, w = struct.unpack('>HH', data[i+3:i+7])
        return (w, h) if w > 0 and h > 0 else None
      i += seg_len
    return None
  return None

def read_verified(base_dir, rel_path, max_bytes):
  try:
    fd, ext = walk_safe(base_dir, rel_path)
  except OSError:
    fail('not found')
  try:
    with os.fdopen(fd, 'rb') as f:
      st = os.fstat(f.fileno())
      if not stat.S_ISREG(st.st_mode):
        fail('not a file')
      if st.st_size > max_bytes:
        fail('too large')
      mtime_ns = int(getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)))
      data = f.read(max_bytes + 1)
  except OSError:
    fail('read error')
  if len(data) > max_bytes:
    fail('too large')
  dims = probe_dims(data, ext)
  if not dims:
    fail('invalid image')
  h = hashlib.sha256(data).hexdigest()[:20]
  return data, ext, dims[0], dims[1], h, mtime_ns

def write_cache(cache_dir, rel_prefix, h, ext, data, max_keep=80):
  os.makedirs(cache_dir, exist_ok=True)
  name = h + ext
  dst = os.path.join(cache_dir, name)
  if not os.path.exists(dst):
    tmp = os.path.join(cache_dir, f'.tmp-{os.getpid()}-{name}')
    with open(tmp, 'wb') as f:
      f.write(data)
    os.replace(tmp, dst)
  else:
    try:
      os.utime(dst, None)
    except OSError:
      pass
  try:
    items = []
    for entry in os.scandir(cache_dir):
      if entry.name.startswith('.') or not entry.is_file():
        continue
      items.append((entry.stat().st_mtime, entry.path))
    if len(items) > max_keep:
      items.sort()
      for _, old in items[:-max_keep]:
        try:
          os.unlink(old)
        except OSError:
          pass
  except OSError:
    pass
  return f'{rel_prefix}/{name}'
`.trim();

const STAGE_LOCAL_IMAGE_PY = `${IMAGE_PROBE_PY_COMMON}
base_dir, rel_path, cache_dir, rel_prefix, max_bytes = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
data, ext, w, h, digest, mtime_ns = read_verified(base_dir, rel_path, max_bytes)
rel = write_cache(cache_dir, rel_prefix, digest, ext, data)
print(json.dumps({'ok': True, 'rel': rel, 'width': w, 'height': h, 'size': len(data), 'hash': digest, 'mtime_ns': mtime_ns}, ensure_ascii=False))
`;

const READ_REMOTE_IMAGE_PY = `${IMAGE_PROBE_PY_COMMON}
base_dir, rel_path, max_bytes = sys.argv[1], sys.argv[2], int(sys.argv[3])
data, ext, w, h, digest, mtime_ns = read_verified(base_dir, rel_path, max_bytes)
print(json.dumps({'ok': True, 'ext': ext, 'width': w, 'height': h, 'size': len(data), 'hash': digest, 'mtime_ns': mtime_ns, 'b64': base64.b64encode(data).decode('ascii')}, ensure_ascii=False))
`;

const STAT_IMAGES_PY = `${IMAGE_PROBE_PY_COMMON}
req = json.loads(sys.argv[1])
out = {}
for item in req if isinstance(req, list) else []:
  key = str(item.get('key') or '')
  base_dir = str(item.get('baseDir') or '')
  rel_path = str(item.get('relPath') or '')
  if not key or not base_dir or not rel_path:
    continue
  try:
    fd, _ext = walk_safe(base_dir, rel_path)
    try:
      st = os.fstat(fd)
    finally:
      os.close(fd)
    if not stat.S_ISREG(st.st_mode):
      out[key] = {'ok': False, 'error': 'not a file'}
    else:
      mtime_ns = int(getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)))
      out[key] = {'ok': True, 'mtime_ns': mtime_ns, 'size': int(st.st_size)}
  except OSError:
    out[key] = {'ok': False, 'error': 'not found'}
print(json.dumps({'ok': True, 'items': out}, ensure_ascii=False))
`;

const WRITE_STAGED_IMAGE_PY = `${IMAGE_PROBE_PY_COMMON}
cache_dir, rel_prefix, digest, ext, b64_file = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
try:
  with open(b64_file, 'r', encoding='ascii') as f:
    raw = base64.b64decode(f.read().strip(), validate=True)
finally:
  try:
    os.unlink(b64_file)
  except OSError:
    pass
dims = probe_dims(raw, ext)
if not dims:
  fail('invalid image')
rel = write_cache(cache_dir, rel_prefix, digest, ext, raw)
print(json.dumps({'ok': True, 'rel': rel, 'width': dims[0], 'height': dims[1], 'size': len(raw), 'hash': digest}, ensure_ascii=False))
`;

export const IMAGE_REVALIDATE_LOCAL_MS = 10000;
export const IMAGE_REVALIDATE_REMOTE_MS = 25000;
export const IMAGE_LIGHTBOX_REVALIDATE_MS = 400;
export const IMAGE_FAIL_BACKOFF_MS = 30000;

export function stageLocalImageArgv(baseDir, relPath, cacheDir, { relPrefix = INLINE_IMAGE_CACHE_DIR, maxBytes = INLINE_IMAGE_MAX_BYTES } = {}) {
  return ['-c', STAGE_LOCAL_IMAGE_PY, String(baseDir), String(relPath), String(cacheDir), String(relPrefix), String(maxBytes)];
}

export function readRemoteImageArgv(baseDir, relPath, { maxBytes = INLINE_IMAGE_REMOTE_MAX_BYTES } = {}) {
  return ['python3', ['-c', READ_REMOTE_IMAGE_PY, String(baseDir), String(relPath), String(maxBytes)]];
}

export function statLocalImagesArgv(items = []) {
  const payload = (Array.isArray(items) ? items : []).map(it => ({
    key: String(it?.key || ''),
    baseDir: String(it?.baseDir || ''),
    relPath: String(it?.relPath || ''),
  })).filter(it => it.key && it.baseDir && it.relPath);
  return ['-c', STAT_IMAGES_PY, JSON.stringify(payload)];
}

export function statRemoteImagesArgv(items = []) {
  return ['python3', statLocalImagesArgv(items)];
}

export function writeStagedImageArgv(cacheDir, digest, ext, b64File, { relPrefix = INLINE_IMAGE_CACHE_DIR } = {}) {
  return ['-c', WRITE_STAGED_IMAGE_PY, String(cacheDir), String(relPrefix), String(digest), String(ext), String(b64File)];
}

// Checks whether a cached staged image entry is still valid against known doc metadata or disk stat.
// Unlike the old `(!version || !cached.version || ...)` check, a newly observed non-empty version
// or a changed disk (mtime_ns, size) strictly invalidates the cache so overwritten same-name files refresh.
export function isImageEntryFresh(entry, { version = '', mtimeNs = 0, size = 0 } = {}) {
  if (!entry || !entry.rel || entry.stale) return false;
  if (version && entry.version !== version) return false;
  if (mtimeNs > 0 && Number(entry.mtimeNs || 0) !== Number(mtimeNs)) return false;
  if (size > 0 && Number(entry.size || 0) !== Number(size)) return false;
  return true;
}

export function needsImageRevalidate(entry, now = Date.now(), { remote = false, minAgeMs = null } = {}) {
  if (!entry || !entry.rel) return false;
  if (entry.stale) return true;
  const threshold = Number.isFinite(minAgeMs) ? minAgeMs : (remote ? IMAGE_REVALIDATE_REMOTE_MS : IMAGE_REVALIDATE_LOCAL_MS);
  const checkedAt = Number(entry.checkedAt || 0);
  return !checkedAt || (Number(now) - checkedAt) >= threshold;
}

// Returns true while a recorded image load/refresh failure is still within its backoff window
// and the underlying file has not changed again (by version, mtime_ns, or size).
export function isImageFailActive(failed, {
  version = '',
  mtimeNs = 0,
  size = 0,
  now = Date.now(),
  backoffMs = IMAGE_FAIL_BACKOFF_MS,
} = {}) {
  if (!failed || !Number.isFinite(Number(failed.at))) return false;
  if ((Number(now) - Number(failed.at)) >= Number(backoffMs)) return false;
  if (version && failed.version && failed.version !== version) return false;
  if (mtimeNs > 0 && Number(failed.mtimeNs || 0) > 0 && Number(failed.mtimeNs) !== Number(mtimeNs)) return false;
  if (size > 0 && Number(failed.size || 0) > 0 && Number(failed.size) !== Number(size)) return false;
  return true;
}

export function reconcileImageCache(cacheMap, files = [], { machine = 'local', slug = '' } = {}) {
  if (!(cacheMap instanceof Map) || !cacheMap.size) return cacheMap;
  const byDocKey = new Map();
  for (const f of Array.isArray(files) ? files : []) {
    if (f?.root && f?.path) byDocKey.set(`${f.root}/${f.path}`, f);
  }
  const prefix = `${machine || 'local'}|${slug}|`;
  let changed = false;
  const next = new Map(cacheMap);
  for (const [cKey, entry] of cacheMap.entries()) {
    if (!entry) continue;
    if (slug && !cKey.startsWith(prefix)) continue;
    const targetKey = cKey.slice(cKey.indexOf('|', cKey.indexOf('|') + 1) + 1);
    const meta = byDocKey.get(targetKey);
    if (!meta) continue;
    const version = String(meta.version || '');
    const metaSize = Number(meta.size || 0);
    if ((version && entry.version !== version) || (metaSize > 0 && Number(entry.size || 0) > 0 && Number(entry.size) !== metaSize)) {
      next.set(cKey, { ...entry, stale: true, checkedAt: 0 });
      changed = true;
    }
  }
  return changed ? next : cacheMap;
}

// ---- Full-window image lightbox zoom, 2D scroll canvas & system preview ----
export const LIGHTBOX_ZOOM_STEPS = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4];
export const LIGHTBOX_MIN_ZOOM = 0.1;
export const LIGHTBOX_MAX_ZOOM = 4;
export const LIGHTBOX_TOOLBAR_HEIGHT = 48;
export const LIGHTBOX_CANVAS_PADDING = 24;

export function createImageLightboxState(opts = {}) {
  const src = opts && typeof opts === 'object' ? opts : {};
  const mode = src.mode === 'scale' ? 'scale' : 'fit';
  const rawScale = Number(src.scale);
  const scale = Number.isFinite(rawScale) && rawScale > 0
    ? Math.min(LIGHTBOX_MAX_ZOOM, Math.max(LIGHTBOX_MIN_ZOOM, rawScale))
    : 1;
  return {
    rel: String(src.rel || ''),
    width: Math.max(0, Math.round(Number(src.width) || 0)),
    height: Math.max(0, Math.round(Number(src.height) || 0)),
    size: Math.max(0, Math.round(Number(src.size) || 0)),
    mtimeNs: Math.max(0, Math.round(Number(src.mtimeNs || src.mtime_ns) || 0)),
    hash: String(src.hash || ''),
    name: String(src.name || fileName(src.path || src.relPath || '') || 'image'),
    root: String(src.root || ''),
    path: String(src.path || ''),
    baseDir: String(src.baseDir || ''),
    relPath: String(src.relPath || ''),
    ext: String(src.ext || ''),
    key: String(src.key || ''),
    machine: String(src.machine || ''),
    absPath: String(src.absPath || ''),
    lang: String(src.lang || ''),
    mode,
    scale,
    error: String(src.error || ''),
  };
}

// Computes aspect-ratio-preserving image size and 2D scroll canvas geometry.
// Uses explicit canvas padding instead of flex-centering on an overflowing container so GPUI
// never pushes top/left edges into unreachable negative scroll coordinates when zoomed in.
export function computeLightboxLayout({
  naturalW = 0,
  naturalH = 0,
  viewportW = 960,
  viewportH = 640,
  mode = 'fit',
  scale = 1,
  padding = LIGHTBOX_CANVAS_PADDING,
} = {}) {
  const vpW = Math.max(240, Math.round(Number(viewportW) || 960));
  const vpH = Math.max(180, Math.round(Number(viewportH) || 640));
  const pad = Math.max(0, Math.round(Number(padding) || 0));
  const availW = Math.max(64, vpW - pad * 2);
  const availH = Math.max(64, vpH - pad * 2);
  const nw = Math.max(0, Number(naturalW) || 0);
  const nh = Math.max(0, Number(naturalH) || 0);
  const fitScale = (nw > 0 && nh > 0)
    ? Math.min(1, availW / nw, availH / nh)
    : 1;
  const isFit = mode !== 'scale';
  const clampedScale = Math.min(LIGHTBOX_MAX_ZOOM, Math.max(LIGHTBOX_MIN_ZOOM, Number(scale) || 1));
  const effectiveScale = isFit ? fitScale : clampedScale;
  const width = (nw > 0 && nh > 0) ? Math.max(1, Math.round(nw * effectiveScale)) : Math.min(availW, 480);
  const height = (nw > 0 && nh > 0) ? Math.max(1, Math.round(nh * effectiveScale)) : Math.min(availH, 320);
  const canvasWidth = Math.max(vpW, width + pad * 2);
  const canvasHeight = Math.max(vpH, height + pad * 2);
  const padLeft = Math.max(pad, Math.floor((canvasWidth - width) / 2));
  const padTop = Math.max(pad, Math.floor((canvasHeight - height) / 2));
  const overflowX = width + pad * 2 > vpW + 1;
  const overflowY = height + pad * 2 > vpH + 1;
  return {
    fitScale,
    effectiveScale,
    percent: Math.max(1, Math.round(effectiveScale * 100)),
    width,
    height,
    canvasWidth,
    canvasHeight,
    padLeft,
    padTop,
    overflowX,
    overflowY,
    scrollable: overflowX || overflowY,
    isFit,
    isActual: !isFit && Math.abs(effectiveScale - 1) < 0.005,
    canZoomIn: effectiveScale < LIGHTBOX_MAX_ZOOM - 0.005,
    canZoomOut: effectiveScale > LIGHTBOX_MIN_ZOOM + 0.005,
  };
}

export function stepLightboxZoom(state, direction, fitScale = 1) {
  const cur = state?.mode === 'scale'
    ? Math.min(LIGHTBOX_MAX_ZOOM, Math.max(LIGHTBOX_MIN_ZOOM, Number(state.scale) || 1))
    : (Number(fitScale) > 0 ? Number(fitScale) : 1);
  let next = cur;
  if (direction > 0) {
    const found = LIGHTBOX_ZOOM_STEPS.find(s => s > cur * 1.02);
    next = found !== undefined ? found : LIGHTBOX_MAX_ZOOM;
  } else if (direction < 0) {
    let found = null;
    for (let i = LIGHTBOX_ZOOM_STEPS.length - 1; i >= 0; i--) {
      if (LIGHTBOX_ZOOM_STEPS[i] < cur / 1.02) {
        found = LIGHTBOX_ZOOM_STEPS[i];
        break;
      }
    }
    next = found !== null ? found : LIGHTBOX_MIN_ZOOM;
  }
  next = Math.min(LIGHTBOX_MAX_ZOOM, Math.max(LIGHTBOX_MIN_ZOOM, next));
  return { ...(state || {}), mode: 'scale', scale: next };
}

export function toggleLightboxFitActual(state, fitScale = 1) {
  if (!state || state.mode !== 'scale') {
    return { ...(state || {}), mode: 'scale', scale: 1 };
  }
  return { ...state, mode: 'fit', scale: Number(fitScale) > 0 ? Number(fitScale) : 1 };
}

export function cycleLightboxZoomPreset(state, fitScale = 1) {
  if (!state || state.mode !== 'scale') {
    return { ...(state || {}), mode: 'scale', scale: 1 };
  }
  const cur = Number(state.scale) || 1;
  if (cur < 0.98) return { ...state, mode: 'scale', scale: 1 };
  if (cur < 1.48) return { ...state, mode: 'scale', scale: 1.5 };
  if (cur < 1.98) return { ...state, mode: 'scale', scale: 2 };
  return { ...state, mode: 'fit', scale: Number(fitScale) > 0 ? Number(fitScale) : 1 };
}

export function applyLightboxPinch(state, delta, fitScale = 1) {
  const d = Number(delta);
  if (!Number.isFinite(d) || Math.abs(d) < 1e-4) return state;
  const base = state?.mode === 'scale'
    ? Math.min(LIGHTBOX_MAX_ZOOM, Math.max(LIGHTBOX_MIN_ZOOM, Number(state.scale) || 1))
    : (Number(fitScale) > 0 ? Number(fitScale) : 1);
  const clampedDelta = Math.max(-0.5, Math.min(0.5, d));
  const next = Math.min(LIGHTBOX_MAX_ZOOM, Math.max(LIGHTBOX_MIN_ZOOM, base * (1 + clampedDelta)));
  return { ...(state || {}), mode: 'scale', scale: Math.round(next * 1000) / 1000 };
}

const STAGED_CACHE_FILE_RE = /^[0-9a-f]{8,64}\.(png|jpe?g|webp|gif)$/i;
const CONTROL_CHAR_RE = /[\x00-\x1f\x7f]/;

export function resolveSystemPreviewPath({ target = null, entry = null, appHomeDir = '', machine = '' } = {}) {
  // Always prefer the staged cache file verified by walk_safe (O_NOFOLLOW, .git rejected, magic-byte checked)
  // so local and remote projects share one symlink-safe, containment-enforced path for system Preview.
  const rel = String(entry?.rel || '').replace(/\\/g, '/').trim();
  const prefix = `${INLINE_IMAGE_CACHE_DIR}/`;
  const appDir = normalizeFsPath(appHomeDir).replace(/\/+$/, '');
  if (appDir && rel.startsWith(prefix) && /^(\/|[a-zA-Z]:\/)/.test(appDir) && !CONTROL_CHAR_RE.test(appDir)) {
    const file = rel.slice(prefix.length);
    if (STAGED_CACHE_FILE_RE.test(file)) {
      return `${appDir}/${prefix}${file}`;
    }
  }
  const isRemote = Boolean(String(machine || '').trim());
  if (!isRemote && target?.baseDir && target?.relPath) {
    const base = normalizeFsPath(target.baseDir).replace(/\/+$/, '');
    const parts = validRelParts(target.relPath, { allowGit: true });
    if (base && parts && !parts.includes('.git') && !CONTROL_CHAR_RE.test(base) && /^(\/|[a-zA-Z]:\/)/.test(base)) {
      const joined = `${base}/${parts.join('/')}`;
      if (isPreviewableImage(joined) && !CONTROL_CHAR_RE.test(joined)) return joined;
    }
  }
  return '';
}

export function systemOpenFileArgv(filePath, platform = 'macos') {
  const p = String(filePath || '').trim();
  if (!p || CONTROL_CHAR_RE.test(p)) return null;
  if (!/^(\/|[a-zA-Z]:[\\/])/.test(p)) return null;
  const os = String(platform || 'macos').toLowerCase();
  if (os === 'windows' || os === 'win32') return ['cmd', ['/c', 'start', '', p]];
  if (os === 'linux') return ['xdg-open', [p]];
  return ['open', [p]];
}

export function imageLightboxOverlaySpec(payload) {
  return {
    mod: 'pm-project',
    props: { imageLightbox: payload },
    kind: 'dialog',
    frame: 'none',
    width: 0.98,
    height: 0.96,
  };
}

// ---- Auto-open right side tab for newly arriving PM replies / open questions ----
const AUTO_OPEN_LIB_ROOTS = new Set(['docs', 'repo_docs', 'research', 'project']);

export function autoOpenEventKey(ev) {
  if (!ev || typeof ev !== 'object') return '';
  if (ev.msg_id) return `msg:${String(ev.msg_id)}`;
  if (ev.seq !== undefined && ev.seq !== null && Number.isFinite(Number(ev.seq))) {
    return `seq:${Number(ev.seq)}`;
  }
  const type = String(ev.type || '');
  const at = String(ev.at || '');
  const task = String(ev.task || '');
  const text = String(ev.text || '').slice(0, 80);
  return `ev:${type}|${at}|${task}|${text}`;
}

// Extracts previewable images and Library documents referenced in a PM message or question card,
// skipping code blocks and inline code spans and enforcing parseRefLink containment.
export function extractAutoOpenDocRefs(markdown, ctx = null, { limit = INLINE_IMAGE_MAX_PER_MSG } = {}) {
  const src = String(markdown || '');
  if (!src || !ctx || typeof ctx !== 'object') return [];
  const cap = Math.max(0, Number(limit) || 0);
  if (cap === 0) return [];

  const byKey = new Map();
  const order = [];
  const pushUrl = rawUrl => {
    const url = stripMarkdownLinkTarget(rawUrl);
    if (!url) return;
    const parsed = parseRefLink(url, ctx);
    if (!parsed || (parsed.kind !== 'library' && parsed.kind !== 'file')) return;
    if (isPreviewableImage(parsed.path)) {
      const target = resolveImageTarget(parsed, ctx);
      if (!target) return;
      if (byKey.has(target.key) || order.length >= cap) return;
      const item = { tab: 'library', root: target.root, path: target.path, key: target.key, kind: 'image', name: fileName(target.path) };
      byKey.set(target.key, item);
      order.push(item);
      return;
    }
    if (parsed.kind === 'library' && AUTO_OPEN_LIB_ROOTS.has(parsed.root)) {
      const root = parsed.root === 'project' && parsed.path.startsWith('docs/') ? 'docs' : parsed.root;
      const path = parsed.root === 'project' && parsed.path.startsWith('docs/') ? parsed.path.slice('docs/'.length) : parsed.path;
      const key = `${root}/${path}`;
      if (byKey.has(key) || order.length >= cap) return;
      const item = { tab: 'library', root, path, key, kind: 'doc', name: fileName(path) };
      byKey.set(key, item);
      order.push(item);
    }
  };

  const scanProse = chunk => {
    const covered = [];
    MD_IMAGE_OR_LINK_RE.lastIndex = 0;
    let m;
    while ((m = MD_IMAGE_OR_LINK_RE.exec(chunk)) !== null) {
      covered.push([m.index, m.index + m[0].length]);
      pushUrl(m[3]);
    }
    BARE_IMAGE_REF_RE.lastIndex = 0;
    while ((m = BARE_IMAGE_REF_RE.exec(chunk)) !== null) {
      const start = m.index, end = start + m[0].length;
      if (covered.some(([a, b]) => start >= a && end <= b)) continue;
      const cleaned = m[1].replace(/[.,;:!?。，；：！？）)]+$/, '');
      pushUrl(cleaned);
    }
  };

  let inFence = false, fence = '';
  for (const line of src.split('\n')) {
    const fMatch = /^\s*(`{3,}|~{3,})/.exec(line);
    if (fMatch) {
      if (!inFence) { inFence = true; fence = fMatch[1][0]; }
      else if (fMatch[1][0] === fence) { inFence = false; fence = ''; }
      continue;
    }
    if (inFence) continue;
    const parts = line.split(/(`[^`]*`)/g);
    for (let i = 0; i < parts.length; i += 2) {
      if (parts[i]) scanProse(parts[i]);
    }
  }
  return order;
}

// Computes the baseline watermark (seen keys + highest seq/timestamp) from initial conversation events.
export function seedAutoOpenState(events) {
  const seen = new Set();
  let minSeq = 0;
  let minAt = '';
  for (const ev of Array.isArray(events) ? events : []) {
    if (!ev || typeof ev !== 'object') continue;
    const k = autoOpenEventKey(ev);
    if (k) seen.add(k);
    const seq = Number(ev.seq);
    if (Number.isFinite(seq) && seq > minSeq) minSeq = seq;
    const at = String(ev.at || '');
    if (at && at > minAt) minAt = at;
  }
  return { seen, minSeq, minAt };
}

// Records prepended historical events ("load earlier") into `seen` so they never trigger auto-open.
export function markAutoOpenHistory(state, events) {
  if (!state || !(state.seen instanceof Set)) return;
  for (const ev of Array.isArray(events) ? events : []) {
    const k = autoOpenEventKey(ev);
    if (k) state.seen.add(k);
  }
}

// Picks the auto-open side-tab target for newly arrived PM replies or open question cards.
// Guardrails: ignores events in `seenKeys` (baseline history + already auto-opened once),
// ignores historical events at/before baseline `minSeq`/`minAt` (e.g. prepended via "load earlier"),
// skips auto-opening while `editingDirty` is true, and prefers image refs over doc refs.
export function pickAutoOpenTarget(events, ctx, { seenKeys = null, minSeq = 0, minAt = '', tasks = [], editingDirty = false } = {}) {
  const list = Array.isArray(events) ? events : [];
  const seen = seenKeys instanceof Set ? seenKeys : new Set();
  const seqFloor = Number.isFinite(Number(minSeq)) ? Number(minSeq) : 0;
  const atFloor = String(minAt || '');
  const taskById = new Map();
  for (const t of Array.isArray(tasks) ? tasks : []) {
    if (t?.id) taskById.set(t.id, t);
  }
  const newKeys = [];
  let chosen = null;

  for (const ev of list) {
    if (!ev || typeof ev !== 'object') continue;
    const isPm = ev.type === 'pm';
    const isBlockedQuestion = (ev.type === 'question') || (ev.type === 'thread' && ev.status === 'blocked');
    if (!isPm && !isBlockedQuestion) continue;
    const key = autoOpenEventKey(ev);
    if (!key || seen.has(key)) continue;
    const evSeq = (ev.seq !== undefined && ev.seq !== null && Number.isFinite(Number(ev.seq))) ? Number(ev.seq) : null;
    const evAt = String(ev.at || '');
    const olderBySeq = evSeq !== null && seqFloor > 0 && evSeq <= seqFloor;
    const olderByAt = evSeq === null && atFloor && evAt && evAt <= atFloor;
    if (olderBySeq || olderByAt) {
      newKeys.push(key);
      continue;
    }
    if (isBlockedQuestion && ev.task) {
      const t = taskById.get(ev.task);
      if (t && t.status && t.status !== 'blocked') {
        newKeys.push(key);
        continue;
      }
    }
    newKeys.push(key);
    if (editingDirty) continue;
    const refs = extractAutoOpenDocRefs(ev.text || '', ctx);
    if (!refs.length) continue;
    const preferred = refs.find(r => r.kind === 'image') || refs[0];
    chosen = { eventKey: key, target: preferred };
  }
  return { eventKey: chosen?.eventKey || '', target: chosen?.target || null, newKeys };
}

export function parseMentionSpans(text) {
  const str = String(text ?? '');
  if (!str.includes('[@')) return [];
  const spans = [];
  MENTION_LINK_RE.lastIndex = 0;
  let m;
  while ((m = MENTION_LINK_RE.exec(str)) !== null) {
    const scheme = m[2].toLowerCase();
    if (!MENTION_SCHEMES.has(scheme)) continue;
    const ref = parseRefLink(`${scheme}:${m[3]}`);
    if (!ref) continue;
    spans.push({
      start: m.index,
      end: m.index + m[0].length,
      raw: m[0],
      label: m[1],
      ...ref,
    });
  }
  return spans;
}

export function splitMentionSegments(text) {
  const str = String(text ?? '');
  const lines = str.split('\n').map(line => {
    const spans = parseMentionSpans(line);
    if (!spans.length) {
      return { hasMentions: false, segments: line ? [{ type: 'text', text: line }] : [] };
    }
    const segments = [];
    let pos = 0;
    for (const sp of spans) {
      if (sp.start > pos) segments.push({ type: 'text', text: line.slice(pos, sp.start) });
      segments.push({ type: 'mention', ...sp });
      pos = sp.end;
    }
    if (pos < line.length) segments.push({ type: 'text', text: line.slice(pos) });
    return { hasMentions: true, segments };
  });
  return { hasMentions: lines.some(l => l.hasMentions), lines };
}

// GPUI ranks keybindings by (deepest matched context depth, then latest registration order).
// gpui-base's multi-line Textarea sets `.key_context("Input")` on the focused leaf and binds
// up/down/tab/enter/escape to `Input`, consuming arrow keys before an ancestor `PmMentionOpen`
// binding can fire. GPUI's descendant predicate `PmMentionOpen > Input` matches at the leaf
// `Input` depth and overrides Textarea's built-ins while the @ popup is open.
export const MENTION_KEY_BINDINGS = [
  { keystroke: 'up', action: 'pm-mention-up', context: 'PmMentionOpen > Input' },
  { keystroke: 'down', action: 'pm-mention-down', context: 'PmMentionOpen > Input' },
  { keystroke: 'tab', action: 'pm-mention-accept', context: 'PmMentionOpen > Input' },
  { keystroke: 'enter', action: 'pm-mention-accept', context: 'PmMentionOpen > Input' },
  { keystroke: 'escape', action: 'pm-mention-escape', context: 'PmMentionOpen > Input' },
  { keystroke: 'up', action: 'pm-mention-up', context: 'PmMentionOpen' },
  { keystroke: 'down', action: 'pm-mention-down', context: 'PmMentionOpen' },
  { keystroke: 'tab', action: 'pm-mention-accept', context: 'PmMentionOpen' },
  { keystroke: 'enter', action: 'pm-mention-accept', context: 'PmMentionOpen' },
  { keystroke: 'escape', action: 'pm-mention-escape', context: 'PmMentionOpen' },
];

export const SEARCH_KEY_BINDINGS = [
  { keystroke: 'up', action: 'pm-search-up', context: 'PmSearchOpen > Input' },
  { keystroke: 'down', action: 'pm-search-down', context: 'PmSearchOpen > Input' },
  { keystroke: 'enter', action: 'pm-search-accept', context: 'PmSearchOpen > Input' },
  { keystroke: 'escape', action: 'pm-search-escape', context: 'PmSearchOpen > Input' },
  { keystroke: 'tab', action: 'pm-search-scope-next', context: 'PmSearchOpen > Input' },
  { keystroke: 'shift-tab', action: 'pm-search-scope-prev', context: 'PmSearchOpen > Input' },
  { keystroke: 'up', action: 'pm-search-up', context: 'PmSearchOpen' },
  { keystroke: 'down', action: 'pm-search-down', context: 'PmSearchOpen' },
  { keystroke: 'enter', action: 'pm-search-accept', context: 'PmSearchOpen' },
  { keystroke: 'escape', action: 'pm-search-escape', context: 'PmSearchOpen' },
  { keystroke: 'tab', action: 'pm-search-scope-next', context: 'PmSearchOpen' },
  { keystroke: 'shift-tab', action: 'pm-search-scope-prev', context: 'PmSearchOpen' },
];

export function detectMentionQuery(text, cursor, tokens = [], dismissedAt = null) {
  const str = String(text ?? '');
  const cur = Number.isInteger(cursor) ? Math.max(0, Math.min(cursor, str.length)) : str.length;
  let floor = 0;
  for (const span of Array.isArray(tokens) ? tokens : []) {
    const s = span?.range?.start, e = span?.range?.end;
    if (!Number.isInteger(s) || !Number.isInteger(e)) continue;
    if (s < cur && cur < e) return null;
    if (e <= cur && e > floor) floor = e;
  }
  const nl = Math.max(str.lastIndexOf('\n', cur - 1), str.lastIndexOf('\r', cur - 1));
  if (nl + 1 > floor) floor = nl + 1;
  for (let i = cur - 1; i >= floor; i--) {
    if (str[i] !== '@') continue;
    if (i > floor && /[A-Za-z0-9._+-]/.test(str[i - 1])) return null;
    const query = str.slice(i + 1, cur);
    if (query.length > 64 || /^\s/.test(query)) return null;
    if (dismissedAt !== null && dismissedAt === i) return null;
    return { start: i, end: cur, query };
  }
  return null;
}

export function parseGitLsFiles(stdout) {
  const raw = String(stdout ?? '');
  if (!raw) return [];
  const parts = raw.includes('\0') ? raw.split('\0') : raw.split(/\r?\n/);
  const seen = new Set();
  const out = [];
  for (let item of parts) {
    if (!item) continue;
    if (item.startsWith('./')) item = item.slice(2);
    item = item.replace(/^\/+/, '');
    if (!item || item === '.git' || item.startsWith('.git/') || item.includes('/.git/')) continue;
    if (seen.has(item)) continue;
    seen.add(item);
    out.push(item);
  }
  return out;
}

export function indexRepoFiles(paths, folders = []) {
  const list = Array.isArray(paths) ? paths : [];
  const aliases = new Set(
    Array.isArray(folders) && folders.length >= 2
      ? folders.map(f => String(f?.alias || '').trim()).filter(Boolean)
      : [],
  );
  const out = [];
  for (const item of list) {
    const path = typeof item === 'string' ? item : String(item?.path || '');
    if (!path) continue;
    if (
      item &&
      typeof item === 'object' &&
      typeof item.path === 'string' &&
      typeof item.nameLow === 'string' &&
      (aliases.size < 2 || typeof item.alias === 'string')
    ) {
      out.push(item);
      continue;
    }
    let alias = '';
    let relPath = path;
    if (aliases.size >= 2) {
      const firstSlash = path.indexOf('/');
      const head = firstSlash > 0 ? path.slice(0, firstSlash) : '';
      if (aliases.has(head)) {
        alias = head;
        relPath = path.slice(firstSlash + 1);
      }
    }
    const slash = relPath.lastIndexOf('/');
    const name = slash >= 0 ? relPath.slice(slash + 1) : relPath;
    const relDir = slash >= 0 ? relPath.slice(0, slash) : '';
    const dir = relDir;
    out.push({ path, name, dir, alias, relPath, pathLow: path.toLowerCase(), nameLow: name.toLowerCase() });
  }
  return out;
}

function isSubsequence(needle, hay) {
  if (!needle) return true;
  if (needle.length > hay.length) return false;
  let j = 0;
  for (let i = 0; i < hay.length && j < needle.length; i++) {
    if (hay[i] === needle[j]) j++;
  }
  return j === needle.length;
}

function segmentMatch(hay, needle) {
  const idx = hay.indexOf(needle);
  if (idx < 0) return -1;
  if (idx === 0) return 0;
  return /[^a-z0-9]/.test(hay[idx - 1]) ? 1 : 2;
}

export function scoreMentionMatch(queryLow, terms, primaryLow, secondaryLow = '') {
  if (!terms.length) return 1;
  const combined = secondaryLow ? `${primaryLow} ${secondaryLow}` : primaryLow;
  if (terms.every(term => combined.includes(term))) {
    if (primaryLow === queryLow) return 1000;
    const pSeg = segmentMatch(primaryLow, queryLow);
    if (pSeg === 0) return 800;
    if (pSeg === 1) return 650;
    if (terms.every(term => primaryLow.includes(term))) return 500;
    const sSeg = secondaryLow ? segmentMatch(secondaryLow, queryLow) : -1;
    if (sSeg === 0 || sSeg === 1) return 350;
    return 250;
  }
  if (terms.length === 1 && queryLow.length >= 2) {
    const first = queryLow[0];
    if (primaryLow.includes(first) && isSubsequence(queryLow, primaryLow)) return 120;
    if (secondaryLow && secondaryLow.includes(first) && isSubsequence(queryLow, secondaryLow)) return 80;
  }
  return 0;
}

function buildMentionCandidate(base) {
  const linkText = formatMentionLink({ kind: base.kind, target: base.target, label: base.label });
  const chipLabel = `@${sanitizeMentionLabel(base.label || base.target) || base.target}`;
  return {
    rowKind: 'item',
    ...base,
    linkText,
    chipLabel,
    token: { id: `${base.kind}:${base.target}`, text: linkText, label: chipLabel },
    primaryLow: String(base.searchPrimary || base.label || '').toLowerCase(),
    secondaryLow: String(base.searchSecondary || '').toLowerCase(),
  };
}

export function buildMentionMenu({
  lang = 'en',
  category = 'all',
  query = '',
  threads = { open: [], sessions: [], finished: [] },
  tasks = [],
  extraThreads = [],
  taskNumbers = null,
  libraryFiles = [],
  repoFiles = [],
  folders = [],
  foldersEmpty = false,
  excludeThread = '',
  filesLoading = false,
  filesError = '',
  libraryLoading = false,
  libraryError = '',
  threadsLoading = false,
} = {}) {
  const byTask = new Map((Array.isArray(tasks) ? tasks : []).filter(t => t?.id).map(t => [t.id, t]));
  const threadItems = [];
  const activeThreads = [];
  const seenThreadIds = new Set();
  for (const r of Array.isArray(threads?.open) ? threads.open : []) {
    if (!r?.task || seenThreadIds.has(r.task) || (excludeThread && r.task === excludeThread)) continue;
    seenThreadIds.add(r.task);
    const task = byTask.get(r.task);
    const num = taskNumber(task) || taskNumber(r) || taskNumber(taskNumbers?.[r.task]);
    const engine = task ? engineLabel(task) : '';
    const folderAlias = String(task?.folder_alias || r.folderAlias || '').trim();
    const active = ['waiting', 'review', 'working'].includes(r.group);
    const numTag = formatTaskNumber(num);
    const item = buildMentionCandidate({
      key: `thread:${r.task}`,
      category: 'threads',
      kind: 'thread',
      target: r.task,
      ...(num ? { number: num } : {}),
      ...(folderAlias ? { folderAlias } : {}),
      label: r.title || r.task,
      subtitle: [numTag, r.branch, engine].filter(Boolean).join(' · ') || r.task,
      typeLabel: word(lang, 'mentionTypeThread'),
      icon: 'hook',
      tone: r.tone || 'quiet',
      group: r.group || 'working',
      working: Boolean(r.working),
      status: r.status || '',
      dimmed: ['offline', 'paused', 'parked'].includes(r.group),
      active,
      tieRank: active ? 0 : 3,
      searchPrimary: numTag ? `${numTag} ${r.title || r.task}` : (r.title || r.task),
      searchSecondary: `${num ? `${num} #${num} ` : ''}${r.task} ${r.branch || ''} ${folderAlias} ${r.latest || ''}`,
    });
    threadItems.push(item);
    if (active) activeThreads.push(item);
  }
  for (const s of Array.isArray(threads?.sessions) ? threads.sessions : []) {
    if (!s?.address) continue;
    const active = s.status !== 'idle';
    const item = buildMentionCandidate({
      key: `session:${s.address}`,
      category: 'threads',
      kind: 'session',
      target: s.address,
      label: s.label || s.address,
      subtitle: s.address,
      typeLabel: word(lang, 'mentionTypeSession'),
      icon: 'agent',
      program: s.program || null,
      sessionStatus: s.status || 'idle',
      dimmed: s.status === 'idle',
      active,
      tieRank: active ? 0 : 3,
      searchPrimary: s.label || s.address,
      searchSecondary: `${s.address} ${s.program?.name || ''}`,
    });
    threadItems.push(item);
    if (active) activeThreads.push(item);
  }
  const pushHistoricalThread = raw => {
    if (!raw || typeof raw !== 'object' || raw.review_of) return;
    const id = String(raw.task || raw.id || '').trim();
    if (!id || seenThreadIds.has(id) || (excludeThread && id === excludeThread)) return;
    const task = byTask.get(id);
    const status = String(raw.status || task?.status || '');
    if (status === GIVEN_UP) return;
    seenThreadIds.add(id);
    const num = taskNumber(task) || taskNumber(raw) || taskNumber(taskNumbers?.[id]);
    const numTag = formatTaskNumber(num);
    const title = String(raw.title || task?.title || id);
    const branch = String(raw.branch || task?.branch || '');
    const item = buildMentionCandidate({
      key: `thread:${id}`,
      category: 'threads',
      kind: 'thread',
      target: id,
      ...(num ? { number: num } : {}),
      label: title,
      subtitle: [numTag, id].filter(Boolean).join(' · '),
      typeLabel: word(lang, 'mentionTypeThread'),
      icon: 'hook',
      tone: 'quiet',
      group: 'finished',
      working: false,
      status: status || 'done',
      dimmed: true,
      active: false,
      tieRank: 4,
      searchPrimary: numTag ? `${numTag} ${title}` : title,
      searchSecondary: `${num ? `${num} #${num} ` : ''}${id}${branch ? ` ${branch}` : ''}`,
    });
    threadItems.push(item);
  };
  for (const r of Array.isArray(threads?.finished) ? threads.finished : []) {
    pushHistoricalThread(r);
  }
  const extraFinishedFromTasks = (Array.isArray(tasks) ? tasks : [])
    .filter(t => t?.id && !t.review_of && CLOSED.includes(t.status) && t.status !== GIVEN_UP)
    .sort((a, b) => String(b.updated || '').localeCompare(String(a.updated || '')));
  for (const t of extraFinishedFromTasks) {
    pushHistoricalThread(t);
  }
  for (const raw of Array.isArray(extraThreads) ? extraThreads : []) {
    if (!raw || typeof raw !== 'object' || raw.review_of) continue;
    const norm = raw.task ? raw : normalizeProjectTaskRow(raw);
    if (norm) pushHistoricalThread(norm);
  }

  const libList = validLibraryPayload(libraryFiles).files.filter(f => f.kind !== 'folder' && !(f.archive && f.hidden));
  const libraryRepoPaths = new Set();
  const libraryItems = libList.map(f => {
    if (f.root === 'repo_docs' || f.root === 'instructions') libraryRepoPaths.add(f.path);
    const title = libraryDocTitle(f);
    const icon = f.root === 'research' ? 'report' : f.root === 'instructions' ? 'lock' : 'file';
    const typeLabel = f.root === 'research'
      ? word(lang, 'mentionTypeResearch')
      : f.root === 'repo_docs'
        ? word(lang, 'mentionTypeRepoDoc')
        : f.root === 'instructions'
          ? word(lang, 'mentionTypeInstructions')
          : word(lang, 'mentionTypeDoc');
    const subtitle = f.root === 'research'
      ? (f.summary || f.path)
      : f.root === 'repo_docs'
        ? (f.title && f.title !== title ? `${f.title} · ${f.path}` : f.path)
        : (f.path !== title ? f.path : '');
    return buildMentionCandidate({
      key: `library:${f.root}/${f.path}`,
      category: 'library',
      kind: 'library',
      root: f.root,
      path: f.path,
      target: `${f.root}/${f.path}`,
      label: title,
      subtitle,
      typeLabel,
      icon,
      dimmed: Boolean(f.archive || f.superseded_by),
      active: false,
      tieRank: f.superseded_by ? 3.5 : 1,
      searchPrimary: title,
      searchSecondary: `${f.root}/${f.path} ${f.title || ''} ${f.summary || f.description || ''} ${f.task_title || ''}`,
    });
  });

  const folderList = Array.isArray(folders) ? folders : [];
  const indexedFiles = indexRepoFiles(repoFiles, folderList);
  const fileTypeLabel = word(lang, 'mentionTypeFile');
  const buildFileItem = f => buildMentionCandidate({
    key: `file:${f.path}`,
    category: 'files',
    kind: 'file',
    path: f.path,
    folderAlias: f.alias || '',
    target: f.path,
    label: f.name,
    subtitle: f.dir,
    typeLabel: fileTypeLabel,
    icon: 'file',
    dimmed: false,
    active: false,
    tieRank: 2,
    searchPrimary: f.name,
    searchSecondary: f.path,
  });

  const qRaw = String(query ?? '').trim();
  const qLow = qRaw.toLowerCase();
  const terms = searchTerms(qRaw);
  const activeCat = MENTION_CATEGORIES.includes(category) ? category : 'all';

  if (activeCat === 'all' && !qRaw) {
    const cats = [
      { rowKind: 'category', key: 'cat:threads', category: 'threads', label: word(lang, 'mentionThreads'), icon: 'hook', count: threadItems.length },
      { rowKind: 'category', key: 'cat:library', category: 'library', label: word(lang, 'mentionLibrary'), icon: 'library', count: libraryItems.length },
      { rowKind: 'category', key: 'cat:files', category: 'files', label: word(lang, 'mentionFiles'), icon: 'file', count: indexedFiles.length },
    ];
    const quick = activeThreads.slice(0, 6);
    return {
      mode: 'root',
      category: 'all',
      title: '',
      items: [...cats, ...quick],
      dividerBefore: quick.length ? cats.length : -1,
      loading: false,
      error: '',
      emptyText: '',
    };
  }

  const qNumMatch = /^#?([1-9][0-9]*)$/.exec(qLow);
  const qNumStr = qNumMatch ? qNumMatch[1] : '';
  const qNum = qNumStr ? Number(qNumStr) : 0;
  const scorePoolItem = it => {
    let score = scoreMentionMatch(qLow, terms, it.primaryLow, it.secondaryLow);
    if (qNum && it.number) {
      if (it.number === qNum) score = Math.max(score, 1100);
      else if (String(it.number).startsWith(qNumStr)) score = Math.max(score, 450);
    }
    return score;
  };
  if (activeCat !== 'all') {
    const title = activeCat === 'threads'
      ? word(lang, 'mentionThreads')
      : activeCat === 'library'
        ? word(lang, 'mentionLibrary')
        : (folderList.length >= 2 ? word(lang, 'mentionFilesMultiTitle', folderList.length) : word(lang, 'mentionFiles'));
    const error = activeCat === 'files' ? String(filesError || '')
      : activeCat === 'library' ? String(libraryError || '')
      : '';
    let items;
    if (activeCat === 'files') {
      if (!terms.length) {
        items = indexedFiles.slice(0, 40).map(buildFileItem);
      } else {
        const hits = [];
        for (let i = 0; i < indexedFiles.length; i++) {
          const f = indexedFiles[i];
          const score = scoreMentionMatch(qLow, terms, f.nameLow, f.pathLow);
          if (score > 0) hits.push({ score, order: i, f });
        }
        hits.sort((a, b) => b.score - a.score || a.f.path.length - b.f.path.length || a.order - b.order);
        items = hits.slice(0, 40).map(h => buildFileItem(h.f));
      }
    } else {
      const pool = activeCat === 'threads' ? threadItems : libraryItems;
      if (!terms.length) {
        items = pool.slice(0, 50);
      } else {
        const hits = [];
        for (let i = 0; i < pool.length; i++) {
          const it = pool[i];
          const score = activeCat === 'threads' ? scorePoolItem(it) : scoreMentionMatch(qLow, terms, it.primaryLow, it.secondaryLow);
          if (score > 0) hits.push({ score, order: i, it });
        }
        hits.sort((a, b) => b.score - a.score || a.it.tieRank - b.it.tieRank || a.order - b.order);
        items = hits.slice(0, 50).map(h => h.it);
      }
    }
    const loading = activeCat === 'files' ? Boolean(filesLoading && !indexedFiles.length)
      : activeCat === 'library' ? Boolean(libraryLoading && !libraryItems.length)
      : activeCat === 'threads' ? Boolean(threadsLoading && !items.length)
      : false;
    const loadingText = !loading ? ''
      : activeCat === 'files' ? word(lang, 'mentionLoadingFiles')
      : activeCat === 'threads' ? word(lang, 'threadsSearching')
      : word(lang, 'libraryLoading');
    const emptyKey = qRaw
      ? 'mentionEmpty'
      : activeCat === 'threads'
        ? 'mentionEmptyThreads'
        : activeCat === 'library'
          ? 'mentionEmptyLibrary'
          : (foldersEmpty && folderList.length === 0 ? 'mentionEmptyFilesNoFolders' : 'mentionEmptyFiles');
    return {
      mode: 'category',
      category: activeCat,
      title,
      items,
      dividerBefore: -1,
      loading,
      loadingText,
      error,
      emptyText: items.length || loading || error ? '' : word(lang, emptyKey),
    };
  }

  // Flat global search across Threads, Library, and Files.
  const scored = [];
  for (let i = 0; i < threadItems.length; i++) {
    const it = threadItems[i];
    const score = scorePoolItem(it);
    if (score > 0) scored.push({ score, tie: it.tieRank, order: i, item: it });
  }
  for (let i = 0; i < libraryItems.length; i++) {
    const it = libraryItems[i];
    const score = scoreMentionMatch(qLow, terms, it.primaryLow, it.secondaryLow);
    if (score > 0) scored.push({ score, tie: it.tieRank, order: i, item: it });
  }
  for (let i = 0; i < indexedFiles.length; i++) {
    const f = indexedFiles[i];
    if (libraryRepoPaths.has(f.path)) continue;
    const score = scoreMentionMatch(qLow, terms, f.nameLow, f.pathLow);
    if (score > 0) scored.push({ score, tie: 2, order: i, f });
  }
  scored.sort((a, b) => b.score - a.score || a.tie - b.tie || a.order - b.order);
  const top = scored.slice(0, 30).map(h => h.item || buildFileItem(h.f));
  const anyLoading = Boolean(
    (filesLoading && !indexedFiles.length)
    || (libraryLoading && !libraryItems.length)
    || threadsLoading
  );
  const loading = !top.length && anyLoading;
  const loadingText = !loading ? ''
    : threadsLoading ? word(lang, 'threadsSearching')
    : (filesLoading && !indexedFiles.length) ? word(lang, 'mentionLoadingFiles')
    : word(lang, 'libraryLoading');
  return {
    mode: 'search',
    category: 'all',
    title: '',
    items: top,
    dividerBefore: -1,
    loading,
    loadingText,
    error: '',
    emptyText: top.length || loading ? '' : word(lang, 'mentionEmpty'),
  };
}

// ---- Selectable plain-text HTML & Quote-reply helpers -------------------------------------

export function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const PLAIN_HTML_CACHE = new Map();
export function plainTextToHtml(text) {
  const raw = String(text ?? '');
  return fifoCacheGetSet(PLAIN_HTML_CACHE, raw, () => {
    const safe = escapeHtml(raw.replace(/\r\n?/g, '\n')).replace(/\n/g, '<br/>');
    return `<span>${safe}</span>`;
  }, 512);
}

export function markdownToPlain(md) {
  const raw = String(md ?? '').replace(/\r\n?/g, '\n');
  if (!raw.trim()) return '';
  const tableSep = /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/;
  const out = [];
  for (const rawLine of raw.split('\n')) {
    if (/^\s*(`{3,}|~{3,})/.test(rawLine)) continue;
    if (tableSep.test(rawLine)) continue;
    let line = rawLine
      .replace(/^\s*#{1,6}\s+/, '')
      .replace(/^\s*(?:>\s?)+/, '')
      .replace(/^\s*(?:[-*+]|\d{1,9}[.)])\s+/, '')
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/\*\*|__|~~|`/g, '');
    if (line.includes('|')) {
      line = line.replace(/^\s*\||\|\s*$/g, '').replace(/\|/g, ' ');
    }
    line = line.replace(/[ \t]+/g, ' ').trim();
    if (line) out.push(line);
    else if (out.length && out[out.length - 1] !== '') out.push('');
  }
  while (out.length && out[out.length - 1] === '') out.pop();
  return out.join('\n');
}

const normLines = s => String(s ?? '')
  .replace(/\r\n?/g, '\n')
  .split('\n')
  .map(l => l.replace(/[ \t]+/g, ' ').trim())
  .filter(Boolean)
  .join('\n');
const bareCompare = s => squash(String(s ?? '').replace(/[*_`~|#>]/g, ' '));

function clipAtBoundary(text, maxChars) {
  const clean = String(text ?? '').trim();
  if (clean.length <= maxChars) return clean;
  const head = clean.slice(0, maxChars);
  const stop = Math.max(
    ...['\n', '。', '！', '？', '；', '. ', '! ', '? ', '; '].map(mark => head.lastIndexOf(mark)),
  );
  if (stop >= Math.floor(maxChars * 0.5)) return `${head.slice(0, stop + 1).trim()}…`;
  return `${head.trimEnd()}…`;
}

export const QUOTE_MIN_SELECTION_CHARS = 4;

export function isQuotableSelection(text, minChars = QUOTE_MIN_SELECTION_CHARS) {
  const clean = squash(text);
  if (!clean || !/[\p{L}\p{N}]/u.test(clean)) return false;
  if (clean.length >= minChars) return true;
  return clean.split(/\s+/).filter(w => /[\p{L}\p{N}]/u.test(w)).length >= 2;
}

export function extractClipboardQuote(clipboard, rawText, {
  maxChars = 500,
  maxSelectionChars = 1200,
  baseline = undefined,
  minChars = QUOTE_MIN_SELECTION_CHARS,
  displayText = undefined,
} = {}) {
  const raw = String(rawText ?? '').replace(/\r\n?/g, '\n').trim();
  const disp = displayText !== undefined ? String(displayText ?? '').replace(/\r\n?/g, '\n').trim() : '';
  if (!raw && !disp) return { text: '', exact: false };
  const clip = String(clipboard ?? '').replace(/\r\n?/g, '\n').trim();
  const hasBaseline = baseline !== undefined;
  const base = hasBaseline ? String(baseline ?? '').replace(/\r\n?/g, '\n').trim() : null;
  const fresh = !hasBaseline || clip !== base;
  const plain = markdownToPlain(raw);
  const dispPlain = disp && disp !== raw ? markdownToPlain(disp) : '';
  const clipBare = bareCompare(clip);
  if (clip && clip.length <= 4000 && fresh && isQuotableSelection(clipBare, minChars)) {
    const clipLines = normLines(clip);
    const clipFlat = squash(clip);
    const matchesSource = (src, srcPlain) => {
      if (!src) return false;
      const srcLines = normLines(src);
      const plainLines = normLines(srcPlain);
      return src.includes(clip)
        || (clipLines && srcLines.includes(clipLines))
        || (clipFlat && squash(src).includes(clipFlat))
        || (clipLines && plainLines.includes(clipLines))
        || (clipFlat && squash(srcPlain).includes(clipFlat))
        || (Boolean(clipBare) && bareCompare(srcPlain).includes(clipBare));
    };
    const matched = (disp && disp !== raw && matchesSource(disp, dispPlain)) || matchesSource(raw, plain);
    if (matched) {
      return { text: clipAtBoundary(clip, maxSelectionChars), exact: true };
    }
  }
  const whole = disp && disp !== raw ? (dispPlain || disp) : (plain || raw);
  return { text: clipAtBoundary(whole, maxChars), exact: false };
}

const PARA_FENCE_OPEN_RE = /^( {0,3})(`{3,}|~{3,})(.*)$/;
const PARA_HR_RE = /^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$/;
const PARA_HEADING_RE = /^ {0,3}#{1,6}(?:[ \t]+|$)/;
const PARA_SETEXT_RE = /^ {0,3}(?:={2,}|-{2,})[ \t]*$/;
const PARA_BLOCKQUOTE_RE = /^ {0,3}>/;
const PARA_TABLE_SEP_RE = /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/;
const PARA_SINGLE_COL_SEP_RE = /^\s*\|\s*:?-{3,}:?\s*\|\s*$/;
const PARA_LIST_ITEM_RE = /^( {0,3})([-*+]|\d{1,9}[.)])(?:([ \t]+)|$)/;

function isFenceOpen(line) {
  const m = PARA_FENCE_OPEN_RE.exec(line);
  if (!m) return null;
  const marker = m[2];
  const info = m[3] || '';
  if (marker[0] === '`' && info.includes('`')) return null;
  return { ch: marker[0], len: marker.length };
}

function isFenceClose(line, fence) {
  const re = new RegExp(`^ {0,3}${fence.ch === '~' ? '~' : '`'}{${fence.len},}[ \\t]*$`);
  return re.test(line);
}

function isTableStart(lines, i) {
  if (i + 1 >= lines.length) return false;
  const cur = lines[i].line;
  const next = lines[i + 1].line;
  if (!cur.includes('|')) return false;
  if (PARA_TABLE_SEP_RE.test(next)) return true;
  return /^\s*\|/.test(cur) && PARA_SINGLE_COL_SEP_RE.test(next);
}

// Splits a Markdown message into natural, hover-quotable blocks:
// - Paragraphs, headings (standalone so sections & lists stay symmetrical), each top-level list item
//   (keeping nested sub-lists, continuations, and nested code fences together), blockquotes,
//   fenced code blocks, and GFM pipe tables each form one block.
// - Thematic breaks (`---`, `***`, `___`) are emitted with `quotable: false`.
// - Every block records exact UTF-16 `{ start, end }` offsets in the normalized input, sharing the
//   same range representation as arbitrary text selections (future #1335).
export function splitMarkdownParagraphs(markdown) {
  const raw = String(markdown ?? '').replace(/\r\n?/g, '\n');
  if (!raw.trim()) return [];
  const rawLines = raw.split('\n');
  const lines = [];
  let offset = 0;
  for (const line of rawLines) {
    lines.push({ line, start: offset, end: offset + line.length });
    offset += line.length + 1;
  }

  const blocks = [];
  let quotableIdx = 0;
  const emit = (kind, from, to, quotable = true) => {
    while (from <= to && !lines[from].line.trim()) from++;
    while (to >= from && !lines[to].line.trim()) to--;
    if (from > to) return;
    const start = lines[from].start;
    const end = lines[to].end;
    const md = raw.slice(start, end);
    let text = '';
    if (quotable) {
      text = kind === 'code' ? md.trim() : (markdownToPlain(md) || md.trim());
    }
    const isQuotable = quotable && Boolean(text);
    blocks.push({
      index: isQuotable ? quotableIdx++ : -1,
      kind,
      markdown: md,
      text,
      start,
      end,
      quotable: isQuotable,
    });
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i].line;
    if (!line.trim()) { i++; continue; }

    // 1. Fenced code block
    const fence = isFenceOpen(line);
    if (fence) {
      const from = i;
      i++;
      while (i < lines.length && !isFenceClose(lines[i].line, fence)) i++;
      if (i < lines.length) i++;
      emit('code', from, i - 1, true);
      continue;
    }

    // 2. Thematic break (checked before list item because `- - -` / `* * *` match list markers)
    if (PARA_HR_RE.test(line)) {
      emit('hr', i, i, false);
      i++;
      continue;
    }

    // 3. ATX Heading (standalone block)
    if (PARA_HEADING_RE.test(line)) {
      emit('heading', i, i, true);
      i++;
      continue;
    }

    // 4. Blockquote (contiguous > lines + lazy continuations)
    if (PARA_BLOCKQUOTE_RE.test(line)) {
      const from = i;
      i++;
      while (i < lines.length) {
        const cur = lines[i].line;
        if (!cur.trim()) break;
        if (PARA_BLOCKQUOTE_RE.test(cur)) { i++; continue; }
        if (isFenceOpen(cur) || PARA_HR_RE.test(cur) || PARA_HEADING_RE.test(cur) || PARA_LIST_ITEM_RE.test(cur) || isTableStart(lines, i)) {
          break;
        }
        i++;
      }
      emit('blockquote', from, i - 1, true);
      continue;
    }

    // 5. GFM Pipe Table (atomic block)
    if (isTableStart(lines, i)) {
      const from = i;
      i += 2;
      while (i < lines.length) {
        const cur = lines[i].line;
        if (!cur.trim() || !cur.includes('|')) break;
        if (isFenceOpen(cur) || PARA_HR_RE.test(cur) || PARA_HEADING_RE.test(cur) || PARA_BLOCKQUOTE_RE.test(cur)) break;
        i++;
      }
      emit('table', from, i - 1, true);
      continue;
    }

    // 6. Top-level List Item (each top-level item is one block; nested sub-items/fences/continuations stay attached)
    const listMatch = PARA_LIST_ITEM_RE.exec(line);
    if (listMatch) {
      const from = i;
      const leadLen = listMatch[1].length;
      const markerLen = listMatch[2].length;
      const gapLen = listMatch[3] ? Math.min(listMatch[3].length, 4) : 1;
      const contentIndent = leadLen + markerLen + gapLen;
      const minChildIndent = Math.max(2, Math.min(contentIndent, leadLen + 2));
      i++;
      let nestedFence = null;
      while (i < lines.length) {
        const cur = lines[i].line;
        if (nestedFence) {
          if (isFenceClose(cur, nestedFence)) nestedFence = null;
          i++;
          continue;
        }
        if (!cur.trim()) {
          let look = i + 1;
          while (look < lines.length && !lines[look].line.trim()) look++;
          if (look < lines.length && indentOf(lines[look].line) >= minChildIndent) {
            i++;
            continue;
          }
          break;
        }
        const curIndent = indentOf(cur);
        if (curIndent >= minChildIndent) {
          const innerSlice = cur.slice(Math.min(curIndent, contentIndent));
          const opens = isFenceOpen(innerSlice);
          if (opens) nestedFence = opens;
          i++;
          continue;
        }
        if (PARA_HR_RE.test(cur) || PARA_HEADING_RE.test(cur) || PARA_BLOCKQUOTE_RE.test(cur) || isFenceOpen(cur) || PARA_LIST_ITEM_RE.test(cur) || isTableStart(lines, i)) {
          break;
        }
        // Lazy wrapped continuation line of the current list item
        i++;
      }
      emit('list-item', from, i - 1, true);
      continue;
    }

    // 7. Regular Paragraph (or Setext heading if immediately underlined with === / ---)
    const from = i;
    i++;
    if (i < lines.length && PARA_SETEXT_RE.test(lines[i].line)) {
      emit('heading', from, i, true);
      i++;
      continue;
    }
    while (i < lines.length) {
      const cur = lines[i].line;
      if (!cur.trim()) break;
      if (isFenceOpen(cur) || PARA_HR_RE.test(cur) || PARA_HEADING_RE.test(cur) || PARA_BLOCKQUOTE_RE.test(cur) || PARA_LIST_ITEM_RE.test(cur) || isTableStart(lines, i)) {
        break;
      }
      if (PARA_SETEXT_RE.test(cur)) break;
      i++;
    }
    emit('paragraph', from, i - 1, true);
  }

  return blocks;
}

function stripInlineMarkdownWithMap(rawSlice, baseOffset) {
  const plainChars = [];
  const rawIdx = [];
  const s = String(rawSlice ?? '');
  let i = 0;
  while (i < s.length) {
    // Line-leading markdown block markers
    if (i === 0 || s[i - 1] === '\n') {
      const prefix = /^(?:[ \t]*(?:#{1,6}[ \t]+|(?:>[ \t]?)+|(?:[-*+]|\d{1,9}[.)])[ \t]+))/.exec(s.slice(i));
      if (prefix) { i += prefix[0].length; continue; }
    }
    // Markdown image/link: ![alt](url) or [label](url)
    if (s[i] === '[' || (s[i] === '!' && s[i + 1] === '[')) {
      const startBracket = s[i] === '!' ? i + 1 : i;
      const closeBracket = s.indexOf(']', startBracket + 1);
      if (closeBracket > startBracket && s[closeBracket + 1] === '(') {
        const closeParen = s.indexOf(')', closeBracket + 2);
        if (closeParen > closeBracket + 1 && !s.slice(startBracket, closeParen).includes('\n')) {
          const innerStart = startBracket + 1;
          for (let j = innerStart; j < closeBracket; j++) {
            const ch = s[j];
            if (ch === '*' || ch === '_' || ch === '~' || ch === '`') continue;
            plainChars.push(ch);
            rawIdx.push(baseOffset + j);
          }
          i = closeParen + 1;
          continue;
        }
      }
    }
    if ((s[i] === '*' && s[i + 1] === '*') || (s[i] === '_' && s[i + 1] === '_') || (s[i] === '~' && s[i + 1] === '~')) {
      i += 2;
      continue;
    }
    if (s[i] === '`') { i++; continue; }
    plainChars.push(s[i]);
    rawIdx.push(baseOffset + i);
    i++;
  }
  return { plain: plainChars.join(''), rawIdx };
}

export function locateQuoteRange(rawText, excerpt) {
  const raw = String(rawText ?? '').replace(/\r\n?/g, '\n');
  const needle = String(excerpt ?? '').replace(/\r\n?/g, '\n').trim();
  if (!raw || !needle) return null;
  const paras = splitMarkdownParagraphs(raw);
  const idx = raw.indexOf(needle);
  if (idx >= 0) {
    const start = idx;
    const end = idx + needle.length;
    const hit = paras.find(p => p.quotable && start >= p.start && end <= p.end);
    return normalizeQuoteRange({
      start,
      end,
      ...(hit ? { paragraph: hit.index, kind: hit.kind } : {}),
    });
  }
  // Fallback: map rendered plain-text selection (e.g. stripped **bold**, `code`, or [label](thread:...))
  // back to canonical rawText UTF-16 coordinates so clipboard & future #1335 selections align with paragraphs.
  const candidates = [needle];
  const noNumPrefix = needle.replace(/#\d+\s+/g, '');
  if (noNumPrefix && noNumPrefix !== needle) candidates.push(noNumPrefix);
  const { plain, rawIdx } = stripInlineMarkdownWithMap(raw, 0);
  for (const cand of candidates) {
    const pIdx = plain.indexOf(cand);
    if (pIdx >= 0 && pIdx + cand.length - 1 < rawIdx.length) {
      const start = rawIdx[pIdx];
      const end = rawIdx[pIdx + cand.length - 1] + 1;
      const hit = paras.find(p => p.quotable && start >= p.start && end <= p.end);
      return normalizeQuoteRange({
        start,
        end,
        ...(hit ? { paragraph: hit.index, kind: hit.kind } : {}),
      });
    }
  }
  // Whole-paragraph plain match (e.g. table or multiline paragraph copied after markdown flattening)
  const flatNeedle = squash(needle);
  if (flatNeedle) {
    const hit = paras.find(p => p.quotable && squash(p.text) === flatNeedle);
    if (hit) return normalizeQuoteRange({ start: hit.start, end: hit.end, paragraph: hit.index, kind: hit.kind });
  }
  return null;
}

export function withQuote(quotes, ...next) {
  const added = next.flatMap(item => (Array.isArray(item) ? item : [item]));
  return normalizeQuotes([...(Array.isArray(quotes) ? quotes : []), ...added]);
}

export function withoutQuote(quotes, id) {
  return (Array.isArray(quotes) ? quotes : []).filter(q => q?.id !== id);
}

function stripQuoteCodeFences(text) {
  return String(text ?? '')
    .replace(/\r\n?/g, '\n')
    .replace(/^\s*(?:`{3,}|~{3,})[^\n]*\n?/, '')
    .replace(/\n?\s*(?:`{3,}|~{3,})\s*$/, '');
}

export function quotePreviewLine(text, maxLen = 96) {
  const stripped = stripQuoteCodeFences(text);
  const line = squash(stripped || text);
  if (!line || line.length <= maxLen) return line;
  return `${line.slice(0, Math.max(1, maxLen - 1)).trimEnd()}…`;
}

const QUOTE_CARD_STOP_RE = /[。！？.!?]/;
const QUOTE_CARD_SOFT_RE = /[，、；：,;:\s]/;
const QUOTE_CARD_TRAIL_WEAK_RE = /[,，、:：;；\-—(\[（【\s]+$/;

// Multi-line bounded preview for quote cards inside sent message bubbles:
// caps visual line count, snaps truncation to a natural sentence/clause/word boundary when possible,
// and always terminates truncated previews with an explicit ellipsis (…).
const QUOTE_PREVIEW_CACHE = new Map();
export function quoteCardPreview(text, {
  maxLines = 3,
  maxWidthPx = 400,
  fontSize = 12.5,
} = {}) {
  const raw = String(text ?? '');
  const limit = Math.max(1, Math.floor(maxLines || 3));
  const width = Math.max(120, Number.isFinite(maxWidthPx) && maxWidthPx > 0 ? maxWidthPx : 400);
  const fSize = Number.isFinite(fontSize) && fontSize > 0 ? fontSize : 12.5;
  const cacheKey = `${limit}\0${width}\0${fSize}\0${raw}`;
  return fifoCacheGetSet(QUOTE_PREVIEW_CACHE, cacheKey, () => {
    const stripped = stripQuoteCodeFences(raw);
    const flat = squash(stripped || raw);
    if (!flat) return { lines: [], text: '', truncated: false };
    const budgetEm = Math.max(6, width / fSize);
    const wrapped = wrapTooltipText(flat, width, { maxLines: limit + 1, fontSize: fSize, padX: 0 });
    if (wrapped.lines.length <= limit && !wrapped.truncated) {
      return { lines: wrapped.lines, text: wrapped.lines.join('\n'), truncated: false };
    }
    const lines = wrapped.lines.slice(0, limit);
    const ellBudget = Math.max(3, budgetEm - 1.0);
    const chars = Array.from(lines[limit - 1].replace(/…+$/, ''));
    while (chars.length > 0 && measureEm(chars.join('')) > ellBudget) chars.pop();
    let last = chars.join('').trimEnd();
    // Prefer snapping back to a clean sentence/clause/word boundary inside the latter portion of the last line
    // so we never hard-cut mid-word or leave awkward fragments before `…`.
    if (last.length >= 4) {
      const minCutEm = measureEm(last) * 0.45;
      let bestStop = -1;
      let bestSoft = -1;
      let accEm = 0;
      const arr = Array.from(last);
      for (let i = 0; i < arr.length; i++) {
        const ch = arr[i];
        accEm += charEmWidth(ch);
        if (accEm < minCutEm) continue;
        if (QUOTE_CARD_STOP_RE.test(ch) && i < arr.length - 1) bestStop = i + 1;
        else if (QUOTE_CARD_SOFT_RE.test(ch) && i < arr.length - 1) bestSoft = i;
      }
      const cut = bestStop > 0 ? bestStop : bestSoft > 0 ? bestSoft : -1;
      if (cut > 0) {
        last = arr.slice(0, cut).join('');
      } else if (/[A-Za-z0-9]$/.test(last)) {
        // Avoid chopping an ASCII word in half when a space exists nearby
        const sp = last.lastIndexOf(' ');
        if (sp > 0 && measureEm(last.slice(0, sp)) >= minCutEm) last = last.slice(0, sp);
      }
    }
    last = last.replace(QUOTE_CARD_TRAIL_WEAK_RE, '').replace(/…+$/, '');
    lines[limit - 1] = `${last}…`;
    return { lines, text: lines.join('\n'), truncated: true };
  }, 256);
}

const QUOTE_HEADER_RE = /^>\s*\[↩\s*([^\]\n]*)\]\(quote:([^)\s\n]*)\)\s*$/;
const QUOTE_ANSWER_PREFIX_RE = /^(【[^】\n]+】)\r?\n([\s\S]*)$/;
const QUOTE_LABEL_SCOPE_RE = /\s·\s(?:¶\d*|excerpt)$/;

function encodeQuoteTarget(key, scope = 'message', range = null) {
  const base = encodeURIComponent(String(key ?? '')).replace(/\(/g, '%28').replace(/\)/g, '%29');
  if (scope === 'message' && !range) return base;
  const parts = [];
  if (scope && scope !== 'message') parts.push(`scope=${scope}`);
  if (range && Number.isInteger(range.paragraph) && range.paragraph >= 0) parts.push(`p=${range.paragraph}`);
  if (range && Number.isInteger(range.start) && Number.isInteger(range.end) && range.end >= range.start) {
    parts.push(`r=${range.start}-${range.end}`);
  }
  return parts.length ? `${base}#${parts.join('&')}` : base;
}

function decodeQuoteTarget(raw) {
  const str = String(raw ?? '');
  const hash = str.indexOf('#');
  const encodedKey = hash >= 0 ? str.slice(0, hash) : str;
  const fragment = hash >= 0 ? str.slice(hash + 1) : '';
  let targetKey = encodedKey;
  try { targetKey = decodeURIComponent(encodedKey); } catch (_) { /* keep encoded */ }
  let scope = '';
  let paragraph;
  let start;
  let end;
  if (fragment) {
    for (const part of fragment.split('&')) {
      const eq = part.indexOf('=');
      if (eq < 0) continue;
      const k = part.slice(0, eq);
      const v = part.slice(eq + 1);
      if (k === 'scope' && QUOTE_SCOPES.includes(v)) scope = v;
      else if (k === 'p' && /^\d+$/.test(v)) paragraph = Number(v);
      else if (k === 'r') {
        const m = /^(\d+)-(\d+)$/.exec(v);
        if (m) { start = Number(m[1]); end = Number(m[2]); }
      }
    }
  }
  const range = normalizeQuoteRange({
    ...(start !== undefined ? { start, end } : {}),
    ...(paragraph !== undefined ? { paragraph } : {}),
  });
  return { targetKey, scope, range };
}

function sanitizeQuoteLabel(label) {
  return String(label ?? '').replace(/[\[\]\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();
}

export function formatQuotedMessage(quotes, text = '', { to = '' } = {}) {
  const list = normalizeQuotes(quotes);
  const body = String(text ?? '').replace(/\r\n?/g, '\n').trim();
  if (!list.length) return to ? answerText(to, body) : body;
  const serialized = list.map(q => {
    const scope = quoteScope(q);
    const baseLabel = q.author && q.time ? `${q.author} · ${q.time}` : (q.author || q.time || 'Message');
    const scopeTag = scope === 'paragraph'
      ? (Number.isInteger(q.range?.paragraph) ? `¶${q.range.paragraph + 1}` : '¶')
      : scope === 'selection' ? 'excerpt' : '';
    const label = sanitizeQuoteLabel(scopeTag ? `${baseLabel} · ${scopeTag}` : baseLabel);
    const header = `> [↩ ${label}](quote:${encodeQuoteTarget(q.targetKey || q.id, scope, q.range)})`;
    const bodyLines = q.text.split('\n').map(line => (line ? `> ${line}` : '>'));
    return [header, ...bodyLines].join('\n');
  }).join('\n\n');
  const combined = body ? `${serialized}\n\n${body}` : serialized;
  return to ? `${answerText(to, '')}\n${combined}` : combined;
}

export function splitQuotedMessage(raw) {
  let str = String(raw ?? '').replace(/\r\n?/g, '\n').trim();
  if (!str) return { quotes: [], text: '' };
  if (!str.includes('(quote:')) return { quotes: [], text: str };
  let answerPrefix = '';
  const ansMatch = QUOTE_ANSWER_PREFIX_RE.exec(str);
  if (ansMatch) {
    const firstRestLine = ansMatch[2].split('\n')[0] || '';
    if (QUOTE_HEADER_RE.test(firstRestLine)) {
      answerPrefix = ansMatch[1];
      str = ansMatch[2];
    }
  }
  const lines = str.split('\n');
  const quotes = [];
  let i = 0;
  while (i < lines.length) {
    while (i < lines.length && !lines[i].trim()) i++;
    if (i >= lines.length) break;
    const hdr = QUOTE_HEADER_RE.exec(lines[i]);
    if (!hdr) break;
    i++;
    const rawLabel = hdr[1].trim();
    const { targetKey, scope: uriScope, range } = decodeQuoteTarget(hdr[2]);
    let scope = uriScope;
    let label = rawLabel;
    const labelSuffix = QUOTE_LABEL_SCOPE_RE.exec(label);
    if (labelSuffix) {
      if (!scope) scope = labelSuffix[0].includes('¶') ? 'paragraph' : 'selection';
      label = label.slice(0, labelSuffix.index).trim();
    }
    const sep = label.lastIndexOf(' · ');
    const author = sep >= 0 ? label.slice(0, sep).trim() : label;
    const time = sep >= 0 ? label.slice(sep + 3).trim() : '';
    const qLines = [];
    while (i < lines.length && lines[i].startsWith('>')) {
      qLines.push(lines[i].replace(/^>[ \t]?/, ''));
      i++;
    }
    const qText = qLines.join('\n').trim();
    if (!qText) break;
    const resolvedScope = scope || 'message';
    quotes.push({
      id: `${targetKey || 'msg'}#${quotes.length}#${qText.slice(0, 24)}`,
      targetKey,
      kind: '',
      author,
      at: '',
      time,
      text: qText,
      scope: resolvedScope,
      ...(resolvedScope === 'selection' ? { exact: true } : {}),
      ...(range ? { range } : {}),
    });
  }
  if (!quotes.length) return { quotes: [], text: String(raw ?? '').trim() };
  const rest = lines.slice(i).join('\n').trim();
  const finalText = answerPrefix ? (rest ? `${answerPrefix}${rest}` : answerPrefix) : rest;
  return { quotes, text: finalText };
}

// Explicit seam for when Herdr's TextView gains native `on_selection_change({ text, bounds, range? })`:
// normalizing the payload here plugs directly into `PmProject.onTextSelection` + `selectionPopover`.
export function selectionToolbarState(selection, source) {
  const text = String(selection?.text ?? '').replace(/\r\n?/g, '\n').trim();
  const key = String(source?.key ?? '').trim();
  if (!text || !key) return null;
  const b = selection?.bounds;
  const bounds = b && Number.isFinite(b.x) && Number.isFinite(b.y)
    ? { x: b.x, y: b.y, width: Number(b.width) || 0, height: Number(b.height) || 0 }
    : null;
  const range = normalizeQuoteRange(selection?.range);
  return {
    text,
    bounds,
    ...(range ? { range } : {}),
    source: {
      key,
      kind: String(source?.kind || 'pm'),
      author: String(source?.author || ''),
      at: String(source?.at || ''),
      time: String(source?.time || ''),
    },
  };
}

// ---- Two-layer prompt-driven task plan (`task.plan` + `task.subplan`) ----------------------

export function inferStepAnchor(text) {
  const raw = String(text || '').trim();
  if (!raw) return 'custom';
  const tags = raw.match(/(?:^|\s)@(work|review|merge|custom|none)(?=\s|$)/gi);
  if (tags) {
    const k = tags[tags.length - 1].trim().slice(1).toLowerCase();
    return k === 'none' ? 'custom' : k;
  }
  const negReviewRe = /(?:免|不|无需|不用|不做|跳过|无)(?:代码)?(?:审查|评审|复审|review)|\b(?:no|without|skip(?:ping)?)\s+(?:code\s+)?reviews?\b/i;
  const userSignoffRe = /(?:等你|用户|待你)(?:审查|审阅|确认|验收)|(?:和|与|给)用户|\b(?:your|user|human)\s+(?:review|sign-?off|approval|check)\b|\bwith\s+(?:the\s+)?(?:user|you|human)\b/i;
  const reviewHeadRe = /^\s*(?:(?:独立\s*)?(?:代码\s*)?(?:审查|复审|评审)|送审|(?:independent\s+)?(?:code\s+)?(?:re-?)?review(?:ing)?(?![a-z]))/i;
  const negMergeRe = /(?:不|无需|不用|暂不|先不|免)(?:合入|合并|合进|合到|合\s*(?:main|master|主分支|主线)|land)|\b(?:no|without|don'?t|do\s+not|not|skip(?:ping)?)\s+(?:code\s+)?(?:merge|land)(?:ing)?\b/gi;
  const mergeAnchorRe = /合进|合入|合到|合\s*(?:main|master|主分支|主线)|合并(?:进|入|到|\s*(?:main|master|主分支|主线|分支)|$)|(?:^|[^a-z])(?:pm\.py\s+)?land(?:\s+(?:to|into|on|in|branch|main|master)\b|\s*$)|(?:^|[^a-z])merge(?:\s+(?:to|into|with|branch|main|master|pr)\b|\s*$)/i;
  const coreWorkRe = /实现|开发|编码|修复|重构|调研|设计|翻译|\b(?:implement\w*|develop\w*|refactor\w*|research\w*|design\w*|translat\w*)\b/i;
  const customPostRe = /安装|装到|部署|发布|挂分支|待验收|等你|审阅|\b(?:install\w*|deploy\w*|release\w*|hold\w*|await\w*|sign-?off)\b/i;
  const workAnchorRe = /实现|开发|编写|编码|修复|改造|重构|调研|设计|出稿|交互稿|翻译|译为|修改|改动|调整|补充|补齐|盘点|迁移|优化|执行任务|\b(?:implement\w*|develop\w*|build\w*|code|coding|fix\w*|refactor\w*|research\w*|design\w*|translat\w*|modif\w*|updat\w*|migrat\w*|optimi[sz]\w*|patch\w*|writ(?:e|ing)|draft\w*)\b/i;

  const reviewMatch = reviewHeadRe.exec(raw);
  if (reviewMatch && !negReviewRe.test(raw) && !userSignoffRe.test(raw)) {
    const tail = raw.slice(reviewMatch[0].length);
    if (!workAnchorRe.test(tail) && !mergeAnchorRe.test(tail.replace(negMergeRe, ' '))) return 'review';
  }
  const mergeClean = raw.replace(negMergeRe, ' ');
  if (mergeAnchorRe.test(mergeClean)) return 'merge';
  if (customPostRe.test(raw) && !coreWorkRe.test(raw)) return 'custom';
  if (workAnchorRe.test(raw)) return 'work';
  return 'custom';
}

export function parsePlanItems(raw) {
  if (!raw) return [];
  let items;
  if (typeof raw === 'string') {
    items = raw.split(/[\n;；]/).map(s => s.trim()).filter(Boolean);
  } else if (Array.isArray(raw)) {
    items = raw;
  } else if (typeof raw === 'object') {
    items = Array.isArray(raw.steps) ? raw.steps : Array.isArray(raw.items) ? raw.items : [];
  } else {
    return [];
  }
  const normState = (v, doneFlag) => {
    if (doneFlag === true) return 'done';
    const s = String(v || '').trim().toLowerCase();
    if (['done', 'completed', 'checked', 'x'].includes(s)) return 'done';
    if (['doing', 'in_progress', 'active', 'running', 'working', '>'].includes(s)) return 'doing';
    if (['todo', 'pending', 'open'].includes(s)) return 'todo';
    return '';
  };
  const normAnchor = v => {
    const s = String(v || '').trim().toLowerCase().replace(/^@/, '');
    if (['work', 'impl', 'execute', 'exec'].includes(s)) return 'work';
    if (s === 'review') return 'review';
    if (['merge', 'land'].includes(s)) return 'merge';
    if (s === 'custom' || s === 'none') return 'custom';
    return '';
  };
  const out = [];
  for (const item of items) {
    if (item == null) continue;
    let isObject = false;
    let text = '';
    let state = '';
    let explicitState = false;
    let explicitAnchor = '';
    let right = '';
    let at = '';
    let commit = '';
    let round = 0;
    if (typeof item === 'string') {
      text = item.trim().replace(/^(?:[-*+]|\d+[.)])\s+/, '');
    } else if (typeof item === 'object' && !Array.isArray(item)) {
      isObject = true;
      text = String(item.text ?? item.title ?? item.label ?? item.name ?? '').trim();
      const st = normState(item.state ?? item.status, item.done);
      if (st) { state = st; explicitState = true; }
      explicitAnchor = normAnchor(item.anchor ?? item.role ?? item.kind ?? item.tag);
      right = String(item.right || '');
      at = String(item.at || '');
      commit = String(item.commit || '');
      if (Number.isFinite(Number(item.round)) && Number(item.round) > 0) round = Math.floor(Number(item.round));
    } else {
      continue;
    }
    const prefix = /^\s*(?:\[([^\]]*)\]|([✓✔◌○]))\s*(.*)$/.exec(text);
    if (prefix) {
      const mark = (prefix[1] != null ? prefix[1] : prefix[2]).trim().toLowerCase();
      if (!explicitState) {
        if (['x', '✓', '✔'].includes(mark)) { state = 'done'; explicitState = true; }
        else if (['>', '*', '~', '◌'].includes(mark)) { state = 'doing'; explicitState = true; }
        else if (mark === '' || mark === '○') { state = 'todo'; explicitState = true; }
      }
      text = prefix[3].trim();
    }
    const tagRe = /(?:^|\s)@(work|review|merge|custom|none)(?=\s|$)/gi;
    let foundTag = '';
    text = text.replace(tagRe, (_, k) => { foundTag = k.toLowerCase(); return ' '; }).replace(/\s+/g, ' ').trim();
    if (!explicitAnchor && foundTag) explicitAnchor = normAnchor(foundTag);
    if (!text && foundTag) {
      text = { work: 'Work', review: 'Review', merge: 'Merge', custom: 'Step' }[foundTag] || '';
    }
    if (!text) continue;
    out.push({
      text,
      state: state || 'todo',
      explicitState,
      anchor: explicitAnchor || (isObject ? 'custom' : inferStepAnchor(text)),
      explicitAnchor: Boolean(explicitAnchor),
      right,
      at,
      commit,
      round,
    });
  }
  return out;
}

export function taskSteps(task, { lang = 'en' } = {}) {
  const summarizeStep = raw => {
    const src = String(raw || '').trim();
    const notes = [];
    const stripped = src.replace(/（([^）]*)）|\(([^)]*)\)/g, (_, zhNote, enNote) => {
      const n = String(zhNote ?? enNote ?? '').trim();
      if (n) notes.push(n);
      return '';
    });
    const core = stripped.replace(/\s+/g, ' ').trim() || src;
    let units = 0;
    let cut = '';
    let clipped = false;
    for (const ch of core) {
      const w = ch.codePointAt(0) > 255 ? 2 : 1;
      if (units + w > STEP_LABEL_UNITS) { clipped = true; break; }
      cut += ch;
      units += w;
    }
    const shortText = clipped ? `${cut.trimEnd()}…` : core;
    const note = notes.join(' · ');
    const tip = shortText !== src ? src : '';
    return { shortText, note, tip };
  };
  const outer = parsePlanItems(task?.plan);
  const sub = parsePlanItems(task?.subplan);
  const status = String(task?.status || '');
  const rawRounds = Math.max(0, Number(task?.rounds) || 0, Array.isArray(task?.review_history) ? task.review_history.length : 0);
  const hasPlan = outer.length > 0;
  const hasSubplan = sub.length > 0;
  const substeps = sub.map((s, index) => ({ index, text: s.text, ...summarizeStep(s.text), state: s.state }));

  let steps;
  if (!hasPlan) {
    const hadReview = status === 'review' || Boolean(task?.review) || rawRounds > 0 ||
      (Array.isArray(task?.log) && task.log.some(e => /\bstatus=review\b/.test(String(e?.text || ''))));
    const templates = hadReview
      ? [
          { text: word(lang, 'planFallbackWork'), anchor: 'work' },
          { text: word(lang, 'planFallbackReview'), anchor: 'review' },
          { text: word(lang, 'planFallbackDone'), anchor: 'custom' },
        ]
      : [
          { text: word(lang, 'planFallbackWork'), anchor: 'work' },
          { text: word(lang, 'planFallbackDone'), anchor: 'custom' },
        ];
    const doneReview = Boolean(task?.review && ['done', 'merged', 'released'].includes(task.review.status));
    steps = templates.map((tpl, index) => {
      let state = 'todo';
      if (['done', 'released', 'merged'].includes(status)) {
        state = 'done';
      } else if (['abandoned', 'cancelled', 'proposed'].includes(status)) {
        state = 'todo';
      } else if (status === 'review') {
        state = tpl.anchor === 'work' ? 'done' : tpl.anchor === 'review' ? 'doing' : 'todo';
      } else if (status === 'paused') {
        if (hadReview && doneReview) state = tpl.anchor === 'work' || tpl.anchor === 'review' ? 'done' : 'todo';
        else state = tpl.anchor === 'work' ? 'doing' : 'todo';
      } else {
        state = tpl.anchor === 'work' ? 'doing' : 'todo';
      }
      return {
        index,
        text: tpl.text,
        ...summarizeStep(tpl.text),
        state,
        anchor: tpl.anchor,
        right: '',
        at: '',
        commit: '',
        round: 0,
        substeps: null,
        subProgress: null,
      };
    });
    if (['done', 'released', 'merged', 'review'].includes(status)) {
      for (const s of substeps) if (s.state === 'doing') s.state = 'done';
    } else if (['abandoned', 'cancelled', 'proposed'].includes(status)) {
      for (const s of substeps) if (s.state === 'doing') s.state = 'todo';
    }
  } else {
    steps = outer.map((item, index) => ({
      index,
      text: item.text,
      ...summarizeStep(item.text),
      state: item.state,
      anchor: item.anchor,
      right: item.right,
      at: item.at,
      commit: item.commit,
      round: item.round,
      substeps: null,
      subProgress: null,
    }));
    const closeDoingSub = () => {
      for (const s of substeps) if (s.state === 'doing') s.state = 'done';
    };
    if (['done', 'released'].includes(status)) {
      for (const s of steps) s.state = 'done';
      closeDoingSub();
    } else if (['abandoned', 'cancelled'].includes(status)) {
      for (const s of steps) if (s.state === 'doing') s.state = 'todo';
      for (const s of substeps) if (s.state === 'doing') s.state = 'todo';
    } else if (status === 'proposed') {
      for (const s of steps) if (s.state === 'doing') s.state = 'todo';
      for (const s of substeps) if (s.state === 'doing') s.state = 'todo';
    } else if (status === 'paused') {
      // Preserve recorded step states while paused.
    } else if (status === 'merged' || (status === 'in_progress' && Boolean(task?.landed || task?.merged_at))) {
      closeDoingSub();
      let mi = -1;
      for (let i = steps.length - 1; i >= 0; i--) if (steps[i].anchor === 'merge') { mi = i; break; }
      if (mi >= 0) {
        for (let i = 0; i <= mi; i++) steps[i].state = 'done';
        const nextIdx = steps.findIndex((s, i) => i > mi && s.state !== 'done');
        for (let i = mi + 1; i < steps.length; i++) {
          if (i === nextIdx) steps[i].state = 'doing';
          else if (steps[i].state === 'doing') steps[i].state = 'todo';
        }
      } else if (status === 'merged') {
        for (const s of steps) s.state = 'done';
      }
    } else if (status === 'review') {
      closeDoingSub();
      let ri = steps.findIndex(s => s.anchor === 'review' && s.state !== 'done');
      if (ri < 0) {
        for (let i = steps.length - 1; i >= 0; i--) if (steps[i].anchor === 'review') { ri = i; break; }
      }
      if (ri >= 0) {
        for (let i = 0; i < ri; i++) steps[i].state = 'done';
        steps[ri].state = 'doing';
        for (let i = ri + 1; i < steps.length; i++) if (steps[i].state === 'doing') steps[i].state = 'todo';
      } else {
        let wi = steps.findIndex(s => s.state === 'doing');
        if (wi < 0) wi = steps.findIndex(s => s.anchor === 'work' && s.state !== 'done');
        if (wi < 0) {
          for (let i = steps.length - 1; i >= 0; i--) if (steps[i].anchor === 'work') { wi = i; break; }
        }
        if (wi >= 0 && wi < steps.length - 1) {
          for (let i = 0; i <= wi; i++) steps[i].state = 'done';
          const nextIdx = steps.findIndex((s, i) => i > wi && s.state !== 'done');
          for (let i = wi + 1; i < steps.length; i++) {
            if (i === nextIdx) steps[i].state = 'doing';
            else if (steps[i].state === 'doing') steps[i].state = 'todo';
          }
        } else if (wi >= 0) {
          for (let i = 0; i < wi; i++) steps[i].state = 'done';
          steps[wi].state = 'doing';
        }
      }
    } else {
      // in_progress or blocked
      let di = steps.findIndex(s => s.state === 'doing');
      const unansweredBlocked = status === 'blocked' && !task?.answered;
      const reviewLive = Boolean(task?.review && !['done', 'merged', 'released', 'abandoned', 'cancelled', 'paused', 'proposed'].includes(task.review.status));
      if (di >= 0 && steps[di].anchor === 'review' && !reviewLive) {
        steps[di].state = 'todo';
        let wi = -1;
        for (let i = di - 1; i >= 0; i--) if (steps[i].anchor === 'work') { wi = i; break; }
        if (wi < 0 && di > 0) wi = 0;
        if (wi >= 0 && !(unansweredBlocked && steps[wi].state === 'done')) {
          steps[wi].state = 'doing';
          di = wi;
        } else {
          di = -1;
        }
      }
      if (di < 0) {
        let mergeDone = -1;
        for (let i = steps.length - 1; i >= 0; i--) {
          if (steps[i].anchor === 'merge' && steps[i].state === 'done') { mergeDone = i; break; }
        }
        if (mergeDone >= 0) {
          const next = steps.findIndex((s, i) => i > mergeDone && s.state === 'todo');
          if (next >= 0 && !(unansweredBlocked && steps[next].anchor === 'review' && !reviewLive)) {
            steps[next].state = 'doing';
          }
        } else {
          const workTodo = steps.findIndex(s => s.anchor === 'work' && s.state === 'todo');
          const anyTodo = steps.findIndex(s => s.state === 'todo');
          const pick = workTodo >= 0 ? workTodo : anyTodo;
          if (pick >= 0 && !(unansweredBlocked && steps[pick].anchor === 'review' && !reviewLive)) {
            steps[pick].state = 'doing';
          }
        }
      }
    }
  }

  const isOpenActive = !['done', 'merged', 'released', 'abandoned', 'cancelled', 'paused', 'proposed'].includes(status) &&
    !(status === 'blocked' && !task?.answered);
  const activeIndex = steps.findIndex(s => s.state === 'doing');
  const active = activeIndex >= 0 ? steps[activeIndex] : null;
  const hasPriorDoneMerge = activeIndex > 0 && steps.slice(0, activeIndex).some(s => s.anchor === 'merge' && s.state === 'done');
  const hasPriorDoneReviewNoMoreGates = activeIndex > 0 &&
    steps.slice(0, activeIndex).some(s => s.anchor === 'review' && s.state === 'done') &&
    !steps.slice(activeIndex).some(s => s.anchor === 'work' || s.anchor === 'review' || s.anchor === 'merge');
  const postGate = Boolean(hasPlan && isOpenActive && active && active.anchor === 'custom' &&
    (hasPriorDoneMerge || hasPriorDoneReviewNoMoreGates));

  const reviewOpen = status === 'review' ||
    Boolean(task?.review && !['done', 'merged', 'released', 'abandoned', 'cancelled', 'paused', 'proposed'].includes(task.review.status));
  const pastReview = postGate || steps.some(s => s.anchor === 'merge' && s.state === 'done') ||
    (steps.some(s => s.anchor === 'review' && s.state === 'done') && !steps.some(s => s.anchor === 'review' && s.state !== 'done'));
  let round = 0;
  let foldedRounds = 0;
  if (reviewOpen) {
    round = Math.max(1, rawRounds);
    foldedRounds = round > 1 ? round - 1 : 0;
  } else if (['in_progress', 'blocked'].includes(status) && !pastReview && rawRounds >= 1) {
    round = rawRounds + 1;
    foldedRounds = rawRounds;
  } else {
    round = 0;
    foldedRounds = rawRounds > 1 ? rawRounds - 1 : 0;
  }
  const foldedLabel = foldedRounds > 0 ? word(lang, 'planFoldedRounds', foldedRounds) : '';
  if (active && round > 1 && (active.anchor === 'review' || active.anchor === 'work')) {
    active.round = round;
  }

  let attachedSubsteps = [];
  if (hasSubplan && steps.length) {
    let attachIdx = -1;
    if (active && active.anchor === 'work') attachIdx = activeIndex;
    else if (active && active.anchor !== 'review' && active.anchor !== 'merge' && !postGate && !steps.some(s => s.anchor === 'work')) {
      attachIdx = activeIndex;
    } else {
      const bound = activeIndex >= 0 ? activeIndex : steps.length;
      for (let i = bound - 1; i >= 0; i--) if (steps[i].anchor === 'work' && steps[i].state === 'done') { attachIdx = i; break; }
      if (attachIdx < 0) for (let i = steps.length - 1; i >= 0; i--) if (steps[i].anchor === 'work' && steps[i].state === 'done') { attachIdx = i; break; }
      if (attachIdx < 0) for (let i = bound - 1; i >= 0; i--) if (steps[i].state === 'done') { attachIdx = i; break; }
      if (attachIdx < 0) attachIdx = steps.findIndex(s => s.anchor === 'work');
      if (attachIdx < 0) attachIdx = 0;
    }
    const subDone = substeps.filter(s => s.state === 'done').length;
    steps[attachIdx].substeps = substeps;
    steps[attachIdx].subProgress = { done: subDone, total: substeps.length };
    attachedSubsteps = substeps;
  }

  const done = steps.filter(s => s.state === 'done').length;
  const total = steps.length;
  const progress = total ? `${done}/${total}` : '';
  const pill = !hasPlan ? '' : postGate && active ? word(lang, 'planPostStep', done, total, active.shortText) : progress;
  const activeSubstep = attachedSubsteps.find(s => s.state === 'doing') || null;
  const noReview = Boolean(task?.no_review) || (hasPlan && !steps.some(s => s.anchor === 'review'));
  const autoReview = !noReview && task?.auto_review !== false && hasPlan && steps.some(s => s.anchor === 'review');
  const rail = [
    ...(foldedRounds > 0 ? [{ kind: 'folded', state: 'done', text: foldedLabel }] : []),
    ...steps.map(s => ({ kind: 'step', state: s.state, text: s.shortText, anchor: s.anchor, round: s.round })),
  ];
  return {
    hasPlan,
    hasSubplan,
    done,
    total,
    progress,
    pill,
    postGate,
    activeIndex,
    activeStep: active,
    activeSubstep,
    round,
    foldedRounds,
    foldedLabel,
    noReview,
    autoReview,
    paused: status === 'paused',
    steps,
    rail,
  };
}

export function isPostGateTask(task) {
  if (!task?.plan) return false;
  return taskSteps(task).postGate;
}

export function taskDependencies(task, allTasks = [], { terms = [], live = [] } = {}) {
  const rawList = Array.isArray(task?.deps) && task.deps.length
    ? task.deps
    : (Array.isArray(task?.depends_on) ? task.depends_on.map(id => ({ id })) : []);
  if (!rawList.length) return null;
  const list = Array.isArray(allTasks) ? allTasks : [];
  const taskMachine = task?.machine || '';
  const findTarget = depId => {
    const namespaced = taskMachine ? `${taskMachine}/${depId}` : depId;
    return list.find(t => t && (t.id === depId || t.id === namespaced ||
      ((t.machine || '') === taskMachine && t.sourceId === depId))) || null;
  };
  const items = [];
  for (const raw of rawList) {
    const depId = typeof raw === 'string' ? raw.trim() : String(raw?.id || '').trim();
    if (!depId) continue;
    const entry = typeof raw === 'object' && raw ? raw : { id: depId };
    const target = findTarget(depId);
    const status = String(target?.status || entry.status || 'missing');
    let state;
    if (target) {
      if (['merged', 'done', 'released'].includes(status) || Boolean(target.landed)) state = 'met';
      else if (['abandoned', 'cancelled'].includes(status)) state = 'abandoned';
      else state = 'waiting';
    } else if (['met', 'waiting', 'abandoned', 'missing'].includes(entry.state)) {
      state = entry.state;
    } else {
      state = 'missing';
    }
    const isMet = state === 'met';
    const isBroken = state === 'abandoned' || state === 'missing';
    const isReview = !isMet && !isBroken && status === 'review';
    const isReviewWorking = isReview && target ? reviewWorking(target, terms, live) : false;
    const isBlocked = !isMet && !isBroken && status === 'blocked' && !target?.answered;
    const isWorking = !isMet && !isBroken && !target?.offline &&
      (status === 'in_progress' || (status === 'blocked' && Boolean(target?.answered)));
    const depNum = taskNumber(target) || taskNumber(entry);
    items.push({
      id: depId,
      ...(depNum ? { number: depNum } : {}),
      targetId: target?.id || (taskMachine ? `${taskMachine}/${depId}` : depId),
      sourceId: target?.sourceId || depId,
      pm: target?.pm || task?.pm || '',
      sourcePm: target?.sourcePm || task?.sourcePm || '',
      machine: target?.machine ?? taskMachine,
      title: String(target?.title || entry.title || depId),
      state,
      status,
      isMet,
      isBroken,
      isReview,
      isReviewWorking,
      isBlocked,
      isWorking,
      clickable: state !== 'missing',
    });
  }
  if (!items.length) return null;
  const metCount = items.filter(i => i.isMet).length;
  const total = items.length;
  const allMet = metCount === total;
  const ready = Boolean(task?.status === 'proposed' && allMet);
  return {
    hasDeps: true,
    showAsWaiting: task?.status === 'proposed',
    items,
    metCount,
    total,
    progress: `${metCount}/${total}`,
    allMet,
    ready,
    broken: items.some(i => i.isBroken),
  };
}

// Short dependency reference (`#338` whenever numbered; otherwise concise title/id, never a sprawling slug).
export function formatDepRef(item, resolveNumber = null) {
  if (!item || typeof item !== 'object') return '';
  const direct = formatTaskNumber(taskNumber(item));
  if (direct) return direct;
  if (typeof resolveNumber === 'function') {
    const resolved = formatTaskNumber(resolveNumber(item.targetId) || resolveNumber(item.id) || resolveNumber(item.sourceId));
    if (resolved) return resolved;
  }
  const title = String(item.title || '').trim();
  if (title && title !== item.id && title !== item.sourceId) {
    return title.length > 14 ? `${title.slice(0, 13)}…` : title;
  }
  const id = String(item.id || '').trim();
  return id.length > 14 ? `${id.slice(0, 13)}…` : id;
}

// ---- Thread sub-agents (`worker`, `review`, `helpers`) & default small-window mode --------

export const AGENT_NAMES = [
  'Milo', 'Nora', 'Kira', 'Leo', 'Maya', 'Owen', 'Iris', 'Rex',
  'Ada', 'Toby', 'Zoe', 'Finn', 'Sage', 'Nova', 'Ezra', 'Luna',
  'Jude', 'Cleo', 'Otto', 'Vera', 'Theo', 'Nyx', 'Gale', 'Wren',
];

function hashAgentSeed(seed) {
  const s = String(seed || '');
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

// Deterministic friendly short name per agent instance; when `usedNames` (a Set) is given,
// linearly probes the pool so agents under the same task never share a name.
export function agentDisplayName(seed, usedNames = null) {
  const baseIdx = hashAgentSeed(seed) % AGENT_NAMES.length;
  const used = usedNames instanceof Set ? usedNames : null;
  if (!used) return AGENT_NAMES[baseIdx];
  for (let step = 0; step < AGENT_NAMES.length; step++) {
    const cand = AGENT_NAMES[(baseIdx + step) % AGENT_NAMES.length];
    if (!used.has(cand)) {
      used.add(cand);
      return cand;
    }
  }
  let suffix = 2;
  while (used.has(`${AGENT_NAMES[baseIdx]} ${suffix}`)) suffix++;
  const fallback = `${AGENT_NAMES[baseIdx]} ${suffix}`;
  used.add(fallback);
  return fallback;
}

export const AGENT_ACTIONS = {
  code: { zh: '编码', en: { doing: 'Coding', done: 'Coded', base: 'Code' } },
  review: { zh: '审查', en: { doing: 'Reviewing', done: 'Reviewed', base: 'Review' } },
  merge: { zh: '合入', en: { doing: 'Merging', done: 'Merged', base: 'Merge' } },
  triage: { zh: '排查', en: { doing: 'Triaging', done: 'Triaged', base: 'Triage' } },
  probe: { zh: '调研', en: { doing: 'Probing', done: 'Probed', base: 'Probe' } },
  design: { zh: '设计', en: { doing: 'Designing', done: 'Designed', base: 'Design' } },
  install: { zh: '安装', en: { doing: 'Installing', done: 'Installed', base: 'Install' } },
  cleanup: { zh: '清理', en: { doing: 'Cleaning', done: 'Cleaned', base: 'Cleanup' } },
  test: { zh: '测试', en: { doing: 'Testing', done: 'Tested', base: 'Test' } },
  fix: { zh: '修复', en: { doing: 'Fixing', done: 'Fixed', base: 'Fix' } },
  docs: { zh: '文档', en: { doing: 'Documenting', done: 'Documented', base: 'Docs' } },
};

const ACTION_RULES = [
  ['review', /(?:^|[\s/:_-])(?:review|reviewer|audit|code[\s-]*review)(?:$|[\s/:_-])|审查|评审|复审/i],
  ['merge', /(?:^|[\s/:_-])(?:merge|merging|land|landing|cherry-pick)(?:$|[\s/:_-])|合入|合并|并入/i],
  ['triage', /(?:^|[\s/:_-])(?:triage|diagnos\w*|debug\w*|troubleshoot\w*)(?:$|[\s/:_-])|排查|诊断|定位根因|根因/i],
  ['install', /(?:^|[\s/:_-])(?:install\w*|deploy\w*|release\w*|publish\w*|upgrade\w*)(?:$|[\s/:_-])|安装|部署|发版|升级/i],
  ['cleanup', /(?:^|[\s/:_-])(?:cleanup|clean[\s-]*up|clean|prune|retire|gc|remove[\s-]*old)(?:$|[\s/:_-])|清理|回收|删旧/i],
  ['probe', /(?:^|[\s/:_-])(?:probe|research\w*|survey|investigat\w*|explor\w*|inspect\w*|scan\w*)(?:$|[\s/:_-])|调研|探查|查\s*mod|摸底|考察/i],
  ['design', /(?:^|[\s/:_-])(?:design\w*|mock\w*|mockup|wireframe|spec|architect\w*|prototype|comparison)(?:$|[\s/:_-])|设计|对比图|原型|草图|方案对比/i],
  ['test', /(?:^|[\s/:_-])(?:smoke|e2e|benchmark|verify|verif\w*|unittest|test(?:s|ing)?)(?:$|[\s/:_-])|冒烟|验证|单测|测试/i],
  ['docs', /(?:^|[\s/:_-])(?:docs?|readme|changelog|guide|manual)(?:$|[\s/:_-])|文档|手册|说明文档/i],
  ['fix', /(?:^|[\s/:_-])(?:fix|bugfix|hotfix|patch|repair)(?:$|[\s/:_-])|修复|修正|解决.*bug/i],
  ['code', /(?:^|[\s/:_-])(?:code|coding|impl\w*|build\w*|scaffold\w*|refactor\w*|feat)(?:$|[\s/:_-])|编码|实现|开发|重构/i],
];

function classifyActionText(text, { preferCodeOverTest = false, skipReview = false } = {}) {
  const raw = String(text || '').trim();
  if (!raw) return '';
  const hasCode = preferCodeOverTest && /(?:实现|开发|重构|新增|支持|内联|\bfeat\b|\bimpl\w*|\bbuild\w*)/i.test(raw);
  for (const [key, re] of ACTION_RULES) {
    if (skipReview && key === 'review') continue;
    if (key === 'test' && hasCode) continue;
    if (re.test(raw)) return key;
  }
  return '';
}

function activePlanStepText(task) {
  const cur = parsePlanItems(task?.subplan).find(item => item.state === 'doing');
  return cur ? String(cur.text || '').trim() : '';
}

// Infer a concise action key (`code`, `review`, `merge`, `triage`, `probe`, `design`, `install`, `cleanup`, `test`, `fix`, `docs`)
// from the agent's role, helper purpose/name, active plan/subplan step, or task metadata.
export function inferAgentAction({ role = 'worker', purpose = '', helperName = '', helperPrompt = '', task = null } = {}) {
  if (role === 'review') return 'review';
  if (role === 'helper') {
    if (purpose === 'land') return 'merge';
    if (purpose === 'triage') return 'triage';
    return classifyActionText(helperName) || classifyActionText(helperPrompt) || 'probe';
  }
  const stepText = activePlanStepText(task);
  const fromStep = classifyActionText(stepText);
  if (fromStep) return fromStep;
  const titleText = [task?.title, task?.branch, task?.id].filter(Boolean).join(' ');
  const fromTask = classifyActionText(titleText, { preferCodeOverTest: true, skipReview: true });
  return fromTask || 'code';
}

// English verb tense by agent state:
// - working / running -> present participle ('doing': Coding / Reviewing / Merging …)
// - done / merged -> past participle ('done': Coded / Reviewed / Merged …)
// - idle / blocked / paused / queued / other -> base form ('base': Code / Review / Merge …)
export function agentActionTense(status, { ended = false, taskStatus = '' } = {}) {
  const s = String(status || '').trim().toLowerCase();
  const ts = String(taskStatus || '').trim().toLowerCase();
  if (!ended && (s === 'working' || s === 'running')) return 'doing';
  if (s === 'done' || s === 'merged') return 'done';
  if (ended && (ts === 'done' || ts === 'merged')) return 'done';
  return 'base';
}

export function agentActionLabel(lang, action, status = '', opts = {}) {
  const entry = AGENT_ACTIONS[action] || AGENT_ACTIONS.code;
  if (lang === 'zh') return entry.zh;
  const tense = agentActionTense(status, opts);
  return entry.en[tense] || entry.en.base;
}

export function agentDefaultMode(agent) {
  const role = agent?.role || 'worker';
  const kind = String(agent?.kind || '').toLowerCase();
  const ended = Boolean(agent?.ended);
  const hasTerm = Boolean(agent?.address);
  if (role === 'helper') {
    if (ended && (agent?.resultPath || agent?.summary)) return 'chat';
    if (!ended && kind === 'claude') return 'chat';
    return hasTerm ? 'terminal' : 'chat';
  }
  if (kind === 'claude') return 'chat';
  if (kind && kind !== 'claude') return hasTerm ? 'terminal' : 'chat';
  if (hasTerm && agent?.programKey && agent.programKey !== 'claude') return 'terminal';
  return 'chat';
}

function normalizeAgentKey(raw) {
  const s = String(raw || '').trim().toLowerCase();
  if (!s) return '';
  if (s === 'claude-code' || s === 'claude_code') return 'claude';
  if (s === 'antigravity') return 'agy';
  return s;
}

export function resolveAgentProgram(term, liveAgent = null, kind = '', catalog = null) {
  const pick = p => (p && typeof p === 'object' && p.icon && !p.shell
    ? { key: String(p.key || ''), name: String(p.name || ''), icon: String(p.icon), tint: Boolean(p.tint) }
    : null);
  const direct = pick(liveAgent?.program) || pick(term?.program);
  if (direct) return direct;
  if (catalog && typeof catalog.get === 'function') {
    for (const raw of [kind, liveAgent?.app, liveAgent?.program?.key, term?.program?.key]) {
      const k = normalizeAgentKey(raw);
      if (k && catalog.has(k)) return catalog.get(k);
    }
  }
  return null;
}

// The task a helper terminal works for: `helper.task` (a PM-owned helper serving a task, e.g. the merge helper
// `pm.py approve --via helper` starts) or `helper.of` (a helper the task's own worker started).
export function helperTaskOf(term) {
  const lb = term?.labels;
  return String(lb?.['helper.task'] || lb?.['helper.of'] || '');
}

// What a task-serving helper is for, from the name pm.py gives it (`land-<task>` for approve --via helper,
// `triage-<task>` for triage): 'land' | 'triage' | ''.
export function helperPurpose(h) {
  const name = String(h?.name || '');
  if (name.startsWith('land-')) return 'land';
  if (name.startsWith('triage-')) return 'triage';
  return '';
}

// The task a PM-owned helper (`pm.helpers` in `pm.py state`) serves, or '':
//   1. its `for_task` (`pm.py state` exposes it from the ledger or `helper.task` label),
//   2. the `helper.task` label of its terminal (live or ended),
//   3. an ended land-/triage- helper whose terminal is gone: the task id its pm.py-written prompt names.
export function pmHelperTask(h, terms = []) {
  if (!h || typeof h !== 'object') return '';
  if (h.for_task) return String(h.for_task);
  const addr = String(h.terminal || h.pane || '').replace(/^hc:/, '');
  const name = String(h.name || '');
  const term = addr ? (Array.isArray(terms) ? terms : []).find(t => t?.address === addr &&
    (!t.labels?.helper || !name || t.labels.helper === name)) : null;
  const labelled = String(term?.labels?.['helper.task'] || '');
  if (labelled) return labelled;
  if (term?.labels?.helper) return '';
  if (!helperPurpose(h)) return '';
  const m = /^PM approved merging task (\S+) \(/.exec(String(h.prompt || ''))
    || /\bfor task (\S+) \(/.exec(String(h.prompt || ''))
    || /（任务 (\S+?)：/.exec(String(h.prompt || ''));
  return m ? m[1] : '';
}

export function threadAgents(task, { terms = [], live = [], pmPane = '', lang = 'en', container = false, pmHelpers = [] } = {}) {
  const empty = { active: [], ended: [], all: [], endedCount: 0, endedSummary: '' };
  if (!task?.id) return empty;
  const termList = Array.isArray(terms) ? terms : [];
  const liveList = Array.isArray(live) ? live : [];
  const programCatalog = new Map();
  const rememberProgram = (prog, app = '') => {
    if (!prog || typeof prog !== 'object' || !prog.icon || prog.shell) return;
    const rec = { key: String(prog.key || ''), name: String(prog.name || ''), icon: String(prog.icon), tint: Boolean(prog.tint) };
    for (const raw of [prog.key, app]) {
      const k = normalizeAgentKey(raw);
      if (k && !programCatalog.has(k)) programCatalog.set(k, rec);
    }
  };
  for (const a of liveList) rememberProgram(a?.program, a?.app);
  for (const t of termList) rememberProgram(t?.program);
  const liveOf = term => (term?.address ? liveList.find(a => a.address === term.address) || null : null);
  const cleanPane = p => {
    const s = String(p || '');
    return s.startsWith('hc:') ? s.slice(3) : s;
  };
  const liveStatus = term => {
    if (!term) return 'idle';
    const s = liveList.find(a => a.address === term.address)?.status || term.status;
    return ['working', 'blocked', 'done', 'idle'].includes(s) ? s : 'idle';
  };
  const shortModel = (engineObj, fallbackKind) => {
    const chip = engineObj ? engineChip(lang, { engine: engineObj }) : null;
    if (chip?.name) return chip.name;
    const lbl = engineObj ? engineLabel({ engine: engineObj }) : '';
    if (lbl) return lbl;
    return fallbackKind ? cap(String(fallbackKind)) : '';
  };

  const active = [];
  const ended = [];
  const usedNames = new Set();
  const pushAgent = (entry, isActive) => {
    if (isActive) active.push(entry);
    else ended.push(entry);
  };

  const taskOver = CLOSED.includes(task.status);
  const taskPaused = task.status === 'paused';

  // 1. Primary worker (container epics have none; single-worker display is resolved via threadAgentLayout).
  if (!container) {
    const wTerm = terminalFor(taskRow(task), termList);
    const wEngine = taskEngine(task);
    const wPane = String(task.pane || '');
    const ownPane = Boolean(wPane && (!pmPane || wPane !== pmPane));
    const hasWorker = Boolean(wTerm) || Boolean(wEngine) || Boolean(task.closed) || Boolean(task.session) ||
      ownPane || contextTokens(task.context_tokens) > 0;
    const skipUnstarted = task.status === 'proposed' && !wTerm && !wEngine && !ownPane;
    if (hasWorker && !skipUnstarted) {
      const isActive = Boolean(wTerm) && !taskOver && !taskPaused;
      const kind = String(wEngine?.kind || wTerm?.program?.key || task.agent || '');
      const ctx = contextTokens(task.context_tokens || wTerm?.context_tokens);
      const programKey = String(wTerm?.program?.key || kind || '').toLowerCase();
      const program = resolveAgentProgram(wTerm, liveOf(wTerm), kind, programCatalog);
      const address = isActive ? wTerm.address : '';
      const badge = formatAgentModelEffort(wEngine, kind);
      const key = `worker:${task.id}`;
      const status = isActive ? liveStatus(wTerm) : (taskOver ? (task.status === 'merged' ? 'merged' : task.status === 'done' ? 'done' : 'ended') : 'ended');
      const action = inferAgentAction({ role: 'worker', task });
      const entry = {
        key,
        role: 'worker',
        roleLabel: word(lang, 'agentRole_worker'),
        displayName: agentDisplayName(key, usedNames),
        action,
        actionLabel: agentActionLabel(lang, action, status, { ended: !isActive, taskStatus: task.status }),
        taskId: task.id,
        ...(taskNumber(task) ? { threadNumber: taskNumber(task) } : {}),
        targetId: task.id,
        name: task.id,
        nameSuffix: '',
        threadTitle: task.title || task.id,
        address,
        status: isActive ? status : 'ended',
        ended: !isActive,
        kind,
        programKey,
        program,
        model: shortModel(wEngine, kind),
        modelShort: badge.model,
        effort: badge.effort,
        modelBadge: badge.label,
        up: wasEscalated(task),
        contextTokens: ctx,
        contextLabel: contextShort(ctx),
        canSwitchMode: Boolean(isActive && wTerm?.address),
        resultPath: '',
        summary: '',
        prompt: '',
      };
      entry.defaultMode = agentDefaultMode(entry);
      pushAgent(entry, isActive);
    }
  }

  // 2. Folded review agent (if present).
  if (task.review?.id) {
    const r = task.review;
    const rTerm = terminalFor(taskRow(r), termList);
    const rEngine = taskEngine(r);
    const rOver = CLOSED.includes(r.status);
    const isActive = Boolean(rTerm) && !rOver && r.status !== 'paused' && !taskOver && !taskPaused;
    const kind = String(rEngine?.kind || rTerm?.program?.key || r.agent || '');
    const ctx = contextTokens(r.context_tokens || rTerm?.context_tokens);
    const programKey = String(rTerm?.program?.key || kind || '').toLowerCase();
    const program = resolveAgentProgram(rTerm, liveOf(rTerm), kind, programCatalog);
    const address = isActive ? rTerm.address : '';
    const badge = formatAgentModelEffort(rEngine, kind);
    const key = `review:${r.id}`;
    const status = isActive ? liveStatus(rTerm) : (rOver ? 'done' : 'ended');
    const action = inferAgentAction({ role: 'review', task: r });
    const entry = {
      key,
      role: 'review',
      roleLabel: word(lang, 'agentRole_review'),
      displayName: agentDisplayName(key, usedNames),
      action,
      actionLabel: agentActionLabel(lang, action, status, { ended: !isActive, taskStatus: r.status }),
      taskId: task.id,
      ...(taskNumber(task) ? { threadNumber: taskNumber(task) } : {}),
      targetId: r.id,
      name: r.id,
      nameSuffix: '',
      threadTitle: task.title || task.id,
      address,
      status,
      ended: !isActive,
      kind,
      programKey,
      program,
      model: shortModel(rEngine, kind),
      modelShort: badge.model,
      effort: badge.effort,
      modelBadge: badge.label,
      up: wasEscalated(r),
      contextTokens: ctx,
      contextLabel: contextShort(ctx),
      canSwitchMode: Boolean(isActive && rTerm?.address),
      resultPath: '',
      summary: '',
      prompt: '',
    };
    entry.defaultMode = agentDefaultMode(entry);
    pushAgent(entry, isActive);
  }

  // 3. Task helpers: the task's own (ledger `task.helpers`, live `helper.of` terminals) and the PM's helpers
  //    that serve it (`pm.py approve --via helper` / `triage`: owned by the PM, linked by `for_task` in the
  //    ledger and `helper.task` on the terminal; see pmHelperTask).
  const seenHelperAddrs = new Set();
  const seenHelperNames = new Set();
  const ownHelpers = Array.isArray(task.helpers) ? task.helpers : [];
  const servingHelpers = (Array.isArray(pmHelpers) ? pmHelpers : [])
    .filter(h => h && typeof h === 'object' && pmHelperTask(h, termList) === task.id);
  [...ownHelpers, ...servingHelpers].forEach((h, idx) => {
    if (!h || typeof h !== 'object') return;
    const hAddr = cleanPane(h.terminal || h.pane);
    const hName = String(h.name || '');
    const term = termList.find(t =>
      (hAddr && t.address === hAddr) ||
      (t.state === 'live' && hName && helperTaskOf(t) === task.id && t.labels?.helper === hName));
    const liveAddr = term?.state === 'live' ? term.address : '';
    const addr = liveAddr || hAddr;
    if (addr && seenHelperAddrs.has(addr)) return;
    if (addr) seenHelperAddrs.add(addr);
    if (hName) seenHelperNames.add(hName);
    const hRunning = h.status === 'running' && !h.offline && h.live_state !== 'offline';
    const isActive = hRunning && !taskOver && !taskPaused && (!term ? Boolean(hAddr) : term.state === 'live');
    const hEngine = (h.profile || h.kind || h.model || h.effort)
      ? { profile: h.profile || '', kind: h.kind || '', model: h.model || '', effort: h.effort || '' }
      : null;
    const kind = String(h.kind || term?.program?.key || '');
    const ctx = contextTokens(h.context_tokens || term?.context_tokens);
    const programKey = String(term?.program?.key || kind || '').toLowerCase();
    const program = resolveAgentProgram(term, liveOf(term), kind, programCatalog);
    const activeAddr = isActive ? (liveAddr || hAddr) : '';
    const rawLive = term ? liveStatus(term) : (['working', 'blocked', 'done', 'idle'].includes(h.live_state) ? h.live_state : 'working');
    const purpose = helperPurpose(h);
    const badge = formatAgentModelEffort(hEngine, kind);
    const key = addr ? `helper:${task.id}:${addr}` : `helper:${task.id}:${hName || 'helper'}#${idx}`;
    const status = isActive ? rawLive : (h.status === 'done' ? 'done' : 'ended');
    const action = inferAgentAction({ role: 'helper', purpose, helperName: hName, helperPrompt: h.prompt, task });
    const entry = {
      key,
      role: 'helper',
      roleLabel: word(lang, 'agentRole_helper'),
      displayName: agentDisplayName(key, usedNames),
      action,
      actionLabel: agentActionLabel(lang, action, status, { ended: !isActive, taskStatus: h.status }),
      taskId: task.id,
      ...(taskNumber(task) ? { threadNumber: taskNumber(task) } : {}),
      targetId: hName || addr || task.id,
      name: hName || addr || 'helper',
      nameSuffix: purpose ? word(lang, `${isActive ? 'helperDoing' : 'helperDid'}_${purpose}`) : hName,
      ...(purpose ? { purpose } : {}),
      threadTitle: task.title || task.id,
      address: activeAddr,
      status,
      ended: !isActive,
      kind,
      programKey,
      program,
      model: shortModel(hEngine, kind),
      modelShort: badge.model,
      effort: badge.effort,
      modelBadge: badge.label,
      up: false,
      contextTokens: ctx,
      contextLabel: contextShort(ctx),
      canSwitchMode: Boolean(isActive && activeAddr),
      resultPath: String(h.result || ''),
      summary: String(h.summary || ''),
      prompt: String(h.prompt || ''),
    };
    entry.defaultMode = agentDefaultMode(entry);
    pushAgent(entry, isActive);
  });

  for (const term of termList) {
    if (term?.state !== 'live' || helperTaskOf(term) !== task.id) continue;
    if (seenHelperAddrs.has(term.address)) continue;
    const hName = String(term.labels?.helper || term.address || '');
    if (hName && seenHelperNames.has(hName)) continue;
    seenHelperAddrs.add(term.address);
    const kind = String(term.program?.key || '');
    const ctx = contextTokens(term.context_tokens);
    const program = resolveAgentProgram(term, liveOf(term), kind, programCatalog);
    const purpose = helperPurpose({ name: term.labels?.helper });
    const badge = formatAgentModelEffort(null, kind);
    const key = `helper:${task.id}:${term.address}`;
    const status = liveStatus(term);
    const action = inferAgentAction({ role: 'helper', purpose, helperName: String(term.labels?.helper || ''), task });
    const entry = {
      key,
      role: 'helper',
      roleLabel: word(lang, 'agentRole_helper'),
      displayName: agentDisplayName(key, usedNames),
      action,
      actionLabel: agentActionLabel(lang, action, status, { ended: false }),
      taskId: task.id,
      ...(taskNumber(task) ? { threadNumber: taskNumber(task) } : {}),
      targetId: hName,
      name: hName,
      nameSuffix: purpose ? word(lang, `helperDoing_${purpose}`) : String(term.labels?.helper || ''),
      ...(purpose ? { purpose } : {}),
      threadTitle: task.title || task.id,
      address: term.address,
      status,
      ended: false,
      kind,
      programKey: kind.toLowerCase(),
      program,
      model: kind ? cap(kind) : '',
      modelShort: badge.model,
      effort: badge.effort,
      modelBadge: badge.label,
      up: false,
      contextTokens: ctx,
      contextLabel: contextShort(ctx),
      canSwitchMode: true,
      resultPath: '',
      summary: '',
      prompt: '',
    };
    entry.defaultMode = agentDefaultMode(entry);
    pushAgent(entry, true);
  }

  let endedSummary = '';
  if (ended.length) {
    const primary = ended.find(a => a.model || a.contextLabel) || ended[0];
    endedSummary = [word(lang, 'endedAgents', ended.length), primary?.model, primary?.contextLabel].filter(Boolean).join(' · ');
  }
  return {
    active,
    ended,
    all: [...active, ...ended],
    endedCount: ended.length,
    endedSummary,
  };
}

// Single-worker inline vs multi-agent compact sub-rows (Option 1):
// - Exactly 1 active agent and it is the primary worker -> inline clickable capsule on the task row.
// - >=2 active agents (e.g. worker + review or worker + helper) or a single active non-worker -> compact sub-rows.
export function threadAgentLayout(agents) {
  const active = Array.isArray(agents?.active) ? agents.active : [];
  const ended = Array.isArray(agents?.ended) ? agents.ended : [];
  const inlineWorker = active.length === 1 && active[0]?.role === 'worker' ? active[0] : null;
  const subAgents = inlineWorker ? [] : active;
  return { inlineWorker, subAgents, ended };
}

// Responsive parts inside the inline single-worker capsule:
// - Wide/normal panel (effective width >= 340px): name · action · model·effort (e.g. Milo · 编码 · Opus·xhigh)
// - Narrower panel (300..339px): name · modelShort (e.g. Milo · Opus)
// - Compact panel (270..299px): name only (e.g. Milo)
// - Tight panel (< 270px): empty (icon-only, always keeping the clickable agent icon)
export function inlineAgentBadgeParts(agent, width = 0, { inEpic = false } = {}) {
  const name = String(agent?.displayName || '').trim();
  const action = String(agent?.actionLabel || '').trim();
  const fullModel = String(agent?.modelBadge || agent?.model || '').trim();
  const shortModel = String(agent?.modelShort || agent?.model || '').trim();
  const w = Number(width) || 0;
  const eff = w > 0 ? w - (inEpic ? 28 : 0) : 999;
  if (eff < 270) return { name: '', action: '', model: '' };
  if (eff < 300) {
    if (name) return { name, action: '', model: '' };
    return { name: '', action: '', model: shortModel || fullModel };
  }
  if (eff < 340) return { name, action: '', model: shortModel || fullModel };
  return { name, action, model: fullModel || shortModel };
}

export function inlineAgentBadgeText(agent, width = 0, opts = {}) {
  const p = inlineAgentBadgeParts(agent, width, opts);
  return [p.name, p.action, p.model].filter(Boolean).join(' · ');
}

function rawDepIds(task) {
  const rawList = Array.isArray(task?.deps) && task.deps.length
    ? task.deps
    : (Array.isArray(task?.depends_on) ? task.depends_on : []);
  const out = [];
  for (const raw of rawList) {
    const depId = typeof raw === 'string' ? raw.trim() : String(raw?.id || '').trim();
    if (depId) out.push(depId);
  }
  return out;
}

// Stable wave-based topological sort for sibling child tasks under a parent:
// - Keeps status rank ordering (active tasks before proposed).
// - Within each rank bucket, orders prerequisites before dependents.
// - For proposed tasks (rank 7), orders ready tasks (no unmet deps) ahead of waiting ones,
//   and breaks same-wave ties by number ascending, then created ascending, then updated ascending.
// - Safely degrades on dependency cycles without infinite loops.
export function sortChildTasks(items, allTasks = [], metaOf = t => ({ task: t, rank: openRank(t), updated: String(t?.updated || '') })) {
  const list = Array.isArray(items) ? items : [];
  if (list.length <= 1) return [...list];

  const byRank = new Map();
  list.forEach((item, index) => {
    const meta = metaOf(item) || {};
    const task = meta.task || item;
    const rank = Number.isFinite(meta.rank) ? meta.rank : openRank(task || {});
    const updated = String(meta.updated ?? task?.updated ?? '');
    let bucket = byRank.get(rank);
    if (!bucket) { bucket = []; byRank.set(rank, bucket); }
    bucket.push({ item, task, rank, updated, index });
  });

  const sortedRanks = [...byRank.keys()].sort((a, b) => a - b);
  const result = [];

  for (const rank of sortedRanks) {
    const entries = byRank.get(rank);
    if (entries.length <= 1) {
      if (entries.length === 1) result.push(entries[0].item);
      continue;
    }

    const isProposed = rank === 7;
    if (isProposed) {
      for (const e of entries) {
        const deps = taskDependencies(e.task, allTasks);
        e.ready = !deps || deps.allMet;
      }
    }

    const n = entries.length;
    const findSiblingIndex = (depId, taskMachine) => {
      const namespaced = taskMachine ? `${taskMachine}/${depId}` : depId;
      for (let i = 0; i < n; i++) {
        const t = entries[i].task;
        if (!t) continue;
        if (t.id === depId || t.id === namespaced || ((t.machine || '') === taskMachine && t.sourceId === depId)) {
          return i;
        }
      }
      return -1;
    };

    const adj = Array.from({ length: n }, () => []);
    const inDegree = new Int32Array(n);
    for (let v = 0; v < n; v++) {
      const task = entries[v].task;
      const taskMachine = task?.machine || '';
      const seenEdges = new Set();
      for (const depId of rawDepIds(task)) {
        const u = findSiblingIndex(depId, taskMachine);
        if (u < 0 || u === v || seenEdges.has(u)) continue;
        seenEdges.add(u);
        adj[u].push(v);
        inDegree[v]++;
      }
    }

    const compare = isProposed
      ? (a, b) => {
          if (a.ready !== b.ready) return a.ready ? -1 : 1;
          const aNum = taskNumber(a.task);
          const bNum = taskNumber(b.task);
          if (aNum !== null && bNum !== null && aNum !== bNum) return aNum - bNum;
          const aCreated = String(a.task?.created || '');
          const bCreated = String(b.task?.created || '');
          if (aCreated && bCreated && aCreated !== bCreated) return aCreated.localeCompare(bCreated);
          if (a.updated !== b.updated) return a.updated.localeCompare(b.updated);
          return a.index - b.index;
        }
      : (a, b) => b.updated.localeCompare(a.updated) || (a.index - b.index);

    const placed = new Uint8Array(n);
    let placedCount = 0;

    const drainWaves = initialWave => {
      let wave = initialWave;
      while (wave.length > 0) {
        wave.sort((i, j) => compare(entries[i], entries[j]));
        const nextWave = [];
        for (const u of wave) {
          if (placed[u]) continue;
          placed[u] = 1;
          placedCount++;
          result.push(entries[u].item);
          for (const v of adj[u]) {
            if (placed[v]) continue;
            inDegree[v]--;
            if (inDegree[v] === 0) nextWave.push(v);
          }
        }
        wave = nextWave;
      }
    };

    const startWave = [];
    for (let i = 0; i < n; i++) {
      if (inDegree[i] === 0) startWave.push(i);
    }
    drainWaves(startWave);

    // Safe cycle fallback: break remaining cycles deterministically without infinite loops.
    while (placedCount < n) {
      let best = -1;
      for (let i = 0; i < n; i++) {
        if (placed[i]) continue;
        if (best < 0 || inDegree[i] < inDegree[best] ||
            (inDegree[i] === inDegree[best] && compare(entries[i], entries[best]) < 0)) {
          best = i;
        }
      }
      if (best < 0) break;
      placed[best] = 1;
      placedCount++;
      result.push(entries[best].item);
      const unlocked = [];
      for (const v of adj[best]) {
        if (placed[v]) continue;
        inDegree[v]--;
        if (inDegree[v] <= 0) unlocked.push(v);
      }
      if (unlocked.length) drainWaves(unlocked);
    }
  }

  return result;
}

// ---- Threads task tree (container epics + sub-threads + sub-agents) -----------------------

export function taskTree(pm, tasks, events = [], { terms = [], live = [], tabs = [], lang = 'en', retiredParts = [], alreadyFolded = false } = {}) {
  const folded = alreadyFolded ? (Array.isArray(tasks) ? tasks.filter(Boolean) : []) : foldReviews(tasks);
  const pmName = pm?.name || '';
  const pmPane = pm?.pane || '';
  const mine = folded.filter(t => t && (t.pm || '') === pmName);
  const openTasks = mine.filter(t => !CLOSED.includes(t.status));
  const openById = new Map(openTasks.map(t => [t.id, t]));
  const openIds = new Set([...openTasks.map(t => t.id), ...mine.filter(t => t.review?.id).map(t => t.review.id)]);
  const base = threadSessionsAndFinished(pm, mine, openIds, events, terms, live, tabs);
  const atWork = workingTasks(terms, live);
  const newest = (a, b) => String(b.updated || '').localeCompare(String(a.updated || ''));

  // Resolve parent edges among open tasks while safely breaking any cycles.
  const parentOf = new Map();
  for (const t of openTasks) {
    let p = t.parent && t.parent !== t.id && openById.has(t.parent) ? t.parent : '';
    if (p) {
      const seen = new Set([t.id]);
      let cur = p;
      while (cur) {
        if (seen.has(cur)) { p = ''; break; }
        seen.add(cur);
        if (parentOf.has(cur)) cur = parentOf.get(cur);
        else {
          const next = openById.get(cur)?.parent;
          cur = next && next !== cur && openById.has(next) ? next : '';
        }
      }
    }
    parentOf.set(t.id, p);
  }

  const childrenById = new Map(openTasks.map(t => [t.id, []]));
  const roots = [];
  for (const t of openTasks) {
    const p = parentOf.get(t.id);
    if (p && childrenById.has(p)) childrenById.get(p).push(t);
    else roots.push(t);
  }

  // Finished children (closed non-abandoned tasks + `retiredParts`), deduplicated per parent.
  const finishedByParent = new Map();
  const seenFinished = new Set();
  const retiredList = Array.isArray(retiredParts) ? retiredParts.filter(t => !pmName || !t?.pm || t.pm === pmName) : [];
  for (const t of [...mine, ...retiredList]) {
    if (!t?.id || !t.parent || t.parent === t.id || t.review_of) continue;
    if (!CLOSED.includes(t.status) || t.status === GIVEN_UP) continue;
    if (!openById.has(t.parent)) continue;
    if (seenFinished.has(t.id)) continue;
    seenFinished.add(t.id);
    const ctx = contextTokens(t.context_tokens);
    const commit = shortCommit(t);
    const list = finishedByParent.get(t.parent) || [];
    list.push({
      task: t.id,
      ...(taskNumber(t) ? { number: taskNumber(t) } : {}),
      title: t.title || t.id,
      status: t.status,
      tone: 'quiet',
      group: 'finished',
      cleanup: Boolean(t.cleanup),
      updated: String(t.updated || ''),
      ...(t.folder_alias ? { folderAlias: String(t.folder_alias) } : {}),
      ...(commit ? { commit } : {}),
      ...(ctx ? { contextTokens: ctx } : {}),
    });
    finishedByParent.set(t.parent, list);
  }
  for (const list of finishedByParent.values()) list.sort(newest);

  const allTasksForDeps = retiredList.length ? [...folded, ...retiredList] : folded;
  const buildNode = task => {
    const rawChildren = childrenById.get(task.id) || [];
    const children = sortChildTasks(rawChildren.map(buildNode), allTasksForDeps, node => ({
      task: openById.get(node.task),
      rank: node._rank,
      updated: String(node._updated || ''),
    }));
    const finishedChildren = finishedByParent.get(task.id) || [];
    const hasChildren = children.length > 0 || finishedChildren.length > 0;
    const ownLiveTerm = terminalFor(taskRow(task), terms);
    const hasOwnWorker = Boolean(ownLiveTerm) || Boolean(task.branch) || Boolean(taskEngine(task)) ||
      (Boolean(task.pane) && (!pmPane || task.pane !== pmPane) && !hasChildren);
    const container = hasChildren && !hasOwnWorker;

    const row = openRow(task, lang, atWork, terms, live);
    let effectiveGroup = row.group;
    let effectiveRank = openRank(task);
    let effectiveUpdated = row.updated;

    if (container) {
      row.working = false;
      delete row.reviewWorking;
      delete row.offline;
      if (!(task.status === 'blocked' && !answeredRow(task))) row.tone = 'quiet';
      if (task.status === 'blocked' && !answeredRow(task)) {
        effectiveGroup = 'waiting';
        effectiveRank = 0;
      } else if (children.length > 0) {
        effectiveRank = Math.min(...children.map(c => c._rank));
        const best = children.find(c => c._rank === effectiveRank) || children[0];
        effectiveGroup = best.group;
        for (const c of children) {
          if (c._updated > effectiveUpdated) effectiveUpdated = c._updated;
        }
      } else {
        effectiveGroup = task.status === 'paused' ? 'paused' : task.status === 'proposed' ? 'parked' : 'working';
        effectiveRank = effectiveGroup === 'paused' ? 6 : effectiveGroup === 'parked' ? 7 : 4;
      }
    }

    let summary = null;
    let activeChild = null;
    if (hasChildren) {
      summary = { waiting: 0, review: 0, working: 0, offline: 0, paused: 0, parked: 0, done: finishedChildren.length };
      for (const c of children) {
        if (c.group === 'waiting') summary.waiting++;
        else if (c.group === 'review' || (c.group === 'working' && (c.reviewing || c.status === 'review'))) summary.review++;
        else if (c.group === 'working') summary.working++;
        else if (c.group === 'offline') summary.offline++;
        else if (c.group === 'paused') summary.paused++;
        else summary.parked++;
      }
      if (children.length) {
        const cNum = taskNumber(children[0]);
        activeChild = { task: children[0].task, ...(cNum ? { number: cNum } : {}), title: children[0].title, status: children[0].status, group: children[0].group };
      }
    }

    const agents = threadAgents(task, { terms, live, pmPane, lang, container, pmHelpers: pm?.helpers });
    return {
      ...row,
      group: effectiveGroup,
      parent: String(task.parent || ''),
      container,
      children,
      finishedChildren,
      summary,
      activeChild,
      agents,
      _rank: effectiveRank,
      _updated: effectiveUpdated,
    };
  };

  const builtRoots = roots.map(buildNode);
  const stripMeta = node => {
    const { _rank, _updated, children, ...rest } = node;
    return { ...rest, children: children.map(stripMeta) };
  };

  const groups = [];
  for (const id of OPEN_GROUPS) {
    const matched = builtRoots
      .filter(n => n.group === id)
      .sort((a, b) => a._rank - b._rank || String(b._updated).localeCompare(String(a._updated)))
      .map(stripMeta);
    if (matched.length) {
      const key = `group_${id}`;
      groups.push({ id, key, title: word(lang, key), count: matched.length, nodes: matched });
    }
  }

  const flatOpen = [];
  const collectFlat = list => {
    for (const node of list) {
      flatOpen.push(node);
      if (node.children.length) collectFlat(node.children);
    }
  };
  for (const g of groups) collectFlat(g.nodes);

  const finished = base.finished.filter(row => !seenFinished.has(row.task));
  return { groups, flatOpen, sessions: base.sessions, finished };
}

// ---- In-Project floating agent small windows (toggle, cap 2, LRU eviction, mode & size) ---

export const AGENT_WINDOW_MAX = 2;
export const AGENT_WINDOW_SIZE_ORDER = ['s', 'm', 'l'];
export const AGENT_WINDOW_DEFAULT_SIZE = 'm';
export const AGENT_WINDOW_SIZES = {
  s: { chat: { width: 420, height: 340 }, terminal: { width: 440, height: 300 } },
  m: { chat: { width: 520, height: 420 }, terminal: { width: 540, height: 380 } },
  l: { chat: { width: 760, height: 580 }, terminal: { width: 800, height: 540 } },
};

export function normalizeAgentWindowSize(size) {
  const key = String(size || '').toLowerCase();
  return AGENT_WINDOW_SIZE_ORDER.includes(key) ? key : AGENT_WINDOW_DEFAULT_SIZE;
}

export function nextAgentWindowSize(size) {
  const cur = normalizeAgentWindowSize(size);
  const idx = AGENT_WINDOW_SIZE_ORDER.indexOf(cur);
  return AGENT_WINDOW_SIZE_ORDER[(idx + 1) % AGENT_WINDOW_SIZE_ORDER.length];
}

export function agentWindowDimensions(mode, size = AGENT_WINDOW_DEFAULT_SIZE, { maxWidth = 0, maxHeight = 0 } = {}) {
  const preset = AGENT_WINDOW_SIZES[normalizeAgentWindowSize(size)];
  const base = mode === 'terminal' ? preset.terminal : preset.chat;
  const width = maxWidth > 0 ? Math.min(base.width, Math.max(360, Math.floor(maxWidth))) : base.width;
  const height = maxHeight > 0 ? Math.min(base.height, Math.max(260, Math.floor(maxHeight))) : base.height;
  return { width, height };
}

export function agentWindowTerminalAddresses(windows, machine = '') {
  const list = Array.isArray(windows) ? windows : [];
  const prefix = machine ? `${machine}/` : '';
  const seen = new Set();
  for (const w of list) {
    if (w?.mode !== 'terminal' || !w.address) continue;
    const raw = String(w.address);
    const addr = (prefix && raw.startsWith(prefix)) ? raw : onMachine(raw, machine);
    if (addr) seen.add(addr);
  }
  return [...seen].sort();
}

export function agentWindowOpen(windows, key) {
  return Boolean(key) && Array.isArray(windows) && windows.some(w => w?.key === key);
}

export function toggleAgentWindow(windows, spec, { max = AGENT_WINDOW_MAX } = {}) {
  const list = Array.isArray(windows) ? windows : [];
  const key = String(spec?.key || '');
  if (!key) return { windows: list, action: 'none', closed: null, opened: null, evicted: null };
  const idx = list.findIndex(w => w?.key === key);
  if (idx >= 0) {
    const closed = list[idx];
    const next = [...list.slice(0, idx), ...list.slice(idx + 1)];
    return { windows: next, action: 'close', closed, opened: null, evicted: null };
  }
  const capCount = Math.max(1, Number(max) || AGENT_WINDOW_MAX);
  const evicted = list.length >= capCount ? list[0] : null;
  const kept = evicted ? list.slice(list.length - capCount + 1) : list;
  const address = String(spec.address || '');
  const entry = {
    key,
    overlayId: String(spec.overlayId || ''),
    role: String(spec.role || 'worker'),
    roleLabel: String(spec.roleLabel || ''),
    displayName: String(spec.displayName || ''),
    action: String(spec.action || ''),
    actionLabel: String(spec.actionLabel || ''),
    taskId: String(spec.taskId || ''),
    targetId: String(spec.targetId || ''),
    name: String(spec.name || ''),
    threadTitle: String(spec.threadTitle || ''),
    address,
    mode: spec.mode || spec.defaultMode || 'chat',
    size: normalizeAgentWindowSize(spec.size),
    canSwitchMode: Boolean(spec.canSwitchMode ?? address),
    typing: Boolean(spec.typing),
    model: String(spec.model || ''),
    up: Boolean(spec.up),
    contextLabel: String(spec.contextLabel || ''),
    ended: Boolean(spec.ended),
    kind: String(spec.kind || ''),
    resultPath: String(spec.resultPath || ''),
    summary: String(spec.summary || ''),
    prompt: String(spec.prompt || ''),
  };
  return { windows: [...kept, entry], action: 'open', closed: null, opened: entry, evicted };
}

export function resolveHelperResultPath(resultPath, { ledgerHome = '', slug = '', homeDir = '' } = {}) {
  const raw = String(resultPath || '').trim();
  if (!raw) return '';
  const norm = raw.replace(/\\/g, '/');
  if (norm.split('/').includes('..')) return '';
  const ledgerMatch = /^~\/(?:\.dudu|\.claude\/pm)\/(.+)$/.exec(norm);
  if (ledgerMatch && ledgerHome) {
    return `${String(ledgerHome).replace(/[\\/]+$/, '')}/${ledgerMatch[1]}`;
  }
  if (norm.startsWith('~/')) {
    return homeDir ? `${String(homeDir).replace(/[\\/]+$/, '')}/${norm.slice(2)}` : '';
  }
  if (raw.startsWith('/') || /^[A-Za-z]:[\\/]/.test(raw)) return raw;
  if (ledgerHome && slug) {
    return `${String(ledgerHome).replace(/[\\/]+$/, '')}/projects/${slug}/${norm.replace(/^\/+/, '')}`;
  }
  return '';
}

export function focusAgentWindow(windows, key) {
  const list = Array.isArray(windows) ? windows : [];
  if (!key) return list;
  const idx = list.findIndex(w => w?.key === key);
  if (idx < 0 || idx === list.length - 1) return list;
  return [...list.slice(0, idx), ...list.slice(idx + 1), list[idx]];
}

export function closeAgentWindow(windows, key = '') {
  const list = Array.isArray(windows) ? windows : [];
  if (!list.length) return { windows: list, closed: null };
  if (!key) {
    return { windows: list.slice(0, -1), closed: list[list.length - 1] };
  }
  const idx = list.findIndex(w => w?.key === key);
  if (idx < 0) return { windows: list, closed: null };
  return { windows: [...list.slice(0, idx), ...list.slice(idx + 1)], closed: list[idx] };
}

export function setAgentWindowOverlay(windows, key, overlayId) {
  const list = Array.isArray(windows) ? windows : [];
  const idx = list.findIndex(w => w?.key === key);
  if (idx < 0) return list;
  const nextId = String(overlayId || '');
  if (list[idx].overlayId === nextId) return list;
  return list.map((w, i) => (i === idx ? { ...w, overlayId: nextId } : w));
}

export function toggleAgentWindowMode(windows, key, nextMode = '') {
  const list = Array.isArray(windows) ? windows : [];
  const idx = list.findIndex(w => w?.key === key);
  if (idx < 0) return { windows: list, changed: false, window: null };
  const cur = list[idx];
  const want = nextMode || (cur.mode === 'terminal' ? 'chat' : 'terminal');
  if (want === 'terminal' && !cur.canSwitchMode && !cur.address) {
    return { windows: list, changed: false, window: cur };
  }
  if (cur.mode === want) return { windows: list, changed: false, window: cur };
  const updated = { ...cur, mode: want };
  return { windows: list.map((w, i) => (i === idx ? updated : w)), changed: true, window: updated };
}

export function setAgentWindowSize(windows, key, nextSize = '') {
  const list = Array.isArray(windows) ? windows : [];
  const idx = list.findIndex(w => w?.key === key);
  if (idx < 0) return { windows: list, changed: false, window: null };
  const cur = list[idx];
  const curSize = normalizeAgentWindowSize(cur.size);
  const want = nextSize ? normalizeAgentWindowSize(nextSize) : nextAgentWindowSize(curSize);
  if (curSize === want && cur.size === want) return { windows: list, changed: false, window: cur };
  const updated = { ...cur, size: want };
  return { windows: list.map((w, i) => (i === idx ? updated : w)), changed: true, window: updated };
}

export function reconcileAgentWindows(windows, liveAddresses) {
  const list = Array.isArray(windows) ? windows : [];
  if (!list.length) return { windows: list, closed: [] };
  const liveSet = liveAddresses instanceof Set
    ? liveAddresses
    : new Set(Array.isArray(liveAddresses) ? liveAddresses : []);
  const kept = [];
  const closed = [];
  for (const w of list) {
    if (w?.mode === 'terminal' && w.address && !liveSet.has(w.address)) closed.push(w);
    else kept.push(w);
  }
  return { windows: closed.length ? kept : list, closed };
}

// ---- Thread Change View (Interface H: commits -> files -> single-file diff) -------------

export const CHANGE_DIFF_LIMIT = 400;
export const CHANGE_COMMITS_LIMIT = 200;
export const CHANGE_TIMEOUT_LOCAL_MS = 30000;
export const CHANGE_TIMEOUT_REMOTE_MS = 45000;

export function diffLineNumWidth(lines) {
  let maxLine = 0;
  for (const line of Array.isArray(lines) ? lines : []) {
    if (!line || typeof line !== 'object') continue;
    if (typeof line.old_line === 'number' && line.old_line > maxLine) maxLine = line.old_line;
    if (typeof line.new_line === 'number' && line.new_line > maxLine) maxLine = line.new_line;
  }
  const digits = Math.max(3, String(Math.floor(maxLine)).length);
  return Math.ceil(digits * 7.5) + 4;
}

export function projectChangeArgv(
  slug,
  taskId,
  { commit = '', file = '', offset = 0, limit = CHANGE_DIFF_LIMIT, commitsLimit = CHANGE_COMMITS_LIMIT } = {},
) {
  const args = ['project', 'change', String(slug), String(taskId)];
  if (commit) args.push('--commit', String(commit));
  if (file) {
    args.push('--file', String(file));
    if (Number(offset) > 0) args.push('--offset', String(Math.floor(Number(offset))));
    if (Number(limit) > 0 && Number(limit) !== CHANGE_DIFF_LIMIT) {
      args.push('--limit', String(Math.floor(Number(limit))));
    }
  } else if (!commit && Number(commitsLimit) > 0 && Number(commitsLimit) !== CHANGE_COMMITS_LIMIT) {
    args.push('--commits-limit', String(Math.floor(Number(commitsLimit))));
  }
  return args;
}

export function changeDiffKey(scope, commitHash, filePath) {
  return `${scope === 'commit' && commitHash ? commitHash : 'all'}::${filePath || ''}`;
}

export function createChangeState(taskId = '') {
  return {
    open: false,
    taskId: String(taskId || ''),
    level: 'commits',
    summary: null,
    summaryLoading: false,
    summaryError: '',
    scope: 'all',
    commitHash: '',
    commitData: null,
    commitLoading: false,
    commitError: '',
    commitCache: {},
    filePath: '',
    fileMeta: null,
    diffData: null,
    diffLoading: false,
    diffLoadingMore: false,
    diffError: '',
    diffCache: {},
    foldedHunks: {},
    showBaseMerges: false,
    reqSeq: 0,
  };
}

export function openChangeView(state, taskId) {
  const id = String(taskId || '');
  if (state && state.taskId === id && state.summary) {
    return {
      ...state,
      open: true,
      level: 'commits',
      summaryError: '',
      commitError: '',
      diffError: '',
    };
  }
  return {
    ...createChangeState(id),
    open: true,
    level: 'commits',
  };
}

export function closeChangeView(state) {
  return { ...(state || createChangeState()), open: false };
}

export function enterChangeFiles(state, { scope = 'all', commitHash = '', commitMeta = null } = {}) {
  const base = state || createChangeState();
  const isCommit = scope === 'commit' && Boolean(commitHash);
  const hash = isCommit ? String(commitHash) : '';
  const cached = isCommit ? base.commitCache?.[hash] || null : null;
  const fallbackCommit = isCommit && !cached && commitMeta
    ? { commit: commitMeta, files: null }
    : cached;
  return {
    ...base,
    open: true,
    level: 'files',
    scope: isCommit ? 'commit' : 'all',
    commitHash: hash,
    commitData: fallbackCommit,
    commitLoading: false,
    commitError: '',
  };
}

export function enterChangeFileDiff(state, fileMeta) {
  const base = state || createChangeState();
  const path = String(fileMeta?.path || '');
  const key = changeDiffKey(base.scope, base.commitHash, path);
  const cached = base.diffCache?.[key] || null;
  return {
    ...base,
    open: true,
    level: 'diff',
    filePath: path,
    fileMeta: fileMeta || null,
    diffData: cached,
    diffLoading: false,
    diffLoadingMore: false,
    diffError: '',
    foldedHunks: {},
  };
}

export function stepBackChangeView(state) {
  if (!state?.open) return { state: state || createChangeState(), handled: false };
  if (state.level === 'diff') {
    return { state: { ...state, level: 'files', diffError: '', diffLoadingMore: false }, handled: true };
  }
  if (state.level === 'files') {
    return { state: { ...state, level: 'commits', commitError: '' }, handled: true };
  }
  return { state: { ...state, open: false }, handled: true };
}

export function appendDiffPage(prev, page) {
  if (!page || typeof page !== 'object') return prev || null;
  const incoming = Array.isArray(page.lines) ? page.lines : [];
  if (!prev || !Array.isArray(prev.lines) || (Number(page.offset) || 0) === 0) {
    return { ...page, lines: incoming };
  }
  const expected = (Number(prev.offset) || 0) + prev.lines.length;
  if (Number(page.offset) !== expected) {
    return { ...page, lines: incoming };
  }
  return {
    ...prev,
    ...page,
    offset: prev.offset,
    lines: [...prev.lines, ...incoming],
    truncated: Boolean(prev.truncated || page.truncated),
    truncated_lines: Boolean(prev.truncated_lines || page.truncated_lines),
  };
}

export function groupDiffHunks(lines) {
  const meta = [];
  const hunks = [];
  let current = null;
  for (const line of Array.isArray(lines) ? lines : []) {
    if (!line || typeof line !== 'object') continue;
    if (line.kind === 'hunk') {
      current = {
        id: `hunk-${hunks.length}`,
        index: hunks.length,
        header: String(line.text || ''),
        lines: [],
        insertions: 0,
        deletions: 0,
      };
      hunks.push(current);
      continue;
    }
    if (!current && line.kind === 'meta') {
      meta.push(line);
      continue;
    }
    if (!current) {
      current = {
        id: `hunk-${hunks.length}`,
        index: hunks.length,
        header: '',
        lines: [],
        insertions: 0,
        deletions: 0,
      };
      hunks.push(current);
    }
    if (line.kind === 'add') current.insertions += 1;
    else if (line.kind === 'del') current.deletions += 1;
    current.lines.push(line);
  }
  return { meta, hunks };
}

export function toggleDiffHunk(foldedHunks, hunkId) {
  const next = { ...(foldedHunks || {}) };
  if (next[hunkId]) delete next[hunkId];
  else next[hunkId] = true;
  return next;
}

export function toggleAllDiffHunks(foldedHunks, hunks) {
  const list = Array.isArray(hunks) ? hunks : [];
  if (!list.length) return {};
  const map = foldedHunks || {};
  const anyExpanded = list.some(h => !map[h.id]);
  if (!anyExpanded) return {};
  const next = {};
  for (const h of list) next[h.id] = true;
  return next;
}

export function splitFilePath(filePath) {
  const p = String(filePath || '');
  const idx = p.lastIndexOf('/');
  if (idx < 0) return { dir: '', name: p };
  return { dir: p.slice(0, idx), name: p.slice(idx + 1) };
}

export function changeStateMessage(lang, data) {
  if (!data || typeof data !== 'object') return '';
  switch (data.state) {
    case 'no_branch': return word(lang, 'changeNoBranch');
    case 'branch_deleted': return word(lang, 'changeBranchDeleted', data.branch || '');
    case 'empty': return word(lang, 'changeEmpty', data.branch || '', data.base || 'main');
    case 'base_missing': return word(lang, 'changeBaseMissing', data.branch || '');
    case 'no_repo': return word(lang, 'changeNoRepo');
    case 'not_git': return word(lang, 'changeNotGit');
    case 'no_git': return word(lang, 'changeNoGit');
    default: return String(data.message || '');
  }
}

export function formatCommitDate(iso, today = '') {
  const s = String(iso || '');
  if (!s) return '';
  if (today && s.slice(0, 10) === today && s.length >= 16) return s.slice(11, 16);
  if (s.length >= 16 && s[10] === 'T') return `${s.slice(5, 10)} ${s.slice(11, 16)}`;
  return s.slice(0, 16).replace('T', ' ');
}

// ---- Bounded hover tooltips (max width, CJK/word wrapping, line cap, panel/window clamping) ----

export const TOOLTIP_MAX_WIDTH = 420;
export const TOOLTIP_MIN_WIDTH = 56;
export const TOOLTIP_MAX_LINES = 5;
export const TOOLTIP_FONT_SIZE = 11.5;
export const TOOLTIP_LINE_HEIGHT = 16.5;
export const TOOLTIP_PAD_X = 18;
export const TOOLTIP_PAD_Y = 12;
export const TOOLTIP_MARGIN = 16;
export const TOOLTIP_GAP = 6;

function isWideCodePoint(code) {
  return code > 0xFFFF
    || (code >= 0x1100 && code <= 0x115F)
    || (code >= 0x2E80 && code <= 0xA4CF)
    || (code >= 0xAC00 && code <= 0xD7A3)
    || (code >= 0xF900 && code <= 0xFAFF)
    || (code >= 0xFE10 && code <= 0xFE19)
    || (code >= 0xFE30 && code <= 0xFE6F)
    || (code >= 0xFF00 && code <= 0xFF60)
    || (code >= 0xFFE0 && code <= 0xFFE6);
}

function charEmWidth(ch) {
  const code = ch.codePointAt(0) || 0;
  if (isWideCodePoint(code)) return 1.0;
  if (' ilI1.,:;\'!|()[]/-·tfjr'.includes(ch)) return 0.38;
  if ('WMmw@%#GOQ'.includes(ch)) return 0.78;
  return 0.58;
}

function measureEm(str) {
  let w = 0;
  for (const ch of str) w += charEmWidth(ch);
  return w;
}

function isBreakAfter(ch) {
  const code = ch.codePointAt(0) || 0;
  return ch === ' ' || ch === '\t' || isWideCodePoint(code)
    || '/-·,;。，、：；）】」'.includes(ch);
}

export function tooltipMaxWidth({
  panelWidth: panelW = 0,
  viewWidth = 0,
  maxWidth = TOOLTIP_MAX_WIDTH,
  margin = TOOLTIP_MARGIN,
} = {}) {
  const base = Number.isFinite(maxWidth) && maxWidth > 0 ? maxWidth : TOOLTIP_MAX_WIDTH;
  let cap = Math.max(80, Math.min(TOOLTIP_MAX_WIDTH, base));
  if (Number.isFinite(panelW) && panelW > 0) {
    cap = Math.min(cap, Math.max(80, Math.floor(panelW - margin * 2)));
  }
  if (Number.isFinite(viewWidth) && viewWidth > 0) {
    cap = Math.min(cap, Math.max(80, Math.floor(viewWidth - margin * 2)));
  }
  return Math.round(cap);
}

export function wrapTooltipText(text, maxWidthPx, {
  maxLines = TOOLTIP_MAX_LINES,
  fontSize = TOOLTIP_FONT_SIZE,
  padX = TOOLTIP_PAD_X,
} = {}) {
  const clean = String(text ?? '').replace(/\r\n?/g, '\n').trim();
  if (!clean) return { lines: [], text: '', truncated: false, longestEm: 0 };
  const innerW = Math.max(40, (Number.isFinite(maxWidthPx) && maxWidthPx > 0 ? maxWidthPx : TOOLTIP_MAX_WIDTH) - padX);
  const budgetEm = Math.max(4, innerW / fontSize);
  const limit = Math.max(1, Math.floor(maxLines || TOOLTIP_MAX_LINES));
  const rawLines = [];
  for (const para of clean.split('\n')) {
    const trimmed = para.replace(/\s+$/g, '');
    if (!trimmed) {
      if (rawLines.length && rawLines[rawLines.length - 1] !== '') rawLines.push('');
      continue;
    }
    const chars = Array.from(trimmed);
    let buf = [];
    let w = 0;
    let lastBreakIdx = -1;
    let lastBreakW = 0;
    for (let i = 0; i < chars.length; i++) {
      const ch = chars[i];
      if (!buf.length && (ch === ' ' || ch === '\t')) continue;
      const cw = charEmWidth(ch);
      if (buf.length > 0 && w + cw > budgetEm) {
        if (lastBreakIdx > 0 && lastBreakW >= budgetEm * 0.35) {
          const head = buf.slice(0, lastBreakIdx).join('').replace(/\s+$/g, '');
          const tail = buf.slice(lastBreakIdx);
          while (tail.length && (tail[0] === ' ' || tail[0] === '\t')) tail.shift();
          rawLines.push(head);
          buf = tail;
          w = measureEm(buf.join(''));
          lastBreakIdx = -1;
          lastBreakW = 0;
          for (let j = 0; j < buf.length; j++) {
            if (isBreakAfter(buf[j])) {
              lastBreakIdx = j + 1;
              lastBreakW = measureEm(buf.slice(0, j + 1).join(''));
            }
          }
          if (buf.length > 0 && w + cw > budgetEm) {
            rawLines.push(buf.join('').replace(/\s+$/g, ''));
            buf = [];
            w = 0;
            lastBreakIdx = -1;
            lastBreakW = 0;
          }
        } else {
          rawLines.push(buf.join('').replace(/\s+$/g, ''));
          buf = [];
          w = 0;
          lastBreakIdx = -1;
          lastBreakW = 0;
        }
        if (!buf.length && (ch === ' ' || ch === '\t')) continue;
      }
      buf.push(ch);
      w += cw;
      if (isBreakAfter(ch)) {
        lastBreakIdx = buf.length;
        lastBreakW = w;
      }
    }
    if (buf.length) rawLines.push(buf.join('').replace(/\s+$/g, ''));
  }
  while (rawLines.length && rawLines[rawLines.length - 1] === '') rawLines.pop();
  let truncated = false;
  let lines = rawLines;
  if (rawLines.length > limit) {
    truncated = true;
    lines = rawLines.slice(0, limit);
    const ellBudget = Math.max(2, budgetEm - 1.0);
    const chars = Array.from(lines[limit - 1]);
    while (chars.length > 0 && measureEm(chars.join('')) > ellBudget) chars.pop();
    lines[limit - 1] = `${chars.join('').replace(/\s+$/g, '')}…`;
  }
  const longestEm = lines.reduce((m, l) => Math.max(m, measureEm(l)), 0);
  return { lines, text: lines.join('\n'), truncated, longestEm };
}

export function clampTooltipRect(triggerRect, cardSize, boundsRect, {
  placement = 'above-left',
  gap = TOOLTIP_GAP,
  margin = TOOLTIP_MARGIN,
} = {}) {
  const wantBelow = String(placement || '').startsWith('below');
  const wantRight = String(placement || '').endsWith('right');
  const minX = boundsRect.x + margin;
  const maxX = Math.max(minX, boundsRect.x + boundsRect.w - cardSize.w - margin);
  const minY = boundsRect.y + margin;
  const maxY = Math.max(minY, boundsRect.y + boundsRect.h - cardSize.h - margin);
  const yAbove = triggerRect.y - gap - cardSize.h;
  const yBelow = triggerRect.y + triggerRect.h + gap;
  const fitsAbove = yAbove >= minY;
  const fitsBelow = yBelow <= maxY;
  const roomAbove = triggerRect.y - gap - minY;
  const roomBelow = (boundsRect.y + boundsRect.h - margin) - (triggerRect.y + triggerRect.h + gap);
  let vert = wantBelow ? 'below' : 'above';
  if (vert === 'above' && !fitsAbove && (fitsBelow || roomBelow > roomAbove)) vert = 'below';
  else if (vert === 'below' && !fitsBelow && (fitsAbove || roomAbove > roomBelow)) vert = 'above';
  const rawY = vert === 'below' ? yBelow : yAbove;
  const rawX = wantRight ? triggerRect.x + triggerRect.w - cardSize.w : triggerRect.x;
  const x = Math.round(Math.max(minX, Math.min(maxX, rawX)));
  const y = Math.round(Math.max(minY, Math.min(maxY, rawY)));
  return { x, y, w: cardSize.w, h: cardSize.h, placement: `${vert}-${wantRight ? 'right' : 'left'}` };
}

export function tooltipLayout(text, opts = {}) {
  const fontSize = opts.fontSize || TOOLTIP_FONT_SIZE;
  const lineHeight = opts.lineHeight || TOOLTIP_LINE_HEIGHT;
  const padX = opts.padX ?? TOOLTIP_PAD_X;
  const padY = opts.padY ?? TOOLTIP_PAD_Y;
  const maxLines = opts.maxLines || TOOLTIP_MAX_LINES;
  const gap = opts.gap ?? TOOLTIP_GAP;
  const margin = opts.margin ?? TOOLTIP_MARGIN;
  const maxWidth = tooltipMaxWidth(opts);
  const wrapped = wrapTooltipText(text, maxWidth, { maxLines, fontSize, padX });
  if (!wrapped.lines.length) return null;
  const width = Math.min(maxWidth, Math.max(TOOLTIP_MIN_WIDTH, Math.ceil(wrapped.longestEm * fontSize + padX + 10)));
  const height = Math.ceil(wrapped.lines.length * lineHeight + padY);
  const maxHeight = Math.ceil(maxLines * lineHeight + padY + 4);
  const placement = opts.placement || 'above-left';
  let anchor = 'bottom_left';
  let pos = { left: 0, top: -gap };
  if (placement === 'above-right') { anchor = 'bottom_right'; pos = { right: 0, top: -gap }; }
  else if (placement === 'below-left') { anchor = 'top_left'; pos = { left: 0, bottom: -gap }; }
  else if (placement === 'below-right') { anchor = 'top_right'; pos = { right: 0, bottom: -gap }; }
  const rect = opts.triggerRect && opts.boundsRect
    ? clampTooltipRect(opts.triggerRect, { w: width, h: height }, opts.boundsRect, { placement, gap, margin })
    : null;
  return {
    lines: wrapped.lines,
    text: wrapped.text,
    truncated: wrapped.truncated,
    width,
    maxWidth,
    height,
    maxHeight,
    fontSize,
    lineHeight,
    placement: rect ? rect.placement : placement,
    anchor,
    pos,
    rect,
  };
}

// ---- Render-cache invalidation signatures (pure, lossless for render memoization) ----------

export function pendingSignature(pending) {
  if (!Array.isArray(pending) || !pending.length) return '';
  let sig = String(pending.length);
  for (let i = 0; i < pending.length; i++) {
    const p = pending[i];
    if (!p) { sig += '\x1e'; continue; }
    sig += `\x1e${p.id ?? ''}\x1f${p.msgId || ''}\x1f${p.failed || ''}\x1f${p.queued ? 1 : 0}${p.serverQueued ? 1 : 0}${p.timedOut ? 1 : 0}${p.verifying ? 1 : 0}${p.inFlight ? 1 : 0}${p.upload ? 1 : 0}${p.received ? 1 : 0}\x1f${p.queuedReason || ''}\x1f${p.receiptAt || 0}\x1f${p.deliveredAt || 0}\x1f${p.sentAt || 0}\x1f${p.question || ''}\x1f${p.text || ''}`;
  }
  return sig;
}

export function hostLiveSignature(terms = [], live = [], tabs = []) {
  let sig = 'T';
  if (Array.isArray(terms)) {
    sig += terms.length;
    for (let i = 0; i < terms.length; i++) {
      const x = terms[i];
      if (!x) { sig += '\x1e'; continue; }
      const lb = x.labels;
      const pr = x.program;
      const rp = x.report;
      sig += `\x1e${x.address || ''}\x1f${x.state || ''}\x1f${x.status || ''}\x1f${x.turn || 0}\x1f${rp?.state || ''}\x1f${rp?.msg || ''}\x1f${rp?.message || ''}\x1f${x.cwd || ''}\x1f${contextTokens(x.context_tokens)}\x1f${pr?.key || ''}\x1f${pr?.name || ''}\x1f${pr?.icon || ''}\x1f${pr?.tint ? 1 : 0}${pr?.shell ? 1 : 0}\x1f${lb?.task || ''}\x1f${lb?.pm || ''}\x1f${lb?.['helper.of'] || ''}\x1f${lb?.helper || ''}\x1f${lb?.['helper.task'] || ''}`;
    }
  }
  sig += '\x1dL';
  if (Array.isArray(live)) {
    sig += live.length;
    for (let i = 0; i < live.length; i++) {
      const a = live[i];
      if (!a) { sig += '\x1e'; continue; }
      const pr = a.program;
      sig += `\x1e${a.address || ''}\x1f${a.status || ''}\x1f${a.tab || ''}\x1f${a.seq || 0}\x1f${a.title || ''}\x1f${a.app || ''}\x1f${pr?.key || ''}\x1f${pr?.name || ''}\x1f${pr?.icon || ''}\x1f${pr?.tint ? 1 : 0}${pr?.shell ? 1 : 0}`;
    }
  }
  sig += '\x1dB';
  if (Array.isArray(tabs)) {
    sig += tabs.length;
    for (let i = 0; i < tabs.length; i++) {
      const tb = tabs[i];
      if (!tb) { sig += '\x1e'; continue; }
      sig += `\x1e${tb.id || ''}\x1f${tb.name || ''}\x1f${tb.named ? 1 : 0}`;
    }
  }
  return sig;
}

export function windowControlButtons(win, { overlay = false } = {}) {
  if (overlay || win?.buttons !== true) return [];
  const isWindows = win.platform === 'windows';
  const maximized = win.maximized === true;
  return [
    {
      id: 'win-minimize',
      command: 'window.minimize',
      icon: isWindows ? 'mods/tabs/win-min.svg' : null,
      glyph: isWindows ? '' : '−',
      iconSize: 16,
      danger: false,
      labelKey: 'windowMinimize',
    },
    {
      id: 'win-maximize',
      command: 'window.maximize',
      icon: isWindows ? (maximized ? 'mods/tabs/win-restore.svg' : 'mods/tabs/win-max.svg') : null,
      glyph: isWindows ? '' : '□',
      iconSize: 16,
      danger: false,
      labelKey: maximized ? 'windowRestore' : 'windowMaximize',
    },
    {
      id: 'win-close',
      command: 'window.close',
      icon: isWindows ? 'mods/tabs/win-close.svg' : 'mods/pane/close.svg',
      glyph: '',
      iconSize: isWindows ? 16 : 13,
      danger: true,
      labelKey: 'windowClose',
    },
  ];
}

// ---- Right Sidebar Multi-Tab Workspace (docs/design/sidebar-multi-tabs.md) ---------------

export const SIDE_TABS_KEY = 'sideTabs';
export const SIDE_TABS_MAX = 12;
export const SIDE_TABS_MAX_PROJECTS = 20;

export function sideTabKey(spec) {
  if (!spec || typeof spec !== 'object') return '';
  if (spec.kind === 'doc') {
    const root = String(spec.root || '').trim();
    const path = String(spec.path || '').trim();
    return root && path ? `doc:${root}/${path}` : '';
  }
  if (spec.kind === 'thread') {
    const taskId = String(spec.taskId || '').trim();
    return taskId ? `thread:${taskId}` : '';
  }
  if (spec.kind === 'draft') {
    if (typeof spec.key === 'string' && spec.key.startsWith('draft:')) return spec.key;
    const id = String(spec.id ?? '').trim();
    const tab = String(spec.tab || 'library').trim();
    return id ? `draft:${tab}:${id}` : '';
  }
  return '';
}

// Compact strip label for thread tabs: shows `#NNN` when numbered so the full task title
// lives once in the detail header without duplicating across tab bar + header.
export function threadTabStripLabel({ number, title = '', taskId = '' } = {}) {
  const num = formatTaskNumber(number);
  if (num) return { text: num, compact: true };
  return { text: String(title || taskId || '').trim(), compact: false };
}

export function createSideTabsState() {
  return {
    tabs: [],
    activeId: null,
    lastActiveId: null,
    seq: 0,
  };
}

function normalizeTabState(state) {
  if (!state || typeof state !== 'object') return createSideTabsState();
  return {
    tabs: Array.isArray(state.tabs) ? state.tabs : [],
    activeId: state.activeId ?? null,
    lastActiveId: state.lastActiveId ?? null,
    seq: Number.isFinite(Number(state.seq)) ? Number(state.seq) : 0,
  };
}

function pickNextActiveAfterClose(remaining, removedIdx) {
  if (!remaining.length) return null;
  let best = null;
  let bestAt = -1;
  for (const t of remaining) {
    const at = Number(t.lastActiveAt) || 0;
    if (at > bestAt) {
      bestAt = at;
      best = t;
    }
  }
  if (best && bestAt > 0) return best.id;
  if (removedIdx < remaining.length) return remaining[removedIdx].id;
  return remaining[remaining.length - 1].id;
}

export function openSideTab(rawState, spec, {
  now = Date.now(),
  insertAdjacent = false,
  maxTabs = SIDE_TABS_MAX,
} = {}) {
  const state = normalizeTabState(rawState);
  if (!spec || typeof spec !== 'object') {
    return { state, tab: null, opened: false, activated: false, evicted: null, blocked: false };
  }
  const kind = spec.kind === 'thread' ? 'thread' : spec.kind === 'draft' ? 'draft' : 'doc';
  const nextSeq = state.seq + 1;
  const key = kind === 'draft'
    ? (spec.key || sideTabKey({ kind: 'draft', tab: spec.tab || 'library', id: spec.id ?? nextSeq }))
    : sideTabKey({ ...spec, kind });
  if (!key) {
    return { state, tab: null, opened: false, activated: false, evicted: null, blocked: false };
  }

  const existingIdx = state.tabs.findIndex(t => t.key === key);
  if (existingIdx >= 0) {
    const existing = state.tabs[existingIdx];
    const updated = {
      ...existing,
      ...(spec.title ? { title: String(spec.title) } : {}),
      ...(spec.threadTab ? { threadTab: spec.threadTab } : {}),
      ...(spec.mode ? { mode: spec.mode } : {}),
      missing: false,
      lastActiveAt: now,
    };
    const nextTabs = state.tabs.slice();
    nextTabs[existingIdx] = updated;
    return {
      state: {
        ...state,
        tabs: nextTabs,
        activeId: updated.id,
        lastActiveId: updated.id,
      },
      tab: updated,
      opened: false,
      activated: true,
      evicted: null,
      blocked: false,
    };
  }

  let nextTabs = state.tabs.slice();
  let evicted = null;
  const limit = Math.max(1, Number(maxTabs) || SIDE_TABS_MAX);
  if (nextTabs.length >= limit) {
    // Evict oldest clean non-active tab (LRU). If none, fall back to any clean tab.
    let evictIdx = -1;
    let oldestAt = Infinity;
    for (let i = 0; i < nextTabs.length; i++) {
      const t = nextTabs[i];
      if (t.dirty || t.id === state.activeId) continue;
      const at = Number(t.lastActiveAt) || 0;
      if (at < oldestAt) {
        oldestAt = at;
        evictIdx = i;
      }
    }
    if (evictIdx < 0) {
      for (let i = 0; i < nextTabs.length; i++) {
        const t = nextTabs[i];
        if (t.dirty) continue;
        const at = Number(t.lastActiveAt) || 0;
        if (at < oldestAt) {
          oldestAt = at;
          evictIdx = i;
        }
      }
    }
    if (evictIdx < 0) {
      return { state, tab: null, opened: false, activated: false, evicted: null, blocked: true };
    }
    evicted = nextTabs[evictIdx];
    nextTabs.splice(evictIdx, 1);
  }

  const id = `tab-${nextSeq}`;
  const baseTab = {
    id,
    key,
    kind,
    title: String(spec.title || (kind === 'thread' ? spec.taskId : spec.path ? fileName(spec.path) : '')),
    dirty: Boolean(spec.dirty),
    missing: false,
    lastActiveAt: now,
  };
  let newTab;
  if (kind === 'thread') {
    newTab = {
      ...baseTab,
      taskId: String(spec.taskId || ''),
      threadTab: spec.threadTab === 'session' ? 'session' : 'log',
      change: spec.change || createChangeState(),
      logExpanded: Boolean(spec.logExpanded),
    };
  } else if (kind === 'draft') {
    newTab = {
      ...baseTab,
      tab: spec.tab === 'memory' ? 'memory' : 'library',
      root: spec.root || (spec.tab === 'memory' ? 'memory' : 'docs'),
      path: '',
      mode: 'edit',
      shownBytes: DOC_INITIAL_BYTES,
      find: { open: false, query: '', jumpQuery: '', matchPos: 0 },
      editDraft: spec.editDraft || null,
      history: null,
    };
  } else {
    const docTab = spec.tab || (spec.root === 'memory' || spec.root === 'personal' ? 'memory' : 'library');
    newTab = {
      ...baseTab,
      tab: docTab,
      root: String(spec.root || ''),
      path: String(spec.path || ''),
      mode: spec.mode || 'read',
      shownBytes: Number(spec.shownBytes) > 0 ? Number(spec.shownBytes) : DOC_INITIAL_BYTES,
      find: spec.find || { open: false, query: '', jumpQuery: '', matchPos: 0 },
      editDraft: spec.editDraft || null,
      history: spec.history || null,
    };
  }

  if (insertAdjacent && state.activeId) {
    const activeIdx = nextTabs.findIndex(t => t.id === state.activeId);
    if (activeIdx >= 0) nextTabs.splice(activeIdx + 1, 0, newTab);
    else nextTabs.push(newTab);
  } else {
    nextTabs.push(newTab);
  }

  return {
    state: {
      tabs: nextTabs,
      activeId: newTab.id,
      lastActiveId: newTab.id,
      seq: nextSeq,
    },
    tab: newTab,
    opened: true,
    activated: true,
    evicted,
    blocked: false,
  };
}

export function activateSideTab(rawState, tabId, { now = Date.now() } = {}) {
  const state = normalizeTabState(rawState);
  const idx = state.tabs.findIndex(t => t.id === tabId);
  if (idx < 0) return { state, tab: null, activated: false };
  const updated = { ...state.tabs[idx], lastActiveAt: now };
  const nextTabs = state.tabs.slice();
  nextTabs[idx] = updated;
  return {
    state: {
      ...state,
      tabs: nextTabs,
      activeId: updated.id,
      lastActiveId: updated.id,
    },
    tab: updated,
    activated: true,
  };
}

export function showSideIndex(rawState) {
  const state = normalizeTabState(rawState);
  if (state.activeId === null) return { state };
  return {
    state: {
      ...state,
      activeId: null,
      lastActiveId: state.activeId || state.lastActiveId,
    },
  };
}

export function toggleSideIndex(rawState, { now = Date.now() } = {}) {
  const state = normalizeTabState(rawState);
  if (state.activeId !== null) return showSideIndex(state);
  if (!state.tabs.length) return { state };
  const targetId = state.tabs.some(t => t.id === state.lastActiveId)
    ? state.lastActiveId
    : pickNextActiveAfterClose(state.tabs, 0);
  if (!targetId) return { state };
  return activateSideTab(state, targetId, { now });
}

export function closeSideTab(rawState, tabId, { force = false, now = Date.now() } = {}) {
  const state = normalizeTabState(rawState);
  const idx = state.tabs.findIndex(t => t.id === tabId);
  if (idx < 0) return { state, closed: null, needsConfirm: null };
  const target = state.tabs[idx];
  if (target.dirty && !force) {
    const act = activateSideTab(state, tabId, { now });
    return { state: act.state, closed: null, needsConfirm: tabId };
  }
  const nextTabs = state.tabs.slice();
  nextTabs.splice(idx, 1);
  let nextActiveId = state.activeId;
  if (state.activeId === tabId) {
    nextActiveId = pickNextActiveAfterClose(nextTabs, idx);
  }
  let nextLastActiveId = state.lastActiveId;
  if (nextLastActiveId === tabId) {
    nextLastActiveId = nextActiveId || pickNextActiveAfterClose(nextTabs, idx);
  }
  return {
    state: {
      ...state,
      tabs: nextTabs,
      activeId: nextActiveId,
      lastActiveId: nextLastActiveId,
    },
    closed: target,
    needsConfirm: null,
  };
}

export function closeOtherSideTabs(rawState, keepTabId) {
  const state = normalizeTabState(rawState);
  const kept = [];
  const closed = [];
  const skippedDirtyIds = [];
  for (const t of state.tabs) {
    if (t.id === keepTabId) {
      kept.push(t);
    } else if (t.dirty) {
      kept.push(t);
      skippedDirtyIds.push(t.id);
    } else {
      closed.push(t);
    }
  }
  const hasActive = kept.some(t => t.id === state.activeId);
  const hasKeep = kept.some(t => t.id === keepTabId);
  const nextActiveId = hasActive ? state.activeId : (hasKeep ? keepTabId : (kept[0]?.id ?? null));
  const nextLastActiveId = kept.some(t => t.id === state.lastActiveId) ? state.lastActiveId : nextActiveId;
  return {
    state: {
      ...state,
      tabs: kept,
      activeId: nextActiveId,
      lastActiveId: nextLastActiveId,
    },
    closed,
    skippedDirtyIds,
  };
}

export function closeRightSideTabs(rawState, fromTabId) {
  const state = normalizeTabState(rawState);
  const fromIdx = state.tabs.findIndex(t => t.id === fromTabId);
  if (fromIdx < 0) return { state, closed: [], skippedDirtyIds: [] };
  const kept = [];
  const closed = [];
  const skippedDirtyIds = [];
  for (let i = 0; i < state.tabs.length; i++) {
    const t = state.tabs[i];
    if (i <= fromIdx) {
      kept.push(t);
    } else if (t.dirty) {
      kept.push(t);
      skippedDirtyIds.push(t.id);
    } else {
      closed.push(t);
    }
  }
  const hasActive = kept.some(t => t.id === state.activeId);
  const nextActiveId = hasActive ? state.activeId : fromTabId;
  const nextLastActiveId = kept.some(t => t.id === state.lastActiveId) ? state.lastActiveId : nextActiveId;
  return {
    state: {
      ...state,
      tabs: kept,
      activeId: nextActiveId,
      lastActiveId: nextLastActiveId,
    },
    closed,
    skippedDirtyIds,
  };
}

export function closeAllSideTabs(rawState) {
  const state = normalizeTabState(rawState);
  const kept = [];
  const closed = [];
  const skippedDirtyIds = [];
  for (const t of state.tabs) {
    if (t.dirty) {
      kept.push(t);
      skippedDirtyIds.push(t.id);
    } else {
      closed.push(t);
    }
  }
  const hasActive = kept.some(t => t.id === state.activeId);
  const nextActiveId = hasActive ? state.activeId : (kept.length ? pickNextActiveAfterClose(kept, 0) : null);
  const nextLastActiveId = kept.some(t => t.id === state.lastActiveId) ? state.lastActiveId : nextActiveId;
  return {
    state: {
      ...state,
      tabs: kept,
      activeId: nextActiveId,
      lastActiveId: nextLastActiveId,
    },
    closed,
    skippedDirtyIds,
  };
}

export function updateSideTab(rawState, tabId, patch) {
  const state = normalizeTabState(rawState);
  const idx = state.tabs.findIndex(t => t.id === tabId);
  if (idx < 0) return { state, tab: null };
  const prev = state.tabs[idx];
  const nextPatch = typeof patch === 'function' ? patch(prev) : patch;
  if (!nextPatch || typeof nextPatch !== 'object') return { state, tab: prev };
  const updated = { ...prev, ...nextPatch };
  const nextTabs = state.tabs.slice();
  nextTabs[idx] = updated;
  return {
    state: { ...state, tabs: nextTabs },
    tab: updated,
  };
}

export function upgradeDraftTab(rawState, draftTabId, { root, path, tab, title, now = Date.now() } = {}) {
  const state = normalizeTabState(rawState);
  const draftIdx = state.tabs.findIndex(t => t.id === draftTabId);
  const docTab = tab || (root === 'memory' || root === 'personal' ? 'memory' : 'library');
  const nextKey = sideTabKey({ kind: 'doc', root, path });
  if (draftIdx < 0 || !nextKey) {
    return { state, tab: null, mergedInto: null, removedDraftId: null };
  }
  const existingIdx = state.tabs.findIndex(t => t.id !== draftTabId && t.key === nextKey);
  if (existingIdx >= 0) {
    const existing = state.tabs[existingIdx];
    const merged = {
      ...existing,
      tab: docTab,
      root,
      path,
      title: title || existing.title || fileName(path),
      mode: 'read',
      dirty: false,
      editDraft: null,
      missing: false,
      lastActiveAt: now,
    };
    const nextTabs = state.tabs
      .filter(t => t.id !== draftTabId)
      .map(t => (t.id === existing.id ? merged : t));
    return {
      state: {
        ...state,
        tabs: nextTabs,
        activeId: merged.id,
        lastActiveId: merged.id,
      },
      tab: merged,
      mergedInto: merged.id,
      removedDraftId: draftTabId,
    };
  }
  const prev = state.tabs[draftIdx];
  const upgraded = {
    ...prev,
    kind: 'doc',
    key: nextKey,
    tab: docTab,
    root,
    path,
    title: title || fileName(path),
    mode: 'read',
    dirty: false,
    editDraft: null,
    missing: false,
    lastActiveAt: now,
  };
  const nextTabs = state.tabs.slice();
  nextTabs[draftIdx] = upgraded;
  return {
    state: {
      ...state,
      tabs: nextTabs,
      activeId: upgraded.id,
      lastActiveId: upgraded.id,
    },
    tab: upgraded,
    mergedInto: null,
    removedDraftId: null,
  };
}

export function cycleSideTab(rawState, delta = 1, { now = Date.now() } = {}) {
  const state = normalizeTabState(rawState);
  const len = state.tabs.length;
  if (!len) return { state, tab: null, activated: false };
  const curIdx = state.tabs.findIndex(t => t.id === state.activeId);
  const nextIdx = curIdx < 0
    ? (delta >= 0 ? 0 : len - 1)
    : ((curIdx + delta) % len + len) % len;
  return activateSideTab(state, state.tabs[nextIdx].id, { now });
}

export function readSideTabsStore(jsonText) {
  const empty = { v: 1, projects: {} };
  if (jsonText == null || String(jsonText).trim() === '') return empty;
  try {
    const parsed = JSON.parse(String(jsonText));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return empty;
    const rawProjects = parsed.projects;
    if (!rawProjects || typeof rawProjects !== 'object' || Array.isArray(rawProjects)) return empty;
    return { v: 1, projects: { ...rawProjects } };
  } catch (_) {
    return empty;
  }
}

export function hydrateProjectTabs(store, pmName, { maxTabs = SIDE_TABS_MAX, now = Date.now() } = {}) {
  const empty = createSideTabsState();
  if (!pmName || !store?.projects || typeof store.projects !== 'object') return empty;
  const entry = store.projects[pmName];
  if (!entry || typeof entry !== 'object' || !Array.isArray(entry.tabs)) return empty;
  const limit = Math.max(1, Number(maxTabs) || SIDE_TABS_MAX);
  const seen = new Set();
  const tabs = [];
  let seq = 0;
  for (const raw of entry.tabs) {
    if (!raw || typeof raw !== 'object') continue;
    if (raw.kind === 'draft' || raw.missing === true) continue;
    const kind = raw.kind === 'thread' ? 'thread' : raw.kind === 'doc' ? 'doc' : '';
    if (!kind) continue;
    const key = kind === 'thread'
      ? sideTabKey({ kind: 'thread', taskId: raw.taskId })
      : sideTabKey({ kind: 'doc', root: raw.root, path: raw.path });
    if (!key || seen.has(key)) continue;
    seen.add(key);
    seq += 1;
    const id = `tab-${seq}`;
    if (kind === 'thread') {
      tabs.push({
        id,
        key,
        kind: 'thread',
        taskId: String(raw.taskId || ''),
        title: String(raw.title || raw.taskId || ''),
        threadTab: raw.threadTab === 'session' ? 'session' : 'log',
        change: createChangeState(),
        logExpanded: false,
        dirty: false,
        missing: false,
        lastActiveAt: now - (entry.tabs.length - seq),
      });
    } else {
      const root = String(raw.root || '');
      const path = String(raw.path || '');
      const docTab = raw.tab || (root === 'memory' || root === 'personal' ? 'memory' : 'library');
      tabs.push({
        id,
        key,
        kind: 'doc',
        tab: docTab,
        root,
        path,
        title: String(raw.title || fileName(path)),
        mode: 'read',
        shownBytes: DOC_INITIAL_BYTES,
        find: { open: false, query: '', jumpQuery: '', matchPos: 0 },
        editDraft: null,
        history: null,
        dirty: false,
        missing: false,
        lastActiveAt: now - (entry.tabs.length - seq),
      });
    }
    if (tabs.length >= limit) break;
  }
  const activeKey = typeof entry.activeKey === 'string' ? entry.activeKey : null;
  const activeTab = activeKey ? tabs.find(t => t.key === activeKey) : null;
  const activeId = activeTab ? activeTab.id : null;
  const lastActiveId = activeId || (tabs.length ? tabs[tabs.length - 1].id : null);
  return { tabs, activeId, lastActiveId, seq };
}

export function serializeProjectTabs(store, pmName, rawState, {
  now = Date.now(),
  maxTabs = SIDE_TABS_MAX,
  maxProjects = SIDE_TABS_MAX_PROJECTS,
} = {}) {
  const base = store && typeof store === 'object' && store.projects && typeof store.projects === 'object'
    ? { ...store.projects }
    : {};
  const state = normalizeTabState(rawState);
  if (pmName) {
    const limit = Math.max(1, Number(maxTabs) || SIDE_TABS_MAX);
    const persisted = [];
    for (const t of state.tabs) {
      if (!t || t.kind === 'draft') continue;
      if (t.kind === 'thread') {
        persisted.push({
          key: t.key,
          kind: 'thread',
          taskId: t.taskId,
          title: t.title || t.taskId,
          threadTab: t.threadTab === 'session' ? 'session' : 'log',
          ...(t.missing ? { missing: true } : {}),
        });
      } else if (t.kind === 'doc') {
        persisted.push({
          key: t.key,
          kind: 'doc',
          tab: t.tab,
          root: t.root,
          path: t.path,
          title: t.title || fileName(t.path),
          ...(t.missing ? { missing: true } : {}),
        });
      }
      if (persisted.length >= limit) break;
    }
    if (persisted.length === 0) {
      delete base[pmName];
    } else {
      const activeTab = state.tabs.find(t => t.id === state.activeId && t.kind !== 'draft');
      base[pmName] = {
        activeKey: activeTab ? activeTab.key : null,
        updatedAt: now,
        tabs: persisted,
      };
    }
  }
  const projLimit = Math.max(1, Number(maxProjects) || SIDE_TABS_MAX_PROJECTS);
  const entries = Object.entries(base);
  if (entries.length > projLimit) {
    entries.sort((a, b) => (Number(b[1]?.updatedAt) || 0) - (Number(a[1]?.updatedAt) || 0));
    const pruned = {};
    for (const [k, v] of entries.slice(0, projLimit)) pruned[k] = v;
    return JSON.stringify({ v: 1, projects: pruned });
  }
  return JSON.stringify({ v: 1, projects: base });
}

// Estimates the rendered pixel width of an open detail tab in the unified 40px right-panel header.
export function estimateSideTabWidth(strip, { isActive = false, narrow = false } = {}) {
  const text = String(strip?.text || '');
  const compact = Boolean(strip?.compact);
  if (compact) {
    const textW = Math.ceil(text.length * 7.4);
    return Math.min(120, 15 + 12 + 5 + textW + (isActive ? 21 : 0));
  }
  let units = 0;
  for (const ch of text) {
    units += /[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe10-\ufe6f\uff01-\uff60\uffe0-\uffe6]/u.test(ch) ? 2 : 1;
  }
  const est = Math.ceil(units * 6.4) + 16 + 13 + 5 + (isActive ? 21 : 0);
  const minW = narrow ? 72 : 84;
  const maxW = narrow ? 124 : 156;
  return Math.max(minW, Math.min(maxW, est));
}

// Computes real tab overflow for the unified 40px right-panel header.
// Only reports overflow when the sum of tab widths genuinely exceeds available stripWidth;
// always keeps the active tab visible when overflowing.
export function computeSideTabOverflow({ tabs = [], activeId = null, stripWidth = 0, narrow = false, stripInfoOf = null } = {}) {
  const list = Array.isArray(tabs) ? tabs : [];
  if (!list.length) return { visibleIds: [], hiddenCount: 0, overflow: false };
  const gap = 3;
  const widths = list.map(tab => {
    const info = typeof stripInfoOf === 'function'
      ? stripInfoOf(tab)
      : { text: tab.title || tab.taskId || tab.path || '', compact: tab.kind === 'thread' };
    return estimateSideTabWidth(info, { isActive: tab.id === activeId, narrow });
  });
  const totalWidth = widths.reduce((sum, w) => sum + w, 0) + Math.max(0, list.length - 1) * gap;
  const avail = Number(stripWidth) || 0;
  if (avail <= 0 || totalWidth <= avail) {
    return { visibleIds: list.map(t => t.id), hiddenCount: 0, overflow: false };
  }
  const overflowBtnW = 44;
  const budget = Math.max(0, avail - overflowBtnW);
  const picked = new Set();
  let used = 0;
  const tryAdd = idx => {
    const w = widths[idx];
    const extra = picked.size > 0 ? gap + w : w;
    if (picked.size > 0 && used + extra > budget) return false;
    picked.add(idx);
    used += extra;
    return true;
  };
  const activeIdx = activeId ? list.findIndex(t => t.id === activeId) : -1;
  if (activeIdx >= 0) tryAdd(activeIdx);
  for (let i = 0; i < list.length; i++) {
    if (picked.has(i)) continue;
    tryAdd(i);
  }
  const visibleIds = list.filter((_, i) => picked.has(i)).map(t => t.id);
  const hiddenCount = Math.max(0, list.length - visibleIds.length);
  return { visibleIds, hiddenCount, overflow: hiddenCount > 0 };
}
