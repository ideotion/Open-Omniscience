# The Bulletin — periodic corpus document

Design record · 2026-07-31 · **nothing built yet**

Supersedes the 2026-07-30 "Weekly Synthesis" draft. Every code claim below was
re-derived from `main` @ `0d76fac` by a verification pass; claims that did not
survive are corrected in place and the correction is marked. Where a mechanism is
missing, this record says so rather than assuming it.

---

## 1. What it is

A periodic document generated from the corpus, describing what rose during a
bounded period, with numbered citations to the articles, law revisions, wiki
revisions, statistics and hazard alerts that support each statement.

It has two outputs:

- **The document** — a self-contained HTML file (plus Markdown and the JSON
  record it renders from). Light, externally linked, shareable.
- **The evidence archive** — an owner-only ZIP holding every cited article and
  source with full metadata, for archival and quality assurance. Not part of
  distribution.

It is deterministic first. A local model may narrate it; that layer is optional,
removable, and gated (§5, §6).

## 2. Naming — RULED

User-facing name: **Bulletin**.

Chosen over "Synthesis" and over "AI summary", for two concrete reasons:

- **"Synthesis" is already taken** by a shipped sibling: two "Synthesize results"
  buttons, `POST /api/llm/synthesize`, `ArticleAnalysis(kind="synthesis")`,
  `SYNTHESIS_PROMPT_VERSION = "synthesis-v2"`, the `#synth-window` dialog, and an
  editable "Synthesis prompt" in Settings. The previous draft resolved this by
  relabelling those surfaces. Naming the new artifact **Bulletin** removes that
  work entirely — nothing existing is renamed.
- **"AI summary" would mislabel it.** The artifact is deterministic-first with a
  removable narration layer, and on hardware below the capability bar (§3) the
  narration is off. A section called "AI summary" would then name a document
  containing no model output. The app reserves the "AI-derived — unreliable"
  label for actual model output; the Bulletin's deterministic half is not that.

Internal namespace: `src/bulletin/`, `/api/bulletin/*`,
`llm_prompt_bulletin_narration`, `BULLETIN_NARRATION_PROMPT_VERSION`.

**HARD RULE (carried over, verified):** do **not** reuse
`ArticleAnalysis(kind="synthesis")`. Verified at `src/api/llm.py:1377-1388` — the
existing path writes a full copy of the synthesis text onto **every** member
article (`for a in ordered: db.add(ArticleAnalysis(...result=result.text...))`).
At `_SYNTHESIS_MAX_ARTICLES = 20` that is 20 copies; an edition citing hundreds
would write hundreds of copies of a long document into the encrypted corpus. The
Bulletin is its own persisted artifact.

"Newsletter" remains rejected as a name: it already means **inbound** in this app
(`newsletters.import.local`, `NewsletterImportManager`, Settings → Newsletters).

## 3. Hardware gate — RULED

**The whole feature is unavailable on hardware that cannot practically run local
inference.** Not merely the narration layer — the feature does not appear.

Mechanism: the existing predicate `inference_capability()`
(`src/llm/backend.py:258`), which composes `detect_gpu()` and
`detect_apple_silicon()`. The Bulletin requires the **practical** tier.

Three invariants this must not break:

1. **Never put hardware policy in `detect_gpu()`.** That predicate answers "can
   vLLM run here?" and is read by 8+ vLLM-gating call sites; vLLM ships
   manylinux wheels only and cannot serve Apple Metal, so collapsing the two
   predicates routes every Mac to a vLLM that cannot run. `inference_capability()`
   is the only correct place. Pinned by
   `tests/test_inference_hardware_gate.py`'s ast guard.
2. **Never a hard block.** The standing override
   `llm_allow_impractical_hw` (`src/config/app_settings.py:94`) /
   `OO_LLM_ALLOW_IMPRACTICAL_HW=1` reveals the feature, with the warning stated.
   Hidden by default is not the same as forbidden.
3. **The refusal states which measurement it made.** Unreadable hardware
   facts report *unmeasured*, never *below* — a claimed shortfall on an absent
   measurement is as dishonest as a fabricated pass.

