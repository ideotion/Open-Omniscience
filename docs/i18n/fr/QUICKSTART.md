<!-- fr: AI-drafted translation of docs/QUICKSTART.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 17 of 17 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# Démarrage rapide — lancer l'application

Voici le **socle fiable** (l'application est une **alpha** assumée — `v0.5.0`, le
cycle `0.5` du bureau de l'enquêteur, étiqueté le 2026-10-26 ; l'application en cours d'exécution indique sa version
exacte) : ajouter une source → la collecter de façon éthique → la stocker avec sa provenance →
recherche booléenne en texte intégral → exporter. Local d'abord, boucle locale uniquement, aucun compte.

---

## 0. La méthode simple — une commande, puis un double-clic pour lancer

Si vous voulez simplement utiliser l'application (aucune connaissance de la ligne de commande nécessaire ensuite) :

**Linux / macOS** — dans un terminal :

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

**Windows 11** — dans PowerShell. Téléchargez-le, *puis* exécutez-le :

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1
```

Windows Defender peut malgré tout mettre le fichier en quarantaine — il n'est pas signé et il est récent. C'est un
faux positif ; le [§C](#c-sous-windows-11-powershell) explique précisément pourquoi et vous propose une
procédure sans script que rien ne peut supprimer.

La prise en charge de Windows est plus limitée que celle de Linux, et la différence est exposée clairement au
[§C](#c-sous-windows-11-powershell) — lisez-le avant de vous y fier.

> **Inspectez avant de faire confiance.** Envoyer un script directement dans votre shell exécute du code sur votre
> machine. Les deux sont volontairement courts — lisez-les d'abord si vous le souhaitez
> ([scripts/bootstrap.sh](../scripts/bootstrap.sh), [install.ps1](../install.ps1)).
> Ils vérifient la présence de git et de Python 3.13, clonent ce dépôt dans `~/open-omniscience`
> (`%USERPROFILE%\Open-Omniscience` sous Windows), puis passent la main à l'installeur
> inclus dans le dépôt. Vous pouvez tout aussi bien cloner vous-même et lancer `./install.sh` / `install.ps1`.

`install.sh` est **sans questions** — il n'y a **aucun menu de composants**. Une seule commande installe
l'ensemble par défaut raisonnable :

| Installé par défaut | Ce que vous obtenez |
|----------------------|--------------|
| **Socle** *(toujours)* | collecte · stockage avec provenance · recherche booléenne · export |
| **Analyse** | mots-clés · comparaison des cadrages · sentiment |
| **Compression** | stockage sur disque du corpus plus rapide |

La configuration du LLM local / d'Ollama ne fait **pas** partie de l'installeur — elle se trouve entièrement dans
l'onglet **Paramètres → IA** de l'application (voir §E). Modifiez l'ensemble installé avec la
variable d'environnement `OO_COMPONENTS="…"` (par ex. `OO_COMPONENTS="analysis,nlp"`) ; relancer
`./install.sh` est idempotent et n'installe que ce qui manque.

**Ensuite, l'application démarre automatiquement.** L'installeur crée un lanceur **Open Omniscience** (menu des
applications + Bureau) et ouvre l'application dans votre navigateur. Pour la relancer plus tard :

- ouvrez votre menu des applications et recherchez **Open Omniscience**, **ou**
- double-cliquez sur l'icône **Open Omniscience** sur votre **Bureau**.

Une petite fenêtre de terminal apparaît, l'application démarre et votre navigateur s'ouvre sur
**http://127.0.0.1:8000**. **Fermez cette fenêtre (ou utilisez le bouton d'alimentation / d'arrêt de la barre
supérieure) pour arrêter l'application.** (Sous macOS, le lanceur est `Open Omniscience.command` sur votre
Bureau ; sous Windows, c'est un raccourci sur le Bureau et dans le menu Démarrer créé par `install.ps1`.)

**Premier lancement.** Sur une nouvelle installation, l'application vous guide dans une courte configuration unique
*avant* l'interface principale : **choisissez votre langue → lisez et acceptez les conditions juridiques**
(refuser **désinstalle** l'application, après une confirmation saisie au clavier) **→ créez la phrase secrète
de votre corpus**. Le corpus est **chiffré au repos par défaut** (SQLCipher 4) et il n'existe
**aucune récupération** possible d'une phrase secrète perdue (une phrase secrète perdue coûte le temps de la recollecte — le
corpus est reconstruit à partir du web). L'application démarre ensuite **hors ligne (mode avion)** ;
passer en ligne fait apparaître **une fenêtre de consentement** qui nomme l'action et affiche les adresses IP de vos
interfaces locales avant qu'aucune requête ne parte.

Vous préférez le terminal ? `cd ~/open-omniscience && ./scripts/launch.sh` fait la même chose.

**Vérifier ou supprimer l'application plus tard :**
```bash
./install.sh --check        # health report: Python, data dir, database, LLM, launcher
#   (same as: open-omniscience doctor)
./install.sh --uninstall    # remove the virtualenv + launcher; your data is kept
                            #   (it asks separately, defaulting to NO, before deleting data)
