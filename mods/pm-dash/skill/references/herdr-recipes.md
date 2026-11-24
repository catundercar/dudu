# herdr-core recipes and pitfalls

Terminals in the Herdr desktop app run in herdr-core; its CLI is `hc`. For the full CLI, run `hc --help` or `hc --skill` once. Below are only the patterns that proved reliable in practice. `<t>` is a terminal address such as `t7`, or `<machine>/t7` on another machine.

## Terminals

- **State of one terminal:** `hc get <t> --json`. An agent's state is under `status` (`app`, `state`); values seen are `idle`, `working`, `done`, and no status at all while a program is still starting or sits at a startup dialog.
- **Read the screen:** `hc read <t> | tail -40`.
- **Start a program in a terminal of its own:** `hc run --bg --name <name> --cwd <dir> -- <program> <args>`. It becomes a sub-agent of the terminal that started it: the app lists it under that agent, without a pane (`herdr-app do terminal.peek '{"terminal":"<t>"}'` shows it, `terminal.keep` gives it a tab). A sub-agent ends with its parent unless started with `--outlive-parent`; `pm.py dispatch` uses that, so a worker survives its PM's rotation. `--no-parent` starts a terminal that the app does not show at all. `--no-notify` stops hc from typing notes about the child into its parent.
- **`--json` goes before `--`.** Anything after `--` is passed to the started program.
- **Labels:** `hc label <t> pm=<project>` marks a PM, `task=<id>` a worker, and `helper.of=<task id or pm-project>` + `helper=<name>` + `helper.project=<slug>` a temporary helper (`pm.py helper start` sets them on `hc run` without `--outlive-parent`, so the helper ends when its caller ends). The board uses them to find the terminal to jump to.
- **End and remove:** `hc kill <t>`, then `hc rm <t>`. `pm.py retire` does both for a worker.

## Agents

- **Send a message (PM):** never run foreground blocking `hc send <t>` from the PM turn (it blocks while the worker is working or has a draft). Use `pm.py update <id> --note "..." --send` (async by default from PM) or `pm.py send <task_id|t> "<msg>"` (always async unless `--wait`). Raw `hc send <t> "..."` is for helpers or manual recovery. Long multi-line text works; `"started": true` means the agent took it as a turn.
- **A just-started agent is not ready.** Wait until its state is `idle` before sending: an agent with no status yet may be at a startup dialog, which takes pasted text and Enter as its answer. `pm.py dispatch` waits up to about a minute (or returns immediately with `--async` and handles startup in the background) and never sends before the program is ready. Known folder-trust dialogs for worktrees under `~/.herdr/worktrees/` (Claude Code, Codex, `agy`, etc.) and CLI update/upgrade prompts are answered automatically by the harness in both `send_when_ready` and `pm.py deliver`.
- **The brief was not delivered or a worker stalled:** if a startup or runtime dialog is NOT one of the known safe prompts (e.g. quota/rate-limit, auth, MCP server, hook review, or an untrusted path), the harness classifies the screen into a concise conclusion instead of dumping raw terminal text to the PM. From the PM, delegate screen inspection/unblocking with `pm.py triage <id>` (spawns an async exec helper and reports back the conclusion) — do not run `hc read` / `hc keys` inside the PM turn. Inside a triage helper, inspect with `hc read <t> | tail -60`, answer safe dialogs with `hc keys <t> <key>` (or resend `sent/<id>.md`), and report the conclusion via `pm.py helper done`. Anything risky or requiring human sign-off: ask the user.
- **Wait for a worker:** in the desktop app, nothing to run: its report is delivered to you (`[from pm.py deliver]`). In the herdr TUI, `pm.py wait <id>` in the background; it returns the worker's report from the ledger. A timeout is a check-in, not a failure: wait again.
- **Stop a turn:** `hc interrupt <t>`.
- **Question UI** (the agent shows options): read the screen, choose with `hc keys <t> ...`, or type a free-text answer with `hc send <t> "<answer>"`.

## Other machines

- `hc machine ls --json` lists connected machines; `hc exec --on <machine> "<cmd>"` runs a command there and prints its output.
- The desktop board reads each connected machine's ledger by running the skill's `pm.py state` there through `hc exec --on <machine>`, so the skill must be installed on that machine too (for any agent, or with the board mod).
