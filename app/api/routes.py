from __future__ import annotations

from typing import Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                     UploadFile)
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..engine.scanner import run_scan
from ..engine.yaml_engine import load_rules
from ..models import Finding, Scan
from ..schemas import FindingOut, RuleOut, ScanOut

router = APIRouter()


@router.get("/health", tags=["system"])
def health():
    return {
        "status": "ok",
        "service": config.API_TITLE,
        "version": config.API_VERSION,
        "rules_loaded": len(load_rules()),
    }


@router.get("/rules", response_model=list[RuleOut], tags=["rules"])
def list_rules():
    """The guardrail pack as loaded from rules.yaml (rules are data)."""
    return [RuleOut.model_validate(r) for r in load_rules()]


async def read_tf_uploads(files: list[UploadFile]) -> list[tuple]:
    """Validate and read multipart uploads — shared by the API and the
    dashboard form, so both enforce the same count/size limits."""
    if len(files) > config.MAX_FILES_PER_SCAN:
        raise HTTPException(status_code=400,
                            detail=f"Too many files (max {config.MAX_FILES_PER_SCAN}).")
    named: list[tuple] = []
    for f in files:
        raw = await f.read()
        if len(raw) > config.MAX_FILE_BYTES:
            raise HTTPException(status_code=400,
                                detail=f"{f.filename}: exceeds size limit "
                                       f"({config.MAX_FILE_BYTES} bytes).")
        named.append((f.filename or "upload.tf", raw.decode("utf-8", errors="replace")))
    return named


@router.post("/scans", response_model=ScanOut, status_code=201, tags=["scans"])
async def create_scan(
    files: list[UploadFile] = File(..., description="One or more .tf files"),
    label: str = Form("", max_length=200),
    db: Session = Depends(get_db),
):
    """Upload one or more Terraform files (multipart) and run a scan."""
    named = await read_tf_uploads(files)
    return run_scan(db, files=named, label=label)


@router.get("/scans/{scan_id}", response_model=ScanOut, tags=["scans"],
            responses={404: {"description": "Scan not found"}})
def get_scan(scan_id: int, db: Session = Depends(get_db)):
    scan = db.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


@router.get("/scans/{scan_id}/findings", response_model=list[FindingOut], tags=["scans"],
            responses={404: {"description": "Scan not found"}})
def scan_findings(
    scan_id: int,
    severity: Optional[str] = Query(None, description="CRITICAL | HIGH | MEDIUM | LOW"),
    rule_id: Optional[str] = Query(None, examples=["SSH-WORLD"]),
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
