# Rejected GC–MS processing experiments: results and reimplementation guide

Research measured locally on 24 September 2026; consolidated 25 September 2026.

**Retain the existing Rust coapex processing. None of the tested replacements
passed all preregistered gates.** The rejected implementations, experimental API
selectors, wrappers, dedicated tests, downloaded tools, and generated result dumps
are not part of the published application. This document retains the measured
findings, frozen methods, and reasons for rejection so a future experiment can be
implemented deliberately. The app continues to read saved analyses from PostgreSQL;
opening a dashboard or saving an analyst decision does not rerun processing.

These results concern specific versions/settings and synthetic inputs. They do
not disprove the papers, establish chemical identities in our sample, or estimate
accuracy across laboratories. Historical source/results remain on the local
research branch, but a checkout of main is not a runnable copy of these experiments.
Reimplementation requires generating and freezing new evidence; this narrative
alone is not a bit-for-bit reproduction bundle.

## Decisions by method

| Method/source | Useful observation | Why it was rejected for production |
|---|---|---|
| Stein-inspired single-model-ion NNLS (`modelpeak-1`) | Python/Rust mechanics agreed on the 48 synthetic cases. | No reduction in missed-component cases; worse spectral/area outcomes; more wrong IDs; real acquisition exceeded the 1,000-component cap. |
| Stein-inspired quality-aware library matching | Historical decoy results alone looked promising. | No benefit for coapex on fresh data; modelpeak wrong tentative IDs rose from 33 to 59. Removing contradictory ions can inflate unrelated matches. |
| Multi-ion consensus model selection | Area error fell 19.7%; near-overlap recovery improved. | Misses fell only 13.3%, below the 20% gate; false splits rose from 1 to 35 and incorrect tentative IDs from 5 to 36. |
| Stein noise-factor estimate | Extras fell from 144 to 116, mainly in drifting blanks. | No recall improvement; area error worsened 1.6%. Retain as a narrow future noise-calibration hypothesis. |
| Consensus plus noise factor | Similar improvements to consensus. | Same failed extraction/identification gates as consensus; no independently demonstrated additional benefit. |
| arPLS background correction | Removed drifting-blank extras and improved drift RMSE 12.6%. | Required 20% RMSE improvement was not reached; area error worsened 13.5%; hump backgrounds worsened and two historical weak components were lost. |
| Original ADAP 4.1.4 MCR kernel, with Mafer preprocessing | Matched settings suppressed extras and improved some mixture spectra. | More misses and wrong IDs; both configurations exceeded the real-run 180-second budget. |
| Original AMDIS 2.73, complete workflow | Completed all new cases; recovered 10/10 near-overlap truths versus 6/10; clean drifting blanks. | Overall misses doubled, extras/splits/wrong IDs increased. High resolution added splits without reducing misses. Ion-area accuracy unavailable. |
| Original ADAP-BIG 1.6.3 / ADAP 4.1.16, complete workflow | Strong overlap/asymmetric spectra; zero extras on the 110 jointly completed truth-bearing cases. | Additional weak/count-noise misses, ten native empty-EIC failures, and duplicate/output-volume concerns on public standards. |
| Original eRah 2.2.0, complete workflow | A distinct CMLC/OSD method was exercised. | 36/39 failed synthetic runs, large split/identity regressions, and real-data timeouts at 600 seconds. |
| MZmine 4.10.90 | Investigated as another external reference. | Not evaluated: its batch interface required unavailable local authentication. No analytical rejection can be inferred. |

## 1. Single-model-ion NNLS: original 48-case experiment

Baseline: coapex at `eda9a281c9a24897439d0b7c2ab08e805b156bb9`.
Use the existing 16 `synthetic-stress-1` scenarios with seeds 17, 29 and 43,
unchanged parameters and reference libraries. They comprise 48 cases and 90 true
components. These were existing diagnostic cases, not an independent holdout.

