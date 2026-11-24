// pi coding agent extension for PM working-set compaction and post-compact ledger sync.
// Loaded via `pi -e .../pm_pi_compact.js` for PM sessions (`pm.py` keeps `.js`, as pi's
// extension loader loads `.ts`/`.js` files only).
import { execFileSync, spawn } from "node:child_process";
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

export function extractPiAssistantReply(event) {
  if (!event || typeof event !== "object") return "";
  if (typeof event.last_assistant_message === "string" && event.last_assistant_message.trim()) {
    return event.last_assistant_message.trim();
  }
  const messages = Array.isArray(event.messages) ? event.messages : [];
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (!m || m.role !== "assistant") continue;
    if (typeof m.content === "string" && m.content.trim()) return m.content.trim();
    if (Array.isArray(m.content)) {
      const parts = m.content
        .filter(b => b && b.type === "text" && typeof b.text === "string" && b.text.trim())
        .map(b => b.text.trim());
      if (parts.length) return parts.join("\n\n");
    }
  }
  return "";
}

export function emitPiTurnHook(payload, spawnFn = spawn) {
  try {
    const child = spawnFn(PYTHON, [PM_SCRIPT, "hook-turn"], {
      stdio: ["pipe", "ignore", "ignore"],
      detached: true,
    });
    if (child?.stdin) {
      child.stdin.on?.("error", () => {});
      child.stdin.end(JSON.stringify(payload));
    }
    child?.unref?.();
  } catch (_) {
    // Hook sync is best-effort and never interrupts pi.
  }
}

export default function pmCompactExtension(pi, deps = {}) {
  const threshold = deps.threshold ?? compactThreshold();
  const run = deps.execFileSync ?? execFileSync;
  const spawnHook = deps.spawnHook ?? (deps.execFileSync ? null : spawn);
  const customInstructions = deps.instructions ?? readPreCompactInstructions(run);
  let compacting = false;

  pi.on("agent_end", (event, ctx) => {
    if (spawnHook) {
      const reply = extractPiAssistantReply(event);
      emitPiTurnHook(
        { hook_event_name: "Stop", cwd: ctx?.cwd || process.cwd(), last_assistant_message: reply },
        spawnHook,
      );
    }
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
