<!-- de: Translation of docs/GOVERNANCE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 7 of 7 headings. Corrections are welcome as a pull request. -->

# Governance und zulässige Nutzung

Open Omniscience ist ein Werkzeug, um **Macht zur Rechenschaft zu ziehen**, indem es Menschen hilft,
die *Struktur* öffentlicher Informationen ehrlich zu sehen. Weil diese Fähigkeit mächtig ist, legt
dieses Dokument klar dar, wofür das Werkzeug gedacht ist, welche Grenzen es nicht überschreitet und
wie es vertrauenswürdig bleiben will, während es wächst. Das ist Teil der Ethik des Projekts, kein
nachträglicher Gedanke.

## Wofür es gedacht ist

- **Investigativer Journalismus und Forschung im öffentlichen Interesse** über *veröffentlichte*
  Medien, Institutionen, Märkte und Rechtstexte — messbare Struktur sichtbar machen
  (Eigentumskonzentration, Koordination/Echo, Neuheit, Framing, Veränderung über die Zeit), die ein
  Mensch beurteilt.
- **Quellenschutz und Reproduzierbarkeit** — lokal zuerst, offline nutzbar, mit
  manipulationserkennbarer Herkunftsangabe, damit Ergebnisse verteidigt werden können. Die
  hash-verkettete, signierte Beweiskette (Chain of Custody) ist **optional** (standardmäßig
  ausgeschaltet — sie fügt pro Artikel einen kleinen Signaturaufwand hinzu): Aktivieren Sie sie
  unter **Einstellungen → Verwahrungskette → „Automatisch beim Erfassen protokollieren“**
  (oder `OO_CUSTODY_ON_INGEST=1`), wenn die Beweisintegrität für einen Fall wichtig ist. Bis dahin
  begleitet die Herkunftsangabe trotzdem jeden Artikel (Quelle, Erfassungszeit, Inhalts-Hash), und
  signierte Beweispakete können bei Bedarf erstellt werden.

## Rote Linien der doppelten Verwendbarkeit (konstruktionsbedingt abwesend, nicht konfigurierbar)

Dieselben Techniken, die eine koordinierte Einflussoperation aufdecken, könnten in falschen Händen
auf gewöhnliche Menschen gerichtet werden. Die Linie, die dies zu einem Instrument der
*Rechenschaft* und nicht zu einem Werkzeug der *Überwachung* macht, ist präzise, und sie wird in
der **Architektur** gehalten, nicht in einer Einstellung, die ein Nutzer umschalten könnte:

1. **Keine Verfolgung von Privatpersonen.** Das Werkzeug analysiert *veröffentlichte Quellen*
   (Medien, Institutionen, öffentliche Dokumente). Es erstellt **keine** Profile von
   Privatpersonen, und `src/compliance/gdpr.py` ist die Schutzvorrichtung. Prominenz misst die
   *Berichterstattung über öffentliche Personen, über die bereits geschrieben wurde* —
   Aufmerksamkeit, niemals Bedeutung oder Verdienst.
2. **Keine biometrische Identifizierung.** Keine Gesichts-, Stimm- oder Gangerkennung. Niemals.
3. **Kein Einlesen privater Kanäle.** Keine Direktnachrichten, privaten Feeds, abgefangenen
   Nachrichten oder nicht öffentlichen Daten. Der Korpus wird aus Quellen aufgebaut, auf die der
   Nutzer rechtmäßig und ethisch zugreifen kann.
4. **Keine automatisierten Urteile.** Kein Wahrheits-, Glaubwürdigkeits- oder „Vertrauens“-Wert,
   kein Etikett „voreingenommen“/„gefälscht“. Das Werkzeug zeigt *Messungen mit Methode +
   Einschränkung*; der Mensch zieht die Schlüsse. (Im Code durchgesetzt:
   `assert_no_score_fields`.)
