# Terms of Use (CGU)

> **Machine-drafted translation — pending native review. The French version
> ([`../CGU.md`](../CGU.md)) is the legally authoritative text.**

> ⚠️ **Important notice — this document is written without professional legal
> review, permanently.** This document is a **working draft** written for
> information by the Publisher directly. **It does not constitute legal advice or
> a legal consultation**, including for contractual use. **Open Omniscience is a
> free, non-commercial project run with no budget**: this document **will not be
> reviewed, adapted or validated by a legal professional** — this is a deliberate
> choice, not a step that has merely been postponed.

**Version:** 1.0
**Effective date:** 2026-07-16
**Contact:** open-omniscience@ideotion.com

---

## Definitions

Throughout the project's legal documents:

- **"the Publisher"** means **Ideotion**, a natural person acting in a
  non-professional capacity, author and publisher of the Software under a pseudonym.
- **"the User"** means any person, natural or legal, who installs, runs or uses the
  Software.
- **"the Software"** means **Open Omniscience**, the free software distributed under
  the GNU GPL v3 licence, together with its documentation, in the version used by the
  User.

## Article 1 — Purpose and scope

1.1. These Terms govern the **use of the running Software** and of its **outputs**
(results, measurements, aggregates, generated text). They add to the GNU GPL v3
licence without replacing it.

