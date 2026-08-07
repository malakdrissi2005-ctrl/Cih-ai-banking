"""Couche de compréhension conversationnelle TOP-LEVEL (Mistral local via
Ollama) : décide le DOMAINE d'un message ("banking" vs "general") — AVANT
tout routage vers le Banking Agent (`agents/agent1_faq/`, jamais modifié par
ce module) ou le General Agent (`agents/general_agent/`).

Strictement séparée de la classification interne de l'Agent 1
(`agents/agent1_faq/llm_router.py`, `agents/agent1_faq/conversational.py`) :
celle-ci reste 100 % inchangée et continue son propre travail de
classification fine (FAQ/personal_data/greeting/...) UNE FOIS le domaine
"banking" déjà tranché ici. Ce module ne classe JAMAIS une intention
bancaire précise (virement, solde, carte...) — uniquement banking vs general.
Duplique volontairement une petite portion du code d'appel Ollama de
`llm_router.py` plutôt que de l'importer : ce module doit rester
complètement autonome du Banking Agent (voir contrainte "Existing Banking
Agent... MUST NOT be modified").

Même philosophie de repli que le reste du projet : Mistral n'est jamais un
point de défaillance unique. En cas d'échec/désactivation/JSON invalide,
repli déterministe garanti sur `domain="banking"` — délègue au Banking
Agent, dont la propre chaîne de repli interne (garde de sécurité +
classification déterministe) reste entièrement fonctionnelle même sans LLM.
Ce choix protège contre une mauvaise classification qui enverrait une vraie
question bancaire vers le General Agent (qui n'a de toute façon aucun accès
à `banking_db`) plutôt que l'inverse.

Sortie : `{"domain": "banking"|"general", "intent": str, "needs_web": False}`.
`needs_web` est TOUJOURS forcé à `False` ici, quelle que soit la sortie du
LLM — architecture préparée pour une future recherche web, non implémentée
(voir énoncé : "Only prepare the architecture for future web search").
"""
from __future__ import annotations

import difflib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Optional

import httpx

_DEFAULT_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_ROUTER_TIMEOUT_SECONDS", "10"))

_VALID_DOMAINS = {"banking", "general"}

# ---------------------------------------------------------------------------
# Garde deterministe pre-LLM : reduit le risque qu'une vraie question
# bancaire soit envoyee par erreur vers le General Agent (Gemini) si Mistral
# se trompe. S'appuie sur `data/banking_keywords.json` (mainteni manuellement,
# jamais modifie par ce module) - fichier absent/invalide => guard inactif
# (listes vides), jamais un crash ni un blocage du demarrage du backend.
# Meme philosophie de repli que le reste du projet : ce garde ne fait
# qu'ELARGIR les cas resolus en "banking" avant tout appel LLM, il ne change
# jamais le comportement existant pour un message qu'il ne reconnait pas.
# ---------------------------------------------------------------------------

# Racine du depot (agents/router/conversational_understanding.py ->
# agents/router -> agents -> racine) - meme convention que
# `agents/agent1_faq/rag.py::_REPO_ROOT`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BANKING_KEYWORDS_PATH = _REPO_ROOT / "data" / "banking_keywords.json"


def _normalize_for_banking_check(text: str) -> str:
    """Minuscule, sans accents - meme principe que
    `agents.agent1_faq.classification._normalize`."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _load_banking_keywords() -> dict:
    """Charge `data/banking_keywords.json` et aplatit toutes les categories
    de chaque langue en une seule liste de mots/expressions par langue.

    Ne leve JAMAIS d'exception : fichier absent ou JSON invalide => listes
    vides pour les trois langues - le garde (`_looks_like_banking`) se
    comporte alors comme s'il etait desactive, sans jamais bloquer le
    demarrage du backend."""
    empty = {"fr": [], "darija_latn": [], "darija_ar": []}
    try:
        with open(_BANKING_KEYWORDS_PATH, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return empty

    flattened: dict = {}
    for language in ("fr", "darija_latn", "darija_ar"):
        categories = raw.get(language) if isinstance(raw, dict) else None
        words: list[str] = []
        if isinstance(categories, dict):
            for category_words in categories.values():
                if isinstance(category_words, list):
                    words.extend(word for word in category_words if isinstance(word, str))
        flattened[language] = words
    return flattened


# Charge une seule fois au niveau module - jamais relu a chaque appel.
_BANKING_KEYWORDS = _load_banking_keywords()

# Vocabulaire latin (FR + darija_latn) normalise, pour un matching de phrase
# exacte (regex) ET pour la tolerance aux fautes de frappe (mots isoles).
_LATIN_KEYWORDS_NORMALIZED = sorted(
    {
        _normalize_for_banking_check(word)
        for word in _BANKING_KEYWORDS["fr"] + _BANKING_KEYWORDS["darija_latn"]
        if word.strip()
    },
    key=len,
    reverse=True,
)
_LATIN_KEYWORD_PATTERN = (
    re.compile(r"\b(" + "|".join(re.escape(word) for word in _LATIN_KEYWORDS_NORMALIZED) + r")\b")
    if _LATIN_KEYWORDS_NORMALIZED
    else None
)
_FUZZY_VOCAB = {token for phrase in _LATIN_KEYWORDS_NORMALIZED for token in phrase.split() if token}


def _looks_like_banking(message: str) -> bool:
    """Garde deterministe : True si `message` contient un mot/expression
    reconnu de `data/banking_keywords.json` - correspondance exacte darija
    arabe (mot brut), correspondance exacte FR/darija_latn (normalisee), ou
    correspondance approximative tolerante aux fautes de frappe. Ne leve
    JAMAIS d'exception : un probleme ici ne doit jamais empecher
    `classify_domain` de repondre."""
    try:
        if not message:
            return False

        if any(word in message for word in _BANKING_KEYWORDS["darija_ar"]):
            return True

        normalized = _normalize_for_banking_check(message)

        if _LATIN_KEYWORD_PATTERN is not None and _LATIN_KEYWORD_PATTERN.search(normalized):
            return True

        for token in re.findall(r"\w+", normalized):
            if len(token) < 4:
                continue
            if difflib.get_close_matches(token, _FUZZY_VOCAB, n=1, cutoff=0.82):
                return True

        return False
    except Exception:
        return False


_SYSTEM_PROMPT = """Tu es un routeur de DOMAINE pour un assistant. Détermine si la question de \
l'utilisateur concerne la BANQUE (compte, solde, carte, virement, opérations, plafond, RIB, \
ouverture de compte, agence, bénéficiaires, prélèvement, salaire...) ou une question GÉNÉRALE \
(salutation, remerciement, small talk, culture générale, actualité, sciences, technologie, ou \
toute question qui n'est pas bancaire).

