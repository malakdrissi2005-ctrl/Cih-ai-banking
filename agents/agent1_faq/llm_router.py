"""LLM Router — couche d'extraction d'intention et de paramètres, placée
*avant* la logique de classification existante (voir `CLAUDE.md`, section
ajoutée pour cette évolution de l'Agent 1).

Nouveau flux :
    Utilisateur -> Détection langue -> LLM Router -> Extraction intention
    + paramètres -> Agent 1 existant (classification déterministe, tools) ->
    Tool approprié -> Réponse utilisateur.

Garanties de sécurité strictes (non négociables) :
- Ce module n'importe **jamais** `app.banking.banking_db` ni `auth.db` : il ne
  reçoit et ne retourne que du texte et un JSON structuré d'intention.
- Le LLM ne produit **jamais** de montant, de solde, de date, de numéro de
  compte ou tout autre contenu bancaire réel : la sortie est validée
  strictement contre un vocabulaire fixe (`_VALID_INTENTS`) et un petit
  ensemble de catégories/périodes autorisées (`_VALID_CATEGORIES`,
  `_VALID_PERIODS`) ; toute valeur hors de cet ensemble est ignorée, jamais
  propagée telle quelle. Un champ suspect (ex. `user_id`, `amount`, `solde`,
  `balance`, `montant`) dans la sortie du LLM invalide la réponse entière.
- Ce module ne décide **jamais** de l'authentification requise : le routage
  d'authentification (`route_decision`/`_route_edge` dans `graph.py`) reste
  strictement déterministe et n'est jamais recalculé à partir de la sortie de
  ce module (voir `graph.py` : le LLM n'affine l'intention **qu'à l'intérieur**
  du bucket déjà décidé par `classification.classify_intent`, jamais pour
  décider si un bucket est "personal_data"/"virement"/"compte_action").
- En cas d'échec (modèle indisponible, timeout, JSON invalide, intention
  inconnue, champ suspect) : retourne toujours `None`. L'appelant (`graph.py`)
  retombe alors intégralement sur la classification déterministe existante
  (`classification.classify_intent`, `banking_answers.classify_personal_intent`)
  — repli garanti, jamais une erreur technique visible par l'utilisateur.

Note de performance (mesures reproduites sur cet environnement, voir
`backend/tests/test_ollama_integration.py`) : le coût dominant n'est **pas**
la génération elle-même (~3,5 à 4 s pour une réponse JSON courte une fois le
modèle chargé), mais le **chargement du modèle depuis le disque en RAM**
lorsqu'Ollama l'a déchargé après une période d'inactivité (~45 à 53 s mesurés
ici, modèle `mistral` Q4_K_M ~4,3 Go, CPU uniquement). Deux mitigations :

1. `keep_alive` est envoyé à chaque appel (`OLLAMA_KEEP_ALIVE`, défaut `30m`)
   pour garder le modèle chargé en RAM entre deux messages d'une même
   conversation/démonstration, au lieu de la valeur par défaut d'Ollama
   (5 minutes).
2. `warm_up()` (ci-dessous) est appelée en tâche de fond, une fois, au
   démarrage du backend (voir `backend/app/main.py`) pour forcer ce
   chargement *avant* le premier message d'un utilisateur réel, plutôt que de
   le lui faire subir en pleine conversation.

`_DEFAULT_TIMEOUT_SECONDS` reste volontairement strict (le repli déterministe
reste la garantie en toutes circonstances, y compris un chargement à froid
que ces mitigations n'auraient pas anticipé) mais est calibré pour couvrir
confortablement un appel à chaud (~6,5 à 7 s mesurés en aller-retour complet),
pas un chargement à froid.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import httpx

_DEFAULT_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_ROUTER_TIMEOUT_SECONDS", "10"))

# Vocabulaire fixe d'intentions que le LLM est autorisé à produire. Toute
# valeur hors de cet ensemble est rejetée (retour `None`).
#
# "greeting"/"thanks" : cas conversationnels (salutation, remerciement) déjà
# interceptés en amont par une couche 100% déterministe (`conversational.py`,
# évaluée avant tout appel Mistral pour la latence) — inclus ici en défense en
# profondeur, pour qu'une variante non couverte par le filtre déterministe
# (faute de frappe, tournure inhabituelle) soit malgré tout reconnue par
# Mistral plutôt que de tomber dans "faq_search"/"unclear".
_VALID_INTENTS = {
    "faq_search",
    "balance_query",
    "transactions_query",
    "card_query",
    "beneficiaries_query",
    "spending_analysis",
    "salary_query",
    "last_direct_debit_query",
    "unclear",
    "greeting",
    "thanks",
}

# Catégories/périodes/champs carte autorisés — mêmes valeurs canoniques que
# `banking_answers._CATEGORY_GROUPS` / `_PERIOD_LABELS` / `_CARD_FIELD_ORDER`.
# Toute valeur hors de cette liste est silencieusement ignorée (jamais
# propagée telle quelle) : le LLM ne peut jamais injecter une catégorie ou un
# champ inventés dans la suite du pipeline.
_VALID_CATEGORIES = {
    "Restaurants", "Transport", "Courses", "Carburant", "Assurance", "Abonnement", "Logement", "Retrait",
}
_VALID_PERIODS = {"current_month", "last_month"}
_VALID_CARD_FIELDS = {"status", "payment_limit", "withdrawal_limit", "ecommerce_enabled", "international_enabled"}

# Champs qui ne doivent **jamais** apparaître dans une sortie LLM légitime :
# leur seule présence indique soit une tentative d'injection, soit un modèle
# qui a halluciné une donnée bancaire réelle — dans les deux cas, on rejette
# la réponse entière plutôt que de tenter un filtrage partiel.
_FORBIDDEN_KEYS = {
    "user_id", "customer_id", "amount", "montant", "solde", "balance",
    "date", "account_number", "card_number", "otp", "password", "token",
}

_SYSTEM_PROMPT = """Tu es un routeur d'intention pour un assistant bancaire. Tu ne réponds JAMAIS \
directement à l'utilisateur et tu n'inventes JAMAIS de donnée bancaire (montant, solde, date, numéro). \
Ton unique rôle est de produire un objet JSON qui identifie l'intention de la question et, si pertinent, \
une catégorie/période/liste de champs parmi des valeurs fixes.

