# Prompt 12 — Finish the Bulletin

> **Scope:** `src/bulletin/`.
> **Gated on:** D1 (the Layer-A hardware gate — one constant, one read), D2, D3, D4.
> **Sequencing:** independent.

## 0. Working mode

Read `_WORKING_MODE.md`, then `docs/design/BULLETIN_DESIGN_2026-07-31.md` — the record of record, including
its §20 open questions and §21 build order.

Steps 1–9 of that build order shipped, plus the translation layer, the annexes, the growth-sentinel fixes
and the language diagnostic. What is left is small, and two of the four remaining questions are one-line
changes.

## 1. Slices

### S1 — D1: `LAYER_A_REQUIRES_CAPABLE_HARDWARE`

One constant in `src/bulletin/gate.py`, with exactly one read, pinned by a test that counts the reads. Layer A
is pure SQL and would run anywhere, so shipping `True` denies a GPU-less operator even the **deterministic**
document — which was implemented as instructed and flagged as reversible in one condition at the time.
Answering D1 is a one-line change either way; the work is making the disclosure say the right thing in both
states.

### S2 — §14: Layer-B narration as a `BackgroundJob` with a persisted cursor

Narration currently runs **inline inside the generate request**. That is fine for a bounded story cap and
wrong for a long run: a request that narrates dozens of stories against a local model is a multi-minute
synchronous handler, which is the freeze family this codebase has already paid for three times. There is no
`BackgroundJob` under `src/bulletin/` at all.

Persisted cursor, visible in the task manager, resumable, and honest about outages rather than aborting to
`done`.

### S3 — §18: the export-privacy enumeration

Owed **before a first evidence archive leaves a machine**. The archive is plaintext out of an encrypted store
and is owner-only by design; the enumeration is the list of what a reader of that ZIP can see, stated where
the operator clicks. The full-text default in the annex ZIP additionally raises a question about each
publisher's terms, which is the maintainer's to answer — record it, do not decide it.

### S4 — The honesty problem the design already names

Producers take no period, so the cards section's figures are **as observed when the edition was generated**,
not as of the period the edition covers (`matches_period` is `False`). The document says so today, which is
the honest minimum. The fix is to give the card producers the explicit period windows that
`top_terms`/`trending` already accept — the seam exists and no caller passes `end` yet.

### S5 — The catalogs and the remaining chrome

The eleven non-English catalogs are AI-drafted and want native review (operator). The guard that pins every
figure's `method` and `caveat` against all twelve locale files is what keeps this from regressing; extend it
to anything S4 adds.

### S6 — D2, D3, D4

The introduction section, mail sending (recommended default: **never** — the app has no outbound mail path
and adding one is a new egress surface for a document the user can already export), and the section list plus
review-screen UX. The review screen shipped as one reading of the last question, not as a ruled design.

## 2. Scope fence

Narration stays off by default below the gate. No LLM output enters the trusted index. Every figure keeps its
`n`, its method and its caveat. The grounding check's stated limit — it cannot catch a false claim built from
real figures and names — stays stated.
