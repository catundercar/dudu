// Herdr's own agent notices ("<program> finished", "<program> needs you") go to
// the agent when clicked: action agent.focus {terminal}. In the pm layout only
// the PM's notices show: an agent the PM dispatched reports to the PM, and the
// PM's own turn ending is what brings the person in.

// True for an agent notice about an agent the PM or a worker dispatched: its terminal
// has a `task` or `helper.of` label, or an ancestor up its `parent` chain is a PM
// (`pm`, or legacy `pm.retired` from an older peer's rotation), task worker (`task`),
// or helper (`helper.of`). Both notice kinds ("finished" and "needs you") are hidden.
// Anything unclear shows the toast (fail open); a PM's own terminal, agents the person
// started, and every other notify() pass through.
export function isWorkerNotice(notice, terminals) {
  const action = notice?.action;
  const address = action?.args?.terminal;
  if (action?.name !== 'agent.focus' || typeof address !== 'string' || !address) return false;
  if (!Array.isArray(terminals)) return false;
  const byAddress = new Map();
  for (const t of terminals) {
    if (t?.address) byAddress.set(t.address, t);
  }
  const terminal = byAddress.get(address);
  if (!terminal) return false;
  if (terminal.labels?.pm || terminal.labels?.['pm.retired']) return false;
  if (terminal.labels?.task || terminal.labels?.['helper.of']) return true;
  const seen = new Set([address]);
  for (let up = terminal.parent; up && !seen.has(up); up = byAddress.get(up)?.parent) {
    seen.add(up);
    const anc = byAddress.get(up);
    if (!anc) return false;
    if (anc.labels?.pm || anc.labels?.['pm.retired'] || anc.labels?.task || anc.labels?.['helper.of']) return true;
  }
  return false;
}

// Hides only agents dispatched by the PM or a worker (`isWorkerNotice`).
export function isHiddenNotice(notice, terminals) {
  return isWorkerNotice(notice, terminals);
}

// A copy of pm-dash/model.js's (a mod cannot import from another mod's folder); pm-dash's
// model.test.mjs checks that it stays identical.
// How a click brings a terminal up. One with a pane: pane.focus, which shows its own space and tab.
// A sub-agent without a pane (Herdr's agents list peeks those) is peeked over the tab of the nearest
// terminal up its parent chain that has a pane and is not a retired PM, else over its project's current
// PM (`home`): a worker that outlived a PM rotated out (closed, or still open but retired). With neither, nothing: no pane is focused and the work
// column is not shown, since that would reveal whatever space was active — another project's.
// agent.focus is not used: on a paneless terminal it changes no tab (t5h opened OldName).
// `paned`: the addresses that have a pane (panes()' terminals, agents()' addresses).
export function focusPlan(address, terms, paned, home = '') {
  const none = { focus: '', peek: '' };
  if (!address) return none;
  const has = new Set(paned.filter(Boolean));
  if (has.has(address)) return { focus: address, peek: '' };
  const byAddress = new Map(terms.map(t => [t.address, t]));
  // Another PM terminal up the chain (`home` is the project's current PM) is passed over:
  // shown on its tab, the thread would invite talking to the wrong PM.
  const otherPm = t => Boolean(home && t?.labels?.pm && t.address !== home);
  const seen = new Set([address]);
  for (let up = byAddress.get(address)?.parent; up && !seen.has(up); up = byAddress.get(up)?.parent) {
    if (has.has(up) && !otherPm(byAddress.get(up))) return { focus: up, peek: address };
    seen.add(up);
  }
  return home && has.has(home) ? { focus: home, peek: address } : none;
}
