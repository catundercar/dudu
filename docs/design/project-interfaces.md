# Core Project Interfaces: Bringing Project Capabilities into Mods

> **Background**: On an unpublished prototype branch, dudu explored a standalone Go service paired with web and desktop frontends for its "Project" view. This design note works out how to bring the parts that can be computed purely by reading the ledger back onto `main` as plain Python modules invoked as subprocesses by Herdr mods, defining four clean interfaces along the way. Written in November 2026.
> **Status: Partially implemented.** `mods/pm-dash/skill/scripts/` now contains `pm_store.py` (`Store` / `FileStore`, with locked read-modify-write and atomic file replacement), `pm_project.py` (`Projects` read model, with review folding and status counts extracted out of `pm.py`), and `pm_sessions.py` (Claude Code session transcripts), along with `pm.py project events/log/session/context/file`; `load` / `save` / `mutate_task` in `pm.py` now delegate to `Store`. The branch diff view (`project change`) and a dedicated `Terminals` module are not yet implemented.

## Direction

- `main` is the mainline. The prototype `app` branch (`service/`, `web/`, `desktop/`) is shelved as reference material only and will not be merged into `main`.
- Capabilities from the prototype service that can be derived solely from the on-disk ledger are rebuilt in Python on `main`, placed flat beside `pm.py` in `mods/pm-dash/skill/scripts/` just like `pm_events.py`. Only design ideas and test cases carry over; no Go code is reused.
- Herdr mods are JavaScript and cannot call Python in-process: mods continue spawning `pm.py` subprocesses and reading JSON from stdout.
- **Files remain the single source of truth**, with the existing ledger directory layout unchanged and **no SQLite**. If SQLite is ever introduced later, it will strictly be a disposable index rebuildable from the files.
- **No long-running daemon processes are introduced.** Scheduled jobs are therefore out of scope for this design.
- Interfaces are invisible to users, so every slice (aside from write-safety plumbing and the Python half of session reading) must ship a user-visible capability, building only the interface methods that capability actually exercises rather than refactoring all of `pm.py` upfront.

## Four Interfaces

The signatures below are sketches; exact method names can be adjusted during implementation so long as module boundaries hold.

### Store: Ledger Reads and Writes (`pm_store.py`)

```python
class Store(Protocol):
    def registrations(self) -> list[dict]: ...                 # pms/*.json
    def registration(self, slug) -> dict | None: ...
    def change_registration(self, slug, change) -> dict: ...   # locked read-modify-write, atomic replace
    def tasks(self, slug=None) -> list[dict]: ...              # tasks/*.json
    def task(self, task_id) -> dict | None: ...
    def change_task(self, task_id, change) -> dict: ...        # locked read-modify-write
    def append_event(self, slug, event) -> int: ...            # returns byte offset
    def events(self, slug, before=None, after=None, limit=200) -> Window: ...
    def documents(self, slug) -> list[dict]: ...               # manifest of project context files
    def document(self, slug, root, path) -> str: ...           # body of a single file, read-only
```

- Only one implementation exists: `FileStore`.
- **Resolve paths dynamically from `pm.py` on every call; never compute ledger paths at import time.** Existing unit tests redirect the ledger to temporary directories by monkeypatching `pm.STATE`, `pm.TASKS`, and `pm.PMS`; workers on Windows pass `--home`, which is parsed after module import. Caching paths at import time would break both. Nor may `pm_store` import `pm` at top level (circular import).
- File locks wrap only the read-modify-write critical section, reusing `pm.py`'s existing `lock_file` / `unlock_file` (`flock` on Unix, `msvcrt` on Windows) with bounded wait timeouts. Each task gets its own lockfile under `locks/` in the ledger rather than locking the task JSON itself (renaming over a locked file fails on Windows). Regenerating `BOARD.md` and posting to Discord happen after releasing the lock. Temporary filenames include the PID so concurrent writers never collide.
- `retire` and `land` previously read a task once, ran slow subprocesses, and wrote the stale dict back — clobbering anything a worker logged during the minutes `land` spent running verification checks. Both must re-read inside `change_task` at the end. Review, escalate, reattach, and dispatch already re-read right before saving and map cleanly onto `change_task`.
- During migration, `load`, `save`, `all_tasks`, `pm_record`, `record`, and `conversation` become one-line forwarders to `Store` so **call sites stay untouched** and tests that patch those helpers keep working.
- `Store` covers only tasks, registrations, conversation events, and project documents. Inboxes, wait markers, lock helpers, sent briefs, and `config.json` remain in `pm.py`.

### Projects: Project Read Model (`pm_project.py`)