**Recorded tension, for the maintainer's awareness.** The 2026-07-31 ruling 15
made GPU-less a *warning* rather than a *refusal* for local inference in general.
This record deliberately applies a **stricter** gate to the Bulletin, and the
justification is workload shape, not hardware snobbery: ruling 15's warning tier
covers interactive, occasional inference (summarise one article on demand), which
a GPU-less 4-core box handles acceptably. The Bulletin's narration is a bulk
multi-hour workload of thousands of calls (§6), which the same box does not.

**Consequence the maintainer should know:** Layer A (§4) is pure SQL and would
run correctly on any machine. Gating the whole feature means a GPU-less operator
gets no document at all, not even the deterministic one. That is the instruction
as given and is implemented as such; making Layer A available below the bar is a
one-condition change if it is ever wanted.

## 4. Two layers

**Layer A — the record.** Deterministic, model-free, always produced (above the
gate). Structured facts for the period: counts, windows, methods, n, references.
Pure SQL over existing queries.

**Layer B — the narration.** A local model turns each fact bundle into prose,
grounded only in that bundle, placing citation markers assigned by Layer A.
Labelled AI-derived, and **removable** — strip Layer B and the document is still
complete, just stiffer.

Layer B paragraphs sit **adjacent** to the facts they narrate, never interleaved
into them, so a reader can always see which sentences a model wrote.

## 5. Windows — RULED

### 5.1 The rule

> **The rising comparison's RECENT window equals the COVERAGE window. The
> baseline is a multiple of it.**

Coverage (which articles the edition is about) and rising (what grew) then answer
the same question, and consecutive editions partition time exactly.

### 5.2 Why the alternative was rejected

An earlier proposal set the rising window to a *fraction* of the period (weekly =
last 1 day vs prior 7). Verified against `queries.py:1370-1371`, that produces a
structural pathology:

> Edition covers Mon–Sun, generated Sunday. Story X: 200 mentions Tuesday,
> decaying to ~5/day by Sunday. `trending(window_days=1, baseline_days=7)` →
> recent = Sunday ≈ 5; prior = Mon–Sat, **containing X's own peak** → expected ≈
> 30/day → growth = 5/30 = **0.17**.

The period's biggest story reads as *falling* in the edition covering that
period, because its peak sits in its own baseline — and it suppresses its own
follow-ups. Structurally, only 1 day in 7 ever contributes, so a story that rises
and decays inside Mon–Sat is never "rising" in any edition.

The proposal's values are also exactly the shipped presets shifted one cadence
down: proposed weekly `(1, 7)` is the shipped `("24h", 1, 7)`; proposed monthly
`(7, 30)` is the shipped `("7d", 7, 30)` (`queries.py:1466-1470`).

### 5.3 Defaults

Operator-editable; these are the defaults.

| Cadence | Coverage = rising recent | Baseline | Source |
|---|---|---|---|
| Daily | 1 d | 7 d | shipped `("24h", 1, 7)` |
| Weekly | 7 d | 30 d | shipped `("7d", 7, 30)` |
| Monthly | 30 d | 90 d | shipped `("30d", 30, 90)` |
| Trimester | 90 d | 270 d | extends the 3× tail |
| Semester | 180 d | 540 d | extends the 3× tail |
| Yearly | 365 d | 1095 d | extends the 3× tail |

Daily, weekly and monthly are the shipped `_TREND_WINDOWS` constants — already
maintainer-ruled and running on Home, so no new calibration. The baseline
multiple is bias-free because `expected` is rate-normalised
(`queries.py:1370`); it trades variance against regime contamination only.

**Long-cadence honesty rail:** at 3×, a yearly edition reaches back four years and
`expected` divides by the *nominal* baseline days regardless of corpus age. On a
younger corpus that understates `expected` and inflates growth. The edition must
report **actual baseline days covered** alongside nominal.

### 5.4 Hourly is blocked, not tweakable

`KeywordMention.observed_on` is a `Date` (`models.py:1768`) and the time is
destroyed at write: `observed_on = observed.date()` (`store.py:285`). There is no
sub-day keyword signal anywhere.

`KeywordMention.created_at` is a DateTime but must **not** be used: re-index does
`filter_by(article_id=...).delete()` then re-inserts every row stamped `now()`
(`store.py:306`), so one keyword clean-up collapses the entire history into a
single hour — a cross-time-recall violation.

