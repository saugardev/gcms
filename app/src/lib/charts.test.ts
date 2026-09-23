import assert from "node:assert/strict";
import test from "node:test";
import { constrainRange, linePath, nearestIndex } from "./charts.ts";

test("selection and zoom stay within the acquisition", () => {
  assert.equal(nearestIndex([], 1), -1);
  assert.equal(nearestIndex([0, 1, 2, 4], 2.8), 2);
  assert.equal(nearestIndex([0, 1, 2, 4], -10), 0);
  assert.equal(nearestIndex([0, 1, 2, 4], 10), 3);
  assert.deepEqual(constrainRange([-5, 5], [0, 60]), [0, 10]);
  assert.deepEqual(constrainRange([55, 65], [0, 60]), [50, 60]);
  assert.deepEqual(constrainRange([5, 5], [0, 60]), [0, 60]);
  assert.equal(
    linePath([0, 1, 2], [0, 2, 0], [0, 2], 100, 100, 2),
    "M0.00,100.00L50.00,0.00L100.00,100.00",
  );
});