| Metric | Frozen coapex | Modelpeak | Verdict |
|---|---:|---:|---|
| Cases with a missed component | 19/48 | 19/48 | Fail: must decrease |
| Exact-coincident merge proxy | 9/9 | 8/9 | Fail: only 11.1% reduction; need at least 50% |
| False splits | 0 | 0 | Pass |
| Wrong tentative decoys | 3 | 3 | Pass; ideal target of at most 1 not met |
| Median paired overlap spectral-cosine change, 72 truths | Reference | −0.000988 | Fail: need at least +0.05 |
| Mean absolute unique-ion area relative error, 90 truths | 22.47% | 28.48% | Fail: 26.7% relative degradation |
| Definite / potential wrong tentative IDs | 3 / 24 | 4 / 26 | Fail: neither may increase |
| Rust warm-analysis median | 0.2385 s | No completed analysis | Inconclusive |
| Rust fresh-process peak RSS median | 526,385,152 bytes | No completed analysis | Inconclusive |

The area-error median worsened from 0.91% to 8.85%. The secondary 0.5-second
merge count stayed 3 versus 3. The first real modelpeak run exceeded the unchanged
1,000-component limit; Python and Rust both rejected it. No completed runtime,
memory ratio or real-output parity was established. Successful synthetic parity
at `rtol=1e-6, atol=1e-8` validates mechanics, not scientific usefulness.

### Reimplement the tested method

Preserve nominal-mass binning, smoothing/background removal, channel MAD noise,
ion-event detection, and all library thresholds. Change only extraction:

1. At each detected apex require `min_ions` maxima within the smaller of
   `coapex_seconds` and one median scan interval; apply the existing relative-ion
   cutoff. Do not consume a whole event when proposing a model.
2. Rank source events by prominence / 95%-prominence width (width floor one scan),
   then prominence, then apex/ion order. Prefer an ion having only one event in
   that window. This is an isolation heuristic, not chemical specificity.
3. Floor/ceil the source's 95%-prominence bounds; extend to at least 12 scans per
   side and clip to the acquisition. Subtract the line joining endpoints, clip
   nonnegative, and normalize at the candidate apex; skip a nonpositive apex.
4. Suppress overlapping, zero-extended profiles with cosine >=0.995. For each
   survivor choose at most one overlapping neighbor, nearest apex then earlier
   apex. Record additional overlaps and singular fits.
5. Fit every acquired ion to `a + b*n + c*M(n) [+ d*Y(n)]`, with centered scan
   coordinate, unrestricted intercept/slope and nonnegative model coefficients.
   Project off the affine baseline and enumerate empty, target-only, neighbor-only,
   and both active sets, retaining strictly lower residual sum of squares.
   Omit affine profiles when residual squared norm <=1e-12 times original squared
   norm; omit the two-model solve if its Gram determinant <=1e-12*g00*g11.
6. Positive target coefficients are apex intensities. Apply the unchanged global
   height fraction. Flag ions when whole-window RMSE >0.2*c, c/noise <3, or neighbor
   contribution at target apex >0.5*c. Integrate c times the model profile by
   trapezoids on actual scan seconds. Display summed unflagged-ion area, falling
   back explicitly to all positive ions. Evaluate unique-ion areas including
   flagged ions; the displayed clean-ion total is not their denominator.

This approximates Stein's model-peak equations; it is not AMDIS. Coincident
identical profiles are unidentifiable by shape. Contaminated model ions, narrow
apex support, and one-neighbor fitting remain limitations. The prototype also
had quadratic candidate comparisons before its output cap.

Original gates required fewer than 19 missed-component cases; at least 50%
reduction in exact-coincident merge proxies accompanied by additional two-component
recoveries; no added splits when baseline splits are zero; no more than three
legacy wrong decoys; median paired overlap cosine gain >=0.05 over all 72 overlap
truths; mean unique-ion area error <=1.1x baseline over all 90 truths; no increase
in definite or potential wrong tentative IDs; three completed Rust runs with
median warm runtime <=3x and fresh-process peak RSS <=2x baseline. Undefined
metrics do not pass. The failed gates are not to be relaxed retrospectively.

