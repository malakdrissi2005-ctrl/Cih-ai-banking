# 03 — Stack Technique : CIH AI Banking

> **Type de document** : Référence technique — pile technologique, justification des choix, configuration **Prérequis** : `01_projet_overview.md`, `02_architecture_multi_agents.md` **Rôle de ce document** : Fixer la liste exacte des technologies retenues, les versions minimales recommandées, la justification technique et sécuritaire de chaque choix structurant, ainsi que la configuration de référence pour démarrer un environnement de développement conforme.

---

## 1\. Rôle du document

Ce document répond à la question *« avec quoi, précisément, construit-on ce système ? »*. Il complète `02_architecture_multi_agents.md` (qui décrit le *comportement*) en fixant :

- la liste normative des technologies et leurs versions minimales ;  
- la justification de chaque choix structurant, du point de vue technique **et** sécuritaire — un critère aussi important que l'autre dans un contexte bancaire ;  
- l'arborescence de référence et les fichiers de configuration à reproduire à l'identique en début de projet.

>   
> Toute introduction d'une nouvelle dépendance structurante (nouveau framework, nouveau service externe) doit être ajoutée à ce document avant d'être mergée dans le code — ce fichier ne doit jamais être en retard sur l'état réel du projet.

---

## 2\. Tableau synthétique de la stack technique

| Couche | Technologie | Version minimale recommandée | Rôle |
| :---- | :---- | :---- | :---- |
| Frontend | React.js | 18.x | Interface conversationnelle et écrans de confirmation/OTP |
| Frontend — style | TailwindCSS | 3.x | Charte graphique CIH Bank (couleurs, densité, composants) |
| Frontend — icônes | lucide-react | 0.4xx | Bibliothèque d'icônes cohérente et légère |
| Backend API | FastAPI | 0.115+ | Endpoints, gestion des sessions et des tokens, exposition de l'endpoint sécurisé de validation OTP |
| Backend — serveur ASGI | Uvicorn | 0.30+ | Serveur d'exécution de FastAPI |
| Service OTP du prototype | `MockOtpService` interne | — | Vérification déterministe du code OTP via FastAPI ; seul le résultat booléen est transmis à l'Agent 2 |
| Langage backend | Python | 3.11+ | Requis par les typages modernes utilisés dans le `SharedState` |
| Orchestration IA | LangChain | 0.3+ | Primitives d'appel LLM, outils, gestion des prompts |
| Orchestration multi-agents | LangGraph | 0.2+ | Graphe d'états, cycles, interruptions humaines |
| Communication inter-agents | A2A (`a2a-sdk`) | 1.1+ | Délégation de tâches entre Agent 1 et Agent 2 |
| Modèle de langage | Mistral | 7B / Mistral-Nemo | Modèle de raisonnement des deux agents |
| Exécution du LLM | Ollama | 0.3+ | Serveur d'inférence local du modèle Mistral |
| Base vectorielle (RAG) | ChromaDB | 0.5+ | Indexation et recherche sémantique de la FAQ publique |
| Protocole d'accès aux outils | MCP (`mcp` SDK Python) | 1.0+ | Exposition standardisée des outils de l'Agent 2 |
| Automatisation métier | n8n | dernière version stable (self-hosted) | Exécution des workflows bancaires (virement, notification) |
| Sécurité des webhooks | HMAC-SHA256 | — | Authentification des appels entre le serveur MCP et n8n |
| Authentification | JOSE / JWT (`python-jose`) | 3.3+ | Émission et vérification des tokens de session |

> Les versions indiquées sont des **planchers**, pas des cibles figées : vérifier la dernière version stable de chaque composant au moment de l'implémentation, et documenter ici toute montée de version majeure.

---

## 3\. Justification stratégique et sécuritaire des choix

### 3.1 Pourquoi Mistral \+ Ollama en local ?