Principe général : base-toi sur le SENS de la question, jamais sur une correspondance de mots exacts. \
La question peut être en français, en darija marocaine (alphabet arabe ou Arabizi), contenir des fautes \
de frappe, ou une formulation que tu n'as jamais rencontrée. Les exemples ci-dessous illustrent des \
CATÉGORIES de formulation, pas une liste exhaustive à mémoriser : applique le même principe à toute \
variante équivalente, dans n'importe quelle langue ou tournure — ne te limite jamais à une \
correspondance littérale avec ces exemples.

Intentions valides (choisis-en une seule) :
- faq_search : question générale publique (procédures, conditions, ouverture de compte...) OU tout \
signalement de problème concernant le COMPTE, l'ACCÈS ou la SÉCURITÉ (bloqué, verrouillé, suspendu, \
inaccessible, fraude, piraté, transaction non reconnue...). Un signalement de problème est TOUJOURS une \
question de procédure, jamais une consultation de donnée personnelle réelle — sauf si l'utilisateur \
demande EN PLUS une information précise déjà couverte par un autre intent ci-dessous (ex. solde, liste \
de transactions).
- balance_query : l'utilisateur veut SAVOIR combien il a / le solde de son compte, OU demande une \
information générale sur le compte (type, numéro, solde) sans préciser d'élément plus spécifique \
(transactions, carte, bénéficiaires, salaire, prélèvement, dépenses). Différence avec faq_search : ici \
l'utilisateur s'informe, il ne signale pas un problème.
- card_query : toute question OU signalement concernant la carte (statut, plafonds, paiement en ligne/\
international, perdue, volée, bloquée, ne fonctionne plus) — informative ou incident, c'est toujours \
card_query ; la distinction FAQ publique / donnée personnelle est déjà gérée en aval, tu n'as pas à la \
faire ici.
- transactions_query : dernières opérations / historique.
- beneficiaries_query : bénéficiaires enregistrés.
- spending_analysis : dépenses par catégorie ou analyse de dépenses.
- salary_query : salaire reçu.
- last_direct_debit_query : dernier prélèvement.
- greeting : simple salutation, sans question (bonjour, salam, hi, slm...).
- thanks : simple remerciement, sans question (merci, chokran, thanks...).
- unclear : question personnelle reconnue mais qui ne correspond à aucune intention ci-dessus \
(ex. conseil financier, "est-ce que ça suffit pour...").

