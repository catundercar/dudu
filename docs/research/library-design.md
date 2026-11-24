# Project Library and Memory Design: Lessons from Cursor Projects and Claude Projects

> **Background**: This report examines what belongs — and what does not belong — inside dudu's project `Library`, and how the separate `Memory` view should be structured, drawing on Cursor Projects and Claude Code Projects (beta). Written in November 2026.
> **Status**: Decided and adopted so far: `Library` holds only project documents and research reports, while memories live on a separate `Memory` page; research reports are read-only, whereas project documents and memories can be edited directly in the panel. The memory topic grouping, `pitfall` type, and existing-memory cleanup plan in Section 4 are design proposals.
> Descriptions of both third-party products cover only publicly observable behavior in released versions, grounded primarily in their official documentation and engineering blog posts (listed in Section 6).

---

## Executive Summary

1. **Separate project data from first principles into four distinct planes**:
   - **(1) `Library` (project references & deliverables)**: specs and reference docs added by the user, plus durable findings produced by threads (research reports, design docs). **Holds only documents and research reports — no memories and no transient runtime state.**
   - **(2) `Memory` (standing rules & hard-won lessons)**: product/architecture decisions, collaboration conventions, external reference pointers, personal preferences, and worker-facing engineering pitfalls. **Lives on its own page, grouped by topic and stratified by signal-to-noise rather than dumped into a single flat list.**
   - **(3) Scheduling & session runtime state**: active threads, conversation logs, manager handover notes (`handover.md`), delivery cursors (`delivered.json`). **Belongs to the scheduler, board, and conversation views — never in Library.**
   - **(4) Merge gates & raw debugging scratch**: `verify` scripts, backup files left by manual edits, render-check screenshots, one-off probe scripts. **Belongs to merge verification or ephemeral troubleshooting — never in Library.**

2. **How Cursor Projects partitions its storage tree** (`project/{docs, internal, inbox}`, `user/{…, canvases}`):
   - `docs/` shown at full contrast: formal analyses and design docs written by the coordinator or sub-agents for the project owner, surfaced in the top "Recent files" strip.
   - `internal/` dimmed: troubleshooting scratch notes and raw evidence written by sub-agents and the coordinator.
   - `inbox/` dimmed: persistent inbox for external event subscriptions (GitHub PRs, Slack, Linear, scheduled triggers). Events land on disk first before waking the coordinator to read them on demand, keeping bulky webhook payloads out of the conversation context.
   - `internal` and `inbox` are **dimmed rather than hidden** — much like `.gitignore` entries in an IDE tree — so frequent scratch writes never drown out `docs/`, while staying one click away whenever the user wants to inspect raw evidence.

3. **Problems in dudu's current memory store and proposed fixes**:
   - Engineering pitfalls were broadly mislabeled as "Decision": the worker brief template instructed workers to record discovered pitfalls with `--type project`, while the localized UI rendered the generic `project` type badge as "Decision" rather than "Project".
   - Organization: **split top-level scope into Project Memory / Personal Memory, group Project Memory into 6 collapsible topic folders, and tag each row with one of 5 type badges**; borrowing Cursor's dimmed-and-collapsed pattern, keep `Engineering pitfalls` and non-empty `Pending candidates` dimmed and collapsed by default.
   - On-disk layout: Anthropic's official docs describe Claude Code auto-memory as a flat directory containing `MEMORY.md` plus topic `.md` files with no subdirectory concept, and in observed behavior memories created by Claude itself land at the top level of that directory. **Keep files flat on disk as `memory/<slug>.md` with a `topic` field in YAML frontmatter**, rendering the grouped tree in the UI and sectioned headings inside `MEMORY.md`.
   - Audit of dudu's live store at the time (84 project memories, 9 personal memories): found 22 engineering pitfalls mislabeled as decisions, 5 duplicate/overlapping clusters, 1 stale entry contradicting a newer decision, and 2 one-off task logs stored as permanent memories.

---

## 1. Cursor Projects: Storage Tree and Library Mechanism

### 1.1 Three Scopes

Cursor Projects mounts project storage as an explicit file tree synced bidirectionally between cloud VMs and local machines:

