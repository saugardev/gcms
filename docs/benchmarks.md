# Python and Rust performance comparison

[Documentation](README.md) · [Project](../README.md)

The Python implementation separates instrument reading, preprocessing, detection
and spectrum extraction, reference projection/matching, and report construction.
It exports intermediate arrays so the Rust implementation can be checked stage
by stage. The optional Rust extension implements smoothing, background subtraction,
noise estimation, peak detection/grouping, spectrum extraction, integration,
reference projection and matching. The reader, MSP parsing, input validation and
report construction remain shared Python code. SciPy also generates the small
Savitzky–Golay coefficient vector; Rust applies it and fits the endpoints.

This measures a **Rust numerical engine inside the existing Python application**.
It is not a standalone Rust API or vendor-file reader. Both engines use float64,
one numerical thread and the unchanged `coapex-1` rules.

The saved timings below predate a Linux portability correction: Python now scores
identical normalized reference vectors once and expands their original columns,
preventing BLAS rounding from reordering tied candidates. This is a correctness
fix; the saved measurements do not measure its additional cost.

## Rust grouping experiment

Rust now selects the strongest event per ion directly, preserving the first event
on equal prominence. Reused selection vectors replace per-group allocation and
two sorts. Python retains its equivalent reference implementation.

Eight warm runs per engine/workflow were measured in rotating order, with one
active worker at a time. Grouping alone lowered review medians from **1.430 to
1.384 s** in the first batch and **1.460 to 1.415 s** in the second (about 3%). It
was faster in 5/8 paired rounds in each batch; background workloads were not
controlled, so this small observed benefit is not a reliable latency guarantee.

Broad filter-buffer reuse was slightly slower and was rejected. A sparse grouping
variant had mixed paired timings and was also omitted. The simpler direct
selection remains. Both batches include the equivalent Python workflow and all
rejected results, stage timings and source/build hashes in the
[raw measurements](../examples/grouping-comparison.json). No further single-analysis
speedup is claimed because the timings were noisy.

A regression case covers duplicate ions, equal and unequal prominences, relative
height filtering and rejected seeds. The retained engines match the original
13-array bundle and complete reports with the existing tolerance and exact
component ordering/statuses. Scientific rules and thresholds are unchanged.

## Noise/library reuse experiment

**Retained in Python:** estimate noise once instead of three times per full
review, and prepare the projected/normalized library once instead of seven times.
Smoothing alternatives still rebuild their corrected signals, and every profile
still detects and scores its own components. Reuse stays inside one review.

**Tested in Rust, then omitted:** equivalent noise/library reuse, plus a second
candidate that iterated contiguous prepared-reference rows. The whole-review
measurements were mixed, so the existing, simpler Rust numerical path remains.
Both engines retain the earlier reuse of corrected signals across compatible profiles.

Nine adjacent before/after pairs were measured per candidate, alternating which
revision ran first. Each revision had its own persistent process, decoded inputs
and one warm-up; only one worker computed at a time. These are warm full reviews:

| Candidate | Before median | Candidate median | Median time saved per pair | Faster pairs |
|---|---:|---:|---:|---:|
| Python reuse | 2.882 s | 2.707 s | 8.5% | 7/9 |
| Rust reuse | 1.326 s | 1.337 s | −1.1% | 4/9 |
| Rust reuse + contiguous row iteration | 1.429 s | 1.440 s | 4.0% | 7/9 |

Python's ratio of overall medians improved by **6.1%**. The paired statistic is
separate: the median of `1 − candidate_time / before_time` for adjacent runs.
Rust's second candidate improved that statistic, but neither candidate lowered
the overall median; no clear overall median benefit was established on this host.
All reports had identical hashes within each engine across these comparisons.

An initial five-repeat experiment rotating four modes (neither new reuse, noise
only, library only, both) suggested about 9% savings in both engines relative to
the new implementation with reuse disabled. The comparisons against the actual
previous implementation above did not establish the same Rust improvement.
Both sets of results are retained, including the rejected candidates.

[Raw measurements and source/build hashes](../examples/reuse-comparison.json)
also include five fresh-process and five warm runs per engine/workflow for the
first candidate, plus final-version review measurements. Other applications
were using the machine; background workload and power mode were not controlled.
No stable startup, memory or single-analysis improvement is claimed. One analysis
has no repeated profiles to reuse.

The retained implementations match the original 13-array bundle, analysis report
and full review within the existing tolerance. Tests compare reused data with
independent recomputation in both engines and change acquisitions/libraries
between reviews. No global cache, extra threads, scientific parameter changes or
new dependencies were introduced.