Catégories valides (uniquement pour spending_analysis, optionnel) : Restaurants, Transport, Courses, \
Carburant, Assurance, Abonnement, Logement, Retrait.
Périodes valides (optionnel) : current_month, last_month.
Champs carte valides (uniquement pour card_query, optionnel, liste) : status, payment_limit, \
withdrawal_limit, ecommerce_enabled, international_enabled.

Exemples illustratifs (une formulation différente relevant de la même catégorie, dans une autre langue \
ou avec des fautes de frappe, doit être traitée de la même façon) :
- "شحال عندي فالحساب؟" / "ch7al 3ndi fl compte" (Arabizi) / "kel est mon sold" (faute de frappe) / \
"Donne-moi les informations sur mon compte" (générique, sans élément précis) -> {"intent": "balance_query"}
- "Mon compte est bloqué" / "Je n'arrive plus à accéder à mon compte" / "J'ai détecté une fraude sur mon \
compte" / "Mon compte a été piraté" -> {"intent": "faq_search", "faq_query": "<reformulation neutre du \
problème signalé>"}
- "Comment ouvrir un compte ?" / "bghit n7ell compte" (Arabizi) -> {"intent": "faq_search", "faq_query": "Comment ouvrir un compte bancaire"}
- "J'ai perdu ma carte" / "khsart carte dyali" (Arabizi) / "خسرت الكارط ديالي" (arabe) -> {"intent": "card_query"}
- "شكون هوما البنيفيسيار ديالي" (arabe, "qui sont mes bénéficiaires") -> {"intent": "beneficiaries_query"}
- "slm" / "salam alaykoum" / "hi" -> {"intent": "greeting"}
- "merci" / "chokran" -> {"intent": "thanks"}

Réponds UNIQUEMENT avec un objet JSON de la forme :
{"intent": "...", "category": null, "period": null, "card_fields": [], "faq_query": null}

