//! Single-threaded float64 kernels for coapex-1; Python owns ingestion and reports.
use numpy::{IntoPyArray, PyArray1, PyArray2, PyReadonlyArray1, PyReadonlyArray2, ndarray::Array2};
use pyo3::{exceptions::PyValueError, prelude::*};
use std::collections::VecDeque;

fn invalid(message: &str) -> PyErr {
    PyValueError::new_err(message.to_owned())
}

fn median(values: &mut [f64]) -> f64 {
    let length = values.len();
    let mid = length / 2;
    let (left, center, _) = values.select_nth_unstable_by(mid, f64::total_cmp);
    let high = *center;
    if mid * 2 == length {
        (left.iter().copied().fold(f64::NEG_INFINITY, f64::max) + high) / 2.0
    } else {
        high
    }
}

fn matrix<'py>(
    py: Python<'py>,
    rows: usize,
    cols: usize,
    data: Vec<f64>,
) -> Bound<'py, PyArray2<f64>> {
    Array2::from_shape_vec((rows, cols), data)
        .expect("internal matrix shape")
        .into_pyarray(py)
}

// Centered sliding minimum/maximum, nearest endpoint extension, O(n).
fn extremum(x: &[f64], radius: usize, maximum: bool) -> Vec<f64> {
    let mut deque: VecDeque<usize> = VecDeque::new();
    let mut output = vec![0.0; x.len()];
    let mut next = 0;
    for (i, value) in output.iter_mut().enumerate() {
        let end = (i + radius + 1).min(x.len());
        while next < end {
            while let Some(&last) = deque.back() {
                if if maximum {
                    x[last] <= x[next]
                } else {
                    x[last] >= x[next]
                } {
                    deque.pop_back();
                } else {
                    break;
                }
            }
            deque.push_back(next);
            next += 1;
        }
        while deque.front().is_some_and(|&j| j < i.saturating_sub(radius)) {
            deque.pop_front();
        }
        *value = x[*deque.front().unwrap()];
    }
    output
}

fn smooth(x: &[f64], coefficients: &[f64]) -> Vec<f64> {
    let n = coefficients.len();
    if n < 3 {
        return x.to_vec();
    }
    let half = n / 2;
    let mut result = vec![0.0; x.len()];
    // convolve1d reverses coefficients; preserve its symmetric summation order.
    let weights: Vec<f64> = coefficients.iter().rev().copied().collect();
    let symmetric = (0..half).all(|i| (weights[i] - weights[n - 1 - i]).abs() <= f64::EPSILON);
    for i in half..x.len() - half {
        let value = if symmetric {
            let mut sum = x[i] * weights[half];
            for j in 0..half {
                sum += (x[i - half + j] + x[i + half - j]) * weights[j];
            }
            sum
        } else {
            let mut sum = x[i + half] * weights[n - 1];
            for j in 0..n - 1 {
                sum += x[i - half + j] * weights[j];
            }
            sum
        };
        result[i] = value.max(0.0);
    }
    // Fit degree-2 polynomials to complete endpoint windows (SciPy mode=interp).
    let s2: f64 = (0..n).map(|j| (j as f64 - half as f64).powi(2)).sum();
    let s4: f64 = (0..n).map(|j| (j as f64 - half as f64).powi(4)).sum();
    let determinant = n as f64 * s4 - s2 * s2;
    for (edge, start) in [0, x.len() - n].into_iter().enumerate() {
        let (mut sy, mut sxy, mut sxxy) = (0.0, 0.0, 0.0);
        for j in 0..n {
            let v = j as f64 - half as f64;
            sy += x[start + j];
            sxy += v * x[start + j];
            sxxy += v * v * x[start + j];
        }
        let a = (s4 * sy - s2 * sxxy) / determinant;
        let b = sxy / s2;
        let c = (n as f64 * sxxy - s2 * sy) / determinant;
        let range = if edge == 0 { 0..half } else { n - half..n };
        for j in range {
            let v = j as f64 - half as f64;
            result[start + j] = (a + b * v + c * v * v).max(0.0);
        }
    }
    result
}

