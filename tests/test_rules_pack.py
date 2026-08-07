"""Slice 2: golden fixtures for the full 7-rule pack + rules-are-data proof.

Every fixture asserts its expected findings exactly: (rule_id,
resource_address, line), per SPEC.md.
"""
import shutil
from pathlib import Path

from app.engine.parser import parse_files
from app.engine.scanner import evaluate
from app.engine.yaml_engine import load_rules, rules_path

FIXTURES = Path(__file__).parent / "fixtures"

SPEC_RULE_IDS = ["S3-PUBLIC", "SSH-WORLD", "RDP-WORLD", "S3-NO-ENCRYPTION",
                 "EBS-NO-ENCRYPTION", "RDS-PUBLIC", "IAM-WILDCARD"]


def scan_fixture(name):
    content = (FIXTURES / name).read_text(encoding="utf-8")
    project = parse_files([(name, content)])
    assert not project.errors, project.errors
    return evaluate(project, load_rules())


def triples(findings):
    return sorted((f["rule_id"], f["resource_address"], f["line"]) for f in findings)


def test_pack_is_exactly_the_seven_spec_rules():
    assert [r.id for r in load_rules()] == SPEC_RULE_IDS


def test_s3_public_acl_and_policy_flavors():
    findings, _ = scan_fixture("s3_public.tf")
    assert triples(findings) == [
        ("S3-PUBLIC", "aws_s3_bucket.web", 6),
        ("S3-PUBLIC", "aws_s3_bucket_policy.assets_public", 41),
    ]
    by_addr = {f["resource_address"]: f for f in findings}
    assert "public-read" in by_addr["aws_s3_bucket.web"]["evidence"]
    assert '"Principal": "*"' in by_addr["aws_s3_bucket_policy.assets_public"]["evidence"]


def test_rdp_world():
    findings, _ = scan_fixture("rdp_world.tf")
    assert triples(findings) == [("RDP-WORLD", "aws_security_group.winbox", 11)]
    assert "0.0.0.0/0" in findings[0]["evidence"]


def test_s3_no_encryption():
    findings, _ = scan_fixture("s3_no_encryption.tf")
    assert triples(findings) == [("S3-NO-ENCRYPTION", "aws_s3_bucket.logs", 3)]
    # absence has no matching line: evidence falls back to the block header
    assert findings[0]["evidence"].startswith('resource "aws_s3_bucket" "logs"')


def test_companion_negative_fixture_zero_findings():
    """SPEC.md interpretation 2, condition 2: bucket + linked SSE companion in
    the same file -> zero findings for S3-NO-ENCRYPTION (here: zero at all)."""
    findings, stats = scan_fixture("s3_encrypted_companion.tf")
    assert findings == []
    assert stats["score"] == 100.0


def test_ebs_no_encryption_absent_and_false():
    findings, _ = scan_fixture("ebs_no_encryption.tf")
    assert triples(findings) == [
        ("EBS-NO-ENCRYPTION", "aws_ebs_volume.cache", 12),
        ("EBS-NO-ENCRYPTION", "aws_ebs_volume.scratch", 4),
    ]


def test_rds_public():
    findings, _ = scan_fixture("rds_public.tf")
    assert triples(findings) == [("RDS-PUBLIC", "aws_db_instance.reporting", 8)]
    assert findings[0]["evidence"].startswith("publicly_accessible")


def test_iam_wildcard():
    findings, _ = scan_fixture("iam_wildcard.tf")
    assert triples(findings) == [("IAM-WILDCARD", "aws_iam_policy.ops_admin", 12)]
    assert '"Action": "*"' in findings[0]["evidence"]


def test_clean_fixture_zero_findings():
    findings, stats = scan_fixture("clean.tf")
    assert findings == []
    assert stats["score"] == 100.0
    assert stats["checks_total"] > 0


def test_extensibility_new_yaml_rule_zero_code_changes(tmp_path, monkeypatch):
    """SPEC.md rules-are-data proof: append a brand-new rule in YAML only,
    point the engine at the copy, and it produces a finding."""
    src = rules_path()                     # resolve before the env override
    pack = tmp_path / "rules.yaml"
    shutil.copyfile(src, pack)
    with open(pack, "a", encoding="utf-8") as fh:
        fh.write(
            "\n- id: TEST-TAGS-REQUIRED\n"
            "  severity: LOW\n"
            "  resource_type: aws_s3_bucket\n"
            "  check:\n"
            "    - op: absent\n"
            "      attr: tags\n"
            "  message: \"Bucket carries no tags.\"\n"
            "  remediation: \"Add owner/cost-center tags.\"\n"
        )
    monkeypatch.setenv("GUARDRAIL_RULES_FILE", str(pack))

    findings, _ = scan_fixture("s3_no_encryption.tf")
    ids = {f["rule_id"] for f in findings}
    assert "TEST-TAGS-REQUIRED" in ids     # the YAML-only rule fired
    assert "S3-NO-ENCRYPTION" in ids       # the original pack still applies
    new = next(f for f in findings if f["rule_id"] == "TEST-TAGS-REQUIRED")
    assert new["severity"] == "LOW"
    assert new["resource_address"] == "aws_s3_bucket.logs"
    assert new["message"] == "Bucket carries no tags."
