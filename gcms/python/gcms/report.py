"""Self-contained, accessible HTML/SVG report. No remote scripts or assets."""

from html import escape

from .models import AnalysisReport

_INTERACTIONS = """
const controls = document.getElementById('component-controls');
const search = document.getElementById('component-search');
const statusFilter = document.getElementById('component-status');
const stabilityFilter = document.getElementById('component-stability');
const body = document.querySelector('#components tbody');
const evidence = document.getElementById('component-evidence');
const rows = [...body.rows].map(row => ({
  row, detail: document.getElementById(row.dataset.component),
  marker: document.querySelector(`svg a[href="#${row.dataset.component}"]`)
}));
const headers = [...document.querySelectorAll('#components th')];
const pageSelect = document.getElementById('component-page');
const pageSize = 10;
let sortKey = 'component', direction = 1, page = 1, selected = '', matches = [], printing = false;

function update() {
  const query = search.value.trim().toLowerCase();
  rows.sort((a, b) => {
    const x = a.row.dataset[sortKey], y = b.row.dataset[sortKey];
    // Missing similarities stay last in either direction.
    const tie = a.row.dataset.component.localeCompare(b.row.dataset.component);
    if (x === '' || y === '') return (x === '') - (y === '') || tie;
    const order = ['apex', 'score', 'area'].includes(sortKey)
      ? Number(x) - Number(y) : x.localeCompare(y, undefined, {numeric: true, sensitivity: 'base'});
    return direction * order || tie;
  });
  matches = rows.filter(({row}) => row.dataset.search.toLowerCase().includes(query)
      && (!statusFilter.value || row.dataset.status === statusFilter.value)
      && (!stabilityFilter?.value || row.dataset.stability === stabilityFilter.value));
  const pages = Math.max(1, Math.ceil(matches.length / pageSize));
  page = Math.max(1, Math.min(page, pages));
  const start = (page - 1) * pageSize;
  const onPage = new Set(matches.slice(start, start + pageSize));
  const matching = new Set(matches);
  if (!matches.some(item => onPage.has(item) && item.row.dataset.component === selected)) selected = '';
  for (const item of rows) {
    const {row, detail, marker} = item;
    row.hidden = printing ? !matching.has(item) : !onPage.has(item);
    detail.hidden = printing ? !matching.has(item) : row.hidden || row.dataset.component !== selected;
    row.classList.toggle('active-row', row.dataset.component === selected);
    row.querySelector('a').setAttribute('aria-current', row.dataset.component === selected ? 'true' : 'false');
    marker.style.display = matching.has(item) ? '' : 'none';
    body.append(row);
    evidence.append(detail);
  }
  document.getElementById('component-count').textContent = printing ? `Showing all ${matches.length} matching components` : matches.length
    ? `Showing ${start + 1}–${Math.min(start + pageSize, matches.length)} of ${matches.length} components${matches.length !== rows.length ? ` (${rows.length} total)` : ''}`
    : `No matching components (${rows.length} total)`;
  document.getElementById('component-empty').hidden = matches.length !== 0;
  document.getElementById('evidence-hint').hidden = !!selected || printing || !rows.length;
  if (pageSelect.options.length !== pages) {
    pageSelect.replaceChildren(...Array.from({length: pages}, (_, i) => new Option(String(i + 1), String(i + 1))));
  }
  pageSelect.value = String(page);
  pageSelect.disabled = pages === 1;
  document.getElementById('page-total').textContent = `of ${pages}`;
  for (const button of document.querySelectorAll('[data-page]')) {
    button.disabled = ['first', 'previous'].includes(button.dataset.page) ? page === 1 : page === pages;
  }
  for (const header of headers) {
    header.setAttribute('aria-sort', header.dataset.sort === sortKey
      ? (direction === 1 ? 'ascending' : 'descending') : 'none');
  }
}
function resetFilters() {
  search.value = statusFilter.value = '';
  if (stabilityFilter) stabilityFilter.value = '';
}
controls.addEventListener('input', () => { page = 1; selected = ''; update(); });
controls.addEventListener('submit', event => event.preventDefault());
document.getElementById('component-reset').addEventListener('click', () => {
  resetFilters(); sortKey = 'component'; direction = 1; page = 1; selected = ''; update();
});
function changePage(value) { page = value; selected = ''; update(); }
pageSelect.addEventListener('change', () => changePage(Number(pageSelect.value)));
for (const button of document.querySelectorAll('[data-page]')) {
  button.addEventListener('click', () => changePage({
    first: 1, previous: page - 1, next: page + 1, last: Math.ceil(matches.length / pageSize)
  }[button.dataset.page]));
}
for (const header of headers) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = header.textContent;
  button.title = `Sort by ${header.textContent}`;
  button.addEventListener('click', () => {
    direction = sortKey === header.dataset.sort ? -direction : 1;
    sortKey = header.dataset.sort;
    page = 1; selected = '';
    update();
  });
  header.replaceChildren(button);
}
function reveal() {
  const node = document.getElementById(location.hash.slice(1));
  if (node?.parentElement === evidence) {
    if (!matches.some(item => item.detail === node)) { resetFilters(); update(); }
    page = Math.floor(matches.findIndex(item => item.detail === node) / pageSize) + 1;
    selected = node.id;
    update();
    node.open = true;
    node.scrollIntoView();
    node.querySelector('summary').focus({preventScroll: true});
  }
}
controls.hidden = false;
document.getElementById('component-pagination').hidden = false;
update();
// Printed packets retain every matching component, including later pages.
window.addEventListener('beforeprint', () => { printing = true; update(); });
window.addEventListener('afterprint', () => { printing = false; update(); });
window.addEventListener('hashchange', reveal);
document.addEventListener('click', event => {
  if (event.target.closest('a')?.getAttribute('href') === location.hash) reveal();
});
reveal();
"""


