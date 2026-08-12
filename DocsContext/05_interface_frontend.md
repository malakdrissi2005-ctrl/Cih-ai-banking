# 05 — Interface Frontend & UI/UX : CIH AI Banking — Démonstration

> **Type de document** : Spécification UI/UX (référence visuelle, structurelle et de synchronisation du frontend) **Prérequis** : `01_projet_overview.md`, `02_architecture_multi_agents.md`, `03_stack_technique.md` **Rôle de ce document** : Définir l'unique application CIH AI Banking et ses deux rendus simultanés (mobile réel et adaptation desktop agrandie), les règles visuelles, la synchronisation totale de l'état, et l'architecture des composants. Ce document est la référence officielle utilisée par Claude Code pour implémenter le frontend ; toute décision non couverte ici doit être ajoutée au document avant d'être codée.

---

## 1\. Objectif fondamental

CIH AI Banking est **avant tout une application mobile**. Sur un ordinateur, la démonstration académique affiche simultanément :

1. à **gauche** : le véritable rendu mobile de l'application, interactif, dans un cadre de téléphone réaliste ;  
2. à **droite** : une **adaptation desktop agrandie de cette même application**, destinée à rendre la démonstration plus lisible.

La partie desktop n'est pas une application différente. Le téléphone n'est pas une image décorative : il est pleinement interactif. Les deux vues représentent en permanence exactement la même application, la même session, le même utilisateur, le même état d'authentification, le même écran actif, les mêmes données, la même conversation, le même agent actif et la même opération en cours (voir §5, synchronisation totale).

---

## 2\. Rôle des trois images de référence

### Image 1 — Connexion CIH

Définit l'identité visuelle **avant authentification** :

- fond en dégradé orange, rouge, bleu et violet ;  
- en-tête compact ;  
- titre « Bienvenue » ;  
- panneau sombre semi-transparent ;  
- champs identifiant et mot de passe ;  
- lien « Oublié ? » ;  
- option « Se souvenir de moi » ;  
- bouton orange « Connexion » ;  
- section « Nos services » en grille 2 × 2\.

### Image 2 — Dashboard CIH

Définit l'identité visuelle **après authentification** :

- fond blanc ;  
- en-tête compact ;  
- ligne orange fine ;  
- salutation orange ;  
- compte et solde centrés ;  
- bouton afficher/masquer le solde ;  
- grille de services 2 × 3 ;  
- icônes orange ;  
- séparateurs orange clair ;  
- transactions récentes ;  
- navigation inférieure.

### Image 3 — Téléphone \+ dashboard desktop

Définit **uniquement** la présentation dans le navigateur :

- téléphone à gauche ;  
- interface desktop à droite ;  
- les deux visibles simultanément ;  
- ensemble centré et compact ;  
- proportions professionnelles.

La marque, les couleurs, le logo, VISA et les données visibles sur cette image de référence ne sont en aucun cas repris : seule la disposition générale (position du téléphone, position du panneau desktop, composition centrée et compacte) est retenue.

---

## 3\. Identité académique (obligatoire)

| Élément | Valeur |
| :---- | :---- |
| Nom du projet affiché | `CIH AI Banking — Démonstration` |
| Mention obligatoire, visible en permanence | `Démonstration académique — aucune opération réelle` |

Interdictions strictes, sans exception :

- aucun logo officiel CIH ;  
- aucun logo VISA ni d'un autre réseau de paiement ;  
- aucune donnée bancaire réelle ;  
- aucun numéro provenant des captures de référence ;  
- aucun nom provenant des captures de référence ;  
- aucune opération réelle.

Toutes les données affichées (nom, numéro de compte, solde, transactions) sont fictives, générées pour la démonstration, et distinctes des valeurs visibles sur les images de référence.

---

## 4\. Affichage responsive (règles exactes)

- **largeur ≥ 900 px** : téléphone interactif à gauche \+ vue desktop agrandie à droite, affichés simultanément.  
- **largeur entre 640 px et 899 px** : vue desktop uniquement ; le téléphone décoratif est masqué.  
- **largeur \< 640 px** : application mobile uniquement, en plein écran, sans cadre de téléphone.

