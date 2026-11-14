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
