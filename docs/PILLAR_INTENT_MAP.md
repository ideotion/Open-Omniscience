# Pillar Intent Map — where each pillar's purpose now lives

The original design organised the platform into six "pillars". Those pillar trees
were ~50k lines that the running app never imported — mostly design-only or
fabricated. **Their *intent* has been preserved**: each pillar's genuine purpose
is now a small, honest, tested module inside `src/` (or is explicitly deferred).
The original pillar trees are kept under `quarantine/pillars/` for reference and
history; nothing is deleted.

| Pillar (intent) | Where the intent lives now | Status |
|---|---|---|
| **1 — Data ingestion** (ethical scrape → unified store) | `src/ingest/` (fetcher, extract, pipeline, email) + `src/database/` | ✅ Real, tested |
| **2 — Scientific rigor** (honest statistics, uncertainty) | `src/analysis/` (`statistical_tests`, `confidence_intervals`) + `POST /api/analysis/*` | ✅ **Salvaged the genuine scipy/statsmodels code** + its 60 tests |
| **3 — Deception defense** (verify media) | `src/verification/metadata.py` (honest EXIF/metadata) + `POST /api/verify/image-metadata` | ✅ Honest scope. Deepfake/propaganda/bias detectors were fabricated → `quarantine/pillar3_analysis/` |
| **4 — Monitoring + legal admissibility** | `src/monitoring/` (real uptime + anomalies) and `src/reporting/` + `src/crypto/` (Merkle + Ed25519 signed evidence) | ✅ Real, tested |
| **5 — Financial intelligence** | *Deferred.* The pattern is proven by Pillar 6's reimplementation; a financial vertical can reuse `src/commodity` + `src/analysis`. | ⏸ Design-only originally (0%); not yet built |
| **6 — Rare-earth / commodity** | `src/commodity/` (prices, correct unit conversion, **real** scipy correlation, CSV import) + `POST /api/commodities/*` | ✅ Real, tested |

## What was salvaged in this step (Pillar 2)
- `src/analysis/statistical_tests.py` — t-tests, ANOVA, chi-square, Pearson/Spearman,
  Mann-Whitney, Wilcoxon, regression, Tukey HSD (scipy/statsmodels). Every result
  carries statistic, p-value, dof, effect size, sample size.
- `src/analysis/confidence_intervals.py` — means and proportions (t/normal/Wilson/
  Clopper-Pearson/Agresti-Coull).
- Exposed at `POST /api/analysis/{t-test,correlation,anova,mann-whitney,confidence-interval}`
  so a journalist can check whether a pattern in their data is actually significant.
- The genuine Pillar-2 test suites moved with the code (`tests/test_statistical_tests.py`,
  `tests/test_confidence_intervals.py`).

## What was NOT salvaged (and why)
- Pillar 2 `peer_review` / `consensus` / `reproducibility` — speculative or shallow
  (e.g. reproducibility was a boolean-average rubric). Parked; revive with real
  methods if needed.
- Pillar 3 forensic detectors, Pillar 4 simulated monitoring/threat-intel, Pillar
  5/6 scaffolds — fabricated or design-only; the honest pieces are already in `src/`.

## Net effect
The repository now reflects what actually runs: a ~16k-line live core (plus the
salvaged statistics), with the aspirational/fabricated ~50k pillar lines parked in
`quarantine/pillars/` rather than masquerading as working features.
