# Scientific decisions and evaluation

[Documentation](README.md) · [Project](../README.md)

The output is a list of candidate chromatographic components and proposed
identities, with enough evidence to review the result. There is no ground-truth
identity list, calibration mixture, blank acquisition or replicate real run.
Consequently real-sample identification accuracy and concentration are unmeasured.
The original acquisition and library are not distributed with this repository.
Sample-specific counts below describe the saved evaluation results in `examples/`.

## Processing

Algorithm `coapex-1` is a deliberately limited baseline. These rules also specify
the behavior a Rust implementation must reproduce to claim a performance comparison.

1. **Read and bin.** Validate complete ChemStation scan records, then decode using
   rainbow-api. Round masses to nearest nominal integer, ties to even, and sum
   intensities. Create a contiguous scan×mass float64 matrix spanning the observed
   mass range, filling absent masses with zero. Verify decoded scan totals and
   times against the raw records. Preserve all scan times in seconds.
2. **Smooth and subtract background.** Independently smooth each ion trace using
   a degree-2 Savitzky–Golay filter, `mode=interp`, default 0.8-second window;
   clip negative values to zero. A grey morphological opening, `mode=nearest`,
   default 60-second window estimates background. Subtract and clip again. Convert
   seconds to scans using the median interval, nearest integer/ties to even,
   then increase an even window by one; cap to the largest odd run length.
   A smoothing window smaller than three scans skips smoothing.
3. **Estimate noise.** For each original ion trace, take successive differences,
   subtract their median, and divide their median absolute deviation by
   `0.9538725524`. This is a Gaussian-equivalent estimate with a one-count floor;
   it is a heuristic for these instrument values, not a measured detection limit.
4. **Find ion peaks.** SciPy `find_peaks` uses prominence at least
   `noise_multiplier × noise` (default 8), and half-prominence widths between
   0.6 and 30 seconds. Convert width limits using the median scan interval.
   Determine integration bounds at 95% of prominence with `peak_widths`.
   Both engines first reject peaks whose height is below the prominence threshold;
   on these nonnegative traces that is an equivalent, cheaper rejection.
5. **Group and reconstruct.** Sort events by scan then mass channel, then visit
   seeds by descending prominence with stable ties. Gather unused events within
   ±0.5 seconds of the seed in scan coordinates. Remove ions below 1% of the
   group's largest event height; keep the strongest event per ion. Require at
   least three ions. A rejected seed is consumed; an accepted group consumes all
   nearby unused events. Construct a spectrum from its selected ions, averaging
   the seed scan and its immediate neighbors; all other masses remain zero.
   Require summed spectrum intensity at least 0.001 of the maximum corrected TIC.
   This global fraction suppresses weak detections but can miss minor constituents.
6. **Integrate.** Use the floor/ceiling of the median ion bounds, ensuring at least
   one scan on either side of the seed and clipping to the acquisition. Trapezoidally
   integrate the corrected sum of selected ions against actual seconds. Sort
   reported components by apex scan and then ion indices. `area_percent` uses the
   sum of these reported areas as its denominator. Selected-ion areas can overlap
   and are neither a disjoint TIC partition nor mass fractions.
7. **Compare spectra.** Project each reference onto the same acquired mass range,
   round/sum as above, take square roots of both intensity vectors, L2-normalize,
   and calculate their dot product, clipped to [0, 1]. A zero spectrum normalizes
   to zero. Keep missing ions as zeros across the full acquired grid. References
   with zero projected intensity are excluded from ranking. Reference intensity
   outside the acquired range is excluded from the score but its fraction is reported.
8. **Report uncertainty.** Keep the top three distinct reference groups by default;
   exact score ties retain original group order. A best score ≥0.75 and retained
   reference intensity ≥0.5 pass screening. A second group within 0.03 of the best,
   or conflicting identities within the best group, yields `ambiguous`; otherwise
   the result is `tentative`. Failing screening yields `unassigned`. None is a
   probability. These thresholds are adjustable, uncalibrated starting settings.

The spectral-change diagnostic is `1 − square-root cosine` between the full
corrected spectra halfway from the start to apex (floor scan) and halfway from
apex to end (ceiling scan). Values over 0.1 flag possible co-elution or spectral
change. A zero-norm comparison gives 1. This diagnostic can miss co-elution and
can react to noise; it is not a purity measure.

Co-apex grouping is **not complete deconvolution**. Two substances peaking together
can merge; asymmetric peaks and displaced ion maxima can split one substance into
several detections. Shared ions can bias both spectra and areas. Retention times
are measured from the acquisition, but library RT/RI is preserved only as metadata
because compatible columns, methods and reference interpretation are unverified.

