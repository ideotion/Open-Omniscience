<!-- fr: Translation of docs/ARCHITECTURE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 28 of 28 headings. Corrections are welcome as a pull request. -->

# Architecture et référence technique

Le complément technique du Manuel d'utilisation : la base de données et sa configuration, la carte de l'API HTTP, et l'internationalisation.

## Sommaire
- [Configuration de la base de données d'Open Omniscience](#configuration-de-la-base-de-données-dopen-omniscience)
- [Référence de l'API](#référence-de-lapi)
- [Internationalisation (i18n) — rendre l'application multilingue](#internationalisation-i18n--rendre-lapplication-multilingue)


---

## Configuration de la base de données d'Open Omniscience

> **État (vérifié lors de l'audit v0.0.7, `docs/archive/audits/00_BASELINE.md`) :** la couche base de données
> **fonctionne et est testée** — le serveur démarre, crée et utilise le stockage SQLite, applique les migrations
> Alembic, et la suite de tests complète (plus de 800 tests) passe contre elle. L'ancien bandeau « concept
> précoce — non fonctionnel » qui figurait ici décrivait un état antérieur à la reconstruction et était depuis longtemps
> périmé.

### 🗃️ SQLite — le stockage pris en charge

SQLite est le **backend par défaut et le seul pris en charge et testé**. Il correspond à la conception
local d'abord et mono-opérateur du produit.

- **Aucune configuration :** la base de données est créée automatiquement au premier lancement, à
  `<data dir>/open_omniscience.db`. Le répertoire de données est `OO_DATA_DIR` s'il est défini, sinon le
  `data/` du dépôt dans une copie des sources, sinon `$XDG_DATA_HOME/open-omniscience` (voir `src/paths.py`).
- **Réglage automatique :** le moteur applique le mode de journalisation `WAL`, `foreign_keys=ON`,
  `busy_timeout=30000` et `synchronous=NORMAL` à chaque connexion
  (`src/database/session.py`) — vous n'avez pas à les définir vous-même.
- **La recherche plein texte** repose sur **FTS5** de SQLite (`article_fts`, à contenu externe, maintenue synchronisée par
  des déclencheurs — `src/database/fts.py`).
- **Changer l'emplacement** avec la variable d'environnement `DATABASE_URL` (ne modifiez **pas**
  les fichiers source) : `DATABASE_URL=sqlite:////absolute/path/to/your.db`
- **Maintenance :** un `sqlite3 <db> "VACUUM;"` occasionnel récupère de l'espace (l'audit v0.0.7
  a aussi supprimé un index redondant qui représentait environ 63 % du fichier sur les gros corpus ; exécutez `make
  migrate` une fois après la mise à niveau pour le retirer des bases existantes).

### 🐘 PostgreSQL — échafaudage expérimental, NON pris en charge

L'honnêteté plutôt que l'aspiration (constat d'audit ARCH-06) : la couche moteur *reconnaît* une
`DATABASE_URL` PostgreSQL (pool de connexions via `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`), **mais**

- **la recherche plein texte n'existe pas sur PostgreSQL** — la mise en place FTS5 ne fait délibérément rien sur
  les moteurs autres que SQLite, si bien que l'onglet Recherche serait inopérant ;
- la suite de tests n'est jamais exécutée contre PostgreSQL, et aucune CI ne le couvre ;
- aucun déploiement publié ne l'a utilisé.

Considérez PostgreSQL comme un **échafaudage non testé pour un avenir possible**, et non comme un choix que vous pouvez
faire aujourd'hui. Si l'échelle multi-écrivains devient un jour un besoin réel, l'élément de feuille de route est un
chemin de recherche `tsvector` plus une matrice CI PostgreSQL — tant que cela n'est pas livré, cette page ne fera pas
semblant.

### 🔄 Migrations

Alembic est configuré à la **racine du dépôt** (`alembic.ini`, `migrations/`). Alembic est
installé avec l'application (c'est une dépendance du cœur — aucune installation séparée).

- **Les nouvelles bases de données** sont créées complètes (`create_all` + FTS) et marquées automatiquement
  au démarrage avec la tête de migration courante.
- **Mettre à niveau une base existante :**
  ```bash
  make migrate          # = alembic upgrade head, from the repo root
  ```
- **Créer une migration** (contributeurs) : modifiez `src/database/models.py`, puis
  ```bash
  alembic revision --autogenerate -m "your message"
  alembic upgrade head
  ```
  et vérifiez le fichier généré — l'autogénération ignore les tables virtuelles FTS (elles se trouvent dans
  `src/database/fts.py`, appliqué au démarrage).
- **Revenir en arrière :** `alembic downgrade -1`.

---

### 📊 Schéma de la base de données

#### Tables :

##### `sources`
| Colonne | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Clé primaire |
| `name` | STRING(100) | Nom de la source (par ex. « BBC News ») |
| `domain` | STRING(255) | Domaine de la source (par ex. « bbc.com ») |
| `rss_url` | STRING(500) | URL du flux RSS (le cas échéant) |
| `rate_limit_ms` | INTEGER | Délai entre requêtes, en millisecondes |
| `enabled` | BOOLEAN | Indique si la source est active pour la collecte |
| `priority` | INTEGER | Niveau de priorité (1 = haute, 3 = basse) |
| `tags` | STRING(500) | Liste d'étiquettes séparées par des virgules |

##### `articles`
| Colonne | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Clé primaire |
| `url` | STRING(1000) | URL d'origine de l'article |
| `canonical_url` | STRING(1000) | URL canonicalisée (pour la détection des doublons) |
| `source_id` | INTEGER | Clé étrangère vers `sources` |
| `title` | STRING(500) | Titre de l'article |
| `content` | TEXT | Contenu textuel intégral de l'article |
| `published_at` | DATETIME | Date/heure de publication (format ISO) |
| `language` | STRING(10) | Code de langue (par ex. « en », « fr ») |
| `hash` | STRING(64) | Empreinte SHA-256 du contenu (pour la détection des doublons) |
| `created_at` | DATETIME | Horodatage de l'ingestion de l'article |

> Les colonnes ci-dessus sont les champs essentiels ; le schéma réel (`src/database/models.py`)
> et les migrations Alembic sous `migrations/versions/` font foi.
> `articles` porte aussi des champs de provenance et d'analyse (author, word_count, region,
> country, sentiment) et une colonne de contenu compressé.

##### Autres tables (voir les modèles / migrations pour l'ensemble des colonnes)

| Table | Rôle |
|-------|---------|
| `source_groups`, `source_metadata`, `source_group_association` | Regroupement des sources + métadonnées géographiques/robots |
| `commodity_prices` | Points de prix observés (symbole, date, prix, devise, **unité**, marché, source) — graphiques + corrélation prix↔actualité |
| `market_extraction_rules` | Règle par source (sélecteur CSS / attribut / regex) localisant le prix d'un instrument sur une page ; catégorie financier/action/matière première |
| `keywords` | Terme distinct de mot-clé/entité (normalisé, langue, `is_entity`/`entity_type`, provenance **`extractor`**) |
| `keyword_mentions` | Une par couple (article, mot-clé) : nombre + premier décalage de caractère + `observed_on`/`country`/`city` dénormalisés — alimente les tendances, associations, contextes et la carte des Analyses |
| `wiki_pages` | Une page Wikipedia suivie dans une édition linguistique ; conserve **une seule** référence de texte intégral compressée |
| `wiki_revisions` | Une modification suivie : **diff + delta d'octets signé** + indicateurs/étiquettes (pas une recopie), scores ORES optionnels, indicateur honnête de grosse modification + raisons |
| `article_analyses` | Résultats LLM dérivés (résumé/traduction) avec la provenance du modèle et de l'invite |
| `keyword_categories`, `external_sources`, `article_links`, … | Catégorisation des mots-clés + suivi des liens et des relations entre sources |

#### Index :
- `idx_article_hash` : index unique sur `hash` (pour la détection des doublons).
- `idx_article_canonical_url` : index sur `canonical_url` (pour les recherches par URL).
- `idx_article_source_id` : index sur `source_id` (pour les requêtes par source).
- `idx_article_content` : index sur `content` (pour la recherche plein texte).

---

### 🔍 Recherche plein texte

La recherche plein texte est **déjà construite et branchée** — il n'y a rien à activer. Le stockage
comporte une table FTS5 à contenu externe (`article_fts`) maintenue synchronisée par des déclencheurs ; voir
`src/database/fts.py` pour le schéma et `search_ids` dans `src/api/main.py` pour le chemin de
requête (résolution des seuls identifiants dans l'ordre final, lignes complètes chargées pour la seule page affichée).

Cette section proposait autrefois une recette « envisagez de créer une table virtuelle » pour SQLite et une
recette `to_tsvector` pour PostgreSQL. Les deux étaient fausses : celle pour SQLite décrivait la construction à
la main d'une table que l'application livre et maintient (sous un *autre* nom, si bien que la suivre aurait
produit un second index, non maintenu), et PostgreSQL n'a ici aucun chemin de recherche,
ce que la section sur le stockage ci-dessus présente comme la première raison pour laquelle il n'est pas un backend pris en charge.

---

### 📉 Surveillance et maintenance

- **Vérifier la taille de la base** :
  ```bash
  ls -lh data/open_omniscience.db
  ```
- **Vérifier la taille des tables** :
  ```bash
  sqlite3 data/open_omniscience.db "SELECT name, COUNT(*) FROM sqlite_master WHERE type='table';"
  ```
  Sur un stockage **chiffré**, l'outil en ligne de commande `sqlite3` ne peut pas du tout ouvrir le fichier (c'est
  précisément le but) — utilisez les surfaces Paramètres → Diagnostics de l'application, qui lisent le stockage
  au travers de la même fabrique de connexions protégée que celle qu'utilise l'application elle-même.

---

### 🚨 Dépannage

#### Problèmes courants :

##### SQLite :
- **« Database is locked »** :
  - SQLite n'autorise qu'un seul écrivain à la fois. Le mode WAL est activé par défaut
    (`src/database/session.py`) et un verrou d'écriture unique à l'échelle du processus
    (`src/database/writer.py`) sérialise les écritures internes à l'application, si bien que l'ingestion et
    l'import simultanés n'entrent plus en collision. Un verrou persistant signifie qu'un autre *processus* écrit.

- **« Too many open files »** :
  - SQLite ouvre une nouvelle connexion pour chaque thread. Limitez le nombre de threads ou utilisez un pool de connexions.

- **« Relation does not exist » / « no such table »** :
  - Exécutez les migrations : `alembic upgrade head`.

---

### 📌 Bonnes pratiques

1. **Sauvegardez par l'application, pas avec `cp`** :
   - Utilisez Paramètres → Sauvegarde (ou `GET /api/database/backup` pour un instantané cohérent).
     Copier `open_omniscience.db` à la main n'est **pas** une sauvegarde : le stockage fonctionne en mode
     WAL, donc le fichier actif ne contient pas ce qui se trouve encore dans `-wal`, et sur le stockage
     **chiffré** par défaut, un fichier copié est inutilisable sans la phrase de passe et ne porte aucun
     engagement d'intégrité. Le chemin propre à l'application effectue un point de contrôle, diffuse et signe.

2. **Testez les migrations** :
   - Testez toujours les migrations sur une sauvegarde de votre base avant de les appliquer en production.

3. **Surveillez les performances** :
   - Paramètres → Diagnostics contient le journal des requêtes lentes, le journal de latence des requêtes et le
     rapport du verrou d'écriture ; l'outil en ligne de commande `sqlite3` fonctionne sur un stockage en clair.

4. **Optimisez les requêtes** :
   - `EXPLAIN QUERY PLAN` est l'outil adéquat. Notez que SQLite écrit `SCAN` **à la fois** pour un simple
     parcours de table et pour un parcours d'index seul — un `SCAN <table> USING [COVERING] INDEX …` est
     sain ; le signal d'alerte est un `SCAN <table>` nu, sans `USING`
     (`src/monitoring/slowquery.py` classe exactement sur ce critère).

5. **Limitez la durée de conservation des données** :
   - Archivez ou supprimez régulièrement les anciens articles pour garder la base gérable.
   - Exemple : supprimer les articles de plus d'un an :
     ```python
     from datetime import datetime, timedelta
     one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
     session.query(Article).filter(Article.published_at < one_year_ago).delete()
     session.commit()
     ```

---
*Copyright © 2026 Ideotion. Distribué sous la licence publique générale GNU v3.0
ou ultérieure (GPL-3.0-or-later) — voir [LICENSE](../LICENSE). Ce logiciel est libre ;
vous pouvez le redistribuer et le modifier selon ces conditions.*


---

## Référence de l'API

La référence de l'API en direct, toujours exacte, est générée par l'application elle-même :

- **Swagger UI / ReDoc :** désactivés par défaut (ils chargent des ressources depuis des hôtes tiers) ; lancez l'application avec `OO_API_DOCS=1` pour obtenir http://127.0.0.1:8000/docs et `/redoc`
- **JSON OpenAPI :** http://127.0.0.1:8000/openapi.json

L'application n'écoute que sur la boucle locale et (pour un seul utilisateur local) n'exige aucune authentification.

### Groupes de points de terminaison

Ceci est une **carte des principaux groupes, et non une liste exhaustive** — le
`/openapi.json` en direct (ci-dessus) fait toujours foi. Les routeurs sont branchés dans
`src/api/main.py` via `include_router(...)` ; les groupes marqués **[analysis]** nécessitent
l'extra `[analysis]` (l'application démarre quand même sans lui, ces points de terminaison étant désactivés).

