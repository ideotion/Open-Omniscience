# Action plan — 2026-09-06 repo analysis

**What this is.** A read-only analysis of everything this repository still has open — documentation,
future developments, unfinished projects, unresolved bugs, and everything the ledger marks as "for later" —
sorted into twenty-three prompts, each written to be pasted into an autonomous Opus 5 coding session on its
own. Nothing was coded or fixed while producing it.

**Anchor:** `main` @ `1d421e9`, 2026-09-06. Version `0.3.0`; `v0.2.0` tagged; 0.3 not yet tagged.

## The files

| File | What it holds |
|---|---|
| `_WORKING_MODE.md` | The rules every prompt shares — ledger-first, the staleness guard, the verbatim CI gates, the sandbox's real capabilities, the honesty rules, the closeout rituals. **Part of every prompt.** |
| `INVENTORY.md` | Every open item found, with a verdict, the tree anchor that proves it, where the stale claim lives, and the owning prompt. Plus the operator-gated, ruling-gated, browser-gated and stale-claim lists. |
| `QUESTIONS_FOR_THE_MAINTAINER.md` | 65 decisions, each with its context, its options and a recommended default. ⛔ marks the ones a session may not decide for you. |
| `PROMPT_01` … `PROMPT_23` | The sessions. |

## How the analysis was done, and what that means for trust

Twelve read-only investigation agents covered `FUTURE_DEVELOPMENTS.md`, the design-document tree, the
roadmaps and release gates, the **entire** pull-request history from #1 to #1010, the code and test and CI
markers, and the audit reports. Every claim they returned was then re-derived from the tree by the
orchestrating session before it entered the inventory.

That second pass was not ceremony. **The single largest category of "open work" in this repository turned out
to be documents describing a past state of the tree.** Four session briefs carry a "Status: PENDING
execution" banner written by the session that then executed them within forty-eight hours. The DB-10
create-time seam, the OSM preprocessing bridge, the quarantine action, the stoplists-as-data-files, the
Ollama `num_ctx` auto-tune, the newsletter-links-to-sources path and the qualification-assist button are all
recorded somewhere as open and are all in the tree.

So the verdict vocabulary is deliberate: **BUILT · PARTIAL · UNBUILT · STALE-CLAIM · OPERATOR-GATED ·
RULING-GATED · BROWSER-GATED · UNCHECKED**, and `UNCHECKED` is used honestly where a claim was not re-derived
rather than being quietly upgraded.

## What is actually open

Once the stale claims are removed, the genuinely open work concentrates in eleven places:

1. **The egress allowlist.** Six consecutive sessions have failed a reach-a-named-publisher task through six
   different tool surfaces — the sixth (2026-09-07, P06) re-probed it rather than assuming it:
   `dumps.wikimedia.org` `CONNECT … 403 Forbidden` against a `pypi.org` 200 control. It is not a prompt problem. It blocks ten items across the law, governments and
   keyword-translation prompts, and one allowlist entry unblocks most of them.
2. **About twenty maintainer rulings**, several of which are create-time irreversible (the storage §8 set).
3. **Operator measurements** — the month-occupancy number, `configs/source_qualification.yml`, the graded gold
   sets, the ≥72 h soak, the committed full import.
4. **Fifty-six `async def` handlers** still taking `Depends(get_db)`, fifty of them in one file, with no guard
   preventing the fifty-seventh.
5. **File members inside the signed backup artifact** — the top parked data-safety item, and the reason both
   the wiki-dump and the models-in-backup rulings sit unbuilt.
6. **The Phase-2 promotion frontier** — a source can be judged and a judged source can be adopted, but nothing
   moves a candidate through trial into collection.
7. **The static-embedding recall layer and the BM25F default**, both waiting on ten minutes of gold-set grading.
8. **The Observatory frontend**, which is designed completely and built not at all.
9. **The UI backlog** — roughly 590 inline handlers, the dead temporal-map cluster, the Insights search bar,
   240 unkeyed strings against two zero-slack ratchets, five accessibility findings, and the P2 tier of the
   2026-07-22 report that a shipped-ledger row describes as closed.