The TIC preview preserves raw-TIC extrema in up to 1,500 scan buckets, acquisition
endpoints and every detected apex. Corrected/baseline traces use the same selected
scans. It is a display reduction; processing uses the full arrays.

## Per-peak stability and review

The optional `review` workflow uses method `stability-1`, preserving the original
`coapex-1` analysis as its baseline. It repeats processing with six alternatives
relative to the supplied baseline parameters:

| Profile | Changes | Default values tested |
|---|---|---|
| Permissive | Noise multiplier ×0.75; minimum component fraction ×0.5 | 6; 0.0005 |
| Conservative | Noise multiplier ×1.5; minimum component fraction ×2 | 12; 0.002 |
| Less / more smoothing | Smoothing duration ×0.5 / ×2 | 0.4 / 1.6 s |
| Narrow / wide grouping | Co-apex tolerance ×0.5 / ×1.5 | 0.25 / 0.75 s |

All other parameters stay fixed. Invalid or duplicate parameter profiles are
skipped explicitly; failed analyses retain their error. Values are not clamped
to force a test to run. These perturbations are a heuristic sensitivity check,
not a calibrated model or a search for the true identity.

A baseline component and an alternative are compatible when apex times differ
by at most 0.75 s and their reconstructed spectra have square-root cosine
similarity at least 0.8. A unique match requires each component to have exactly
one compatible counterpart. Competing edges remain ambiguous; the method does
not force a correspondence through a split or merge.

- **Consistent:** all six alternatives complete, uniquely match, and keep the
  same nonempty top reference group.
- **Sensitive:** at least one completed alternative has no compatible match or
  a uniquely matched component changes the top group. This takes precedence if
  other alternatives are incomplete or ambiguous.
- **Inconclusive:** remaining cases, including incomplete tests, ambiguous
  correspondence or no reference candidate.

`match_fraction` is unique matches divided by completed alternatives, excluding
baseline. Ambiguous/no-match observations remain in that denominator; skipped
and failed profiles do not. No compatible match can mean changed detection or
changed spectrum, not necessarily absence of signal. Apex shifts and area-ratio
ranges use only unique alternative matches relative to the baseline. Stability
does not require unchanged area or screening status; those are retained as
separate observations. A stable reference group can contain conflicting names.

Only baseline detections receive detailed annotations. Each profile separately
counts alternative detections not uniquely paired to baseline, including competing
correspondences. The supplied sample gives 333 baseline detections and respectively
800, 174, 370, 280, 367 and 307 detections in the six alternatives. Both engines
produce **45 consistent, 288 sensitive and 0 inconclusive** annotations. This does
not imply 45 correct identifications or 288 false detections.

Each local plot contains raw/corrected TIC, the corrected sum of all selected
ions used for area, integration boundaries and apex. Up to five strongest selected
ion traces are normalized separately to compare shapes. Windows over 400 scans
use min/max points across 24 buckets for all displayed traces, retaining endpoints,
apex and integration bounds. The supplied sample needs no local downsampling.
Numerical processing and area integration always use full arrays.

The packet selects up to two unused, largest-area examples each of consistent
tentative results, ambiguous identities, sensitive results, inconclusive results
and unassigned results, then fills to 12 by descending area. It records selection
reasons and leaves analyst findings blank. It is purposive and biased toward
large signals; do not calculate sample-wide accuracy from it. Use it to obtain
expert feedback and design a separate, independently verified evaluation set.

## Library ambiguity

The supplied library contains 957 entries: 120 labelled `Propia` and 837 `NIST`.
Sorting each spectrum's mass/intensity pairs and grouping exactly equal float64
pairs yields 812 groups. Of 112 groups containing multiple entries, 79 contain
different names and 51 contain different nonempty CAS identifiers. The 112 groups
contain 257 entries. There are 101 distinct reference RT values.

All names, CAS identifiers and source entries remain attached to their shared
spectrum. The grouping is exact, not approximate or scale-normalized. Different
spectra that become identical after projection can still tie during scoring.
CAS is used as the identity key when present, otherwise the case-folded name;
different names with the same CAS therefore remain synonyms for screening.
Conflicting library metadata is preserved, not silently repaired. Identical
spectral evidence cannot select a unique label among conflicting references.

## Measured results

The supplied sample contains 17,749 scans across m/z 40–320, from 5.455 to
3,599.750 seconds. The approximately 60-minute time axis belongs to the recorded
experiment, not the software execution.

Default settings produce **333 candidate components: 24 tentative, 46 ambiguous,
263 unassigned**. These are processing outputs, not a count of verified chemicals.
Selected examples in the [saved report](../examples/sample.html):

