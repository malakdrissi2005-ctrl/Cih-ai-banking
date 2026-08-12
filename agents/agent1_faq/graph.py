"""Graphe LangGraph de l'Agent 1 — FAQ publique + questions bancaires personnelles,
en français et en darija marocaine (arabe et Arabizi).

Implémente les nœuds `security_guard`, `conversational_understanding`,
`answer_conversational`, `llm_router`, `classify_fallback`, `route_decision`,
`answer_faq`, `require_login`, `answer_personal_data` et
`service_unavailable` décrits dans `DocsContext/02_architecture_multi_agents.md`
(§2, §2.4). Le routage vers les nœuds de réponse est appliqué par une arête
conditionnelle explicite du graphe (`add_conditional_edges`), jamais laissé à
l'appréciation d'un LLM :

- salutation/remerciement/small talk/message court inintelligible
  (`conversational.py`)                              → `answer_conversational`
  (gabarit localisé, jamais ChromaDB ni `banking_db`)
- question publique (`faq_generale`)                → `answer_faq` (ChromaDB)
- question personnelle (`balance_query`/`transactions_query`/`spending_analysis`/
  `beneficiaries_query`/`salary_query`/`last_direct_debit_query`, préservées
  telles quelles depuis Mistral — voir §"Préservation des intentions"
  ci-dessous — ou `personal_data` générique en repli déterministe) + session
  valide                                              → `answer_personal_data`
  invalide/absente                                    → `require_login`
- `card_query` : FAQ générale par défaut, sauf si le message signale la carte
  PERSONNELLE de l'utilisateur (`_mentions_own_card`, ex. "ma carte") — alors
  même routage que les autres questions personnelles ci-dessus
- demande de virement ou de modification bancaire     → `service_unavailable`
  (`virement`/`compte_action`, quel que soit l'état d'authentification)

Ordre de compréhension — Mistral EST le classificateur principal pour les
questions bancaires, appelé en premier dans le graphe pour toute question non
sensible et non conversationnelle, structurellement avant
`classification.classify_intent` :

    START → security_guard → personal_entity_guard → conversational_understanding
          → llm_router → classify_fallback → route_decision

ORDRE DE PRIORITÉ DES INTENTIONS (du plus fort au plus faible) :

    1. Security Guard              — virement / action de compte, 100% déterministe
    2. Entité personnelle précise  — `personal_entity_guard`, décision FINALE
    3. Repli personnel générique   — entité + possession sans sous-intention précise
    4. Messages conversationnels   — salutation, remerciement, small talk
    5. FAQ publique / RAG          — dernier recours, jamais avant les précédents

0bis. `personal_entity_guard` : deuxième étape déterministe pré-LLM. Reconnaît
   de façon COMPOSITIONNELLE (`personal_entities.py`) une demande portant sur
   une donnée bancaire personnelle — entité bancaire (rib, iban, numéro de
   compte, solde, opérations…) combinée à un marqueur de possession (mon, ma,
   mes, dyali, ديالي…). Sa décision est FINALE : Mistral ne la revoit jamais.
   Corrige le défaut de hiérarchie qui faisait que « Quel est mon RIB ? »
   recevait une définition publique, « je veux voir mon rib » une réponse sur
   le mot de passe et « je veux connaitre mon rib » le solde total — trois
   réponses différentes pour une même demande, alors que le classificateur
   déterministe traitait correctement les trois mais n'avait aucune autorité
   face au LLM. Une question de définition sans possessif (« Qu'est-ce qu'un
   RIB ? ») n'est pas interceptée et poursuit vers la FAQ.

1. `security_guard` : la SEULE étape strictement pré-LLM, évaluée pour
   *chaque* message avant tout appel réseau — une garde 100% déterministe,
   incontournable, qui appelle EXCLUSIVEMENT
   `classification.detect_sensitive_operation`. Cette fonction ne connaît même
   pas les patterns `personal_data`/`faq_generale` : elle est structurellement
   incapable de retourner autre chose que `virement`/`compte_action`/`None` —
   le Security Guard protège l'accès, il ne choisit jamais l'intention. Si
   elle matche, une arête conditionnelle saute directement à `route_decision` :
   `conversational_understanding`, `llm_router` et `classify_fallback` ne sont
   même pas exécutés, Mistral n'est **jamais** consulté pour ces cas et ne
   peut **jamais** faire basculer le bucket vers l'un d'eux, quel que soit son
   résultat (voir CLAUDE.md §2, §13 règle 5 : aucun chemin bancaire sensible
   ne doit dépendre de l'appréciation d'un modèle de langage).
2. `conversational_understanding` : couche déterministe (`conversational.py`,
   aucun appel LLM) qui reconnaît salutations, remerciements, small talk et
   messages courts inintelligibles — un message qui n'est **entièrement**
   composé que de ce vocabulaire est répondu directement par
   `answer_conversational`, sans jamais atteindre ChromaDB ni `banking_db`,
   ni consommer un appel Mistral. Un message qui mélange une salutation et
   une vraie question ("bonjour, quel est mon solde ?") n'est **pas**
   intercepté ici et continue normalement vers `llm_router`. Optimisation de
   latence uniquement — pas une classification concurrente de Mistral : voir
   point 3 ci-dessous, `greeting`/`thanks` font aussi partie du vocabulaire
   Mistral, en défense en profondeur.
3. `llm_router` : si aucune des deux étapes précédentes n'a rien détecté,
   Mistral (`llm_router.py`) est appelé **en premier** comme classificateur
   principal — pour `personal_data`/`faq_generale` mais aussi, en repli de la
   couche déterministe du point 2, pour `greeting`/`thanks` — utile en cas de
   fautes de frappe, de darija (arabe ou Arabizi) mal normalisée par
   `darija_normalization.py`. En cas de succès (intention concrète reconnue),
   une arête conditionnelle saute directement à `route_decision`
   (ou `answer_conversational` pour `greeting`/`thanks`) : `classify_fallback`
   n'est pas exécuté.
4. `classify_fallback` : atteint **uniquement** si Mistral est désactivé, non
   configuré, indisponible, en timeout, renvoie un JSON invalide, ou une
   intention "unclear" de faible confiance — repli de secours garanti sur
   `classification.classify_intent` (déterministe), exactement comme avant.
   Ce nœud ne revoit jamais `virement`/`compte_action` : ces cas ont déjà été
   écartés par `security_guard`. Ce n'est qu'un filet de sécurité en cas
   d'échec du LLM, jamais un classificateur concurrent de Mistral en
   fonctionnement normal — Agent 1 utilise la sortie de Mistral dès qu'elle
   est disponible.

Préservation des intentions (`_llm_router_node`) : une intention concrète
reconnue par Mistral (`balance_query`, `transactions_query`, `card_query`,
`beneficiaries_query`, `spending_analysis`, `salary_query`,
`last_direct_debit_query`) est reportée TELLE QUELLE dans `intent` — plus
jamais appauvrie vers un bucket générique `personal_data`. La décision
d'authentification et le choix du nœud de traitement en sont **complètement
découplés** : `_route_decision_node`/`_route_edge` les recalculent séparément
à partir de cette intention précise et de la session (`_AUTH_REQUIRED_INTENTS`),
jamais à partir d'une supposition faite par Mistral lui-même. L'authentification
requise reste, comme avant, strictement basée sur la session (`is_authenticated`)
— jamais recalculée à partir de la sortie de Mistral : une question
personnelle identifiée par Mistral chez un utilisateur non authentifié
aboutit toujours à `require_login`, jamais à une donnée réelle.

Couche linguistique (voir `language_detection.py`, `darija_normalization.py`,
`response_localizer.py`) strictement séparée de la logique métier ci-dessus :
- `original_message` : message tel que reçu, jamais modifié.
- `detected_language` : "fr" | "darija_ar" | "darija_latn", détecté
  déterministiquement sur `original_message`.
- `normalized_message` : `original_message` inchangé si "fr", sinon converti
  vers des termes canoniques français — **uniquement** utilisé par la
  classification (`classify_intent`, `classify_personal_intent`) et la
  recherche ChromaDB. Jamais utilisé pour construire une requête SQL.
- La réponse finale est mise en phrase selon `detected_language`
  (`response_localizer`), sans jamais modifier un montant, une date, un
  numéro ou une condition bancaire récupérés de `banking_db`/ChromaDB.

Hors périmètre pour cette étape (voir `CLAUDE.md`) : Agent 2, protocole A2A,
MCP, n8n, toute exécution réelle (virement, changement de plafond, blocage de
carte). Les données bancaires ne sont jamais indexées dans ChromaDB.
"""
from __future__ import annotations

