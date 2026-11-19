<!-- fr: Translation of docs/GOVERNANCE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 7 of 7 headings. Corrections are welcome as a pull request. -->

# Gouvernance et usage acceptable

Open Omniscience est un outil pour **demander des comptes au pouvoir** en aidant les gens à voir
honnêtement la *structure* de l'information publique. Parce que cette capacité est puissante, ce
document énonce clairement à quoi sert l'outil, les lignes qu'il ne franchira pas et comment il
entend rester digne de confiance en grandissant. Cela fait partie de l'éthique du projet, et non
d'une réflexion après coup.

## À quoi il sert

- **Journalisme d'investigation et recherche d'intérêt public** sur les médias, institutions,
  marchés et textes de loi *publiés* — en faisant apparaître une structure mesurable (concentration
  de la propriété, coordination/écho, nouveauté, cadrage, évolution dans le temps) qu'un humain juge.
- **Protection des sources et reproductibilité** — local d'abord, utilisable hors ligne, avec une
  provenance qui rend toute altération visible, afin que les conclusions puissent être défendues. La
  piste de chaîne de traçabilité, chaînée par hachage et signée, est **facultative** (désactivée par
  défaut — elle ajoute un petit coût de signature par article) : activez-la dans
  **Paramètres → Chaîne de possession → « Journalisation automatique à l'ingestion »**
  (ou `OO_CUSTODY_ON_INGEST=1`) lorsque l'intégrité probatoire compte pour une affaire. En attendant,
  la provenance accompagne quand même chaque article (source, heure de capture, empreinte du
  contenu) et des lots de preuves signés peuvent être produits à la demande.

## Lignes rouges du double usage (absentes par construction, non configurables)

Les mêmes techniques qui révèlent une opération d'influence coordonnée pourraient, entre de
mauvaises mains, être dirigées contre des personnes ordinaires. La ligne qui fait de cet outil un
instrument de *responsabilité* et non un outil de *surveillance* est précise, et elle est tenue
dans l'**architecture**, pas dans un réglage qu'un utilisateur pourrait basculer :

1. **Aucun suivi de particuliers.** L'outil analyse des *sources publiées* (médias, institutions,
   documents publics). Il ne profile **pas** de personnes privées, et `src/compliance/gdpr.py` en
   est le garde-fou. La notoriété mesure la *couverture de personnalités publiques dont on parle
   déjà* — l'attention, jamais l'importance ni le mérite.
2. **Aucune identification biométrique.** Aucune reconnaissance du visage, de la voix ou de la
   démarche. Jamais.
3. **Aucune ingestion de canaux privés.** Pas de messages privés, de flux privés, de messages
   interceptés ni de données non publiques. Le corpus est constitué de sources auxquelles
   l'utilisateur peut accéder légalement et éthiquement.
4. **Aucun verdict automatisé.** Pas de score de vérité, de crédibilité ou de « confiance », pas
   d'étiquette « biaisé »/« faux ». L'outil fait apparaître des *mesures avec méthode + mise en
   garde* ; l'humain conclut. (Imposé dans le code : `assert_no_score_fields`.)
5. **Aucun serveur central, aucun compte, aucune télémétrie.** Rien ne quitte la machine de
   l'utilisateur hormis les requêtes qu'il dirige. Il n'existe aucun pot de miel de données
   d'utilisateurs à saisir ou à réclamer par voie judiciaire.
6. **Aucun filtrage ni déclassement silencieux des sources.** Les faits de couverture sont
   *montrés* ; toute désamplification est appliquée par l'utilisateur, signalée et réversible —
   montrer, jamais imposer.

Elles sont imposées autant que le code le permet : un test d'intégration continue
(`tests/test_repo_invariants.py::test_red_lines_not_crossed`) fait échouer la compilation si des
capacités interdites (reconnaissance biométrique, suivi d'individus) apparaissent dans la base de
code. Un test est un fil de détente, pas une preuve — la vraie garantie, ce sont la culture et la
relecture.

## Posture juridique et éthique

- Un **miroir de recherche**, pas la source faisant autorité, et **pas un conseil juridique** ;
  chaque enregistrement renvoie à son origine.
- **Accès éthique** par défaut : robots.txt en échec fermé, limites de débit par hôte, un
  User-Agent qui s'identifie, attribution et provenance enregistrées. (Un utilisateur peut activer
  la récupération *Protégée* — proxy + UA générique, sauf pour les requêtes Wikipédia, Wikidata et
  de dumps que l'application adresse elle-même à Wikimedia, dont la politique d'API demande à chaque
  outil de se nommer — pour protéger une source ou se protéger lui-même lorsqu'il enquête sur une
  cible puissante ; c'est le devoir journalistique de protection des sources, assumé délibérément
  et documenté, jamais le comportement silencieux par défaut.)
- **Respecter les licences et le droit d'auteur** ; enregistrer la provenance et le minimum
  nécessaire ; honorer les obligations de protection des données propres à chaque juridiction.

## Indépendance et financement

L'outil est délibérément **peu coûteux à faire fonctionner** (local, sans infrastructure) afin de
pouvoir rester **indépendant**. Si le projet accepte un jour un financement, il évitera d'être
capturé par un bailleur ou un programme unique, gouvernera ses décisions de manière transparente et
ne pliera jamais la définition de la « désinformation » au gré d'un commanditaire. Le choix le plus
politique que fait ce projet est de rester petit, local et impossible à capturer.

## Résistance aux abus

Aucun outil ne peut empêcher tous les abus, et nous ne prétendrons pas le contraire. Notre
résistance est structurelle : les lignes rouges ci-dessus, la conception locale d'abord (pas de
données centrales à exploiter à grande échelle), le refus de rendre des verdicts et l'ouverture
(chacun peut inspecter, forker et auditer). Si vous pensez que le projet est poussé au-delà d'une
ligne rouge, ouvrez un ticket — cette possibilité de contestation est précisément le but.

## Comment les décisions sont prises (intention)

Aujourd'hui, c'est un projet jeune avec un seul mainteneur. Avant une alpha publique `0.1`, nous
prévoyons : une **revue externe de sécurité et d'éthique**, une évolution vers une **gouvernance à
plusieurs mainteneurs** avec une prise de décision transparente, et une **charte de contribution**
qui engage les contributeurs à respecter les lignes rouges. D'ici là, ce document est l'engagement
de référence.
