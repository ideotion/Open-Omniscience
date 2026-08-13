# Internet-session prompt — Governments data, aggregates and blocs (2026-08-07)

The build sandbox cannot reach `api.worldbank.org`, `oecd.org`, `imf.org` or
`afdb.org` (403 / HTTP 000), so every fact below that the Governments work needs was
**deliberately left unverified rather than guessed**. This file is the prompt to hand a
networked session, and the format its answer should come back in.

**How to use it:** copy everything between the two rules into a fresh
internet-connected session, then paste the whole answer back here. Nothing in the answer
gets merged without being re-read against the code first.


> **STATUS 2026-08-07 — partially answered; re-run only the open tasks.**
>
> A networked pass returned Tasks 1, 1b and most of 2, and they are MERGED: the aggregate
> table is now the complete live set of 78, and the seven World Bank regions are populated
> with all 217 economies. Three of its findings were corrections to things this repo had
> asserted from documentation, each invisible on inspection — a row for `FCS`/`F1` that
> does not exist, a MEA rename that had moved Afghanistan and Pakistan out of South Asia,
> and the premise that `countryiso3code` is empty for aggregates, which is false.
>
> **Still open, and the reason to run this again:** Task 3 (all 36 indicator codes — the
> pass was blocked from constructing those URLs), Task 4 (bloc membership with dates, which
> is the one thing still holding the bloc lens empty), Task 5, Task 6, and the AfDB/UNECA
> half of Task 7. Task 2 has two loose ends: confirm `page=2` against a cache-disabled
> request, and read the tail of page 1.
>
> Task 4 is worth its own session. Several hundred member-rows each wanting a dated source
> URL, and a partial roster is more dangerous than none: an empty registry fails visibly,
> a half-filled one computes.

> **STATUS 2026-08-13 — re-run #2. Tasks 3, 4 and 5 are STILL OPEN, and Task 3 will NOT
> close in a chat session with this tooling. Do not simply run this again.**
>
> What it closed: Task 2's `page_meta` question, verbatim `{"page":1,"pages":18,
> "per_page":1000,"total":17490,"sourceid":"2","lastupdated":"2026-07-13"}` — note the two
> keys this prompt never asked for, and that `lastupdated` is a publisher-stated vintage.
> On ordering it established one thing and over-claimed another. SUPPORTED: within a run of
> entries the sort is alphabetical **by `country.value`**, not by any code — `EAS` ("East
> Asia & Pacific") precedes `EAP` ("… (excluding high income)"), so **nothing in the ingest
> may sort by `id` or `iso2Code` and expect a match**. NOT SUPPORTED: the pass also wrote
> that aggregates are "interleaved among real countries rather than blocked separately", and
> its own observed page 1 refutes that — it runs AFE, AFW, ARB, CSS, CEB, EAR, EAS, EAP,
> TEA, which is nine aggregates and no countries, while `"Afghanistan"` sorts *before*
> `"Africa Eastern and Southern"` and would have led the page if one sort spanned everything.
> So the aggregates arrive as a leading BLOCK. Treat interleaving as unverified; it changes
> where a page boundary falls, which is the one thing the pagination work depends on. It
> independently re-derived Task 7's `AFR`/`A9` finding (already merged) and confirmed the
> `countryiso3code`, `FCS`/`F1` and MEA corrections. Two facts worth having: `per_page` is
> a STRING on the `/country` call and an integer on the indicator call, and
> `"Sub-Saharan Africa "` / `"Latin America & Caribbean "` carry a trailing space in
> `name` — anything keyed on the NAME silently misses.
>
> **Why Task 3 is blocked, structurally.** This tooling only fetches a URL that already
> appeared verbatim in a prior result or in the pasted prompt, so a URL built by
> substituting into a `{CODE}` template is REFUSED outright. Worse, varying the query
> string on a URL that *was* in the prompt did not refuse — it silently served the prompt's
> version and reported it as the answer. See absolute rule 5, which exists because of it.
>
> **The fix is not a better prompt.** Add `api.worldbank.org` to the build sandbox's egress
> allowlist and the 36 checks become a ten-line loop, `fetched` at the strongest tier with
> no transcription step — and the same session also settles whether `AFR`/`A9` carries any
> observations and whether `page=2` works. Failing that, any shell with plain outbound
> HTTPS does it. A third chat re-run is the one route already known not to work.

---

You are researching **public statistical data sources** for a local-first, offline
investigative-journalism tool. Your entire output will be pasted into a coding session
that will turn it into committed configuration, so precision matters more than coverage.

## Absolute rules

1. **Never fabricate an identifier.** Not a country code, not an indicator code, not an
   endpoint, not a date. If you cannot verify something, write `UNVERIFIED` and say what
   you tried. A missing row is free to fix later; a wrong row silently corrupts a
   published figure and nobody downstream can detect it.
2. **Mark every row's verification tier** — no defaults, because a default silently
   claims the stronger tier for whatever you forgot to think about:
   - `fetched` — you actually loaded the URL/API and read the value off the response.
   - `search-verified` — you found it stated on the publisher's own page but did not
     load the machine endpoint itself.
   - `lead` — plausible, unconfirmed. Ships disabled.
3. **Quote the URL you read** for each fact. "The World Bank documents this" is not a
   source; `https://api.worldbank.org/v2/country?format=json&per_page=400` is.