import re
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.agent1_faq import conversation_memory, llm_router, personal_entities, response_localizer
from agents.agent1_faq.banking_answers import build_personal_data_answer
from agents.agent1_faq.classification import _normalize, classify_intent, detect_sensitive_operation
from agents.agent1_faq.conversational import classify_conversational
from agents.agent1_faq.darija_normalization import normalize_darija_message
from agents.agent1_faq.language_detection import detect_language
from agents.agent1_faq.rag import (
    FaqEmbeddingDimensionMismatchError,
    get_faq_collection,
    search_faq,
    search_faq_candidates,
)

REQUIRE_LOGIN_MESSAGE = "Pour consulter vos informations personnelles, vous devez d'abord vous connecter à votre espace client."

SERVICE_UNAVAILABLE_MESSAGE = "Ce service n'est pas disponible pour le moment."

NO_FAQ_MESSAGE = (
    "Aucune information n'est disponible pour le moment dans notre base de connaissances. "
    "Merci de reformuler votre question ou de contacter le service client."
)


class Agent1State(TypedDict, total=False):
    message: str
    original_message: str
    normalized_message: str
    detected_language: str
    session_info: dict
    session_id: Optional[str]
    use_llm_router: bool
    collection: Any
    banking_db_path: Optional[str]
    # "virement"/"compte_action"/"personal_data"/"faq_generale" (classification.Intent,
    # repli deterministe) OU une intention Mistral CONCRETE preservee telle
    # quelle ("balance_query"/"transactions_query"/"card_query"/
    # "beneficiaries_query"/"spending_analysis"/"salary_query"/
    # "last_direct_debit_query" - voir _LLM_CONCRETE_PERSONAL_INTENTS) OU
    # "greeting"/"thanks"/"small_talk"/"unclear_short" (conversational.ConversationalIntent) :
    # vocabulaires disjoints qui partagent ce même champ, résolu progressivement
    # au fil du graphe (security_guard -> conversational_understanding -> llm_router ->
    # classify_fallback).
    intent: Optional[str]
    llm_parsed: Optional[dict]
    # Entite bancaire personnelle reconnue de facon deterministe par
    # `_personal_entity_guard_node` (rib/iban, solde, transactions...), ou None.
    # Purement informatif pour le diagnostic et les tests : la decision de
    # routage est deja portee par `intent`.
    personal_entity: Optional[str]
    requires_auth: bool
    # Résultat de `_mentions_own_card`, calculé par `_route_decision_node`
    # uniquement quand `intent == "card_query"` — DOIT être déclaré ici : une
    # clé absente du schéma `Agent1State` est silencieusement ignorée par les
    # canaux d'état de LangGraph et ne serait jamais visible par `_route_edge`
    # (bug constaté et corrigé — voir tests, `card_query` retombait toujours
    # sur `answer_faq`).
    card_query_is_personal: bool
    response: Optional[str]


