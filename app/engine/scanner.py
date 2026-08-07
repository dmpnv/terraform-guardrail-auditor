"""Scan orchestration: parse -> evaluate rules -> persist scan + findings."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from ..models import Finding, Scan
from .parser import ParsedProject, parse_files, parse_path
from .rules import SEVERITY_RANK, SEVERITY_WEIGHT, all_rules


def evaluate(project: ParsedProject) -> tuple[list, dict]:
    """Run every rule against every applicable resource.

    Returns (finding_dicts, stats). The score is severity-weighted:
    failing a CRITICAL check costs 10x a LOW check.
    """
    findings: list[dict] = []
    checks_total = checks_failed = 0
    weight_total = weight_failed = 0

    for r in all_rules():
        if "*" in r.resource_types:
            targets = project.managed()
        else:
            targets = project.managed(*r.resource_types)
        for res in targets:
            checks_total += 1
            weight_total += SEVERITY_WEIGHT[r.severity]
            messages = r.check(res, project) or []
            if not messages:
                continue
            checks_failed += 1
            weight_failed += SEVERITY_WEIGHT[r.severity]
            for msg in messages:
                findings.append({
                    "rule_id": r.id,
                    "rule_title": r.title,
                    "severity": r.severity.value,
                    "severity_rank": SEVERITY_RANK[r.severity],
                    "resource_type": res.type,
                    "resource_address": res.address,
                    "file": res.file,
                    "line": res.start_line,
                    "message": msg,
                    "remediation": r.remediation,
                })

    score = 100.0 if weight_total == 0 else round(100.0 * (1 - weight_failed / weight_total), 1)
    stats = {
        "resources_scanned": len(project.managed()),
        "checks_total": checks_total,
        "checks_failed": checks_failed,
        "score": score,
    }
    return findings, stats


def run_scan(
    db: Session,
    *,
    path: Optional[Path] = None,
    files: Optional[Iterable[tuple]] = None,
    label: str = "",
) -> Scan:
    started = time.perf_counter()
    if path is not None:
        project = parse_path(path)
        source = str(path)
    else:
        project = parse_files(files or [])
        source = "inline-upload"

    findings, stats = evaluate(project)
    scan = Scan(
        label=label or "",
        source=source,
        duration_ms=int((time.perf_counter() - started) * 1000),
        files_scanned=len(project.files),
        parse_errors=project.errors,
        **stats,
    )
    scan.findings = [Finding(**f) for f in findings]
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan
