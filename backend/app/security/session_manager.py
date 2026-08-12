"""Authentification de démonstration multi-utilisateur — session opaque en SQLite.

Voir `CLAUDE.md` §4 : la session utilisateur est identifiée par un
`session_id` **opaque** (chaîne aléatoire sans structure interne), validée
par FastAPI à chaque requête protégée — **jamais** un JWT. Elle est
strictement distincte du futur jeton de délégation A2A (signé, JWT via
`python-jose`, `security/jwt_handler.py`), hors périmètre de ce module.

Persistance : une base SQLite dédiée (`users` + `sessions`), séparée de
`chroma_db/` (RAG) et du futur checkpointer LangGraph de l'Agent 2.

Le système ne se limite pas à un unique utilisateur de démonstration :
n'importe quel nombre d'utilisateurs peut être importé depuis
`data/auth/users_seed.json` (voir `seed_users`), sans modification de code.
Chaque utilisateur possède un `user_id` opaque (ex. `usr_001`) et un
`username` propres, tous deux uniques ; toute session créée après connexion
est associée au `user_id` de l'utilisateur authentifié.

Hors périmètre pour cette étape (voir `CLAUDE.md`) : `banking.db`, comptes
bancaires, soldes, transactions, bénéficiaires, virements, réponses
personnelles de l'Agent 1, Agent 2, OTP, A2A, MCP, n8n.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt

# Racine du dépôt (security/session_manager.py -> security -> app -> backend -> racine),
# même convention que `agents/agent1_faq/rag.py` : les chemins relatifs (AUTH_DB_PATH)
# sont résolus par rapport à la racine du monorepo, jamais au répertoire courant du
# processus (qui varie selon l'endroit d'où une commande est lancée).
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return str(path)


DEFAULT_DB_PATH = _resolve_path(os.getenv("AUTH_DB_PATH", "./auth.db"))
DEFAULT_SESSION_MINUTES = int(os.getenv("SESSION_EXPIRATION_MINUTES", "30"))
DEFAULT_USERS_SEED_PATH = _REPO_ROOT / "data" / "auth" / "users_seed.json"


class UsersSeedValidationError(ValueError):
    """Levée quand `users_seed.json` contient une entrée invalide ou n'est pas une liste JSON."""


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    resolved = _resolve_path(db_path) if db_path else DEFAULT_DB_PATH
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Crée les tables `users`/`sessions` si elles n'existent pas déjà (idempotent).

    `users.user_id` (ex. `usr_001`) est l'identifiant opaque métier, distinct
    du `session_id` de session — c'est lui qui est propagé dans `sessions`.
    """
    with closing(_get_connection(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            """
        )
        conn.commit()


def load_users_seed(seed_path: Optional[Path] = None) -> list[dict]:
    """Lit et valide `users_seed.json`. Lève `UsersSeedValidationError` sur toute entrée invalide."""
    seed_path = Path(seed_path) if seed_path else DEFAULT_USERS_SEED_PATH
    if not seed_path.exists():
        raise UsersSeedValidationError(
            f"{seed_path} est introuvable — créez-le avec un tableau JSON d'utilisateurs."
        )

    raw = seed_path.read_text(encoding="utf-8").strip() or "[]"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsersSeedValidationError(f"{seed_path} : JSON invalide ({exc}).") from exc

    if not isinstance(data, list):
        raise UsersSeedValidationError(
            f"{seed_path} : le contenu doit être une liste JSON, reçu {type(data).__name__}."
        )

    entries: list[dict] = []
    seen_user_ids: set[str] = set()
    seen_usernames: set[str] = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise UsersSeedValidationError(
                f"Entrée #{index} invalide : un objet JSON est attendu, reçu {type(item).__name__}."
            )

        user_id = item.get("user_id")
        if not isinstance(user_id, str) or not user_id.strip():
            raise UsersSeedValidationError(f"Entrée #{index} invalide : champ 'user_id' manquant ou vide.")
        if user_id in seen_user_ids:
            raise UsersSeedValidationError(f"Entrée #{index} invalide : user_id '{user_id}' dupliqué dans le fichier.")
        seen_user_ids.add(user_id)

        username = item.get("username")
        if not isinstance(username, str) or not username.strip():
            raise UsersSeedValidationError(f"Entrée #{index} invalide (user_id={user_id}) : champ 'username' manquant ou vide.")
        if username in seen_usernames:
            raise UsersSeedValidationError(f"Entrée #{index} invalide : username '{username}' dupliqué dans le fichier.")
        seen_usernames.add(username)

        display_name = item.get("display_name")
        if not isinstance(display_name, str) or not display_name.strip():
            raise UsersSeedValidationError(
                f"Entrée #{index} invalide (user_id={user_id}) : champ 'display_name' manquant ou vide."
            )

        status = item.get("status") or "active"
        if not isinstance(status, str) or not status.strip():
            raise UsersSeedValidationError(f"Entrée #{index} invalide (user_id={user_id}) : champ 'status' invalide.")

        entries.append(
            {
                "user_id": user_id.strip(),
                "username": username.strip(),
                "display_name": display_name.strip(),
                "status": status.strip(),
            }
        )

    return entries