```

---

## A. Sur une AppVM Debian de Qubes OS (la cible)

Qubes réinitialise le système de fichiers racine d'une AppVM à chaque démarrage ; seuls `/home` (ainsi que
`/usr/local` et `/rw`) sont conservés. Les paquets système vont donc dans la **TemplateVM**, et
l'application, l'environnement virtuel et la base de données résident sous `/home` dans l'**AppVM**.

**1. Dans la TemplateVM (une seule fois) :**
```bash
sudo ./install.sh --template      # installs python3.13, venv, git, sqlite3, ...
```
Éteignez la TemplateVM, puis **redémarrez l'AppVM** pour que les paquets soient visibles.

**2. Dans l'AppVM (avec votre utilisateur, sans sudo) :**
```bash
./install.sh                      # promptless: Core + Analysis + Compression, then auto-launches
# Qubes AppVM (unattended, creates the launcher, no prompts): Core + Analysis + Compression
./install.sh --appvm
```

**3. Lancez-la (écoute uniquement sur 127.0.0.1) :**
Double-cliquez sur le lanceur **Open Omniscience** (menu des applications / Bureau), ou :
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # starts the app + opens the browser
```
Ouvrez **http://127.0.0.1:8000** dans le navigateur de l'AppVM.

Le serveur n'écoute jamais en dehors de la boucle locale. Pour passer entièrement hors ligne après une exécution, détachez la
NetVM de l'AppVM — l'interface n'a aucune dépendance externe et continue de fonctionner sur les données stockées.

---

## B. Exécution locale pour le développement (tout Linux avec Python 3.13)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # full test suite
open-omniscience                   # serve at http://127.0.0.1:8000
```

Variables d'environnement utiles : `OO_DATA_DIR` (emplacement de la base SQLite et des données), `OO_HOST`/`OO_PORT`,
`OO_FETCH_MIN_INTERVAL` (délai de politesse par hôte, en secondes).

### Sous Tails

Debian, Ubuntu et Tails fournissent les modules standard `venv`/`ensurepip` dans un **paquet apt séparé**, si bien que
`python3 -m venv` échoue tant qu'il n'est pas installé. `install.sh` l'installe désormais
**automatiquement** — sous Tails, cela nécessite un **mot de passe d'administration** (à définir dans
l'écran d'accueil ; il est désactivé par défaut) et une **connexion Tor** fonctionnelle (apt télécharge via
Tor). Désactivez ce comportement avec `OO_NO_APT=1` si vous préférez lancer apt vous-même.

Deux mises en garde honnêtes propres à Tails :

- **Version de Python.** Tails est basé sur Debian 12 → **Python 3.11**, mais l'application cible **3.13**.
  Vous devez disposer d'un interpréteur 3.13 et l'indiquer à l'installeur
  (`OO_PYTHON=python3.13 ./install.sh`) ; la version 3.13 et son paquet `python3.13-venv` ne sont **pas**
  dans les dépôts par défaut de Tails.
- **Amnésie.** Tout ce qui est installé avec apt — et l'intégralité de `.venv` — est **perdu au redémarrage**, sauf
  s'il se trouve sur le Stockage persistant : ajoutez le paquet venv via **Stockage persistant → Logiciels
  supplémentaires**, et conservez le dépôt cloné ainsi que `OO_DATA_DIR` sur le volume persistant.

### Mettre à niveau une base de données existante

Les nouvelles installations construisent le schéma automatiquement (`init_db()`), et la base de données est
marquée au niveau de référence de migration actuel. Quand une future version modifiera le
schéma, mettez à niveau une base existante avec :
```bash
alembic upgrade head
```
`alembic check` indique si les modèles et les migrations sont synchronisés (la CI le vérifie).

---

## C. Sous Windows 11 (PowerShell)

**État réel de la prise en charge — à lire en premier.** Chaque exécution de la CI prouve trois choses sur
`windows-latest` : l'installation des dépendances, la **vérification du démarrage** (toute l'application s'importe)
et le **chiffrement au repos SQLCipher** — ce dernier sur une voie *bloquante*, si bien que
le chiffrement n'est pas une supposition. Rien d'autre n'est prouvé. La **voie pytest de Windows
se bloque** (les dernières exécutions terminées sont restées dans `pytest` pendant 3h21m et ~6h, contre 18 minutes
sous macOS), et **personne n'a parcouru l'interface sous Windows**. Donc : attendez-vous à ce que l'installation
et le lancement fonctionnent, considérez tout ce qui suit le démarrage comme non vérifié, et signalez s'il vous plaît ce qui
ne fonctionne pas. Linux reste la référence pour valider une version.

### 1. Installation

Ouvrez **PowerShell** (aucun droit d'administrateur n'est nécessaire, sauf si Python lui-même doit être
installé). Téléchargez l'installeur, lisez-le si vous le souhaitez, puis exécutez-le :

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
notepad $env:TEMP\oo-install.ps1                                     # optional: see what you are about to run
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1 -Extras analysis
```

