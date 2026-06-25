CATALOG REPORT - gap-fill source set (second pass complete)
Built 2026-06-25. Companion to sources.yml / sources.csv.
Plain text, no markdown emphasis, copy-paste friendly.

Totals: 105 verified rows, 105 unique domains, 0 validation errors.
59 distinct ISO-2 countries/territories + 5 transnational rows.
Confidence: 90 high, 15 medium, 0 low. Every row enabled:false for operator review.
No mono-stance regions remain. All nine source_type values are now represented.

Note on region buckets: the schema's region field is continental. The Caribbean
target therefore splits across two values - island states sit in north-america,
while the mainland Caribbean states Guyana and Suriname sit in south-america. Read
"north-america + south-america" together as the Caribbean slice (16 rows, 8 states).


====================================================================
1. COVERAGE BY REGION  (sources + distinct countries)
====================================================================

region            sources   countries   transnational
----------------  -------   ---------   -------------
north-america         12           6        +1   (Caribbean islands: bb cu do ht jm tt)
south-america          4           2        +0   (mainland Caribbean: gy sr)
oceania               15          11        +1   (Pacific: ck fj mh nc pf pg pw sb to vu ws)
africa                48          24        +3   (SSA + N-Africa MENA + institutional)
asia                  26          16        +1   (Central Asia + Levant/Gulf/Israel + S/SE Asia)
----------------  -------   ---------   -------------
TOTAL                105          59        +5

Distinct countries by target-gap priority:
  1 Caribbean states/territories ...... jm bb tt do cu ht gy sr                       (8)
  2 Pacific island states/territories . vu ws fj to pg sb ck mh pw pf nc              (11)
  3 sub-Saharan Africa ................ ng ke za gh ug tz zw zm na bw rw mw et sn cd cm ao mz cv lr  (20)
  4 Central Asia ...................... kz kg uz                                      (3)
  5 MENA / North Africa ............... eg ma tn dz lb qa sa il                       (8)
  6 South / SE Asia ................... pk in bd lk id my ph th mm                    (9)
  7 Lusophone / Francophone Africa .... lusophone: ao mz cv ;  francophone: sn cd cm dz
  Transnational ..................... CARICOM, PINA, Dubawa, African Union, ISS Africa,
                                      The Times of Central Asia

Second-pass additions (11 new rows, all confidence=high):
  NCN (Guyana, state broadcaster)  -> fixes the south-america mono-stance flag
  Tahiti Infos (pf), Les Nouvelles Caledoniennes (nc)  -> French Pacific, fr
  FrontPage Africa (lr), Daily Observer (lr)  -> Liberia
  TSA (dz, independent), APS (dz, state wire)  -> Algeria, plural pair
  African Union (igo), ISS Africa (academic-research),
  Statistics South Africa (data-portal), SAnews (government-primary)
    -> fill the four previously-missing non-news source types


====================================================================
2. STANCE / TYPE MATRIX  (so plurality is visible)
====================================================================

OWNERSHIP x REGION
(ownership: independent | state-media | public-broadcaster | wire-agency | government;
 plus igo / ngo-civil-society for institutional rows where the bucket does not fit)

region            indep  state  pub-bcast  wire  govt   igo  ngo-cs
----------------  -----  -----  ---------  ----  ----   ---  ------
north-america        10      1          0     0     0     1       0
south-america         3      0          1     0     0     0       0
oceania              12      0          2     0     0     0       1
africa               32      7          2     4     2     1       0
asia                 21      2          0     3     0     0       0
----------------  -----  -----  ---------  ----  ----   ---  ------
TOTAL                78     10          5     7     2     2       1

