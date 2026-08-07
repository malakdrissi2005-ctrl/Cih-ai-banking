"""General Agent — point d'entrée métier pour les questions non bancaires.

Reçoit UNIQUEMENT des messages déjà classés "general" par le routeur
top-level (`agents/router/router.py`), jamais une question bancaire. Appelle
`gemini_client.GeminiClient` et retourne la réponse au frontend, dans le même
format que `agents.agent1_faq.graph.run_agent1` (`{"intent", "requires_auth",
"response"}`) pour rester interchangeable côté appelant
(`backend/app/routers/chat.py`).

N'accède jamais à `banking_db`, ChromaDB ni `auth.db` — aucune donnée
bancaire ne transite par ce module, conformément à la séparation stricte
entre agents exigée par CLAUDE.md. Ne nécessite jamais d'authentification
(`requires_auth` toujours `False`) : une question générale est, par
définition, publique.
"""
from __future__ import annotations

from agents.general_agent.gemini_client import GeminiClient, GeminiNotConfiguredError, GeminiRequestError

# Messages distincts pour permettre à l'appelant/aux tests de distinguer une
# absence de configuration (erreur opérateur) d'un échec d'appel ponctuel
# (réseau, quota...) — voir exigence "Missing GOOGLE_API_KEY returns a clear error".
GEMINI_NOT_CONFIGURED_MESSAGE = (
    "L'assistant général (Gemini) n'est pas configuré : aucune clé API n'est renseignée "
    "(GEMINI_API_KEY_1, GEMINI_API_KEY_2, GEMINI_API_KEY_3, ou à défaut GOOGLE_API_KEY)."
)
GENERAL_AGENT_UNAVAILABLE_MESSAGE = "L'assistant général n'est pas disponible pour le moment. Merci de réessayer plus tard."

_client = GeminiClient()


def run_general_agent(message: str) -> dict:
    """Ne lève jamais d'exception : toute erreur Gemini (clé manquante, échec
    réseau, quota, réponse invalide...) est transformée ici en un message
    clair, jamais une erreur HTTP 500 opaque pour l'utilisateur final.
    """
    try:
        response = _client.generate(message)
    except GeminiNotConfiguredError:
        return {"intent": "general_query", "requires_auth": False, "response": GEMINI_NOT_CONFIGURED_MESSAGE}
    except GeminiRequestError:
        return {"intent": "general_query", "requires_auth": False, "response": GENERAL_AGENT_UNAVAILABLE_MESSAGE}

    return {"intent": "general_query", "requires_auth": False, "response": response}
