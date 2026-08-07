SNIPPET = """
resource "aws_security_group" "open" {
  ingress {
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
"""


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_rules_endpoint(client):
    r = client.get("/api/v1/rules")
    assert r.status_code == 200
    assert any(rule["id"] == "GR-NET-001" for rule in r.json())


def test_inline_scan_roundtrip(client):
    r = client.post("/api/v1/scans", json={
        "label": "api-test",
        "files": [{"path": "main.tf", "content": SNIPPET}],
    })
    assert r.status_code == 201, r.text
    scan = r.json()
    assert scan["checks_failed"] >= 1
    assert scan["severity_counts"]["CRITICAL"] >= 1
    assert any(f["rule_id"] == "GR-NET-001" for f in scan["findings"])
    sid = scan["id"]

    r2 = client.get(f"/api/v1/scans/{sid}/findings", params={"severity": "critical"})
    assert r2.status_code == 200
    assert len(r2.json()) >= 1

    r3 = client.get("/api/v1/summary")
    assert r3.status_code == 200
    assert r3.json()["latest"]["id"] == sid


def test_scan_requires_exactly_one_source(client):
    assert client.post("/api/v1/scans", json={"label": "bad"}).status_code == 422


def test_path_scan_of_samples(client):
    r = client.post("/api/v1/scans", json={
        "label": "insecure-sample",
        "path": "samples/insecure",
    })
    assert r.status_code == 201, r.text
    assert r.json()["score"] < 60
    assert r.json()["grade"] == "F"


def test_unknown_path_is_400(client):
    r = client.post("/api/v1/scans", json={"path": "no/such/dir"})
    assert r.status_code == 400


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Guardrail" in r.text
