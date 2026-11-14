<!-- de: AI-drafted translation of docs/QUICKSTART.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 17 of 17 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# Schnellstart — die App ausführen

Dies ist der **vertrauenswürdige Kern** (die App ist ein ehrliches **Alpha** — `v0.5.0`, der
`0.5`-Zyklus „Schreibtisch des Ermittlers“, getaggt am 2026-10-26; die laufende App meldet ihre genaue
Version): eine Quelle hinzufügen → sie ethisch abrufen → mit Herkunftsnachweis speichern →
boolesche Volltextsuche → exportieren. Lokal zuerst, nur Loopback, keine Konten.

---

## 0. Der einfache Weg — ein Befehl, danach per Doppelklick starten

Wenn Sie die App einfach nur nutzen möchten (danach sind keine Kommandozeilenkenntnisse nötig):

**Linux / macOS** — in einem Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

**Windows 11** — in PowerShell. Laden Sie es herunter und führen Sie es *danach* aus:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1
```

Windows Defender stellt die Datei unter Umständen trotzdem unter Quarantäne — sie ist unsigniert und neu. Das ist ein
Fehlalarm; [§C](#c-unter-windows-11-powershell) erklärt genau, warum, und bietet Ihnen einen
Weg ohne Skript, den nichts verschlucken kann.

Die Windows-Unterstützung ist enger gefasst als die für Linux, und der Unterschied wird in
[§C](#c-unter-windows-11-powershell) offen benannt — lesen Sie ihn, bevor Sie sich darauf verlassen.

> **Erst prüfen, dann vertrauen.** Wenn Sie ein Skript per Pipe an Ihre Shell übergeben, wird Code auf Ihrem
> Rechner ausgeführt. Beide sind bewusst klein gehalten — lesen Sie sie vorher, wenn Sie möchten
> ([scripts/bootstrap.sh](../scripts/bootstrap.sh), [install.ps1](../install.ps1)).
> Sie prüfen, ob git + Python 3.13 vorhanden sind, klonen dieses Repository nach `~/open-omniscience`
> (`%USERPROFILE%\Open-Omniscience` unter Windows) und übergeben an den Installer
> im Repository. Sie können genauso gut selbst klonen und `./install.sh` / `install.ps1` ausführen.

`install.sh` arbeitet **ohne Rückfragen** — es gibt **kein Komponentenmenü**. Ein Befehl installiert
die sinnvolle Standardauswahl:

| Standardmäßig installiert | Was Sie erhalten |
|----------------------|--------------|
| **Kern** *(immer)* | abrufen · mit Herkunftsnachweis speichern · boolesche Suche · exportieren |
| **Analyse** | Schlüsselwörter · Vergleich der Darstellung (Framing) · Stimmung |
| **Komprimierung** | schnellere Speicherung des Korpus auf der Festplatte |

Die Einrichtung eines lokalen LLM / von Ollama ist **nicht** Teil des Installers — sie findet vollständig im
Tab **Einstellungen → KI** der App statt (siehe §E). Die installierte Auswahl überschreiben Sie mit der
Umgebungsvariablen `OO_COMPONENTS="…"` (z. B. `OO_COMPONENTS="analysis,nlp"`); ein erneuter Aufruf von
`./install.sh` ist idempotent und installiert nur, was fehlt.

**Danach startet sie automatisch.** Der Installer legt einen **Open Omniscience**-Starter an (Anwendungsmenü
+ Schreibtisch) und öffnet die App in Ihrem Browser. Um sie später wieder zu starten:

- öffnen Sie Ihr Anwendungsmenü und suchen Sie nach **Open Omniscience**, **oder**
- doppelklicken Sie auf das Symbol **Open Omniscience** auf Ihrem **Schreibtisch**.

Ein kleines Terminalfenster erscheint, die App startet, und Ihr Browser öffnet
**http://127.0.0.1:8000**. **Schließen Sie dieses Fenster (oder verwenden Sie die Ein/Aus- bzw. Beenden-Schaltfläche
in der oberen Leiste), um die App zu beenden.** (Unter macOS ist der Starter `Open Omniscience.command` auf Ihrem
Schreibtisch; unter Windows ist es eine Verknüpfung auf dem Desktop und im Startmenü, die `install.ps1` anlegt.)

**Erster Start.** Bei einer frischen Installation führt Sie die App durch eine kurze, einmalige Einrichtung,
*bevor* die eigentliche Oberfläche erscheint: **Sprache wählen → die rechtlichen Bedingungen lesen und annehmen**
(eine Ablehnung **deinstalliert** die App, nach einer eingetippten Bestätigung) **→ die Passphrase für Ihren Korpus
festlegen**. Der Korpus ist **standardmäßig im Ruhezustand verschlüsselt** (SQLCipher 4), und es gibt
**keine Wiederherstellung** einer verlorenen Passphrase (eine verlorene Passphrase kostet die Zeit für das erneute Sammeln — der
Korpus wird aus dem Web neu aufgebaut). Die App startet dann **offline (Flugmodus)**;
der Wechsel in den Online-Betrieb führt über **ein Zustimmungs-Popup**, das die Aktion benennt und Ihre lokalen
Schnittstellen-IPs anzeigt, bevor irgendeine Anfrage hinausgeht.

Lieber im Terminal? `cd ~/open-omniscience && ./scripts/launch.sh` bewirkt dasselbe.

**Später prüfen oder entfernen:**
```bash
./install.sh --check        # health report: Python, data dir, database, LLM, launcher
#   (same as: open-omniscience doctor)
./install.sh --uninstall    # remove the virtualenv + launcher; your data is kept
                            #   (it asks separately, defaulting to NO, before deleting data)
