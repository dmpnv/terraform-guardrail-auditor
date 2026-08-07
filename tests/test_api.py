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

    r3 = client.get("/api/v1/summary")
    assert r3.status_code == 200
    assert r3.json()["latest"]["id"] == sid


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


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Guardrail" in r.text
    assert "Risk score" in r.text


def test_dashboard_severity_filter(client):
    r = client.get("/", params={"severity": "CRITICAL"})
    assert r.status_code == 200
    assert "Critical" in r.text


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
