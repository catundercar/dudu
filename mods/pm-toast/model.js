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
