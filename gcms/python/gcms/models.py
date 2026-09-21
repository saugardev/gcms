"""Public API schema and the fixed, versioned processing parameters."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Parameters(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, frozen=True, validate_default=True
    )

    smoothing_seconds: float = Field(0.8, ge=0, le=5)
    baseline_seconds: float = Field(60, ge=10, le=300)
    min_width_seconds: float = Field(0.6, ge=0.1, le=10)
    max_width_seconds: float = Field(30, ge=1, le=120)
    coapex_seconds: float = Field(0.5, ge=0, le=2)
    noise_multiplier: float = Field(8, ge=3, le=50)
    min_ions: int = Field(3, ge=2, le=10)
    relative_ion_threshold: float = Field(0.01, ge=0, le=0.2)
    min_component_fraction: float = Field(0.001, ge=0, le=0.1)
    match_threshold: float = Field(0.75, ge=0, le=1)
    ambiguity_margin: float = Field(0.03, ge=0, le=0.2)
    top_k: int = Field(3, ge=1, le=10)

    @model_validator(mode="after")
    def ordered_windows(self):
        if not self.min_width_seconds < self.max_width_seconds < self.baseline_seconds:
            raise ValueError("Require min_width_seconds < max_width_seconds < baseline_seconds")
        return self


class Identity(BaseModel):
    entry_id: str
    name: str
    source: str | None = None
    cas: str | None = None
    formula: str | None = None
    molecular_weight: float | None = None
    reference_rt: float | None = None
    reference_ri: float | None = None


class Spectrum(BaseModel):
    mz: list[float]
    intensity: list[float]


class Candidate(BaseModel):
    group_id: str
    score: float
    identities: list[Identity]
    library_intensity_fraction_in_mass_range: float
    reference_spectrum: Spectrum


class Component(BaseModel):
    component_id: str
    apex_scan: int
    start_seconds: float
    apex_seconds: float
    end_seconds: float
    area: float
    area_percent: float
    apexing_ion_count: int
    spectrum: Spectrum
    status: Literal["tentative", "ambiguous", "unassigned"]
    score_margin: float | None
    close_candidate_groups: int
    spectral_change: float
    warnings: list[str]
    candidates: list[Candidate]


class AnalysisReport(BaseModel):
    schema_version: str = "1.0"
    algorithm_version: str = "coapex-1"
    sample_name: str
    provenance: dict
    acquisition: dict
    parameters: Parameters
    library: dict
    summary: dict
    warnings: list[str]
    chromatogram: dict
    components: list[Component]


class ReviewVariant(BaseModel):
    name: str
    parameters: dict
    state: Literal["completed", "skipped", "failed"]
    reason: str | None = None
    component_count: int | None = None
    statuses: dict[str, int] = Field(default_factory=dict)
    unmatched_variant_components: int | None = None


class ProfileObservation(BaseModel):
    profile: str
    outcome: Literal["matched", "not_matched", "ambiguous", "not_evaluated"]
    eligible_components: int = 0
    component_id: str | None = None
    apex_seconds: float | None = None
    spectral_similarity: float | None = None
    top_group_id: str | None = None
    top_names: list[str] = Field(default_factory=list)
    same_top_group: bool | None = None
    identification_status: str | None = None
    area: float | None = None


class IonTrace(BaseModel):
    mz: float
    intensity: list[float]


class PeakTrace(BaseModel):
    time_seconds: list[float]
    raw_tic: list[float]
    corrected_tic: list[float]
    component_ion_sum: list[float]
    ions: list[IonTrace]
    preview: bool
    full_window_scan_count: int


class ComponentReview(BaseModel):
    label: Literal["consistent", "sensitive", "inconclusive"]
    evaluated_profiles: int
    matched_profiles: int
    same_top_group_profiles: int
    match_fraction: float | None
    max_apex_shift_seconds: float | None
    min_area_ratio: float | None
    max_area_ratio: float | None
    observations: list[ProfileObservation]
    trace: PeakTrace
    selection_reasons: list[str] = Field(default_factory=list)


class ReviewReport(BaseModel):
    schema_version: str = "review-1.0"
    analysis: AnalysisReport
    method: dict
    variants: list[ReviewVariant]
    annotations: dict[str, ComponentReview]
    review_packet: list[str]
    summary: dict
    warnings: list[str]


class ProcessingError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)
