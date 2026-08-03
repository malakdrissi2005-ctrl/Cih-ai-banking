# CLAUDE.md — Guide de référence : CIH AI Banking

> Ce fichier est le point d'entrée pour toute contribution au code de ce projet avec Claude Code.
> Il synthétise la documentation de référence complète, présente dans `DocsContext/` :
> - `01_projet_overview.md` — vue d'ensemble, valeur ajoutée, cycle de vie d'un virement
> - `02_architecture_multi_agents.md` — spécification des graphes LangGraph, protocole A2A, jeton de délégation, persistance
> - `03_stack_technique.md` — stack, justifications techniques, arborescence, mock-banking-api, installation
> - `04_scenarios_et_securite.md` — scénarios E2E, mesures de sécurité transverses, OTP simulé, idempotence, audit
> - `05_interface_frontend.md` — application unique CIH AI Banking à deux rendus simultanés (mobile interactif + adaptation desktop), état partagé unique, règles responsive exactes, identité visuelle avant/après authentification
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
- Le frontend ne communique **jamais** directement avec l'Agent 1, l'Agent 2, ou tout composant interne — uniquement avec FastAPI (`POST /api/chat`, endpoint d'authentification).
- Le flux complet d'un virement suit la chaîne `React → FastAPI → Agent 1 → A2A → Agent 2 → MCP → n8n → mock-banking-api` ; chaque frontière constitue un point de contrôle et d'audit indépendant, aucun composant ne communiquant directement avec un composant situé à plus d'un saut de lui.
- L'Agent 1 ne reçoit **jamais** le code OTP brut : sa saisie et sa vérification empruntent un chemin séparé entre le frontend, FastAPI et le `MockOtpService` (§8) — jamais via une tâche A2A ni le LLM.

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

Ce jeton de délégation est **distinct** de la session utilisateur : FastAPI gère une session utilisateur identifiée par un `session_id` opaque, validé par FastAPI à chaque requête protégée — y compris avant tout traitement lié à l'OTP (§8). Ce `session_id` est distinct du jeton de délégation A2A, qui est un jeton **signé, à courte durée de vie**, émis uniquement au moment d'une délégation vers l'Agent 2.

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

États de tâche : `submitted` → `working` → `input-required:confirmation` → `working` → `input-required:otp` → `working` → `completed` / `failed` / `cancelled` / `expired`.

Les deux interruptions ne suivent pas le même chemin de reprise :
- **Confirmation** : chemin conversationnel habituel, `React → FastAPI → Agent 1 → A2A → Agent 2`.
- **OTP** : chemin direct et séparé, `React → FastAPI → MockOtpService` (endpoint `POST /api/transfers/{task_id}/verify-otp`) ; FastAPI transmet ensuite uniquement `{"task_id": "...", "otp_verified": true}` à l'Agent 2, qui reprend son graphe au nœud `validate_otp`. Si `otp_verified=true`, l'exécution se poursuit : `Agent 2 → MCP → n8n → mock-banking-api → completed`.

- `A2A_TASK_TTL_MINUTES=10` : une tâche en `input-required:*` sans réponse pendant 10 minutes devient `expired`.
- L'OTP garde sa **propre** expiration de 3 minutes, indépendante du TTL de la tâche.
- Le checkpointer peut conserver `otp_verified` (booléen) dans l'état persisté du graphe — **jamais** le code OTP brut, qui n'est à aucun moment transmis à l'Agent 2 ni donc persisté.

Détails : `DocsContext/02_architecture_multi_agents.md` (§4.4, §4.5).

## 7. Service bancaire simulé (`mock-banking-api`) & bénéficiaires

Service FastAPI séparé (`mock-banking-api/`, port 8010), données 100% fictives, jamais accessible directement depuis le frontend.

Endpoints internes : `GET /internal/accounts/{customer_id}`, `GET /internal/accounts/{customer_id}/balance`, `GET /internal/customers/{customer_id}/beneficiaries/{beneficiary_id}`, `GET /internal/customers/{customer_id}/transactions`, `GET /internal/customers/{customer_id}/limits`, `POST /internal/transfers` (idempotent), `GET /internal/transfers/{idempotency_key}`.

**Modèle de bénéficiaire** : `beneficiary_id`, `owner_customer_id`, `display_name`, `masked_account_number`, `status`, `eligible_for_transfer`, `created_at`. Le contrôle n°2 (`validate_beneficiary`) vérifie : existence, appartenance au client authentifié, statut actif, éligibilité au virement.

Détails : `DocsContext/03_stack_technique.md` (§4.5).

## 8. OTP simulé (`MockOtpService`) — flux sécurisé

Aucun fournisseur SMS/e-mail réel pour ce MVP. Code de démonstration fixe et configurable (`DEMO_OTP_CODE=123456`), validité 180 secondes, 3 tentatives max.

**Chemin du code OTP brut** : `React → FastAPI → MockOtpService`, via l'endpoint dédié `POST /api/transfers/{task_id}/verify-otp`. FastAPI vérifie la session, l'appartenance du `task_id`, l'état de la tâche, la fenêtre de validité et le nombre de tentatives, puis transmet le code **uniquement** au `MockOtpService`, qui effectue la comparaison déterministe (`code_saisi == DEMO_OTP_CODE`).

**Résultat transmis à l'Agent 2** : uniquement `{"task_id": "a2a-7f3e2b1c", "otp_verified": true}`. Le nœud `validate_otp` (contrôle n°7) ne vérifie que ce résultat structuré et n'accède jamais au code brut, qui **ne passe jamais** par l'Agent 1, le LLM, LangChain, une tâche A2A, l'Agent 2, LangGraph, le checkpointer SQLite, MCP, n8n ou le mock-banking-api.

**Échecs** : `failed: invalid_otp` après 3 tentatives ; `failed: otp_expired` après expiration — dans les deux cas, le code brut n'est jamais journalisé.

**Journalisation** : composant `otp_service`, événement `otp_validation_attempt`, champ `otp_verified` (jamais de champ `otp_provided`).

Le frontend n'affiche qu'un numéro masqué fictif.

> **En production**, `MockOtpService` doit être remplacé par un véritable fournisseur OTP générant un code aléatoire à usage unique — jamais un code fixe partagé.

Détails : `DocsContext/04_scenarios_et_securite.md` (§4.4).

## 9. Frontend — une seule application, deux rendus simultanés synchronisés

> Cette section reflète intégralement `DocsContext/05_interface_frontend.md` (dernière révision). Elle **remplace** toute règle frontend antérieure. En cas d'écart entre cette synthèse et le document source, **le document source fait foi**.

### 9.1 Principe fondamental

CIH AI Banking est **avant tout une application mobile**. Sur ordinateur, la démonstration affiche **simultanément** :

1. à **gauche** : le véritable rendu mobile, **pleinement interactif**, dans un cadre de téléphone réaliste — ce n'est pas une image décorative ;
2. à **droite** : une **adaptation desktop agrandie de cette même application**, pour une démonstration plus lisible.

Il ne s'agit jamais de deux applications différentes : **le téléphone et la vue desktop utilisent en permanence le même état synchronisé** — même session, même utilisateur, même écran actif, mêmes données, même conversation, même agent actif, même opération en cours. Une action posée sur un panneau apparaît **immédiatement** sur l'autre ; aucune divergence n'est tolérée, à aucun instant.

### 9.2 Règles responsive exactes (reprises telles quelles de `05_interface_frontend.md` §4)

- **Largeur ≥ 900 px** : téléphone interactif à gauche **+** vue desktop agrandie à droite, affichés **simultanément**.
- **Largeur entre 640 px et 899 px** : vue desktop uniquement ; le téléphone décoratif est masqué.
- **Largeur < 640 px** : application mobile uniquement, en plein écran, sans cadre de téléphone.
- L'ensemble « téléphone + panneau desktop » forme une composition **centrée et compacte**, avec une largeur maximale raisonnable pour le bloc entier — le panneau desktop n'est jamais étiré jusqu'aux bords de la fenêtre. **Aucun défilement horizontal** ne doit apparaître, quelle que soit la largeur testée.
- Le cadre du téléphone reste visible en permanence tant que la règle ≥ 900 px s'applique, **y compris lorsque la fenêtre de chat est ouverte**.
- Ce seuil est appliqué en **CSS pur** (classes `.showcase-layout` / `.showcase-phone` / `.showcase-desktop`, voir `src/index.css`), **jamais** via une classe Tailwind `xl:` (1280 px par défaut) — un seuil CSS explicite reste fiable même lorsque la mise à l'échelle du système d'exploitation réduit la largeur CSS effective rapportée par le navigateur.

### 9.3 Un seul `ChatWidget`, deux boutons d'accès

Il existe **un seul `ChatWidget`**, monté une seule fois dans `App`. Il n'existe ni deux instances de chat, ni deux fenêtres indépendantes.

- **Deux boutons visuels Assistant IA** existent : un dans le téléphone, un dans le panneau desktop.
- Les deux boutons contrôlent **le même** `ChatWidget`, **la même** fenêtre, **la même** conversation, **le même** état d'ouverture. Cliquer sur l'un ou l'autre ouvre/ferme la fenêtre unique, visible identiquement dans les deux panneaux.
- Le chat est **fermé par défaut**.
- Avant authentification, la conversation est figée sur l'Agent FAQ (Agent 1). Une question personnelle/sensible sans connexion déclenche une invitation à se connecter, avec mise en évidence **simultanée** des deux écrans de connexion (mobile et desktop), puisqu'il s'agit du même écran actif partagé.
- Après authentification, la bascule vers l'Agent Transactionnel (Agent 2) puis le retour à l'Agent FAQ en fin d'opération sont visibles **simultanément et à l'identique** par les deux boutons d'accès.

### 9.4 Virement et OTP — états synchronisés

Le déroulé d'un virement (demande → `TransferConfirmationCard` → confirmation/annulation → passage en « Mode opération sécurisée » → `OtpModal` → code `123456` en démonstration → succès, ou échec après 3 tentatives → `TransferResult`) suit une séquence d'états **strictement synchronisée** entre le téléphone et le panneau desktop — seule la présentation visuelle s'adapte au format, jamais le contenu ni l'état. Cette séquence applicative reste cohérente avec les 7 contrôles fonctionnels de l'Agent 2 (§3).

### 9.5 Identité académique obligatoire

| Élément | Valeur |
|---|---|
| Nom du projet affiché | `CIH AI Banking — Démonstration` |
| Mention permanente, sur les deux panneaux | `Démonstration académique — aucune opération réelle` |

Interdictions strictes, sans exception : aucun logo officiel CIH, aucun logo VISA ni d'un autre réseau de paiement, aucune donnée bancaire réelle, aucun numéro ou nom provenant de captures de référence. Toutes les données affichées (nom, compte, solde, transactions) sont fictives et distinctes des exemples des captures de référence.

### 9.6 Identité visuelle — avant authentification

Fond en dégradé (orange → rouge-orangé → bleu profond → violet sombre), en-tête compact, titre « Bienvenue », panneau d'authentification sombre semi-transparent (`auth-panel`), champs identifiant/mot de passe, lien « Oublié ? », bascule « Se souvenir de moi », bouton pleine largeur `cih-orange` (`#F26522`), section « Nos services » en grille.

### 9.7 Identité visuelle — après authentification

Fond principal **blanc** (`surface-bg`) ; **règle impérative : aucun grand fond sombre et aucun dégradé de grande surface ne réapparaissent après authentification** — écran clair, sobre, de style bancaire, dans les deux panneaux. Séparateur fin et salutation en `cih-orange`, texte principal gris foncé, information secondaire (numéro de compte masqué, liens) en `cih-blue` (`#005CA9`), icônes de services `cih-orange`, séparateurs secondaires orange clair, cartes blanches à bordure très légère (`card-surface`).

### 9.8 Composants clés (détail complet et props exactes : `05_interface_frontend.md` §17-18)

`App` (racine, monte `BankingAppProvider` + `ResponsiveShowcase` + l'unique `ChatWidget`) · `BankingAppProvider` (état partagé unique) · `ResponsiveShowcase` (applique les règles §9.2) · `PhonePreview` (téléphone interactif, ≥900 px) · `MobileAppView` (mobile réel, <640 px, sans cadre) · `MobileLoginView` / `DesktopLoginView` (écran de connexion, mêmes champs, adaptés en largeur) · `MobileDashboard` / `DesktopDashboard` (même dashboard, le desktop ajoutant `SpendingChart`, `BankCard` et `SecurityBanner` comme visualisations complémentaires des mêmes données) · `Sidebar`, `DesktopHeader`, `BottomNav` (navigation) · `AccountCard`, `RecentTransactions`, `QuickActions` (partagés mobile/desktop, mêmes données) · `ChatWidget`, `ChatFab` (deux instances, un seul widget contrôlé), `ChatWindow`, `ChatMessage`, `QuickSuggestions`, `TransferConfirmationCard`, `OtpModal`, `TransferResult`.

### 9.9 Stack et tokens de style

React 18 + Vite + JavaScript (JSX) + TailwindCSS 3 + `lucide-react` exclusivement pour les icônes. Cartes/blocs toujours `rounded-2xl` (jamais d'angle vif sur un conteneur de premier niveau), `shadow-md` par défaut, `shadow-xl` réservé au chat déplié et aux modales, espacement en multiples de 4 (Tailwind), jamais de valeurs arbitraires.

### 9.10 Règle d'évolution du document

Tout nouvel écran, composant de chat riche ou nouvelle donnée affichée doit d'abord être décrit dans `05_interface_frontend.md` — avec son contenu exact et sa règle de synchronisation totale — **avant** d'être implémenté.

## 10. Stack technique

| Couche | Techno | Version min. |
|---|---|---|
| Frontend | React 18 + Vite + TailwindCSS 3 + lucide-react | 18.x / 3.x |
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

## 11. Arborescence de référence du monorepo

```
cih-ai-banking/
├── frontend/            # React + Vite + Tailwind — structure interne detaillee en 05_interface_frontend.md §18
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

## 12. Plan MVP par phases

- **Phase 0** — Documentation cohérente et arborescence (ce fichier + `DocsContext/`, scaffolding des dossiers).
- **Phase 1** — Frontend visuel avec données simulées : application unique à deux rendus synchronisés (téléphone interactif + adaptation desktop, voir §9), sans backend réel.
- **Phase 2** — Backend FastAPI, authentification et `mock-banking-api`.
- **Phase 3** — Agent 1 : outils de lecture seule et RAG (ingestion FAQ, ChromaDB).
- **Phase 4** — Agent 2 isolé avec les 7 contrôles fonctionnels (données mockées, testé en autonomie).
- **Phase 5** — Communication A2A (jeton de délégation, Agent Card) et reprise SQLite (checkpointer, TTL).
- **Phase 6** — MCP et n8n (outil `initiate_transfer`, webhook HMAC, idempotence de bout en bout).
- **Phase 7** — Tests E2E et durcissement de sécurité (scénarios adversariaux de `04_scenarios_et_securite.md`, pytest, vitest).

## 13. Règles de contribution à respecter

1. Toute nouvelle dépendance structurante doit d'abord être ajoutée à `DocsContext/03_stack_technique.md`.
2. Toute nouvelle fonctionnalité touchant l'authentification, les virements, ou exposant un nouvel outil à un agent doit être accompagnée d'un scénario dans `DocsContext/04_scenarios_et_securite.md` **avant** merge.
3. Tout nouvel écran, composant de chat riche ou nouvelle donnée affichée doit d'abord être décrit dans `DocsContext/05_interface_frontend.md` **avant** d'être implémenté (§9.10).
4. Toute déviation par rapport aux règles d'aiguillage ou à la séquence des 7 contrôles doit être documentée comme exception explicite et justifiée, jamais implicite.
5. Ne jamais introduire de chemin de code permettant à l'Agent 1 d'appeler directement un outil bancaire sensible, ni à l'Agent 2 de sauter un contrôle (l'OTP y compris, quel que soit le montant).
6. Ne jamais journaliser un secret en clair (OTP, jeton de délégation complet, mot de passe, secret HMAC).
7. Ne jamais utiliser `float` pour un montant — toujours `Decimal` côté Python, toujours une chaîne décimale en JSON.
8. Ne jamais faire de retry aveugle sur `POST /internal/transfers` — toujours vérifier `GET /internal/transfers/{idempotency_key}` d'abord.
9. Ne jamais numéroter une mesure transverse (anti-injection, HMAC, anti-rejeu, idempotence, journalisation) comme un contrôle fonctionnel — la liste des 7 contrôles (§3) est la seule référence.
10. Ne jamais laisser diverger l'état entre le panneau mobile et le panneau desktop — une seule source d'état partagée (§9.1) ; ne jamais créer une deuxième instance de `ChatWidget`.
