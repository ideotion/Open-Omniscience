# Sharing the burden without sharing the text — the swarm question, the article ledger, and what the app owes the newsrooms it reads (2026-09-28)

**Status: THINKING MEMO + QUESTION ROUND (`PS01`–`PS16`) — UNANSWERED; on 2026-09-30 the maintainer set it aside for now (`R100`: no data sharing between installs; `PS01` stays open). Nothing here is built. Nothing here
is decided: the maintainer decides; this file records.** Written on 2026-09-28 at the maintainer's request, in
the maintainer's words:

> *"Let's have a step back for a moment and think things through about Open-Omniscience. The app's intention
> is to help users understand what's going on in the digital world while encouraging them to use a critical
> approach to "digital facts" and "knowledge" and "data". However, I'd like to think of long term horizon. In
> the event the app is successful and many people download and use it, all sources will be scrapped
> individually so many times it could have negative impact on their servers and economical situations, which
> would deprive a part of society from having journalist, an indispensable pillar to democracy and freedom of
> thought. mark my words. As a consequence, I'd like to think of a way to create a torrent like approach
> allowing users to share their downloads / scraping with other users to lighten the burden on journalist's
> servers, with digital proof and safety. It would both theoretically help users with bandwidth and protect
> sources from being scrapped all over again. It would help confirm when an article is scraped twice a year
> from different sources and that it has not changed (or that it did!). Help me out think this through, as I
> am bothered with the ethical aspect of the app and the impact it could have in case of success to media
> which massively depend on users paying for exclusive content or submitting themselves to commercials while
> accepting cookies and all others sorts of data scraping that can be sold to data brokers. Please ask any
> questions to help us think through this. We're just thinking, deciding and planning for now."*
>
> and, while the session read the ledger: *"remember that I initially wanted the app to have a blockchain
> like approach to articles : marking each of them like a financial transaction in their dedicated
> blockchain."* — then, while the memo was being written: *"the idea behind a blockchain approach could be
> an equivalent of a blockchain for the financial data to information data. Maybe there's a platform need
> for blockchain based information data."*

The concern has two halves that the memo keeps apart, because they have different remedies: the **cost** a
successful app imposes on a newsroom's servers (which scales with the number of users and which fetching less,
or fetching once, can reduce), and the **revenue** a newsroom never sees from the app's readers (which is the
same at one user as at a million, and which no fetching arrangement restores). The torrent idea addresses the
first. The second is what the maintainer is actually bothered by, and it needs a different kind of answer
(§6).

---

## §0 How to answer, and how the answers are processed

- Write a letter after `ANSWER PSnn:` (a note in your own words after it is welcome and is recorded verbatim;
  where the note contradicts the letter, **the note is the ruling**). Answering in chat with the same
  `PSnn = letter` form is equivalent; the receiving session copies the letters here.
- **Blank on a ⛔ question stays PENDING** — never defaulted. **Blank on any other question takes the stated
  default as an ASSUMPTION**, reversible at any time, and the session that acts on it labels it as one. Where
  the writer's recommendation (★) differs from the default, the default is the status quo, because changing a
  ruled sequence or a non-negotiable must be explicit.
- Markers, as on the 2026-09-12 sheet: **⛔** irreversible, outward-facing or data-safety — never taken
  autonomously; **🔒** reversible but changes what the app retains or contacts — must be explicit.
