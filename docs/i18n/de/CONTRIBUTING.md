<!-- de: Translation of docs/CONTRIBUTING.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 15 of 15 headings. Corrections are welcome as a pull request. -->

# Mitwirken

Danke für Ihre Hilfe. Das Leitprinzip ist **Ehrlichkeit**: Eine Funktion muss tun, was sie
verspricht, sonst wird sie nicht ausgeliefert. Keine erfundenen Ausgaben, keine falschen
Konfidenzwerte, keine stille Verschlechterung — siehe [DESIGN.md](DESIGN.md) §3.

## Einrichtung

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q          # full suite, a few minutes
```

`pyproject.toml` bleibt die einzige maßgebliche Quelle für Abhängigkeiten (wir installieren die
neueste Version oberhalb der Mindestversionen, damit die CI Brüche bei Upstream-Projekten früh
erkennt). Für eine **reproduzierbare / Release-Installation** gibt es eine daraus abgeleitete,
per Hash fixierte Sperrdatei:

```bash
pip install -r requirements.lock          # exact, hash-verified core + analysis pins
# regenerate after a dependency change:
pip-compile --generate-hashes --extra analysis -o requirements.lock pyproject.toml
```

**Das ist in `./install.sh` eingebunden, nicht nur ein Befehl, den Sie von Hand ausführen.** Der
Online-Installationspfad (`pip_install()`) verwendet `requirements.lock` automatisch, sobald die
Datei vorhanden ist, für das laufende Python erzeugt wurde und jede angeforderte Komponente
(`OO_COMPONENTS`) abdeckt — geprüft gegen den eigenen `pip-compile ... --extra=...`-Kopf der
Sperrdatei, niemals von Hand gepflegt. Wenn eine dieser Bedingungen nicht erfüllt ist (die
Sperrdatei ist für Ihr Python veraltet, verlangt eine Komponente, mit der sie nicht erzeugt wurde,
oder eine Fixierung lässt sich auf dieser Plattform nicht auflösen), fällt er auf die gewöhnliche,
auf Mindestversionen beruhende Auflösung `pip install -e ".[...]"` zurück, mit einer deutlichen
Meldung, warum der geprüfte Pfad nicht verwendet wurde — `OO_USE_LOCK=0` schaltet die Sperrdatei
bedingungslos ab. **Im ausgelieferten Zustand deckt die Sperrdatei nur `--extra analysis` ab**,
während der eigene Standard-Komponentensatz von `install.sh` `analysis,compression,columnar` ist —
ein unbeaufsichtigter Standardlauf von `./install.sh` fällt daher heute auf die Auflösung nach
Mindestversionen zurück (compression/columnar sind von der Sperrdatei nicht abgedeckt). Führen Sie
`OO_COMPONENTS=analysis ./install.sh` aus, um den geprüften Pfad im aktuellen Zustand zu nutzen,
oder erweitern Sie die Abdeckung der Sperrdatei mit `pip-compile --extra analysis --extra
compression --extra columnar ...`, damit auch der Standard-Installationspfad auf der Sperrdatei
beruht.

Das **Offline-/Air-Gap-Paket** (`scripts/build_offline_bundle.sh`, verwendet vom
`--no-index`-Offline-Pfad von `install.sh` für das Ziel Qubes/Tails) ist **noch nicht an die
Sperrdatei angebunden** — es löst bei jedem Bau neu aus den Mindestversionen von `pyproject.toml`
auf. Das ist eine bekannte, offene Lücke, kein Versehen: das Offline-Paket ebenfalls auf die
Sperrdatei zu stützen (`pip download --require-hashes -r requirements.lock`, wobei die auf `$SPEC`
beruhende Auflösung als Rückfall für alle Extras bleibt, die die Sperrdatei nicht abdeckt), ist als
Folgearbeit erfasst.

## Arbeitsablauf

- **Python 3.13**, eine einzige `pyproject.toml` (keine requirements.txt).
- Linting/Formatierung mit **ruff**; Typprüfung mit **mypy**: `make lint && make typecheck`.
- Jede Änderung endet grün: `make check` (ruff + pytest). Fügen Sie für neues Verhalten einen
  Verhaltenstest hinzu; reparieren oder in Quarantäne stellen — lassen Sie keinen halb
  funktionierenden Code im Importpfad.
- Committen Sie in kleinen, ehrlichen Schritten mit Nachrichten, die sagen, *was und warum*.
- Schemaänderungen laufen über Alembic (`alembic revision --autogenerate`); die CI führt
  `alembic check` aus, um Abweichungen zwischen Modell und Migration zu erkennen.

## Das Auslieferungsregister: eine Datei pro Zeile

Hängen Sie nichts an `docs/ledger/shipped.csv` an. Die Merge-Prüfung von GitHub ignoriert die
`merge=union`-Regel der Datei, sodass eine von jedem PR angehängte Zeile nach jedem Merge jeden
offenen PR in Konflikt brachte. Fügen Sie stattdessen EINE neue Datei hinzu:

    python scripts/ledger_shipped.py new --date 2026-09-30 --area tests --item "..." \
        --status "shipped (draft)" --refs "PR #1240" --key-paths "src/a.py; tests/b.py" --summary "..."

Das schreibt `docs/ledger/shipped.d/<date>-<slug>.csv` (den Kopf des Registers plus eine Zeile).
Kein anderer PR kann mit einer Datei in Konflikt geraten, die er nicht berührt.
`python scripts/ledger_shipped.py check` prüft jedes Fragment; die Release Notes und die
Repo-Invarianten-Tests lesen zuerst `shipped.csv` und danach die Fragmente.
`ledger_shipped.py fold` hängt die Fragmente binär an `shipped.csv` an und löscht sie; das ist für
den Maintainer oder ein Release gedacht, niemals für einen Feature-PR. `refs` muss die echte
PR-Nummer sein, nicht `PR pending` (sonst schlägt ein Test fehl).

## Lektionen und Einträge im Auslieferungsprotokoll: je eine Datei

Dieselbe Konvention gilt für die beiden großen Archive. Eine Lektion ist EINE Datei,
`docs/ledger/lessons.d/<date>-<slug>.md` (`python scripts/lessons.py --new SLUG`); ein wörtlicher
Eintrag im Auslieferungsprotokoll ist EINE Datei, `docs/ledger/shipped_log.d/<date>-<slug>.md`
(`python scripts/ledger_fold.py new-log SLUG`). Hängen Sie niemals etwas an `LESSONS.md` oder
`SHIPPED_LOG.md` an und bearbeiten Sie niemals `_LESSONS_LINE_CEILING`: Jeder PR, der das tat,
geriet mit jedem anderen in Konflikt. Ein Fragment beginnt mit `## <date> — title`, endet mit einem
Zeilenumbruch und ist UTF-8 mit LF-Zeilenenden; eine Lektion (kein Eintrag im
Auslieferungsprotokoll) hat keine zweite Überschrift und bleibt unter 200 Zeilen (das begrenzt die
Größe eines Eintrags); `python scripts/ledger_fold.py check` (und `tests/test_ledger_fragments.py`)
validiert sie, weist die Platzhalter `#NNNN` und `PR pending` zurück, und `lessons.py <words>`
durchsucht auch die Fragmente. `ledger_fold.py fold` führt sie bei einem Release in die Archive
zusammen und ist niemals für einen Feature-PR gedacht.