```

---

## A. Auf einer Debian-AppVM unter Qubes OS (das Zielsystem)

Qubes setzt das Root-Dateisystem einer AppVM bei jedem Start zurück; nur `/home` (sowie
`/usr/local`, `/rw`) bleiben erhalten. Systempakete gehören daher in die **TemplateVM**, und die
App + virtuelle Umgebung + Datenbank liegen unter `/home` in der **AppVM**.

**1. In der TemplateVM (einmalig):**
```bash
sudo ./install.sh --template      # installs python3.13, venv, git, sqlite3, ...
```
Fahren Sie die TemplateVM herunter und **starten Sie dann die AppVM neu**, damit die Pakete sichtbar sind.

**2. In der AppVM (als Ihr Benutzer, ohne sudo):**
```bash
./install.sh                      # promptless: Core + Analysis + Compression, then auto-launches
# Qubes AppVM (unattended, creates the launcher, no prompts): Core + Analysis + Compression
./install.sh --appvm
```

**3. Ausführen (bindet nur an 127.0.0.1):**
Doppelklicken Sie auf den Starter **Open Omniscience** (Anwendungsmenü / Schreibtisch), oder:
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # starts the app + opens the browser
```
Öffnen Sie **http://127.0.0.1:8000** im Browser der AppVM.

Der Server lauscht niemals außerhalb von Loopback. Um nach einem Lauf vollständig offline zu gehen, trennen Sie die
NetVM der AppVM — die Oberfläche hat keine externen Abhängigkeiten und arbeitet mit den gespeicherten Daten weiter.

---

