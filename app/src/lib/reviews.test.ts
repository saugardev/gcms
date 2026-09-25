import { test } from "node:test";
import assert from "node:assert/strict";
import { acceptedComponents, mergeReviews, type ComponentReview } from "./reviews.ts";
import type { Peak } from "./api.ts";
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

test("accepted components use analyst choices, stay sample-scoped and reflect changed decisions", () => {
  const peak = (id: string, time: number): Peak => ({ component_id: id, apex_seconds: time, start_seconds: time - 1,
    end_seconds: time + 1, area_percent: 2, status: "tentative", name: "Leading match", score: .9, stability: null, search_text: "" });
  const peaks = [peak("component-0001", 50), peak("component-0002", 20), peak("component-0003", 30)];
  const review = (id: string, decision: "accepted" | "rejected"): ComponentReview => ({ component_id: id, version: 1,
    decisions: [{ group_id: "second-candidate", candidate_name: "Analyst choice", decision,
      updated_by: { id: "reviewer", name: "Reviewer" }, updated_at: "2026-09-25T10:00:00Z" }] });
  const reviews = Object.fromEntries([review("component-0001", "accepted"), review("component-0002", "accepted"),
    review("component-0003", "rejected"), review("component-9999", "accepted")].map((r) => [r.component_id, r]));
  const accepted = acceptedComponents(peaks, reviews);
  assert.deepEqual(accepted.map(({ peak }) => peak.component_id), ["component-0002", "component-0001"]);
  assert.equal(accepted[0].decision.candidate_name, "Analyst choice");
  assert.equal(accepted[0].decision.group_id, "second-candidate");
  const changed = mergeReviews(reviews, [{ ...review("component-0002", "rejected"), version: 2 }]);
  assert.deepEqual(acceptedComponents(peaks, changed).map(({ peak }) => peak.component_id), ["component-0001"]);
  assert.deepEqual(acceptedComponents([], reviews), []);
});
