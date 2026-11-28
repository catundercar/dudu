# Board Token Analytics: Multi-Runtime Schema, Incremental Rollups & Flat-Fill UI

## Goal

Surface multi-dimensional token analytics directly inside dudu's **Board** (`mods/pm-dash`) across supported coding agent runtimes (`Claude Code`, `agy`, `Codex`, `pi`), without slowing down `pm.py state` refreshes or shrinking the live PM-to-Task topology graph (`fitBoard`).

---

## 1. Observable Local Transcript Token Schemas

Each runtime writes append-only JSONL session logs under the user's home directory with distinct token accounting rules:

| Field / Semantics | Claude Code (`~/.claude/projects`) | agy (`~/.gemini/antigravity-cli`) | Codex (`~/.codex/sessions`) | pi (`~/.pi/agent/sessions`) |
| :--- | :--- | :--- | :--- | :--- |
| **Session files** | `<folder>/<sid>.jsonl` + `<sid>/subagents/agent-*.jsonl` | `brain/<cid>/.system_generated/logs/transcript.jsonl` + `conversation_summaries.db` | `YYYY/MM/DD/rollout-<ts>-<sid>.jsonl` | `--<cwd>--/<ts>_<sid>.jsonl` |
| **Usage event row** | `type == "assistant"` with `message.usage` | `type == "PLANNER_RESPONSE"` (`status == "DONE"`) | `type == "token_usage_record"` (fallback: `event_msg` `token_count`) | `type == "message"`, `message.role == "assistant"` |
| **Deduplication key** | `message.id \|\| requestId` (multi-block turns emit several rows with identical `usage`) | `step_index` | `payload.response_id` (avoids duplicate `token_count` snapshots) | row index / `id` |
| **Uncached `input`** | `usage.input_tokens` (excludes cache) | `input_tokens` (excludes `cache_read_tokens`) | `max(0, input_tokens - cached_input_tokens - cache_write_input_tokens)` (`input_tokens` includes cached) | `usage.input` (excludes cache) |
| **`output` (incl. reasoning)** | `usage.output_tokens` (includes `thinking_tokens`) | `output_tokens` | `output_tokens` (`last_usage_includes_reasoning: true`) | `usage.output` |
| **`cache_read`** | `usage.cache_read_input_tokens` | `cache_read_tokens` | `cached_input_tokens` | `usage.cacheRead` |
| **`cache_write`** | `usage.cache_creation_input_tokens` (`ephemeral_5m` / `ephemeral_1h`) | Not emitted (`0`) | `cache_write_input_tokens` | `usage.cacheWrite` |
| **`model` & Advisor split** | Unroll `usage.iterations` when non-empty so `advisor_message` calls (`iter.model`) are attributed separately from `message.model` | `model` | Latest `turn_context.payload.model` | `message.model` (`message.provider`) |
| **Errors** | `type == "system"`, `subtype in ("api_error", "error")` | `type == "ERROR_MESSAGE"` | `event_msg` `error` / `stream_error` | `bool(message.errorMessage)` |
| **Cost (USD)** | Estimated from model list-price table | Estimated from model list-price table | Estimated from model list-price table | `usage.cost.total` when > 0, else price table |

### Dimensions Available vs. Estimated vs. Omitted

- **Exact from local transcripts**: uncached input, output, cache read, cache write (except `agy`, where cache write is absent), model ID (including Fable advisor split), UTC timestamp (bucketed in local timezone), request count, API error count, and project / thread (`#N`) / role (`PM`, `Worker`, `Reviewer`, `Helper`, `Subagent`) attribution.
- **Estimated**: USD API-equivalent cost and prompt-cache savings (`cache_read * (input_rate - cache_read_rate)`), calculated at query time from a configurable `token_pricing` table in `config.json` with built-in defaults (clearly labeled as API list-rate equivalent since subscription plans are not billed per call).
- **Omitted (not persisted in local transcripts)**: streaming throughput (`tok/s`) and time-to-first-token (`TTFT`). Instead, breakdown rows surface harness-native dimensions (`Worker` coding vs. `Review` split, thread number jump, cache hit rate).

