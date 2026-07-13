# Source-metadata enrichment — parallel-session prompt (batch `en-001`)

> Paste everything below the line into a fresh **Claude Opus 4.8** web/app session
> (one session per batch; run several in parallel). The session needs **web
> search** enabled. It is self-contained — it does not read this repo.
>
> Tool-call budget is limited. The prompt is written so a batch finishes in **one
> structured answer** after at most a handful of searches. Do not edit the
> taxonomy or schema between batches — consistency across sessions is the point.

---

You are classifying news/information **sources** for an offline research catalog.
For each source in the INPUT list, output enriched metadata as YAML. The catalog's
rule is absolute: **never fabricate**. If you are not reasonably sure of a field,
omit it (or use the honest fallback below) and lower `confidence`. A wrong tag is
worse than a missing one.

## Tool-use discipline (read first — keeps you within budget)
- Most of these are well-known outlets. **Answer from your own knowledge first.**
- Use **web search only to disambiguate or verify** a source you are unsure about,
  and at most **one search per uncertain source**. Do not browse multiple pages,
  do not open the outlet's site to read it — a single search snippet is enough to
  confirm ownership/type/topic or to confirm the domain is the outlet you think.
- If after one search you are still unsure of a field, omit it and set
  `confidence: low`. Never loop.
- Produce the **entire batch in one final YAML block.** Do not narrate per source.

## Dimensions to fill (these are ORTHOGONAL — keep them in their own fields)

### 1. `source_type` — the MEDIUM/genre (exactly one). Controlled vocabulary:
`news`, `wire-agency`, `magazine`, `broadcaster`, `investigative`,
`academic-research`, `scientific-journal`, `government-primary`, `igo`
(intergovernmental org, e.g. UN/WHO/IMF), `ngo-civil-society`, `think-tank`,
`fact-checker`, `data-portal` (statistics/open-data), `blog`, `religious`,
`financial-data`. Pick the single best fit; default `news` only when it genuinely
is a general news outlet.

### 2. `ownership` — funding/control (exactly one, when known). Controlled vocab:
`independent` (privately owned, editorially independent), `state-owned`
(government owns/controls editorial), `public-broadcaster` (publicly funded,
arms-length charter, e.g. BBC/NHK/ARD), `state-media` (state-funded AND
state-directed messaging), `corporate` (owned by a large non-media conglomerate),
`party-affiliated`, `nonprofit`, `cooperative`, `wire-agency`. Omit if unsure.
This describes the money/control, **not** political slant.

### 3. `lean` — political slant (one, ONLY where a widely-cited assessment exists).
`lean-left`, `lean-center-left`, `center`, `lean-center-right`, `lean-right`.
This is **reputational and contestable** — set it only for outlets with a
well-known, commonly-cited editorial stance, and **omit it entirely otherwise**
(most sources should have no `lean`). Never guess slant from the country.

### 4. `topics` — subject coverage (1–4 tags). Use these where they fit; add a
precise lowercase-hyphenated tag if none do. Prefer the controlled set:
`general`, `politics`, `economy`, `business`, `finance`, `markets`,
`science`, `technology`, `ai`, `health`, `medicine`, `climate`, `energy`,
`environment`, `agriculture`, `space`, `defense`, `security`, `cybersecurity`,
`human-rights`, `justice`, `law`, `migration`, `education`, `culture`, `sports`,
`media`, `religion`, `local-news`, `regional`. For a general outlet, `general`
plus its 1–2 strongest beats.

### 5. Geography (fill ONLY if the INPUT shows `?` and you are sure):
- `country` — ISO-3166-1 alpha-2, lowercase (or `null` if genuinely transnational
  — e.g. an IGO or pan-regional outlet). Never guess from the language.
- `language` — ISO-639-1 (e.g. `en`, `fr`, `ar`).
- `coverage_scope` — one of `local`, `national`, `regional`, `global`.

