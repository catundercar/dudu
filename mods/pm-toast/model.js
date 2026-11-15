// Herdr's own agent notices ("<program> finished", "<program> needs you") go to
// the agent when clicked: action agent.focus {terminal}. In the pm layout only
// the PM's notices show: an agent the PM dispatched reports to the PM, and the
// PM's own turn ending is what brings the person in.

// True for an agent notice about an agent the PM dispatched: its terminal has a
// `task` label, or its parent terminal has a non-empty `pm` label. Both notice
// kinds are hidden. Anything unclear shows the toast (fail open); the PM's own
// terminal, agents the person started and every other notify() pass through.
export function isWorkerNotice(notice, terminals) {
  const action = notice?.action;
  const address = action?.args?.terminal;
  if (action?.name !== 'agent.focus' || typeof address !== 'string' || !address) return false;
  if (!Array.isArray(terminals)) return false;
  const find = at => terminals.find(t => t?.address === at);
  const terminal = find(address);
  if (!terminal) return false;
  if (terminal.labels?.task) return true;
  return Boolean(terminal.parent && find(terminal.parent)?.labels?.pm);
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
  // A retired PM up the chain (labeled pm.retired by `pm.py rotate`, or a PM terminal that is not the
  // project's current one) is passed over: shown on its tab, the thread would invite talking to it.
  const retired = t => Boolean(t?.labels?.['pm.retired'] || (home && t?.labels?.pm && t.address !== home));
  const seen = new Set([address]);
  for (let up = byAddress.get(address)?.parent; up && !seen.has(up); up = byAddress.get(up)?.parent) {
    if (has.has(up) && !retired(byAddress.get(up))) return { focus: up, peek: address };
    seen.add(up);
  }
  return home && has.has(home) ? { focus: home, peek: address } : none;
}