---

## 2. Incremental Byte-Offset Rollup Cache

Cold-scanning >1 GB of historical JSONL transcripts takes ~2.5–3.0s in Python, so token aggregation is decoupled from `pm.py state`:

1. **Dedicated read model (`pm.py tokens`)**:
   - `mods/pm-dash` paints immediately (`0 ms`) from `~/.dudu/cache/token-analytics.json` via `readTextFile`, then refreshes asynchronously via `execPython(..., ['pm.py', 'tokens'])` on Board open, manual refresh click, and a `30s` visible-only timer.
   - A single `pm.py tokens` response (~25 KB JSON) includes pre-sliced views for `today` (24 hourly buckets), `7d`, `30d`, and `all` (daily buckets), making UI switches across time windows, metrics (`Tokens / Cost / Requests`), and dimensions (`Model / Thread / Agent`) instant in memory (`0 ms`).
2. **Append-only cursor + hourly rollup SQLite cache (`~/.dudu/cache/token-usage-v1.db`, WAL)**:
   - `files(path PRIMARY KEY, agent, ino, size, mtime_ns, byte_offset, cwd, sid, opening_role, opening_task_hint, last_model, tail_seen_ids_json)`
   - `hourly_rollups(path, hour_epoch, model, calls, errors, input_tok, output_tok, cache_read_tok, cache_write_5m_tok, cache_write_1h_tok, explicit_usd, PRIMARY KEY (path, hour_epoch, model))`
   - Directory pruning restricts scans to `in_scope(cwd, repo_or_worktrees)` folders (excluding `/tmp` test scratchpads).
   - Unchanged `(ino, size, mtime_ns)` files read `0` bytes; appended files `seek(byte_offset)` and parse only newly completed `\n`-terminated lines (<8 ms warm tick).
   - Thread attribution joins `files` against live `tasks/*.json` (`session.id`, `prior_sessions`, `worktree`, `review_of`) at query time, folding `*-review` threads into their parent task without rescanning transcripts.

---

## 3. Board Placement, Interaction & `gpui-kit` Mapping

### Two-Point Layout Preserving `fitBoard` Scale

1. **Header Pulse Pill** (top-right summary row, beside `Running | Review | Blocked`):
   - `50px` flat-fill `bg(t.surface)` pill (`rounded(12)`, no border) displaying today's total tokens, estimated API cost, and cache hit percentage. Clicking scrolls to or expands the analytics shelf.
2. **Collapsible Analytics Shelf** (inside `#scroll` below the topology stage + `Recent activity`):
   - Excluded from `fitBoard`'s `fixedHeight` (same rule as opened `Ended N` lists) so expanding the shelf never shrinks `g.scale` of the PM-to-Task graph.
   - **Collapsed state (`44px`)**: quiet `bg(t.surface)` single-line bar with summary stats, 12-hour mini spark-bars, and expand chevron.
   - **Expanded state**:
     - Control bar: time range (`Today / 7d / 30d / All`), agent filter (`All Agents`), icon-only refresh & collapse controls (`actions-as-icons`).
     - 4 flat-fill KPI cards (`bg(t.surface)`, `rounded(13)`, no 1px borders): **Total Tokens** (with prompt/cache micro-bar), **Requests & Threads**, **Est. API Cost** (with cache-savings badge), and **Cache Hit Rate** (with gauge bar).
     - Responsive body (`h_flex` at `>= 1100px`, `v_flex` below): left **Stacked Time-Series Bar Chart** (`Tokens | Cost | Requests` + `Popup` hover card per bar) and right **Grouped Progress Breakdown** (`Model | Thread | Agent`, where `Thread` folds worker + reviewer usage into dual-segment bars and clicks through to open the thread).
   - Pressing `Esc` folds an open hover card or shelf one step (`esc-goes-back-one-level`).
   - All labels ship in both `STRINGS.en` and `STRINGS.zh`, switching live with `config.json` `lang`.