1.2. **The licence of the *code* is governed exclusively by the GNU GPL v3.** These
Terms do **not** govern copying, studying, modifying or redistributing the code: see
[Article 3](#article-3--relationship-with-the-gnu-gpl-v3-licence).

1.3. **No service operated by the Publisher.** The Software is **installed and run
locally** by the User, on their own machine and infrastructure. The Publisher
**operates no server, no online service, no account and no database** accessible to
the User, and provides **no associated service**. These Terms therefore create **no
service contract** and no availability obligation on the Publisher.

## Article 2 — Acceptance of the terms

2.1. Use of the Software requires the **prior, express and unreserved acceptance** of
these Terms and of the [Acceptable-Use Charter](CHARTE_USAGE.md). A User who does not
accept these terms must **refrain from using** the Software (which deprives them of
none of the rights the GPL v3 otherwise grants them over the code).

2.2. **Acceptance mechanism.** The Software includes a **first-launch consent**
mechanism: it presents these documents and **records locally** (on the User's
machine) the **accepted version** and the **timestamp** (in ISO 8601 format) of
acceptance. This record stays on the User's machine and is **never transmitted** to
the Publisher. The technical details are described in the
[Implementation Notes](IMPLEMENTATION_NOTES.md).

2.3. **New version.** In the event of a substantial change, a **new acceptance** may
be requested at a later launch (see
[Article 14](#article-14--term-changes-to-the-terms-version)).

## Article 3 — Relationship with the GNU GPL v3 licence

3.1. The **code** of the Software is distributed under the **GNU General Public
License version 3**. The **four freedoms** guaranteed by that licence — to run the
program, to study it, to modify it, and to redistribute copies (modified or not),
**including for commercial purposes** — remain **whole and intact**.

3.2. These Terms **add no restriction** to the GPL v3 and **do not condition** the
exercise of those freedoms. No provision herein may be construed as limiting the
copying, modification or redistribution of the code.

3.3. **Precedence of the GPL v3.** In the event of a contradiction between these
Terms and the GPL v3 **concerning the code licence**, **the GPL v3 prevails**. The
Terms apply only to the areas the GPL v3 does not cover (use of the running software,
outputs, conduct, warnings, warranty, liability, indemnification, data).

## Article 4 — Nature of the Software ("as-is")

4.1. The Software is provided **"as-is"**, **without warranty of any kind**, in line
with **sections 15 and 16 of the GPL v3** (disclaimer of warranty and limitation of
liability).

4.2. **Stage of development.** The Software is **young and experimental**: its own
version number (`0.0.x`, pre-alpha) deliberately signals **limited maturity**, and
its documentation indicates that some features are incomplete or under construction.
The Publisher does not warrant **fitness for a particular purpose, the accuracy of
results, availability, or the absence of errors or interruptions**.

4.3. The User acknowledges using the Software **with knowledge of this stage** and
assumes the risks inherent in an experimental tool.

## Article 5 — User's responsibility: legality of use

5.1. The User is **solely responsible** for the compliance of their use with all
**applicable law** in their jurisdiction(s), in particular:

- compliance with the **`robots.txt`** files and the **terms of use (ToS)** of the
  sites consulted or collected;
- **copyright** and **neighbouring rights**, as well as the ***sui generis* right of
  database producers**;
- the law on **personal-data protection** (see [Article 6](#article-6--personal-data)
  and the [Privacy Policy](POLITIQUE_DE_CONFIDENTIALITE.md));
- **trade secrets**, **professional secrecy**, and any legal or contractual
  restriction applicable to the content processed.

5.2. The Software includes technical safeguards (fail-closed `robots.txt` compliance,
per-host rate limiting, an identifying user agent); these safeguards **do not relieve**
the User from verifying the lawfulness of each collection and each processing
operation.

5.3. The User **shall not** circumvent any technical protection measure, collect
content they cannot lawfully access, or, more generally, make any use prohibited by
the [Acceptable-Use Charter](CHARTE_USAGE.md).

## Article 6 — Personal data

6.1. **No processing by the Publisher.** The Publisher **collects, hosts and processes
no personal data** of Users and **operates no server**. All processing carried out by
means of the Software takes place **locally**, on the User's machine.

6.2. **The User is the sole data controller.** For any personal data contained in the
content they collect, import, store or analyse, the User acts as the **data
controller** within the meaning of the **Règlement (UE) 2016/679 (RGPD)**. The
Publisher is **neither the controller nor a processor** of such data.

6.3. The User's obligations in this respect (legal basis, special-category data,
transparency, rights of data subjects including the **right to erasure**, the
journalistic exemption) are detailed in the
[Privacy Policy](POLITIQUE_DE_CONFIDENTIALITE.md).

## Article 7 — Outputs produced or assisted by AI

> 🔴 **KEY CLAUSE — READ CAREFULLY.**

7.1. **Probabilistic and fallible nature.** The Software may produce or present
**outputs generated or assisted by models or automated processing**, in particular:
**summaries**, **translations**, **syntheses** across articles, **keyword and entity
extraction**, **sentiment / "tone" analysis** ("framing"), **associations** between
terms ("mind-map"), **near-duplicate and coordination detection** across sources,
**change flagging** (Wikipedia, law), **price ↔ media-coverage correlations**, and
**investigation cards** ("*Leads*") highlighting structural patterns. All such outputs
are **probabilistic, approximate and liable to be wrong**.

7.2. **They are neither findings nor accusations.** These outputs are
**investigative-assistance signals** accompanied by their method and caveats —
**never a verdict, never proof, never an accusation**. They constitute **no factual
finding, no legal characterisation, no judgment of the credibility, truthfulness or
reliability** of a person, a source or a piece of content. Consistent with the
messages displayed within the Software itself:

> - "*AI summary — unreliable, verify against the source.*"
> - "*AI translation — unreliable, verify against the source.*"
> - "*Assistance, never a verdict.*"
> - "*Deduced from text, never confirmed.*"
> - "*counts only, never a verdict*"

7.3. **Mandatory independent verification.** Before any **use, dissemination,
publication or decision** based on an output of the Software, the User must
**verify it independently** against the primary sources. Sentiment analysis, in
particular, relies in part on an **English-lexicon method** (VADER): the tone shown
for non-English content is **unreliable or absent**.

7.4. **Capability limits — no claim to non-functional detectors.** The project has
deliberately **set aside ("quarantined")** components once advertised (deepfake
detection, propaganda, cognitive bias, bots) that **fabricated scores** without real
detection (see [`../../ETHICS.md`](../../ETHICS.md) and the `README`). Accordingly,
the Software **does not provide** such detectors as if they worked. **If** an output
of a classificatory or evaluative nature should exist or be added (for example a bias
indicator, a "disinformation risk", a manipulation or deepfake index, a peer-review
simulation, or a reproducibility score), **the same caveats would apply *a
fortiori*** : a probabilistic, fallible output, to be verified, **never a verdict**.

7.5. **Defamation and third-party rights — the User's responsibility.** Publishing,
disseminating or imputing to an **identifiable person** a characterisation derived
from an output of the Software (for example presenting them as a "disinformer",
"coordinated", "biased", etc.) may engage the **civil and/or criminal liability of
the User** (in particular for **defamation**, insult, disparagement or breach of
data protection). **This liability lies with the User, not with the Publisher or the
Software.** The User remains the sole author and editorial party responsible for any
publication derived from their use.

7.6. **No composite score.** In keeping with the Software's design, it presents **no
composite score** of trust, quality or credibility; each signal is accompanied by its
method, a caveat and its sample size (*n*).

## Article 8 — Acceptable use

8.1. The User undertakes to comply with the [Acceptable-Use Charter](CHARTE_USAGE.md),
which forms an **integral part** of these Terms and lists the **intended purpose**
(investigative journalism, public-interest research, accountability) as well as the
**strictly prohibited uses** (surveillance of individuals, harassment, *doxxing*,
profiling of private persons, unlawful interception, circumvention of site terms, and
any unlawful or malicious use).

8.2. Any use contrary to the Charter constitutes a **breach of these Terms**.

## Article 9 — Disclaimer of warranty and limitation of liability

9.1. **Disclaimer of warranty.** To the **fullest extent permitted by applicable
law**, the Software is provided **without any warranty**, express or implied,
including, without limitation, warranties of **merchantability**, **fitness for a
particular purpose**, **accuracy**, **availability** and **non-infringement**. This
disclaimer **reinforces and supplements** the disclaimer of warranty in **section 15
of the GPL v3**.

9.2. **Limitation of liability.** To the **fullest extent permitted by applicable
law**, the Publisher shall not be liable for **direct or indirect damages** (in
particular loss of data, loss of business, reputational harm, third-party claims)
arising from the use of, or inability to use, the Software or its outputs. This
limitation **reinforces and supplements** **section 16 of the GPL v3**.

9.3. **Mandatory limits — consumer protection.** The above exclusions and limitations
apply **only within the limits permitted by law** and **may not set aside** what
cannot lawfully be set aside, in particular:

- liability in the event of **wilful misconduct (dol)** or **gross negligence (faute
  lourde)**;
- liability in the event of **personal injury**;
- the **mandatory rights granted to consumers** by the **Code de la consommation** and
  by European Union law (including, where applicable, the rules on the **conformity of
  digital content and services**).

Where the User acts as a **consumer**, no provision herein deprives them of the
**mandatory rights** guaranteed to them by law, in particular **articles L.224-25-1 to
L.224-25-32 of the Code de la consommation** (the conformity guarantee for digital
content and services, transposing Directive (EU) 2019/770 — the conformity guarantee
proper being set out in articles L.224-25-12 to L.224-25-26), which apply even where
the digital content or service is supplied **free of charge**.

## Article 10 — Indemnification

10.1. To the **fullest extent permitted by applicable law**, the User undertakes to
**indemnify and hold the Publisher harmless** from any **claim, action, judgment,
loss, damage, cost or expense** (including reasonable defence costs) brought by a third
party and arising from: (i) their **use or misuse** of the Software or its outputs;
(ii) their **breach** of these Terms or of the [Acceptable-Use Charter](CHARTE_USAGE.md);
(iii) any **violation by the User of the law or of third-party rights** (copyright,
neighbouring rights, database rights, data protection, privacy, defamation, etc.).

10.2. This clause **does not apply** to the extent such indemnification is
**prohibited by a mandatory provision**, in particular **as regards a consumer**.

## Article 11 — Third-party components (models and dependencies)

11.1. The Software **enables** the User to download and run **third-party AI models**
and relies on **third-party libraries and dependencies**, each governed by its **own
licence** and, where applicable, its own **acceptable-use policy**.

11.2. **User's responsibility.** It is the User's responsibility to **become aware of
and comply with** the licence and use policy of **any model or component** they
download, install or run. The Publisher **recommends by default** models published
under **OSI-approved permissive licences** (Apache-2.0 / MIT), but the choice of model
remains **free**: any other model is used **at the sole discretion and under the sole
responsibility of the User**, under that model's own licence.

11.3. **Exclusion.** The Publisher **disclaims all responsibility** for third-party
models and components, their outputs, their compliance, and the **lawfulness of the
content** the User collects or produces by means of those components.

## Article 12 — Intellectual property

12.1. The Publisher **claims no rights** over the **content** the User collects,
imports, stores, produces or exports by means of the Software. Such content remains
subject to the **rights of their respective holders**, which the User undertakes to
respect.

12.2. The **code** of the Software is protected and distributed under the **GNU GPL
v3**. "Ideotion" is used as an **author pseudonym**; this use grants the User no right
over that pseudonym.

## Article 13 — User's data and backups

13.1. As the Software is **local**, the User is **solely responsible** for the
**retention, backup and security** of their data (corpus, settings, keys). In
particular, at-rest encryption (SQLCipher) **offers no recovery** in the event the
passphrase is lost.

13.2. The Publisher has **no access** to any of the User's data and can therefore
neither restore nor recover it.

## Article 14 — Term, changes to the terms, version

14.1. These Terms apply for the entire duration of use of the Software.

14.2. The Publisher may **amend** these Terms. The **applicable version** is the one
**distributed with the version of the Software** used by the User; it is identified by
the **"Version"** field above. A substantial change may give rise to a **new request
for acceptance** (see [Article 2](#article-2--acceptance-of-the-terms)).

## Article 15 — Governing law and jurisdiction

15.1. These Terms are governed by **French law**, within the framework of **European
Union law** as the applicable supranational framework.

15.2. **Disputes.** The parties shall endeavour to resolve any dispute amicably.
Failing that, the dispute shall be brought before the competent courts in accordance
with the rules of ordinary law.

15.3. **Consumer protection — mandatory rule.** Where the User acts as a **consumer**,
these provisions **do not deprive them** of the possibility of bringing the matter
before the **court of their place of domicile**, nor of the **mandatory rules of
jurisdiction and protection** provided in their favour, in particular by the **Code de
la consommation** and by **articles 17 to 19 of règlement (UE) n° 1215/2012 ("Brussels
I bis")** (the section devoted to contracts concluded by consumers), and in particular
**article 18**, which allows the consumer to bring proceedings before the court of
their own domicile and, reciprocally, restricts the trader to bringing proceedings
against the consumer only before that same court. No clause herein may derogate from
these mandatory rules.

## Article 16 — Miscellaneous

16.1. **Partial invalidity.** If any provision herein is held void or unenforceable,
the remaining provisions remain in force.

16.2. **Language.** The **French** version of these Terms prevails.

## Article 17 — Contact

For any question regarding these Terms: **open-omniscience@ideotion.com**.

---

*Related documents: [Legal Notice](MENTIONS_LEGALES.md) · [Privacy Policy](POLITIQUE_DE_CONFIDENTIALITE.md) · [Acceptable-Use Charter](CHARTE_USAGE.md) · [Implementation Notes](IMPLEMENTATION_NOTES.md) · [Index](README.md). See also [`../../ETHICS.md`](../../ETHICS.md) and [`../../GOVERNANCE.md`](../../GOVERNANCE.md).*
