"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchSaved,
  type Analysis,
  type AnalysisSummary,
  type ComponentDetail,
  type IonTrace,
} from "@/lib/api";
import { Chromatogram } from "./plots";
import { CardInfo } from "./card-info";
import { SpectrumPanel, type SpectrumView } from "./spectrum-panel";
import { useSharedReviews } from "./use-shared-reviews";
import { ReviewNotifications } from "./review-notifications";
import type { SessionUser } from "@/lib/session";
import { ambiguityReasons } from "@/lib/assignments";
import {
  ResultGuide,
  ResultLabel,
  assignments,
  stabilityLabels,
} from "./result-labels";

import {
  emptySelection,
  selectAll,
  selectComponent,
  selectRange,
  type SelectionOptions,
} from "@/lib/selection";

const minutes = (seconds: number) => (seconds / 60).toFixed(3);
const human = (value: string) => value.replaceAll("_", " ");

export default function Workspace({ user }: { user: SessionUser }) {
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  async function signOut() {
    setSigningOut(true); setSignOutError("");
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok && response.status !== 401) throw new Error();
      location.assign("/login");
    } catch {
      setSignOutError("Could not sign out. Please try again."); setSigningOut(false);
    }
  }
  const [analyses, setAnalyses] = useState<AnalysisSummary[] | null>(null);
  const [analysisId, setAnalysisId] = useState("");
  const shared = useSharedReviews(analysisId);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selection, setSelection] = useState(emptySelection);
  const [spectrumView, setSpectrumView] = useState<SpectrumView>("library");
  const [scanTarget, setScanTarget] = useState("index=0");
  const [scanTime, setScanTime] = useState<number | undefined>();
  const [ionMz, setIonMz] = useState<number | null>(null);
  const [ionTolerance, setIonTolerance] = useState(0.5);
  const [ionTrace, setIonTrace] = useState<IonTrace | null>(null);
  const [ionError, setIonError] = useState("");
  const [ionRetry, setIonRetry] = useState(0);
  useEffect(() => {
    setSpectrumView(selection.ids.length > 1 ? "compare" : "library");
  }, [selection]);
  const selectedId = selection.active;
  const selectedIds = new Set(selection.ids);
  const [loadedDetail, setDetail] = useState<ComponentDetail | null>(null);
  const [candidateIndex, setCandidateIndex] = useState(0);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [retry, setRetry] = useState(0);
  const [detailRetry, setDetailRetry] = useState(0);
  const [loadMs, setLoadMs] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [stability, setStability] = useState("all");
  const [sort, setSort] = useState("time");
  const cache = useRef(new Map<string, ComponentDetail>());
  const rows = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    fetchSaved<{ analyses: AnalysisSummary[] }>("/analyses", controller.signal)
      .then((result) => {
        setAnalyses(result.analyses);
        setAnalysisId(
          (current) =>
            current ||
            new URLSearchParams(location.search).get("analysis") ||
            result.analyses[0]?.id ||
            "",
        );
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err.message);
      });
    return () => controller.abort();
  }, [retry]);

  useEffect(() => {
    if (!analysisId) return;
    const controller = new AbortController();
    const start = performance.now();
    setAnalysis(null);
    setDetail(null);
    setError("");
    setLoadMs(null);
    cache.current.clear();
    setQuery("");
    setStatus("all");
    setStability("all");
    setScanTarget("index=0");
    setScanTime(undefined);
    setIonMz(null);
    setIonTrace(null);
    fetchSaved<Analysis>(
      `/analyses/${encodeURIComponent(analysisId)}`,
      controller.signal,
    )
      .then((result) => {
        setAnalysis(result);
        setLoadMs(performance.now() - start);
        const requested = new URLSearchParams(location.search).get("peak");
        const peak =
          result.peaks.find((p) => p.component_id === requested) ??
          [...result.peaks].sort((a, b) => b.area_percent - a.area_percent)[0];
        setSelection(
          peak
            ? {
                ids: [peak.component_id],
                active: peak.component_id,
                anchor: peak.component_id,
              }
            : emptySelection,
        );
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err.message);
      });
    return () => controller.abort();
  }, [analysisId, retry]);

  useEffect(() => {
    setIonTrace(null);
    setIonError("");
    if (!analysis || ionMz === null) return;
    const controller = new AbortController();
    fetchSaved<IonTrace>(
      `/analyses/${analysis.id}/ions?mz=${ionMz}&tolerance=${ionTolerance}`,
      controller.signal,
    )
      .then((trace) => {
        if (controller.signal.aborted) return;
        if (
          trace.intensity.length !==
          analysis.raw_chromatogram?.time_seconds.length
        )
          throw new Error("The ion trace does not match this acquisition.");
        setIonTrace(trace);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setIonError(error.message);
      });
    return () => controller.abort();
  }, [analysis, ionMz, ionTolerance, ionRetry]);

  useEffect(() => {
    if (!analysis) return;
    const controller = new AbortController();
    setDetail(null);
    setDetailError("");
    setCandidateIndex(0);
    const params = new URLSearchParams({
      analysis: analysis.id,
    });
    if (selectedId) params.set("peak", selectedId);
    const previous = new URLSearchParams(location.search);
    const requestedCandidate = previous.get("peak") === selectedId ? previous.get("candidate") : null;
    if (requestedCandidate) params.set("candidate", requestedCandidate);
    history.replaceState(null, "", `?${params}`);
    if (!selectedId) return;
    const key = `${analysis.id}/${selectedId}`;
    const saved = cache.current.get(key);
    function showDetail(result: ComponentDetail) {
      setDetail(result);
      const candidate = result.component.candidates.findIndex((item) => item.group_id === requestedCandidate);
      setCandidateIndex(Math.max(0, candidate));
    }
    if (saved) showDetail(saved);
    else
      fetchSaved<ComponentDetail>(
        `/analyses/${analysis.id}/components/${selectedId}`,
        controller.signal,
      )
        .then((result) => {
          if (controller.signal.aborted) return;
          cache.current.set(key, result);
          showDetail(result);
        })
        .catch((err) => {
          if (!controller.signal.aborted) setDetailError(err.message);
        });
    return () => controller.abort();
  }, [analysis, selectedId, detailRetry]);

  const peaks = useMemo(
    () =>
      (analysis?.peaks ?? [])
        .filter(
          (p) =>
            (status === "all" || p.status === status) &&
            (stability === "all" ||
              (p.stability ?? "not_reviewed") === stability) &&
            p.search_text.toLowerCase().includes(query.trim().toLowerCase()),
        )
        .sort((a, b) =>
          sort === "area"
            ? b.area_percent - a.area_percent
            : sort === "score"
              ? (b.score ?? -1) - (a.score ?? -1)
              : a.apex_seconds - b.apex_seconds,
        ),
    [analysis, query, status, stability, sort],
  );
  const selected = analysis?.peaks.find((p) => p.component_id === selectedId);
  const selectedIndex = peaks.findIndex((p) => p.component_id === selectedId);
  const detail =
    loadedDetail?.component.component_id === selectedId ? loadedDetail : null;
  function choose(
    id: string,
    options: SelectionOptions = {},
    order = peaks.map((p) => p.component_id),
  ) {
    setSelection((current) => selectComponent(current, id, order, options));
  }
  function tableKeys(event: React.KeyboardEvent<HTMLTableElement>) {
    if (!(event.target instanceof HTMLElement)) return;
    if (!event.target.closest(".row-select, .selection-cell input")) return;
    const rowId = event.target.closest("tr")?.dataset.component;
    const index = peaks.findIndex((p) => p.component_id === rowId);
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      setSelection((current) =>
        selectAll(
          current,
          peaks.map((p) => p.component_id),
        ),
      );
    } else if (event.key === "Escape") {
      event.preventDefault();
      setSelection(emptySelection);
    } else if (
      ["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key) &&
      peaks.length
    ) {
      event.preventDefault();
      const next =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? peaks.length - 1
            : Math.max(
                0,
                Math.min(
                  peaks.length - 1,
                  index + (event.key === "ArrowDown" ? 1 : -1),
                ),
              );
      const id = peaks[next].component_id;
      choose(id, { range: event.shiftKey });
      rows.current
        ?.querySelector<HTMLButtonElement>(
          `[data-component="${id}"] .row-select`,
        )
        ?.focus({ preventScroll: true });
    }
  }
  useEffect(() => {
    const container = rows.current;
    const row = container?.querySelector<HTMLElement>(`[data-active="true"]`);
    if (container && row) {
      const a = row.getBoundingClientRect(),
        b = container.getBoundingClientRect();
      if (a.top < b.top + 36 || a.bottom > b.bottom)
        container.scrollTop += a.top - b.top - 40;
    }
  }, [selectedId, peaks]);

  return (
    <main className="workspace">
      <header className="app-header">
        <div className="wordmark">
          <img
            className="brand-logo"
            src="/mafer-logo.svg"
            alt="Mafer"
            width={104}
            height={21}
          />
          <div>
            <h1>Analyst workspace</h1>
            <p>GC–MS · Saved analysis</p>
          </div>
        </div>
        <div className="sample-controls">
          <label className="sr-only" htmlFor="sample">
            Saved sample
          </label>
          <select
            id="sample"
            value={analysisId}
            onChange={(e) => setAnalysisId(e.target.value)}
            disabled={!analyses?.length}
          >
            {analyses?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.sample_name}
              </option>
            ))}
          </select>
          <button onClick={() => setRetry((n) => n + 1)}>Reload sample</button>
          <span className="load-time" aria-live="polite">
            {loadMs !== null
              ? `Loaded in ${Math.round(loadMs)} ms`
              : analysisId && !error
                ? "Loading…"
                : ""}
          </span>
        </div>
        <div className="account-controls"><span>{user.name}</span><button disabled={signingOut} onClick={signOut}>{signingOut ? "Signing out…" : "Sign out"}</button>{signOutError && <span role="alert">{signOutError}</span>}</div>
        <ReviewNotifications events={shared.notifications} connection={shared.connection} userId={user.id} onDismiss={shared.dismiss} />
      </header>
      {error ? (
        <section className="state-page" role="alert">
          <h2>Could not load this analysis</h2>
          <p>{error}</p>
          <button onClick={() => setRetry((n) => n + 1)}>Try again</button>
        </section>
      ) : !analyses || (analysisId && !analysis) ? (
        <section className="state-page" role="status">
          <span className="loading-dot" />
          <p>Loading saved analysis…</p>
        </section>
      ) : !analysis ? (
        <section className="state-page">
          <h2>No saved analyses yet</h2>
          <p>Import a saved Rust report to open a sample here.</p>
          <button onClick={() => setRetry((n) => n + 1)}>
            Refresh samples
          </button>
        </section>
      ) : (
        <>
          <div className="sample-summary">
            <strong>{analysis.metadata.sample_name}</strong>
            <span>
              {analysis.metadata.acquisition.scan_count.toLocaleString()} scans
            </span>
            <span>
              {(analysis.metadata.acquisition.end_seconds / 60).toFixed(1)} min
            </span>
            <span>
              m/z {analysis.metadata.acquisition.mz_min}–
              {analysis.metadata.acquisition.mz_max}
            </span>
            <span className="saved-indicator">Saved result</span>
          </div>
          <div className="workspace-grid">
            <Chromatogram
              key={analysis.id}
              analysis={analysis}
              selected={selected}
              localTrace={detail?.review?.trace}
              selectedIds={selectedIds}
              onSelect={(id, options) =>
                choose(
                  id,
                  options,
                  analysis.peaks.map((p) => p.component_id),
                )
              }
              onScan={(time) => {
                setScanTarget(`time_seconds=${time}`);
                setSpectrumView("raw");
              }}
              scanTime={spectrumView === "raw" ? scanTime : undefined}
              ionMz={ionMz}
              ionTolerance={ionTolerance}
              ionTrace={
                ionTrace?.mz === ionMz && ionTrace?.tolerance === ionTolerance
                  ? ionTrace
                  : null
              }
              ionError={ionError}
              onIonTolerance={setIonTolerance}
              onClearIon={() => setIonMz(null)}
              onRetryIon={() => setIonRetry((n) => n + 1)}
              onSelectRange={(ids, additive) =>
                setSelection((current) => selectRange(current, ids, additive))
              }
            />
            <SpectrumPanel
              analysis={analysis}
              selectedIds={selection.ids}
              activeId={selectedId}
              detail={detail}
              detailError={detailError}
              onRetryDetail={() => setDetailRetry((n) => n + 1)}
              candidateIndex={candidateIndex}
              view={spectrumView}
              onViewChange={(view) => {
                if (view === "raw" && scanTime === undefined && selected)
                  setScanTarget(`time_seconds=${selected.apex_seconds}`);
                setSpectrumView(view);
              }}
              scanTarget={scanTarget}
              onScanTarget={setScanTarget}
              onScanLoaded={setScanTime}
              ionMz={ionMz}
              ionTolerance={ionTolerance}
              onIonSelect={setIonMz}
              onActivate={(id) =>
                setSelection((current) => ({ ...current, active: id }))
              }
            />
            <section
              className="panel peaks-panel"
              aria-labelledby="peaks-title"
            >
              <div className="panel-heading">
                <div>
                  <div className="card-title">
                    <h2 id="peaks-title">Detected components</h2>
                    <CardInfo title="Detected components">
                      Groups of ions detected by the saved analysis, each with a
                      retention time and proposed identity. Select a row to
                      inspect it; use checkboxes, Ctrl/⌘-click or Shift-click to
                      compare several. Area % is relative signal area, not
                      concentration.
                    </CardInfo>
                    <span className="count">{peaks.length}</span>
                  </div>
                  <p id="selection-help">
                    ↑ ↓ navigate · Shift selects a range · Ctrl / ⌘ adds peaks
                  </p>
                </div>
                <div className="button-group">
                  <button
                    aria-label="Previous component"
                    disabled={selectedIndex <= 0}
                    onClick={() =>
                      choose(peaks[selectedIndex - 1].component_id)
                    }
                  >
                    ↑
                  </button>
                  <button
                    aria-label="Next component"
                    disabled={
                      !peaks.length || selectedIndex >= peaks.length - 1
                    }
                    onClick={() =>
                      choose(peaks[Math.max(0, selectedIndex + 1)].component_id)
                    }
                  >
                    ↓
                  </button>
                </div>
              </div>
              <div className="table-filters">
                <input
                  aria-label="Search components by name, CAS, or ID"
                  placeholder="Search name, CAS, or component…"
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                <select
                  aria-label="Filter by assignment"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  <option value="all">All assignments</option>
                  {Object.keys(assignments).map((value) => (
                    <option key={value} value={value}>
                      {human(value)} (
                      {analysis.peaks.filter((p) => p.status === value).length})
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Filter by robustness"
                  value={stability}
                  onChange={(event) => setStability(event.target.value)}
                >
                  <option value="all">Robustness: all</option>
                  {Object.keys(stabilityLabels).map((value) => (
                    <option key={value} value={value}>
                      {human(value)} (
                      {
                        analysis.peaks.filter((p) => p.stability === value)
                          .length
                      }
                      )
                    </option>
                  ))}
                  {analysis.peaks.some((p) => !p.stability) && (
                    <option value="not_reviewed">Not reviewed</option>
                  )}
                </select>
                <select
                  aria-label="Sort components"
                  value={sort}
                  onChange={(e) => setSort(e.target.value)}
                >
                  <option value="time">Time ↑</option>
                  <option value="area">Area ↓</option>
                  <option value="score">Similarity ↓</option>
                </select>
              </div>
              <div className="table-scroll" ref={rows}>
                <table
                  aria-label="Detected components"
                  aria-describedby="selection-help"
                  onKeyDown={tableKeys}
                >
                  <thead>
                    <tr>
                      <th className="selection-cell" scope="col">
                        <span className="sr-only">Select</span>
                      </th>
                      <th scope="col">RT (min)</th>
                      <th scope="col">Leading proposal</th>
                      <th scope="col" className="numeric">
                        Area %
                      </th>
                      <th scope="col" className="numeric">
                        Similarity
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {peaks.map((p) => (
                      <tr
                        key={p.component_id}
                        data-component={p.component_id}
                        data-selected={selectedIds.has(p.component_id)}
                        data-active={p.component_id === selectedId}
                        onClick={(event) =>
                          choose(p.component_id, {
                            toggle: event.metaKey || event.ctrlKey,
                            range: event.shiftKey,
                          })
                        }
                      >
                        <td className="selection-cell">
                          <input
                            type="checkbox"
                            aria-label={`Include ${p.component_id} in selection`}
                            checked={selectedIds.has(p.component_id)}
                            onClick={(event) => event.stopPropagation()}
                            onChange={(event) =>
                              choose(p.component_id, {
                                toggle: true,
                                range: (event.nativeEvent as MouseEvent)
                                  .shiftKey,
                              })
                            }
                          />
                        </td>
                        <td>
                          <button
                            className="row-select"
                            aria-pressed={selectedIds.has(p.component_id)}
                            tabIndex={
                              p.component_id === selectedId ||
                              (selectedIndex < 0 &&
                                p.component_id === peaks[0]?.component_id)
                                ? 0
                                : -1
                            }
                            aria-label={`Select ${p.component_id} at ${minutes(p.apex_seconds)} minutes`}
                            onClick={(event) => {
                              event.stopPropagation();
                              choose(p.component_id, {
                                toggle: event.metaKey || event.ctrlKey,
                                range: event.shiftKey,
                              });
                            }}
                          >
                            {minutes(p.apex_seconds)}
                          </button>
                        </td>
                        <td>
                          <span
                            className="compound-name"
                            title={p.name || "Unassigned"}
                          >
                            {p.name || "Unassigned"}
                          </span>
                          {shared.reviews[p.component_id] && <span className="analyst-summary">
                            {shared.reviews[p.component_id].decisions.find((d) => d.decision === "accepted")
                              ? `Analyst accepted: ${shared.reviews[p.component_id].decisions.find((d) => d.decision === "accepted")!.candidate_name}`
                              : shared.reviews[p.component_id].decisions.some((d) => d.decision === "rejected")
                                ? "Analyst review: candidates rejected" : "Analyst review: unreviewed"}
                          </span>}
                          <span className="row-meta">
                            <span>
                              {p.component_id.replace("component-", "#")}
                            </span>
                            <span title={assignments[p.status]}>
                              {human(p.status)}
                            </span>
                            {p.stability && (
                              <span title={stabilityLabels[p.stability]}>
                                {human(p.stability)}
                              </span>
                            )}
                          </span>
                        </td>
                        <td className="numeric">{p.area_percent.toFixed(2)}</td>
                        <td className="numeric">
                          {p.score?.toFixed(3) ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!peaks.length && (
                  <div className="panel-state">
                    <p>No components match these filters.</p>
                    <button
                      onClick={() => {
                        setQuery("");
                        setStatus("all");
                        setStability("all");
                      }}
                    >
                      Clear filters
                    </button>
                  </div>
                )}
              </div>
              <div className="selection-summary">
                <span aria-live="polite">
                  {selection.ids.length} selected · {peaks.length} shown
                  {selectedId
                    ? ` · Viewing #${selectedId.replace("component-", "")}`
                    : ""}
                  {selectedId && selectedIndex < 0 ? " (outside filters)" : ""}
                </span>
                <button
                  disabled={!peaks.length}
                  onClick={() =>
                    setSelection((current) =>
                      selectAll(
                        current,
                        peaks.map((p) => p.component_id),
                      ),
                    )
                  }
                >
                  Select shown
                </button>
                <button
                  disabled={!selection.ids.length}
                  onClick={() => setSelection(emptySelection)}
                >
                  Clear
                </button>
              </div>
            </section>
            <section
              className="panel candidates-panel"
              aria-labelledby="candidates-title"
            >
              <div className="panel-heading">
                <div>
                  <div className="card-title">
                    <h2 id="candidates-title">Library candidates</h2>
                    <CardInfo title="Library candidates">
                      Library entries with spectra resembling the active
                      component, ranked by similarity. Select a candidate to
                      compare its reference spectrum. Similarity is not a
                      probability, and a leading match does not confirm chemical
                      identity. Analyst decisions are shared with all registered users. Accepting a candidate group does not distinguish identities within it.
                    </CardInfo>
                  </div>
                  <p>
                    {selected
                      ? `Saved candidates for #${selected.component_id.replace("component-", "")} · ${minutes(selected.apex_seconds)} min`
                      : "Select a component to inspect its library matches"}
                  </p>
                </div>
                <span className="count">
                  {detail?.component.candidates.length ?? "—"}
                </span>
              </div>
              <div className="shared-review-status" role="status">
                <span data-live={shared.connection === "Live"}>{shared.connection}</span>
                <span>{shared.saving ? "Saving decision…" : "Shared analyst decisions"}</span>
              </div>
              {shared.error && <p className="review-save-error" role="alert">{shared.error}</p>}
              <div className="candidate-scroll">
                {detail ? (
                  <>
                    <div className="component-facts">
                      <span>
                        Integrated area{" "}
                        <strong>
                          {detail.component.area_percent.toFixed(2)}%
                        </strong>
                      </span>
                      <span>
                        Window{" "}
                        <strong>
                          {minutes(detail.component.start_seconds)}–
                          {minutes(detail.component.end_seconds)} min
                        </strong>
                      </span>
                      {detail.review && (
                        <span>
                          Robustness{" "}
                          <ResultLabel
                            value={detail.review.label}
                            kind="stability"
                          />
                        </span>
                      )}
                    </div>
                    {detail.component.status === "ambiguous" && (
                      <section className="assignment-reason" aria-labelledby="ambiguity-title">
                        <h3 id="ambiguity-title">Why ambiguous?</h3>
                        {ambiguityReasons(
                          detail.component,
                          analysis.metadata.parameters?.ambiguity_margin,
                        ).map((reason) => <p key={reason}>{reason}</p>)}
                      </section>
                    )}
                    {detail.component.candidates.length ? (
                      <ol className="candidate-list">
                        {detail.component.candidates.map((c, index) => (
                          <li key={c.group_id}>
                            <button
                              className="candidate"
                              aria-pressed={candidateIndex === index}
                              onClick={() => {
                                setCandidateIndex(index);
                                setSpectrumView("library");
                              }}
                            >
                              <span className="candidate-rank">
                                {index + 1}
                              </span>
                              <span className="candidate-identity">
                                <strong>
                                  {c.identities.map((i) => i.name).join(" / ")}
                                </strong>
                                <small>
                                  {c.identities
                                    .map(
                                      (i) =>
                                        `${i.cas ? `CAS ${i.cas}` : "CAS unavailable"}${i.source ? ` · ${i.source}` : ""}`,
                                    )
                                    .join(" / ")}
                                </small>
                              </span>
                              <span className="candidate-score">
                                {c.score.toFixed(3)}
                                <small>similarity</small>
                              </span>
                            </button>
                            <div className="candidate-decision">
                              <div className="button-group" role="group" aria-label={`Analyst decision for candidate ${index + 1}`}>
                                <button disabled={!shared.loaded || !!shared.saving}
                                  aria-pressed={shared.reviews[selectedId]?.decisions.find((d) => d.group_id === c.group_id)?.decision === "accepted"}
                                  onClick={() => shared.save(selectedId, c.group_id, "accepted")}>Accept</button>
                                <button disabled={!shared.loaded || !!shared.saving}
                                  aria-pressed={shared.reviews[selectedId]?.decisions.find((d) => d.group_id === c.group_id)?.decision === "rejected"}
                                  onClick={() => shared.save(selectedId, c.group_id, "rejected")}>Reject</button>
                                <button disabled={!shared.loaded || !!shared.saving || !shared.reviews[selectedId]?.decisions.some((d) => d.group_id === c.group_id && d.decision !== "unreviewed")}
                                  onClick={() => shared.save(selectedId, c.group_id, "unreviewed")}>Clear decision</button>
                              </div>
                              <small>{(() => {
                                const decision = shared.reviews[selectedId]?.decisions.find((d) => d.group_id === c.group_id);
                                return decision ? `${human(decision.decision)} · ${decision.updated_by.name} · ${new Date(decision.updated_at).toLocaleString()}` : "Unreviewed";
                              })()}</small>
                            </div>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="empty-copy">
                        No library candidates for this component.
                      </p>
                    )}
                    {!!detail.component.warnings.length && (
                      <details className="review-notes">
                        <summary>
                          Component notes ({detail.component.warnings.length})
                        </summary>
                        <ul>
                          {detail.component.warnings.map((warning, i) => (
                            <li key={i}>{human(warning)}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </>
                ) : (
                  <div className="panel-state">
                    {detailError
                      ? "Candidates could not load. Retry the spectrum above."
                      : selected
                        ? "Loading candidates…"
                        : "Select a component to inspect library matches."}
                  </div>
                )}
              </div>
            </section>
          </div>
          <footer className="workspace-footer">
            <span>
              Identities are proposals · Similarity is not a probability · Area
              is not concentration
            </span>
            <button className="help-link" popoverTarget="result-guide">
              Labels & shortcuts
            </button>
          </footer>
        </>
      )}
      <ResultGuide />
    </main>
  );
}
