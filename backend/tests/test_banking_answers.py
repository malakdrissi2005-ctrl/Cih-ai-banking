"""Tests de la formulation multi-intentions des réponses bancaires personnelles
(agents/agent1_faq/banking_answers.py)."""
import pytest

from agents.agent1_faq.banking_answers import build_personal_data_answer, classify_personal_intent
from app.banking import banking_db


@pytest.fixture
def banking_path(tmp_path):
    path = str(tmp_path / "banking_answers_test.db")
    banking_db.seed_banking_data(db_path=path)
    return path


# ---------------------------------------------------------------------------
# 1. Questions combinées sur la carte (multi-intentions)
# ---------------------------------------------------------------------------


def test_classify_status_and_both_limits_together():
    parsed = classify_personal_intent(
        "Donne-moi le statut actuel de ma carte ainsi que ses plafonds de paiement et de retrait."
    )
    assert parsed["intent"] == "card_information"
    assert set(parsed["requested_fields"]) == {"status", "payment_limit", "withdrawal_limit"}


def test_status_and_limits_returns_complete_answer(banking_path):
    answer = build_personal_data_answer(
        "Donne-moi le statut actuel de ma carte ainsi que ses plafonds de paiement et de retrait.",
        "usr_001",
        banking_path,
    )
    assert "active" in answer.lower()
    assert "5000.00" in answer
    assert "2000.00" in answer


def test_status_and_online_payment_active_card(banking_path):
    answer = build_personal_data_answer(
        "Ma carte est-elle active et autorisée pour les paiements sur Internet ?", "usr_001", banking_path
    )
    assert "active" in answer.lower()
    assert "autorises" in answer.lower() or "autorisés" in answer.lower() or "autorise" in answer.lower()


def test_status_for_blocked_card(banking_path):
    # usr_004 a une carte au statut "blocked" dans le jeu de donnees fictif.
    answer = build_personal_data_answer("Quel est le statut actuel de ma carte ?", "usr_004", banking_path)
    assert "active" not in answer.lower()
    assert "blocked" in answer.lower()


def test_foreign_site_purchase_checks_ecommerce_and_international_both_enabled(banking_path):
    # usr_001 : online=1, international=1
    answer = build_personal_data_answer(
        "Est-ce que je peux utiliser ma carte pour effectuer un achat sur un site étranger ?", "usr_001", banking_path
    )
    assert answer == "Oui, votre carte autorise les paiements en ligne et les achats internationaux."


def test_foreign_site_purchase_ecommerce_enabled_but_international_disabled(banking_path):
    # usr_002 : online=1, international=0
    answer = build_personal_data_answer(
        "Est-ce que je peux utiliser ma carte pour effectuer un achat sur un site étranger ?", "usr_002", banking_path
    )
    assert answer == "Non, votre carte autorise les paiements en ligne, mais les achats internationaux sont désactivés."


def test_both_limits_without_status(banking_path):
    answer = build_personal_data_answer(
        "Quels sont actuellement le plafond de paiement et le plafond de retrait associés à ma carte ?",
        "usr_001",
        banking_path,
    )
    assert "5000.00" in answer
    assert "2000.00" in answer


def test_online_and_international_payments_check(banking_path):
    answer = build_personal_data_answer(
        "Vérifie si ma carte autorise les paiements en ligne et les paiements internationaux.", "usr_001", banking_path
    )
    assert answer == "Oui, votre carte autorise les paiements en ligne et les achats internationaux."


def test_card_multi_intent_never_returns_partial_answer(banking_path):
    answer = build_personal_data_answer(
        "Donne-moi le statut actuel de ma carte ainsi que ses plafonds de paiement et de retrait.",
        "usr_001",
        banking_path,
    )
    # Les trois informations demandees doivent toutes apparaitre.
    assert "active" in answer.lower()
    assert "5000.00" in answer
    assert "2000.00" in answer


# ---------------------------------------------------------------------------
# 2. Questions sur les depenses par categorie
# ---------------------------------------------------------------------------


def test_classify_spending_extracts_category_and_period():
    parsed = classify_personal_intent("Combien ai-je dépensé dans les restaurants pendant le mois en cours ?")
    assert parsed == {"intent": "spending_by_category", "category": "Restaurants", "period": "current_month"}


