# 01 — Vue d'ensemble du projet : CIH AI Banking

> **Type de document** : Spécification fonctionnelle et technique de référence **Statut** : Document fondateur — à consulter avant toute contribution au code **Portée** : Ce document encadre l'ensemble des décisions d'architecture prises dans le reste de la documentation (`02_*.md`, `03_*.md`, etc.). Toute déviation par rapport aux principes énoncés ici doit être justifiée et documentée.

---

## 1\. Titre & vue d'ensemble du projet

**CIH AI Banking** est un assistant bancaire virtuel intelligent reposant sur une **architecture multi-agents autonomes**, où deux agents spécialisés collaborent via un protocole **Agent-to-Agent (A2A)** plutôt que via un unique modèle monolithique.

### 1.1 Définition

Le système expose à l'utilisateur une interface conversationnelle unique, mais cette interface est en réalité soutenue par deux agents indépendants, chacun responsable d'un périmètre fonctionnel strictement délimité :

- un agent d'accueil et de consultation, exposé directement au client ;  
- un agent transactionnel, invisible du client, spécialisé dans l'exécution sécurisée des opérations sensibles.

### 1.2 Objectif principal

> Offrir une expérience utilisateur fluide et disponible en continu pour les besoins de consultation (FAQ, RAG), **tout en garantissant une sécurité maximale et non-contournable** pour les opérations transactionnelles à enjeu financier (virements bancaires).

Ces deux objectifs sont en tension naturelle : la fluidité conversationnelle pousse vers la flexibilité, la sécurité bancaire exige la rigidité et le contrôle. L'architecture décrite dans ce document résout cette tension par la **séparation physique et logique** des deux préoccupations plutôt que par des garde-fous ajoutés a posteriori à un système unique.

---

## 2\. Problématique & valeur ajoutée

### 2.1 Pourquoi pas un chatbot monolithique ?

Une approche naïve consisterait à confier l'intégralité des responsabilités (FAQ, consultation de compte, exécution de virement) à un seul agent doté d'un large éventail d'outils. Cette approche est **délibérément écartée** pour les raisons suivantes :

| Problème du modèle monolithique | Réponse apportée par le multi-agent |
| :---- | :---- |
| Un prompt unique et volumineux mélange instructions conversationnelles et règles de sécurité critiques — plus un prompt est long et polyvalent, plus il est difficile à auditer et plus le risque de contournement (prompt injection, dérive de comportement) augmente. | Chaque agent reçoit un prompt court, spécialisé, et strictement borné à son périmètre. Un agent qui ne connaît pas l'existence d'un outil de virement ne peut pas être manipulé pour l'invoquer. |
| Une seule faille de raisonnement du modèle peut affecter aussi bien une réponse anodine (FAQ) qu'une opération financière. | L'isolation agit comme un compartimentage : une erreur de raisonnement de l'agent conversationnel n'a aucune capacité d'exécution sur le système bancaire. Seul l'Agent 2 dispose de ce pouvoir, et il est conçu pour être maximaliste dans ses vérifications. |
| Difficile à faire évoluer : ajouter une nouvelle capacité oblige à retester l'ensemble du comportement de l'agent. | Chaque agent évolue indépendamment. Faire évoluer la base de FAQ n'a aucun impact sur la logique de validation des virements, et inversement. |
| Testabilité et auditabilité faibles (un seul bloc de décision opaque). | Chaque agent constitue une unité testable isolément, avec des scénarios de test dédiés et un historique d'audit propre. |

### 2.2 Valeur ajoutée de l'architecture retenue

