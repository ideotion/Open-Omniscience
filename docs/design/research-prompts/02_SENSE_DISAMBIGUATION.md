# Research prompt 2 — the "April problem": open sense inventories & disambiguation

**Read `00_SHARED_RULES.md` first and follow it exactly.**

## The problem, concretely

Open Omniscience extracts keywords from news articles. Its keyword identity is a single
**normalized string** — one database row per term, globally, carrying one language tag.

That model cannot represent a word with several meanings. **April** is a month, a given
name (April Ryan, the White House correspondent), and part of organisation names (the
April 6 Youth Movement). All three are one row.

The app's current answer is a blunt one: month names sit in a **language-agnostic
stopword list**, so they are dropped at extraction. Measured consequence — the keyword
engine cannot see:

| lost | because |
|---|---|
| the planet **Mars**, Mars rover, Mars Inc. | `mars` is French for *March* |
| the **March** on Washington, a climate march | `march` is an English month |
| Theresa **May** · **April** Ryan · **Avril** Haines · **August** Landmesser | same pattern |

We have ruled that the target model is **sense-level identity keyed on Wikidata QIDs**
(April-the-month = Q118, April-the-given-name = a different QID). We need to know what
open, offline-shippable data and technique exist to get there — and what the honest
failure modes are.

## What to find out

### A. Open sense inventories (the "homonym dictionary")

We need: **surface form → the set of candidate senses it could denote**, for our 12
languages (`en fr de es pt ru ar zh ja hi bn id`), shippable offline as a data file.

1. **Wikidata as its own homonym dictionary.** Our generator already fetches labels and
   aliases per QID — so "which *other* items carry this same label" is data we may
   already be retrieving. Establish: is there a clean way to build a surface-form →
   {QID} index from Wikidata (disambiguation-page items, label/alias indexes, a dump
   field)? What is the realistic size for 12 languages? **This is the option we most want
   to work, because it is CC0 and already in our pipeline.**
2. **Other open sense inventories** — WordNet synsets, Wiktionary sense sections,
   Wikipedia disambiguation pages, anything else. Licence per Rule 3, size per Rule 4.
3. How do these inventories represent the *kind* of a sense (month vs person vs
   organisation)? We need that distinction, not just "there are 3 senses."

### B. Disambiguation technique WITHOUT a neural model

`torch` / `onnx` / `transformers` are banned from this project's core (Rule 5). So:

1. What **non-neural** entity-linking / word-sense-disambiguation approaches are used in
   open-source systems? (String + context + prior-probability methods, gazetteer +
   co-occurrence, graph methods over an inventory.) Name real projects and their licences.
2. What **accuracy** do those approaches actually report, and on what benchmarks? Be
   precise and cite. We would rather ship no disambiguation than a silently-wrong one, so
   a realistic error rate is decision-relevant.
3. What is the standard way to represent **"could not decide"**? We require an unlinked
   mention to stay fully usable — never dropped for want of a sense. Do open systems model
   an explicit NIL/unlinked sense, and how?
4. Is there an open **prior-probability table** (how often a surface form denotes each
   sense) derivable from a CC0/permissive source? A prior alone plus a confidence floor
   may be most of the value at a fraction of the complexity.

### C. The specific sub-problem: month names vs. content

Narrower and immediately actionable. In a multilingual news corpus, month names are
simultaneously high-frequency **dateline noise** and legitimate **content** (Mars,
the march, April Ryan).

1. How do open-source news/IR pipelines separate the two? Is the standard answer to let a
   **date parser consume the span** and keep whatever it does not claim? (That is our
   current hypothesis — we have a multilingual date extractor already.)
2. What **recall** do open multilingual date parsers actually achieve on news text
   (`dateparser`, `duckling`, HeidelTime, others)? Cite numbers. This decides how much
   dateline noise would leak back if we stopped blanket-banning month names.
3. Does **Unicode CLDR** give a clean, complete, per-locale month-name list (including
   abbreviations and inflected forms — Slavic and Arabic matter here) that we could use to
   scope the problem per language instead of globally?

### D. Prior art on the whole shape

Any open project that has solved *"one surface form, several senses, several languages,
offline"* — how did it model identity? We are especially interested in schemas that keep
the unlinked case first-class, and in anyone who tried this and **reported that it did not
work**. Negative results are as valuable as positive ones here.

## Deliverable

`docs/research/keywords/SENSE_DISAMBIGUATION_<date>.md` in the shared format. Lead with
section A (the inventory question is what unblocks us), then B, C, D.

End with your judgement, clearly marked as judgement, on: **is non-neural sense
disambiguation good enough to be worth shipping, or is an honest "this term is ambiguous,
here are the senses, you choose" surface the better answer?** We would genuinely rather
hear "it is not good enough" than be told what we hoped to hear.

**Do not write any code and do not modify the app.**
