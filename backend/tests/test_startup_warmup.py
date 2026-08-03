"""Vérifie le réchauffement Ollama au démarrage du backend (`backend/app/main.py`).

Le réchauffement (`llm_router.warm_up`) n'est déclenché que via le protocole
ASGI *lifespan*, activé uniquement par `with TestClient(app) as client:` —
jamais par une simple instanciation `TestClient(app)` comme dans le reste de
la suite (voir `test_api.py`), qui reste donc totalement inchangée par cet
ajout. Ici, `warm_up` est systématiquement mocké : aucun appel Ollama réel
(couvert séparément et optionnellement par `test_ollama_integration.py`).
"""
from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from agents.agent1_faq import llm_router
from app.main import app


def test_lifespan_triggers_warmup_in_background_when_configured(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    monkeypatch.delenv("LLM_ROUTER_ENABLED", raising=False)

    called = threading.Event()

    def _fake_warm_up(*args, **kwargs):
        called.set()
        return True

    monkeypatch.setattr(llm_router, "warm_up", _fake_warm_up)

    with TestClient(app) as client:
        assert called.wait(timeout=2), "warm_up() aurait dû être appelée au démarrage du backend."
        # Le démarrage n'attend jamais le réchauffement (thread séparé) : l'app
        # reste immédiatement disponible.
        response = client.get("/health")
        assert response.status_code == 200


def test_lifespan_skips_warmup_when_router_disabled(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    monkeypatch.setenv("LLM_ROUTER_ENABLED", "false")

    called = threading.Event()
    monkeypatch.setattr(llm_router, "warm_up", lambda *a, **k: called.set() or True)

    with TestClient(app) as client:
        assert not called.wait(timeout=0.5)
        assert client.get("/health").status_code == 200


def test_lifespan_skips_warmup_when_ollama_not_configured(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_ROUTER_ENABLED", raising=False)

    called = threading.Event()
    monkeypatch.setattr(llm_router, "warm_up", lambda *a, **k: called.set() or True)

    with TestClient(app) as client:
        assert not called.wait(timeout=0.5)
        assert client.get("/health").status_code == 200