| Component | Apex (min) | Top spectral evidence | Interpretation |
|---|---:|---|---|
| 0091 | 35.623 | Hydroxy Citronellal / Octanal, 7-hydroxy-3,7-dimethyl-; 0.9742 | Tentative; shared CAS, score margin 0.1046 |
| 0083 | 34.799 | Phenyl Ethyl Alcohol / Dipropylene glycol (isomer 2) | Conflicting library identities; inspect the ambiguity warning |

These names reproduce library annotations and have not been independently confirmed.

The reproducible [evaluation output](../examples/evaluation.json) measures:

| Controlled input | Expected / detected | Missed / extra | Apex error | Relative area error |
|---|---:|---:|---:|---:|
| Two isolated synthetic peaks | 2 / 2 | 0 / 0 | 0 s | 1.06%, 1.08% |
| Two partially overlapping synthetic peaks | 2 / 2 | 0 / 0 | 0 s | 0.12%, 6.53% |
| Synthetic background/noise only | 0 / 0 | 0 / 0 | N/A | N/A |

Both nonblank cases return the expected identity in the top reference group.
Signals are Gaussian with known spectra, shared ions, a drifting baseline and
seeded Gaussian noise. This small favorable test set checks mechanics; it does
not establish broad detection performance or real chemical identification accuracy.
Synthetic detection matching maximizes the number of pairs within 0.75 s, then
minimizes total time error without considering identity labels. Competing
compatible partners leave identity and area metrics undefined (`null`).
Precision/recall are undefined (`null`) where their denominators are zero.

Evaluation version `2.0` also retains 48 harder synthetic cases. Nineteen cases
miss at least one known component, and three deliberately similar but incorrect
reference cases produce a wrong tentative match. These failures are included in
the results. The conditions and limits of every claim are documented in
[validation.md](validation.md). These are constructed diagnostics, not a chemical
accuracy estimate or an independent held-out benchmark.

### Sensitivity on the real sample

| Settings (noise multiplier; minimum TIC fraction) | Components | Tentative / ambiguous / unassigned | Default detections retained | Same top group among matches |
|---|---:|---|---:|---:|
| Permissive (6; 0.0005) | 800 | 31 / 50 / 719 | 100% | 81.7% |
| Default (8; 0.001) | 333 | 24 / 46 / 263 | 100% | 100% |
| Conservative (12; 0.002) | 174 | 20 / 43 / 111 | 52.3% | 86.8% |

This is a substantial sensitivity, particularly for weak features. Time-based
matching can also associate nearby fragments of an oversegmented peak. These
figures measure stability, not correctness. Do not select settings by maximizing
the number of named detections. The default was chosen as a screening starting
point and has not been optimized against independent truth.

## Highest-value next steps

1. **Obtain reference annotations and standards.** Ask the analyst for verified
   identities, blanks, replicates and known mixtures, marking which annotations
   are confirmed. Separate complete truth lists from partial ones. Measure
   detection precision/recall, top-k group inclusion, wrong confident assignments,
   abstention rate and area repeatability on held-out runs. Keep exact-spectrum
   groups together when splitting reference data to avoid duplicate leakage.
2. **Resolve library provenance.** Have the lab review the 51 conflicting-CAS
   groups and explain the RT/RI fields. Version corrections while retaining source
   records. Measure unresolved conflicts and reviewed false assignments. Add a
   retention filter only after method compatibility or measured RI calibration.
3. **Improve overlapping-peak treatment.** Use known mixtures with decreasing
   separation and concentration ratios to compare this baseline with established
   deconvolution or chromatographic profile fitting. Measure recovered components,
   false splits/merges, spectral error and area error before changing the method.
4. **Keep performance and method changes separately measurable.** The Rust
   engine now reproduces the numerical baseline and review output. Preserve
   that contract when optimizing; evaluate scientific method changes under a
   new version with independent evidence.

## Methods and reused tools

rainbow-api handles proprietary decoding; our code validates records and decoded
totals, parses/audits MSP, groups ion peaks, constructs reports and evaluates them.
The method is not an implementation of AMDIS. Relevant primary documentation:

- [rainbow ChemStation decoder](https://rainbow-api.readthedocs.io/en/latest/_modules/rainbow/agilent/chemstation.html)
- [SciPy Savitzky–Golay filter](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html)
- [SciPy morphological opening](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.grey_opening.html)
- [SciPy peak detection](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html)
- [NIST AMDIS explanation](https://chemdata.nist.gov/dokuwiki/doku.php?id=chemdata%3Aamdisexplained)
