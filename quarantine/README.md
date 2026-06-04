# Quarantine

Code in this directory was **removed from the import/runtime path** because it
*pretended to work*. It is kept (not deleted) so the honest parts can be salvaged
when each feature is rebuilt for real — but **nothing here is wired into the app**,
and none of it should be presented to a user as functional.

The guiding rule for this project (see `docs/PRODUCT_SYNTHESIS.md` §3.5/§3.7):
> A confidence score must come from a real method, or not exist.
> The system must never silently degrade into invalid output.

## `pillar3_analysis/` — fabricated media-forensics detectors

| File | Why it was quarantined |
|------|------------------------|
| `deepfake_detector.py` | Loads ONNX `InferenceSession`s but **never calls `.run()`**. The actual "score" is `cv2.Laplacian(...).var()` blur + `cv2.Canny` edge density — a generic blur heuristic dressed up as deepfake detection. The README's ">95% accuracy" is aspirational. |
| `propaganda.py` | Several techniques are unreachable; emitted `confidence` is a **hardcoded constant** (`0.8` / `0.9`), not a measurement. |
| `cognitive_bias.py` | Most biases unreachable; `confidence` **hardcoded to `0.75`**. |
| `bot_detector.py` | "Network analysis" reduces to `len(followers) + len(following) > 1000`. |
| `test_deepfake_detector.py` | Tested the fabricated detector; moved with it. |

### What to do instead (future work)
- **Metadata/EXIF validation — DONE (v0.4).** Revived as a clean, Pillow-based,
  honest implementation in `src/verification/metadata.py` + `POST /api/verify/
  image-metadata`, scoped explicitly as "metadata checks" (not deepfake detection).
  The old cv2-based `pillar3/.../metadata_validator.py` is superseded.
- If media forensics is ever rebuilt, use a **real, published, evaluated FOSS model**,
  call its inference, and report measured accuracy — or label outputs clearly as an
  "experimental heuristic, not evidence."

## `dead_src/` — fabricated / over-engineered modules removed in v0.4 (Phase 6.1)

These modules were **imported by nothing** (not the app, not the tests) — pure
dead weight that obscured the real code. Removed from `src/` (history preserved):

| Module | Why |
|--------|-----|
| `scraper_distributed.py` (1831) | fabricated "distributed" scraper |
| `llm_optimizer.py` (1612) | fabricated LLM "optimizer" |
| `database_query_optimizer.py` (1561) | unused; carried a **latent f-string SQL injection** |
| `api_performance.py` (1404) | unused performance endpoints |
| `utils_performance.py` (760) | unused |
| `database_optimization.py` (697) | unused |
| `compliance_ethical_scraper.py` (641) | superseded by `src/ingest` (the real, fail-closed fetcher) |
| `ingestor_importer.py` (286) | superseded CSV importer |

~8,300 lines removed; the suite stayed green. `database/async_db.py` (future
Postgres async session) and `src/database/migrations/*` (Alembic) were
deliberately **kept**.

## `legacy_database_search.py` — superseded dead code

The former `src/database/search.py` (1310 lines) advertised SQLite FTS5 / Postgres
full-text search but was **never imported** by the application; the real, tested
search lives in `src/database/fts.py`. Parked here to avoid confusion. Mine it for
any genuinely useful Postgres-FTS ideas if/when a Postgres backend is built.

---

Restoring a file means: rebuild its logic so the output reflects a real method,
add honest tests, then move it back and wire it in deliberately.