5. **Kein zentraler Server, keine Konten, keine Telemetrie.** Nichts verlässt den Rechner des
   Nutzers außer den Abrufen, die er veranlasst. Es gibt keinen Honigtopf an Nutzerdaten, der
   beschlagnahmt oder per Gerichtsbeschluss angefordert werden könnte.
6. **Kein stilles Filtern oder Herabgewichten von Quellen.** Fakten zur Berichterstattung werden
   *angezeigt*; jede Abschwächung wird vom Nutzer angewendet, gekennzeichnet und ist umkehrbar —
   anzeigen, niemals erzwingen.

Diese werden durchgesetzt, soweit Code das kann: Ein CI-Test
(`tests/test_repo_invariants.py::test_red_lines_not_crossed`) lässt den Build scheitern, wenn
verbotene Fähigkeiten (biometrische Erkennung, Verfolgung von Einzelpersonen) in der Codebasis
auftauchen. Ein Test ist ein Stolperdraht, kein Beweis — die eigentliche Garantie sind Kultur und
Review.

## Rechtliche und ethische Haltung

- Ein **Forschungsspiegel**, nicht die maßgebliche Quelle, und **keine Rechtsberatung**; jeder
  Datensatz verweist auf seinen Ursprung.
- **Ethischer Zugriff** als Standard: robots.txt schlägt geschlossen fehl, Ratenbegrenzung pro
  Host, ein sich identifizierender User-Agent, gespeicherte Quellenangabe und Herkunft. (Ein Nutzer
  kann den *geschützten* Abruf aktivieren — Proxy + generischer UA, außer bei den eigenen
  Wikipedia-, Wikidata- und Dump-Anfragen der App an Wikimedia, deren API-Richtlinie verlangt, dass
  sich jedes Werkzeug zu erkennen gibt —, um eine Quelle oder sich selbst zu schützen, wenn er
  gegen ein mächtiges Ziel recherchiert; das ist die journalistische Pflicht zum Quellenschutz,
  bewusst wahrgenommen und dokumentiert, niemals die stille Voreinstellung.)
- **Lizenzen und Urheberrecht respektieren**; Herkunft und nur das Nötigste speichern; die
  Datenschutzpflichten der jeweiligen Rechtsordnung einhalten.

## Unabhängigkeit und Finanzierung

Das Werkzeug ist bewusst **günstig im Betrieb** (lokal, keine Infrastruktur), damit es
**unabhängig** bleiben kann. Sollte das Projekt jemals Finanzierung annehmen, wird es die
Vereinnahmung durch einen einzelnen Geldgeber oder eine einzelne Agenda vermeiden, Entscheidungen
transparent treffen und die Definition von „Desinformation“ niemals einem Sponsor zuliebe
verbiegen. Die politischste Entscheidung dieses Projekts ist, klein, lokal und unvereinnahmbar zu
bleiben.

## Widerstand gegen Missbrauch

Kein Werkzeug kann jeden Missbrauch verhindern, und wir werden nichts anderes behaupten. Unser
Widerstand ist strukturell: die oben genannten roten Linien, das lokale Design (keine zentralen
Daten, die sich in großem Maßstab missbrauchen ließen), die Weigerung, Urteile zu fällen, und
Offenheit (jeder kann prüfen, forken und auditieren). Wenn Sie glauben, dass das Projekt über eine
rote Linie gelenkt wird, eröffnen Sie ein Issue — diese Anfechtbarkeit ist der Sinn der Sache.

## Wie Entscheidungen getroffen werden (Absicht)

Heute ist dies ein junges Projekt mit einem einzigen Maintainer. Vor einer öffentlichen
`0.1`-Alpha beabsichtigen wir: eine **externe Sicherheits- und Ethikprüfung**, einen Übergang zu
einer **Governance mit mehreren Maintainern** mit transparenter Entscheidungsfindung und eine
**Beitragsvereinbarung**, die Mitwirkende an die roten Linien bindet. Bis dahin ist dieses Dokument
die verbindliche Zusage.
