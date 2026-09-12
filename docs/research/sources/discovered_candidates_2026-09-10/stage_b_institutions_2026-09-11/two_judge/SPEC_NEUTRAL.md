# Stage B triage spec

You classify SOURCE WEBSITES from evidence already fetched for you. You do NOT browse.
Each row gives: domain, name, site_title, description, up to 8 recent headlines, country,
language, wikidata_type. The headlines are the strongest evidence — read what the site
actually PUBLISHES, not what its name suggests.

## Output — one JSON object per batch, nothing else

{"rows": [ {...}, {...} ]}

One object per input row, in any order. EVERY row in the input must appear EXACTLY ONCE.
A batch with a missing row is thrown away whole, so count before you finish.

Each object:
  "domain"        : copied exactly from the input
  "journalism"    : true/false — does this site produce ORIGINAL REPORTING for a general or
                    specialist audience? A body publishing its own announcements is NOT
                    journalism, however newsworthy.
  "kind"          : EXACTLY ONE of this closed list, copied character for character:
                    news, magazine, broadcaster, wire-agency, investigative, fact-checker,
                    academic, trade-or-corporate, institution, religious, personal-blog,
                    aggregator, other
                    Anything outside this list voids the WHOLE batch. There is no
                    "corporate" (use trade-or-corporate) and no "tabloid" (that is a topic).
  "language"      : ISO 639-1 two-letter code of the site's own language, or "unknown"
  "topics"        : 0-3 strings from the closed vocabulary below. Nothing else. Omit rather
                    than invent — an off-list topic is dropped and wastes the slot.
  "confidence"    : high | medium | low — your confidence in "kind"
  "primary_source": REQUIRED when kind is "institution", omitted otherwise. See below.

## primary_source — the only new question, and the one that matters here

Most rows in these batches are institutions, and the bucket is MIXED. Answer true ONLY if
the body publishes its own AUTHORITATIVE RECORDS — the things it alone is the source of:

  true  : ministries, regulators, agencies, courts, parliaments, statistics offices,
          central banks, standards bodies, inspectorates, public health authorities,
          international organisations — publishing decisions, regulations, statistics,
          official announcements, inspection results, case law, tenders
  false : a museum's exhibitions and opening hours, a club or hobby association, an alumni
          body, a promotional or tourism site, an events calendar, a charity's campaign
          page, a trade association's member newsletter, a university's marketing pages

Test to apply: if this body vanished, would a specific class of PUBLIC RECORD become
unavailable? True = yes. If it only publishes news ABOUT itself, that is false.

When genuinely torn, answer false and set confidence to medium or low. A wrongly admitted
row starts collecting a gift-shop announcement as though it were a public record.

## Closed topic vocabulary (the only permitted "topics" values)

agriculture, ai, analysis, ancient-history, applied-science, biotech, brics, business,
climate, culture, cybersecurity, defense, disinformation, economy, education, energy,
environment, fact-checking, fake-news, finance, financial, general, general-news,
geopolitical, healthcare, history, human-rights, investigative, iq, lean-center, legal,
news, open-source, osint, permaculture, policy, politics, privacy, quantum, regional,
robotics, science, society, space, tabloid, technology, war, water

---

# METHOD — read rows, not batches

A previous run over these exact batches was refused by the validator, and the cause is worth
knowing because it is easy to repeat.

**Workers stopped reading individual rows and classified the batch.** On the same input, one
produced 240 `institution` labels, another 48 `broadcaster` and 46 `other`, another 169 `other`
including national government ministries. One had written domain-name string heuristics instead
of reading the evidence. Every one of them reported success and believed it had validated its
own output.

**These batches are heterogeneous.** Most rows are public bodies, but a batch also contains
newspapers, museums, universities, broadcasters, research institutes and professional
associations. A row that does not resemble its neighbours is not noise to be smoothed over — it
is a row, and it gets read on its own evidence like every other one.

`other` is a last resort for a site that genuinely fits nothing on the list. If `institution`
fits, use `institution`. The `wikidata_type` field is a HINT from an external catalogue and is
sometimes wrong or out of date — the headlines are the evidence.

Go row by row. For each, answer the two questions separately:

1. What KIND of site is this, on the evidence in front of you?
2. If it is an institution — apply the `primary_source` test stated above, as written.

Do not decide what the batch is and then fill it in.