## 2. Paper-inspired ablations and external MCR kernel

Eleven fixed variants completed the 48 diagnostic cases plus 120 fresh cases:
1,848 synthetic analyses. The fresh set contains 225 truths, from 24 conditions
and five spectral/noise seeds (101, 211, 307, 401, 503). The same spectral set is
reused across conditions for each seed; these are not 120 independent mixtures.

| Variant | Missed / 225 | Extra detections | False splits | Incorrect tentative assignments | Mean spectral cosine | Mean unique-ion area error |
|---|---:|---:|---:|---:|---:|---:|
| `coapex` | 15 | 144 | 1 | 5 | 0.8659 | 11.96% |
| `modelpeak` | 12 | 202 | 48 | 33 | 0.8816 | 19.25% |
| `coapex-quality` | 15 | 144 | 1 | 5 | 0.8659 | 11.96% |
| `modelpeak-quality` | 12 | 202 | 48 | 59 | 0.8816 | 19.25% |
| `consensus` | 13 | 56 | 35 | 36 | 0.8905 | 9.61% |
| `consensus-quality` | 13 | 56 | 35 | 36 | 0.8905 | 9.61% |
| `stein-noise` | 15 | 116 | 1 | 5 | 0.8663 | 12.15% |
| `consensus-noise` | 13 | 56 | 35 | 36 | 0.8905 | 9.61% |
| `arpls` | 15 | 78 | 1 | 5 | 0.8655 | 13.58% |
| `adap-default` | 80 | 2 | 0 | 7 | 0.6277 | 36.88% |
| `adap-matched` | 22 | 2 | 1 | 11 | 0.8777 | 12.64% |

No variant passed every registered usefulness condition. In particular,
quality-weighting modelpeak produced 24 newly incorrect calls in drifting blanks.
Consensus's +0.0246 mean cosine gain had a descriptive paired case-bootstrap
interval of -0.0009 to +0.0514; do not claim universal improvement.

Real acquisition, three successful repetitions where available: Rust coapex
333 components / 0.256 s median analysis; Python coapex approximately 0.516 s;
consensus 269 / 6.096 s; noise-factor 328 / 0.613 s; arPLS 396 / 11.240 s.
Modelpeak variants exceeded the component cap. Both ADAP MCR configurations
failed to complete within a fixed 180-second total child-process budget. These
failures are not completed speed measurements; Python worker RSS excluded Java
peak memory. The real sample has no independently verified compound list.

### Reimplementation recipes

- **Quality matching:** retain square-root cosine, score threshold 0.75 and
  ambiguity margin 0.03. Per reference, omit flagged query ions absent from that
  reference from the query norm; multiply shared flagged dot-product terms by
  0.9; retain reference ions and all unflagged query ions. Sum retained terms
  directly to avoid cancellation. For coapex, flag ions whose unit-area profile
  L1 distance from the median component profile exceeds 0.2, or apex/noise <3.
  Do not use library identities or synthetic truth to set flags.
- **Consensus models:** gather one strongest event per ion within the full
  coapex radius, with existing relative-ion/minimum-ion cuts. Expand the seed's
  95%-prominence bounds 1.5x and to at least 12 scans per side. Do not subtract
  another endpoint baseline. Exclude ions with multiple events in the window;
  require cosine >=0.995 and at least two coherent ions. Sharpness is the mean
  largest fractional drop per scan on each side of the ion maximum; retain
  >=75% of maximum sharpness and at least two model ions. Sum/normalize models,
  rank by ion count, apex abundance, then apex/seed order, and suppress duplicate
  shapes at cosine >=0.995. Use the same one-neighbor NNLS/flags/area rule above.
