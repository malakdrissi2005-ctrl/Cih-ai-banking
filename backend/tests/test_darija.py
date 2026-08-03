"""Tests de bout en bout du support Darija (arabe et Arabizi) de l'Agent 1.

Utilise le vrai pipeline `run_agent1` (détection de langue -> normalisation
-> classification -> lecture banking.db -> localisation de la réponse), avec
des bases ChromaDB/banking.db isolées (tmp_path) — jamais les vraies bases du
projet.
"""
import json

import pytest

from agents.agent1_faq.graph import run_agent1
from agents.agent1_faq.rag import get_faq_collection
from app.banking import banking_db
from scripts.ingest_faq import ingest_faq


@pytest.fixture
def collection(tmp_path):
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(
        json.dumps(
            [{"question": "Quels documents pour ouvrir un compte ?", "answer": "CIN et justificatif de domicile."}]
        ),
        encoding="utf-8",
    )
    persist_dir = str(tmp_path / "chroma")
    ingest_faq(faq_path=faq_path, persist_dir=persist_dir, collection_name="faq_darija_test")
    return get_faq_collection(persist_dir=persist_dir, collection_name="faq_darija_test")


@pytest.fixture
def banking_path(tmp_path):
    path = str(tmp_path / "banking_darija_test.db")
    banking_db.seed_banking_data(db_path=path)
    return path


# ---------------------------------------------------------------------------
# Solde en arabe et en Arabizi
# ---------------------------------------------------------------------------


def test_balance_question_in_arabic(collection, banking_path):
    result = run_agent1(
        "شحال عندي فالحساب؟", is_authenticated=True, user_id="usr_001", collection=collection, banking_db_path=banking_path
    )
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    assert "45730.50" in result["response"]  # 15230.50 (courant) + 30500.00 (carnet)


def test_balance_question_in_arabizi(collection, banking_path):
    result = run_agent1(
        "ch7al 3ndi f compte?", is_authenticated=True, user_id="usr_001", collection=collection, banking_db_path=banking_path
    )
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    assert "45730.50" in result["response"]


# ---------------------------------------------------------------------------
# Dernieres operations
# ---------------------------------------------------------------------------