```python
class Projects:
    def __init__(self, store, sessions=None, live=None): ...   # live: snapshot of running terminals
    def list(self) -> list[Project]: ...
    def threads(self, slug) -> list[Thread]: ...
    def events(self, slug, before=None, limit=200) -> Window: ...
    def thread_log(self, task_id, before=None, limit=50) -> Page: ...
    def context(self, slug) -> list[Document]: ...
    def document(self, slug, root, path) -> str: ...
    def session(self, task_id, before=None, limit=50) -> Turns: ...
    def change(self, task_id) -> Change: ...
```

- **`pm.py` defines the business rules**: review-thread folding, "already answered", and "currently working" all follow `pm.py`'s existing logic. `folded_status` (previously a nested helper inside `dash_state`) is extracted first. Go structs from the prototype service are consulted only for field naming — that prototype counted raw statuses without folding review threads or filtering offline terminals, so **its counting logic must not be copied**.
- Offline detection, manager liveness, and "currently working" depend on whether terminals are alive, so methods computing them accept a live terminal snapshot (the same snapshot `dash_state` already gathers). Mods cannot see Herdr TUI panes directly; only `pm.py` can query them. Pagination (`events`, `thread_log`), Context, session transcripts, and branch diffs do not need a live snapshot.
- `Project` (slug, name, repo, archived flag) and `Coordinator` (terminal, session, runtime, rotation count) are separated at the Python/JSON interface while remaining stored together in `pms/<slug>.json` on disk without a schema migration.

### Sessions: Agent Session Transcripts (`pm_sessions.py`)

```python
class Sessions(Protocol):
    def transcript(self, session) -> Path | None: ...
    def context_tokens(self, session) -> int: ...
    def turns(self, session, before=None, limit=50) -> Turns: ...
```

- Transcripts live in each coding agent's own state directory rather than the dudu ledger. Task records and manager registrations already store session kind and ID; `find_session` (already used by `pm.py reattach`) locates Claude Code and Codex transcripts and serves as the starting point.
- Context token measurement generalizes `pm.py`'s existing `context_tokens` helper (originally run only on the manager session for the 200k handover warning) so any agent session can be measured.
- One adapter per agent kind, starting with Claude Code. **Transcript formats for Codex, agy, and other agents have not been verified here** — when a format is unsupported or unreadable, omit the metric cleanly rather than guessing.

### Terminals: Terminal Control (Future `pm_terminals.py`)

- Modeled on `Executor` from the prototype service: `labeled`, `get`, `send`, `keys`, `interrupt`, `kill`, `read`, `ended`, backed by two implementations: Herdr desktop terminals (`hc`) and Herdr TUI panes.
- **Not migrated wholesale in this pass.** Only terminal teardown (`end_terminal`, direct kill calls inside `retire`, and the delayed `close-worker` helper) needs consolidation now so "closed intentionally, reattachable" can record an explicit close marker.

## How Mods Read Data

- **Needed on every poll**: added as optional fields inside `pm.py state`. Mods check whether a field is present and fall back gracefully when talking to an older `pm.py` on a remote machine — no version handshake needed.
- **Needed only on demand**: exposed as new JSON-emitting subcommands:
  - `pm.py project events <slug> --before <offset> --limit <n>`
  - `pm.py project log <task> --before <n>`
  - `pm.py project context <slug>` and `pm.py project file <slug> <path>`
  - `pm.py project session <task> --before <n>`
  - `pm.py project change <task>` (not yet implemented)
- When a remote machine runs an older `pm.py`, unknown subcommands exit non-zero; the mod simply hides the corresponding UI affordance without surfacing an error banner.
- Write paths stay unchanged: project creation, archiving, restoring, and reattaching invoke `pm.py`; answering question cards and chatting still send text into the terminal.

## Capability Breakdown

