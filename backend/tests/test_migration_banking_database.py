"""Tests du script de migration (scripts/migrate_banking_database.py).

Garantie centrale vérifiée ici : la base SOURCE n'est jamais modifiée. La
migration écrit toujours dans une base distincte, de sorte que l'ancienne
`banking.db` reste utilisable comme sauvegarde en cas de retour arrière.

Toutes les bases sont créées dans `tmp_path` — jamais celles du projet.
"""
import sqlite3

import pytest

from app.banking import banking_db
from scripts.migrate_banking_database import MigrationError, inspect_source, migrate


def _build_legacy_database(path: str) -> None:
    """Recrée une base à l'ANCIEN schéma (celui d'avant l'étape 1)."""
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE customers (customer_id TEXT PRIMARY KEY, full_name TEXT, status TEXT, created_at TEXT);
            CREATE TABLE accounts (account_id TEXT PRIMARY KEY, customer_id TEXT, account_type TEXT,
                currency TEXT, masked_account_number TEXT, balance TEXT, created_at TEXT);
            CREATE TABLE account_balance_history (account_id TEXT, as_of_date TEXT, balance TEXT,
                created_at TEXT, PRIMARY KEY (account_id, as_of_date));
            CREATE TABLE transactions (transaction_id TEXT PRIMARY KEY, account_id TEXT, transaction_date TEXT,
                transaction_type TEXT, direction TEXT, description TEXT, category TEXT, amount TEXT,
                currency TEXT, related_account_id TEXT, created_at TEXT);
            CREATE TABLE beneficiaries (beneficiary_id TEXT PRIMARY KEY, owner_customer_id TEXT,
                display_name TEXT, masked_account_number TEXT, status TEXT, eligible_for_transfer INTEGER,
                created_at TEXT);
            CREATE TABLE cards (card_id TEXT PRIMARY KEY, account_id TEXT, card_type TEXT,
                masked_card_number TEXT, status TEXT, payment_limit TEXT, withdrawal_limit TEXT,
                online_payments_enabled INTEGER, international_payments_enabled INTEGER, created_at TEXT);

            INSERT INTO customers VALUES ('usr_001', 'Client Démo 1', 'active', '2026-01-01T00:00:00+00:00');
            INSERT INTO accounts VALUES ('acc_001_courant', 'usr_001', 'courant', 'MAD',
                'CIH •••• 1001', '15230.50', '2026-01-01T00:00:00+00:00');
            INSERT INTO account_balance_history VALUES ('acc_001_courant', '2026-01-01', '9000.00',
                '2026-01-01T00:00:00+00:00');
            INSERT INTO transactions VALUES ('tx_001_salary', 'acc_001_courant', '2026-07-25', 'salary',
                'credit', 'Virement salaire (fictif)', 'Salaire', '12000.00', 'MAD', NULL,
                '2026-01-01T00:00:00+00:00');
            INSERT INTO beneficiaries VALUES ('ben_001_a', 'usr_001', 'Bénéficiaire Démo 1A',
                'CIH •••• 2001', 'active', 1, '2026-01-01T00:00:00+00:00');
            INSERT INTO cards VALUES ('card_001', 'acc_001_courant', 'Visa Débit', '•••• •••• •••• 1001',
                'active', '5000.00', '2000.00', 1, 1, '2026-01-01T00:00:00+00:00');
            """
        )
        conn.commit()


@pytest.fixture
def legacy_db(tmp_path):
    path = str(tmp_path / "banking_legacy.db")
    _build_legacy_database(path)
    return path


# ---------------------------------------------------------------------------
# 1. Inspection (dry-run)
# ---------------------------------------------------------------------------


def test_inspect_reports_legacy_row_counts(legacy_db):
    info = inspect_source(legacy_db)
    assert info["counts"]["customers"] == 1
    assert info["counts"]["transactions"] == 1


def test_inspect_rejects_a_missing_source(tmp_path):
    with pytest.raises(MigrationError) as excinfo:
        inspect_source(str(tmp_path / "absente.db"))
    assert "introuvable" in str(excinfo.value)


def test_inspect_rejects_a_database_already_migrated(tmp_path):
    """Une base au NOUVEAU schéma n'a plus rien à migrer : message explicite."""
    path = str(tmp_path / "deja_migree.db")
    banking_db.init_db(path)
    with pytest.raises(MigrationError) as excinfo:
        inspect_source(path)
    assert "déjà été migrée" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 2. La source n'est JAMAIS modifiée
