# Model Selection and Multi-Model Composition at Dispatch

> **Background**: This design note examines how dudu's project manager chooses models for workers when dispatching tasks, and how multiple models are combined across a task's lifecycle. Written in November 2026.
> **Status: Mostly implemented.** `mods/pm-dash/skill/scripts/pm.py` now ships four built-in profiles — `light` / `standard` / `hard` / `deep` (`dispatch --profile`) — along with a per-profile review model table, `pm.py escalate` to step up one tier after two failed review rounds, a user confirmation question card before dispatching or escalating to `deep`, `worker` / `escalations` / `rounds` fields on task records, and model badges in the `pm-project` sidebar. The sections below preserve the original design analysis and trade-offs; where details differ from the current code, `pm.py` and `mods/pm-dash/skill/SKILL.md` are authoritative.
> Model names and pricing reflect Anthropic's public documentation at the time of writing; the `kind` in any profile can be swapped to any coding agent (Claude Code, Codex, pi, etc.).

References: Anthropic's [Choosing the right model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model) and [Optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence), plus Claude Code's [advisor](https://code.claude.com/docs/en/advisor) and [model-config](https://code.claude.com/docs/en/model-config) documentation.

## 0. State at Design Time

- `pm.py dispatch` already accepted `--kind/--model/--effort`, defaulting to `worker` in `config.json`. A typical config was `{"kind": "claude", "model": "opus"}`, running every task on the same model at the same effort.
- **An existing bug:** `AGENT_KINDS["claude"]` had an empty `effort` flag template (and a test explicitly asserted that Claude took no effort flag). Yet Claude Code already supported `--effort low|medium|high|xhigh|max`. When the playbook told managers to pass `--effort xhigh` on high-risk tasks, the flag was **silently dropped** for Claude workers. (Fixed: Claude's entry now passes `--effort`.)
- Model choice was recorded only inside the free-text dispatch note, not in a structured task field. Neither the sidebar nor the board could display it, and rework rates could not be aggregated by model afterward.
- When the manager spawned a sub-agent to review a task, it specified no model, inheriting the manager's own model. Whenever the coding worker also ran Opus, the same model ended up reviewing its own code.

## 1. Takeaways from the Documentation Relevant to dudu

| Finding | Implication for dudu |
|---|---|
| Start most tasks on Opus 5.5, whose default effort is `medium` | Use Opus 5.5 at its default effort for the `standard` profile |
| Tune effort first, switch models second, combine multiple models last | Differentiate profiles primarily via effort; stepping up to Fable is the last resort |
| Opus 5.5 coding benchmark: `medium` 86.6% / $0.84 vs. `xhigh` 91.1% / $4.11 | `xhigh` costs roughly 5x as much; reserve it for high-risk tasks |
| Fable 5.2 ($8/$40) costs twice as much per token as Opus 5.5 ($4/$20); suited to multi-hour, ambiguous, end-to-end tasks | Reserve Fable for `deep` tasks or tasks where Opus `xhigh` failed |
| Running everything at `low` and retrying failures at `high` matches pass rate at ~40% lower cost — **given a reliable failure signal** | dudu's review and verification gates provide a built-in failure signal, making escalate-on-failure practical |
| Opus orchestrator + Haiku worker sub-agents: 32% cheaper, but pass rate drops 4.2 percentage points | Do not default coding workers to a cheap model; limit cheaper models to easily verifiable tasks |
| Advisor (a cheaper executor consulting a stronger model on hard decisions): Opus `high` + Fable advisor scores 90.1% / $2.92 vs. Opus `medium` alone at 86.6% / $0.84; if most tasks consult the advisor, using the stronger model directly is cheaper | Enable the advisor only on the `hard` profile, not by default |
| Evaluations never let a model grade its own output | Review must use a different model from the worker |
| Optimize for cost per completed task, not cost per token | Record profile and rework rounds in the ledger so real data is available later |

## 2. Design

### 2.1 Profiles: The Manager Picks a Tier Name, Not a Model ID

Add `profiles` to `config.json` and `--profile` to `dispatch`:

```json
{"worker": {"profile": "standard"},
 "profiles": {
   "light":    {"kind": "claude", "model": "sonnet", "effort": "medium"},
   "standard": {"kind": "claude", "model": "opus"},
   "hard":     {"kind": "claude", "model": "opus", "effort": "xhigh", "advisor": "fable"},
   "deep":     {"kind": "claude", "model": "fable", "effort": "high"}
 },
 "review": {"standard": "fable", "hard": "fable", "deep": "opus", "light": "opus"}}
```

- When omitted from `config.json`, these four built-in profiles apply; explicit `--kind/--model/--effort` flags still override values from the profile (CLI wins).
- Why profiles help: cost policy lives in a single user-owned file; when a new model ships, updating one line updates everything without touching the playbook; the manager reasons about `"hard"` rather than model IDs that go stale.
- Switching to Codex only requires changing `kind` to `codex`. Different profiles can even use different agent CLIs.

**How the manager picks a profile** (documented in the playbook):

| Profile | Task shape | Examples |
|---|---|---|
| `light` (Sonnet 5.5 · `medium`) | Mechanical, narrow scope, trivially verifiable | Copy or translation edits, renames, adding one unit test, read-only fact gathering |
| `standard` (Opus 5.5 · default) | Most feature work and bug fixes | Mod UI work, `pm.py` subcommands, ordinary bug fixes |
| `hard` (Opus 5.5 · `xhigh` + Fable advisor) | High blast radius or multi-step reasoning | Releases, security, protocol compatibility, concurrency, migrations, cross-module refactors; also the first escalation target |
| `deep` (Fable 5.2 · `high`) | Multi-hour, ambiguous goals, end-to-end delivery | Architecture design docs, root-cause investigations carried through to a finished report, tasks where `hard` still failed |

When dispatching, the manager records the chosen profile and a one-line reason in the note, e.g. `hard: touches terminal handover in rotate`.

### 2.2 Composition 1: Escalate on Failure (Primary Composition Pattern)

Because dudu already has code review as a failure signal, starting at a sufficient tier and stepping up on failure gives the best cost/quality trade-off:

1. When a task fails its first review, send the findings back to the **same worker**.
2. If the same task fails review a second time — or if the worker reports being stuck on capability rather than waiting for a product decision from the user — escalate one tier: `light` → `standard` → `hard` → `deep`, one step at a time.
3. Escalation starts a fresh worker **in the same worktree and on the same branch**: it gets a clean context window, the original brief, the findings from prior reviews, and instructions noting that the previous worker's commits are already on the branch so it should continue from there rather than start over. The old terminal is closed, the task ID stays the same, and a ledger entry is appended, e.g. `escalated to hard (Opus·xhigh): failed two review rounds`.
   - Why not switch models in place via `/model` inside the original worker? Anthropic's guidance notes that retry gains come largely from a fresh second attempt once the original context has gone down a rabbit hole; moreover, switching across agent kinds (such as Codex to Claude) requires spawning a new process anyway.
4. Add `pm.py escalate <id> [--profile <tier>]`, defaulting to one tier up when `--profile` is omitted.

### 2.3 Composition 2: Cross-Model Review

- The reviewer must not be the same model that wrote the code. For `hard` and `deep` tasks, the reviewer should be at least as capable as the worker, selected via the `review` mapping in `config.json` (shown above).
- When the manager delegates review to a sub-agent, it explicitly passes the review model (e.g., the `model` parameter on Claude Code's Agent tool).
- If review later moves to a standalone ledger thread, it simply dispatches a read-only thread using the same `review` table.
- Optional: review Claude-authored code with Codex (cross-vendor models have less correlated blind spots). Left open for user decision; see §4.

### 2.4 Composition 3: Advisor (`hard` Profile Only)

- Add `"advisor": ["--advisor", "{}"]` to `AGENT_KINDS["claude"]`, passing it only when a profile specifies `advisor`; agent kinds without advisor support ignore the field and note that in the dispatch log.
- At design time, `--advisor` had not yet been verified in headless operation and needed a quick spike first: `--advisor` did not appear in `claude --help`, the feature was still experimental, first-time use of Fable as an advisor required accepting Fable billing (a prompt that could stall a background worker at startup), and when the API rejected an unsupported pair Claude Code **silently** sent requests without the advisor. The spike needed to confirm two things: non-interactive startup does not block on a billing dialog, and `Advising` actually appears in the session transcript. If the spike failed, `hard` would fall back to `xhigh` alone without an advisor.
- Current implementation: if a worker launched with an advisor exits immediately on startup, the task is marked `blocked` with actionable options (such as retrying `hard` without an advisor via `--advisor none`). Environments without Fable access can set `"fable": false` in `config.json`, which strips the advisor from `hard`, disables `deep`, and routes reviews that would have used Fable to an alternate model so workers still never grade their own work.

### 2.5 Which Model Runs the Manager

The manager is the orchestrator in an "orchestrator + parallel workers" setup. It runs across many turns with a large context window, but each turn is mostly coordination decisions and user conversation. Keeping the manager on Opus 5.5 (`"pm": {"kind": "claude", "model": "opus"}`) rather than Fable avoids doubling per-turn token cost on a large context where Fable's extra depth would go unused. Tasks need Fable; coordination does not.

### 2.6 Ledger and UI

- Add structured fields on each task: `worker: {profile, kind, model, effort, advisor}` and `escalations: [{from, to, why, at}]`, incrementing `rounds` whenever a review fails.
- In the sidebar thread header, show a subtle badge beside the existing agent icon (such as `Opus·xhigh`), revealing the profile name and dispatch reason on hover — no new buttons or bulky cards. Escalated tasks prefix the badge with a small upward arrow (`↑`).
- With these fields recorded, dudu can later answer questions like "how many rework rounds does each profile average?" without building a dedicated analytics command upfront.

## 3. What We Deliberately Skip (and Why)

- **Starting everything at `low` and escalating on failure**: saves ~40% in benchmarks, but every failure in dudu costs a full review round and adds wall-clock wait time for the user. Defaulting to `standard` and escalating only on failure keeps latency predictable.
- **Auto-routing tasks with Haiku**: the manager is already the router; adding a classifier layer in front only introduces another failure point.
- **Fast mode**: costs 2x per token while workers run asynchronously in the background where nobody is watching keystrokes live.
- **Running multiple models in parallel on the same task and picking the best**: multiplies cost severalfold. Reserved for explicit user requests (e.g., "draft three UI directions so I can pick one"), which the manager can already dispatch manually as separate threads.
- **Consulting an advisor on every turn or attaching an advisor to the manager**: benchmarks show overly frequent advisor calls cost more than simply running the stronger model directly.

## 4. Decisions and Open Questions

1. **Who approves the `deep` profile**: Decided. Before dispatching at `deep` (Fable) or escalating a task to `deep`, the manager posts a question card (marking the task `blocked` with choices) and waits for user approval; `hard` and below are decided autonomously by the manager. When `pm.py escalate` targets `deep`, it posts the question card instead of spawning the worker immediately, then proceeds once re-run with `--confirmed` after approval. Users can also pre-approve `deep` once in `config.json` (see the Deep section in `references/config.md`).
2. **Whether to review Claude workers with Codex**: Open. Recommended to defer for now: every additional CLI brings another interactive startup hurdle to troubleshoot (such as hook trust prompts). Revisit once reviews run as standalone dispatched threads.

## 5. Rollout Order

1. Fix the Claude `--effort` bug (independent of all other steps).
2. Run the advisor spike: produce findings only, no production code edits.
3. Profiles + task fields: `--profile`, four built-in profiles, `profiles`/`review` in `config.json`, `worker` metadata on tasks, and unit tests; include `--advisor` depending on step 2.
4. `pm.py escalate` plus playbook sections covering profile selection, cross-model review, and escalation (depends on step 3).
5. Sidebar model badge in `pm-project` (depends on step 3's fields).

Steps 1 and 2 can run in parallel; once step 3 lands, steps 4 and 5 can run in parallel. Changes to `pm.py` must remain backward-compatible because connected remote machines may still carry an older installed copy.