## Earlier optimization experiment

Five fresh-process and five warm repeats per implementation on the same supplied
acquisition, measured sequentially on macOS arm64 with one numerical thread.
The before version is commit `8623ac0`; the after version is identified by source
and native-library hashes in [the complete measurements](../examples/optimization-comparison.json).

| Warm workflow | Python before → after | Python speedup | Rust before → after | Rust speedup |
|---|---:|---:|---:|---:|
| Single analysis, median | 0.739 → 0.492 s | 1.50× | 0.463 → 0.244 s | 1.90× |
| Full seven-run review, median | 5.428 → 2.696 s | 2.01× | 3.399 → 1.366 s | 2.49× |

After optimization, Rust is **2.02× faster for analysis** and **1.97× for review**
than the optimized Python engine in these warm measurements.

| Fresh-process scope | Python before → after | Rust before → after |
|---|---:|---:|
| Single analysis, median | 1.791 → 1.551 s | 1.479 → 1.354 s |
| Full review, median | 6.469 → 3.967 s | 4.483 → 2.393 s |
| Analysis peak RSS, median | 644 → 598 MiB | 516 → 472 MiB |
| Review peak RSS, median | 610 → 709 MiB | 575 → 588 MiB |

Review memory use increased in this measurement, especially for Python; this is
a speed improvement, not a claim of lower memory use. RSS includes the interpreter,
reader and allocator behavior. Warm timings exclude input loading and JSON;
fresh timings include both. Neither measures HTTP or HTML generation. Background
workload and power settings were not controlled, and OS caches were retained.

The retained approaches remove repeated or unnecessary work:

- Python batches co-apex window searches instead of repeatedly converting the
  event array for scalar searches. Both engines defer bound medians until a
  component passes the existing intensity threshold, and the shared report code
  determines valid references once per report.
- Rust ends each prominence-base search at its first exact zero on nonnegative
  traces and skips exact-zero query products when matching spectra. It retains
  nonzero intensities, mass order, tie rules and float64 precision.
- Both engines reuse baseline preprocessing for the four review profiles whose
  smoothing/background settings are unchanged. The two smoothing alternatives
  still recompute it. All six alternatives still run detection and matching;
  there is no cache shared across requests.

A separate five-repeat experiment tested column-major input, including conversion
time, with both engines. Warm review changed from 2.727 to 2.692 s in Python and
1.397 to 1.415 s in Rust. That small, inconsistent benefit did not justify changing
the input layout; the implementation remains row-major. Those raw runs and all
before/after benchmark runs are included in the linked evidence.

Both optimized engines match the original frozen **13 arrays and complete reports**,
and the saved full review, using `rtol=1e-6, atol=1e-8` for floats and exact discrete
values. They also match each other. The result remains 333 detections, 24 tentative,
46 ambiguous and 263 unassigned; review labels remain 45 consistent and 288 sensitive.
These checks preserve behavior, not independently established chemical accuracy.

Reproduce each workflow with the existing harness after setting the external
input paths and building Rust as shown below:

```sh
uv run --locked gcms benchmark --engine python --repeats 5 --out artifacts/python-analysis.json
uv run --locked gcms benchmark --engine rust --repeats 5 --out artifacts/rust-analysis.json
uv run --locked gcms benchmark --workflow review --engine python --repeats 5 --out artifacts/python-review.json
uv run --locked gcms benchmark --workflow review --engine rust --repeats 5 --out artifacts/rust-review.json
```

For a before/after comparison, run the same commands and inputs from a separate
checkout of `8623ac0`, with its own release build. Do not mix extension binaries
between revisions. Individual timings, environment, input hashes, source hashes,
binary hashes and equivalence results are recorded in the evidence file.

## Run the Rust version

With the Python environment installed and a Rust toolchain available, from the
repository root (tested with rustc 1.94.0 on macOS arm64):

```sh
export GCMS_SAMPLE=/absolute/path/to/sample.D
export GCMS_LIBRARY=/absolute/path/to/library.msp
PYO3_PYTHON="$PWD/.venv/bin/python" cargo build --release --locked --manifest-path gcms/rust/Cargo.toml
uv run --locked gcms analyze --engine rust --out artifacts/rust-sample
uv run --locked gcms export-bundle --out artifacts/python
uv run --locked gcms export-bundle --engine rust --out artifacts/rust
uv run --locked gcms compare artifacts/python artifacts/rust
uv run --locked python -m unittest discover -s tests -v
uv run --locked gcms benchmark --engine python --repeats 7 --out artifacts/python-benchmark.json
uv run --locked gcms benchmark --engine rust --repeats 7 --out artifacts/rust-benchmark.json
```

