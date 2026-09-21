# Implementations

- [python/gcms](python/gcms/): API, CLI, input validation, reports and NumPy/SciPy baseline.
- [rust](rust/): optional numerical kernels loaded by the Python application.

Rust was faster in our measurements because it compiles the peak-processing loops
to native code and, during stability checks, filters candidate peak pairs by time
before comparing spectra. NumPy/SciPy already run much of their work in native
code, so the benefit depends on the algorithm and workload, not just the language.

Measured warm medians were **0.678 s vs 0.438 s** for one analysis (**1.55×**) and
**5.598 s vs 3.374 s** for the full review (**1.66×**), Python then Rust. Both use
the same Python reader and report code. See [benchmarks and build instructions](../docs/benchmarks.md).
