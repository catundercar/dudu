# Changelog

All notable changes to dudu. Dates are UTC.

## Unreleased

- The README is short and points to [the guide](docs/guide.md) for the details.
- A home page on GitHub Pages: https://catundercar.github.io/dudu/
- A project on a remote machine opens in the project view, like a local one, instead of in its manager's terminal.
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
