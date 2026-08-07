"""Slice 3: the score formula asserted against hand-computed fixtures."""
from pathlib import Path

from app.engine.parser import parse_files
from app.engine.scanner import evaluate
from app.engine.yaml_engine import load_rules

FIXTURES = Path(__file__).parent / "fixtures"


def test_score_formula_worked_example():
    """README worked example, computed by hand:

    pairs: S3-PUBLIC×bucket FAIL(10) · SSH-WORLD×sg FAIL(10) · RDP-WORLD×sg
    pass(10) · S3-NO-ENCRYPTION×bucket FAIL(2) · EBS-NO-ENCRYPTION×volume
    pass(5). RDS-PUBLIC and IAM-WILDCARD have no matching resource types and
    contribute nothing to the denominator.
    denominator 37, numerator 22 -> 100 × (1 − 22/37) = 40.5405… -> 40.5
    """
    content = (FIXTURES / "score_formula.tf").read_text(encoding="utf-8")
    project = parse_files([("score_formula.tf", content)])
    findings, stats = evaluate(project, load_rules())

    assert {f["rule_id"] for f in findings} == {"S3-PUBLIC", "SSH-WORLD", "S3-NO-ENCRYPTION"}
    assert stats["checks_total"] == 5
    assert stats["checks_failed"] == 3
    assert stats["score"] == 40.5
    assert stats["file_scores"] == {"score_formula.tf": 40.5}


def test_per_file_scores_are_independent():
    bad = ('resource "aws_db_instance" "r" {\n'
           '  publicly_accessible = true\n'
           '  skip_final_snapshot = true\n'
           '}\n')
    good = ('resource "aws_ebs_volume" "v" {\n'
            '  availability_zone = "us-east-1a"\n'
            '  size              = 10\n'
            '  encrypted         = true\n'
            '}\n')
    project = parse_files([("bad.tf", bad), ("good.tf", good)])
    findings, stats = evaluate(project, load_rules())

    # bad.tf: one HIGH pair failed -> 0.0; good.tf: one HIGH pair passed -> 100.0
    assert stats["file_scores"] == {"bad.tf": 0.0, "good.tf": 100.0}
    # scan total: 100 × (1 − 5/10) = 50.0
    assert stats["score"] == 50.0


def test_file_with_no_evaluated_checks_scores_100():
    content = 'resource "aws_cloudwatch_log_group" "g" {\n  name = "app"\n}\n'
    project = parse_files([("logs.tf", content)])
    findings, stats = evaluate(project, load_rules())
    assert findings == []
    assert stats["checks_total"] == 0
    assert stats["score"] == 100.0
    assert stats["file_scores"] == {"logs.tf": 100.0}
