"""Tests du schéma bancaire métier (backend/app/banking/banking_db.py).

Base isolée par test (tmp_path) — jamais le vrai `backend/data/demo_bancaire.db`
du projet.

Ce fichier est le SEUL à interroger le schéma PHYSIQUE en SQL brut (noms de
tables et de colonnes). Tous les autres tests passent par les fonctions
publiques de `banking_db`, dont les clés de retour sont inchangées — c'est ce
qui a permis de renommer les tables sans toucher une seule de leurs
assertions.

Schéma cible : `CLIENT`, `UTILISATEUR_E_BANKING`, `COMPTE_BANCAIRE`,
`CARTE_BANCAIRE`, `TRANSACTION`, `BENEFICIAIRE`, plus `account_balance_history`
conservée (elle alimente `get_balance_at_date`, hors spécification cible mais
indispensable à une fonctionnalité existante et testée).

`TRANSACTION` étant un mot réservé SQL, la table est toujours citée entre
guillemets doubles.
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
        "CLIENT",
        "UTILISATEUR_E_BANKING",
        "COMPTE_BANCAIRE",
        "account_balance_history",
        "TRANSACTION",
        "BENEFICIAIRE",
        "CARTE_BANCAIRE",
    }.issubset(tables)


def test_legacy_tables_are_never_created_by_the_new_schema(db_path):
    """Non-régression de migration : l'ancien schéma ne doit plus apparaître.

    Sa conversion est le rôle explicite de `scripts/migrate_banking_database.py`,
    jamais un effet de bord de `init_db`."""
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}

    assert not {"customers", "accounts", "transactions", "cards", "beneficiaries"} & tables


def test_each_user_has_a_courant_and_a_carnet_account(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT id_client, type_compte FROM COMPTE_BANCAIRE").fetchall()

    assert len(rows) == 10  # 2 comptes x 5 utilisateurs
    for customer_id in EXPECTED_USER_IDS:
        types = {type_compte for cid, type_compte in rows if cid == customer_id}
        assert types == {"courant", "carnet"}


def test_every_account_has_a_rib_and_an_iban(db_path):
    """Nouveaux champs du schéma réaliste — déterministes, jamais aléatoires."""
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT rib, iban, numero_compte FROM COMPTE_BANCAIRE").fetchall()

    assert len(rows) == 10
    for rib, iban, numero_compte in rows:
        assert len(rib) == 24 and rib.isdigit()
        assert iban.startswith("MA") and len(iban) == 28
        assert len(numero_compte) == 16


def test_rib_generation_is_deterministic(db_path):
    """Deux ré-exécutions du seed doivent produire exactement les mêmes RIB."""
    banking_db.seed_banking_data(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        first = dict(conn.execute("SELECT id_compte, rib FROM COMPTE_BANCAIRE").fetchall())

    banking_db.seed_banking_data(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        second = dict(conn.execute("SELECT id_compte, rib FROM COMPTE_BANCAIRE").fetchall())

    assert first == second


def test_client_table_holds_identity_fields(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT nom, prenom, telephone_mobile, email, statut_client "
            "FROM CLIENT WHERE id_client = 'usr_001'"
        ).fetchone()

    assert row is not None
    nom, prenom, telephone, email, statut = row
    assert prenom and nom
    assert telephone and email
    assert statut == "actif"


def test_total_balance_across_accounts(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT solde_disponible FROM COMPTE_BANCAIRE WHERE id_client = 'usr_001'"
        ).fetchall()

    total = sum(Decimal(balance) for (balance,) in rows)
    # Solde courant + solde carnet, valeurs connues du jeu de données usr_001
    assert total == Decimal("15230.50") + Decimal("30500.00")


def test_transactions_by_category_and_period(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT montant FROM "TRANSACTION"
            JOIN COMPTE_BANCAIRE ON COMPTE_BANCAIRE.id_compte = "TRANSACTION".id_compte
            WHERE COMPTE_BANCAIRE.id_client = 'usr_001'
              AND "TRANSACTION".categorie = 'Restaurants'
              AND substr("TRANSACTION".date_operation, 1, 7) = ?
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
                SELECT "TRANSACTION".id_transaction FROM "TRANSACTION"
                JOIN COMPTE_BANCAIRE ON COMPTE_BANCAIRE.id_compte = "TRANSACTION".id_compte
                WHERE COMPTE_BANCAIRE.id_client = ?
                  AND "TRANSACTION".type_operation = 'card_payment'
                  AND substr("TRANSACTION".date_operation, 1, 7) = ?
                """,
                (customer_id, banking_db.DEMO_LAST_MONTH),
            ).fetchall()
            assert len(rows) >= 1