- **Project scope (`project` in UI)**: shared read/write across the project coordinator, all sub-agents it spawns, and collaborators' agents in multiplayer projects, with conflict detection on concurrent writes.
- **Personal scope (`user` in UI)**: mounted only for that user's own agents, invisible to collaborators. When multiplayer is enabled on a project, the coordinator asks whether project-relevant personal preferences should be copied into `project`.
- **Repository rules (checked into Git rather than the Store)**: `.cursor/rules/*.mdc` (supporting always-on, path-glob auto-attachment, description-matched agent selection, and manual `@rule` invocation) alongside `AGENTS.md`. Cursor retired its earlier opaque auto-Memories in favor of explicit files.

### 1.2 What Each Directory Holds and Who Writes It

| Tree node | Contents | Writers | UI presentation |
| :--- | :--- | :--- | :--- |
| `project/docs` | Formal research reports, architecture analyses, and design specs meant for the project owner | Coordinator, doc-producing sub-agents, or manual user creation/edits | Full contrast; eligible for the top "Recent files" preview strip |
| `project/internal` | Troubleshooting scratchpads, root-cause probes, raw evidence, sub-agent handoff notes | Primarily sub-agents, plus coordinator debugging notes. Official guidance puts human-facing docs in `docs/` and working notes/evidence in `internal/` | Dimmed, collapsed by default, excluded from Recent files |
| `project/inbox` | Raw payloads delivered from external event subscriptions | Cursor's event delivery service only. The public Projects API lists `inbox/` as a reserved path rejecting external writes | Dimmed, collapsed by default, excluded from Recent files |
| `user/canvases` | Personal interactive visual canvases | Generated via Agent canvas tools or created manually | Shown under `user`, reusable across projects, excluded from project Recent files |
| `user/<integration>` | Per-integration personal bot/connector state, alongside personal preference files and skills | Written automatically by the corresponding integration | Shown under `user` |

#### `inbox/` Workflow

Per Cursor's official documentation and blog posts, external subscriptions (GitHub PRs, Slack, Linear, scheduled runs) are never dumped straight into the coordinator's chat stream: incoming payloads are written into `inbox/` inside the project store first (listed as a reserved path in the public Projects API), and then wake the coordinator, which reads them on demand and decides whether to ignore the event, update the task board, or dispatch a sub-agent. Large webhook payloads thus never bloat the main conversation context.

#### Why `internal/` and `inbox/` Are Dimmed Rather Than Hidden

The UI applies two-tier filtering:

- **Excluded from highlights**: the top Recent files strip omits `internal/` and `inbox/` (as well as task-board metadata), so bursts of webhooks or scratch notes never push design docs out of view;
- **Muted inside All Files**: in the full tree below, both folders remain browseable at reduced opacity and collapsed by default.
- **Underlying principle**: operational scratch data should not compete for attention day-to-day, yet the system must not become a black box either. Whenever a user wonders whether a PR webhook arrived or wants to inspect the raw probe behind a report, clicking the dimmed folder reveals everything. **dudu's `Memory` page can apply the exact same pattern to worker engineering pitfalls and unreviewed memory candidates.**

---

## 2. Claude Code Projects (beta): Library and Memory Mechanism

Grounded primarily in Anthropic's official *Claude Code Projects (beta)* and *How Claude remembers your project* documentation, cross-checked against released desktop and CLI builds.

1. **Clean three-way separation of UI surfaces** (adopted by dudu as well):
   - **Overview › Threads**: dedicated strictly to concurrent execution. The coordinator works from recent conversation turns, recent thread summaries, and project memory, while child threads run in isolated clones or worktrees.
   - **Overview › Library**: holds **only user-uploaded reference materials** (mounted read-only in the sandbox, stripping dotfiles and `node_modules` on upload) and **thread deliverables** (research reports, generated files, Artifacts, PRs). Every deliverable credits Claude and links back to the thread that produced it, with pinning, list/grid toggle, and type filters.
   - **Project settings › Memory**: manages *Project instructions* (character-capped, injected into every new thread) and *Auto memory* (`MEMORY.md` plus topic `.md` files), with create/edit/delete controls and optimistic concurrency checks — completely separate from Library.

