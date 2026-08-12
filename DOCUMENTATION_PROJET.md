# CIH AI Banking — Documentation technique complète

> **But de ce document** : donner à un assistant IA (ChatGPT, Claude…) ou à un
> nouveau développeur une compréhension complète et autonome du projet, sans
> avoir accès au dépôt. Il décrit l'état **réel et vérifié** du code au
> 11 août 2026, pas l'intention initiale.
>
> **Nature du projet** : prototype **académique** (PFE, ENSAM). Toutes les
> données bancaires sont fictives. Aucune connexion à un système bancaire réel.

---

## 1. Le projet en une phrase

**CIH AI Banking** est un assistant bancaire conversationnel qui répond aux
questions générales (FAQ publique) et personnelles (solde, transactions,
carte, bénéficiaires) en **français, en darija marocaine (écriture arabe) et
en Arabizi (darija en alphabet latin)**, avec une architecture de sécurité où
**aucune protection ne dépend du bon vouloir du LLM**.

Le principe directeur, répété partout dans le code : *le LLM aide à
comprendre, il ne décide jamais d'un accès*. Toutes les décisions de sécurité
(authentification requise, refus d'une donnée sensible) sont prises par du
code déterministe, évalué **avant** et **indépendamment** de toute sortie de
modèle de langage.

---

## 2. Stack technique

| Couche | Technologie |
|---|---|
| Frontend | React 18 + Vite + TailwindCSS 3 + `lucide-react` |
| Backend API | FastAPI + Uvicorn (Python 3.11+) |
| Orchestration IA | LangGraph (graphe d'états de l'Agent 1) |
| LLM principal | **Mistral via Ollama, en local** (jamais d'API cloud pour les données bancaires) |
| LLM secondaire | Google Gemini — questions **hors domaine bancaire** uniquement |
| RAG | ChromaDB, embedding **local et déterministe** (pas de `sentence-transformers`) |
| Bases de données | SQLite (3 fichiers séparés) |
| Mots de passe | bcrypt |
| Tests | pytest (backend), vitest + @testing-library/react (frontend) |
| Conteneurisation | Docker Compose (3 services : ollama, backend, frontend) |

**Choix structurant** : Mistral tourne **en local via Ollama**. Aucune donnée
bancaire ne sort de la machine. Gemini n'est appelé que pour les questions
sans rapport avec la banque (météo, culture générale…).

---

## 3. Arborescence réelle

```
cih-ai-banking/
├── CLAUDE.md                    # Règles de contribution (source de vérité)
├── DocsContext/                 # 5 documents de spécification
│   ├── 01_projet_overview.md
│   ├── 02_architecture_multi_agents.md
│   ├── 03_stack_technique.md
│   ├── 04_scenarios_et_securite.md
│   └── 05_interface_frontend.md
│
├── agents/
│   ├── router/
│   │   ├── router.py                      # Aiguillage Agent 1 / General Agent
│   │   └── conversational_understanding.py # Garde déterministe "banking vs general"
│   ├── agent1_faq/                        # LE CŒUR DU PROJET
│   │   ├── graph.py                       # Graphe LangGraph (orchestrateur)
│   │   ├── classification.py              # Classification déterministe 4 buckets
│   │   ├── banking_answers.py             # Sous-intentions + réponses personnelles
│   │   ├── llm_router.py                  # Appel Mistral (compréhension fine)
│   │   ├── rag.py                         # Embedding local + recherche ChromaDB
│   │   ├── language_detection.py          # fr / darija_ar / darija_latn
│   │   ├── darija_normalization.py        # Darija → français canonique
│   │   ├── response_localizer.py          # Réponses localisées en darija
│   │   ├── conversation_memory.py         # Contexte court terme
│   │   ├── conversational.py              # Salutations, small talk
│   │   └── tools.py                       # Outils de lecture seule
│   ├── agent2_transaction/                # VIDE (.gitkeep) — jamais implémenté
│   └── general_agent/                     # Gemini (hors domaine bancaire)
│       ├── general_agent.py
│       ├── gemini_client.py
│       └── gemini_key_manager.py          # Rotation de 3 clés API
│
├── backend/
│   ├── app/
│   │   ├── main.py                        # Application FastAPI
│   │   ├── routers/
│   │   │   ├── auth.py                    # /api/auth/login, /session, /logout
│   │   │   └── chat.py                    # /api/chat
│   │   ├── banking/banking_db.py          # Base bancaire métier (SQL brut)
│   │   ├── chatbot/chatbot_db.py          # Base traces chatbot (phase 1)
│   │   └── security/session_manager.py    # Sessions + bcrypt
│   ├── data/
│   │   ├── demo_bancaire.db               # BASE ACTIVE (100 clients)
│   │   └── banking.db                     # Ancienne base (sauvegarde)
│   └── tests/                             # 27 fichiers, 746 tests
│
├── frontend/src/
│   ├── App.jsx
│   ├── context/BankingAppProvider.jsx     # État partagé UNIQUE
│   ├── components/
│   │   ├── ResponsiveShowcase.jsx         # Mobile + desktop simultanés
│   │   ├── PhonePreview.jsx / DesktopView.jsx
│   │   ├── chat/                          # ChatWidget, ChatMessage, OtpModal…
│   │   ├── mobile/ desktop/ shared/
│   └── data/                              # Données mockées + authApi.js
│
├── scripts/
│   ├── seed_demo_database.py              # Génère les 100 clients
│   ├── migrate_banking_database.py        # Ancien schéma → nouveau
│   ├── seed_auth_users.py
│   ├── seed_banking_data.py
│   └── ingest_faq.py                      # FAQ → ChromaDB
│
├── data/
│   ├── faq_docs/faq.json                  # 100 questions FAQ publiques
│   ├── auth/users_seed.json
│   ├── demo/moroccan_names.json           # Noms marocains (génération)
│   └── banking_keywords.json              # ~440 mots-clés bancaires multilingues
│
├── auth.db                                # Sessions uniquement
├── chroma_db/                             # Index vectoriel FAQ (gitignored)
├── docker-compose.yml
└── .env / .env.example
```

---

## 4. Architecture de traitement d'un message

```
Utilisateur (React)
      │  POST /api/chat  { message }  + Authorization: Bearer <session_id>
      ▼
backend/app/routers/chat.py
      │  _resolve_session() → auth.db (sessions) + demo_bancaire.db (utilisateur)
      │  → (is_authenticated, user_id=id_client)
      ▼
agents/router/router.py :: route_message()
      │  conversational_understanding.classify_domain()
      │    ├─ GARDE DÉTERMINISTE : ~440 mots-clés bancaires (banking_keywords.json)
      │    │  + tolérance aux fautes de frappe (difflib, cutoff 0.82)
      │    │  → si mot bancaire détecté : "banking" SANS appeler Mistral
      │    └─ sinon : Mistral tranche, repli "banking" par défaut
      │
      ├─ domain = "general" → agents/general_agent (Gemini)
      └─ domain = "banking" → agents/agent1_faq/graph.py
                                    │
                                    ▼
              ┌──────────── GRAPHE LANGGRAPH (Agent 1) ────────────┐
              │                                                     │
              │  1. security_guard                                  │
              │     detect_sensitive_operation()                    │
              │     → "virement" / "compte_action" → REFUS IMMÉDIAT │
              │       (Mistral n'est JAMAIS consulté dans ce cas)   │
              │                                                     │
              │  2. conversational_understanding                    │
              │     salutations, remerciements, small talk          │
              │                                                     │
              │  3. llm_router (Mistral)  ← PRIMAIRE                │
              │     extraction d'intention fine                     │
              │     échec/timeout/"unclear" → None                  │
              │                                                     │
              │  4. classify_fallback  ← REPLI DÉTERMINISTE         │
              │     classification.classify_intent()                │
              │     4 buckets : virement | compte_action |          │
              │                 personal_data | faq_generale        │
              │                                                     │
              │  5. route_decision                                  │
              │     personal_data + non authentifié → require_login │
              │                                                     │
              │  6a. answer_personal_data                           │
              │      banking_answers.build_personal_data_answer()   │
              │  6b. answer_faq → RAG ChromaDB (+ reranking Mistral)│
              └─────────────────────────────────────────────────────┘
                                    │
                                    ▼
                      ChatResponse { intent, requires_auth, response }
```

**Propriété essentielle** : le système fonctionne **entièrement sans Mistral**.
Si Ollama est éteint, indisponible ou renvoie `"unclear"`, le repli
déterministe prend le relais sans que l'utilisateur voie la moindre erreur.
64 tests couvrent explicitement ces trois états de défaillance.

---

## 5. Les trois bases de données

Séparation volontaire. SQLite n'autorisant pas de `FOREIGN KEY` entre
fichiers, les liaisons inter-bases se font **par valeur**, jamais par
contrainte physique.

### 5.1 `backend/data/demo_bancaire.db` — base bancaire métier

```
CLIENT (id_client PK, nom, prenom, telephone_mobile, email,
        statut_client, date_creation)
   │
   ├─1:1─ UTILISATEUR_E_BANKING (id_utilisateur PK, id_client FK,
   │        identifiant_connexion, mot_de_passe_hash [bcrypt],
   │        statut_connexion, derniere_connexion, date_creation)
   │
   ├─1:N─ COMPTE_BANCAIRE (id_compte PK, id_client FK, numero_compte,
   │        │   numero_compte_masque, rib, iban, type_compte, devise,
   │        │   solde_disponible, date_creation)
   │        │
   │        ├─1:N─ account_balance_history (id_compte, as_of_date, solde)
   │        │
   │        ├─1:N─ "TRANSACTION" (id_transaction PK, id_compte FK,
   │        │        date_operation, type_operation, sens, libelle,
   │        │        categorie, montant, devise, id_compte_lie)
   │        │
   │        └─1:1─ CARTE_BANCAIRE (id_carte PK, id_compte FK,
   │                 numero_carte_masque, type_carte, date_expiration,
   │                 statut_carte, plafond_paiement, plafond_retrait,
   │                 paiement_en_ligne_actif, paiement_international_actif)
   │
   └─1:N─ BENEFICIAIRE (id_beneficiaire PK, id_client FK, nom_beneficiaire,
            rib, numero_compte_masque, statut, eligible_virement)
```

Notes importantes :
- `TRANSACTION` est un **mot réservé SQL** : toujours entre guillemets doubles.
- `account_balance_history` est en minuscules (héritage), elle alimente la
  question « quel était mon solde au 1er janvier ? ».
- **`CARTE_BANCAIRE` ne stocke QUE le numéro masqué** (`450078XXXXXX7007`).
  Le numéro complet (PAN) n'existe nulle part dans le projet, pas même en
  mémoire pendant la génération.
- Les montants sont **toujours** des `Decimal` Python, stockés en **chaîne
  de caractères** (`TEXT`), jamais en flottant.

### 5.2 `auth.db` — sessions uniquement

```
users    (LEGACY, conservée pour compatibilité de transition)
sessions (session_id PK, user_id, created_at, expires_at)
```

`session_id` est une chaîne opaque (`secrets.token_urlsafe(32)`), **jamais un
JWT**. Expiration : 30 minutes.

### 5.3 `backend/data/chatbot.db` — traces conversationnelles (PHASE 1)

```
CHATBOT_SESSION    (id_session PK, id_utilisateur, date_debut, date_fin, canal)
CHATBOT_MESSAGE    (id_message PK, id_session FK, expediteur, texte_message,
                    date_heure, intention_detectee, score_confiance)
CHATBOT_EVALUATION (id_evaluation PK, id_message FK, vote, commentaire)
```

**Le schéma existe mais AUCUNE écriture n'est branchée.** `chat.py` ne
l'importe pas. Un test verrouille cette décision et échouera si quelqu'un
branche l'écriture sans passer par une phase 2 explicite.

---

## 6. Sécurité — les cinq mécanismes

### 6.1 Security Guard (`classification.detect_sensitive_operation`)

Détecte les opérations sensibles (virement, blocage de carte, modification de
plafond) **avant tout appel LLM**. Ces demandes reçoivent toujours :
« Ce service n'est pas disponible pour le moment. » Mistral n'est jamais
consulté — testé explicitement.

### 6.2 Authentification obligatoire pour les données personnelles

`route_decision` renvoie vers `require_login` si `personal_data` et pas de
session valide. `requires_auth` est calculé **depuis la session**, jamais
recalculé depuis une sortie LLM.

### 6.3 Isolation entre clients

Chaque fonction de lecture exige un `customer_id` explicite et filtre par
`WHERE id_client = ?`. Aucun identifiant d'objet ne transite par l'URL : le
client ne peut structurellement demander que ses propres données (pas d'IDOR).

### 6.4 Protection du numéro de carte

```
"Donne-moi mon numéro de carte"
        ↓
classification.py — _PERSONAL_DATA_PATTERNS
   \bnumero\b.{0,20}\bcartes?\b   → personal_data (session exigée)
        ↓
banking_answers.py — _requests_card_number()
   ÉVALUÉ AVANT la sortie de Mistral ET avant toute lecture en base
        ↓
intent = "card_number_redirect"
        ↓
CARD_NUMBER_REDIRECT_MESSAGE
   « Pour votre sécurité, je ne peux pas afficher le numéro complet de votre
     carte dans cette conversation. […] connectez-vous à votre espace client
     sécurisé, rubrique « Mes cartes », ou rendez-vous en agence. »
```

Trois couches : le PAN n'existe pas en base · `_CARD_FIELD_ORDER` n'expose
aucun champ de numéro · refus explicite prioritaire sur le LLM.

### 6.5 Anti-prompt-injection

Séparation stricte instructions système / message utilisateur, validation
Pydantic des sorties, allowlist d'outils, refus systématique des instructions
de contournement. **La détection d'injection ne remplace jamais les contrôles
programmatiques** — elle s'y ajoute.

---

## 7. Support multilingue (français / darija / Arabizi)

```
Message utilisateur
      ↓
language_detection.detect_language()  →  "fr" | "darija_ar" | "darija_latn"
      ↓  (si ≠ fr)
darija_normalization.normalize_darija_message()
      │  _PHRASE_MAP  (65 entrées)  — phrases entières irrégulières
      │  _WORD_MAP   (101 entrées)  — tokens, appliqués par longueur décroissante
      ↓
Forme française canonique  →  classification déterministe habituelle
      ↓
response_localizer  →  réponse rendue dans la langue d'origine
```

Exemples réels :
- `ch7al baqi lia` → `combien me reste` → `total_balance`
- `بغيت نشوف الحساب ديالي` → `quelles sont les informations de mon compte`
- `tafasil dyal lkarta` → `quel est le statut de ma carte` → `card_information`

Couverture mesurée sur 107 formulations : **100 % (53 FR, 33 Arabizi, 21 arabe)**,
contre 63 % avant enrichissement.

---

## 8. RAG — recherche FAQ

`agents/agent1_faq/rag.py` implémente `HashingBagOfWordsEmbedding` :

- **1024 dimensions**, hachage CRC32, normalisation L2, distance cosinus
- **Stemming léger français** intégré dans `_tokenize()` : deux phases
  (pluriel puis un seul suffixe), avec trois protections contre les faux
  positifs (racine minimale de 4 caractères, liste d'invariants, tokens
  non alphabétiques intacts)
- **100 % local, déterministe, sans téléchargement de modèle**

Protection contre les embeddings obsolètes : le nom versionné
(`hashing-bag-of-words-v2`) et une vérification de dimension lèvent
`FaqEmbeddingDimensionMismatchError` avec la commande exacte à lancer.

⚠️ **Après tout changement d'embedding : `python scripts/ingest_faq.py`
est obligatoire.**

---

## 9. API HTTP

### `POST /api/auth/login`
```json
Requête  : { "username": "malakdrissi2005@gmail.com", "password": "..." }
Réponse  : { "session_id": "...", "expires_at": "2026-08-11T11:31:32+00:00" }
```
Le champ `username` accepte **un identifiant OU une adresse e-mail**
(insensible à la casse). 401 si invalide ou compte bloqué.

### `GET /api/auth/session`
En-tête `Authorization: Bearer <session_id>` →
`{ authenticated, user_id, username, expires_at }`

### `POST /api/auth/logout`

### `POST /api/chat`
```json
Requête  : { "message": "Quel est mon solde ?" }
Réponse  : { "intent": "personal_data", "requires_auth": false,
             "response": "Le total de vos comptes est de 106318.39 MAD (...)" }
```
Session **facultative** : sans elle, les questions FAQ publiques fonctionnent,
les questions personnelles renvoient une invitation à se connecter.

---

## 10. Intentions reconnues

| Intention | Exemple | Source |
|---|---|---|
| `total_balance` | « Quel est mon solde ? » | `COMPTE_BANCAIRE.solde_disponible` |
| `balance_at_date` | « Mon solde au 1er janvier ? » | `account_balance_history` |
| `recent_transactions` | « Mes dernières opérations » | `"TRANSACTION"` (5 dernières) |
| `spending_by_category` | « Combien dépensé en restaurants ? » | agrégation par catégorie |
| `card_information` | « Le statut de ma carte ? » | `CARTE_BANCAIRE` |
| `card_number_redirect` | « Mon numéro de carte complet » | **refus + redirection** |
| `beneficiaries` | « Mes bénéficiaires ? » | `BENEFICIAIRE` |
| `salary` | « Mon salaire est-il arrivé ? » | transactions `salary` |
| `last_direct_debit` | « Dernier prélèvement ? » | transactions `direct_debit` |
| `payments` | « Mes paiements du mois » | transactions `card_payment` |
| `assistant_explain` | question personnelle sans outil précis | liste des capacités |

**L'ordre d'évaluation compte** : la chaîne est « premier match gagne ».
`card_number_redirect` est évaluée en premier, la règle générique de synthèse
de compte en dernier — pour ne jamais voler un message à une intention plus
précise.

---

## 11. Frontend

Application React **unique** avec deux rendus **simultanés et synchronisés** :

- **≥ 900 px** : téléphone interactif à gauche + vue desktop agrandie à droite
- **640–899 px** : vue desktop seule
- **< 640 px** : application mobile plein écran

`BankingAppProvider` détient l'**état partagé unique** (session, messages,
écran actif). Les deux panneaux le lisent — aucune divergence possible.
Il existe **un seul `ChatWidget`**, monté une fois, contrôlé par deux boutons.

`ChatMessage.jsx` gère quatre types de messages : `text`,
`transfer_confirmation`, `otp_request`, `transfer_result`.

**Limites actuelles du frontend** :
- Pas de `react-router`, pas de navigation entre écrans
- L'onglet « Cartes » de `BottomNav` est décoratif (aucun `onClick`)
- `ChatResponse` ne transporte que du texte : impossible d'afficher un bouton
  d'action sans étendre le contrat d'API

---

## 12. Données de démonstration

`python scripts/seed_demo_database.py` génère **100 clients**, de façon
**strictement déterministe** (`random.Random(20242025)`, dates ancrées sur
`DEMO_REFERENCE_DATE = 2026-07-28`, identifiants dérivés de l'index).

| Entité | Volume |
|---|---|
| Clients / utilisateurs e-banking | 100 / 100 |
| Comptes bancaires | 196 (1 à 3 par client, toujours un courant) |
| Transactions | 3 024 (11 à 50 par client) |
| Cartes | 100 (Visa Classic, Visa Gold, Mastercard) |
| Bénéficiaires | 253 (1 à 4 par client) |
| Soldes | 651 à 99 632 MAD |

**Compte de démonstration — `CL0001`** :
- Malak Drissi · `malakdrissi2005@gmail.com` · identifiant `malak.drissi`
- Solde total : **106 318,39 MAD**
- Seul le hash bcrypt est en base ; le mot de passe clair n'est jamais stocké

Seuls **2 hashs bcrypt** sont calculés (bcrypt coûte ~307 ms : 100 hashs
prendraient 30 s). `CL0001` a le sien ; les 99 comptes fictifs partagent un
mot de passe de démonstration commun.

---

## 13. Tests

**746 tests, 8 ignorés, 0 échec** — validés sur deux exécutions (ordre fixe et
aléatoire).

| Fichier | Objet |
|---|---|
| `test_classification.py` | Classification déterministe, faux positifs |
| `test_banking_answers.py` | Sous-intentions, ordre de priorité |
| `test_darija.py` | Darija/Arabizi/arabe, 39 cas par intention |
| `test_faq_rag.py` | Embedding, stemming, dimension 1024 |
| `test_card_number_protection.py` | Refus du numéro de carte (18 tests) |
| `test_demo_end_to_end.py` | **Parcours HTTP complet** (18 tests) |
| `test_demo_database.py` | 100 clients, déterminisme, bcrypt |
| `test_auth_ebanking.py` | Login email, sessions deux sources |
| `test_migration_banking_database.py` | Migration, source jamais modifiée |
| `test_llm_first_routing.py` | 3 états de défaillance de Mistral |

Convention : **tous les appels à Ollama et Gemini sont mockés**. Chaque test
crée ses propres bases dans `tmp_path`. La suite est rapide (~60 s) et
hermétique.

`test_ollama_integration.py` teste contre un Ollama réel — **désactivé par
défaut**.

---

## 14. Lancement

```bash
# 1. Dépendances
cd backend && pip install -r requirements.txt
cd ../frontend && npm install

# 2. Configuration
cp .env.example .env        # puis renseigner GEMINI_API_KEY_*

# 3. Données (obligatoire au premier lancement)
python scripts/seed_demo_database.py    # 100 clients
python scripts/ingest_faq.py            # index vectoriel FAQ

# 4. Ollama
ollama pull mistral && ollama serve

# 5. Application
cd backend && uvicorn app.main:app --reload   # http://localhost:8000
cd frontend && npm run dev                     # http://localhost:5173

# Alternative : docker compose up --build
```

Connexion de démonstration : `malakdrissi2005@gmail.com` / `UnivEnsam20242025?!`

Questions à essayer : « Quel est mon solde ? » · « Mes dernières
transactions » · « Quelle est ma carte ? » · « Mes bénéficiaires ? » ·
« ch7al baqi lia » · « شحال باقي ليا » · et surtout **« Donne-moi mon numéro
de carte complet »**.

---

## 15. État d'avancement et limites connues

**Implémenté et testé** : Agent 1 complet (FAQ + données personnelles),
support trilingue, RAG local, authentification bcrypt, protection du numéro
de carte, base 100 clients, frontend synchronisé, Docker.

**Non implémenté** :
- **Agent 2 transactionnel** — `agents/agent2_transaction/` ne contient qu'un
  `.gitkeep`. Aucun virement n'est exécutable. Les demandes sont refusées par
  le Security Guard.
- **Protocole A2A**, **MCP**, **n8n**, **mock-banking-api** — prévus par la
  documentation initiale, jamais développés.
- **OTP** — `OtpModal.jsx` existe côté frontend, sans backend.
- **Écriture des traces chatbot** — schéma prêt, branchement en phase 2.

**Limites documentées** :
- `faq_009` (« Puis-je changer le type de mon compte… ») reste mal classée en
  `personal_data`. Corriger via un garde sur « puis-je » casserait « Puis-je
  consulter mon solde ? ». Limite assumée.
- La darija n'ayant pas d'orthographe standardisée, une variante non listée et
  sans marqueur reconnu reste non couverte.
- Le client `CL0001` porte des coordonnées **réelles** (celles de
  l'étudiante), par exception explicite à la règle « 100 % fictif ».
- `chroma_db/` est dans `.gitignore` : `ingest_faq.py` doit être relancé sur
  chaque poste.

---

## 16. Règles de contribution (extraits de `CLAUDE.md`)

1. Ne jamais laisser une décision de sécurité dépendre du LLM.
2. Ne jamais permettre à l'Agent 1 d'exécuter une opération bancaire.
3. Ne jamais journaliser un secret en clair (OTP, mot de passe, hash, jeton).
4. Ne jamais utiliser `float` pour un montant — `Decimal` en Python, chaîne
   décimale en JSON et en base.
5. Ne jamais laisser diverger l'état entre le panneau mobile et le panneau
   desktop — une seule source d'état partagée.
6. Tout nouvel écran ou composant de chat riche doit d'abord être décrit dans
   `DocsContext/05_interface_frontend.md` **avant** implémentation.
7. Toute évolution du calcul d'embedding doit incrémenter le numéro de version
   dans `HashingBagOfWordsEmbedding.name()`.

---

## 17. Points saillants pour une présentation

**L'argument central** : la sécurité ne repose jamais sur le LLM. Chaque
protection est une porte fermée par défaut, ouverte uniquement par une
vérification programmatique. Démontrable en éteignant Ollama : le système
continue de fonctionner et de protéger.

**Le support trilingue** est déterministe et sans modèle de traduction :
normalisation vers une forme canonique française, puis classification
habituelle. Coût nul en latence, comportement reproductible.

**La protection du numéro de carte** illustre la défense en profondeur : la
donnée n'existe pas en base, aucun champ ne l'expose, et le refus est
prioritaire sur le LLM. Trois couches indépendantes.

**Le déterminisme** est une propriété testée, pas un espoir : embedding,
génération des 100 clients et classification produisent des résultats
identiques à chaque exécution.
