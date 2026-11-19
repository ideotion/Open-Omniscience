<!-- fr: Translation of docs/CONTRIBUTING.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 15 of 15 headings. Corrections are welcome as a pull request. -->

# Contribuer

Merci de votre aide. Le principe directeur est l'**honnêteté** : une fonctionnalité doit faire ce
qu'elle annonce, sinon elle n'est pas livrée. Pas de résultats fabriqués, pas de faux scores de
confiance, pas de dégradation silencieuse — voir [DESIGN.md](DESIGN.md) §3.

## Installation

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q          # full suite, a few minutes
```

`pyproject.toml` reste la source unique de vérité pour les dépendances (nous installons la
dernière version au-dessus des planchers afin que l'intégration continue détecte tôt les ruptures
en amont). Pour une **installation reproductible / de publication**, il existe un fichier de
verrouillage épinglé par hachage, dérivé de celui-ci :

```bash
pip install -r requirements.lock          # exact, hash-verified core + analysis pins
# regenerate after a dependency change:
pip-compile --generate-hashes --extra analysis -o requirements.lock pyproject.toml
```

**Ceci est intégré à `./install.sh`, ce n'est pas seulement une commande à lancer à la main.** Le
chemin d'installation en ligne (`pip_install()`) utilise automatiquement `requirements.lock`
chaque fois qu'il est présent, qu'il a été généré pour le Python que vous exécutez et qu'il couvre
chaque composant demandé (`OO_COMPONENTS`) — vérifié par rapport à l'en-tête
`pip-compile ... --extra=...` du fichier de verrouillage lui-même, jamais maintenu à la main.
Lorsque l'une de ces conditions n'est pas remplie (le fichier de verrouillage est périmé pour
votre Python, ou demande un composant avec lequel il n'a pas été généré, ou un épinglage ne se
résout pas sur cette plateforme), il revient à la résolution ordinaire fondée sur les planchers,
`pip install -e ".[...]"`, avec un message visible expliquant pourquoi le chemin audité n'a pas été
utilisé — `OO_USE_LOCK=0` désactive le fichier de verrouillage sans condition. **Tel que livré, le
fichier de verrouillage ne couvre que `--extra analysis`**, alors que l'ensemble de composants par
défaut de `install.sh` est `analysis,compression,columnar` — donc une exécution par défaut, sans
surveillance, de `./install.sh` revient aujourd'hui à la résolution fondée sur les planchers
(compression/columnar ne sont pas couverts par le fichier de verrouillage). Lancez
`OO_COMPONENTS=analysis ./install.sh` pour exercer le chemin audité dans son état actuel, ou
élargissez la couverture du fichier de verrouillage avec `pip-compile --extra analysis --extra
compression --extra columnar ...` pour que le chemin d'installation par défaut repose lui aussi
sur le verrouillage.

Le **paquet hors ligne / isolé du réseau** (`scripts/build_offline_bundle.sh`, utilisé par le
chemin hors ligne `--no-index` de `install.sh` pour la cible Qubes/Tails) **n'est pas encore relié
au fichier de verrouillage** — il résout encore à neuf à partir des planchers de `pyproject.toml` à
chaque construction. C'est une lacune connue et ouverte, pas un oubli : rendre le paquet hors ligne
lui aussi fondé sur le verrouillage (`pip download --require-hashes -r requirements.lock`, en
gardant la résolution fondée sur `$SPEC` comme solution de repli pour les extras que le fichier de
verrouillage ne couvre pas) est suivi comme travail ultérieur.

## Méthode de travail

- **Python 3.13**, un seul `pyproject.toml` (pas de requirements.txt).
- Lint/formatage avec **ruff** ; vérification des types avec **mypy** :
  `make lint && make typecheck`.
- Chaque modification se termine au vert : `make check` (ruff + pytest). Ajoutez un test de
  comportement pour tout nouveau comportement ; corrigez ou mettez en quarantaine — ne laissez pas
  de code à moitié fonctionnel dans le chemin d'import.
- Faites des commits par petits incréments honnêtes, avec des messages qui disent *quoi et
  pourquoi*.
- Les changements de schéma passent par Alembic (`alembic revision --autogenerate`) ;
  l'intégration continue lance `alembic check` pour détecter un écart entre modèle et migration.

## Le registre des livraisons : un fichier par ligne

N'ajoutez rien à la fin de `docs/ledger/shipped.csv`. La vérification de fusion de GitHub ignore la
règle `merge=union` du fichier, si bien qu'une ligne ajoutée par chaque PR mettait toutes les PR
ouvertes en conflit après chaque fusion. Ajoutez plutôt UN nouveau fichier :

    python scripts/ledger_shipped.py new --date 2026-09-30 --area tests --item "..." \
        --status "shipped (draft)" --refs "PR #1240" --key-paths "src/a.py; tests/b.py" --summary "..."

Cela écrit `docs/ledger/shipped.d/<date>-<slug>.csv` (l'en-tête du registre plus une ligne). Aucune
autre PR ne peut entrer en conflit avec un fichier qu'elle ne touche pas.
`python scripts/ledger_shipped.py check` vérifie chaque fragment ; les notes de version et les
tests d'invariants du dépôt lisent d'abord `shipped.csv`, puis les fragments. `ledger_shipped.py
fold` ajoute les fragments à `shipped.csv` en binaire et les supprime ; il est réservé au mainteneur
ou à une publication, jamais à une PR de fonctionnalité. `refs` doit être le vrai numéro de PR, pas
`PR pending` (un test échoue sinon).

## Leçons et entrées du journal des livraisons : un fichier chacune

La même convention couvre les deux grandes archives. Une leçon est UN fichier,
`docs/ledger/lessons.d/<date>-<slug>.md` (`python scripts/lessons.py --new SLUG`) ; une entrée
verbatim du journal des livraisons est UN fichier, `docs/ledger/shipped_log.d/<date>-<slug>.md`
(`python scripts/ledger_fold.py new-log SLUG`). N'ajoutez jamais rien à `LESSONS.md` ou
`SHIPPED_LOG.md` et ne modifiez jamais `_LESSONS_LINE_CEILING` : chaque PR qui le faisait entrait en
conflit avec toutes les autres. Un fragment commence par `## <date> — title`, se termine par un
saut de ligne et est en UTF-8 avec des fins de ligne LF ; une leçon (pas une entrée du journal des
livraisons) n'a pas de second titre et reste sous 200 lignes (cela borne la taille d'une entrée) ;
`python scripts/ledger_fold.py check` (et `tests/test_ledger_fragments.py`) la valide, refuse les
marqueurs provisoires `#NNNN` et `PR pending`, et `lessons.py <words>` cherche aussi dans les
fragments. `ledger_fold.py fold` les fusionne dans les archives lors d'une publication et n'est
jamais destiné à une PR de fonctionnalité.