def test_balance_at_a_past_date_is_retrievable(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT solde FROM account_balance_history
            WHERE id_compte = 'acc_001_courant' AND as_of_date = '2026-01-01'
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
                SELECT "TRANSACTION".date_operation, "TRANSACTION".id_compte_lie
                FROM "TRANSACTION"
                JOIN COMPTE_BANCAIRE ON COMPTE_BANCAIRE.id_compte = "TRANSACTION".id_compte
                WHERE COMPTE_BANCAIRE.id_client = ?
                  AND "TRANSACTION".type_operation = 'incoming_transfer'
                """,
                (customer_id,),
            ).fetchall()
            assert len(rows) == 1
            date_operation, id_compte_lie = rows[0]
            assert date_operation >= banking_db.DEMO_THIS_WEEK_START
            assert id_compte_lie is not None and id_compte_lie.endswith("_carnet")


def test_salary_credit_date_is_retrievable(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT date_operation, montant FROM "TRANSACTION"
            WHERE id_transaction = 'tx_001_salary'
            """
        ).fetchone()

    assert row is not None
    date_operation, montant = row
    assert date_operation == "2026-07-25"
    assert Decimal(montant) == Decimal("12000.00")


def test_last_direct_debit_is_unambiguous(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        for customer_id in EXPECTED_USER_IDS:
            row = conn.execute(
                """
                SELECT "TRANSACTION".date_operation, "TRANSACTION".libelle
                FROM "TRANSACTION"
                JOIN COMPTE_BANCAIRE ON COMPTE_BANCAIRE.id_compte = "TRANSACTION".id_compte
                WHERE COMPTE_BANCAIRE.id_client = ?
                  AND "TRANSACTION".type_operation = 'direct_debit'
                  AND COMPTE_BANCAIRE.type_compte = 'courant'
                ORDER BY "TRANSACTION".date_operation DESC
                LIMIT 1
                """,
                (customer_id,),
            ).fetchone()
            assert row is not None
            date_operation, libelle = row
            assert date_operation == "2026-07-20"
            assert "abonnement" in libelle.lower()


def test_card_settings_per_user(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT COMPTE_BANCAIRE.id_client,
                   CARTE_BANCAIRE.paiement_international_actif,
                   CARTE_BANCAIRE.plafond_paiement
            FROM CARTE_BANCAIRE
            JOIN COMPTE_BANCAIRE ON COMPTE_BANCAIRE.id_compte = CARTE_BANCAIRE.id_compte
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
        rows = conn.execute("SELECT plafond_paiement, plafond_retrait FROM CARTE_BANCAIRE").fetchall()

    assert len(rows) == 5
    for plafond_paiement, plafond_retrait in rows:
        assert Decimal(plafond_paiement) > 0
        assert Decimal(plafond_retrait) > 0


def test_card_number_is_stored_masked_only(db_path):
    """Sécurité : la base ne doit jamais contenir de numéro de carte en clair."""
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT numero_carte_masque FROM CARTE_BANCAIRE").fetchall()

    assert len(rows) == 5
    for (numero,) in rows:
        digits = "".join(char for char in numero if char.isdigit())
        # Un PAN complet fait 16 chiffres : le stockage masqué doit en exposer
        # strictement moins.
        assert len(digits) < 16


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
        assert conn.execute("SELECT COUNT(*) FROM COMPTE_BANCAIRE").fetchone()[0] == 10
        assert conn.execute("SELECT COUNT(DISTINCT id_compte) FROM COMPTE_BANCAIRE").fetchone()[0] == 10
        assert conn.execute('SELECT COUNT(*) FROM "TRANSACTION"').fetchone()[0] == 75
        assert conn.execute('SELECT COUNT(DISTINCT id_transaction) FROM "TRANSACTION"').fetchone()[0] == 75
        assert conn.execute("SELECT COUNT(*) FROM account_balance_history").fetchone()[0] == 30
        assert conn.execute("SELECT COUNT(*) FROM CARTE_BANCAIRE").fetchone()[0] == 5


def test_amounts_are_stored_as_exact_decimal_strings_not_float(db_path):
    banking_db.seed_banking_data(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        balance_row = conn.execute(
            "SELECT solde_disponible, typeof(solde_disponible) FROM COMPTE_BANCAIRE "
            "WHERE id_compte = 'acc_001_courant'"
        ).fetchone()
        history_row = conn.execute(
            "SELECT solde, typeof(solde) FROM account_balance_history "
            "WHERE id_compte = 'acc_001_courant' AND as_of_date = '2026-01-01'"
        ).fetchone()
        tx_row = conn.execute(
            'SELECT montant, typeof(montant) FROM "TRANSACTION" WHERE id_transaction = \'tx_001_salary\''
        ).fetchone()
        card_row = conn.execute(
            "SELECT plafond_paiement, typeof(plafond_paiement) FROM CARTE_BANCAIRE WHERE id_carte = 'card_001'"
        ).fetchone()

    for value, sqlite_type in (balance_row, history_row, tx_row, card_row):
        assert sqlite_type == "text"

    assert Decimal(balance_row[0]) == Decimal("15230.50")
    assert Decimal(history_row[0]) == Decimal("9000.00")
    assert Decimal(tx_row[0]) == Decimal("12000.00")
    assert Decimal(card_row[0]) == Decimal("5000.00")


def test_auth_db_and_public_chat_still_work(tmp_path):
    """Vérifie que la base bancaire n'interfère ni avec auth.db ni avec l'Agent 1 public."""
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
