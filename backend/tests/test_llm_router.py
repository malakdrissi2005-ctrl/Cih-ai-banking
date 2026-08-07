"""Tests du LLM Router (agents/agent1_faq/llm_router.py).

Aucun test ici n'appelle un service Ollama réel : les appels HTTP
(`httpx.post`) sont systématiquement mockés via `monkeypatch`. Une inférence
Mistral réelle en CPU peut dépasser 90 secondes pour un prompt trivial (mesuré
manuellement dans cet environnement) — totalement incompatible avec une
suite de tests rapide et déterministe. Une démonstration avec un Ollama
réellement démarré est réservée à une vérification manuelle ponctuelle, hors
suite automatisée (voir le rapport final).
"""
from __future__ import annotations

import json

import httpx
import pytest

from agents.agent1_faq import llm_router


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self) -> dict:
        return self._payload


def _ollama_json_response(model_output: dict) -> _FakeResponse:
    return _FakeResponse({"response": json.dumps(model_output)})


@pytest.fixture(autouse=True)
def _configure_ollama_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")


def test_is_llm_configured_true_when_env_present():
    assert llm_router.is_llm_configured() is True


def test_is_llm_configured_false_when_env_missing(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert llm_router.is_llm_configured() is False


def test_route_with_llm_valid_balance_query(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: _ollama_json_response({"intent": "balance_query"})
    )
    result = llm_router.route_with_llm("Peux-tu me dire combien j'ai sur mon compte ?", "...", "fr")
    assert result["intent"] == "balance_query"


def test_route_with_llm_valid_spending_analysis_with_category(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _ollama_json_response(
            {"intent": "spending_analysis", "category": "Restaurants", "period": "current_month"}
        ),
    )
    result = llm_router.route_with_llm("Combien ai-je dépensé dans les restaurants ce mois-ci ?", "...", "fr")
    assert result == {
        "intent": "spending_analysis",
        "category": "Restaurants",
        "period": "current_month",
        "card_fields": [],
        "faq_query": None,
    }


def test_route_with_llm_rejects_unknown_intent(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _ollama_json_response({"intent": "transfer_money"}))
    assert llm_router.route_with_llm("...", "...", "fr") is None


def test_route_with_llm_rejects_forbidden_field_user_id(monkeypatch):
    # Tentative d'injection / hallucination : un champ "user_id" ne doit
    # jamais être accepté, quelle que soit sa valeur.
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: _ollama_json_response({"intent": "balance_query", "user_id": "usr_999"})
    )
    assert llm_router.route_with_llm("...", "...", "fr") is None


def test_route_with_llm_rejects_forbidden_field_amount(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: _ollama_json_response({"intent": "balance_query", "amount": "999999.00"})
    )
    assert llm_router.route_with_llm("...", "...", "fr") is None


def test_route_with_llm_drops_invalid_category(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _ollama_json_response({"intent": "spending_analysis", "category": "Voyages fictifs"}),
    )
    result = llm_router.route_with_llm("...", "...", "fr")
    assert result["intent"] == "spending_analysis"
    assert result["category"] is None


def test_route_with_llm_drops_invalid_card_fields(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _ollama_json_response({"intent": "card_query", "card_fields": ["status", "pin_code"]}),
    )
    result = llm_router.route_with_llm("...", "...", "fr")
    assert result["card_fields"] == ["status"]


def test_route_with_llm_returns_none_on_timeout(monkeypatch):
    def _raise_timeout(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "post", _raise_timeout)
    assert llm_router.route_with_llm("...", "...", "fr") is None


def test_route_with_llm_returns_none_on_connection_error(monkeypatch):
    def _raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raise_connect_error)
    assert llm_router.route_with_llm("...", "...", "fr") is None


def test_route_with_llm_returns_none_on_invalid_json(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({"response": "not json at all"}))
    assert llm_router.route_with_llm("...", "...", "fr") is None


