"""Tests de la base bancaire fictive enrichie `banking.db` (backend/app/banking/banking_db.py).

Base isolée par test (tmp_path) — jamais le vrai `backend/data/banking.db` du projet.
"""
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from app.banking import banking_db

EXPECTED_USER_IDS = {"usr_001", "usr_002", "usr_003", "usr_004", "usr_005"}


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "banking_test.db")


def test_seed_creates_the_database_file(db_path):
    assert not Path(db_path).exists()
    banking_db.seed_banking_data(db_path=db_path)
    assert Path(db_path).exists()


def test_seed_creates_expected_tables(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}

    assert {
        "customers",
        "accounts",
        "account_balance_history",
        "transactions",
        "beneficiaries",
        "cards",
    }.issubset(tables)


def test_each_user_has_a_courant_and_a_carnet_account(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT customer_id, account_type FROM accounts").fetchall()

    assert len(rows) == 10  # 2 comptes x 5 utilisateurs
    for customer_id in EXPECTED_USER_IDS:
        types = {account_type for cid, account_type in rows if cid == customer_id}
        assert types == {"courant", "carnet"}


def test_total_balance_across_accounts(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT balance FROM accounts WHERE customer_id = 'usr_001'"
        ).fetchall()

    total = sum(Decimal(balance) for (balance,) in rows)
    # Solde courant + solde carnet, valeurs connues du jeu de données usr_001
    assert total == Decimal("15230.50") + Decimal("30500.00")


def test_transactions_by_category_and_period(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT amount FROM transactions
            JOIN accounts ON accounts.account_id = transactions.account_id
            WHERE accounts.customer_id = 'usr_001'
              AND transactions.category = 'Restaurants'
              AND substr(transactions.transaction_date, 1, 7) = ?
            """,
            (banking_db.DEMO_CURRENT_MONTH,),
        ).fetchall()

    total_spent = sum(Decimal(amount) for (amount,) in rows)
    assert len(rows) == 3
    assert total_spent == Decimal("89.90") + Decimal("120.00") + Decimal("76.50")


def test_payments_from_last_month_are_retrievable(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        for customer_id in EXPECTED_USER_IDS:
            rows = conn.execute(
                """
                SELECT transactions.transaction_id FROM transactions
                JOIN accounts ON accounts.account_id = transactions.account_id
                WHERE accounts.customer_id = ?
                  AND transactions.transaction_type = 'card_payment'
                  AND substr(transactions.transaction_date, 1, 7) = ?
                """,
                (customer_id, banking_db.DEMO_LAST_MONTH),
            ).fetchall()
            assert len(rows) >= 1


def test_balance_at_a_past_date_is_retrievable(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT balance FROM account_balance_history
            WHERE account_id = 'acc_001_courant' AND as_of_date = '2026-01-01'
            """
        ).fetchone()

    assert row is not None
    assert Decimal(row[0]) == Decimal("9000.00")


def test_incoming_transfer_received_this_week(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        for customer_id in EXPECTED_USER_IDS:
            rows = conn.execute(
                """
                SELECT transactions.transaction_date, transactions.related_account_id
                FROM transactions
                JOIN accounts ON accounts.account_id = transactions.account_id
                WHERE accounts.customer_id = ?
                  AND transactions.transaction_type = 'incoming_transfer'
                """,
                (customer_id,),
            ).fetchall()
            assert len(rows) == 1
            transaction_date, related_account_id = rows[0]
            assert transaction_date >= banking_db.DEMO_THIS_WEEK_START
            assert related_account_id is not None and related_account_id.endswith("_carnet")


def test_salary_credit_date_is_retrievable(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT transaction_date, amount FROM transactions
            WHERE transaction_id = 'tx_001_salary'
            """
        ).fetchone()

    assert row is not None
    transaction_date, amount = row
    assert transaction_date == "2026-07-25"
    assert Decimal(amount) == Decimal("12000.00")


def test_last_direct_debit_is_unambiguous(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        for customer_id in EXPECTED_USER_IDS:
            row = conn.execute(
                """
                SELECT transactions.transaction_date, transactions.description
                FROM transactions
                JOIN accounts ON accounts.account_id = transactions.account_id
                WHERE accounts.customer_id = ?
                  AND transactions.transaction_type = 'direct_debit'
                  AND accounts.account_type = 'courant'
                ORDER BY transactions.transaction_date DESC
                LIMIT 1
                """,
                (customer_id,),
            ).fetchone()
            assert row is not None
            transaction_date, description = row
            assert transaction_date == "2026-07-20"
            assert "abonnement" in description.lower()


def test_card_settings_per_user(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT accounts.customer_id, cards.international_payments_enabled, cards.payment_limit
            FROM cards
            JOIN accounts ON accounts.account_id = cards.account_id
            """
        ).fetchall()

    assert len(rows) == 5
    by_customer = {customer_id: (intl, Decimal(limit)) for customer_id, intl, limit in rows}
    assert by_customer["usr_002"][0] == 0  # achats internationaux desactives pour cet utilisateur
    assert by_customer["usr_001"][0] == 1  # actives pour un autre
    assert by_customer["usr_001"][1] == Decimal("5000.00")


def test_card_limits_are_present_for_every_user(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT payment_limit, withdrawal_limit FROM cards").fetchall()

    assert len(rows) == 5
    for payment_limit, withdrawal_limit in rows:
        assert Decimal(payment_limit) > 0
        assert Decimal(withdrawal_limit) > 0


def test_reseeding_does_not_create_duplicates(db_path):
    banking_db.seed_banking_data(db_path=db_path)
    stats = banking_db.seed_banking_data(db_path=db_path)

    assert stats["customers_in_db"] == 5
    assert stats["accounts_in_db"] == 10
    assert stats["balance_history_in_db"] == 30
    assert stats["transactions_in_db"] == 75
    assert stats["beneficiaries_in_db"] == 10
    assert stats["cards_in_db"] == 5
    assert stats["changes"]["accounts"]["inserted"] == 0
    assert stats["changes"]["transactions"]["inserted"] == 0

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 10
        assert conn.execute("SELECT COUNT(DISTINCT account_id) FROM accounts").fetchone()[0] == 10
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 75
        assert conn.execute("SELECT COUNT(DISTINCT transaction_id) FROM transactions").fetchone()[0] == 75
        assert conn.execute("SELECT COUNT(*) FROM account_balance_history").fetchone()[0] == 30
        assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 5


def test_amounts_are_stored_as_exact_decimal_strings_not_float(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        balance_row = conn.execute(
            "SELECT balance, typeof(balance) FROM accounts WHERE account_id = 'acc_001_courant'"
        ).fetchone()
        history_row = conn.execute(
            "SELECT balance, typeof(balance) FROM account_balance_history "
            "WHERE account_id = 'acc_001_courant' AND as_of_date = '2026-01-01'"
        ).fetchone()
        tx_row = conn.execute(
            "SELECT amount, typeof(amount) FROM transactions WHERE transaction_id = 'tx_001_salary'"
        ).fetchone()
        card_row = conn.execute(
            "SELECT payment_limit, typeof(payment_limit) FROM cards WHERE card_id = 'card_001'"
        ).fetchone()

    for value, sqlite_type in (balance_row, history_row, tx_row, card_row):
        assert sqlite_type == "text"

    assert Decimal(balance_row[0]) == Decimal("15230.50")
    assert Decimal(history_row[0]) == Decimal("9000.00")
    assert Decimal(tx_row[0]) == Decimal("12000.00")
    assert Decimal(card_row[0]) == Decimal("5000.00")


def test_auth_db_and_public_chat_still_work(tmp_path):
    """Vérifie que banking.db n'interfère ni avec auth.db ni avec l'Agent 1 public."""
    import json

    from app.security import session_manager

    auth_db_path = str(tmp_path / "auth_regression.db")
    seed_path = tmp_path / "users_seed.json"
    seed_path.write_text(
        json.dumps([{"user_id": "usr_001", "username": "client001", "display_name": "Client Démo 1", "status": "active"}]),
        encoding="utf-8",
    )

    stats = session_manager.seed_users(seed_path=seed_path, db_path=auth_db_path, default_password="Demo1234!Test")
    assert stats["users_in_db"] == 1

    user = session_manager.verify_credentials("client001", "Demo1234!Test", db_path=auth_db_path)
    assert user is not None
    assert user["user_id"] == "usr_001"

    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "Quels documents pour ouvrir un compte ?"})
    assert response.status_code == 200
    assert response.json()["intent"] == "faq_generale"
