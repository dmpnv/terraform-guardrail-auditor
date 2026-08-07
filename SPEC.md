# SPEC — Terraform Guardrail Auditor (MVP) · v1, for approval

## Purpose & scope
Audit Terraform HCL against **seven fixed security guardrails** via a local,
API-first service with persisted scan history and a dependency-free dashboard.
**Terraform files only; CloudFormation explicitly out of scope (stated in
README).** Pure static analysis — no terraform binary, **no cloud services of
any kind at any point**. Runtime: Python 3.12 in a plain venv, Windows and
Unix. No Docker, no containers.

## Rule pack (exactly 7 — data, not code)
| # | id | severity | resource_type | check (fixed operators only) |
|---|---|---|---|---|
| 1 | S3-PUBLIC | CRITICAL | aws_s3_bucket, aws_s3_bucket_acl, aws_s3_bucket_policy | `acl eq [public-read, public-read-write]` OR `policy contains "Principal": "*"` |
| 2 | SSH-WORLD | CRITICAL | aws_security_group, aws_security_group_rule | `open_port(22, 0.0.0.0/0)` |
| 3 | RDP-WORLD | CRITICAL | aws_security_group, aws_security_group_rule | `open_port(3389, 0.0.0.0/0)` |
| 4 | S3-NO-ENCRYPTION | MEDIUM | aws_s3_bucket | `server_side_encryption_configuration absent` (companion-aware, see below) |
| 5 | EBS-NO-ENCRYPTION | HIGH | aws_ebs_volume | `encrypted absent` OR `encrypted eq false` |
| 6 | RDS-PUBLIC | HIGH | aws_db_instance | `publicly_accessible eq true` |
| 7 | IAM-WILDCARD | HIGH | aws_iam_policy, aws_iam_role_policy, aws_iam_user_policy, aws_iam_group_policy | `policy contains "Action": "*"` |

**`rules.yaml`** (one file) — entry fields exactly: `id / severity /
resource_type / check / message / remediation`. `check` is a list of clauses;
a resource **fails if any clause matches**. Operator vocabulary is closed:
- `exists <attr>` / `absent <attr>`
- `eq <attr> <value>` — booleans and strings
- `contains <attr> <substring>` — whitespace-normalized substring match
- `open_port {port, cidr}` — an ingress definition whose port range covers
  `port` (or protocol `-1`/`all`) with `cidr` in its sources
No eval, no expression language. An unknown operator in YAML is a startup error.

**Interpretations needing your sign-off** (parameterizations, not new operators):
1. `resource_type` and clause values may be **lists** (list = any-of) — needed
   for "ACL **or** policy" and the two public ACL values.
2. `absent` takes an optional `companion_type`: the check passes when a
   resource of that type references this resource (S3 encryption lives in a
   split `aws_s3_bucket_server_side_encryption_configuration` resource on
   AWS provider v4+). Used by rule 4 only.
3. Severity assignments above (3× CRITICAL, 3× HIGH, 1× MEDIUM) are my
   proposal — say the word to re-grade.

## Findings & provenance
Every finding carries: `file, line, resource_address, rule_id, severity,
message, remediation, evidence` (trimmed source snippet of the matching
attribute, else the block header). Line numbers: try python-hcl2 `with_meta`
first; installed 8.1.2 does not support it → **bounded scan**: locate the
`resource "type" "name"` header in the source, evidence found only within that
block's span (header to next top-level header). No hand-built parser.

## API (FastAPI, `/api/v1`) + dashboard
`POST /scans` (multipart upload, one or more `.tf` files) · `GET /scans/{id}`
· `GET /scans/{id}/findings` · `GET /rules` · `GET /health`.
`GET /` — **one server-rendered HTML page** (Jinja2 template): overall risk
score, per-severity counts, findings table with severity filter (via query
parameter — zero client JS), trend across scans as **inline SVG**. **No CDN,
no JS framework, no webfonts — zero external requests.**

## Storage & scoring
SQLite only (`data/guardrail.db`, SQLAlchemy), tables `scans` and `findings`;
history persists across runs to draw the trend. Score (formula goes in
README): weights CRITICAL=10, HIGH=5, MEDIUM=2, LOW=1;
`score = 100 × (1 − Σ weight(failed checks) / Σ weight(evaluated checks))`,
rounded to 1 decimal; no evaluated checks → 100. Computed **per file and per
scan**.

## Tests
pytest golden fixtures in `tests/fixtures/`: one deliberately-bad `.tf` per
rule plus one clean `.tf`; expected findings (rule id, resource address, line)
asserted exactly.

## Repo hygiene
Pinned `requirements.txt` (adds PyYAML, python-multipart, Jinja2; removes
nothing blindly — pins from the working venv), MIT `LICENSE`, `.gitignore`, no
secrets or tokens anywhere. README: architecture, exact score formula, run
commands for Windows **and** Unix, CloudFormation-out-of-scope note, and a
statement that **no cloud resources were used by design**. Local git only —
no remotes, no push.

## Delivery — compliance slices over the existing draft (1 slice = 1 turn, verified + committed)
1. YAML rule engine skeleton + provenance (line + evidence) in the parser +
   **one rule (SSH-WORLD) end to end** + its golden fixture test.
2. Remaining six rules in `rules.yaml` + fixtures; **delete** the Python
   11-rule pack.
3. Per-file + total score, server-rendered dashboard with inline-SVG trend
   (**delete** the Chart.js/Google-Fonts CDN page), multipart `POST /scans`.
4. README, LICENSE, pinned requirements, polish; **delete** everything the
   spec doesn't call for — `GET /scans` list, `DELETE /scans/{id}`,
   `/api/v1/summary`, JSON-body scan inputs (path + inline), `samples/`
   (superseded by fixtures) — each deletion noted in `prompts.md`.

Post-MVP (time-budgeted): short Marp slide deck on the result, on request.

## Out of scope
CloudFormation, `terraform plan` JSON, `::/0` variants, module resolution,
cross-file references beyond the S3 companion rule, auth/multi-user, waivers,
Postgres, Docker, any cloud usage.