## Output schema (YAML; one list item per INPUT row, SAME order)
```yaml
- domain: example.com        # echo verbatim from INPUT — the join key
  source_type: news
  ownership: independent      # omit if unknown
  lean: lean-center-left      # omit unless a cited stance exists (most: omit)
  topics: [general, politics]
  country: fr                 # include ONLY if INPUT had '?' and you are sure
  language: fr                # include ONLY if INPUT had '?' and you are sure
  coverage_scope: national
  confidence: high            # high | medium | low
  note: ""                    # <=12 words: basis or caveat; "" if none
```

## Hard rules
- Output **one row per INPUT row, in the same order**, keyed by the exact `domain`.
- Omit any field you are not sure of; do not pad with defaults. `topics` and
  `source_type` are the only always-required fields.
- `lean` is the rare exception, not the rule — leave it off unless the stance is
  widely documented.
- If a `domain` looks dead, parked, or you cannot identify it at all, output the
  row with `source_type: news`, `confidence: low`, `note: "unidentified"` and
  nothing else — never invent an identity.
- No prose outside the final YAML block.

## INPUT (batch `en-001`)
```
# domain | name | country | language
972mag.com | +972 Magazine (Israel/Palestine) | il | en
36krglobal.com | 36Kr Global | cn | en
38north.org | 38 North (Korea) | ? | en
3news.com | 3News (Ghana) | gh | en
aarp.org | AARP (American Association of Retired Persons) | ? | en
new.abb.com | ABB Robotics | ? | en
abcnews.go.com | ABC News | us | en
abc.net.au | ABC News (Australia) | au | en
abcnews.go.com | ABC News - Fact Check | ? | en
academia.edu | Academia.edu - Intelligence Studies | ? | en
accessnow.org | Access Now | ? | en
aclanthology.org | ACL Anthology | ? | en
acm.org | ACM News | ? | en
actahort.org | Acta Horticulturae | ? | en
adaderana.lk | Ada Derana (Sri Lanka) | lk | en
addgene.org | Addgene - CRISPR | ? | en
addisstandard.com | Addis Standard (Ethiopia) | et | en
onlinelibrary.wiley.com | Advanced Materials | ? | en
onlinelibrary.wiley.com | Advanced Robotics | ? | en
advancedsciencenews.com | Advanced Science News | ? | en
adweek.com | AdWeek | ? | en
aeon.co | AEON - Intelligence | ? | en
factcheck.afp.com | AFP Fact Check - US | ? | en
africacheck.org | Africa Check | ? | en
africa-health.com | Africa Health | ? | en
africuncensored.net | Africa Uncensored (Kenya) | ke | en
academic.oup.com | African Affairs | ? | en
link.springer.com | African Archaeological Review | ? | en
africanarguments.org | African Arguments | ? | en
african.business | African Business | ? | en
africancolonialhistory.com | African Colonial History | ? | en
africandecolonization.com | African Decolonization | ? | en
africandiasporahistory.com | African Diaspora History | ? | en
africandigitallibrary.net | African Digital Library | ? | en
aehnetwork.org | African Economic History Network | ? | en
africanhistoryforum.com | African History Forum | ? | en
africanhistoryinmaps.com | African History in Maps | ? | en
africanhistorypodcast.com | African History Podcast | ? | en
sourcebooks.fordham.edu | African History Sourcebook (Fordham University) | ? | en
africanindependencemovements.com | African Independence Movements | ? | en
africanleaders.org | African Leaders | ? | en
africanmilitaryhistory.com | African Military History | ? | en
africanmusichistory.com | African Music History | ? | en
africanoilgasreport.com | African Oil & Gas Report | ? | en
africanoralnarratives.com | African Oral Narratives | ? | en
africanpolitics.org | African Politics | ? | en
asanet.org | African Studies Association (ASA) | ? | en
bu.edu | African Studies Center (Boston University) | ? | en
dia.org | African World Museum (Detroit) | ? | en
africanews.com | Africanews | ? | en
```
