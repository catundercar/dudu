# herdr-core recipes and pitfalls

Terminals in the Herdr desktop app run in herdr-core; its CLI is `hc`. For the full CLI, run `hc --help` or `hc --skill` once. Below are only the patterns that proved reliable in practice. `<t>` is a terminal address such as `t7`, or `<machine>/t7` on another machine.

## Terminals

- **State of one terminal:** `hc get <t> --json`. An agent's state is under `status` (`app`, `state`); values seen are `idle`, `working`, `done`, and no status at all while a program is still starting or sits at a startup dialog.
- **Read the screen:** `hc read <t> | tail -40`.
- **Start a program in a terminal of its own:** `hc run --bg --name <name> --cwd <dir> -- <program> <args>`. It becomes a sub-agent of the terminal that started it: the app lists it under that agent, without a pane (`herdr-app do terminal.peek '{"terminal":"<t>"}'` shows it, `terminal.keep` gives it a tab). A sub-agent ends with its parent unless started with `--outlive-parent`; `pm.py dispatch` uses that, so a worker survives its PM's rotation. `--no-parent` starts a terminal that the app does not show at all. `--no-notify` stops hc from typing notes about the child into its parent.
- **`--json` goes before `--`.** Anything after `--` is passed to the started program.
- **Labels:** `hc label <t> pm=<project>` marks a PM, `task=<id>` a worker. The board uses them to find the terminal to jump to.
- **End and remove:** `hc kill <t>`, then `hc rm <t>`. `pm.py retire` does both for a worker.

## Agents

- **Send a brief:** `hc send <t> "$(cat brief.txt)"`. Long multi-line text works. The result contains `"started": true` when the agent took it as a turn.
- **A just-started agent is not ready.** Wait until its state is `idle` before sending; `pm.py dispatch` does this and retries for a short while.
- **The brief was not delivered:** a startup screen took the input or blocked it. Codex asks whether to trust a folder it has not seen, offers an update when one is out (`pm.py dispatch` turns that check off with `-c check_for_update_on_startup=false`), and shows a hook review screen ("1 hook needs review") the first time it meets a new hook. Read the screen. If the dialog is one the user would confirm (their own folder, a hook they installed), answer it with `hc keys <t> <key>`, then resend the brief. Anything else: ask the user.
- **Wait for a worker:** `hc wait <t> --timeout 3600` in the background. A timeout is a check-in, not a failure: read the screen and wait again.
- **Stop a turn:** `hc interrupt <t>`.
- **Question UI** (the agent shows options): read the screen, choose with `hc keys <t> ...`, or type a free-text answer with `hc send <t> "<answer>"`.

## Other machines

- `hc machine ls --json` lists connected machines; `hc exec --on <machine> "<cmd>"` runs a command there and prints its output.
- The desktop board reads each connected machine's ledger by running the skill's `pm.py state` there through `hc exec --on <machine>`, so the skill must be installed on that machine too (for any agent, or with the board mod).
