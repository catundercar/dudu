# Keeping Automated UI Render Checks Running Under Screen Lock and Display Sleep: Design and Verification

> **Background**: Render check (`tests/render_check.py`; design in [render-check.md](../design/render-check.md)) originally relied on macOS scheduling display-link frames for a private Herdr window. As soon as the screen locked or the display went to sleep, macOS stopped delivering frames, forcing the check to report "not judged" (exit code 2) and blocking every unattended merge. This report analyzes the root cause, compares candidate approaches, and documents verification of the adopted design (synchronous frame rendering via `herdr-app shot` + hiding the private app). Written in November 2026 on macOS 27.2 with Herdr 0.1.16; **implemented** and merged into `tests/render_check.py`.

## Conclusion

**Drive frames on demand from the harness instead of waiting on the macOS display link.** After every poke, the check invokes `herdr-app shot` against the private Herdr instance. Whenever the window is dirty, `shot` synchronously executes `window.draw(cx)` — running every mod's `render`, layout, prepaint, and paint — and renders the scene into an offscreen texture without requiring the window to be visible. As soon as the private Herdr window answers its first RPC, the harness hides the private app with `NSRunningApplication.hide` (the programmatic equivalent of Cmd-H), without activating it, stealing focus, or needing Accessibility permissions. From then on the window stays offscreen and every frame comes from `shot`.

**Verified live under a locked screen.** Across windows of time where the screen remained continuously locked and the display remained asleep from before start until after teardown:

- Current `main` code: **PASS**, every one of the 7 pages rendered 3+ times, 25 frames drawn on demand;
- Positive control (a historical commit known to throw on its second render): **FAIL**, catching the exact expected error (`pm-project default.render: track_focus(handle) expects a FocusHandle …`);
- Screenshots captured while locked contain real rendered UI populated with live copied-ledger data.

Multiple additional locked-screen runs confirmed stability: with `hide` enabled, the check passed, hiding the private window ~0.4 s after first response with zero onscreen samples at 0.5 s polling intervals thereafter; three instances run **concurrently** while locked (two on current code, one on the positive control, each in its own run directory) finished in 32–87 s with two `PASS` and one `FAIL` reporting `track_focus`. CLI flags and exit codes are unchanged, requiring no caller updates.

**Verified while unlocked with a user at the keyboard: zero focus theft.** An unlocked run passed in 32 s (33 frames drawn on demand); the private window opened at the bottom-left of the main display, stayed visible for at most ~0.6 s before hiding, and never took focus — the user's own Herdr remained frontmost throughout, and macOS system logs confirm WindowServer rejected the private instance's activation requests (see "Verification While Unlocked" below).

Practical impact:

- Screen lock, display sleep, and covered windows no longer produce unjudged runs; the merge gate rule ("unjudged also blocks merge") stays intact while exit code 2 shrinks to genuine infrastructure failures (e.g., private Herdr fails to launch or stops answering `shot`).
- An earlier exception allowing render check to raise its small window to the front (without stealing keyboard focus) can be retired: the window hides immediately on startup and needs neither window-raising nor Accessibility permissions.
- Requires zero extra packages, virtual display drivers, or macOS system setting changes.

## Root Cause: Why Nothing Draws When the Screen Is Locked

Herdr's source is open (`github.com/herdrdev/herdr-app`); the findings below come from reading its GPUI integration and testing against live instances:

- On macOS, GPUI frames are driven by a `CVDisplayLink`. In `vendor/gpui-pre-macos/src/window.rs`, `start_display_link` checks whether `occlusionState()` contains `Visible` and refuses to start otherwise; `window_did_change_occlusion_state` stops the display link whenever a window becomes non-visible. Screen lock, display sleep, full window occlusion, minimization, and residing on an inactive Space all clear `Visible`, dropping frame delivery to zero. `cx.notify()` only marks the window dirty — without a frame tick, `render` never runs. That was the exact source of exit code 2.
- Lock-screen occlusion is **session-wide**, not geometric occlusion by the lock shield: placing a window on a second (virtual) display not covered by the lock screen shield still produced 0 frames.
- `herdr-app shot` calls `Window::render_current_to_image` (`vendor/gpui-pre/src/window.rs`). When the window is dirty, it synchronously calls `window.draw(cx)` (up to two passes, draining `next_frame` callbacks) and renders the scene into an offscreen Metal texture via `render_to_image`. Source comments note it is `"useful for visual testing … without displaying it or requiring the window to be visible"`, and `herdr-app --skill` documents that `shot` works `"even when the window is covered or minimized"`.
- `shot` requires the window to have completed at least one initial draw, and GPUI's `open_window` always performs one synchronous draw at creation time (`vendor/gpui-pre/src/app.rs`). Consequently, `shot` works immediately on any newly opened window — even one opened while the screen is already locked.

## How Alternative Approaches Fare Under Screen Lock

