import assert from "node:assert/strict";
import test from "node:test";
import {
  emptySelection,
  selectAll,
  selectComponent,
  selectRange,
  selectionFromRoute,
} from "./selection.ts";

test("desktop selection follows the visible order and keeps an active selected component", () => {
  const order = ["a", "b", "c", "d"];
  const single = selectComponent(emptySelection, "b", order);
  assert.deepEqual(selectAll(single, order), {
    ids: order,
    active: "b",
    anchor: "b",
  });
  assert.deepEqual(selectAll(single, []), emptySelection);
  const range = selectComponent(single, "d", order, { range: true });
  assert.deepEqual(range, { ids: ["b", "c", "d"], active: "d", anchor: "b" });
  assert.deepEqual(selectComponent(range, "a", order, { range: true }).ids, [
    "a",
    "b",
  ]);
  const toggled = selectComponent(range, "d", order, { toggle: true });
  assert.deepEqual(toggled.ids, ["b", "c"]);
  assert.equal(toggled.active, "c");
  assert.deepEqual(
    selectComponent(single, "b", order, { toggle: true }).ids,
    [],
  );
  assert.equal(
    selectComponent(single, "b", order, { toggle: true }).active,
    "",
  );
  assert.deepEqual(
    selectComponent(single, "d", ["d", "a"], { range: true }).ids,
    ["d"],
  );
  assert.deepEqual(
    selectComponent(single, "a", ["d", "c", "b", "a"], { range: true }).ids,
    ["b", "a"],
  );
  assert.equal(selectComponent(single, "missing", order), single);
  assert.deepEqual(selectRange(single, ["c", "d"], true).ids, ["b", "c", "d"]);
  assert.deepEqual(selectRange(single, []), emptySelection);
  assert.deepEqual(selectRange(single, ["a", "b"], true).ids, ["b", "a"]);
});

test("page navigation preserves selection while component links select their destination", () => {
  const order = ["a", "b", "c"];
  const multiple = selectRange(emptySelection, ["a", "b"]);
  assert.equal(selectionFromRoute(multiple, "b", order), multiple);
  assert.equal(selectionFromRoute(multiple, null, order), multiple);
  assert.equal(selectionFromRoute(multiple, "missing", order), multiple);
  assert.deepEqual(selectionFromRoute(multiple, "c", order), {
    ids: ["c"], active: "c", anchor: "c",
  });
});