Hourly would require a new column, index, migration and a corpus-wide backfill.
**Daily is the floor cadence.** (Article-level hourly volume *is* free —
`Article.created_at` is a DateTime and indexed — if volume-only is ever enough.)

### 5.5 Boundaries

- Windows are **half-open** `[start, end)`. Consecutive periods then have no gap
  and no overlap.
- **Do not reuse `_window_filter`** (`queries.py:1659-1665`): it is inclusive
  (`>= start`, `<= end`), so consecutive periods double-count the boundary day,
  while `_counts` (`:1341`) is half-open. Two conventions coexist in one file.
- **Do not reuse `trending()`'s today-anchored arithmetic** — see §5.6.
- `observed_on` is nullable and both bounds exclude NULL, so undated mentions are
  invisible to every window. Count and **disclose** that excluded set rather than
  dropping it silently.

### 5.6 A prerequisite bug, found while verifying this

Independent of the Bulletin, and worth its own reviewed slice:

`trending()`'s recent window is `_counts(w_start, today + timedelta(days=1))` =
`[today−N, today+1)` = **N+1 days** (`queries.py:1361`), but
`expected = (pc / baseline_days) * window_days` scales the rate to **N** days
(`:1370`). Growth is inflated by (N+1)/N — **2× on the "Past 24h" preset** — and
drifts through the day because today is partial. The same `+1` shape in
`supergroup_rising.py:180` and `concentration.py:64` **cancels**, because those
are same-window share tests; it does not cancel here. Tests place fixtures safely
inside windows and never assert width, which is why it is unnoticed.

The Bulletin must define its windows explicitly rather than inherit this.

### 5.7 Date convention — RULED

**`coalesce(published_at, created_at)` for the whole edition**, stated in the
method line. It is the only convention with an index built for it
(`ix_article_observed`) and the only one that never silently drops an undated
article. It is also already what `observed_on` stores (`store.py:284`), so the
keyword path needs no change.

Disclosed caveat: `published_at` is publisher-asserted and back-datable.
`latest.py` deliberately orders by `created_at` on those grounds. An article
ingested this period but published earlier therefore lands in an earlier bucket.
The edition states which clock it used.

## 6. Content anchoring — RULED

The previous draft's fact bundles carried no article text
(`_evidence_from_articles`, `producers.py:169-188`, emits only
`{title, url, source, published_at, article_id}`), so narration could only
re-word counts. Addressed frontally.

### 6.1 What already exists

- **Per-article When/Where/Who extraction is built, complete and eval-gated**:
  `src/ai_layer/perception.py` — one constrained call per article, a system
  prompt demanding exactly three lines `WHO:/WHERE:/WHEN:`, writing candidates to
  `ai_keyword` with model and prompt provenance, behind the tri-state
  `gate_languages_from_report`. **Reuse it; do not rebuild it.**
- **Batch summarisation and translation** exist: `POST /api/llm/bulk`
  (`src/api/llm.py:1464`), storing to `ArticleAnalysis` with provenance.
- **Keyword triage** (`src/ai_layer/triage.py`) judges the **global keyword
  vocabulary**, not one article's keywords. A per-article "confirm this article's
  keywords" stage does **not** exist — and is deliberately not proposed: the
  rule-based keyword index is the trusted layer, and having a small model
  "confirm" it either changes nothing or quietly corrupts the one deterministic
  thing the app has.

### 6.2 The layered path

1. **Extractive floor, no model.** Lead paragraphs of the top articles per
   cluster. Deterministic, zero fabrication risk. This is what the document
   contains when narration is off.
2. **Cached analyses.** Reuse existing `ArticleAnalysis` summaries/translations
   where present. Free; coverage is whatever has been computed.
3. **Narration over real text.** 3–6 representative articles' actual text per
   story cluster, temperature 0. This is the shape of the shipped
   `/api/llm/synthesize` path (`_SYNTHESIS_BUDGET_CHARS = 24_000`), the one place
   in the app that already feeds article text to a model.

**No cascade.** Stage 3 reads article text **directly**; extracted
When/Where/Who facts are optional *hints*, never inputs it depends on. A bad
extraction then degrades one hint instead of poisoning the summary.

### 6.3 Volume is a budget, not a count — RULED

There is **no recorded per-call LLM latency anywhere in this repo** (the capture
machinery exists; the measurements do not). So no honest article count can be
prescribed today.

