# dudu guide

The details behind the [README](../README.md): every install path and option, the full get-started commands, configuration, alerts, uninstalling, the manual layout steps, and the repository layout.

## Install

Choose either path:

- **From herdr.dev:** add the PM layout, or copy `layouts/` and `mods/` into your Herdr app folder (`~/.config/herdr-app`, or `$HERDR_APP_HOME`). Select the PM layout, open **Board**, then click **Set up**. The skill is bundled inside `pm-dash`; no repository checkout or separate installer command is needed.
- **From the repository:** clone or download this repository, then run from its root:

```bash
./install.sh          # macOS / Linux (or Git Bash)
python install.py     # Windows (cmd / PowerShell) or any platform without Bash
```

Both paths use `mods/pm-dash/setup.py`. It copies the PM skill into the skill folder of each coding agent it finds, and adds the skill's hooks for agents that have hooks:

| Agent | Skill folder (`pm.py` is in its `scripts/`) | Hooks |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/pm` | `~/.claude/settings.json` |
| Codex | `~/.codex/skills/pm` | `~/.codex/hooks.json` |
| pi | `~/.pi/agent/skills/pm` | none |

An agent is set up when its home folder (`~/.claude`, `~/.codex`, `~/.pi/agent`) exists; when none exists, Claude Code is set up, as before. `--agents claude,codex,pi` names the agents instead. The installer sets up no skill for Gemini CLI, opencode or other agents; they can still be the PM or a worker (see [Configuration](#configuration)).

The hooks are `SessionStart`, which tells a new session whether the project has a PM, and `UserPromptSubmit` and `Stop`, which note each turn of a PM session for the board and remind a PM to hand over when its context is large. Hook commands from earlier installs that ran `pm.py hook-mirror` are replaced. Existing settings and unrelated hooks are preserved. Before the first change to an existing hooks file, the installer saves its original bytes as `settings.json.pm-backup` or `hooks.json.pm-backup`; later runs keep that backup. If any hooks file is invalid, nothing is written.

Codex runs a new hook only after you trust it: it asks when it next starts. Hooks also need the `hooks` feature, which is on by default (`codex features list` shows it; `[features]` in `~/.codex/config.toml` can turn it off). The installer does not edit `config.toml`.

With `./install.sh`, if `~/.config/herdr-app` exists, the installer also copies `pm-dash`, `pm-nav`, `pm-list`, `pm-toast` and `pm-project` into its `mods/` directory and creates `layouts/pm.json` from `layouts/main.json`. The original layout is unchanged. An existing PM layout containing `pm-nav` is kept; if it has no `pm-list` block yet, the installer adds only that block (right under `pm-nav`, after saving the first `pm.json.pm-backup`); a `pm-list` block that is still right above `agents`, where earlier versions put it, stays there and the installer prints how to move it; likewise adds a missing `pm-project` block to the `pm-stage` stack; and adds `"window_drag": true` to its `pm-board` and `pm-project` blocks when they have no such field, so their title bars move the window; it leaves your other edits alone. Before replacing another existing `pm.json`, the installer saves the first `pm.json.pm-backup`. Generated layouts are marked with `generated_by: "dudu install.sh"` and include `cloned_from` metadata when the main layout has a version. If the base layout is missing or has an incompatible structure, the skill and mods still install and the script prints manual layout steps.

```bash
./install.sh --desktop          # Install desktop mods even before its config directory exists
./install.sh --agents codex,pi  # Set up only these agents
./install.sh --dry-run          # Preview without writing any files
./install.sh --uninstall        # Remove the installation, keeping the ledger
```

Options can be combined, including `--uninstall --dry-run`. Re-running the installer replaces the installed skill and mod directories to remove stale files, without duplicating hook commands. A destination linked to its repository source is left in place. Hooks are written atomically after file installation succeeds.

Installation destinations can be overridden:

```bash
CLAUDE_HOME=/path/to/claude-config \
CODEX_HOME=/path/to/codex-home \
PI_CODING_AGENT_DIR=/path/to/pi-agent \
HERDR_APP_HOME=/path/to/herdr-config \
./install.sh --desktop
```

Defaults are `~/.claude`, `~/.codex`, `~/.pi/agent` and `~/.config/herdr-app`. Use the same overrides when uninstalling. Hook commands use the selected skill path, including paths containing spaces. Codex, pi and Herdr desktop read `CODEX_HOME`, `PI_CODING_AGENT_DIR` and `HERDR_APP_HOME` themselves; `CLAUDE_HOME` only selects the install destination. The board's Set up action uses `~/.claude` for Claude Code.

The ledger lives in the ledger home, not in an agent's folder (see [Configuration](#configuration)). The desktop mods read local state with the bundled `mods/pm-dash/skill/scripts/pm.py` under `appHome()` and watch the ledger home that it reports.

Restart running agent sessions to load the skill and hooks.

## Add it from herdr.dev

This repository is also a Herdr layout: `layouts/pm.json` plus the `pm-nav`, `pm-list`, `pm-toast`, `pm-dash` and `pm-project` mods. The sidebar has the PM entry on top with the PMs right under it (each project's PM with its live status and age; click to open the project), then spaces, then agents. A project opens as one conversation with its coordinator: what you said, the PM's replies, each task as a thread line in the place it started, showing what it is now, and the PM's questions as cards with answers to pick; the side panel lists the project's open tasks, the sessions working in it and what ended last, and shows a thread's log, terminal and changes when you open one. Read [RECIPE.md](../RECIPE.md) for its behavior, dependencies, and rebuild instructions. A public GitHub repository with the `herdr-layout` topic can appear in the [Herdr layout directory](https://herdr.dev/layouts).

Open **Board** and click **Set up** to copy the bundled skill into every coding agent found and add their hooks. Before setup, the board shows a centered setup block and the sidebar says **Set up**; status checks do not write files. Success shows a reminder to restart your coding agent sessions and say “act as PM for this project”, then displays the board. Errors stay visible with a retryable button. If any installed `pm.py` differs from the bundle, the normal board shows a quiet **Update** action using the same installer. Setup is checked at startup and after the action, not on the ledger polling timer.

Local ledger reads use the bundled script. For a connected machine, the mods run `state` through `hc` with the first `pm.py` found there among the desktop bundle (`~/.config/herdr-app/mods/pm-dash/skill/scripts/pm.py`) and the Claude Code, Codex and pi skill folders; that machine keeps its own ledger. The sidebar’s remote cache starts writing only once the skill is installed for a local agent.

The shipped layout has no installer ownership marker. `./install.sh` keeps an existing layout containing `pm-nav`; otherwise it generates a layout from your own `main.json`, rather than copying the shipped file. `--uninstall` keeps the unmarked layout but removes the PM mods it needs, so switch away from it before uninstalling.

## Get started

Below, `pm.py` means `python3 <skill folder>/scripts/pm.py`, for example `python3 ~/.codex/skills/pm/scripts/pm.py` (see the table under [Install](#install)). Without an agent skill folder, use the desktop bundle: `python3 ~/.config/herdr-app/mods/pm-dash/skill/scripts/pm.py`.

1. Start a PM for your project. Either:

   - open a session of an agent with skills (Claude Code, Codex, pi) in your project directory inside the Herdr desktop app and say **“act as PM for this project”**; or
   - start one from any terminal inside the desktop app; this works for any agent, including ones without skills:

     ```bash
     pm.py start --repo /path/to/project --kind codex   # or claude, pi, gemini, opencode, …
     ```

     It starts the agent, registers it as the project's PM and gives it its first prompt. Startup can stop at a dialog of the agent's own (for example folder trust); answer it in that terminal.

   An agent session that is already running can register itself with `pm.py claim`.

2. Give the PM a concrete task, for example: “Ask a worker to add a search filter, run the relevant tests, and bring the result back for review.” The PM tracks the brief, worker, branch, and progress in the ledger. Workers run in herdr-core terminals.

3. View progress:

   ```bash
   pm.py status
   pm.py board
   ```

   Switch to the installed layout, then click the board entry under **PM** in the sidebar:

   ```bash
   herdr-app do layout.switch '{"name":"pm"}'
   ```

   The installer only prints this command; it does not switch your layout or touch running windows. `herdr-app commands` lists the commands supported by your installed version.

   For a browser board, run `pm.py dash` and open `http://127.0.0.1:7317/`.

