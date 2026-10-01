# A keyword's kind comes from a source (R97, `RC05`)

**Status:** design, before any code. Ruled 2026-09-30 15:34 UTC («1=a (but we should make plans
for autonomy and complete independence»), recorded as `R97`; refined at 17:06 UTC by `R106` (build
all the no-network parts, the offline resolver is measured before it is promised), `R107` (NO
hand-set kinds) and `R108` (which edition). Thread «Keyword working session». Section 5 is the plan
the maintainer's condition asks for; section 7 records how its three questions were answered.

## 1. What is ruled

A keyword's kind (person, organisation, place) is given by a SOURCE and carries that source and
its date. The source is Wikidata's «instance of» (`P31`) reached through the entity spine (row
C, #1206). A keyword with no match stays «unknown» and is never guessed. About 300 matches are
checked by hand as a stratified sample, so the precision is a measured figure. Ambiguous names
are listed for review. Wikidata lookups go through the existing consent window (invariant #14),
the head of the list first. The 64,910 old AI suggestions are not rebuilt; no review list is
built for AI guesses.

## 2. What exists

* `Keyword.is_entity` / `entity_type` / `extractor`: a **labelled-by-X assertion** by the
  extractor (baseline, spaCy, an LLM), «never ground truth» in the model's own comment. It stays
  as it is and is not what this ruling adds; a surface shows the sourced kind first and never
  presents an extractor label as sourced.
* `src/entities/`: `spine.py` (name → QID through the generated rings, refusing several-item
  names), `items.py` + `wikidata_items.py` (the consented, R8-gated `wbgetentities` fetch and the
  `wikidata_items` cache with `P31`, `P17`, `P625`, `P571`, riding backups since #1257), `places.py`
  (the gazetteer).
* **The measured limit:** `configs/keyword_rings_generated.yml` holds **684 rings with a QID**,
  concepts like `government` (Q7188), not names. So the rings cannot type the head of a corpus's
  names; a NAME → QID matcher is the missing piece.

## 3. Design

**Store: one new table, not columns on `keywords`.** `keyword_kinds(keyword_id, kind, source,
source_id, as_of, note)`, one row per (keyword, source), so several sources can disagree and
both are kept. Reasons: `keywords` is rewritten by the corpus-sized migrations D33 fuses, and a
new table needs no rewrite; provenance is per row; the table rides backups with the same
keep / discard / reversible-swap rules as the rest (R61, R71), so a restored install keeps its
kinds without the network. `kind` is a closed set: `person`, `organisation`, `place`, `other`
(the source says what it is and it is none of the three: a species, an event), and the row is
absent when there is no answer («unknown» is the absence, never a stored guess).

**Class table: a dated, shipped file.** `P31` gives a class QID (`Q5` human, `Q4830453` business,
`Q6256` country …); mapping a class to a kind needs the subclass tree (`P279`). The mapping is
`configs/wikidata_kind_classes.yml`: the class QIDs for each kind, the tree pre-computed at
build time, `as_of` stamped, registered in `configs/external_artifacts.yml` (the repo's own
rule for anything externally sourced). At run time `kind_from_claims(p31_qids)` is pure: a class
in exactly one kind gives that kind; classes in two kinds, or none, give «unknown» and the
disagreement is kept for the maintainer-side ambiguity report in the diagnostics (there is no in-app review list: `R111`; carrying R111 to this list is our application of R111). **No network is needed to turn a cached item into a
kind.**

**Matcher: exact Wikipedia titles, in batches.** A NAME → QID lookup by search would be one
request per name at R8's one request per ten seconds (about 360 names an hour, so 5,000 head
names are 14 hours). `wbgetentities` with `sites=enwiki&titles=A|B|…` resolves 50 exact titles
per request (about 18,000 names an hour at the same rate), follows redirects and never
fuzzy-matches. So: candidate names come from `article_entities` and capitalised keywords, most
cited first (the existing `_ENTITY_SCAN_CAP` discipline: a stated cap, never a silent
truncation); each is asked as an exact title in the keyword's own language edition when it is one of the twelve, English otherwise (`R108`); a disambiguation
page (`P31` = Q4167410) is refused as ambiguous and listed; a redirect is followed and the
resolved title stated. A name that is not an exact title is «unknown», not searched.

**The sample check.** Stratified by language × frequency band (head, torso, tail), about 300
matches in total: each is judged against a few sentences of the articles that use the keyword and
the item's own description, and the verdict is stored with the sample. The report gives the
precision per stratum with a Wilson 95 % interval and the count of names the matcher refused,
so the figure a card may quote is measured, never a hope. It is a diagnostics member and a
reviewed document, not a score.

## 4. Phases (one PR each, each behind its own Opus review)

1. `wikidata_kind_classes.yml` + `kind_from_claims` (pure) + tests + the registry entry.
2. The `keyword_kinds` table (migration, models, backups keep / discard), and a read seam.
3. The matcher over the consent window (the «Go online?» window names the lane), with the
   coverage diagnostic first: how many of the top N names resolve, refuse or stay unknown.
4. The sample check and its report; the ambiguity list as a maintainer-side report in the diagnostics (`R111`: no in-app review screen exists, and users are never asked about stopwords; carrying that to the kinds ambiguity list is our application of the ruling's principle, not a separate maintainer ruling).
5. Surfaces show the kind with its source on hover (invariant #17); «unknown» is shown as such.

## 5. Plan for autonomy and complete independence (the maintainer's condition)

**Principle: the network only ADDS; nothing REQUIRES it, and nothing is lost when it is gone.**

* **T0, no network at all.** «Unknown» is a first-class answer; every surface works with no
  kinds. Boot makes zero calls (unchanged).
* **T1, local sources, no network.** The 684 shipped ring QIDs, the OSM gazetteer for places (row
  D, already local and ODbL-credited), the local `wikidata_items` cache, and any Wikipedia page the
  operator already follows (its QID is in the page data). **There is NO hand-set kind (`R107`):
  the maintainer ruled that kind attribution is optimised by us, not by users, and a wrong kind is
  fixed in the class table or the matcher, never overridden by hand.** Everything here works on
  an air-gapped machine.
* **T2, consented lookups, cached for good.** The matcher of section 3. Every answer is stored
  with source and date and rides backups, so a restored install has its kinds without the
  network, and re-asking is never needed for a name already answered.
* **T3, independence from any ONE source.** The store is source-agnostic (`source`,
  `source_id`), so a second source (a national authority file, a government registry the
  operator imports) is an additional row, never a rewrite. Wikidata is the first source, not
  the schema.
* **T4, offline resolution from a file the operator holds.** The same matcher can read a
  Wikidata dump extract the operator downloaded once through the existing dump lane, instead
  of the API: no network afterwards. It is the only tier that costs real work (a streaming
  reader of a very large file). `R106`: it stays in the plan and is MEASURED before it is promised;
  nothing in T0 to T3 depends on it.

Nothing in this plan shares data between installs (`R100`): each install resolves and stores its
own kinds; articles and kinds travel only through the operator's own backups.

## 6. What could go wrong, stated

* Wikipedia titles are mostly exact for people and organisations of the head and mostly absent
  for the tail, so coverage is high for the head and low for the tail. That is the honest
  shape, and the coverage diagnostic reports it before anything is built on it.
* A name that is an exact title but the wrong item (a namesake) is the error the sample check
  measures; ambiguous names go to the list, never guessed.
* Kinds of `other` (a species, an event) are kept because dropping them would look like
  «unknown» and invite a second lookup.

## 7. The three questions, answered (2026-09-30 17:06 UTC)

1. **How far should independence go?** `R106` = a: T0 to T3 now; the offline resolver (T4) stays in
   the plan and is measured before it is promised.
2. **The operator's own pin:** `R107` = b, **NO.** Kinds come only from sources. No screen
   (`R111` cancelled `R98`'s review screen) carries a control that sets a kind, and there is no `operator` source row.
3. **Which language edition asks the titles?** `R108` = a: the keyword's own language edition when
   it has one among the twelve, English otherwise.