## Sprachdateien und Merge-Konflikte

Die 12 Dateien `src/static/locales/*.json` werden **sortiert** gehalten (`_meta` zuerst, dann die
Schlüssel in Codepunkt-Reihenfolge), sodass zwei PRs, die Zeichenketten hinzufügen, diese an
verschiedenen Stellen einfügen und sauber zusammengeführt werden. Führen Sie nach dem Hinzufügen
von Zeichenketten `python scripts/locales_merge.py` aus; es sortiert die Dateien und prüft sie
(`--check` prüft nur; `tests/test_locales_merge.py` schlägt bei unsortierten oder doppelten
Schlüsseln fehl).

Wenn `git merge origin/main` Konfliktmarkierungen in Sprachdateien hinterlässt, führen Sie dasselbe
Skript aus: Es behält beide Seiten jedes Abschnitts, sortiert und hält an, wobei es den Schlüssel
nennt, wenn beide Seiten demselben Schlüssel unterschiedlichen Text gegeben haben (ein echter
Widerspruch, der zu entscheiden ist). `docs/ledger/shipped.csv` steht in `.gitattributes` auf
`merge=union`, was ein lokales `git merge` beachtet, der Web-Merge von GitHub und die
Schaltfläche zum Aktualisieren des Branches jedoch nicht: Führen Sie main lokal zusammen und prüfen
Sie dann auf doppelte `(date, area, item)`-Zeilen.

