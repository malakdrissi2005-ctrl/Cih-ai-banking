# CLAUDE.md — Guide de référence : CIH AI Banking

> Ce fichier est le point d'entrée pour toute contribution au code de ce projet avec Claude Code.
> Il synthétise la documentation de référence complète, présente dans `DocsContext/` :
> - `01_projet_overview.md` — vue d'ensemble, valeur ajoutée, cycle de vie d'un virement
> - `02_architecture_multi_agents.md` — spécification des graphes LangGraph, protocole A2A, jeton de délégation, persistance
> - `03_stack_technique.md` — stack, justifications techniques, arborescence, mock-banking-api, installation
> - `04_scenarios_et_securite.md` — scénarios E2E, mesures de sécurité transverses, OTP simulé, idempotence, audit
> - `05_interface_frontend.md` — design system, écrans, composants React/Tailwind, contrat d'authentification
>
> **En cas de doute ou d'ambiguïté sur une décision d'implémentation, consulter le document source correspondant avant d'improviser.** Toute déviation par rapport aux règles ci-dessous doit être documentée et justifiée, jamais silencieuse.

---

## 1. Le projet en une phrase

**CIH AI Banking** est un assistant bancaire conversationnel reposant sur **deux agents autonomes séparés** communiquant via le protocole **Agent-to-Agent (A2A)** : un agent d'accueil/FAQ exposé au client, et un agent transactionnel invisible, seul habilité à exécuter des opérations bancaires sensibles. La séparation est **physique et structurelle**, pas un garde-fou ajouté à un chatbot monolithique. Ce projet est un **prototype académique** : toutes les données bancaires, tous les clients et toutes les valeurs de sécurité (OTP, plafonds) sont fictifs.

## 2. Les deux agents

| | Agent 1 — FAQ & Orientation | Agent 2 — Transactionnel haute sécurité |
|---|---|---|
| Déploiement | **Module Python intégré au Backend FastAPI** — pas de service séparé, pas de port dédié | **Service séparé**, interne, exposé **uniquement** via A2A (port 8002) |
| Exposition | Directe (seul point de contact du client, via `POST /api/chat`) | Jamais directe — uniquement via délégation A2A |
| Rôle | RAG (ChromaDB) sur FAQ publique, lecture seule de données perso, classification d'intention, délégation | Exécution exclusive des virements, après 7 contrôles fonctionnels |
| Mémoire | ChromaDB (contenu **public uniquement**, jamais de données perso/transactionnelles) | Aucune donnée personnelle persistée localement ; état de tâche persisté via checkpointer SQLite (§6) |
| Capacité d'exécution | Aucune sur le système bancaire | Exclusive |

**Règles structurelles non négociables :**
- Un utilisateur non authentifié ne peut **jamais** déclencher une action sensible — refus appliqué dans le graphe LangGraph (`route_decision`), jamais laissé à l'appréciation du prompt.
- L'Agent 2 ne fait **jamais confiance par défaut** à ce que lui transmet l'Agent 1 : il revalide indépendamment, **localement et cryptographiquement**, le jeton de délégation A2A (contrôle n°1) — jamais un appel à un service d'authentification externe supplémentaire pour ce MVP.
- Lors du handover A2A, seuls trois éléments franchissent la frontière : le jeton de délégation, les paramètres de la transaction extraits par l'Agent 1, le message utilisateur déclencheur. L'historique conversationnel complet et le contexte RAG **ne sont jamais transmis** à l'Agent 2.
- Aucun chemin du graphe de l'Agent 2 ne permet d'atteindre le nœud d'exécution (`initiate_transfer`) sans avoir traversé les 7 contrôles dans l'ordre. Pas d'edge direct de contournement.
- Le frontend ne communique **jamais** directement avec l'Agent 1, l'Agent 2, ou tout composant interne — uniquement avec FastAPI (`POST /api/chat`, `POST /api/auth/login`).

Détails complets : `DocsContext/01_projet_overview.md` (§3), `DocsContext/02_architecture_multi_agents.md`.

## 3. Séquence des 7 contrôles fonctionnels — référence unique

> **Cette table est la seule et unique source de vérité pour "Contrôle n°X" dans toute la documentation.** Aucune autre liste ne doit être numérotée en parallèle. Les mesures transverses (assainissement anti-injection, signature HMAC, anti-rejeu, idempotence, journalisation — §5) ne sont **jamais** numérotées comme des contrôles fonctionnels.