Therefore the operator setting is a **time budget** ("spend up to N hours"), not
a count. The run works a disclosed priority order and the edition states
"AI-analysed 1,240 of 5,318 articles".

This preserves the anti-capping rule exactly: **deterministic counts stay exact
and uncapped; only the narration is sampled.** A cap bounds examples, never a
reported number.

**First build step is measuring**, so the setting has real numbers behind it.

### 6.4 Temperature — RULED

Temperature must be selectable on **both** backends. Verified: `options` reaches
Ollama (`ollama.py:401` → `payload["options"] = options`, `:415`) but is
**silently ignored** on vLLM — `options: dict | None = None,  # noqa: ARG002 -
signature parity with OllamaClient` (`vllm_client.py:142`). Map `options` →
OpenAI `temperature`/`top_p` in `VllmClient.generate`. Small, and a real
determinism bug independent of this feature.

## 7. Trustworthiness of the narration — RULED

The goal: know whether model-written sentences can be trusted, per language,
without pretending to knowledge nobody has.

Two kinds of checking, and they are not interchangeable:

**Machine checking — works in every language, needs no human.** Every number and
every named entity in a generated sentence must appear in the source text it was
given. If the model writes "312 articles" and no source says 312, the sentence is
rejected and the deterministic template is used instead. This is the echo-back
validation pattern already proven in `src/ai_layer/triage.py`. It catches
invented facts. It does **not** catch a sentence that uses only real numbers and
arranges them into a false claim.

**Human checking — only in languages the operator reads.** A sample is read and
graded. No gold set for grounding exists in this repo, and none can be
manufactured for languages the operator does not read; inventing one would be a
fabricated pass.

**The gate is therefore tri-state per language**, exactly as
`gate_languages_from_report` already behaves:

| State | Meaning | Effect |
|---|---|---|
| cleared | graded, met the floor | narration on for that language |
| failed | graded, below the floor | narration off, stated |
| **never evaluated** | not graded — e.g. operator does not read it | **narration off, stated** |

Never-evaluated is **epistemic, not permissive**: it explains the absence of a
measurement, and the decision still refuses. A language the operator cannot grade
never silently passes.

Batch translation can help spot-check a foreign-language edition by translating
it back into a language the operator reads — but translation can hide and
introduce errors, so it is an **aid, never the gate**.

## 8. What the model is not asked to do

> The model never authors a fact, a number, or a citation.

Layer A computes the facts and **pre-assigns** the reference numbers. The model
receives the bundle already in the output language and turns it into 1–3
sentences, placing the markers it was given. Failure → deterministic template for
that item, recorded as a fallback.

**Known blind spots, stated rather than papered over.** The validator checks
citation existence and numeric support. It cannot catch: an unsupported qualifier
("sharply", "unprecedented"), an invented causal link ("in response to"),
attribution of a fact to the wrong entity, or a citation that exists but does not
support the specific clause it is attached to. These are the reason §7's human
grading and §12's review step exist; they are not solved by validation.

**Per-sentence provenance is recorded** — `llm` / `template-fallback` /
`withheld` — and rendered visibly, with the counts in the masthead. Without it, a
document that is entirely fallbacks looks identical to one the model wrote, and a
model regression is invisible.

## 9. Citations and the two exits

### 9.1 Referents

| Referent | Identity | Recipient link |
|---|---|---|
| Article / newsletter / **alert** | id + content hash | `article.url` |
| Wikipedia change | `revid` | `?oldid=<revid>` — permanent, exact version |
| Law change | `content_hash` + `observed_at` | `official_url` — a **living** page |
| Statistic | series + vintage | agency URL |

Hazards need no special path: they are already ingested as one Article per
provider event id with magnitude and coordinates in a linked
`HazardEventDetail`.

Law is the hard case — the official URL has moved on since observation, so the
reference must say "as observed `<date>`; the linked page shows current text,
which may differ."

### 9.2 The published document carries external links only — RULED

`Article.id` is a local autoincrement with no meaning off the machine that
assigned it. A recipient also running the app resolves
`/api/articles/418823/view` against **their** corpus and gets an unrelated
article — a citation that appears to work and points at the wrong source. A
relative link 404s. There is no third outcome.

The shipped `_synthAsHtml` (`app.js:17449`) already does the right thing: it
renders the external URL and never the reader path. The Bulletin follows it.
Local reader links remain correct — and are kept — **on screen only**.