Règle de composition : conformément à l'image 3, l'ensemble « téléphone \+ panneau desktop » forme une composition centrée et compacte, avec une largeur maximale raisonnable pour le bloc entier, plutôt que d'étirer le panneau desktop jusqu'aux bords de la fenêtre. Aucun défilement horizontal ne doit apparaître, quelle que soit la largeur testée.

Le cadre du téléphone reste visible en permanence tant que la règle ≥ 900 px s'applique, **y compris lorsque la fenêtre de chat est ouverte** (voir §9, positionnement de la fenêtre de chat).

> **Implémentation technique** : ce seuil est appliqué en **CSS pur** (regles `.showcase-layout` / `.showcase-phone` / `.showcase-desktop`, voir `frontend/src/index.css`), jamais via une classe Tailwind `xl:` (1280 px par défaut) — un seuil CSS explicite reste fiable même lorsque la mise à l'échelle du système d'exploitation réduit la largeur CSS effective rapportée par le navigateur.

---

## 5\. Synchronisation totale de l'état

Une **source d'état unique**, partagée entre le panneau mobile et le panneau desktop, pilote l'intégralité de l'application. Aucune divergence n'est tolérée entre les deux panneaux, à aucun instant, sur aucun des éléments suivants :

- authentification ;  
- utilisateur ;  
- écran actif ;  
- navigation ;  
- solde ;  
- visibilité du solde ;  
- données ;  
- conversation ;  
- chat ouvert ou fermé ;  
- agent actif ;  
- virement ;  
- confirmation ;  
- OTP ;  
- tentatives ;  
- résultat ;  
- déconnexion.

Une action effectuée sur le PC doit apparaître **immédiatement** dans le téléphone. Une action effectuée dans le téléphone doit apparaître **immédiatement** sur le PC. Il n'existe aucun réglage, aucune donnée et aucun état d'interface qui puisse être différent d'un panneau à l'autre.

---

## 6\. Palette avant authentification

| Rôle | Nom | Teinte / valeur | Usage |
| :---- | :---- | :---- | :---- |
| Dégradé de fond, point 1 | `auth-gradient-orange` | orange chaud | Coin supérieur du dégradé |
| Dégradé de fond, point 2 | `auth-gradient-red` | rouge-orangé | Zone haute-milieu du dégradé |
| Dégradé de fond, point 3 | `auth-gradient-blue` | bleu profond | Zone basse-milieu du dégradé |
| Dégradé de fond, point 4 | `auth-gradient-violet` | violet sombre | Coin inférieur du dégradé |
| Panneau d'authentification | `auth-panel` | noir/gris très sombre, semi-transparent | Panneau contenant le formulaire |
| Accent d'action | `cih-orange` | `#F26522` | Bouton « Connexion », liens actifs |

---

## 7\. Palette après authentification

| Rôle | Nom | Teinte / valeur | Usage |
| :---- | :---- | :---- | :---- |
| Fond principal | `surface-bg` | blanc | Fond de tout l'écran |
| Séparateur | `cih-orange` (fin) | `#F26522` | Ligne sous l'en-tête |
| Salutation | `cih-orange` | `#F26522` | Texte « Bonjour {prénom} \! » |
| Texte principal | `text-primary` | gris foncé | Libellés, titres |
| Information secondaire | `cih-blue` | `#005CA9` | Numéro de compte masqué, liens secondaires |
| Icônes d'action | `cih-orange` | `#F26522` | Icônes de la grille de services |
| Séparateurs secondaires | `cih-orange-light` | orange clair | Séparateurs entre blocs |
| Cartes | `card-surface` | blanc, bordure grise très claire | Carte de compte, transactions |

Règle impérative : après authentification, aucun grand fond sombre et aucun dégradé de grande surface ne réapparaissent. L'écran reste clair, sobre, de style bancaire, dans les deux panneaux.

---

## 8\. Stack technique et design tokens