| Approach | Works while locked? | Evidence |
|---|---|---|
| **On-demand frame drawing (`shot`-driven, adopted)** | **Yes** | Measured: current code `PASS`, positive control `FAIL`, real rendered screenshots |
| Original design: small bottom-left window + `AXRaise`, waiting on display link | No | Measured `NOT RUN`, exit code 2. Its occlusion diagnostic also misreported "covered by Herdr" while locked because `CGWindowList` ordering is unreliable under lock |
| Plain `poke` waiting on OS frame scheduling | No | Measured 0 frames across 3 pokes; on the exact same locked window, each `shot` call drew 1 frame |
| Moving the window onto a virtual display | No | Measured: even when `onscreen=true` on a secondary display outside the lock shield, `poke` produced 0 frames — and creating virtual displays mutates system display state |
| Resizing or raising via Accessibility (`AX`) to force a redraw | No | Measured: while locked, `AX` exposes only `AXApplication` with zero windows (`AXSize` returns `-25205`, `AXRaise` returns `-25206`); the old `AXRaise` helper logged `"raised 0"` |
| Running only `herdr-app check` | Runs while locked, misses the bug class | Measured 5/5 `PASS` on current code **and** 5/5 `PASS` on the broken positive control. Source comments (`vendor/gpui-kit/crates/shell/src/plugin.rs`) note it renders once without full layout, nested views, or async state updates |
| Splitting error checking (pure JS mock host) from visual rendering | Not recommended | On-demand `shot` already runs a real full frame and produces screenshots in one pass. Pure JS mocks miss native Rust builder validations (`track_focus` was thrown by a native builder), and mocking ~22k lines of `gpui-kit` typings would inevitably drift from the real runtime |
| Running on another Mac | Only moves the problem | Fails the moment that machine locks its screen |
| Headless Linux (`Xvfb` or headless Weston) | Independent of Mac lock (**not tested end-to-end**) | Upstream's `scripts/sandbox` uses headless Weston + Xwayland (`"frames never stall"`), but requires maintaining a container with Mesa software GL, `xkbcommon`, fonts, a Linux Herdr build matched to the Mac version, and fixture ledgers — unnecessary overhead now, viable later for CI |
| macOS VM (Tart, etc.) | Works in principle (**not tested**) | Guest OS has its own `WindowServer` unaffected by host lock, common in macOS UI CI, at the cost of tens-of-GB VM images, version sync, and ledger copying |
| Asking upstream for a headless or draw-while-hidden flag | Unnecessary | `shot` is already a documented upstream capability (and GPUI has `HeadlessAppContext`). Optionally ask upstream to codify "dirty windows draw before capture in `shot`" as an explicit contract |

## Implementation Highlights