def _path(x, y, x0, x1, y_max, width=1000, height=240):
    return " ".join(
        f"{'M' if i == 0 else 'L'}{55 + (a - x0) / (x1 - x0) * (width - 80):.2f},"
        f"{height - 35 - b / max(y_max, 1) * (height - 60):.2f}"
        for i, (a, b) in enumerate(zip(x, y))
    )


def _chromatogram(report, components=None):
    c = report.chromatogram
    x, raw, corrected = c["time_seconds"], c["raw_tic"], c["corrected_tic"]
    top = max(raw)
    ticks = "".join(
        f'<text x="{55 + i * 184}" y="230" text-anchor="middle">'
        f"{(x[0] + (x[-1] - x[0]) * i / 5) / 60:.1f}</text>"
        for i in range(6)
    )
    markers = "".join(
        f'<a href="#{p.component_id}" aria-label="Inspect {p.component_id}">'
        f'<circle cx="{55 + (p.apex_seconds - x[0]) / (x[-1] - x[0]) * 920:.2f}" '
        f'cy="{205 - corrected[x.index(p.apex_seconds)] / max(top, 1) * 180:.2f}" r="3">'
        f"<title>{escape(p.component_id)} · {p.apex_seconds / 60:.3f} min</title></circle></a>"
        for p in (report.components if components is None else components)
    )
    return (
        '<svg viewBox="0 0 1000 255" role="img" aria-label="Total ion chromatogram">'
        "<title>Total ion chromatogram: raw and baseline-corrected signal</title>"
        f'<text x="55" y="14">Intensity · maximum {top:,.0f}</text>'
        f'<path class="raw" d="{_path(x, raw, x[0], x[-1], top)}"/>'
        f'<path class="signal" d="{_path(x, corrected, x[0], x[-1], top)}"/>'
        f'{markers}{ticks}<text x="985" y="248" text-anchor="end">min</text></svg>'
    )


