export function numberedLabel(terminal, label) {
  const id = terminal.address.split("/").pop();
  const name = label || terminal.name || terminal.template || terminal.title || terminal.program?.name || "";
  if (!name || name === terminal.address || name === id) return name || id;
  if (name.startsWith(id) && /^[\s·:：\-—]/u.test(name.slice(id.length))) return name;
  return `${id} · ${name}`;
}

// Extend the host list without inventing an agent status or a terminal.
export function includePMs(list, terminals, panes, spaces) {
  const result = [...list];
  const known = new Set(list.map(a => a.address));
  const locations = new Map();
  for (const space of spaces) {
    for (const tab of space.tabs) locations.set(tab.id, { space, tab });
  }
  for (const terminal of terminals) {
    const labels = terminal.labels ?? {};
    if (terminal.state !== "live" || !labels.pm || labels["pm.retired"] || known.has(terminal.address)) continue;
    const pane = panes.find(p => p.terminal === terminal.address);
    const slash = terminal.address.lastIndexOf("/");
    const prefix = slash < 0 ? "" : terminal.address.slice(0, slash + 1);
    const tabId = pane?.tab ?? (labels["herdr.tab"] ? prefix + labels["herdr.tab"] : null);
    const location = locations.get(tabId);
    if (!location) continue; // A disconnected/unmapped workspace must not get a phantom row.
    const { space, tab } = location;
    result.push({
      address: terminal.address, pane: pane?.pane ?? null,
      space: space.id, space_name: space.name,
      tab: tab.id, tab_index: tab.index, tab_name: tab.name,
      status: pane?.status ?? null, app: pane?.app ?? null,
      program: pane?.program ?? terminal.program,
      title: `PM-${labels.pm}`, pmFallback: true,
      seq: 0, pinned: Boolean(labels["herdr.pinned"]), focused: Boolean(pane?.focused),
    });
    known.add(terminal.address);
  }
  // Appending would split an existing space into two grouped headers.
  const order = new Map(spaces.map((space, index) => [space.id, index]));
  return result.sort((a, b) => (order.get(a.space) ?? Infinity) - (order.get(b.space) ?? Infinity)
    || a.tab_index - b.tab_index);
}
