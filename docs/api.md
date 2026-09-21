# HTTP API

[Documentation](README.md) · [Scientific method](science.md) · [OpenAPI](../examples/openapi.json)

Run the commands below from the repository root after `uv sync --locked`.

Start a local server in a separate terminal. Explicit thread limits keep it
comparable with the CLI, which defaults these variables to one.

```sh
export GCMS_LIBRARY=/absolute/path/to/library.msp
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  uv run --locked uvicorn gcms.api:app --host 127.0.0.1 --port 8000 --workers 1
```

The external library is required and parsed once at startup.
A malformed library fails startup rather than silently discarding entries.

Open **http://127.0.0.1:8000/** for the dashboard. Upload a ZIP, choose Python or
Rust, and enable or disable stability checks. Optionally set
`GCMS_SAMPLE=/absolute/path/to/sample.D` before startup to load a configured sample
automatically with Python and stability checks. Loading and error states
include retry; a failed analysis preserves the previous result.

Create a ZIP and send it as the request body:

```sh
mkdir -p artifacts
uv run --locked python -m zipfile -c artifacts/sample.zip /absolute/path/to/sample.D
curl --fail-with-body -H 'Content-Type: application/zip' \
  --data-binary @artifacts/sample.zip \
  http://127.0.0.1:8000/v1/analyze -o artifacts/api-result.json
curl --fail-with-body -H 'Content-Type: application/zip' \
  --data-binary @artifacts/sample.zip \
  'http://127.0.0.1:8000/v1/analyze?output=html' -o artifacts/api-result.html
```

| Endpoint | Result |
|---|---|
| `GET /` | Browser dashboard with ZIP upload and sample loading |
| `GET /v1/sample` | Analyze the optional `GCMS_SAMPLE`; same options and response schemas as the upload endpoint |
| `GET /health` | Service status and version |
| `GET /v1/library` | Library hash and duplicate audit |
| `POST /v1/analyze` | JSON report; `?output=html` returns HTML |
| `GET /openapi.json` | Machine-readable API definition |
| `GET /docs` | Interactive API documentation |

For the full review, add `?review=true&engine=rust&output=html` to the upload URL.
Use `engine=python` for NumPy/SciPy, or omit `output=html` for JSON. The Rust
extension must be built before starting the server. Defaults remain a single
Python analysis.

Both sample and upload HTML responses use the same paginated dashboard. Pagination
is local to the browser after the complete report loads; JSON responses retain the
complete scientific result. No stored analysis sessions or frontend dependencies
are required. No acquisition or reference library is distributed with the package.

This upload uses raw `application/zip`, not multipart. A ZIP may have a wrapper
directory but must contain exactly one `.D` directory with a direct `data.ms`.
Names are case-insensitive for `.D` and `data.ms`. Other acquisition files are
validated as archive entries but not extracted or used. Use stored or deflated,
unencrypted ZIPs. Renaming the sample does not affect processing.

The response arrives synchronously. Each process accepts one analysis at a time
and returns `503` with `Retry-After: 2` while occupied; clients may retry after
that delay. Temporary uploads are removed after processing. No job database,
authentication or public hosting is included. The documented command binds to
the local machine; an external deployment needs the lab's access controls and TLS.

## Parameters

Each processing setting is an optional query parameter, for example
`?noise_multiplier=12&min_component_fraction=0.002&top_k=5`.
Unknown keys and invalid combinations return `422`. The CLI accepts the same
settings as a JSON object using `--params parameters.json`. Actual settings are
always returned in the report. See [the algorithm specification](science.md#processing)
for their meaning and [models.py](../gcms/python/gcms/models.py) for defaults and permitted bounds.

## Response contract

The versioned report schema is defined in [models.py](../gcms/python/gcms/models.py), with a
complete [example](../examples/sample.json) and [OpenAPI export](../examples/openapi.json).
All numeric times in JSON are **seconds**; HTML displays minutes. Masses are
nominal m/z; intensities are uncalibrated instrument values.

| Field | Meaning |
|---|---|
| `schema_version`, `algorithm_version` | Output contract and processing method versions |
| `sample_name` | Name of the submitted acquisition |
| `provenance` | SHA-256 of `data.ms` and MSP bytes, software versions, numeric type and binning rule |
| `acquisition` | Scan/channel counts, start/end times, median interval, mass range and reader metadata |
| `parameters` | Complete processing configuration |
| `library` | Entry/group counts, conflicting names/CAS counts, RT diversity and source counts |
| `summary` | Component count, counts by status, sum and units of reported areas |
| `warnings` | Analysis-wide interpretation limits |
| `chromatogram` | Aligned time/raw/baseline/corrected TIC arrays; a display preview with full scan count |
| `components[]` | Time-ordered detections, each with evidence and ranked candidates |

Each component contains its zero-based `apex_scan`, integration start/apex/end
times, `area` in intensity·seconds, and `area_percent` relative to the sum of
reported component-ion areas. It also contains selected-ion count, a sparse
measured spectrum, status, margin between the best two distinct reference groups,
number of groups close to the best score, spectral-change diagnostic and warnings.

Each candidate has a `group_id`, square-root cosine `score` in [0, 1], all original
`identities`, the fraction of reference intensity in the acquired mass range,
and the projected reference spectrum. Spectrum `mz` and `intensity` arrays are
aligned pairs. Identity records preserve name, source, CAS, formula, molecular
weight and available RT/RI; absence is `null`.

`tentative` means the screening rules passed with no reference tie; `ambiguous`
means they passed with competing reference groups or conflicting identities;
`unassigned` means they did not pass. Co-elution warnings remain relevant even for
tentative results. Candidates are still shown for unassigned detections.
Component IDs are local to one result; reference IDs depend on the ordered,
hashed library. Do not use them as universal chemical identifiers.

With `review=true`, the response uses schema `review-1.0`: `analysis` contains
the original report; `method` defines the correspondence rules; `variants`
records every tested or skipped profile; `annotations` maps baseline component
IDs to stability, observations and local traces; `review_packet` lists selected
IDs. Failed/skipped profiles are visible and excluded from match-fraction
denominators. All six must complete for a consistent label. The default report
schema stays `1.0`.

## Errors and limits

Errors have the shape `{"error":{"code":"invalid_zip","message":"…"}}`.
Parameter errors also include `details`, a list of `location` and `message`.

| HTTP status | Examples |
|---|---|
| 408 | Upload took over 60 seconds |
| 413 | ZIP or `data.ms` exceeds 64 MiB; archive declares over 128 MiB expanded or 512 entries |
| 415 | Missing/wrong content type |
| 422 | Unsafe/corrupt ZIP, multiple samples, unsupported/truncated MS data, invalid parameters, too many detections |
| 503 | Another analysis is active, or `/v1/sample` was called without configuring `GCMS_SAMPLE` |

The supported reader path is a complete ChemStation `GC / MS Data File` with
the supplied format signature, 7–50,000 scans, a nominal 1 Da grid and no more
than 12 million scan×mass cells. Scan intervals must stay within 5% of their
median. These constraints are checked before analysis; MS records and totals are
checked against the decoder. Agilent `.D` is a directory convention, not a
guarantee that every instrument mode or file variant is compatible. Only the
supplied real acquisition has been verified; no second independent run was provided.
Detection is capped at 100,000 ion peaks and 1,000 reported components.
