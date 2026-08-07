from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import (BaseModel, ConfigDict, Field, computed_field,
                      field_serializer, model_validator)


def grade_for(score: float) -> str:
    for threshold, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= threshold:
            return letter
    return "F"


def _iso_utc(v: datetime) -> str:
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.isoformat()


# ---------------------------------------------------------------------------
# requests

class FileIn(BaseModel):
    path: str = Field(..., examples=["main.tf"], description="Display name of the file")
    content: str = Field(..., description="Raw Terraform (HCL) content")


class ScanCreate(BaseModel):
    label: str = Field("", max_length=200, examples=["payments-prod baseline"])
    path: Optional[str] = Field(
        None,
        description="Server-local directory containing .tf files",
        examples=["samples/insecure"],
    )
    files: Optional[list[FileIn]] = Field(
        None, description="Inline files (alternative to 'path')",
    )

    @model_validator(mode="after")
    def _exactly_one_source(self):
        if bool(self.path) == bool(self.files):
            raise ValueError("Provide exactly one of 'path' or 'files'.")
        return self


# ---------------------------------------------------------------------------
# responses

class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: str
    rule_title: str
    severity: str
    resource_type: str
    resource_address: str
    file: str
    line: Optional[int]
    message: str
    remediation: str


class ScanSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    source: str
    created_at: datetime
    duration_ms: int
    files_scanned: int
    resources_scanned: int
    checks_total: int
    checks_failed: int
    score: float
    findings_count: int
    severity_counts: dict
    parse_errors: list = []

    @computed_field
    @property
    def grade(self) -> str:
        return grade_for(self.score)

    @field_serializer("created_at")
    def _ser_created_at(self, v: datetime) -> str:
        return _iso_utc(v)


class ScanOut(ScanSummaryOut):
    findings: list[FindingOut] = []


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    severity: str
    resource_types: list
    remediation: str
    references: list


class TopRule(BaseModel):
    rule_id: str
    rule_title: str
    severity: str
    count: int


class TrendPoint(BaseModel):
    id: int
    label: str
    created_at: datetime
    score: float

    @field_serializer("created_at")
    def _ser_created_at(self, v: datetime) -> str:
        return _iso_utc(v)


class SummaryOut(BaseModel):
    total_scans: int
    total_findings: int
    latest: Optional[ScanSummaryOut]
    top_rules: list[TopRule]
    trend: list[TrendPoint]
