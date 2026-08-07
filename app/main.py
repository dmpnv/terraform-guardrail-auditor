import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import (Cookie, Depends, FastAPI, File, Form, HTTPException,
                     Query, Request, UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .api.routes import read_tf_uploads, router
from .db import get_db, init_db
from .engine.scanner import run_scan
from .engine.yaml_engine import load_rules
from .models import Finding, Scan, ScanFile

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
# Colors live in the template's CSS custom properties (Turn-19 theming
# amendment) — per-theme values, hue never alone: glyph + label everywhere.
SEV_META = {
    "CRITICAL": {"glyph": "▲", "label": "Critical"},
    "HIGH":     {"glyph": "◆", "label": "High"},
    "MEDIUM":   {"glyph": "●", "label": "Medium"},
    "LOW":      {"glyph": "─", "label": "Low"},
}

THEMES = ("dark", "light")

FORM_ERRORS = {
    "no_files": "Choose at least one .tf file to scan.",
    "limits": "Upload rejected: too many files or a file over the size limit.",
}


_ANCHOR_RE = re.compile(r"[^a-z0-9]+")


def anchor_base(path: str) -> str:
    """Sanitized fragment-anchor prefix for a source file, e.g.
    'main.tf' -> 'src-main-tf' (flagged line 23 -> #src-main-tf-L23)."""
    return "src-" + _ANCHOR_RE.sub("-", path.lower()).strip("-")


def _source_views(stored_files: list, findings: list, file_scores: dict) -> list:
    """Annotated source model for the template. Findings are the (already
    severity-filtered) rows for the displayed scan, so the filter chips apply
    to the source column too. Rendering stays escaped text — never raw HTML.
    """
    by_line: dict = {}
    for f in findings:
        if f.line:
            by_line.setdefault((f.file, f.line), []).append(f)

    views = []
    for sf in stored_files:
        lines = sf.content.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        rows = []
        for n, text in enumerate(lines, start=1):
            marks = by_line.get((sf.path, n), [])
            worst = min(marks, key=lambda m: m.severity_rank).severity if marks else None
            rows.append({"n": n, "text": text, "marks": marks, "worst": worst})
        score = (file_scores or {}).get(sf.path)
        views.append({
            "path": sf.path,
            "anchor": anchor_base(sf.path),
            "score": score,
            "band": score_band(score) if score is not None else None,
            "rows": rows,
        })
    return views


def score_band(score: float) -> dict:
    """Color grade for a 0-100 risk score (always shown with its text label).
    `cls` selects a CSS variable so both themes stay readable."""
    if score >= 90:
        return {"cls": "band-good", "label": "Healthy"}
    if score >= 70:
        return {"cls": "band-warn", "label": "Needs attention"}
    if score >= 50:
        return {"cls": "band-risk", "label": "At risk"}
    return {"cls": "band-crit", "label": "Critical"}


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
    """Inline-SVG geometry for the score trend (no JS, no libraries).

    Axis labels, per-point score labels (all points up to 12 scans, else
    first/last/min/max), and last-point emphasis are computed here so the
    template stays declarative.
    """
    if not scans:
        return None
    w, h = 640, 178
    pad_l, pad_r, pad_t, pad_b = 34, 18, 20, 26
    inner_w, inner_h = w - pad_l - pad_r, h - pad_t - pad_b
    n = len(scans)

    if n <= 12:
        labeled = set(range(n))
    else:
        scores = [s.score for s in scans]
        labeled = {0, n - 1, scores.index(min(scores)), scores.index(max(scores))}

    points = []
    for i, s in enumerate(scans):
        x = pad_l + inner_w / 2 if n == 1 else pad_l + i * inner_w / (n - 1)
        y = pad_t + (100 - s.score) * inner_h / 100
        points.append({
            "x": round(x, 1),
            "y": round(y, 1),
            "scan": s,
            "value": f"{s.score:g}",
            "labeled": i in labeled,
        })
    return {
        "w": w, "h": h,
        "polyline": " ".join(f"{p['x']}, {p['y']}" for p in points),
        "points": points,
        "last": points[-1],
        "gridlines": [
            {"y": round(pad_t, 1), "label": "100"},
            {"y": round(pad_t + inner_h / 2, 1), "label": "50"},
            {"y": round(pad_t + inner_h, 1), "label": "0"},
        ],
        "x_axis": {
            "y": h - 8,
            "first": {"x": points[0]["x"],
                      "text": points[0]["scan"].created_at.strftime("%b %d, %H:%M")},
            "last": {"x": points[-1]["x"],
                     "text": points[-1]["scan"].created_at.strftime("%b %d, %H:%M")},
        },
        "grid_x2": w - pad_r,
    }


@app.get("/theme/{choice}", include_in_schema=False)
def set_theme(choice: str):
    """Theme switcher (Turn-19 amendment): sets or clears the cookie and
    303-redirects back to the dashboard. 'system' clears the override."""
    resp = RedirectResponse("/", status_code=303)
    if choice in THEMES:
        resp.set_cookie("theme", choice, max_age=31536000,
                        httponly=True, samesite="lax", path="/")
    elif choice == "system":
        resp.delete_cookie("theme", path="/")
    return resp


@app.get("/", include_in_schema=False)
def dashboard(
    request: Request,
    severity: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    theme: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    sev = severity.upper() if severity else None
    if sev not in SEVERITIES:
        sev = None
    if theme not in THEMES:
        theme = None

    latest = db.scalars(
        select(Scan).order_by(Scan.created_at.desc(), Scan.id.desc()).limit(1)
    ).first()

    counts = {s: 0 for s in SEVERITIES}
    findings: list = []
    file_rows: list = []
    source_views: list = []
    has_sources = False
    band = None
    if latest:
        counts.update(latest.severity_counts)
        stmt = select(Finding).where(Finding.scan_id == latest.id)
        if sev:
            stmt = stmt.where(Finding.severity == sev)
        findings = db.scalars(stmt.order_by(Finding.severity_rank, Finding.id)).all()
        band = score_band(latest.score)
        file_rows = [
            {"file": f, "score": s, "band": score_band(s)}
            for f, s in sorted((latest.file_scores or {}).items())
        ]
        stored = db.scalars(
            select(ScanFile).where(ScanFile.scan_id == latest.id).order_by(ScanFile.id)
        ).all()
        has_sources = bool(stored)
        if has_sources:
            source_views = _source_views(stored, findings, latest.file_scores)

    recent = db.scalars(
        select(Scan).order_by(Scan.created_at.desc(), Scan.id.desc()).limit(30)
    ).all()
    trend = _trend_geometry(list(reversed(recent)))
    total_scans = db.scalar(select(func.count(Scan.id))) or 0

    return TEMPLATES.TemplateResponse(request, "dashboard.html", {
        "latest": latest,
        "band": band,
        "counts": counts,
        "findings": findings,
        "file_rows": file_rows,
        "active_severity": sev,
        "trend": trend,
        "total_scans": total_scans,
        "severities": SEVERITIES,
        "sev_meta": SEV_META,
        "rules_loaded": len(load_rules()),
        "version": config.API_VERSION,
        "error_message": FORM_ERRORS.get(error) if error else None,
        "source_views": source_views,
        "has_sources": has_sources,
        "anchor_for": anchor_base,
        "theme": theme,
    })


@app.post("/", include_in_schema=False)
async def dashboard_upload(
    files: list[UploadFile] = File(None),
    label: str = Form(""),
    db: Session = Depends(get_db),
):
    """Dashboard upload form (Post/Redirect/Get): reuses run_scan under the
    API's limits, then redirects so the user never lands on raw JSON."""
    files = [f for f in (files or []) if f.filename]
    if not files:
        return RedirectResponse("/?error=no_files", status_code=303)
    try:
        named = await read_tf_uploads(files)
    except HTTPException:
        return RedirectResponse("/?error=limits", status_code=303)
    run_scan(db, files=named, label=label[:200])
    return RedirectResponse("/", status_code=303)
