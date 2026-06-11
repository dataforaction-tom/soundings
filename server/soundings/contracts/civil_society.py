"""CivilSocietyProfile — response shape for `get_civil_society_profile`.

Aggregate view of registered charities operating in a place: total,
income distribution, median/mean size, and a registration-cohort
trend. Inputs come from `data.organisation` (CC bulk register) joined
to `data.organisation_operates_in`.
"""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from soundings.contracts.source_ref import SourceRef


class IncomeBucket(BaseModel):
    label: str = Field(description="Human-readable bucket label, e.g. '<10k', '10k-100k'.")
    lower: float = Field(ge=0, description="Inclusive lower bound, GBP.")
    upper: float | None = Field(
        default=None,
        description="Exclusive upper bound, GBP. None for the open-ended top bucket.",
    )
    count: int = Field(ge=0)


class RegistrationCohort(BaseModel):
    year: int
    registered: int = Field(ge=0, description="Charities first registered in this year.")
    removed: int = Field(ge=0, description="Charities removed in this year.")
    net: int = Field(description="`registered` - `removed`.")

    @model_validator(mode="after")
    def _check_net(self) -> Self:
        if self.net != self.registered - self.removed:
            raise ValueError("net must equal registered - removed")
        return self


class CivilSocietyProfile(BaseModel):
    place_id: str
    total_organisations: int = Field(ge=0)
    with_reported_income: int = Field(
        ge=0,
        description=(
            "Subset of total_organisations that have a non-null `latest_income` on"
            " their CC return. Median/mean are computed over this subset."
        ),
    )
    median_income: float | None = Field(
        default=None, description="Median GBP of `latest_income` over reporting charities."
    )
    mean_income: float | None = Field(
        default=None, description="Mean GBP of `latest_income` over reporting charities."
    )
    income_buckets: list[IncomeBucket] = Field(default_factory=list)
    registration_cohort: list[RegistrationCohort] = Field(
        default_factory=list,
        description="One row per year, oldest first; window controlled by the orchestrator.",
    )
    sources: list[SourceRef] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    partial: bool = Field(default=False)
