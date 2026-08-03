"""Tests du General Agent (Gemini) et du Router top-level (`agents/router/`).

Couvre :
1. Une question bancaire n'appelle jamais Gemini (le Router délègue
   entièrement au Banking Agent existant, `agents.agent1_faq.graph.run_agent1`,
   jamais modifié).
2. Une question générale appelle Gemini, jamais `banking_db`/ChromaDB/le
   Security Guard (`run_agent1` n'est jamais invoqué).
3. `GOOGLE_API_KEY` manquante retourne une erreur claire, à la fois au niveau
   du client Gemini (exception typée) et du General Agent (message clair,
   jamais un crash ni une erreur HTTP 500 opaque).

Tous les appels réseau (Ollama, Gemini) sont mockés ici — même convention que
`test_llm_first_routing.py`/`test_mistral_primary_architecture.py` : suite
rapide et déterministe, jamais un service réel.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.general_agent import gemini_client
from agents.general_agent.general_agent import (
    GEMINI_NOT_CONFIGURED_MESSAGE,
    GENERAL_AGENT_UNAVAILABLE_MESSAGE,
    run_general_agent,
)
from agents.general_agent.gemini_client import GeminiClient, GeminiNotConfiguredError, GeminiRequestError
from agents.router import conversational_understanding, router
from agents.router.conversational_understanding import _validate_and_normalize, classify_domain
from app.main import app
from app.routers.chat import get_use_llm_router_dependency


# ---------------------------------------------------------------------------
# 1. Conversational Understanding (domaine) — repli déterministe garanti,
#    "needs_web" toujours forcé à False.
# ---------------------------------------------------------------------------


def test_classify_domain_defaults_to_banking_without_llm(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("_classify_with_llm ne doit pas etre appele quand use_llm_router=False")

    monkeypatch.setattr(conversational_understanding, "_classify_with_llm", _fail)
    result = classify_domain("Qui est Albert Einstein ?", use_llm_router=False)
    assert result == {"domain": "banking", "intent": "unclear", "needs_web": False}


def test_classify_domain_uses_llm_when_enabled(monkeypatch):
    monkeypatch.setattr(
        conversational_understanding,
        "_classify_with_llm",
        lambda *a, **k: {"domain": "general", "intent": "knowledge_question", "needs_web": False},
    )
    result = classify_domain("Explique-moi la blockchain", use_llm_router=True)
    assert result["domain"] == "general"
    assert result["needs_web"] is False


def test_classify_domain_falls_back_to_banking_when_llm_fails(monkeypatch):
    monkeypatch.setattr(conversational_understanding, "_classify_with_llm", lambda *a, **k: None)
    result = classify_domain("ch7al 3ndi fl compte", use_llm_router=True)
    assert result["domain"] == "banking"


def test_validate_and_normalize_forces_needs_web_false_regardless_of_llm_output():
    # Architecture preparee pour une future recherche web (non implementee) :
    # "needs_web" n'est JAMAIS lu depuis la sortie LLM.
    result = _validate_and_normalize({"domain": "general", "intent": "knowledge_question", "needs_web": True})
    assert result == {"domain": "general", "intent": "knowledge_question", "needs_web": False}


def test_validate_and_normalize_rejects_invalid_domain():
    assert _validate_and_normalize({"domain": "other", "intent": "x"}) is None
    assert _validate_and_normalize({"domain": "banking"}) == {"domain": "banking", "intent": "unclear", "needs_web": False}
    assert _validate_and_normalize("not a dict") is None


# ---------------------------------------------------------------------------
# 2. Router : une question bancaire n'appelle JAMAIS Gemini ; une question
#    generale n'appelle JAMAIS le Banking Agent (banking_db/ChromaDB/Security
#    Guard).
# ---------------------------------------------------------------------------


def test_router_banking_question_never_calls_gemini(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("GeminiClient.generate ne doit jamais etre appele pour une question bancaire")

    monkeypatch.setattr(GeminiClient, "generate", _fail)
    # use_llm_router=False -> repli deterministe garanti sur domain="banking".
    result = router.route_message("Quel est mon solde ?", is_authenticated=False, use_llm_router=False)
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is True


def test_router_general_question_calls_gemini_never_banking_agent(monkeypatch):
    monkeypatch.setattr(
        router,
        "classify_domain",
        lambda *a, **k: {"domain": "general", "intent": "knowledge_question", "needs_web": False},
    )

    def _fail(*args, **kwargs):
        raise AssertionError("run_agent1 ne doit jamais etre appele pour une question generale")

    monkeypatch.setattr(router, "run_agent1", _fail)
    monkeypatch.setattr(GeminiClient, "generate", lambda self, prompt: "Albert Einstein etait un physicien theoricien.")

    result = router.route_message("Qui est Albert Einstein ?", is_authenticated=False, use_llm_router=True)
    assert result["intent"] == "general_query"
    assert result["requires_auth"] is False
    assert "Einstein" in result["response"]


# ---------------------------------------------------------------------------
# 3. GOOGLE_API_KEY manquante -> erreur claire, jamais un crash.
# ---------------------------------------------------------------------------


def test_gemini_client_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert gemini_client.is_configured() is False
    client = GeminiClient()
    with pytest.raises(GeminiNotConfiguredError):
        client.generate("Qui est Albert Einstein ?")


def test_run_general_agent_missing_api_key_returns_clear_message(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = run_general_agent("Qui est Albert Einstein ?")
    assert result["response"] == GEMINI_NOT_CONFIGURED_MESSAGE
    assert result["requires_auth"] is False
    assert result["intent"] == "general_query"


def test_run_general_agent_request_error_returns_graceful_message(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-tests")

    def _fail(self, prompt):
        raise GeminiRequestError("timeout")

    monkeypatch.setattr(GeminiClient, "generate", _fail)
    result = run_general_agent("Explique-moi la blockchain")
    assert result["response"] == GENERAL_AGENT_UNAVAILABLE_MESSAGE


def test_run_general_agent_success_returns_gemini_response(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(GeminiClient, "generate", lambda self, prompt: "La blockchain est un registre distribue.")
    result = run_general_agent("Explique-moi la blockchain")
    assert result["response"] == "La blockchain est un registre distribue."
    assert result["intent"] == "general_query"
    assert result["requires_auth"] is False


# ---------------------------------------------------------------------------
# 5. Modele Gemini (GEMINI_MODEL) — "gemini-1.5-flash" a ete retire par l'API
#    (404) ; "gemini-flash-latest" est le nouveau defaut, configurable.
# ---------------------------------------------------------------------------


def test_gemini_default_model_is_not_the_retired_model():
    # "gemini-1.5-flash" renvoie desormais 404 "is not found for API version
    # v1beta" sur l'API Gemini reelle (voir historique de ce bug) - ne doit
    # plus jamais etre le defaut.
    assert gemini_client._DEFAULT_MODEL != "gemini-1.5-flash"
    assert gemini_client._DEFAULT_MODEL == "gemini-flash-latest"


def test_gemini_client_initializes_configured_model_without_real_network(monkeypatch):
    """Verifie, sans aucun appel reseau reel, que `GeminiClient.generate`
    initialise bien le SDK (`genai.configure` puis `genai.GenerativeModel`)
    avec la cle API et le nom de modele attendus (`_DEFAULT_MODEL`)."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-tests")

    captured: dict = {}

    def fake_configure(api_key):
        captured["api_key"] = api_key

    class FakeGenerativeModel:
        def __init__(self, model_name):
            captured["model_name"] = model_name

        def generate_content(self, prompt):
            captured["prompt"] = prompt

            class _FakeResponse:
                text = "reponse simulee"

            return _FakeResponse()

    monkeypatch.setattr(gemini_client.genai, "configure", fake_configure)
    monkeypatch.setattr(gemini_client.genai, "GenerativeModel", FakeGenerativeModel)

    client = GeminiClient()
    result = client.generate("Qui est Albert Einstein ?")

    assert result == "reponse simulee"
    assert captured["api_key"] == "fake-key-for-tests"
    assert captured["model_name"] == gemini_client._DEFAULT_MODEL
    assert captured["prompt"] == "Qui est Albert Einstein ?"


