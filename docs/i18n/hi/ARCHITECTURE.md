<!-- hi: Translation of docs/ARCHITECTURE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 28 of 28 headings. Corrections are welcome as a pull request. -->

# वास्तुकला और तकनीकी संदर्भ

उपयोगकर्ता पुस्तिका (User Manual) का तकनीकी साथी: डेटाबेस/कॉन्फ़िगरेशन, HTTP API का नक्शा, और अंतर्राष्ट्रीयकरण।

## विषय-सूची
- [Open Omniscience के लिए डेटाबेस कॉन्फ़िगरेशन](#open-omniscience-क-लए-डटबस-कनफगरशन)
- [API संदर्भ](#api-सदरभ)
- [अंतर्राष्ट्रीयकरण (i18n) — ऐप को बहुभाषी बनाना](#अतररषटरयकरण-i18n--ऐप-क-बहभष-बनन)


---

## Open Omniscience के लिए डेटाबेस कॉन्फ़िगरेशन

> **स्थिति (v0.0.7 ऑडिट में सत्यापित, `docs/archive/audits/00_BASELINE.md`):** डेटाबेस परत
> **काम करती है और परीक्षित है** — सर्वर boot होता है, SQLite store बनाता/उपयोग करता है, Alembic
> migrations लागू करता है, और पूरा test suite (800+) उसके विरुद्ध पास होता है। पुराना "प्रारंभिक अवधारणा —
> काम नहीं करता" बैनर जो पहले यहाँ था, rebuild से पहले की स्थिति का वर्णन करता था और लंबे समय से
> पुराना हो चुका था।

### 🗃️ SQLite — समर्थित store

SQLite **डिफ़ॉल्ट और एकमात्र समर्थित, परीक्षित backend** है। यह उत्पाद के local-first,
एकल-ऑपरेटर डिज़ाइन के अनुकूल है।

- **शून्य कॉन्फ़िगरेशन:** डेटाबेस पहली बार चलाने पर स्वचालित रूप से
  `<data dir>/open_omniscience.db` पर बनता है। data dir `OO_DATA_DIR` है यदि वह सेट हो, अन्यथा
  source checkout में repo का `data/`, अन्यथा `$XDG_DATA_HOME/open-omniscience` (`src/paths.py` देखें)।
- **स्वचालित रूप से समायोजित:** engine हर connection पर `WAL` journal mode, `foreign_keys=ON`,
  `busy_timeout=30000` और `synchronous=NORMAL` लागू करता है (`src/database/session.py`) —
  आपको इन्हें स्वयं सेट करने की आवश्यकता नहीं है।
- **पूर्ण-पाठ खोज** SQLite **FTS5** है (`article_fts`, external-content, triggers द्वारा समन्वित रखी
  जाती है — `src/database/fts.py`)।
- **स्थान बदलें** `DATABASE_URL` environment variable से (स्रोत फ़ाइलें संपादित **न** करें):
  `DATABASE_URL=sqlite:////absolute/path/to/your.db`
- **रखरखाव:** कभी-कभार `sqlite3 <db> "VACUUM;"` जगह वापस पाता है (v0.0.7 ऑडिट ने एक अनावश्यक
  index भी हटाया जो बड़े corpora पर फ़ाइल का ~63% था; मौजूदा डेटाबेस से उसे हटाने के लिए upgrade के
  बाद एक बार `make migrate` चलाएँ)।

### 🐘 PostgreSQL — प्रायोगिक ढाँचा, समर्थित नहीं

आकांक्षा से ऊपर ईमानदारी (ऑडिट निष्कर्ष ARCH-06): engine परत PostgreSQL `DATABASE_URL` को
*पहचानती* है (`DB_POOL_SIZE`/`DB_MAX_OVERFLOW` के माध्यम से connection pooling), **लेकिन**

- **PostgreSQL पर पूर्ण-पाठ खोज मौजूद नहीं है** — FTS5 setup गैर-SQLite engines पर जानबूझकर
  कुछ नहीं करता, इसलिए खोज टैब निष्क्रिय होगा;
- test suite कभी PostgreSQL के विरुद्ध नहीं चलता, और कोई CI इसे कवर नहीं करता;
- किसी प्रकाशित deployment ने इसका उपयोग नहीं किया है।

PostgreSQL को **संभावित भविष्य के लिए अपरीक्षित ढाँचा** मानें, ऐसा विकल्प नहीं जिसे आप आज चुन सकें।
यदि कभी multi-writer पैमाना वास्तविक आवश्यकता बनता है, तो roadmap आइटम एक `tsvector` खोज-पथ और
एक PostgreSQL CI matrix है — जब तक वह नहीं आता, यह पृष्ठ दिखावा नहीं करेगा।

### 🔄 Migrations

Alembic **repository root** पर कॉन्फ़िगर है (`alembic.ini`, `migrations/`)। Alembic ऐप के साथ
स्थापित होता है (यह एक मूल निर्भरता है — अलग से स्थापना की आवश्यकता नहीं)।

- **नए डेटाबेस** पूर्ण रूप में बनाए जाते हैं (`create_all` + FTS) और startup पर स्वचालित रूप से
  मौजूदा migration head के साथ stamp किए जाते हैं।
- **मौजूदा डेटाबेस को upgrade करना:**
  ```bash
  make migrate          # = alembic upgrade head, from the repo root
  ```
- **Migration बनाना** (योगदानकर्ता): `src/database/models.py` संपादित करें, फिर
  ```bash
  alembic revision --autogenerate -m "your message"
  alembic upgrade head
  ```
  और बनी हुई फ़ाइल जाँचें — autogenerate FTS virtual tables को छोड़ देता है (वे
  `src/database/fts.py` में रहती हैं, startup पर लागू होती हैं)।
- **वापस लौटाना (rollback):** `alembic downgrade -1`।

---

### 📊 डेटाबेस Schema

#### Tables:

##### `sources`
| कॉलम | प्रकार | विवरण |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `name` | STRING(100) | स्रोत का नाम (जैसे "BBC News") |
| `domain` | STRING(255) | स्रोत का डोमेन (जैसे "bbc.com") |
| `rss_url` | STRING(500) | RSS फ़ीड का URL (यदि उपलब्ध हो) |
| `rate_limit_ms` | INTEGER | अनुरोधों के बीच मिलीसेकंड में विलंब |
| `enabled` | BOOLEAN | स्रोत scraping के लिए सक्रिय है या नहीं |
| `priority` | INTEGER | प्राथमिकता स्तर (1 = उच्च, 3 = निम्न) |
| `tags` | STRING(500) | tags की अल्पविराम-पृथक सूची |

##### `articles`
| कॉलम | प्रकार | विवरण |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `url` | STRING(1000) | लेख का मूल URL |
| `canonical_url` | STRING(1000) | Canonicalized URL (दोहराव की पहचान के लिए) |
| `source_id` | INTEGER | `sources` की foreign key |
| `title` | STRING(500) | लेख का शीर्षक |
| `content` | TEXT | लेख की पूर्ण पाठ सामग्री |
| `published_at` | DATETIME | प्रकाशन तिथि/समय (ISO प्रारूप) |
| `language` | STRING(10) | भाषा कोड (जैसे "en", "fr") |
| `hash` | STRING(64) | सामग्री का SHA-256 hash (दोहराव की पहचान के लिए) |
| `created_at` | DATETIME | लेख के ingest होने का timestamp |

> ऊपर के कॉलम मूल फ़ील्ड हैं; live schema (`src/database/models.py`) और
> `migrations/versions/` के अंतर्गत Alembic migrations सत्य का स्रोत हैं।
> `articles` में उत्पत्ति/विश्लेषण फ़ील्ड (author, word_count, region, country, sentiment) और
> एक संपीड़ित-सामग्री कॉलम भी होता है।

##### अन्य tables (पूरे कॉलम के लिए models / migrations देखें)

| Table | उद्देश्य |
|-------|---------|
| `source_groups`, `source_metadata`, `source_group_association` | स्रोत समूहीकरण + geo/robots metadata |
| `commodity_prices` | देखे गए मूल्य-बिंदु (symbol, date, price, currency, **unit**, market, source) — charts + मूल्य↔समाचार सहसंबंध |
| `market_extraction_rules` | प्रति-स्रोत नियम (CSS selector / attribute / regex) जो एक पृष्ठ पर एक instrument का मूल्य खोजता है; श्रेणी financial/stock/commodity |
| `keywords` | विशिष्ट keyword/entity शब्द (normalized, language, `is_entity`/`entity_type`, **`extractor`** उत्पत्ति) |
| `keyword_mentions` | प्रति (article, keyword) एक: गिनती + पहला वर्ण offset + denormalised `observed_on`/`country`/`city` — अंतर्दृष्टि के रुझान, संबंध, संदर्भ, मानचित्र को संचालित करता है |
| `wiki_pages` | एक भाषा संस्करण में एक ट्रैक किया गया Wikipedia पृष्ठ; **एक** संपीड़ित पूर्ण-पाठ baseline रखता है |
| `wiki_revisions` | एक ट्रैक किया गया संपादन: **diff + signed byte delta** + flags/tags (दोबारा प्रति नहीं), वैकल्पिक ORES स्कोर, ईमानदार बड़े-संपादन flag + कारण |
| `article_analyses` | व्युत्पन्न LLM परिणाम (सारांश/अनुवाद) model + prompt उत्पत्ति के साथ |
| `keyword_categories`, `external_sources`, `article_links`, … | Keyword वर्गीकरण + link/स्रोत-संबंध ट्रैकिंग |

#### Indexes:
- `idx_article_hash`: `hash` पर unique index (दोहराव की पहचान के लिए)।
- `idx_article_canonical_url`: `canonical_url` पर index (URL lookups के लिए)।
- `idx_article_source_id`: `source_id` पर index (स्रोत-आधारित queries के लिए)।
- `idx_article_content`: `content` पर index (पूर्ण-पाठ खोज के लिए)।

---

### 🔍 पूर्ण-पाठ खोज

पूर्ण-पाठ खोज **पहले से बनी हुई और जुड़ी हुई** है — सक्षम करने के लिए कुछ नहीं है। store में एक FTS5
external-content table (`article_fts`) होती है जिसे triggers समन्वित रखते हैं; schema के लिए
`src/database/fts.py` और query पथ के लिए `src/api/main.py` में `search_ids` देखें (अंतिम क्रम में
केवल-id resolution, पूरी पंक्तियाँ केवल उस पृष्ठ के लिए लोड होती हैं)।

यह खंड पहले SQLite के लिए "एक virtual table बनाने पर विचार करें" नुस्ख़ा और PostgreSQL के लिए एक
`to_tsvector` नुस्ख़ा देता था। दोनों गलत थे: SQLite वाला हाथ से ऐसी table बनाने का वर्णन करता था
जिसे ऐप स्वयं साथ भेजता और बनाए रखता है (एक *अलग* नाम से, इसलिए उसका पालन करने से एक दूसरा,
बिना-रखरखाव वाला index बन जाता), और यहाँ PostgreSQL का कोई खोज-पथ है ही नहीं, जिसे ऊपर का store
खंड इसके समर्थित backend न होने के पहले कारण के रूप में बताता है।

---

### 📉 निगरानी और रखरखाव

- **डेटाबेस का आकार जाँचें**:
  ```bash
  ls -lh data/open_omniscience.db
  ```
- **Tables के आकार जाँचें**:
  ```bash
  sqlite3 data/open_omniscience.db "SELECT name, COUNT(*) FROM sqlite_master WHERE type='table';"
  ```
  **एन्क्रिप्टेड** store पर `sqlite3` CLI फ़ाइल खोल ही नहीं सकता (यही उसका उद्देश्य है) — ऐप के
  भीतर सेटिंग्स → निदान की सतहों का उपयोग करें, जो store को उसी संरक्षित connection factory के
  माध्यम से पढ़ती हैं जिसका उपयोग ऐप स्वयं करता है।

---

### 🚨 समस्या निवारण

#### सामान्य समस्याएँ:

##### SQLite:
- **"Database is locked"**:
  - SQLite एक समय में केवल एक writer की अनुमति देता है। WAL mode डिफ़ॉल्ट रूप से सक्षम है
    (`src/database/session.py`) और एक process-व्यापी single-writer gate
    (`src/database/writer.py`) ऐप के भीतर के writes को क्रमबद्ध करता है, इसलिए समवर्ती ingest +
    import अब नहीं टकराते। लगातार lock का अर्थ है कि कोई दूसरी *process* लिख रही है।

- **"Too many open files"**:
  - SQLite हर thread के लिए एक नया connection खोलता है। threads की संख्या सीमित करें या connection pooling का उपयोग करें।

- **"Relation does not exist" / "no such table"**:
  - migrations चलाएँ: `alembic upgrade head`।

---

### 📌 सर्वोत्तम प्रथाएँ

1. **बैकअप ऐप के माध्यम से लें, `cp` से नहीं**:
   - सेटिंग्स → बैकअप का उपयोग करें (या एक सुसंगत snapshot के लिए `GET /api/database/backup`)।
     `open_omniscience.db` को हाथ से कॉपी करना बैकअप **नहीं** है: store WAL mode में चलता है,
     इसलिए live फ़ाइल में वह सब नहीं होता जो अभी भी `-wal` में है, और डिफ़ॉल्ट **एन्क्रिप्टेड**
     store पर कॉपी की गई फ़ाइल passphrase के बिना बेकार है और उसमें कोई अखंडता-प्रतिबद्धता नहीं होती।
     ऐप का अपना पथ checkpoint करता है, stream करता है और हस्ताक्षर करता है।

2. **Migrations का परीक्षण करें**:
   - production पर लागू करने से पहले हमेशा अपने डेटाबेस के बैकअप पर migrations का परीक्षण करें।

3. **प्रदर्शन की निगरानी करें**:
   - सेटिंग्स → निदान में slow-query log, request-latency log और write-gate रिपोर्ट होती है;
     `sqlite3` CLI plaintext store पर काम करता है।

4. **Queries को अनुकूलित करें**:
   - `EXPLAIN QUERY PLAN` ही साधन है। ध्यान दें कि SQLite एक साधारण table scan और एक index-only
     scan **दोनों** के लिए `SCAN` लिखता है — `SCAN <table> USING [COVERING] INDEX …` स्वस्थ है;
     संदिग्ध संकेत बिना `USING` वाला साधारण `SCAN <table>` है
     (`src/monitoring/slowquery.py` ठीक इसी आधार पर वर्गीकरण करता है)।

5. **डेटा प्रतिधारण सीमित करें**:
   - डेटाबेस को प्रबंधनीय रखने के लिए पुराने लेखों को नियमित रूप से संग्रहित (archive) करें या हटाएँ।
   - उदाहरण: 1 वर्ष से पुराने लेख हटाएँ:
     ```python
     from datetime import datetime, timedelta
     one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
     session.query(Article).filter(Article.published_at < one_year_ago).delete()
     session.commit()
     ```

---
*कॉपीराइट © 2026 Ideotion. GNU General Public License v3.0 या बाद के संस्करण
(GPL-3.0-or-later) के अंतर्गत लाइसेंस प्राप्त — [LICENSE](../LICENSE) देखें। यह मुक्त सॉफ़्टवेयर है;
आप इसे उन शर्तों के अंतर्गत पुनर्वितरित और संशोधित कर सकते हैं।*


---

## API संदर्भ

हमेशा सटीक, live API संदर्भ ऐप स्वयं बनाता है:

- **Swagger UI / ReDoc:** डिफ़ॉल्ट रूप से बंद (वे तृतीय-पक्ष होस्ट से assets लोड करते हैं); http://127.0.0.1:8000/docs और `/redoc` के लिए ऐप को `OO_API_DOCS=1` के साथ शुरू करें
- **OpenAPI JSON:** http://127.0.0.1:8000/openapi.json

ऐप केवल loopback से bind होता है और (एकल स्थानीय उपयोगकर्ता के लिए) किसी प्रमाणीकरण की आवश्यकता नहीं रखता।

### Endpoint समूह

यह **मुख्य समूहों का नक्शा है, संपूर्ण सूची नहीं** — live `/openapi.json` (ऊपर) हमेशा प्रामाणिक है।
routers `src/api/main.py` में `include_router(...)` के माध्यम से जुड़े हैं; **[analysis]** चिह्नित
समूहों को `[analysis]` extra की आवश्यकता होती है (ऐप उसके बिना भी boot होता है, वे endpoints अक्षम रहते हैं)।

| Prefix | यह क्या करता है |
|--------|--------------|
| `GET /api/health` | Liveness + संस्करण |
| `GET /api/articles`, `/api/articles/export` | Boolean पूर्ण-पाठ खोज (FTS5) + CSV/JSON निर्यात |
| `POST /api/ingest`, `/api/sources/{id}/ingest`, `/api/sources/{id}/ingest-email` | नैतिक ingestion: एकल URL, RSS फ़ीड, IMAP mailbox |
| `… /api/sources`, `/api/sources/...` | स्रोत + समूह + metadata प्रबंधन |
| `POST /api/sources/seed-defaults` | चयनित स्रोत-catalogs को seed करें (समाचार + बाज़ार + बनाया गया विश्व catalog) |
| `GET /api/database/stats`, `/coverage`, `/countries` | Corpus पंक्ति-गिनती + डिस्क पर आकार; देश-कवरेज; प्रति-देश स्रोत गिनती + विषय keywords |
| `GET /api/database/backup` | सुसंगत SQLite snapshot डाउनलोड (केवल plaintext SQLite store; किसी दूसरी साइट से आए अनुरोध या ऐसे Host के लिए अस्वीकृत जिसे DNS-rebinding guard सेवा नहीं देता, और loopback के अलावा किसी नाम पर, ऐसे अनुरोध के लिए जो उस पृष्ठ का नाम नहीं बताता जहाँ से वह आया है, जब तक वह `X-OO-Download: 1` न भेजे; प्रति process एक समय में एक, डेटाबेस के बगल में एक निजी `.oo-backup-*` फ़ोल्डर में लिखा जाता है और डाउनलोड समाप्त होने या process रुकने पर हटा दिया जाता है (kill करने पर यह अगले start के sweep के लिए रह जाता है, जो मृत owner का फ़ोल्डर तुरंत हटा देता है), 507 जब डेटा volume उसे नहीं समा सकता) |
| `POST /api/database/v2/restore/preview`, `/v2/restore/commit`, `/api/backup/v2/*` | हस्ताक्षरित `oo-backup-2` artifact के माध्यम से **केवल-योगात्मक** restore: merge योजना का preview करें, फिर commit करें। Restore **कभी आपके corpus को अधिलेखित नहीं करता** — यह बिना दोहराव के merge करता है, टकराव पर स्थानीय मान रखता है (विनाशकारी replace पथ 2026-06-13 को हटा दिया गया) |
| `GET/PUT /api/settings` | GUI प्राथमिकताएँ (theme, डिफ़ॉल्ट परिणाम सीमा) |
| `… /api/scheduler/...` | पृष्ठभूमि संग्रह: status, start, stop, run-now, config। `0.4` चक्र से संग्रह एक scheduler mode के बजाय **साथ-साथ चलने वाली lanes** के रूप में चलता है (`rss` / `crawl` / `markets` / `wiki` / `law`) — प्रति-lane storage `… /api/storage/...` के अंतर्गत, और **जीवंत स्रोत** टैब `… /api/living/...` पढ़ता है (Wikipedia, क़ानून और मानचित्रों में क्या बदला) |
| `… /api/markets/rules`, `/rules/{id}/run`, `/overview` | प्रति-स्रोत मूल्य-निष्कर्षण नियम + एक "test" run + बाज़ार अवलोकन |
| `GET /api/markets/feeds`, `POST /feeds/{key}/import`, `/feeds/import-url` | आधिकारिक CSV मूल्य-फ़ीड catalog + import (FRED/World Bank/EIA) + कस्टम-URL import |
| `GET /api/catalog/export.csv`, `/template.csv`, `/columns`, `POST /api/catalog/import` | स्रोत-सूची CSV निर्यात / template / कॉलम / डोमेन-आधारित upsert import |
| `… /api/insights/...` | Keyword और entity विश्लेषण: status, reindex, top, trending, trend, associations (PMI), context, map |
| `GET /api/timemap`, `/timemap/range` | एक मानचित्र+समय-अक्ष पर स्थान-काल संकेत (anchors + geocoded corpus + opt-in hazards/उल्लिखित-तिथियाँ); `?kinds`, `?start`/`?end` भिन्नात्मक-वर्ष window, `?hazards`, `?articles`, `?mentions`, `?days` |
| `… /api/article-dates/...` | लेख-पाठ में उल्लिखित, निकाली गई तिथियाँ, मानव-पुष्टि योग्य प्रति-लेख tags के रूप में: प्रति लेख सूची/निष्कर्षण, पुष्टि/अस्वीकार, batch index, तिथि-आधारित corpus filter |
| `GET/POST /api/llm/...` | स्थानीय LLM (Ollama): health, models, generate, किसी लेख का सारांश |
| `… /api/commodities/...` | Commodity मूल्य (import / CSV / list) + ईमानदार मूल्य↔समाचार सहसंबंध |
| `POST /api/analysis/...` | वैज्ञानिक-कठोरता सांख्यिकी: t-test, correlation, ANOVA, Mann-Whitney, CI |
| `GET /api/monitoring/...` | वास्तविक स्रोत-uptime स्वास्थ्य + corpus-मात्रा विसंगतियाँ |
| `POST /api/verify/image-metadata` | ईमानदार छवि EXIF/metadata निष्कर्षण |
| `POST /api/reports/evidence`, `/evidence/verify` | हस्ताक्षरित, छेड़छाड़-प्रकट (tamper-evident) साक्ष्य bundles |
| `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`, `POST /api/custody/export`, `POST /api/custody/verify` | केवल-जोड़ने योग्य, hash-chained हस्ताक्षरित chain-of-custody log + ऑफ़लाइन सत्यापन |
| `GET/PUT /api/custody/settings` | Runtime custody प्राथमिकताएँ (post-quantum signing, anchoring mode, auto-log) — *प्रभावी*, उपलब्धता-सजग स्थिति बताता है |
| `POST /api/custody/anchor`, `GET /api/custody/providers` | एक Merkle root को anchor करें (local / OpenTimestamps) + provider उपलब्धता |
| `POST /api/custody/reconcile` | किसी विफलता के कारण बकाया रह गई INGEST प्रविष्टियाँ लिखें, प्रत्येक अपने हस्ताक्षरित metadata में देर से दर्ज के रूप में चिह्नित; `scan` पुराने अंतरालों को गिनता है, `record_gaps` उन्हें queue करता है (2026-09-24, CUST-1) |
| `… /api/keywords/...`, `/api/analysis/articles/similarity` | **[analysis]** Keyword निष्कर्षण + लेख समानता |
| `GET /api/search/omni` | Index-आधारित federated omnibar (articles FTS5 + keywords + sources + wiki/law) |
| `… /api/jobs/...` | Task-manager job एकत्रीकरण (collect pass, चालू fetch, wiki-dump queue + पुनः क्रम) |
| `… /api/system/...` | System vitals + network स्थिति/सहमति (airplane-mode kill switch, स्थानीय interface IPs) |
| `… /api/safety/...` | सुरक्षा नियंत्रण: kill switch, discovery gate, एन्क्रिप्टेड artifact से restore |
| `… /api/briefing/...` | मुखपृष्ठ briefing producers (साक्ष्य-स्तरीय cards; विधि+चेतावनी+n) |
| `… /api/insights/...`, `/api/insights/who`, `/where` | Keyword/entity विश्लेषण + corpus-व्यापी Who/Where एकत्रीकरण |
| `… /api/links/...` (shared, preview) | साझा-बाहरी-link / citation-graph विश्लेषण + स्थानीय link-preview dialog |
| `… /api/events/...`, `/api/events/astronomy`, `/climate` | कार्यसूची घटनाएँ, जिनमें स्थानीय रूप से गणना की गई खगोल-विज्ञान (Meeus) + El Niño तालिका शामिल |
| `POST /api/weather/context` | पुष्टि के लिए सहमति-प्राप्त, सीमित Open-Meteo reanalysis अंश |
| `… /api/law/...` | ट्रैक किया गया विधान/प्राथमिक-स्रोत परिवर्तन फ़ीड |
| `… /api/integrity/...` | Echo / समन्वय / वंशावली संकेत |
| `… /api/annotations/...` | स्थानीय, वैकल्पिक रूप से हस्ताक्षरित लेख annotations |
| `… /api/wiki/...` | Wikipedia संस्करण, निगरानी किए गए पृष्ठ, dump डाउनलोड/पढ़ना, corpus sync |
| `… /api/hazards/...`, `/api/timemap` | Hazard overlays + स्थान-काल मानचित्र |
| `GET /unlock`, `POST /api/unlock`, `/create-db`, `/doctor`, `/encrypt-db` | विश्राम-अवस्था में एन्क्रिप्शन: locked-boot unlock स्क्रीन, एन्क्रिप्टेड/plaintext store बनाना, header सत्यापन, एकतरफ़ा encrypt टूल |

**[analysis]** चिह्नित routers (commodities, statistics, keywords, framing) को `[analysis]` extra
की आवश्यकता होती है; उसके बिना ऐप फिर भी मूल ढाँचे के साथ boot होता है और वे endpoints अक्षम रहते हैं।

व्यवहार संबंधी टिप्पणियाँ:
- Ingestion केवल नैतिक fetcher के माध्यम से fetch करता है (robots.txt fail-closed, दर-सीमित);
  यदि Ollama उपलब्ध नहीं है तो LLM endpoints **503** लौटाते हैं (कभी नकली उत्तर नहीं)।
- साक्ष्य सत्यापन: केवल अखंडता ही नहीं, उत्पत्ति सिद्ध करने के लिए हस्ताक्षरकर्ता की public key दें
  ([QUICKSTART](QUICKSTART.md) और `scripts/verify_evidence.py` देखें)।
- Custody settings *प्राथमिकताएँ* हैं, गारंटी नहीं: `GET/PUT /api/custody/settings` हमेशा
  **प्रभावी** स्थिति बताते हैं (प्राथमिकता **और** library उपलब्धता), इसलिए post-quantum /
  OpenTimestamps कभी सक्षम नहीं दिखते जब सहायक extra अनुपस्थित हो। Anchoring डिफ़ॉल्ट रूप से
  ऑफ़लाइन `local` provider का उपयोग करता है; OpenTimestamps और public-chain anchoring के साथ एक
  निजता चेतावनी होती है ([CHAIN_OF_CUSTODY](USER_MANUAL.md) देखें)।


---

## अंतर्राष्ट्रीयकरण (i18n) — ऐप को बहुभाषी बनाना

> लक्ष्य: **पूरा UI** (और, समय के साथ, **दस्तावेज़ीकरण**) लगभग एक दर्जन भाषाओं में उपलब्ध, ताकि
> खुली पहुँच "लगभग सभी मनुष्यों" तक विस्तृत हो। परियोजना के तरीके से किया गया: **ऑफ़लाइन, कोई CDN
> नहीं, कोई runtime अनुवाद API नहीं, कोई telemetry नहीं**, और अनुवाद की गुणवत्ता के बारे में
> **ईमानदार** (हम मशीनी अनुमानों को ऐसे नहीं भेजते मानो वे प्रामाणिक हों)।

---

### एक दर्जन भाषाएँ (Phase 1 समूह)

पहुँच (मूल + द्वितीय-भाषा बोलने वालों) के आधार पर, और जानबूझकर Global South को शामिल करने के लिए
चुनी गईं (`ROADMAP.md` के पूर्वाग्रह-विरोधी लक्ष्य के अनुसार):

| कोड | भाषा | मूल नाम | लिपि / दिशा | स्थिति |
|---|---|---|---|---|
| `en` | अंग्रेज़ी | English | LTR | **स्रोत** (पूर्ण) |
| `fr` | फ़्रेंच | Français | LTR | **पूर्ण** (प्रमाणित) |
| `es` | स्पेनिश | Español | LTR | **पूर्ण** (प्रमाणित) |
| `de` | जर्मन | Deutsch | LTR | **पूर्ण** (प्रमाणित) |
| `zh` | चीनी (मंदारिन) | 中文 | LTR | पूर्ण (अनूदित, `0.4` चक्र; अभी प्रमाणित नहीं) |
| `hi` | हिन्दी | हिन्दी | LTR | पूर्ण (अनूदित, `0.4` चक्र; अभी प्रमाणित नहीं) |
| `ar` | अरबी | العربية | **RTL** | पूर्ण (अनूदित, `0.4` चक्र; अभी प्रमाणित नहीं) |
| `bn` | बांग्ला | বাংলা | LTR | पूर्ण (अनूदित, `0.4` चक्र; अभी प्रमाणित नहीं) |
| `ru` | रूसी | Русский | LTR | पूर्ण (अनूदित, `0.4` चक्र; अभी प्रमाणित नहीं) |
| `pt` | पुर्तगाली | Português | LTR | पूर्ण (अनूदित, `0.4` चक्र; अभी प्रमाणित नहीं) |
| `id` | इंडोनेशियाई | Bahasa Indonesia | LTR | पूर्ण (अनूदित, `0.4` चक्र; अभी प्रमाणित नहीं) |
| `ja` | जापानी | 日本語 | LTR | पूर्ण (अनूदित, `0.4` चक्र; अभी प्रमाणित नहीं) |

पहुँच के लिए आसान अगली भाषाएँ: **स्वाहिली (`sw`)**, **उर्दू (`ur`, RTL)**, इतालवी (`it`),
तुर्की (`tr`), वियतनामी (`vi`)।

**ईमानदारी का रुख।** एक *stub* किसी भाषा को **अभी चुनने योग्य** बनाता है और किसी भी अनअनूदित string
के लिए अंग्रेज़ी पर लौट आता है — आंशिक locale कभी UI नहीं तोड़ता (यही वह तंत्र है जिससे भविष्य का
कोई भी locale — `it`, `tr`, `vi`, … — शुरू होता है)। हम प्रत्येक locale को `complete | draft | stub`
चिह्नित करते हैं। maintainer केवल वही भेजते हैं जिसकी वे पुष्टि कर सकें; बाकी सब **सामुदायिक योगदान**
से भरा जाता है (ठीक इसी तरह open-source पहुँच का विस्तार करता है)।

---

### वास्तुकला (ऑफ़लाइन, निर्भरता-मुक्त)

`src/static/i18n.js` + `src/static/locales/<code>.json`। कोई build चरण नहीं, कोई network नहीं।

- **अंग्रेज़ी ही key है।** Locale फ़ाइलें **अंग्रेज़ी UI string → उसका अनुवाद** map करती हैं
  (जैसे `"Search the corpus": "Rechercher dans le corpus"`)। इससे हम हर element को tag किए बिना
  मौजूदा UI में इसे बाद में जोड़ सकते हैं, और अंग्रेज़ी प्रामाणिक स्रोत बनी रहती है।
- **`OOI18N.setLang(code)`** `locales/<code>.json` लोड करता है, चुनाव को `localStorage` (`oo.lang`)
  में सहेजता है, `document.documentElement.lang` और `dir` सेट करता है (`ar`/`ur` के लिए RTL), फिर
  **`apply()`** DOM में घूमता है — उन text nodes का अनुवाद करता है जिनका trimmed पाठ किसी key से मेल
  खाता है, साथ ही `placeholder`/`title`/`aria-label` attributes का। अज्ञात strings जैसी हैं वैसी
  छोड़ दी जाती हैं (अंग्रेज़ी fallback) — कुछ भी कभी नहीं टूटता।
- **गतिशील सामग्री** (डेटा: लेख-शीर्षक, स्रोत-नाम, गिनतियाँ) का अनुवाद **कभी नहीं** होता — केवल
  chrome का। JS से render होने वाला chrome (command palette, drawer) render होने के बाद
  `OOI18N.apply()` को call करता है।
- प्रत्येक locale में `_meta` (`name`, `native`, `dir`, `status`) होता है।

#### इसे एकीकृत करना (Phase 2 — भेजा जा चुका; Desk तब से हटा दिया गया है)

`index.html` में दो पंक्तियाँ (और, 2026-06-10 को हटाए जाने से पहले, `desk.html` में), फिर एक भाषा
चयनकर्ता:

```html
<script src="/static/i18n.js"></script>
<!-- after first render and on each view change: --> OOI18N.apply();
```

**भाषा** चयनकर्ता सेटिंग्स में है और `OOI18N.setLang(code)` को call करता है, जो अन्य स्थानीय UI
प्राथमिकताओं के साथ सहेजा जाता है।

---

### कई भाषाओं में दस्तावेज़ीकरण

दस्तावेज़ लंबे होते हैं और छोटी UI strings की तुलना में अनुवाद की गुणवत्ता अधिक मायने रखती है, इसलिए:

- संरचना: `docs/i18n/<code>/<DOC>.md`, `docs/` का प्रतिबिंब है।
- **अंग्रेज़ी दस्तावेज़ प्रामाणिक बने रहते हैं**; अनुवाद समुदाय/maintainer का काम हैं, प्रत्येक पर उसकी
  अनुवाद-तिथि और वह अंग्रेज़ी commit अंकित होता है जिसका वह अनुसरण करता है।
- हम दस्तावेज़ों का **स्वचालित मशीनी अनुवाद करके** उन्हें प्रामाणिक के रूप में प्रस्तुत **नहीं** करते
  — वह परियोजना के ईमानदारी सिद्धांत का उल्लंघन होगा। प्रत्येक भाषा में सबसे अधिक मूल्यवान, सबसे छोटे
  दस्तावेज़ों (QUICKSTART, "आप पहले क्या देखेंगे" दौरा, ETHICS) से शुरुआत करें।

---

### योगदान की कार्यप्रणाली (डिज़ाइन से खुली पहुँच)

1. `locales/en.json` → `locales/<code>.json` कॉपी करें, मानों का अनुवाद करें, `_meta.status` सेट करें।
2. RTL भाषाओं के लिए `_meta.dir: "rtl"` सेट करें।
3. (नियोजित) key-कवरेज जाँच चलाएँ: `en.json` की तुलना में अनुपस्थित/अतिरिक्त keys की रिपोर्ट।
4. जमा करें। अनअनूदित keys भरे जाने तक बस अंग्रेज़ी पर लौट आती हैं।

---

### स्थिति

**Phase 1 (पूर्ण):** i18n engine (`i18n.js`), सभी 12 भाषाओं के लिए locale ढाँचा, और
**en/fr/es/de** के लिए पूर्ण संदर्भ अनुवाद।

**Phase 1b (पूर्ण, `0.4.0`):** शेष interface strings को key किया गया और **सभी बारह** भाषाओं में
अनूदित किया गया (`CHANGES.md` 0.4.0 देखें), इसलिए `src/static/locales/*.json` में हर locale में अब
पूरा key समूह है (सत्यापित: 12 फ़ाइलें, प्रत्येक में 6,991 keys, कोई अनुपस्थित नहीं)। ईमानदारी
अपरिवर्तित है: नाम व्यक्तिवाचक संज्ञाएँ हैं और उनका अनुवाद नहीं होता, और आंशिक locale अब भी टूटने के
बजाय अंग्रेज़ी पर लौट आता है।

**Phase 2 (पूर्ण — वास्तविक ब्राउज़र जाँच लंबित):** `i18n.js` `index.html` में शामिल है (और
2026-06-10 को Desk के हटाए जाने तक `desk.html` में था); एक **भाषा** चयनकर्ता (`#oo-lang-select`)
सेटिंग्स में है और स्वतः जुड़ा हुआ है; गतिशील रूप से render होने वाले chrome का अनुवाद एक debounced
`MutationObserver` द्वारा स्वचालित रूप से होता है (कोई बिखरे हुए `apply()` calls नहीं); अंग्रेज़ी पर
स्विच करने से मूल पाठ वापस आ जाते हैं; `<html dir>` के माध्यम से RTL। संरचना/syntax सत्यापित हैं,
लेकिन व्यवहार को फिर भी ब्राउज़र में आँखों से जाँचना चाहिए।

**Phase 3 (अगला):** `en.json` को *पूरे* string catalogue तक विस्तारित करना (यह वर्तमान में अधिक
उपयोग वाले chrome को कवर करता है), stub locales को पूर्ण करना (समुदाय), और `ar`/`ur` के लिए RTL
layout को निखारना।


## निर्यात अनुबंध (संस्करणित)

मशीन-पठनीय निर्यात एक स्थिर, स्व-वर्णनात्मक अनुबंध रखते हैं (schema `oo-export-1`,
0.0.8 part 2 / RM-15), ताकि downstream pipelines को कभी अनुमान न लगाना पड़े:

- **JSON** (`/api/articles/export?format=json`, `/api/links/export.json`): एक envelope —
  `{export_schema, kind, app_version, generated_at, query, count, articles|data}`। `query`
  object शब्दशः उत्पन्न करने वाला चयन है; उत्पत्ति डेटा के साथ यात्रा करती है।
- **CSV** (`/api/articles/export?format=csv`): कोई टिप्पणी-पंक्ति नहीं (वह सरल readers को तोड़ देगी);
  वही envelope HTTP headers के रूप में चलता है (`X-OO-Export-Schema`, `X-OO-App-Version`,
  `X-OO-Generated-At`, `X-OO-Query`)। कॉलम अपना क्रम बनाए रखते हैं, और नया कॉलम केवल अंत में ही
  जोड़ा जाता है: `Fetched From Host` (queue आइटम 61), वह होस्ट जहाँ से पृष्ठ अपने redirects के बाद
  fetch किया गया, दर्ज न होने पर खाली; JSON निर्यात इसे `fetched_host` के रूप में रखता है।
- **Citation graph** (`/api/links/export.graphml`, `.json`): कौन-किसे-उद्धृत-करता-है graph
  (संग्रहीत लेख → बाहरी पंजीकरण-योग्य डोमेन)। **केवल गिनतियाँ — कोई अनुमानित विश्वसनीयता नहीं,
  कोई स्कोर नहीं**; चेतावनी फ़ाइल में ही समाहित है। GraphML Gephi/yEd/NetworkX में खुलता है।

Schema परिवर्तन `oo-export-N` को बढ़ाते हैं; मौजूदा फ़ील्ड को कभी चुपचाप नए उद्देश्य में नहीं लगाया
जाता। उनके बगल में जोड़ा गया फ़ील्ड (अंत में एक CSV कॉलम, एक नई JSON key) हर मौजूदा reader के
फ़ील्ड को उनके स्थान पर ही छोड़ता है, इसलिए वह schema को नहीं बढ़ाता।
