# Law vetting board — every catalog row awaiting a maintainer decision

> **Generated** by `scripts/law_vetting_board.py` from `configs/legal_sources_generated.yml` + `configs/legal_sources.yml`. Do not hand-edit: re-run the script. Every cell but **Decision** is copied from the catalog, and `tests/test_law_vetting_board.py` re-derives the counts, so no row here can describe a source that is not in the file.
>
> **44 rows need a decision** out of 277 catalog sources (catalog `as_of` 2026-07-17). Sections 1 and 2 are facts read off `verification.status`; sections 3 and 4 are a **keyword triage** over the catalog's own evidence and notes, offered so the backlog can be scanned in one pass. A triage keyword both over- and under-selects, so these two sections are a starting point and not an exhaustive list of blocked or dead domains.
>
> Nothing here is scraped around. A host's robots refusal or bot wall is that host's choice; the only honest answers are an adapter/API path the publisher offers, or a recorded gap.

## 1. Confirmed gaps — nothing to fetch, only to acknowledge — 2

A `lead` row with **no domain**: the producing session looked and found no official portal at all, and recorded the absence rather than inventing one. These need no adapter and no fetch; the decision is whether the record stands.

| Country | Domain | Kind | What the catalog records | Decision (Stands as a gap? / re-open) |
| --- | --- | --- | --- | --- |
| PRK | _(none — deliberate)_ | gap | No DPRK government body operates a public online legal database, gazette portal or enumeration page. NYU Globalex's "Overview of the North Korean Legal System", the US Library of Congress Guide to Law Online, and 38 North's NK TechLab project (2025-26) all ind… [truncated, 284 chars in the catalog] |  |
| YEM | _(none — deliberate)_ | gazette | No functioning official online gazette or legislation portal was located. HIIL's 2018 "Rule of Law in Yemen" report states the Ministry of Legal and Parliamentary Affairs prints the Official Gazette but "is not mandated to distribute copies of the laws, nor is… [truncated, 293 chars in the catalog] |  |

## 2. Unverified leads — a real domain nobody loaded — 9

A `lead` row **with** a domain: the URL was found but never fetched, so it ships disabled and no document under it is watched. Each is one of: enable it, route it through an adapter, or record it as a gap.

| Country | Domain | Kind | What the catalog records | Decision (Enable / adapter / gap / drop) |
| --- | --- | --- | --- | --- |
| CRI | imprentanacional.go.cr | gazette | Domain seen only as a citation host (imprentanacional.go.cr/editorialdigital/...) inside a PGR-published legal text; the gazette's own search or issue-browse URL path was not directly located this session |  |
| GMB | assembly.gm | consolidated_portal | assembly.gm homepage describes itself as providing 'Access legislation, member profiles, news, events, tenders, and parliamentary resources'; a specific legislation-listing URL and count were not confirmed this session |  |
| INT | gcc-sg.org | consolidated_portal | No dedicated public treaty/instrument enumeration page found; the 'Agreements' URL surfaced by search (gcc-sg.org/en-us/CognitiveSources/Pages/Agreements.aspx) 404s on fetch, and the Secretariat's 'Digital Library' (gcc-sg.org/en/MediaCenter/DigitalLibrary/) i… [truncated, 335 chars in the catalog] |  |
| KNA | gazette.gov.kn | gazette | the Official Gazette Bill, 2023 (passed 8 Feb 2023) provided for digitising the Gazette and named gazette.gov.kn as its future home; a Yale Law Library guide separately lists the Gazette as 'not available online'. No direct evidence the site is live was found… [truncated, 273 chars in the catalog] |  |
| KWT | e.gov.kw | gazette | Kuwait Government Online (e.gov.kw) hosts an e-subscription page for Kuwait Alyawm; the Ministry of Information's gazette app package (kw.gov.media.KuwaitAlyoumApp) confirms a media.gov.kw family domain, but the exact public website root for the gazette was no… [truncated, 294 chars in the catalog] |  |
| LBY | aladel.gov.ly | gazette | aladel.gov.ly (Ministry of Justice of the Tripoli-based Government of National Unity) references an official-gazette announcement page. Separately, parliament.ly (the Benghazi/Tobruk-based House of Representatives) publishes its own, distinct numbered 'الجريدة… [truncated, 353 chars in the catalog] |  |
| MMR | moi.gov.mm | gazette | Domain (www.moi.gov.mm/ppe/, Ministry of Information / Printing & Publishing Enterprise) is cited by Wikipedia as the gazette's home. Not independently confirmed live this session — searches surfaced only a same-named news column (Global New Light of Myanmar's… [truncated, 381 chars in the catalog] |  |
| NER | sgg.ne | gazette | sgg.ne confirmed as the SGG's institutional site; Library of Congress and WorldCat records confirm the print JO's existence and imprint, but no searchable/downloadable web archive was located |  |
| SYR | parliament.gov.sy | gazette | parliament.gov.sy has a decrees-and-laws section — existence confirmed via search only, not fetched. NYU Law's Globalex guide states explicitly that direct online access to the Official Gazette is limited for Syria. |  |

