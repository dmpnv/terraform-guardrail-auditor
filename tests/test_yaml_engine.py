"""Slice 1: YAML rule pack loader + SSH-WORLD end to end with provenance."""
from pathlib import Path

import pytest

from app.engine.parser import parse_files
from app.engine.scanner import evaluate
from app.engine.yaml_engine import RulePackError, load_rules

FIXTURES = Path(__file__).parent / "fixtures"


def test_pack_loads_ssh_world():
    rules = {r.id: r for r in load_rules()}
    r = rules["SSH-WORLD"]
    assert r.severity == "CRITICAL"
    assert r.resource_type == ("aws_security_group", "aws_security_group_rule")
    assert r.check[0].op == "open_port"
    assert r.check[0].port == 22
    assert r.check[0].cidr == "0.0.0.0/0"


def test_loader_rejects_unknown_operator(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "- id: X-1\n"
        "  severity: LOW\n"
        "  resource_type: aws_s3_bucket\n"
        "  check: [{op: regex, attr: acl, value: p}]\n"
        "  message: m\n"
        "  remediation: r\n",
        encoding="utf-8",
    )
    with pytest.raises(RulePackError, match="unknown operator"):
        load_rules(bad)


def test_loader_rejects_missing_field(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "- id: X-1\n"
        "  severity: LOW\n"
        "  resource_type: aws_s3_bucket\n"
        "  check: [{op: exists, attr: acl}]\n"
        "  message: m\n",
        encoding="utf-8",
    )
    with pytest.raises(RulePackError, match="missing fields"):
        load_rules(bad)


def test_rules_file_env_override(tmp_path, monkeypatch):
    alt = tmp_path / "alt.yaml"
    alt.write_text(
        "- id: CUSTOM-1\n"
        "  severity: HIGH\n"
        "  resource_type: aws_security_group\n"
        "  check: [{op: open_port, port: 80, cidr: 0.0.0.0/0}]\n"
        "  message: m\n"
        "  remediation: r\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GUARDRAIL_RULES_FILE", str(alt))
    assert [r.id for r in load_rules()] == ["CUSTOM-1"]


def test_ssh_world_golden_fixture():
    content = (FIXTURES / "ssh_world.tf").read_text(encoding="utf-8")
    project = parse_files([("ssh_world.tf", content)])
    findings, stats = evaluate(project, load_rules())

    assert len(findings) == 1, findings
    f = findings[0]
    assert f["rule_id"] == "SSH-WORLD"
    assert f["severity"] == "CRITICAL"
    assert f["resource_address"] == "aws_security_group.bastion"
    assert f["file"] == "ssh_world.tf"
    assert f["line"] == 11                      # the cidr_blocks line
    assert f["evidence"].startswith("cidr_blocks")
    assert "0.0.0.0/0" in f["evidence"]

    # two SGs x (SSH-WORLD + RDP-WORLD) = 4 pairs; one failed -> 100*(1-10/40)
    assert stats["checks_total"] == 4
    assert stats["checks_failed"] == 1
    assert stats["score"] == 75.0


def test_ssh_world_end_to_end_api(client):
    content = (FIXTURES / "ssh_world.tf").read_text(encoding="utf-8")
    r = client.post(
        "/api/v1/scans",
        data={"label": "slice1-e2e"},
        files=[("files", ("ssh_world.tf", content.encode("utf-8"), "text/plain"))],
    )
    assert r.status_code == 201, r.text
    scan = r.json()
    assert scan["findings_count"] == 1
    f = scan["findings"][0]
    assert f["rule_id"] == "SSH-WORLD"
    assert f["line"] == 11
    assert "0.0.0.0/0" in f["evidence"]

    rules = client.get("/api/v1/rules").json()
    assert "SSH-WORLD" in [x["id"] for x in rules]
    assert len(rules) == 7
    health = client.get("/api/v1/health").json()
    assert health["rules_loaded"] == 7