Il installe Git et Python 3.13 via `winget` uniquement s'ils sont absents, clone le dépôt dans
`%USERPROFILE%\Open-Omniscience`, construit un `.venv` et vérifie le résultat en
important l'application réelle. Retirez l'option `-Extras` pour obtenir l'ensemble par défaut plus complet, ou consultez
les [options de l'installeur](#options-de-linstalleur).

Vous avez déjà cloné le dépôt ? Lancez-le sur place — il détecte son propre dépôt et saute le clonage :

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> **Pourquoi pas une seule ligne `irm … | iex` ?** Parce que récupérer du code distant et l'exécuter
> directement en mémoire est la façon la plus courante de diffuser des logiciels malveillants sous Windows, si bien que
> Defender juge cette forme hostile quel que soit le contenu du script. Écrire d'abord le fichier
> sur le disque est à la fois moins susceptible d'être bloqué et plus honnête — vous pouvez lire ce qui va s'exécuter
> avant que cela ne s'exécute.

### 2. Si Windows Defender met l'installeur en quarantaine

Il peut supprimer `install.ps1` dès qu'il le voit. C'est un **faux positif**, et vous n'avez pas à
nous croire sur parole — voici précisément pourquoi cela se produit, pour que vous puissiez en juger :

- Le fichier n'est **pas signé et il est récent**, donc la réputation cloud de Defender ne l'a jamais vu.
  Inconnu + non signé suffit à lui seul à déclencher les heuristiques d'apprentissage automatique ; le
  nom de la détection se termine généralement par `!ml`.
- Sa **forme** est celle d'un installeur : il appelle un gestionnaire de paquets, relit `PATH` depuis
  le registre, crée des raccourcis dans le menu Démarrer, et son option `-Uninstall` supprime des
  dossiers. Les programmes malveillants de type « dropper » font exactement la même chose. Le classifieur évalue la forme, pas l'intention.

Ce qu'il ne contient *pas*, et que vous pouvez vérifier vous-même en ~500 lignes lisibles : aucun
`Invoke-Expression`, aucune charge encodée ou obscurcie, aucun `WebClient`, aucune fenêtre
cachée, et aucun téléchargement autre que ce dépôt.

Trois façons d'avancer, de la meilleure à la moins bonne :

1. **Utilisez la procédure sans script** — l'[installation manuelle](#installation-manuelle-sans-script) ci-dessous.
   Les mêmes commandes que celles de l'installeur, aucun fichier à mettre en quarantaine. Cela fonctionne toujours.
2. **Signalez le faux positif** à Microsoft sur
   <https://www.microsoft.com/en-us/wdsi/filesubmission> (choisissez *Software developer*).
   Le traitement prend généralement un jour ou deux et corrige le problème pour tous ceux qui installent
   après vous — pas seulement pour vous.
3. **Excluez le dossier** (Sécurité Windows → Protection contre les virus et menaces → Gérer
   les paramètres → Exclusions). Sachez ce que vous échangez avant de le faire : une exclusion empêche
   Defender d'analyser ce dossier *entièrement*, pour tout fichier, sans limite de durée — pas seulement
   pour ce fichier-là. C'est votre machine et votre décision ; nous ne prétendrons pas que c'est sans contrepartie.

La vraie correction de notre côté est la signature du code, dont nous ne disposons pas encore.

### 3. Lancement

L'installeur crée un raccourci **Open Omniscience** sur votre **Bureau** et dans le
**menu Démarrer**. Double-cliquez dessus : une fenêtre de terminal apparaît, et votre navigateur s'ouvre sur
**http://127.0.0.1:8000** dès que l'application répond réellement. Fermez cette fenêtre (ou utilisez le
bouton d'alimentation de l'application) pour l'arrêter.