- `Check.poke()`: writes the poke file, sleeps 0.3 s so each mod's `watchFolder` fires `cx.notify()`, then calls `frame()`.
- `Check.frame()`: runs `herdr-app shot` once to advance a frame, recording any failure reason so unjudged reports explain exactly why.
- Page sequencing and render-count assertions stay unchanged, except every poke now deterministically advances a frame. `still_drawing()`, which previously poked once and waited passively, now draws a frame every 0.3 s during its wait loop so a slightly delayed watcher notification is never misread as a stalled window.
- Launch still uses `open -g` at `1000×680` (which sets `pm-project`'s responsive breakpoint). As soon as the window answers, `hide()` calls `NSRunningApplication.hide` and verifies read-only that its windows are offscreen.
- `open -j` (launch hidden) **does not work**: Herdr calls `cx.activate(true)` after opening its window (`src/main.rs`), putting the window onscreen and centered anyway. `herdr-app do app.hide` over the control socket is a no-op.
- Removed `AXRaise` and `CGWindowList` occlusion diagnostics completely.
- Every `shot` call — including end-of-page screenshots — goes through the same helper: failure or a 30 s timeout marks the step "did not draw a frame" (`NOT RUN`, exit code 2) rather than a mod error. Timeouts in `herdr-app` or `hc` likewise report `BLOCKED` (exit code 2) instead of raising uncaught exceptions (exit code 1).
- The report summary replaces `"private window raised N"` with `"private window hidden X s after it answered, N frames drawn on demand"`, appending a note if the window ever came back onscreen before exit.

### Issues Caught and Fixed During Review

1. **Polling project readiness without drawing frames.** `pm-project` learns which project it displays only during `render`. An earlier wait loop queried `rc-report` without drawing frames; if that project had not yet rendered, the loop timed out after 10 s with a false `FAIL` (exit code 1) despite zero mod errors. Poking (and thus drawing a frame) before each poll fixed it — verified by moving the thread-detail page to position 1, where the old loop failed with `"pm-project did not show … within 10 s"` and the new loop passed.
2. **Fault injection.** Injecting timeouts from page 2 onward verified clean classification: `shot` timing out on every frame → `NOT JUDGED` (exit code 2); only the end-of-page screenshot timing out → `NOT JUDGED` (exit code 2); `herdr-app do` timing out → `BLOCKED` (exit code 2, with `SIGTERM` cleaning up the private process once `app.quit` also timed out).
3. **Window placement.** Early locked-screen runs placed the window in the center of the screen instead of the bottom-left corner because `~/.config/herdr-app/window.json` does not always carry a `display` UUID (Herdr rewrites that file), and Herdr centers any window whose `display` is omitted or unrecognized while clamping offscreen coordinates. Unlocked users would see a centered flash; under the old design the centered window stayed up for the entire run. Computing the main display UUID directly via CoreGraphics for the private `window.json` (never reading the user's `window.json`) and tightening startup polling from 0.5 s to 0.2 s pinned the brief pre-hide window to the bottom-left corner. While locked, the main display is inactive so Herdr may still center it, when nobody can see the screen anyway.
4. **Other scripts reusing `Check`.** Because `Check` now hides the app and drives frames via `shot`, external scripts importing `Check` for live screen recordings must raise the window themselves and write poke files directly during recording without calling on-demand `shot`; the display-geometry helper also returns an extra display UUID element now, so callers unpacking coordinates should slice the first two values.

## Verification While Unlocked

**Result: `PASS`, window visible at the bottom-left for at most ~0.6 s, zero focus theft.**

A watcher waited until the screen was unlocked and awake, ran `render_check.py` once while sampling window bounds and frontmost app, and confirmed the display remained unlocked and lit throughout:

- **Check outcome**: `PASS`, 3–6 renders per page across all 7 pages, 33 frames drawn on demand; report logged `"private window hidden 0.4 s after it answered"`.
- **Window placement**: private main window `bounds=0,400,1000x680` on a `1920×1080` main display (CoreGraphics origin at top-left, `400 + 680 = 1080`, flush bottom-left).
- **Visibility duration**: the external sampler (~0.7 s per pass) saw `onscreen=false` on its very first observation and across 100+ subsequent samples. Because 0.7 s is coarser than the exposure window, exact timing comes from read-only macOS unified logs (`log show`) filtered to the private PID:

| Relative time | Log entry | Meaning |
|---|---|---|
| `0 s` | `BringForward … dontMakeFrontmost=1` | `open -g` honored: launched without bringing to front |
| `+0.16 s` | WindowServer `SetFrontProcessWithInfo … presents 0 windows … Denying the request` | Initial frontmost request denied before any window existed |
| `+0.64 s` | WindowServer `Rejecting the request … due to the activation count being 0 … window count = 1` | After window creation, Herdr's own `activate` call was also rejected |
| `+0.74 s` | `DoHide(self)` / `PostHideProcess` | `NSRunningApplication.hide` took effect |
| At exit | `QUITTING: … wasFront=0` | OS record confirming the process was never frontmost |

The private Herdr never once became the active application, so user keystrokes cannot land in it — enforced by macOS 14+'s cooperative activation policy: because the process was launched with `open -g` and had user activation count 0, its unilateral `activateIgnoringOtherApps` call was denied by WindowServer.

- **Cleanup**: run directory deleted, private processes exited, only the user's Herdr remained.

## Trade-offs and Risks

- **Relies on `shot` drawing dirty windows before capture** (Herdr 0.1.16 / `gpui-pre`). If upstream ever changes `shot` to capture only the last presented texture, the liveness check fails safe with `NOT RUN` (`"herdr-app shot answered, but no mod rendered"`) rather than a false `PASS`.
- **Skips Metal swapchain presentation and WindowServer compositing**, which are host responsibilities rather than mod logic (and which the old design could not reach while locked anyway).
- **Deterministic frame cadence**: disabling reliance on the display link puts render counts under harness control, which should eliminate sporadic `"the window stopped drawing"` retries, subject to longer-term observation.
- **Less intrusive**: at most a ~0.6 s bottom-left glimpse instead of 25–30 s onscreen, zero Accessibility permissions, and zero reads from `~/.config/herdr-app`.
- **Focus behavior depends on macOS cooperative activation**: verified on macOS 27.2; re-verify across major macOS upgrades or if launch flags (`open -g`) change.
- **Wall-clock overhead**: encoding a `2000×1360` PNG on every frame adds ~0.1–0.3 s per frame (~35 s total vs. ~24 s unlocked previously).
- **App Nap**: macOS may throttle hidden apps, though locked-screen runs completed at normal speed without timeouts.
- **Out-of-scope environment**: if no GUI login session exists at all (user fully logged out), `open` cannot launch an app and exits `BLOCKED`. Managers and workers run inside the user's graphical session in normal operation.

## Not Yet Verified

- Only one live unlocked run was measured; exact Z-order during that ≤0.6 s window (whether the bottom-left `1000×680` rect appeared above or behind existing windows before hiding) was not instrumented.
- Neither headless Linux nor macOS VMs were tested end-to-end.
- Other scripts importing `Check` were not individually re-executed; live screen-recording mode was checked only in probe mode rather than a full recording session.
- Long-horizon stability across repeated lock/unlock cycles and multi-hour system sleep has not yet been accumulated.