| Élément | Valeur |
| :---- | :---- |
| Bibliothèque UI | React 18 |
| Outil de build | Vite |
| Langage | JavaScript (JSX) |
| Framework CSS | TailwindCSS 3 |
| Icônes | `lucide-react` |
| Accent principal | `cih-orange` — `#F26522` |
| Accent secondaire | `cih-blue` — `#005CA9` |
| Rayon des cartes et blocs | `rounded-2xl` (jamais d'angle vif sur un conteneur de premier niveau) |
| Élévation par défaut | `shadow-md` pour les cartes |
| Élévation renforcée | `shadow-xl` réservé au chat déplié et aux modales |
| Rythme d'espacement | multiples de 4 en Tailwind (`gap-3`, `gap-4`, `p-4`, `p-6`…), pas de valeurs arbitraires |

---

## 9\. Règles communes de style

- **Rayons** : cartes et blocs largement arrondis (`rounded-2xl`), jamais d'angles vifs sur un conteneur de premier niveau.  
- **Ombres** : `shadow-md` par défaut sur les cartes ; `shadow-xl` réservé à la fenêtre de chat dépliée et aux modales.  
- **Espacement** : rythme régulier, identique dans l'esprit entre mobile et desktop ; le panneau desktop respire davantage grâce à l'espace disponible, sans jamais paraître compressé ni disproportionné.  
- **Icônes** : exclusivement `lucide-react`, un seul jeu cohérent partout, taille réduite dans les listes, intermédiaire dans les en-têtes, plus grande pour le bouton flottant de l'assistant.  
- **Transitions** : toute carte cliquable, bouton ou bascule s'anime avec une transition courte et douce.  
- **Positionnement du chat** : la fenêtre de chat est positionnée de manière à ne jamais recouvrir entièrement le cadre du téléphone (voir §4).

---

## 10\. Écran de connexion — version mobile (dans le téléphone)

Contenu, de haut en bas, fidèle à l'image 1 :

1. **En-tête compact** : icône menu à gauche, nom du projet au centre (`CIH AI Banking — Démonstration`, texte seul, sans logo), icône de sécurité à droite.  
2. **Titre** : « Bienvenue ».  
3. **Panneau sombre semi-transparent** :  
   - identifiant (valeur fictive pré-remplie, ex. « Client Démo ») ;  
   - mot de passe masqué, avec lien « Oublié ? » aligné à droite ;  
   - bascule « Se souvenir de moi » ;  
   - bouton pleine largeur « Connexion » (`cih-orange`).  
4. **Section « Nos services »**, grille 2 × 2 : Portail immobilier, Assurances, Agences, Partenaires.  
5. **Bouton Assistant IA** (visuel), fenêtre de chat partagée fermée par défaut.

---

## 11\. Écran de connexion — adaptation desktop agrandie (même écran)

Le panneau desktop affiche **exactement le même écran de connexion**, agrandi et respacé pour un affichage large — ce n'est pas un écran différent ni une page d'accueil marketing :

1. **En-tête compact**, mêmes éléments que la version mobile (menu, nom du projet, icône de sécurité), simplement étirés sur la largeur du panneau.  
2. **Titre « Bienvenue »**, repris à l'identique, en taille agrandie.  
3. **Panneau sombre semi-transparent**, mêmes champs dans le même ordre (identifiant, mot de passe, « Oublié ? », « Se souvenir de moi », bouton « Connexion »), présenté dans un module de largeur confortable et centré dans le panneau desktop, sur le même fond en dégradé que la version mobile.  
4. **Section « Nos services »**, mêmes quatre entrées (Portail immobilier, Assurances, Agences, Partenaires), réorganisées sur une seule rangée de quatre plutôt qu'en grille 2 × 2, pour profiter de la largeur disponible.  
5. **Bouton Assistant IA** (visuel), contrôlant la même fenêtre de chat partagée que le bouton mobile (voir §13).  
6. **Mention académique** visible en pied de panneau.

---

## 12\. Écran dashboard — version mobile (dans le téléphone)

Contenu, de haut en bas, fidèle à l'image 2 :

1. **En-tête** : icône menu, icône messages (badge), icône notifications (badge), icône déconnexion/paramètres.  
2. **Salutation** : « Bonjour {prénom} \! », en orange, sous une ligne fine orange.  
3. **Carte de compte**, centrée : type de compte, numéro fictif masqué, libellé « Solde », montant masqué par défaut (`**** MAD`) avec bouton afficher/masquer.  
4. **Grille de services 2 × 3** : Mes cartes, Effectuer un virement, Effectuer une recharge, Payer mes factures, Financer mon projet, Payer vignette — icônes orange, séparateurs orange clair.  
5. **Transactions récentes** : liste courte, icône de catégorie, libellé, date, montant.  
6. **Navigation inférieure** : Accueil, Virements, Cartes, Assistance.  
7. **Bouton Assistant IA** (visuel), fenêtre de chat partagée fermée par défaut.

Toutes les données sont fictives et proviennent de l'état partagé unique (§5) ; aucune valeur n'est codée en dur.

---

## 13\. Écran dashboard — adaptation desktop agrandie (même écran, visualisations complémentaires)

Le panneau desktop affiche **le même dashboard**, avec les mêmes données de session, présentées plus clairement grâce à l'espace disponible. Il peut inclure des visualisations complémentaires des mêmes données fictives :

1. **Sidebar** : navigation verticale (adaptation de la navigation inférieure mobile : Accueil, Virements, Cartes, Assistance), nom du projet en en-tête de sidebar.  
2. **En-tête desktop** : salutation « Bonjour {prénom} \! » (reprise à l'identique, taille agrandie), messages, notifications.  
3. **Compte et solde** : même carte de compte que la version mobile (même numéro masqué, même solde, même bouton afficher/masquer partagé).  
4. **Six raccourcis** : mêmes six actions que la grille mobile (Mes cartes, Effectuer un virement, Effectuer une recharge, Payer mes factures, Financer mon projet, Payer vignette), présentées en rangée ou en grille adaptée à la largeur.  
5. **Transactions récentes** : même liste que la version mobile, avec plus d'espace de lecture.  
6. **Graphique de répartition fictive des dépenses** : visualisation complémentaire, catégories et montants fictifs cohérents avec les transactions affichées.  
7. **Carte bancaire fictive et masquée** : visuel générique, numéro masqué, nom fictif, date d'expiration fictive, sans aucun logo de réseau de paiement.  
8. **Encart de sécurité** : invitation à activer une double authentification, cohérente avec les contrôles décrits dans `04_scenarios_et_securite.md`.  
9. **Bouton Assistant IA** (visuel), contrôlant la même fenêtre de chat partagée que le bouton mobile.  
10. **Mention académique** visible en pied de panneau.

Ces éléments desktop ne constituent pas une deuxième application : ils présentent, de façon plus lisible, les mêmes données fictives de la session mobile.

---

## 13bis\. Données bancaires réelles — `GET /api/banking/overview`

Une fois le client authentifié, le tableau de bord n'affiche **plus aucune donnée simulée**. Les
montants, comptes, transactions et informations de carte proviennent exclusivement de
`GET /api/banking/overview`, appelé par `BankingAppProvider` avec le `session_id` de la session
courante placé dans l'en-tête `Authorization` — **jamais dans l'URL**.

**Raison d'être.** Avant cette intégration, le tableau de bord affichait `mockAccount`
(15 420,50 MAD) pendant que l'assistant lisait la base réelle (106 318,39 MAD pour le client de
démonstration). Les deux se contredisaient à l'écran. Le tableau de bord et l'assistant partagent
désormais la même source pour la même session.

**État exposé par `BankingAppProvider`** (identique pour le téléphone et le panneau desktop) :

| Valeur | Contenu |
| :---- | :---- |
| `overview` | Réponse complète, ou `null` |
| `overviewStatus` | `idle` \| `loading` \| `ready` \| `error` |
| `overviewError` | `unauthorized` \| `network` \| `invalid` |
| `accounts` | Tous les comptes du client, dans l'ordre renvoyé par le backend |
| `selectedAccountIndex`, `selectAccount` | Compte affiché par `AccountCard` |
| `account` | Compte sélectionné, au format attendu par les composants existants |
| `totalBalance` | Solde cumulé **tous comptes** — c'est le montant annoncé par l'assistant |
| `card` | Carte masquée du client, ou `null` |
| `transactions` | Transactions récentes, converties au contrat de `RecentTransactions` |
| `retryOverview` | Relance le chargement avec la session courante |

**Règles obligatoires :**

- **Aucun repli sur les données simulées après authentification.** Si la requête échoue, les
  panneaux affichent `OverviewStatusBanner` et **aucun montant**. Afficher un solde de
  démonstration à la place d'un solde réel indisponible serait pris pour le vrai solde.
  `mockAccount` et `mockTransactions` ne servent plus que sur l'écran public, avant connexion.
- **Un seul chargement, deux panneaux.** Le téléphone et le panneau desktop lisent le même
  `overviewStatus` et affichent ou masquent exactement les mêmes données au même instant (§5).
- **Réponse obsolète ignorée.** Un jeton de course (`overviewRequestRef`) neutralise toute réponse
  arrivant après une déconnexion ou une autre connexion : les données d'un client ne peuvent
  jamais apparaître dans la session d'un autre.
- **`401` ⇒ déconnexion.** Le `session_id` est retiré de `sessionStorage` et l'application repasse
  en état non authentifié, plutôt que d'afficher un tableau de bord authentifié sans données.
- **Déconnexion ⇒ effacement.** `overview`, les comptes, le total, la carte et la conversation
  sont vidés ; la conversation contient elle aussi des données personnelles.
- **Montants en chaîne décimale**, jamais en nombre flottant, jusqu'à l'affichage (`src/data/money.js`).
- **Données jamais exposées** : le PAN complet, le CVV, le PIN et la clé technique `id_compte`
  n'atteignent pas le frontend, le backend ne les renvoyant pas. Le RIB et l'IBAN complets, en
  revanche, sont bien remis à leur propriétaire authentifié : ce sont ses propres coordonnées.
- **Contrat de `RecentTransactions`** : `amount` est une chaîne décimale **non signée**, le sens
  est porté par `direction` valant `'in'` ou `'out'`. Le backend parle `credit` / `debit` : la
  traduction se fait une seule fois, dans `BankingAppProvider`.
- **Aucun élément de repli après authentification.** Si le client n'a pas de carte, `BankCard`
  n'est pas rendu — `mockCard` ne le remplace pas. Tant que le nom réel n'est pas connu, la
  salutation « Bonjour … » n'est pas affichée plutôt que d'afficher un nom de démonstration.
  En cas d'erreur, la colonne de visualisations complémentaires est masquée entièrement : ses
  montants seraient sinon les seuls chiffres à l'écran et seraient pris pour les vrais.
- La **répartition des dépenses** (`SpendingChart`) reste simulée : le backend n'expose pas encore
  cette agrégation via cet endpoint. C'est le **seul** élément simulé subsistant après
  authentification ; il porte à l'écran la mention « Répartition simulée — non issue de votre
  compte » et n'apparaît que lorsque les données réelles sont chargées.

---

## 14\. Assistant IA — un seul ChatWidget

Il existe **un seul `ChatWidget`**, monté une seule fois dans `App`. Il n'existe ni deux instances de chat, ni deux fenêtres de chat indépendantes, ni ouverture locale propre à un panneau.

- Deux **boutons visuels** existent : un bouton Assistant IA dans le téléphone, un bouton Assistant IA dans le panneau desktop.  
- Les deux boutons contrôlent **le même** `ChatWidget`, **la même** fenêtre, **la même** conversation et **le même** état d'ouverture. Cliquer sur l'un ou l'autre ouvre ou ferme la fenêtre de chat unique, visible identiquement dans son état pour les deux panneaux.  
- Le chat est **fermé par défaut**.  
- Avant authentification, la conversation est figée sur l'Agent FAQ (Agent 1, voir `02_architecture_multi_agents.md`). Si l'utilisateur pose une question personnelle ou sensible sans être connecté, l'assistant invite à se connecter et les deux écrans de connexion (mobile et desktop) sont mis en évidence simultanément (léger halo orange temporaire), puisqu'il s'agit du même écran actif partagé.  
- Après authentification, la bascule vers l'Agent Transactionnel (Agent 2\) et le retour à l'Agent FAQ en fin d'opération sont visibles simultanément et à l'identique par les deux boutons d'accès, puisqu'il s'agit du même widget et de la même conversation.

---

## 15\. Virement et OTP — états synchronisés

Le déroulé d'un virement suit une séquence d'états strictement synchronisée entre le téléphone et le panneau desktop ; seule la présentation visuelle s'adapte au format (largeur de bulle, densité), jamais le contenu ni l'état :

1. **Demande de virement** : l'utilisateur exprime son intention (bénéficiaire, montant) dans la conversation.  
2. **`TransferConfirmationCard`** : récapitulatif de l'opération (bénéficiaire, montant, compte source) affiché dans le fil de discussion.  
3. **Confirmation ou annulation** : action de l'utilisateur sur la carte de récapitulatif.  
4. **Passage en « Mode opération sécurisée »** : l'en-tête du chat signale le passage à l'Agent Transactionnel (Agent 2).  
5. **`OtpModal`** : saisie du code de confirmation, intégrée au fil de discussion.  
6. **Code de démonstration `123456`** : seule valeur acceptée dans l'environnement de démonstration.  
7. **Code correct → succès** : passage à l'étape de résultat positif.  
8. **Autre code → erreur** : message d'erreur, décrément du nombre de tentatives restantes.  
9. **Maximum trois tentatives** : au-delà, l'opération est annulée et l'échec est notifié.  
10. **`TransferResult`** : bloc final affichant le résultat (succès ou échec) de l'opération.

Chaque étape apparaît **simultanément** dans le téléphone et dans la vue desktop, avec le même état (même carte affichée, même nombre de tentatives restantes, même résultat), quelle que soit l'interface depuis laquelle l'utilisateur agit.

---

## 16\. Règles de contenu fictif obligatoires

| Élément | Règle |
| :---- | :---- |
| Nom d'utilisateur | Fictif, injecté dynamiquement, jamais identique aux captures de référence |
| Numéro de compte | Fictif, masqué par défaut, format plausible mais inventé |
| Solde et montants | Fictifs, distincts des exemples des captures de référence |
| Transactions | Fictives (enseignes, dates, montants inventés) |
| Carte bancaire (desktop) | Visuel générique, masqué, sans logo de réseau de paiement |
| Logos | Aucun logo officiel CIH, aucun logo VISA ou autre réseau ; uniquement le nom du projet en texte |
| Mention académique | Toujours visible, sur les deux panneaux, avant et après authentification |

---

## 17\. Composants — rôle, props et emplacement

| Composant | Rôle | Props principales | Emplacement |
| :---- | :---- | :---- | :---- |
| `App` | Racine de l'application ; détient/fournit l'état partagé via `BankingAppProvider` ; monte `ResponsiveShowcase` et l'unique `ChatWidget` | — | `src/App.jsx` |
| `BankingAppProvider` | Fournisseur de l'état partagé unique (auth, utilisateur, écran actif, données de compte, conversation, agent actif, opération de virement, ouverture du chat) | `children` | `src/context/BankingAppProvider.jsx` |
| `ResponsiveShowcase` | Organise l'affichage selon les règles de largeur (§4) ; décide du rendu de `PhonePreview` et/ou `DesktopView` | — (lit l'état partagé) | `src/components/ResponsiveShowcase.jsx` |
| `PhonePreview` | Cadre de téléphone décoratif et interactif, utilisé uniquement à partir de 900 px (aux côtés de `DesktopView`) ; reçoit l'état partagé et rend `MobileLoginView` ou `MobileDashboard` selon l'écran actif | état partagé (lecture/écriture) | `src/components/PhonePreview.jsx` |
| `MobileAppView` | Affiche directement `MobileLoginView` ou `MobileDashboard` sur un véritable écran mobile, sans cadre décoratif, utilisé sous 640 px | utilise le même état global partagé | `src/components/mobile/MobileAppView.jsx` |
| `MobileLoginView` | Écran de connexion mobile (§10) | `onLogin` | `src/components/mobile/MobileLoginView.jsx` |
| `MobileDashboard` | Écran dashboard mobile (§12) | `account`, `transactions`, `balanceVisible`, `onToggleBalance` | `src/components/mobile/MobileDashboard.jsx` |
| `DesktopLoginView` | Écran de connexion desktop agrandi (§11) | `onLogin` | `src/components/desktop/DesktopLoginView.jsx` |
| `DesktopDashboard` | Écran dashboard desktop agrandi (§13) | `account`, `transactions`, `balanceVisible`, `onToggleBalance` | `src/components/desktop/DesktopDashboard.jsx` |
| `DesktopView` | Équivalent desktop de `PhonePreview` ; reçoit le même état partagé et rend `DesktopLoginView` ou `DesktopDashboard` selon l'écran actif | état partagé (lecture/écriture) | `src/components/DesktopView.jsx` |
| `Sidebar` | Navigation verticale du dashboard desktop (adaptation de la navigation inférieure mobile) | `activeSection`, `onNavigate` | `src/components/desktop/Sidebar.jsx` |
| `DesktopHeader` | En-tête du panneau desktop (salutation, messages, notifications) | `userName` | `src/components/desktop/DesktopHeader.jsx` |
| `AccountCard` | Carte de compte et de solde, rendue à l'identique dans les deux panneaux à partir du même état ; affiche en complément le **total tous comptes** lorsqu'il diffère du compte sélectionné | `account`, `balanceVisible`, `onToggleBalance`, `totalBalance` (optionnel) | `src/components/shared/AccountCard.jsx` |
| `AccountSelector` | Choix du compte affiché lorsque le client en détient plusieurs (y compris plusieurs du même type) ; masqué pour un client mono-compte | `accounts`, `selectedIndex`, `onSelect` | `src/components/shared/AccountSelector.jsx` |
| `OverviewStatusBanner` | État de chargement des données bancaires réelles : squelette pendant le chargement, message et bouton « Réessayer » en cas d'échec. **Aucun montant simulé n'est affiché en repli** | `status`, `error`, `onRetry` | `src/components/shared/OverviewStatusBanner.jsx` |
| `BankCard` | Visuel de carte bancaire fictive et masquée (desktop) | `cardData` | `src/components/desktop/BankCard.jsx` |
| `RecentTransactions` | Liste des transactions récentes (mobile et desktop) | `transactions` | `src/components/shared/RecentTransactions.jsx` |
| `QuickActions` | Six raccourcis bancaires (mobile et desktop) | `actions` | `src/components/shared/QuickActions.jsx` |
| `SpendingChart` | Graphique fictif de répartition des dépenses (desktop) | `data` | `src/components/desktop/SpendingChart.jsx` |
| `SecurityBanner` | Encart d'incitation à la double authentification (desktop) | `onActivate` | `src/components/desktop/SecurityBanner.jsx` |
| `BottomNav` | Navigation inférieure mobile | `activeSection`, `onNavigate` | `src/components/mobile/BottomNav.jsx` |
| `ChatWidget` | Composant unique de l'assistant IA, monté une seule fois dans `App` ; détient la conversation, l'agent actif et l'état d'ouverture partagés | `jwtToken`, `mode` | `src/components/chat/ChatWidget.jsx` |
| `ChatFab` | Bouton visuel d'ouverture/fermeture, rendu une fois dans `PhonePreview` et une fois dans `DesktopView`, contrôlant le même `ChatWidget` | `onToggle`, `variant: "mobile" ou "desktop"` | `src/components/chat/ChatFab.jsx` |
| `ChatWindow` | Fenêtre de conversation affichant l'historique partagé | `messages`, `isTyping`, `onSend` | `src/components/chat/ChatWindow.jsx` |
| `ChatMessage` | Bulle de message individuelle (texte ou composant riche) | `message` | `src/components/chat/ChatMessage.jsx` |
| `QuickSuggestions` | Suggestions de questions rapides dans le chat | `suggestions`, `onSelect` | `src/components/chat/QuickSuggestions.jsx` |
| `TransferConfirmationCard` | Récapitulatif de virement à confirmer (§15) | `data`, `onConfirm`, `onCancel` | `src/components/chat/TransferConfirmationCard.jsx` |
| `OtpModal` | Saisie du code de confirmation (§15) | `expiresIn`, `attemptsLeft`, `onSubmit`, `onResend` | `src/components/chat/OtpModal.jsx` |
| `TransferResult` | Bloc de résultat final de l'opération (§15) | `status`, `details` | `src/components/chat/TransferResult.jsx` |