## Fichiers de langue et conflits de fusion

Les 12 fichiers `src/static/locales/*.json` sont maintenus **triés** (`_meta` d'abord, puis les clés
dans l'ordre des points de code), de sorte que deux PR qui ajoutent des chaînes les insèrent à des
endroits différents et fusionnent proprement. Après avoir ajouté des chaînes, lancez
`python scripts/locales_merge.py` ; il trie les fichiers et les vérifie (`--check` ne fait que
vérifier ; `tests/test_locales_merge.py` échoue sur des clés non triées ou en double).

Si `git merge origin/main` laisse des marqueurs de conflit dans les fichiers de langue, lancez le
même script : il garde les deux côtés de chaque bloc, trie, et s'arrête en nommant la clé si les
deux côtés ont donné à une même clé des textes différents (une vraie contradiction à trancher).
`docs/ledger/shipped.csv` est en `merge=union` dans `.gitattributes`, ce que respecte un
`git merge` local mais pas la fusion web de GitHub ni le bouton de mise à jour de branche : fusionnez
main localement, puis vérifiez l'absence de lignes `(date, area, item)` en double.

## Normes

- Provenance partout : les données stockées portent source + horodatage + empreinte.
- Tout nombre montré à un utilisateur doit provenir d'une méthode réelle avec une incertitude
  énoncée (`src/analysis`), jamais d'une constante.
- L'ingestion passe par l'unique récupérateur éthique (robots en échec fermé, débit limité).
- Le code fabriqué ou mort va dans `quarantine/` (documenté), pas dans `src/`.

## Code de conduite

En participant, vous acceptez de respecter le [Code de conduite](CODE_OF_CONDUCT.md)
(Contributor Covenant 2.1). Signalez vos préoccupations en privé à open-omniscience@ideotion.com.

## Licence

Les contributions sont sous **GPL-3.0-or-later** (voir [LICENSE](../LICENSE)).

---

# Politique de versionnage

Comment le projet est versionné — une maturité délibérément sous-estimée.

**Dans cette partie :**
- [Politique de versionnage](#politique-de-versionnage)


---

## Politique de versionnage

> **Nous sous-estimons délibérément la maturité. L'honnêteté plutôt que l'esbroufe.** Mieux vaut
> qu'un utilisateur soit agréablement surpris que trompé. Le numéro de version est une promesse sur
> la *maturité*, et nous gardons cette promesse prudente.

### La source unique de vérité

La version se trouve à **un seul endroit : `pyproject.toml` (`[project] version`)**. Tout le reste
en découle :

- L'application en cours d'exécution la lit dans les métadonnées du paquet installé
  (`importlib.metadata.version("open-omniscience")`) — ainsi `/api/health`, le `version=` de l'API
  et l'interface rapportent tous automatiquement la version *réellement* installée.
- Aucun autre code n'inscrit une version en dur. Les tests vérifient par rapport aux métadonnées du
  paquet, pas à une chaîne (voir `tests/test_api_search.py`).
- Le `README.md` à la racine du dépôt énonce la version une fois, dans son en-tête, et un garde-fou
  d'intégration continue vérifie qu'elle correspond au paquet
  (`tests/test_repo_invariants.py::test_readme_version_matches_package`).

**Pour changer de version, modifiez uniquement `pyproject.toml`**, mettez l'en-tête du README en
accord (le garde-fou l'impose), puis lancez `pip install -e .` pour rafraîchir les métadonnées.

**N'étiquetez `vX.Y.Z` que sur un commit dont le `pyproject.toml` indique déjà `X.Y.Z`.** Le flux de
publication (`.github/workflows/release.yml`) refuse toute autre étiquette avant de construire quoi
que ce soit, de sorte qu'une étiquette posée avant le changement de version publie une version sans
wheel, sdist ni sommes de contrôle. Le premier `v0.4.0` a été posé ainsi le 2026-09-28 ; la version
a été fixée ensuite et l'étiquette déplacée dessus (`docs/product/RELEASE_0.4_GATE.md` ligne G).
**Déplacer une étiquette nécessite git :** le site web de GitHub ne peut ni supprimer ni déplacer
une étiquette, et une version publiée là-bas réutilise l'étiquette existante sans lancer le flux.
Sans clone local capable de pousser, ouvrez un Codespace sur `main` et lancez
`git fetch origin && git tag -f vX.Y.Z origin/main && git push -f origin vX.Y.Z`. Supprimez d'abord
la version GitHub si le flux doit écrire les notes générées : il conserve les notes d'une version
existante et n'ajoute que les fichiers et les sommes de contrôle.

### L'échelle de maturité (où nous en sommes, où nous allons)

Le logiciel est jeune et encore en cours de validation, il reste donc **sous `1.0`** :

```
0.0.x  pre-alpha    the first, un-public pre-alpha iterations (0.0.4 .. 0.0.9).
0.x    alpha        ← we are here (0.5.0). Public, working, honestly-labelled — open
                     to feedback, but not yet consolidated (each cycle is still an
                     "honest about every limit, not finished" release, per the README
                     header — see it for the current cycle's exact status).
0.x    beta         once things consolidate (a deliberate, later maintainer call —
                     not implied by any particular `0.x` number crossing over from alpha).
1.0    release      an official, stable release.
```

Nous ne **sauterons pas** à un numéro de version qui suggère plus de maturité qu'il n'en existe
(par exemple, `0.2` ne signifie pas « fini à 20 % » ni « presque bêta » — c'est le décompte honnête
des cycles alpha jusqu'ici). Chaque cycle est une petite itération réelle — rien de plus n'est
revendiqué.

### Correspondance cycle ↔ version

Les cycles de développement (et leurs branches) portent le nom de la version qu'ils produisent, les
zéros de tête étant omis par souci de brièveté :

| Nom de branche / de cycle | Version du paquet |
|---|---|
| `0.04` | `0.0.4` |
| `0.05` | `0.0.5` |
| `0.06` | `0.0.6` |
| `0.07` | `0.0.7` |
| `0.08` | `0.0.8` |
| `0.09` | `0.0.9` |
| `0.1`  | `0.1.0` |  (la branche du cycle `0.09` a été renommée `0.09 → 0.1` au passage en alpha)
| `0.2`  | `0.2.0` |  (la branche du cycle `0.1` a été renommée `0.1 → 0.2` au passage en 0.2)
| `main` | `0.2.0` → `0.3.0` → `0.4.0` → `0.5.0` |  (la branche du cycle `0.2` a été renommée `0.2 → main` le 2026-07-15 — la branche par défaut est désormais définitivement `main`, et le nom de branche et la version sont indépendants ; `v0.2.0` a été étiquetée après la validation à l'échelle sur un corpus réel, `v0.3.0` a clos le cycle mesuré-et-vérifié, `v0.4.0` a clos le cycle des sources vivantes, et `main` indique désormais `0.5.0`, la version du bureau de l'enquêteur, étiquetée `v0.5.0`)

Ainsi, « la couche d'intelligence `0.06` » signifie « le travail livré dans `0.0.6` ». Quand vous
lisez un raccourci de cycle comme `0.05` dans la documentation, lisez-le comme `0.0.5`. Les PR
arrivent sur `main`, la branche du cycle actuel — et non sur l'un des anciens noms de branche
numérotés ci-dessus.

**Depuis la première alpha (`0.1.0`), la correspondance est cycle `0.N` ⇒ `v0.N.0`** — le cycle
`0.2` s'est clos avec `v0.2.0`, le cycle `0.3` avec `v0.3.0`, le cycle `0.4` avec `v0.4.0`, le
cycle `0.5` avec `v0.5.0` (la seule exception est le cycle consolidé `0.09`, qui a produit
`0.1.0`). Un cycle porte le nom de la version qui le clôt — les fichiers de jalon de publication le
disent dans leurs propres termes (`RELEASE_0.4_GATE.md` est « l'inventaire vérifiable pour clore le
cycle `0.4` ») — et un numéro de version peut être *fixé* en cours de cycle avant l'étiquette (par
exemple, `0.4.0` a été fixé le 2026-09-28, pour que l'étiquette y soit déplacée ; `0.5.0` a été fixé
dans la PR de bascule, et l'étiquette désigne son commit de fusion), ce qui explique que la date
d'un titre du journal des modifications et la date de son étiquette puissent différer.

### Pourquoi c'est important (le lien avec les valeurs)

Ce projet existe pour aider les gens à voir l'information honnêtement. Un outil qui surestimerait
sa propre maturité contredirait cela à la racine. Un versionnage prudent relève de la même
discipline que le reste de la base de code : **ne revendiquer que ce qui est réel, et le prouver.**
