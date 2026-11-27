[Task: {title}. From the PM ({pane})]

Where: {where}

What the user asked (verbatim):
{ask}

Attachments:
{attachments}

Recent conversation pointers ({conversation_path}):
{conversation_pointers}

PM note:
{note}

Investigation & working rules:
- Investigate the codebase and facts from first principles before making changes; do not guess.
- If a product decision or user confirmation is needed, stop and report `blocked` with clear options rather than assuming.
- Stay within the requested scope; do not add unnecessary scripts, frameworks, or abstractions.
- Run targeted checks for what you changed and summarize them concisely.

Red lines:
- Do not touch the user's running apps or system settings; test only in isolated directories.
- No `git add -A`, no push, no merge.

Commits: 1–3, conventional style. Write a brief evidence note in `evidence/<topic>/README.md` if applicable. When done, report as the appended section says, then stop.