### 9.3 Hash claim, corrected

`generate_content_hash` hashes the whitespace-normalised **extracted** text. It
commits the operator to what was stored. It does **not** let a third party verify
against the live page — that would require the same extraction pipeline and
version. The previous draft's "the discrepancy is visible rather than silent"
overclaimed. The archive (§9.4) is what makes the commitment inspectable.

### 9.4 Two exits, one record — RULED

The question was whether to use the export/backup tool or a ZIP. They solve
different problems, and one comes free.

- **The edition JSON rides the encrypted backup automatically.** Persist under
  `data_dir()/bulletin/` and register one line in
  `src/backup/artifact.py::_collect_members` — exactly how import reports already
  do it (`artifact.py:337`). Reliability, restore and versioning: free.
- **The evidence ZIP is a separate, on-demand, operator-initiated export.**
  Directly browsable, no passphrase, no app needed. Reuses the multi-part builder
  at `src/api/diagnostics.py:3864`.

So: both, but not two archives. The backup carries the **record**; the ZIP is an
**export** of it. One source of truth, two exits.

**Stated plainly at export:** the ZIP is plaintext corpus content leaving the
encrypted store. That is the operator's choice to make, and it is disclosed, not
assumed.

**ZIP contents:** cited articles with full metadata · the source records ·
the Layer A fact bundle · the exact prompts, model id and backend · a structured
table of contents. **File naming:** `20260731-OOS-bulletin-2026W31/`.

### 9.5 Reference titles are never translated

Original title verbatim plus a language tag. A translated title is a fabricated
citation. Concept translation belongs in the body.

## 10. Output and delivery — RULED

**Format:** self-contained HTML with inline `style=` attributes, no external
assets, no JS. Mail clients strip `<style>` blocks unpredictably and ignore CSS
variables, so the 17-theme system is unusable here.

**Three renders from one JSON record:** inline-styled HTML, Markdown, and the
JSON itself.

**One render, three uses:** server-render at `/api/bulletin/{id}/view` exactly
like `/api/articles/{id}/view` — the same file is the in-app reading surface, the
save target, and the mail body. (Plain `def` handler or `run_in_threadpool`; an
`async def` freezes the single worker.)

**Delivery: download the HTML file is primary; a short digest is what gets
pasted.** Two reasons the previous draft's clipboard-first plan fails:

- Gmail clips HTML mail at ~102 KB (far less on mobile), and because the
  reference list sits at the bottom, the discarded bytes are precisely the
  citations. A document whose honesty rests on per-claim references would arrive
  with the claims intact and the evidence cut off.
- `ClipboardItem` `text/html` write support is materially weaker on Gecko than
  Chromium, and Gecko is this project's verification bar. A Chromium-only
  mechanism is untestable on the machine that signs it off.

**Caveats must be inline text.** The `#oo-tip` hover layering does not exist in
an exported document. Per-section method lines plus a **Methods & caveats**
appendix; `src/reporting/methods.py` is the seed.

## 11. Sections, ordering, and the masthead

Sections are registered producers over facts, so the list is cheap to change.
Proposed: the period in numbers · rising concepts · across channels (which
channel surfaced a concept first — computable from the denormalised
`KeywordMention.source_id`) · by topic tag · changes of record · alerts · plus
**Methods & caveats** and **References**.

**Deliberately omitted: any "top story" or editorial lead.** That is where an
implicit composite score creeps in. Ordering uses the disclosed `explain_order`
tuple and the section header states the method.

**Cross-time counterweight.** A periodic document structurally trains a reader
that recent equals important. A `through_time` section is included as a lens —
never a reweighting. Cross-time recall is sacred.

**Masthead is mandatory — RULED.** The document's framing verb is "what rose in
this corpus", never "what trended", and the lens is stated in the same breath:

- sources that actually contributed in the period, and the top-3 share
- language distribution, including the unknown-language bucket
- country / unlocated split
- days with any ingest, out of the period's days
- corpus total and the period's article count
- **the selection math**: how articles were chosen per section, sample vs total,
  never a cap presented as a total

All of it operator-tweakable in the Bulletin's settings.

