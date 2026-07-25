# 05 — Interface Frontend & UI/UX : CIH AI Banking

> **Type de document** : Spécification UI/UX et guide de développement Frontend **Prérequis** : `01_projet_overview.md`, `02_architecture_multi_agents.md`, `03_stack_technique.md` **Rôle de ce document** : Servir de référence complète pour reproduire fidèlement l'expérience de l'application CIH Mobile en React/TailwindCSS, gérer les deux états graphiques (non-authentifié / authentifié), et intégrer le widget de chat multi-agents comme composant transverse de l'interface.

---

## 1\. Rôle du document

Ce document fixe, pour chaque écran et chaque composant :

- la classe CSS/Tailwind exacte à appliquer ;  
- l'état React nécessaire et sa provenance ;  
- le comportement du widget de chat selon le contexte (session authentifiée ou non) ;  
- la structure de composants à respecter, avec leurs props.

>   
> Aucune valeur de couleur, d'espacement ou d'arrondi ne doit être improvisée pendant le développement : tout écart par rapport aux classes listées ici doit être proposé comme modification de ce document avant d'être codé.

---

## 2\. Charte graphique & Design System CIH Bank

### 2.1 Palette de couleurs

Extension à ajouter dans `tailwind.config.js` :

// tailwind.config.js

module.exports \= {

  content: \["./src/\*\*/\*.{js,jsx}"\],

  theme: {

    extend: {

      colors: {

        "cih-orange": "\#F26522",

        "cih-orange-dark": "\#D9530F",

        "cih-orange-light": "\#FDECE2",

        "cih-blue": "\#005CA9",

        "cih-blue-dark": "\#00427A",

        "cih-blue-light": "\#E6F0F9",

        "cih-bg-dark-from": "\#0B1E33",

        "cih-bg-dark-to": "\#142A45",

        "cih-surface": "\#F8FAFC",

      },

    },

  },

};

| Rôle | Token Tailwind | Hex | Usage |
| :---- | :---- | :---- | :---- |
| Accent principal | `cih-orange` | `#F26522` | Boutons d'action, badges, éléments actifs, bulles utilisateur du chat |
| Accent secondaire | `cih-blue` | `#005CA9` | Titres, icônes secondaires, header, liens |
| Fond écran de connexion | `cih-bg-dark-from` → `cih-bg-dark-to` | `#0B1E33` → `#142A45` | Dégradé de fond de l'écran non-authentifié |
| Fond dashboard | `white` / `cih-surface` | `#FFFFFF` / `#F8FAFC` | Fond des écrans authentifiés |

### 2.2 Typographie & style de composants

- **Cartes** : toujours `rounded-2xl`, jamais `rounded-md` ou `rounded-lg` pour un conteneur de premier niveau.  
- **Élévation** : `shadow-md` par défaut sur les cartes, `shadow-xl` réservé à la fenêtre de chat dépliée et aux modales.  
- **Police** : police système par défaut de Tailwind (`font-sans`) ; poids `font-semibold` pour les titres de carte, `font-bold` pour les montants.  
- **Icônes** : exclusivement `lucide-react`, taille standard `w-5 h-5` en contexte de liste, `w-6 h-6` en header, `w-7 h-7` dans le FAB.  
- **Espacements** : rythme vertical en multiples de `4` (Tailwind) — `gap-3`, `gap-4`, `p-4`, `p-6`. Éviter les valeurs arbitraires (`p-[13px]`).  
- **Transitions** : `transition` \+ `duration-200` sur tout élément interactif (bouton, carte cliquable, FAB).

---

## 3\. Écran 1 — Vue non-authentifiée (Landing / Connexion)

### 3.1 Structure générale

\<div className="min-h-screen bg-gradient-to-b from-cih-bg-dark-from to-cih-bg-dark-to flex flex-col"\>

  \<Navbar authenticated={false} /\>

  \<LoginForm /\>

  \<PublicServicesGrid /\>

  \<ChatWidget mode="public" /\>

\</div\>

### 3.2 Header (`Navbar`, variante non-authentifiée)

