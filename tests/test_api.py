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


def test_inline_scan_roundtrip(client):
    r = client.post("/api/v1/scans", json={
        "label": "api-test",
        "files": [{"path": "main.tf", "content": SNIPPET}],
    })
    assert r.status_code == 201, r.text
    scan = r.json()
    assert scan["checks_failed"] >= 1
    assert scan["severity_counts"]["CRITICAL"] >= 1
    assert any(f["rule_id"] == "SSH-WORLD" for f in scan["findings"])
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


def test_unknown_path_is_400(client):
    r = client.post("/api/v1/scans", json={"path": "no/such/dir"})
    assert r.status_code == 400


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Guardrail" in r.text
