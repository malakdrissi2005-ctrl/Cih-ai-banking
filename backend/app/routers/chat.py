"""`POST /api/chat` — interface HTTP vers le Router top-level
(`agents/router/`), qui dispatche vers le Banking Agent (Agent 1 — FAQ
publique + questions bancaires personnelles pour un utilisateur authentifié)
ou le General Agent (questions non bancaires, via Gemini).

La session est optionnelle (`Authorization: Bearer <session_id>`) : absente,
invalide ou expirée, elle est traitée silencieusement comme non authentifiée
(jamais une erreur HTTP ici — une question personnelle sans session valide
reçoit simplement une invitation à se connecter, voir `CLAUDE.md`). Quand la
session est valide, seul le `user_id` qu'elle porte est transmis au Banking
Agent — jamais un identifiant venant du corps de la requête — pour garantir
l'isolation stricte entre utilisateurs. Le General Agent ne reçoit jamais de
`user_id` ni de session : une question générale est, par définition, publique.
"""
from __future__ import annotations

import sys
from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from agents.agent1_faq import llm_router
from agents.agent1_faq.rag import FaqEmbeddingDimensionMismatchError, get_faq_collection
from agents.router.router import route_message
from app.banking.banking_db import DEFAULT_DB_PATH as DEFAULT_BANKING_DB_PATH
from app.routers.auth import get_auth_db_path
from app.security import session_manager

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    intent: str
    requires_auth: bool
    response: str


# Journalisé une seule fois par processus : `get_faq_collection` lève à CHAQUE
# appel tant que l'index n'est pas ré-ingéré, ce qui inonderait les logs.
_faq_collection_error_logged = False


def get_faq_collection_dependency():
    """Dépendance FastAPI — surchargée dans les tests pour isoler ChromaDB.

    Retourne `None` si l'index vectoriel est INUTILISABLE (créé par une
    version précédente de l'embedding, voir `rag.py`), au lieu de laisser
    l'exception remonter.

    Pourquoi : une dépendance FastAPI est résolue AVANT le corps de
    l'endpoint. Une exception ici renvoyait un HTTP 500 sur *toutes* les
    requêtes `/api/chat` — y compris les questions personnelles et les refus
    d'opération sensible, qui n'utilisent pourtant jamais ChromaDB. Un index
    FAQ périmé est un problème de DONNÉES, réparable par une commande ; il ne
    doit pas mettre l'assistant entier hors service (`CLAUDE.md` : le repli
    déterministe doit fonctionner en toutes circonstances).

    L'erreur n'est jamais silencieuse : elle est journalisée sur stderr avec
    la commande exacte à lancer, et la FAQ publique répond alors
    `NO_FAQ_MESSAGE` (voir `graph.py::_answer_faq_node`) plutôt qu'une erreur
    technique.
    """
    global _faq_collection_error_logged
    try:
        return get_faq_collection()
    except FaqEmbeddingDimensionMismatchError as exc:
        if not _faq_collection_error_logged:
            print(
                "[FAQ] Index vectoriel inutilisable : la recherche FAQ publique est "
                f"temporairement désactivée. Le reste de l'assistant fonctionne. {exc}",
                file=sys.stderr,
            )
            _faq_collection_error_logged = True
        return None


def get_banking_db_path_dependency() -> Optional[str]:
    """Dépendance FastAPI — surchargée dans les tests pour isoler banking.db."""
    return DEFAULT_BANKING_DB_PATH


def get_use_llm_router_dependency() -> bool:
    """Dépendance FastAPI — surchargée (`False`) dans les tests pour rester
    hermétique à tout service Ollama réel. Reflète `llm_router.is_router_enabled()`
    (`LLM_ROUTER_ENABLED`, défaut "true") ; un opérateur peut désactiver
    entièrement la tentative LLM pour ne conserver que le comportement
    déterministe existant, sans changer de code."""
    return llm_router.is_router_enabled()


def _extract_session_id(authorization: Optional[str]) -> Optional[str]:
    """Extrait le jeton de session brut (`Authorization: Bearer <session_id>`),
    valide ou non — utilisé uniquement comme clé du contexte conversationnel
    court terme (`conversation_memory.py`), jamais pour l'autorisation."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    session_id = authorization.split(" ", 1)[1].strip()
    return session_id or None


def _resolve_session(
    authorization: Optional[str],
    auth_db_path: Optional[str],
    banking_db_path: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Valide silencieusement une session optionnelle. Ne lève jamais d'erreur HTTP :
    absente/invalide/expirée => utilisateur non authentifié pour ce message.

    `banking_db_path` est INDISPENSABLE : la table `sessions` vit dans
    `auth.db`, mais l'utilisateur est résolu dans `UTILISATEUR_E_BANKING`
    (base bancaire). Sans ce paramètre, `session_manager` interrogeait la base
    bancaire par défaut au lieu de celle réellement configurée — une session
    valide était alors rejetée en environnement de test ou de démonstration.
    """
    session_id = _extract_session_id(authorization)
    if session_id is None:
        return False, None
    session = session_manager.get_valid_session(
        session_id, db_path=auth_db_path, banking_db_path=banking_db_path
    )
    if session is None:
        return False, None
    return True, session["user_id"]


@router.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(
    payload: ChatRequest,
    authorization: Optional[str] = Header(default=None),
    collection=Depends(get_faq_collection_dependency),
    auth_db_path: Optional[str] = Depends(get_auth_db_path),
    banking_db_path: Optional[str] = Depends(get_banking_db_path_dependency),
    use_llm_router: bool = Depends(get_use_llm_router_dependency),
) -> ChatResponse:
    is_authenticated, user_id = _resolve_session(authorization, auth_db_path, banking_db_path)
    session_id = _extract_session_id(authorization)

    # --- LOG TEMPORAIRE DEBUG (a retirer une fois le bug de routage identifie) ---
    print("[CHAT-DEBUG] appel de agents.router.router.route_message() "
          f"(use_llm_router={use_llm_router})")
    # --- FIN LOG TEMPORAIRE DEBUG ---

    result = route_message(
        payload.message,
        is_authenticated=is_authenticated,
        user_id=user_id,
        collection=collection,
        banking_db_path=banking_db_path,
        session_id=session_id,
        use_llm_router=use_llm_router,
    )

    # --- LOG TEMPORAIRE DEBUG (a retirer une fois le bug de routage identifie) ---
    selected_agent = "general_agent" if result.get("intent") == "general_query" else "agent1"
    print(f"[CHAT-DEBUG] agent selectionne (deduit de result.intent={result.get('intent')!r}) = {selected_agent}")
    # --- FIN LOG TEMPORAIRE DEBUG ---

    return ChatResponse(**result)
