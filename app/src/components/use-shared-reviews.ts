"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchSaved } from "@/lib/api";
import { mergeReviews, type ComponentReview, type Decision, type ReviewEvent } from "@/lib/reviews";

export function useSharedReviews(analysisId: string) {
  const [reviews, setReviews] = useState<Record<string, ComponentReview>>({});
  const [connection, setConnection] = useState("Connecting…");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState("");
  const [notifications, setNotifications] = useState<ReviewEvent[]>([]);
  const current = useRef(reviews);
  const scope = useRef(analysisId);
  scope.current = analysisId;
  const seen = useRef(new Set<string>());
  const merge = useCallback((incoming: ComponentReview[]) => {
    current.current = mergeReviews(current.current, incoming);
    setReviews(current.current);
  }, []);
  const applyEvent = useCallback((event: ReviewEvent) => {
    if (event.analysis_id !== scope.current || seen.current.has(event.event_id)) return;
    if (event.review.version < (current.current[event.component_id]?.version ?? 0)) return;
    seen.current.add(event.event_id);
    if (seen.current.size > 256) seen.current.delete(seen.current.values().next().value!);
    merge([event.review]);
    setNotifications((items) => [...items.slice(-4), event]);
  }, [merge]);
  useEffect(() => {
    current.current = {}; setReviews({}); seen.current.clear();
    setNotifications([]); setError(""); setSaving(""); setLoaded(false);
    if (!analysisId) return;
    let stopped = false;
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let syncTimer: ReturnType<typeof setTimeout> | undefined;
    let retry = 0;
    const controller = new AbortController();
    async function synchronize() {
      clearTimeout(syncTimer);
      try {
        const result = await fetchSaved<{ reviews: ComponentReview[] }>(`/analyses/${analysisId}/reviews`, controller.signal);
        if (stopped) return;
        merge(result.reviews); setLoaded(true);
        if (socket?.readyState === WebSocket.OPEN) setConnection("Live");
      } catch {
        if (!stopped) {
          setConnection("Sync unavailable · retrying…");
          syncTimer = setTimeout(synchronize, 5000);
        }
      }
    }
    function connect() {
      if (stopped) return;
      setConnection(retry ? "Reconnecting…" : "Connecting…");
      socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/analyses/${analysisId}`);
      socket.onmessage = (message) => {
        if (stopped) return;
        try {
          const event = JSON.parse(message.data);
          if (event.type === "ready" || event.type === "resync") {
            retry = 0;
            void synchronize();
          } else if (event.type === "review_changed") applyEvent(event);
        } catch { socket?.close(); }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (stopped) return;
        setConnection("Reconnecting…");
        // Also detects revoked sessions; a failed handshake has no readable HTTP status.
        void synchronize();
        timer = setTimeout(connect, Math.min(30_000, 1000 * 2 ** Math.min(retry++, 5)) + Math.random() * 250);
      };
    }
    void synchronize();
    connect();
    const focus = () => { void synchronize(); };
    window.addEventListener("focus", focus);
    return () => {
      stopped = true; controller.abort(); clearTimeout(timer); clearTimeout(syncTimer); socket?.close();
      window.removeEventListener("focus", focus);
    };
  }, [analysisId, applyEvent, merge]);
  async function save(component: string, group: string, decision: Decision) {
    if (saving || !loaded) return;
    setSaving(`${component}/${group}`); setError("");
    try {
      const response = await fetch(`/api/analyses/${analysisId}/components/${component}/candidates/${encodeURIComponent(group)}/decision`, {
        method: "PUT", headers: { "content-type": "application/json" },
        body: JSON.stringify({ decision, expected_version: current.current[component]?.version ?? 0 }),
      });
      if (response.status === 401) {
        location.assign(`/login?return_to=${encodeURIComponent(location.pathname + location.search)}`);
        return;
      }
      const result = await response.json();
      if (scope.current !== analysisId) return;
      if (result.review) merge([result.review]);
      if (!response.ok) throw new Error(result.error?.message ?? "The decision could not be saved. Try again.");
      if (result.event) applyEvent(result.event);
    } catch (error) {
      if (scope.current === analysisId) setError(error instanceof Error ? error.message : "Could not save. Try again.");
    } finally { if (scope.current === analysisId) setSaving(""); }
  }
  return { reviews, connection, loaded, error, saving, notifications, save,
    dismiss: (id: string) => setNotifications((items) => items.filter((item) => item.event_id !== id)) };
}
