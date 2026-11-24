// pi coding agent extension for PM working-set compaction and post-compact ledger sync.
// Loaded via `pi -e .../pm_pi_compact.js` for PM sessions (`pm.py` keeps `.js`, as pi's
// extension loader loads `.ts`/`.js` files only).
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const DEFAULT_COMPACT_TOKENS = 220_000;
const PM_SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), "pm.py");
const PYTHON = process.platform === "win32" ? "python" : "python3";

export const FALLBACK_COMPACT_INSTRUCTIONS = [
  "Compact Instructions for PM Coordinator:",
  "1. Preserve ALL unrecorded verbal user constraints, temporary red lines, freeze windows, forbidden commands/scripts, and external action boundaries verbatim.",
  "2. Preserve rejected technical alternatives with exact failure reasons and measured numbers.",
  "3. Preserve cross-thread conditional promises and sequencing (e.g., after X merges, dispatch Y).",
  "4. Preserve user interaction/formatting preferences and exact step-by-step plans approved via short replies.",
  "5. Omit verbose logs and raw diffs; active task statuses and latest reports are refreshed from disk right after compaction.",
].join("\n");

export function compactThreshold(env = process.env) {
  const raw = Number(env.PM_PI_COMPACT_TOKENS || env.PM_COMPACT_TOKENS || "");
  return Number.isFinite(raw) && raw >= 50_000 ? Math.floor(raw) : DEFAULT_COMPACT_TOKENS;
}

export function readPreCompactInstructions(run = execFileSync) {
  try {
    const out = run(PYTHON, [PM_SCRIPT, "hook-pre-compact", "--print"], {
      encoding: "utf8",
      timeout: 5000,
    });
    const text = String(out || "").trim();
    if (text) return text;
  } catch (_) {
    // Fall back to embedded checklist if pm.py cannot be invoked.
  }
  return FALLBACK_COMPACT_INSTRUCTIONS;
}

export function readCompactSync(cwd, run = execFileSync) {
  try {
    const out = run(PYTHON, [PM_SCRIPT, "handover", "--compact", "--repo", cwd || process.cwd()], {
      encoding: "utf8",
      timeout: 8000,
    });
    return String(out || "").trim();
  } catch (_) {
    return "";
  }
}

export default function pmCompactExtension(pi, deps = {}) {
  const threshold = deps.threshold ?? compactThreshold();
  const run = deps.execFileSync ?? execFileSync;
  const customInstructions = deps.instructions ?? readPreCompactInstructions(run);
  let compacting = false;

  pi.on("agent_end", (_event, ctx) => {
    if (compacting || ctx?.hasPendingMessages?.()) return;
    const usage = ctx?.getContextUsage?.();
    if (!usage || typeof usage.tokens !== "number" || usage.tokens <= threshold) return;
    compacting = true;
    try {
      ctx.compact({
        customInstructions,
        onComplete: () => { compacting = false; },
        onError: () => { compacting = false; },
      });
    } catch (_) {
      compacting = false;
    }
  });

  pi.on("tool_call", (event, ctx) => {
    const name = String(event?.toolName || event?.name || "").trim();
    if (!["AskUserQuestion", "request_user_input", "ask_user", "ask_question"].includes(name)) return;
    const cwd = ctx?.cwd || process.cwd();
    return {
      block: true,
      reason: [
        `Do not call ${name} directly in a PM session: questions must appear as a question card in the project conversation.`,
        `Run \`${PYTHON} ${PM_SCRIPT} new "<short title>" --repo "${cwd}" --status blocked --note "<question>" --option "<recommended option>" --why "<reason>" --option "<other option>" --recommend\` (or \`update <task-id> --status blocked ...\` for an existing task), then end your turn.`,
      ].join("\n"),
    };
  });

  pi.on("session_compact", (_event, ctx) => {
    compacting = false;
    const snapshot = readCompactSync(ctx?.cwd || process.cwd(), run);
    if (!snapshot) return;
    pi.sendMessage(
      { customType: "pm-compact-sync", content: snapshot, display: false },
      { triggerTurn: false },
    );
  });
}
