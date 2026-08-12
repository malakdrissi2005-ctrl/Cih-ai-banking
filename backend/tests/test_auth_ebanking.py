"""Authentification via `UTILISATEUR_E_BANKING` (base bancaire métier).

Vérifie la résolution à DEUX SOURCES mise en place à l'étape 4 :
1. `UTILISATEUR_E_BANKING`, dans la base bancaire (source cible),
2. `auth.db.users` (LEGACY, repli de transition).

Et surtout que la bascule ne casse rien : la table `sessions` reste dans
`auth.db`, tout `session_id` déjà émis reste valide, et bcrypt demeure la
seule porte de vérification sur les deux chemins.

Bases isolées par test (tmp_path) — jamais les vraies bases du projet.
"""
import sqlite3

import bcrypt
import pytest

from app.banking import banking_db
from app.security import session_manager

DEMO_PASSWORD = "UnivEnsam20242025?!"
WRONG_PASSWORD = "MauvaisMotDePasse!123"


@pytest.fixture
def banking_path(tmp_path):
    """Base bancaire contenant un client et son compte d'accès en ligne."""
    path = str(tmp_path / "demo_bancaire_test.db")
    banking_db.init_db(db_path=path)

    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO CLIENT (id_client, nom, prenom, telephone_mobile, email, statut_client, date_creation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("CL0001", "Drissi", "Malak", "0690184186", "malakdrissi2005@gmail.com", "actif", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()

    # Le hash est produit par bcrypt ; le mot de passe clair ne quitte jamais ce test.
    banking_db.upsert_ebanking_user(
        id_utilisateur="EB0001",
        id_client="CL0001",
        identifiant_connexion="malak.drissi",
        mot_de_passe_hash=bcrypt.hashpw(DEMO_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        db_path=path,
    )
    return path


@pytest.fixture
def auth_path(tmp_path):
    path = str(tmp_path / "auth_test.db")
    session_manager.init_db(db_path=path)
    return path


# ---------------------------------------------------------------------------
# 1. Connexion par identifiant ET par e-mail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("login", ["malak.drissi", "malakdrissi2005@gmail.com"])
def test_login_works_with_identifier_and_with_email(auth_path, banking_path, login):
    user = session_manager.verify_credentials(
        login, DEMO_PASSWORD, db_path=auth_path, banking_db_path=banking_path
    )
    assert user is not None
    # `user_id` porte l'ID CLIENT (`CL0001`), jamais l'ID du compte d'accès
    # (`EB0001`) : c'est lui qui indexe toutes les lectures bancaires.
    assert user["user_id"] == "CL0001"


@pytest.mark.parametrize("login", ["Malak.Drissi", "MalakDrissi2005@GMAIL.com"])
def test_login_is_case_insensitive(auth_path, banking_path, login):
    """Un e-mail saisi avec des majuscules doit retrouver le compte."""
    user = session_manager.verify_credentials(
        login, DEMO_PASSWORD, db_path=auth_path, banking_db_path=banking_path
    )
    assert user is not None
    # `user_id` porte l'ID CLIENT (`CL0001`), jamais l'ID du compte d'accès
    # (`EB0001`) : c'est lui qui indexe toutes les lectures bancaires.
    assert user["user_id"] == "CL0001"


def test_wrong_password_is_rejected(auth_path, banking_path):
    assert (
        session_manager.verify_credentials(
            "malakdrissi2005@gmail.com", WRONG_PASSWORD, db_path=auth_path, banking_db_path=banking_path
        )
        is None
    )


def test_unknown_login_is_rejected(auth_path, banking_path):
    assert (
        session_manager.verify_credentials(
            "inconnu@example.invalid", DEMO_PASSWORD, db_path=auth_path, banking_db_path=banking_path
        )
        is None
    )


def test_blocked_account_cannot_log_in_even_with_correct_password(auth_path, banking_path):
    """`statut_connexion` != 'actif' interdit la connexion, mot de passe correct ou non."""
    with sqlite3.connect(banking_path) as conn:
        conn.execute("UPDATE UTILISATEUR_E_BANKING SET statut_connexion = 'bloque' WHERE id_utilisateur = 'EB0001'")
        conn.commit()

    assert (
        session_manager.verify_credentials(
            "malak.drissi", DEMO_PASSWORD, db_path=auth_path, banking_db_path=banking_path
        )
        is None
    )


# ---------------------------------------------------------------------------
# 2. bcrypt — jamais de mot de passe en clair
# ---------------------------------------------------------------------------


def test_password_is_stored_as_a_bcrypt_hash_never_in_clear(banking_path):
    with sqlite3.connect(banking_path) as conn:
        stored = conn.execute(
            "SELECT mot_de_passe_hash FROM UTILISATEUR_E_BANKING WHERE id_utilisateur = 'EB0001'"
        ).fetchone()[0]

    assert DEMO_PASSWORD not in stored
    assert stored.startswith("$2b$")  # préfixe bcrypt
    assert bcrypt.checkpw(DEMO_PASSWORD.encode("utf-8"), stored.encode("utf-8"))


def test_no_table_of_the_banking_database_contains_the_clear_password(banking_path):
    """Balayage exhaustif : le mot de passe clair ne doit apparaître nulle part."""
    with sqlite3.connect(banking_path) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
            for row in rows:
                assert DEMO_PASSWORD not in " ".join(str(value) for value in row)


def test_last_login_is_recorded_on_success_only(auth_path, banking_path):
    def _last_login():
        with sqlite3.connect(banking_path) as conn:
            return conn.execute(
                "SELECT derniere_connexion FROM UTILISATEUR_E_BANKING WHERE id_utilisateur = 'EB0001'"
            ).fetchone()[0]

    assert _last_login() is None
    session_manager.verify_credentials(
        "malak.drissi", WRONG_PASSWORD, db_path=auth_path, banking_db_path=banking_path
    )
    assert _last_login() is None  # échec : pas d'horodatage

    session_manager.verify_credentials(
        "malak.drissi", DEMO_PASSWORD, db_path=auth_path, banking_db_path=banking_path
    )
    assert _last_login() is not None


# ---------------------------------------------------------------------------
# 3. Sessions — compatibilité et résolution à deux sources
# ---------------------------------------------------------------------------


def test_session_created_for_an_ebanking_user_resolves_correctly(auth_path, banking_path):
    user = session_manager.verify_credentials(
        "malakdrissi2005@gmail.com", DEMO_PASSWORD, db_path=auth_path, banking_db_path=banking_path
    )
    created = session_manager.create_session(user_id=user["user_id"], db_path=auth_path)

    session = session_manager.get_valid_session(
        created["session_id"], db_path=auth_path, banking_db_path=banking_path
    )
    assert session is not None
    assert session["user_id"] == "CL0001"
    assert session["username"] == "malak.drissi"


def test_sessions_table_is_unchanged_and_still_lives_in_auth_db(auth_path, banking_path):
    """La table `sessions` ne bouge pas : ni de fichier, ni de schéma."""
    user = session_manager.verify_credentials(
        "malak.drissi", DEMO_PASSWORD, db_path=auth_path, banking_db_path=banking_path
    )
    session_manager.create_session(user_id=user["user_id"], db_path=auth_path)

    with sqlite3.connect(auth_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        assert columns == {"session_id", "user_id", "created_at", "expires_at"}
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1

    # La base bancaire ne contient AUCUNE table de session.
    with sqlite3.connect(banking_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "sessions" not in tables


def test_legacy_auth_db_user_still_works_without_any_banking_database(auth_path, tmp_path):
    """REPLI LEGACY : un utilisateur présent uniquement dans `auth.db.users`
    continue de se connecter et sa session de se résoudre, exactement comme
    avant l'étape 4. C'est ce qui protège l'existant pendant la bascule."""
    import json

    seed_path = tmp_path / "users_seed.json"
    seed_path.write_text(
        json.dumps([{"user_id": "usr_001", "username": "client001", "display_name": "Client Démo 1", "status": "active"}]),
        encoding="utf-8",
    )
    session_manager.seed_users(seed_path=seed_path, db_path=auth_path, default_password="Demo1234!Test")

    user = session_manager.verify_credentials("client001", "Demo1234!Test", db_path=auth_path)
    assert user is not None and user["user_id"] == "usr_001"

    created = session_manager.create_session(user_id="usr_001", db_path=auth_path)
    session = session_manager.get_valid_session(created["session_id"], db_path=auth_path)
    assert session is not None
    assert session["user_id"] == "usr_001"
    assert session["username"] == "client001"


def test_session_issued_before_the_migration_remains_valid(auth_path, banking_path, tmp_path):
    """Une session émise AVANT l'étape 4 (utilisateur legacy) doit rester
    valide même une fois la base bancaire branchée."""
    import json

    seed_path = tmp_path / "users_seed.json"
    seed_path.write_text(
        json.dumps([{"user_id": "usr_001", "username": "client001", "display_name": "Client Démo 1", "status": "active"}]),
        encoding="utf-8",
    )
    session_manager.seed_users(seed_path=seed_path, db_path=auth_path, default_password="Demo1234!Test")
    created = session_manager.create_session(user_id="usr_001", db_path=auth_path)

    session = session_manager.get_valid_session(
        created["session_id"], db_path=auth_path, banking_db_path=banking_path
    )
    assert session is not None
    assert session["user_id"] == "usr_001"


def test_orphan_session_is_rejected(auth_path, banking_path):
    """Sémantique conservée : une session dont l'utilisateur n'existe dans
    aucune des deux sources est rejetée — comme le faisait l'ancien JOIN."""
    created = session_manager.create_session(user_id="utilisateur_inexistant", db_path=auth_path)
    assert (
        session_manager.get_valid_session(
            created["session_id"], db_path=auth_path, banking_db_path=banking_path
        )
        is None
    )


def test_expired_session_is_rejected(auth_path, banking_path):
    user = session_manager.verify_credentials(
        "malak.drissi", DEMO_PASSWORD, db_path=auth_path, banking_db_path=banking_path
    )
    created = session_manager.create_session(user_id=user["user_id"], minutes=-1, db_path=auth_path)
    assert (
        session_manager.get_valid_session(
            created["session_id"], db_path=auth_path, banking_db_path=banking_path
        )
        is None
    )


def test_ebanking_source_takes_precedence_over_legacy(auth_path, banking_path, tmp_path):
    """Si le même identifiant existe dans les deux sources, la base bancaire
    (source cible) l'emporte."""
    import json

    seed_path = tmp_path / "users_seed.json"
    seed_path.write_text(
        json.dumps([{"user_id": "usr_legacy", "username": "malak.drissi", "display_name": "Doublon", "status": "active"}]),
        encoding="utf-8",
    )
    session_manager.seed_users(seed_path=seed_path, db_path=auth_path, default_password="AutreMotDePasse!1")

    user = session_manager.verify_credentials(
        "malak.drissi", DEMO_PASSWORD, db_path=auth_path, banking_db_path=banking_path
    )
    assert user is not None
    # `user_id` porte l'ID CLIENT (`CL0001`), jamais l'ID du compte d'accès
    # (`EB0001`) : c'est lui qui indexe toutes les lectures bancaires.
    assert user["user_id"] == "CL0001"  # et non "usr_legacy"


def test_upsert_ebanking_user_is_idempotent(banking_path):
    outcome = banking_db.upsert_ebanking_user(
        id_utilisateur="EB0001",
        id_client="CL0001",
        identifiant_connexion="malak.drissi",
        mot_de_passe_hash="$2b$12$placeholderplaceholderplaceholderplaceholderplaceholderab",
        db_path=banking_path,
    )
    assert outcome == "updated"

    with sqlite3.connect(banking_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM UTILISATEUR_E_BANKING").fetchone()[0] == 1
