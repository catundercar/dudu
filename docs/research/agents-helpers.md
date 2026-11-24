# Sub-agents: Presentation and Lifecycle of Thread Workers and Temporary Helpers in Herdr

> **Background**: This report examines how dudu's two kinds of sub-agents — thread workers that return commits, and temporary helpers that return written findings — are displayed, parented, and lifecycle-managed inside Herdr, as well as why workers "disappear" from Herdr's Agents list after a manager session rotates. Written in November 2026.
> **Status**: Research and design proposal. Commands such as `pm.py seat` and `pm.py helper` described below were proposed here and not yet implemented at the time of writing; the mechanism analysis is backed by controlled experiments.
> Any coding agent (Claude Code, Codex, pi, agy, …) can serve as the manager, a worker, or a helper; specific agents are named below only when discussing agent-specific behavior.

## Summary

### I. Why Workers Disappear (Measured)

1. **Workers have no panel by design.** Early on, each worker opened as an ordinary tab in the manager's space with no parent-child hierarchy; dispatch was later changed to spawn workers as sub-agents of the manager terminal via `--parent <manager> --outlive-parent --no-notify`. In Herdr, a sub-agent occupies no pane: it appears only in the sidebar Agents list as an indented child row beneath the manager, and clicking it opens a `peek` overlay rather than a panel.
   - Dispatch borrowed Herdr's sub-agent mechanism purely to nest workers visually under the manager, turning off both default helper behaviors: dying with the parent (`--outlive-parent`) and typing completion notices into the parent terminal (`--no-notify`).
   - "Open a real panel while remaining marked as a sub-agent" is called a *kept sub-agent* in Herdr: it gets its own tab while staying nested in its parent's tree. dudu already supports this via `"tabs": {"new_tab": true}` in `config.json` (off by default).
2. **After manager rotation, prior workers have nowhere to hang in the tree.** Herdr's Agents tree grows only beneath agents that currently own a pane.
   - `pm.py rotate` moves the manager to a new terminal. The old terminal is parked via `terminal.park` (which strips its `herdr.space` and `herdr.tab` labels) and then killed.
   - Workers dispatched before rotation still have `parent` pointing at that retired terminal, and `hc` provides no way to reparent a terminal after creation. As a result, those workers vanish from both the Agents sidebar and `herdr-app ls` — even while they continue running normally. Controlled reproduction confirmed the exact behavior.
