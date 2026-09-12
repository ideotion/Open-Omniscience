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

# READ THIS PART TOO — it is a correction, from a measured failure on these exact batches

A first pass over these batches was REFUSED by the validator. Six of ten workers had every
one of their batches thrown away. The cause was not carelessness about the format — every
one of them reported success and passed their own checks. The cause was this:

**They stopped reading individual rows and classified the batch.**

The measured evidence: on identical input, one worker labelled all 240 rows `institution`,
another labelled 48 rows `broadcaster` and 46 `other`, another labelled 169 rows `other`
including national government ministries. Those cannot all be right. And each of them
flattened the rows that did not fit the pattern they had settled on.

## What this means for you

**These batches are HETEROGENEOUS.** The majority are public bodies, but a batch also
contains major international news organisations, museums, universities, broadcasters,
professional associations and research institutes. A row that does not look like its
neighbours is not an anomaly to be smoothed over — it is a row, and it gets read on its own
evidence like every other.

Concretely, the errors that voided batches:

- a globally-known daily newspaper labelled `magazine`, `trade-or-corporate` and
  `institution` — by three different workers. Read the headlines: a paper reporting on
  housing bills, storms and interest rates is `news`, and `journalism: true`.
- national and supranational government bodies labelled `other`, when `institution` is on
  the list and fits exactly.
- a museum labelled `other`, when `institution` fits and `primary_source: false` carries
  the distinction.

## Sharper guidance on primary_source, from the same failure

One worker marked a supranational executive body `primary_source: false`. That is wrong, and
the spec above says so: international organisations publishing decisions, regulations and
official announcements are the clearest `true` there is.

The conservative default in the spec ("when genuinely torn, answer false") applies when you
are TORN. It is not a licence to answer false by habit. A ministry, a regulator, a court, a
statistics office, a central bank and an international organisation are not torn cases.

## Method

Go row by row. For each one, ask the two questions separately:
  1. What KIND of site is this? (from the closed list, on the evidence in front of you)
  2. If it is an institution — is it a source of public RECORD, or does it publish about
     itself?

Do not decide what the batch is and then fill it in.