4. Where a figure is a **count of things that changes** (how many codes, how many
   members), give the count **and the date you read it**.
5. **Confirm the URL you were actually served, not the one you asked for.** A fetch tool
   may silently REWRITE the request. On 2026-08-13 this happened three times: asking for
   `…&page=2` returned `…&per_page=1000` — page 1 — with no error and no warning, and the
   pass came within one check of reporting "page=2 returns page 1, pagination is broken at
   the publisher": confident, wrong, about someone else's API, and undetectable downstream.
   So for every `fetched` row, read the response's own `destination_url` (or equivalent) and
   compare it to what you requested. If they differ, the tier is **not** `fetched` — it is
   `UNVERIFIED`, and say what you were served instead. This rule outranks the others in
   practice, because a silently-substituted response is the one failure that arrives wearing
   the strongest tier.

## Task 1 — World Bank aggregate codes (highest value)

Fetch `https://api.worldbank.org/v2/country?format=json&per_page=400`.

Every entry whose `region.value` is exactly `"Aggregates"` is a non-country aggregate.
For each one report: `id` (alpha-3), `iso2Code` (alpha-2), `name`.

Return the **complete** list as a table. Then answer explicitly:

- How many aggregates are there in total, as of today?
- What are the alpha-2 codes for these specific groupings, which a previous offline pass
  could **not** tell apart and therefore omitted entirely:
  `LDC` (Least developed countries: UN classification), `IBT` (IDA & IBRD total),
  `EAR` (Early-demographic dividend), `LTE` (Late-demographic dividend),
  `PRE` (Pre-demographic dividend), `PST` (Post-demographic dividend).
- Confirm or correct each of these pairs, which were asserted offline from documentation
  knowledge and have **never been read off a live response**:

  | alpha-3 | alpha-2 | name asserted offline |
  |---|---|---|
  | WLD | 1W | World |
  | HIC | XD | High income |
  | UMC | XT | Upper middle income |
  | LMC | XN | Lower middle income |
  | LIC | XM | Low income |
  | MIC | XP | Middle income |
  | LMY | XO | Low & middle income |
  | EAS | Z4 | East Asia & Pacific |
  | ECS | Z7 | Europe & Central Asia |
  | LCN | ZJ | Latin America & Caribbean |
  | MEA | ZQ | Middle East & North Africa |
  | NAC | XU | North America |
  | SAS | 8S | South Asia |
  | SSF | ZG | Sub-Saharan Africa |
  | AFE | ZH | Africa Eastern and Southern |
  | AFW | ZI | Africa Western and Central |
  | EUU | EU | European Union |
  | EMU | XC | Euro area |
  | OED | OE | OECD members |
  | ARB | 1A | Arab World |
  | CEB | B8 | Central Europe and the Baltics |
  | IDA | XG | IDA total |
  | IDX | XI | IDA only |
  | IDB | XH | IDA blend |
  | IBD | XF | IBRD only |
  | HPC | XE | Heavily indebted poor countries (HIPC) |
  | SST | S1 | Small states |
  | PSS | S2 | Pacific island small states |
  | CSS | S3 | Caribbean small states |
  | OSS | S4 | Other small states |
  | FCS | F1 | Fragile and conflict affected situations |

  Flag any row that is **wrong**, and any real aggregate **missing** from it.

### Task 1b — and the region of every COUNTRY, from the same response

The same call carries `region.value` for each real country ("Europe & Central Asia",
"Sub-Saharan Africa", …). Report it as a plain `alpha-2 → region` list for every entry
whose region is **not** "Aggregates".