## B. Lokaler Entwicklungslauf (jedes Linux mit Python 3.13)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # full test suite
open-omniscience                   # serve at http://127.0.0.1:8000
```

Nützliche Umgebungsvariablen: `OO_DATA_DIR` (wo die SQLite-Datenbank + die Daten liegen), `OO_HOST`/`OO_PORT`,
`OO_FETCH_MIN_INTERVAL` (Höflichkeitsverzögerung pro Host, in Sekunden).

### Unter Tails

Debian/Ubuntu/Tails liefern `venv`/`ensurepip` aus der Standardbibliothek in einem **separaten apt-Paket** aus, daher
schlägt `python3 -m venv` fehl, bis dieses installiert ist. `install.sh` installiert es inzwischen
**automatisch** — unter Tails braucht das ein **Administrationspasswort** (legen Sie es im
Begrüßungsbildschirm fest; standardmäßig ist es aus) und eine funktionierende **Tor-Verbindung** (apt lädt über
Tor herunter). Mit `OO_NO_APT=1` verzichten Sie darauf, wenn Sie apt lieber selbst ausführen.

Zwei ehrliche Vorbehalte, die speziell Tails betreffen:

- **Python-Version.** Tails ist Debian 12 → **Python 3.11**, die App zielt aber auf **3.13**.
  Sie müssen einen 3.13-Interpreter zur Verfügung haben und den Installer darauf verweisen
  (`OO_PYTHON=python3.13 ./install.sh`); 3.13 und das zugehörige Paket `python3.13-venv` sind **nicht**
  in den Standard-Repositorys von Tails enthalten.
- **Amnesie.** Alles, was per apt installiert wurde — und die gesamte `.venv` — **geht beim Neustart verloren**, sofern
  es nicht im beständigen Speicherbereich liegt: Fügen Sie das venv-Paket über **Beständiger Speicherbereich (Persistent Storage) → Zusätzliche
  Software (Additional Software)** hinzu, und legen Sie den Checkout + `OO_DATA_DIR` auf den beständigen Datenträger.

### Eine bestehende Datenbank aktualisieren

Frische Installationen bauen das Schema automatisch auf (`init_db()`), und die Datenbank wird
mit dem aktuellen Migrations-Ausgangsstand gekennzeichnet. Wenn eine künftige Version das
Schema ändert, aktualisieren Sie eine bestehende Datenbank mit:
```bash
alembic upgrade head
```
`alembic check` meldet, ob Modelle und Migrationen übereinstimmen (die CI überwacht das).

---

## C. Unter Windows 11 (PowerShell)

**Ehrlicher Stand der Unterstützung — lesen Sie dies zuerst.** Jeder CI-Lauf belegt drei Dinge auf
`windows-latest`: die Installation der Abhängigkeiten, den **Startcheck** (die gesamte App lässt sich importieren)
und die **SQLCipher-Verschlüsselung im Ruhezustand** — Letzteres in einer *blockierenden* Spur, die
Verschlüsselung ist also keine Vermutung. Darüber hinaus ist nichts belegt. Die **pytest-Spur unter Windows
bleibt hängen** (kürzlich abgeschlossene Läufe hingen 3h21m bzw. ~6h in `pytest`, gegenüber 18 Minuten
unter macOS), und **niemand hat die Oberfläche unter Windows durchgeklickt**. Also: Rechnen Sie damit, dass Installation
und Start funktionieren, betrachten Sie alles nach dem Start als ungeprüft, und melden Sie bitte, was
nicht funktioniert. Linux bleibt das Kriterium für Veröffentlichungen.

### 1. Installieren

Öffnen Sie **PowerShell** (Administratorrechte sind nicht nötig, außer Python selbst muss
installiert werden). Laden Sie den Installer herunter, lesen Sie ihn, wenn Sie möchten, und führen Sie ihn dann aus:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
notepad $env:TEMP\oo-install.ps1                                     # optional: see what you are about to run
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1 -Extras analysis
```

