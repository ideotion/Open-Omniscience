# Shared source annotations — signed, portable, federated by trust

> **Status:** `0.06` Phase D — shipped and tested. The scaling answer to the source
> profile (FUTURE_DEVELOPMENTS §6). Pairs with [`INTEGRITY.md`](INTEGRITY.md).

The source profile lets *you* weight which dimensions matter. But **nobody can neutrally
assess thousands of sources alone** — so the weighting must be **collective**. The
honest, local-first, non-centralised way to do that is **signed, shareable annotation
bundles**.

- You publish your source annotations — coordination tags, ownership/transparency
  facts, leaning tags, corrections, notes — as a **custody-signed, verifiable, portable
  bundle** (reusing the same hybrid Ed25519 + ML-DSA signer as the chain of custody —
  *mutualisation*, not a second crypto stack).
- Other users **import** the bundles they choose to trust — an opt-in **web of trust**,
  **never** a central authority.
- Aggregation is **transparent**: you always see *who asserted what*, and **dissent is
  shown, not averaged** into a hidden number.

No server, no accounts, no global score — **federation by signed exchange.**

## What an annotation is (and is not)

An annotation is a **descriptive, contestable fact or tag** about a source. Kinds:
`ownership`, `leaning`, `coordination-tag`, `transparency-fact`, `correction`, `note`.
It is **never** a composite trust/quality score — that is forbidden, by design and in
code (an invalid kind like `trust-score` is rejected).

## Trust model — what a signature does and doesn't prove

Each bundle embeds the author's **public identity** and a signature over the canonical
manifest. Verification **pins** the embedded key, so a tamper-and-re-sign attack cannot
*impersonate* the original author — it merely produces a **different** author. A
verified bundle is therefore always truthfully attributed to whatever key signed it.
You then decide *which keys to trust*; only trusted authors' annotations are aggregated.

This is **web-of-trust, not proof of correctness**: trusting an author means "I want to
see their assertions," not "their assertions are true." Dissent between trusted authors
is surfaced for you to judge, never resolved for you.

## Using it (the Source integrity tab)

1. **Author** annotations (target + kind + value) under *Shared annotations*.
2. **Export signed bundle** → a JSON file you can publish or share.
3. **Import bundle…** → the app **verifies the signature** before storing it (an invalid
   bundle is refused, loudly), then lists the author under *Trusted authors* with a
   trust toggle.
4. **Who said what?** → aggregate every assertion about a source from you + trusted
   authors, with attributions and dissent shown.

Untrusting an author excludes their annotations; removing one deletes them cleanly.

## API

| Method & path | Purpose |
|---|---|
| `GET /api/annotations/mine` · `POST` · `DELETE /mine/{i}` | your authored annotations |
| `GET /api/annotations/export` | a signed, portable bundle of your annotations |
| `POST /api/annotations/import` | verify + store an imported bundle (refused if invalid) |
| `GET /api/annotations/authors` · `PUT /authors/trust` · `DELETE /authors/{id}` | the web of trust |
| `GET /api/annotations/for?target=` | transparent aggregation — who asserted what |

## Honesty constraints

- **No averaging, no consensus number, no score.** Aggregation returns attributed
  claims and names *dissent*; it never collapses disagreement into a figure.
- **Local-first.** Everything is a file under your data dir; nothing is transmitted and
  there is no server or account.
- **Contestable by construction.** Every annotation is a tag/fact you and others can
  disagree about — visibly.