- **Noise factor:** segment each raw ion and TIC into complete 13-scan blocks;
  reject blocks containing zero or fewer than seven strict crossings of their
  mean. Pool median(abs(block-mean))/sqrt(mean), take the pooled median, divide
  by 0.6744897501960817, then set channel noise to
  max(factor*sqrt(median(raw channel)),1). If no finite positive factor exists,
  explicitly fall back to original MAD noise. Keep the detector's 8x multiplier.
  This is constant channel noise, not full signal-dependent AMDIS noise analysis.
- **arPLS:** retain existing degree-two Savitzky–Golay smoothing, clip, MAD noise
  and all detection thresholds. Replace morphological background with per-channel
  solves `(diag(w)+lambda*D.T*D)z=w*y`, second differences with natural ends.
  Use a three-diagonal banded SPD solver; lambda is
  `(baseline_seconds/(2*pi*median_dt))^4`, baseline_seconds=60. Initialize w=1;
  use mean m/sample SD s of negative residuals, then
  `w_new=expit(-2*(residual-(2*s-m))/s)`, floored at 1e-12. Stop relative weight
  change <1e-6 or 50 solves. Retain/report nonconvergence and degenerate noise;
  constant channels return their constant baseline. Clip corrected signal only.
  This GC–MS scale adaptation was ours, not a paper recommendation.
- **ADAP kernel:** execute unchanged `Decomposition.run` from ADAP 4.1.4 in Java
  with Mafer corrected EICs/events, using floor/ceil 95%-prominence windows.
  MZmine host defaults: 0.2-minute window, 0.05-minute apex tolerance, minimum
  cluster 1, no parabola adjustment. Matched setting: tolerance 0.5 s, cluster 3;
  other settings unchanged. Preserve native >4 ion-events-per-window restriction,
  40,000 iteration limits, 1e-12 factorization and 1e-10 regression tolerance.
  Per-ion area is native apex coefficient times trapezoid(profile/max(profile))
  in seconds. Java 17+, 1 GiB heap; include startup/transport in the comparison.

Matching usefulness required fewer definite wrong tentative IDs, no increase in
possible wrong IDs, and retention of >=95% uniquely assessable correct tentative
IDs. Extraction required >=20% fewer misses and either +0.02 mean all-truth cosine
or >=10% lower area error, without increased false detections or wrong identities.
ArPLS required >=20% lower drift RMSE, no more misses/false detections/wrong IDs,
and <=10% worse overall area error. All candidates also had to complete the real
sample under 1,000 components. Runtime >3x Python control was a separate concern.

## 3. Original complete external workflows

These tools received raw scans and performed their own preprocessing, detection
and deconvolution. They did not receive Mafer peak proposals or truth identities.
This is separate from the older ADAP MCR-only experiment above. Independent
synthetic draws used seed `910001 + 1009*i + 37*j`, scenario i=0..23, replicate
j=0..4; 120 cases / 225 truths. Coapex Python/Rust controls agreed on component
counts, RT, status and leading reference; maximum score difference 4.45e-16.

| Workflow | Failures / 120 | Missed / 225 | Extras observed | False splits | Wrong tentative: definite / possible | Mean cosine ↑ | Mean unique-ion area error ↓ |
|---|---:|---:|---:|---:|---:|---:|---:|
| Current coapex | 0 | 14 | 144 | 2 | 5 / 16 | 0.864 | 12.4% |
| AMDIS default | 0 | 28 | 233 | 32 | 12 / 32 | 0.841 | Unavailable |
| AMDIS high resolution | 0 | 28 | 305 | 75 | 21 / 46 | 0.834 | Unavailable |
| ADAP-BIG default | 10 | 59 | 0 | 0 | 5 / 15 | 0.728 | 29.6% |
| ADAP-BIG matched | 10 | 40 | 0 | 0 | 5 / 15 | 0.813 | 21.8% |
| eRah default thresholds | 36 | 118 | 60 | 56 | 15 / 16 | 0.457 | 78.2% |
| eRah matched | 39 | 107 | 160 | 66 | 17 / 18 | 0.499 | 76.1% |

