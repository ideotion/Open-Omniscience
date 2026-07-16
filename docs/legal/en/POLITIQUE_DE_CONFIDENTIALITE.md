# Privacy Policy (RGPD)

> **Machine-drafted translation — pending native review. The French version
> ([`../POLITIQUE_DE_CONFIDENTIALITE.md`](../POLITIQUE_DE_CONFIDENTIALITE.md)) is the
> legally authoritative text.**

> ⚠️ **Important notice — working draft, not legal advice.** This document is a
> **working draft (template)** provided for information. It **does not constitute
> legal advice or a legal consultation** and has not been validated by a qualified
> legal professional. It must be **reviewed, completed and validated by a qualified
> professional** before any publication. The bracketed mentions
> **[À COMPLÉTER: …]** and **[À VÉRIFIER: …]** flag information still to be provided
> or confirmed.

**Version:** 1.0-draft
**Effective date:** 2026-07-16
**Contact:** open-omniscience@ideotion.com

---

## 1. Guiding principle: no processing by the Publisher

**Open Omniscience** ("the Software") is **"local-first" free software**. **The
Publisher (Ideotion) collects, hosts and processes no personal data** of Users, and
**operates no server**. There is **no account, no registration, no online service and
no telemetry**. **100% of the processing** carried out by means of the Software runs
**locally, on the User's machine**.

Accordingly:

- the Publisher is **neither the data controller nor a processor** of the data
  processed by the User by means of the Software;
- the Publisher has **no access** to any of the User's data;
- this policy has an **informational** value: it explains how the Software works and
  **the obligations that fall on the User** when they process personal data.

## 2. No telemetry and no collection (verifiable)

The design of the Software guarantees, **by construction**:

- **no telemetry**, no tracker, no usage identifier;
- **start-up with no network call whatsoever**; a **network switch ("airplane mode")**
  in the interface cuts off all outbound traffic;
- the **only** network connections are those **the User triggers** to collect sources
  (via the "ethical" fetch component), and, where applicable, the **local** use of an
  AI model (Ollama) that **does not leave the machine**;
- as the code is **free (GPL v3)**, this behaviour is **auditable by anyone**.

> *Consistency note:* these statements reflect the documented state of the Software
> (see the `README`, [`../../SECURITY.md`](../../SECURITY.md) and
> [`../../ETHICS.md`](../../ETHICS.md)). Any future change that introduced any
> transmission of data should be documented here **before** going into service.
> [À VÉRIFIER: confirm the absence of telemetry at each published version.]

## 3. Technical data processed locally by the Software

The Software stores, **on the User's machine only**, the data needed for its
operation: the collected corpus, provenance metadata, the search index, settings,
local logs, signing keys, and the **local consent record** (accepted version +
ISO 8601 timestamp). This data **remains under the exclusive control of the User** and
is never transmitted to the Publisher.

## 4. The User, the sole data controller

Where the content the User collects, imports or analyses **contains personal data**
(for example names, attributed statements, images, identifiers), the User acts as the
**data controller** within the meaning of the **Règlement (UE) 2016/679 (RGPD)** and
of the **loi n° 78-17 du 6 janvier 1978 relative à l'informatique, aux fichiers et aux
libertés ("Loi Informatique et Libertés")**, as amended.

As such, **it is for the User** to comply in particular with the following
obligations:

### 4.1. Legal basis and minimisation

- determine an appropriate **legal basis** (for example **legitimate interest**, in
  compliance with the **balancing** against the rights of the data subjects);
- apply the principles of **minimisation**, **purpose limitation** and **storage
  limitation**.

### 4.2. Special-category data

- exercise **heightened vigilance** towards the **special categories of data**
  (alleged racial or ethnic origin, political opinions, beliefs, health, sexual
  orientation, biometric or genetic data, etc.) covered by **article 9 of the RGPD**,
  the processing of which is **in principle prohibited** save where an applicable
  exception applies.

### 4.3. Transparency and rights of data subjects

- ensure, to the extent required, **transparency** towards the data subjects;
- enable the exercise of their **rights**: **access, rectification, erasure ("right to
  be forgotten"), restriction, objection and portability**.

### 4.4. Erasure requests

Any request for erasure or rectification relating to content collected by the User is
the **User's responsibility** (who holds and controls the data locally). **The
Publisher cannot process any such request**, having no access to the data. To
facilitate this obligation, the Software lets the User **search and delete** content
from their local corpus.

### 4.5. "Journalistic" exemption

Where the processing is carried out for **journalistic purposes** or for **expression
and information**, the User may, under conditions, benefit from **adjustments**
provided by **article 85 of the RGPD** and by the corresponding provisions of the
**Loi Informatique et Libertés**. This exemption **does not relieve** from compliance
with the essential principles and **must be assessed case by case**; it falls within
the **assessment and responsibility of the User**. [À VÉRIFIER: precise references of
the national provisions transposing article 85.]

## 5. AI-produced outputs and personal data

Outputs produced or assisted by AI (summaries, translations, entity extraction,
sentiment analysis, etc.) may **mention or infer** information relating to persons.
They are **probabilistic and fallible** (see **article 7 of the [Terms of
Use](CGU.md)**) and **constitute neither a finding nor an accusation**. Their
production, retention and, above all, their **possible dissemination** fall within the
**responsibility of the User** as data controller and editorial author.

## 6. Security

The Software offers **local** security measures (for example **at-rest encryption** via
SQLCipher, execution restricted to the loopback interface). The **implementation and
robustness** of these measures, and the **physical and logical security** of the
machine, fall to the User. At-rest encryption protects a **seized or copied** file,
**not** a compromised running session, and **offers no recovery** of the passphrase.

## 7. Supervisory authority

In France, the competent supervisory authority is the **Commission nationale de
l'informatique et des libertés (CNIL)**. The User, in their capacity as data
controller, is the **point of contact** for the supervisory authority for the
processing they carry out.

## 8. Contact

As this policy is **informational** (the Publisher processing no data), no request to
exercise rights can be satisfied by the Publisher. For any **question regarding this
document**: **open-omniscience@ideotion.com**.

---

*Related documents: [Terms of Use](CGU.md) · [Legal Notice](MENTIONS_LEGALES.md) · [Acceptable-Use Charter](CHARTE_USAGE.md) · [Index](README.md). See also [`../../SECURITY.md`](../../SECURITY.md) and [`../../ETHICS.md`](../../ETHICS.md).*