Use `pm.py --help` for the ledger commands, and `pm.py dispatch --help` and `pm.py start --help` for agent options.

## Configuration

### Ledger home and migration

The ledger home holds tasks, PM registrations, project conversations, memories, helpers, and your configuration. It resolves in this order:

1. `$PM_HOME`, if set;
2. `~/.claude/pm`, if an earlier install created it as a real directory (not a symlink to `~/.dudu`);
3. `~/.dudu` (the default for new and migrated installs).

`pm.py home` prints the resolved ledger home and migration status; `pm.py state` also reports it as `home`.

If an earlier install keeps your ledger at `~/.claude/pm`, you can move it to `~/.dudu` safely without losing history or breaking older scripts:

```bash
pm.py home --migrate --dry-run   # Preview every step and check for running sessions
pm.py home --migrate             # Back up, move to ~/.dudu, and leave ~/.claude/pm -> ~/.dudu
```

What `pm.py home --migrate` does:

1. **Refuses while active writers are running.** If a PM, worker, helper, `deliver`, `watch`, `seat`, `wait`, `reattach`, or ledger lock is active, migration refuses and lists what to stop first.
2. **Creates and verifies a full backup first.** Before moving anything, it packs the entire `~/.claude/pm` directory into `~/.claude/pm-backups/pm-YYYYMMDD-HHMMSS-before-migrate.tgz` (override with `--backup-dir`) and verifies the archive can be read back.
3. **Preserves non-ledger files in `~/.dudu`.** If `~/.dudu` already contains leftover files from an older standalone service (for example `dudu.db`, `d.sock`, `service.lock`, `agents/`, `hc/`) or other non-ledger files, the whole folder is moved aside to `~/.dudu-legacy-service-YYYYMMDD` (or `~/.dudu-legacy-YYYYMMDD`) rather than deleted. If `~/.dudu` already contains another ledger, migration refuses rather than auto-merging.
4. **Moves and symlinks.** Moves `~/.claude/pm` to `~/.dudu` and leaves a compatibility symlink `~/.claude/pm -> ~/.dudu` so older `pm.py` copies, installed hooks, and remote skills keep working while newer versions treat `~/.dudu` as canonical. **Keep the `~/.claude/pm` symlink in place — do not delete it:** existing records in `pms/` and `tasks/` can still hold historical absolute `~/.claude/pm/...` paths that rely on it. Re-running `pm.py home --migrate` is idempotent.
5. **Updates generated settings and lists sessions to restart.** Refreshes `autoMemoryDirectory` paths in generated `pm-settings.json` / `reads/*.json` files and prints which PM and agent sessions to restart or rotate so they pick up `~/.dudu`.

