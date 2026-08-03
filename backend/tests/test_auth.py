"""Tests de l'authentification multi-utilisateur (session_id opaque, SQLite, sans JWT).

Utilise un fichier `users_seed.json` et une base de test isolés (tmp_path),
jamais les vrais `data/auth/users_seed.json` / `auth.db` du projet.
"""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.auth import get_auth_db_path
from app.security import session_manager

TEST_PASSWORD = "Demo1234!Test"

TEST_USERS = [
    {"user_id": "usr_t01", "username": "test_user_1", "display_name": "Test Un", "status": "active"},
    {"user_id": "usr_t02", "username": "test_user_2", "display_name": "Test Deux", "status": "active"},
    {"user_id": "usr_t03", "username": "test_user_3", "display_name": "Test Trois", "status": "active"},
]


@pytest.fixture(autouse=True)
def _demo_password_env(monkeypatch):
    monkeypatch.setenv("DEMO_DEFAULT_PASSWORD", TEST_PASSWORD)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "auth_test.db")


@pytest.fixture
def seed_path(tmp_path):
    path = tmp_path / "users_seed.json"
    path.write_text(json.dumps(TEST_USERS), encoding="utf-8")
    return path


@pytest.fixture
def seeded_db(seed_path, db_path):
    return session_manager.seed_users(seed_path=seed_path, db_path=db_path)


@pytest.fixture
def client(db_path):
    app.dependency_overrides[get_auth_db_path] = lambda: db_path
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_seed_imports_multiple_users(seed_path, db_path):
    stats = session_manager.seed_users(seed_path=seed_path, db_path=db_path)

    assert stats["total_entries"] == 3
    assert stats["inserted"] == 3
    assert stats["users_in_db"] == 3
    assert stats["sessions_in_db"] == 0  # aucune session creee pendant l'initialisation


def test_seed_rejects_duplicate_user_id(tmp_path, db_path):
    bad_seed = tmp_path / "bad_seed.json"
    bad_seed.write_text(
        json.dumps(
            [
                {"user_id": "usr_dup", "username": "alice", "display_name": "Alice", "status": "active"},
                {"user_id": "usr_dup", "username": "bob", "display_name": "Bob", "status": "active"},
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(session_manager.UsersSeedValidationError):
        session_manager.seed_users(seed_path=bad_seed, db_path=db_path)


def test_seed_rejects_duplicate_username(tmp_path, db_path):
    bad_seed = tmp_path / "bad_seed.json"
    bad_seed.write_text(
        json.dumps(
            [
                {"user_id": "usr_a", "username": "meme_username", "display_name": "A", "status": "active"},
                {"user_id": "usr_b", "username": "meme_username", "display_name": "B", "status": "active"},
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(session_manager.UsersSeedValidationError):
        session_manager.seed_users(seed_path=bad_seed, db_path=db_path)


def test_reseeding_does_not_create_duplicates(seed_path, db_path):
    session_manager.seed_users(seed_path=seed_path, db_path=db_path)
    stats_second_run = session_manager.seed_users(seed_path=seed_path, db_path=db_path)

    assert stats_second_run["inserted"] == 0
    assert stats_second_run["updated"] == 3
    assert stats_second_run["users_in_db"] == 3

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        distinct_user_ids = conn.execute("SELECT COUNT(DISTINCT user_id) FROM users").fetchone()[0]
        distinct_usernames = conn.execute("SELECT COUNT(DISTINCT username) FROM users").fetchone()[0]

    assert count == 3
    assert distinct_user_ids == 3
    assert distinct_usernames == 3


def test_login_works_for_several_different_users(seeded_db, client):
    response_1 = client.post("/api/auth/login", json={"username": "test_user_1", "password": TEST_PASSWORD})
    response_2 = client.post("/api/auth/login", json={"username": "test_user_2", "password": TEST_PASSWORD})

    assert response_1.status_code == 200
    assert response_2.status_code == 200
    assert response_1.json()["session_id"] != response_2.json()["session_id"]


def test_login_rejects_unknown_username(seeded_db, client):
    response = client.post("/api/auth/login", json={"username": "utilisateur_inconnu", "password": TEST_PASSWORD})

    assert response.status_code == 401


def test_login_rejects_wrong_password(seeded_db, client):
    response = client.post("/api/auth/login", json={"username": "test_user_1", "password": "mauvais-mot-de-passe"})

    assert response.status_code == 401


def test_session_is_associated_with_the_correct_user(seeded_db, client):
    login_1 = client.post("/api/auth/login", json={"username": "test_user_1", "password": TEST_PASSWORD})
    login_2 = client.post("/api/auth/login", json={"username": "test_user_2", "password": TEST_PASSWORD})

    session_1 = client.get(
        "/api/auth/session", headers={"Authorization": f"Bearer {login_1.json()['session_id']}"}
    ).json()
    session_2 = client.get(
        "/api/auth/session", headers={"Authorization": f"Bearer {login_2.json()['session_id']}"}
    ).json()

    assert session_1["user_id"] == "usr_t01"
    assert session_1["username"] == "test_user_1"
    assert session_2["user_id"] == "usr_t02"
    assert session_2["username"] == "test_user_2"


def test_passwords_are_never_stored_in_clear(seeded_db, db_path):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT username, password_hash FROM users").fetchall()

    assert len(rows) == 3
    for username, password_hash in rows:
        assert password_hash != TEST_PASSWORD
        assert TEST_PASSWORD not in password_hash
        assert password_hash.startswith("$2b$")


def test_missing_default_password_env_fails_loudly(monkeypatch, seed_path, db_path):
    monkeypatch.delenv("DEMO_DEFAULT_PASSWORD", raising=False)

    with pytest.raises(RuntimeError):
        session_manager.seed_users(seed_path=seed_path, db_path=db_path)