def test_gemini_client_explicit_model_name_overrides_default(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-tests")

    captured: dict = {}

    class FakeGenerativeModel:
        def __init__(self, model_name):
            captured["model_name"] = model_name

        def generate_content(self, prompt):
            class _FakeResponse:
                text = "ok"

            return _FakeResponse()

    monkeypatch.setattr(gemini_client.genai, "configure", lambda api_key: None)
    monkeypatch.setattr(gemini_client.genai, "GenerativeModel", FakeGenerativeModel)

    client = GeminiClient(model_name="gemini-custom-test-model")
    client.generate("test")

    assert captured["model_name"] == "gemini-custom-test-model"


def test_gemini_model_configurable_via_env_var_at_startup():
    """`GEMINI_MODEL` est lu au chargement du module (`_DEFAULT_MODEL`) — testé
    dans un sous-processus isolé pour ne jamais recharger `gemini_client` dans
    le process de test (un `importlib.reload` re-creerait les classes
    d'exception du module, cassant leur identite pour les autres tests de ce
    fichier qui s'appuient sur les classes importees une seule fois en tete de
    fichier)."""
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env["GEMINI_MODEL"] = "gemini-custom-env-model"
    result = subprocess.run(
        [sys.executable, "-c", "from agents.general_agent import gemini_client; print(gemini_client._DEFAULT_MODEL)"],
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "gemini-custom-env-model"


# ---------------------------------------------------------------------------
# 4. Bout en bout, via le VRAI endpoint FastAPI `/api/chat` (pas uniquement
#    `router.route_message` en isolation) : reproduit exactement le chemin
#    emprunte par le frontend, pour confirmer que le dispatch fonctionne
#    reellement au niveau HTTP et pas seulement au niveau du module Python.
# ---------------------------------------------------------------------------


def test_api_chat_endpoint_routes_general_question_to_general_agent(monkeypatch):
    monkeypatch.setattr(
        router,
        "classify_domain",
        lambda *a, **k: {"domain": "general", "intent": "knowledge_question", "needs_web": False},
    )
    monkeypatch.setattr(
        GeminiClient, "generate", lambda self, prompt: "L'intelligence artificielle est un domaine de l'informatique."
    )
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: True
    try:
        client = TestClient(app)
        response = client.post("/api/chat", json={"message": "Explique-moi l'intelligence artificielle"})
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "general_query"
        assert data["requires_auth"] is False
        assert "intelligence artificielle" in data["response"].lower()
    finally:
        app.dependency_overrides.clear()


def test_api_chat_endpoint_routes_banking_question_to_agent1_never_gemini(monkeypatch):
    def _fail(self, prompt):
        raise AssertionError("Gemini ne doit jamais etre appele pour une question bancaire")

    monkeypatch.setattr(GeminiClient, "generate", _fail)
    # use_llm_router=False -> repli deterministe garanti sur domain="banking"
    # (meme convention que les autres tests de test_api.py).
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: False
    try:
        client = TestClient(app)
        response = client.post("/api/chat", json={"message": "ch7al 3ndi fl compte"})
        assert response.status_code == 200
        data = response.json()
        # Traite par le Banking Agent (Agent 1) - jamais "general_query".
        assert data["intent"] != "general_query"
    finally:
        app.dependency_overrides.clear()
