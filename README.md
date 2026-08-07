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
  exact formula and a worked example under *Risk score* below.

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

All endpoints live under the **`/api/v1`** prefix (locked).

Spec endpoints (`SPEC.md`):

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/v1/health` | Liveness + rule count |
| `GET`  | `/api/v1/rules` | The guardrail pack (id, severity, message, remediation) |
| `POST` | `/api/v1/scans` | Upload one or more `.tf` files and run a scan |
| `GET`  | `/api/v1/scans/{id}` | One scan with its scores |
| `GET`  | `/api/v1/scans/{id}/findings` | Findings, filterable by `severity` |

Draft-only endpoints still present until slices 3–4 remove them:
`GET /api/v1/scans` (list), `DELETE /api/v1/scans/{id}`, `GET /api/v1/summary`.

### curl examples — every endpoint

One command per line. On Unix shells type `curl`; in Windows PowerShell type
`curl.exe` (bare `curl` is an alias for `Invoke-WebRequest`).

```bash
# health — liveness and rule count
curl -s http://127.0.0.1:8011/api/v1/health

# rules — the loaded guardrail pack
curl -s http://127.0.0.1:8011/api/v1/rules

# create a scan — target form per SPEC.md (multipart upload; lands in slice 3;
# repeat -F for more files)
curl -s -X POST http://127.0.0.1:8011/api/v1/scans -F "files=@tests/fixtures/ssh_world.tf"

# create a scan — draft form (works against the committed draft today)
curl -s -X POST http://127.0.0.1:8011/api/v1/scans -H "Content-Type: application/json" -d '{"label": "insecure baseline", "path": "samples/insecure"}'

# one scan by id
curl -s http://127.0.0.1:8011/api/v1/scans/1

# findings for a scan, filtered by severity
curl -s "http://127.0.0.1:8011/api/v1/scans/1/findings?severity=CRITICAL"
```

The dashboard is not an API endpoint — open <http://127.0.0.1:8011/> in a
browser.

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

**Data contract — `companion_type` on `absent`:** `absent <attr>` normally
flags a resource when `<attr>` is missing. With `companion_type: <type>` the
check instead **passes** if the scan contains a resource of `<type>` that is
*linked* to the checked resource — linked meaning any top-level argument of
the companion either references the checked resource's address (e.g. contains
`aws_s3_bucket.reports`) or literally equals the checked resource's
name-defining argument (for S3, `bucket`). This models arguments the AWS
provider v4+ split into companion resources; S3-NO-ENCRYPTION uses it. A
negative fixture guarantees that a bucket with its
`aws_s3_bucket_server_side_encryption_configuration` in the same file yields
zero findings for that rule.

## Risk score

Weights: CRITICAL = 10, HIGH = 5, MEDIUM = 2, LOW = 1.

**One evaluated check = one (rule, resource) pair** where the resource's type
matches the rule's `resource_type` list. Rules whose `resource_type` does not
occur anywhere in the scan contribute nothing to the denominator. A failed
pair counts its rule's weight once, no matter how many clauses matched.

```
score = 100 × (1 − Σ weight(failed checks) / Σ weight(evaluated checks))
```

rounded to one decimal; a scan with zero evaluated checks scores 100.0. The
per-file score applies the same formula to that file's resources only.

**Worked example** — one file containing an S3 bucket with
`acl = "public-read"` and no encryption, a security group with SSH 22 open to
0.0.0.0/0, and an EBS volume with `encrypted = true`; no RDS instance and no
IAM policy anywhere in the scan:

| Rule (severity → weight) | Evaluated against | Result |
|---|---|---|
| S3-PUBLIC (CRITICAL → 10) | the bucket | FAIL |
| SSH-WORLD (CRITICAL → 10) | the security group | FAIL |
| RDP-WORLD (CRITICAL → 10) | the security group | pass |
| S3-NO-ENCRYPTION (MEDIUM → 2) | the bucket | FAIL |
| EBS-NO-ENCRYPTION (HIGH → 5) | the volume | pass |
| RDS-PUBLIC (HIGH → 5) | no `aws_db_instance` in scan | not evaluated |
| IAM-WILDCARD (HIGH → 5) | no IAM policy resources in scan | not evaluated |

Denominator = 10 + 10 + 10 + 2 + 5 = **37** · numerator = 10 + 10 + 2 = **22**

`score = 100 × (1 − 22/37) = 40.5405… →` **40.5**

This exact fixture with its hand-computed 40.5 is asserted by a pytest.
*(Status note: the committed draft still runs interim weights 10/6/3/1 over an
11-rule pack; the formula above becomes the implementation in slice 3 per
`SPEC.md`.)*

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