The installer (`./install.sh` / `setup.py`) detects an unmigrated `~/.claude/pm` ledger and prints the migration command; it never migrates automatically.

Create `config.json` in the ledger home to set your preferences; every key is optional:

```json
{
  "lang": "zh",
  "worker": {"kind": "codex", "model": "your-model", "effort": "high"},
  "pm": {"kind": "claude", "model": "opus", "lean": true},
  "agents": {
    "mine": {"argv": ["mine", "--yes"], "model": ["--model", "{}"], "effort": [], "prompt_arg": false}
  }
}
```

`lang` defaults to `en`; set it to `zh` for Chinese. It controls built-in text, including handover prompts, the labels around recorded user quotes, and dashboard text. User quotes, task titles, and logs are kept in their original language.

`worker` gives the defaults for `pm.py dispatch`; its `--kind`, `--model` and `--effort` flags take precedence, and without either the worker program's own defaults apply. A configured `model` or `effort` belongs to the configured `kind`: it is not passed to a different program named with `--kind`. `pm` gives the defaults for `pm.py start` (`--kind`, `--model`) and `pm.py rotate` (`--model`). Without configuration, workers are Codex and PMs are Claude Code on Opus; a rotation does not carry over the outgoing PM's model. A Claude Code PM starts lean, because every turn re-reads its whole context: no MCP servers or Chrome tools, your plugins off and your other skills hidden from the model (still typable as `/name`), for that session only and without touching your Claude Code settings. Set `"lean": false` to start it with everything. The lean start passes `--strict-mcp-config`, `--no-chrome` and a `skillOverrides` setting, which need Claude Code 2.1.129 or later (`skillOverrides` works from that release; tested on 2.1.325); on an older Claude Code set `"pm": {"lean": false}`. It turns off every plugin in the PM session, Discord included: a PM you talk to through a channel plugin needs `"lean": false`.