Er installiert Git und Python 3.13 über `winget` nur, wenn sie fehlen, klont nach
`%USERPROFILE%\Open-Omniscience`, erstellt eine `.venv` und prüft das Ergebnis, indem er
die echte App importiert. Lassen Sie den Schalter `-Extras` weg, um die umfangreichere Standardauswahl zu erhalten, oder siehe
[Installer-Optionen](#installer-optionen).

Bereits geklont? Führen Sie ihn an Ort und Stelle aus — er erkennt seinen eigenen Checkout und überspringt das Klonen:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> **Warum nicht eine einzige Zeile `irm … | iex`?** Weil das Abrufen von entferntem Code und sein Ausführen
> direkt aus dem Arbeitsspeicher der häufigste Weg ist, auf dem Windows-Schadsoftware ausgeliefert wird, sodass
> Defender dieses Muster als feindselig bewertet, ganz gleich, was das Skript enthält. Die Datei zuerst
> zu speichern wird seltener blockiert und ist zugleich ehrlicher — Sie können das Ding lesen,
> bevor es läuft.

### 2. Wenn Windows Defender den Installer unter Quarantäne stellt

Er löscht `install.ps1` womöglich sofort. Das ist ein **Fehlalarm**, und Sie sollten uns das nicht
einfach glauben — hier steht genau, warum es passiert, damit Sie selbst urteilen können:

- Die Datei ist **unsigniert und neu**, daher hat die Cloud-Reputation von Defender sie noch nie gesehen.
  Unbekannt + unsigniert reicht für sich genommen schon aus, um die Heuristiken des maschinellen Lernens auszulösen; der
  Name der Erkennung endet typischerweise auf `!ml`.
- Ihre **Gestalt** ist die eines Installers: Sie ruft einen Paketmanager auf, liest `PATH` erneut aus
  der Registry, legt Startmenü-Verknüpfungen an, und ihr `-Uninstall`-Pfad löscht
  Verzeichnisse. Dropper tun genau dieselben Dinge. Der Klassifikator bewertet die Gestalt, nicht die Absicht.

Was sie *nicht* enthält — und was Sie in ~500 gut lesbaren Zeilen selbst prüfen können: kein
`Invoke-Expression`, keine codierte oder verschleierte Nutzlast, kein `WebClient`, keine versteckten
Fenster und keinen Download außer aus diesem Repository.

Drei Wege nach vorn, der beste zuerst:

1. **Nutzen Sie den Weg ohne Skript** — [Manuelle Installation](#manuelle-installation-ohne-skript) weiter unten.
   Dieselben Befehle, die der Installer ausführt, keine Datei, die unter Quarantäne gestellt werden könnte. Das funktioniert immer.
2. **Melden Sie den Fehlalarm** an Microsoft unter
   <https://www.microsoft.com/en-us/wdsi/filesubmission> (wählen Sie *Software developer*).
   Das wird meist innerhalb von ein oder zwei Tagen bearbeitet und behebt das Problem für alle, die
   nach Ihnen installieren — nicht nur für Sie.
3. **Schließen Sie den Ordner aus** (Windows-Sicherheit → Viren- & Bedrohungsschutz → Einstellungen
   verwalten → Ausschlüsse). Kennen Sie den Preis, bevor Sie das tun: Ein Ausschluss bewirkt, dass Defender
   diesen Ordner *überhaupt nicht* mehr scannt, für alles und auf unbestimmte Zeit — nicht nur
   für diese eine Datei. Ihr Rechner, Ihre Entscheidung; wir werden nicht so tun, als koste das nichts.

Die ehrliche Lösung auf unserer Seite ist Code-Signierung, die wir noch nicht haben.

### 3. Ausführen

Der Installer legt eine Verknüpfung **Open Omniscience** auf Ihrem **Desktop** und im
**Startmenü** an. Doppelklicken Sie darauf: Ein Terminalfenster erscheint, und Ihr Browser öffnet
**http://127.0.0.1:8000**, sobald die App tatsächlich antwortet. Schließen Sie dieses Fenster (oder verwenden Sie die
Ein/Aus-Schaltfläche der App), um sie zu beenden.

Stattdessen aus einem Terminal: `scripts\launch.cmd`.

### 4. Erster Start

Derselbe einmalige Ablauf wie auf jeder Plattform: **Sprache wählen → die rechtlichen Bedingungen lesen und
annehmen → die Passphrase für Ihren Korpus festlegen**. Der Korpus ist **standardmäßig im Ruhezustand
verschlüsselt**, und es gibt **keine Wiederherstellung** einer verlorenen Passphrase. Die App startet dann
**offline (Flugmodus)**; der Wechsel in den Online-Betrieb führt über **ein Zustimmungs-Popup**.

### Installer-Optionen

| Schalter | Was er bewirkt |
|------|--------------|
| *(keiner)* | Kern + `analysis,compression,columnar`, dann Prüfung und Anlegen der Starter |
| `-Path <dir>` | An einem anderen Ort als `%USERPROFILE%\Open-Omniscience` installieren |
| `-Extras "analysis"` | Die pip-Extras wählen (`""` nur für den Kern) |
| `-Ref <branch>` | Einen bestimmten Branch oder Tag klonen |
| `-NoPython` | Git/Python niemals automatisch installieren; stattdessen mit Anleitung abbrechen |
| `-NoLauncher` | Die Verknüpfungen auf dem Desktop / im Startmenü überspringen |
| `-Check` | Zustandsbericht (wie `open-omniscience doctor`) |
| `-Uninstall` | `.venv` + Starter entfernen; Daten bleiben erhalten, sofern nicht gesondert bestätigt |
| `-Yes` | Bei Rückfragen „Ja“ annehmen (unbeaufsichtigt) |

Nur `analysis` ist unter Windows durch die CI belegt. Wenn sich die umfangreichere Standardauswahl nicht
installieren lässt, **fällt das Skript auf `analysis` zurück und sagt das auch**, statt
stillschweigend zu scheitern oder so zu tun, als wären die Extras angekommen.

### Manuelle Installation (ohne Skript)

```powershell
# 1. Prerequisites -- skip either line if you already have it
winget install --id Git.Git -e --source winget
winget install --id Python.Python.3.13 -e --source winget --scope user

# 2. Find the interpreter. winget frequently installs Python WITHOUT adding it to
#    PATH, so `python` and `py` can still resolve to nothing on a freshly restarted
#    machine. This reads the record the installer itself writes (PEP 514) -- the same
#    one py.exe uses -- so it answers whatever PATH says:
Get-ChildItem 'HKCU:\SOFTWARE\Python','HKLM:\SOFTWARE\Python' -Recurse -ErrorAction SilentlyContinue |
  Where-Object PSChildName -eq 'InstallPath' |
  ForEach-Object { (Get-ItemProperty $_.PSPath).'(default)' }

$py = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"   # or whatever that printed

# 3. Clone
git clone --depth 1 https://github.com/ideotion/Open-Omniscience.git $HOME\Open-Omniscience
cd $HOME\Open-Omniscience

# 4. Virtual environment. Everything is called by full path on purpose: activating a
#    venv needs Activate.ps1, which the default execution policy blocks.
& $py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[analysis]"

# 5. Verify -- the exact check CI's Windows lane runs
.\.venv\Scripts\python.exe -c "from src.api.main import app; print(sum(1 for _ in app.routes))"

# 6. Run
.\.venv\Scripts\open-omniscience.exe
```

### Hinweise speziell für Windows

- **Ausführungsrichtlinie.** Die Standardrichtlinie blockiert `.\.venv\Scripts\Activate.ps1`.
  Nichts hier braucht es: Rufen Sie `.venv\Scripts\python.exe` über den Pfad auf, und das ganze Problem
  verschwindet. `-ExecutionPolicy Bypass` auf der Befehlszeile deckt den Installer selbst ab.
- **Das `python`, das den Microsoft Store öffnet.** Ein frisches Windows 11 bringt einen
  Ausführungsalias-Platzhalter namens `python.exe` mit, der den Store startet, statt
  Code auszuführen. Der Installer ignoriert ihn (ein Platzhalter gibt keine Version aus) und verwendet den Starter `py -3.13`.
  Wenn Sie manuell installieren, ziehen Sie `py -3.13` dem Aufruf `python` vor.
- **Wo Ihre Daten liegen.** Da es sich um einen Quellcode-Checkout handelt, landen der Korpus, die Signierschlüssel
  und die Einstellungen in **`<repo>\data`** — nicht in `%APPDATA%`. Setzen Sie `OO_DATA_DIR`, um sie
  auf ein anderes Laufwerk zu legen.
- **Ordnerberechtigungen.** Unter Linux ist das Datenverzeichnis auf Ihren Benutzer beschränkt
  (`chmod 0700`); dieser Aufruf bewirkt unter Windows nichts, sodass der Ordner gewöhnliche
  Windows-ACLs erbt. Auf einem gemeinsam genutzten PC schränken Sie `<repo>\data` selbst ein. Die Korpus-Datenbank
  selbst ist in jedem Fall im Ruhezustand verschlüsselt.
- **SmartScreen / Defender.** Nichts hier ist code-signiert, daher behandelt Windows alles davon
  als unbekannt: SmartScreen warnt möglicherweise beim Starter, und Defender stellt
  `install.ps1` womöglich direkt unter Quarantäne — siehe
  [§2](#2-wenn-windows-defender-den-installer-unter-quarantäne-stellt) dazu, was das ist und was Sie
  dagegen tun können. Der Echtzeitschutz verlangsamt außerdem das erste `pip install` spürbar.
- **Port.** Setzen Sie `OO_PORT` vor dem Start, um von 8000 abzuweichen; `scripts\launch.cmd`
  berücksichtigt das.
- **Architektur (x64 / ARM64 / 32-Bit).** Wird vom Installer erkannt und behandelt; hier
  steht, was er dabei entscheidet. Ob `pip install` gelingt, hängt nicht vom
  Rechner ab, sondern davon, welche Wheels für die Plattform des *Interpreters* existieren. Gemessen an
  PyPI am 2026-08-23, für CPython 3.13, über die gesamte Abhängigkeitsmenge dieses Projekts:

  | Interpreter | Wheels |
  |---|---|
  | `win-amd64` | **jede Abhängigkeit.** Die einzige vollständige Architektur. |
  | `win-arm64` | alle bis auf drei — `cryptography` (Kern), `httptools` (Kern, über `uvicorn[standard]`) und `statsmodels` (`analysis`) |
  | `win32` | `cryptography` veröffentlicht überhaupt keine |

  Windows on ARM führt x64-Binärdateien transparent aus, daher ist ein **x64-Interpreter auch unter ARM64 die richtige
  Antwort** — kein Kompromiss, sondern die vollständige Menge. `install.ps1` bevorzugt deshalb
  überall `win-amd64` und beschafft einen, wenn der Rechner keinen hat:
  winget mit benannter Architektur, dann winget im Benutzerbereich, dann das eigenständige x64-CPython der Python
  Software Foundation von nuget.org — geprüft gegen
  den SHA-512, den nuget dafür bestätigt, entpackt nach
  `%LOCALAPPDATA%\Open-Omniscience\python-x64`, ohne Rechteerhöhung, ohne PATH-Änderung
  und ohne Registry-Eintrag. Er liegt bewusst **außerhalb** des Checkouts: Er ist eine Ressource des
  Rechners, überlebt also das Löschen des App-Ordners (die darauf aufgebaute `.venv` würde
  sonst kaputtgehen), und ein zweiter Checkout mit `-Path` verwendet ihn wieder. `-Uninstall` entfernt ihn. Ein abweichender Hash oder eine
  Version, für die nuget keinen Hash bestätigt, wird **abgelehnt**.

  Wenn jede Stufe scheitert, erhalten Sie einen Abbruch mit der Lösung per einem einzigen Download, nicht einen zwanzigminütigen
  Rust-Build, der mit `linker link.exe not found` endet.

  Eine vorhandene `.venv` wird **geprüft, nicht nur gefunden**: Sie behält die Version und die Wheel-Plattform
  des Interpreters, mit dem sie erstellt wurde, daher wird eine von einem früheren Lauf mit einem
  anderen Python übrig gebliebene ersetzt statt wiederverwendet — sonst würde alles oben Beschriebene
  im letzten Schritt stillschweigend zunichtegemacht. Eine passende wird unverändert wiederverwendet. Ein erneuter Aufruf des
  Installers ist daher die Lösung für eine halb fertige Installation; nichts muss von Hand
  gelöscht werden.

  - **Warum eine native ARM64-Installation nicht automatisch aktiviert wird.** Sie würde erfordern, `cryptography`
    auf 46.0.0–46.0.3 festzulegen, die einzige Reihe mit ARM64-Wheels. Diese Version hat
    **13 offene Sicherheitshinweise** (darunter einen zu statisch gelinktem OpenSSL, behoben in
    48.0.1). Diese App signiert Belege; das stillschweigend zu installieren wäre Sicherheitstheater.
    Wenn Ihr Rechner tatsächlich Visual Studio Build Tools **und** eine Rust-Toolchain
    hat, kompiliert `-AllowSourceBuilds` die drei nativ — eine ausdrückliche Entscheidung,
    niemals eine Voreinstellung.
  - **32-Bit-Windows wird nicht unterstützt**, und das ist eine echte Grenze, keine bloße Sperre:
    `cryptography` liefert kein `win32`-Wheel. 64-Bit-Windows ist erforderlich.

---

## D. Der Ablauf von Anfang bis Ende (Oberfläche oder API)

> **Quellen sind vorkonfiguriert.** Beim ersten Start (oder während `install.sh --appvm`)
> werden die kuratierten Kataloge (`configs/sources.yml` mit ~3.200 Medien von öffentlichem Interesse, dazu
> die Kataloge für Märkte, politisches Spektrum und Recht/geistiges Eigentum — **insgesamt ~3.395 eindeutige Domains**)
> automatisch eingespielt — Sie können also sofort mit dem Einlesen beginnen.
> (Diese Zahlen **verschieben sich**, während die Kataloge wachsen; maßgeblich ist, was
> `configs/*.yml` aktuell enthält.) Das erneute Einspielen ist idempotent. Schalten Sie das automatische Einspielen mit
> `OO_AUTOSEED=0` ab; spielen Sie manuell mit `python scripts/seed_sources.py` oder
> `POST /api/sources/seed-defaults` neu ein. Feed-URLs/robots-Regeln ändern sich mit der Zeit; der
> ethische Abrufer lehnt alles ab, was er nicht bestätigen kann, also kürzen/erweitern Sie die Liste passend zu
> Ihrer Recherche.

**In der Oberfläche:** **Gehen Sie einmal online** (der Flugmodus-Schalter → ein Zustimmungs-Popup), und
**die Sammlung läuft von selbst** im Hintergrund — gestaffelt nach Sprachen und Quellen-Tags,
unter Beachtung von robots-Regeln und mit begrenzter Rate. Dann **suchen Sie in Erkunden** (der Tab in der Seitenleiste; Enter in der
Omnibar, obere Leiste oder Ctrl/⌘-K, öffnet Erkunden in einem neuen Browser-Tab) — die Analyse der passenden Artikel erscheint unter den
Ergebnissen, wo Sie filtern, lesen, boolesche Abfragen ausführen und **exportieren** (CSV/JSON, Methodenanhang,
signierte Belege). Sie können weiterhin manuell eine Quelle hinzufügen und einen einzelnen Feed oder eine URL *einlesen (Ingest)*,
und zwar unter **Einstellungen → Erweitert → Erfassung / Quellen**.

**Über die API:**
```bash
# add a source
curl -X POST http://127.0.0.1:8000/api/sources/ -H 'Content-Type: application/json' \
  -d '{"name":"Example News","domain":"example.com","rss_url":"https://example.com/feed.xml"}'

# ingest its feed (ethical: robots.txt respected fail-closed, rate-limited)
curl -X POST http://127.0.0.1:8000/api/sources/1/ingest

# or ingest a single article URL under that source
curl -X POST http://127.0.0.1:8000/api/ingest -H 'Content-Type: application/json' \
  -d '{"source_id":1,"url":"https://example.com/some-article"}'

# Boolean full-text search (AND / OR / NOT, "phrases", parentheses)
curl 'http://127.0.0.1:8000/api/articles?query=(climate OR energy) AND policy NOT opinion'

# export the filtered set
curl 'http://127.0.0.1:8000/api/articles/export?format=csv&query=climate'
```

Das maschinenlesbare API-Schema finden Sie unter **http://127.0.0.1:8000/openapi.json**. Die interaktive Swagger-Seite ist standardmäßig aus (sie lädt Ressourcen von fremden Hosts); wer entwickelt, kann die App mit `OO_API_DOCS=1` starten, um sie unter `/docs` zu erhalten.

---

## E. Analysefunktionen

Alle arbeiten lokal zuerst und melden Ausfälle lautstark (sie erfinden nie etwas). Vollständige Schemata unter `/openapi.json`.

**Lokales LLM (Ollama).** Richten Sie es unter **Einstellungen → KI** ein: ein in die App integrierter,
**prüfsummengesicherter** Ollama-Installer (Linux) sowie eine **Warteschlange für Modell-Downloads** (echter
Fortschritt in Bytes, abbrechbar), eine Auswahl des aktiven Modells und ein Bereich mit bearbeitbaren Prompts. Oder installieren Sie
Ollama selbst von **ollama.com** und führen Sie `ollama pull llama3.2:3b` aus. Modell-Downloads gehen
**über das offene Internet (Clearnet) durch den Ollama-Prozess** hinaus (nicht über den Tor-Pfad der App) — das wird bei der
Zustimmung offengelegt. Die LLM-Plakette in der oberen Leiste zeigt den aktuellen Status (ein Klick darauf öffnet Einstellungen → KI); jedes
Suchergebnis hat die Schaltflächen **Zusammenfassen** und **Übersetzen**. API:
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisted with provenance
```
Wenn Ollama nicht läuft, liefern diese HTTP 503 mit einer klaren Meldung — keine vorgetäuschte Zusammenfassung.

**Rohstoffpreise + ehrliche Korrelation.**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
Die Korrelation liefert einen echten Koeffizienten + p-Wert + n aus scipy (Pearson/Spearman),
mit dem Vorbehalt „Korrelation ≠ Kausalität“; zu wenig Überschneidung → `insufficient_data`.

**Überwachung.** `GET /api/monitoring/health` führt echte Erreichbarkeitsprüfungen
durch (über den ethischen Abrufer); `GET /api/monitoring/anomalies` markiert
Ausschläge im Artikelvolumen per z-Wert. **E-Mail:** `POST /api/sources/{id}/ingest-email`
(IMAP) führt Nachrichten in denselben durchsuchbaren Korpus ein.

**Prüfung von Bild-Metadaten.** `POST /api/verify/image-metadata`
(ein Bild hochladen) liefert Format, Abmessungen, EXIF und GPS mit nüchternen, sachlichen
Beobachtungen (z. B. Kennzeichnung durch Bearbeitungssoftware vorhanden, kein Aufnahmezeitstempel). Ehrlich
eingegrenzt als *Metadatenprüfungen* — **keine** Erkennung von Deepfakes/Manipulationen (die war
erfunden und wurde aus dem Arbeitsverzeichnis in Quarantäne verschoben; siehe
[docs/QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md)).

**Signierte Beweispakete.** Die Schaltfläche **Signierte Belege exportieren** im Analysefenster
(oder `POST /api/reports/evidence`) erzeugt ein Paket mit Merkle-Wurzel und
Ed25519-Signatur. Jeder kann es offline prüfen, ohne diese App:
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = verified
```

**Verwahrungskette.** Der Oberflächenbereich **Verwahrungskette** verfolgt einen signierten,
manipulationserkennbaren Herkunftsnachweis und lässt Sie sein Verhalten zur Laufzeit umschalten:
Post-Quanten-Signaturen, Verankerungsmodus (offline `local` oder über Bitcoin verankert per
**OpenTimestamps**) und automatische Protokollierung beim Einlesen. Die Schalter sind *Präferenzen* — der
Bereich zeigt den **tatsächlich wirksamen** Zustand, sodass nichts behauptet, eingeschaltet zu sein, wenn sein zusätzliches Paket
nicht installiert ist. API:
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # effective state
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # offline-verifiable
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = verified
```
Vollständiges Modell, Bedrohungsmodell und Datenschutz-Vorbehalte: [USER_MANUAL.md](USER_MANUAL.md).

---

## Was „ethisches Einlesen“ garantiert

- robots.txt wird abgerufen, pro Host zwischengespeichert und ist **im Zweifel sperrend (fail-closed)**: Lässt es sich nicht
  bestätigen (Netzwerkfehler, Zeitüberschreitung, 5xx oder ein einschränkendes 401/403), wird die URL
  **nicht** abgerufen.
- Ein Mindestabstand pro Host wird durchgesetzt (unter Beachtung von `Crawl-delay`).
- Ein einziger Abrufpfad, ein identifizierender User-Agent (im geschützten Modus ein generischer, außer bei API- und Dump-Anfragen an die Server von Wikimedia), für Artikel nur HTML — keine rohe Umgehung.
- Die Extraktion verwendet trafilatura; wird kein echter Artikeltext gefunden, wird nichts gespeichert
  (keine erfundenen Zeilen „No Title / No Content“).
- Jeder gespeicherte Artikel trägt einen Herkunftsnachweis: Quelle, ursprüngliche URL, kanonische URL,
  Inhalts-Hash (für die Deduplizierung verwendet), Abrufzeitpunkt.
