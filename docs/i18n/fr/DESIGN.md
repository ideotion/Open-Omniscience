<!-- fr: Translation of docs/DESIGN.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 68 of 68 headings. Corrections are welcome as a pull request. -->

# Conception et synthèse produit

Ce qu'est l'application et ce qu'elle n'est pas, où vit désormais chacun des « piliers » d'origine, le raisonnement de conception de l'interface graphique et la stratégie d'analyse de contenu. La référence de conception unique.

## Sommaire
- [Open-Omniscience — Synthèse produit (ce que l'application doit faire)](#open-omniscience--synthèse-produit-ce-que-lapplication-doit-faire)
- [Carte des intentions des piliers — où vit désormais la raison d'être de chaque pilier](#carte-des-intentions-des-piliers--où-vit-désormais-la-raison-dêtre-de-chaque-pilier)
- [Refonte de l'interface graphique — « 0.05 »](#refonte-de-linterface-graphique---005)
- [Deux interfaces, un argument — « Console » contre « Desk »](#deux-interfaces-un-argument---console--contre--desk)
- [Stratégie d'analyse de contenu — liens, uniformité et source originale](#stratégie-danalyse-de-contenu--liens-uniformité-et-source-originale)


---

## Open-Omniscience — Synthèse produit (ce que l'application doit faire)

> **Statut :** brouillon soumis à relecture. Ce document rassemble la conception *voulue*, éparpillée dans
> la documentation du dépôt, en une spécification unique, cohérente et dédoublonnée. Il élimine
> délibérément les dérives de version, le discours marketing et les affirmations d'assurance qualité
> invérifiables. Il décrit le **produit cible**, et non le code actuel (en grande partie non fonctionnel).
>
> Marqueurs utilisés :
> - `⚠️ DECIDE:` un point où les documents sources étaient ambigus ou se contredisaient — à vous de trancher.
> - `(P0/P1/P2)` une priorité *suggérée* pour cette capacité (P0 = cœur du MVP, P1 = important, P2 = plus tard).

---

### 0. Contexte de déploiement (RÉSOLU — conditionne tout ce qui suit)

Cette version vise **un environnement précis et un seul utilisateur**. Ces réponses sont désormais
arrêtées et tranchent plusieurs des anciens points `⚠️ DECIDE`.

- **Hôte :** Qubes OS, à l'intérieur d'une **AppVM Debian** (fondée sur un modèle).
- **Python :** **3.13 comme interpréteur par défaut.**
- **Utilisateur :** un **utilisateur principal unique (le propriétaire du projet)** — pas de comptes multi-locataires, pas de RBAC.
- **Surface :** **interface web + API REST liées à `127.0.0.1` uniquement** (boucle locale). Aucune écoute externe.
- **Posture réseau :** local d'abord ; trafic sortant uniquement pendant la collecte et le téléchargement des modèles LLM ; **aucun** trafic entrant.

#### 0.1 Ce que Qubes change à la conception

Qubes n'est pas « simplement Debian ». Son modèle de sécurité et le cycle de vie des AppVM imposent des
contraintes strictes que l'installateur et l'exécution **doivent** respecter :

1. **La persistance du système de fichiers est sélective.** Dans une AppVM, seuls **`/home`, `/usr/local` et `/rw`**
   survivent à un redémarrage ; le système de fichiers racine est **réinitialisé depuis la TemplateVM à chaque démarrage**. Par conséquent :
   - L'application, son environnement virtuel, la base de données, les données collectées, les journaux, la piste d'audit et
     tous les modèles LLM téléchargés **doivent résider sous `/home/user/...`** (recommandé : `/home/user/open-omniscience`).
   - **Les paquets `apt`/système ne persistent *pas*** s'ils sont installés dans l'AppVM. Les dépendances système doivent être
     installées **dans la TemplateVM** (puis l'AppVM redémarrée), ou intégrées via les `bind-dirs` de Qubes.
     L'installateur doit **séparer** : « dépendances système → TemplateVM » et « venv Python + application → `/home` de l'AppVM ».
2. **Aucune hypothèse de racine persistante.** Les modifications de la racine dans l'AppVM disparaissent au redémarrage. Traiter l'AppVM comme :
   `/home` persistant, racine éphémère.
3. **Réseau via une NetVM.** L'AppVM n'accède à Internet qu'à travers le qube réseau/pare-feu qui lui est
   attribué. L'application doit **se dégrader proprement hors ligne** et ne jamais présumer de la connectivité.
4. **Pas de GPU.** Le passage du GPU est irréaliste dans les configurations Qubes courantes → **l'inférence LLM se fait uniquement sur CPU**.
   Par défaut, **petits modèles** (p. ex. `gemma2:2b`, `llama3.2:3b`, `qwen2.5:1.5b`) ; les grands modèles sur option.
5. **L'isolation réseau / la séparation en plusieurs VM est une option *future* de premier plan (pas en v1).** Qubes rend naturel le schéma
   « collecte éthique dans un qube connecté, analyse/stockage dans un qube coffre-fort hors ligne » via **qrexec/qubes-rpc**. La v1
   tourne dans **une seule AppVM** ; l'architecture doit garder une frontière de *récupération* nette pour qu'une séparation ultérieure soit un
   changement de déploiement, pas une réécriture. (Le dépôt contient déjà des vestiges `src/qubes/rpc/` et
   des documents `docs/QUBES_*` — à revoir ou remplacer, pas à croire sur parole.)

#### 0.2 Conséquences de Python 3.13 (résout les conflits de versions de dépendances)

- **La pile principale est compatible 3.13 :** FastAPI, uvicorn, SQLAlchemy 2.x, pydantic 2.x, requests, httpx,
  beautifulsoup4, feedparser, numpy, pandas, scipy, scikit-learn, statsmodels — tous publient des wheels 3.13.
- **Le LLM local n'exige PAS d'apprentissage automatique lourd en Python.** Ollama est un **binaire natif distinct** ; l'application lui parle
  **uniquement en HTTP**. Toutes les capacités LLM fonctionnent sous 3.13 avec seulement `httpx`/`requests` — aucun
  `torch`/`transformers` dans l'application.
- **Les bibliothèques d'apprentissage automatique lourdes sont retirées du cœur.** `torch`, `onnx`/`onnxruntime`, `tensorflow`,
  `pyAudioAnalysis` et la pile de détection d'hypertrucages sont **supprimés** pour la v1 parce qu'ils sont (a) actuellement
  **factices** (le « CNN de détection d'hypertrucages » n'exécute jamais d'inférence), (b) lourds et **limités au CPU ici**, et
  (c) un risque de wheel 3.13 paquet par paquet (`pyAudioAnalysis` n'est plus maintenu ; `igraph`/`leidenalg`/`gensim`
  doivent chacun être vérifiés avant usage). Toute fonctionnalité d'apprentissage automatique future devra justifier son poids et prouver l'existence d'un wheel 3.13.
- **Un seul manifeste de dépendances, épinglé sur 3.13.** Remplacer les six fichiers requirements contradictoires par un unique
  `pyproject.toml` à la racine (`requires-python = ">=3.13"`) + des extras optionnels (`[llm]`, `[analysis]`, `[dev]`).
  Supprimer les commentaires « correctifs » générés par IA et les épinglages impossibles.

#### 0.3 Modèle de sécurité pour un utilisateur local unique (simplifie les P0)

Puisque la seule écoute est la boucle locale et que le seul utilisateur, c'est vous :
- **Authentification :** aucune n'est requise pour la v1 *à condition* que le serveur se lie strictement à `127.0.0.1` et ne soit jamais exposé
  par une règle de pare-feu Qubes. (Un jeton d'API optionnel unique pourra être ajouté plus tard en cas de proxy.) Cela **résout**
  le constat « aucune authentification sur les points d'accès » *pour ce déploiement* — en supprimant l'exposition réseau plutôt qu'en
  ajoutant du RBAC.
- **`/metrics` :** limité à la boucle locale, comme tout le reste.
- **La sûreté de l'installateur reste obligatoire :** aucun `rm -rf` non confirmé, aucun `curl | sh` non vérifié, ne jamais jeter
  la sortie d'erreur du gestionnaire de paquets — ce sont des questions de justesse et de sûreté, utilisateur unique ou non.
- **Ressources front-end embarquées localement** (pas de Google Fonts ni de React via CDN) — indispensable pour le hors-ligne/Qubes et
  pour le principe de confidentialité.

---

### 1. Définition en une phrase

Open-Omniscience est une **plateforme de renseignement open source, locale d'abord, destinée aux journalistes d'investigation**,
qui agrège de manière éthique de nombreuses sources de données mondiales en un **corpus unique, interrogeable, recoupable
et dont la provenance est tracée**, avec une **IA locale** optionnelle pour l'analyse — et où chaque résultat est
conçu pour être **défendable scientifiquement et juridiquement**.

### 2. Pour qui, et pour quelles tâches

**Utilisateur principal :** un journaliste d'investigation, un chercheur ou un analyste — travaillant probablement seul ou dans une
petite rédaction, souvent soucieux de confidentialité (des sources à protéger), parfois dans des environnements restreints
ou isolés du réseau.

**Tâches essentielles à accomplir :**
1. *« Rassembler automatiquement, en un seul endroit, tout ce qui concerne mon enquête à partir de nombreuses sources. »*
2. *« Tout rechercher et tout recouper ensemble — articles, marchés, courriels — pour trouver des liens. »*
3. *« M'aider à comprendre de grands volumes de texte »* (résumer, traduire, extraire des entités) — **sans
   envoyer mes données à qui que ce soit.**
4. *« Me dire quand quelque chose est digne de confiance — ou de méfiance »* (vérifier les médias, signaler les manipulations).
5. *« Prouver d'où cela vient et que je ne l'ai pas altéré »* (provenance pour la publication ou la justice).
6. *« M'alerter quand quelque chose change »* (une source disparaît, un prix flambe, un récit émerge).

### 3. Principes directeurs (les non-négociables)

Ils sont au cœur de l'intention et doivent encadrer chaque fonctionnalité. Lorsque le code actuel en viole un,
c'est un défaut, pas un compromis.

1. **Local d'abord et utilisable hors ligne.** Tourne entièrement sur la machine ou le serveur de l'utilisateur. Doit fonctionner
   sans Internet, sauf pendant la collecte elle-même. Adapté à un usage isolé du réseau (avec données/modèles préchargés).
2. **Respectueux de la vie privée.** Aucune télémétrie. **Aucune donnée utilisateur ne quitte jamais la machine** — en particulier le traitement
   LLM (local via Ollama uniquement). ✅ RÉSOLU (§0) : toutes les ressources front-end (polices, bibliothèques JS) sont
   **embarquées localement** — aucun appel à un CDN — condition indispensable à la posture Qubes/hors ligne.
3. **100 % FOSS.** Tout le code et tous les modèles sont open source. ⚠️ DECIDE: la licence est **GPLv3** à la racine mais
   **AGPL-3.0** dans le Pilier 3 — en choisir une pour tout le projet (l'AGPL est plus stricte pour l'usage en réseau).
4. **Éthique par construction.** Respecter `robots.txt` et les limites de débit, identifier le robot, données publiques uniquement,
   ne jamais contourner un paywall ni utiliser d'identifiants pour collecter. **Échouer *fermé*** — si la conformité ne peut être
   vérifiée, ne pas collecter.
5. **Résultats défendables (scientifiquement et juridiquement).** Chaque résultat analytique porte une incertitude honnête et une
   provenance traçable. **Aucun chiffre fabriqué.** Un score de confiance doit provenir d'une méthode réelle, ou
   ne pas exister. La chaîne de possession doit être réelle (signée, révélant toute altération), pas un simple fichier journal.
6. **Corpus unifié.** Tout ce qui est ingéré — actualités, données financières, matières premières, courriels — vit dans **une seule
   base de données** et peut être **recoupé en une seule requête**. C'est la raison d'être du produit.
7. **La transparence plutôt que l'échec silencieux.** Le système ne doit jamais se dégrader en silence vers un résultat invalide.
   Modèle manquant, source bloquée, dépendance indisponible → **statut visible et explicite**, jamais un
   espace réservé muet.

### 4. Le modèle mental central

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

**La colonne vertébrale (ingestion → stockage unifié → recherche → export) doit être d'une solidité absolue avant tout pilier.**
Les piliers sont des *enrichisseurs* qui lisent dans le stockage partagé et y réécrivent.

---

### 5. Périmètre fonctionnel, par domaine de capacité

#### 5.1 Ingestion des données (P0)
- **Types de sources :** sites d'information (HTML), flux RSS/Atom. Plus tard : API, plateformes sociales, dépôts de fichiers.
  ⚠️ DECIDE: le Pilier 4 mentionne Twitter/X, Reddit, Telegram, Mastodon, S3/SFTP — confirmer lesquels (s'il y en a)
  relèvent du périmètre réel ou de l'aspiration.
- **Collecteur éthique (implémentation unique et partagée) :** vérification de robots.txt (mise en cache, tenant compte de http et https,
  **échec fermé** en cas d'incertitude), limitation de débit par source, User-Agent identifiant, nouvelles tentatives avec temporisation.
  **Une seule récupération par URL** — pas de double récupération, pas de chemin brut de contournement.
- **Dédoublonnage :** fondé sur l'empreinte du contenu et l'URL canonique ; ne jamais stocker deux fois le même article.
- **Normalisation :** extraire de manière fiable le titre, l'auteur, la date de publication, la langue, l'URL canonique et le corps du texte.
  ⚠️ DECIDE: une véritable extraction d'articles de presse exige des règles par site ou une bibliothèque (p. ex. du type trafilatura) ;
  l'approche CSS générique actuelle produit silencieusement « No Title/No Content ». Confirmer l'adoption d'une extraction robuste.
- **Planification et mises à jour incrémentales :** recollecte périodique, ne récupérer que le contenu nouveau ou modifié, reprendre
  les exécutions interrompues.

#### 5.2 Stockage de données unifié (P0)
- **Une seule base de données** contenant tous les types d'entités, avec des **tables de liaison** explicites qui les relient
  (article ↔ instrument financier, article ↔ matière première, article ↔ courriel, article ↔ entité nommée).
- **Champs de provenance sur chaque enregistrement :** source, horodatage de récupération, URL d'origine, empreinte du contenu,
  séparation du brut et du traité.
- **Moteurs :** SQLite pour un usage mono-utilisateur/bureau ; PostgreSQL pour un usage serveur/concurrent.
  ⚠️ DECIDE: confirmer SQLite par défaut + Postgres optionnel (la documentation mentionne les deux ; ainsi que Redis pour le cache —
  dedans ou dehors ?).
- **Journal d'audit :** en ajout seul, **révélant toute altération**, enregistrant chaque ingestion et chaque modification.

#### 5.3 Recherche et consultation (P0)
- **Recherche plein texte** sur l'ensemble du corpus.
- **Opérateurs booléens** (`AND`/`OR`/`NOT`), **expressions entre guillemets** et **parenthèses avec la bonne
  priorité** — implémentés avec une vraie grammaire ou la recherche plein texte native de la base, pas avec des bricolages de chaînes.
- **Filtres structurés :** source, plage de dates, langue, étiquettes/catégorie, entité, type de données.
- **Pagination**, classement des résultats, extrait/surlignage.
- **Export :** CSV et JSON (et ⚠️ DECIDE: formats PDF/rapport ?), fidèle à l'ensemble de résultats filtré.

#### 5.4 Recoupement et corrélation (P1 — l'élément différenciant)
- Pivoter de n'importe quel enregistrement vers les enregistrements liés, tous types confondus (article → entreprises citées → mouvements de prix
  autour de la date de publication → courriels liés).
- **Moteurs de corrélation** (finance/matières premières ↔ actualités) qui font apparaître des relations *candidates* avec une
  **mesure honnête et définie** (en indiquant clairement que corrélation ≠ causalité). Aucune valeur p fabriquée.
- Vue centrée sur l'entité : tout ce que le corpus sait d'une personne, d'une organisation, d'un lieu ou d'un instrument.

#### 5.5 Analyse par LLM local (P1)
- **Moteur d'exécution :** Ollama, entièrement local. Les modèles sont interchangeables ; livrer un petit modèle par défaut raisonnable qui *existe
  vraiment*. ⚠️ DECIDE: le modèle par défaut actuel `gemma4:e2b` et la plupart des modèles listés (Gemma 4, Llama 4, Qwen 3.5)
  sont hallucinés — remplacer le catalogue par de vraies étiquettes (p. ex. `gemma2:2b`, `llama3.2:3b`, `qwen2.5`,
  `phi3`).
- **Capacités :** générer, discuter (avec contexte), extraire (entités/mots-clés/résumés/citations/liens),
  traduire (multilingue), analyser (sentiment/ton/lisibilité ; biais seulement si honnêtement borné),
  synthétiser (résumés, comparaisons, chronologies, rapports), traitement par lots.
- **Se dégrader bruyamment :** si Ollama ou le modèle est absent, le dire — ne jamais renvoyer une fausse analyse.

#### 5.6 Vérification et défense contre la tromperie — *Pilier 3* (P2, périmètre à définir)
- **Intention :** détecter les médias manipulés (hypertrucages image/vidéo/audio), les techniques de propagande, les biais
  cognitifs, les robots et les campagnes coordonnées ; valider les métadonnées (EXIF/ID3) et la cohérence entre modalités.
- ⚠️ DECIDE (important) : aujourd'hui, c'est **factice** — le « CNN de détection d'hypertrucages » n'exécute jamais d'inférence ; les scores
  sont des heuristiques de flou ; la couverture des biais/de la propagande est en grande partie inaccessible ; « précision >95% » est une aspiration.
  En choisir une :
  - **(a) Couper** la criminalistique des médias pour l'instant et ne livrer que ce qui est honnête (la validation des métadonnées/EXIF est réelle
    et utile) ; **(b) Reconstruire** avec de véritables modèles FOSS évalués et une précision publiée ; ou
    **(c) Garder** mais **étiqueter clairement « heuristique expérimentale, pas une preuve ».**
  Ma recommandation : (a) maintenant, (b) plus tard. Une criminalistique fabriquée est le plus grand risque, à lui seul, pour un
  outil de journalisme ou juridique.

#### 5.7 Rigueur scientifique — *Pilier 2* (P1)
- **Intention :** rendre défendables les affirmations quantitatives de la plateforme — vrais tests statistiques, intervalles de
  confiance, évaluation de la reproductibilité et de la lignée, et « relecture par les pairs » via plusieurs LLM locaux qui se contre-vérifient.
- Ce pilier est le plus réellement implémenté (vrais scipy/statsmodels). Le garder, le durcir et en faire le
  **gardien** : tout chiffre que l'application montre à l'utilisateur doit passer par une déclaration honnête de l'incertitude.

#### 5.8 Surveillance et alertes en temps réel — *Pilier 4* (P2)
- **Intention :** surveillance continue des sources ; détection d'anomalies, de tendances et de motifs ; enrichissement par le renseignement sur les menaces ;
  alertes multicanal (courriel/webhook/messagerie) avec règles et escalade.
- ⚠️ DECIDE: les contrôles d'état actuels sont simulés (`sleep; return HEALTHY`) et le renseignement sur les menaces/STIX-TAXII
  n'existe pas. Confirmer le périmètre : une vraie surveillance de la disponibilité des sources + des alertes d'anomalies sur le corpus est
  réalisable et utile ; STIX/TAXII, SMS/Twilio, Slack/Teams sont lourds — dedans ou dehors ?

#### 5.9 Renseignement financier — *Pilier 5* (P2, marqué 0 % dans la documentation)
- **Intention :** collecter les bourses mondiales (OHLC + fondamentaux) à partir de sources web ouvertes (sans API ni paywall),
  détecter fluctuations, motifs et anomalies, et **corréler les mouvements de prix avec l'actualité** dans la base partagée.
- ⚠️ DECIDE: c'est **uniquement de la conception (0 % construit)** malgré du code d'échafaudage versionné. Confirmer qu'il s'agit d'une vraie
  cible et, si oui, de son premier périmètre réaliste (p. ex. une poignée de bourses, OHLC quotidien, corrélation avec les
  articles) plutôt que « plus de 50 bourses / plus de 10 000 entreprises » dès le premier jour. Remarque : une collecte multi-bourses
  robuste sans API est une entreprise vaste et fragile.

#### 5.10 Renseignement sur les terres rares / matières premières — *Pilier 6* (P2, marqué 0 % dans la documentation)
- **Intention :** le même schéma que le Pilier 5 pour les 17 terres rares — prix, production, stocks,
  corrélés aux événements géopolitiques et d'actualité ; avec des prévisions.
- ⚠️ DECIDE: également **uniquement de la conception (0 % construit)**. Confirmer le périmètre et la priorité par rapport au Pilier 5. (Correction nécessaire : le
  calcul des unités pour la normalisation des prix est actuellement faux d'un facteur d'environ 1000×, et les devises ne sont pas converties.)
  ⚠️ DECIDE: la « prévision » est-elle dans le périmètre ? Une prévision honnête, avec incertitude, est difficile ; recommandation : reporter.

#### 5.11 Renseignement sur les courriels et les lettres d'information (P1/P2)
- **Intention :** récupérer depuis IMAP/POP3 et des sources de lettres d'information (Substack/Mailchimp/RSS-vers-courriel), analyser et
  nettoyer, traiter les pièces jointes (PDF/Office/images avec OCR), extraire les entités et les réseaux de communication,
  et **les intégrer au même corpus interrogeable**.
- **La confidentialité et le consentement sont primordiaux ici** (communications privées) : autorisation explicite, stockage chiffré
  des identifiants, minimisation des données, durée de conservation/droit à l'oubli.
- ⚠️ DECIDE: intégrations d'API de lettres d'information (Substack/Mailchimp/etc.) ou simplement IMAP + RSS-vers-courriel pour la v1 ?

#### 5.12 Interface graphique / UX (P0 pour le cœur, P1+ pour les tableaux de bord des piliers)
- **Interface graphique de base :** interface de recherche, navigation dans les résultats, gestion des sources, export, tableaux de bord simples.
- **Tableaux de bord des piliers (plus tard) :** cartes thermiques et graphiques financiers, vues des matières premières, surveillance/alertes, boîte de réception
  des courriels, explorateur de corrélations.
- ✅ RÉSOLU (§0) : **interface web servie par FastAPI à `127.0.0.1:8000` ; l'application de bureau Tkinter est abandonnée**
  (retirer `python3-tk`). S'ouvre dans le navigateur de l'AppVM.
- ✅ RÉSOLU (§0) : le front-end est en **JS natif + bibliothèques embarquées (servies depuis `/static`)** — pas de CDN.
  ⚠️ DECIDE (mineur) : garder des graphiques légers (p. ex. une petite bibliothèque de graphiques embarquée) ou aucun en v1.

#### 5.13 Rapports et résultats défendables (P1)
- Générer des rapports d'enquête qui regroupent les constats **avec leur provenance** (sources, horodatages,
  empreintes, méthodes, incertitude).
- **Chaîne de possession / intégrité :** signature cryptographique + preuve d'altération sur les éléments exportés
  (les modules cryptographiques existent mais ne sont pas branchés). C'est ce qui rend l'affirmation de « recevabilité juridique »
  réelle plutôt que décorative.

---

### 6. Exigences non fonctionnelles

- **Plateforme :** ✅ RÉSOLU (§0) — **l'AppVM Debian de Qubes OS** est la *seule* cible prise en charge pour la v1
  (construite et testée là). Une Debian 13 ordinaire peut fonctionner mais ce n'est pas un objectif ; aucun engagement multiplateforme.
- **Python :** ✅ RÉSOLU (§0) — **3.13**, de manière cohérente dans `pyproject.toml`, `.python-version` et
  toute CI. Abandonner les dépendances dépourvues de wheels 3.13 (voir §0.2).
- **Empreinte d'installation :** un véritable **cœur minimal** (web + base + recherche, léger) séparable des extras
  optionnels (`[llm]`, `[analysis]`). **Un seul** `pyproject.toml` — pas six manifestes contradictoires. L'installateur
  respecte la persistance de Qubes (§0.1) : dépendances système dans la TemplateVM, venv et données dans `/home`.
- **Sécurité :** ✅ RÉSOLU (§0) — utilisateur local unique, **boucle locale uniquement**, donc pas de RBAC. Toujours obligatoire :
  accès à la base uniquement par requêtes paramétrées (supprimer le « nettoyeur » à liste noire), aucun secret dans le code, `/metrics` en boucle locale,
  et un **installateur sûr** (aucun `rm -rf` non confirmé, aucun `curl | sh` non vérifié, ne jamais jeter la sortie d'erreur des paquets).
- **Performances :** E/S non bloquantes pour le travail réseau/LLM ; concurrence bornée ; l'application reste réactive pendant
  la collecte et l'inférence. Hypothèses **CPU uniquement** (pas de GPU dans Qubes). Objectifs définis selon des ressources
  d'AppVM réalistes, pas aspirationnelles.
- **Hors ligne :** toutes les ressources, polices et modèles (téléchargés à l'avance) en local ; procédure documentée pour fonctionner avec la
  NetVM détachée une fois les données et modèles récupérés.
- **Observabilité :** journaux structurés (sous `/home`), contrôles d'état honnêtes, métriques Prometheus en boucle locale —
  reflétant l'état réel.

### 7. Non-objectifs explicites / hors périmètre (proposé — à ajuster)

- Pas un robot d'exploration ni un outil de miroir généraliste (la filiation HTTrack est un vestige ; abandonner ce cadrage).
- Pas un outil de contournement de paywall, de bourrage d'identifiants ni de collecte violant des conditions d'utilisation.
- Pas un produit cloud/SaaS ; aucune API d'IA externe.
- ⚠️ DECIDE: la prévision (5.10), l'ingestion des réseaux sociaux (5.8) et la criminalistique des médias (5.6) sont-elles dedans ou dehors
  pour la première vraie version ?

### 8. Modèle des données, de la provenance et de la défendabilité juridique (transversal)

- Chaque élément stocké : `{source, original_url, fetched_at, content_hash, raw_payload_ref, processing_log}`.
- Chaque résultat dérivé/analytique : `{method, version, inputs_ref, uncertainty/confidence_basis,
  computed_at}` — **la confiance n'est jamais une constante codée en dur.**
- Éléments exportés : optionnellement **signés**, avec un manifeste vérifiable (empreintes + Merkle/GPG) pour qu'un tiers
  puisse confirmer leur intégrité. C'est le sens concret de « Pilier 4 : recevabilité juridique ».

### 9. Décisions (consolidées)

**✅ Résolues par le contexte de déploiement (§0) :**
- **3. Déploiement et modèle de menace** → utilisateur local unique, AppVM Debian de Qubes, boucle locale uniquement, pas de RBAC.
- **7. Interface graphique** → interface web à `127.0.0.1:8000`, JS natif, ressources embarquées localement ; Tkinter abandonné.
- **8. Plateforme/Python** → AppVM Debian de Qubes, Python 3.13, SQLite par défaut (Postgres/Redis **exclus** pour la v1).

**⚠️ Encore ouvertes (à vous de trancher — valeurs par défaut raisonnables proposées) :**
1. **Périmètre du MVP :** *proposé* — d'abord le Cœur fiable seul (Phase 1), puis le LLM. À confirmer.
2. **Stratégie de reconstruction :** *proposé* — récupérer les quelques bonnes parties (modèles de base de données, `ethical_scraper`,
   `async_db`, squelette FastAPI), supprimer les piliers factices, reconstruire le cœur autour d'elles. À confirmer, par opposition à
   une refonte complète à partir de zéro.
4. **Criminalistique des médias (Pilier 3) :** *proposé* — **(a) couper** hypertrucages/propagande/biais pour la v1 (également
   hostiles à 3.13/au CPU), **garder** la vraie validation des métadonnées/EXIF. À confirmer.
5. **Finance (5) et matières premières (6) :** *proposé* — reporter à la Phase 3, puis construire **une seule** verticale fine.
   Laquelle d'abord ?
6. **Courriel :** *proposé* — IMAP + RSS-vers-courriel uniquement pour la v1 ; reporter les intégrations d'API de lettres d'information. À confirmer.
9. **Licence :** GPLv3 ou AGPL-3.0 pour tout le projet — une décision reste nécessaire.
10. **Confirmation du hors-périmètre :** prévision, ingestion des réseaux sociaux, STIX/TAXII, alertes SMS/messagerie —
    *proposés* hors périmètre pour la v1.

### 10. Phasage suggéré (proposition, pas un engagement)

- **Phase 1 — Cœur fiable :** ingestion éthique → stockage unifié (avec provenance) → recherche booléenne/
  plein texte correcte → export → interface web minimale → vrais tests. *Tout le reste désactivé tant que ceci n'est pas au vert.*
- **Phase 2 — LLM local + rigueur scientifique :** brancher Ollama (vrais modèles, dégradation bruyante) ; faire du Pilier 2
  le filtre d'honnêteté de tout chiffre affiché.
- **Phase 3 — Une verticale + corrélation :** choisir **soit** la finance **soit** les matières premières, construire une tranche fine mais
  réelle, démontrer de bout en bout l'expérience de corrélation article↔données.
- **Phase 4 — Surveillance/alertes, courriel, vérification (métadonnées d'abord) :** ajouter les enrichisseurs un par un,
  chacun réellement fonctionnel et testé.
- **Phase 5 — Rapports défendables :** brancher une vraie signature/chaîne de possession dans les exports.

---

### 11. État de l'implémentation (actuel)

Ce qui est construit et testé aujourd'hui, rapporté au périmètre ci-dessus (l'intention est inchangée ; ces
notes indiquent où en est désormais la réalité). Voir les documents de fonctionnalités liés pour le détail.

- **Cœur fiable (5.1–5.3, 5.13) :** ✅ ingestion éthique, stockage unifié avec provenance,
  recherche booléenne FTS5, export CSV/JSON, chaîne de possession signée.
- **Ingestion à grande échelle (5.1) :** ✅ **planificateur** intégré (démarrage/arrêt, intervalle, modes
  rss/crawl/markets) et un **robot d'exploration récursif borné** (*découverte* sur le même domaine,
  robots en échec fermé, plafonds de profondeur/pages) — pas un outil de miroir généraliste (§7 respecté).
- **Interface graphique (5.12) :** ✅ interface web à onglets — Recherche · Ingestion · **Sources & base de données** (statistiques,
  gestion des sources, **couverture mondiale**) · **Marchés** · **Analyses** · Chaîne de
  possession · **Paramètres** (thème + sauvegarde/restauration SQLite). Sans dépendance, hors ligne.
- **Finance et matières premières (5.9, 5.10) :** ✅ verticale fine mais réelle — **règles d'extraction**
  des prix par source, **flux CSV officiels** (FRED→Banque mondiale/EIA), graphiques et
  corrélation prix↔actualités honnête. Calcul des unités corrigé ; chiffres issus uniquement d'une règle vérifiée
  ou d'un CSV importé. Voir [USER_MANUAL.md](USER_MANUAL.md).
- **Couverture mondiale des sources :** ✅ catalogue des marchés intégré + un **générateur dérivé
  des données** (Wikidata CC0) pour les médias d'information **et** les institutions de chaque pays, avec un
  rapport de couverture. Import/export CSV de la liste des sources. Voir
  [ROADMAP.md](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).
- **Recoupement et corrélation (5.4) :** ✅ **analyse des mots-clés et des entités** —
  extraction à l'ingestion, stockage des mentions avec leur contexte, tendances, associations PMI
  (« carte mentale ») et une carte par pays/ville. Voir [USER_MANUAL.md](USER_MANUAL.md).
- **Wikipédia comme source suivie (nouveau) :** 🚧 fondations du suivi des modifications (éditions
  par langue, stockage des différences, signalement des grosses modifications et du révisionnisme, y compris via ORES) — schéma +
  analyseur + signalement faits ; interrogation en direct, onglet et téléchargeur hors ligne à venir. Voir
  [USER_MANUAL.md](USER_MANUAL.md).
- **Vérification (5.6) :** ✅ uniquement les métadonnées/EXIF d'image honnêtes (la criminalistique factice
  reste en quarantaine). **LLM (5.5)**, **surveillance/alertes (5.8)**, **courriel (5.11)** :
  partiels/en file d'attente.

---


---

## Carte des intentions des piliers — où vit désormais la raison d'être de chaque pilier

La conception d'origine organisait la plateforme en six « piliers ». Ces arborescences de piliers
représentaient environ 50 000 lignes que l'application en fonctionnement n'importait jamais — pour l'essentiel uniquement de la conception ou
du code factice. **Leur *intention* a été préservée** : la raison d'être réelle de chaque pilier
est désormais un petit module honnête et testé dans `src/` (ou est explicitement reportée).
Les arborescences de piliers d'origine sont conservées sous `quarantine/pillars/` pour référence et
pour l'historique ; rien n'est supprimé.

| Pilier (intention) | Où vit désormais l'intention | Statut |
|---|---|---|
| **1 — Ingestion des données** (collecte éthique → stockage unifié) | `src/ingest/` (fetcher, extract, pipeline, email) + `src/database/` | ✅ Réel, testé |
| **2 — Rigueur scientifique** (statistiques honnêtes, incertitude) | `src/analysis/` (`statistical_tests`, `confidence_intervals`) + `POST /api/analysis/*` | ✅ **Récupération du vrai code scipy/statsmodels** + ses 60 tests |
| **3 — Défense contre la tromperie** (vérifier les médias) | `src/verification/metadata.py` (métadonnées/EXIF honnêtes) + `POST /api/verify/image-metadata` | ✅ Périmètre honnête. Les détecteurs d'hypertrucages/propagande/biais étaient factices → `quarantine/pillar3_analysis/` |
| **4 — Surveillance + recevabilité juridique** | `src/monitoring/` (vraie disponibilité + anomalies) et `src/reporting/` + `src/crypto/` (preuves signées Merkle + Ed25519) | ✅ Réel, testé |
| **5 — Renseignement financier** | *Reporté.* Le schéma est éprouvé par la réimplémentation du Pilier 6 ; une verticale financière peut réutiliser `src/commodity` + `src/analysis`. | ⏸ Uniquement de la conception à l'origine (0 %) ; pas encore construit |
| **6 — Terres rares / matières premières** | `src/commodity/` (prix, conversion d'unités correcte, **vraie** corrélation scipy, import CSV) + `POST /api/commodities/*` | ✅ Réel, testé |

### Ce qui a été récupéré à cette étape (Pilier 2)
- `src/analysis/statistical_tests.py` — tests t, ANOVA, khi-deux, Pearson/Spearman,
  Mann-Whitney, Wilcoxon, régression, Tukey HSD (scipy/statsmodels). Chaque résultat
  porte la statistique, la valeur p, les degrés de liberté, la taille d'effet et la taille d'échantillon.
- `src/analysis/confidence_intervals.py` — moyennes et proportions (t/normale/Wilson/
  Clopper-Pearson/Agresti-Coull).
- Exposés à `POST /api/analysis/{t-test,correlation,anova,mann-whitney,confidence-interval}`
  pour qu'un journaliste puisse vérifier si un motif dans ses données est réellement significatif.
- Les véritables suites de tests du Pilier 2 ont suivi le code (`tests/test_statistical_tests.py`,
  `tests/test_confidence_intervals.py`).

### Ce qui n'a PAS été récupéré (et pourquoi)
- `peer_review` / `consensus` / `reproducibility` du Pilier 2 — spéculatifs ou superficiels
  (p. ex. la reproductibilité était une grille de moyenne de booléens). Mis de côté ; à relancer avec de vraies
  méthodes si nécessaire.
- Les détecteurs criminalistiques du Pilier 3, la surveillance/le renseignement sur les menaces simulés du Pilier 4, les échafaudages des Piliers
  5/6 — factices ou uniquement de la conception ; les parties honnêtes sont déjà dans `src/`.

### Effet net
Le dépôt reflète désormais ce qui tourne réellement : un cœur actif d'environ 16 000 lignes (plus les
statistiques récupérées), les quelque 50 000 lignes aspirationnelles/factices des piliers étant mises de côté dans
`quarantine/pillars/` au lieu de se faire passer pour des fonctionnalités opérationnelles.


---

## Refonte de l'interface graphique — « 0.05 »

> Une refonte complète de l'interface d'Open Omniscience, raisonnée à partir de l'utilisateur
> vers l'extérieur. Ce document est le *pourquoi* ; `src/static/index.html` est le *quoi*.
> Lisez-le d'abord si vous voulez comprendre (ou contester) les décisions.

---

### 0. La commande, reformulée

Refondre toute l'interface graphique pour une personne précise : **une personne en quête de vérité — un
enquêteur ou une journaliste qui n'*aime* pas particulièrement les ordinateurs**, qui veut comprendre
le monde tel qu'il est vraiment et communiquer ses constats de manière crédible. Le résultat doit être
élégant, beau, adaptable, très personnalisable, simple *et* profond, et assez bon
pour qu'un collègue jetant un œil par-dessus l'épaule dise *« c'est quoi, ça — je peux l'avoir ? »* Il doit respecter ce que le projet est déjà : **mono-utilisateur, limité à la boucle locale,
hors ligne d'abord, sans dépendance, sans télémétrie**, régi par la **Charte de Munich**
(vérité, vérification des sources, vie privée, refus de la propagande).

#### Posture d'ingénierie (et le compromis honnête)

L'interface précédente est un unique `index.html` de 2 200 lignes reliant environ 110 fonctions à environ 150
points d'accès d'API. Ces fonctions *marchent et sont testées*. Une réécriture à partir de zéro aurait
produit une coquille plus jolie avec une forte probabilité de boutons silencieusement cassés — l'exact
contraire d'un outil dont tout l'argument est l'**honnêteté**. Il s'agit donc d'une
**refonte totale de tout ce que l'utilisateur voit et touche** — langage visuel,
mise en page, modèle de navigation, architecture de l'information, dénominations, accueil des nouveaux utilisateurs,
personnalisation, et deux surfaces entièrement nouvelles (un tableau de bord Accueil et un lecteur de
documentation intégré) — construite *au-dessus de la couche de données éprouvée*, chaque identifiant d'élément d'origine
étant conservé pour que rien ne régresse. L'absence de dépendance reste absolue : **pas de CDN, pas de polices
web, pas de framework** — un seul fichier autonome qui fonctionne avec la NetVM détachée.

---

### 1. Personas (ceux que nous servons réellement)

**Amara — journaliste d'investigation, 44 ans. Persona principale.**
Couvre la corruption dans les marchés publics. Reporter brillante, utilisatrice d'ordinateur réticente. Travaille
sur des sujets sensibles et se méfie (à juste titre) de la surveillance et de la perte de données.
*Besoins :* trouver vite dans son propre corpus ; prouver qu'un document est authentique et
inaltéré ; exporter quelque chose qu'elle peut remettre à un rédacteur en chef ou à un tribunal ; ne jamais se sentir bête.
*Craintes :* perdre son travail, être pistée, le jargon, avoir l'air d'une amatrice à côté d'un collègue « technique ».
*Condition de réussite :* elle ouvre l'application et sait immédiatement quoi faire, et ce qu'elle
produit a l'air fiable *et l'est*.

**Daniel — chercheur OSINT indépendant, 29 ans. Persona expert.**
Semi-technique, rapide, piloté au clavier, gère de nombreuses sources. *Besoins :* densité, opérations
par lots, tendances/associations, corrélations de marché, raccourcis clavier, une palette
de commandes. *Craintes :* un accompagnement qui le ralentit ; des fonctionnalités cachées.
*Condition de réussite :* il n'a jamais besoin de toucher la souris et trouve une puissance avancée à portée de main.

**La militante de la cause — l'« opérative », la cinquantaine. Persona des valeurs.**
Se méfie des géants de la tech ; veut la souveraineté. *Besoins :* la preuve que rien n'appelle la maison ; un fonctionnement
hors ligne ; des explications claires de ce que chaque action fait à son exposition réseau.
*Condition de réussite :* elle peut lire, dans l'application, exactement ce qu'elle fera et ne fera pas.

**Elliot — le rédacteur en chef, 38 ans. Persona destinataire.**
N'ouvre jamais l'application ; il en *reçoit* les productions. *Besoins :* des exports lisibles et
vérifiables par eux-mêmes. L'interface le sert indirectement : dossiers de preuves, possession
signée, CSV/JSON propres.

**Conséquence pour la conception :** concevoir d'abord pour Amara (clarté, accompagnement, confiance), superposer la
profondeur de Daniel pour qu'elle ne la gêne jamais (divulgation progressive + palette de commandes),
honorer la souveraineté de l'opérative dans les textes et le comportement, et faire des
productions d'Elliot des citoyennes de première classe.

---

### 2. Principes de conception (déduits, pas empruntés)

1. **La clarté plutôt que l'astuce.** Des verbes simples, des libellés humains, une action principale évidente
   par écran. Le jargon (« ingestion », « corpus », « racine de Merkle ») est traduit ou
   expliqué sur place, jamais présupposé.
2. **La confiance est le produit.** La vérifiabilité, la provenance et « ce chiffre est réel,
   pas estimé » sont mises en avant, pas enfouies. L'esthétique doit *donner l'impression* d'un
   instrument, pas d'un jouet.
3. **Divulgation progressive.** Simple par défaut ; la profondeur à un clic. Les panneaux avancés
   se replient ; les modules rarement utilisés peuvent être entièrement masqués.
4. **Personnalisable, parce que la confiance est personnelle.** Thèmes, couleur d'accent, densité, taille de police,
   mise en page, et *quels outils apparaissent tout court* sont réglés par l'utilisateur — et ne persistent
   qu'en local.
5. **L'honnêteté dans l'interface.** Si une capacité dépend d'un extra optionnel, l'interface
   le dit au lieu de faire semblant. Rien ne simule un succès.
6. **Souverain par construction.** Aucune requête externe d'aucune sorte. L'apparence est
   obtenue avec les polices système et des icônes SVG faites à la main.
7. **Le clavier d'abord, c'est aussi l'accessibilité d'abord.** Une palette de commandes et des raccourcis
   servent Daniel *et* rendent toute l'application accessible sans maniement précis de la souris.

---

### 3. Analyse outil par outil — avantages, inconvénients, décision

L'ancien jeu d'onglets du haut : *Recherche · Ingestion · Sources · Base de données · Marchés · Analyses ·
Wikipédia · Chaîne de possession · Paramètres.* Évalués un par un au regard de nos personas.

| Ancien onglet | Avantages | Inconvénients | **Décision** |
|---|---|---|---|
| **Recherche** | L'acte central. Tout le monde en a besoin. | Noyé comme un onglet parmi neuf ; aucune orientation pour un nouvel utilisateur. | **Garder et élever.** Devient le cœur, accessible instantanément ; un nouvel **Accueil** donne l'orientation autour de lui. |
| **Ingestion** | Nécessaire pour faire entrer les données. | « Ingestion » est un jargon d'ingénieur ; intimidant ; confondait planificateur et récupération manuelle. | **Garder, renommer → « Collecter ».** Commencer par l'action manuelle simple ; le planificateur devient « Collecte automatique », présentée comme « on règle et on oublie ». |
| **Sources** | La crédibilité vit ici ; la provenance commence par le *où*. | Tableaux denses ; ressemblait à de l'administration, pas à du journalisme. | **Garder, recadrer en « Sources » (la liste de rubriques de votre rédaction).** Restylé pour se lire comme une bibliothèque, pas comme une console de base de données. |
| **Base de données** | Comptes en direct honnêtes ; sauvegarde/restauration. | « Base de données » ne dit rien à Amara ; elle a une *bibliothèque/des archives*, pas une base de données. | **Garder, renommer → « Bibliothèque ».** Mêmes comptes réels et même couverture mondiale, présentés comme « ce que vous avez rassemblé ». |
| **Marchés** | Puissant pour les enquêtes qui « suivent l'argent ». | Hors sujet pour la plupart des sujets ; lourd, de niche ; encombrant pour Amara. | **Garder, marquer Avancé, masquable.** Hors du chemin critique ; un interrupteur le retire pour les utilisateurs qui ne font pas de travail financier. |
| **Analyses** | La vitrine visuelle — tendances, associations, carte. L'effet « waouh ». | Était un onglet discret au milieu ; sous-valorisé. | **Garder et promouvoir.** C'est une fonctionnalité phare ; mise en avant et soignée. |
| **Wikipédia** | Très pertinent : « le monde tel qu'il est vraiment », savoir hors ligne, détection des guerres d'édition. | Deux choses différentes (suivi en direct et lourds vidages hors ligne) réparties de façon confuse entre onglets. | **Garder.** Le suivi reste ici ; les lourds vidages restent dans Paramètres, avec des renvois clairs (déjà fait dans un travail antérieur). |
| **Chaîne de possession** | L'élément différenciant de la confiance. C'est ce qui fait qu'Elliot fait confiance au résultat et qu'Amara a l'air professionnelle. | Nommé en jargon juridique ; ressemblait à un coffre que peu ouvriraient. | **Garder, renommer → « Preuves & possession », promouvoir.** Fait partie du moment « c'est quoi, ça ?! ». |
| **Paramètres** | Nécessaire. | Était un fourre-tout (préférences + filtre de mots-clés + vidages + sauvegarde). | **Garder, restructurer** en sections (Apparence · Général · Wikipédia · Données & sauvegarde · Sécurité). *(0.07 : le tiroir Personnaliser autonome a été intégré comme section **Apparence** — un seul lieu pour l'apparence, moins d'éléments flottants.)* |

#### Nouvelles surfaces ajoutées

- **Accueil (tableau de bord).** *Justification :* Amara a besoin d'orientation, pas d'un champ de recherche vide.
  L'état d'un coup d'œil (taille du corpus, sources, planificateur, dernière activité), de grandes actions
  rapides (« Rechercher », « Collecter maintenant », « Vérifier un document ») et un état vide qui
  enseigne. C'est, à lui seul, le plus grand gain d'utilisabilité pour la persona principale.
- **Aide / lecteur de documentation.** L'utilisateur a explicitement demandé un accès direct au manuel
  détaillé. Une surface **Aide** de premier plan affiche le Manuel utilisateur (et d'autres documents)
  *dans* l'application — interrogeable, hors ligne, sans quitter l'outil. Également accessible depuis
  la barre supérieure (`?`) et la palette de commandes.

#### Architecture de l'information qui en résulte

La rangée plate de 9 onglets devient une **barre latérale groupée** (repliable en icônes), ordonnée
selon le déroulement réel du travail :

- **Enquêter** — Accueil · Recherche · Analyses · Carte temporelle · Wikipédia · *Marchés (avancé)*
- **Collecter** — Collecter · Sources · Bibliothèque
- **Confiance** — Preuves & possession
- **Système** — Paramètres · Aide

Le regroupement transforme « neuf étrangers égaux » en « quatre intentions », ce qui correspond à la façon de penser d'Amara
(« je veux *trouver* quelque chose » / « je veux *rassembler* » / « je veux *prouver* »).

---

### 4. L'effet « waouh » — ce qui fait se pencher un journaliste

- **Un système visuel cohérent.** Un thème sombre « encre » profond par défaut avec une seule
  couleur d'accent affirmée, un rythme d'espacement généreux, une vraie hiérarchie typographique, du monospace pour
  les données et les empreintes, une profondeur douce et des animations sobres. Cela se lit comme un *instrument*, pas comme un
  *modèle de tableau de bord*.
- **Palette de commandes (Ctrl/⌘-K).** Tapez pour aller n'importe où, lancer n'importe quelle action ou ouvrir
  n'importe quel document. De la puissance pour Daniel ; une carte de « qu'est-ce que je peux faire ici, au juste ? » pour Amara.
- **Réglages d'apparence** (Paramètres → Apparence ; un tiroir en direct jusqu'à la 0.06, intégré
  aux Paramètres en 0.07). Thèmes prédéfinis (Ink, Slate, Midnight, Paper, Sepia,
  Terminal, High-contrast), pastilles de couleur d'accent, densité, taille de police, repli de la barre latérale,
  et **visibilité des modules** — tout est instantané, local et persistant.
- **Un Accueil qui oriente**, un accueil des nouveaux utilisateurs qui enseigne et des états vides qui guident.
- **La confiance rendue visible.** La possession/la vérification et le cadrage « mesuré, pas estimé »
  font partie de l'esthétique, pas des petits caractères.
- **Intégrité hors ligne totale.** Aucun appel réseau pour l'habillage — ce qui est en soi une
  fonctionnalité que vous pouvez *montrer* à un collègue soucieux de sécurité.

---

### 5. Modèle de personnalisation

L'apparence est stockée dans `localStorage` (`oo.ui`) — jamais envoyée nulle part — elle est donc
instantanée et survit hors ligne. Les préférences fonctionnelles (limite de résultats par défaut, thème
de base) continuent de persister côté serveur via `/api/settings`. Personnalisables : thème
prédéfini, couleur d'accent, densité, échelle de police, état de la barre latérale et ensemble des
modules visibles. Des valeurs par défaut raisonnables font qu'un utilisateur à sa première utilisation n'a besoin de toucher à rien.

---

### 6. Ce que je n'ai délibérément **pas** fait (honnêteté)

- **Pas de framework / d'étape de compilation / de CDN.** Cela briserait l'éthos hors ligne, auditable et souverain
  pour un gain cosmétique. JS natif, fichier unique, polices système, SVG dessinés à la main.
- **Aucune fonctionnalité factice.** Chaque bouton correspond à un point d'accès réel et fonctionnel. Une capacité
  qui dépend d'un extra optionnel le dit toujours.
- **Aucun changement silencieux du backend**, hormis un point d'accès de documentation additif, en lecture seule et sur liste d'autorisation
  (`/api/docs`) pour alimenter le lecteur d'Aide.
- **Les champs de langue en texte libre sont restés en texte libre** (déjà noté dans OPEN_QUESTIONS) ;
  la refonte n'invente pas de listes déroulantes que le backend ne peut pas soutenir.

---

### 7. Statut

`0.05` est désormais la **branche par défaut** du dépôt (ligne principale) ; les lignes antérieures (0.04
et avant) restent dans l'historique git. La parité fonctionnelle est préservée (mêmes identifiants
d'éléments, même câblage) ; le changement porte sur tout ce qui *entoure* ce moteur. La version par défaut livre
**deux** interfaces — Console (`/`) et Desk (`/desk`) — comparées dans
[`DESIGN.md`](DESIGN.md).


---

## Deux interfaces, un argument — « Console » contre « Desk »

> Vous avez demandé un argument *contradictoire* : non pas une défense de la refonte 0.05, mais
> un plaidoyer honnête pour l'idée qu'elle pourrait être la **mauvaise** interface pour cette application — et une
> alternative concrète à laquelle la confronter. Ce document est cet argument. Les deux
> interfaces sont livrées côte à côte pour que vous puissiez les faire tourner toutes deux sur les mêmes données et juger
> par vous-même.

---

### 0. D'abord, revenir à ce qu'est réellement cette application

Avant de débattre de l'habillage, les non-négociables (tirés de `ETHICS.md`,
`DESIGN.md`, de la Charte de Munich) :

- **Un utilisateur, une machine, boucle locale uniquement, hors ligne d'abord.** Pas de comptes, pas de cloud,
  pas de télémétrie. Souvent exécutée dans une AppVM Qubes avec le qube réseau *détaché*.
- **Une personne en quête de vérité qui n'aime pas particulièrement les ordinateurs.** Un enquêteur /
  une journaliste dont le métier est de *comprendre la réalité et de la communiquer de manière crédible*.
- **Le produit, c'est la confiance.** Provenance, vérification des sources, « mesuré, pas
  estimé », preuve d'altération. La Charte de Munich (vérité, vérifier les sources, protéger les
  sources, résister à la propagande) en est la colonne vertébrale.
- **La souveraineté comme esthétique.** L'outil doit *donner l'impression* d'appartenir à l'utilisateur,
  pas à une plateforme.

Toute interface doit être jugée à l'aune de *ces points-là*, et non de « ressemble-t-elle à un
produit SaaS de 2025 ».

---

### 1. L'acte d'accusation contre « Console » (la refonte 0.05)

Présenter sous son meilleur jour l'argument selon lequel la 0.05 fait fausse route :

1. **Elle habille un outil souverain des vêtements du capitalisme de surveillance.** Barre latérale gauche
   persistante, pastilles d'état, palette de commandes, un tiroir de personnalisation avec huit
   thèmes — c'est la grammaire visuelle de Slack, Linear, Notion : le *SaaS dans le cloud*. Pour
   une utilisatrice qui se méfie des géants de la tech et travaille sur des sujets sensibles, cette grammaire peut
   se lire comme « encore une application qui m'observe », sapant la seule chose qui compte le
   plus ici : la confiance. L'apparence combat les valeurs.

2. **Elle optimise pour la démo, pas pour le travail.** La commande incluait « faire qu'un
   journaliste dise *je peux l'avoir ?* » — une réaction de cinq secondes par-dessus l'épaule.
   Concevoir pour cela tire vers le clinquant du tableau de bord (dégradés, compteurs animés,
   ménagerie de thèmes) et éloigne de la réalité calme, centrée sur la lecture et les documents, de
   l'enquête. Les meilleurs outils de travail en profondeur (un éditeur de texte, un carnet) sont
   *sobres*. Console est peut-être impressionnante et superficielle.

3. **La personnalisation est une taxe déguisée en cadeau.** Huit thèmes, pastilles d'accent,
   densité, échelle de police, masquage par module. Pour *Amara* (qui n'aime pas les ordinateurs), chacun
   de ces réglages est une décision qu'elle ne voulait pas prendre et une façon de mal configurer son outil.
   « Très personnalisable » servait la formulation de la commande et l'idée que le *concepteur* se fait de la
   générosité — mais un outil vraiment simple est **affirmé** : il fait le bon
   choix pour que l'utilisateur n'ait pas à le faire. Le choix est une charge cognitive.

4. **L'architecture de l'information reste celle du logiciel, pas celle de l'utilisateur.** Console
   a renommé et regroupé les onglets, mais le menu reste une liste de *modules*
   (Recherche, Sources, Analyses, Marchés, Possession…). Amara ne pense pas en modules ;
   elle pense en **dossier** : « je suis sur ce sujet — rassembler, lire, relier, prouver,
   publier. » La 0.04 comme la 0.05 obligent l'utilisateur à traduire son *métier* en *fonctionnalités*
   de l'application. Une navigation persistante de neuf destinations est une carte du code source.

5. **L'habillage concurrence le contenu.** Une barre latérale fixe + une barre supérieure consomment en permanence
   environ 250 px et une bande horizontale pour une *navigation que l'utilisateur emploie deux secondes par
   session*. Ce qu'il fait vraiment — lire des articles, parcourir des résultats, comparer des
   différences — se contente des restes. Enquêter, c'est lire ; Console sert mal la
   lecture.

6. **L'effet « waouh » est emprunté, pas mérité.** Une palette et des thèmes sont le *minimum attendu*
   dans les applications modernes — impressionnants précisément parce qu'ils sont familiers. Les fonctionnalités vraiment
   différenciantes, du genre « je n'ai jamais vu ça », sont ici la *substance* :
   détection hors ligne des guerres d'édition sur Wikipédia, possession révélant toute altération, « chaque chiffre est un
   vrai COUNT(\*) ». Console décore ; elle ne met pas en scène ce qui est réellement unique.

C'est un réquisitoire sérieux. Il mérite une véritable alternative, pas une réfutation.

---

### 2. Pour la défense de Console (pour que l'argument soit équitable)

- Une navigation persistante est **découvrable** : rien n'est caché, ce qui compte pour une
  novice qui ne sait pas encore ce que l'outil peut faire. Les modèles en étoile cachent
  la puissance derrière un clic et une supposition.
- La personnalisation est **facultative** : les valeurs par défaut sont saines ; un utilisateur qui ignore le tiroir
  ne perd rien. Et les thèmes aident réellement face à la fatigue visuelle et aux nuits tardives du
  métier, ainsi qu'à l'accessibilité (contraste élevé, taille du texte) pour de *vrais* utilisateurs.
- La « grammaire SaaS » n'est aussi que la **convention d'utilisabilité actuelle** — les gens savent
  s'en servir dès le premier jour. La nouveauté pour elle-même a sa propre taxe.
- Elle reste **100 % hors ligne et sans dépendance**. La grammaire est empruntée ; la
  substance (pas de réseau, pas de télémétrie) ne l'est pas.

Les deux positions sont légitimes. La façon de trancher n'est pas de débattre davantage — c'est de
**construire l'antithèse et d'utiliser les deux**.

---

### 3. L'antithèse : « Desk »

Si Console est une **vaste console d'opérations** (tout toujours à un clic,
flexibilité maximale, grammaire d'application moderne), **Desk** est la thèse opposée :

> **Un bureau d'enquêteur : calme, affirmé, centré sur le contenu et organisé par tâches.
> Presque aucun habillage. Une tâche à la fois. L'interface s'efface devant la lecture
> et la réflexion.**

Engagements concrets sur lesquels Desk est délibérément *en désaccord* avec Console :

| Dimension | Console (thèse) | Desk (antithèse) |
|---|---|---|
| Navigation | Barre latérale gauche persistante (toujours visible) | **Pas de navigation persistante.** La navigation est *à la demande* — un accueil calme, une surcouche « Aller à… » et ⌘K. L'habillage n'apparaît que lorsqu'on l'appelle. |
| Point d'entrée | Un tableau de bord d'état | **Un accueil organisé par tâches :** « Sur quoi travaillez-vous ? » → Rassembler · Trouver et lire · Relier · Vérifier et partager. Organisé selon la tâche de l'utilisateur, pas selon les modules de l'application. |
| Personnalisation | 8 thèmes, accent, densité, police, interrupteurs de modules | **Deux thèmes seulement** (Paper / Ink), aucun réglage. Affirmé. L'outil décide pour que vous n'ayez pas à le faire. |
| Esthétique | Console d'application moderne (sans empattement, pastilles, dégradés) | **Éditoriale / imprimée :** titres à empattement, chaleur du papier, marges généreuses, longueur de ligne de lecture. Cela évoque une rédaction, pas un SaaS. |
| Ce qui occupe l'espace | Navigation + état, puis contenu | **Le contenu.** Une seule colonne de lecture centrée ; les tableaux et le lecteur d'articles ont la place. |
| Signal de confiance | Une pastille d'état | Une ligne discrète et persistante **« Local · Hors ligne · Rien ne quitte cette machine »** — la souveraineté énoncée, pas sous-entendue. |
| Réaction à la démo | « Élégant ! » | « …oh, c'est *calme*. Et tout est à moi. » Un effet « waouh » plus lent et plus profond. |

Ce que Desk **conserve** (parce que c'est la raison d'être de l'application, pas de l'habillage) : chaque fonctionnalité
et chaque point d'accès fonctionnel. Desk et Console partagent exactement le même moteur et les
mêmes panneaux de contenu — ils ne diffèrent *que* par la coquille, le modèle de navigation, le cadrage de l'architecture de l'information
et l'esthétique. C'est délibéré : cela garde l'expérience contrôlée, de sorte que ce que vous
comparez est **la philosophie**, et non celle des deux que j'aurais câblée avec plus de soin.

---

### 4. Comment les juger (grille)

Évaluez chacune au regard des valeurs — pas de votre intuition « laquelle est la plus jolie » :

1. **Confiance** — laquelle *donne l'impression* de vous appartenir et de ne pas vous trahir ?
2. **Calme ou capacité** — laquelle vous laisse réfléchir ? laquelle rend la puissance trouvable ?
3. **Parcours novice** — lâchez *Amara* sans préparation : laquelle l'amène plus vite à un résultat, avec
   moins de crainte ?
4. **Parcours expert** — *Daniel* au clavier : laquelle s'efface devant lui ?
5. **Lecture** — ouvrez un long article / une différence Wikipédia dans chacune. Laquelle est le meilleur
   endroit pour *lire* ?
6. **Le test des 5 secondes** — montrez chacune à un collègue. Laquelle provoque « je peux l'avoir ? » —
   et est-ce la réaction que vous voulez vraiment optimiser ?
7. **Adéquation à l'éthos** — à laquelle feriez-vous confiance pour tourner avec le réseau détaché dans
   un coffre-fort Qubes ?

---

### 5. Avantages / inconvénients prévus (mon pari honnête, à tester)

**Console** — *Avantages :* découvrable, conventionnelle, flexible, réglages d'accessibilité, éclat
en démo. *Inconvénients :* habillage lourd, charge décisionnelle, allure de SaaS générique qui peut éroder la confiance,
architecture de l'information toujours centrée sur les modules.

**Desk** — *Avantages :* calme, centrée sur le contenu et la lecture, affirmée (pas de taxe de configuration),
entrée organisée par tâches, une esthétique qui *renforce* la souveraineté et la confiance. *Inconvénients :*
la puissance est à un appel près (un clic/une touche), moins de réglages d'accessibilité, moins
immédiatement « impressionnante », la nouveauté a un petit coût d'apprentissage.

---

### 6. Ma recommandation (synthèse — provisoire, en attendant votre test)

Je m'attends à ce que la bonne réponse ne soit **ni Console pure ni Desk pure**, mais une synthèse
qui s'appuie sur l'*adéquation aux valeurs* de Desk et la *découvrabilité* de Console :

- **Adopter l'accueil organisé par tâches et le calme éditorial de Desk** comme ambiance par défaut. Le
  cadrage par tâches (« rassembler / lire / relier / vérifier ») est, à lui seul, la meilleure réponse à la critique
  « l'architecture de l'information, c'est le code source ».
- **Adopter la retenue de Desk en matière de personnalisation :** livrer deux excellents thèmes
  (Paper/Ink) + un réglage de taille du texte pour l'accessibilité, et **supprimer** la prolifération accent /
  densité / masquage des modules. Ici, l'affirmé l'emporte sur le configurable.
- **Garder de Console une navigation *discrète et repliable*** pour la découvrabilité — mais
  repliée par défaut, pour que le contenu passe en premier et que la navigation soit là quand on la veut.
- **Garder ⌘K** (il sert à la fois la novice et l'expert et il est réellement utile).
- **Mettre en scène la substance, pas l'habillage :** faire de la possession, de Wikipédia hors ligne et des
  « vrais comptes » les héros visuels — c'est l'effet « waouh » mérité.
- **Afficher la ligne de confiance partout** (« rien ne quitte cette machine »). C'est
  la marque.

Mais c'est une hypothèse. Faites tourner les deux, évaluez-les selon le §4, et dites-moi où la réalité
s'écarte de mon pari — j'intégrerai alors le verdict dans une 0.06 unique.

> **VERDICT FINAL (mainteneur, 2026-06-10, après usage réel) :** la dialectique est
> tranchée — **Desk est entièrement retirée. Une seule interface : la Console** (`/`).
> Deux icônes ont semé plus de confusion qu'elles n'ont aidé ; l'ensemble d'outils réduit de Desk donnait l'impression que
> des fonctionnalités livrées (Carte temporelle, Agenda) étaient perdues ; et la Console
> s'adapte déjà en douceur à la taille de la fenêtre (la barre latérale se rétracte en rail d'icônes). Le
> fichier `desk.html` a été supprimé (il subsiste dans l'historique git) ; `/desk` redirige désormais
> vers `/`. Les meilleures idées de Desk — l'accueil organisé par tâches, ⌘K, le calme
> éditorial — doivent être intégrées à la Console au fil du temps, conformément au §6 ci-dessus.

---

### 7. Faire tourner les deux en même temps

Les deux interfaces sont servies par le même backend local, sur les mêmes données :

- **Console** → `http://127.0.0.1:8000/`  (par défaut)
- **Desk** → `http://127.0.0.1:8000/desk`

L'installateur crée **deux icônes de bureau** — *Open Omniscience* (Console) et
*Open Omniscience — Desk* — pour que vous puissiez lancer l'une ou l'autre, ou ouvrir les deux fenêtres ensemble
et les comparer onglet par onglet sur des données identiques. Choisissez une gagnante (ou demandez la
synthèse) et nous reviendrons à une seule en 0.06.


---

## Stratégie d'analyse de contenu — liens, uniformité et source originale

> Des stratégies concrètes et échelonnées pour la vision exposée dans [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md) :
> utiliser les **liens** des articles pour rassembler ce qui parle de la même chose, faire apparaître
> l'**uniformité** des médias et remonter l'information jusqu'à sa **source originale** — tout en
> laissant **le pouvoir à l'utilisateur**, une analyse **transparente et locale**, et sans jamais
> laisser l'outil devenir un arbitre de la vérité (Charte de Munich). Open source et
> hors ligne de bout en bout.

---

### 0. Où nous en sommes (statut honnête)

La détection des liens d'articles est **échafaudée mais pas branchée** :

- ✅ **`src/services/link_analyzer/extractor.py`** (`LinkExtractor`) — extrait les liens
  du HTML, normalise les URL, suit le texte d'ancre et la position, classe le *type* de lien
  (interne/externe/image/…) et produit des statistiques de liens. Environ 500 lignes, au format testable unitairement.
- ✅ **Schéma de base de données** — `ArticleLink` (url, normalized_url, link_text, position,
  link_type, **classification** = source/reference/ad/social/navigation,
  `external_source_id`, `source_article_id`, is_working, http_status…),
  `ExternalSource` et `LinkClassificationRule`. Les relations sont en place
  (`Article.links`, `ExternalSource.links`).
- ✅ **Appelé à l'ingestion** *(fait — P0)* — `src/ingest/pipeline.py:_maybe_index_links`
  remplit `article_links` avec les liens sortants **externes** (au mieux, échec ouvert ;
  liens internes/images/publicités/réseaux sociaux/traceurs exclus conformément à `ROADMAP.md` ; dédoublonnés + plafonnés).
- ✅ **API** *(fait — P1)* — `src/api/link_analysis.py` (`/api/links`) : `stats`,
  `top-cited` (par url|domaine, sur une fenêtre), `articles-by-link` (par url|domaine). Des comptes
  uniquement ; rien n'est noté ni jugé.
- ❌ **Pas encore d'interface** — aucune vue Analyses sur le graphe des liens (P2, ci-dessous).

Les P0/P1 sont donc branchés ; le travail restant concerne l'interface et les analyses plus poussées (P3/P4).

---

### 1. L'idée centrale : les liens forment un graphe de citations

Traiter chaque article comme un nœud et chaque lien sortant comme une arête orientée vers une URL (et
vers son domaine). Ce graphe répond exactement à ce que vous avez demandé :

- **« Rassembler tous les articles qui parlent du même lien. »** = regrouper les articles selon
  l'URL externe qu'ils citent → le **degré entrant** de l'URL, c'est « combien de mes articles pointent
  ici ». Un degré entrant élevé = un **pivot** : souvent un document primaire, une dépêche d'agence ou une
  référence très discutée.
- **« Découvrir des tendances grâce aux liens internes. »** = observer le degré entrant dans le temps ; une URL ou un
  domaine dont les citations s'envolent est une *tendance* ancrée dans ce que les journalistes citent réellement,
  pas seulement dans la fréquence des mots-clés.
- **« Remonter à la source originale / première. »** = au sein d'un groupe d'articles sur un même
  sujet, l'original est le nœud vers lequel les autres **pointent**, et/ou le plus ancien, et/ou celui
  qui cite un **document primaire** (tribunal/gouvernement/jeu de données). Liens + horodatages + attribution
  aux agences permettent de le trianguler.

C'est de l'*analyse de co-citation* — peu coûteuse, transparente et explicable. Aucune boîte noire.

---

### 2. Stratégies échelonnées (chacune livrable seule)

#### P0 — Brancher l'extracteur dans l'ingestion (faire exister le graphe)
- Appeler `LinkExtractor` pendant l'ingestion sur le HTML récupéré ; enregistrer les liens sortants
  **externes** dans `article_links` (ignorer la navigation interne, les publicités et — conformément à
  `ROADMAP.md` — les liens d'images/binaires). Stocker normalized_url + texte d'ancre + type.
- Associer le domaine de chaque lien externe à une `Source`/`ExternalSource` connue lorsque
  c'est possible (pour que « qui cite qui » puisse remonter jusqu'aux médias et à leurs **propriétaires**).
- Peu coûteux, déterministe, hors ligne. Rien n'est récupéré au-delà de ce que l'ingestion récupérait déjà.

#### P1 — Agrégation + API (répondre à la question de l'utilisateur)
Points d'accès en lecture seule sur le graphe :
- **`top-cited`** — les URL/domaines les plus cités sur une fenêtre (le signal de tendance).
- **`articles-by-link`** — pour une URL/un domaine donné, chaque article du corpus qui le cite
  (« rassembler tous les articles qui parlent du même lien »).
- **`link-graph`** — nœuds/arêtes pour un sujet ou une fenêtre, à des fins de visualisation.
- **`co-citation`** — les articles qui citent les *mêmes* sources externes (groupes candidats
  « même sujet »), avec les comptes de recouvrement.

#### P2 — Interface : une vue « Liens et sources » dans Analyses
- Une liste classée des **liens/domaines les plus cités** (clic → tous les articles qui les citent).
- Un petit **graphe de citations** zoomable (réutiliser l'approche SVG déjà employée pour la
  carte d'Analyses — aucune nouvelle dépendance).
- Affiche toujours les **tailles d'échantillon** (« cité par 14 de vos articles ») — mesurées, pas
  devinées. L'utilisateur clique, explore, décide.

#### P3 — Lignée de la source originale
Pour un groupe d'articles sur un même sujet, présenter une **lignée**, classée selon des signaux
(chacun affiché, aucun décisif) :
- le degré entrant (vers qui pointent les autres),
- l'horodatage de publication le plus ancien,
- l'attribution à une agence (AFP/Reuters/AP — nous étiquetons déjà `wire-agency`),
- la présence d'un lien vers un **document primaire** (gouvernement/tribunal/jeu de données/prépublication).
Résultat : « document primaire → premier article → échos », sous forme d'une chaîne que l'utilisateur lit.

#### P4 — Uniformité et écho (lié à la concentration des médias)
- **Détection des quasi-doublons** (MinHash/SimHash peu coûteux) pour signaler les textes repris ou copiés
  d'un média à l'autre — s'appuie sur `src/ingestor/duplicate_detector.py`.
- **Score d'écho** : un groupe où de nombreux médias citent **une seule** source (ou se citent mutuellement dans une
  boucle serrée) et ajoutent peu de liens originaux = écho élevé. Des citations de sources primaires diverses =
  un journalisme indépendant.
- **Superposition de la concentration** : pondérer l'écho par la **propriété** — si le groupe qui fait écho correspond
  à un seul propriétaire/bloc (le cas « ~7 milliardaires possèdent ~90 % »), le faire apparaître. Nécessite le
  graphe de propriété (Wikidata P127/P749 + saisie manuelle), conformément à `ROADMAP.md`.

---

### 3. Laisser le pouvoir à l'utilisateur (non négociable)

- **Faire apparaître, ne jamais supprimer.** Les scores d'écho/de lignée sont *affichés et triables* ; l'outil
  ne masque ni ne rétrograde jamais automatiquement une source. Toute pondération à la baisse est un réglage utilisateur
  explicite et réversible, **désactivé par défaut**.
- **Aucune étiquette de vérité.** « Le plus ancien que nous ayons vu » / « le plus cité » ≠ « vrai ». Nous montrons la structure
  (qui l'a dit en premier, qui cite qui, qui possède qui) et nous nous arrêtons là.
- **Tout est explicable et local.** Chaque chiffre remonte à des lignes que l'utilisateur peut inspecter ;
  aucun appel externe, aucune boîte noire d'apprentissage automatique (hachage + comptage + degré dans le graphe).
- **Open source et auditable.** Fonctions pures, testables unitairement, règles de classification sous forme de
  données (`LinkClassificationRule`) que l'utilisateur peut modifier.

---

### 4. Risques et limites honnêtes

- L'extraction des liens ne vaut que ce que vaut le HTML récupéré (les paywalls et le JS la limitent).
- Les conventions d'ancre et de citation varient ; un « selon X » sans lien est manqué (une
  passe de traitement automatique du langage ultérieure pourrait aider, mais on commence simple).
- Les données de propriété sont lacunaires et datées — elles doivent être attribuables, pas devinées.
- Les quasi-doublons à l'échelle du corpus exigent du soin pour rester peu coûteux sur une seule machine (hachage, comparaison
  par fenêtre), et non des comparaisons plein texte en O(n²).

### 5. Premier commit suggéré

Brancher le **P0** (remplir `article_links` à l'ingestion) derrière un paramètre, ajouter les points d'accès **P1
`articles-by-link`** et **`top-cited`**, ainsi qu'une liste minimale dans Analyses. Cela
suffit à fournir « rassembler tous les articles qui citent le même lien » et une tendance fondée sur les citations
— la plus petite tranche de valeur réelle, parfaitement fidèle à l'éthos.