def seed_users(
    seed_path: Optional[Path] = None,
    db_path: Optional[str] = None,
    default_password: Optional[str] = None,
) -> dict:
    """Importe tous les utilisateurs de `users_seed.json` dans `auth.db` (idempotent).

    N'écrit jamais de mot de passe en dur : `DEMO_DEFAULT_PASSWORD` doit être
    définie (ou passée explicitement pour les tests) — seul son hash bcrypt
    est stocké, identique pour tous les utilisateurs importés par cette
    exécution. Ré-exécutable sans dupliquer ni créer de seconde ligne pour un
    `user_id` déjà présent (upsert par `user_id`, unicité garantie par le
    schéma sur `user_id` et `username`). Ne crée **aucune** session.
    """
    seed_path = Path(seed_path) if seed_path else DEFAULT_USERS_SEED_PATH
    entries = load_users_seed(seed_path)

    password = default_password or os.getenv("DEMO_DEFAULT_PASSWORD")
    if not password:
        raise RuntimeError(
            "DEMO_DEFAULT_PASSWORD doit être définie (voir .env.example) pour initialiser "
            "les utilisateurs de démonstration."
        )

    init_db(db_path)
    password_hash = _hash_password(password)

    inserted = 0
    updated = 0
    with closing(_get_connection(db_path)) as conn:
        for entry in entries:
            existing = conn.execute(
                "SELECT user_id FROM users WHERE user_id = ?", (entry["user_id"],)
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO users (user_id, username, display_name, status, password_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry["user_id"],
                        entry["username"],
                        entry["display_name"],
                        entry["status"],
                        password_hash,
                        _utcnow().isoformat(),
                    ),
                )
                inserted += 1
            else:
                conn.execute(
                    """
                    UPDATE users SET username = ?, display_name = ?, status = ?, password_hash = ?
                    WHERE user_id = ?
                    """,
                    (entry["username"], entry["display_name"], entry["status"], password_hash, entry["user_id"]),
                )
                updated += 1
        conn.commit()

        users_in_db = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        sessions_in_db = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    return {
        "seed_path": str(seed_path),
        "total_entries": len(entries),
        "inserted": inserted,
        "updated": updated,
        "users_in_db": users_in_db,
        "sessions_in_db": sessions_in_db,
    }


# ---------------------------------------------------------------------------
# Résolution de l'utilisateur — DEUX SOURCES, dans cet ordre.
#
# 1. `UTILISATEUR_E_BANKING`, dans la base bancaire métier (source cible).
# 2. `users`, dans `auth.db` (LEGACY, conservée pour la transition).
#
# Pourquoi deux sources : la table `sessions` reste dans `auth.db` tandis que
# les comptes d'accès migrent vers la base bancaire. SQLite n'autorisant pas de
# `JOIN` entre fichiers, l'ancien `sessions JOIN users` est remplacé par deux
# lectures et une liaison par valeur.
#
# Le repli legacy n'est pas de la dette : il garantit qu'une session déjà
# émise, et que tout l'existant (scripts de seed, tests d'authentification),
# continuent de fonctionner sans modification pendant la bascule. Il pourra
# être retiré une fois `auth.db.users` définitivement abandonnée.
#
# bcrypt est obligatoire sur les DEUX chemins : `_verify_password` est la seule
# porte de vérification, aucun mot de passe en clair n'est jamais comparé,
# stocké ni journalisé.
# ---------------------------------------------------------------------------


def _verify_against_ebanking(login: str, password: str, banking_db_path: Optional[str]) -> Optional[dict]:
    """Vérifie les identifiants contre `UTILISATEUR_E_BANKING`.

    Accepte un identifiant de connexion OU une adresse e-mail (voir
    `banking_db.find_ebanking_user_by_login`). Retourne `None` si la table
    n'existe pas encore, si le compte est introuvable, si son
    `statut_connexion` n'est pas actif, ou si le mot de passe est invalide —
    dans tous ces cas l'appelant tentera la source legacy.
    """
    from app.banking import banking_db  # import local : évite tout cycle au chargement

    try:
        account = banking_db.find_ebanking_user_by_login(login, db_path=banking_db_path)
    except Exception:  # noqa: BLE001 — base bancaire absente/illisible : on retombe sur le legacy
        return None

    if account is None:
        return None
    if account["statut_connexion"] != "actif":
        return None
    if not _verify_password(password, account["mot_de_passe_hash"]):
        return None

    banking_db.touch_last_login(account["id_utilisateur"], db_path=banking_db_path)
    # `user_id` porte l'ID CLIENT (`CL0001`), jamais l'ID du compte d'accès
    # (`EB0001`) : c'est `id_client` qui indexe toutes les lectures bancaires
    # (`get_total_balance`, `get_transactions`, `get_card_for_customer`…).
    # Sémantique inchangée par rapport au schéma précédent, où `usr_001`
    # servait déjà à la fois d'identifiant d'utilisateur et de client.
    return {"user_id": account["id_client"], "username": account["identifiant_connexion"]}


