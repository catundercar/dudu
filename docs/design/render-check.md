# Render Check: Rendering Every UI Mod Inside an Isolated Private Herdr Before Merge

> **Background**: `herdr-app check` loads and describes each mod once without laying out the page a second time, so a mod that throws only on re-render passes `herdr-app check` cleanly. This document describes the design of `tests/render_check.py`, which launches a fully isolated private Herdr instance, renders every UI mod across multiple real frames, and judges pass/fail from runtime errors thrown by the mods. Written in November 2026; **implemented** and wired into pre-merge verification (gating merges whenever UI mods are touched).

## How to Run

```sh
python3 tests/render_check.py                 # mods/ and layouts/ from the working tree
python3 tests/render_check.py --rev <commit>  # mods/ and layouts/ from a commit (via git archive, no worktree)
```

Optional flags:

| Flag | Purpose |
|---|---|
| `--pm <name>` | Which project's manager to display (default: the registered project with a conversation log and the most tasks) |
| `--thread <id>` | Which thread detail view to open (default: the project's most recently updated non-review thread) |
| `--ledger DIR` | Ledger directory to copy as fixture data (default: `$PM_HOME`, legacy `~/.claude/pm` unless symlinked to `~/.dudu`, or `~/.dudu`) |
| `--dir DIR` | Run directory (default: `evidence/render-check/run/`, gitignored). Only replaces an existing directory that carries a `.render-check` marker; keep the path short because macOS Unix domain sockets have a 104-byte path limit |
| `--keep` | Keep the private app home, copied ledger, and extracted source tree after completion |

After a normal run, the run directory retains only `app.log`, `report.txt`, and `shots/*.png` (one screenshot per page). A passing run takes roughly 30–35 seconds; a failing page waits out its per-page timeout and takes longer.

## Exit Codes

| Code | Meaning | Action |
|---|---|---|
| 0 | Every page rendered cleanly with zero mod errors (`PASS`) | — |
| 1 | A mod threw an error, a page rendered fewer times than required, a page never reached its expected state, or a mod never rendered at all (`FAILED`) | Fix the code |
| 2 | Not judged (`NOT RUN`): isolation preconditions failed (`BLOCKED`), or the private window stopped producing frames / `herdr-app shot`, `herdr-app do`, or `hc` timed out | Not a mod bug; retry |

Timeouts from the private Herdr instance or its private `herdr-core` are always classified as `BLOCKED` with exit code 2 rather than misattributed as mod failures.

## When It Must Run

Render check lives in the pre-merge verification script, but **only gates merges that touch UI mods**: it runs when staged/merged paths include `mods/<mod>/` (excluding `mods/pm-dash/skill/`) or `tests/render_check*` itself; merges touching only the skill, docs, or Python tests skip it and print `render-check skipped: no UI files in this merge`. Conceptually:

```sh
if git diff --cached --name-only HEAD | grep -E '^(mods/[^/]+/|tests/render_check)' | grep -qv '^mods/pm-dash/skill/'; then
  python3 tests/render_check.py || { [ $? -eq 2 ] && echo "render-check did not judge; retry once"; exit 1; }
fi
```

Exit code 2 still blocks the merge, with a message distinguishing "could not judge" from a broken mod. Because frames are now drawn on demand (see §4 below), screen lock, display sleep, and occluded windows no longer cause exit code 2 — only genuine infrastructure failures (such as the private Herdr failing to launch or refusing `shot`) do.

## Design

### 1. Isolation: Never Touch the User's Own Herdr

- **Private app home**: creates a fresh `HERDR_APP_HOME` inside the run directory populated with copies of the repository's `layouts/pm.json` and `mods/`, plus generated config files:
  - `settings.json`: sound off, telemetry off;
  - `update-notes.json`: records the current version as already seen so Herdr does not treat launch as a post-upgrade first run and attempt to upgrade `herdr-core`;
  - `window.json`: 1000×680 anchored at the bottom-left of the main display (window dimensions govern `pm-project`'s wide vs. narrow responsive layout); the main display UUID is queried live via CoreGraphics rather than read from the user's `window.json` (Herdr centers windows if the configured display UUID is missing);
  - `shared.json`: selects the `pm` layout and initial stage page.
- **Copied ledger**: copies the ledger into the run directory and points `PM_HOME` at the copy, skipping symlinks and sockets so writes inside the test can never follow a link back to the real ledger.
- **Dedicated core session**: starts `herdr-core` under `HC_SESSION=rc<pid>` after scrubbing inherited `HC_*`, `HERDR_APP_HOME`, and `PM_HOME` variables (which otherwise point at the user's live session when invoked from inside a Herdr terminal).
- **Stand-in terminals**: spawns two `cat` processes labeled as the project's manager terminal and the target thread's worker terminal so the UI renders live "online" states.
- **Background second app instance**: launches a separate Herdr process via `open -g -n`, leaving the frontmost application and keyboard focus untouched.
- **Call guards**: every `herdr-app` invocation explicitly sets the private `HERDR_APP_HOME` and aborts if path resolution points inside the user's home config or outside the run directory; every `hc` call explicitly targets the private session. Neither `~/.config/herdr-app` nor the real ledger is ever read from or written to after fixture setup.

### 2. Catching Errors: Wrapping Every Mod's View

Herdr does not surface `"This view could not be re-rendered"` in `herdr-app status` or the log file — it only paints an error banner inside the window. Inside the private mod copies, the harness therefore:

- renames each mod's `main.js` to `main.real.js` (leaving its contents byte-for-byte intact) and writes a thin wrapper `main.js`;
- wraps `init` and `render` on every exported View class in `main.real.js` and sibling `.js` modules in `try`/`catch`, logging any thrown exception and stack trace before **re-throwing** it unchanged so Herdr's behavior is preserved;
- logs a monotonic render counter on every `render` call so pass criteria can verify real re-renders.

Uncaught exceptions inside timers or async tasks and `console.error` calls are already logged as `ERROR` by Herdr itself and count as failures. Commands rejected with `unknown command` because a mod failed to register also count as failures. Other `WARN`/`ERROR` lines are included in the report for inspection without failing the run.

### 3. Driving Pages

- `pm-list` stays mounted in the sidebar across every page and does not consume `nextCommand` itself, so its wrapper handles `rc-page:*` commands (`setShared` + `layout.select`) to switch views.
- `pm-project`'s wrapper handles `rc-thread:<id>` (invoking `openThread`) and `rc-report` (logging internal state such as project slug, event count, `detail`, `thread`, and `threadTask`).
- Every wrapper watches a `poke` folder inside the run directory and calls `cx.notify()` whenever a file is written, marking all mounted mods dirty for re-render.
- If `pm-list` or `pm-project` ever starts reading `nextCommand` directly in production code, the harness exits with code 2 instructing the author to move the test driver hook rather than competing with the mod's own command handler.

### 4. Drawing Frames on Demand (Works Under Screen Lock and Display Sleep)

On macOS, GPUI runs its display link only while a window is at least partially visible; when the screen is locked, the display is asleep, or the window is fully covered or minimized, zero display-link frames fire and `cx.notify()` merely marks the window dirty. Rather than waiting on the OS display link, the harness **drives frame rendering itself**:

- After each poke, it waits ~0.3 s for each mod's `watchFolder` callback to invoke `cx.notify()`, then runs `herdr-app shot`. On a dirty window, `shot` synchronously executes a full `window.draw(cx)` pass (every mod's `render`, layout, prepaint, and paint) into an offscreen texture without requiring window visibility.
- As soon as the private window answers its first RPC, the harness calls `NSRunningApplication.hide` on the private process (equivalent to pressing Cmd-H on it) — without activating it, stealing focus, or needing Accessibility permissions — and verifies read-only that all of its windows are offscreen. Every subsequent frame comes from `shot`.
- If `shot` fails or does not answer within 30 seconds, the step is recorded as "did not draw a frame" and treated as unjudged (exit code 2).

For the full root-cause analysis and locked-screen verification measurements, see [render-check-locked.md](../research/render-check-locked.md).

### 5. Pages and Pass Criteria

The harness steps through 7 pages in order. On each page it sends the navigation command, mutates the target thread's JSON in the copied ledger (exercising the mod's own filesystem watcher), and repeatedly pokes and draws frames until the page's target mod has rendered at least 3 additional times and (for `pm-project`) reports internal state matching that page, up to a 20-second budget per page.

| Page | Mod under test | Additional state assertions |
|---|---|---|
| Projects list | `pm-dash` | — |
| Projects board | `pm-dash` | — |
| Project conversation | `pm-project` | Expected project resolved and loaded, `events > 0` |
| Project board | `pm-dash` | — |
| Thread detail | `pm-project` | `detail` open, `thread` and `threadTask` match target ID |
| Remote project (unreachable machine) | `pm-project` | Machine points to a host unknown to the private core; page renders its "unreachable" error state cleanly without throwing |
| Toast | `pm-toast` | Triggers `notify()` so `pm-toast` renders at least once |

In addition, every installed mod must render at least once across the run, and `herdr-app status` must report zero errors.

Because `pm-project` resolves which project it is showing during `render`, before opening thread detail the harness pokes and queries in a loop (up to 10 seconds) until `pm-project` confirms it has rendered the target project.

### 6. Liveness Check: Separating "Window Stopped Drawing" from "Mod Broke"

- Right after startup, the harness pokes once and requires sidebar `pm-list` to render again; otherwise it aborts with exit code 2.
- At the end of each page, if a page failed to reach its render count, the harness pokes once more while drawing frames every 0.3 s; if `pm-list` still does not render, that page is marked unjudged and the run stops immediately rather than timing out on every remaining page.
- As long as no mod threw an error, any unjudged page yields exit code 2; if a mod already failed, exit code 1 takes precedence.

Originally built so display sleep would never misreport healthy code as `FAIL`, this liveness check now guards the `shot` assumption itself: if an upstream Herdr change ever makes `shot` return a cached texture without drawing dirty views first, the check fails safe with `NOT RUN` rather than silently reporting `PASS`.

### 7. Cleanup

Executed in a `finally` block as well as on `SIGINT` / `SIGTERM` / `SIGHUP`:

1. Sends `herdr-app do app.quit`; if the process remains alive and its environment confirms it belongs to this run, sends `SIGTERM` (re-scanning by environment if interrupted early before window discovery finished).
2. Runs `hc kill` on both stand-in terminals, runs `hc server stop`, and removes the private `herdr-core` state directory.
3. Unless `--keep` was passed, deletes the private app home, copied ledger, extracted source copy, and `poke` directory.

In controlled interrupt tests sending `SIGINT` at 1 s, 3 s, and 9 s after launch, every run exited with code 2, left only the user's own Herdr running, and left zero residual state directories (on the 1 s interrupt before `app.quit` could answer, `SIGTERM` cleaned up the process).

### 8. Focus

The harness reads the frontmost application before and after the run (read-only). If focus changed, `report.txt` logs a note stating whether the private instance ever became frontmost; when focus stayed put, it reports how quickly the private window hid after answering and how many frames were drawn on demand. If the private window ever reappeared onscreen before teardown, a note is logged as well.

## The Class of Bugs It Catches

This harness was built after a real regression: in an earlier commit, `pm-project`'s `Esc` focus handle was shadowed by a timeline key handler, throwing inside `track_focus` on the second render. `herdr-app check` passed 5/5 on that commit; `render_check.py` produced:

```
ok   projects        pm-dash rendered 8x
ok   projects-board  pm-dash rendered 5x
FAIL conversation    pm-project rendered 4x
       7 error(s) from the mods while this page was shown (listed below)
ok   project-board   pm-dash rendered 4x
FAIL thread          pm-project rendered 0x
       64 error(s) from the mods while this page was shown (listed below)
       pm-project rendered 0 time(s) after the page was shown, expected at least 3
FAIL toast           pm-toast rendered 3x
       7 error(s) from the mods while this page was shown (listed below)
FAIL 78 error(s) from the mods:
  ERROR pm-project default.render: track_focus(handle) expects a FocusHandle from cx.focus_handle(), not a name or an element
        at render (mods/pm-project/main.js:991:20)   (x78)
FAILED
```

The conversation page rendered cleanly a few times before events finished loading, then crashed as soon as events arrived; errors during the `toast` step also came from `pm-project` still mounted underneath the toast overlay. On the fix commit, all 7 pages passed with exit code 0. That historical broken commit has served as the positive control ever since.

## What Is Not Covered

- Mouse clicks and keyboard input (`Esc` navigation, sending messages, drag-and-drop) are not exercised — only states reachable via commands and file updates.
- Catches exceptions thrown from `init` / `render`, plus timer/async exceptions and `console.error` lines logged as `ERROR` by Herdr; exceptions inside click handlers will not fire unless invoked.
- Connected remote machines: the isolated core has no remote peers, so only the "unreachable remote machine" state is exercised.
- `pm-toast` is tested with an ordinary notification, not the branch that suppresses worker sub-agent notifications.
- macOS only (launches the `.app` bundle); non-macOS platforms exit immediately with code 2.
- Does not verify final Metal presentation or WindowServer compositing to physical pixels, which sit outside mod code.
- Wrapper assertions inspect `pm-project` internal properties (`pmName`, `events`, `detail`, `thread`, `threadTask`, `openThread`). Renaming those properties in `pm-project` surfaces `null` in the state report and fails the corresponding page until `render_check.py` is updated in lockstep.
