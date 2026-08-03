"""Wrapper client pour l'API Google Gemini (`google-generativeai`).

Utilise EXCLUSIVEMENT `GOOGLE_API_KEY` depuis les variables d'environnement —
jamais de clé en dur dans le code (voir CLAUDE.md §5 : aucune valeur secrète
en clair dans le code source ni dans les logs). Gère les erreurs d'appel de
manière gracieuse : `generate()` ne lève jamais qu'une des deux exceptions
typées définies ici — jamais une exception brute de la bibliothèque tierce —
à charge de `general_agent.py` de les transformer en réponse utilisateur
claire, jamais une erreur HTTP 500 opaque côté `/api/chat`.

N'accède jamais à `banking_db`, ChromaDB ni `auth.db` : ce client ne reçoit
qu'un texte de question déjà classée "générale" par le routeur top-level
(`agents/router/`), jamais une donnée bancaire.
"""
from __future__ import annotations

import os
from typing import Optional

import google.generativeai as genai

# "gemini-1.5-flash" a ete retire par l'API Gemini (404). "gemini-flash-latest"
# est l'alias officiel du modele flash gratuit courant, verifie disponible
# (quota free-tier > 0) contrairement a des identifiants dates comme
# "gemini-2.0-flash"/"gemini-2.5-flash" (quota 0 ou retires pour les nouveaux
# projets) - evite de refaire face a une deprecation similaire.
_DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")


class GeminiNotConfiguredError(Exception):
    """`GOOGLE_API_KEY` absente/vide des variables d'environnement."""


class GeminiRequestError(Exception):
    """Échec de l'appel à l'API Gemini (réseau, quota, réponse invalide...)."""


def is_configured() -> bool:
    """Vérifie uniquement que `GOOGLE_API_KEY` est renseignée — ne garantit
    pas que la clé est valide ni que le service est joignable (seule une
    tentative d'appel via `GeminiClient.generate` peut le déterminer)."""
    return bool(os.getenv("GOOGLE_API_KEY"))


class GeminiClient:
    """Wrapper mince autour de `google.generativeai` — un seul point d'entrée
    (`generate`). La clé API est relue à chaque appel (jamais mise en cache
    en mémoire au-delà de la durée de l'appel) pour refléter immédiatement
    toute modification de configuration."""

    def __init__(self, model_name: Optional[str] = None) -> None:
        self._model_name = model_name or _DEFAULT_MODEL

    def generate(self, prompt: str) -> str:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise GeminiNotConfiguredError(
                "GOOGLE_API_KEY n'est pas configurée — le General Agent (Gemini) est indisponible."
            )

        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(self._model_name)
            response = model.generate_content(prompt)
        except Exception as exc:  # noqa: BLE001 — frontière SDK tiers : toute erreur
            # (réseau, quota, clé invalide, contenu bloqué...) doit être
            # convertie en `GeminiRequestError`, jamais propagée telle quelle
            # (voir exigence "Handle API errors gracefully").
            raise GeminiRequestError(f"Échec de l'appel à l'API Gemini : {exc}") from exc

        text = getattr(response, "text", None)
        if not text:
            raise GeminiRequestError("Réponse Gemini vide ou invalide.")
        return text.strip()
