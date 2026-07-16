# Politique de confidentialité (RGPD)

> ⚠️ **Avis important — modèle de travail, non un avis juridique.** Ce document est un
> **modèle (template) de travail** rédigé à titre informatif. Il **ne constitue pas un
> avis ou une consultation juridique** et n'a pas été validé par un professionnel du
> droit. Il doit être **relu, complété et validé par un juriste qualifié** avant toute
> publication. Les mentions entre crochets **[À COMPLÉTER : …]** et **[À VÉRIFIER : …]**
> signalent les informations restant à fournir ou à confirmer.

**Version :** 1.0-draft
**Date d'entrée en vigueur :** 2026-07-16
**Contact :** open-omniscience@ideotion.com

---

## 1. Principe directeur : aucun traitement par l'Éditeur

**Open Omniscience** (« le Logiciel ») est un **logiciel libre « local d'abord »**.
**L'Éditeur (Ideotion) ne collecte, n'héberge et ne traite aucune donnée à caractère
personnel** des Utilisateurs, et **n'exploite aucun serveur**. Il n'existe **ni compte, ni
inscription, ni service en ligne, ni télémétrie**. **100 % des traitements** réalisés au
moyen du Logiciel s'exécutent **localement, sur la machine de l'Utilisateur**.

En conséquence :

- l'Éditeur **n'est ni responsable de traitement, ni sous-traitant** des données traitées
  par l'Utilisateur au moyen du Logiciel ;
- l'Éditeur **n'a accès à aucune** donnée de l'Utilisateur ;
- la présente politique a une **valeur d'information** : elle explique le fonctionnement du
  Logiciel et **les obligations qui pèsent sur l'Utilisateur** lorsqu'il traite des données
  personnelles.

## 2. Absence de télémétrie et de collecte (vérifiable)

La conception du Logiciel garantit, **par construction** :

- **aucune télémétrie**, aucun mouchard, aucun identifiant d'usage ;
- **démarrage sans aucun appel réseau** ; un **interrupteur réseau (« mode avion »)** dans
  l'interface coupe tout trafic sortant ;
- les **seules** connexions réseau sont celles que **l'Utilisateur déclenche** pour
  collecter des sources (via le composant de récupération « éthique »), et, le cas échéant,
  l'usage **local** d'un modèle d'IA (Ollama) qui **ne sort pas de la machine** ;
- le code étant **libre (GPL v3)**, ce comportement est **auditable par quiconque**.

> *Note de cohérence :* ces affirmations reflètent l'état documenté du Logiciel (voir le
> `README`, [`../SECURITY.md`](../SECURITY.md) et [`../ETHICS.md`](../ETHICS.md)). Toute
> évolution future qui introduirait une quelconque transmission de données devrait être
> documentée ici **avant** mise en service. **Point de vigilance permanent (à re-vérifier à
> chaque version, avant toute mise à jour du champ « Version » ci-dessus) : reconfirmer
> l'absence de télémétrie dans le code effectivement publié.**

## 3. Données techniques traitées localement par le Logiciel

Le Logiciel stocke, **sur la machine de l'Utilisateur uniquement**, les données
nécessaires à son fonctionnement : corpus collecté, métadonnées de provenance, index de
recherche, paramètres, journaux locaux, clés de signature, et l'**enregistrement local du
consentement** (version acceptée + horodatage ISO 8601). Ces données **restent sous le
contrôle exclusif de l'Utilisateur** et ne sont jamais transmises à l'Éditeur.

## 4. L'Utilisateur, seul responsable de traitement

Lorsque les contenus que l'Utilisateur collecte, importe ou analyse **contiennent des
données à caractère personnel** (par exemple des noms, des propos attribués, des images,
des identifiants), l'Utilisateur agit en qualité de **responsable de traitement** au sens
du **Règlement (UE) 2016/679 (RGPD)** et de la **loi n° 78-17 du 6 janvier 1978 relative à
l'informatique, aux fichiers et aux libertés (« Loi Informatique et Libertés »)**, telle
que modifiée.

À ce titre, **il incombe à l'Utilisateur** de respecter notamment les obligations
suivantes :

### 4.1. Base légale et minimisation

- déterminer une **base légale** appropriée (par exemple l'**intérêt légitime**, dans le
  respect de la **mise en balance** avec les droits des personnes concernées) ;