Depuis un terminal : `scripts\launch.cmd`.

### 4. Premier lancement

Le même parcours unique que sur toutes les plateformes : **choisissez votre langue → lisez et acceptez les
conditions juridiques → créez la phrase secrète de votre corpus**. Le corpus est **chiffré au repos par
défaut** et il n'existe **aucune récupération** possible d'une phrase secrète perdue. L'application démarre ensuite
**hors ligne (mode avion)** ; passer en ligne fait apparaître **une fenêtre de consentement**.

### Options de l'installeur

| Option | Ce qu'elle fait |
|------|--------------|
| *(aucune)* | Socle + `analysis,compression,columnar`, puis vérification et création des lanceurs |
| `-Path <dir>` | Installer ailleurs que dans `%USERPROFILE%\Open-Omniscience` |
| `-Extras "analysis"` | Choisir les extras pip (`""` pour le socle seul) |
| `-Ref <branch>` | Cloner une branche ou une étiquette précise |
| `-NoPython` | Ne jamais installer Git/Python automatiquement ; échouer avec des instructions à la place |
| `-NoLauncher` | Ne pas créer les raccourcis du Bureau / du menu Démarrer |
| `-Check` | Rapport d'état (identique à `open-omniscience doctor`) |
| `-Uninstall` | Supprimer `.venv` + les lanceurs ; les données sont conservées sauf confirmation séparée |
| `-Yes` | Répondre oui aux questions (sans surveillance) |

Seul `analysis` est prouvé sous Windows par la CI. Si l'ensemble par défaut plus complet ne parvient pas à
s'installer, le script **se replie sur `analysis` et le signale** au lieu d'échouer
en silence ou de prétendre que les extras sont installés.

### Installation manuelle (sans script)

```powershell
# 1. Prerequisites -- skip either line if you already have it
winget install --id Git.Git -e --source winget
winget install --id Python.Python.3.13 -e --source winget --scope user

# 2. Find the interpreter. winget frequently installs Python WITHOUT adding it to
#    PATH, so `python` and `py` can still resolve to nothing on a freshly restarted
#    machine. This reads the record the installer itself writes (PEP 514) -- the same
#    one py.exe uses -- so it answers whatever PATH says:
Get-ChildItem 'HKCU:\SOFTWARE\Python','HKLM:\SOFTWARE\Python' -Recurse -ErrorAction SilentlyContinue |
  Where-Object PSChildName -eq 'InstallPath' |
  ForEach-Object { (Get-ItemProperty $_.PSPath).'(default)' }

$py = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"   # or whatever that printed

# 3. Clone
git clone --depth 1 https://github.com/ideotion/Open-Omniscience.git $HOME\Open-Omniscience
cd $HOME\Open-Omniscience

# 4. Virtual environment. Everything is called by full path on purpose: activating a
#    venv needs Activate.ps1, which the default execution policy blocks.
& $py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[analysis]"

# 5. Verify -- the exact check CI's Windows lane runs
.\.venv\Scripts\python.exe -c "from src.api.main import app; print(sum(1 for _ in app.routes))"

# 6. Run
.\.venv\Scripts\open-omniscience.exe
```

### Remarques propres à Windows

- **Stratégie d'exécution.** La stratégie par défaut bloque `.\.venv\Scripts\Activate.ps1`.
  Rien ici n'en a besoin : appelez `.venv\Scripts\python.exe` par son chemin et le problème
  disparaît entièrement. `-ExecutionPolicy Bypass` sur la ligne de commande couvre l'installeur lui-même.
