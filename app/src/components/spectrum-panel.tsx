"use client";

import { useEffect, useState } from "react";
import {
  fetchSaved,
  type Analysis,
  type ComponentDetail,
  type ComponentSpectrum,
  type RawScan,
} from "@/lib/api";
import { MassSpectrum } from "./plots";
import { ResultLabel } from "./result-labels";
import { CardInfo } from "./card-info";

export type SpectrumView = "library" | "compare" | "raw";

export function SpectrumPanel({
  analysis,
  selectedIds,
  activeId,
  detail,
  detailError,
  onRetryDetail,
  candidateIndex,
  view,
  onViewChange,
  scanTarget,
  onScanTarget,
  onScanLoaded,
  onActivate,
  ionMz,
  ionTolerance,
  onIonSelect,
}: {
  analysis: Analysis;
  selectedIds: string[];
  activeId: string;
  detail: ComponentDetail | null;
  detailError: string;
  onRetryDetail: () => void;
  candidateIndex: number;
  view: SpectrumView;
  onViewChange: (view: SpectrumView) => void;
  scanTarget: string;
  onScanTarget: (target: string) => void;
  onScanLoaded: (time: number) => void;
  onActivate: (id: string) => void;
  ionMz: number | null;
  ionTolerance: number;
  onIonSelect: (mz: number) => void;
}) {
  const [comparison, setComparison] = useState<{
    key: string;
    spectra: ComponentSpectrum[];
  } | null>(null);
  const [loadedScan, setScan] = useState<{ key: string; scan: RawScan } | null>(
    null,
  );
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const ids = [...selectedIds].sort().join(",");
  const requestKey = `${analysis.id}/${view}/${view === "compare" ? ids : scanTarget}`;
  useEffect(() => {
    setError("");
    if (view === "library" || (view === "compare" && !ids)) return;
    const controller = new AbortController();
    if (view === "compare") {
      setComparison(null);
      fetchSaved<{ spectra: ComponentSpectrum[] }>(
        `/analyses/${analysis.id}/spectra?components=${encodeURIComponent(ids)}`,
        controller.signal,
      )
        .then((result) => {
          if (!controller.signal.aborted)
            setComparison({ key: requestKey, ...result });
        })
        .catch((err) => {
          if (!controller.signal.aborted) setError(err.message);
        });
    } else {
      setScan(null);
      fetchSaved<RawScan>(
        `/analyses/${analysis.id}/scans?${scanTarget}`,
        controller.signal,
      )
        .then((scan) => {
          if (!controller.signal.aborted) {
            setScan({ key: requestKey, scan });
            onScanLoaded(scan.time_seconds);
          }
        })
        .catch((err) => {
          if (!controller.signal.aborted) setError(err.message);
        });
    }
    return () => controller.abort();
  }, [analysis.id, ids, view, scanTarget, requestKey, retry, onScanLoaded]);
  const scan = loadedScan?.key === requestKey ? loadedScan.scan : null;
  const spectra = comparison?.key === requestKey ? comparison.spectra : null;
  const selected = analysis.peaks.find((p) => p.component_id === activeId);
  const candidate = detail?.component.candidates[candidateIndex];
  const massRange: [number, number] = [
    analysis.metadata.acquisition.mz_min,
    analysis.metadata.acquisition.mz_max,
  ];
  const message = view === "library" ? detailError : error;
  const loading =
    view === "library"
      ? activeId && !detail
      : view === "compare"
        ? ids && !spectra
        : !scan;
  const title =
    view === "compare"
      ? "Compare spectra"
      : view === "raw"
        ? "Raw scan spectrum"
        : "Mass spectrum";
  return (
    <section className="panel spectrum-panel" aria-labelledby="spectrum-title">
      <div className="panel-heading">
        <div>
          <div className="card-title">
            <h2 id="spectrum-title">{title}</h2>
            <CardInfo title={title}>
              {view === "compare"
                ? "A separate spectrum for every selected component on the same mass-to-charge (m/z) axis. Each is scaled to its own strongest ion (100%), so compare ion patterns, not amounts. Zoom applies to all spectra; click a spectrum or its heading to activate its component and inspect its library candidates."
                : view === "raw"
                  ? "Ions recorded in one acquisition scan, including background. Click an ion or enter its m/z to show its signal over time on the chromatogram. Use the scan arrows or time input to move through the acquisition. The plot is scaled to its strongest ion (100%); hover to see counts."
                  : "The selected component’s reconstructed ion pattern by mass-to-charge ratio (m/z). Blue sticks show the component; gray sticks below show the chosen library reference. Each spectrum is scaled to its strongest ion (100%). Drag to zoom and compare the patterns."}
            </CardInfo>
          </div>
          <p>
            {view === "compare"
              ? `${selectedIds.length} components · Shared m/z axis`
              : view === "raw"
                ? scan
                  ? `Scan ${scan.scan_index + 1} / ${analysis.metadata.acquisition.scan_count} · ${(scan.time_seconds / 60).toFixed(4)} min`
                  : "Select any time on the chromatogram"
                : selected
                  ? `${selected.component_id} · ${(selected.apex_seconds / 60).toFixed(3)} min`
                  : "Select a component"}
          </p>
        </div>
        {view === "library" && selected && (
          <ResultLabel value={selected.status} kind="assignment" />
        )}
      </div>
      <div className="spectrum-view" role="group" aria-label="Spectrum view">
        <button
          aria-pressed={view === "library"}
          onClick={() => onViewChange("library")}
        >
          Library match
        </button>
        <button
          aria-pressed={view === "compare"}
          disabled={selectedIds.length < 2}
          onClick={() => onViewChange("compare")}
        >
          Compare ({selectedIds.length})
        </button>
        <button
          aria-pressed={view === "raw"}
          disabled={!analysis.raw_chromatogram}
          title={
            !analysis.raw_chromatogram
              ? "Raw acquisition has not been imported"
              : undefined
          }
          onClick={() => onViewChange("raw")}
        >
          Raw scan
        </button>
      </div>
      {view === "raw" && (
        <form
          className="scan-controls"
          onSubmit={(event) => {
            event.preventDefault();
            const value =
              Number(new FormData(event.currentTarget).get("time")) * 60;
            if (Number.isFinite(value)) onScanTarget(`time_seconds=${value}`);
          }}
        >
          <button
            type="button"
            aria-label="Previous raw scan"
            disabled={!scan || scan.scan_index === 0}
            onClick={() => onScanTarget(`index=${scan!.scan_index - 1}`)}
          >
            ←
          </button>
          <button
            type="button"
            aria-label="Next raw scan"
            disabled={
              !scan ||
              scan.scan_index >= analysis.metadata.acquisition.scan_count - 1
            }
            onClick={() => onScanTarget(`index=${scan!.scan_index + 1}`)}
          >
            →
          </button>
          <label htmlFor="scan-time">Time (min)</label>
          <input
            id="scan-time"
            name="time"
            type="number"
            required
            step="any"
            min={
              Math.floor(
                (analysis.metadata.acquisition.start_seconds / 60) * 1e6,
              ) / 1e6
            }
            max={
              Math.ceil(
                (analysis.metadata.acquisition.end_seconds / 60) * 1e6,
              ) / 1e6
            }
            key={scan?.time_seconds ?? "loading"}
            defaultValue={
              scan ? Number((scan.time_seconds / 60).toFixed(6)) : ""
            }
          />
          <button type="submit">Go</button>
        </form>
      )}
      {view === "raw" && (
        <form
          className="ion-extract"
          onSubmit={(event) => {
            event.preventDefault();
            const mz = Number(new FormData(event.currentTarget).get("mz"));
            if (Number.isFinite(mz) && mz >= 0 && mz <= 3276.75)
              onIonSelect(mz);
          }}
        >
          <label htmlFor="extract-mz">Extract m/z</label>
          <input
            id="extract-mz"
            name="mz"
            type="number"
            required
            min="0"
            max="3276.75"
            step="any"
            key={ionMz ?? "none"}
            defaultValue={ionMz ?? ""}
            placeholder="e.g. 83"
          />
          <button type="submit">Show ion</button>
          <span>or click an ion below</span>
        </form>
      )}
      {message ? (
        <div className="panel-state" role="alert">
          <p>{message}</p>
          <button
            onClick={() =>
              view === "library" ? onRetryDetail() : setRetry((n) => n + 1)
            }
          >
            Retry spectrum
          </button>
        </div>
      ) : loading ? (
        <div className="panel-state spectrum-loading" role="status">
          <span className="spectrum-placeholder" aria-hidden="true" />
          <p>Loading {view === "compare" ? "selected spectra" : "spectrum"}…</p>
        </div>
      ) : view === "compare" && spectra ? (
        <MassSpectrum
          key="compare"
          series={spectra.map((item) => ({
            id: item.component_id,
            label: `#${item.component_id.replace("component-", "")} · ${(item.apex_seconds / 60).toFixed(3)} min`,
            spectrum: item.spectrum,
          }))}
          massRange={massRange}
          activeId={activeId}
          onActivate={onActivate}
        />
      ) : view === "raw" && scan ? (
        <>
          <MassSpectrum
            key="raw"
            showCounts
            onIonSelect={onIonSelect}
            ionMz={ionMz}
            ionTolerance={ionTolerance}
            series={[
              {
                id: `scan-${scan.scan_index}`,
                label: "Acquired ions · native m/z",
                spectrum: scan.spectrum,
              },
            ]}
            massRange={massRange}
          />
          <p className="raw-scan-note">
            Total ion count{" "}
            {scan.spectrum.intensity
              .reduce((sum, value) => sum + value, 0)
              .toLocaleString()}{" "}
            · No background subtraction
          </p>
        </>
      ) : view === "library" && detail ? (
        <MassSpectrum
          key="library"
          series={[
            {
              id: activeId,
              label: "Component",
              spectrum: detail.component.spectrum,
            },
            ...(candidate
              ? [
                  {
                    id: candidate.group_id,
                    label: "Library reference",
                    spectrum: candidate.reference_spectrum,
                  },
                ]
              : []),
          ]}
          mirrored={!!candidate}
          massRange={massRange}
        />
      ) : (
        <div className="panel-state">
          <p>Choose a detected component to see its spectrum.</p>
        </div>
      )}
    </section>
  );
}