The extension is loaded from `gcms/rust/target/release/`. Both macOS and Linux library
names are supported; only macOS was measured here. Cargo.lock pins dependencies;
builds use release optimization and thin LTO, without fast-math or extra threads.
Rust compilation is excluded from execution timings. A missing build gives a
clear error rather than falling back to Python. The HTTP API still defaults to
the original Python engine; select Rust through `?engine=rust`, the CLI, or
`analyze(..., engine="rust")`.

The complete real-sample report and all 13 arrays pass the original comparison
with exact integer indices and `rtol=1e-6, atol=1e-8` floats. The 333 component IDs,
candidate ordering, statuses and warnings agree. The checks include
cross-language checks of synthetic isolated/overlapping/blank signals, multiple
filter windows, non-contiguous arrays, plateaus, ties, out-of-range references,
short acquisitions and conservative settings on the real sample. Rust checks
are skipped if the optional extension has not been built.

Review checks also cover reciprocal correspondence, skipped/failed settings,
plot-integral agreement, safe exports and complete real-sample review equivalence.

Sources: [Rust kernels](../gcms/rust/src/lib.rs), [Python bridge](../gcms/python/gcms/rust_backend.py),
[parity checks](../tests/test_rust.py). The bridge uses [PyO3](https://pyo3.rs/)
and [rust-numpy](https://docs.rs/numpy/0.29.0/numpy/). Peak and convolution behavior
follows the documented [SciPy peak routines](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html)
and [filter](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html).

## Seven-run review workflow

The table in this section predates the optimizations above and is retained as
historical evidence. Five repeats per engine on the same macOS arm64 machine:

| Scope | Python / NumPy / SciPy | Rust kernels + shared Python | Speedup |
|---|---:|---:|---:|
| Warm full review, median | 5.598 s | 3.374 s | 1.66× |
| Warm full review, min–max | 5.518–6.838 s | 3.311–3.573 s | — |
| Fresh process with raw input, median | 6.611 s | 4.545 s | 1.45× |
| Fresh process, min–max | 6.354–7.361 s | 4.453–4.834 s | — |
| Fresh-process peak RSS, median | 664 MiB | 550 MiB | — |

Rust uses about 40% less warm review time here. Both engines produce identical
discrete findings (45 consistent, 288 sensitive) and deterministic report hashes
within each engine. Cross-engine floats match within the tolerance below.
Background workloads and power settings were not controlled; these are local
measurements, not universal speed or latency guarantees.

```sh
uv run --locked gcms review --engine python --out artifacts/review-python
uv run --locked gcms review --engine rust --out artifacts/review-rust
uv run --locked gcms compare-reviews artifacts/review-python.json artifacts/review-rust.json
uv run --locked gcms benchmark --workflow review --engine python --repeats 5 --out artifacts/python-review-benchmark.json
uv run --locked gcms benchmark --workflow review --engine rust --repeats 5 --out artifacts/rust-review-benchmark.json
```

The review workload includes the baseline, six alternative analyses, numerical
cross-profile correspondence, shared Python stability classification and local
plot-trace preparation. Python uses NumPy for cross-profile spectral products;
Rust filters pairs by time before computing their spectral agreement. Both retain
the same reciprocal-uniqueness rule and thresholds. HTML/CSV generation and disk
writes are outside these timings. Fresh-process measurements include JSON
serialization; warm measurements exclude it.

With `workflow=review`, the existing `warm_analysis_seconds` and
`analysis_seconds` benchmark fields mean the **entire seven-run review**, not
one analysis. Compare the same workflow across engines. The complete review JSON
passes `rtol=1e-6, atol=1e-8`, ignoring only `analysis.provenance.software`.
All discrete labels, component correspondences, candidate names and packet
selections must agree. The comparator exits 0 for equivalent results, 1 for a
difference and 2 for invalid input.

Saved evidence: [Python measurements](../examples/python-review-benchmark.json),
[Rust measurements](../examples/rust-review-benchmark.json),
[comparison and measured source/build hashes](../examples/review-comparison.json),
[equivalence](../examples/review-equivalence.json). All saved benchmark files and
hashes describe the source measured at that time and are retained as historical
evidence.

The original acquisition and library are external inputs and are not distributed.
Recorded source paths refer to the layout used at measurement time; the current
implementations live under `gcms/python` and `gcms/rust`.

## Earlier single-analysis comparison

The earlier single-analysis measurement used seven repeats per engine on the same supplied sample, this macOS arm64 machine
(10 logical CPUs), Python 3.12.13, NumPy 2.5.3, SciPy 1.18.1 and rustc 1.94.0:

| Scope | Python / NumPy / SciPy | Rust kernels + shared Python | Speedup |
|---|---:|---:|---:|
| Warm analysis, median | 0.678 s | 0.438 s | 1.55× |
| Warm analysis, min–max | 0.658–0.750 s | 0.435–0.458 s | — |
| Fresh process with raw input, median | 1.790 s | 1.520 s | 1.18× |
| Fresh process, min–max | 1.740–2.172 s | 1.427–1.619 s | — |
| Fresh-process peak RSS, median | 613 MiB | 489 MiB | — |

Rust took about **35% less warm analysis time** in this comparison. It does not
make every operation faster:

| Warm stage median | Python / NumPy / SciPy | Rust engine |
|---|---:|---:|
| Preprocessing | 0.200 s | 0.114 s |
| Peak detection and extraction | 0.402 s | 0.226 s |
| Reference projection and matching | 0.006 s | 0.042 s |
| Shared Python report construction | 0.049 s | 0.049 s |

Stage medians need not sum to the median total; validation and bridge overhead
are also included in total analysis time. NumPy's optimized matrix matching
outperforms the scalar Rust implementation here. The net gain comes from the
other stages. This is evidence about these implementations and this workload,
not a universal language speed ratio.

Before final timing, both engines received the same safe height prefilter: on a
nonnegative trace, a peak below the required prominence in height cannot pass.
Rejecting it before searching for its bases reduces work without changing the
algorithm's results. Both optimized engines still match the original frozen
arrays/report. No filtering threshold, precision or scientific acceptance rule
was relaxed to obtain these timings.

Evidence: [comparison summary, build/source hashes](../examples/rust-comparison.json),
[Python measurements](../examples/python-comparison-benchmark.json),
[Rust measurements](../examples/rust-benchmark.json),
[equivalence against the original](../examples/rust-equivalence.json).
Measurements were sequential on the local machine with OS caches retained;
background workload and power settings were not controlled. Peak RSS includes the
shared Python reader. Neither measurement includes HTTP upload or HTML rendering.

## Original Python baseline

On this macOS arm64 machine (10 logical CPUs), Python 3.12.13, NumPy 2.5.3,
SciPy 1.18.1 and one numerical thread, five repeats on the supplied sample gave:

| Scope | Median | Min–max |
|---|---:|---:|
| Fresh process, raw input | 1.637 s | 1.617–1.676 s |
| Warm analysis | 0.693 s | 0.688–0.722 s |
| Fresh-process peak RSS | 673 MiB | 672–675 MiB |

All five fresh runs produced the same report hash and 333 components. These are
local measurements, not latency guarantees or a cross-language comparison.
The full [raw-input results](../examples/benchmark.json) and separately measured
[canonical-input results](../examples/bundle-benchmark.json) preserve individual runs.

## Reproduce the measurement

Run from the repository root on macOS or Linux:

```sh
uv run --locked gcms benchmark --repeats 5 --out artifacts/benchmark.json
uv run --locked gcms export-bundle --out artifacts/baseline
uv run --locked gcms benchmark --bundle artifacts/baseline --repeats 5 --out artifacts/bundle-benchmark.json
uv run --locked gcms analyze --bundle artifacts/baseline --out artifacts/from-bundle
```

The CLI defaults `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`
and `VECLIB_MAXIMUM_THREADS` to 1 before loading numerical libraries. Caller
overrides are respected and recorded. Close competing CPU-heavy workloads and
use the same machine, input, parameters, library, thread limits and repeat count
for both implementations. Record power mode and other workload conditions if
publishing results; the current harness does not control those conditions.

The saved [raw-input benchmark](../examples/benchmark.json) records individual runs,
medians/minima/maxima, software and input hashes, parameters, Python/OS/CPU
architecture, logical CPU count, NumPy build and thread settings. It has two scopes:

- **Fresh process:** wall time from spawning a new Python process through its
  completion. Includes imports, validated raw or canonical input reading, library
  parsing, all analysis stages, report construction and JSON serialization.
  Peak RSS comes from that child process and includes interpreter/native libraries.
- **Warm analysis:** one unmeasured warm-up, then repeated analysis of already
  decoded arrays and parsed library in the same process. Includes input-array
  validation and report construction. Excludes file loading and JSON serialization.

Neither includes HTTP upload, ZIP extraction, HTML rendering or writing the report
to disk. OS disk caches are not flushed: “fresh process” does not mean cold storage.
RSS is process peak resident memory, not array allocation size. The warm-stage
timers exclude the small validation/dispatch overhead included in total warm time.
Identical report hashes across fresh runs check reproducibility on that environment;
they do not demonstrate scientific accuracy.

Raw-input and canonical-input timings must be labelled separately. Compare the
warm numerical stage timings first, then measure the complete service separately
if client latency is the target. Do not compare Rust's numerical kernel against
Python's process startup plus file decoding.

## Portable fixture contract

`gcms export-bundle` creates a local directory containing:

- `manifest.json`: bundle version `1.0`, algorithm `coapex-1`, parameters,
  original acquisition/library hashes, sample name, metadata and per-array
  shape/dtype/order/file hash.
- `library.msp`: an exact copy of the reference input.
- `report.json`: expected complete structured output.
- Thirteen `.npy` arrays, uncompressed C order (row-major), little-endian float64
  (`<f8`) except zero-based scan indices (`<i8`). No object arrays or pickle.

Let S = scans, M = mass channels, G = exact reference groups and C = components.

| Array | Shape | Meaning |
|---|---|---|
| `time_seconds` | S | Original scan timestamps |
| `mz` | M | Contiguous nominal mass grid |
| `intensity` | S × M | Decoded input intensities |
| `corrected` | S × M | Smoothed, background-subtracted intensities |
| `baseline_tic` | S | Sum of estimated background across masses |
| `noise` | M | Per-ion first-difference noise estimates |
| `reference_intensity` | G × M | Group reference spectra projected onto the grid |
| `reference_mass_fraction` | G | Fraction of reference intensity retained |
| `component_spectra` | C × M | Reconstructed component spectra |
| `scores` | C × G | Square-root cosine similarity |
| `component_apex_scan` | C | Zero-based apex indices, int64 |
| `component_bounds_scan` | C × 2 | Inclusive start/end scan indices, int64 |
| `component_area` | C | Selected-ion areas in intensity·seconds |

`time_seconds`, `mz`, `intensity` and the library are the canonical inputs. The
remaining arrays and report are expected outputs. Group/component ordering, zero
handling, rounding, filter boundaries and stable ties matter. The exact processing
rules are in [science.md](science.md#processing); the reference implementation is
[pipeline.py](../gcms/python/gcms/pipeline.py). Input loading verifies hashes and rejects pickle.
Large bundles are generated locally under `artifacts/`, not stored as sample results.

## Contract for further Rust migration

1. Keep the vendor decoder shared until numerical correctness is established.
   The current extension receives the actual decoded arrays through rust-numpy;
   it does not read expected stage outputs from a fixture.
2. Preserve `coapex-1`, float64 and the documented boundary/tie rules.
   Reproduce the same matrices and report. Compile in release mode before timing.
3. Write a second directory with the same manifest/array/report contract and
   updated hashes for its own files. Preserve input/library hashes, parameters,
   algorithm version, group ordering and all reference identities. Software
   provenance should identify the Rust implementation.
4. Compare:

   ```sh
   uv run --locked gcms compare artifacts/baseline artifacts/rust
   ```

   Exit 0 means equivalent, 1 means a reported difference, 2 means invalid input.
   Array shapes/dtypes and integer indices must match exactly; float values use
   `rtol=1e-6, atol=1e-8`. File hashes and declared layouts are verified against
   each bundle's manifest, but cross-language output file bytes need not match.
   The JSON comparison ignores only `provenance.software`; numeric float fields
   use the same tolerance, and IDs, statuses, candidates and warnings must match.
5. Measure identical scopes and report the full distributions, component count,
   equivalence result and peak RSS. Compute speedup as Python median / Rust median.

The comparator tolerances are a proposed engineering acceptance threshold, not a
claim that every discrepancy is scientifically irrelevant. Changes in peak count,
bounds, candidate order or ambiguity must be investigated. Freeze a baseline before
changing the algorithm; evaluate a revised method scientifically under a new
algorithm version instead of treating different outputs as a pure speedup.

The [saved equivalence check](../examples/equivalence.json) verifies that the exported
real-sample inputs recompute the original Python stages/report. Tests also modify
a stage, update its hash, and confirm that numerical differences still fail.
Passing a comparison against an unchanged copy alone would not check this.

## What to optimize next

Peak detection/extraction remains the largest stage in both implementations.
The unbounded prominence search can revisit long portions of a trace; indexing
the nearest higher peaks is a possible next experiment if profiling justifies it.
For a production hybrid, retaining NumPy's matrix matching would be more attractive
than the current scalar Rust loop. Neither change is needed to reproduce this
comparison. More threads, float32 and scientific algorithm changes should remain
separate configurations, each with its own correctness evidence.