| Préfixe | Ce qu'il fait |
|--------|--------------|
| `GET /api/health` | État de vie + version |
| `GET /api/articles`, `/api/articles/export` | Recherche plein texte booléenne (FTS5) + export CSV/JSON |
| `POST /api/ingest`, `/api/sources/{id}/ingest`, `/api/sources/{id}/ingest-email` | Ingestion éthique : URL unique, flux RSS, boîte aux lettres IMAP |
| `… /api/sources`, `/api/sources/...` | Gestion des sources, des groupes et des métadonnées |
| `POST /api/sources/seed-defaults` | Peuple les catalogues de sources sélectionnés (actualités + marchés + catalogue mondial généré) |
| `GET /api/database/stats`, `/coverage`, `/countries` | Nombres de lignes du corpus + taille sur disque ; couverture par pays ; nombre de sources par pays + mots-clés thématiques |
| `GET /api/database/backup` | Téléchargement d'un instantané SQLite cohérent (stockage SQLite en clair uniquement ; refusé pour une requête venant d'un autre site ou d'un Host que la protection contre le DNS rebinding ne sert pas, et, sur un nom autre que la boucle locale, pour une requête qui ne nomme aucune page d'origine sauf si elle envoie `X-OO-Download: 1` ; un seul à la fois par processus, écrit dans un dossier privé `.oo-backup-*` à côté de la base de données et supprimé à la fin du téléchargement ou à l'arrêt du processus (un arrêt forcé le laisse au nettoyage du démarrage suivant, qui supprime aussitôt le dossier d'un propriétaire disparu) ; 507 lorsque le volume de données ne peut pas le contenir) |
| `POST /api/database/v2/restore/preview`, `/v2/restore/commit`, `/api/backup/v2/*` | Restauration **purement additive** via l'artefact signé `oo-backup-2` : prévisualiser le plan de fusion, puis valider. La restauration **n'écrase jamais votre corpus** — elle fusionne sans doublons, en gardant les valeurs locales en cas de conflit (le chemin de remplacement destructif a été supprimé le 2026-06-13) |
| `GET/PUT /api/settings` | Préférences de l'interface (thème, limite de résultats par défaut) |
| `… /api/scheduler/...` | Collecte en arrière-plan : état, démarrage, arrêt, exécution immédiate, configuration. Depuis le cycle `0.4`, la collecte s'exécute en **voies côte à côte** (`rss` / `crawl` / `markets` / `wiki` / `law`), et non en un mode unique du planificateur — stockage par voie sous `… /api/storage/...`, et l'onglet **Sources vivantes** lit `… /api/living/...` (ce qui a changé dans Wikipedia, le droit et les cartes) |
| `… /api/markets/rules`, `/rules/{id}/run`, `/overview` | Règles d'extraction de prix par source + exécution de « test » + vue d'ensemble des Marchés |
| `GET /api/markets/feeds`, `POST /feeds/{key}/import`, `/feeds/import-url` | Catalogue officiel de flux de prix CSV + import (FRED/Banque mondiale/EIA) + import depuis une URL personnalisée |
| `GET /api/catalog/export.csv`, `/template.csv`, `/columns`, `POST /api/catalog/import` | Export CSV de la liste des sources / modèle / colonnes / import avec mise à jour par domaine |
| `… /api/insights/...` | Analytique des mots-clés et entités : état, réindexation, top, tendances montantes, tendance, associations (PMI), contexte, carte |
| `GET /api/timemap`, `/timemap/range` | Signaux spatio-temporels sur une carte et un axe temporel uniques (ancres + corpus géocodé + aléas/dates mentionnées sur option) ; `?kinds`, fenêtre en années fractionnaires `?start`/`?end`, `?hazards`, `?articles`, `?mentions`, `?days` |
| `… /api/article-dates/...` | Dates extraites du texte des articles, sous forme d'étiquettes par article confirmables par un humain : liste/extraction par article, confirmer/rejeter, indexation par lot, filtre du corpus par date |
| `GET/POST /api/llm/...` | LLM local (Ollama) : état, modèles, génération, résumé d'un article |
| `… /api/commodities/...` | Prix des matières premières (import / CSV / liste) + corrélation honnête prix↔actualité |
| `POST /api/analysis/...` | Statistiques de rigueur scientifique : test t, corrélation, ANOVA, Mann-Whitney, IC |
| `GET /api/monitoring/...` | Disponibilité réelle des sources + anomalies de volume du corpus |
| `POST /api/verify/image-metadata` | Extraction honnête des EXIF/métadonnées d'images |
| `POST /api/reports/evidence`, `/evidence/verify` | Dossiers de preuves signés, à falsification détectable |
| `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`, `POST /api/custody/export`, `POST /api/custody/verify` | Journal de chaîne de traçabilité signé, en ajout seul et chaîné par hachage + vérification hors ligne |
| `GET/PUT /api/custody/settings` | Préférences d'exécution de la traçabilité (signature post-quantique, mode d'ancrage, journalisation automatique) — rapporte l'état *effectif*, tenant compte de la disponibilité |
| `POST /api/custody/anchor`, `GET /api/custody/providers` | Ancre une racine de Merkle (local / OpenTimestamps) + disponibilité des fournisseurs |
| `POST /api/custody/reconcile` | Écrit les entrées INGEST qu'un échec a laissées en souffrance, chacune marquée tardive dans ses métadonnées signées ; `scan` compte les lacunes plus anciennes, `record_gaps` les met en file (2026-09-24, CUST-1) |
| `… /api/keywords/...`, `/api/analysis/articles/similarity` | **[analysis]** Extraction de mots-clés + similarité entre articles |
| `GET /api/search/omni` | Barre de recherche fédérée adossée aux index (articles FTS5 + mots-clés + sources + wiki/droit) |
| `… /api/jobs/...` | Agrégation des tâches du gestionnaire de tâches (passe de collecte, récupération en cours, file des dumps wiki + réordonnancement) |
| `… /api/system/...` | Indicateurs système + état/consentement réseau (interrupteur d'arrêt du mode avion, IP des interfaces locales) |
| `… /api/safety/...` | Contrôles de sécurité : interrupteur d'arrêt, verrou de découverte, restauration depuis un artefact chiffré |
| `… /api/briefing/...` | Producteurs du briefing de l'Accueil (cartes hiérarchisées par niveau de preuve ; méthode + mise en garde + n) |
| `… /api/insights/...`, `/api/insights/who`, `/where` | Analytique des mots-clés et entités + agrégation Qui/Où sur l'ensemble du corpus |
| `… /api/links/...` (shared, preview) | Analyse des liens sortants partagés / du graphe de citations + boîte de dialogue locale d'aperçu des liens |
| `… /api/events/...`, `/api/events/astronomy`, `/climate` | Événements de l'Agenda, y compris l'astronomie calculée localement (Meeus) + table El Niño |
| `POST /api/weather/context` | Extrait de réanalyse Open-Meteo, consenti et borné, à des fins de corroboration |
| `… /api/law/...` | Flux des modifications de la législation suivie / des sources primaires |
| `… /api/integrity/...` | Signaux d'écho / de coordination / de filiation |
| `… /api/annotations/...` | Annotations d'articles locales, éventuellement signées |
| `… /api/wiki/...` | Éditions Wikipedia, pages suivies, téléchargement/lecture des dumps, synchronisation avec le corpus |
| `… /api/hazards/...`, `/api/timemap` | Couches d'aléas + carte spatio-temporelle |
| `GET /unlock`, `POST /api/unlock`, `/create-db`, `/doctor`, `/encrypt-db` | Chiffrement au repos : écran de déverrouillage au démarrage verrouillé, création d'un stockage chiffré/en clair, attestation d'en-tête, outil de chiffrement à sens unique |

Les routeurs marqués **[analysis]** (matières premières, statistiques, mots-clés, cadrage)
nécessitent l'extra `[analysis]` ; sans lui, l'application démarre quand même avec le
socle et ces points de terminaison sont désactivés.

Notes de comportement :
- L'ingestion récupère uniquement via le récupérateur éthique (robots.txt en échec fermé, débit
  limité) ; les points de terminaison LLM renvoient **503** si Ollama est indisponible (jamais une fausse réponse).