type Prepared<'py> = (
    Bound<'py, PyArray2<f64>>,
    Bound<'py, PyArray1<f64>>,
    Bound<'py, PyArray1<f64>>,
);

#[pyfunction]
fn preprocess<'py>(
    py: Python<'py>,
    data: PyReadonlyArray2<'py, f64>,
    coefficients: Vec<f64>,
    baseline_n: usize,
) -> PyResult<Prepared<'py>> {
    let input = data.as_array();
    let (rows, cols) = input.dim();
    if rows < 7
        || cols < 2
        || input.len() > 12_000_000
        || coefficients.is_empty()
        || coefficients.len() > rows
        || coefficients.len().is_multiple_of(2)
        || baseline_n == 0
        || baseline_n > rows
        || baseline_n.is_multiple_of(2)
        || input.iter().any(|v| !v.is_finite() || *v < 0.0)
        || coefficients.iter().any(|v| !v.is_finite())
    {
        return Err(invalid("Invalid signal or filter windows"));
    }
    let mut corrected = vec![0.0; input.len()];
    let mut baseline_tic = vec![0.0; rows];
    let mut noise = vec![0.0; cols];
    for ion in 0..cols {
        let trace: Vec<f64> = input.column(ion).iter().copied().collect();
        let filtered = smooth(&trace, &coefficients);
        let baseline = extremum(
            &extremum(&filtered, baseline_n / 2, false),
            baseline_n / 2,
            true,
        );
        for scan in 0..rows {
            corrected[scan * cols + ion] = (filtered[scan] - baseline[scan]).max(0.0);
            baseline_tic[scan] += baseline[scan];
        }
        let mut differences: Vec<f64> = trace.windows(2).map(|w| w[1] - w[0]).collect();
        let center = median(&mut differences);
        for value in &mut differences {
            *value = (*value - center).abs();
        }
        noise[ion] = (median(&mut differences) / 0.9538725524).max(1.0);
    }
    Ok((
        matrix(py, rows, cols, corrected),
        baseline_tic.into_pyarray(py),
        noise.into_pyarray(py),
    ))
}

struct Event {
    scan: usize,
    ion: usize,
    height: f64,
    prominence: f64,
    left: f64,
    right: f64,
}

fn bounds(
    x: &[f64],
    peak: usize,
    left: usize,
    right: usize,
    prominence: f64,
    relative: f64,
) -> (f64, f64) {
    let height = x[peak] - prominence * relative;
    let mut l = peak;
    while l > left && x[l] > height {
        l -= 1;
    }
    let mut r = peak;
    while r < right && x[r] > height {
        r += 1;
    }
    let mut start = l as f64;
    let mut end = r as f64;
    if x[l] < height && x[l + 1] != x[l] {
        start += (height - x[l]) / (x[l + 1] - x[l]);
    }
    if x[r] < height && x[r - 1] != x[r] {
        end -= (height - x[r]) / (x[r - 1] - x[r]);
    }
    (start, end)
}

fn ion_events(
    x: &[f64],
    ion: usize,
    threshold: f64,
    min_width: f64,
    max_width: f64,
    events: &mut Vec<Event>,
) {
    // ponytail: prominence searches can be quadratic; index higher peaks if long traces dominate.
    let mut i = 1;
    while i + 1 < x.len() {
        if x[i - 1] >= x[i] {
            i += 1;
            continue;
        }
        let start = i;
        while i + 1 < x.len() && x[i + 1] == x[start] {
            i += 1;
        }
        let last = i;
        i += 1;
        if i == x.len() || x[i] >= x[start] {
            continue;
        }
        let peak = (start + last) / 2;
        // Corrected intensities are nonnegative, so prominence cannot exceed height.
        if x[peak] < threshold {
            continue;
        }
        let mut left = peak;
        let mut right = peak;
        for j in (0..peak).rev() {
            if x[j] > x[peak] {
                break;
            }
            if x[j] < x[left] {
                left = j;
            }
        }
        for j in peak + 1..x.len() {
            if x[j] > x[peak] {
                break;
            }
            if x[j] < x[right] {
                right = j;
            }
        }
        let prominence = x[peak] - x[left].max(x[right]);
        if prominence < threshold {
            continue;
        }
        let (l, r) = bounds(x, peak, left, right, prominence, 0.5);
        if r - l < min_width || r - l > max_width {
            continue;
        }
        let (l, r) = bounds(x, peak, left, right, prominence, 0.95);
        events.push(Event {
            scan: peak,
            ion,
            height: x[peak],
            prominence,
            left: l,
            right: r,
        });
    }
}

