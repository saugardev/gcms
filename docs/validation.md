# What the evidence supports

[Documentation](README.md) · [Project](../README.md)

This submission demonstrates a reproducible GC-MS screening workflow. Its chemical
identification accuracy on the supplied acquisition remains **unmeasured**.

| Claim | Evidence | What it does not establish |
|---|---|---|
| The supported acquisition can be processed through the API | Real ZIP input, API/CLI equivalence checks, structured errors | Compatibility with every Agilent `.D` variant |
| Basic detection and integration work on controlled signals | Isolated/overlapping/blank cases with known times and areas | Performance on arbitrary experimental mixtures |
| The implementations agree | Stage/report parity tests and complete review comparison | Chemical correctness; both engines can reproduce the same mistake |
| Results are sensitive to processing settings | 45 consistent and 288 sensitive baseline detections across six alternatives | Identification probabilities or a count of true/false chemicals |
| The implementation has known failure modes | The 48-case stress experiment below | A population error rate or independent benchmark |
| Source and setup can be checked independently | Fresh archive installation, fresh Rust compilation, tests and original-result comparison | A second operating-system test or bit-identical binaries across machines |

## Harder synthetic evaluation

Run `uv run --locked gcms evaluate --out artifacts/evaluation.json`.
Add `--engine rust` to repeat the same protocol with native numerical kernels.
All conditions, seeds, input-array/library hashes and individual results are in
the [Python evaluation](../examples/evaluation.json) and [Rust evaluation](../examples/evaluation-rust.json).
The full protocol is `synthetic-stress-1` in [evaluation.py](../gcms/python/gcms/evaluation.py).

The protocol fixes the processing parameters before evaluating 16 scenarios,
each with three seeds (17, 29, 43):

- Two Gaussian signals with 0, 0.5, 1.5 or 3 seconds separation; the second
  signal's amplitude is 1, 0.1 or 0.01 times the first. Noise standard deviation
  is 5 instrument counts and the Gaussian width parameter is 0.9 seconds.
- An isolated weak signal at amplitude ratio 0.001, with noise deviation 25.
- Background/noise only, with noise deviation 25.
- A true signal whose reference is removed from the library.
- A true reference replaced by a differently named synthetic decoy with the same
  fragment masses and intensities perturbed by ±10%. This deliberately constructed
  counterexample tests whether a high similarity score can support a wrong label.

| Result across 48 cases | Count |
|---|---:|
| Cases with at least one missed simulated component | 19 |
| Cases with additional unmatched detections | 0 |
| Cases with a wrong tentative match | 3 |

All three wrong tentative matches occur in the deliberately similar-decoy case.
Coincident signals merge, and some weak signals are missed. Zero additional
detections in this small constructed set does not establish a zero false-positive
rate on real data. The stress set was developed after the initial implementation;
it is diagnostic, not an independent held-out test. No processing parameters were
tuned against its outcomes. Future method changes must use a separate evaluation
set if these cases guide development.

For synthetic detection counts, match as many detections to known apex times as
possible within 0.75 seconds, then minimize total time error. Identity labels do
not influence that assignment. When either side has multiple compatible partners,
identity correctness and relative area error are `null`: an arbitrary pairing of
overlapping signals cannot validate their chemical identities or individual areas.
Wrong-tentative counts use only uniquely assessable matches, so unresolved cases
must be considered separately. Area errors compare selected-ion estimates with
the full known injected synthetic area; that is a diagnostic, not concentration
validation. The older real-sample aggregate sensitivity table retains its separate,
RT-only greedy correspondence rule; the newer per-peak review additionally uses
spectral agreement and preserves competing matches.

## Reproduce the submission from its source archive

From the repository root, with `uv` and a Rust toolchain manager installed:

```sh
uv run --locked python scripts/verify_submission.py
```

The script builds a source archive, inspects its members, extracts it into a new
temporary directory, installs locked dependencies into a new virtual environment
with uv's package cache disabled, and compiles Rust from the included sources.
It runs the synthetic and available real-input tests, Ruff, both evaluation
engines and a comparison against the saved synthetic results. Rust must load;
real-input tests are skipped when their external inputs are absent.
The default Python version is pinned in
`.python-version`; the Rust toolchain is pinned in `rust-toolchain.toml`.

To also run every original real-input check and reproduce the saved sample report,
provide the original acquisition and library explicitly (or set `GCMS_SAMPLE` and
`GCMS_LIBRARY`):

```sh
uv run --locked python scripts/verify_submission.py \
  --sample /absolute/path/to/original-sample.D --library /absolute/path/to/original-library.msp
```

The deliverables are generated under `artifacts/submission-check/`:

- `mafer_gcms-0.1.0.tar.gz`: source, documentation,
  tests and examples. Extract it, enter the extracted directory, then follow README.
- `verification.json`: pass/fail, archive and member SHA-256 hashes, commands,
  versions, test results, numerical equivalence and environmental limitations.
- `step-*.log`: complete command output, including any failure.
- `evaluation-python.json` and `evaluation-rust.json`: fresh evaluation results.

The archive uses [Hatch's explicit file selection](https://hatch.pypa.io/latest/config/build/#explicit-selection).
It includes the submitted source even before those files are committed to Git.
The check requires the public `docs/` guides and MIT `LICENSE` in the archive,
and rejects the removed challenge directory, private `.local/` notes, build
output and working environments. Acquisitions and libraries remain external.
The Python wheel contains the Python package; use the source archive for the
tests, documentation and optional Rust build. Managed Python and
Rust installations and Cargo's registry cache may be reused. The fresh environment
check is performed on the current host, with no claim of cross-platform validation.
Regenerate the archive and evidence after changing the submission.

## Independent chemical validation still needed

The [12-example packet](../examples/review-packet.html) and
[worksheet](../examples/review-packet.csv) are ready for an analyst. No entries have
been reviewed. They are purposively selected, biased toward large signals, and
show candidate names; they are useful for feedback but unsuitable as a blinded
accuracy set.

For a defensible accuracy measurement, obtain a separate acquisition or known
mixture with independently established identities, acquisition conditions and
an explicit statement of whether the reference list is complete. Obtain the
reference annotations before exposing our candidate rankings. Agree on apex
tolerance, identity/synonym rules, handling of co-elution and acceptable error
rates with the laboratory before scoring. Keep that evaluation data separate from
parameter selection and library corrections.

Report detection precision/recall only against complete annotations, identity
agreement among assessable matches, wrong tentative assignments, abstentions and
unresolved cases with their denominators. A partial identity list does not make
every unlisted detection false. Replicate acquisitions and calibrated standards
are needed to evaluate repeatability and concentration claims respectively.
No independent truth, replicate real run or calibration was supplied here.