Misses include truths in failed runs. Extras/splits/wrong IDs count observed
outputs from completed runs and are incomplete when a method fails. A failed
blank is not a successful zero-false-positive result. All identity counts here
use the unchanged Mafer matcher applied to external spectra, not native tool
identification performance. AMDIS per-ion areas remain unavailable throughout.

AMDIS default's near-overlap cosine improved 0.526→0.924, but its overall cosine
difference had descriptive bootstrap interval -0.057 to +0.008. Matched ADAP-BIG
reduced extras 73→0 on 110 jointly completed truth-bearing cases; the remaining
71 coapex extras came from drifting blanks where ADAP failed. Matched ADAP gained
26 additional misses: 15 weak-component, five count-noise, four shared-dominant,
one near-overlap and one triple-overlap. These configuration trade-offs block
promotion despite useful spectra.

### Exact external implementations and transport requirements

| Tool | Version and acquisition/settings |
|---|---|
| AMDIS | Official NIST 2.73 Windows executable. Run under Wine 8.0 / Debian Bookworm linux/amd64 with Xvfb for the original GUI. Raw ANDI-MS/netCDF input; Simple analysis (`/S /E`), keep results. Reset **Settings → Default**, not the installer's personalized INI. Width 12 scans; subtract one adjacent peak; Medium resolution/sensitivity/shape; TIC model allowed; filters off; automatic mass bounds; native library minimum match 60. Secondary changes only resolution to High, not width/sensitivity. |
| ADAP-BIG | Release 1.6.3, original kernel 4.1.16; Temurin 21.0.12.1+1, 2 GiB heap, one active processor. Run original importer, chromatogram builder, wavelet detector and MCR; omit only multi-sample downstream alignment/statistics. Export raw ANDI-MS/netCDF with unchanged intensity scale. |
| eRah | CRAN 2.2.0 on R 4.5.2, sequential futures, random seed 20260924. Supply native `RawDataParameters`/`.rdata` and call `newExp(createInstrumentalTable(...))`, then `deconvolveComp(...)`. This avoids an upstream CDF reader dropping the final scan / requiring a 500-mass random sample. No Mafer preprocessing. |

ADAP-BIG uses shipped low-mass settings: mass tolerance 0.5 Da; scan span 3;
builder height 1,000, relative intensity 0.009; wavelet SNR 10 with intensity_window;
feature height 1,000; widths 1.2–60 s; CWT scales 0.06–3.6 s; coefficient/area
threshold 0; MCR window 12 s; RT tolerance 1.2 s; cluster 5; no apex adjustment.
Matched mode changes only widths to 0.6–30 s, RT tolerance to 0.5 s and cluster to 3.
The 1,000-count cutoff is not a calibrated universal sensitivity threshold.
Both modes failed when zero EICs caused peak detection to omit its output and
native deconvolution then requested a missing file. Preserve such failures.

Both eRah modes use minimum width 0.6 s, all acquired masses, compression 2,
analysis.time=0 and no downsampling or virtual sampling. Default height/noise are
2500/500, matched 100/100. The package's fixed 100-count channel floor remains;
noise.threshold is stored but not used in its main factor extraction. The width
parameter is not Mafer FWHM. Native degenerate-table errors (six column names for
a two-column table) are failures, distinct from valid completed no-detection runs.

Validate units and native semantics before scoring:

- AMDIS alternatives group by exact native RT, agreeing with FIN `NC`. `OR`
  defines displayed model order; `MP` identifies extraction variants, including
  `MPTIC`. Choose lowest positive OR; flag zero/tied order and keep native file
  ordering plus every alternative. Do not group by apex scan. `FR` bounds are
  zero-based inclusive. RT quantization permits at least 0.00300001 s edge
  tolerance. Native scan-sum/normalized values are not seconds-integrated ion
  areas. The study corrected these transport interpretations by reparsing saved
  exports without changing processing parameters. Native identification uses
  shipped ONSITE.MSL; its influence on model ordering was not established.