"faq_query" : uniquement si intent="faq_search" — une reformulation courte et neutre de la question en \
français, sans jamais ajouter d'information qui n'était pas dans la question originale.
N'inclus JAMAIS de champ "user_id", "montant", "solde", "date" ou toute autre donnée bancaire réelle : \
tu n'as accès à aucune donnée bancaire et ne dois jamais en fabriquer."""


def is_llm_configured() -> bool:
    """Vérifie que la configuration minimale (URL + modèle Ollama) est présente.

    Ne garantit **pas** que le service est réellement joignable ni rapide —
    seule une tentative d'appel (`route_with_llm`) peut le déterminer, avec
    repli automatique sur `None` en cas d'échec.
    """
    return bool(os.getenv("OLLAMA_BASE_URL")) and bool(os.getenv("OLLAMA_MODEL"))


def is_router_enabled() -> bool:
    """Interrupteur opérateur (`LLM_ROUTER_ENABLED`, défaut `"true"`).

    Indépendant de `is_llm_configured()` : ce dernier vérifie que l'URL/modèle
    Ollama sont renseignés, celui-ci permet à un opérateur de couper la
    tentative LLM entièrement (ex. pour ne conserver que le comportement
    déterministe) sans retirer la configuration Ollama. Source unique de cette
    bascule — utilisée par la dépendance FastAPI de `backend/app/routers/chat.py`
    et par le réchauffement au démarrage (`backend/app/main.py`)."""
    return os.getenv("LLM_ROUTER_ENABLED", "true").strip().lower() != "false"


def _build_prompt(message: str, normalized_message: str, conversation_history: Optional[list[tuple[str, str]]]) -> str:
    history_block = ""
    if conversation_history:
        # Contexte conversationnel simple (voir conversation_memory.py) — jamais
        # une mémoire permanente, seulement les derniers échanges de la session
        # en cours, pour désambiguïser des questions de suivi ("et mes dépenses
        # du mois ?" après "quel est mon solde ?").
        lines = [f"Utilisateur: {question}\nAssistant: {answer}" for question, answer in conversation_history]
        history_block = "Échanges précédents de cette conversation :\n" + "\n".join(lines) + "\n\n"

    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"{history_block}"
        f"Question de l'utilisateur (texte original) : {message}\n"
        f"Question normalisée (référence) : {normalized_message}\n\n"
        "Objet JSON :"
    )


def _validate_and_normalize(raw: dict) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None

    if _FORBIDDEN_KEYS & set(raw.keys()):
        return None

    intent = raw.get("intent")
    if not isinstance(intent, str) or intent not in _VALID_INTENTS:
        return None

    category = raw.get("category")
    if category not in _VALID_CATEGORIES:
        category = None

    period = raw.get("period")
    if period not in _VALID_PERIODS:
        period = None

    card_fields_raw = raw.get("card_fields")
    card_fields: list[str] = []
    if isinstance(card_fields_raw, list):
        card_fields = [field for field in card_fields_raw if field in _VALID_CARD_FIELDS]

    faq_query = raw.get("faq_query")
    if not isinstance(faq_query, str) or not faq_query.strip():
        faq_query = None
    else:
        faq_query = faq_query.strip()[:300]

    return {
        "intent": intent,
        "category": category,
        "period": period,
        "card_fields": card_fields,
        "faq_query": faq_query,
    }


def route_with_llm(
    message: str,
    normalized_message: str,
    language: str,
    conversation_history: Optional[list[tuple[str, str]]] = None,
    timeout: Optional[float] = None,
) -> Optional[dict]:
    """Tente d'extraire `{intent, category, period, card_fields, faq_query}` via Ollama.

    Retourne `None` sur **tout** échec (service indisponible, timeout, JSON
    invalide, intention inconnue, champ suspect) — l'appelant retombe alors
    intégralement sur la classification déterministe existante. Ne lève
    jamais d'exception vers l'appelant.
    """
    if not is_llm_configured():
        return None

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "mistral")
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
    resolved_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT_SECONDS

    prompt = _build_prompt(message, normalized_message, conversation_history)

    try:
        response = httpx.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "keep_alive": keep_alive,
            },
            timeout=resolved_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        raw_output = json.loads(payload["response"])
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
        return None

    return _validate_and_normalize(raw_output)


# ---------------------------------------------------------------------------
# FAQ/RAG : extraction de sujet + reranking — fonctions DÉDIÉES, séparées de
# `route_with_llm` ci-dessus (routage d'intention personnel/FAQ, déjà vérifié)
# pour ne jamais risquer d'y introduire une régression. N'sont appelées que
# par `graph.py::_answer_faq_node`, une fois le bucket "faq_generale" déjà
# tranché par la garde déterministe de `_classify_intent_node` — jamais avant.
# Comme `route_with_llm` : ne reçoivent et ne produisent jamais de donnée
# bancaire, ne rédigent jamais de réponse elles-mêmes, retournent toujours
# `None` sur tout échec (repli garanti sur le comportement déterministe
# existant, jamais d'exception visible par l'appelant).
# ---------------------------------------------------------------------------

_FAQ_TOPIC_SYSTEM_PROMPT = """Tu es un assistant qui reformule une question bancaire publique en un \
sujet de recherche clair et neutre, en français standard, pour interroger une base de FAQ.

Règles strictes :
- Traite les fautes de frappe, la darija marocaine (alphabet arabe ou Arabizi) et les formulations \
maladroites comme des variantes équivalentes du français standard — ne te limite jamais à une \
correspondance de mots exacts.
- Ne réponds JAMAIS à la question toi-même, n'ajoute jamais d'information absente de la question \
originale, n'invente jamais de procédure ni de donnée bancaire.
- Produis uniquement une courte reformulation neutre en français (5 à 10 mots).

Réponds UNIQUEMENT avec un objet JSON de la forme : {"topic": "..."}