- **Confidentialité bancaire absolue (Zero Data Leakage)** : aucune donnée client, aucune conversation, aucun contenu de FAQ interne ne transite vers une API cloud tierce (OpenAI, Anthropic, ou tout autre fournisseur externe). L'inférence a lieu entièrement sur l'infrastructure de la banque.  
- **Conformité réglementaire** : dans un contexte bancaire, l'exigence de non-transmission de données à caractère personnel ou financier vers des tiers est structurante. L'exécution locale supprime la question même de la conformité d'un sous-traitant externe.  
- **Indépendance vis-à-vis d'Internet** : le système reste opérationnel même en cas de coupure de connectivité externe — pertinent pour un service considéré comme critique.  
- **Coût prévisible** : pas de facturation à l'appel API, donc un coût d'exploitation indépendant du volume de conversations.

**Contrepartie assumée** : un modèle local comme Mistral est moins puissant qu'un modèle frontière propriétaire. Ce compromis est jugé acceptable car les deux agents ont des périmètres volontairement restreints (§02, séparation des responsabilités) — un modèle plus modeste suffit à un rôle borné et spécialisé.

### 3.2 Pourquoi LangGraph plutôt que LangChain seul ?

LangChain seul excelle pour des chaînes d'appels linéaires (prompt → LLM → sortie), mais ce projet a trois besoins que LangGraph adresse spécifiquement :

- **Gestion d'états cycliques et complexes** : la séquence des 7 contrôles de l'Agent 2 (`02_architecture_multi_agents.md`, §3.2) n'est pas un pipeline linéaire — elle comporte des branches d'échec, des retours, et un état (`SharedState`) qui doit être lu et enrichi par chaque nœud.  
- **Support natif du multi-agent** : LangGraph permet de modéliser chaque agent comme un graphe indépendant, tout en formalisant proprement la frontière de délégation entre eux (§02, §4).  
- **Interruptions natives pour la validation humaine** : le mécanisme d'interruption de LangGraph (`interrupt` / reprise de graphe) correspond aux étapes `input-required` du cycle A2A. Pour la confirmation, le graphe attend une action explicite de l'utilisateur. Pour l'OTP, il attend uniquement le résultat structuré de la vérification effectuée par FastAPI et le service OTP déterministe. Le code OTP brut n'est jamais transmis au graphe, au LLM, à l'Agent 1 ou à la tâche A2A. Après réception du résultat `otp_verified`, le graphe reprend exactement là où il s'était arrêté, sans reconstruire son contexte.

### 3.3 Pourquoi ChromaDB ?

- **Légèreté et absence de surcoût d'infrastructure** : ChromaDB fonctionne en mode embarqué (persistance sur disque), sans nécessiter de serveur de base de données séparé à provisionner et maintenir — adapté au périmètre de la FAQ publique, qui reste un volume de données modeste.  
- **Intégration native avec l'écosystème Python/LangChain** : intégration directe comme *vector store* dans les chaînes LangChain, sans couche d'adaptation supplémentaire.  
- **Persistance locale cohérente avec le choix Mistral/Ollama** : la donnée indexée (FAQ publique) reste sur l'infrastructure interne, dans la continuité de la stratégie de confidentialité du §3.1.

### 3.4 Pourquoi MCP \+ n8n ?

- **Standardisation de l'accès aux outils (MCP)** : l'Agent 2 ne connaît qu'un contrat d'outil standardisé (`initiate_transfer`), jamais l'implémentation réelle de l'exécution bancaire. Ce découplage limite la surface d'attaque : compromettre l'agent ne donne pas un accès direct au système bancaire, seulement à un outil dont l'exécution reste sous contrôle du serveur MCP.  
- **Découplage total entre logique d'IA et logique métier/bancaire** : la logique d'exécution réelle (règles de validation supplémentaires, appels au cœur bancaire, notifications) est portée par les workflows n8n, modifiables **sans redéploiement du code de l'agent**. Une évolution réglementaire ou métier se traduit par une modification de workflow, pas par une réécriture de prompt ou de graphe LangGraph.  
- **Auditabilité** : chaque exécution n8n est journalisée nativement (succès, échec, durée, payload), ce qui constitue une piste d'audit indépendante de celle de l'agent.  
- **Sécurité des échanges** : les appels du serveur MCP vers n8n sont signés par HMAC-SHA256 (`X-Webhook-Signature`, voir `02_architecture_multi_agents.md`, §5.2), garantissant que n8n n'exécute jamais un ordre de virement provenant d'une source non authentifiée.

