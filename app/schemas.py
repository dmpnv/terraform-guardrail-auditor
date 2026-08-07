from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_serializer


def _iso_utc(v: datetime) -> str:
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.isoformat()


# ---------------------------------------------------------------------------
# responses (requests are multipart form uploads — no JSON request bodies)

class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: str
    severity: str
    resource_type: str
    resource_address: str
    file: str
    line: Optional[int]
    evidence: str
    message: str
    remediation: str


class ScanOut(BaseModel):
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
    file_scores: dict = {}
    findings_count: int
    severity_counts: dict
    parse_errors: list = []
    findings: list[FindingOut] = []

    @field_serializer("created_at")
    def _ser_created_at(self, v: datetime) -> str:
        return _iso_utc(v)


class RuleOut(BaseModel):
    """A rule as declared in rules.yaml (rules are data — SPEC.md)."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    severity: str
    resource_type: list
    message: str
    remediation: str