- Vérification des preuves : transmettez la clé publique du signataire pour prouver la provenance, et pas seulement
  l'intégrité (voir [QUICKSTART](QUICKSTART.md) et `scripts/verify_evidence.py`).
- Les paramètres de traçabilité sont des *préférences*, non des garanties : `GET/PUT /api/custody/settings`
  rapportent toujours l'état **effectif** (préférence **et** disponibilité de la bibliothèque), si bien que
  le post-quantique / OpenTimestamps n'apparaissent jamais activés lorsque l'extra correspondant est
  absent. L'ancrage utilise par défaut le fournisseur hors ligne `local` ; OpenTimestamps et
  l'ancrage sur chaîne publique s'accompagnent d'un avertissement de confidentialité (voir
  [CHAIN_OF_CUSTODY](USER_MANUAL.md)).


---

## Internationalisation (i18n) — rendre l'application multilingue

> Objectif : l'**interface entière** (et, avec le temps, la **documentation**) disponible dans une
> douzaine de langues, pour élargir l'accès ouvert vers « presque tous les humains ». À la manière
> du projet : **hors ligne, sans CDN, sans API de traduction à l'exécution, sans télémétrie**, et
> **honnête** sur la qualité des traductions (nous ne livrons pas des approximations automatiques comme si elles
> faisaient autorité).

