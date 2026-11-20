<!-- fr: Translation of docs/ETHICS.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 50 of 50 headings. Corrections are welcome as a pull request. -->

# Lignes directrices éthiques d'Open Omniscience

> **État (revérifié le 2026-10-08) :** le logiciel est une **alpha** fonctionnelle et testée
> (`v0.5.0` — voir le README du dépôt pour ce qui fonctionne aujourd'hui ; la formulation de l'époque 0.0.9 ci-dessous est
> conservée comme trace historique du moment où ces lignes directrices sont entrées en vigueur). Les premières versions portaient ici un
> bandeau « non fonctionnel » ; cela a cessé d'être vrai et le bandeau a été retiré —
> ces lignes directrices sont **en vigueur dès maintenant**, et non une référence pour l'avenir.
> *Note historique :* les toutes premières versions conceptuelles (antérieures à 0.0.4) partaient
> du copieur de sites web HTTrack ; la base de code actuelle est une réécriture complète et
> ne partage aucun code avec lui.

Ce document expose les **principes éthiques, les exigences de conformité et les bonnes pratiques** pour l'utilisation d'Open Omniscience et la contribution au projet. Le respect de ces lignes directrices est **obligatoire** pour tous les utilisateurs et développeurs.

Open Omniscience s'inscrit dans la **Charte de Munich**, ensemble de principes fondateurs pour les journalistes adopté en 1971. Ces principes sont intégrés ci-dessous pour guider l'usage éthique de cette plateforme.

---

## 📜 Charte de Munich : Déclaration des devoirs et des droits

### Préambule
Le droit à l'information, à la libre expression et à la critique est une des libertés fondamentales de tout être humain. Tous les droits et devoirs de ceux qui utilisent Open Omniscience découlent du droit du public à connaître les faits et les opinions. La responsabilité des utilisateurs vis-à-vis du public prime toute autre responsabilité, en particulier à l'égard de leurs employeurs et des pouvoirs publics. La mission d'information comporte nécessairement des limites que les utilisateurs eux-mêmes s'imposent spontanément. Tel est l'objet de la déclaration des devoirs formulée ci-dessous.

Un utilisateur d'Open Omniscience ne peut respecter ces devoirs dans l'exercice de son usage que si les conditions concrètes de l'indépendance et de la dignité professionnelle sont réalisées. Tel est l'objet de la déclaration des droits qui suit.

---

### 📋 Déclaration des devoirs
Les devoirs essentiels des utilisateurs d'Open Omniscience engagés dans la recherche, la rédaction et l'analyse de l'information sont :

1. **Respect de la vérité :**
   Respecter la vérité, quelles qu'en puissent être les conséquences pour soi-même, et ce, en raison du droit que le public a de connaître la vérité.

2. **Défendre la liberté de l'information :**
   Défendre la liberté de l'information, du commentaire et de la critique.

3. **Vérifier les sources :**
   Ne publier que les informations dont l'origine est connue ; ne pas supprimer les informations essentielles et ne pas altérer les textes et les documents.

4. **Méthodes loyales :**
   Ne pas user de méthodes déloyales pour obtenir des informations, des photographies et des documents.

5. **Respect de la vie privée :**
   S'obliger à respecter la vie privée des personnes.

6. **Rectifier les inexactitudes :**
   Rectifier toute information publiée qui se révèle inexacte.

7. **Secret professionnel :**
   Garder le secret professionnel et ne pas divulguer la source des informations obtenues confidentiellement.

8. **Éviter les fautes professionnelles :**
   Tenir pour fautes professionnelles graves :
   - le plagiat ;
   - la calomnie, la diffamation, les accusations sans fondement ;
   - l'acceptation d'un avantage quelconque en raison de la publication ou de la suppression d'une information.

9. **Séparation d'avec la publicité et la propagande :**
   Ne jamais confondre l'usage d'Open Omniscience avec celui de la vente publicitaire ou d'activités de propagande, et n'accepter aucune consigne, directe ou indirecte, des annonceurs.

10. **Résister aux pressions :**
    Refuser toute pression et n'accepter de directives que de personnes responsables attachées à l'usage éthique de la plateforme.

---

### 📜 Déclaration des droits

Les utilisateurs d'Open Omniscience revendiquent :

1. **Libre accès à l'information :**
   Le libre accès à toutes les sources d'information et le droit d'enquêter librement sur tous les faits qui conditionnent la vie publique. Le secret des affaires publiques ou privées ne peut en ce cas être opposé aux utilisateurs que par exception et en vertu de motifs clairement exprimés.