| Capability | What the user sees | Interfaces & changes involved | Depends on |
| --- | --- | --- | --- |
| Scroll back earlier | Scroll past the latest 200 conversation events and 60 thread log entries in `pm-project` | Read half of `Store`; `Projects.events` and `thread_log`; `pm.py project events/log`; "Earlier" control in UI | — |
| Session transcripts (Python side) | Nothing visible yet | Claude Code adapter in `pm_sessions.py`; optional context-usage fields on managers and tasks in `state`; `pm.py project session` | — |
| Context panel | New `Context` tab on the right side of `pm-project`: project & personal memories, `decisions.md`, and `handover.md` readable as docs with in-panel search | `Store.documents` and `document`; `Projects.context`; `pm.py project context/file`; right-hand tab UI | Scroll back earlier |
| Write safety | Invisible to users; `land` stops overwriting concurrent worker updates | `change_task`, `change_registration`, atomic writes, per-task lockfiles; `retire` and `land` re-read before saving; legacy helpers forward to `Store` | Scroll back earlier, plus coordination with any concurrent write-path edits |
| Context usage & session UI | "Context 123k" beside managers and workers; `Session` tab inside thread detail | Mod-only changes (`pm-project`, `pm-list`) | Session transcripts, Context panel |
| Starting & recovering managers | Start icon when a manager is offline; one-click recovery for disconnected agents; intentionally closed workers labeled "Closed, reattachable" | Consolidate terminal teardown; record close timestamp & terminal ID on task; surface flag in `state`; UI controls | Write safety, Context usage UI |
| Unified status counts | "Waiting for you" and "Working" counts match everywhere | Extract `folded_status`; move counts into `Projects`; emit in `state`; delete duplicate JS counters across mods | Write safety, plus settling count definitions |
| Branch change view | Inspect a thread's commits and diff directly inside `pm-project` instead of opening a terminal to run `git diff` | `Projects.change`; `pm.py project change`; `Changes` tab in thread detail | Scroll back earlier, Starting & recovering managers |
| Project search | Filter threads, messages, and decisions within a project | Mod-only filtering over already-loaded data | Branch change view |

Because `pm-project`'s UI lives in two large files (`mods/pm-project/main.js` and `model.js`), UI slices should land serially, whereas pure Python slices can run in parallel alongside them.

## Implementation Pitfalls to Watch For

- **Do not exclude "intentionally closed" workers from offline handling.** A task remains open while its terminal was deliberately closed in only two cases: `workers.close_reported` (off by default) and `idle-workers --close`. Both previously appeared as `offline`, which is the exact state that exposes the reattach action in the UI. Keep them reattachable by adding a field on the task so the label reads "Closed" rather than introducing a separate ended-terminals registry file like the Go prototype had.
- **Keep `pm-project`'s client-side "answered" optimistic adjustment.** Right after a user submits an answer — before `pm.py` has observed the turn — subtracting it locally drops the bell badge immediately by design.
- **Duplication that can be deleted**: multiple JS copies of `foldReviews` and per-mod "waiting" counters, once every connected machine's `pm.py` emits the unified fields.
- **Duplication that cannot be deleted**: `LEDGER_HOME_SH`, `PM_SCRIPTS`, `terminalFor`, and `python.js`, because Herdr isolates mods from importing code across sibling mod directories.
- **Two copies of `pm.py` operate on the same ledger**: mods invoke the copy bundled under `mods/pm-dash/skill/scripts/`, while coding agents and hooks invoke the copy installed in the agent's skill folder. Locking guarantees hold completely only once both copies are updated.
- **Once `pm_store.py` exists, copying `pm.py` alone is no longer enough** (previously `pm.py` tolerated a missing sibling `pm_events.py`). Emit a clear error message if sibling modules are missing.
- **Add every new `test_*.py` file to `SKILL_EXCLUDED` in `mods/pm-dash/setup.py`** (and the corresponding bundle check in `tests/test_install.py`) so test files are not installed into user skill directories.
- **Leave `cache/remote-states.json` under the ledger untouched** — `pm-nav` owns that cache.
- Memory helpers (`memory_dir`, `memories`, `recall`) already exist on `main` and can be reused directly by the Context panel.

## Constraints

- Tests must never touch a real user ledger; enforce `assert_temporary_ledger` from `test_pm.py`. A past bug wiped real ledger data during a test run, so this rule is non-negotiable.
- Existing `test_pm.py` and `test_pm_events.py` suites must pass unmodified to prove behavioral compatibility.
- Do not delete, rewrite, or reorganize existing files in live ledgers as part of these interface additions.
- Projects hosted on connected remote machines must continue to work cleanly.
- UI actions use icons and direct interaction rather than cards with large text buttons.

## Open Questions

| Question | Affects | Recommendation |
| --- | --- | --- |
| Whose definition of "waiting for you" and "working" wins: `pm.py`'s (unclaimed blocked tasks excluded; `in_progress` and not offline counts as working) or the `pm-dash` board header's? | Unified status counts | Use `pm.py`'s definition, surfacing unclaimed blocked tasks as a separate line item in the overview |
| What triggers scheduled jobs? | Out of scope here | Defer: mod timers run per window copy and stop when the app quits, while a manager's `watch` is one-shot — neither is a suitable cron host |

## Unverified Assumptions

- Whether context token usage and turn transcripts can be parsed reliably from Codex and agy session files has not yet been verified.
- Understanding of Cursor's Context tab layout is based on its public documentation.
- Potential temp-file collision when two processes save the same task simultaneously was inferred by reading the code rather than reproduced live.