def test_route_with_llm_returns_none_when_not_configured(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert llm_router.route_with_llm("...", "...", "fr") is None


def test_route_with_llm_includes_keep_alive_in_payload(monkeypatch):
    # keep_alive maintient le modele charge en RAM entre deux appels (voir
    # llm_router.py, en-tete de module : rechargement a froid mesure a ~45-53s).
    captured = {}

    def _capture(url, json, timeout):  # noqa: A002
        captured["json"] = json
        return _ollama_json_response({"intent": "balance_query"})

    monkeypatch.setattr(httpx, "post", _capture)
    llm_router.route_with_llm("...", "...", "fr")
    assert captured["json"]["keep_alive"] == "30m"


def test_route_with_llm_respects_custom_keep_alive(monkeypatch):
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "1h")
    captured = {}

    def _capture(url, json, timeout):  # noqa: A002
        captured["json"] = json
        return _ollama_json_response({"intent": "balance_query"})

    monkeypatch.setattr(httpx, "post", _capture)
    llm_router.route_with_llm("...", "...", "fr")
    assert captured["json"]["keep_alive"] == "1h"


def test_default_timeout_covers_measured_warm_latency():
    # Mesure empirique reproduite localement (voir test_ollama_integration.py) :
    # un appel a chaud (modele deja charge) prend ~6.5-7s aller-retour complet.
    # Le delai par defaut doit rester strictement superieur, avec marge, pour
    # ne pas timeout systematiquement meme une fois le modele chaud.
    assert llm_router._DEFAULT_TIMEOUT_SECONDS >= 8


def test_is_router_enabled_default_true(monkeypatch):
    monkeypatch.delenv("LLM_ROUTER_ENABLED", raising=False)
    assert llm_router.is_router_enabled() is True


def test_is_router_enabled_false_when_disabled(monkeypatch):
    monkeypatch.setenv("LLM_ROUTER_ENABLED", "false")
    assert llm_router.is_router_enabled() is False


def test_is_router_enabled_case_insensitive(monkeypatch):
    monkeypatch.setenv("LLM_ROUTER_ENABLED", "FALSE")
    assert llm_router.is_router_enabled() is False


# ---------------------------------------------------------------------------
# warm_up : rechauffement en tache de fond au demarrage du backend (voir
# backend/app/main.py) — jamais appele dans le chemin d'une requete utilisateur.
# ---------------------------------------------------------------------------


def test_warm_up_returns_true_on_success(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({"response": "ok"}))
    assert llm_router.warm_up() is True


def test_warm_up_returns_false_on_timeout(monkeypatch):
    def _raise_timeout(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "post", _raise_timeout)
    assert llm_router.warm_up() is False


def test_warm_up_returns_false_on_connection_error(monkeypatch):
    def _raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raise_connect_error)
    assert llm_router.warm_up() is False