---

## 4\. Arborescence & fichiers de configuration recommandés

### 4.1 Structure type du monorepo

cih-ai-banking/

├── frontend/

│   ├── src/

│   │   ├── components/

│   │   ├── screens/

│   │   └── App.jsx

│   ├── package.json

│   └── tailwind.config.js

│

├── backend/

│   ├── app/

│   │   ├── main.py

│   │   ├── middleware/

│   │   │   └── auth.py

│   │   ├── routers/

│   │   │   ├── auth.py

│   │   │   ├── chat.py

│   │   │   └── transfers.py          \# endpoint sécurisé /api/transfers/{task\_id}/verify-otp

│   │   ├── security/

│   │   │   └── jwt\_handler.py

│   │   └── services/

│   │       └── otp\_service.py        \# MockOtpService déterministe pour le MVP

│   ├── requirements.txt

│   └── .env

│

├── agents/

│   ├── agent1\_faq/                \# module Python importé par backend/app/main.py — PAS de serveur Uvicorn séparé

│   │   ├── graph.py

│   │   ├── tools/

│   │   └── CLAUDE.md

│   └── agent2\_transaction/        \# service séparé, exposé uniquement via A2A (port 8002)

│       ├── graph.py

│       ├── validators/

│       ├── checkpoint.sqlite      \# état des tâches interrompues (checkpointer LangGraph, gitignored)

│       └── CLAUDE.md

│

├── mcp-server/

│   ├── server.py

│   └── tools/

│       └── initiate\_transfer.py

│

├── n8n-workflows/

│   └── execute-transfer.json      \# export du workflow n8n

│

├── mock-banking-api/              \# service FastAPI séparé simulant le système bancaire (port 8010)

│   ├── app/

│   │   ├── main.py

│   │   └── routers/

│   │       ├── accounts.py

│   │       ├── beneficiaries.py

│   │       └── transfers.py

│   └── requirements.txt

│

├── scripts/

│   └── ingest\_faq.py              \# pipeline d'ingestion FAQ → ChromaDB (voir §6)

│

├── data/

│   └── faq\_docs/                  \# documents sources de la FAQ publique

│

├── chroma\_db/                     \# persistance vectorielle locale (gitignored)

│

└── DocsContext/

    ├── 01\_projet\_overview.md

    ├── 02\_architecture\_multi\_agents.md

    ├── 03\_stack\_technique.md

    ├── 04\_scenarios\_et\_securite.md

    └── 05\_interface\_frontend.md

### 4.2 `requirements.txt` (backend \+ agents)

\# \--- Serveur API \---

fastapi\>=0.115

uvicorn\[standard\]\>=0.30

python-multipart\>=0.0.9

pydantic\>=2.7

\# \--- Authentification \---

python-jose\[cryptography\]\>=3.3

passlib\[bcrypt\]\>=1.7

\# \--- Orchestration IA \---

langchain\>=0.3

langgraph\>=0.2

langgraph-checkpoint-sqlite\>=1.0

langchain-ollama\>=0.2

langchain-chroma\>=0.1

\# \--- Base vectorielle \---

chromadb\>=0.5

\# \--- Protocoles inter-agents et outils \---

a2a-sdk\>=1.1

mcp\>=1.0

\# \--- Communication HTTP (également réutilisé pour les tests d'API, voir §6) \---

httpx\>=0.27

\# \--- Utilitaires \---

python-dotenv\>=1.0

\# \--- Tests \---

pytest\>=8.0

pytest-asyncio\>=0.24

### 4.3 Dépendances frontend (extrait `package.json`)

{

  "dependencies": {

    "react": "^18.3.0",

    "react-dom": "^18.3.0",

    "lucide-react": "^0.400.0",

    "axios": "^1.7.0"

  },

  "devDependencies": {

    "tailwindcss": "^3.4.0",

    "autoprefixer": "^10.4.0",

    "postcss": "^8.4.0",

    "vite": "^5.4.0",

    "vitest": "^2.0.0",

    "@testing-library/react": "^16.0.0"

  }

}

