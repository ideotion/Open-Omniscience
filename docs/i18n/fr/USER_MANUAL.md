<!-- fr: AI-drafted translation of docs/USER_MANUAL.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 124 of 124 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# Open Omniscience — Manuel d'utilisation

*Une plateforme de renseignement open source, éthique et locale d'abord, pour le
journalisme d'investigation.* Ce manuel est le guide accessible, de bout en bout : ce
qu'est l'application, comment l'installer et la lancer, et une visite de **chaque onglet,
commande, paramètre et procédure**, suivie d'une référence technique (emplacement des
données, variables d'environnement, l'API HTTP complète) et d'une section de dépannage.

> **En une phrase :** Open Omniscience rassemble de façon éthique des actualités (ainsi que
> des modifications de Wikipedia et des cours de marché) dans une base de données SQLite
> unique, consultable, dédoublonnée et dont la provenance est tracée, sur *votre* machine ;
> elle vous permet de les analyser (recherche, tendances, cartes, cadrage, résumés par LLM
> local) et peut produire des **preuves signées cryptographiquement, vérifiables hors
> ligne**, de ce qu'elle contenait et à quel moment.

**Les engagements de conception qui façonnent tout ce qui suit :**

- **Local d'abord et privé.** Tout fonctionne sur `127.0.0.1` (boucle locale uniquement).
  Aucun compte, aucune télémétrie, rien ne quitte votre machine — le seul trafic sortant
  est celui du collecteur éthique qui récupère les sources que vous lui indiquez (et, si
  vous l'acceptez, Wikipedia/OpenTimestamps/Ollama).
- **Uniquement des chiffres honnêtes.** Chaque chiffre est un vrai `COUNT(*)`, une vraie
  taille en octets sur le disque, ou un vrai agrégat statistique accompagné de la taille
  de son échantillon et de sa mise en garde. L'application préfère afficher une erreur
  plutôt qu'inventer une valeur. (Plusieurs anciennes fonctions de « détection par IA »
  qui fabriquaient des scores ont été retirées — voir `docs/HISTORY.md`.)
