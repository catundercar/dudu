# Delivering Worker Reports to the Manager: Push (`deliver`) vs. Wait (`wait` / `watch`)

> **Background**: Once a worker logs a report — or stalls or exits — dudu needs to bring that update to the project manager's attention. Two mechanisms exist in the codebase: manager-driven waiting (`wait` / `watch`) and background push delivery (`deliver`). This note compares their reliability, token cost, and runtime trade-offs, and records the resulting recommendation. Written in November 2026.
> **Status: Recommendation partially implemented.** In `mods/pm-dash/skill/scripts/pm.py`, managers running inside the Herdr desktop app now use `deliver` (`pm.py wait` prints a hint that explicit waiting is unnecessary there); `deliver_batches` stays alive until the manager exits and wakes via `ChangeWaiter` on conversation log, registration, task file, and terminal state changes. Section 3 below preserves the recommendation as written at the time.

## 1. Two Mechanisms

**Wait (`wait` / `watch`).** The manager spawns a `pm.py wait` command per dispatched task (`cmd_wait` → `wait_for_report`), and in the Herdr TUI can also run `pm.py watch` (`cmd_watch`) on its inbox. Both block on `ChangeWaiter` in `pm_events.py`, which multiplexes two signal sources:

- `DirectoryEvents`: OS filesystem notifications paired with file-signature comparisons (`inode`, size, `mtime`) so atomic file replacements and overflowed notification queues are never missed;
- `hc events`: the Herdr terminal event stream, catching stalled workers within ~5 seconds, backed by a 60-second reconciliation sweep in case an event is dropped.

**Push (`deliver`).** The project's conversation log (`conversation.jsonl`) doubles as an event stream:

- On ledger writes, `wake_fields` checks whether an entry should wake the manager (for instance, someone moved a task to `review`, `blocked`, `done`, or `proposed`, or an assigned worker posted a report) and tags the event with `wake`;
- `deliver_later` ensures a background `pm.py deliver` process (`cmd_deliver`) is running for the project so the caller returns immediately without blocking on the manager;
- `deliver_batches` waits until the manager terminal is idle, coalesces all undelivered wake events into a single batch, sends them into the manager terminal, and advances the delivered cursor;
- When the manager's turn hook fires on that delivered batch, `took_delivery` deduplicates the message and marks the turn as responding to a delivery rather than a fresh user prompt.

## 2. Trade-offs

**Reliability and latency.**

- `wait` watches task files and terminal events directly, independent of the writer's `pm.py` version or agent hooks — its biggest strength. Worker crashes surface in ~5 seconds. Its weakness is operational: the manager has to remember to start a background `wait` for every task, which is easy to miss.
- `deliver` never forgets a task and merges updates into the manager's very next idle turn with near-zero delay. Its weaknesses at the time of writing: it relied on writers setting `wake` (older `pm.py` copies did not, which had caused dropped reports); for hookless agents (such as pi or agy), worker stalls went unnoticed; worker crashes were caught only on the next `sweep_exited` pass; and the background `deliver` daemon exited after 600 seconds of inactivity, stopping further pushes until something respawned it.

**Token cost and rotation.**

- `deliver` wins clearly: the manager spends zero tool calls waiting, simultaneous reports coalesce into one turn instead of trickling in across several turns, and session rotation is transparent to the delivery loop.
- `wait` burns tool-call tokens, wakes the manager separately as each wait exits, and has to be re-spawned across every manager rotation.

**Runtime environment.**

- Inside the Herdr desktop app (`hc`), prefer `deliver`: `hc send` holds back delivery whenever the user has an unsent draft typed in the terminal.
- Inside the Herdr TUI, terminal injection has no draft protection, so keep `wait` + `watch`.
- When pi runs as a worker (no stop hooks), pair `deliver` with `wait` as a fallback for stall detection; when pi runs as the manager, `deliver` spares it from needing background shell task tooling.
- On Windows, `deliver` avoids the orphaned inbox lock issue observed with `watch`.

## 3. Recommendation and Minimal Changes

Use `deliver` backed by a long-lived `ChangeWaiter` loop inside the Herdr desktop app, and keep `wait` + `watch` for the Herdr TUI. Four minimal changes close `deliver`'s reliability gaps:

1. Keep `deliver_batches` running for the lifetime of the manager session, watching task files, `conversation.jsonl`, and `hc events` together instead of timing out after 600 seconds;
2. Teach `pending_batch` to include manager-waking task mutations directly and tolerate legacy entries written without a `wake` flag;
3. Have `sweep_exited` convert stalls and exits of hookless workers into `stalled` notifications in real time;
4. Ensure the `deliver` process is alive during `cmd_claim`, `cmd_rotate`, and `cmd_dispatch` (keepalive).