- Processing (the §0.2 protocol of the 2026-09-12 sheet): the first session that receives this file back
  parses the letters mechanically; this file stays in place as the primary record; the `OPEN_QUEUE.md` entry
  that indexes the round is updated; `RULINGS_INDEX.md` gets one row per answered `PSnn` (an unanswered one
  gets none, as the pre-flight round's did); contradictions with an existing ruling are listed, never resolved
  by the recording session; nothing is built from a blank.
- **Protocol note, recorded rather than hidden.** THE PROTOCOL rule (1) says to read `LESSONS.md` in full every
  session. It measured 1,076,242 bytes today (the two constitution files together 1,137,007, against the
  573,850 the 2026-09-07 amendment cites as what made "in full" achievable). Whether rule (1) is still
  achievable as written is **`PF11` ⛔, asked 2026-09-18 and still unanswered** — it is pointed at here, not
  re-asked. This session read every heading and, in full, every entry in the families this memo touches
  (egress, consent, robots and refusals, publishers, custody and anchoring, privacy, Tor), and says so.

---

## §1 What is already decided or recorded — pointed at, not restated

Everything below was grepped in `CLAUDE.md`, `docs/ledger/RULINGS_INDEX.md`, `docs/ledger/OPEN_QUEUE.md` and
`docs/FUTURE_DEVELOPMENTS.md` before a single question was written (rule (6)). The swarm question is new; most
of its parts are not.

| Subject | Where | What it settles for this question |
|---|---|---|
| Hosting stance: give the software away; **never host the users' data**; no SaaS, no central server, no accounts, no telemetry | `CLAUDE.md` Non-negotiables (ruled 2026-06-10); `FUTURE_DEVELOPMENTS.md` §*Hosting & mobile* | A swarm in which users' machines serve each other is not "hosting the users' data" by the app's maker — but it makes each USER a host of what others fetched. The stance was written about a server the maker runs; the question whether it also forbids user-to-user redistribution is asked, not assumed (`PS01`). |
| The Open Commons Mirror is a SEPARATE sister project for PUBLIC data; **user corpora never touch it**; node 0 is the maintainer's machine; created only once this project is mature | `CLAUDE.md` (clarified 2026-06-12); `FUTURE_DEVELOPMENTS.md` §*The Open Commons Mirror*; `OPEN_QUEUE.md` entry *OPEN COMMONS MIRROR — SISTER PROJECT* | The "few named nodes fetch once, everyone pulls" shape (§4, E) already exists as a design with eight recorded open questions. This memo does not re-ask them; it adds the reason to bring the design forward (`PS11`). |
| **The reliable-memory pillar** and **the blockchain initial intention**: the record must not be silently rewritten; the recorded read is "anchor into a chain, do not run one"; a dedicated chain "must justify itself"; the one scenario that would — *mutually-distrusting anonymous operators* — "is not the federation described here … revisit if that changes" | `FUTURE_DEVELOPMENTS.md` §*Blockchain — the maintainer's initial intention*; `OPEN_QUEUE.md` same entry | A user swarm IS that scenario. So the question is legitimately re-opened, and §5 answers it again on its merits rather than by pointing at the old answer. |
| The 2026-06-19 data-architecture rulings: `src/custody` **is the day-one federation seam**; **witness federation** goes to the sister project ("this app stays single-machine + anchoring-only via OpenTimestamps"); **TLS notarisation is Tier-2, not load-bearing** (TLS-1.2-only, Tor-incompatible, injects a deanonymising third party); the K1 content-multihash and K2 `canon_version` seams | `OPEN_QUEUE.md` entry *DATA-ARCHITECTURE & DURABILITY SKELETON*; `docs/design/DATA_ARCHITECTURE_SKELETON.md` | The receipt design in §5 rides the seams these rulings froze. "Single-machine + anchoring-only" is the standing ruling this memo would amend if `PS04`/`PS05` open a receipt exchange — said here so the amendment is deliberate. |
| **Federation by signed exchange** already shipped for source annotations: custody-signed bundles, import verifies before storing, a web of trust, *who said what*, dissent shown never averaged, no server, no accounts | `docs/USER_MANUAL.md` §*Shared source annotations* | The exact pattern a first receipt exchange can reuse without a new socket or a new crypto stack (`PS05` a). |
| Conditional GET + capped self-resetting per-feed backoff (a 200 that stores nothing → `skip_until = now + min(300 s·2ⁿ, 6 h)`) | `OPEN_QUEUE.md` (F) *RSS DUP RATE ~93% — CONDITIONAL-GET CORE SHIPPED*, PR #208; `src/ingest/pipeline.py:ingest_source` | The cheapest load reduction on feeds is already built. What remains on feeds is the cadence of ACTIVE feeds and servers that ignore validators. |
| One rate authority (`Q1012` = a): a per-PROCESS budget composed with the collection-speed governor; per-host politeness persisted with a named deferral (`Q1013` = a); 1 request/s/host, one connection per host, `Crawl-delay` honoured | `RULINGS_INDEX.md` Q1012/Q1013; `src/scheduler/process_budget.py`; `src/ingest/__init__.py` | Per-host politeness is settled. A swarm would not change any of it — it changes how many INSTANCES stand behind the same polite behaviour. |
| A robots refusal is a deferral, never a rejection; never shop for an exit; **"reading a refusing publisher through an archive or mirror as a workaround" is a SEPARATE question needing its own ruling** | `OPEN_QUEUE.md` 2026-09-10/11 entries (refusal ethics, the Whonix addendum) | `PS10` points at that pending ruling and asks the neighbouring one (an archive as a shared cache), without deciding either. |
| **BUL-3**: "Is redistributing a publisher's full text the operator's to do?" — the Bulletin's annexes default to full text; three options recorded, none taken | `OPEN_QUEUE.md` entry *ONE QUESTION §18's ENUMERATION RAISES*; `docs/ROADMAP.md` → The Bulletin | The same question as `PS01` in another coat. Whatever `PS01` rules should be read onto BUL-3 in the same turn, and this memo says so rather than asking twice. |
| **The default deployment is a Whonix/Tor path through a Debian VM** — no clearnet path exists for that operator; asking for one is asking them to deanonymise | `OPEN_QUEUE.md` *ADDENDUM 2026-09-10* | Decisive for the swarm shape: peer-to-peer over Tor is unsafe and slow, and an inbound connection is not something a Whonix workstation offers (§4). |
| `ETHICS.md` commitments: **"Respect Opt-Outs — if a source requests to be removed, comply immediately"**; GDPR "respect the right to erasure"; copyright — personal, non-commercial, fair use, transformative; **"Cache responses to avoid repeated requests for the same content"** | `docs/ETHICS.md` §*Core Principles*, §*Best Practices for Contributors*, §*Privacy* | The ethics document already asks for the cache the maintainer is describing — and already promises the two things (opt-out, erasure) an anonymous swarm cannot deliver (§4). |
| The privacy policy states, as a verifiable legal claim, that the Editor processes nothing and the software sends no telemetry; the operator is the sole controller; a "journalistic exception" clause exists | `docs/legal/POLITIQUE_DE_CONFIDENTIALITE.md` §1–§4 ×12; `CLAUDE.md` per-release no-telemetry re-check | Any exchange between users is a new outbound channel and would change the legal documents in all 12 languages before it changes code. |
| `PF11` ⛔ — rule (1)'s achievability at `LESSONS.md`'s size | `docs/design/PREFLIGHT_QUESTIONS_2026-09-18_RELEASE_RUN.md` | Pending; pointed at in §0. |

---

## §2 The facts this rests on

Evidence tiers as on the 2026-09-12 sheet: **VERIFIED** = read in the tree at `main`@`01a4c69` this session;
**LEDGER** = a dated measurement recorded in the ledger, cited; **FROM MEMORY** = a fact the writer is confident
of but could not check from a sandbox with no egress to the sources — the session that builds on it must
confirm it; **ESTIMATE** = arithmetic over the above, method stated, never precision.

### §2.1 What one user's instance does to one newsroom (VERIFIED)

1. Every byte goes through the one `EthicalFetcher` (`src/ingest/__init__.py`): robots.txt read first and
   fail-closed (a refusal or an unreachable robots.txt means nothing is fetched), per-host lock (one request in
   flight per host), `min_interval_s = 1.0` (one request per second per host at most), a host's `Crawl-delay`
   honoured when larger and now persisted across passes with a named deferral beyond 180 s (`Q1013`), an honest
   `OpenOmniscienceBot/<version> (+repo URL; ethical research crawler)` User-Agent — **except in protected
   (Tor) mode, where a generic browser UA is sent so the operator is not singled out** (`docs/ETHICS.md` §6).
   That exception matters for §6: a newsroom cannot recognise, count or opt out of a crawler it cannot see.
2. A collect pass polls each due source's feed with `If-None-Match` / `If-Modified-Since`; a 304 costs about a
   kilobyte and no parse; a 200 is parsed and each entry's canonical URL is checked against the store **before
   any page is fetched** (`pipeline.ingest_url`: "Deduplication is by canonical URL (cheap, pre-fetch)"). So a
   known article costs the newsroom only its share of the feed poll, never a second page fetch. A new article
   costs exactly one page fetch (capped at 10 MB, HTML only), then extraction, hashing, indexing — all local.
3. A feed whose 200 stored nothing new backs off geometrically to a 6 h cap and re-checks after that; a feed
   that keeps producing is polled every pass. Passes run continuously (`continuous = True`, short inter-pass
   gaps) at the governor's "maximum" by default, across DIFFERENT hosts only.
4. No page is ever re-fetched to see whether it changed. The app has no change detection for press articles at
   all today; `src/versioned/` does it for Wikipedia, law and OSM, whose sources publish change feeds. **So the
   "scraped twice a year — has it changed?" half of the maintainer's idea is not a load problem to be shared,
   it is a capability the app does not have.** A receipt exchange (§5) would give it to the community without
   any user re-fetching anything.
5. There is no listening socket in the app except the loopback UI server. Airplane mode is a process-wide
   socket-level guard; every offline→online transition passes ONE consent popup whose hover lists every host
   the app can reach (`docs/SECURITY.md`, enumerated and test-guarded). A peer that ACCEPTS connections would
   be the first inbound surface the app ever had.

### §2.2 What the field measured (LEDGER)

- Catalogue: 5,580 entries in `configs/sources.yml` (VERIFIED); in the two analysed field instances 3,599 were
  enabled, 2,766 of them with an RSS URL, yielding **≈ 2 new articles/day per feed at the median**, with
  big-name feeds above 10/day; **≈ 90 % of feed items are already known** (`OPEN_QUEUE.md` throughput verdict,
  2026-07; the dedup front's docstring cites 90–92 %).
- Measured average download is "a few kB/s", two orders below Tor capability; the bottleneck is app-side, not
  the network — so the app is a slow, polite reader today by construction, not by choice.
- Bytes per article differ 2× between two corpora (`OPEN_QUEUE.md`, 2026-09), so no single figure is honest;
  a news page with its markup is commonly 0.1–1 MB before scripts (FROM MEMORY), and the fetcher takes the
  HTML only.

### §2.3 What the app has never given a newsroom, at any scale (VERIFIED by construction)

The fetch carries no cookies, runs no scripts, loads no advertisement, sends no identifier, opens no
subscription. Every article the app reads is read at zero revenue to its publisher — this is true at one user
and at a million. It is exactly what protects the operator from "commercials … cookies and all others sorts of
data scraping that can be sold to data brokers", and it is exactly why the maintainer's discomfort is well
placed: **the app's readers are the newsroom's audience with the paying part removed.** Sharing fetches
between users changes what the newsroom PAYS in bandwidth; it cannot change what the newsroom EARNS, which was
already nothing. Section 6 is about that half.

### §2.4 What the app already proves, and what it cannot (VERIFIED)

- `Article.hash` is SHA-256 over the **whitespace-normalised EXTRACTED text** (`url_utils.generate_content_hash`),
  not over the bytes the server sent. Two installs with different extractor versions (trafilatura settings,
  the non-article gate, a stopword change upstream of extraction) can hash the same page differently. Any
  cross-install comparison must therefore carry the extractor/canonicalisation version (the K2 `canon_version`
  seam exists on the row for exactly this reason, and `content_multihash` names the algorithm).
- The custody log (`src/custody/log.py`) is **already a per-install blockchain in every sense that matters**:
  append-only, hash-chained (`prev_hash`), signed (Ed25519, plus ML-DSA when enabled), each entry a
  "transaction" over an item hash with an action (ingest, access, export, redact, anchor …), verifiable
  offline from an exported bundle. What it cannot prove by itself, and says so: that nothing was dropped from
  its TAIL (needs an external anchor) and WHEN (the timestamp is self-asserted unless anchored).
- OpenTimestamps anchoring (`src/custody/anchor.py`, opt-in, consent-gated per invariant #14f) commits a
  Merkle root of the chain into Bitcoin through public calendars: existence-before-T, no wallet, no fee, no
  trust in the app — the "anchor into a chain, do not run one" ruling, built.
- Nothing proves **authenticity** — that the publisher served those bytes. A hash is a statement about what
  the fetcher SAW; a signature says who vouches for having seen it; an anchor says by when. None of them says
  the server said it. The 2026-06-19 ruling parked the only mechanism that would (TLS notarisation) for good
  reasons that still hold.

---

## §3 The arithmetic of the burden (ESTIMATE — method stated, order of magnitude only)

Per user, per newsroom, per day, from §2.1–§2.2: a MEDIAN feed (≈ 2 new/day, quiet most of the day) costs on
the order of 5–70 requests and 0.1–1 MB (the backoff makes the low end; a validator-ignoring server that
answers 200 every pass makes the high end). A BIG-NAME newsroom (dozens of articles/day, an always-active feed)
costs on the order of 60–150 requests and 2–30 MB (the pages dominate the bytes, the polls dominate the
requests).

| Users of the app | On a median newsroom, per day | On a big-name newsroom, per day | What it is next to their own audience (FROM MEMORY: a national daily serves ~10⁶–10⁷ page views/day at 2–5 MB each; a regional site 10⁴–10⁵) |
|---|---|---|---|
| 10⁴ | 0.05–0.7 M requests · 1–10 GB | 0.6–1.5 M requests · 20–300 GB | Below 1 % of a national daily's bytes; noticeable request count for a small self-hosted site (a WordPress on shared hosting sees this as one more crawler) |
| 10⁵ | 0.5–7 M requests · 10–100 GB | 6–15 M requests · 0.2–3 TB | A few per cent of a national daily's bytes; on a par with a small site's whole audience in requests |
| 10⁶ | 5–70 M requests · 0.1–1 TB | 60–150 M requests · 2–30 TB | The scale of their human audience, as bot traffic, at zero revenue — they WILL notice, and they will block or write to whoever the User-Agent points at |

Three honest readings of the table:

1. **The maintainer's scenario is real at 10⁶ and material at 10⁵, and it is noise at 10⁴** — where the app is
   likely to live for years (a heavy install, an encrypted store, a local model, Tor by default). `PS12` asks
   which scale to plan for; the principles below are scale-free, the urgency is not.
2. **Requests and bytes hurt different newsrooms.** Bytes are a CDN line item for the large; request count is
   what makes a small self-hosted newsroom's server sweat. Feed cadence is the request lever and it is
   coordinable without sharing any text (§4, A); page bytes are the byte lever and only fewer FETCHERS (not
   fewer users) move it (§4, E) — or sharing the text itself (§4, B).
3. **Whatever the scale, the traffic is recognisable bot traffic in transparent mode and INVISIBLE bot traffic
   in protected mode.** The second is the harder ethical fact: over Tor the app "blends in" as a browser, so
   a newsroom that wanted to say "please stop" to `OpenOmniscienceBot` could not find it. §6 and `PS09` are
   about giving them somewhere to say it.

---

## §4 What "torrent-like" can mean here — five shapes, and where the constitution stands on each

| | **A · Receipts only** — users exchange signed `(url, hash, time, canon_version)` receipts, never text | **B · The swarm** — users serve each other the article text, torrent-style | **C · Publisher-cooperative** — text is shared only from publishers that declare consent or an open licence | **D · Archive-mediated** — fetch or verify through a third-party archive (Wayback etc.) | **E · Named nodes** — a few accountable nodes (the sister project) fetch once; users pull by consent |
|---|---|---|---|---|---|
| Burden on newsrooms | Requests ↓ (coordinated feed cadence: "12 peers saw this feed unchanged 10 min ago"); bytes ≈ unchanged (every user still fetches each new article once) | Requests ↓↓ and bytes ↓↓ (N fetches → k) | ↓↓ for the consenting minority; unchanged for the rest | Shifts the load to an institution that did not consent to be a CDN | Requests ↓↓ and bytes ↓↓ (N → number of nodes) |
| What it proves | Change timelines; k-witness corroboration with dissent shown; existence-before-T via anchoring | The same, plus the bytes themselves — from a PEER, not from the publisher | The strongest: publisher-signed content is authentic by construction | An independent capture (a widely accepted witness), for what it captured | Node-signed captures; a named party that can be held to its log |
| Legal (FROM MEMORY, not counsel — `PS15`) | Facts about public pages; no expression redistributed. Clean. | Reproduction + making available of press publications, by every user, to strangers; the maker's inducement exposure (Grokster-class); EU DSM art. 15 press publishers' right excludes private individual use and ends where a network service begins; TDM exceptions (art. 3/4) permit mining, not redistribution | Whatever the publisher's declaration permits — the only shape where "permission" is a fact rather than an inference from robots.txt | The archive's own contested position (Hachette v. Internet Archive was about books, news archiving is tolerated, not settled) becomes ours | Concentrated on named operators who can hold a licence, answer a notice, and negotiate — accountability is the point |
| Privacy of the operator | A receipt reveals what an install read. Mitigable: only sources in the shared catalogue (everyone polls those anyway), pseudonymous install key, batched, exported by an explicit act (`PS04`, `PS05`) | A DHT announces what you hold; peers learn your IP and your reading; incompatible with the Whonix default | As A | The archive sees every URL you ask for | A node sees what a user pulls unless pulls are bulk snapshots (torrents tolerate this: you fetch the whole day, not the article) |
| Safety on the default (Tor) path | Files or a pull-only sync work over Tor | Peer-to-peer over Tor is unsafe (the Tor Project's own standing guidance against BitTorrent over Tor — FROM MEMORY) and slow; inbound connections do not exist on a Whonix workstation | As A/E | Works over Tor, slowly | Pull-only bulk sync works over Tor |
| Poisoning | A peer can lie about a hash → shown as dissent, weighed by trust, never averaged | A peer can serve a fabricated article as the newsroom's | Signature-checked | Trust the archive | Node-signed; the node's log is auditable |
| Opt-out / erasure (`ETHICS.md` promises both) | Trivial — nothing of theirs is redistributed | **Impossible** — a torrent cannot be recalled; a GDPR erasure cannot be honoured by a swarm | Honoured through the declaration | The archive's procedures, not ours | Honoured by the nodes (a named node can delete and log the deletion as an event, per the vintage model) |
| Constitution fit | Fits; needs `PS04`/`PS05` and an amendment to "single-machine + anchoring-only" | Breaks loopback-only, the one-popup model, the no-inbound surface, the opt-out and erasure commitments, and makes every user a distributor | Fits; needs the declaration and outreach | Touches the pending "archive workaround" ruling; a third party sees the reading | Is the recorded sister project; the fork inherits the constitution |
| Effort | M (bundles) → L (a pull-only exchange) | XL, and a new threat model | M for the manifest; outreach is the maintainer's | S–M | XL, and it is not this repo's work |

### §4.1 The seven objections that close the anonymous full-text swarm (B), on the app's own rules

1. **Opt-out becomes impossible.** `ETHICS.md` promises a source that asks to be removed is removed
   immediately. A torrent cannot be recalled; the newsroom that objects would be objecting to a thousand
   strangers' copies the app put into circulation.
2. **Erasure becomes impossible.** Articles carry personal data. Today the single operator is the sole
   controller with a journalistic exception clause; a swarm makes each user a distributor of that data to
   strangers, and no exception the writer knows of covers a general-public redistribution network.
3. **Each user becomes a distributor — the legal exposure lands on exactly the people the app exists to
   protect,** and the app's maker becomes the distributor of a tool built for redistribution.
4. **Robots consent is granted to an identified crawler for a FETCH.** A newsroom that allows
   `OpenOmniscienceBot` has allowed one polite reader to read; nothing in that permission extends to the
   reader handing copies to a network. Reading the permission wider than it was given is the behaviour the
   refusal-ethics rulings refuse in every other place.
5. **The default operator is on Tor.** Peer-to-peer over Tor is the textbook way to deanonymise a Tor user,
   and a Whonix workstation accepts no inbound connection; the shape is not merely risky for that operator, it
   is unavailable to them.
6. **A peer's bytes are not the newsroom's bytes.** Without publisher signatures nothing distinguishes a
   faithfully relayed article from a fabricated one but the agreement of other witnesses — who, in an
   anonymous swarm, cost nothing to invent (the Sybil problem, §5). Newsrooms also personalise: regional
   editions, A/B headlines, consent banners — so honest witnesses legitimately disagree about "the" bytes.
7. **It does not touch the revenue half.** It saves the newsroom's bandwidth and, if anything, deepens "one
   reader pays, everyone reads" — the paywall economics the maintainer names are made worse, not better, by
   making copies travel further.

### §4.2 What receipts-only (A) buys, and what it honestly does not

It does not reduce the first fetch: every user still reads each new article once from the newsroom. It CAN
reduce feed polling on active feeds (the request lever, §3) if instances learn from each other that a feed has
not changed — at the price of trusting peers about freshness, which must never suppress a fetch, only lengthen
the interval within the existing 6 h cap. Its real product is the second half of the maintainer's idea: **a
community change record for press articles** (the timeline of distinct hashes per URL, per witness, with the
extractor version beside each), and **corroboration** ("seven installs report the same text; one reports a
different one — here is who and when"), shown exactly as the annotation federation shows dissent: attributed,
never averaged into a number. That is the "scraped twice a year, changed or not" question answered without
anyone re-fetching, and it is legally the cleanest object the app could publish.

### §4.3 Where the newsroom is actually protected (C and E)

The library model already exists in the world for exactly this problem: LOCKSS ("Lots Of Copies Keep Stuff
Safe") and CLOCKSS keep publisher-CONSENTED copies of journals in named libraries' hands, dark until a trigger
event (FROM MEMORY). Consent is what makes those archives legitimate, and a NAMED custodian is what makes
consent possible: a newsroom can say no to a foundation, license a foundation, or write to a foundation; it can
do none of those things to a swarm. The sister project's design already says this in its own words ("the most
verifiable mirror, not the only one", named witnesses, a foundation before the node is loud). The maintainer's
concern is the strongest argument yet for building it — and for the *publisher-cooperative* half (C): a
machine-readable declaration a newsroom can publish (mirrorable or not, under which licence, whom to contact,
which channel to fetch from) so that "permission" becomes a stated fact rather than an inference from a
robots.txt written for search engines. Public broadcasters, nonprofit newsrooms and wire services with open
feeds are the plausible first signatories; paywalled dailies are not, and the design must be honest that the
protection it offers them is *reading less of them, more politely*, not mirroring them.

---

## §5 The blockchain, re-read with the maintainer's reminder

**What "a transaction per article, in a dedicated blockchain" asks for, taken seriously.** Each article is an
event: at time T, install K fetched URL U and obtained bytes whose extracted text hashed to H. The maintainer
wants that event recorded so that it cannot be silently rewritten, so that it can be checked by others, and so
that a later event about the same U (same H or a different one) can be set beside it. Every one of those
properties is a property of an **append-only, signed, hash-chained log with external anchoring** — which the
custody log already is, per install (§2.4). The receipt (§4, A) is simply that transaction made portable:

```
receipt:
  url · canonical_url · fetched_at (self-asserted) · status
  content_hash (sha2-256 over the extracted text) · canon_version (which extractor/normalisation produced it)
  signer (the install's custody key) · signature
  anchored_in (optional: the OpenTimestamps proof of the batch's Merkle root)
```

**What a chain adds, and what we would need it for.** A blockchain is a mechanism for many parties who do not
trust each other to agree on ONE ORDER of CONFLICTING claims (whose coin is it). Two receipts about the same
URL never conflict: "K₁ saw H at T₁" and "K₂ saw H′ at T₂" are both true observations, and their coexistence
IS the finding (the article changed, or the newsroom serves two versions, or one extractor differs). There is
no double-spend to prevent, no scarce thing to allocate, nothing to order that timestamps and anchors do not
already order. What a swarm of anonymous users DOES introduce is the Sybil problem: a witness costs nothing, so
"seven installs agree" means nothing until identity costs something. **A chain does not solve that; proof-of-
work or proof-of-stake solve it by making identity expensive — and the price is a token, validators and
governance-by-wealth**, which the recorded funding stance calls misaligned ("anything that monetizes reader
behavior"; paid services never paid data). So the 2026-06-12 criterion is met by the swarm scenario and the
answer is still no, for a sharper reason than before: **a chain can order anonymous claims, it cannot make them
true.** What makes a witness credible is who they are (a named library, a newsroom, a known install with a
history) — the web-of-trust the annotation federation already implements — not the data structure their claim
is stored in.

**The honest name for what the maintainer wants is the article ledger**: a transparency log (the Certificate
Transparency shape the mirror design already chose — inclusion proofs, consistency proofs, no token) of
receipts from pseudonymous installs and named witnesses, with every batch's Merkle root anchored into Bitcoin
through OpenTimestamps (built, consented). It gives each article its transaction, makes the record publicly
checkable, makes a silent rewrite detectable, and shows disagreement instead of hiding it. It never says an
article is TRUE, and it never says the newsroom served those bytes — a receipt is a claim about what a reader
saw. The one thing that would turn it into proof of authenticity is the publisher's own signature (§4, C),
and that needs no chain either.

**A door kept open, with its criterion written down.** If the day comes when the witnesses ARE mutually
distrusting institutions with money at stake in the record (rival press groups, states), a permissioned BFT
log among them is the honest re-opening — and it is, again, witness cosigning with more machinery, not a
public chain with a token. `PS06` asks the maintainer which of the properties above is the one they want, so
that the build serves the intention rather than the word.

### §5.1 The platform reading — "a blockchain for information data, as there is one for financial data"

The maintainer's third message widens the question from *my record* to *a shared public record*: is there a
platform-sized gap — a ledger of record for information events, the way public chains became one for value
transfers? Taken seriously, the analogy maps like this:

| Finance | Information |
|---|---|
| A transaction transfers a scarce asset | An **event**: publisher P published bytes B at URL U at time T; reader K observed hash H at U at T′ |
| A balance is the sum of transactions | A **version history** is the sequence of distinct H seen at U, per witness |
| Double-spend is the conflict consensus must order | Two witnesses seeing different bytes is **not a conflict** — it is the finding (an edit, a regional edition, an extractor difference), to be shown, not resolved |
| The chain's owner-lessness resists compulsion | A public log's operators can be compelled; **anchoring + replicated snapshots** make a compelled deletion detectable and the data recoverable, which is the claim the mirror design already limits itself to ("detectable and expensive", never "impossible") |
| Tokens pay validators and make identity expensive (Sybil resistance) | Witness weight comes from **who** signs — a newsroom, a library, a known install — never from stake |

**Is the gap real? Yes — and it is unfilled.** The world has a public, cryptographic, append-only log for
*certificates* (Certificate Transparency), for *software artifacts* (Sigstore's Rekor, a Trillian Merkle log
that anyone may write a signed entry to, with no token and no fee), for *media provenance* (C2PA content
credentials, signed at capture — Project Origin's newsroom pilots), and for *existence-before-T* (OpenTimestamps);
the Starling Lab framework combines authenticated capture with distributed storage for exactly the journalism
use case (all FROM MEMORY — the receiving session confirms each before building on it). There is **no public
log of "what did URL U say at time T, according to whom"** other than the Internet Archive — one organisation,
one jurisdiction, no signatures, no witnesses, under legal pressure. That is the platform the maintainer is
pointing at, and the recorded sister-project question Q5 ("a neutral commons several apps, including non-OO
tools, can cite") already asked for its governance shape without naming this first service.

**What the platform would be, in the mirror design's own vocabulary:** a neutral **receipt format** (the record
of §5, specified so a newsroom, an archive, a browser extension or a rival tool can write one — a
publisher-signed receipt is the strongest entry the log can hold), a **public transparency log** of receipts
(Rekor/Trillian-class: inclusion and consistency proofs, checkpoints co-signed by independent witnesses in the
transparency.dev sense), **anchoring** of checkpoints into public chains (built), and **replicated
snapshots** of the whole log that anyone can mirror (LOCKSS, again). It is cheaper than mirroring bytes by
three orders of magnitude — a receipt is a few hundred bytes, and CT logs already hold billions of entries —
so it is the sister project's *first* service, not its last. This app is its first client and, until the log
exists, its bundles are the log (`PS05` = a).

**Where the chain still earns its keep, stated fairly.** The one property a permissionless chain has that a
federated log lacks is having no operator to compel. The honest answer is the layered one: run the log (so
the record is cheap, fast and free to write), anchor its checkpoints into Bitcoin (so its history cannot be
back-dated by anyone, the operators included), and publish content-addressed snapshots (so no single custodian
can make an entry disappear). If a future federation of mutually-distrusting institutions wants BFT agreement
on checkpoints, that is witness cosigning with more machinery. What remains unjustified at every scale
examined is a token: it would fund the wrong thing (making anonymous identity expensive) with the wrong
incentive (monetising the record). `PS16` asks whether the platform, not only the feature, is the intention.

---

## §6 What the app owes newsrooms whatever the swarm decision — the give-back layer

The revenue half has no fetching remedy. It has honesty remedies, and each one fits the informed-consent
non-negotiable (caveats visible, choice given, layering not hiding). None needs a ruling to be *designed*;
several need one to be *built* because they change what the app retains or shows.

1. **A footprint meter — the app's own load, measured where the bytes leave.** Per host: requests, bytes, the
   share answered 304, over 24 h and 30 days, from the fetcher's own counters (the activity monitor already
   stamps them); a per-instance line in the consent popup's hover ("yesterday this instance made N requests to
   M hosts"). Transparency in the direction the app has never had it — toward the people being read. `PS08`,
   `PS14`.
2. **Read the newsroom's own machine-readable wishes, not only its robots.txt.** Today nothing in the tree
   reads `isAccessibleForFree: false` (schema.org's paywall markup), the TDM Reservation Protocol
   (`tdm-reservation: 1` header, `<meta name="tdm-reservation">`, `/.well-known/tdmrep.json` — the
   machine-readable opt-out EU DSM art. 4 names), or `noarchive`/`noai` (VERIFIED: the only paywall handling
   is the post-fetch non-article gate that discards paywall STUBS). A newsroom that reserved its text from
   mining has said, in the file designed to say so, the thing the app's robots discipline respects everywhere
   else. Honouring it costs corpus — an unmeasured share — and that share should be measured on a field corpus
   before the default moves. `PS07`.
3. **A crawler page and a place to say no.** The honest UA already links the repository; the repository has
   no page a newsroom's operator can read: who fetches, at what cadence, how to opt out (a robots `Disallow`
   for `OpenOmniscienceBot` reaches every instance at its next robots read; an email reaches the catalogue),
   and — stated plainly — that instances in protected mode present a generic UA and cannot be singled out,
   which is why the robots rule is the reliable channel. Every well-run crawler publishes such a page; it is
   how "Respect Opt-Outs" becomes operational at any scale. `PS09`.
4. **A cooperative declaration for newsrooms that want to be mirrored** (§4.3) — the manifest, then the
   outreach, once there is a named node to mirror to. `PS13`.
5. **The reader.** Invariant #6 sends the user to the LOCAL copy first and makes the newsroom's own page a
   secondary "source ↗" link behind a confirmation popup. That is the right default for a tool whose value is
   the corpus, and it is not re-litigated here — but it is where the app could tell the user, in one visible
   line, what they are reading for free and where the newsroom would be paid: a "read at the source / support
   this newsroom" affordance carrying the publisher's own subscription page when the catalogue knows it,
   never an advertisement, never a tracker. Recorded as a question, not a design.

---

## §7 Recommendation — the writer's leaning; the maintainer decides

A phased path, each phase useful on its own and none of them the swarm:

- **Phase 0 — give back and measure (this cycle, small):** the footprint meter (§6.1); read and DISCLOSE the
  machine-readable reservations without yet acting on them, and measure the share of the field corpus they
  cover (§6.2 as `PS07` = b first); the crawler page (§6.3). No new host, no new socket, no legal change.
- **Phase 1 — the article ledger as files (0.5/0.6, M):** receipts written from the custody seam for every
  ingested article (opt-in, like auto-log-on-ingest), exported and imported as signed bundles exactly like
  annotation bundles; a change timeline and a corroboration view per URL with dissent shown; the extractor
  version beside every hash; OpenTimestamps anchoring of bundle roots for those who consent; the receipt
  format written as a neutral specification from the first day (`PS16`). Nothing leaves a machine without an
  explicit export. This is the "transaction per article" the maintainer asked for, made
  portable, with no chain and no token.
- **Phase 2 — a consented, pull-only receipt exchange (later, L):** instances pull receipt bundles from a
  named relay (the sister project's node 0 is the natural one) through the ONE consent popup; no listening
  socket, Tor-compatible, the relay's log auditable. Coordinated feed cadence rides on it, bounded by the
  existing 6 h cap and never suppressing a fetch.
- **Phase 3 — text shared only where consent is a fact (the sister project):** named nodes fetch once and
  serve bulk snapshots; publisher declarations decide what is mirrored; opt-out and erasure are honoured by
  named custodians who can be written to. The anonymous full-text swarm is not on the path, on the seven
  grounds of §4.1 — unless the maintainer overrides `PS01`, in which case counsel comes before design
  (`PS15`).

---

## §8 The questions

#### PS01 ⛔ 🔒 · May full article TEXT ever travel from one user's machine to another's through this app?
The line every other question stands on. BUL-3 (the Bulletin annexes' full-text default) is the same question
in another coat and should be read with this answer in the same turn.
- **a** ★ — **Never through this app.** Receipts (hashes, times, signatures) may travel; text stays on the
  machine that fetched it, or goes to the sister project by an explicit export under its own rules. _Impact:_
  §4 B is closed; A, C-via-E and the give-back layer remain; every opt-out, erasure and distributor objection
  dissolves; the app itself reduces no first-fetch bytes for any newsroom.
- **b** — **Only text from publishers that have consented or licensed it** (a machine-readable declaration or
  an open licence), and only through named nodes, never peer to peer. _Impact:_ opens §4 C through E; needs
  the declaration (`PS13`) and a node to hold it; still closes the swarm.
- **c** — **Yes, any robots-permitted text, peer to peer.** _Impact:_ the swarm; §4.1's seven objections apply
  in full; the legal documents change ×12 before any code; `PS15` comes first.
Default if blank: **none — ⛔, stays PENDING.**
ANSWER PS01: STILL OPEN (⛔, no letter) — given in the project thread «Record the 37 answers» 2026-09-30 03:35 UTC (the older-rounds list, item 10) and copied here by the recording session: «articles will travel between machines through backups and restores eventually. Let's think of this differently. For now, the app only scraps the web for data, stores and indexes it. no data sharing for now, as I need a clear view before making such big decisions.» Recorded as `R100`: no data sharing between installs for now; nothing here is designed or built until the maintainer reopens the question.

#### PS02 · Which burden is the one to spare first?
- **a** ★ — **Request count on small self-hosted newsrooms** (feed polling cadence). _Impact:_ coordinated
  cadence through receipts, on top of the backoff already built; cheap; text never moves.
- **b** — **Bytes on large publishers' CDNs** (page fetches). _Impact:_ only fewer FETCHERS (named nodes) or
  shared text move it — nothing this app can do alone if `PS01` = a.
- **c** — **Both, equally.**
Default if blank: **a**.
ANSWER PS02:

#### PS03 · Who fetches once, on the day N users read the same newsroom?
- **a** ★ — **Users fetch for themselves until the sister project exists; from then on, named accountable
  nodes fetch once and users pull by consent.** _Impact:_ the burden question becomes the sister project's
  reason to exist; this app's job is the receipts, the give-back layer and the pull path.
- **b** — **Users fetch for themselves, permanently;** the app only gets politer. _Impact:_ §3's table is the
  ceiling; no structural answer to 10⁶.
- **c** — **An anonymous swarm of users.** _Impact:_ §4.1.
Default if blank: **a**.
ANSWER PS03:

#### PS04 🔒 · What identity does a receipt carry?
- **a** ★ — **A stable pseudonymous key per install** (the custody signer), published only by an explicit
  export and only for sources in the shared catalogue, so a receipt links to an install, never to a person,
  and the linkage is disclosed where the export happens. _Impact:_ witnesses can be weighed through the web
  of trust; an install's reading of catalogue sources is what it reveals.
- **b** — **Unlinkable receipts** (a fresh key per bundle). _Impact:_ no linkage — and no weighing: a thousand
  witnesses cost nothing to invent, so timelines work and corroboration does not.
- **c** — **Only named institutional witnesses count as witnesses;** users' receipts feed their own timelines.
  _Impact:_ corroboration waits for the sister project's witness set.
Default if blank: **a**.
ANSWER PS04:

#### PS05 🔒 · How receipts move between users, first version
- **a** ★ — **Files:** export/import signed receipt bundles exactly like the annotation bundles — no new
  socket, no new host, works over Tor and offline. _Impact:_ M; the swarm's product without the swarm.
- **b** — **Pull-only sync from a consented relay** (a named node), through the ONE consent popup; no
  listening socket. _Impact:_ L; the natural second step; a new host in `docs/SECURITY.md`'s table and the
  popup's hover in the same diff.
- **c** — **A DHT or inbound peer connections.** _Impact:_ the first inbound surface the app ever had; a new
  threat model; unavailable on the Whonix default.
Default if blank: **a**.
ANSWER PS05:

#### PS06 · The blockchain intention — which property is wanted? *(multi-select)*
- **a** — **My own record cannot be silently edited.** _Already true:_ the custody chain.
- **b** — **Anyone can verify my record existed before a date without trusting me.** _Already true when
  anchored:_ OpenTimestamps, opt-in, consent-gated.
- **c** ★ — **Strangers can check the record's integrity and see which witnesses saw which bytes, with
  disagreement shown.** _Needs:_ the article ledger (receipts published, a log with inclusion/consistency
  proofs, named and pseudonymous witnesses) — §5.
- **d** — **One agreed "true version" of each article at each time.** _Cannot be had in general_ (personalised
  and regional pages, extractor differences); k-witness corroboration with dissent shown is the honest
  substitute, and the memo asks that the wording never promise more.
- **e** — **A dedicated chain regardless of a–d.** _Impact:_ tokens, validators, governance; §5 says why the
  writer would not; the note is the place to say why the maintainer would.
Default if blank: **a, b, c**.
ANSWER PS06:

#### PS07 🔒 · The newsroom's machine-readable reservations — read them, honour them, or neither?
`isAccessibleForFree: false`, the TDM Reservation Protocol, `noarchive`/`noai`. None is read today.
- **a** — **Honour:** a reserved or paywalled article is kept as METADATA only (headline, URL, date, hash), its
  text is not stored; the per-source count of such articles is shown. _Impact:_ the strongest position, and an
  unmeasured loss of corpus — measure first.
- **b** ★ — **Read and DISCLOSE first:** store as today, mark each such article visibly ("the publisher
  reserved this text from mining"), count them per source, and bring the measured share back for the decision
  on (a). _Impact:_ honest label, behaviour unchanged, the number the ruling needs.
- **c** — **Neither** (today).
Default if blank: **b**.
ANSWER PS07:

#### PS08 · A footprint meter — the app's own load on each host
- **a** ★ — **Build it:** per host, requests / bytes / 304 share over 24 h and 30 days from the fetcher's own
  counters, in the task manager's Coverage subtab and the diagnostics bundle. _Impact:_ S–M; counts only,
  never a score; the first transparency the app offers toward the people it reads.
- **b** — **Diagnostics only.**
- **c** — **Not needed.**
Default if blank: **a**.
ANSWER PS08:

#### PS09 · A crawler page and an opt-out channel
- **a** ★ — **Publish `docs/BOT.md`**, reached from the UA's repository link: who fetches, how politely, how to
  opt out (robots `Disallow` for `OpenOmniscienceBot`, or an email to the project), what an opt-out does
  (every instance honours robots at its next read; a catalogue entry can be marked declined), and the plain
  statement that protected-mode instances present a generic UA and cannot be singled out. _Impact:_ S;
  docs-only; makes "Respect Opt-Outs" operational at scale.
- **b** — **Not now.**
Default if blank: **a**.
ANSWER PS09:

#### PS10 · An archive (Wayback and its kind) as a shared cache — points at the pending "archive workaround" ruling
- **a** ★ — **No, not as a fetch path:** a third party would then see what every operator reads; the load
  moves to a nonprofit that did not consent to be our CDN; it is one organisation under legal pressure; and
  the pending ruling is about REFUSING publishers, which this is not.
- **b** — **As a consented, disclosed, per-URL VERIFICATION** (compare my hash with the archive's capture,
  when both have one) — never as the source of text.
- **c** — **As a fetch path by default.**
Default if blank: **a**.
ANSWER PS10:

#### PS11 · Sequencing — does this bring the sister project's DESIGN forward?
The recorded gate: the fork is created "only once the current project is mature". A design document is not a
repository.
- **a** ★ — **Write the Open Commons Mirror's design document now** (its eight recorded questions, the library
  model of §4.3, the receipt exchange of §5 as its first service), as docs; code still waits for maturity.
- **b** — **Everything waits for maturity, as ruled.**
Default if blank: **b** (the status quo; the writer recommends a, and a change to a ruled sequence must be
explicit).
ANSWER PS11:

#### PS12 · The scale to plan for
The mechanisms are scale-free; the urgency and the default budgets are not (§3).
- **a** — **10⁴ users** — the app's likely audience for years (a heavy install, an encrypted store, a local
  model, Tor by default). _Impact:_ the give-back layer suffices; the ledger is built for its proof value.
- **b** ★ — **10⁵.** _Impact:_ plan the mechanisms now, size today's defaults for 10⁴.
- **c** — **10⁶ and above.** _Impact:_ the sister project's fetch-once nodes become the priority, not the
  afterthought.
Default if blank: **b** — plan the mechanisms for 10⁵, size today's defaults for 10⁴.
ANSWER PS12:

#### PS13 · A cooperative declaration for newsrooms
- **a** ★ — **Draft the opt-in declaration** (a `/.well-known/` document or a feed extension: mirrorable or
  not, licence, contact, preferred fetch channel) as a design now; the outreach to public broadcasters,
  nonprofit newsrooms and open-feed wire services is the maintainer's, once a named node exists.
- **b** — **Not now.**
Default if blank: **a** (the draft only; outreach is never taken autonomously).
ANSWER PS13:

#### PS14 · Telling users about their own footprint at consent time
- **a** ★ — **Yes:** once `PS08` exists, the consent popup's hover gains one measured line (yesterday's
  requests and hosts for this instance). _Impact:_ informed consent in both directions; ×12 strings.
- **b** — **No.**
Default if blank: **a**.
ANSWER PS14:

#### PS15 ⛔ · Counsel before any text leaves a machine
An operator step, not a design one: copyright (reproduction, making available), the EU DSM Directive (art. 3/4
TDM and its machine-readable opt-out; art. 15 press publishers' right), GDPR controller status of a user who
redistributes, and the maker's inducement exposure — for the jurisdictions the maintainer cares about.
- **a** ★ — **Obtain it before `PS01` = b or c is designed.**
- **b** — **Proceed on the writer's reading** (a non-lawyer's, FROM MEMORY).
Default if blank: **none — ⛔, stays PENDING.**
ANSWER PS15:

#### PS16 · Platform or feature — is the article ledger meant as a public protocol others can write to?
The maintainer's third message ("maybe there's a platform need for blockchain based information data"), read
with the sister project's recorded Q5.
- **a** ★ — **A platform, built as the sister project's FIRST service:** a neutral, publicly specified receipt
  format (publisher-signed entries welcome), a public transparency log with independent witnesses, anchored
  checkpoints, mirrorable snapshots; this app is the first client. _Impact:_ the sister project's design (`PS11`)
  starts from the log rather than from the byte mirror; governance and a legal home come with it (its Q2, Q5,
  Q6); nothing in this repository changes until the format exists.
- **b** — **A feature first** (`PS05` = a bundles between this app's users), **a platform if it is adopted.**
  _Impact:_ cheapest; the format still gets written neutrally so the promotion costs nothing later.
- **c** — **A feature only.**
Default if blank: **b**.
ANSWER PS16:

---

## §9 Pointed at, not re-asked

- **BUL-3** — the Bulletin annexes' full-text default (`OPEN_QUEUE.md`; `docs/ROADMAP.md`): read `PS01` onto it.
- **The "archive workaround" ruling** — reading a refusing publisher through an archive or mirror
  (`OPEN_QUEUE.md`, the 2026-09-10 Whonix addendum): `PS10` is its neighbour, not its answer.
- **`PF11` ⛔** — rule (1)'s achievability at `LESSONS.md`'s size (§0).
- **The Open Commons Mirror's eight questions** (`FUTURE_DEVELOPMENTS.md`): unchanged; `PS11` asks only
  whether their design document is written now.
- **`Q1136`** (self-update: consented like any egress, never auto-install) and **`Q1001`/`Q1002`** (the host
  table and the one popup's hover): any relay under `PS05` = b follows them.

## §10 What this session did not do

It did not build, change or configure anything. It did not read `LESSONS.md` in full (§0). It did not reach
any publisher, archive, standard body or legal text — every FROM MEMORY fact above is labelled and is the
receiving session's to confirm before it is built on.
