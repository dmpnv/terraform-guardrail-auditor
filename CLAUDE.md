# Standing session rules — Guardrail Auditor (Lead Architect mode)

These rules survive context compaction. **After any compaction, re-read the
Decisions section at the top of `prompts.md` before continuing.**

- **T0 (absolute, fixed):** `2026-08-07T14:46:28+02:00` — the moment of the
  user's first message, reconstructed from the `date` call made as the first
  action of the first response. Every response ends with `Elapsed: H:MM`
  computed as **system clock now minus this stored T0**. Read the clock with
  `date` every turn; never estimate elapsed time.
- **No manual edits by the user.** Claude authors every change and every fix.
- **`prompts.md` is updated after every turn:** the user's prompt verbatim,
  chronological, never reordered. Every entry carries three annotation lines:
  intent / what changed / how it was verified. The Decisions section at the
  top is kept current.
- **Commit after each verified slice.** When the MVP milestone is reached, say
  so explicitly in the response and record it in `prompts.md`.
- **The repository stays local until the user publishes it themselves: never
  create remotes, never push.**
- **Spec-first:** `SPEC.md` governs scope and requires the user's approval
  before any implementation code. The Turn-1 output is an unreviewed draft
  under audit; anything in it the spec does not call for gets deleted, and the
  deletion is noted in `prompts.md`.
