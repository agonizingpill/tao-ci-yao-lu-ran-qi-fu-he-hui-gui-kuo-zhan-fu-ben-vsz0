from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=400)]


class Phase(StrEnum):
    ramp = 'ramp'
    soak = 'soak'
    cool = 'cool'


class BatchStatus(StrEnum):
    scheduled = 'scheduled'
    recording = 'recording'
    analyzed = 'analyzed'
    confirmed = 'confirmed'


class Credentials(BaseModel):
    username: Label
    password: Annotated[str, Field(min_length=1, max_length=128)]


class Batch(BaseModel):
    code: Annotated[str, Field(pattern=r'^[A-Z0-9][A-Z0-9-]{1,30}$')]
    kiln: Label
    recipe: Label
    baseline_version: int = Field(ge=1, le=10000)
    batch_kg: Decimal = Field(gt=0, le=100000, max_digits=10, decimal_places=2)
    opened_at: AwareDatetime
    closed_at: AwareDatetime
    planned_minutes: int = Field(ge=30, le=1440)

    @model_validator(mode='after')
    def valid_cycle(self):
        duration = (self.closed_at - self.opened_at).total_seconds() / 60
        if not 30 <= duration <= 1440:
            raise ValueError('烧成周期须介于 30 分钟和 24 小时')
        return self


class CurveSegment(BaseModel):
    phase: Phase
    started_at: AwareDatetime
    ended_at: AwareDatetime
    peak_c: Decimal = Field(ge=20, le=1500, max_digits=7, decimal_places=2)
    source_file: Label


class MeterSample(BaseModel):
    sampled_at: AwareDatetime
    meter_serial: Label
    reading_m3: Decimal = Field(ge=0, max_digits=13, decimal_places=3)
    source_file: Label


class RecipeProposal(BaseModel):
    description: Reason


class RecipeDecision(BaseModel):
    decision: Literal['approved', 'rejected']
    note: Reason


class ReviewPlan(BaseModel):
    run_id: int = Field(gt=0)
    next_minutes: int = Field(ge=30, le=1440)
    attribution: Literal['observed', 'recipe']
    rationale: Reason
