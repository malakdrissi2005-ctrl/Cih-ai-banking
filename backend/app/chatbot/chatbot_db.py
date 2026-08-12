"""Base SQLite applicative du chatbot — `backend/data/chatbot.db`.

**Phase 1 : schéma seul.** Ce module crée et expose les trois tables
`CHATBOT_SESSION`, `CHATBOT_MESSAGE`, `CHATBOT_EVALUATION`, mais AUCUN
composant applicatif ne les alimente encore : `backend/app/routers/chat.py`
n'est volontairement pas modifié à ce stade. Le branchement de l'écriture des
sessions et des messages fera l'objet d'une phase 2 distincte, validée
séparément.

Base **séparée** des deux autres (voir `banking_db.py` et
`security/session_manager.py`) :
- `demo_bancaire.db` — données métier bancaires (CLIENT, COMPTE_BANCAIRE…)
- `auth.db`          — sessions d'authentification uniquement
- `chatbot.db`       — traces conversationnelles (ce module)

SQLite n'autorisant pas de contrainte `FOREIGN KEY` entre fichiers distincts,
`CHATBOT_SESSION.id_utilisateur` référence `UTILISATEUR_E_BANKING.id_utilisateur`
**par valeur uniquement**, jamais par contrainte physique — même principe que
la liaison existante entre `auth.db` et la base bancaire.

Confidentialité (voir `CLAUDE.md` §5) : cette base conserve le TEXTE des
messages échangés. Elle ne doit donc jamais recevoir de secret — ni code OTP,
ni mot de passe, ni jeton de délégation complet, ni numéro de carte en clair.
`intention_detectee` et `score_confiance` sont des métadonnées de
classification, jamais des données bancaires.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Racine du dépôt (chatbot/chatbot_db.py -> chatbot -> app -> backend -> racine),
# même convention que `banking_db.py` et `security/session_manager.py` : un
# chemin relatif est résolu depuis la racine du monorepo, jamais depuis le
# répertoire courant du processus.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return str(path)


DEFAULT_DB_PATH = _resolve_path(os.getenv("CHATBOT_DB_PATH", "./backend/data/chatbot.db"))

# Valeurs autorisées, contrôlées par le schéma lui-même (CHECK) plutôt que
# laissées à la discrétion de l'appelant.
CANAUX = ("web", "mobile", "api")
EXPEDITEURS = ("client", "agent")
VOTES = ("positif", "negatif")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    resolved = _resolve_path(db_path) if db_path else DEFAULT_DB_PATH
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Crée les trois tables du chatbot — idempotent, jamais destructif."""
    with closing(_get_connection(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS CHATBOT_SESSION (
                id_session TEXT PRIMARY KEY,
                id_utilisateur TEXT,
                date_debut TEXT NOT NULL,
                date_fin TEXT,
                canal TEXT NOT NULL DEFAULT 'web' CHECK (canal IN ('web', 'mobile', 'api'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS CHATBOT_MESSAGE (
                id_message TEXT PRIMARY KEY,
                id_session TEXT NOT NULL,
                expediteur TEXT NOT NULL CHECK (expediteur IN ('client', 'agent')),
                texte_message TEXT NOT NULL,
                date_heure TEXT NOT NULL,
                intention_detectee TEXT,
                score_confiance TEXT,
                FOREIGN KEY (id_session) REFERENCES CHATBOT_SESSION(id_session)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS CHATBOT_EVALUATION (
                id_evaluation TEXT PRIMARY KEY,
                id_message TEXT NOT NULL,
                vote TEXT NOT NULL CHECK (vote IN ('positif', 'negatif')),
                commentaire TEXT,
                date_creation TEXT NOT NULL,
                FOREIGN KEY (id_message) REFERENCES CHATBOT_MESSAGE(id_message)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_session ON CHATBOT_MESSAGE(id_session, date_heure)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_utilisateur ON CHATBOT_SESSION(id_utilisateur)"
        )
        conn.commit()


def get_schema_info(db_path: Optional[str] = None) -> dict:
    """Retourne les tables présentes et le nombre de lignes de chacune.

    Utilitaire de vérification pour la phase 1 (schéma seul) : permet de
    constater que les tables existent et sont vides, sans avoir à ouvrir la
    base à la main.
    """
    init_db(db_path)
    with closing(_get_connection(db_path)) as conn:
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'CHATBOT_%' ORDER BY name"
            )
        ]
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}

    return {
        "db_path": _resolve_path(db_path) if db_path else DEFAULT_DB_PATH,
        "tables": tables,
        "counts": counts,
    }
