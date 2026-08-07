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

**Rules are user-editable data: adding or changing a rule means editing
`rules.yaml` and nothing else — zero code changes.** The engine loads the pack
from a configurable path (`GUARDRAIL_RULES_FILE`, default `rules.yaml`) at
startup. The README states this policy explicitly, and a dedicated test proves
it (see Tests).

**Interpretations** (parameterizations, not new operators — 3 still needs
your sign-off):
1. **ACCEPTED (Turn 8):** `resource_type` and clause values may be **lists**
   (list = any-of) — needed for "ACL **or** policy" and the two public ACL
   values.
2. **ACCEPTED (Turn 5), with two conditions now part of this spec:** `absent`
   takes an optional `companion_type`. Semantics (data contract, documented in
   the README next to the rules-are-data policy): the check **passes** when
   the scan contains a resource of `companion_type` **linked** to the checked
   resource — linked meaning any top-level argument of the companion either
   references the checked resource's address (e.g. contains
   `aws_s3_bucket.reports`) or literally equals the checked resource's
   name-defining argument (for S3, `bucket`). Models arguments the AWS
   provider v4+ split into companion resources; used by rule 4 only.
   Condition two: a **negative fixture** — a bucket plus its
   `aws_s3_bucket_server_side_encryption_configuration` in the same file must
   produce **zero findings for rule 4** (see Tests).
3. Severity assignments above (3× CRITICAL, 3× HIGH, 1× MEDIUM) are my
   proposal — say the word to re-grade.

## Findings & provenance
Every finding carries: `file, line, resource_address, rule_id, severity,
message, remediation, evidence` (trimmed source snippet of the matching
attribute, else the block header). Line numbers: try python-hcl2 `with_meta`
first; installed 8.1.2 does not support it → **bounded scan**: locate the
`resource "type" "name"` header in the source, evidence found only within that
block's span (header to next top-level header). No hand-built parser.

## API (FastAPI, `/api/v1` — prefix locked) + dashboard
`POST /scans` (multipart upload, one or more `.tf` files) · `GET /scans/{id}`
· `GET /scans/{id}/findings` · `GET /rules` · `GET /health`.
`GET /` — **one server-rendered HTML page** (Jinja2 template): overall risk
score, per-severity counts, findings table with severity filter (via query
parameter — zero client JS), trend across scans as **inline SVG**. **No CDN,
no JS framework, no webfonts — zero external requests.**

## Storage & scoring
SQLite only (`data/guardrail.db`, SQLAlchemy), tables `scans` and `findings`;
history persists across runs to draw the trend. Score (formula **and worked
numeric example** go in README): weights CRITICAL=10, HIGH=5, MEDIUM=2, LOW=1;
`score = 100 × (1 − Σ weight(failed checks) / Σ weight(evaluated checks))`,
rounded to 1 decimal; no evaluated checks → 100. Computed **per file and per
scan** (per file = the same formula restricted to that file's resources).

**Evaluated check, precisely: one (rule, resource) pair where the resource's
type matches the rule's `resource_type` list.** A rule whose `resource_type`
does not occur anywhere in the scan contributes **nothing** to the
denominator. A failed pair adds its rule's weight to the numerator **once**,
no matter how many clauses or attribute matches it produced.

## Tests
pytest golden fixtures in `tests/fixtures/`: one deliberately-bad `.tf` per
rule plus one clean `.tf`; expected findings (rule id, resource address, line)
asserted exactly.

Plus a **rule-extensibility test** proving rules-are-data: copy `rules.yaml`,
append a brand-new rule in YAML only (e.g. LOW / `aws_s3_bucket` /
`tags absent`), point the engine at the copy via `GUARDRAIL_RULES_FILE`, scan
a fixture, and assert the new rule id surfaces as a finding with full
provenance — zero code changes anywhere.

A **companion negative fixture**: a bucket plus its linked
`aws_s3_bucket_server_side_encryption_configuration` in the same file —
asserts **zero findings for rule 4** (S3-NO-ENCRYPTION), guarding the
`companion_type` mechanism against false positives.

And a **score-formula test**: the README's worked example as a fixture
(public + unencrypted S3 bucket, security group with SSH 22 open to
0.0.0.0/0, encrypted EBS volume; no RDS, no IAM anywhere) — asserts the scan
scores exactly **40.5**, hand-computed as `100 × (1 − 22/37)`.

## Repo hygiene
Pinned `requirements.txt` (adds PyYAML, python-multipart, Jinja2; removes
nothing blindly — pins from the working venv), MIT `LICENSE`, `.gitignore`, no
secrets or tokens anywhere. README: architecture, exact score formula, run
commands for Windows **and** Unix, **exact curl examples for every endpoint**,
CloudFormation-out-of-scope note, the rules-are-data policy (edit
`rules.yaml`, zero code changes), and a statement that **no cloud resources
were used by design**. Local git only —
no remotes, no push.

## Delivery — compliance slices over the existing draft (1 slice = 1 turn, verified + committed)
1. YAML rule engine skeleton + provenance (line + evidence) in the parser +
   **one rule (SSH-WORLD) end to end** + its golden fixture test.
2. Remaining six rules in `rules.yaml` + fixtures (incl. the companion
   negative fixture for rule 4) + the rule-extensibility test; **delete** the
   Python 11-rule pack.
3. Per-file + total score + the score-formula test (hand-computed 40.5
   fixture), server-rendered dashboard with inline-SVG trend (**delete** the
   Chart.js/Google-Fonts CDN page), multipart `POST /scans`.
4. README, LICENSE, pinned requirements, polish; **delete** everything the
   spec doesn't call for — `GET /scans` list, `DELETE /scans/{id}`,
   `/api/v1/summary`, JSON-body scan inputs (path + inline), `samples/`
   (superseded by fixtures) — each deletion noted in `prompts.md`.

Post-MVP (time-budgeted): short Marp slide deck on the result, on request.

## Out of scope
CloudFormation, `terraform plan` JSON, `::/0` variants, module resolution,
cross-file references beyond the S3 companion rule, auth/multi-user, waivers,
Postgres, Docker, any cloud usage.