- ADAP-BIG apex/bounds/profile RT are minutes; convert to seconds. Native area is
  intensity×minutes; retain native spectrum/model and verify per-ion scaling on
  an independent known Gaussian before scoring. Do not synthesize a profile.
- eRah native RT uses a one-based scan index rounded to four minute decimals.
  Recover the zero-based index and interpolate onto actual scan times, retaining
  the correction. Native area is rounded sum(C) in intensity×scans; spectral S
  is rounded to 1000 with tiny ions truncated. Derived per-ion area is
  native_Area*median_dt*exported_ion/1000, a rounded rectangle approximation.
- For non-AMDIS float edges accept only max(1e-5 s,2e-7*max|time|) roundoff, then
  clamp; larger out-of-acquisition coordinates fail. Distinguish missing quantities
  from zero. Check scan counts, mass/intensity mapping, timing and repeated outputs
  on independent simple signals before using scored cases.

The external extraction gate required >=20% fewer misses, either +0.02 cosine or
>=10% lower area error, and no increase in extras, splits or wrong-ID bounds.
An alternative background-suppression gate required >=20% fewer extras, no more
misses/splits/wrong IDs, cosine loss <=0.01 and >=95% retained uniquely assessable
correct tentative matches. Missing metrics/failures do not pass. Time limits were
300 s per synthetic case and 600 s per real run; real candidates must fit the
existing 1,000-component cap. Do not infer future Rust speed from Java/R/Wine.

### Laboratory and private-sample observations

Public input: metaMSdata 1.42.0 `STDmix_GC_01.CDF`, with reference spectra and
approximate RTs from separate injection 03. Check ±3 seconds around Linalool
1071.6 s, Methyl salicylate 1346.4 s and Ethyl hexanoate 646.2 s. This provides
three positive checks, not a complete truth list, global false-positive rate,
or area-accuracy measure.

| Workflow | Components | Known standards recovered | Nearby tentative assignments | Observed seconds |
|---|---:|---:|---:|---:|
| Current coapex | 365 | 3 / 3 | 3 | 0.32 |
| AMDIS default | 394 | 3 / 3 | 6 | 133.62 |
| AMDIS high resolution | 541 | 3 / 3 | 6 | 140.41 |
| ADAP-BIG default | 591 | 3 / 3 | 4 | 146.29 |
| ADAP-BIG matched | 2,691 | 3 / 3 | 9 | 125.64 |
| eRah default thresholds | Timeout | Unmeasured | — | 600.22 |
| eRah matched | Timeout | Unmeasured | — | 600.28 |

For the private acquisition (no verified identities):

| Workflow | Components | Tentative / ambiguous / unassigned | Observed seconds |
|---|---:|---:|---:|
| Current coapex (Rust) | 333 | 24 / 46 / 263 | 0.27 |
| AMDIS default | 446 | 75 / 162 / 209 | 187.34 |
| AMDIS high resolution | 578 | 96 / 214 / 268 | 185.32 |
| ADAP-BIG default | 351 | 49 / 136 / 166 | 242.75 |
| ADAP-BIG matched | 638 | 67 / 189 / 382 | 239.41 |
| eRah default thresholds | Timeout | Unmeasured | 600.37 |
| eRah matched | Timeout | Unmeasured | 600.28 |

All real timings above are single observed runs including external transport and
startup/compatibility overhead; some offline jobs ran concurrently. They are not
controlled cross-language speed benchmarks. More tentative names are not evidence
of better chemistry. Public matched ADAP's 2,691 outputs exceeded the app's normal
component budget; recovering three standards does not justify that output volume.

## Recreate the case families for a future experiment

Use the retained production 48-case generator as the diagnostic control. For fresh
cases, use 0–100 s at dt=0.1 s and nominal m/z 40–140 inclusive. With a seeded
NumPy generator, permute masses; each of three signatures has three common and
five unique masses, abundances uniform 15–100 and max-normalized to 100. Default
components have centers 35+uniform(-0.5,0.5) s plus 30 s separation, Gaussian sigma
0.75+uniform(0,0.4), relative amounts 1/0.4/0.15 and profile scale 100. Sum noiseless
signals and retain per-ion trapezoid areas/unique masses as truth. Background is
(30+0.2*t) times channel scale uniform(0.3,1.5); add independent normal noise SD 5
and clip nonnegative. Add 12 unrelated eight-ion references with abundances 10–100.

