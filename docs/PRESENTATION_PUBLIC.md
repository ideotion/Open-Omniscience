# Open Omniscience — Présentation grand public

> **Une plateforme libre, éthique et locale d'aide à l'enquête journalistique.**
> Document de présentation destiné au grand public — sans prérequis technique.

---

## En une phrase

**Open Omniscience est un logiciel libre qui aide les journalistes d'investigation
à rassembler en un seul endroit une grande quantité d'informations publiques, à les
fouiller intelligemment, et à prouver d'où elles viennent — le tout en restant sur
leur propre ordinateur, sans rien envoyer à personne.**

---

## 1. Le problème que l'on cherche à résoudre

Imaginez le travail d'un journaliste d'investigation aujourd'hui.

Les informations utiles à une enquête sont **éparpillées partout** : des centaines de
sites d'actualité, des fils d'information (les « flux RSS »), des lettres d'information
par e-mail, des données économiques… Aucune personne seule ne peut tout lire, tout
mémoriser, et surtout **faire le lien** entre un article publié au Japon, un mouvement
de prix sur une matière première, et un communiqué reçu par courriel trois semaines
plus tôt.

À cela s'ajoutent deux difficultés bien réelles :

- **La confidentialité.** Un journaliste protège ses sources. Confier ses recherches à
  un service en ligne (un « nuage », ou *cloud*), c'est risquer que ces recherches
  soient lues, conservées, ou réclamées par un tiers.
- **La preuve.** Pour publier — ou pour se défendre devant un tribunal — il ne suffit
  pas d'avoir une information : il faut pouvoir **prouver d'où elle vient** et qu'elle
  n'a pas été modifiée entre-temps.

Open Omniscience est né pour répondre à ces trois besoins à la fois :
**rassembler**, **fouiller**, et **prouver** — sans jamais sacrifier la
confidentialité.

---

## 2. L'idée en une image

Pensez à Open Omniscience comme à une **immense bibliothèque privée et personnelle**,
posée entièrement sur votre propre table de travail.

```
   Des milliers de sources          Une seule bibliothèque,            Vous, qui posez
   d'information publiques    ─────▶  rangée et étiquetée,       ─────▶  vos questions
   (sites, flux, e-mails…)           qui n'oublie jamais d'où              et obtenez
                                     vient chaque document                 des réponses
                                                                            traçables
```

1. Le logiciel va **chercher** des informations publiques, poliment et légalement.
2. Il les **range** toutes ensemble dans une seule base, en notant pour chacune
   *d'où elle vient, quand elle a été récupérée, et son « empreinte »* (une sorte de
   sceau numérique qui garantit qu'elle n'a pas été altérée).
3. Vous pouvez ensuite **interroger** cette bibliothèque, faire des recoupements, et
   exporter un dossier dont chaque pièce est **vérifiable**.

Et tout cela vit **sur votre machine** : rien ne part vers un serveur extérieur.

---

## 3. Ce que le logiciel sait faire aujourd'hui

> 🟢 Les fonctions ci-dessous **existent réellement et sont testées**. Open Omniscience
> en est à une version **0.0.6 (pré-alpha)** : un cœur solide, sur lequel d'autres
> fonctionnalités viendront s'ajouter.

### a) Collecter, mais avec des bonnes manières

Le logiciel récupère des articles depuis des sites web ou des flux d'actualité. La
particularité, c'est qu'il le fait **éthiquement** :

- Il respecte le fichier `robots.txt` de chaque site — c'est le panneau « entrée
  autorisée / interdite » que les sites affichent à l'intention des robots. En cas de
  doute, **il s'abstient** (on dit qu'il « échoue en se fermant » : dans le doute, il ne
  prend rien).
- Il **ralentit volontairement** pour ne pas surcharger les sites qu'il visite.
- Il s'identifie honnêtement et ne contourne **jamais** un péage (*paywall*) ni un mot
  de passe. Uniquement de l'information **publique**.

### b) Tout ranger au même endroit, proprement

Chaque document récupéré est nettoyé (on ne garde que le vrai texte de l'article, pas
les menus ni les publicités) puis enregistré dans une base de données unique. Le
logiciel **ne stocke jamais deux fois le même article** et conserve pour chacun sa
**provenance** : la source, l'adresse d'origine, l'heure de récupération et son
empreinte numérique.

### c) Chercher comme un professionnel

La recherche n'est pas un simple « ctrl+F ». Vous pouvez combiner des critères :

- **ET / OU / SAUF** (par exemple : *« élection » ET « financement » SAUF « sport »*),
- des **expressions exactes** entre guillemets,
- des **parenthèses** pour grouper les conditions, comme en mathématiques.

Cela permet de retrouver l'aiguille dans la botte de foin, avec précision.

### d) Exporter votre travail

Les résultats s'exportent en formats **CSV** (pour un tableur) ou **JSON** (pour un
autre logiciel), fidèles à ce que vous avez sélectionné.

### e) Une interface simple, hors-ligne

Le logiciel s'utilise dans votre navigateur web habituel, mais **sans Internet** : il
tourne uniquement sur votre ordinateur (à l'adresse `127.0.0.1`, qui veut dire
« ici, chez moi »). Aucune page extérieure n'est chargée.

---

## 4. Les fonctions avancées (déjà présentes, à éprouver sur le terrain)

Au-delà de ce cœur, la version 0.0.6 intègre des briques plus avancées, conçues selon le
même principe : **honnêteté et confidentialité d'abord**.

