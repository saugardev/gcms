export const assignments: Record<string, string> = {
  tentative:
    "One clear leading library match; chemical identity still needs confirmation.",
  ambiguous:
    "Several candidates match similarly, or the reference has conflicting identities.",
  unassigned:
    "A component was detected, but its leading match did not pass screening or no candidate was available.",
};

export const stabilityLabels: Record<string, string> = {
  consistent:
    "All six processing variations found a matching component and retained the same leading reference group.",
  sensitive:
    "At least one processing variation changed the leading reference group or could no longer match the component.",
  inconclusive:
    "Incomplete checks or uncertain correspondence prevented a clear parameter sensitivity result.",
};

export function ResultLabel({
  value,
  kind,
}: {
  value: string;
  kind: "assignment" | "stability";
}) {
  const description = (kind === "assignment" ? assignments : stabilityLabels)[
    value
  ];
  return (
    <button
      type="button"
      className={`result-label ${kind}`}
      title={description}
      aria-label={`${kind === "assignment" ? "Identification status" : "Parameter sensitivity"}: ${value}. Show explanation`}
      popoverTarget="result-guide"
      onClick={(event) => event.stopPropagation()}
    >
      <span className="label-dot" aria-hidden="true" />
      {value}
    </button>
  );
}

export function ResultGuide() {
  return (
    <div
      id="result-guide"
      className="result-guide"
      popover="auto"
      aria-labelledby="guide-title"
    >
      <div className="guide-heading">
        <div>
          <h2 id="guide-title">Workspace guide</h2>
          <p>Identification status and parameter sensitivity for each component.</p>
        </div>
        <button
          popoverTarget="result-guide"
          popoverTargetAction="hide"
          aria-label="Close result explanations"
        >
          ×
        </button>
      </div>
      <div className="guide-columns">
        <section>
          <h3>Identification status</h3>
          <p>How clearly does the spectrum match a library identity?</p>
          <dl>
            {Object.entries(assignments).map(([label, description]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{description}</dd>
              </div>
            ))}
          </dl>
        </section>
        <section>
          <h3>Parameter sensitivity</h3>
          <p>Does the result persist when processing parameters change? This describes the analysis, not ion abundance or purity.</p>
          <dl>
            {Object.entries(stabilityLabels).map(([label, description]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{description}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
      <section className="selection-shortcuts">
        <h3>Selecting components</h3>
        <p>
          Click a row or peak to inspect it. Ctrl / ⌘-click adds or removes a
          component; Shift-click selects a range. Use checkboxes on touch
          screens.
        </p>
        <p>
          ↑ / ↓ moves through the table; Shift + ↑ / ↓ extends the selection.
          Ctrl / ⌘ + A selects the shown rows. Escape clears the selection.
          Multiple selected components appear as stacked spectra with a shared
          m/z axis. Click a spectrum or its heading to inspect its library search results.
        </p>
        <p>
          In Select mode, drag across the chromatogram to select peaks. Hold
          Ctrl / ⌘ or Shift to add a range. Switch to Zoom to magnify a region.
          Scan mode shows the raw acquisition spectrum at any time. Use the scan
          arrows or enter a retention time to move precisely.
        </p>
        <p>
          Click an ion in the raw spectrum, or enter its m/z, to show its
          chromatogram. Adjust the ± mass tolerance beside the trace; hide Raw
          TIC to focus on the ion signal. Selecting an ion keeps the active
          component and its candidates unchanged.
        </p>
      </section>
      <p className="guide-note">
        Drag within a mass spectrum to zoom the shared m/z range. Each spectrum
        shows relative abundance (%) with its own base peak (strongest ion) at 100%.
        These percentages do not measure sample composition. Scan spectra retain acquired masses
        and include background; component spectra are reconstructed by the saved
        analysis.
      </p>
      <p className="guide-note">
        A consistent result can still have an ambiguous identity. These are
        saved screening results, not confirmed identifications.
      </p>
    </div>
  );
}
