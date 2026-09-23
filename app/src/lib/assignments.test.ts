import assert from "node:assert/strict";
import test from "node:test";
import { ambiguityReasons } from "./assignments.ts";

test("ambiguity explanations use recorded causes, including hidden matches and missing evidence", () => {
  const component = {
    status: "ambiguous",
    warnings: ["similar_candidate_scores", "additional_close_candidates_not_displayed"],
    score_margin: 0.01472099277,
    close_candidate_groups: 5,
    candidates: [],
  };
  const [scores] = ambiguityReasons(component, 0.03);
  assert.match(scores, /5 library matches/);
  assert.match(scores, /margin of 0\.030/);
  assert.match(scores, /gap is 0\.015/);
  assert.match(scores, /more close matches exist/);
  const conflict = { ...component, warnings: ["conflicting_reference_identities"] };
  assert.match(ambiguityReasons(conflict, 0.03)[0], /multiple chemical identities/);
  assert.doesNotMatch(ambiguityReasons(conflict, 0.03)[0], /similar scores/);
  assert.equal(ambiguityReasons({ ...component, warnings: [...component.warnings, ...conflict.warnings] }).length, 2);
  assert.deepEqual(ambiguityReasons({ ...component, status: "unassigned" }, 0.03), []);
  assert.match(ambiguityReasons({ ...component, warnings: [] })[0], /no specific reason was recorded/);
  const [missing] = ambiguityReasons({ status: "ambiguous", warnings: ["similar_candidate_scores"], candidates: [] });
  assert.match(missing, /Several library matches/);
  assert.doesNotMatch(missing, /margin|gap|undefined|NaN/);
});