**Prose style:** 1–3 sentences per item; no section introductions, no
transitions, no closing summary. Structure carries the flow. One amendment to the
previous draft: the 1–3 sentence rule left no slot for the caveat every producer
carries — caveats render on their own line, outside the sentence budget.

## 12. Producer selection — RULED

The previous draft proposed classifying producers up front into windowed /
whole-corpus / forward-looking. Replaced, on the maintainer's instruction, by
something better suited to a sandbox phase:

- **Every producer prints its real window** in the output. A monthly edition
  showing a 14-day echo number is then *visible* during testing rather than
  hidden.
- **Per-producer toggles in the review screen**, driven by the actual content:
  the operator sees each producer's output for this period and includes or
  excludes it before export.
- Classification then falls out of what is observed, instead of being guessed.

Toggling re-renders from the persisted JSON. **Never hand-edit output.**

## 13. Draft → review → publish

Full automation to a **draft**. Automation to published is rejected — the
operator is the byline.

The artifact has a state: `draft` → `published`. The review screen shows, per
sentence, the fact bundle it came from and whether it passed validation or fell
back to a template. Review can drop an item, drop a section, or toggle a producer
(§12), and **re-render**.

## 14. Scheduling, storage, cost

- **Layer A placement — corrected.** The previous draft put it in the
  housekeeping lane. Verified: that lane is refused **wholesale** under the kill
  switch (`runner.py:1684`), so on an airplane-first install a lane step would
  never run — contradicting "Layer A is pure DB, airplane-safe". Layer A must sit
  outside the lane, or the lane's airplane refusal must be per-step. Layer A is
  local SQL and must work offline.
- **Layer B is a `BackgroundJob`** (`cancellable=True`, `is_writer=False`):
  task-manager-visible, abortable, with a **persisted cursor** so a multi-hour
  run survives restart. It must **not** repeat the abort-to-done bug this repo
  has fixed three times: a transient LLM error must retry with backoff, never
  end the run in a benign-looking "done".
- **Idempotence.** An edition either exists on disk or does not. Enumerate the
  cases that break it: generated mid-period; a period that gains articles later
  via import or backfill; a re-index that changes counts; a machine off for two
  periods. A partial Layer B run must not read as a finished edition.
- **Import interaction.** Under the ruled merge behaviour an imported article has
  **no keyword mentions** until re-indexed. Read `reindex_backlog_status()` at
  generation: a non-empty backlog means article counts and keyword facts are
  computed over different populations. Refuse, or stamp the edition with the
  backlog size. `available: false` means *unknown* — refuse, never treat as
  clear.
- **Storage.** `data_dir()/bulletin/<period>-<id>.json`, atomic write, traversal
  guard, cloning `src/backup/import_reports.py`.
- **Quarantine.** `grep quarantined src/analytics/{queries,store,rollup_serve,columnar}.py`
  returns **zero hits** — every keyword aggregate currently counts quarantined
  articles. Layer A must exclude them explicitly, or disclose that it does not.

## 15. Continuous improvement — RULED

Not "audit the audit's quality". **An iterative loop**: improve the card system →
audit → improve → audit again, in the pharmaceutical sense of continuous
improvement. **This is the intended posture app-wide, not only for cards.**

**The prerequisite is already built.** `src/briefing/card_audit.py` (1,891 lines,
merged 2026-07-30) already implements what the previous draft proposed building:
per-card fact bundle, `check_trigger` arithmetic re-verification,
`_corpus_fidelity`, `_independence`, `walk_banned_keys`,
`non_fabrication_checks`, depth levels with a size preflight, and — closing the
gap the draft called "the gap that matters most" — `observe_producers`, which
records `ok` / `no-signal` / `error` per producer instead of collapsing every
empty result into an indistinguishable `[]`.

**What is missing is the loop, and it is three small instruments:**

1. **Determinism check** — run the card pass twice and diff. `card_audit` does
   not do this today, and the previous draft said determinism should be
   default-ON. Without it, "this number changed" cannot be distinguished from
   "this number is nondeterministic".
2. **Persisted audit runs** — each audit stored as a comparable snapshot.
3. **Audit-to-audit diff** — improved / regressed / unchanged / not-measurable.
   **`scripts/kpi_diff.py` already has exactly this shape** (`classify(old, new)`,
   `diff_snapshots`); it simply is not pointed at card audits.

