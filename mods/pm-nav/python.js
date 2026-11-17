// Which Python runs the PM scripts. pm-dash's python.js is the source; pm-nav, pm-list and
// pm-project carry identical copies (a mod cannot import another's code; model.test.mjs checks).
//
// Tried in order: python3 (macOS, Linux), py -3 (the Windows launcher), python. Each is asked to
// run a line of Python; the first that does, at 3.8 or newer, wins. Windows' python/python3 stubs
// (app execution aliases under %LOCALAPPDATA%\Microsoft\WindowsApps that only point at the
// Microsoft Store) print a Store link and exit 9009 without running anything, so they fail the
// probe. A Python installed from the Store also lives under WindowsApps but runs the probe, so it
// is kept: the probe decides, not the path.

export const PYTHON_CANDIDATES = [['python3'], ['py', '-3'], ['python']];
export const MIN_PYTHON = [3, 8];
export const PYTHON_PROBE = 'import sys; print("pm-python", sys.version_info[0], sys.version_info[1], sys.executable)';
// The message a caller shows (or tests for) when no candidate runs Python.
export const NO_PYTHON = 'no-python';

// The probe's answer as {version, executable}, or null when it is not one.
export function probeAnswer(result) {
  if (!result || result.code !== 0) return null;
  const m = /^pm-python (\d+) (\d+) (.*)$/m.exec(String(result.stdout || ''));
  return m ? { version: [Number(m[1]), Number(m[2])], executable: m[3].trim() } : null;
}

export const recentEnough = ([major, minor], [needMajor, needMinor] = MIN_PYTHON) =>
  major > needMajor || (major === needMajor && minor >= needMinor);

// run(command, args) is herdr's exec: a result, or a rejection when the program cannot start.
// Resolves to {command, args, version, executable}, or null when nothing runs Python 3.8+.
export async function findPython(run, candidates = PYTHON_CANDIDATES) {
  for (const [command, ...args] of candidates) {
    let answer = null;
    try { answer = probeAnswer(await run(command, [...args, '-c', PYTHON_PROBE], { timeout: 10000 })); }
    catch (_) { /* Not installed: the next one. */ }
    if (answer && recentEnough(answer.version)) return { command, args, ...answer };
  }
  return null;
}

// One answer per mod while it is found; a miss is asked again next time (Herdr restarted with a
// new PATH, or the person clicked Set up again).
let found = null;
export function python(run) {
  if (!found) found = findPython(run).then(py => { if (!py) found = null; return py; });
  return found;
}
export function forgetPython() { found = null; }

// exec(<python>, args, options) with the Python found; rejects with Error(NO_PYTHON) when there is none.
export async function execPython(run, args, options) {
  const py = await python(run);
  if (!py) throw new Error(NO_PYTHON);
  return run(py.command, [...py.args, ...args], options);
}
