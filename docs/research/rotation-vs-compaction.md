# Manager Sessions: Rotation vs. Built-in Agent Context Compaction

> **Background**: dudu's project manager is a long-running coding agent session. In dudu's initial design, whenever the manager's context approached ~200k tokens, dudu terminated the session and handed the project over to a fresh session via `pm.py handover` ("rotation"). Written in November 2026, this report combines real ledger metrics, a comparison of compaction mechanics across four coding agents, and a controlled experiment to answer whether threshold rotation is the right everyday context-management mechanism.
>
> **Status**: **Implemented.** Automatic 200k-token rotation has been abolished and replaced by guided built-in context compaction (~200k–220k working set across Claude Code, Codex, and pi, with 150k idle pre-compaction on Claude Code) anchored by `PreCompact` retention rules and `SessionStart[compact]` live ledger sync (`pm.py handover --compact`). `pm.py rotate` is now reserved for crashes, model/agent switches, and explicit user requests (with transparent swap notices in place of silent takeover), `pm_sessions` / `pm.py` handle `isCompactSummary` and `compact_boundary` `postTokens`, and `handover` has been trimmed (pitfalls to worker briefs only, `--once` decisions preserved, 600/400-char limits).

---

## 1. Conclusions

### 1.1 Is Rotation a Good Design?

The question splits cleanly into two layers:

1. **The architectural invariant — "all project truth lives on disk, so the manager session is replaceable at any moment" — is sound and must be kept.**
   A project is a durable conversation (`conversation.jsonl` + `tasks/` + `decisions.md` + `memory/`); the running manager process is merely a replaceable executor attached to that state. Process crashes, machine reboots, switching models or agent CLIs (e.g. Claude Code to Codex), and project `archive` / `restore` all depend on this guarantee.
2. **Killing the active session at 200k tokens and replacing it via `handover` as routine context management is a mistake and should be retired.**
   - It conflates **crash recoverability** with **routine working-set garbage collection** — akin to restarting a database process every few hours just to evict memory caches.
   - In real ledger logs, an active project rotated 3 times in a single day, with each manager session surviving only 39–62 turns (~5–8 hours). Every rotation invalidated warm prompt caches, forced the replacement session to re-read files to rebuild its working set, and caused concrete user-facing failures: handover race conditions that dropped worker reports without telling the user, running workers falling out of the sidebar Agents tree as orphans, ~60-second stalls when a user prompt crossed the 200k line, and broken background `wait`/`watch` jobs in the TUI. Hiding dual-terminal swaps accumulated 650+ lines of transition and silent-turn machinery across `pm.py` and four UI mods.
3. **Two initial assumptions corrected during research:**
   - **"pi and agy cannot compact" is false.** Verified against official docs and released builds: Claude Code, Codex, pi, and agy all ship built-in automatic context compaction and manual `/compact`. Their real differences are **overly high default thresholds on 1M-context models (900k–983k)** and **varying external hook control** (agy currently exposes neither a configurable compaction threshold nor a `PreCompact` hook).
   - **"Raw unguided auto-compaction is enough on its own" is also false — compaction must be anchored to on-disk truth.** In our controlled experiment, raw `/compact` without hooks scored **5.5 / 8**: it preserved tacit context such as verbal agreements and rejected-option rationales better than handwritten handovers, yet truncated one rationale with an ellipsis and **held stale task state when external processes mutated the ledger on disk during compaction**. Pairing `PreCompact` (custom retention rules) with `SessionStart[compact]` (post-compaction injection of live on-disk active tasks) — **guided compaction** — scored **8.0 / 8** at ~11% lower total cost than rotation.

### 1.2 Recommended Design: Fixed Seat + Guided Compaction + Event-Driven Session Replacement

Factor manager lifecycle into three orthogonal layers:

| Layer | Mechanism | Trigger | Problem solved |
| --- | --- | --- | --- |
| **1. Container** | **Manager seat (`seat`)** | Created once when the project starts | Keeps terminal ID fixed so worker/helper trees never break; session replacement swaps only the child process inside the terminal |
| **2. Routine memory** | **Guided native compaction** | Working set reaches ~200k–250k tokens, or ~55 min idle | Keeps process and background watchers alive, preserves recent verbatim turns, compresses older history to ~15k tokens, and re-anchors to on-disk ledger state via hooks |
| **3. Recovery / switch** | **Explicit session replacement** | **Only on**: (1) crash/hang, (2) model or agent switch, (3) `archive`/`restore`, (4) explicit user request | Clean cross-session rebuild via serial restart inside the seat + `pm.py handover`, eliminating dual-terminal "pretend nothing happened" swaps |

