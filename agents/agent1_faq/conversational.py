"""Couche de compréhension conversationnelle de l'Agent 1 — salutations,
remerciements, small talk et messages courts inintelligibles.

Insérée dans le graphe (`graph.py`) juste après `security_guard` et **avant**
`llm_router`/`classify_fallback` : ces messages ne portent aucune intention
bancaire (ni FAQ, ni donnée personnelle) et ne doivent donc **jamais**
déclencher une recherche ChromaDB ni une lecture de `banking_db` — les
intercepter tôt, avant tout appel Mistral, évite aussi une latence inutile
(~4-7 s d'aller-retour Ollama) pour un simple "slm".

Classification purement déterministe (regex/ensembles de mots), même
principe que `classification.classify_intent` : jamais laissée à
l'appréciation d'un LLM, jamais d'accès à `banking_db`/ChromaDB.

Approche volontairement conservatrice : un message n'est classé
conversationnel que si la totalité de ses mots appartient au vocabulaire
connu (salutation/remerciement/filler) — un message qui mélange une
salutation et une vraie question ("bonjour, quel est mon solde ?") n'est PAS
intercepté ici et continue vers la classification habituelle
(`llm_router`/`classify_fallback`), pour ne jamais avaler une question
bancaire réelle.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal, Optional

ConversationalIntent = Literal["greeting", "thanks", "small_talk", "unclear_short"]


def _normalize(text: str) -> str:
    """Minuscule, sans accents/diacritiques — même approche que `classification._normalize`."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


# Salutations — français, anglais, darija (arabe et Arabizi/latin). Formes
# déjà normalisées (sans accent/diacritique) pour correspondre à la sortie de
# `_normalize` ci-dessus.
_GREETING_TOKENS = {
    "slm", "salam", "salamalikoum", "salamoalikoum", "salam3alikoum",
    "assalam", "assalamoalaikoum", "bonjour", "bonsoir", "bsoir", "salut",
    "coucou", "hi", "hello", "hey", "yo",
    "سلام", "السلام", "عليكم", "مرحبا", "اهلا",
}

# Remerciements — français, anglais, darija.
_THANKS_TOKENS = {
    "merci", "mrc", "chokran", "choukran", "shokran", "thanks", "thank", "thx",
    "شكرا", "متشكرين",
}

# Petites conversations ("comment ça va ?") : expressions multi-mots,
# recherchées comme sous-chaîne du message normalisé (contrairement aux
# salutations/remerciements ci-dessus qui exigent une correspondance totale
# du message) car il n'existe pas de vocabulaire bancaire légitime qui les
# contiendrait accidentellement.
_SMALL_TALK_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\bca va\b",
        r"\bcv\b",
        r"\blabas\b",
        r"\bkif rak\b",
        r"\bkifach rak\b",
        r"\bkif dayer\b",
        r"\bcomment (vas[- ]tu|allez[- ]vous)\b",
        r"\bhow are you\b",
    )
]

# Filler/interjections courtes sans contenu — n'importe quel message
# entièrement composé de ces tokens est traité comme "unclear_short" plutôt
# que d'être envoyé à ChromaDB (qui ne retournerait qu'un bruit non pertinent).
_FILLER_TOKENS = {
    "ok", "okay", "daccord", "bon", "bref", "hmm", "hum", "euh", "bah",
    "test", "cc", "wesh",
}


def classify_conversational(message: Optional[str]) -> Optional[ConversationalIntent]:
    """Retourne "greeting"/"thanks"/"small_talk"/"unclear_short" si le message
    est purement conversationnel (rien à router vers la FAQ ou les données
    personnelles), sinon `None` — l'appelant (`graph.py`) continue alors vers
    la classification habituelle (`llm_router` puis, en repli,
    `classify_fallback`), sans aucune modification de leur comportement.
    """
    if message is None or not message.strip():
        return "unclear_short"

    normalized = _normalize(message.strip())
    tokens = re.findall(r"\w+", normalized)

    if not tokens:
        # Uniquement de la ponctuation/des symboles/des emojis, aucun mot.
        return "unclear_short"

    if all(token in _GREETING_TOKENS for token in tokens):
        return "greeting"

    if all(token in _THANKS_TOKENS for token in tokens):
        return "thanks"

    if any(pattern.search(normalized) for pattern in _SMALL_TALK_PATTERNS):
        return "small_talk"

    if all(token in _FILLER_TOKENS for token in tokens):
        return "unclear_short"

    return None
