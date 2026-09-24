import { test } from "node:test";
import assert from "node:assert/strict";
import { mergeReviews } from "./reviews.ts";
import { safeReturnTo } from "./auth-path.ts";

test("live review state survives stale snapshots and out-of-order events", () => {
  const initial = { component_id: "component-0001", version: 2, decisions: [] };
  const newer = { ...initial, version: 3 };
  const current = mergeReviews({}, [newer]);
  assert.equal(mergeReviews(current, [initial])[initial.component_id], newer);
  assert.equal(mergeReviews(current, [newer])[initial.component_id], newer);
  const other = { ...initial, component_id: "component-0002" };
  assert.equal(Object.keys(mergeReviews(current, [other])).length, 2);
});

test("login return paths cannot escape the app or target auth/API endpoints", () => {
  for (const target of ["//evil.test", "/\\evil.test", "/\n/evil.test", "https://evil.test", "/api/auth/logout", "/login", "/register?x=1", ["/", "//evil.test"], null, {}]) {
    assert.equal(safeReturnTo(target), "/");
  }
  assert.equal(safeReturnTo("/?analysis=abc&peak=component-0001"), "/?analysis=abc&peak=component-0001");
});