def _resolve_user_from_ebanking(user_id: str, banking_db_path: Optional[str]) -> Optional[dict]:
    """Résout l'utilisateur d'une session existante dans la base bancaire.

    `user_id` est un ID CLIENT (voir la note dans `_verify_against_ebanking`),
    la recherche se fait donc sur `id_client`.
    """
    from app.banking import banking_db

    try:
        account = banking_db.find_ebanking_user_by_client(user_id, db_path=banking_db_path)
    except Exception:  # noqa: BLE001 — voir commentaire ci-dessus
        return None

    if account is None:
        return None
    return {"user_id": account["id_client"], "username": account["identifiant_connexion"]}


def verify_credentials(
    username: str,
    password: str,
    db_path: Optional[str] = None,
    banking_db_path: Optional[str] = None,
) -> Optional[dict]:
    """Retourne `{user_id, username}` si les identifiants sont corrects, sinon `None`.

    `username` accepte indifféremment un identifiant de connexion ou une
    adresse e-mail lorsque le compte provient de `UTILISATEUR_E_BANKING`.
    Signature rétro-compatible : les deux premiers paramètres sont inchangés.
    """
    account = _verify_against_ebanking(username, password, banking_db_path)
    if account is not None:
        return account

    # --- Repli LEGACY : `auth.db.users` ---
    init_db(db_path)
    with closing(_get_connection(db_path)) as conn:
        row = conn.execute(
            "SELECT user_id, username, password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        return None
    if not _verify_password(password, row["password_hash"]):
        return None
    return {"user_id": row["user_id"], "username": row["username"]}


def create_session(user_id: str, minutes: Optional[int] = None, db_path: Optional[str] = None) -> dict:
    """Crée une session opaque (`secrets.token_urlsafe`, jamais un JWT) associée à `user_id`."""
    init_db(db_path)
    session_id = secrets.token_urlsafe(32)
    now = _utcnow()
    expires_at = now + timedelta(minutes=minutes if minutes is not None else DEFAULT_SESSION_MINUTES)
    with closing(_get_connection(db_path)) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (session_id, user_id, now.isoformat(), expires_at.isoformat()),
        )
        conn.commit()
    return {"session_id": session_id, "expires_at": expires_at.isoformat()}


def get_valid_session(
    session_id: str,
    db_path: Optional[str] = None,
    banking_db_path: Optional[str] = None,
) -> Optional[dict]:
    """Retourne `{session_id, user_id, username, expires_at}` si la session existe et n'a pas expiré.

    L'ancien `sessions JOIN users` a été scindé en deux lectures : la table
    `sessions` reste dans `auth.db`, l'utilisateur est résolu dans la base
    bancaire (`UTILISATEUR_E_BANKING`) puis, à défaut, dans `auth.db.users`.
    Une session dont le `user_id` n'existe dans AUCUNE des deux sources est
    considérée comme orpheline et rejetée — sémantique identique à celle du
    JOIN précédent, qui ne renvoyait rien dans ce cas.

    La table `sessions` n'ayant pas changé, tout `session_id` déjà émis reste
    valide.
    """
    init_db(db_path)
    with closing(_get_connection(db_path)) as conn:
        row = conn.execute(
            "SELECT session_id, user_id, expires_at FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

    if row is None:
        return None

    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at <= _utcnow():
        return None

    account = _resolve_user_from_ebanking(row["user_id"], banking_db_path)
    if account is None:
        # --- Repli LEGACY : `auth.db.users` ---
        with closing(_get_connection(db_path)) as conn:
            legacy = conn.execute(
                "SELECT user_id, username FROM users WHERE user_id = ?", (row["user_id"],)
            ).fetchone()
        if legacy is None:
            return None
        account = {"user_id": legacy["user_id"], "username": legacy["username"]}

    return {
        "session_id": row["session_id"],
        "user_id": account["user_id"],
        "username": account["username"],
        "expires_at": row["expires_at"],
    }


def delete_session(session_id: str, db_path: Optional[str] = None) -> None:
    """Supprime une session (déconnexion). Silencieux si elle n'existe déjà plus."""
    init_db(db_path)
    with closing(_get_connection(db_path)) as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