# ---------------------------------------------------------------------------


def test_source_database_is_left_untouched(legacy_db, tmp_path):
    before = open(legacy_db, "rb").read()
    migrate(legacy_db, str(tmp_path / "cible.db"))
    assert open(legacy_db, "rb").read() == before


def test_migration_refuses_source_equal_to_target(legacy_db):
    with pytest.raises(MigrationError) as excinfo:
        migrate(legacy_db, legacy_db)
    assert "même fichier" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 3. Fidélité de la conversion
# ---------------------------------------------------------------------------


@pytest.fixture
def migrated_db(legacy_db, tmp_path):
    target = str(tmp_path / "demo_bancaire.db")
    migrate(legacy_db, target)
    return target


def test_all_rows_are_migrated(legacy_db, tmp_path):
    result = migrate(legacy_db, str(tmp_path / "cible.db"))
    assert result["migrated"] == {
        "CLIENT": 1, "COMPTE_BANCAIRE": 1, "account_balance_history": 1,
        "TRANSACTION": 1, "BENEFICIAIRE": 1, "CARTE_BANCAIRE": 1,
    }


def test_amounts_are_preserved_exactly(migrated_db):
    """Aucune conversion en float : les montants restent des chaînes décimales."""
    with sqlite3.connect(migrated_db) as conn:
        assert conn.execute(
            "SELECT solde_disponible FROM COMPTE_BANCAIRE WHERE id_compte = 'acc_001_courant'"
        ).fetchone()[0] == "15230.50"
        assert conn.execute(
            'SELECT montant FROM "TRANSACTION" WHERE id_transaction = \'tx_001_salary\''
        ).fetchone()[0] == "12000.00"
        assert conn.execute("SELECT typeof(solde_disponible) FROM COMPTE_BANCAIRE").fetchone()[0] == "text"


def test_generated_fields_absent_from_the_legacy_schema(migrated_db):
    """`rib`, `iban` et `numero_compte` n'existaient pas : ils sont dérivés."""
    with sqlite3.connect(migrated_db) as conn:
        rib, iban, numero = conn.execute(
            "SELECT rib, iban, numero_compte FROM COMPTE_BANCAIRE WHERE id_compte = 'acc_001_courant'"
        ).fetchone()
    assert len(rib) == 24 and rib.isdigit()
    assert iban.startswith("MA") and len(iban) == 28
    assert len(numero) == 16


def test_migration_is_deterministic(legacy_db, tmp_path):
    """Deux migrations de la même source produisent des RIB/IBAN identiques."""
    first = str(tmp_path / "m1.db")
    second = str(tmp_path / "m2.db")
    migrate(legacy_db, first)
    migrate(legacy_db, second)

    def _snapshot(path):
        with sqlite3.connect(path) as conn:
            return conn.execute("SELECT id_compte, rib, iban FROM COMPTE_BANCAIRE ORDER BY 1").fetchall()

    assert _snapshot(first) == _snapshot(second)


def test_migration_is_idempotent(legacy_db, tmp_path):
    target = str(tmp_path / "idem.db")
    migrate(legacy_db, target)
    migrate(legacy_db, target)
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT COUNT(*) FROM CLIENT").fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM "TRANSACTION"').fetchone()[0] == 1


def test_no_ebanking_account_is_invented(migrated_db):
    """Le script ne peut pas fabriquer de hash bcrypt : il ne crée aucun compte
    d'accès en ligne, et n'a jamais accès à un mot de passe."""
    with sqlite3.connect(migrated_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM UTILISATEUR_E_BANKING").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# 4. L'Agent 1 sait lire la base migrée
# ---------------------------------------------------------------------------


def test_agent1_read_functions_work_on_the_migrated_database(migrated_db):
    from decimal import Decimal

    assert banking_db.get_total_balance("usr_001", db_path=migrated_db) == Decimal("15230.50")

    transactions = banking_db.get_transactions("usr_001", db_path=migrated_db)
    assert len(transactions) == 1
    assert transactions[0]["transaction_type"] == "salary"

    card = banking_db.get_card_for_customer("usr_001", db_path=migrated_db)
    assert card is not None and card["status"] == "active"

    assert len(banking_db.get_beneficiaries_for_customer("usr_001", db_path=migrated_db)) == 1
    assert banking_db.get_balance_at_date("usr_001", "2026-01-01", db_path=migrated_db)
