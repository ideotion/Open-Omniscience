# Growing the academic catalogue, comprehensively

**Status: a STRATEGY, not a change.** Written for the note on Q1109 = b (2026-09-15): *"we
should develop a strategy to comprehensively increase the list."* The brief that carries that
ruling is explicit that this document **decides nothing** — it is a plan to be ruled on, and
nothing in it has been built or run.

**What exists today.** `configs/academic_sources.yml` holds 622 peer-reviewed journals, 606
admitted by the 2026-09-11 ruling from the Stage A/B discovery pipeline and 16 moved in from
`official_sources.yml` on 2026-09-18 (Q1111 = a — they were tagged `research-institute` and
were in fact journals). Every row is feed-verified: its feed parsed, carried ≥3 dated entries
and was fresh within 120 days at verification time.

---

## 1. What "comprehensive" would have to mean, before any method is chosen

A list of journals can be large and still be badly skewed, and the skew that matters here is
the one the institutions review already named for a different list: **a pipeline calibrated on
one part of the world produces a catalogue that looks complete and is not.** So the target is
stated as coverage along axes we can actually measure, rather than as a row count:

| axis | why it is the axis | measurable today? |
| --- | --- | --- |
| **language** | An English-only scholarly catalogue is not a scholarly catalogue. The corpus already measures per-language coverage. | Yes — `Source.language`, and the corpus's own language mix |
| **region** | The Global South publishes a great deal of peer-reviewed work in regional platforms that Western indexes under-list. | Yes — `Source.region`, `country` |
| **discipline** | A catalogue that is all biomedicine has a shape, not a gap. | Partly — `tags`, and the corpus's keyword families |
| **access model** | Open-access journals are reachable; paywalled ones are largely not, and a catalogue that silently omits them is describing what we can fetch, not what exists. | **No** — nothing records it today |
| **publisher concentration** | The same failure Q1117 names for a CMS vendor: many rows behind one platform is one outage. | Partly — feed-path clustering, as the splice already does |

**The last two are the ones to build first**, because they are the two a bigger list would
make worse without saying so.

## 2. Four sources of rows, in the order their cost-to-value argues for

**(a) DOAJ — the Directory of Open Access Journals.** ~20,000 journals with an open API,
carrying language, country, subject and licence per journal. It is the single highest-yield
input available and it is explicitly open data. **Cost:** one bulk fetch under the network
consent, then Stage A feed verification per candidate — which is the expensive half, not the
listing. **Risk:** DOAJ's own inclusion criteria become ours by inheritance; that is a
judgement we would be importing, and it should be recorded as provenance (`via:doaj`) rather
than absorbed.

**(b) Regional platforms, deliberately before anything global.** SciELO (Latin America,
Iberia, South Africa), AJOL (Africa), J-STAGE (Japan), KoreaScience, CyberLeninka (Russian),
Redalyc (Ibero-America), ASEAN Citation Index. **This is the half that decides whether the
catalogue is comprehensive or merely big** — these platforms are where the non-English
scholarly record actually lives, and every one of them publishes machine-readable listings.
Doing DOAJ first and these "later" is how the skew gets baked in, so they are listed here as
peers, not as a follow-up.

**(c) The corpus's own citations.** Articles already collected cite journals; the citation
channel already promotes candidate sources. This finds journals the corpus demonstrably needs
rather than journals a directory happens to list, and it costs no new discovery run. It is
the smallest source of rows and the best-targeted.

**(d) OpenAlex / Crossref, as a cross-check rather than a source.** Their journal lists are
larger than anything above and largely without feeds. Their value is measuring what the
catalogue is MISSING — a denominator — not supplying rows.

## 3. The admission rule this would run under, unchanged

Every candidate goes through what already exists, and this strategy proposes no exception:

1. **Stage A** — feed verification (parses, ≥3 dated entries, fresh). Nothing judges what the
   outlet *is* here.
2. **Qualification** — the shipped source gate. Since Q1101 a `qualified` verdict admits the
   source to collection, under the admission audit, undoable.
3. **`restricted_namespace` and the content-integrity tiers** (Q1112 = b) — a trip blocks the
   splice absent a written override, never a silent drop.
4. **Bare identifiers** (Q1116 = a) — resolved at the polite rate or the row is declined.
   **A recorded, unruled inconsistency in the 16 rows just moved.** Q1111 = a said *move*
   them and said nothing about retyping them, so they arrived carrying
   `source_type: academic-research` and the tag `research-institute` — on rows named
   *Chilean Journal of Agricultural Research*, *Lebanese Science Journal* and
   *Helminthologia*. The docket (institutions B3) states plainly that these **are journals**,
   so the type is wrong on its own evidence. It was NOT corrected during the move, because
   correcting it is a second change nobody ruled on and a move is a bad place to hide one.
   It needs one line from the maintainer: retype the 16 to `scientific-journal` and drop the
   `research-institute` tag, or leave them as an honest record of how they shipped.

   Worth flagging: **`academic_sources.yml` today contains rows whose name is a bare Q-id**
   (`Q139990366` is its first entry). Those are exactly the rows Q1116 is about, and they are
   already shipped — so the resolver should be run over the EXISTING catalogue, not only over
   new candidates. That is a concrete, small first step and it needs no new ruling.

## 4. What a bigger list costs, stated before it is proposed

- **Collection load.** 622 → several thousand sources multiplies passes, bandwidth and Tor
  circuit use. The per-pass hardware budget (`machine_floor`) is the bound, and it is already
  the bound on Tor use; a larger catalogue makes each source's turn come round less often
  rather than making the app fetch more. **That is a freshness cost, and it should be measured
  before the list grows, not after.**
- **What a corpus statistic means.** The academic catalogue is separate from `sources.yml`
  precisely so that scholarly publishing does not silently change what a news-corpus figure
  describes. Growing it must not quietly merge the two.
- **Publisher concentration.** See §1. Adding 2,000 journals from three platforms is three
  points of failure wearing 2,000 names.

## 5. Proposed first steps, smallest first

1. **Run the Q1116 resolver over the existing 622 rows.** No ruling needed, no new data, and
   it fixes shipped rows named after identifiers.
2. **Record an access-model and publisher field**, so §1's two unmeasurable axes become
   measurable before the list grows rather than after.
3. **Measure the current 622 against DOAJ and OpenAlex** — a coverage gap report, no
   admissions. This produces the denominator §2(d) is for and costs one bulk fetch.
4. **Then** propose a first admission batch, regional platforms and DOAJ together, with the
   balance shift disclosed the way the Stage B splice report discloses it.

**None of this is a decision.** Steps 1–3 read and measure; step 4 is where a ruling would be
needed, and the numbers from 1–3 are what it should rest on.
