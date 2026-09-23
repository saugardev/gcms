export type Spectrum = { mz: number[]; intensity: number[] };
export type IonTrace = { mz: number; tolerance: number; intensity: number[] };
export type ComponentSpectrum = {
  component_id: string;
  apex_seconds: number;
  spectrum: Spectrum;
};
export type RawScan = {
  scan_index: number;
  time_seconds: number;
  spectrum: Spectrum;
};
export type Candidate = {
  group_id: string;
  score: number;
  identities: { name: string; cas: string | null; source: string | null }[];
  reference_spectrum: Spectrum;
};
export type Peak = {
  component_id: string;
  apex_seconds: number;
  start_seconds: number;
  end_seconds: number;
  area_percent: number;
  status: string;
  name: string;
  score: number | null;
  stability: string | null;
  search_text: string;
};
export type AnalysisSummary = {
  id: string;
  sample_name: string;
  imported_at: string;
  component_count: number;
};
export type Analysis = {
  id: string;
  imported_at: string;
  metadata: {
    sample_name: string;
    warnings: string[];
    algorithm_version: string;
    acquisition: {
      scan_count: number;
      start_seconds: number;
      end_seconds: number;
      mz_min: number;
      mz_max: number;
    };
    provenance: { input_data_ms_sha256: string; library_sha256: string };
  };
  chromatogram: {
    time_seconds: number[];
    raw_tic: number[];
    corrected_tic: number[];
    preview: boolean;
  };
  raw_chromatogram: null | { time_seconds: number[]; raw_tic: number[] };
  peaks: Peak[];
};
export type ComponentDetail = {
  component: {
    component_id: string;
    apex_seconds: number;
    start_seconds: number;
    end_seconds: number;
    area: number;
    area_percent: number;
    status: string;
    warnings: string[];
    spectrum: Spectrum;
    candidates: Candidate[];
  };
  review: null | {
    label: string;
    matched_profiles: number;
    evaluated_profiles: number;
    trace: {
      time_seconds: number[];
      corrected_tic: number[];
      raw_tic: number[];
      component_ion_sum: number[];
      ions: { mz: number; intensity: number[] }[];
    };
  };
};

export async function fetchSaved<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api${path}`, { signal, cache: "no-store" });
  if (!response.ok)
    throw new Error(
      response.status === 404
        ? "This saved analysis is no longer available."
        : "Cannot reach the saved analyses. Please try again.",
    );
  return response.json();
}
