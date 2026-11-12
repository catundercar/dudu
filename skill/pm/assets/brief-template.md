[Task: <one-line title>. From the PM (herdr pane <PM pane>)]

Where: <worktree path>, branch <branch>, based on <base> <short sha> (<version>). <files prepared for you that must not be committed, e.g. the .tools link>

What the user said (their words):
- <...>

The chosen solution (smallest change that does it: no new measuring scripts or tools, no new abstraction layers, only the few tests that are needed, short evidence):
1. <change>
2. <change>

Red lines:
- Do not touch the user's running apps; test only with isolated copies (separate bundle ID or config directory).
- Computer use and UI tests run in background, small-window mode: do not steal focus (open -g / --background / Accessibility APIs), do not activate or raise windows, no global mouse or keyboard events, keep windows small and out of the way, capture only the target window, close what you opened. If a step truly needs the foreground, stop and ask the user first.
- Do not change system permissions, lock state or network configuration.
- No `git add -A`, no push, no merge.

Verification (only these):
- <targeted unit tests>
- <one real run, cleaned up afterwards>
- The project's full check list: <copied from the project profile>

Commits: 1–3, conventional style, ending with <session attribution line>. Write a dozen lines in evidence/<topic>/README.md. When done, report briefly and stop.