2. **Two structural constraints in Claude's memory layer** (which directly shape dudu's on-disk design):
   - **Constraint A — Auto-memory directories are flat**: official documentation describes a single directory containing a `MEMORY.md` index alongside topic `.md` files, with no mention of subdirectories; in observed behavior, memories written by Claude itself always land at the top level of that directory. At session start only the opening slice of `MEMORY.md` (the first 200 lines per official docs) is preloaded, while individual topic files are read on demand.
   - **Constraint B — Path-scoped engineering rules belong in `.claude/rules/*.md`, not Auto memory**: official docs advise keeping code-derivable facts and module-local rules out of Auto memory, placing path-specific rules into `.claude/rules/<topic>.md` with YAML `paths:` globs so they consume zero tokens until an agent touches matching files.

---

## 3. dudu's `Library` Panel: What Stays and What Moves Out

Previously, `pm.py project context <slug>` returned a wide mix of files. Under the decision that `Library` holds only documents and research reports, each category lands as follows:

| Item category | Examples | Destination | Rationale |
| :--- | :--- | :--- | :--- |
| Merge-gate scripts & editor backups | `verify` and leftover manual backup files | **Remove from Library** (delete stray backups; keep `verify` internal to the ledger or surface later under project settings) | Gate configuration, not project knowledge |
| Manager handover note | `handover.md` | **Remove from Library** | Ephemeral snapshot of which pane ran what at rotation time; goes stale immediately |
| Generated memory indexes | `memory/MEMORY.md`, personal `MEMORY.md` | **Hide in UI** (keep on disk for agent startup injection) | 100% machine-generated from individual memory files; showing it duplicates every entry |
| Unreviewed candidate folders & empty dirs | `memory/candidates/**` | **Remove from Library** (prune empty dirs automatically; show non-empty candidates in a dimmed footer section on `Memory`) | Unverified staging area; empty dirs are a pre-creation artifact |
| Project & personal memories | `projects/<slug>/memory/*.md`, `~/.claude/pm/memory/*.md` | **Move out of Library onto dedicated `Memory` page** | Follows Claude Projects so dozens of bite-sized rules do not bury design specs and reports |
| Formal project documents | Specs and user-dropped reference docs | **Keep in Library** (allowlisted root `docs`: `projects/<slug>/docs/`) | Editable and deletable in-panel (with `.history/` recovery) plus drag-and-drop import |
| Research reports | Thread research READMEs; migrating over time to `projects/<slug>/docs/research/` | **Keep in Library** (allowlisted root `research`, read-only) | Excludes screenshots and probe scripts; uses H1 as title, links back to originating thread, and copies back from worker worktrees on finish/merge |
| Repository-wide agent instructions | `CLAUDE.md`, `AGENTS.md`, `.claude/coordination.md` | **Include in Library** (allowlisted root `instructions`, read-only) | Centralizes repo-wide standing instructions for inspection |
| Chronological decision log | `decisions.md` | **Unpin and demote to a collapsed historical archive at the bottom of Docs** | Once the ~16 unmigrated historical decisions are promoted into structured memories, hide from the default list |

---

## 4. dudu's `Memory` Page and Memory Organization (Proposal)

### 4.1 Diagnosing Current Issues

Auditing dudu's live store at the time (84 flat project memories in `memory/`, 9 personal memories, and 1 unreviewed candidate) surfaced four structural issues:

1. **Collapsed type taxonomy and misleading localized badge: engineering pitfalls labeled as "Decision"**
   - `pm.py` had only four types: `user`, `feedback`, `project`, and `reference`. `pm.py decide` wrote user-approved product/architecture/UI decisions (~53 entries carrying user quotes) as `type: project`; meanwhile, the worker brief template instructed workers to record empirical gotchas via `pm.py remember … --type project --verified …` (~22 entries with verification notes and no user quote), also landing as `type: project`.
   - While the English UI rendered `project` generically as `"Project"`, the localized label rendered it as `"Decision"`.
   - As a result, the top of the memory list filled up with freshly logged test/harness quirks all wearing `"Decision"` badges, drowning out actual product and workflow decisions.

2. **Flat chronological list with no hierarchy**: both the UI and `MEMORY.md` sorted everything by `mtime` descending. At ~16.5 KB, `MEMORY.md` risked truncating older entries past the 200-line startup preload window.

3. **Single-sentence literal deduplication**: `alike()` compared only the one-line `description` via `SequenceMatcher` (0.75 threshold). Two workers phrasing the same trap differently scored 0.15–0.41 similarity and wrote duplicate files whose slugs differed by a single hyphen — nor was there any check when a new decision superseded an older one.

