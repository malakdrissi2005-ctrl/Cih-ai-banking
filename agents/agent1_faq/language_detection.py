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
    # --- Ajout : couverture d'une demande d'information générale sur le compte
    # ("3afak 3tini lma3lomat 3la l7sab" - non détectée auparavant, aucun de ces
    # tokens n'existant en français standard, donc aucun risque de faux positif) ---
    "3afak",
    "afak",
    "3tini",
    "3la",
    "hsab",
    "lhsab",
    "ma3lomat",
    "m3lomat",
    # --- Enrichissement de la couverture Darija/Arabizi : marqueurs des
    # nouvelles formulations prises en charge par `darija_normalization.py`.
    # Sans marqueur ici, le message est détecté comme "fr", donc JAMAIS
    # normalisé — écart mesuré sur "chhal baqi liya", qui restait en
    # `faq_generale` alors que sa normalisation était pourtant correcte.
    # Comme les entrées ci-dessus, tous ces tokens sont choisis parce qu'ils
    # n'existent pas en français standard : aucun risque de faux positif sur
    # un message réellement français.
    "chhal",
    "ch7el",
    "cha7al",
    "liya",
    "baqi",
    "n3ref",
    "nchof",
    "nchouf",
    "chof",
    "tafasil",
    "l7sab",
    "l7ssab",
    "l7ala",
    "l3amaliyat",
    "3amaliyat",
    "akhir",
    "khsart",
    "wdart",
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