- **Une intelligence artificielle… locale.** Le logiciel peut résumer des textes grâce
  à une IA qui tourne **entièrement sur votre machine** (via un outil appelé *Ollama*).
  Vos documents ne sont **jamais** envoyés à une entreprise d'IA. Et si l'IA n'est pas
  installée, le logiciel le dit franchement plutôt que d'inventer un résultat.
- **Le recoupement avec des données économiques.** Une première brique permet de relier
  l'évolution du prix d'une matière première à l'actualité, avec un **vrai calcul
  statistique** (et non un chiffre inventé pour faire joli).
- **La surveillance de sources.** Le logiciel peut signaler quand une source « tombe »
  ou quand quelque chose d'anormal apparaît.
- **L'intégration des e-mails.** Des courriels (boîtes IMAP) peuvent rejoindre la même
  bibliothèque consultable.
- **Le dossier de preuve « scellé ».** Vous pouvez exporter un dossier d'enquête
  **signé numériquement** et **infalsifiable** : n'importe qui peut ensuite vérifier,
  avec un petit outil fourni, qu'aucune pièce n'a été modifiée. C'est ce qui rend une
  preuve **défendable**, y compris sur le plan juridique.

---

## 5. Nos engagements : ce qui rend ce projet différent

Ces principes ne sont pas des slogans : ce sont des **règles de construction**. Quand
le code les enfreint, c'est considéré comme un défaut à corriger.

| Engagement | Ce que cela signifie concrètement |
|---|---|
| 🏠 **Local d'abord** | Tout se passe sur votre ordinateur. Le logiciel fonctionne même sans Internet (sauf au moment précis où il va chercher de l'information). |
| 🔒 **Respect de la vie privée** | Aucune donnée ne quitte votre machine. Aucun mouchard, aucune statistique envoyée. |
| 📖 **100 % libre et ouvert** | Le code est public (licence GNU GPLv3). N'importe qui peut l'inspecter, le vérifier, le modifier. Rien n'est caché. |
| 🤝 **Éthique par construction** | On respecte les règles des sites, on ne contourne jamais un péage, on ne collecte que du public. Dans le doute, on s'abstient. |
| ⚖️ **Des résultats défendables** | Pas de chiffre inventé. Un indice de confiance n'existe que s'il provient d'une vraie méthode. La traçabilité est garantie. |
| 🔎 **La transparence avant tout** | Si une fonction ne marche pas (IA absente, source bloquée…), le logiciel le **dit clairement**. Il ne fait jamais semblant. |

---

## 6. Une honnêteté revendiquée

C'est un point dont l'équipe est fière, et qui mérite d'être expliqué simplement.

Dans des versions antérieures, certaines fonctions « impressionnantes » (détection de
*deepfakes*, de propagande, de robots…) **faisaient seulement semblant de fonctionner** :
elles affichaient des scores qui avaient l'air sérieux, mais qui n'étaient pas réels.

Plutôt que de continuer à les présenter comme fiables, l'équipe les a **mises de côté,
ouvertement et par écrit** (« mises en quarantaine »). Pour un outil destiné au
journalisme et potentiellement à la justice, **une fausse preuve est la pire des
choses**. Mieux vaut une fonction de moins, mais en laquelle on peut avoir confiance.

> En résumé : **Open Omniscience préfère vous dire « je ne sais pas faire » plutôt que
> de vous mentir.**

---

## 7. Pour qui, et pour quoi faire ?

**Public visé :** un journaliste d'investigation, un chercheur ou un analyste,
travaillant souvent seul ou en petite rédaction, soucieux de protéger ses sources.

Quelques exemples d'usage :

- *« Rassembler automatiquement tout ce qui concerne mon enquête, depuis de nombreuses
  sources, au même endroit. »*
- *« Tout fouiller ensemble pour trouver des liens invisibles à l'œil nu. »*
- *« M'aider à digérer d'énormes volumes de texte — sans envoyer mes données à
  quiconque. »*
- *« Prouver d'où vient cette information et que je ne l'ai pas trafiquée. »*

---

## 8. Ce que le projet n'est PAS

Pour éviter tout malentendu, disons-le clairement. Open Omniscience **n'est pas** :

- un outil pour **contourner les péages** ou voler des mots de passe ;
- un logiciel d'**espionnage** ou de surveillance des particuliers ;
- un **service en ligne** : rien n'est hébergé « dans le nuage », pas d'IA distante ;
- un outil **magique** : il aide à organiser et recouper, mais le travail
  journalistique — vérifier, comprendre, juger — reste **humain**.

---

## 9. Où en est le projet ?

- **Version actuelle : 0.0.6 (pré-alpha).** Le cœur — collecter, ranger, chercher, exporter —
  **fonctionne et est testé de bout en bout**.
- Les briques avancées (IA locale, données économiques, surveillance, e-mails, dossiers
  signés) **sont en place** et seront éprouvées sur des cas réels.
- Le développement se poursuit de façon **progressive et honnête** : chaque
  fonctionnalité n'est annoncée que lorsqu'elle marche réellement.

**Licence :** GNU GPLv3 (libre).
**Auteur :** Ideotion.

---

## 10. En une diapositive de conclusion

> **Open Omniscience, c'est une bibliothèque d'enquête privée, posée sur votre table.**
>
> Elle rassemble l'information publique du monde entier au même endroit, vous laisse la
> fouiller avec précision, et vous permet de prouver d'où vient chaque pièce — **sans
> jamais que vos recherches ne quittent votre ordinateur**.
>
> Libre, éthique, local, et honnête : un outil au service du droit du public à être
> informé.

---

*© 2026 Ideotion — conçu pour le journalisme d'investigation, en toute honnêteté.*
