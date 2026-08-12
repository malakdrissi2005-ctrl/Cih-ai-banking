"""Endpoints d'authentification de démonstration — session opaque, sans JWT.

`POST /api/auth/login`, `GET /api/auth/session`, `POST /api/auth/logout`.
Voir `backend/app/security/session_manager.py` pour la logique et le
principe (session_id opaque en SQLite, jamais un JWT — CLAUDE.md §4).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.security import session_manager

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    # Le champ conserve le nom `username` pour ne rien casser côté frontend,
    # mais accepte désormais indifféremment un IDENTIFIANT DE CONNEXION ou une
    # ADRESSE E-MAIL : la résolution est faite par
    # `session_manager.verify_credentials` (voir `UTILISATEUR_E_BANKING`).
    username: str
    password: str


class LoginResponse(BaseModel):
    session_id: str
    expires_at: str


class SessionResponse(BaseModel):
    authenticated: bool
    user_id: str
    username: str
    expires_at: str


def get_auth_db_path() -> Optional[str]:
    """Dépendance FastAPI — surchargée dans les tests pour isoler la base SQLite."""
    return session_manager.DEFAULT_DB_PATH


def get_banking_db_path() -> Optional[str]:
    """Dépendance FastAPI — chemin de la base bancaire métier.

    Nécessaire ici parce que les comptes d'accès en ligne
    (`UTILISATEUR_E_BANKING`) vivent dans la base bancaire, tandis que la
    table `sessions` reste dans `auth.db`. Sans cette dépendance, le login
    interrogeait la base bancaire PAR DÉFAUT au lieu de celle réellement
    configurée, et retournait 401 alors que les identifiants étaient valides.
    """
    from app.banking import banking_db

    return banking_db.DEFAULT_DB_PATH


def _extract_session_id(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Session manquante ou invalide.")
    session_id = authorization.split(" ", 1)[1].strip()
    if not session_id:
        raise HTTPException(status_code=401, detail="Session manquante ou invalide.")
    return session_id


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    db_path: Optional[str] = Depends(get_auth_db_path),
    banking_db_path: Optional[str] = Depends(get_banking_db_path),
) -> LoginResponse:
    # Les utilisateurs sont importés séparément depuis data/auth/users_seed.json
    # (voir scripts/seed_auth_users.py) - le login ne crée plus lui-même d'utilisateur.
    user = session_manager.verify_credentials(
        payload.username, payload.password, db_path=db_path, banking_db_path=banking_db_path
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Identifiants invalides.")

    session = session_manager.create_session(user_id=user["user_id"], db_path=db_path)
    return LoginResponse(**session)


@router.get("/session", response_model=SessionResponse)
def check_session(
    authorization: Optional[str] = Header(default=None),
    db_path: Optional[str] = Depends(get_auth_db_path),
    banking_db_path: Optional[str] = Depends(get_banking_db_path),
) -> SessionResponse:
    session_id = _extract_session_id(authorization)
    session = session_manager.get_valid_session(
        session_id, db_path=db_path, banking_db_path=banking_db_path
    )
    if session is None:
        raise HTTPException(status_code=401, detail="Session invalide ou expirée.")
    return SessionResponse(
        authenticated=True,
        user_id=session["user_id"],
        username=session["username"],
        expires_at=session["expires_at"],
    )


@router.post("/logout")
def logout(
    authorization: Optional[str] = Header(default=None),
    db_path: Optional[str] = Depends(get_auth_db_path),
) -> dict:
    session_id = _extract_session_id(authorization)
    session_manager.delete_session(session_id, db_path=db_path)
    return {"status": "logged_out"}