- **Le `python` qui ouvre le Microsoft Store.** Un Windows 11 neuf contient un
  alias d'exécution factice nommé `python.exe` qui ouvre le Store au lieu d'exécuter du
  code. L'installeur l'ignore (cet alias n'affiche aucune version) et utilise le lanceur `py -3.13`.
  Si vous installez manuellement, préférez `py -3.13` à `python`.
- **Où se trouvent vos données.** Comme il s'agit d'un dépôt de sources cloné, le corpus, les clés de
  signature et les paramètres vont dans **`<repo>\data`** — et non dans `%APPDATA%`. Définissez `OO_DATA_DIR` pour les placer
  sur un autre disque.
- **Permissions du dossier.** Sous Linux, le dossier de données est réservé à votre utilisateur
  (`chmod 0700`) ; cet appel est sans effet sous Windows, si bien que le dossier hérite des ACL
  Windows ordinaires. Sur un PC partagé, restreignez vous-même l'accès à `<repo>\data`. La base de données du corpus
  reste de toute façon chiffrée au repos.
- **SmartScreen / Defender.** Rien ici n'est signé, donc Windows traite tout cela
  comme inconnu : SmartScreen peut afficher un avertissement sur le lanceur, et Defender peut mettre
  `install.ps1` directement en quarantaine — voir le
  [§2](#2-si-windows-defender-met-linstalleur-en-quarantaine) pour savoir de quoi il s'agit et que
  faire. L'analyse en temps réel ralentit aussi sensiblement le premier `pip install`.
- **Port.** Définissez `OO_PORT` avant le lancement pour ne plus utiliser le port 8000 ; `scripts\launch.cmd`
  le respecte.
- **Architecture (x64 / ARM64 / 32 bits).** Détectée et prise en charge par l'installeur ; voici
  ce qu'il décide. Ce qui détermine la réussite de `pip install`, ce n'est pas la
  machine mais les wheels disponibles pour la plateforme de l'*interpréteur*. Mesuré sur
  PyPI le 2026-08-23, pour CPython 3.13, sur l'ensemble des dépendances de ce projet :

  | interpréteur | wheels |
  |---|---|
  | `win-amd64` | **toutes les dépendances.** La seule architecture complète. |
  | `win-arm64` | toutes sauf trois — `cryptography` (socle), `httptools` (socle, via `uvicorn[standard]`) et `statsmodels` (`analysis`) |
  | `win32` | `cryptography` n'en publie aucune |

  Windows sur ARM exécute les binaires x64 de manière transparente, donc un **interpréteur x64 est aussi la bonne
  réponse sur ARM64** — pas un compromis, mais l'ensemble complet. `install.ps1` privilégie donc
  `win-amd64` partout et en obtiendra un si la machine n'en a pas :
  winget en précisant l'architecture, puis winget dans la portée utilisateur, puis le CPython x64 autonome
  de la Python Software Foundation depuis nuget.org — vérifié par rapport à
  l'empreinte SHA-512 que nuget atteste pour lui, décompressé dans
  `%LOCALAPPDATA%\Open-Omniscience\python-x64`, sans élévation de privilèges, sans modification de PATH
  et sans entrée dans le registre. Il se trouve volontairement **en dehors** du dépôt cloné : c'est une ressource
  de la machine, il survit donc à la suppression du dossier de l'application (le `.venv` construit dessus
  cesserait sinon de fonctionner) et un second dépôt cloné avec `-Path` le réutilise. `-Uninstall` le supprime. Une empreinte qui ne correspond pas, ou une
  version pour laquelle nuget n'atteste aucune empreinte, entraîne un **refus**.

  Si toutes les étapes échouent, vous obtenez un arrêt avec la solution en un seul téléchargement, et non une compilation
  Rust de vingt minutes qui se termine par `linker link.exe not found`.

  Un `.venv` existant est **examiné, pas seulement détecté** : il conserve la version et la plateforme de wheels
  de l'interpréteur qui l'a construit, donc un `.venv` laissé par une exécution précédente avec un
  autre Python est remplacé plutôt que réutilisé — sans quoi tout ce qui précède serait
  annulé en silence à la dernière étape. Un `.venv` correspondant est réutilisé tel quel. Relancer
  l'installeur est donc la solution pour une installation inachevée ; rien n'a besoin d'être supprimé à
  la main.

  - **Pourquoi une installation ARM64 native n'est pas activée automatiquement.** Elle nécessiterait de figer `cryptography`
    entre les versions 46.0.0 et 46.0.3, la seule série disposant de wheels ARM64. Cette version comporte
    **13 avis de sécurité ouverts** (dont un concernant OpenSSL lié statiquement, corrigé dans la
    48.0.1). Cette application signe des preuves ; installer cela discrètement serait de la sécurité
    de façade. Si votre machine dispose réellement des Visual Studio Build Tools **et** d'une chaîne
    d'outils Rust, `-AllowSourceBuilds` compile les trois nativement — un choix explicite,
    jamais un réglage par défaut.
  - **Windows 32 bits n'est pas pris en charge**, et c'est une vraie limite plutôt qu'un blocage arbitraire :
    `cryptography` ne fournit aucune wheel `win32`. Windows 64 bits est obligatoire.

---

## D. La boucle de bout en bout (interface ou API)

> **Les sources sont préconfigurées.** Au premier lancement (ou pendant `install.sh --appvm`),
> les catalogues sélectionnés (`configs/sources.yml` ~3 200 médias d'intérêt public, plus
> les catalogues des marchés, du spectre politique et du droit / de la propriété intellectuelle — **~3 395 domaines uniques au
> total**) sont chargés automatiquement — vous pouvez donc commencer la collecte immédiatement.
> (Ces chiffres **évoluent** à mesure que les catalogues s'enrichissent ; le chiffre réel est celui que
> contient actuellement `configs/*.yml`.) Le rechargement est idempotent. Désactivez le chargement automatique avec
> `OO_AUTOSEED=0` ; rechargez manuellement avec `python scripts/seed_sources.py` ou
> `POST /api/sources/seed-defaults`. Les URL des flux et les règles robots changent avec le temps ; le
> collecteur éthique refuse tout ce qu'il ne peut pas confirmer, alors élaguez ou complétez la liste selon
> votre enquête.

**Dans l'interface :** **passez en ligne** une fois (le bouton du mode avion → une fenêtre de consentement) et
**la collecte se fait toute seule** en arrière-plan — répartie entre les langues et les étiquettes
de sources, dans le respect de robots.txt et avec un débit limité. Ensuite, **cherchez dans Explorer** (l'onglet de la barre latérale ; appuyer sur
Entrée dans la barre de commande, barre supérieure ou Ctrl/⌘-K, ouvre Explorer dans un nouvel onglet du navigateur) — l'analyse des articles correspondants apparaît sous les
résultats, où vous filtrez, lisez, lancez des requêtes booléennes et **exportez** (CSV/JSON, annexe
méthodologique, preuves signées). Vous pouvez toujours ajouter une source et *Ingérer (Ingest)* un flux ou une URL unique
manuellement depuis **Paramètres → Avancé → Collecte / Sources**.

**Via l'API :**
```bash
# add a source
curl -X POST http://127.0.0.1:8000/api/sources/ -H 'Content-Type: application/json' \
  -d '{"name":"Example News","domain":"example.com","rss_url":"https://example.com/feed.xml"}'

# ingest its feed (ethical: robots.txt respected fail-closed, rate-limited)
curl -X POST http://127.0.0.1:8000/api/sources/1/ingest

# or ingest a single article URL under that source
curl -X POST http://127.0.0.1:8000/api/ingest -H 'Content-Type: application/json' \
  -d '{"source_id":1,"url":"https://example.com/some-article"}'

# Boolean full-text search (AND / OR / NOT, "phrases", parentheses)
curl 'http://127.0.0.1:8000/api/articles?query=(climate OR energy) AND policy NOT opinion'

# export the filtered set
curl 'http://127.0.0.1:8000/api/articles/export?format=csv&query=climate'
```

Le schéma de l'API lisible par machine se trouve à **http://127.0.0.1:8000/openapi.json**. La page Swagger interactive est désactivée par défaut (elle charge des ressources depuis des hôtes tiers) ; un développeur peut lancer l'application avec `OO_API_DOCS=1` pour l'obtenir à `/docs`.

---

## E. Capacités d'analyse

Toutes fonctionnent en local d'abord et signalent clairement leurs défaillances (jamais d'invention). Schémas complets sur `/openapi.json`.

