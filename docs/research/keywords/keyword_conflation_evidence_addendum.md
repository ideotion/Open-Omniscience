# Keyword Conflation in Open-Omniscience — Evidence Addendum (v2.1)

> Repository note (saved 2026-06-26): this is the COMPLETE-log revision. An earlier
> first pass computed its figures over a top-5,000-rows-per-language cap (truncated after
> "sr"); three numbers were cap artifacts and are corrected in place below (the
> capped pass is superseded — its 8.7% global mismatch figure was the artifact). Companion
> to `keyword_conflation_FOSS_research.md`.

Author of request: Ideotion
Companion to: keyword_conflation_FOSS_research_v2.md
Basis: the five diagnostics uploaded 2026-06-25 — keyword-engine report, two
selftests (06-24, 06-25), the Heaps growth curve, and the per-language keyword log.
Every number below is computed from those files; the method for each is stated.
Counts only, never a score — same posture as the source artifacts.

REVISION (after the COMPLETE log was supplied): the first log zip was capped at the
top 5,000 rows per language (and truncated after "sr"). The complete export — 48
files, 206,850 rows, en alone 74,962 rows — supersedes it. Three numbers moved and
are corrected in place below; the conclusions did not change, two of them got
stronger. Corrected figures: global language-mismatch is 16.2% (not 8.7% — the 8.7%
was a cap artifact, not a missing tail); the English mismatch is 39.7% among the
top-5,000 most-mentioned but 17.2% across the full English log; the English
lemma-merge rate is 20.7% of single-token terms on the full log (32.6% on the dense
top-5,000 head). The zh-vs-th "unsegmented" finding is also refined (P4).