def test_recent_transactions_in_darija(collection, banking_path):
    result = run_agent1(
        "وريني آخر العمليات ديالي",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert "2026-07" in result["response"]


# ---------------------------------------------------------------------------
# Salaire cette semaine
# ---------------------------------------------------------------------------


def test_salary_this_week_in_arabic(collection, banking_path):
    result = run_agent1(
        "واش دخل ليا الصالير هاد السيمانة؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "12000.00" in result["response"]
    assert "2026-07-25" in result["response"]


def test_salary_this_week_in_arabizi(collection, banking_path):
    result = run_agent1(
        "wach dkhal lia salaire had simana?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "12000.00" in result["response"]
    assert "2026-07-25" in result["response"]


# ---------------------------------------------------------------------------
# Depenses par categorie/periode
# ---------------------------------------------------------------------------


def test_restaurants_current_month_in_arabic(collection, banking_path):
    result = run_agent1(
        "شحال صرفت فالمطاعم هاد الشهر؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "286.40" in result["response"]  # 89.90 + 120.00 + 76.50


def test_restaurants_current_month_in_arabizi(collection, banking_path):
    result = run_agent1(
        "ch7al sraft f restaurant had chher?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "286.40" in result["response"]


def test_transport_last_month_in_arabic(collection, banking_path):
    result = run_agent1(
        "شحال صرفت فالنقل الشهر اللي فات؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "45.00" in result["response"]


def test_transport_last_month_in_arabizi(collection, banking_path):
    result = run_agent1(
        "ch7al sraft f transport chher li fat?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "45.00" in result["response"]


# ---------------------------------------------------------------------------
# Carte : statut, plafonds, paiement Internet, achat international
# ---------------------------------------------------------------------------


def test_card_status_in_arabic(collection, banking_path):
    result = run_agent1(
        "واش الكارط ديالي خدامة؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert result["response"]  # reponse non vide


def test_card_status_inactive_card_in_arabizi(collection, banking_path):
    # usr_004 a une carte au statut "blocked" dans le jeu de donnees fictif.
    result = run_agent1(
        "wach carte dyali khdama?",
        is_authenticated=True,
        user_id="usr_004",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "active" not in result["response"].lower() or "blocked" in result["response"].lower()


def test_payment_and_withdrawal_limits_in_arabic(collection, banking_path):
    result = run_agent1(
        "شحال هو سقف الأداء والسحب؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "5000.00" in result["response"]
    assert "2000.00" in result["response"]


def test_payment_and_withdrawal_limits_in_arabizi(collection, banking_path):
    result = run_agent1(
        "ch7al plafond dyal paiement w retrait?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "5000.00" in result["response"]
    assert "2000.00" in result["response"]


def test_online_payment_in_arabic(collection, banking_path):
    result = run_agent1(
        "واش نقدر نشري بالكارط من الإنترنت؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert result["response"]


def test_online_payment_in_arabizi(collection, banking_path):
    result = run_agent1(
        "wach n9der nchri biha mn internet?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert result["response"]


def test_international_purchase_in_arabic(collection, banking_path):
    # usr_001 : online=1, international=1
    result = run_agent1(
        "واش نقدر نشري من موقع أجنبي؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["response"]


def test_international_purchase_disabled_in_arabizi(collection, banking_path):
    # usr_002 : online=1, international=0
    result = run_agent1(
        "wach n9der nchri mn site etranger?",
        is_authenticated=True,
        user_id="usr_002",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["response"]


# ---------------------------------------------------------------------------
# Demande personnelle sans session valide
# ---------------------------------------------------------------------------


def test_personal_question_without_session_in_arabic(collection, banking_path):
    result = run_agent1("شحال عندي فالحساب؟", collection=collection, banking_db_path=banking_path)
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is True
    assert "خاصك" in result["response"]


def test_personal_question_without_session_in_arabizi(collection, banking_path):
    result = run_agent1("ch7al 3ndi f compte?", collection=collection, banking_db_path=banking_path)
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is True
    assert "khassk" in result["response"].lower()


# ---------------------------------------------------------------------------
# Action de virement/carte indisponible
# ---------------------------------------------------------------------------


def test_virement_unavailable_in_arabic(collection, banking_path):
    result = run_agent1(
        "حول ليا 500 درهم", is_authenticated=True, user_id="usr_001", collection=collection, banking_db_path=banking_path
    )
    assert result["intent"] == "virement"
    assert "متوفراش" in result["response"]


def test_virement_unavailable_in_arabizi(collection, banking_path):
    result = run_agent1(
        "bghit n7awel 500 MAD",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "virement"
    assert "mtwafrach" in result["response"].lower()


def test_card_block_action_unavailable_in_arabic(collection, banking_path):
    result = run_agent1(
        "بلوكي ليا الكارط", is_authenticated=True, user_id="usr_001", collection=collection, banking_db_path=banking_path
    )
    assert result["intent"] == "compte_action"
    assert "متوفراش" in result["response"]


def test_card_limit_increase_action_unavailable_in_arabizi(collection, banking_path):
    result = run_agent1(
        "zid lia plafond dyal carte",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "compte_action"
    assert "mtwafrach" in result["response"].lower()


# ---------------------------------------------------------------------------
# Isolation entre deux utilisateurs (en Darija)
# ---------------------------------------------------------------------------


def test_isolation_between_users_in_darija(collection, banking_path):
    result_1 = run_agent1(
        "شحال عندي فالحساب؟", is_authenticated=True, user_id="usr_001", collection=collection, banking_db_path=banking_path
    )
    result_2 = run_agent1(
        "شحال عندي فالحساب؟", is_authenticated=True, user_id="usr_002", collection=collection, banking_db_path=banking_path
    )
    assert result_1["response"] != result_2["response"]
    assert "45730.50" in result_1["response"]
    assert "45730.50" not in result_2["response"]
    assert "11094.10" in result_2["response"]


# ---------------------------------------------------------------------------
# Conservation exacte des montants (pas de float, pas de modification)
# ---------------------------------------------------------------------------


def test_amounts_are_preserved_exactly_across_languages(collection, banking_path):
    result_fr = run_agent1(
        "Combien ai-je dépensé dans les restaurants ce mois-ci ?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    result_ar = run_agent1(
        "شحال صرفت فالمطاعم هاد الشهر؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    result_latn = run_agent1(
        "ch7al sraft f restaurant had chher?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "286.40" in result_fr["response"]
    assert "286.40" in result_ar["response"]
    assert "286.40" in result_latn["response"]


# ---------------------------------------------------------------------------
# Les questions francaises restent inchangees
# ---------------------------------------------------------------------------


def test_french_questions_still_work_unchanged(collection, banking_path):
    result = run_agent1(
        "Combien me reste-t-il au total ?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert "Le total de vos comptes est de 45730.50 MAD" in result["response"]


def test_french_public_faq_still_works(collection):
    result = run_agent1("Quels documents pour ouvrir un compte ?", collection=collection)
    assert result["intent"] == "faq_generale"
    assert "CIN" in result["response"]
