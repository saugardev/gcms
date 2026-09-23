export type Range = [number, number];

export function nearestIndex(values: number[], value: number) {
  if (!values.length) return -1;
  let lo = 0,
    hi = values.length - 1;
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (values[mid] < value) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 &&
    Math.abs(values[lo - 1] - value) <= Math.abs(values[lo] - value)
    ? lo - 1
    : lo;
}

export function constrainRange(range: Range, full: Range): Range {
  const width = Math.min(range[1] - range[0], full[1] - full[0]);
  if (!(width > 0)) return full;
  const start = Math.max(full[0], Math.min(range[0], full[1] - width));
  return [start, start + width];
}

export function ticks(range: Range, count = 4) {
  return Array.from(
    { length: count + 1 },
    (_, i) => range[0] + ((range[1] - range[0]) * i) / count,
  );
}

export function linePath(
  times: number[],
  values: number[],
  range: Range,
  width: number,
  height: number,
  max: number,
) {
  let result = "";
  // ponytail: raw imports are capped at 50,000 scans; decimate per pixel if larger acquisitions are supported.
  for (
    let i = Math.max(0, nearestIndex(times, range[0]) - 1);
    i < times.length;
    i++
  ) {
    const x = ((times[i] - range[0]) / (range[1] - range[0])) * width;
    const y = height - (values[i] / Math.max(1, max)) * height;
    result += `${result ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`;
    if (times[i] >= range[1]) break;
  }
  return result;
}