# Intentions "concrètes" que Mistral (`llm_router.py`) est autorisé à faire
# gagner le bucket `personal_data` — exclut volontairement "unclear" (simple
# signal de faible confiance, jamais utilisé pour changer de bucket : en cas
# d'incertitude du LLM, on retombe sur la classification déterministe,
# exactement comme en cas d'échec) et "faq_search" (traité séparément,
# fait gagner `faq_generale`).
_LLM_CONCRETE_PERSONAL_INTENTS = {
    "balance_query",
    "transactions_query",
    "card_query",
    "beneficiaries_query",
    "spending_analysis",
    "salary_query",
    "last_direct_debit_query",
}


def _security_guard_node(state: Agent1State) -> dict:
    """Seule étape strictement pré-LLM du graphe — évaluée pour CHAQUE message,
    avant tout appel réseau vers Mistral. Appelle exclusivement
    `classification.detect_sensitive_operation`, structurellement incapable de
    retourner `personal_data`/`faq_generale` (ni a fortiori une sous-intention
    comme `card_query`/`balance_query`) : le Security Guard protège l'accès
    (virement/action de compte), il ne choisit jamais l'intention — celle-ci
    est tranchée plus loin dans le graphe, par `conversational_understanding`,
    puis `llm_router` (Mistral, classificateur principal) et, en tout dernier
    recours, `classify_fallback`. `intent` reste `None` tant qu'aucune sortie
    sensible n'est détectée : c'est ce `None` que `_after_security_guard`
    teste pour décider si le graphe continue ou saute directement à
    `route_decision`.
    """
    original = state["message"]
    language = detect_language(original)
    normalized_message = normalize_darija_message(original) if language != "fr" else original

    sensitive_intent = detect_sensitive_operation(normalized_message)

    return {
        "original_message": original,
        "normalized_message": normalized_message,
        "detected_language": language,
        "intent": sensitive_intent,
        "llm_parsed": None,
        "personal_entity": None,
    }


def _after_security_guard(state: Agent1State) -> str:
    return "route_decision" if state.get("intent") is not None else "personal_entity_guard"


# Entité reconnue -> intention personnelle à imposer QUAND, et seulement quand,
# la chaîne de classification a conclu « question publique ».
#
# Le veto ne réécrit jamais une intention personnelle déjà correcte : Mistral
# garde la main sur le vocabulaire (`balance_query`, `card_query`…) et le repli
# déterministe garde son bucket générique `personal_data`. Le contrat de
# `POST /api/chat` est donc inchangé dans tous les cas où il était déjà juste.
#
# `account_identifiers` n'a pas d'équivalent dans le vocabulaire Mistral : il
# passe par `personal_data`, dont `banking_answers.classify_personal_intent`
# tire ensuite la sous-intention précise.
_ENTITY_VETO_INTENT = {
    personal_entities.ACCOUNT_IDENTIFIERS: "personal_data",
    personal_entities.BALANCE: "personal_data",
    personal_entities.TRANSACTIONS: "personal_data",
    personal_entities.BENEFICIARIES: "personal_data",
    # Les deux entités carte passent aussi par `personal_data` : c'est
    # l'étiquette que produisait déjà le repli déterministe pour ces messages,
    # et `_route_decision_node` la traite comme exigeant une session. Émettre
    # `card_query` ici changerait la valeur du champ `intent` renvoyé par
    # `POST /api/chat` sans rien apporter.
    personal_entities.CARD_NUMBER: "personal_data",
    personal_entities.CARD_INFORMATION: "personal_data",
}


# Entités dont le signal textuel est EXACT et sans ambiguïté : « rib », « iban »,
# « numéro de carte ». Pour celles-ci, le veto s'impose même face à une autre
# intention PERSONNELLE — c'était le bug n°2, Mistral répondant `balance_query`
# sur « je veux connaitre mon rib » et l'utilisateur recevant son solde.
#
# Les entités plus floues (solde, opérations, bénéficiaires) restent soumises au
# veto uniquement contre la FAQ : leur vocabulaire se recouvre, et l'étiquette
# fine de Mistral y est souvent meilleure que la nôtre.
_PRECISE_VETO_ENTITIES = {
    personal_entities.ACCOUNT_IDENTIFIERS,
    personal_entities.CARD_NUMBER,
}

# Étiquettes déjà correctes pour ces entités : le veto les laisse passer.
# Pour `account_identifiers`, seul `personal_data` convient — c'est la seule
# étiquette dont `banking_answers` tire la sous-intention `account_identifiers`.
# Toute autre intention personnelle (`balance_query` en tête) est précisément
# l'erreur à corriger.
_ENTITY_ACCEPTABLE_INTENTS = {
    personal_entities.ACCOUNT_IDENTIFIERS: {"personal_data"},
    personal_entities.CARD_NUMBER: {"personal_data", "card_query"},
}


