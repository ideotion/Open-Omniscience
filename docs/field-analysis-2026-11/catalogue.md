# Goal 5: the initial source catalogue

## Method

- **Catalogue on main, indexed by `(domain, feed_key)`** (`scripts/catalogue_index.py`). It uses the app's own
  `src/database/feed_key.py:feed_key` and the export masking `shown_feed_key`.
- **Files and counts:**
  - `sources.yml` 5,580
  - `academic_sources.yml` 622
  - `sources_spectrum.yml` 278
  - `legal_sources_generated.yml` 226
  - `markets_sources.yml` 112
  - `legal_sources.yml` 51
  - `official_sources.yml` 27

  That is 6,896 entries and 6,856 distinct keys.
- **Joined with each snapshot's source rows** (`scripts/catalogue_join.py`, `catalogue_health.py`,
  `catalogue_evidence.py`). 6,612 keys are source rows on every Linux instance. The other 244 are feed-less
  spectrum, markets and legal rows whose domain the seeder merges into another entry.
- **Snapshots:** 13 in all. The 4 current ones, Linux C and H2–H8 on 2026-11-14, and Windows on 2026-11-15.
- **Limit of the 2026-11-14 snapshots:** they list only sources that hold an article, so for those snapshots a key
  that is absent from the list is not evidence.

## 1. Catalogue health

**Per current instance** (class of each key; see the definitions in `scripts/catalogue_health.py`):

| class | Windows | Linux A | Linux B | Linux C |
|---|---:|---:|---:|---:|
| stored ≥ 1 article | 3,843 | 3,656 | 4,059 | 3,385 |
| disqualified by a re-check | 0 | 130 | 0 | 149 |
| no article, feed answered 200/304 | – | 497 | 428 | 570 |
| no article, no fetch ever recorded | – | 1,621 | 1,447 | 1,788 |
| no article, no feed | – | 708 | 678 | 720 |
| no article, class not exported (older Windows build) | 2,653 | – | – | – |
| not a source row | 360 | 244 | 244 | 244 |

**Collected share by file** (Linux A / B / C):
- `sources.yml`: 2,943 / 3,277 / 2,727 of 5,563 (49–59%)
- `academic`: 562 / 599 / 521 of 622 (84–96%)
- `official`: 25 / 27 / 23 of 27
- `spectrum`: 35 / 38 / 29 of 273
- `markets`: 23 / 33 / 18 of 111
- `legal`: 9 / 13 / 8 of 49
- `legal_generated`: 59 / 72 / 59 of 211

**Across all 13 snapshots:**
- 2,786 keys stored articles in all 13.
- **2,339 keys never stored a single article in any snapshot.** Their current Linux classes:

| never stored anywhere, Linux A/B/C class | keys | list |
|---|---:|---|
| no fetch recorded on any Linux instance | 1,311 | appendix B |
| no feed | 649 | appendix C |
| feed answered 200/304 on all three | 301 | appendix A |
| mixed (answered on some, no fetch recorded on others) | 78 | – |

**What "no fetch recorded" means.** A failed feed fetch writes no state (`src/ingest/pipeline.py:733-752`), so
these 1,311 are either never reached by the slow rotation (ingest.md §2.2) or failing every time. The data cannot
tell the two apart. PR 1 makes them distinguishable.

## 2. Removals and demotions: none proposed as code

The rule given for this work is that a removal needs agreement across instances or a verified dead source.

- **Appendix A (301).** The instances agree, but the evidence does not show the feeds are dead. They answer HTTP
  200/304 and their items are lost later, and why is not recorded per source.
  - The list includes the Washington Post world feed, the FT, EFE English, Folha, O Globo, El Tiempo, the NZ Herald,
    the Korea Herald and Mainichi. Their items are more likely refused (HTTP 403 is 48–70% of item failures,
    scraping.md) or paywalled than missing.
  - 19 have a sibling feed of the same domain that collects. 17 of these are Deutsche Welle language feeds, which
    suggests same-outlet duplicates rather than dead feeds. **Could not determine.**
- **Appendix B (1,311).** Possibly never reached; see above.
- **Appendix C (649).** These are feed-less, and feed-less sources are not read by regular passes
  (`src/scheduler/runner.py:857`). The fix is to find their feeds, not to remove them (P7).
- **Effect of a catalogue `enabled: false`.** It would reach fresh installs only. `enabled` is not a
  catalogue-owned field, so existing installs keep their value (`src/ingest/seed_sources.py:520-522`).

**Proposed next step.** Once PR 1's failure recording has run for one quarter on ≥ 2 instances, demote the
appendix-A and appendix-B keys that are **failing on every instance**. Their error classes will then be in the
data.

**The 110 catalogue domains disqualified by both re-checking instances are not removal candidates.** Their random
articles are normal, and the disqualification comes from the link-density rule (source-qualification.md §4.2).

## 3. Fix the entry: catalogue language (code PR: catalogue language)

`scripts/catalogue_language.py` compared, for every catalogue key sampled in ≥ 3 snapshots (3,779 keys):
- the script of its random stored article;
- the script its catalogue language implies.

- **Measured:** 39 keys mismatch in ≥ 75% of snapshots, all on one script.
- **Read:** one stored title per key, to name the right language. **23 are unambiguous** and are fixed in the PR.
- **Left in this report (16), because the right value is not clear:**
  - Ukrainian, Russian, Arabic and Lebanese journals whose Cyrillic or Arabic titles sit over English abstracts;
  - two Korean outlets where the script check reads 9–10 of 12;
  - an e-paper page index, a mixed-script TV site and the Korean law site.

`language` is a catalogue-owned field, so the fix reaches existing installs at the next seed
(`src/ingest/seed_sources.py:520-522`). Articles stored earlier keep their language. Nothing is re-extracted.

