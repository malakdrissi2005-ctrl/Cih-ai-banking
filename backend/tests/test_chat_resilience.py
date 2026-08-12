"""Résilience de `POST /api/chat` — l'assistant ne doit jamais renvoyer 500.

NON-RÉGRESSION D'UNE PANNE RÉELLE : après le passage à l'embedding v2
(stemming + 1024 dimensions), un `chroma_db/` resté à l'ancien format faisait
lever `FaqEmbeddingDimensionMismatchError` DANS la dépendance FastAPI
`get_faq_collection_dependency`. Une dépendance étant résolue avant le corps
de l'endpoint, l'exception produisait un **HTTP 500 sur toutes les requêtes**
`/api/chat` — y compris les questions personnelles et les refus d'opération
sensible, qui n'utilisent pourtant jamais ChromaDB. Le frontend affichait
« Le service de l'assistant est temporairement indisponible. »

Principe défendu ici (`CLAUDE.md`) : un index FAQ périmé est un problème de
DONNÉES, réparable par une commande. Il ne doit jamais mettre l'assistant
entier hors service, ni faire disparaître les garanties de sécurité.
"""
import pytest
from fastapi.testclient import TestClient

from agents.agent1_faq.graph import run_agent1
from agents.agent1_faq.rag import FaqEmbeddingDimensionMismatchError
from app.main import app
from app.routers.chat import (
    get_banking_db_path_dependency,
    get_faq_collection_dependency,
    get_use_llm_router_dependency,
)


def _raise_obsolete_index():
    """Simule un `chroma_db/` créé par une version précédente de l'embedding."""
    raise FaqEmbeddingDimensionMismatchError(
        "La collection ChromaDB 'faq_generale' a été créée par une version précédente "
        "de l'embedding FAQ. Ré-ingérez la FAQ : python scripts/ingest_faq.py"
    )


@pytest.fixture
def client_with_obsolete_index(tmp_path, monkeypatch):
    """Client HTTP dont l'index vectoriel est inutilisable.

    La panne est simulée à sa VRAIE source : `rag.get_faq_collection`, telle
    qu'importée par `app.routers.chat`. Surcharger la dépendance
    `get_faq_collection_dependency` via `dependency_overrides` remplacerait la
    fonction entière et court-circuiterait précisément le `try/except` que ce
    fichier doit valider — le test ne prouverait alors rien.
    """
    import app.routers.chat as chat_module
    from app.banking import banking_db

    banking_path = str(tmp_path / "banking.db")
    banking_db.seed_banking_data(db_path=banking_path)

    monkeypatch.setattr(chat_module, "get_faq_collection", _raise_obsolete_index)
    # Le repli de `graph.py` doit lui aussi tenir si le nœud FAQ tente une
    # résolution directe.
    monkeypatch.setattr("agents.agent1_faq.graph.get_faq_collection", _raise_obsolete_index)

    app.dependency_overrides[get_banking_db_path_dependency] = lambda: banking_path
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: False
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "message",
    [
        "J'ai oublié mon mot de passe",          # suggestion FAQ — le cas signalé
        "Quels documents pour ouvrir un compte ?",
        "Quel est mon solde ?",                   # personnel — n'utilise pas ChromaDB
        "Je veux virer 500 dh",                   # sensible — n'utilise pas ChromaDB
        "Bonjour",
    ],
)
def test_chat_never_returns_500_when_the_faq_index_is_obsolete(client_with_obsolete_index, message):
    """LE test de non-régression : plus jamais de 500 à cause de l'index FAQ."""
    response = client_with_obsolete_index.post("/api/chat", json={"message": message})
    assert response.status_code == 200
    assert response.json()["response"]


def test_personal_questions_still_require_authentication_with_obsolete_index(client_with_obsolete_index):
    """La dégradation de la FAQ ne doit RIEN relâcher côté sécurité."""
    payload = client_with_obsolete_index.post(
        "/api/chat", json={"message": "Quel est mon solde ?"}
    ).json()
    assert payload["requires_auth"] is True
    assert "connecter" in payload["response"].lower()


@pytest.mark.parametrize("message", ["Je veux virer 500 dh", "Bloque ma carte", "Augmente mon plafond"])
def test_sensitive_operations_still_blocked_with_obsolete_index(client_with_obsolete_index, message):
    payload = client_with_obsolete_index.post("/api/chat", json={"message": message}).json()
    assert payload["intent"] in ("virement", "compte_action")
    assert payload["response"] == "Ce service n'est pas disponible pour le moment."


def test_faq_degrades_gracefully_instead_of_crashing(client_with_obsolete_index):
    """Une question FAQ reçoit le message « aucune réponse trouvée », jamais une
    erreur technique ni une trace d'exception."""
    payload = client_with_obsolete_index.post(
        "/api/chat", json={"message": "Quels documents pour ouvrir un compte ?"}
    ).json()
    assert payload["intent"] == "faq_generale"
    reponse = payload["response"]
    for fuite in ("Traceback", "Error", "Exception", "chroma", "500"):
        assert fuite.lower() not in reponse.lower()


def test_run_agent1_tolerates_an_unusable_collection(monkeypatch, tmp_path):
    """Appel direct (scripts, tests, outils) : `run_agent1` ne doit pas planter
    non plus quand l'index est inutilisable — voir
    `graph._resolve_faq_collection`."""
    from agents.agent1_faq import graph

    monkeypatch.setattr(graph, "get_faq_collection", _raise_obsolete_index)
    result = run_agent1("Quels documents pour ouvrir un compte ?", use_llm_router=False)
    assert result["intent"] == "faq_generale"
    assert result["response"]


def test_a_valid_collection_is_still_used_normally(tmp_path):
    """Contrepartie : le correctif ne doit pas désactiver la FAQ quand l'index
    est sain."""
    from agents.agent1_faq.rag import get_faq_collection
    from scripts.ingest_faq import ingest_faq

    persist_dir = str(tmp_path / "chroma_ok")
    ingest_faq(persist_dir=persist_dir, collection_name="faq_resilience_test")
    collection = get_faq_collection(persist_dir=persist_dir, collection_name="faq_resilience_test")

    app.dependency_overrides[get_faq_collection_dependency] = lambda: collection
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: False
    try:
        payload = TestClient(app).post(
            "/api/chat", json={"message": "Quels documents pour ouvrir un compte ?"}
        ).json()
        assert payload["intent"] == "faq_generale"
        # Une vraie réponse FAQ, pas le message de repli.
        assert "Aucune réponse" not in payload["response"]
    finally:
        app.dependency_overrides.clear()