**Per-agent context strategy when running as manager:**

1. **Claude Code**
   - Remove the `ROTATE_TOKENS` rotation prompt and explicitly cap the auto-compact window at 200k (`--autocompact 200k` or `"autoCompactWindow": 200000` in settings) so 1M-window models do not climb to ~967k re-reading nearly a million cached tokens every turn.
   - Keep `"idleCompaction": true` with `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS=150000`: when the user steps away for ~55 minutes (just before the 1-hour prompt cache expires), Claude pre-compacts in the background so the next user turn switches in 12–31 ms.
   - Register two lightweight hooks: `PreCompact` emits manager-specific retention instructions (verbal guardrails, why options were rejected, cross-task conditional promises, user communication preferences; discard verbose committed diffs and logs), and `SessionStart` (`matcher: "compact"`) runs `pm.py handover --compact` to inject only active/blocked task reports and unanswered prompts (~2–3 KB) so the summary never drifts from disk.
2. **Codex**
   - Pass `-c model_auto_compact_token_limit=220000 -c model_post_turn_compact_threshold_percent=80` (favoring end-of-turn compaction over mid-tool-chain compaction) and wire `compact_prompt` / `SessionStart` (`source: "compact"`) with the same retention rules and on-disk active snapshot.
3. **pi**
   - Set `compaction.keepRecentTokens: 20000` and cap the working set around ~220k via `compaction.modelOverrides`; optionally attach a tiny TypeScript extension on `session_before_compact` to inject on-disk truth.
4. **agy**
   - Ships automatic 1M-window compaction and `/compact <instructions>` while keeping background tasks and active sub-agents alive, but **currently offers neither a lower threshold setting nor a `PreCompact` hook**. When running agy as manager, either accept its native threshold or inspect transcript token usage in a `Stop` hook and send `/compact <retention instructions>` once idle past ~220k.

---

## 2. Decisions Proposed at the Time

1. **Replace 200k automatic rotation with guided auto-compaction for everyday context management?**
   Recommended and **adopted**: auto-compact Claude Code / Codex / pi around a 200k–250k working set (plus 150k idle pre-compaction on Claude Code) with `PreCompact` + `SessionStart[compact]` hooks, reserving `pm.py rotate` for manual, model-switch, or crash recovery use. Raising the rotation threshold to 400k–500k instead was rejected because it still periodically wipes tacit context and prompt caches.
2. **When a session genuinely does change, drop silent "pretend nobody switched" handovers (`quiet_turn`)?**
   Recommended: delete `quiet_turn` / `pm.quiet` / `takeover.json`. Once session switches are rare operational events, posting a single transparent system line in the project timeline (e.g. `"Manager session switched (model change / recovery); resumed from ledger"`) eliminates swallowed replies and silent stalls.
3. **Trimming `handover` output**
   Recommended: (1) scope worker engineering pitfalls out of manager `handover` into worker briefs only; (2) fix a bug where `pm.py decide --once` entries vanished completely from `handover` whenever a project had at least one memory file; and (3) widen truncation limits on active `review`/`blocked` task reports and recent conversation turns.

---

## 3. Evidence 1: Real Cost of Rotation and the Problems It Caused

### 3.1 Trigger and Handover Pipeline at the Time

- **Trigger (effective only on Claude Code)**: on every `UserPromptSubmit`, the hook scanned the tail of the session transcript, summed `input + cache_read + cache_creation` on the last mainline assistant turn, and injected a `"time to rotate"` reminder above `ROTATE_TOKENS` (default 200,000).
  - **Blind spot**: only Claude Code's transcript schema was parsed; Codex (`event_msg/token_count`), pi (`message.usage`), and agy (planner response usage) always returned `context_tokens == 0`, meaning **200k rotation never fired for any of those three agents**.
