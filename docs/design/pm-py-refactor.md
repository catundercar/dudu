# Splitting `pm.py` into a Package: Domain Objects, IO Ports, and a Staged Migration

> **Background**: `mods/pm-dash/skill/scripts/pm.py` is the whole command line of the manager skill: the task ledger, dispatch, review, merge (`land`), event delivery to the manager, helpers, the manager's seat, rotation and compaction, memory and the Library, ledger-home migration and the conversation log. It has grown to 16,815 lines in one file. This note maps what is in it, proposes the structure it should have, lists what must not change for anything outside it, and lays out a migration in stages that can each be reviewed and merged on their own. Written in November 2026.
> **Status: Accepted, being implemented.** The user accepted the proposal and its recommendations on 2026-11-22; implementation runs stage by stage as child threads of the task that produced this note, each reviewed and merged on its own. As of midday on 2026-11-22, pass one (cutting the file into the package, section 4.1 rule 2) is on `main` except its last carves: the worker lifecycle, review and land, the deliverer loop and the hooks are in review; moving the commands out, splitting the parser and deleting `_legacy.py` are briefed and not started. `_legacy.py` is down from 16,867 lines to about 9,300, in 61 modules. Pass two (the objects) has not begun; its plan is a note of its own. Where a stage taught something that changes the plan, the text below says so. No code was changed for the note itself. Numbers come from an AST pass over `pm.py` at `d3138d8` and from the test files beside it; the compatibility shim in the migration section was prototyped on a toy package, not yet on the real test suite.
> In this note "manager" is the coordinating session (`pm` in code and file names).

## Summary

- **Target**: `scripts/pm.py` stays where it is and becomes a launcher of about 40 lines. The code moves into a package beside it, `scripts/pmlib/`, in five layers that only depend downwards: base → ports (files, terminals, git, processes, agent programs) → domain (ledger, project, caller, news policy, memory) → services (workers, review, land, delivery, manager session, helpers) → interface (CLI, hooks, JSON views).
- **Objects**: `Home` (the on-disk layout), `Store` (exists), `Ledger` and `Task`, `Project` and `Conversation`, `Caller` (who runs this process), `Terminals` (herdr-core or herdr TUI), `AgentKind` (Claude Code, Codex, pi, …), `Context` (the one place process-wide state lives). Rules are pure functions over these; IO goes through the ports, so a test passes a fake terminal host instead of patching 89 call sites.
- **Contracts**: the command line, every file in the ledger home, hook commands, what the mods run and read, the install layout, and `import pm` in the existing tests all keep working. The list is in [Contracts](#3-contracts-that-do-not-change).
- **Migration**: nine stages (0–8; stage 0 is two threads side by side). Stage 1 renames the file into the package and leaves a launcher, so every later stage is "carve one module out of `_legacy.py`"; the existing tests run unchanged through a forwarding shim until the last stage.
- **Two bugs fixed on the way** ([section 5](#5-two-bugs-fixed-on-the-way)), both before the refactor starts:
  - A worker's report on a task whose `pane` is the manager's terminal is never delivered when it does not move the status. Root cause: both the writer (`wake_fields`) and the reader (`is_news`) decide "is this the task's worker reporting" from the *task's* fields (`task.pane == writer` and `task.dispatched`) instead of from *who the writer is*.
  - `reattach` resumed a reviewer's session as the worker's. Root cause: `find_session` falls back to scanning the transcripts in the task's folders and picks one by the task id appearing in its text; a reviewer works in the same worktree and its transcript quotes the task. Nothing checks whose session it is, or that its agent kind is the worker's.
- **A parent task that closes itself** once all its child tasks are finished has a place in the model: `ledger/family.py` and one row in the reactions list (sections 2.3 and 2.5).

## 1. Where `pm.py` stands

### 1.1 Size

| | |
| --- | --- |
| `pm.py` | 16,815 lines, 642 top-level functions, 5 classes |
| Commands | 59 top-level, plus 17 under `project` and 5 under `helper` |
| Already split out | `pm_store.py` 2,347 · `pm_project.py` 1,362 · `pm_sessions.py` 1,132 · `pm_events.py` 437 (none imports `pm`) |
| Tests | `test_pm.py` 9,939 lines; seven more `test_pm_*.py`; about 510 test methods, all `import pm` |
| Exits and output | 246 `sys.exit(...)` and 311 `print(...)`, most of them inside functions other commands call |
| Largest functions | `build_parser` 553 · `cmd_update` 270 · `cmd_home` 250 · `cmd_helper_start` 241 · `cmd_land` 231 · `dash_state` 210 · `cmd_approve` 182 · `collect_research` 182 |

### 1.2 Responsibility areas

Lines are function bodies only, so they add up to less than the file. Each function was assigned to one of 48 candidate areas by reading it; the table groups those.

| Area | Lines | What is in it (real names) |
| --- | ---: | --- |
| Task ledger | 1,570 | `load`, `mutate_task`, `note`, `resolve_task_id`, `cmd_new`, `cmd_update`; plans (`parse_plan_steps`, `sync_plan_for_status`, `advance_outer_plan_step`); dependencies (`parse_depends_on`, `reconcile_dependencies`); question cards (`quick_answers`); `write_board`; `cmd_backfill_numbers`; `collect_research` |
| Project record | 470 | `pm_record`, `find_pm`, `hc_pm`, `registered_repo`; conversation log (`record`, `conversation_events`, `log_tail`); session bookkeeping (`remember_pm_session`, `remember_worker_session`, `task_session_info`) |
| Caller identity | 405 | `check_role`, `hc_role`, `identity_inventory`, `caller_identity`, `own_task`, `own_pm_record`, `own_registration`, `is_pm_caller`, `worker_task_for_hook`, `memory_writer`, `_helper_caller_identity` |
| Terminal hosts | 410 | `hc`, `herdr`, `hc_rpc`, `agents`; desktop tabs (`name_tab`, `rename_tab`, `worker_tab`, `tab_title`); screens (`screen_of`, `trust_keys`, `update_keys`, `classify_stuck_screen`) |
| Agent programs | 570 | `agent_kinds`, `agent_argv`, `worker_argv`, `launch_wrap`; profiles (`worker_defaults`, `profiles`, `ladder`); the Codex pool (`codex_pool`, `apply_codex_pool`, `hold_pool_lock`); briefs (`report_section`, `read_settings`, `keep_sent`) |
| Workers | 2,170 | `cmd_dispatch`, `dispatch_hc`, `register_worker`, `ask_first`; `send_when_ready`, `cmd_send`, `cmd__deliver_send`; `wait_for_report_events`; `close_worker`, `end_terminal`, `retire_workspace`, `cmd_idle_workers`; `cmd_escalate`; `cmd_reattach`, `reattach_plan`, `find_session`, `adopt_task` |
| Review and land | 970 | `cmd_review`, `review_brief`, `should_auto_review`, `run_auto_review`; `cmd_approve`, `cmd_land`, `run_checks`, `verify_land_caller`, `cmd_triage` |
| Events to the manager | 990 | `wake_fields`, `is_news`, `pending_batch`, `batch_text`, `deliver_batches`, `deliver_look`; stalls (`watch_workers`, `stop_state`, `round_starts`, `worker_stopped`); `cmd_notify`, `cmd_event`; herdr TUI inbox (`cmd_watch`, `watch_notifications`) |
| Manager session | 2,350 | `cmd_claim`, `cmd_start`, `cmd_archive`, `cmd_restore`; `cmd_seat`, `pop_next_session`; `cmd_rotate`, `build_fallback_spec`, `cmd_end_session`; `cmd_handover`, `handover_compact_text`; `lean_pm`, `codex_pm_compact`, `pi_pm_compact`; hooks (`cmd_hook_turn`, `cmd_hook_pre_tool`, `cmd_hook_session_start`, `record_taken_in`) |
| Memory and Library | 970 | `remember`, `read_memory`, `write_index`, `memory_block`, `forget_memory`, `restore_memory`, `adopt_memory_candidate`, `prune_candidates`; `cmd_decide`; `save_memory_file`, `cmd_project_edit`, `migrate_research` |
| Helpers | 1,540 | `cmd_helper_start`, `cmd_helper_wait`, `cmd_helper_done`, `finalize_helper`, `watch_helpers`, `reconcile_owner_helpers`, `helper_brief` |
| Read models | 690 | `dash_state`, `cmd_status`, `cmd_show`, `cmd_diff`, `cmd_project_session`, `cmd_dash` |
| Ledger-home migration | 740 | `cmd_home`, `inspect_ledger_home`, `active_ledger_writers`, `create_verified_backup` |
| Discord mirror | 190 | `post_board`, `discord_api`, `discord_mirror`, `write_mcp_config` |
| Command line | 560 | `build_parser`, `main` |
| Shared small things | 210 | `shell_quote`, `python_command`, `own_group`, `pid_alive`; `config`, `tr`; `git`, `project_root`, `git_state`; `now`, `default_home` |

The `# ----` section comments in the file no longer describe what is under them. The section headed "codex provider settings" holds `cmd_dispatch`, `config`, `tr`, the agent kinds and all screen-prompt recognition; the 2,486 lines under "memory" also hold the handover, the lean manager launch, the seat, `rotate`, `archive` and `restore`.

### 1.3 State every area shares

| What | Where it comes from | Reach |
| --- | --- | --- |
| `PANE`, `HC_TERMINAL`, `WORKSPACE` | read from the environment when the module is imported | `PANE` is read in 61 functions, `HC_TERMINAL` in 15 |
| `STATE`, `TASKS`, `PMS`, `PROJECTS`, `INBOX`, `BOARD` | `default_home()` at import; `--home` works by editing `sys.argv` and `os.environ` before the module body runs; tests reassign them | 32, 28, 13, 12, 7 and 3 functions |
| `STORE` | a `FileStore` built at import with a lambda that reads the globals above | 60 functions |
| `_PENDING_NOTES` | a module global that `mutate_task` sets so that `note()` calls inside the change are written to the conversation log after the task file is saved | an implicit transaction between two functions |
| `_IDENTITY`, `_SESSION` | caches of the herdr TUI identity inventory | reset by tests |
| `config()` and `tr()` | `config.json` read from `STATE` | 30 and 129 callers |
| Ad-hoc paths | 41 direct reads of `TASKS / f"{id}.json"` or `PMS.glob(...)` that bypass `STORE`; `project_dir(repo) / "<name>"` for 11 file names; `STATE / "<name>"` for 18 | the on-disk layout is spelled out in every area |
| Locks | per-task and per-registration locks in `locks/` (through `STORE`); `deliver.lock`, `delivered.lock`, `seat.lock` per project; `memory_lock`; `hold_pool_lock`; `watch_lock`; the helper-wait lock; the reattach lock (`stale_lock`) | each area builds its own lock path and calls `lock_file` itself |
| Its own path | `Path(__file__)` in 13 places: six background commands start `[sys.executable, <this file>, "<command>", …]` (`deliver`, `_deliver-send`, `_deliver-ready`, `close-worker`, `name-agent`, `end-session`), `pm_script()` is written into briefs and hooks, and `pm_pi_compact.js` and `assets/dash.html` are found relative to it | `script_mark()` watches `pm.py` and `pm_events.py` only |

### 1.4 The worst tangles

1. **Almost everything reaches almost everything.** In the reference graph between the 48 candidate areas, 38 form one strongly connected component: each can reach every other. Only `config`, `git`, the platform helpers, question cards, the TUI inbox, `notify`, the Library commands, memory-candidate adoption and the read models stay out of it. (The graph is by name, so a local variable that shadows a global adds a false edge here and there; the conclusion does not hang on those.)
2. **`cmd_update` is the hub.** In 270 lines it references 40 other top-level functions: it validates the question card, applies field changes, syncs the two-layer plan, decides who is woken (`wake_fields`), may start an auto-review (`run_auto_review`), collects research reports (`collect_research`), sends the note into the worker (`send_back`), retires the review and the worker (`retire_review`, `cmd_retire`, `close_later`, `close_worker`, `close_reported`), prunes memory candidates (`prune_candidates`), syncs the reviewed task's plan (`sync_plan_on_review_done`) and reconciles dependents (`reconcile_dependents_of`). Every feature that reacts to a status change is added here.
3. **"Who is calling?" has at least twelve answers.** `check_role`/`hc_role` (for `guard`), `is_pm_caller`, `own_pm_record`, `own_registration`, `current_pm_record`, `own_task`, `worker_task_for_hook`, `memory_writer`, `_helper_caller_identity`, `helper_self_info`, `blocked_by_worker` and `wake_fields` each derive the caller's role from `PANE`, registrations, task fields and terminal labels with rules of their own. The delivery bug in section 5 is two of these disagreeing with reality.
4. **Two terminal hosts, branched inline.** 116 lines test for herdr-core versus the herdr TUI (`in_tui()`, `app_caller()`, `startswith("hc:")`, `runtime == "hc"`, `HC_TERMINAL`); `hc("get", …)` alone is called at 52 sites, each reading the raw reply.
5. **Agent kinds, branched inline.** 116 comparisons on the agent kind decide the argv, whether it takes a prompt, how it resumes, how it compacts, whether it has a Stop hook, where its transcripts are.
6. **Low-level functions call upwards.** `mutate_task` → `write_board` → `post_board` (a Discord REST call on the ledger write path); `hc_pm` → `seat_alive`; `name_tab` → `tabs_cfg`; `reconcile_dependencies` → `deliver_later`; `deliver_look` → `watch_helpers`, `reconcile_dependencies`, `next_session_ready`; `task_session_info` → `dispatched_with`, `session_score` (the reattach code).
7. **Commands call commands through fake arguments.** 13 places build an `argparse.Namespace` to call another `cmd_…` (`cmd_update` → `cmd_retire`, `cmd_land` → `cmd_update`, `register_worker` → `cmd_new`, `run_auto_review` → `cmd_review`, `cmd_approve` and `cmd_triage` → `cmd_helper_start`, `cmd_start` → `cmd_claim`, `cmd_restore` → `cmd_start`). The parser's defaults are thereby part of an internal API, and a callee's `sys.exit` is the caller's control flow: `deliver_batches` catches `(Exception, SystemExit)` to survive one.
8. **Tests are coupled to module globals.** The suite patches `pm.hc` 89 times, `pm.PANE` 49, `pm.HC_TERMINAL` 30, `pm.end_terminal` 21, `pm.deliver_later` 19, `pm.agents` 19, `pm.herdr` 18, and over a hundred other names. Any move of a function changes what such a patch reaches.

### 1.5 A cost that comes with the single file

Python does not cache the bytecode of the script it is started with, so every `python3 pm.py …` compiles 16,815 lines again. Measured on this machine (Python 3.14): `pm.py hook-pre-tool` takes 0.17 s as a script, `import pm` with a cached `.pyc` takes 0.06 s, bare `python3` 0.02 s. About 0.11 s of every invocation is compilation, and `hook-pre-tool` runs before every question tool call, `hook-turn` twice per turn. A launcher that imports a package gets that back with no other change.

## 2. Target structure

### 2.1 Principles

1. **Files stay the source of truth**, in the layout they have today. No database, no new long-running process.
2. **Dependencies point one way.** Five layers; a module imports only from its own layer or below. A test parses the imports and fails on a violation, so the structure cannot erode silently.
3. **Rules are separate from IO.** What is news, what a status change means for a plan, whether dependencies are met, who may write a memory: pure functions over plain data. Reading files, calling `hc`, running git and starting processes go through a small set of ports.
4. **One answer per question.** One `Home` knows the layout, one `Caller` knows who is calling, one `Terminals` port talks to the host, one `AgentKind` per agent program.
5. **Commands are thin.** A command parses arguments, calls a service, prints. Services raise exceptions; only the command line turns them into exit codes. Services call services, never commands.
6. **Process-wide state lives in one object** (`Context`), built once in `main()` from the environment and `--home`, and passed down.
7. **Standard library only**, Python 3.9 and later (what `pm.py` needs today: it uses `Path.is_relative_to`), Windows included.

### 2.2 Layout

```text
mods/pm-dash/skill/scripts/
  pm.py                    launcher: UTF-8 re-exec on Windows, clear error when pmlib is missing, pmlib.cli.main()
  pm_pi_compact.js         unchanged (finds pm.py beside itself)
  pmlib/
    cli.py                 main(): build Context, assemble the parser, map errors to exit codes
    context.py             Context, Clock, Output
    errors.py              PmError and its kinds (Refused, NotFound, IdentityError, …)
    osutil.py              shell_quote, python_command, own_group, pid_alive, stop_group
    config.py              Config (config.json), tr()

    home.py                Home, ProjectFiles: every path in the ledger home, and nothing else
    store.py               FileStore, locks, atomic writes                      (today pm_store.py)
    gitrepo.py             Git: roots, branches, worktrees, merge, state
    terminals/
      base.py              Terminals protocol, Terminal handle, TerminalInfo
      hc.py                herdr-core (desktop app)
      tui.py               herdr terminal UI panes
      tabs.py              desktop tab names
      screen.py            reading a screen: trust and update prompts, stuck classification
      events.py            ChangeWaiter, DirectoryEvents                        (today pm_events.py)
    procs.py               Processes: start a pm.py command in the background, the code mark
    agents/
      base.py              AgentKind protocol, registry by name
      claude.py codex.py pi.py generic.py
      profiles.py          profiles, worker and reviewer defaults, the ladder
      codex_pool.py
      sessions.py          transcripts, context size, finding a task's session  (today pm_sessions.py + find_session)

    ledger/
      task.py              Task: a view over the task record, status sets, refs (#N)
      ledger.py            Ledger: load, change (locked), entries; board after save
      plan.py              two-layer plans: parse, progress, what a status change does to them
      deps.py              depends_on: parse, cycle check, evaluate
      question.py          question cards: options, recommended, answered
      family.py            parent and child tasks: the children of a task, what their states mean for the parent
      numbers.py           task numbers and backfill
    project/
      project.py           Project, Coordinator (the registration), registry lookups
      conversation.py      Conversation: append, read after an offset, tail
    caller.py              Caller: terminal, labels, role in a project — the only place that decides it
    events/
      policy.py            what is news, what wakes the manager, the pending batch (pure)
      deliver.py           the deliverer loop, the batch text, delivered marks
      stalls.py            rounds, stop states, stall events
      inbox.py             herdr TUI inbox and watch
      notify.py            notify, event
    memory/
      layer.py             MemoryLayer (project, personal): read, remember, forget, history, index
      candidates.py        workers' own memory waiting to be adopted
      decisions.py
      dream/               reserved: background consolidation (section 6)

    workers/
      dispatch.py          start a worker: placement, worktree, brief, registration
      brief.py             report section, outside reads, sent/<id>.md
      send.py              send when ready, background sends
      wait.py
      lifecycle.py         close, end terminal, retire, idle workers
      escalate.py
      reattach.py          offline tasks: resume or start fresh, adopt
      research.py          collecting evidence reports
    review/
      review.py            reviewer start, brief, auto-review
      land.py              approve, land, checks, triage
    reactions.py           what follows a task's status change, as one ordered list (section 2.5)
    manager/
      claim.py             claim, start, archive, restore
      seat.py              the seat process and its state
      rotate.py            rotate, end-session, fallback
      launch.py            the manager's command: narrow, lean, compaction per agent kind
      handover.py
    helpers/
      service.py           start, done, stop, finalize, reconcile
      watch.py             what the deliverer does for helpers
    library.py             Library and Memory page edits, research migration
    homemove.py            ledger-home inspection and migration
    discord.py

    hooks.py               hook-session-start, hook-pre-compact, hook-pre-tool, hook-turn
    views/
      state.py             `state` (dash_state)
      project.py           Projects read model                                  (today pm_project.py)
      status.py            status, show, board, diff, find, log
      dash.py              the browser board
    commands/              one file per area: argument declarations and thin cmd_ adapters
  tests/                   one test file per module; fakes for Terminals, Git, Processes, Clock
```

Layers, bottom to top:

| Layer | Modules | May import |
| --- | --- | --- |
| 0 base | `errors`, `osutil`, `config`, `context` | standard library |
| 1 ports | `home`, `store`, `gitrepo`, `terminals/`, `procs`, `agents/` | 0 |
| 2 domain | `ledger/`, `project/`, `caller`, `events/policy`, `memory/` | 0–1 |
| 3 services | `events/` (the rest), `workers/`, `review/`, `reactions`, `manager/`, `helpers/`, `library`, `homemove`, `discord` | 0–2, and each other only along the arrows below |
| 4 interface | `cli`, `commands/`, `hooks`, `views/` | everything |

Within layer 3: `workers` ← `review` ← `reactions`; `events` ← `workers` (a dispatch makes sure the deliverer runs); `helpers` ← `review` (delegated land and triage run as helpers); `manager` uses `workers` and `events`. The deliverer needs helpers and dependencies each look (`deliver_look` → `watch_helpers`, `reconcile_dependencies`): those register themselves as *watchers* with the deliverer instead of being imported by it, which is what breaks today's cycle.

The package is named `pmlib`, not `pm`: a package `pm/` beside `pm.py` would make `import pm` mean the package, and through the migration `import pm` must keep meaning the module the tests know. The name is cheap to change before stage 1.

### 2.3 Core objects

| Object | Owns | Replaces |
| --- | --- | --- |
| `Home` | The ledger home and every path in it: `home.task(id)`, `home.registration(slug)`, `home.project(slug)` → `ProjectFiles` (`conversation`, `delivered`, `deliver_lock`, `seat_state`, `next_session`, `memory`, `helpers`, `verify`, …), `home.inbox(name)`, `home.sent(id)`, `home.waits`. Paths only, no IO. `Home.from_env(home_option)` applies today's rule (`PM_HOME`, else an existing `~/.claude/pm`, else `~/.dudu`). | `STATE`, `TASKS`, `PMS`, `PROJECTS`, `INBOX`, `BOARD`, `project_dir`, 70 hand-built paths |
| `Store` (`FileStore`) | Locked, atomic reads and writes of tasks, registrations, the conversation log and documents. Exists; takes a `Home` instead of a lambda over globals. | the 41 direct file reads |
| `Task` | A view over one task record that **keeps the record as it is** (unknown fields survive: other `pm.py` versions write the same files). Properties and rules: `status`, `is_open`, `terminal`, `review_of`, `started_by_manager`, `number`, `ref`, `plan`, `depends_on`, `question`. | `hc_terminal_of`, `pm_started`, `task_ref`, `needs_cleanup`, status lists |
| `Ledger` | `load(ref)`, `tasks(project)`, and `change(task_id, fn)`: the locked read-modify-write. `fn` gets a `Change` with the task and `change.note(text, **fields)`; the entries go to the conversation log after the save. | `load`, `save`, `mutate_task`, `note`, `_PENDING_NOTES` |
| `Plan`, `Dependencies`, `Question` | Value objects with the rules that are pure today but scattered: what a status change does to plan steps, whether dependencies are met and the key that deduplicates the notice, which options a card offers. | 45 functions in the plan, dependency and question-card areas |
| `Family` | A task with its children (`parent` on the child, as on disk today): `children`, a summary of their states, and `rollup()` — what the children's states mean for the parent. Pure: it returns a proposed change (close the parent, or tell the manager), and `reactions` applies it. Today the relation is only displayed (`task_children_map`, `format_children_summary` in `status`, `show` and the handover); nothing acts on it, so a parent whose children have all finished stays open until someone closes it by hand. | `parent_of`, `task_children_map`, `format_children_summary` |
| `Project`, `Coordinator` | The project (slug, repo, archived) and its manager registration (terminal, runtime, seat, session, previous terminal, helpers). Split in code as `project-interfaces.md` already proposes; one file on disk as today. | `pm_record`, `find_pm`, `hc_pm`, `app_pm`, `pm_panes`, `registered_repo` |
| `Conversation` | The project's event log: `append(type, **fields)`, `after(offset)`, `tail(n)`. | `record`, `conversation`, `conversation_events`, `events_after` |
| `Caller` | Who runs this process: its terminal, workspace, agent session id, terminal labels (read once, cached), and `role_in(project)` → manager, worker of task X, reviewer, helper of owner Y, another session, or a person at a shell. Authorization for `guard` builds on it. | the twelve identity functions in 1.4 |
| `Terminals` | The host as a port: `get`, `ls`, `run`, `send`, `keys`, `read`, `label`, `keep`, `kill`, `remove`, `interrupt`, `events`. Two implementations, `HcTerminals` and `TuiPanes`; the registration says which one a project uses. `TerminalInfo` names the fields of a reply (`state`, `status`, `turn`, `labels`, `program`, `cwd`). | `hc`, `herdr`, `agents`, 116 inline branches |
| `AgentKind` | One class per agent program: `argv(model, effort, …)`, `takes_prompt`, `resume_argv(session)`, `manager_argv(…)` (narrow, lean, compaction), `has_stop_hook`, `sessions` (where its transcripts are), `native_memory_settings`, the startup prompts it shows. Kinds from `config.json` use `GenericAgent`. | 116 comparisons on kind; `agent_argv`, `resume_argv`, `lean_pm`, `codex_pm_compact`, `pi_pm_compact`, `native_memory`, `HOOKED_KINDS` |
| `MemoryLayer` | One memory folder (a project's, or the personal one): `read`, `remember(…, writer)`, `forget`, `restore`, `history`, `write_index`, `lock()`. | 33 functions over `memory_dir(repo)` |
| `Context` | `home`, `store`, `caller`, `config`, `terminals`, `git`, `procs`, `clock`, `out`. Built once in `cli.main()`; a test builds its own with a temporary home and fakes. | every module global in 1.3 |

Services are classes that take a `Context`: `Workers(ctx).dispatch(...)`, `Reviews(ctx).start(task)`, `Landing(ctx).land(task)`, `Deliverer(ctx, project).run()`, `Helpers(ctx).start(owner, name, prompt, …)`. They take and return domain objects, not `argparse.Namespace`.

### 2.4 Where IO goes

| Port | Real implementation | In tests |
| --- | --- | --- |
| `Store` | `FileStore` on `Home` | the same, on a temporary directory (it is fast and it is the contract) |
| `Terminals` | `HcTerminals` (the `hc` CLI and `hc connect`), `TuiPanes` (the `herdr` CLI) | `FakeTerminals`: terminals as dicts, a log of what was sent, scripted status changes |
| `Git` | subprocess `git` | real git in a temporary repository (as today), or a stub where only `state()` matters |
| `Processes` | `Popen` of the launcher in a process group of its own | records what would be started; can run it inline |
| `Clock` | `datetime.now()`, `time.monotonic()`, `sleep` | a clock the test moves |
| `Output` | stdout and stderr | captured strings |
| `AgentKind.sessions` | transcript folders under the agent's home | a temporary folder |

Domain code (layer 2) gets data in and returns data: `policy.is_news(event, task, manager_panes)`, `plan.after_status(plan, new, prev)`, `deps.evaluate(task, tasks_by_id)`. It can be tested with literals, with no temporary directory and no patching.

The existing rule that tests never run against a real ledger (`assert_temporary_ledger`) becomes structural: a test builds `Home(tmp)` itself, and `Home.from_env` is only called from `cli.main()`.

### 2.5 Status changes and what follows them

`cmd_update` splits into three parts:

1. **`Ledger.transition(task_id, request)`**: validate, apply field changes, sync the plan, attach the question card, write the entry with its `source` (from `Caller`) and its `wake` (from `events.policy`). One locked change. Returns a `Transition` (task before, task after, the entry, what moved).
2. **`reactions.after(transition)`**: one ordered list in one file, each item a small function in the area that owns it. In today's order:

   | Order | When | Reaction | Owner |
   | --- | --- | --- | --- |
   | 1 | the entry wakes | make sure the deliverer runs | `events.deliver` |
   | 2 | now `review` or `done`, with a report | collect research reports | `workers.research` |
   | 3 | a worker reported `review` and the plan has a review step | start the auto-review; stop here | `review.review` |
   | 4 | `--send` | type the note into the worker | `workers.send` |
   | 5 | now `merged` | retire the review; retire or schedule the worker's close | `workers.lifecycle` |
   | 6 | now closed | end the worker's terminal; prune memory candidates | `workers.lifecycle`, `memory.candidates` |
   | 7 | now `review`, `workers.close_reported` on | end the reported worker's terminal once idle | `workers.lifecycle` |
   | 8 | a review thread is `done` | sync the reviewed task's plan step | `ledger.plan` through `Ledger` |
   | 9 | dependencies changed, or the task met someone's dependency | reconcile dependents | `ledger.deps` through `Ledger` |
   | 10 (new) | a task with a `parent` closed | roll up the parent: `Family.rollup()` | `ledger.family` through `Ledger` |
   | after any save | | `BOARD.md`, then the Discord board | `ledger`, `discord` |

   Row 10 is the one row that does not exist today. The rule `Family.rollup()` starts with: when every child is closed (`merged`, `released`, `done` or `abandoned`) and at least one of them is not `abandoned`, a parent that has no worker and no branch of its own and no unfinished plan step moves to `done` with an entry "all N child tasks finished" (`source: "rollup"`, which is news for the manager like any other move to `done`). A parent that still has its own worker, branch or open plan steps is not moved; the manager gets one event saying its children are finished. The rule is a pure function over the parent and its children, so changing it later is a change in one file with table tests.

3. **`commands/tasks.py: cmd_update`**: arguments in, `transition` + `reactions`, lines out.

`land`, `retire`, `approve`, `archive` and the auto-review, which today call `cmd_update` or repeat parts of it, call `Ledger.transition` and get the same reactions. A new feature that reacts to a status change (background memory consolidation after a land is the next one) adds a row here, not a branch in `cmd_update`. The list is explicit and ordered on purpose: no event bus, no registration by import side effect.

### 2.6 Errors and output

- Layers 0–3 raise: `Refused` (the request is not allowed as asked; the text says what to do instead), `NotFound`, `IdentityError`, `StoreError` and its kinds. They never call `sys.exit` and never print; a service that has something to say returns it or writes to `ctx.out`.
- `cli.main()` maps exceptions to today's exit codes and messages, byte for byte where a mod matches the text (section 3.4). Commands with exit codes of their own (`wait`: 2 timeout, 3 stopped unreported; `guard`: 2; `project save`: 4 with `{"error": "conflict"}`; `codex-cmd`: 3; `recall`: 3) raise an exception that carries the code.
- The deliverer, the hooks and the seat catch `PmError` where they must keep running, instead of `SystemExit`.

### 2.7 Command line and background processes

- Each file in `commands/` has `register(sub)` with the argument declarations that are in `build_parser` today, moved verbatim, and the `cmd_…` adapters. `cli.py` calls them in today's order. The parser is assembled whole on every run (it costs 9 ms); argparse's own messages, which `pm-project` matches, stay argparse's.
- **Imports happen at startup, never inside functions.** A deliverer, a seat or a `helper wait` runs for hours; an install replaces the files under it. A module imported late would come from the new version into an old process. With every import at the top, a process is one version from start to end, as it is with one file.
- `procs.code_mark()` replaces `script_mark()`: the inode, size and mtime of `pm.py` and every `pmlib/**/*.py`. The deliverer hands over to a fresh copy when it changes, as today.
- `procs.launcher()` is the one place that knows the path of `scripts/pm.py`; background starts, `pm_script()` in briefs, the seat's argv, `pm_pi_compact.js` and `assets/dash.html` are found through it.

## 3. Contracts that do not change

A stage may be merged only if everything in this section still holds. Stage 0 turns as much of it as possible into tests.

### 3.1 Command line

- **Entry point**: `python3 <skill>/scripts/pm.py <command> …`, at four install paths (`~/.claude/skills/pm/`, `~/.codex/skills/pm/`, `~/.pi/agent/skills/pm/`, and the mod's own bundled copy `<herdr-app home>/mods/pm-dash/skill/scripts/pm.py`). On Windows `py -3 "<path>" …`.
- **`pm.py --home <dir> <command>`** before the command, and `PM_HOME`.
- **Commands** (59): `new`, `update`, `log`, `show`, `board`, `status`, `diff`, `find`, `claim`, `guard`, `launch`, `start`, `archive`, `restore`, `deliver`, `event`, `notify`, `watch`, `codex-cmd`, `dispatch`, `wait`, `approve`, `triage`, `send`, `_deliver-send`, `_deliver-ready`, `land`, `review`, `escalate`, `reattach`, `retab`, `retire`, `idle-workers`, `close-worker`, `state`, `project` (`events`, `log`, `session`, `change`, `context`, `file`, `files`, `library`, `memory`, `save`, `delete`, `restore`, `history`, `add`, `retopic`, `archive-decisions`, `research-migrate`), `helper` (`start`, `done`, `wait`, `ls`, `stop`), `dash`, `decide`, `remember`, `recall`, `forget`, `adopt`, `memory`, `handover`, `decisions`, `conversation`, `context`, `rotate`, `seat`, `end-session`, `name-agent`, `home`, `backfill-numbers`, `hook-session-start`, `hook-pre-compact`, `hook-pre-tool`, `hook-turn`, `hook-mirror`.
- **Every option, default and positional** of those. Stage 0 dumps the parser tree to a golden file and compares.
- **Exit codes** as in 2.6, and stdout shapes that are parsed: the JSON of `state`, `project …`, `show --json`, `idle-workers --json`, `home --json`, `backfill-numbers --json`, `helper … --json`; the first line of a delivered batch, `[from pm.py deliver] N event(s) (<start>-<end>)`, which the manager's turn hook reads back; `[from <sender>] …` on sent text.
- Older and newer `pm.py` run against the same ledger at once (a remote machine, a skill not yet updated). Argument shapes and JSON fields only grow.

### 3.2 The ledger on disk

Written by one version, read by another, by the mods, and by people. Names, formats and locking stay as they are.

| Path under the ledger home | Read or written outside `pm.py` by |
| --- | --- |
| `tasks/<id>.json` (all fields, open-ended; `log[]` entries `{at, by, text}`, text shaped `status=review, commit=abc; <note>`) | `pm-project` reads it directly and parses the entry text; `pm-dash`, `pm-nav`, `pm-project` watch the folder; `render_check.py` |
| `pms/<slug>.json` | `pm-list` watches the folder |
| `projects/<slug>/conversation.jsonl` (append-only; event `type` values and fields as today) | `pm-dash` and `pm-project` tail it; watched |
| `projects/<slug>/` `delivered.json`, `delivered.lock`, `deliver.lock`, `seat.json`, `seat.lock`, `next-session.json`, `turn-cause.json`, `taken-in.json`, `task-seq.json`, `handover.md`, `verify`, `pm-settings.json` | other `pm.py` processes and versions |
| `projects/<slug>/` `decisions.md`, `library.json`, `research-sources.json`, `docs/`, `research/`, `attachments/` | `pm-project` watches them and writes attachments |
| `projects/<slug>/memory/` and `memory/` (`*.md` with frontmatter, `MEMORY.md`, `candidates/`, `.history/`) | coding agents read `MEMORY.md` and write candidates; `pm-project` watches |
| `projects/<slug>/helpers/<owner>/<name>.md` | `pm-project` reads the result file |
| `BOARD.md`, `config.json`, `sent/<id>.md`, `inbox/<name>.log` and `.offset`, `waits/<task>.json`, `locks/`, `reattach/`, `reads/`, `tmp/`, `mcp/`, `turns.log`, `discord.json`, `discord.log`, `pm-settings.json` | people (`config.json`, `BOARD.md`), agents told to resend `sent/<id>.md` |
| `cache/remote-states.json`, `attachments/<machine>/`, `install/` | owned by the mods and `setup.py`; `pm.py` leaves them alone |

Also unchanged: per-task lock files under `locks/` (never a lock on the JSON itself), temporary names that carry the pid, and the ledger-home rule, which is copied in `setup.py`, `render_check.py` and four mods.

### 3.3 Hooks and terminals

- Hook commands as `setup.py` writes them: `python3 ~/.claude/skills/pm/scripts/pm.py hook-session-start | hook-pre-compact | hook-pre-tool | hook-turn` (and the Codex equivalents). Uninstall recognizes a hook by the substring `skills/pm/scripts/pm.py`. Installed hooks are not rewritten by an update, so the path and the command names are fixed.
- Hook input (JSON on stdin) and output (plain text for Claude Code, JSON for Codex), and that a hook never fails the session.
- `pm_pi_compact.js` runs `pm.py hook-pre-compact --print` and `pm.py handover --compact --repo <cwd>` from the file beside it.
- Terminal labels that the mods read: `pm`, `pm.retired`, `task`, `helper`, `helper.of`; task `pane` values `hc:<terminal>`.
- Environment: `PM_HOME`, `HC_TERMINAL_ID`, `HERDR_PANE_ID`, `HERDR_WORKSPACE_ID`, `HERDR_ENV`, `HC_SESSION`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CONFIG_DIR`, `PM_COMPACT_TOKENS` (and `PM_ROTATE_TOKENS`, `PM_PI_COMPACT_TOKENS`), `PM_NO_DISCORD`, `PM_HELPER_OF`, `PM_HELPER_NAME`, `PM_HELPER_PROJECT`, `DISCORD_*`.

### 3.4 What the mods run and match

- **Commands**: `state` (all four mods, also on remote machines through a shell loop over four script paths with bare `python3`); `start`, `archive`, `restore` (`pm-dash`, `pm-project`); `reattach`, `adopt` and `project events | log | session | library | memory | file | save | delete | restore | history | add | retopic | files | change` (`pm-project`).
- **Error text** that `pm-project` matches on stderr: argparse's `invalid choice: '<command>'` and `unrecognized arguments` (how it detects an older `pm.py`), `already exists`, `is not offline`, `was replaced`, `shorter than`, `no line ends at byte`, `no line of the transcript starts at byte`, `is not supported`, `no session found`, `no session recorded`, `transcript not found`, `no unambiguous claude session`, `no task `, `not a task id`, `invalid document root`, and **`pm_sessions.py is missing`**. The last one names a file: the message keeps its wording even after that module moves.
- **Interpreter**: the mods probe for Python 3.8 or later; `pm.py` needs 3.9 today. The package must not raise that.
- `assets/dash.html` is found at `../assets/` from the scripts folder and fetches `/api/state` from `pm.py dash`.

### 3.5 Install

- `setup.py` removes the installed `skills/pm` folder and copies the bundled `skill/` folder **whole** (`shutil.copytree`), so a `pmlib/` folder is installed and fingerprinted with no change. It excludes test files by a **list of eight file names**; that list becomes patterns (`test_*.py`, `tests`) in stage 0, in `SKILL_EXCLUDED` and in the matching checks of `tests/test_install.py`.
- `fingerprint()` requires `scripts/pm.py` to exist and hashes every installed file, so a mixed copy counts as outdated.
- `install.sh`, `install.py` (the bash-free entry point, used on Windows) and `render_check.py` copy the `mods/` tree, test files included; `render_check.py` skips `__pycache__` and symlinks, and runs the bundled `pm.py state` and `pm.py project session`.
- Windows: `pm.py` re-runs itself with `-X utf8`; hooks use `py -3` and a double-quoted absolute path with forward slashes. Both stay in the launcher and in `osutil`.
- The copy is not atomic today (remove, then copy). A process that starts in that window finds no `pmlib` and gets the same "install or copy the whole skills/pm folder" error that a missing `pm_store.py` gives now.

### 3.6 `import pm` and the sibling modules

- All eight test files do `sys.path.insert(0, <scripts>)` and `import pm`, then call `pm.<function>` and assign or patch `pm.<name>` (section 1.4, item 8). `test_pm.py` replaces `pm.deliver_later`, `pm.send_async_later` and `pm.send_ready_later` at import so no test types into a real terminal, and checks `pm.STATE`, `pm.TASKS`, `pm.PMS`, `pm.INBOX`, `pm.PROJECTS` and `pm.PANE` before anything runs.
- `tests/test_install.py` loads `pm.py` **by file path** under another name and patches `WINDOWS` on it.
- `import pm_store`, `pm_project`, `pm_sessions`, `pm_events` in tests, and `python3 -c "import pm_events"` in `test_install.py`. These four stay importable under these names until stage 8, and as one-line re-exports after it.
- Several tests start `python3 -c "import pm; …"` or `python3 pm.py …` in a subprocess with the scripts folder on `sys.path`.

## 4. Migration

### 4.1 How the tests stay green while code moves

Two devices carry the whole migration.

**The rename.** Stage 1 is `git mv pm.py pmlib/_legacy.py` as a commit of its own, then a new 50-line `pm.py`. From then on `pm.py` never changes again, and each later step moves functions out of `_legacy.py` into the module that owns them, until `_legacy.py` is empty and deleted.

A branch that edits `pm.py` and was cut before stage 1 does **not** merge by itself: once a new `pm.py` stands at the old path, git sees a rewritten file and a new one, not a rename, and reports a conflict in `pm.py`. Such a branch first merges the rename commit alone (`git merge 3ba6c49`, where `pm.py` does not exist and the rename is detected, so its edits move into `_legacy.py`), then merges `main`. Tried on a scratch clone: the direct merge conflicts, the two-step merge is clean and the edit lands in `_legacy.py`.

**The forwarding shim.** When `pm.py` is imported (not run), it turns itself into a module whose attributes forward to the package:

- reading `pm.X` returns `X` from the module that owns it;
- assigning `pm.X = v` (which is also what `mock.patch.object(pm, "X", v)` does, on entry and on exit) sets `X` in the owner **and in every `pmlib` module that holds the same object under that name**, so both `host.hc(...)` and a bare `hc(...)` behind `from .host import hc` see the replacement;
- a name defined in two modules is an error when the shim is built, which keeps "one owner per name" true through the migration.

This was prototyped on a toy package (`runtime`, `host`, `tasks`, `_legacy`) with the patterns the suite uses: plain assignment, `mock.patch.object`, `mock.patch("pm.X")`, patching a function another function of the same module calls by its bare name, patching a constant, a cache written inside the package and read through `pm`. All passed. It has not been run against the real 510 tests; that is the first thing stage 1 does, and if a pattern turns up that the shim cannot serve, that test is changed in the same stage and listed in its report. One such change is already known: `tests/test_install.py`'s `load_module` needs the usual `sys.modules[name] = module` line before `exec_module`, so the path-loaded module can be turned into a shim.

Because of the shim, moving a function does not require touching its tests. Tests move to the new modules and to fakes at their own pace (section 4.3, stage 8), which keeps each stage reviewable: a move is a move.

**Rules for a carve** (each one is a branch of its own):

1. Bottom-up only. A module may be carved when everything it calls is already in the package below it. Where a low-level function calls upwards (1.4, item 6), a first commit turns that call around inside `_legacy.py` (a reaction, a watcher or a parameter); the move comes after.
2. Split first, reshape afterwards, as two passes over the whole file (decided after stage 2; the first version of this note had each carve do both). **Pass one** only cuts `_legacy.py` into the modules of 2.2: functions move as they are and change only how they reach other modules; an upward call is turned around first (rule 1). `scripts/tests/moved.py` makes this mechanical: it compares the syntax tree of every top-level definition before and after, so a carve's report is "N moved unchanged, M changed in these lines". **Pass two** starts when `_legacy.py` is empty: on modules of a few hundred lines, `Context`, the ports and the service classes come in, `cmd_update` becomes `Ledger.transition` with the reactions list, and the tests move to fakes. Doing both in one carve of a 16,000-line file means proving "moved correctly" and "reshaped correctly" at once, with a failure hard to place; one at a time, each step proves one thing. The objects that pass one does introduce are the ones a moved function uses at once (`Home`, `Caller`) or that are new rules with nothing to break (`Family`).
3. Until stage 8, the old functions and module-level values stay the source of truth and a new object wraps them, not the other way round: `Home` is built from the current `STATE`, `TASKS`, … on each call, `HcTerminals.get` calls the module-level `hc`. The suite patches those names (`pm.hc` 89 times, `pm.PANE` 49), and several hundred uses in `_legacy.py` read them; an object that owned the state would need the shim to translate every such patch. Stage 8, when tests build a `Context` with fakes, turns it around. For the same reason an object arrives with its first user, not before: `Home` in stage 2 (the path functions use it), `Caller` in stage 3 (the news policy takes one), `Context` and the `Terminals` protocol in stage 4 with the first service class.
4. A moved module reads a process global as `context.PANE`, at call time, never through `from … import`; a name that its module rebinds at run time (`_IDENTITY`, `_PENDING_NOTES`, …) is read and written only by that module's functions.
5. No behaviour change in a carve. The two bug fixes come before the first carve (stage 0b); the one new behaviour of the migration, the parent roll-up, is a separate commit at the end of stage 5.
6. The layer test, the parser golden test and the full unit suite pass on every commit that is merged.

### 4.2 Checks used by every stage

| Check | What it catches |
| --- | --- |
| The existing suite, unchanged: all `test_pm*.py` and `tests/test_install.py` | behaviour |
| Parser golden test (stage 0) | a command, option or default that changed |
| Layer test (stage 1) | an import against the layering; an import inside a function |
| Differential replay (stage 0): a script runs the same sequence of commands (`new`, `update`, `dispatch --dry-run`, `review`, `land` against a temporary repository, `remember`, `handover`, `state`, `project …`) with a fake `hc` on `PATH`, once with `pm.py` from `main` and once from the branch, each in its own temporary home, and compares the two ledger trees and the outputs with times and temporary paths normalized | a difference no unit test looks for, on disk or on stdout |
| Read-only commands against a **copy** of a real ledger (`state`, `status`, `handover`, `deliver --dry-run`, `project events`), old and new output compared | real data shapes; never the live ledger, which has no backup |
| Startup time of `hook-pre-tool` and `hook-turn` | an import that became slow |
| At stages 1 and 8, on a Windows machine: the unit suite, and one real hook run | `-X utf8`, `py -3`, paths, `msvcrt` locks |

Mods are not touched, so their `node --test` suites and the render check are not gates for these stages; the render check still runs once on `main` after the last one.

The project's merge check (`projects/<slug>/verify` in dudu's own ledger) runs `test_pm.py` and `tests/test_install.py` only. For this migration every stage's worker and reviewer run all eight `test_pm*.py` files and the new tests under `scripts/tests/`; the merge check should list them too for as long as the migration runs.

### 4.3 Stages

| Stage | What moves | Size | Main risk | Extra verification |
| --- | --- | --- | --- | --- |
| **0a. Safety net** | Nothing. Adds the parser golden test, the differential replay script and its fake `hc`, pattern-based test exclusion in `setup.py` and `test_install.py`, and a timing baseline. | tests only | none | the new tests pass on `main` as it is |
| **0b. The two bugs** | Nothing moves. Fixes delivery (5.3, 5.4) and reattach (5.6) in today's `pm.py`, with their regression tests. Runs beside 0a. | ~80 lines and tests | one extra `hc get` per worker `update` | the three log entries of 5.1 replayed; the transcripts of 5.6 |
| **1. Launcher and package** | `pm.py` → `pmlib/_legacy.py`; new `pm.py` (UTF-8 re-exec, `--home`, missing-package error, shim, `main()`); `pmlib/procs.py` with `launcher()` and `code_mark()`, used by the 13 `__file__` sites; the layer test. | 1 rename, ~200 new lines | the shim against the real suite; the installed layout | full suite; `test_install`; install into a temporary agent home and run a hook; deliverer hand-over test with a touched `pmlib` file; timing (expect about −0.1 s per call); Windows run |
| **2. Foundations** | `osutil`, `config`, `gitrepo`, `terminals/` (`hc`, `herdr`, tabs, screens): moved as they are. `context` becomes the home of the process globals (`STATE`, `TASKS`, `PANE`, …), still as module-level values. `home` gets the path functions and the first new object, `Home`, built from those values on each call. | ~1,000 lines | the tests assign `pm.STATE`, `pm.PANE` and the like directly: the moved functions must see the new value | the temporary-ledger guard still trips when pointed at a real home; replay |
| **3. Ledger, caller, news policy** | Three carves. **3a**: `store`, `project/`, `ledger/` (task, ledger, board); the upward calls from the write path (board, Discord) and from `hc_pm` (the seat) become registered after-save steps and a registered check. **3b**, beside 3a: the pure rules, `ledger/` plan, deps, question and family; `Family.rollup()` arrives as a rule with its table test, called by nothing yet. **3c**, after 3a: `caller` (the identity functions moved, pinned by a table test of what each returns today, then `Caller` around them) and `events/policy` (the delivery fix of stage 0b as a pure rule over a task and a `Caller`). | ~2,500 lines | `mutate_task`/`note` ordering (entries after the save); `Caller` replacing twelve functions with slightly different rules | a table test per identity function, old result against `Caller`'s, before each is switched; replay; the delivery regression tests of stage 0b |
| **4. Agents, workers, delivery** | `agents/` (kinds as classes, profiles, Codex pool, sessions incl. `find_session`), `workers/` (dispatch, brief, send, wait, lifecycle, escalate, reattach, research), the rest of `events/` (deliver, stalls, inbox, notify), with helpers and dependencies attached to the deliverer as watchers. | ~4,000 lines, in 5–6 carves | the largest stage; timing-sensitive code (`send_when_ready`, stalls) | `test_pm_events.py`, `test_pm_delegate.py`; one real dispatch → report → deliver round in a private herdr-core session |
| **5. Reactions, review, land** | `cmd_update` becomes `Ledger.transition` + `reactions`; `review/`, `land`; the 13 `Namespace` calls become service calls. Then, as a commit of its own, the one new behaviour: the parent roll-up (row 10 in 2.5). | ~1,500 lines | the order of reactions; `land` and `retire` re-reading inside the change | replay with a merge, a failed check and a conflict; `test_pm_delegate.py`; table tests for `Family.rollup()` |
| **6. Manager session** | `manager/` (claim, seat, rotate, launch, handover), `hooks`, `discord`. | ~2,700 lines | the seat hosts live sessions; a rotation swaps code under it | a rotation and a compaction in a private session; hooks run from an installed copy for Claude Code and Codex |
| **7. Memory, Library, helpers, views, home** | `memory/`, `library`, `helpers/`, `views/` (incl. `pm_project.py`'s content behind a re-export), `homemove`. `Helpers.start(...)` and `MemoryLayer` get the programmatic interfaces section 6 needs. | ~4,500 lines, in 5 carves | JSON shapes the mods read | `state` and `project …` output compared on the ledger copy; `test_pm_home.py`, `test_pm_project.py`, `test_pm_context.py` |
| **8. Command line, tests, clean-up** | `build_parser` splits into `commands/*.register`; first `procs.code_mark()` is changed to list the code files on each call (stage 1 caches the list when the process starts, so a version that deletes a file leaves an older deliverer whose mark is `None` for ever: it never hands over and keeps `deliver.lock`; found in the review of stage 1, reproduced there); then `_legacy.py` is deleted; `pm_store.py`, `pm_sessions.py` and `pm_events.py` move in behind re-exports; `test_pm.py` is split into one file per module under `tests/`, new tests use `Context` with fakes, and the shim shrinks to the names old tests still use. | parser 550 lines; tests are rewritten gradually | splitting a 9,939-line test file | parser golden test; the test count before and after; Windows run; render check once on `main` |

**As carried out**, the table's stages 3–7 are pass one of rule 2 in 4.1 (cutting only), in carves of 300–900 lines that follow the call graph rather than the stage numbers: what a carve needs below it must be there, nothing else orders them. Fifteen carves so far: ledger core; plan, dependency, question and family rules; caller and news policy; agent programs and profiles; delivery infrastructure; sessions, briefs and the Codex pool; worker lifecycle; the deliverer loop; review and land; the manager's session; hooks; memory; helpers; Library edits; Discord and the ledger-home move. Each was checked the same way: the full suite, the differential replay against `main`, startup time, and `moved.py`'s syntax-tree comparison (typically 40–90 definitions unchanged and 5–30 changed only by a `context.` prefix). Upward calls were turned into registration points as they were met: what follows a save, the seat check, the caller's projects for a bare `#N`, the candidate pruner, and the deliverer's watchers; five in all, registered where the program starts. The reshaping the table lists under those stages (`cmd_update` into transitions and reactions, service classes instead of `Namespace` calls, `MemoryLayer`, the parent roll-up wired in) is pass two, after stage 8's command-line split.

Stages 0a and 0b run side by side; 1–3 are strictly in order. After stage 3, the carves of stages 4, 6 and 7 touch different regions of `_legacy.py` and different target files, so two or three workers can run in parallel; `homemove` (740 lines, used by one other area, with a test file of its own) and `discord` can go any time after stage 2 and make a good first carve to prove the routine. Stage 5 needs stage 4. Stage 8 needs everything.

### 4.4 Risks across stages

- **Branches in flight.** Nearly every feature thread edits `pm.py` and `test_pm.py`. The rename is followed by git only through the two-step merge of 4.1; a function that moved between files is not followed at all, and a branch that edited it gets a conflict. So: carves are short-lived branches (hours, not days), a carve is merged when no open thread touches the functions it moves, and test files are left alone until stage 8 so they never conflict.
- **Two copies on one ledger.** The mods run the bundled copy, agents the installed one, remote machines whatever they have. Nothing here changes a file format or an argument, so mixed versions behave as they do today.
- **A process outliving an install.** Covered by imports at startup and `code_mark()` (2.7). The seat is the longest-lived process; stage 6 tests an install under a running seat.
- **A stage that turns out larger than planned.** Every carve leaves `main` working, so the migration can pause after any of them; a half-migrated tree is `_legacy.py` plus finished modules, not a broken state.

## 5. Two bugs fixed on the way

Both are fixed on today's `pm.py` before stage 1 (stage 0b), each with regression tests; stages 3 and 4 then move the fixed logic into `Caller`, `events/policy.py` and `agents/sessions.py` with those tests guarding the move.

### 5.1 Delivery: what happened

On 2026-11-22 in dudu's own ledger, a worker (terminal `hc:t16m`, dispatched for one task) did follow-up work that the manager had registered as a second task for bookkeeping. That second task was created by the manager itself, so its `pane` was the manager's terminal and it had no `dispatched` mark. It was already in `review`. The worker then reported on it without moving the status: `update <task> --commit a27dc32 --note "…"`. The manager was never told, and the merge waited until the manager noticed by hand.

The conversation log shows it. Three entries by that worker on that task:

| Time | Entry | `source` | `wake` | Delivered |
| --- | --- | --- | --- | --- |
| 00:26 | `status=blocked; …` | `session` | `true` | yes |
| 00:49 | `status=review, commit=63ce17c; …` | `session` | `true` | yes |
| 01:10 | `commit=a27dc32; …` | `session` | absent | **no** |

### 5.2 Delivery: root cause

Two functions decide whether an entry reaches the manager, and both ask the wrong question.

- The writer, `wake_fields` (`pm.py:4187`):

  ```python
  worker = bool(PANE) and task.get("pane") == PANE and pm_started(task)
  fields = {"source": "worker" if worker else "session"}
  waking = status in WAKING or (worker and reported and task.get("status") in ("review", "blocked"))
  ```

  "Worker" means *this task's recorded pane is my terminal, and this task was dispatched*. A worker writing to any other task is a `session`. The first two entries woke the manager only because they moved the status (`status in WAKING`); the third moved nothing, so it needed `worker` to be true.

- The reader, `is_news` (`pm.py:4246`), re-derives the answer from the entry so that older versions' entries are judged the same way. For an entry on a task in `review` that sets a commit it requires `source in ("worker", None)`, and for a note alone `source == "worker"`. The entry says `session`, so it is "another session's comment on a task that is already there": not news.

So the report was dropped by design of the rule, not by a failure of the deliverer. The rule identifies the reporter through **the task being written to** (`task.pane`, `task.dispatched`) instead of through **the writer** (which terminal is this, and what was it started for). It breaks whenever a manager-started agent reports in place on a task it is not the recorded pane of: a task the manager registered itself (as here), a sibling or child task on the same branch, or a task whose `pane` still names an earlier terminal.

### 5.3 Delivery: the fix

1. **`Caller` says who the writer is, independent of the target.** `caller.role_in(project)` is `manager` when the terminal is one of the project's manager terminals; `worker(task X)` when the terminal carries the `task=X` label that `dispatch`, `review`, `escalate` and `reattach` set (or its agent session is recorded on X); `helper`; otherwise `session`, or `user` outside any terminal. This is `own_task()`'s rule, which already exists and is already the strict one; `wake_fields` just does not use it.
2. **The entry records that.** `source` is the writer's role. When a worker writes to a task other than its own, the entry also carries `from_task: X`. Both are additions; readers that do not know `from_task` ignore it.
3. **The policy is one pure function** in `events/policy.py`, used by the writer (to set `wake`) and by the reader (for entries of other versions): an entry is news when its writer is not the manager and it is a report — it moves the task into `review`, `blocked`, `done` or `proposed`, or it is a commit or note from a manager-started agent on a task that is in `review` or `blocked`. "From a manager-started agent" is `source in ("worker", "helper")`, whatever task the entry is on. A plain session's comment on a waiting task stays quiet, as today.
4. **The batch says where the work is.** With `from_task`, `batch_text` names the reporting worker's own task and branch (`… reported by the worker of #163 <id> (branch dev/…)`) and bases its hints (`pm.py diff`, `approve`, `review`) on that task when the target has no branch of its own. That covers "forward a sub-task's report to the task that owns the branch" without `pm.py` silently writing to a second task; whether to move the branch's task to `review` stays the manager's call.
5. **Tests**: the three entries above as a regression test (the third must be delivered); a table over writer role × entry kind × task status for the policy; a test that an older entry with `source: "session"` and no `from_task` is judged as before.

### 5.4 Delivery: the fix on today's code

The fix does not need the refactor. In today's code it is `wake_fields` using `own_task()` to decide `worker`, plus `from_task` and the batch text: about 30 lines and the tests above. Stage 3 keeps the behaviour and changes where it lives.

One cost: deciding the writer's role needs the terminal's labels, one `hc get` per `update` from a worker terminal. `Caller` caches it for the process.

### 5.5 Reattach: what happened and why

A worker running on `agy` had its terminal stopped. `pm.py reattach <task>` then resumed a Claude Code session, which turned out to be a session of that task's *reviewer*. The reviewer came back believing it was the worker.

The path through the code:

1. The task has no recorded session (`task.session` is empty: session recording covers Claude Code and Codex, and this worker was neither), so `find_session` (`pm.py:12641`) falls back to scanning.
2. `claude_sessions` looks at every transcript under `~/.claude/projects/<folder>` for each of the task's folders, the worktree first. A reviewer is placed in the reviewed task's worktree, so its transcripts are in that same folder.
3. `session_score` (`pm.py:12581`) decides by text: 0 for a manager's or a helper's session (recognized by their opening), otherwise 1 when the transcript mentions the task id and 2 when it contains `update <id>` or `log <id>`. Its docstring expects a review to be told apart because it writes `update <id>-review`. But a reviewer's transcript quotes the reviewed task's ledger entries and brief, which contain `pm.py update <id> …` verbatim: the transcript that was resumed has six such matches. It scored 2.
4. `reattach_plan` (`pm.py:12724`) takes the best candidate. It compares the session's kind with the kind the worker was dispatched with (`same`), but only to decide which model flags to pass; a Claude Code session for an `agy` worker is resumed all the same.

So the scan identifies a session by **what its text mentions**, not by **whose session it is**, and the one hard fact available (the worker's agent kind) is not used to reject a candidate.

### 5.6 Reattach: the fix

1. **A session of another kind is never the worker's.** Candidates are limited to the kind the task's worker was dispatched with (`dispatched_with`). A kind that cannot be resumed here (`agy`, `pi`) skips the scan and starts fresh with the brief, which `reattach_plan` already knows how to do.
2. **A session that belongs to someone else is excluded.** Every session id recorded on another task (`session.id` and `prior_sessions`, in particular those of `<id>-review`) is out.
3. **Role comes from the opening, as it already does for managers and helpers.** `pm_session` and `helper_session` look only at the transcript's opening (what `pm.py` sent first). The same test is added for reviewers: an opening that carries a review brief is a reviewer's session and scores 0 for the reviewed task. The words a session quotes later no longer decide anything.
4. In the new structure this is `agents/sessions.py`: `session_role(opening)` returns manager, helper, reviewer of X or worker of X, and `find_session(task)` asks each `AgentKind` only for sessions of that task's role. The background-consolidation collector (section 6) uses the same function to tell worker transcripts from reviewer transcripts.
5. **Tests**: a worktree folder with a worker transcript and a reviewer transcript that quotes `update <id>`: the worker's is found; with only the reviewer's present: none is found and the plan is `fresh`; an `agy` task never resumes a Claude Code or Codex session.

### 5.7 Seen while this was under way: a background command holds all delivery back

Not fixed; recorded here because it belongs to the delivery policy that stage 4 moves.

On 2026-11-22 the manager's session started a shell command in the background that never ended (an `ls -la` that hung). Its turn was over and it sat at its prompt, but its terminal kept reporting `{"state": "working", "msg": "1 shell still running"}`. `deliver_look` sends a batch only when the state is `idle` or `done`, so nothing was delivered for 85 minutes: nine events queued, among them two reviews that had passed and a blocked worker. Delivery resumed the moment the command was killed.

The rule treats "has background work" as "is in a turn". They are different: a manager with a background `land` or `wait` running can take a message, and the code already tells them apart elsewhere (`background_work(info)` is what a rotation looks at). Where it goes in the new structure: `events/policy.py` decides "can the manager take a batch now" from a `TerminalInfo` that names turn state and background work separately, and the deliverer raises a stall of its own (a notice to the user's conversation) when events have waited longer than a limit. Whether to fix it before stage 4 as a bug of its own is the user's call.

## 6. Where background memory consolidation (`autoDream`) lands

The consolidation design (draft, not yet in the repository) adds a gate after `land`, `retire` and the end of a manager turn, a collector over session transcripts and the ledger, a read-only helper that proposes a plan, and a guarded `dream apply` with undo. It is not built by this refactor. The structure leaves it a place and the interfaces it needs:

| The draft needs | Lands on |
| --- | --- |
| Its own code: gate, collector (`dream pack`), guard (`dream apply`), undo, the `dream` commands | `pmlib/memory/dream/` (`gate.py`, `collect.py`, `guard.py`, `undo.py`) and `commands/dream.py`. A service-layer package that imports `memory`, `agents.sessions`, `helpers`, `ledger`, `project`. |
| Triggers after `land`, `retire` and a manager's Stop hook | two rows in `reactions.py` (a task landed; a task retired) and one call in `hooks.py`, each to `dream.gate.maybe(project)`. No edits inside `land` or `retire`. |
| Validated memory writes under the layer's lock, with history | `MemoryLayer.lock()`, `.remember(…, writer)`, `.forget`, `.restore`, `.history`, `.write_index`, and `quote_said` on `Conversation`. Stage 7 exposes these as methods that take a writer explicitly, so a consolidation run can write as itself. |
| Starting a read-only helper from code | `Helpers(ctx).start(owner, name, prompt, mode, reads, labels, memory=False)`. Today the only entry is `cmd_helper_start(a)`, 241 lines over an `argparse.Namespace`; stage 7 makes the command a wrapper of the service. |
| Reading transcripts of every agent kind incrementally | `agents/sessions.py`: the `Sessions` protocol per `AgentKind` (a Codex reader is added there), `find_session(task)`, forward reads from a byte offset. |
| `.dream.json`, `.dreams/<run>/` in the project's memory folder | `ProjectFiles.memory` in `home.py` gets the two names; the files are new, nothing existing changes. |
| A quiet line in the conversation, waking the manager only on conflicts | `Conversation.append(type="dream", …)` with `wake` decided by `events.policy`. |
| `autoDreamEnabled: false` in Claude Code's settings | `agents/claude.py`, `native_memory_settings`. |
| Status in the Memory page | `library.memory_page` adds a `dream` key; `state` is untouched. |

The draft's first slice (the settings guard and persisting `session.path` on tasks) does not depend on the refactor and can go before it; the rest should wait for stage 7, so it is written once against `MemoryLayer` and `Helpers` rather than against 33 functions and a `Namespace`.

## 7. Decisions

Decided by the user on 2026-11-22 ("follow the recommendations"):

| Question | Decision |
| --- | --- |
| The structure and the staging | As in this note. After stages 0 and 1, look at how the shim held up on the real suite before the carves start. |
| The package name | `pmlib`. |
| The two bugs | Fixed now, as stage 0b, on today's code. |
| Who implements | Child threads of this task, one per stage or carve, each checked against this note, reviewed independently, and merged in stage order. One at a time through stage 3; up to three side by side after it. Implementer and reviewer are different models. |
| The test split in stage 8 | Gradual: a test moves when its module is next touched. |

Still open, to settle in pass two before the roll-up is wired to a status change:

- Whether a rolled-up parent closes itself as `done` (the rule in 2.5) or only tells the manager.
- **What "the parent has work of its own" means.** `Family.rollup()` as it landed (carve 3b; nothing calls it yet) decides this from `dispatched`, `worker`, `worker_pane`, `agent`, `branch` and unfinished plan steps. It does not look at `pane`. A task that a session registered for itself (`pm.py new` from that session) carries only `pane`: 104 such tasks in the real ledger when 3b was reviewed. A parent of that kind whose session is still at work would be proposed for closing. Before the roll-up acts, the rule must take "the session in the parent's `pane` is not the manager's and is still live" as an input fact (passed in, so the rule stays pure) and treat it as own work. Found in the review of 3b; the planned task for the roll-up (#210) depends on it.

## Not verified

- The forwarding shim: stage 1 ran the real suite through it. All 519 tests pass unchanged except seven places that read `pm.py` as the file holding the source (`pm.__file__`, copying `pm.py` alone); no patch pattern had to be rewritten.
- The area sizes and the reference graph come from a name-level AST pass and a by-hand assignment of 642 functions to areas; individual edges can be wrong, the overall picture is not sensitive to that.
- The startup timing is from one machine (macOS, Python 3.14): after stage 1, `hook-pre-tool` takes 67 ms instead of 169 ms once the bytecode cache exists; with 61 modules it is about 80 ms, each module costing a fraction of a millisecond to import. Where the cache cannot be written (a read-only install folder, `PYTHONDONTWRITEBYTECODE`) it takes 317 ms instead of 191 ms: importing the uncached package costs more than running the uncached script did. Install folders are writable, so this was accepted. Windows and older Pythons were not timed.
- Windows (Python 3.12, a temporary folder on a real machine, stage 1's branch): `state`, both hooks, `status`, `board`, `home --json`, a memory with Chinese text and the error paths give the same output as `main`. A hook started by a real agent on Windows was not run.
- The cost of one extra `hc get` per worker `update` for the delivery fix was not measured.
- The reattach root cause was read from the code and from the one transcript that was wrongly resumed (six `update <id>` matches in it); the review brief's exact opening, which the fix keys on, is to be confirmed when the fix is written.
