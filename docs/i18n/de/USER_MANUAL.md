<!-- de: AI-drafted translation of docs/USER_MANUAL.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 124 of 124 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# Open Omniscience — Benutzerhandbuch

*Eine quelloffene, ethische, lokal arbeitende Recherche-Plattform für investigativen
Journalismus.* Dieses Handbuch ist der freundliche Leitfaden von A bis Z: was die App ist, wie
Sie sie installieren und starten, und ein Rundgang durch **jeden Tab, jedes Bedienelement, jede Einstellung und jeden Arbeitsablauf**,
gefolgt von einer technischen Referenz (Speicherorte der Daten, Umgebungsvariablen, die vollständige
HTTP-API) und Hilfe bei der Fehlersuche.

> **In einem Satz:** Open Omniscience sammelt auf ethische Weise Nachrichten (dazu Wikipedia-Bearbeitungen
> und Marktpreise) in einer durchsuchbaren, von Duplikaten bereinigten SQLite-Datenbank mit
> Herkunftsnachweis auf *Ihrem* Rechner, lässt Sie diese auswerten (Suche, Trends, Karten,
> Framing, Zusammenfassungen durch ein lokales LLM) und kann **kryptografisch signierte,
> offline überprüfbare Belege** dafür erzeugen, was sie wann enthielt.

**Gestaltungsversprechen, die alles Folgende prägen:**

- **Lokal & privat.** Alles läuft auf `127.0.0.1` (nur Loopback). Keine
  Konten, keine Telemetrie, nichts verlässt Ihren Rechner — der einzige ausgehende Verkehr
  ist der ethische Scraper, der die Quellen abruft, auf die Sie ihn ansetzen (und, wenn Sie zustimmen,
  Wikipedia/OpenTimestamps/Ollama).
- **Nur ehrliche Zahlen.** Jede Zahl ist ein echtes `COUNT(*)`, eine echte Bytegröße auf der Festplatte
  oder ein echtes statistisches Aggregat mit Stichprobengröße und Einschränkung. Die App
  zeigt lieber einen Fehler an, als einen Wert zu erfinden. (Mehrere frühere „KI-Erkennungs“-Funktionen,
  die Bewertungen vortäuschten, wurden entfernt — siehe `docs/HISTORY.md`.)
- **Ethische Erfassung.** Ein einziger Abrufweg. `robots.txt` wird **im Zweifel restriktiv** beachtet
  (im Zweifel wird *nicht* abgerufen), jeder Host wird gedrosselt, und nichts wird
  gespeichert, solange nicht ein echter Artikeltext extrahiert wurde.

---

## Inhaltsverzeichnis

1. [Installation & erster Start](#1-installation--erster-start)
2. [Der 60-Sekunden-Rundgang](#2-der-60-sekunden-rundgang)
3. [Die Werkzeuge im Einzelnen](#3-die-werkzeuge-im-einzelnen)
   - [Start](#30-start) · [Aktivität & Task-Manager](#30a-aktivität--der-task-manager) ·
     [Feed](#30b-feed) ·
     [Erkunden: Suche](#31-suche) · [Erkunden: die Analyse](#31a-analyse--das-korpusfenster) · [Sammeln](#32-sammeln-unter-einstellungen--erweitert--erfassung) ·
     [Quellen](#33-quellen-unter-einstellungen--erweitert--quellen) · [Bibliothek](#34-bibliothek) · [Märkte](#35-märkte) ·
     [Indizes](#35a-indizes) · [Einblicke](#36-einblicke) ·
     [Weltkarte](#36a-weltkarte) · [Agenda](#36b-agenda) ·
     [Lebende Quellen](#36b-lebende-quellen) · [Klima](#36c-klima) · [Sternwarte](#36d-sternwarte) ·
     [Wikipedia](#37-wikipedia-unter-einstellungen--wikipedia) ·
     [Beweise & Verwahrung](#38-beweise--verwahrung) · [Einstellungen](#39-einstellungen) ·
     [Hilfe & Doku](#310-hilfe--doku)
4. [Häufige Arbeitsabläufe (Anleitungen)](#4-häufige-arbeitsabläufe-anleitungen)
5. [Technische Referenz](#5-technische-referenz)
   - [Wo Ihre Daten liegen](#51-wo-ihre-daten-liegen) ·
     [Umgebungsvariablen](#52-umgebungsvariablen) ·
     [Optionale Zusatzpakete](#53-optionale-erweiterungen) ·
     [Die HTTP-API](#54-die-http-api) ·
     [Arbeitsspeicher auf einem kleinen Rechner](#55a-speicher-auf-einem-kleinen-rechner--die-einzige-echte-obergrenze)
6. [Fehlerbehebung](#6-fehlerbehebung)
7. [Glossar](#7-glossar)

---

## 1. Installation & erster Start

Open Omniscience setzt **Python 3.13** auf Debian-basiertem Linux voraus (es ist für
eine **Qubes OS**-Debian-AppVM ausgelegt, läuft aber auf jedem modernen Linux). Es ist eine Einzelbenutzer-App,
die lokal arbeitet.

### Am einfachsten: der Einzeilen-Installer

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

Dies klont das Repository und führt `./install.sh` aus, das **reibungslos läuft — es fragt nichts**.
Es installiert den Standardumfang — **Core** (Scrapen, Speichern, Suchen, Exportieren) plus das
Zusatzpaket **Analysis** (Statistik, Schlagwort- und Entitätsauswertung, Marktkorrelation über
scipy/scikit-learn; optional spaCy für echte Erkennung benannter Entitäten) plus Komprimierung —,
legt dann einen **Open Omniscience**-Starter in Ihrem Anwendungsmenü und auf dem Desktop an und
**startet die App automatisch** in Ihrem Browser unter `http://127.0.0.1:8000`. (Setzen Sie
`OO_COMPONENTS`, um den Komponentenumfang zu ändern.) Zusammenfassen/Übersetzen auf dem Gerät braucht ein
lokales Modell — installieren Sie **Ollama** über **Einstellungen → KI** (geprüfter Installer in der App) oder
von ollama.com. Sie können `install.sh` jederzeit erneut ausführen.

> Prüfen Sie ein Skript immer, bevor Sie es an eine Shell weiterleiten. Die Datei
> [`bootstrap.sh`](../scripts/bootstrap.sh) ist winzig; Sie können das Repository auch selbst klonen
> und `./install.sh` ausführen.

**Unter Qubes:** Führen Sie `sudo ./install.sh --template` in der TemplateVM aus, starten Sie die
AppVM neu und führen Sie dann `./install.sh` in der AppVM aus.

### Entwickler- / manuelle Installation

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"     # core + analysis + test tooling
pytest -q                            # full suite should be green
open-omniscience                     # serves http://127.0.0.1:8000
```

Beim ersten Start **legt die App automatisch einen weltweiten Katalog an (~3.400 eindeutige Domains
aus Nachrichten, Märkten, dem Satz zum politischen Spektrum und amtlichen Rechts-/IP-Portalen)**, damit Sie
sofort etwas zum Erfassen haben, initialisiert die SQLite-Datenbank und den FTS-Index
und startet (falls aktiviert) den Hintergrund-Zeitplaner.

### Die Erststart-Seite (Sprache → Bedingungen → Passphrase)

Bei einer **Neuinstallation** sehen Sie als Allererstes die eigenständige Offline-Einrichtungsseite
unter `/unlock`, mit drei Schritten, **bevor sich die App öffnet**:

1. **Wählen Sie Ihre Sprache** — eine der 12 Oberflächensprachen; die ganze Seite
   wechselt sofort, und Ihre Wahl wird in die App übernommen.
2. **Lesen und akzeptieren Sie die rechtlichen Dokumente** (in Ihrer Sprache angezeigt; maßgeblich ist die
   französische Fassung). Mit **Akzeptieren und fortfahren (Accept and continue)** geht es weiter, mit **Ablehnen (Decline)** nicht — das Ablehnen
   **deinstalliert die App** (ein Unterbereich mit getippter Bestätigung stellt sicher, dass ein versehentlicher
   Klick niemals etwas löscht).
3. **Legen Sie Ihre Korpus-Passphrase fest.** Neue Datenbanken werden **standardmäßig mit SQLCipher auf der Festplatte
   verschlüsselt**, daher wählen Sie hier **DIE Passphrase** (zur Bestätigung zweimal eingegeben). Sie ist
   ein einziges, dauerhaftes Geheimnis, wie eine Benutzerkennung, **ohne Wiederherstellung und ohne alternative
   Entschlüsselung** — eine verlorene Passphrase kostet Zeit für das erneute Sammeln, weil der Korpus
   aus dem Web neu aufgebaut wird. Die vollständige Begründung und das ehrliche Bedrohungsmodell finden Sie unter
   [Einstellungen → Erweitert → Sicherheit](#39-einstellungen).

Bei **späteren Starts** ist der Speicher bereits angelegt, Sie gelangen also direkt zu einer einzigen
**Entsperr**-Abfrage für dieselbe Passphrase. Headless-/skriptgesteuerte Läufe übergeben sie mit
`OO_DB_PASSPHRASE`; unverschlüsselter Betrieb bleibt eine ausdrückliche Entscheidung (`OO_DB_PLAINTEXT=1`).

### Die geführte Einrichtung & der Startbildschirm

Sobald Sie drin sind, kann Sie eine einmalige **geführte Einrichtung** in der App (ein Dialog in Schritten) durch
Ihre ersten Entscheidungen führen: Sie beginnt mit einem Schritt **Sprache** und endet mit einem Schritt **Fertig**,
der erklärt, dass die App **offline startet**, und eine Schaltfläche *„Online gehen und mit dem Sammeln
beginnen“* anbietet. Online gehen führt immer über das Netzwerk-Zustimmungsfenster (siehe unten) —
die Anleitung lädt Sie nur ein; sie verbindet sich nie von selbst. Sie können sie jederzeit erneut ausführen,
über **Einstellungen → Allgemein → „Erststart-Anleitung erneut ausführen“.**

Danach öffnet sich die App auf **Start**, wo Ihr **Briefing** an erster Stelle steht — ein Feed
ehrlicher **Spuren** (siehe [3.0 Start](#30-start)) — über einem kompakten Streifen **Auf einen Blick** mit
Live-Zählwerten. Sie müssen nichts von Hand anlegen: Der kuratierte Katalog **wird beim Start automatisch
angelegt**, und Online gehen **startet das Sammeln automatisch**, danach enthält die **Suche**
echte Artikel.

**Die Oberfläche.** Die Navigation befindet sich in einer **linken Seitenleiste** — einer **flachen Liste** der Daten-Werkzeuge:
**Start · Feed · Erkunden · Einblicke · Sternwarte · Weltkarte · Regierungen ·
Agenda · Klima · Indizes · Rohstoffe *(erweitert)* · Lebende Quellen · Bibliothek** (bei der
Oberflächentiefe **Wesentlich** sind nur Start und Feed angeheftet, der Rest liegt hinter einer
beschrifteten Zeile **Mehr anzeigen**; siehe [3.](#3-die-werkzeuge-im-einzelnen)) (in schmalen Fenstern klappt sie zu einer Symbolleiste zusammen, verschwindet aber
nie). Eine Schaltfläche **Einstellungen** sitzt **unten in der Seitenleiste** (neben dem
Schalter zum Einklappen), und eine **minimale obere Leiste** über dem Inhalt enthält:

- **Die Such- / Befehlsleiste (⌘K / Ctrl-K).** Tippen Sie, um zu einem beliebigen Werkzeug zu springen, eine häufige
  Aktion auszuführen, ein beliebiges Dokument zu öffnen — oder Ihre Daten übergreifend zu durchsuchen (siehe [3.1 Suche](#31-suche)).
  Die vollständige Suche mit ihrer Analyse ist der Tab **Erkunden**.
- **Live-Status** — ein Statuspunkt für das Backend und eine **LLM**-Pille (ein Klick öffnet
  Einstellungen → KI).
- **Task-Manager** — eine Schaltfläche, die das [Task-Manager-Fenster](#30a-aktivität--der-task-manager) öffnet.
- **Flugmodus** — der eine Netzwerk-Ein/Aus-Schalter (ein Flugzeugsymbol, dessen *Füllung* den
  Zustand zeigt; gefüllt = offline). Beim ersten Start weist, solange Sie offline sind, ein kleiner Hinweis auf
  ihn und lädt Sie ein, online zu gehen, wenn Sie so weit sind.
- **Sprachumschalter** — alle 12 Sprachen in einem Menü (die Flagge ist nur ein Hinweis; der
  Name in der Landessprache ist das Erkennungsmerkmal). Ein Klick übersetzt die gesamte Oberfläche neu.
- **Hilfe (?)** — öffnet den Dokumentationsleser in der App (dieses Handbuch und die anderen
  Leitfäden), durchsuchbar und vollständig offline. (Die interaktiven Swagger-/ReDoc-Seiten sind standardmäßig ausgeschaltet, siehe §5.4.)
- **Herunterfahren (Ein/Aus-Symbol)** — beendet den Server sauber; Ihre Daten bleiben unberührt, und die Oberfläche
  wird durch eine Einblendung „Sie können diesen Tab schließen“ ersetzt. (Das ist *keine* Deinstallation und keine
  Löschung.)

**Einstellungen** öffnen Sie über die **Schaltfläche Einstellungen unten in der Seitenleiste** (auch die
Befehlspalette springt direkt dorthin); siehe [3.9 Einstellungen](#39-einstellungen).
**Erscheinungsbild** (**Einstellungen → Grafik**) bietet **14 Farbthemen + System**, Akzentfarbe,
Dichte, eine Auswahl mitgelieferter Schriftarten und das Einklappen der Seitenleiste. Alles wird
lokal gespeichert; nichts wird übertragen.

### Neuerungen (Live-Testzyklus 0.0.8, Juni 2026)

> **Historische Momentaufnahme.** Dieser Abschnitt beschreibt die App zum Stand des Zyklus 0.0.8
> (Juni 2026); die App hat sich seitdem weiterentwickelt. `CLAUDE.md` ist die aktuelle maßgebliche Quelle
> dafür, was danach ausgeliefert wurde — siehe `docs/ledger/shipped.csv` für das Verzeichnis.

- **Der Netzwerkschalter ist ein Flugmodus-Schalter (obere Leiste):** ein gleichbleibendes
  Flugzeugsymbol, dessen **Füllung den Zustand zeigt** — gefüllt bedeutet offline aktiv
  (jede neue Netzwerkanfrage wird sofort abgelehnt; eine bereits laufende Anfrage darf
  noch zu Ende laufen). **Jeder Wechsel zurück nach online fragt zuerst**: Ein einziges Zustimmungsfenster
  nennt die Aktion, die das Netzwerk braucht, und listet die **lokalen
  Schnittstellenadressen** Ihres Rechners auf (aus den Tabellen des Kernels gelesen — nie ein Netzwerk-Aufruf;
  die App ruft bewusst keinen „Wie lautet meine IP“-Dienst ab, denn
  das wäre selbst schon Verkehr). Über diese lokalen Adressen hinaus sieht das Internet
  die öffentliche Adresse, die Ihr Internetanbieter oder VPN vorweist. Einen Sammeldurchlauf starten,
  Markt-Feeds importieren, eine beobachtete Wikipedia-Seite hinzufügen oder einen Dump herunterladen
  — all das läuft offline über dieselbe Zustimmung, und der Schalter
  wird bei jedem Wechsel sofort neu gezeichnet — er wartet nie auf die nächste Abfrage.

  **Der Flugmodus ist eine Garantie auf Socket-Ebene, nicht nur eine Konvention pro Aufruf.** Als
  informierte Einwilligung über den *eigenen* Schutz der App: Solange der Flugmodus aktiv ist, installiert die
  App einen **prozessweiten Schutz** über den Socket-Aufrufen der unteren Ebene
  (`getaddrinfo` / `create_connection` / `connect`), sodass **jeder** Versuch, eine
  Nicht-Loopback-Adresse zu erreichen — aus jedem Codepfad, einer Drittanbieter-Bibliothek oder einem DNS-Prefetch —
  einen Fehler auslöst, bevor der echte Socket benutzt wird. Loopback (127/8, ::1, `localhost`) und Unix-Sockets
  werden immer durchgelassen, sodass der eigene Server der App, ein lokales Ollama und die Datei-Datenbank
  weiter funktionieren. Solange Sie online sind, ist er unsichtbar (keine Kosten während des
  Sammelns). Setzen Sie `OO_AIRPLANE_SOCKET_GUARD=0`, um ihn zu deaktivieren (für eine ungewöhnliche Installation,
  die Loopback anderswohin weiterleitet).
- **Mindmap & Wortwolke in Ebenen (Einblicke):** eine echte radiale Mindmap (Mitte →
  Arme → nach außen gerichtete Blätter) über drei Zoomebenen (Schlagwörter ↔ Familien ↔
  Supergruppen), mit einer Wortwolke als zweiter Ansicht, einem Datumsspektrum-Regler, einem
  Schriftgrößen-Schieberegler und ⛶ Vergrößern. Die Schriftgröße steht immer für die Menge gemeinsamer Artikel.
- **Vorab angelegte Supergruppen:** ein mitgelieferter Grundstock (aus echten Feldprotokollen
  entworfen) wird beim Start angelegt; Ihre eigenen Änderungen und Löschungen haben immer Vorrang.
- **Die Weltkarte ist jetzt eine Choroplethenkarte (ooMap):** Der Tab färbt Länder nach einer gemessenen
  Dimension ein (Quellen · Artikel · Schlagwort-Nennungen · Tonfall), mit Bedienelementen in der Karte für die
  Messgröße, die Feinheit Land↔Kontinent, eine Orte-Ebene, eine Signale-Ebene mit einem
  Zeitpunkt-Schieberegler, eine Server-IP-Ebene, Mausrad-Zoom, Verschieben durch Ziehen und ⛶ Vergrößern. Siehe
  [3.6a](#36a-weltkarte).
- **Aus dem Text extrahierte Ereignisdaten, Orte, Personen und Organisationen:** Der
  Datumsextraktor liest sechs Sprachen, numerische Formate und verankerte Ausdrücke
  („gestern“, bloße Wochentage, „11. Juni“); der Ortsextraktor findet
  Städte aus dem Ortsverzeichnis und Ländernamen; der Entitätsextraktor bringt **Personen**
  und **Organisationen** als zwei bewusst getrennte Klassen zutage (ein Name mit vorangestellter Anrede
  und ein wiederholtes Akronym beantworten unterschiedliche Fragen — jeder Eintrag hält fest,
  welche Regel ihn gefunden hat). Alles fließt in den Metadaten-Kopf des Artikellesers, der
  **„Aus der Quelle“** von **„Von dieser App abgeleitet — weniger verlässlich“**
  (gestrichelter Rahmen) trennt: Extraktionen sind lexikalische Kandidaten mit Herkunftsausschnitt,
  niemals bestätigte Tatsachen.
- **Schlagwort-Exporte pro Sprache:** Das Diagnose-Schlagwortprotokoll ist auf 5.000
  Schlagwörter *pro vorherrschender Sprache* begrenzt, sodass Wortschätze von Minderheitensprachen nie
  durch die Menge englischer Texte aus der Auswertung verdrängt werden.
- **Wikipedia-Offline-Dumps:** Die Liste der Ausgaben lädt wieder korrekt und ist
  mehrfach auswählbar — laden Sie mehrere Sprachausgaben in einem Durchlauf aus der Warteschlange herunter.
- **17 Themen und mitgelieferte quelloffene Schriften:** Neun neue Farbstellungen (Arctic,
  Solar, Forest, Aubergine, Garnet, Cyber, Mist, Dawn, Mint) ergänzen den ursprünglichen
  Satz, und sechs SIL-OFL-Schriftarten werden jetzt **in der App mitgeliefert** (Cantarell, Inter,
  Outfit, Manrope, JetBrains Mono, Source Serif 4 — siehe
  `src/static/fonts/README.md`): nichts herunterzuladen, keine Schriftanfrage verlässt jemals
  Ihren Rechner. Manche Themen sind mit einer Schrift gepaart (Arctic→Inter,
  Cyber→Outfit, Sepia/Paper→Source Serif); die neue Auswahl **Schriftart** in
  Einstellungen → Grafik setzt jede davon außer Kraft, und der Artikelleser verwendet die
  mitgelieferte Serifenschrift. Formularelemente (Schieberegler, Kontrollkästchen, native Auswahllisten) folgen jetzt
  ebenfalls dem Thema.

**Eine Anmerkung zu „FOOS“.** Browser-Tabs, die die App öffnet (Spuren-Recherchen, der
lokale Artikelleser), tragen die Endung **„· FOOS“ — Free Open OmniScience**: kurz
genug für schmale Tableisten, während die App erkennbar bleibt. Es ist der
Arbeitsname der Alpha-Phase; eine richtige Umbenennung kann später folgen.

**Ein Symbol, eine Oberfläche.** Der Installer legt **einen Starter** an — **Open
Omniscience** → `http://127.0.0.1:8000/` — eine leicht zu erkundende, anpassbare App mit Seitenleiste,
die sich fließend an Ihre Fenstergröße anpasst (die Seitenleiste zieht sich in schmaleren Fenstern zu einer Symbolleiste
zurück). Eine experimentelle zweite Oberfläche („Desk“) gab es
in früheren Zyklen; sie wurde in 0.0.8 eingestellt; ihre Geschichte steht in
[`DESIGN.md`](DESIGN.md).

**Betrieb im Hintergrund, bei geschlossenem Browser.** Die App lebt in ihrem Starter-Fenster,
nicht im Browser-Tab. Sie können den Browser jederzeit schließen: das Sammeln,
Wikipedia- und Karten-Downloads, Sicherungen in einen Ordner oder auf ein Laufwerk, Importe, die KI-Aufträge (Modell-Downloads,
Spracherkennung, die KI-Prüfungen) und das Diagnosearchiv laufen alle
weiter. So lassen Sie einen Rechner tagelang sammeln und sparen dabei den Arbeitsspeicher, den ein
Browser belegt (oft 0,5 bis 1 GB, was auf einer kleinen VM ins Gewicht fällt).

Während die App läuft, zeigt das Starter-Fenster ein **Panel**, und es bleibt dort, solange
die App läuft: Es gibt ein einziges Fenster, unter Linux, macOS und Windows gleichermaßen. Oben zeigt es,
ob die App gesperrt ist, den Netzwerk- und Sammelzustand, Arbeitsspeicher und CPU des Servers
und was gerade läuft. Darunter steht ein **Aktivitätsprotokoll**: eine Zeile mit Uhrzeit für jedes Ereignis
(das Sammeln beginnt oder endet, ein Download erreicht 40 %, eine Sicherung ist fertig, das
Netzwerk geht offline, die App antwortet nicht mehr und dann wieder), eine nach der anderen angefügt,
solange die App läuft, die neueste unten. Zurückblättern können Sie mit den Pfeiltasten, PgUp und
PgDn oder dem Mausrad; End springt zurück zur neuesten Zeile. Klicken Sie auf die Schaltflächen oder drücken Sie die
jeweils angezeigte Taste:

- **UI öffnen (Open UI) (o)** öffnet die App wieder in Ihrem Browser.
- **Sammeln pausieren (Pause collection) (p)** beendet das Sammeln und versetzt die App in den Flugmodus. Zum Fortsetzen
  öffnen Sie die Oberfläche: Online gehen führt immer über deren Zustimmungsfenster, nie über das Terminal.
- **Servermeldungen (Server messages) (l)** zeigt die eigenen Meldungen des Servers (nicht unter Windows); drücken Sie eine beliebige Taste,
  um zurückzukehren.
- **App beenden (Stop app) (s)** beendet die App nach einem zweiten Tastendruck. Es nennt die Aufträge, die dabei enden würden.

Das Panel schließt sich nicht von selbst, solange die App läuft, auch nicht, wenn die App beschäftigt ist oder der
Rechner im Ruhezustand war und die App eine Weile zum Antworten braucht: Es sagt, wie lange die App
still war, und versucht es weiter. Es endet, wenn die App endet.
Das Panel fragt nie nach Ihrer Passphrase: Ist die App gesperrt, sagt es das, und Sie entsperren
sie im Browser. Das Schließen des Starter-Fensters oder Ctrl-C beendet die App weiterhin, wie
bisher. Setzen Sie `OO_PANEL=0`, um ohne das Panel zu starten. Die KI-Werkzeuge, die auf der Seite antworten
(Massen-Zusammenfassung oder -Übersetzung, KI-Schlagwortextraktion, Prompt-Läufe), laufen ebenfalls weiter, wenn der
Tab geschlossen ist, und erscheinen im Panel. Um einen davon zu stoppen, öffnen Sie die Oberfläche und drücken Sie **Stoppen**
in seiner Zeile im Task-Manager oder **Abbrechen** auf der Seite (das eigene „App beenden“ des Panels beendet
die ganze App): Er stoppt nach dem gerade bearbeiteten Artikel, und die bereits erledigten Artikel bleiben
gespeichert. Auch der Schlagwortindex der Artikel, die Einblicke noch nicht indexiert hat, holt
von selbst auf, während die App untätig ist. Nur zwei Dinge erfordern, dass der Tab offen bleibt: ein Upload, den Sie
aus dem Browser senden, und eine Datei, die der Browser gerade herunterlädt. Unter
Windows öffnet sich das Panel in einem eigenen Fenster (dessen Schließen beendet die App nicht). Es braucht
das curses-Modul von Python, das Windows über das Paket windows-curses erhält: Der Installer
fügt es auf Intel- und AMD-PCs hinzu, und bei einer Installation, die vor dieser Version gemacht wurde, können Sie es mit
`.venv\Scripts\python -m pip install windows-curses` im Ordner der App hinzufügen. Für Windows on ARM gibt es
noch keinen Build davon, daher startet die App dort ohne das Panel.

---

## 2. Der 60-Sekunden-Rundgang

Der Grundablauf ist:

> **Quelle wählen/hinzufügen → Sammeln → Erkunden (suchen und auswerten) → Exportieren / signieren.**

1. **Einstellungen → Erweitert → Quellen** — ein weltweiter Katalog ist bereits angelegt; fügen Sie nach Belieben eigene hinzu.
2. **Einstellungen → Erweitert → Erfassung** — rufen Sie den RSS-Feed einer Quelle ab oder fügen Sie eine einzelne Artikel-URL ein.
   Oder lassen Sie den **Zeitplaner** das automatisch in Intervallen erledigen. Sammeln braucht das
   Netzwerk: Die Flugzeug-Schaltfläche in der oberen Leiste muss aus sein, und das Ausschalten fragt Sie
   vorher.
3. **Start** und **Feed** — lesen Sie, was hereingekommen ist: Start als gemessene Signale (Spuren), Feed als
   einfacher Strom von Artikeln.
4. **Erkunden** — boolesche Volltextsuche über alles, was Sie gesammelt haben; die
   Analyse der passenden Artikel erscheint unter den Ergebnissen.
5. **Einblicke / Sternwarte / Weltkarte / Regierungen / Agenda / Klima / Indizes /
   Rohstoffe / Lebende Quellen** — optionale Ansichten auf den Korpus und auf öffentliche
   Daten (Muster, Raum-Zeit, Recht, Termine, Klimadaten, Preise, was sich geändert hat).
6. **Exportieren** — CSV/JSON oder ein **signiertes Beweisbündel**, das jeder offline
   überprüfen kann.

Wählen Sie ein beliebiges Werkzeug in der Seitenleiste, oder drücken Sie einfach **⌘K / Ctrl-K** und tippen Sie, wohin Sie
möchten. Für einen kurzen Gang durch die Tabs der Seitenleiste in Ihrer Oberflächentiefe
wählen Sie **Tour starten** (Einstellungen → Allgemein, Hilfe & Doku oder die Befehlspalette).
Sie startet nur, wenn Sie es verlangen, ändert nichts und hält nicht fest, dass sie gelaufen ist. Die aktive Ansicht aktualisiert sich live (alle paar Sekunden), solange sie auf dem
Bildschirm ist, und Aktionen werden mit kleinen Hinweismeldungen in der Ecke bestätigt.
Zerstörerische Aktionen fragen immer zuerst nach.

---

## 3. Die Werkzeuge im Einzelnen

Die Seitenleiste ist eine **flache Liste** der Daten-Werkzeuge (von oben nach unten):

- **Start · Feed · Erkunden · Einblicke · Sternwarte · Weltkarte · Regierungen · Agenda ·
  Klima · Indizes · Rohstoffe *(erweitert)* · Lebende Quellen · Bibliothek** — dazu die Schaltfläche **Einstellungen**
  unten in der Seitenleiste. Die Hilfe öffnet sich über die Schaltfläche **?** in der oberen Leiste.
  Es gibt keinen Tab „Sammeln“: Das Sammeln befindet sich in den Einstellungen.
- **Erkunden** ist eine einzige Seite: das Suchfeld oben und die Analyse der passenden
  Artikel unter den Ergebnissen, sobald eine Suche zurückkommt (siehe [3.1](#31-suche) und
  [3.1a](#31a-analyse--das-korpusfenster)). Ein innerhalb der App angeklicktes Schlagwort
  öffnet seine Analyse auf dieser Seite; ein Schlagwort im Artikelleser, **Korpus öffnen ↗** einer
  Spur auf der Startseite und Enter in der Omnibar öffnen sie in Erkunden in einem **neuen Browser-Tab**.
- **Oberflächentiefe** (Einstellungen → Allgemein) ändert, was die Seitenleiste *anheftet*, nie, was
  Sie erreichen können. Bei **Wesentlich** sind nur Start und Feed angeheftet, und die anderen Tabs liegen
  hinter einer beschrifteten Zeile **Mehr anzeigen**; **Standard** und **Vollständig** listen jeden Tab auf. Die
  Befehlspalette (Ctrl/⌘-K) erreicht jeden Tab in jeder Tiefe.

**Inhalt zuerst.** Die Seitenleiste zeigt die *Daten*; die Oberflächen für Beschaffung und Wartung
befinden sich in den **Einstellungen**: **Sammeln** (der Zeitplaner + manuelles Einlesen), **Quellen**
(der Katalog), **Wikipedia** (Änderungsverfolgung + Offline-Dumps), **Beweise & Verwahrung**
und der **Schreibtisch für Quellenintegrität (source-integrity desk)** werden alle über die Einstellungen erreicht (beschrieben in ihren eigenen
Unterabschnitten unten). Die Einstellungen öffnen sich über die **Schaltfläche unten in der Seitenleiste**; auch die
Befehlspalette springt direkt dorthin.

Einige Namen wurden schlichter (die Bedienelemente sind dieselben): **Einlesen (Ingest) → Sammeln**,
**Datenbank → Bibliothek**, **Weltrecht → Regierungen** (jetzt mit den Unter-Tabs **Länder · Karte · Recht**),
**Märkte → Rohstoffe** (mit abgetrennten **Indizes**). Springen Sie mit
der Befehlspalette (Ctrl/⌘-K) zu jedem Werkzeug.

### 3.0 Start

**Wofür es da ist:** Ihr **Briefing** — ein Sichtungs-Feed plus Orientierung.

- **Briefing (der Feed):** Die App sammelt und misst im Hintergrund und bringt dann
  mögliche Geschichten als **Spuren** zum Vorschein (der Bildschirmname für die Briefing-Karten),
  gruppiert in redaktionelle Kategorien (*steigend, überberichtet, unterberichtet, untersuchen,
  Framing prüfen, beobachten, Kontext, Datenintegrität*). Jede Spur ist **ein gemessenes
  Signal + Beleg-Links + eine Einschränkung** — niemals ein Urteil, und es gibt **keinen „Vertrauens-Score“**
  (im Code verboten).
- **Wendekarten — die Warnung steht auf der Rückseite.** Eine Spur ist eine **zweiseitige Wendekarte**:
  Die **Vorderseite** ist die Spur auf einen Blick; **klicken Sie darauf (oder drücken Sie Enter)**, und sie dreht sich auf eine
  **Rückseite**, die **die Einschränkung, die Methode, den Auslöser, die Belege und eine
  Schaltfläche „Korpus öffnen ↗“** trägt (die genau die Artikelmenge dieser Spur in einem neuen Analysefenster
  öffnet). Die Einschränkung ist standardmäßig im DOM, direkt neben der Aktion — sie wird nie
  hinter einem Ruhe-Schalter versteckt. **+ Zum Entwurf** heftet eine Spur an; **Ausblenden** blendet sie aus
  (umkehrbar). Der Feed ist zwischengespeichert (sofort da) und **aktualisiert sich selbst** — er wird im
  Hintergrund nach jedem Scrape-Durchlauf neu berechnet und fragt selbst erneut ab; es gibt keine Schaltfläche zum Aktualisieren.
- **Newsletter-Entwurf:** angeheftete Spuren + Ihre Notizen, exportiert als **Markdown**, in dem
  jede Aussage bereits ihre Quell-Links, Methode und Einschränkung trägt — reproduzierbarer
  Journalismus. Für eine signierte Kopie der zugrunde liegenden Artikel verwenden Sie Beweise & Verwahrung.
- **Inhalt zuerst im Layout:** Ein kompakter Streifen **Auf einen Blick** ist oben angeheftet (Live-Zählwerte
  + ob das automatische Sammeln läuft), und die Spuren darunter lassen sich
  über vertikale Unter-Tabs nach **Familie** filtern (eine Standardansicht **„Alle Spuren“** plus ein Tab pro
  Kategorie mit eigenem Farbton). Der kuratierte Katalog wird automatisch angelegt, und das Sammeln beginnt, wenn Sie
  online gehen, sodass eine leere Startseite einfach einen ehrlichen Leerzustand zeigt — keine Willkommenskarte. *(Die
  alte große Begrüßung und die Zeile „Schnellaktionen“ wurden entfernt — Start öffnet direkt mit dem
  Briefing.)*

### 3.0a Aktivität & der Task-Manager

**Wofür es da ist:** alles sehen — und steuern —, was die App im
Hintergrund tut, von jedem Tab aus.

- Ein **Aktivitäts-Chip** in der oberen Leiste leuchtet auf, während Arbeit läuft (ein Sammeldurchlauf, ein
  Wikipedia-Dump, ein Marktimport); eine dauerhafte Schaltfläche **Task-Manager** sitzt daneben
  (sie bleibt erreichbar, auch wenn die App untätig ist).
- Öffnen Sie den **Task-Manager** — ein richtiges Fenster (kein Popover) mit fünf Unter-Tabs:
  - **Aktiv** — jeder laufende Auftrag: der Sammeldurchlauf, jeder herunterladende Wikipedia-Dump,
    der gerade laufende Abruf (nur als DOMAIN angezeigt), die Leerlaufschleife und jeder pausierte/fehlgeschlagene
    Download. Jeder Auftrag zeigt seinen echten Fortschritt und die passenden Bedienelemente — **Stoppen** für einen
    Sammeldurchlauf (das aktiviert auch den Netzwerk-Notschalter, Sie gehen also offline; die
    Schaltfläche sagt das) und **Pausieren/Abbrechen** für einen Dump. Keine erfundene Restzeit oder Rate — nur der
    echte Byte-Fortschritt, den der zuständige Teil meldet.
  - **Warteschlange** — Aufträge, die darauf warten, an die Reihe zu kommen: die Warteschlange der Wikipedia-Dumps (einer nach dem anderen) in
    Reihenfolge, mit **↑ / ↓**-Bedienelementen zum Umsortieren (ziehen Sie einen kleinen französischen Dump vor einen
    riesigen englischen).
  - **Zeitplan** — die echten Fakten des Zeitplaners: Zustand (läuft / untätig / gestoppt),
    Fortschritt des aktuellen Durchlaufs (nur Domain), Rhythmus, letzter Lauf und die eigene
    Zeit des nächsten Laufs laut Backend, als ehrliche relative Zeit angezeigt (die Methode steht in der Hover-Blase —
    nie ein erfundener Countdown).
  - **Abdeckung** — Scraping-Reichweite und Aktualität pro Tag (wie viel von jedem Thema/Tag Ihre
    Sammlung tatsächlich berührt und wie aktuell es ist), damit Sie Lücken sehen.
  - **System** — Live-Prozesswerte (CPU, RAM, Downloadrate). *(Die Werte sind aus der oberen Leiste
    hierher umgezogen.)*
- Das Fenster liest **live aus den Systemen, denen die Arbeit gehört**, kann also nie
  von dem abweichen, was tatsächlich geschieht — kein Schattenzustand.

### 3.0b Feed

**Wofür es da ist:** Ihren Korpus als **Strom** lesen statt als Menge gemessener
Signale. Start sagt Ihnen, was herausstach; der Feed reicht Ihnen einfach Artikel, einen nach dem
anderen, und lässt Sie scrollen.

- **Zwei Reihenfolgen, beide benannt.** **Neueste zuerst** ist das Veröffentlichungsdatum, das neueste oben.
  **Gemischt** ist eine feste Reihenfolge, gewählt durch einen **Seed**: Die Position eines Artikels hängt
  von seiner ID und diesem Seed ab und **von nichts sonst**. Jede Seite trägt ihre eigene Methodenzeile,
  die sagt, welche der beiden Sie lesen.
- **Das Mischen ist eine Stöberhilfe, keine Empfehlungsmaschine.** Es gibt **keinerlei Bewertung
  von Engagement** — nichts misst, was Sie geöffnet haben, wie lange Sie geblieben sind oder was Sie
  übersprungen haben, und **es wird kein Leseverlauf geführt oder herangezogen**. Zwei Personen mit demselben
  Seed und demselben Korpus sehen dieselbe Reihenfolge. Dieser Satz ist Teil des Methodentexts,
  den die Seite ausgibt, sodass er nicht stillschweigend aufhören kann, wahr zu sein.
- **Was ausgelassen wird, gezählt.** Der Feed zeigt Artikel, die **nicht in Quarantäne** sind
  und deren **Quelle eingestuft wurde**. Beide Ausschlüsse werden **exakt gezählt** und
  auf der ersten Seite angezeigt, sodass ein kurzer Feed bei vollem Korpus als *„Ihre Quellen wurden
  noch nicht eingestuft“* zu lesen ist — womit Sie etwas anfangen können — statt als *„Sie haben nichts“*,
  was falsch wäre. Diese beiden Zahlen beschreiben den Korpus, nicht die Seite, daher
  werden sie einmal berechnet und ändern sich beim Scrollen nicht.
- **Wo Sie aufgehört haben.** Das Scrollen behält seine Stelle über Sitzungen hinweg, indem es **eine
  Positionsmarke** in Ihrem Browser speichert — einen Seed und einen einzelnen Cursor, nie eine Liste dessen, was
  Sie gelesen haben. **Einstellungen → Allgemein → Feed-Scrollverlauf** enthält die beiden Bedienelemente:
  **Neu mischen** (ein neuer Seed, eine neue Reihenfolge, zurück zum Anfang) und **Von oben beginnen**
  (gleiche Reihenfolge, Position gelöscht).
- **Die ehrliche Lücke in jeder Reihenfolge.** Das Sammeln läuft weiter, während Sie scrollen, und jede
  Reihenfolge verpasst neu eingetroffene Artikel auf andere Weise: Bei **Gemischt** können sie *unterhalb*
  der Stelle landen, die Sie erreicht haben (Neu mischen erreicht sie), und bei **Neueste zuerst**
  erscheinen sie *oberhalb* davon (zurück nach oben erreicht sie). Die Seite sagt, was jeweils gilt.
- **Jede Karte** zeigt den Titel, die Quelle, das Datum und die **eigenen drei häufigsten
  Schlagwörter** des Artikels — die Schlagwörter dieses Artikels, nicht die dessen, wonach Sie gesucht haben. **Weiterlesen**
  klappt die Zusammenfassung **an Ort und Stelle** auf; der Titel öffnet den Artikel im lokalen Leser.

### 3.1 Suche

**Wofür es da ist:** Artikel in Ihrem Korpus finden. Die Suche ist die obere Hälfte des
Tabs **Erkunden** in der Seitenleiste; die Analyse der gefundenen Artikel
([3.1a](#31a-analyse--das-korpusfenster)) erscheint direkt unter den Ergebnissen, ohne dass Sie
eine Schaltfläche drücken müssen. Eine Suche ohne Wörter und ohne Filter listet einfach jeden Artikel auf und
wertet nichts aus.

- **Boolesche Abfrage** — unterstützt `AND` / `OR` / `NOT`, `"exact phrases"` und
  Klammern mit korrektem Vorrang, z. B.
  `(climate OR energy) AND policy NOT opinion`. Gestützt auf SQLite FTS5 und vollständig
  parametrisiert (keine Injection).
- **Arabische, chinesische und japanische Wörter werden gefunden, wie auch immer sie geschrieben sind.** Ein arabisches
  Wort passt mit oder ohne Vokalzeichen und unabhängig von der Schreibweise von Alif, Ta marbuta
  oder Alif maqsura (أحمد findet احمد, مدرسة findet مدرسه), und ein chinesisches oder japanisches
  Wort wird innerhalb einer längeren Zeichenfolge gefunden (东京 findet einen Artikel, in dem 东京大学 steht).
  Chinesisch wird bei jeder Installation von jieba in Wörter zerlegt; Japanisch von sudachipy, das
  mit dem optionalen Zusatzpaket `[segmentation]` kommt. Artikel, die vor dieser Version indexiert wurden,
  werden weiter so gefunden wie bisher, und auch nach Wörtern, sobald **Suche neu
  indexieren** (Einstellungen → Erweitert → Diagnose) gelaufen ist.
- **Filter:** Quelle (exakter Name), Sprache (Code wie `en`) und ein **Zeitraum**-Regler
  — Von/Bis-Datumsfelder, eine ziehbare Bereichsleiste und Schnellvorgaben
  (1M · 6M · 1Y · 5Y · All) — *derselbe* Regler wie bei Märkte, Einblicke und dem
  Analysefenster. Über die volle Spanne eingestellt, schließt er nichts aus; engen Sie ihn ein, um die
  Suche auf einen Zeitraum zu beschränken. Alles optional.
- **Suche** führt die Abfrage aus; die Ergebnistabelle zeigt **Titel · Quelle · Veröffentlicht ·
  Sprache** und eine Anzahl (`N result(s)` und, falls gekürzt, wie viele angezeigt werden).
- **Aktionen pro Zeile:** **öffnen** (eine saubere Offline-Kopie des gespeicherten Artikels),
  **Quelle ↗** (die ursprüngliche URL), **Zusammenfassen** und **Übersetzen** (lokales LLM, sofern
  Ollama verfügbar ist).
- **Exporte:** **CSV exportieren**, **JSON exportieren** und **Signierte Belege exportieren** — ein
  manipulationssicheres, signiertes Bündel genau der Artikel, die zu Ihrer Abfrage passen (siehe
  [Beweise & Verwahrung](#38-beweise--verwahrung)). Es öffnet zuerst eine Übersicht: wie viele
  Artikel und Quellen, was die Datei enthält, dass sie unverschlüsselt ist und welcher Schlüssel signiert;
  das Speichern ist ein weiterer Klick, und die Meldung danach listet die Bestandteile der Datei und den
  Schlüssel auf, den Sie dem Empfänger geben. Außerdem ein **Methodenanhang** (eine reproduzierbare Aufzeichnung der
  Abfrage + Methode).
- **Läufe des lokalen Modells über alle Treffer:** **Alle zusammenfassen** / **Alle übersetzen** stellen
  einen Hintergrundlauf Ihres lokalen Modells über jeden gefundenen Artikel in die Warteschlange (gespeichert mit Modell +
  Datum und — da es KI-Ausgabe ist — nie in den vertrauenswürdigen Schlagwortindex eingespeist); **Extraktor
  ausführen** lässt einen Ihrer eigenen KI-Extraktoren über die Menge laufen; **Ergebnisse synthetisieren**
  öffnet ein Fenster, in dem Sie bis zu 20 Elemente auswählen und einen einzigen Durchlauf des lokalen Modells mit Quellenangaben
  darüber erhalten (siehe die Vertiefung). Läufe stehen in der Warteschlange und lassen sich abbrechen; dieselben Bedienelemente stehen im
  Analysefenster.

> **Zwei Wege hinein.** Öffnen Sie **Erkunden** in der Seitenleiste, oder tippen Sie in die Omnibar und wählen Sie
> *„Vollständige Boolesche Suche ausführen“*: Beide führen auf dieselbe Seite, mit vorausgefüllter Abfrage.

**Die Omnibar (Ctrl/⌘-K), von überall:** Die Befehlspalette ist auch eine
übergreifende Suche über Ihre Daten. Ab zwei getippten Zeichen zeigt sie die ersten
drei Treffer pro Gruppe — **Artikel** (vollständige boolesche FTS), **Schlagwörter** (jedes öffnet
sein Korpusfenster), **Quellen**, **beobachtete Wikipedia-Seiten**, **auf diesem Rechner gespeicherte
Wikipedia-Texte** (ältere Versionen und Texte geänderter Seiten, die der Wikipedia-Bereich aufbewahrt,
siehe 3.7) und **verfolgte Rechtsdokumente** — mit der *tatsächlichen Gesamtzahl* jeder Gruppe in ihrer Kopfzeile.
Alles ist indexgestützt und wird nur auf diesem Rechner durchsucht; eine halb getippte
Abfrage ist nie ein Fehler. Wählen Sie *„Vollständige Boolesche Suche ausführen“*, gelangen Sie in
diesen Tab mit vorausgefüllter Abfrage, sodass jede oben genannte Fähigkeit nur einen Schritt
entfernt bleibt.

### 3.1a Analyse — das Korpusfenster

**Wofür es da ist:** eine *Menge* von Artikeln oder ein einzelnes Schlagwort in ein Analyseobjekt
verwandeln, das Sie aus jedem Blickwinkel lesen können. Ein Schlagwort ist ein Korpus; ein einzelner Artikel ist ein Korpus
aus einem. Die Analyse befindet sich auf der Seite **Erkunden**, unter den Suchergebnissen. Sie
erscheint, wenn Sie:

- in Erkunden eine Suche ausführen (oder in der Omnibar *„Vollständige Boolesche Suche ausführen“* wählen),
- in der Omnibar **Enter** drücken (das öffnet Erkunden in einem neuen Browser-Tab),
- irgendwo auf ein **Schlagwort** klicken (Einblicke, die Rückseite einer Spur oder der Leser, wo sie sich in einem neuen Browser-Tab öffnet),
- auf eine **Spur auf der Startseite** klicken (ihr „Korpus öffnen ↗“ öffnet die *exakte* Artikelmenge, in einem neuen Browser-Tab), oder
- auf den Titel eines Rohstoff-Diagramms / **Analysieren ↗** klicken.

Wird eine Analyse von anderswo geöffnet (ein Schlagwort, eine Spur, ein Rohstoff), wird die
Suchliste beiseitegelegt, und die Seite sagt, wessen Analyse sie zeigt, sodass Liste und
Analyse nie stillschweigend zwei verschiedene Artikelmengen beschreiben. Mehrere Analysen
bestehen nebeneinander als **benannte Tabs** in einem Streifen oben; jede ist nach ihrer Abfrage benannt und zeigt die
**Artikelanzahl**, über die sie berechnet wurde. Die Unter-Tabs sind:

- **Übersicht** — eine Zusammenfassung der Menge auf einen Blick.
- **Schlagwörter** — die Rangtabelle der Schlagwörter (echtes gemeinsames Vorkommen / n / PMI, kein Score).
- **Trend** — der Verlauf von Nennungen/Volumen über die Zeit, gezeichnet mit dem gemeinsamen interaktiven Diagramm-Werkzeugkasten
  (Mausrad-Zoom, Verschieben durch Ziehen, Hover für einen exakten Messwert; volle Auflösung innerhalb des
  Fensters, wobei dünn besetzte Abschnitte ehrlich als Balken + eine Einschränkung für frühe Korpora gezeigt werden statt
  als vorgetäuschte Kurve).
- **Mindmap** — eine deterministische radiale Schlagwortkarte (Mitte → Arme, immer nach außen).
- **Artikel** — die zugehörigen Artikel (seitenweise). Spalten: **Titel · Quelle ·
  Veröffentlicht · Häufigstes Schlagwort**, und jede Spaltenüberschrift ist die **Sortiersteuerung** — ein Klick
  sortiert danach, ein erneuter Klick kehrt die Reihenfolge um; der Pfeil markiert die gültige Spalte. Namen
  beginnen mit A–Z, Daten und Zahlen mit dem größten Wert. Dieselbe Wahl steht in den
  Auswahllisten **Sortieren nach / Reihenfolge** über der Liste, denn es sind dieselben zwei Felder: Es gibt
  genau eine Sortierung in diesem Fenster, sodass nichts Ihre Wahl stillschweigend außer Kraft setzen kann. *(Die
  Sortierung befand sich früher unter **Erweitert**, drei Unter-Tabs entfernt von der einzigen Liste, die sie liest.)*

  **Häufigstes Schlagwort** ist das EIGENE meistgenannte Schlagwort dieses Artikels mit seiner Anzahl, ermittelt
  bei der Indexierung des Artikels — eine andere Frage als die Anzahl des *gesuchten* Schlagworts,
  die die separate Schaltfläche `↕ "term" count` ist. Wo mehrere Schlagwörter bei dieser Anzahl gleichauf liegen,
  sagt die Zeile **gleichauf**, denn das genannte ist einfach das erste davon, und es das häufigste
  Schlagwort zu nennen, würde eine Rangfolge behaupten, die die Zählung nie aufgestellt hat. Ein Artikel, den die Neuindexierung
  noch nicht erreicht hat, zeigt **—**, nie eine 0: Ihm fehlt eine Messung, nicht
  Schlagwörter.

  Jede Zeile öffnet sich im **Offline-Leser**, dessen eigene Tab-Leiste **Lesen · Zusammenfassung ·
  Übersetzung · Schlagwörter · Mindmap · Stimmung · Verwandt · Quelle · Links** lautet — dort
  lesen Sie ihn, sehen seine **ursprüngliche Quelle** (der sichtbare Text des Links ist die vollständige
  URL) und lassen **Zusammenfassung / Übersetzung** vom lokalen Modell erstellen. Diese drei wurden früher
  pro Zeile als Pfeil und zwei Schaltflächen wiederholt; sie sind auf die eine Seite umgezogen, die
  das Ergebnis tatsächlich anzeigen kann. Die Massenaktionen **Alle zusammenfassen / Alle übersetzen** sind in
  der Aktionszeile unten unverändert. Nahezu identische Kopien tragen die Kennzeichnung „N Kopien = eine Stimme“.
- **Wann/Wo/Wer** — die Daten, Orte und Personen/Organisationen, die die Menge erwähnt, als anklickbare
  **Facetten**; ein Klick auf einen Wert **vertieft** auf genau die Artikel, die ihn erwähnen (ein verfeinertes
  Analysefenster). Aus dem Text abgeleitet, nie bestätigt.
- **Links** — welche zugehörigen Artikel **ausgehende Links teilen**. Das bringt bewusst
  *Strukturen gemeinsamer Herkunft* zum Vorschein: Drei Artikel, die einen Ursprung zitieren, sind eine Quelle
  mit drei Hüten, daher zählt Übereinstimmung nur dann als Bestätigung, wenn die Wege
  unabhängig sind. Das Ziel sind die *Quellen der Quellen*.
- **Verwandt** — nahezu identische Kopien über Quellen hinweg („N Kopien = eine Stimme“) und gemeinsame
  Ursprünge, jeweils mit einem **„In ein neues Korpus abzweigen →“**, das ein neues Analysefenster
  über genau diese Artikel öffnet.
- **Stimmung** — Tonfall pro Quelle (VADER; die Einschränkung „nur Englisch“ wird angezeigt).
- **Quellen** — die beschreibende Herkunft der Medien in der Menge.
- **Wettbewerb** — wie die Medien in der Menge im Vergleich abschneiden (Volumen / Tonfall / Zeitpunkt /
  Gewichtung — beschreibend, nie ein Sieger oder ein Score).
- **Preis** — *(nur wenn das Fenster von einem Rohstoff aus geöffnet wurde)* die Preiskurve,
  überlagert mit der Abdeckung in Ihrem Korpus auf einer gemeinsamen Zeitachse (gemeinsames Auftreten, nie Kausalität),
  jede Reihe auf ihrer eigenen Skala in echten Einheiten.
- **Erweitert** — schränken Sie die Menge nach **Quelle · Sprache · Zeitraum** ein; ein Chip „Gefiltert“
  und eine Zusammenfassung zeigen, was aktiv ist. (Die Sortierung ist in den Tab Artikel umgezogen, siehe oben.)

Die Aktionszeile enthält **Methodenanhang**, **Signierte Belege exportieren**, **Ergebnisse
synthetisieren** (das Fenster zur Auswahl der Elemente) und die in die Warteschlange gestellten Läufe des lokalen Modells **Alle zusammenfassen / Alle übersetzen / Extraktor
ausführen** — derselbe Satz wie bei der Suche darüber.

### 3.2 Sammeln *(unter Einstellungen → Erweitert → Erfassung)*

> **Wo es sich jetzt befindet.** Die Erfassung ist eine Beschaffungsoberfläche und ist deshalb aus der
> Seitenleiste nach **Einstellungen → Erweitert → Erfassung** umgezogen (Inhalte zuerst). Die Bedienelemente sind unverändert.

**Wofür es da ist:** Artikel in den Korpus bringen – automatisch oder manuell.

**A. Automatische Erfassung (der Planer).** Ein Hintergrundprozess, der in festen
Zeitabständen erfasst. Bedienelemente:

- **Starten / Stoppen / Jetzt sammeln** – dauerhaft laufen lassen, anhalten oder sofort einen
  einzelnen Durchlauf ausführen. Die Statusanzeige zeigt `running` / `running — scrape in progress` /
  `stopped` sowie den Zeitpunkt des nächsten Laufs; die Zeile darunter zeigt die Bilanz des letzten Laufs.
- **Intervall (Minuten)** und ein Schieberegler **Sammelgeschwindigkeit** (ein Zielwert für die Downloadrate). Die
  App misst ihre eigene tatsächliche Downloadrate und erhöht oder senkt die Zahl der gleichzeitig
  angesprochenen Hosts, um Ihren Zielwert zu halten; sie drosselt automatisch, wenn CPU, Arbeitsspeicher oder der eine
  verschlüsselte Schreibvorgang zum Engpass werden. Die Rücksichtnahme pro Host wird nie gegen Geschwindigkeit eingetauscht.
  *(Es gibt keine Obergrenze „max. Quellen pro Lauf“ – mit der Zeit kommt jede Quelle an die Reihe, sodass keine
  zu kurz kommt.)*
- **Modus:** *RSS-Feeds*, *Rekursives Crawling*, *Märkte (Preisregeln)* oder *Wikipedia
  (beobachtete Seiten)*. Wenn Sie **Crawling** wählen, erscheinen **Crawl-Tiefe** und **Max. Seiten /
  Quelle** (der Crawler bleibt innerhalb der Domain der jeweiligen Quelle, beachtet robots.txt
  nach dem Prinzip „im Zweifel gesperrt“, ist ratenbegrenzt und hart beschränkt – er *entdeckt* Artikel, er
  spiegelt keine Websites).
- **Ausrichtung:** **Sprachen**, **Quellentypen** und **Tags / Schlüsselwörter (eines genügt)**
  schränken ein, welche Quellen ein Lauf berührt. **Ziele vorschauen** zeigt genau, wie viele
  Quellen passen (aufgeschlüsselt nach Sprache und Typ), *bevor* Sie den Lauf starten.
- **Beim Start automatisch beginnen** + **Zeitplan speichern** speichern die Konfiguration dauerhaft.

**B. Manuelle Erfassung.**

- **RSS-Feed einer Quelle einlesen** – wählen Sie eine Quelle und klicken Sie auf **Feed abrufen**.
- **…oder eine einzelne Artikel-URL einlesen** – fügen Sie eine URL ein und klicken Sie auf **URL einlesen**.

In beiden Fällen zeigt die Ergebniszeile eine Bilanz: gespeichert, übersprungene Duplikate, durch
robots blockiert usw. Der Abruf erfolgt immer ethisch (robots im Zweifel gesperrt, ratenbegrenzt).

### 3.3 Quellen *(unter Einstellungen → Erweitert → Quellen)*

> **Wo es sich jetzt befindet.** Wie „Sammeln“ ist auch der Quellenkatalog nach **Einstellungen →
> Erweitert → Quellen** umgezogen (Inhalte zuerst). Die Bedienelemente sind unverändert.

**Wofür es da ist:** die Medien, aus denen Sie sammeln, erfassen und pflegen.

- **Eine Quelle hinzufügen:** Name, Domain, RSS-URL, Tags → **Quelle hinzufügen**. Oder **Startquellen
  einrichten**, um die kuratierte Auswahl im öffentlichen Interesse zu registrieren.
- **Quellen verwalten (Tabelle):** Filtern nach Suchtext, Land, Sprache, Typ, Tag
  und Aktivierungsstatus. Die Spalten sind **sortierbar** (Name, Domain, Typ, Land, Sprache,
  Priorität (Priority), Artikel). Direkt in der Tabelle können Sie die **Priorität** (1–3) ändern, **Aktiviert** umschalten
  und **Löschen** (mit Bestätigung). Seitenweise angezeigt, mit einer Zählung `N source(s)`.
- **Import / Export (CSV):** **Alle exportieren (CSV)**, **Vorlage herunterladen** und
  **CSV importieren**. Spalten: `name`, `domain` (Pflicht), dazu `rss_url`,
  `source_type`, `country` (2 Buchstaben), `language`, `region`, `tags`
  (kommagetrennt), `priority` (1–3), `rate_limit_ms`, `enabled`,
  `reliability_score` (1–10). Der Import **aktualisiert oder legt an, abgeglichen über die Domain** – neue Zeilen werden angelegt,
  vorhandene aktualisiert – und **fehlerhafte Zeilen werden gemeldet, nicht stillschweigend verworfen**.

#### Quellenqualifizierung – die Zulassungsprüfung

**Eine Quelle zu aktivieren reicht allein nicht aus** – eine Quelle wird überhaupt erst *gesammelt*, wenn
sie **qualifiziert** wurde. Jede Quelle trägt einen von drei kategorialen Stempeln, niemals
eine Qualitätsbewertung:

- **ungeprüft** (unqualified) – noch nicht beurteilt (der Standard für eine entdeckte, zitierte oder von Hand hinzugefügte
  Quelle);
- **qualifiziert** – hat einen kleinen Probeabruf bestanden, der die *Gültigkeit der Extraktion* geprüft hat (echter
  Fließtext statt eines kaputten/unbrauchbaren Abrufs, z. B. einer Navigationsmenü-Seite oder einer Bezahlschranke) – sie
  nimmt jetzt an der regulären Sammlung teil;
- **disqualifiziert** – die bei der Probe extrahierten Seiten wirkten strukturell kaputt, nicht
  bloß „langweilig“ oder knapp (der Stil wird nie beurteilt, nur ob überhaupt echter Artikeltext
  zurückkam).

**Der kuratierte Katalog, der mit der App ausgeliefert wird, ist von Anfang an qualifiziert** (Entscheidung des Maintainers
vom 2026-09-10). Seine Einträge – die von Hand geprüften Kataloge für Nachrichten, Spektrum, Märkte und Recht –
tragen einen Stempel, dessen *Grundlage* der Katalog selbst ist; im Herkunftsbereich der Quelle wird er
als **qualifiziert · per Katalog** angezeigt, und diese Quellen nehmen vom ersten Tag an an der Sammlung teil, statt
hinter dem Rückstand der entdeckten Quellen zu warten. Der Stempel ist keine Messung und gibt sich nie als
solche aus: Er wird im **gleichen Drei-Monats-Takt wie jede qualifizierte Quelle** erneut geprüft (siehe unten),
eine nicht bestandene Nachprüfung disqualifiziert die Quelle genau wie jede andere, ein Urteil, zu dem diese Instanz
bereits gelangt ist, wird von ihm nie überschrieben, und der Qualifizierungsexport zählt solche
Einträge gesondert und gibt sie nie als selbst erarbeitete Urteile weiter. Entdeckte, zitierte und von Hand hinzugefügte
Quellen durchlaufen weiterhin die Probe.

Ein **Hintergrundauftrag führt bei jedem Online-Sammeldurchlauf automatisch einige dieser Probeprüfungen
aus** (ein begrenzter, genehmigter Netzwerkabruf von „wenigen Artikeln“ – im Flugmodus
verweigert, genau wie jede andere Netzwerkaktion). Bei einer Neuinstallation mit
vielen frisch eingerichteten/entdeckten Quellen kann dieses Tröpfeln einen echten Rückstand hinterlassen: **Einstellungen
→ Quellen → „Quellenqualifizierung“** zeigt den Bereich und eine Schaltfläche **„Rückstand qualifizieren“**,
die *dieselbe* Beurteilung gebündelt als abbrechbaren Task-Manager-Auftrag ausführt, um
schneller aufzuholen.

**Die Qualifizierungswarteschlange** (Erweitert → Qualitätsprüfungen) zeigt, was die nächsten Durchläufe
beurteilen werden, in dieser Reihenfolge: **zuerst neue Quellen** (nie beurteilt oder ohne genug Artikel
versucht), dann die Quellen, deren Nachprüfung fällig ist. Eine neue Quelle ist immer dringlicher als eine
Nachprüfung (Entscheidung R94). Der Bereich gibt außerdem an, wie viele qualifizierte Quellen warten und wann
die nächste in die Warteschlange kommt.

**Wie viele Quellen ein Durchlauf beurteilt**, wächst mit dem Rechner (Entscheidung R95): Die Zahl unter
Einstellungen → Erweitert → Qualitätsprüfungen (*Zu beurteilende Quellen pro Sammeldurchlauf*) und die
*Qualifizierungs-Nachprüfungen pro Durchlauf* (qualification re-checks per pass) des Planers (festgelegt über die Planerkonfiguration, `PUT /api/scheduler/config`;
dafür gibt es kein Bedienelement in den Einstellungen) sind ein Minimum, und solange *automatisches Qualifizierungsbudget* (qualification budget auto) eingeschaltet ist (der Standard), beurteilt jeder Durchlauf so viele
neue Quellen und Nachprüfungen, wie Arbeitsspeicher und Prozessorkerne des Rechners tragen, ohne feste Obergrenze. Eine
Einstellung unter den Standardwerten, oder 0, wird so übernommen wie angegeben; wenn Sie die Automatik ausschalten, gelten die Zahlen
genau. Jeder Kandidat wird anhand seiner neuesten Artikel beurteilt, so vielen, wie der verfügbare Arbeitsspeicher
fassen kann (mindestens 2.000), und der Durchlauf gibt an, für wie viele Kandidaten diese Grenze galt.

**Auf einem kleinen Rechner** (mit weniger Arbeitsspeicher als die Scan-Untergrenze der App) beurteilt ein Durchlauf Kandidaten
anhand einer **Stichprobe der neuesten 20.000 Artikel** statt des gesamten Korpus, und das
Urteil vermerkt, dass es auf einer Stichprobe beruht (Entscheidung R93). Vorher übersprangen solche Rechner jeden
Durchlauf stillschweigend, und keine Quelle wurde je qualifiziert. Passt selbst die Stichprobe nicht, sagt der Durchlauf
das und startet nicht.

Eine **disqualifizierte Quelle bekommt eine zweite Chance** – sie wird nie gelöscht, und allein die Zeit
(nie ein erneuter Import oder ein neues Zitat) löst eine Nachprüfung aus:
1 Monat nach der ersten Disqualifizierung, dann verdoppelt bis zu einer Obergrenze von 6 Monaten (1 → 2 → 4 →
6), und zurückgesetzt, sobald eine Nachprüfung bestanden ist. **Deshalb kann eine neu hinzugefügte oder
kürzlich disqualifizierte Quelle bis zu sechs Monate lang aktiviert, aber ungesammelt bleiben**,
ohne etwas zu sammeln – prüfen Sie die Qualifizierungsanzeige in ihrer Zeile (siehe unten), wenn eine
von Ihnen hinzugefügte Quelle scheinbar nie Artikel beisteuert.

**Wo die Qualifizierungszahl geblieben ist:** Die Kachel in der Bibliothek, die früher eine einzige
Zahl „Quellen“ zeigte, zeigt jetzt **drei ehrliche, sich nicht überschneidende Zahlen** – *Quellen
(sammelnd)* (Sources (collecting); aktiviert **und** qualifiziert), *Quellen, die auf Qualifizierung warten (aktiviert)* (Sources awaiting qualification (enabled))
und *Entdeckte Kandidaten* (noch deaktiviert – siehe unten) –, denn wurden sie zu
einer Zahl zusammengefasst, sah ein maschinell gewachsener Rückstand von Zehntausenden entdeckter Kandidaten
so aus, als sammle die App bereits aus allen.

#### Nachprüfung – ein Stempel gilt nicht ewig

Ein Urteil ist eine Messung, und eine Messung altert. **Ein Qualifiziert-Stempel wird etwa alle drei
Monate erneut geprüft** (Entscheidung R94, 2026-09-29) (die Planereinstellung `qualification_recheck_per_pass`, nur per API; 0
schaltet die Nachprüfung ab). Die Nachprüfung folgt einem festen Intervall, nicht der Verdopplung der
Disqualifizierungsleiter – die Verdopplung drückt schwindende Hoffnung nach wiederholtem Scheitern aus und bedeutet
nach einem Erfolg nichts.

**Was eine Nachprüfung sehen kann und was nicht, klar gesagt:** Sie beurteilt eine Quelle anhand ihrer gesamten
gespeicherten Historie. Sie erkennt also eine Quelle, die *grundsätzlich* kaputt ist, und sie wird eine Quelle **nicht**
bemerken, die erst kürzlich schlecht wurde, wenn Jahre guter Artikel die neuen
überwiegen. Ihr eigentlicher Wert liegt woanders und ist wissenswert: Eine Quelle, die sehr früh
zugelassen wurde, auf Grundlage von nur ein oder zwei Artikeln, wurde beurteilt, als es noch nicht genug Korpus
zum Vergleich gab – die Nachprüfung ist das erste Mal, dass sie an einem echten
Maßstab gemessen wird.

Nachprüfungen haben ihr **eigenes** Budget, getrennt von dem, das neue Kandidaten zulässt.
Das ist kein Detail: Solange sie sich ein Budget teilten, verbrauchte eine Installation mit großem Rückstand
ungeprüfter Quellen jeden Platz für neue Kandidaten, und keine Nachprüfung – auch nicht die
oben beschriebene zweite Chance für Disqualifizierte – lief jemals tatsächlich.

#### Urteile wandern mit: Sicherungen und eine Neuinstallation

Qualifizierungsarbeit, die auf einer Instanz geleistet wurde, **geht nicht verloren, wenn Sie Korpora verschieben oder zusammenführen**.

- **Beim Import einer Sicherung** werden deren Urteile mitgenommen. Eine Quelle, die der eingehende Korpus beurteilt hat,
  kommt beurteilt an. Eine Quelle, die *diese* Instanz nie beurteilt hat, **übernimmt** das eingehende
  Urteil – in beide Richtungen, sodass eine Quelle, die eine andere Instanz als kaputt befunden hat, hier nicht
  stillschweigend wieder in die Probewarteschlange gelangt. Ein Urteil, zu dem *diese* Instanz gelangt ist, hat immer Vorrang:
  Ein importierter Korpus kann das Urteil Ihres eigenen Rechners nie umstoßen, in keiner
  Richtung.
  Der Ausgangsstempel des Katalogs ist kein solches Urteil: Ein importiertes *gemessenes* Urteil
  ersetzt ihn. Hat eine Quelle, die noch nur den Katalogstempel trägt, ein neueres importiertes
  Urteil *disqualifiziert*, nimmt der nächste Start sie aus der Sammlung und führt sie in der
  Diagnose auf; wo das Urteil Ihres eigenen Rechners dem Import widerspricht, bleibt Ihres erhalten, und die
  Quelle wird von Ihrem eigenen Qualifizierungsdurchlauf vorzeitig erneut geprüft.
- **Eine Neuinstallation beginnt mit dem, was frühere Instanzen gemessen haben.** Die App liefert
  `configs/source_qualification.yml` mit, eine generierte Liste von Urteilen, und übernimmt sie beim
  ersten Start für Quellen, die sie nie beurteilt hat. Eine Quelle, die in dieser Datei **fehlt**, wird einfach
  ungeprüft ausgeliefert und vom ersten eigenen Qualifizierungsdurchlauf der Installation beurteilt, genau
  wie bevor es die Datei gab – der ausgelieferte Katalog besteht also faktisch aus zwei Listen: den
  bereits von der App qualifizierten Quellen und denen, die es noch werden sollen.

Ein übernommenes Urteil wird als **geerbt** vermerkt, nicht als etwas, das dieser Rechner gemessen hat,
und es behält das Datum, an dem es ursprünglich gefällt wurde – so sieht nie etwas so aus, als hätte Ihre
Installation es gemessen. Neu beginnt dagegen die eigene Nachprüfungsuhr Ihres Rechners: Sie läuft ab
dem Tag, an dem Sie das Urteil übernommen haben, nicht ab dem Tag, an dem jemand anderes es erarbeitet hat. Ein erster Download ist
daher ruhig, und genau das ist der Sinn – ein ausgelieferter Katalog ist immer älter als das dreimonatige
Intervall, wenn er bei Ihnen ankommt; liefe die Uhr ab dem ursprünglichen Datum, müsste jede
Neuinstallation am ersten Tag den ganzen Katalog neu qualifizieren, also genau die Arbeit leisten, die die
ausgelieferte Datei ersparen soll.

Dieser Kompromiss ist bewusst gewählt und hat einen Preis, den man aussprechen sollte: Die Aktualität des ausgelieferten
Katalogs stellt nicht mehr jede Installation für sich selbst fest. Sie wird
neu hergestellt, wenn eine neue Version eine Ergänzungsdatei (Overlay) ausliefert, die aus Instanzen neu erstellt wurde, die die
Nachprüfung *tatsächlich* durchgeführt haben. Der unten beschriebene Export gibt an, wie alt seine Urteile sind, sodass diese Veraltung
sichtbar statt verschwiegen ist.

#### Die Urteile Ihrer Instanz zurückgeben

`GET /api/diagnostics/source-qualification-export` gibt an, was Ihre Instanz über
ihre ausgelieferten Quellen weiß – wie viele qualifiziert, wie viele disqualifiziert und wie viele noch
offen sind –, und `?fmt=yaml` liefert dieselbe Liste als die Overlay-Datei selbst.
`scripts/merge_source_qualification.py` führt Exporte mehrerer Instanzen zu einem zusammen.

Wenn Sie von diesen Instanzen bereits **Gesamtdiagnose-Pakete** (all-diagnostics bundles) gesammelt haben, müssen Sie nicht
zurückgehen und neu exportieren: Das Paket enthält denselben Export als Bestandteil, und
`--from-bundle` liest ihn direkt aus der ZIP-Datei. Die beiden Wege sind austauschbar und
lassen sich in einem Lauf beliebig mischen:

```
python scripts/merge_source_qualification.py laptop-export.json \
    --from-bundle oo-all-diagnostics-desktop.zip \
    --from-bundle oo-all-diagnostics-server.zip
```

Der ausgegebene Bericht nennt, wie viele Instanzen zusammengeführt wurden und auf welchem Weg. Ein Paket, dessen
Exportbestandteil nicht vollständig war, wird mit dem Grund genannt, den diese Instanz vermerkt hat – es wird
nie stillschweigend übersprungen, denn ein Overlay, von dem Sie glauben, es beruhe auf drei Instanzen, das
tatsächlich aber auf zweien beruht, ist schlimmer als ein Fehler.

Zwei Dinge tut das Skript bewusst nicht. Es **löst nie einen Widerspruch auf**: Hat eine
Instanz eine Domain qualifiziert, die eine andere disqualifiziert hat, wird das gemeldet, damit ein Mensch es sich
ansieht, denn automatisch einen Gewinner auszuwählen, würde jeder Installation ein Urteil liefern, das niemand geprüft hat.
Und es zählt ein **geerbtes** Urteil nie als Bestätigung – eine Sicherung in
acht Rechner zu importieren, ist eine Messung, die achtmal gesehen wird, nicht acht Messungen.

#### Entdeckungsspur und Bilanz qualifizierter Zitate

Klicken Sie auf die Zeile einer Quelle, um **ihre Entdeckungsspur aufzuklappen**: **wo sie gefunden wurde**
(der Zitatkanal, der Katalog, Wikipedia-Belege, …) und, bei einer
über Zitate entdeckten Quelle, den **ersten Artikel, der sie zitiert hat** (mit einem Link sowohl zum
Artikel als auch zur zitierenden Quelle). Daneben zählt eine **Bilanz qualifizierter Zitate**
die Domains, die *diese* Quelle selbst zitiert, aufgeteilt in **qualifiziert / disqualifiziert /
offen / nicht registriert** – jede Zahl ist anklickbar und klappt die genaue Liste auf.

Das ist eine **beschreibende Tatsache, niemals ein Urteil über eine der beiden Quellen** – eine
disqualifizierte Domain zu zitieren, ist keine Schuld (ein seriöses Medium verlinkt routinemäßig Unternehmen,
Plattformen oder kaputte Seiten, über die es lediglich *berichtet*), und viele qualifizierte
Domains zu zitieren, ist ebenso wenig eine Empfehlung (eine Nachrichtenagentur wird von allen zitiert; eine
Drehscheibe zur Verschleierung kann gezielt seriöse Quellen zitieren). Lesen Sie es als Hinweis, dem man
nachgehen kann, so wie jedes andere gemessene Signal in dieser App ein Hinweis ist und keine
Bewertung.

#### Sprachen, die wir noch nicht analysieren können – standardmäßig deaktiviert (behalten)

Die Schlüsselwort-/Analyse-Engine kann nur Sprachen **verwalten**, für die eine *Stoppwortliste*
existiert und deren Schrift **durch Leerzeichen gegliedert** ist. Die maßgebliche Liste steht in einem
Modul – [`src/analytics/managed.py`](../src/analytics/managed.py) (`MANAGED_LANGUAGES`)
–, das sowohl die Quellensteuerung als auch der Engine-Bericht in der App auslesen, sodass das Handbuch nicht
vom Code abweichen kann. Laut diesem Modul umfasst die verwaltete Menge: **en, fr, de, es, it, pt, nl,
ru, ar, hu, id, sv, da, nb, no, pl, sr, sl, el, bg, hi, bn, fa, ur, uk, ro, cs, sk, ca,
sw, az, et, tr, fi, bs, hr**. Eine Sprache, die **nicht** in dieser Menge ist, wird zwar weiterhin *in Tokens zerlegt*, aber ihre
Funktionswörter (Entsprechungen von „der/des/und“) schleichen sich als falsche Schlüsselwörter ein. **ja und th sind
nicht segmentiert**, sofern das optionale Extra `[segmentation]` nicht installiert ist – sie haben keine
Leerzeichen zwischen den Wörtern, sodass die Schlüsselwortextraktion ohne Segmentierer völlig unbrauchbar ist, unabhängig
von jeder Stoppwortliste. **zh** war in derselben Lage, bis jieba in
0.4 zu einer Kernabhängigkeit wurde; es wird auf jeder Installation segmentiert und ist daher verwaltet.

Material in diesen Sprachen zu sammeln, erzeugt daher **unbrauchbare Schlüsselwörter**, die:

- **die Analysen verfälschen** – falsche Schlüsselwörter verzerren Assoziationen, Trends und
  Supergruppen, und
- **den Korpus aufblähen** – jede Aggregation (Einblicke, Gruppen, die Mindmap) zahlt
  den Preis für Hunderttausende bedeutungsloser Zeilen, was bei großen Korpora die
  Leistung spürbar bremst.

Daher gilt bewusst: **Eine neue Quelle in einer nicht verwalteten Sprache wird *deaktiviert* angelegt**. Sie wird
**behalten** (nie gelöscht) und ist vollständig **wieder aktivierbar** – Sie können diese
Medien weiterhin lesen, und sobald eine Stoppwortliste für ihre Sprache hinzukommt, schalten Sie sie wieder
ein. Das ist ein ehrlicher Kompromiss: Wir *sammeln* lieber *nicht*, was wir *verstümmeln* würden,
als unzuverlässige Analysen zu präsentieren. Ein **ausdrückliches** `enabled: true` in einem CSV-Import
hat immer Vorrang (Ihre Auswahl wird respektiert), und eine Quelle, deren Sprache **unbekannt** ist,
bleibt aktiviert (wir deaktivieren nie, was wir nicht einordnen können).

**Um dies auf einen bestehenden Korpus anzuwenden:** Einstellungen → Erweitert → Quellen zeigt, wie viele aktivierte
Quellen in nicht verwalteten Sprachen vorliegen (und welche), und bietet **„Quellen in noch nicht analysierbaren Sprachen
deaktivieren“** an – eine umkehrbare Sammelaktion, die sie deaktiviert
(und behält). Jede davon können Sie jederzeit in der Quellentabelle wieder aktivieren.

### 3.4 Bibliothek

*(Vor 0.05 hieß sie **Datenbank**.)*

**Wofür es da ist:** ein ehrlicher Blick darauf, was Sie tatsächlich besitzen und wie weit Ihre
Quellen reichen.

- **Datenbankstatistik (Database stats):** live animierte Zählungen (Artikel, Quellen, eindeutige Domains,
  …), dazu das Backend sowie **Größe auf dem Datenträger und Pfad** der Datenbank. Jede
  Zahl ist eine echte Zählung oder Bytegröße – nichts ist geschätzt.
- **Weltweite Abdeckung:** wie viele Länder Ihr Quellenkatalog erreicht, gemessen
  an ISO 3166 – `covered/total countries`, `coverage %`, die Zahl der *nicht* abgedeckten
  und die Zahl der „dünn“ abgedeckten Länder (unter dem Schwellenwert). Länder werden als ISO-2-Codes in Kleinbuchstaben
  gespeichert und **mit ihrem vollen Namen angezeigt** (eine einzige Umwandlungsschicht,
  `src/catalog/countries.py`). Ein Block **Regionale Balance** vergleicht die Quellen und abgedeckten Länder
  jedes Kontinents mit den Arbeitsuntergrenzen in
  `configs/catalog_targets.yml` (klar als Zielvorstellungen gekennzeichnet, entworfen anhand der
  tatsächlichen Gestalt des Katalogs), dazu eine **Konzentrationswarnung** für das stärkste Land – die
  Kennzahl aus 0.0.9 gegen die US-Zentrierung. Die Tabelle listet jedes Land mit seiner Region, der Zahl seiner Quellen
  und **Themen-Schlüsselwort-Plaketten** (aus den Quellen-Tags). **Klicken Sie auf ein Land oder ein
  Schlüsselwort**, um zu den Quellen zu springen, gefiltert auf genau diese Quellen. Ein Lückenbericht
  nennt die Länder, für die es noch keine Quelle gibt. Der Bereich aktualisiert sich live (keine Schaltfläche zum
  Aktualisieren nötig); dieselbe Kennzahl ist offline über
  `python scripts/catalog_coverage_report.py` verfügbar.

### 3.5 Märkte

**Wofür es da ist:** **echte** Preise für Rohstoffe, Währungen und Energie verfolgen und
sie mit dem Nachrichtenaufkommen in Beziehung setzen.

- **Markttrend-Übersicht (Market trends dashboard):** eine Karte pro Preisreihe – Symbol, prozentuale Veränderung, letzter
  Preis (Währung/Einheit), Anzahl der Datenpunkte und eine kleine Verlaufslinie. Ein Bedienelement für den **Zeitraum**
  – Datumsfelder Von/Bis, ein verschiebbarer Bereichsbalken und Schnellvorgaben (1M · 6M · 1Y ·
  5Y · Alle) – richtet jede Karte auf ein exaktes Start-/Endfenster aus (keine feste Liste von
  Maßstäben); die vollständige Reihe wird darin immer in voller Auflösung gezeichnet, nie
  ausgedünnt. Klicken Sie auf eine Karte für ein vollständiges Diagramm sowie
  eine **Preis↔Nachrichten-Korrelation** (echter Pearson-/Spearman-Koeffizient, p-Wert und
  Stichprobengröße – nie eine geschätzte Zahl). Die kuratierten offiziellen Feeds **aktualisieren sich
  automatisch im Hintergrund**, während Sie online sind (es gibt keine Schaltfläche zum Laden/Aktualisieren);
  die Übersicht hat außerdem **Kategorie-Untertabs**, einen Ansichtsschalter **Karten/Familien**, eine
  **Vergleichen**-Überlagerung (mit einem Skalenschalter Absolut/Indexiert/Log) und eine gemeinsame Zeitachse.
- **Datenquellen konfigurieren** (einklappbar – die meisten Nutzer werden es nicht brauchen):
  - **Offizielle Preis-Feeds** (FRED, das die Reihen des **„Pink Sheet“ der Weltbank**
    und der **EIA** führt): **Importieren** per Klick, dazu **Diagramm**.
  - **Preisextraktionsregeln (Price-extraction rules):** eine Regel hinzufügen (Quelle, Symbol, Bezeichnung, Seiten-URL, **CSS-Selektor**,
    optional Attribut/Regex, Währung, Einheit, Markt). Die goldene Regel:
    **Eine Zahl wird nur gespeichert, wenn Ihr Selektor tatsächlich auf eine trifft – nie
    geraten.** Mit **Testen** rufen Sie die Seite einmal ab und sehen den genau gefundenen Wert oder
    den genauen Grund, warum nichts passte, bevor Sie sich darauf verlassen.
  - **Eigener Feed (beliebige CSV-URL):** verweisen Sie auf eine beliebige CSV-Datei (Standardzuordnung ist Spalte 1 =
    Datum, Spalte 2 = Wert, die FRED-Konvention); fehlende Werte werden übersprungen, nie
    als null gespeichert.

Die vollständige Referenz zu Extraktionsregeln finden Sie in [`docs/USER_MANUAL.md`](USER_MANUAL.md).

### 3.5a Indizes

**Wofür es da ist:** weltweite **Aktienindizes** (S&P 500, NASDAQ, Dow Jones,
VIX, Nikkei 225 …) – **getrennt von den Rohstoffen** geführt, denn ein Index ist ein
Index und kein Rohstoff.

- Eine Übersicht von Indexreihen mit denselben detaillierten Diagrammen in voller Auflösung wie bei den
  Rohstoffen (Kategorie-Untertabs, Tag-Filter, Vergleichen-Überlagerung, Familienansicht, eine gemeinsame
  Zeitachse). Die kuratierten offiziellen Feeds (FRED, Stooq) **aktualisieren sich automatisch im
  Hintergrund**, während Sie online sind – es gibt keine Schaltfläche zum Importieren/Aktualisieren.
- Jeder Feed trägt ein **ehrliches Urteil pro Feed**, wenn er nicht abgerufen werden kann –
  *verweigert* ≠ *durch robots untersagt* ≠ *eingestellte Reihe* ≠ *nicht erreichbar* ≠ *offline* –, sodass
  ein blockierter Feed laut scheitert, statt eine falsche Zahl anzuzeigen. Über Tor werden manche
  Feeds vom Host blockiert; das Urteil sagt genau das (siehe §5.5).

### 3.6 Einblicke

**Wofür es da ist:** Schlüsselwort- und Entitätsanalysen über den **Text der erfassten
Artikel**. *(Erfordert das Extra `[analysis]`; echte Erkennung benannter Entitäten ist
optional über das spaCy-Extra `[nlp]`.)*

- **Status und Indexierung:** Eine Anzeige zeigt `indexed/total articles · keywords (entities)
  · mentions · remaining`. **Die Indexierung erfolgt automatisch** – sie folgt der Erfassung, und wenn Sie
  Einblicke öffnen, arbeitet eine stille Nachindexierung im Hintergrund jeden verbliebenen Rückstand ab (die Zahl
  „remaining“ zählt von selbst auf 0 herunter). Es gibt **keine Schaltfläche „Korpus indexieren“ (Index corpus)** – sie wurde
  zugunsten der automatischen Indexierung entfernt. Personen, Organisationen und Orte werden als
  Einheiten behalten; die Indexierung lässt sich fortsetzen, und der Balken aktualisiert sich live. *(Die automatische
  Indexierung schalten Sie mit `OO_NO_INDEX=1` ab.)*
- Acht Untertabs:
  - **Erkunden** – geben Sie ein Schlüsselwort oder eine Entität ein (z. B. *Inflation*, *Emmanuel Macron*,
    *Rio Tinto*) und erhalten Sie: eine **Trend**-Linie über die Zeit; eine **Assoziations-Mindmap**
    (nach PMI geordnete gemeinsam auftretende Begriffe – Kantenbreite = gemeinsames Auftreten, Abstand =
    Stärke; klicken Sie auf einen Knoten, um ihn ins Zentrum zu rücken); eine Tabelle zur **Rahmung** (wie sich der
    Ton der einzelnen Medien unterscheidet, über VADER, mit den Begriffen, die sie betonen); und **Im Kontext**:
    Textausschnitte mit Links zu Quelle/Ort/Datum.
  - **Trends** – **Steigend** (am schnellsten wachsende Schlüsselwörter, aktuelles Fenster gegenüber Vergleichsfenster) und
    **Top** (am häufigsten erwähnt), dazu drei voreingestellte Fenster (24h · Woche · Monat) nebeneinander,
    filterbar nach Art (Begriffe/Entitäten/Personen/Organisationen/Orte) und Land. Klicken Sie auf einen
    Begriff, um ihn zu erkunden; klicken Sie auf ✕, um ihn auszuschließen.
  - **Quellen** – Quellen, die in Ihrem Korpus im Trend liegen.
  - **Familien** – Schlüsselwortfamilien (morphologische Varianten zusammengefasst).
  - **Gruppen** – Supergruppen (dauerhafte Oberbegriffe) und sprachübergreifende **Ringe**
    (ein Begriff und seine Übersetzungen/Synonyme), bearbeitbar.
  - **Karte** – die ooMap-Choroplethenkarte über Ihren Korpus (dieselbe Komponente wie der Tab
    Weltkarte).
  - **Konvergenz** – rein lesendes gemeinsames Auftreten in Raum und Zeit: Artikel, die sich innerhalb eines Zeitfensters
    um das genannte Ereignisdatum auf denselben **Ort** konzentrieren. Die Unabhängigkeit wird
    an **verschiedenen Quellen** gemessen (eine einzelne geschwätzige Quelle kann keine erzeugen); jeder Cluster
    trägt den Vorbehalt „gemeinsames Auftreten, niemals Kausalität – ein Anlass zum Lesen, kein Beweis“.
  - **Beobachtungen** – Ihre gespeicherten „Wenn-dies-dann-beobachten“-Bedingungen: eine lokale FTS-Abfrage + ein
    Schwellenwert + ein Zeitfenster. Wenn der Korpus genug neue passende Artikel hinzugewinnt, erscheint eine **Beobachtungs-Spur**
    auf der Startseite. Nur lokal, keine Benachrichtigungen, kein Netzwerk, keine Telemetrie;
    anlegen / aktivieren / bearbeiten / löschen, mit einem Trefferverlauf.

Jede Zahl ist ein echtes Aggregat mit ihrer Stichprobengröße und einem Vorbehalt. Siehe
[`docs/USER_MANUAL.md`](USER_MANUAL.md). Um festzulegen, welche Schlüsselwörter erscheinen, verwenden Sie den
[Schlüsselwortfilter in den Einstellungen](#39-einstellungen).

### 3.6a Weltkarte

**Wofür es da ist:** sehen, *wo* Ihr Korpus angesiedelt ist – eine **Choroplethenkarte** („Weltweite
Abdeckung“), die jedes Land nach einer gemessenen Dimension Ihrer Daten einfärbt, mit optionalen
Ebenen für Orte, Signale und Serverstandorte. Sie beruht auf einer wiederverwendbaren Kartenkomponente
(**ooMap**), und jedes Bedienelement befindet sich **innerhalb der Karte** (die Google-Maps-Konvention):
Zoom ＋/－, Zoomen mit dem Mausrad, Verschieben durch Ziehen, ⛶ Vergrößern sowie die Auswahl für Ebene und Messgröße.

- **Die Messgröße der Choroplethenkarte (Auswahl in der Karte):** Wechseln Sie, was die Länder einfärbt, zwischen
  **Quellen · Artikel · Schlüsselwort-Erwähnungen · Mittlerer Ton**. Zählungen verwenden eine sequenzielle Skala;
  **Mittlerer Ton** verwendet eine **divergierende** Skala (positiv ↔ negativ um null) und trägt
  den Vorbehalt **VADER nur für Englisch** sowie das `n` der bewerteten Artikel – ein Land ohne
  englischsprachigen bewerteten Artikel zeigt „keine Daten“, nie ein erfundenes Neutral.
- **Ehrlich: keine Daten ≠ null:** Ein Land ohne verortete Daten wird mit einem **Schraffurmuster**
  dargestellt und mit „keine Daten“ beschriftet, optisch klar unterschieden von einer echten Null. Kleine Gebiete, die der grobe
  Umriss nicht zeichnen kann, erscheinen als **Punkte**; Quellen ohne Land werden **gezählt, aber
  nie platziert** („N not mapped“).
- **Granularität (Schalter in der Karte):** Ansicht nach **Land** oder zusammengefasst nach **Kontinent**
  (eine Summe bei Zählungen, ein nach `n` gewichteter Mittelwert beim Ton – nie ein Mittelwert von Mittelwerten; ein unbekannter
  Kontinent ist ehrlich „keine Daten“).
- **Orts-Überlagerung:** Schalten Sie **Orte** ein, um die Orte darzustellen, *über die* Ihre Artikel
  *sprechen* (aus dem bei der Erfassung extrahierten Wann/Wo/Wer, an einer Gazetteer-Koordinate), als
  hohle Markierungen, deren Größe der Verbreitung über Artikel entspricht – mit dem Vorbehalt **„Aus dem Text abgeleitet, nie
  bestätigt.“**.
- **Ebene Signale + fokussierter Moment:** Schalten Sie **Signale** ein, um datierbare Ereignisse in Raum und Zeit
  (kuratierte Ankerpunkte, Korpusartikel, extrahierte Daten) als nach Art eingefärbte Punkte darzustellen; ein
  **Schieberegler für den fokussierten Moment** fährt durch die Zeit (bestätigt = gefüllt, zukünftig/unbestätigt = ein
  gestrichelter Ring, der mit zeitlichem Abstand verblasst). Klicken Sie auf eine Markierung für einen Detailbereich – Datum,
  Ort, Quelle, offizieller Link, **„Abdeckung in Ihrem Korpus finden“** und eine Liste **„Nah in
  Raum & Zeit“**, die ausdrücklich sagt, dass gemeinsames Auftreten *„keine Verbindung und keine
  Ursache ist. Sie urteilen.“*
- **Ebene Server-IPs:** Zeigen Sie optional die offline geolokalisierten **Serverstandorte** der
  Quellen an – mit dem ehrlichen Vorbehalt, dass es sich um einen CDN-Edge- bzw. Anycast-Host handelt, **nicht** um einen Beweis
  für den wahren Ursprung des Herausgebers (und über Tor nicht verfügbar, wo der Socket der
  Proxy ist, nicht der Server).
- **Küstenlinien und Grenzen werden mitgeliefert:** Die Geometrie der Länder und Küsten wird mit der App ausgeliefert
  (Natural Earth, vergröbert) – nichts zu erstellen, keine Grenzen erfunden.

Daten, *von denen* ein Bericht handelt, werden außerdem zu **Datums-Tags pro Artikel**: Öffnen Sie die Offline-Leseansicht
eines Artikels, um sie aufgelistet zu sehen, jeden Kandidaten zu **bestätigen oder abzulehnen** oder bei Bedarf zu **extrahieren**;
der Korpus lässt sich dann nach einem genannten Datum filtern (`GET /api/article-dates/by-date`).
Der Extraktor arbeitet mit hoher Präzision: Bloße Jahreszahlen und vage Zeitspannen werden nicht extrahiert,
**verankerte relative Wörter** („gestern“) und **bloße Wochentage** dagegen schon.

### 3.6b Agenda

**Wofür es da ist:** ein Kalender datierter Ereignisse – was ansteht, mit Quellen belegt und ehrlich.

- Ein **Monatsraster** (Wochenbeginn Montag; Monats- und Tagesnamen in Ihrer Oberflächensprache) ist die
  Standardansicht, daneben gibt es die Ansichten **Woche · Quartal · Halbjahr · Jahr · Jahrzehnt · Liste**
  (eine gemeinsame Navigationsleiste). Tage mit Ereignissen sind markiert; klicken Sie auf einen Tag für die
  Details und auf den Titel eines Ereignisses, um es im Korpus zu öffnen.
- **Abgeleitete Ereignisse (aus Ihren Artikeln):** Zukünftige Daten, die in mehreren
  Artikeln *genannt* werden, erscheinen als eigene, filterbare Ebene **abgeleitet** – jeder Eintrag zeigt eine
  Plakette „abgeleitet · nie bestätigt“ und die Zahl der Artikel/Quellen, und sein Titel öffnet
  genau die zugehörige Artikelmenge. Nur Zählungen, niemals ein Urteil.
- **Astronomie, lokal berechnet:** Die vier Hauptmondphasen (Neumond, erstes Viertel, Vollmond, letztes Viertel) sowie die Tagundnachtgleichen/Sonnenwenden werden
  auf diesem Rechner berechnet (Algorithmen nach Meeus, überprüft an veröffentlichten Werten aus astronomischen
  Jahrbüchern); jeder Eintrag nennt in der Hover-Blase seine **Methode und Genauigkeit**.
  Jahreszeiten werden **ehrlich nach Hemisphäre** benannt – nie ein bloßes „Sommer“.
- **Klimakontext:** ein mitgelieferter Datensatz zu El-Niño-/La-Niña-Episoden (nach der
  NOAA-CPC-ONI-Konvention); jeder Eintrag, der noch auf einen Abgleich über das offene Internet wartet, trägt eine
  Markierung „Prüfung ausstehend“.
- **Bewegliche Daten sind als solche gekennzeichnet** – die App erfindet nie einen genauen Tag für ein
  Ereignis, dessen Datum sich jedes Jahr verschiebt.
- **Kalender** (iCal-Quellen für Feiertage / religiöse Feste / Astronomie) werden unter
  **Einstellungen → Agenda** abonniert, nicht hier – der Tab zeigt die Daten, die Technik dahinter liegt in den
  Einstellungen. Danach halten sie sich selbst aktuell: Während die Sammlung läuft, werden neue Ereignisse
  importiert und jeder Feed der Reihe nach erneut geprüft, einige pro Durchlauf. Ein Feed, der fehlschlägt, wird
  nach 1 Monat erneut geprüft, dann nach 2, 4 und 6 – **mit Obergrenze, sodass ein Feed nie endgültig
  abgeschrieben wird** –, und die Bilanz pro Durchlauf ist im **Tab Zeitplan des
  Task-Managers** sichtbar. Nichts davon läuft beim Start oder offline. Der **Katalog** mit rund 500 Feeds selbst
  (Urteile, Ordner doppelter Anbieter, Hinzufügen eigener `.ics`-Dateien) gehört zur Technik und
  befindet sich unter **Einstellungen → Erweitert → Kalenderverzeichnis**.
- **Ist die Datei mit den importierten Ereignissen so beschädigt, dass nichts davon gelesen werden kann** (abgeschnitten,
  kein gültiges JSON oder ein Lesefehler des Datenträgers unter Linux oder macOS), liest die Agenda sie als leer, und das Protokoll
  vermerkt das. Bevor die nächste Speicherung sie ersetzt (ein Import, eine Wiederherstellung, das Entfernen eines Feeds), bewahrt die App die beschädigte Datei einmal
  unverändert als `calendar_feed_imports.json.damaged` in Ihrem Datenordner auf, für Sie oder ein
  Wiederherstellungswerkzeug; eine zweite Beschädigung überschreibt diese erste Kopie nie. Sie ist nicht Teil einer
  Sicherung. Sie können sie jederzeit selbst entfernen. Eine Datei, in der nur einige Einträge beschädigt sind,
  wird weiterhin gelesen: Diese Einträge werden ausgelassen, das Protokoll zählt sie, und es wird keine Kopie angelegt. Eine
  leere Datei wird ebenfalls nicht kopiert: Sie enthält nichts, was sich wiederherstellen ließe.

### 3.6b Lebende Quellen

Der Tab **Lebende Quellen** zeigt, was sich in den Quellen geändert hat, die sich nach dem
Sammeln weiter ändern: Wikipedia, Recht und Karten, mit je einem Untertab. Alles darin
wird von diesem Rechner gelesen; zum Darstellen wird nichts abgerufen.

- **Wikipedia:** wie vielen Seiten der Live-Stream folgt, wie viele Änderungen er
  in den letzten 30 Tagen gemeldet hat und **für wie viele er den Text gespeichert hat** („2 von 4“:
  innerhalb eines Budgets speichert er einige und zählt den Rest), der Punkt, bis zu dem jeder
  Feed ohne Unterbrechung gelesen wurde, und alle Lücken, von denen er weiß, dass er sie verpasst hat. Darunter steht jede
  Änderung, die neueste zuerst; **Diff anzeigen** öffnet den Diff, der beim Eintreffen der Änderung gespeichert wurde.
  Eine Änderung, die nur gezählt wurde, sagt das und hat keinen Diff. Die Seiten, die Sie von Hand
  verfolgen (Einstellungen → Wikipedia), sind ebenfalls aufgeführt: Wählen Sie eine aus, um ihre verfolgten
  Versionen zu lesen. Jede Version an einem der beiden Enden des Vergleichs hat ihr eigenes **Zum
  Korpus hinzufügen**: Es fügt genau diese Version als eigenen Artikel hinzu, datiert auf den Zeitpunkt, an dem das Wiki sie
  erstellt hat, und sagt es, wenn Ihr Korpus sie oder denselben Wortlaut bereits enthält. Eine Version,
  deren Text nicht gespeichert wurde, kann nicht hinzugefügt werden, und ihre Schaltfläche sagt, warum. Auf diesem Weg gelangt eine
  von **Jetzt verfolgen** gespeicherte Version in Ihren Korpus, da die Suche diese noch nicht
  liest. Wenn der **Seitendurchlauf** eingeschaltet ist (siehe unten), zeigt eine Gruppe *Seitendurchlauf*, was er
  gerade tut (durchlaufen; angehalten, und warum; oder Abwarten nach einer Ablehnung durch das Wiki) und,
  pro Ausgabe, die Seiten, die er aufgelistet hat, **gemessen an der eigenen Artikelzahl der Ausgabe**
  („1 234 000 von 2 700 000“). Das sind zwei Zählungen, nie ein Prozentsatz: Jede Ausgabe
  zählt ihre Artikel auf ihre eigene Weise, sodass die erste Zahl die zweite übersteigen kann. Wenn
  das Abrufen der **anderen geänderten Seiten** eingeschaltet ist (siehe unten), zählt eine Gruppe *Andere geänderte Seiten*
  (oberhalb der des Durchlaufs) die Seiten, die einen Text haben, die geänderten Seiten, die noch auf
  ihren warten, die abgerufenen Texte und die Seiten, denen der Stream inzwischen
  folgt, ebenfalls pro Ausgabe, und sagt, wann sie aufhört: bei einem angegebenen Anteil des
  Speicherbudgets – ein vorgeschlagener Standardwert, den die App anzeigt, keine Entscheidung.
- **Recht:** die Dokumente, denen der Rechts-Tracker folgt, die neueste und die älteste Prüfung sowie
  jede echte Änderung (eine erneute Prüfung, die nichts geändert hat, wird nicht gezählt) mit ihrem
  gespeicherten Diff und einem Link zu Ihrer lokalen Kopie.
- **Karten:** Ihre heruntergeladenen Kartenregionen, welche davon angehalten oder fehlgeschlagen sind und warum, und
  der Speicherplatz, den sie belegen.

Die Aktualität wird als Datum angezeigt, nie bewertet: Wie aktuell aktuell genug ist, hängt von
der jeweiligen Geschichte ab. Budgets werden angezeigt, aber unter **Einstellungen → Daten & Sicherung** festgelegt.

### 3.6c Klima

**Wofür es da ist:** sechs veröffentlichte Klima- und Erddatenreihen neben Ihrem Korpus lesen,
jede genau so, wie ihr Herausgeber sie veröffentlicht hat. Der Tab hat einen Untertab pro Datensatz:

- **Temperatur** – NASA GISTEMP v4: monatliche und jährliche globale
  Temperatur-*Anomalien* (Abweichungen vom Durchschnitt 1951-1980, in °C, keine Temperaturen).
- **Meereis** – NSIDC Sea Ice Index v3: die tägliche Meereisausdehnung in der Arktis oder Antarktis, in
  Millionen km².
- **El Niño** – der Oceanic Niño Index der NOAA: die dreimonatige Anomalie der Meeresoberflächentemperatur
  in der Region Niño 3.4 im Pazifik.
- **Erdbeben** – der USGS-Katalog: Erdbeben der Magnitude 6,0 und darüber weltweit,
  gezählt pro Monat seit Januar 1973, mit der jeweils größten Magnitude des Monats.
- **Emissionen & Energie** – Our World in Data: jährliche Emissions- und Energiedaten nach
  Land und Region, wobei jede Spalte die Bedingungen ihres ursprünglichen Erzeugers behält.
- **Wetterstation** – NOAA GHCN-Daily: tägliche Temperatur, Niederschlag und Schnee an
  **einer** Station, ausgewählt über ihre 11-stellige Kennung (zum Beispiel `USW00094728`, New York
  Central Park). Eine Station beschreibt einen Ort, keine Region und nicht das Klima.

**Wie abgerufen wird.** Nichts wird heruntergeladen, bevor Sie es verlangen. Jeder Untertab hat seine eigene
Schaltfläche **Beim Herausgeber abrufen** (sie lautet **Beim Herausgeber aktualisieren**, sobald etwas
gespeichert ist; bei **Wetterstation** geben Sie eine Stationskennung ein und drücken **Station abrufen**, danach
**Diese Station aktualisieren**), die den Server nennt, den sie kontaktiert. Sie durchläuft dasselbe Zustimmungs-Popup wie jede
andere Netzwerkaktion und wird verweigert, solange der Flugmodus eingeschaltet ist. Der Abruf läuft im
Hintergrund; der Task-Manager zeigt ihn an. Das Lesen bereits gespeicherter Daten löst keinen
Netzwerkzugriff aus.

**Worauf Sie sich verlassen können.** Jeder Untertab nennt seine Quelle, seine Lizenz, seine Methode und wann
dieser Rechner sie zuletzt abgerufen hat. Ein neuer Abruf speichert nur Werte, die neu sind oder die der
Herausgeber überarbeitet hat: Frühere Werte bleiben lesbar, und Zeiträume, die der Herausgeber nicht mehr bereitstellt,
werden gezählt, nie gelöscht. Eine leere Zelle ist eine veröffentlichte Lücke, nie eine Null. Nichts hier ist
eine Prognose, eine Bewertung oder eine Risikoeinstufung.

### 3.6d Sternwarte

**Wofür es da ist:** Ihren gesamten Korpus auf einen Blick sehen, gezeichnet als Nachthimmel. Jede
**Galaxie** ist eine Gruppe verwandter Schlüsselwörter; jeder Kreissektor ist einer von zwölf
Themenbereichen.

- Der **Winkel** (Angle) trägt nur den Themenbereich. Wo eine Galaxie innerhalb ihres Sektors sitzt, ergibt sich aus einem stabilen
  Hash, sodass sie zwischen Besuchen an ihrem Platz bleibt und für sich genommen nichts bedeutet.
- Der **Abstand vom Zentrum** trägt die eine Messgröße, die Sie wählen, mit beschrifteten Ringen.
  Die **Sterngröße** (Star size) wird als Fläche gezeichnet (Erwähnungen) und ist ein zweitrangiger Hinweis.
- Die **Farbe** zeigt die Sprache oder die Linse **Trend**; sie ist nie das einzige Signal.
  Sternbildlinien verbinden Galaxien, die ein Schlüsselwort als Mitglied teilen, nie Galaxien, die
  bloß nah beieinander aussehen.
- Die **Rangtabelle** unter dem Himmel listet jede Galaxie vollständig auf, auch diejenigen, die der
  Himmel nicht platzieren kann. Die Tabelle ist die maßgebliche Ansicht; der Himmel ist eine zweite Art, sie
  zu lesen. Eine Zeile darüber zählt, was das Bild auslässt (noch nicht beobachtete Galaxien und
  Schlüsselwörter außerhalb jeder Galaxie).
- Derselbe Korpus zeichnet immer denselben Himmel, sodass eine Veränderung, die Sie sehen, eine Veränderung in Ihren
  Daten ist. Es gibt keine zusammengesetzte Bewertung.

### 3.7 Wikipedia *(unter Einstellungen → Wikipedia)*

> **Wo sie jetzt zu finden ist.** Die Wikipedia-Änderungsverfolgung und die Werkzeuge für Offline-Dumps sind
> nach **Einstellungen → Wikipedia** umgezogen (Inhalt zuerst); die beobachteten Seiten erscheinen weiterhin in
> der allgemeinen Suche und Analyse wie jeder andere Artikel. Die Bedienelemente sind unverändert.

**Wozu sie dient:** bestimmte Wikipedia-Seiten beobachten und **verdächtige
Bearbeitungen markieren** — die Daten sind die *Bearbeitungen*, nicht eine Kopie des Artikels.

- Fügen Sie eine zu beobachtende Seite über **Ausgabe** (Sprachcode, z. B. `en`, `fr`, `ar`),
  **Artikeltitel** (Article title) und eine optionale Bezeichnung für die **Beobachtungsliste** hinzu. Die App speichert **einen
  Ausgangs-Schnappschuss** und danach nur noch die **Unterschiede (Diffs/Deltas)** jeder neuen Bearbeitung — kosmetische
  Änderungen kosten also fast nichts.
- **Jetzt verfolgen** (optional mit **ORES-Bewertungen verwenden**) holt neue Revisionen ab und markiert
  große oder verdächtige: große Größenänderungen, Revert-/Leerungs-Tags, anonyme Bearbeitungen,
  Bearbeitungsschübe und — falls aktiviert — die ML-Bewertungen von ORES zu Schädlichkeit/gutem Glauben. Kandidaten
  werden *Ihnen zur Beurteilung vorgelegt*; nichts wird als „Desinformation“ bezeichnet.
- **Markierte Änderungen** listet Bearbeitungen auf (Zeitpunkt · Ausgabe · Seite · Bearbeiter · Δ Bytes ·
  Gründe · ORES), mit einer **Unterschiede**-Ansicht und einem **Live**-Link zu Wikipedia.
  Filtern Sie nach *nur markierte* und nach Ausgabe.

**Beobachtete Seiten sind Korpusartikel (die Entscheidungen zu lebenden Quellen, offen benannt):**
Jede Seite, die Sie beobachten, wird außerdem als Artikel unter einer Quelle pro Ausgabe
(„Wikipedia (en)“) in Ihren Korpus aufgenommen, sodass sie in der **allgemeinen Suche, bei den Schlagwörtern und
in Wann×Wo×Wer wie jeder andere Artikel** erscheint. Die Entscheidungen, die die App für Sie trifft,
sichtbar gemacht: (1) Suche und Analysen sehen immer die **neueste Version**,
die der Tracker abgerufen hat, und die genaue Revisions-ID, der sie entspricht, wird
festgehalten; (2) der **vollständige Text jeder verfolgten Revision wird auf diesem
Rechner gespeichert** — frühere Versionen bleiben exakt rekonstruierbar (versionsgebundene
Analysen, kein Nachspielen von Diffs), zum ehrlich benannten Preis, dass der Speicherbedarf mit der Bearbeitungsaktivität
wächst; (3) der analysierte Text ist auf reinen Text reduzierter Wikitext — er wird nie
als der gerenderte Artikel ausgegeben. Alles bleibt lokal; der Änderungsverlauf
bleibt pro Seite verfügbar, und der Reiter **Lebende Quellen** zeigt ihn
([3.6b](#36b-lebende-quellen)).

**Das Speicherbudget des Strangs (standardmäßig 150 GB, Sie können es senken):** Der Wikipedia-Strang
hört auf, Text zu speichern, sobald die Gesamtmenge erreicht ist, die Sie im Einrichtungsassistenten beim ersten Start festgelegt haben (oder unter **Einstellungen →
Speicher**, neben der Rechnung gegen den freien Speicherplatz dieses Rechners). Der Standardwert ist
seit der Entscheidung vom 2026-09-29 **150 GB**, zuvor 20 GB; senken Sie ihn auf 20 GB oder auf jeden Wert
bis hinunter zu 1 GB, wenn die Festplatte klein ist. Eine Installation, die den Assistenten bereits durchlaufen hat,
behält den Wert, dem sie zugestimmt hat; eine, die den Assistenten nie gesehen hat, folgt dem neuen Standardwert,
bis Sie einen eigenen festlegen.

**Der Seitendurchlauf (aus, solange Sie ihn nicht einschalten):** Der Live-Stream erfährt immer nur
von Seiten, die jemand bearbeitet, sodass der größte Teil einer Enzyklopädie ihn nie erreicht. Wenn Sie
**Auch jeden Artikeltitel durchlaufen** ankreuzen (Einstellungen → Wikipedia, unter *Der Live-Bearbeitungsstream*),
werden alle Artikel der von Ihnen gewählten Ausgaben aufgelistet, 50 Titel pro Anfrage, eine
Anfrage nach der anderen, zwischen den eigenen Lesevorgängen des Streams, über mehrere Tage. Er speichert von jeder
Seite Titel, Größe, neueste Revision und Wikidata-ID, nie ihren Text, innerhalb desselben
Speicherbudgets, und er wird nie zu einer Seite gemacht, der der Stream vollständig folgt. Er
läuft nur, solange der Live-Stream läuft, über dieselbe Verbindung: Flugmodus oder
geschützter Modus ohne nutzbaren Proxy lassen ihn **warten** (er geht nie direkt), und ein
Wiki, das ihn bittet, langsamer zu werden, wird erst nach einer Pause erneut angefragt, die sich bis zu einer
Stunde verdoppelt. Nach einem Neustart setzt jede Ausgabe dort fort, wo sie aufgehört hat. Sein Fortschritt steht unter **Lebende
Quellen** und im Task-Manager.

**Warum der Durchlauf hinter dem ersten Abarbeiten des Streams warten kann.** Der Stream speichert, was er gehört hat, in
einem Abarbeitungsschritt alle 30 Sekunden; der Suchindex, der Abruf anderer geänderter Seiten und der Durchlauf laufen
in der Zeit *nach* jedem Abarbeitungsschritt. Ein Abarbeitungsschritt ruft den Text der verfolgten Seiten ab, die sich geändert haben,
und hinter einem Rückstau (ein Stream, der Stunden zurück fortgesetzt wurde) sind das Tausende höflicher Anfragen, daher
hat der Abarbeitungsschritt jetzt eine **Grenze von 20 Sekunden für das Abrufen von Texten**, aufgeteilt zwischen den Ausgaben
(die erste Ausgabe wechselt mit jedem Abarbeitungsschritt). Jede Änderung wird weiterhin festgehalten; ein Text, der nicht rechtzeitig
erreicht wird, wird als *zurückgestellt* gezählt, und **ein späterer Abarbeitungsschritt ruft ihn ab**: zuerst nie gespeicherte Seiten, dann
die am längsten ungeprüften (bis zu 200 Seiten pro Ausgabe pro Abarbeitungsschritt; `text_backlog` im Bericht des Abarbeitungsschritts
sagt, wie viele das Nachholen wartend *vorgefunden* hat, was nicht dasselbe ist wie abgerufen). Diese Seiten
werden vor den neuesten Änderungen der Ausgabe innerhalb ihres Zeitanteils versucht. Eine Seite, deren Abruf fehlgeschlagen ist oder
abgelehnt wurde, lässt das Nachholen 5 Minuten lang in Ruhe, damit eine Seite, die der Dienst wiederholt ablehnt, nicht
alle 30 Sekunden angefragt wird. Der Client
stellt eine Anfrage pro Sekunde, sodass ein Abarbeitungsschritt etwa zwanzig Texte abruft: Hinter Tausenden zurückgestellter
Texte dauert das Nachholen Stunden, nicht einen Abarbeitungsschritt. Die Grenze bestimmt, wann ein Abruf *beginnen* darf: Einer,
der bereits läuft, wird zuerst abgeschlossen (jeder Verbindungsaufbau und jeder Lesevorgang wartet bis zu 30 Sekunden), sodass ein Abarbeitungsschritt
etwas länger als 20 Sekunden dauern kann. Solange der Seitendurchlauf eingeschaltet ist, behält er 30% der Leerlaufzeit, sodass der Abruf anderer geänderter Seiten
sie nicht vollständig nutzen kann. Der Status (`/api/scheduler/status`, der Block `wiki_lane.service.drain`)
sagt, wo der Abarbeitungsschritt steht: die Phase (`hot-sets` oder `feeds`), die Ausgabe, wie lange er
schon in diesem Abarbeitungsschritt ist und wie viele Abarbeitungsschritte nacheinander fehlgeschlagen sind und warum.

**Das W in der oberen Leiste lesen.** Das W ist der Schalter des **Streams**, nicht der des Durchlaufs: Der
Durchlauf ist das Kästchen oben, und er läuft nur, solange der Stream läuft. Das kleine Zeichen in der
Ecke des W zeigt durch seine Form, was der Stream tut: Ein ausgefüllter Punkt bedeutet verbunden und empfangend;
ein Ring bedeutet *gewählt, aber nicht verbunden* (der Flugmodus hält ihn zurück, oder er wurde in dieser
Sitzung noch nicht gestartet); ein Ring mit Punkt bedeutet, dass er sich zu verbinden versucht, dabei scheitert und es von selbst erneut versucht; ein Strich bedeutet pausiert;
ein Kreuz bedeutet gestoppt. Fahren Sie mit der Maus darüber, um es in Worten zu lesen, einschließlich der Angabe, ob der Seitendurchlauf eingeschaltet ist. Ein Klick
auf einen Ring **startet** den Stream (Sie bestätigen einmal, dass Sie online gehen); ein Klick auf einen Punkt oder einen Ring
mit Punkt **pausiert** ihn; Umschalt+Klick stoppt ihn. Einstellungen → Wikipedia zeigt dieselben zwei Zeilen
in Worten über den Ausgaben. Beide werden neu gezeichnet, wenn Sie online oder offline gehen und wenn Sie den Durchlauf
ankreuzen oder das Kreuz entfernen.

**Die anderen geänderten Seiten (aus, solange Sie es nicht einschalten):** Der Live-Stream speichert
den Text der Seiten, denen er folgt, und zählt nur die Änderungen, die er zu jeder
anderen Seite meldet. Wenn Sie **Auch den Text anderer geänderter Seiten abrufen** ankreuzen (Einstellungen →
Wikipedia, neben dem Kästchen des Durchlaufs), wird auch der neueste Text dieser anderen Seiten abgerufen,
50 Seiten pro Anfrage, die Seite, die am längsten gewartet hat, zuerst. Eine Seite, die zehnmal bearbeitet wurde,
während sie wartete, kostet einen einzigen Abruf, und zwar ihres aktuellen Stands. Die App behält von jeder Seite den
**neuesten und den vorherigen** Text, und eine später gelöschte Seite behält den Text, den sie hatte. Diese
Texte **bleiben in der eigenen Datei des Strangs, nicht in Ihrem Korpus**; das Suchfeld findet sie
(siehe *Durchsuchen, was der Strang speichert*, unten). Sie enden, wenn die Datei des Strangs **90% ihres Speicherbudgets** belegt, damit der
Rest für die Seiten bleibt, denen der Stream folgt; dieser Anteil ist ein vorgeschlagener Standardwert, keine
Entscheidung, und Lebende Quellen zeigt ihn an. Er läuft nur, solange der Live-Stream läuft, über
dieselbe Verbindung und mit denselben Wartezeiten wie der Durchlauf: Flugmodus oder geschützter
Modus ohne nutzbaren Proxy lassen ihn warten (er geht nie direkt), und ein Wiki, das ihn bittet,
langsamer zu werden, wird erst nach einer Pause erneut angefragt, die sich bis zu einer Stunde verdoppelt.

**Ein Absturz oder ein Update verliert den Lauf nicht.** Alles, was der Strang speichert, wird in
kleinen Alles-oder-nichts-Schritten geschrieben, sodass ein Absturz (oder das Beenden der App) höchstens den laufenden Schritt verliert; der
Durchlauf setzt an seinem Lesezeichen fort und der Stream an der zuletzt gespeicherten Position. Was hingegen
anhält, ist der Strang selbst: Die App startet immer **offline**, daher wird nach einem Neustart nichts
abgerufen, bis Sie mit der Flugmodus-Schaltfläche wieder online gehen; das setzt den Lauf fort, wenn er eingeschaltet war, und lässt ihn aus, wenn er aus war (die Startseite zeigt eine Zeile, solange der Lauf wartet). Während er wartet, geht nichts verloren
(der eigene Verlauf des Streams reicht etwa eine Woche zurück). Lebende Quellen → Wikipedia → Livestream
zeigt **Bisheriger Lauf** (Stunden, in denen diese Installation etwas gespeichert oder angefragt hat,
über Neustarts hinweg gezählt, mit der Anzahl der Stopps) und, wenn der Strang verstummt ist, eine
Zeile **Gestoppt** mit Dauer und Beginn. Dieselben Zahlen stehen im Bericht des Soak-Fensters
als `wiki_lane.run`. Ein Stopp besagt, dass der Strang drei oder mehr Stunden lang kein Lebenszeichen gezeigt hat,
nicht warum: Ein Absturz, ein Update, der Flugmodus und eine geschlossene App sehen gleich aus.

**Durchsuchen, was der Strang speichert:** Der Strang führt einen Suchindex über die Texte, die er
speichert, in derselben Datei und innerhalb desselben Speicherbudgets. Der **neueste** Text einer geänderten Seite
wird vollständig indexiert, einschließlich des Titels. Jede **ältere Version** (der vorherige Text einer
geänderten Seite und jede Version einer Seite, der der Stream folgt, außer
der neuesten, die bereits Ihr Korpusartikel ist) wird über die **Zeilen indexiert, die eine spätere
Bearbeitung entfernt hat**: Der Rest steht in der neueren Version, wo er bereits gefunden wird.
Eine Suche, deren Wörter teils in behaltenen und teils in entfernten Zeilen stehen, findet daher
keine der beiden Versionen, und jede Liste dieser Treffer sagt das. Der Index wird aufgebaut, während der
Live-Stream läuft, vor den Abrufen und höchstens in der Hälfte ihrer Leerlaufzeit, und
eine Suche sagt, wie viele Texte noch auf ihn warten; ein Text, der nicht gelesen werden kann,
wird zurückgestellt und beim nächsten Start des Strangs erneut versucht. Chinesisch, Japanisch und
Arabisch werden genau wie im eigenen Index Ihres Korpus zerlegt und vereinheitlicht, und Wörter auf Hindi und
Bengalisch bleiben ganz. Im Suchfeld (Ctrl/⌘-K) werden diese Treffer unter
**Auf diesem Rechner gespeicherte Wikipedia-Texte** aufgeführt, neben den Treffern Ihres Korpus und nie in diese
eingereiht, jeder mit Angabe seiner Ausgabe, um welchen Text es sich handelt (den neuesten oder
vorherigen Text einer geänderten Seite oder eine frühere Version einer Seite, der der Stream folgt) und seines Datums.
Wenn Sie einen öffnen, sehen Sie den Text dieser Version, wo er gespeichert ist, und seine vollständige Adresse auf
Wikipedia; **Zum Korpus hinzufügen** fügt genau diese Version als eigenen Artikel hinzu, datiert auf den Zeitpunkt, zu dem
das Wiki sie erstellt hat, und sagt es, wenn Ihr Korpus sie oder dieselben Wörter bereits enthält,
statt sie doppelt zu speichern. Auf keinem anderen Weg gelangt etwas aus dem Strang in Ihren Korpus.
Die Seite **Erkunden** listet dieselben Treffer in einem eigenen Abschnitt unterhalb der Ergebnisse
Ihres Korpus auf, jeweils mit der passenden Textstelle und einer eigenen Schaltfläche **Zum Korpus hinzufügen**.
Darüber steht, was durchsucht wurde: nur die Texte, die der Wikipedia-Strang
auf diesem Rechner speichert, nie Wikipedia selbst, mit den Seiten und Ausgaben, aus denen sie
stammen, wie viele Texte noch auf den Index warten und ob der Abruf anderer
geänderter Seiten ausgeschaltet ist. Eine leere Liste bedeutet also, dass die Texte des Strangs Ihre
Wörter nicht enthalten, nicht, dass Wikipedia sie nicht enthält. Die Versionen, die **Jetzt verfolgen** (Einstellungen → Wikipedia)
für beobachtete Seiten speichert, sind ebenfalls in dieser Suche: Sie bleiben in der Datenbank Ihres Korpus,
und der Index des Strangs, in seiner eigenen Datei, liest sie auf dieselbe Weise (jede ältere Version über
die Zeilen, die die nächste gespeicherte Version entfernt hat, die neueste vollständig, sofern Ihr Korpusartikel
nicht bereits diese Version ist). Sie werden unter derselben Überschrift gefunden, gekennzeichnet als
vom Seiten-Tracker gespeichert, und **Zum Korpus hinzufügen** fügt genau diese Version hinzu wie jede
andere; die Suche sagt, wie viele verfolgte Seiten sie gelesen hat. Eine Seite, der Sie sowohl folgen als auch die Sie verfolgen, kann
eine Version einmal pro Speicher auflisten: Die beiden Speicher werden getrennt gelesen, und keiner hängt vom
anderen ab. Heruntergeladene Dumps sind nicht in dieser Suche: Ihr Text
wird in der Wikipedia-Gruppe des Suchfelds gefunden. Eine Abfrage wird in beiden Listen gleich gelesen (`salt*`,
`NEAR(salt works, 5)`, `title:salt`), aber die Filter, die Artikel beschreiben (die
Felder Quelle, Sprache und Zeit sowie `source:`, `author:`, `url:`, `tag:` und
`title:=`), erreichen diese Texte nicht, und der Abschnitt sagt das, sobald einer gesetzt ist.
Exporte, das Analysefenster und die Massenaktionen arbeiten mit Ihrem Korpus; ein Wikipedia-Text
wird einbezogen, sobald Sie ihn hinzufügen.

**Ein Objekt über die Ausgaben hinweg und die meistaufgerufenen Seiten** (Lebende Quellen → Wikipedia, ganz
unten). Zwei Ansichten, die nur lesen, was dieser Rechner bereits gespeichert hat; keine von beiden ruft etwas ab.
*Ein Objekt über die Ausgaben hinweg*: Geben Sie ein Wikidata-Objekt ein (Q42) oder drücken Sie einen der Vorschläge (die
Objekte, zu deren Seiten der Stream diese Woche die meisten Änderungen festgehalten hat), und eine Tabelle zeigt für
jede Ausgabe, der Sie folgen, die Seite dieser Ausgabe, ihre **Größe in Bytes Wikitext** (einmal gelesen,
als der Seitendurchlauf die Seite erreicht hat), wann sie gelesen wurde, und die **Änderungen, die dieser Rechner
in den letzten sieben Tagen festgehalten hat**. Eine Ausgabe ohne Seite sagt, warum: Der Durchlauf ist für sie
nicht gelaufen, hat sie noch nicht abgeschlossen (und wie weit er gekommen ist, sodass das Objekt dort noch sein kann), oder hat sie abgeschlossen
und keine gefunden. Die Änderungszahl ist das, was der Live-Stream auf diesem Rechner festgehalten hat; für eine Ausgabe, zu der er
nichts festgehalten hat, steht dort „unbekannt“, denn das ist nicht dasselbe wie null. Der Balken neben einer Größe ist diese Größe im Verhältnis zur größten auf dem Bildschirm,
ab null; sonst wird nichts berechnet, und die Ausgaben sind eigenständige Artikel, keine
Übersetzungen. Der Seitendurchlauf ist aus, bis Sie ihn einschalten (Einstellungen → Wikipedia), daher gibt es auf einer
Instanz, die noch keinen Durchlauf gemacht hat, noch nichts zu vergleichen, und die Tabelle sagt das.
*Meistaufgerufene Seiten neben Ihrem Korpus*: die eigene Liste der Quelle mit den meistaufgerufenen Seiten ihres
letzten Tages (Rang und Aufrufzahl, wie die Quelle sie angegeben hat; die ersten fünfzig Zeilen werden behalten), jede neben
der Anzahl der Artikel in **Ihrem Korpus**, die den Titel als Wortgruppe erwähnen, veröffentlicht an diesem
UTC-Tag und in den sieben Tagen, die mit ihm enden. Es ist **ein einzelner Tag, keine Zeitreihe**: Die Liste wird
jeden Tag überschrieben, und es wird kein Aufrufverlauf pro Seite gespeichert. Die Zählungen sind die Ihres Korpus,
also dessen, was dieser Rechner gesammelt hat, nicht der Presse; ein Titel kann mehrdeutig sein oder in einer
anderen Sprache anders geschrieben werden; aus Wikipedia stammende Artikel und Artikel in Quarantäne werden nicht gezählt;
eine Zeile, die die Zählung innerhalb ihres Zeitlimits nicht erreicht hat oder deren Titel keine Wörter enthält, die der Suchindex abgleichen kann (ein bloßes „-“), zeigt „nicht gezählt“, mit dem Grund im Hover-Text; die Vorschläge lesen nur die 400 in dieser Woche am häufigsten geänderten Seiten. Die beiden Zahlen stehen
nebeneinander und werden nie kombiniert.

Umfangreiche **Offline-Volltext-Grundlagen** (Dumps ganzer Ausgaben) sind *davon getrennt* und befinden sich
unter **Einstellungen → Wikipedia** — für die Änderungsverfolgung brauchen Sie sie nicht. Siehe
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

**Einen heruntergeladenen Dump lesen (offline):** Neue Dump-Downloads verwenden die
*Multistream*-Form, und der kleine zugehörige Index wird mit heruntergeladen — dieses
Paar macht den Dump durchsuchbar. Wählen Sie unter **Einstellungen → Wikipedia → Eine Seite aus einem heruntergeladenen Dump lesen**
eine bereite Ausgabe, geben Sie einen Seitentitel ein, und die App durchsucht
den Index, entpackt einen kleinen Block an seinem Byte-Offset und zeigt den
**rohen Wikitext** der Seite — vollständig auf diesem Rechner, mit Anzeige der Suchstatistik.
Was Sie lesen, ist ein *Schnappschuss zum Stand des Dump-Datums*, nicht der Live-Artikel; eine
Titelübereinstimmung ohne Beachtung der Groß-/Kleinschreibung wird angeboten und gekennzeichnet. Ältere Single-Stream-Dateien
erlauben keinen wahlfreien Zugriff — die App sagt das und schlägt einen erneuten Download vor.
Die **Sprachliste für Dumps ist auf die Sprachen der App beschränkt** (die 12 Oberflächensprachen
plus die Korpussprachen, die die Analysewerkzeuge unterstützen); die Ausgabenauswahl für beobachtete Seiten
oben behält die vollständige Liste.

### 3.7a Regierungen

**Wozu er dient:** Der Seitenleisten-Reiter **Regierungen** (der Code-Anker bleibt `law`, die
Beschriftung lautet „Regierungen“) sammelt amtliche Daten pro Land und verfolgt, wie sich das **Recht**
ändert. Er hat sechs Unterreiter:

- **Länder** — **amtliche Statistiken** pro Land von der Weltbank (BIP,
  Bevölkerung, Lebenserwartung, Arbeit, öffentliche Finanzen + gängige Indizes). **Standard-Länderdaten
  laden** ruft sie ab (online, mit Zustimmungsabfrage). Jeder Wert ist eine vom Datenproduzenten
  veröffentlichte Zahl, **nie eine Glaubwürdigkeitsbewertung**; ein **fehlender Wert ist eine veröffentlichte Lücke,
  nicht null**; Produzenten werden angezeigt, **nie gemittelt**. Jede Zahl trägt ihre Einheit, und
  der Hover-Text jedes Indikators erklärt, was er misst — zwei, die wie Fehler aussehen und keine sind:
  Mobilfunkverträge können 100 pro 100 Personen übersteigen (Menschen haben mehrere SIM-Karten), und die Brutto-Einschulungsquote
  kann 100% übersteigen (sie zählt Wiederholer und Schüler über dem Regelalter mit).
- **Vergleichen** — zwei Länder nebeneinander, jeder Indikator als ausgerichtete Zeile. Das ist eine
  **Darstellung**, keine Berechnung: Sie zeigt die jeweils neueste veröffentlichte Zahl jedes Landes und
  das Jahr, zu dem sie gehört, und wo ein Land keine Zahl hat, steht in der Zelle eine **Lücke**.
  Sie zieht nie voneinander ab, ordnet nie in eine Rangfolge und bewertet das Paar nie — den Vergleich ziehen Sie selbst.
- **Gruppen** — Aggregate und Staatenbündnisse, in zwei **Ansichten**, zwischen denen Sie umschalten:
  - *Veröffentlicht* zeigt die Aggregate, die der Produzent selbst veröffentlicht („High income“,
    „Sub-Saharan Africa“, „European Union“ der Weltbank usw.). Zuerst öffnet sich eine kuratierte Auswahlliste;
    **Alle anzeigen** erweitert sie auf den vollständigen Satz. Das sind die eigenen Zahlen des Produzenten,
    nicht unsere. **Weltbank-Regionen sind keine Kontinente** — „Sub-Saharan Africa“
    schließt Ägypten, Libyen, Tunesien, Algerien und Marokko aus, die zu ihrer Region Middle East &
    North Africa gehören, daher hat diese Ansicht **überhaupt keine Zahl für den afrikanischen Kontinent** und sagt
    das, statt eine zusammenzusetzen, die amtlich aussähe.
  - *Berechnet* (Computed) aggregiert die Mitgliedsländer selbst und zeigt **mehrere Verfahren
    nebeneinander** (bevölkerungsgewichteter Mittelwert, einfacher Mittelwert, BIP-gewichtet, Median und eine Summe,
    wo eine sinnvoll ist), damit Sie sehen, wie stark das Ergebnis von der Methode abhängt,
    statt eine einzige Zahl vorgesetzt zu bekommen. Nichts wird in eine Rangfolge gebracht, und kein Verfahren wird als das
    beste bezeichnet. Eine **Summe** wird nur für Indikatoren angeboten, bei denen das Aufsummieren etwas bedeutet
    (Bevölkerung, BIP, Erwerbspersonen); für einen Prozentsatz, eine Rate oder eine Lebenserwartung wird sie
    **mit angezeigtem Grund verweigert**, denn das Addieren von Prozentsätzen ergibt eine Zahl, die niemand
    gemessen hat. Jede Zahl gibt ihre **Abdeckung** und ihre **Streuung** an (min/max/n) —
    eine Schlagzeile zu einem Staatenbündnis, die eine zehnfache Spanne verbirgt, ist wahr und irreführend, deshalb wird die Spanne
    mitgeführt. Wo Mitglieder fehlen, wird das Aggregat **standardmäßig verweigert**; Sie können
    es trotzdem veröffentlichen, und das Ergebnis wird dann als unvollständig gekennzeichnet und nennt genau, welche
    Mitglieder fehlen. Die Mitgliedschaft in Staatenbündnissen ändert sich im Lauf der Zeit (BRICS hatte bis
    2024 fünf Mitglieder; die EU verlor 2020 das Vereinigte Königreich), daher gibt jede Zahl für ein Staatenbündnis den **Mitgliedschaftsstand**
    an, für den sie berechnet wurde, und ein Bündnis, dessen Mitgliederliste wir noch nicht belegen können, sagt
    das klar, statt eine Zahl anzuzeigen.
- **Karte** — eine **ooMap-Choroplethenkarte** eines wählbaren Indikators mit einer Auswahl für Jahr/Verlauf;
  klicken Sie auf ein Land, um seine Details im Unterreiter Länder zu öffnen.
- **Recht** — verfolgt das **Recht** (Gesetze, Amtsblätter, Register zu geistigem Eigentum) aus amtlichen Quellen
  weltweit und beobachtet, wie es sich im Lauf der Zeit ändert (die *Änderungen sind die Daten*). Ein **Recherche-Spiegel**,
  nie die maßgebliche Quelle und **keine Rechtsberatung** — jeder Eintrag verweist
  zurück auf sein amtliches Verkündungsblatt. Ein weltweiter Katalog echter amtlicher Quellen
  (`legislation.gov.uk`, EUR-Lex, Légifrance, govinfo, WIPO Lex, USPTO, EPO, …) ist
  standardmäßig vorbelegt. **Änderungen jetzt verfolgen** ruft die verfolgten Dokumente über den ethischen
  Abrufer ab, speichert einen Ausgangsstand und danach ehrliche **Diffs** mit einer Markierung für große Änderungen; **Markierte
  Gesetzesänderungen** listet sie auf (Rechtsraum · Titel · Δ Bytes · Gründe), mit dem Diff und
  einem Link zur amtlichen Quelle. Das Briefing zeigt außerdem eine **Mustergesetzgebungs**-Spur,
  wenn nahezu identischer Text in mehreren Rechtsräumen auftaucht.
- **Statistik** — das Verzeichnis der Produzenten und die rohen, mit Stand versehenen Zahlen hinter den anderen
  Unterreitern, dazu **Reihen zum Korpus hinzufügen** (siehe unten).

**Statistiken in der gewöhnlichen Suche.** Eine Zahl, die niemand finden kann, ist nicht wirklich in Ihrem Korpus,
daher kann jede **Reihe** — ein Indikator für ein Land über alle gespeicherten Jahre — auch
als gewöhnlicher **Artikel** angelegt werden. Sie nimmt dann die normalen Wege: Die Suche findet
„Lebenserwartung Frankreich“, ihre Wörter gelangen in die Trends und die Spuren, und sie erscheint im Feed
wie alles andere, ohne dass Sie sich ein besonderes Suchfeld merken müssen. Vier Dinge sind wissenswert:

- Es gibt **einen Artikel pro Indikator pro Land**, nicht einen pro Revision. Eine korrigierte Zahl für 1991
  aktualisiert den vorhandenen Artikel, statt eine Beinahe-Kopie hinzuzufügen, sodass ein erneutes Ausführen des
  Auftrags nichts kostet und nichts hinzufügt.
- Die Artikel sind **als das gekennzeichnet, was sie sind** — die Quelle lautet „Official statistics
  (World Bank)“ und die Herkunftsklasse ist `statistics` —, sodass Sie sie in jeder Ansicht ein- oder
  ausfiltern können und die Koordinationsprüfungen, die nach vielen Medien suchen, die einander wiederholen,
  Tausende gleich aufgebauter Zeilen nicht für Übereinstimmung halten können.
- Der Text nennt bewusst **nur den Gegenstand und die Zahlen**, wobei eine **veröffentlichte Lücke
  als Lücke angezeigt** wird. Den Namen des Produzenten und den maschinellen Reihencode in jedem
  der ~9.800 Artikel zu wiederholen, brachte „World Bank“ ganz an die Spitze der Schlagwort-Rangliste
  des gesamten Korpus — Gerüst, das vor dem rangierte, worum es in Ihrem Korpus tatsächlich geht —, deshalb geschieht das nicht.
- Um sie **nach Produzent** statt nach Gegenstand zu finden, filtern Sie nach der Quelle oder dem
  Tag `statistics`; um eine **nach Reihencode** nachzuschlagen, verwenden Sie den Unterreiter Statistik, der
  exakt antwortet statt über einen Textabgleich.

Das Anlegen ist ein Hintergrundauftrag, den Sie unter **Regierungen → Statistik** starten; er ist
fortsetzbar, abbrechbar und hält die Erfassung nicht auf.

### 3.8 Beweise & Verwahrung

*(Erreichbar über **Einstellungen → Erweitert → Sicherheit** — „Verwahrungskette“ ist die Überschrift des Bereichs; er hat
die Seitenleiste bei der Umgestaltung nach dem Prinzip „Inhalt zuerst“ verlassen.)*

**Wozu er dient:** einem skeptischen Dritten — offline — beweisen, dass Ihr Korpus
*dieses* Element mit *diesem* Inhalt zu *diesem* Zeitpunkt enthielt und dass der Eintrag sich seitdem
nicht verändert hat. Er ist **kein** Whistleblower-/SecureDrop-System; eine „Quelle“ ist hier ein
Nachrichtenmedium, kein vertraulicher Informant.

Der Bereich hat drei Teile:

- **Einstellungen & Status** (Settings & status). Schalter für **Post-Quanten-Signaturen** (eine ML-DSA-/
  FIPS-204-Signatur zusätzlich zu Ed25519), **OpenTimestamps-Verankerung** (Verankerung in
  Bitcoin als unabhängiger Zeitnachweis), **Automatisch beim Erfassen protokollieren** (bei jeder erfolgreichen Erfassung einen signierten
  Eintrag anhängen) und eine Bezeichnung **Standardakteur**. Entscheidend ist, dass der
  Status immer den **tatsächlich wirksamen** Zustand zeigt, nicht nur Ihren Wunsch: Wenn Sie PQC
  oder OpenTimestamps aktivieren, die zugehörige Bibliothek aber nicht installiert ist, steht dort *„angefordert,
  Bibliothek nicht installiert“*, und es bleibt bei Ed25519 bzw. nur lokal — **es zeigt nie ein grünes
  Licht, das es nicht belegen kann.** Auch der Schlüsselschutz wird angezeigt (`aes256gcm-scrypt`, wenn eine Passphrase
  vorliegt, aus `OO_KEY_PASSPHRASE` oder der Datenbank-Passphrase; sonst `plaintext-0600`; und `pkcs8-pbkdf2`
  oder `plaintext-0600` bei vorliegender Passphrase für einen Schlüssel aus der Zeit vor 0.6, der noch nicht neu verpackt werden konnte;
  das gibt an, was seine Datei wirklich enthält).
- **Kette anzeigen & prüfen** (View & verify chain). Geben Sie eine Element-ID ein (z. B. `article:42`), um **Kette anzeigen**
  (Reihenfolge, Aktion, Akteur, Zeit, Signaturalgorithmus), **Prüfen** (prüft Kettenglieder,
  Hashes, Signaturen und Zeitstempel erneut) oder **Paket exportieren** (eine
  offline überprüfbare Datei) zu wählen.
- **Merkle-Wurzel verankern** (Anchor Merkle root). Fügen Sie eine Merkle-Wurzel ein, um sie über den konfigurierten Anbieter zu verankern.

> **In der App angezeigte Datenschutzwarnung:** Eine Verankerung in einer öffentlichen Blockchain veröffentlicht einen
> Hash dauerhaft und gibt Ihre IP-Adresse/Ihr Timing gegenüber den Betreibern der Kalenderserver preis. Ziehen Sie
> lokal + OpenTimestamps finanzierten On-Chain-Wallets vor; leiten Sie über Tor (`HTTPS_PROXY`),
> wenn Sie Anonymität brauchen; oder bleiben Sie rein lokal (der Standard gibt nichts preis).

**OpenTimestamps und Flugmodus.** Im OpenTimestamps-Modus erhält ein Erfassungseintrag, dessen
Übermittlung der Netzwerk-Notschalter abgelehnt hat (ein Stopp während der Sammlung), nicht stattdessen einen
rein lokalen Nachweis, denn dieser Nachweis wäre dauerhaft: Der Eintrag wird geschuldet
und später geschrieben, als verspätet markiert, mit seiner Verankerung. Die Warteschlange der geschuldeten Einträge hat keine Größenbegrenzung, und
das Ende jedes Sammeldurchlaufs schreibt höchstens 200 davon, jeden Eintrag mit bis zu drei
Übermittlungen an Kalenderserver, die erfolgen, während das Verwahrungsprotokoll zum Schreiben gesperrt ist. Ein großer Rückstau
verlangsamt daher eine Zeit lang das Ende der Sammeldurchläufe, sobald Sie wieder online sind.
Solange der Schalter noch aktiv ist, bricht das Schreiben geschuldeter Einträge („Eintragen, als verspätet markiert“ oder
`POST /api/custody/reconcile`) bei der ersten Ablehnung ab und sagt, dass der Notschalter sie abgelehnt
hat; die Einträge bleiben geschuldet. Eine reine Lückenprüfung antwortet weiterhin, und ihr Block `drained`
meldet `refused_offline`.

Prüfen Sie ein Paket an beliebiger Stelle, ohne diese App:

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
python scripts/verify_evidence.py bundle.json [signer_pubkey]
```

Der vollständige Entwurf — und genau, was jeder Mechanismus beweist und was er **nicht** beweist — steht
in [`docs/USER_MANUAL.md`](USER_MANUAL.md). *(Eine geplante Überarbeitung, die
diesen Reiter narrensicher und weitgehend automatisch machen soll, ist festgehalten in
[`docs/ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).)*

### 3.8a Quellenintegrität

*(Der Quellenintegritäts-Desk ist umgezogen nach **Einstellungen → Erweitert → Sicherheit → „Quellenintegritäts-Desk
öffnen“**; Koordination wird jetzt außerdem automatisch angezeigt — als Spuren auf der Startseite, in der Ansicht **Verwandt**
des Analysefensters und als eingebettete Kennzeichen „N Kopien = eine Stimme“ in Artikellisten
und im Lesemodus.)*

**Wozu er dient:** die *Struktur* hinter Ihren Quellen sehen — und selbst entscheiden,
wessen Signal zählt. Es gibt bewusst **keine Vertrauensbewertung**; eine einzige Zahl würde
Voreingenommenheit festschreiben und kleine, ausländische, neue oder dissidente Quellen zum Schweigen bringen. Vollständige Anleitung:
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

- **Anti-Verstärkung (vorschlagen → Sie entscheiden):** *Nach Koordination suchen* findet
  Fluten nahezu identischer Inhalte, die im Gleichschritt über viele Quellen veröffentlicht werden, mit ihren Belegen
  (gemeinsamer Text, Zeitpunkt, Host). Standardmäßig werden sie nur **annotiert** — nie stillschweigend
  zusammengefasst. **Zusammenfassung anwenden** zählt ein Netzwerk als **eine Stimme** (in jeder Zählung, die
  Konsens misst); es bleibt markiert, und **Aufklappen (rückgängig)** stellt die ursprüngliche, gleichgewichtete Ansicht
  exakt wieder her. Ohne Ihr Zutun wird nie etwas zusammengefasst. Echokammer-Spuren auf der Startseite
  bieten dieselbe Aktion.
- **Quellenprofil:** ein Bereich gemessener Dimensionen — Koordination, Neuheit
  (stammt von ihr vs. gibt wieder), Ausstoßkapazität, Transparenzfakten, Erfolgsbilanz —, jede mit
  ihrer Methode und ihrem Vorbehalt, und **ohne zusammengesetzte Bewertung**.
- **Geteilte Anmerkungen (Web of Trust):** Verfassen Sie beschreibende, anfechtbare Fakten über
  Quellen (Eigentümer, Ausrichtung, Koordination, Korrekturen); **exportieren** Sie sie als
  **signiertes** Paket; **importieren** Sie die Pakete, denen Sie vertrauen möchten. *Wer hat was gesagt?* zeigt
  jede Zuschreibung zu einer Quelle und macht **abweichende Meinungen** sichtbar — nie zu einer Zahl gemittelt.
  Siehe [`docs/USER_MANUAL.md`](USER_MANUAL.md).

### 3.9 Einstellungen

**Wofür es da ist:** Präferenzen, die Erfassungsflächen und die Wartung — gegliedert
in **neun** Bereiche über eine Unternavigation: **Grafik · Allgemein · Karten · KI · Wikipedia ·
OpenStreetMap · Agenda · Daten & Sicherung · Erweitert**.
Sie öffnen die Einstellungen über die **Schaltfläche unten in der Seitenleiste**; auch die Befehlspalette
springt direkt hierher. Alles wird lokal gespeichert; keine Telemetrie.

Für den Alltag brauchen Sie nichts aus **Erweitert**: Die Erfassungstechnik, die Quellenverwaltung, die
Schlagwortpflege, das Verzeichnis der Statistikproduzenten, der Katalog der Kalender-Feeds, der
Diagnoseplatz, **Sicherheit** und **Deinstallieren und löschen** liegen alle dort, in **eingeklappten Abschnitten, die
ihre Daten erst laden, wenn Sie einen öffnen** (allein der Quellenkatalog kann Zehntausende
von Zeilen enthalten). Sicherheit war früher ein eigener Unterreiter; jetzt ist es der vorletzte Abschnitt von Erweitert,
und die beiden unumkehrbaren Aktionen — **Notfall-Löschung** und **App deinstallieren** — sind
in einen eigenen Abschnitt (**Deinstallieren und löschen**) ausgelagert, sodass keine von beiden versehentlich erreicht werden kann,
während Sie etwas über Verschlüsselung lesen. Bei keinem der beiden Umzüge ging etwas verloren: Jedes Bedienelement,
das auf dem Unterreiter Sicherheit war, ist noch da, unter denselben Überschriften. **Sammeln** und **Quellen** sind
oben beschrieben ([3.2](#32-sammeln-unter-einstellungen--erweitert--erfassung),
[3.3](#33-quellen-unter-einstellungen--erweitert--quellen)) und werden über Erweitert erreicht;
**Wikipedia** ([3.7](#37-wikipedia-unter-einstellungen--wikipedia)) behält einen eigenen Bereich.
Amtliche **Zahlen** stehen hier überhaupt nicht — sie sind Daten und liegen daher unter
**Regierungen → Statistik**.

- **Grafik (Erscheinungsbild):** Designs, Akzentfarbe, Dichte, **Schriftart**
  und Seitenleiste ausgeklappt/eingeklappt. (Es gibt keinen Schieberegler für die Textgröße: Er skalierte nur das
  Wurzelelement, von dem im Stylesheet fast nichts erbte, und bewirkte daher nichts.
  Verwenden Sie den Zoom Ihres Browsers — er skaliert alles, auch die Teile, die ein nur auf das Wurzelelement wirkender
  Regler nie erreichen konnte.) Dieser Bereich enthält auch die Galerie **Alternative Oberflächen**
  (markiert als *Experimentell*): acht optionale Oberflächen — **Aurora, Atlas, Command, Field,
  Focus, Terminal, Canvas, Editorial** — über denselben Daten und mit denselben Ehrlichkeitsgarantien;
  wenn Sie eine auswählen, wird die Seite neu geladen, um sie anzuwenden. (Die frühere schwebende Schublade „Anpassen“ ist
  jetzt dieser vollwertige Bereich.)
- **Karten (Spuren auf der Startseite):** jeder Spur-Produzent, den die App ausführen kann, gruppiert nach seiner Familie
  (*Steigend · Überdeckt erzählt · Unterbelichtet · Untersuchenswert · Rahmung prüfen · Weiter beobachten ·
  Kontext · Datenintegrität*). Schalten Sie einen davon aus, erscheint er nicht mehr — das ändert nichts
  an den Artikeln selbst, nur daran, welche Hinweise Ihre Startseite erreichen. Wo eine Spur
  Schwellenwerte hat, sind diese jetzt sichtbar und einstellbar, jeweils mit einem angegebenen **sicheren Bereich**, einer
  einzeiligen Notiz dazu, was eine Änderung bewirkt, und einem **Zurücksetzen**. Sie können eine Spur jederzeit
  *strenger* machen; die Untergrenzen gibt es, damit eine Spur nie mehr behaupten kann, als ihre Belege
  tragen — die Prüfung auf Überflutung zum Beispiel geht nicht unter die Schwelle p<0.05,
  weil der Test darunter einen echten Anstieg nicht mehr von gewöhnlicher Schwankung unterscheiden kann. Jeder
  Wert außerhalb eines Bereichs wird korrigiert **und gemeldet**, nie stillschweigend angepasst.
- **Einstellungen (Allgemein):** **Design** (System/Dunkel/Hell), **Sprache** und **Standard-Suchergebnisse**.
- **Schlagwort-Filterung (Erweitert → Schlagwörter):** „Dumme“ Funktionswörter (der, du, nicht, …) werden durch eine
  eingebaute mehrsprachige Stoppwortliste entfernt. Passen Sie sie an: Legen Sie die **Minimale Schlagwortlänge** fest, lassen Sie
  **Rein numerische Begriffe verwerfen**, schalten Sie die eingebaute Stoppwortliste ein oder aus und pflegen Sie eine Liste
  **Ausgeschlossene Schlagwörter** (eines pro Zeile oder durch Kommas getrennt). Ein Ausschluss blendet einen Begriff
  überall aus, ist aber umkehrbar — gespeicherte Nennungen bleiben erhalten. (Sie können auch neben jedem Schlagwort
  in Einblicke auf ✕ klicken.)
- **Wikipedia-Offline-Basislinien:** Wählen Sie eine **Sprachausgabe** aus einer **flachen Liste**
  (zuerst Ihre Oberflächensprachen, dann die größten Ausgaben); jede Option beginnt mit dem
  **einheimischen Namen** (Autonym) — Ausgaben richten sich nach Sprachen, nicht nach Ländern, daher gibt
  es keine Gruppierung nach Kontinenten. Jede Ausgabe, für die ein Dump verfügbar ist, zeigt eine **ungefähre Größe direkt
  in der Liste** (`~X GB`, aus einer mitgelieferten, datierten Tabelle — kein zusätzlicher Netzwerkzugriff), damit Sie
  vor dem Herunterladen abwägen können; die genaue Größe wird beim Start des Downloads gelesen. **Herunterladen** lässt sich
  fortsetzen (Pausieren/Fortsetzen + eine Fortschrittstabelle). Diese Offline-Dumps sind groß und
  optional und dienen nur dem Offline-Lesen und -Suchen — die Live-Änderungsverfolgung (der
  Wikipedia-Reiter) braucht sie nicht.
- **KI (lokales LLM):** Ein Kasten **Lokale KI einrichten** ganz oben nennt den gesamten verbleibenden
  Plan an einer Stelle — welches Backend dieser Rechner verwenden wird (vLLM, wo eine dedizierte
  NVIDIA-GPU es bedienen kann, sonst Ollama), was noch installiert werden muss und die
  Downloadgrößen — und führt ihn mit **einer Schaltfläche** nach **einer einzigen** Zustimmung aus. Er blendet
  sich aus, sobald nichts mehr zu tun ist; die Bedienelemente für die einzelnen Komponenten darunter sind
  unverändert, sodass Sie jeden Schritt weiterhin selbst ausführen können. Darunter: das aktive Backend
  und **warum** es gewählt wurde, installierte Modelle und ein kuratierter, datierter Katalog, ein Modell
  **herunterladen** (ein **eingereihter** Download-Auftrag — einer nach dem anderen, abbrechbar, mit live angezeigtem Byte-
  Fortschritt; die Bytes laufen über das Clearnet über den Ollama-Prozess, **nicht** über Tor — das wird
  bei der Zustimmungsabfrage gesagt), eines **entfernen** und das **aktive Modell** festlegen.
  Die **Hardware-Eignung** (Hardware suitability) wird einmal, hier, angegeben, zusammen mit dem, was sie für Sie bedeutet: Lokale
  Inferenz wird standardmäßig nur unterhalb einer Untergrenze verweigert (weniger als 4 CPU-Kerne oder weniger
  als 6 GB RAM, ohne Beschleuniger); der Betrieb ohne dedizierte GPU, auf einer
  Karte mit wenig VRAM oder auf einem kleinen Mac mit gemeinsamem Arbeitsspeicher ist eine **Warnung, womit Sie
  rechnen müssen**, keine Verweigerung. Es ist **nie eine Sperre** — ein Kontrollkästchen schaltet die KI wieder ein, und
  der Hinweis bleibt in jedem Fall sichtbar. **Gestartet** wird die lokale KI über das **KI-Symbol**
  in der oberen Leiste, von jedem Bildschirm aus.
  Ein Editor **„Verhalten & Prompts“** zeigt die vier bearbeitbaren System-Prompts
  (Zusammenfassung / Übersetzung / Synthese / Schlagwortextraktion) und die Keep-alive-Zeit des Modells.
  Diese vier Prompts **werden in allen zwölf Oberflächensprachen mitgeliefert**, sodass eine französische oder
  japanische Leserin eine Zusammenfassung in ihrer Sprache erhält statt einer englischen;
  der Editor zeigt den eingebauten Text für **Ihre** Sprache, und der genau verwendete Prompt
  wird mit jedem Ergebnis gespeichert. Ihr eigener Prompt, falls Sie einen schreiben, wird **genau
  so verwendet, wie Sie ihn geschrieben haben**, in welcher Sprache auch immer. Eine Liste **Eigene Extraktoren**
  lässt Sie verwaltete Prompts festlegen, die KI-abgeleitete Metadaten schreiben (gekennzeichnet als
  *unzuverlässig*, nie im vertrauenswürdigen Schlagwortindex).
  Wenn Ollama nicht vorhanden ist, erscheint ein **Installationsprogramm in der App** (Linux/Debian): Es lädt
  das offizielle Installationsskript herunter, prüft es gegen den von GitHub beglaubigten sha256-Digest, zeigt
  einen sichtbaren Schritt zur Rechteerhöhung und führt es aus — bei jeder Abweichung des Digests verweigert es. macOS/Windows
  erhalten einen ehrlichen Verweis auf ollama.com/download.
- **Statistik — das Verzeichnis der Produzenten (Erweitert → Amtliche Statistik):** ein
  beschreibendes Verzeichnis staatlicher und internationaler Statistikproduzenten. Die
  **Zahlen** selbst sind Daten und liegen daher unter **Regierungen → Statistik**,
  nicht in den Einstellungen. Jeder Produzent trägt **denselben beschreibenden Hinweis auf eine Quelle mit
  eigener Haltung** — eine amtliche Zahl nennt die Behörde, die sie erstellt, und deren Haltung — **nie ein
  Etikett „umstritten“ pro Quelle, ein Urteil oder eine Bewertung**. Sie können **sie zu Ihren Quellen hinzufügen** — ein Produzent, dessen
  Nachrichten- oder Presseteil bekannt ist, wird aktiviert und von dort gesammelt, während einer, dessen
  Adresse noch nicht recherchiert wurde, deaktiviert hinzugefügt wird, statt sein
  Datenportal zu durchkämmen — und **amtliche Zahlen abrufen** über dokumentierte maschinenlesbare Endpunkte
  (World Bank API / Eurostat SDMX), gespeichert mit ihrer vollständigen Herkunft und einem eigenständigen
  **Stand** (ein erneuter Abruf ist eine neue Zeile, nie ein Überschreiben). Produzenten werden **nebeneinander
  gezeigt, nie gemittelt**, und eine Ansicht **Triangulieren** (Triangulate) markiert Zellen, die nicht vergleichbare
  Einheiten / Saisonbereinigungen / Basisjahre mischen. **Revisionsanomalien prüfen** markiert, rein
  rückblickend, eine gespeicherte Zahl, deren neuester Stand einen früheren Wert ungewöhnlich weit verschoben hat,
  gemessen an der eigenen Revisionsgeschichte dieser Reihe (keine Bewertung). Der Abruf geht über den von Ihnen eingestellten
  Transport ins Netz und wird im Flugmodus verweigert.
- **OpenStreetMap:** Wählen Sie eine Kartenregion (mit einer datierten Schätzung in `~GB`) und laden Sie sie
  als fortsetzbaren, pausierbaren Auftrag im Task-Manager herunter (abgesichert durch das eine Netzwerk-Zustimmungsfenster).
- **Newsletter:** Importieren Sie Newsletter als Artikel — **beim Einlesen anonymisiert** (der
  Empfänger wird nie gespeichert, Wiederholungen der Empfängerangaben werden geschwärzt, Tracker-Token werden entfernt
  und serverseitige Tracker-Umleitungen werden markiert; **es wird nie etwas abgerufen**, daher kann ein Import
  nie verraten, dass Sie etwas geöffnet oder angeklickt haben). Drei Wege:
  - **.eml-Dateien auswählen** (Choose .eml files) — ein kleiner Upload mehrerer Dateien.
  - **Ganzen Ordner importieren** — zeigen Sie auf einen Ordner auf diesem Rechner; jede `.eml` darunter
    wird als **pausierbarer, fortsetzbarer Hintergrundauftrag** importiert (sichtbar im Task-Manager), der
    auf Archive von 20 GB und mehr skaliert und bereits importierte Nachrichten überspringt.
  - **Aus einem Postfach abrufen (IMAP/POP3)** — live aus einem Postfach abrufen, mit einem sichtbaren
    Hinweis an der Stelle der Nutzung (TLS zum Anbieter, Ihre IP ist sichtbar, **nicht** über
    Tor, Zugangsdaten werden nicht gespeichert). Über TLS muss das Zertifikat des Servers zu seinem Namen passen
    und von einer Stelle stammen, der Ihr Computer vertraut; andernfalls wird der Abruf verweigert, bevor
    Ihr Passwort gesendet wird, und die Meldung sagt, warum. Über die API rüstet ein Abruf mit
    `use_ssl` auf false (meist an Port 143/110) zuerst per STARTTLS unter derselben
    Prüfung auf und wird verweigert, wenn der Server das nicht anbietet: Ihr Passwort wird nie
    unverschlüsselt gesendet.
  - **Zu welchem Herausgeber gehört jeder Newsletter?** — importierte Newsletter liegen derzeit
    alle in einer einzigen Sammelquelle. `GET /api/newsletters/publisher-preview` zeigt, wie eine
    Ablage pro Herausgeber für die Newsletter, die Sie schon haben, aussehen WÜRDE: jede sendende
    Domain, wie viele Nachrichten von ihr kamen und welcher vorhandenen Quelle sie zugeordnet wird (eine echte
    eTLD+1 aus einer mitgelieferten Public Suffix List — `email.bbc.com` wird also zu `bbc.com` aufgelöst —, wobei
    Newsletter-Plattformen umgekehrt behandelt werden, sodass zwei Substack-Publikationen nie
    zu einem „Substack“ zusammenfallen). Es ist **nur eine Vorschau**: Nichts wird zugeordnet oder verschoben, und
    wo die Belege nicht entscheiden, sagt sie das, statt zu raten.
  - **Importierte Newsletter entfernen** — löscht jeden importierten Newsletter-Artikel (.eml +
    Postfach) aus dem aktiven Korpus, um einen fehlerhaften Satz durch einen sauberen Neuimport zu ersetzen
    (die Wiederherstellung ist additiv, daher entfernt das Weglassen von Newslettern aus einer Sicherung sie nie — dies
    hier schon).
- **Daten & Sicherung — der einheitliche Export / Import:** eine Stelle, um alles zu sichern, bei
  **jeder Datenbankgröße**. **Exportieren / Sichern…** öffnet einen Dialog: Wählen Sie einen **Zielordner
  oder ein Laufwerk**, haken Sie an, was enthalten sein soll (Korpus, importierte Newsletter, lokale LLM-Modelle,
  Offline-Karten, Wikipedia-Dumps), und geben Sie eine **Passphrase** an — der verschlüsselte Korpus wird
  in diesen Ordner geschrieben, als **unabhängig authentifizierte Volumes plus Reed-Solomon-Parität** (sodass
  ein verlorenes oder beschädigtes Volume, selbst ein Korpus-Volume, wiederhergestellt werden kann), und die großen öffentlichen Daten
  (Modelle / Karten / Dumps) werden **unverändert** kopiert. Es gibt **keine Größenobergrenze**, und das Archiv wird
  nie als Ganzes im RAM gehalten. Die Passphrase hat **keine Wiederherstellung** — eine verlorene Passphrase bedeutet, dass die
  Korpussicherung nicht geöffnet werden kann.
  - **Jeder Export legt einen eigenen datierten Ordner an.** Das gewählte Ziel ist der ÜBERGEORDNETE Ordner:
    Darin erstellt jeder Export `YYYYMMDDHHMM_OpenOmniscience_Backup` — das lokale Datum
    und die Uhrzeit des Exportstarts, sodass die Ordner in der Reihenfolge sortiert sind, in der Sie sie angelegt haben. Ein zweiter
    Export in derselben Minute erhält `_2`, `_3` und so weiter. In einen vorhandenen Ordner wird **nie
    hineingeschrieben**, sodass eine frühere Sicherung auf demselben Laufwerk nicht durch eine spätere beschädigt werden kann.
  - **Jeder Export ist eine vollständige neue Sicherung.** Nichts wird aus einer früheren wiederverwendet; ein
    Export kostet also die Zeit und den Platz für alles, was Sie ausgewählt haben — und dafür wurde jedes
    Byte in diesem Ordner von genau diesem einen Durchlauf geschrieben.
  - **Nach dem Schreiben prüfen** (Verify after writing; standardmäßig an). Wenn das letzte Volume angekommen ist, wird jedes Volume
    vom Ziel zurückgelesen und seine Prüfsumme mit der beim Schreiben
    gespeicherten verglichen. Dabei wird jedes Byte ein zweites Mal gelesen, was die Dauer eines
    Exports auf einem langsamen Laufwerk ungefähr verdoppelt; es ist das Einzige, was ein Laufwerk erkennt, das
    den Schreibvorgang angenommen und etwas anderes gespeichert hat. Das Abschlussfeld zeigt dann **„Überprüft“** (Verified) —
    und wenn nicht, sagt es, welcher der vier Gründe zutrifft: Die Prüfung war ausgeschaltet,
    sie wurde abgebrochen, der Satz konnte nicht erneut gelesen werden, oder sie ist **fehlgeschlagen** und nennt die
    Volumes.
  - **`BACKUP_SUMMARY.md`** wird am Ende jedes Exports neben `volumes.json` geschrieben:
    dieselben Fakten, die das Abschlussfeld zeigt — Volumes, Bytes, Zeilen pro Tabelle mit den
    Artikeln zuerst, kopierte Dateien pro Kategorie, verstrichene Zeit, Ziel, Verschlüsselungsstatus,
    Schema- und App-Versionen, das Prüfergebnis und die Quellenangaben, die für
    den Inhalt der Sicherung gelten. Sie ist da, damit sich der Ordner auf einem Wechseldatenträger noch Jahre später
    selbst erklärt, wenn das Feld, das all dies angezeigt hat, längst verschwunden ist. Sie ist eine Beschreibung,
    keine Signatur: `volumes.json` enthält die Prüfsummen pro Volume, die die Bytes belegen.
    **Sie ist außerdem die einzige Datei in diesem Ordner, die nicht verschlüsselt ist** — der Korpus ist
    ohne Ihre Passphrase unlesbar, und diese Zusammenfassung liegt als Klartext daneben und sagt,
    wie viele Artikel, Quellen und verfolgte Dokumente der Korpus enthält. Das ist der Kompromiss,
    den die Datei eingeht; er steht in der Datei selbst, und Sie können sie löschen, wenn es Ihnen weniger wichtig ist, dass
    sich der Ordner selbst erklärt, als dem, der das Laufwerk findet, nichts zu verraten.
  - **Exporte werden nie zeitgesteuert.** Es gibt keinen automatischen oder zeitgesteuerten Export, und keiner ist
    geplant — ein Export ist ein **bewusster Akt**, weil er Ihren Korpus an einen Ort schreibt,
    den Sie gewählt haben, zu einem Zeitpunkt, den Sie gewählt haben.
  **Importieren…** zeigt auf einen Ordner, findet, was darin importierbar ist (eine wiederherzustellende Sicherung,
  große Daten oder Newsletter), und stellt es wieder her. **Die Wiederherstellung ist rein additiv** — sie
  **ergänzt** Ihren Korpus und **ersetzt** ihn **nie**: Nichts, was Sie schon haben, wird
  überschrieben, Duplikate werden Bit für Bit erkannt, und bei einem widersprüchlichen Wert **bleibt Ihr
  lokaler erhalten und beide werden gemeldet**, nie gemittelt.
  - **Importberichte.** Sowohl eine Merge-Wiederherstellung als auch ein Newsletter-Import aus einem Ordner
    schreiben danach automatisch einen **dauerhaft gespeicherten Bericht** auf die Festplatte (in der Einheit
    ARTIKEL — nie eine tabellenübergreifende Zeilensumme, die nach Millionen von Artikeln aussieht, obwohl es
    in Wirklichkeit Zeilen über viele Tabellen sind) — wie viele Artikel hinzukamen, wie viele als
    Nicht-Artikel aussortiert wurden (siehe **Aussortieren von Nicht-Artikeln** unten) und welche
    „ausgelöste Arbeit“ zurückbleibt (z. B. wie viele neu importierte Quellen noch
    auf ihre Qualifizierung warten, siehe [§3.3](#33-quellen-unter-einstellungen--erweitert--quellen)). Der Bericht
    selbst reist mit Ihrer **nächsten** verschlüsselten Sicherung, sodass er mit dem Korpus mitwandert. Er lässt sich
    herunterladen über `GET /api/backup/import-reports` (Liste) und
    `GET /api/backup/import-reports/{filename}` (als JSON oder mit `?format=md` als
    lesbare Markdown-Darstellung) — es gibt noch keinen eigenen Bildschirm dafür in der App,
    verwenden Sie also diese Endpunkte (oder den Browser), um einen zu lesen.
  - **Aussortieren von Nicht-Artikeln.** Jede Merge-Wiederherstellung und jeder Newsletter-Import aus einem Ordner
    prüft automatisch die gerade eingebrachten Artikel und **stellt** alle **unter Quarantäne** — behalten,
    nie gelöscht und umkehrbar —, die dieselben Kriterien für die Gültigkeit der Extraktion erfüllen,
    die auch der Qualifizierungstest für Quellen verwendet (eine Navigationsmenü-Seite, eine Linkliste, ein
    fehlerhaftes Scraping). Ein Artikel in Quarantäne ist von Suche und Analysen ausgeschlossen, bleibt aber
    in der Datenbank und reist mit Ihren Sicherungen; die Zählung steht im Importbericht.
  > **Alte Wege / Migrationswege (für ältere Sicherungen beibehalten).** Ein eigenes Feld stellt ein
  > **älteres Einzeldatei-Archiv `oo-backup-2`** mit derselben additiven Zusammenführungs-**Vorschau**
  > (neu / Duplikat / Konflikt) wieder her, bevor Sie **Anwenden** (Apply) (auf einer geprüften bereitgestellten Kopie, atomarer Austausch,
  > ein Schnappschuss `pre-restore-*.db` wird neben der Datenbank aufbewahrt). Ein roher Schnappschuss **Sicherung herunterladen (.db)**
  > (SQLite-Online-Backup-API) ist unter *„Älteres Backup-Tool…“* (Older backup tool…) für die manuelle
  > Nutzung versteckt. **Die zerstörerische Wiederherstellung „Ihren Korpus ersetzen“ wurde vollständig entfernt** — kein Ablauf
  > kann Ihre Daten überschreiben, und das Wiederherstellen einer **verschlüsselten** Sicherung entschlüsselt
  > Ihren Korpus nie stillschweigend.
- **Wartung (Diagnose-Feld):** **Schlüsselwörter bereinigen (neu indizieren, dann entfernen)** und
  **Gesamten Korpus neu indizieren** laufen als **pausierbarer Hintergrundauftrag mit gespeichertem Cursor**
  (er übersteht das Schließen des Tabs oder einen Neustart und setzt dort fort, wo er aufgehört hat). Führen Sie die Bereinigung nach
  einem Upgrade der Schlagwort-Engine aus, um die neueren Stoppwortlisten/Familien auf bestehende Artikel anzuwenden.
  **Schlüsselwortformen zusammenführen (Studien → Studie)** daneben erledigt den einen Teil dieser Bereinigung,
  den die Lemmatisierung braucht, ohne einen Artikel neu zu lesen: Schlagwörter, die indiziert wurden, bevor die Lemmatisierung
  hinzukam, halten „studies“ getrennt von „study“, das neue Artikel verwenden, und die Zusammenführung legt diese
  älteren Nennungen unter der Grundform ab, genau wie es eine Neuindizierung täte. Danach setzt sie die Sprache jedes
  Schlagworts anhand der Sprachen seiner Nennungen. Wortgruppen, Namen und Schlagwörter, die Ihre
  Familien oder Gruppen verwenden, werden nie zusammengeführt. Es ist ein pausierbarer Auftrag im Task-Manager, und
  **Bericht zur Zusammenführung (.json)** zeigt, was die letzte abgeschlossene Zusammenführung gezählt hat, und ihre größten Zusammenführungen.
  Eine Zusammenführung kann nicht rückgängig gemacht werden; ein späteres Entfernen beseitigt die Schlagwörter, die sie geleert hat.
  **Suche neu indexieren (Arabisch, Chinesisch, Japanisch)** indiziert Artikel, die vor dieser
  Version geschrieben wurden, so wie neue, damit ältere arabische, chinesische und japanische Artikel auch über
  einzelne Wörter gefunden werden. Es liest jeden Artikel einmal und indiziert nur die neu, deren Sucheintrag sich
  ändern würde; es ist ein pausierbarer Auftrag im Task-Manager, und **Bericht zur Neuindexierung der Suche (.json)**
  zeigt, wie viele es geprüft und neu indiziert hat, nach Schriftsystem. Führen Sie es nach einem Upgrade von jieba oder
  dem japanischen Wörterbuch erneut aus: Die Artikel, die das neue Wörterbuch anders zerlegt, werden
  neu indiziert, und der Bericht nennt die Versionen, mit denen es lief.
- **Vorübergehende Feldtest-Instrumentierung (Live-Test-Zyklus 0.0.8).** Während dieses
  Zyklus übt die App automatisch jede Netzwerkfläche einmal *innerhalb Ihrer
  eigenen Sammeldurchläufe* aus (Prüfung der Kalender-Feeds in höflichen Stapeln, die Markt-
  und Index-Feed-Importe, eine Rechtsverfolgung, eine Wiki-Verfolgung) und speichert jedes
  Ergebnis wörtlich in `data/field_test.jsonl`, das im Debug-Paket enthalten ist.
  **Zweck:** wiederkehrende Selbstverbesserung der Quellen-, Feed- und Kalenderlisten der Standardinstallation
  anhand echter Ergebnisse — der Maintainer installiert neu,
  klickt sich durch und teilt das Paket mit der Entwicklung. **Sie ist seit 0.1 standardmäßig
  aus** — aktivieren Sie sie für einen Live-Test-Zyklus mit `OO_FIELD_TEST=1`.
  Die App überträgt nie etwas: Die Protokolle bleiben auf diesem Rechner, bis *Sie*
  sie herunterladen und teilen. Der Start bleibt in jedem Fall vollständig offline.
- **Diagnoseprotokoll:** eine teilbare Zusammenschau, wie die App Ihren Korpus sieht — nur erzeugt,
  wenn Sie klicken, nur Zählungen und Strukturen (nie Bewertungen), und nur Sie entscheiden, wer
  die Datei bekommt. Das Feld hat EINE Schaltfläche **Diagnose**, ihr Kästchen **Gründlich** und zwei kleine Links, **Alle Schlüsselwörter** und **Letzte Diagnose erneut speichern**; jedes andere Protokoll in dieser Tabelle ist ein **Bestandteil des Diagnosearchivs**, keine eigene
  Schaltfläche (mehrere enthalten mehr als einen Bericht: `selftests.json` enthält die dreizehn Selbsttests der Mechanismen
  mit je einem Ergebnis, `storage.json` die Messungen zu Platzbedarf, Zusammensetzung, Volume und Persistenz,
  `contention.json` die Schreibsperre und die Zuordnung von Stockungen, `ai-runs.json` die letzten Ergebnisse der KI-Aufträge,
  `run-journal.json` die Zusammenfassung und ihre Rohzeilen; bei einem zusammengelegten Bestandteil nennt `merged.replaces` im Manifest
  die Dateien, die er ersetzt hat, sodass ein altes Archiv neben einem neuen gelesen werden kann):

  | Export oder Archivbestandteil | Was es ist |
  |---|---|
  | **Diagnose** (und ihr Kästchen **Gründlich**) | EIN Archiv mit allem, was diese Installation über sich selbst sagen kann, im Hintergrund erstellt (die App bleibt nutzbar) und dann übergeben: **eine Datei**, wenn es in 4 MB passt, sonst **nummerierte Dateien von jeweils höchstens 4 MB** (`…-part-03-of-12.zip`) plus eine kleine `…-manifest.zip`, die jede Datei mit ihrer Größe und ihrem SHA-256 auflistet. Jede Datei lässt sich für sich in jedem Entpackprogramm öffnen. **Schnell** (Quick; die Voreinstellung) schreibt zuerst die Aufzeichnungen, während die Erfassung weiterläuft, dann so viele Durchsuchungen Ihres Korpus, wie in zehn Minuten passen, die kürzesten zuerst; eine Durchsuchung, die nicht mehr passte, wird **in der Datei** als nicht ausgeführt **genannt**, mit Begründung, nie stillschweigend weggelassen. **Gründlich** (das Kästchen neben der Schaltfläche, das bei jedem Öffnen des Feldes wieder leer ist) führt jede Durchsuchung aus, jede bis zu fünf Minuten lang, wobei die Erfassung währenddessen pausiert (27 bis 47 Minuten gemessen an einem großen Korpus). Die `manifest.json` der Datei sagt, welcher Modus lief, auf welchem Rechner (Build, Bibliotheksversionen, Speicherstufe, die Namen der gesetzten `OO_*`-Schalter, nie deren Werte), und für jeden Bestandteil seinen Bereich (Arbeitsspeicher, Speicherplatz, Datenbank, Sitzungen, Läufe, Schlagwörter, Oberfläche, Quellen, KI, Selbsttests, Build). Siehe „Die nummerierten Dateien speichern“ unten |
  | **Letzte Diagnose erneut speichern** (ein Link unter der Schaltfläche, sichtbar, sobald ein Build existiert) | dasselbe fertige Archiv, erneut gespeichert (geben Sie zuerst eine Teilnummer in „Beginnen bei Teilnummer“ ein, dann beginnt es dort, sodass Sie nur die erneut senden können, deren Upload fehlgeschlagen ist). Es verwendet nur ein Archiv wieder, das Sie bereits erstellt haben — es startet nie einen neuen Build. Ist ein einzelnes Protokoll zu groß für eine Datei, wird es an Datensatzgrenzen in nummerierte Stücke geteilt, und das Manifest sagt, welches (ein Schnitt nach Bytes, `.part0001of0003`, ist der letzte Ausweg und wird in `volumes.json` genannt) |
  | **Alle Schlüsselwörter** (ein Link) | die Liste pro Schlagwort: jedes Schlagwort im Korpus (nicht nur die häufigsten pro Sprache), ohne Obergrenze für die Gesamtgröße, als nummerierte Dateien von jeweils höchstens 4 MB. Die ersten Dateien enthalten die 5.000 häufigsten jeder Sprache; wenn Sie also nicht alle senden können, senden Sie sie in der Reihenfolge der Nummern. Es wird stapelweise auf die Festplatte geschrieben, sodass der Arbeitsspeicher der App unabhängig von der Korpusgröße gleich bleibt; ein großer Korpus ergibt viele Dateien (die Seite sagt, wie viele, bevor Sie eine speichern) und braucht Minuten, und der Export bricht mit einer klaren Meldung ab (und entfernt seine unvollständigen Dateien, wo das Laufwerk es zulässt), wenn Arbeitsspeicher oder Festplatte knapp werden. Alles andere, was das Schlagwortprotokoll enthielt, steht, wo der Diagnose-Build es ausgeführt hat, im Diagnosearchiv als `keyword-log-digest.json`: die Familien (die 1.000 häufigsten ausgegeben, jede Familie in der Zusammenfassung der Datei gezählt), Ihre Korrekturen, die Supergruppen, die Konzentration pro Quelle, die Kandidaten für Stoppwörter und Ringe und die Korpuszählungen, so wie das Schlagwortprotokoll sie enthielt, plus die 100 häufigsten Schlagwörter nach Nennungen mit der Anzahl der weggelassenen. Ein Build im Modus Schnell kann bei einem großen Korpus den Digest als nicht ausgeführt nennen, weil er nicht in die zehn Minuten passte (haken Sie **Gründlich** an), ein Computer ohne den nötigen Arbeitsspeicher nennt ihn als abgelehnt, und ein Digest, der seine eigene Grenze von fünf Minuten überschreitet, wird als übersprungen genannt (Gründlich behält diese Grenze bei); dann ist dieser Link der Weg zu den Schlagwörtern, und seine eigene Zusammenfassung wird über jedes Schlagwort erstellt, nicht nur über die ersten 5.000 jeder Sprache. Auf einem Computer mit wenig Arbeitsspeicher, der den Digest dennoch ausführt, werden die Familien nur über die ersten Schlagwörter jeder Sprache gebildet, und die Datei sagt das und verweist auf diesen Link. Es gibt keine Schaltfläche, um den letzten Satz Schlagwortdateien erneut zu speichern: Nachdem Sie die Seite neu geladen haben, drücken Sie den Link, um einen neuen Satz zu erstellen |
  | **Schlüsselwort-Selbsttest (.json)** | eine Prüfung anhand von Musterfällen, ob die Vorauswahl der Schlagwörter sich noch richtig verhält (z. B. *WHO* ≠ *who*) |
  | **Bericht der Schlüsselwort-Engine (.json)** | Zusammensetzung, Genauigkeit der Entitäten, Abdeckung durch Übersetzungen/Tags, Status pro Sprache |
  | **Schlüsselwort-Wachstumskurve / (.json)** | kumulierte unterschiedliche Schlagwörter gegenüber hinzugekommenen Wörtern (sättigt sich der Wortschatz?) |
  | **Startkarten-Diagnose (.json)** | öffnet jede Spur auf der Startseite ihren genauen Korpus oder einen unscharfen Ersatz? |
  | **Datumsextraktions-Protokoll (.json)** | Abdeckung der Datumsmarkierung |
  | **Monatsbelegung (.json)** (Month occupancy) | von den Monatsnamen, die der Schlagwortfilter verwirft, wie viele tatsächlich Teil eines Datums waren — der Beleg dafür, ob dieser Filter datumsbewusst werden sollte |
  | **Netzwerkprotokoll (.json)** | Abrufergebnisse mit transportbewussten Urteilen |
  | **Leistungsbericht / Skalierungs-Benchmark / Rollup-Benchmark (.json)** | Zeitmessungen und Skalierungsprüfungen |
  | **Debug-Paket (.json)** | ein zusammengefasstes Support-Paket |

  **Die nummerierten Dateien speichern.** Die Seite sagt, wie viele Dateien bereit sind („13 Dateien von höchstens 4 MB sind bereit (Manifest: 1, nummerierte Teile: 12)“),
  und übergibt sie Ihrem Browser **fünf pro Klick**, das Manifest zuerst, weil fünf das ist, was eine Upload-Nachricht aufnimmt, und weil ein Klick das ist, was einen
  Browser einen Download annehmen lässt. Ihr Browser fragt möglicherweise einmal, ob er mehrere Downloads erlauben soll: Erlauben Sie sie. Nach den ersten fünf heißt die Schaltfläche „Die nächsten 5 speichern“;
  „Alle übrigen speichern“ wird angeboten, sobald mehr als fünf Dateien übrig sind, für einen einzigen Klick, der alles erledigt. Ein Paket aus fünf Dateien oder weniger, was der Normalfall ist, wird
  Ihrem Browser von der Seite selbst übergeben, wenn der Build endet (der Klick, der ihn gestartet hat, liegt längst zurück); „Letzte Diagnose erneut speichern“ sendet dieselben Dateien noch einmal. Die Seite kann Ihren Browser nur *bitten*,
  eine Datei zu speichern, daher sagt sie „Ihr Browser wurde gebeten, 5 von 13 Dateien zu speichern“, nie, dass sie gespeichert sind: Sehen Sie in Ihrem Download-Ordner nach (ein Browser, der die
  Frage nach mehreren Downloads abgelehnt hat, speichert nichts und teilt das der Seite nicht mit). Während Dateien unterwegs sind, sind die Schaltflächen ausgegraut, und ein zweiter Klick bewirkt
  nichts. Jede Datei ist höchstens 4.000.000 Bytes groß (die Größe, an der diese App teilt) und lässt sich für sich öffnen, sodass Sie einige jetzt und
  den Rest später senden können. Um nur einige Dateien erneut zu senden, geben Sie eine Teilnummer in „Beginnen bei Teilnummer“ ein und drücken „Ab diesem Teil speichern“: Das übergibt fünf Dateien
  ab diesem Teil (das Manifest wird nicht erneut gespeichert), und eine Nummer hinter dem letzten Teil beginnt beim letzten und sagt das. Eine Nummer, die Sie in dasselbe Feld eingeben, sagt auch
  „Letzte Diagnose erneut speichern“, wo es beginnen soll (eine Nummer, die die Seite selbst dort eingetragen hat, wird ignoriert, sodass „erneut“ bei unberührtem Feld
  beim Manifest beginnt). Das erneute Senden eines Teils verschiebt „Die nächsten 5 speichern“ nicht: Es geht ab der am weitesten fortgeschrittenen Datei weiter, die dem Browser bereits übergeben wurde. Wenn Sie eine Nummer vor den bereits gespeicherten Dateien eingeben, werden die
  dazwischen übersprungen (die Zahl in der Statuszeile sagt, wie viele angefordert wurden); geben Sie die erste fehlende Teilnummer ein, um die Lücke zu füllen.
  Ein Satz ist vollständig, wenn jeder Name von `…-part-01-of-NN` bis `…-part-NN-of-NN` vorhanden ist und sein SHA-256 mit dem
  Manifest übereinstimmt. Um einen Satz mit dem Analyseskript zu lesen, übergeben Sie ihm den Ordner (oder eine beliebige Datei daraus): `python scripts/analyze_keyword_log.py <folder>` — es
  nennt die Teile, die fehlen oder vom Manifest abweichen, überspringt einen beschädigten Teil und liest den Rest.

  Dasselbe Feld führt auch die lokale **Quellenanreicherung** (Source enrichment; Themen-Tags aus Ihrem
  Korpus ableiten) und zustimmungspflichtige **Wikidata**-Durchläufe aus (Quellentypen, Entdeckung neuer Quellen).
- **Sicherheit & gefährdete Nutzung (Erweitert → Sicherheit):** Werkzeuge für Journalistinnen und Journalisten, die unter
  Druck arbeiten, jedes mit seiner **ehrlichen Grenze** gekennzeichnet:
  - **Verschlüsselung im Ruhezustand (Standard für neue Korpora).** Neue Datenbanken sind
    auf der Festplatte mit SQLCipher 4 verschlüsselt: Bei jedem Start fragt die App nach **DER
    Passphrase** — einem einzigen, gleichbleibenden Geheimnis, wie eine Benutzerkennung (`OO_DB_PASSPHRASE` für
    skriptgesteuerte/Headless-Läufe). **Es gibt keine Wiederherstellung und keine alternative
    Entschlüsselung**: Eine verlorene Passphrase kostet Zeit für das erneute Sammeln, weil der
    Korpus aus dem Web neu aufgebaut wird — er enthält nichts Persönliches über das hinaus, was
    aus öffentlichen Quellen gescrapt und abgeleitet wurde. Bestehende unverschlüsselte Korpora funktionieren
    unverändert weiter; **Einstellungen → Erweitert → Sicherheit → „Diesen Korpus verschlüsseln…“** wandelt
    einen *an Ort und Stelle* um (ausdrückliche Zustimmung, vollständige Prüfung vor dem Austausch und ein
    bewusst aufbewahrter unverschlüsselter Schnappschuss als Notausgang — löschen Sie ihn, sobald
    Sie erfolgreich entsperrt haben). Der **Doctor** (`GET /api/system/doctor`
    und dasselbe Feld) bestätigt den *tatsächlichen* Zustand jedes Speichers, indem er die
    Dateiköpfe liest — Korpus, Verwahrungsprotokoll, Signaturschlüssel —, nie aufgrund von Annahmen.
    **Die ehrliche Grenze:** Die Verschlüsselung im Ruhezustand schützt eine *beschlagnahmte oder kopierte
    Datei*. Sie kann keine kompromittierte laufende Sitzung schützen (der Schlüssel liegt im
    Arbeitsspeicher, solange die App läuft), und sie ist von einer Vollverschlüsselung der Festplatte nur unabhängig,
    wenn die beiden Passphrasen verschieden sind. Der unverschlüsselte Betrieb bleibt
    als ausdrückliche Wahl verfügbar (`OO_DB_PLAINTEXT=1`) — die App zeigt nie einen Sperrbildschirm
    über einer unverschlüsselten Datei, denn das wäre vorgetäuschte Sicherheit.
    Sicherungen eines verschlüsselten Korpus funktionieren unverändert: Die Bestandteile sind
    übertragbar, die eigene Hülle des verschlüsselten Archivs schützt sie im Ruhezustand,
    und Wiederherstellungen erhalten die Verschlüsselung Ihres Korpus (durch Tests geprüft).
  - **Verschlüsseltes Backup** — ein passphrasegeschützter Schnappschuss (AES-256-GCM + scrypt).
    Eine verlorene oder falsche Passphrase bedeutet, dass die Datei nicht geöffnet werden kann: Es gibt keine Wiederherstellung.
    Um eine verschlüsselte Sicherung zurückzuholen, verwenden Sie die **additive Merge-Wiederherstellung** unter
    **Daten & Sicherung** (oben) — sie zeigt eine Vorschau und ergänzt dann Ihren Korpus, ohne ihn je zu
    ersetzen, und entschlüsselt Ihren aktiven Speicher nie stillschweigend. *(Die alte zerstörerische
    Wiederherstellung durch verschlüsseltes Ersetzen wurde entfernt.)*
  - **Datenbankwartung** — *Datenbank kompaktieren (VACUUM)* baut die Datenbankdatei
    neu auf: Sie gewinnt den Platz zurück, den Löschungen hinterlassen (angezeigt als „Rückgewinnbarer
    Speicherplatz“, ein echter Messwert aus `PRAGMA freelist_count`), und defragmentiert die Indizes.
    Sie dauert proportional zur Dateigröße und pausiert die Schreibvorgänge der Erfassung,
    solange sie läuft; das Ergebnis meldet die tatsächlich freigegebenen Bytes und die Dauer. Sie
    deutet oder entfernt nie Daten. Sie baut die kompaktierte Kopie im Arbeitsspeicher auf
    (sie in eine temporäre Datei zu schreiben, beschädigt eine verschlüsselte Datei bei der Seitengröße der App,
    gemessen), daher prüft sie zuerst, ob der Computer den Arbeitsspeicher dafür hat
    (etwa das 1,25-Fache des genutzten Teils der Datei, zusätzlich zum freien
    Arbeitsspeicher, den die App immer für sich selbst reserviert) und Platz auf dem Laufwerk (etwa das Doppelte
    des genutzten Teils plus die Größe des Protokolls der Datei), und wenn eines davon nicht reicht,
    sagt sie, welches, mit den Zahlen, und startet nicht. Ein Wert, den sie nicht
    lesen konnte, wird nicht geprüft, und auch das sagt sie.
  - **Netzwerk-Abrufmodus** — *Transparent* (Standard; höflich, nennt das Werkzeug im
    User-Agent) oder *Geschützt* (die Webabrufe der App werden über einen Proxy geleitet, den **Sie** betreiben,
    z. B. Tor, mit einem generischen User-Agent). Die eine Ausnahme beim User-Agent sind die API-
    und Dump-Anfragen der App an die Server von Wikimedia (ihre Funktionen für Wikipedia, Wikidata und Dumps):
    Die API-Richtlinie von Wikimedia verlangt, dass sich jedes Werkzeug zu erkennen gibt, daher tragen diese
    Anfragen im geschützten Modus weiterhin den eigenen User-Agent des Werkzeugs, über denselben Proxy und nur über
    https. Alles andere, was von einer Wikimedia-Seite abgerufen wird (ein Artikel, der wie jede andere
    Seite gesammelt wird), erhält den generischen. Drei Dinge verbinden sich selbst im geschützten Modus direkt, wie
    der Hover-Text im Netzwerk-Zustimmungsfenster für jedes davon sagt: der Abruf aus dem Newsletter-Postfach,
    die OpenTimestamps-Verankerung und die Downloads für die lokale KI.
    Der geschützte Modus **kann keine Anonymität garantieren** — Sie müssen den Proxy selbst betreiben und ihm
    vertrauen; ohne Proxy-URL lässt er sich nicht aktivieren. SOCKS-Proxys wie Tor brauchen
    keine zusätzliche Installation.
  Die beiden **unumkehrbaren** Aktionen liegen einen Abschnitt weiter unten, unter **Erweitert →
  Deinstallieren und löschen**, bewusst entfernt von allem oben Genannten:

  - **Notfall-Löschung** — löscht unumkehrbar den Korpus, die Schlüssel und die Caches auf diesem Rechner
    (doppelt bestätigt). **Grenze:** Überschreiben an Ort und Stelle garantiert auf SSD/Flash *keine*
    Unwiederherstellbarkeit — dafür verwenden Sie eine Vollverschlüsselung der Festplatte (LUKS/Qubes/Tails)
    und vernichten den Schlüssel. Es gibt außerdem ein `panic`-Kommandozeilenwerkzeug und einen Betriebsmodus `--ephemeral`
    (Daten nur im RAM, beim Beenden gelöscht).
  - **App deinstallieren** — entfernt die **virtuelle Umgebung** (virtualenv) und die **Desktop-Starter** der App
    und stoppt dann den Server (Bestätigung durch Eintippen). Ihre **Daten bleiben erhalten** (verwenden Sie zuerst die Notfall-Löschung, um
    sie zu vernichten); der App-Ordner bleibt bestehen und muss von Hand gelöscht werden. Gleichwertig mit
    `./install.sh --uninstall` oder dem Desktop-Symbol **„Open Omniscience deinstallieren“** (Uninstall Open Omniscience), das das
    Installationsprogramm neben den beiden App-Startern anlegt.

  Die Governance und die roten Linien zur doppelten Verwendbarkeit (Dual Use), die all dem Grenzen setzen, stehen in
  [`GOVERNANCE.md`](GOVERNANCE.md) (auch unter **Hilfe & Doku**).

### 3.10 Hilfe & Doku

**Wofür es da ist:** die Dokumentation **in der App** lesen, offline. Eine
Liste links wählt ein Dokument aus (dieses **Benutzerhandbuch** ist die Voreinstellung; die anderen
gehen tiefer auf bestimmte Themen ein), das rechts dargestellt wird, mit **Suche auf der Seite**. Öffnen Sie
sie über das **?** in der oberen Leiste oder die Befehlspalette („Benutzerhandbuch öffnen“ (Open the User Manual)). Das
rohe API-Schema liegt unter `/openapi.json`.

---

## 4. Häufige Arbeitsabläufe (Anleitungen)

**Nachrichten zu einem Thema sammeln und durchsuchen**
1. **Einstellungen → Erweitert → Quellen** → prüfen Sie, ob die passenden Quellen aktiviert sind (Filter nach Land/Tag).
2. **Einstellungen → Erweitert → Erfassung** → klicken Sie entweder pro Quelle auf **Feed abrufen**, oder stellen Sie den
   **Planer** (scheduler) auf den RSS-Modus mit Ihren **Tags / Schlüsselwörter** und klicken Sie auf **Starten** (oder gehen Sie einfach online
   — die Erfassung läuft dann automatisch).
3. Suchen Sie über die **Omnibar** → boolesche Abfrage → bei Bedarf **CSV exportieren**/**JSON exportieren**.

**Ein Themenfeld dauerhaft im Hintergrund beobachten**
1. **Einstellungen → Erweitert → Erfassung** → Planer **Modus: RSS-Feeds**, **Sprachen**/**Tags** festlegen,
   **Ziele vorschauen**, ein **Intervall** festlegen, **Beim Start automatisch beginnen** ankreuzen,
   **Speichern (Save)**.
2. Aktivieren Sie optional **Beweise & Verwahrung → Automatisch beim Erfassen protokollieren**, damit jede Erfassung
   beim Eintreffen signiert wird.

**Einen vor Gericht bzw. gegenüber einer Redaktion belastbaren Nachweis eines Artikels erstellen**
1. Suchen Sie den oder die Artikel über die Omnibar.
2. **Signierte Belege exportieren** (oder **Beweise & Verwahrung → Paket exportieren** für ein einzelnes Element).
3. Übergeben Sie der empfangenden Person das Paket und `scripts/verify_evidence.py` /
   `verify_custody.py`; sie prüft offline, ohne Ihnen oder diesem Werkzeug vertrauen zu müssen.
4. Für einen unabhängigen *Zeit*nachweis aktivieren Sie **OpenTimestamps** und verankern die
   Merkle-Wurzel des Pakets (beachten Sie den Datenschutzhinweis).

**Einen umstrittenen Wikipedia-Artikel auf Manipulation überwachen**
1. **Einstellungen → Wikipedia** → fügen Sie die Seite hinzu (Ausgabe + Titel), kreuzen Sie **ORES-Bewertungen verwenden** an,
   **Jetzt verfolgen**.
2. Prüfen Sie die **Markierten Änderungen**; öffnen Sie bei allem Verdächtigen **Unterschiede**.

**Einen Rohstoffpreis im Vergleich zu Nachrichten verfolgen**
1. **Rohstoffe** — die kuratierten Feeds werden bereits automatisch im Hintergrund aktualisiert;
   für einen seitenspezifischen Preis fügen Sie eine **Preis-Extraktionsregel** hinzu und klicken auf **Testen**.
2. Klicken Sie auf die Karte der Zeitreihe → lesen Sie das Diagramm und die **Korrelation** mit einer Nachrichtenabfrage.

**Ihren Korpus auf einen anderen Rechner verschieben (oder zusammenführen)**
1. **Einstellungen → Daten & Sicherung → Exportieren / Sichern…** — wählen Sie einen Zielordner bzw. ein Ziellaufwerk und
   eine Passphrase; der Korpus wird als verschlüsselte Volumes + Parität ausgegeben (beliebige Größe).
2. Auf dem anderen Rechner: **Einstellungen → Daten & Sicherung → Importieren…** — zeigen Sie auf diesen Ordner und
   stellen Sie wieder her. Die Wiederherstellung ist additiv — sie ergänzt den Korpus dieses Rechners und
   ersetzt ihn nie, sodass Sie damit auch zwei Korpora *zusammenführen* können. Eine ältere Einzeldatei
   `oo-backup-2` braucht nichts Besonderes: Die Import-Suche findet eine solche an beliebiger Stelle verschachtelt im
   angegebenen Ordner und bietet sie als eigenes Element an, sodass alte Sicherungen wiederherstellbar bleiben.

**Stattdessen den ganzen Ordner kopieren — ein vollwertiger Weg zum Verschieben oder Sichern**

Die Werkzeuge in der App gibt es, um Dinge hinzuzufügen, die eine Dateikopie nicht leisten kann (ein signiertes Manifest, Parität, die
ein beschädigtes Volume repariert, eine additive Zusammenführung zweier Korpora, eine selektive Wiederherstellung). Sie sind
keine Hürde, die Sie nehmen müssen. Das Kopieren des Datenordners ist bei jeder Größe ein unterstützter Weg, und es
ist der richtige, um einen Rechner komplett umzuziehen:

1. **Beenden Sie die App** — mit dem Ein/Aus-Knopf in der oberen Leiste oder mit Strg-C in ihrem Terminal. Das ist
   nicht optional: Eine Kopie, die während des Betriebs entsteht, kann ein halb geschriebenes WAL erwischen.
2. Kopieren Sie den gesamten **Daten**ordner (§5.1 — `<app folder>/data/`, oder wohin auch immer `OO_DATA_DIR`
   zeigt). Nicht den App-/Code-Ordner: Der Code lässt sich neu installieren, die Daten nicht.
3. Legen Sie den Ordner auf dem anderen Rechner dort ab, wo Sie ihn haben möchten, und lassen Sie `OO_DATA_DIR` darauf zeigen —
   oder wählen Sie bei einer ganz neuen Installation diesen Ordner im Schritt beim ersten Start (§5.1).

Der Korpus bleibt während des Kopierens im Ruhezustand verschlüsselt, und die Schlüssel reisen im Ordner mit,
daher ist **die Passphrase das Einzige, was Sie separat mitbringen müssen**. Seit 2026-08 liegen auch die lokalen KI-Gewichte
im Datenordner, sodass eine Kopie diese ebenfalls mitnimmt — genau das macht daraus
einen echten Umzug des ganzen Rechners statt eines reinen Korpus-Umzugs.

---

## 5. Technische Referenz

### 5.1 Wo Ihre Daten liegen

Ermittelt von `src/paths.py`, in dieser Rangfolge:

1. **`OO_DATA_DIR`**, falls gesetzt (gewinnt immer).
2. **Quellcode-Checkout** — wenn die App aus einem beschreibbaren Repository läuft (Entwicklung/editierbar/Qubes-Installation
   in `$HOME`), liegen die Daten in `<repo>/data/`.
3. **Pro Benutzer** — andernfalls XDG: `$XDG_DATA_HOME/open-omniscience` oder
   `~/.local/share/open-omniscience`.

Fall 2 ist der Normalfall bei einer Installation mit `install.sh`: Das Installationsprogramm klont einen
beschreibbaren Verzeichnisbaum, Ihre Daten liegen also in `<app folder>/data/`, und der XDG-Pfad aus Fall 3
wird nie angelegt. Wenn Sie ihn suchen und er fehlt, ist das kein Fehler.

**Den Ordner beim ersten Start wählen.** Beim allerersten Start der App —
nach den Schritten zu Sprache und Rechtlichem, bevor Sie die Passphrase festlegen — fragt sie, wo
Ihr Korpus liegen soll. Den Standard beizubehalten ist ein Klick. Wählen Sie einen anderen
Ordner (etwa ein externes Laufwerk), legt die App darin einen Ordner namens **`OOS data`**
an und hält die Wahl in `oo.env` im Installationsverzeichnis fest, das
`scripts/launch.sh` bei jedem Start liest.

Zwei Dinge an diesem Schritt sind beabsichtigt und wissenswert:

* **Er erscheint nur bei einer ganz neuen Installation.** Sobald ein Korpus existiert, verweigert die App
  eine Änderung der Einstellung, weil sie das Vorhandene nicht verschieben kann: Die Schlüssel,
  das Verwahrungsprotokoll und der Modellspeicher würden der neuen Einstellung folgen, während der Korpus
  zurückbliebe, und der nächste Start würde einen leeren Ordner vorfinden und anbieten, einen
  einzurichten. Einen bestehenden Korpus verschieben Sie mit der einfachen Ordnerkopie aus §4 („Stattdessen den
  ganzen Ordner kopieren“) — App beenden, Datenordner kopieren, `OO_DATA_DIR`
  auf die Kopie zeigen lassen.
* **Die Wahl eines anderen Ordners beendet die Einrichtung und bittet Sie, die App erneut zu starten.**
  Zu diesem Zeitpunkt wurde noch nichts angelegt; der Ordner wird erst beim nächsten
  Start wirksam, daher würde ein Weitermachen in derselben Sitzung den Korpus im alten Ordner ablegen,
  während die festgehaltene Wahl auf den neuen zeigt.

Sie werden informiert, aber nicht blockiert, wenn der Ordner ungewöhnlich ist: ein Ordner, der bereits einen
Korpus enthält (beim Fortfahren wird dieser geöffnet, statt einen neuen anzulegen), ein RAM-gestütztes
Dateisystem (alles dort Geschriebene geht bei einem Neustart verloren) oder wenig freier Speicherplatz, mit
der Zahl. Abgelehnt wird nur ein Ordner, in den die App tatsächlich nicht schreiben kann.

**Wenn das Laufwerk abgezogen wird.** Ein auf diese Weise gewählter Ordner erhält eine kleine Markierungsdatei,
`.oos-volume`, deren Kennung auch in `oo.env` festgehalten wird (`OO_DATA_VOLUME_ID`). Die App
liest sie während des Betriebs alle zwei Sekunden. Verschwindet das Laufwerk:

* Die App protokolliert die Trennung auf der internen Festplatte (unter
  `~/.local/state/open-omniscience/`, da sie nicht auf das fehlende Laufwerk schreiben kann).
  Das Diagnosepaket enthält dieses Protokoll, und der nächste Start nennt es, wenn er
  erklärt, wie die vorherige Sitzung endete.
* Die Erfassung pausiert, und ein Fenster bittet Sie, das Laufwerk innerhalb von 30 Sekunden wieder anzuschließen.
  Kommt dasselbe Laufwerk zurück, startet die App neu, um Ihre Daten wieder zu öffnen (ein verschlüsselter
  Korpus fragt erneut nach seiner Passphrase). Einfach weiterlaufen kann sie nicht: Die Datenbank-
  verbindung wird beim Start der App festgelegt.
* Nach diesen 30 Sekunden schließt ein zweiter Countdown die App sauber nach weiteren 30
  Sekunden; **Jetzt schließen** tut dies sofort. Ein erneutes Anschließen während dieses zweiten Countdowns
  startet die App stattdessen trotzdem neu.
* Was in den letzten Augenblicken vor dem Abziehen geschrieben wurde, kann verloren gehen. Die
  Datenbank selbst bleibt konsistent: SQLite macht einen unvollendeten Schreibvorgang beim nächsten
  Öffnen rückgängig.

Starten Sie die App, während das Laufwerk nicht angeschlossen ist, legt sie an seiner Stelle keinen leeren
Ordner an: Sie zeigt eine Seite „Ihr Datenlaufwerk ist nicht angeschlossen“, prüft
alle paar Sekunden erneut und öffnet die App, sobald das Laufwerk wieder da ist. Ein anderes
Laufwerk, das unter demselben Pfad eingehängt wird, wird als anderes erkannt (seine Markierung stimmt nicht
überein). Haben Sie den Ordner absichtlich gelöscht, entfernen Sie die Zeilen `OO_DATA_DIR` und
`OO_DATA_VOLUME_ID` aus `oo.env`, um mit einem neuen, leeren Korpus neu zu beginnen.
Die Notfalllöschung erledigt das für Sie. Hängt das System das Laufwerk nach erneutem Anschließen unter einem neuen Pfad
ein, kann die App es dort nicht finden: Schließen Sie sie und lassen Sie `OO_DATA_DIR` in
`oo.env` auf den neuen Pfad zeigen.

In diesem Verzeichnis finden Sie: `open_omniscience.db` (den Korpus, SQLite/WAL),
`app_settings.json` (Design, Ergebnislimit), `custody_settings.json` (Verwahrungs-
einstellungen), Verwahrungsschlüssel, heruntergeladene Wikipedia-Dumps, eventuelle `pre-restore-*.db`-
Schnappschüsse und `models/` — die lokalen KI-Gewichte, die im eigenen
Datenverzeichnis der App liegen statt im Home-Verzeichnis des jeweiligen Backends:

| Pfad | Inhalt |
| --- | --- |
| `models/ollama/` | Der Modellspeicher von Ollama (`OLLAMA_MODELS` zeigt hierher) |
| `models/huggingface/hub/models--<org>--<name>/` | Die Gewichte von vLLM, ein Ordner pro Repository (`HF_HOME` zeigt auf `models/huggingface`) |
| `cache/` | Die Rechen-Caches des vLLM-Servers — Triton-Kernel, torch Inductor, der CUDA-JIT-Cache, vLLMs eigene Cache- und Konfigurationswurzeln. Werden beim ersten Lauf aufgebaut, können gefahrlos gelöscht werden (sie werden neu aufgebaut) und können mehrere GB erreichen |
| `vllm_start_attempts.jsonl` | Jeder Start und jedes Ende des vLLM-Servers, mit dem Wortlaut des Fehlers. Wird **hier** statt in der vLLM-Umgebung aufbewahrt, damit eine Neuinstallation von vLLM — das Erste, was die meisten versuchen, wenn ein Server nicht startet — nicht den Nachweis löscht, warum er fehlschlug |
| `vllm_failed_starts/` | Das vollständige Protokoll jedes der letzten paar **fehlgeschlagenen** Starts. Das laufende Serverprotokoll wird vom nächsten Versuch überschrieben, und eine Wiederholungsschleife überschreibt es innerhalb einer Minute, daher wird eine Kopie angefertigt, sobald ein Start als fehlgeschlagen erkannt wird. Höchstens einige hundert KB |

Wenn Sie `OLLAMA_MODELS`, `HF_HOME` oder eine der Cache-Variablen
(`XDG_CACHE_HOME`, `TRITON_CACHE_DIR`, `TORCHINDUCTOR_CACHE_DIR`,
`CUDA_CACHE_PATH`, `VLLM_CACHE_ROOT`, `VLLM_CONFIG_ROOT`) selbst setzen, hat das immer Vorrang —
die App exportiert Ihren Wert erneut, statt ihn zu überschreiben. Die Umleitung gilt
nur für den **Server**: Die Installation von vLLM nutzt weiterhin den normalen Wheel-Cache von pip, sodass
eine Neuinstallation nicht erneut mehrere GB herunterlädt, die bereits vorhanden sind. Gewichte, die **vor** dem 2026-08-04 heruntergeladen wurden, liegen
weiterhin im eigenen `~/.cache/huggingface/hub/` von Hugging Face; Einstellungen → KI meldet
sie und nennt, wohin sie verschoben werden sollten, und nichts wird für Sie verschoben oder gelöscht.

### 5.2 Umgebungsvariablen

> **Ehrlichkeitshinweis:** Diese Tabelle listet das Wesentliche für den Betrieb — sie umfasst **nicht** jede
> Umgebungsvariable, die der Code lesen kann (eine Prüfung zählte ~259 Verweise auf Umgebungsvariablen
> im Code). Fehlt eine Variable in dieser Tabelle, liegt das an der Kürze des Handbuchs,
> nicht an der Behauptung, dass es die Variable nicht gibt.

| Variable | Zweck |
|---|---|
| `OO_DATA_DIR` | Überschreibt das Datenverzeichnis (siehe oben). |
| `OO_HOST` / `OO_PORT` | Bindungsadresse/-port (Standard `127.0.0.1:8000`). |
| `OO_AUTOSEED` | Befüllt beim ersten Lauf den weltweiten Katalog (standardmäßig an; `0` zum Deaktivieren). |
| `OO_NO_SCHEDULER` | Auf `1` setzen, um den Hintergrund-Planer nie automatisch zu starten; die App startet dann online statt im Flugmodus. Der Socket-Schutz des Flugmodus wird in jedem Fall installiert (nur `OO_AIRPLANE_SOCKET_GUARD=0` lässt ihn weg), sodass ein späteres Einschalten des Flugmodus ausgehende Verbindungen weiterhin auf Socket-Ebene blockiert (die wenigen verbleibenden Ausnahmen sind in SECURITY.md aufgeführt). |
| `OO_NO_INDEX` | Auf `1` setzen, um die automatische Indizierung für Einblicke zu überspringen. |
| `OO_CUSTODY_ON_INGEST` | Veralteter Standard für die automatische Verwahrungsprotokollierung beim Erfassen (die Einstellung in der Oberfläche hat Vorrang, sobald sie gespeichert ist). |
| `OO_KEY_PASSPHRASE` | Verschlüsselt private Verwahrungsschlüssel im Ruhezustand (AES-256-GCM über scrypt). Ohne sie umhüllt die Datenbank-Passphrase die Schlüssel; ohne beide werden die Schlüssel mit `0600` im Klartext geschrieben und ehrlich als `plaintext-0600` gemeldet. |
| `OO_FETCH_TIMEOUT` / `OO_FETCH_MIN_INTERVAL` | Stellt Zeitlimit und Mindestabstand pro Host des ethischen Abrufers ein. |
| `OO_LLM_MODEL` / `OO_OLLAMA_URL` (oder `OLLAMA_BASE_URL`) | Standardmäßiges lokales Modell und Ollama-Endpunkt. |
| `OO_ALLOW_BIG_SCANS` | Auf `1` setzen, um die Hintergrund-Scans über den ganzen Korpus auf einem Rechner unterhalb der Speichergrenze auszuführen (siehe [Speicher auf einem kleinen Rechner](#55a-speicher-auf-einem-kleinen-rechner--die-einzige-echte-obergrenze)). Die Einschätzung meldet dann, dass Sie sie übergangen haben. |
| `OO_CKPT_GATE_TIMEOUT_S` | Wie lange der WAL-Checkpoint zwischen zwei Durchläufen auf die Einzelschreiber-Sperre wartet, bevor er ein ehrliches Überspringen festhält und weitermacht (Standard `30`). `0` stellt das alte unbegrenzte Warten wieder her (der eigene Checkpoint des Speicherschutzes wartet weiterhin höchstens 30 s auf die Schreibsperre, in einem eigenen Thread, sodass eine erzwungene Fortsetzung beobachtet bleibt). |
| `OO_STORAGE_GUARD` | Auf `0` setzen, um den Speicherschutz abzuschalten (keine Messungen, keine Pause). Der Schutz pausiert die Erfassung von selbst, wenn das Write-Ahead-Log der Datenbank über eine an Ihren Rechner angepasste Grenze hinausgewachsen ist oder das Laufwerk fast voll ist, und setzt sie von selbst fort; „Trotzdem fortsetzen“ in der Meldung erzwingt die Erfassung, solange die Grenze noch besteht, und endet von selbst, wenn der freie Speicherplatz zu stark sinkt oder nicht gelesen werden kann, wenn ein Schreibvorgang mangels Platz fehlschlägt oder wenn eine zweite Grenze überschritten wird. Dieselbe Pause hält, solange sie dauert, auch die Hintergrund-Neuindizierung an, die einen unterbrochenen Import abschließt, sowie den einmaligen Aufbau der Indizes der Artikelliste (ihre Zeilen im Task-Manager sagen das, und sie laufen von selbst weiter; „Trotzdem fortsetzen“ erzwingt die Erfassung, nicht diese). |
| `OO_DAMAGE_GUARD` | Auf `0` setzen, um die Pause abzuschalten, die auf eine Meldung der Datenbank über eine Beschädigung in einer Ihrer Datendateien folgt (die Meldung selbst wird weiterhin in `database-damage.json` in Ihrem Datenordner festgehalten, und die Mitteilung sagt dann, dass die Pause aus ist). Ohne sie wird in eine Datei, die die Datenbank als beschädigt meldet, weder von der Erfassung noch von den Wartungsschritten noch vom Wikipedia-Strang geschrieben (jeweils nur für die eigene Datei), bis Sie die Erfassung erneut starten (bei der Wikipedia-Datei: bis Sie den Wikipedia-Abruf aus- und wieder einschalten). Eine Pause, die die Startprüfung gesetzt hat (siehe `OO_BOOT_VERIFY`), endet erst, wenn die von der Prüfung genannten Tabellen wieder fehlerfrei gelesen werden; jede andere Pause endet und setzt beim ersten fehlgeschlagenen Lesevorgang wieder ein, falls die Beschädigung noch besteht. Unabhängig von `OO_STORAGE_GUARD`. |
| `OO_BOOT_VERIFY` | Auf `0` setzen, um die Prüfung Ihrer Datendateien abzuschalten, die beim Start läuft, während die App noch offline ist, nach einem unerwarteten Ende (und nachdem eine frühere Prüfung unvollendet blieb oder eine Beschädigung fand): Jede Tabelle wird einmal mit SQLites `PRAGMA quick_check` gelesen, eine Tabelle nach der anderen, über eine schreibgeschützte Verbindung, sodass die Prüfung selbst nichts schreibt. Eine Tabelle, die Tabellenliste oder die Seitenprüfung, die eine Beschädigung meldet, wird ein zweites Mal über eine neue Verbindung gelesen und zählt nur dann als beschädigt, wenn der zweite Lesevorgang übereinstimmt: Ein zweiter Lesevorgang, der abweicht oder nicht möglich ist, lässt sie mit Angabe des Grundes ungeprüft, und deswegen wird nichts pausiert oder repariert. Bei einer verschlüsselten Datei fragt sie, wenn für eine Tabelle keine Antwort möglich war (SQLCipher löst bei vielen beschädigten Seiten einen allgemeinen Fehler aus), außerdem einmal SQLCiphers eigene Seitenprüfung ab (`PRAGMA cipher_integrity_check`, etwa eine Sekunde pro 230 MB) und hält fest, welche Seiten ihre Authentifizierung nicht bestehen (eine Datei größer als 4 GiB wird dieser Seitenprüfung nicht übergeben, weil sie jenseits dieser Grenze die falschen Bytes liest; der Eintrag sagt das, und die Datei wird nicht als fehlerfrei bezeichnet); eine Datei mit fehlschlagenden Seiten ist beschädigt, und eine Datei, deren Seiten alle bestehen, wird trotzdem nicht als fehlerfrei bezeichnet, solange eine Tabelle unbeantwortet ist. Eine Seite, die überhaupt nicht gelesen werden konnte (ein ausfallendes Laufwerk), wird gesondert gezählt und ist für sich allein kein Befund, und ein Beenden während dieser Prüfung verbraucht keinen der drei Versuche. Die Erfassung wartet, bis sie endet; eine als beschädigt erkannte Datei wird pausiert (siehe `OO_DAMAGE_GUARD`), und ein erneuter Start der Erfassung liest die genannten Tabellen noch einmal, bevor die Pause aufgehoben wird (bei der Wikipedia-Datei geschieht das durch Aus- und Wiedereinschalten des Wikipedia-Abrufs). Eine Prüfung, die nicht abgeschlossen werden kann, wird nach drei Starts in Folge nicht erneut versucht, und die App sagt das (diese Sperre gilt über jeden normalen Start hinweg, bis die App das nächste Mal unerwartet endet, was ein neuer Grund zur Prüfung ist); das hebt nie einen Befund auf: Eine Datei, die eine frühere Prüfung als beschädigt befand, bleibt pausiert, bis die genannten Tabellen fehlerfrei gelesen werden (oder die Datei ersetzt wird). Das Ergebnis jeder Datei steht in `database-damage.json` in Ihrem Datenordner. |
| `OO_BOOT_REPAIR` | Auf `0` setzen, um die Reparatur einer beschädigten Bibliotheksdatei abzuschalten (und damit auch die unten beschriebene Entfernung). Standardmäßig repariert die App, wenn die Startprüfung (siehe `OO_BOOT_VERIFY`) eine Tabelle Ihrer Bibliotheksdatei als beschädigt liest, die Datei bei diesem Start, während sie noch offline ist und bevor die Erfassung etwas schreibt: Sie kopiert jede noch lesbare Zeile, Tabelle für Tabelle, in eine neue Datei daneben, baut die Indizes und den Suchindex neu auf, prüft die neue Datei mit demselben tabellenweisen Lesen und wechselt erst dann zu ihr. Zeilen auf Seiten, die nicht gelesen werden konnten, sind nicht in der neuen Datei; die Mitteilung sagt, wie viele Einträge kopiert wurden und wie viele nicht gelesen werden konnten, und in welchen Tabellen sie standen. Zeilen, deren übergeordnete Zeile nicht gelesen werden konnte, werden behalten, nie entfernt, und pro Tabelle gezählt; wo eine Tabelle sonst die Nummer einer verlorenen Zeile an die nächste gespeicherte Zeile vergeben würde, fügt die Reparatur EINE Platzhalterzeile mit der Kennzeichnung «(lost …)» bei der höchsten verlorenen Nummer ein (es ist eine sichtbare Zeile, und der Suchindex findet sie unter dieser Kennzeichnung), und die Mitteilung nennt diese Tabellen. Alles, was die App speichert, wartet, während sie arbeitet (die Reparatur braucht die Schreibsperre, die standardmäßig an ist: mit `OO_WRITE_GATE=0` lehnt sie ab und sagt das), und wenn dennoch während des Kopierens etwas in die Datei gespeichert wurde, wird die Kopie verworfen und beim nächsten Start neu angefertigt, statt über diese Speicherung hinweg eingewechselt zu werden. Sie braucht freien Speicherplatz für die ganze Datei plus ihr Log plus die Reserve, die der Festplattenschutz vorhält, und ein Laufwerk, das einer Datei einen zweiten Namen geben kann (ein Hardlink); sie sagt, was davon fehlt, und ändert nichts, wenn es fehlt. Repariert wird nur die Bibliotheksdatei, und nur nachdem die eigene Prüfung dieses Starts eine Beschädigung fand: Die Wikipedia- und Gesetzesdateien werden wie bisher pausiert, aber nicht repariert, eine Datei, die während des Betriebs als beschädigt erkannt wird, wird beim nächsten Start geprüft und dann repariert, wenn die Prüfung es bestätigt, und eine Tabelle, die die Prüfung nicht lesen konnte, ist kein Befund. **Die beschädigte Datei wird behalten, nicht gelöscht:** Die Reparatur gibt ihr neben der neuen Datei einen zweiten Namen, `<name>.damaged-<date and time>.<ending>` (mit ihrem Log unter demselben Namen und `-wal`), weil sie noch Zeilen enthalten kann, die die Kopie nicht lesen konnte, für ein Wiederherstellungswerkzeug. **Die App entfernt genau diese eine Datei 30 Tage, nachdem die neue Datei erstmals fehlerfrei gelesen wurde**, beim ersten Start an oder nach diesem Datum, nie während eine Reparatur oder Prüfung läuft oder während die Bibliothek erneut als beschädigt gemeldet wird; die Reparaturmitteilung und das Diagnose-Zip sagen, wie groß sie ist, wo sie liegt und welches Datum gilt, und nach der Entfernung, dass sie entfernt wurde und wie groß sie war. Konnte das Laufwerk selbst eine Seite Ihrer Bibliotheksdatei nicht lesen (die Mitteilung sagt, wie viele Seiten), entfernt die App diese Datei überhaupt nicht, weil ein ausfallendes Laufwerk der Grund sein kann, warum die Seiten nicht gelesen werden konnten: Sie bleibt, bis Sie sie selbst entfernen, und die Mitteilung rät, das Laufwerk zu prüfen. Mit `OO_BOOT_REPAIR=0` ist die Entfernung aus, und die Mitteilung sagt das. Sie können sie jederzeit selbst entfernen. Gelöscht wird nur die Datei, die die Reparatur beiseitegelegt hat (sie muss in Ihrem Datenordner liegen, eine gewöhnliche Datei sein, genau diesen Namen tragen und dieselbe Datei sein, die die Reparatur festgehalten hat), und sonst nichts; trifft etwas davon nicht zu, entfernt sie nichts, sagt das und versucht es nicht erneut. Eine Reparatur, die begann und nicht endete, wird beim nächsten Start erneut versucht; auf zwei aufeinanderfolgende Starts, die mitten in der Reparatur endeten, folgt kein dritter Versuch, bis die App aktualisiert wird (der Eintrag ist `database-repair-attempt.json` in Ihrem Datenordner). Der Eintrag jeder Reparatur (das Datum, die Zahlen, der Name der Datei und, sobald sie erfolgt, ihre Entfernung) steht in `database-damage.json`; dort werden die letzten zehn aufbewahrt, und eine aufbewahrte Datei, deren Eintrag aus diesen zehn herausgefallen ist, wird von der App nie entfernt. |
| `OO_ARTICLE_INDEXES` | Auf `0` setzen, um die beiden Indizes der Artikelliste nicht aufzubauen. Standardmäßig baut die App sie einmal auf, beim ersten Start nach einem Update, während sie noch offline ist: einen für den Sprachfilter und einen für die Sortierung nach Titel, damit beide schnell bleiben, wenn die Bibliothek wächst (sie belegen etwa 190 MB pro 1,5 Millionen Artikel). Bei einer großen Bibliothek auf einem langsamen Laufwerk kann der Aufbau einige Minuten dauern; er erscheint im Task-Manager als „Die Indizes der Artikelliste werden aufgebaut“, alles, was die App speichert, wartet, bis er fertig ist, und er braucht zwei Dinge, die er zuerst misst und zu denen er sich äußert, ohne zu beginnen, wenn eines davon knapp ist: etwa 400 Byte freien Speicherplatz pro Artikel auf dem Laufwerk, auf dem Ihre Datendatei liegt, und Arbeitsspeicher für das Sortieren der Titel (etwa 300 Byte pro Artikel, im Arbeitsspeicher gehalten und nie in eine temporäre Datei geschrieben, plus den freien Arbeitsspeicher, den die App immer für sich selbst vorhält; sie nennt die Zahlen). Ein Start, der mitten im Aufbau endet, beginnt ihn erneut; auf zwei aufeinanderfolgende Starts, die mitten im Aufbau enden (dem Rechner ging der Arbeitsspeicher oder der Strom aus), folgt kein dritter Versuch, bis die App aktualisiert wird, weil ein Aufbau, der selbst die App zum Absturz bringt, nicht zu einem Start werden darf, der nie fertig wird (der Eintrag dazu ist `article-indexes-attempt.json` in Ihrem Datenordner; wenn Sie ihn löschen, versucht es die App erneut, und ein normales Beenden der App gibt den Versuch zurück). Bei abgeschaltetem Schalter oder nach einer sich wiederholenden Ablehnung verbringt jeder Start einen Sekundenbruchteil damit, die Version der Datenbank mit ihren Tabellen abzugleichen. Bei abgeschaltetem Schalter funktioniert die Liste wie bisher, nur bei diesen beiden Auswahlmöglichkeiten langsamer. |
| `OO_WAL_HIGH_MB` / `OO_DISK_RESERVE_MB` | Ersetzt die beiden abgeleiteten Grenzen des Speicherschutzes durch eine Zahl in MB: die Größe des Write-Ahead-Logs, ab der die Erfassung pausiert, und den freien Speicherplatz, unterhalb dessen sie pausiert (Standard: an Ihren Rechner angepasst; die Grenzen stehen in der Mitteilung, die der Schutz im Task-Manager anzeigt, solange er die Erfassung anhält). |
| `OO_STORAGE_GUARD_TRIP_AFTER` / `OO_STORAGE_GUARD_RESUME_AFTER` | Wie viele aufeinanderfolgende Messungen (im Abstand von etwa fünf Sekunden) den Schutz auslösen bzw. aufheben (Standard `2` und `2`). |
| `OO_WRITE_GATE_WARN_S` | Schreibt eine Warnung ins Protokoll, mit dem Namen des haltenden Threads und einem Stack, wenn ein einzelner Schreibvorgang die Sperre länger als diesen Wert hält (Standard `60`); die Warnung wird geschrieben, sobald das Halten bemerkt wird, daher ist ihre Zahl mindestens der Schwellenwert und nicht die Dauer des Haltens. Endet ein solches Halten, erhält das Protokoll eine zweite Zeile, `write gate released after 61.3s by 'name'` (die tatsächliche Dauer, auf eine Zehntelsekunde genau, anstelle von 61,3; Haltezeiten unter einer Sekunde erhalten sie nie). `OO_WRITE_GATE_WATCHDOG=0` schaltet die Überwachung ganz ab. |
| `OO_REINDEX_HOLD_TARGET_S` | Wie lange ein Stapel einer Neuindizierung die Einzelschreiber-Sperre halten darf, bevor er festschreibt und einen wartenden Schreiber hereinlässt (Standard `10`). Das gilt für die Hintergrund-Neuindizierung importierter Artikel, für den Neuindizierungsauftrag über den ganzen Korpus (wenn `OO_REINDEX_COMMIT_BATCH` über 1 liegt) und für die Neuindizierung am Ende einer Wiederherstellung. Er schreibt noch früher fest, beim nächsten Artikel, nachdem sich ein anderer Schreibvorgang dahinter eingereiht hat, sobald der Stapel die Sperre mindestens eine Sekunde gehalten hat (ein Halten kann das Ziel also um den gerade bearbeiteten Artikel und das Festschreiben überschreiten, und ein Schreiber, der ständig wartet, kostet die Neuindizierung etwa ein Festschreiben pro Sekunde statt eines pro Artikel). Die Stapelbreite (`OO_IMPORT_REINDEX_COMMIT_BATCH`, `OO_REINDEX_COMMIT_BATCH`) bleibt die Obergrenze, und bei einer Breite von `1` wird jeder Artikel einzeln festgeschrieben, es gibt also keinen Stapel, den das Ziel vorzeitig beenden könnte (der Bericht der Wiederherstellung und der Fortschritt des Neuindizierungsauftrags nennen trotzdem das geltende Ziel). `0` ist die alte Regel: nur bei der Stapelbreite festschreiben. Ein Wert, der keine Sekundenzahl größer oder gleich null ist, behält den Standard. |
| `OO_HEAVY_TAIL_WAIT_S` | Wie lange die Neuberechnung des Home-Briefings und die Hintergrund-Wartungsspur aufeinander warten, statt gleichzeitig zu laufen (Standard `900`). `0` wartet unbegrenzt. |
| `HTTPS_PROXY` | Leitet ausgehenden Verkehr (z. B. OpenTimestamps) über einen Proxy/Tor. |

### 5.3 Optionale Erweiterungen

Installation mit `pip install -e ".[extra]"`:

- **`analysis`** — Statistik, Schlagwort-/Entitätsanalysen, Marktkorrelation.
- **`nlp`** — spaCy-Modelle für echte Eigennamenerkennung in Einblicke.
- **`pqc`** — Post-Quanten-Signatur mit ML-DSA für die Verwahrungskette.
- **`timestamping`** — Verankerung mit OpenTimestamps (Bitcoin).
- **`dev`** — Test-/Lint-Werkzeuge.

Fehlt eine Erweiterung, **verschlechtert sich die abhängige Funktion lautstark** (ein klarer Fehler oder
ein `503`, ein ehrlicher Status „nicht installiert“) — sie täuscht die Fähigkeit nie stillschweigend vor.

### 5.4 Die HTTP-API

Die App ist ein FastAPI-Server auf `127.0.0.1:8000`; die Weboberfläche ist eine einzige
abhängigkeitsfreie `index.html`, ausgeliefert unter `/`. Das maschinenlesbare Schema liegt unter **`/openapi.json`**. Die interaktiven Seiten Swagger (`/docs`) und ReDoc
(`/redoc`) sind **standardmäßig aus**: Sie lassen den Browser Skripte, Stylesheets und eine Schrift von Drittanbieter-
Hosts laden, daher startet ein Entwickler, der sie haben möchte, die App mit `OO_API_DOCS=1`. Prometheus-Metriken unter `/metrics`. Es gibt bewusst **keine Authentifizierung**
(nur Loopback, ein einzelner Benutzer). Alle Endpunkte sind **ratenbegrenzt** (ungefähr: Lesen
100/h, Schreiben/Exporte 50/h, Löschen 20/h, Massenimporte 10/h; `429` mit
`Retry-After` bei Überschreitung).

Eine verdichtete Übersicht (siehe `/openapi.json` oder `/docs` mit `OO_API_DOCS=1` für das maßgebliche, stets aktuelle Schema und
`docs/ARCHITECTURE.md` für die Beschreibung in Textform):

**Kern & Suche** — `GET /api/health`; `GET /api/articles` (FTS + Filter);
`GET /api/articles/export` (csv|json); `GET /api/articles/{id}/view` (Offline-HTML);
`GET /api/sources`.

**Erfassung** — `POST /api/sources/seed-defaults`;
`POST /api/sources/{id}/ingest`; `POST /api/sources/{id}/ingest-email` (IMAP);
`POST /api/ingest` (einzelne URL).

**Quellen & Katalog** — vollständiges CRUD unter `/api/sources/…` (inkl. Stapeloperationen, Gruppen,
tagbasierte Gruppen, Metadaten, Erkennung, YAML-Import/-Export, Statistiken, Suche); CSV-
Katalog unter `/api/catalog/sources`, `/export.csv`, `/template.csv`, `POST /import`.

**Planer** — `GET /api/scheduler/status|config|targets`;
`PUT /api/scheduler/config`; `POST /api/scheduler/start|stop|run-now`.

**Datenbank & Sicherung** — `GET /api/database/stats|coverage|countries`;
`GET /api/database/backup` (roher `.db`-Schnappschuss; unter einem Namen, den Sie in `OO_ALLOWED_HOSTS` aufgeführt haben, muss eine Anfrage, die keine Herkunftsseite nennt, den Header `X-OO-Download: 1` hinzufügen, wie es `curl -H "X-OO-Download: 1" …` tut; wird die Adresse in einem Browser eingetippt oder ein Lesezeichen geöffnet, sendet ein solcher Name über reines HTTP nichts von dem, was ein Browser bei Loopback oder HTTPS hinzufügen würde, daher wird es dort abgelehnt). Sicherungen werden von den Streaming-
Engines **erstellt**: verschlüsselte Volumes+Parität unter `POST /api/backup/v2/volumes/start` (+ `/restore`,
`/cancel`, `GET /volumes/status`) und die Ordnerkopie für große Datenmengen unter
`POST /api/backup/folder/start` (+ `/plan`, `/restore`, `/{action}`, `GET /folder/status`).
Die Wiederherstellung eines älteren Einzeldatei-Archivs ist die **additive Zusammenführung**:
`POST /api/backup/v2/restore/preview`, `POST /api/backup/v2/restore/commit`,
`GET /api/backup/v2/batches`. *(Die destruktiven `POST /api/database/restore` und
`/api/safety/restore/encrypted` wurden entfernt.)*

**System & Netzwerk** — `GET /api/system/vitals|network|interfaces`;
`POST /api/system/network` (Flugmodus-Schalter); `GET /api/system/doctor|lock-state`;
`POST /api/system/unlock|create-db|encrypt-db`. **Aufträge / Task-Manager** —
`GET /api/jobs`; `POST /api/jobs/dumps/reorder`; `POST /api/jobs/{id}/cancel`.

**Weltkarte** — `GET /api/timemap` (Raum-Zeit-Signale; `?kinds`, `?start`/`?end`
Zeitfenster in Bruchteilen von Jahren, `?hazards`, `?articles`, `?mentions`, `?days`); `GET /api/timemap/range`.

**Datums-Tags von Artikeln** — `GET/POST /api/article-dates/article/{id}` (auflisten / extrahieren);
`POST /api/article-dates/{tag_id}/confirm|reject`; `POST /api/article-dates/index`;
`GET /api/article-dates/by-date`.

**Einblicke** — `GET/PUT /api/insights/filter`; `POST /api/insights/exclude|include`;
`GET /api/insights/status`; `POST /api/insights/reindex`;
`GET /api/insights/top|trending|trend|associations|context|map`; korpusweite
**Wann×Wo×Wer**-Zusammenfassungen unter `GET /api/insights/who|where`.
**Framing** — `GET /api/framing`.

**Suche (Omnibar)** — `GET /api/search/omni` (indexgestützte Föderation über Artikel,
Schlagwörter, Quellen, beobachtete Wikipedia-Seiten und verfolgte Gesetze).

**Links** — `GET /api/links/shared` (welche Mitgliedsartikel ausgehende Links teilen, mit
Hinweisen zur Unabhängigkeit); `GET /api/links/preview` (lokale Extraktion der Link-Vorschau).

**Agenda-Ereignisse** — `GET /api/events/calendars|feeds|imported`;
`GET /api/events/astronomy` (lokal berechnete Mondphasen — Neumond, erstes Viertel, Vollmond, letztes Viertel — + Tagundnachtgleichen/Sonnenwenden, gegen den
Almanach geprüft) und `GET /api/events/climate` (mitgelieferter El-Niño-Datensatz). **Wetterkontext** —
`POST /api/weather/context` (korpusgesteuerte Ausschnitte der Open-Meteo-Reanalyse, mit Einwilligung).

**Märkte & Rohstoffe** — `/api/markets/rules` (CRUD + `/run`),
`/api/markets/overview|series|feeds`, `/api/markets/feeds/{key}/import`,
`/import-all`, `/import-url`; `/api/commodities/{symbol}/prices` (+ `/import-csv`,
`/correlation`).

**Regierungen** — Indikatoren der Weltbank pro Land + die Choroplethenkarte, nur lesend
außer dem einen Abruf mit Einwilligung: `GET /api/governments/indicators|map|country/{iso}`;
`POST /api/governments/load-standard` (+ `/load-standard/status`, ein Hintergrundauftrag).
**Weltrecht** — verfolgte Gesetze/Amtsblätter/IP-Register, ein Recherche-Spiegel (nie eine Rechts-
beratung): `GET /api/law/status|documents|documents/{id}|documents/{id}/view|changes`;
`POST /api/law/documents` (ein Dokument per URL hinzufügen — wird sofort abgerufen);
`DELETE /api/law/documents/{id}` (Verfolgung beenden; der Verlauf bleibt erhalten); `POST /api/law/track`
(jedes beobachtete Dokument jetzt abrufen) und `/api/law/seed` (den weltweiten Katalog neu befüllen).
Ein verfolgtes Dokument wird zu einem vollwertigen, durchsuchbaren Korpusartikel (Wann×Wo×Wer,
Schlagwörter) neben gesammelten Nachrichten, mit seinem Änderungsverlauf als verknüpfter Ebene.

**Wikipedia** — `GET /api/wiki/status|pages|changes`; `POST /api/wiki/pages`,
`/track-now`, `/pages/{id}/track`; `GET /api/wiki/revisions/{id}`;
`GET /api/wiki/languages` (eine **flache Liste, UI-Sprachen zuerst**, jede Option beginnt mit dem
Namen in der eigenen Sprache; `region` bleibt nur als beschreibende Metadaten erhalten — keine Kontinent-`groups`;
`?scope=dumps` fügt eingebettete `~GB`-Größenschätzungen hinzu); Dumps unter `/api/wiki/dumps…`.

**Verwahrungskette** — `POST /api/custody/log`; `GET /api/custody/{item}` (+
`/verify`); `POST /api/custody/verify`; `GET /api/custody/export`;
`GET /api/custody/providers`; `POST /api/custody/anchor`;
`GET/PUT /api/custody/settings`; `POST /api/custody/reconcile` (ein INGEST-Eintrag, der
beim Speichern seines Artikels nicht geschrieben werden konnte, wird vorgemerkt und später geschrieben, am Ende
des nächsten Erfassungsdurchlaufs, solange die automatische Protokollierung an ist, in seinen eigenen signierten Metadaten als verspätet markiert --
der Tab „Verwahrungskette“ zählt sie, und seine
Schaltfläche „Nach fehlenden Erfassungseinträgen suchen“ zählt ältere Lücken, ohne etwas festzuhalten,
bis Sie „Eintragen, als verspätet markiert“ drücken). **Belege** — `POST /api/reports/evidence`
(+ `/verify`).

**LLM (lokales Ollama)** — `GET /api/llm/health|models`; `POST /api/llm/generate`;
`POST /api/llm/articles/{id}/summarize|translate`.

**Sonstiges** — `/api/analysis/*` (t-Tests, Korrelation, ANOVA, …);
`/api/keywords/*` (Extraktionswerkzeuge); `/api/monitoring/health|anomalies`;
`POST /api/verify/image-metadata` (EXIF/GPS).

### 5.5 Betrieb über Tor

Die App funktioniert über Tor (Abrufmodus „Geschützt“ → ein Tor-Proxy, den Sie selbst betreiben), mit einer
ehrlicherweise geringeren Reichweite — gemessen, nicht geschätzt (Live-Protokoll 2026-06-12: 32 von 50
Standardquellen in einem Durchlauf über Tor importiert):

- **Ablehnungen einzelner Verbindungen sind normal, nicht fatal.** Manche Hosts lehnen manche
  Tor-Exits ab: Im selben Lauf wurden 21/28 FRED-Zeitreihen importiert, während andere fehlschlugen.
  Deshalb tragen Feed-Fehler eine **transportbewusste Einschätzung** — *abgelehnt*
  („Verbindung abgelehnt/zurückgesetzt — über Tor ist das oft die Ablehnung eines einzelnen
  Exits; ein erneuter Versuch landet häufig auf einem anderen Circuit“) ist nicht *robots
  verbietet* (die erklärte Richtlinie des Hosts, die wir respektieren und nie wiederholen oder
  umgehen), ist nicht *tote Zeitreihe* (HTTP 404 — der Katalogeintrag braucht einen
  Ersatz; ein erneuter Versuch kann nicht helfen), ist nicht *unerreichbar*. Vorübergehende
  Fehler werden einmal automatisch wiederholt; die Schaltfläche **Fehlgeschlagene Feeds erneut versuchen**
  führt genau die ehrlich wiederholbaren erneut aus.
- **Die Tor-Sperre eines Hosts ist die Entscheidung des Hosts.** Wir machen sie sichtbar; wir umgehen nie
  robots, Sperren oder CAPTCHAs. Bevorzugen Sie Tor-tolerante offizielle Endpunkte, wo
  es sie gibt.
- **Modell-Downloads funktionieren nicht über Tor.** Ollama lädt seine Modelle über das offene
  Internet mit seinem eigenen Prozess herunter (Installation/Download unter **Einstellungen → KI**); ein funktionierender
  Clearnet-Weg ist eine ausdrücklich genannte Voraussetzung für das Herunterladen eines Modells. Ist es einmal heruntergeladen, läuft die Inferenz
  über Loopback und ist nicht betroffen. *(Ein vorgefertigtes Offline-LLM-Paket ist geplant, aber noch nicht ausgeliefert.)*
- **Bricht die vLLM-Installation mittendrin ab**, liegt das fast immer an einem Download, der bei einem
  der sehr großen Wheels in ein Zeitlimit läuft — torch allein hat rund 500 MB. Die Meldung nennt
  es, und bereits heruntergeladene Wheels werden zwischengespeichert, sodass ein erneuter Start der Installation fortsetzt,
  statt von vorn zu beginnen. Bei einer Verbindung, die so langsam ist, dass es immer wieder scheitert, erhöhen Sie
  `UV_HTTP_TIMEOUT` (in Sekunden), bevor Sie die App starten.
- **Startet der vLLM-Server und stirbt immer wieder**, wird der Grund festgehalten, ob Sie
  zugesehen haben oder nicht: Jeder Start und jedes Ende landen in
  `vllm_start_attempts.jsonl` mit dem Wortlaut des Fehlers, und das vollständige Protokoll
  jedes der letzten paar fehlgeschlagenen Starts wird in `vllm_failed_starts/` aufbewahrt — beides im
  Datenverzeichnis, sodass eine Neuinstallation von vLLM sie nicht löscht. Beides ist im Export
  **Diagnose → alle Diagnosen (all diagnostics)** enthalten, die Antwort steckt also im Paket, statt
  dass man sie live erwischen müsste.
- **Für Anonymität bleiben Sie selbst verantwortlich**: Der geschützte Modus kann keine
  Anonymität garantieren — Sie betreiben den Proxy und vertrauen ihm; der Beitrag der App besteht darin, ihre Web-
  Abrufe mit einem generischen User-Agent darüber zu leiten, außer bei ihren API- und Dump-
  Anfragen an die Server von Wikimedia, die das Werkzeug weiterhin nennen (die API-
  Richtlinie von Wikimedia verlangt das). Das Abholen aus dem Newsletter-Postfach, die Verankerung mit OpenTimestamps und
  die Downloads für die lokale KI verbinden sich direkt.

---

### 5.5a Speicher auf einem kleinen Rechner — die einzige echte Obergrenze

Die App verkleinert sich auf einem kleinen Rechner bereits selbst: unter **4 GB RAM** oder mit
weniger als **1 GB frei** nutzt sie einen kleineren Datenbank-Cache und weniger gepoolte
Verbindungen, begrenzt, wie viele Quellen sie gleichzeitig abruft, und **pausiert die
Hintergrund-Scans über den ganzen Korpus** (Quellenqualifizierung). Sie teilt Ihnen das mit, samt
Zahlen, neben dem Erfassungsstatus unter Einstellungen → Erweitert → Erfassung.

**Die Kosten klar ausgesprochen:** Auf einem Rechner mit großem Korpus und wenig freiem
Arbeitsspeicher kann das bedeuten, dass die Quellenqualifizierung dort nie läuft. Das sind die Kosten
der Einstellung, kein Fehler. Um die Scans trotzdem auszuführen, starten Sie die App mit
`OO_ALLOW_BIG_SCANS=1` — die Einschätzung meldet dann, dass Sie sie übergangen haben, und sie
meldet weiterhin, dass der Rechner klein ist, denn die Übersteuerung ändert, was die
App *tut*, nie, was sie *gemessen* hat.

#### Eine schwere Ansicht stoppt, bevor sie die App zum Absturz bringen kann

Die schweren Analyse-Lesevorgänge (die meisten Ansichten in Einblicke, die Sternwarte, die meistzitierten
Quellen, das Diagnosepaket) laufen bereits mit einem Zeitlimit. Außerdem
beobachten sie den verfügbaren Arbeitsspeicher, während die Datenbank ihnen Zeilen liefert. Fällt er auf die
Untergrenze des Speicherschutzes (standardmäßig **256 MB**, `OO_MEM_GUARD_AVAIL_MB`), wird der Lesevorgang
gestoppt, und die Ansicht sagt, warum, mit den Zahlen: *„stopped this read after
12s: the machine was nearly out of memory (180 MB available, at or below the
256 MB floor the memory guard uses) ...“* (dieser Lesevorgang wurde nach 12 s gestoppt: Der Rechner hatte fast keinen Arbeitsspeicher mehr (180 MB verfügbar, auf oder unter der Untergrenze von 256 MB, die der Speicherschutz verwendet) ...). Ein Lesevorgang, der angefordert wird, wenn der Arbeitsspeicher
bereits so knapp ist, beginnt gar nicht erst und sagt stattdessen *„did not start this read“* (dieser Lesevorgang wurde nicht gestartet).
Öffnen Sie die Ansicht erneut, sobald sich der Arbeitsspeicher erholt hat; nichts ging verloren,
denn ein Lesevorgang ändert nichts.

**Was es nicht tut:** Es ist ein Stopp, keine Obergrenze. Es sieht, was wächst, während Zeilen
gelesen werden — dort wächst eine Ansicht, die eine ganze Tabelle lädt —, und
sonst nichts. `OO_READ_MEMORY_STOP=0` schaltet es ab, ohne den Schutz anzutasten.

#### Bleibt der Arbeitsspeicher erschöpft, beendet sich die App selbst und sagt das

Der Speicherschutz pausiert neue Erfassungen, wenn der Arbeitsspeicher knapp ist. Eine Pause gibt nicht
zurück, was die App bereits hält, daher kann der Arbeitsspeicher auf einem kleinen Rechner viele Minuten
an der Untergrenze bleiben, und dann beendet das Betriebssystem die App ohne ein
Wort der Begründung. Die App beendet sich jetzt stattdessen selbst. Das tut sie nur, wenn **all**
dies zutrifft: Der Schutz war während der gesamten letzten **5 Minuten** aktiv
(`OO_MEM_STOP_WINDOW_S`), mindestens neun von zehn seiner Messwerte lagen auf oder unter
**64 MB** verfügbar (`OO_MEM_STOP_AVAIL_MB`), keiner lag über 128 MB, keine Lücke zwischen
Messwerten war länger als ein Zehntel des Zeitfensters (30 s), und diese App hält mindestens ein Drittel
des Arbeitsspeichers des Rechners (hält etwas anderes ihn, würde ein Beenden nichts freigeben,
und die App beendet sich nicht). Eine Erholung, auch eine kurze, oder ein Druck auf Starten oder
Fortsetzen leert das Zeitfenster.

Bevor sie sich beendet, bewahrt sie, was sie weiß: einen Schnappschuss dessen, was jeder Thread gerade
tat, eine Zeile im Sitzungsprotokoll und `memory_stop.json` neben Ihren Daten
(Zahlen und Schrittnamen, höchstens 8 KB). Dann beendet sie sich über denselben Weg wie
der Ein/Aus-Knopf. Ihre gespeicherten Daten werden nicht angetastet; sie wartet zunächst bis zu einer Minute,
bis ein Importlauf, ein Hintergrundauftrag, der den Korpus hält, oder ein laufender Datenbank-Schreibvorgang
abgeschlossen ist (eine Wiederherstellung oder ein Umzug des Datenlaufwerks wird als laufend festgehalten, aber
nicht als solcher abgewartet), hält im Eintrag fest, ob noch einer lief, und was in dieser Zeit nicht
fertig werden konnte, wird nicht fertig.
Während sie das tut, sagt der Task-
Manager *„Die App beendet sich selbst, weil der Speicher erschöpft blieb“*.
Beim nächsten Start zeigt die Zeile **Sitzungen** im Tab System *„Selbst beendet —
der Speicher blieb erschöpft“* (mit der Maus darüberfahren für den Vorbehalt), eine einmalige Meldung sagt
dasselbe, und das Diagnose-Zip enthält den Eintrag. **Was endet, ist das, was
lief; Sie starten es erneut.** `OO_MEM_STOP=0` schaltet das Beenden ab und lässt die
Pause bestehen.

#### Warum die App ihren eigenen Arbeitsspeicher nicht einfach begrenzen kann

Es gibt keinen ehrlichen Weg, wie ein Programm sich selbst eine Speicherobergrenze auferlegen kann:

- **`RLIMIT_RSS` wird von Linux ignoriert.** Es existiert in der API und bewirkt nichts.
- **`RLIMIT_AS` begrenzt den *Adressraum*, nicht den genutzten Arbeitsspeicher.** Bibliotheken, die diese App
  verwendet (DuckDB, numpy), reservieren weit mehr virtuellen Adressraum, als sie je
  berühren, daher löst eine Adressraum-Obergrenze in unbeteiligtem Code `MemoryError` aus, lange
  bevor der Prozess tatsächlich groß ist. Die App setzt bewusst keine von beiden, und ein
  Test lässt den Build fehlschlagen, falls je eine hinzugefügt wird.

#### Die Obergrenze, die funktioniert: in einer cgroup ausführen

Unter Linux mit systemd starten Sie die App mit einer harten Speichergrenze:

```bash
systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0 \
  ~/open-omniscience/scripts/launch.sh
```

**Was das ehrlich bringt:** Es verwandelt ein *Einfrieren des Desktops* in einen *sauberen Neustart
der App*. Ohne Grenze lagert ein Rechner, dem der Arbeitsspeicher ausgeht, so lange aus, bis er
für alles unbrauchbar ist — den Browser, das Terminal, den Desktop —, und Sie müssen ihn
womöglich aus- und wieder einschalten. Mit einer Grenze beendet der Kernel stattdessen **diese App**, und
nur diese App.

**Was es kostet:** Die App wird mitten in der Arbeit beendet, ohne Gelegenheit zum Aufräumen.

**Warum Ihr Korpus trotzdem sicher ist:** Die Datenbank läuft im WAL-Modus mit
`synchronous=NORMAL`, daher kann ein Beenden nur Arbeit verlieren, die nie festgeschrieben wurde.
Alles Festgeschriebene liegt auf der Festplatte, und das Write-Ahead-Log wird beim nächsten
Entsperren erneut eingespielt. **Nichts, was Sie bereits gesammelt hatten, geht verloren.**

Eine auf diese Weise unterbrochene **Sicherung** ist etwas anderes: Sie bleibt unvollständig.
Ihr wird aber nicht stillschweigend vertraut — jedes Volume trägt eine Prüfsumme im
Manifest, und der eigene Prüfschritt der Sicherung prüft alle und nennt diejenigen,
die fehlen oder nicht übereinstimmen. Führen Sie eine Prüfung durch (oder erstellen Sie die Sicherung einfach neu),
bevor Sie sich auf eine unterbrochene verlassen.

Wählen Sie `MemoryMax` bei ungefähr **60–75 % des gesamten RAM**, damit Platz für den
Desktop und den Browser bleibt. `MemorySwapMax=0` ist die Hälfte, die das Auslagerungschaos verhindert:
Ohne sie kann die App den Rechner immer noch durch Auslagern in Zeitlupe versetzen, bevor die Grenze
erreicht ist.

Wenn Sie nicht mit systemd arbeiten, steht dasselbe über Docker/Podman
(`--memory=3g --memory-swap=3g`) oder ein einfaches cgroup-v2-`memory.max` zur Verfügung.

#### Nach einem Absturz: was der nächste Start Ihnen sagen kann

Wird die App beendet oder stürzt sie ab, bleibt das Startfenster jetzt offen und sagt,
wie sie endete: `SIGKILL` ist das übliche Kennzeichen eines Prozessbeenders bei Speichermangel. Ein gewöhnliches
Beenden (die eigene Stopp-Schaltfläche der App, das Schließen des Fensters, das Abmelden) schließt das
Fenster wie bisher.

Der nächste Start sagt dann, wie die vorherige Sitzung endete, unter **Einstellungen →
Erweitert → Diagnose → Sitzungsforensik** und in `session-forensics.json`
im Diagnose-Archiv, anhand derjenigen dieser Zeugen, die geantwortet haben:

- der Aufzeichnung des Startprogramms über den Exit-Status (`diagnostics/launcher_exits.jsonl`);
- des Kernel-Protokolls, das die eigenen Out-of-Memory-Beendigungen des Kernels nennt;
- der Protokollzeilen der Speicher-Killer im Benutzerbereich (systemd-oomd, earlyoom,
  nohang) und von systemd-coredump, die die App nennen. Diese erscheinen nie im
  Kernel-Protokoll, und systemd-oomd nennt die cgroup der App statt ihres Prozesses;
- eines Absturz-Traces aller Threads, wenn nativer Code abbricht
  (`diagnostics/crash_trace.log`).

Die Protokoll-Lesevorgänge sind lokal und nur lesend, und sie behalten nur Zeilen über diese App.
`OO_NO_KERNEL_LOG=1` schaltet sie ab; `OO_CRASH_TRACE=0` schaltet den Trace ab.
Die Speicher-Killer schreiben in das Systemjournal, das nur Mitglieder von `adm` oder
`systemd-journal` (`wheel` unter Fedora) lesen können; kann Ihr Konto das nicht, sagt der Bericht
das, statt das Protokoll als leer zu bezeichnen. Ganz ohne Zeugen sagt der Bericht,
dass das Ende unbekannt ist, nie, dass es sauber war.

Derselbe Bericht sagt, woraus der Arbeitsspeicher zum Spitzenwert der Sitzung bestand. Trat
dieser Spitzenwert auf, als der Arbeitsspeicher bereits zu knapp war, um den C-Heap sicher zu lesen, was
kurz vor einem Out-of-Memory-Absturz meist der Fall ist, zeigt er zusätzlich den jüngsten
früheren Spitzenwert, bei dem das Lesen gelang, mit dessen eigener Größe und Zeit. Außerdem sagt er,
was jeder Thread gerade tat (sein Name, der App-Code, den er ausführte, und die CPU-Zeit,
die er nutzte), und zwar zu zwei Arten von Zeitpunkten: wenn der verfügbare Arbeitsspeicher unter 15 % des RAM fiel
(höchstens 1 GB), zuerst beim Unterschreiten und erneut bei jedem neuen Tiefstwert, und wenn die
App innerhalb von fünf Sekunden eine Million oder mehr Python-Objekte erzeugte, höchstens einmal
alle fünf Minuten. Die jüngsten acht Schnappschüsse werden in
`session_pressure.json` im Datenordner aufbewahrt, und sie bleiben wie
die übrige Diagnose auf diesem Computer.

## 5.6 Bekannte Grenzen & offene Hinweise

Ehrlichkeit als Bauprinzip heißt: zu sagen, was das Werkzeug Ihnen *nicht* sagen kann, und nicht nur,
was es kann. Dies sind die dauerhaften Grenzen der Methoden (audit-07, „Offenlegungs-Durchgang“
(disclosure sweep)). Keine davon ist ein Fehler; jede bestimmt, wie Sie ein Ergebnis lesen sollten.

- **Schlagwort- und Trendzählungen sind lexikalisch, nicht semantisch.** Sie messen, wie oft
  Wörter vorkommen, nicht, was gemeint war. Verneinung („keine Krise“), Zitate,
  Sarkasmus und Ironie werden wörtlich gezählt. Volumen ist Berichterstattung, niemals
  Bedeutung oder Wahrheit.
- **Stimmung/Tonalität beruht auf VADER, einer Methode mit englischem Lexikon.** Werte für nicht englische
  Artikel sind unzuverlässig; die Ansichten **Stimmung** und **Rahmung** legen dies offen und
  zeigen den Anteil, der auf Englisch bewertet wurde. Tonalität ist ein messbares Signal, niemals ein Urteil
  darüber, dass ein Medium voreingenommen ist.
- **LLM-Zusammenfassungen und -Übersetzungen sind Modellerzeugnisse.** Ein lokales Modell kann
  flüssig formulieren und trotzdem falsch liegen. Jedes erzeugte Feld ist mit „mit dem gespeicherten
  Artikel abgleichen“ beschriftet; behandeln Sie seine Ausgabe als Hinweis und prüfen Sie sie anhand des Originaltexts,
  den Sie gesammelt haben.
- **Ein langer Artikel wird aufgeteilt, nicht abgeschnitten.** Das Kontextfenster eines Modells ist begrenzt. Wenn
  Sie eine Zusammenfassung oder Übersetzung eines Artikels anfordern, der nicht hineinpasst, teilt die
  App ihn an Absatzgrenzen auf und verarbeitet jeden Teil — eine Übersetzung besteht aus
  den zusammengefügten Teilen, und eine Zusammenfassung fasst die Teile einzeln und dann
  gemeinsam zusammen. In beiden Fällen sagt das Ergebnis dies („in N Teilen übersetzt“, „hierarchische
  Zusammenfassung über N Teile“), denn eine zweistufige Zusammenfassung ist ein anderes Erzeugnis als
  eine in einem Durchgang, und Sie sollten wissen, welche Sie lesen. Sie bricht niemals stillschweigend
  mittendrin ab: Eine abgeschnittene Übersetzung sieht genau wie eine vollständige aus.
  Hintergrund-Durchläufe (die Wer/Wo/Wann-Extraktion) schneiden lange Artikel SEHR WOHL ab und
  vermerken das — „die ersten N von M Zeichen analysiert“ —, damit eine dünne
  Extraktion nie mit einem dünnen Artikel verwechselt wird.
- **Hintergrund-KI läuft auf einer einzigen Spur, und Ihre Arbeit hat Vorrang.** Die Durchläufe, die Sie aktivieren,
  laufen nacheinander auf dem einen lokalen Backend, statt um es zu konkurrieren.
  Alles, was Sie selbst anfordern — eine Massenübersetzung, ein manuell gestarteter Durchlauf —, pausiert
  diese Spur für seine Dauer, und sie setzt danach von selbst fort; nichts verliert
  seinen Platz. Auf einem Rechner, auf dem lokale Inferenz unpraktikabel ist, ist die Spur standardmäßig
  aus, mit Angabe des Grundes, und Sie können sie trotzdem einschalten.
- **Die App verarbeitet nur Text.** Sie analysiert Artikeltext. Bei Bildern gibt es nur ehrliche Angaben zu EXIF/Metadaten
  (keine forensischen oder Deepfake-Aussagen); es gibt keine Audio- oder Video-
  Analyse. Eine Behauptung, die nur in einem Video oder Bild steckt, liegt außerhalb dessen, was das Werkzeug
  sehen kann.
- **Japanisch und Thai benötigen das optionale Extra `[segmentation]`.** Die Schlagwortextraktion
  beruht auf Tokenisierung an Leerzeichen, sofern kein Wortsegmentierer installiert ist. Chinesisch wird
  bei jeder Installation segmentiert (jieba, seit 0.4 eine Kernabhängigkeit); die Schlagwortanalyse für Japanisch und Thai
  funktioniert ohne das Extra (janome, pythainlp) praktisch nicht, obwohl
  die Oberfläche in diesen Sprachen ausgeliefert wird, und die japanische Suche wird nur
  mit sudachipy aus dem Extra in Wörter zerlegt. Der **verwaltete** Satz
  (durch Leerzeichen segmentiert, mit Stoppwortliste) ist in
  [`src/analytics/managed.py`](../src/analytics/managed.py) festgelegt; die *Analysetiefe* je
  Sprache variiert, und nicht segmentierte Schriften sind derzeit die größte Lücke.
- **Überlebensverzerrung zugunsten freizügiger Hosts.** Weil robots.txt im Zweifel sperrt (fail-closed), sind im
  Korpus Websites, die das Crawlen *erlauben*, überrepräsentiert, und Journalismus hinter Bezahlschranken oder mit
  Crawl-Beschränkungen ist strukturell unterrepräsentiert. Das lässt sich nicht auf ethische Weise
  „beheben“ — es wird abgemildert, indem offizielle APIs/Archive bevorzugt werden, und wird
  hier offengelegt, damit Sie die Abdeckung entsprechend lesen.
- **Ihre Aufzeichnung beginnt, als Sie mit dem Sammeln begonnen haben.** Trends und „steigende“ Signale
  sind durch Ihr Sammelzeitfenster begrenzt; das Werkzeug hat keine Historie aus der Zeit, bevor Sie
  angefangen haben. Wikipedia-Dumps und (künftige) Archive reichen weiter in die Vergangenheit; ansonsten lesen Sie
  Ergebnisse aus einem jungen Korpus mit den Vorbehalten zum angezeigten n.
- **Wikipedia bringt ihre eigenen systemischen Verzerrungen mit.** Beobachtete/aufgenommene Wikipedia-Inhalte
  übernehmen die gut dokumentierten redaktionellen und inhaltlichen Schieflagen jeder Ausgabe.
  Quellen je Ausgabe (`xx.wikipedia.org`) halten sie filterbar, und sie lässt sich
  wie jede andere Quelle gegenprüfen — sie ist niemals ein Orakel.
- **Auswahlverzerrung des Katalogs wird gemessen, nicht verborgen.** Der Quellenkatalog ist ein
  von Menschen kuratierter Bestand, dessen Ausrichtung weg von den USA noch im Gange ist; die Ansicht **Weltweite Abdeckung**
  zeigt, welche Länder vertreten sind und welche nicht, damit Sie die Form dessen sehen,
  was Sie sammeln (und was nicht).

---

## 6. Fehlerbehebung

- **Die Seite lädt nicht.** Prüfen Sie, ob der Prozess läuft und an
  `127.0.0.1:8000` (oder Ihren `OO_HOST`/`OO_PORT`) gebunden ist. Die Statusanzeige in der Kopfzeile wechselt auf
  `offline`, wenn die API nicht erreichbar ist.
- **Die Suche ist leer.** Sie haben noch nichts gesammelt — **gehen Sie online** über die Flugzeug-
  Schaltfläche (ein Einwilligungsdialog), und die Erfassung startet automatisch; der manuelle Weg ist
  **Einstellungen → Erweitert → Erfassung → Feed abrufen**.
- **Eine Aufnahme hat nichts gespeichert.** Das ist oft korrekt und ethisch: Die Seite kann
  durch `robots.txt` gesperrt sein (fail-closed), einer Ratenbegrenzung unterliegen, ein Duplikat sein oder keinen
  extrahierbaren Haupttext haben. Die Ergebnisübersicht sagt Ihnen, was zutrifft.
- **Bedienelemente von Einblicke/Märkte fehlen oder melden Fehler.** Das Extra `[analysis]`
  ist nicht installiert — führen Sie `install.sh` erneut aus (das Analyse-Extra wird standardmäßig installiert).
- **Die LLM-Anzeige meldet offline.** Ollama läuft nicht oder ist nicht erreichbar; starten Sie es oder setzen Sie
  `OLLAMA_BASE_URL`. Zusammenfassen/Übersetzen liefern ein klares `503`, wenn es nicht verfügbar ist.
- **Die Verwahrung zeigt „angefordert, Bibliothek nicht installiert“.** Installieren Sie das Extra `pqc` und/oder
  `timestamping`; der tatsächliche Zustand wechselt, sobald die Bibliothek vorhanden ist.
- **Die Wiederherstellung hat meine Datei abgelehnt / die Vorschau lässt sich nicht anwenden.** Das ist so gewollt — es muss eine
  echte Open-Omniscience-Sicherung sein, und **Anwenden (Apply)** bleibt deaktiviert, wenn die vorbereitete
  Prüfung fehlschlägt. Ihr aktueller Korpus bleibt in jedem Fall unberührt; die Wiederherstellung
  *ergänzt* immer nur, sie ersetzt nie.
- **Der Wikipedia-Dump ist riesig.** `enwiki` umfasst zig GB. Nutzen Sie zuerst **Größe schätzen (Estimate size)**;
  die meisten Ausgaben sind weit kleiner, und für die Änderungsverfolgung brauchen Sie keinen Dump.

---

## 7. Glossar

- **Korpus** — Ihre lokale SQLite-Datenbank mit den gesammelten Artikeln.
- **Provenienz** — die gespeicherte Herkunft jedes Elements (Quelle, URL, kanonische URL,
  Inhalts-Hash, Abrufzeit), die für Deduplizierung und Vertrauen genutzt wird.
- **FTS5** — die Volltextsuche von SQLite, die boolesche Abfragen ermöglicht.
- **Ethischer Abruf** — der eine, robots.txt respektierende, ratenbegrenzte Abrufweg.
- **Beweiskette (Chain of custody)** — ein nur erweiterbares, per Hash verkettetes, signiertes Protokoll, das die
  Integrität, Herkunft und den Zeitpunkt eines Elements belegt.
- **Beweispaket** — ein signierter, auf einer Merkle-Wurzel beruhender, offline prüfbarer Export
  ausgewählter Artikel.
- **OpenTimestamps** — ein Verfahren, einen Hash in Bitcoin zu verankern, als unabhängiger Nachweis, dass etwas
  „spätestens zum Zeitpunkt“ eines Blocks existierte.
- **ML-DSA** — Post-Quanten-Signaturverfahren nach FIPS-204 (im *hybriden* Modus
  zusammen mit Ed25519 verwendet).
- **ORES** — ML-Dienst von Wikimedia, der Bearbeitungen auf Schaden / guten Glauben bewertet.
- **PMI** — punktweise Transinformation (pointwise mutual information); ordnet ein, wie stark zwei Begriffe
  über den Zufall hinaus gemeinsam auftreten (die „Mindmap“ in Einblicke).
- **VADER** — ein lexikonbasiertes Bewertungsverfahren für Tonalität/Stimmung (die Ansicht „Rahmung“ in Einblicke).

---

*Siehe auch:* [QUICKSTART](QUICKSTART.md) · [CHAIN_OF_CUSTODY](USER_MANUAL.md) ·
[INSIGHTS](USER_MANUAL.md) · [MARKETS](USER_MANUAL.md) · [WIKIPEDIA](USER_MANUAL.md) ·
[DATABASE](ARCHITECTURE.md) · [API_DOCUMENTATION](ARCHITECTURE.md) ·
[SECURITY](SECURITY.md) · [PRODUCT_SYNTHESIS](DESIGN.md) ·
[OPEN_QUESTIONS](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).

*© 2026 Ideotion — gebaut für investigativen Journalismus, ehrlich. GPLv3.*

---

# Funktionen im Detail

Vertiefende Referenz zu jedem Werkzeug, zusammengeführt aus den früheren Anleitungen zu einzelnen Funktionen. Der Rundgang in den Teilen 1–6 oben bleibt die schnellste Orientierung; dieser Teil liefert die Details.

**In diesem Teil:**
- [Das Briefing auf der Startseite — Erkenntnisse als ehrliche „Karten“](#das-briefing-auf-der-startseite--erkenntnisse-als-ehrliche-karten)
- [Quellenintegrität & Anti-Verstärkung](#quellenintegrität--anti-verstärkung)
- [Geteilte Quellenanmerkungen — signiert, portabel, über Vertrauen föderiert](#geteilte-quellenanmerkungen--signiert-portabel-über-vertrauen-föderiert)
- [Einblicke — Analysen von Schlagwörtern & Entitäten](#einblicke--analysen-von-schlagwörtern--entitäten)
- [Änderungsverfolgung für Wikipedia](#änderungsverfolgung-für-wikipedia)
- [Weltrecht — Änderungsverfolgung für Gesetze, Amtsblätter & geistiges Eigentum](#weltrecht--änderungsverfolgung-für-gesetze-amtsblätter--geistiges-eigentum)
- [Märkte: Finanz-, Börsen- und Rohstoff-/Seltene-Erden-Informationen](#märkte-finanz--börsen--und-rohstoff-seltenerd-informationen)
- [Beweiskette (Chain of Custody)](#verwahrungskette)


---

## Das Briefing auf der Startseite — Erkenntnisse als ehrliche „Karten“

> **Stand:** `0.06` Phase A (das GUI-Grundgerüst) — ausgeliefert und getestet. Der Phasenplan
> steht in [`ROADMAP.md` → „0.06 — The Intelligence Layer“](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md); das
> *Was & Warum* in [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).

Der Tab **Start** zeigt nicht mehr nur Kennzahlen auf einen Blick. Er ist ein **Sichtungs-Feed**: Die
App sammelt und misst im Hintergrund und stellt dann *mögliche Geschichten* als
**Karten — auf dem Bildschirm als „Spuren“ angezeigt** — bereit (dieses Kapitel sagt „Karte“ für den internen
Mechanismus; die Beschriftung in der Oberfläche lautet „Spur“). Die App übernimmt das Sammeln; **Sie urteilen**. Jede Karte
ist **ein messbares Signal + die Belegverweise + ein Vorbehalt**, einsortiert in eine redaktionelle
Rubrik, und wird als **zweiseitige Wendekarte** dargestellt (Vorderseite = die Spur; Rückseite = Vorbehalt +
Methode + Belege + „Korpus öffnen“).

Eine Karte **zeigt ein Signal auf; sie fällt niemals ein Urteil.** Es gibt kein „voreingenommen“, keine
„Propaganda“, kein „wahr/falsch“ und — bewusst so gestaltet und *im Code erzwungen* — **keinen zusammengesetzten
Vertrauenswert** (siehe „Ehrlichkeitssicherungen“ unten).

---

### Was Sie sehen

Das Briefing gruppiert Karten in **Rubriken** (in Anzeigereihenfolge):

| Rubrik | Bedeutung | Redaktionelle Verwendung |
|---|---|---|
| **Im Aufwind** | etwas bewegt sich / ist neu | Kandidaten für Aufmacher |
| **Überdeckt erzählt** | Quellen stimmen zu schnell / zu einheitlich überein | den Chor entlarven |
| **Unterbelichtet** | etwas hat sich bewegt, aber kaum jemand / niemand hat darüber berichtet | die Lücke sichtbar machen |
| **Untersuchenswert** | Quellen oder Daten widersprechen sich | nachbohren |
| **Rahmung prüfen** | dasselbe Ereignis wird gegensätzlich gerahmt | die Behauptung prüfen |
| **Weiter beobachten** | eine Änderung, die Aufmerksamkeit verdient (z. B. ein umgestalteter Eintrag) | beobachten |
| **Kontext** | Hintergrund / Selbstprüfung / feststehende Fakten | einordnen |
| **Datenintegrität** | Hygienesignale über den Korpus selbst | die Verarbeitungskette reparieren |

Der Dreiklang dahinter ist der Motor: **Übereinstimmung → überdeckt erzählt**, **Abweichung →
untersuchen/entlarven**, **Abwesenheit → unterbelichtet**.

Jede Spur (der Name einer Briefing-Karte auf dem Bildschirm) zeigt auf ihrer **Vorderseite** ihren **Titel**, eine einzeilige
**Zusammenfassung** und das **gemessene Signal** (z. B. `growth_ratio = 4.2`, `n=6`).
**Klicken Sie darauf (oder drücken Sie Enter), um sie umzudrehen:** Die **Rückseite** enthält den
**Vorbehalt**, die **Methode** (genau wie die Zahl berechnet wurde und was sie *nicht*
bedeutet), warum sie ausgelöst wurde, die **Belegverweise** zurück in Ihren Korpus und eine Schaltfläche **„Korpus öffnen
↗“**. Der Vorbehalt steht standardmäßig im DOM, auf der gleichwertigen Rückseite direkt neben der
Aktion — niemals hinter einem Schalter für eine „ruhige“ Ansicht. Genau darum geht es: **Transparenz ist die
Oberfläche.**

> **Gleichwertige Ansicht.** In dieser Version wird jede Quelle einmal gezählt und **keine Quelle wird
> abgeschwächt**. Die Schicht für Quellenintegrität / Anti-Verstärkung (koordinierte Fluten zu
> einzelnen Akteuren zusammenfassen, Gewichtung nach Neuheit) ist die nächste Phase und ist
> **nutzergesteuert** — die App wird *vorschlagen*, Sie werden *entscheiden*. Bis dahin ist das
> Briefing, ehrlich gesagt, die ungefilterte Ansicht mit Gleichbehandlung.

---

### Der Kreislauf Karte → Entwurf → Newsletter

Der Nutzen-Kreislauf ist vom ersten Tag an sichtbar:

1. Klicken Sie auf einer beliebigen Karte auf **+ Zum Entwurf**.
2. Öffnen Sie das Feld **Newsletter-Entwurf**; fügen Sie jeder angehefteten Karte Ihre eigene Notiz hinzu.
3. **Als Markdown exportieren** (oder **Kopieren**). Jede Aussage wird **mit ihren Quellverweisen,
   ihrer Methode und ihrem Vorbehalt** ausgegeben — nachvollziehbarer Journalismus durch die Gestaltung.

Für eine *signierte, manipulationssichtbare* Kopie der zugrunde liegenden Artikel exportieren Sie ein **Beweis-
paket** aus **Beweise & Verwahrung** — die Belege können mit Ihrer Ausgabe mitgeliefert werden.

---

### Wie die Karten entstehen (Briefing v0)

Jede Karte wird von einem **Erzeuger** (producer) erstellt: einer Funktion `corpus → [Card]`. Erzeuger kombinieren
Analysen, die *bereits echte Zahlen liefern* — nichts wird erfunden. Ein Erzeuger, dem
seine Eingaben oder eine optionale Abhängigkeit `[analysis]` fehlen, **liefert nichts und protokolliert,
warum** (lautes Herabstufen); er erfindet niemals eine Karte.

| Karte | Rubrik | Grundlage | Stand |
|---|---|---|---|
| **„X“ ist im Aufwind** | Im Aufwind | `insights.trending` (Verhältnis aktueller zu vorheriger Zeitraum) | jetzt |
| **Unterschiedliche Rahmung** | Rahmung prüfen | VADER-Tonalität je Quelle für einen Trendbegriff | jetzt¹ |
| **Eintrag umgestaltet** | Weiter beobachten | Wikipedia-Erkennung großer/markierter Bearbeitungen | jetzt |
| **Preis ↔ Narrativ (Price ↔ narrative)** | Kontext | ehrliche scipy-Korrelation (Koeffizient + p + n) | jetzt¹ |
| **Veraltete Daten** | Datenintegrität | `last_run_at` / `last_status` der Marktextraktionsregeln | jetzt |
| **Selbstprüfung der Lesediät (Diet self-audit)** | Kontext | `signals.concentration` (Gini + Top-3-Anteil über Ihre Quellen) | jetzt |
| **Echokammer** | Überdeckt erzählt | Akteursgraph aus `signals.coordination` (Beinahe-Duplikate + Zeitpunkte + Host) | neu |
| **Einsames Signal** | Unterbelichtet | Beinahe-Duplikat-Cluster aus einer einzigen Quelle, das kein Echo fand | neu |
| **Unplausible Kapazität (Capacity implausible)** | Untersuchenswert | Artikel/Tag im Vergleich zum Median des Korpus | neu |
| **Emotionsprofil** | Kontext | Emotionslexikon über die Kontextfenster eines Schlagworts | neu² |
| **IP-/Rechtspuls (IP / legal pulse)** | Kontext | steigende IP-/Rechtsbegriffe im Nachrichtenkorpus | dünn |
| **Eigentümerwechsel** | Untersuchenswert | Sprache von Übernahmen (übernommen/Fusion/veräußert) in aktuellen Nachrichten | dünn |
| **Herkunft einer Meldung** | Kontext | `signals.lineage` — ein Beinahe-Duplikat-Cluster, nach Veröffentlichungszeit geordnet + Agenturzuschreibung | neu |
| **Abdeckungsberater** | Kontext | `signals.concentration` über Land/Sprache Ihrer Quellen (Schieflage, keine Obergrenze) | neu |
| **Wetterprüfung verfügbar (Weather check available)** | Untersuchenswert | `analytics.corroboration` — Begriffe für Klimaereignisse × erschlossene Orte × Artikeldaten | neu |

¹ Benötigt das Extra `[analysis]` (VADER / scipy). Ohne es erscheinen diese Karten einfach nicht
— der Rest des Briefings funktioniert weiterhin.
² Verwendet ein Emotionslexikon; mitgeliefert wird nur eine minimale englische **Stichprobe** — für ernsthaften Einsatz
richten Sie `OO_EMOTION_LEXICON` auf ein vollständigeres JSON-Lexikon (nur Englisch).

Die Karten **Echokammer**, **Einsames Signal** und **Unplausible Kapazität** stammen aus der
Schicht für Quellenintegrität — siehe [`USER_MANUAL.md`](USER_MANUAL.md). Echokammer-Karten tragen
die Aktion *Auf einen Akteur zusammenfassen* (nutzergesteuerte Anti-Verstärkung — Vorschlag → Sie entscheiden).

Die **Selbstprüfung der Lesediät** nutzt das erste reine Grundelement der gemeinsamen
Basis [`src/signals/`](../src/signals/): **Konzentration** (Gini-Koeffizient +
Top-N-Anteil). Es ist *dieselbe Mathematik*, die für die Konzentration von Medieneigentum
(FUTURE_DEVELOPMENTS §1) und die Prominenz von Personen (§4) vorgesehen ist — ein Motor, viele Bereiche.

Die **Herkunft einer Meldung** verfolgt eine vielfach wiederholte Geschichte zurück zu ihrer **Urquelle**: Für ein Beinahe-Duplikat-
Cluster über viele Medien hinweg ordnet sie die Beiträge nach Veröffentlichungszeit und erkennt ausdrückliche
**Agenturzuschreibungen** („laut Reuters“, „(AFP)“), sodass Originalberichterstattung gegenüber abgeleiteten Echos
in den Vordergrund rückt. Die klare Grenze ist ehrlich: *„das Früheste, was wir gesehen haben“ ≠ „die Wahrheit“* — sie
zeigt Struktur auf; der Mensch urteilt. Der **Abdeckungsberater** macht geografische/sprachliche
**Schieflagen in Ihrer eigenen Sammlung** sichtbar (z. B. „~80 % dessen, was Sie gesammelt haben, stammt aus einem Land“) als
behutsamen Vorschlag zur Verbreiterung — er filtert oder begrenzt niemals etwas; ein schiefer Korpus verzerrt jedes
nachgelagerte Signal, also ist es genau der Zweck, die Schieflage zu sehen.

**Wetterprüfung verfügbar** ist die erste *Wenn-dies-dann-Vorschlag*-Karte: Wenn mehrere Ihrer
Artikel dasselbe Wort für ein Klimaereignis erwähnen (Dürre, Überschwemmung, Hitzewelle … — eine kuratierte
Ausgangsliste in 12 Sprachen, `configs/corroboration_rules.yml`) zusammen mit demselben erschlossenen
Ort innerhalb eines Zeitfensters, **bietet** die Karte an, unabhängige Wetterdaten für
genau diesen Ort und dieses Zeitfenster abzurufen. Die Karte selbst wird lokal berechnet — das sagt sie auch — und
nichts wird abgerufen, bis Sie auf **Wetterkontext abrufen** klicken, was über denselben
Einwilligungsdialog für das Netzwerk läuft wie jede andere Online-Aktion. Zurück kommt ein einziger begrenzter
Ausschnitt einer Open-Meteo-**Reanalyse** (CC BY 4.0, Quellenangabe wird angezeigt): eine *Modellschätzung*, keine
Stationsmessung — sie kann das, was die Artikel sagen, **stützen oder infrage stellen**, aber niemals beweisen.
Der Ausschnitt wird auf der Festplatte zwischengespeichert, sodass ein späteres erneutes Lesen offline erfolgt; der Cache-Zustand und
die Abrufzeit werden immer angezeigt.

---

### Leistung — vorberechnen, zwischenspeichern, aus dem Cache ausliefern

Das Briefing **berechnet niemals pro Anfrage**. Der Hintergrund-Planer aktualisiert es
nach jedem Sammeldurchlauf und schreibt einen Cache (`briefing_cache.json` in Ihrem Datenverzeichnis);
die Startseite liest den Cache und lädt sofort. Es **aktualisiert sich selbst** — es wird nach jedem Durchlauf
im Hintergrund neu berechnet, und die Startseite fragt von selbst erneut ab (ein Fortschrittsbanner wird angezeigt,
während eine Aktualisierung läuft); es gibt keine manuelle Schaltfläche zum Aktualisieren. Ausgeblendete Karten
(`briefing_dismissed.json`) und der Entwurf (`briefing_draft.json`) sind kleine lokale JSON-
Dateien — für einen einzelnen Nutzer, lokal zuerst, niemals übertragen.

---

### Ehrlichkeitssicherungen (im Code, nicht nur in der Dokumentation)

FUTURE_DEVELOPMENTS §6 verbietet einen einzelnen automatisierten Vertrauens-/Qualitätswert (er schreibt das
Weltbild des Bewertenden in eine scheinbar objektive Zahl fest und *wird* kleine, ausländische,
neue oder dissidente Quellen falsch einstufen). Dieses Verbot wird **mechanisch** durchgesetzt:

- `src/briefing/card.py:assert_no_score_fields()` weist jedes `Card`-Feld zurück, dessen Name
  einen zusammengesetzten Wert nahelegt (`score`, `trust_score`, `credibility`, `rating`,
  `verdict`, …). Es läuft beim Import, und ein Test stellt sicher, dass dies gilt.
- Der Zahlenwert, den eine Karte trägt, steht in `signal` als **eine gemessene Größe mit einer
  angegebenen Methode** — ein Wachstumsverhältnis, ein Gini-Wert, ein Korrelationskoeffizient —, niemals ein
  gemischter Wert über nicht vergleichbare Dimensionen.
- **Sichtbar machen, nicht unterdrücken.** Das Ausblenden lässt sich rückgängig machen; jede künftige Abwertung wird
  transparent, einstellbar, standardmäßig aus und umkehrbar sein.

---

### API

Alles unter `/api/briefing` (nur Loopback, wie der Rest der App):

| Methode & Pfad | Zweck |
|---|---|
| `GET /api/briefing` | der zwischengespeicherte Feed, nach Rubrik gruppiert (`?force=true` zum Neuberechnen) |
| `POST /api/briefing/refresh` | jetzt neu berechnen |
| `POST /api/briefing/dismiss` · `/restore` · `/dismissed/clear` | ausgeblendete Karten verwalten |
| `GET /api/briefing/draft` | der aktuelle Entwurf (angeheftete Karten + Notizen + Titel) |
| `POST /api/briefing/draft/add` · `DELETE /api/briefing/draft/{id}` | eine Karte anheften / lösen |
| `PUT /api/briefing/draft/note` · `/title` · `POST /draft/clear` | den Entwurf bearbeiten |
| `GET /api/briefing/draft/export.md` | das Markdown mit den Belegen |

---

### Fahrplan (Stand)

Die Phasen A–D sind ausgeliefert: das Grundgerüst aus Karten und Briefing (A), die vollständige Basis `src/signals/`
— Konzentration, Beinahe-Duplikate/Koordination, Neuheit (B), das Quellenintegritätsprofil +
nutzergesteuerte Anti-Verstärkung (C, siehe [`USER_MANUAL.md`](USER_MANUAL.md)) und gemeinschaftlich erstellte,
signierte Anmerkungspakete (D, siehe [`USER_MANUAL.md`](USER_MANUAL.md)). Phase E liefert die
kombinierbaren Fachbereiche als Karten aus (Emotion, IP-/Rechtsnachrichten); die **Fachbereiche zur Änderungsverfolgung von
Rechts-/IP-Primärquellen** (Aufnahme von `legislation.gov.uk`, EUR-Lex, Patenten/Verfahrensakten)
bleiben der dokumentierte nächste Schritt — sie nutzen die vorhandenen Motoren für Änderungsverfolgung und
Beinahe-Duplikate/Korrelation, benötigen aber externe Live-Quellen. Siehe
[`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md), Phasen B–E.


---

## Quellenintegrität & Anti-Verstärkung

> **Stand:** `0.06` Phase C — ausgeliefert und getestet. Der Schlussstein der Erkenntnis-
> schicht (FUTURE_DEVELOPMENTS §6). Gehört zusammen mit [`USER_MANUAL.md`](USER_MANUAL.md) und
> [`USER_MANUAL.md`](USER_MANUAL.md).

Die anderen Werkzeuge zeigen Signale auf; **dieses entscheidet, wessen Signal zählt** — *ohne
zum Schiedsrichter über die Wahrheit zu werden*. Es ist die Antwort auf das Problem „Müll rein“.

### Die Überraschung: Jede Quelle gleich zu behandeln ist **nicht** neutral

Trends, Prominenz, Gleichzeitigkeit und „was wird abgedeckt“ **zählen alle Medien und Volumen**.
Gleichbehandlung von Medien, angewandt auf eine Volumenkennzahl, hat also eine eingebaute Verzerrung:
*Wer am meisten produziert, gewinnt.* Ein gut ausgestatteter Akteur, der 40 Medien aufzieht (oder
Trollfabriken oder Content-Farmen), verwandelt Kapital direkt in scheinbaren Konsens und
**verwässert** ehrliche Geschichten aus einer einzelnen Quelle bis zur Bedeutungslosigkeit. Nichts zu tun ist nicht neutral —
es subventioniert den, der flutet.

Die Lösung besteht nicht darin, Quellen zu *bewerten*. Sie besteht darin, Neutralität über die richtige
**Einheit** zu definieren: Gleichbehandlung *unabhängiger Akteure, gewichtet nach den neuen Informationen, die sie
beitragen*, nicht von *Medien*. **Strohpuppen als Stimmen zu zählen ist ein Messfehler,
keine Neutralität.**

### Was gemessen wird (und was verboten ist)

Wir bewegen uns strikt in der **erlaubten** Hälfte der Unterscheidung aus §6:

- **(A) Bewertung von Wahrhaftigkeit / Qualität** — „ist diese Quelle wahrhaftig / gut?“ — darf
  **nicht automatisiert werden.** Sie schreibt das Weltbild des Bewertenden in eine scheinbar objektive
  Zahl fest und *wird* früher oder später auch eine gute, aber ungewöhnliche Quelle herabstufen.
- **(B) Signale zu Echtheit / Struktur** — „ist diese Quelle, was sie zu sein vorgibt? ein
  Knoten eines koordinierten Netzwerks? *bringt* sie Neues *hervor* oder gibt sie nur *Echos* wieder? liegt ihr Ausstoß
  im Rahmen menschlicher Kapazität? legt sie offen, wer sie betreibt?“ — das sind in erheblichem
  Maße **messbare strukturelle Tatsachen.** Die gesamte Gestaltung liegt hier.

#### Der gemeinsame Motor (`src/signals/`)

| Grundelement | Misst | Speist |
|---|---|---|
| `concentration` | Gini + Top-N-Anteil | Konzentration von Eigentum/Lesediät, Prominenz |
| `near_dup` | Beinahe-Duplikat-Cluster per MinHash + LSH | Erkennung von Echos / Syndizierung |
| `coordination` | Akteursgraph aus Beinahe-Duplikaten + Gleichschritt-Zeitpunkten + gemeinsamem Host | Zusammenfassen von Akteuren |
| `novelty` | Anteil der Wort-Schindeln, die für den Korpus neu sind | Gewichtung Hervorbringen-oder-Echo |

Alle vier sind **rein** (keine Datenbank, kein Netzwerk), eigenschaftsbasiert getestet und tragen Methode + Vorbehalt.

### Anti-Verstärkung ist **nutzergesteuert** (Vorschlag → Sie entscheiden)

Anti-Verstärkung ist **niemals** eine stille Umwandlung, die die App vornimmt und die Sie lediglich
*rückgängig machen* — das würde die App zu dem Schiedsrichter machen, den §6 verbietet.

- **Standard = „gleich, aber bewusst“.** Die ungefilterte Ansicht mit Gleichbehandlung ist die Ausgangsbasis; eine
  koordinierte Flut wird **darauf vermerkt** (die *Echokammer*-Karte), nicht zusammengefasst.
- **Sie wenden eine Zusammenfassung an**, pro Cluster oder global. Erst dann wird ein koordiniertes
  Netzwerk in jeder Zählung, die Konsens misst (wie viele
  unabhängige Stimmen eine Geschichte tragen), zu **einer Stimme** zusammengefasst.
- **Jede angewandte Zusammenfassung bleibt markiert und umkehrbar.** Ein Klick klappt sie in ihre
  Mitglieder auf; das Zurücksetzen stellt die ungefilterten gleichen Zählungen **exakt** wieder her. *Keine Zusammenfassung wird je
  ohne Ihr ausdrückliches Handeln angewandt* — durch einen Test erzwungen.

Das ist der **Quellenintegritäts-Desk** (Einstellungen → Erweitert → Sicherheit → „Quellenintegritäts-Desk
öffnen“): *Nach Koordination suchen* listet vorgeschlagene Akteure mit ihren Belegen auf (gemeinsamer Text,
Gleichschritt-Zeitpunkte, gemeinsamer Host); *Zusammenfassung anwenden* / *Aufklappen (rückgängig)* liegen in Ihrer Wahl.
Die Echokammer-Spuren auf der Startseite tragen dieselbe Aktion *Auf einen Akteur zusammenfassen*.

### Das Quellenprofil — gemessene Dimensionen, **kein zusammengesetzter Wert**

Pro Quelle ein Feld *gemessener* Signale — und **bewusst keine einzelne Vertrauens-
zahl** (das verbotene „B“). Ein Wert von 0–100 ist Scheingenauigkeit über nicht vergleichbare
Dimensionen, nach Goodhart manipulierbar, ein einzelner Angriffspunkt für Vereinnahmung und *wird* kleine /
ausländische / neue / dissidente Quellen falsch einstufen. Das Verbot ist im Code durchgesetzt (das Profil
liefert `no_composite_score: true`, und ein Test stellt sicher, dass es keinen aggregierten `*score*`-Schlüssel gibt).

Dimensionen (jede mit eigener Methode + Vorbehalt):

- **Koordination** — Zugehörigkeit zu einem Akteur, mit wem, wie viele gemeinsame Geschichten.
- **Neuheit** — bringt diese Quelle Neues hervor oder gibt sie überwiegend Echos wieder? (bezogen auf *Ihren* Korpus).
- **Ausstoßkapazität** — Artikel/Tag im Vergleich zum Median des Korpus (eine *Frage*, kein Urteil;
  Nachrichtenagenturen und große Redaktionen sind berechtigterweise produktiv).
- **Transparenz** — Land, Sprache, Tags zu Eigentum/Ausrichtung (rufbezogen,
  anfechtbar, bearbeitbar) und der vom Betreiber gesetzte `reliability_score` (hier nicht berechnet).
- **Bilanz** — was diese Quelle zu Ihrem Korpus beigetragen hat.

Sie gewichten selbst, welche Dimensionen in *Ihre* Ansicht einfließen — standardmäßig aus, umkehrbar, die
ungefilterte gleiche Ansicht immer nur einen Klick entfernt.

### Neue Briefing-Karten aus dieser Schicht

- **Echokammer** (überdeckt erzählt) — eine Geschichte, getragen von N koordinierten Quellen.
- **Einsames Signal** (unterbelichtet) — eine gehaltvolle Geschichte aus einer einzigen Quelle, die kein Echo fand.
- **Unplausible Kapazität** (untersuchenswert) — eine Quelle, die weit über der Norm des Korpus veröffentlicht.

### API

| Methode & Pfad | Zweck |
|---|---|
| `GET /api/integrity/profile?source=` | das Feld gemessener Signale ohne zusammengesetzten Wert |
| `GET /api/integrity/actors` | vorgeschlagene koordinierte Akteure, jeweils als angewandt/nicht angewandt markiert |
| `GET /api/integrity/prominence` | Prominenz einer Geschichte in unabhängigen Stimmen, ungefiltert vs. zusammengefasst |
| `POST /api/integrity/collapse/apply` · `/revert` | eine Zusammenfassung anwenden / rückgängig machen (pro Akteur) |
| `POST /api/integrity/collapse/apply_all` · `/revert_all` | global zusammenfassen / zurücksetzen |

### Ehrliche Grenzen (benannt)

- **Wettrüsten / Goodhart** — jedes veröffentlichte Signal ist ein Optimierungsziel; dies ist
  gestaffelte Verteidigung, niemals ein Anspruch auf Vollständigkeit.
- **Falsche Zusammenführungen schaden Unschuldigen** — die Erkennung ist auf hohe Präzision ausgelegt, neigt dazu,
  *zu wenig* zusammenzuführen, zeigt immer die Belege und ist immer umkehrbar.
- **Vereinnahmung** — wir liefern *Mechanismen, keine Urteile*; der Standard ist die transparente
  gleiche Ansicht; Sie können alles übersteuern.
- **Das Ziel** ist nicht, „allen Müll zu erkennen“ (unmöglich, und es zu behaupten wäre der
  unehrliche Schritt), sondern **dem Müll seinen mechanischen Vorteil zu nehmen**, damit sich das Spiel mit den
  40 Agenturen *nicht mehr auszahlt*.


---

## Geteilte Quellenanmerkungen — signiert, portabel, über Vertrauen föderiert

> **Stand:** `0.06` Phase D — ausgeliefert und getestet. Die skalierende Antwort auf das Quellen-
> profil (FUTURE_DEVELOPMENTS §6). Gehört zusammen mit [`USER_MANUAL.md`](USER_MANUAL.md).

Mit dem Quellenprofil gewichten *Sie*, welche Dimensionen zählen. Aber **niemand kann Tausende von Quellen
allein neutral beurteilen** — also muss die Gewichtung **gemeinschaftlich** erfolgen. Der
ehrliche, lokal zuerst arbeitende, nicht zentralisierte Weg dafür sind **signierte, teilbare Anmerkungs-
pakete**.

- Sie veröffentlichen Ihre Quellenanmerkungen — Koordinations-Tags, Fakten zu Eigentum/Transparenz,
  Tags zur Ausrichtung, Korrekturen, Notizen — als **von der Beweiskette signiertes, prüfbares, portables
  Paket** (mit demselben hybriden Signierer aus Ed25519 + ML-DSA wie die Beweiskette —
  *Gemeinsamnutzung*, kein zweiter Kryptografie-Stapel).
- Andere Nutzer **importieren** die Pakete, denen sie vertrauen möchten — ein freiwilliges **Web of Trust**,
  **niemals** eine zentrale Instanz.
- Die Zusammenführung ist **transparent**: Sie sehen immer, *wer was behauptet hat*, und **abweichende Meinungen werden
  gezeigt, nicht gemittelt** zu einer versteckten Zahl.

Kein Server, keine Konten, kein globaler Wert — **Föderation durch signierten Austausch.**

### Was eine Anmerkung ist (und was nicht)

Eine Anmerkung ist eine **beschreibende, anfechtbare Tatsache oder ein Tag** zu einer Quelle. Arten:
`ownership`, `leaning`, `coordination-tag`, `transparency-fact`, `correction`, `note`.
Sie ist **niemals** ein zusammengesetzter Vertrauens-/Qualitätswert — das ist verboten, durch die Gestaltung und im
Code (eine ungültige Art wie `trust-score` wird zurückgewiesen).

### Vertrauensmodell — was eine Signatur beweist und was nicht

Jedes Paket enthält die **öffentliche Identität** des Autors und eine Signatur über das kanonische
Manifest. Die Prüfung **heftet** den eingebetteten Schlüssel **an**, sodass ein Angriff aus Manipulieren-und-neu-Signieren
den ursprünglichen Autor nicht *imitieren* kann — er erzeugt lediglich einen **anderen** Autor. Ein
geprüftes Paket wird daher immer wahrheitsgemäß dem Schlüssel zugeordnet, der es signiert hat.
Sie entscheiden dann, *welchen Schlüsseln Sie vertrauen*; nur die Anmerkungen vertrauenswürdiger Autoren werden zusammengeführt.

Das ist **ein Web of Trust, kein Beweis für Richtigkeit**: Einem Autor zu vertrauen heißt „ich möchte
seine Behauptungen sehen“, nicht „seine Behauptungen sind wahr“. Abweichende Meinungen zwischen vertrauenswürdigen Autoren
werden Ihnen zur Beurteilung gezeigt, niemals für Sie aufgelöst.

### Verwendung (der Quellenintegritäts-Desk — Einstellungen → Erweitert → Sicherheit)

1. **Verfassen** Sie Anmerkungen (Ziel + Art + Wert) unter *Geteilte Anmerkungen*.
2. **Signiertes Paket exportieren** → eine JSON-Datei, die Sie veröffentlichen oder weitergeben können.
3. **Bündel importieren…** → die App **prüft die Signatur**, bevor sie es speichert (ein ungültiges
   Paket wird laut zurückgewiesen), und führt den Autor dann unter *Vertrauenswürdige Autoren* mit einem
   Vertrauensschalter auf.
4. **Wer hat was gesagt?** → führt jede Behauptung über eine Quelle von Ihnen + vertrauenswürdigen
   Autoren zusammen, mit Zuordnungen und abweichenden Meinungen.

Wenn Sie einem Autor das Vertrauen entziehen, werden seine Anmerkungen ausgeschlossen; wenn Sie ihn entfernen, werden sie sauber gelöscht.

### API

| Methode & Pfad | Zweck |
|---|---|
| `GET /api/annotations/mine` · `POST` · `DELETE /mine/{i}` | Ihre selbst verfassten Anmerkungen |
| `GET /api/annotations/export` | ein signiertes, portables Paket Ihrer Anmerkungen |
| `POST /api/annotations/import` | ein importiertes Paket prüfen + speichern (bei Ungültigkeit zurückgewiesen) |
| `GET /api/annotations/authors` · `PUT /authors/trust` · `DELETE /authors/{id}` | das Web of Trust |
| `GET /api/annotations/for?target=` | transparente Zusammenführung — wer was behauptet hat |

### Ehrlichkeitsvorgaben

- **Kein Mitteln, keine Konsenszahl, kein Wert.** Die Zusammenführung liefert zugeordnete
  Behauptungen und benennt *abweichende Meinungen*; sie fasst Uneinigkeit nie zu einer Zahl zusammen.
- **Lokal zuerst.** Alles ist eine Datei in Ihrem Datenverzeichnis; nichts wird übertragen, und
  es gibt weder Server noch Konto.
- **Anfechtbar durch die Bauweise.** Jede Anmerkung ist ein Tag/eine Tatsache, über die Sie und andere
  uneins sein können — sichtbar.


---

## Einblicke — Analysen von Schlagwörtern & Entitäten

### Zweck

Den einheitlichen Korpus von einem Suchfeld in ein Analyseinstrument verwandeln. Schlagwörter
und Entitäten werden aus dem **Text aufgenommener Artikel** extrahiert, mit ihren
Vorkommen und ihrem Kontext gespeichert und so aufbereitet, dass eine investigative Journalistin fragen kann:
*Worüber wird gesprochen, wo, wann, von wem und in Verbindung womit?*

Alles hier ist eine **echte Aggregation** über gespeicherte Daten mit angegebener Methode und
Stichprobengröße — niemals ein erfundener Wert (PRODUCT_SYNTHESIS §3.5).

### Funktionsweise

```
ingest an article ──► extract (baseline / opt-in spaCy) ──► KeywordMention rows
                          terms + entities, offsets        (count + first offset +
                                                            denormalised date/country/city)
                                                                   │
                          Insights tab / /api/insights  ◄──────────┘
                          trends · associations (PMI) · context · map
```

- **Extraktion** (`src/analytics/extract.py`): thematische N-Gramm-**Begriffe**
  (nach Stoppwörtern gefiltert) plus **Entitäten** — Personen, Unternehmen/Organisationen, Orte — als
  einzelne Einheiten. Die Basisvariante (ohne Abhängigkeiten) erkennt Entitäten als mehrteilige
  Folgen großgeschriebener Wörter (Title Case) und vergibt eine Art `person`/`org`/`location` nur anhand eines
  Ortsverzeichnisses (Gazetteer) (andernfalls die ehrliche allgemeine Art `entity`); ein optionales **spaCy**-Extra `[nlp]`
  ergänzt echte Erkennung benannter Entitäten für `PERSON`/`ORG`/`GPE`. Jedes Schlagwort vermerkt, **welcher Extraktor
  es beschriftet hat** — ein Entitätstyp ist eine *von-X-beschriftet-Aussage*, keine gesicherte Wahrheit.
  Am besten geeignet für Schriften mit Leerzeichen zwischen Wörtern; Segmentierung für CJK/Arabisch ist ein bekannter späterer Schritt.
- **Speicherung** (`src/analytics/store.py`): ein `KeywordMention` je (Artikel,
  Schlagwort) — Anzahl der Vorkommen + Zeichenposition des ersten Vorkommens (der Kontextsatz wird beim Lesen
  aus dem gespeicherten Artikel ausgeschnitten, damit die Datenbank schlank bleibt) + denormalisierte Angaben
  `observed_on` / `country` / `city` aus der Quelle. Die Indizierung läuft nach bestem Bemühen bei der
  Aufnahme (schnelle Basisvariante, fail-open). Die Indizierung erfolgt **automatisch** — ein Rückstand wird
  durch eine stille Nachindizierung im Hintergrund abgearbeitet, wenn Sie Einblicke öffnen (der Zähler für „verbleibend“ zählt
  von selbst auf 0 herunter); es gibt keine Schaltfläche „Korpus indizieren (Index corpus)“. Eine vollständige Neuindizierung des vorhandenen Korpus
  ist unter **Einstellungen → Erweitert → Diagnose** verfügbar („Gesamten Korpus neu indizieren“ / „Schlüsselwörter
  bereinigen“) als pausierbarer Hintergrundauftrag.

### Funktionen (Tab Einblicke + `/api/insights`)

| Ansicht | Endpunkt | Was sie zeigt |
|------|----------|---------------|
| Erkunden — Trend | `GET /trend?term=&bucket=` | Volumen der Erwähnungen im Zeitverlauf (Tag/Woche/Monat), mit dem aufgelösten Schlagwort + Art |
| Erkunden — Mindmap | `GET /associations?term=` | Gemeinsam auftretende Schlagwörter, geordnet nach **PMI** (punktweise Transinformation), mit Stichprobengrößen + dem Vorbehalt „Assoziation ≠ Kausalität“; klicken Sie auf einen Knoten, um ihn ins Zentrum zu setzen |
| Erkunden — Kontext | `GET /context?term=` | Aktuelle Ausschnitte von Erwähnungen aus dem Artikeltext, mit Verweisen auf Artikel/Quelle + Land/Stadt/Datum |
| Trends | `GET /trending`, `GET /top` | Steigende Begriffe (**Verhältnis** aktuell zu vorher, eine beschriftete Kennzahl) und Top-Begriffe, filterbar nach Zeitfenster / Art / Land |
| Karte | `GET /map?days=&kind=` | Top-Schlagwörter **je Land und je Stadt** (regionales Signal auf Basis der Quelle) |
| Indizierung | `GET /status`, `POST /reindex?limit=` | Anzahl indiziert/verbleibend; schrittweises Nachindizieren des Korpus |

Filter für `kind`: `term`, `entity`, `person`, `org`, `location`.

### Ehrlichkeitsgarantien

- Trends/Top sind echte Zählungen; „steigend“ ist ein definiertes **Verhältnis** aktuell zu vorher,
  ausdrücklich *kein* Signifikanztest.
- Assoziationen verwenden **PMI** über das gemeinsame Auftreten in Artikeln und werden mit `n` und dem
  Vorbehalt geliefert, dass kleine Stichproben verrauscht sind.
- Entitätsarten tragen die Herkunft ihres Extraktors; die Basisvariante behauptet nie einen genauen
  Typ Person/Organisation/Ort, den sie nicht begründen kann.
- Die Region auf der Karte ist Land/Stadt der **Quelle** (das verlässliche Signal). Die
  Ansicht Karte enthält jetzt ein **interaktives SVG in plattkarter Projektion** (Zoomen/Verschieben, Städte-
  beschriftungen beim Zoomen), das Städte nach echten Breiten-/Längengraden aus einem **Ortsverzeichnis (Gazetteer)** einzeichnet: Eine kleine
  Stichprobe wird mitgeliefert (`configs/cities.sample.yml`); der vollständige Satz wird aus
  Wikidata erzeugt (`scripts/build_city_gazetteer.py` → `configs/cities.yml`). Eine Stadt ohne
  Treffer im Ortsverzeichnis behält ihre Schlagwortdaten, aber **keine eingezeichnete Position** (niemals ein
  erfundener Ort). Tabellen nach Land/Stadt bleiben neben der Karte erhalten.


---

## Änderungsverfolgung für Wikipedia

### Zweck

Wikipedia ist umkämpftes Terrain: Artikel werden ständig bearbeitet, und im LLM-
Zeitalter ist es leichter denn je, Geschichte zu entfernen oder umzuschreiben. Dieses Werkzeug behandelt jede
Wikipedia-**Sprachausgabe** als verfolgte Quelle, deren *Bearbeitungen* die Daten sind, sodass
eine Journalistin großflächige oder geschichtsverfälschende Änderungen **erkennen und dokumentieren** kann —
z. B. nachweisen, dass ein Satz an einem bestimmten Datum existierte und von einem bestimmten
Konto entfernt wurde.

> Ausgaben gibt es je **Sprache** (`en`, `fr`, `ar`, `ru`, `zh`, …), nicht
> je Land (es gibt keine nationale Wikipedia); die Oberfläche ordnet Sprachen Ländern zu.

### Warum dies keine Aufnahme „gewöhnlicher Artikel“ ist

Artikel ändern sich im Lauf der Zeit, daher können sie nicht als einmalige `Article`-Zeilen gespeichert werden.
Daraus folgen zwei Gestaltungsentscheidungen:

1. **Die MediaWiki Action API verwenden, kein Auslesen von Seiten** — `revisions`,
   `recentchanges` (mit Byte-Differenzen) und `compare` (serverseitig berechnete Unterschiede). Das
   ist der effiziente, nutzungsbedingungsfreundliche, auf Änderungen ausgerichtete Weg.
2. **Differenzen speichern, keine erneuten Kopien** — **eine** komprimierte Volltext-Basisversion
   je Seite (`wiki_pages.baseline_text`) behalten; jede spätere Bearbeitung ist eine `wiki_revisions`-
   Zeile mit dem **Diff + vorzeichenbehafteter Byte-Differenz + Markierungen**, niemals dem ganzen neuen
   Artikel. Jede historische Fassung lässt sich durch erneutes Anwenden der Diffs rekonstruieren.

**Das beantwortet die Frage nach Redundanz und Speicherplatz:** Eine kosmetische Bearbeitung ist ein winziger Diff
mit der MediaWiki-Markierung `minor` und wird durch eine Schwelle für Größe/geringfügige Änderung herausgefiltert, sodass sie
fast nichts kostet. Der Speicherbedarf wächst mit der **Bearbeitungsaktivität auf beobachteten Seiten**, nicht
mit dem mehrere GB großen Artikelkorpus — für die Verfolgung brauchen Sie nie den vollständigen Dump.

### Erkennen großflächiger / verdächtiger Bearbeitungen (ehrlich)

`src/wiki/flagging.py` markiert eine Bearbeitung und vermerkt **Begründungscodes** — es zeigt
*Kandidaten* auf, es erklärt nichts zur „Desinformation“:

- `large_removal` / `large_addition` — Byte-Differenz über einer Schwelle
- `revert` / `blank` — MediaWiki-Änderungsmarkierungen (`mw-reverted`, `mw-undo`, `mw-blank`…)
- `anon_large` — eine mittlere oder größere Bearbeitung von einer anonymen IP
- `burst` — viele Bearbeitungen an einer Seite in kurzer Zeit
- `ores_damaging` — optionale „damaging“-Wahrscheinlichkeit von **Wikimedia ORES**, dargestellt
  als *von-ORES-beschriftet*-Aussage (wie unsere Herkunftsangabe bei Entitäten)

Geringfügige kosmetische Bearbeitungen werden nie markiert. Jede markierte Bearbeitung wird mit ihrem
Diff + ihrer Herkunft (revid, Bearbeiter, Zeitstempel) dokumentiert, was an die vorhandene
**Beweiskette** für signierte/mit Zeitstempel versehene Belege anschließt.

### Zwei klar getrennte Teilsysteme (UX)

1. **Beobachten & verfolgen (Watch & track)** (leichtgewichtig, sofort, der Standard): eine Beobachtungsliste von Seiten /
   Kategorien je Sprachausgabe; Versionen über den Planer in der App abfragen; Versionen
   + Diffs + Markierungen speichern; eine Diff-Ansicht + Zeitleiste je Seite. Kein Massendownload.
2. **Offline-Basislinie (Offline baseline)** (schwergewichtig, optional): befindet sich unter **Einstellungen → Wikipedia-
   Offline-Basislinien** (bewusst abseits des leichtgewichtigen Trackers). Eine
   **auswählbare Liste von Sprachausgaben** (kuratiert, die größten zuerst, mit dem Eigennamen jeder
   Sprache und einer groben Größenstufe) ersetzt die Eingabe eines Codes als Freitext; die
   genaue aktuelle Dump-Größe wird auf Anfrage vom Server gelesen (`Estimate size`),
   dann herunterladen / pausieren / fortsetzen / löschen. Die Liste stammt aus
   `GET /api/wiki/languages`; das Download-Programm akzeptiert weiterhin jeden Ausgabecode.
   (Größen in der Praxis: enwiki mit aktuellem Text ≈ 22 GB komprimiert; die vollständige Versionsgeschichte umfasst
   Terabytes — nur für historische Diffs im Offline-Betrieb nötig.)

### Stand

- **Erledigt:** Schema (`wiki_pages`, `wiki_revisions`; Migration `d4e5f6a7b8c9`);
  der MediaWiki-API-Parser + Live-Client (`mediawiki.py`, `client.py`); die
  Logik zum Markieren von Bearbeitungen (`flagging.py`); ORES-Client (`ores.py`); die Steuerung
  der Verfolgung (`track.py`, Speicherung von Basisversion + Differenzen); der Planermodus `wiki`;
  die **API** (`/api/wiki/*`) und **Einstellungen → Wikipedia** (Beobachtungsliste, jetzt verfolgen,
  Feed markierter Änderungen, Diff-Ansicht); das **Download-Programm für Offline-Basislinien**
  (`dumps.py` — je Sprache, fortsetzbar, Größenabfrage), jetzt gesteuert über eine **Sprach-
  auswahl** (`languages.py`, `GET /api/wiki/languages`), verlegt nach **Einstellungen →
  Wikipedia-Offline-Basislinien**. Sämtliche reine Logik + Steuerung ist mit
  Testdaten (fixtures) unit-getestet (ohne Netzwerk).
- **Als Nächstes:** Wiki-Diffs mit den Schlagwortanalysen von Einblicke verknüpfen; optionaler
  EventStreams-Datenstrom (firehose); Export eines markierten Diffs als Beleg über die Beweiskette.

### Ethik

Jeder Abruf hält die Nutzungsrichtlinie der MediaWiki API ein (identifizierender User-Agent,
`maxlag`, Ratenbegrenzungen) — rücksichtsvoller als Scraping. Wir speichern nur öffentliche
Versionsdaten; nichts wird abgerufen, bevor die Verfolgung läuft.


---

## Weltrecht — Änderungsverfolgung für Gesetze, Amtsblätter & geistiges Eigentum

> **Stand:** `0.06` Phase E — ausgeliefert. Der Fachbereich aus §5: eine „Wikipedia für das Recht“.
> Nutzt den Motor zur Änderungsverfolgung (`src/wiki`) und die gemeinsamen Motoren aus `src/signals/` erneut.

Das **Recht** zusammentragen — Gesetze, Rechtsvorschriften, Amtsblätter, Register zum geistigen Eigentum — aus
offiziellen Quellen weltweit, und **verfolgen, wie es sich im Lauf der Zeit ändert**. Recht ist in
vielen Ländern öffentlich und ändert sich durch Novellierungen, also *sind* die Daten der Diff: was sich geändert hat und wann.

### Standardmäßig an — ein weltweiter Katalog echter offizieller Quellen

`configs/legal_sources.yml` liefert einen kuratierten, weltweiten Bestand **echter offizieller Primär-
quellen** — nationale Gesetzesdatenbanken (`legislation.gov.uk`, EUR-Lex, Légifrance,
`gesetze-im-internet.de`, `congress.gov`/`govinfo.gov`, `legislation.gov.au`,
`indiacode.nic.in`, `elaws.e-gov.go.jp`, `law.go.kr`, …), Amtsblätter, Ämter für geistiges Eigentum
(WIPO Lex, USPTO, EPO, EUIPO, JPO, …) und offene Systeme für Rechtsprechung/Einreichungen (CourtListener,
SEC EDGAR). Beim ersten Start werden diese als gewöhnliche **aufnehmbare, durchsuchbare** Quellen angelegt
(`source_type` legal/ip), sodass sie durch *dieselbe* ethische Verarbeitungskette laufen wie Nachrichten.

Eine kuratierte Teilmenge stabiler, bekannter **konsolidierter Rechtstexte** (z. B. der britische Human
Rights Act, die EU-DSGVO, die US-Verfassung) ist von Haus aus für die **Änderungsverfolgung**
registriert.

### Wie die Verfolgung funktioniert (nutzt den Wikipedia-Motor erneut)

Für jedes verfolgte Dokument ist der erste erfolgreiche Abruf die unveränderliche **Basisversion**
(„das Recht, wie es am Datum X galt“). Jeder spätere Abruf, dessen *normalisierter sichtbarer Text*
abweicht, erfasst eine Version mit der Byte-Differenz, einem gekürzten vereinheitlichten **Diff** gegenüber der
Basisversion und einer ehrlichen **Markierung für große Änderungen** (mit denselben Markierungsschwellen wie bei Wikipedia).
Starten Sie sie über **Tab Regierungen → Untertab Recht** („Änderungen jetzt verfolgen“) oder über den
Hintergrund-Planer (Modus `law`). Jeder Abruf läuft über den **ethischen,
robots.txt-fail-closed** Weg.

### Ein Gesetz aus dem eigenen XML des Herausgebers lesen (strukturierte Quellen)

Eine Webseite muss erst zu Text *rekonstruiert* werden: Navigation, Suchformular und
Cookie-Banner entfernen und hoffen, dass der Rest das Gesetz ist. Das funktioniert, und so
geht der Tracker bei den meisten Quellen vor — aber die gespeicherte Kopie eines britischen
Gesetzes begann einmal mit dem eigenen Suchformular des Portals, und alles, was daraus
abgeleitet wurde (eine „Personal Acts“-Person, eine „PART“-Organisation), stammte aus Text,
der nie im Gesetz stand.

Wo ein Herausgeber sein **eigenes XML** bereitstellt, entfällt all das: In der Datei gibt es
keine Seitenelemente, denn die Datei ist keine Seite. Open Omniscience kann das CLML von
`legislation.gov.uk` direkt lesen, was zusätzlich zwei Dinge liefert, die eine Seite nicht bieten kann:

- **Bestimmungen mit zitierfähigen Adressen.** Jeder Abschnitt wird mit dem darüberliegenden
  Teil-/Kapitelpfad gelesen, sodass eine Änderung als *„Abschnitt 12 von Teil 2 wurde geändert“*
  gemeldet werden kann statt als Anzahl von Bytes. Abschnitte werden über diese Adresse
  zugeordnet und nie über ihre Position — sonst würde das Einfügen eines einzigen Abschnitts
  den gesamten restlichen Teil des Gesetzes als geändert melden.
- **Daten, die bedeuten, was sie sagen.** Inkrafttreten, Konsolidierungsstand und das Datum,
  an dem *wir* das Dokument abgerufen haben, sind drei getrennte Felder ohne gegenseitigen
  Ersatz. Ein Datum, das das Dokument nicht nennt, wird als unbekannt angezeigt und nie aus
  einem anderen aufgefüllt. (Deshalb zeigt ein verfolgtes Gesetz kein Veröffentlichungsdatum,
  sofern das Dokument selbst keines liefert: Das einzige verfügbare Datum war der Tag, an dem
  wir die Seite abgefragt haben, und ein Abfragedatum ist kein Veröffentlichungsdatum.)

Der Vergleich pro Abschnitt ist **ergänzend und experimentell**: Der gewöhnliche Textvergleich
entscheidet weiterhin, ob eine Revision erfasst wird, und trägt weiterhin die Markierung für
große Änderungen. Und eine Grenze wird offen benannt statt geglättet — ein Abschnitt, der in
derselben Änderung *neu nummeriert und umgeschrieben* wird, wird als eine Entfernung plus eine
Hinzufügung gemeldet, denn ihn seinem früheren Ich zuzuordnen hieße zu raten, welcher von zwei
unterschiedlich nummerierten Abschnitten „derselbe, bearbeitet“ ist.

**Was es noch nicht gibt:** Bisher ruft nichts diese XML-Dokumente automatisch ab. Das gesamte
Rechtskorpus einer Rechtsordnung zu lesen bedeutet, die eigene Liste des Herausgebers
durchzugehen (das Vereinigte Königreich listet jedes Gesetz auf; Frankreich listet 76 Gesetzbücher),
und diese Aufzählung ist nicht gebaut. Bis dahin bleibt die verfolgte Menge die kuratierte, und
der Abdeckungsbericht sagt ehrlich „Abdeckung unbekannt“ (coverage unknown), statt eine Anzahl
verfolgter Dokumente so darzustellen, als wäre sie das gesamte Korpus.

### Prüfen, ob die Gesetzeskorrekturen Ihre Daten erreicht haben

Zwei Gesetzeskorrekturen heilen **still, beim nächsten erfolgreichen Abruf eines Dokuments**:
Seitenelemente werden aus einer gespeicherten Ausgangsfassung neu herausgelesen, und ein
Veröffentlichungsdatum, das in Wahrheit ein Abfragedatum war, wird gelöscht. Beides ist
richtig — und ein Dokument, dessen Portal nicht erreichbar ist, heilt nie, und genau dieser
Fall ist wissenswert.

Der Bericht **law-ingest** (im Gesamtpaket aller Diagnosen oder einzeln) beantwortet das aus
gespeicherten Daten ohne Netzwerkaufruf: was die letzte Prüfung jedes verfolgten Dokuments
festgehalten hat (eine Anzahl pro Ergebnis, etwa unverändert, neu gelesen, Fehler oder
zurückgestellt, sowie das eigene Ergebnis jedes Dokuments und den Zeitpunkt des letzten
Versuchs), und ob ein Gesetzesartikel noch ein Veröffentlichungsdatum trägt, das er nicht
tragen sollte. Ein Dokument, dessen letzte Prüfung fehlschlug, verdient einen Blick, aber der
Bericht kann nicht sagen, ob es einmal neu gelesen wurde, bevor die Fehler begannen: Das wird
nicht erfasst. Die Zahl der Neulesungen selbst zählt nur Dokumente, deren jüngste Abfrage die
Neulesung war, sodass sie auf einer Installation, auf der jedes Dokument geheilt ist, gegen
null zurückfällt.

Er meldet außerdem **Reste von Seitenelementen** (chrome residue) — Navigationstext, der noch in
einem gespeicherten Text steht. Lesen Sie das als *Messung*, nicht als Urteil: Das Entfernen der
Seitenelemente entfernt bewusst nur, was das Markup als solche ausweist, und lässt den Rest
stehen, denn eine Regel auf Textabgleich würde auch die eigenen Abschnittsüberschriften eines
Gesetzes löschen. Reste nach einer korrekten Neulesung sind zu erwarten; die Zahl sagt Ihnen,
wie viele nicht ausgewiesene Seitenelemente in Ihrem Korpus stecken, und die Markerliste ist
eine Untergrenze, sodass null „keines davon“ bedeutet, nie „keine Seitenelemente“.

### Briefing-Karten aus dem Rechtskorpus

- **Gesetz geändert** (Law changed) (beobachten) — eine markierte Änderung an einem verfolgten
  Rechtsdokument.
- **Mustergesetzgebung** (untersuchen) — nahezu identischer Rechtstext in zwei oder mehr
  Rechtsordnungen (die §1/§2-Engine für Beinahe-Duplikate), ein messbares Verbreitungsmuster.

Außerdem funktionieren, weil der Rechtstext im einheitlichen Korpus liegt, die Korrelation
**Recht ↔ Nachrichten** und die Schlagwortanalysen darüber wie bei jeder anderen Quelle.

### API

| Methode & Pfad | Zweck |
|---|---|
| `GET /api/law/status` | Abdeckung: Dokumente pro Rechtsordnung, Summen der Änderungen/Markierungen |
| `GET /api/law/documents` | verfolgte Dokumente (optional `?jurisdiction=`) |
| `GET /api/law/documents/{id}` | ein Dokument mit seinem Änderungsverlauf (Diffs) |
| `GET /api/law/changes` | jüngste (markierte) Rechtsänderungen, neueste zuerst |
| `POST /api/law/track` | alle beobachteten Dokumente jetzt abrufen (ethischer Fetcher) |
| `POST /api/law/seed` | den weltweiten Katalog (neu) einspielen + Dokumente registrieren |

### Ehrlichkeitsvorgaben (beim Recht steht viel auf dem Spiel)

- **Keine Rechtsberatung, nicht die maßgebliche Quelle.** Die zusammengeführte Kopie ist ein
  *Recherche-Spiegel*; jeder Eintrag verlinkt zurück auf das amtliche Verkündungsblatt, und die
  Oberfläche sagt das. Verfolgen und sichtbar machen; nie die Rechtmäßigkeit auslegen oder ein
  Gesetz bewerten.
- **„Öffentlich“ ≠ „frei weiterverbreitbar“.** Lizenzen unterscheiden sich, selbst wo der Text
  öffentlich ist — jede wird beachtet und mit Quellenangabe versehen, die Herkunft wird
  gespeichert, robots.txt schlägt geschlossen fehl (wie bei Nachrichten).
- **Den Umfang ehrlich benennen.** „Jedes Land“ ist der Leitstern, nicht v1: Der Katalog ist
  breit, aber kuratiert, und die Änderungsverfolgung erfolgt über einen Vergleich des
  normalisierten Textes (Portale mit konsolidierten Fassungen liefern das sauberste Signal). Wo
  ein Herausgeber strukturiertes XML bereitstellt, sind Vergleiche pro Abschnitt verfügbar
  (siehe oben) — heute CLML; Akoma Ntoso / ELI werden noch nicht gelesen. Das Werkzeug sagt für
  jedes Dokument, was es davon hat, und weigert sich zu raten: Ein Dokument, das es nicht
  strukturell auswerten kann, behält den Textvergleich, statt so gemeldet zu werden, als hätte es
  Abschnitte.
- **Übersetzung** (über das lokale LLM) ist eine separate, deutlich gekennzeichnete Hilfe —
  nie eine maßgebliche juristische Übersetzung.


---

## Märkte: Finanz-, Börsen- und Rohstoff-/Seltenerd-Informationen

Open Omniscience liefert einen **kuratierten, weltweiten Katalog von Marktquellen** mit, damit
es direkt nach der Installation Finanzmarktberichterstattung aufnehmen kann, sowie einen Tab
**Rohstoffe**, der *konfigurierte* Seiten in eine echte, als Diagramm darstellbare Preisreihe
verwandelt, die mit Nachrichten korreliert wird.

Dieses Dokument erklärt, was vorinstalliert ist, was nicht, und warum — denn die ehrliche
Grenze ist hier wichtiger als eine lange Funktionsliste.

### Was vorinstalliert ist (sofort einsatzbereit)

`configs/markets_sources.yml` wird beim ersten Start automatisch zusammen mit dem
Nachrichtenkatalog (`configs/sources.yml`) eingespielt sowie über **Einstellungen → Erweitert →
Quellen → Startquellen einrichten**. Er enthält ~110 kuratierte Einträge, die über eine stabile
Hauptdomain identifiziert werden:

- **Aktien- und Wertpapierbörsen** weltweit (Amerika, Europa, Asien-Pazifik, Naher Osten,
  Afrika) — NYSE, Nasdaq, LSE, Euronext, Deutsche Börse, JPX, HKEX, SSE/SZSE, NSE/BSE Indien,
  SGX, ASX, B3, Tadawul, JSE und viele mehr.
- **Rohstoff-, Metall-, Energie- und Derivatebörsen** — CME Group, ICE, LME, SHFE, DCE, ZCE,
  INE, **GFEX** (Futures auf Seltene Erden & Industriesilizium), MCX, Eurex, MGEX.
- **Preis- und Datenquellen für Rohstoffe & Seltene Erden** — Shanghai Metals Market, Kitco,
  USGS, World Bank Pink Sheet, EIA, IEA, OPEC, Fastmarkets, Argus, Benchmark Mineral
  Intelligence, S&P Global Commodity Insights.
- **Finanznachrichten- und Datenanbieter** — Bloomberg, Reuters, FT, WSJ, CNBC,
  MarketWatch, Nikkei Asia, Caixin und weitere.

Das sind gewöhnliche **Quellen**: Sie speisen das einheitliche Korpus über denselben ethischen
Fetcher (robots.txt schlägt geschlossen fehl, Ratenbegrenzung). Jede trägt einen
`source_type` (`stock_exchange` / `commodity` / `financial`), eine Region, ein Land und
Schlagwörter, sodass Sie sie unter **Einstellungen → Erweitert → Quellen** filtern und unter
**Rohstoffe** Preisregeln anhängen können.

> RSS-Feeds sind bei diesen Einträgen absichtlich leer gelassen (eine falsche Feed-URL ist
> nur Rauschen). Nehmen Sie sie mit dem rekursiven Crawler auf, oder fügen Sie pro Quelle unter
> **Einstellungen → Erweitert → Quellen** einen geprüften RSS-Feed hinzu.

### Echte Preiszahlen erhalten

Eine Preisreihe entsteht nur dort, wo Sie der App **genau sagen, wo die Zahl steht** — es gibt
bewusst kein magisches Auslesen von Seiten. Zwei ehrliche Wege:

#### 1. Extraktionsregeln pro Seite (Tab Rohstoffe → „Datenquellen konfigurieren“)

*(Die Feeds und Extraktionsregeln liegen in einem eingeklappten Bereich „Datenquellen
konfigurieren“ (Configure data sources) auf dem Tab Rohstoffe; die kuratierten Feeds selbst
werden im Hintergrund automatisch aktualisiert.)*

Fügen Sie eine Regel hinzu (Quelle, Symbol, Seiten-URL, **CSS-Selektor**, optional Attribut /
Wert-Regex, Währung, Einheit) und drücken Sie dann **Testen**. Der Test ruft die Seite einmal ab
und zeigt den *genauen* gefundenen Wert — oder den *genauen* Grund, warum nichts passte —, sodass
Sie den Selektor mit echter Rückmeldung abstimmen können. Passende Regeln speichern einen
`CommodityPrice` pro Tag, den die eingebetteten Diagramme und die Preis↔Nachrichten-Korrelation lesen.

Vorlagen zum Kopieren: `configs/market_rules.example.yml`.

**Vorbehalt (bitte lesen):** Die meisten Börsen- und Kursseiten zeigen Preise per JavaScript
an, daher steht die Zahl *nicht* im statischen HTML, das der Fetcher erhält, und ein Selektor
findet nichts. Deshalb werden funktionierende Selektoren **nicht** mitgeliefert — sie zu raten
hieße, Zahlen zu erfinden. Serverseitig gerenderte Seiten (viele amtliche/statistische Websites,
manche Datentabellen) funktionieren gut; stark clientseitig gerenderte Kurs-Widgets nicht.

#### 2. Offizielle CSV-Feeds (empfohlen — zuverlässig, mit Katalog)

Für vertrauenswürdige Zahlenreihen importieren Sie eine maschinenlesbare CSV-Reihe aus einer
amtlichen Quelle. Das ist der zuverlässige Weg, und die App liefert einen Startkatalog
(`configs/commodity_feeds.yml`) mit, den Sie mit einem Klick unter
**Rohstoffe → Datenquellen konfigurieren → Offizielle Preis-Feeds** oder über die API importieren können:

```
GET  /api/markets/feeds                # list curated feeds + how many points each has
POST /api/markets/feeds/{key}/import   # import one (e.g. copper, wti_crude, brent_crude)
POST /api/markets/feeds/import-url      # import ANY CSV URL you supply (user-customizable)
```

**Hauptanbieter — FRED** (Federal Reserve Bank of St. Louis): ein stabiler CSV-Endpunkt ohne
API-Schlüssel, `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`, der **die
Rohstoffreihen des „Pink Sheet“ der Weltbank weiterverbreitet** (die IDs „Global price of …“ —
Kupfer `PCOPPUSDM`, Brent `POILBREUSDM` usw.) sowie Energiereihen der **EIA** (`DCOILWTICO`,
`DHHNGSP`, …). Die erste Spalte ist das Datum, die zweite der Wert; fehlende Werte (`.`) werden
übersprungen, nie als null gespeichert. Der Import ist idempotent pro `(symbol, market, date)`.

**Vergleichbare Quellen**, die Sie als eigenen Feed hinzufügen können (URL + optionale Spaltennamen):
- **Weltbank** Commodity Markets („Pink Sheet“): Die `.xlsx` liegt unter
  <https://www.worldbank.org/en/research/commodity-markets>; dieselben Reihen als saubere CSV
  kommen über die FRED-Feeds oben.
- Offene Energiedaten der **U.S. EIA**: <https://www.eia.gov/opendata/>
- **IWF** Primary Commodity Prices: <https://www.imf.org/en/Research/commodity-prices>
- Mineralische Rohstoffdaten des **USGS** (Seltene Erden): <https://www.usgs.gov/centers/national-minerals-information-center>

Die Standard-Spaltenzuordnung ist Spalte 1 = Datum, Spalte 2 = Wert (die FRED-Konvention);
nennen Sie `date_column` / `value_column` ausdrücklich für andere Layouts.

Es gibt außerdem einen direkten Datei-Upload für eine CSV, die Sie bereits haben:

```
POST /api/commodities/{symbol}/prices/import-csv      (multipart file upload)
```

> Wenn ein Anbieter eine Reihe umbenennt oder einstellt, schlägt der Import **laut** fehl
> (HTTP-Fehler / keine verwertbaren Zeilen), statt Daten zu erfinden — korrigieren Sie die URL in
> `configs/commodity_feeds.yml` oder verwenden Sie einen eigenen Feed.

### Warum keine automatisch extrahierten Preise ab dem ersten Tag?

Weil eine Zahl ohne überprüfbare Herkunft schlimmer ist als keine Zahl. Alles in diesem Werkzeug
ist so gebaut, dass eine dem Nutzer gezeigte Zahl aus einer echten Messung stammt: einem Selektor,
der tatsächlich gepasst hat, oder einer CSV, die tatsächlich importiert wurde. Der Katalog
verschafft Ihnen die *Quellen* sofort; Sie entscheiden pro Seite, wann ein Preis vertrauenswürdig
genug ist, um ihn zu erfassen.


---

## Verwahrungskette

Open Omniscience erhebt einen bewusst *engen und ehrlichen* Beweisanspruch:

> **Dieses Korpus enthielt _dieses_ Element, mit _diesem_ Inhalt, erfasst zu _dieser_
> Zeit, und der Eintrag wurde seitdem nicht verändert — und hier ist ein kryptografischer
> Beweis, den Sie selbst prüfen können, offline, ohne diesem Werkzeug vertrauen zu müssen.**

Das ist für investigative Journalistinnen und Journalisten wirklich nützlich: Es schützt gegen
„Sie haben das erfunden“, „Sie haben das rückdatiert“ oder „Sie haben es nachträglich still
bearbeitet“, und es lässt Sie zeigen, dass Sie über etwas berichtet haben, *bevor* eine Quellseite
geändert oder gelöscht wurde. Es ist **kein** Einreichungssystem für Whistleblower (wie
SecureDrop), und eine „Quelle“ ist in diesem Werkzeug ein *Nachrichtenmedium*, keine vertrauliche
menschliche Quelle. Behalten Sie diesen Umfang im Blick, wenn Sie über Schutz nachdenken.

Dieses Dokument beschreibt die tatsächlichen Mechanismen (`src/custody/`, `src/reporting/`) und
sagt ausdrücklich, was jeder davon beweist und was **nicht**.

---

### Die drei Eigenschaften und wie wir jede ehrlich erreichen

| Eigenschaft | Mechanismus | Was sie beweist | Was sie **nicht** beweist |
|---|---|---|---|
| **Integrität** | Ed25519- (+ optional ML‑DSA-)Signaturen über eine kanonische Serialisierung; Merkle-Wurzel über alle Herkunftsfelder | Die Bytes haben sich seit dem Signieren nicht verändert; alles ist abgedeckt, nicht nur der Inhalt | — |
| **Herkunft** | **Festlegen** (Pinning) des bekannten öffentlichen Schlüssels des Signierenden | Der Eintrag wurde von *diesem* Signierenden signiert | Gar nichts, wenn Sie keinen Schlüssel festlegen — eine gültige Signatur allein bedeutet nur „signiert mit dem im Paket eingebetteten Schlüssel“ |
| **Zeit** | `local` (selbst behauptet) **oder** OpenTimestamps (in Bitcoin verankert) | Lokal: eine Zeit, die das Werkzeug behauptet. OTS: Der Inhalt existierte *spätestens* zu einem Bitcoin-Block | Lokale Zeit beweist einem Dritten nichts; OTS beweist eine *Obergrenze* der Zeit, nicht den genauen Moment |

Wir weigern uns, irgendetwas davon vorzutäuschen. Lässt sich kein echter Zeitstempel eines Dritten
beschaffen (offline, oder die Bibliothek ist nicht installiert), löst der Code einen Fehler aus,
statt eine Zeit zu erfinden — der Fehlermodus, den die Charta des Projekts verbietet
(PRODUCT_SYNTHESIS §3.7).

---

### Komponenten

#### 1. Signierte Beweispakete — `src/reporting/evidence.py`
Ein Export ausgewählter Artikel zu einem Zeitpunkt, jeder mit seiner Herkunft und einem
Inhalts-Hash, zusammengebunden durch eine **domänengetrennte Merkle-Wurzel** und eine
**Ed25519-Signatur**. Offline prüfen mit `scripts/verify_evidence.py <bundle.json> [signer_pubkey]`.
Bereitgestellt unter `POST /api/reports/evidence` und `/api/reports/evidence/verify`.

Der Signaturschlüssel liegt in `keys/evidence_ed25519.pem` in Ihrem Datenordner. Bei einem
verschlüsselten Speicher wird er mit Ihrer Passphrase umhüllt (ein zuvor erzeugter Schlüssel wird
unverändert umhüllt, sobald ein Export ihn zum ersten Mal bei entsperrtem Speicher lädt), sodass
eine Kopie des Datenordners allein nicht in Ihrem Namen signieren kann; ohne Passphrase bleibt er
mit `0600` im Klartext. Hat ein wiederhergestelltes Backup einen Schlüssel mitgebracht, der mit der
Passphrase einer anderen Installation umhüllt ist, melden ein Beweisexport und jedes Backup (ein
Backup signiert sein Manifest mit diesem Schlüssel), dass sie ihn nicht öffnen können, und ersetzen
nichts: Verwenden Sie die Passphrase, mit der er umhüllt wurde, oder verschieben Sie die Datei
beiseite, damit ein neuer Schlüssel erzeugt wird (mit dem alten Schlüssel signierte Pakete lassen
sich weiterhin mit dessen öffentlichem Schlüssel prüfen). Eine verlorene Passphrase bedeutet einen
verlorenen Schlüssel; es gibt keine Wiederherstellung.

#### 2. Hybride Signaturen — `src/custody/signing.py`
Kombiniert **Ed25519** (schnell, klassisch) mit **ML‑DSA** (FIPS 204, Post-Quanten, der
standardisierte Nachfolger von CRYSTALS‑Dilithium). Zwei Regeln machen das ehrlich:

- **Ehrliche Kennzeichnung.** Eine Signatur wird nur dann als `hybrid` gekennzeichnet, wenn
  tatsächlich ein ML‑DSA-Schlüssel verwendet wurde. Ohne installiertes Extra `pqc` erzeugt das
  Signieren eine `ed25519`-Signatur und sagt das auch — es behauptet nie eine Quantenresistenz,
  die es nicht hergestellt hat.
- **Hybrid heißt UND.** Eine `hybrid`-Signatur gilt nur dann als gültig, wenn **beide**
  Bestandteile gültig sind. Einem Prüfer ohne die Post-Quanten-Bibliothek ist die Prüfung der
  ML‑DSA-Hälfte nicht möglich, und er **schlägt daher laut fehl** — er lässt nie stillschweigend
  allein die klassische Hälfte gelten. (Ein Verfahren, das *eine der beiden* Signaturen
  akzeptiert, ist wertlos, sobald die klassische gebrochen ist.)

Private Schlüssel werden im Ruhezustand mit AES‑256‑GCM unter einem per scrypt abgeleiteten
Schlüssel verschlüsselt, wenn die App eine Passphrase hat (`OO_KEY_PASSPHRASE`, sonst die
Passphrase der Datenbank); andernfalls werden sie mit `0600` im Klartext geschrieben, und die
Schutzstufe wird wahrheitsgemäß als `plaintext-0600` gemeldet.

#### 3. Verwahrungsprotokoll — `src/custody/log.py`
Ein **nur anhängbares** SQLite-Register. Jede Aktion (`ingest`, `access`, `export`,
`redact`, …) wird zu einem Eintrag, der mit seinem Vorgänger **per Hash verkettet**,
**signiert** und **mit Zeitstempel versehen** ist. `verify()` prüft erneut Reihenfolge,
Kettenglieder, Hashes pro Eintrag, Signaturen und Zeitstempel-Digests. Exporte lassen sich
offline prüfen:

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
```

REST: `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`,
`GET /api/custody/export`, `POST /api/custody/verify`.

Optionale automatische Protokollierung bei der Aufnahme: setzen Sie `OO_CUSTODY_ON_INGEST=1`
(`Config.custody_on_ingest`). Sie ist **standardmäßig aus** — eine ausdrückliche
Beweisentscheidung mit geringen Signaturkosten pro Artikel, kein stilles, immer aktives
Verhalten. Sie schlägt offen fehl: Ein Verwahrungsfehler bricht die Aufnahme nie ab.

#### 4. Verankerung — `src/custody/anchor.py`
Veröffentlicht eine Merkle-Wurzel bei einem externen Zeugen, damit ihr Existenzzeitpunkt nicht
auf Ihrer eigenen Uhr oder Ihrem eigenen Schlüssel beruht:

- **`local`** (Standard, offline): erfasst die Wurzel in einem lokalen Ankerbuch. Beweist nur,
  dass *dieses Werkzeug* sie gespeichert hat — interne Prüfung, kein Beweis gegenüber Dritten.
- **`opentimestamps`** (Netzwerk): verankert einen undurchsichtigen Hash in Bitcoin. Keine
  Wallet, keine Gebühr, unabhängig überprüfbar. Fällt offline auf einen ausdrücklichen Fehler
  *nicht verfügbar* zurück — nie auf eine gefälschte Quittung.
- **`ethereum` / `ipfs` / `arweave`**: deklariert, aber **nicht implementiert**. Sie verweigern
  mit einem klaren Fehler, statt als Platzhalter ausgeliefert zu werden, deren `verify()` immer
  false zurückgibt.

REST: `POST /api/custody/anchor`, `GET /api/custody/providers`.

#### 5. Einstellungen — `src/custody/settings.py` (in der Oberfläche konfigurierbar)
Das Verwahrungsverhalten wird zur Laufzeit von der bedienenden Person gesteuert, nicht nur über
Umgebungsvariablen/YAML. Die Einstellungen werden in `custody_settings.json` im Datenverzeichnis
gespeichert und im Bereich **Verwahrungskette** der Weboberfläche (oder über die REST-API) bearbeitet:

- **`pqc_enabled`** — hybrides Signieren mit Ed25519 + ML‑DSA anfordern.
- **`anchoring_mode`** — `local` (Standard) oder `opentimestamps`.
- **`auto_log_on_ingest`** — bei jeder erfolgreichen Aufnahme einen signierten Eintrag anhängen
  (übernimmt standardmäßig den bisherigen Schalter `OO_CUSTODY_ON_INGEST`, bis eine Einstellung
  gespeichert wird).
- **`default_actor`** — optionale Akteursbezeichnung für automatisch protokollierte Einträge.

**Ehrlichkeitsinvariante.** Ein Schalter ist eine *Anforderung*, keine Garantie. API und
Oberfläche zeigen immer den **tatsächlichen** Zustand (Einstellung **UND** Verfügbarkeit der
Bibliothek): Ist PQC aktiviert, aber `pqcrypto` nicht installiert, bleibt der Signierer bei
Ed25519 allein, und die Oberfläche sagt das — sie zeigt nie ein grünes „hybrid“-Licht, das sie
nicht belegen kann. Dasselbe gilt für OpenTimestamps ohne das Extra `timestamping`.

REST: `GET /api/custody/settings`, `PUT /api/custody/settings`.

Ein typischer Ablauf für „maximalen Beweis“:

```
export evidence bundle  ->  take its merkle_root  ->  POST /api/custody/anchor
  (POST /api/reports/evidence)                         {merkle_root, "opentimestamps"}
```

---

### ⚠️ Privatsphäre: Verankerung kann Sie deanonymisieren

Die Verankerung in einer **öffentlichen** Blockchain ist eine **dauerhafte Veröffentlichung**
eines Hashs und eines Zeitstempels. Der Hash selbst verrät nichts über den Inhalt, aber der
*Vorgang* des Einreichens verrät den Betreibern der Kalender-/RPC-Server Ihre IP-Adresse und den
Zeitpunkt, und eine mit Geld gefüllte On-Chain-Wallet hinterlässt eine Geldspur. Für alle, die
Anonymität brauchen:

- Bevorzugen Sie **lokal + OpenTimestamps** gegenüber Wallets auf öffentlichen Blockchains.
- Leiten Sie OpenTimestamps-Einreichungen über **Tor** (z. B. `HTTPS_PROXY`).
- Oder verzichten Sie ganz auf externe Verankerung und verlassen Sie sich auf lokale
  Zeitstempel + Signaturen.

Vertraulichkeit und Verankerung in öffentlichen Blockchains stehen in Spannung zueinander. Die
Standardkonfiguration (lokaler Offline-Anbieter, selbst behauptete lokale Zeit) gibt nichts preis.

---

### Was wir bewusst **nicht** gebaut haben

- **Keine gefälschte RFC‑3161-TSA.** `datetime.now()` zurückzugeben und es einen
  „vertrauenswürdigen Zeitstempel“ zu nennen, ist Theater. Verwenden Sie OpenTimestamps (echt)
  oder lokal (ehrlich gekennzeichnet).
- **Keine hybriden Signaturen mit ODER-Semantik.** Siehe „Hybrid heißt UND“ oben.
- **Kein immer laufender Integritätsdienst im Hintergrund, kein unverschlüsselter
  Schlüsselspeicher, der als „verschlüsselt“ beworben wird.** Schlüssel sagen, wie sie geschützt
  sind; geprüft wird auf Anforderung.

### Bedrohungsmodell in einem Absatz

Das Werkzeug läuft als **einzelner lokaler Nutzer, nur über Loopback, unter Qubes** (siehe
`docs/SECURITY.md`). Das Verwahrungssystem schützt die *Integrität und Herkunft Ihrer eigenen
Beweiskette* gegen spätere Manipulation und gegen den Vorwurf „Sie haben das erfunden“. Es schützt
nicht — und kann von sich aus nicht schützen — die Identität einer menschlichen Quelle, und naive
Verankerung in öffentlichen Blockchains kann der Anonymität aktiv *schaden* — deshalb ist die
Verankerung optional, standardmäßig offline und wird mit der obigen Warnung ausgeliefert.


---

# Was in 0.0.8 ausgeliefert wurde — der Roadmap-Zyklus

> **Historische Momentaufnahme, siehe CLAUDE.md.** Dies ist eine Aufzeichnung des 0.0.8-Zyklus zu
> einem bestimmten Zeitpunkt; sie wird für spätere Versionen nicht gepflegt. `docs/ledger/OPEN_QUEUE.md` + `docs/ledger/`
> sind die aktuellen maßgeblichen Quellen dafür, was seitdem ausgeliefert wurde.

Alles Folgende ist jetzt verfügbar, vollständig über die Browser-Oberfläche. Jede Funktion nennt
ihre ehrliche Grenze dort, wo sie erscheint.

## Untersuchungsrezepte (Start) und das Dashboard `/investigate`

Das Briefing auf der Startseite beobachtet Ihr eigenes Korpus jetzt auf **Raum-Zeit-Signale** und
erzeugt Karten — alles lokal berechnet, nie aus dem Netzwerk:

- **Fällige Versprechen** — ein Artikel nannte ein Datum, das zum Zeitpunkt seiner Veröffentlichung
  *in der Zukunft* lag; dieses Datum ist nun gekommen. Zeit zu fragen, was tatsächlich geschehen ist.
- **Edit-War-Ausbruch** — eine Wikipedia-Seite, die Sie verfolgen, wird mit ≥3× ihrer eigenen
  jüngsten wöchentlichen Rate bearbeitet; ihre öffentliche Darstellung ist in Bewegung.
- **Region verstummt** — ein Land, das zuverlässig Artikel für Sie geliefert hat, hat (fast)
  aufgehört. Der Vorbehalt ist eingebaut: Das misst *Ihr Korpus*, nicht die Region — ein toter
  Feed sieht genauso aus wie echte Stille, prüfen Sie also zuerst die Quellen.
- **Quellenkandidaten warten auf Prüfung** (Source candidates await review) — siehe
  *Entdeckte Kandidaten* weiter unten.

Karten mit einer Schaltfläche **„Untersuchung öffnen ↗“** öffnen ein eigenes Dashboard **in einem
neuen Browser-Tab** (die Haupt-App arbeitet weiter; öffnen Sie mehrere gleichzeitig). Das
Dashboard stellt die zugehörigen Bereiche automatisch zusammen — den Originalartikel mit seinen
Herkunftsausschnitten, eine vorausgefüllte Folgesuche, die gespeicherte Revisionsliste, den
Abdeckungskontext —, trägt den Vorbehalt der Karte wörtlich ganz oben und endet mit einer Leiste
**„Tiefer einsteigen“**, in der jeder Vorschlag eine normale Aktion mit sichtbaren Parametern ist.
Der gesamte Zustand der Seite steckt in ihrer URL: Setzen Sie ein Lesezeichen, öffnen Sie sie
erneut, teilen Sie sie zwischen Ihren eigenen Rechnern.

Einzelne Rezepte schalten Sie unter **Einstellungen → Karten** ab, wo sie jetzt neben jeder anderen
Spur stehen, die diese App erzeugen kann, nach Familie gruppiert — derselbe Schalter, für alle
angewendet.

## Methodenanhang

Die Schaltfläche **Methodenanhang** (auf der Suchseite und in der Aktionsleiste des
Analysefensters) lädt ein Markdown-Dokument herunter, das festhält, *wie* Ihre aktuelle Auswahl
zustande kam: die App-Version, die wörtliche boolesche Abfrage, Trefferzahlen, Korpuskontext und
eine Herkunftszeile pro Artikel (Titel · Quelle · veröffentlicht · URL · Inhalts-SHA-256). Er
erfasst nur die Auswahl und behauptet keine Schlussfolgerung — die analytischen Aussagen bleiben
Ihre eigenen, überprüfbar anhand der Zeilen. Gebaut für Faktencheck-Urteile und Peer-Review;
kombinieren Sie ihn mit einem signierten Beweispaket (Beweise & Verwahrung), wenn Sie Dokument +
Beweis zusammen brauchen.

## Ergebnisse synthetisieren

**Ergebnisse synthetisieren** (auf der Suchseite und im Analysefenster) öffnet ein Fenster in zwei
Schritten: Es holt einen Kandidatenpool, zeigt Ihnen die gefundenen Artikel mit ihren Metadaten und
lässt Sie **bis zu 20 Mitglieder auswählen** (die ersten ≤20 sind vorab angehakt); danach führt es
EINEN Durchlauf des lokalen Modells über genau diese aus und liefert gemeinsame Fakten,
Streitpunkte und offene Fragen, wobei die Mitgliedsartikel per Nummer zitiert werden. Das Ergebnis
enthält das vollständige synthetisierte Korpus mit den Metadaten und Leser-Links jedes Artikels
sowie **Export**-Optionen (Kopieren, .md oder als eigenständige Seite öffnen). Die Synthese wird
mit Herkunftsangaben zu Modell + Prompt-Version pro Mitgliedsartikel gespeichert, und der Vorbehalt
reist mit: Dies ist eine Lesehilfe ausschließlich über die aufgeführten Mitglieder — nie ein
Urteil. Erfordert Ollama, wie die anderen LLM-Funktionen; ohne Ollama erhalten Sie eine ehrliche
Meldung „nicht erreichbar“.

## Versionierte Exporte und der Zitationsgraph

- Maschinenlesbare Exporte tragen jetzt einen stabilen Vertrag (`oo-export-1`): JSON-Exporte sind
  selbstbeschreibende Umschläge (Schema, App-Version, Erstellungszeitpunkt, die exakte Abfrage,
  Anzahl); CSV-Spalten behalten ihre Reihenfolge, mit derselben Herkunft wie die HTTP-Header
  `X-OO-*`. Die letzte Spalte, **Fetched From Host** (`fetched_host` in JSON), ist der Host, von
  dem die Seite nach ihren Weiterleitungen tatsächlich abgerufen wurde; sie ist leer für einen
  Artikel, der gespeichert wurde, bevor dies erfasst wurde.
- Der **Zitationsgraph** — welche externen Domains Ihre gespeicherten Artikel zitieren, nur Zählungen,
  keine abgeleitete Glaubwürdigkeit — lässt sich als GraphML (`/api/links/export.graphml`) für
  Gephi/yEd/NetworkX oder als JSON exportieren.

## Laufprotokoll des Planers und der Export in einen lokalen Ordner (Sammeln)

Jeder Lauf des Planers — erfolgreich oder fehlgeschlagen — hängt eine Zeile an ein lokales,
prüfbares Laufprotokoll an (`scheduler_runs.jsonl`), sodass das Korpus beantworten kann: „Was lief,
während ich weg war?“. Optional können Sie in der Planer-Karte unter Sammeln einen Pfad für
**Export in lokalen Ordner** festlegen: Jeder Lauf schreibt dann die neuen Artikel seit dem letzten
Lauf als Umschlag-JSON-Datei in diesen lokalen Ordner, den Ihre eigene Verarbeitungskette
beobachten kann. Leer = aus (Standard); nichts Neues = keine Datei.

## Entdeckte Kandidaten (Quellen)

Die App schlägt jetzt selbst Quellen vor — **nur offline**: Domains, die Ihre gespeicherten Artikel
wiederholt zitieren, und Medien aus dem mitgelieferten Katalog für Länder, die Ihr Korpus nur dünn
abdeckt. Vorschläge werden bereitgestellt, nie umgesetzt: Jeder trägt seine Belege im Bereich
**Entdeckte Kandidaten** (Einstellungen → Erweitert → Quellen), Läufe sind durch das
Entdeckungsbudget des Planers begrenzt und werden im Laufprotokoll erfasst, und eine Karte auf der
Startseite sagt Ihnen, wann Kandidaten auf Prüfung warten. **Übernehmen** (Promote) legt eine
*deaktivierte* Quelle an, die Sie noch selbst aktivieren müssen; **Ausblenden** wird gemerkt und
nie wieder vorgeschlagen. Die auf DuckDuckGo gestützte Themensuche bleibt davon getrennt,
**standardmäßig aus** und hinter Einstellungen → Erweitert → Sicherheit geschützt (siehe unten).

## Externe Themensuche ist optional (Einstellungen → Erweitert → Sicherheit)

Die *Themensuche* ist die eine Funktion, die **eine Freitext-Suchanfrage an eine Suchmaschine
sendet**: Sie sendet Ihre Themenanfrage an DuckDuckGo. (Andere Online-Aktionen — Sammeln, Markt-/
Statistikabrufe, Ollama-Downloads, OpenTimestamps — erfordern ebenfalls jeweils Zustimmung und sind
benannt; dies ist die eine, die eine von Ihnen eingetippte Anfrage überträgt.) Sie ist
**standardmäßig deaktiviert** und verweigert mit einer ehrlichen
Meldung, bis Sie **Einstellungen → Erweitert → Sicherheit → Externe Themensuche** aktivieren („Ihre
Suchanfrage verlässt diesen Rechner“). Das Finden von RSS-Feeds für Quellen, die Sie selbst
hinzugefügt haben, bleibt auf dem lokalen ethischen Abrufweg und ist nicht betroffen.

## Sprachen

Die Oberfläche wird jetzt mit **vollständigen Übersetzungen in 12 Sprachen** ausgeliefert (English,
العربية, বাংলা, Deutsch, Español, Français, हिन्दी, Bahasa Indonesia, 日本語, Português, Русский, 中文),
einschließlich Rechts-nach-links-Layout für Arabisch. Wählen Sie Ihre Sprache in der
Sprachauswahl; die Übersetzungen sind maschinell erstellte erste Entwürfe — Korrekturen sind
willkommene Beiträge (siehe `docs/ARCHITECTURE.md` → Internationalisation).
