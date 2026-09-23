# User guide

[Project](../README.md) · [HTTP API](api.md) · [Scientific method](science.md) · [Validation](validation.md) · [Python and Rust](benchmarks.md)

Process an acquisition, inspect proposed identities, and reproduce the results.
Run the commands below from the repository root. For the browser dashboard and
ZIP uploads, follow the [HTTP API guide](api.md).

## Run an analysis

From the repository root, with [uv](https://docs.astral.sh/uv/). Python 3.12.13 is
pinned in `.python-version`; this setup has been exercised on macOS arm64:

```sh
uv sync --locked
export GCMS_SAMPLE=/absolute/path/to/sample.D
export GCMS_LIBRARY=/absolute/path/to/library.msp
uv run --locked gcms analyze
```

Open `artifacts/sample.html`; the full machine-readable result is
`artifacts/sample.json`. No acquisition or library is bundled. Environment
variables supply defaults; command-line options can select another input:

```sh
uv run --locked gcms analyze --sample /path/to/sample.D --library /path/to/library.msp --out artifacts/another
```

Saved results: [HTML report](../examples/sample.html), [JSON report](../examples/sample.json),
[evaluation](../examples/evaluation.json), and [benchmark](../examples/benchmark.json).
Download the HTML and open it in a browser if your repository viewer displays its source.
The report needs no server or external assets.
Search components by ID, candidate name or CAS; filter by status and, in review
reports, stability. Click any component-table heading to sort or reverse its order.
The table shows 10 components per page with first/previous/next/last controls and
a page selector. Sorting and filtering apply to all components before pagination.
Select a component ID to open its evidence; chromatogram links jump to its page.
Area percentages retain their original full-report denominator. Printing includes
all matching components, including later pages.

## Read a report

Each row is a detected signal with proposed library matches, not a confirmed
ingredient. Different detections can receive the same proposed name; keep their
evidence separate until their identities have been reviewed. Area % describes
reported signal areas, not the product's formulation or concentration.

| Label | Meaning |
|---|---|
| Tentative | A candidate passes the screening rules without a close competing group or conflicting reference identity. |
| Ambiguous | The screening rules pass, but competing candidates or conflicting reference identities remain. |
| Unassigned | No candidate passes screening; the detection may still represent a real substance. |
| Consistent | All six alternative processing settings recover a unique corresponding detection with the same top reference group. |
| Sensitive | At least one alternative has no compatible detection or changes the top reference group. |
| Inconclusive | The comparisons cannot establish consistency, for example because profiles fail or correspondences are ambiguous. |

Stability checks reprocess the same data; they are not independent laboratory
measurements. A consistent candidate can still be wrong. See the
[scientific method](science.md) for exact rules and limitations.

## Review peak stability in Python and Rust

Run the baseline plus six controlled settings changes, with local chromatograms,
ion traces and a per-peak correspondence table:

```sh
uv run --locked gcms review --engine python --out artifacts/review-python
PYO3_PYTHON="$PWD/.venv/bin/python" cargo build --release --locked --manifest-path services/rust/Cargo.toml
uv run --locked gcms review --engine rust --out artifacts/review-rust
uv run --locked gcms compare-reviews artifacts/review-python.json artifacts/review-rust.json
```

Each run writes a complete `.html`/`.json` review and a `-packet.html`/`-packet.csv`
with 12 selected examples and blank analyst fields. Start with the saved
[review packet](../examples/review-packet.html) and [worksheet](../examples/review-packet.csv).
The larger full reports are generated locally under `artifacts/`.

Both engines report **45 consistent and 288 sensitive** baseline detections.
Consistent means all six alternatives uniquely match and retain the same leading
reference group. Sensitive means at least one alternative changes that group or
has no compatible match. Incomplete or uncertain evaluations can be inconclusive.
These are settings-stability labels, not chemical confirmation; an ambiguous
identity can still be consistent. The packet is an illustrative selection, not
an accuracy test. [Method and limits](science.md#per-peak-stability-and-review).

Rust performs the numerical analyses and cross-profile spectral correspondence.
Both paths share Python ingestion, review classification, plot preparation and
HTML/CSV output. [Repeated measurements](benchmarks.md#seven-run-review-workflow)
and the [complete-review comparison](../examples/review-equivalence.json) make this
scope explicit.

## Check and measure

For a complete clean-install check and source submission archive:

```sh
uv run --locked python scripts/verify_submission.py
```

This installs the packaged source in a fresh environment and builds Rust from
source. Results, logs and the source archive are written to
`artifacts/submission-check/`. See [validation.md](validation.md) for the exact
scope and a claim-by-claim account of the scientific evidence.

Individual checks:

```sh
uv run --locked python -m unittest discover -s tests -v
uv run --locked ruff check gcms tests scripts
uv run --locked gcms evaluate
uv run --locked gcms benchmark --repeats 5
uv run --locked gcms export-bundle
```

Without `GCMS_SAMPLE` and `GCMS_LIBRARY`, `gcms evaluate` runs only the synthetic
cases, and tests that require the original evaluation inputs are explicitly
skipped. The API requires `GCMS_LIBRARY`; its configured sample is optional.

The dependency-free [browser check](../tests/report-controls.html) exercises pagination,
global sorting, filters, the component inspector, evidence links and printing against
the saved reports. Serve the repository root
with `python -m http.server 8002 --bind 127.0.0.1` and open
`http://127.0.0.1:8002/tests/report-controls.html`.

The checks cover known signals, ambiguous/missing identities, invalid inputs,
real-sample API equivalence, HTML escaping, and the numerical comparison contract.
[benchmarks.md](benchmarks.md) explains numerical equivalence and the measured
Python/Rust comparison.

Implementation: `io.py` handles input; `pipeline.py` performs numerical stages;
`models.py` defines the contract; `api.py` and `cli.py` expose it; `report.py`
renders HTML; `evaluation.py` and `benchmark.py` provide reproducible checks.
NumPy/SciPy perform array/signal operations, rainbow-api decodes ChemStation,
FastAPI/Pydantic provide HTTP/schema validation, and Python's standard library
handles archives, hashes, HTML/SVG generation and test execution.
