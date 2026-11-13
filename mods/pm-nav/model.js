// Compare navigation identities, not cwd: a shell changing directory is not
// sidebar navigation. Keep remote machine prefixes intact.
export function focusKey(focus) {
  return JSON.stringify(['space', 'tab', 'pane', 'terminal', 'shown', 'agent'].map(key => focus?.[key] ?? null));
}

export function shouldReturnToWork(shown, wasShown, focus, previousFocus) {
  return shown && wasShown && focus !== previousFocus;
}

// The same task statuses used by the dashboard's ledger summary.
export function summary(local, remote = {}) {
  const states = [local, ...Object.values(remote)].filter(state =>
    state && Array.isArray(state.pms) && Array.isArray(state.tasks));
  const pms = states.flatMap(state => state.pms), tasks = states.flatMap(state => state.tasks);
  return {
    projects: pms.length,
    active: tasks.filter(task => task.status === 'in_progress').length,
    blocked: tasks.filter(task => task.status === 'blocked').length,
  };
}

// Half an em per Latin character, one em per wide CJK character. The kit
// exposes layout sizes, but no text measurement or whole-child overflow hiding.
export function estimateTextWidth(text, fontSize = 11.5) {
  return Array.from(text).reduce((width, char) => width +
    (/[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe10-\ufe6f\uff01-\uff60\uffe0-\uffe6\u{20000}-\u{3ffff}]/u.test(char) ? 2 : 1), 0) * fontSize / 2;
}

// Width is the summary's budget after row padding, title, gap and error marker.
// Select whole phrases; leave a small allowance for proportional-font variance.
export function fitSummary(counts, lang, width) {
  const { projects, active, blocked } = counts, zh = lang === 'zh';
  const projectText = zh ? `${projects} 项目` : `${projects} ${projects === 1 ? 'project' : 'projects'}`;
  const activeText = zh ? `${active} 进行中` : `${active} active`;
  const blockedText = blocked ? (zh ? `${blocked} 阻塞` : `${blocked} blocked`) : '';
  const fullText = `${projectText} · ${activeText}`;
  const detail = `${fullText}${blockedText ? ` · ${blockedText}` : ''}`;
  const primary = blockedText || activeText;
  for (const text of [fullText, activeText, blockedText ? '' : activeText]) {
    const red = `${text && blockedText ? ' · ' : ''}${blockedText}`;
    if (estimateTextWidth(text + red) + 4 <= width || (text || red) === primary) {
      return { text, blocked: red, detail, minimumWidth: estimateTextWidth(primary) + 4 };
    }
  }
}

// Copies of pm-dash/model.js (a mod cannot import from another mod's folder);
// model.test.mjs checks that both stay identical.
export const LEDGER_HOME_SH = 'if [ -n "$PM_HOME" ]; then printf %s "$PM_HOME"; ' +
  'elif [ -d "$HOME/.claude/pm" ]; then printf %s "$HOME/.claude/pm"; else printf %s "$HOME/.dudu"; fi';
export const PM_SCRIPTS = ['.config/herdr-app/mods/pm-dash/skill/scripts/pm.py', '.claude/skills/pm/scripts/pm.py',
  '.codex/skills/pm/scripts/pm.py', '.pi/agent/skills/pm/scripts/pm.py'];
export function remoteStateCommand(scripts = PM_SCRIPTS) {
  return `for f in ${scripts.map(path => `"$HOME/${path}"`).join(' ')}; do ` +
    'if [ -f "$f" ]; then exec python3 "$f" state; fi; done; echo "pm.py not found" >&2; exit 127';
}

// writeTextFile documents atomic replacement of existing files, but not parent
// creation or atomic first creation. Rename a sibling temp file in both cases.
export const WRITE_REMOTE_CACHE = `
import json, os, sys, tempfile
from pathlib import Path
path = Path(sys.argv[1])
states = json.loads(sys.argv[2])
at = int(sys.argv[3])
try:
    old = json.loads(path.read_text(encoding='utf-8'))
except (OSError, ValueError):
    old = None
if (isinstance(old, dict) and type(old.get('at')) in (int, float)
        and 0 <= old['at'] <= at and old.get('states') == states):
    sys.exit(0)
path.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix='.remote-states-', dir=path.parent)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump({'at': at, 'states': states}, output, ensure_ascii=False)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
`;

// Copies of pm-dash's reviewWaiting / blockedWaiting (model.test.mjs keeps them equal).
export const ALERT_STRINGS = {
  en: { review: 'Review · Waiting for you', blocked: 'Blocked · Waiting for you',
    more: n => `${n} more ${n === 1 ? 'item' : 'items'} waiting for you` },
  zh: { review: '待审 · 等你', blocked: '阻塞 · 等你', more: n => `还有 ${n} 件事等你` },
};
const WAITING = ['review', 'blocked'];
export const ALERT_LIMIT = 3;
export const BOARD_ACTION = { name: 'layout.select', args: { stack: 'pm-stage', child: 'pm-board' } };

// `seen` maps a source ('' for this computer, else the machine name) to the
// waiting tasks of its last read, {id: status}. A source's first read is the
// baseline; afterwards a task alerts each time it enters review or blocked
// from anything else (moving between the two is still the same wait).
export function enteredWaiting(seen, source, state) {
  const before = seen?.[source], now = {}, entered = [];
  for (const task of Array.isArray(state?.tasks) ? state.tasks : []) {
    if (!task?.id || !WAITING.includes(task.status) || now[task.id]) continue;
    now[task.id] = task.status;
    if (before && !before[task.id]) entered.push({ ...task, machine: source });
  }
  return { seen: { ...seen, [source]: now }, entered };
}

// One notification per task, at most ALERT_LIMIT, then one line for the rest;
// one sound for the lot ("blocked" if any task is blocked).
export function alertNotices(entered, lang, limit = ALERT_LIMIT) {
  const words = ALERT_STRINGS[lang === 'zh' ? 'zh' : 'en'];
  const level = tasks => tasks.some(t => t.status === 'blocked') ? 'error' : 'info';
  const notices = entered.slice(0, limit).map(task => ({
    title: task.title || task.id, body: [task.project, words[task.status]].filter(Boolean).join(' · '),
    level: level([task]), action: BOARD_ACTION }));
  const rest = entered.slice(limit);
  if (rest.length) notices.push({ title: words.more(rest.length), level: level(rest), action: BOARD_ACTION });
  return { notices, sound: entered.length ? (level(entered) === 'error' ? 'blocked' : 'done') : null };
}
