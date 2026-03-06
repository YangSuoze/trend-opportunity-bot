from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class Signal(BaseModel):
    source: str
    title: str
    url: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float | str | None] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    fingerprint: str

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            cleaned = " ".join(tag.strip().split()).lower()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                normalized.append(cleaned)
        return normalized


class OpportunityScoring(BaseModel):
    demand: int = 0
    urgency: int = 0
    distribution: int = 0
    feasibility: int = 0
    monetization: int = 0
    defensibility: int = 0
    total: int | None = None

    @field_validator(
        "demand",
        "urgency",
        "distribution",
        "feasibility",
        "monetization",
        "defensibility",
    )
    @classmethod
    def validate_score_range(cls, value: int) -> int:
        if value < 0 or value > 5:
            raise ValueError("scores must be in range 0-5")
        return value

    @model_validator(mode="after")
    def compute_total(self) -> OpportunityScoring:
        calculated = (
            self.demand
            + self.urgency
            + self.distribution
            + self.feasibility
            + self.monetization
            + self.defensibility
        )
        self.total = calculated
        return self


class OpportunityCard(BaseModel):
    source: str
    source_title: str
    source_url: str
    source_fingerprint: str
    target_user: str
    trigger: str
    pain: str
    existing_alternatives: str
    solution: str
    pricing_reason: str
    validation_7d: str
    success_signal: str
    zh_summary: str = ""
    zh_analysis: str = ""
    scoring: OpportunityScoring
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