Register the loop as a harness in `src/monitoring/recursive_loop.py`, which
already hosts this class of thing.

**Sequence:** build the three instruments → run improve/audit cycles until the
diff stops showing regressions → then the Bulletin consumes a card system whose
behaviour is known rather than assumed.

## 16. Placement — RULED

A **folded section at the very bottom** of the Advanced settings subtab, so it
can be reached by skipping to the end. Folded by default; discreet.

**Corrected count:** the previous draft said this would be the 20th Settings
subtab and listed 18. There are currently **12** (`graphics general shortcuts
models newsletters wikipedia stats offlinemap agenda data safety advanced`) —
`keywords`, `leads`, `collect` and `sources` were absorbed into `advanced`, and
the ruled restructure targets **10**. A new subtab would have collided with a
restructure actively reducing the count; a folded Advanced section does not.

**Folded must not mean fetched**: loaders fire on section **expand**, not on
subtab select, matching the existing Advanced sections.

Chrome strings follow the existing Advanced-section precedent, **except** that
every caveat, method, consent and AI-label string ships ×12 in the same commit —
that rule is binding for this feature regardless of the surrounding precedent.

## 17. Honesty rails

- No "top story"; ordering is the disclosed `explain_order` tuple.
- Recency is a lens, never a reweighting.
- Real totals; a cap bounds examples and must say "showing 10 of 347".
- External links in the exported artifact; local links on screen only (§9.2).
- Reproducible and vintaged: each edition records window bounds and basis, model,
  backend, prompt version **and exact prompt text**, corpus epoch and counter
  snapshot, section versions, app version. Vintages append, never overwrite.
- No score-shaped field names. Note the recorded trap: `"degraded"` contains
  `"grade"`, so per-status tallies are `[{"status": s, "n": n}]` objects, never
  dict keys.
- Post-publication: an edition is a frozen snapshot. A later quarantine,
  deletion or source disqualification does not retroactively alter what was
  cited — the archive preserves it, and errata are a stated procedure.

## 18. Privacy of the exported artifact

The document reveals the operator's source list, interests, cadence, and — via
timestamps — their timezone. Enumerate and decide before the first export:

- source names and domains
- article ids and corpus totals (a scale lower bound; across editions, a growth
  rate)
- app version (an install fingerprint)
- newsletter subject lines (reveals subscriptions)
- synthetic URIs exposing which verticals are enabled
- **signing key**: if editions are signed with the existing evidence key, every
  edition carries the same public key — a persistent identifier for the install
  across recipients. Either a per-edition ephemeral key or no signature, with the
  trade-off stated.

A named **publication profile** whitelists what may appear, and the document
prints which profile produced it so a recipient knows what was withheld. A
key-based scrubber is a net, never the mechanism — every item above is
legitimate content under an innocuous key.

## 19. PR and documentation tone

Neutral and feature-only. No mention of publishing, monetisation or personal
motivation in PR titles, bodies, commit messages, code comments or docs. The
feature is generically useful — any operator may want a periodic document over
their own corpus — so descriptions can be honest without being personal.

## 20. Open questions

1. Final section list (§11 is a proposal).
2. Introduction: include one? Generated from edition facts, templated, or none?
3. Mail sending: never / opt-in later? (Current design is download plus a short
   digest for paste. Sending is real egress that reveals the operator to a mail
   provider, off Tor, with stored credentials.)
4. Should Layer A be available below the hardware gate (§3), given it needs no
   model?
5. Review-screen UX detail.

## 21. Build order

1. `trending()` off-by-one fix (§5.6) — independent, own reviewed slice.
2. vLLM temperature mapping (§6.4) — independent, small.
3. Continuous-improvement instruments (§15): determinism check, persisted audit
   runs, audit-to-audit diff. Run cycles.
4. Explicit `start`/`end` windows on `top_terms` / `trending` / `trending_windows`,
   mirroring `associations`' existing `_window_filter` signature.
5. Measure LLM per-call latency (§6.3) so the budget setting has real numbers.
6. Layer A: period-bounded article selector + fact bundles + quarantine exclusion.
7. Persistence, backup registration, ZIP export.
8. Layer B: story clustering, narration, validator, per-sentence provenance.
9. Settings section, review screen, renders.

Steps 1–3 are worth doing whether or not the Bulletin is built.