- **Séparation des responsabilités** : un agent \= un métier \= un ensemble d'outils clairement délimité.  
- **Isolation de la sécurité** : la logique de contrôle des opérations sensibles est concentrée dans un unique composant (l'Agent 2), plus facile à sécuriser, auditer et faire évoluer réglementairement qu'une logique diffuse.  
- **Prompts courts et spécialisés** : un prompt focalisé réduit la surface d'ambiguïté et améliore la fiabilité du modèle.  
- **Communication standardisée** : le protocole A2A formalise l'échange entre agents (découverte de capacités via *Agent Card*, cycle de vie de tâche), ce qui rend l'architecture extensible à un futur troisième agent sans reconception globale.

---

## 3\. Description des deux agents principaux

### 3.1 Agent 1 — Assistant FAQ & Orientation

**Rôle** : point d'entrée unique de l'utilisateur. C'est le seul agent avec lequel le client interagit directement.

**Responsabilités :**

- Répondre aux questions publiques et générales (frais bancaires, conditions d'ouverture de compte, procédures courantes) grâce à une architecture **RAG (Retrieval-Augmented Generation)** adossée à **ChromaDB**.  
- Déterminer à chaque message l'**état de session** de l'utilisateur (authentifié ou non-authentifié), transmis de façon fiable par le Backend.  
- Pour un utilisateur authentifié, consulter des données personnelles en **lecture seule** (solde, historique de transactions) via des outils bancaires dédiés — sans jamais persister ces données dans ChromaDB.  
- Détecter toute intention de virement et **déléguer** immédiatement la demande à l'Agent 2 via le protocole A2A, sans jamais tenter d'exécuter l'opération lui-même.

>   
> **Règle non négociable** : l'Agent 1 est structurellement **interdit** d'exécuter ou même d'initier une action sensible (virement, modification de compte) lorsqu'un utilisateur n'est pas authentifié. Cette interdiction est appliquée dans la logique du graphe (LangGraph), pas seulement suggérée dans le prompt — une instruction en langage naturel n'est jamais considérée comme une garantie de sécurité suffisante.

### 3.2 Agent 2 — Agent Transactionnel de Haute Sécurité

**Rôle** : exécuteur unique et exclusif des opérations sensibles. Invisible du client, il n'est jamais contacté directement — uniquement via une délégation A2A émise par l'Agent 1\.

**Responsabilités, dans un ordre de contrôle strict :**

1. Revérifier l'authentification de l'utilisateur (aucune confiance accordée à l'état transmis par l'Agent 1 sans revalidation).  
2. Vérifier l'existence et la validité du bénéficiaire.  
3. Vérifier la cohérence du montant demandé.  
4. Vérifier que le solde disponible couvre l'opération.  
5. Vérifier le respect des plafonds bancaires (journaliers/mensuels).  
6. Demander une **confirmation explicite** du client.  
7. Déclencher un **contrôle OTP** (code à usage unique) — **obligatoire pour tout virement, quel que soit le montant**, sans exception ni seuil.  
8. Une fois l'ensemble des contrôles validés, invoquer l'outil d'exécution exposé via **MCP**, qui déclenche à son tour le workflow **n8n** responsable de l'exécution réelle côté système bancaire.

>   
> **Principe de conception** : l'Agent 2 ne fait jamais confiance par défaut. Chaque contrôle est une porte fermée par défaut, ouverte uniquement si la condition est explicitement vérifiée. Aucune étape de validation ne peut être court-circuitée par le contenu d'un message utilisateur.

### 3.3 Synthèse comparative

| Critère | Agent 1 (FAQ & Orientation) | Agent 2 (Transactionnel) |
| :---- | :---- | :---- |
| Exposition | Directe (client) | Indirecte (uniquement via A2A) |
| Données manipulées | FAQ publiques, données personnelles en lecture seule | Données transactionnelles sensibles, en écriture |
| Mémoire persistante | Base vectorielle ChromaDB (contenu public uniquement) | Aucune donnée personnelle persistée localement |
| Capacité d'exécution | Aucune sur le système bancaire | Exclusive, encadrée par 7 contrôles successifs |
| Tolérance à l'erreur | Modérée (réponse informative) | Nulle (opération financière irréversible) |

---

## 4\. Composants clés du système

| Composant | Technologie retenue | Rôle dans l'architecture |
| :---- | :---- | :---- |
| Interface utilisateur | React \+ TailwindCSS | Restitue la conversation et les écrans de confirmation/OTP ; aucune logique métier ou de sécurité côté client. |
| API Backend | FastAPI | Gère l'authentification, les sessions et les tokens ; expose les endpoints consommés par le frontend ; transmet un état de session fiable aux agents sans jamais arbitrer lui-même la logique métier. |
| Orchestration IA | LangChain & LangGraph | Modélise chaque agent comme un graphe d'états ; gère un `SharedState` propageant le contexte utile (identité, statut d'authentification, historique récent) entre les nœuds d'un même agent. |
| Moteur LLM | Mistral (exécution locale via Ollama) | Modèle de langage utilisé par les deux agents ; l'exécution locale garantit qu'aucune donnée bancaire ne transite vers un fournisseur tiers. |
| Recherche documentaire (RAG) | ChromaDB | Stocke exclusivement les documents publics de la FAQ (frais, procédures, conditions) sous forme vectorielle. **Aucune donnée personnelle ou transactionnelle n'y est persistée.** |
| Protocole de communication inter-agents | Agent-to-Agent (A2A) | Formalise la délégation d'une tâche de l'Agent 1 vers l'Agent 2 : découverte des capacités via *Agent Card*, soumission de tâche, gestion du cycle de vie (`submitted` → `working` → `input-required` → `completed`/`failed`). |
| Protocole d'accès aux outils | Model Context Protocol (MCP) | Standardise l'accès de l'Agent 2 à ses outils d'exécution ; l'agent ne dialogue jamais directement avec le système bancaire, uniquement avec des outils exposés et contrôlés via MCP. |
| Automatisation de l'exécution | n8n (déclenché via Webhook HTTP) | Reçoit l'appel de l'outil MCP, orchestre l'exécution réelle (ou simulée) de l'opération dans le système bancaire, journalise l'action et déclenche la notification au client. |

---

## 5\. Cycle de vie d'une requête — scénario de virement

Le scénario suivant illustre le parcours complet d'une demande de virement, de la saisie initiale jusqu'à la confirmation finale.

1. **Saisie utilisateur (React)** — L'utilisateur, déjà authentifié, écrit dans l'interface de chat : *« Envoie 2000 MAD à ma mère »*.  
     
2. **Transmission au Backend (FastAPI)** — Le frontend envoie le message au endpoint `/chat`, accompagné du token de session. Le middleware d'authentification décode le token et enrichit la requête avec `is_authenticated=true` et `user_id`.  
     
3. **Réception par l'Agent 1** — L'Agent 1 reçoit le message et le statut de session. Le nœud `classify_intent` du graphe LangGraph identifie une intention de virement.  
     
4. **Délégation A2A** — L'Agent 1 ne traite pas la demande lui-même. Il consulte l'*Agent Card* de l'Agent 2, confirme qu'il expose la capacité *« traiter un virement bancaire »*, puis lui soumet une tâche A2A contenant les paramètres extraits (bénéficiaire, montant) et le contexte d'authentification.  
     
5. **Prise en charge par l'Agent 2** — La tâche A2A passe à l'état `working`. L'Agent 2 exécute séquentiellement ses contrôles : revalidation de l'authentification, existence du bénéficiaire, cohérence du montant, suffisance du solde, respect du plafond.  
     
6. **Demande de confirmation** — Tous les contrôles automatiques étant positifs, la tâche passe à l'état `input-required` : l'Agent 2 demande une confirmation explicite du client. Cette question remonte à l'Agent 1, qui la relaie au Backend puis au frontend React.  
     
7. **Validation OTP** — Le client confirme l'opération. L'OTP étant obligatoire pour tout virement, quel que soit le montant, l'Agent 2 déclenche systématiquement l'envoi d'un code OTP (simulé pour ce prototype, voir `04_scenarios_et_securite.md` §4.4) et attend sa saisie. Le frontend affiche l'écran de vérification dédié ; le code est transmis par le même chemin (React → Backend → Agent 1 → tâche A2A).  
     
8. **Exécution via MCP** — Le code OTP étant validé, l'Agent 2 invoque l'outil `initiate_transfer` exposé via MCP.  
     
9. **Déclenchement du workflow n8n** — L'outil MCP appelle le Webhook HTTP du workflow n8n dédié, qui exécute (ou simule) l'opération dans le système bancaire, enregistre la transaction et déclenche une notification (SMS/email).  
     
10. **Retour du résultat** — Le résultat de l'exécution remonte : n8n → outil MCP → Agent 2, qui clôt la tâche A2A à l'état `completed` (ou `failed` en cas d'échec) et retourne la réponse à l'Agent 1\.  
      
11. **Restitution au client** — L'Agent 1 reçoit la confirmation, la met en forme dans un langage naturel et clair, et la transmet au Backend puis au frontend React, qui l'affiche à l'utilisateur.

>   
> **Point d'attention architectural** : à aucune étape de ce cycle l'Agent 1 n'accède directement aux outils bancaires sensibles, et à aucune étape l'Agent 2 n'accepte un paramètre sans revalidation. La sécurité du système repose sur la **redondance des contrôles** entre les niveaux, jamais sur la confiance implicite envers le niveau précédent.  