| # | Contrôle | Nœud LangGraph | Échec → |
|---|---|---|---|
| 1 | Revalidation cryptographique du jeton de délégation A2A | `revalidate_auth` | `failed: unauthenticated` |
| 2 | Existence/éligibilité du bénéficiaire (§7) | `validate_beneficiary` | `failed: invalid_beneficiary` |
| 3 | Validité du montant (`Decimal`, positif) | `validate_amount` | `failed: invalid_amount` |
| 4 | Couverture du solde | `validate_balance` | `failed: insufficient_funds` |
| 5 | Respect des plafonds (`DAILY_TRANSFER_LIMIT`, `MONTHLY_TRANSFER_LIMIT`) | `validate_limits` | `failed: limit_exceeded` |
| 6 | Confirmation explicite utilisateur | `request_confirmation` | `failed: user_cancelled` / `input-required: confirmation` |
| 7 | Validation OTP — **obligatoire pour tout virement, sans seuil ni exception** | `validate_otp` | `failed: invalid_otp` (3 tentatives) / `failed: otp_expired` (3 min) |

Chaque contrôle doit réussir avant que le suivant soit évalué. Un échec interrompt immédiatement le graphe avec un motif précis. **L'OTP (contrôle n°7) n'est jamais sauté**, quel que soit le montant du virement — il n'existe aucune notion de seuil conditionnel dans ce projet. Voir `DocsContext/02_architecture_multi_agents.md` (§3.2) et `DocsContext/04_scenarios_et_securite.md` (§3, mesures transverses).

## 4. Jeton de délégation A2A