**LLM local (Ollama).** Configurez-le depuis **Paramètres → IA** : un installeur d'Ollama intégré à l'application,
**vérifié par somme de contrôle** (Linux), plus une **file de téléchargement des modèles** (progression réelle
en octets, annulation), un sélecteur du modèle actif et un panneau de prompts modifiables. Vous pouvez aussi installer
Ollama vous-même depuis **ollama.com** puis lancer `ollama pull llama3.2:3b`. Les téléchargements de modèles sortent
sur **l'internet ouvert via le processus Ollama** (et non via le chemin Tor de l'application) — ce qui est indiqué au moment du
consentement. La pastille LLM de la barre supérieure affiche l'état en direct (cliquez dessus pour ouvrir Paramètres → IA) ; chaque
résultat de recherche dispose des boutons **Résumer** et **Traduire**. API :
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisted with provenance
```
Si Ollama ne tourne pas, ces appels renvoient une erreur HTTP 503 avec un message clair — et non un faux résumé.

**Prix des matières premières + corrélation honnête.**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
La corrélation renvoie un vrai coefficient + une valeur p + n calculés par scipy (Pearson/Spearman),
avec une mise en garde « corrélation ≠ causalité » ; si le recouvrement est trop faible → `insufficient_data`.

**Surveillance.** `POST /api/monitoring/health` effectue de vrais contrôles
d'accessibilité (via le collecteur éthique) ; `GET /api/monitoring/anomalies` signale
les pics de volume d'articles par z-score. **E-mail :** `POST /api/sources/{id}/ingest-email`
(IMAP) intègre les messages dans le même corpus consultable.

**Vérification des métadonnées d'image.** `POST /api/verify/image-metadata`
(envoyez une image) renvoie son format, ses dimensions, ses données EXIF et GPS avec des
constats factuels simples (par ex. présence d'une étiquette de logiciel de retouche, absence d'horodatage de prise de vue). Son périmètre est
présenté honnêtement comme des *contrôles de métadonnées* — **pas** une détection de deepfakes ou de manipulations (celle-ci était
inventée et a été mise en quarantaine hors de l'arborescence de travail ; voir
[docs/QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md)).

**Lots de preuves signés.** Le bouton **Exporter des preuves signées** de la fenêtre d'analyse
(ou `POST /api/reports/evidence`) produit un lot doté d'une racine de Merkle et
signé en Ed25519. N'importe qui peut le vérifier hors ligne, sans cette application :
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = verified
```