- **Desktop dual-terminal swap (`cmd_rotate`)**:
  1. Overwrote `projects/<slug>/handover.md` (wiping the previous manager's handwritten notes).
  2. Spawned a new session in place with a quiet-turn marker, wrote `takeover.json`, labeled the old terminal retired, and updated the manager registry.
  3. Waited up to 60 s for the new session to boot, spawned a background helper to swap and park the old pane, and waited up to 1 hour for background shells in the old session to finish before killing it.

### 3.2 Measured Cost Across 13 Real Rotations

Read-only measurements across 13 real rotations on an active project:

| Phase | First-turn takeover latency | First-turn API calls | Context after turn 1 | Cache creation | Cache reads | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Before startup slimming (9 rotations) | 12–165 s (plus one ~3 h hang) | 5–49 | 64.7k–100.8k (median 77.2k) | 50k–155k | 237k–3.97M | Reading `handover`, playbook, and coordination docs burned ~40% of the 200k budget on turn 1 |
| After slimming, no unanswered user message | 7–9 s | 4 | 40k–55k | 23k–34k | 130k–164k | Fast, but deferred reading playbook/templates to subsequent turns |
| After slimming, with unanswered user prompt | **~60 s** | 15 | 63k | 49k–53k | 815k–818k | When a user message crossed 200k, the user waited ~1 full minute for an answer |

**Hidden extra turn**: `pm.py rotate` told the outgoing session to finish its turn silently with no output, which caused Claude Code to re-prompt on empty output — burning an extra ~204k-token request inside the already-retired session.

### 3.3 Anatomy of `pm.py handover` Output

Running `pm.py handover` on a live project (~26.6 KB total):

| Section | Share | Issue exposed |
| --- | ---: | --- |
| Header | 1.3% | Fine |
| Memories (`MEMORY.md`) | **67.0%** | 75+ flat entries, mostly worker-only unit-test pitfalls re-read in full by every incoming manager |
| Decisions (`decisions.md`) | **0%** | Code skipped `decisions.md` whenever any memory existed — **hiding every temporary `decide --once` guardrail from `handover`** |
| Outgoing manager's note | 7.8% | Depended entirely on what the outgoing session remembered to jot down; overwritten on the very next rotation |
| Active tasks | 17.3% | Kept only the last 2 log lines per task hard-truncated at 100 chars, slicing off blocker details at the end of worker reports |
| Recent conversation | 6.4% | Kept 6 turns truncated to 120 chars (user) / 80 chars (manager); short replies like `"sounds good, do that"` lost the proposal being approved |

### 3.4 Incidents and Code Burden Directly Caused by Proactive Rotation

1. **Handover race dropping a user reply.** In a real incident, an outgoing session called `rotate` right after receiving a worker report — before relaying the result to the user — yet wrote `"just relayed to user"` in `handover.md`. Within seconds the incoming session read `handover.md` and ended its silent takeover turn. Over 4 seconds later, the outgoing session realized its mistake, updated `handover.md` too late, and printed its detailed summary to the already-retired terminal where the `Stop` hook discarded it. Neither session spoke to the user, leaving ~1.5 minutes of dead air until the user followed up.
2. **Running workers repeatedly vanishing from the sidebar Agents tree.** Because `hc` fixes a worker's `parent` terminal at creation time, retiring the old manager terminal orphaned every active worker out of the Agents tree (5 active workers orphaned at once in a single rotation).
3. **A long tail of rotation-only bugs**: swallowed startup prompt leaving a replacement session idle for ~1.5 hours; `quiet_turn` eating legitimate replies; premature termination of background jobs; and a custom delayed-delivery lock just to bridge rotation gaps.
4. **Retired sessions still triggering idle compaction.** At least 6 retired manager tabs stayed open long enough (~55 min) to trigger Claude Code's automatic idle compaction — paying for both the replacement session and a wasted compaction pass on the dead one.
5. **Cross-module complexity**: 650+ lines across `pm.py` and four UI mods (`pm-dash`, `pm-list`, `pm-project`, `pm-toast`) dedicated to dual-terminal swapping, retired-session filtering, and silent takeovers.

---

## 4. Evidence 2: Comparing Context Compaction Across Four Agents

Verified against official documentation and released builds in November 2026:

| Dimension | Claude Code | Codex | pi | agy |
| --- | --- | --- | --- | --- |
| **Auto-compaction** | Yes (threshold + `idleCompaction` before 1 h cache expiry) | Yes (mid-turn token limit + post-turn percentage threshold) | Yes (checked between tool batches + overflow retry) | Yes (automatic checkpoint summary near context limit) |
| **Manual compaction** | `/compact [instructions]` | `/compact` (TUI & app-server RPC) | `/compact [instructions]` | `/compact [instructions]` (TUI & `-p`) |
| **Default threshold on 1M models** | ~200k on 200k models; **~967k on 1M models**; `idleCompaction` ≥200k after ~55 min idle | ~90% of model window | `contextWindow - reserveTokens` (16,384 default) → **~983k** on 1M models | Near model window limit |
| **Configurable lower threshold?** | **Yes**: `--autocompact` (min 100k), `autoCompactWindow`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` | **Yes**: `model_auto_compact_token_limit`, `model_post_turn_compact_threshold_percent` | **Yes**: `compaction.reserveTokens`, per-model `compaction.modelOverrides` | **No**: no threshold setting exposed yet |
| **What survives compaction** | System prompt (cache preserved); root `CLAUDE.md`, rules, `MEMORY.md` (reloaded from disk); invoked skills; recently edited files; **last 3–4 verbatim messages**; **running background commands & subagents**; structured summary + transcript path | System instructions, `AGENTS.md`, tool definitions + structured summary | System prompt + structured summary (goals / constraints / progress / decisions / next steps / key context + touched files) + **recent `keepRecentTokens` (20k default) verbatim** | System instructions, loaded rules/skills/MCP + structured summary + deterministic snapshot (recent requests, background tasks, active subagents) |
| **Compaction hooks / custom instructions** | `PreCompact` (stdout sets summary instructions; can block), `PostCompact`, `SessionStart[compact]` (stdout injected post-compaction), `Compact Instructions` in `CLAUDE.md` | With hooks enabled: `PreCompact`, `PostCompact`, `SessionStart[compact]`, plus `compact_prompt` | No shell hooks, but TypeScript extensions handle `session_before_compact` (can customize or replace summary) and `session_compact_failed` | Supports `SessionStart` / `PreInvocation` / `PostInvocation` / `Stop`; **no `PreCompact` / `PostCompact` yet** |
| **Observable in on-disk logs?** | Yes: `compact_boundary` (pre/post tokens, duration, precomputed flag) & `isCompactSummary` | Yes: `token_count` events & compaction items | Yes: `type: "compaction"` entries | Yes: per-step token usage & checkpoint records |
| **Session resume CLI** | `claude --resume <id>` (wired in `pm.py`) | `codex resume <id>` (wired in `pm.py`) | `pi --session <id>` (not yet wired at the time) | `agy --conversation <id>` (not yet wired at the time) |

### 4.1 Claude Code Auto-Compaction in Real Sessions

Across 17 automatic compactions found in real transcripts:

- **Compression ratio**: at the 200k tier, ~204k–214k pre-compaction compressed down to a **12.6k–20.2k** summary (~92% history reduction). Including the system prompt, the next turn totaled ~63k–72k (~48k–52k on the slimmed startup base) — no larger than a fresh post-rotation session (55k–63k).
- **Prompt cache preservation**: compacting while the cache is still warm reads history at cached-input rates (~0.1x), and on the following turn the ~29k–33k system-prompt prefix remains a cache hit.
- **Near-zero perceived latency on idle pre-compaction**: idle compactions fired 55–56 minutes after the previous turn (just before 1-hour cache expiry), cutting user-visible switch time on the next prompt to **12–31 ms**.

### 4.2 Three Compaction Incompatibilities in Existing Code (Must Fix During Migration)

1. **Compaction summaries misparsed as user messages.** Claude Code writes compaction summaries as `type: "user"` with `isVisibleInTranscriptOnly: true` and no `isMeta` flag. Because transcript parsing filtered only `isMeta` and `isSidechain`, the UI rendered the entire multi-kilobyte summary as a user chat bubble and misidentified "the user's last message".
2. **Token counter scanning past `compact_boundary`.** Right after compaction, before a new assistant turn is logged, scanning backward from EOF crosses `compact_boundary` and reads the pre-compaction 208k count — falsely re-triggering high-token hooks. Backward scans must stop at `compact_boundary` and return its post-compaction token count.
3. **`SessionStart[compact]` skipped incremental sync.** Although the hook matched `compact`, it printed only `"run pm.py handover if you haven't read it yet in this session"`; because the compacted summary remembered reading `handover` at session start, the model never re-ran it, leaving external ledger updates made during compaction invisible.

---

## 5. Evidence 3: Rotation vs. Raw Compaction vs. Guided Compaction

### 5.1 Natural Control: Handwritten Rotation vs. Auto-Compaction on the Exact Same Session

One real ~204k manager session wrote a handwritten handover note and rotated to a new session; because its old tab stayed open, 78 minutes later that exact same session also ran automatic idle compaction. Comparing the two artifacts side by side:

- **Handwritten handover note (~2,100 chars) + `pm.py handover`**: preserved the active task queue and one promise to the user, but lost 9 resolved review-finding details from the session, a subtle shell-quoting trap, and background context explaining why not to file an upstream issue.
- **Auto-compaction summary of the exact same session (~8,700 chars + 4 verbatim recent messages)**: retained all 8 user decisions made during the session, related promises, all 9 review rework points, the shell-quoting trap, and the upstream-issue context, plus a pointer to the full transcript file on disk.

### 5.2 Controlled Experiment

Inside an isolated temporary `PM_HOME` and standalone terminal session, we constructed an 8-turn Claude Code (Opus) manager session (~58.6k tokens) seeded with: a formal logged decision, a verbal temporary deploy freeze (`decide --once`), measured OOM numbers behind a rejected design option, a cross-task conditional commitment, a user communication preference *and* its reason, a 3-step plan (>80 chars) approved by a terse `"let's do those three steps"`, and 360 lines of noisy health-check logs. An external process then flipped one task on disk to `blocked`, and the baseline session was forked three ways with tools disabled on the quiz turn to test pure working-memory fidelity:

| Quiz item | A: Rotation + `pm.py handover` | B: Raw `/compact` | C: Guided `/compact` (`PreCompact` + `SessionStart[compact]`) |
| --- | --- | --- | --- |
| Q1 Logged formal decision | Pass | Pass | Pass |
| Q2 Tail detail of a `review` report (past 100-char cutoff) | Pass (truncated in task list, rescued by handwritten note; lost on next hop) | Partial (recalled numbers, lost whether quoted verbatim from worker) | Pass |
| Q3 Verbal temporary deploy freeze (`decide --once`) | Pass (hidden by `handover` bug; rescued solely by handwritten note) | Pass | Pass |
| Q4 Technical reason an option was rejected | Pass (saved in `MEMORY.md`) | Pass | Pass |
| Q5 Cross-task conditional promise | Pass (rescued by handwritten note) | Pass | Pass |
| Q6 User communication preference *and* its rationale | Pass | Partial (rule kept, rationale truncated with `…` in summary) | Pass (`PreCompact` preserved full rationale) |
| Q7 Full 3-step plan behind terse user approval | Pass (step 3 truncated in both memory & recent chat; rescued by handwritten note) | Pass | Pass |
| Q8 External ledger mutation on disk during transition | Pass (spotted truncation in `handover` and queried disk) | **Fail** (reported stale pre-block status) | Pass (`SessionStart[compact]` synced live blocked state) |
| **Total score (out of 8)** | **8.0** (ideal single hop; 3 items relied on handwritten note that decays across hops or crashes) | **5.5** | **8.0** (zero manual note-writing; stable across single and multi-hop runs) |
| **Transition latency** | 21.3 s write + 7.1 s boot = 28.4 s (60 s+ on real projects with pending user message) | 39.3 s active (~0 ms perceived when idle-precompacted) | 31.7 s active, shorter summary (4,939 vs. 5,251 tokens); ~0 ms when idle-precompacted |
| **End-to-end cost** | $0.9910 | $0.9155 | **$0.8845 (lowest; ~11% cheaper than rotation)** |

### 5.3 Side-by-Side Comparison

| Dimension | Proactive 200k rotation (legacy) | Guided auto-compaction (recommended) |
| --- | --- | --- |
| **Tacit context & multi-turn reasoning** | Anything omitted from handwritten note is lost forever; notes overwrite on next rotation, decaying each hop | Structured iterative summary + recent verbatim turns + on-disk transcript fallback |
| **Consistency with on-disk ledger** | Fresh session reads disk (current, though truncated) | Live event delivery + `SessionStart[compact]` active-task refresh stays equally current |
| **Token & cache efficiency** | Invalidates all caches; extra ~204k empty-reply turn on old session; 55k–63k turn-1 boot plus re-reading docs | Keeps system-prompt cache warm; compacts at 0.1x cached read rate; never re-reads playbook docs |
| **User-visible disruption** | ~60 s stall when coinciding with a user prompt; history of swallowed replies and hung startups | Mostly invisible during idle windows (ms switch); ~30–45 s `Compacting…` indicator under heavy continuous chat, with zero cross-process race conditions |
| **Agents tree & background watchers** | Orphans active workers out of Agents tree; breaks TUI `pm.py wait` / `watch` and opens extra tabs | Same process, same terminal, same tab: parent-child tree and background watchers stay untouched |

---

## 6. Rollout: Completing On-Disk State, Relationship to Seat, and Migration Steps

### 6.1 Closing Gaps in On-Disk State

So neither compaction nor crash recovery ever drops context:

1. **Surface temporary decisions in `handover`.** `decide --once` guardrails must no longer be skipped when `MEMORY.md` is non-empty; `handover` (and `handover --compact`) should always include recent unmigrated decisions or active temporary guardrails rather than hoping an outgoing session writes them down by hand.
2. **Split memory injection by role (manager vs. worker).** Keep code/test pitfalls attached to worker briefs only, freeing the 67% slice of `handover` previously consumed by flat memories.
3. **Widen truncation limits on active reports and recent turns.** Expand latest reports on `review` / `blocked` tasks from 100 chars to ~600 chars, and recent 4–6 conversation turns to ~400 chars so short approvals retain their referent.
4. **Wire session discovery and resume for pi and agy.** Add `pi --session <id>` and `agy --conversation <id>` to `pm.py` so seat recovery, `reattach`, and `adopt` resume cleanly across all four agents.

### 6.2 How Guided Compaction Relates to Manager Seat

- **Orthogonal and mutually reinforcing — guided compaction dramatically lowers `seat`'s operational risk.**
  - `seat` keeps the manager's terminal ID fixed whenever a new session *does* have to start (crash recovery, model/agent switch, manual `rotate`), preserving worker parent-child trees.
  - Guided compaction eliminates the need to swap sessions every few hours at 200k tokens. `seat` shifts from a high-frequency switcher (with a multi-second input gap three times a day) to a rare crash/switch supervisor while one session runs continuously inside it.
- **Context-usage UI**: displaying `context_tokens` beside managers remains valuable (showing the working set grow and drop cleanly after compaction), provided the first two bugs in §4.2 are fixed alongside it.

### 6.3 Migration Steps

1. **Policy switch + compaction hooks + transcript parser fixes**
   - Remove the `ROTATE_TOKENS` auto-rotation reminder (keep `pm.py context` for inspecting working-set size).
   - Write `"autoCompactWindow": 200000`, `"idleCompaction": true`, and `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS=150000` into generated Claude manager settings; pass `model_auto_compact_token_limit=220000` and `model_post_turn_compact_threshold_percent=80` when launching Codex managers.
   - Register `PreCompact` → `pm.py hook-pre-compact` and `SessionStart` (`matcher: "compact"`) → `pm.py handover --compact` for Claude Code and Codex in `setup.py`.
   - Filter `isCompactSummary` / `isVisibleInTranscriptOnly` in session transcripts and stop backward token scans at `compact_boundary`.
   - Update `SKILL.md` and the playbook: replace proactive 200k rotation with routine auto-compaction (or manual `/compact` at natural milestones), reserving `pm.py rotate` for model switches, crashes, or user requests.
2. **Retire dual-terminal and silent-takeover machinery**
   - Once paired with `seat` and visible session-switch notices, remove `takeover.json`, `pm.quiet`, `quiet_turn`, and retired/quiet filtering branches across all four UI mods.

---

## 7. Not Yet Verified

- **End-to-end 200k auto-compaction runs on Codex, pi, and agy**: flags, hook protocols, and historical compaction entries were verified against official docs and real session files, while the controlled quiz experiment was executed on Claude Code (Opus) only.
- **Summary drift across a dozen+ consecutive compactions**: real transcripts confirmed healthy operation across 4 consecutive auto-compactions in a single session (~1.52M cumulative tokens discarded); multi-week sessions spanning 10+ compactions have not yet been stress-tested live, relying by design on `SessionStart[compact]` re-injecting on-disk truth after every pass.