- **Collecte éthique.** Un seul chemin de récupération. Le fichier `robots.txt` est
  respecté **en échec fermé** (en cas de doute, l'application ne récupère *pas*), le débit
  de chaque hôte est limité, et rien n'est stocké tant que le corps réel d'un article n'a
  pas été extrait.

---

## Table des matières

1. [Installation et premier lancement](#1-installation-et-premier-lancement)
2. [La visite en 60 secondes](#2-la-visite-en-60-secondes)
3. [Les outils, un par un](#3-les-outils-un-par-un)
   - [Accueil](#30-accueil) · [Activité et Gestionnaire de tâches](#30a-activité-et-le-gestionnaire-de-tâches) ·
     [Fil](#30b-fil) ·
     [Explorer : la recherche](#31-recherche) · [Explorer : l'analyse](#31a-analyse--la-fenêtre-des-corpus) · [Collecter](#32-collecter-dans-paramètres--avancé--collecte) ·
     [Sources](#33-sources-dans-paramètres--avancé--sources) · [Bibliothèque](#34-bibliothèque) · [Marchés](#35-marchés) ·
     [Indices](#35a-indices) · [Analyses](#36-analyses) ·
     [Carte du monde](#36a-carte-du-monde) · [Agenda](#36b-agenda) ·
     [Sources vivantes](#36b-sources-vivantes) · [Climat](#36c-climat) · [Observatoire](#36d-observatoire) ·
     [Wikipédia](#37-wikipedia-dans-paramètres--wikipédia) ·
     [Preuves & possession](#38-preuves-et-chaîne-de-possession) · [Paramètres](#39-paramètres) ·
     [Aide & docs](#310-aide--docs)
4. [Procédures courantes (mode d'emploi)](#4-tâches-courantes-mode-demploi)
5. [Référence technique](#5-référence-technique)
   - [Où se trouvent vos données](#51-où-se-trouvent-vos-données) ·
     [Variables d'environnement](#52-variables-denvironnement) ·
     [Extensions facultatives](#53-extensions-optionnelles) ·
     [L'API HTTP](#54-lapi-http) ·
     [La mémoire sur une petite machine](#55a-la-mémoire-sur-une-petite-machine--le-seul-vrai-plafond)
6. [Dépannage](#6-dépannage)
7. [Glossaire](#7-glossaire)

---

## 1. Installation et premier lancement

Open Omniscience vise **Python 3.13** sur un Linux de la famille Debian (elle est conçue
pour une AppVM Debian sous **Qubes OS**, mais fonctionne sur n'importe quel Linux récent).
C'est une application mono-utilisateur, locale d'abord.

### Le plus simple : l'installateur en une ligne

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

Cette commande clone le dépôt et lance `./install.sh`, qui est **sans interruption — il ne
pose aucune question**. Il installe l'ensemble par défaut — le **Cœur** (collecte,
stockage, recherche, export), plus l'extension **Analyse** (statistiques, analyse des
mots-clés et des entités, corrélation avec les marchés via scipy/scikit-learn ; spaCy en
option pour une vraie reconnaissance des entités nommées), plus la compression — puis crée
un lanceur **Open Omniscience** dans le menu de vos applications et sur le Bureau, et
**lance automatiquement** l'application dans votre navigateur à l'adresse
`http://127.0.0.1:8000`. (Définissez `OO_COMPONENTS` pour choisir un autre ensemble de
composants.) Résumer et traduire sur l'appareil nécessite un modèle local — installez
**Ollama** depuis **Paramètres → IA** (installateur vérifié intégré à l'application) ou
depuis ollama.com. Vous pouvez relancer `install.sh` à tout moment.

> Inspectez toujours un script avant de l'envoyer à un shell. Le
> [`bootstrap.sh`](../scripts/bootstrap.sh) est minuscule ; vous pouvez aussi cloner le
> dépôt et lancer `./install.sh` vous-même.

**Sous Qubes :** lancez `sudo ./install.sh --template` dans la TemplateVM, redémarrez
l'AppVM, puis lancez `./install.sh` dans l'AppVM.

### Installation manuelle / pour développeurs

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"     # core + analysis + test tooling
pytest -q                            # full suite should be green
open-omniscience                     # serves http://127.0.0.1:8000
```

Au premier lancement, l'application **amorce automatiquement un catalogue mondial
(~3 400 domaines uniques couvrant l'actualité, les marchés, l'ensemble du spectre
politique et les portails officiels du droit et de la propriété intellectuelle)** pour que
vous ayez immédiatement quelque chose à collecter, initialise la base de données SQLite et
l'index FTS, et (si c'est activé) démarre le planificateur en arrière-plan.

### La page du premier lancement (langue → conditions → phrase secrète)

Sur une **nouvelle installation**, la toute première chose que vous voyez est la page de
configuration autonome et hors ligne à l'adresse `/unlock`, en trois étapes **avant
l'ouverture de l'application** :

1. **Choisissez votre langue** — choisissez parmi les 12 langues de l'interface ; toute la
   page change de langue en direct et votre choix est repris dans l'application.
2. **Lisez et acceptez les documents juridiques** (affichés dans votre langue ; la version
   française fait foi). **Accepter et continuer** pour poursuivre, ou **Refuser** — refuser
   **désinstalle l'application** (un sous-panneau de confirmation à saisir garantit qu'un
   clic accidentel n'efface jamais rien).
3. **Créez la phrase secrète de votre corpus.** Les nouvelles bases de données sont
   **chiffrées sur le disque avec SQLCipher par défaut** ; vous choisissez donc ici **LA
   phrase secrète** (saisie deux fois pour confirmation). C'est un secret unique et stable,
   comme un identifiant, **sans récupération possible et sans autre moyen de
   déchiffrement** — une phrase secrète perdue coûte le temps de refaire la collecte, car
   le corpus se reconstruit à partir du web. La justification complète et le modèle de
   menace, exposé honnêtement, se trouvent dans
   [Paramètres → Avancé → Sécurité](#39-paramètres).

Aux **lancements suivants**, le stockage existe déjà : vous arrivez directement sur une
seule invite de **déverrouillage** demandant la même phrase secrète. Les exécutions sans
interface ou scriptées la fournissent avec `OO_DB_PASSPHRASE` ; le fonctionnement en clair
reste un choix explicite (`OO_DB_PLAINTEXT=1`).

### La configuration guidée et l'écran d'Accueil

Une fois entré, une **configuration guidée (guided setup)** unique dans l'application (une
boîte de dialogue par étapes) peut vous accompagner dans vos premiers choix : elle s'ouvre
sur une étape **Langue** et se termine sur une étape **Terminer** qui indique que
l'application **démarre hors ligne** et propose un bouton *« Passer en ligne et lancer la
collecte »*. Passer en ligne passe toujours par la fenêtre de consentement réseau
(ci-dessous) — le guide se contente de vous y inviter ; il ne se connecte jamais de
lui-même. Vous pouvez le relancer à tout moment depuis **Paramètres → Général →
« Relancer le guide de premier lancement. »**

Ensuite, l'application s'ouvre sur **Accueil**, qui commence par votre **Briefing** — un
fil de **Pistes** honnêtes (voir [3.0 Accueil](#30-accueil)) — au-dessus d'un bandeau compact
**d'un coup d'œil (at-a-glance)** affichant des décomptes en direct. Vous n'avez rien à
amorcer à la main : le catalogue sélectionné **s'amorce automatiquement au démarrage**, et
passer en ligne **lance automatiquement la collecte**, après quoi la **Recherche** contient
de vrais articles.

**L'enveloppe de l'application.** La navigation se fait dans une **barre latérale gauche**
— une **liste à plat** des outils de données : **Accueil · Fil · Explorer · Analyses ·
Observatoire · Carte du monde · Gouvernements · Agenda · Climat · Indices · Matières
premières *(avancé)* · Sources vivantes · Bibliothèque** (à la profondeur d'interface **Essentiel**,
seuls Accueil et Fil sont épinglés et les autres se trouvent derrière une ligne libellée
**Afficher plus** ; voir [3.](#3-les-outils-un-par-un)) (elle se réduit à une colonne
d'icônes sur les fenêtres étroites, mais ne disparaît jamais). Un bouton **Paramètres** se
trouve **en bas de la barre latérale** (avec le bouton de réduction), et une **barre
supérieure minimale** au-dessus du contenu contient :

- **La barre de recherche / de commandes (⌘K / Ctrl-K).** Tapez pour aller à n'importe quel
  outil, lancer une action courante, ouvrir n'importe quel document — ou faire une
  recherche fédérée dans vos données (voir [3.1 Recherche](#31-recherche)). La recherche
  complète, avec son analyse, est l'onglet **Explorer**.
- **État en direct (Live status)** — un point indiquant la santé du serveur et une pastille
  **LLM** (cliquez dessus pour ouvrir Paramètres → IA).
- **Gestionnaire de tâches** — un bouton qui ouvre la
  [fenêtre du gestionnaire de tâches](#30a-activité-et-le-gestionnaire-de-tâches).
- **Mode avion** — l'unique interrupteur réseau marche/arrêt (un pictogramme d'avion dont le
  *remplissage* indique l'état ; rempli = hors ligne). Au premier lancement, tant que vous
  êtes hors ligne, une petite bulle d'aide le désigne et vous invite à passer en ligne
  quand vous êtes prêt.
- **Sélecteur de langue** — les 12 langues dans un seul menu (le drapeau n'est qu'un
  repère ; c'est le nom natif qui identifie la langue). Un clic retraduit toute
  l'interface.
- **Aide (?)** — ouvre le lecteur de documentation intégré (ce manuel et les autres
  guides), avec recherche et entièrement hors ligne. (Les pages interactives Swagger/ReDoc
  sont désactivées par défaut, voir §5.4.)
- **Éteindre (bouton marche/arrêt)** — arrête proprement le serveur ; vos données ne sont
  pas touchées, et l'interface est remplacée par un message « vous pouvez fermer cet
  onglet ». (Ce n'est *pas* une désinstallation ni un effacement.)

Les **Paramètres** s'ouvrent depuis le **bouton Paramètres en bas de la barre latérale**
(la palette de commandes y mène aussi directement) ; voir [3.9 Paramètres](#39-paramètres).
L'**Apparence** (**Paramètres → Graphismes**) propose **14 thèmes de couleurs + Système**,
une couleur d'accent, la densité, un sélecteur de polices intégrées et la réduction de la
barre latérale. Tout est stocké localement ; rien n'est transmis.

### Ajouts récents (cycle de test en conditions réelles 0.0.8, juin 2026)

> **Instantané historique.** Cette section décrit l'application telle qu'elle était au
> cycle 0.0.8 (juin 2026) ; l'application a évolué depuis. `CLAUDE.md` est la source de
> référence à jour pour ce qui a été livré ensuite — voir `docs/ledger/shipped.csv` pour
> l'index.

- **L'interrupteur réseau est un bouton de mode avion (barre supérieure) :** un unique
  pictogramme d'avion, toujours le même, dont **le remplissage indique l'état** — rempli
  signifie que le mode hors ligne est engagé (toute nouvelle requête réseau est refusée
  immédiatement ; une requête déjà en cours peut se terminer). **Chaque retour en ligne
  demande d'abord votre accord** : une unique fenêtre de consentement indique quelle action
  a besoin du réseau et liste les **adresses des interfaces locales** de votre machine
  (lues dans les tables du noyau lui-même — jamais par un appel réseau ; l'application
  s'abstient délibérément d'interroger un service « quelle est mon IP », car ce serait déjà
  du trafic). Au-delà de ces adresses locales, internet voit l'adresse publique que
  présente votre fournisseur d'accès ou votre VPN. Lancer une passe de collecte, importer
  des flux de marché, ajouter une page Wikipedia suivie ou télécharger une archive passent
  tous par ce même consentement lorsque vous êtes hors ligne, et le bouton se redessine
  immédiatement à chaque changement d'état — il n'attend jamais la prochaine
  interrogation périodique.

  **Le mode avion est une garantie au niveau des sockets, pas seulement une convention
  appel par appel.** Pour vous informer en toute transparence de la protection propre à
  l'application : tant que le mode avion est engagé, l'application installe un **garde
  global au processus** sur les appels de socket de bas niveau
  (`getaddrinfo` / `create_connection` / `connect`), de sorte que **toute** tentative
  d'atteindre une adresse autre que la boucle locale — depuis n'importe quel chemin de
  code, une bibliothèque tierce ou une prérésolution DNS — échoue avant que le vrai socket
  ne soit utilisé. La boucle locale (127/8, ::1, `localhost`) et les sockets Unix passent
  toujours, si bien que le serveur de l'application, un Ollama local et la base de données
  sur fichier continuent de fonctionner. Ce garde est transparent tant que vous êtes en
  ligne (aucun coût pendant la collecte). Définissez `OO_AIRPLANE_SOCKET_GUARD=0` pour le
  désactiver (pour un déploiement inhabituel qui redirige la boucle locale ailleurs).
- **Carte mentale à niveaux et nuage de mots (Analyses) :** une véritable carte mentale
  radiale (centre → branches → feuilles vers l'extérieur) sur trois niveaux de zoom
  (mots-clés ↔ familles ↔ super-groupes), avec un nuage de mots comme seconde vue, une
  commande de plage de dates, un curseur de taille du texte et ⛶ Agrandir. La taille de
  police représente toujours le volume d'articles partagés.
- **Super-groupes prédéfinis :** un ensemble de départ intégré (élaboré à partir de
  journaux de terrain réels) est amorcé au démarrage ; vos propres modifications et
  suppressions l'emportent toujours.
- **La Carte du monde est désormais une carte choroplèthe (ooMap) :** l'onglet colore les
  pays selon une dimension mesurée (sources · articles · mentions de mots-clés · tonalité),
  avec des commandes intégrées à la carte pour la mesure, la granularité pays↔continent,
  une surcouche Lieux, une couche Signaux avec un curseur pour le moment observé, une
  couche IP des serveurs, le zoom à la molette, le déplacement par glisser et ⛶ Agrandir.
  Voir [3.6a](#36a-carte-du-monde).
- **Dates d'événements, lieux, personnes et organisations extraits du texte :**
  l'extracteur de dates lit six langues, les formats numériques et les expressions
  ancrées (« hier », un jour de la semaine seul, « 11 juin ») ; l'extracteur de lieux
  trouve les villes du répertoire géographique et les noms de pays ; l'extracteur
  d'entités fait ressortir les **personnes** et les **organisations** comme deux classes
  délibérément distinctes (un nom précédé d'un titre de civilité et un sigle répété
  répondent à des questions différentes — chaque entrée indique quelle règle l'a trouvée).
  Tous alimentent l'en-tête de métadonnées du lecteur d'articles, qui sépare **« Depuis la
  source »** de **« Déduit par cette application — moins fiable »** (cadre en pointillés) :
  les extractions sont des candidats lexicaux avec l'extrait qui les justifie, jamais des
  faits confirmés.
- **Exports de mots-clés par langue :** le journal de diagnostic des mots-clés est plafonné
  à 5 000 mots-clés *par langue dominante*, afin que les vocabulaires des langues
  minoritaires ne soient jamais évincés de l'analyse par le volume de l'anglais.
- **Archives hors ligne de Wikipedia :** la liste des éditions se charge de nouveau
  correctement et permet la sélection multiple — téléchargez plusieurs éditions
  linguistiques en une seule exécution mise en file d'attente.
- **17 thèmes et des polices open source intégrées :** neuf nouvelles palettes (Arctique,
  Solar, Forest, Aubergine, Garnet, Cyber, Mist, Dawn, Mint) rejoignent l'ensemble
  d'origine, et six polices SIL-OFL sont désormais livrées **dans l'application**
  (Cantarell, Inter, Outfit, Manrope, JetBrains Mono, Source Serif 4 — voir
  `src/static/fonts/README.md`) : rien à télécharger, aucune requête de police ne quitte
  jamais votre machine. Certains thèmes sont associés à une police (Arctique→Inter,
  Cyber→Outfit, Sepia/Paper→Source Serif) ; le nouveau sélecteur **Police de caractères**
  dans Paramètres → Graphismes remplace n'importe laquelle d'entre elles, et le lecteur
  d'articles utilise la police à empattements intégrée. Les éléments de formulaire
  (curseurs, cases à cocher, listes déroulantes natives) suivent désormais eux aussi le
  thème.

**Une remarque sur « FOOS ».** Les onglets de navigateur que l'application ouvre
(investigations de pistes, le lecteur d'articles local) portent le suffixe **« · FOOS » —
Free Open OmniScience** : assez court pour les barres d'onglets étroites tout en gardant
l'application identifiable. C'est le nom de travail de la version alpha ; un vrai
changement de nom pourra venir plus tard.

**Une icône, une interface.** L'installateur crée **un seul lanceur** — **Open
Omniscience** → `http://127.0.0.1:8000/` — une application à barre latérale facile à
découvrir et à personnaliser, qui s'adapte en douceur à la taille de votre fenêtre (la
barre latérale se réduit à une colonne d'icônes sur les fenêtres plus étroites). Une
seconde interface expérimentale (« Desk ») a existé lors de cycles précédents et a été
retirée en 0.0.8 ; son historique se trouve dans [`DESIGN.md`](DESIGN.md).

**Fonctionnement en arrière-plan, navigateur fermé.** L'application vit dans la fenêtre de
son lanceur, pas dans l'onglet du navigateur. Vous pouvez fermer le navigateur à tout
moment : la collecte, les téléchargements Wikipedia et de cartes, les sauvegardes vers un
dossier ou un disque, les importations, les tâches d'IA (téléchargements de modèles,
détection de langue, vérifications par l'IA) et l'archive de diagnostic continuent tous de
tourner. C'est ainsi qu'on laisse une machine collecter pendant des jours tout en
économisant la mémoire que prend un navigateur (souvent 0,5 à 1 Go, ce qui compte sur une
petite VM).

Tant que l'application tourne, la fenêtre du lanceur affiche un **panneau**, qui reste là
aussi longtemps que l'application tourne : il n'y a qu'une seule fenêtre, sous Linux,
macOS comme Windows. En haut, il indique si l'application est verrouillée, l'état du
réseau et de la collecte, la mémoire et le CPU du serveur, et ce qui est en cours. En
dessous se trouve un **journal d'activité** : une ligne horodatée pour chaque événement (la
collecte démarre ou s'arrête, un téléchargement atteint 40 %, une sauvegarde se termine, le
réseau passe hors ligne, l'application cesse de répondre puis répond à nouveau), ajoutées
les unes après les autres aussi longtemps que l'application tourne, la plus récente en bas.
Remontez avec les flèches, PgUp et PgDn ou la molette de la souris ; End ramène à la ligne
la plus récente. Cliquez sur les boutons, ou appuyez sur la touche indiquée sur chacun :

- **Ouvrir l'interface (Open UI) (o)** rouvre l'application dans votre navigateur.
- **Suspendre la collecte (Pause collection) (p)** arrête la collecte et met l'application
  en mode avion. Pour reprendre, ouvrez l'interface : le passage en ligne passe toujours
  par sa fenêtre de consentement, jamais par le terminal.
- **Messages du serveur (Server messages) (l)** affiche les messages propres du serveur
  (pas sous Windows) ; appuyez sur n'importe quelle touche pour revenir.
- **Arrêter l'application (Stop app) (s)** arrête l'application, après un second appui.
  Il nomme les tâches qui prendraient fin.

Le panneau ne se ferme pas de lui-même tant que l'application tourne, même lorsque
l'application est occupée ou que l'ordinateur était en veille et que l'application met du
temps à répondre : il indique depuis combien de temps l'application est silencieuse et
continue d'essayer. Il se termine quand l'application se termine.
Le panneau ne demande jamais votre phrase secrète : si l'application est verrouillée, il
le dit, et vous la déverrouillez dans le navigateur. Fermer la fenêtre du lanceur ou
appuyer sur Ctrl-C arrête toujours l'application, comme avant. Définissez `OO_PANEL=0`
pour démarrer sans le panneau. Les outils d'IA qui répondent dans la page (résumé ou
traduction en masse, extraction de mots-clés par IA, exécutions de prompts) continuent eux
aussi une fois l'onglet fermé, et apparaissent dans le panneau. Pour en arrêter un, ouvrez
l'interface et appuyez sur **Arrêter** sur sa ligne dans le gestionnaire de tâches, ou sur
**Annuler** dans la page (le bouton Arrêter l'application du panneau arrête toute
l'application) : il s'arrête après l'article en cours de traitement, et les articles déjà
traités restent enregistrés. L'index des mots-clés des articles qu'Analyses n'a pas encore
indexés se met aussi à jour de lui-même quand l'application est inactive. Seules deux
choses exigent que l'onglet reste ouvert : un envoi de fichier que vous faites depuis le
navigateur, et un fichier que le navigateur est en train de télécharger. Sous Windows, le
panneau s'ouvre dans une fenêtre à part (la fermer n'arrête pas l'application). Il a
besoin du module curses de Python, que Windows obtient avec le paquet windows-curses :
l'installateur l'ajoute sur les PC Intel et AMD, et sur une installation antérieure à
cette version vous pouvez l'ajouter avec
`.venv\Scripts\python -m pip install windows-curses` dans le dossier de l'application.
Windows sur ARM n'en a pas encore de version compilée ; l'application y démarre donc sans
le panneau.

---

## 2. La visite en 60 secondes

La boucle principale est :

> **Choisir/ajouter une source → Collecter → Explorer (rechercher et analyser) → Exporter / signer.**

1. **Paramètres → Avancé → Sources** — un catalogue mondial est déjà amorcé ; ajoutez les
   vôtres si vous le souhaitez.
2. **Paramètres → Avancé → Collecte** — récupérez le flux RSS d'une source ou collez l'URL
   d'un article. Ou laissez le **planificateur** le faire automatiquement à intervalles
   réguliers. La collecte a besoin du réseau : le bouton avion de la barre supérieure doit
   être désactivé, et le désactiver vous demande d'abord votre accord.
3. **Accueil** et **Fil** — lisez ce qui est arrivé : Accueil sous forme de signaux mesurés
   (Pistes), Fil sous forme de simple flux d'articles.
4. **Explorer** — recherche booléenne en texte intégral dans tout ce que vous avez
   rassemblé ; l'analyse des articles correspondants apparaît sous les résultats.
5. **Analyses / Observatoire / Carte du monde / Gouvernements / Agenda / Climat / Indices /
   Matières premières / Sources vivantes** — des vues facultatives sur le corpus et sur des
   données publiques (motifs, espace-temps, droit, dates, relevés climatiques, prix, ce qui
   a changé).
6. **Exporter** — CSV/JSON, ou un **lot de preuves signé** que n'importe qui peut vérifier
   hors ligne.

Choisissez n'importe quel outil dans la barre latérale, ou appuyez simplement sur **⌘K /
Ctrl-K** et tapez où vous voulez aller. Pour un court parcours des onglets de la barre
latérale à votre profondeur d'interface, choisissez **Faire la visite** (Paramètres →
Général, Aide & docs, ou la palette de commandes). Elle ne démarre que si vous le demandez,
ne modifie rien et ne garde aucune trace de son exécution. La vue active se rafraîchit
d'elle-même en direct (toutes les quelques secondes) tant qu'elle est à l'écran, et les
actions sont confirmées par de petites notifications dans le coin.
Les actions destructrices demandent toujours confirmation d'abord.

---

## 3. Les outils, un par un

La barre latérale est une **liste à plat** des outils de données (de haut en bas) :

- **Accueil · Fil · Explorer · Analyses · Observatoire · Carte du monde · Gouvernements ·
  Agenda · Climat · Indices · Matières premières *(avancé)* · Sources vivantes · Bibliothèque** — plus
  le bouton **Paramètres** en bas de la barre latérale. L'aide s'ouvre avec le bouton **?**
  de la barre supérieure. Il n'y a pas d'onglet « Collecter » : la collecte se trouve dans
  les Paramètres.
- **Explorer** est une seule page : le champ de recherche en haut, et l'analyse des
  articles correspondants sous les résultats dès qu'une recherche aboutit (voir
  [3.1](#31-recherche) et [3.1a](#31a-analyse--la-fenêtre-des-corpus)). Un mot-clé cliqué
  dans l'application ouvre son analyse sur cette page ; un mot-clé du lecteur d'articles,
  le bouton **Ouvrir le corpus ↗** d'une Piste de l'Accueil et la touche Entrée dans la
  barre omnibox l'ouvrent sur Explorer dans un **nouvel onglet du navigateur**.
- La **Profondeur de l’interface** (Paramètres → Général) change ce que la barre latérale
  *épingle*, jamais ce que vous pouvez atteindre. En **Essentiel**, seuls Accueil et Fil
  sont épinglés et les autres onglets se trouvent derrière une ligne libellée **Afficher
  plus** ; **Standard** et **Complet** listent tous les onglets. La palette de commandes
  (Ctrl/⌘-K) atteint chaque onglet à toutes les profondeurs.

**Le contenu d'abord.** La barre latérale montre les *données* ; les écrans d'acquisition
et de maintenance se trouvent dans les **Paramètres** : **Collecter** (le planificateur +
la collecte manuelle), **Sources** (le catalogue), **Wikipédia** (suivi des modifications +
archives hors ligne), **Preuves & possession** et le **bureau d'intégrité des sources
(source-integrity desk)** sont tous accessibles depuis les Paramètres (documentés dans
leurs propres sous-sections ci-dessous). Les Paramètres s'ouvrent depuis le **bouton en bas
de la barre latérale** ; la palette de commandes y mène aussi directement.

Quelques noms ont changé pour être plus simples (les commandes sont les mêmes) :
**Ingestion → Collecter**, **Base de données → Bibliothèque**, **Droit mondial →
Gouvernements** (désormais avec les sous-onglets **Pays · Carte · Droit**), **Marchés →
Matières premières** (avec **Indices** devenu un onglet à part). Allez à n'importe quel
outil avec la palette de commandes (Ctrl/⌘-K).

### 3.0 Accueil

**À quoi il sert :** votre **briefing** — un fil de tri plus une orientation.

- **Briefing (le fil) :** l'application collecte et mesure en arrière-plan, puis fait
  ressortir des sujets candidats sous forme de **Pistes** (le nom affiché à l'écran pour
  les cartes du briefing), regroupées en catégories éditoriales (*en hausse, sur-raconté,
  sous-raconté, enquêter, vérifier le cadrage, surveillance, contexte, intégrité des
  données*). Chaque Piste est **un signal mesuré + des liens vers les éléments de preuve +
  une mise en garde** — jamais un verdict, et il n'y a **aucun « score de confiance »**
  (interdit dans le code).
- **Cartes à retourner — la mise en garde est au dos.** Une Piste est une **carte à deux
  faces que l'on retourne** : le **recto** présente la piste d'un coup d'œil ; **cliquez
  dessus (ou appuyez sur Entrée)** et elle se retourne sur un **verso** qui porte **la mise
  en garde, la méthode, la raison de son déclenchement, les éléments de preuve et un bouton
  « Ouvrir le corpus ↗ »** (qui ouvre l'ensemble exact d'articles de cette Piste dans une
  nouvelle fenêtre d'analyse). La mise en garde est présente dans le DOM par défaut, juste à
  côté de l'action — elle n'est jamais cachée derrière une option d'interface épurée.
  **+ Ajouter au brouillon** épingle une Piste ; **Écarter** la masque (réversible). Le fil
  est mis en cache (instantané) et **se met à jour de lui-même** — il se recalcule en
  arrière-plan après chaque passe de collecte et s'interroge à nouveau de lui-même ; il n'y
  a pas de bouton Actualiser.
- **Brouillon d’infolettre :** les Pistes épinglées + vos notes, exportées en **Markdown**
  où chaque affirmation porte déjà ses liens vers les sources, sa méthode et sa mise en
  garde — un journalisme reproductible. Pour une copie signée des articles sous-jacents,
  utilisez Preuves & possession.
- **Disposition « contenu d'abord » :** un bandeau compact **d'un coup d'œil** est épinglé
  en haut (décomptes en direct + indication si la collecte automatique tourne), et les
  Pistes en dessous peuvent être filtrées par **famille** grâce à des sous-onglets
  verticaux (une vue par défaut **« Toutes les pistes »**, plus un onglet par catégorie,
  chacun avec sa propre teinte). Le catalogue sélectionné s'amorce automatiquement et la
  collecte démarre quand vous passez en ligne ; un Accueil vide affiche donc simplement un
  état vide honnête — pas de carte de bienvenue. *(L'ancien message d'accueil en bannière et
  la ligne « Actions rapides » ont été retirés — l'Accueil s'ouvre directement sur le
  Briefing.)*

### 3.0a Activité et le Gestionnaire de tâches

**À quoi il sert :** voir — et piloter — tout ce que l'application fait en arrière-plan,
depuis n'importe quel onglet.

- Une **pastille d'activité** dans la barre supérieure s'allume pendant qu'un travail est
  en cours (une passe de collecte, une archive Wikipedia, une importation de marché) ; un
  bouton permanent de **gestionnaire de tâches** se trouve à côté (il reste accessible même
  quand l'application est inactive).
- Ouvrez le **Gestionnaire de tâches** — une vraie fenêtre (pas une bulle) avec cinq
  sous-onglets :
  - **En cours** — chaque tâche en cours d'exécution : la passe de collecte, chaque archive
    Wikipedia en cours de téléchargement, la récupération en cours (affichée par son
    DOMAINE uniquement), la boucle d'inactivité, et tout téléchargement suspendu ou en
    échec. Chaque tâche affiche sa progression réelle et les commandes qui s'y appliquent —
    **Arrêter** une passe de collecte (ce qui engage aussi le coupe-circuit réseau, donc
    vous passez hors ligne ; le bouton le dit) et **Suspendre/Annuler** une archive. Aucune
    durée restante ni aucun débit fabriqués — seulement la progression réelle en octets
    que rapporte le responsable de la tâche.
  - **File d'attente** — les tâches qui attendent leur tour : la file des archives
    Wikipedia (un seul téléchargement à la fois), dans l'ordre, avec des commandes **↑ / ↓**
    pour la réordonner (faire passer une petite archive française avant une énorme archive
    anglaise).
  - **Planification** — les faits réels du planificateur : état (en cours / inactif /
    arrêté), progression de la passe en cours (domaine uniquement), cadence, dernière
    exécution, et l'heure de la prochaine exécution donnée par le serveur lui-même,
    affichée honnêtement en temps relatif (la méthode figure dans la bulle de survol —
    jamais un compte à rebours fabriqué).
  - **Couverture** — la portée et la fraîcheur de la collecte par étiquette (quelle part de
    chaque sujet ou étiquette votre collecte atteint réellement, et à quel point c'est
    récent), pour que vous puissiez voir les lacunes.
  - **Système** — les signes vitaux du processus en direct (CPU, RAM, débit de
    téléchargement). *(Les signes vitaux ont été déplacés ici depuis la barre
    supérieure.)*
- La fenêtre lit **en direct les systèmes qui effectuent le travail**, elle ne peut donc
  jamais être en désaccord avec ce qui se passe réellement — pas d'état fantôme.

### 3.0b Fil

**À quoi il sert :** lire votre corpus comme un **flux** plutôt que comme un ensemble de
signaux mesurés. L'Accueil vous dit ce qui s'est démarqué ; le Fil vous donne simplement
des articles, l'un après l'autre, et vous laisse faire défiler.

- **Deux ordres, tous deux annoncés.** **Plus récents d'abord** suit la date de
  publication, la plus récente en haut. **Aléatoire** est un ordre fixe choisi par une
  **graine** : la position d'un article dépend de son identifiant et de cette graine, **et
  de rien d'autre**. Chaque page porte sa propre ligne de méthode indiquant lequel des deux
  vous lisez.
- **Le mélange aide à parcourir, ce n'est pas un système de recommandation.** Il n'y a
  **aucune mesure d'engagement d'aucune sorte** — rien ne mesure ce que vous avez ouvert,
  combien de temps vous êtes resté ni ce que vous avez sauté, et **aucun historique de
  lecture n'est conservé ni consulté**. Deux personnes ayant la même graine et le même
  corpus voient le même ordre. Cette phrase fait partie du texte de méthode que la page
  affiche, elle ne peut donc pas cesser discrètement d'être vraie.
- **Ce qui est laissé de côté, compté.** Le Fil montre les articles qui **ne sont pas en
  quarantaine** et dont **la source a été qualifiée**. Les deux exclusions sont **comptées
  exactement** et affichées sur la première page, de sorte qu'un fil court sur un corpus
  plein se lit comme *« vos sources n'ont pas encore été qualifiées »* — ce sur quoi vous
  pouvez agir — plutôt que comme *« vous n'avez rien »*, ce qui serait faux. Ces deux
  décomptes décrivent le corpus et non la page ; ils sont donc calculés une seule fois et ne
  changent pas pendant le défilement.
- **Là où vous vous êtes arrêté.** Le défilement garde sa place d'une session à l'autre en
  stockant **un seul marqueur de position** dans votre navigateur — une graine et un seul
  curseur, jamais une liste de ce que vous avez lu. **Paramètres → Général → Historique de
  défilement du fil** propose les deux commandes : **Remélanger** (une nouvelle graine, un
  nouvel ordre, retour au début) et **Repartir du début** (même ordre, position effacée).
- **La lacune honnête de chaque ordre.** La collecte continue pendant que vous faites
  défiler, et chaque ordre manque les articles nouvellement arrivés d'une façon
  différente : en **Aléatoire**, ils peuvent tomber *en dessous* du point que vous avez
  atteint (remélanger permet de les atteindre), et en **Plus récents d'abord**, ils
  arrivent *au-dessus* (revenir en haut permet de les atteindre). La page indique le cas qui
  s'applique.
- **Chaque carte** affiche le titre, la source, la date et les **trois principaux
  mots-clés propres à l'article** — les mots-clés de cet article, pas ceux de ce que vous
  avez recherché. **Lire la suite** déplie le résumé **sur place** ; le titre ouvre
  l'article dans le lecteur local.

### 3.1 Recherche

**À quoi elle sert :** trouver des articles dans votre corpus. La recherche est la moitié
supérieure de l'onglet **Explorer** de la barre latérale ; l'analyse des articles trouvés
([3.1a](#31a-analyse--la-fenêtre-des-corpus)) apparaît juste sous les résultats, sans bouton
à presser. Une recherche sans aucun mot ni filtre liste simplement tous les articles et
n'analyse rien.

- **Requête booléenne** — prend en charge `AND` / `OR` / `NOT`, les `"exact phrases"`
  (expressions exactes) et les parenthèses avec une priorité correcte, par ex.
  `(climate OR energy) AND policy NOT opinion`. Repose sur SQLite FTS5 et entièrement
  paramétrée (aucune injection possible).
- **Les mots arabes, chinois et japonais sont trouvés quelle que soit leur graphie.** Un
  mot arabe est trouvé avec ou sans voyelles et quelle que soit sa graphie de l'alif, du tā'
  marbūṭa ou de l'alif maqṣūra (أحمد trouve احمد, مدرسة trouve مدرسه), et un mot chinois ou
  japonais est trouvé à l'intérieur d'une suite de texte plus longue (东京 trouve un article
  qui dit 东京大学). Le chinois est découpé en mots par jieba sur toutes les installations ;
  le japonais par sudachipy, fourni avec l'extension facultative `[segmentation]`. Les
  articles indexés avant cette version continuent d'être trouvés comme ils l'ont toujours
  été, et sont aussi trouvés par mot une fois que **Réindexer la recherche (Re-index
  search)** (Paramètres → Avancé → Diagnostics) a été exécuté.
- **Filtres :** Source (nom exact), Langue (code comme `en`), et une commande de **plage
  temporelle** — des champs de date Du/Au, une barre de plage déplaçable et des
  préréglages rapides (1M · 6M · 1Y · 5Y · Tout) — la *même* commande que celle utilisée
  dans Marchés, Analyses et la fenêtre d'analyse. Laissée sur toute son étendue, elle
  n'exclut rien ; resserrez-la pour limiter la recherche à une période. Tous sont
  facultatifs.
- **Recherche** exécute la requête ; le tableau des résultats affiche **Titre · Source ·
  Publié · Langue**, ainsi qu'un décompte (`N result(s)`, et combien sont affichés si la
  liste est tronquée).
- **Actions par ligne :** **ouvrir** (une copie propre et hors ligne de l'article
  enregistré), **source ↗** (l'URL d'origine), **Résumer** et **Traduire** (LLM local, si
  Ollama est disponible).
- **Exports :** **Exporter en CSV**, **Exporter en JSON** et **Exporter des preuves
  signées** — un lot signé, qui rend toute altération détectable, contenant exactement les
  articles correspondant à votre requête (voir
  [Preuves & possession](#38-preuves-et-chaîne-de-possession)). Il ouvre d'abord un récapitulatif : combien
  d'articles et de sources, ce que contient le fichier, le fait qu'il est en clair, et quelle
  clé signe ; l'enregistrement demande un clic de plus, et le message qui suit liste les
  éléments du fichier et la clé à donner au destinataire. Il y a aussi une **Annexe
  méthodologique** (un relevé reproductible de la requête + de la méthode).
- **Exécutions du modèle local sur l'ensemble des résultats :** **Tout résumer** / **Tout
  traduire** mettent en file d'attente une exécution en arrière-plan de votre modèle local
  sur chaque article trouvé (enregistrée avec le modèle + la date, et — s'agissant d'une
  production d'IA — jamais injectée dans l'index de mots-clés de confiance) ; **Lancer
  l'extracteur** exécute l'un de vos extracteurs d'IA personnalisés sur l'ensemble ;
  **Synthétiser les résultats** ouvre une fenêtre où vous choisissez jusqu'à 20 éléments et
  obtenez un unique passage du modèle local, avec citations, sur ceux-ci (voir l'analyse
  détaillée). Les exécutions sont mises en file d'attente et annulables ; les mêmes
  commandes se trouvent dans la fenêtre d'analyse.

> **Deux façons d'y accéder.** Ouvrez **Explorer** depuis la barre latérale, ou tapez dans
> la barre omnibox et choisissez *« Lancer la recherche booléenne complète »* : les deux
> mènent à la même page, avec la requête préremplie.

**La barre omnibox (Ctrl/⌘-K), depuis n'importe où :** la palette de commandes est aussi
une recherche fédérée dans vos données. Dès deux caractères saisis, elle affiche les trois
premiers résultats par groupe — **articles** (FTS booléen complet), **mots-clés** (chacun
ouvre sa fenêtre de corpus), **sources**, **pages Wikipedia suivies**, **textes Wikipedia
conservés sur cette machine** (les anciennes versions et les textes des pages modifiées que
conserve la voie Wikipedia, voir 3.7) et **documents juridiques suivis** — avec le *total
réel* de chaque groupe indiqué dans son en-tête.
Tout s'appuie sur des index et la recherche se fait uniquement sur cette machine ; une
requête à moitié saisie n'est jamais une erreur. Choisir *« Lancer la recherche booléenne
complète »* vous amène dans cet onglet avec la requête préremplie, de sorte que chacune des
possibilités ci-dessus reste à une étape.

### 3.1a Analyse — la fenêtre des corpus

**À quoi elle sert :** transformer un *ensemble* d'articles, ou un seul mot-clé, en un
objet d'analyse que vous pouvez lire sous tous les angles. Un mot-clé est un corpus ; un
article seul est un corpus d'un élément. L'analyse se trouve sur la page **Explorer**, sous
les résultats de la recherche. Elle apparaît quand vous :

- lancez une recherche dans Explorer (ou choisissez *« Lancer la recherche booléenne
  complète »* dans la barre omnibox),
- appuyez sur **Entrée** dans la barre omnibox (cela ouvre Explorer dans un nouvel onglet
  du navigateur),
- cliquez sur un **mot-clé** n'importe où (Analyses, le verso d'une Piste ou le lecteur, où il
  s'ouvre dans un nouvel onglet du navigateur),
- cliquez sur une **Piste de l'Accueil** (son « Ouvrir le corpus ↗ » ouvre l'ensemble
  *exact* d'articles, dans un nouvel onglet du navigateur), ou
- cliquez sur le titre du graphique d'une matière première / **Analyser ↗**.

Quand une analyse est ouverte depuis un autre endroit (un mot-clé, une Piste, une matière
première), la liste de recherche est mise de côté et la page indique de quoi elle affiche
l'analyse, afin que la liste et l'analyse ne décrivent jamais discrètement deux ensembles
d'articles différents. Plusieurs analyses coexistent sous forme d'**onglets nommés** dans
un bandeau en haut ; chacun porte le titre de sa requête et indique le **nombre
d'articles** sur lequel il a été calculé. Les sous-onglets sont :

- **Vue d'ensemble** — un résumé de l'ensemble, d'un seul coup d'œil.
- **Mots-clés** — le tableau classé des mots-clés (cooccurrence réelle / n / PMI, aucun
  score).
- **Tendance** — l'évolution des mentions / du volume dans le temps, tracée avec la boîte à
  outils de graphiques interactifs commune (zoom à la molette, déplacement par glisser,
  survol pour une lecture exacte ; pleine résolution dans la fenêtre, les portions
  clairsemées étant montrées honnêtement sous forme de barres + une mise en garde sur le
  corpus encore jeune plutôt que par une courbe fabriquée).
- **Carte mentale** — une carte radiale déterministe des mots-clés (centre → branches,
  toujours vers l'extérieur).
- **Articles** — les articles membres (paginés). Colonnes : **Titre · Source · Publié ·
  Mot-clé principal**, et chaque en-tête de colonne est la **commande de tri** — cliquez
  sur l'un d'eux pour trier selon cette colonne, cliquez à nouveau pour inverser ; la flèche
  marque la colonne active. Les noms s'ouvrent de A à Z, les dates et les décomptes en
  commençant par les plus grands. Le même choix figure dans les listes **Trier par /
  Ordre** au-dessus de la liste, car ce sont les deux mêmes champs : il n'existe qu'un seul
  tri dans cette fenêtre, donc rien ne peut discrètement passer outre votre choix. *(Le tri
  se trouvait autrefois dans **Avancé**, à trois sous-onglets de la seule liste qui
  l'utilise.)*

  **Mot-clé principal** est le mot-clé le plus mentionné PROPRE à cet article, avec son
  décompte, calculé au moment de l'indexation de l'article — une question différente du
  décompte du mot-clé *recherché*, qui est le bouton distinct `↕ "term" count`. Lorsque
  plusieurs mots-clés sont à égalité pour ce décompte, la ligne indique **à égalité**, car
  celui qui est nommé est simplement le premier d'entre eux, et l'appeler le mot-clé
  principal affirmerait un classement que le décompte n'a jamais établi. Un article que la
  réindexation n'a pas encore atteint affiche **—**, jamais 0 : il lui manque une mesure,
  pas des mots-clés.

  Chaque ligne s'ouvre dans le **lecteur hors ligne**, dont la propre barre d'onglets est
  **Lire · Résumé · Traduction · Mots-clés · Carte mentale · Sentiment · Liés · Source ·
  Liens** — c'est là que vous le lisez, que vous voyez sa **source d'origine** (le texte
  visible du lien est l'URL complète) et que vous lancez **Résumé / Traduction** avec le
  modèle local. Ces trois éléments étaient autrefois répétés sous forme d'une flèche et de
  deux boutons sur chaque ligne ; ils ont été déplacés vers la seule page capable
  d'afficher réellement le résultat. Les commandes en masse **Tout résumer / Tout
  traduire** sont inchangées dans la ligne d'actions ci-dessous. Les copies quasi
  identiques portent le badge « N copies = une seule voix ».
- **Quand/Où/Qui** — les dates, lieux et personnes/organisations que mentionne l'ensemble,
  sous forme de **facettes** cliquables ; cliquer sur une valeur **affine** l'analyse aux
  seuls articles qui la mentionnent (une fenêtre d'analyse affinée). Déduit du texte,
  jamais confirmé.
- **Liens** — quels articles membres **partagent des liens sortants**. Cela fait
  délibérément ressortir une *structure d'origine commune* : trois articles qui citent une
  même origine sont une seule source sous trois casquettes ; la convergence ne compte donc
  comme corroboration que lorsque les chemins sont indépendants. Le but est de remonter aux
  *sources des sources*.
- **Liés** — les copies quasi identiques d'une source à l'autre (« N copies = une seule
  voix ») et les origines communes, chacune avec un bouton **« Dériver vers un nouveau
  corpus → »** qui crée une nouvelle fenêtre d'analyse portant exactement sur ces articles.
- **Sentiment** — la tonalité par source (VADER ; la mise en garde « anglais uniquement »
  est affichée).
- **Sources** — la provenance descriptive des médias présents dans l'ensemble.
- **Concurrentiel** — comment se comparent les médias de l'ensemble (volume / tonalité /
  moment de publication / angle mis en avant — descriptif, jamais un gagnant ni un score).
- **Prix** — *(uniquement quand la fenêtre a été ouverte à partir d'une matière première)*
  la courbe des prix superposée à la couverture de votre corpus sur un axe temporel commun
  (cooccurrence, jamais causalité), chaque série sur sa propre échelle en unités réelles.
- **Avancé** — restreignez l'ensemble par **source · langue · plage de dates** ; une
  pastille « Filtré » et un résumé indiquent ce qui est actif. (Le tri a été déplacé dans
  l'onglet Articles, ci-dessus.)

La ligne d'actions comporte **Annexe méthodologique**, **Exporter des preuves signées**,
**Synthétiser les résultats** (la fenêtre de sélection des éléments), et les exécutions
du modèle local mises en file d'attente **Tout résumer / Tout traduire / Lancer
l'extracteur** — le même ensemble que pour la recherche au-dessus.

### 3.2 Collecter *(dans Paramètres → Avancé → Collecte)*

> **Où cela se trouve désormais.** La collecte est une surface d'acquisition : elle a donc quitté
> la barre latérale pour **Paramètres → Avancé → Collecte** (le contenu d'abord). Les commandes sont inchangées.

**À quoi ça sert :** faire entrer des articles dans le corpus, automatiquement ou manuellement.

**A. Ingestion automatique (le planificateur).** Une tâche de fond qui ingère à
intervalles réguliers. Commandes :

- **Démarrer / Arrêter / Collecter maintenant** : tourner en continu, s'arrêter, ou lancer une seule passe
  immédiatement. La pastille d'état affiche `running` / `running — scrape in progress` /
  `stopped` et l'heure de la prochaine exécution ; la ligne en dessous donne le bilan de la dernière exécution.
- **Intervalle (minutes)** et un curseur **Vitesse de collecte** (un débit de téléchargement visé). L'application
  mesure son propre débit de téléchargement réel et augmente ou réduit le nombre d'hôtes interrogés
  simultanément pour suivre votre objectif, en ralentissant automatiquement lorsque le processeur, la mémoire ou
  l'unique processus d'écriture chiffrée devient le facteur limitant ; la politesse envers chaque hôte n'est jamais sacrifiée à la vitesse.
  *(Il n'y a pas de plafond « nombre maximal de sources par exécution » : avec le temps, chaque source est couverte, si bien qu'aucune n'est
  laissée de côté.)*
- **Mode :** *Flux RSS*, *Exploration récursive*, *Marchés (règles de prix)* ou *Wikipédia
  (pages suivies)*. Choisir **l'exploration** fait apparaître **Profondeur d'exploration** et **Pages max /
  source** (l'explorateur reste à l'intérieur du domaine propre à chaque source, respecte robots.txt
  en mode fermé par défaut (fail-closed), est limité en débit et strictement borné : il *découvre* des articles, il
  ne fait pas de copie miroir des sites).
- **Ciblage :** **Langues**, **Types de source** et **Étiquettes / mots-clés (au moins un)**
  restreignent les sources concernées par une exécution. **Aperçu des cibles** indique exactement combien de
  sources correspondent (avec une répartition par langue et par type) *avant* que vous ne lanciez l'exécution.
- **Démarrer automatiquement au lancement** + **Enregistrer la planification** conservent la configuration.

**B. Ingestion manuelle.**

- **Ingérer le flux RSS d'une source** : choisissez une source, cliquez sur **Récupérer le flux**.
- **…ou ingérer l'URL d'un seul article** : collez une URL, cliquez sur **Ingérer l'URL**.

Dans les deux cas, la ligne de résultat affiche un bilan : articles enregistrés, doublons ignorés, bloqués par
robots.txt, etc. La récupération est toujours éthique (robots.txt en mode fermé par défaut, débit limité).

### 3.3 Sources *(dans Paramètres → Avancé → Sources)*

> **Où cela se trouve désormais.** Comme Collecter, le catalogue des sources a été déplacé dans **Paramètres →
> Avancé → Sources** (le contenu d'abord). Les commandes sont inchangées.

**À quoi ça sert :** enregistrer et organiser les médias auprès desquels vous collectez.

- **Ajouter une source :** Nom, Domaine, URL du flux RSS, Étiquettes → **Ajouter une source**. Ou **Initialiser des
  sources de départ** pour enregistrer la sélection d'intérêt public préparée à l'avance.
- **Gérer les sources (tableau) :** filtrez par texte recherché, pays, langue, type, étiquette
  et état d'activation. Les colonnes sont **triables** (Nom, Domaine, Type, Pays, Langue,
  Priorité (Priority), Articles). Directement dans le tableau, vous pouvez modifier la **Priorité** (1–3), basculer **Activées**
  et **Supprimer** (avec confirmation). Pagination, avec un compteur `N source(s)`.
- **Importer / Exporter (CSV) :** **Tout exporter (CSV)**, **Télécharger le modèle** et
  **Importer un CSV**. Colonnes : `name`, `domain` (obligatoires), plus `rss_url`,
  `source_type`, `country` (2 lettres), `language`, `region`, `tags`
  (séparées par des virgules), `priority` (1–3), `rate_limit_ms`, `enabled`,
  `reliability_score` (1–10). L'import **met à jour ou crée selon le domaine** (les nouvelles lignes sont créées,
  les existantes mises à jour) et **les lignes invalides sont signalées, jamais écartées en silence**.

#### Qualification des sources : le contrôle d'admission

**Activer une source ne suffit pas à lui seul** : une source n'est jamais *collectée* tant
qu'elle n'a pas été **qualifiée**. Chaque source porte l'un de trois tampons catégoriels, jamais
une note de qualité :

- **non jugé** (unqualified) : pas encore évaluée (valeur par défaut pour une source découverte, citée ou ajoutée
  à la main) ;
- **qualifié** : a réussi un petit essai de récupération qui a vérifié la *validité de l'extraction* (vrai
  texte rédigé plutôt qu'une collecte cassée ou inutilisable, par exemple une page de menu de navigation ou un mur de paiement) ; elle
  rejoint désormais la collecte régulière ;
- **disqualifié** : les pages extraites pendant l'essai semblaient structurellement cassées, pas
  simplement « ennuyeuses » ou laconiques (le style n'est jamais jugé, seulement le fait qu'un vrai texte d'article
  soit revenu ou non).

**Le catalogue préparé à l'avance livré avec l'application est qualifié dès le départ** (décision du mainteneur
du 2026-09-10). Ses lignes (les catalogues d'actualités, de spectre, de marchés et de droit vérifiés à la main)
portent un tampon dont la *base* est le catalogue lui-même, affiché dans le panneau de provenance de la source
sous la forme **qualifié · par catalogue**, et elles rejoignent la collecte dès le premier jour au lieu d'attendre
leur tour derrière la file des sources découvertes. Ce tampon n'est pas une mesure et ne se présente jamais comme
telle : il est revérifié selon la **même horloge de trois mois que toute source qualifiée** (voir plus bas),
une revérification échouée disqualifie la source exactement comme n'importe quelle autre, un verdict que cette instance
a déjà établi n'est jamais écrasé par lui, et l'export de qualification compte ces
lignes à part et ne les livre jamais comme des verdicts mérités. Les sources découvertes, citées et ajoutées à la main
passent toujours l'essai.

Une **tâche de fond effectue automatiquement quelques-uns de ces essais à chaque passe de collecte
en ligne** (une récupération « de quelques articles » bornée, consentie et passant par le réseau, refusée
en mode avion, exactement comme toute autre action réseau). Sur une nouvelle installation comptant
de nombreuses sources fraîchement initialisées ou découvertes, ce goutte-à-goutte peut laisser un vrai arriéré : **Paramètres
→ Sources → « Qualification des sources »** affiche le panneau et un bouton **« Qualifier la file d'attente »**
qui lance le *même* jugement en masse, sous forme de tâche annulable du gestionnaire de tâches, pour
rattraper le retard plus vite.

**La file de qualification** (Avancé → Contrôles de qualité) montre ce que les prochaines passes vont
juger, dans l'ordre : **les nouvelles sources d'abord** (jamais jugées, ou essayées sans encore assez d'articles),
puis les sources dont la revérification arrive à échéance. Une nouvelle source est toujours plus urgente qu'une
revérification (décision R94). Le panneau indique aussi combien de sources qualifiées attendent et quand
la prochaine rejoint la file.

**Le nombre de sources qu'une passe juge** augmente avec la machine (décision R95) : le nombre réglé dans
Paramètres → Avancé → Contrôles de qualité (*Sources à juger à chaque passe de collecte*) et les
*revérifications de qualification par passe* (qualification re-checks per pass) du planificateur (réglées via la configuration du planificateur, `PUT /api/scheduler/config` ;
il n'existe pas de commande dans les Paramètres pour cela) sont un minimum, et tant que *budget de qualification automatique* (qualification budget auto) est activé (par défaut), chaque passe juge autant de
nouvelles sources et de revérifications que la mémoire et les cœurs de la machine le permettent, sans plafond fixe. Un
réglage inférieur aux valeurs par défaut, ou 0, est conservé tel quel ; désactiver le mode automatique fige les nombres
exactement. Chaque candidate est jugée sur ses articles les plus récents, autant que la mémoire disponible peut
en contenir (au moins 2 000), et la passe indique à combien de candidates cette limite s'est appliquée.

**Sur une petite machine** (moins de mémoire que le plancher d'analyse de l'application), une passe juge les candidates
sur un **échantillon des 20 000 articles les plus récents** au lieu du corpus entier, et le
verdict enregistre qu'il a été établi sur échantillon (décision R93). Auparavant, ces machines sautaient chaque
passe en silence et aucune source n'était jamais qualifiée. Si même l'échantillon ne tient pas en mémoire, la passe
le dit et ne démarre pas.

Une **source disqualifiée a droit à une seconde chance** : elle n'est jamais supprimée, et l'horloge
(jamais une réimportation ni une nouvelle citation) est la seule chose qui déclenche une revérification :
1 mois après la première disqualification, puis un délai qui double jusqu'à un plafond de 6 mois (1 → 2 → 4 →
6), remis à zéro dès qu'une revérification réussit. **C'est pourquoi une source nouvellement ajoutée ou
récemment disqualifiée peut rester activée mais non collectée pendant jusqu'à six
mois** sans rien collecter : vérifiez la pastille de qualification de sa ligne (voir plus bas) si une
source que vous avez ajoutée ne semble jamais fournir d'articles.

**Où est passé le compte de qualification :** la tuile de la Bibliothèque qui affichait autrefois un seul
chiffre « Sources » présente désormais **trois chiffres honnêtes, sans chevauchement** : *Sources
(en collecte)* (Sources (collecting) : activées **et** qualifiées), *Sources en attente de qualification (activées)* (Sources awaiting qualification (enabled))
et *Candidates découvertes* (encore désactivées, voir plus bas), parce que les fondre en
un seul nombre faisait passer un arriéré de découverte, accumulé automatiquement et comptant des dizaines de milliers de candidates,
pour des sources auprès desquelles l'application collectait déjà.

#### Revérification : un tampon ne dure pas éternellement

Un verdict est une mesure, et une mesure vieillit. **Un tampon « qualifié » est revérifié
environ tous les trois mois** (décision R94, 2026-09-29) (le réglage `qualification_recheck_per_pass` du planificateur, accessible uniquement par l'API ; 0
désactive la revérification). La revérification suit un intervalle fixe, et non le doublement de
l'échelle des sources disqualifiées : le doublement traduit un espoir qui s'amenuise après des échecs répétés et ne signifie
rien après une réussite.

**Ce qu'une revérification peut voir et ne peut pas voir, dit simplement :** elle juge une source sur tout son
historique enregistré ; elle repère donc une source *globalement* cassée, mais elle ne **remarquera pas**
une source qui s'est dégradée récemment si des années de bons articles l'emportent sur les plus récents.
Son véritable intérêt est ailleurs, et mérite d'être connu : une source admise très tôt,
sur un ou deux articles seulement, a été jugée alors qu'il n'existait pas encore assez de corpus pour
la comparer ; la revérification est la première fois qu'elle est mesurée par rapport à une véritable
référence.

Les revérifications ont leur **propre** budget, distinct de celui qui admet les nouvelles candidates.
Ce n'est pas un détail : tant qu'elles partageaient un budget, une installation avec un gros arriéré de
sources non examinées consacrait chaque créneau aux nouvelles candidates, et aucune revérification (y compris
la seconde chance des sources disqualifiées décrite plus haut) n'était jamais réellement effectuée.

#### Les verdicts voyagent : sauvegardes et nouvelle installation

Le travail de qualification fait sur une instance **n'est pas perdu lorsque vous déplacez ou fusionnez des corpus**.

- **Importer une sauvegarde** apporte ses verdicts. Une source jugée par le corpus entrant
  arrive jugée. Une source que *cette* instance n'a jamais jugée **adopte** le verdict
  entrant, dans les deux sens : une source qu'une autre instance a trouvée cassée ne
  revient donc pas discrètement dans la file d'essai ici. Un verdict établi par *cette* instance l'emporte toujours :
  un corpus importé ne peut jamais renverser le jugement de votre propre machine, dans un sens comme dans
  l'autre.
  Le tampon de départ du catalogue n'est pas un tel verdict : un verdict importé *mesuré* le
  remplace. Lorsqu'une source qui ne porte encore que le tampon du catalogue reçoit un jugement importé
  plus récent de *disqualifié*, le démarrage suivant la retire de la collecte et l'indique dans les
  diagnostics ; lorsque le verdict de votre propre machine contredit l'import, le vôtre est conservé et la
  source est revérifiée plus tôt par votre propre passe de qualification.
- **Une nouvelle installation part de ce que les instances précédentes ont mesuré.** L'application est livrée avec
  `configs/source_qualification.yml`, une liste de verdicts générée, et les adopte au
  premier démarrage pour les sources qu'elle n'a jamais jugées. Une source **absente** de ce fichier est simplement
  livrée non jugée et sera évaluée par la première passe de qualification de l'installation, exactement
  comme avant l'existence de ce fichier ; le catalogue livré se compose donc en pratique de deux listes : les
  sources déjà qualifiées par l'application, et celles qui restent à qualifier.

Un verdict adopté est enregistré comme **hérité**, et non comme une mesure faite par cette machine,
et il garde la date à laquelle il a été établi à l'origine : rien ne laisse donc croire que votre
installation l'a mesuré. Ce qui repart de zéro, c'est l'horloge de revérification propre à votre machine : elle court à partir
du jour où vous avez adopté le verdict, et non du jour où quelqu'un d'autre l'a obtenu. Un premier téléchargement est
donc silencieux, et c'est voulu : un catalogue livré est toujours plus ancien que l'intervalle de trois mois
au moment où il vous parvient, si bien que compter à partir de la date d'origine obligerait chaque
nouvelle installation à requalifier tout le catalogue dès le premier jour, soit exactement le travail que le
fichier livré a pour but d'éviter.

Ce compromis est délibéré et a un coût qu'il faut énoncer : la fraîcheur du catalogue
livré n'est plus quelque chose que chaque installation rétablit par elle-même. Elle est
rétablie lorsqu'une nouvelle version est livrée avec une surcouche recalculée à partir d'instances qui *ont* effectué
la revérification. L'export ci-dessous indique l'âge de ses verdicts, afin que leur ancienneté
soit visible plutôt que passée sous silence.

#### Partager en retour les verdicts de votre instance

`GET /api/diagnostics/source-qualification-export` indique ce que votre instance sait de
ses sources livrées (combien sont qualifiées, combien disqualifiées, combien encore
en attente) et `?fmt=yaml` renvoie cette même liste sous la forme du fichier de surcouche lui-même.
`scripts/merge_source_qualification.py` combine les exports de plusieurs instances en un seul.

Si vous avez déjà récupéré des **paquets de tous les diagnostics** (all-diagnostics bundles) de ces instances, vous n'avez pas besoin
d'y retourner pour refaire l'export : le paquet contient ce même export comme élément, et
`--from-bundle` le lit directement dans le zip. Les deux voies sont interchangeables et
peuvent être librement combinées en une seule exécution :

```
python scripts/merge_source_qualification.py laptop-export.json \
    --from-bundle oo-all-diagnostics-desktop.zip \
    --from-bundle oo-all-diagnostics-server.zip
```

Le rapport affiché indique combien d'instances ont été fusionnées et par quelle voie. Un paquet dont
l'élément d'export ne s'est pas terminé est nommé, avec la raison que cette instance a enregistrée : il n'est
jamais ignoré en silence, car une surcouche que vous croyez fondée sur trois instances alors
qu'elle ne repose que sur deux est pire qu'une erreur.

Il y a deux choses que l'outil refuse délibérément de faire. Il ne **tranche jamais un désaccord** : si une
instance a qualifié un domaine qu'une autre a disqualifié, c'est signalé pour qu'un humain l'examine,
car choisir automatiquement un gagnant livrerait à toutes les installations un verdict que personne n'a vérifié.
Et il ne compte jamais un verdict **hérité** comme une confirmation : importer une même sauvegarde sur
huit machines, c'est une seule mesure vue huit fois, pas huit mesures.

#### Piste de découverte et décompte des citations qualifiées

Cliquez sur la ligne d'une source pour **déplier sa piste de découverte** : **où elle a été trouvée**
(le canal des citations, le catalogue, les références Wikipédia, …) et, pour une
source découverte par citation, le **premier article qui l'a citée** (avec un lien à la fois vers
l'article et vers la source citante). À côté, un **décompte des citations qualifiées** compte
les domaines que *cette* source cite elle-même, répartis en **qualifiés / disqualifiés /
en attente / non enregistrés** ; chaque nombre est cliquable et déplie la liste exacte.

C'est un **fait descriptif, jamais un verdict sur l'une ou l'autre source** : citer un
domaine disqualifié n'est pas une faute (un média sain renvoie couramment vers des entreprises,
des plateformes ou des pages cassées dont il se contente de *parler*), et citer de nombreux domaines
qualifiés n'est pas non plus une caution (une agence de presse est citée par tout le monde ; une
plateforme de blanchiment peut citer des sources réputées à dessein). Lisez-le comme une piste à
creuser, de la même manière que chaque autre signal mesuré dans cette application est une piste, pas une
note.

#### Langues que nous ne savons pas encore analyser : désactivées par défaut (conservées)

Le moteur de mots-clés et d'analyse ne peut **gérer** que les langues pour lesquelles une *liste de mots vides* (stoplist)
existe et dont l'écriture **sépare les mots par des espaces**. La liste de référence se trouve dans un seul
module, [`src/analytics/managed.py`](../src/analytics/managed.py) (`MANAGED_LANGUAGES`),
que lisent à la fois le filtrage des sources et le rapport du moteur dans l'application, si bien que le manuel ne peut pas
s'écarter du code. Selon ce module, l'ensemble géré est : **en, fr, de, es, it, pt, nl,
ru, ar, hu, id, sv, da, nb, no, pl, sr, sl, el, bg, hi, bn, fa, ur, uk, ro, cs, sk, ca,
sw, az, et, tr, fi, bs, hr**. Une langue **absente** de cet ensemble est quand même *découpée en mots*, mais ses
mots grammaticaux (les équivalents de « le/de/et ») s'infiltrent comme de faux mots-clés. **ja et th ne sont
pas segmentés** sauf si l'extra optionnel `[segmentation]` est installé : ces langues n'ont pas
d'espaces entre les mots, donc sans segmenteur l'extraction de mots-clés est purement et simplement cassée, quelle que soit
la liste de mots vides. **zh** était dans la même situation jusqu'à ce que jieba devienne une dépendance de base en
0.4 ; le chinois est segmenté, et donc géré, sur toutes les installations.

Collecter des contenus dans ces langues produit donc des **mots-clés parasites** qui :

- **polluent les analyses** : de faux mots-clés faussent les associations, les tendances et
  les super-groupes, et
- **gonflent le corpus** : chaque agrégation (Analyses, Groupes, la carte mentale) paie
  le prix de centaines de milliers de lignes dénuées de sens, ce qui ralentit réellement
  les gros corpus.

C'est donc voulu : **une nouvelle source dans une langue non gérée est initialisée *désactivée***. Elle est
**conservée** (jamais supprimée) et entièrement **réactivable** : vous pouvez toujours lire ces
médias, et dès qu'une liste de mots vides est ajoutée pour leur langue, vous les réactivez.
C'est un compromis honnête : nous préférons *ne pas collecter* ce que nous *déformerions*
plutôt que de présenter des analyses peu fiables. Un `enabled: true` **explicite** dans un import CSV
l'emporte toujours (vos choix sont respectés), et une source dont la langue est **inconnue**
reste activée (nous ne désactivons jamais ce que nous ne savons pas classer).

**Pour appliquer cela à un corpus existant :** Paramètres → Avancé → Sources indique combien de sources activées
sont dans des langues non gérées (et lesquelles) et propose **« Désactiver les sources dans les langues que nous ne pouvons
pas encore analyser »**, une action groupée réversible qui les désactive
(en les conservant). Réactivez n'importe laquelle d'entre elles à tout moment depuis le tableau des sources.

### 3.4 Bibliothèque

*(Appelée **Base de données** avant la 0.05.)*

**À quoi ça sert :** un regard honnête sur ce que vous détenez réellement, et sur la portée
géographique de vos sources.

- **Statistiques de la base de données (Database stats) :** des compteurs animés en direct (articles, sources, domaines uniques,
  …), ainsi que le moteur de base de données et la **taille sur disque et le chemin** de la base. Chaque
  chiffre est un vrai décompte ou une vraie taille en octets : rien n'est estimé.
- **Couverture mondiale :** combien de pays votre catalogue de sources atteint, mesuré
  par rapport à ISO 3166 : `covered/total countries`, `coverage %`, nombre de pays *non* couverts,
  et nombre de pays « peu couverts » (sous le seuil). Les pays sont stockés sous forme de codes ISO-2
  en minuscules et **affichés sous leur nom complet** (une seule couche de conversion,
  `src/catalog/countries.py`). Un bloc **Équilibre régional** compare les sources et les pays couverts de chaque
  continent aux seuils de travail définis dans
  `configs/catalog_targets.yml` (des objectifs clairement présentés comme tels, établis à partir de la
  forme réelle du catalogue), plus un **garde-fou de concentration** sur le premier pays : la mesure de
  décentrage par rapport aux États-Unis de la 0.0.9. Le tableau liste chaque pays avec sa région, son nombre de
  sources et des **pastilles de mots-clés thématiques** (issues des étiquettes des sources). **Cliquez sur un pays ou un
  mot-clé** pour ouvrir Sources filtrées exactement sur ces sources. Un rapport des lacunes
  nomme les pays qui n'ont encore aucune source. Le panneau se met à jour en direct (aucun bouton
  Actualiser n'est nécessaire) ; la même mesure est disponible hors ligne via
  `python scripts/catalog_coverage_report.py`.

### 3.5 Marchés

**À quoi ça sert :** suivre de **vrais** prix de matières premières, de devises et d'énergie et
les mettre en relation avec le volume d'actualités.

- **Tableau de bord des tendances de marché :** une carte par série de prix : symbole, variation en %, dernier
  prix (devise/unité), nombre de points et une mini-courbe. Une commande de **période**
  (champs de date Du/Au, une barre de plage déplaçable et des préréglages rapides : 1M · 6M · 1Y ·
  5Y · All) redessine chaque carte selon une fenêtre de début et de fin exacte (et non une liste fixe
  d'échelles) ; la série complète est toujours tracée en pleine résolution dans cette fenêtre, jamais
  éclaircie. Cliquez sur une carte pour obtenir un graphique complet ainsi qu'une
  **corrélation prix↔actualités** (vrai coefficient de Pearson/Spearman, valeur p et
  taille d'échantillon, jamais un chiffre deviné). Les flux officiels sélectionnés **se mettent à jour
  automatiquement en arrière-plan** lorsque vous êtes en ligne (il n'y a pas de bouton Charger/Actualiser) ;
  le tableau comporte aussi des **sous-onglets par catégorie**, une bascule d'affichage **Cartes/Familles**, une
  superposition **Comparer** (avec une bascule d'échelle Absolue/Indexé/Log) et un axe temporel commun.
- **Configurer les sources de données** (Configure data sources ; repliable, la plupart des utilisateurs n'en auront pas besoin) :
  - **Flux de prix officiels** (FRED, qui reprend les séries de la **« Pink Sheet » de la Banque mondiale**
    et de l'**EIA**) : **Importer** en un clic, plus **Graphique**.
  - **Règles d'extraction de prix** (Price-extraction rules) : ajoutez une règle (Source, Symbole, Libellé, URL de la page, **sélecteur
    CSS**, attribut/regex facultatifs, devise, unité, marché). La règle d'or :
    **un nombre n'est enregistré que là où votre sélecteur tombe réellement sur un nombre, jamais
    deviné.** Utilisez **Tester** pour récupérer la page une fois et voir la valeur exacte trouvée, ou
    la raison exacte de l'échec, avant de vous y fier.
  - **Flux personnalisé (toute URL CSV) :** pointez vers n'importe quel CSV (correspondance par défaut : colonne 1 =
    date, colonne 2 = valeur, la convention de FRED) ; les valeurs manquantes sont ignorées, jamais
    enregistrées comme zéro.

Voir [`docs/USER_MANUAL.md`](USER_MANUAL.md) pour la référence complète des règles d'extraction.

### 3.5a Indices

**À quoi ça sert :** les **indices** boursiers mondiaux (S&P 500, NASDAQ, Dow Jones,
VIX, Nikkei 225 …), tenus **séparés des Matières premières**, car un indice est un
indice, pas une matière première.

- Un tableau de séries d'indices avec les mêmes graphiques détaillés en pleine résolution que
  les Matières premières (sous-onglets par catégorie, filtre par étiquette, superposition Comparer, vue Familles, un axe
  temporel commun). Les flux officiels sélectionnés (FRED, Stooq) **se mettent à jour automatiquement en
  arrière-plan** lorsque vous êtes en ligne : il n'y a pas de bouton Importer/Actualiser.
- Chaque flux porte un **verdict honnête propre à ce flux** lorsqu'il ne peut pas être récupéré :
  *refusé* ≠ *interdit par robots.txt* ≠ *série morte* ≠ *injoignable* ≠ *hors ligne* ; ainsi,
  un flux bloqué se dégrade de façon visible au lieu d'afficher un faux chiffre. Via Tor, certains
  flux sont bloqués par l'hôte ; le verdict le dit exactement (voir §5.5).

### 3.6 Analyses

**À quoi ça sert :** des analyses de mots-clés et d'entités sur le **texte des
articles ingérés**. *(Nécessite l'extra `[analysis]` ; la véritable reconnaissance d'entités nommées est
facultative, via l'extra spaCy `[nlp]`.)*

- **État et indexation :** une pastille affiche `indexed/total articles · keywords (entities)
  · mentions · remaining`. **L'indexation est automatique** : elle suit l'ingestion, et lorsque vous
  ouvrez Analyses, un complément silencieux en arrière-plan résorbe tout arriéré restant (le compteur « remaining »
  descend tout seul jusqu'à 0). Il n'y a **pas de bouton « Indexer le corpus » (Index corpus)** : il a été
  supprimé au profit de l'indexation automatique. Les personnes, organisations et lieux sont conservés comme
  unités indivisibles ; l'indexation peut reprendre là où elle s'était arrêtée et la barre se met à jour en direct. *(Désactivez l'indexation
  automatique avec `OO_NO_INDEX=1`.)*
- Huit sous-onglets :
  - **Explorer** : saisissez un mot-clé ou une entité (par ex. *inflation*, *Emmanuel Macron*,
    *Rio Tinto*) pour obtenir : une courbe de **tendance** dans le temps ; une **carte mentale des associations**
    (termes co-occurrents classés par PMI : épaisseur des liens = co-occurrence, distance =
    force ; cliquez sur un nœud pour le recentrer) ; un tableau de **cadrage** (en quoi le
    ton de chaque média diffère, via VADER, avec les termes qu'il met en avant) ; et des extraits **en contexte**
    avec des liens vers la source, le lieu et la date.
  - **Tendances** : **En hausse** (mots-clés à la croissance la plus rapide, fenêtre récente comparée à une fenêtre de référence) et
    **Top** (les plus mentionnés), plus trois fenêtres préréglées (24h · semaine · mois) côte à
    côte, filtrables par type (termes/entités/personnes/organisations/lieux) et par pays. Cliquez sur n'importe quel
    terme pour l'Explorer ; cliquez sur ✕ pour l'exclure.
  - **Sources** : les sources en tendance dans votre corpus.
  - **Familles** : familles de mots-clés (variantes morphologiques regroupées).
  - **Groupes** : super-groupes (concepts parapluies durables) et **anneaux** multilingues
    (un concept et ses traductions/synonymes), modifiables.
  - **Carte** : la carte choroplèthe ooMap appliquée à votre corpus (le même composant que l'onglet
    Carte du monde).
  - **Convergence** : co-occurrence spatio-temporelle en lecture seule : des articles qui convergent vers le même
    **lieu** dans une fenêtre de temps autour de la date d'événement mentionnée. L'indépendance est mesurée
    par les **sources distinctes** (une seule source bavarde ne peut pas en fabriquer une) ; chaque groupe
    porte la mise en garde « co-occurrence, jamais causalité : une invitation à lire, pas une preuve ».
  - **Veilles** : vos conditions enregistrées « si ceci, alors surveiller » : une requête FTS locale + un
    seuil + une fenêtre. Lorsque le corpus gagne assez de nouveaux articles correspondants, une **piste
    de veille** apparaît sur l'Accueil. Uniquement locale, sans notifications, sans réseau, sans télémétrie ;
    créer / activer / modifier / supprimer, avec un historique des correspondances.

Chaque chiffre est un vrai agrégat, accompagné de la taille de son échantillon et d'une mise en garde. Voir
[`docs/USER_MANUAL.md`](USER_MANUAL.md). Pour régler les mots-clés qui apparaissent, utilisez le
[filtre de mots-clés dans les Paramètres](#39-paramètres).

### 3.6a Carte du monde

**À quoi ça sert :** voir *où* se situe votre corpus : une **carte choroplèthe** (« Couverture
mondiale ») qui colore chaque pays selon une dimension mesurée de vos données, avec des couches facultatives
de lieux, de signaux et d'emplacements de serveurs. Elle repose sur un composant cartographique réutilisable unique
(**ooMap**), et chaque commande se trouve **à l'intérieur de la carte** (la convention de Google Maps) :
zoom ＋/－, zoom à la molette, déplacement par glisser, ⛶ agrandir, et les sélecteurs de couche et de mesure.

- **La mesure de la choroplèthe (sélecteur dans la carte) :** choisissez ce qui colore les pays parmi
  **Sources · Articles · Mentions de mots-clés · Tonalité moyenne**. Les décomptes utilisent une échelle séquentielle ;
  **Tonalité moyenne** utilise une échelle **divergente** (positif ↔ négatif autour de zéro) et porte
  la mise en garde **VADER, anglais uniquement** ainsi que le `n` des articles évalués : un pays sans aucun
  article anglais évalué affiche « aucune donnée », jamais un neutre fabriqué.
- **Absence de données honnête ≠ zéro :** un pays sans données localisées est affiché avec des **hachures**
  marquées « aucune donnée », visuellement distinctes d'un vrai zéro. Les petits territoires que le contour
  grossier ne peut pas dessiner apparaissent sous forme de **points** ; les sources sans pays sont **comptées mais
  jamais placées** (« N non cartographiées »).
- **Granularité (bascule dans la carte) :** affichez par **Pays** ou agrégez par **Continent**
  (une somme pour les décomptes, une moyenne pondérée par `n` pour la tonalité, jamais une moyenne de moyennes ; un
  continent inconnu est honnêtement indiqué « aucune donnée »).
- **Couche des lieux :** activez **Lieux** pour placer les endroits dont vos articles *parlent*
  (d'après les Quand/Où/Qui extraits à l'ingestion, aux coordonnées d'un répertoire géographique) sous forme de
  marqueurs creux dimensionnés selon la dispersion des articles, avec la mise en garde **« Déduit du texte, jamais
  confirmé. »**
- **Couche des signaux + moment ciblé :** activez **Signaux** pour placer des événements
  spatio-temporels datables (repères choisis, articles du corpus, dates extraites) sous forme de points colorés par type ; un
  **curseur de moment ciblé** parcourt le temps (confirmé = plein, futur/non confirmé = un
  anneau en pointillés, qui s'estompe avec l'éloignement dans le temps). Cliquez sur un marqueur pour ouvrir un panneau de détails : date,
  lieu, source, lien officiel, **« Trouver la couverture dans votre corpus »**, et une liste **« Proche dans
  l'espace et le temps »** qui précise explicitement que la co-occurrence n'est *« ni un lien ni une
  cause. C'est à vous de juger. »*
- **Couche des IP des serveurs :** affichez si vous le souhaitez les **emplacements des serveurs** des
  sources, géolocalisés hors ligne, avec la mise en garde honnête qu'il s'agit d'un nœud périphérique de CDN ou d'un hôte anycast, et **non** d'une preuve
  de l'origine réelle de l'éditeur (et indisponible via Tor, où la connexion aboutit au
  proxy, pas au serveur).
- **Les côtes et les frontières sont incluses :** la géométrie des pays et des côtes est livrée avec l'application
  (Natural Earth, simplifiée) : rien à construire, aucune frontière inventée.

Les dates *dont parle* un article deviennent aussi des **étiquettes de date propres à chaque article** : ouvrez le lecteur
hors ligne d'un article pour les voir listées, **confirmer ou rejeter** chaque candidate, ou les **extraire** à la demande ;
le corpus peut ensuite être filtré par date mentionnée (`GET /api/article-dates/by-date`).
L'extracteur privilégie la précision : les années seules et les périodes vagues ne sont pas extraites, mais
**les mots relatifs ancrés** (« hier ») et **les jours de la semaine seuls** le sont.

### 3.6b Agenda

**À quoi ça sert :** un calendrier d'événements datés : ce qui arrive, avec ses sources et en toute honnêteté.

- Une **grille mensuelle** (semaine commençant le lundi ; noms des mois et des jours dans la langue de votre interface) est la
  vue par défaut, avec les vues **Semaine · Trimestre · Semestre · Année · Décennie · Liste**
  à côté (une seule barre de navigation commune). Les jours comportant des événements sont marqués ; cliquez sur un jour pour en voir les
  détails, et cliquez sur le titre d'un événement pour l'ouvrir dans le corpus.
- **Événements déduits (de vos articles) :** les dates futures *mentionnées* dans plusieurs
  articles apparaissent comme une couche **déduit** distincte et filtrable : chaque entrée affiche une
  pastille « déduit · jamais confirmé » et le nombre d'articles et de sources, et son titre ouvre
  l'ensemble exact d'articles. Des décomptes seulement, jamais un verdict.
- **Astronomie, calculée localement :** les quatre phases principales de la Lune (nouvelle lune, premier quartier, pleine lune, dernier quartier) et les équinoxes/solstices sont
  calculés sur cette machine (algorithmes de Meeus, vérifiés par rapport aux valeurs publiées
  dans les éphémérides) ; chaque entrée indique sa **méthode et sa précision** dans la bulle de survol.
  Les saisons sont nommées **honnêtement selon l'hémisphère** : jamais un « été » tout court.
- **Contexte climatique :** un jeu de données inclus sur les épisodes El Niño / La Niña (convention ONI
  du NOAA CPC) ; toute entrée encore en attente d'une vérification croisée sur l'internet en clair porte un
  indicateur « vérification en attente ».
- **Les dates mobiles sont signalées comme telles** : l'application n'invente jamais de jour exact pour un
  événement dont la date change chaque année.
- Les **Calendriers** (sources iCal de jours fériés, de fêtes religieuses, d'astronomie) s'abonnent dans
  **Paramètres → Agenda**, pas ici : l'onglet montre les données, la tuyauterie se trouve dans
  les Paramètres. Ils se tiennent ensuite à jour d'eux-mêmes : tant que la collecte est active, les nouveaux événements sont
  importés et chaque flux est revérifié à tour de rôle, quelques-uns par passe. Un flux en échec est
  revérifié au bout de 1 mois, puis 2, 4 et 6 : **avec un plafond, si bien qu'un flux n'est jamais abandonné
  définitivement**, et le bilan de chaque passe est visible dans l'onglet **Planification du gestionnaire
  de tâches**. Rien de tout cela ne s'exécute au démarrage ni hors ligne. Le **catalogue** d'environ 500 flux lui-même
  (verdicts, dossiers de fournisseurs en double, ajout de vos propres `.ics`) relève de la tuyauterie et
  se trouve dans **Paramètres → Avancé → Annuaire des calendriers**.
- **Si le fichier des événements importés est endommagé au point qu'aucune partie ne puisse être lue** (tronqué,
  JSON non valide, ou erreur de lecture du disque sous Linux ou macOS), l'Agenda le lit comme vide et le journal
  le signale. Avant que l'enregistrement suivant ne le remplace (un import, une restauration, la suppression d'un flux), l'application conserve une fois le fichier endommagé,
  sans modification, sous le nom `calendar_feed_imports.json.damaged` dans votre dossier de données, pour vous ou pour un
  outil de récupération ; un second endommagement n'écrase jamais cette première copie. Elle ne fait pas partie d'une
  sauvegarde. Vous pouvez la supprimer vous-même à tout moment. Un fichier dont seules certaines entrées sont endommagées
  est quand même lu : ces entrées sont écartées, le journal les compte et aucune copie n'est faite. Un
  fichier vide n'est pas copié non plus : il ne contient rien à récupérer.

### 3.6b Sources vivantes

L'onglet **Sources vivantes** montre ce qui a changé dans les sources qui continuent d'évoluer
après leur collecte : Wikipédia, le droit et les cartes, avec un sous-onglet pour chacun. Tout ce qu'il contient
est lu sur cette machine ; rien n'est récupéré pour l'afficher.

- **Wikipédia :** combien de pages le flux en direct suit, combien de modifications il a
  signalées au cours des 30 derniers jours et **pour combien d'entre elles il a enregistré le texte** (« 2 sur 4 » :
  dans la limite d'un budget, il en enregistre certaines et compte les autres), le point jusqu'auquel chaque
  flux a été lu sans interruption, et les éventuelles lacunes qu'il sait avoir manquées. En dessous, chaque
  modification, de la plus récente à la plus ancienne ; **Afficher le diff** ouvre le diff enregistré à l'arrivée de la modification.
  Une modification qui a seulement été comptée l'indique et n'a pas de diff. Les pages que vous suivez à la
  main (Paramètres → Wikipédia) sont aussi listées : choisissez-en une pour lire ses révisions
  suivies. Chaque version, à l'une ou l'autre extrémité de la comparaison, a son propre bouton **Ajouter au
  corpus** : il ajoute cette version exacte comme article à part entière, daté du moment où le wiki l'a
  produite, et signale si votre corpus contient déjà cette version ou les mêmes mots. Une version
  dont le texte n'a pas été enregistré ne peut pas être ajoutée, et son bouton en donne la raison. C'est ainsi qu'une
  révision enregistrée par **Suivre maintenant** rejoint votre corpus, puisque la recherche ne les lit pas
  encore. Lorsque le **parcours des pages** est activé (voir plus bas), un groupe *Parcours des pages* indique ce qu'il
  fait (parcours en cours ; en pause, et pourquoi ; ou attente après un refus du wiki) et,
  pour chaque édition, les pages qu'il a listées **par rapport au nombre d'articles annoncé par l'édition elle-même**
  (« 1 234 000 sur 2 700 000 »). Ce sont deux décomptes, jamais un pourcentage : chaque édition
  compte ses articles à sa manière, si bien que le premier nombre peut dépasser le second. Lorsque
  la récupération des **autres pages modifiées** est activée (voir plus bas), un groupe *Autres pages modifiées*
  (au-dessus de celui du parcours) compte les pages qui ont un texte, les pages modifiées qui attendent encore
  le leur, les textes récupérés et les pages qui sont depuis devenues des pages suivies par le flux,
  également par édition, et indique quand il s'arrête : à une part annoncée du budget
  de stockage, une valeur par défaut proposée que l'application affiche, et non une décision arrêtée.
- **Droit :** les documents suivis par le traqueur juridique, la vérification la plus récente et la plus ancienne, et
  chaque modification réelle (une revérification qui n'a rien changé n'est pas comptée) avec son
  diff enregistré et un lien vers votre copie locale.
- **Cartes :** vos régions cartographiques téléchargées, celles qui sont en pause ou en échec et pourquoi, et
  l'espace qu'elles occupent.

La fraîcheur est affichée sous forme de dates, jamais jugée : ce qui est assez récent dépend du
sujet. Les budgets sont affichés mais se règlent dans **Paramètres → Données & sauvegarde**.

### 3.6c Climat

**À quoi ça sert :** lire six relevés publiés sur le climat et la Terre à côté de votre corpus,
chacun exactement tel que son éditeur l'a publié. L'onglet comporte un sous-onglet par jeu de données :

- **Température** : NASA GISTEMP v4 : les *anomalies* de température mondiale mensuelles et annuelles
  (écarts par rapport à la moyenne 1951-1980, en °C, et non des températures).
- **Banquise** : NSIDC Sea Ice Index v3 : l'étendue quotidienne de la banquise arctique ou antarctique, en
  millions de km².
- **El Niño** : l'Oceanic Niño Index du NOAA : l'anomalie de température de surface de la mer sur trois mois
  dans la région Niño 3.4 du Pacifique.
- **Séismes** : le catalogue de l'USGS : les séismes de magnitude 6,0 et plus dans le monde entier,
  comptés par mois depuis janvier 1973, avec la plus forte magnitude de chaque mois.
- **Émissions et énergie** : Our World in Data : chiffres annuels d'émissions et d'énergie par
  pays et par région, chaque colonne conservant les conditions de son producteur d'origine.
- **Station météo** : NOAA GHCN-Daily : température, précipitations et neige quotidiennes pour
  **une seule** station, choisie par son identifiant de 11 caractères (par exemple `USW00094728`, New York
  Central Park). Une station décrit un lieu, pas une région ni le climat.

**Comment il récupère les données.** Rien n'est téléchargé tant que vous ne le demandez pas. Chaque sous-onglet a son propre
bouton **Récupérer auprès de l'éditeur** (il devient **Mettre à jour auprès de l'éditeur** une fois que des données
sont enregistrées ; sur **Station météo**, vous saisissez un identifiant de station et appuyez sur **Récupérer la station**, puis
**Mettre à jour cette station**), qui nomme le serveur qu'il contacte. Il passe par la même fenêtre de consentement que toutes
les autres actions réseau et il est refusé tant que le mode avion est activé. La récupération s'exécute en
arrière-plan ; le gestionnaire de tâches l'affiche. Lire ce qui est déjà enregistré ne fait aucun appel
réseau.

**Ce sur quoi vous pouvez compter.** Chaque sous-onglet nomme sa source, sa licence, sa méthode et la date à laquelle
cette machine l'a récupérée pour la dernière fois. Une nouvelle récupération n'enregistre que les valeurs nouvelles ou que
l'éditeur a révisées : les valeurs antérieures restent lisibles, et les périodes que l'éditeur ne diffuse plus
sont comptées, jamais supprimées. Une cellule vide est une lacune publiée, jamais un zéro. Rien ici n'est
une prévision, une note ou une évaluation de risque.

### 3.6d Observatoire

**À quoi ça sert :** voir tout votre corpus d'un seul coup d'œil, dessiné comme un ciel nocturne. Chaque
**galaxie** est un groupe de mots-clés apparentés ; chaque secteur du cercle correspond à l'un des douze domaines
thématiques.

- **L'angle** (Angle) ne porte que le domaine. La position d'une galaxie à l'intérieur de son secteur est un hachage
  stable : elle reste au même endroit d'une visite à l'autre et ne signifie rien en elle-même.
- **La distance au centre** porte la mesure unique que vous choisissez, avec des anneaux légendés.
  **La taille des étoiles** (Star size) est dessinée en surface (mentions) et n'est qu'un indice secondaire.
- **La couleur** indique la langue, ou l'optique **Tendance** ; elle n'est jamais le seul signal.
  Les lignes de constellation relient les galaxies qui partagent un mot-clé membre, jamais des galaxies qui
  semblent simplement proches.
- Le **tableau classé** sous le ciel liste chaque galaxie au complet, y compris celles que le
  ciel ne peut pas placer. Le tableau est la vue de référence ; le ciel est une seconde façon de le
  lire. Une ligne au-dessus compte ce que l'image laisse de côté (les galaxies pas encore observées, et
  les mots-clés en dehors de toute galaxie).
- Le même corpus dessine toujours le même ciel : un changement que vous voyez est donc un changement dans vos
  données. Il n'y a pas de note composite.

### 3.7 Wikipedia *(dans Paramètres → Wikipédia)*

> **Où cela se trouve désormais.** Le suivi des modifications de Wikipedia et les outils de dumps hors ligne ont été déplacés
> dans **Paramètres → Wikipédia** (le contenu d'abord) ; les pages suivies apparaissent toujours dans la
> recherche générale et l'analyse comme n'importe quel article. Les commandes n'ont pas changé.

**À quoi ça sert :** surveiller des pages Wikipedia précises et **signaler les modifications
suspectes** — ce sont les *modifications* qui constituent les données, pas une copie de l'article.

- Ajoutez une page à surveiller par **Édition** (code de langue, par ex. `en`, `fr`, `ar`),
  **Titre de l'article (Article title)** et une étiquette **Liste de suivi** facultative. L'application stocke **un seul
  instantané de référence**, puis uniquement les **différences/deltas** de chaque nouvelle modification — si bien que les
  changements cosmétiques ne coûtent presque rien.
- **Suivre maintenant** (éventuellement en **utilisant les scores ORES**) récupère les nouvelles révisions et signale
  celles qui sont importantes ou suspectes : forts écarts de taille, balises de révocation ou de blanchiment, modifications anonymes,
  rafales de modifications et — si l'option est activée — scores d'apprentissage automatique ORES « dommageable »/« de bonne foi ». Les candidates
  sont *présentées pour que vous en jugiez* ; rien n'est étiqueté « désinformation ».
- **Modifications signalées** liste les modifications (Quand · Édition · Page · Auteur · Δ octets ·
  Motifs · ORES), avec une visionneuse **Différences** et un lien **en direct (live)** vers Wikipedia.
  Filtrez par *signalées seulement* et par édition.

**Les pages suivies sont des articles du corpus (les choix des sources vivantes, énoncés) :**
chaque page que vous suivez rejoint aussi votre corpus en tant qu'article, sous une source
propre à chaque édition (« Wikipedia (en) »), de sorte qu'elle apparaît dans **la recherche générale, les mots-clés et
Quand×Où×Qui comme n'importe quel autre article**. Les choix que l'application fait pour vous,
de façon visible : (1) ce que voient la recherche et les analyses est toujours la **version la plus récente**
que le suivi a récupérée, et l'identifiant exact de la révision correspondante est
enregistré ; (2) le **texte intégral de chaque révision suivie est stocké sur cette
machine** — les versions passées restent exactement reconstructibles (analyses ancrées sur une version,
sans rejouer les différences), au prix honnête d'un stockage qui croît avec l'activité
d'édition ; (3) le texte analysé est du wikitexte réduit à du texte brut — jamais
présenté comme l'article affiché. Tout reste local ; l'historique des modifications
reste disponible pour chaque page, et l'onglet **Sources vivantes** l'affiche
([3.6b](#36b-sources-vivantes)).

**Le budget de stockage de la voie (150 Go par défaut, à vous de le réduire) :** la voie Wikipédia
cesse de stocker du texte au total que vous fixez dans l'assistant de premier lancement (ou dans **Paramètres →
Stockage**, à côté du calcul fait par rapport à l'espace disque libre de cette machine). Le défaut est
de **150 Go** depuis la décision du 2026-09-29, contre 20 Go auparavant ; réduisez-le à 20 Go, ou à n'importe quelle valeur
jusqu'à 1 Go, si le disque est petit. Une installation qui est déjà passée par l'assistant
conserve le chiffre qu'elle a accepté ; une installation qui n'a jamais vu l'assistant suit le nouveau défaut
jusqu'à ce que vous fixiez le vôtre.

**Le parcours des pages (désactivé tant que vous ne l'activez pas) :** le flux en direct n'entend jamais parler
que des pages que quelqu'un modifie, si bien que la majeure partie d'une encyclopédie ne lui parvient jamais. Cocher
**Parcourir aussi tous les titres d'articles** (Paramètres → Wikipédia, sous *Le flux d'édition
en direct*) liste tous les articles des éditions que vous avez choisies, 50 titres par requête, une
requête à la fois, entre les lectures propres au flux, pendant plusieurs jours. Il conserve pour chaque
page son titre, sa taille, sa révision la plus récente et son identifiant Wikidata, jamais son texte, à l'intérieur du même
budget de stockage, et il n'en fait jamais une page que le flux suit intégralement. Il
ne tourne que pendant que le flux en direct tourne, sur la même connexion : le mode avion, ou le
mode protégé sans proxy utilisable, le fait **attendre** (il ne passe jamais en direct), et un
wiki qui lui demande de ralentir est interrogé de nouveau après une pause qui double jusqu'à une
heure. Un redémarrage reprend chaque édition là où elle s'était arrêtée. Sa progression figure dans **Sources
vivantes** et dans le gestionnaire de tâches.

**Pourquoi le parcours peut attendre derrière la première vidange du flux.** Le flux stocke ce qu'il a entendu lors
d'une vidange toutes les 30 secondes ; l'index de recherche, la récupération des autres pages modifiées et le parcours tournent
dans le temps *qui suit* chaque vidange. Une vidange récupère le texte des pages suivies qui ont changé,
et derrière un arriéré (un flux repris des heures en arrière) cela représente des milliers de requêtes polies ; la
vidange a donc désormais une **limite de 20 secondes pour récupérer les textes**, répartie entre les éditions
(la première édition change à chaque vidange). Chaque modification reste enregistrée ; un texte non atteint à
temps est compté comme *différé* et **une vidange ultérieure le récupère** : d'abord les pages jamais stockées, puis
celles qui n'ont pas été vérifiées depuis le plus longtemps (jusqu'à 200 pages par édition et par vidange ; `text_backlog` dans le
rapport de la vidange indique combien de pages le rattrapage a *trouvées* en attente, ce qui n'est pas la même chose que récupérées). Ces pages
sont essayées avant les modifications les plus récentes de l'édition, dans sa part de temps. Une page dont la récupération a échoué ou a été
refusée est laissée de côté par le rattrapage pendant 5 minutes, afin qu'une page que le service refuse sans cesse ne soit pas
redemandée toutes les 30 secondes. Le client
fait une requête par seconde, si bien qu'une vidange récupère une vingtaine de textes : derrière des milliers de textes
différés, le rattrapage prend des heures, pas une seule vidange. La limite porte sur le moment où une récupération peut *commencer* : une
récupération déjà en cours se termine d'abord (chaque connexion ou lecture attend jusqu'à 30 secondes), si bien qu'une vidange peut
dépasser un peu les 20 secondes. Tant que le parcours des pages est activé, il conserve 30 % du temps libre, si bien que la récupération des autres pages modifiées
ne peut pas tout l'utiliser. L'état (`/api/scheduler/status`, le bloc `wiki_lane.service.drain`)
indique où en est la vidange : l'étape (`hot-sets` ou `feeds`), l'édition, depuis combien de temps elle
est dans cette vidange, et combien de vidanges ont échoué d'affilée et pourquoi.

**Lire le W de la barre supérieure.** Le W est l'interrupteur du **flux**, pas celui du parcours : le
parcours est la case à cocher ci-dessus, et il ne tourne que pendant que le flux tourne. La petite marque dans le
coin du W indique par sa forme ce que fait le flux : un point plein signifie connecté et en réception ;
un anneau signifie *choisi mais non connecté* (le mode avion le retient, ou il n'a pas démarré dans cette
session) ; un anneau avec un point signifie qu'il tente de se connecter et échoue, en réessayant de lui-même ; un tiret signifie en pause ;
une croix signifie arrêté. Survolez-la pour lire l'explication, y compris si le parcours des pages est activé. Un clic
sur un anneau **démarre** le flux (vous confirmez une fois le passage en ligne) ; un clic sur un point ou sur un anneau
avec un point le **met en pause** ; Maj+clic l'arrête. Paramètres → Wikipédia affiche les deux mêmes lignes
en toutes lettres au-dessus des éditions. Les deux se redessinent quand vous passez en ligne ou hors ligne, et quand vous cochez
ou décochez le parcours.

**Les autres pages modifiées (désactivé tant que vous ne l'activez pas) :** le flux en direct stocke
le texte des pages qu'il suit et se contente de compter les modifications qu'il signale sur toutes les
autres pages. Cocher **Récupérer aussi le texte des autres pages modifiées** (Paramètres →
Wikipédia, à côté de la case du parcours) récupère aussi le texte le plus récent de ces autres pages,
50 pages par requête, en commençant par la page qui attend depuis le plus longtemps. Une page modifiée dix fois
pendant qu'elle attendait ne coûte qu'une récupération, celle de son état actuel. L'application conserve le texte **le plus récent
et le précédent** de chaque page, et une page supprimée plus tard conserve le texte qu'elle avait. Ces
textes **restent dans le fichier propre à la voie, pas dans votre corpus** ; la zone de recherche les trouve
(voir *Rechercher ce que conserve la voie*, ci-dessous). Ils s'arrêtent quand le fichier de la voie occupe **90 % de son budget de stockage**, afin que le
reste demeure disponible pour les pages que le flux suit ; cette part est un défaut proposé, pas une
décision, et Sources vivantes l'affiche. Cela ne tourne que pendant que le flux en direct tourne, sur la
même connexion et avec les mêmes attentes que le parcours : le mode avion, ou le mode protégé
sans proxy utilisable, le fait attendre (il ne passe jamais en direct), et un wiki qui lui demande
de ralentir est interrogé de nouveau après une pause qui double jusqu'à une heure.

**Un plantage ou une mise à jour ne fait pas perdre la progression.** Tout ce que stocke la voie est écrit par
petites étapes en tout-ou-rien, si bien qu'un plantage (ou l'arrêt forcé de l'application) ne perd au plus que l'étape en cours ; le
parcours reprend à partir de son signet et le flux à partir de la dernière position qu'il a stockée. Ce qui
s'arrête, en revanche, c'est la voie elle-même : l'application démarre toujours **hors ligne**, si bien qu'après un redémarrage rien n'est
récupéré tant que vous ne repassez pas en ligne avec le bouton avion, ce qui reprend l'exécution si elle était active et la laisse arrêtée si elle était arrêtée (l'Accueil affiche une ligne pendant que l'exécution attend). Rien n'est perdu pendant cette attente
(l'historique propre au flux remonte à environ une semaine). Sources vivantes → Wikipédia → Flux
en direct affiche **Durée de fonctionnement** (les heures pendant lesquelles cette installation a stocké ou demandé quelque chose,
comptées à travers les redémarrages, avec le nombre d'arrêts) et, quand la voie est devenue silencieuse, une
ligne **Arrêté** indiquant depuis combien de temps et depuis quand. Les mêmes chiffres figurent dans le rapport de la fenêtre
d'endurance (soak window) sous `wiki_lane.run`. Un arrêt indique que la voie n'a donné aucun signe de vie pendant trois heures ou
plus, pas pourquoi : un plantage, une mise à jour, le mode avion et une application fermée se présentent de la même façon.

**Rechercher ce que conserve la voie :** la voie tient un index de recherche des textes qu'elle
conserve, dans le même fichier et à l'intérieur du même budget de stockage. Le texte **le plus récent**
d'une page modifiée est indexé intégralement, titre compris. Chaque **version plus ancienne** (le texte
précédent d'une page modifiée, et chaque version d'une page que le flux suit, sauf
la plus récente, qui est déjà votre article du corpus) est indexée par les **lignes qu'une modification
ultérieure a supprimées** : le reste se trouve dans la version plus récente, où il est déjà trouvé.
Ainsi, une recherche dont les mots se trouvent en partie dans des lignes conservées et en partie dans des lignes supprimées ne trouve
aucune des deux versions, et chaque liste de ces résultats le signale. L'index est construit pendant que le
flux en direct tourne, avant les récupérations et pendant au plus la moitié de leur temps libre, et
une recherche indique combien de textes l'attendent encore ; un texte illisible
est mis de côté et réessayé au prochain démarrage de la voie. Le chinois, le japonais et
l'arabe sont découpés et normalisés exactement comme dans l'index propre à votre corpus, et les mots en hindi et en
bengali restent entiers. Dans la zone de recherche (Ctrl/⌘-K), ces résultats sont listés sous
**Textes Wikipédia conservés sur cette machine**, à côté des résultats de votre corpus et jamais classés
parmi eux, chacun indiquant son édition, de quel texte il s'agit (le texte le plus récent ou
précédent d'une page modifiée, ou une version antérieure d'une page que le flux suit) et sa date.
En ouvrir un affiche le texte de cette version, l'endroit où il est conservé et son adresse complète sur
Wikipedia ; **Ajouter au corpus** ajoute cette version exacte comme article à part entière, daté du moment où
le wiki l'a produite, et le signale quand votre corpus contient déjà cette version ou les mêmes mots
au lieu de les stocker deux fois. Rien d'autre de la voie n'atteint votre corpus.
La page **Explorer** liste les mêmes résultats dans une section à part, sous les résultats de votre
corpus, chacun avec le passage qui correspond et son propre bouton **Ajouter au corpus**.
Au-dessus, elle indique ce qui a été cherché : uniquement les textes que la voie Wikipédia
conserve sur cette machine, jamais Wikipedia elle-même, avec les pages et les éditions dont ils proviennent,
le nombre de textes qui attendent encore l'index, et si la récupération des autres
pages modifiées est désactivée. Une liste vide signifie donc que les textes de la voie ne contiennent pas vos
mots, et non que Wikipedia ne les contient pas. Les versions que **Suivre maintenant** (Paramètres → Wikipédia)
stocke pour les pages suivies figurent aussi dans cette recherche : elles restent dans la base de données de votre corpus,
et l'index de la voie, dans son propre fichier, les lit de la même façon (chaque version plus ancienne par
les lignes que la version stockée suivante a supprimées, la plus récente intégralement, sauf si votre article du corpus
est déjà cette version). Elles sont trouvées sous le même intitulé, marquées comme
stockées par le suivi des pages, et **Ajouter au corpus** ajoute cette version exacte comme n'importe quelle
autre ; la recherche indique combien de pages suivies elle a lues. Une page que vous suivez à la fois par le flux et par le suivi des pages peut
lister une version une fois pour chaque stockage : les deux stockages sont lus séparément, et aucun ne dépend de
l'autre. Les dumps téléchargés ne font pas partie de cette recherche : leur texte
se trouve dans le groupe Wikipédia de la zone de recherche. Une requête se lit de la même façon dans les deux listes (`salt*`,
`NEAR(salt works, 5)`, `title:salt`), mais les filtres qui décrivent les articles (les champs
Source, Langue et Heure, ainsi que `source:`, `author:`, `url:`, `tag:` et
`title:=`) n'atteignent pas ces textes, et la section le signale chaque fois que l'un d'eux est défini.
Les exports, la fenêtre d'analyse et les actions groupées portent sur votre corpus ; un texte
Wikipedia les rejoint une fois que vous l'avez ajouté.

**Un élément à travers les éditions, et les pages les plus vues** (Sources vivantes → Wikipédia, en
bas). Deux vues qui se contentent de lire ce que cette machine conserve déjà ; aucune ne récupère quoi que ce soit.
*Un élément à travers les éditions* : saisissez un élément Wikidata (Q42) ou cliquez sur l'une des suggestions (les
éléments dont les pages ont fait l'objet du plus grand nombre de modifications enregistrées par le flux cette semaine) et un tableau affiche, pour
chaque édition que vous suivez, la page de cette édition, sa **taille en octets de wikitexte** (lue une seule fois,
quand le parcours des pages a atteint la page), quand elle a été lue, et les **modifications que cette machine
a enregistrées au cours des sept derniers jours**. Une édition sans page en indique la raison : le parcours n'a pas tourné
pour elle, ne l'a pas terminée (avec l'avancement atteint, si bien que l'élément peut s'y trouver), ou l'a terminée
sans en trouver. Le nombre de modifications est ce que le flux en direct a enregistré sur cette machine ; pour une édition pour laquelle il n'a
rien enregistré, il affiche « inconnu », parce que ce n'est pas la même chose que zéro. La barre à côté d'une taille représente cette taille rapportée à la plus grande à l'écran,
à partir de zéro ; rien d'autre n'est calculé, et les éditions sont des articles distincts, pas des
traductions. Le parcours des pages est désactivé tant que vous ne l'activez pas (Paramètres → Wikipédia), si bien que sur une
instance qui n'a pas encore fait de parcours, il n'y a encore rien à comparer et le tableau le signale.
*Pages les plus vues, à côté de votre corpus* : la liste propre à la source des pages les plus vues de sa
dernière journée (rang et nombre de vues tels qu'elle les a fournis ; les cinquante premières lignes sont conservées), chacune à côté
du nombre d'articles de **votre corpus** qui mentionnent le titre en tant qu'expression, publiés ce jour-là (UTC)
et au cours des sept jours qui se terminent ce jour-là. C'est **une seule journée, pas une série** : la liste est
écrasée chaque jour et aucun historique des vues par page n'est conservé. Les chiffres sont ceux de votre corpus,
c'est-à-dire de ce que cette machine a collecté, pas de la presse ; un titre peut être ambigu ou s'écrire
différemment dans une autre langue ; les articles provenant de Wikipedia et les articles en quarantaine ne sont pas comptés ;
une ligne que le comptage n'a pas atteinte dans son délai, ou dont le titre ne contient aucun mot que l'index de recherche puisse retrouver (un simple « - »), affiche « non compté », avec la raison au survol ; les suggestions ne lisent que les 400 pages les plus modifiées de la semaine. Les deux chiffres sont placés côte
à côte et ne sont jamais combinés.

Les lourdes **références plein texte hors ligne** (dumps d'éditions entières) sont *séparées* et se trouvent
dans **Paramètres → Wikipédia** — vous n'en avez pas besoin pour le suivi des modifications. Voir
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

**Lire un dump téléchargé (hors ligne) :** les nouveaux téléchargements de dumps utilisent la
forme *multistream*, et le petit index qui l'accompagne est téléchargé avec — c'est cette
paire qui rend le dump accessible par position. Dans **Paramètres → Wikipédia → Lire une page depuis un
dump téléchargé**, choisissez une édition prête, saisissez un titre de page, et l'application parcourt
l'index, décompresse un petit bloc à son décalage en octets, et affiche le
**wikitexte brut** de la page — entièrement sur cette machine, avec les statistiques du parcours affichées.
Ce que vous lisez est un *instantané à la date du dump*, pas l'article en ligne ; une
correspondance de titre insensible à la casse est proposée et signalée comme telle. Les anciens fichiers à flux unique
ne permettent pas l'accès aléatoire — l'application le dit et suggère un nouveau téléchargement.
La **liste des langues des dumps est limitée aux langues de l'application** (les 12 langues de
l'interface plus les langues de corpus prises en charge par les analyseurs) ; le sélecteur d'édition
des pages suivies ci-dessus conserve la liste complète.

### 3.7a Gouvernements

**À quoi ça sert :** l'onglet **Gouvernements** de la barre latérale (l'ancre dans le code reste `law`, le
libellé est « Gouvernements ») rassemble des données officielles par pays et suit l'évolution du **droit**.
Il comporte six sous-onglets :

- **Pays** — **statistiques officielles** par pays issues de la Banque mondiale (PIB,
  population, espérance de vie, travail, finances publiques + indices courants). **Charger les données standard
  par pays** les récupère (en ligne, soumis à consentement). Chaque valeur est un chiffre publié par un producteur,
  **jamais un score de crédibilité** ; une **valeur manquante est une lacune publiée,
  pas un zéro** ; les producteurs sont affichés, **jamais moyennés**. Chaque chiffre porte son unité, et
  le survol de chaque indicateur explique ce qu'il mesure — deux d'entre eux ressemblent à des erreurs sans en être :
  le nombre d'abonnements mobiles peut dépasser 100 pour 100 personnes (on possède plusieurs cartes SIM) et le taux brut
  de scolarisation peut dépasser 100 % (il compte les redoublants et les élèves plus âgés que l'âge normal).
- **Comparer** — deux pays côte à côte, chaque indicateur sur une ligne alignée. Il s'agit d'un
  **affichage**, pas d'un calcul : il montre le dernier chiffre publié propre à chaque pays et
  l'année à laquelle il se rapporte, et là où un pays n'a pas de chiffre, la cellule apparaît comme une **lacune**.
  Il ne soustrait, ne classe et ne note jamais la paire — c'est à vous de faire la comparaison.
- **Groupes** — agrégats et blocs, selon deux **angles** entre lesquels vous basculez :
  - *Publié* affiche les agrégats que le producteur publie lui-même (les catégories de la Banque mondiale
    « Revenu élevé », « Afrique subsaharienne », « Union européenne », etc.). Une sélection restreinte
    s'ouvre d'abord ; **Tout afficher** étend à l'ensemble complet. Ce sont les chiffres
    du producteur, pas les nôtres. **Les régions de la Banque mondiale ne sont pas des continents** — « Afrique subsaharienne »
    exclut l'Égypte, la Libye, la Tunisie, l'Algérie et le Maroc, qui relèvent de sa région Moyen-Orient et
    Afrique du Nord ; cet angle n'a donc **aucun chiffre pour l'Afrique continentale** et le
    dit, plutôt que d'en assembler un qui aurait l'air officiel.
  - *Calculé (Computed)* agrège nous-mêmes les pays membres, et affiche **plusieurs méthodes côte
    à côte** (moyenne pondérée par la population, moyenne simple, pondération par le PIB, médiane, et un total
    lorsqu'il a un sens) afin que vous puissiez voir à quel point la réponse dépend de la méthode,
    au lieu de recevoir un chiffre unique. Rien n'est classé et aucune méthode n'est déclarée
    meilleure. Un **total** n'est proposé que pour les indicateurs dont la somme a un sens
    (population, PIB, population active) ; pour un pourcentage, un taux ou une espérance de vie, il est
    **refusé, avec la raison affichée**, car additionner des pourcentages produit un chiffre que personne
    n'a mesuré. Chaque chiffre indique sa **couverture** et sa **dispersion** (min/max/n) —
    un chiffre global de bloc qui masque un écart du simple au décuple est vrai et trompeur, c'est pourquoi l'écart l'accompagne
    toujours. Là où des membres manquent, l'agrégat est **refusé par défaut** ; vous pouvez
    le publier quand même, et le résultat est alors étiqueté partiel et nomme précisément les
    membres manquants. La composition des blocs évolue dans le temps (les BRICS comptaient cinq membres jusqu'en
    2024 ; l'UE a perdu le Royaume-Uni en 2020), c'est pourquoi chaque chiffre de bloc indique la **composition
    de référence** (membership vintage) sur laquelle il a été calculé, et un bloc dont nous ne pouvons pas encore sourcer la liste des membres le dit
    clairement au lieu d'afficher un chiffre.
- **Carte** — une **carte choroplèthe ooMap** d'un indicateur au choix, avec un sélecteur
  d'année/d'historique ; cliquez sur un pays pour ouvrir son détail dans le sous-onglet Pays.
- **Droit** — suivi du **droit** (lois, journaux officiels, registres de propriété intellectuelle) à partir de sources officielles
  du monde entier, en observant comment il évolue dans le temps (ce sont les *modifications qui constituent les données*). Un **miroir
  de recherche**, jamais la source qui fait foi et **pas un conseil juridique** — chaque enregistrement renvoie
  à son journal officiel. Un catalogue mondial de véritables sources officielles
  (`legislation.gov.uk`, EUR-Lex, Légifrance, govinfo, WIPO Lex, USPTO, EPO, …) est fourni
  par défaut. **Suivre les modifications maintenant** récupère les documents suivis via le récupérateur
  éthique, en stockant une référence puis des **différences** honnêtes, avec un signalement des changements importants ; **Changements
  juridiques signalés** les liste (juridiction · titre · Δ octets · motifs) avec les différences et
  un lien vers la source officielle. La synthèse fait aussi ressortir une piste de **législation type**
  lorsqu'un texte quasi identique apparaît dans plusieurs juridictions.
- **Statistiques** — le répertoire des producteurs et les chiffres bruts datés par version qui sous-tendent les autres
  sous-onglets, plus **Ajouter les séries au corpus** (voir ci-dessous).

**Les statistiques dans la recherche ordinaire.** Un chiffre que personne ne peut trouver n'est pas vraiment dans votre corpus ;
chaque **série** — un indicateur pour un pays, sur toutes les années disponibles — peut donc aussi être
matérialisée sous la forme d'un **Article** ordinaire. Elle emprunte alors les chemins habituels : la recherche trouve
« espérance de vie France », ses mots alimentent les tendances et les pistes, et elle apparaît dans le Fil
comme n'importe quoi d'autre, sans zone de recherche spéciale à retenir. Quatre points méritent d'être connus :

- Il y a **un Article par indicateur et par pays**, pas un par révision. Un chiffre de 1991
  corrigé met à jour l'Article existant au lieu d'en ajouter une quasi-copie ; relancer la
  tâche ne coûte donc rien et n'ajoute rien.
- Les Articles sont **étiquetés pour ce qu'ils sont** — la source indique « Statistiques officielles
  (Banque mondiale) » et la classe de provenance est `statistics` — de sorte que vous pouvez les inclure ou
  les exclure de n'importe quelle vue, et que les vérifications de coordination qui repèrent de nombreux médias se répétant les uns
  les autres ne peuvent pas prendre des milliers de lignes de même forme pour un accord.
- Le corps de l'article ne mentionne délibérément **que le sujet et les chiffres**, une **lacune publiée
  étant affichée comme une lacune**. Répéter le nom du producteur et le code machine de la série sur chacun
  des quelque 9 800 Articles plaçait « World Bank » tout en haut du classement des mots-clés
  de l'ensemble du corpus — l'échafaudage passant devant ce dont parle réellement votre corpus — c'est pourquoi ce n'est pas fait.
- Pour les retrouver **par producteur** plutôt que par sujet, filtrez sur la source ou sur l'étiquette
  `statistics` ; pour en chercher un **par code de série**, utilisez le sous-onglet Statistiques, qui
  répond de façon exacte plutôt que par correspondance de texte.

Leur matérialisation est une tâche d'arrière-plan que vous lancez depuis **Gouvernements → Statistiques** ; elle peut
être reprise et annulée, et elle ne retarde pas la collecte.

### 3.8 Preuves et chaîne de possession

*(Accessible depuis **Paramètres → Avancé → Sécurité** — « Chaîne de possession » est le titre du panneau ; il a quitté
la barre latérale lors de la refonte « le contenu d'abord ».)*

**À quoi ça sert :** prouver — à un tiers sceptique, hors ligne — que votre corpus
contenait *cet* élément, avec *ce* contenu, à *ce* moment-là, et que l'enregistrement n'a pas
changé depuis. Ce n'est **pas** un système pour lanceurs d'alerte de type SecureDrop ; une « source » désigne ici un
média d'information, pas une personne confidentielle.

Le panneau comporte trois parties :

- **Paramètres et état (Settings & status).** Des interrupteurs pour **Signatures post-quantiques** (ajouter une signature ML-DSA /
  FIPS-204 en plus d'Ed25519), **Ancrage OpenTimestamps** (ancrer dans
  Bitcoin pour une preuve indépendante de la date), **Journalisation automatique à l'ingestion** (ajouter une entrée
  signée à chaque ingestion réussie), et une étiquette **Acteur par défaut**. Point essentiel, l'
  état affiche toujours la situation **effective**, pas seulement votre souhait : si vous activez la cryptographie post-quantique
  ou OpenTimestamps mais que la bibliothèque nécessaire n'est pas installée, il indique *« demandé,
  bibliothèque non installée »* et reste limité à Ed25519/au local — **il n'affiche jamais un voyant vert
  qu'il ne peut pas justifier.** La protection de la clé est également affichée (`aes256gcm-scrypt` lorsqu'une phrase secrète est
  disponible, provenant de `OO_KEY_PASSPHRASE` ou de la phrase secrète de la base de données ; `plaintext-0600` sinon ; et `pkcs8-pbkdf2`
  ou `plaintext-0600` avec une phrase secrète disponible, pour une clé antérieure à 0.6 qui n'a pas encore pu être réenveloppée,
  ce qui indique ce que son fichier contient réellement).
- **Voir et vérifier la chaîne (View & verify chain).** Saisissez un identifiant d'élément (par ex. `article:42`) pour **Voir la chaîne**
  (séquence, action, acteur, date, algorithme de signature), **Vérifier** (revérifie les liens de la chaîne,
  les empreintes, les signatures, les horodatages) ou **Exporter le lot** (un
  fichier vérifiable hors ligne).
- **Ancrer la racine de Merkle (Anchor Merkle root).** Collez une racine de Merkle pour l'ancrer via le fournisseur configuré.

> **Avertissement de confidentialité affiché dans l'application :** l'ancrage dans une blockchain publique publie une
> empreinte de façon permanente et révèle votre adresse IP et le moment de l'envoi aux opérateurs des serveurs de calendrier. Préférez
> le local + OpenTimestamps à des portefeuilles approvisionnés sur la chaîne ; passez par Tor (`HTTPS_PROXY`)
> si vous avez besoin d'anonymat ; ou restez en local uniquement (le défaut ne laisse rien fuiter).

**OpenTimestamps et mode avion.** En mode OpenTimestamps, une entrée d'ingestion dont
le coupe-circuit réseau a refusé la soumission (un Arrêt pendant la collecte) ne reçoit pas à la place
une preuve uniquement locale, car cette preuve serait permanente : l'entrée est due,
et écrite plus tard, marquée tardive, avec son ancrage. La file des entrées dues n'a pas de limite de taille, et
la fin de chaque passe de collecte en écrit au plus 200, chaque entrée avec jusqu'à trois
soumissions aux serveurs de calendrier, effectuées pendant que le journal de possession est verrouillé en écriture. Un arriéré important
ralentit donc la fin des passes de collecte pendant un certain temps une fois que vous êtes de nouveau en ligne.
Tant que le coupe-circuit reste engagé, l'écriture des entrées dues (« Les enregistrer, marquées tardives », ou
`POST /api/custody/reconcile`) s'arrête au premier refus et indique que le coupe-circuit l'a
refusée ; les entrées restent dues. Une simple vérification des lacunes répond toujours, et son bloc `drained`
signale `refused_offline`.

Vérifiez un lot n'importe où, sans cette application :

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
python scripts/verify_evidence.py bundle.json [signer_pubkey]
```

La conception complète — et ce que chaque mécanisme prouve et ne prouve **pas** exactement — se trouve
dans [`docs/USER_MANUAL.md`](USER_MANUAL.md). *(Une refonte prévue pour rendre
cet onglet utilisable sans connaissances particulières et en grande partie automatique est décrite dans
[`docs/ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).)*

### 3.8a Intégrité des sources

*(Le bureau d'intégrité des sources a été déplacé dans **Paramètres → Avancé → Sécurité → « Ouvrir le bureau
d'intégrité des sources »** ; la coordination est aussi désormais signalée automatiquement — sous forme de pistes sur l'Accueil, dans la vue
**Liés** de la fenêtre d'analyse, et sous forme de badges « N copies = une seule voix » dans les listes d'articles
et le lecteur.)*

**À quoi ça sert :** voir la *structure* qui se cache derrière vos sources — et décider, vous-même,
quel signal compte. Il n'y a délibérément **aucun score de confiance** ; un chiffre unique
figerait des biais et réduirait au silence les sources petites, étrangères, nouvelles ou dissidentes. Guide complet :
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

- **Anti-amplification (proposer → vous décidez) :** *Détecter la coordination* trouve
  des déferlements de quasi-doublons publiés en même temps par de nombreuses sources, avec leurs éléments de preuve
  (texte commun, chronologie, hôte). Par défaut, ils sont seulement **annotés** — jamais regroupés
  en silence. **Appliquer le regroupement** pour compter un réseau comme **une seule voix** (dans tout comptage qui
  mesure un consensus) ; il reste signalé, et **Développer (annuler)** rétablit exactement la vue brute
  où chaque source pèse autant. Rien n'est jamais regroupé sans votre action. Les pistes de chambre d'écho sur l'Accueil
  proposent la même action.
- **Profil de la source :** un panneau de dimensions mesurées — coordination, originalité
  (est à l'origine ou fait écho), capacité de production, éléments de transparence, historique — chacune avec
  sa méthode et sa mise en garde, et **aucun score composite**.
- **Annotations partagées (toile de confiance) :** rédigez des faits descriptifs et contestables sur les
  sources (propriété, orientation, coordination, rectifications) ; **exportez**-les sous forme de lot
  **signé** ; **importez** les lots auxquels vous choisissez de faire confiance. *Qui a dit quoi ?* affiche
  toutes les attributions concernant une source et fait ressortir les **désaccords** — jamais moyennés en un chiffre.
  Voir [`docs/USER_MANUAL.md`](USER_MANUAL.md).

### 3.9 Paramètres

**À quoi ça sert :** les préférences, les surfaces d'acquisition et la maintenance — organisées
en **neuf** sections via une sous-navigation : **Graphismes · Général · Cartes · IA · Wikipédia ·
OpenStreetMap · Agenda · Données & sauvegarde · Avancé**.
Ouvrez les Paramètres depuis le **bouton en bas de la barre latérale** ; la palette de commandes
y mène aussi directement. Tout est stocké localement ; aucune télémétrie.

L'usage quotidien ne demande rien de la section **Avancé** : la mécanique de collecte, la gestion des sources, la curation
des mots-clés, l'annuaire des producteurs de statistiques, le catalogue des flux de calendrier, le poste de
diagnostic, **Sécurité** et **Désinstaller et effacer** s'y trouvent tous, dans des **sections repliées qui ne
chargent leurs données qu'à leur ouverture** (le catalogue des sources peut à lui seul contenir des dizaines de milliers
de lignes). Sécurité était auparavant un sous-onglet à part ; c'est désormais l'avant-dernière section d'Avancé,
et les deux actions irréversibles — **Effacement d’urgence** et **Désinstaller l'application** — ont été placées à part
dans une section qui leur est propre (**Désinstaller et effacer**), afin qu'aucune des deux ne puisse être atteinte par erreur
pendant que vous lisez des informations sur le chiffrement. Rien n'a été perdu dans l'un ou l'autre de ces déplacements : chaque commande
qui se trouvait dans le sous-onglet Sécurité y est toujours, sous les mêmes intitulés. **Collecte** et **Sources** sont
documentées plus haut ([3.2](#32-collecter-dans-paramètres--avancé--collecte),
[3.3](#33-sources-dans-paramètres--avancé--sources)) et s'atteignent par Avancé ;
**Wikipédia** ([3.7](#37-wikipedia-dans-paramètres--wikipédia)) garde sa propre section.
Les **chiffres** officiels ne sont pas du tout ici — ce sont des données, ils se trouvent donc sous
**Gouvernements → Statistiques**.

- **Graphismes (Apparence) :** thèmes, couleur d'accent, densité, **police de caractères**,
  et barre latérale développée/réduite. (Il n'y a pas de curseur de taille du texte : il ne faisait que mettre à l'échelle
  l'élément racine, dont presque rien dans la feuille de style n'héritait, si bien qu'il n'avait aucun effet.
  Utilisez le zoom de votre navigateur — il met tout à l'échelle, y compris les parties qu'un curseur
  agissant sur la seule racine ne pouvait jamais atteindre.) Cette section contient aussi la galerie **Interfaces alternatives**
  (marquée *Expérimental*) : huit habillages facultatifs — **Aurora, Atlas, Command, Field,
  Focus, Terminal, Canvas, Editorial** — sur les mêmes données et avec les mêmes garanties
  d'honnêteté ; en choisir un recharge la page pour l'appliquer. (L'ancien tiroir flottant « Personnaliser » est
  désormais cette section à part entière.)
- **Cartes (pistes sur l'accueil) :** chaque producteur de pistes que l'application peut exécuter, regroupé par famille
  (*En hausse · Sur-raconté · Sous-raconté · À enquêter · Vérifier le cadrage · À surveiller ·
  Contexte · Intégrité des données*). Désactivez-en un et il cesse d'apparaître — cela ne change rien
  aux articles eux-mêmes, seulement aux suggestions qui atteignent votre Accueil. Lorsqu'une piste a des
  seuils, ils sont désormais visibles et réglables, chacun avec une **plage sûre** indiquée, une
  note d'une ligne sur l'effet d'un changement, et un bouton **Réinitialiser**. Vous pouvez toujours rendre une piste
  *plus stricte* ; les bornes inférieures existent pour qu'une piste ne puisse jamais affirmer plus que ce que ses éléments de preuve
  permettent — le contrôle d'inondation, par exemple, ne descendra pas sous le seuil p<0.05,
  car en dessous le test ne peut plus distinguer une véritable poussée d'une variation ordinaire. Toute
  valeur hors plage est corrigée **et signalée**, jamais ajustée en silence.
- **Préférences (Général) :** **Thème** (Système/Sombre/Clair), **langue** et **Résultats de recherche par défaut**.
- **Filtrage des mots-clés (Avancé → Mots-clés) :** les mots « bêtes » (mots-outils : le, vous, pas, …) sont retirés par une
  liste d'exclusion multilingue intégrée. Réglez-la : définissez la **Longueur minimale des mots-clés**, **écartez les
  termes purement numériques**, activez ou désactivez la liste d'exclusion intégrée, et tenez à jour une liste de **mots-clés
  exclus** (un par ligne ou séparés par des virgules). Exclure masque un terme
  partout mais reste réversible — les mentions stockées sont conservées. (Vous pouvez aussi cliquer sur ✕
  à côté de n'importe quel mot-clé dans Analyses.)
- **Bases de référence Wikipedia hors ligne :** choisissez une **édition linguistique** dans une **liste à plat**
  (vos langues d'interface d'abord, puis les plus grandes éditions), chaque option commençant par le
  **nom natif** (autonyme) — les éditions sont fondées sur la langue, pas sur le pays, il n'y a donc
  pas de regroupement par continent. Chaque édition disposant d'un dump affiche une **taille
  approximative en ligne** (`~X GB`, tirée d'un tableau daté intégré — aucun accès réseau supplémentaire) pour que vous puissiez juger
  avant de télécharger ; la taille exacte est lue au début du téléchargement. **Télécharger** peut
  reprendre (pause/reprise + un tableau de progression). Ces dumps hors ligne sont lourds et
  facultatifs, et servent uniquement à la lecture/recherche hors ligne — le suivi des modifications en direct (l'onglet
  Wikipédia) n'en a pas besoin.
- **IA (LLM local) :** un encadré **Configurer l'IA locale** en haut expose tout le plan
  restant en un seul endroit — le moteur que cette machine utilisera (vLLM lorsqu'un GPU NVIDIA
  dédié peut le faire tourner, Ollama sinon), ce qui reste à installer, et les
  tailles de téléchargement — et l'exécute d'**un seul bouton** après **un seul** consentement. Il se masque
  de lui-même une fois qu'il n'y a plus rien à faire ; les commandes par composant situées en dessous sont
  inchangées, vous pouvez donc toujours faire chaque étape vous-même. En dessous : le moteur actif
  et **pourquoi** il a été choisi, les modèles installés et un catalogue daté et sélectionné, **télécharger** un
  modèle (une tâche de téléchargement **mise en file d'attente** — une à la fois, annulable, avec la progression
  en direct en octets ; les octets passent par le clearnet via le processus Ollama, **pas** par Tor — c'est indiqué à
  l'invite de consentement), en **retirer** un, et définir le **modèle actif**.
  **L'adéquation du matériel (Hardware suitability)** est indiquée une seule fois, ici, avec ce qu'elle signifie pour vous : l'inférence
  locale n'est refusée par défaut que sous un plancher (moins de 4 cœurs de processeur, ou moins
  de 6 Go de RAM, sans accélérateur) ; fonctionner sans GPU dédié, avec une
  carte à faible VRAM ou sur un petit Mac à mémoire unifiée donne un **avertissement sur ce à quoi
  s'attendre**, pas un refus. Ce n'est **jamais un blocage** — une case à cocher réactive l'IA, et
  l'information reste visible dans tous les cas. **Démarrer** l'IA locale se fait par la **pastille IA**
  de la barre supérieure, depuis n'importe quel écran.
  Un éditeur **« Comportement et invites »** expose les quatre invites système modifiables
  (résumé / traduction / synthèse / extraction de mots-clés) et le maintien en mémoire du modèle.
  Ces quatre invites **sont fournies dans les douze langues de l'interface**, si bien qu'un lecteur francophone ou
  japonais obtient un résumé rédigé dans sa langue plutôt qu'un travail en anglais ;
  l'éditeur affiche le texte intégré pour **votre** langue, et l'invite exacte utilisée
  est enregistrée avec chaque résultat. Votre propre invite, si vous en écrivez une, est utilisée **exactement
  telle que vous l'avez écrite**, dans la langue où vous l'avez écrite. Une liste **Extracteurs personnalisés**
  vous permet de définir des invites gérées qui écrivent des métadonnées dérivées par IA (étiquetées
  *non fiables*, jamais l'index de mots-clés de confiance).
  Lorsqu'Ollama n'est pas présent, un **installateur intégré** apparaît (Linux/Debian) : il télécharge
  le script d'installation officiel, le vérifie par rapport à l'empreinte sha256 attestée par GitHub, affiche
  une étape d'élévation de privilèges visible, et l'exécute — en refusant à la moindre empreinte discordante. macOS/Windows
  reçoivent une indication honnête vers ollama.com/download.
- **Statistiques — l'annuaire des producteurs (Avancé → Statistiques officielles) :** un
  annuaire descriptif des producteurs de statistiques gouvernementaux et internationaux. Les
  **chiffres** eux-mêmes sont des données, ils se trouvent donc sous **Gouvernements → Statistiques**,
  pas dans les Paramètres. Chaque producteur porte la **même mise en garde descriptive sur les sources
  engagées** — un chiffre officiel indique l'organisme qui le produit et sa position — **jamais d'étiquette
  « controversé », de verdict ou de score par source**. Vous pouvez **les ajouter à vos sources** — un producteur dont
  la rubrique actualités/presse est connue est activé et collecté depuis celle-ci, tandis qu'un producteur dont
  l'adresse n'a pas encore été recherchée est ajouté désactivé plutôt que d'être parcouru jusque dans son
  portail de données — et **récupérer des chiffres officiels** depuis des points d'accès machine documentés
  (API de la Banque mondiale / SDMX d'Eurostat), stockés avec leur provenance complète et un **millésime**
  à part entière (une nouvelle récupération crée une nouvelle ligne, jamais un écrasement). Les producteurs sont affichés **côte à
  côte, jamais moyennés**, et une vue **Trianguler (Triangulate)** signale les cellules qui mélangent des unités
  incomparables / des corrections saisonnières / des années de base différentes. **Vérifier les anomalies de révision** signale, de façon purement
  rétrospective, un chiffre stocké dont le millésime le plus récent a déplacé une valeur passée de façon inhabituellement forte
  par rapport à l'historique de révision propre à cette série (aucun score). La récupération sort par le transport
  que vous avez configuré et est refusée en mode avion.
- **OpenStreetMap :** choisissez une région de carte (avec une estimation datée en `~GB`) et téléchargez-la
  sous forme de tâche du gestionnaire de tâches, pouvant être reprise et mise en pause (soumise à l'unique fenêtre de consentement réseau).
- **Infolettres :** importez des infolettres comme articles — **anonymisées à l'ingestion** (le
  destinataire n'est jamais stocké, les échos du destinataire sont masqués, les jetons de pistage sont supprimés
  et les enveloppes de pistage côté serveur sont signalées ; **rien n'est jamais récupéré**, donc l'import
  ne peut jamais révéler que vous avez ouvert ou cliqué). Trois chemins :
  - **Choisir des fichiers .eml (Choose .eml files)** — un petit envoi de plusieurs fichiers.
  - **Importer un dossier entier** — désignez un dossier sur cette machine ; chaque `.eml` qu'il contient
    est importé dans le cadre d'une **tâche d'arrière-plan pouvant être mise en pause et reprise** (visible dans le gestionnaire de tâches) qui
    tient la charge jusqu'à des archives de 20 Go et plus, en ignorant les messages déjà importés.
  - **Récupérer depuis une boîte mail (IMAP/POP3)** — récupération en direct depuis une boîte mail, avec une
    information visible au moment de l'utilisation (TLS vers le fournisseur, votre IP est visible, **pas** via
    Tor, les identifiants ne sont pas stockés). En TLS, le certificat du serveur doit correspondre à son nom
    et provenir d'une autorité à laquelle votre ordinateur fait confiance ; sinon, la récupération est refusée avant
    l'envoi de votre mot de passe, et le message indique pourquoi. Via l'API, une récupération avec
    `use_ssl` à false (généralement sur le port 143/110) passe d'abord en STARTTLS sous le
    même contrôle, et est refusée si le serveur ne le propose pas : votre mot de passe n'est jamais
    envoyé en clair.
  - **À quel éditeur appartient chaque infolettre ?** — les infolettres importées se trouvent actuellement
    toutes dans une seule source fourre-tout. `GET /api/newsletters/publisher-preview` montre à quoi RESSEMBLERAIT
    un classement par éditeur pour les infolettres que vous avez déjà : chaque domaine
    d'envoi, le nombre de messages qui en proviennent, et la source existante à laquelle il se rattache (un véritable
    eTLD+1 tiré d'une Public Suffix List intégrée — ainsi `email.bbc.com` se rattache à `bbc.com` — les
    plateformes d'infolettres étant traitées dans l'autre sens, pour que deux publications Substack ne soient jamais
    fondues en un seul « Substack »). Ce n'est **qu'un aperçu** : rien n'est rattaché ni déplacé, et
    lorsque les éléments ne permettent pas de trancher, il le dit au lieu de deviner.
  - **Supprimer les newsletters importées** — supprime du corpus actif chaque article issu d'une infolettre importée (.eml +
    boîte mail), pour remplacer un lot défectueux par une réimportation propre
    (la restauration est additive, donc laisser les infolettres hors d'une sauvegarde ne les retire jamais — ceci
    les retire).
- **Données & sauvegarde — l'Export / Import unifié :** un seul endroit pour tout sauvegarder, quelle que soit
  la **taille de la base de données**. **Exporter / Sauvegarder…** ouvre une boîte de dialogue : choisissez un **dossier de destination
  ou un disque**, cochez ce qu'il faut inclure (corpus, infolettres importées, modèles de LLM locaux,
  cartes hors ligne, dumps Wikipedia), et donnez une **phrase secrète** — le corpus chiffré est écrit en flux
  dans ce dossier sous forme de **volumes authentifiés indépendamment, plus une parité Reed-Solomon** (ainsi
  un volume perdu/corrompu, même un volume du corpus, peut être reconstruit), et les gros blobs publics
  (modèles / cartes / dumps) sont copiés **tels quels**. Il n'y a **aucune limite de taille** et l'archive n'est
  jamais tenue entière en RAM. La phrase secrète n'a **aucune récupération possible** — une phrase secrète perdue signifie que la
  sauvegarde du corpus ne peut pas être ouverte.
  - **Chaque export crée son propre dossier daté.** La destination que vous choisissez est le dossier PARENT :
    à l'intérieur, chaque export crée `YYYYMMDDHHMM_OpenOmniscience_Backup` — la date et l'heure
    locales du début de l'export, pour que les dossiers se trient dans l'ordre où vous les avez créés. Un second
    export dans la même minute reçoit `_2`, `_3` et ainsi de suite. On n'**écrit jamais dans** un dossier existant,
    si bien qu'une sauvegarde antérieure sur le même disque ne peut pas être endommagée par une suivante.
  - **Chaque export est une nouvelle sauvegarde complète.** Rien n'est réutilisé d'une sauvegarde antérieure, donc un
    export coûte le temps et l'espace de tout ce que vous avez sélectionné — et en échange, chaque
    octet de ce dossier a été écrit par ce seul passage.
  - **Vérifier après l'écriture (Verify after writing)** (activé par défaut). Lorsque le dernier volume est écrit, chaque volume est
    relu depuis la destination et sa somme de contrôle comparée à celle enregistrée lors de son
    écriture. Cela relit chaque octet une seconde fois, ce qui double à peu près la durée d'un
    export sur un disque lent ; c'est la seule chose qui détecte un disque qui a accepté
    l'écriture et stocké autre chose. Le panneau de fin affiche alors **« Vérifiée »** —
    et sinon, il indique laquelle des quatre raisons s'applique : la vérification était désactivée,
    elle a été annulée, le lot n'a pas pu être relu, ou elle a **échoué**, et il nomme alors les
    volumes.
  - **`BACKUP_SUMMARY.md`** est écrit à côté de `volumes.json` à la fin de chaque export :
    les mêmes faits que ceux du panneau de fin — volumes, octets, lignes par table avec
    les articles en premier, fichiers copiés par catégorie, durée écoulée, destination, état du chiffrement,
    versions du schéma et de l'application, résultat de la vérification, et les mentions d'attribution qui s'appliquent à
    ce que contient la sauvegarde. Il est là pour que le dossier s'explique de lui-même sur un disque amovible
    des années plus tard, quand le panneau qui indiquait tout cela aura disparu depuis longtemps. C'est une description,
    pas une signature : `volumes.json` contient les sommes de contrôle par volume qui prouvent les octets.
    **C'est aussi le seul fichier de ce dossier qui n'est pas chiffré** — le corpus est
    illisible sans votre phrase secrète, et ce résumé est du texte en clair à côté de lui, qui indique
    combien d'articles, de sources et de documents suivis contient le corpus. C'est le compromis
    que fait ce fichier, il est indiqué dans le fichier lui-même, et vous pouvez le supprimer si le fait que le dossier
    s'explique de lui-même compte moins pour vous que de ne rien dire à quiconque trouverait le disque.
  - **Les exports ne sont jamais planifiés.** Il n'existe aucun export automatique ou programmé et aucun n'est
    prévu — un export est un **acte délibéré**, parce qu'il écrit votre corpus à un endroit
    que vous avez choisi, à un moment que vous avez choisi.
  **Importer…** désigne un dossier, trouve ce qui peut y être importé (une sauvegarde à restaurer,
  des données volumineuses ou des infolettres) et le restaure. **La restauration est uniquement additive** — elle
  **complète** votre corpus et **ne le remplace jamais** : rien de ce que vous avez déjà n'est
  écrasé, les doublons sont détectés bit à bit, et une valeur en conflit **conserve votre
  valeur locale et signale les deux**, jamais moyennées.
  - **Rapports d'import.** Une fusion par restauration comme un import d'infolettres depuis un dossier
    écrivent ensuite automatiquement un **rapport persistant** sur le disque (dans l'unité
    ARTICLES — jamais une somme de lignes sur plusieurs tables, qui ressemblerait à des millions d'articles alors qu'il
    s'agit en réalité de lignes réparties sur de nombreuses tables) — combien d'articles sont entrés, combien ont été
    écartés comme non-articles (voir **Filtrage des non-articles**, ci-dessous), et le
    « travail induit » qu'il laisse derrière lui (par ex. combien de sources nouvellement importées attendent encore
    leur qualification, voir [§3.3](#33-sources-dans-paramètres--avancé--sources)). Le rapport
    lui-même voyage dans votre **prochaine** sauvegarde chiffrée, il accompagne donc le corpus. Il est
    téléchargeable via `GET /api/backup/import-reports` (liste) et
    `GET /api/backup/import-reports/{filename}` (en JSON, ou `?format=md` pour un
    rendu Markdown lisible) — il n'existe pas encore d'écran dédié dans l'application pour cela,
    utilisez donc ces points d'accès (ou le navigateur) pour en lire un.
  - **Filtrage des non-articles.** Chaque fusion par restauration et chaque import d'infolettres depuis un dossier
    filtre automatiquement les articles qu'il vient d'apporter et **met en quarantaine** — conservés,
    jamais supprimés, et de façon réversible — ceux qui répondent aux mêmes critères de validité d'extraction
    que l'essai de qualification des sources (une page de menu de navigation, une liste de liens, une
    extraction ratée). Un article en quarantaine est exclu de la recherche et des analyses mais
    reste dans la base de données et voyage dans vos sauvegardes ; le décompte figure dans le rapport d'import.
  > **Chemins anciens / de migration (conservés pour les anciennes sauvegardes).** Un panneau séparé restaure une
  > **ancienne archive mono-fichier `oo-backup-2`** avec le même **aperçu** de fusion additive
  > (nouveau / doublon / conflit) avant **Appliquer (Apply)** (sur une copie préparée et vérifiée, échange atomique,
  > un instantané `pre-restore-*.db` conservé à côté de la base de données). Un instantané brut **Télécharger la sauvegarde (.db)**
  > (API de sauvegarde en ligne de SQLite) est rangé sous *« Ancien outil de sauvegarde… » (Older backup tool…)* pour un usage
  > manuel. **La restauration destructrice « remplacer votre corpus » a été entièrement supprimée** — aucun parcours
  > ne peut écraser vos données, et la restauration d'une sauvegarde **chiffrée** ne déchiffre jamais silencieusement
  > votre corpus.
- **Maintenance (panneau Diagnostics) :** **Nettoyer les mots-clés (réindexer, puis élaguer)** et
  **Réindexer tout le corpus** lancent une **tâche d'arrière-plan pouvant être mise en pause, avec un curseur persistant**
  (elle survit à la fermeture d'un onglet ou à un redémarrage et reprend là où elle s'était arrêtée). Lancez le nettoyage après
  une mise à jour du moteur de mots-clés pour appliquer les nouvelles listes d'exclusion/familles aux articles existants.
  **Replier les formes de mots-clés (études → étude)**, à côté, effectue la seule partie de ce nettoyage
  dont la lemmatisation a besoin, sans relire aucun article : les mots-clés indexés avant l'ajout de la lemmatisation
  séparent « studies » du « study » qu'utilisent les nouveaux articles, et le repli classe ces
  mentions plus anciennes sous la forme de base, exactement comme le ferait une réindexation. Il définit ensuite la
  langue de chaque mot-clé à partir des langues de ses mentions. Les expressions, les noms et les mots-clés qu'utilisent vos
  familles ou groupes ne sont jamais repliés. C'est une tâche pouvant être mise en pause dans le gestionnaire de tâches, et
  **Rapport de repli (.json)** montre ce que le dernier repli terminé a compté ainsi que ses plus grands replis.
  Un repli ne peut pas être annulé ; un élagage ultérieur supprime les mots-clés qu'il a vidés.
  **Réindexer la recherche (arabe, chinois, japonais)** indexe les articles écrits avant cette
  version de la même manière que les nouveaux, afin que les articles arabes, chinois et japonais plus anciens soient aussi trouvés par
  mot. Elle lit chaque article une fois et ne réindexe que ceux dont l'entrée de recherche
  changerait ; c'est une tâche pouvant être mise en pause dans le gestionnaire de tâches, et **Rapport de réindexation de la recherche (.json)**
  indique combien d'articles elle a vérifiés et réindexés, par écriture. Relancez-la après une mise à jour de jieba ou
  du dictionnaire japonais : les articles que le nouveau dictionnaire découpe différemment sont
  réindexés, et le rapport nomme les versions avec lesquelles elle a tourné.
- **Instrumentation temporaire de test de terrain (cycle de test en conditions réelles 0.0.8).** Pendant ce
  cycle, l'application exerce automatiquement chaque surface réseau une fois *au sein de vos
  propres passes de collecte* (vérification des flux de calendrier par lots polis, imports des flux de marchés
  et d'indices, un suivi de loi, un suivi wiki) et enregistre chaque
  résultat mot pour mot dans `data/field_test.jsonl`, inclus dans le lot de débogage.
  **Objectif :** améliorer de façon récurrente les listes de sources, de flux
  et de calendriers de l'installation par défaut à partir de verdicts réels — le mainteneur réinstalle,
  parcourt l'application et partage le lot avec le développement. **Elle est désactivée par
  défaut depuis la 0.1** — activez-la pour un cycle de test en conditions réelles avec `OO_FIELD_TEST=1`.
  L'application ne transmet jamais rien : les journaux restent sur cette machine jusqu'à ce que *vous*
  les téléchargiez et les partagiez. Le démarrage reste entièrement hors ligne dans tous les cas.
- **Journal de diagnostic :** une synthèse partageable de la façon dont l'application voit votre corpus — générée
  uniquement lorsque vous cliquez, uniquement des comptages et des structures (jamais de scores), et vous seul décidez qui
  reçoit le fichier. Le panneau comporte UN SEUL bouton **Diagnostics**, sa case **Approfondi**, et deux petits liens, **Tous les mots-clés** et **Enregistrer à nouveau le dernier Diagnostics** ; chaque autre journal de ce tableau est un **membre de l'archive Diagnostics**, pas un bouton à
  part (plusieurs contiennent plus d'un rapport : `selftests.json` contient les treize auto-tests de mécanismes
  avec un verdict chacun, `storage.json` les lectures d'empreinte, de composition, de volume et de persistance,
  `contention.json` le verrou d'écriture et l'attribution des blocages, `ai-runs.json` les résultats des dernières tâches d'IA,
  `run-journal.json` le résumé et ses lignes brutes ; le `merged.replaces` d'un membre fusionné dans le manifeste
  nomme les fichiers qu'il a remplacés, afin qu'une ancienne archive puisse être lue en regard d'une nouvelle) :

  | Export ou membre de l'archive | Ce que c'est |
  |---|---|
  | **Diagnostics** (et sa case **Approfondi**) | UNE seule archive avec tout ce que cette installation peut dire d'elle-même, construite en arrière-plan (l'application reste utilisable) puis remise : **un seul fichier** s'il tient en 4 Mo, sinon **des fichiers numérotés de 4 Mo au plus chacun** (`…-part-03-of-12.zip`) plus un petit `…-manifest.zip` qui liste chaque fichier avec sa taille et son SHA-256. Chaque fichier s'ouvre seul dans n'importe quel outil de décompression. **Rapide (Quick)** (le choix par défaut) écrit d'abord les relevés, la collecte continuant de tourner, puis autant d'analyses de votre corpus que dix minutes le permettent, des plus courtes aux plus longues ; une analyse qui n'a pas tenu est **nommée dans le fichier** comme non exécutée, avec la raison, jamais omise en silence. **Approfondi** (la case à côté du bouton, de nouveau vide à chaque ouverture du panneau) exécute toutes les analyses, chacune jusqu'à cinq minutes, la collecte étant mise en pause pendant leur exécution (27 à 47 minutes mesurées sur un gros corpus). Le `manifest.json` du fichier indique quel mode a tourné, la machine sur laquelle il a tourné (build, versions des bibliothèques, palier de mémoire, les noms des commutateurs `OO_*` qui étaient définis, jamais leurs valeurs), et pour chaque membre son domaine (mémoire, stockage, base de données, sessions, exécutions, mots-clés, interface, sources, IA, auto-tests, build). Voir « Enregistrer les fichiers numérotés » ci-dessous |
  | **Enregistrer à nouveau le dernier Diagnostics** (un lien sous le bouton, affiché dès qu'une construction existe) | la même archive terminée, enregistrée à nouveau (saisissez d'abord un numéro de partie dans « Commencer au numéro de partie » et l'enregistrement commence là, pour que vous puissiez renvoyer uniquement celles dont l'envoi a échoué). Il ne fait que réutiliser une archive que vous avez déjà construite — il ne lance jamais une nouvelle construction. Si un journal isolé est trop gros pour tenir dans un fichier, il est coupé aux limites des enregistrements en morceaux numérotés, et le manifeste indique lesquels (une coupe à l'octet, `.part0001of0003`, est le dernier recours et est nommée dans `volumes.json`) |
  | **Tous les mots-clés** (un lien) | la liste par mot-clé : chaque mot-clé du corpus (pas seulement les premiers par langue), sans limite de taille totale, sous forme de fichiers numérotés de 4 Mo au plus chacun. Les premiers fichiers contiennent les 5 000 premiers de chaque langue, donc si vous ne pouvez pas tous les envoyer, envoyez-les dans l'ordre des numéros. L'écriture sur disque se fait par lots, si bien que la mémoire de l'application reste stable quelle que soit la taille du corpus ; un gros corpus produit beaucoup de fichiers (la page indique combien avant que vous n'en enregistriez aucun) et prend des minutes, et l'export s'arrête avec un message clair (et supprime ses fichiers partiels, là où le disque le permet) si la mémoire ou le disque vient à manquer. Tout le reste de ce que contenait le journal des mots-clés se trouve, là où la construction Diagnostics l'a exécuté, dans l'archive Diagnostics sous le nom `keyword-log-digest.json` : les familles (les 1 000 premières imprimées, chaque famille comptée dans le résumé du fichier), vos corrections, les super-groupes, la concentration par source, les candidats mots vides et anneaux et les comptages du corpus, tels que le journal des mots-clés les contenait, plus les 100 premiers mots-clés par nombre de mentions avec le nombre de ceux laissés de côté. Une construction Rapide sur un gros corpus peut nommer le condensé comme non exécuté parce qu'il n'a pas tenu dans les dix minutes (cochez **Approfondi**), un ordinateur sans la mémoire nécessaire le nomme comme refusé, et un condensé qui dépasse sa propre limite de cinq minutes est nommé comme ignoré (Approfondi conserve cette limite) ; ce lien est alors le chemin vers les mots-clés, et son propre résumé est construit sur chaque mot-clé, pas seulement sur les 5 000 premiers de chaque langue. Sur un ordinateur à court de mémoire qui exécute tout de même le condensé, les familles ne sont regroupées que sur les premiers mots-clés de chaque langue, et le fichier le dit et renvoie vers ce lien. Il n'y a pas de bouton pour enregistrer à nouveau le dernier lot de fichiers de mots-clés : après avoir rechargé la page, appuyez sur le lien pour construire un nouveau lot |
  | **Auto-test des mots-clés (.json)** | une vérification sur des cas de référence que la présélection des mots-clés se comporte toujours correctement (par ex. *WHO* ≠ *who*) |
  | **Rapport du moteur de mots-clés (.json)** | composition, précision des entités, couverture des traductions/étiquettes, état par langue |
  | **Courbe de croissance des mots-clés / (.json)** | nombre cumulé de mots-clés distincts en fonction des mots ajoutés (le vocabulaire arrive-t-il à saturation ?) |
  | **Diagnostic des cartes d'accueil (.json)** | chaque piste de l'Accueil ouvre-t-elle son corpus exact ou un repli approximatif ? |
  | **Journal d'extraction de dates (.json)** | couverture de l'étiquetage des dates |
  | **Occupation des mois (.json) (Month occupancy (.json))** | parmi les noms de mois que le filtre de mots-clés écarte, combien faisaient réellement partie d'une date — l'élément de preuve pour décider si ce filtre devrait tenir compte des dates |
  | **Journal réseau (.json)** | résultats des récupérations avec des verdicts tenant compte du transport |
  | **Rapport de performance / Test de montée en charge / Test du rollup (.json)** | mesures de temps et vérifications de montée en charge |
  | **Lot de débogage (.json)** | un lot d'assistance consolidé |

  **Enregistrer les fichiers numérotés.** La page indique combien de fichiers sont prêts (« 13 fichiers de 4 Mo au plus sont prêts (manifeste : 1, parties numérotées : 12) »)
  et les remet à votre navigateur **cinq par clic**, le manifeste en premier, parce que cinq est ce que contient un message d'envoi et qu'un clic est ce qui fait
  accepter un téléchargement à un navigateur. Votre navigateur peut demander une fois l'autorisation de télécharger plusieurs fichiers : acceptez. Après les cinq premiers, le bouton affiche « Enregistrer les 5 suivants » ;
  « Enregistrer tout le reste » est proposé dès qu'il reste plus de cinq fichiers, pour un seul clic qui fait tout. Un lot de cinq fichiers ou moins, ce qui est le cas habituel, est
  remis à votre navigateur par la page elle-même à la fin de la construction (le clic qui l'a lancée est loin derrière) ; « Enregistrer à nouveau le dernier Diagnostics » envoie de nouveau les mêmes fichiers. La page ne peut que *demander à votre navigateur* d'enregistrer
  un fichier, elle affiche donc « Votre navigateur a reçu la demande d’enregistrer 5 fichiers sur 13 », jamais qu'ils sont enregistrés : regardez dans votre dossier de téléchargements (un navigateur qui a refusé la
  question des téléchargements multiples n'enregistre rien et ne le signale pas à la page). Pendant que des fichiers sont en route, les boutons sont grisés, et un second clic ne fait
  rien. Chaque fichier fait au plus 4 000 000 octets (la taille à laquelle cette application découpe) et s'ouvre seul, vous pouvez donc en envoyer certains maintenant et
  le reste plus tard. Pour renvoyer seulement certains fichiers, saisissez un numéro de partie dans « Commencer au numéro de partie » et appuyez sur « Enregistrer à partir de cette partie » : cela remet cinq fichiers
  à partir de cette partie (le manifeste n'est pas enregistré de nouveau), et un numéro au-delà de la dernière partie commence à la dernière et le signale. Un numéro que vous saisissez dans cette même case indique aussi
  à « Enregistrer à nouveau le dernier Diagnostics » où commencer (un numéro que la page y a écrit elle-même est ignoré, donc « à nouveau » avec la case non modifiée
  commence au manifeste). Renvoyer une partie ne déplace pas « Enregistrer les 5 suivants » : celui-ci continue à partir du fichier le plus avancé déjà remis au navigateur. Saisir un numéro situé au-delà des fichiers déjà enregistrés saute ceux
  d'entre les deux (le décompte dans la ligne d'état indique combien ont été demandés) ; saisissez le numéro de la première partie manquante pour combler le trou.
  Un lot est complet lorsque chaque nom de `…-part-01-of-NN` à `…-part-NN-of-NN` est présent et que son SHA-256 correspond au
  manifeste. Pour lire un lot avec le script d'analyse, donnez-lui le dossier (ou n'importe quel fichier du lot) : `python scripts/analyze_keyword_log.py <folder>` — il
  nomme les parties manquantes ou qui diffèrent du manifeste, ignore une partie endommagée, et lit le reste.

  Le même panneau exécute aussi l'**enrichissement des sources** en local (déduire des étiquettes de thème à partir de votre
  corpus) et des passes **Wikidata** soumises à consentement (types de sources, découverte de nouvelles sources).
- **Sécurité et usage à risque (Avancé → Sécurité) :** des outils pour les journalistes qui travaillent sous
  pression, chacun étiqueté avec sa **limite honnête** :
  - **Chiffrement au repos (par défaut pour les nouveaux corpus).** Les nouvelles bases de données sont
    chiffrées sur disque avec SQLCipher 4 : à chaque démarrage, l'application demande **LA
    phrase secrète** — un secret unique et stable, comme un identifiant d'utilisateur (`OO_DB_PASSPHRASE` pour les
    exécutions scriptées/sans interface). **Il n'existe aucune récupération et aucune autre
    voie de déchiffrement** : une phrase secrète perdue coûte du temps de recollecte, car le
    corpus est reconstruit à partir du web — il ne contient rien de personnel au-delà de ce qui a été
    collecté et déduit de sources publiques. Les corpus existants en clair continuent de
    fonctionner sans changement ; **Paramètres → Avancé → Sécurité → « Chiffrer ce corpus… »** en convertit
    un *sur place* (consentement explicite, vérification complète avant l'échange, et un
    instantané en clair conservé délibérément comme porte de sortie — supprimez-le une fois que
    vous avez réussi à déverrouiller). Le **doctor** (`GET /api/system/doctor`,
    et le même panneau) atteste l'état *réel* de chaque magasin de données en lisant les
    en-têtes des fichiers — corpus, journal de chaîne de possession, clés de signature — jamais par supposition.
    **La limite honnête :** le chiffrement au repos protège un *fichier saisi ou
    copié*. Il ne peut pas protéger une session en cours compromise (la clé réside en
    mémoire pendant que l'application tourne), et il n'est indépendant du chiffrement intégral du disque
    que si les deux phrases secrètes diffèrent. Le fonctionnement en clair reste disponible
    comme choix explicite (`OO_DB_PLAINTEXT=1`) — l'application n'affiche jamais d'écran de
    verrouillage par-dessus un fichier en clair, car ce serait une sécurité fabriquée.
    Les sauvegardes d'un corpus chiffré fonctionnent sans changement : les membres de l'artefact sont
    portables, l'enveloppe propre à l'artefact chiffré les protège au repos,
    et les restaurations préservent le chiffrement de votre corpus (vérifié par des tests).
  - **Sauvegarde chiffrée** — un instantané protégé par phrase secrète (AES-256-GCM + scrypt).
    Une phrase secrète perdue ou erronée signifie que le fichier ne peut pas être ouvert : il n'y a aucune récupération.
    Pour réintégrer une sauvegarde chiffrée, utilisez la **restauration par fusion additive** dans
    **Données & sauvegarde** (ci-dessus) — elle présente un aperçu, puis complète votre corpus sans jamais
    le remplacer, et ne déchiffre jamais silencieusement votre magasin actif. *(L'ancienne restauration chiffrée
    destructrice par remplacement a été supprimée.)*
  - **Maintenance de la base de données** — *Compacter la base (VACUUM)* reconstruit le fichier
    de la base de données : il récupère l'espace que laissent les suppressions (affiché comme « Espace
    récupérable », une véritable lecture de `PRAGMA freelist_count`) et défragmente les index.
    Il prend un temps proportionnel à la taille du fichier et met en pause les écritures de la collecte
    pendant qu'il tourne ; le résultat indique les octets réellement libérés et la durée. Il
    n'interprète ni ne supprime jamais de données. Il construit la copie compactée en mémoire
    (l'écrire dans un fichier temporaire corrompt un fichier chiffré à la taille de page de
    l'application, c'est mesuré), il vérifie donc d'abord que l'ordinateur a la mémoire nécessaire
    (environ 1,25 fois la partie du fichier en usage, en plus de la mémoire libre
    que l'application garde toujours pour elle-même) et la place sur le disque (environ deux fois
    la partie en usage, plus la taille du journal du fichier), et lorsque l'une ou l'autre manque,
    il dit laquelle, avec les chiffres, et ne démarre pas. Une valeur qu'il n'a pas pu
    lire n'est pas vérifiée, et il le dit aussi.
  - **Mode de collecte réseau** — *Transparent* (par défaut ; poli, nomme l'outil dans le
    User-Agent) ou *Protégé* (les récupérations web de l'application passent par un proxy que **vous** faites tourner,
    par ex. Tor, avec un User-Agent générique). La seule exception concernant le User-Agent concerne les requêtes d'API
    et de dumps de l'application vers les serveurs de Wikimedia (ses fonctions Wikipedia, Wikidata et dumps) :
    la politique d'API de Wikimedia demande à chaque outil de se nommer, donc en mode protégé ces
    requêtes portent toujours le User-Agent propre à l'outil, via le même proxy et uniquement en
    https. Tout autre contenu récupéré sur un site Wikimedia (un article collecté comme n'importe quelle autre
    page) reçoit le User-Agent générique. Trois éléments se connectent directement même en mode protégé, comme
    l'indique pour chacun l'info-bulle de la fenêtre de consentement réseau : la récupération depuis la boîte mail des infolettres,
    l'ancrage OpenTimestamps et les téléchargements de l'IA locale.
    Le mode protégé **ne peut pas garantir l'anonymat** — vous devez faire tourner le proxy et lui faire confiance
    vous-même ; il refuse de s'activer sans URL de proxy. Les proxies SOCKS comme Tor ne demandent
    rien d'autre à installer.
  Les deux actions **irréversibles** se trouvent une section plus bas, sous **Avancé →
  Désinstaller et effacer**, délibérément à l'écart de tout ce qui précède :

  - **Effacement d’urgence** — supprime de façon irréversible le corpus, les clés et les caches sur cette machine
    (double confirmation). **Limite :** l'écrasement sur place ne garantit *pas* l'impossibilité
    de récupération sur SSD/mémoire flash — pour cela, utilisez le chiffrement intégral du disque (LUKS/Qubes/Tails)
    et détruisez la clé. Il existe aussi une commande CLI `panic` et un mode d'exécution `--ephemeral`
    (données en RAM uniquement, effacées à la sortie).
  - **Désinstaller l'application** — supprime le **virtualenv** et les **lanceurs de bureau** de l'application,
    puis arrête le serveur (confirmation par saisie). Vos **données sont conservées** (utilisez d'abord l'Effacement d’urgence pour
    les détruire) ; le dossier de l'application est laissé en place, à supprimer manuellement. Équivalent à
    `./install.sh --uninstall` ou à l'icône de bureau **« Uninstall Open Omniscience »** que
    l'installateur crée à côté des deux lanceurs de l'application.

  La gouvernance et les lignes rouges liées au double usage qui encadrent tout cela se trouvent dans
  [`GOVERNANCE.md`](GOVERNANCE.md) (également dans **Aide & docs**).

### 3.10 Aide & docs

**À quoi ça sert :** lire la documentation **dans l'application**, hors ligne. Une
liste à gauche sélectionne un document (ce **Manuel de l'utilisateur** est celui par défaut ; les autres
approfondissent des sujets précis), affiché à droite avec une **recherche dans la page**. Ouvrez-la
depuis le **?** de la barre supérieure ou la palette de commandes (« Ouvrir le manuel de l'utilisateur » (Open the User Manual)). Le
schéma brut de l'API se trouve à `/openapi.json`.

---

## 4. Tâches courantes (mode d'emploi)

**Rassembler l'actualité sur un sujet et y faire des recherches**
1. **Paramètres → Avancé → Sources** → vérifiez que les sources pertinentes sont activées (filtrez par pays/étiquette).
2. **Paramètres → Avancé → Collecte** → cliquez sur **Récupérer le flux** pour chaque source, ou réglez le
   **planificateur** (scheduler) en mode RSS avec vos **Étiquettes / mots-clés** (Tags/keywords) puis **Démarrer** (ou passez simplement en ligne
   — la collecte se lance automatiquement).
3. Cherchez depuis l'**omnibarre** (omnibar) → requête booléenne → **Exporter en CSV/JSON** si besoin.

**Surveiller un sujet en continu, en arrière-plan**
1. **Paramètres → Avancé → Collecte** → planificateur **Mode : Flux RSS**, réglez **Langues**/**Étiquettes**,
   **Aperçu des cibles**, réglez un **Intervalle**, cochez **Démarrer automatiquement au lancement**,
   **Enregistrer** (Save).
2. Vous pouvez aussi activer **Preuves & possession → Journalisation automatique à l'ingestion** pour que chaque capture soit
   signée dès son arrivée.

**Produire une preuve d'un article recevable devant un tribunal ou une rédaction**
1. Recherchez le ou les articles depuis l'omnibarre.
2. **Exporter des preuves signées** (ou **Preuves & possession → Exporter le lot** pour un élément).
3. Remettez au destinataire le lot ainsi que `scripts/verify_evidence.py` /
   `verify_custody.py` ; il vérifie hors ligne, sans avoir à vous faire confiance ni à faire confiance à cet outil.
4. Pour une preuve de *date* indépendante, activez **OpenTimestamps** et ancrez la racine de Merkle
   du lot (tenez compte de l'avertissement sur la confidentialité).

**Surveiller un article Wikipédia controversé pour détecter des manipulations**
1. **Paramètres → Wikipédia** → ajoutez la page (édition + titre), cochez **utiliser les scores ORES**,
   **Suivre maintenant**.
2. Examinez les **Modifications signalées** ; ouvrez **Différences** sur tout ce qui paraît suspect.

**Suivre le prix d'une matière première au regard de l'actualité**
1. **Matières premières** — les flux sélectionnés se mettent déjà à jour automatiquement en arrière-plan ;
   pour le prix d'une page précise, ajoutez une **règle d'extraction de prix** et **Testez**-la.
2. Cliquez sur la carte de la série → lisez le graphique et la **corrélation** avec une requête d'actualité.

**Déplacer (ou fusionner) votre corpus vers une autre machine**
1. **Paramètres → Données & sauvegarde → Exporter / Sauvegarder…** — choisissez un dossier/disque de destination et
   une phrase secrète ; le corpus est écrit en flux sous forme de volumes chiffrés + parité (quelle que soit la taille).
2. Sur l'autre machine, **Paramètres → Données & sauvegarde → Importer…** — désignez ce dossier et
   restaurez. La restauration est additive — elle complète le corpus de cette machine et ne
   le remplace jamais, si bien que vous pouvez aussi vous en servir pour *fusionner* deux corpus. Une ancienne sauvegarde
   `oo-backup-2` en fichier unique ne demande rien de particulier : l'analyse d'importation en trouve une, où qu'elle soit imbriquée dans le
   dossier désigné, et la propose comme un élément à part entière ; les anciennes sauvegardes restent donc restaurables.

**Copier plutôt le dossier entier — une manière à part entière de déplacer ou de sauvegarder**

Les outils intégrés existent pour ajouter ce qu'une copie de fichiers ne sait pas faire (un manifeste signé, une parité qui
répare un volume endommagé, une fusion additive de deux corpus, une restauration sélective). Ce n'est
pas un passage obligé. Copier le dossier de données est une voie prise en charge quelle que soit la taille, et c'est
la bonne pour déplacer une machine en bloc :

1. **Arrêtez l'application** — le bouton d'alimentation dans la barre du haut, ou Ctrl-C dans son terminal. Ce n'est
   pas facultatif : une copie faite pendant qu'elle tourne peut saisir un WAL à moitié écrit.
2. Copiez tout le dossier **data** (§5.1 — `<app folder>/data/`, ou là où pointe `OO_DATA_DIR`).
   Pas le dossier de l'application/du code : le code peut être réinstallé, les données non.
3. Sur l'autre machine, placez le dossier où vous le souhaitez et faites pointer `OO_DATA_DIR` dessus —
   ou, sur une installation toute neuve, choisissez ce dossier à l'étape du premier lancement (§5.1).

Le corpus reste chiffré au repos pendant la copie, et les clés voyagent à l'intérieur du dossier ;
**la phrase secrète est donc la seule chose que vous devez apporter séparément**. Depuis 2026-08, les poids de l'IA locale
se trouvent aussi dans le dossier de données, si bien qu'une copie les emporte également — c'est ce qui en fait
un véritable déplacement de toute la machine, et non du seul corpus.

---

## 5. Référence technique

### 5.1 Où se trouvent vos données

Déterminé par `src/paths.py`, dans cet ordre de priorité :

1. **`OO_DATA_DIR`** s'il est défini (l'emporte toujours).
2. **Copie des sources** — si l'application tourne depuis un dépôt accessible en écriture (installation de développement/éditable/Qubes
   dans `$HOME`), les données se trouvent dans `<repo>/data/`.
3. **Par utilisateur** — sinon XDG : `$XDG_DATA_HOME/open-omniscience` ou
   `~/.local/share/open-omniscience`.

Le cas 2 est le cas normal pour une installation par `install.sh` : l'installateur clone une
arborescence accessible en écriture, vos données se trouvent donc dans `<app folder>/data/` et le chemin XDG du cas 3
n'est jamais créé. Si vous le cherchez et qu'il n'existe pas, ce n'est pas un bogue.

**Choisir le dossier au premier lancement.** La toute première fois que vous démarrez l'application —
après les étapes de langue et juridiques, avant de définir la phrase secrète — elle vous demande où
votre corpus doit être placé. Garder l'emplacement par défaut se fait en un clic. Si vous choisissez un autre
dossier (un disque externe, par exemple), l'application crée un dossier nommé **`OOS data`**
à l'intérieur et enregistre ce choix dans `oo.env` à la racine de l'installation, que
`scripts/launch.sh` lit à chaque démarrage.

Deux aspects de cette étape sont délibérés et bons à savoir :

* **Elle n'apparaît que sur une installation toute neuve.** Dès qu'un corpus existe, l'application refuse
  de modifier ce réglage, car elle ne peut pas déplacer ce qui s'y trouve déjà : les clés,
  le journal de possession et le magasin de modèles suivraient le nouveau réglage tandis que le corpus
  resterait en arrière, et le démarrage suivant trouverait un dossier vide et proposerait d'en créer
  un. Déplacer un corpus existant, c'est la simple copie de dossier décrite au §4 (« Copier plutôt le
  dossier entier ») — arrêtez l'application, copiez le dossier de données, faites pointer `OO_DATA_DIR`
  vers la copie.
* **Choisir un autre dossier met fin à la configuration et vous demande de redémarrer l'application.**
  Rien n'a encore été créé à ce stade ; le dossier ne prend effet qu'au démarrage
  suivant, et continuer dans la même session placerait donc le corpus dans l'ancien dossier
  alors que le choix enregistré pointerait vers le nouveau.

Vous êtes averti, sans être bloqué, si le dossier sort de l'ordinaire : un dossier qui contient déjà un
corpus (continuer l'ouvre au lieu d'en créer un nouveau), un système de fichiers
en mémoire vive (tout ce qui y est écrit est perdu au redémarrage), ou peu d'espace libre, avec
le chiffre. Seul un dossier dans lequel l'application ne peut réellement pas écrire est refusé.

**Si le disque est débranché.** Un dossier choisi de cette façon reçoit un petit fichier marqueur,
`.oos-volume`, dont l'identifiant est aussi enregistré dans `oo.env` (`OO_DATA_VOLUME_ID`). L'application
le lit toutes les deux secondes pendant qu'elle tourne. Si le disque disparaît :

* L'application consigne la déconnexion sur le disque interne (dans
  `~/.local/state/open-omniscience/`, puisqu'elle ne peut pas écrire sur le disque absent).
  Le lot de diagnostics contient ce journal, et le démarrage suivant le mentionne quand il
  explique comment la session précédente s'est terminée.
* La collecte se met en pause et une fenêtre vous demande de reconnecter le disque dans les 30 secondes.
  Si le même disque revient, l'application redémarre pour rouvrir vos données (un corpus
  chiffré redemande sa phrase secrète). Elle ne peut pas simplement continuer : la connexion à la
  base de données est fixée au démarrage de l'application.
* Passé ces 30 secondes, un second compte à rebours ferme proprement l'application au bout de 30 secondes
  supplémentaires ; **Fermer maintenant** le fait immédiatement. Reconnecter le disque pendant ce second compte à rebours
  redémarre quand même l'application à la place.
* Ce qui était en cours d'écriture dans les derniers instants avant le débranchement peut être perdu. La
  base de données elle-même reste cohérente : SQLite annule une écriture inachevée à sa prochaine
  ouverture.

Si vous démarrez l'application alors que le disque n'est pas connecté, elle ne crée pas de dossier vide
à sa place : elle affiche une page « Votre disque de données n'est pas connecté », revérifie
toutes les quelques secondes et ouvre l'application dès que le disque est de retour. Un autre
disque monté au même chemin est reconnu comme différent (son marqueur ne
correspond pas). Si vous avez supprimé le dossier volontairement, retirez les lignes `OO_DATA_DIR` et
`OO_DATA_VOLUME_ID` de `oo.env` pour repartir avec un nouveau corpus vide.
L'effacement d'urgence le fait pour vous. Si le système monte le disque à un nouveau chemin
après l'avoir rebranché, l'application ne peut pas l'y trouver : fermez-la, et faites pointer `OO_DATA_DIR` dans
`oo.env` vers le nouveau chemin.

Dans ce répertoire, vous trouverez : `open_omniscience.db` (le corpus, SQLite/WAL),
`app_settings.json` (thème, limite de résultats), `custody_settings.json` (préférences de
possession), les clés de possession, les dumps Wikipédia téléchargés, d'éventuels instantanés `pre-restore-*.db`,
et `models/` — les poids de l'IA locale, qui se trouvent dans le propre
répertoire de données de l'application plutôt que dans le répertoire de chaque moteur :

| chemin | contenu |
| --- | --- |
| `models/ollama/` | Le magasin de modèles d'Ollama (`OLLAMA_MODELS` pointe ici) |
| `models/huggingface/hub/models--<org>--<name>/` | Les poids de vLLM, un dossier par dépôt (`HF_HOME` pointe vers `models/huggingface`) |
| `cache/` | Les caches de calcul du serveur vLLM — noyaux Triton, torch Inductor, le cache JIT CUDA, les racines de cache et de configuration propres à vLLM. Construits au premier lancement, supprimables sans risque (ils sont reconstruits), et peuvent atteindre plusieurs Go |
| `vllm_start_attempts.jsonl` | Chaque démarrage et chaque arrêt du serveur vLLM, avec les propres termes de l'échec. Conservé **ici** plutôt que dans l'environnement vLLM, afin que réinstaller vLLM — la première chose que la plupart des gens essaient quand un serveur refuse de démarrer — n'efface pas la trace de la cause de l'échec |
| `vllm_failed_starts/` | Le journal complet de chacun des quelques derniers démarrages **échoués**. Le journal courant du serveur est écrasé par la tentative suivante, et une boucle de nouvelles tentatives l'écrase en moins d'une minute ; une copie est donc faite dès qu'un démarrage est constaté en échec. Quelques centaines de Ko au plus |

Si vous définissez vous-même `OLLAMA_MODELS`, `HF_HOME` ou l'une des variables de cache
(`XDG_CACHE_HOME`, `TRITON_CACHE_DIR`, `TORCHINDUCTOR_CACHE_DIR`,
`CUDA_CACHE_PATH`, `VLLM_CACHE_ROOT`, `VLLM_CONFIG_ROOT`), votre valeur l'emporte toujours —
l'application la réexporte au lieu de la remplacer. La redirection ne s'applique
qu'au **serveur** : l'installation de vLLM utilise toujours le cache de wheels habituel de pip, si bien que
réinstaller ne retélécharge pas plusieurs Go déjà présents. Les poids téléchargés **avant** le 2026-08-04 se trouvent
toujours dans le propre `~/.cache/huggingface/hub/` de Hugging Face ; Paramètres → IA les signale
et indique où les déplacer, et rien n'est déplacé ni supprimé à votre place.

### 5.2 Variables d'environnement

> **Note d'honnêteté :** ce tableau liste l'essentiel destiné à l'opérateur — ce n'est **pas** la liste de toutes les
> variables d'environnement que le code peut lire (un audit a compté ~259 références à des variables d'environnement
> dans le code). Une variable absente de ce tableau relève de la concision du manuel,
> pas d'une affirmation que la variable n'existe pas.

| Variable | Rôle |
|---|---|
| `OO_DATA_DIR` | Remplace le répertoire de données (voir plus haut). |
| `OO_HOST` / `OO_PORT` | Adresse/port d'écoute (par défaut `127.0.0.1:8000`). |
| `OO_AUTOSEED` | Amorce le catalogue mondial au premier lancement (activé par défaut ; `0` pour désactiver). |
| `OO_NO_SCHEDULER` | Mettez `1` pour ne jamais lancer automatiquement le planificateur en arrière-plan ; l'application démarre alors en ligne au lieu du mode avion. La protection au niveau des sockets du mode avion est installée dans les deux cas (seul `OO_AIRPLANE_SOCKET_GUARD=0` l'omet), si bien qu'activer le mode avion plus tard bloque toujours les connexions extérieures au niveau des sockets (les quelques exceptions résiduelles sont listées dans SECURITY.md). |
| `OO_NO_INDEX` | Mettez `1` pour ignorer l'indexation automatique des Analyses. |
| `OO_CUSTODY_ON_INGEST` | Valeur par défaut héritée pour la journalisation automatique de la possession à l'ingestion (la préférence de l'interface la remplace dès qu'elle est enregistrée). |
| `OO_KEY_PASSPHRASE` | Chiffre au repos les clés privées de possession (AES-256-GCM via scrypt). Sans elle, c'est la phrase secrète de la base de données qui les protège ; sans aucune des deux, les clés sont écrites en clair avec les droits `0600` et signalées honnêtement comme `plaintext-0600`. |
| `OO_FETCH_TIMEOUT` / `OO_FETCH_MIN_INTERVAL` | Ajustent le délai d'expiration du récupérateur éthique et son intervalle minimal par hôte. |
| `OO_LLM_MODEL` / `OO_OLLAMA_URL` (ou `OLLAMA_BASE_URL`) | Modèle local par défaut et point d'accès Ollama. |
| `OO_ALLOW_BIG_SCANS` | Mettez `1` pour lancer les analyses de fond portant sur tout le corpus sur une machine en dessous du plancher de mémoire (voir [La mémoire sur une petite machine](#55a-la-mémoire-sur-une-petite-machine--le-seul-vrai-plafond)). Le verdict indique alors que vous l'avez outrepassé. |
| `OO_CKPT_GATE_TIMEOUT_S` | Durée pendant laquelle le point de contrôle WAL entre deux passes attend le verrou d'écrivain unique avant de consigner honnêtement qu'il est ignoré et de passer à la suite (par défaut `30`). `0` rétablit l'ancienne attente illimitée (le propre point de contrôle de la protection du stockage attend toujours au plus 30 s le verrou d'écriture, sur un fil d'exécution à part, de sorte qu'une reprise forcée reste surveillée). |
| `OO_STORAGE_GUARD` | Mettez `0` pour désactiver la protection du stockage (aucun échantillonnage, aucune pause). La protection met d'elle-même la collecte en pause quand le journal d'écriture anticipée (WAL) de la base de données a dépassé une limite calculée d'après votre machine ou que le disque est presque plein, et la reprend d'elle-même ; « Reprendre quand même » dans l'avis force la reprise de la collecte alors que la limite tient toujours, et cesse d'elle-même si l'espace libre devient trop faible ou ne peut pas être lu, si une écriture échoue faute d'espace, ou si une deuxième limite est franchie. La même pause retient, tant qu'elle dure, la réindexation de fond qui termine une importation interrompue et la construction unique des index de la liste d'articles (leurs lignes dans le gestionnaire de tâches l'indiquent, et elles reprennent d'elles-mêmes ; « Reprendre quand même » force la collecte, pas celles-ci). |
| `OO_DAMAGE_GUARD` | Mettez `0` pour désactiver la pause qui suit un signalement par la base de données d'un endommagement de l'un de vos fichiers de données (le signalement lui-même est toujours consigné dans `database-damage.json` dans votre dossier de données, et l'avis indique alors que la pause est désactivée). Sans cela, un fichier que la base de données déclare endommagé ne reçoit plus d'écritures de la collecte, des tâches de maintenance ni de la voie Wikipédia (chacune seulement pour son propre fichier) jusqu'à ce que vous relanciez la collecte (pour le fichier Wikipédia : jusqu'à ce que vous désactiviez puis réactiviez la récupération Wikipédia). Une pause posée par la vérification au démarrage (voir `OO_BOOT_VERIFY`) ne prend fin que lorsque les tables désignées par la vérification se lisent de nouveau sans erreur ; toute autre pause prend fin, puis s'arrête de nouveau à la première lecture en échec si l'endommagement est toujours là. Indépendant de `OO_STORAGE_GUARD`. |
| `OO_BOOT_VERIFY` | Mettez `0` pour désactiver la vérification de vos fichiers de données exécutée au démarrage, alors que l'application est encore hors ligne, après un arrêt inattendu (et après qu'une vérification antérieure est restée inachevée ou a trouvé un endommagement) : chaque table est lue une fois avec le `PRAGMA quick_check` de SQLite, une table à la fois, sur une connexion en lecture seule, de sorte que la vérification n'écrit rien elle-même. Une table, la liste des tables ou la vérification des pages qui signale un endommagement est relue une seconde fois sur une nouvelle connexion et ne compte comme endommagée que si la seconde lecture concorde : une seconde lecture qui diffère, ou qui ne peut pas être faite, la laisse non vérifiée avec la raison, et rien n'est mis en pause ni réparé pour autant. Sur un fichier chiffré, quand une table n'a pas pu être garantie (SQLCipher lève une erreur générique pour de nombreuses pages endommagées), elle demande aussi une fois la propre vérification des pages de SQLCipher (`PRAGMA cipher_integrity_check`, environ une seconde par 230 Mo) et consigne quelles pages échouent à leur authentification (un fichier de plus de 4 Gio n'est pas soumis à cette vérification des pages, car elle lit les mauvais octets au-delà de ce point ; le compte rendu l'indique et le fichier n'est pas déclaré sain) ; un fichier dont des pages échouent est endommagé, et un fichier dont toutes les pages passent n'est toujours pas déclaré sain tant qu'une table reste sans réponse. Une page qu'elle n'a pas pu lire du tout (un disque défaillant) est comptée à part et ne constitue pas à elle seule une constatation, et quitter pendant que cette vérification tourne ne consomme pas l'un des trois essais. La collecte attend qu'elle se termine ; un fichier qu'elle trouve endommagé est mis en pause (voir `OO_DAMAGE_GUARD`), et relancer la collecte relit une fois de plus les tables qu'elle a désignées avant de lever la pause (pour le fichier Wikipédia, c'est le fait de désactiver puis réactiver la récupération Wikipédia qui le fait). Une vérification qui ne parvient pas à se terminer n'est plus tentée après trois démarrages consécutifs, et l'application le signale (cette suspension dure à travers tous les démarrages normaux jusqu'au prochain arrêt inattendu de l'application, qui est une nouvelle raison de vérifier) ; cela n'efface jamais une constatation : un fichier qu'une vérification antérieure a trouvé endommagé reste en pause jusqu'à ce que les tables qu'elle a désignées se lisent sans erreur (ou que le fichier soit remplacé). Le résultat de chaque fichier se trouve dans `database-damage.json` dans votre dossier de données. |
| `OO_BOOT_REPAIR` | Mettez `0` pour désactiver la réparation d'un fichier de bibliothèque endommagé (et, avec elle, la suppression décrite plus bas). Par défaut, quand la vérification au démarrage (voir `OO_BOOT_VERIFY`) lit une table de votre fichier de bibliothèque comme endommagée, l'application répare le fichier à ce démarrage, alors qu'elle est encore hors ligne et avant que la collecte n'écrive quoi que ce soit : elle copie chaque ligne encore lisible, table par table, dans un nouveau fichier placé à côté, reconstruit les index et l'index de recherche, vérifie le nouveau fichier avec la même lecture table par table, et seulement ensuite bascule dessus. Les lignes situées sur des pages illisibles ne sont pas dans le nouveau fichier ; l'avis indique combien d'entrées ont été copiées et combien n'ont pas pu être lues, et dans quelles tables elles se trouvaient. Les lignes dont la ligne parente n'a pas pu être lue sont conservées, jamais supprimées, et comptées par table ; là où une table attribuerait sinon le numéro d'une ligne perdue à la prochaine ligne enregistrée, la réparation ajoute UNE ligne de remplacement marquée «(lost …)» au plus grand numéro perdu (c'est une ligne visible, et l'index de recherche la trouve sous cette marque), et l'avis nomme ces tables. Tout ce que l'application enregistre attend pendant qu'elle travaille (la réparation a besoin du verrou d'écriture, activé par défaut : avec `OO_WRITE_GATE=0`, elle refuse et le dit), et si quelque chose a malgré tout été enregistré dans le fichier pendant la copie, la copie est abandonnée et refaite au démarrage suivant plutôt que substituée par-dessus cet enregistrement. Elle a besoin d'un espace libre égal à celui du fichier entier plus son journal plus la réserve que conserve la protection du disque, et d'un disque capable de donner un second nom à un fichier (un lien physique) ; elle indique lequel de ces éléments manque et ne change rien dans ce cas. Seul le fichier de bibliothèque est réparé, et seulement après que la vérification de ce démarrage a elle-même trouvé un endommagement : les fichiers Wikipédia et de droit sont mis en pause comme avant mais pas réparés, un fichier trouvé endommagé pendant que l'application tourne est vérifié au démarrage suivant et réparé à ce moment si la vérification le confirme, et une table que la vérification n'a pas pu lire ne constitue pas une constatation. **Le fichier endommagé est conservé, pas supprimé :** la réparation lui donne un second nom à côté du nouveau fichier, `<name>.damaged-<date and time>.<ending>` (avec son journal sous le même nom suivi de `-wal`), car il peut encore contenir des lignes que la copie n'a pas pu lire, utiles à un outil de récupération. **L'application supprime ce fichier, et lui seul, 30 jours après la première lecture sans erreur du nouveau fichier**, au premier démarrage à cette date ou après, jamais pendant qu'une réparation ou une vérification est en cours ni pendant que la bibliothèque est de nouveau signalée endommagée ; l'avis de réparation et le zip Diagnostics indiquent sa taille, son emplacement et la date, et après la suppression indiquent qu'il a été supprimé et quelle était sa taille. Si le disque lui-même n'a pas pu lire une page de votre fichier de bibliothèque (l'avis indique combien de pages), l'application ne supprime pas du tout ce fichier, car un disque défaillant peut expliquer pourquoi les pages n'ont pas pu être lues : il reste jusqu'à ce que vous le supprimiez vous-même, et l'avis vous invite à vérifier le disque. Avec `OO_BOOT_REPAIR=0`, la suppression est désactivée et l'avis le dit. Vous pouvez le supprimer vous-même à tout moment. Elle ne supprime que le fichier mis de côté par la réparation (il doit se trouver dans votre dossier de données, être un fichier ordinaire, porter exactement ce nom et être le même fichier que celui consigné par la réparation) et rien d'autre ; si l'une de ces conditions n'est pas remplie, elle ne supprime rien, le dit, et ne réessaie pas. Une réparation commencée et non terminée est retentée au démarrage suivant ; deux démarrages consécutifs interrompus en pleine réparation ne sont pas suivis d'un troisième essai tant que l'application n'est pas mise à jour (la trace est `database-repair-attempt.json` dans votre dossier de données). Le compte rendu de chaque réparation (la date, les comptes, le nom du fichier et, le moment venu, sa suppression) se trouve dans `database-damage.json` ; il conserve les dix derniers, et un fichier conservé dont le compte rendu est sorti de ces dix n'est jamais supprimé par l'application. |
| `OO_ARTICLE_INDEXES` | Mettez `0` pour ne pas construire les deux index de la liste d'articles. Par défaut, l'application les construit une fois, au premier démarrage après une mise à jour, alors qu'elle est encore hors ligne : un pour le filtre par langue et un pour le tri par titre, afin que les deux restent rapides à mesure que la bibliothèque grandit (ils occupent environ 190 Mo pour 1,5 million d'articles). Sur une grosse bibliothèque sur un disque lent, la construction peut prendre quelques minutes ; elle apparaît dans le gestionnaire de tâches sous « Construction des index de la liste d’articles », tout ce que l'application enregistre attend qu'elle soit terminée, et elle a besoin de deux choses qu'elle mesure d'abord et dont elle parle, sans démarrer, quand l'une ou l'autre manque : environ 400 octets d'espace libre par article sur le disque où se trouve votre fichier de données, et de la mémoire pour le tri des titres (environ 300 octets par article, gardés en mémoire et jamais écrits dans un fichier temporaire, plus la mémoire libre que l'application garde toujours pour elle ; elle indique les chiffres). Un démarrage qui s'interrompt en pleine construction la recommence ; deux démarrages consécutifs interrompus en pleine construction (l'ordinateur a manqué de mémoire ou de courant) ne sont pas suivis d'un troisième essai tant que l'application n'est pas mise à jour, car une construction qui fait elle-même tomber l'application ne doit pas devenir un démarrage qui ne se termine jamais (la trace en est `article-indexes-attempt.json` dans votre dossier de données ; le supprimer permet à l'application de réessayer, et quitter l'application normalement rend la tentative). Avec l'interrupteur désactivé, ou après un refus qui se répète, chaque démarrage consacre une fraction de seconde à comparer la version de la base de données avec ses tables. Avec l'interrupteur désactivé, la liste fonctionne comme avant, seulement plus lentement pour ces deux choix. |
| `OO_WAL_HIGH_MB` / `OO_DISK_RESERVE_MB` | Remplacent les deux limites calculées de la protection du stockage par un nombre de Mo : la taille du journal d'écriture anticipée à laquelle la collecte se met en pause, et l'espace libre en dessous duquel elle se met en pause (par défaut : calculées d'après votre machine ; les limites figurent dans l'avis que la protection affiche dans le gestionnaire de tâches tant qu'elle retient la collecte). |
| `OO_STORAGE_GUARD_TRIP_AFTER` / `OO_STORAGE_GUARD_RESUME_AFTER` | Nombre d'échantillons consécutifs (espacés d'environ cinq secondes) qui enclenchent et relâchent la protection (par défaut `2` et `2`). |
| `OO_WRITE_GATE_WARN_S` | Consigne un avertissement, avec le nom du fil d'exécution détenteur et une pile d'appels, quand une seule écriture détient le verrou plus longtemps que cette durée (par défaut `60`) ; l'avertissement est écrit au moment où la détention est remarquée, si bien que son chiffre est au moins égal au seuil et ne correspond pas à la durée de la détention. Quand une telle détention prend fin, le journal reçoit une seconde ligne, `write gate released after 61.3s by 'name'` (la durée réelle, au dixième de seconde, à la place de 61,3 ; les détentions de moins d'une seconde n'en reçoivent jamais). `OO_WRITE_GATE_WATCHDOG=0` désactive entièrement cette surveillance. |
| `OO_REINDEX_HOLD_TARGET_S` | Durée pendant laquelle un lot de réindexation peut détenir le verrou d'écrivain unique avant de valider et de laisser entrer un écrivain en attente (par défaut `10`). Cela s'applique à la réindexation de fond des articles importés, à la tâche de réindexation de tout le corpus (quand `OO_REINDEX_COMMIT_BATCH` est supérieur à 1) et à la réindexation qui termine une restauration. Elle valide plus tôt encore, à l'article suivant, dès qu'une autre écriture se met en file derrière elle, une fois que le lot a détenu le verrou au moins une seconde (une détention peut donc dépasser la cible de la durée de l'article en cours et de la validation, et un écrivain toujours en attente coûte à la réindexation environ une validation par seconde plutôt qu'une par article). La largeur de lot (`OO_IMPORT_REINDEX_COMMIT_BATCH`, `OO_REINDEX_COMMIT_BATCH`) reste le plafond, et avec une largeur de `1` chaque article est validé seul, il n'y a donc pas de lot que la cible puisse terminer plus tôt (le rapport de la restauration et la progression de la tâche de réindexation indiquent quand même la cible en vigueur). `0` correspond à l'ancienne règle : valider uniquement à la largeur de lot. Une valeur qui n'est pas un nombre de secondes supérieur ou égal à zéro conserve la valeur par défaut. |
| `OO_HEAVY_TAIL_WAIT_S` | Durée pendant laquelle le recalcul du briefing de l'Accueil et la voie de maintenance en arrière-plan s'attendent l'un l'autre plutôt que de tourner en même temps (par défaut `900`). `0` attend indéfiniment. |
| `HTTPS_PROXY` | Fait passer le trafic sortant (p. ex. OpenTimestamps) par un proxy/Tor. |

### 5.3 Extensions optionnelles

Installez-les avec `pip install -e ".[extra]"` :

- **`analysis`** — statistiques, analyses de mots-clés/entités, corrélation avec les marchés.
- **`nlp`** — modèles spaCy pour une véritable reconnaissance des entités nommées dans les Analyses.
- **`pqc`** — signature post-quantique ML-DSA pour la Chaîne de possession.
- **`timestamping`** — ancrage OpenTimestamps (Bitcoin).
- **`dev`** — outils de test/lint.

Si une extension manque, la fonction qui en dépend **se dégrade bruyamment** (une erreur claire ou
un `503`, un état honnête « non installé ») — elle ne simule jamais la fonctionnalité en silence.

### 5.4 L'API HTTP

L'application est un serveur FastAPI sur `127.0.0.1:8000` ; l'interface web est un unique
`index.html` sans dépendance servi à `/`. Le schéma lisible par machine se trouve à **`/openapi.json`**. Les pages interactives Swagger (`/docs`) et ReDoc
(`/redoc`) sont **désactivées par défaut** : elles font télécharger au navigateur des scripts, des styles et une police depuis des hôtes
tiers ; un développeur qui les veut démarre donc l'application avec `OO_API_DOCS=1`. Métriques Prometheus à `/metrics`. Il n'y a **aucune authentification**, à dessein
(boucle locale uniquement, un seul utilisateur). Tous les points d'accès sont **soumis à une limite de débit** (en gros : lectures
100/h, écritures/exportations 50/h, suppressions 20/h, importations en masse 10/h ; `429` avec
`Retry-After` en cas de dépassement).

Un inventaire condensé (voir `/openapi.json`, ou `/docs` avec `OO_API_DOCS=1`, pour le schéma faisant foi, toujours à jour, et
`docs/ARCHITECTURE.md` pour la description rédigée) :

**Cœur & recherche** — `GET /api/health` ; `GET /api/articles` (FTS + filtres) ;
`GET /api/articles/export` (csv|json) ; `GET /api/articles/{id}/view` (HTML hors ligne) ;
`GET /api/sources`.

**Ingestion** — `POST /api/sources/seed-defaults` ;
`POST /api/sources/{id}/ingest` ; `POST /api/sources/{id}/ingest-email` (IMAP) ;
`POST /api/ingest` (URL unique).

**Sources & catalogue** — CRUD complet sous `/api/sources/…` (y compris opérations par lots, groupes,
groupes par étiquette, métadonnées, découverte, import/export YAML, statistiques, recherche) ; catalogue
CSV à `/api/catalog/sources`, `/export.csv`, `/template.csv`, `POST /import`.

**Planificateur** — `GET /api/scheduler/status|config|targets` ;
`PUT /api/scheduler/config` ; `POST /api/scheduler/start|stop|run-now`.

**Base de données & sauvegarde** — `GET /api/database/stats|coverage|countries` ;
`GET /api/database/backup` (instantané `.db` brut ; sous un nom que vous avez listé dans `OO_ALLOWED_HOSTS`, une requête qui n'indique aucune page d'origine doit ajouter l'en-tête `X-OO-Download: 1`, comme le fait `curl -H "X-OO-Download: 1" …` ; taper l'adresse dans un navigateur, ou ouvrir un favori, sur un nom de ce type en HTTP simple n'envoie rien de ce qu'un navigateur ajouterait en boucle locale ou en HTTPS, et la requête y est donc refusée). Les sauvegardes sont **créées** par les moteurs
en flux : volumes chiffrés + parité à `POST /api/backup/v2/volumes/start` (+ `/restore`,
`/cancel`, `GET /volumes/status`) et la copie de dossier pour gros volumes de données à
`POST /api/backup/folder/start` (+ `/plan`, `/restore`, `/{action}`, `GET /folder/status`).
La restauration d'une ancienne archive en fichier unique est la **fusion additive** :
`POST /api/backup/v2/restore/preview`, `POST /api/backup/v2/restore/commit`,
`GET /api/backup/v2/batches`. *(Les points d'accès destructeurs `POST /api/database/restore` et
`/api/safety/restore/encrypted` ont été supprimés.)*

**Système & réseau** — `GET /api/system/vitals|network|interfaces` ;
`POST /api/system/network` (bascule du mode avion) ; `GET /api/system/doctor|lock-state` ;
`POST /api/system/unlock|create-db|encrypt-db`. **Tâches / gestionnaire de tâches** —
`GET /api/jobs` ; `POST /api/jobs/dumps/reorder` ; `POST /api/jobs/{id}/cancel`.

**Carte du monde** — `GET /api/timemap` (signaux spatio-temporels ; `?kinds`, fenêtre `?start`/`?end`
en années fractionnaires, `?hazards`, `?articles`, `?mentions`, `?days`) ; `GET /api/timemap/range`.

**Étiquettes de date des articles** — `GET/POST /api/article-dates/article/{id}` (lister / extraire) ;
`POST /api/article-dates/{tag_id}/confirm|reject` ; `POST /api/article-dates/index` ;
`GET /api/article-dates/by-date`.

**Analyses** — `GET/PUT /api/insights/filter` ; `POST /api/insights/exclude|include` ;
`GET /api/insights/status` ; `POST /api/insights/reindex` ;
`GET /api/insights/top|trending|trend|associations|context|map` ; agrégats
**Quand×Où×Qui** sur tout le corpus à `GET /api/insights/who|where`.
**Cadrage** — `GET /api/framing`.

**Recherche (omnibarre)** — `GET /api/search/omni` (fédération adossée aux index, sur les articles,
les mots-clés, les sources, les pages Wikipédia surveillées et le droit suivi).

**Liens** — `GET /api/links/shared` (quels articles membres partagent des liens sortants, avec
des notes d'indépendance) ; `GET /api/links/preview` (extraction locale d'aperçu de lien).

**Événements de l'agenda** — `GET /api/events/calendars|feeds|imported` ;
`GET /api/events/astronomy` (phases de la Lune calculées localement — nouvelle lune, premier quartier, pleine lune, dernier quartier — + équinoxes/solstices, vérifiées par rapport à
un almanach) et `GET /api/events/climate` (jeu de données El Niño fourni avec l'application). **Contexte météo** —
`POST /api/weather/context` (tranches de réanalyse Open-Meteo guidées par le corpus, avec consentement).

**Marchés & matières premières** — `/api/markets/rules` (CRUD + `/run`),
`/api/markets/overview|series|feeds`, `/api/markets/feeds/{key}/import`,
`/import-all`, `/import-url` ; `/api/commodities/{symbol}/prices` (+ `/import-csv`,
`/correlation`).

**Gouvernements** — indicateurs de la Banque mondiale par pays + la carte choroplèthe, en lecture seule
à l'exception de l'unique récupération avec consentement : `GET /api/governments/indicators|map|country/{iso}` ;
`POST /api/governments/load-standard` (+ `/load-standard/status`, une tâche de fond).
**Droit mondial** — lois/journaux officiels/titres de propriété intellectuelle suivis, un miroir de recherche (jamais un conseil
juridique) : `GET /api/law/status|documents|documents/{id}|documents/{id}/view|changes` ;
`POST /api/law/documents` (ajoute un document par URL — récupéré immédiatement) ;
`DELETE /api/law/documents/{id}` (arrête le suivi ; l'historique est conservé) ; `POST /api/law/track`
(récupère maintenant chaque document surveillé) et `/api/law/seed` (réamorce le catalogue mondial).
Un document suivi devient un article du corpus à part entière, consultable par la recherche (Quand×Où×Qui,
mots-clés), aux côtés de l'actualité collectée, avec son historique de modifications comme couche liée.

**Wikipédia** — `GET /api/wiki/status|pages|changes` ; `POST /api/wiki/pages`,
`/track-now`, `/pages/{id}/track` ; `GET /api/wiki/revisions/{id}` ;
`GET /api/wiki/languages` (une liste **plate, langues de l'interface en premier**, chaque option commençant par le
nom natif ; `region` n'est conservé que comme métadonnée descriptive — pas de `groups` par continent ;
`?scope=dumps` ajoute des estimations de taille `~GB` en ligne) ; dumps sous `/api/wiki/dumps…`.

**Chaîne de possession** — `POST /api/custody/log` ; `GET /api/custody/{item}` (+
`/verify`) ; `POST /api/custody/verify` ; `GET /api/custody/export` ;
`GET /api/custody/providers` ; `POST /api/custody/anchor` ;
`GET/PUT /api/custody/settings` ; `POST /api/custody/reconcile` (une entrée INGEST qui
n'a pas pu être écrite au moment où son article a été stocké est mise en file et écrite plus tard, à la fin
de la passe de collecte suivante tant que la journalisation automatique est activée, marquée comme tardive dans ses propres métadonnées signées --
l'onglet Chaîne de possession les compte, et son bouton
« Rechercher les entrées d'ingestion manquantes » compte les lacunes plus anciennes sans rien enregistrer
tant que vous n'appuyez pas sur « Les enregistrer, marquées tardives »). **Preuves** — `POST /api/reports/evidence`
(+ `/verify`).

**LLM (Ollama local)** — `GET /api/llm/health|models` ; `POST /api/llm/generate` ;
`POST /api/llm/articles/{id}/summarize|translate`.

**Autres** — `/api/analysis/*` (tests t, corrélation, ANOVA, …) ;
`/api/keywords/*` (utilitaires d'extraction) ; `/api/monitoring/health|anomalies` ;
`POST /api/verify/image-metadata` (EXIF/GPS).

### 5.5 Utilisation via Tor

L'application fonctionne via Tor (mode de récupération Protégé → un proxy Tor que vous faites tourner), avec une
portée honnêtement plus réduite — mesurée, pas devinée (journal réel du 2026-06-12 : 32 des 50
sources par défaut importées via Tor en une passe) :

- **Les refus par connexion sont normaux, pas fatals.** Certains hôtes refusent certains
  nœuds de sortie Tor : lors de la même exécution, 21/28 séries FRED ont été importées tandis que d'autres échouaient.
  C'est pourquoi les échecs de flux portent un **verdict tenant compte du transport** — *refusé*
  (« connexion refusée/réinitialisée — via Tor, c'est souvent le refus d'un seul nœud de sortie ;
  une nouvelle tentative tombe souvent sur un autre circuit ») n'est pas *interdit par robots*
  (la politique déclarée de l'hôte, que nous respectons et ne réessayons ni ne contournons jamais), n'est pas une *série morte*
  (HTTP 404 — l'entrée du catalogue doit être remplacée ; réessayer n'y changera rien), n'est pas
  *injoignable*. Les échecs transitoires sont réessayés une fois automatiquement ; le bouton **Réessayer les flux en échec**
  relance exactement ceux qui peuvent honnêtement être réessayés.
- **Le blocage de Tor par un hôte est le choix de cet hôte.** Nous le signalons ; nous ne contournons jamais
  robots, blocages ou CAPTCHA. Préférez les points d'accès officiels tolérants envers Tor quand
  ils existent.
- **Les téléchargements de modèles ne fonctionnent pas via Tor.** Ollama télécharge ses modèles par l'internet
  ordinaire, via son propre processus (installation/téléchargement depuis **Paramètres → IA**) ; un accès
  fonctionnel à l'internet ordinaire (clearnet) est une condition préalable déclarée pour télécharger un modèle. Une fois téléchargé, l'inférence
  passe par la boucle locale et n'est pas affectée. *(Un kit LLM hors ligne empaqueté est prévu, pas encore livré.)*
- **Si l'installation de vLLM s'interrompt en cours de route**, c'est presque toujours un téléchargement qui expire
  sur l'une des très grosses wheels — torch seule pèse environ 500 Mo. Le message la
  nomme, et les wheels déjà téléchargées sont mises en cache ; relancer l'installation reprend donc
  au lieu de tout recommencer. Sur une connexion assez lente pour échouer à répétition, augmentez
  `UV_HTTP_TIMEOUT` (en secondes) avant de lancer l'application.
- **Si le serveur vLLM démarre et meurt à répétition**, la cause est consignée, que vous ayez
  regardé ou non : chaque démarrage et chaque arrêt sont inscrits dans
  `vllm_start_attempts.jsonl` avec les propres termes de l'échec, et le journal complet de
  chacun des quelques derniers démarrages échoués est conservé dans `vllm_failed_starts/` — tous deux dans le
  répertoire de données, si bien que réinstaller vLLM ne les efface pas. Les deux font partie de l'export
  **Diagnostics → tous les diagnostics** (all diagnostics) ; la réponse se trouve donc dans le lot plutôt que
  dans quelque chose qu'il faudrait saisir en direct.
- **L'anonymat reste votre affaire** : le mode Protégé ne peut pas garantir
  l'anonymat — c'est vous qui faites tourner le proxy et lui faites confiance ; le rôle de l'application est de faire passer ses
  récupérations web par ce proxy avec un User-Agent générique, sauf pour ses requêtes d'API et de dumps
  vers les serveurs de Wikimedia, qui nomment toujours l'outil (la politique d'API de Wikimedia
  le demande). La récupération de la boîte aux lettres des newsletters, l'ancrage OpenTimestamps et
  les téléchargements de l'IA locale se connectent directement.

---

### 5.5a La mémoire sur une petite machine — le seul vrai plafond

L'application se réduit déjà d'elle-même sur une petite machine : en dessous de **4 Go de RAM**, ou avec
moins de **1 Go libre**, elle utilise un cache de base de données plus petit et moins de connexions
en pool, plafonne le nombre de sources qu'elle récupère simultanément, et **met en pause les
analyses de fond portant sur tout le corpus** (qualification des sources). Elle vous le dit, chiffres à l'appui,
à côté de l'état de la collecte dans Paramètres → Avancé → Collecte.

**Disons clairement ce que cela coûte :** sur une machine avec un gros corpus et peu de mémoire
libre, cela peut signifier que la qualification des sources n'y tourne jamais. C'est le coût du
réglage, pas une défaillance. Pour les lancer quand même, démarrez l'application avec
`OO_ALLOW_BIG_SCANS=1` — le verdict indique alors que vous l'avez outrepassé, et il
continue d'indiquer que la machine est petite, car l'outrepassement change ce que l'application
*fait*, jamais ce qu'elle a *mesuré*.

#### Une vue lourde s'arrête avant de pouvoir faire tomber l'application

Les lectures analytiques lourdes (la plupart des vues des Analyses, l'Observatoire, les sources les plus
citées, le lot de diagnostics) tournent déjà avec une limite de temps. Elles surveillent aussi
la mémoire disponible pendant que la base de données leur transmet des lignes. Si celle-ci tombe au
plancher de la protection mémoire (**256 Mo** par défaut, `OO_MEM_GUARD_AVAIL_MB`), la lecture
est arrêtée et la vue en donne la raison, chiffres à l'appui : *« lecture arrêtée au bout de
12 s : la machine était presque à court de mémoire (180 Mo disponibles, au plancher de 256 Mo
utilisé par la protection mémoire ou en dessous) ... »*. Une lecture demandée alors que la mémoire est
déjà aussi basse ne démarre pas, et indique *« cette lecture n'a pas démarré »*
à la place. Rouvrez la vue une fois la mémoire revenue ; rien n'a été perdu,
car une lecture ne modifie rien.

**Ce qu'elle ne fait pas :** c'est un arrêt, pas un plafond. Elle voit ce qui grossit pendant que des lignes
sont lues, c'est-à-dire là où grossit une vue qui charge une table entière, et
rien d'autre. `OO_READ_MEMORY_STOP=0` la désactive sans toucher à la protection mémoire.

#### Quand la mémoire reste épuisée, l'application s'arrête d'elle-même et le dit

La protection mémoire met en pause la nouvelle collecte quand la mémoire manque. Une pause ne
rend pas ce que l'application détient déjà ; sur une petite machine, la mémoire peut donc rester au
plancher pendant de nombreuses minutes, puis le système d'exploitation tue l'application sans
dire pourquoi. Désormais, l'application s'arrête plutôt d'elle-même. Elle ne le fait que lorsque **toutes**
ces conditions sont réunies : la protection est enclenchée depuis l'intégralité des **5 dernières minutes**
(`OO_MEM_STOP_WINDOW_S`), au moins neuf de ses relevés sur dix étaient à **64 Mo** disponibles ou
en dessous (`OO_MEM_STOP_AVAIL_MB`), aucun n'était au-dessus de 128 Mo, aucun intervalle entre
relevés n'a dépassé un dixième de la fenêtre (30 s), et cette application détient au moins un tiers de
la mémoire de la machine (si c'est autre chose qui la détient, s'arrêter ne libérerait rien,
et l'application ne s'arrête pas). Un rétablissement, même bref, ou un appui sur démarrer ou
reprendre vide la fenêtre.

Avant de s'arrêter, elle conserve ce qu'elle sait : un instantané de ce que faisait chaque fil
d'exécution, une ligne dans le registre des sessions, et `memory_stop.json` à côté de vos données
(des chiffres et des noms d'étapes, 8 Ko au plus). Puis elle se termine par le même chemin que
le bouton d'alimentation. Vos données enregistrées ne sont pas touchées ; elle attend d'abord jusqu'à une minute
qu'une importation en cours, une tâche de fond qui détient le corpus ou une écriture en base
en cours se termine (une restauration ou un déplacement du disque de données est consigné comme en cours mais
n'est pas attendu en tant que tel), indique dans le compte rendu si l'une d'elles l'était encore, et ce qui n'a pas pu
se terminer dans ce délai n'est pas terminé.
Pendant ce temps, le gestionnaire
de tâches affiche *« L'application s'arrête d'elle-même parce que la mémoire est restée épuisée »*.
Au démarrage suivant, la ligne **Sessions** de l'onglet Système indique *« Arrêt volontaire —
la mémoire est restée épuisée »* (survolez pour la mise en garde), un message unique dit la
même chose, et le zip Diagnostics contient le compte rendu. **Ce qui s'arrête, c'est ce qui
tournait ; c'est à vous de le relancer.** `OO_MEM_STOP=0` désactive l'arrêt et conserve la
pause.

#### Pourquoi l'application ne peut pas simplement plafonner sa propre mémoire

Il n'existe aucun moyen honnête pour un programme de s'imposer à lui-même un plafond de mémoire :

- **`RLIMIT_RSS` est ignoré par Linux.** Il existe dans l'API et ne fait rien.
- **`RLIMIT_AS` plafonne l'*espace d'adressage*, pas la mémoire utilisée.** Des bibliothèques que cette application
  utilise (DuckDB, numpy) réservent bien plus d'espace d'adressage virtuel qu'elles n'en
  touchent jamais, si bien qu'un plafond d'espace d'adressage déclenche `MemoryError` dans du code sans rapport bien
  avant que le processus soit réellement gros. L'application ne fixe délibérément ni l'un ni l'autre, et un
  test fait échouer la compilation si l'un d'eux est un jour ajouté.

#### Le plafond qui fonctionne : la faire tourner dans un cgroup

Sous Linux avec systemd, démarrez l'application avec une limite de mémoire stricte :

```bash
systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0 \
  ~/open-omniscience/scripts/launch.sh
```

**Ce que cela apporte, honnêtement :** cela transforme un *gel du bureau* en un *redémarrage propre de
l'application*. Sans limite, une machine à court de mémoire utilise le swap jusqu'à devenir
inutilisable pour tout — le navigateur, le terminal, le bureau — et vous pouvez
être obligé de l'éteindre et la rallumer. Avec une limite, le noyau tue **cette application** à la place, et
uniquement cette application.

**Ce que cela coûte :** l'application est tuée en plein travail, sans possibilité de faire le ménage.

**Pourquoi votre corpus est malgré tout en sécurité :** la base de données tourne en mode WAL avec
`synchronous=NORMAL`, si bien qu'un arrêt brutal ne peut perdre que du travail qui n'a jamais été validé.
Tout ce qui a été validé est sur le disque, et le journal d'écriture anticipée est rejoué au prochain
déverrouillage. **Rien de ce que vous aviez déjà collecté n'est perdu.**

Une **sauvegarde** interrompue de cette façon est une autre affaire : elle reste incomplète.
On ne s'y fie pas pour autant en silence — chaque volume porte une somme de contrôle dans le
manifeste, et l'étape de vérification propre à la sauvegarde les contrôle toutes et nomme celles
qui manquent ou ne correspondent pas. Lancez une vérification (ou refaites simplement la sauvegarde)
avant de vous fier à une sauvegarde qui a été interrompue.

Choisissez `MemoryMax` à environ **60–75 % de la RAM totale**, en laissant de la place pour le
bureau et le navigateur. `MemorySwapMax=0` est la moitié qui empêche l'emballement du swap :
sans elle, l'application peut encore faire ramer la machine à force de swap avant que la limite soit
atteinte.

Si vous n'êtes pas sous systemd, la même chose est disponible via Docker/Podman
(`--memory=3g --memory-swap=3g`) ou un simple `memory.max` de cgroup v2.

#### Après un plantage : ce que le démarrage suivant peut vous dire

Quand l'application est tuée ou plante, la fenêtre du lanceur reste désormais ouverte et indique
comment elle s'est terminée : `SIGKILL` est la marque habituelle d'un tueur de processus en cas de manque de mémoire. Un arrêt
ordinaire (le propre bouton Arrêter de l'application, la fermeture de la fenêtre, la déconnexion) ferme la
fenêtre comme avant.

Le démarrage suivant indique alors comment la session précédente s'est terminée, sous **Paramètres →
Avancé → Diagnostics → Analyse de session** et dans `session-forensics.json`
à l'intérieur de l'archive Diagnostics, à partir de ceux de ces témoins qui ont répondu :

- la trace, tenue par le lanceur, du code de sortie (`diagnostics/launcher_exits.jsonl`) ;
- le journal du noyau, qui nomme les arrêts pour manque de mémoire décidés par le noyau lui-même ;
- les lignes de journal des tueurs de processus en espace utilisateur (systemd-oomd, earlyoom,
  nohang) et de systemd-coredump qui nomment l'application. Celles-ci n'apparaissent jamais dans le
  journal du noyau, et systemd-oomd nomme le cgroup de l'application plutôt que son processus ;
- une trace de plantage de chaque fil d'exécution quand du code natif s'interrompt brutalement
  (`diagnostics/crash_trace.log`).

Les lectures de journaux sont locales et en lecture seule, et ne conservent que les lignes concernant cette application.
`OO_NO_KERNEL_LOG=1` les désactive ; `OO_CRASH_TRACE=0` désactive la trace.
Les tueurs de processus mémoire écrivent dans le journal système, que seuls les membres de `adm` ou
`systemd-journal` (`wheel` sous Fedora) peuvent lire ; quand ce n'est pas votre cas, le rapport
le dit au lieu de déclarer le journal vide. Sans aucun témoin, le rapport
indique que la fin est inconnue, jamais qu'elle a été propre.

Le même rapport indique de quoi était composée la mémoire au pic de la session. Quand
ce pic est survenu alors que la mémoire était déjà trop basse pour lire le tas C sans risque, ce qui est
généralement le cas juste avant un plantage par manque de mémoire, il montre aussi le pic antérieur le plus récent
qui a pu le lire, avec la taille et l'heure propres à ce pic. Il indique aussi
ce que faisait chaque fil d'exécution (son nom, le code de l'application qu'il exécutait et le temps CPU
qu'il a utilisé) à deux sortes de moments : quand la mémoire disponible est passée sous 15 % de la RAM
(1 Go au plus), d'abord au franchissement puis à chaque nouveau minimum, et quand l'application
a créé un million d'objets Python ou plus en cinq secondes, au plus une fois
toutes les cinq minutes. Les huit instantanés les plus récents sont conservés dans
`session_pressure.json` dans le dossier de données, et ils restent sur cet ordinateur comme
le reste des diagnostics.

## 5.6 Limites connues et transparence

L'honnêteté par construction consiste à dire ce que l'outil *ne peut pas* vous apprendre, pas seulement
ce qu'il peut. Voici les limites permanentes des méthodes (« passe de transparence »
de l'audit-07). Aucune n'est un bogue ; chacune conditionne la lecture d'un résultat.

- **Les comptages de mots-clés et de tendances sont lexicaux, pas sémantiques.** Ils mesurent la fréquence
  d'apparition des mots, pas ce qui était voulu dire. La négation (« pas une crise »), la citation,
  le sarcasme et l'ironie sont comptés au pied de la lettre. Le volume mesure la couverture, jamais
  l'importance ni la vérité.
- **Le sentiment et le ton reposent sur VADER, une méthode fondée sur un lexique anglais.** Les scores des articles
  non anglophones ne sont pas fiables ; les vues Sentiment et Cadrage le signalent et
  affichent la part notée en anglais. Le ton est un signal mesurable, jamais un verdict
  établissant qu'un média est partial.
- **Les résumés et traductions par LLM sont des productions du modèle.** Un modèle local peut être
  fluide et se tromper. Chaque cellule générée porte la mention « à vérifier par rapport à l'article
  enregistré » ; considérez ce qu'il produit comme une piste, et vérifiez-le par rapport au texte d'origine
  que vous avez collecté.
- **Un article long est découpé, pas tronqué.** La fenêtre de contexte d'un modèle est limitée. Lorsque
  vous demandez le résumé ou la traduction d'un article qui n'y tient pas, l'application
  le découpe aux limites de paragraphes et traite chaque partie — une traduction est
  la réunion des parties, et un résumé est le résumé de chaque partie, puis le résumé de
  l'ensemble. Dans les deux cas, le résultat l'indique (« traduit en N parties », « résumé
  hiérarchique sur N parties »), car un résumé en deux étapes n'est pas la même production
  qu'un résumé en une passe, et vous devez savoir lequel vous lisez. Il ne s'arrête jamais discrètement
  en cours de route : une traduction tronquée ressemble exactement à une traduction complète.
  Les passes d'arrière-plan (l'extraction qui/où/quand) TRONQUENT bien les articles longs, et
  consignent qu'elles l'ont fait — « N premiers caractères analysés sur M » — afin qu'une extraction
  maigre ne soit jamais prise pour un article maigre.
- **L'IA d'arrière-plan n'a qu'une seule file, et votre travail passe en premier.** Les passes que vous activez
  s'exécutent une par une sur l'unique moteur local au lieu de se le disputer.
  Tout ce que vous demandez vous-même — une traduction en masse, l'exécution manuelle d'une passe — suspend
  cette file le temps nécessaire, puis elle reprend d'elle-même ; rien ne perd
  sa place. Sur une machine où l'inférence locale n'est pas réaliste, la file est désactivée par
  défaut, avec la raison indiquée, et vous pouvez quand même l'activer.
- **L'application ne traite que du texte.** Elle analyse le texte des articles. Pour les images, elle se limite
  à une transparence sur les métadonnées EXIF (aucune affirmation de criminalistique ni de détection de deepfake) ; il n'y a aucune analyse audio ni
  vidéo. Une affirmation qui n'existe que dans une vidéo ou une image échappe à ce que l'outil
  peut voir.
- **Le japonais et le thaï nécessitent l'extra facultatif `[segmentation]`.** L'extraction des mots-clés
  repose sur un découpage aux espaces, sauf si un segmenteur de mots est installé. Le chinois est
  segmenté sur toutes les installations (jieba, une dépendance de base depuis la 0.4) ; l'analyse des mots-clés
  en japonais et en thaï est en pratique inopérante sans l'extra (janome, pythainlp), même
  si l'interface est disponible dans ces langues, et la recherche en japonais n'est découpée en mots
  qu'avec le sudachipy de l'extra. L'ensemble **géré**
  (langues segmentées par espaces, avec une liste de mots vides) est défini dans
  [`src/analytics/managed.py`](../src/analytics/managed.py) ; la *profondeur d'analyse* varie
  selon la langue, et les écritures non segmentées constituent aujourd'hui la plus grande lacune.
- **Biais de survie des hôtes permissifs.** Comme robots.txt est appliqué en mode fermé par défaut, le
  corpus surreprésente les sites qui *autorisent* l'exploration et sous-représente structurellement
  le journalisme payant ou restrictif envers les robots. Ce biais ne peut pas être
  « corrigé » de façon éthique — il est atténué en privilégiant les API et archives officielles, et il est
  signalé ici pour que vous lisiez la couverture en conséquence.
- **Votre historique commence le jour où vous avez commencé à collecter.** Les tendances et les signaux « en hausse »
  sont bornés par votre fenêtre de collecte ; l'outil n'a aucun historique antérieur à vos
  débuts. Les dumps Wikipédia et les archives (à venir) prolongent le passé ; sinon, lisez
  les résultats d'un jeune corpus avec les mises en garde où n est affiché.
- **Wikipédia porte ses propres biais systémiques.** Wikipédia surveillé ou ingéré
  importe les biais éditoriaux et de couverture bien documentés de chaque édition.
  Les sources par édition (`xx.wikipedia.org`) permettent de le filtrer, et on peut le
  recouper comme n'importe quelle autre source — ce n'est jamais un oracle.
- **Le biais de sélection du catalogue est mesuré, pas caché.** Le catalogue de sources est un ensemble
  constitué à la main, en cours de rééquilibrage pour sortir du centrage sur les États-Unis ; la vue **Couverture mondiale**
  montre quels pays sont représentés et lesquels ne le sont pas, pour que vous voyiez la forme de
  ce que vous collectez (et de ce que vous ne collectez pas).

---

## 6. Dépannage

- **La page ne se charge pas.** Vérifiez que le processus tourne et écoute sur
  `127.0.0.1:8000` (ou vos `OO_HOST`/`OO_PORT`). La pastille d'état de l'en-tête passe à
  `offline` si l'API n'est pas joignable.
- **La recherche est vide.** Vous n'avez encore rien collecté — **passez en ligne** avec le bouton
  avion (une seule fenêtre de consentement) et la collecte démarre automatiquement ; le chemin manuel est
  **Paramètres → Avancé → Collecte → Récupérer le flux**.
- **Une ingestion n'a rien enregistré.** C'est souvent normal et éthique : la page peut être
  bloquée par `robots.txt` (fermé par défaut), limitée en débit, être un doublon ou n'avoir aucun
  corps extractible. Le décompte du résultat vous dit lequel.
- **Les commandes d'Analyses ou de Marchés manquent ou renvoient des erreurs.** L'extra `[analysis]`
  n'est pas installé — relancez `install.sh` (l'extra d'analyse s'installe par défaut).
- **La pastille LLM indique hors ligne.** Ollama ne tourne pas ou n'est pas joignable ; démarrez-le ou définissez
  `OLLAMA_BASE_URL`. Résumer et traduire renvoient une erreur `503` explicite lorsqu'il est indisponible.
- **La possession affiche « demandé, bibliothèque non installée ».** Installez l'extra `pqc` et/ou
  `timestamping` ; l'état effectif changera dès que la bibliothèque sera présente.
- **La restauration a refusé mon fichier / l'aperçu ne permet pas d'Appliquer.** C'est voulu — il doit s'agir d'une
  véritable sauvegarde Open Omniscience, et **Appliquer (Apply)** reste désactivé si la
  vérification préalable échoue. Votre corpus actuel n'est touché dans aucun cas ; la restauration ne fait jamais
  qu'*ajouter*, elle ne remplace jamais.
- **Le dump Wikipédia est énorme.** `enwiki` pèse des dizaines de Go. Utilisez d'abord **Estimer la taille (Estimate size)** ;
  la plupart des éditions sont bien plus petites, et vous n'avez pas besoin d'un dump pour le suivi des modifications.

---

## 7. Glossaire

- **Corpus** — votre base de données SQLite locale des articles rassemblés.
- **Provenance** — l'origine enregistrée de chaque élément (source, URL, URL canonique,
  empreinte du contenu, heure de récupération), utilisée pour le dédoublonnage et la confiance.
- **FTS5** — la recherche plein texte de SQLite, qui permet les requêtes booléennes.
- **Récupération éthique** — le chemin de récupération unique, respectueux de robots.txt et limité en débit.
- **Chaîne de possession** — journal signé, en ajout seul et chaîné par empreintes, qui prouve l'intégrité,
  la provenance et la date d'un élément.
- **Lot de preuves** — une exportation signée, à racine de Merkle et vérifiable hors ligne,
  d'articles sélectionnés.
- **OpenTimestamps** — un moyen d'ancrer une empreinte dans Bitcoin comme preuve indépendante qu'un élément
  « existait au plus tard » à un bloc donné.
- **ML-DSA** — schéma de signature post-quantique FIPS-204 (utilisé en mode *hybride*
  aux côtés d'Ed25519).
- **ORES** — le service d'apprentissage automatique de Wikimedia qui note les modifications pour leur nocivité / leur bonne foi.
- **PMI** — information mutuelle ponctuelle ; classe la force avec laquelle deux termes apparaissent ensemble
  au-delà du hasard (la « carte mentale » d'Analyses).
- **VADER** — un outil de notation du ton/sentiment fondé sur un lexique (la vue « cadrage » d'Analyses).

---

*Voir aussi :* [QUICKSTART](QUICKSTART.md) · [CHAIN_OF_CUSTODY](USER_MANUAL.md) ·
[INSIGHTS](USER_MANUAL.md) · [MARKETS](USER_MANUAL.md) · [WIKIPEDIA](USER_MANUAL.md) ·
[DATABASE](ARCHITECTURE.md) · [API_DOCUMENTATION](ARCHITECTURE.md) ·
[SECURITY](SECURITY.md) · [PRODUCT_SYNTHESIS](DESIGN.md) ·
[OPEN_QUESTIONS](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).

*© 2026 Ideotion — conçu pour le journalisme d'investigation, honnêtement. GPLv3.*

---

# Fonctionnalités en détail

La référence détaillée de chaque outil, regroupant les anciens guides par fonctionnalité. La visite guidée des parties 1 à 6 ci-dessus reste le moyen le plus rapide de s'orienter ; cette partie donne le détail.

**Dans cette partie :**
- [Le briefing de l'Accueil — le renseignement sous forme de « cartes » honnêtes](#le-briefing-de-laccueil--le-renseignement-sous-forme-de--cartes--honnêtes)
- [Intégrité des sources et anti-amplification](#intégrité-des-sources-et-anti-amplification)
- [Annotations de sources partagées — signées, portables, fédérées par la confiance](#annotations-de-sources-partagées--signées-portables-fédérées-par-la-confiance)
- [Analyses — statistiques sur les mots-clés et les entités](#analyses--statistiques-sur-les-mots-clés-et-les-entités)
- [Suivi des modifications de Wikipédia](#suivi-des-modifications-de-wikipédia)
- [Droit mondial — suivi des modifications des lois, journaux officiels et PI](#droit-mondial--suivi-des-modifications-des-lois-journaux-officiels-et-pi)
- [Marchés : renseignement financier, boursier et sur les matières premières et terres rares](#marchés--renseignement-financier-boursier-et-sur-les-matières-premières-et-terres-rares)
- [Chaîne de possession](#chaîne-de-possession)


---

## Le briefing de l'Accueil — le renseignement sous forme de « cartes » honnêtes

> **État :** `0.06` Phase A (la colonne vertébrale de l'interface) — livrée et testée. Le plan par phases
> se trouve dans [`ROADMAP.md` → « 0.06 — The Intelligence Layer »](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md) ; le
> *quoi et pourquoi* dans [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).

L'onglet **Accueil** n'est plus seulement un aperçu de statistiques. C'est un **fil de tri** :
l'application rassemble et mesure en arrière-plan, puis fait remonter des *sujets candidats* sous forme de
**cartes — affichées à l'écran comme des « Pistes »** (ce chapitre dit « carte » pour le mécanisme
interne ; le libellé de l'interface est « Piste »). L'application rassemble ; **c'est vous qui jugez**. Chaque carte
est **un signal mesurable + les liens vers les éléments + une mise en garde**, classée dans une catégorie
éditoriale, et présentée comme une **carte retournable à deux faces** (recto = la piste ; verso = mise en garde +
méthode + éléments + « Ouvrir le corpus »).

Une carte **fait remonter un signal ; elle ne rend jamais de verdict.** Il n'y a pas de « partial », pas de
« propagande », pas de « vrai/faux », et — par conception et *imposé dans le code* — **aucun score de confiance
composite** (voir « Garde-fous d'honnêteté » ci-dessous).

---

### Ce que vous voyez

Le briefing regroupe les cartes en **catégories** (ordre d'affichage) :

| Catégorie | Signification | Usage éditorial |
|---|---|---|
| **En hausse** | quelque chose bouge / est nouveau | pistes potentielles |
| **Sur-raconté** | les sources s'accordent trop vite / trop uniformément | démonter le chœur |
| **Sous-raconté** | quelque chose a bougé, mais peu de monde ou personne n'en a parlé | révéler le manque |
| **À enquêter** | les sources ou les données divergent | creuser |
| **Vérifier le cadrage** | le même événement présenté de façons opposées | vérifier l'affirmation |
| **À surveiller** | un changement qui mérite l'attention (p. ex. une fiche remaniée) | suivre |
| **Contexte** | arrière-plan / auto-audit / faits permanents | mettre en contexte |
| **Intégrité des données** | signaux d'hygiène sur le corpus lui-même | réparer la chaîne de traitement |

La triade qui les sous-tend est le moteur : **convergence → sur-raconté**, **divergence →
enquêter/démonter**, **absence → sous-raconté**.

Chaque Piste (le nom affiché à l'écran pour une carte du briefing) montre sur son **recto** son **titre**, un
**résumé** d'une ligne et le **signal mesuré** (p. ex. `growth_ratio = 4.2`, `n=6`).
**Cliquez dessus (ou appuyez sur Entrée) pour la retourner :** le **verso** porte la
**mise en garde**, la **méthode** (exactement comment le chiffre a été calculé et ce qu'il ne signifie *pas*),
la raison de son déclenchement, les **liens vers les éléments** de votre corpus et un bouton **« Ouvrir le corpus
↗ »**. La mise en garde est présente dans le DOM par défaut, sur la face verso de même rang, juste à côté de
l'action — jamais derrière un interrupteur d'interface épurée. C'est tout l'enjeu : **la transparence est
l'interface.**

> **Vue égalitaire.** Dans cette version, chaque source est comptée une fois et **aucune source n'est
> désamplifiée**. La couche d'intégrité des sources / d'anti-amplification (regrouper les
> déferlements coordonnés en acteurs uniques, pondérer par la nouveauté) est la phase suivante et elle est
> **guidée par l'utilisateur** — l'application *propose*, vous *disposez*. D'ici là, le
> briefing est, honnêtement, la vue brute à traitement égal.

---

### La boucle carte → brouillon → infolettre

La boucle qui donne tout son intérêt à l'outil est visible dès le premier jour :

1. Sur n'importe quelle carte, cliquez sur **+ Ajouter au brouillon**.
2. Ouvrez le panneau **Brouillon d’infolettre** ; ajoutez votre propre note à chaque carte épinglée.
3. **Exporter en Markdown** (ou **Copier**). Chaque affirmation part **avec ses liens vers les sources,
   sa méthode et sa mise en garde** — un journalisme reproductible par conception.

Pour une copie *signée et inviolable* des articles sous-jacents, exportez un **lot de
preuves** depuis **Preuves & possession** — les justificatifs peuvent accompagner votre numéro.

---

### Comment les cartes sont produites (Briefing v0)

Chaque carte est créée par un **producteur** : une fonction `corpus → [Card]`. Les producteurs combinent
des analyses qui *renvoient déjà de vrais chiffres* — rien n'est inventé. Un producteur à qui
il manque ses entrées ou une dépendance facultative `[analysis]` **ne renvoie rien et consigne
pourquoi** (dégradation signalée) ; il ne fabrique jamais de carte.

| Carte | Catégorie | Repose sur | État |
|---|---|---|---|
| **« X » est en hausse** | en hausse | `insights.trending` (rapport période récente / période précédente) | disponible |
| **Cadrages divergents** | vérifier le cadrage | ton VADER par source d'un terme en hausse | disponible¹ |
| **Fiche remaniée** | à surveiller | détection des modifications Wikipédia importantes/signalées | disponible |
| **Prix ↔ récit** | contexte | corrélation scipy honnête (coef + p + n) | disponible¹ |
| **Données périmées** | intégrité des données | `last_run_at` / `last_status` de la règle d'extraction des marchés | disponible |
| **Auto-audit du régime d'information (Diet self-audit)** | contexte | `signals.concentration` (Gini + part des 3 premières sur vos sources) | disponible |
| **Chambre d'écho** | sur-raconté | graphe d'acteurs `signals.coordination` (quasi-doublon + synchronisation + hôte) | nouveau |
| **Signal isolé** | sous-raconté | groupe de quasi-doublons à source unique qui n'a pas eu d'écho | nouveau |
| **Capacité invraisemblable (Capacity implausible)** | à enquêter | articles/jour par rapport à la médiane du corpus | nouveau |
| **Profil émotionnel** | contexte | lexique des émotions appliqué aux fenêtres de contexte d'un mot-clé | nouveau² |
| **Pouls PI / juridique** | contexte | termes de PI/juridiques en hausse dans le corpus d'actualités | embryonnaire |
| **Changement de propriétaire** | à enquêter | vocabulaire des transactions (racheté/fusion/cédé) dans l'actualité récente | embryonnaire |
| **Filiation d'un récit** | contexte | `signals.lineage` — un groupe de quasi-doublons classé par date de publication + attribution à une agence | nouveau |
| **Conseil de couverture** | contexte | `signals.concentration` sur le pays/la langue de vos sources (déséquilibre, pas plafond) | nouveau |
| **Vérification météo disponible (Weather check available)** | à enquêter | `analytics.corroboration` — termes d'événements climatiques × lieux déduits × dates des articles | nouveau |

¹ Nécessite l'extra `[analysis]` (VADER / scipy). Sans lui, ces cartes n'apparaissent tout simplement
pas — le reste du briefing fonctionne toujours.
² Utilise un lexique des émotions ; un petit **échantillon** anglais est fourni, faites pointer
`OO_EMOTION_LEXICON` vers un lexique JSON plus complet pour un usage sérieux (anglais uniquement).

Les cartes **chambre d'écho**, **signal isolé** et **capacité invraisemblable** proviennent de la
couche d'intégrité des sources — voir [`USER_MANUAL.md`](USER_MANUAL.md). Les cartes chambre d'écho portent
une action *Regrouper en un seul acteur* (anti-amplification guidée par l'utilisateur — l'application propose → vous disposez).

L'**auto-audit du régime d'information** utilise la première primitive pure du socle partagé
[`src/signals/`](../src/signals/) : la **concentration** (coefficient de Gini + part des
N premiers). Ce sont les *mêmes calculs* que ceux prévus pour la concentration de la propriété des médias
(FUTURE_DEVELOPMENTS §1) et la notoriété des personnes (§4) — un seul moteur, de nombreux domaines.

La **filiation d'un récit** remonte un sujet repris jusqu'à sa **source primaire** : pour un groupe de
quasi-doublons répartis sur de nombreux médias, elle classe les articles par date de publication et détecte les
**attributions explicites à une agence** (« selon Reuters », « (AFP) ») afin de mettre en avant le reportage original
plutôt que les reprises dérivées. La limite est posée honnêtement : *« le plus ancien que nous ayons vu » ≠ « la vérité »* — elle
fait apparaître une structure ; l'humain juge. Le **conseil de couverture** signale le **déséquilibre**
géographique/linguistique **de votre propre collecte** (p. ex. « ~80% de ce que vous avez collecté vient d'un seul pays ») comme une
suggestion discrète d'élargir — il ne filtre ni ne plafonne jamais rien ; un corpus déséquilibré fausse chaque
signal en aval, donc voir ce déséquilibre est tout l'enjeu.

La **vérification météo disponible** est la première carte du type *si ceci, alors suggérer* : lorsque plusieurs de vos
articles mentionnent le même mot lié à un événement climatique (sécheresse, inondation, canicule… — une liste de départ
établie à la main en 12 langues, `configs/corroboration_rules.yml`) avec le même lieu
déduit dans une même fenêtre temporelle, la carte **propose** de récupérer des données météo indépendantes pour
exactement ce lieu et cette fenêtre. La carte elle-même est calculée localement — elle le dit — et
rien n'est récupéré tant que vous ne cliquez pas sur **Récupérer le contexte météo**, qui passe par la
même fenêtre de consentement réseau que toute autre action en ligne. Ce qui revient est une tranche limitée
de **réanalyse** Open-Meteo (CC BY 4.0, attribution affichée) : une *estimation de modèle*, pas un
relevé de station — elle peut **corroborer ou contredire** ce que disent les articles, jamais le prouver.
La tranche est mise en cache sur le disque, de sorte qu'une relecture ultérieure se fait hors ligne ; l'état du cache et
l'heure de récupération sont toujours affichés.

---

### Performances — précalculer, mettre en cache, servir le cache

Le briefing **n'est jamais calculé à chaque requête**. Le planificateur d'arrière-plan l'actualise
après chaque collecte et écrit un cache (`briefing_cache.json` dans votre dossier de données) ;
l'Accueil lit ce cache et se charge instantanément. Il se **met à jour tout seul** — il est recalculé en
arrière-plan après chaque passe et l'Accueil réinterroge de lui-même (une bannière de progression s'affiche
pendant une actualisation) ; il n'y a pas de bouton Actualiser manuel. Les cartes écartées
(`briefing_dismissed.json`) et le brouillon (`briefing_draft.json`) sont de petits fichiers JSON
locaux — mono-utilisateur, local d'abord, jamais transmis.

---

### Garde-fous d'honnêteté (dans le code, pas seulement dans la documentation)

FUTURE_DEVELOPMENTS §6 interdit tout score automatisé unique de confiance/qualité (il grave la
vision du monde de l'évaluateur dans un chiffre faussement objectif et *classera mal* les sources petites, étrangères,
nouvelles ou dissidentes). Cette interdiction est appliquée **mécaniquement** :

- `src/briefing/card.py:assert_no_score_fields()` rejette tout champ de `Card` dont le nom
  suggère un score composite (`score`, `trust_score`, `credibility`, `rating`,
  `verdict`, …). Elle s'exécute à l'import et un test vérifie qu'elle tient.
- La valeur numérique que porte une carte se trouve dans `signal` sous la forme d'**une seule grandeur mesurée avec une
  méthode indiquée** — un rapport de croissance, une valeur de Gini, un coefficient de corrélation — jamais un
  score mélangeant des dimensions incommensurables.
- **Montrer, ne pas étouffer.** Écarter une carte est réversible ; toute future sous-pondération sera
  transparente, réglable, désactivée par défaut et réversible.

---

### API

Tout se trouve sous `/api/briefing` (boucle locale uniquement, comme le reste de l'application) :

| Méthode et chemin | Rôle |
|---|---|
| `GET /api/briefing` | le fil en cache, regroupé par catégorie (`?force=true` pour recalculer) |
| `POST /api/briefing/refresh` | recalculer maintenant |
| `POST /api/briefing/dismiss` · `/restore` · `/dismissed/clear` | gérer les cartes écartées |
| `GET /api/briefing/draft` | le brouillon actuel (cartes épinglées + notes + titre) |
| `POST /api/briefing/draft/add` · `DELETE /api/briefing/draft/{id}` | épingler / désépingler une carte |
| `PUT /api/briefing/draft/note` · `/title` · `POST /draft/clear` | modifier le brouillon |
| `GET /api/briefing/draft/export.md` | le Markdown accompagné de ses preuves |

---

### Feuille de route (état)

Les phases A à D sont livrées : la colonne vertébrale cartes + briefing (A), le socle complet `src/signals/`
— concentration, quasi-doublons/coordination, nouveauté (B), le profil d'intégrité des sources +
l'anti-amplification guidée par l'utilisateur (C, voir [`USER_MANUAL.md`](USER_MANUAL.md)), et les lots
d'annotations signés et participatifs (D, voir [`USER_MANUAL.md`](USER_MANUAL.md)). La phase E livre les
verticales combinables sous forme de cartes (émotion, actualité PI/juridique) ; les **verticales de suivi des
modifications des sources primaires du droit et de la PI** (ingestion de `legislation.gov.uk`, EUR-Lex, brevets/registres)
restent l'étape suivante documentée — elles réutilisent les moteurs existants de suivi des modifications et de
quasi-doublons/corrélation, mais nécessitent des sources externes en direct. Voir
[`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md), phases B à E.


---

## Intégrité des sources et anti-amplification

> **État :** `0.06` Phase C — livrée et testée. La clé de voûte de la couche de
> renseignement (FUTURE_DEVELOPMENTS §6). Va de pair avec [`USER_MANUAL.md`](USER_MANUAL.md) et
> [`USER_MANUAL.md`](USER_MANUAL.md).

Les autres outils font remonter des signaux ; **celui-ci décide quels signaux comptent** — *sans
devenir un arbitre de la vérité*. C'est la réponse au problème « données pourries en entrée ».

### La surprise : traiter toutes les sources à égalité n'est **pas** neutre

Les tendances, la notoriété, la synchronie et « ce qui est couvert » **comptent tous des médias et du volume**.
L'égalité de traitement entre médias, appliquée à une mesure de volume, comporte donc un biais intrinsèque :
*celui qui produit le plus gagne.* Un acteur doté de moyens qui lance 40 médias (ou des
fermes à trolls, ou des usines à contenu) convertit directement son capital en consensus apparent et
**noie** les sujets honnêtes à source unique jusqu'à les faire disparaître. Ne rien faire n'est pas neutre —
c'est subventionner celui qui inonde.

La solution n'est pas de *noter* les sources. Elle consiste à définir la neutralité sur la bonne
**unité** : l'égalité de traitement entre *acteurs indépendants, pondérés par l'information nouvelle qu'ils
apportent*, et non entre *médias*. **Compter des faux-nez comme des voix est une erreur de mesure,
pas de la neutralité.**

### Ce qui est mesuré (et ce qui est interdit)

Nous restons strictement dans la moitié **autorisée** de la distinction du §6 :

- **(A) La notation de la véracité / de la qualité** — « cette source dit-elle vrai / est-elle bonne ? » — est
  **interdite à l'automatisation.** Elle grave la vision du monde de l'évaluateur dans un chiffre faussement
  objectif et *finira* par dévaloriser aussi une source bonne mais atypique.
- **(B) Les signaux d'authenticité / de structure** — « cette source est-elle ce qu'elle prétend être ? un
  nœud d'un réseau coordonné ? *produit*-elle l'information ou se contente-t-elle d'en *faire l'écho* ? sa production est-elle
  à la portée d'humains ? est-elle transparente sur qui la dirige ? » — ce sont, dans une large
  mesure, des **faits structurels mesurables.** Toute la conception se situe ici.

#### Le moteur partagé (`src/signals/`)

| Primitive | Mesure | Alimente |
|---|---|---|
| `concentration` | Gini + part des N premiers | concentration de la propriété / du régime d'information, notoriété |
| `near_dup` | groupes de quasi-doublons MinHash + LSH | détection d'écho / de syndication |
| `coordination` | graphe d'acteurs issu des quasi-doublons + synchronisation en cadence + hôte partagé | regroupement d'acteurs |
| `novelty` | part des séquences de mots nouvelles pour le corpus | pondération source d'origine / simple écho |

Les quatre sont **pures** (ni base de données, ni réseau), testées par propriétés, et portent une méthode + une mise en garde.

### L'anti-amplification est **guidée par l'utilisateur** (l'application propose → vous disposez)

L'anti-amplification n'est **jamais** une transformation silencieuse que l'application effectue et que vous vous contentez
d'*annuler* — cela ferait de l'application l'arbitre que le §6 interdit.

- **Par défaut = « égal mais averti ».** La vue brute à traitement égal est la référence ; un
  déferlement coordonné y est **annoté** (la carte *chambre d'écho*), pas regroupé.
- **C'est vous qui appliquez un regroupement**, groupe par groupe ou globalement. Alors seulement un réseau
  coordonné se replie en **une seule voix** dans tout comptage mesurant un consensus (combien de
  voix indépendantes portent un sujet).
- **Chaque regroupement appliqué reste signalé et réversible.** Un clic le redéploie en ses
  membres ; l'annulation reproduit **exactement** les comptages bruts à égalité. *Aucun regroupement n'est jamais
  appliqué sans action explicite de votre part* — garanti par un test.

C'est le **bureau d'intégrité des sources** (Paramètres → Avancé → Sécurité → « Ouvrir le bureau d'intégrité des sources ») :
*Détecter la coordination* liste les acteurs proposés avec leurs éléments (texte partagé,
synchronisation en cadence, hôte partagé) ; *Appliquer le regroupement* / *Développer (annuler)* sont à votre choix.
Les Pistes chambre d'écho de l'Accueil portent la même action *Regrouper en un seul acteur*.

### Le profil de la source — des dimensions mesurées, **aucun score composite**

Pour chaque source, un panneau de signaux *mesurés* — et **délibérément aucun chiffre de confiance
unique** (le « B » interdit). Un score sur 100 est une fausse précision sur des dimensions
incommensurables, manipulable selon la loi de Goodhart, un point unique de capture, et il *classera mal* les sources
petites / étrangères / nouvelles / dissidentes. L'interdiction est appliquée dans le code (le profil
renvoie `no_composite_score: true` et un test vérifie l'absence de toute clé agrégée `*score*`).

Dimensions (chacune avec sa propre méthode + sa mise en garde) :

- **Coordination** — appartenance à un acteur, avec qui, combien de sujets partagés.
- **Nouveauté** — cette source produit-elle l'information ou en fait-elle surtout l'écho ? (par rapport à *votre* corpus).
- **Capacité de production** — articles/jour par rapport à la médiane du corpus (une *question*, pas un verdict ;
  les agences de presse et les grandes rédactions sont légitimement prolifiques).
- **Transparence** — étiquettes de pays, de langue, de propriété/d'orientation (réputationnelles,
  contestables, modifiables), et le `reliability_score` défini par l'opérateur (non calculé ici).
- **Historique** — ce que cette source a apporté à votre corpus.

C'est vous qui choisissez le poids des dimensions dans *votre* vue — désactivé par défaut, réversible, la
vue brute à égalité toujours à un clic.

### Nouvelles cartes de briefing issues de cette couche

- **Chambre d'écho** (sur-raconté) — un même sujet porté par N sources coordonnées.
- **Signal isolé** (sous-raconté) — un sujet substantiel à source unique qui n'a pas eu d'écho.
- **Capacité invraisemblable** (à enquêter) — une source qui publie bien au-delà de la norme du corpus.

### API

| Méthode et chemin | Rôle |
|---|---|
| `GET /api/integrity/profile?source=` | le panneau de signaux mesurés sans score composite |
| `GET /api/integrity/actors` | acteurs coordonnés proposés, chacun signalé appliqué/non appliqué |
| `GET /api/integrity/prominence` | notoriété d'un sujet en voix indépendantes, brute ou regroupée |
| `POST /api/integrity/collapse/apply` · `/revert` | appliquer / annuler un regroupement (par acteur) |
| `POST /api/integrity/collapse/apply_all` · `/revert_all` | regrouper / réinitialiser globalement |

### Limites honnêtes (nommées)

- **Course aux armements / Goodhart** — tout signal publié devient une cible d'optimisation ; il s'agit
  d'une défense en profondeur, jamais d'une prétention à l'exhaustivité.
- **Les fusions erronées pénalisent les innocents** — la détection privilégie la précision, penche vers
  le *sous*-regroupement, montre toujours ses éléments, reste toujours réversible.
- **Capture** — nous livrons *des mécanismes, pas des verdicts* ; la vue par défaut est la vue transparente
  à égalité ; vous pouvez tout outrepasser.
- **L'objectif** n'est pas de « détecter tous les contenus pourris » (impossible, et le prétendre serait la
  démarche malhonnête), mais de **priver ces contenus de leur avantage mécanique** pour que la stratégie des 40
  agences *cesse d'être payante*.


---

## Annotations de sources partagées — signées, portables, fédérées par la confiance

> **État :** `0.06` Phase D — livrée et testée. La réponse au passage à l'échelle du profil de
> source (FUTURE_DEVELOPMENTS §6). Va de pair avec [`USER_MANUAL.md`](USER_MANUAL.md).

Le profil de la source vous laisse choisir le poids des dimensions. Mais **personne ne peut évaluer seul
et de façon neutre des milliers de sources** — la pondération doit donc être **collective**. La façon
honnête, locale d'abord et non centralisée d'y parvenir, ce sont des **lots d'annotations signés et
partageables**.

- Vous publiez vos annotations de sources — étiquettes de coordination, faits de propriété/transparence,
  étiquettes d'orientation, corrections, notes — sous la forme d'un **lot signé par la chaîne de possession, vérifiable et
  portable** (avec le même signataire hybride Ed25519 + ML-DSA que la chaîne de possession —
  une *mutualisation*, pas une seconde pile cryptographique).
- Les autres utilisateurs **importent** les lots auxquels ils choisissent de faire confiance — une **toile de confiance** facultative,
  **jamais** une autorité centrale.
- L'agrégation est **transparente** : vous voyez toujours *qui a affirmé quoi*, et **le désaccord est
  affiché, pas moyenné** dans un chiffre caché.

Ni serveur, ni comptes, ni score global — **une fédération par échange signé.**

### Ce qu'est une annotation (et ce qu'elle n'est pas)

Une annotation est un **fait ou une étiquette descriptifs et contestables** concernant une source. Types :
`ownership`, `leaning`, `coordination-tag`, `transparency-fact`, `correction`, `note`.
Ce n'est **jamais** un score composite de confiance/qualité — c'est interdit, par conception et dans
le code (un type invalide comme `trust-score` est rejeté).

### Modèle de confiance — ce qu'une signature prouve et ne prouve pas

Chaque lot intègre l'**identité publique** de son auteur et une signature sur le manifeste
canonique. La vérification **épingle** la clé intégrée, si bien qu'une attaque par altération puis nouvelle signature ne peut pas
*usurper l'identité* de l'auteur d'origine — elle produit simplement un auteur **différent**. Un
lot vérifié est donc toujours attribué fidèlement à la clé qui l'a signé, quelle qu'elle soit.
Vous décidez ensuite *à quelles clés faire confiance* ; seules les annotations des auteurs de confiance sont agrégées.

C'est une **toile de confiance, pas une preuve d'exactitude** : faire confiance à un auteur signifie « je veux
voir ses affirmations », pas « ses affirmations sont vraies ». Le désaccord entre auteurs de confiance
vous est présenté pour que vous en jugiez, jamais tranché à votre place.

### Utilisation (le bureau d'intégrité des sources — Paramètres → Avancé → Sécurité)

1. **Rédigez** des annotations (cible + type + valeur) sous *Annotations partagées (toile de confiance)*.
2. **Exporter un lot signé** → un fichier JSON que vous pouvez publier ou partager.
3. **Importer un lot…** → l'application **vérifie la signature** avant de l'enregistrer (un lot invalide
   est refusé, de façon explicite), puis liste l'auteur sous *Auteurs de confiance* avec un
   interrupteur de confiance.
4. **Qui a dit quoi ?** → agrège toutes les affirmations sur une source provenant de vous et des
   auteurs de confiance, avec les attributions et les désaccords affichés.

Retirer sa confiance à un auteur exclut ses annotations ; supprimer un auteur les efface proprement.

### API

| Méthode et chemin | Rôle |
|---|---|
| `GET /api/annotations/mine` · `POST` · `DELETE /mine/{i}` | les annotations que vous avez rédigées |
| `POST /api/annotations/export` | un lot signé et portable de vos annotations |
| `POST /api/annotations/import` | vérifier + enregistrer un lot importé (refusé s'il est invalide) |
| `GET /api/annotations/authors` · `PUT /authors/trust` · `DELETE /authors/{id}` | la toile de confiance |
| `GET /api/annotations/for?target=` | agrégation transparente — qui a affirmé quoi |

### Contraintes d'honnêteté

- **Pas de moyenne, pas de chiffre de consensus, pas de score.** L'agrégation renvoie des affirmations
  attribuées et nomme les *désaccords* ; elle ne réduit jamais un désaccord à un chiffre.
- **Local d'abord.** Tout est un fichier dans votre dossier de données ; rien n'est transmis et
  il n'y a ni serveur ni compte.
- **Contestable par construction.** Chaque annotation est une étiquette ou un fait sur lequel vous et d'autres pouvez
  être en désaccord — de façon visible.


---

## Analyses — statistiques sur les mots-clés et les entités

### Objectif

Transformer le corpus unifié, simple champ de recherche, en instrument d'analyse. Les mots-clés
et les entités sont extraits du **texte des articles ingérés**, enregistrés avec leurs
occurrences et leur contexte, et présentés de sorte qu'un journaliste d'investigation puisse se demander :
*de quoi parle-t-on, où, quand, qui en parle, et en lien avec quoi ?*

Tout ce qui figure ici est un **véritable agrégat** de données enregistrées, avec une méthode et une
taille d'échantillon indiquées — jamais un score fabriqué (PRODUCT_SYNTHESIS §3.5).

### Fonctionnement

```
ingest an article ──► extract (baseline / opt-in spaCy) ──► KeywordMention rows
                          terms + entities, offsets        (count + first offset +
                                                            denormalised date/country/city)
                                                                   │
                          Insights tab / /api/insights  ◄──────────┘
                          trends · associations (PMI) · context · map
```

- **Extraction** (`src/analytics/extract.py`) : des **termes** n-grammes thématiques
  (filtrés des mots vides) ainsi que des **entités** — personnes, entreprises/organisations, lieux — traitées comme
  des unités. La version de base (sans dépendance) détecte les entités comme des suites de plusieurs mots
  à majuscule initiale et n'attribue un type `person`/`org`/`location` qu'à partir d'un
  répertoire géographique (sinon, le type générique honnête `entity`) ; un extra facultatif **spaCy** `[nlp]`
  ajoute une vraie reconnaissance d'entités nommées `PERSON`/`ORG`/`GPE`. Chaque mot-clé consigne **quel extracteur
  l'a étiqueté** — un type d'entité est une *affirmation étiquetée par X*, pas une vérité de terrain.
  Fonctionne au mieux pour les écritures séparant les mots par des espaces ; la segmentation CJK/arabe est une étape ultérieure connue.
- **Stockage** (`src/analytics/store.py`) : une `KeywordMention` par couple (article,
  mot-clé) — nombre d'occurrences + position du premier caractère (la phrase de contexte est extraite
  de l'article enregistré à la lecture, ce qui garde la base légère) + `observed_on` / `country` / `city`
  dénormalisés, issus de la source. L'indexation s'exécute au mieux lors de
  l'ingestion (version de base rapide, sans blocage en cas d'échec). L'indexation est **automatique** — tout retard est résorbé
  par un rattrapage silencieux en arrière-plan quand vous ouvrez Analyses (le compteur « restants » descend à 0
  de lui-même) ; il n'y a pas de bouton « Indexer le corpus (Index corpus) ». Une réindexation complète du corpus existant
  est disponible dans **Paramètres → Avancé → Diagnostics** (« Réindexer tout le corpus » / « Nettoyer les
  mots-clés (réindexer, puis élaguer) ») sous la forme d'une tâche d'arrière-plan pouvant être suspendue.

### Fonctions (onglet Analyses + `/api/insights`)

| Vue | Point d'accès | Ce qu'elle montre |
|------|----------|---------------|
| Explorer — tendance | `GET /trend?term=&bucket=` | Volume de mentions dans le temps (jour/semaine/mois), avec le mot-clé résolu + son type |
| Explorer — carte mentale | `GET /associations?term=` | Mots-clés cooccurrents classés par **PMI** (information mutuelle ponctuelle) avec les tailles d'échantillon + une mise en garde « association ≠ causalité » ; cliquez sur un nœud pour recentrer |
| Explorer — contexte | `GET /context?term=` | Extraits de mentions récentes tirés du texte des articles, avec liens vers l'article/la source + pays/ville/date |
| Tendances | `GET /trending`, `GET /top` | Termes en hausse (**rapport** période récente / période précédente, une mesure étiquetée) et termes principaux, filtrables par fenêtre / type / pays |
| Carte | `GET /map?days=&kind=` | Principaux mots-clés **par pays et par ville** (signal régional fondé sur la source) |
| Indexation | `GET /status`, `POST /reindex?limit=` | Nombres d'éléments indexés/restants ; rattrapage du corpus par lots |

Filtres `kind` : `term`, `entity`, `person`, `org`, `location`.

### Garanties d'honnêteté

- Les tendances et termes principaux sont de vrais comptages ; « en hausse » est un **rapport** défini entre période récente et période précédente,
  explicitement *pas* un test de significativité.
- Les associations utilisent la **PMI** sur la cooccurrence au sein des articles, renvoyée avec `n` et la
  mise en garde selon laquelle les petits échantillons sont bruités.
- Les types d'entités portent la provenance de leur extracteur ; la version de base ne revendique jamais un type
  précis personne/organisation/lieu qu'elle ne peut pas justifier.
- La région sur la carte est le pays/la ville **de la source** (le signal fiable). La
  vue Carte comprend désormais un **SVG équirectangulaire interactif** (zoom/déplacement, noms des villes
  affichés au zoom) qui place les villes selon leurs vraies latitude/longitude tirées d'un **répertoire géographique** : un petit
  échantillon est fourni (`configs/cities.sample.yml`) ; l'ensemble complet est généré à partir de
  Wikidata (`scripts/build_city_gazetteer.py` → `configs/cities.yml`). Une ville sans
  correspondance dans le répertoire conserve ses données de mots-clés mais **aucune position tracée** (jamais une
  localisation fabriquée). Les tableaux par pays/ville restent affichés à côté de la carte.


---

## Suivi des modifications de Wikipédia

### Objectif

Wikipédia est un terrain disputé : les articles sont modifiés en continu et, à l'ère des LLM,
supprimer ou réécrire l'histoire n'a jamais été aussi facile. Cet outil traite chaque
**édition linguistique** de Wikipédia comme une source suivie dont les *modifications* sont les données, afin
qu'un journaliste puisse **détecter et documenter** des changements de grande ampleur ou révisionnistes —
p. ex. prouver qu'une phrase existait à une date donnée et a été supprimée par un
compte donné.

> Les éditions sont par **langue** (`en`, `fr`, `ar`, `ru`, `zh`, …), pas
> par pays (il n'existe pas de Wikipédia nationale) ; l'interface associe les langues aux pays.

### Pourquoi ce n'est pas une ingestion d'« article ordinaire »

Les articles changent avec le temps ; ils ne peuvent donc pas être enregistrés comme des lignes `Article` ponctuelles.
Deux choix de conception en découlent :

1. **Utiliser l'API Action de MediaWiki, pas l'extraction des pages** — `revisions`,
   `recentchanges` (avec les variations en octets) et `compare` (différences calculées par le serveur). C'est
   la voie efficace, respectueuse des conditions d'utilisation et orientée changements.
2. **Enregistrer les différences, pas des copies** — conserver **une seule** version de référence compressée en texte intégral
   par page (`wiki_pages.baseline_text`) ; chaque modification ultérieure est une ligne `wiki_revisions`
   contenant la **différence + la variation signée en octets + les indicateurs**, jamais le nouvel article
   en entier. Toute version historique peut être reconstituée en rejouant les différences.

**Cela répond à la question de la redondance et de l'espace disque :** une modification cosmétique est une petite différence
portant l'indicateur `minor` de MediaWiki, filtrée par un seuil de taille/mineure ; elle
ne coûte donc presque rien. Le stockage croît avec **l'activité de modification des pages surveillées**, pas
avec le corpus d'articles de plusieurs Go — vous n'avez jamais besoin du dump complet pour le suivi.

### Détecter les modifications de grande ampleur / suspectes (honnêtement)

`src/wiki/flagging.py` signale une modification et enregistre des **codes de motif** — il fait remonter
des *candidats*, il ne déclare pas « désinformation » :

- `large_removal` / `large_addition` — variation en octets au-delà d'un seuil
- `revert` / `blank` — balises de modification MediaWiki (`mw-reverted`, `mw-undo`, `mw-blank`…)
- `anon_large` — une modification moyenne ou plus importante depuis une IP anonyme
- `burst` — de nombreuses modifications d'une même page en peu de temps
- `ores_damaging` — probabilité « nuisible » facultative de **Wikimedia ORES**, présentée
  comme une affirmation *étiquetée par ORES* (comme notre provenance des entités)

Les modifications cosmétiques mineures ne sont jamais signalées. Chaque modification signalée est documentée avec sa
différence + sa provenance (revid, auteur de la modification, horodatage), qui s'intègrent à la
**chaîne de possession** existante pour des preuves signées et horodatées.

### Deux sous-systèmes clairement séparés (expérience utilisateur)

1. **Surveiller et suivre (Watch & track)** (léger, instantané, par défaut) : une liste de suivi de pages /
   catégories par édition linguistique ; interrogation des révisions par le planificateur intégré ; enregistrement des
   révisions + différences + indicateurs ; un visualiseur de différences + une chronologie par page. Aucun téléchargement massif.
2. **Version de référence hors ligne (Offline baseline)** (lourde, facultative) : se trouve dans **Paramètres → Bases de référence
   Wikipédia hors ligne** (délibérément à l'écart du suivi léger). Une
   **liste sélectionnable d'éditions linguistiques** (choisie, de la plus grande à la plus petite, avec le nom de
   chaque langue dans cette langue et un ordre de grandeur de taille) remplace la saisie libre d'un code ; la
   taille exacte du dump actuel est lue sur le serveur à la demande (`Estimate size`),
   puis téléchargement / suspension / reprise / suppression. La liste provient de
   `GET /api/wiki/languages` ; le téléchargeur accepte toujours n'importe quel code d'édition.
   (Ordre de grandeur réel : le texte actuel d'enwiki ≈ 22 Go compressé ; l'historique complet se compte en
   téraoctets — utile seulement pour des différences historiques hors ligne.)

### État

- **Fait :** schéma (`wiki_pages`, `wiki_revisions` ; migration `d4e5f6a7b8c9`) ;
  l'analyseur de l'API MediaWiki + le client en direct (`mediawiki.py`, `client.py`) ; la
  logique de signalement des modifications (`flagging.py`) ; le client ORES (`ores.py`) ; l'orchestrateur
  de suivi (`track.py`, stockage version de référence + différences) ; le mode `wiki` du planificateur ;
  l'**API** (`/api/wiki/*`) et **Paramètres → Wikipédia** (liste de suivi, suivre maintenant,
  fil des modifications signalées, visualiseur de différences) ; le **téléchargeur de versions de référence hors ligne**
  (`dumps.py` — par langue, reprenable, sonde de taille), désormais piloté par un **sélecteur
  de langue** (`languages.py`, `GET /api/wiki/languages`) déplacé vers **Paramètres →
  Bases de référence Wikipédia hors ligne**. Toute la logique pure et l'orchestration sont testées unitairement avec
  des données de test (sans réseau).
- **À venir :** relier les différences wiki aux statistiques de mots-clés d'Analyses ; flux
  EventStreams facultatif ; exportation en preuve d'une différence signalée via la chaîne de possession.

### Éthique

Toute récupération respecte la politique d'utilisation de l'API MediaWiki (User-Agent identifiant,
`maxlag`, limites de débit) — plus respectueux que l'extraction de pages. Nous n'enregistrons que des données
de révision publiques ; rien n'est récupéré tant que le suivi ne s'exécute pas.


---

## Droit mondial — suivi des modifications des lois, journaux officiels et PI

> **État :** `0.06` Phase E — livrée. La verticale du §5 : un « Wikipédia du droit ».
> Réutilise le moteur de suivi des modifications (`src/wiki`) et les moteurs partagés de `src/signals/`.

Rassembler le **droit** — lois, législation, journaux officiels, registres de PI — à partir de
sources officielles du monde entier, et **suivre son évolution dans le temps**. Le droit est public dans
de nombreux pays et change par voie d'amendement, si bien que les données *sont la différence* : ce qui a changé, et quand.

### Activé par défaut — un catalogue mondial de vraies sources officielles

`configs/legal_sources.yml` fournit un ensemble choisi et mondial de **vraies sources primaires
officielles** — bases nationales de législation (`legislation.gov.uk`, EUR-Lex, Légifrance,
`gesetze-im-internet.de`, `congress.gov`/`govinfo.gov`, `legislation.gov.au`,
`indiacode.nic.in`, `elaws.e-gov.go.jp`, `law.go.kr`, …), journaux officiels, offices de PI
(WIPO Lex, USPTO, EPO, EUIPO, JPO, …) et systèmes ouverts de jurisprudence et de dépôts (CourtListener,
SEC EDGAR). Au premier lancement, elles sont ajoutées comme des sources ordinaires **ingérables et consultables**
(`source_type` legal/ip), de sorte qu'elles passent par la *même* chaîne de traitement éthique que l'actualité.

Un sous-ensemble choisi de **textes de loi consolidés** stables et bien connus (p. ex. le Human
Rights Act britannique, le RGPD de l'UE, la Constitution des États-Unis) est enregistré pour le **suivi des modifications**
dès l'installation.

### Fonctionnement du suivi (réutilise le moteur Wikipédia)

Pour chaque document suivi, la première récupération réussie constitue la **version de référence** immuable
(« la loi telle qu'elle était à la date X »). Chaque récupération ultérieure dont le *texte visible normalisé*
diffère enregistre une révision portant la variation en octets, une **différence** unifiée plafonnée par rapport à la
version de référence, et un **indicateur de changement important** honnête (qui réutilise les seuils de signalement du wiki).
Lancez-le depuis l'**onglet Gouvernements → sous-onglet Droit** (« Suivre les modifications maintenant ») ou via le
planificateur d'arrière-plan (mode `law`). Toute récupération passe par le chemin **éthique,
fermé par défaut vis-à-vis de robots.txt**.

### Lire une loi à partir du XML de l'éditeur lui-même (sources structurées)

Une page web doit être *reconstruite* en texte : on retire la navigation, le formulaire de recherche,
le bandeau des cookies, en espérant que ce qui reste soit bien la loi. Cela fonctionne, et c'est ce que
fait le suivi pour la plupart des sources — mais la copie enregistrée d'une loi britannique a un jour commencé par
le formulaire de recherche du portail lui-même, et tout ce qui en a été dérivé (une personne « Personal Acts », une
organisation « PART ») provenait d'un texte qui n'avait jamais figuré dans la loi.

Lorsqu'un éditeur publie son **propre XML**, rien de tout cela ne s'applique : le fichier ne contient aucun habillage
de page, puisque ce n'est pas une page. Open Omniscience sait lire directement le CLML de
`legislation.gov.uk`, ce qui apporte en plus deux choses qu'une page ne peut pas offrir :

- **Des dispositions dotées d'adresses citables.** Chaque article est lu avec le chemin Partie/Chapitre
  qui le surplombe, si bien qu'une modification peut être signalée comme *« l'article 12 de la Partie 2 a changé »* plutôt que
  comme un nombre d'octets. Les articles sont mis en correspondance par cette adresse, jamais par leur position —
  sinon, l'insertion d'un seul article ferait apparaître comme modifié tout le reste de la loi.
- **Des dates qui veulent dire ce qu'elles disent.** La promulgation, le point de consolidation et la date à laquelle *nous*
  l'avons récupérée sont trois champs distincts, sans aucun repli de l'un sur l'autre. Une date que le document
  n'indique pas s'affiche comme inconnue, jamais complétée à partir d'une autre. (C'est pourquoi une
  loi suivie n'affiche aucune date de publication si le document lui-même n'en fournit pas : la seule
  date disponible était le jour où nous avons interrogé la page, et une date d'interrogation n'est pas une date
  de publication.)

La comparaison article par article est **additionnelle et expérimentale** : la comparaison de texte ordinaire décide toujours
si une révision est enregistrée et porte toujours l'indicateur de modification importante. Et une
limite est énoncée plutôt qu'aplanie — un article *renuméroté et réécrit*
dans la même modification est signalé comme une suppression plus un ajout, car le rapprocher de
son ancienne version reviendrait à deviner lequel de deux articles numérotés différemment est « le
même, modifié ».

**Ce qui n'existe pas encore :** rien ne récupère encore ces documents XML automatiquement. Lire
l'ensemble du corpus juridique d'une juridiction suppose de parcourir la liste que l'éditeur en tient lui-même (le Royaume-Uni
liste chaque loi ; la France liste 76 codes), et ce recensement n'est pas construit. En attendant,
l'ensemble suivi reste l'ensemble sélectionné à la main, et le rapport de couverture indique honnêtement
« couverture inconnue » plutôt que de présenter un nombre de documents suivis comme s'il s'agissait du
corpus entier.

### Vérifier que les correctifs juridiques ont atteint vos données

Deux correctifs juridiques se réparent **discrètement, à la prochaine récupération réussie d'un document** : l'habillage de page est
relu à partir d'une référence enregistrée, et une date de publication qui était en réalité une date d'interrogation est
effacée. Les deux sont corrects — et un document dont le portail est injoignable ne se répare jamais, ce qui
est précisément le cas qu'il vaut la peine de connaître.

Le rapport **law-ingest** (dans le lot de tous les diagnostics, ou seul) répond à cette question à partir des
données enregistrées, sans aucun appel réseau : ce que la dernière vérification de chaque document suivi a enregistré (un
décompte par résultat, par exemple inchangé, relu, erreur ou différé, ainsi que le résultat propre à chaque document et
l'heure de sa dernière tentative), et si un article juridique porte encore une
date de publication qu'il ne devrait pas avoir. Un document dont la dernière vérification a échoué mérite qu'on
s'y intéresse, mais le rapport ne peut pas dire s'il a été relu une fois avant de commencer à échouer :
ce n'est pas enregistré. Le décompte des relectures ne compte d'ailleurs que les documents dont l'interrogation
la plus récente était la relecture ; sur une installation où tous les documents sont réparés, il retombe donc
vers zéro.

Il signale aussi les **résidus d'habillage** — du texte de navigation encore présent dans un corps enregistré. Lisez
cela comme une *mesure*, pas comme un verdict : le retrait de l'habillage n'enlève délibérément que ce que
le balisage déclare comme habillage et laisse le reste, car une règle fondée sur la correspondance de texte
supprimerait aussi les propres intitulés d'articles d'une loi. Des résidus après une relecture correcte sont attendus ;
le nombre vous indique combien d'habillage non déclaré se trouve dans votre corpus, et la liste des marqueurs est
un plancher : zéro signifie donc « aucun de ceux-ci », jamais « aucun habillage ».

### Cartes de briefing issues du corpus juridique

- **Loi modifiée (Law changed)** (à surveiller) — une modification signalée d'un document juridique suivi.
- **Législation modèle** (à examiner) — un texte juridique quasi identique dans deux juridictions ou plus
  (le moteur de quasi-doublons des §1/§2), un schéma de diffusion mesurable.

En outre, comme le texte juridique fait partie du corpus unifié, la corrélation **droit ↔ actualités** et
l'analyse des mots-clés s'y appliquent comme à n'importe quelle autre source.

### API

| Méthode et chemin | Rôle |
|---|---|
| `GET /api/law/status` | couverture : documents par juridiction, totaux des modifications et des signalements |
| `GET /api/law/documents` | documents suivis (éventuellement `?jurisdiction=`) |
| `GET /api/law/documents/{id}` | un document avec son historique de modifications (différences) |
| `GET /api/law/changes` | modifications juridiques récentes (signalées), les plus récentes en premier |
| `POST /api/law/track` | récupérer maintenant tous les documents surveillés (récupérateur éthique) |
| `POST /api/law/seed` | (ré)initialiser le catalogue mondial + enregistrer les documents |

### Contraintes d'honnêteté (le droit est un domaine à enjeux élevés)

- **Ni un conseil juridique, ni la source qui fait foi.** La copie agrégée est un
  *miroir de recherche* ; chaque enregistrement renvoie au journal officiel, et l'interface le dit.
  Suivre et faire apparaître ; ne jamais interpréter la légalité ni juger une loi.
- **« Public » ≠ « librement redistribuable ».** Les licences varient même lorsque le texte est public —
  chacune est respectée et attribuée, avec la provenance enregistrée, et robots.txt fermé en cas d'échec (comme pour les actualités).
- **Délimiter honnêtement la portée.** « Tous les pays » est le cap, pas la v1 : le catalogue est large mais
  sélectionné, et le suivi des modifications se fait par comparaison de texte normalisé (les portails de textes consolidés donnent
  le signal le plus net). Lorsqu'un éditeur publie du XML structuré, des comparaisons article par article sont
  disponibles (voir ci-dessus) — le CLML aujourd'hui ; Akoma Ntoso / ELI ne sont pas encore lus. L'outil indique
  ce dont il dispose pour chaque document et refuse de deviner : un document qu'il ne peut pas analyser
  structurellement garde la comparaison de texte plutôt que d'être présenté comme s'il comportait des articles.
- **La traduction** (par le LLM local) est une aide distincte, clairement étiquetée — jamais une
  traduction juridique qui fait foi.


---

## Marchés : renseignement financier, boursier et sur les matières premières et terres rares

Open Omniscience fournit un **catalogue mondial et sélectionné de sources de marché**, si bien qu'il est
prêt à collecter l'actualité des marchés financiers dès l'installation, ainsi qu'un onglet **Matières premières** qui
transforme des pages *configurées* en une véritable série de prix, affichable en graphique et corrélée aux actualités.

Ce document explique ce qui est préinstallé, ce qui ne l'est pas, et pourquoi — car la
frontière honnête compte ici davantage qu'une longue liste de fonctionnalités.

### Ce qui est préinstallé (prêt à l'emploi tel quel)

`configs/markets_sources.yml` est chargé automatiquement en même temps que le catalogue d'actualités
(`configs/sources.yml`) au premier lancement, et via **Paramètres → Avancé → Sources → Initialiser des sources de départ**.
Il contient environ 110 entrées sélectionnées, identifiées par un domaine
principal stable :

- **Bourses de valeurs et de titres** du monde entier (Amériques, Europe, Asie-Pacifique,
  Moyen-Orient, Afrique) — NYSE, Nasdaq, LSE, Euronext, Deutsche Börse, JPX, HKEX,
  SSE/SZSE, NSE/BSE Inde, SGX, ASX, B3, Tadawul, JSE, et bien d'autres.
- **Bourses de matières premières, de métaux, d'énergie et de produits dérivés** — CME Group, ICE, LME,
  SHFE, DCE, ZCE, INE, **GFEX** (contrats à terme sur les terres rares et le silicium industriel), MCX,
  Eurex, MGEX.
- **Sources de prix et de données sur les matières premières et les terres rares** — Shanghai Metals Market, Kitco,
  USGS, World Bank Pink Sheet, EIA, IEA, OPEC, Fastmarkets, Argus, Benchmark
  Mineral Intelligence, S&P Global Commodity Insights.
- **Éditeurs d'actualités et de données financières** — Bloomberg, Reuters, FT, WSJ, CNBC,
  MarketWatch, Nikkei Asia, Caixin, et d'autres.

Ce sont des **sources** ordinaires : elles alimentent le corpus unifié par le même
récupérateur éthique (robots.txt fermé en cas d'échec, débit limité). Chacune porte un
`source_type` (`stock_exchange` / `commodity` / `financial`), une région, un pays et
des étiquettes, pour que vous puissiez les filtrer dans **Paramètres → Avancé → Sources** et leur associer des règles de prix dans
**Matières premières**.

> Les flux RSS sont volontairement laissés vides pour ces entrées (une URL de flux erronée n'est
> que du bruit). Collectez-les avec le robot d'exploration récursif, ou ajoutez un flux RSS vérifié
> pour chaque source depuis **Paramètres → Avancé → Sources**.

### Obtenir de vrais chiffres de prix

Une série de prix n'est produite que là où vous indiquez à l'application **exactement où se trouve
le chiffre** — il n'y a pas de lecture magique des pages, et c'est voulu. Deux voies honnêtes :

#### 1. Règles d'extraction par page (onglet Matières premières → « Configurer les sources de données »)

*(Les flux et les règles d'extraction se trouvent dans une section repliée « Configurer les sources de données (flux et règles d'extraction) » de
l'onglet Matières premières ; les flux sélectionnés eux-mêmes se mettent à jour automatiquement en
arrière-plan.)*

Ajoutez une règle (source, symbole, URL de la page, **sélecteur CSS**, attribut et
expression régulière de valeur facultatifs, devise, unité), puis appuyez sur **Tester**. Le test récupère la page une fois et
affiche la valeur *exacte* trouvée — ou la raison *exacte* de l'absence de correspondance — pour que vous puissiez
ajuster le sélecteur avec un vrai retour. Les règles qui trouvent une correspondance enregistrent un `CommodityPrice`
par jour, que lisent les graphiques intégrés et la corrélation prix↔actualités.

Modèles à copier : `configs/market_rules.example.yml`.

**Mise en garde (à lire) :** la plupart des pages de bourses et de cotations affichent les prix avec JavaScript,
si bien que le chiffre ne figure *pas* dans le HTML statique que reçoit le récupérateur, et un sélecteur
ne trouvera rien. C'est pourquoi aucun sélecteur fonctionnel n'est **fourni d'avance** — les deviner
reviendrait à fabriquer des chiffres. Les pages rendues côté serveur (beaucoup de sites officiels ou statistiques,
certains tableaux de données) fonctionnent bien ; les widgets de cotation fortement rendus côté client, non.

#### 2. Flux CSV officiels (recommandé — fiable, livré avec un catalogue)

Pour un historique chiffré digne de confiance, importez une série CSV lisible par machine depuis une
source officielle. C'est la voie fiable, et l'application fournit un catalogue de départ
(`configs/commodity_feeds.yml`) que vous pouvez importer en un clic depuis
**Matières premières → Configurer les sources de données → Flux de prix officiels**, ou via l'API :

```
GET  /api/markets/feeds                # list curated feeds + how many points each has
POST /api/markets/feeds/{key}/import   # import one (e.g. copper, wti_crude, brent_crude)
POST /api/markets/feeds/import-url      # import ANY CSV URL you supply (user-customizable)
```

**Fournisseur principal — FRED** (Federal Reserve Bank of St. Louis) : un point d'accès CSV stable,
sans clé d'API, `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`,
qui **redistribue les séries de matières premières « Pink Sheet » de la Banque mondiale** (les identifiants
« Global price of … » — cuivre `PCOPPUSDM`, brent `POILBREUSDM`, etc.) et
les séries énergétiques de l'**EIA** (`DCOILWTICO`, `DHHNGSP`, …). La première colonne est la date,
la deuxième la valeur ; les valeurs manquantes (`.`) sont ignorées, jamais enregistrées comme zéro. L'import
est idempotent par `(symbol, market, date)`.

**Sources comparables** que vous pouvez ajouter comme flux personnalisé (URL + noms de colonnes facultatifs) :
- **Banque mondiale** Commodity Markets (« Pink Sheet ») : le `.xlsx` se trouve à
  <https://www.worldbank.org/en/research/commodity-markets> ; les mêmes séries en
  CSV propre sont disponibles via les flux FRED ci-dessus.
- Données ouvertes sur l'énergie de l'**EIA** américaine : <https://www.eia.gov/opendata/>
- **FMI** Primary Commodity Prices : <https://www.imf.org/en/Research/commodity-prices>
- Données de l'**USGS** sur les matières premières minérales (terres rares) : <https://www.usgs.gov/centers/national-minerals-information-center>

La correspondance de colonnes par défaut est colonne 1 = date, colonne 2 = valeur (la convention
FRED) ; nommez explicitement `date_column` / `value_column` pour d'autres dispositions.

Il existe aussi une voie de téléversement direct pour un CSV que vous avez déjà :

```
POST /api/commodities/{symbol}/prices/import-csv      (multipart file upload)
```

> Si un fournisseur renomme ou retire une série, l'import échoue **bruyamment** (erreur
> HTTP / aucune ligne exploitable) plutôt que d'inventer des données — corrigez l'URL dans
> `configs/commodity_feeds.yml` ou utilisez un flux personnalisé.

### Pourquoi pas de prix extraits automatiquement dès le premier jour ?

Parce qu'un chiffre sans origine vérifiable est pire que pas de chiffre du tout. Tout dans
cet outil est conçu pour qu'un chiffre montré à l'utilisateur provienne d'une véritable
mesure : un sélecteur qui a réellement trouvé une correspondance, ou un CSV réellement
importé. Le catalogue vous donne les *sources* instantanément ; c'est vous qui décidez, page par page, quand
un prix est assez fiable pour être enregistré.


---

## Chaîne de possession

Open Omniscience formule une affirmation probante délibérément *étroite et honnête* :

> **Ce corpus contenait _cet_ élément, avec _ce_ contenu, enregistré à _ce_
> moment, et l'enregistrement n'a pas été modifié depuis — et voici une preuve
> cryptographique que vous pouvez vérifier vous-même, hors ligne, sans faire confiance à cet outil.**

C'est réellement utile pour un journaliste d'investigation : cela protège contre
« vous avez fabriqué ceci », « vous avez antidaté ceci » ou « vous l'avez discrètement modifié après
coup », et cela vous permet de montrer que vous aviez rendu compte de quelque chose *avant* qu'une page source ne soit
modifiée ou supprimée. Ce n'est **pas** un système de dépôt pour lanceurs d'alerte (comme
SecureDrop), et une « source » dans cet outil est un *média d'information*, pas une source
humaine confidentielle. Gardez cette portée à l'esprit lorsque vous raisonnez en termes de protection.

Ce document décrit les mécanismes réels (`src/custody/`, `src/reporting/`) et
dit explicitement ce que chacun prouve et ce qu'il ne prouve **pas**.

---

### Les trois propriétés, et comment nous obtenons chacune honnêtement

| Propriété | Mécanisme | Ce que cela prouve | Ce que cela ne prouve **pas** |
|---|---|---|---|
| **Intégrité** | Signatures Ed25519 (+ ML‑DSA facultatif) sur une sérialisation canonique ; racine de Merkle sur tous les champs de provenance | Les octets n'ont pas changé depuis la signature ; tout est couvert, pas seulement le contenu | — |
| **Provenance** | **Épinglage** de la clé publique connue du signataire | L'enregistrement a été signé par *ce* signataire | Rien, si vous n'épinglez pas de clé — une signature valide seule signifie uniquement « signé par la clé intégrée au lot » |
| **Horodatage** | `local` (auto-déclaré) **ou** OpenTimestamps (ancré dans Bitcoin) | Local : une heure que l'outil affirme. OTS : le contenu existait *au plus tard* lors d'un bloc Bitcoin | L'heure locale ne prouve rien à un tiers ; OTS prouve une *limite supérieure* dans le temps, pas le moment exact |

Nous refusons de simuler l'une ou l'autre de ces propriétés. Si un véritable horodatage tiers ne peut pas être obtenu
(hors ligne, ou la bibliothèque n'est pas installée), le code lève une erreur plutôt que d'inventer une
heure — le mode d'échec que la charte du projet interdit (PRODUCT_SYNTHESIS §3.7).

---

### Composants

#### 1. Lots de preuves signés — `src/reporting/evidence.py`
Un export à un instant donné d'articles sélectionnés, chacun avec sa provenance et une empreinte
de contenu, liés par une **racine de Merkle à séparation de domaine** et une **signature Ed25519**.
Vérifiez hors ligne avec `scripts/verify_evidence.py <bundle.json> [signer_pubkey]`.
Exposé à `POST /api/reports/evidence` et `/api/reports/evidence/verify`.

La clé de signature se trouve dans `keys/evidence_ed25519.pem` sous votre dossier de données. Sur un
stockage chiffré, elle est enveloppée sous votre phrase secrète (une clé créée auparavant est enveloppée, telle quelle, la première fois
qu'un export la charge avec le stockage déverrouillé), si bien qu'une copie du seul dossier de données ne peut pas signer à votre place ;
sans phrase secrète, elle reste en `0600` en clair. Si une sauvegarde restaurée a apporté une clé enveloppée
sous la phrase secrète d'une autre installation, un export de preuves et chaque sauvegarde (une sauvegarde signe son manifeste
avec cette clé) indiquent qu'ils ne peuvent pas l'ouvrir et ne remplacent rien : utilisez la phrase secrète sous laquelle elle a été enveloppée,
ou déplacez le fichier ailleurs pour qu'une nouvelle clé soit créée (les lots signés avec l'ancienne clé restent vérifiables avec
sa clé publique). Une phrase secrète perdue fait perdre la clé ; il n'existe aucune récupération.

#### 2. Signatures hybrides — `src/custody/signing.py`
Combine **Ed25519** (rapide, classique) et **ML‑DSA** (FIPS 204, post-quantique,
le successeur normalisé de CRYSTALS‑Dilithium). Deux règles rendent cela honnête :

- **Des étiquettes honnêtes.** Une signature n'est étiquetée `hybrid` que si une clé ML‑DSA a
  réellement été utilisée. Sans l'extra `pqc` installé, la signature produit une signature `ed25519`
  et le dit — elle ne revendique jamais une résistance quantique qu'elle n'a pas produite.
- **Hybride signifie ET.** Une signature `hybrid` n'est validée que si **les deux** composantes
  sont validées. Un vérificateur qui ne dispose pas de la bibliothèque post-quantique ne peut pas contrôler la moitié
  ML‑DSA et **échoue donc bruyamment** — il ne valide jamais silencieusement sur la seule moitié
  classique. (Un schéma qui accepte *l'une ou l'autre* signature ne vaut rien dès que la
  classique est cassée.)

Les clés privées sont chiffrées au repos en AES‑256‑GCM sous une clé dérivée par scrypt
lorsque l'application détient une phrase secrète (`OO_KEY_PASSPHRASE`, ou à défaut la phrase secrète
de la base de données) ; sinon elles sont écrites en `0600` en clair et le niveau de protection
est déclaré fidèlement comme `plaintext-0600`.

#### 3. Journal de possession — `src/custody/log.py`
Un registre SQLite **en ajout seul**. Chaque action (`ingest`, `access`, `export`,
`redact`, …) devient une entrée **chaînée par empreinte** à la précédente,
**signée** et **horodatée**. `verify()` revérifie l'ordre de la séquence, les maillons de la chaîne,
les empreintes de chaque entrée, les signatures et les condensés d'horodatage. Les exports se vérifient hors ligne :

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
```

REST : `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`,
`GET /api/custody/export`, `POST /api/custody/verify`.

Journalisation automatique à la collecte, sur option : définissez `OO_CUSTODY_ON_INGEST=1`
(`Config.custody_on_ingest`). Elle est **désactivée par défaut** — un choix probant explicite
avec un petit coût de signature par article, pas un comportement silencieux toujours actif.
Elle échoue en mode ouvert : une erreur de possession n'interrompt jamais la collecte.

#### 4. Ancrage — `src/custody/anchor.py`
Publie une racine de Merkle auprès d'un témoin externe, pour que sa date d'existence ne repose pas
sur votre propre horloge ou votre propre clé :

- **`local`** (par défaut, hors ligne) : enregistre la racine dans un registre d'ancrage local. Prouve
  seulement que *cet outil* l'a stockée — audit interne, pas preuve opposable à un tiers.
- **`opentimestamps`** (réseau) : ancre une empreinte opaque dans Bitcoin. Pas de portefeuille,
  pas de frais, vérifiable de façon indépendante. Se rabat sur une erreur explicite *indisponible*
  hors ligne — jamais un faux reçu.
- **`ethereum` / `ipfs` / `arweave`** : déclarés mais **non implémentés**. Ils
  refusent avec une erreur claire plutôt que d'être livrés comme des ébauches dont `verify()` renverrait
  toujours false.

REST : `POST /api/custody/anchor`, `GET /api/custody/providers`.

#### 5. Paramètres — `src/custody/settings.py` (configurables depuis l'interface)
Le comportement de possession est contrôlé par l'opérateur à l'exécution, pas seulement via les variables d'environnement ou le YAML.
Les préférences sont conservées dans `custody_settings.json` sous le dossier de données et se modifient
depuis le panneau **Chaîne de possession** de l'interface web (ou par l'API REST) :

- **`pqc_enabled`** — demander la signature hybride Ed25519 + ML‑DSA.
- **`anchoring_mode`** — `local` (par défaut) ou `opentimestamps`.
- **`auto_log_on_ingest`** — ajouter une entrée signée à chaque collecte réussie
  (vaut par défaut l'ancien indicateur `OO_CUSTODY_ON_INGEST` tant qu'aucune préférence n'est enregistrée).
- **`default_actor`** — étiquette d'acteur facultative pour les entrées journalisées automatiquement.

**Invariant d'honnêteté.** Un interrupteur est une *demande*, pas une garantie. L'API et l'interface
affichent toujours l'état **effectif** (préférence **ET** disponibilité de la bibliothèque) :
si la PQC est activée mais que `pqcrypto` n'est pas installé, le signataire reste en Ed25519 seul
et l'interface le dit — elle n'affiche jamais un voyant vert « hybride » qu'elle ne peut pas justifier. Il en va de même
pour OpenTimestamps sans l'extra `timestamping`.

REST : `GET /api/custody/settings`, `PUT /api/custody/settings`.

Un déroulé type de « preuve maximale » :

```
export evidence bundle  ->  take its merkle_root  ->  POST /api/custody/anchor
  (POST /api/reports/evidence)                         {merkle_root, "opentimestamps"}
```

---

### ⚠️ Vie privée : l'ancrage peut vous désanonymiser

Ancrer dans une blockchain **publique**, c'est **publier de façon permanente** une empreinte et un
horodatage. L'empreinte elle-même ne révèle rien du contenu, mais l'*acte* de
soumission révèle votre adresse IP et le moment de l'envoi aux opérateurs des calendriers ou des points RPC, et un portefeuille
on-chain approvisionné crée une piste financière. Pour quiconque a besoin d'anonymat :

- Préférez **local + OpenTimestamps** aux portefeuilles sur une chaîne publique.
- Faites passer les soumissions OpenTimestamps par **Tor** (par ex. `HTTPS_PROXY`).
- Ou renoncez entièrement à l'ancrage externe et appuyez-vous sur les horodatages locaux + la signature.

Confidentialité et ancrage sur une chaîne publique sont en tension. La configuration
par défaut (fournisseur local hors ligne, heure locale auto-déclarée) ne laisse rien fuiter.

---

### Ce que nous n'avons délibérément **pas** construit

- **Pas de faux TSA RFC‑3161.** Renvoyer `datetime.now()` et l'appeler « horodatage
  de confiance » relève du théâtre. Utilisez OpenTimestamps (réel) ou local (honnêtement étiqueté).
- **Pas de signatures hybrides à sémantique OU.** Voir « Hybride signifie ET » ci-dessus.
- **Pas de démon d'intégrité tournant en permanence en arrière-plan, pas de stockage de clés non chiffré présenté
  comme « chiffré ».** Les clés disent comment elles sont protégées ; la vérification se fait à la demande.

### Le modèle de menace en un paragraphe

L'outil fonctionne pour **un seul utilisateur local, en boucle locale uniquement, sous Qubes** (voir
`docs/SECURITY.md`). Le système de possession défend *l'intégrité et la provenance de
votre propre piste de preuves* contre une altération ultérieure et contre les accusations du type « vous avez inventé ça ».
Il ne protège pas, et ne peut pas protéger à lui seul, l'identité d'une source humaine, et un
ancrage naïf sur une chaîne publique peut activement *nuire* à l'anonymat — c'est pourquoi l'ancrage est
facultatif, hors ligne par défaut, et livré avec l'avertissement ci-dessus.


---

# Ce qui a été livré dans la 0.0.8 — le cycle de la feuille de route

> **Instantané historique, voir CLAUDE.md.** Ceci est un relevé à un instant donné du cycle 0.0.8 ;
> il n'est pas tenu à jour au fil des versions suivantes. `docs/ledger/OPEN_QUEUE.md` + `docs/ledger/`
> sont les sources de vérité vivantes pour ce qui a été livré depuis.

Tout ce qui suit est disponible dès maintenant, entièrement depuis l'interface du navigateur. Chaque fonctionnalité indique sa
limite honnête là où elle apparaît.

## Recettes d'enquête (Accueil) et le tableau de bord `/investigate`

Le briefing de l'Accueil surveille désormais votre propre corpus à la recherche de **signaux spatio-temporels** et fait apparaître des cartes —
toutes calculées localement, jamais depuis le réseau :

- **Promesses arrivées à échéance** — un article mentionnait une date qui était *dans le futur* au moment de sa
  publication ; cette date est maintenant arrivée. Le moment est venu de demander ce qui s'est réellement passé.
- **Flambée de guerre d’édition** — une page Wikipédia que vous suivez est modifiée à au moins 3× son propre rythme
  hebdomadaire récent ; sa trace publique est en mouvement.
- **Région devenue silencieuse** — un pays qui produisait régulièrement des articles pour vous a (presque)
  cessé. La mise en garde est intégrée : cela mesure *votre corpus*, pas la région — un flux
  mort ressemble exactement à un vrai silence, alors vérifiez d'abord les sources.
- **Des sources candidates attendent votre examen (Source candidates await review)** — voir *Candidates découvertes* ci-dessous.

Les cartes dotées d'un bouton **« Ouvrir l'enquête ↗ »** ouvrent un tableau de bord dédié **dans un nouvel
onglet du navigateur** (l'application principale continue de fonctionner ; ouvrez-en plusieurs à la fois). Le tableau de bord
assemble automatiquement les panneaux associés — l'article d'origine avec ses extraits de provenance, une
recherche de suivi pré-remplie, la liste des révisions enregistrées, le contexte de couverture —, reprend mot pour mot la
mise en garde de la carte tout en haut, et se termine par un bandeau **« Aller plus loin »** où chaque
suggestion est une action normale dont les paramètres sont affichés. Tout l'état de la page tient dans
son URL : mettez-la en favori, rouvrez-la, partagez-la entre vos propres machines.

Désactivez individuellement des recettes dans **Paramètres → Cartes**, où elles figurent désormais à côté de toutes
les autres pistes que cette application peut faire apparaître, regroupées par famille — le même interrupteur, appliqué à toutes.

## Annexe méthodologique

Le bouton **Annexe méthodologique** (sur la page de recherche et dans la rangée d'actions de la fenêtre
d'analyse) télécharge un document Markdown qui consigne *comment* votre sélection actuelle a été produite :
la version de l'application, la requête booléenne mot pour mot, le nombre de résultats, le contexte du corpus, et une
ligne de provenance par article (titre · source · date de publication · URL · SHA-256 du contenu). Il
consigne uniquement la sélection et n'affirme aucune conclusion — les affirmations analytiques restent les vôtres,
vérifiables au regard des lignes. Conçu pour les verdicts de vérification des faits et la relecture par les pairs ; associez-le à un
lot de preuves signé (Preuves & possession) lorsque vous avez besoin du document et de la preuve ensemble.

## Synthétiser les résultats

**Synthétiser les résultats** (sur la page de recherche et dans la fenêtre d'analyse) ouvre une fenêtre en
deux étapes : elle récupère un ensemble de candidats, vous montre les articles correspondants avec leurs métadonnées,
et vous permet de **choisir jusqu'à 20 membres** (les ≤20 premiers sont cochés d'avance) ; elle effectue ensuite UNE SEULE
passe du modèle local sur exactement ces articles et renvoie les faits communs, les points de désaccord et les
questions ouvertes, en citant les articles membres par leur numéro. Le résultat contient l'intégralité du corpus synthétisé,
avec les métadonnées et les liens de lecture de chaque article, ainsi que des options d'**export** (Copier, .md, ou
ouverture comme page autonome). La synthèse est enregistrée avec la provenance du modèle et de la version du prompt
pour chaque article membre, et la mise en garde l'accompagne : il s'agit d'une aide à la lecture portant uniquement sur les
membres listés — jamais d'un verdict. Nécessite Ollama, comme les autres fonctionnalités LLM ;
sans lui, vous obtenez un message honnête « injoignable ».

## Exports versionnés et graphe des citations

- Les exports lisibles par machine suivent désormais un contrat stable (`oo-export-1`) : les exports JSON sont
  des enveloppes auto-descriptives (schéma, version de l'application, date de génération, requête exacte, nombre) ;
  les colonnes CSV gardent leur ordre, avec la même provenance que les en-têtes HTTP `X-OO-*`. La dernière
  colonne, **Fetched From Host** (`fetched_host` en JSON), est l'hôte depuis lequel la page a réellement été
  récupérée après ses redirections ; elle est vide pour un article enregistré avant que cette information ne soit consignée.
- Le **graphe des citations** — quels domaines externes vos articles enregistrés citent, uniquement des décomptes,
  aucune crédibilité déduite — s'exporte en GraphML (`/api/links/export.graphml`) pour
  Gephi/yEd/NetworkX, ou en JSON.

## Journal d'exécution du planificateur et export vers un dossier local (Collecter)

Chaque exécution du planificateur — réussie ou non — ajoute une ligne à un journal d'exécution local et vérifiable
(`scheduler_runs.jsonl`), pour que le corpus puisse répondre à « qu'est-ce qui a tourné pendant mon absence ? ». En option,
indiquez un chemin d'**Export vers un dossier local** dans la carte du planificateur de Collecter : chaque exécution écrit alors le
delta des nouveaux articles sous forme de fichier JSON enveloppé dans ce dossier local, que votre propre chaîne de traitement peut
surveiller. Vide = désactivé (par défaut) ; rien de nouveau = aucun fichier.

## Candidates découvertes (Sources)

L'application suggère désormais des sources d'elle-même — **hors ligne uniquement** : des domaines que vos articles enregistrés
citent de façon répétée, et des médias du catalogue fourni pour les pays que votre corpus couvre peu.
Les suggestions sont mises en attente, jamais appliquées : chacune porte ses éléments probants dans le panneau **Candidates
découvertes** (Paramètres → Avancé → Sources), les exécutions sont plafonnées par le budget de découverte du planificateur et
consignées dans le journal d'exécution, et une carte de l'Accueil vous signale quand des candidates attendent votre examen.
**Promouvoir (Promote)** crée une source *désactivée* qu'il vous reste à activer ; **Écarter** est mémorisé
et la source n'est plus jamais suggérée. La recherche par sujet propulsée par DuckDuckGo reste séparée, **désactivée par
défaut**, et verrouillée derrière Paramètres → Avancé → Sécurité (voir ci-dessous).

## La découverte externe par sujet est facultative (Paramètres → Avancé → Sécurité)

*Découverte par sujet* est la seule fonctionnalité qui **envoie une requête en texte libre à un moteur
de recherche** : elle envoie votre requête de sujet à DuckDuckGo. (Les autres actions en ligne — collecte,
récupération de données de marché ou de statistiques, téléchargements de modèles Ollama, OpenTimestamps — sont chacune soumises à consentement et nommées elles aussi ;
celle-ci est la seule qui transmet une requête que vous avez tapée.) Elle est **désactivée par défaut** et
refuse avec un message
honnête tant que vous n'avez pas activé **Paramètres → Avancé → Sécurité → Découverte externe par sujet** (« Votre requête
quitte cette machine »). La découverte de flux RSS pour les sources que vous avez ajoutées vous-même reste sur la
voie locale de récupération éthique et n'est pas concernée.

## Langues

L'interface est désormais livrée avec des **traductions complètes en 12 langues** (English, العربية, বাংলা,
Deutsch, Español, Français, हिन्दी, Bahasa Indonesia, 日本語, Português, Русский, 中文),
y compris la mise en page de droite à gauche pour l'arabe. Choisissez la vôtre dans le sélecteur de langue ; les
traductions sont des premières ébauches générées par machine — les corrections sont des contributions bienvenues
(voir `docs/ARCHITECTURE.md` → Internationalisation).