def _apply_personal_veto(state, intent):
    """Empêche une demande personnelle reconnue de finir en FAQ/RAG.

    Retourne l'intention inchangée sauf si le message porte une entité
    bancaire possédée ET que l'intention proposée est publique — c'est
    exactement le cas qui produisait les trois réponses erronées sur le RIB.
    """
    entite = state.get("personal_entity")
    if not entite:
        return intent
    if entite in _PRECISE_VETO_ENTITIES:
        # Le veto corrige une famille ERRONÉE ; il ne renomme pas une étiquette
        # déjà correcte. Si Mistral a bien reconnu `card_query` sur une demande
        # de numéro de carte, on la conserve — la protection, elle, est de
        # toute façon appliquée plus loin de façon déterministe.
        if intent in _ENTITY_ACCEPTABLE_INTENTS[entite]:
            return intent
        return _ENTITY_VETO_INTENT[entite]
    if intent in (None, "faq_generale"):
        return _ENTITY_VETO_INTENT.get(entite, "personal_data")
    return intent


def _personal_entity_guard_node(state: Agent1State) -> dict:
    """PRIORITÉ 2 — reconnaissance déterministe et compositionnelle d'une
    demande de donnée bancaire personnelle, évaluée AVANT `llm_router`.

    RAISON D'ÊTRE — trois formulations équivalentes donnaient trois réponses
    différentes (« je veux voir mon rib » -> FAQ mot de passe, « je veux
    connaitre mon rib » -> solde total, « Quel est mon RIB ? » -> définition
    publique). Le classificateur déterministe répondait pourtant correctement
    aux trois : le défaut n'était pas le vocabulaire mais la hiérarchie. Mistral
    étant le classificateur principal, aucune règle déterministe ne pouvait le
    contredire, et une phrase bien écrite pouvait être moins bien comprise
    qu'une phrase fautive tombée dans le repli.

    Ce nœud rétablit l'ordre : entité bancaire + marqueur de possession donne
    une décision FINALE (`personal_entities.resolve`), que Mistral ne revoit
    jamais. Une question de définition sans possessif n'est pas capturée ici et
    poursuit son chemin normal vers la FAQ/RAG.

    N'accorde AUCUN accès : il fixe uniquement le bucket d'intention.
    L'authentification reste décidée par `_route_decision_node` à partir de la
    seule session serveur (CLAUDE.md §2).
    """
    match = personal_entities.resolve(
        state["normalized_message"], state.get("original_message")
    )
    return {"personal_entity": match.entity if match.is_personal else None}


def _after_personal_entity_guard(state: Agent1State) -> str:
    """Le flux continue TOUJOURS normalement.

    Ce nœud est un VETO, pas un classificateur concurrent : il n'impose pas
    d'étiquette d'intention, il retire seulement à la FAQ le droit de gagner
    (voir `_after_llm_router`, `_classify_fallback_node` et `_route_edge`).
    Mistral conserve ainsi la main sur le vocabulaire d'intention — le contrat
    de `POST /api/chat` est inchangé — mais ne peut plus envoyer « mon RIB »
    vers la documentation publique.
    """
    return "conversational_understanding"


def _conversational_understanding_node(state: Agent1State) -> dict:
    """Couche de compréhension conversationnelle (`conversational.py`) —
    évaluée pour tout message déjà écarté par `security_guard` (donc jamais
    `virement`/`compte_action`), AVANT tout appel Mistral. Purement
    déterministe : salutations, remerciements, small talk et messages courts
    inintelligibles sont reconnus ici et n'atteignent jamais `llm_router`,
    `classify_fallback`, ChromaDB ni `banking_db`.

    `intent` reste `None` si le message ne correspond à aucune de ces
    catégories — `_after_conversational_understanding` route alors vers
    `llm_router`, exactement comme avant l'ajout de ce nœud.
    """
    conversational_intent = classify_conversational(state["normalized_message"])
    return {"intent": conversational_intent}


def _after_conversational_understanding(state: Agent1State) -> str:
    return "answer_conversational" if state.get("intent") is not None else "llm_router"


def _answer_conversational_node(state: Agent1State) -> dict:
    """Réponse directe (gabarit localisé, `response_localizer.py`) pour une
    salutation/un remerciement/du small talk/un message court inintelligible.
    Ne consulte jamais ChromaDB ni `banking_db` ; ne nécessite jamais
    d'authentification (`requires_auth` fixé à `False` directement ici, ce
    nœud ne passe jamais par `route_decision`)."""
    language = state.get("detected_language", "fr")
    conversational_intent = state["intent"]
    if conversational_intent == "greeting":
        response = response_localizer.localize_greeting(language)
    elif conversational_intent == "thanks":
        response = response_localizer.localize_thanks(language)
    elif conversational_intent == "small_talk":
        response = response_localizer.localize_small_talk(language)
    else:  # "unclear_short"
        response = response_localizer.localize_unclear_short(language)

    session_id = state.get("session_id")
    if session_id:
        conversation_memory.record_turn(session_id, state["original_message"], response)
    return {"requires_auth": False, "response": response}