Exemples :
- "je te dits comment je peux ouvre un comrt" -> {"topic": "Comment ouvrir un compte bancaire"}
- "bghit n7ell compte" -> {"topic": "Comment ouvrir un compte bancaire"}
- "chno khasni bach n7ell compte" -> {"topic": "Quels documents pour ouvrir un compte"}
- "ma carte a expiré, koi dois je faire" -> {"topic": "Renouvellement d'une carte bancaire expirée"}"""


def extract_faq_topic(
    message: str,
    normalized_message: str,
    language: str,
    timeout: Optional[float] = None,
) -> Optional[str]:
    """Extrait, via Mistral, un sujet de recherche FAQ neutre en français —
    utilisé comme requête de recherche ChromaDB (`rag.search_faq_candidates`)
    à la place du texte normalisé déterministe, plus robuste aux fautes de
    frappe et à la darija mal normalisée par `darija_normalization.py`.

    Retourne toujours `None` en cas d'échec (non configuré, timeout, JSON
    invalide, champ suspect, sujet vide) : l'appelant retombe alors sur
    `normalized_message` — repli déterministe garanti, inchangé.
    """
    if not is_llm_configured():
        return None

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "mistral")
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
    resolved_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT_SECONDS

    prompt = (
        f"{_FAQ_TOPIC_SYSTEM_PROMPT}\n\n"
        f"Question de l'utilisateur (texte original) : {message}\n"
        f"Question normalisée (référence) : {normalized_message}\n\n"
        "Objet JSON :"
    )

    try:
        response = httpx.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "keep_alive": keep_alive,
            },
            timeout=resolved_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        raw_output = json.loads(payload["response"])
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(raw_output, dict) or (_FORBIDDEN_KEYS & set(raw_output.keys())):
        return None
    topic = raw_output.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        return None
    return topic.strip()[:200]


_FAQ_RERANK_SYSTEM_PROMPT = """Tu reçois une question d'utilisateur et une liste numérotée de questions \
candidates issues d'une FAQ bancaire publique.

Ta seule tâche : choisir l'index de la question candidate qui répond le mieux à la question de \
l'utilisateur, ou null si aucune candidate ne correspond raisonnablement.

Les candidates sont déjà triées de la plus probable (index 0) à la moins probable, selon une
recherche documentaire — en cas de doute entre deux candidates proches, préfère l'index le plus
petit (le mieux classé par la recherche).

Règles strictes :
- Tu ne rédiges JAMAIS de réponse toi-même.
- Tu ne modifies JAMAIS le texte des candidates.
- Tu ne peux choisir qu'un index parmi ceux fournis ci-dessous, ou null.
- Ne choisis JAMAIS une candidate évoquant une fraude, une opération suspecte ou un piratage si la \
question de l'utilisateur ne mentionne EXPLICITEMENT aucun de ces termes — même si elle mentionne un \
blocage, un problème d'accès ou de connexion. Un compte bloqué/verrouillé n'est pas, par défaut, une \
fraude : préfère toujours la candidate qui parle de blocage/accès dans ce cas.

Réponds UNIQUEMENT avec un objet JSON de la forme : {"best_match_index": <entier ou null>}

Exemples :
Question de l'utilisateur : je veux ouvre un comrt
Candidates :
0: Quels documents sont nécessaires pour ouvrir un compte ?
1: Comment fermer un compte bancaire ?
2: Comment fonctionne un virement bancaire ?
Objet JSON : {"best_match_index": 0}

Question de l'utilisateur : Mon compte est bloqué
Candidates :
0: Que faire si mon compte client est temporairement bloqué après plusieurs tentatives ?
1: Mon compte est bloqué, mon compte est verrouillé, ou mon accès est bloqué : que faire si je n'arrive plus à accéder à mon compte ou à mon espace client ?
2: Que faire si je soupçonne une fraude sur mon compte ?
Objet JSON : {"best_match_index": 0}