4. **Redundant `MEMORY.md` injection and unsplit audience roles**: when Claude Code ran as manager, its native auto-memory already loaded `projects/<slug>/memory/MEMORY.md` at startup, yet `cmd_handover()` called `memory_block()` and printed the entire index a second time. Worse, so long as worker-only pitfalls lived inside `MEMORY.md`, trimming pitfalls out of `handover` still left the manager reading every pitfall via native auto-memory.

### 4.2 Grouping Structure

- **Grouping by author (user / manager / worker / migration)**: poor primary axis — someone looking up board styling rules cares about the subject, not who wrote the file (only unreviewed candidates need provenance separation).
- **Grouping by type alone**: too coarse — `"Decision + Feedback"` alone spans ~60 entries.
- **Proposed structure**: **two scopes (Project / Personal) × topic folders (primary grouping) + trailing type badges + Cursor-style dimmed/collapsed sections**.

Clustering dudu's existing memories maps cleanly onto six fixed project topics (entry counts in parentheses):

```text
▾ Project memory (84 → ~76 after cleanup)
  ▾ Product & architecture (architecture · 11)
  ▾ UI & interaction (ui · 28; can split further into board / project view / global)
  ▾ Collaboration & dispatch (workflow · 9)
  ▸ Environment & releases (ops · 7)
  ▸ Reference index (reference · 3)
  ▸ Engineering pitfalls (pitfalls · ~20)      [dimmed · collapsed by default]
  ▸ Pending candidates (candidates · shown only when non-empty) [dimmed · collapsed by default, with Promote / Discard]

▾ Personal memory (9, applies across projects)
  ▾ Collaboration & communication rules (5)
  ▸ Machine & environment (4)
```

Expand type badges to 5 distinct types:

| `type` | Badge | Who writes & validation rule | Injected into |
| :--- | :--- | :--- | :--- |
| `project` | Decision | User or manager (`pm.py decide` / `remember --quote`) | Manager + all workers |
| `feedback` | Feedback | User-corrected or confirmed working conventions (with `--quote`, project or personal scope) | Manager + all workers |
| `reference` | Reference | Pointers to key docs, design links, or external systems | Manager; workers `recall` on demand |
| `pitfall` (*new*) | Pitfall | Non-obvious empirical traps verified by workers, reviewers, or the manager (`--verified`) | **Worker briefs only — omitted from manager `handover` and manager-facing `MEMORY.md`**; shown dimmed & collapsed under `Engineering pitfalls` on the `Memory` page |
| `user` | User | Cross-project personal background & preferences (personal scope only) | Manager (personal `feedback` entries also go to workers) |

> **Graduation rule (inspired by `.claude/rules/`)**: `pitfall` entries should not accumulate forever. Traps caused by a repo bug (e.g. a missing regex word boundary in a test) should be retired via `forget` once fixed; durable rules tied to specific source paths (e.g. updating two exclusion lists whenever adding `test_*.py` under `skill/scripts/`) can graduate into `.claude/rules/<topic>.md` with YAML `paths:` globs so they cost zero tokens outside matching edits.

### 4.3 Real Subdirectories on Disk vs. Flat Files with Frontmatter `topic`

| Dimension | **Option A (recommended): flat `memory/<slug>.md` + frontmatter `topic`** | **Option B: real subdirectories `memory/<topic>/<slug>.md`** | **Option C (hybrid): flat core memories, real `pitfalls/` & `candidates/` subdirs** |
| :--- | :--- | :--- | :--- |
| Claude Code auto-memory compatibility | Fully compatible: matches the flat layout in official docs, and memories written directly by Claude land in the same directory (defaulting to uncategorized until given a `topic`) | Incompatible: official docs define no subdirectories, nested files may be ignored, and Claude's own writes still land at the root unless native auto-memory is disabled | Compatible, plus physical isolation: native root scanning sees core memories while naturally skipping `pitfalls/` |
| `MEMORY.md` index | `write_index()` emits `### <Topic>` sections and skips `pitfall`; `memory_block(worker=True)` appends pitfalls for worker briefs | Links become `topic/slug.md` and must be rewritten whenever a topic changes | Same as Option A |
| `remember / recall / forget` UX | Simplest: `<slug>` stays globally unique without directory prefixes; changing topic edits frontmatter without moving files or `.history/` | Re-categorizing moves files; lookup must recurse while excluding `candidates/` and `.history/` | `<slug>` stays unique across two known dirs; `--type pitfall` routes automatically to `pitfalls/` |
| Browsing in Finder / shell | Flat `.md` list | Mirrors UI folder tree | Separates core memories from pitfalls on disk |

