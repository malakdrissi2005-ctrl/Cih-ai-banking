"""Tests du graphe Agent 1 : FAQ publique, blocage personnel, virement/actions indisponibles,
questions bancaires personnelles authentifiées."""
import json
from unittest.mock import patch

import pytest

from agents.agent1_faq.graph import run_agent1
from agents.agent1_faq.rag import get_faq_collection
from app.banking import banking_db
from scripts.ingest_faq import ingest_faq


def _populated_collection(tmp_path):
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(
        json.dumps(
            [{"question": "Quels documents pour ouvrir un compte ?", "answer": "CIN et justificatif de domicile."}]
        ),
        encoding="utf-8",
    )
    persist_dir = str(tmp_path / "chroma")
    ingest_faq(faq_path=faq_path, persist_dir=persist_dir, collection_name="faq_graph_test")
    return get_faq_collection(persist_dir=persist_dir, collection_name="faq_graph_test")


def test_public_question_returns_faq_answer(tmp_path):
    collection = _populated_collection(tmp_path)

    result = run_agent1("Quels documents pour ouvrir un compte ?", collection=collection)

    assert result["intent"] == "faq_generale"
    assert result["requires_auth"] is False
    assert "CIN" in result["response"]


def test_empty_faq_returns_graceful_message(tmp_path):
    persist_dir = str(tmp_path / "chroma_empty")
    collection = get_faq_collection(persist_dir=persist_dir, collection_name="faq_empty_test")

    result = run_agent1("Quels sont vos horaires ?", collection=collection)

    assert result["intent"] == "faq_generale"
    assert result["requires_auth"] is False
    assert "Aucune information" in result["response"]


def test_personal_question_requires_login_without_calling_chromadb(tmp_path):
    collection = _populated_collection(tmp_path)

    with patch("agents.agent1_faq.graph.search_faq") as mocked_search:
        result = run_agent1("Quel est mon solde ?", collection=collection)

    mocked_search.assert_not_called()
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is True
    assert "connecter" in result["response"]


@pytest.mark.parametrize(
    "message",
    [
        "Donne-moi le statut actuel de ma carte ainsi que ses plafonds de paiement et de retrait.",
        "Combien ai-je dépensé dans les restaurants ce mois-ci ?",
    ],
)
def test_complex_personal_questions_require_login_without_session(tmp_path, message):
    collection = _populated_collection(tmp_path)

    with patch("agents.agent1_faq.graph.search_faq") as mocked_search:
        result = run_agent1(message, collection=collection)

    mocked_search.assert_not_called()
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is True
    assert "connecter" in result["response"]


def test_virement_request_is_unavailable_without_calling_chromadb(tmp_path):
    collection = _populated_collection(tmp_path)

    with patch("agents.agent1_faq.graph.search_faq") as mocked_search:
        result = run_agent1("Je veux virer 500 DH à Youssef", collection=collection)

    mocked_search.assert_not_called()
    assert result["intent"] == "virement"
    assert result["response"] == "Ce service n'est pas disponible pour le moment."


def test_virement_request_is_unavailable_even_when_authenticated(tmp_path):
    collection = _populated_collection(tmp_path)

    result = run_agent1(
        "Je veux virer 500 DH à Youssef", is_authenticated=True, user_id="usr_001", collection=collection
    )

    assert result["intent"] == "virement"
    assert result["requires_auth"] is False
    assert result["response"] == "Ce service n'est pas disponible pour le moment."


def test_account_action_request_is_unavailable_even_when_authenticated(tmp_path):
    collection = _populated_collection(tmp_path)

    result = run_agent1(
        "Je veux augmenter le plafond de ma carte", is_authenticated=True, user_id="usr_001", collection=collection
    )

    assert result["intent"] == "compte_action"
    assert result["response"] == "Ce service n'est pas disponible pour le moment."


def test_card_block_request_is_unavailable(tmp_path):
    collection = _populated_collection(tmp_path)

    result = run_agent1("Peux-tu bloquer ma carte ?", is_authenticated=True, user_id="usr_001", collection=collection)

    assert result["intent"] == "compte_action"
    assert result["response"] == "Ce service n'est pas disponible pour le moment."


def test_authenticated_personal_question_reads_banking_data(tmp_path):
    collection = _populated_collection(tmp_path)
    banking_path = str(tmp_path / "banking_graph_test.db")
    banking_db.seed_banking_data(db_path=banking_path)

    result = run_agent1(
        "Combien me reste-t-il au total ?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )

    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    # Total connu pour usr_001 : 15230.50 (courant) + 30500.00 (carnet)
    assert "45730.50" in result["response"]


def test_authenticated_personal_question_isolated_per_user(tmp_path):
    collection = _populated_collection(tmp_path)
    banking_path = str(tmp_path / "banking_graph_test.db")
    banking_db.seed_banking_data(db_path=banking_path)

    result_user1 = run_agent1(
        "Combien me reste-t-il au total ?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    result_user2 = run_agent1(
        "Combien me reste-t-il au total ?",
        is_authenticated=True,
        user_id="usr_002",
        collection=collection,
        banking_db_path=banking_path,
    )

    assert result_user1["response"] != result_user2["response"]
    assert "usr_002" not in result_user1["response"]
