"""Tests de la base de démonstration 100 clients (scripts/seed_demo_database.py).

Vérifie les six garanties exigées pour la démonstration ACP/OCP :
1. schéma conforme,
2. `CL0001` réservé au compte de démonstration,
3. les 100 clients possèdent TOUTES les entités,
4. génération strictement déterministe,
5. bcrypt uniquement, jamais de mot de passe en clair,
6. numéros de carte stockés masqués.

Base générée dans `tmp_path` — jamais le vrai `backend/data/demo_bancaire.db`.
La génération étant coûteuse (~3 000 transactions + 2 hashs bcrypt), la
fixture est de portée `module` : construite une seule fois pour tout le
fichier.
"""
import sqlite3

import bcrypt
import pytest

from scripts.seed_demo_database import (
    DEMO_CLIENT_ID,
    DEMO_EMAIL,
    DEMO_LOGIN,
    DEMO_NOM,
    DEMO_PASSWORD,
    DEMO_PRENOM,
    DEMO_TELEPHONE,
    FIXTURE_PASSWORD,
    NB_CLIENTS,
    seed_demo_database,
)


@pytest.fixture(scope="module")
def demo_db(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("demo") / "demo_bancaire.db")
    seed_demo_database(db_path=path)
    return path


def _query(db_path, sql, params=()):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------------------
# 1. Schéma
# ---------------------------------------------------------------------------


