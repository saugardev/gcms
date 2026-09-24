export type Decision = "accepted" | "rejected" | "unreviewed";
export type CandidateDecision = {
  group_id: string; candidate_name: string; decision: Decision;
  updated_by: { id: string; name: string }; updated_at: string;
};
export type ComponentReview = { component_id: string; version: number; decisions: CandidateDecision[] };
export type ReviewEvent = {
  type: "review_changed"; event_id: string; analysis_id: string; component_id: string;
  group_id: string; candidate_name: string; decision: Decision;
  actor: { id: string; name: string }; occurred_at: string; review: ComponentReview;
};
export function mergeReviews(current: Record<string, ComponentReview>, incoming: ComponentReview[]) {
  const next = { ...current };
  for (const review of incoming) {
    if (review.version > (next[review.component_id]?.version ?? -1)) next[review.component_id] = review;
  }
  return next;
}
