# Guardrail Auditor — Enterprise Terraform Security

API-first auditor that scans Terraform (HCL) against an enterprise security
guardrail pack, persists every scan to a free database (SQLite), and visualizes
security posture on a built-in dashboard. Pure static analysis: no terraform
binary, no cloud credentials, nothing gets deployed.

**Scope:** Terraform files only — **CloudFormation is explicitly out of
scope.** And a design constraint worth stating plainly: **no cloud resources
were used by design**, at any point — the auditor reads text, and nothing
leaves your machine.

```
.tf files (multipart upload)
        │
        ▼
FastAPI  /api/v1  ──►  Rule engine (python-hcl2 parse → rules.yaml, 7 guardrails)
        │                          │
        ▼                          ▼
OpenAPI docs (/docs)      SQLite via SQLAlchemy (data/guardrail.db:
                                   │            scans · findings · files)
                                   ▼
                     Dashboard at /  (server-rendered, zero JS / zero CDN)
```

- **API-first** — every capability is a REST endpoint with interactive OpenAPI
  docs at `/docs`; the dashboard at `/` is a server-rendered view of the same
  SQLite data with no JavaScript and no external requests.
- **Free database** — SQLite by default; point `GUARDRAIL_DATABASE_URL` at
  Postgres/MySQL to swap (SQLAlchemy handles both).
- **Severity-weighted scoring** — failing a CRITICAL check costs 10× a LOW one;
  exact formula and a worked example under *Risk score* below.

## Quickstart

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8011
```

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --port 8011
```

- Dashboard: <http://127.0.0.1:8011>
- API docs: <http://127.0.0.1:8011/docs>

Then upload Terraform through the API and open the dashboard:

```bash
curl -s -X POST http://127.0.0.1:8011/api/v1/scans -F "files=@tests/fixtures/ssh_world.tf"
```

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

### curl examples — every endpoint

One command per line. On Unix shells type `curl`; in Windows PowerShell type
`curl.exe` (bare `curl` is an alias for `Invoke-WebRequest`).

```bash
# health — liveness and rule count
curl -s http://127.0.0.1:8011/api/v1/health

# rules — the loaded guardrail pack
curl -s http://127.0.0.1:8011/api/v1/rules

# create a scan — multipart upload (repeat -F for more files; optional label)
curl -s -X POST http://127.0.0.1:8011/api/v1/scans -F "files=@tests/fixtures/ssh_world.tf" -F "label=baseline"

# one scan by id
curl -s http://127.0.0.1:8011/api/v1/scans/1

# findings for a scan, filtered by severity
curl -s "http://127.0.0.1:8011/api/v1/scans/1/findings?severity=CRITICAL"
```

## Dashboard

One server-rendered page at `/` — **zero JavaScript, zero CDN, system fonts,
inline SVG only; nothing leaves your machine**:

- upload form (multiple `.tf` files + optional label, Post/Redirect/Get —
  same limits as the API);
- risk score with a color grade, severity badges, per-file scores;
- an **annotated source view**: your uploaded files with line numbers,
  finding lines highlighted in the severity color with the rule and message
  beneath, and the findings list linking straight to the flagged line;
- severity filter (plain links) and a score trend across scans as inline SVG.

Scans recorded before source storage existed simply show the findings list
with a note — never an error.

## Guardrail pack (7 rules, defined in `rules.yaml`)

| ID | Severity | Guardrail |
|---|---|---|
| S3-PUBLIC | CRITICAL | No public S3 buckets (inline ACL, `aws_s3_bucket_acl`, or a bucket policy with `"Principal": "*"`) |
| SSH-WORLD | CRITICAL | SSH (22) never open to 0.0.0.0/0 |
| RDP-WORLD | CRITICAL | RDP (3389) never open to 0.0.0.0/0 |
| S3-NO-ENCRYPTION | MEDIUM | Buckets declare server-side encryption (inline or companion resource) |
| EBS-NO-ENCRYPTION | HIGH | EBS volumes encrypted at rest (`encrypted` missing or false fails) |
| RDS-PUBLIC | HIGH | RDS instances not publicly accessible |
| IAM-WILDCARD | HIGH | No IAM policy grants `Action "*"` |

**Rules are user-editable data.** Adding or changing a guardrail means editing
`rules.yaml` — with zero code changes; the engine loads the pack at startup
from a configurable path (`GUARDRAIL_RULES_FILE`). A dedicated test proves it:
a newly added YAML rule is picked up by the engine and produces a finding.
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

This exact fixture (`tests/fixtures/score_formula.tf` — the public ACL is the
inline `acl` attribute on the bucket, not a separate `aws_s3_bucket_acl`
resource, so the denominator stays 37) with its hand-computed 40.5 is asserted
by `tests/test_score.py`.

## Tests

```powershell
.venv\Scripts\python -m pytest -q      # Windows
```
```bash
.venv/bin/python -m pytest -q          # macOS / Linux
```

33 tests, all against a throwaway database: golden fixtures asserting exact
(rule, resource, line) findings for every guardrail, the companion negative
fixture (bucket + linked SSE config ⇒ zero findings for S3-NO-ENCRYPTION),
the rules-are-data extensibility proof (a YAML-appended rule fires with zero
code changes), the hand-computed 40.5 score-formula fixture, API round-trips,
and dashboard end-to-end (form upload → redirect → annotated source render,
plus the no-stored-source fallback).

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `GUARDRAIL_RULES_FILE` | `./rules.yaml` | The guardrail pack (rules are data) |
| `GUARDRAIL_DATABASE_URL` | `sqlite:///./data/guardrail.db` | Any SQLAlchemy URL |
| `GUARDRAIL_DATA_DIR` | `./data` | Where the default SQLite file lives |
| `GUARDRAIL_MAX_FILES` | `500` | Max `.tf` files per scan |
| `GUARDRAIL_MAX_FILE_BYTES` | `1000000` | Per-file size cap |

## License

MIT — see `LICENSE`.

## Roadmap

- `terraform plan` JSON ingestion (catches computed values the HCL pass can't)
- Azure / GCP rule packs; custom rules from YAML
- Waiver / exception workflow with expiry dates
- API keys + roles; CI gate mode (`fail if score < threshold`) as a GitHub Action
- Postgres deployment profile