### 4.4 `.env.example`

\# \--- Backend / Authentification \---

JWT\_SECRET\_KEY=change-me-in-production

JWT\_ALGORITHM=HS256

JWT\_EXPIRATION\_MINUTES=30

\# \--- Modèle de langage local (Ollama) \---

OLLAMA\_BASE\_URL=http://localhost:11434

OLLAMA\_MODEL=mistral

\# \--- Base vectorielle ChromaDB \---

CHROMA\_PERSIST\_DIR=./chroma\_db

CHROMA\_COLLECTION\_FAQ=faq\_generale

\# \--- Agent 2 / Protocole A2A \---

AGENT2\_A2A\_URL=http://localhost:8002/a2a/agent2

A2A\_DELEGATION\_TOKEN\_SECRET=change-me-in-production   \# signe le jeton de délégation (sub, task\_id, scope, iss, aud, iat, exp, jti)

A2A\_DELEGATION\_TOKEN\_TTL\_SECONDS=120

A2A\_TASK\_TTL\_MINUTES=10                                \# une tâche input-required sans réponse devient "expired" au-delà de ce délai

A2A\_CHECKPOINTER\_SQLITE\_PATH=./agents/agent2\_transaction/checkpoint.sqlite

\# \--- Serveur MCP \---

MCP\_SERVER\_URL=http://localhost:9000

\# \--- Webhook n8n \---

N8N\_TRANSFER\_WEBHOOK\_URL=https://n8n.internal.cih-ai.local/webhook/execute-transfer

N8N\_WEBHOOK\_HMAC\_SECRET=change-me-in-production

\# \--- Système bancaire simulé (mock-banking-api, port 8010) \---

BANKING\_API\_BASE\_URL=http://localhost:8010

\# \--- Règles métier du virement (valeurs fictives de démonstration) \---

DAILY\_TRANSFER\_LIMIT=20000.00

MONTHLY\_TRANSFER\_LIMIT=50000.00

TRANSFER\_CURRENCY=MAD

\# \--- Service OTP déterministe du MVP (appelé exclusivement par FastAPI) \---

DEMO\_OTP\_CODE=123456

OTP\_EXPIRATION\_SECONDS=180

OTP\_MAX\_ATTEMPTS=3

> **Chemin sécurisé de l'OTP** : `DEMO_OTP_CODE` est utilisé uniquement par le `MockOtpService` appelé depuis l'endpoint FastAPI dédié. Le code saisi par l'utilisateur n'est jamais transmis à l'Agent 1, au LLM, au protocole A2A, à l'Agent 2 ou au checkpointer LangGraph. Seul le résultat booléen `otp_verified` peut être communiqué à l'Agent 2.

> **Règle de sécurité non négociable** : `.env` ne doit jamais être committé. Seul `.env.example` (sans valeurs réelles) est versionné. Toute valeur marquée `change-me-in-production` doit être régénérée avant tout déploiement au-delà du poste de développement.

> **Valeurs fictives de démonstration.** `DAILY_TRANSFER_LIMIT`, `MONTHLY_TRANSFER_LIMIT` et `DEMO_OTP_CODE` sont des valeurs de prototype académique, sans aucune valeur réglementaire ou contractuelle. `DEMO_OTP_CODE` en particulier ne doit exister que dans `.env.example` et la documentation de démonstration — en production, `MockOtpService` doit être remplacé par un véritable fournisseur OTP (§6 de `04_scenarios_et_securite.md`).

