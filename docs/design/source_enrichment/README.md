# Source-metadata enrichment — operator runbook

Enrich `configs/sources.yml` so sources carry real multi-dimensional metadata
instead of a lone `news` tag. Full rationale + taxonomy:
[`../SOURCE_METADATA_ENRICHMENT_STRATEGY.md`](../SOURCE_METADATA_ENRICHMENT_STRATEGY.md).

There are **two ways to run the LLM classification** (Strategy 4). Both produce the
same result rows; both feed the same additive merge.

## Why this scales: per-agent tool budget
A single chat session has a limited tool-call budget, so verifying 2,958 sources in
one session is impossible. **Each subagent gets its own budget.** Splitting the work
into batches — one batch per subagent — multiplies the available budget by the number
of agents. That is the whole reason fan-out is the right tool for "so many sources."

---

## Path A — Claude Code subagents / Workflow (in-session, automated)
Best when this environment has web access (it does — verified 2026-06-27).

1. Generate the worklist (parse the inputs you want to process):
   ```
   python scripts/make_enrichment_batches.py --no-prompts        # writes input_*.txt
   ```
2. Fan out with the workflow (requires opting into the Workflow tool — say
   "run a workflow"): pass the parsed `input_*.txt` rows as `args`. The workflow
   ([`enrich_sources.workflow.js`](enrich_sources.workflow.js)) chunks them, spawns
   **one web-enabled subagent per batch** (each with its own tool budget), validates
   every row against a schema, and returns the merged row array.
3. Save the returned rows to `results/<name>.yaml` and go to **Merge**.

Smaller alternative without the Workflow tool: ask Claude to spawn a handful of
`general-purpose` subagents (the Agent tool) in parallel, each given one
`input_*.txt` batch + the rules from the prompt template, each returning YAML.

## Path B — external parallel chat sessions (manual, no sandbox needed)
Best when you want to run many Opus 4.8 web sessions yourself in parallel.

1. Generate ready-to-paste prompts:
   ```
   python scripts/make_enrichment_batches.py            # batches of 50, by language
   ```
   → `batches/prompt_<lang>-NNN.md` (template + that batch's input inlined) +
   `batches/MANIFEST.txt`. (`prompt_en-001.md` is committed as a worked example; the
   rest is regenerated and gitignored.)
2. Paste each `prompt_*.md` into a fresh Opus 4.8 session **with web search**, in
   parallel. Group by language so each session stays in one lane. Save each YAML
   answer to `results/<id>.yaml`.

---

## Merge (both paths converge here — additive, dry-run by default)
```
python scripts/merge_enrichment_results.py results/ --min-confidence medium
python scripts/merge_enrichment_results.py results/ --min-confidence medium --write
```
- Unions tags (topics + valid ownership + valid lean), sets `source_type` only when
  missing/`news`, fills `country`/`language` only when absent.
- Never overwrites curated values; never adds new sources (unmatched domains are
  reported). Low-confidence rows skipped by default.
- Review the `git diff` on `configs/sources.yml` before committing.

## Honesty rules (non-negotiable)
Never fabricate — omit + lower confidence instead. No composite scores. `lean` is
reputational/contestable, set only where widely documented (most rows: none).
Machine-derived tags never overwrite human-curated ones.