**Verdict: prefer Option A (Option C is also viable); avoid Option B.** Project memories number in the dozens rather than thousands, and their primary consumers are `pm.py` and coding agents' auto-memory loaders. A flat `topic` frontmatter field delivers the exact same collapsible UI tree, counts, timestamps, and dimmed styling as physical folders while keeping `recall <slug>` prefix-free, preserving links across topic edits, and remaining 100% compatible with Claude Code's flat loader.

Companion changes:

1. **Add `topic` to frontmatter**: controlled enum `architecture / ui / workflow / ops / reference / pitfalls`. Defaults to `pitfalls` when `type == pitfall` and `reference` when `type == reference`; otherwise inferred lightly from keywords or set to `general` until categorized in the UI.
2. **Section `MEMORY.md` and split by audience**:
   - `write_index()` emits `### <Topic>` sections and omits `pitfall` from project `MEMORY.md`, shrinking the manager's preloaded index by ~30%;
   - `cmd_handover()` skips re-printing `MEMORY.md` when the manager agent already loads it natively, printing only the directory path and pending candidate count;
   - `memory_block(worker=True)` appends the `Engineering pitfalls` section for workers.
3. **Strengthen `remember` deduplication and brief guidance**: update the worker brief template to recommend `--type pitfall --verified "<how verified>"`, and normalize slugs (stripping hyphens/underscores) inside `alike()` alongside description similarity to catch near-identical filenames.
4. **Support group queries in `recall`**: `pm.py recall --topic ui` and `pm.py recall --type pitfall` so agents can fetch a full category if `MEMORY.md` ever outgrows its preload cap.

### 4.4 Audit of Existing Memories (Summary Statistics)

Reviewing every project memory in dudu's ledger at the time identified four cleanable categories (all reversible via `.history/`):

- **Duplicates and heavy overlaps — 5 clusters (net reduction of 6 files)**: e.g., two entries for the same OSC 7501 format differing by one hyphen in slug; two workers independently logging the same subparser regex trap; one entry whose second half repeated another verbatim; an entry whose slug stated the opposite of its updated body; and one UI conclusion split across two files.
- **Stale entry contradicting a newer decision — 1 file**: an older lean-session entry whose second clause still mandated keeping 200k rotation after automatic compaction had replaced rotation (trim the superseded clause).
- **One-off task logs saved as permanent memories — 2 files**: operational notes already covered by standing rules (`forget` to archive).
- **Mislabeled pitfalls — 22 `verified` entries** (~20 after deduplication) to retag from `type: project` to `type: pitfall` + `topic: pitfalls`, plus 8 empty candidate directories to prune and 1 pending candidate to review.

### 4.5 Migration Steps

1. **Backend data model and allowlisted roots (`pm.py`, `pm_store.py`)**
   - Replace denylist directory scanning in `pm_store.py` with explicit allowlisted roots:
     - `Library` serves only `docs` (`projects/<slug>/docs/`, plus archived `decisions.md` at the bottom), `research` (research READMEs excluding screenshots/probes, extracting H1 titles and originating tasks), and `instructions` (`CLAUDE.md`, `AGENTS.md`, `.claude/coordination.md`);
     - `Memory` separately returns project memories, personal memories, and non-empty candidates, hiding `verify*`, `handover.md`, `MEMORY.md`, and empty directories.
   - Add `pitfall` type and `topic` field in `pm.py`; add normalized-slug matching to `alike()`; section `write_index()` by topic while omitting `pitfall` from manager `MEMORY.md`; include `pitfall` in `memory_block(worker=True)`; drop duplicate handover index printing; auto-prune empty candidate dirs.
