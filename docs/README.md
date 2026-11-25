# dudu docs

- [guide.md](guide.md): user guide (install, first project, everyday use).
- Project site: [index.html](index.html), published with GitHub Pages.

The documents below are design notes and research reports written while building dudu, an app where one coding agent manages a project and dispatches work to other agents. Any coding agent (Claude Code, Codex, pi, …) can be the manager or a worker. Each document opens with a short background block stating what it covers and how much of it is built. Command and file names (`pm.py`, `PM_HOME`, `pm-dash`, …) are the real ones in this repository.

## design/: how dudu is (or will be) built

| Document | Summary |
| --- | --- |
| [project-interfaces.md](design/project-interfaces.md) | Moving project capabilities into desktop mods: files remain the single source of truth, mods spawn `pm.py` subprocesses for JSON with no SQLite and no long-running daemon, factored into four interfaces (Store / Projects / Sessions / Terminals). Partially implemented. |
| [model-selection.md](design/model-selection.md) | Selecting and combining models when dispatching tasks: four built-in profiles (`light` / `standard` / `hard` / `deep`), escalating one tier on repeated review failure, cross-model review, and pairing `hard` with an advisor. Mostly implemented. |
| [render-check.md](design/render-check.md) | Rendering every UI mod multiple times inside an isolated private Herdr instance before merge and judging pass/fail from errors thrown by the mods (`tests/render_check.py`): CLI usage, isolation, page driver, exit codes, and when it gates merges. |
| [pm-py-refactor.md](design/pm-py-refactor.md) | Splitting the 16,800-line `pm.py` into a layered package (`pmlib`): a map of what is in it and how tangled it is, the target modules and domain objects with IO behind ports, the contracts that must not change (command line, ledger files, hooks, mods, install), a nine-stage migration that keeps the existing tests green through a forwarding shim, and two bugs fixed on the way. |
| [auto-dream.md](design/auto-dream.md) | Background memory consolidation (`autoDream`): a review of the earlier draft and the final design. A read-only helper proposes merges, candidate adoption and removals as a JSON plan; `pm.py dream apply` validates every operation in code, touches only worker-written pitfalls and references, keeps history, and can undo a whole run. Triggered by a deliverer watcher, off by default, never wakes the manager. Implemented. |
| [library-repo-docs.md](design/library-repo-docs.md) | Unifying repository design docs with ledger project documents in Library: adds a curated read-only `repo_docs` root (four-stage discovery/filtering with `library.json` overrides and 200-doc tier cap), `superseded_by` graduation/demotion for unarchived ledger drafts, `@Library`/`@Files` deduplication, cross-root link resolution, and merge-triggered auto-refresh. Implemented. |

## research/: investigations and mechanism comparisons

| Document | Summary |
| --- | --- |
| [rotation-vs-compaction.md](research/rotation-vs-compaction.md) | Should manager sessions rotate at a 200k-token threshold? Combining real ledger metrics, a comparison of compaction across four coding agents, and a controlled experiment: rely on built-in agent compaction anchored to on-disk state via hooks, reserving rotation for crashes and model switches. |
| [deliver-vs-wait.md](research/deliver-vs-wait.md) | Getting worker reports to the manager: push-based `deliver` vs. blocking `wait` / `watch`, compared across reliability, token cost, and runtime environment, with concrete recommendations. |
| [agents-helpers.md](research/agents-helpers.md) | Why workers have no panel in Herdr and drop out of the Agents tree after rotation; proposes unifying sub-agents under one mechanism (threads return commits, helpers return findings) and keeping a fixed "manager seat" terminal to preserve hierarchy. |
| [library-design.md](research/library-design.md) | Drawing on Cursor Projects and Claude Projects, scopes the project Library strictly to documents and research reports, splits memories into a dedicated Memory page, and proposes a topic/type organization and cleanup plan for existing memories. |
| [at-mention.md](research/at-mention.md) | Drawing on Cursor: `@` in the input box is a typed context pointer rather than a message router. Defines three target categories (`Threads` / `Library` / `Files`), a two-level menu, keyboard behavior, inline chips, and plain-text link serialization. |
| [render-check-locked.md](research/render-check-locked.md) | macOS stops scheduling display-link frames for non-visible windows during screen lock or display sleep. Switching to synchronous frame rendering via `herdr-app shot` while hiding the private app keeps real UI rendering working while locked: root-cause analysis, alternatives, and live verification. |
