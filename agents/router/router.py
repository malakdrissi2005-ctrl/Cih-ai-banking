"""Router top-level : dispatche un message entre le Banking Agent
(`agents/agent1_faq/`, jamais modifié) et le General Agent
(`agents/general_agent/`), à partir du domaine décidé par
`conversational_understanding.classify_domain`.

    Utilisateur
       |
    Conversational Understanding (Mistral local via Ollama)
       |
    Router (ce module)
       |
       +----------------+
       |                |
       v                v
    Banking Agent   General Agent
       |                |
    banking.db       Gemini API
    ChromaDB
    Auth

Point de dispatch UNIQUE appelé par `backend/app/routers/chat.py` — le seul
endroit qui décide quel agent traite un message. Aucun autre composant
n'appelle `run_general_agent` ou `run_agent1` directement en dehors de ce
module (et des tests).
"""
from __future__ import annotations

from typing import Any, Optional

from agents.agent1_faq.graph import run_agent1
from agents.general_agent.general_agent import run_general_agent
from agents.router.conversational_understanding import classify_domain


def route_message(
    message: str,
    *,
    is_authenticated: bool = False,
    user_id: Optional[str] = None,
    collection: Any = None,
    banking_db_path: Optional[str] = None,
    session_id: Optional[str] = None,
    use_llm_router: bool = False,
) -> dict:
    """Point d'entrée unique : retourne toujours `{"intent", "requires_auth",
    "response"}`, quel que soit l'agent choisi.

    Domaine "general" -> `run_general_agent` (Gemini) UNIQUEMENT : `run_agent1`
    (donc `banking_db`/ChromaDB/le Security Guard/l'authentification) n'est
    jamais consulté.
    Domaine "banking" (y compris le repli déterministe par défaut) ->
    `run_agent1`, appelé exactement comme avant l'introduction de ce routeur
    (mêmes paramètres, comportement 100 % inchangé) : le General Agent
    (donc Gemini) n'est jamais consulté.
    """
    classification = classify_domain(message, use_llm_router=use_llm_router)
    domain = classification["domain"]
    agent = "general_agent" if domain == "general" else "agent1"

    # --- LOG TEMPORAIRE DEBUG (a retirer une fois le bug de routage identifie) ---
    print("[ROUTER-DEBUG] ===== Router top-level - trace requete =====")
    print(f"[ROUTER-DEBUG] message={message!r}")
    print(f"[ROUTER-DEBUG] use_llm_router={use_llm_router}")
    print(f"[ROUTER-DEBUG] conversational_understanding_output={classification!r}")
    print(f"[ROUTER-DEBUG] domain={domain}")
    print(f"[ROUTER-DEBUG] selected_route={agent}")
    print("[ROUTER-DEBUG] ================================================")
    # --- FIN LOG TEMPORAIRE DEBUG ---

    if domain == "general":
        return run_general_agent(message)

    return run_agent1(
        message,
        is_authenticated=is_authenticated,
        user_id=user_id,
        collection=collection,
        banking_db_path=banking_db_path,
        session_id=session_id,
        use_llm_router=use_llm_router,
    )