**Any coding agent can be the PM or a worker.** `kind` names the program: `claude`, `codex`, `pi`, `gemini` and `opencode` are built in (only Claude Code and Codex are tested). `agents` adds other programs or overrides a built-in one: `argv` is the command, `model` and `effort` are the flags that carry those values (`{}` is replaced), and `prompt_arg` says the program takes its first prompt as a trailing argument; without it, the prompt is typed in once the program is ready. A kind that is not listed is run as written (`--kind "mine --yes"`). `pm.py claim` records which program a PM is, so a rotation starts the same one.

What differs between agents:

| | Claude Code | Codex | pi, Gemini CLI, opencode, others |
| --- | --- | --- | --- |
| Skill installed by setup | yes | yes | pi only |
| Session-start reminder and turn notes on the board (hooks) | yes | yes | no |
| Conversation log: what you and the PM said, kept per project and read by a handover (hooks) | yes | not run yet | no |
| Context-size warning | yes | no | no |

Everything else (ledger, dispatch, review, rotation, board) is the same for all.

The skill includes two task brief templates: `assets/brief-template.md` (English) and `assets/brief-template.zh.md` (Chinese), under `mods/pm-dash/skill/`. Choose kinds and models available in your environment; the values above are examples.

More keys, all off or empty until you set them: a pool of codex profiles with per-profile limits, a launcher for Claude Code or Codex workers, a tab of its own for each worker, closing workers once they report, and agreeing to Fable (deep) workers once instead of per task. [references/config.md](../mods/pm-dash/skill/references/config.md) in the skill describes them with an example. `"workers": {"close_on_close": true}` ends a finished task's worker terminal with the task.

The installer does not create or overwrite this configuration. The ledger home survives uninstalling.

## Alerts

In the `pm` layout (other layouts are unchanged):

- **Only the PM's toasts.** When a PM finishes its turn or needs you, Herdr's own "… finished" / "… needs you" toast shows; clicking it focuses that PM, and leaves the board (or a project view) first if one is up. Agents the PM dispatched (a terminal with a `task` label, or whose parent terminal has a `pm` label) report to the PM instead, so both of their toasts close at once without drawing anything. This is `mods/pm-toast`, which the layout uses in place of Herdr's `toast`. Agents you started yourself and every other notification look and behave as before.
- **No task alerts.** A task moving to `review` or `blocked` posts no notification of its own; the PM's turn ends and its toast is the signal.
- **Not solved: the worker's sound.** Herdr plays its finished/needs-you sound itself, apart from the toast mod, and only has the global `sounds.enabled` switch. A layout or mod cannot silence one terminal, so a finishing worker is still heard. dudu does not change your sound settings; see the roadmap.