Règles structurelles obligatoires :

- `App` détient ou fournit l'état partagé (via `BankingAppProvider`).  
- `ResponsiveShowcase` organise les deux vues selon les règles de largeur (§4).  
- `PhonePreview` reçoit l'état partagé.  
- `DesktopView` reçoit le même état partagé.  
- `ChatWidget` est monté une seule fois dans `App`.

---

## 18\. Organisation générale (arborescence)

Interface racine

├── App

│   └── BankingAppProvider (état partagé unique)

│       ├── ResponsiveShowcase

│       │   ├── ≥ 900 px

│       │   │   ├── PhonePreview

│       │   │   │   ├── MobileLoginView          (§10)

│       │   │   │   ├── MobileDashboard          (§12)

│       │   │   │   ├── BottomNav

│       │   │   │   └── ChatFab (variant="mobile")

│       │   │   └── DesktopView

│       │   │       ├── DesktopLoginView         (§11)

│       │   │       ├── DesktopDashboard         (§13)

│       │   │       │   ├── Sidebar

│       │   │       │   ├── DesktopHeader

│       │   │       │   ├── AccountCard

│       │   │       │   ├── QuickActions

│       │   │       │   ├── RecentTransactions

│       │   │       │   ├── SpendingChart

│       │   │       │   ├── BankCard

