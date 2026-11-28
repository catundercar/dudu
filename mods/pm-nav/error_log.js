// Persistent error log for Herdr mods (<ledgerHome>/cache/mod-errors.log).
// pm-dash's error_log.js is the source; pm-nav and pm-project carry identical copies
// (a mod cannot import another's code; model.test.mjs checks).

import { execPython } from './python.js';

export const DEFAULT_THROTTLE_MS = 60_000;
export const DEFAULT_MAX_LINES = 500;
export const DEFAULT_MAX_BYTES = 256 * 1024;
export const MAX_MESSAGE_LEN = 1000;
const MAX_QUEUE = 50;
const MAX_TRACKED_SOURCES = 64;

export function formatLocalTimestamp(dateOrMs = Date.now()) {
  const d = dateOrMs instanceof Date ? dateOrMs : new Date(dateOrMs);
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

export function normalizeErrorMessage(error, maxLen = MAX_MESSAGE_LEN) {
  if (error == null) return '';
  const raw = typeof error === 'string'
    ? error
    : (typeof error?.message === 'string' && error.message ? error.message : String(error));
  const clean = raw.replace(/\s+/g, ' ').trim();
  if (!clean) return '';
  return clean.length > maxLen ? clean.slice(0, Math.max(1, maxLen - 1)) + '…' : clean;
}

export function formatErrorLine({ at = Date.now(), mod = 'mod', source = 'unknown', message = '', suppressed = 0 }) {
  const repeat = suppressed > 0 ? `(repeated ${suppressed}x) ` : '';
  return `${formatLocalTimestamp(at)} [${mod}] [${source}] ${repeat}${message}`;
}

// Appends one or more lines to <ledgerHome>/cache/mod-errors.log with line & byte rotation,
// POSIX flock serialization across mods, and atomic temp-file replacement.
export const APPEND_MOD_ERROR_LOG = `
import json, os, sys, tempfile
from pathlib import Path

path = Path(sys.argv[1])
new_lines = json.loads(sys.argv[2])
max_lines = max(1, int(sys.argv[3]))
max_bytes = max(1024, int(sys.argv[4]))
if not isinstance(new_lines, list) or not new_lines:
    sys.exit(0)
new_lines = [str(line).replace('\\r', ' ').replace('\\n', ' ').strip() for line in new_lines if str(line).strip()]
if not new_lines:
    sys.exit(0)

path.parent.mkdir(parents=True, exist_ok=True)
lock_fd = None
try:
    try:
        import fcntl
        lock_fd = os.open(str(path.parent / '.mod-errors.lock'), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    except Exception:
        pass
    try:
        existing = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        existing = []
    lines = (existing + new_lines)[-max_lines:]
    total = sum(len(line.encode('utf-8')) + 1 for line in lines)
    while len(lines) > 1 and total > max_bytes:
        removed = lines.pop(0)
        total -= len(removed.encode('utf-8')) + 1
    fd, temporary = tempfile.mkstemp(prefix='.mod-errors-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write('\\n'.join(lines) + '\\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass
finally:
    if lock_fd is not None:
        try:
            os.close(lock_fd)
        except OSError:
            pass
`;

export function createErrorLogger({
  mod,
  exec,
  execPy = execPython,
  getLedgerHome,
  now = () => Date.now(),
  throttleMs = DEFAULT_THROTTLE_MS,
  maxLines = DEFAULT_MAX_LINES,
  maxBytes = DEFAULT_MAX_BYTES,
}) {
  const lastByKey = new Map();
  const lastKeyBySource = new Map();
  const queue = [];
  let inFlight = null;

  function enqueue(line) {
    if (queue.length >= MAX_QUEUE) queue.shift();
    queue.push(line);
  }

  function drain() {
    if (inFlight || !queue.length) return inFlight || Promise.resolve();
    inFlight = (async () => {
      try {
        while (queue.length) {
          const batch = queue.splice(0, queue.length);
          const base = String(getLedgerHome?.() || '').trim().replace(/[\\/]+$/, '');
          if (!base || typeof exec !== 'function') break;
          const logPath = `${base}/cache/mod-errors.log`;
          try {
            await execPy(
              exec,
              ['-c', APPEND_MOD_ERROR_LOG, logPath, JSON.stringify(batch), String(maxLines), String(maxBytes)],
              { timeout: 4000 },
            );
          } catch (_) {
            /* Logging failures must never affect the mod's main flow. */
          }
        }
      } finally {
        inFlight = null;
        if (queue.length) drain();
      }
    })();
    return inFlight;
  }

  function record(source, error) {
    try {
      const src = String(source || 'unknown').replace(/\s+/g, ' ').trim() || 'unknown';
      const message = normalizeErrorMessage(error);
      if (!message) return false;
      const stamp = Number(now()) || Date.now();
      const key = `${src}\0${message}`;
      const existing = lastByKey.get(key);
      if (existing && (stamp - existing.at) < throttleMs) {
        existing.suppressed += 1;
        existing.lastAt = stamp;
        lastKeyBySource.set(src, key);
        return false;
      }
      // If a different error on the same source had suppressed repeats, flush its count before switching.
      const prevKey = lastKeyBySource.get(src);
      if (prevKey && prevKey !== key) {
        const prevEntry = lastByKey.get(prevKey);
        if (prevEntry && prevEntry.suppressed > 0) {
          enqueue(formatErrorLine({
            at: prevEntry.lastAt || stamp,
            mod: mod || 'mod',
            source: src,
            message: prevEntry.message,
            suppressed: prevEntry.suppressed,
          }));
          prevEntry.suppressed = 0;
        }
      }
      const suppressed = existing ? existing.suppressed : 0;
      if (lastByKey.has(key)) lastByKey.delete(key);
      lastByKey.set(key, { message, at: stamp, lastAt: stamp, suppressed: 0 });
      lastKeyBySource.set(src, key);
      if (lastByKey.size > MAX_TRACKED_SOURCES) {
        const oldest = lastByKey.keys().next().value;
        lastByKey.delete(oldest);
      }
      enqueue(formatErrorLine({ at: stamp, mod: mod || 'mod', source: src, message, suppressed }));
      drain();
      return true;
    } catch (_) {
      return false;
    }
  }

  async function flush() {
    while (inFlight || queue.length) {
      await (inFlight || drain());
    }
  }

  return { record, flush };
}
