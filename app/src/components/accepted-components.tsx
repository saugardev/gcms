"use client";

import Link from "next/link";
import { useState } from "react";
import type { acceptedComponents } from "@/lib/reviews";
import { CardInfo } from "./card-info";

export function AcceptedComponents({ analysisId, rows, loaded, connection, dashboardHref }: {
  analysisId: string; rows: ReturnType<typeof acceptedComponents>; loaded: boolean;
  connection: string; dashboardHref: string;
}) {
  const [query, setQuery] = useState("");
  const visible = rows.filter(({ peak, decision }) =>
    `${decision.candidate_name} ${peak.component_id} ${decision.updated_by.name}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <section className="panel accepted-panel" aria-labelledby="accepted-title">
    <div className="panel-heading">
      <div><div className="card-title"><h2 id="accepted-title">Accepted components</h2><CardInfo title="Accepted components">Components with a candidate group accepted by an analyst for this sample. These are shared review decisions, not automatic chemical confirmations. Area (%) is the component’s share of reported signal area, not concentration. Open a component to inspect its spectrum and the accepted candidate.</CardInfo></div>
        <p>Your team’s accepted candidates for this sample.</p></div>
      <span className="count">{loaded ? rows.length : "—"}</span>
    </div>
    <div className="accepted-toolbar">
      <input type="search" aria-label="Search accepted components" placeholder="Search candidate, component or reviewer…" value={query} onChange={(event) => setQuery(event.target.value)} />
      <span className="connection-status" data-live={connection === "Live"}>{connection}</span>
    </div>
    {!loaded ? <div className="panel-state" role="status">{connection.startsWith("Sync unavailable") ? "Review decisions are unavailable. Retrying…" : "Loading accepted components…"}</div> : !rows.length ?
      <div className="accepted-empty"><span className="accepted-empty-icon" aria-hidden="true">✓</span><h3>No accepted components yet</h3><p>Open a component in the dashboard and accept a library candidate to add it here.</p><Link className="button-link" href={dashboardHref}>Open dashboard</Link></div> : !visible.length ?
      <div className="accepted-empty"><h3>No matching components</h3><p>Try a different candidate name, component or reviewer.</p><button onClick={() => setQuery("")}>Clear search</button></div> :
      <div className="table-scroll accepted-table-scroll"><table className="accepted-table" aria-label="Accepted components">
        <thead><tr><th scope="col">Accepted candidate</th><th scope="col">RT (min)</th><th scope="col">Area (%)</th><th scope="col">Accepted by</th><th scope="col">Last updated</th><th scope="col"><span className="sr-only">Open component</span></th></tr></thead>
        <tbody>{visible.map(({ peak, decision }) => <tr key={peak.component_id}>
          <td><strong>{decision.candidate_name}</strong><span className="accepted-component-id">{peak.component_id.replace("component-", "#")}</span></td>
          <td>{(peak.apex_seconds / 60).toFixed(3)}</td><td>{peak.area_percent.toFixed(2)}</td><td>{decision.updated_by.name}</td>
          <td><time dateTime={decision.updated_at}>{new Date(decision.updated_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</time></td>
          <td><Link className="component-link" aria-label={`View ${peak.component_id} in dashboard`} href={`/?${new URLSearchParams({ analysis: analysisId, peak: peak.component_id, candidate: decision.group_id })}`}>View component <span aria-hidden="true">↗</span></Link></td>
        </tr>)}</tbody>
      </table></div>}
    {loaded && rows.length > 0 && <div className="accepted-footer">{visible.length} of {rows.length} accepted components</div>}
  </section>;
}
