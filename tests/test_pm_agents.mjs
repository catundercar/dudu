import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { test } from "node:test";
const source = readFileSync(new URL("../mods/pm-agents/model.js", import.meta.url), "utf8");
const { includePMs } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const spaces = [{ id: "dev/s1", name: "project", tabs: [{ id: "dev/b1", index: 1, name: "PM" }] }];
const pm = { address: "dev/t3", state: "live", labels: { pm: "project", "herdr.tab": "b1" } };
const pane = { terminal: "dev/t3", pane: "dev/p1", tab: "dev/b1", focused: true, status: null };
test("remote PM without status gets one clickable row, not an idle/working claim", () => {
  const [row] = includePMs([], [pm], [pane], spaces);
  assert.equal(row.address, pm.address);
  assert.equal(row.pane, "dev/p1");
  assert.equal(row.space, "dev/s1");
  assert.equal(row.title, "PM-project");
  assert.equal(row.status, null);
  assert.equal(row.focused, true);
});
test("native status reporting replaces fallback without duplicates", () => {
  const native = { address: pm.address, space: "dev/s1", tab_index: 1, status: "working" };
  assert.deepEqual(includePMs([native], [pm], [pane], spaces), [native]);
});
test("dead, retired, unlabelled and unmapped PMs are excluded", () => {
  for (const item of [
    { ...pm, state: "exited" }, { ...pm, labels: { ...pm.labels, "pm.retired": "project" } },
    { ...pm, labels: {} }, { ...pm, labels: { pm: "project", "herdr.tab": "gone" } },
  ]) assert.deepEqual(includePMs([], [item], [], spaces), []);
});
test("parked PM keeps address and null pane for peek; duplicate snapshots deduplicate", () => {
  const rows = includePMs([], [pm, pm], [], spaces);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].pane, null);
});
test("local terminals resolve without a remote prefix", () => {
  const [row] = includePMs([], [{ ...pm, address: "t3" }], [], [
    { id: "s1", name: "local", tabs: [{ id: "b1", index: 1 }] },
  ]);
  assert.equal(row.space, "s1");
});
test("fallback remains adjacent to its space in grouped mode", () => {
  const list = [
    { address: "dev/t4", space: "dev/s1", tab_index: 2 },
    { address: "t5", space: "s2", tab_index: 1 },
  ];
  const rows = includePMs(list, [pm], [], [...spaces, { id: "s2", name: "other", tabs: [] }]);
  assert.deepEqual(rows.map(a => a.address), ["dev/t3", "dev/t4", "t5"]);
  assert.equal(list.length, 2);
});
test("label-only PM does not swallow existing numbered agent rows into its tree", () => {
  const viewSource = readFileSync(new URL("../mods/pm-agents/main.js", import.meta.url), "utf8")
    .replace(/^import .*;$/gm, "").replace("export default class Agents", "class Agents");
  const Agents = new Function("View", `${viewSource}; return Agents;`)(class {});
  const view = new Agents();
  const worker = { address: "dev/t62", parent: pm.address, state: "live" };
  const fallback = { address: pm.address, pmFallback: true };
  assert.deepEqual(view.children([worker], fallback), []);
  assert.equal(view.children([worker], { address: pm.address })[0].t.address, worker.address);
  // Every render path (hiding, ranking, drawing) must use the same safe child list.
  assert.equal((viewSource.match(/this\.children\(all, a\)/g) ?? []).length, 3);
  assert.equal(viewSource.includes("this.tree(all, a.address)"), false);
});
test("render preserves a named worker tab even when fallback PM shares that tab", () => {
  const viewSource = readFileSync(new URL("../mods/pm-agents/main.js", import.meta.url), "utf8")
    .replace(/^import .*;$/gm, "").replace("export default class Agents", "class Agents");
  const texts = [];
  const element = () => {
    const proxy = new Proxy({}, { get: (_, key) => (...args) => {
      if (key === "child" && typeof args[0] === "string") texts.push(args[0]);
      if (key === "when" && args[0]) args[1](proxy);
      return proxy;
    } });
    return proxy;
  };
  const program = { name: "Claude", key: "claude", agent: true };
  const worker = { address: "dev/t62", pane: "dev/p62", tab: "dev/b1", tab_index: 1,
    space: "dev/s1", space_name: "project", title: "Implement feature", program, status: "idle" };
  const bindings = {
    View: class {}, includePMs, agents: () => [worker],
    terminals: () => [pm, { address: worker.address, parent: pm.address, state: "live" }],
    panes: () => [{ ...worker, terminal: worker.address }, pane],
    spaces: () => [{ ...spaces[0], tabs: [{ id: "dev/b1", index: 1, name: "t62", named: true }] }],
    theme: () => ({}), props: () => ({}), focused: () => ({}),
    shared: () => "grouped", setAgentOrder: () => {}, layout: () => null,
    localStorage: { setItem() {} },
    div: element, h_flex: element, v_flex: element, svg: element, image: element,
  };
  const Agents = new Function(...Object.keys(bindings), `${viewSource}; return Agents;`)(...Object.values(bindings));
  const view = new Agents();
  Object.assign(view, { changed: {}, pendingPins: [], migratingPins: new Set(), folded: new Set() });
  view.render({});
  assert.ok(texts.includes("t62"));
  assert.ok(texts.includes("PM-project"));
  assert.ok(!texts.includes("Implement feature"));
});