Tu ne réponds JAMAIS toi-même à la question et tu n'inventes JAMAIS de donnée bancaire.

Réponds UNIQUEMENT avec un objet JSON de la forme :
{"domain": "banking"|"general", "intent": "<courte étiquette>", "needs_web": false}

"needs_web" reste TOUJOURS false pour le moment.

Exemples :
- "ch7al 3ndi fl compte" -> {"domain": "banking", "intent": "balance_query", "needs_web": false}
- "Quel est mon solde ?" -> {"domain": "banking", "intent": "balance_query", "needs_web": false}
- "J'ai perdu ma carte" -> {"domain": "banking", "intent": "card_query", "needs_web": false}
- "Bonjour" -> {"domain": "general", "intent": "greeting", "needs_web": false}
- "Comment ça va ?" -> {"domain": "general", "intent": "small_talk", "needs_web": false}
- "Explique-moi la blockchain" -> {"domain": "general", "intent": "knowledge_question", "needs_web": false}
- "Qui est Albert Einstein ?" -> {"domain": "general", "intent": "knowledge_question", "needs_web": false}"""


def is_llm_configured() -> bool:
    """Vérifie que la configuration minimale (URL + modèle Ollama) est
    présente — ne garantit pas que le service est réellement joignable, voir
    `classify_domain` pour le repli garanti en cas d'échec réel."""
    return bool(os.getenv("OLLAMA_BASE_URL")) and bool(os.getenv("OLLAMA_MODEL"))


def _validate_and_normalize(raw: object) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None

    domain = raw.get("domain")
    if domain not in _VALID_DOMAINS:
        return None

    intent = raw.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        intent = "unclear"
    else:
        intent = intent.strip()[:100]

    # `needs_web` n'est JAMAIS lu depuis la sortie LLM — toujours forcé à
    # False ici, indépendamment de ce que le modèle a produit.
    return {"domain": domain, "intent": intent, "needs_web": False}


def _classify_with_llm(message: str, timeout: Optional[float] = None) -> Optional[dict]:
    """Retourne toujours `None` en cas d'échec (service indisponible, timeout,
    JSON invalide, domaine hors vocabulaire) — ne lève jamais d'exception.
    """
    if not is_llm_configured():
        # --- LOG TEMPORAIRE DEBUG (a retirer une fois le bug de routage identifie) ---
        print("[CU-DEBUG] is_llm_configured()=False (OLLAMA_BASE_URL/OLLAMA_MODEL manquant) -> repli immediat")
        # --- FIN LOG TEMPORAIRE DEBUG ---
        return None

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "mistral")
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
    resolved_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT_SECONDS

    prompt = f"{_SYSTEM_PROMPT}\n\nQuestion de l'utilisateur : {message}\n\nObjet JSON :"

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
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as exc:
        # --- LOG TEMPORAIRE DEBUG (a retirer une fois le bug de routage identifie) ---
        print(f"[CU-DEBUG] appel Ollama ({base_url}, model={model}) en echec : {exc!r} -> repli sur 'banking'")
        # --- FIN LOG TEMPORAIRE DEBUG ---
        return None

    # --- LOG TEMPORAIRE DEBUG (a retirer une fois le bug de routage identifie) ---
    print(f"[CU-DEBUG] raw_mistral_output={raw_output!r}")
    # --- FIN LOG TEMPORAIRE DEBUG ---

    normalized = _validate_and_normalize(raw_output)

    # --- LOG TEMPORAIRE DEBUG (a retirer une fois le bug de routage identifie) ---
    print(f"[CU-DEBUG] normalized_output={normalized!r}")
    # --- FIN LOG TEMPORAIRE DEBUG ---

    return normalized


def classify_domain(message: str, use_llm_router: bool = False, timeout: Optional[float] = None) -> dict:
    """Retourne toujours `{"domain", "intent", "needs_web"}` — ne lève jamais
    d'exception. `use_llm_router=False` (défaut) : repli déterministe
    immédiat sur `domain="banking"`, sans le moindre appel réseau — même
    convention que `agents.agent1_faq.graph.run_agent1` (`use_llm_router`
    désactivé par défaut, activé par la dépendance FastAPI
    `backend/app/routers/chat.py`).
    """
    if _looks_like_banking(message):
        return {"domain": "banking", "intent": "unclear", "needs_web": False}

    if use_llm_router:
        result = _classify_with_llm(message, timeout=timeout)
        if result is not None:
            return result

    # Repli déterministe garanti : LLM désactivé/non configuré/en échec ->
    # toujours "banking" (voir docstring du module : jamais "general" par
    # défaut, pour ne jamais laisser passer une vraie question bancaire sans
    # les protections du Banking Agent).
    return {"domain": "banking", "intent": "unclear", "needs_web": False}