- appliquer les principes de **minimisation**, de **limitation des finalités** et de
  **limitation de la conservation**.

### 4.2. Données sensibles (catégories particulières)

- exercer une **vigilance renforcée** à l'égard des **catégories particulières de données**
  (origine prétendue raciale ou ethnique, opinions politiques, convictions, santé,
  orientation sexuelle, données biométriques ou génétiques, etc.) visées par l'**article 9
  du RGPD**, dont le traitement est **en principe interdit** sauf exception applicable.

### 4.3. Transparence et droits des personnes concernées

- assurer, dans la mesure requise, la **transparence** vis-à-vis des personnes concernées ;
- permettre l'exercice de leurs **droits** : **accès, rectification, effacement
  (« droit à l'oubli »), limitation, opposition et portabilité**.

### 4.4. Demandes d'effacement

Toute demande d'effacement ou de rectification portant sur un contenu collecté par
l'Utilisateur relève de la **responsabilité de l'Utilisateur** (qui détient et contrôle les
données localement). **L'Éditeur ne peut traiter aucune telle demande**, faute d'accès aux
données. Pour faciliter cette obligation, le Logiciel permet à l'Utilisateur de **rechercher
et de supprimer** des contenus de son corpus local.

### 4.5. Exception « journalistique »

Lorsque le traitement est réalisé à des **fins journalistiques** ou d'**expression et
d'information**, l'Utilisateur peut, sous conditions, bénéficier d'**aménagements** prévus
par l'**article 85 du RGPD** et par les dispositions correspondantes de la **Loi
Informatique et Libertés**. Cette exception **ne dispense pas** du respect des principes
essentiels et **doit être appréciée au cas par cas** ; elle relève de l'**appréciation et de
la responsabilité de l'Utilisateur**. La transposition nationale figure à l'**article 80 de
la loi n° 78-17 du 6 janvier 1978** (dans sa rédaction issue de l'ordonnance du 12 décembre
2018), qui écarte, à titre dérogatoire et dans la mesure nécessaire à la conciliation entre
protection des données et liberté d'expression et d'information, l'application de certaines
dispositions du RGPD aux traitements mis en œuvre notamment aux fins d'exercice, à titre
professionnel, de l'activité de journaliste.

## 5. Sorties produites par l'IA et données personnelles

Les sorties produites ou assistées par l'IA (résumés, traductions, extraction d'entités,
analyse de sentiment, etc.) peuvent **mentionner ou inférer** des informations relatives à
des personnes. Elles sont **probabilistes et faillibles** (voir l'**article 7 des
[CGU](CGU.md)**) et **ne constituent ni un constat, ni une accusation**. Leur production,
leur conservation et, surtout, leur **éventuelle diffusion** relèvent de la
**responsabilité de l'Utilisateur** en tant que responsable de traitement et auteur
éditorial.

## 6. Sécurité

Le Logiciel propose des mesures de sécurité **locales** (par exemple le **chiffrement au
repos** via SQLCipher, l'exécution restreinte à l'interface de bouclage). La **mise en
œuvre et la robustesse** de ces mesures, ainsi que la **sécurité physique et logique** de
la machine, relèvent de l'Utilisateur. Le chiffrement au repos protège un fichier **dérobé
ou copié**, **non** une session compromise en cours d'exécution, et **n'offre aucune
récupération** de la phrase secrète.

## 7. Autorité de contrôle

En France, l'autorité de contrôle compétente est la **Commission nationale de
l'informatique et des libertés (CNIL)**. L'Utilisateur, en sa qualité de responsable de
traitement, est l'**interlocuteur** de l'autorité de contrôle pour les traitements qu'il
réalise.

## 8. Contact

Cette politique étant **informative** (l'Éditeur ne traitant aucune donnée), aucune demande
d'exercice de droits ne peut être satisfaite par l'Éditeur. Pour toute **question relative
au présent document** : **open-omniscience@ideotion.com**.

---

*Documents liés : [CGU](CGU.md) · [Mentions légales](MENTIONS_LEGALES.md) · [Charte d'usage](CHARTE_USAGE.md) · [Index](README.md). Voir aussi [`../SECURITY.md`](../SECURITY.md) et [`../ETHICS.md`](../ETHICS.md).*
