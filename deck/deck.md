---
marp: true
theme: default
paginate: false
size: 16:9
html: true
style: |
  section {
    font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
    background: linear-gradient(160deg, #0a1a2f 0%, #122843 100%);
    color: #eef2f7; text-align: left; justify-content: flex-start; padding-top: 54px;
  }
  section h2 {
    color: #ffb703; font-size: 22px; letter-spacing: 3px; text-transform: uppercase;
    border: none; margin-bottom: 10px; font-weight: 700;
  }
  section h1 { color: #ffffff; font-size: 42px; line-height: 1.2; margin: 0 0 18px 0; }
  section h1 strong, section h2 strong { color: #ffb703; }
  section p  { color: #b7c6d8; font-size: 24px; line-height: 1.45; margin: 8px 0; }
  section strong { color: #ffb703; }
  section em { color: #7f97ad; font-style: normal; font-size: 20px; }
  section ul, section ol { color: #cdd9e6; font-size: 23px; line-height: 1.5; margin: 6px 0; }
  section li { margin: 4px 0; }
  section table { border-collapse: collapse; margin: 14px 0 0 0; font-size: 20px; width: 100%; }
  section table thead td, section table th {
    color: #ffb703 !important; background: transparent !important; border: none !important;
    border-bottom: 1px solid #2a4a6e !important; font-weight: 700; text-align: left; padding: 6px 14px 6px 0;
  }
  section table tbody td {
    color: #cdd9e6 !important; background: transparent !important; border: none !important;
    border-bottom: 1px solid #1b3a57 !important; padding: 7px 14px 7px 0; vertical-align: top;
  }
  section table tbody tr { background: transparent !important; }
  /* added (disclosed): marp's default theme paints thead tr white; this one
     line completes the theme's own transparent-table intent — no rule above
     was altered */
  section table thead tr { background: transparent !important; }
  section .takeaway { color: #ffb703; font-size: 22px; margin-top: 16px; font-weight: 600; }
  section .loop {
    position: absolute; top: 58px; right: 54px;
    font-size: 14px; letter-spacing: 2px; color: #46617f; font-weight: 600;
  }
  section .loop strong { color: #ffb703; }
  section img { display: block; margin: 10px auto; background: #f4f7fa; padding: 8px;
    border-radius: 10px; box-shadow: 0 8px 28px rgba(0,0,0,0.45); max-height: 420px; }
---

## Terraform · Enterprise Security Guardrails

# **Guardrail Auditor**

An API-first security auditor for Terraform: seven guardrails as data, findings
with file / line / evidence, a severity-weighted risk score — and one
server-rendered dashboard with zero client JavaScript.

*Built 2026-08-07, in one session. Every line written by an AI; every step gated by a human.*

---

## The exercise

# Vibe coding, **with a gate**

- The human architects and gates: spec, approvals, written amendments, audits — and **never edits a line**.
- The AI writes everything end to end: code, tests, fixtures, docs, every commit.
- Nothing lands unverified: pytest on every turn, plus live checks against the running app in a real browser.

<p class="takeaway">The discipline is the product; the scanner is the proof.</p>

---

## What was built

# A working auditor, **not a mock**

- **7 guardrails** for Terraform: public S3 (ACL or policy), SSH & RDP world-open (IPv4 **and** IPv6), S3 & EBS encryption, RDS public, IAM `Action "*"`.
- **API-first**: FastAPI + SQLite — 5 endpoints, multipart upload, OpenAPI docs, clean operationIds.
- **Server-rendered dashboard**: annotated source view, severity filter, per-file scores, score trend, System/Dark/Light theming.
- **35 tests**: golden fixtures asserting exact *(rule, resource, line)* triples, a hand-computed score fixture, end-to-end form flows.

---

## How it works

# One page, plain HTTP, **zero client JS**

- One server-rendered page — zero client JS, zero CDN: runs offline from a fresh clone.
- Upload via form or API — one shared pipeline, same limits (multipart `POST /api/v1/scans`).
- Annotated source: every finding lands on its own line — `file:line`, evidence, fix beneath.
- Posture at a glance: severity tiles plus a score trend across persisted scans (SQLite).
- Deep-linkable: filter = query param, code line = fragment anchor; theme rides a cookie (System / Dark / Light).

---

## Rules are data

# Closing a gap with **zero engine changes**

- `rules.yaml` with a closed operator vocabulary — `exists`, `absent`, `eq`, `contains`, `open_port`. No eval, ever.
- The extensibility test appends a brand-new YAML rule to a copied pack — it fires with **zero code changes**.
- Case in point: the IPv6 world-open gap was closed by adding two `open_port {port, cidr: "::/0"}` clauses — a pure YAML edit.
- Verified live: the **running** server picked the clauses up on the very next scan. No restart, no deploy.

<p class="takeaway">The spec promised rules-as-data. The repo proves it twice.</p>

---

## Process

# Spec first — even after the AI **ran ahead**

- Turn 1 generated a full application instead of stopping at "acknowledge". It was frozen and committed honestly: *"initial draft from the opening prompt, pre-spec"*.
- A one-page SPEC followed — user-approved (v2), then amended **in writing before** every change.
- The draft was audited into compliance through four verified, committed slices; everything off-spec was deleted, and every deletion logged.
- `prompts.md` records every prompt **verbatim**, each with three lines: intent / what changed / how it was verified.

---

## Honest clock

# T0 → MVP in **2:33**, against a 4–6h goal

- T0 fixed at the first message: `2026-08-07T14:46:28+02:00`. Every turn ends with Elapsed read from the **system clock** — never estimated.
- MVP milestone: commit `f692820`, elapsed **2:33** (recorded in `prompts.md`).
- Even the milestone-timestamp correction is its own commit (`d73a66a`) — the history admits its mistakes.
- The clock kept running past MVP: theming, annotated source view, IPv6 clauses — all logged the same way.

---

## Numbers

# Every figure below is **checkable in the repo**

| Metric | Value | Where to check |
| --- | --- | --- |
| Tests passing | 35 | `python -m pytest -q` |
| Guardrails / operators | 7 / 5 | `rules.yaml` |
| API endpoints | 5 | `/openapi.json`, README curl section |
| Golden fixtures | 11 | `tests/fixtures/*.tf` |
| Commits before this deck | 25 | `git rev-list --count HEAD~1` |
| Prompts logged verbatim | 21 turns | `prompts.md` |
| Themes | 2 + System | `/theme/{system,dark,light}` |
| Manual code edits by the human | 0 | `CLAUDE.md` rule, `prompts.md` log |
| Remotes / pushes | 0 | `git remote -v` |

---

## Limits & next

# Deterministic core, **honest edges**

- Known limitations (README): single-scan semantics — no module resolution (the S3 encryption companion is the one cross-resource link); policy matching is textual — `jsonencode()` isn't parsed; the interactive `/docs` needs network (the curl section is the offline reference).
- Roadmap: a thin CLI over the API for CI gates · more port rules **as data** · CloudFormation.
- Where GenAI slots in next: LLM-drafted remediation *explanations* behind a seam — opt-in, and **outside the verdict path**.

<p class="takeaway">The scanner itself stays deterministic by design.</p>

---

## Closing

# The repo **is** the talk

| File | What it proves |
| --- | --- |
| `README.md` | how to run (Windows + Unix), the score formula, curl for every endpoint, known limitations |
| `SPEC.md` | the approved contract, plus every amendment in writing |
| `prompts.md` | every prompt verbatim — intent / change / verification, T0 to now |
| `rules.yaml` | the 7 guardrails as editable data |
| `tests/` | 35 tests: golden fixtures, the 40.5 formula, the extensibility proof |

*Local git only — no remotes, nothing ever pushed. Clone it, run pytest, open the dashboard.*
