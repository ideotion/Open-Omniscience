# Governance & acceptable use

Open Omniscience is a tool for **holding power accountable** by helping people see the
*structure* of public information honestly. Because that capability is powerful, this
document states plainly what the tool is for, the lines it will not cross, and how it
intends to stay trustworthy as it grows. This is part of the project's ethics, not an
afterthought.

## What it is for

- **Investigative journalism and public-interest research** over *published* media,
  institutions, markets and law — surfacing measurable structure (ownership concentration,
  coordination/echo, novelty, framing, change-over-time) for a human to judge.
- **Source protection and reproducibility** — local-first, offline-capable, with
  tamper-evident provenance so findings can be defended.

## Dual-use red lines (absent by construction, not configurable)

The same techniques that expose a coordinated influence operation could, in the wrong
hands, be aimed at ordinary people. The line that keeps this an instrument of
*accountability* and not a tool of *surveillance* is precise, and it is held in the
**architecture**, not in a setting a user could flip:

1. **No tracking of private individuals.** The tool analyses *published sources*
   (outlets, institutions, public documents). It does **not** profile private persons,
   and `src/compliance/gdpr.py` is the guardrail. Prominence measures *coverage of public
   figures already written about* — attention, never importance or merit.
2. **No biometric identification.** No face, voice, or gait recognition. Ever.
3. **No private-channel ingestion.** No DMs, private feeds, intercepted messages, or
   non-public data. The corpus is built from sources the user can lawfully and ethically
   access.
4. **No automated verdicts.** No truth/credibility/"trust" score, no "biased"/"fake"
   label. The tool surfaces *measurements with method + caveat*; the human concludes.
   (Enforced in code: `assert_no_score_fields`.)
5. **No central server, accounts, or telemetry.** Nothing leaves the user's machine
   except the fetches they direct. There is no honeypot of user data to seize or subpoena.
6. **No silent filtering or down-weighting of sources.** Coverage facts are *surfaced*;
   any de-amplification is user-applied, flagged, and reversible — surface, never enforce.

These are enforced as far as code can: a CI test
(`tests/test_repo_invariants.py::test_red_lines_not_crossed`) fails the build if forbidden
capabilities (biometric recognition, individual tracking) appear in the codebase. A test is
a tripwire, not a proof — the real guarantee is culture and review.

## Legal & ethical posture

- A **research mirror**, not the authoritative source, and **not legal advice**; every
  record links back to its origin.
- **Ethical access** by default: robots.txt fail-closed, per-host rate limits, an
  identifying User-Agent, attribution and provenance stored. (A user may enable *Protected*
  fetch — proxy + generic UA — to protect a source or themselves when investigating a
  powerful target; this is the journalistic duty of source protection, taken deliberately
  and documented, never the silent default.)
- **Respect licences and copyright**; store provenance and the minimum needed; honour
  jurisdictional data-protection obligations.

## Independence & funding

The tool is deliberately **cheap to run** (local, no infrastructure) so it can stay
**independent**. If the project ever takes funding, it will avoid capture by any single
funder or agenda, govern decisions transparently, and never bend the definition of
"disinformation" to suit a sponsor. The most political choice this project makes is to stay
small, local, and un-capturable.

## Misuse resistance

No tool can prevent all misuse, and we will not pretend otherwise. Our resistance is
structural: the red lines above, the local-first design (no central data to abuse at
scale), the refusal to render verdicts, and openness (anyone can inspect, fork, and audit).
If you believe the project is being steered across a red line, open an issue — that
contestability is the point.

## How decisions are made (intent)

Today this is an early, single-maintainer project. Before a public `0.1` alpha we intend:
an **external security & ethics review**, a move toward **multi-maintainer governance**
with transparent decision-making, and a **contribution covenant** that binds contributors
to the red lines. Until then, this document is the commitment of record.
