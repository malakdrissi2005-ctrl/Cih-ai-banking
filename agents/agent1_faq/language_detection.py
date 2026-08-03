"""Détection déterministe de la langue du message entrant.

Couche linguistique strictement séparée de la logique métier (voir
`CLAUDE.md`, `DocsContext/02_architecture_multi_agents.md` §2.4) : purement
programmatique, jamais laissée à l'appréciation d'un LLM — même principe que
`classification.classify_intent`.

Retourne l'une de trois valeurs :
- "fr"           : français
- "darija_ar"     : darija marocaine écrite en alphabet arabe
- "darija_latn"   : darija marocaine écrite en alphabet latin / Arabizi
"""
from __future__ import annotations

import re

Language = str  # "fr" | "darija_ar" | "darija_latn"

# Bloc Unicode de l'écriture arabe (arabe + supplément + formes de présentation),
# suffisant pour l'arabe marocain (darija) écrit sans diacritiques particuliers.
_ARABIC_CHAR_PATTERN = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_LATIN_LETTER_PATTERN = re.compile(r"[A-Za-z]")

# Marqueurs lexicaux caractéristiques de la darija écrite en alphabet latin /
# Arabizi (liste volontairement limitée aux mots qui n'existent pas en
# français standard, pour éviter tout faux positif sur du texte français).
_DARIJA_LATN_MARKERS = [
    "ch7al",
    "wach",
    "dyali",
    "dyalek",
    "dyal",
    "3ndi",
    "n9der",
    "had",
    "chher",
    "sraft",
    "khdama",
    "bghit",
    "n7awel",
    "khassk",
    "khassni",
    "zid",
    "dkhal",
    "lia",
    "simana",
    "biha",
    "mn",
    "howa",
]
_DARIJA_LATN_PATTERN = re.compile(r"\b(" + "|".join(_DARIJA_LATN_MARKERS) + r")\b", re.IGNORECASE)


def detect_language(message: str) -> Language:
    """Détecte la langue du message : "fr", "darija_ar" ou "darija_latn"."""
    if not message:
        return "fr"

    arabic_chars = len(_ARABIC_CHAR_PATTERN.findall(message))
    latin_letters = len(_LATIN_LETTER_PATTERN.findall(message))

    # Présence majoritaire de caractères arabes parmi les lettres du message.
    if arabic_chars > 0 and arabic_chars >= latin_letters:
        return "darija_ar"

    if _DARIJA_LATN_PATTERN.search(message):
        return "darija_latn"

    return "fr"