2. **One-time store cleanup script** (preserving all valid user quotes and archiving prior versions in `.history/`): populate `topic`, retag empirical notes to `pitfall`, apply the merges/trims/archives from §4.4, remove stray backup files and empty candidate dirs, and migrate the remaining ~16 decisions out of `decisions.md`.
3. **Frontend `Memory` tab (`mods/pm-project`)**
   - Split the right-hand sidebar tabs into **Threads · Library · Memory**;
   - Render only docs, repo instructions, and research reports (with source-thread jump links) in `Library`;
   - Render the collapsible topic tree in `Memory`: 5 full-contrast topic folders plus dimmed, default-collapsed `Engineering pitfalls` and non-empty `Pending candidates`, followed by collapsible Personal Memory and updated type badges.
4. **In-panel editing and rule graduation**: enable edit, delete (`forget` with `.history/` recovery), topic reassignment, and file drop in `Library` (`docs`) and `Memory`, keeping research reports read-only; graduate path-bound invariants into `.claude/rules/`.

---

## 5. Open Design Options

### 5.1 On-Disk Storage for Topic Folders
- **A (recommended)**: flat `memory/<slug>.md` + frontmatter `topic`, rendered as a collapsible tree in UI and sectioned in `MEMORY.md`.
- **B (hybrid)**: flat core memories, with worker `pitfalls/` placed in a real subdirectory like Cursor's `internal/`.
- **C**: real subdirectories for every topic (requires disabling native root auto-memory scanning for the manager).
- Rationale: both A and B stay compatible with Claude Code's native loader, keep `recall <slug>` prefix-free, and avoid broken links when re-categorizing, while producing the exact same UI tree as C.

### 5.2 Fixed Topic Enum vs. Free-Form Topics
- **A (recommended)**: 6 fixed topic groups plus conditional `Pending candidates`; only users or explicit curation threads can rename/add groups, never workers autonomously.
- **B**: let any agent pass arbitrary `remember --topic <word>` strings.
- Rationale: existing memories fit cleanly into the 6 topics, whereas unconstrained agent naming quickly fragments into near-synonym folders.

### 5.3 Fixing Engineering Pitfalls Labeled as "Decision"
- **A (recommended)**: add `pitfall` as a 5th type, keeping `project` strictly for product/architecture/UI decisions and updating the worker brief template to `--type pitfall`.
- **B**: keep 4 types, rename the localized `project` badge back to generic "Project", and infer decisions vs. pitfalls from whether `--quote` is present.
- Rationale: because pitfalls route differently (workers only, dimmed & collapsed in UI), encoding `pitfall` directly in `type` makes backend routing, CLI filtering, and UI badges unambiguous.

### 5.4 Cleaning Up Existing Memories in One Pass
- **A (recommended)**: run the full §4.4 cleanup pass now, with every prior file version preserved automatically in `.history/`.
- **B**: backfill `topic` and `pitfall` tags first without merging duplicates or trimming stale entries.
- Rationale: leaving contradictory or inverted-slug entries active continues misleading subsequent managers and workers.

---

## 6. References

**Cursor Official**
- Cursor Docs — Projects: <https://cursor.com/docs/agent/projects>
- Cursor Help — Projects (`docs/` vs. `internal/`, User Store): <https://cursor.com/help/ai-features/projects>
- Cursor Blog — Projects: <https://cursor.com/blog/projects>
- Cursor Blog — Multiplayer Projects: <https://cursor.com/blog/projects-multiplayer>
- Cursor Cloud Agent API — Projects endpoints (reserved paths `inbox/`, `artifacts/`, `.cursor`): <https://cursor.com/docs/cloud-agent/api/endpoints>
- Cursor Docs — Rules (`.cursor/rules/*.mdc` and `AGENTS.md`): <https://cursor.com/docs/rules>

**Claude / Anthropic Official**
- Claude Code Docs — Claude Code Projects (beta): <https://code.claude.com/docs/en/claude-projects.md>
- Claude Code Docs — How Claude remembers your project (`CLAUDE.md`, `.claude/rules/`, `AGENTS.md`, Auto memory): <https://code.claude.com/docs/en/memory.md>
- Claude Articles — Projects, redesigned: <https://claude.com/resources/articles/projects-redesigned>
- Claude Code Docs — Claude Code Desktop: <https://code.claude.com/docs/en/desktop.md>
- Anthropic Research — Components of agent memory: <https://www.anthropic.com/research/components-of-agent-memory>