2. **Refuser une subordination contraire à l'éthique :**
   Le droit de refuser toute subordination qui serait contraire à la ligne générale d'Open Omniscience, ainsi que toute subordination que cette ligne n'impliquerait pas clairement.

3. **Conscience et conviction :**
   Un utilisateur ne peut être contraint d'accomplir un acte ou d'exprimer une opinion contraire à ses convictions ou à sa conscience.

4. **Transparence dans la prise de décision :**
   La communauté doit être informée de toute décision importante de nature à influer sur le projet. Elle doit au moins être consultée avant toute décision définitive sur l'ensemble des questions touchant à l'orientation du projet.

5. **Juste rétribution et indépendance :**
   Compte tenu de leurs fonctions et de leurs responsabilités, les contributeurs ont droit à une reconnaissance et à des conditions qui assurent la sécurité matérielle et morale de leur travail, ainsi que leur indépendance économique.

---

## 🌍 Principes fondamentaux d'Open Omniscience

1. **Respect des conditions des sources :** toujours respecter les directives `robots.txt` et les conditions d'utilisation des sites web collectés.
2. **Limitation de débit :** le chemin de récupération unique (`EthicalFetcher`) impose un intervalle
   minimal entre requêtes par hôte et prend un verrou par hôte, de sorte qu'une seule requête vers un hôte
   donné soit en cours à un instant donné.
   - Par défaut : **1 requête par seconde et par hôte** — le `min_interval_s` de
     `EthicalFetcher`, défini à partir de la variable d'environnement `OO_FETCH_MIN_INTERVAL`.
   - Lorsque le `robots.txt` d'un hôte publie un **`Crawl-delay`**, celui-ci est respecté : l'intervalle
     effectif est `max(min_interval, Crawl-delay)`.
   - (Le `rate_limit_ms` par source dans `sources.yml` est un champ de données, **non** relié à
     l'intervalle du récupérateur ; ce sont les deux leviers ci-dessus qui limitent réellement le débit.)
3. **Transparence :** l'activité de récupération est enregistrée localement, pour l'examen propre de
   l'opérateur — verdicts par source et par flux dans `data/source_preflight.jsonl` et
   `data/feed_preflight.jsonl`, résultats des tests de terrain dans `data/field_test.jsonl`, et
   erreurs de l'application dans `data/app_errors.jsonl`. Ces fichiers restent sur la machine et sont regroupés,
   **sur clic uniquement**, dans le **paquet de débogage** de Paramètres → diagnostics — jamais
   transmis automatiquement. (Il n'existe pas de `audit/scrape_log.csv` ; c'était une conception initiale
   que la posture local d'abord et sans télémétrie a remplacée.)
4. **Minimisation des données :** ne collecter et ne stocker que les données nécessaires aux fonctions essentielles de la plateforme (URL, titre, contenu, métadonnées).
5. **Usage non malveillant :** Open Omniscience ne doit pas être utilisé pour :
   - le spam ou le harcèlement ;
   - des activités illégales (par ex. piratage informatique, violation du droit d'auteur) ;
   - une exploitation commerciale sans autorisation.
6. **Identification par User-Agent :** utiliser une chaîne User-Agent claire et identifiable. Le robot
   envoie `OpenOmniscienceBot/{version} (+https://github.com/ideotion/Open-Omniscience; ethical research crawler)`
   (les récupérations protégées/routées via Tor envoient à la place un UA de navigateur générique, pour se fondre dans la masse).
7. **Modération par IP :** éviter les rafales de requêtes depuis une même IP. Respecter l'usage raisonnable des serveurs.

---

## ✅ Liste de contrôle de conformité

Avant de collecter une nouvelle source, vérifiez les points suivants :
- [ ] Le domaine ne figure **pas** dans la [liste des sites à ne pas collecter](#liste-des-sites-à-ne-pas-collecter).
- [ ] Le fichier `robots.txt` autorise la collecte (vérifier [https://{domain}/robots.txt](https://{domain}/robots.txt)).
- [ ] La source n'exige **pas** d'authentification et la collecte ne contourne pas de paywall.
- [ ] Les limites de débit sont configurées pour éviter **plus d'1 requête par seconde** par défaut (à ajuster pour les domaines sensibles).
- [ ] La chaîne User-Agent identifie Open Omniscience (`OpenOmniscienceBot/{version}`).
- [x] Les verdicts de récupération sont enregistrés localement (`data/*_preflight.jsonl`), mis à disposition
  sur clic via le paquet de débogage des Paramètres — jamais transmis automatiquement.

---

## 🚫 Liste des sites à ne pas collecter

Cette liste est une **recommandation à l'opérateur**, et non une liste de blocage appliquée mécaniquement : l'application
n'embarque pas de blocage codé en dur de ces domaines. La protection au niveau du code est le **robots.txt
en échec fermé** dans le chemin unique `EthicalFetcher` — une source dont le `robots.txt` ne peut pas
être récupéré ou n'autorise pas clairement l'URL est refusée, et non collectée. Les opérateurs doivent
néanmoins faire preuve de discernement et éviter les catégories ci-dessous lorsqu'ils ajoutent des sources :

### Contenus payants


### Plateformes de réseaux sociaux


### Données privées ou sensibles
- Bases de données gouvernementales (par ex. `*.gov`, `*.mil`, sauf si explicitement publiques)
- Dossiers médicaux (par ex. `*.health`, `*.medical`)
- Données financières (par ex. `*.bank`, `*.finance`, sauf si publiques)
- Référentiels de données personnelles (par ex. `*.personal`, `*.private`)

### Restrictions techniques
- Domaines à **limitation de débit agressive** (par ex. `github.com`, `stackoverflow.com`).
- Domaines qui **bloquent les robots de collecte** (par ex. sites protégés par `cloudflare.com` sans contournement).
- **Sources accessibles uniquement par API** (par ex. `twitter.com/api`, `reddit.com/api` — utilisez plutôt les API officielles).

> **Remarque :** cette liste n'est pas exhaustive. Les utilisateurs doivent faire preuve de **diligence raisonnable** et d'**esprit critique** lorsqu'ils ajoutent de nouvelles sources. En cas de doute, **ne collectez pas**. 

---

## 📊 Audit et responsabilité

L'activité de récupération est enregistrée **localement**, pour l'examen propre de l'opérateur, et n'est partagée
**que sur clic** — jamais transmise automatiquement (aucune télémétrie ; local d'abord par conception). Le
mécanisme réel (la conception initiale `audit/scrape_log.csv` a été remplacée par celui-ci) :

- **Verdicts de pré-vérification** — les résultats d'accessibilité/robots/transport par source et par flux
  sont ajoutés à `data/source_preflight.jsonl` et
  `data/feed_preflight.jsonl` (chaque ligne : horodatage, source/domaine, le verdict tenant compte
  du transport, et la raison honnête). Ils alimentent l'expérience « Réessayer les flux en échec » et les
  verdicts par flux des Indices/marchés.
- **Résultats des tests de terrain** — lorsque le mode test de terrain est actif, les exercices des surfaces de récupération sont
  écrits tels quels dans `data/field_test.jsonl`.
- **Erreurs de l'application** — bornées dans `data/app_errors.jsonl` (les lignes les plus récentes sont conservées).

### Partage pour l'assistance

Il n'existe pas de CSV ni d'`errors.log` téléversé automatiquement. L'opérateur peut constituer un **paquet de débogage**
(Paramètres → diagnostics) qui regroupe les journaux JSONL ci-dessus ainsi que les diagnostics mots-clés/réseau ;
il est écrit sur le disque et partagé uniquement par une action explicite de l'opérateur.
C'est le protocole du mainteneur : parcourir l'application en cliquant, puis remettre le paquet.

---

## 🔒 Vie privée et protection des données

- **Aucun suivi des utilisateurs :** Open Omniscience ne collecte ni ne stocke :
  - les adresses IP des utilisateurs
  - les historiques de recherche
  - les données personnelles
- **Local uniquement :** toutes les données restent sur la machine de l'utilisateur. Aucune dépendance au cloud par défaut.
- **Chiffrement au repos (activé par défaut) :** les nouveaux corpus sont créés **chiffrés** avec
  SQLCipher, protégés par une phrase de passe que l'utilisateur choisit au premier lancement. Utiliser une base
  de données **en clair** est un choix explicite de désactivation qui exige de confirmer par saisie le
  risque énoncé. Il n'existe **aucune récupération** d'une phrase de passe oubliée (le corpus est
  reconstituable en recollectant, donc aucune clé de récupération ni seconde surface de déchiffrement n'est
  ajoutée). Le modèle de menace est une machine saisie ou copiée qui est **éteinte** — et non une
  session compromise déjà en cours d'exécution (voir `SECURITY.md`).
- **Conformité au RGPD :** en cas de collecte de sources basées dans l'UE :
  - anonymiser les données personnelles (par ex. noms, adresses e-mail) dans le contenu stocké ;
  - respecter le droit à l'effacement (supprimer les données sur demande).

---

## 🌍 Considérations juridiques

- **Droit d'auteur :** respectez le droit d'auteur. Ne collectez et ne stockez du contenu que pour :
  - une analyse **personnelle et non commerciale** ;
  - un **usage équitable** (fair use : par ex. critique, commentaire, recherche) ;
  - des **finalités transformatives** (par ex. agrégation à des fins de journalisme d'investigation).
- **Conformité au RGPD :** en cas de traitement de données de citoyens de l'UE :
  - minimiser la collecte de données personnelles ;
  - offrir aux personnes un moyen de demander la suppression de leurs données.
- **Juridiction :** les utilisateurs sont responsables du respect des lois de leur juridiction, notamment :
  - le **Computer Fraud and Abuse Act (CFAA)** (États-Unis)
  - le **Règlement général sur la protection des données (RGPD)** (UE)
  - les **lois sur le droit d'auteur** (selon les pays)

---

## 🛡️ Garde-fous techniques

Pour prévenir les abus et garantir une collecte éthique, Open Omniscience met en œuvre les garde-fous suivants :

1. **Limitation de débit :**
   - Par défaut : 1 requête par seconde et par hôte (`min_interval_s`, à partir de `OO_FETCH_MIN_INTERVAL`).
   - Le `Crawl-delay` du robots d'un hôte est respecté lorsqu'il est plus long ; une seule requête par hôte à la fois.

2. **Respect de robots.txt :**
   - Vérifie automatiquement `robots.txt` avant toute collecte.
   - Respecte les directives `Disallow`.

3. **Identification par User-Agent :**
   - Envoie `OpenOmniscienceBot/{version} (+https://github.com/ideotion/Open-Omniscience; ethical research crawler)`.
   - Les récupérations protégées (routées via Tor) envoient un UA de navigateur générique afin de ne pas être distinguées.

4. **Gestion des erreurs :**
   - Relance les requêtes échouées avec un délai d'attente exponentiel.
   - Journalise toutes les erreurs pour examen.

5. **Détection des doublons :**
   - Utilise la canonicalisation des URL et le hachage du contenu pour éviter les collectes redondantes.

6. **Pistes d'audit :**
   - Journalise toutes les activités de collecte, par souci de transparence et de responsabilité.

---

## 📐 Mesures honnêtes — aucun score fabriqué

Honnêteté par construction : l'application ne présente jamais de **score composite de confiance / qualité /
crédibilité**. Chaque signal qu'elle calcule porte sa méthode, une mise en garde et son
*n* ; une carte qui tenterait de livrer un score agrégé est rejetée mécaniquement par le schéma
de carte. Les colonnes de score dormantes (`credibility_score`, `political_bias`) restent
à NULL et ne sont jamais sérialisées dans aucune réponse de l'API.

**Une exemption délibérée et étroite — `reliability_score`.** Ce champ `1–10` par source
est une **métadonnée de provenance déclarée par l'opérateur** : un nombre que *vous* (l'opérateur)
fixez par source via la configuration ou un import CSV. Il n'est **jamais calculé, jamais attribué par défaut
et jamais dérivé des données des articles** par l'application — l'ancienne valeur par défaut fabriquée `=5`
a été supprimée (mise à NULL par la migration `f4b5c6d7e8a9`). Parce qu'il s'agit de votre propre
affirmation (et non d'un verdict fabriqué par l'outil), il est exposé dans la liste des sources
et étiqueté **« fixé par l'opérateur, non calculé »** partout où il apparaît ; une carte de briefing
ne peut toujours jamais le présenter comme un score. Un invariant du dépôt
(`tests/test_repo_invariants.py::test_reliability_score_is_operator_set_never_computed`)
le maintient ainsi, afin qu'il ne puisse pas devenir discrètement un verdict de qualité calculé.

---

## 📢 Signaler des violations

Si vous constatez ou soupçonnez un usage contraire à l'éthique d'Open Omniscience :
1. **Arrêtez** immédiatement l'activité en infraction.
2. **Documentez** l'incident (par ex. captures d'écran, journaux, horodatages).
3. **Signalez-le** aux mainteneurs via :
   - [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues) (pour les signalements publics)
   - E-mail : `open-omniscience@ideotion.com` (pour les signalements sensibles)

---

## 📅 Révision et mises à jour

Ce document sera **régulièrement révisé et mis à jour** pour tenir compte :
- des nouveaux défis éthiques (par ex. contenus générés par IA, hypertrucages) ;
- des exigences légales (par ex. évolutions du droit d'auteur ou des lois sur la protection des données) ;
- des retours de la communauté (par ex. signalements d'abus ou suggestions d'amélioration).

### Historique des versions
| Version | Date       | Modifications                                                           |
|---------|------------|-------------------------------------------------------------------------|
| 1.0     | 2026-05-07 | Version initiale. Ajout de la liste des sites à ne pas collecter, de la journalisation d'audit et des notes RGPD. |
| 1.1     | 2026-05-07 | Ajout de l'identification par User-Agent, de la modération par IP et des garde-fous techniques. |

---

## 📌 Bonnes pratiques pour les contributeurs

1. **Tester de manière éthique :**
   - Testez toujours la collecte à petite échelle avant de passer à l'échelle.
   - Utilisez `localhost` ou des environnements de préproduction lorsque c'est possible.

2. **Documenter les sources :**
   - Ajoutez des commentaires dans `sources.yml` expliquant pourquoi une source est incluse ou exclue.
   - Notez toute exigence de collecte particulière (par ex. sélecteurs personnalisés).

3. **Respecter les demandes de retrait :**
   - Si une source demande à être retirée, obtempérez immédiatement.
   - Ajoutez le domaine à la liste des sites à ne pas collecter.

4. **Minimiser l'impact :**
   - Collectez pendant les heures creuses lorsque c'est possible.
   - Mettez les réponses en cache pour éviter de redemander le même contenu.

5. **Rester à jour :**
   - Vérifiez régulièrement les modifications de `robots.txt`.
   - Surveillez les évolutions juridiques (par ex. nouvelles lois sur le droit d'auteur).

---
**À retenir :** la collecte éthique n'est pas seulement une obligation légale — c'est une **responsabilité morale**. En utilisant Open Omniscience, vous vous engagez à respecter ces principes.

---

# Conformité, licences et mentions de tiers

Le complément juridique et d'attribution des principes éthiques ci-dessus.

**Dans cette partie :**
- [Guide de conformité à la GPLv3](#guide-de-conformité-à-la-gplv3)
- [Mentions et attributions de tiers](#mentions-et-attributions-de-tiers)


---

## Guide de conformité à la GPLv3

Cette section décrit la conformité d'Open Omniscience à la licence publique générale GNU
version 3 (GPLv3). Elle s'applique au logiciel fonctionnel tel qu'il est livré.

---

### 📜 Licence d'Open Omniscience

**Licence :** GNU General Public License version 3 (GPLv3)  
**Copyright :** © 2026 Ideotion  
**Fichier de licence :** [LICENSE](../LICENSE)

Open Omniscience est entièrement placé sous GPLv3, qui accorde aux utilisateurs les
libertés suivantes (le logiciel est une pré-alpha fonctionnelle et testée — elles s'appliquent dès maintenant) :

1. **Liberté 0 :** la liberté d'exécuter le programme, pour tous les usages
2. **Liberté 1 :** la liberté d'étudier le fonctionnement du programme et de le modifier
3. **Liberté 2 :** la liberté de redistribuer des copies
4. **Liberté 3 :** la liberté de distribuer des versions modifiées

---

### ✅ Liste de contrôle de conformité à la GPLv3

#### Pour le projet Open Omniscience

- [x] **Fichier de licence** : texte intégral de la GPLv3 inclus dans [LICENSE](../LICENSE)
- [x] **Disponibilité du code source** : tout le code source est publiquement disponible dans ce dépôt
- [x] **Mentions de copyright** : les modules source portent une mention `Copyright (C) 2026 Ideotion` ;
  le fichier [LICENSE](../LICENSE) du projet régit l'œuvre dans son ensemble
- [x] **En-têtes de licence** : la plupart des modules source portent un en-tête de type SPDX `GPL-3.0-or-later`
  (une poignée de marqueurs de paquet `__init__.py` vides et quelques petits modules n'en ont
  pas). La GPLv3 n'exige **pas** d'en-tête par fichier — le fichier [LICENSE](../LICENSE) fait
  foi pour l'ensemble de l'œuvre ; les mentions par module sont une courtoisie, et non l'affirmation
  que chaque fichier en porte une
- [x] **Aucune restriction supplémentaire** : aucune restriction au-delà de la GPLv3 n'est imposée
- [x] **Versions modifiées** : toutes les modifications portent des mentions bien visibles (section 5a)
- [x] **Informations d'installation** : sans objet (ce n'est pas un « produit utilisateur » au sens de la GPLv3)

---

### 📦 Conformité de la distribution

#### Distribution du code source

Lorsque vous distribuez le code source d'Open Omniscience :

1. ✅ **Inclure le fichier LICENSE** : le texte intégral de la licence GPLv3 doit être inclus
2. ✅ **Inclure ETHICS.md** : les attributions de tiers doivent être incluses
3. ✅ **Préserver les en-têtes** : tous les fichiers source doivent conserver leurs en-têtes GPLv3
4. ✅ **Préserver les copyrights** : toutes les mentions de copyright doivent être conservées
5. ✅ **Documenter les modifications** : toute modification doit être documentée

#### Distribution binaire

Lorsque vous distribuez Open Omniscience sous forme binaire :

1. ✅ **Inclure le code source** : vous devez fournir la « Source correspondante » (section 6)
2. ✅ **Inclure LICENSE** : le texte intégral de la GPLv3 doit être inclus
3. ✅ **Inclure ETHICS.md** : les attributions de tiers doivent être incluses
4. ✅ **Documenter les modifications** : toute modification doit être documentée
5. ✅ **Aucune restriction supplémentaire** : impossible d'ajouter des restrictions au-delà de la GPLv3

#### Conformité pour les produits utilisateur

Si Open Omniscience est distribué au sein d'un produit utilisateur (appareil grand public) :

1. ✅ **Informations d'installation** : vous devez fournir les informations permettant d'installer des versions modifiées (section 6)
2. ✅ **Disponibilité du code source** : vous devez fournir la Source correspondante
3. ✅ **Pas de tivoïsation** : vous ne pouvez pas empêcher les utilisateurs d'installer des versions modifiées

**Remarque :** Open Omniscience n'est pas lui-même un produit utilisateur, mais si vous l'intégrez dans un tel produit, ces exigences s'appliquent.

---

### 🔍 Étapes de vérification

#### Pour les développeurs

1. **Vérifier les en-têtes de licence**
   ```bash
   grep -r "GNU General Public License" src/ tests/ package/ scripts/
   ```

2. **Vérifier le fichier LICENSE**
   ```bash
   head -5 LICENSE
   ```

3. **Consulter le fichier des mentions**
   ```bash
   cat ETHICS.md
   ```

4. **Vérifier l'absence de code propriétaire**
   ```bash
   # Check for any non-GPLv3 licensed code in active project
   find . -path "./.git" -prune -o -path "./archive" -prune -o -type f -print
   ```

#### Pour les utilisateurs

1. **Vérifier la licence**
   ```bash
   cat LICENSE | head -5
   ```

2. **Consulter les attributions**
   ```bash
   cat ETHICS.md
   ```

---

### 📝 Questions fréquentes sur la conformité

#### Q : Puis-je utiliser Open Omniscience à des fins commerciales ?
**R :** Oui ! La GPLv3 autorise l'usage commercial. Toutefois, toute version modifiée que vous distribuez doit également être placée sous GPLv3, et vous devez en fournir le code source.

#### Q : Puis-je utiliser Open Omniscience dans un logiciel propriétaire ?
**R :** Non. La GPLv3 exige que les œuvres dérivées soient elles aussi placées sous GPLv3. Vous ne pouvez pas intégrer Open Omniscience dans une application propriétaire à code fermé.

#### Q : Dois-je publier mes modifications ?
**R :** Seulement si vous les distribuez. Si vous modifiez Open Omniscience pour votre propre usage sans le distribuer, vous n'avez pas à publier vos modifications.

#### Q : Qu'en est-il des dépendances Python ?
**R :** Les dépendances Python (FastAPI, SQLAlchemy, etc.) sont des œuvres distinctes, sous leurs propres licences. La licence GPLv3 d'Open Omniscience ne les affecte pas. Voir [ETHICS.md](ETHICS.md) pour plus de détails.

#### Q : Qu'en est-il des données que je collecte ?
**R :** La licence GPLv3 s'applique uniquement au logiciel Open Omniscience lui-même, et non aux données que vous collectez. Il vous incombe de respecter le droit d'auteur et les conditions d'utilisation des sites web que vous collectez.

---

### 📞 Signaler un problème de conformité

Si vous avez des questions ou des préoccupations concernant la conformité à la GPLv3 :

- **E-mail :** open-omniscience@ideotion.com
- **GitHub :** https://github.com/ideotion/Open-Omniscience
- **GitHub Issues :** https://github.com/ideotion/Open-Omniscience/issues

---

### 📚 Ressources

- [Texte intégral de la licence GPLv3](../LICENSE)
- [Site officiel de la GNU GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)
- [FAQ de la GNU GPLv3](https://www.gnu.org/licenses/gpl-faq.html)
- [Mentions de tiers](ETHICS.md)

---

**Dernière mise à jour :** 2026-06-14


---

## Mentions et attributions de tiers

Cette section contient les mentions et attributions relatives aux logiciels et
bibliothèques de tiers utilisés par Open Omniscience. (*Note historique :* les versions
conceptuelles antérieures à 0.0.4 partaient de HTTrack ; la base de code actuelle est une réécriture complète et
il ne reste aucun code de HTTrack.)

---

### 📦 Dépendances Python

Open Omniscience **utilise** les paquets Python suivants, chacun sous sa propre
licence. La liste de référence, à source unique, est [`pyproject.toml`](../pyproject.toml) ;
exécutez `pip show <package>` (ou `pip-licenses`) pour confirmer la licence de toute
version installée. **Chaque dépendance est un logiciel libre (FOSS) compatible avec la GPLv3** — c'est une
condition d'inclusion (voir l'invariant « FOSS uniquement » dans `docs/DESIGN.md`).

**Cœur (toujours installé) :**

| Paquet | Licence | Rôle |
|---------|---------|---------|
| FastAPI | MIT | Framework d'API web |
| Uvicorn | BSD-3-Clause | Serveur ASGI |
| Jinja2 | BSD-3-Clause | Gabarits côté serveur |
| SlowAPI | MIT | Limitation de débit |
| Prometheus Client | Apache-2.0 | Point de terminaison de métriques |
| SQLAlchemy | MIT | ORM de base de données |
| Alembic | MIT | Migrations de schéma |
| sqlcipher3 | Zlib/BSD-style | Chiffrement SQLCipher au repos |
| Requests | Apache-2.0 | Client HTTP (récupérateur éthique) |
| httpx | BSD-3-Clause | Client HTTP |
| BeautifulSoup4 | MIT | Analyse HTML |
| lxml | BSD-3-Clause | Analyse XML/HTML |
| feedparser | BSD-2-Clause | Analyse RSS/Atom |
| trafilatura | Apache-2.0 | Extraction d'articles |
| Pydantic | MIT | Validation des données |
| PyYAML | MIT | Analyse de la configuration |
| Bleach | Apache-2.0 | Assainissement HTML |
| bcrypt | Apache-2.0 | Primitive de hachage de mots de passe |
| defusedxml | PSF-2.0 | Durcissement face au XML non fiable (dumps Wikipedia) |
| cryptography | Apache-2.0 OR BSD-3-Clause | Signatures Ed25519 + arbres de Merkle |
| Pillow | HPND (MIT-CMU) | EXIF / métadonnées d'images |
| python-dateutil | Apache-2.0 / BSD | Analyse des dates |
| tenacity | Apache-2.0 | Relance / délai d'attente |
| cachetools | MIT | Cache en mémoire |
| orjson | Apache-2.0 OR MIT (avec un composant MPL-2.0) | JSON rapide |
| psutil | BSD-3-Clause | Indicateurs matériels |

**Extras optionnels (installés à la demande) :**

| Extra | Paquets | Licence | Rôle |
|---|---|---|---|
| `analysis` | numpy, pandas, scipy, scikit-learn, statsmodels, networkx | BSD-3-Clause | Statistiques / graphes |
| `analysis` | nltk | Apache-2.0 | Segmentation en mots |
| `analysis` | vaderSentiment | MIT | Sentiment par lexique (anglais uniquement) |
| `nlp` | spaCy | MIT | Chaîne de traitement TAL |
| `crypto` | python-gnupg | LGPL-3.0 | Intégration GPG |
| `pqc` | pqcrypto | MIT | Signatures post-quantiques (ML-DSA) |
| `timestamping` | opentimestamps | LGPL-3.0 | Horodatages ancrés dans Bitcoin |
| `compression` | zstandard, lz4 | BSD | Compression des sauvegardes |

Le LLM local est le binaire **externe Ollama** (MIT), joint via HTTP sur la
boucle locale — aucun poids de modèle ni aucune bibliothèque d'inférence n'est embarqué ou livré.

#### Notes de conformité

- Chaque dépendance est une **œuvre distincte** sous sa propre licence ; la GPLv3 d'Open
  Omniscience ne s'étend pas à elle, et sa licence ne restreint pas
  Open Omniscience.
- Toutes les licences listées sont **permissives ou à copyleft faible, et compatibles avec la GPLv3**
  (les extras sous LGPL-3.0 `python-gnupg`/`opentimestamps`, ainsi que le composant MPL-2.0
  d'`orjson`, sont chacun compatibles avec la GPL-3.0). Le caractère libre (FOSS) et la compatibilité GPLv3 sont une
  condition d'inclusion impérative.
- Les utilisateurs doivent respecter la licence propre à chaque dépendance ; `pip show <pkg>`
  l'affiche.

---

### 📄 Polices et icônes

| Ressource | Licence | Source |
|----------|---------|--------|
| Icône du projet | MIT (originale) | Incluse dans le projet |
| Polices embarquées — Inter, Outfit, Manrope, JetBrains Mono, Source Serif 4, Cantarell | SIL Open Font License 1.1 | `src/static/fonts/` (chacune avec son `OFL-*.txt`) |

### 📦 Données et ressources embarquées

Ces ressources non logicielles sont intégrées au dépôt sous leurs propres licences.
Elles sont enregistrées dans `configs/external_artifacts.yml` (fraîcheur et attribution y sont suivies).

| Ressource | Licence | Attribution / remarques |
|-------|---------|---------------------|
| Polices (Inter · Outfit · Manrope · JetBrains Mono · Source Serif 4 · Cantarell) | SIL OFL 1.1 | `src/static/fonts/*.woff2`, texte de licence dans `src/static/fonts/OFL-*.txt` |
| Alpine.js v3.14.1 (galerie d'interfaces) | MIT | Intégré localement, épinglé par sha256, sans CDN — `src/static/guis/vendor/alpine.min.js` |
| vaderSentiment 3.3.2 — trois méthodes de l'analyseur adaptées pour un temps linéaire | MIT | **Copyright (c) 2016 C.J. Hutto** ; la mention est reproduite dans `src/analytics/vader_linear.py`, qui ne s'exécute que sur le fichier exact contre lequel il a été vérifié (épinglé par sha256) |
| DB-IP IP-to-Country Lite (géolocalisation hors ligne) | CC BY 4.0 | **Attribution requise :** « IP geolocation by DB-IP (https://db-ip.com) — CC BY 4.0 » — `src/geo/data/dbip_country_lite.csv.gz` |
| stopwords-iso (listes de mots vides multilingues) | MIT | `configs/stopwords_iso/*.txt` |
| Natural Earth (littoraux + polygones des pays) | Domaine public | `src/static/world_outline.json`, `src/static/world_countries.json` |

---

### 📝 Sources de données

Open Omniscience agrège des données provenant de diverses sources d'information. Les utilisateurs sont responsables de :

1. respecter le **droit d'auteur** du contenu collecté
2. se conformer aux **conditions d'utilisation** de chaque site web
3. suivre les directives **robots.txt**
4. adhérer aux lignes directrices de **collecte éthique** (voir [ETHICS.md](ETHICS.md))

**Remarque :** la licence GPLv3 d'Open Omniscience ne s'applique **pas** aux données collectées au moyen du logiciel. Les utilisateurs sont seuls responsables de veiller à ce que leur usage des données collectées respecte l'ensemble des lois et règlements applicables.

---

### 🔍 Vérification

Pour vérifier la conformité aux licences de tiers :

1. **Dépendances Python** : exécutez `pip list` pour voir tous les paquets installés et leurs licences
2. **Code source** : tout le code source d'Open Omniscience est disponible dans ce dépôt

---

### 📞 Contact

Pour toute question sur les licences de tiers ou la conformité :
- **E-mail :** open-omniscience@ideotion.com
- **GitHub :** https://github.com/ideotion/Open-Omniscience

---

**Dernière mise à jour :** 2026-06-14
