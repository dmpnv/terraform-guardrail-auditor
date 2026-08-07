from app import config
from app.engine.parser import parse_files, parse_path
from app.engine.rules import all_rules
from app.engine.scanner import evaluate

SAMPLES = config.BASE_DIR / "samples"


def test_rule_pack_loaded():
    rules = all_rules()
    assert len(rules) >= 11
    assert len({r.id for r in rules}) == len(rules)


def test_insecure_sample_trips_every_guardrail():
    project = parse_path(SAMPLES / "insecure")
    assert not project.errors
    findings, stats = evaluate(project)
    fired = {f["rule_id"] for f in findings}
    assert fired == {r.id for r in all_rules()}
    assert stats["score"] < 60


def test_secure_sample_is_clean():
    project = parse_path(SAMPLES / "secure")
    assert not project.errors
    findings, stats = evaluate(project)
    assert findings == []
    assert stats["score"] == 100.0


def test_parse_error_is_reported_not_fatal():
    project = parse_files([("broken.tf", 'resource "aws_s3_bucket" {')])
    assert project.errors
    assert project.errors[0]["file"] == "broken.tf"
    findings, stats = evaluate(project)
    assert findings == []
