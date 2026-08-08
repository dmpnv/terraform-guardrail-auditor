"""Saturday finding 1 (fresh-clone verification): CRLF inputs must not
silently scan as healthy.

python-hcl2 raises on \r, so before the fix a CRLF upload parsed to zero
resources and reported score 100 with no findings. CRLF content is built
in-test (never checked in) so the regression holds regardless of git eol
settings.
"""
from pathlib import Path

from app.engine.parser import parse_files
from app.engine.scanner import evaluate
from app.engine.yaml_engine import load_rules

FIXTURES = Path(__file__).parent / "fixtures"

LF_CONTENT = (FIXTURES / "ssh_world.tf").read_text(encoding="utf-8")  # universal newlines
CRLF_CONTENT = LF_CONTENT.replace("\n", "\r\n")

BROKEN = 'resource "aws_s3_bucket" {'


def _triples(findings):
    return sorted((f["rule_id"], f["resource_address"], f["line"]) for f in findings)


def test_crlf_equals_lf_at_parser_level():
    lf_project = parse_files([("ssh_world.tf", LF_CONTENT)])
    crlf_project = parse_files([("ssh_world.tf", CRLF_CONTENT)])
    assert crlf_project.errors == []
    assert len(crlf_project.managed()) == len(lf_project.managed()) == 2

    lf_findings, lf_stats = evaluate(lf_project, load_rules())
    crlf_findings, crlf_stats = evaluate(crlf_project, load_rules())
    assert _triples(crlf_findings) == _triples(lf_findings) == [
        ("SSH-WORLD", "aws_security_group.bastion", 11)
    ]
    assert crlf_stats["score"] == lf_stats["score"] == 75.0


def test_crlf_equals_lf_via_multipart_api(client):
    responses = {}
    for name, content in (("lf.tf", LF_CONTENT), ("crlf.tf", CRLF_CONTENT)):
        r = client.post(
            "/api/v1/scans",
            data={"label": f"crlf-regression-{name}"},
            files=[("files", (name, content.encode("utf-8"), "text/plain"))],
        )
        assert r.status_code == 201, r.text
        responses[name] = r.json()

    for scan in responses.values():
        assert scan["parse_errors"] == []
        assert scan["score"] == 75.0
        assert scan["findings_count"] == 1
        assert scan["findings"][0]["rule_id"] == "SSH-WORLD"
        assert scan["findings"][0]["line"] == 11


def test_parse_failure_is_surfaced_not_silent(client):
    """A file that fails to parse must be visible on the scan and the
    dashboard — never a clean 100 with zero checks and no explanation."""
    r = client.post(
        "/api/v1/scans",
        data={"label": "broken-upload"},
        files=[("files", ("broken.tf", BROKEN.encode("utf-8"), "text/plain"))],
    )
    assert r.status_code == 201, r.text
    scan = r.json()
    assert scan["checks_total"] == 0
    assert scan["findings"] == []
    assert scan["parse_errors"], "parse failure must be recorded on the scan"
    assert scan["parse_errors"][0]["file"] == "broken.tf"

    page = client.get("/")
    assert "could not be parsed" in page.text     # dashboard warning row
    assert "broken.tf" in page.text               # names the failing file