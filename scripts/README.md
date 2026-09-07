# Scripts

Maintainer and operator tools shipped with the repo. All run from the repository
root; none are needed for normal app use. Network-touching scripts say so.

| Script | What it does | Network |
|---|---|---|
| `bootstrap.sh` | One-shot dev setup (venv + editable install). | PyPI |
| `launch.sh` | Start the app and open the Console in a browser. | loopback only |
| `seed_sources.py` | Seed the curated source catalogs into the DB (idempotent). | no |
| `catalog_coverage_report.py` | The 0.0.9 catalog-balance acceptance metric: global + per-region coverage vs `configs/catalog_targets.yml`, named gaps, concentration guards. | no |
| `build_world_news_catalog.py` | Generate `configs/world_news_sources.yml` from Wikidata per country (see the runbook in `docs/ROADMAP.md`). | Wikidata |
| `verify_worldbank_indicators.py` | Check every curated World Bank indicator code in `src/stats/indicators.py` against the live API — reports `OK` / `EMPTY` (valid code, this area does not report it) / `DEAD-INVALID` (the API rejected the code) and refuses the `fetched` tier when the URL served differs from the one requested. Needs `api.worldbank.org` reachable — see the STATUS block in `docs/design/INTERNET_SESSION_PROMPT_2026-08-07_GOVERNMENTS_DATA.md`. | World Bank API |
| `build_city_gazetteer.py` | Build the bundled city gazetteer. | Wikidata |
| `build_world_outline.py` | Rebuild the bundled Natural-Earth coastline outline. | download |
| `i18n_report.py` | Locale completeness report; `--audit-chrome` diffs every UI text node against `en.json` (the long-tail number). | no |
| `translate_docs.py` | Draft `docs/i18n/<lang>/` translations with the LOCAL Ollama (provenance banner, resumable). | loopback (Ollama) |
| `benchmark_audit.py` | The performance gates recorded during the v0.0.7 audit. | no |
| `verify_custody.py` / `verify_evidence.py` | Offline verification of the signed custody log / evidence bundles. | no |
| `add_gpl3_headers.py` / `update_license.py` | License-header maintenance. | no |
| `make_icon_png.py` | Render the eye icon PNG from the SVG. | no |
| `analysis/` | Ad-hoc analysis helpers used during audits. | no |
| `init-postgres.sql` | Schema scaffolding for a PostgreSQL path that **does not exist** — not supported, not tested, not run by anything here (J3, 2026-09-07; the file's own banner and `docs/ARCHITECTURE.md` say why). | — |

> `setup_llm.py` was **removed on 2026-09-07** (PARKED PRH-04). It had not run for a
> long time and could not: its first two imports, `src.llm.config` and
> `src.llm.model_manager`, name modules that no longer exist, so the script died at
> import with `ModuleNotFoundError` before parsing a single argument — while this table
> advertised it as the way to provision the local model. Everything it offered now lives
> in the app: Settings → Local models pulls and manages models, and `src/llm/installer.py`
> installs the Ollama binary against the publisher's own attested digest. Repairing it
> would have meant a second, untested provisioning path beside the one the app actually
> uses, which is how two surfaces come to disagree about one thing.

> This file used to document a `debug_install.sh` helper (with a `curl | bash`
> line pointing at the long-retired `0.03` branch) that never shipped — removed
> in the 0.0.9 audit. For install problems, use the in-app debug bundle
> (Settings → Data & backup → Debug bundle) instead.