### PM notifications

**In the desktop app** the PM waits on nothing. One deliverer per project (`pm.py deliver`, started again by the
PM's hooks, `claim`, `rotate`, `dispatch`, `review`, `escalate`, `reattach` and every ledger write that is news,
whenever none runs) lives as long as the PM's terminal: it sends the PM each worker's report, `notify` and
`event` as one message once the PM is idle (held back while you have an unsent draft there), and tells it about a
worker that can no longer report: its terminal gone, waiting at a prompt or an error, or, for an agent without
hooks (pi, agy), a turn that ended without a report. It ends by itself once the PM's terminal is gone, and starts
the new script after an install. `pm.py wait` refuses in a desktop-app PM's terminal (exit 4), and no `watch` is
needed there: each would bring the same report twice.

**In the herdr terminal UI** run `pm.py wait <task> --timeout 3600` in the background for a worker's report, and
one `pm.py watch` in the background for the PM's inbox. Handle what it prints, then start it again; do not
repeatedly call `status`, `show`, or read terminal screens while waiting. `wait` cannot see a TUI worker stop, so
there `watch` also wakes on worker states.

Start both with the agent's own background tool, the one that reports when the
command exits (Claude Code: `run_in_background: true`), never with `&`, `nohup`,
`disown` or a redirect to `/dev/null`: what such a process prints reaches no one.
`watch` refuses to start that way, and a watcher whose starter goes away stops
within five seconds without reading the inbox, so its lines wait for the next
watcher. A second watcher for the same PM is refused with the running one's
command, what started it and the number of unread inbox lines.

