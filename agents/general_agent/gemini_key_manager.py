"""Gestionnaire de rotation des clés API Gemini.

Charge `GEMINI_API_KEY_1`/`GEMINI_API_KEY_2`/`GEMINI_API_KEY_3` depuis
l'environnement (ignore les variables absentes/vides — fonctionne avec 1, 2
ou 3 clés). Compatibilité ascendante : si aucune `GEMINI_API_KEY_N` n'est
définie, se rabat sur `GOOGLE_API_KEY` (variable historique, toujours
documentée dans `.env.example`/`CLAUDE.md`) comme unique clé — un déploiement
qui n'a pas encore migré vers plusieurs clés continue de fonctionner
à l'identique.

État simple, en mémoire, pour la durée du process : une fois une clé marquée
épuisée, on ne revient jamais en arrière (pas de réessai automatique après un
délai — volontairement simple, voir CLAUDE.md/consigne "pas de complexité
inutile"). Ce module ne fait lui-même aucun appel réseau — seul
`gemini_client.py` interroge l'API Gemini ; ce gestionnaire décide
uniquement QUELLE clé utiliser.
"""
from __future__ import annotations

import os
from typing import Optional

_KEY_ENV_VARS = ("GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3")
_LEGACY_KEY_ENV_VAR = "GOOGLE_API_KEY"


class GeminiKeyManager:
    """Rotation simple et séquentielle entre plusieurs clés API Gemini."""

    def __init__(self) -> None:
        self._index = 0

    def _load_keys(self) -> list[str]:
        """Relit les clés depuis l'environnement à chaque appel (même
        principe que `GeminiClient` : jamais mises en cache au-delà d'un
        appel, pour refléter immédiatement toute modification de
        configuration)."""
        keys = [os.getenv(var) for var in _KEY_ENV_VARS]
        keys = [key for key in keys if key]
        if keys:
            return keys
        # Compatibilité ascendante : aucune GEMINI_API_KEY_N définie -> repli
        # sur l'ancienne variable à clé unique, si présente.
        legacy = os.getenv(_LEGACY_KEY_ENV_VAR)
        return [legacy] if legacy else []

    def current_key(self) -> Optional[str]:
        """Retourne la clé active, ou `None` si toutes les clés disponibles
        ont déjà été marquées épuisées pour ce process."""
        keys = self._load_keys()
        if self._index >= len(keys):
            return None
        return keys[self._index]

    def current_key_number(self) -> int:
        """Numéro d'affichage (1-based) de la clé active, pour les logs
        `[GENAI]` — n'est jamais utilisé pour indexer `_load_keys()`."""
        return self._index + 1

    def advance(self) -> bool:
        """Passe à la clé suivante. Retourne `True` si une clé suivante
        existe (donc si un nouvel essai est possible), `False` si toutes les
        clés disponibles ont déjà été essayées."""
        self._index += 1
        return self.current_key() is not None
