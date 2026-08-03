"""Contexte conversationnel simple, en mémoire, non persistant.

Permet de désambiguïser une question de suivi (ex. "Quel est mon solde ?" puis
"Et mes dépenses du mois ?") en fournissant les derniers échanges de la
**même session** au LLM Router (`llm_router.py`). Ce n'est **jamais** une
mémoire permanente : rien n'est écrit sur disque ni dans `banking.db`/`auth.db`,
tout est perdu au redémarrage du processus — conformément à la demande
explicite de ne pas créer de mémoire permanente.

Clé de stockage : `session_id` (le jeton de session opaque déjà émis par
`app/security/session_manager.py`, jamais un identifiant fourni par le texte
du message). Un `session_id` absent (utilisateur non authentifié) ne stocke
et ne lit simplement rien — comportement sans effet, jamais une erreur.
"""
from __future__ import annotations

import threading

_MAX_TURNS_PER_SESSION = 5

_lock = threading.Lock()
_history: dict[str, list[tuple[str, str]]] = {}


def record_turn(session_id: str, message: str, response: str) -> None:
    """Ajoute un échange (message utilisateur, réponse) à l'historique de la session.

    Conserve au maximum `_MAX_TURNS_PER_SESSION` échanges les plus récents —
    ni journal complet, ni persistance : uniquement un contexte à court terme
    pour enrichir le prompt du LLM Router.
    """
    if not session_id:
        return
    with _lock:
        turns = _history.setdefault(session_id, [])
        turns.append((message, response))
        del turns[:-_MAX_TURNS_PER_SESSION]


def get_history(session_id: str) -> list[tuple[str, str]]:
    """Retourne une copie des derniers échanges de la session, ou une liste vide."""
    if not session_id:
        return []
    with _lock:
        return list(_history.get(session_id, []))


def clear(session_id: str) -> None:
    """Efface l'historique d'une session (ex. à la déconnexion)."""
    with _lock:
        _history.pop(session_id, None)