---

### Les douze langues (ensemble de la phase 1)

Choisies pour leur portée (locuteurs natifs + en langue seconde) et pour inclure délibérément le
Sud global (conformément à l'objectif anti-biais de `ROADMAP.md`) :

| Code | Langue | Nom natif | Écriture / sens | État |
|---|---|---|---|---|
| `en` | Anglais | English | LTR | **source** (complète) |
| `fr` | Français | Français | LTR | **complète** (validée) |
| `es` | Espagnol | Español | LTR | **complète** (validée) |
| `de` | Allemand | Deutsch | LTR | **complète** (validée) |
| `zh` | Chinois (mandarin) | 中文 | LTR | complète (traduite, cycle `0.4` ; pas encore validée) |
| `hi` | Hindi | हिन्दी | LTR | complète (traduite, cycle `0.4` ; pas encore validée) |
| `ar` | Arabe | العربية | **RTL** | complète (traduite, cycle `0.4` ; pas encore validée) |
| `bn` | Bengali | বাংলা | LTR | complète (traduite, cycle `0.4` ; pas encore validée) |
| `ru` | Russe | Русский | LTR | complète (traduite, cycle `0.4` ; pas encore validée) |
| `pt` | Portugais | Português | LTR | complète (traduite, cycle `0.4` ; pas encore validée) |
| `id` | Indonésien | Bahasa Indonesia | LTR | complète (traduite, cycle `0.4` ; pas encore validée) |
| `ja` | Japonais | 日本語 | LTR | complète (traduite, cycle `0.4` ; pas encore validée) |

Ajouts faciles pour élargir la portée : **swahili (`sw`)**, **ourdou (`ur`, RTL)**, italien
(`it`), turc (`tr`), vietnamien (`vi`).

**Position d'honnêteté.** Une *ébauche* rend une langue **sélectionnable dès maintenant** et se rabat sur
l'anglais pour toute chaîne non traduite — une locale partielle ne casse jamais l'interface (c'est
le mécanisme dont part toute locale future — `it`, `tr`, `vi`, … ). Nous marquons chaque locale `complete | draft | stub`. Le mainteneur
ne livre que ce dont il peut se porter garant ; tout le reste est complété par **contribution
communautaire** (c'est précisément ainsi que le logiciel libre élargit l'accès).

---

### Architecture (hors ligne, sans dépendance)

`src/static/i18n.js` + `src/static/locales/<code>.json`. Aucune étape de compilation, aucun réseau.

- **L'anglais sert de clé.** Les fichiers de locale associent **la chaîne d'interface anglaise → sa traduction**
  (par ex. `"Search the corpus": "Rechercher dans le corpus"`). Cela permet d'adapter
  l'interface existante sans baliser chaque élément, et conserve l'anglais comme source
  canonique.
- **`OOI18N.setLang(code)`** charge `locales/<code>.json`, mémorise le choix dans
  `localStorage` (`oo.lang`), définit `document.documentElement.lang` et `dir` (RTL pour
  `ar`/`ur`), puis **`apply()`** parcourt le DOM — en traduisant les nœuds texte dont le texte
  épuré correspond à une clé, ainsi que les attributs `placeholder`/`title`/`aria-label`. Les chaînes
  inconnues sont laissées telles quelles (repli sur l'anglais) — rien ne casse jamais.
- **Le contenu dynamique** (données : titres d'articles, noms de sources, décomptes) n'est **jamais**
  traduit — seul l'habillage de l'interface l'est. L'habillage rendu en JS (palette de commandes, tiroir) appelle
  `OOI18N.apply()` après son rendu.
- Chaque locale porte un `_meta` (`name`, `native`, `dir`, `status`).

#### L'intégrer (phase 2 — livrée ; Desk a depuis été retiré)

Deux lignes dans `index.html` (et, avant son retrait le 2026-06-10, dans `desk.html`),
puis un sélecteur de langue :

```html
<script src="/static/i18n.js"></script>
<!-- after first render and on each view change: --> OOI18N.apply();
```

Le sélecteur **Langue** se trouve dans les Paramètres et appelle `OOI18N.setLang(code)`,
mémorisé avec les autres préférences d'interface locales.

---

### Documentation en plusieurs langues

Les documents sont longs et la qualité de la traduction compte davantage que pour de courtes chaînes d'interface, donc :

- Structure : `docs/i18n/<code>/<DOC>.md` reflète `docs/`.
- Les **documents anglais restent canoniques** ; les traductions relèvent du travail de la communauté/du mainteneur,
  chacune marquée de sa date de traduction et du commit anglais qu'elle suit.
- Nous ne traduisons **pas** automatiquement les documents pour les présenter comme faisant autorité — cela
  violerait le principe d'honnêteté du projet. Commencez par les documents les plus utiles et les plus courts
  (QUICKSTART, la visite « What you'll see first », ETHICS) pour chaque langue.

---

### Processus de contribution (accès ouvert par conception)

1. Copiez `locales/en.json` → `locales/<code>.json`, traduisez les valeurs, définissez `_meta.status`.
2. Pour les langues RTL, définissez `_meta.dir: "rtl"`.
3. Exécutez la vérification (prévue) de couverture des clés : signaler les clés manquantes/en trop par rapport à `en.json`.
4. Soumettez. Les clés non traduites se rabattent simplement sur l'anglais jusqu'à ce qu'elles soient complétées.

---

### État

**Phase 1 (terminée) :** le moteur i18n (`i18n.js`), l'ossature de locale pour les 12
langues, et des traductions de référence complètes pour **en/fr/es/de**.

**Phase 1b (terminée, `0.4.0`) :** les chaînes d'interface restantes ont été dotées de clés et
traduites dans **les douze** langues (voir `CHANGES.md` 0.4.0), si bien que chaque
locale de `src/static/locales/*.json` porte désormais l'ensemble complet des clés (vérifié :
12 fichiers, 6 991 clés chacun, aucune manquante). L'honnêteté est inchangée : les noms sont des
noms propres et ne sont pas traduits, et une locale partielle se rabat toujours sur
l'anglais plutôt que de casser.

**Phase 2 (terminée — en attente d'un vrai passage dans un navigateur) :** `i18n.js` est inclus dans
`index.html` (et l'était dans `desk.html` jusqu'au retrait de Desk le 2026-06-10) ; un
sélecteur **Langue** (`#oo-lang-select`) se trouve dans les Paramètres et est branché automatiquement ; l'habillage rendu dynamiquement est traduit automatiquement par
un `MutationObserver` temporisé (aucun appel `apply()` disséminé) ; repasser à l'anglais
restaure les originaux ; RTL via `<html dir>`. La structure et la syntaxe sont validées, mais
le comportement devrait encore être vérifié à l'œil dans un navigateur.

**Phase 3 (suivante) :** étendre `en.json` au catalogue *complet* des chaînes (il couvre actuellement
l'habillage le plus fréquenté), compléter les locales à l'état d'ébauche (communauté) et peaufiner
la mise en page RTL pour `ar`/`ur`.


## Contrat d'export (versionné)

Les exports lisibles par machine portent un contrat stable et autodescriptif (schéma `oo-export-1`,
0.0.8 partie 2 / RM-15) afin que les chaînes de traitement en aval n'aient jamais à deviner :

- **JSON** (`/api/articles/export?format=json`, `/api/links/export.json`) : une enveloppe —
  `{export_schema, kind, app_version, generated_at, query, count, articles|data}`. L'objet
  `query` est la sélection génératrice telle quelle ; la provenance voyage avec les données.
- **CSV** (`/api/articles/export?format=csv`) : pas de ligne de commentaire (elle casserait les lecteurs naïfs) ;
  la même enveloppe voyage sous forme d'en-têtes HTTP (`X-OO-Export-Schema`, `X-OO-App-Version`,
  `X-OO-Generated-At`, `X-OO-Query`). Les colonnes gardent leur ordre, et une nouvelle colonne n'est jamais
  qu'ajoutée à la fin : `Fetched From Host` (élément 61 de la file), l'hôte depuis lequel la page a été récupérée après
  ses redirections, vide lorsqu'il n'a pas été enregistré ; l'export JSON le porte sous `fetched_host`.
- **Graphe de citations** (`/api/links/export.graphml`, `.json`) : le graphe qui-cite-qui
  (articles stockés → domaines enregistrables externes). **Des décomptes uniquement — aucune crédibilité
  inférée, aucun score** ; la mise en garde est intégrée dans le fichier lui-même. Le GraphML s'ouvre dans
  Gephi/yEd/NetworkX.

Les changements de schéma incrémentent `oo-export-N` ; les champs existants ne sont jamais réaffectés en silence. Un champ
ajouté à côté d'eux (une colonne CSV en fin de ligne, une nouvelle clé JSON) laisse les champs de chaque lecteur existant
là où ils étaient, et n'incrémente donc pas le schéma.
