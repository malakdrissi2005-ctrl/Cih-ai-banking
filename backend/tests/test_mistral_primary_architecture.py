"""Tests de la nouvelle architecture Agent 1 : Security Guard limité à la
sécurité (`classification.detect_sensitive_operation`), Mistral comme moteur
de compréhension principal.

Couvre exactement les 7 messages demandés ("slm", "bonjour", "merci",
"bghit n7ell compte", "J'ai perdu ma carte", "ch7al 3ndi fl compte",
"kel est mon sold") et vérifie que :
1. Le Security Guard ne remplace/ne choisit plus jamais l'intention
   (`personal_data`/`faq_public`/`card_query`/`balance_query`).
2. Mistral (mocké — jamais un service Ollama réel, même convention que
   `test_llm_first_routing.py`) comprend correctement chacun de ces messages.
3. Les données bancaires retournées viennent uniquement de `banking.db`,
   jamais inventées par le LLM.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.agent1_faq import llm_router
from agents.agent1_faq.classification import detect_sensitive_operation
from agents.agent1_faq.graph import run_agent1
from app.banking import banking_db

SEVEN_MESSAGES = [
    "slm",
    "bonjour",
    "merci",
    "bghit n7ell compte",
    "J'ai perdu ma carte",
    "ch7al 3ndi fl compte",
    "kel est mon sold",
]


@pytest.fixture
def banking_path(tmp_path):
    path = str(tmp_path / "mistral_primary_test.db")
    banking_db.seed_banking_data(db_path=path)
    return path


def _mock_llm_response(monkeypatch, intent, **extra):
    payload = {"intent": intent, "category": None, "period": None, "card_fields": [], "faq_query": None}
    payload.update(extra)
    monkeypatch.setattr(llm_router, "route_with_llm", lambda *a, **k: payload)


def _forbid_mistral_call(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("Mistral ne doit pas etre appele ici")

    monkeypatch.setattr(llm_router, "route_with_llm", _fail)


# ---------------------------------------------------------------------------
# 1. Security Guard : ne classe plus jamais personal_data/faq_public/
#    card_query/balance_query - structurellement limite a virement/compte_action/None.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", SEVEN_MESSAGES)
def test_security_guard_never_resolves_a_non_sensitive_category(message):
    # detect_sensitive_operation ne peut retourner que "virement"/"compte_action"/None -
    # jamais personal_data/faq_generale/card_query/balance_query pour aucun des 7 messages.
    result = detect_sensitive_operation(message)
    assert result in (None, "virement", "compte_action")
    assert result not in ("personal_data", "faq_generale", "card_query", "balance_query")


def test_security_guard_does_not_flag_any_of_the_seven_messages_as_sensitive():
    # Aucun des 7 messages demandes n'est une operation sensible (virement/compte_action) :
    # tous doivent pouvoir continuer vers Mistral.
    for message in SEVEN_MESSAGES:
        assert detect_sensitive_operation(message) is None


def test_security_guard_still_protects_real_sensitive_requests():
    # Garde-fou non regresse par ce changement : virement/compte_action toujours detectes.
    assert detect_sensitive_operation("Je veux virer 500 dh") == "virement"
    assert detect_sensitive_operation("bloque ma carte") == "compte_action"


# ---------------------------------------------------------------------------
# 2. Mistral (mocke) comme moteur de comprehension principal - un cas par
#    message demande.
# ---------------------------------------------------------------------------


def test_slm_is_understood_as_greeting(monkeypatch):
    # "slm" est deja intercepte par la couche deterministe rapide
    # (conversational.py) avant meme d'atteindre Mistral (optimisation de
    # latence) - le resultat final doit neanmoins etre "greeting", sans le
    # moindre appel a Mistral pour un cas aussi trivial.
    _forbid_mistral_call(monkeypatch)
    result = run_agent1("slm", use_llm_router=True)
    assert result["intent"] == "greeting"
    assert "Bonjour" in result["response"]


def test_bonjour_is_understood_as_greeting(monkeypatch):
    _forbid_mistral_call(monkeypatch)
    result = run_agent1("bonjour", use_llm_router=True)
    assert result["intent"] == "greeting"


def test_merci_is_understood_as_thanks(monkeypatch):
    _forbid_mistral_call(monkeypatch)
    result = run_agent1("merci", use_llm_router=True)
    assert result["intent"] == "thanks"
    assert result["response"] == "Je vous en prie."


def test_greeting_variant_not_caught_by_fast_filter_is_still_understood_by_mistral(monkeypatch):
    # Variante non couverte par le filtre deterministe rapide
    # (conversational.py, qui n'accepte une salutation que si TOUT le message
    # correspond a son vocabulaire fixe) : Mistral doit pouvoir la reconnaitre
    # comme "greeting" (vocabulaire etendu de llm_router.py) sans jamais
    # toucher ChromaDB ni banking_db.
    _mock_llm_response(monkeypatch, "greeting")
    result = run_agent1("salam a tous, ravi de vous parler aujourdhui", use_llm_router=True)
    assert result["intent"] == "greeting"
    assert "Bonjour" in result["response"]


def test_bghit_n7ell_compte_is_understood_as_faq_public(monkeypatch):
    _mock_llm_response(monkeypatch, "faq_search", faq_query="Comment ouvrir un compte bancaire")
    result = run_agent1("bghit n7ell compte", use_llm_router=True)
    assert result["intent"] == "faq_generale"


def test_j_ai_perdu_ma_carte_is_understood_as_card_query_routes_to_faq(monkeypatch):
    # Regle : "J'ai perdu ma carte" est un SIGNALEMENT D'INCIDENT, pas une
    # demande de donnee personnelle - card_query -> FAQ generale, jamais
    # d'authentification exigee, jamais de lecture banking_db, MEME
    # authentifie (voir graph.py::_requests_personal_card_info).
    _mock_llm_response(monkeypatch, "card_query", card_fields=["status"])
    with patch("agents.agent1_faq.graph.build_personal_data_answer") as mocked_personal:
        result = run_agent1("J'ai perdu ma carte", is_authenticated=True, user_id="usr_001", use_llm_router=True)
    mocked_personal.assert_not_called()
    assert result["intent"] == "card_query"
    assert result["requires_auth"] is False


@pytest.mark.parametrize("message", ["ma carte ne marche pas", "carte bloquee"])
def test_card_incident_reports_route_to_faq_no_auth(monkeypatch, message):
    # Memes regles pour les autres signalements d'incident/panne cites par
    # l'enonce : jamais une demande de donnee personnelle.
    _mock_llm_response(monkeypatch, "card_query", card_fields=["status"])
    with patch("agents.agent1_faq.graph.build_personal_data_answer") as mocked_personal:
        result = run_agent1(message, is_authenticated=True, user_id="usr_001", use_llm_router=True)
    mocked_personal.assert_not_called()
    assert result["intent"] == "card_query"
    assert result["requires_auth"] is False


@pytest.mark.parametrize(
    "message,expected_faq_query",
    [
        ("Mon compte est bloqué", "Que faire si mon compte est bloqué ou verrouillé"),
        ("Mon compte est verrouillé", "Que faire si mon compte est bloqué ou verrouillé"),
        ("Je n'arrive plus à accéder à mon compte", "Que faire si je n'arrive plus à accéder à mon compte"),
    ],
)
def test_account_lock_incident_reports_route_to_faq_no_auth(monkeypatch, message, expected_faq_query):
    # Regle ajoutee au prompt Mistral (llm_router._SYSTEM_PROMPT, voir
    # test_llm_router.py) pour lever l'ambiguite avec balance_query (dont la
    # definition a ete elargie pour couvrir les demandes generiques
    # d'informations sur le compte) : un signalement de blocage/verrouillage
    # de compte est une question de procedure (faq_search), jamais une donnee
    # personnelle - meme principe que les incidents carte ci-dessus.
    _mock_llm_response(monkeypatch, "faq_search", faq_query=expected_faq_query)
    with patch("agents.agent1_faq.graph.build_personal_data_answer") as mocked_personal:
        result = run_agent1(message, is_authenticated=True, user_id="usr_001", use_llm_router=True)
    mocked_personal.assert_not_called()
    assert result["intent"] == "faq_generale"
    assert result["requires_auth"] is False


def test_card_query_without_personal_marker_is_general_faq_no_auth(monkeypatch, banking_path):
    # Regle : card_query -> FAQ generale par defaut, sauf demande explicite
    # d'information personnelle sur la carte. Ici, aucun mot-cle
    # d'information (numero/statut/plafond) : doit rester une question
    # publique, jamais d'authentification exigee, jamais de lecture banking_db.
    _mock_llm_response(monkeypatch, "card_query", card_fields=["status"])
    result = run_agent1("Quels types de carte proposez-vous ?", is_authenticated=False, use_llm_router=True)
    assert result["intent"] == "card_query"
    assert result["requires_auth"] is False


@pytest.mark.parametrize("message", ["quel est le numero de ma carte", "donne-moi les informations de ma carte"])
def test_explicit_personal_card_info_request_requires_auth(monkeypatch, banking_path, message):
    # Regle : seule une DEMANDE D'INFORMATION personnelle explicite (numero,
    # informations, statut, plafond) sur la carte exige une authentification
    # - jamais un simple signalement d'incident.
    _mock_llm_response(monkeypatch, "card_query", card_fields=["status"])
    result_unauthenticated = run_agent1(message, is_authenticated=False, banking_db_path=banking_path, use_llm_router=True)
    assert result_unauthenticated["intent"] == "card_query"
    assert result_unauthenticated["requires_auth"] is True

    result_authenticated = run_agent1(
        message, is_authenticated=True, user_id="usr_001", banking_db_path=banking_path, use_llm_router=True
    )
    assert result_authenticated["intent"] == "card_query"
    assert result_authenticated["requires_auth"] is False


def test_card_information_request_returns_real_status_from_database(monkeypatch, banking_path):
    """Une demande d'INFORMATION sur la carte renvoie bien la donnee reelle,
    lue en base et jamais inventee par Mistral."""
    _mock_llm_response(monkeypatch, "card_query", card_fields=["status"])
    result = run_agent1(
        "donne-moi les informations de ma carte",
        is_authenticated=True, user_id="usr_001", banking_db_path=banking_path, use_llm_router=True,
    )
    real_card = banking_db.get_card_for_customer("usr_001", db_path=banking_path)
    assert real_card["status"] == "active"
    assert "active" in result["response"].lower()


def test_card_number_request_is_refused_even_when_mistral_says_card_query(monkeypatch, banking_path):
    """CHANGEMENT DE CONTRAT ASSUME (protection numero de carte).

    "quel est le numero de ma carte" ne renvoie plus le statut de la carte :
    le numero complet ne doit jamais transiter par le chatbot. La demande
    exige toujours une authentification (assertion conservee ci-dessus), mais
    la reponse est desormais un refus explicite avec redirection securisee -
    y compris lorsque Mistral, lui, classe la demande en `card_query`
    (`CLAUDE.md` §5 : aucune securite ne repose sur le LLM).

    Voir `backend/tests/test_card_number_protection.py` pour la couverture
    complete de cette protection."""
    from agents.agent1_faq.banking_answers import CARD_NUMBER_REDIRECT_MESSAGE

    _mock_llm_response(monkeypatch, "card_query", card_fields=["status"])
    result = run_agent1(
        "quel est le numero de ma carte",
        is_authenticated=True, user_id="usr_001", banking_db_path=banking_path, use_llm_router=True,
    )
    assert result["response"] == CARD_NUMBER_REDIRECT_MESSAGE
    assert "active" not in result["response"].lower()


def test_ch7al_3ndi_fl_compte_is_understood_as_balance_query(monkeypatch, banking_path):
    # Correctif architecture : preserve "balance_query", plus jamais
    # converti en "personal_data".
    _mock_llm_response(monkeypatch, "balance_query")
    result = run_agent1(
        "ch7al 3ndi fl compte",
        is_authenticated=True,
        user_id="usr_001",
        banking_db_path=banking_path,
        use_llm_router=True,
    )
    assert result["intent"] == "balance_query"
    expected_total = banking_db.get_total_balance("usr_001", db_path=banking_path)
    assert str(expected_total) in result["response"]


def test_kel_est_mon_sold_is_understood_as_balance_query(monkeypatch, banking_path):
    _mock_llm_response(monkeypatch, "balance_query")
    result = run_agent1(
        "kel est mon sold",
        is_authenticated=True,
        user_id="usr_001",
        banking_db_path=banking_path,
        use_llm_router=True,
    )
    assert result["intent"] == "balance_query"
    expected_total = banking_db.get_total_balance("usr_001", db_path=banking_path)
    assert str(expected_total) in result["response"]


# ---------------------------------------------------------------------------
# Non-regression explicite (formulations exactes demandees) : la regle
# ajoutee pour desambiguiser "compte bloque" ne doit jamais affecter les
# vraies demandes de donnees personnelles ni le signalement de carte perdue.
# ---------------------------------------------------------------------------


def test_quel_est_mon_solde_still_balance_query(monkeypatch, banking_path):
    _mock_llm_response(monkeypatch, "balance_query")
    result = run_agent1(
        "Quel est mon solde ?",
        is_authenticated=True,
        user_id="usr_001",
        banking_db_path=banking_path,
        use_llm_router=True,
    )
    assert result["intent"] == "balance_query"
    expected_total = banking_db.get_total_balance("usr_001", db_path=banking_path)
    assert str(expected_total) in result["response"]


def test_donne_moi_mes_transactions_still_transactions_query(monkeypatch, banking_path):
    _mock_llm_response(monkeypatch, "transactions_query")
    result = run_agent1(
        "Donne-moi mes transactions",
        is_authenticated=True,
        user_id="usr_001",
        banking_db_path=banking_path,
        use_llm_router=True,
    )
    assert result["intent"] == "transactions_query"
    assert result["requires_auth"] is False


def test_j_ai_perdu_ma_carte_still_card_query_not_confused_with_account_lock(monkeypatch):
    _mock_llm_response(monkeypatch, "card_query", card_fields=["status"])
    result = run_agent1("J'ai perdu ma carte", is_authenticated=True, user_id="usr_001", use_llm_router=True)
    assert result["intent"] == "card_query"
    assert result["requires_auth"] is False


# ---------------------------------------------------------------------------
# 3. Authentification toujours obligatoire pour les donnees personnelles,
#    quelle que soit l'intention reconnue par Mistral - jamais recalculee a
#    partir de sa sortie. user_id vient uniquement de la session.
# ---------------------------------------------------------------------------


def test_ch7al_3ndi_unauthenticated_requires_login_and_never_leaks_balance(monkeypatch, banking_path):
    _mock_llm_response(monkeypatch, "balance_query")
    result = run_agent1("ch7al 3ndi fl compte", is_authenticated=False, banking_db_path=banking_path, use_llm_router=True)
    assert result["intent"] == "balance_query"
    assert result["requires_auth"] is True
    assert "45730.50" not in result["response"]


def test_j_ai_perdu_ma_carte_unauthenticated_never_requires_login(monkeypatch, banking_path):
    # Signalement d'incident, pas une demande de donnee personnelle -> jamais
    # d'authentification exigee, meme non connecte (voir aussi
    # test_j_ai_perdu_ma_carte_is_understood_as_card_query_routes_to_faq
    # pour le cas authentifie).
    _mock_llm_response(monkeypatch, "card_query", card_fields=["status"])
    result = run_agent1(
        "J'ai perdu ma carte", is_authenticated=False, banking_db_path=banking_path, use_llm_router=True
    )
    assert result["intent"] == "card_query"
    assert result["requires_auth"] is False


# ---------------------------------------------------------------------------
# 4. Repli garanti : si Mistral est indisponible, Agent 1 ne plante jamais et
#    retombe sur classify_fallback (classification.classify_intent) - jamais
#    sur le Security Guard, qui ne fait plus ce travail.
# ---------------------------------------------------------------------------


def test_mistral_failure_falls_back_to_classify_fallback_never_to_security_guard(monkeypatch, banking_path):
    monkeypatch.setattr(llm_router, "route_with_llm", lambda *a, **k: None)
    result = run_agent1(
        "Quel est mon solde ?", is_authenticated=True, user_id="usr_001", banking_db_path=banking_path, use_llm_router=True
    )
    assert result["intent"] == "personal_data"
    assert "45730.50" in result["response"]
