# Journal des modifications — Agent 1 (`agents/agent1_faq/`)

> Documente les évolutions apportées au graphe LangGraph de l'Agent 1 au fil
> de cette série de changements. Ne remplace pas `DocsContext/` (non modifié,
> par consigne) — ce fichier est un journal technique local au module.

---

## Vue d'ensemble — architecture finale

```
Utilisateur
   ↓
security_guard                — SÉCURITÉ UNIQUEMENT (classification.detect_sensitive_operation)
   ↓ (si non sensible)
conversational_understanding  — filtre rapide déterministe (greeting/thanks/small talk/message court)
   ↓ (si non conversationnel)
llm_router (Mistral/Ollama)   — CLASSIFICATEUR PRINCIPAL, vocabulaire étendu
   ↓ (si Mistral échoue/désactivé — repli de secours uniquement)
classify_fallback             — classification.classify_intent (déterministe complet)
   ↓
route_decision → route_edge
   ↓
{answer_faq (ChromaDB) | answer_personal_data (banking.db) | require_login |
 service_unavailable | answer_conversational}
```

Chaque saut est une **arête conditionnelle explicite** du graphe
(`add_conditional_edges`), jamais une décision laissée à l'appréciation d'un
LLM. Le Security Guard et le filtre conversationnel sont deux étapes
*pré-Mistral*, mais aucune des deux ne concurrence Mistral pour la
classification bancaire : la première ne connaît que `virement`/`compte_action`,
la seconde ne reconnaît que du pur small-talk (correspondance intégrale du
message) — toute vraie question tombe systématiquement vers Mistral.

---

## 1. Réorganisation du graphe : Mistral avant la classification déterministe

**Avant :** un seul nœud `classify_intent` calculait `classification.classify_intent()`
(déterministe, 4 catégories) **avant** Mistral, et Mistral ne pouvait
qu'*écraser* une valeur déjà calculée.

**Après (`graph.py`) :** trois nœuds distincts, reliés par des arêtes
conditionnelles réelles (pas un simple `if` interne) :

- `security_guard` — garde 100 % déterministe, évaluée en premier pour
  *chaque* message, avant tout appel réseau.
- `llm_router` — Mistral appelé **en premier** comme classificateur principal
  pour les questions bancaires (`personal_data`/`faq_generale`).
- `classify_fallback` — atteint **uniquement** si Mistral échoue/est
  désactivé/retourne `"unclear"` : filet de sécurité, jamais un
  classificateur concurrent en fonctionnement normal.

## 2. Logs de debug temporaires

Un bloc `[TEMP-DEBUG]` a été ajouté dans `_route_edge` (`graph.py`), imprimé
une fois par requête, affichant : message original, résultat du Security
Guard (recalculé uniquement pour l'affichage, sans effet sur la décision déjà
prise), sortie JSON brute de Mistral, intent final retenu, route finale
(`faq_public`/`personal_data`/`service_unavailable`). **Marqué temporaire** —
à retirer avant mise en production, aucune logique n'a été modifiée pour
l'ajouter.

## 3. Couche de compréhension conversationnelle (nouveau fichier `conversational.py`)

Ajout d'un filtre déterministe, **avant** Mistral, qui reconnaît :
`greeting` (slm, salam, bonjour, hi…), `thanks` (merci, chokran…),
`small_talk` (ça va, labas…), `unclear_short` (message vide/filler/pure
ponctuation). Approche conservatrice : un message n'est intercepté que s'il
correspond **intégralement** à ce vocabulaire — un message mêlant salutation
et vraie question ("bonjour, quel est mon solde ?") continue normalement vers
Mistral. Ces messages ne touchent jamais ChromaDB ni `banking_db`.

Nœuds ajoutés au graphe : `conversational_understanding` → `answer_conversational`
(réponses localisées via de nouvelles fonctions dans `response_localizer.py` :
`localize_greeting`, `localize_thanks`, `localize_small_talk`,
`localize_unclear_short`).

## 4. Security Guard : rôle strictement limité à la sécurité

**Avant :** `security_guard` appelait `classification.classify_intent()` (le
classificateur complet à 4 catégories) puis jetait le résultat s'il n'était
pas `virement`/`compte_action` — fonctionnellement correct, mais pas
structurellement "sécurité uniquement".

**Après (`classification.py`) :** extraction de
`detect_sensitive_operation()`, une fonction dédiée qui ne connaît même pas
les patterns `personal_data`/`faq_generale` — structurellement incapable de
retourner autre chose que `virement`/`compte_action`/`None`.
`classify_intent()` (toujours utilisée par `classify_fallback`) délègue
maintenant à cette fonction en interne ; comportement identique, contrat plus
strict pour `security_guard`.

## 5. Mistral : vocabulaire étendu (`llm_router.py`)

`_VALID_INTENTS` inclut désormais `greeting`/`thanks` (en plus de
`faq_search`, `balance_query`, `card_query`, etc.) — défense en profondeur :
si une salutation/un remerciement échappe au filtre déterministe rapide
(point 3), Mistral la reconnaît quand même. Prompt système enrichi
d'exemples (`bghit n7ell compte`, `J'ai perdu ma carte`, `slm`, `merci`).
Câblage correspondant dans `graph.py` (`_llm_router_node`/`_after_llm_router`) :
une sortie Mistral `greeting`/`thanks` route vers `answer_conversational`.

## 6. Nouveau fichier de tests

`backend/tests/test_mistral_primary_architecture.py` — couvre les 7 messages
demandés (`slm`, `bonjour`, `merci`, `bghit n7ell compte`,
`J'ai perdu ma carte`, `ch7al 3ndi fl compte`, `kel est mon sold`) et vérifie :
Security Guard structurellement incapable de classer `personal_data`/
`faq_public`/`card_query`/`balance_query` ; Mistral (mocké) comprend
correctement chaque message ; les données bancaires viennent exclusivement de
`banking.db` (jamais inventées par le LLM) ; l'authentification reste
obligatoire quelle que soit l'intention reconnue ; repli garanti sur
`classify_fallback` (jamais sur le Security Guard) si Mistral échoue.

---

## Fichiers modifiés (session complète)

| Fichier | Nature du changement |
|---|---|
| `agents/agent1_faq/graph.py` | Restructuration complète du graphe (nœuds `security_guard`, `conversational_understanding`, `answer_conversational`, `llm_router`, `classify_fallback`), logs debug temporaires |
| `agents/agent1_faq/classification.py` | Extraction de `detect_sensitive_operation()`, `classify_intent()` refactorée pour déléguer |
| `agents/agent1_faq/llm_router.py` | Vocabulaire étendu (`greeting`, `thanks`) + exemples de prompt |
| `agents/agent1_faq/conversational.py` | **Nouveau fichier** — filtre déterministe conversationnel |
| `agents/agent1_faq/response_localizer.py` | Ajout de `localize_greeting`/`localize_thanks`/`localize_small_talk`/`localize_unclear_short` |
| `backend/tests/test_llm_first_routing.py` | Existant, non modifié dans cette dernière étape — toujours valide |
| `backend/tests/test_mistral_primary_architecture.py` | **Nouveau fichier** — tests dédiés à cette architecture |

**Non modifiés (consigne explicite) :** `frontend/`, `auth.db`, `banking.db`,
`chroma_db/`, `DocsContext/`, `CLAUDE.md`, `banking_answers.py`.

## Résultat des tests

Suite complète : **286 passed, 8 skipped** (les 8 skip = tests d'intégration
Ollama réel, désactivés par défaut, voir `test_ollama_integration.py`).