10. **Documentation hygiene**, which is worth more than it sounds for the reason above.
11. **Thirty-five items that live only in a pull-request body** — deliberate decisions and known defects that
    stopped being written down anywhere a future session would look.

## The prompts

| # | Prompt | Gated on | Notes |
|---|---|---|---|
| 01 | `release-0-3-close-and-0-4-gate` | A1 is an operator step, A2 | First. Later prompts add rows to the 0.4 board it creates. |
| 02 | `docs-hygiene-and-reality-check` | A4, L8 | Early — the feature prompts are otherwise misled by the claims it removes. |
| 03 | `ledger-restructure` | ⛔ A3 | Must not run concurrently with anything: every other prompt appends to the files it moves. |
| 04 | `sources-qualification-and-promotion` | ⛔ B1, B6, B7, L9, L10 | The largest genuinely-unbuilt backend area. |
| 05 | `keyword-engine-quality` | B2, B3, B4 | Shares a data-safety boundary with 07 — not concurrent. |
| 06 | `keyword-translation-and-sense` | E1, E2, E3, E4 | S1 unblocks the moment the occupancy number lands. |
| 07 | `data-safety-and-backup-completeness` | ⛔ C1, C6, C7 | Full skeptic matrix throughout. Not concurrent with 08 or 09. |
| 08 | `import-performance-and-conclusion` | C2, C3 | Not concurrent with 07 or 09. |
| 09 | `crash-memory-and-write-path` | — | Buildable now. Holds the 56-handler slice. |
| 10 | `throughput-scaling` | the brief's own evidence gates | Its C16 touches the write path — not concurrent with 09. |
| 11 | `ai-layer-and-model-supply` | D5–D10, AI-15 | No GPU here; the GPU path is fixture-testable only. |
| 12 | `bulletin-completion` | D1–D4 | Two of the four are one-line changes. |
| 13 | `law-vertical` | ⛔ F1, L6 | S2–S5 are buildable **without** egress. |
| 14 | `governments-and-statistics` | ⛔ F1, G1, G4, G5 | S2–S4 buildable without egress. |
| 15 | `ui-browser-backlog` | H2, ⛔ H3, H4, L2, L5, L7 | Split across several sessions; the most accumulated debt. |
| 16 | `observatory-and-dataviz` | ⛔ H1 | After 15's S8 and after 17's S1. Cannot ship conservative-and-flagged. |
| 17 | `groups-and-analysis-surfaces` | — | Its S1 is a prerequisite for 16. |
| 18 | `wikipedia-living-source` | G10, storage milestones | Last among the verticals; S1 is P0-scale-gated by a standing ruling. |
| 19 | `agenda-maps-newsletters` | G8, I1, I2 | Four loosely-coupled areas; take them one at a time. |
| 20 | `structural-debt` | J1, J2, J3, L8 | Almost all behaviour-neutral — good for interleaving. |
| 21 | `security-and-network` | I3, I4, G9 | Its CSP slice waits on 15's inline-handler retirement. |
| 22 | `storage-phase-c` | ⛔ C4, C5 | First deliverable may honestly be an updated design, not code. |
| 23 | `v1-pathway-and-verticals` | ⛔ G1, G2, G4 | Last. Its first deliverable is eight rulings, not code. |

## Suggested order

**Now, in parallel where the fences allow:** 01 (the release), 02 (the hygiene that stops later sessions
being misled), 09 (the handler conversions — the largest measured backend defect class), 20 (behaviour-neutral,
interleaves with anything).

**Next, once the rulings arrive:** 03 (alone), 04, 05, 07, 11, 15.

**Then:** 06, 08, 10, 12, 13, 14, 17, 21.

**Later, and deliberately so:** 16, 18, 19, 22, 23.

## Concurrency fences

- 03 runs alone.
- 07, 08 and 09 all touch the merge and the write path — one at a time.
- 05's quarantine-filter slice and 07 share a data-safety boundary.
- 16 needs 17's S1 and 15's S8.
- 21's CSP slice needs 15's S2.

## What this plan is not

It is not a commitment to build all of it, and several prompts say plainly that their honest outcome may be
to park work rather than start it. It records **direction and evidence**, so that a future session spends its
time building rather than re-deriving what is already known — and so that a decision the maintainer already
made is not asked again.