def _llm_router_node(state: Agent1State) -> dict:
    """Mistral comme classificateur PRINCIPAL, appelé en premier dans le graphe
    pour toute question non sensible (déjà écartée par `security_guard`), pour
    distinguer `personal_data` de `faq_generale` — utile en cas de fautes de
    frappe ou de darija mal normalisée. Ne reçoit et ne produit jamais de
    donnée bancaire : seul un intent parmi un vocabulaire fixe, déjà validé par
    `llm_router._validate_and_normalize` (`_VALID_INTENTS`, `_FORBIDDEN_KEYS`).
    N'accède jamais à `banking_db`/ChromaDB lui-même.

    `intent` reste `None` en cas d'échec/désactivation/intention "unclear" —
    `_after_llm_router` route alors vers `classify_fallback`, jamais vers une
    décision par défaut prise ici. `greeting`/`thanks` (défense en profondeur :
    variante non couverte par le filtre déterministe de
    `conversational_understanding`, ex. faute de frappe) routent vers
    `answer_conversational`, jamais vers `route_decision`.
    """
    original = state["original_message"]
    normalized_message = state["normalized_message"]
    language = state["detected_language"]

    llm_parsed: Optional[dict] = None
    if state.get("use_llm_router", False):
        session_id = state.get("session_id")
        history = conversation_memory.get_history(session_id) if session_id else []
        llm_parsed = llm_router.route_with_llm(original, normalized_message, language, conversation_history=history)

    llm_intent = llm_parsed.get("intent") if llm_parsed else None
    if llm_intent == "faq_search":
        intent = "faq_generale"
    elif llm_intent in _LLM_CONCRETE_PERSONAL_INTENTS:
        # Préservé TEL QUEL (balance_query, transactions_query, card_query,
        # beneficiaries_query, spending_analysis, salary_query,
        # last_direct_debit_query) — plus jamais collapsé vers un bucket
        # générique "personal_data". L'authentification et le nœud de
        # traitement sont décidés séparément, par la couche de routage
        # (`_route_decision_node`/`_route_edge` ci-dessous), à partir de cette
        # intention précise et de la session — jamais recalculés à partir
        # d'un bucket appauvri.
        intent = llm_intent
    elif llm_intent in ("greeting", "thanks"):
        intent = llm_intent
    else:
        # Non résolu ici : LLM désactivé/non configuré, échec (timeout, JSON
        # invalide, champ suspect -> route_with_llm retourne toujours `None`
        # dans ces cas), ou intention "unclear" -> classify_fallback tranche.
        intent = None

    # VETO : Mistral peut se tromper de famille (il répondait `faq_search` ou
    # `balance_query` sur « je veux voir mon rib »). Une demande portant une
    # entité bancaire possédée ne peut jamais partir en FAQ.
    intent = _apply_personal_veto(state, intent)

    return {"intent": intent, "llm_parsed": llm_parsed}


def _after_llm_router(state: Agent1State) -> str:
    intent = state.get("intent")
    if intent in ("greeting", "thanks"):
        return "answer_conversational"
    return "route_decision" if intent is not None else "classify_fallback"


def _classify_fallback_node(state: Agent1State) -> dict:
    """Repli de secours UNIQUEMENT : atteint seulement si `llm_router` n'a pas
    résolu l'intention (Mistral désactivé, non configuré, indisponible, en
    timeout, JSON invalide, ou intention "unclear"). Ne revoit jamais
    `virement`/`compte_action` : ces cas ont déjà été écartés par
    `security_guard`, avant tout appel LLM.
    """
    fallback_intent = classify_intent(state["normalized_message"])
    # Même veto que ci-dessus : « chhal 3andi f l7sab » ou « combien jai » ne
    # sont reconnus par aucun motif de `classification.py` et repartaient en
    # FAQ, alors que la composition entité + possession les identifie
    # clairement comme des questions personnelles.
    return {"intent": _apply_personal_veto(state, fallback_intent)}


# Intentions (préservées telles quelles depuis Mistral, ou le bucket
# générique "personal_data" du repli déterministe `classify_fallback`) qui
# exigent toujours une authentification — décidé ici par la couche de
# routage, JAMAIS par Mistral lui-même (voir CLAUDE.md §2 : l'authentification
# requise reste strictement basée sur la session).
#
# `card_query` est volontairement ABSENT de cet ensemble : par défaut une
# question FAQ générale (incident, procédure, ex. "J'ai perdu ma carte",
# "ma carte ne marche pas", "carte bloquée"), sauf si le message demande
# EXPLICITEMENT une information personnelle précise sur la carte (voir
# `_requests_personal_card_info` ci-dessous) — seul ce cas exige une
# authentification.
_AUTH_REQUIRED_INTENTS = {
    "personal_data",
    "balance_query",
    "transactions_query",
    "spending_analysis",
    "beneficiaries_query",
    "salary_query",
    "last_direct_debit_query",
}

# Mots-clés d'une DEMANDE D'INFORMATION précise sur la carte (numéro, statut,
# plafond...) — volontairement étroit et normalisé (accents déjà retirés par
# `classification._normalize`). Ne contient PAS de verbe de panne/incident
# ("marche", "fonctionne", "perdu", "bloque"...) : un signalement d'incident
# ("ma carte ne marche pas", "carte bloquée", "j'ai perdu ma carte") n'est
# PAS une demande de donnée personnelle — c'est une question de procédure,
# répondue par la FAQ publique, jamais par une lecture de banking_db.
_PERSONAL_CARD_INFO_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\bnumero\b",
        r"\binformations?\b",
        r"\bstatut\b",
        r"\bplafond\b",
    )
]


