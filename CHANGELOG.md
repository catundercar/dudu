# Changelog

All notable changes to dudu. Dates are UTC.

## Unreleased

- In the desktop app each project now has one deliverer that runs for as long as its manager does, instead of one per report that gave up after ten minutes. It decides by itself which ledger entries are news, so a report written by an older `pm.py` (on a worker that has not been updated) reaches the manager too, and it watches the project's workers through herdr-core: a worker without hooks (pi, agy) that stops without reporting, and any worker whose terminal exits or that waits at a prompt, is reported within seconds. A report that comes during a rotation goes to the new manager once its takeover turn is over; the deliverer ends by itself once the manager's terminal is gone, and restarts on its own after an install. `pm.py wait` refuses in a desktop-app manager's own terminal, where it would bring each report twice.
- Task brief templates and the skill rules no longer ask workers for the smallest change: scope stays tight (no unrequested scripts, tools or abstraction layers), while the approach starts from first principles; the templates also add an optional section for design and research tasks to work from the requirements themselves before laying out the path from the current code.
- A dispatched worker's follow-up `pm.py update` with `--note` or `--commit` now wakes the manager even when the task is already in `review` or `blocked` (such as after fixing review comments without passing `--status` again).
- In the desktop app a worker's report, a `pm.py notify` and the new `pm.py event` reach the manager as one delivered message once it is idle, instead of a `wait` per task; a worker that stops without reporting is reminded once, then the manager is told. In the herdr terminal UI the inbox, `wait` and `watch` stay as they were. Memory in two layers, yours and the project's (`pm.py remember`, `recall`, `forget`, `adopt`, `memory`): the handover and every brief carry its index, `decide` also writes one unless `--once`, and Claude Code's own memory is pointed at it. Words that reach a manager while its turn runs are now kept in the conversation. Restart running manager sessions after installing, or they keep starting `wait` and get each report twice.
- The PM list in the sidebar lists PMs only, no longer their workers: Herdr's Agents list already shows each worker under its PM, so they showed twice. A PM whose terminal reports no status is marked unknown (?), not idle, and a terminal labelled as a PM that this ledger does not know gets a row too.
- PM `watch` / `wait` now wake on file notifications (macOS kqueue, Linux inotify, Windows directory notifications) and desktop `hc events`, ignoring title animations and heartbeats. Fact streams reconnect, unread inbox offsets survive restarts, and a 60-second reconciliation covers missed events. The legacy TUI retains its state-check fallback.
- `pm.py watch` refuses to start with its output going nowhere (`&`, `nohup`, `/dev/null`), stops within 5 s once what started it is gone, without reading the inbox, and says what holds the lock when a second watcher is refused. A first watch delivers at most the newest 20 unread inbox lines. Worker states wake a watch only in the herdr terminal UI; in the desktop app it is the inbox alone, as before (`wait` sees a worker stop there).
- `pm.py notify` from a repository nested in the project's folder reaches the PM of its task or of the nearest folder above; `--repo` names a project and never falls back to another PM; when it finds no PM it exits 1 instead of reporting success.
- Installing over a build that had `pm-agents` points the pm layout's agents block back to Herdr's agents mod and removes `mods/pm-agents`; uninstalling does too.
- Windows Desktop: sending a reply no longer shells out through Unix `env -u`; it runs `hc send` / `hc put` directly so the message box works without a usable `env`.
- Workers can run on a pool of codex profiles with a limit each (`codex.profiles`); when all are full, a Claude worker starts instead and the task says why. Claude Code and Codex workers can be started through a launcher of your own (`claude.launcher`, `codex.launcher`).
- A finished task's worker terminal can be closed with it (`workers.close_on_close`); `pm.py idle-workers` lists and closes idle ones, and `pm.py status` lists reported work whose terminal is still open. `workers.close_reported` closes a worker's terminal once it has reported and sat idle.
- `"deep": {"confirmed": true}` in `config.json` records that you agreed to Fable workers for good, so the manager stops asking each time; off by default.
- `dispatch --task` takes up a registered task, `--here` works without a worktree, `--dry-run` shows the plan; `tabs.new_tab` gives each worker a tab of its own, and `pm.py retab` renames it.
- The skill's main file is less than half its size: the details moved to files the manager reads when they apply.
- Installing over a skill copy that was edited by hand backs the edits up first and says so.
- The README is short and points to [the guide](docs/guide.md) for the details.
- A home page on GitHub Pages: https://catundercar.github.io/dudu/
- A project on a remote machine opens in the project view, like a local one, instead of in its manager's terminal.
- In a remote project's conversation you can paste, drop or pick files: they are copied to that machine when the message is sent, and a file that could not be copied says so under the message.
- A remote project's attachments: a file with a Chinese (or other non-ASCII) name arrives under a readable name such as `image-20261116-221514-1-v2.png` instead of `____v2.png`; a pasted screenshot is no longer kept here once its message went, and leftovers older than a week are cleared; sending again after a file failed does not copy the files that already went a second time.
- Manager sessions start lighter: a Claude Code manager starts without MCP servers, browser tools or other plugins (`"pm": {"lean": false}` turns this off).
- The manager reads less: short task and status output, the full report only when a task comes back, and small diffs land without a separate reviewer.
- Handing a long conversation to a fresh manager session happens in the same tab, without a word to you; the old session stays until the new one is working.

## v0.1.0 (2026-11-15)

First tagged release. [Release notes](https://github.com/catundercar/dudu/releases/tag/v0.1.0)

- **Projects** in the sidebar: create, archive and restore projects; each opens as a conversation with its manager or as its own board.
- Question cards can be answered in your own words; waiting items without a card can be answered from the thread.
- Review threads fold into the task they review; threads can be reattached, resized and show each worker's profile.
- Worker profiles (light, standard, hard, deep) map to a model and effort; a failed review escalates one step.
- Merges happen only after the project's checks pass; reviews run read-only on a different model.
- Dispatch waits for a ready worker and gets past its first-run prompts by itself.
- Esc steps back one level everywhere; the title bar drags the window; message boxes take files and keep drafts.
