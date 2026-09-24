"use client";

import Link from "next/link";
import { useId, useRef } from "react";
import type { ReviewEvent } from "@/lib/reviews";

export function ReviewNotifications({ events, connection, userId, onDismiss }: {
  events: ReviewEvent[]; connection: string; userId: string; onDismiss: (id: string) => void;
}) {
  const id = useId();
  const panel = useRef<HTMLDivElement>(null);
  const newest = events.at(-1);
  const message = (event: ReviewEvent) => `${event.actor.id === userId ? "You" : event.actor.name} ${event.decision === "unreviewed" ? "cleared the decision for" : event.decision} ${event.candidate_name}`;
  return <div className="notification-control">
    <button className="notification-trigger" popoverTarget={id} aria-label={`Notifications${events.length ? `, ${events.length} recent changes` : ""}`}>
      <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 14h12l-1.5-2V8a4.5 4.5 0 0 0-9 0v4L4 14Zm4 3h4" /></svg>
      <span>Notifications</span>
      {events.length > 0 && <span className="notification-count">{events.length}</span>}
    </button>
    <span className="sr-only" role="status">{newest ? message(newest) : ""}</span>
    <div ref={panel} id={id} className="notification-panel" popover="auto" aria-label="Review notifications">
      <div className="notification-heading"><h2>Notifications</h2><span className="connection-status" data-live={connection === "Live"}>{connection}</span></div>
      <p className="notification-caption">Recent changes to this sample</p>
      {events.length ? <ul>{[...events].reverse().map((event) => <li key={event.event_id}>
        <p>{message(event)}</p>
        <span className="notification-meta">{event.component_id.replace("component-", "#")} · <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time></span>
        <div className="notification-actions">
          <Link href={`/?${new URLSearchParams({ analysis: event.analysis_id, peak: event.component_id, candidate: event.group_id })}`} onClick={() => { panel.current?.hidePopover(); onDismiss(event.event_id); }}>View component</Link>
          <button onClick={() => onDismiss(event.event_id)} aria-label={`Dismiss change to ${event.component_id}`}>Dismiss</button>
        </div>
      </li>)}</ul> : <div className="notification-empty"><strong>No new notifications</strong><p>Team review changes will appear here.</p></div>}
    </div>
  </div>;
}
