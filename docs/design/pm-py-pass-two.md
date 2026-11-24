# Reshaping `pmlib` into Domain Objects and IO Ports: Pass Two Plan

> **Background**: Pass one of the `pm.py` refactor ([`pm-py-refactor.md`](./pm-py-refactor.md), section 4.1 rule 2) cut the 16,815-line single-file script into an 89-module five-layer package under `mods/pm-dash/skill/scripts/pmlib/`, deleted `pmlib/_legacy.py`, and left `scripts/pm.py` as a 50-line launcher calling `pmlib.cli.main()`. Every carve in pass one was verified by AST comparison to preserve exact function bodies and behavior. Because pass one only moved code, modules still read process-wide globals from `pmlib.context`, call `hc(...)` and `herdr(...)` inline, exit with `sys.exit(...)` and print from inside service and domain code, call commands through fake `argparse.Namespace` objects, and rely on `pmlib/compat.py` so tests can monkeypatch `pm.<name>`. This document inventories the codebase as pass one left it at `7c10c07` and lays out the implementation plan for pass two: introducing `Context`, IO ports, domain objects, service classes, `Ledger.transition` with an explicit reactions table, `Context`-based test fakes, and three standalone behavioral fixes carried over from pass one. Written in November 2026.
> **Status: Proposed.** No code or tests were modified for this plan. All counts come from read-only AST passes over `pmlib/` and the test suites at `7c10c07`, verified against a clean temporary-directory run of all 669 existing unit tests.
> In this document "manager" refers to the coordinating session (`pm` in code identifiers, file paths, and CLI flags).

## Summary