The 24 conditions, in seed-formula order:

| Index | Condition | Changes to defaults |
|---|---|---|
| 0 | clean | None |
| 1 | overlap-moderate | separation=3.0 |
| 2 | overlap-strong | separation=1.2 |
| 3 | overlap-near | separation=0.4 |
| 4 | coincident | separation=0.0 |
| 5 | weak-10-overlap | separation=1.2, ratio=0.1 |
| 6 | weak-1-overlap | separation=1.2, ratio=0.01 |
| 7 | weak-1-separated | separation=3.0, ratio=0.01 |
| 8 | trace-noisy | ratio=0.002, noise=25.0 |
| 9 | tailing | separation=2.2, shape=tail |
| 10 | fronting | separation=2.2, shape=front |
| 11 | unequal-widths | separation=1.6, widths=[0.5, 1.4] |
| 12 | triple-overlap | count=3, separation=1.4 |
| 13 | baseline-hump | background=hump |
| 14 | baseline-wave | background=wave |
| 15 | baseline-quadratic | background=quadratic |
| 16 | count-noise | count_noise=True, ratio=0.05 |
| 17 | shared-dominant | separation=1.4, shared_dominant=True |
| 18 | fast-scans | separation=1.2, dt=0.08 |
| 19 | slow-scans | separation=1.2, dt=0.16 |
| 20 | missing-reference | reference=missing |
| 21 | similar-decoy | reference=decoy |
| 22 | blank | count=0, noise=25.0 |
| 23 | drift-blank | count=0, noise=25.0, background=wave |

Tailing/fronting multiply sigma on the respective side by 2.2. Hump adds a
500-count Gaussian centered 50 s with sigma 16 s; wave adds
180*(1+sin(3*pi*t/100)); quadratic adds 0.1*(t-25)^2 before channel scaling.
Count-noise draws Poisson(signal+background) before normal noise. Shared-dominant
multiplies shared ions by five before signature normalization. Missing-reference
removes compound 2; decoy renames compound 2 and alternates its reference ion
scales 0.9/1.1. The table records historical settings, not permission to reuse
inspected seeds as an unseen holdout. Pin random generator/library versions and
freeze new input hashes before comparing any revised implementation.

### Measurement contract and future acceptance

1. Freeze the hypothesis, inputs, thresholds, failure handling and gates before
   scoring. Record source/tool versions and hashes. Use independent development
   mixtures for sensitivity calibration and fresh held-out seeds for decisions.
2. Match detections to truth by maximum cardinality within 0.75 s, then minimum
   RT error, without reference identities. Preserve ambiguous correspondences.
   For spectral diagnostics only, use a separate one-to-one truth-assisted pairing
   within that same RT bound, maximizing spectral agreement after cardinality.
3. Retain every truth in denominators: missed cosine is zero and measurable
   unique-ion area error is 100%. AMDIS unavailable areas remain unavailable,
   including misses. Report extras, false splits (extra detections near a truth),
   and definite/possible wrong tentative bounds. An identity is definitely wrong
   if it matches no eligible truth, potentially wrong if any eligible truth is
   absent from its names. Do not credit an unresolved pair as confidently correct.
4. Keep Mafer matching fixed (square-root cosine, 0.75 screening, 0.03 margin).
   Report diagnostic and fresh sets separately, all failures, scenario regressions,
   absolute metrics and paired changes. Case bootstrap: seed 404, 2,000 resamples;
   also resample five seed blocks for the first fresh set's dependence. Intervals
   describe synthetic inputs, not population laboratory accuracy.
