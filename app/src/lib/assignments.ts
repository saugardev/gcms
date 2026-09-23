import type { ComponentDetail } from "./api.ts";

export function ambiguityReasons(
  component: Pick<
    ComponentDetail["component"],
    "status" | "warnings" | "score_margin" | "close_candidate_groups" | "candidates"
  >,
  margin?: number,
) {
  if (component.status !== "ambiguous") return [];
  const reasons: string[] = [];
  if (component.warnings.includes("similar_candidate_scores")) {
    const count = component.close_candidate_groups;
    let reason = `${count && count > 1 ? count : "Several"} library matches have similar scores.`;
    if (margin !== undefined && Number.isFinite(margin) && margin >= 0)
      reason += ` They fall within the saved ambiguity margin of ${margin.toFixed(3)} from the leading score.`;
    if (component.score_margin != null && Number.isFinite(component.score_margin))
      reason += ` The top-two score gap is ${component.score_margin.toFixed(3)}.`;
    if (component.warnings.includes("additional_close_candidates_not_displayed"))
      reason += ` Only ${component.candidates.length} candidates are shown; more close matches exist.`;
    reasons.push(reason);
  }
  if (component.warnings.includes("conflicting_reference_identities"))
    reasons.push(
      "The leading library spectrum is linked to multiple chemical identities. Candidate 1 lists the conflicting names and CAS numbers.",
    );
  return reasons.length
    ? reasons
    : ["This result was saved as ambiguous, but no specific reason was recorded."];
}