type Feature = (usize, usize, usize, Vec<usize>, f64, f64);
type Detected<'py> = (Vec<Feature>, Bound<'py, PyArray2<f64>>);

#[pyfunction]
fn detect<'py>(
    py: Python<'py>,
    data: PyReadonlyArray2<'py, f64>,
    time: PyReadonlyArray1<'py, f64>,
    noise: PyReadonlyArray1<'py, f64>,
    settings: Vec<f64>,
) -> PyResult<Detected<'py>> {
    let y = data.as_array();
    let t = time.as_slice()?;
    let noise = noise.as_slice()?;
    let (rows, cols) = y.dim();
    if rows < 7
        || cols < 2
        || y.len() > 12_000_000
        || t.len() != rows
        || noise.len() != cols
        || settings.len() != 7
        || settings.iter().any(|v| !v.is_finite() || *v < 0.0)
        || t.iter().any(|v| !v.is_finite())
        || t.windows(2).any(|w| w[1] <= w[0])
        || noise.iter().any(|v| !v.is_finite() || *v <= 0.0)
        || y.iter().any(|v| !v.is_finite() || *v < 0.0)
    {
        return Err(invalid("Invalid detection inputs"));
    }
    let dt = median(&mut t.windows(2).map(|w| w[1] - w[0]).collect::<Vec<_>>());
    let (min_width, max_width, radius, multiplier, min_ions, relative, fraction) = (
        settings[0] / dt,
        settings[1] / dt,
        settings[2] / dt,
        settings[3],
        settings[4] as usize,
        settings[5],
        settings[6],
    );
    if min_width <= 0.0
        || max_width <= min_width
        || min_ions < 2
        || relative > 1.0
        || multiplier == 0.0
    {
        return Err(invalid("Invalid detection settings"));
    }
    let mut events = Vec::new();
    for (ion, &level) in noise.iter().enumerate() {
        let trace: Vec<f64> = y.column(ion).iter().copied().collect();
        ion_events(
            &trace,
            ion,
            multiplier * level,
            min_width,
            max_width,
            &mut events,
        );
        if events.len() > 100_000 {
            return Err(invalid(
                "More than 100,000 ion peaks; increase noise_multiplier.",
            ));
        }
    }
    events.sort_by_key(|e| (e.scan, e.ion));
    let mut order: Vec<usize> = (0..events.len()).collect();
    order.sort_by(|&a, &b| events[b].prominence.total_cmp(&events[a].prominence));
    let mut used = vec![false; events.len()];
    let minimum_height = fraction * y.rows().into_iter().map(|r| r.sum()).fold(0.0, f64::max);
    let mut found: Vec<(Feature, Vec<f64>)> = Vec::new();
    for seed in order {
        if used[seed] {
            continue;
        }
        let apex = events[seed].scan;
        let lo = events.partition_point(|e| (e.scan as f64) < apex as f64 - radius);
        let hi = events.partition_point(|e| (e.scan as f64) <= apex as f64 + radius);
        let all: Vec<usize> = (lo..hi).filter(|&j| !used[j]).collect();
        let height = all.iter().map(|&j| events[j].height).fold(0.0, f64::max);
        let mut members: Vec<usize> = all
            .iter()
            .copied()
            .filter(|&j| events[j].height >= height * relative)
            .collect();
        members.sort_by(|&a, &b| events[b].prominence.total_cmp(&events[a].prominence));
        let mut seen = vec![false; cols];
        members.retain(|&j| {
            let ion = events[j].ion;
            let fresh = !seen[ion];
            seen[ion] = true;
            fresh
        });
        members.sort_by_key(|&j| events[j].ion);
        if members.len() < min_ions {
            used[seed] = true;
            continue;
        }
        for j in all {
            used[j] = true;
        }
        let ions: Vec<usize> = members.iter().map(|&j| events[j].ion).collect();
        let mut left: Vec<f64> = members.iter().map(|&j| events[j].left).collect();
        let mut right: Vec<f64> = members.iter().map(|&j| events[j].right).collect();
        let start = (median(&mut left).floor() as usize).min(apex - 1);
        let end = (median(&mut right).ceil() as usize)
            .max(apex + 1)
            .min(rows - 1);
        let mut spectrum = vec![0.0; cols];
        for &ion in &ions {
            spectrum[ion] = (y[[apex - 1, ion]] + y[[apex, ion]] + y[[apex + 1, ion]]) / 3.0;
        }
        if spectrum.iter().sum::<f64>() < minimum_height {
            continue;
        }
        let trace: Vec<f64> = (start..=end)
            .map(|i| ions.iter().map(|&j| y[[i, j]]).sum())
            .collect();
        let area = trace
            .windows(2)
            .enumerate()
            .map(|(i, w)| (t[start + i + 1] - t[start + i]) * (w[0] + w[1]) / 2.0)
            .sum();
        let l = (start + apex) / 2;
        let r = (apex + end).div_ceil(2);
        let (mut dot, mut aa, mut bb) = (0.0, 0.0, 0.0);
        for j in 0..cols {
            let a = y[[l, j]].sqrt();
            let b = y[[r, j]].sqrt();
            dot += a * b;
            aa += a * a;
            bb += b * b;
        }
        let denominator = aa.sqrt() * bb.sqrt();
        let change = if denominator > 0.0 {
            1.0 - (dot / denominator).clamp(0.0, 1.0)
        } else {
            1.0
        };
        found.push(((apex, start, end, ions, area, change), spectrum));
        if found.len() > 1000 {
            return Err(invalid(
                "More than 1,000 components; increase noise_multiplier.",
            ));
        }
    }
    found.sort_by(|a, b| a.0.0.cmp(&b.0.0).then_with(|| a.0.3.cmp(&b.0.3)));
    let count = found.len();
    let mut spectra = Vec::with_capacity(count * cols);
    let mut features = Vec::with_capacity(count);
    for (feature, spectrum) in found {
        features.push(feature);
        spectra.extend(spectrum);
    }
    Ok((features, matrix(py, count, cols, spectra)))
}

