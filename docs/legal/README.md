# Documents juridiques & de gouvernance — Open Omniscience

> ⚠️ **Avis important — modèles de travail, pas un avis juridique.** Les documents
> de ce dossier sont des **modèles (templates) de travail** fournis à titre informatif.
> Ils **ne constituent pas un avis ou une consultation juridique** et n'ont pas été
> validés par un professionnel du droit. Ils doivent être **relus, complétés, adaptés et
> validés par un juriste qualifié** avant toute publication. Les mentions entre crochets
> **[À COMPLÉTER : …]** et **[À VÉRIFIER : …]** signalent les informations restant à
> fournir ou à confirmer.

Ce dossier rassemble le cadre juridique et éthique d'**Open Omniscience** (« le
Logiciel »), un **logiciel libre** publié par **Ideotion** (« l'Éditeur ») sous licence
**GNU GPL v3**.

## Structure en couches

Le cadre est volontairement organisé en couches complémentaires, du plus formel au plus
moral :

| Document | Rôle |
|---|---|
| [`MENTIONS_LEGALES.md`](MENTIONS_LEGALES.md) | **Mentions légales** — identification de l'Éditeur, du directeur de la publication et de l'hébergeur du code source ; rappel qu'aucun serveur n'est exploité et qu'aucune donnée d'utilisateur n'est collectée. |
| [`CGU.md`](CGU.md) | **Conditions Générales d'Utilisation** — le document central : objet, acceptation, articulation avec la GPL v3, nature « en l'état » du Logiciel, responsabilités de l'Utilisateur, **transparence sur les sorties produites par l'IA**, exclusion de garantie, limitation de responsabilité, indemnisation, composants tiers, droit applicable. |
| [`POLITIQUE_DE_CONFIDENTIALITE.md`](POLITIQUE_DE_CONFIDENTIALITE.md) | **Politique de confidentialité (RGPD)** — l'Éditeur ne traite aucune donnée personnelle d'utilisateur et n'exploite aucun serveur ; l'Utilisateur est le **seul responsable de traitement** des données présentes dans les contenus qu'il collecte. |
| [`CHARTE_USAGE.md`](CHARTE_USAGE.md) | **Charte d'usage** (éthique / *acceptable use*) — finalité visée, **liste des usages interdits**, et engagements explicites de l'Utilisateur. Acceptée explicitement, en cohérence avec [`../ETHICS.md`](../ETHICS.md) et [`../GOVERNANCE.md`](../GOVERNANCE.md). |
| [`IMPLEMENTATION_NOTES.md`](IMPLEMENTATION_NOTES.md) | **Notes techniques** — comment le **mécanisme d'acceptation explicite** (consentement au premier lancement) est implémenté et comment finaliser son intégration (interface web + CLI). |

## La distinction essentielle : licence du **code** vs. conditions d'**usage**

- La **GNU GPL v3** régit le **code source** : les quatre libertés (exécuter, étudier,
  modifier, redistribuer), y compris **à des fins commerciales**. Ces documents
  **n'ajoutent aucune restriction** à cette licence et ne la conditionnent pas.
- Les présents documents régissent uniquement ce que la GPL v3 ne couvre pas :
  l'**usage du logiciel en fonctionnement**, ses **sorties** (notamment celles produites
  par l'IA), la **conduite** de l'Utilisateur, les **avertissements**, la **garantie**,
  la **responsabilité**, l'**indemnisation** et la **responsabilité des données**.
- **En cas de conflit** entre ces documents et la GPL v3 **au sujet de la licence du
  code**, **la GPL v3 prévaut**.

## Contact

Pour toute question : **open-omniscience@ideotion.com**.
