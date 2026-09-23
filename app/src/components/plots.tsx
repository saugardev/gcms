"use client";

import { useEffect, useId, useRef, useState } from "react";
import type {
  Analysis,
  ComponentDetail,
  Peak,
  Spectrum,
} from "@/lib/api";
import {
  constrainRange,
  linePath,
  nearestIndex,
  ticks,
  type Range,
} from "@/lib/charts";

import type { SelectionOptions } from "@/lib/selection";

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(240, entry.contentRect.width)),
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

export function Chromatogram({
  analysis,
  selected,
  localTrace,
  selectedIds,
  onSelect,
  onSelectRange,
  onScan,
  scanTime,
}: {
  analysis: Analysis;
  selected?: Peak;
  localTrace?: NonNullable<ComponentDetail["review"]>["trace"];
  selectedIds: Set<string>;
  onSelect: (id: string, options?: SelectionOptions) => void;
  onSelectRange: (ids: string[], additive: boolean) => void;
  onScan: (time: number) => void;
  scanTime?: number;
}) {
  const { ref, width } = useWidth();
  const clip = useId();
  const overview = analysis.chromatogram;
  const chosenPeaks = analysis.peaks.filter((p) =>
    selectedIds.has(p.component_id),
  );
  const full: Range = [overview.time_seconds[0], overview.time_seconds.at(-1)!];
  const [range, setRange] = useState<Range>(full);
  const [fullStart, fullEnd] = full;
  useEffect(() => {
    if (scanTime === undefined) return;
    setRange((current) => {
      if (scanTime >= current[0] && scanTime <= current[1]) return current;
      const half = (current[1] - current[0]) / 2;
      return constrainRange(
        [scanTime - half, scanTime + half],
        [fullStart, fullEnd],
      );
    });
  }, [scanTime, fullStart, fullEnd]);
  const useLocal =
    localTrace &&
    localTrace.time_seconds.length > 1 &&
    range[0] >= localTrace.time_seconds[0] &&
    range[1] <= localTrace.time_seconds.at(-1)!;
  const trace = useLocal ? localTrace : overview;
  const rawTrace = analysis.raw_chromatogram ?? trace;
  const [mode, setMode] = useState<"select" | "zoom" | "scan">("select");
  const [raw, setRaw] = useState(true);
  const [corrected, setCorrected] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const [drag, setDrag] = useState<Range | null>(null);
  const origin = useRef<number | null>(null);
  const w = width - 66,
    h = 224,
    left = 53,
    top = 17;
  const span = range[1] - range[0];
  const x = (time: number) => ((time - range[0]) / span) * w;
  let maximum = 1;
  for (const [times, values, visible] of [
    [rawTrace.time_seconds, rawTrace.raw_tic, raw],
    [trace.time_seconds, trace.corrected_tic, corrected],
  ] as const) {
    if (!visible) continue;
    for (
      let i = Math.max(0, nearestIndex(times, range[0]) - 1);
      i < times.length && times[i] <= range[1];
      i++
    ) {
      maximum = Math.max(maximum, values[i]);
    }
  }
  const timeAt = (event: React.PointerEvent<SVGRectElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return (
      range[0] +
      Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) *
        span
    );
  };
  const zoom = (factor: number) => {
    const center = (range[0] + range[1]) / 2;
    const size = Math.max(2, span * factor);
    setRange(constrainRange([center - size / 2, center + size / 2], full));
  };
  const move = (direction: number) =>
    setRange(
      constrainRange(
        [range[0] + (direction * span) / 3, range[1] + (direction * span) / 3],
        full,
      ),
    );
  const hoverTimes =
    raw ? rawTrace.time_seconds : trace.time_seconds;
  const hoverValues = raw
    ? rawTrace.raw_tic
    : trace.corrected_tic;
  const hoveredIndex = hover === null ? -1 : nearestIndex(hoverTimes, hover);
  return (
    <section className="panel chromatogram-panel" aria-labelledby="tic-title">
      <div className="panel-heading">
        <div>
          <div className="card-title">
            <h2 id="tic-title">Total ion chromatogram</h2>
          </div>
          <p>
            {mode === "scan"
              ? "Click any time to inspect its raw scan"
              : `Click a peak · ${mode === "select" ? "Drag to select a range" : "Drag to zoom"}`}
          </p>
        </div>
        <div
          className="plot-mode"
          role="group"
          aria-label="Chromatogram drag mode"
        >
          <button
            aria-pressed={mode === "select"}
            onClick={() => setMode("select")}
          >
            Select
          </button>
          <button
            aria-pressed={mode === "zoom"}
            onClick={() => setMode("zoom")}
          >
            Zoom
          </button>
          <button
            aria-pressed={mode === "scan"}
            disabled={!analysis.raw_chromatogram}
            title={
              !analysis.raw_chromatogram
                ? "Raw acquisition has not been imported"
                : "Inspect individual acquisition scans"
            }
            onClick={() => {
              setMode("scan");
              onScan(selected?.apex_seconds ?? (range[0] + range[1]) / 2);
            }}
          >
            Scan
          </button>
        </div>
      </div>
      <div className="plot-toolbar">
        <div className="trace-controls">
          <label>
            <input
              type="checkbox"
              checked={raw}
              onChange={(e) => {
                setRaw(e.target.checked);
                if (!e.target.checked) setCorrected(true);
              }}
            />
            <span className="swatch measured" />
            Raw TIC
          </label>
          <label>
            <input
              type="checkbox"
              checked={corrected}
              onChange={(e) => {
                setCorrected(e.target.checked);
                if (!e.target.checked) setRaw(true);
              }}
            />
            <span className="swatch reference" />
            Corrected
          </label>
        </div>
        <div className="button-group">
          <button
            aria-label="Pan earlier"
            title="Pan earlier"
            disabled={range[0] <= full[0]}
            onClick={() => move(-1)}
          >
            ←
          </button>
          <button
            aria-label="Zoom in"
            title="Zoom in"
            disabled={span <= 2}
            onClick={() => zoom(0.5)}
          >
            +
          </button>
          <button
            aria-label="Zoom out"
            title="Zoom out"
            disabled={span >= full[1] - full[0]}
            onClick={() => zoom(2)}
          >
            −
          </button>
          <button
            aria-label="Pan later"
            title="Pan later"
            disabled={range[1] >= full[1]}
            onClick={() => move(1)}
          >
            →
          </button>
          <button onClick={() => setRange(full)}>Reset</button>
          <button
            disabled={!selected}
            onClick={() => {
              if (chosenPeaks.length > 1) {
                const start = Math.min(
                  ...chosenPeaks.map((p) => p.start_seconds),
                );
                const end = Math.max(...chosenPeaks.map((p) => p.end_seconds));
                const padding = Math.max(2, (end - start) * 0.1);
                setRange(
                  constrainRange([start - padding, end + padding], full),
                );
              } else if (localTrace && localTrace.time_seconds.length > 1) {
                setRange(
                  constrainRange(
                    [
                      localTrace.time_seconds[0],
                      localTrace.time_seconds.at(-1)!,
                    ],
                    full,
                  ),
                );
              } else if (selected) {
                const padding = Math.max(
                  2,
                  selected.end_seconds - selected.start_seconds,
                );
                setRange(
                  constrainRange(
                    [
                      selected.start_seconds - padding,
                      selected.end_seconds + padding,
                    ],
                    full,
                  ),
                );
              }
            }}
          >
            {chosenPeaks.length > 1 ? "Focus selection" : "Focus peak"}
          </button>
        </div>
      </div>
      <div className="plot" ref={ref}>
        <svg
          width={width}
          height={h + 62}
          role="img"
          aria-label="Total ion chromatogram. Select a component using the peak table or click near its retention time."
        >
          <defs>
            <clipPath id={clip}>
              <rect width={w} height={h} />
            </clipPath>
          </defs>
          <g transform={`translate(${left},${top})`}>
            {[0, 0.5, 1].map((v) => (
              <g key={v}>
                <line
                  className="grid-line"
                  x2={w}
                  y1={h * (1 - v)}
                  y2={h * (1 - v)}
                />
                <text
                  className="axis-text"
                  x={-7}
                  y={h * (1 - v) + 4}
                  textAnchor="end"
                >
                  {(maximum * v).toExponential(1)}
                </text>
              </g>
            ))}
            {ticks(range).map((t) => (
              <g key={t}>
                <line
                  className="axis-line"
                  x1={x(t)}
                  x2={x(t)}
                  y1={h}
                  y2={h + 4}
                />
                <text
                  className="axis-text"
                  x={x(t)}
                  y={h + 19}
                  textAnchor="middle"
                >
                  {(t / 60).toFixed(span < 60 ? 2 : 1)}
                </text>
              </g>
            ))}
            <g clipPath={`url(#${clip})`}>
              {chosenPeaks.map((p) => (
                <g key={p.component_id}>
                  <rect
                    className="selection-band"
                    x={x(p.start_seconds)}
                    width={Math.max(2, x(p.end_seconds) - x(p.start_seconds))}
                    height={h}
                  />
                  <line
                    className={
                      p.component_id === selected?.component_id
                        ? "active-peak-line"
                        : "selection-line"
                    }
                    x1={x(p.apex_seconds)}
                    x2={x(p.apex_seconds)}
                    y2={h}
                  />
                </g>
              ))}
              {raw && (
                <path
                  className="measured-line"
                  d={linePath(
                    rawTrace.time_seconds,
                    rawTrace.raw_tic,
                    range,
                    w,
                    h,
                    maximum,
                  )}
                />
              )}
              {corrected && (
                <path
                  className="reference-line"
                  d={linePath(
                    trace.time_seconds,
                    trace.corrected_tic,
                    range,
                    w,
                    h,
                    maximum,
                  )}
                />
              )}
              {scanTime !== undefined && (
                <line
                  className="scan-line"
                  x1={x(scanTime)}
                  x2={x(scanTime)}
                  y2={h}
                />
              )}
              {drag && (
                <rect
                  className="selection-band"
                  x={x(Math.min(...drag))}
                  width={Math.abs(x(drag[1]) - x(drag[0]))}
                  height={h}
                />
              )}
            </g>
            <rect
              className="plot-target"
              width={w}
              height={h}
              fill="transparent"
              onPointerDown={(event) => {
                if (event.button !== 0) return;
                event.currentTarget.setPointerCapture(event.pointerId);
                origin.current = timeAt(event);
                setDrag([origin.current, origin.current]);
              }}
              onPointerMove={(event) => {
                const time = timeAt(event);
                setHover(time);
                if (origin.current !== null) setDrag([origin.current, time]);
              }}
              onPointerUp={(event) => {
                if (origin.current === null) return;
                const start = origin.current,
                  end = timeAt(event);
                origin.current = null;
                setDrag(null);
                if (mode === "scan") {
                  onScan(end);
                } else if ((Math.abs(end - start) / span) * w > 8) {
                  if (mode === "select") {
                    const ids = analysis.peaks
                      .filter(
                        (p) =>
                          p.apex_seconds >= Math.min(start, end) &&
                          p.apex_seconds <= Math.max(start, end),
                      )
                      .map((p) => p.component_id);
                    onSelectRange(
                      ids,
                      event.metaKey || event.ctrlKey || event.shiftKey,
                    );
                  } else {
                    const center = (start + end) / 2,
                      size = Math.max(2, Math.abs(end - start));
                    setRange(
                      constrainRange(
                        [center - size / 2, center + size / 2],
                        full,
                      ),
                    );
                  }
                } else {
                  const index = nearestIndex(
                    analysis.peaks.map((p) => p.apex_seconds),
                    end,
                  );
                  if (index >= 0)
                    onSelect(analysis.peaks[index].component_id, {
                      toggle: event.metaKey || event.ctrlKey,
                      range: event.shiftKey,
                    });
                }
              }}
              onPointerCancel={() => {
                origin.current = null;
                setDrag(null);
              }}
              onPointerLeave={() => setHover(null)}
            />
            <text
              className="axis-text"
              x={w / 2}
              y={h + 39}
              textAnchor="middle"
            >
              Retention time (min)
            </text>
          </g>
        </svg>
      </div>
      <div className="plot-caption">
        <span>
          {hoveredIndex >= 0
            ? `${(hoverTimes[hoveredIndex] / 60).toFixed(3)} min · ${(hoverValues[hoveredIndex] ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })} counts`
            : `Intensity · maximum ${maximum.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
        </span>
        <span>
          {raw && analysis.raw_chromatogram
            ? corrected
              ? "Full raw · saved corrected"
              : "Full raw trace"
            : useLocal
              ? "Saved peak trace"
              : overview.preview
                ? "Preview trace"
                : "Full trace"}
        </span>
      </div>
    </section>
  );
}

export type SpectrumSeries = { id: string; label: string; spectrum: Spectrum };

export function MassSpectrum({
  series,
  massRange,
  mirrored = false,
  showCounts = false,
  activeId,
  onActivate,
}: {
  series: SpectrumSeries[];
  massRange: Range;
  mirrored?: boolean;
  showCounts?: boolean;
  activeId?: string;
  onActivate?: (id: string) => void;
}) {
  const { ref, width } = useWidth();
  const clip = useId();
  const [requested, setRange] = useState<Range | null>(null);
  const [hover, setHover] = useState<{ mz: number; id: string } | null>(null);
  const [drag, setDrag] = useState<Range | null>(null);
  const origin = useRef<number | null>(null);
  const full: Range = [...massRange];
  for (const item of series) {
    if (item.spectrum.mz.length) {
      full[0] = Math.min(full[0], item.spectrum.mz[0]);
      full[1] = Math.max(full[1], item.spectrum.mz.at(-1)!);
    }
  }
  if (full[0] === full[1]) full[1]++;
  const range = requested ? constrainRange(requested, full) : full;
  const span = range[1] - range[0];
  const w = width - 62,
    left = 46;
  const x = (mz: number) => ((mz - range[0]) / span) * w;
  const valueAt = (event: React.PointerEvent<SVGRectElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return (
      range[0] +
      Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) *
        span
    );
  };
  const zoom = (factor: number) => {
    const center = (range[0] + range[1]) / 2,
      size = Math.max(1, span * factor);
    setRange(constrainRange([center - size / 2, center + size / 2], full));
  };
  const pan = (direction: number) =>
    setRange(
      constrainRange(
        [range[0] + (direction * span) / 3, range[1] + (direction * span) / 3],
        full,
      ),
    );
  const hovered = series.find((item) => item.id === hover?.id);
  const ion =
    hovered && hover ? nearestIndex(hovered.spectrum.mz, hover.mz) : -1;

  function plot(items: SpectrumSeries[], mirror: boolean) {
    const h = mirror ? 80 : series.length === 1 ? 90 : 44,
      baseline = mirror ? 100 : series.length === 1 ? 108 : 62;
    const bottom = mirror ? baseline + h : baseline;
    const plotId = `${clip}-${items[0].id}`;
    return (
      <svg
        width={width}
        height={bottom + 36}
        role="img"
        aria-label={`${items.map((i) => i.label).join(" versus ")} mass spectrum. Drag to zoom m/z.`}
      >
        <defs>
          <clipPath id={plotId}>
            <rect width={w} y={12} height={bottom - 12} />
          </clipPath>
        </defs>
        <g transform={`translate(${left},0)`}>
          {(mirror ? [-1, 0, 1] : [-1, 0]).map((v) => (
            <g key={v}>
              <line
                className="grid-line"
                x2={w}
                y1={baseline + v * h}
                y2={baseline + v * h}
              />
              <text
                className="axis-text"
                x={-8}
                y={baseline + v * h + 3}
                textAnchor="end"
              >
                {Math.abs(v) * 100}
              </text>
            </g>
          ))}
          <g clipPath={`url(#${plotId})`}>
            {items.map((item, itemIndex) => {
              const max = Math.max(1, ...item.spectrum.intensity);
              const direction = mirror && itemIndex === 1 ? 1 : -1;
              return (
                <g key={item.id}>
                  {item.spectrum.mz.map(
                    (mz, i) =>
                      mz >= range[0] &&
                      mz <= range[1] && (
                        <line
                          key={mz}
                          className={
                            mirror && itemIndex === 1
                              ? "reference-line"
                              : "measured-line"
                          }
                          x1={x(mz)}
                          x2={x(mz)}
                          y1={baseline}
                          y2={
                            baseline +
                            ((direction * item.spectrum.intensity[i]) / max) * h
                          }
                        />
                      ),
                  )}
                </g>
              );
            })}
            {hover && (
              <line
                className="crosshair"
                x1={x(hover.mz)}
                x2={x(hover.mz)}
                y1={12}
                y2={bottom}
              />
            )}
            {drag && (
              <rect
                className="selection-band"
                x={x(Math.min(...drag))}
                y={12}
                width={Math.abs(x(drag[1]) - x(drag[0]))}
                height={bottom - 12}
              />
            )}
          </g>
          {items.slice(0, 1).flatMap((item) => {
            const max = Math.max(1, ...item.spectrum.intensity);
            const labeled: number[] = [];
            return item.spectrum.mz
              .map((mz, i) => ({ mz, value: item.spectrum.intensity[i] }))
              .filter((ion) => ion.mz >= range[0] && ion.mz <= range[1])
              .sort((a, b) => b.value - a.value)
              .slice(0, 5)
              .map((ion) => {
                if (labeled.some((mz) => Math.abs(x(mz) - x(ion.mz)) < 30))
                  return null;
                labeled.push(ion.mz);
                return (
                  <text
                    key={ion.mz}
                    className="ion-label"
                    x={x(ion.mz)}
                    y={baseline - (ion.value / max) * h - 5}
                    textAnchor="middle"
                  >
                    {Number(ion.mz.toFixed(2))}
                  </text>
                );
              });
          })}
          {ticks(range).map((mz) => (
            <text
              key={mz}
              className="axis-text"
              x={x(mz)}
              y={bottom + 17}
              textAnchor="middle"
            >
              {Number(mz.toFixed(span < 10 ? 2 : 0))}
            </text>
          ))}
          <text
            className="axis-text"
            x={w / 2}
            y={bottom + 32}
            textAnchor="middle"
          >
            m/z
          </text>
          <rect
            className="plot-target"
            fill="transparent"
            width={w}
            y={12}
            height={bottom - 12}
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              event.currentTarget.setPointerCapture(event.pointerId);
              origin.current = valueAt(event);
              setDrag([origin.current, origin.current]);
            }}
            onPointerMove={(event) => {
              const mz = valueAt(event);
              setHover({
                mz,
                id:
                  items[
                    mirror &&
                    event.clientY >
                      event.currentTarget.getBoundingClientRect().top +
                        baseline -
                        12
                      ? 1
                      : 0
                  ]?.id ?? items[0].id,
              });
              if (origin.current !== null) setDrag([origin.current, mz]);
            }}
            onPointerUp={(event) => {
              if (origin.current === null) return;
              const start = origin.current,
                end = valueAt(event);
              origin.current = null;
              setDrag(null);
              if ((Math.abs(end - start) / span) * w > 8) {
                const center = (start + end) / 2,
                  size = Math.max(1, Math.abs(end - start));
                setRange(
                  constrainRange([center - size / 2, center + size / 2], full),
                );
              } else if (onActivate) {
                onActivate(items[0].id);
              }
            }}
            onPointerCancel={() => {
              origin.current = null;
              setDrag(null);
            }}
            onPointerLeave={() => setHover(null)}
            onDoubleClick={() => setRange(null)}
          />
        </g>
      </svg>
    );
  }
  return (
    <>
      <div className="spectrum-tools">
        <div className="button-group">
          <button
            aria-label="Pan spectrum to lower masses"
            disabled={range[0] <= full[0]}
            onClick={() => pan(-1)}
          >
            ←
          </button>
          <button
            aria-label="Zoom spectrum in"
            disabled={span <= 1}
            onClick={() => zoom(0.5)}
          >
            +
          </button>
          <button
            aria-label="Zoom spectrum out"
            disabled={span >= full[1] - full[0]}
            onClick={() => zoom(2)}
          >
            −
          </button>
          <button
            aria-label="Pan spectrum to higher masses"
            disabled={range[1] >= full[1]}
            onClick={() => pan(1)}
          >
            →
          </button>
          <button onClick={() => setRange(null)}>Reset m/z</button>
        </div>
        <span>Drag to zoom · Relative %</span>
      </div>
      <div className="spectrum-scroll" ref={ref}>
        {mirrored ? (
          <>
            <div className="spectrum-legend">
              {series.map((item, i) => (
                <span key={item.id}>
                  <i
                    className={`swatch ${i === 1 ? "reference" : "measured"}`}
                  />
                  {item.label}
                </span>
              ))}
            </div>
            {plot(series, true)}
          </>
        ) : (
          series.map((item) => (
            <div
              className="spectrum-lane"
              key={item.id}
              data-active={item.id === activeId}
            >
              {onActivate ? (
                <button
                  className="spectrum-lane-title"
                  aria-pressed={item.id === activeId}
                  onClick={() => onActivate(item.id)}
                >
                  {item.label}
                  {item.id === activeId ? " · Active" : ""}
                </button>
              ) : (
                <div className="spectrum-lane-title">{item.label}</div>
              )}
              {plot([item], false)}
            </div>
          ))
        )}
      </div>
      <div className="plot-caption spectrum-caption" aria-live="off">
        {hovered && ion >= 0
          ? `m/z ${hovered.spectrum.mz[ion].toFixed(2)}${showCounts ? ` · ${hovered.spectrum.intensity[ion].toLocaleString()} counts` : ""} · ${((hovered.spectrum.intensity[ion] / Math.max(1, ...hovered.spectrum.intensity)) * 100).toFixed(1)}%`
          : `${range[0].toFixed(1)}–${range[1].toFixed(1)} m/z · Each spectrum normalized independently`}
      </div>
    </>
  );
}