def test_warm_up_returns_false_when_not_configured(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert llm_router.warm_up() is False


def test_warm_up_sends_minimal_single_token_payload(monkeypatch):
    # num_predict=1 : seul le chargement en RAM nous interesse, jamais la
    # qualite de la sortie generee.
    captured = {}

    def _capture(url, json, timeout):  # noqa: A002
        captured["json"] = json
        return _FakeResponse({"response": "ok"})

    monkeypatch.setattr(httpx, "post", _capture)
    llm_router.warm_up()
    assert captured["json"]["keep_alive"] == "30m"
    assert captured["json"]["options"]["num_predict"] == 1


def test_route_with_llm_uses_conversation_history_in_prompt(monkeypatch):
    captured = {}

    def _capture(url, json, timeout):  # noqa: A002 - nom du paramètre imposé par l'appel réel
        captured["prompt"] = json["prompt"]
        return _ollama_json_response({"intent": "spending_analysis"})

    monkeypatch.setattr(httpx, "post", _capture)
    llm_router.route_with_llm(
        "Et mes dépenses du mois ?",
        "...",
        "fr",
        conversation_history=[("Quel est mon solde ?", "Le total de vos comptes est de 100 MAD.")],
    )
    assert "Quel est mon solde" in captured["prompt"]


# ---------------------------------------------------------------------------
# to_personal_intent : conversion du vocabulaire LLM Router vers le format
# attendu par banking_answers.build_personal_data_answer.
# ---------------------------------------------------------------------------


def test_to_personal_intent_balance_query():
    assert llm_router.to_personal_intent({"intent": "balance_query"}) == {"intent": "total_balance"}


def test_to_personal_intent_card_query_defaults_to_status():
    assert llm_router.to_personal_intent({"intent": "card_query", "card_fields": []}) == {
        "intent": "card_information",
        "requested_fields": ["status"],
    }


def test_to_personal_intent_spending_analysis_without_category():
    result = llm_router.to_personal_intent({"intent": "spending_analysis", "category": None, "period": None})
    assert result == {"intent": "spending_by_category", "category": None, "period": "current_month"}


def test_to_personal_intent_faq_search_returns_none():
    assert llm_router.to_personal_intent({"intent": "faq_search", "faq_query": "ouvrir un compte"}) is None


def test_to_personal_intent_unclear_maps_to_assistant_explain():
    assert llm_router.to_personal_intent({"intent": "unclear"}) == {"intent": "assistant_explain"}


# ---------------------------------------------------------------------------
# Desambiguisation "compte bloque"/"fraude" vs balance_query (non-regression) :
# la definition de balance_query a ete elargie ("une demande d'informations
# generales sur le compte... qui ne precise aucun element plus specifique")
# pour couvrir "donne-moi les informations sur mon compte" - ce qui pouvait
# entrer en collision avec un signalement de blocage/verrouillage/fraude sur
# le compte, lui aussi une mention generique du compte sans element plus
# specifique. Architecture (voir echange "je ne veux pas resoudre les
# problemes utilisateur par utilisateur avec des regles") : le prompt encode
# desormais un PRINCIPE general de desambiguisation (signalement de probleme
# -> faq_search, jamais personal_data) plutot qu'une enumeration figee de
# formulations litterales - verifie ici que ce principe est bien present,
# sans dependre d'une liste exhaustive de phrases exactes qui grossirait a
# chaque nouveau cas signale.
# ---------------------------------------------------------------------------


def test_system_prompt_contains_general_principle_not_literal_memorization():
    # Garde-fou architectural : le prompt doit explicitement dire a Mistral
    # de generaliser a partir du sens, pas de la correspondance de mots -
    # sinon on retombe dans l'anti-pattern "une regle par bug signale".
    prompt = llm_router._SYSTEM_PROMPT
    assert "base-toi sur le SENS de la question" in prompt
    assert "pas une liste exhaustive à mémoriser" in prompt


def test_system_prompt_disambiguates_account_problem_reports_from_balance_query():
    prompt = llm_router._SYSTEM_PROMPT
    assert "signalement de problème concernant le COMPTE, l'ACCÈS ou la SÉCURITÉ" in prompt
    assert "bloqué, verrouillé, suspendu" in prompt
    assert "fraude, piraté" in prompt
    assert "Un signalement de problème est TOUJOURS une" in prompt
    # Exemple illustratif regroupe (plusieurs formulations -> une seule ligne,
    # pas une ligne par phrase exacte).
    assert '"Mon compte est bloqué"' in prompt
    assert '"J\'ai détecté une fraude sur mon' in prompt
    assert '{"intent": "faq_search"' in prompt


def test_system_prompt_card_incidents_still_map_to_card_query_not_faq_search():
    # Distinction critique preservee : un incident CARTE (perdue/volee/
    # bloquee) reste card_query (graph.py gere deja la nuance FAQ/personnel
    # en aval) - jamais confondu avec le principe "incident compte -> faq_search"
    # ci-dessus, qui ne concerne que le compte/l'acces/la securite.
    prompt = llm_router._SYSTEM_PROMPT
    assert '"J\'ai perdu ma carte"' in prompt
    assert "perdue, volée, bloquée" in prompt
    # Verrouille l'exemple explicite lui-meme (pas seulement la presence du
    # mot "card_query" ailleurs dans le prompt) - voir regression signalee
    # "J'ai perdu ma carte" ne doit plus jamais perdre cet exemple lors d'une
    # future simplification du prompt.
    assert '"J\'ai perdu ma carte" / "khsart carte dyali"' in prompt
    assert '-> {"intent": "card_query"}' in prompt
