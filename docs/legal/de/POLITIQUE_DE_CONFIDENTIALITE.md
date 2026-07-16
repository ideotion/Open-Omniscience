# Datenschutzerklärung (DSGVO/RGPD)

> **Maschinell erstellte Übersetzung (Entwurf) — vorbehaltlich muttersprachlicher
> Prüfung. Die französische Fassung
> ([`../POLITIQUE_DE_CONFIDENTIALITE.md`](../POLITIQUE_DE_CONFIDENTIALITE.md)) ist der
> rechtlich maßgebliche Text.**

> ⚠️ **Wichtiger Hinweis — Arbeitsentwurf, keine Rechtsberatung.** Dieses Dokument ist
> ein **Arbeitsentwurf (Vorlage)**, der zu Informationszwecken bereitgestellt wird. Es
> **stellt keine Rechtsberatung und keine rechtliche Auskunft dar** und wurde nicht von
> einer qualifizierten Person des Rechts geprüft. Es muss vor jeder Veröffentlichung von
> **einer qualifizierten Fachperson geprüft, vervollständigt und freigegeben** werden.
> Die in eckigen Klammern stehenden Hinweise **[À COMPLÉTER: …]** und **[À VÉRIFIER: …]**
> kennzeichnen noch zu ergänzende oder zu bestätigende Angaben.

**Version:** 1.0-draft
**Datum des Inkrafttretens:** 2026-07-16
**Kontakt:** open-omniscience@ideotion.com

---

## 1. Leitprinzip: keine Verarbeitung durch den Herausgeber

