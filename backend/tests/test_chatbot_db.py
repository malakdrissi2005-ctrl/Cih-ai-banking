"""Tests du schéma de la base chatbot (backend/app/chatbot/chatbot_db.py).

PHASE 1 — schéma seul. Ces tests vérifient que les tables existent, que leurs
contraintes tiennent, et surtout qu'AUCUNE écriture automatique n'a lieu :
`chat.py` n'est volontairement pas branché à ce stade.

Base isolée par test (tmp_path) — jamais le vrai `backend/data/chatbot.db`.
"""
import sqlite3
import uuid
from pathlib import Path

import pytest

from app.chatbot import chatbot_db


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "chatbot_test.db")


def test_init_creates_the_database_file(db_path):
    assert not Path(db_path).exists()
    chatbot_db.init_db(db_path=db_path)
    assert Path(db_path).exists()


def test_init_creates_the_three_expected_tables(db_path):
    chatbot_db.init_db(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {"CHATBOT_SESSION", "CHATBOT_MESSAGE", "CHATBOT_EVALUATION"}.issubset(tables)


def test_init_is_idempotent(db_path):
    chatbot_db.init_db(db_path=db_path)
    chatbot_db.init_db(db_path=db_path)  # ne doit jamais lever ni dupliquer

    info = chatbot_db.get_schema_info(db_path=db_path)
    assert info["counts"] == {"CHATBOT_SESSION": 0, "CHATBOT_MESSAGE": 0, "CHATBOT_EVALUATION": 0}


def test_tables_are_empty_phase_1_writes_nothing_automatically(db_path):
    """PHASE 1 : le schéma existe mais rien ne l'alimente encore.

    Ce test verrouille la décision : si quelqu'un branche l'écriture dans
    `chat.py` sans passer par la phase 2, ce test le signalera."""
    info = chatbot_db.get_schema_info(db_path=db_path)
    assert sum(info["counts"].values()) == 0


def test_chat_router_does_not_import_chatbot_db_yet():
    """Contrôle explicite de la phase 1 : `chat.py` ne doit pas encore
    dépendre de la base chatbot."""
    source = (Path(__file__).resolve().parents[1] / "app" / "routers" / "chat.py").read_text(encoding="utf-8")
    assert "chatbot_db" not in source


# ---------------------------------------------------------------------------
# Contraintes du schéma — vérifiées par écriture manuelle (jamais par le code
# applicatif, qui n'écrit pas encore).
# ---------------------------------------------------------------------------


def _insert_session(conn, canal="web", id_utilisateur="usr_001"):
    session_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO CHATBOT_SESSION (id_session, id_utilisateur, date_debut, canal) VALUES (?, ?, ?, ?)",
        (session_id, id_utilisateur, "2026-07-28T10:00:00+00:00", canal),
    )
    return session_id


def test_session_accepts_known_channels_and_rejects_unknown(db_path):
    chatbot_db.init_db(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        for canal in chatbot_db.CANAUX:
            _insert_session(conn, canal=canal)

        with pytest.raises(sqlite3.IntegrityError):
            _insert_session(conn, canal="pigeon-voyageur")


def test_message_sender_is_constrained(db_path):
    chatbot_db.init_db(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        session_id = _insert_session(conn)
        for expediteur in chatbot_db.EXPEDITEURS:
            conn.execute(
                "INSERT INTO CHATBOT_MESSAGE (id_message, id_session, expediteur, texte_message, date_heure) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), session_id, expediteur, "bonjour", "2026-07-28T10:00:01+00:00"),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO CHATBOT_MESSAGE (id_message, id_session, expediteur, texte_message, date_heure) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), session_id, "inconnu", "bonjour", "2026-07-28T10:00:02+00:00"),
            )


def test_evaluation_vote_is_constrained(db_path):
    chatbot_db.init_db(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        session_id = _insert_session(conn)
        message_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO CHATBOT_MESSAGE (id_message, id_session, expediteur, texte_message, date_heure) "
            "VALUES (?, ?, ?, ?, ?)",
            (message_id, session_id, "agent", "voici votre solde", "2026-07-28T10:00:03+00:00"),
        )

        for vote in chatbot_db.VOTES:
            conn.execute(
                "INSERT INTO CHATBOT_EVALUATION (id_evaluation, id_message, vote, date_creation) "
                "VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), message_id, vote, "2026-07-28T10:00:04+00:00"),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO CHATBOT_EVALUATION (id_evaluation, id_message, vote, date_creation) "
                "VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), message_id, "moyen", "2026-07-28T10:00:05+00:00"),
            )


def test_message_can_store_intent_and_confidence_metadata(db_path):
    """`intention_detectee` / `score_confiance` : métadonnées de
    classification, jamais des données bancaires."""
    chatbot_db.init_db(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        session_id = _insert_session(conn)
        message_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO CHATBOT_MESSAGE (id_message, id_session, expediteur, texte_message, date_heure, "
            "intention_detectee, score_confiance) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, session_id, "client", "quel est mon solde", "2026-07-28T10:00:06+00:00",
             "total_balance", "0.92"),
        )
        row = conn.execute(
            "SELECT intention_detectee, score_confiance FROM CHATBOT_MESSAGE WHERE id_message = ?",
            (message_id,),
        ).fetchone()

    assert row == ("total_balance", "0.92")


def test_chatbot_db_is_separate_from_banking_and_auth(db_path, tmp_path):
    """Séparation stricte des trois bases : la base chatbot ne doit contenir
    aucune table bancaire ni d'authentification."""
    chatbot_db.init_db(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert not {"CLIENT", "COMPTE_BANCAIRE", "CARTE_BANCAIRE", "TRANSACTION", "users", "sessions"} & tables