def _spectrum(component, mass_range):
    low, high = mass_range
    paths = []
    pairs = [(component.spectrum, -1, "signal")]
    if component.candidates:
        pairs.append((component.candidates[0].reference_spectrum, 1, "reference"))
    for spectrum, sign, style in pairs:
        maximum = max(spectrum.intensity, default=1)
        d = " ".join(
            f"M{55 + (m - low) / (high - low) * 920:.2f},110v{sign * intensity / maximum * 85:.2f}"
            for m, intensity in zip(spectrum.mz, spectrum.intensity)
        )
        paths.append(f'<path class="{style}" d="{d}"/>')
    ticks = "".join(
        f'<text x="{55 + i * 184}" y="220" text-anchor="middle">'
        f"{low + (high - low) * i / 5:.0f}</text>"
        for i in range(6)
    )
    return (
        '<svg viewBox="0 0 1000 235" role="img" aria-label="Measured and reference mass spectra">'
        "<title>Mirror plot: measured spectrum above, top candidate reference below; "
        "each normalized to its own maximum</title>"
        '<path class="axis" d="M55,110H975"/>'
        + "".join(paths)
        + ticks
        + '<text x="985" y="232" text-anchor="end">m/z</text></svg>'
    )


def _local_evidence(p, annotation):
    trace = annotation.trace
    x = trace.time_seconds
    high = max(max(trace.raw_tic), max(trace.corrected_tic), max(trace.component_ion_sum))

    def position(seconds):
        return 55 + (seconds - x[0]) / (x[-1] - x[0]) * 920

    band = f'<rect x="{position(p.start_seconds):.2f}" y="22" width="{position(p.end_seconds) - position(p.start_seconds):.2f}" height="183" fill="#dcefe9"/>'
    apex = f'<path class="apex" d="M{position(p.apex_seconds):.2f},22V205"/>'
    ticks = "".join(
        f'<text x="{55 + i * 230}" y="230" text-anchor="middle">{(x[0] + (x[-1] - x[0]) * i / 4) / 60:.3f}</text>'
        for i in range(5)
    )
    chromatogram = (
        '<h3>Peak window and integration</h3><svg viewBox="0 0 1000 255" role="img" aria-label="Local chromatogram with integration boundaries">'
        "<title>Raw TIC, corrected TIC and selected-ion sum; shaded integration interval and dashed apex</title>"
        + band
        + apex
        + f'<text x="55" y="14">Intensity · maximum {high:,.0f}</text>'
        + f'<path class="raw" d="{_path(x, trace.raw_tic, x[0], x[-1], high)}"/>'
        + f'<path class="signal" d="{_path(x, trace.corrected_tic, x[0], x[-1], high)}"/>'
        + f'<path class="selected" d="{_path(x, trace.component_ion_sum, x[0], x[-1], high)}"/>'
        + ticks
        + '<text x="985" y="248" text-anchor="end">min</text></svg>'
        '<p class="legend">Gray: raw TIC · Teal: corrected TIC · Purple: selected-ion sum used for this component’s area. Shading marks its integration interval.</p>'
    )
    colors = ["#087e8b", "#b95739", "#7652a3", "#3b6ba5", "#7c751b"]
    lines, legends = [], []
    for ion, color in zip(trace.ions, colors):
        maximum = max(ion.intensity, default=0)
        scaled = [v / maximum if maximum else 0 for v in ion.intensity]
        lines.append(f'<path style="stroke:{color}" d="{_path(x, scaled, x[0], x[-1], 1)}"/>')
        legends.append(f'<span style="color:{color}">m/z {ion.mz:g}</span>')
    ions = (
        '<h3>Strongest selected ion traces</h3><svg viewBox="0 0 1000 255" role="img" aria-label="Individual ion traces normalized separately">'
        "<title>Up to five strongest selected ions, each scaled to its own maximum; trace shape comparison</title>"
        + band
        + apex
        + '<text x="55" y="14">Each ion’s own maximum = 100%</text>'
        + "".join(lines)
        + ticks
        + '<text x="985" y="248" text-anchor="end">min</text></svg>'
        '<p class="legend">'
        + " · ".join(legends)
        + ". Each trace is normalized separately to compare timing and shape, not abundance.</p>"
    )
    preview = (
        '<p class="muted">Local plot is downsampled; boundaries and extrema are retained.</p>'
        if trace.preview
        else ""
    )
    return chromatogram + ions + preview


