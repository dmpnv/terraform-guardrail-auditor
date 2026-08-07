from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..engine.rules import all_rules
from ..engine.scanner import run_scan
from ..models import Finding, Scan
from ..schemas import (FindingOut, RuleOut, ScanCreate, ScanOut,
                       ScanSummaryOut, SummaryOut, TopRule, TrendPoint)

router = APIRouter()


@router.get("/health", tags=["system"])
def health():
    return {
        "status": "ok",
        "service": config.API_TITLE,
        "version": config.API_VERSION,
        "rules_loaded": len(all_rules()),
    }


@router.get("/rules", response_model=list[RuleOut], tags=["rules"])
def list_rules():
    """The guardrail pack this auditor enforces."""
    return [RuleOut.model_validate(r) for r in all_rules()]


def _resolve_scan_dir(raw: str) -> Path:
    candidates = [Path(raw)]
    if not Path(raw).is_absolute():
        candidates.append(config.BASE_DIR / raw)
    for c in candidates:
        if c.is_dir():
            return c
    raise HTTPException(status_code=400, detail=f"Directory not found on server: {raw}")


@router.post("/scans", response_model=ScanOut, status_code=201, tags=["scans"])
def create_scan(body: ScanCreate, db: Session = Depends(get_db)):
    """Audit Terraform from a server-local directory or inline file contents."""
    if body.path:
        return run_scan(db, path=_resolve_scan_dir(body.path), label=body.label)
    return run_scan(db, files=[(f.path, f.content) for f in body.files], label=body.label)


@router.get("/scans", response_model=list[ScanSummaryOut], tags=["scans"])
def list_scans(
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = (select(Scan)
            .order_by(Scan.created_at.desc(), Scan.id.desc())
            .limit(limit).offset(offset))
    return db.scalars(stmt).all()


@router.get("/scans/{scan_id}", response_model=ScanOut, tags=["scans"])
def get_scan(scan_id: int, db: Session = Depends(get_db)):
    scan = db.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


@router.get("/scans/{scan_id}/findings", response_model=list[FindingOut], tags=["scans"])
def scan_findings(
    scan_id: int,
    severity: Optional[str] = Query(None, description="CRITICAL | HIGH | MEDIUM | LOW"),
    rule_id: Optional[str] = Query(None, examples=["GR-NET-001"]),
    db: Session = Depends(get_db),
):
    if not db.get(Scan, scan_id):
        raise HTTPException(status_code=404, detail="Scan not found")
    stmt = select(Finding).where(Finding.scan_id == scan_id)
    if severity:
        stmt = stmt.where(Finding.severity == severity.upper())
    if rule_id:
        stmt = stmt.where(Finding.rule_id == rule_id)
    return db.scalars(stmt.order_by(Finding.severity_rank, Finding.id)).all()


@router.delete("/scans/{scan_id}", status_code=204, tags=["scans"])
def delete_scan(scan_id: int, db: Session = Depends(get_db)):
    scan = db.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    db.delete(scan)
    db.commit()
    return Response(status_code=204)


@router.get("/summary", response_model=SummaryOut, tags=["dashboard"])
def summary(db: Session = Depends(get_db)):
    """Aggregated posture for the dashboard: latest scan + score trend."""
    total_scans = db.scalar(select(func.count(Scan.id))) or 0
    total_findings = db.scalar(select(func.count(Finding.id))) or 0
    latest = db.scalars(
        select(Scan).order_by(Scan.created_at.desc(), Scan.id.desc()).limit(1)
    ).first()

    top_rules: list[TopRule] = []
    if latest:
        rows = db.execute(
            select(Finding.rule_id, Finding.rule_title, Finding.severity,
                   func.count(Finding.id))
            .where(Finding.scan_id == latest.id)
            .group_by(Finding.rule_id, Finding.rule_title, Finding.severity)
            .order_by(func.count(Finding.id).desc(), Finding.rule_id)
            .limit(8)
        ).all()
        top_rules = [TopRule(rule_id=r[0], rule_title=r[1], severity=r[2], count=r[3])
                     for r in rows]

    recent = db.scalars(
        select(Scan).order_by(Scan.created_at.desc(), Scan.id.desc()).limit(50)
    ).all()
    trend = [TrendPoint(id=s.id, label=s.label or f"scan #{s.id}",
                        created_at=s.created_at, score=s.score)
             for s in reversed(recent)]

    return SummaryOut(
        total_scans=total_scans,
        total_findings=total_findings,
        latest=ScanSummaryOut.model_validate(latest) if latest else None,
        top_rules=top_rules,
        trend=trend,
    )
