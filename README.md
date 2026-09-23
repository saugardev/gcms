# Mafer

GC-MS screening for analyst review. Process a ChemStation `.D` acquisition,
compare its spectra with an MSP library, and inspect proposed identities in a
browser dashboard or a JSON report.

[Documentation](docs/README.md) · [HTTP API](docs/api.md) · [Sample report](examples/sample.html)

## Getting started

Install [uv](https://docs.astral.sh/uv/), then run from the repository root:

```sh
uv sync --locked
export GCMS_LIBRARY=/absolute/path/to/library.msp
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  uv run --locked uvicorn gcms.api:app --host 127.0.0.1 --port 8000 --workers 1
```

Open **http://127.0.0.1:8000/**. Upload an acquisition as a ZIP, sort and filter the
results, and select a detected component to inspect its evidence.
Acquisitions and reference libraries are external inputs; none are bundled.
Optionally set `GCMS_SAMPLE=/absolute/path/to/sample.D` before starting the server
to load that acquisition automatically.

For a report without a server:

```sh
uv run --locked gcms analyze --sample /absolute/path/to/sample.D
```

Open `artifacts/sample.html`; the complete JSON is `artifacts/sample.json`.
Python 3.12.13 is pinned. Setup and measurements have been verified on macOS arm64.

## Documentation

- [User guide](docs/README.md): CLI usage, reports and stability checks.
- [HTTP API](docs/api.md): ZIP uploads, parameters, response schemas and errors.
- [Scientific method](docs/science.md): detection, matching, library ambiguity and limitations.
- [Validation](docs/validation.md): measured evidence and reproducible submission checks.
- [Python and Rust](docs/benchmarks.md): optional Rust build, equivalence and benchmarks.
- [Implementations](services/README.md): source layout and the measured Rust speedup.
- [Deployment](docs/deployment.md): GitHub Actions, Jio VM and HTTPS demo.

Saved reports and evaluation results are in [examples/](examples/). Download the
HTML files and open them locally if GitHub displays their source.

Identities remain proposals: similarity is not an identification probability,
and reported peak areas are not concentrations. Independent chemical accuracy
on the original evaluation sample has not been measured.

## License

Project source and documentation are licensed under [MIT](LICENSE).
