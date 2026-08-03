"""Tests du nouvel ordre de compréhension de l'Agent 1 : Mistral (`llm_router.py`)
est désormais appelé **en premier** (avant la sous-classification fine) pour
distinguer `balance_query` de `faq_generale` — voir `graph.py::_llm_router_node`.

Vérifie en particulier les 5 formulations qui mettaient en échec la
classification déterministe seule (fautes de frappe, darija arabe/Arabizi) :
elles doivent désormais toutes aboutir à l'intent `balance_query` (préservé
tel quel depuis Mistral, jamais appauvri vers un bucket générique
`personal_data`), **via** une sortie Mistral mockée
(`{"intent": "balance_query"}`) — la fiabilité réelle du modèle sur ces
phrases est vérifiée séparément, contre un Ollama réellement démarré, par
`test_ollama_integration.py` (désactivé par défaut).

Tous les appels à `llm_router.route_with_llm` sont mockés ici (jamais un
service Ollama réel) — même convention que `test_llm_router.py` et
`test_smart_understanding.py` : suite rapide et déterministe.
"""
from __future__ import annotations

import pytest

from agents.agent1_faq import llm_router
from agents.agent1_faq.graph import run_agent1
from app.banking import banking_db

# Les 5 formulations demandées : fautes de frappe, darija arabe (correcte et
# tronquée), Arabizi, français fautif, français familier sans mot-clé "solde".
FIVE_PHRASES = [
    "حال عندي فالحساب",
    "شحال عندي فالحساب",
    "ch7al 3ndi fl compte",
    "kel est mon sold",
    "combien jai",
]


@pytest.fixture
def banking_path(tmp_path):
    path = str(tmp_path / "llm_first_routing_test.db")
    banking_db.seed_banking_data(db_path=path)
    return path


def _mock_balance_query(monkeypatch):
    monkeypatch.setattr(
        llm_router,
        "route_with_llm",
        lambda *args, **kwargs: {
            "intent": "balance_query",
            "category": None,
            "period": None,
            "card_fields": [],
            "faq_query": None,
        },
    )


# ---------------------------------------------------------------------------
# 1. Les 5 phrases doivent toutes aboutir à intent="personal_data".
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", FIVE_PHRASES)
def test_five_phrases_resolve_to_balance_query_intent(monkeypatch, banking_path, message):
    # Mistral preserve l'intention precise ("balance_query") - plus jamais
    # appauvrie vers un bucket generique "personal_data" (voir graph.py,
    # _llm_router_node : preservation des intentions).
    _mock_balance_query(monkeypatch)
    result = run_agent1(message, is_authenticated=True, user_id="usr_001", banking_db_path=banking_path, use_llm_router=True)
    assert result["intent"] == "balance_query"


@pytest.mark.parametrize("message", FIVE_PHRASES)
def test_five_phrases_authenticated_return_real_balance(monkeypatch, banking_path, message):
    _mock_balance_query(monkeypatch)
    result = run_agent1(message, is_authenticated=True, user_id="usr_001", banking_db_path=banking_path, use_llm_router=True)
    expected_total = banking_db.get_total_balance("usr_001", db_path=banking_path)
    assert str(expected_total) in result["response"]


@pytest.mark.parametrize("message", FIVE_PHRASES)
def test_five_phrases_unauthenticated_require_login_never_leak_data(monkeypatch, banking_path, message):
    # Meme identifiees comme personal_data par Mistral, un utilisateur non
    # authentifie ne doit JAMAIS recevoir de donnee reelle - uniquement une
    # invitation a se connecter (`requires_auth` reste base sur la session,
    # jamais recalcule a partir de la sortie LLM).
    _mock_balance_query(monkeypatch)
    result = run_agent1(message, is_authenticated=False, banking_db_path=banking_path, use_llm_router=True)
    assert result["intent"] == "balance_query"
    assert result["requires_auth"] is True
    assert "45730.50" not in result["response"]


# ---------------------------------------------------------------------------
# 2. Repli déterministe garanti : Mistral en échec/désactivé/incertain.
# ---------------------------------------------------------------------------


def test_llm_failure_falls_back_to_deterministic_classification(monkeypatch, banking_path):
    monkeypatch.setattr(llm_router, "route_with_llm", lambda *a, **k: None)
    result = run_agent1(
        "Quel est mon solde ?", is_authenticated=True, user_id="usr_001", banking_db_path=banking_path, use_llm_router=True
    )
    assert result["intent"] == "personal_data"
    assert "45730.50" in result["response"]


def test_llm_unclear_intent_falls_back_to_deterministic_classification(monkeypatch, banking_path):
    # "unclear" est un signal de faible confiance : ne doit jamais a lui seul
    # faire basculer le bucket - repli sur le classificateur deterministe.
    monkeypatch.setattr(llm_router, "route_with_llm", lambda *a, **k: {"intent": "unclear"})
    result = run_agent1(
        "Comment ouvrir un compte ?", is_authenticated=False, use_llm_router=True
    )
    assert result["intent"] == "faq_generale"


def test_use_llm_router_false_never_calls_mistral(monkeypatch, banking_path):
    def _fail(*args, **kwargs):
        raise AssertionError("route_with_llm ne doit jamais etre appele quand use_llm_router=False")

    monkeypatch.setattr(llm_router, "route_with_llm", _fail)
    result = run_agent1(
        "combien jai", is_authenticated=True, user_id="usr_001", banking_db_path=banking_path, use_llm_router=False
    )
    # Repli deterministe : "combien jai" (sans apostrophe, aucun mot-cle
    # reconnu par classification.py) -> faq_generale, comportement inchange.
    assert result["intent"] == "faq_generale"


# ---------------------------------------------------------------------------
# 3. Garde de securite INCONTOURNABLE : virement/compte_action ne consultent
#    JAMAIS Mistral, quel que soit `use_llm_router` - et son resultat ne peut
#    jamais faire basculer le bucket vers l'un de ces deux cas.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    ["Je veux virer 500 dh", "bloque ma carte", "je voudrais augmenter mon plafond"],
)
def test_sensitive_requests_never_call_mistral(monkeypatch, banking_path, message):
    def _fail(*args, **kwargs):
        raise AssertionError("Mistral ne doit jamais etre consulte pour virement/compte_action")

    monkeypatch.setattr(llm_router, "route_with_llm", _fail)
    result = run_agent1(
        message, is_authenticated=True, user_id="usr_001", banking_db_path=banking_path, use_llm_router=True
    )
    assert result["intent"] in ("virement", "compte_action")
    assert result["response"] == "Ce service n'est pas disponible pour le moment."


def test_mistral_cannot_force_bucket_into_virement_or_compte_action(monkeypatch, banking_path):
    # Meme si Mistral etait (hypothetiquement) manipule pour renvoyer une
    # intention arbitraire, aucune valeur de `_VALID_INTENTS` (llm_router.py)
    # ne correspond a "virement"/"compte_action" - la garde deterministe est
    # de toute facon evaluee AVANT tout appel LLM (voir _security_guard_node),
    # donc jamais atteinte pour un message deja detecte comme sensible.
    monkeypatch.setattr(llm_router, "route_with_llm", lambda *a, **k: {"intent": "balance_query"})
    result = run_agent1(
        "Je veux virer 500 dh a mon beneficiaire", is_authenticated=True, user_id="usr_001",
        banking_db_path=banking_path, use_llm_router=True,
    )
    assert result["intent"] == "virement"
