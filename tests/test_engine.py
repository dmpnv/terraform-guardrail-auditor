"""Parser tests: normalization, provenance spans, parse-error resilience.

Run against the golden fixtures (samples/ was deleted in slice 4 — fixtures
are the canonical corpus).
"""
from pathlib import Path

from app.engine.parser import parse_files
from app.engine.scanner import evaluate

FIXTURES = Path(__file__).parent / "fixtures"


def _parse_fixture(name):
    content = (FIXTURES / name).read_text(encoding="utf-8")
    return parse_files([(name, content)])


def test_fixture_parses_with_spans():
    project = _parse_fixture("score_formula.tf")
    assert not project.errors
    assert len(project.managed()) == 3
    for res in project.resources:
        assert isinstance(res.start_line, int) and res.start_line >= 1
        assert isinstance(res.end_line, int) and res.end_line >= res.start_line
    sg = project.managed("aws_security_group")[0]
    assert sg.address == "aws_security_group.edge"
    ingress = sg.attrs["ingress"]
    assert isinstance(ingress, list)
    assert ingress[0]["cidr_blocks"] == ["0.0.0.0/0"]


def test_clean_fixture_parses_all_resource_types():
    project = _parse_fixture("clean.tf")
    assert not project.errors
    assert len(project.managed()) == 6
    types = {r.type for r in project.managed()}
    assert "aws_s3_bucket" in types
    assert "aws_iam_policy" in types


def test_sources_retained_for_evidence():
    project = parse_files([("a.tf", 'resource "aws_s3_bucket" "b" {\n  acl = "private"\n}\n')])
    assert "a.tf" in project.sources
    assert project.resources[0].start_line == 1
    assert project.resources[0].end_line >= 2


def test_parse_error_is_reported_not_fatal():
    project = parse_files([("broken.tf", 'resource "aws_s3_bucket" {')])
    assert project.errors
    assert project.errors[0]["file"] == "broken.tf"
    findings, stats = evaluate(project, [])
    assert findings == []
    assert stats["score"] == 100.0