- **Starting point**: 89 modules (19,331 lines) in `pmlib/` plus 4 sibling `pm_*.py` modules (5,278 lines). Across `pmlib/`, there remain **322** reads of `context.*` globals in 48 modules, **100** direct `hc(...)` calls and **42** `herdr(...)` calls, **81** `sys.exit(...)` calls and **78** `print(...)` calls in Layers 0–3, **13** `argparse.Namespace(...)` constructions, and **653** `pm.*` attribute replacements/patches across the 28 test files.
- **Core architecture**: Process-wide state moves into a single `Context` built once in `cli.main()` (and per test in unit tests). Layers 0–3 raise `PmError` subclasses and return structured values — zero `sys.exit`, zero `print`, zero `argparse.Namespace`, zero module-level mutable state.
- **Refinements from first principles** (where pass one's experience adjusts [`pm-py-refactor.md`](./pm-py-refactor.md) section 2.3):
  - **`HcHost` and `TuiHost` stay separate ports** on `Context` rather than forcing a single symmetric `Terminals` protocol: TUI panes lack labels, screen reads, key injection, `keep`, and event streams, while `dash_state` queries both hosts in one call. A shared `TerminalInfo` value object replaces 52 raw `hc("get", ...)` dict-digging sites.
  - **`Output` stays strictly in Layer 4**: services return structured results instead of writing to `ctx.out`, eliminating the five `redirect_stdout(io.StringIO())` wrappers commands currently need around internal calls.
  - **`AgentKind` uses declarative specs plus three concrete subclasses** (`ClaudeAgent`, `CodexAgent`, `PiAgent` over `GenericAgent`) rather than empty per-program files for agents with no custom logic.
  - **`Plan`, `Dependencies`, and `Question` stay pure functions plus typed request dataclasses** rather than stateless wrapper classes; `Family` and `Rollup` are already classes.
- **The hub (`cmd_update`)**: Splits into `Ledger.transition(task_id, request)` (plus explicit methods for the two silent fast-paths `--step-done` and `--subplan`) and `pmlib/reactions.py:after(ctx, transition)` executing today's 9 post-save steps in exact order, proved unchanged by a 14-branch reaction-trace suite and differential replay.
- **Pause-anywhere migration**: Seven stages. Stages 1–5 reshape `pmlib/` behind a temporary `legacy_context()` bridge while keeping the 8 `test_pm*.py` files untouched as a regression oracle; Stage 6 freezes production code, splits `test_pm.py` (10,282 lines, 39 `TestCase` classes) into module-level tests on `Context` + fakes, deletes `legacy_context()`, and shrinks `compat.py`; Stage 7 lands the three behavioral fixes on separate branches after user sign-off.

---

## 1. Where `pmlib` stands after pass one

All numbers below come from AST inspection of `mods/pm-dash/skill/scripts/` and `tests/test_install.py` on `main` (`7c10c07`).

### 1.1 Package size by layer

| Layer | Purpose | Modules | Lines | Notes |
| --- | --- | ---: | ---: | --- |
| 0 base | `osutil`, `config`, `context`, `__init__` | 4 | 272 | `errors.py` does not exist yet |
| 1 ports | `home`, `store`, `gitrepo`, `procs`, `terminals/*`, `agents/*` | 15 | 1,514 | 4 sibling `pm_*.py` files (5,278 lines) still sit beside `pm.py` |
| 2 domain | `ledger/*`, `project/*`, `caller`, `events/policy`, `memory/*` | 16 | 2,843 | Pure rules mixed with `context.*` reads and 22 `sys.exit` calls |
| 3 services | `events/*` (rest), `workers/*`, `review/*`, `manager/*`, `helpers/*`, `library`, `homemove`, `discord` | 36 | 7,716 | `reactions.py` does not exist yet; ~1,100 lines of service logic still sit in `commands/` |
| 4 interface | `cli`, `commands/*`, `hooks`, `views/*`, `compat` | 18 | 6,986 | `pm.py` launcher adds 50 lines outside `pmlib/` |
| **Total** | | **89** | **19,331** | Plus 5,278 lines in `pm_store.py`, `pm_project.py`, `pm_sessions.py`, `pm_events.py` |

### 1.2 Direct `context.*` global reads and writes

Outside `context.py` itself, `pmlib/` has **322 direct reads** and **0 writes** of the nine `context.*` process globals across **48 modules**:

| Global | Reads | Writes | What it holds today |
| --- | ---: | ---: | --- |
| `context.PANE` | 123 | 0 | `HERDR_PANE_ID` or `hc:<HC_TERMINAL_ID>` |
| `context.STATE` | 52 | 0 | Ledger home root (`PM_HOME`, `~/.claude/pm`, or `~/.dudu`) |
| `context.HC_TERMINAL` | 44 | 0 | `HC_TERMINAL_ID` |
| `context.TASKS` | 34 | 0 | `STATE / "tasks"` |
| `context.PMS` | 27 | 0 | `STATE / "pms"` |
| `context.WORKSPACE` | 14 | 0 | `HERDR_WORKSPACE_ID` |
| `context.PROJECTS` | 13 | 0 | `STATE / "projects"` |
| `context.INBOX` | 11 | 0 | `STATE / "inbox"` |
| `context.BOARD` | 4 | 0 | `STATE / "BOARD.md"` |
| **Total** | **322** | **0** | Across 48 of 89 modules |

Distribution across all 48 modules that read `context.*`:

| Layer | Module | Reads | Breakdown by global |
| --- | --- | ---: | --- |
| 0 | `config` | 1 | `STATE:1` |
| 1 | `home` | 12 | `PROJECTS:5, INBOX:2, STATE:2, BOARD:1, PMS:1, TASKS:1` |
| 1 | `store` | 4 | `PMS:1, PROJECTS:1, STATE:1, TASKS:1` |
| 1 | `procs` | 2 | `STATE:2` |
| 1 | `terminals/tabs` | 2 | `PANE:2` |
| 1 | `agents/sessions` | 1 | `STATE:1` |
| 2 | `caller` | 51 | `PANE:24, PMS:10, WORKSPACE:9, HC_TERMINAL:7, TASKS:1` |
| 2 | `project/project` | 9 | `PMS:7, STATE:1, WORKSPACE:1` |
| 2 | `ledger/ledger` | 6 | `PANE:3, TASKS:3` |
| 2 | `ledger/board` | 3 | `BOARD:1, STATE:1, TASKS:1` |
| 2 | `ledger/deps` | 2 | `TASKS:2` |
| 2 | `ledger/family` | 2 | `TASKS:2` |
| 3 | `workers/sessions` | 15 | `PANE:10, HC_TERMINAL:2, TASKS:2, PROJECTS:1` |
| 3 | `manager/seat` | 11 | `HC_TERMINAL:11` |
| 3 | `workers/lifecycle` | 11 | `PANE:7, TASKS:2, STATE:1, WORKSPACE:1` |
| 3 | `helpers/service` | 9 | `PANE:5, HC_TERMINAL:4` |
| 3 | `events/inbox` | 8 | `INBOX:8` |
| 3 | `helpers/records` | 6 | `PMS:2, TASKS:2, PROJECTS:1, STATE:1` |
| 3 | `workers/dispatch` | 6 | `PANE:6` |
| 3 | `workers/escalate` | 6 | `PANE:3, STATE:1, TASKS:1, WORKSPACE:1` |
| 3 | `discord` | 5 | `STATE:4, PANE:1` |
| 3 | `review/land` | 5 | `PANE:3, HC_TERMINAL:2` |
| 3 | `workers/wait` | 5 | `PANE:3, TASKS:2` |
| 3 | `events/deliver` | 4 | `TASKS:3, STATE:1` |
| 3 | `events/deliverer` | 4 | `PMS:2, STATE:1, TASKS:1` |
| 3 | `events/stalls` | 4 | `HC_TERMINAL:3, PANE:1` |
| 3 | `homemove` | 4 | `STATE:4` |
| 3 | `manager/launch` | 4 | `STATE:4` |
| 3 | `manager/rotate` | 4 | `HC_TERMINAL:2, STATE:2` |
| 3 | `workers/send` | 4 | `STATE:3, PANE:1` |
| 3 | `review/review` | 3 | `TASKS:3` |
| 3 | `workers/brief` | 3 | `STATE:2, TASKS:1` |
| 3 | `workers/reattach` | 3 | `STATE:2, TASKS:1` |
| 3 | `helpers/config` | 2 | `PANE:2` |
| 3 | `library` | 2 | `PROJECTS:2` |
| 3 | `workers/codex_pool` | 1 | `STATE:1` |
| 3 | `workers/research` | 1 | `PROJECTS:1` |
| 4 | `commands/manager` | 24 | `PANE:13, HC_TERMINAL:10, WORKSPACE:1` |
| 4 | `hooks` | 17 | `PANE:11, HC_TERMINAL:3, STATE:2, BOARD:1` |
| 4 | `commands/ledger` | 14 | `STATE:7, PANE:5, PROJECTS:1, WORKSPACE:1` |
| 4 | `commands/review` | 12 | `PANE:9, STATE:2, TASKS:1` |
| 4 | `commands/workers` | 9 | `PANE:4, TASKS:3, STATE:2` |
| 4 | `commands/events` | 5 | `PANE:4, INBOX:1` |
| 4 | `views/state` | 5 | `PMS:2, STATE:2, PROJECTS:1` |
| 4 | `views/status` | 5 | `PANE:2, PMS:2, BOARD:1` |
| 4 | `commands/helpers` | 3 | `PANE:2, STATE:1` |
| 4 | `commands/dispatch` | 2 | `PANE:2` |
| 4 | `commands/memory` | 1 | `TASKS:1` |

Other module-level process state sharing the same root cause:

- **Clock helpers in `context.py`**: 46 calls/references outside `context.py` (`now`: 40, `now_sec`: 4, `seconds_since`: 2).
- **Global `STORE` singleton**: 108 references across 24 modules (`store.STORE` wraps `context.*` in a zero-arg lambda).
- **Direct path arithmetic / `.glob(...)` over `context.<FOLDER>`**: 102 sites across 34 modules bypassing `Home` and `Store`.
- **Direct `os.environ` reads/writes**: 45 sites across 16 modules (4 in `context.py`, 41 scattered across `caller`, `manager/launch`, `commands/manager`, `workers/sessions`, `discord`, `hooks`, etc.).
- **Runtime-rebound module globals**: `caller._IDENTITY`, `caller._SESSION` (`global`), `ledger.ledger._PENDING_NOTES` (`global`), `workers.codex_pool._POOL_LOCK` (`global`), `workers.lifecycle.ENDING` (mutated dict), plus `caller.HERDR_PANE`, `hooks.TURN_LOG`, `agents.sessions.CLAUDE_PROJECTS`, `agents.sessions.CODEX_SESSIONS`, and `workers.brief.HERDR_DOCS` (evaluated at import time).
- **Import-time callback registries**: 6 module-level registries (`project._SEAT_CHECK`, `ledger.AFTER_SAVE`, `ledger._CALLER_PROJECTS`, `memory.layer._CANDIDATE_PRUNER`, `events.deliver._WATCHERS`, `events.deliver._HOLDS`) wired when `cli.py`, `ledger/board.py`, and `memory/candidates.py` are imported.

### 1.3 Direct `hc(...)`, `herdr(...)`, and host CLI calls

`hc(...)` is called directly **100 times** across 26 modules (4 inside `terminals/hc.py`, **96 outside `terminals/hc.py`**), plus **2** `hc_rpc(...)` calls in `terminals/tabs.py`. `herdr(...)` is called **42 times** across 14 modules (1 inside `terminals/tui.py`, **41 outside `terminals/tui.py`**), plus **3** raw `subprocess.run(["herdr", ...])` calls (`caller.py:52,69`, `events/inbox.py:81`) and **4** raw `subprocess.run(["herdr-app", ...])` calls (`terminals/tabs.py:29,42`, `manager/launch.py:307,390`).

| Module | Layer | `hc(...)` | `herdr(...)` | Raw host `subprocess` |
| --- | :---: | ---: | ---: | ---: |
| `terminals/hc` | 1 | 4 | 0 | 2 (`hc`, `hc connect`) |
| `terminals/tui` | 1 | 0 | 1 | 1 (`herdr`) |
| `terminals/tabs` | 1 | 2 (+2 `hc_rpc`) | 0 | 2 (`herdr-app`) |
| `terminals/screen` | 1 | 1 | 0 | 0 |
| `caller` | 2 | 3 | 1 | 2 (`herdr session/status`) |
| `project/project` | 2 | 1 | 0 | 0 |
| `workers/lifecycle` | 3 | 9 | 3 | 0 |
| `helpers/records` | 3 | 8 | 0 | 0 |
| `events/stalls` | 3 | 5 | 0 | 0 |
| `workers/send` | 3 | 5 | 0 | 0 |
| `workers/escalate` | 3 | 4 | 8 | 0 |
| `manager/claim` | 3 | 4 | 3 | 0 |
| `manager/seat` | 3 | 4 | 0 | 0 |
| `workers/reattach` | 3 | 3 | 3 | 0 |
| `helpers/watch` | 3 | 3 | 0 | 0 |
| `manager/launch` | 3 | 3 | 0 | 2 (`herdr-app`) |
| `events/deliverer` | 3 | 2 | 0 | 0 |
| `manager/rotate` | 3 | 1 | 10 | 0 |
| `events/inbox` | 3 | 0 | 2 | 1 (`herdr`) |
| `workers/codex_pool` | 3 | 1 | 0 | 0 |
| `workers/dispatch` | 3 | 1 | 0 | 0 |
| `workers/sessions` | 3 | 1 | 0 | 0 |
| `commands/manager` | 4 | 21 | 2 | 0 |
| `commands/workers` | 4 | 8 | 1 | 0 |
| `commands/review` | 4 | 3 | 0 | 0 |
| `commands/events` | 4 | 1 | 2 | 0 |
| `commands/dispatch` | 4 | 0 | 4 | 0 |
| `commands/helpers` | 4 | 1 | 0 | 0 |
| `commands/ledger` | 4 | 1 | 0 | 0 |
| `hooks` | 4 | 0 | 1 | 0 |
| `views/status` | 4 | 0 | 1 | 0 |
| **Total** | | **100** | **42** | **10** |

(`git(...)` has a similar profile: **37** calls across 8 modules — 9 inside `gitrepo.py` and **28** outside across `commands/review` [8], `review/land` [6], `views/status` [6], `workers/lifecycle` [5], `commands/dispatch` [1], `review/review` [1], `workers/codex_pool` [1] — plus **4** raw `subprocess.run(["git", ...])` calls outside `gitrepo.py` in `commands/review.py:564` and `workers/research.py:27,39,54`.)

### 1.4 `sys.exit` and `print` outside the command layer

Counting both boundaries — strict command adapters (`commands/*` + `cli.py`) versus the full Layer 4 interface (`cli.py`, `commands/*`, `views/*`, `hooks.py`):

- **`sys.exit(...)`**: **254** total in `pmlib/` (plus 2 in launcher `pm.py`, 0 in the 4 `pm_*.py` siblings; `cli.py` also has 2 `p.exit`, `commands/ledger.py` 1 `parser.error`, and `commands/workers.py` 1 `raise SystemExit`).
  - Inside `commands/*` + `cli.py`: **157**.
  - **Outside `commands/*` + `cli.py`**: **97** — **81 in Layers 0–3** (across 21 modules) and **16 in `views/*` + `hooks.py`** (including 3 import-time `pm_store`/`pm_project` missing-file guards).
- **`print(...)`**: **311** total in `pmlib/` (plus 1 in `pm_events.py`, 0 in `pm.py` and the other 3 siblings).
  - Inside `commands/*` + `cli.py`: **173**.
  - **Outside `commands/*` + `cli.py`**: **138** — **78 in Layers 0–3** (across 17 modules) and **60 in `views/*` + `hooks.py`**.

Per-module breakdown of all non-`commands/` `sys.exit` and `print` calls:

| Layer | Module | `sys.exit` | `print` | Notes |
| :---: | --- | ---: | ---: | --- |
| 1 | `agents/profiles` | 1 | 0 | Unknown profile in `worker_defaults` |
| 1 | `store` | 1 | 0 | Missing `pm_store.py` at import |
| 2 | `ledger/ledger` | 8 | 0 | Missing/ambiguous task in `load`, `_resolve_num_ref`, `mutate_task` |
| 2 | `ledger/deps` | 5 | 0 | Invalid/missing/cyclic `--depends-on` |
| 2 | `memory/candidates` | 4 | 3 | `adopt_memory_candidate` (belongs in Layer 3/4) |
| 2 | `ledger/family` | 3 | 0 | Invalid/missing/cyclic `--parent` in `parent_of` |
| 2 | `ledger/question` | 2 | 0 | `--option` validation in `quick_answers` |
| 3 | `workers/reattach` | 15 | 4 | Validation and CLI output inside `reattach` / `adopt` helpers |
| 3 | `workers/escalate` | 8 | 3 | Escalation validation and question-card output |
| 3 | `helpers/service` | 8 | 3 | Ownership authorization, owner lookup, helper hooks |
| 3 | `workers/codex_pool` | 4 | 1 | Unknown codex profile, pool notice |
| 3 | `workers/wait` | 3 | 9 | Timeout (exit 2), stopped-unreported (exit 3), report lines |
| 3 | `workers/lifecycle` | 3 | 4 | `retire_workspace` refusals and summary output |
| 3 | `manager/rotate` | 3 | 4 | `rotate_herdr` tab/start failures and status output |
| 3 | `discord` | 3 | 0 | Discord API / mirror configuration errors |
| 3 | `review/land` | 2 | 3 | `refuse()` (exit 2) and `stuck()` (exit 5) |
| 3 | `events/inbox` | 2 | 3 | `watch_notifications` in TUI |
| 3 | `manager/claim` | 1 | 7 | `end_pm` and claim helpers |
| 3 | `workers/send` | 1 | 3 | `send_back` queued/sent/failed (exit 1) |
| 3 | `helpers/config` | 1 | 0 | Invalid helper config |
| 3 | `helpers/records` | 1 | 7 | Wait guard and result formatting |
| 3 | `manager/launch` | 1 | 0 | Launch failure |
| 3 | `workers/dispatch` | 1 | 0 | `ask_escalation` / dispatch helper |
| 3 | `homemove` | 0 | 20 | Backup/migration progress lines |
| 3 | `events/deliver` | 0 | 2 | `took_delivery` repeat warning, `bring_pending` batch |
| 3 | `events/stalls` | 0 | 1 | `worker_stopped` Claude Stop-hook JSON block |
| 3 | `manager/handover` | 0 | 1 | `handover_full` |
| **0–3 subtotal** | **25 modules** | **81** | **78** | **Must all become `0` in pass two** |
| 4 | `views/project` | 9 | 1 | `cmd_project_session` |
| 4 | `views/status` | 5 | 46 | `status`, `show`, `board`, `diff`, `find`, `log` |
| 4 | `views/state` | 1 | 1 | 1 import guard + `cmd_state` JSON |
| 4 | `views/dash` | 0 | 3 | Local HTTP board URL |
| 4 | `hooks` | 1 | 9 | 1 import guard + hook stdout responses |
| **Layer 4 (`views`+`hooks`)** | **5 modules** | **16** | **60** | Interface layer: moves to `PmError` + `ctx.out` |
| 4 | `commands/*` (9 modules) + `cli` | 157 | 173 | Command adapters: thin wrappers over `ctx.out` and `cli.main()` |

### 1.5 Fake `argparse.Namespace` constructions and command-to-command calls

`pmlib/` constructs `argparse.Namespace(...)` at **13 sites**:

- **10 cross-command calls** building fake CLI namespaces to invoke another `cmd_*` function:
  1. `commands/dispatch.py:200` (`register_worker` → `ledger.cmd_new`)
  2. `commands/dispatch.py:256` (`ask_first` → `ledger.cmd_new`)
  3. `commands/ledger.py:424` (`cmd_update` → `workers.cmd_retire`, catching `SystemExit`)
  4. `commands/manager.py:365` (`cmd_start` → `cmd_claim`, catching `SystemExit` to kill the spawned terminal)
  5. `commands/manager.py:492` (`cmd_restore` → `cmd_start`, catching `SystemExit` to roll back task statuses)
  6. `commands/review.py:70` (`run_auto_review` → `cmd_review`, inside `redirect_stdout`/`redirect_stderr`, catching `SystemExit`)
  7. `commands/review.py:223→264` (`cmd_approve` → `helpers.cmd_helper_start`, inside `redirect_stdout`, catching `SystemExit`)
  8. `commands/review.py:362→385` (`cmd_triage` → `helpers.cmd_helper_start`, inside `redirect_stdout`)
  9. `commands/review.py:664` (`cmd_land` delegated merge → `workers.cmd_retire`, inside `redirect_stdout`, catching `SystemExit`)
  10. `commands/review.py:683` (`cmd_land` manager/CLI merge → `ledger.cmd_update`, inside `redirect_stdout`, slicing `splitlines()[1:]`)
- **3 mutable-bag constructions** feeding `worker_defaults` / `apply_codex_pool` / `worker_argv`, which mutate a `Namespace` in place:
  11. `commands/workers.py:252` (`cmd_codex_cmd`)
  12. `commands/workers.py:465` (`cmd_escalate`)
  13. `workers/reattach.py:104` (`reattach_plan`, inside Layer 3)
- Plus **3 direct `cmd_*` delegations** forwarding an already-parsed `a`: `commands/review.py:521` (`cmd_land --delegate` → `cmd_approve(a)`), `commands/project.py:375` (`cmd_project` → `cmd_project_session(a)`), and `commands/project.py:407` (`cmd_project` → `cmd_project_edit(a, slug)`).

### 1.6 Test suite coupling to `pm.*`

Across all **28 test files** (20,249 lines, **669 runtime test methods**):

- **`pm.X = ...` direct assignments**: **370** across **46** distinct names (plus **12** `setattr(pm, ...)` calls in `setUp`/cleanup helpers).
- **`mock.patch.object(pm, ...)`**: **283** (**277** literal attribute names across **81** distinct names + **6** loop sites patching `STATE`/`PMS`/`TASKS`/`PROJECTS`/`BOARD`/`INBOX`).
- **`mock.patch("pm....")`**: **0**.

By test file (the other 19 files under `scripts/tests/` and `tests/test_install.py` have **0** `pm.X = ...` and **0** `patch.object(pm, ...)`):

| Test file | Lines | Runtime tests | `pm.X = ...` | `patch.object(pm, ...)` | `setattr(pm, ...)` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `scripts/test_pm.py` | 10,282 | 397 | 306 | 201 | 11 |
| `scripts/test_pm_sessions.py` | 1,039 | 23 | 32 | 13 | 0 |
| `scripts/test_pm_project.py` | 955 | 13 | 0 | 22 | 0 |
| `scripts/test_pm_context.py` | 920 | 12 | 0 | 6 | 0 |
| `scripts/test_pm_store.py` | 920 | 19 | 0 | 13 | 0 |
| `scripts/test_pm_events.py` | 689 | 35 | 0 | 21 | 0 |
| `scripts/test_pm_delegate.py` | 633 | 15 | 18 | 1 | 0 |
| `scripts/test_pm_home.py` | 502 | 12 | 0 | 5 | 0 |
| `scripts/tests/test_caller_table.py` | 541 | 6 | 14 | 1 | 1 |
| 18 other `scripts/tests/test_*.py` | 2,659 | 96 | 0 | 0 | 0 |
| `tests/test_install.py` | 1,109 | 41 | 0 | 0 | 0 |
| **Total** | **20,249** | **669** | **370** | **283** | **12** |

Distribution of all **653** (`370 + 283`) `pm.*` replacements by the `pmlib` (or sibling) module that defines each name:

| Defining module | `pm.X = ...` | `patch.object` | Total | Names (`count`) |
| --- | ---: | ---: | ---: | --- |
| `context` | 143 | 32 | **175** | `PANE`(85), `HC_TERMINAL`(43), `WORKSPACE`(11), `STATE`(8), `PROJECTS`(6), `<loop:STATE..INBOX>`(6), `TASKS`(5), `PMS`(5), `BOARD`(3), `INBOX`(3) |
| `terminals/hc` | 58 | 64 | **122** | `hc`(116), `worker_state`(3), `hc_rpc`(2), `live_hc_terminals`(1) |
| `terminals/tui` | 42 | 15 | **57** | `herdr`(31), `agents`(26) |
| `events/deliver` | 22 | 10 | **32** | `deliver_later`(21), `SETTLE`(11) |
| `caller` | 23 | 9 | **32** | `HERDR_PANE`(13), `_IDENTITY`(7), `herdr_session`(4), `_SESSION`(3), `in_tui`(2), `check_role`(1), `current_pm_record`(1), `caller_projects`(1) |
| `workers/lifecycle` | 2 | 27 | **29** | `end_terminal`(21), `close_later`(5), `end_worker`(2), `retire_review`(1) |
| `workers/send` | 8 | 9 | **17** | `send_async_later`(8), `send_when_ready`(6), `send_ready_later`(3) |
| `agents/sessions` | 12 | 2 | **14** | `CLAUDE_PROJECTS`(7), `CODEX_SESSIONS`(7) |
| `manager/rotate` | 6 | 8 | **14** | `end_session_later`(5), `background_work`(5), `name_later`(2), `rotate_herdr`(2) |
| `hooks` | 11 | 1 | **12** | `TAKEN_IN_TAIL`(5), `TURN_LOG`(3), `TAKEN_IN_MORE`(3), `read_hook_stdin`(1) |
| `gitrepo` | 5 | 7 | **12** | `worktree_home`(6), `project_root`(2), `git_state`(2), `merge_target`(1), `git`(1) |
| `terminals/tabs` | 2 | 10 | **12** | `name_tab`(9), `worker_tab`(2), `rename_tab`(1) |
| `events/stalls` | 2 | 9 | **11** | `STALL_GRACE`(10), `worker_stopped`(1) |
| `manager/launch` | 5 | 6 | **11** | `start_pm_terminal`(7), `COMPACT_TOKENS`(2), `claude_dir`(1), `lean_settings`(1) |
| `osutil` | 0 | 11 | **11** | `pid_alive`(5), `stop_pid_group`(4), `WINDOWS`(1), `process_name`(1) |
| `project/project` | 0 | 9 | **9** | `find_pm`(5), `hc_pm`(2), `pm_record`(1), `app_pm`(1) |
| `workers/codex_pool` | 1 | 8 | **9** | `live_codex`(5), `_POOL_LOCK`(1), `hold_pool_lock`(1), `codex_fast`(1), `pool_started`(1) |
| `pm_events` (sibling) | 0 | 8 | **8** | `ChangeWaiter`(7), `replace_task_file`(1) |
| `ledger/ledger` | 0 | 8 | **8** | `all_tasks`(6), `save`(2) |
| `config` | 4 | 3 | **7** | `config`(7) |
| `events/deliverer` | 5 | 1 | **6** | `DELIVER_GONE`(2), `DELIVER_GAP`(2), `DELIVER_PAUSE`(1), `script_mark`(1) |
| `commands/manager` | 4 | 2 | **6** | `cmd_claim`(6) |
| `terminals/screen` | 0 | 5 | **5** | `screen_of`(4), `screen_line`(1) |
| `terminals/events` | 5 | 0 | **5** | `change_waiter`(5) |
| `workers/brief` | 4 | 0 | **4** | `HERDR_DOCS`(3), `outside_reads`(1) |
| `workers/reattach` | 0 | 4 | **4** | `start_beside_pm`(2), `offline_now`(1), `reattach_plan`(1) |
| `manager/seat` | 0 | 3 | **3** | `SEAT_START_WAIT`(1), `next_session_ready`(1), `seat_alive`(1) |
| `memory/layer` | 2 | 0 | **2** | `INDEX_LINES`(2) |
| `workers/escalate` | 0 | 2 | **2** | `quiet_old_worker`(2) |
| `workers/sessions` | 2 | 0 | **2** | `find_session`(2) |
| `workers/research` | 0 | 2 | **2** | `retire_dirty`(1), `collect_research`(1) |
| `workers/wait` | 2 | 0 | **2** | `wait_for_report`(2) |
| 8 modules w/ 1 each | 0 | 8 | **8** | `watched_agents`, `record`, `write_board`, `launcher`, `project_slug`, `review_brief`, `dispatch_hc`, `post_board` |

*(Note on `compat.py` today: constants of built-in type such as `STALL_GRACE`, `WINDOWS`, and `COMPACT_TOKENS` have `__module__ == "builtins"`, so `compat.holders()` currently sorts whichever alphabetical importer loaded them first — e.g. `commands.helpers` for `STALL_GRACE` — to index 0; fan-out still updates every holder, so tests work, and replacing globals with `Context` removes the issue completely.)*

Seven areas alone (`context`, `terminals/hc`, `terminals/tui`, `events/deliver`, `caller`, `workers/lifecycle`, `workers/send`) account for **464 of the 653 patches (71%)**.

---

## 2. Target objects, introduction order, and design trade-offs

Pass one proved a practical rule: **introduce an object only when concrete callers simplify because of it**. Applying that rule to [`pm-py-refactor.md`](./pm-py-refactor.md) section 2.3 keeps most of the proposed design, adds two missing pieces (`PmError` and `ManagerSessions`), and pushes back on four over-abstractions.

### 2.1 Pushback and adjustments to section 2.3

1. **Keep `HcHost` and `TuiHost` as two honest ports on `Context`, not one symmetric `Terminals` protocol.**
   Section 2.3 sketched a single `Terminals` protocol (`get, ls, run, send, keys, read, label, keep, kill, remove, interrupt, events`) implemented by `HcTerminals` and `TuiPanes`, selected per project by its registration. The actual code contradicts that symmetry in two ways:
   - **Disjoint capabilities**: Herdr TUI has no terminal labels, no `keep`, no `keys`, no `read` (screen classification is `hc`-only), no `interrupt`, and no `ChangeWaiter` stream (TUI uses file-backed `inbox/`), while `HcTerminals` has no `worktree create/remove`, `agent rename/prompt/wait`, `session list`, or `pane process-info`. Putting twelve methods on one protocol forces `NotImplementedError` stubs with zero callers (and per project direction, Herdr TUI is kept working as-is without new capabilities).
   - **Cross-host callers**: `dash_state()` queries *both* `tui.agents()` and `hc.ls(all=True)` in a single invocation because one ledger home can hold both TUI and desktop projects; `Caller` inspects its own host before any project registration is known; `retire_workspace` checks `herdr worktree list` even for git worktree cleanup.
   - **What to build instead**: Put `ctx.hc: HcHost` (wrapping `hc`, `hc_rpc`, `herdr-app` tab commands, and `ChangeWaiter` creation) and `ctx.tui: TuiHost` (wrapping `herdr` CLI and `herdr session list` / `status server`) directly on `Context`, paired with `FakeHc` and `FakeTui` in tests. Introduce **`TerminalInfo`** (typed dataclass over an `hc get` / `hc ls` row: `address`, `state`, `agent_state`, `status_msg`, `turn`, `labels`, `argv`, `foreground_argv`, `cwd`, `pid`, `status_ms`, `reported`, `is_shell`) — which has 50+ real callers — and keep runtime branching explicit in the three service methods that genuinely support both hosts (`find_manager`, `live_worker`, `end_worker`).

2. **Restrict `Output` to Layer 4; services return structured results instead of writing to `ctx.out`.**
   Section 2.6 allowed a Layer 3 service to *"return it or write to `ctx.out`"*. Today, functions printing directly is the exact reason `run_auto_review`, `cmd_approve`, `cmd_triage`, and `cmd_land` have to wrap internal calls in `with contextlib.redirect_stdout(io.StringIO())` and slice stdout lines (`commands/review.py:69,263,384,663,682`). If services write to `ctx.out`, callers still have to capture text buffers to compose operations.
   - **Rule for pass two**: Layers 0–2 never know `Output` exists. Layer 3 services **never print and never touch `ctx.out`**; they return typed result dataclasses carrying any side-note lines (e.g. `collected_research`, `closed_reviews`, `retire_summary`). Only Layer 4 (`cli.py`, `commands/*`, `views/*`, `hooks.py`) writes to `ctx.out` (`stdout` / `stderr`).

3. **`AgentKind`: spec-driven `GenericAgent` plus only the three subclasses with real behavior (`ClaudeAgent`, `CodexAgent`, `PiAgent`).**
   Section 2.2 listed `claude.py`, `codex.py`, `pi.py`, `generic.py` as one class per program. In `agents/base.py` today, `gemini`, `opencode`, and user-defined `config.json` `"agents"` entries differ *only* by declarative CLI flags (`argv`, `model`, `effort`, `prompt_arg`). Creating subclasses without distinct methods is dead boilerplate.
   - **What to build**: `AgentSpec` + `GenericAgent` in `agents/base.py` handling flag substitution, `takes_prompt`, `launch_wrap`, and `READY_MARKS`, plus three subclasses where behavior genuinely diverges:
     - `ClaudeAgent`: `--advisor`, `--fallback-model`, `NARROW`/`LEAN` manager flags, `native_memory_settings` (`autoMemoryDirectory`), reviewer/helper `--disallowedTools` + `--add-dir` settings, `--resume`, Stop-hook `{"decision": "block"}` continuation, `~/.claude/projects` session discovery (`claude_dir` / `claude_projects` on `Context` rather than module globals — note `workers/sessions.py` currently imports `CLAUDE_PROJECTS` and `CODEX_SESSIONS` via `from ..agents.sessions import ...`, so direct module tests that do not go through `compat.py` would miss a module-attribute patch until both move onto `Context`).
     - `CodexAgent`: `codex resume`, `codex_pm_compact` flags, `-p <provider>` pool injection, `~/.codex/sessions` discovery (`codex_sessions` on `Context`), `has_stop_hook = True`.
     - `PiAgent`: `pm_pi_compact.js` manager wrapper.
   - Also replace the `argparse.Namespace` bag mutated by `worker_defaults` and `apply_codex_pool` with an explicit `@dataclass class WorkerSpec` (`profile`, `kind`, `model`, `effort`, `advisor`, `advisor_dropped`, `fallback`, `codex_profile`, `provider`, `pool_said`, `preapproved`).

4. **Keep `plan.py`, `deps.py`, and `question.py` as pure functions plus request dataclasses; do not wrap stateless rules in extra classes.**
   `Family` and `Rollup` already landed in `ledger/family.py` as classes with pure table tests. By contrast, `parse_plan_steps`, `sync_plan_for_status`, `evaluate_depends_on`, and `quick_answers` are already cohesive functions. Wrapping stateless functions in `Plan` / `Dependencies` / `Question` classes has no caller asking for object identity. What `Ledger.create` and `Ledger.transition` *do* need are typed input values (`PlanInput`, `QuestionCard`) so validation moves off `argparse.Namespace`, plus removing the 10 `sys.exit` calls and 4 `context.TASKS` reads still inside `deps.py`, `family.py`, and `question.py`.

5. **Allow `helpers` → `workers` in Layer 3 (`ARROWS`) and move read-permission helpers to `agents/`.**
   Pass one had to leave `helper_brief` and 240 lines of `cmd_helper_start` inside `commands/helpers.py` (Layer 4) because `test_layers.py` forbade `helpers` from importing `workers`. Moving `outside_reads`, `read_settings`, and `docs_line` down to `agents/` (Layer 1, parameterized by `herdr_docs` path on `Context`) and adding `"workers"` to `ARROWS["helpers"]` (`events ← workers ← helpers ← review ← reactions`, strictly acyclic since `workers` never imports `helpers`) lets `Helpers(ctx).start(...)` live in `pmlib/helpers/service.py` (Layer 3), where `Landing` (`approve`, `triage`) and future memory consolidation (`autoDream`, [`pm-py-refactor.md`](./pm-py-refactor.md) section 6) can call it directly without `argparse.Namespace`.

6. **Add `ManagerSessions(ctx)` alongside the five services named in section 2.3.**
   `commands/manager.py` is 884 lines, holds 21 direct `hc(...)` calls and 24 `context.*` reads, and uses two fake-`Namespace` calls (`cmd_start → cmd_claim`, `cmd_restore → cmd_start` with `SystemExit` rollback). Grouping `claim`, `start`, `archive`, `restore`, `rotate`, and `handover` into `ManagerSessions(ctx)` in `pmlib/manager/` gives those callers typed methods and makes `commands/manager.py` thin.

### 2.2 Complete object table and introduction order

Objects are introduced strictly bottom-up so every new class is immediately consumed by the layer above it:

| Order | Object & Module | Owns | Replaces |
| :---: | --- | --- | --- |
| **1** | `PmError` (`Refused`, `NotFound`, `IdentityError`, `StoreError`, `VersionConflict`, `WaitOutcome`) in `pmlib/errors.py` (L0) | Structured domain/service failures with exit code (`1`, `2`, `3`, `4`, `5`, `128+sig`), optional JSON payload, and target stream | 81 `sys.exit` calls in Layers 0–3; `except SystemExit` control flow in `deliverer`, `review`, `ledger`, `manager`, `deps_watch` |
| **2** | `Home` & `ProjectFiles` in `pmlib/home.py`; moved-in `store.py`, `terminals/events.py`, `agents/sessions.py`, `views/project.py` (L1/L4) | Every path in the ledger home (`task`, `registration`, `project(slug)` → `ProjectFiles`, `sent`, `waits`, `locks`, `tmp`, `turn_log`, `reattach`, `inbox`, `board`, `config`) | `STATE`, `TASKS`, `PMS`, `PROJECTS`, `INBOX`, `BOARD`, 102 ad-hoc path sites, `FileStore`'s globals lambda, `SIBLINGS` table in `test_layers.py` |
| **3** | `Clock`, `Output`, `Config`, `Processes`, and `Context` in `context.py`, `config.py`, `procs.py` (L0–L1) | Process-wide state built once in `cli.main()` (or per test): `home`, `store`, `config`, `clock`, `out`, `procs`, `hc`, `tui`, `git`, `agents`, `caller`, `env`, plus injected hooks | All 322 `context.*` global reads, 46 `now`/`now_sec` calls, 108 `STORE` refs, 45 scattered `os.environ` reads, and all 6 import-time registration dicts |
| **4** | `TerminalInfo`, `HcHost`, `TuiHost` in `pmlib/terminals/` (L1) | Host queries and mutations (`get` → `TerminalInfo`, `ls`, `run`, `send`, `keys`, `read`, `label`, `keep`, `kill`, `remove`, `interrupt`, `name_tab`, `change_waiter`; TUI `agents`, `panes`, `sessions`, `worktrees`, `tabs`) | 100 `hc(...)` calls, 2 `hc_rpc(...)` calls, 42 `herdr(...)` calls, 7 raw `herdr`/`herdr-app` subprocess calls, 199 test patches on `pm.hc`/`pm.herdr`/`pm.agents`/`pm.name_tab` |
| **5** | `GitRepo` in `pmlib/gitrepo.py` (L1) | Repository queries, worktree creation/removal, `merge_no_commit`, `conflicts`, `undo_merge`, `git_state`, `worktree_home` | 37 `git(...)` calls, 4 raw `git` subprocess calls in `commands/review` and `workers/research`, 12 test patches on `pm.git*`/`pm.worktree_home` |
| **6** | `AgentKind` (`GenericAgent`, `ClaudeAgent`, `CodexAgent`, `PiAgent`), `AgentRegistry`, `WorkerSpec` in `pmlib/agents/` (L1) | Agent launch/resume/manager argv, prompt delivery mode, native memory settings, read/write tool restrictions, transcript paths (`claude_projects`, `codex_sessions`), profile resolution | `AGENT_KINDS` branching, `worker_defaults(Namespace)`, 14 test patches on `CLAUDE_PROJECTS`/`CODEX_SESSIONS`/`claude_dir` |
| **7** | `Task`, `Ledger`, `Change`, `Transition`, `PlanInput`, `QuestionCard` in `pmlib/ledger/` (L2) | Dict-preserving `Task` view (including `ATTACHED` moved from `workers/sessions.py`); `Ledger.load`, `create`, `change(id, fn)` with instance-scoped `Change.note`, `advance_step`, `update_subplan`, `transition` | `load`, `save`, `mutate_task`, `note`, `_PENDING_NOTES`, `AFTER_SAVE`, `_CALLER_PROJECTS`, `hc_terminal_of`, `pm_started`, `started_by_pm`, `needs_cleanup` |
| **8** | `Project`, `Coordinator`, `ProjectRegistry`, `Conversation` in `pmlib/project/` (L2) | Project metadata vs manager registration view over `pms/<slug>.json`, live manager lookup (with injected `seat_alive`), append/offset/tail conversation log | `pm_record`, `pm_records`, `find_pm`, `hc_pm`, `app_pm`, `pm_panes`, `registered_repo`, `_SEAT_CHECK`, `record`, `conversation`, `events_after` |
| **9** | `Caller` in `pmlib/caller.py` (L2) | Single-read `terminal_info`/`labels`, instance-cached TUI inventory, project-scoped `role_in(repo)`, `manages(repo)`, `check_guard(action, repo)` | `_IDENTITY`, `_SESSION`, `HERDR_PANE`, and the 12 separate identity functions in `caller.py` and `workers/sessions.py` |
| **10** | `MemoryLayer` in `pmlib/memory/layer.py` (L2) | Project or personal memory folder: `memories`, `read`, `remember(..., writer)`, `forget`, `restore`, `history`, `write_index`, `lock` | 20 module-level functions over `memory_dir(repo)`, `_CANDIDATE_PRUNER`, implicit `memory_writer` lookup |
| **11** | `Workers`, `Helpers`, `Deliverer`, `ManagerSessions`, `Reviews`, `Landing`, and `reactions` in Layer 3 | Typed service methods over `Context` and domain objects; explicit ordered post-transition reactions | All 13 `argparse.Namespace` sites, `ENDING` global, `_POOL_LOCK` global, `_WATCHERS`/`_HOLDS` globals, `redirect_stdout` captures, thick `commands/*` bodies |

Replacing the six import-time registration globals carried over from pass one: when `Context` builds its components, `ProjectRegistry` receives `seat_alive`, `Ledger` receives `caller_projects` and `after_save = [board.write, discord.post_board]`, `MemoryLayer` receives `candidates.prune`, and `Deliverer` receives `watchers = [helpers_watcher, deps_watcher]` and `holds = [seat.next_session_ready]`. No module mutates another module's global state on `import`.

---

## 3. Reshaping `cmd_update`: `Ledger.transition` and `reactions`

`cmd_update` (`pmlib/commands/ledger.py:186-456`, 271 lines) is the central hub of the ledger. Reshaping it without changing a single observable detail requires accounting for **every line it executes today**, including five behaviors in the live code that go beyond the high-level sketch in [`pm-py-refactor.md`](./pm-py-refactor.md) section 2.5.

### 3.1 Anatomy of `cmd_update` today

#### Phase A — Pre-lock validation, two silent fast-paths, and pre-lock probes (`lines 187–284`)

1. **Resolve and read snapshot** (`187–188`): `snapshot = load(a.id)`.
2. **Validate flags** (`189–212`):
   - `plan_input_from_args`: rejects mixing `--plan`/`--step` with `--outer-plan`/`--subplan`; routes `--plan`/`--step` to `subplan` when called by the task's non-manager worker from its own pane, else to outer `plan`.
   - `--send` without `--note` → refuses.
   - `--ask` without `--status blocked` → refuses.
   - Re-blocking an already-`blocked` task that the user has answered in `conversation.jsonl` without `--ask` → refuses.
   - `parent_of` validates existence and non-cyclicity of `--parent`; `parse_depends_on` validates existence and non-cyclicity of `--depends-on`; `quick_answers` validates `--option`/`--why`/`--recommend`.
3. **Two silent fast-paths that skip `BOARD.md`, skip `conversation.jsonl`, and run zero reactions** (`215–251`):
   - **Fast-path 1 (`--step-done` alone, `215–235`)**: calls `advance_outer_plan_step` + `remember_session` under `board=False`, prints `{id}: {status} (no outer plan | plan d/t...)`, and returns.
   - **Fast-path 2 (`--subplan` or worker `--plan` alone, `236–251`)**: updates/clears `subplan` + `remember_session` under `board=False`, prints `{id}: {status} (subplan d/t | subplan cleared)`, and returns.
   - *Design*: Expose these on `Ledger` as `Ledger.advance_step(task_id)` and `Ledger.update_subplan(task_id, steps)` (called by `cmd_update` when `UpdateRequest.is_step_done_only` / `is_subplan_only`), keeping `Ledger.transition` focused on logged transitions.
4. **Pre-lock probes** (`253–284`, plus git probe for auto-review):
   - If `snapshot.review_of` is set and `status == "done"`, reads parent's `auto_review` (`starting`/`running`) to attach `review_of`, `worker_commit`, `worker_note` to the event.
   - Computes `auto_resume_blocked`: `send and status is None and snapshot.status == "blocked" and is_pm_caller and blocked_by_worker`.
   - If moving into `in_progress` from another status on a local `hc` terminal, reads `pre_turn = hc.get(term).turn` *before* acquiring the task lock.
   - *(Improvement during reshape)* Pre-compute the git SHA / ahead count needed by `should_auto_review` before acquiring the file lock as well, re-checking task fields inside the lock so `git` never runs while holding `locks/<id>.lock`.

#### Phase B — Locked `Ledger.transition(task_id, request)` (`lines 287–393`)

Inside one `Ledger.change(task_id, ...)` critical section:

1. Apply `FIELDS` (`parent=""` deletes `parent`; changing `pane` clears `closed`; `status="blocked"` when already `blocked` still records `"status=blocked"` in `changes` for follow-up questions).
2. If `auto_resume_blocked` still holds on the locked record, append `"status=in_progress"` and set `status = "in_progress"`.
3. Apply `depends_on` (clearing `deps_notified` on any change), `plan`, `subplan`, `no_review`, and combined `step_done`.
4. If `moved` (`status=` in `changes`): clear `deps_notified` when `moved != "proposed"`, run `sync_plan_for_status`, clear `paused_from` / `escalating` / `adopting`, and if `"status=in_progress" in changes` on a local `hc` terminal call `round_starts(task, term, turn=pre_turn)`. Otherwise if `outer_steps` and `status == "in_progress"`, call `activate_first_todo`.
5. If `options` or any `status=` change, replace `QUESTION_FIELDS` with `asked`.
6. Evaluate `should_auto_review` → `(will_auto_review, resolved_sha, skip_reason)`.
7. If `note_text or changes or offered or plan_changed`: format entry text (appending `" (auto-review skipped: round limit reached)"` when applicable), compute `wake_fields`, suppress `wake=False` and set `task["auto_review"] = {"status": "starting", ...}` when `will_auto_review` (or suppress `wake=False` on `"duplicate running commit"`), set `handled_by="pm"` when manager unblocks a worker-blocked task, and record via `change.note(...)`.
8. Call `remember_session(task)`, save and unlock, flush pending `thread` event to `conversation.jsonl`, and run `after_save` (`BOARD.md`, then Discord mirror).
9. Return `Transition(before, after, changes, moved_status, entry_fields, will_auto_review, resolved_sha, request)`.

#### Phase C — Every post-save action in `cmd_update` today (`lines 394–456`)

Five subtleties in `commands/ledger.py:394-456` differ from or refine the summary table in [`pm-py-refactor.md`](./pm-py-refactor.md) section 2.5:

1. **Stdout ordering (`line 396`)**: `print(f"{task['id']}: {task['status']}")` runs **after** `deliver_later` (step 1) and **before** steps 2–9. `cmd_land` (`commands/review.py:688`) and tests depend on `<id>: <status>` being line 0 followed by reaction lines, even if step 4 (`send_back --wait`) later raises an error.
2. **Research collection statuses (`line 397`)**: triggers on `("review", "blocked", "done", "merged", "released")` whenever `status=` changed OR `--note` OR `--commit` was given — not only `"review" or "done"`.
3. **Post-merge `done` retirement (`lines 410–411`)**: `landed_done` (`"status=done" in changes and task.get("landed") and task.get("dispatched") and not task.get("retired") and not keep`) triggers full workspace retirement (`retire_workspace` / self-closing `close_later(..., retire=True)`), just like `status=merged`.
4. **Mutual exclusion of steps 5b, 6, and 7 (`lines 415, 427, 434`)**: `if auto or landed_done` / `elif closed and not keep` / `elif status=review` is a single `if/elif/elif` chain (`retire_workspace` already prunes memory candidates internally, so step 6 only runs when step 5b did not).
5. **Two dependency steps (`lines 441–455`)**: 9a updates `deps_notified` on the edited `proposed` task itself (and prints `"note: all dependencies of <id> are already met..."` to `stderr`), whereas 9b calls `reconcile_dependents_of(task["id"])` when `moved_status in ("merged", "released", "done", "abandoned")`.

### 3.2 Complete ordered `reactions` table (`pmlib/reactions.py`)

`cmd_update` prints `f"{tr.after.id}: {tr.after.status}"` immediately after `Ledger.transition` (or `reactions.after` emits messages via a callback flushed per step), and `reactions.after(ctx, tr)` runs the explicit ordered list below:

| Row | Exact condition on `Transition` (`tr`) | Reaction | Owner | Output / Control flow |
| :---: | --- | --- | --- | --- |
| `after_save` | Inside `Ledger.change` when task wrote and `board=True` | Flush `thread` event to `conversation.jsonl`; write `BOARD.md`; `discord.post_board()` | `ledger`, `discord` | None; continues |
| **1** | `tr.entry_fields.get("wake")` is True | `ctx.deliverer_starter.ensure_running(tr.after.repo)` (`deliver_later`) | `events.deliver` | None; continues |
| **2** | `tr.after.status in ("review", "blocked", "done", "merged", "released")` and (`tr.status_changed` or `tr.request.note` or `tr.request.commit`) | `collect_research(ctx, tr.after)` | `workers.research` | If collected: stdout `{id}: collected research: ...`; continues |
| **3** | `tr.will_auto_review` is True | `Reviews(ctx).run_auto_review(tr.after.id, commit, tr.resolved_sha, note)` | `review.review` | Stdout `{id}: auto-review started\|failed ...`; **stops here (`halt=True`)** |
| **4** | `tr.request.send` is True | `Workers(ctx).send_back(tr.after, tr.request.note, wait=tr.request.wait)` | `workers.send` | Stdout queued/sent line (or failure line + raises `PmError(code=1)`) |
| **5a** | `"status=merged" in tr.changes` and not `auto_retire` | `Workers(ctx).retire_review(tr.after)` | `workers.lifecycle` | If closed: stdout `{id}: closed ...`; continues |
| **5b** | `auto_retire` (`"status=merged"` + `dispatched` + `not keep`) or `landed_done` (`"status=done"` + `landed` + `dispatched` + `not retired` + `not keep`) | Self-terminal: `close_later(..., retire=True)`; else `Workers(ctx).retire(tr.after.id, force=False)` catching `Refused` into `not retired: ...` | `workers.lifecycle` | Stdout retire summary or self-close / `not retired:` notice; skips 6 & 7 |
| **6** | Not 5b, and `tr.moved_status in CLOSED` (`merged`, `released`, `done`, `abandoned`) and `not tr.request.keep` | `Workers(ctx).close_worker(tr.after)` + `MemoryCandidates(ctx).prune(repo, finished=...)` | `workers.lifecycle`, `memory.candidates` | If ended: stdout `{id}: {ended}`; skips 7 |
| **7** | Not 5b/6, and `"status=review" in tr.changes` | `ended = Workers(ctx).close_reported(tr.after)`; if `ended`, log note on task | `workers.lifecycle`, `ledger` | Writes task note; continues |
| **8** | `tr.after.review_of` and `"status=done" in tr.changes` | `Reviews(ctx).sync_parent_on_review_done(tr.after.review_of, tr.after.id, note)` | `review.review` | None; continues |
| **9a** | `tr.request.depends_on is not None` and `tr.request.depends_on != []` and `tr.after.status == "proposed"` | Evaluate `depends_on`, store `deps_notified` (`board=False`), emit ready hint if all met | `events.deps_watch` | If ready: **stderr** `note: all dependencies of {id} are already met...` |
| **9b** | `tr.moved_status in ("merged", "released", "done", "abandoned")` | `reconcile_dependents_of(ctx, tr.after.id, primary_repo=tr.after.repo)` | `events.deps_watch` | None; continues |
| **10** *(Stage 7b)* | `tr.moved_status in CLOSED` and `tr.after.parent` | Roll up parent via `Family.rollup(..., own_session_live=...)` (Section 5.1) | `ledger.family` via `reactions` | **Not wired in Stage 5**; added as its own behavioral stage (Stage 7b) |

How other commands share `Ledger.transition` + `reactions`:

- **`Landing.land` (manager/CLI path, no post-merge steps)**: replaces `cmd_update(Namespace(status="merged", commit=sha, keep=keep, note=...))` with `Ledger.transition` + `reactions.after`, receiving the reaction messages directly instead of `redirect_stdout` + `splitlines()[1:]`.
- **`Landing.land` (delegated worker/helper path, no post-merge steps)**: passes `landed={...}`, `clear_land_approved=True`, `source=caller_role` into `Ledger.transition` + `reactions.after`, deleting 45 lines of hand-copied post-merge cleanup in `commands/review.py:630-675`. *(Note: the hand-copied delegated path today omitted row 9b `reconcile_dependents_of`, relying on the deliverer's periodic watcher instead; sharing `reactions.after` reconciles dependents immediately on delegated merge too. Check `test_pm_delegate.py` when wiring; if strict zero-diff is desired in Stage 5, gate row 9b or verify `test_pm_delegate.py` and `replay.py` pass unchanged.)*
- **`archive` / `restore`**: `status="paused"` (and restoring from `paused`) with `source="pm", wake=False` triggers none of rows 1–9 except `9b` if a task was paused from a closed status (impossible: `ARCHIVE_PAUSES` is open statuses only), so `Ledger.transition` applies cleanly.

### 3.3 Verifying zero behavioral change on `cmd_update`

`replay.py` already exercises `update` across blocked question cards, unblocking with `--branch`/`--plan`, `--depends-on` edits on `proposed` tasks (row 9a), silent worker `--plan` subplans (fast-path 2), waking worker `review` reports (row 1), field-only updates, `merged --keep`, `abandoned` (row 9b), and `land`'s three outcomes (failed check exit 1, clean merge exit 0, conflict exit 4).

It does **not** cover fast-path 1 (`--step-done`), row 2 (`collect_research` with files present), row 3 (`will_auto_review` early return and round-limit skip), row 4 (`--send` + `auto_resume_blocked`), row 5a/5b (`merged` and `landed_done` without `--keep`, plus self-closing worker), row 6 (`close_on_close` + `prune_candidates`), row 7 (`close_reported`), or row 8 (`<id>-review` `done` syncing parent plan).

Before changing a single line of `cmd_update` in Stage 5:

1. Add **`scripts/tests/test_transition_reactions.py`** (commit 1 of Stage 5, run against the *unmodified* `cmd_update` first): a 14-case characterization suite exercising both silent fast-paths, every reaction row 1–9b, the `3` early-return cutoff, the `5b / 6 / 7` mutual exclusion, and synchronous `--send --wait` failure, asserting byte-for-byte stdout, stderr, exit code, `tasks/*.json`, `conversation.jsonl`, `BOARD.md`, and the exact ordered list of host/process calls.
2. Run **differential replay (`replay.py`)** against `main` plus all **669 unit tests** (including `TwoLayerPlanAndAutoReview`, `ResearchCollectionTests`, `CloseWorkers`, `TaskDependencies`, `PmQuestionCardsAndStaleBlockedTest`, and `test_pm_delegate.py`) on the reshaped commit, requiring zero diffs.

---

## 4. Migrating the test suite and shrinking `compat.py`

### 4.1 Inverting the source of truth without a flag day (`legacy_context()`)

In pass one ([`pm-py-refactor.md`](./pm-py-refactor.md) section 4.1 rule 3), module globals (`context.PANE`, `context.STATE`, `terminals.hc.hc`) remained the source of truth and new objects (`Home.current()`, `Caller.current()`) read them on every call so `pm.X = ...` patches kept working.

Pass two inverts this cleanly in two steps without ever breaking `main`:

1. **Inside reshaped `pmlib/` classes (Stages 1–5): zero globals.**
   `Context`, `Home`, `FileStore`, `HcHost`, `TuiHost`, `GitRepo`, `AgentRegistry`, `Ledger`, `ProjectRegistry`, `Caller`, `MemoryLayer`, and all Layer 3 services accept explicit constructor dependencies (`ctx` or specific ports). None of them imports `context.PANE`, `context.STATE`, or module-level `hc`/`herdr`.
   - `cli.main()` constructs `ctx = Context.from_env()` once per invocation and passes `ctx` to command handlers.
   - New tests in `scripts/tests/` construct `ctx = make_ctx(tmp_dir, hc=FakeHc(...), tui=FakeTui(...), clock=FakeClock())` directly — structural isolation makes running against `~/.dudu` or `~/.claude/pm` impossible even without `assert_temporary_ledger()`.
2. **At legacy module-level entry points (Stages 1–5 only): `legacy_context()` bridge.**
   While `test_pm*.py` still calls `pm.cmd_update(a)` or `pm.load(id)` after mutating `pm.PANE = "hc:t7"` and `pm.hc = fake_hc`, the legacy module-level wrapper functions (`def load(task_id, *, repo=None): return Ledger(legacy_context()).load(...)`) build a lightweight bridge `Context` whose `Home` reads `context.STATE/TASKS/PMS/PROJECTS/INBOX/BOARD` and whose `HcHost`/`TuiHost` delegate to the current module-level `terminals.hc.hc` / `terminals.tui.herdr` callables (and whose `deliver_later`, `end_terminal`, `send_async_later`, etc. resolve through module attributes while `legacy_context` is active).
   - **Why keep `test_pm*.py` untouched during Stages 1–5?** Modifying production code *and* rewriting its test in the same PR weakens the safety net: a subtle bug in the test rewrite can mask a regression in the code reshape. Keeping all 526 tests in the 8 `test_pm*.py` files frozen throughout Stages 1–5 proves every object/service reshape against the original test suite, while new `Context`-based unit tests are added alongside in `scripts/tests/`.
   - **Then in Stage 6, freeze production code and migrate tests.** Each Stage 6 cut moves a batch of `TestCase` classes out of `test_pm*.py` into `scripts/tests/test_<area>.py` using `make_ctx` and `tests/fakes.py`, verifying the total test count never decreases. Once the last `test_pm*.py` file is emptied and removed in Stage 6c, `legacy_context()` and the `context.*` globals are deleted.

### 4.2 Shared test doubles (`mods/pm-dash/skill/scripts/tests/fakes.py`)

Built in Stage 1b so every subsequent stage and test migration uses one set of fakes instead of ad-hoc lambdas:

- **`FakeHc`**: in-memory terminal table (`address → dict`), call log, scripted multi-look state queues (`terms["t7"] = [working, idle]` as `Events` in `test_pm.py` uses today), `--if idle` checking on `send`, `{"ok": True, "started": True}` replies, `hc_rpc` hook, and deterministic `FakeChangeWaiter` integration. Replaces 122 patches on `terminals/hc` and 12 on `terminals/tabs`.
- **`FakeTui`**: in-memory `sessions`, `workspaces`, `panes`, `agents`, and `worktrees`. Replaces 57 patches on `terminals/tui` and 17 TUI patches on `caller`.
- **`FakeProcs`**: records detached background `pm.py` spawns (`deliver`, `_deliver-send`, `_deliver-ready`, `close-worker`, `name-agent`, `end-session`) and can run them inline on demand. Replaces the three import-time monkeypatches at `test_pm.py:58-62` (`deliver_later`, `send_async_later`, `send_ready_later` — 32 patches) plus `close_later`, `end_session_later`, and `name_later` (12 patches).
- **`FakeClock`**: controllable wall time (`datetime`), `monotonic()`, and `sleep(dt)` (advances virtual clock without sleeping). Replaces `SETTLE = 0` (11 patches), `STALL_GRACE = 0` (10 patches), `DELIVER_GAP`/`DELIVER_GONE`/`DELIVER_PAUSE` (5 patches), and `datetime` monkeypatches.
- **`make_ctx(tmp_dir, *, pane="", hc=None, tui=None, config=None, ...)`**: builds a complete `Context` rooted at `Home(tmp_dir)` with real `FileStore` and real `GitRepo` (or optional `StubGit`), empty `herdr_docs` / `claude_projects` / `codex_sessions` folders under `tmp_dir`, and `BufferOutput`.

### 4.3 Splitting `test_pm.py` (10,282 lines, 39 `TestCase` classes) and the 7 `test_pm_*.py` files

All 39 `TestCase` classes in `test_pm.py` (397 tests) and the 7 sibling `test_pm_*.py` files (129 tests) map cleanly onto module-aligned files under `mods/pm-dash/skill/scripts/tests/`:

| Wave | Target file under `scripts/tests/` | Source classes / files | Lines | Tests | Current `pm.*` patches |
| :---: | --- | --- | ---: | ---: | ---: |
| **6a** | `test_osutil_procs.py` | `WindowsCommandLines` (`test_pm.py`) | 101 | 7 | Low (1) |
| **6a** | `test_tabs_events.py` | `TabText`, `TabWithoutApp`, `EventWaitHc` (`test_pm.py`) + `test_pm_events.py` (waiter half) | ~440 | 28 | Low (12) |
| **6a** | `test_store_locks.py` | `WithoutFcntl` (`test_pm.py`) + `test_pm_store.py` | 958 | 21 | Low (13) |
| **6a** | `test_homemove.py` | `test_pm_home.py` | 502 | 12 | Low (5) |
| **6a** | `test_agents_profiles.py` | `LaunchArgs`, `Pool`, `Fast` (`test_pm.py`) + `test_pm_sessions.py` | 1,190 | 45 | Medium (61) |
| **6a** | `test_ledger_transitions.py` | `SubThreads`, `ConversationLog`, `TaskNumbersTests`, `TwoLayerPlanAndAutoReview` (`test_pm.py`) | 1,158 | 21 | Low (5) |
| **6a** | `test_memory.py` | `Memory` (`test_pm.py`) | 363 | 17 | 0 |
| **6a** | `test_caller.py` | `DevMachine` (`test_pm.py`) + `tests/test_caller_table.py` | 877 | 25 | Medium (48) |
| **6a** | `test_views.py` | `LightOutput`, `ProjectView` (`test_pm.py`) + `test_pm_project.py` + `test_pm_context.py` | 2,177 | 38 | Medium (30) |
| **6a** | `test_hooks.py` | `TakenIn`, `TerminalUI`, `PmQuestionCardsAndStaleBlockedTest` (`test_pm.py`) | 974 | 40 | Medium (42) |
| **6b** | `test_workers_dispatch.py` | `Commands`, `SendBrief`, `Profiles`, `OutsideReads`, `WorkerTabs`, `TakeUp`, `DeepPreapproval` (`test_pm.py`) | 1,363 | 68 | High (95) |
| **6b** | `test_workers_lifecycle.py` | `ReportAndWait`, `Offline`, `CloseWorkers` (`test_pm.py`) | 625 | 39 | High (62) |
| **6b** | `test_helpers.py` | `Helpers` (`test_pm.py`) | 721 | 19 | Medium (25) |
| **6b** | `test_review_land.py` | `LandAndReview`, `ResearchCollectionTests`, `ReviewChainAndStateHelpers` (`test_pm.py`) + `test_pm_delegate.py` | 1,562 | 39 | High (68) |
| **6c** | `test_deliverer.py` | `Events`, `TaskDependencies` (`test_pm.py`) + `test_pm_events.py` (inbox/watch half) | 1,556 | 62 | High (110) |
| **6c** | `test_manager_seat.py` | `Rotation`, `ProjectLifecycle`, `SeamlessRotation`, `PMSeatAndAdopt` (`test_pm.py`) | 1,579 | 51 | High (76) |

*(Bonus fixed in 6a: `TakenIn` currently has 1 failure when run standalone because of module-level state left by earlier classes in `test_pm.py`; giving each test its own `Context` eliminates cross-test pollution.)*

### 4.4 When `compat.py` shrinks

`pmlib/compat.py` shrinks in two concrete steps:

1. **After Stage 6a (explicit export list)**: Replace `pkgutil.walk_packages` wildcard scanning in `compat.py` with an explicit `COMPAT_EXPORTS` mapping covering only the symbols still referenced by `test_pm.py` (Waves 6b–6c) and `tests/test_install.py`. This immediately drops the package-wide rule that private helpers (`_foo`) cannot share a name across two unrelated `pmlib` modules.
2. **At the end of Stage 6c (minimal public facade)**: Once all 8 `test_pm*.py` files are migrated into `scripts/tests/` and deleted:
   - Delete `legacy_context()`, the 9 module-level globals in `context.py`, `store.STORE`, and the `__setattr__` fan-out machinery in `compat.py`.
   - Keep `scripts/pm.py`'s `import pm` branch (`_pmlib("pmlib.compat").install(...)`) exposing a small static surface (`main`, `build_parser`, `Context`, `Home`, `WINDOWS` for `tests/test_install.py`), plus the four 1-line sibling re-export files (`pm_store.py`, `pm_project.py`, `pm_sessions.py`, `pm_events.py`) required by [`pm-py-refactor.md`](./pm-py-refactor.md) section 3.6.

---

## 5. Three behavioral fixes on separate branches

Per rule 5 of [`pm-py-refactor.md`](./pm-py-refactor.md) section 4.1, none of these three behavioral changes is mixed into a structural reshape commit. Each runs as its own branch in Stage 7 (after Stages 1–6 finish with zero differential-replay diffs), reviewed independently.

### 5.1 Parent task automatic roll-up (`#210`: `ledger/family.py` + `reactions.py`)

- **Current behavior**:
  - `Family.rollup(active, closed)` in `pmlib/ledger/family.py:112-143` is dead code (called nowhere). When a parent's child tasks (`child["parent"] == parent_id`) all close, the parent stays `in_progress` or `proposed` forever until closed by hand.
  - Furthermore, `_parent_has_own_work(parent)` (`family.py:62-68`) checks `dispatched`, `worker`, `worker_pane`, `agent`, `branch`, and `has_unfinished_plan(parent)`, **ignoring `parent["pane"]`, `parent["helpers"]`, and `parent["status"] == "review"`**. A task registered by a non-manager session for its own work (`pm.py new` from a standalone terminal — 104 tasks in the real ledger when 3b was reviewed) carries only `pane`. If that session splits out a child task and the child finishes while the parent's own session is still live in `pane`, `_parent_has_own_work` returns `False` and would wrongly propose closing the parent.
- **Target change**:
  1. **Fix "parent has work of its own" while keeping `Family.rollup` pure (Layer 2)**:
     - Add `own_session_live: bool = False` to `Family.rollup(active, closed, *, own_session_live=False)`.
     - Treat `own_session_live`, `parent.get("status") == "review"`, or any running helper (`any(h.get("status") == "running" for h in parent.get("helpers") or [])`) as `_parent_has_own_work` → `Rollup(action="notify", reason="parent_has_work", ...)`.
     - In Layer 3 (`reactions.py`), compute `own_session_live` before calling `rollup`: True when `parent.pane` is non-empty, is **not** in `projects.pm_panes(parent.repo)` (a task parked on the manager's own terminal has no separate session), and `Workers(ctx).is_pane_live(parent.pane)` is True (local `hc` terminal `state == "live"`, live TUI agent in `pane`, or remote `machine/term`).
  2. **Wire row 10 in `reactions.py` with lock-safe deduplication and bounded ancestor cascade**:
     - When `tr.moved_status in CLOSED` and `tr.after.parent`: lock `parent_id`, re-read `parent` and all project tasks, and evaluate `Family.from_tasks(parent, tasks).rollup(ACTIVE, CLOSED, own_session_live=...)`.
     - Compute a state key over sorted `(child_id, child_status)` pairs (`rollup_notified` on `parent`, cleared if a new child is added or reopened) so two children closing concurrently never emit duplicate notices.
     - On `action == "close"` (if approved below): transition `parent` to `done` with `text=f"status=done; {rollup.summary}"`, `source="rollup"`, `wake=True` (when `app_pm`), run `reconcile_dependents_of(parent_id)`, and walk `parent.parent` up to depth 5 (cycle-guarded).
     - On `action == "notify"`: record `rollup_notified = key` on `parent` (`board=False`), append a waking `event` (`source="rollup"`, `task=parent_id`, `text=rollup.summary`, `wake=bool(app_pm)`), and call `deliver_later`.
- **Requires user decision (Decision 1)**: When all children of a parent finish (at least one not `abandoned`) and the parent has no work of its own, should `pm.py` **(Recommended) automatically close the parent as `done` and wake the manager**, or **only send a waking `rollup` event and leave closing the parent to the manager**?

### 5.2 Background commands holding back delivery and misreporting `wait` (section 5.7)

- **Current behavior**:
  - **Manager delivery freezes (`events/deliverer.py:97-99`)**: When a Claude Code manager session has a background shell command running after its model turn has ended, its terminal keeps reporting OSC 7501 `{"state": "working", "msg": "1 shell still running"}`. `deliver_look` requires `state in ("idle", "done")`, so it withholds all batches indefinitely (85 minutes in the 2026-11-22 incident) with no notice in the project conversation.
  - **`pm.py wait` and unhooked worker stall detection false-alarm (`workers/wait.py:60-83`, `events/stalls.py:86-104`)**: Conversely, when a worker's foreground turn ends (`status.state` becomes `"done"` or `"idle"`) while a background command it started is still running under its terminal process tree, `worker_state(term)` returns `"done"`/`"idle"`. After 5 seconds, `pm.py wait` exits 3 claiming `"the worker stopped (done) without reporting"`, and for unhooked agents (`agy`, `pi`) `stop_state` records a false stall. (Claude Code's Stop hook avoids the stall only because hook stdin carries `background_tasks`.)
- **Target change**:
  1. **Separate `turn_active` from `background_active` on `TerminalInfo` and in `osutil` / `procs`**:
     - Move `background_work(info)` from `manager/rotate.py` down to `procs.py` (Layer 1) so `events`, `workers`, and `manager` can all query live background child commands under a terminal's PID.
     - For **workers (`wait.py` and `stalls.py:stop_state`)**: when `status.state in ("idle", "done")`, check whether the terminal still has active background child commands; while it does, treat the worker as still working (resetting `stopped_at` in `wait` and returning `""` from `stop_state`).
     - For **manager delivery (`events/policy.py` + `events/deliverer.py`)**: extract a pure policy `manager_ready_for_batch(term_info, last_turn_stopped)` that returns `(ready: bool, if_idle_flag: bool)`. `ready` is True when `term_info.agent_state in ("idle", "done")`, OR when `term_info.agent_state == "working"` solely due to background shells (`"shell still running"` / `"shells still running"` in `status_msg`) **and** the manager's `Stop` hook has already fired after its latest `UserPromptSubmit` (`turns.log` / `turn-cause`). When sending in that background-shell state, omit `--if idle` (which `hc` would reject because `hc` sees `working`).
     - **Mandatory pre-implementation probe (see [Not verified](#not-verified))**: Before coding the `hc send` call for the background-shell case, Stage 7c must run a disposable `hc` terminal probe to verify what `hc send <term> <text>` returns in JSON (`"started"` field and draft-holding behavior) when `hc get` already reports `status.state == "working"`.
  2. **Delivery delay notice (`events/deliverer.py`)**:
     - Track `waiting_since` for an undelivered non-empty batch. If a batch waits longer than `deliver_warn_seconds` (default 900 s / 15 min) because the manager terminal is busy, at a dialog, or held back, record a one-shot `event` (`source="deliver-stall"`, `wake=False`) in `conversation.jsonl` naming the terminal's state/message so the user sees it in the Project view instead of silent stalling.
- **Requires user decision (Decision 2)**: Approve fixing both sides of background-command status (`deliver` + `wait`/`stalls`) plus the 15-minute delivery-delay conversation notice as Stage 7c (gated on the live `hc send` probe)?

### 5.3 Unifying the three identity and news-policy contradictions (`caller.py` + `events/policy.py`)

`tests/test_caller_table.py` and `tests/test_policy.py` pin three contradictions in today's code (plus two `Caller` gaps left by pass one):

1. **Moved manager terminal (`moved_hc`, `moved_tui`)**:
   - *Today*: When `pms/proj.json` still names `hc:tPM` (or TUI `w1:p1`), but live `hc` labels it `pm=other` (or TUI runs `pm-other` in `other/`), `guard` (`check_role`) returns `"uncertain"` and refuses mutations, `own_pm_record` returns `None` in `moved_tui` but `'pm-proj'` in `moved_hc`, and `is_pm_caller`, `memory_writer`, `wake_fields` (`source: "pm"`), and `Caller.role_in` all still treat the terminal as `proj`'s manager.
   - *Change*: `Caller.manages(repo)` checks live host facts when available: if `hc` reports a live `pm=<slug>` label naming a *different* project, or TUI's live agent/cwd belongs to a different project, `manages(repo)` is `False` (`own_pm_record` returns `None` in both `moved_hc` and `moved_tui`; `role_in(repo)` returns `SESSION`, while `guard` continues returning `"uncertain"` so stale registrations cannot mutate as a worker either).
2. **Helpers recognized as three different roles + `Caller.role_in(project)` ignoring `project`**:
   - *Today*: On a helper terminal (`helper=look`, `helper.of=w-1`, `helper.project=proj`), `Caller.role_in` and `_helper_caller_identity` say `"helper"`, `memory_writer` says `("other", "session:hc:tH")`, and `wake_fields` says `{"source": "session"}` — **never** emitting `"source": "helper"` even though `is_news` (`policy.py:95`), `pending_items` (`policy.py:163`), and [`pm-py-refactor.md`](./pm-py-refactor.md) section 5.3 check `source in ("worker", "helper")`. Meanwhile `Caller.role_in(project)` ignores `project` when returning `WORKER`/`REVIEWER`/`HELPER` (a worker of project A is called `WORKER` in project B), and `Caller.labels` is unused by `own_task`/`helper_self_info` (causing 3 `hc get` calls instead of 1).
   - *Change*: `Caller` reads `hc.get(terminal)` at most once (`terminal_info` / `labels` shared by `own_task` and `helper`); `Caller.role_in(repo)` scopes `WORKER`/`REVIEWER` (`in_scope(mine["repo"], repo)`) and `HELPER` (`helper.project == project_slug(repo)`) to `repo`; `wake_rule` maps `Role.HELPER` to `source: "helper"` (waking on reports just like `Role.WORKER`); `memory_writer` maps `Role.HELPER` to `("helper", f"helper:{name}")` with worker-level write rules (pitfalls and references only).
3. **`wake_rule` vs `is_news` on `done` and `proposed`**:
   - *Today*: For a non-status-moving report (`--commit` or `--note`) by a worker, `wake_rule` (`policy.py:61`) sets `wake=True` only when `task.status in ("review", "blocked")`, leaving `"wake"` absent on `done` and `proposed`. Because `"wake"` is absent (not `False`), `is_news` (`policy.py:96-106`) falls through to `e.get("status") in WAKING` (`review, blocked, done, proposed`) and returns `True` on `done` and `proposed`.
   - *Why `done` matters (`test_pm.py:6101`)*: Reviewers close `<id>-review` with `--status done`. `test_pm.py:6101` (`# a reviewer, again`) explicitly tests a reviewer sending a follow-up amended finding on an already-`done` review thread (`pm.py update <id>-review --note "以这条为准..."`). Today `wake_rule` fails to set `wake=True` on that amended review report, so `cmd_update` never starts `deliver_later`! Conversely, on a `proposed` task, a non-moving note should not wake.
   - *Change*: Align both `wake_rule` and `is_news`: a non-status-moving report (`--commit` or `--note`) from a `worker`/`reviewer`/`helper` wakes when the task is in `("review", "blocked", "done")` (and does **not** wake on `"proposed"` unless the entry registered or moved the task); `wake_fields` writes explicit `"wake": False` on non-waking `thread` entries when `app_pm` exists so writer and reader never diverge.
- **Requires user decision (Decision 3)**: Confirm these three unified rules for Stage 7a?

---

## 6. Staged plan and verification

### 6.1 Stages, parallelism, size, and risks

Every stage merges cleanly to `main` with all 669+ unit tests, `test_layers.py`, `test_cli_surface.py`, `test_install.py`, and differential replay passing.

```text
Stage 1 (Errors, Home, Sibling Move-in, Context, Fakes)
   ├──► Stage 2a (HcHost, TuiHost, TerminalInfo, GitRepo) ─┐
   └──► Stage 2b (AgentKind, AgentRegistry, WorkerSpec)   ─┼──► Stage 3a (Task, Ledger, Project, Conversation)
                                                           │       ├──► Stage 3b (Caller inversion)
                                                           │       └──► Stage 3c (MemoryLayer, Library, Homemove, Discord)
                                                           ▼
        ┌── Stage 4a (Workers service) ────────────────────┐
        ├── Stage 4b (Helpers service, after 4a) ──────────┼──► Stage 5 (Reviews, Landing, Ledger.transition + reactions)
        ├── Stage 4c (Deliverer service) ──────────────────┤       │
        └── Stage 4d (ManagerSessions service) ────────────┘       ▼
                                                           Stage 6a → 6b → 6c (Split test_pm*.py, drop legacy_context, shrink compat)
                                                                   │
                                                   ┌───────────────┼───────────────┐
                                                   ▼               ▼               ▼
                                               Stage 7a        Stage 7b        Stage 7c
                                            (Caller/Policy)  (#210 Rollup)  (§5.7 Bg Work)
```

| Stage | Scope | Parallelism | Est. diff | Main risk |
| --- | --- | --- | ---: | --- |
| **1. Foundation & Fakes** | `pmlib/errors.py`; move `pm_store.py`, `pm_events.py`, `pm_sessions.py`, `pm_project.py` into `pmlib/` behind 1-line re-exports; complete `Home`/`ProjectFiles`; `Context`, `Clock`, `Output`, `Config`, `Processes`, `legacy_context()`; `scripts/tests/fakes.py`. | Sequential (first) | ~850 new/edited + 5,278 moved | Preserving `pm.STATE`/`pm.TASKS` test mutations via `legacy_context()`, and keeping `"pm_sessions.py is missing"` wording exact. (`moved.py` verifies the 4 sibling moves.) |
| **2a. Host & Git Ports** | `TerminalInfo`, `HcHost`, `TuiHost`, desktop tab methods, `GitRepo` (including the 4 raw `git` subprocess sites). | Parallel with **2b** | ~700 lines | Keeping `pm.hc` (116 patches) and `pm.herdr` (31 patches) wired through `legacy_context()`. |
| **2b. Agent Ports** | `AgentKind` (`GenericAgent`, `ClaudeAgent`, `CodexAgent`, `PiAgent`), `AgentRegistry`, `WorkerSpec`; move `outside_reads`/`read_settings`/`docs_line` to `agents/`. | Parallel with **2a** | ~650 lines | Matching exact CLI flag ordering across profiles, launchers, and Windows quoting. |
| **3a. Ledger & Project Domain** | `Task` (with `ATTACHED`), `Ledger` + `Change` (eliminating `_PENDING_NOTES`, `AFTER_SAVE`, `_CALLER_PROJECTS`), pure `plan`/`deps`/`question`/`family` (0 `sys.exit`, 0 `context.*`), `Project`/`Coordinator`/`ProjectRegistry` (eliminating `_SEAT_CHECK`), `Conversation`. | Sequential after 2a+2b | ~950 lines | Preserving exact lock/save/conversation-append ordering and `pm.save` spy compatibility until Stage 6. |
| **3b. `Caller` Inversion** | `Caller` owns single-read `terminal_info`/`labels` and instance TUI cache (eliminating `_IDENTITY`, `_SESSION`, `HERDR_PANE`); 12 legacy identity functions become thin wrappers with **zero behavior change** (`test_caller_table.py` unchanged). | Parallel with **3c** (after 3a) | ~450 lines | TUI multi-session socket caching and `hc get` call counts pinned in `test_caller_table.py`. |
| **3c. `MemoryLayer` & Leaf Services** | `MemoryLayer(ctx, repo)` with explicit `writer` (eliminating `_CANDIDATE_PRUNER`), `MemoryCandidates`, `LibraryService`, `HomeMover`, `DiscordMirror` (0 `sys.exit`, 0 `print` in all four). | Parallel with **3b** (after 3a) | ~650 lines | Preserving exact `MEMORY.md` cap accounting, `.history` filenames, and `home --json` output. |
| **4a. `Workers` Service** | `Workers(ctx)` (`dispatch`, `send`, `wait`, `escalate`, `reattach`, `adopt`, `retire`, `close_worker`, `close_reported`, `idle_workers`); removes 35 `sys.exit`, 27 `print`, `ENDING`, `_POOL_LOCK`, and `cmd_new` `Namespace` calls. | Parallel with **4c, 4d** | ~1,200 lines | Timing-sensitive paths (`send_when_ready`, `wait` exit codes 2/3/4, `retire_workspace` edge cases). |
| **4b. `Helpers` Service** | Update `ARROWS["helpers"] = {"workers", "events"}`; move `helper_brief` & `start` orchestration from `commands/helpers.py` into `Helpers(ctx)` in `helpers/service.py`; remove 10 `sys.exit` and 10 `print`. | After **4a** (parallel with 4c/4d) | ~700 lines | Keeping per-project `helper-start-<slug>.lock` scope narrow (never held across `send_when_ready`). |
| **4c. `Deliverer` Service** | `Deliverer(ctx, repo)` with constructor-injected `watchers` and `holds` (eliminating `_WATCHERS`, `_HOLDS`); `PmError` replaces `except SystemExit`; remove `sys.exit`/`print` from `events/`. | Parallel with **4a, 4b, 4d** | ~550 lines | Cross-version deliverer handover (`script_mark` / `code_mark`) and outbound-cursor vs `received` ack ranges. |
| **4d. `ManagerSessions` Service** | `ManagerSessions(ctx)` (`claim`, `start`, `archive`, `restore`, `rotate`, `seat`, `handover`); replaces `cmd_start → cmd_claim` and `cmd_restore → cmd_start` `Namespace`/`SystemExit` calls; removes `sys.exit`/`print` in `manager/`. | Parallel with **4a, 4b, 4c** | ~800 lines | Seat TTY handoff, `os.execvp` in-pane seat start, and `restore` rollback on start failure. |
| **5. `Ledger.transition`, `reactions`, `Reviews`, `Landing`** | Commit 1: `test_transition_reactions.py` (14 branches). Commit 2: `Reviews(ctx)` & `Landing(ctx)` (eliminating last 6 `Namespace` calls & all `redirect_stdout` captures). Commit 3: `Ledger.transition` + `pmlib/reactions.py` rows 1–9; thin `commands/*`, `views/*`, `hooks.py` over `ctx.out`. | Sequential after 4a–4d | ~900 lines | Exact ordering of `<id>: <status>` line, `will_auto_review` early return, and `5b/6/7` mutual exclusion. |
| **6. Test Split & Shim Cleanup (6a, 6b, 6c)** | Freeze `pmlib/` logic; split `test_pm.py` (39 classes) + 7 `test_pm_*.py` into 16 `scripts/tests/test_*.py` files on `make_ctx` + `fakes.py` in three waves (6a, 6b, 6c); update `verify`; delete `legacy_context()` & `context.*` globals; shrink `compat.py` to static facade. | 6a → 6b → 6c (within each wave, target test files can split in parallel before deleting from `test_pm.py`) | ~15,900 test lines moved/rewritten | Silently dropping a test or weakening an assertion: enforce `total_tests_after >= total_tests_before` on every wave. |
| **7. Three Behavioral Fixes (7a, 7b, 7c)** | **7a**: `Caller.role_in` & `events/policy` unification. **7b**: `#210` parent roll-up (`own_session_live` + reaction row 10). **7c**: §5.7 background work in `deliverer` & `wait`/`stalls` + delay notice. | **7a, 7b, 7c run in parallel** (after user decisions) | ~150–200 lines each | Changing live coordination behavior: each has its own branch, table/regression tests, and independent review. |

### 6.2 How reshaping stages are verified without `moved.py`

In pass one, `moved.py` compared ASTs before and after each carve because function bodies did not change. In pass two, function bodies are intentionally rewritten into methods over `Context`, ports, and exceptions (except Stage 1's move of the 4 `pm_*.py` siblings, where `moved.py` still applies). Six mechanisms replace `moved.py` as the objective gate on every Stage 1–6 merge:

1. **Two-phase separation of code changes and test rewrites**:
   - In **Stages 1–5**, production code reshapes while all **526 tests in `test_pm*.py`** and **41 tests in `test_install.py`** remain **unmodified** (save any explicit exception documented in the stage report).
   - In **Stage 6**, production logic in `pmlib/` stays **frozen** while tests migrate onto `Context` + `fakes.py`, with automated test-count verification (`>= 669` tests).
2. **AST Ratchet Tables in `scripts/tests/test_layers.py`** (the structural counterpart to `moved.py`):
   Add four allowlists to `test_layers.py` listing the exact modules that still have (a) `context.<GLOBAL>` references, (b) `sys.exit` in Layers 0–3, (c) `print` in Layers 0–3, (d) `argparse.Namespace` outside `cli`/tests, and (e) direct `hc(`/`herdr(` outside `terminals/`. Each stage deletes its modules from those allowlists; any regression in an already-cleaned module fails `test_layers.py` immediately. By Stage 6c all five allowlists are empty (`set()`).
3. **Differential Replay (`scripts/tests/replay.py`) + Reaction Trace (`test_transition_reactions.py`)**:
   Because Stages 1–6 make **zero** behavioral changes, `replay.py --old <main-at-7c10c07> --new mods/pm-dash/skill/scripts` must report `0 differences` across exit codes, stdout, stderr, `fake_hc` call logs, and normalized ledger file trees on every single stage through Stage 6c.
4. **CLI Surface Golden Test & Mod Error-Substring Test**:
   `scripts/tests/test_cli_surface.py` (`golden/cli_surface.json` untouched), byte-for-byte `--help` comparison across all 59 top-level + 22 nested subcommands, and a contract test asserting all 15 stderr substrings matched by `pm-project` ([`pm-py-refactor.md`](./pm-py-refactor.md) section 3.4) still come out verbatim when raised as `PmError`.
5. **Cross-Version Deliverer Handover & Scratch Install Check**:
   On Stage 1, Stage 4c, and Stage 6c: install into a temporary `--claude-home` (`setup.py --agents claude`), verify `state`, `hook-pre-tool`, and `hook-turn` under a temporary `PM_HOME`, and verify a running deliverer hands over cleanly when `code_mark()` changes.
6. **Cached-Bytecode Startup Timing**:
   Measured with `timing.py` (warm `.pyc` cache) on `hook-pre-tool`, `hook-turn`, and `state`: median latency must not regress by more than 5 ms against `main` (~80 ms on macOS Python 3.14; class definitions in eager imports are cheap, module-level IO is forbidden).

After Stage 6c (and after Stage 7), run the closing suite once on `main`: `python3 tests/render_check.py` (with screen awake) and a Windows smoke run of `state` and hooks if a Windows host is available.

---

## 7. What pass two does not touch

- **On-disk ledger format and paths**: Every directory, filename, JSON field, `log[]` entry text format (`status=..., commit=...; <note>`), `conversation.jsonl` event schema, `MEMORY.md` and `memory/*.md` frontmatter format, per-task lock file under `locks/`, and PID-suffixed atomic temp file under `~/.dudu` / `~/.claude/pm` stays untouched. `Project` and `Coordinator` remain stored together in `pms/<slug>.json`. No SQLite, no background daemon, no ledger migration.
- **Command-line contract**: `scripts/pm.py` entry point, `--home <dir>` and `PM_HOME`, all 59 top-level commands, 17 `project` subcommands, and 5 `helper` subcommands, every flag, choice, default, subcommand `--help` order, exit code, JSON stdout schema (`state`, `project *`, `show --json`, `idle-workers --json`, `home --json`, `backfill-numbers --json`, `helper * --json`), `[from pm.py deliver]` header, and the 15 stderr substrings matched by `pm-project` (including `"pm_sessions.py is missing"`).
- **Hook commands and sibling assets**: Hook command strings written by `setup.py` (`skills/pm/scripts/pm.py hook-...`), `scripts/pm_pi_compact.js`, and `assets/dash.html`.
- **JavaScript mods and Herdr app files**: Nothing under `mods/pm-dash/*.js`, `mods/pm-project/`, `mods/pm-list/`, `mods/pm-nav/`, `mods/pm-toast/`, or `~/.config/herdr-app` is edited.
- **Installed skill copies and live ledgers**: Pass two edits only the repository worktree and tests in `tempfile` directories; it never reads or writes `~/.dudu` or `~/.claude/pm`, and does not deploy to `~/.claude/skills/pm/`, `~/.codex/skills/pm/`, `~/.pi/agent/skills/pm/`, or other machines until the user or manager explicitly installs a merged milestone.
- **Deferred features**: Background memory consolidation (`autoDream`, [`pm-py-refactor.md`](./pm-py-refactor.md) section 6) is not implemented here — Stages 3c, 4b, and 5 build the `MemoryLayer`, `Helpers(ctx).start(...)`, and `reactions.py` seams it will use. No new capabilities are added to Herdr TUI.

---

## 8. Open questions for the user

| # | Question | Options | Where it blocks |
| :---: | --- | --- | --- |
| **1** | **Parent task automatic roll-up (`#210`, Section 5.1)**: Once `own_session_live` on `parent["pane"]` is checked and all child tasks are closed (at least one not `abandoned`) on a parent with no work of its own, what should happen? | **(Recommended) Auto-close as `done` and wake the manager** (`status=done; all N child tasks finished (...)`, `source="rollup"`), notifying without closing only when all children were `abandoned`, parent is `blocked`/`review`, or parent has own work.<br>*Alternative*: **Notify only** in all cases, leaving closing the parent to the manager. | Only **Stage 7b** (Stages 1–6 do not wait on it) |
| **2** | **Background commands vs turn state (Section 5.2)**: Should we fix both manager delivery stalling on `"1 shell still running"` and `pm.py wait` / unhooked stall detection misreporting workers with live background commands, plus add a 15-minute delivery-delay notice in `conversation.jsonl`? | **(Recommended) Yes, implement both sides + 15-min conversation notice in Stage 7c**, gated on a disposable `hc send` probe first.<br>*Alternative*: Fix `wait`/stall background detection + 15-min notice only, and keep `deliver` strictly on `idle`/`done`. | Only **Stage 7c** |
| **3** | **Caller identity & news-policy unification (Section 5.3)**: Confirm the unified answers for the three contradictions (`moved_hc`/`moved_tui` no longer treated as old project's manager; helpers emit `source: "helper"` and `by: "helper:<name>"`; worker/reviewer non-moving reports wake on `review`, `blocked`, and `done`, not `proposed`)? | **(Recommended) Confirm all three rules as specified in Section 5.3.**<br>*Alternative*: Keep `done` non-waking on follow-up notes (only `review` and `blocked` wake when status does not change). | Only **Stage 7a** |

---

## Not verified

- **Live `hc send` behavior when `hc get` reports `{"state": "working", "msg": "1 shell still running"}`**: No live `hc` commands were run for this read-only plan. Specifically, it has not been verified whether `hc send <term> <text>` (without `--if idle`) returns `{"ok": true, "started": true}` when `status.state` is already `"working"`, nor whether `hc` still holds the send back when the user has an unsent draft in that state. Stage 7c must verify both in a disposable `hc` terminal before changing `deliver_look`.
- **Exact `ps` command-line shape of background child commands under non-Claude agents (`codex`, `agy`, `pi`)**: `manager/rotate.py:background_work` currently matches Claude Code's `shell-snapshots/snapshot-` wrapper (`line 346`). Extending it in Stage 7c to detect live background child commands of `codex` / `agy` workers in `wait` and `stalls` requires checking child process trees of those agents in a scratch terminal (and on Windows, where `ps` is absent).
- **Delegated `land` immediate `reconcile_dependents_of` interaction**: Sharing `reactions.after` on the delegated worker/helper `land` path adds immediate dependent reconciliation (today `_land_done_delegated` omits it and relies on the deliverer's watcher). While all 15 tests in `test_pm_delegate.py` pass today, Stage 5 will confirm no test asserts the absence of that immediate `deps` event.
- **Warm-cache import overhead of class definitions on older Pythons and Windows**: Startup timing (`~80 ms` cached for 89 modules) was previously measured on macOS Python 3.14; pass two keeps module count nearly flat (~90 modules, absorbing the 4 `pm_*.py` siblings and adding `errors.py` and `reactions.py`), but Windows and Python 3.9–3.12 import times were not measured here.