type Matched<'py> = (
    Bound<'py, PyArray2<f64>>,
    Bound<'py, PyArray1<f64>>,
    Bound<'py, PyArray2<f64>>,
);

#[pyfunction]
fn project_match<'py>(
    py: Python<'py>,
    mz: PyReadonlyArray1<'py, f64>,
    spectra: PyReadonlyArray2<'py, f64>,
    library: Vec<PyReadonlyArray2<'py, f64>>,
) -> PyResult<Matched<'py>> {
    let mz = mz.as_slice()?;
    let query = spectra.as_array();
    let (count, cols) = query.dim();
    if cols < 2
        || cols != mz.len()
        || count > 1000
        || library.is_empty()
        || library.len() > 100_000
        || mz
            .iter()
            .any(|v| !v.is_finite() || *v != v.round_ties_even())
        || mz.windows(2).any(|w| w[1] - w[0] != 1.0)
        || query.iter().any(|v| !v.is_finite() || *v < 0.0)
    {
        return Err(invalid("Invalid matching inputs"));
    }
    let groups = library.len();
    if groups.checked_mul(cols).is_none_or(|n| n > 12_000_000) {
        return Err(invalid("Reference matrix too large"));
    }
    let mut reference = vec![0.0; groups * cols];
    let mut fractions = vec![0.0; groups];
    for (i, peaks) in library.iter().enumerate() {
        let peaks = peaks.as_array();
        if peaks.ncols() != 2 || peaks.iter().any(|v| !v.is_finite() || *v < 0.0) {
            return Err(invalid("Invalid reference peaks"));
        }
        let mut total = 0.0;
        for peak in peaks.rows() {
            total += peak[1];
            let bin = peak[0].round_ties_even() - mz[0];
            if bin >= 0.0 && bin < (cols as f64) {
                reference[i * cols + bin as usize] += peak[1];
            }
        }
        if total <= 0.0 || !total.is_finite() {
            return Err(invalid("Empty reference spectrum"));
        }
        fractions[i] = reference[i * cols..(i + 1) * cols].iter().sum::<f64>() / total;
    }
    let refs: Vec<Vec<f64>> = reference
        .chunks(cols)
        .map(|r| normalized(r.iter().copied()))
        .collect();
    let mut scores = Vec::with_capacity(count * groups);
    for row in query.rows() {
        let q = normalized(row.iter().copied());
        for r in &refs {
            scores.push(
                q.iter()
                    .zip(r)
                    .map(|(a, b)| a * b)
                    .sum::<f64>()
                    .clamp(0.0, 1.0),
            );
        }
    }
    Ok((
        matrix(py, groups, cols, reference),
        fractions.into_pyarray(py),
        matrix(py, count, groups, scores),
    ))
}