5. Validate mechanics independently: NNLS against SciPy/dense active sets,
   banded arPLS against dense equations, native export units against a known
   Gaussian, and observed exports against the original GUI where needed.
   Verify the frozen coapex control still matches. Keep synthetic truth out of
   extraction and real analyst decisions out of the ground truth.
6. Test independent laboratory standards, blanks and replicates. Separate scientific
   usefulness from completion/runtime/memory. If an idea passes, implement only
   that bounded method in Rust and verify numerical equivalence before integrating.

Promising next hypotheses are noise-calibrated background rejection and isolating
ADAP native detection from its MCR stage. Use the same ADAP 4.1.16 kernel/settings
on both branches; comparing to 4.1.4 confounds stage and version effects. Require
weak recovery, correct empty-input handling and control of duplicate components.
Use AMDIS default as an independent comparator. Do not port an entire failed
pipeline, reuse a failed matcher, or loosen thresholds to make these results pass.

## Sources and pinned external inputs

- Stein (1999), model-peak least-squares/noise/identification method:
  [paper](https://chemdata.nist.gov/dokuwiki/lib/exe/fetch.php?media=chemdata:method.pdf),
  [DOI 10.1016/S1044-0305(99)00047-1](https://doi.org/10.1016/S1044-0305(99)00047-1).
- Baek et al. (2015), arPLS:
  [DOI 10.1039/C4AN01061B](https://doi.org/10.1039/C4AN01061B).
  Its published validation is Raman/simulated spectra; GC–MS use here was experimental.
- Smirnov et al. (2019), ADAP-GC 4.0:
  [original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC6705124/).
  Kernel 4.1.4 came from author MZmine commit
  `c8e1f6c844760e095c88eac92d3b2e5f9eb17b24`; JAR SHA-256
  `98e84ba2d5030c670c030bce12f56d4227ae769cbe1b70be683826b98f0759c6`.
- [ADAP-BIG 1.6.3 release](https://github.com/ADAP-BIG/adap-big.github.io/releases/tag/v1.6.3),
  [manual](https://adap-big.github.io/user-manual.html); JAR SHA-256
  `100cc5e2b47dd7ea396017ecb74aca3c216b3107f53a60327362144bf50ad0ed`.
- [NIST AMDIS](https://chemdata.nist.gov/dokuwiki/doku.php?id=chemdata:amdis),
  [manual](https://www.nist.gov/system/files/documents/srd/AMDISMan.pdf).
  AMDIS_Installer-17.zip SHA-256
  `74dd1dd5ebe489f9c13b4d5193f0ff2d92cd6f56105f2031ddcddd3a21d42807`;
  AMDIS_32.exe SHA-256
  `ab11bd8f092be88446198975968015e8f4558fa4699e81beebedbf5680e2fdde`.
- Domingo-Almenara et al. (2016), eRah:
  [DOI 10.1021/acs.analchem.6b02927](https://doi.org/10.1021/acs.analchem.6b02927),
  [CRAN](https://cran.r-project.org/package=erah), source archive 2.2.0 SHA-256
  `e9b796489ff69fd59d9aa104e9273246c2c9ccb0e1bf412c29cefd9858b27b48`.
- [metaMS laboratory workflow](https://bioconductor.org/packages/release/bioc/vignettes/metaMS/inst/doc/runGC.pdf).
  metaMSdata 1.42.0: STDmix_GC_01.CDF SHA-256
  `b0eba20810a89f99a0c3027d92b7aeef7caa5ae53e44b90c04953e7323b1cba8`;
  threeStdsDB.msp `8e745b34f9706646b47420312b76c3a57af183dd92be39e3e71bcb2c32d7398e`;
  threeStdsInfo.csv `0ddacba9881eb8b61a49df8bb77abd8752f158f6131f7482ffd64a1b57574f56`.

External Java/R tools carry their own licenses (including GPL); NIST binaries
also have distribution terms. The application contains no copied external
implementation or bundled binary. A future port/distribution requires checking
upstream terms rather than treating a wrapper as permission to redistribute.
