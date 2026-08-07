"""Scan orchestration: parse -> evaluate the YAML rule pack -> persist."""
from __future__ import annotations

import time
from typing import Iterable

from sqlalchemy.orm import Session

from ..models import Finding, Scan, ScanFile
from .parser import ParsedProject, TFResource, parse_files
from .yaml_engine import SEVERITY_RANK, SEVERITY_WEIGHT, evaluate_clause, load_rules


def _evidence(project: ParsedProject, res: TFResource, hint: str) -> tuple:
    """Bounded scan of the resource's block span for the matching token.

    Returns (line, snippet): the first line inside the span containing the
    hint, else the block header line. Never reads outside the span (SPEC.md).
    """
    text = project.sources.get(res.file)
    if not text or not res.start_line:
        return res.start_line, ""
    lines = text.split("\n")
    end = min(res.end_line or res.start_line, len(lines))
    if hint:
        for i in range(res.start_line - 1, end):
            if hint in lines[i]:
                return i + 1, lines[i].strip()[:200]
        norm_hint = " ".join(hint.split())
        for i in range(res.start_line - 1, end):
            if norm_hint in " ".join(lines[i].split()):
                return i + 1, lines[i].strip()[:200]
    return res.start_line, lines[res.start_line - 1].strip()[:200]


def _score(weight_total: int, weight_failed: int) -> float:
    """SPEC.md formula: 100 x (1 - failed/evaluated weight), 1 decimal;
    zero evaluated checks -> 100."""
    if weight_total == 0:
        return 100.0
    return round(100.0 * (1 - weight_failed / weight_total), 1)


def evaluate(project: ParsedProject, rules: list) -> tuple:
    """One evaluated check = one (rule, resource) pair whose resource type
    matches the rule's resource_type list (SPEC.md). Clauses are any-of; a
    failed pair produces one finding and counts its severity weight once.
    The per-file score applies the same formula to each file's resources.
    """
    findings: list[dict] = []
    checks_total = checks_failed = 0
    weight_total = weight_failed = 0
    per_file: dict = {}   # file -> [weight_total, weight_failed]

    for rule in rules:
        for res in project.managed(*rule.resource_type):
            checks_total += 1
            w = SEVERITY_WEIGHT[rule.severity]
            weight_total += w
            bucket = per_file.setdefault(res.file, [0, 0])
            bucket[0] += w
            hint = None
            matched = False
            for clause in rule.check:
                ok, h = evaluate_clause(clause, res, project)
                if ok:
                    matched, hint = True, (h or clause.attr or "")
                    break
            if not matched:
                continue
            checks_failed += 1
            weight_failed += w
            bucket[1] += w
            line, snippet = _evidence(project, res, hint)
            findings.append({
                "rule_id": rule.id,
                "severity": rule.severity,
                "severity_rank": SEVERITY_RANK[rule.severity],
                "resource_type": res.type,
                "resource_address": res.address,
                "file": res.file,
                "line": line,
                "evidence": snippet,
                "message": rule.message,
                "remediation": rule.remediation,
            })

    file_scores = {f: _score(wt, wf) for f, (wt, wf) in per_file.items()}
    for f in project.files:
        file_scores.setdefault(f, 100.0)   # parsed file, no evaluated checks
    stats = {
        "resources_scanned": len(project.managed()),
        "checks_total": checks_total,
        "checks_failed": checks_failed,
        "score": _score(weight_total, weight_failed),
        "file_scores": file_scores,
    }
    return findings, stats


def run_scan(
    db: Session,
    *,
    files: Iterable[tuple],
    label: str = "",
) -> Scan:
    started = time.perf_counter()
    rules = load_rules()
    named = list(files)
    project = parse_files(named)
    source = ", ".join(project.files)[:490] or "upload"

    findings, stats = evaluate(project, rules)
    scan = Scan(
        label=label or "",
        source=source,
        duration_ms=int((time.perf_counter() - started) * 1000),
        files_scanned=len(project.files),
        parse_errors=project.errors,
        **stats,
    )
    scan.findings = [Finding(**f) for f in findings]
    # SPEC.md Turn-14 amendment: persist the uploaded text (already size-capped
    # by the shared upload limits) for the dashboard's annotated source view.
    scan.source_files = [ScanFile(path=p, content=t) for p, t in named]
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan
