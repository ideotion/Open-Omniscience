<!-- TRADUCTION FRANÇAISE (fr) — amorce relue à la main, 2026-06-10. La version
anglaise fait foi. Améliorez ce fichier par une pull request. -->

# Démarrage rapide — lancer le prototype

Ceci est le **noyau digne de confiance** (v0.0.7) : ajouter une source → la
collecter éthiquement → stocker avec provenance → recherche plein-texte
booléenne → exporter. Local d'abord, boucle locale uniquement, sans compte. Le
LLM local et les piliers verticaux arrivent dans des phases ultérieures.

---

## 0. La voie facile — une commande, puis un double-clic pour lancer

Si vous voulez simplement utiliser l'application (aucune connaissance de la
ligne de commande nécessaire ensuite) :

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

> **Inspectez avant de faire confiance.** Envoyer un script dans votre shell
> exécute du code sur votre machine. Le bootstrap est volontairement minuscule —
> lisez-le d'abord si vous le souhaitez
> ([scripts/bootstrap.sh](../../scripts/bootstrap.sh)) ; tout ce qu'il fait est
> vérifier git + Python 3.13, cloner ce dépôt dans `~/open-omniscience`, et
> passer la main au `./install.sh` du dépôt. Vous pouvez tout autant cloner
> vous-même et lancer `./install.sh`.

`install.sh` affiche ensuite un petit menu (une interface en boîtes si
`whiptail` est présent, sinon des invites simples) où vous choisissez :

| Composant | Ce que vous obtenez |
|-----------|---------------------|
| **Noyau** *(toujours)* | collecte · stockage avec provenance · recherche booléenne · export |
| **Outils d'analyse** | mots-clés · comparaison de cadrage · sentiment |
| **Outils LLM locaux** | résumer & traduire via **Ollama** (installe éventuellement Ollama + un petit modèle pour vous) |

Vous pouvez relancer `./install.sh` à tout moment pour **ajouter les outils LLM
plus tard** — il est idempotent et n'installe que ce qui manque.

**Ensuite, double-cliquez simplement pour lancer.** L'installateur propose de
créer un lanceur **Open Omniscience**. Pour démarrer l'application ensuite :

- ouvrez votre menu d'applications et cherchez **Open Omniscience**, **ou**
- double-cliquez l'icône **Open Omniscience** sur votre **Bureau**.

Une petite fenêtre de terminal apparaît, l'application démarre, et votre
navigateur s'ouvre sur **http://127.0.0.1:8000**. **Fermez cette fenêtre pour
arrêter l'application.** (Sur macOS, le lanceur est `Open Omniscience.command`
sur votre Bureau.)

Vous préférez le terminal ? `cd ~/open-omniscience && ./scripts/launch.sh` fait
la même chose.

**Vérifier ou désinstaller plus tard :**
```bash
./install.sh --check        # bilan de santé : Python, répertoire de données, base, LLM, lanceur
#   (équivalent : open-omniscience doctor)
./install.sh --uninstall    # retire le virtualenv + le lanceur ; vos données sont conservées
                            #   (il demande séparément, NON par défaut, avant de toucher aux données)
```

---

## A. Sur une AppVM Debian de Qubes OS (la cible)

Qubes réinitialise le système de fichiers racine d'une AppVM à chaque démarrage ;
seuls `/home` (et `/usr/local`, `/rw`) persistent. Les paquets système vont donc
dans la **TemplateVM**, et l'application + le virtualenv + la base vivent sous
`/home` dans l'**AppVM**.

**1. Dans la TemplateVM (une fois) :**
```bash
sudo ./install.sh --template      # installe python3.13, venv, git, sqlite3, ...
```
Éteignez la TemplateVM, puis **redémarrez l'AppVM** pour que les paquets soient
visibles.

**2. Dans l'AppVM (avec votre utilisateur, sans sudo) :**
```bash
./install.sh                      # menu interactif : composants, lanceur optionnel
# ou sans interaction (Noyau + Analyse, crée le lanceur) :
./install.sh --appvm
```