3. **A regression in `pm-list`.** `pm-list` briefly carried logic to re-display pre-rotation workers under the current manager, then removed worker rows altogether on the assumption that Herdr's built-in Agents list already nested workers under the manager — an assumption that breaks across rotation. Consequently, pre-rotation workers appear nowhere in the sidebar, remaining visible only in the project view and board from ledger records; per code inspection, clicking them there peeks onto the current manager's tab (unverified live; see §5).
4. **Collapsing the sidebar to a narrow strip hides all child rows in the Agents list** (measured behavior of Herdr's built-in `agents` mod in narrow mode). Normal sidebar widths are unaffected.

**Additional empirical finding that shapes the design:** Closing a manager's pane or tab inside the Herdr app kills every worker beneath it — `--outlive-parent` does not prevent this because app-level `pane.close` / `terminal.kill` explicitly terminates a terminal together with its sub-agents. Closing a worker's own tab behaves the same way: no confirmation prompt appears, and both the worker and its helpers are killed. Only core-level termination (`hc kill`, which `rotate` uses) leaves `--outlive-parent` children alive.

### II. Recommended Design (One-Sentence Version)

Use a single underlying mechanism: every sub-agent is an `hc` child terminal of the agent that spawned it, carrying an identity label. Every behavioral difference between the two roles follows directly from **what it hands back**:

- A **thread** hands back **commits**: it owns a worktree and a ledger task, goes through review and merge, and lives until `retire`.
- A **helper** hands back **a written finding**: it has no branch, runs read-only, creates no ledger task, delivers its note to the agent that spawned it, and terminates when its parent agent ends.

Hierarchy relies solely on `hc`'s `parent` link — which requires **keeping the manager's terminal fixed**: rotation swaps only the process inside the terminal, never the terminal itself (referred to below as the **manager seat**). Controlled experiments confirm that when one program exits and the next starts inside the same terminal, both `--outlive-parent` workers and ordinary helpers remain alive and attached beneath it.

### III. Migration: Three Threads

1. **Thread 1 — Manager seat (Python):** rotation stops orphaning workers in the Agents tree.
2. **Thread 2 — `pm.py helper` (Python):** both managers and workers can spawn bounded, time-limited helpers.
3. **Thread 3 — UI (mods):** `pm-toast` recognizes helpers; board thread cards show a collapsed `"N helpers"` count; if on-demand tabs are chosen, add open-as-tab and park icons.

Threads 1 and 2 can run in parallel; Thread 3 follows Thread 2. Details in §3.

### IV. Decisions to Make

1. **How worker panels open** (options in §4.1). Recommended: **(b)** start as a single tree row by default, promote to a tab when clicked in the project view or board, and provide a "park" icon to fold it back into a row. Option **(a)** can already be tried today by setting `"tabs": {"new_tab": true}` in `~/.claude/pm/config.json` (opens a tab immediately on dispatch while keeping it nested under the manager).
2. **Switch rotation to the seat model.** Old and new sessions no longer overlap, leaving a few seconds with no active manager; if the new session fails to start, fall back to resuming the previous session (supported by Claude Code and Codex).
3. **Whether workers need manager approval before spawning helpers.** Recommended: no approval required, capped at 3 concurrent helpers per worker and defaulting to the `light` profile.

---

## 1. Evidence

Experimental setup: an isolated `hc` core (`HC_SESSION`) paired with an isolated Herdr app instance (matching `Check` in `tests/render_check.py`), running the repository's mods and `pm` layout against a copied ledger. Stand-in agents were shell scripts reporting state via OSC 7501 (`ESC]7501;state=<s>:app=<a>BEL` — colon-separated key-value pairs; semicolon separators or bare state words are ignored by `hc`). All test processes and state directories were cleaned up afterward.

| Step | Action | Observed result |
| --- | --- | --- |
| A | Manager in a tab; two workers spawned like `dispatch` (`--parent <manager> --outlive-parent --no-notify`); two ordinary helpers spawned under a worker | Three-level tree in the Agents sidebar: `manager → worker → helper`. `herdr-app ls` lists only workers under the manager's `sub_agents`; helpers are omitted from `ls` but rendered in the Agents tree |
| A2 | Spawn one worker with `herdr.space` + a fresh `herdr.tab` (`tabs.new_tab` path); run `terminal.keep {place:"tab"}` on the other | Both become full tabs while remaining in the manager's `sub_agents` (sub-agents with panes) |
| B | Shrink sidebar width to narrow strip (`76`) | Only pane-owning agents remain visible; all child rows disappear |
| C | `terminal.peek` on a worker | Opens a floating peek overlay over the current tab |
| D | Reproduce `rotate`: start new terminal with old terminal's space/tab labels, `pane.swap`, `terminal.park` old terminal, then `hc kill` | After `park`, old terminal retains only `pm.retired` and `where`; pre-rotation workers and helpers stay alive in `hc`, but vanish from `herdr-app ls` and the Agents sidebar; post-rotation workers nest normally under the new manager |
| E | Surface an orphaned worker via `terminal.keep right`, adding manager tab labels, then `terminal.park` | Both `keep` and tab labels turn it into a split pane inside the manager tab (bringing its helpers back too), but 2+ splits crowd the tab and duplicate row names in Agents; `park` strips `herdr.*` labels and hides it again |
| G | First program exits inside a terminal and second program starts (`sh -c 'A; exec B'`, matching the manager's current `zsh` wrapper) | Terminal ID stays unchanged; `--outlive-parent` workers and ordinary helpers remain alive and nested under it |
| F | Spawn helper with `--rm`; parent runs `hc wait --children all` | `wait` returns `{"terminal":"<terminal>","status":"done","ended":true}`; helper terminal is already removed (`not_found`); nothing is typed into parent terminal — findings must travel via files rather than `hc` |
| F | `hc kill` a worker | Its ordinary helpers terminate with it |
| F1 | Close manager's pane (`pane.close`) | Both `--outlive-parent` workers and their helpers under the manager terminate |
| F2 | Run `terminal.kill` on the manager | Same as F1 |
| H | Close a worker's tab (`tab.close`, without `confirmed`) | Closes immediately with no confirmation overlay (`overlays` empty); both the worker and its helpers terminate |

Read-only snapshots of a live workspace (`hc ls`, `hc get`, `herdr-app ls`) matched the controlled runs: post-rotation workers appeared as child rows under the current manager, whereas pre-rotation workers still pointed at dead `pm.retired` terminals and appeared nowhere in Herdr. In another active project, a single manager had over a dozen workers — several holding both child rows and tabs, with sub-agents of their own also holding both child rows and tabs — illustrating tab-bar sprawl firsthand.

Code and documentation basis:
- Herdr's built-in Agents list (observed behavior): the tree only grows beneath agents that have a pane; when the sidebar is collapsed to a narrow strip, child rows are not drawn.
- Herdr's mod documentation (the `AGENTS.md` shipped with `herdr-app`; see <https://herdr.dev>) notes that sub-agents belong to their parent terminal's tab without taking a pane of their own, and that ending a terminal (`terminal.kill`) ends its sub-agents along with it.
- `hc schema` exposes no method to reparent a terminal; the core docs state that `parent` is set once at start.

## 2. Design

### 2.1 Starting from Requirements

- Users need to see who is working, who is blocked, and click in when curious — without dedicating a permanent screen tile to every agent.
- The manager needs worker reports (currently written to the ledger and pushed via `deliver`).
- Whichever agent spawns a helper needs that helper's findings. Users rarely need to read raw helper output, but should see `"2 helpers running"` and be able to audit past helpers in the log.
- The fundamental distinction between the two sub-agent roles is **what they return** — commits vs. prose — and every row in the table below follows from that single distinction:

| Dimension | Thread worker | Helper |
| --- | --- | --- |
| Deliverable | Commits on a branch | Written findings in a file |
| Worktree / branch | Dedicated worktree & branch | None; runs read-only in its caller's directory |
| Ledger footprint | Full task JSON (as today) | No task created; appends a record inside the caller's task (or manager registration): name, terminal, start/end timestamps, output file, status |
| Review / merge | Reviewed and merged by manager | Not reviewed or queued for merge; the spawning agent evaluates its findings directly |
| Who can spawn | Manager (`pm.py dispatch`) | Manager or thread worker (`pm.py helper start`); helpers cannot spawn nested helpers |
| `hc` parent | Manager seat terminal (`--outlive-parent --no-notify`) | Spawning terminal (default lifecycle: dies with parent) |
| Lifetime | Until `retire` | Whichever comes first: findings collected, parent agent exits, or timeout |
| Deliverable recipient | Manager (`pm.py update` → event log → `deliver`) | Spawning agent (§2.4) |
| Labels | `task=<id>` | `helper.of=<task-id or pm-<project>>`, `helper=<name>` |
| Desktop toast | Suppressed (`notifications-pm-only`) | Suppressed |
| In Herdr | Child row under manager in Agents tree; tab policy per §4.1 | Child row one level below its caller; click to `peek`; never opens a tab |
| On the board | Thread card (as today) | Collapsed badge on caller's card: `"2 helpers running"` |

- **What if a helper needs to edit code?** Then its deliverable is a commit, making it a thread: specifically a child thread (`--parent <task>`) branched off and merged back into the parent thread's branch, dispatched exclusively by the manager (which owns the merge queue). When a worker wants parallel code edits, it asks the manager via the ledger.
- **Why helpers stay out of the task list**: they produce nothing to review or merge; listing them as tasks would clutter the board and inflate waiting counts.
- **Why helpers are still logged in the ledger**: auditability. Who ran, under what profile, and where their findings landed should remain visible in the thread log, with files as the source of truth and `hc` answering only whether a terminal is currently alive.

### 2.2 What Is Unified

`dispatch` and `helper start` share one terminal-spawning function parameterized by role, parent terminal, profile, brief, and labels. Profiles and agent binaries reuse `worker_argv`, so Claude Code, Codex, pi, and agy can all run as helpers, and brief injection reuses `send_when_ready`. Role determines just three things: `hc run` lifecycle flags (`--outlive-parent` and `--no-notify`), terminal labels, and where the ledger entry is written.

The entire design relies solely on `hc` (`run`, `parent`, `label`, `wait`, `send`), OSC 7501 status reporting, plain files, and shell commands runnable by any agent.

Only session resumption (seat fallback, `adopt`, `reattach`) depends on agent-specific capabilities: `find_session` currently locates Claude Code and Codex transcripts, degrading cleanly for other agent kinds to starting a fresh session from `handover` or the task brief (preserving functionality while losing unlogged in-memory context). Nothing depends on any agent's proprietary internal sub-agent tool (such as Claude Code's `Task` tool), which agents remain free to use for quick local lookups invisible to dudu; `pm.py helper` is for work that needs visibility, explicit collection, or a different model profile.

### 2.3 Manager Seat: Preserving Parent-Child Hierarchy Across Rotations

Because `hc` sets `parent` once at creation and Herdr grows its Agents tree only from pane-owning terminals, keeping the hierarchy intact requires **never replacing the manager terminal**.

**Mechanism**

- Run `pm.py seat <project>` as the foreground wrapper inside the manager terminal — occupying the exact slot currently held by `zsh -lic '"$@"; exec "$0" -li'`, not a background daemon.
- The loop runs the agent session; when that process exits, if `projects/<slug>/next-session.json` exists, it launches the next session in the same terminal with the handover prompt; otherwise it drops to an interactive shell just as today.
- `pm.py rotate` writes `handover.md` and `next-session.json`, then spawns `end-session` in the background (mirroring today's `end-retired`: waits for the current turn and any background shell jobs to finish, then terminates the agent process — never the terminal).
- If the new session exits within `N` seconds or never enters an active state, resumable agent kinds automatically resume the previous session (`claude --resume <id>`, `codex resume <id>`), while non-resumable kinds start fresh from `handover.md` and append a notice to the project conversation.

**Benefits**

- Every worker and helper keeps the exact same `parent` terminal across rotations (verified at the `hc` layer in Step G).
- The manager's terminal ID becomes a stable per-machine address for the project, eliminating target drift for notifications, focus jumps, and peeks.
- Deletes ~hundreds of lines of dual-terminal machinery (`start_in_place`, `take_place`, `pane.swap`, `terminal.park`, `pm.retired`, `never_started`) plus retired-manager workarounds in `focusPlan` across `pm-list`, `pm-dash`, `pm-project`, and `pm-toast` (retaining read-side compatibility briefly until legacy terminals age out).

**Trade-offs**

- Old and new sessions no longer overlap, leaving a few seconds without an active manager during rotation; keystrokes typed into the manager tab during that gap land in the seat wrapper and must either be buffered for the next session or discarded.
- Herdr TUI rotation (`rotate_herdr`) is out of scope here.

**Alternatives considered and rejected**

- Drawing a custom worker tree inside `pm-list` from ledger data: duplicates Herdr's Agents list (`pm-list` was intentionally scoped down to managers only) while leaving Herdr's own Agents list incomplete.
- Killing and resuming every active worker under the new manager during rotation: disrupts workers mid-turn; appropriate only for idle orphans during one-time migration (`adopt`).
- Opening every thread in its own tab: keeps workers visible, but still flattens the hierarchy into top-level rows after rotation (observed in Step D).

### 2.4 Returning Helper Results to the Caller

- `helper start` assigns a deterministic output path upfront: `<ledger>/projects/<slug>/helpers/<caller-task-or-pm>/<name>.md`.
- The generated brief ends with a fixed instruction: write findings to that file, then run `pm.py helper done`, which marks the ledger entry complete and notifies the caller according to role:
  - **Spawned by the manager**: appends an event to `conversation.jsonl`, riding the exact same `deliver` pipeline as worker reports so the manager receives it on its next idle turn without blocking or learning a second notification channel.
  - **Spawned by a worker**: sends `"helper X finished; findings at <path>"` via `hc send`, or lets the worker block synchronously on `pm.py helper wait`.
- `pm.py helper wait [--all|--any]` wraps `hc wait --children`, cross-checking ledger state and output files, enforcing timeouts, and killing finished helper processes via `hc kill` (leaving buffer history readable via `hc read`). Because `hc wait` reports only `done`/`ended` without payload text, findings always travel via the output file.
- If a helper finishes its turn without running `done` (`hc` transitions it out of `working`), `wait` still collects the result — reading the output file if written, or falling back to the last few dozen terminal lines.

### 2.5 Resource Limits and Runaway Prevention

- **Concurrency caps**: at most 3 concurrent helpers per caller (`helpers.max`) and at most 10 concurrent threads + helpers across a project (`helpers.project_max`), rejecting excess launches with a list of currently active runs.
- **Timeouts**: 30 minutes by default (`helpers.timeout`). With no background daemon, cleanup piggybacks opportunistically on `helper start` (reaping expired siblings first), `helper wait`, and routine `pm.py status` / `wait` calls, marking expired runs `timeout`.
- **Orphans**:
  - Helpers are ordinary child terminals and cannot outlive their parent terminal (verified: killing a worker or closing its tab kills its helpers).
  - Under a fixed seat terminal, workers are never orphaned by rotation. If the user closes the seat tab itself, Herdr terminates its workers too (Steps F1/F2), which the ledger marks "Closed, reattachable" for `pm.py reattach`.
- **Nesting depth**: capped at `manager → thread → helper` or `manager → helper`; `helper start` refuses callers carrying a `helper.of` label.
- **Cost**: helpers default to the `light` profile, with profile and runtime logged in the ledger.

### 2.6 How Users See Them

- **Herdr sidebar Agents list**: renders the native three-level `manager → thread → helper` tree (Step A), uninterrupted by rotation once `seat` lands. Narrow-sidebar hiding of child rows is upstream Herdr behavior and left unchanged.
- **Tabs (panels)**: per §4.1.
- **dudu board and project view**:
  - Thread cards show a collapsed helper count and highest-priority state (`"2 helpers running"`), listing names and result files on hover and peeking on click.
  - The central manager card shows helpers spawned directly by the manager.
  - Helpers never increment "waiting for you" or open-thread counters.
- **Notifications**: `pm-toast` currently suppresses toasts only when a terminal carries `task` or its immediate parent carries `pm` (`isWorkerNotice` in `mods/pm-toast/model.js`). A helper spawned by a worker satisfies neither.
  - Because Herdr emits completion notices for paneless sub-agents (which is why `pm-toast` added worker suppression in the first place), worker-spawned helpers would likely pop desktop toasts unless `isWorkerNotice` also checks `helper.of` and walks up the `parent` chain.

## 3. Path from Current State

**Step 0 — Manual recovery before code changes.**
- Pre-rotation workers still running can currently be opened only from thread rows in the project view (peeking onto the manager's tab).
- Left alone, they never return to the Agents tree before `retire`.
- Once idle, a manager can recover one into the tree via `hc kill` followed by `pm.py reattach <task>` (which requires the old terminal to be gone, resumes Claude Code / Codex sessions in a new child terminal under the current manager).

**Thread 1 — Manager seat (Python, `hard`).**
- Scope: `pm.py seat`, `next-session`, `end-session`, startup failure fallback; `claim` and `start` launch managers inside a seat; `rotate` performs one final legacy transition when upgrading an existing non-seat manager; `pm.py adopt <task>` moves idle orphaned workers under the seat (resuming Claude Code / Codex sessions, or prompting first for non-resumable agent kinds); retain read-side `pm.retired` handling; add `test_pm` coverage.
- Verification: live isolated-core run reproducing Step G.
- Outcome: workers stay nested under the manager across rotations, with no brief split-pane flash in the manager tab.

**Thread 2 — `pm.py helper` (Python, `standard` or `hard`).**
- Scope: `start`, `done`, `wait`, `ls`, `stop`; ledger entries; concurrency caps and opportunistic timeouts; terminal labels; `SKILL.md` and reference updates explaining when to use a helper vs. a child thread; `test_pm` coverage.
- Coordinates with the ledger write-safety work: helper records live on task JSONs and should route through `change_task` once available.
- Outcome: helpers appear beneath workers in the Agents tree and leave structured entries in thread logs.

**Thread 3 — UI (mods; requires `render_check.py`).**
- Scope: teach `pm-toast` about `helper.of`; display collapsed helper badges on thread cards in `pm-project` and `pm-dash`; if §4.1 picks (b), add open-as-tab (`terminal.keep {place:"tab"}`) and park (`terminal.park`) icons on threads.
- Scheduling: pairs naturally with the "Closed, reattachable" UI slice.
- Outcome: `"2 helpers running"` badges on cards, plus one-click promotion of any thread to a real tab and back.

Sequencing: Threads 1 and 2 touch disjoint functions in `pm.py` and can run in parallel (second to merge rebases); Thread 3 follows Thread 2. Choosing (a) in §4.1 replaces Thread 3's tab/park icons with flipping `tabs.new_tab`'s default and auto-parking tabs when a task enters `review`.

## 4. Decisions to Make

### 4.1 How Worker Panels Open

| Option | Behavior | Pros | Cons |
| --- | --- | --- | --- |
| (a) Open a tab immediately on dispatch, nested under manager | Equivalent to enabling `tabs.new_tab` today, optionally auto-parking back to a row when submitted for `review` | Most direct match for "open a panel marked as a sub-agent" | Tab bar grows crowded with many workers; clicking `×` on a tab kills the worker immediately without confirmation (Step H) |
| (b) Single row by default; open as tab on click (**recommended**) | Starts as a single row in Agents and on the board; clicking a thread in the board or project view promotes it to a focused tab, and a "park" icon folds it back without killing it | Tab bar holds only what you are actively inspecting; hierarchy stays intact | Takes one click to get a full panel; clicking child rows inside Herdr's own Agents list still opens `peek` (which offers its own "keep as tab" button) |
| (c) Keep status quo | Row + `peek` overlay only | Zero UI changes | Preserves today's "workers feel invisible" friction |

### 4.2 Switching Rotation to the Seat Model

If adopted: old and new sessions no longer overlap (leaving a brief gap of a few seconds), falling back to session resume or `handover` if the new session fails to launch.
Note on architecture constraints: `pm.py seat` runs for as long as the manager terminal stays open, occupying the exact process slot currently held by the interactive `zsh` wrapper — listening on no ports, managing no other projects, and exiting as soon as the terminal closes — so it respects dudu's "no background daemon" rule, though worth confirming explicitly.
If declined: keep dual-terminal rotation and accept that pre-rotation workers drop out of Herdr's Agents tree and remain reachable only via the project view and board.

### 4.3 Whether Workers May Spawn Helpers Without Asking the Manager

Recommended: allow without prior approval, bounded to 3 helpers per worker on the `light` profile and logged in the ledger. A stricter alternative is requiring workers to request helpers via the ledger for manager approval first.

Side note (not a decision): closing a manager's tab in Herdr kills all workers beneath it. That is built into Herdr's `pane.close` / `terminal.kill` semantics; dudu handles it by surfacing those tasks on the board as "Closed, reattachable".

## 5. Not Verified

- Live user-facing screenshots were not captured during the probe; post-rotation worker visibility in the Agents tree was established from layout state, `herdr-app ls`, and isolated reproductions, while queries against the live workspace were strictly read-only (`herdr-app ls`, `herdr-app status`, `hc ls`, `hc get`).
  - One additional practical reason workers can look "missing": in a short window where other sidebar mods take vertical space, the Agents list viewport can shrink to a few hundred pixels, requiring scrolling when many agents are open.
- Clicking an orphaned pre-rotation worker in the board or project view peeking onto the current manager's tab was inferred from `focusPlan` source rather than tested live.
- Whether Herdr pops native toasts for paneless helpers spawned by a worker was inferred from `pm-toast` code rather than triggered live.
- The seat mechanism was verified at the `hc` layer (swapping foreground processes inside one terminal preserves child hierarchy), whereas `pm.py seat` itself — prompt delivery across transitions and resume behavior across every agent kind — awaits live testing in Thread 1.
- Whether clicking a tab's visual `×` button invokes the exact same path as `herdr-app do tab.close` was tested via the command API rather than simulated mouse clicks.
