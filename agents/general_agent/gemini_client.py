"""Wrapper client pour l'API Google Gemini (`google-generativeai`).

Utilise `GEMINI_API_KEY_1`/`_2`/`_3` (ou, à défaut, `GOOGLE_API_KEY` pour la
compatibilité ascendante — voir `gemini_key_manager.py`) depuis les variables
d'environnement — jamais de clé en dur dans le code (voir CLAUDE.md §5 :
aucune valeur secrète en clair dans le code source ni dans les logs). Gère
les erreurs d'appel de manière gracieuse : `generate()` ne lève jamais qu'une
des deux exceptions typées définies ici — jamais une exception brute de la
bibliothèque tierce — à charge de `general_agent.py` de les transformer en
réponse utilisateur claire, jamais une erreur HTTP 500 opaque côté
`/api/chat`. Ce contrat de sortie est strictement inchangé par la rotation de
clés ci-dessous : `general_agent.py` n'a besoin d'aucune modification.

N'accède jamais à `banking_db`, ChromaDB ni `auth.db` : ce client ne reçoit
qu'un texte de question déjà classée "générale" par le routeur top-level
(`agents/router/`), jamais une donnée bancaire.

Rotation de clés (voir `gemini_key_manager.GeminiKeyManager`) : quand la clé
active échoue pour une raison LIÉE À LA CLÉ (quota gratuit épuisé, clé
invalide), `generate()` passe automatiquement à la clé suivante et retente —
totalement transparent pour l'appelant, qui ne voit jamais la clé utilisée.
Toute autre erreur (réseau, réponse vide...) échoue immédiatement, exactement
comme avant, sans gaspiller les autres clés sur un problème qui les
affecterait toutes de la même façon.
"""
from __future__ import annotations

import os
from typing import Optional

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from agents.general_agent.gemini_key_manager import GeminiKeyManager

# "gemini-1.5-flash" a ete retire par l'API Gemini (404). "gemini-flash-latest"
# est l'alias officiel du modele flash gratuit courant, verifie disponible
# (quota free-tier > 0) contrairement a des identifiants dates comme
# "gemini-2.0-flash"/"gemini-2.5-flash" (quota 0 ou retires pour les nouveaux
# projets) - evite de refaire face a une deprecation similaire.
_DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")


class GeminiNotConfiguredError(Exception):
    """Aucune clé API Gemini configurée (ni `GEMINI_API_KEY_1/2/3`, ni `GOOGLE_API_KEY`)."""


class GeminiRequestError(Exception):
    """Échec de l'appel à l'API Gemini (réseau, quota, clé invalide, réponse invalide...)."""


def is_configured() -> bool:
    """Vérifie qu'au moins une clé Gemini est configurée — ne garantit pas
    qu'elle est valide ni que le service est joignable (seule une tentative
    d'appel via `GeminiClient.generate` peut le déterminer)."""
    return GeminiKeyManager().current_key() is not None


# Sous-chaines qui identifient un echec LIE A LA CLE (quota gratuit epuise ou
# cle invalide) plutot qu'une panne quelconque - seules ces erreurs
# declenchent une rotation vers la cle suivante ; toute autre erreur echoue
# immediatement, sans gaspiller les autres cles sur un probleme qui ne
# depend pas de la cle utilisee (reseau, contenu bloque...).
def _is_key_related_error(exc: Exception) -> bool:
    if isinstance(exc, google_exceptions.ResourceExhausted):
        return True
    message = str(exc).lower()
    if "429" in message or "quota" in message or "resourceexhausted" in message:
        return True
    if isinstance(exc, google_exceptions.InvalidArgument) and (
        "api_key_invalid" in message or "api key not valid" in message
    ):
        return True
    return False


class GeminiClient:
    """Wrapper mince autour de `google.generativeai` — un seul point d'entrée
    (`generate`). Chaque instance a son propre `GeminiKeyManager` : la clé
    (et son numéro de rotation) sont relus/recalculés à chaque appel, jamais
    mis en cache au-delà de la durée de l'appel, pour refléter immédiatement
    toute modification de configuration."""

    def __init__(self, model_name: Optional[str] = None, key_manager: Optional[GeminiKeyManager] = None) -> None:
        self._model_name = model_name or _DEFAULT_MODEL
        # `key_manager` injectable uniquement pour les tests (vérifier la
        # rotation de manière isolée) — en production, chaque `GeminiClient`
        # garde son propre gestionnaire.
        self._key_manager = key_manager or GeminiKeyManager()

    def generate(self, prompt: str) -> str:
        if self._key_manager.current_key() is None:
            raise GeminiNotConfiguredError(
                "Aucune clé API Gemini n'est configurée (GEMINI_API_KEY_1/2/3 ou GOOGLE_API_KEY) — "
                "le General Agent (Gemini) est indisponible."
            )

        last_error: Optional[Exception] = None

        while True:
            api_key = self._key_manager.current_key()
            if api_key is None:
                break
            key_number = self._key_manager.current_key_number()
            print(f"[GENAI] Using Gemini key {key_number}")

            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(self._model_name)
                response = model.generate_content(prompt)
            except Exception as exc:  # noqa: BLE001 — frontière SDK tiers : toute erreur
                # (réseau, quota, clé invalide, contenu bloqué...) doit être
                # convertie en `GeminiRequestError`, jamais propagée telle
                # quelle (voir exigence "Handle API errors gracefully") —
                # sauf si elle est liée à la clé, auquel cas on tourne
                # d'abord vers la clé suivante plutôt que d'abandonner.
                last_error = exc
                if _is_key_related_error(exc):
                    print(f"[GENAI] Quota exceeded on key {key_number}")
                    print("[GENAI] Current key failed, switching to next key")
                    if self._key_manager.advance():
                        print(f"[GENAI] Switching to key {self._key_manager.current_key_number()}")
                        continue
                    break
                raise GeminiRequestError(f"Échec de l'appel à l'API Gemini : {exc}") from exc

            text = getattr(response, "text", None)
            if not text:
                raise GeminiRequestError("Réponse Gemini vide ou invalide.")

            print("[GENAI] Response generated successfully")
            return text.strip()

        raise GeminiRequestError(
            f"Échec de l'appel à l'API Gemini (toutes les clés disponibles ont échoué) : {last_error}"
        ) from last_error
