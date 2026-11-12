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
