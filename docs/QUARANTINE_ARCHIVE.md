# Quarantine archive

The `quarantine/` directory — the original six-pillar trees plus a set of
fabricated/dead modules, **~79.5k lines, never imported by the running app** —
was **removed from the working tree on 2026-06-14** and preserved on the
**`quarantine-archive`** branch. Nothing here was ever wired into the app; it was
kept only as a salvage reference while each feature was rebuilt honestly in `src/`.
This document is the permanent record of *what* was there and *why*, so the
breadcrumbs in the live code still land somewhere.

> The guiding rule (PRODUCT_SYNTHESIS §3.5/§3.7):
> *A confidence score must come from a real method, or not exist. The system must
> never silently degrade into invalid output.* Everything below violated that and
> was removed from the import/runtime path.

## How to retrieve any archived file

The content is preserved verbatim on the `quarantine-archive` branch (a pointer to
the last `0.09` commit that still contained the folder — no history was rewritten,
so every commit SHA is intact):

```sh
# list what was there
git ls-tree -r --name-only quarantine-archive -- quarantine/

# bring one file/dir back into your working tree
git checkout quarantine-archive -- quarantine/pillars/pillar2/...

# or read it without checking it out
git show quarantine-archive:quarantine/README.md
```

It also remains in normal git history at any commit up to and including
`bf7ee7f` on `0.09`.

## What was archived, and why

### `pillar3_analysis/` — fabricated media-forensics detectors
| File | Why it was quarantined |
|------|------------------------|
| `deepfake_detector.py` | Loaded ONNX sessions but never called `.run()`; the real "score" was a `cv2.Laplacian` blur heuristic dressed up as deepfake detection. The ">95% accuracy" was aspirational. |
| `propaganda.py` | Several techniques unreachable; emitted `confidence` was a hardcoded constant (`0.8`/`0.9`). |
| `cognitive_bias.py` | Most biases unreachable; `confidence` hardcoded to `0.75`. |
| `bot_detector.py` | "Network analysis" reduced to `len(followers)+len(following) > 1000`. |

### `dead_src/` — fabricated / over-engineered modules (v0.4 Phase 6.1)
Imported by nothing. `scraper_distributed.py`, `llm_optimizer.py`,
`database_query_optimizer.py` (carried a latent f-string SQL injection),
`api_performance.py`, `utils_performance.py`, `database_optimization.py`,
`compliance_ethical_scraper.py`, `ingestor_importer.py` (~8,300 lines).

### v0.0.7 audit (MAINT-01) — six dead packages
`ingestor/`, `scraper/`, `custom_types/`, `compliance/`, `audit/`, `reports/`
(~4,360 lines) — imported by no live code; superseded by `src/ingest`,
`src/custody`, `src/reporting`, `configs/legal.yml`.

### `pillars/` — the original six-pillar trees (~50k lines)
The running app never imported them. Each pillar's genuine intent now lives as a
small, honest, tested module in `src/` (see `docs/PILLAR_INTENT_MAP.md`). Pillar 2's
real statistical code was salvaged into `src/analysis/`.

### `link_analyzer/`, `legacy_database_search.py`, `link_analysis_router.py`
The fabricated credibility scorer (returned ~100 for every input), the unused
SQLite/Postgres FTS search module (superseded by `src/database/fts.py`), and the
old link-analysis router. The honest replacements are `src/services/link_analyzer/`
(extraction only) and `src/api/link_analysis.py` (counts only, nothing scored).

## What was salvaged (the honest replacements now in `src/`)
- **Metadata/EXIF validation** → `src/verification/metadata.py` + `POST /api/verify/image-metadata`
  (scoped as "metadata checks", not deepfake detection).
- **Pillar 2 statistics** → `src/analysis/`.
- **Ethical fetching** → `src/ingest/` (the real, fail-closed `EthicalFetcher`).
- **Chain of custody / reports** → `src/custody/`, `src/reporting/`.
- **Full-text search** → `src/database/fts.py`.

---

*Removed from the working tree 2026-06-14; preserved on `quarantine-archive`.
Restoring a file means: rebuild its logic so the output reflects a real method,
add honest tests, then move it back and wire it in deliberately.*