> **Règle `Decimal`** : tout montant manipulé côté Python (`validate_amount`, `validate_balance`, `validate_limits`, l'outil MCP `initiate_transfer`) utilise le type `Decimal` (module `decimal`), **jamais** `float`. Sur le réseau (JSON), un montant est toujours une **chaîne décimale** (`"2000.00"`), jamais un nombre. Voir `02_architecture_multi_agents.md` (§4.1) pour la justification complète.

### 4.5 Service bancaire simulé (`mock-banking-api`)

Le système bancaire réel n'est jamais intégré dans ce prototype académique : toutes les données (clients, comptes, soldes, transactions, bénéficiaires, plafonds, virements) sont **fictives**, servies par un service FastAPI séparé, `mock-banking-api/`, écoutant sur `http://localhost:8010` (`BANKING_API_BASE_URL`).

> **Frontière de sécurité** : les endpoints de `mock-banking-api` sont préfixés `/internal/` et ne sont **jamais** accessibles directement depuis le frontend React. Seuls le Backend (Agent 1, lecture seule) et la chaîne Agent 2 → MCP → n8n (écriture) y accèdent.

Endpoints internes minimaux :

| Endpoint | Méthode | Rôle |
| :---- | :---- | :---- |
| `/internal/accounts/{customer_id}` | GET | Détails du ou des comptes du client |
| `/internal/accounts/{customer_id}/balance` | GET | Solde courant (lecture seule, utilisé par l'Agent 1) |
| `/internal/customers/{customer_id}/beneficiaries/{beneficiary_id}` | GET | Détails d'un bénéficiaire (utilisé par `validate_beneficiary`) |
| `/internal/customers/{customer_id}/transactions` | GET | Historique des transactions (lecture seule, utilisé par l'Agent 1) |
| `/internal/customers/{customer_id}/limits` | GET | Plafonds journaliers/mensuels applicables (utilisé par `validate_limits`) |
| `/internal/transfers` | POST | Exécute un virement simulé ; **idempotent** via `idempotency_key` (voir `04_scenarios_et_securite.md`, §3.1) |
| `/internal/transfers/{idempotency_key}` | GET | Consulte le résultat d'un virement déjà exécuté (utilisé avant tout retry, jamais de retry aveugle sur le POST) |

**Modèle fictif de bénéficiaire** (`beneficiaries`) :

| Champ | Type | Description |
| :---- | :---- | :---- |
| `beneficiary_id` | string | Identifiant unique du bénéficiaire |
| `owner_customer_id` | string | Client propriétaire de ce bénéficiaire (jamais partagé entre clients) |
| `display_name` | string | Nom affiché (ex. "Mère — CIH ••••1042") |
| `masked_account_number` | string | Numéro de compte masqué |
| `status` | `"active" \| "inactive"` | Statut du bénéficiaire |
| `eligible_for_transfer` | boolean | Éligibilité au virement (ex. faux pendant une période de mise en quarantaine après ajout) |
| `created_at` | string (ISO 8601\) | Date de création |

Le nœud `validate_beneficiary` (contrôle fonctionnel n°2, voir `02_architecture_multi_agents.md` §3.2) vérifie dans l'ordre : (1) l'existence du bénéficiaire, (2) que `owner_customer_id` correspond bien au client authentifié, (3) que `status == "active"`, (4) que `eligible_for_transfer == true`.

---

## 5\. Prérequis & guide d'installation rapide

### 5.1 Prérequis système

- Python 3.11+  
- Node.js 20+  
- Git  
- Docker (pour n8n)  
- 8 Go de RAM minimum recommandés pour l'exécution locale de Mistral via Ollama

### 5.2 Installation pas à pas

**1\. Installer et démarrer Ollama, puis récupérer le modèle Mistral**

\# Installation d'Ollama : voir https://ollama.com

ollama pull mistral

ollama run mistral   \# vérifie que le modèle répond correctement, puis quitter avec /bye

**2\. Cloner le dépôt et créer l'environnement Python**

git clone \<url-du-repo\> cih-ai-banking

cd cih-ai-banking/backend

python3 \-m venv .venv

source .venv/bin/activate      \# Windows : .venv\\Scripts\\activate

pip install \-r requirements.txt

**3\. Configurer les variables d'environnement**

cp .env.example .env

\# Renseigner les valeurs réelles (secrets JWT, URL n8n, etc.)

**4\. Démarrer le service bancaire simulé (mock-banking-api)**

cd ../mock-banking-api

pip install \-r requirements.txt

uvicorn app.main:app \--port 8010 \--reload

**5\. Ingérer les documents FAQ dans ChromaDB**

cd ../backend

python ../scripts/ingest\_faq.py

Ce script lit `data/faq_docs/`, nettoie et découpe les documents, calcule les embeddings localement, puis les insère dans la collection `faq_generale` (voir §6). Il peut être relancé à tout moment pour réingérer le contenu.

**6\. Démarrer n8n (self-hosted, via Docker)**

docker run \-it \--rm \-p 5678:5678 \-v \~/.n8n:/home/node/.n8n n8nio/n8n

Importer le workflow `n8n-workflows/execute-transfer.json` depuis l'interface n8n, puis copier l'URL du webhook généré dans `N8N_TRANSFER_WEBHOOK_URL`.

**7\. Démarrer le serveur MCP**

cd ../mcp-server

python server.py

**8\. Démarrer l'Agent 2 (service séparé, exposé via A2A)**

cd ../agents/agent2\_transaction && uvicorn graph:app \--port 8002 \--reload

> **L'Agent 1 n'est pas démarré séparément.** Pour ce MVP, l'Agent 1 est un module Python importé directement par le Backend FastAPI (`backend/app/main.py`) — il n'existe **aucune commande de démarrage sur le port 8001**. Seul l'Agent 2 tourne comme service indépendant, car il doit être joignable en HTTP par le protocole A2A.

**9\. Démarrer le Backend FastAPI (inclut l'Agent 1)**

cd ../../backend

uvicorn app.main:app \--port 8000 \--reload

**10\. Démarrer le Frontend React**

cd ../frontend

npm install

npm run dev

**11\. Vérification de bout en bout**

Ouvrir l'application frontend, s'authentifier via `POST /api/auth/login` (voir `05_interface_frontend.md` pour le contrat), puis tester successivement :

- une question de FAQ publique (sans connexion) ;  
- une demande de solde après connexion ;  
- une demande de virement complète, jusqu'à la validation sécurisée de l'OTP via l'endpoint FastAPI dédié et le `MockOtpService` (code de démonstration `DEMO_OTP_CODE`).

Chaque étape doit être visible dans les journaux respectifs du Backend (Agent 1 inclus), de l'Agent 2, du serveur MCP et de n8n — c'est le signe que la chaîne de bout en bout décrite dans `02_architecture_multi_agents.md` (§5) fonctionne dans son intégralité.

---

## 6\. Pipeline d'ingestion FAQ (`scripts/ingest_faq.py`)

Ce script alimente la collection ChromaDB `faq_generale` consommée par le RAG de l'Agent 1. Il doit pouvoir être **relancé à tout moment** (réingestion complète) sans dupliquer les entrées.

Étapes du pipeline :

1. **Lecture** de l'ensemble des documents sources dans `data/faq_docs/`.  
2. **Nettoyage** : suppression du bruit de mise en forme (en-têtes, pieds de page répétés, caractères de contrôle).  
3. **Découpage** (*chunking*) en segments de taille raisonnable pour l'embedding et la recherche sémantique.  
4. **Calcul des embeddings**, localement (cohérent avec la stratégie Mistral/Ollama de confidentialité, §3.1) — jamais via une API d'embedding tierce.  
5. **Insertion** dans la collection `faq_generale` de ChromaDB, avec **conservation des métadonnées de source** (nom de fichier, section, date d'ingestion) pour permettre la traçabilité d'une réponse RAG jusqu'à son document d'origine.  
6. **Réingestion** : une exécution ultérieure du script doit pouvoir remplacer proprement le contenu existant (par exemple en vidant puis reconstruisant la collection, ou par upsert sur un identifiant stable de chunk), sans laisser de doublons.

> **Rappel de périmètre** : `faq_generale` ne contient et ne contiendra jamais que du contenu **public** (frais, procédures, conditions). Aucune donnée personnelle ou transactionnelle n'est jamais indexée par ce pipeline — voir `02_architecture_multi_agents.md` (§2.2).
