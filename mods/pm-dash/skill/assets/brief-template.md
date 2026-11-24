[Task: <one-line title>. From the PM (herdr pane <PM pane>)]

Where: <worktree path>, branch <branch>, based on <base> <short sha> (<version>). <files prepared for you that must not be committed, e.g. the .tools link>

What the user said (their words):
- <...>

The chosen solution (start from first principles to find the right approach, then implement it within the task's scope: do not expand scope, add no scripts, tools or abstraction layers the task does not need, only the few tests that are needed, short evidence):
1. <change>
2. <change>

Design and research (design or research tasks; replaces "The chosen solution" above when no solution is set yet; delete this part for other tasks):
- Goal and scope: <the problem to solve, boundaries and hard constraints>.
- Start from the requirements themselves and work out the right design or approach from first principles, without accommodating the existing code; if the current approach is wrong, say so and replace it.
- Once the right design is clear, lay out how to get there from the current state (steps, trade-offs and risks).
- Write the conclusions and report to `evidence/<topic>/README.md` (start with a `# <title>` heading). `evidence/` stays local and unpublished; when you report, `pm.py` automatically collects it (into the main checkout when git ignores `evidence/`, otherwise into the project's ledger `research/` folder) so it appears in Context.

Coverage (bug fixes, done before the work goes to review; delete this part for other tasks):
- List every place the data or text is used: where it is written, every place it is read (pages, exports, notifications, logs), the repository that holds the real menu entry, other entries to the same component or interface. The hand-off (merge or pull request description) carries a table: entry | repository and file | changed / not changed / not affected | how it was checked. Give a reason on every "not changed" row.
- List what is kept on purpose: text still shown in the original language after switching, column headers or keys that are never translated, neighbouring items out of scope. Give a reason for each; the PM confirms them with whoever filed the bug, and nothing unconfirmed is kept.
- Check every number the bug states against kept samples (the real maximum) first; the PM gets the product owner to fix the value.
- Replay the bug: on a build with the fix, follow the bug's own steps, including leaving and coming back after saving (and switching language where text is involved); run once more with non-default data. Anything you could not do goes in the report's first line, and then do not suggest closing the bug.
- The resolution note in the bug tracker has seven parts: root cause, solution, files changed, modules affected, steps to retest, expected result (with what is kept on purpose and who confirmed it), build version.

Red lines:
- Do not touch the user's running apps; test only with isolated copies (separate bundle ID or config directory).
- Computer use and UI tests run in background, small-window mode: do not steal focus (open -g / --background / Accessibility APIs), do not activate or raise windows, no global mouse or keyboard events, keep windows small and out of the way, capture only the target window, close what you opened. If a step truly needs the foreground, stop and ask the user first.
- Do not change system permissions, lock state or network configuration.
- No `git add -A`, no push, no merge.

Verification (only these):
- <targeted unit tests>
- <one real run, cleaned up afterwards>
- The project's full check list: <copied from the project profile>

Commits: 1–3, conventional style, ending with <session attribution line>. Write a dozen lines in evidence/<topic>/README.md. For parallel read-only research or checks, you may start up to 3 temporary helpers (`pm.py helper start` / `wait` / `ls` / `stop`, default `opus`/`neon` profile, no PM approval needed); if parallel code edits/commits are needed, propose a sub-thread (`dispatch --parent`) to the PM in the ledger. When done, report as the section appended below says, then stop.
