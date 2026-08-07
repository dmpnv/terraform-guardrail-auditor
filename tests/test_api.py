"""API tests — scans are created via multipart upload (SPEC.md form)."""
SNIPPET = """
resource "aws_security_group" "open" {
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
"""


def post_scan(client, named_files, label=""):
    """Multipart POST /scans: named_files = [(filename, content_str), ...]."""
    return client.post(
        "/api/v1/scans",
        data={"label": label},
        files=[("files", (name, content.encode("utf-8"), "text/plain"))
               for name, content in named_files],
    )


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["rules_loaded"] == 7


def test_rules_endpoint(client):
    r = client.get("/api/v1/rules")
    assert r.status_code == 200
    assert any(rule["id"] == "SSH-WORLD" for rule in r.json())


def test_multipart_scan_roundtrip(client):
    r = post_scan(client, [("main.tf", SNIPPET)], label="api-test")
    assert r.status_code == 201, r.text
    scan = r.json()
    assert scan["checks_failed"] >= 1
    assert scan["severity_counts"]["CRITICAL"] >= 1
    assert any(f["rule_id"] == "SSH-WORLD" for f in scan["findings"])
    assert scan["file_scores"]["main.tf"] == 50.0
    sid = scan["id"]

    r2 = client.get(f"/api/v1/scans/{sid}/findings", params={"severity": "critical"})
    assert r2.status_code == 200
    assert len(r2.json()) >= 1

    r3 = client.get(f"/api/v1/scans/{sid}")
    assert r3.status_code == 200
    assert r3.json()["id"] == sid
    assert r3.json()["findings_count"] == len(r3.json()["findings"])


def test_multi_file_upload_gets_per_file_scores(client):
    bad = ('resource "aws_db_instance" "r" {\n'
           '  publicly_accessible = true\n'
           '  skip_final_snapshot = true\n'
           '}\n')
    good = ('resource "aws_ebs_volume" "v" {\n'
            '  availability_zone = "us-east-1a"\n'
            '  size              = 10\n'
            '  encrypted         = true\n'
            '}\n')
    r = post_scan(client, [("bad.tf", bad), ("good.tf", good)], label="multi")
    assert r.status_code == 201, r.text
    scan = r.json()
    assert scan["files_scanned"] == 2
    assert scan["file_scores"] == {"bad.tf": 0.0, "good.tf": 100.0}
    assert scan["score"] == 50.0


def test_scan_without_files_is_422(client):
    r = client.post("/api/v1/scans", data={"label": "empty"})
    assert r.status_code == 422


def test_off_spec_endpoints_are_gone(client):
    """Slice 4 deletions: only the five spec endpoints remain."""
    assert client.get("/api/v1/summary").status_code == 404
    assert client.get("/api/v1/scans").status_code == 405       # POST-only path
    assert client.delete("/api/v1/scans/1").status_code == 405  # GET-only path


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Guardrail" in r.text
    assert "Risk score" in r.text


def test_dashboard_severity_filter(client):
    r = client.get("/", params={"severity": "CRITICAL"})
    assert r.status_code == 200
    assert "Critical" in r.text


def test_theme_routes_and_rendering(client):
    """Turn-19 amendment: cookie-based theming, zero JS."""
    page = client.get("/")
    assert '<html lang="en" data-theme' not in page.text    # system default

    r = client.get("/theme/light", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert "theme=light" in r.headers.get("set-cookie", "")

    page = client.get("/")                                  # cookie persisted
    assert '<html lang="en" data-theme="light">' in page.text

    r = client.get("/theme/system", follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/")                                  # override cleared
    assert '<html lang="en" data-theme' not in page.text


def test_dashboard_form_upload_redirects_and_renders(client):
    """Amendment (Turn 13): plain-HTML form POST / -> 303 (PRG) -> GET /
    renders the newly created scan — the user never lands on raw JSON."""
    content = ('resource "aws_db_instance" "r" {\n'
               '  publicly_accessible = true\n'
               '  skip_final_snapshot = true\n'
               '}\n')
    r = client.post(
        "/",
        data={"label": "form-upload"},
        files=[("files", ("form_rds.tf", content.encode("utf-8"), "text/plain"))],
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    page = client.get("/")
    assert page.status_code == 200
    assert "form-upload" in page.text          # the new scan is the latest
    assert "RDS-PUBLIC" in page.text           # its finding renders
    assert "form_rds.tf" in page.text          # per-file scores block

    # Turn-14 amendment: annotated source view with anchors and annotations
    assert 'id="src-form-rds-tf-L2"' in page.text            # flagged line anchor
    assert 'href="#src-form-rds-tf-L2"' in page.text         # list links to source
    assert "publicly_accessible = true" in page.text         # escaped source text
    assert "RDS instance is publicly accessible." in page.text  # annotation message
    # Turn-20 fix: remediation joins the annotation, muted, beneath
    assert "Fix:" in page.text
    assert "SSM port forwarding" in page.text                # rds remediation text


def test_dashboard_without_stored_sources_shows_note(client):
    """Scans recorded before the files table existed have no stored sources:
    the findings list renders full-width with a muted note — never an error."""
    content = ('resource "aws_ebs_volume" "v" {\n'
               '  availability_zone = "us-east-1a"\n'
               '  size = 5\n'
               '}\n')
    r = post_scan(client, [("legacy.tf", content)], label="legacy-sim")
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    from app.db import SessionLocal
    from app.models import ScanFile
    with SessionLocal() as db:
        db.query(ScanFile).filter(ScanFile.scan_id == sid).delete()
        db.commit()

    page = client.get("/")
    assert page.status_code == 200
    assert "Source not stored for this scan." in page.text
    assert "EBS-NO-ENCRYPTION" in page.text    # findings list still renders
    assert 'id="src-legacy-tf' not in page.text  # no source column