def _requests_personal_card_info(normalized_message: str) -> bool:
    """Distingue une DEMANDE D'INFORMATION personnelle précise sur la carte
    ("quel est le numéro de ma carte", "donne-moi les informations de ma
    carte", "quel est le statut de ma carte") d'un signalement
    d'incident/panne ("j'ai perdu ma carte", "ma carte ne marche pas", "carte
    bloquée") — ce dernier reste une question de FAQ générale (procédure),
    jamais une lecture de donnée personnelle. Déterministe, aucun appel LLM —
    utilisée uniquement par la couche de routage
    (`_route_decision_node`/`_route_edge`), jamais par le Security Guard
    (`classification.detect_sensitive_operation`, inchangé)."""
    normalized = _normalize(normalized_message)
    return any(pattern.search(normalized) for pattern in _PERSONAL_CARD_INFO_PATTERNS)


def _route_decision_node(state: Agent1State) -> dict:
    """Décide si une authentification est requise — uniquement à partir de
    l'intention déjà résolue (préservée telle quelle depuis Mistral) et de la
    session (`is_authenticated`), jamais recalculée à partir d'un texte brut
    ni d'une supposition du LLM. `card_query` est le seul cas nécessitant un
    signal supplémentaire (`_requests_personal_card_info`) pour trancher FAQ
    générale (incident/procédure) vs demande d'information personnelle.
    """
    intent = state["intent"]
    is_authenticated = bool(state.get("session_info", {}).get("is_authenticated", False))

    if intent == "card_query":
        # Une demande de numéro de carte reconnue par le garde déterministe est
        # personnelle par construction : « je veux les 16 chiffres de ma carte »
        # ne contient aucun des mots-clés de `_requests_personal_card_info` et
        # repartait donc en FAQ « perte de carte » au lieu du refus attendu.
        is_personal_card_query = _requests_personal_card_info(
            state["normalized_message"]
        ) or state.get("personal_entity") in (
            personal_entities.CARD_NUMBER,
            personal_entities.CARD_INFORMATION,
        )
        requires_auth = is_personal_card_query and not is_authenticated
        return {"requires_auth": requires_auth, "card_query_is_personal": is_personal_card_query}

    requires_auth = intent in _AUTH_REQUIRED_INTENTS and not is_authenticated
    return {"requires_auth": requires_auth}


_DEBUG_ROUTE_LABELS = {
    "answer_faq": "faq_public",
    "answer_personal_data": "personal_data",
    "require_login": "personal_data",
    "service_unavailable": "service_unavailable",
}


def _route_edge(state: Agent1State) -> str:
    intent = state["intent"]
    if intent in ("virement", "compte_action"):
        route = "service_unavailable"
    elif intent == "card_query":
        if state.get("card_query_is_personal"):
            route = "require_login" if state["requires_auth"] else "answer_personal_data"
        else:
            route = "answer_faq"
    elif intent in _AUTH_REQUIRED_INTENTS:
        route = "require_login" if state["requires_auth"] else "answer_personal_data"
    elif state.get("personal_entity"):
        # Dernier filet du veto : quelle que soit l'intention retenue en amont,
        # une demande portant une entité bancaire possédée ne part JAMAIS vers
        # ChromaDB. `requires_auth` est recalculé ici car `_route_decision_node`
        # a raisonné sur une intention publique.
        is_authenticated = bool(state.get("session_info", {}).get("is_authenticated", False))
        route = "answer_personal_data" if is_authenticated else "require_login"
    else:
        route = "answer_faq"

    # --- LOG TEMPORAIRE (trace complete d'une requete Agent 1 — a retirer) ---
    # Recalcul de classify_intent() ici UNIQUEMENT pour afficher le resultat du
    # Security Guard (deja calcule et deja utilise plus haut dans le graphe,
    # dans _security_guard_node) : ce recalcul est un doublon sans effet de
    # bord, il ne sert qu'a l'affichage et ne remplace ni ne modifie aucune
    # decision de routage deja prise.
    debug_security_guard_result = classify_intent(state["normalized_message"])
    print("[TEMP-DEBUG] ===== Agent 1 - trace requete =====")
    print(f"[TEMP-DEBUG] 1. Message utilisateur original      : {state.get('original_message')!r}")
    print(f"[TEMP-DEBUG] 2. Resultat Security Guard            : {debug_security_guard_result!r}")
    print(f"[TEMP-DEBUG] 3. Sortie JSON Mistral (llm_router)    : {state.get('llm_parsed')!r}")
    print(f"[TEMP-DEBUG] 4. Intent final retenu par Agent 1     : {intent!r}")
    print(f"[TEMP-DEBUG] 5. Route finale                        : {_DEBUG_ROUTE_LABELS[route]!r} (noeud: {route!r})")
    print("[TEMP-DEBUG] =====================================")
    # --- FIN LOG TEMPORAIRE ---

    return route


_FAQ_CANDIDATE_TOP_K = 7