| file:index | domain | name | was | becomes | snapshots mismatching | evidence (script observed; title read) |
|---|---|---|---|---|---:|---|
| sources.yml:154 | ria.ru | RIA Novosti | en | ru | 12/12 | Cyrillic; Russian |
| sources.yml:979 | meduza.io | Meduza | en | ru | 12/12 | Cyrillic; Russian |
| sources.yml:1586 | english.hani.co.kr | Hankyoreh (South Korea) | en | ko | 11/11 | Hangul; Korean |
| sources.yml:1610 | pravda.com.ua | Ukrainska Pravda (Ukraine) | en | uk | 12/12 | Cyrillic; Ukrainian |
| sources.yml:1900 | en.royanews.tv | Roya News (Jordan) | en | ar | 12/12 | Arabic; Arabic |
| sources.yml:2286 | independentarabia.com | Independent Arabia | ar | en | 12/12 | Latin; English |
| sources.yml:3450 | pan.am | PanARMENIAN.Net | en | hy | 12/12 | Armenian; Armenian |
| sources.yml:3516 | kabar.kg | Kabar | en | ky | 12/12 | Cyrillic; Kyrgyz |
| sources.yml:3520 | cn.kabar.kg | Kabar | en | zh | 12/12 | Han; Chinese |
| sources.yml:3522 | cambodiadaily.com | The Cambodia Daily | en | km | 12/12 | Khmer; Khmer |
| sources.yml:3523 | postkhmer.com | The Phnom Penh Post | en | km | 4/4 | Khmer; Khmer |
| sources.yml:3762 | dy365.in | DY365 | bn | en | 12/12 | Latin; English |
| sources.yml:4054 | teluguvaaditv.com | Telugu Vaadi TV | en | te | 11/12 | Telugu; Telugu |
| sources.yml:4835 | azathabar.com | RFE/RL's Turkmen Service | ru | tk | 10/10 | Latin; Turkmen |
| sources.yml:5018 | globes.co.il | Globes | en | he | 3/3 | Hebrew; Hebrew |
| sources.yml:5025 | b4blaze.com | B4Blaze | en | ml | 12/12 | Malayalam; Malayalam |
| sources.yml:5068 | arabita.news | Arabita News | ar | it | 12/12 | Latin; Italian |
| sources.yml:5201 | ezerzeme.lv | Ezerzeme | ru | lv | 12/12 | Latin; Latvian |
| sources.yml:5269 | malaysiaindru.my | Malaysiakini | zh | ta | 12/12 | Tamil; Tamil |
| sources.yml:5302 | bd.toonsmag.com | Toons Mag | en | bn | 12/12 | Bengali; Bengali |
| academic_sources.yml:400 | wameedalfikr.com | Wameed Al-Fikr Journal | ar | en | 3/3 | Latin; English |
| academic_sources.yml:485 | serbiosoc.org.rs | Archives of Biological Sciences | en | sr | 12/12 | Cyrillic; Serbian |
| academic_sources.yml:533 | goldhorde.ru | Zolotoordynskoe Obozrenie | en | ru | 10/10 | Cyrillic; Russian |

Confidence: **high** where 10–12 of 10–12 snapshots agree; **medium** for the three entries with 3–4 snapshots
(postkhmer.com, globes.co.il, wameedalfikr.com). The check only sees script errors, so same-script errors
(es/pt, ru/be) are not found and this list is a lower bound.

## 4. Additions

`scripts/candidates_eval.py` evaluated 993 candidate domains, i.e. sources an instance qualified by its own
measurement that no catalogue has:
- on 1 instance: 686
- on 2 instances: 172
- on 3 instances: 104
- on all 4: 31

The rule tested: qualified on ≥ 3 of 4 instances, median ≥ 20 stored articles, newest article ≤ 30 days old on
≥ 2 instances, every sampled article ≥ 100 words with no stub phrase, and disqualified nowhere. 15 domains pass:

- **11 are the app's own channels**, not web sources: Wikipedia-edition rows and one hazard row. The candidate
  export should leave out non-web provenance classes, as the quality export already does (code PR: candidate
  export).
- **4 are web outlets:**

| source | domain | country | instances | median stored | newest article | action | confidence |
|---|---|---|---:|---:|---|---|---|
| Canal 26 | canal26.com | ar | 3 | 25 | 15 d | add once a feed is found | low |
| Diario Hoy (Argentina) | diariohoy.net | ar | 3 | 25 | 15 d | add once a feed is found | low |
| El Trece | eltrecetv.com.ar | ar | 3 | 25 | 15 d | add once a feed is found | low |
| Río Negro | rionegro.com.ar | ar | 3 | 23 | 15 d | add once a feed is found | low |

All four were qualified without a feed address. Regular passes skip feed-less sources
(`src/scheduler/runner.py:857`), so adding them as they are would add four more rows to appendix C. **No addition
is proposed as code.** A maintainer can add them with feed URLs after a manual check. That check needs a live
fetch, which was not done here.

**Why so few pass.** 50–54% of candidates on every instance have a newest stored article > 365 days old or
undated, and 9–35% rest on fewer than 5 stored articles (source-qualification.md §4.3).

## 5. Duplicates

- There are **no exact duplicate feeds within one catalogue file** (raw `feed_key`, same file).
- 31 keys appear in two files. These are mostly the same outlet in `sources.yml` and `sources_spectrum.yml`, or
  repeats inside the generated legal list, and the seeder merges them by design (`src/ingest/seed_sources.py:450-470`).
- Same-outlet feeds that never collect while a sibling does: 19 keys in appendix A, 17 of them Deutsche Welle
  language feeds.
