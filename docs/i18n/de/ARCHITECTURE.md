<!-- de: Translation of docs/ARCHITECTURE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 28 of 28 headings. Corrections are welcome as a pull request. -->

# Architektur und technische Referenz

Das technische Gegenstück zum Benutzerhandbuch: Datenbank/Konfiguration, die Übersicht der HTTP-API und die Internationalisierung.

## Inhalt
- [Datenbankkonfiguration für Open Omniscience](#datenbankkonfiguration-für-open-omniscience)
- [API-Referenz](#api-referenz)
- [Internationalisierung (i18n) — die App mehrsprachig machen](#internationalisierung-i18n--die-app-mehrsprachig-machen)


---

## Datenbankkonfiguration für Open Omniscience

> **Status (überprüft im Audit zu v0.0.7, `docs/archive/audits/00_BASELINE.md`):** Die Datenbankschicht
> **funktioniert und ist getestet** — der Server startet, legt den SQLite-Speicher an bzw. verwendet ihn, wendet die Alembic-
> Migrationen an, und die vollständige Testsuite (800+) läuft dagegen erfolgreich durch. Das alte Banner „frühes Konzept —
> nicht funktionsfähig“, das hier früher stand, beschrieb einen Zustand vor dem Neuaufbau und war längst
> veraltet.

### 🗃️ SQLite — der unterstützte Speicher

SQLite ist das **standardmäßige und einzige unterstützte, getestete Backend**. Es passt zum lokalen,
auf eine einzelne Betreiberin bzw. einen einzelnen Betreiber ausgelegten Design des Produkts.

- **Keine Konfiguration nötig:** Die Datenbank wird beim ersten Start automatisch angelegt, unter
  `<data dir>/open_omniscience.db`. Das Datenverzeichnis ist `OO_DATA_DIR`, falls gesetzt, sonst das
  `data/` des Repositorys in einem Quellcode-Checkout, sonst `$XDG_DATA_HOME/open-omniscience` (siehe `src/paths.py`).
- **Automatisch abgestimmt:** Die Engine setzt bei jeder Verbindung den Journalmodus `WAL`, `foreign_keys=ON`,
  `busy_timeout=30000` und `synchronous=NORMAL`
  (`src/database/session.py`) — Sie müssen diese nicht selbst setzen.
- **Volltextsuche** erfolgt über SQLite **FTS5** (`article_fts`, External-Content-Tabelle, durch
  Trigger synchron gehalten — `src/database/fts.py`).
- **Speicherort überschreiben** mit der Umgebungsvariable `DATABASE_URL` (bearbeiten Sie **keine**
  Quelldateien): `DATABASE_URL=sqlite:////absolute/path/to/your.db`
- **Wartung:** Ein gelegentliches `sqlite3 <db> "VACUUM;"` gibt Speicherplatz frei (das Audit zu v0.0.7
  hat außerdem einen überflüssigen Index entfernt, der bei großen Korpora ~63 % der Datei ausmachte; führen Sie nach einem Upgrade einmal `make
  migrate` aus, um ihn aus bestehenden Datenbanken zu entfernen).

### 🐘 PostgreSQL — experimentelles Gerüst, NICHT unterstützt

Ehrlichkeit vor Anspruch (Audit-Befund ARCH-06): Die Engine-Schicht *erkennt* eine
PostgreSQL-`DATABASE_URL` (Connection-Pooling über `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`), **aber**

- **die Volltextsuche existiert unter PostgreSQL nicht** — die FTS5-Einrichtung bewirkt bei
  Nicht-SQLite-Engines absichtlich nichts, sodass der Tab „Suche“ tot wäre;
- die Testsuite läuft nie gegen PostgreSQL, und keine CI deckt es ab;
- keine veröffentlichte Installation hat es verwendet.

Betrachten Sie PostgreSQL als **ungetestetes Gerüst für eine mögliche Zukunft**, nicht als Wahl, die Sie
heute treffen können. Sollte Skalierung mit mehreren Schreibern je zu einer echten Anforderung werden, ist der Roadmap-Punkt ein
`tsvector`-Suchpfad plus eine PostgreSQL-CI-Matrix — bis das umgesetzt ist, wird diese Seite nichts
vortäuschen.

### 🔄 Migrationen

Alembic ist im **Wurzelverzeichnis des Repositorys** konfiguriert (`alembic.ini`, `migrations/`). Alembic wird
mit der App installiert (es ist eine Kernabhängigkeit — keine separate Installation).

- **Neue Datenbanken** werden vollständig angelegt (`create_all` + FTS) und beim Start automatisch mit dem aktuellen
  Migrationsstand (Head) gekennzeichnet.
- **Eine bestehende Datenbank aktualisieren:**
  ```bash
  make migrate          # = alembic upgrade head, from the repo root
  ```
- **Eine Migration erstellen** (Mitwirkende): Bearbeiten Sie `src/database/models.py`, dann
  ```bash
  alembic revision --autogenerate -m "your message"
  alembic upgrade head
  ```
  und prüfen Sie die erzeugte Datei — Autogenerate übersieht virtuelle FTS-Tabellen (diese befinden sich in
  `src/database/fts.py` und werden beim Start angewendet).
- **Zurückrollen:** `alembic downgrade -1`.

---

### 📊 Datenbankschema

#### Tabellen:

##### `sources`
| Spalte | Typ | Beschreibung |
|--------|------|-------------|
| `id` | INTEGER | Primärschlüssel |
| `name` | STRING(100) | Name der Quelle (z. B. "BBC News") |
| `domain` | STRING(255) | Domain der Quelle (z. B. "bbc.com") |
| `rss_url` | STRING(500) | URL des RSS-Feeds (falls vorhanden) |
| `rate_limit_ms` | INTEGER | Verzögerung zwischen Anfragen in Millisekunden |
| `enabled` | BOOLEAN | Ob die Quelle zum Auslesen aktiv ist |
| `priority` | INTEGER | Prioritätsstufe (1 = hoch, 3 = niedrig) |
| `tags` | STRING(500) | Kommagetrennte Liste von Tags |

##### `articles`
| Spalte | Typ | Beschreibung |
|--------|------|-------------|
| `id` | INTEGER | Primärschlüssel |
| `url` | STRING(1000) | Ursprüngliche URL des Artikels |
| `canonical_url` | STRING(1000) | Kanonisierte URL (zur Erkennung von Duplikaten) |
| `source_id` | INTEGER | Fremdschlüssel auf `sources` |
| `title` | STRING(500) | Titel des Artikels |
| `content` | TEXT | Vollständiger Textinhalt des Artikels |
| `published_at` | DATETIME | Veröffentlichungsdatum/-zeit (ISO-Format) |
| `language` | STRING(10) | Sprachcode (z. B. "en", "fr") |
| `hash` | STRING(64) | SHA-256-Hash des Inhalts (zur Erkennung von Duplikaten) |
| `created_at` | DATETIME | Zeitstempel der Aufnahme des Artikels |

> Die obigen Spalten sind die Kernfelder; das tatsächliche Schema (`src/database/models.py`)
> und die Alembic-Migrationen unter `migrations/versions/` sind maßgeblich.
> `articles` enthält außerdem Herkunfts-/Analysefelder (author, word_count, region,
> country, sentiment) und eine Spalte für komprimierten Inhalt.

##### Weitere Tabellen (vollständige Spalten siehe Modelle / Migrationen)

| Tabelle | Zweck |
|-------|---------|
| `source_groups`, `source_metadata`, `source_group_association` | Gruppierung von Quellen + Geo-/robots-Metadaten |
| `commodity_prices` | Beobachtete Preispunkte (Symbol, Datum, Preis, Währung, **Einheit**, Markt, Quelle) — Diagramme + Korrelation Preis↔Nachrichten |
| `market_extraction_rules` | Regel pro Quelle (CSS-Selektor / Attribut / Regex), die den Preis eines Instruments auf einer Seite findet; Kategorie financial/stock/commodity |
| `keywords` | Eindeutiger Schlüsselwort-/Entitätsbegriff (normalisiert, Sprache, `is_entity`/`entity_type`, Herkunft über **`extractor`**) |
| `keyword_mentions` | Eine pro (Artikel, Schlüsselwort): Anzahl + Offset des ersten Zeichens + denormalisierte `observed_on`/`country`/`city` — speist Trends, Assoziationen, Kontext und Karte unter „Einblicke“ |
| `wiki_pages` | Eine verfolgte Wikipedia-Seite in einer Sprachausgabe; enthält **eine** komprimierte Volltext-Basisversion |
| `wiki_revisions` | Eine verfolgte Bearbeitung: **Diff + vorzeichenbehaftete Byte-Differenz** + Flags/Tags (keine erneute Kopie), optionale ORES-Bewertungen, ehrliche Markierung großer Bearbeitungen + Gründe |
| `article_analyses` | Abgeleitete LLM-Ergebnisse (Zusammenfassung/Übersetzung) mit Herkunft von Modell + Prompt |
| `keyword_categories`, `external_sources`, `article_links`, … | Kategorisierung von Schlüsselwörtern + Verfolgung von Links/Quellenbeziehungen |

#### Indizes:
- `idx_article_hash`: Eindeutiger Index auf `hash` (zur Erkennung von Duplikaten).
- `idx_article_canonical_url`: Index auf `canonical_url` (für URL-Abfragen).
- `idx_article_source_id`: Index auf `source_id` (für quellenbasierte Abfragen).
- `idx_article_content`: Index auf `content` (für die Volltextsuche).

---

### 🔍 Volltextsuche

Die Volltextsuche ist **bereits gebaut und angebunden** — es gibt nichts zu aktivieren. Der Speicher
enthält eine FTS5-External-Content-Tabelle (`article_fts`), die durch Trigger synchron gehalten wird; siehe
`src/database/fts.py` für das Schema und `search_ids` in `src/api/main.py` für den Abfrage-
pfad (Auflösung nur der IDs in endgültiger Reihenfolge, vollständige Zeilen nur für die jeweilige Seite geladen).

Dieser Abschnitt bot früher ein Rezept „erwägen Sie, eine virtuelle Tabelle anzulegen“ für SQLite und ein
`to_tsvector`-Rezept für PostgreSQL. Beide waren falsch: Das SQLite-Rezept beschrieb, wie man eine Tabelle
von Hand anlegt, die die App selbst ausliefert und pflegt (unter einem *anderen* Namen, sodass man damit
einen zweiten, ungepflegten Index erzeugt hätte), und PostgreSQL hat hier überhaupt keinen Suchpfad,
was der Abschnitt über den Speicher oben als ersten Grund nennt, warum es kein unterstütztes Backend ist.

---

### 📉 Überwachung und Wartung

- **Datenbankgröße prüfen**:
  ```bash
  ls -lh data/open_omniscience.db
  ```
- **Tabellengrößen prüfen**:
  ```bash
  sqlite3 data/open_omniscience.db "SELECT name, COUNT(*) FROM sqlite_master WHERE type='table';"
  ```
  Bei einem **verschlüsselten** Speicher kann die `sqlite3`-CLI die Datei überhaupt nicht öffnen (genau das
  ist der Zweck) — verwenden Sie die Ansichten unter Einstellungen → Diagnose in der App, die den Speicher
  über dieselbe abgesicherte Verbindungsfabrik lesen, die auch die App selbst verwendet.

---

### 🚨 Fehlerbehebung

#### Häufige Probleme:

##### SQLite:
- **"Database is locked"**:
  - SQLite erlaubt jeweils nur einen Schreiber. Der WAL-Modus ist standardmäßig aktiviert
    (`src/database/session.py`), und eine prozessweite Single-Writer-Sperre
    (`src/database/writer.py`) serialisiert Schreibvorgänge innerhalb der App, sodass gleichzeitige Aufnahme und
    Import nicht mehr kollidieren. Eine anhaltende Sperre bedeutet, dass ein anderer *Prozess* schreibt.

- **"Too many open files"**:
  - SQLite öffnet für jeden Thread eine neue Verbindung. Begrenzen Sie die Anzahl der Threads oder verwenden Sie Connection-Pooling.

- **"Relation does not exist" / "no such table"**:
  - Führen Sie die Migrationen aus: `alembic upgrade head`.

---

### 📌 Bewährte Verfahren

1. **Sichern Sie über die App, nicht mit `cp`**:
   - Verwenden Sie Einstellungen → Sicherung (oder `GET /api/database/backup` für einen konsistenten Schnappschuss).
     Das Kopieren von `open_omniscience.db` von Hand ist **keine** Sicherung: Der Speicher läuft im WAL-
     Modus, sodass der live genutzten Datei fehlt, was noch in `-wal` steht, und beim standardmäßig
     **verschlüsselten** Speicher ist eine kopierte Datei ohne die Passphrase nutzlos und trägt keine
     Integritätszusage. Der eigene Weg der App führt einen Checkpoint aus, streamt und signiert.

2. **Migrationen testen**:
   - Testen Sie Migrationen immer an einer Sicherung Ihrer Datenbank, bevor Sie sie im Produktivbetrieb anwenden.

3. **Leistung überwachen**:
   - Einstellungen → Diagnose enthält das Protokoll langsamer Abfragen, das Protokoll der Anfragelatenz und den
     Bericht der Schreibsperre; die `sqlite3`-CLI funktioniert bei einem unverschlüsselten Speicher.

4. **Abfragen optimieren**:
   - `EXPLAIN QUERY PLAN` ist das Werkzeug. Beachten Sie, dass SQLite `SCAN` **sowohl** für einen reinen
     Tabellenscan als auch für einen reinen Indexscan schreibt — ein `SCAN <table> USING [COVERING] INDEX …` ist
     unbedenklich; das Warnzeichen ist ein bloßes `SCAN <table>` ohne `USING`
     (`src/monitoring/slowquery.py` klassifiziert genau danach).

5. **Datenaufbewahrung begrenzen**:
   - Archivieren oder löschen Sie regelmäßig alte Artikel, um die Datenbank handhabbar zu halten.
   - Beispiel: Artikel löschen, die älter als 1 Jahr sind:
     ```python
     from datetime import datetime, timedelta
     one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
     session.query(Article).filter(Article.published_at < one_year_ago).delete()
     session.commit()
     ```

---
*Copyright © 2026 Ideotion. Lizenziert unter der GNU General Public License v3.0
oder später (GPL-3.0-or-later) — siehe [LICENSE](../LICENSE). Dies ist freie Software;
Sie dürfen sie unter diesen Bedingungen weiterverbreiten und verändern.*


---

## API-Referenz

Die aktuelle, stets zutreffende API-Referenz wird von der App selbst erzeugt:

- **Swagger UI / ReDoc:** standardmäßig deaktiviert (sie laden Ressourcen von Drittanbieter-Hosts); starten Sie die App mit `OO_API_DOCS=1` für http://127.0.0.1:8000/docs und `/redoc`
- **OpenAPI-JSON:** http://127.0.0.1:8000/openapi.json

Die App bindet sich nur an Loopback und erfordert (für eine einzelne lokale Nutzerin bzw. einen einzelnen lokalen Nutzer) keine Authentifizierung.

### Endpunktgruppen

Dies ist eine **Übersicht der wichtigsten Gruppen, keine vollständige Liste** — das aktuelle
`/openapi.json` (oben) ist immer maßgeblich. Die Router werden in
`src/api/main.py` über `include_router(...)` eingebunden; mit **[analysis]** markierte Gruppen erfordern
das Extra `[analysis]` (die App startet auch ohne es, diese Endpunkte sind dann deaktiviert).

| Präfix | Funktion |
|--------|--------------|
| `GET /api/health` | Lebenszeichen + Version |
| `GET /api/articles`, `/api/articles/export` | Boolesche Volltextsuche (FTS5) + CSV-/JSON-Export |
| `POST /api/ingest`, `/api/sources/{id}/ingest`, `/api/sources/{id}/ingest-email` | Ethische Aufnahme: einzelne URL, RSS-Feed, IMAP-Postfach |
| `… /api/sources`, `/api/sources/...` | Verwaltung von Quellen + Gruppen + Metadaten |
| `POST /api/sources/seed-defaults` | Die kuratierten Quellenkataloge einspielen (Nachrichten + Märkte + generierter Weltkatalog) |
| `GET /api/database/stats`, `/coverage`, `/countries` | Zeilenzahlen des Korpus + Größe auf der Festplatte; Länderabdeckung; Quellenzahlen pro Land + Themenschlüsselwörter |
| `GET /api/database/backup` | Download eines konsistenten SQLite-Schnappschusses (nur unverschlüsselter SQLite-Speicher; abgelehnt für eine Anfrage von einer anderen Site oder mit einem Host, den der DNS-Rebinding-Schutz nicht bedient, und, bei einem anderen Namen als Loopback, für eine Anfrage, die keine Herkunftsseite nennt, sofern sie nicht `X-OO-Download: 1` sendet; jeweils einer gleichzeitig pro Prozess, geschrieben in einen privaten Ordner `.oo-backup-*` neben der Datenbank und entfernt, wenn der Download endet oder der Prozess stoppt (ein Abbruch hinterlässt ihn für die Bereinigung beim nächsten Start, die den Ordner eines nicht mehr laufenden Besitzers sofort entfernt); 507, wenn das Datenvolumen ihn nicht aufnehmen kann) |
| `POST /api/database/v2/restore/preview`, `/v2/restore/commit`, `/api/backup/v2/*` | **Rein additive** Wiederherstellung über das signierte Artefakt `oo-backup-2`: Vorschau des Zusammenführungsplans, dann Bestätigung. Die Wiederherstellung **überschreibt Ihren Korpus nie** — sie führt ohne Duplikate zusammen und behält bei Konflikten die lokalen Werte (der zerstörerische Ersetzungspfad wurde am 2026-06-13 entfernt) |
| `GET/PUT /api/settings` | GUI-Einstellungen (Design, Standardanzahl der Ergebnisse) |
| `… /api/scheduler/...` | Hintergrundsammlung: Status, Start, Stopp, sofort ausführen, Konfiguration. Seit dem Zyklus `0.4` läuft die Sammlung in **nebeneinander laufenden Spuren** (`rss` / `crawl` / `markets` / `wiki` / `law`), nicht in einem einzigen Scheduler-Modus — Speicher pro Spur unter `… /api/storage/...`, und der Tab **Lebende Quellen** liest `… /api/living/...` (was sich in Wikipedia, Gesetzen und Karten geändert hat) |
| `… /api/markets/rules`, `/rules/{id}/run`, `/overview` | Preisextraktionsregeln pro Quelle + ein „Test“-Lauf + Märkte-Übersicht |
| `GET /api/markets/feeds`, `POST /feeds/{key}/import`, `/feeds/import-url` | Katalog offizieller CSV-Preisfeeds + Import (FRED/World Bank/EIA) + Import von eigener URL |
| `GET /api/catalog/export.csv`, `/template.csv`, `/columns`, `POST /api/catalog/import` | CSV-Export / Vorlage / Spalten der Quellenliste / Import mit Upsert nach Domain |
| `… /api/insights/...` | Schlüsselwort- und Entitätsanalysen: Status, Neuindizierung, Top, Trendend, Trend, Assoziationen (PMI), Kontext, Karte |
| `GET /api/timemap`, `/timemap/range` | Raum-Zeit-Signale auf einer Karte mit Zeitachse (Anker + geokodierter Korpus + optionale Gefahren/erwähnte Daten); `?kinds`, `?start`/`?end`-Fenster in Bruchteilen von Jahren, `?hazards`, `?articles`, `?mentions`, `?days` |
| `… /api/article-dates/...` | Aus dem Artikeltext extrahierte erwähnte Daten als von Menschen bestätigbare Tags pro Artikel: auflisten/extrahieren pro Artikel, bestätigen/ablehnen, Stapelindizierung, Korpusfilter nach Datum |
| `GET/POST /api/llm/...` | Lokales LLM (Ollama): Status, Modelle, Generieren, einen Artikel zusammenfassen |
| `… /api/commodities/...` | Rohstoffpreise (Import / CSV / Liste) + ehrliche Korrelation Preis↔Nachrichten |
| `POST /api/analysis/...` | Statistik mit wissenschaftlicher Strenge: t-Test, Korrelation, ANOVA, Mann-Whitney, Konfidenzintervalle |
| `GET /api/monitoring/...` | Tatsächlicher Verfügbarkeitszustand der Quellen + Anomalien im Korpusvolumen |
| `POST /api/verify/image-metadata` | Ehrliche Extraktion von EXIF-/Bildmetadaten |
| `POST /api/reports/evidence`, `/evidence/verify` | Signierte, manipulationssichtbare Beweispakete |
| `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`, `POST /api/custody/export`, `POST /api/custody/verify` | Nur anhängbares, hash-verkettetes, signiertes Protokoll der Beweiskette + Offline-Prüfung |
| `GET/PUT /api/custody/settings` | Laufzeit-Einstellungen der Beweiskette (Post-Quanten-Signatur, Verankerungsmodus, automatische Protokollierung) — meldet den *tatsächlich wirksamen*, verfügbarkeitsabhängigen Zustand |
| `POST /api/custody/anchor`, `GET /api/custody/providers` | Eine Merkle-Wurzel verankern (lokal / OpenTimestamps) + Verfügbarkeit der Anbieter |
| `POST /api/custody/reconcile` | Die INGEST-Einträge schreiben, die nach einem Fehler noch ausstanden, jeweils in ihren signierten Metadaten als verspätet markiert; `scan` zählt ältere Lücken, `record_gaps` reiht sie ein (2026-09-24, CUST-1) |
| `… /api/keywords/...`, `/api/analysis/articles/similarity` | **[analysis]** Schlüsselwortextraktion + Artikelähnlichkeit |
| `GET /api/search/omni` | Indexgestützte föderierte Omnibar (Artikel-FTS5 + Schlüsselwörter + Quellen + Wiki/Recht) |
| `… /api/jobs/...` | Bündelung der Aufgaben für den Task-Manager (Sammeldurchlauf, laufender Abruf, Warteschlange für Wiki-Dumps + Neuordnung) |
| `… /api/system/...` | Systemkennwerte + Netzwerkzustand/Einwilligung (Kill Switch des Flugmodus, lokale Schnittstellen-IPs) |
| `… /api/safety/...` | Sicherheitssteuerung: Kill Switch, Freigabe der Entdeckung, Wiederherstellung aus verschlüsseltem Artefakt |
| `… /api/briefing/...` | Erzeuger des Start-Briefings (nach Evidenz gestufte Karten; Methode+Vorbehalt+n) |
| `… /api/insights/...`, `/api/insights/who`, `/where` | Schlüsselwort-/Entitätsanalysen + korpusweite Wer/Wo-Aggregation |
| `… /api/links/...` (shared, preview) | Analyse gemeinsamer ausgehender Links / des Zitationsgraphen + lokaler Link-Vorschau-Dialog |
| `… /api/events/...`, `/api/events/astronomy`, `/climate` | Agenda-Ereignisse einschließlich lokal berechneter Astronomie (Meeus) + El-Niño-Tabelle |
| `POST /api/weather/context` | Eingewilligter, begrenzter Ausschnitt der Open-Meteo-Reanalyse zur Untermauerung |
| `… /api/law/...` | Änderungsfeed verfolgter Gesetzgebung/Primärquellen |
| `… /api/integrity/...` | Signale zu Echo / Koordination / Abstammung |
| `… /api/annotations/...` | Lokale, optional signierte Artikelanmerkungen |
| `… /api/wiki/...` | Wikipedia-Ausgaben, beobachtete Seiten, Dump-Download/-Lesen, Korpus-Synchronisierung |
| `… /api/hazards/...`, `/api/timemap` | Gefahren-Overlays + Raum-Zeit-Karte |
| `GET /unlock`, `POST /api/unlock`, `/create-db`, `/doctor`, `/encrypt-db` | Verschlüsselung im Ruhezustand: Entsperrbildschirm beim gesperrten Start, verschlüsselten/unverschlüsselten Speicher anlegen, Header-Bestätigung, Einweg-Verschlüsselungswerkzeug |

Mit **[analysis]** markierte Router (commodities, statistics, keywords, framing)
erfordern das Extra `[analysis]`; ohne es startet die App weiterhin mit dem Kern-
gerüst, und diese Endpunkte sind deaktiviert.

Hinweise zum Verhalten:
- Die Aufnahme ruft nur über den ethischen Fetcher ab (robots.txt mit Fail-Closed-Verhalten, ratenbegrenzt);
  LLM-Endpunkte geben **503** zurück, wenn Ollama nicht verfügbar ist (niemals eine vorgetäuschte Antwort).
- Prüfung von Beweisen: Übergeben Sie den öffentlichen Schlüssel der unterzeichnenden Person, um die Herkunft nachzuweisen, nicht nur die
  Integrität (siehe [QUICKSTART](QUICKSTART.md) und `scripts/verify_evidence.py`).
- Einstellungen der Beweiskette sind *Präferenzen*, keine Garantien: `GET/PUT /api/custody/settings`
  melden immer den **tatsächlich wirksamen** Zustand (Präferenz **und** Verfügbarkeit der Bibliothek), sodass
  Post-Quanten-Signaturen / OpenTimestamps nie als aktiviert erscheinen, wenn das unterstützende Extra
  fehlt. Die Verankerung verwendet standardmäßig den Offline-Anbieter `local`; OpenTimestamps und
  die Verankerung in öffentlichen Blockchains tragen einen Datenschutzhinweis (siehe
  [CHAIN_OF_CUSTODY](USER_MANUAL.md)).


---

## Internationalisierung (i18n) — die App mehrsprachig machen

> Ziel: die **gesamte Benutzeroberfläche** (und mit der Zeit auch die **Dokumentation**) in ~einem
> Dutzend Sprachen verfügbar machen, um den offenen Zugang in Richtung „fast aller Menschen“ zu erweitern. Umgesetzt auf
> die Art des Projekts: **offline, kein CDN, keine Übersetzungs-API zur Laufzeit, keine Telemetrie** und
> **ehrlich**, was die Übersetzungsqualität betrifft (wir liefern keine maschinellen Vermutungen aus, als wären sie
> maßgeblich).

---

### Das Dutzend Sprachen (Satz der Phase 1)

Ausgewählt nach Reichweite (Mutter- und Zweitsprachler) und um bewusst den
Globalen Süden einzubeziehen (gemäß dem Anti-Bias-Ziel in `ROADMAP.md`):

| Code | Sprache | Eigenname | Schrift / Richtung | Status |
|---|---|---|---|---|
| `en` | Englisch | English | LTR | **Quelle** (vollständig) |
| `fr` | Französisch | Français | LTR | **vollständig** (geprüft) |
| `es` | Spanisch | Español | LTR | **vollständig** (geprüft) |
| `de` | Deutsch | Deutsch | LTR | **vollständig** (geprüft) |
| `zh` | Chinesisch (Mandarin) | 中文 | LTR | vollständig (übersetzt, Zyklus `0.4`; noch nicht geprüft) |
| `hi` | Hindi | हिन्दी | LTR | vollständig (übersetzt, Zyklus `0.4`; noch nicht geprüft) |
| `ar` | Arabisch | العربية | **RTL** | vollständig (übersetzt, Zyklus `0.4`; noch nicht geprüft) |
| `bn` | Bengalisch | বাংলা | LTR | vollständig (übersetzt, Zyklus `0.4`; noch nicht geprüft) |
| `ru` | Russisch | Русский | LTR | vollständig (übersetzt, Zyklus `0.4`; noch nicht geprüft) |
| `pt` | Portugiesisch | Português | LTR | vollständig (übersetzt, Zyklus `0.4`; noch nicht geprüft) |
| `id` | Indonesisch | Bahasa Indonesia | LTR | vollständig (übersetzt, Zyklus `0.4`; noch nicht geprüft) |
| `ja` | Japanisch | 日本語 | LTR | vollständig (übersetzt, Zyklus `0.4`; noch nicht geprüft) |

Naheliegende nächste Ergänzungen für mehr Reichweite: **Swahili (`sw`)**, **Urdu (`ur`, RTL)**, Italienisch
(`it`), Türkisch (`tr`), Vietnamesisch (`vi`).

**Haltung zur Ehrlichkeit.** Ein *Stub* macht eine Sprache **sofort auswählbar** und fällt für jede
nicht übersetzte Zeichenkette auf Englisch zurück — eine unvollständige Sprachdatei bricht die Oberfläche nie (das ist
der Mechanismus, von dem jede künftige Sprache — `it`, `tr`, `vi`, … — ausgeht). Wir kennzeichnen jede Sprachdatei als `complete | draft | stub`. Der Maintainer
liefert nur aus, wofür er sich verbürgen kann; alles andere wird durch **Beiträge aus der Gemeinschaft**
ergänzt (genau so erweitert Open Source den Zugang).

---

### Architektur (offline, ohne Abhängigkeiten)

`src/static/i18n.js` + `src/static/locales/<code>.json`. Kein Build-Schritt, kein Netzwerk.

- **Englisch ist der Schlüssel.** Sprachdateien ordnen die **englische UI-Zeichenkette → ihrer Übersetzung** zu
  (z. B. `"Search the corpus": "Rechercher dans le corpus"`). So lässt sich die
  bestehende Oberfläche nachrüsten, ohne jedes Element zu kennzeichnen, und Englisch bleibt die kanonische
  Quelle.
- **`OOI18N.setLang(code)`** lädt `locales/<code>.json`, speichert die Wahl in
  `localStorage` (`oo.lang`), setzt `document.documentElement.lang` und `dir` (RTL für
  `ar`/`ur`) und durchläuft dann mit **`apply()`** das DOM — es übersetzt Textknoten, deren getrimmter
  Text einem Schlüssel entspricht, sowie die Attribute `placeholder`/`title`/`aria-label`. Unbekannte
  Zeichenketten bleiben unverändert (Rückfall auf Englisch) — nichts geht je kaputt.
- **Dynamische Inhalte** (Daten: Artikeltitel, Quellennamen, Zählwerte) werden **nie**
  übersetzt — nur die Bedienoberfläche. Per JS gerenderte Oberflächenteile (Befehlspalette, Drawer) rufen
  `OOI18N.apply()` auf, nachdem sie gerendert wurden.
- Jede Sprachdatei enthält `_meta` (`name`, `native`, `dir`, `status`).

#### Einbindung (Phase 2 — ausgeliefert; Desk wurde inzwischen eingestellt)

Zwei Zeilen in `index.html` (und, vor seiner Einstellung am 2026-06-10, in `desk.html`),
dann eine Sprachauswahl:

```html
<script src="/static/i18n.js"></script>
<!-- after first render and on each view change: --> OOI18N.apply();
```

Die Auswahl **Sprache** befindet sich in den Einstellungen und ruft `OOI18N.setLang(code)` auf,
gespeichert zusammen mit den übrigen lokalen UI-Einstellungen.

---

### Dokumentation in vielen Sprachen

Dokumente sind lang, und die Übersetzungsqualität zählt bei ihnen mehr als bei kurzen UI-Zeichenketten, daher:

- Struktur: `docs/i18n/<code>/<DOC>.md` spiegelt `docs/`.
- Die **englischen Dokumente bleiben kanonisch**; Übersetzungen sind Arbeit der Gemeinschaft bzw. des Maintainers,
  jeweils gekennzeichnet mit ihrem Übersetzungsdatum und dem englischen Commit, dem sie folgen.
- Wir übersetzen Dokumente **nicht** automatisch maschinell und präsentieren sie als maßgeblich — das
  würde gegen das Ehrlichkeitsprinzip des Projekts verstoßen. Beginnen Sie pro Sprache mit den wertvollsten, kürzesten
  Dokumenten (QUICKSTART, die Tour „What you'll see first“, ETHICS).

---

### Ablauf für Beiträge (offener Zugang von Grund auf)

1. Kopieren Sie `locales/en.json` → `locales/<code>.json`, übersetzen Sie die Werte, setzen Sie `_meta.status`.
2. Setzen Sie für RTL-Sprachen `_meta.dir: "rtl"`.
3. Führen Sie die (geplante) Prüfung der Schlüsselabdeckung aus: fehlende/überzählige Schlüssel gegenüber `en.json` melden.
4. Reichen Sie ein. Nicht übersetzte Schlüssel fallen einfach auf Englisch zurück, bis sie ergänzt sind.

---

### Status

**Phase 1 (erledigt):** die i18n-Engine (`i18n.js`), das Sprachdatei-Gerüst für alle 12
Sprachen und vollständige Referenzübersetzungen für **en/fr/es/de**.

**Phase 1b (erledigt, `0.4.0`):** Die übrigen Oberflächenzeichenketten wurden mit Schlüsseln versehen und
in **alle zwölf** Sprachen übersetzt (siehe `CHANGES.md` 0.4.0), sodass jede
Sprachdatei in `src/static/locales/*.json` nun den vollständigen Schlüsselsatz enthält (überprüft:
12 Dateien, je 6.991 Schlüssel, keiner fehlt). Die Ehrlichkeit bleibt unverändert: Namen sind
Eigennamen und werden nicht übersetzt, und eine unvollständige Sprachdatei fällt weiterhin auf
Englisch zurück, statt etwas kaputtzumachen.

**Phase 2 (erledigt — ausstehend ist ein Durchgang in einem echten Browser):** `i18n.js` ist in
`index.html` eingebunden (und war es in `desk.html` bis zur Einstellung von Desk am 2026-06-10); eine
Auswahl **Sprache** (`#oo-lang-select`) befindet sich in den Einstellungen und wird automatisch angebunden; dynamisch gerenderte Oberflächenteile werden automatisch übersetzt durch
einen entprellten `MutationObserver` (keine verstreuten `apply()`-Aufrufe); das Umschalten auf Englisch
stellt die Originale wieder her; RTL über `<html dir>`. Struktur und Syntax sind validiert, das
Verhalten sollte aber dennoch in einem Browser in Augenschein genommen werden.

**Phase 3 (als Nächstes):** `en.json` auf den *vollständigen* Zeichenkettenkatalog erweitern (derzeit
deckt es die meistgenutzten Oberflächenteile ab), die Stub-Sprachdateien vervollständigen (Gemeinschaft) und das
RTL-Layout für `ar`/`ur` verfeinern.


## Exportvertrag (versioniert)

Maschinenlesbare Exporte tragen einen stabilen, selbstbeschreibenden Vertrag (Schema `oo-export-1`,
0.0.8 Teil 2 / RM-15), damit nachgelagerte Pipelines nie raten müssen:

- **JSON** (`/api/articles/export?format=json`, `/api/links/export.json`): eine Hülle —
  `{export_schema, kind, app_version, generated_at, query, count, articles|data}`. Das
  `query`-Objekt ist die wortgetreue erzeugende Auswahl; die Herkunft reist mit den Daten.
- **CSV** (`/api/articles/export?format=csv`): keine Kommentarzeile (sie würde einfache Leseprogramme stören);
  dieselbe Hülle wird als HTTP-Header mitgeführt (`X-OO-Export-Schema`, `X-OO-App-Version`,
  `X-OO-Generated-At`, `X-OO-Query`). Die Spalten behalten ihre Reihenfolge, und eine neue wird immer nur
  angehängt: `Fetched From Host` (Warteschlangenpunkt 61), der Host, von dem die Seite nach ihren
  Weiterleitungen abgerufen wurde, leer, wenn nicht erfasst; der JSON-Export führt ihn als `fetched_host`.
- **Zitationsgraph** (`/api/links/export.graphml`, `.json`): der Graph „wer zitiert wen“
  (gespeicherte Artikel → externe registrierbare Domains). **Nur Zählwerte — keine abgeleitete
  Glaubwürdigkeit, keine Bewertungen**; der Vorbehalt ist in die Datei selbst eingebettet. GraphML lässt sich in
  Gephi/yEd/NetworkX öffnen.

Schemaänderungen erhöhen `oo-export-N`; bestehende Felder werden nie stillschweigend umgewidmet. Ein daneben
hinzugefügtes Feld (eine angehängte CSV-Spalte, ein neuer JSON-Schlüssel) lässt die Felder jedes bestehenden Leseprogramms
an ihrem Platz, daher erhöht es das Schema nicht.
