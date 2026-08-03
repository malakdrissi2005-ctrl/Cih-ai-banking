"""Tests des outils internes (agents/agent1_faq/tools.py) — la seule surface
que le LLM Router est autorisé à choisir ; jamais d'accès direct à `banking_db`
ou `auth.db` depuis le LLM lui-même."""
import json

import pytest

from agents.agent1_faq import tools
from agents.agent1_faq.rag import get_faq_collection
from app.banking import banking_db
from scripts.ingest_faq import ingest_faq


@pytest.fixture
def banking_path(tmp_path):
    path = str(tmp_path / "tools_test.db")
    banking_db.seed_banking_data(db_path=path)
    return path


@pytest.fixture
def faq_collection(tmp_path):
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(
        json.dumps([{"question": "Comment ouvrir un compte ?", "answer": "Rendez-vous en agence avec une pièce d'identité."}]),
        encoding="utf-8",
    )
    persist_dir = str(tmp_path / "chroma")
    ingest_faq(faq_path=faq_path, persist_dir=persist_dir, collection_name="tools_test_faq")
    return get_faq_collection(persist_dir=persist_dir, collection_name="tools_test_faq")


def test_search_public_faq_finds_match(faq_collection):
    match = tools.search_public_faq("Comment ouvrir un compte ?", collection=faq_collection)
    assert match is not None
    assert "agence" in match["answer"]


def test_get_account_balance_returns_real_data(banking_path):
    data = tools.get_account_balance("usr_001", db_path=banking_path)
    assert data["total"] == banking_db.get_total_balance("usr_001", db_path=banking_path)
    assert len(data["accounts"]) == 2


def test_get_transactions_returns_customer_transactions(banking_path):
    transactions = tools.get_transactions("usr_001", limit=5, db_path=banking_path)
    assert len(transactions) == 5
    assert all(tx["transaction_id"].startswith("tx_001") for tx in transactions)


def test_get_card_information_returns_card(banking_path):
    card = tools.get_card_information("usr_001", db_path=banking_path)
    assert card["status"] == "active"


def test_get_beneficiaries_returns_beneficiaries(banking_path):
    beneficiaries = tools.get_beneficiaries("usr_001", db_path=banking_path)
    assert len(beneficiaries) == 2
    assert all(b["display_name"].startswith("Bénéficiaire Démo 1") for b in beneficiaries)


def test_get_spending_summary_matches_banking_db(banking_path):
    summary = tools.get_spending_summary("usr_001", category="Restaurants", period="current_month", db_path=banking_path)
    expected = banking_db.get_spending_total(
        "usr_001", category="Restaurants", year_month=banking_db.DEMO_CURRENT_MONTH, db_path=banking_path
    )
    assert summary == expected


def test_get_spending_summary_all_categories(banking_path):
    summary = tools.get_spending_summary("usr_001", category=None, period="current_month", db_path=banking_path)
    assert summary > 0


def test_tools_isolate_data_between_users(banking_path):
    balance_1 = tools.get_account_balance("usr_001", db_path=banking_path)
    balance_2 = tools.get_account_balance("usr_002", db_path=banking_path)
    assert balance_1["total"] != balance_2["total"]
