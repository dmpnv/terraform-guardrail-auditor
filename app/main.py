from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .api.routes import router
from .db import get_db, init_db
from .engine.yaml_engine import load_rules
from .models import Finding, Scan

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
# Status colors validated against the dark surface (#121e31): contrast >= 3:1.
# Hue never carries meaning alone: every use pairs a glyph + text label.
SEV_META = {
    "CRITICAL": {"glyph": "▲", "color": "#d03b3b", "label": "Critical"},
    "HIGH":     {"glyph": "◆", "color": "#ec835a", "label": "High"},
    "MEDIUM":   {"glyph": "●", "color": "#fab219", "label": "Medium"},
    "LOW":      {"glyph": "─", "color": "#8a97ab", "label": "Low"},
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION,
    description=(
        "API-first enterprise security guardrail auditor for Terraform. "
        "Scans uploaded HCL against the YAML guardrail pack, persists results, "
        "and tracks security posture over time. The dashboard at `/` is a "
        "server-rendered view of the same data."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


def _trend_geometry(scans: list) -> Optional[dict]:
    """Inline-SVG polyline geometry for the score trend (no JS, no libs)."""
    if not scans:
        return None
    w, h, pad = 640, 150, 14
    points = []
    n = len(scans)
    for i, s in enumerate(scans):
        x = w / 2 if n == 1 else pad + i * (w - 2 * pad) / (n - 1)
        y = pad + (100 - s.score) * (h - 2 * pad) / 100
        points.append({"x": round(x, 1), "y": round(y, 1), "scan": s})
    return {
        "w": w, "h": h,
        "polyline": " ".join(f"{p['x']},{p['y']}" for p in points),
        "points": points,
        "gridlines": [
            {"y": pad, "label": "100"},
            {"y": pad + (h - 2 * pad) / 2, "label": "50"},
            {"y": h - pad, "label": "0"},
        ],
    }


@app.get("/", include_in_schema=False)
def dashboard(
    request: Request,
    severity: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    sev = severity.upper() if severity else None
    if sev not in SEVERITIES:
        sev = None

    latest = db.scalars(
        select(Scan).order_by(Scan.created_at.desc(), Scan.id.desc()).limit(1)
    ).first()

    counts = {s: 0 for s in SEVERITIES}
    findings: list = []
    if latest:
        counts.update(latest.severity_counts)
        stmt = select(Finding).where(Finding.scan_id == latest.id)
        if sev:
            stmt = stmt.where(Finding.severity == sev)
        findings = db.scalars(stmt.order_by(Finding.severity_rank, Finding.id)).all()

    recent = db.scalars(
        select(Scan).order_by(Scan.created_at.desc(), Scan.id.desc()).limit(30)
    ).all()
    trend = _trend_geometry(list(reversed(recent)))
    total_scans = db.scalar(select(func.count(Scan.id))) or 0

    return TEMPLATES.TemplateResponse(request, "dashboard.html", {
        "latest": latest,
        "counts": counts,
        "findings": findings,
        "active_severity": sev,
        "trend": trend,
        "total_scans": total_scans,
        "severities": SEVERITIES,
        "sev_meta": SEV_META,
        "rules_loaded": len(load_rules()),
        "version": config.API_VERSION,
    })