\<header className="flex items-center justify-between px-4 pt-6 pb-4"\>

  \<button aria-label="Ouvrir le menu" className="text-white/90"\>

    \<Menu className="w-6 h-6" /\>

  \</button\>

  \<img src="/logo-cih-white.svg" alt="CIH Bank" className="h-8" /\>

  \<ShieldCheck className="w-6 h-6 text-cih-orange" aria-hidden="true" /\>

\</header\>

### 3.3 Formulaire d'authentification (`LoginForm`)

\<div className="mx-4 mt-6 bg-white rounded-2xl shadow-md p-6 space-y-5"\>

  \<div\>

    \<label className="block text-xs font-medium text-gray-500 mb-1"\>Identifiant\</label\>

    \<input

      type="text"

      placeholder="Identifiant client"

      className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm

                 focus:outline-none focus:ring-2 focus:ring-cih-orange focus:border-transparent"

    /\>

  \</div\>

  \<div\>

    \<div className="flex items-center justify-between mb-1"\>

      \<label className="text-xs font-medium text-gray-500"\>Mot de passe\</label\>

      \<a href="\#" className="text-xs text-cih-blue font-medium"\>Oublié ?\</a\>

    \</div\>

    \<input

      type="password"

      className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm

                 focus:outline-none focus:ring-2 focus:ring-cih-orange focus:border-transparent"

    /\>

  \</div\>

  \<div className="flex items-center justify-between"\>

    \<span className="text-sm text-gray-600"\>Se souvenir de moi\</span\>

    {/\* Toggle : conteneur w-10 h-6, pastille w-4 h-4, translate-x-4 à l'état actif \*/}

    \<button

      role="switch"

      aria-checked={remember}

      onClick={() \=\> setRemember(\!remember)}

      className={\`w-10 h-6 rounded-full transition ${remember ? "bg-cih-orange" : "bg-gray-300"}\`}

    \>

      \<span className={\`block w-4 h-4 bg-white rounded-full shadow transform transition ${remember ? "translate-x-5" : "translate-x-1"}\`} /\>

    \</button\>

  \</div\>

  \<button className="w-full bg-cih-orange hover:bg-cih-orange-dark text-white font-semibold

                     py-3 rounded-xl transition duration-200"\>

    Connexion

  \</button\>

\</div\>

**État React requis** : `identifiant`, `motDePasse`, `remember` (boolean), `isSubmitting`, `loginError`.

### 3.4 Grille de services publics (2×2)

\<div className="grid grid-cols-2 gap-3 px-4 mt-6"\>

  {publicServices.map((s) \=\> (

    \<button key={s.label} className="bg-white rounded-2xl shadow-md p-4 flex flex-col items-center gap-2

                                       hover:shadow-lg transition duration-200"\>

      \<s.icon className="w-6 h-6 text-cih-blue" /\>

      \<span className="text-xs font-medium text-gray-700 text-center"\>{s.label}\</span\>

    \</button\>

  ))}

\</div\>

`publicServices` : `[{ icon: Building2, label: "Portail Immobilier" }, { icon: ShieldCheck, label: "Assurances" }, { icon: MapPin, label: "Agences" }, { icon: Handshake, label: "Partenaires" }]`.

### 3.5 Comportement du chat en mode public

- Le widget (`ChatWidget mode="public"`) est monté avec `mode="public"` — cette seule prop suffit à garantir qu'aucune bascule vers un affichage transactionnel n'est possible dans cet état (pas de prop `agent` distincte, voir §6.2 pour la table complète des props).  
- L'Agent 1 répond aux questions générales via RAG (ChromaDB) sans en-tête d'authentification.  
- Si l'utilisateur pose une question personnelle ou sensible (solde, virement), le message assistant retourné contient un champ `requires_auth: true`. Le composant `ChatMessage` détecte ce champ et :  
  1. affiche le message d'invitation ( *« Pour consulter cette information, connectez-vous à votre espace client. »* ) ;  
  2. déclenche `onRequireAuth()`, remonté par `ChatWidget` jusqu'au composant racine, qui applique une classe de surbrillance temporaire sur `LoginForm` :

\<div className={\`mx-4 mt-6 bg-white rounded-2xl shadow-md p-6 space-y-5 transition

                 ${highlightLogin ? "ring-2 ring-cih-orange animate-pulse" : ""}\`}\>

La surbrillance (`highlightLogin`, état booléen levé dans le composant parent) se retire automatiquement après 2,5 secondes ou dès la première frappe dans le formulaire.

---

## 4\. Écran 2 — Vue authentifiée (Dashboard Client)

### 4.1 Structure générale

\<div className="min-h-screen bg-cih-surface flex flex-col"\>

  \<Navbar authenticated={true} userName="MME MALAK DRISSI" /\>

  \<AccountCard account={account} /\>

  \<ShortcutGrid /\>

  \<ChatWidget mode="authenticated" jwtToken={token} /\>

\</div\>

### 4.2 Header & salutation

\<div className="px-4 pt-4 pb-2 border-b-2 border-cih-orange"\>

  \<p className="text-cih-orange font-bold text-sm"\>Bonjour {userName} \!\</p\>

\</div\>

`userName` est injecté dynamiquement depuis la réponse d'authentification (`/auth/login`), jamais codé en dur.

### 4.3 Carte récapitulative de compte (`AccountCard`)

\<div className="mx-4 mt-4 bg-white rounded-2xl shadow-md border border-gray-100 p-5 text-center"\>

  \<p className="text-xs text-gray-500"\>{account.type}\</p\>

  \<p className="text-cih-blue font-medium text-sm mt-1"\>{account.number}\</p\>

  \<p className="text-\[11px\] text-gray-400 mt-4"\>Solde\</p\>

  \<div className="flex items-center justify-center gap-2 mt-1"\>

    \<span className="text-xl font-bold text-gray-900 tracking-wide"\>

      {balanceVisible ? \`${account.balance.toLocaleString("fr-FR")} MAD\` : "\*\*\*\* MAD"}

    \</span\>

    \<button onClick={() \=\> setBalanceVisible(\!balanceVisible)} aria-label="Afficher/masquer le solde"\>

      \<Eye className="w-5 h-5 text-cih-blue" /\>

    \</button\>

  \</div\>

\</div\>

Exemple de données : `{ type: "Compte chèques", number: "6120491211011600", balance: 15420.50 }`. `balanceVisible` initialisé à `false` (le solde reste masqué par défaut à chaque ouverture d'écran).

### 4.4 Grille de raccourcis (2×3)

\<div className="grid grid-cols-2 gap-3 px-4 mt-5"\>

  {shortcuts.map((s) \=\> (

    \<button key={s.label} className="bg-white rounded-2xl border border-gray-100 shadow-md

                                       p-4 flex flex-col items-center gap-2 hover:bg-cih-orange-light

                                       transition duration-200"\>

      \<s.icon className="w-6 h-6 text-cih-orange" /\>

      \<span className="text-xs font-medium text-gray-700 text-center"\>{s.label}\</span\>

    \</button\>

  ))}

\</div\>

`shortcuts` : `Mes Cartes`, `Effectuer un virement`, `Effectuer une recharge`, `Payez vos factures`, `Financer mon projet`, `Payer vignette` — chacun avec son icône `lucide-react` correspondante (`CreditCard`, `ArrowLeftRight`, `Smartphone`, `Receipt`, `Home`, `Car`).

### 4.5 Comportement du chat en mode authentifié

- `ChatWidget` reçoit le prop `jwtToken`. Chaque appel réseau vers `/chat` inclut systématiquement l'en-tête :

fetch("/api/chat", {

  method: "POST",

  headers: {

    "Content-Type": "application/json",

    Authorization: \`Bearer ${jwtToken}\`,

  },

  body: JSON.stringify({ message, conversation\_id }),

});

- La consultation du solde en temps réel est autorisée : l'Agent 1 peut invoquer ses outils de lecture seule et la réponse est affichée comme un message assistant standard (`ChatMessage type="text"`).  
- Lorsque le Backend signale, via le champ `active_agent` de la réponse, un passage à `"secure_operation"`, `ChatWidget` :  
  1. met à jour l'en-tête de la fenêtre de chat (nom affiché : *Agent Transactionnel CIH*, voir §5.2) ;  
  2. rend les messages suivants avec des composants riches selon leur `type` :  
     - `type: "transfer_confirmation"` → `<TransferConfirmationCard data={message.data} onConfirm={...} onCancel={...} />`  
     - `type: "otp_request"` → `<OtpModal onSubmit={...} onResend={...} expiresIn={message.data.expiresIn} />`  
  3. revient automatiquement à l'affichage *Agent FAQ CIH* dès que le Backend renvoie `active_agent: "assistant"` (fin du scénario transactionnel, succès ou échec).

> **`active_agent` est un indicateur d'affichage, jamais un canal de communication.** Que sa valeur soit `"assistant"` ou `"secure_operation"`, le frontend continue de communiquer **exclusivement** avec FastAPI (`POST /api/chat`) — il ne dialogue jamais directement avec l'Agent 1, l'Agent 2, ou tout composant interne. Ces deux valeurs remplacent les anciennes valeurs internes `"agent_1"`/`"agent_2"` du `SharedState` (voir `02_architecture_multi_agents.md`, §4.1, note sur la portée du champ `active_agent`), qui restent un détail d'implémentation jamais exposé au frontend.

---

## 5\. Composant Chat Overlay (Widget Floating Chat)

### 5.1 Floating Action Button (`ChatFab`)

\<button

  onClick={toggleOpen}

  aria-label="Ouvrir l'assistant CIH"

  className="fixed bottom-6 right-6 w-14 h-14 rounded-full bg-cih-orange text-white

             shadow-xl flex items-center justify-center hover:bg-cih-orange-dark

             transition duration-200 z-50"

\>

  \<Bot className="w-6 h-6" /\>

  {hasUnread && (

    \<span className="absolute \-top-1 \-right-1 w-3.5 h-3.5 bg-cih-blue rounded-full border-2 border-white" /\>

  )}

\</button\>

### 5.2 Fenêtre modale dépliable (`ChatWindow`)

\<div className="fixed bottom-24 right-6 w-\[360px\] h-\[520px\] bg-white rounded-2xl

                shadow-xl flex flex-col overflow-hidden z-50"\>

  {/\* En-tête \*/}

  \<div className="flex items-center justify-between px-4 py-3 border-b border-gray-100"\>

    \<div className="flex items-center gap-2.5"\>

      \<div className="w-9 h-9 rounded-full bg-cih-blue-light flex items-center justify-center"\>

        \<Bot className="w-5 h-5 text-cih-blue" /\>

      \</div\>

      \<div\>

        \<p className="text-sm font-semibold text-gray-900"\>

          {activeAgent \=== "secure\_operation" ? "Agent Transactionnel CIH" : "Agent FAQ CIH"}

        \</p\>

        \<p className="text-\[11px\] text-green-600 flex items-center gap-1"\>

          \<span className="w-1.5 h-1.5 rounded-full bg-green-500" /\> En ligne

        \</p\>

      \</div\>

    \</div\>

    \<button onClick={onMinimize} aria-label="Réduire la conversation"\>

      \<ChevronDown className="w-5 h-5 text-gray-400" /\>

    \</button\>

  \</div\>

  {/\* Zone de messages \*/}

  \<div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 bg-cih-surface"\>

    {messages.map((m) \=\> \<ChatMessage key={m.id} message={m} /\>)}

    {isTyping && \<TypingIndicator /\>}

  \</div\>

  {/\* Zone de saisie \*/}

  \<div className="border-t border-gray-100 px-3 py-2.5 flex items-center gap-2"\>

    \<input

      value={draft}

      onChange={(e) \=\> setDraft(e.target.value)}

      placeholder="Écrivez votre message…"

      className="flex-1 bg-gray-100 rounded-full px-4 py-2 text-sm

                 focus:outline-none focus:ring-2 focus:ring-cih-orange"

    /\>

    \<button

      onClick={onSend}

      aria-label="Envoyer"

      className="w-9 h-9 rounded-full bg-cih-orange text-white flex items-center

                 justify-center hover:bg-cih-orange-dark transition"

    \>

      \<Send className="w-4 h-4" /\>

    \</button\>

  \</div\>

\</div\>

### 5.3 Bulles de message (`ChatMessage`)

function ChatMessage({ message }) {

  const isUser \= message.role \=== "user";

  return (

    \<div className={\`flex items-end gap-2 max-w-\[85%\] ${isUser ? "ml-auto flex-row-reverse" : ""}\`}\>

      {\!isUser && (

        \<div className="w-6 h-6 rounded-full bg-cih-blue-light flex items-center justify-center shrink-0"\>

          \<Bot className="w-3.5 h-3.5 text-cih-blue" /\>

        \</div\>

      )}

      \<div className={

        isUser

          ? "bg-cih-orange text-white rounded-2xl rounded-br-sm px-4 py-2 text-sm"

          : "bg-white border border-gray-100 text-gray-800 rounded-2xl rounded-bl-sm px-4 py-2 text-sm shadow-sm"

      }\>

        {message.type \=== "text" && message.content}

        {message.type \=== "transfer\_confirmation" && \<TransferConfirmationCard data={message.data} /\>}

        {message.type \=== "otp\_request" && \<OtpModal data={message.data} /\>}

      \</div\>

    \</div\>

  );

}

### 5.4 Indicateur de saisie (`TypingIndicator`)

\<div className="flex items-center gap-1 bg-white border border-gray-100 rounded-2xl

                px-4 py-3 w-fit shadow-sm"\>

  \<span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce \[animation-delay:-0.3s\]" /\>

  \<span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce \[animation-delay:-0.15s\]" /\>

  \<span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" /\>

\</div\>

### 5.5 Composants riches intégrés au chat

**`TransferConfirmationCard`** — carte de confirmation de virement, rendue à l'intérieur d'une bulle assistant :

\<div className="bg-cih-blue-light rounded-xl p-3 text-sm space-y-1.5 min-w-\[220px\]"\>

  \<div className="flex justify-between"\>\<span className="text-gray-500"\>Bénéficiaire\</span\>\<span className="font-medium"\>{data.beneficiary}\</span\>\</div\>

  \<div className="flex justify-between"\>\<span className="text-gray-500"\>Montant\</span\>\<span className="font-bold text-cih-blue"\>{data.amount} MAD\</span\>\</div\>

  \<div className="flex gap-2 pt-2"\>

    \<button onClick={onConfirm} className="flex-1 bg-cih-orange text-white rounded-lg py-1.5 font-medium"\>Confirmer\</button\>

    \<button onClick={onCancel} className="flex-1 bg-white border border-gray-200 rounded-lg py-1.5 text-gray-600"\>Annuler\</button\>

  \</div\>

\</div\>

**`OtpModal`** (variante intégrée au fil de discussion, et non en overlay séparé lorsqu'invoquée depuis le chat) — 6 cases de saisie, chronomètre de renvoi, bouton de validation, reprenant le même schéma que la carte de confirmation (fond `cih-blue-light`, bouton principal `bg-cih-orange`).

---

## 6\. Architecture des composants React & Props

### 6.1 Arborescence suggérée

src/components/

├── Navbar.jsx

├── LoginForm.jsx

├── PublicServicesGrid.jsx

│   └── ServiceCard.jsx

├── Dashboard.jsx

│   ├── AccountCard.jsx

│   └── ShortcutGrid.jsx

│       └── ShortcutCard.jsx

└── chat/

    ├── ChatWidget.jsx          \# composant racine, monté une seule fois dans App.jsx

    ├── ChatFab.jsx

    ├── ChatWindow.jsx

    ├── ChatMessage.jsx

    ├── TypingIndicator.jsx

    ├── TransferConfirmationCard.jsx

    └── OtpModal.jsx

### 6.2 Table des props par composant

**`ChatWidget`**

| Prop | Type | Requis | Description |
| :---- | :---- | :---- | :---- |
| `mode` | `"public" | "authenticated"` | oui | Détermine si l'agent est figé sur `agent1` ou si la bascule vers `agent2` est autorisée. |
| `jwtToken` | `string | null` | non | Transmis dans l'en-tête `Authorization` de chaque appel `/chat` en mode authentifié. |
| `onRequireAuth` | `() => void` | non | Remonté par un message `requires_auth: true` ; déclenche la surbrillance du `LoginForm`. |

**`ChatMessage`**

| Prop | Type | Requis | Description |
| :---- | :---- | :---- | :---- |
| `message` | `{ id, role: "user" | "assistant", type: "text" | "transfer_confirmation" | "otp_request", content?, data? }` | oui | Modèle unique couvrant les messages texte et les composants riches. |

**`TransferConfirmationCard`**

| Prop | Type | Requis | Description |
| :---- | :---- | :---- | :---- |
| `data` | `{ beneficiary: string, amount: number, account: string }` | oui | Détails de l'opération à confirmer. |
| `onConfirm` | `() => void` | oui | Envoie la confirmation à l'Agent 2 via le canal de chat. |
| `onCancel` | `() => void` | oui | Annule l'opération côté client et notifie le Backend. |

**`OtpModal`**

| Prop | Type | Requis | Description |
| :---- | :---- | :---- | :---- |
| `data` | `{ expiresIn: number, phoneMasked: string }` | oui | Durée de validité du code et numéro masqué destinataire. |
| `onSubmit` | `(code: string) => void` | oui | Transmet le code saisi à l'Agent 2\. |
| `onResend` | `() => void` | oui | Demande un renvoi de code, désactivé tant que `expiresIn` n'est pas écoulé. |

**`AccountCard`**

| Prop | Type | Requis | Description |
| :---- | :---- | :---- | :---- |
| `account` | `{ type: string, number: string, balance: number }` | oui | Données du compte affiché ; `balance` n'est jamais affiché en clair par défaut (voir §4.3). |

**`LoginForm`**

| Prop | Type | Requis | Description |
| :---- | :---- | :---- | :---- |
| `highlight` | `boolean` | non | Applique la classe `ring-2 ring-cih-orange animate-pulse` lorsque l'Agent 1 invite l'utilisateur à se connecter. |
| `onSubmit` | `(identifiant: string, motDePasse: string, remember: boolean) => void` | oui | Déclenche l'appel `/auth/login`. |

> **Règle de cohérence** : tout nouveau composant ajouté à `src/components/chat/` doit être documenté dans ce tableau avant d'être utilisé dans `ChatMessage`, afin que la liste des `type` de message reste exhaustive et centralisée.  

---

## 7\. Contrat d'authentification (`POST /api/auth/login`)

Le `LoginForm` (§3.3, prop `onSubmit`) déclenche cet appel. Toutes les données ci-dessous sont **fictives**, réservées à la démonstration académique.

**Requête :**

{

  "customer\_number": "DEMO001",

  "password": "valeur de démonstration"

}

**Réponse réussie :**

{

  "access\_token": "...",

  "token\_type": "bearer",

  "expires\_in": 1800,

  "user": {

    "customer\_id": "CUST-DEMO-001",

    "display\_name": "Client Démonstration"

  }

}

- Le frontend utilise **exclusivement** `user.display_name` pour la salutation du header (§4.2) — jamais de nom codé en dur.  
- `access_token` est le jeton de session **long terme** (frontend ↔ FastAPI), distinct du jeton de délégation A2A à courte durée de vie décrit dans `02_architecture_multi_agents.md` (§4.2bis), que le frontend ne voit jamais.  
- `expires_in` est exprimé en secondes (`1800` = 30 minutes, cohérent avec `JWT_EXPIRATION_MINUTES=30` dans `03_stack_technique.md`).