@pytest.mark.parametrize(
    "message",
    [
        "Combien ai-je dépensé dans les restaurants pendant le mois en cours ?",
        "Combien ai-je dépensé dans les restaurants ce mois-ci ?",
    ],
)
def test_restaurants_current_month(banking_path, message):
    answer = build_personal_data_answer(message, "usr_001", banking_path)
    # 89.90 + 120.00 + 76.50 = 286.40
    assert "286.40" in answer
    assert "Restaurants" in answer


@pytest.mark.parametrize(
    "message",
    [
        "Quel montant ai-je consacré au transport le mois dernier ?",
        "Combien ai-je dépensé en transport durant le mois précédent ?",
    ],
)
def test_transport_last_month(banking_path, message):
    answer = build_personal_data_answer(message, "usr_001", banking_path)
    assert "45.00" in answer
    assert "Transport" in answer


def test_transport_current_month_is_zero(banking_path):
    answer = build_personal_data_answer(
        "Combien ai-je dépensé en transport ce mois-ci ?", "usr_001", banking_path
    )
    assert "aucune depense" in answer.lower().replace("é", "e") or "aucune dépense" in answer
    assert "Transport" in answer


def test_supermarket_category_plural_and_accent(banking_path):
    answer = build_personal_data_answer("Combien ai-je dépensé dans les supermarchés ce mois-ci ?", "usr_001", banking_path)
    assert "Courses" in answer  # categorie canonique en base
    assert "300.00" in answer


def test_category_synonym_alimentation(banking_path):
    answer = build_personal_data_answer("Combien ai-je dépensé en alimentation ce mois-ci ?", "usr_001", banking_path)
    assert "Courses" in answer
    assert "300.00" in answer


def test_period_wording_mois_actuel(banking_path):
    parsed = classify_personal_intent("Combien ai-je dépensé dans les restaurants mois actuel ?")
    assert parsed["period"] == "current_month"


def test_period_wording_mois_passe(banking_path):
    parsed = classify_personal_intent("Combien ai-je dépensé dans les restaurants le mois passé ?")
    assert parsed["period"] == "last_month"


def test_zero_spending_message_is_explicit(banking_path):
    answer = build_personal_data_answer("Combien ai-je dépensé en transport ce mois-ci ?", "usr_002", banking_path)
    assert "Transport" in answer
    assert "0.00" not in answer  # la phrase doit etre explicite, pas juste "0.00 MAD"
    assert "aucune" in answer.lower()


def test_spending_never_includes_credits_or_salary(banking_path):
    # Le salaire (12000.00) et le virement recu (2000.00) ne doivent jamais
    # etre confondus avec une categorie de depense.
    answer = build_personal_data_answer("Combien ai-je dépensé dans les restaurants ce mois-ci ?", "usr_001", banking_path)
    assert "12000.00" not in answer
    assert "2000.00" not in answer


# ---------------------------------------------------------------------------
# Isolation entre utilisateurs / absence de session
# ---------------------------------------------------------------------------


def test_isolation_between_users_for_spending(banking_path):
    answer_1 = build_personal_data_answer("Combien ai-je dépensé dans les restaurants ce mois-ci ?", "usr_001", banking_path)
    answer_2 = build_personal_data_answer("Combien ai-je dépensé dans les restaurants ce mois-ci ?", "usr_002", banking_path)
    assert answer_1 != answer_2
    assert "286.40" in answer_1
    assert "286.40" not in answer_2


def test_isolation_between_users_for_card(banking_path):
    answer_1 = build_personal_data_answer("Quel est le statut actuel de ma carte ?", "usr_001", banking_path)
    answer_2 = build_personal_data_answer("Quel est le statut actuel de ma carte ?", "usr_004", banking_path)
    assert "active" in answer_1.lower()
    assert "blocked" in answer_2.lower()
    assert answer_1 != answer_2


def test_missing_user_id_falls_back_gracefully(banking_path):
    answer = build_personal_data_answer("Quel est mon solde ?", None, banking_path)
    assert answer  # ne leve jamais d'exception, renvoie un message generique