## Standards

- Herkunft überall: Gespeicherte Daten tragen Quelle + Zeitstempel + Hash.
- Jede einem Nutzer gezeigte Zahl muss aus einer echten Methode mit angegebener Unsicherheit
  stammen (`src/analysis`), niemals aus einer Konstante.
- Das Einlesen läuft über den einen ethischen Abrufer (robots schlägt geschlossen fehl,
  ratenbegrenzt).
- Erfundener/toter Code gehört (dokumentiert) nach `quarantine/`, nicht nach `src/`.

## Verhaltenskodex

Mit Ihrer Teilnahme verpflichten Sie sich, den [Verhaltenskodex](CODE_OF_CONDUCT.md) einzuhalten
(Contributor Covenant 2.1). Melden Sie Bedenken vertraulich an open-omniscience@ideotion.com.

## Lizenz

Beiträge stehen unter **GPL-3.0-or-later** (siehe [LICENSE](../LICENSE)).

---

# Versionierungsrichtlinie

Wie das Projekt versioniert wird — mit bewusst untertriebener Reife.

**In diesem Teil:**
- [Versionierungsrichtlinie](#versionierungsrichtlinie)


---

## Versionierungsrichtlinie

> **Wir untertreiben die Reife bewusst. Ehrlichkeit vor Hype.** Es ist besser, dass ein Nutzer
> angenehm überrascht als getäuscht wird. Die Versionsnummer ist ein Versprechen über die *Reife*,
> und wir halten dieses Versprechen zurückhaltend.

### Die einzige maßgebliche Quelle

Die Version steht an **einer Stelle: `pyproject.toml` (`[project] version`)**. Alles andere wird
daraus abgeleitet:

- Die laufende App liest sie aus den Metadaten des installierten Pakets
  (`importlib.metadata.version("open-omniscience")`) — so melden `/api/health`, das
  `version=` der API und die Oberfläche automatisch die *tatsächlich* installierte Version.
- Kein anderer Code enthält ein fest kodiertes Versionsliteral. Tests prüfen gegen die
  Paketmetadaten, nicht gegen eine Zeichenkette (siehe `tests/test_api_search.py`).
- Die `README.md` im Wurzelverzeichnis des Repos nennt die Version einmal, in ihrem Kopf, und eine
  CI-Prüfung stellt sicher, dass sie zum Paket passt
  (`tests/test_repo_invariants.py::test_readme_version_matches_package`).

**Um die Version zu erhöhen, ändern Sie nur `pyproject.toml`**, passen Sie den README-Kopf an (die
Prüfung erzwingt das) und führen Sie dann `pip install -e .` aus, damit die Metadaten aktualisiert
werden.

**Setzen Sie `vX.Y.Z` nur auf einen Commit, dessen `pyproject.toml` bereits `X.Y.Z` lautet.** Der
Release-Workflow (`.github/workflows/release.yml`) weist jedes andere Tag zurück, bevor er
irgendetwas baut, sodass ein vor der Versionserhöhung gesetztes Tag ein Release ohne Wheel, sdist
oder Prüfsummen veröffentlicht. Das erste `v0.4.0` wurde am 2026-09-28 so gesetzt; die Version
wurde danach gesetzt und das Tag darauf verschoben (`docs/product/RELEASE_0.4_GATE.md` Zeile G).
**Ein Tag zu verschieben erfordert git:** Die GitHub-Website kann ein Tag weder löschen noch
verschieben, und ein dort veröffentlichtes Release verwendet das vorhandene Tag weiter, ohne den
Workflow zu starten. Ohne lokalen Klon, der pushen kann, öffnen Sie einen Codespace auf `main` und
führen Sie `git fetch origin && git tag -f vX.Y.Z origin/main && git push -f origin vX.Y.Z` aus.
Löschen Sie zuerst das GitHub-Release, wenn der Workflow die generierten Notizen schreiben soll: Er
behält die Notizen eines vorhandenen Releases und fügt nur die Dateien und Prüfsummen hinzu.

### Die Reifeleiter (wo wir stehen, wohin wir gehen)

Die Software ist jung und muss sich noch bewähren, daher bleibt sie **unter `1.0`**:

```
0.0.x  pre-alpha    the first, un-public pre-alpha iterations (0.0.4 .. 0.0.9).
0.x    alpha        ← we are here (0.5.0). Public, working, honestly-labelled — open
                     to feedback, but not yet consolidated (each cycle is still an
                     "honest about every limit, not finished" release, per the README
                     header — see it for the current cycle's exact status).
0.x    beta         once things consolidate (a deliberate, later maintainer call —
                     not implied by any particular `0.x` number crossing over from alpha).
1.0    release      an official, stable release.
```

Wir werden **nicht** zu einer Versionsnummer springen, die mehr Reife andeutet, als vorhanden ist
(z. B. bedeutet `0.2` nicht „zu 20 % fertig“ oder „fast Beta“ — es ist die ehrliche Zählung der
bisherigen Alpha-Zyklen). Jeder Zyklus ist eine kleine, echte Iteration — mehr wird nicht
behauptet.

### Zuordnung Zyklus ↔ Version

Entwicklungszyklen (und ihre Branches) sind nach der Version benannt, die sie hervorbringen, wobei
führende Nullen der Kürze halber weggelassen werden:

| Branch-/Zyklusname | Paketversion |
|---|---|
| `0.04` | `0.0.4` |
| `0.05` | `0.0.5` |
| `0.06` | `0.0.6` |
| `0.07` | `0.0.7` |
| `0.08` | `0.0.8` |
| `0.09` | `0.0.9` |
| `0.1`  | `0.1.0` |  (der Zyklus-Branch `0.09` wurde beim Wechsel zur Alpha in `0.09 → 0.1` umbenannt)
| `0.2`  | `0.2.0` |  (der Zyklus-Branch `0.1` wurde beim Wechsel zu 0.2 in `0.1 → 0.2` umbenannt)
| `main` | `0.2.0` → `0.3.0` → `0.4.0` → `0.5.0` |  (der Zyklus-Branch `0.2` wurde am 2026-07-15 in `0.2 → main` umbenannt — der Standard-Branch ist nun dauerhaft `main`, und Branch-Name und Version sind unabhängig; `v0.2.0` wurde nach der Skalierungsvalidierung mit einem echten Korpus getaggt, `v0.3.0` schloss den Zyklus „gemessen und verifiziert“ ab, `v0.4.0` schloss den Zyklus der lebenden Quellen ab, und `main` lautet nun `0.5.0`, das Release des Ermittlerschreibtischs, getaggt als `v0.5.0`)

„Die Intelligenzschicht `0.06`“ bedeutet also „die Arbeit, die in `0.0.6` ausgeliefert wird“. Wenn
Sie in der Dokumentation eine Zykluskurzform wie `0.05` lesen, lesen Sie sie als `0.0.5`. PRs
landen auf `main`, dem aktuellen Zyklus-Branch — nicht auf einem der oben genannten, nicht mehr
verwendeten nummerierten Branch-Namen.

**Seit der ersten Alpha (`0.1.0`) lautet die Zuordnung Zyklus `0.N` ⇒ `v0.N.0`** — der Zyklus
`0.2` endete mit `v0.2.0`, der Zyklus `0.3` mit `v0.3.0`, der Zyklus `0.4` mit `v0.4.0`, der
Zyklus `0.5` mit `v0.5.0` (die einzige Ausnahme ist der konsolidierte Zyklus `0.09`, der `0.1.0`
hervorbrachte). Ein Zyklus ist nach dem Release benannt, das ihn abschließt — die
Release-Gate-Dateien sagen das mit eigenen Worten (`RELEASE_0.4_GATE.md` ist „das prüfbare
Inventar zum Abschluss des Zyklus `0.4`“) —, und eine Versionsnummer kann mitten im Zyklus vor dem
Tag *gesetzt* werden (z. B. wurde `0.4.0` am 2026-09-28 gesetzt, damit das Tag darauf verschoben
werden konnte; `0.5.0` wurde im Umstellungs-PR gesetzt, und das Tag benennt dessen Merge-Commit),
weshalb das Datum einer Changelog-Überschrift und das Datum ihres Tags voneinander abweichen
können.

### Warum das wichtig ist (der Bezug zu den Werten)

Dieses Projekt existiert, um Menschen zu helfen, Informationen ehrlich zu sehen. Ein Werkzeug, das
seine eigene Reife übertreibt, würde dem an der Wurzel widersprechen. Zurückhaltende Versionierung
ist dieselbe Disziplin wie im Rest der Codebasis: **nur beanspruchen, was real ist, und es
beweisen.**