def _merge_faq_candidates(collection: Any, queries: list[str], top_k: int) -> list[dict]:
    """Fusionne les candidats de plusieurs requêtes ChromaDB (dédupliqués par
    question, meilleure distance conservée), triés du plus au moins pertinent.

    Nécessaire car l'embedding "sac de mots haché" (`rag.py`) est trompé par le
    vocabulaire générique partagé entre questions FAQ proches (ex. "Comment
    ouvrir/fermer un compte bancaire ?" ne diffèrent que d'un mot) : une seule
    requête — que ce soit le texte brut ou un sujet reformulé propre par
    Mistral — peut manquer la bonne réponse ou la classer trop bas. Combiner
    le texte normalisé (garde le vocabulaire distinctif de la question
    d'origine) et le sujet Mistral (indispensable pour la darija/l'Arabizi,
    sans recouvrement lexical avec le français) augmente la chance que la
    bonne entrée apparaisse dans le lot soumis au reranking ci-dessous.
    """
    best_by_question: dict[str, dict] = {}
    for query in queries:
        if not query:
            continue
        for candidate in search_faq_candidates(collection, query, top_k=top_k):
            question = candidate.get("question")
            if question is None:
                continue
            existing = best_by_question.get(question)
            if existing is None or (candidate["distance"] or 0) < (existing["distance"] or 0):
                best_by_question[question] = candidate
    return sorted(best_by_question.values(), key=lambda c: c["distance"] if c["distance"] is not None else float("inf"))


def _resolve_faq_collection(state: Agent1State) -> Any:
    """Collection ChromaDB à interroger, ou `None` si elle est inutilisable.

    Un index créé par une version précédente de l'embedding (voir
    `rag.FaqEmbeddingDimensionMismatchError`) ne doit PAS faire échouer la
    requête : la FAQ répond alors `NO_FAQ_MESSAGE`, exactement comme lorsque
    la collection est vide. Les autres chemins de l'Agent 1 (données
    personnelles, refus d'opération sensible, salutations) n'utilisent jamais
    ChromaDB et restent intacts.

    L'erreur est déjà journalisée en amont par
    `app/routers/chat.py::get_faq_collection_dependency` ; ce repli couvre les
    appels directs à `run_agent1` (scripts, tests, outils).
    """
    collection = state.get("collection")
    if collection is not None:
        return collection
    try:
        return get_faq_collection()
    except FaqEmbeddingDimensionMismatchError:
        return None


def _answer_faq_node(state: Agent1State) -> dict:
    collection = _resolve_faq_collection(state)
    language = state.get("detected_language", "fr")
    use_llm_router = state.get("use_llm_router", False)
    original = state["original_message"]
    normalized = state["normalized_message"]

    # --- Récupération : texte normalisé seul, top-1, quand le routeur LLM est
    # désactivé (déterministe, comportement historique STRICTEMENT inchangé).
    # Quand actif : `extract_faq_topic` (Mistral, couche DÉDIÉE à la FAQ —
    # jamais banking_db/auth.db, jamais la garde de sécurité de
    # classification.py) produit un sujet reformulé, utile pour les fautes de
    # frappe et la darija mal normalisée ; les candidats du texte normalisé ET
    # du sujet sont fusionnés (voir `_merge_faq_candidates`) plutôt que de
    # choisir l'un ou l'autre — aucun des deux seul ne suffit toujours sur cet
    # embedding. Échec de `extract_faq_topic` -> repli garanti sur `normalized`
    # seul, exactement comme avant.
    if collection is None:
        # Index vectoriel inutilisable : aucun candidat, on retombe sur le
        # message "aucune réponse trouvée" ci-dessous plutôt que de planter.
        candidates = []
    elif not use_llm_router:
        top_match = search_faq(collection, normalized)
        candidates = [top_match] if top_match else []
    else:
        topic = llm_router.extract_faq_topic(original, normalized, language)
        candidates = _merge_faq_candidates(collection, [normalized, topic], top_k=_FAQ_CANDIDATE_TOP_K)

    if not candidates:
        response = NO_FAQ_MESSAGE if language == "fr" else response_localizer.localize_no_faq_answer(language)
        session_id = state.get("session_id")
        if session_id:
            conversation_memory.record_turn(session_id, original, response)
        return {"response": response}

    # --- Reranking (uniquement si plusieurs candidats et routeur actif) :
    # Mistral ne CHOISIT qu'un index parmi des candidats déjà récupérés de
    # ChromaDB (voir llm_router.rerank_faq_candidates) — il ne rédige jamais
    # de réponse, jamais de contenu absent des documents FAQ existants.
    # Échec/incertain -> repli sur le premier candidat (déjà trié par
    # distance ChromaDB), comportement historique.
    chosen = candidates[0]
    if use_llm_router and len(candidates) > 1:
        best_index = llm_router.rerank_faq_candidates(original, candidates)
        if best_index is not None:
            chosen = candidates[best_index]

    if language == "fr":
        response = chosen["answer"]
    else:
        # La réponse FAQ française récupérée n'est jamais modifiée (montants,
        # dates, conditions bancaires) - uniquement encadrée d'une courte
        # phrase d'introduction en darija (response_localizer.localize_faq_answer).
        response = response_localizer.localize_faq_answer(chosen["answer"], language)

    session_id = state.get("session_id")
    if session_id:
        conversation_memory.record_turn(session_id, original, response)
    return {"response": response}


def _require_login_node(state: Agent1State) -> dict:
    language = state.get("detected_language", "fr")
    if language == "fr":
        return {"response": REQUIRE_LOGIN_MESSAGE}
    return {"response": response_localizer.localize_require_login(language)}


def _service_unavailable_node(state: Agent1State) -> dict:
    language = state.get("detected_language", "fr")
    if language == "fr":
        return {"response": SERVICE_UNAVAILABLE_MESSAGE}
    return {"response": response_localizer.localize_service_unavailable(language)}