def _stability_evidence(annotation):
    rows = []
    for r in annotation.observations:
        outcome = {
            "matched": "Unique match",
            "not_matched": "No compatible match",
            "ambiguous": f"Ambiguous correspondence ({r.eligible_components} eligible)",
            "not_evaluated": "Not evaluated",
        }[r.outcome]
        candidate = " / ".join(r.top_names) or "—"
        change = (
            "same group"
            if r.same_top_group is True
            else "changed group"
            if r.same_top_group is False
            else "—"
        )
        shift = f"{r.apex_seconds / 60:.3f}" if r.apex_seconds is not None else "—"
        similarity = f"{r.spectral_similarity:.3f}" if r.spectral_similarity is not None else "—"
        rows.append(
            f"<tr><td>{escape(r.profile.replace('_', ' '))}</td><td>{outcome}</td><td>{shift}</td><td>{similarity}</td><td>{escape(candidate)}<small>{change}</small></td></tr>"
        )
    area = (
        f"Matched-profile areas are {annotation.min_area_ratio:.2f}–{annotation.max_area_ratio:.2f} times the baseline area."
        if annotation.min_area_ratio is not None
        else "No uniquely matched alternative areas are available."
    )
    return (
        f'<h3>Stability: <span class="badge {annotation.label}">{annotation.label}</span></h3>'
        f"<p>{annotation.matched_profiles}/{annotation.evaluated_profiles} completed alternatives uniquely match this peak; "
        f"{annotation.same_top_group_profiles} retain the same top reference group. {area}</p>"
        '<p class="muted">An absent compatible match can mean changed detection or changed spectrum. Ambiguous matches are not counted as confirmed persistence.</p>'
        '<div class="table-wrap"><table><thead><tr><th>Profile</th><th>Correspondence</th><th>Apex, min</th><th>Spectral agreement</th><th>Top candidate</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _review_overview(review, packet_only):
    links = " · ".join(
        f'<a href="#{cid}">{cid.removeprefix("component-")}</a>' for cid in review.review_packet
    )
    rows = "".join(
        f"<tr><td>{escape(v.name.replace('_', ' '))}</td><td>{escape(v.state)}</td>"
        f"<td>{v.component_count if v.component_count is not None else '—'}</td>"
        f"<td>{v.unmatched_variant_components if v.unmatched_variant_components is not None else '—'}</td>"
        f"<td>{escape(v.reason or '')}</td></tr>"
        for v in review.variants
    )
    settings = "".join(
        f"<details><summary>{escape(v.name.replace('_', ' '))} settings</summary><pre>{escape(str(v.parameters))}</pre></details>"
        for v in review.variants
    )
    mode = (
        f"This packet shows {len(review.review_packet)} selected examples from {len(review.analysis.components)} baseline detections."
        if packet_only
        else "Each baseline detection has a local peak plot and a cross-profile stability check."
    )
    labels = " · ".join(f"{n} {label}" for label, n in review.summary["labels"].items())
    return (
        "<section><h2>Review and stability</h2>"
        + f"<p>{mode}</p><p><strong>{escape(labels)}</strong></p>"
        "<p>Consistent: unique matches and the same top reference group across all six alternatives. "
        "Sensitive: at least one alternative has no compatible match or changes the top group. "
        "Inconclusive: the remaining cases, including uncertain correspondence or incomplete evaluation.</p>"
        '<p class="warnings">These labels describe sensitivity to settings, not identification confidence.</p>'
        f"<p>Analyst review packet: {links}. Selection is illustrative, not a representative accuracy test. All examples remain unreviewed.</p>"
        '<div class="table-wrap"><table><thead><tr><th>Profile</th><th>State</th><th>Detections</th><th>Not uniquely linked to baseline</th><th>Reason</th></tr></thead><tbody>'
        + rows
        + "</tbody></table></div><details><summary>Exact tested settings</summary>"
        + settings
        + "</details></section>"
    )


def render_report(report: AnalysisReport, *, review=None, packet_only=False) -> str:
    rows, details = [], []
    components = [
        p
        for p in report.components
        if not packet_only or (review and p.component_id in review.review_packet)
    ]
    for p in components:
        annotation = review.annotations[p.component_id] if review else None
        stability_cell = (
            f'<td><span class="badge {annotation.label}">{annotation.label}</span><small>{annotation.matched_profiles}/{annotation.evaluated_profiles} matched</small></td>'
            if annotation
            else ""
        )
        names = (
            " / ".join(dict.fromkeys(i.name for i in p.candidates[0].identities))
            if p.candidates
            else "No candidate"
        )
        score = f"{p.candidates[0].score:.3f}" if p.candidates else "—"
        searchable = " ".join(
            [p.component_id]
            + [value for c in p.candidates for i in c.identities for value in (i.name, i.cas or "")]
        )
        attributes = {
            "component": p.component_id,
            "search": searchable,
            "apex": p.apex_seconds,
            "names": names,
            "score": p.candidates[0].score if p.candidates else "",
            "area": p.area_percent,
            "status": p.status,
            "stability": annotation.label if annotation else "",
        }
        row_data = " ".join(
            f'data-{key}="{escape(str(value))}"' for key, value in attributes.items()
        )
        rows.append(
            f'<tr {row_data}><td><a href="#{p.component_id}">{p.component_id.removeprefix("component-")}</a></td>'
            f'<td>{p.apex_seconds / 60:.3f}</td><td class="names"><span title="{escape(names)}">{escape(names)}</span></td>'
            f'<td>{score}</td><td>{p.area_percent:.2f}</td><td><span class="badge {p.status}">'
            f"{p.status}</span></td>{stability_cell}</tr>"
        )
        candidates = "".join(
            "<tr><td>"
            + "<br>".join(
                f"{escape(i.name)} <small>CAS {escape(i.cas or 'unspecified')} · "
                f"{escape(i.source or 'unspecified')} · {escape(i.entry_id)}</small>"
                for i in c.identities
            )
            + f"</td><td>{c.score:.4f}</td><td>{100 * c.library_intensity_fraction_in_mass_range:.1f}%</td></tr>"
            for c in p.candidates
        )
        warnings = "".join(f"<li>{escape(w.replace('_', ' '))}</li>" for w in p.warnings)
        margin = f"{p.score_margin:.4f}" if p.score_margin is not None else "not available"
        review_evidence = (
            (_stability_evidence(annotation) + _local_evidence(p, annotation)) if annotation else ""
        )
        if annotation and annotation.selection_reasons:
            review_evidence = (
                "<p><strong>Selected for review:</strong> "
                + escape("; ".join(annotation.selection_reasons))
                + ". Review status: unreviewed.</p>"
                + review_evidence
            )
        candidate_notes = ""
        if annotation and p.candidates:
            q = p.candidates[0]
            observed = set(p.spectrum.mz)
            shared = sorted(observed & set(q.reference_spectrum.mz))
            missing = sorted(
                zip(q.reference_spectrum.mz, q.reference_spectrum.intensity),
                key=lambda pair: (-pair[1], pair[0]),
            )
            missing = [mass for mass, _ in missing if mass not in observed][:3]
            candidate_notes = f"<p>Top reference shares {len(shared)}/{len(observed)} extracted ions. Strong reference ions absent from the extracted spectrum: {', '.join(f'{v:g}' for v in missing) or 'none'}. This does not establish that those ions are absent from the raw sample.</p>"
        details.append(
            f'<details id="{p.component_id}"{" open" if packet_only else ""}><summary>{p.apex_seconds / 60:.3f} min · '
            f'{escape(names)} <span class="badge {p.status}">{p.status}</span></summary>'
            f'<div class="detail"><p>Integration: {p.start_seconds / 60:.3f}–{p.end_seconds / 60:.3f} min. '
            f"Area: {p.area:,.0f} intensity·s, using {p.apexing_ion_count} apexing ions. "
            f"Score margin: {margin}. Close reference groups: {p.close_candidate_groups}.</p>"
            + (f'<ul class="warnings">{warnings}</ul>' if warnings else "")
            + review_evidence
            + candidate_notes
            + _spectrum(p, (report.acquisition["mz_min"], report.acquisition["mz_max"]))
            + '<p class="legend"><span>Measured ↑</span><span>Top reference ↓</span> '
            "Relative intensity, each spectrum normalized separately</p>"
            '<div class="table-wrap"><table><thead><tr><th>Candidate identities</th><th>Similarity</th>'
            "<th>Reference intensity in acquired range</th></tr></thead><tbody>"
            + candidates
            + "</tbody></table></div>"
            + (
                '<p class="review-notes">Analyst decision: ____________________ &nbsp; Identity: ____________________<br>Reviewer: ____________________ &nbsp; Notes: ________________________________________</p>'
                if packet_only
                else ""
            )
            + "</div></details>"
        )
    warnings = "".join(f"<li>{escape(w)}</li>" for w in report.warnings)
    settings = "".join(
        f"<tr><td>{escape(k)}</td><td>{v}</td></tr>"
        for k, v in report.parameters.model_dump().items()
    )
    stability_filter = (
        '<label>Stability<select id="component-stability"><option value="">All stability labels</option>'
        '<option value="consistent">Consistent</option><option value="sensitive">Sensitive</option>'
        '<option value="inconclusive">Inconclusive</option></select></label>'
        if review
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(report.sample_name)} — GC-MS screening report</title>
<style>
:root{{color-scheme:light;--ink:#1d343b;--muted:#526970;--signal:#087e8b;--reference:#b95739;--surface:#fff;--border:#dce4e2;--control:#738983;--soft:#edf5f3;--space:8px}}
*{{box-sizing:border-box}}body{{margin:0;background:#f4f6f5;color:var(--ink);font:14px/1.6 system-ui,sans-serif}}
main{{max-width:1280px;margin:24px auto;padding:0 24px}}h1{{font-size:28px;letter-spacing:-.8px;margin:4px 0;overflow-wrap:anywhere}}
h2{{font-size:20px;margin:0 0 12px}}p{{margin:8px 0}}small,.muted{{color:var(--muted)}}small{{display:block}}
.eyebrow{{text-transform:uppercase;letter-spacing:2px;font-size:12px;color:var(--signal)}}
section,.panel{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;margin:16px 0}}
.panel>section{{border:0;padding:16px 0 0;margin:0}}.panel>summary{{min-height:40px;align-content:center}}
.stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:24px 0}}.stats>div{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px}}.stats strong{{font-size:28px;display:block}}
.stats span{{color:var(--muted);font-size:13px}}a{{color:#086d79}}:focus-visible{{outline:3px solid #b95739;outline-offset:4px}}
[hidden]{{display:none!important}}.filters{{display:flex;flex-wrap:wrap;align-items:end;gap:12px;margin:18px 0}}
.filters label{{display:flex;flex-direction:column;gap:5px;font-size:12px;font-weight:600}}.filters .search{{flex:1;min-width:200px}}
input,select,button{{font:inherit;color:inherit}}.filters input,.filters select,.filters button,.pagination button,.pagination select{{font-size:14px;border:1px solid var(--control);border-radius:6px;padding:8px 12px;background:var(--surface);min-height:40px}}
button{{cursor:pointer}}button:disabled{{cursor:default;opacity:.45}}#components th button{{border:0;background:transparent;padding:8px 0;min-height:40px;text-align:left;font-weight:600}}
.pagination{{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:8px;margin-top:16px}}.pagination label{{display:flex;align-items:center;gap:8px}}.pagination .page-size{{margin-right:auto;color:var(--muted)}}
#components tbody tr:hover,#components .active-row{{background:var(--soft)}}#components td:first-child a{{display:inline-flex;align-items:center;min-width:40px;min-height:40px;font-weight:600}}#components td{{padding:8px 12px;vertical-align:middle}}#components th{{padding:0 12px}}#components{{min-width:760px}}
#components .names span{{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}#component-evidence summary{{overflow-wrap:anywhere}}
#components th button::after{{content:' ↕';white-space:nowrap}}#components th[aria-sort="ascending"] button::after{{content:' ↑'}}#components th[aria-sort="descending"] button::after{{content:' ↓'}}
#components th button:hover{{color:var(--signal)}}#component-empty{{padding:18px 0}}
.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}
th,td{{padding:12px 10px;border-bottom:1px solid #e6ecea;text-align:left;vertical-align:top}}th{{font-size:12px;color:var(--muted)}}
.names{{max-width:420px}}svg{{width:100%;height:auto;display:block}}svg text{{font:12px system-ui;fill:var(--muted)}}
svg path{{fill:none;stroke-width:1.2}}.raw{{stroke:#a2afb2}}.signal{{stroke:var(--signal)}}.reference{{stroke:var(--reference)}}
.axis{{stroke:#c6d2d0}}circle{{fill:var(--reference)}}circle:hover{{r:6}}.legend{{font-size:12px;color:var(--muted)}}
.legend span:first-child{{color:var(--signal);margin-right:20px}}.legend span:nth-child(2){{color:var(--reference);margin-right:20px}}
.badge{{display:inline-block;border-radius:5px;padding:2px 7px;font-size:12px;background:#edf1f2;white-space:nowrap}}
.tentative{{background:#e0f3ed;color:#1e6250}}.ambiguous{{background:#fff0d7;color:#865719}}.unassigned{{background:#eceff2;color:#465b65}}
details{{border-top:1px solid #dce4e2;padding:14px 0;scroll-margin-top:20px}}summary{{cursor:pointer;font-weight:600}}
.detail{{padding:14px 0}}.warnings{{color:#865719}}code{{overflow-wrap:anywhere;font-size:12px}}
.selected{{stroke:#7652a3}}.apex{{stroke:#65757a;stroke-dasharray:4 4}}h3{{font-size:16px;margin:24px 0 8px}}
.consistent{{background:#e0f3ed;color:#1e6250}}.sensitive{{background:#fff0d7;color:#865719}}.inconclusive{{background:#eceff2;color:#465b65}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.review-notes{{line-height:2.5}}
@media(max-width:640px){{main{{padding:0 12px;margin:16px auto}}section,.panel{{padding:16px}}h1{{font-size:24px}}.stats{{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}.pagination{{justify-content:flex-start}}.pagination .page-size{{flex-basis:100%}}}}
@media print{{body{{background:white}}main{{max-width:none}}details{{break-inside:avoid}}.filters,.pagination{{display:none}}#components .names span{{display:block}}}}
</style></head><body><main>
<header><div class="eyebrow">GC-MS · Component dashboard</div><h1>{escape(report.sample_name)}</h1>
<p class="muted">{report.acquisition["scan_count"]:,} scans · {report.acquisition["end_seconds"] / 60:.1f} min recorded run · {report.library["spectrum_groups"]} reference groups</p>
<p class="muted">Screening candidates for analyst review. Similarity is not identification probability.</p></header>
<div class="stats"><div><strong>{report.summary["component_count"]}</strong><span>candidate components</span></div>
<div><strong>{report.summary["statuses"].get("tentative", 0)}</strong><span>tentative identities</span></div>
<div><strong>{report.summary["statuses"].get("ambiguous", 0)}</strong><span>ambiguous identities</span></div>
<div><strong>{report.summary["statuses"].get("unassigned", 0)}</strong><span>unassigned</span></div></div>
<details class="panel"><summary>Total ion chromatogram</summary>{_chromatogram(report, components)}
<p class="legend"><span>Corrected signal</span><span>Detected component markers</span>Gray: raw signal. Markers include all filtered components. Click one to open its page and evidence. Display is downsampled with extrema preserved.</p></details>
<section id="detected-components"><h2>Detected components</h2><p class="muted">Area % is the share of reported component-ion areas, not concentration. Filters preserve full-report totals.</p>
<form id="component-controls" class="filters" hidden role="search" aria-label="Filter components">
<label class="search">Search components<input id="component-search" type="search" autocomplete="off" placeholder="Component ID, candidate name or CAS" aria-describedby="search-help"></label>
<label>Status<select id="component-status"><option value="">All statuses</option><option value="tentative">Tentative</option><option value="ambiguous">Ambiguous</option><option value="unassigned">Unassigned</option></select></label>
{stability_filter}<button id="component-reset" type="button">Reset</button>
<small id="search-help" style="flex-basis:100%">Search includes all listed candidate identities. Click a column heading to sort; click again to reverse.</small></form>
<p id="component-count" class="muted" role="status" aria-live="polite">Showing {len(components)} of {len(components)} components</p>
<div class="table-wrap"><table id="components" aria-label="Detected components"><thead><tr><th scope="col" data-sort="component">Component</th><th scope="col" data-sort="apex">Apex, min</th><th scope="col" data-sort="names">Top candidate names</th><th scope="col" data-sort="score">Similarity</th><th scope="col" data-sort="area">Area %</th><th scope="col" data-sort="status">Status</th>{'<th scope="col" data-sort="stability">Stability</th>' if review else ""}</tr></thead>
<tbody>{"".join(rows)}</tbody></table></div><p id="component-empty" hidden>No components match these filters. Clear the search or select Reset.</p>
<nav id="component-pagination" class="pagination" aria-label="Component pages" hidden><span class="page-size">10 components per page</span>
<button type="button" data-page="first">First</button><button type="button" data-page="previous">Previous</button>
<label>Page <select id="component-page" aria-label="Component page"></select> <span id="page-total"></span></label>
<button type="button" data-page="next">Next</button><button type="button" data-page="last">Last</button></nav></section>
<section><h2>Inspect spectral evidence</h2><p id="evidence-hint" class="muted" hidden>Select a component ID in the table to inspect its candidates, spectra and warnings.</p><div id="component-evidence">{"".join(details) or "<p>No components passed the detection criteria.</p>"}</div></section>
{'<details class="panel"><summary>Review and stability checks</summary>' + _review_overview(review, packet_only) + "</details>" if review else ""}
<details class="panel"><summary>Limitations and provenance</summary><ul>{warnings}</ul>
<p>Library: {report.library["entries"]} entries, {report.library["exact_duplicate_groups"]} duplicate-spectrum groups.
{report.library["duplicate_groups_with_different_cas"]} groups contain different CAS identifiers.</p>
<p>Input SHA-256: <code>{escape(report.provenance["input_data_ms_sha256"])}</code><br>
Library SHA-256: <code>{escape(report.provenance["library_sha256"])}</code><br>
Algorithm: <code>{escape(report.algorithm_version)}</code> · Numeric type: float64</p>
<details><summary>Processing settings</summary><table><tbody>{settings}</tbody></table></details></details>
</main><script>{_INTERACTIONS}</script></body></html>"""