Le Backend (service d'authentification) émet un **jeton de délégation signé, à courte durée de vie** — l'Agent 1 ne fabrique jamais lui-même de preuve d'authentification. Réclamations minimales : `sub` (customer_id), `task_id`, `scope=bank_transfer`, `iss` (issuer), `aud=agent2`, `iat`, `exp`, `jti` (unique, anti-rejeu).

L'Agent 2 revalide **localement et cryptographiquement** (contrôle n°1) : signature, issuer, audience, expiration, scope, `task_id`, unicité du `jti`. Un simple `is_authenticated=true` transmis en clair n'est **jamais** une preuve suffisante. Le jeton complet n'est **jamais journalisé**. Détails : `DocsContext/02_architecture_multi_agents.md` (§4.2bis).

## 5. Sécurité — mesures transverses

- **Aucune sécurité ne repose sur la capacité du LLM à "bien se comporter".** Chaque contrôle fonctionnel (§3) est une porte fermée par défaut, ouverte uniquement par une vérification programmatique explicite.
- **Anti-prompt-injection** (mesure transverse, pas de bibliothèque "magique") : séparation stricte instructions système / message utilisateur, limite de taille des messages, validation Pydantic des sorties, classification structurée, allowlist d'outils par agent, autorisations programmatiques indépendantes du LLM, refus systématique de toute instruction de contournement, journalisation des tentatives suspectes, données RAG traitées comme non fiables et non exécutables. **La détection d'injection ne remplace jamais les contrôles fonctionnels.**
- **Anti-rejeu** : `jti` unique par jeton de délégation, jamais réutilisable.
- **Idempotence** : une `idempotency_key` unique est créée par l'Agent 2 avant l'exécution et propagée **sans modification** : Agent 2 → MCP → n8n → mock-banking-api. Une même clé ne peut produire qu'un seul virement. En cas de timeout, on interroge d'abord `GET /internal/transfers/{idempotency_key}` avant tout nouvel essai — **aucun retry aveugle** sur `POST /internal/transfers`.
- **Webhooks n8n** : signés HMAC-SHA256 (`X-Webhook-Signature`) — n8n rejette (HTTP 401) tout appel non authentifié.
- **Journalisation** : append-only, horodatée UTC ISO 8601, indexée par `task_id` A2A. **Jamais de secret en clair** (OTP, jeton de délégation complet, mot de passe, secret HMAC → `"[REDACTED]"` ou statut booléen uniquement), filtrage appliqué **avant** l'écriture du log.
- `.env` n'est jamais commité ; seul `.env.example` est versionné. Toute valeur `change-me-in-production` doit être régénérée avant déploiement.
- **Montants** : toujours `Decimal` en Python, jamais `float` ; toujours une **chaîne décimale** en JSON (`"2000.00"`), jamais un nombre.

Détails complets, scénarios adversariaux : `DocsContext/04_scenarios_et_securite.md`.

## 6. Persistance des tâches (checkpointer SQLite)

Le cycle `input-required` (confirmation puis OTP) implique que le graphe LangGraph de l'Agent 2 soit interrompu et repris entre plusieurs requêtes HTTP. Un **checkpointer SQLite** (`langgraph-checkpoint-sqlite`) persiste l'état par `task_id` (clé de reprise principale).

États de tâche : `submitted` → `working` → `input-required: confirmation` → `working` → `input-required: otp` → `working` → `completed` / `failed` / `cancelled` / `expired`.

- `A2A_TASK_TTL_MINUTES=10` : une tâche en `input-required:*` sans réponse pendant 10 minutes devient `expired`.
- L'OTP garde sa **propre** expiration de 3 minutes, indépendante du TTL de la tâche.

Détails : `DocsContext/02_architecture_multi_agents.md` (§4.4, §4.5).

## 7. Service bancaire simulé (`mock-banking-api`) & bénéficiaires

Service FastAPI séparé (`mock-banking-api/`, port 8010), données 100% fictives, jamais accessible directement depuis le frontend.

Endpoints internes : `GET /internal/accounts/{customer_id}`, `GET /internal/accounts/{customer_id}/balance`, `GET /internal/customers/{customer_id}/beneficiaries/{beneficiary_id}`, `GET /internal/customers/{customer_id}/transactions`, `GET /internal/customers/{customer_id}/limits`, `POST /internal/transfers` (idempotent), `GET /internal/transfers/{idempotency_key}`.

**Modèle de bénéficiaire** : `beneficiary_id`, `owner_customer_id`, `display_name`, `masked_account_number`, `status`, `eligible_for_transfer`, `created_at`. Le contrôle n°2 (`validate_beneficiary`) vérifie : existence, appartenance au client authentifié, statut actif, éligibilité au virement.

Détails : `DocsContext/03_stack_technique.md` (§4.5).

## 8. OTP simulé (`MockOtpService`)

Aucun fournisseur SMS/e-mail réel pour ce MVP. Code de démonstration fixe et configurable (`DEMO_OTP_CODE=123456`), validité 3 minutes, 3 tentatives max. **Jamais journalisé, jamais transmis à n8n, jamais validé par le LLM** (comparaison programmatique stricte dans `validate_otp`). Le frontend n'affiche qu'un `phoneMasked` fictif.

> **En production**, `MockOtpService` doit être remplacé par un véritable fournisseur OTP générant un code aléatoire à usage unique — jamais un code fixe partagé.

Détails : `DocsContext/04_scenarios_et_securite.md` (§4.4).

## 9. Contrat d'authentification (`POST /api/auth/login`)

Requête : `{ "customer_number": "DEMO001", "password": "..." }`. Réponse : `{ "access_token", "token_type": "bearer", "expires_in": 1800, "user": { "customer_id", "display_name" } }`. Le frontend utilise exclusivement `user.display_name`. Toutes les données sont fictives. Détails : `DocsContext/05_interface_frontend.md` (§7).

## 10. Stack technique

| Couche | Techno | Version min. |
|---|---|---|
| Frontend | React 18 + TailwindCSS 3 + lucide-react | 18.x / 3.x |
| Backend API (+ Agent 1 intégré) | FastAPI + Uvicorn (Python 3.11+) | 0.115+ / 0.30+ |
| Orchestration IA | LangChain 0.3+ / LangGraph 0.2+ / `langgraph-checkpoint-sqlite` | — |
| Inter-agents | A2A (`a2a-sdk` 1.1+) | — |
| LLM | Mistral, exécution locale via Ollama 0.3+ | — |
| RAG | ChromaDB 0.5+ (collection `faq_generale`, contenu public uniquement) | — |
| Outils Agent 2 | MCP (`mcp` SDK Python 1.0+) | — |
| Automatisation | n8n self-hosted, déclenché par Webhook HTTP + HMAC-SHA256 | — |
| Banque simulée | `mock-banking-api` (FastAPI séparé, port 8010) | — |
| Auth | JWT via `python-jose` 3.3+ | — |
| Tests | pytest, pytest-asyncio, httpx (API) ; vitest + @testing-library/react (frontend) | — |

**Pourquoi Mistral/Ollama en local** : zéro fuite de données bancaires vers un tiers, conformité réglementaire, indépendance réseau. **Pourquoi LangGraph** : gestion d'états cycliques (7 contrôles), support natif multi-agent, interruptions natives pour `input-required` + reprise via checkpointer SQLite. **Pourquoi MCP+n8n** : découplage entre logique IA et logique métier.

Justifications complètes, `.env.example`, guide d'installation pas-à-pas : `DocsContext/03_stack_technique.md`.

## 11. Frontend — règles de design system

- Couleurs : `cih-orange` (#F26522, accent principal/actions), `cih-blue` (#005CA9, titres/liens), dégradé `cih-bg-dark-from→to` (écran non-authentifié), `cih-surface`/`white` (dashboard authentifié).
- Cartes : toujours `rounded-2xl` (jamais `rounded-md`/`rounded-lg` en conteneur de premier niveau), `shadow-md` par défaut, `shadow-xl` réservé au chat déplié et aux modales.
- Icônes : exclusivement `lucide-react`. Espacements en multiples de 4 (Tailwind), jamais de valeurs arbitraires (`p-[13px]`).
- `ChatWidget` — props officielles : `mode` (`"public" | "authenticated"`), `jwtToken`, `onRequireAuth`. **Pas de prop `agent` figée.** Le backend retourne `active_agent` (`"assistant"` ou `"secure_operation"`) uniquement pour adapter l'affichage (en-tête, styling) — même en `secure_operation`, le frontend ne parle qu'à FastAPI.
- Tout nouveau composant ajouté à `src/components/chat/` doit être documenté dans la table des props avant utilisation dans `ChatMessage`.

Détails : `DocsContext/05_interface_frontend.md`.

## 12. Arborescence de référence du monorepo

```
cih-ai-banking/
├── frontend/            # React + Tailwind
├── backend/              # FastAPI + Agent 1 (module intégré, pas de service séparé)
├── agents/
│   ├── agent1_faq/       # module Python importé par backend/app/main.py
│   └── agent2_transaction/  # service séparé, exposé via A2A (port 8002), checkpoint.sqlite
├── mcp-server/           # server.py, tools/initiate_transfer.py
├── n8n-workflows/        # export JSON des workflows
├── mock-banking-api/     # service FastAPI séparé (port 8010), données 100% fictives
├── scripts/
│   └── ingest_faq.py     # pipeline d'ingestion FAQ → ChromaDB
├── data/faq_docs/        # sources FAQ publique
├── chroma_db/            # persistance vectorielle locale (gitignored)
└── DocsContext/          # documentation de référence (ce dossier)
```

## 13. Nouvel ordre du plan MVP

- **Phase 0** — Documentation cohérente et arborescence (ce fichier + `DocsContext/`, scaffolding des dossiers).
- **Phase 1** — Frontend visuel avec données simulées (écrans authentifié/non-authentifié, ChatWidget, composants riches, sans backend réel).
- **Phase 2** — Backend FastAPI, authentification (`/api/auth/login`) et `mock-banking-api`.
- **Phase 3** — Agent 1 : outils de lecture seule et RAG (ingestion FAQ, ChromaDB).
- **Phase 4** — Agent 2 isolé avec les 7 contrôles fonctionnels (données mockées, testé en autonomie).
- **Phase 5** — Communication A2A (jeton de délégation, Agent Card) et reprise SQLite (checkpointer, TTL).
- **Phase 6** — MCP et n8n (outil `initiate_transfer`, webhook HMAC, idempotence de bout en bout).
- **Phase 7** — Tests E2E et durcissement de sécurité (scénarios adversariaux de `04_scenarios_et_securite.md`, pytest, vitest).

## 14. Règles de contribution à respecter

1. Toute nouvelle dépendance structurante doit d'abord être ajoutée à `DocsContext/03_stack_technique.md`.
2. Toute nouvelle fonctionnalité touchant l'authentification, les virements, ou exposant un nouvel outil à un agent doit être accompagnée d'un scénario dans `DocsContext/04_scenarios_et_securite.md` **avant** merge.
3. Toute déviation par rapport aux règles d'aiguillage ou à la séquence des 7 contrôles doit être documentée comme exception explicite et justifiée, jamais implicite.
4. Ne jamais introduire de chemin de code permettant à l'Agent 1 d'appeler directement un outil bancaire sensible, ni à l'Agent 2 de sauter un contrôle (l'OTP y compris, quel que soit le montant).
5. Ne jamais journaliser un secret en clair (OTP, jeton de délégation complet, mot de passe, secret HMAC).
6. Ne jamais utiliser `float` pour un montant — toujours `Decimal` côté Python, toujours une chaîne décimale en JSON.
7. Ne jamais faire de retry aveugle sur `POST /internal/transfers` — toujours vérifier `GET /internal/transfers/{idempotency_key}` d'abord.
8. Ne jamais numéroter une mesure transverse (anti-injection, HMAC, anti-rejeu, idempotence, journalisation) comme un contrôle fonctionnel — la liste des 7 contrôles (§3) est la seule référence.