**Open Omniscience** („die Software") ist **freie „local-first"-Software**. **Der
Herausgeber (Ideotion) erhebt, hostet und verarbeitet keine personenbezogenen Daten** der
Nutzerinnen und Nutzer und **betreibt keinen Server**. Es gibt **kein Konto, keine
Registrierung, keinen Online-Dienst und keine Telemetrie**. **100 % der Verarbeitungen**,
die mithilfe der Software durchgeführt werden, laufen **lokal, auf dem Rechner der Nutzerin
bzw. des Nutzers**.

Dementsprechend:

- ist der Herausgeber **weder Verantwortlicher noch Auftragsverarbeiter** der von der
  Nutzerin bzw. dem Nutzer mithilfe der Software verarbeiteten Daten;
- hat der Herausgeber **keinen Zugriff** auf irgendwelche Daten der Nutzerin bzw. des
  Nutzers;
- hat die vorliegende Erklärung **informativen** Wert: Sie erläutert die Funktionsweise der
  Software und **die Pflichten, die der Nutzerin bzw. dem Nutzer obliegen**, wenn sie bzw.
  er personenbezogene Daten verarbeitet.

## 2. Keine Telemetrie und keine Erhebung (überprüfbar)

Die Konzeption der Software garantiert **konstruktionsbedingt**:

- **keine Telemetrie**, keinen Tracker, keine Nutzungskennung;
- einen **Start ohne jeden Netzwerkaufruf**; ein **Netzwerkschalter („Flugmodus")** in der
  Oberfläche unterbricht jeglichen ausgehenden Verkehr;
- die **einzigen** Netzwerkverbindungen sind diejenigen, die die **Nutzerin bzw. der Nutzer
  auslöst**, um Quellen zu erheben (über die „ethische" Abrufkomponente), sowie
  gegebenenfalls die **lokale** Nutzung eines KI-Modells (Ollama), das **den Rechner nicht
  verlässt**;
- da der Code **frei (GPL v3)** ist, ist dieses Verhalten **von jedermann überprüfbar**.

> *Hinweis zur Kohärenz:* Diese Aussagen geben den dokumentierten Stand der Software wieder
> (siehe die `README`, [`../../SECURITY.md`](../../SECURITY.md) und
> [`../../ETHICS.md`](../../ETHICS.md)). Jede künftige Weiterentwicklung, die irgendeine
> Übermittlung von Daten einführen würde, müsste hier **vor** ihrer Inbetriebnahme
> dokumentiert werden. **Dauerhafter Prüfpunkt (bei jeder Version erneut zu überprüfen,
> vor jeder Aktualisierung des oben stehenden Felds „Version"): das Fehlen von Telemetrie
> im tatsächlich veröffentlichten Code erneut bestätigen.**

## 3. Technische Daten, die lokal von der Software verarbeitet werden

Die Software speichert **ausschließlich auf dem Rechner der Nutzerin bzw. des Nutzers** die
für ihren Betrieb erforderlichen Daten: das erhobene Korpus, Herkunftsmetadaten, den
Suchindex, die Einstellungen, lokale Protokolle, Signaturschlüssel und die **lokale
Einwilligungsaufzeichnung** (angenommene Version + Zeitstempel ISO 8601). Diese Daten
**verbleiben unter der ausschließlichen Kontrolle der Nutzerin bzw. des Nutzers** und
werden niemals an den Herausgeber übermittelt.

## 4. Die Nutzerin bzw. der Nutzer als alleinige(r) Verantwortliche(r)

Enthalten die von der Nutzerin bzw. dem Nutzer erhobenen, importierten oder analysierten
Inhalte **personenbezogene Daten** (z. B. Namen, zugeschriebene Äußerungen, Bilder,
Kennungen), so handelt die Nutzerin bzw. der Nutzer als **Verantwortliche(r)** im Sinne des
**Règlement (UE) 2016/679 (RGPD / DSGVO)** und der **loi n° 78-17 du 6 janvier 1978
relative à l'informatique, aux fichiers et aux libertés („Loi Informatique et Libertés")**
in ihrer geänderten Fassung.

Als solche(r) **obliegt es der Nutzerin bzw. dem Nutzer**, insbesondere folgende Pflichten
einzuhalten:

### 4.1. Rechtsgrundlage und Datenminimierung

- eine geeignete **Rechtsgrundlage** bestimmen (z. B. das **berechtigte Interesse**, unter
  Beachtung der **Abwägung** mit den Rechten der betroffenen Personen);
- die Grundsätze der **Datenminimierung**, der **Zweckbindung** und der **Speicherbegrenzung**
  anwenden.

### 4.2. Besondere Datenkategorien

- eine **erhöhte Wachsamkeit** gegenüber den **besonderen Kategorien personenbezogener
  Daten** (vermeintliche rassische oder ethnische Herkunft, politische Meinungen,
  Überzeugungen, Gesundheit, sexuelle Orientierung, biometrische oder genetische Daten
  usw.) walten lassen, die von **article 9 du RGPD** erfasst werden und deren Verarbeitung
  **grundsätzlich untersagt** ist, sofern keine anwendbare Ausnahme greift.

### 4.3. Transparenz und Rechte der betroffenen Personen

- soweit erforderlich die **Transparenz** gegenüber den betroffenen Personen
  gewährleisten;
- die Ausübung ihrer **Rechte** ermöglichen: **Auskunft, Berichtigung, Löschung („Recht
  auf Vergessenwerden"), Einschränkung, Widerspruch und Übertragbarkeit**.

### 4.4. Löschungsanträge

Jeder Antrag auf Löschung oder Berichtigung in Bezug auf von der Nutzerin bzw. dem Nutzer
erhobene Inhalte liegt in der **Verantwortung der Nutzerin bzw. des Nutzers** (die bzw. der
die Daten lokal besitzt und kontrolliert). **Der Herausgeber kann keinen solchen Antrag
bearbeiten**, da er keinen Zugriff auf die Daten hat. Zur Erleichterung dieser Pflicht
ermöglicht die Software es der Nutzerin bzw. dem Nutzer, Inhalte aus ihrem bzw. seinem
lokalen Korpus zu **durchsuchen und zu löschen**.

### 4.5. „Journalistische" Ausnahme

Erfolgt die Verarbeitung zu **journalistischen Zwecken** oder zu Zwecken der **Äußerung und
Information**, so kann die Nutzerin bzw. der Nutzer unter bestimmten Voraussetzungen die in
**article 85 du RGPD** und in den entsprechenden Bestimmungen der **Loi Informatique et
Libertés** vorgesehenen **Anpassungen** in Anspruch nehmen. Diese Ausnahme **entbindet
nicht** von der Einhaltung der wesentlichen Grundsätze und **ist im Einzelfall zu
beurteilen**; sie fällt in die **Beurteilung und Verantwortung der Nutzerin bzw. des
Nutzers**. Die nationale Umsetzung findet sich in **Artikel 80 der loi n° 78-17 du 6
janvier 1978** (in der durch die Ordonnance vom 12. Dezember 2018 geänderten Fassung), der
es — ausnahmsweise und in dem zur Vereinbarkeit von Datenschutz und der Freiheit der
Meinungsäußerung und Information erforderlichen Umfang — ausschließt, bestimmte
Vorschriften der DSGVO auf Verarbeitungen anzuwenden, die insbesondere zur berufsmäßigen
Ausübung der journalistischen Tätigkeit vorgenommen werden.

## 5. Durch KI erzeugte Ergebnisse und personenbezogene Daten

Durch KI erzeugte oder unterstützte Ergebnisse (Zusammenfassungen, Übersetzungen,
Entitätsextraktion, Sentiment-Analyse usw.) können Informationen über Personen **erwähnen
oder ableiten**. Sie sind **probabilistisch und fehleranfällig** (siehe **Artikel 7 der
[Nutzungsbedingungen](CGU.md)**) und **stellen weder eine Feststellung noch eine
Anschuldigung dar**. Ihre Erzeugung, ihre Aufbewahrung und vor allem ihre **etwaige
Verbreitung** fallen in die **Verantwortung der Nutzerin bzw. des Nutzers** als
Verantwortliche(r) und redaktionelle(r) Urheber(in).

## 6. Sicherheit

Die Software bietet **lokale** Sicherheitsmaßnahmen (z. B. die **Verschlüsselung im
Ruhezustand** mittels SQLCipher, die auf die Loopback-Schnittstelle beschränkte
Ausführung). Die **Umsetzung und Robustheit** dieser Maßnahmen sowie die **physische und
logische Sicherheit** des Rechners obliegen der Nutzerin bzw. dem Nutzer. Die
Verschlüsselung im Ruhezustand schützt eine **beschlagnahmte oder kopierte** Datei,
**nicht** eine kompromittierte laufende Sitzung, und bietet **keine Wiederherstellung** der
Passphrase.

## 7. Aufsichtsbehörde

In Frankreich ist die zuständige Aufsichtsbehörde die **Commission nationale de
l'informatique et des libertés (CNIL)**. Die Nutzerin bzw. der Nutzer ist in ihrer bzw.
seiner Eigenschaft als Verantwortliche(r) die **Ansprechperson** der Aufsichtsbehörde für
die von ihr bzw. ihm durchgeführten Verarbeitungen.

## 8. Kontakt

Da die vorliegende Erklärung **informativen** Wert hat (der Herausgeber verarbeitet keine
Daten), kann kein Antrag auf Ausübung von Rechten vom Herausgeber erfüllt werden. Bei
**Fragen zu diesem Dokument**: **open-omniscience@ideotion.com**.

---

*Zugehörige Dokumente: [Nutzungsbedingungen](CGU.md) · [Impressum](MENTIONS_LEGALES.md) · [Charta der akzeptablen Nutzung](CHARTE_USAGE.md) · [Index](README.md). Siehe auch [`../../SECURITY.md`](../../SECURITY.md) und [`../../ETHICS.md`](../../ETHICS.md).*