Question de l'utilisateur : J'ai détecté une fraude sur mon compte
Candidates :
0: Que faire si mon compte semble bloqué ou verrouillé ?
1: Que faire si je soupçonne une fraude sur mon compte ?
Objet JSON : {"best_match_index": 1}"""


def rerank_faq_candidates(
    user_question: str,
    candidates: list[dict],
    timeout: Optional[float] = None,
) -> Optional[int]:
    """Demande à Mistral de choisir, parmi `candidates` (liste de dicts avec
    au moins une clé "question"), l'index du plus pertinent pour `user_question`.

    Ne reçoit et ne produit jamais que des index dans les bornes fournies —
    jamais de texte libre, jamais une réponse générée par le modèle : la
    réponse finale vient toujours du champ "answer" du candidat choisi,
    jamais de Mistral lui-même. Retourne toujours `None` sur tout échec ou
    sortie hors bornes/invalide : l'appelant retombe alors sur le premier
    candidat (déjà trié par distance ChromaDB — comportement historique).
    """
    if not is_llm_configured() or not candidates:
        return None

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "mistral")
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
    resolved_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT_SECONDS

    numbered = "\n".join(f"{index}: {candidate.get('question', '')}" for index, candidate in enumerate(candidates))
    prompt = (
        f"{_FAQ_RERANK_SYSTEM_PROMPT}\n\n"
        f"Question de l'utilisateur : {user_question}\n\n"
        f"Candidates :\n{numbered}\n\n"
        "Objet JSON :"
    )

    try:
        response = httpx.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "keep_alive": keep_alive,
            },
            timeout=resolved_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        raw_output = json.loads(payload["response"])
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(raw_output, dict):
        return None
    index = raw_output.get("best_match_index")
    if index is None or isinstance(index, bool) or not isinstance(index, int):
        return None
    if not (0 <= index < len(candidates)):
        return None
    return index


def warm_up(timeout: float = 60.0) -> bool:
    """Force le chargement du modèle Ollama en RAM, sans attendre un vrai message.

    À appeler une fois en tâche de fond au démarrage du backend (voir
    `backend/app/main.py`), jamais dans le chemin d'une requête utilisateur :
    le chargement à froid mesuré sur cet environnement (~45-53 s) rendrait
    toute première requête de démonstration inutilisable si elle attendait ce
    résultat. `timeout` est donc généreux ici (contrairement à
    `_DEFAULT_TIMEOUT_SECONDS`, dimensionné pour un appel à chaud) : un
    dépassement ne bloque jamais l'appelant, il est lancé dans un thread séparé.

    `options.num_predict=1` limite la génération à un seul jeton — seul le
    chargement du modèle en mémoire nous intéresse ici, jamais la qualité de
    la sortie. Ne lève jamais d'exception : retourne `False` sur tout échec
    (service indisponible, timeout, configuration absente), exactement comme
    `route_with_llm`."""
    if not is_llm_configured():
        return False

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "mistral")
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

    try:
        response = httpx.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": "ok",
                "stream": False,
                "keep_alive": keep_alive,
                "options": {"num_predict": 1},
            },
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True


# ---------------------------------------------------------------------------
# Correspondance entre le vocabulaire du LLM Router et le vocabulaire interne
# déjà utilisé par `banking_answers.classify_personal_intent` — un seul
# endroit traduit les deux, pour ne jamais dupliquer/diverger la logique.
# ---------------------------------------------------------------------------
_INTENT_TO_PERSONAL_INTENT = {
    "balance_query": "total_balance",
    "transactions_query": "recent_transactions",
    "beneficiaries_query": "beneficiaries",
    "salary_query": "salary",
    "last_direct_debit_query": "last_direct_debit",
    "unclear": "assistant_explain",
}


def to_personal_intent(llm_parsed: dict) -> Optional[dict]:
    """Convertit une sortie validée de `route_with_llm` vers le format attendu
    par `banking_answers.build_personal_data_answer` (même forme que
    `classify_personal_intent`). Retourne `None` si l'intention ne correspond
    à aucun outil personnel connu (ex. "faq_search", géré séparément par le
    nœud FAQ) — l'appelant retombe alors sur la classification déterministe.
    """
    intent = llm_parsed.get("intent")

    if intent == "card_query":
        return {"intent": "card_information", "requested_fields": llm_parsed.get("card_fields") or ["status"]}
    if intent == "spending_analysis":
        return {
            "intent": "spending_by_category",
            "category": llm_parsed.get("category"),
            "period": llm_parsed.get("period") or "current_month",
        }
    mapped = _INTENT_TO_PERSONAL_INTENT.get(intent)
    if mapped is None:
        return None
    return {"intent": mapped}
