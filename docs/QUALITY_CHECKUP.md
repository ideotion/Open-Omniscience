# Quality Check-up — post-merge (v0.4)

Honest assessment of the repository immediately after Phases 0–5 were merged into
`0.04`. Companion to the upgraded plan in [`ACTION_PLAN.md`](ACTION_PLAN.md) §"Phase 6".

> ## Update after Phase 6 execution
> Status against the issues below (all green, branch `claude/kind-lovelace-ulpTc`):
> - **6.1 Dead-code purge ✅** — ~26.6k dead LOC → ~7.4k; **live ratio 36% → 68%.**
>   Removed the hallucinated-LLM catalog and the latent SQL-injection module.
> - **6.2 Source seeding ✅** — the full `configs/sources.yml` catalog (~1,780
>   unique) auto-seeds on install/first-run.
> - **6.3 Alembic migrations ✅** — baseline + drift guard (`alembic check`) in CI;
>   init_db stamps fresh DBs.
> - **6.4 Router/enricher hardening ◑** — SourceManager already well-covered; added
>   keyword-extractor + link-extractor tests; fixed two real bugs (`list_sources`
>   DI; link internal/external classification).
> - **6.6 Lint ◑** — ~1,990 → ~1,060 via safe autofix (no import removal).
> - **6.7 Commodity ◑** — CSV bulk price import added (real web scraper deferred:
>   needs a live source).
> - **Still open (low marginal value / needs the operator's machine):** Pillar-2
>   honesty gate (6.5 — moot now that fabricated numbers are quarantined), the
>   remaining unsafe/manual lint + flipping CI lint to blocking, link-analyzer
>   deeper quality, a live web scraper.
> - Tests: 350 passing / 0 failing.

## Scorecard

| Dimension | State | Notes |
|-----------|-------|-------|
| **Core functionality** | 🟢 Working | ingest → store → search → export → summarize → correlate → signed evidence, live-verified end to end. |
| **Tests** | 🟢 361 pass / 0 fail | New code well covered; one full-workflow integration test; route-smoke guard (no GET 5xx). |
| **Install / packaging** | 🟢 Clean | one `pyproject.toml`, Python 3.13, Qubes-aware installer, working CI. |
| **Honesty** | 🟡 Improved, not done | Fabricated detectors quarantined; but large fabricated/over-engineered **dead** modules remain in the tree. |
| **Dead code** | 🔴 Major | **~26k of ~41k lines in `src/` are not loaded by the app (~64%).** The live, working core is ~15k lines. |
| **Lint** | 🔴 ~1,990 findings | Almost all in legacy/dead modules; CI runs ruff as advisory so it never blocks. |
| **Schema evolution** | 🟡 Additive-only | New tables (ArticleAnalysis, CommodityPrice) are created by `create_all`; there is no Alembic migration path for *altering* existing tables. |
| **Out-of-the-box utility** | 🟡 Empty corpus | The app works but ships with **no sources**; a user must add feeds manually before anything happens. |
| **Verticals** | 🟡 Thin | Commodity prices are import-only (no real scraper); financial pillar not started. |
| **Latent risks (unused)** | 🟡 Contained | `database/query_optimizer.py` has f-string SQL injection but is **unreachable** (dead). Should be removed, not left as a footgun. |

## Biggest issue: dead/fabricated bulk

44 of 92 `src/` modules are never loaded by the running app. The largest are
fabricated or grossly over-engineered and add no value while obscuring the real
code and inflating the lint/maintenance burden:

| LOC | Module | Verdict |
|----:|--------|---------|
| 1831 | `src/scraper/distributed.py` | fabricated "distributed" scraper — remove |
| 1612 | `src/llm/optimizer.py` | fabricated LLM "optimizer" — remove |
| 1561 | `src/database/query_optimizer.py` | unused; **latent SQL injection** — remove |
| 1404 | `src/api/performance.py` | unused perf endpoints — remove |
| 923 | `src/database/async_db.py` | **keep** — correct async session for a future Postgres backend |
| 760 | `src/utils/performance.py` | unused — remove |
| 697 | `src/database/optimization.py` | unused — remove |
| 651 | `src/main_pipeline.py` | **keep for now** — referenced by `test_pipeline.py` |
| 641 | `src/compliance/ethical_scraper.py` | superseded by `src/ingest` — remove (kept in history) |

(The `src/database/migrations/*` files are run by Alembic, not imported — keep.)

## What this means
The app a user runs is sound. The *repository* is not yet trustworthy to read:
two thirds of it is code that doesn't run. Making the repo "functional" in the
fuller sense means (a) purging the dead/fabricated bulk so what remains is real,
(b) giving the app immediate utility (seeded sources), (c) a real migration path,
and (d) hardening the live legacy routers. These are laid out as **Phase 6** in
the action plan.