def _answer_personal_data_node(state: Agent1State) -> dict:
    user_id = state.get("session_info", {}).get("user_id")
    language = state.get("detected_language", "fr")
    # Sur une entité au signal exact (rib/iban, numéro de carte), la sortie de
    # Mistral est volontairement ignorée pour le CHOIX DE L'OUTIL : la laisser
    # décider rejouerait le bug n°2 (`balance_query` sur « mon rib » renvoyant
    # le solde). La sous-intention est alors tranchée par
    # `classify_personal_intent`, purement déterministe.
    llm_parsed = state.get("llm_parsed")
    if state.get("personal_entity") in _PRECISE_VETO_ENTITIES:
        llm_parsed = None

    answer = build_personal_data_answer(
        state["normalized_message"],
        user_id,
        banking_db_path=state.get("banking_db_path"),
        language=language,
        llm_parsed=llm_parsed,
    )
    session_id = state.get("session_id")
    if session_id:
        conversation_memory.record_turn(session_id, state["original_message"], answer)
    return {"response": answer}


def build_agent1_graph():
    graph = StateGraph(Agent1State)
    graph.add_node("security_guard", _security_guard_node)
    graph.add_node("personal_entity_guard", _personal_entity_guard_node)
    graph.add_node("conversational_understanding", _conversational_understanding_node)
    graph.add_node("answer_conversational", _answer_conversational_node)
    graph.add_node("llm_router", _llm_router_node)
    graph.add_node("classify_fallback", _classify_fallback_node)
    graph.add_node("route_decision", _route_decision_node)
    graph.add_node("answer_faq", _answer_faq_node)
    graph.add_node("require_login", _require_login_node)
    graph.add_node("answer_personal_data", _answer_personal_data_node)
    graph.add_node("service_unavailable", _service_unavailable_node)

    graph.add_edge(START, "security_guard")
    graph.add_conditional_edges(
        "security_guard",
        _after_security_guard,
        {"route_decision": "route_decision", "personal_entity_guard": "personal_entity_guard"},
    )
    graph.add_conditional_edges(
        "personal_entity_guard",
        _after_personal_entity_guard,
        {"route_decision": "route_decision", "conversational_understanding": "conversational_understanding"},
    )
    graph.add_conditional_edges(
        "conversational_understanding",
        _after_conversational_understanding,
        {"answer_conversational": "answer_conversational", "llm_router": "llm_router"},
    )
    graph.add_conditional_edges(
        "llm_router",
        _after_llm_router,
        {
            "route_decision": "route_decision",
            "classify_fallback": "classify_fallback",
            "answer_conversational": "answer_conversational",
        },
    )
    graph.add_edge("classify_fallback", "route_decision")
    graph.add_conditional_edges(
        "route_decision",
        _route_edge,
        {
            "answer_faq": "answer_faq",
            "require_login": "require_login",
            "answer_personal_data": "answer_personal_data",
            "service_unavailable": "service_unavailable",
        },
    )
    graph.add_edge("answer_conversational", END)
    graph.add_edge("answer_faq", END)
    graph.add_edge("require_login", END)
    graph.add_edge("answer_personal_data", END)
    graph.add_edge("service_unavailable", END)
    return graph.compile()


_COMPILED_GRAPH = None


def _get_compiled_graph():
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = build_agent1_graph()
    return _COMPILED_GRAPH


def run_agent1(
    message: str,
    is_authenticated: bool = False,
    user_id: Optional[str] = None,
    collection: Any = None,
    banking_db_path: Optional[str] = None,
    session_id: Optional[str] = None,
    use_llm_router: bool = False,
) -> dict:
    """Point d'entrée synchrone de l'Agent 1.

    `collection` (ChromaDB) et `banking_db_path` permettent d'injecter des
    bases isolées (tests, API) ; par défaut, les bases persistantes
    configurées par variables d'environnement sont utilisées. `user_id` doit
    provenir exclusivement de la session validée côté serveur — jamais du
    texte du message — c'est la seule garantie d'isolation entre utilisateurs.
    La langue (français, darija arabe, darija latine) est détectée
    automatiquement à partir de `message` — aucun paramètre supplémentaire
    n'est nécessaire côté appelant.

    `session_id` (optionnel) sert uniquement de clé pour le contexte
    conversationnel court terme (`conversation_memory.py`) — jamais pour
    l'autorisation, qui reste décidée par `is_authenticated`/`user_id`.

    `use_llm_router` (défaut `False`, repli garanti) : active la tentative
    d'extraction d'intention via le LLM Router (`llm_router.py`) en plus de la
    classification déterministe existante, qui reste dans tous les cas le
    chemin de repli automatique (voir `llm_router.route_with_llm`, qui ne
    lève jamais et retourne `None` sur tout échec). Laissé à `False` par
    défaut afin que tout appelant existant conserve un comportement strictement
    identique sans configuration supplémentaire.
    """
    graph = _get_compiled_graph()
    initial_state: Agent1State = {
        "message": message,
        "session_info": {"is_authenticated": is_authenticated, "user_id": user_id},
        "session_id": session_id,
        "use_llm_router": use_llm_router,
        "collection": collection,
        "banking_db_path": banking_db_path,
    }
    result = graph.invoke(initial_state)
    return {
        "intent": result["intent"],
        "requires_auth": result["requires_auth"],
        "response": result["response"],
    }
