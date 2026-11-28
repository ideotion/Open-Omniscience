# Analysis scripts

Standard-library Python 3.13, except `catalogue_index.py`, which imports `yaml` and the repo's own
`src/database/feed_key.py`. They read the raw exports and write intermediate files. None of them fetches anything.
The raw data and the intermediate files are private: they hold article text, per-instance source lists and the
manual labels. Only aggregate output belongs in a report.

Run every script with `python3 -I` and keep the scripts outside the data folders, because the exports are
untrusted input.

**Inputs**
- `DATA_ROOT/<folder>/`: one folder per instance, holding the downloaded exports unpacked by `unpack.py` (one
  sub-folder per archive; byte-split parts are joined).
- `INSTANCES_JSON`: `{"<folder>": "<label>"}`, for example `{"folderA": "Linux A", ...}`. Keep it private if the
  folder names identify machines.

**Order**
1. `unpack.py SRC DATA_ROOT`
2. `identify.py DATA_ROOT` (local only: prints machine facts for matching) and `inventory.py DATA_ROOT INSTANCES_JSON REPO`
3. `build_sources.py DATA_ROOT INSTANCES_JSON DERIVED`: per-source tables
4. `article_quality.py DATA_ROOT INSTANCES_JSON DERIVED`: per-source random-article flags (quality.md §1.2)
5. `label_sample.py DATA_ROOT INSTANCES_JSON 40 20261128`: the manual-reading sample (quality.md §1.1)
6. `keyword_quality.py DATA_ROOT INSTANCES_JSON` (quality.md §1.3)
7. `ingest_runs.py DATA_ROOT INSTANCES_JSON [EXTRA_ROOT EXTRA_JSON]` and `collection_contention.py` (ingest.md, scraping.md §3.2)
8. `stage_a.py STAGE_A_DIR [SECOND_DIR]` (scraping.md §3.3)
9. `catalogue_index.py REPO CATALOGUE.json`, then `catalogue_join.py`, `catalogue_health.py`,
   `catalogue_evidence.py`, `catalogue_lists.py` and `catalogue_language.py` (catalogue.md)
10. `qualification_checks.py DATA_ROOT INSTANCES_JSON "Linux A" "Linux C"`, `candidates_eval.py`,
    `freshness_rule.py` (source-qualification.md, catalogue.md §4)
