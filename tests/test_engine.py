"""Parser tests: normalization, provenance spans, parse-error resilience.

The draft's 11-rule code-pack tests were removed in slice 1 — the YAML engine
supersedes the Python pack (deleted entirely in slice 2), and rule coverage
now lives in the golden-fixture tests.
"""
from app import config
from app.engine.parser import parse_files, parse_path
from app.engine.scanner import evaluate

SAMPLES = config.BASE_DIR / "samples"


def test_insecure_sample_parses_with_spans():
    project = parse_path(SAMPLES / "insecure")
    assert not project.errors
    assert len(project.managed()) == 6
    for res in project.resources:
        assert isinstance(res.start_line, int) and res.start_line >= 1
        assert isinstance(res.end_line, int) and res.end_line >= res.start_line
    sg = project.managed("aws_security_group")[0]
    assert sg.address == "aws_security_group.edge"
    ingress = sg.attrs["ingress"]
    assert isinstance(ingress, list) and len(ingress) == 2
    assert ingress[0]["cidr_blocks"] == ["0.0.0.0/0"]


def test_secure_sample_parses():
    project = parse_path(SAMPLES / "secure")
    assert not project.errors
    assert len(project.managed()) == 9


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
