// Herdr's own agent notice is titled "<program> finished" or "<program> needs you"
// and goes to the agent when clicked: action agent.focus {terminal}. Only
// "finished" is hidden: a worker that needs the person (a permission prompt, a
// question) tells nobody else, so that notice always shows.
const FINISHED_NOTICE = / finished$/;

// True only for Herdr's "finished" notice about a dispatched worker: a live terminal
// with a `task` label and a parent. Anything unclear shows the toast (fail open);
// dudu's own alerts (layout.select) and every other notify() pass through.
export function isWorkerNotice(notice, terminals) {
  const action = notice?.action;
  const address = action?.args?.terminal;
  if (action?.name !== 'agent.focus' || typeof address !== 'string' || !address) return false;
  if (!FINISHED_NOTICE.test(notice.title ?? '')) return false;
  const terminal = Array.isArray(terminals) ? terminals.find(t => t?.address === address) : null;
  return Boolean(terminal && terminal.state === 'live' && terminal.parent && terminal.labels?.task);
}
