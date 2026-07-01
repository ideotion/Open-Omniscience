# Strategy-4 fan-out — ready-to-paste session prompt

Paste the block below into a **fresh Claude Code / claude.ai/code session on this
repo** (Opus 4.8, web search enabled). It orchestrates the whole subagent fan-out
over the under-tagged sources and opens a PR. It relies on tooling already in the
repo (`scripts/make_enrichment_batches.py`, `enrich_sources.workflow.js`,
`scripts/merge_enrichment_results.py`).

---

You are enriching source metadata in `configs/sources.yml` for the Open Omniscience
repo. ~2,900 of the ~3,200 sources carry at most one topical tag. Your job: classify
them via a **subagent fan-out** (each subagent handles one batch, so each gets its
own tool-call budget), then additively merge and open a draft PR. Do NOT hand-edit
`sources.yml`; the merge script writes it.

## Steps

1. **Branch** off the latest default branch `0.09`:
   `git fetch origin 0.09 && git checkout -B claude/source-fanout-enrich origin/0.09`

2. **Generate the worklist** (no prompts, just the input lists):
   `python scripts/make_enrichment_batches.py --no-prompts --batch-size 40`
   This writes `docs/design/source_enrichment/batches/input_<lang>-NNN.txt`
   (`# domain | name | country | language`). Read them; they are your batches.

3. **Fan out.** Preferred: run the repo Workflow
   `docs/design/source_enrichment/enrich_sources.workflow.js` — parse the
   `input_*.txt` rows into `[{domain,name,country,language}, ...]` and pass them as
   `args` (it chunks, spawns one web-enabled subagent per batch with schema-validated
   output, and returns `{rows}`). If the Workflow tool is unavailable, instead spawn
   `general-purpose` subagents yourself, **8–12 in parallel per message**, one batch
   each, giving each subagent the CLASSIFICATION BRIEF below. Collect every row.

   Budget discipline: tell each subagent to answer well-known outlets from knowledge
   and use web search only to verify an *uncertain* source, **≤1 search per source**,
   no multi-page browsing. ~40 sources/batch keeps a subagent inside budget.

4. **Write results** to `results/fanout/<lang>-NNN.yaml` (a YAML list of the rows).

5. **Merge additively** — dry run first, eyeball it, then apply:
   `python scripts/merge_enrichment_results.py results/fanout/ --min-confidence medium`
   `python scripts/merge_enrichment_results.py results/fanout/ --min-confidence medium --write`
   It unions tags, sets `source_type` only when missing/`news`, fills country/language
   only when absent, never overwrites curated values, never invents sources.

6. **Verify + PR.** Run the guard `python -m pytest tests/test_source_taxonomy.py -q`
   (every value must stay in the controlled vocabulary; no leaked country names).
   Review `git diff configs/sources.yml`. Commit, push `-u origin`, open a **draft**
   PR onto `0.09`. Do NOT commit the `results/` or `batches/` bulk.

## CLASSIFICATION BRIEF (give this verbatim to every subagent)

> Classify each source below. Output a YAML list, one row per input line, same order,
> keyed by the exact `domain`. NEVER fabricate — omit any field you are unsure of and
> lower `confidence`. A wrong tag is worse than a missing one. Answer well-known
> outlets from your own knowledge; use web search only to verify an uncertain source,
> at most one search per source, no multi-page browsing. Return all rows in one block.
>
> Fields (orthogonal — keep separate):
> - `source_type` (exactly one): news, wire-agency, magazine, broadcaster,
>   investigative, academic-research, scientific-journal, government-primary, igo,
>   ngo-civil-society, think-tank, fact-checker, data-portal, blog, religious,
>   financial-data.
> - `ownership` (one, omit if unsure): independent, state-owned, public-broadcaster,
>   state-media, corporate, party-affiliated, nonprofit, cooperative, wire-agency.
> - `lean` (omit unless a widely-cited stance exists — most rows: omit): lean-left,
>   lean-center-left, center, lean-center-right, lean-right.
> - `topics` (1–4): politics, economy, business, finance, markets, science,
>   technology, ai, health, medicine, climate, energy, environment, agriculture,
>   space, defense, security, cybersecurity, human-rights, justice, law, migration,
>   education, culture, sports, media, religion, local-news, regional, general (or a
>   precise lowercase-hyphen tag).
> - `country` (ISO-3166-1 alpha-2 lowercase) and `language` (ISO-639-1): include ONLY
>   if the input shows `?` and you are sure. `coverage_scope`: local|national|regional|global.
> - `confidence`: high|medium|low. `note`: ≤12 words or "".
>
> If a domain is dead or unidentifiable: `source_type: news`, `confidence: low`,
> `note: "unidentified"`, nothing else. Never invent an identity.
>
> Row schema:
> ```yaml
> - domain: example.com
>   source_type: news
>   ownership: independent      # omit if unknown
>   lean: lean-center-left      # omit unless documented
>   topics: [general, politics]
>   country: fr                 # only if input had '?'
>   language: fr                # only if input had '?'
>   coverage_scope: national
>   confidence: high
>   note: ""
> ```

## Honesty rules (non-negotiable)
Never fabricate. No composite scores. `lean` is reputational/contestable — set it only
where widely documented. Machine tags never overwrite curated ones (the merge enforces
this). Keep the run inside the controlled vocabulary in `src/catalog/taxonomy.py`.

## Scale note
~2,900 sources ÷ 40 ≈ 73 batches. English is the bulk (~43 batches); the rest is a
multilingual tail — group by language (the generator already does) so each subagent
stays in one linguistic lane. Expect the obscure long tail to trigger most of the
searches; that is exactly the work the fan-out distributes across per-agent budgets.