File notifications observe inbox appends and task-file replacements: kqueue on
macOS (it watches the inbox log and the task file themselves, since a folder
watch there does not see an append), inotify on Linux and directory
notifications on Windows. On Windows and Linux, where those report every change
in the folder (every PM's log and offset, every task file), a change wakes only
when the PM's own inbox log or the waited task's file is not as it was (inode,
size, modification time). The deliverer and desktop waits subscribe to `hc events`,
following the task's terminal when `reattach` or `escalate` replaces it; title
animations, heartbeats and an agent's progress do not trigger state queries. On
disconnect the subscription retries with bounded backoff, and a fresh snapshot
reconciles state. A 60-second reconciliation is retained for lost events,
filesystems that send no notifications, and older writers. The legacy Herdr TUI
has no hc stream; `watch --interval` controls its state-check fallback only.

A worker that stops without reporting gets a five-second grace period; repeated
events cannot shorten it. Inbox offsets, and in the herdr TUI worker snapshots,
persist between watcher runs. A PM's first watch delivers its unread inbox lines, at most
the newest 20 (while no watcher ran, `notify` typed the older ones into the PM),
and says how many it left out. No event injects text into a worker or executes a
command from a notification. `notify` still avoids typing into a PM while its
watcher runs.

Without `--repo`, `notify` goes to the PM of the task its session works on, also
from a repository nested in the project's folder (a folder that holds several
repositories' worktrees) or from another project's folder. The task is known by
the terminal's `task=<id>` label or by the Claude Code session it recorded, never
by a pane number alone (herdr TUI sessions repeat them). Otherwise it goes to the
PM of the current folder's project or of the nearest folder above it with one, up
to the home folder. `--repo <folder>` names a project: its PM, or the nearest
folder above it with one, and no other, so a project without a PM is an error
there, not the caller's task's PM. When it finds no PM, `notify` exits 1 and says
that nothing was delivered; a project without a PM needs no notify.

Installing updated scripts affects newly started waits/watchers. Already running
waits keep their old code until they exit and the PM starts the next wait; a
running deliverer notices the new script and hands over to it. There is no need
to restart worker terminals. This changes PM coordination, not
the desktop mods' separate remote-data refresh timers.

## Uninstall

```bash
./install.sh --uninstall
```

Use this command for either installation path; there is no uninstall button in the board. If you installed through herdr.dev, download this repository to run it. `--agents` limits it to the named agents.

This removes PM command hooks (commands containing `skills/pm/scripts/pm.py`) from `~/.claude/settings.json` and `~/.codex/hooks.json`, each agent's `skills/pm`, the five PM mod directories (`pm-dash`, `pm-nav`, `pm-list`, `pm-toast`, `pm-project`), and `layouts/pm.json` only when it carries the installer’s `generated_by` marker. Unmarked layouts (including layouts from older installers) are kept. If a hooks file is invalid, uninstall warns and skips its hook cleanup but still removes installed files. Other settings and hooks are kept, including unrelated commands grouped with a PM hook.

The ledger home (printed at the end), the `*.pm-backup` copies of hooks files, and `layouts/pm.json.pm-backup` are retained. The uninstaller does not restore a whole backup, so settings added after installation are not lost. If you use the desktop PM layout, switch back to `main` before uninstalling:

```bash
herdr-app do layout.switch '{"name":"main"}'
```

## Manual desktop layout fallback

Use these steps when automatic layout generation is skipped. Paths below are relative to `HERDR_APP_HOME` (default `~/.config/herdr-app`). The mods must already be installed, for example with `./install.sh --desktop`.

1. Copy `layouts/main.json` to `layouts/pm.json`. If `main.json` is absent, obtain the default layout from your Herdr desktop installation first. Keep any custom layout you want to preserve before replacing it.
2. Find the `sidebar-lists` column. Insert this node as the first element of its `children` array:

   ```json
   {"id":"pm-nav","type":"block","size":{"px":64},"content":{"mod":"pm-nav"}}
   ```

   Insert this one right after it (the mod resizes it to fit its PMs):

   ```json
   {"id":"pm-list","type":"block","size":{"px":30},"content":{"mod":"pm-list"}}
   ```

3. Replace the `work` column at its current position with this stack. In the example below, replace `<original work node>` with the **entire original `work` object**, keeping its children and other properties intact. The placeholder is not valid JSON.

   ```text
   {
     "id": "pm-stage",
     "type": "stack",
     "active": "work",
     "children": [
       <original work node>,
       {"id":"pm-board","type":"block","window_drag":true,"content":{"mod":"pm-dash"}},
       {"id":"pm-project","type":"block","window_drag":true,"content":{"mod":"pm-project"}}
     ]
   }
   ```

   `window_drag` lets the blank part of each page's title bar move the window, as Herdr's own top bars do; the pages keep presses on their controls and content.

4. At the root object, add `"toast": "pm-toast"` (hides the toasts of agents the PM dispatched; see [Alerts](#alerts)).
5. Save valid JSON, then select it with `herdr-app do layout.switch '{"name":"pm"}'`.

## Repository structure

- `install.py` / `install.sh` — desktop installation, preview, and uninstall (`install.sh` delegates to `install.py`); calls the shared skill installer.
- `layouts/pm.json` — distributable PM layout.
- `mods/pm-dash/` — desktop project/task board, including `setup.py` for per-agent skill/hooks installation and read-only status.
- `mods/pm-dash/skill/` — the single bundled PM skill (`SKILL.md`, the playbook and reference files), ledger CLI, and browser dashboard.
- `mods/pm-nav/` — desktop sidebar entry and summary; returns to work when you navigate away from the board.
- `mods/pm-list/` — sidebar PM list under the PM entry: each PM's live status and age; a click opens its project view (a remote PM: focuses it).
- `mods/pm-project/` — the project view: the project's conversation with its PM, tasks as thread lines, questions as cards, a side panel (the thread list, or one thread), and a message box that sends to the PM.
- `mods/pm-toast/` — the pm layout's notification mod: Herdr's toast, minus the agent notices of agents the PM dispatched.
- `tests/test_install.py` — installation tests using temporary directories.