def test_schema_contains_all_target_tables(demo_db):
    tables = {row[0] for row in _query(demo_db, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {
        "CLIENT",
        "UTILISATEUR_E_BANKING",
        "COMPTE_BANCAIRE",
        "CARTE_BANCAIRE",
        "TRANSACTION",
        "BENEFICIAIRE",
        "account_balance_history",
    }.issubset(tables)


# ---------------------------------------------------------------------------
# 2. CL0001 réservé à Malak Drissi
# ---------------------------------------------------------------------------


def test_cl0001_is_the_demo_client(demo_db):
    row = _query(demo_db, "SELECT * FROM CLIENT WHERE id_client = ?", (DEMO_CLIENT_ID,))[0]
    assert row["nom"] == DEMO_NOM
    assert row["prenom"] == DEMO_PRENOM
    assert row["email"] == DEMO_EMAIL
    assert row["telephone_mobile"] == DEMO_TELEPHONE
    assert row["statut_client"] == "actif"


def test_demo_identity_is_unique_across_the_hundred_clients(demo_db):
    """Aucun client généré ne doit usurper l'identité de démonstration."""
    assert len(_query(demo_db, "SELECT 1 FROM CLIENT WHERE nom = ? AND prenom = ?", (DEMO_NOM, DEMO_PRENOM))) == 1
    assert len(_query(demo_db, "SELECT 1 FROM CLIENT WHERE email = ?", (DEMO_EMAIL,))) == 1


def test_demo_client_has_a_working_ebanking_account(demo_db):
    row = _query(
        demo_db, "SELECT * FROM UTILISATEUR_E_BANKING WHERE id_client = ?", (DEMO_CLIENT_ID,)
    )[0]
    assert row["identifiant_connexion"] == DEMO_LOGIN
    assert row["statut_connexion"] == "actif"
    assert bcrypt.checkpw(DEMO_PASSWORD.encode("utf-8"), row["mot_de_passe_hash"].encode("utf-8"))


def test_demo_client_password_does_not_open_other_accounts(demo_db):
    """Le mot de passe de démonstration doit être propre à CL0001."""
    others = _query(
        demo_db, "SELECT mot_de_passe_hash FROM UTILISATEUR_E_BANKING WHERE id_client != ? LIMIT 5", (DEMO_CLIENT_ID,)
    )
    for row in others:
        assert not bcrypt.checkpw(DEMO_PASSWORD.encode("utf-8"), row["mot_de_passe_hash"].encode("utf-8"))


# ---------------------------------------------------------------------------
# 3. Complétude : 100 clients, toutes les entités
# ---------------------------------------------------------------------------


def test_exactly_one_hundred_clients_and_one_ebanking_account_each(demo_db):
    assert _query(demo_db, "SELECT COUNT(*) c FROM CLIENT")[0]["c"] == NB_CLIENTS
    assert _query(demo_db, "SELECT COUNT(*) c FROM UTILISATEUR_E_BANKING")[0]["c"] == NB_CLIENTS


def test_every_client_has_all_required_entities(demo_db):
    """Aucun client ne doit être incomplet : compte, carte, transactions et
    bénéficiaires sont tous obligatoires."""
    complete = _query(
        demo_db,
        """
        SELECT COUNT(*) c FROM CLIENT c
        WHERE EXISTS (SELECT 1 FROM UTILISATEUR_E_BANKING WHERE id_client = c.id_client)
          AND EXISTS (SELECT 1 FROM COMPTE_BANCAIRE WHERE id_client = c.id_client)
          AND EXISTS (SELECT 1 FROM CARTE_BANCAIRE ca
                      JOIN COMPTE_BANCAIRE co ON co.id_compte = ca.id_compte
                      WHERE co.id_client = c.id_client)
          AND EXISTS (SELECT 1 FROM "TRANSACTION" t
                      JOIN COMPTE_BANCAIRE co ON co.id_compte = t.id_compte
                      WHERE co.id_client = c.id_client)
          AND EXISTS (SELECT 1 FROM BENEFICIAIRE WHERE id_client = c.id_client)
        """,
    )[0]["c"]
    assert complete == NB_CLIENTS


def test_account_count_per_client_is_between_one_and_three(demo_db):
    row = _query(
        demo_db, "SELECT MIN(n) mn, MAX(n) mx FROM (SELECT COUNT(*) n FROM COMPTE_BANCAIRE GROUP BY id_client)"
    )[0]
    assert row["mn"] >= 1
    assert row["mx"] <= 3


def test_every_client_has_a_current_account(demo_db):
    """Le compte courant porte la carte et les transactions : il est obligatoire."""
    missing = _query(
        demo_db,
        "SELECT COUNT(*) c FROM CLIENT c WHERE NOT EXISTS "
        "(SELECT 1 FROM COMPTE_BANCAIRE WHERE id_client = c.id_client AND type_compte = 'courant')",
    )[0]["c"]
    assert missing == 0


def test_transaction_count_per_client_is_between_ten_and_fifty(demo_db):
    row = _query(
        demo_db,
        'SELECT MIN(n) mn, MAX(n) mx FROM (SELECT COUNT(*) n FROM "TRANSACTION" t '
        "JOIN COMPTE_BANCAIRE co ON co.id_compte = t.id_compte GROUP BY co.id_client)",
    )[0]
    assert row["mn"] >= 10
    assert row["mx"] <= 50


def test_balances_are_within_the_requested_range(demo_db):
    row = _query(
        demo_db,
        "SELECT MIN(CAST(solde_disponible AS REAL)) mn, MAX(CAST(solde_disponible AS REAL)) mx FROM COMPTE_BANCAIRE",
    )[0]
    assert row["mn"] >= 100.0
    assert row["mx"] <= 100000.0


def test_all_five_operation_families_are_represented(demo_db):
    types = {row["type_operation"] for row in _query(demo_db, 'SELECT DISTINCT type_operation FROM "TRANSACTION"')}
    assert {"salary", "incoming_transfer", "card_payment", "withdrawal", "direct_debit"}.issubset(types)


def test_the_three_card_brands_are_represented(demo_db):
    types = {row["type_carte"] for row in _query(demo_db, "SELECT DISTINCT type_carte FROM CARTE_BANCAIRE")}
    assert types == {"Visa Classic", "Visa Gold", "Mastercard"}


def test_amounts_are_stored_as_decimal_strings_never_float(demo_db):
    for table, column in (
        ("COMPTE_BANCAIRE", "solde_disponible"),
        ('"TRANSACTION"', "montant"),
        ("CARTE_BANCAIRE", "plafond_paiement"),
        ("account_balance_history", "solde"),
    ):
        row = _query(demo_db, f"SELECT typeof({column}) t FROM {table} LIMIT 1")[0]
        assert row["t"] == "text", f"{table}.{column}"


def test_every_account_has_a_valid_rib_and_iban(demo_db):
    rows = _query(demo_db, "SELECT rib, iban FROM COMPTE_BANCAIRE")
    for row in rows:
        assert len(row["rib"]) == 24 and row["rib"].isdigit()
        assert row["iban"].startswith("MA") and len(row["iban"]) == 28


# ---------------------------------------------------------------------------
# 4. Déterminisme
# ---------------------------------------------------------------------------


def test_generation_is_deterministic(tmp_path):
    """Deux exécutions doivent produire des données strictement identiques.

    Le hash bcrypt est volontairement EXCLU de la comparaison : son sel est
    aléatoire par construction, et le figer serait une faute de sécurité.
    C'est la seule valeur non déterministe de la base.
    """
    first = str(tmp_path / "a.db")
    second = str(tmp_path / "b.db")
    seed_demo_database(db_path=first, nb_clients=12)
    seed_demo_database(db_path=second, nb_clients=12)

    for table, columns in (
        ("CLIENT", "id_client, nom, prenom, telephone_mobile, email, statut_client"),
        ("UTILISATEUR_E_BANKING", "id_utilisateur, id_client, identifiant_connexion, statut_connexion"),
        ("COMPTE_BANCAIRE", "id_compte, id_client, rib, iban, type_compte, solde_disponible"),
        ('"TRANSACTION"', "id_transaction, date_operation, type_operation, sens, categorie, montant"),
        ("CARTE_BANCAIRE", "id_carte, numero_carte_masque, type_carte, date_expiration, plafond_paiement"),
        ("BENEFICIAIRE", "id_beneficiaire, nom_beneficiaire, rib, numero_compte_masque"),
        ("account_balance_history", "id_compte, as_of_date, solde"),
    ):
        sql = f"SELECT {columns} FROM {table} ORDER BY 1"
        assert [tuple(r) for r in _query(first, sql)] == [tuple(r) for r in _query(second, sql)], table


def test_reseeding_is_idempotent(tmp_path):
    path = str(tmp_path / "idem.db")
    seed_demo_database(db_path=path, nb_clients=10)
    before = _query(path, "SELECT COUNT(*) c FROM CLIENT")[0]["c"]
    seed_demo_database(db_path=path, nb_clients=10)
    after = _query(path, "SELECT COUNT(*) c FROM CLIENT")[0]["c"]
    assert before == after == 10


# ---------------------------------------------------------------------------
# 5. Sécurité — bcrypt, aucun mot de passe en clair
# ---------------------------------------------------------------------------


def test_every_password_is_a_bcrypt_hash(demo_db):
    rows = _query(demo_db, "SELECT mot_de_passe_hash FROM UTILISATEUR_E_BANKING")
    assert len(rows) == NB_CLIENTS
    for row in rows:
        assert row["mot_de_passe_hash"].startswith("$2b$")


def test_no_clear_password_anywhere_in_the_database(demo_db):
    """Balayage exhaustif de toutes les tables et de toutes les colonnes."""
    with sqlite3.connect(demo_db) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                contenu = " ".join(str(value) for value in row)
                assert DEMO_PASSWORD not in contenu, table
                assert FIXTURE_PASSWORD not in contenu, table


def test_only_two_distinct_hashes_are_computed(demo_db):
    """bcrypt coûte ~300 ms : un hash par client prendrait 30 s. Seuls deux
    hashs sont calculés — celui de CL0001 et celui, partagé, des 99 comptes
    fictifs."""
    assert _query(demo_db, "SELECT COUNT(DISTINCT mot_de_passe_hash) c FROM UTILISATEUR_E_BANKING")[0]["c"] == 2


# ---------------------------------------------------------------------------
# 6. Sécurité — numéros de carte masqués
# ---------------------------------------------------------------------------


def test_card_numbers_are_stored_masked_only(demo_db):
    """Format attendu : `450012XXXXXX3456`. Le PAN complet n'existe jamais,
    pas même en mémoire pendant la génération."""
    rows = _query(demo_db, "SELECT numero_carte_masque FROM CARTE_BANCAIRE")
    assert len(rows) == NB_CLIENTS
    for row in rows:
        numero = row["numero_carte_masque"]
        assert "XXXXXX" in numero
        assert len(numero) == 16
        digits = "".join(char for char in numero if char.isdigit())
        assert len(digits) == 10  # 6 (BIN) + 4 (derniers) — jamais 16


# ---------------------------------------------------------------------------
# 7. Bout en bout : l'Agent 1 sait lire cette base
# ---------------------------------------------------------------------------


def test_agent1_read_functions_work_against_the_demo_database(demo_db):
    """Les 7 fonctions publiques utilisées par l'Agent 1 doivent fonctionner
    sur la nouvelle base sans adaptation."""
    from app.banking import banking_db

    accounts = banking_db.get_accounts_for_customer(DEMO_CLIENT_ID, db_path=demo_db)
    assert len(accounts) >= 1

    total = banking_db.get_total_balance(DEMO_CLIENT_ID, db_path=demo_db)
    assert total > 0
    assert total == sum(account["balance"] for account in accounts)

    transactions = banking_db.get_transactions(DEMO_CLIENT_ID, limit=5, db_path=demo_db)
    assert len(transactions) == 5

    card = banking_db.get_card_for_customer(DEMO_CLIENT_ID, db_path=demo_db)
    assert card is not None and "XXXXXX" in card["masked_card_number"]

    beneficiaries = banking_db.get_beneficiaries_for_customer(DEMO_CLIENT_ID, db_path=demo_db)
    assert len(beneficiaries) >= 1

    assert banking_db.get_spending_total(DEMO_CLIENT_ID, db_path=demo_db) >= 0
    assert banking_db.get_balance_at_date(DEMO_CLIENT_ID, "2026-01-01", db_path=demo_db)


def test_client_can_only_read_his_own_data(demo_db):
    """Isolation : aucune fonction ne doit laisser fuiter les données d'un
    autre client."""
    from app.banking import banking_db

    accounts_demo = {a["account_id"] for a in banking_db.get_accounts_for_customer(DEMO_CLIENT_ID, db_path=demo_db)}
    accounts_other = {a["account_id"] for a in banking_db.get_accounts_for_customer("CL0042", db_path=demo_db)}
    assert accounts_demo and accounts_other
    assert not (accounts_demo & accounts_other)

    beneficiaries_demo = {b["beneficiary_id"] for b in banking_db.get_beneficiaries_for_customer(DEMO_CLIENT_ID, db_path=demo_db)}
    beneficiaries_other = {b["beneficiary_id"] for b in banking_db.get_beneficiaries_for_customer("CL0042", db_path=demo_db)}
    assert not (beneficiaries_demo & beneficiaries_other)

    assert banking_db.get_total_balance(DEMO_CLIENT_ID, db_path=demo_db) != banking_db.get_total_balance(
        "CL0042", db_path=demo_db
    )


def test_unknown_client_reads_nothing(demo_db):
    from app.banking import banking_db

    assert banking_db.get_accounts_for_customer("CL9999", db_path=demo_db) == []
    assert banking_db.get_transactions("CL9999", db_path=demo_db) == []
    assert banking_db.get_card_for_customer("CL9999", db_path=demo_db) is None
