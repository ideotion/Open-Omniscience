<!-- de: Translation of docs/DESIGN.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 68 of 68 headings. Corrections are welcome as a pull request. -->

# Design- und Produktsynthese

Was die App ist und was nicht, wo jede ursprüngliche „Säule“ heute lebt, die Designbegründung der GUI und die Strategie zur Inhaltsanalyse. Die eine Design-Referenz.

## Inhalt
- [Open-Omniscience — Produktsynthese (was die App leisten soll)](#open-omniscience--produktsynthese-was-die-app-leisten-soll)
- [Säulen-Absichtskarte — wo der Zweck jeder Säule heute lebt](#säulen-absichtskarte--wo-der-zweck-jeder-säule-heute-lebt)
- [GUI-Neugestaltung — „0.05“](#gui-neugestaltung--005)
- [Zwei Oberflächen, ein Argument — „Console“ vs. „Desk“](#zwei-oberflächen-ein-argument--console-vs-desk)
- [Strategie zur Inhaltsanalyse — Links, Gleichförmigkeit und die Originalquelle](#strategie-zur-inhaltsanalyse--links-gleichförmigkeit-und-die-originalquelle)


---

## Open-Omniscience — Produktsynthese (was die App leisten soll)

> **Status:** Entwurf zur Prüfung. Dieses Dokument führt das *beabsichtigte* Design aus der gesamten
> Dokumentation des Repositorys zu einer kohärenten, von Dubletten bereinigten Spezifikation zusammen. Es entfernt
> bewusst Versionsdrift, Marketing-Übertreibungen und nicht überprüfbare QA-Behauptungen. Es beschreibt das **Zielprodukt**, nicht
> den aktuellen (weitgehend nicht funktionsfähigen) Code.
>
> Verwendete Markierungen:
> - `⚠️ DECIDE:` eine Stelle, an der die Quelldokumente mehrdeutig waren oder einander widersprachen — Ihre Entscheidung.
> - `(P0/P1/P2)` eine *vorgeschlagene* Priorität für diese Fähigkeit (P0 = MVP-Kern, P1 = wichtig, P2 = später).

---

### 0. Einsatzkontext (GEKLÄRT — bestimmt alles Folgende)

Dieser Build zielt auf **eine bestimmte Umgebung und einen Nutzer**. Diese Antworten stehen nun fest und klären
mehrere der früheren `⚠️ DECIDE`-Punkte.

- **Host:** Qubes OS, innerhalb einer **Debian-AppVM** (vorlagenbasiert).
- **Python:** **3.13 als Standard-Interpreter.**
- **Nutzer:** ein **einziger Hauptnutzer (der Projektinhaber)** — keine mandantenfähigen Konten, kein RBAC.
- **Oberfläche:** **Web-UI + REST-API, ausschließlich an `127.0.0.1` gebunden** (Loopback). Keine externen Listener.
- **Netzwerkhaltung:** local-first; ausgehende Verbindungen nur beim Scraping/LLM-Pull; **keinerlei** eingehende Verbindungen.

#### 0.1 Was Qubes am Design ändert

Qubes ist nicht „einfach Debian“. Sein Sicherheitsmodell und der Lebenszyklus der AppVM erzwingen harte Vorgaben, die
Installer und Laufzeit **einhalten müssen**:

1. **Die Persistenz des Dateisystems ist selektiv.** In einer AppVM überstehen nur **`/home`, `/usr/local` und `/rw`**
   einen Neustart; das Root-Dateisystem wird **bei jedem Start aus der TemplateVM zurückgesetzt**. Daher gilt:
   - Die App, ihr Virtualenv, die Datenbank, gescrapte Daten, Logs, Audit-Trail und alle heruntergeladenen LLM-Modelle
     **müssen unter `/home/user/...` liegen** (empfohlen: `/home/user/open-omniscience`).
   - **`apt`-/Systempakete bleiben *nicht* erhalten**, wenn sie in der AppVM installiert werden. Systemabhängigkeiten müssen
     **in der TemplateVM** installiert werden (und die AppVM neu gestartet) oder über Qubes `bind-dirs` eingebunden werden.
     Der Installer muss **trennen**: „Systemabhängigkeiten → TemplateVM“ vs. „Python-venv + App → AppVM `/home`.“
2. **Keine Annahme eines persistenten Root.** Root-Änderungen in der AppVM verschwinden beim Neustart. Die AppVM ist zu behandeln als:
   persistentes `/home`, flüchtiges Root.
3. **Netzwerk über eine NetVM.** Die AppVM erreicht das Internet nur über den ihr zugewiesenen Netz-/Firewall-Qube.
   Die App muss **offline sauber degradieren** und darf niemals Konnektivität voraussetzen.
4. **Keine GPU.** GPU-Passthrough ist in typischen Qubes-Setups unpraktikabel → **LLM-Inferenz läuft nur auf der CPU**.
   Standardmäßig **kleine Modelle** (z. B. `gemma2:2b`, `llama3.2:3b`, `qwen2.5:1.5b`); große Modelle nur auf Wunsch.
5. **Air-Gap / Split-VM ist eine erstklassige *zukünftige* Option (nicht v1).** Qubes macht das Muster „ethisches Scraping in einem
   vernetzten Qube, Analyse/Speicherung in einem Offline-Tresor-Qube“ über **qrexec/qubes-rpc** naheliegend. v1
   läuft in **einer AppVM**; die Architektur muss die *Fetch*-Grenze sauber halten, damit eine spätere Aufteilung eine
   Änderung der Bereitstellung ist und keine Neuentwicklung. (Das Repository enthält bereits rudimentäres `src/qubes/rpc/`- und
   `docs/QUBES_*`-Material — zu prüfen/zu ersetzen, nicht zu vertrauen.)

#### 0.2 Folgen von Python 3.13 (klärt die Konflikte bei Abhängigkeitsversionen)

- **Der Kern-Stack ist 3.13-sauber:** FastAPI, uvicorn, SQLAlchemy 2.x, pydantic 2.x, requests, httpx,
  beautifulsoup4, feedparser, numpy, pandas, scipy, scikit-learn, statsmodels — alle liefern 3.13-Wheels.
- **Ein lokales LLM erfordert KEIN schweres Python-ML.** Ollama ist ein **separates natives Binary**; die App spricht
  mit ihm **nur über HTTP**. Der volle LLM-Funktionsumfang läuft auf 3.13 mit nur `httpx`/`requests` — überhaupt kein
  `torch`/`transformers` in der App.
- **Schwere ML-Bibliotheken werden aus dem Kern gestrichen.** `torch`, `onnx`/`onnxruntime`, `tensorflow`,
  `pyAudioAnalysis` und der Deepfake-Stack werden für v1 **entfernt**, weil sie (a) derzeit
  **fabriziert** sind (das „Deepfake-CNN“ führt nie eine Inferenz aus), (b) schwer und hier **nur auf der CPU** lauffähig sind und
  (c) pro Paket ein 3.13-Wheel-Risiko darstellen (`pyAudioAnalysis` wird nicht mehr gepflegt; `igraph`/`leidenalg`/`gensim`
  müssen vor der Nutzung jeweils geprüft werden). Jede künftige ML-Funktion muss ihr Gewicht rechtfertigen und ein 3.13-Wheel nachweisen.
- **Ein Abhängigkeitsmanifest, auf 3.13 festgelegt.** Die sechs einander widersprechenden requirements-Dateien werden durch eine einzige
  `pyproject.toml` im Wurzelverzeichnis (`requires-python = ">=3.13"`) + optionale Extras (`[llm]`, `[analysis]`, `[dev]`) ersetzt.
  Die „korrigierenden“ KI-Kommentare und unmöglichen Pins werden gelöscht.

#### 0.3 Sicherheitsmodell für einen einzelnen lokalen Nutzer (vereinfacht die P0s)

Da der einzige Listener Loopback ist und der einzige Nutzer Sie sind:
- **Authentifizierung:** für v1 keine erforderlich, *sofern* der Server strikt an `127.0.0.1` gebunden ist und niemals
  durch eine Qubes-Firewallregel exponiert wird. (Ein einzelnes optionales API-Token kann später ergänzt werden, falls ein Proxy davorsteht.) Das **klärt**
  den Befund „keine Authentifizierung an den Endpunkten“ *für diesen Einsatz* — indem die Netzwerkexposition entfernt wird, statt
  RBAC hinzuzufügen.
- **`/metrics`:** wie alles andere nur über Loopback.
- **Die Sicherheit des Installers bleibt Pflicht:** kein unbestätigtes `rm -rf`, kein ungeprüftes `curl | sh`, niemals
  stderr des Paketmanagers verwerfen — Korrektheits-/Sicherheitsfragen unabhängig vom Einzelnutzerbetrieb.
- **Frontend-Assets lokal mitgeliefert** (keine Google Fonts / kein React vom CDN) — erforderlich für Offline/Qubes und
  für das Datenschutzprinzip.

---

### 1. Definition in einem Satz

Open-Omniscience ist eine **local-first, quelloffene Recherche-Plattform für investigative Journalistinnen und Journalisten**,
die viele weltweite Datenquellen auf ethische Weise zu einem **einzigen, durchsuchbaren, querverweisbaren
und herkunftsnachverfolgten Korpus** zusammenführt, mit optionaler **lokaler KI** zur Analyse — und bei der jedes Ergebnis
darauf ausgelegt ist, **wissenschaftlich und rechtlich belastbar** zu sein.

### 2. Für wen sie gedacht ist und für welche Aufgaben man sie „einstellt“

**Hauptnutzer:** eine investigative Journalistin, ein Forscher oder eine Analystin — wahrscheinlich allein oder in einer
kleinen Redaktion arbeitend, oft datenschutzsensibel (Quellen sind zu schützen), manchmal in eingeschränkten/vom Netz getrennten
Umgebungen.

**Zentrale Jobs-to-be-done:**
1. *„Sammle alles für meine Recherche Relevante aus vielen Quellen an einem Ort, automatisch.“*
2. *„Durchsuche und verknüpfe alles miteinander — Artikel, Märkte, E-Mails —, um Zusammenhänge zu finden.“*
3. *„Hilf mir, große Textmengen zu verstehen“* (zusammenfassen, übersetzen, Entitäten extrahieren) — **ohne
   meine Daten an irgendjemanden zu senden.**
4. *„Sag mir, wenn etwas vertrauenswürdig ist — oder misstrauenswürdig“* (Medien prüfen, Manipulation markieren).
5. *„Beweise, woher das stammt und dass ich es nicht verändert habe“* (Herkunftsnachweis für Veröffentlichung/Recht).
6. *„Benachrichtige mich, wenn sich etwas ändert“* (eine Quelle verstummt, ein Preis schießt hoch, ein Narrativ entsteht).

### 3. Leitprinzipien (die Unverhandelbaren)

Sie sind der Kern der Absicht und müssen jede Funktion begrenzen. Wo heutiger Code eines davon verletzt,
ist das ein Defekt, kein Kompromiss.

1. **Local-first & offlinefähig.** Läuft vollständig auf dem Rechner/Server des Nutzers. Muss ohne
   Internet funktionieren, außer während des Scrapings selbst. Geeignet für den Air-Gap-Betrieb (mit vorab bereitgestellten Daten/Modellen).
2. **Datenschutzwahrend.** Keine Telemetrie. **Keine Nutzerdaten verlassen jemals den Rechner** — insbesondere bei der LLM-
   Verarbeitung (nur lokal über Ollama). ✅ GEKLÄRT (§0): alle Frontend-Assets (Schriften, JS-Bibliotheken) werden
   **lokal mitgeliefert** — keine CDN-Aufrufe — erforderlich für die Qubes-/Offline-Haltung.
3. **100 % FOSS.** Aller Code und alle Modelle quelloffen. ⚠️ DECIDE: Die Lizenz ist **GPLv3** im Wurzelverzeichnis, aber
   **AGPL-3.0** in Säule 3 — projektweit eine wählen (AGPL ist bei Netzwerknutzung strenger).
4. **Ethisch durch Konstruktion.** `robots.txt` und Ratenlimits respektieren, den Bot identifizieren, nur öffentliche Daten,
   niemals Paywalls umgehen oder Zugangsdaten zum Scrapen verwenden. **Im Zweifel *geschlossen* scheitern** — wenn die Konformität nicht
   überprüft werden kann, wird nicht gescrapt.
5. **Belastbare Ergebnisse (wissenschaftlich + rechtlich).** Jedes Analyseergebnis trägt ehrliche Unsicherheit und
   nachvollziehbare Herkunft. **Keine erfundenen Zahlen.** Ein Konfidenzwert muss aus einer echten Methode stammen oder
   darf nicht existieren. Die Verwahrungskette muss echt sein (signiert, manipulationssicher), keine einfache Logdatei.
6. **Einheitlicher Korpus.** Alles Erfasste — Nachrichten, Finanzdaten, Rohstoffe, E-Mail — liegt in **einer
   Datenbank** und ist **in einer Abfrage querverweisbar**. Das ist der Daseinsgrund des Produkts.
7. **Transparenz statt stillem Ausweichen.** Das System darf niemals still zu ungültigen Ergebnissen degradieren.
   Fehlendes Modell, blockierte Quelle, nicht verfügbare Abhängigkeit → **sichtbarer, expliziter Status**, niemals ein
   stiller Platzhalter.

### 4. Das zentrale mentale Modell

```
        ┌─────────────────────────── INGESTION ───────────────────────────┐
        │  Web articles · RSS · Financial · Commodities · Email/Newsletters │
        │            (all ethically scraped / retrieved)                    │
        └───────────────────────────────┬───────────────────────────────────┘
                                         ▼
        ┌──────────────────── ONE UNIFIED, PROVENANCE-TRACKED STORE ────────┐
        │  articles · financial_data · commodity_data · emails · entities    │
        │  + links between them (article ↔ price move ↔ email ↔ entity)      │
        └───────────────────────────────┬───────────────────────────────────┘
                                         ▼
   ┌──────────── RETRIEVAL ────────────┐   ┌──────────── ANALYSIS (opt-in) ───────────┐
   │ Boolean / full-text search        │   │ Local LLM · verification · stats ·        │
   │ filters · cross-source correlation│   │ monitoring/alerts · correlation engines   │
   │ export (CSV/JSON) · reports       │   │ (every result: method + uncertainty)      │
   └───────────────────────────────────┘   └───────────────────────────────────────────┘
                                         ▼
                         GUI (search, dashboards, source mgmt, reports)
                         + REST API (everything available programmatically)
```

**Das Rückgrat (Erfassung → einheitlicher Speicher → Suche → Export) muss grundsolide sein, bevor irgendeine Säule kommt.**
Säulen sind *Anreicherer*, die aus dem gemeinsamen Speicher lesen und in ihn zurückschreiben.

---

### 5. Funktionsumfang nach Fähigkeitsbereichen

#### 5.1 Datenerfassung (P0)
- **Quelltypen:** Nachrichten-Websites (HTML), RSS/Atom-Feeds. Später: APIs, soziale Plattformen, Dateiablagen.
  ⚠️ DECIDE: Säule 4 nennt Twitter/X, Reddit, Telegram, Mastodon, S3/SFTP — bestätigen, welche (falls überhaupt)
  tatsächlich zum Umfang gehören und welche nur Wunschdenken sind.
- **Ethischer Scraper (eine einzige, gemeinsame Implementierung):** robots.txt-Prüfung (gecacht, http+https-bewusst,
  **schließt bei Unsicherheit**), Ratenbegrenzung pro Quelle, identifizierender User-Agent, Wiederholung/Backoff.
  **Ein Abruf pro URL** — kein doppelter Abruf, kein roher Umgehungspfad.
- **Deduplizierung:** auf Basis von Inhalts-Hash + kanonischer URL; denselben Artikel niemals zweimal speichern.
- **Normalisierung:** Titel, Autor, Veröffentlichungsdatum, Sprache, kanonische URL und Fließtext zuverlässig extrahieren.
  ⚠️ DECIDE: Echte Nachrichtenextraktion braucht Regeln pro Website oder eine Bibliothek (z. B. im Stil von trafilatura); der
  aktuelle generische CSS-Ansatz liefert still „No Title/No Content“. Bestätigen, dass wir eine robuste Extraktion übernehmen.
- **Planung & inkrementelle Aktualisierungen:** periodisches erneutes Scrapen, nur neue/geänderte Inhalte abrufen, unterbrochene
  Läufe fortsetzen.

#### 5.2 Einheitlicher Datenspeicher (P0)
- **Eine einzige Datenbank** für alle Entitätstypen, mit expliziten **Verknüpfungstabellen**, die sie verbinden
  (Artikel ↔ Finanzinstrument, Artikel ↔ Rohstoff, Artikel ↔ E-Mail, Artikel ↔ benannte Entität).
- **Herkunftsfelder in jedem Datensatz:** Quelle, Abrufzeitpunkt, Original-URL, Inhalts-Hash,
  Trennung von Roh- und verarbeiteten Daten.
- **Backends:** SQLite für Einzelnutzer/Desktop; PostgreSQL für Server/parallele Nutzung.
  ⚠️ DECIDE: SQLite als Standard + optional Postgres bestätigen (die Dokumente nennen beides; außerdem Redis fürs Caching —
  dabei oder nicht?).
- **Audit-Log:** nur anhängend, **manipulationssichere** Aufzeichnung jeder Erfassung und Änderung.

#### 5.3 Suche & Abruf (P0)
- **Volltextsuche** über den gesamten Korpus.
- **Boolesche Operatoren** (`AND`/`OR`/`NOT`), **Phrasen in Anführungszeichen** und **Klammern mit korrekter
  Rangfolge** — umgesetzt mit einer echten Grammatik oder der nativen FTS der Datenbank, nicht mit String-Tricks.
- **Strukturierte Filter:** Quelle, Datumsbereich, Sprache, Tags/Kategorie, Entität, Datentyp.
- **Seitenweise Ausgabe**, Ergebnis-Ranking, Snippet/Hervorhebung.
- **Export:** CSV und JSON (und ⚠️ DECIDE: PDF-/Berichtsformate?), getreu der gefilterten Ergebnismenge.

#### 5.4 Querverweise & Korrelation (P1 — das Alleinstellungsmerkmal)
- Von jedem Datensatz zu verwandten Datensätzen über Typen hinweg springen (Artikel → erwähnte Unternehmen → Kursbewegungen
  um das Veröffentlichungsdatum → verwandte E-Mails).
- **Korrelations-Engines** (Finanzen/Rohstoffe ↔ Nachrichten), die *Kandidaten* für Zusammenhänge mit einem
  **ehrlichen, definierten Maß** sichtbar machen (und klar kennzeichnen: Korrelation ≠ Kausalität). Keine erfundenen p-Werte.
- Entitätszentrierte Ansicht: alles, was der Korpus über eine Person/Organisation/einen Ort/ein Instrument weiß.

#### 5.5 Lokale LLM-Analyse (P1)
- **Laufzeit:** Ollama, vollständig lokal. Modelle sind austauschbar; ausgeliefert wird ein kleiner, sinnvoller Standard, der *tatsächlich
  existiert*. ⚠️ DECIDE: Der aktuelle Standard `gemma4:e2b` und die meisten gelisteten Modelle (Gemma 4, Llama 4, Qwen 3.5)
  sind halluziniert — den Katalog durch echte Tags ersetzen (z. B. `gemma2:2b`, `llama3.2:3b`, `qwen2.5`,
  `phi3`).
- **Fähigkeiten:** generieren, chatten (mit Kontext), extrahieren (Entitäten/Schlüsselwörter/Zusammenfassungen/Zitate/Links),
  übersetzen (mehrsprachig), analysieren (Stimmung/Ton/Lesbarkeit; Bias nur, wenn ehrlich eingegrenzt),
  synthetisieren (Zusammenfassungen, Vergleiche, Zeitleisten, Berichte), Stapelverarbeitung.
- **Laut degradieren:** Fehlen Ollama oder das Modell, wird das gesagt — niemals eine gefälschte Analyse zurückgeben.

#### 5.6 Verifikation & Abwehr von Täuschung — *Säule 3* (P2, Umfang offen)
- **Absicht:** manipulierte Medien (Bild-/Video-/Audio-Deepfakes), Propagandatechniken, kognitive
  Verzerrungen, Bots und koordinierte Kampagnen erkennen; Metadaten (EXIF/ID3) und modalübergreifende Konsistenz validieren.
- ⚠️ DECIDE (wichtig): Heute ist das **fabriziert** — das „Deepfake-CNN“ führt nie eine Inferenz aus; Werte
  sind Unschärfe-Heuristiken; die Abdeckung von Bias/Propaganda ist größtenteils unerreichbar; „Genauigkeit >95 %“ ist ein Wunsch.
  Eine Option wählen:
  - **(a) Streichen** der Medienforensik vorerst und nur ausliefern, was ehrlich ist (Metadaten-/EXIF-Validierung ist echt
    und nützlich); **(b) Neu aufbauen** mit echten, evaluierten FOSS-Modellen und veröffentlichter Genauigkeit; oder
    **(c) Behalten**, aber **klar als „experimentelle Heuristik, kein Beweis“ kennzeichnen.**
  Meine Empfehlung: jetzt (a), später (b). Fabrizierte Forensik ist das größte einzelne Haftungsrisiko für ein
  Werkzeug für Journalismus/Recht.

#### 5.7 Wissenschaftliche Strenge — *Säule 2* (P1)
- **Absicht:** die quantitativen Aussagen der Plattform belastbar machen — echte statistische Tests, Konfidenz-
  intervalle, Bewertung von Reproduzierbarkeit/Herkunftslinie und „Peer-Review“ durch mehrere lokale LLMs, die sich gegenseitig prüfen.
- Diese Säule ist die am echtesten umgesetzte (echtes scipy/statsmodels). Behalten, härten und zum
  **Torwächter** machen: Jede Zahl, die die App dem Nutzer zeigt, sollte eine ehrliche Unsicherheitsangabe durchlaufen.

#### 5.8 Echtzeitüberwachung & Alarmierung — *Säule 4* (P2)
- **Absicht:** fortlaufende Überwachung der Quellen; Erkennung von Anomalien/Trends/Mustern; Anreicherung mit Threat-Intel;
  Mehrkanal-Alarme (E-Mail/Webhook/Chat) mit Regeln und Eskalation.
- ⚠️ DECIDE: Die aktuellen Health-Checks sind simuliert (`sleep; return HEALTHY`), und Threat-Intel/STIX-TAXII
  existieren nicht. Umfang bestätigen: echte Verfügbarkeitsüberwachung der Quellen + Anomalie-Alarme auf dem Korpus sind
  erreichbar und wertvoll; STIX/TAXII, SMS/Twilio, Slack/Teams sind schwergewichtig — dabei oder nicht?

#### 5.9 Finanzaufklärung — *Säule 5* (P2, in den Dokumenten mit 0 % angegeben)
- **Absicht:** weltweite Börsen (OHLC + Fundamentaldaten) aus offenen Webquellen scrapen (keine APIs/Paywalls),
  Schwankungen/Muster/Anomalien erkennen und **Kursbewegungen mit Nachrichten** in der gemeinsamen Datenbank **korrelieren**.
- ⚠️ DECIDE: Das ist **reines Design (0 % gebaut)**, trotz eingechecktem Gerüstcode. Bestätigen, dass es ein echtes
  Ziel ist, und falls ja, seinen realistischen ersten Umfang (z. B. eine Handvoll Börsen, tägliche OHLC, Korrelation mit
  Artikeln) statt „50+ Börsen / 10.000+ Unternehmen“ ab dem ersten Tag. Hinweis: robustes Scraping mehrerer Börsen
  ohne APIs ist ein großes, fragiles Unterfangen.

#### 5.10 Seltene Erden / Rohstoffaufklärung — *Säule 6* (P2, in den Dokumenten mit 0 % angegeben)
- **Absicht:** dasselbe Muster wie Säule 5 für die 17 Seltenerdelemente — Preise, Produktion, Lagerbestände,
  korreliert mit geopolitischen/Nachrichtenereignissen; mit Prognose.
- ⚠️ DECIDE: Ebenfalls **reines Design (0 % gebaut)**. Umfang und Priorität gegenüber Säule 5 bestätigen. (Korrektur nötig: Die
  Einheitenrechnung der Preisnormalisierung liegt derzeit um ~1000× daneben, und Währungen werden nicht umgerechnet.)
  ⚠️ DECIDE: Gehört „Prognose“ zum Umfang? Ehrliche Prognosen mit Unsicherheit sind schwierig; Empfehlung: zurückstellen.

#### 5.11 E-Mail- & Newsletter-Aufklärung (P1/P2)
- **Absicht:** Abruf über IMAP/POP3 und aus Newsletter-Quellen (Substack/Mailchimp/RSS-to-Email), parsen +
  bereinigen, Anhänge verarbeiten (PDF/Office/Bilder mit OCR), Entitäten und Kommunikationsnetze extrahieren
  und **in denselben durchsuchbaren Korpus einfügen**.
- **Datenschutz/Einwilligung sind hier oberstes Gebot** (private Kommunikation): ausdrückliche Autorisierung, verschlüsselte
  Speicherung der Zugangsdaten, Datenminimierung, Aufbewahrung/Recht auf Vergessenwerden.
- ⚠️ DECIDE: Newsletter-API-Integrationen (Substack/Mailchimp/usw.) oder nur IMAP + RSS-to-Email für v1?

#### 5.12 GUI / UX (P0 für den Kern, P1+ für Säulen-Dashboards)
- **Kern-GUI:** Suchoberfläche, Durchsehen der Ergebnisse, Quellenverwaltung, Export, einfache Dashboards.
- **Säulen-Dashboards (später):** Finanz-Heatmaps/-Diagramme, Rohstoffansichten, Überwachung/Alarme, E-Mail-
  Posteingang, Korrelations-Explorer.
- ✅ GEKLÄRT (§0): **Web-UI, ausgeliefert von FastAPI unter `127.0.0.1:8000`; die Tkinter-Desktop-App entfällt**
  (`python3-tk` entfernen). Im Browser der AppVM öffnen.
- ✅ GEKLÄRT (§0): Das Frontend ist **Vanilla-JS + lokal mitgelieferte Bibliotheken (ausgeliefert aus `/static`)** — kein CDN.
  ⚠️ DECIDE (geringfügig): Diagramme leichtgewichtig halten (z. B. eine kleine, mitgelieferte Diagrammbibliothek) vs. keine in v1.

#### 5.13 Berichte & belastbare Ergebnisse (P1)
- Rechercheberichte erzeugen, die Befunde **mitsamt ihrer Herkunft** bündeln (Quellen, Zeitstempel,
  Hashes, Methoden, Unsicherheit).
- **Verwahrungskette / Integrität:** kryptografische Signatur + Manipulationsnachweis für exportierte Beweise
  (die Krypto-Module existieren, sind aber nicht angebunden). Erst das macht die Behauptung der „rechtlichen Verwertbarkeit“
  real statt dekorativ.

---

### 6. Nichtfunktionale Anforderungen

- **Plattform:** ✅ GEKLÄRT (§0) — **Qubes OS Debian-AppVM** ist das *einzige* unterstützte Ziel für v1
  (dort gebaut und getestet). Ein einfaches Debian 13 mag funktionieren, ist aber kein Ziel; keine plattformübergreifende Zusage.
- **Python:** ✅ GEKLÄRT (§0) — **3.13**, einheitlich in `pyproject.toml`, `.python-version` und
  jeder CI. Abhängigkeiten ohne 3.13-Wheels streichen (siehe §0.2).
- **Installationsumfang:** ein echter **minimaler Kern** (Web + Datenbank + Suche, leichtgewichtig), getrennt von optionalen
  Extras (`[llm]`, `[analysis]`). **Eine** `pyproject.toml` — nicht sechs einander widersprechende Manifeste. Der Installer
  respektiert die Qubes-Persistenz (§0.1): Systemabhängigkeiten in der TemplateVM, venv+Daten in `/home`.
- **Sicherheit:** ✅ GEKLÄRT (§0) — einzelner lokaler Nutzer, **nur Loopback**, daher kein RBAC. Weiterhin Pflicht:
  ausschließlich parametrisierter Datenbankzugriff (den Blocklisten-„Sanitizer“ löschen), keine Geheimnisse im Code, `/metrics` nur über Loopback
  und ein **sicherer Installer** (kein unbestätigtes `rm -rf`, kein ungeprüftes `curl | sh`, niemals stderr des Paketmanagers verwerfen).
- **Leistung:** nicht blockierende I/O für Netzwerk-/LLM-Arbeit; begrenzte Nebenläufigkeit; die App bleibt reaktionsfähig, während
  sie scrapt/inferiert. Annahmen **nur für CPU** (keine GPU in Qubes). Zielwerte festgelegt nach realistischen AppVM-
  Ressourcen, nicht nach Wunschvorstellungen.
- **Offline:** alle Assets, Schriften und (vorab gezogenen) Modelle lokal; dokumentiertes Verfahren für den Betrieb mit
  abgekoppelter NetVM, nachdem Daten/Modelle abgerufen wurden.
- **Beobachtbarkeit:** strukturierte Logs (unter `/home`), ehrliche Health-Checks, Prometheus-Metriken über Loopback —
  die den realen Zustand widerspiegeln.

### 7. Ausdrückliche Nicht-Ziele / außerhalb des Umfangs (vorgeschlagen — anpassen)

- Kein universeller Web-Crawler/Spiegel (die HTTrack-Abstammung ist ein Überbleibsel; diese Rahmung fallen lassen).
- Kein Scraper zum Umgehen von Paywalls, für Credential-Stuffing oder unter Verletzung von Nutzungsbedingungen.
- Kein Cloud-/SaaS-Produkt; keine externen KI-APIs.
- ⚠️ DECIDE: Gehören Prognose (5.10), Erfassung sozialer Medien (5.8) und Medienforensik (5.6) zum ersten
  echten Release oder nicht?

### 8. Daten-, Herkunfts- & Rechtsbelastbarkeitsmodell (bereichsübergreifend)

- Jedes gespeicherte Element: `{source, original_url, fetched_at, content_hash, raw_payload_ref, processing_log}`.
- Jedes abgeleitete/analytische Ergebnis: `{method, version, inputs_ref, uncertainty/confidence_basis,
  computed_at}` — **Konfidenz ist niemals eine fest einprogrammierte Konstante.**
- Exportierte Beweise: optional **signiert**, mit einem überprüfbaren Manifest (Hashes + Merkle/GPG), damit eine dritte
  Partei die Integrität bestätigen kann. Das ist die konkrete Bedeutung von „Säule 4: rechtliche Verwertbarkeit“.

### 9. Entscheidungen (zusammengeführt)

**✅ Durch den Einsatzkontext geklärt (§0):**
- **3. Einsatz- & Bedrohungsmodell** → einzelner lokaler Nutzer, Qubes-Debian-AppVM, nur Loopback, kein RBAC.
- **7. GUI** → Web-UI unter `127.0.0.1:8000`, Vanilla-JS, Assets lokal mitgeliefert; Tkinter entfällt.
- **8. Plattform/Python** → Qubes-Debian-AppVM, Python 3.13, SQLite als Standard (Postgres/Redis für v1 **draußen**).

**⚠️ Noch offen (Ihre Entscheidung — sinnvolle Standards vorgeschlagen):**
1. **MVP-Umfang:** *vorgeschlagen* — zuerst nur der vertrauenswürdige Kern (Phase 1), dann LLM. Bestätigen.
2. **Neuaufbau-Strategie:** *vorgeschlagen* — die schmalen guten Teile retten (DB-Modelle, `ethical_scraper`,
   `async_db`, FastAPI-Gerüst), die fabrizierten Säulen löschen, den Kern um sie herum neu aufbauen. Bestätigen vs.
   kompletter Neubeginn.
4. **Medienforensik (Säule 3):** *vorgeschlagen* — **(a) streichen** von Deepfake/Propaganda/Bias für v1 (zudem
   3.13-/CPU-feindlich), echte Metadaten-/EXIF-Validierung **behalten**. Bestätigen.
5. **Finanzen (5) & Rohstoffe (6):** *vorgeschlagen* — auf Phase 3 verschieben, dann **eine** schmale Vertikale bauen.
   Welche zuerst?
6. **E-Mail:** *vorgeschlagen* — für v1 nur IMAP + RSS-to-Email; Newsletter-API-Integrationen verschieben. Bestätigen.
9. **Lizenz:** GPLv3 vs. AGPL-3.0 projektweit — braucht noch eine Entscheidung.
10. **Bestätigung des Nicht-Umfangs:** Prognose, Erfassung sozialer Medien, STIX/TAXII, SMS-/Chat-Alarme —
    für v1 *vorgeschlagen* draußen.

### 10. Vorgeschlagene Phasen (Vorschlag, keine Zusage)

- **Phase 1 — Vertrauenswürdiger Kern:** ethische Erfassung → einheitlicher Speicher (mit Herkunft) → korrekte boolesche/
  Volltextsuche → Export → minimale Web-GUI → echte Tests. *Alles andere bleibt aus, bis das grün ist.*
- **Phase 2 — Lokales LLM + wissenschaftliche Strenge:** Ollama anbinden (echte Modelle, laute Degradierung); Säule 2
  zum Ehrlichkeitstor für jede angezeigte Zahl machen.
- **Phase 3 — Eine Vertikale + Korrelation:** **entweder** Finanzen **oder** Rohstoffe wählen, einen schmalen, aber
  echten Ausschnitt bauen, das Korrelationserlebnis Artikel↔Daten durchgängig nachweisen.
- **Phase 4 — Überwachung/Alarme, E-Mail, Verifikation (Metadaten zuerst):** Anreicherer einzeln hinzufügen,
  jeder tatsächlich funktionierend und getestet.
- **Phase 5 — Belastbare Berichte:** echte Signatur/Verwahrungskette in die Exporte einbinden.

---

### 11. Umsetzungsstand (aktuell)

Was heute gebaut und getestet ist, abgebildet auf den obigen Umfang (die Absicht ist unverändert; dies
hält fest, wo die Realität jetzt steht). Details in den verlinkten Funktionsdokumenten.

- **Vertrauenswürdiger Kern (5.1–5.3, 5.13):** ✅ ethische Erfassung, einheitlicher Herkunftsspeicher,
  boolesche FTS5-Suche, CSV/JSON-Export, signierte Verwahrungskette.
- **Erfassung im großen Maßstab (5.1):** ✅ In-App-**Scheduler** (Start/Stopp, Intervall, Modi
  rss/crawl/markets) und ein **begrenzter rekursiver Crawler** (*Entdeckung* innerhalb derselben Domain,
  robots schließt im Zweifel, Tiefen-/Seitenbegrenzung) — kein universeller Spiegel (§7 eingehalten).
- **GUI (5.12):** ✅ Web-UI mit Tabs — Suche · Ingest · **Quellen & Datenbank** (Statistiken,
  Quellenverwaltung, **weltweite Abdeckung**) · **Märkte** · **Einblicke** · Verwahrungskette
  · **Einstellungen** (Design + SQLite-Sicherung/-Wiederherstellung). Ohne Abhängigkeiten, offline.
- **Finanzen & Rohstoffe (5.9, 5.10):** ✅ schmale, echte Vertikale — **Extraktionsregeln** für Preise
  pro Quelle, **offizielle CSV-Feeds** (FRED→World Bank/EIA), Diagramme und
  ehrliche Preis↔Nachrichten-Korrelation. Einheitenrechnung korrigiert; Zahlen nur aus einer geprüften Regel
  oder importierten CSV. Siehe [USER_MANUAL.md](USER_MANUAL.md).
- **Weltweite Quellenabdeckung:** ✅ mitgelieferter Marktkatalog + ein **datenbasierter
  Generator** (Wikidata CC0) für Nachrichtenmedien **und** Institutionen pro Land, mit einem
  Abdeckungsbericht. CSV-Import/-Export der Quellenliste. Siehe
  [ROADMAP.md](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).
- **Querverweise & Korrelation (5.4):** ✅ **Schlüsselwort- & Entitätsanalysen** —
  Extraktion bei der Erfassung, Erwähnungsspeicher mit Kontext, Trends, PMI-Assoziationen
  („Mindmap“) und eine Karte nach Land/Stadt. Siehe [USER_MANUAL.md](USER_MANUAL.md).
- **Wikipedia als verfolgte Quelle (neu):** 🚧 Grundlage für die Änderungsverfolgung (Ausgaben pro Sprache,
  Delta-Speicherung, Markierung großer Bearbeitungen/von Geschichtsrevisionismus inkl. ORES) — Schema +
  Parser + Markierung fertig; Live-Abfrage, Tab und Offline-Downloader als Nächstes. Siehe
  [USER_MANUAL.md](USER_MANUAL.md).
- **Verifikation (5.6):** ✅ nur ehrliche Bild-EXIF/-Metadaten (fabrizierte Forensik
  bleibt in Quarantäne). **LLM (5.5)**, **Überwachung/Alarme (5.8)**, **E-Mail (5.11)**:
  teilweise/in der Warteschlange.

---


---

## Säulen-Absichtskarte — wo der Zweck jeder Säule heute lebt

Das ursprüngliche Design gliederte die Plattform in sechs „Säulen“. Diese Säulenbäume
umfassten ~50k Zeilen, die die laufende App nie importierte — größtenteils reines Design oder
fabriziert. **Ihre *Absicht* wurde bewahrt**: Der echte Zweck jeder Säule
ist heute ein kleines, ehrliches, getestetes Modul innerhalb von `src/` (oder ausdrücklich zurückgestellt).
Die ursprünglichen Säulenbäume werden zur Referenz und
Historie unter `quarantine/pillars/` aufbewahrt; nichts wird gelöscht.

| Säule (Absicht) | Wo die Absicht heute lebt | Status |
|---|---|---|
| **1 — Datenerfassung** (ethisches Scraping → einheitlicher Speicher) | `src/ingest/` (fetcher, extract, pipeline, email) + `src/database/` | ✅ Echt, getestet |
| **2 — Wissenschaftliche Strenge** (ehrliche Statistik, Unsicherheit) | `src/analysis/` (`statistical_tests`, `confidence_intervals`) + `POST /api/analysis/*` | ✅ **Den echten scipy/statsmodels-Code gerettet** + seine 60 Tests |
| **3 — Abwehr von Täuschung** (Medien prüfen) | `src/verification/metadata.py` (ehrliche EXIF/Metadaten) + `POST /api/verify/image-metadata` | ✅ Ehrlicher Umfang. Deepfake-/Propaganda-/Bias-Detektoren waren fabriziert → `quarantine/pillar3_analysis/` |
| **4 — Überwachung + rechtliche Verwertbarkeit** | `src/monitoring/` (echte Verfügbarkeit + Anomalien) und `src/reporting/` + `src/crypto/` (mit Merkle + Ed25519 signierte Beweise) | ✅ Echt, getestet |
| **5 — Finanzaufklärung** | *Zurückgestellt.* Das Muster ist durch die Neuimplementierung von Säule 6 belegt; eine Finanzvertikale kann `src/commodity` + `src/analysis` wiederverwenden. | ⏸ Ursprünglich reines Design (0 %); noch nicht gebaut |
| **6 — Seltene Erden / Rohstoffe** | `src/commodity/` (Preise, korrekte Einheitenumrechnung, **echte** scipy-Korrelation, CSV-Import) + `POST /api/commodities/*` | ✅ Echt, getestet |

### Was in diesem Schritt gerettet wurde (Säule 2)
- `src/analysis/statistical_tests.py` — t-Tests, ANOVA, Chi-Quadrat, Pearson/Spearman,
  Mann-Whitney, Wilcoxon, Regression, Tukey HSD (scipy/statsmodels). Jedes Ergebnis
  trägt Teststatistik, p-Wert, Freiheitsgrade, Effektstärke und Stichprobengröße.
- `src/analysis/confidence_intervals.py` — Mittelwerte und Anteile (t/normal/Wilson/
  Clopper-Pearson/Agresti-Coull).
- Bereitgestellt unter `POST /api/analysis/{t-test,correlation,anova,mann-whitney,confidence-interval}`,
  damit eine Journalistin prüfen kann, ob ein Muster in ihren Daten tatsächlich signifikant ist.
- Die echten Testsuiten von Säule 2 sind mit dem Code umgezogen (`tests/test_statistical_tests.py`,
  `tests/test_confidence_intervals.py`).

### Was NICHT gerettet wurde (und warum)
- `peer_review` / `consensus` / `reproducibility` aus Säule 2 — spekulativ oder oberflächlich
  (z. B. war Reproduzierbarkeit eine Bewertungsskala aus gemittelten Booleschen Werten). Geparkt; bei Bedarf mit echten
  Methoden wiederbeleben.
- Die forensischen Detektoren aus Säule 3, die simulierte Überwachung/Threat-Intel aus Säule 4, die Gerüste der Säulen
  5/6 — fabriziert oder reines Design; die ehrlichen Teile sind bereits in `src/`.

### Gesamtwirkung
Das Repository spiegelt nun wider, was tatsächlich läuft: ein Live-Kern von ~16k Zeilen (plus die
geretteten Statistiken), wobei die erhofften/fabrizierten ~50k Säulenzeilen in
`quarantine/pillars/` geparkt sind, statt sich als funktionierende Funktionen auszugeben.


---

## GUI-Neugestaltung — „0.05“

> Eine Neugestaltung der Open Omniscience-Oberfläche von Grund auf, gedacht vom Nutzer
> aus. Dieses Dokument ist das *Warum*; `src/static/index.html` ist das *Was*.
> Lesen Sie es zuerst, wenn Sie die Entscheidungen verstehen (oder anfechten) wollen.

---

### 0. Der Auftrag, neu formuliert

Die gesamte GUI für eine bestimmte Person neu gestalten: **eine wahrheitssuchende Akteurin — eine
Ermittlerin/Journalistin, die *kein* Freund von Computern ist**, die die Welt so verstehen will,
wie sie wirklich ist, und ihre Befunde glaubwürdig vermitteln will. Das Ergebnis muss
elegant, schön, anpassungsfähig, weitgehend konfigurierbar, einfach *und* tiefgründig sein und so gut,
dass eine Kollegin beim Blick über die Schulter sagt: *„Was ist das — kann ich das
haben?“* Es muss respektieren, was das Projekt bereits ist: **Einzelnutzer, nur Loopback,
offline-first, ohne Abhängigkeiten, keine Telemetrie**, geleitet von der **Münchner Erklärung**
(Wahrheit, Quellenprüfung, Privatsphäre, keine Propaganda).

#### Technische Haltung (und der ehrliche Kompromiss)

Die bisherige UI ist eine einzige `index.html` mit 2.200 Zeilen, die ~110 Funktionen mit ~150
API-Endpunkten verbindet. Diese Funktionen *funktionieren und sind getestet*. Eine Neuschreibung von Grund auf hätte
eine hübschere Hülle mit hoher Wahrscheinlichkeit still kaputter Schaltflächen hervorgebracht — das
genaue Gegenteil eines Werkzeugs, dessen gesamtes Verkaufsargument **Ehrlichkeit** ist. Daher ist dies eine
**vollständige Neugestaltung von allem, was die Nutzerin sieht und berührt** — Bildsprache,
Layout, Navigationsmodell, Informationsarchitektur, Benennung, Einführung,
Anpassung und zwei völlig neue Oberflächen (ein Home-Dashboard und ein In-App-Leser für die Dokumentation)
— aufgebaut *auf der bewährten Datenschicht*, wobei jede ursprüngliche Element-ID
erhalten bleibt, damit nichts zurückfällt. Abhängigkeitsfreiheit bleibt absolut: **kein CDN, keine Web-
Fonts, kein Framework** — eine eigenständige Datei, die mit abgekoppelter NetVM läuft.

---

### 1. Personas (wem wir tatsächlich dienen)

**Amara — investigative Journalistin, 44. Primäre Persona.**
Berichtet über Korruption bei öffentlichen Aufträgen. Brillante Reporterin, widerwillige Computernutzerin. Arbeitet
an sensiblen Geschichten und ist (zu Recht) misstrauisch gegenüber Überwachung und Datenverlust.
*Braucht:* schnell Dinge in ihrem eigenen Korpus finden; beweisen, dass ein Dokument echt und
unverändert ist; etwas exportieren, das sie einer Redakteurin oder einem Gericht übergeben kann; sich nie dumm fühlen.
*Fürchtet:* Arbeit zu verlieren, verfolgt zu werden, Fachjargon, neben einem „technischen“ Kollegen amateurhaft zu wirken.
*Erfolgsbedingung:* Sie öffnet die App und weiß sofort, was zu tun ist, und was sie
produziert, wirkt vertrauenswürdig *und ist es*.

**Daniel — freiberuflicher OSINT-Rechercheur, 29. Power-Persona.**
Halbtechnisch, schnell, tastaturgesteuert, betreibt viele Quellen. *Braucht:* Dichte, Stapel-
operationen, Trends/Assoziationen, Marktkorrelationen, Tastenkürzel, eine Befehls-
palette. *Fürchtet:* Händchenhalten, das ihn bremst; versteckte Funktionen.
*Erfolgsbedingung:* Er muss nie die Maus anfassen und findet fortgeschrittene Möglichkeiten auf Abruf.

**Schwester im Geiste — die „Akteurin“, 50er. Werte-Persona.**
Misstraut Big Tech; will Souveränität. *Braucht:* den Beweis, dass nichts nach Hause telefoniert; Offline-
Betrieb; einfache Erklärungen dazu, was jede Aktion für ihre Netzwerkexposition bedeutet.
*Erfolgsbedingung:* Sie kann in der App genau nachlesen, was sie tun wird und was nicht.

**Elliot — der Redakteur, 38. Empfänger-Persona.**
Öffnet die App nie; *empfängt* ihre Ergebnisse. *Braucht:* Exporte, die für sich genommen lesbar und
überprüfbar sind. Die UI dient ihm indirekt: Beweisbündel, signierte
Verwahrung, saubere CSV/JSON.

**Folgerung für das Design:** für Amara führen (Klarheit, Anleitung, Vertrauen), Daniels
Tiefe so einschichten, dass sie ihr nie im Weg steht (schrittweise Offenlegung + Befehlspalette),
die Souveränität der Akteurin in Texten und Verhalten achten und Elliots
Artefakte zu Bürgern erster Klasse machen.

---

### 2. Designprinzipien (hergeleitet, nicht entliehen)

1. **Klarheit vor Raffinesse.** Einfache Verben, menschliche Beschriftungen, eine offensichtliche primäre
   Aktion pro Bildschirm. Fachjargon („ingest“, „Korpus“, „Merkle-Wurzel“) wird übersetzt oder
   direkt erklärt, nie vorausgesetzt.
2. **Vertrauen ist das Produkt.** Überprüfbarkeit, Herkunft und „diese Zahl ist echt,
   nicht geschätzt“ werden sichtbar gemacht, nicht vergraben. Die Ästhetik soll sich wie ein
   Instrument *anfühlen*, nicht wie ein Spielzeug.
3. **Schrittweise Offenlegung.** Standardmäßig einfach; Tiefe einen Klick entfernt. Erweiterte
   Bereiche klappen ein; selten genutzte Module lassen sich ganz ausblenden.
4. **Anpassbar, weil Vertrauen persönlich ist.** Designs, Akzentfarbe, Dichte, Schriftgröße,
   Layout und *welche Werkzeuge überhaupt erscheinen* legt die Nutzerin fest — und sie
   werden nur lokal gespeichert.
5. **Ehrlichkeit in der Oberfläche.** Hängt eine Fähigkeit von einem optionalen Extra ab, sagt die
   UI das, statt etwas vorzutäuschen. Nichts täuscht Erfolg vor.
6. **Souverän durch Konstruktion.** Keinerlei externe Anfragen. Das Erscheinungsbild wird
   mit Systemschriften und handgebauten SVG-Icons erreicht.
7. **Tastatur zuerst ist auch Barrierefreiheit zuerst.** Eine Befehlspalette und Tastenkürzel
   dienen Daniel *und* machen die ganze App ohne präzises Mausen erreichbar.

---

### 3. Analyse Werkzeug für Werkzeug — Vor- und Nachteile, Entscheidung

Die alte Reihe oberer Tabs: *Suche · Ingest · Quellen · Datenbank · Märkte · Einblicke ·
Wikipedia · Verwahrungskette · Einstellungen.* Eine nach der anderen für unsere Personas bewertet.

| Alter Tab | Vorteile | Nachteile | **Entscheidung** |
|---|---|---|---|
| **Suche** | Der Kernvorgang. Jeder braucht ihn. | Vergraben als ein Tab unter neun; keine Orientierung für neue Nutzer. | **Behalten & aufwerten.** Wird zum Herzstück, sofort erreichbar; ein neues **Start** bietet Orientierung darum herum. |
| **Ingest** | Nötig, um Daten hereinzuholen. | „Ingest“ ist Ingenieursjargon; einschüchternd; vermischte Scheduler und manuellen Abruf. | **Behalten, umbenennen → „Sammeln“.** Mit der einfachen manuellen Aktion beginnen; der Scheduler ist die „Automatische Erfassung“, gerahmt als einmal einstellen und vergessen. |
| **Quellen** | Hier lebt die Glaubwürdigkeit; Herkunft beginnt mit dem *Woher*. | Dichte Tabellen; fühlte sich wie Verwaltung an, nicht wie Journalismus. | **Behalten, neu rahmen als „Quellen“ (die Themenliste Ihrer Redaktion).** Umgestaltet, damit es sich wie eine Bibliothek liest, nicht wie eine Datenbankkonsole. |
| **Datenbank** | Ehrliche Live-Zählungen; Sicherung/Wiederherstellung. | „Datenbank“ sagt Amara nichts; sie hat eine *Bibliothek/ein Archiv*, keine DB. | **Behalten, umbenennen → „Bibliothek“.** Dieselben echten Zählungen und dieselbe weltweite Abdeckung, gerahmt als „was Sie gesammelt haben“. |
| **Märkte** | Stark für „Folge dem Geld“-Recherchen. | Für die meisten Geschichten irrelevant; schwer, nischig; Ballast für Amara. | **Behalten, als Erweitert markieren, ausblendbar.** Abseits des kritischen Pfads; ein Schalter entfernt ihn für Nutzer, die keine Finanzrecherche machen. |
| **Einblicke** | Das visuelle Glanzstück — Trends, Assoziationen, Karte. Das „Wow“. | War ein unauffälliger mittlerer Tab; unter Wert verkauft. | **Behalten & hervorheben.** Das ist eine Hauptfunktion; sie erhält Prominenz und Feinschliff. |
| **Wikipedia** | Passt hervorragend: „die Welt, wie sie wirklich ist“, Offline-Wissen, Erkennung von Edit-Wars. | Zwei verschiedene Dinge (Live-Verfolgung vs. schwere Offline-Dumps) verwirrend auf Tabs verteilt. | **Behalten.** Die Verfolgung bleibt hier; schwere Dumps bleiben in den Einstellungen, klar quer verlinkt (bereits in früherer Arbeit erledigt). |
| **Verwahrungskette** | Das Vertrauens-Alleinstellungsmerkmal. Es lässt Elliot dem Ergebnis vertrauen und Amara professionell wirken. | In Juristendeutsch benannt; fühlte sich an wie ein Tresor, den kaum jemand öffnet. | **Behalten, umbenennen → „Beweise & Verwahrung“, hervorheben.** Teil des „Was ist das?!“-Moments. |
| **Einstellungen** | Nötig. | War eine Rumpelkammer (Präferenzen + Schlüsselwortfilter + Dumps + Sicherung). | **Behalten, umstrukturieren** in Abschnitte (Erscheinungsbild · Allgemein · Wikipedia · Daten & Sicherung · Sicherheit). *(0.07: Die eigenständige Anpassen-Schublade wurde als Abschnitt **Erscheinungsbild** eingegliedert — ein Zuhause für das Erscheinungsbild, weniger schwebende Bedienelemente.)* |

#### Neu hinzugefügte Oberflächen

- **Start (Dashboard).** *Begründung:* Amara braucht Orientierung, kein leeres Suchfeld.
  Status auf einen Blick (Korpusgröße, Quellen, Scheduler, letzte Aktivität), große Schnell-
  aktionen („Suche“, „Jetzt sammeln“, „Ein Dokument prüfen“) und ein leerer Zustand, der
  etwas beibringt. Das ist der größte einzelne Gewinn an Benutzbarkeit für die primäre Persona.
- **Hilfe / Dokumentationsleser.** Die Nutzerin hat ausdrücklich direkten Zugriff auf das ausführliche
  Handbuch verlangt. Eine erstklassige Oberfläche **Hilfe** stellt das Benutzerhandbuch (und weitere Dokumente)
  *innerhalb* der App dar — durchsuchbar, offline, ohne das Werkzeug zu verlassen. Auch über
  die obere Leiste (`?`) und die Befehlspalette erreichbar.

#### Resultierende Informationsarchitektur

Die flache Leiste mit 9 Tabs wird zu einer **gruppierten Seitenleiste** (auf Icons einklappbar), geordnet
danach, wie die Arbeit tatsächlich abläuft:

- **Untersuchen** — Start · Suche · Einblicke · Zeitkarte · Wikipedia · *Märkte (erweitert)*
- **Sammeln** — Sammeln · Quellen · Bibliothek
- **Vertrauen** — Beweise & Verwahrung
- **System** — Einstellungen · Hilfe

Die Gruppierung macht aus „neun gleichrangigen Fremden“ „vier Absichten“ — so denkt Amara
(„Ich will etwas *finden*“ / „Ich will *sammeln*“ / „Ich will *beweisen*“).

---

### 4. Das „Wow“ — was eine Journalistin aufhorchen lässt

- **Ein kohärentes visuelles System.** Standardmäßig ein tiefdunkles „Tinten“-Design mit einer selbstbewussten
  einzelnen Akzentfarbe, großzügigem Abstandsrhythmus, echter typografischer Hierarchie, Monospace für
  Daten/Hashes, sanfter Tiefe und zurückhaltender Bewegung. Es wirkt wie ein *Instrument*, nicht wie eine
  *Dashboard-Vorlage*.
- **Befehlspalette (Strg/⌘-K).** Tippen, um überallhin zu springen, jede Aktion auszuführen oder jedes
  Dokument zu öffnen. Macht für Daniel; eine „Was kann ich hier überhaupt tun?“-Karte für Amara.
- **Steuerung des Erscheinungsbilds** (Einstellungen → Erscheinungsbild; bis 0.06 eine Live-Schublade, in 0.07 in die
  Einstellungen eingegliedert). Design-Vorlagen (Ink, Slate, Midnight, Paper, Sepia,
  Terminal, High-contrast), Akzentfarbfelder, Dichte, Schriftgröße, Einklappen der Seitenleiste
  und **Sichtbarkeit der Module** — alles sofort, alles lokal, alles dauerhaft.
- **Ein Start, der orientiert**, eine Einführung, die anleitet, und leere Zustände, die führen.
- **Vertrauen, sichtbar gemacht.** Verwahrung/Verifikation und die Rahmung „gemessen, nicht geschätzt“
  sind Teil der Ästhetik, kein Kleingedrucktes.
- **Vollständige Offline-Integrität.** Keine Netzwerkaufrufe für die Bedienoberfläche — was selbst eine
  Funktion ist, die man einer sicherheitsbewussten Kollegin *zeigen* kann.

---

### 5. Anpassungsmodell

Das Erscheinungsbild wird in `localStorage` (`oo.ui`) gespeichert — nie irgendwohin gesendet —, daher
greift es sofort und übersteht den Offline-Betrieb. Funktionale Präferenzen (Standard-Ergebnislimit, Basis-
design) werden weiterhin serverseitig über `/api/settings` gespeichert. Anpassbar: Design-
Vorlage, Akzentfarbe, Dichte, Schriftskalierung, Zustand der Seitenleiste und die Menge der sichtbaren
Module. Dank sinnvoller Standards rührt eine Erstnutzerin nichts davon an.

---

### 6. Was ich bewusst **nicht** getan habe (Ehrlichkeit)

- **Kein Framework / kein Build-Schritt / kein CDN.** Das würde das offline-fähige, prüfbare, souveräne
  Ethos für kosmetischen Gewinn brechen. Vanilla, eine Datei, Systemschriften, handgezeichnetes SVG.
- **Keine fabrizierten Funktionen.** Jede Schaltfläche führt zu einem echten, funktionierenden Endpunkt. Fähigkeiten,
  die von einem optionalen Extra abhängen, sagen das weiterhin.
- **Keine stillen Backend-Änderungen** über einen additiven, schreibgeschützten Dokumentations-Endpunkt mit Allowlist
  (`/api/docs`) für den Hilfe-Leser hinaus.
- **Die Freitext-Spracheingaben blieben Freitext** (bereits in OPEN_QUESTIONS vermerkt);
  die Neugestaltung erfindet keine Dropdowns, die das Backend nicht stützen kann.

---

### 7. Status

`0.05` ist nun der **Standard-Branch** des Repositorys (Hauptlinie); frühere Linien (0.04
und älter) bleiben in der Git-Historie. Die funktionale Gleichwertigkeit bleibt erhalten (dieselben Element-
IDs, dieselbe Verdrahtung); die Änderung ist alles *um* diese Engine herum. Standardmäßig werden
**zwei** Oberflächen ausgeliefert — Console (`/`) und Desk (`/desk`) —, verglichen in
[`DESIGN.md`](DESIGN.md).


---

## Zwei Oberflächen, ein Argument — „Console“ vs. „Desk“

> Sie haben um ein *widersprechendes* Argument gebeten: keine Verteidigung der Neugestaltung 0.05, sondern
> eine ehrliche Begründung dafür, dass sie die **falsche** Oberfläche für diese App sein könnte — und eine
> konkrete Alternative, an der man sie messen kann. Dieses Dokument ist dieses Argument. Die beiden
> Oberflächen werden nebeneinander ausgeliefert, damit Sie beide mit denselben Daten betreiben und selbst
> urteilen können.

---

### 0. Zuerst: zurück zu dem, was diese App tatsächlich ist

Bevor über Bedienelemente gestritten wird, die Unverhandelbaren (aus `ETHICS.md`,
`DESIGN.md`, der Münchner Erklärung):

- **Ein Nutzer, ein Rechner, nur Loopback, offline-first.** Keine Konten, keine Cloud,
  keine Telemetrie. Oft in einer Qubes-AppVM betrieben, mit *abgekoppeltem* Netzwerk-Qube.
- **Eine wahrheitssuchende Akteurin, die kein Freund von Computern ist.** Eine Ermittlerin /
  Journalistin, deren Aufgabe es ist, *die Wirklichkeit zu verstehen und glaubwürdig zu vermitteln*.
- **Das Produkt ist Vertrauen.** Herkunft, Quellenprüfung, „gemessen, nicht
  geschätzt“, Manipulationsnachweis. Die Münchner Erklärung (Wahrheit, Quellen prüfen, Quellen
  schützen, Propaganda widerstehen) ist das Rückgrat.
- **Souveränität als Ästhetik.** Das Werkzeug soll sich *anfühlen*, als gehöre es der Nutzerin,
  nicht einer Plattform.

Jede Oberfläche ist an *diesen* Punkten zu messen, nicht daran, ob sie „wie ein
SaaS-Produkt von 2025 aussieht“.

---

### 1. Die Anklageschrift gegen „Console“ (die Neugestaltung 0.05)

Die stärkste Fassung des Arguments, dass 0.05 die falsche Richtung ist:

1. **Sie kleidet ein souveränes Werkzeug in die Kleider des Überwachungskapitalismus.** Dauerhafte
   linke Seitenleiste, Status-Pillen, Befehlspalette, eine Anpassungsschublade mit acht
   Designs — das ist die visuelle Grammatik von Slack, Linear, Notion: *Cloud-SaaS*. Für
   eine Nutzerin, die Big Tech misstraut und an sensiblen Geschichten arbeitet, kann diese Grammatik
   sich lesen wie „noch eine App, die mich beobachtet“, und untergräbt damit das, worauf es hier
   am meisten ankommt: Vertrauen. Das Aussehen kämpft gegen die Werte.

2. **Sie optimiert für die Vorführung, nicht für die Arbeit.** Der Auftrag enthielt „eine
   Journalistin soll sagen *kann ich das haben?*“ — eine Fünf-Sekunden-Reaktion über die Schulter.
   Wer dafür gestaltet, wird zu Dashboard-Glanz gezogen (Verläufe, animierte Zähler,
   Design-Zoo) und weg von der stillen, leseintensiven, dokumentzentrierten Realität der
   Recherche. Die besten Werkzeuge für konzentrierte Arbeit (ein Texteditor, ein Notizbuch) sind
   *schlicht*. Console mag beeindruckend und oberflächlich sein.

3. **Anpassung ist eine als Geschenk getarnte Steuer.** Acht Designs, Akzentfarbfelder,
   Dichte, Schriftskalierung, Ausblenden einzelner Module. Für *Amara* (kein Freund von Computern) ist jedes
   davon eine Entscheidung, die sie nicht wollte, und eine Möglichkeit, ihr Werkzeug falsch einzustellen.
   „Weitgehend konfigurierbar“ diente dem Wortlaut des Auftrags und der Vorstellung des *Designers* von
   Großzügigkeit — aber ein wirklich einfaches Werkzeug ist **meinungsstark**: Es trifft die richtige
   Entscheidung, damit die Nutzerin es nicht muss. Auswahl ist kognitive Last.

4. **Die Informationsarchitektur gehört immer noch der Software, nicht der Nutzerin.** Console
   hat die Tabs umbenannt und neu gruppiert, aber das Menü ist weiterhin eine Liste von *Modulen*
   (Suche, Quellen, Einblicke, Märkte, Verwahrung…). Amara denkt nicht in Modulen;
   sie denkt in einem **Fall**: „Ich verfolge diese Geschichte — sammeln, lesen, verknüpfen, beweisen,
   veröffentlichen.“ Sowohl 0.04 als auch 0.05 zwingen die Nutzerin, ihren *Job* in die
   *Funktionen* der App zu übersetzen. Eine dauerhafte Navigation mit neun Zielen ist eine Karte der Codebasis.

5. **Bedienelemente konkurrieren mit dem Inhalt.** Eine feste Seitenleiste + obere Leiste verbrauchen dauerhaft
   ~250px und einen horizontalen Streifen für *Navigation, die die Nutzerin zwei Sekunden pro
   Sitzung nutzt*. Das, was sie tatsächlich tut — Artikel lesen, Ergebnisse überfliegen, Diffs
   vergleichen —, bekommt die Reste. Recherche ist Lesen; Console bedient das Lesen unzureichend.

6. **Das „Wow“ ist geliehen, nicht verdient.** Eine Palette und Designs sind in modernen Apps
   *Grundausstattung* — beeindruckend gerade weil sie vertraut sind. Die wirklich
   unterscheidenden „So etwas habe ich noch nie gesehen“-Funktionen hier sind die *Substanz*:
   Offline-Erkennung von Wikipedia-Edit-Wars, manipulationssichere Verwahrung, „jede Zahl ist ein
   echtes COUNT(\*)“. Console dekoriert; sie inszeniert nicht, was tatsächlich einzigartig ist.

Das ist eine ernste Anklage. Sie verdient eine echte Alternative, keine Gegenrede.

---

### 2. Zur Verteidigung von Console (damit das Argument fair ist)

- Eine dauerhafte Navigation ist **auffindbar**: Nichts ist versteckt, was für eine
  Anfängerin wichtig ist, die noch nicht weiß, was das Werkzeug kann. Nabe-Speiche-Modelle verstecken
  Möglichkeiten hinter einem Klick und einer Vermutung.
- Anpassung ist **abwählbar**: Die Standards sind vernünftig; eine Nutzerin, die die Schublade ignoriert,
  verliert nichts. Und Designs helfen tatsächlich gegen die Augenbelastung bei der Arbeit spät in der Nacht
  sowie der Barrierefreiheit (hoher Kontrast, Textgröße) *realer* Nutzerinnen und Nutzer.
- Die „SaaS-Grammatik“ ist auch einfach **aktuelle Usability-Konvention** — die Leute wissen, wie
  man sie vom ersten Tag an bedient. Neuheit um ihrer selbst willen hat ihre eigene Steuer.
- Sie ist weiterhin **zu 100 % offline und ohne Abhängigkeiten**. Die Grammatik ist geliehen; die
  Substanz (kein Netzwerk, keine Telemetrie) nicht.

Beide Positionen sind legitim. Der Weg, das aufzulösen, ist nicht noch mehr Streit — sondern
**die Antithese zu bauen und beide zu nutzen**.

---

### 3. Die Antithese: „Desk“

Wenn Console eine **breite Bedienkonsole** ist (alles stets einen Klick entfernt,
maximal flexibel, Grammatik moderner Apps), dann ist **Desk** die Gegenthese:

> **Der Schreibtisch einer Ermittlerin: ruhig, meinungsstark, inhaltszentriert und aufgabenorientiert.
> Fast keine Bedienelemente. Eine Aufgabe nach der anderen. Die Oberfläche tritt beiseite für das Lesen
> und Denken.**

Konkrete Festlegungen, bei denen Desk Console bewusst *widerspricht*:

| Dimension | Console (These) | Desk (Antithese) |
|---|---|---|
| Navigation | Dauerhafte linke Seitenleiste (immer sichtbar) | **Keine dauerhafte Navigation.** Navigation gibt es *auf Abruf* — ein ruhiger Startbildschirm, ein „Gehe zu…“-Overlay und ⌘K. Bedienelemente erscheinen nur, wenn sie gerufen werden. |
| Einstiegspunkt | Ein Status-Dashboard | **Ein aufgabenorientierter Startbildschirm:** „Woran arbeiten Sie?“ → Sammeln · Finden & lesen · Verknüpfen · Prüfen & teilen. Gerahmt von der Aufgabe der Nutzerin, nicht von den Modulen der App. |
| Anpassung | 8 Designs, Akzentfarbe, Dichte, Schrift, Modulschalter | **Nur zwei Designs** (Paper / Ink), keine Regler. Meinungsstark. Das Werkzeug entscheidet, damit Sie es nicht müssen. |
| Ästhetik | Moderne App-Konsole (serifenlos, Pillen, Verläufe) | **Redaktionell / Druck:** Überschriften mit Serifen, Papierwärme, großzügige Ränder, angenehme Zeilenlänge. Fühlt sich an wie eine Redaktion, nicht wie ein SaaS. |
| Was den Platz bekommt | Navigation + Status, dann Inhalt | **Inhalt.** Eine einzige zentrierte Lesespalte; Tabellen und der Artikelleser bekommen den Raum. |
| Vertrauenssignal | Eine Status-Pille | Eine dauerhafte, leise Zeile **„Lokal · Offline · Nichts verlässt diesen Rechner“** — Souveränität ausgesprochen, nicht angedeutet. |
| Reaktion bei der Vorführung | „Elegant!“ | „…oh, das ist *ruhig*. Und es gehört ganz mir.“ Eine langsamere, tiefere Art von Wow. |

Was Desk **behält** (weil es der Sinn der App ist, keine Bedienoberfläche): jede Funktion
und jeden funktionierenden Endpunkt. Desk und Console teilen sich genau dieselbe Engine und
dieselben Inhaltsbereiche — sie unterscheiden sich *nur* in Hülle, Navigationsmodell, IA-Rahmung
und Ästhetik. Das ist Absicht: So bleibt das Experiment kontrolliert, und was Sie vergleichen,
ist **die Philosophie**, nicht welche der beiden ich zufällig sorgfältiger verdrahtet habe.

---

### 4. Wie man sie beurteilt (Bewertungsraster)

Bewerten Sie jede an den Werten — nicht nach Ihrem Bauchgefühl, „welche schöner aussieht“:

1. **Vertrauen** — welche *fühlt* sich an, als gehöre sie Ihnen und würde Sie nicht verraten?
2. **Ruhe vs. Leistungsfähigkeit** — welche lässt Sie denken? Bei welcher sind die Möglichkeiten auffindbar?
3. **Anfängerpfad** — setzen Sie *Amara* unvorbereitet davor: Welche bringt sie schneller und
   mit weniger Angst zu einem Ergebnis?
4. **Power-Pfad** — *Daniel* an der Tastatur: Welche geht ihm aus dem Weg?
5. **Lesen** — öffnen Sie in jeder einen langen Artikel / einen Wikipedia-Diff. Welche ist der bessere
   Ort zum *Lesen*?
6. **Der 5-Sekunden-Test** — zeigen Sie jede einer Kollegin. Welche provoziert „kann ich das haben?“ —
   und ist das die Reaktion, auf die Sie tatsächlich optimieren wollen?
7. **Passung zum Ethos** — welcher würden Sie zutrauen, mit abgekoppeltem Netzwerk in
   einem Qubes-Tresor zu laufen?

---

### 5. Erwartete Vor- und Nachteile (meine ehrliche Wette, zu testen)

**Console** — *Vorteile:* auffindbar, konventionell, flexibel, Regler für Barrierefreiheit, Vorführ-
glanz. *Nachteile:* viele Bedienelemente, Entscheidungslast, generisches SaaS-Gefühl, das Vertrauen untergraben kann,
IA weiterhin modulzentriert.

**Desk** — *Vorteile:* ruhig, Inhalt/Lesen zuerst, meinungsstark (keine Konfigurationssteuer),
aufgabenorientierter Einstieg, eine Ästhetik, die Souveränität und Vertrauen *verstärkt*. *Nachteile:*
Möglichkeiten sind einen Ruf entfernt (ein Klick/Tastendruck), weniger Regler für Barrierefreiheit, weniger
unmittelbar „beeindruckend“, Neuheit hat geringe Lernkosten.

---

### 6. Meine Empfehlung (Synthese — vorläufig, bis zu Ihrem Test)

Ich erwarte, dass die richtige Antwort **weder reine Console noch reiner Desk** ist, sondern eine Synthese,
die sich auf Desks *Passung zu den Werten* und Consoles *Auffindbarkeit* stützt:

- **Desks aufgabenorientierten Startbildschirm und redaktionelle Ruhe** als Standardstimmung übernehmen. Die Aufgaben-
  rahmung („sammeln / lesen / verknüpfen / prüfen“) ist die größte einzelne Korrektur an der Kritik
  „die IA ist die Codebasis“.
- **Desks Zurückhaltung bei der Anpassung übernehmen:** zwei ausgezeichnete Designs ausliefern
  (Paper/Ink) + eine Textgrößensteuerung für die Barrierefreiheit, und den Wildwuchs aus Akzentfarbe /
  Dichte / Modulausblendung **streichen**. Meinungsstark schlägt konfigurierbar hier.
- **Eine *leise, einklappbare* Navigation von Console behalten** für die Auffindbarkeit — aber
  standardmäßig eingeklappt, sodass der Inhalt führt und die Navigation da ist, wenn sie gewünscht wird.
- **⌘K behalten** (dient sowohl Anfängern als auch Power-Nutzern und ist wirklich nützlich).
- **Die Substanz inszenieren, nicht die Bedienelemente:** Verwahrung, Offline-Wikipedia und
  „echte Zählungen“ zu den visuellen Helden machen — das ist das verdiente Wow.
- **Die Vertrauenszeile überall voranstellen** („nichts verlässt diesen Rechner“). Sie ist
  die Marke.

Aber das ist eine Hypothese. Betreiben Sie beide, bewerten Sie sie nach §4 und sagen Sie mir, wo die Realität
von meiner Wette abweicht — dann arbeite ich das Urteil in eine einzige 0.06 ein.

> **ENDGÜLTIGES URTEIL (Maintainer, 2026-06-10, nach Live-Nutzung):** Die Dialektik ist
> aufgelöst — **Desk wird vollständig eingestellt. Eine Oberfläche: die Console** (`/`).
> Zwei Icons verwirrten mehr, als sie halfen; Desks reduzierter Werkzeugsatz ließ
> ausgelieferte Funktionen (Zeitkarte, Agenda) verloren wirken; und die Console
> passt sich bereits geschmeidig an die Fenstergröße an (die Seitenleiste zieht sich zu einer Icon-Leiste zurück). Die
> Datei `desk.html` wurde entfernt (sie lebt in der Git-Historie); `/desk` leitet nun
> auf `/` um. Desks beste Ideen — der aufgabenorientierte Startbildschirm, ⌘K, redaktionelle
> Ruhe — sollen mit der Zeit in die Console eingearbeitet werden, gemäß §6 oben.

---

### 7. Beide gleichzeitig betreiben

Beide Oberflächen werden vom selben lokalen Backend mit denselben Daten ausgeliefert:

- **Console** → `http://127.0.0.1:8000/`  (der Standard)
- **Desk** → `http://127.0.0.1:8000/desk`

Der Installer legt **zwei Desktop-Icons** an — *Open Omniscience* (Console) und
*Open Omniscience — Desk* —, sodass Sie jede einzeln starten oder beide Fenster zusammen öffnen
und sie Tab für Tab mit identischen Daten vergleichen können. Wählen Sie eine Siegerin (oder verlangen Sie die
Synthese), und wir kehren in 0.06 zu einer zurück.


---

## Strategie zur Inhaltsanalyse — Links, Gleichförmigkeit und die Originalquelle

> Konkrete, gestufte Strategien für die Vision in [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md):
> die **Links** von Artikeln nutzen, um zusammenzutragen, was über dieselbe Sache spricht, die
> **Gleichförmigkeit** der Medien sichtbar machen und Informationen bis zu ihrer **Originalquelle** zurückverfolgen — und dabei
> die **Nutzerin am Steuer** lassen, die Analyse **transparent und lokal** halten und das Werkzeug niemals
> zum Schiedsrichter über die Wahrheit werden lassen (Münchner Erklärung). Durchgehend quelloffen und
> offline.

---

### 0. Wo wir stehen (ehrlicher Stand)

Die Erkennung von Artikel-Links ist **als Gerüst vorhanden, aber nicht verdrahtet**:

- ✅ **`src/services/link_analyzer/extractor.py`** (`LinkExtractor`) — extrahiert Links
  aus HTML, normalisiert URLs, erfasst Ankertext + Position, klassifiziert den Link-*Typ*
  (intern/extern/Bild/…) und erzeugt Link-Statistiken. ~500 Zeilen, als Einheit testbar.
- ✅ **DB-Schema** — `ArticleLink` (url, normalized_url, link_text, position,
  link_type, **classification** = source/reference/ad/social/navigation,
  `external_source_id`, `source_article_id`, is_working, http_status…),
  `ExternalSource` und `LinkClassificationRule`. Die Beziehungen sind vorhanden
  (`Article.links`, `ExternalSource.links`).
- ✅ **Bei der Erfassung aufgerufen** *(erledigt — P0)* — `src/ingest/pipeline.py:_maybe_index_links`
  befüllt `article_links` mit ausgehenden **externen** Links (nach bestem Bemühen, im Fehlerfall offen;
  interne/Bild-/Werbe-/Social-/Tracker-Links ausgeschlossen gemäß `ROADMAP.md`; dedupliziert + begrenzt).
- ✅ **API** *(erledigt — P1)* — `src/api/link_analysis.py` (`/api/links`): `stats`,
  `top-cited` (nach url|domain, mit Zeitfenster), `articles-by-link` (nach url|domain). Nur Zählungen;
  nichts wird bewertet oder beurteilt.
- ❌ **Noch keine UI** — keine Einblicke-Ansicht über den Link-Graphen (P2, siehe unten).

P0/P1 sind also verdrahtet; die verbleibende Arbeit sind die UI und die tieferen Analysen (P3/P4).

---

### 1. Die Kernidee: Links sind ein Zitationsgraph

Jeder Artikel wird als Knoten behandelt und jeder ausgehende Link als gerichtete Kante zu einer URL (und
zu ihrer Domain). Dieser Graph beantwortet genau das, was Sie gefragt haben:

- **„Alle Artikel zusammentragen, die über denselben Link sprechen.“** = Artikel nach der
  externen URL gruppieren, die sie zitieren → der **Eingangsgrad** der URL ist „wie viele meiner Artikel hierher
  verweisen“. Hoher Eingangsgrad = ein **Knotenpunkt**: oft ein Primärdokument, eine Agenturmeldung oder eine
  viel diskutierte Referenz.
- **„Trends über interne Links entdecken.“** = den Eingangsgrad über die Zeit beobachten; eine URL oder
  Domain, deren Zitationen sprunghaft steigen, ist ein *Trend*, der darin verankert ist, was Reporter tatsächlich zitieren,
  nicht bloß in Schlüsselworthäufigkeit.
- **„Die ursprüngliche / Urquelle zurückverfolgen.“** = innerhalb eines Clusters von Artikeln zu einer
  Geschichte ist das Original der Knoten, auf den die anderen **verlinken**, und/oder der früheste und/oder der,
  der ein **Primärdokument** zitiert (Gericht/Behörde/Datensatz). Links + Zeitstempel + Agenturangabe
  triangulieren es.

Das ist *Kozitationsanalyse* — günstig, transparent und erklärbar. Keine Blackbox.

---

### 2. Gestufte Strategien (jede für sich auslieferbar)

#### P0 — Den Extraktor in die Erfassung einbinden (den Graphen entstehen lassen)
- `LinkExtractor` während der Erfassung auf dem abgerufenen HTML aufrufen; ausgehende
  **externe** Links in `article_links` speichern (interne Navigation, Werbung und — gemäß
  `ROADMAP.md` — Bild-/Binär-Links überspringen). normalized_url + Ankertext + Typ speichern.
- Die Domain jedes externen Links wo möglich einer bekannten `Source`/`ExternalSource` zuordnen
  (damit sich „wer zitiert wen“ auf Medien und **Eigentümer** verdichten lässt).
- Günstig, deterministisch, offline. Nichts wird abgerufen über das hinaus, was die Erfassung ohnehin abgerufen hat.

#### P1 — Aggregation + API (die Frage der Nutzerin beantworten)
Schreibgeschützte Endpunkte über dem Graphen:
- **`top-cited`** — die meistzitierten URLs/Domains in einem Zeitfenster (das Trendsignal).
- **`articles-by-link`** — zu einer URL/Domain jeden Artikel im Korpus, der sie zitiert
  („alle Artikel zusammentragen, die über denselben Link sprechen“).
- **`link-graph`** — Knoten/Kanten für ein Thema oder Zeitfenster, zur Visualisierung.
- **`co-citation`** — Artikel, die *dieselben* externen Quellen zitieren (Kandidaten für Cluster zur
  „selben Geschichte“), mit Überschneidungszählungen.

#### P2 — UI: eine Ansicht „Links & Quellen“ in Einblicke
- Eine Rangliste der **meistzitierten Links/Domains** (Klick → alle zitierenden Artikel).
- Ein kleiner, zoombarer **Zitationsgraph** (den SVG-Ansatz wiederverwenden, der bereits für die
  Karte in Einblicke genutzt wird — keine neue Abhängigkeit).
- Zeigt immer **Stichprobengrößen** („zitiert von 14 Ihrer Artikel“) — gemessen, nicht
  geraten. Die Nutzerin klickt, erkundet, entscheidet.

#### P3 — Herkunftslinie der Originalquelle
Für ein Cluster von Artikeln zu einer Geschichte eine **Herkunftslinie** darstellen, gereiht nach Signalen
(jedes angezeigt, keines entscheidend):
- Eingangsgrad (auf wen die anderen verlinken),
- frühester Veröffentlichungszeitstempel,
- Agenturangabe (AFP/Reuters/AP — wir taggen bereits `wire-agency`),
- Vorhandensein eines Links auf ein **Primärdokument** (Behörde/Gericht/Datensatz/Preprint).
Ausgabe: „Primärdokument → erster Bericht → Echos“, als Kette, die die Nutzerin liest.

#### P4 — Gleichförmigkeit & Echo (verbunden mit Medienkonzentration)
- **Erkennung von Beinahe-Duplikaten** (günstiges MinHash/SimHash), um syndizierten/kopierten Text
  über Medien hinweg zu markieren — baut auf `src/ingestor/duplicate_detector.py` auf.
- **Echo-Wert**: ein Cluster, in dem viele Medien **eine** Quelle zitieren (oder einander in einer
  engen Schleife) und wenig eigene Verlinkung hinzufügen = hohes Echo. Vielfältige Zitationen von Primärquellen
  = unabhängige Berichterstattung.
- **Konzentrations-Overlay**: das Echo nach **Eigentümerschaft** gewichten — wenn das echoende Cluster einem
  Eigentümer/Block zuzuordnen ist (der Fall „~7 Milliardäre besitzen ~90 %“), dies sichtbar machen. Erfordert den
  Eigentümergraphen (Wikidata P127/P749 + manuell), gemäß `ROADMAP.md`.

---

### 3. Die Nutzerin am Steuer lassen (unverhandelbar)

- **Sichtbar machen, nie unterdrücken.** Echo-/Herkunftswerte werden *angezeigt und sind sortierbar*; das Werkzeug
  versteckt oder stuft eine Quelle niemals automatisch herab. Jede Abwertung ist eine ausdrückliche, umkehrbare
  Einstellung der Nutzerin, **standardmäßig aus**.
- **Keine Wahrheitsetiketten.** „Am frühesten gesehen“ / „am meisten zitiert“ ≠ „wahr“. Wir zeigen Struktur
  (wer es zuerst gesagt hat, wer wen zitiert, wem was gehört) und hören dort auf.
- **Alles erklärbar & lokal.** Jede Zahl lässt sich auf Zeilen zurückführen, die die Nutzerin einsehen kann;
  keine externen Aufrufe, keine ML-Blackbox (Hashing + Zählen + Graphgrad).
- **Quelloffen & prüfbar.** Reine Funktionen, als Einheit testbar, Klassifikationsregeln als Daten
  (`LinkClassificationRule`), die die Nutzerin bearbeiten kann.

---

### 4. Risiken & ehrliche Grenzen

- Die Link-Extraktion ist nur so gut wie das abgerufene HTML (Paywalls/JS schränken sie ein).
- Anker-/Zitierkonventionen variieren; „laut X“ ohne Link wird übersehen (ein
  späterer NLP-Durchlauf könnte helfen, beginnt aber einfach).
- Eigentümerdaten sind lückenhaft und veraltet — sie müssen zuordenbar sein, nicht geraten.
- Beinahe-Duplikate im Korpusmaßstab erfordern Sorgfalt, damit es auf einem Rechner günstig bleibt (Hashing, gefensterter
  Vergleich), keine O(n²)-Volltextvergleiche.

### 5. Vorgeschlagener erster Commit

**P0** einbinden (`article_links` bei der Erfassung befüllen) hinter einer Einstellung, die **P1**-Endpunkte
**`articles-by-link`** und **`top-cited`** hinzufügen sowie eine minimale Liste in Einblicke. Das
allein liefert „alle Artikel zusammentragen, die denselben Link zitieren“ und einen zitationsbasierten
Trend — den kleinsten Ausschnitt echten Werts, ganz im Einklang mit dem Ethos.