**Chaîne de possession.** Le panneau **Chaîne de possession** de l'interface suit une provenance signée
et inviolable (toute altération est détectable) et vous permet de modifier son comportement en cours d'exécution :
signatures post-quantiques, mode d'ancrage (`local` hors ligne ou ancrage Bitcoin via
**OpenTimestamps**) et journalisation automatique à l'ingestion. Ces réglages sont des *préférences* — le
panneau affiche l'état **effectif**, si bien que rien ne prétend être activé quand son extra
n'est pas installé. API :
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # effective state
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # offline-verifiable
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = verified
```
Modèle complet, modèle de menace et mises en garde relatives à la vie privée : [USER_MANUAL.md](USER_MANUAL.md).

---

## Ce que garantit la « collecte éthique »

- Le fichier robots.txt est récupéré, mis en cache par hôte, et **fermé en cas d'échec** : s'il ne peut pas être
  confirmé (erreur réseau, délai dépassé, 5xx, ou un 401/403 restreint), l'URL n'est
  **pas** récupérée.
- Un intervalle minimal par hôte est imposé (en respectant `Crawl-delay`).
- Un seul chemin de récupération, un User-Agent qui s'identifie (en mode protégé, un User-Agent générique, sauf pour les requêtes d'API et de dumps vers les serveurs de Wikimedia), uniquement du HTML pour les articles — aucun contournement brut.
- L'extraction utilise trafilatura ; si aucun véritable corps d'article n'est trouvé, rien n'est stocké
  (aucune ligne inventée « No Title / No Content »).
- Chaque article stocké porte sa provenance : source, URL d'origine, URL canonique,
  empreinte du contenu (utilisée pour le dédoublonnage), heure de récupération.
