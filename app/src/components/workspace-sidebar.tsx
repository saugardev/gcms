"use client";

import Link from "next/link";
import { useState } from "react";
import type { AnalysisSummary } from "@/lib/api";
import type { SessionUser } from "@/lib/session";

export function WorkspaceSidebar({ user, analyses, analysisId, onSelect, view, dashboardHref, acceptedHref, acceptedCount }: {
  user: SessionUser; analyses: AnalysisSummary[] | null; analysisId: string;
  onSelect: (id: string) => void; view: "dashboard" | "accepted";
  dashboardHref: string; acceptedHref: string; acceptedCount: number | null;
}) {
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState("");
  async function signOut() {
    setSigningOut(true); setError("");
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok && response.status !== 401) throw new Error();
      location.assign("/login");
    } catch {
      setError("Could not sign out. Please try again."); setSigningOut(false);
    }
  }
  return <aside className="workspace-sidebar" aria-label="Workspace sidebar">
    <Link className="sidebar-brand" href={dashboardHref} aria-label="Mafer dashboard">
      <img src="/mafer-logo.svg" alt="Mafer" width={104} height={21} />
      <span>Analyst workspace</span>
    </Link>
    <div className="project-selector">
      <label htmlFor="sample">Project</label>
      <select id="sample" value={analysisId} onChange={(event) => onSelect(event.target.value)} disabled={!analyses?.length}>
        {!analyses?.length && <option value="">{analyses ? "No saved samples" : "Loading samples…"}</option>}
        {analyses?.map((analysis) => <option key={analysis.id} value={analysis.id}>{analysis.sample_name}</option>)}
      </select>
      <span>Saved sample</span>
    </div>
    <nav className="sidebar-nav" aria-label="Workspace pages">
      <Link href={dashboardHref} aria-current={view === "dashboard" ? "page" : undefined}>
        <svg viewBox="0 0 20 20" aria-hidden="true"><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="12" y="3" width="5" height="6" rx="1" /><rect x="3" y="12" width="6" height="5" rx="1" /><rect x="12" y="12" width="5" height="5" rx="1" /></svg>
        Dashboard
      </Link>
      <Link href={acceptedHref} aria-current={view === "accepted" ? "page" : undefined}>
        <svg viewBox="0 0 20 20" aria-hidden="true"><rect x="3" y="3" width="14" height="14" rx="3" /><path d="m6 10 3 3 5-6" /></svg>
        <span>Accepted components</span>
        {acceptedCount !== null && <span className="nav-count">{acceptedCount}</span>}
      </Link>
    </nav>
    <div className="sidebar-account">
      <div className="sidebar-user"><span className="user-avatar" aria-hidden="true">{user.name.slice(0, 1).toUpperCase()}</span><div><strong>{user.name}</strong><span title={user.email}>{user.email}</span></div></div>
      {error && <p role="alert" className="auth-error">{error}</p>}
      <button className="sign-out" disabled={signingOut} onClick={signOut}>
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M8 3H4v14h4M8 10h9m-3-3 3 3-3 3" /></svg>
        {signingOut ? "Signing out…" : "Sign out"}
      </button>
    </div>
  </aside>;
}