**3. Lancez-la (n'écoute que sur 127.0.0.1) :**
Double-cliquez le lanceur **Open Omniscience** (menu d'applications / Bureau), ou :
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # démarre l'app + ouvre le navigateur
```
Ouvrez **http://127.0.0.1:8000** dans le navigateur de l'AppVM.

Le serveur n'écoute jamais hors de la boucle locale. Pour passer entièrement
hors-ligne après une collecte, détachez la NetVM de l'AppVM — l'interface n'a
aucune dépendance externe et continue de fonctionner sur les données stockées.

---

## B. Exécution de développement locale (tout Linux avec Python 3.13)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # suite de tests complète
open-omniscience                   # sert sur http://127.0.0.1:8000
```

Variables d'environnement utiles : `OO_DATA_DIR` (où vivent la base SQLite + les
données), `OO_HOST`/`OO_PORT`, `OO_FETCH_MIN_INTERVAL` (délai de politesse par
hôte, en secondes).

### Mettre à niveau une base existante

Les installations fraîches construisent le schéma automatiquement (`init_db()`),
et la base est estampillée à la référence de migration courante. Quand une
version future change le schéma, mettez à niveau une base existante avec :
```bash
alembic upgrade head
```
`alembic check` indique si les modèles et les migrations sont synchronisés (la
CI le garantit).

---

## C. La boucle de bout en bout (UI ou API)

> **Les sources sont préconfigurées.** Au premier lancement (ou pendant
> `install.sh --appvm`), le catalogue organisé de `configs/sources.yml`
> (~1 900 médias d'intérêt public, ~1 780 uniques) est semé automatiquement —
> vous pouvez donc commencer à collecter immédiatement. Le re-semis est
> idempotent. Désactivez le semis automatique avec `OO_AUTOSEED=0` ; re-semez
> manuellement avec `python scripts/seed_sources.py` ou
> `POST /api/sources/seed-defaults`. Les URL de flux et les politiques robots
> changent avec le temps ; le collecteur éthique refuse tout ce qu'il ne peut
> pas confirmer — élaguez/étendez la liste selon votre enquête.

**Dans l'interface :** choisissez (ou ajoutez) une source → *Collecter* un flux
ou une URL unique → *Rechercher* avec des opérateurs booléens → *Exporter*
CSV/JSON.

**Via l'API :**
```bash
# ajouter une source
curl -X POST http://127.0.0.1:8000/api/sources/ -H 'Content-Type: application/json' \
  -d '{"name":"Example News","domain":"example.com","rss_url":"https://example.com/feed.xml"}'

# collecter son flux (éthique : robots.txt respecté, fermé par défaut, débit limité)
curl -X POST http://127.0.0.1:8000/api/sources/1/ingest

# ou collecter une seule URL d'article sous cette source
curl -X POST http://127.0.0.1:8000/api/ingest -H 'Content-Type: application/json' \
  -d '{"source_id":1,"url":"https://example.com/some-article"}'

# recherche plein-texte booléenne (AND / OR / NOT, "phrases", parenthèses)
curl 'http://127.0.0.1:8000/api/articles?query=(climate OR energy) AND policy NOT opinion'

# exporter l'ensemble filtré
curl 'http://127.0.0.1:8000/api/articles/export?format=csv&query=climate'
```

Documentation interactive de l'API : **http://127.0.0.1:8000/docs**.

---

## D. Capacités d'analyse

Toutes sont locales d'abord et se dégradent bruyamment (jamais de fabrication).
Schémas complets sur `/docs`.

**LLM local (Ollama) — Phase 2.** Le plus simple : choisissez **Outils LLM
locaux** dans `./install.sh` (il peut installer Ollama et tirer un petit modèle
pour vous). Manuellement : installez Ollama, puis `ollama pull llama3.2:3b`.
L'en-tête de l'interface montre l'état du LLM ; chaque résultat de recherche a
des boutons **Résumer** et **Traduire**. API :
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisté avec provenance
```
Si Ollama ne tourne pas, ces appels renvoient HTTP 503 avec un message clair —
pas un faux résumé.

**Prix des matières premières + corrélation honnête — Phase 3.**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
La corrélation renvoie un vrai coefficient + valeur p + n via scipy
(Pearson/Spearman), avec l'avertissement « corrélation ≠ causalité » ; trop peu
de recouvrement → `insufficient_data`.

**Surveillance — Phase 4.** `GET /api/monitoring/health` effectue de vraies
vérifications d'accessibilité (par le collecteur éthique) ;
`GET /api/monitoring/anomalies` signale les pics de volume d'articles par
z-score. **Courriel :** `POST /api/sources/{id}/ingest-email` (IMAP) verse les
messages dans le même corpus interrogeable.

**Vérification des métadonnées d'image — Phase 4.**
`POST /api/verify/image-metadata` (téléversez une image) renvoie format,
dimensions, EXIF et GPS avec des observations factuelles claires (p. ex.
étiquette de logiciel d'édition présente, pas d'horodatage de capture). Cadré
honnêtement comme des *vérifications de métadonnées* — **pas** de détection de
deepfake/manipulation (celle-ci était fabriquée et est en quarantaine).

**Lots de preuves signés — Phase 5.** Le bouton **Exporter des preuves
signées** du panneau de recherche (ou `POST /api/reports/evidence`) produit un
lot à racine de Merkle, signé Ed25519. N'importe qui peut le vérifier hors
ligne, sans cette application :
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = vérifié
```

**Chaîne de possession — Phase 5.** Le panneau **Preuves & possession** suit la
provenance signée, inviolable, et vous laisse régler son comportement à chaud :
signatures post-quantiques, mode d'ancrage (`local` hors-ligne vs ancrage
Bitcoin **OpenTimestamps**), et journalisation automatique à la collecte. Les
interrupteurs sont des *préférences* — le panneau montre l'état **effectif**,
donc rien ne prétend être actif quand son extension n'est pas installée. API :
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # état effectif
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # vérifiable hors-ligne
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = vérifié
```
Modèle complet, modèle de menace et réserves de confidentialité :
[USER_MANUAL.md](../../USER_MANUAL.md).

---

## Ce que garantit la « collecte éthique »

- robots.txt est récupéré, mis en cache par hôte, et **fermé par défaut** : s'il
  ne peut pas être confirmé (erreur réseau, délai dépassé, 5xx, ou un 401/403
  restrictif), l'URL n'est **pas** récupérée.
- Un intervalle minimal par hôte est appliqué (en honorant `Crawl-delay`).
- Un seul chemin de récupération, un User-Agent qui s'identifie, HTML seulement
  pour les articles — aucun contournement brut.
- L'extraction utilise trafilatura ; si aucun vrai corps d'article n'est trouvé,
  rien n'est stocké (pas de lignes fabriquées « Sans titre / Sans contenu »).
- Chaque article stocké porte sa provenance : source, URL d'origine, URL
  canonique, empreinte du contenu (utilisée pour la déduplication), heure de
  récupération.