This is a separate deliverable from the aggregate list above and it populates a
different thing: the World Bank *region* lens, which is registered in the app but empty.
Do not substitute continents for it — **World Bank regions are not continents.**
"Sub-Saharan Africa" excludes Egypt, Libya, Tunisia, Algeria and Morocco, which the Bank
files under "Middle East & North Africa", so the two lenses give genuinely different
answers for Africa and both are wanted.

Also report which `incomeLevel.value` and `lendingType.value` each country carries, if
they come back in the same response — they cost nothing extra here and they are the
membership of the income-group aggregates in Task 1.

## Task 2 — the shape of a paginated response

Fetch page 1 of a real indicator over every economy:
`https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CD?format=json&per_page=1000`

Report:

- The **entire `page_meta` object** (element `[0]`) verbatim — `page`, `pages`,
  `per_page`, `total`, and any other keys.
- How many observations are in element `[1]`.
- **Which economies appear on page 1, in order** (just the `countryiso3code` /
  `country.id` sequence, deduplicated). This settles an open question: with pagination
  broken, exactly ONE economy survived into the tool's store, and it is not yet known
  whether page 1 is one economy's full history or an interleaving of many.
- Confirm whether `countryiso3code` is **empty** for aggregate rows while populated for
  real countries. (The tool relies on this indirectly; if it is not true, say so.)
- Fetch page 2 as well and confirm `&page=2` is the correct parameter name.

## Task 3 — verify all 36 indicator codes

Each of these was **search-verified but never fetched**. A wrong code fails silently as
"no data" — which is indistinguishable from a country genuinely not reporting.

For each, fetch
`https://api.worldbank.org/v2/country/FRA/indicator/{CODE}?format=json&per_page=5`
and report `OK` (rows returned) or `DEAD` (empty/error), plus the indicator's official
name from the response so the label can be checked against ours.

```
NY.GDP.MKTP.CD  NY.GDP.PCAP.CD  NY.GDP.MKTP.KD.ZG  NY.GDP.MKTP.PP.CD
NY.GDP.PCAP.PP.CD  NE.TRD.GNFS.ZS  BX.KLT.DINV.WD.GD.ZS  FP.CPI.TOTL.ZG
SP.POP.TOTL  SP.POP.GROW  SP.URB.TOTL.IN.ZS  SP.DYN.TFRT.IN
SP.DYN.LE00.IN  SH.DYN.MORT  SH.STA.MMRT  SH.MED.PHYS.ZS
SH.XPD.CHEX.GD.ZS  SL.UEM.TOTL.ZS  SL.TLF.TOTL.IN  SL.TLF.CACT.ZS
SE.ADT.LITR.ZS  SE.XPD.TOTL.GD.ZS  SE.PRM.ENRR  SE.SEC.ENRR
EG.ELC.ACCS.ZS  EG.FEC.RNEW.ZS  EN.ATM.CO2E.PC  AG.LND.FRST.ZS
IT.NET.USER.ZS  IT.CEL.SETS.P2  MS.MIL.XPND.GD.ZS  GC.NLD.TOTL.GD.ZS
GC.DOD.TOTL.GD.ZS  GC.TAX.TOTL.GD.ZS  GC.REV.XGRT.GD.ZS  SI.POV.GINI
```


**Also report, for two of them, whether the value is what we think it is**, because both
look like errors and are believed correct:

- `IT.CEL.SETS.P2` — is the unit "per 100 people" and can it legitimately exceed 100?
- `SE.SEC.ENRR` — is this **gross** enrollment, and does it legitimately exceed 100%?

## Task 4 — bloc membership, with dates

For each bloc below, give the **current member list** and, per member, the **date it
joined** and (if applicable) **left**, each with the URL you read it from.

`BRICS · G7 · G20 · NATO · European Union · African Union · ASEAN · Mercosur ·
CARICOM · Gulf Cooperation Council · OPEC · Commonwealth of Nations ·
Organisation internationale de la Francophonie`

These are exactly the thirteen groups the app has registered and left empty, so a
roster for any one of them is directly usable and a roster for anything else is not
(yet) — if a bloc is easy to source and not on this list, mention it rather than
researching it in depth.

This is time-critical data and the reason the dates matter is worth stating: a bloc
figure computed with today's roster over a 1995 series is wrong in a way no reader can
detect. So:

- **Never infer a date to make a series continuous.** If you cannot source an accession
  date, write `joined: UNVERIFIED` and say so. That is a usable answer; a guessed date
  is not.
- Pay particular attention to the recent changes: BRICS' 2024 expansion (Egypt,
  Ethiopia, Iran, UAE — and confirm the exact status of Saudi Arabia, which was invited
  and whose membership has been reported ambiguously) and Indonesia in 2025; NATO's
  Finland (2023) and Sweden (2024); the UK leaving the EU (2020).
