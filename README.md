# Guardrail Auditor — Enterprise Terraform Security

API-first auditor that scans Terraform (HCL) against an enterprise security
guardrail pack, persists every scan to a free database (SQLite), and visualizes
security posture on a built-in dashboard. Pure static analysis: no terraform
binary, no cloud credentials, nothing gets deployed.

```
.tf files / inline upload
        │
        ▼
FastAPI  /api/v1  ──►  Rule engine (python-hcl2 parse → 11 guardrails)
        │                          │
        ▼                          ▼
OpenAPI docs (/docs)      SQLite via SQLAlchemy (data/guardrail.db)
        │                          │
        └──────────►  Dashboard at /  (a plain consumer of the API)
```

- **API-first** — every capability is a REST endpoint; the dashboard holds no
  logic of its own. Interactive OpenAPI docs at `/docs`.
- **Free database** — SQLite by default; point `GUARDRAIL_DATABASE_URL` at
  Postgres/MySQL to swap (SQLAlchemy handles both).
- **Severity-weighted scoring** — failing a CRITICAL check costs 10× a LOW one;
  scans get a 0–100 score and an A–F grade.

## Quickstart (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8011
```

- Dashboard: <http://127.0.0.1:8011>
- API docs: <http://127.0.0.1:8011/docs>

Then click **“Scan insecure sample”** on the dashboard (or use the API below)
to watch every guardrail fire; **“Scan secure sample”** shows a clean 100/A run.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/v1/health` | Liveness + rule count |
| `GET`  | `/api/v1/rules` | The guardrail pack (id, severity, remediation, references) |
| `POST` | `/api/v1/scans` | Run a scan: `{"label", "path"}` **or** `{"label", "files": [{"path","content"}]}` |
| `GET`  | `/api/v1/scans` | Scan history (`limit`, `offset`) |
| `GET`  | `/api/v1/scans/{id}` | One scan with findings |
| `GET`  | `/api/v1/scans/{id}/findings` | Findings, filterable by `severity` / `rule_id` |
| `DELETE` | `/api/v1/scans/{id}` | Remove a scan and its findings |
| `GET`  | `/api/v1/summary` | Dashboard aggregate: latest scan, top rules, score trend |

```bash
curl -s -X POST http://127.0.0.1:8011/api/v1/scans \
  -H "Content-Type: application/json" \
  -d '{"label": "insecure baseline", "path": "samples/insecure"}'
```

## Guardrail pack (v0.1 — 11 rules)

| ID | Severity | Guardrail |
|---|---|---|
| GR-EBS-001 | HIGH | Block storage (EBS volumes, instance block devices) encrypted at rest |
| GR-EC2-001 | HIGH | EC2 instances enforce IMDSv2 (`http_tokens = "required"`) |
| GR-IAM-001 | CRITICAL | No IAM policy grants `Action "*"` on `Resource "*"` |
| GR-NET-001 | CRITICAL | SSH/RDP never exposed to 0.0.0.0/0 or ::/0 |
| GR-NET-002 | HIGH | Any world-open ingress is flagged |
| GR-RDS-001 | HIGH | RDS instances not publicly accessible |
| GR-RDS-002 | HIGH | RDS storage encrypted at rest |
| GR-S3-001 | CRITICAL | No public bucket ACLs |
| GR-S3-002 | MEDIUM | Buckets declare server-side encryption |
| GR-S3-003 | HIGH | Buckets enable all four public-access-block settings |
| GR-SEC-001 | CRITICAL | No hardcoded secrets (password/token/*_key literals) |

**Rules are user-editable data.** Adding or changing a guardrail means editing
`rules.yaml` — with zero code changes; the engine loads the pack at startup
from a configurable path (`GUARDRAIL_RULES_FILE`). A dedicated test proves it:
a newly added YAML rule is picked up by the engine and produces a finding.
*(Status note: the committed draft still ships rules as Python code in
`app/engine/rules.py`; the migration to `rules.yaml` is governed by `SPEC.md`
and lands in slice 2.)*

## Tests

```powershell
.venv\Scripts\python -m pytest -q
```

11 tests: engine unit tests (the insecure sample must trip **every** rule; the
secure sample must score 100.0) plus API round-trips through a throwaway DB.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `GUARDRAIL_DATABASE_URL` | `sqlite:///./data/guardrail.db` | Any SQLAlchemy URL |
| `GUARDRAIL_DATA_DIR` | `./data` | Where the default SQLite file lives |
| `GUARDRAIL_MAX_FILES` | `500` | Max `.tf` files per scan |
| `GUARDRAIL_MAX_FILE_BYTES` | `1000000` | Per-file size cap |

## Roadmap

- `terraform plan` JSON ingestion (catches computed values the HCL pass can't)
- Azure / GCP rule packs; custom rules from YAML
- Waiver / exception workflow with expiry dates
- API keys + roles; CI gate mode (`fail if score < threshold`) as a GitHub Action
- Postgres deployment profile
