# Research prompt 1 — open multilingual translation & synonym sources

**Read `00_SHARED_RULES.md` first and follow it exactly, especially Rule 0 (probe the
hosts before doing any work) and Rule 2 (fact vs inference).**

## Context

Open Omniscience is a GPL-3.0, local-first, fully-offline news-analysis app. It already
ships a cross-language keyword dictionary: **698 concept "rings", ~22,000 members,
covering exactly 12 UI languages** — `en fr de es pt ru ar zh ja hi bn id` — generated
from **Wikidata labels + aliases (CC0)** and hand-vetted, in
`configs/keyword_rings_generated.yml`. A ring looks like:

```yaml
- id: drought
  qid: Q43059
  members: ["en:drought", "fr:sécheresse", "de:dürre", "es:sequía", "ru:засуха",
            "ar:جفاف", "zh:干旱", "ja:干ばつ", "hi:सूखा", "bn:খরা", "id:kekeringan"]
```

**The ceiling is coverage: 698 concepts against ~250,000 distinct corpus terms.** We want
to grow that, and to add a *separate* within-language synonym tier.

## What to find out

### A. Can we do better without leaving Wikidata? (answer this first)

Wikidata is CC0 and already in our pipeline, so anything it can supply costs no new
licence decision. Establish, with evidence:

1. **Wikidata Lexemes** — what lexical data actually exists (senses, forms, translations),
   **per language for our 12**. How many lexemes exist per language? Is coverage real or
   nominal for non-European languages? Is there a standalone dump, and how big?
2. Practical ways to select good ring *seeds* at scale from Wikidata itself — is there a
   usable notion of "concepts a news corpus would contain" (sitelink counts, class
   membership, statement counts)? Cite what you actually found.
3. Any known **quality traps** in using labels+aliases as translations. We have been
   burned twice already: seeds resolving to bands, journals, films, video games and
   Wikidata meta-classes sharing a concept's name. What do others do about this?

### B. Alternative open sources — licence, coverage, size

For each, report the licence **read from the artefact** (Rule 3) and the offline
viability (Rule 4):

* **PanLex** — believed CC0; verify. Coverage for our 12 languages. Distribution format
  and size. Quality: is it curated, or aggregated from sources of varying reliability?
* **Open Multilingual WordNet / Open English WordNet** — **licences vary per language
  pack**; report per pack for our 12. Coverage. Whether synsets are usable offline as
  plain data.
* **Wiktionary via Wiktextract / kaikki.org** — confirm the exact licence and how
  attribution + share-alike would apply to a *derived, filtered* data file bundled in a
  GPL-3.0 repository. Report the full-dump size and whether a 12-language filtered
  extract could plausibly fit under 100 MB per file.
* **ConceptNet** — licence, and whether its multilingual edges are useful for translation
  as opposed to loose relatedness.
* **Unicode CLDR** — for calendar/month vocabulary specifically (we have a concrete
  month-name problem; see prompt 2).
* **Anything else you find** that is genuinely open, offline-shippable, and multilingual.
  Explicitly exclude BabelNet (research/non-commercial licence) and say why if you
  mention it.

### C. Synonyms are a different, riskier problem — treat them separately

Cross-language equivalence (`climate`↔`climat`) is near-identity. Within-language
synonymy is not: synsets and dictionary "synonyms" sections routinely mix true synonyms
with **hypernyms** (`car`↔`automobile` is fine; `car`↔`vehicle` loses precision).

Find out how open-source systems distinguish these, and whether any source gives a
**usable synonym/hypernym distinction** rather than one undifferentiated bag. If none
does, say so — that is a finding, and it decides whether we ship a synonym tier at all.

### D. Prior art

How do open-source multilingual search/NLP systems solve *"query in one language, match
documents in another"* **without** a neural model? We care about the data layer and the
technique, not about products. Anything with a permissive licence and an offline story is
interesting.

## Deliverable

`docs/research/keywords/TRANSLATION_SOURCES_<date>.md`, in the format of
`00_SHARED_RULES.md`. A comparison table (source · licence + evidence URL · coverage of
our 12 languages · raw size · filtered-size estimate · offline-viable y/n · verification
tier), then per-source detail, then the three closing sections the shared rules require.

**Do not write any code and do not modify the app.** This is a research pass. If a host
is blocked, report that per Rule 0 rather than working around it.