- Note any member whose membership is **suspended** rather than ended (several African
  Union members have been), because that is a third state and neither `joined` nor
  `left` expresses it. **A suspension is an EPISODE with a start and possibly an end**, and
  a member may have more than one: Mali was suspended in 2012 and reinstated in 2013, then
  suspended again in 2021; Egypt was suspended in 2013 and reinstated in 2014. Give every
  episode you can source, each with its own dates and URL. (The registry was carrying a
  single `suspended_from` date, which made suspension permanent once set — Egypt read as
  suspended in 2026. Corrected 2026-08-13, before this roster was written, so the format
  below is what it now stores.)
- **Saudi Arabia in BRICS is not a research gap to close with a better search.** It was
  invited in the August 2023 Johannesburg declaration, members themselves have reported its
  accession inconsistently, and BRICS has no accession instrument that creates a citable
  date. `joined: UNVERIFIED` with a note is the permanent, correct answer — not a to-do for
  a later pass.

Format each member as the four fields the registry actually stores, so the answer can be
transcribed without interpretation. Omit a field that does not apply; write `UNVERIFIED`
where you looked and could not source it.

```
BRICS
  source: <url for the roster itself>
  br  joined 2009-06-16                          source <url>
  ru  joined 2009-06-16                          source <url>
  eg  joined 2024-01-01                          source <url>
  sa  joined UNVERIFIED  — invited 2023, accession status reported ambiguously; <url>

AFRICAN UNION
  source: <url>
  eg  joined 2002-07-09  suspended 2013-07-05..2014-06-17            source <url>
  ml  joined 1963-05-25  suspended 2012-03-23..2013-10-28            source <url>
                         suspended 2021-06-01..                      source <url>
  ma  joined 2017-01-30  left 1984-11-12 rejoined 2017-01-30 — see note   source <url>
```

Use lowercase ISO 3166-1 alpha-2 codes. A suspension is written `suspended START..END`,
with the END left blank if it has not ended (`2021-06-01..`), and **one line per episode** —
Mali above shows two. Do not merge two episodes into one range: the gap between them is a
period when the member was NOT suspended, and merging asserts the opposite.

A suspension is a **third state**: it is neither `joined` nor `left`, and a suspended member
is still a member, so please do not resolve it into either — the app models it separately for
exactly this reason. If you can establish that a suspension ended but cannot date the end,
say that in a note rather than leaving the range open; an open range means "still suspended
today", which would be a false claim about a current state.

If a country left and later rejoined (Morocco and the OAU/AU is the clean example), say
so in a note rather than collapsing it to one date range; the registry can hold the
history but only if the answer distinguishes the two spells.

## Task 5 — publishers of bloc-level data

For each bloc in Task 4, does the bloc **itself publish** aggregate statistics, or would
a figure have to be computed from its members? Name the publication or API where one
exists. Specifically:

- The **BRICS Joint Statistical Publication** — an annual volume from the members' own
  statistical offices. Does the latest edition exist, where, and in what format
  (PDF / Excel / API)?
- **NATO defence expenditure** — NATO publishes this directly; find the machine-readable
  form if there is one.
- **OPEC** Annual Statistical Bulletin — format and access.
- **ASEANstats**, **GCC-Stat**, **CARICOM** statistics — do they expose an API?

## Task 6 — OECD and IMF SDMX

The tool has an SDMX-JSON parser written against **version 2.1**. It is believed OECD
serves **1.0** and IMF serves **3.0**, which would mean the parser does not cover them.

- Confirm the actual SDMX message version each currently serves.
- Give one **working example URL** per publisher that returns a small JSON dataset.
- Paste the **first ~60 lines** of each response so the parser's assumptions can be
  checked against the real shape rather than against documentation.

## Task 7 — continental Africa

The World Bank has **no continental-Africa aggregate** — its "Sub-Saharan Africa"
excludes Egypt, Libya, Tunisia, Algeria and Morocco, which sit in "Middle East & North
Africa". So a continental figure must come from another publisher or be computed.

- **AfDB** (African Development Bank) data portal — is there an API? What does it cover?
- **UNECA** — same question.
- Does either publish an **Africa-wide** aggregate directly?

---

## Answer format

Please return one section per task, in order, each row carrying its verification tier
and source URL. Where something could not be verified, say so explicitly — an honest
`UNVERIFIED` is more useful here than a confident guess, because the guess is the thing
that survives review and reaches a reader.
