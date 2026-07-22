# Autonomous session brief — lemmatization goes DEFAULT-ON (2026-07-18)

**The ruling (maintainer, 2026-07-18).** `OO_FAMILY_LEMMA` flips from default-OFF to
**default-ON**. The gate that held it — measure-before-trust — is now SATISFIED: the
maintainer ran the `lemma_preview` instrument on the live ~500k-article corpus (top 500
keywords → 35 candidate groups / 71 keywords) and reviewed the merges for precision;
the sample is clean (regular plurals + verb forms + irregulars: file/filed, build/built,
call/called, study/studied, learn/learning, jour/jours…; nothing meaning-changing — the
`media→medium` class is already denylisted). NOTE the recorded correction that reframed
this gate: lemmatization is a DISPLAY-layer families change, invisible to the FTS
retrieval harness, so the IR-gold-set A/B was never the coherent measurement — the
precision review of the preview was, and it has now happened. The preview stays the
standing review instrument after the flip.

**Executor:** one Claude Code CLI session, LOCAL only (no egress). Branch
`claude/lemma-default-on-*` off a freshly-fetched `origin/main`, ONE draft PR,
commit-per-slice. House gates: staleness guard on every anchor below (verified at
`56c0e86`, 2026-07-18 — the repo moves fast, re-verify); full local suite green
(py3.13 `.venv` where available; simplemma is in the `[analysis]` extra); ledger +
`docs/ledger/shipped.csv` rows at close; CLAUDE.md merges ADDITIVELY (never revert a
sibling session's lines).

---

## §1 Ground truth (anchors verified at `56c0e86`)

- `src/analytics/families.py`:
  - `_lemma_enabled():188` — `os.getenv("OO_FAMILY_LEMMA", "0") == "1"` ← **the flip site**.
  - `_LEMMA_LANGS:176` — `{en, fr, de, es, it, pt, nl, ru, id}` (simplemma-well-covered;
    zh/ja + poorly-covered languages deliberately no-op: "a wrong lemma is worse than none").
  - `_MISLEMMA_DENYLIST:183` — media/data/us/good/better/was/be/left/right.
  - `_lemma():196` — conservative guards: single-token TERMS only (never entity names),
    per (kind, language), denylist, missing-simplemma/any-error → fall back to `norm`.
  - `conflated_by` provenance: dataclass field `:223`, `to_dict:238`, set at `:421` —
    exposed in the API payload but **never rendered in the frontend** (the deferred
    indicator — see S3).
- Tests that PIN THE OLD DEFAULT (these change meaning, not just assertions):
  - `tests/test_repo_invariants.py:490 test_lemmatization_is_opt_in_display_layer_and_reversible`
  - `tests/test_families.py:185 test_lemma_is_off_by_default`
  - `tests/test_families.py:162/:201` monkeypatch `OO_FAMILY_LEMMA=1` (still valid; the
    env override becomes redundant but harmless).
- Instruments (unchanged in behavior, updated in wording):
  - `src/analytics/engine_report.py:254 lemma_preview_report` (+ `_lemma_preview:211`) —
    the Settings→Diagnostics "preview lemmatization merges" surface.
  - `src/analytics/selftest.py:476` `lemmatization_mechanism` golden (checks `_lemma`
    directly — env-independent, thread-safe; unaffected by the flip).
- Core-install safety: simplemma ships in `[analysis]`; on a core install
  `_simplemma is None` → the whole pass no-ops regardless of the default. The
  "Core-only install" CI lane is the proof — the flip must not disturb it.

## §2 The slices

### S1 — The flip (the whole point; keep it surgical)
1. `_lemma_enabled()` default `"0"` → `"1"` (opt-OUT: `OO_FAMILY_LEMMA=0` disables).
   Update the function/docstrings and the `families.py` header comments: the
   measure-gate is SATISFIED (cite the 2026-07-18 live-corpus precision review), the
   discipline continues via the preview instrument + the evidence-grown denylist.
2. Rewrite the two default-pinning tests to pin the NEW contract:
   - `test_lemma_is_off_by_default` → `test_lemma_is_on_by_default_and_opt_out_restores_byte_identical`:
     no env → studied/study MERGE; `OO_FAMILY_LEMMA=0` → byte-identical to the
     pre-lemma grouping (the reversibility half is the load-bearing assertion).
     Mind the sandbox: this test must skip gracefully when simplemma is absent
     (follow the existing skip-guards in the same file).
   - `test_repo_invariants.py:490` → rename/reframe: default-ON + display-layer +
     reversible. It must KEEP the invariants that matter: `extract.py`/`store.py`
     never import simplemma (the trusted index stays untouched), the denylist exists,
     the opt-out env is honored. Grep the TEST tree for the old test name and any
     source-anchored strings before renaming (the stale-anchor lesson).
3. Docs sweep, small: `docs/design/KEYWORD_ENGINE_OPTIMIZATION_STRATEGY.md` P4.3
   status, USER_MANUAL if it names the toggle, and the Settings→Diagnostics hint text
   beside the preview button if it says "default off" (i18n: only if the string is
   keyed; follow the un-keyed-diagnostics-strings convention otherwise).

### S2 — Preview honesty upgrade (the maintainer's own critique)
The preview lists lemma-sharing groups WITHOUT subtracting what the plural rule
already merges — so most of its rows (agent/agents, cost/costs, country/countries…)
looked like new merges but are already collapsed in display today. Annotate each group
with whether it is **already merged by the plural rule** vs a **genuine lemma
addition** (verb forms/irregulars), so future reviews show the true delta. Pure
computation in `_lemma_preview` (the plural logic is in the same module —
`_plural_bases` et al.); no new endpoint; update the report's method text. Counts
only, no score.

### S3 — The deferred `conflated_by` indicator (conservative + flagged)
Now that lemma merges actually render by default, ship the deferred frontend
indicator: family chips/groups that carry `conflated_by: ["lemma"]` show a small
"conflated by lemma" marker (title-hover via the #oo-tip convention; a keyed string ×12
locales, or English-fallback via `t()` per the standing convention — state which).
Browser-unverified per fork-3/Q6a: node --check + an invariant guard + defensive
render (missing field → no marker). Small, additive, no layout shift (invariant #3
family: constant footprints).

### S4 — Watch item, NOT a change
`learn/learning` is the one sample merge worth watching ("learning" standalone often
comes from machine-learning contexts). Do NOT pre-add it to the denylist — the
denylist is evidence-grown (observed annoyance, keyword-log evidence), not
speculative. Record it as a watch in the ledger row.

## §3 Verification

- Negative space: unsupported languages (zh/ja/ar + an unknown code) produce ZERO
  merges default-on; denylisted norms never merge; entities never merge; a split
  override still wins; `OO_FAMILY_LEMMA=0` is byte-identical to today's output.
- The existing enabled-path tests (`test_families.py:162/:201`) stay green unchanged.
- Full suite + `node --check` (S3) + i18n gate if any keyed string is added.
- Honest limitation to carry in wording wherever the feature is described: the deeper
  grouping applies to the NINE `_LEMMA_LANGS` only — a mixed corpus gets uneven family
  depth by design (disclosed, like the segmenter gap), never a fabricated merge in an
  unsupported language.

## §4 Out of scope

Extending `_LEMMA_LANGS` (needs per-language quality evidence, not this session);
CJK anything (segmenter territory); touching `_normalize`/the stored index (forbidden
— display layer only, invariant-pinned); any denylist additions without evidence;
the BM25F default choice (a genuinely separate, retrieval-side decision that still
wants the graded gold set).

## §5 Definition of done

The flip + reframed tests green; the preview shows plural-rule-overlap vs genuine
additions; the indicator shipped conservative+flagged; ledger + shipped.csv rows
(including the learn/learning watch); one draft PR onto `main` whose body shows the
maintainer's §0 preview table annotated with what actually changes at default-on.