Headline: the data largely CONFIRMS the v2 diagnosis but RE-PRIORITIZES the fix.
Morphological fragmentation (the country/country's problem) is real and measurable,
but it is one slice among several, and it is NOT the cheapest or highest-yield lever.
The largest, cheapest win is a RE-INDEX to flush a stale digit/code-token backlog the
filters already remove; the largest head-quality problem is language MIS-assignment,
which is also a prerequisite for trustworthy lemmatization.


## A. What the data CONFIRMS (v2 was right)

  A1  Plurals are already handled (v2 correction C1, now proven). selftest
      plural_family_merge = PASS on both 06-24 and 06-25 (state + states collapse).
      The rule layer works on golden cases. v1's "rules cannot do plurals" is dead.
  A2  The cross-language ring is additive and sparsely populated, exactly as v2 said:
      translation_coverage = 79 of the top 500 keywords in a ring (15.8%), 550 rings
      total against ~977k keywords. (engine report)
  A3  Entity handling is acronym-only. entity_precision = 43,090 entities, 100%
      acronyms (Title-case dropped 2026-06-16). This SHARPENS v2's Section 6: there is
      effectively NO spelled-out person/org/place recognition live, so OpenTapioca
      linking (L3) would be the FIRST real entity layer, not an enhancement (see C3).
  A4  The baseline/Item AC tagging exists but is unpopulated: tag_coverage = 0 of the
      top 500 tagged (0.0%), 40 curated tags total. v2's C5 ("plug into the baseline
      subsystem") is architecturally right, but the subsystem is empty in practice —
      seeding it is its own work item (P6).


## B. What the data CORRECTS (in v2, and in my own first pass)

  B1  Cross-language fragmentation is NOT a row-duplication problem. On the complete
      export, of 197,044 distinct normalized forms, only 1,631 (0.8%) appear in
      >=2 language files, and they are edge cases (proper nouns like neymar; loanwords
      premium/format/sol; same-script shares across ar/fa/ur and ru/uk/bg). The
      language_signature already aggregates a concept's cross-language mentions into
      ONE row (e.g. "data" carries en + id + ? mentions in a single row). So the ring
      layer's job is translation ANNOTATION and merging DIFFERENT strings
      (election/élection/wahl), not de-duping the same string. Do not oversell
      cross-language as a fragmentation source; the data says 0.3%.

  B2  The dominant extraction noise is digit/code tokens, not morphology, and it is
      STALE. In the 60,000-row scan the engine flagged 17.3% (10,409): mostly_digits
      7,171 + code_token 3,087 dominate; markup_token 0 and has_markup_char 0 (markup
      stripping works); elision_contaminated only 151. Crucially the report itself says
      mostly_digits/code_token "clear on re-index" — the §2.5/§2.6 filters already drop
      them; the stored rows simply predate the filters. Examples are aircraft/code
      designations and hashes: A-10C, A-18A-D, 1h15, gd_combo_table,
      A013AF040A51D0025848F016CA8DDD6D. This is backlog, not a missing capability.

  B3  POS-free lemmatization at the head is risky but BOUNDED — and mostly correct,
      including the irregulars the rules cannot do. See Section C; this tempers v2's
      C4 (the hazard is real, ~1% of merge groups, fixable with a tiny denylist) while
      keeping its conclusion (do not ship POS-free lemmatization without that denylist).

  B4  spaCy may not be deployed here. 100%-acronym entities (A3) strongly implies the
      acronym-only BaselineExtractor is what indexed this corpus, not the spaCy NER
      pipeline (which would have emitted PERSON/ORG/GPE). If so, v2's L1a ("re-enable
      spaCy's lemmatizer+tagger, the cheapest POS path") is unavailable in this
      deployment, and simplemma (L1b) becomes the realistic primary — which makes the
      denylist mandatory, not optional. Verify via the Keyword.extractor provenance
      field (a GROUP BY extractor); if it is ~all "baseline", L1a is moot.


## C. The empirical lemmatizer test (the decision-relevant result)

I ran simplemma 1.2.0 (en) over the visible single-token alphabetic TERMS in the
English log (the live head) to measure what a lemmatizer would actually merge.

  Population: en.json. Two cuts, because the first export was top-5,000-capped:
    - dense head (top 5,000 mentions): 4,522 single-token alpha terms.
    - full English log: 38,135 single-token alpha terms.
  Result:
    - Head: 1,018 lemma groups with >1 form; 1,476 rows (32.6%) would merge; those
      groups hold 68.8% of term mentions.
    - Full log: 7,880 rows (20.7% of single-token terms) would merge; those groups
      hold 77.0% of term mentions. The lower ROW rate (20.7% vs 32.6%) is expected —
      the long tail has more genuinely unique terms — while the higher MENTION share
      (77%) confirms merges concentrate on the high-traffic head. Use 20.7% as the
      representative row-reduction estimate; the head is denser.
    - Of the head's 1,018 groups, only ~517 are regular-plural-with-base-present (what
      families.py P1.5 already covers); ~501 are NET-NEW (verbs, irregulars,
      short plurals P1.5's len>=5 guard skips like key/keys, law/laws, act/acts).

  Danger analysis: only 13 of 1,018 groups have members that do NOT share a stem
  (the over-merge signature). Most of those 13 are CORRECT irregular morphology that
  the rules cannot reach and that a lemmatizer SHOULD merge:
    give/gave/gives/giving, hold/held/holds, keep/keeps/kept, bring/brings/brought,
    sell/selling/sold, grow/grew/grown, seek/seeks/sought, break/broken, sit/sat/sits,
    foot/feet, less/least.
  The genuinely WRONG merges are a tiny, high-traffic minority:
    good <- best/better/GOODS   (15,680 mentions; "goods"=commodities must NOT fold)
    wrong <- worse/worst/wrong  ( 2,278 mentions; "wrong" is not the comparative of bad)
    medium/media                ( "media"=press is not the singular "medium")
    down/downing                ( "downing" is not an inflection of "down")
  Plus judgment calls (tuning, not bugs): adjective degrees high/higher/highest and
  good/better/best — a journalism index may want these kept distinct.

  Conclusion: lemmatization is net-positive even at the head (it captures valuable
  irregular verbs/plurals the rules miss), but POS-free simplemma needs a small
  curated mislemma denylist — the SAME evidence-grown pattern as _PLURAL_DENYLIST.
  Starter denylist, drop into the conflation layer (pin these to their own key; never
  fold into the lemmatizer's proposed base):

      mislemma_denylist:          # form -> keep standalone, do NOT take simplemma's lemma
        - goods                   # not "good"
        - media                   # not "medium" (press sense)
        - wrong                   # not "worse"/"bad"
        - downing                 # not "down" (Downing St / surname)
        - saw                     # not "see" (tool / past tense ambiguity)
      degree_policy: keep_separate  # high/higher/highest, good/better/best stay distinct
      short_plural_extend: true     # allow P1.5 to merge 4-letter plurals (keys/laws/acts)

  Caveat on scope: this is the English HEAD only. The tail (692,186 single-article
  keywords, below) is where lemmatization yields the most ROW reduction, but the tail
  is also where language MIS-assignment (Section D) is worst, so tail lemmatization
  must be gated on a trustworthy language tag.


## D. The head-quality finding v2 under-weighted: language MIS-assignment

The per-language log carries a language_mismatch flag (stored language tag disagrees
with the keyword's own mention-signature majority). Rates I computed:

  Complete export (48 files, 206,850 rows): 33,562 flagged = 16.2%.
  Per language (mismatch %), full log:
    "?" 64.9   en 17.2   es 17.3   fr 11.8   sr 11.6   de 11.7   ru 15.5   uk 9.1
    sv  7.5   it  8.7   ...   th 0.3   zh 0.0   bn 0.1   el 0.4
  Top-5,000 head (the most-mentioned, most user-visible) is far worse: en 39.7%,
  "?" 71.1%. (The earlier 8.7% global was the 5k-capped sample; 16.2% is the truth.)

16.2% of logged keywords — and 39.7% of the most-mentioned English keywords (e.g. "AI"
stored as el, signature 4,589 en / 2,669 "?" -> hidden) — are language-mismatch
flagged. This matters twice:
  - It is a first-order data-quality problem in its own right, worst exactly where it
    shows: the top-mentioned keywords. (The rest of the head is clean: ~0.5% hidden,
    0.4% digit-heavy.)
  - It is a PREREQUISITE for multilingual lemmatization: a per-language lemmatizer
    keyed on a wrong language tag applies the wrong language's rules. Lemmatize/group
    by the SIGNATURE-MAJORITY language, not the stored tag, or fix langdetect for short
    strings first — otherwise L1 amplifies a 9-40% error.

Related: the "?" unknown bucket is not exotic-language content — it is English web
chrome that langdetect could not place and that "?" (no_stoplist) does not filter:
top "?" terms are email, link, click, privacy, newsletter, app, view, service, gov,
department, tracked. Routing "?" through the English stoplist + a boilerplate list is
a concrete, high-yield cleanup (engine report: "?" holds 30,903 keywords).


## E. The growth curve in context

beta = 0.7619 (Heaps), r2 = 0.9988 — vocabulary is saturating, which is healthy, but
only mildly: the minting rate fell from 87.96 to 73.54 new keywords per 1,000 words,
a modest drop that still reads as junk-influenced (a clean corpus bends harder). Two
caveats on reading it:
  - The corpus more than DOUBLED in the last ~25 days: 2026-05-31 = 416,475 keywords /
    7.53M tokens / 26,906 articles -> 2026-06-25 = 944,942 / 15.72M / 62,538. A spike
    this size means a fresh, un-curated intake dominates the latest vocabulary; expect
    the digit/code backlog (B2) and the langdetect noise (D) to be concentrated in it.
    A re-index now pays off precisely because so much was just ingested.
  - The growth file totals 944,942 keywords vs the engine report's 977,139 — different
    methods (growth reads keyword_mentions only, ordered by article date; the engine
    counts all rows incl. 5,863 zero-mention orphans). They are not meant to match.


## F. Re-prioritized roadmap (evidence-ranked; supersedes v2 Section 9 ordering)

The v2 layer DESIGN (L0-L3) stands. What changes is the ORDER and the expected yield,
now that the data shows where the bloat actually is.

  P1  RE-INDEX to flush the stale backlog.  Cost: low (no new dependency).
      Yield: high. Clears mostly_digits (7,171/60k) + code_token (3,087/60k) that the
      §2.5/§2.6 filters already drop, the 151 elision_contaminated, and lets the 5,863
      zero-mention orphans be pruned. This is the single highest yield-per-effort move
      and it must precede any tooling decision, because it changes the noise baseline
      everything else is measured against. v2's L0 possessive collapse rides along.

  P2  Fix language assignment (Section D).  Cost: low-medium.  Yield: high on the head.
      Group/lemmatize by signature-majority language; surface language_mismatch as a
      review queue; give "?" the English stoplist + boilerplate filter as fallback.
      Prerequisite for P3 to be safe.

  P3  Add lemmatization (v2 L1), POS-aware or denylisted (Section C).  Cost: medium.
      Yield: medium head (20.7% of en single-token terms share a lemma on the full
      log, 32.6% on the dense head; captures irregulars the rules cannot), high tail (compresses the 692k single-article
      keywords) — but tail gain is gated on P2. Ship simplemma (L1b) + the Section C
      mislemma denylist; only pursue L1a (spaCy tagger) if provenance shows spaCy is
      actually deployed (B4). Keep verbs OFF for entity names.

  P4  Fix broken multilingual extraction.  Cost: medium.  Yield: medium.
      The two "unsegmented" languages are NOT equally broken (I read their content):
      th (8,661) is genuinely broken — Thai has no inter-word spaces, so without a
      segmenter the tokenizer emits mid-word fragments (e.g. างประเทศ, a cut of
      ต่างประเทศ "foreign country"; นเท, ระบ, คอล are fragments). Urgent: add a Thai
      segmenter (pythainlp / ICU) or stop minting th keywords.
      zh (17,021) is DEGRADED, not garbage — the samples are plausible multi-character
      terms (新加坡 Singapore, 东南亚 Southeast Asia, 中小企业 SME, 美国股市 US-stock-
      market), but compounds aren't split (美国股市 should be 美国 + 股市). Lower
      priority: a jieba/ICU segmenter improves granularity; current output is usable.
      The no_stoplist set (55,058 keywords across ?, vi, lt, lv, ms, ko, is, mr, kn,
      ml, my) leaks function words; add stoplists. All higher-yield than chasing more
      English morphology.

  P5  Entity linking to QIDs (v2 L3, OpenTapioca).  Cost: high.  Yield: high but
      strategic. Given A3 (entities are acronym-only today), this is a NET-NEW
      capability and the principled long-term answer for the journalism core. Sequence
      after P1-P3; confirm whether the deployment even runs spaCy first (B4).

  P6  Seed the baseline/Item AC tagging (v2 L2 curation surface).  Cost: medium.
      Yield: compounding. tag_coverage is 0% of top-500; populate from a dated
      Wikidata P31 snapshot (CC0) so known keywords arrive pre-tagged, and route P3's
      lemma proposals and P2's mismatch queue INTO this human-review loop rather than a
      parallel store. This is where v2's L2 Lexeme map and the mislemma denylist live.

One-line sequencing rule: re-index (P1) before you measure anything; fix language
(P2) before you lemmatize (P3); link entities (P5) only after confirming the extractor.


## G. Provenance and verification

All figures computed at 2026-06-25 from the uploaded artifacts:
  - composition / mention distribution / noise / coverage / language status:
    oo-keyword-engine-20260625(1).json (corpus-wide; bounded 60k scan for noise).
  - selftest PASS set incl. plural_family_merge / equivalence_ring / baseline_tag:
    oo-keyword-selftest-20260625(1).json and ...20260624(1).json.
  - Heaps beta / minting rate / the 25-day doubling: oo-keyword-growth-20260625.json.
  - language-mismatch 16.2% global / 39.7% en-head / 17.2% en-full, hidden 0.5%,
    0.8% cross-file overlap, per-language mismatch table, zh/th content, the "?"
    boilerplate sample: computed across all 48 files of the COMPLETE export
    oo-keyword-log-20260625(1).zip (206,850 rows). This supersedes the first zip
    oo-keyword-log-20260625.zip, which was capped at top-5,000 rows/language and
    truncated after "sr" — its 8.7% global figure was a cap artifact, now corrected.
  - lemma-merge 20.7% full / 32.6% head / 77.0% mentions / 13-of-1018 danger groups /
    the wrong-merge examples / the denylist seed: simplemma 1.2.0 (lang=en) over the
    en.json visible single-token
    terms, by me, just now. This is the one place I produced new measurements rather
    than reading a field; the method is in Section C so you can reproduce it.

Citation/no-fabrication posture unchanged from v2: no new bibliographic identifiers
were added; the only DOIs/arXiv IDs remain the ones v1 verified. The denylist tokens
are derived from YOUR data, not invented.