│       │   │       │   └── SecurityBanner

│       │   │       └── ChatFab (variant="desktop")

│       │   ├── 640–899 px

│       │   │   └── DesktopView (seul rendu, structure identique ci-dessus)

│       │   └── \< 640 px

│       │       └── MobileAppView (sans cadre décoratif)

│       │           ├── MobileLoginView          (§10)

│       │           ├── MobileDashboard          (§12)

│       │           ├── BottomNav

│       │           └── ChatFab (variant="mobile")

│       └── ChatWidget (monté une seule fois, instance unique)

│           ├── ChatWindow

│           │   ├── ChatMessage

│           │   ├── QuickSuggestions

│           │   ├── TransferConfirmationCard

│           │   ├── OtpModal

│           │   └── TransferResult

└── Mention académique persistante (les deux panneaux)

---

## 19\. Checklist de validation

- [ ] À 1920 px avant connexion : téléphone login \+ connexion desktop.  
- [ ] À 1920 px après connexion : dashboard mobile \+ dashboard desktop.  
- [ ] À 800 px (entre 640 et 899 px) : vue desktop uniquement.  
- [ ] À 375 px : application mobile uniquement.  
- [ ] Le téléphone est interactif et non décoratif.  
- [ ] Les actions du PC apparaissent dans le téléphone.  
- [ ] Les actions du téléphone apparaissent dans le PC.  
- [ ] Le solde affiché ou masqué est synchronisé.  
- [ ] Un seul ChatWidget est monté dans App.  
- [ ] Deux boutons visuels ouvrent le même chat.  
- [ ] Le chat est fermé par défaut.  
- [ ] Le virement, la confirmation, l'OTP et le résultat sont synchronisés.  
- [ ] Le téléphone reste visible lorsque le chat est ouvert.  
- [ ] Aucun logo officiel et aucune donnée réelle.  
- [ ] Aucun défilement horizontal à 1920 px.

---

## 20\. Règle de cohérence et d'évolution du document

Tout nouvel écran, tout nouveau composant de chat riche ou toute nouvelle donnée affichée doit d'abord être décrit dans ce document — avec son contenu exact et sa règle de synchronisation totale entre le téléphone et le panneau desktop — avant d'être implémenté. Aucun état métier, aucune donnée, aucune conversation et aucune opération ne peuvent différer entre les deux vues. La vue desktop peut toutefois utiliser des composants visuels complémentaires — graphique, carte bancaire fictive et encart de sécurité — pour présenter plus clairement les mêmes données partagées.  