## 3. Access-blocked or bot-walled — cannot be scraped fail-closed — 29

The row's own prose mentions robots, a bot wall, a CAPTCHA or a 403. This project never evades a block, so scraping is off the table by ruling: each of these is either an adapter/API path or an honest gap. Read the evidence column — the bucket is a keyword triage, not a finding.

| Country | Domain | Kind | What the catalog records | Decision (Adapter / API / honest gap) |
| --- | --- | --- | --- | --- |
| AGO | imprensanacional.gov.ao | gazette | Imprensa Nacional – E.P.'s statutory-publisher role and its imprensanacional.gov.ao address are corroborated by its own site copy (found via search) and independently by decree texts on governo.gov.ao and FAOLEX mirrors citing Lei 2/10 and Lei 24/11. |  |
| BDI | amategeko.gov.bi | consolidated_portal | Search results show Bulletin Officiel du Burundi (BOB) issue PDFs hosted under amategeko.gov.bi, browsable by legal-instrument type (e.g. /nature/decret-presidentiel/), tagline 'L'information sur le droit à la portée de tous' |  |
| BRB | barbadosparliament-laws.com | consolidated_portal | counts (623 Consolidated Statutes, 550 Acts, 681 Subsidiary Legislation, 1936 Statutory Instruments, 1574 Gazettes, plus Hansard/Order Papers/Bills) read from a search-engine cache snippet showing nearby content dated as recent as 15 Jul 2026; direct fetch ret… [truncated, 283 chars in the catalog] |  |
| BWA | elaws.gov.bw | consolidated_portal | The official government portal gov.bw repeatedly and consistently directs users to elaws.gov.bw for current Acts and subsidiary legislation, new legislation, historical legislation, and unreported case law. A page on elaws.gov.bw itself (found via search) stat… [truncated, 334 chars in the catalog] |  |
| CIV | sgg.gouv.ci | gazette | Search snippet confirms sgg.gouv.ci/jo.php as SGG's JO page; direct fetch blocked by robots.txt |  |
| COL | suin-juriscol.gov.co | consolidated_portal | Multiple .gov.co citations (MinJusticia, Fiscalia, Comision de la Verdad) confirming the domain, plus the site's own stats section reporting 87,392 normas and 13,596 sentencias; direct fetch was blocked by robots.txt |  |
| CRI | sinalevi.go.cr | consolidated_portal | PGR's own site (pgr.go.cr) announces that pgrweb.go.cr/scij/ is moving to sinalevi.go.cr effective 20 July 2026; a direct fetch of the new domain returned ROBOTS_DISALLOWED, meaning the site is live and resolving but blocks automated access |  |
| CUB | gacetaoficial.gob.cu | gazette | domain and site structure (Normas Jurídicas, Búsqueda Avanzada, Ediciones del Mes) confirmed via search snippets; direct fetch returned ROBOTS_DISALLOWED |  |
| GNQ | boe.gob.gq | gazette | Corroborated independently by a government-adjacent news outlet (guineaecuatorialpress.com, reporting the CNIAPGE's official launch of the BOE portal around October 2020) and by the BOE's own help/search page at boe.gob.gq/ayudaboege.html, which describes sear… [truncated, 304 chars in the catalog] |  |
| HND | congresonacional.hn | gazette | La Prensa (Honduras) editorial and ENAG/DIGER government announcements dated March and June 2026 describe a new Congreso Nacional-ENAG agreement making all Gaceta content free at congresonacional.hn, replacing the former paid portal; a direct fetch of the doma… [truncated, 289 chars in the catalog] |  |
| HTI | pressesnationales.ht | gazette | domain corroborated by a business directory and Wikidata's 'official website' claim (2013–); direct fetch returned ROBOTS_DISALLOWED |  |
| IDN | peraturan.go.id | consolidated_portal | Loaded directly. Live but displaying a 'Website dalam perbaikan' (under repair) banner with a fallback search link, alongside working links to Lembaran Negara (State Gazette), Berita Negara (State Bulletin), Rancangan Peraturan (draft regulations), and a publi… [truncated, 284 chars in the catalog] |  |
| INT | documentation.ecowas.int | consolidated_portal | Search snippets confirm 'ECOWAS Documentation on-line' at documentation.ecowas.int, with a 'Legal Documents' section listing Treaties, Regulations/Acts, Decisions, Protocols and Publications; individual protocol PDFs are hosted under /download/en/legal_documen… [truncated, 273 chars in the catalog] |  |
| INT | eccis.org | consolidated_portal | Loaded e-cis.info/reestr/, the CIS Internet Portal's public document-registry page, which links directly to the CIS Executive Committee's own 'Unified Register of Legal Acts and Other Documents of the CIS' at eccis.org/reestrv2/; the portal's front page carrie… [truncated, 320 chars in the catalog] |  |
| MMR | mlis.gov.mm | consolidated_portal | Launch and scope (hosting the Burma Code Vol. 1-13, 1955-present, plus subsidiary legislation, built with Korea International Cooperation Agency support) reported by the Myanmar Times and independently cross-linked from the Constitutional Tribunal of Myanmar's… [truncated, 324 chars in the catalog] |  |
| MOZ | inm.gov.mz | gazette | inm.gov.mz (Imprensa Nacional de Moçambique, E.P., founded 1854) self-describes as the body responsible for printing, distributing and selling the Boletim da República (I/II/III Série), and states it "provides public access to the legislative database" — wordi… [truncated, 309 chars in the catalog] |  |
| MRT | msgg.gov.mr | consolidated_portal | Search-result snippet shows page content '16 Codes consolidés' (e.g. Code des investissements 2025, Code de l'urbanisme 2024, Code de l'hydrogène vert 2024); direct fetch blocked by robots.txt |  |
| MRT | msgg.gov.mr | gazette | Search snippet: 'Journaux officiels de Mauritanie de 1958 à aujourd'hui'; direct fetch blocked by robots.txt; count corroborated by Nov-2025 news coverage of the relaunch |  |
| MYS | federalgazette.agc.gov.my | gazette | Confirmed live and current via a search-indexed 2026 gazette entry (P.U.(A) 252/2026, Income Tax rules) on this exact domain. Direct fetch of the root page was robots-disallowed. |  |
| MYS | lom.agc.gov.my | consolidated_portal | Confirmed by IALS Digital Resources (academic law-library catalog) and Thomson Reuters Practical Law; a search-indexed page footer reads 'Copyrights © 2026 All Rights Reserved by Attorney General's Chambers of Malaysia'. Direct fetch is robots-disallowed. |  |
| PNG | paclii.org | consolidated_portal | Direct fetch of the PacLII consolidated-legislation page was blocked by bot detection. Confirmed instead via a University of Melbourne library guide (Consolidated Legislation 1905-2014; Sessional Legislation 1974-current) and a paclii.org/pg/indices/legis/ sea… [truncated, 405 chars in the catalog] |  |
| SEN | jo.gouv.sn | gazette | Search snippets confirm ADIE launched jo.gouv.sn publishing JO texts since 2001; direct fetch blocked by robots.txt |  |
| TCD | journalofficiel.gouv.td | gazette | journalofficiel.gouv.td appears in search as the place to consult Chad's Journal Officiel online. A September/October 2025 SGG news item describes this platform as being in the "final stage of deployment" at that time, so its live history is short. |  |
| THA | krisdika.ocs.go.th | consolidated_portal | Confirmed as the Council of State's official consolidated law database by Thomson Reuters Practical Law, PyThaiNLP's public dataset, and the Library of Congress. www.krisdika.go.th/ (root) 404s this session, while deep links under krisdika.ocs.go.th/web/... ar… [truncated, 404 chars in the catalog] |  |
| THA | ratchakitcha.soc.go.th | gazette | Publisher is the Secretariat of the Cabinet. Confirmed current via third-party compliance sources citing direct document links as recent as 12 Dec 2025 (ratchakitcha.soc.go.th/documents/98728.pdf). Direct fetch of the site was blocked by bot detection this ses… [truncated, 265 chars in the catalog] |  |
| UKR | zakon.rada.gov.ua | consolidated_portal | zakon.rada.gov.ua confirmed as the Verkhovna Rada's official consolidated legislation database via Ukrainian Wikipedia and numerous citing sources; direct fetch of the root domain and its gazette section (laws/main/b19) both returned ROBOTS_DISALLOWED, so no p… [truncated, 291 chars in the catalog] |  |
| VNM | congbao.chinhphu.vn | gazette | Loaded directly — showed Công báo số 403 dated 16/07/2026 with full-text links and a working PDF download. Separately fetched the RSS feed above and confirmed well-formed RSS 2.0 XML with live, dated items through May 2026. |  |
| VNM | vbpl.vn | consolidated_portal | Multiple concurrent Vietnamese state-media outlets (Vietnam+/VNA, SGGP, VOV, Vietnam Law Magazine) independently confirm an upgraded version of this Ministry of Justice database went live at this exact domain on 23 April 2026, restructured down to individual a… [truncated, 276 chars in the catalog] |  |
| ZWE | jsc.org.zw | gazette | Wikipedia's "Government Gazette (Zimbabwe)" article explicitly lists jsc.org.zw/gazette.php as the "Official website," distinguishing it from gazettes.africa, which it labels "Unofficial: Republishes print publications." Independently found jsc.org.zw hosting… [truncated, 323 chars in the catalog] |  |

## 4. Recorded as down or non-functional — 4

The row's prose says the site was unreachable, in maintenance or serving a placeholder when it was checked. A dated observation ages; the decision is whether to re-check, park or drop.

| Country | Domain | Kind | What the catalog records | Decision (Re-check / park / drop) |
| --- | --- | --- | --- | --- |
| FJI | laws.gov.fj | consolidated_portal | Loaded laws.gov.fj/Home/laws directly. Run by the Office of the Attorney-General; offers an A-Z browsable list of Principal and Subsidiary consolidated laws, plus a separate "Laws as Published" (gazetted Acts/Legal Notices) section. No aggregate total is displ… [truncated, 332 chars in the catalog] |  |
| GRD | laws.gov.gd | consolidated_portal | laws.gov.gd currently returns a static 'Upgrading...' maintenance placeholder rather than the legislation tool; www.laws.gov.gd/index.php/acts returned an HTTP 409 error. Site content (Acts index, informational-use disclaimer) is otherwise known only from an i… [truncated, 297 chars in the catalog] |  |
| MLI | sgg-mali.ml | gazette | Fetched page header: '2403 Journaux officiels sur 67 Années', issues current through June 2026 |  |
| SUR | dna.sr | consolidated_portal | dna.sr/wetgeving/surinaamse-wetten/ pages split into pre-2005 (Geldende teksten t/m 2005) and post-2005 (Wetten na 2005) laws, including a December 2024 new Burgerlijk Wetboek entry |  |