fn normalized(values: impl Iterator<Item = f64>) -> Vec<f64> {
    let mut row: Vec<f64> = values.map(f64::sqrt).collect();
    let norm = row.iter().map(|v| v * v).sum::<f64>().sqrt();
    if norm > 0.0 {
        for v in &mut row {
            *v /= norm;
        }
    }
    row
}

#[pyfunction]
fn correspondences(
    base_time: PyReadonlyArray1<'_, f64>,
    base_spectra: PyReadonlyArray2<'_, f64>,
    other_time: PyReadonlyArray1<'_, f64>,
    other_spectra: PyReadonlyArray2<'_, f64>,
    tolerance: f64,
    minimum_similarity: f64,
) -> PyResult<Vec<Vec<(usize, f64)>>> {
    let a = base_spectra.as_array();
    let b = other_spectra.as_array();
    let at = base_time.as_slice()?;
    let bt = other_time.as_slice()?;
    if a.nrows() != at.len()
        || b.nrows() != bt.len()
        || a.ncols() != b.ncols()
        || a.ncols() < 2
        || a.nrows() > 1000
        || b.nrows() > 1000
        || a.len() > 12_000_000
        || b.len() > 12_000_000
        || !tolerance.is_finite()
        || tolerance < 0.0
        || !(0.0..=1.0).contains(&minimum_similarity)
        || at.iter().chain(bt).any(|v| !v.is_finite())
        || a.iter().chain(b.iter()).any(|v| !v.is_finite() || *v < 0.0)
    {
        return Err(invalid("Invalid cross-profile correspondence inputs"));
    }
    let refs: Vec<Vec<f64>> = b
        .rows()
        .into_iter()
        .map(|r| normalized(r.iter().copied()))
        .collect();
    let mut result = Vec::with_capacity(at.len());
    for (i, row) in a.rows().into_iter().enumerate() {
        let q = normalized(row.iter().copied());
        let mut eligible = Vec::new();
        for (j, r) in refs.iter().enumerate() {
            if (at[i] - bt[j]).abs() <= tolerance {
                let score = q
                    .iter()
                    .zip(r)
                    .map(|(x, y)| x * y)
                    .sum::<f64>()
                    .clamp(0.0, 1.0);
                if score >= minimum_similarity {
                    eligible.push((j, score));
                }
            }
        }
        result.push(eligible);
    }
    Ok(result)
}

#[pymodule]
fn _gcms_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(preprocess, m)?)?;
    m.add_function(wrap_pyfunction!(detect, m)?)?;
    m.add_function(wrap_pyfunction!(project_match, m)?)?;
    m.add_function(wrap_pyfunction!(correspondences, m)?)?;
    Ok(())
}
