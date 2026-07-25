# CIH AI Banking

> **Projet academique / prototype de demonstration.** Toutes les donnees (clients, comptes, soldes, beneficiaires, transactions, codes OTP) sont **fictives**. Aucune connexion a un systeme bancaire reel n'existe. Ce depot n'a aucune vocation de production.

## Objectif

Explorer une architecture **multi-agents autonomes** pour un assistant bancaire conversationnel, en separant strictement deux preoccupations qui sont habituellement melangees dans un chatbot unique :

- repondre a des questions generales et consulter des donnees personnelles en lecture seule ;
- executer une operation sensible (un virement) sous un controle de securite maximal.

La documentation de reference complete se trouve dans [`DocsContext/`](./DocsContext) et est synthetisee dans [`CLAUDE.md`](./CLAUDE.md).

## Les deux agents

- **Agent 1 — FAQ & Orientation** : point d'entree unique du client. Repond aux questions publiques via RAG (ChromaDB), consulte en lecture seule le solde/historique d'un client authentifie, et detecte les demandes de virement pour les deleguer — il n'execute jamais lui-meme une operation sensible. Pour ce prototype, c'est un module Python integre au backend FastAPI (pas de service separe).
- **Agent 2 — Transactionnel de haute securite** : seul composant autorise a executer un virement. Invisible du client, contacte uniquement via une delegation **Agent-to-Agent (A2A)**. Applique une sequence de 7 controles fonctionnels stricts (authentification, beneficiaire, montant, solde, plafonds, confirmation, OTP) avant toute execution.

## Role des composants techniques

| Composant | Role |
| :---- | :---- |
| **FastAPI** | Backend applicatif : authentification, sessions, endpoint `/api/chat`, et heberge l'Agent 1 comme module interne. |
| **A2A (Agent-to-Agent)** | Protocole standardise par lequel l'Agent 1 delegue une tache de virement a l'Agent 2, avec un jeton de delegation signe et un cycle de vie de tache explicite. |
| **MCP (Model Context Protocol)** | Standardise l'acces de l'Agent 2 a son outil d'execution (`initiate_transfer`) — l'agent ne dialogue jamais directement avec un systeme bancaire. |
| **n8n** | Orchestre l'execution (simulee) du virement une fois l'outil MCP invoque, et journalise l'operation. |
| **ChromaDB** | Base vectorielle utilisee par le RAG de l'Agent 1, contenant exclusivement des documents publics de FAQ — jamais de donnees personnelles. |
| **Ollama (Mistral)** | Execution locale du modele de langage utilise par les deux agents, garantissant qu'aucune donnee bancaire ne transite vers un fournisseur tiers. |

## Simulation

Ce prototype ne se connecte a aucun systeme bancaire reel :

- un service `mock-banking-api` simule comptes, soldes, beneficiaires, plafonds et virements ;
- l'OTP est simule (`MockOtpService`, code de demonstration configurable) — aucun fournisseur SMS/e-mail reel n'est integre ;
- toutes les identites, montants et operations sont fictifs et reserves a la demonstration.

## Etat du projet

Le projet en est a la **Phase 0** (fondations et arborescence). Voir `CLAUDE.md` (§13) pour le plan complet par phases. Aucun code applicatif n'est encore present.
