# Implementations

- [python/gcms](python/gcms/): API, CLI, input validation, reports and NumPy/SciPy baseline.
- [rust](rust/): optional numerical kernels loaded by the Python application.

Rust was faster here because its compiled peak-processing loops stop searching
at zero background and skip exact-zero spectral products. Both engines reuse
compatible filtered signals during review; Python also reuses noise and prepared
references. NumPy/SciPy already run native code, so the workload matters too.

Python's latest paired review trials improved its overall median from **2.882 s
to 2.707 s**. Additional Rust reuse was tested and omitted after mixed timings;
its existing engine measured roughly **1.3–1.4 s** in those comparisons. Both share
Python input/report code. Direct Rust grouping subsequently lowered review
medians about 3% in two noisy batches. See [measurements and build instructions](../docs/benchmarks.md).
