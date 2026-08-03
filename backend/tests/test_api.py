"""Tests de l'API FastAPI (`POST /api/chat`, `GET /health`, page de démonstration `GET /`)."""
import json

from fastapi.testclient import TestClient

from agents.agent1_faq.rag import get_faq_collection
from app.banking import banking_db
from app.main import app
from app.routers.auth import get_auth_db_path
from app.routers.chat import get_banking_db_path_dependency, get_faq_collection_dependency, get_use_llm_router_dependency
from app.security import session_manager
from scripts.ingest_faq import ingest_faq


def _override_with_populated_collection(tmp_path):
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(
        json.dumps(
            [{"question": "Quels sont les frais de tenue de compte ?", "answer": "Gratuit pour les moins de 26 ans."}]
        ),
        encoding="utf-8",
    )
    persist_dir = str(tmp_path / "chroma")
    ingest_faq(faq_path=faq_path, persist_dir=persist_dir, collection_name="faq_api_test")
    collection = get_faq_collection(persist_dir=persist_dir, collection_name="faq_api_test")
    app.dependency_overrides[get_faq_collection_dependency] = lambda: collection
    # Le LLM Router (voir agents/agent1_faq/llm_router.py) reste désactivé pour
    # ces tests API : ils doivent rester rapides et hermétiques, sans dépendre
    # d'un service Ollama réellement disponible sur la machine d'exécution.
    # Couvert séparément (mocké) par backend/tests/test_llm_router.py.
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: False


def _create_session_for(tmp_path, user_id: str, username: str) -> tuple[str, str]:
    """Crée une session valide isolée (auth.db de test) et retourne (session_id, auth_db_path)."""
    auth_db_path = str(tmp_path / "auth_api_test.db")
    seed_path = tmp_path / "users_seed.json"
    seed_path.write_text(
        json.dumps([{"user_id": user_id, "username": username, "display_name": username, "status": "active"}]),
        encoding="utf-8",
    )
    session_manager.seed_users(seed_path=seed_path, db_path=auth_db_path, default_password="Demo1234!Test")
    user = session_manager.verify_credentials(username, "Demo1234!Test", db_path=auth_db_path)
    session = session_manager.create_session(user_id=user["user_id"], db_path=auth_db_path)
    app.dependency_overrides[get_auth_db_path] = lambda: auth_db_path
    return session["session_id"], auth_db_path


def _override_banking_db(tmp_path) -> str:
    banking_path = str(tmp_path / "banking_api_test.db")
    banking_db.seed_banking_data(db_path=banking_path)
    app.dependency_overrides[get_banking_db_path_dependency] = lambda: banking_path
    return banking_path


def test_chat_endpoint_public_question(tmp_path):
    _override_with_populated_collection(tmp_path)
    try:
        client = TestClient(app)
        response = client.post("/api/chat", json={"message": "Quels sont les frais de tenue de compte ?"})

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "faq_generale"
        assert data["requires_auth"] is False
        assert "Gratuit" in data["response"]
    finally:
        app.dependency_overrides.clear()


def test_chat_endpoint_personal_question_blocked_without_session(tmp_path):
    _override_with_populated_collection(tmp_path)
    try:
        client = TestClient(app)
        response = client.post("/api/chat", json={"message": "Quel est mon solde ?"})

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "personal_data"
        assert data["requires_auth"] is True
    finally:
        app.dependency_overrides.clear()


def test_chat_endpoint_personal_question_blocked_with_invalid_session(tmp_path):
    _override_with_populated_collection(tmp_path)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/chat",
            json={"message": "Quel est mon solde ?"},
            headers={"Authorization": "Bearer token-invalide"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["requires_auth"] is True
    finally:
        app.dependency_overrides.clear()


def test_chat_endpoint_virement_unavailable(tmp_path):
    _override_with_populated_collection(tmp_path)
    try:
        client = TestClient(app)
        response = client.post("/api/chat", json={"message": "Je veux virer 500 DH à Youssef"})

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "virement"
        assert data["response"] == "Ce service n'est pas disponible pour le moment."
    finally:
        app.dependency_overrides.clear()


def test_chat_endpoint_account_action_unavailable(tmp_path):
    _override_with_populated_collection(tmp_path)
    session_id, _ = _create_session_for(tmp_path, "usr_001", "client001")
    _override_banking_db(tmp_path)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/chat",
            json={"message": "Peux-tu augmenter le plafond de ma carte ?"},
            headers={"Authorization": f"Bearer {session_id}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "compte_action"
        assert data["response"] == "Ce service n'est pas disponible pour le moment."
    finally:
        app.dependency_overrides.clear()


def test_chat_endpoint_personal_question_with_valid_session(tmp_path):
    _override_with_populated_collection(tmp_path)
    session_id, _ = _create_session_for(tmp_path, "usr_001", "client001")
    _override_banking_db(tmp_path)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/chat",
            json={"message": "Combien me reste-t-il au total ?"},
            headers={"Authorization": f"Bearer {session_id}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "personal_data"
        assert data["requires_auth"] is False
        assert "45730.50" in data["response"]  # 15230.50 (courant) + 30500.00 (carnet) pour usr_001
    finally:
        app.dependency_overrides.clear()


def test_chat_endpoint_isolates_data_between_users(tmp_path):
    _override_with_populated_collection(tmp_path)
    _override_banking_db(tmp_path)

    session_1, _ = _create_session_for(tmp_path, "usr_001", "client001")
    client = TestClient(app)
    response_1 = client.post(
        "/api/chat",
        json={"message": "Combien me reste-t-il au total ?"},
        headers={"Authorization": f"Bearer {session_1}"},
    )

    session_2, _ = _create_session_for(tmp_path, "usr_002", "client002")
    response_2 = client.post(
        "/api/chat",
        json={"message": "Combien me reste-t-il au total ?"},
        headers={"Authorization": f"Bearer {session_2}"},
    )

    try:
        assert response_1.json()["response"] != response_2.json()["response"]
        assert "45730.50" in response_1.json()["response"]
        assert "11094.10" in response_2.json()["response"]  # 2894.10 + 8200.00 pour usr_002
    finally:
        app.dependency_overrides.clear()


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_demo_page_served():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "CIH AI Banking" in response.text