Mono-stance flag: NONE. Every region now carries a state/public/government baseline
alongside independents. The previously-flagged south-america slice was resolved by
adding NCN (Guyana's state-owned broadcaster) next to independent Kaieteur News.
Sample intra-region plurality:
  - Cuba: state Granma vs independent 14ymedio + Diario de Cuba
  - Guyana: state NCN vs independent Kaieteur News
  - Algeria: independent TSA vs state wire APS
  - Uganda: independent Monitor vs state New Vision; Zimbabwe: NewsDay vs The Herald
  - Ghana: state Graphic vs independent MyJoy/Citi; Egypt: state Al-Ahram vs Mada Masr
  - South Africa: independents (News24, Daily Maverick, M&G, amaBhungane) + public
    broadcaster SABC + government SAnews + data portal Stats SA
  - Gulf: state-funded Al Jazeera (Qatar) vs Saudi Al Arabiya/Arab News
  - Fiji & Solomon Is.: independent press vs public broadcaster (FBC, SIBC)

SOURCE_TYPE (totals) - all nine values now represented
  news .............. 82
  investigative ..... 13   (amaBhungane, Daily Maverick, M&G, Premium Times, Mada Masr,
                            Nawaat, Addis Standard, Kaieteur, Samoa Observer, Tempo,
                            Rappler, The Wire, FrontPage Africa)
  geopolitical ......  2   (Al Jazeera, Times of Central Asia)
  ngo-civil-society .  2   (AlterPresse, PINA)
  igo ...............  2   (CARICOM, African Union)
  fact-checker ......  1   (Dubawa)
  academic-research .  1   (ISS Africa)
  data-portal .......  1   (Statistics South Africa)
  government-primary   1   (SAnews)
  NOT REPRESENTED: none.

EDITORIAL LEAN (totals; assigned only where a widely-cited, contestable assessment exists)
  lean-left ......... 1   (Haaretz)
  lean-center-left .. 1   (The Hindu)
  center ............ 1   (The Times of Israel)
  lean-center-right . 0
  lean-right ........ 1   (The Jerusalem Post)
  omitted / unknown . 101 of 105
Reading: a left-right lean is reported on only 4 rows. This is deliberate - for the
great majority of Global-South outlets no widely-cited left-right rating exists, so
lean is omitted rather than guessed. Richest spread is the Israel English trio
(left / center / right). The one gap on the assigned axis is lean-center-right.

LANGUAGE (totals; all within the managed set, all Global-South editions)
  en 70 | fr 13 | es 5 | ru 5 | pt 4 | ar 3 | id 3 | nl 2
8 of the 17 managed languages are exercised. fr grew via the French Pacific (pf, nc)
and Algeria (dz). Non-en pickups span nl (Suriname), ru (Central Asia), id (Indonesia),
pt (Lusophone Africa), ar (Egypt/Morocco), fr (Haiti, Francophone Africa, Lebanon,
Tunisia, Algeria, French Pacific).

CONFIDENCE (totals)
  high 90 | medium 15 | low 0


====================================================================
3. RSS FEEDS  (populated only where the feed URL was seen verbatim in results)
====================================================================
5 of 105 rows now carry a verified rss_url:
  Premium Times .... https://www.premiumtimesng.com/feed         (awesome-rss-feeds OPML)
  Daily Maverick ... https://www.dailymaverick.co.za/dmrss       (Feedspot SA directory)
  Mail & Guardian .. https://mg.co.za/feed                       (Feedspot SA directory)
  The Hindu ........ https://www.thehindu.com/feeder/default.rss (awesome-rss-feeds OPML)
  ANTARA ........... https://en.antaranews.com/rss/news.xml      (Feedspot SE-Asia directory)

All five appeared as explicit feed URLs in feed directories / OPML files; none was
guessed. Other feeds were left empty rather than inferred. Remaining feed discovery is
a clean follow-up: most outlets run standard CMSs with discoverable feeds, but each
should be confirmed (directory listing or fetched <link rel=alternate>) before enabling.


====================================================================
4. BLOCKED-BY-LANGUAGE  (worklist for when stoplists expand)
====================================================================
Countries/cases whose MAIN domestic outlets publish in languages NOT in the managed
set. Managed set excludes, among others: fa he tr hi bn ur sw am th vi my km lo mn
tl ms zh ko ja ka hy az kk ky uz tg tk.

Fully blocked (no managed-language flagship found):
  - Iran (fa) - IRNA/Tehran Times/Press TV have en editions.
  - Afghanistan (fa/ps) - TOLOnews has en.
  - Mongolia (mn); Cambodia (km); Laos (lo); Eritrea (ti).
  - Maldives (dv); Bhutan (dz) - Kuensel has en; Brunei (ms; note ms is NOT managed).

Partial - country included via a managed-language edition, but most domestic press is
in an unmanaged language (candidates to broaden once the language is enabled):
  - Thailand (th) - included via Bangkok Post (en).
  - Myanmar (my) - included via The Irrawaddy (en).
  - Ethiopia (am/om) - included via Addis Standard (en).
  - Vietnam (vi) - no row yet; VnExpress/Vietnam News have en (see W-5).
  - Turkmenistan (tk) - closed space; ru-language exile outlets exist under managed ru.

Biggest unlocks by target region: sw (East Africa), hi/bn/ur (South Asia), am (Horn),
th/vi/my/km (SE Asia), fa (Iran/Afghanistan), ms (Malaysia/Brunei), he (Israel domestic),
kk/ky/uz (Central Asia).


====================================================================
5. COULD-NOT-VERIFY (excluded) and AMBIGUOUS (included with caveat)
====================================================================
DEFUNCT / closed - deliberately EXCLUDED (verification caught these):
  - Loop News (loopnews.com), Caribbean regional. Ceased operations June 2025.
  - Stabroek News (stabroeknews.com), Guyana. "Last edition" notices; publisher Guyana
    Publications Inc in liquidation. (Guyana is covered by Kaieteur News + NCN.)

AMBIGUOUS DOMAIN - INCLUDED but flagged (confidence: medium):
  - The Herald (Zimbabwe). The domain that resolved live with current Zimpapers content
    was heraldonline.co.zw, NOT the commonly cited herald.co.zw. Catalog uses
    heraldonline.co.zw; reconcile the canonical domain before enabling.


====================================================================
6. WORKLIST  (remaining - real sources whose domain was not confirmed this session;
   NOT fabricated, NOT included; verify, then add)
====================================================================
Cleared this pass: W-1 (NCN Guyana), W-2 (Tahiti Infos, LNC), W-3 (FrontPage Africa,
Daily Observer), W-4 (TSA, APS), and most of W-7/W-8 (African Union, ISS Africa,
Stats SA, SAnews). Remaining:

W-1b Suriname state baseline: STVS/SRS or government info service (Suriname still all-
     independent at country level, though south-america overall is no longer mono-stance).
W-5  SE Asia state contrast: VnExpress International (Vietnam, vn, en).
W-6  Stance plurality fill-ins:
       Senegal independent (Sud Quotidien / Le Quotidien) to pair with state Le Soleil;
       Tanzania state Daily News (dailynews.co.tz) to pair with independent The Citizen;
       Kazakhstan state Kazinform / Astana Times to pair with independent Tengrinews/Vlast;
       Jordan Times (semi-official, en) for Levant breadth.
W-7b More institutional sources: Pacific Islands Forum (forumsec.org, oceania igo),
       ASEAN (asean.org, asia igo), ECOWAS. Note: truly global data portals such as
       ReliefWeb (reliefweb.int) do not map onto the continental region field - consider
       adding a 'global'/'transnational' region value to the app schema for these.
W-8b Investigative / fact-check: Maka Angola (makaangola.org, Angola, pt, anti-corruption);
       Africa Check (africacheck.org, pan-African - would be a second fact-checker).
W-9  Under-covered Lusophone state: Tela Non (telanon.info, Sao Tome e Principe, pt).
W-10 Central Asia breadth: Asia-Plus (asiaplustj.info, Tajikistan, ru/en, independent).


====================================================================
7. METHODOLOGY and CONFIDENCE BASIS
====================================================================
How verified: each domain was matched to a live or current outlet via web-search
corroboration on 2026-06-25. No domain, feed URL, or outlet was invented. Outlets that
could not be tied to a confirmed resolving domain in results were sent to the worklist
(section 6), not the catalog.

confidence = high (90 rows): a current/live homepage or section was observed in results
  with recent content, OR the outlet is internationally prominent with current reputable
  references and an unambiguous established domain. All 11 second-pass additions are high
  (each had a live homepage with current content this session).
confidence = medium (15 rows): the registrable domain is corroborated by a reputable
  source (Wikipedia, a university library guide, an established media directory, RSF, or
  a feed directory) but a fresh live homepage was not directly captured, or there is a
  minor domain caveat. The 15 medium rows and their basis:
    Post-Courier (postcourier.com.pg) - AARoads Oceania wiki + 2025 PIR roundups.
    SIBC (sibconline.com.sb) - AARoads Oceania wiki; state broadcaster site.
    Marshall Islands Journal (marshallislandsjournal.com) - AARoads wiki + UC guide.
    Island Times / Palau (islandtimes.org) - AARoads Oceania wiki.
    NAN (nannews.ng) - Stanford Nigeria library guide.
    KBC (kbc.co.ke) - Stanford Kenya library guide.
    SABC News (sabcnews.com) - Stanford South Africa library guide.
    GNA (gna.org.gh) - Stanford Ghana library guide.
    The Herald (heraldonline.co.zw) - live in results; canonical-domain caveat (sec.5).
    Mmegi (mmegi.bw) - Wikipedia WikiProject Africa sources list.
    Business News (businessnews.com.tn) - RSF Tunisia 2026 confirms current relevance;
      domain is the standard eTLD+1 per Tunisia press directories.
    Vlast (vlast.kz) - Harvard Caspiana media guide.
    ANTARA (antaranews.com) - state agency; en edition + RSS confirmed via feed directory.
    Bangkok Post (bangkokpost.com) - SE-Asia feed directory ("Website bangkokpost.com").
    The Irrawaddy (irrawaddy.com) - SE-Asia feed directory; exile-operated.

Label notes (descriptive, contestable - not quality scores):
  - Al Jazeera (qa) and Al Arabiya (sa): tagged state-media because they are state-
    funded/owned international networks (Qatar government; Saudi-owned MBC), not domestic
    public-service broadcasters. Contestable.
  - Arab News (sa): tagged independent ownership with a state-aligned-editorial tag -
    privately owned (SRMG) but broadly reflects Saudi establishment positions.
  - NCN (gy), FBC (fj), SIBC (sb), SABC (za): tagged public-broadcaster (state-owned
    broadcasters). NCN and SABC are clearly state-controlled; tag reflects org type.
  - APS (dz), MAP (ma), NAN (ng), GNA (gh), Kabar (kg), ANTARA (id): wire-agency; the
    state-owned ones additionally carry a state-owned/government tag.
  - SAnews (za) and Stats SA (za): ownership = government (GCIS news service; national
    statistics office). Source types government-primary and data-portal respectively.
  - African Union (au.int): ownership = igo; source_type igo (also a government-primary
    institutional source).
  - ISS Africa (issafrica.org): independent nonprofit research institute (think-tank);
    re-publishing partners include Daily Maverick and Premium Times.
  - The New Times (rw): privately owned but widely described as government-leaning; a
    left-right lean is not applied (its alignment is pro-incumbent, not L-R).
  - Radio Okapi (cd): editorially independent, funded/operated via UN MONUSCO +
    Fondation Hirondelle (tagged accordingly).
  - state-media tags reflect OWNERSHIP (state/government), not editorial quality;
    editorial latitude varies by outlet.
  - lean values (Haaretz / Times of Israel / Jerusalem Post / The Hindu) are reputational
    and contestable, drawn from widely-cited media-bias discourse.

Files in this delivery:
  sources.yml  - the catalog, grouped by region then country (primary artifact).
  sources.csv  - same rows flattened (adds derived ownership/lean columns) for ingestion.
  catalog_report.md - this report.
