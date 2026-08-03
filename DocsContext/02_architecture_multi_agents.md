# 02 — Architecture Multi-Agents : CIH AI Banking

> **Type de document** : Spécification technique de référence — architecture du graphe de décision **Prérequis** : `01_projet_overview.md` **Rôle de ce document** : Détailler le fonctionnement interne de chaque agent (graphe LangGraph, règles d'aiguillage), le protocole de communication inter-agents (A2A), la structure de l'état partagé, et le flux de données complet, du frontend jusqu'au système bancaire. Ce document fait autorité sur toute question d'implémentation touchant à l'orchestration des agents.

---

## 1\. Rôle du document

Ce fichier répond à trois questions que `01_projet_overview.md` ne couvre pas en détail :

1. **Comment** chaque agent décide-t-il de son comportement, nœud par nœud ?  
2. **Comment** les deux agents communiquent-ils sans partager plus d'informations que nécessaire ?  
3. **Comment** une donnée circule-t-elle, techniquement (formats, headers, endpoints), entre React et le système bancaire ?

Toute implémentation qui dévierait des règles d'aiguillage ou de la séquence de contrôle décrites ici doit être documentée comme une exception explicite, justifiée et validée — jamais silencieuse.

---

## 2\. Spécification détaillée de l'Agent 1 — Assistant FAQ & Orientation

### 2.1 Mission

L'Agent 1 est le **point d'entrée utilisateur unique** du système. Il assure les fonctions d'accueil, d'information, de consultation en lecture seule et d'orientation.

Ses responsabilités, dans l'ordre où elles interviennent dans le graphe, sont les suivantes :

1. Recevoir le message utilisateur ainsi que le contexte de session vérifié par le Backend FastAPI.
2. Classifier l'intention du message entrant.
3. Répondre aux questions documentaires publiques via le pipeline RAG.
4. Pour un utilisateur authentifié, consulter certaines données bancaires personnelles en lecture seule, notamment le solde et l'historique des transactions, au moyen d'outils bancaires strictement limités.
5. Orienter un utilisateur non authentifié vers la connexion lorsqu'il demande l'accès à une donnée personnelle ou souhaite effectuer une opération sensible.
6. Détecter les demandes de virement et, uniquement lorsque l'utilisateur est authentifié, déléguer leur traitement à l'Agent 2 via le protocole A2A.

L'Agent 1 ne détient **aucune capacité d'écriture ou d'exécution d'une opération sensible** sur le système bancaire. Il peut uniquement consulter des données autorisées en lecture seule. Il ne peut ni créer, ni modifier, ni supprimer une donnée bancaire, et ne peut jamais exécuter directement un virement.

### 2.2 Moteur RAG

- **Base vectorielle** : ChromaDB, collection `faq_generale`.  
- **Contenu indexé** : documents publics uniquement (frais, procédures, conditions d'ouverture de compte, etc.).  
- **Contrainte stricte** : aucune donnée personnelle ou transactionnelle (solde, historique, identité) n'est jamais écrite dans ChromaDB. Les données personnelles consultées en lecture seule sont récupérées **à la volée** depuis le système bancaire à chaque requête, jamais mises en cache dans la base vectorielle.

### 2.3 Gestion de la session

L'Agent 1 ne détermine jamais lui-même si un utilisateur est authentifié. Ce statut lui est transmis par FastAPI, dans le champ `session_info.is_authenticated` de l'état d'entrée du graphe (voir §4.1). L'Agent 1 **fait confiance à cette valeur pour orienter la conversation**, mais cette confiance s'arrête à la frontière de l'Agent 1 : toute action sensible déléguée à l'Agent 2 est revalidée indépendamment (§3.2, contrôle n°1).

### 2.4 Règle d'aiguillage (nœud `route_decision`)

| Condition | `is_authenticated` | Comportement de l'Agent 1 |
| :---- | :---- | :---- |
| Question publique (FAQ) | Indifférent | Exécute le pipeline RAG et répond directement. |
| Demande de donnée personnelle (solde, historique) | `false` | **Refus d'exécution.** Aucun outil de lecture n'est invoqué. Réponse d'orientation vers la connexion. |
| Demande de donnée personnelle (solde, historique) | `true` | Invoque l'outil de lecture seule correspondant et restitue le résultat. |
| Demande de virement | `false` | **Refus d'exécution.** Aucune délégation à l'Agent 2 n'est déclenchée. Réponse d'orientation vers la connexion. |
| Demande de virement | `true` | **Invalide sa propre compétence d'exécution** et déclenche la délégation A2A vers l'Agent 2 (§4). |

> **Principe d'implémentation** : cette table est appliquée par une condition explicite dans le graphe (`add_conditional_edges`), jamais laissée à l'appréciation du prompt du LLM. Le modèle de langage peut se tromper sur l'intention détectée ; il ne peut pas se tromper sur la porte de sortie qu'on lui autorise à emprunter.

---

## 3\. Spécification détaillée de l'Agent 2 — Agent Transactionnel de Haute Sécurité

### 3.1 Mission

L'Agent 2 est l'unique composant du système autorisé à exécuter une opération financière. Il n'est **jamais contacté directement** par le client : il ne reçoit de tâche que via une délégation A2A émise par l'Agent 1\.

### 3.2 Séquence des 7 contrôles fonctionnels — référence unique

> **Table de référence normative.** La table ci-dessous est la **seule et unique** source de vérité pour la numérotation "Contrôle n°X" utilisée dans l'ensemble de la documentation (`DocsContext/01_projet_overview.md`, `04_scenarios_et_securite.md`, `CLAUDE.md`). Toute autre liste de mesures de sécurité (assainissement anti-injection, signature HMAC, journalisation, anti-rejeu, idempotence — voir `04_scenarios_et_securite.md`, §3) est une **mesure transverse**, appliquée en continu, mais n'est **jamais numérotée** dans cette séquence pour éviter toute ambiguïté de référence croisée.

La séquence est **incompressible** : chaque contrôle doit réussir avant que le suivant ne soit évalué. Un échec à n'importe quelle étape interrompt immédiatement le graphe et renvoie un statut `failed` avec le motif précis. Le nœud `validate_otp` (contrôle n°7) **n'est jamais sauté** : pour ce prototype, l'OTP est obligatoire pour tout virement, quel que soit le montant — il n'existe aucune notion de seuil conditionnel.

| \# | Contrôle | Nœud LangGraph | Échec → |
| :---- | :---- | :---- | :---- |
| 1 | Revalidation cryptographique du jeton de délégation A2A | `revalidate_auth` | `failed: unauthenticated` |
| 2 | Existence et éligibilité du bénéficiaire | `validate_beneficiary` | `failed: invalid_beneficiary` |
| 3 | Validité du montant (positif, format correct, `Decimal`) | `validate_amount` | `failed: invalid_amount` |
| 4 | Couverture du solde disponible | `validate_balance` | `failed: insufficient_funds` |
| 5 | Respect des plafonds journaliers/mensuels (`DAILY_TRANSFER_LIMIT`, `MONTHLY_TRANSFER_LIMIT`) | `validate_limits` | `failed: limit_exceeded` |
| 6 | Confirmation explicite de l'utilisateur | `request_confirmation` | `failed: user_cancelled` (ou passage en `input-required: confirmation`) |
| 7 | Vérification du résultat de validation OTP fourni par le service OTP déterministe — **obligatoire, sans exception, quel que soit le montant** | `validate_otp` | `failed: invalid_otp` (après 3 tentatives) ou `failed: otp_expired` (au-delà de 3 minutes) |

> **Traitement sécurisé de l'OTP** : le nœud `validate_otp` ne reçoit jamais le code OTP brut. Le code saisi par l'utilisateur est envoyé directement par le frontend vers un endpoint FastAPI dédié, puis vérifié par un service OTP déterministe. L'Agent 2 reçoit uniquement le résultat structuré de cette vérification, sous la forme `otp_verified=true` ou `otp_verified=false`, associé au `task_id` concerné. Le code OTP n'est jamais transmis à l'Agent 1, au LLM, au protocole A2A, aux messages LangChain ou au checkpointer LangGraph.

> **Contrôle n°1 — pourquoi une revalidation, et comment ?** L'Agent 1 a déjà transmis un statut d'authentification dans le contexte de délégation. L'Agent 2 ne considère jamais cette information comme acquise : il revalide **localement et cryptographiquement** le jeton de délégation A2A reçu (signature, émetteur, audience, expiration, portée, `task_id`, `jti` — voir §4.2). Pour ce MVP, cette validation locale est **suffisante** : aucun appel réseau supplémentaire vers un service d'authentification externe n'est nécessaire. Un simple champ `is_authenticated=true` transmis en clair n'est **jamais** considéré comme une preuve suffisante. Le jeton complet n'est **jamais journalisé** (voir `04_scenarios_et_securite.md`, §5).

### 3.3 Exécution

Ce n'est qu'après le succès **cumulé** des 7 contrôles que l'Agent 2 invoque l'outil `initiate_transfer` exposé via MCP (§5, étapes 8-9). Aucun chemin du graphe ne permet d'atteindre ce nœud d'exécution sans être passé par les 7 validations précédentes — il n'existe pas de bord (edge) direct vers le nœud d'exécution depuis un autre point du graphe.

---

## 4\. Protocole de communication A2A dans LangGraph

### 4.1 Structure du `SharedState`

L'état partagé constitue le contrat de données entre les nœuds d'un même agent, et la base à partir de laquelle est construit le message de délégation A2A. Il est défini comme suit :

from decimal import Decimal

from typing import TypedDict, Literal, Optional

from langchain\_core.messages import BaseMessage

class SessionInfo(TypedDict):

    user\_id: Optional\[str\]

    is\_authenticated: bool

    auth\_token: Optional\[str\]           \# jeton de session long terme (frontend ↔ FastAPI)

    auth\_timestamp: Optional\[str\]

class TransactionData(TypedDict):

    beneficiary: Optional\[str\]

    amount: Optional\[Decimal\]            \# jamais float — voir §4.1 note sur les montants

    currency: str                        \# ex. "MAD" (TRANSFER\_CURRENCY)

    reference: Optional\[str\]

    idempotency\_key: Optional\[str\]       \# créée avant exécution, propagée Agent 2 → MCP → n8n → mock-banking-api

    otp\_verified: bool

    validation\_steps: dict\[str, bool\]   \# ex. {"beneficiary": True, "amount": True, ...}

class SharedState(TypedDict):

    messages: list\[BaseMessage\]                 \# historique conversationnel pertinent

    session\_info: SessionInfo                   \# statut d'authentification

    active\_agent: Literal\["agent\_1", "agent\_2"\] \# agent actuellement responsable du tour (usage interne uniquement)

    transaction\_data: Optional\[TransactionData\] \# présent uniquement pendant un scénario de virement

    task\_status: Literal\[

        "idle", "submitted", "working",

        "input-required:confirmation", "input-required:otp",

        "completed", "failed", "cancelled", "expired"

    \]

| Champ | Portée | Remarque |
| :---- | :---- | :---- |
| `messages` | Local à chaque agent | Voir §4.2 — n'est **pas** transmis intégralement lors du handover. |
| `session_info` | Partagé, revalidé à chaque frontière d'agent | Jamais consommé comme une preuve définitive par l'agent qui le reçoit. |
| `active_agent` | Partagé, usage interne | Permet au Backend de savoir à quel agent adresser la prochaine réponse utilisateur. **Ne correspond pas** à la valeur `active_agent` exposée au frontend (`assistant` / `secure_operation`, voir `05_interface_frontend.md`, §4.5), qui reste un simple indicateur d'affichage. |
| `transaction_data` | Créé par l'Agent 1, complété par l'Agent 2 | `null` en dehors d'un scénario transactionnel. Les montants sont systématiquement du type `Decimal` en Python et transmis comme chaîne décimale en JSON (jamais `float`, pour éviter toute erreur d'arrondi binaire sur une opération bancaire). |
| `task_status` | Reflète le cycle de vie de la tâche A2A, persisté via le checkpointer (§4.5) | Distingue explicitement les deux natures d'`input-required` (confirmation vs OTP), et ajoute `cancelled` (annulation utilisateur) et `expired` (dépassement de `A2A_TASK_TTL_MINUTES`, voir §4.5). |

> **Pourquoi `Decimal` et jamais `float` ?** Un flottant binaire (IEEE 754) ne représente pas exactement des valeurs décimales comme `0.10` — inacceptable pour une opération financière irréversible. Toute la chaîne (`validate_amount`, `validate_balance`, `validate_limits`, l'outil MCP `initiate_transfer`, le payload envoyé à n8n et au mock-banking-api) manipule des `Decimal` côté Python et des chaînes décimales (`"1000.00"`, pas `1000.00` nombre JSON) sur le réseau.

### 4.2 Mécanisme de handshake et de transfert de contexte (State Handover)

Lorsque l'Agent 1 délègue une tâche, il ne transmet **pas** l'intégralité de son `SharedState` interne à l'Agent 2\. Un objet de délégation minimal est construit :

{

  "task\_id": "a2a-7f3e2b1c",

  "skill": "process\_bank\_transfer",

  "context": {

    "delegation\_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9....\<signature\>",

    "transaction\_data": {

      "beneficiary": "Mère — CIH ••••1042",

      "amount": "2000.00",

      "currency": "MAD",

      "idempotency\_key": "idem-9c1f4a7e-2026-07-25"

    }

  },

  "message": {

    "role": "user",

    "parts": \[{ "type": "text", "text": "Envoie 2000 MAD à ma mère" }\]

  }

}

> **Absence de fuite mémoire — principe du besoin d'en connaître.** Seuls trois éléments franchissent la frontière entre agents : (1) le jeton de délégation prouvant l'identité et l'autorisation, (2) les paramètres de la transaction extraits par l'Agent 1, (3) le message utilisateur déclencheur. L'historique complet des échanges FAQ précédents, les documents RAG consultés, ou toute autre donnée de contexte conversationnel de l'Agent 1 **ne sont jamais transmis**. L'Agent 2 démarre sa propre séquence de contrôles sans hériter d'aucun état de confiance implicite.

### 4.2bis Structure du jeton de délégation A2A

Le `delegation_token` n'est **jamais** un simple booléen ou une chaîne opaque arbitraire : c'est un jeton **signé, à courte durée de vie**, émis par le Backend (service d'authentification), distinct du token de session long terme utilisé par le frontend. L'Agent 1 **ne fabrique jamais lui-même** de preuve d'authentification — il ne fait que déclencher, auprès du Backend, l'émission de ce jeton au moment de la délégation.

Réclamations (*claims*) minimales obligatoires, une fois le jeton décodé :

{

  "sub": "usr\_48210",              // subject / customer\_id

  "task\_id": "a2a-7f3e2b1c",

  "scope": "bank\_transfer",

  "iss": "cih-ai-banking-auth",     // issuer

  "aud": "agent2",                  // audience

  "iat": 1785000000,                // issued\_at

  "exp": 1785000120,                // expiration (courte durée de vie, ex. 2 minutes)

  "jti": "9f3e2b1c-7f3e-4b1c-a2a0-000000000001"  // identifiant unique du jeton, anti-rejeu

}

**Revalidation côté Agent 2 (contrôle n°1, `revalidate_auth`)** — validation **purement locale et cryptographique**, sans appel réseau supplémentaire :

- vérification de la **signature** ;
- vérification de l'**issuer** (`iss`) ;
- vérification de l'**audience** (`aud == "agent2"`) ;
- vérification de l'**expiration** (`exp`) ;
- vérification du **scope** (`scope == "bank_transfer"`) ;
- cohérence du **`task_id`** avec la tâche A2A en cours ;
- unicité du **`jti`** (protection anti-rejeu — un jeton déjà consommé ne peut pas être réutilisé).

Le jeton complet (`delegation_token`) n'est **jamais journalisé**, y compris en cas d'échec de la revalidation — seul un statut booléen ou une empreinte tronquée peut apparaître dans les logs (voir `04_scenarios_et_securite.md`, §5).

### 4.3 Découverte de capacités via Agent Card

L'Agent 2 publie sa carte de capacités à une URL fixe (`/.well-known/agent.json`), consultée par l'Agent 1 avant toute délégation :

{

  "name": "cih-transaction-agent",

  "description": "Agent transactionnel de haute sécurité — exécution de virements bancaires",

  "url": "https://internal.cih-ai.local/a2a/agent2",

  "version": "1.0.0",

  "capabilities": {

    "streaming": true,

    "pushNotifications": false

  },

  "skills": \[

    {

      "id": "process\_bank\_transfer",

      "name": "Traiter un virement bancaire",

      "description": "Valide et exécute un virement après contrôle complet (auth, bénéficiaire, solde, plafond, confirmation, OTP).",

      "tags": \["banking", "transfer", "high-security"\]

    }

  \]

}

L'Agent 1 n'a donc jamais besoin de connaître l'implémentation interne de l'Agent 2 : il sait uniquement, par lecture de cette carte, que la compétence `process_bank_transfer` existe et quel contrat de données elle attend.

### 4.4 Cycle de vie de la tâche A2A

submitted ──▶ working ──▶ input-required:confirmation ──▶ working ──▶ input-required:otp ──▶ working ──▶ completed

                 │                    │                                      │                              │

                 │                    └──────────────▶ cancelled             │                              │

                 │                                                           │                              │

                 └───────────────────────────────▶ failed ◀──────────────────┴──────────────────────────────┘

                                    (toute tâche, quel que soit son état intermédiaire) ──▶ expired (si sans réponse > A2A_TASK_TTL_MINUTES)

| État | Signification |
| :---- | :---- |
| `submitted` | La tâche vient d'être créée par l'Agent 1. |
| `working` | L'Agent 2 exécute sa séquence de contrôles (§3.2). |
| `input-required: confirmation` | Le contrôle n°6 (`request_confirmation`) attend une action explicite de l'utilisateur côté frontend. |
| `input-required:otp` | Le contrôle n°7 (`validate_otp`) attend le résultat de la vérification effectuée par le service OTP déterministe. Le frontend collecte le code dans un écran dédié et l'envoie directement à FastAPI, sans passage par l'Agent 1, le LLM ou la tâche A2A. La fenêtre de validité de l'OTP est de **3 minutes**, indépendamment du TTL global de la tâche. |
| `completed` | Les 7 contrôles ont réussi et le virement a été exécuté avec succès. |
| `failed` | Un contrôle a échoué (motif explicite, ex. `insufficient_funds`, `invalid_otp`). |
| `cancelled` | L'utilisateur a explicitement annulé l'opération (ex. bouton "Annuler" de la `TransferConfirmationCard`). |
| `expired` | Aucune réponse reçue pendant plus de `A2A_TASK_TTL_MINUTES` (10 minutes par défaut) alors que la tâche était en `input-required:*` — la tâche est close automatiquement, l'utilisateur doit reformuler intégralement sa demande. |

---

### 4.5 Persistance et reprise de tâche (checkpointer SQLite)

Le cycle `input-required` (§4.4) implique que le graphe LangGraph de l'Agent 2 soit **interrompu puis repris** entre plusieurs requêtes HTTP distinctes. Ces deux interruptions ne suivent pas le même chemin :

- **Confirmation** : chemin conversationnel habituel, React → FastAPI → Agent 1 → A2A → Agent 2.
- **OTP** : chemin direct et séparé, React → FastAPI → service OTP déterministe. Après vérification, FastAPI transmet à l'Agent 2 uniquement un résultat structuré, jamais le code lui-même :

{

  "task\_id": "a2a-7f3e2b1c",

  "otp\_verified": true

}

Un backend FastAPI est **sans état** entre deux requêtes : sans mécanisme de persistance explicite, l'état interrompu du graphe serait perdu.

**Décision pour le MVP** : un **checkpointer SQLite** (`langgraph.checkpoint.sqlite`) persiste l'état complet du graphe de l'Agent 2 à chaque interruption.

- **Clé de reprise principale** : `task_id` (identifiant de la tâche A2A). Chaque appel de reprise (`invoke`/`resume` du graphe) est adressé avec ce même `task_id` comme `thread_id` du checkpointer.
- À réception d'une **confirmation**, le Backend relaie l'information via le chemin conversationnel (Agent 1 → A2A) avec le `task_id` reçu précédemment par le frontend ; l'Agent 2 charge l'état correspondant depuis SQLite et reprend l'exécution au nœud `request_confirmation`.
- À réception d'un **résultat de vérification OTP**, le Backend transmet directement à l'Agent 2 le couple `{task_id, otp_verified}` reçu du service OTP déterministe ; l'Agent 2 charge l'état correspondant depuis SQLite et reprend l'exécution au nœud `validate_otp` sans jamais recevoir le code brut.
- **Expiration de tâche** : `A2A_TASK_TTL_MINUTES=10` — une tâche en `input-required:*` sans réponse pendant 10 minutes passe automatiquement à `expired` (vérifié à la lecture du checkpoint, en comparant l'horodatage de dernière mise à jour à l'horloge courante).
- **Expiration de l'OTP** : indépendante du TTL de la tâche — un code OTP émis reste valide **3 minutes** ; passé ce délai, `input-required:otp` échoue avec `failed: otp_expired` même si la tâche globale n'a pas atteint son TTL de 10 minutes.
- Le fichier SQLite du checkpointer ne contient que l'état structuré du graphe (montants, statuts de validation, `task_id`) — jamais de secret en clair (le jeton de délégation et le code OTP ne sont jamais persistés tels quels dans un champ lisible sans contrôle d'accès équivalent à celui du reste du système).

---

## 5\. Flux de données end-to-end

### 5.1 Schéma général

┌────────────┐      HTTPS/JSON       ┌───────────────┐

│   React    │ ────────────────────▶ │    FastAPI     │

│ (Frontend) │ ◀──────────────────── │  (Middleware)  │

└────────────┘                       └───────┬────────┘

                                              │ SharedState initial

                                              ▼

                                    ┌───────────────────┐

                                    │  Agent 1 (LangGraph)│

                                    │  RAG · Routage      │

                                    └─────────┬───────────┘

                                              │ A2A Task (skill: process\_bank\_transfer)

                                              ▼

                                    ┌───────────────────┐

                                    │  Agent 2 (LangGraph)│

                                    │  7 contrôles stricts│

                                    └─────────┬───────────┘

                                              │ Appel outil (MCP)

                                              ▼

                                    ┌───────────────────┐

                                    │   Serveur MCP       │

                                    │  initiate\_transfer  │

                                    └─────────┬───────────┘

                                              │ HTTP POST (Webhook)

                                              ▼

                                    ┌───────────────────┐

                                    │   Workflow n8n       │

                                    └─────────┬───────────┘

                                              │ Appel API interne

                                              ▼

                                    ┌───────────────────┐

                                    │ Système Bancaire CIH│

                                    └─────────┬───────────┘

                                              │ Résultat opération

                                              ▼

                        (remontée symétrique : n8n → MCP → Agent 2 → Agent 1 → FastAPI → React)

### 5.2 Détail étape par étape

**Étape 1 — React → FastAPI**

POST /chat HTTP/1.1

Authorization: Bearer \<jwt\_session\_token\>

Content-Type: application/json

{ "message": "Envoie 2000 MAD à ma mère", "conversation\_id": "conv\_9f21" }

**Étape 2 — Middleware FastAPI** Le middleware décode le JWT, en extrait `user_id` et la validité de la session, puis construit l'état initial du graphe :

{

  "messages": \[{"role": "user", "content": "Envoie 2000 MAD à ma mère"}\],

  "session\_info": {"user\_id": "usr\_48210", "is\_authenticated": true},

  "active\_agent": "agent\_1",

  "transaction\_data": null,

  "task\_status": "idle"

}

**Étape 3 — Agent 1 (LangGraph)** Le nœud `classify_intent` détecte une intention de virement ; le nœud `route_decision` confirme `is_authenticated=true` et bascule `task_status` à `submitted`, avant de construire l'objet de délégation A2A décrit en §4.2.

**Étape 4 — Transmission A2A vers l'Agent 2**

POST /a2a/agent2/tasks HTTP/1.1

Content-Type: application/json

X-A2A-Source-Agent: cih-faq-agent

{ "task\_id": "a2a-7f3e2b1c", "skill": "process\_bank\_transfer", "context": { ... } }

**Étape 5 — Agent 2 (LangGraph)** Exécution séquentielle des 7 contrôles (§3.2). Si un `input-required` est déclenché (confirmation ou OTP), la réponse remonte immédiatement à l'Agent 1 avec le statut correspondant et la question à poser au client ; le cycle Backend/Frontend se répète jusqu'à réception du complément nécessaire.

**Étape 6 — Invocation de l'outil MCP**

{

  "jsonrpc": "2.0",

  "method": "tools/call",

  "params": {

    "name": "initiate\_transfer",

    "arguments": {

      "user\_id": "usr\_48210",

      "beneficiary": "ben\_1042",

      "amount": "2000.00",

      "currency": "MAD",

      "idempotency\_key": "idem-9c1f4a7e-2026-07-25"

    }

  }

}

> **Montant en chaîne décimale.** `amount` est toujours transmis comme chaîne (`"2000.00"`), jamais comme nombre JSON — un nombre JSON est désérialisé en `float`/`double` dans la plupart des runtimes, ce qui réintroduirait le risque d'imprécision qu'un type `Decimal` côté Python cherche justement à éviter (voir §4.1).

**Étape 7 — Webhook n8n**

POST https://n8n.internal.cih-ai.local/webhook/execute-transfer HTTP/1.1

Content-Type: application/json

X-Webhook-Signature: sha256=\<hmac\_signature\>

{ "user\_id": "usr\_48210", "beneficiary\_id": "ben\_1042", "amount": "2000.00", "currency": "MAD", "task\_id": "a2a-7f3e2b1c", "idempotency\_key": "idem-9c1f4a7e-2026-07-25" }

La signature HMAC (`X-Webhook-Signature`) permet à n8n de vérifier que l'appel provient bien du serveur MCP autorisé, et non d'une source externe non authentifiée. L'`idempotency_key` est propagée sans modification jusqu'au mock-banking-api : une même clé ne peut produire qu'un seul virement, même en cas d'appel dupliqué (retry réseau, timeout) — voir `DocsContext/04_scenarios_et_securite.md`, §3 (mesures transverses) pour la politique complète d'idempotence et de retry.

**Étape 8 — Exécution bancaire (simulée)** Le workflow n8n appelle le service `mock-banking-api` (`POST /internal/transfers`, voir `03_stack_technique.md`) pour exécuter l'opération simulée, enregistre la transaction et déclenche une notification (SMS/email simulée) au client.

**Étape 9 — Remontée du résultat**

{ "status": "success", "transaction\_id": "TX-2026-0723-00417", "executed\_at": "2026-07-23T10:42:11Z", "idempotency\_key": "idem-9c1f4a7e-2026-07-25" }

Ce résultat remonte en sens inverse : n8n → réponse HTTP au serveur MCP → retour de l'outil à l'Agent 2 → clôture de la tâche A2A à `completed` → transmission à l'Agent 1 → réponse FastAPI → affichage React.

> **Symétrie du flux.** Le chemin de retour emprunte exactement les mêmes frontières que le chemin aller, dans l'ordre inverse. Aucun composant ne communique directement avec un composant situé à plus d'un saut de lui dans la chaîne (le Backend ne parle jamais directement à n8n, l'Agent 1 ne parle jamais directement au serveur MCP) — cette discipline garantit que chaque frontière reste un point de contrôle et d'audit possible.  
