"""Base SQLite bancaire fictive de démonstration — `backend/data/banking.db`.

Base **séparée** de `auth.db` (voir `backend/app/security/session_manager.py`) :
SQLite ne permet pas de contrainte `FOREIGN KEY` entre deux fichiers de base
différents, la liaison entre les deux bases se fait donc **par valeur**, via
le même `user_id`/`customer_id` opaque (`usr_001`…`usr_005`), jamais par une
contrainte physique cross-fichier.

Ce module expose également les fonctions de **lecture seule** utilisées par
l'Agent 1 authentifié (`agents/agent1_faq/banking_answers.py`) pour répondre
aux questions personnelles : chaque fonction exige un `customer_id` explicite
(jamais déduit d'un texte libre) et ne retourne que les lignes de ce client —
aucun chemin ne permet de lire les données d'un autre utilisateur. Aucune
écriture n'est jamais effectuée par ces fonctions ; aucun virement réel,
aucune modification bancaire (plafond, blocage de carte) n'est implémentée.

Toutes les données sont **100 % fictives** (prototype académique, voir
`CLAUDE.md` §9.5) : aucune n'est reprise d'une capture de référence. Les
dates sont ancrées sur une date de référence fixe (`DEMO_REFERENCE_DATE`),
pas sur l'horloge système, pour que "cette semaine"/"ce mois-ci"/"le mois
dernier" restent des réponses stables et reproductibles.

Montants : toujours `Decimal` en Python ; stockés en base sous forme de
**chaîne décimale** (colonne `TEXT`), jamais un type flottant SQLite — même
règle que pour le JSON réseau (`02_architecture_multi_agents.md`, §4.1).
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

# Racine du dépôt (banking/banking_db.py -> banking -> app -> backend -> racine),
# même convention que `security/session_manager.py` et `agents/agent1_faq/rag.py`.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return str(path)


DEFAULT_DB_PATH = _resolve_path(os.getenv("BANKING_DB_PATH", "./backend/data/banking.db"))

# Date de référence fictive ("aujourd'hui" pour ce jeu de données) : ancre les
# notions de "cette semaine" (>= 2026-07-21), "ce mois-ci" (2026-07) et "le
# mois dernier" (2026-06) utilisées par les futures questions personnelles.
DEMO_REFERENCE_DATE = "2026-07-28"
DEMO_CURRENT_MONTH = "2026-07"
DEMO_LAST_MONTH = "2026-06"
DEMO_THIS_WEEK_START = "2026-07-21"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    resolved = _resolve_path(db_path) if db_path else DEFAULT_DB_PATH
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def init_db(db_path: Optional[str] = None) -> None:
    """Crée (ou migre) les tables — idempotent.

    Migration : la version précédente de cette base (un seul compte par
    client, transactions non catégorisées) est incompatible avec le nouveau
    schéma enrichi (comptes multiples, historique de solde, catégories,
    cartes). Puisqu'il s'agit uniquement de données fictives entièrement
    reproductibles par `seed_banking_data` (jamais de donnée réelle), les
    anciennes tables `accounts`/`transactions` sont recréées si elles datent
    encore de l'ancien schéma (détecté via l'absence de la colonne
    `description`), plutôt que de tenter une migration `ALTER TABLE` complexe
    pour des données jetables.
    """
    with closing(_get_connection(db_path)) as conn:
        if _table_exists(conn, "transactions") and not _has_column(conn, "transactions", "description"):
            conn.execute("DROP TABLE IF EXISTS transactions")
            conn.execute("DROP TABLE IF EXISTS accounts")
            conn.execute("DROP TABLE IF EXISTS account_balance_history")
            conn.commit()

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                account_type TEXT NOT NULL CHECK (account_type IN ('courant', 'carnet')),
                currency TEXT NOT NULL,
                masked_account_number TEXT NOT NULL,
                balance TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_balance_history (
                account_id TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                balance TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (account_id, as_of_date),
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                transaction_date TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                direction TEXT NOT NULL CHECK (direction IN ('credit', 'debit')),
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL,
                related_account_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS beneficiaries (
                beneficiary_id TEXT PRIMARY KEY,
                owner_customer_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                masked_account_number TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                eligible_for_transfer INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (owner_customer_id) REFERENCES customers(customer_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cards (
                card_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                card_type TEXT NOT NULL,
                masked_card_number TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                payment_limit TEXT NOT NULL,
                withdrawal_limit TEXT NOT NULL,
                online_payments_enabled INTEGER NOT NULL DEFAULT 1,
                international_payments_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
            """
        )
        conn.commit()


def _upsert(conn: sqlite3.Connection, table: str, pk_cols: list[str], columns: dict) -> str:
    """Insère ou met à jour une ligne par clé (primaire, simple ou composite).

    `table`/`pk_cols`/les clés de `columns` sont toujours des constantes
    internes de ce module (jamais une valeur fournie par un appelant externe) :
    aucun risque d'injection SQL malgré l'interpolation de noms.
    """
    where_clause = " AND ".join(f"{col} = ?" for col in pk_cols)
    pk_values = [columns[col] for col in pk_cols]
    existing = conn.execute(f"SELECT 1 FROM {table} WHERE {where_clause}", pk_values).fetchone()

    cols = list(columns.keys())
    values = list(columns.values())
    if existing is None:
        placeholders = ", ".join(["?"] * len(cols))
        conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})", values)
        return "inserted"
    set_clause = ", ".join(f"{col} = ?" for col in cols)
    conn.execute(f"UPDATE {table} SET {set_clause} WHERE {where_clause}", values + pk_values)
    return "updated"


def _account(account_id: str, account_type: str, masked_account_number: str, balance: Decimal, history: list) -> dict:
    return {
        "account_id": account_id,
        "account_type": account_type,
        "masked_account_number": masked_account_number,
        "balance": balance,
        # historique : liste de (as_of_date, balance) - permet de retrouver le
        # solde exact a une date passee (ex. "le 1er janvier de cette annee").
        "history": history,
    }


def _tx(transaction_id, transaction_type, direction, category, description, amount, date, related_account_id=None):
    return {
        "transaction_id": transaction_id,
        "transaction_type": transaction_type,
        "direction": direction,
        "category": category,
        "description": description,
        "amount": amount,
        "transaction_date": date,
        "related_account_id": related_account_id,
    }


def _demo_customers() -> list[dict]:
    """Jeu de données 100 % fictif, cohérent, distinct par utilisateur de
    démonstration (`usr_001`…`usr_005`, mêmes `user_id` que dans `auth.db`).

    Chaque client possède deux comptes (courant + carnet/épargne), un
    historique de solde trimestriel, des transactions catégorisées couvrant
    salaire, virement interne reçu, prélèvements, paiements carte (dont
    "Restaurants") et retrait, ainsi qu'une carte bancaire avec ses plafonds
    et ses autorisations (achats en ligne / internationaux).
    """
    profiles = [
        # (index, user_id, full_name, courant_now, courant_hist, carnet_now, carnet_hist,
        #  salary, transfer_in, debit1, debit2, rest1, rest2, rest3, courses, carburant,
        #  courses_june, rest_june, loyer_june, transport_june, withdrawal,
        #  card_type, payment_limit, withdrawal_limit, online_enabled, intl_enabled, card_status)
        (
            1, "usr_001", "Client Démo 1",
            Decimal("15230.50"), [("2026-01-01", Decimal("9000.00")), ("2026-04-01", Decimal("11500.00")), ("2026-07-01", Decimal("14000.00"))],
            Decimal("30500.00"), [("2026-01-01", Decimal("28000.00")), ("2026-04-01", Decimal("29000.00")), ("2026-07-01", Decimal("30000.00"))],
            Decimal("12000.00"), Decimal("2000.00"), Decimal("450.75"), Decimal("129.00"),
            Decimal("89.90"), Decimal("120.00"), Decimal("76.50"), Decimal("300.00"), Decimal("250.00"),
            Decimal("280.00"), Decimal("95.00"), Decimal("3000.00"), Decimal("45.00"), Decimal("500.00"),
            "Visa Débit", Decimal("5000.00"), Decimal("2000.00"), 1, 1, "active",
        ),
        (
            2, "usr_002", "Client Démo 2",
            Decimal("2894.10"), [("2026-01-01", Decimal("2000.00")), ("2026-04-01", Decimal("2400.00")), ("2026-07-01", Decimal("2700.00"))],
            Decimal("8200.00"), [("2026-01-01", Decimal("7000.00")), ("2026-04-01", Decimal("7600.00")), ("2026-07-01", Decimal("8000.00"))],
            Decimal("8000.00"), Decimal("1000.00"), Decimal("210.00"), Decimal("59.00"),
            Decimal("45.00"), Decimal("60.00"), Decimal("38.00"), Decimal("150.00"), Decimal("100.00"),
            Decimal("140.00"), Decimal("42.00"), Decimal("1200.00"), Decimal("30.00"), Decimal("200.00"),
            "Mastercard Débit", Decimal("3000.00"), Decimal("1500.00"), 1, 0, "active",
        ),
        (
            3, "usr_003", "Client Démo 3",
            Decimal("48210.00"), [("2026-01-01", Decimal("40000.00")), ("2026-04-01", Decimal("44000.00")), ("2026-07-01", Decimal("47000.00"))],
            Decimal("95000.00"), [("2026-01-01", Decimal("90000.00")), ("2026-04-01", Decimal("92500.00")), ("2026-07-01", Decimal("94000.00"))],
            Decimal("20000.00"), Decimal("5000.00"), Decimal("800.00"), Decimal("199.00"),
            Decimal("150.00"), Decimal("210.00"), Decimal("175.00"), Decimal("600.00"), Decimal("400.00"),
            Decimal("550.00"), Decimal("190.00"), Decimal("6000.00"), Decimal("90.00"), Decimal("1000.00"),
            "Visa Débit", Decimal("10000.00"), Decimal("4000.00"), 0, 1, "active",
        ),
        (
            4, "usr_004", "Client Démo 4",
            Decimal("670.25"), [("2026-01-01", Decimal("500.00")), ("2026-04-01", Decimal("580.00")), ("2026-07-01", Decimal("630.00"))],
            Decimal("1200.00"), [("2026-01-01", Decimal("1000.00")), ("2026-04-01", Decimal("1100.00")), ("2026-07-01", Decimal("1150.00"))],
            Decimal("4500.00"), Decimal("300.00"), Decimal("95.00"), Decimal("39.00"),
            Decimal("25.00"), Decimal("32.00"), Decimal("21.50"), Decimal("90.00"), Decimal("70.00"),
            Decimal("85.00"), Decimal("28.00"), Decimal("900.00"), Decimal("15.00"), Decimal("100.00"),
            # Carte bloquee pour ce client - permet de tester le cas "carte inactive".
            "Mastercard Débit", Decimal("1500.00"), Decimal("800.00"), 1, 1, "blocked",
        ),
        (
            5, "usr_005", "Client Démo 5",
            Decimal("125000.00"), [("2026-01-01", Decimal("100000.00")), ("2026-04-01", Decimal("112000.00")), ("2026-07-01", Decimal("120000.00"))],
            Decimal("250000.00"), [("2026-01-01", Decimal("230000.00")), ("2026-04-01", Decimal("240000.00")), ("2026-07-01", Decimal("248000.00"))],
            Decimal("60000.00"), Decimal("10000.00"), Decimal("1500.00"), Decimal("299.00"),
            Decimal("400.00"), Decimal("550.00"), Decimal("320.00"), Decimal("1200.00"), Decimal("900.00"),
            Decimal("1100.00"), Decimal("380.00"), Decimal("15000.00"), Decimal("200.00"), Decimal("2000.00"),
            "Visa Débit", Decimal("20000.00"), Decimal("8000.00"), 1, 0, "active",
        ),
    ]

    customers = []
    for (
        index, user_id, full_name,
        courant_now, courant_hist, carnet_now, carnet_hist,
        salary, transfer_in, debit1, debit2,
        rest1, rest2, rest3, courses, carburant,
        courses_june, rest_june, loyer_june, transport_june, withdrawal,
        card_type, payment_limit, withdrawal_limit, online_enabled, intl_enabled, card_status,
    ) in profiles:
        i = f"{index:03d}"
        courant_id = f"acc_{i}_courant"
        carnet_id = f"acc_{i}_carnet"

        customers.append(
            {
                "customer_id": user_id,
                "full_name": full_name,
                "accounts": [
                    _account(courant_id, "courant", f"CIH •••• 1{i}", courant_now, courant_hist),
                    _account(carnet_id, "carnet", f"CIH Carnet •••• 3{i}", carnet_now, carnet_hist),
                ],
                "transactions": {
                    courant_id: [
                        _tx(f"tx_{i}_salary", "salary", "credit", "Salaire", "Virement salaire (fictif)", salary, "2026-07-25"),
                        _tx(f"tx_{i}_transfer_in", "incoming_transfer", "credit", "Virement reçu",
                            "Virement depuis compte sur carnet (fictif)", transfer_in, "2026-07-26", related_account_id=carnet_id),
                        _tx(f"tx_{i}_debit1", "direct_debit", "debit", "Assurance", "Prélèvement assurance (fictif)", debit1, "2026-07-05"),
                        _tx(f"tx_{i}_debit2", "direct_debit", "debit", "Abonnement", "Prélèvement abonnement internet (fictif)", debit2, "2026-07-20"),
                        _tx(f"tx_{i}_rest1", "card_payment", "debit", "Restaurants", "Paiement carte restaurant (fictif)", rest1, "2026-07-08"),
                        _tx(f"tx_{i}_rest2", "card_payment", "debit", "Restaurants", "Paiement carte restaurant (fictif)", rest2, "2026-07-15"),
                        _tx(f"tx_{i}_rest3", "card_payment", "debit", "Restaurants", "Paiement carte restaurant (fictif)", rest3, "2026-07-23"),
                        _tx(f"tx_{i}_courses", "card_payment", "debit", "Courses", "Paiement carte supermarché (fictif)", courses, "2026-07-10"),
                        _tx(f"tx_{i}_carburant", "card_payment", "debit", "Carburant", "Paiement carte station-service (fictif)", carburant, "2026-07-18"),
                        _tx(f"tx_{i}_withdrawal", "withdrawal", "debit", "Retrait", "Retrait distributeur (fictif)", withdrawal, "2026-07-12"),
                        _tx(f"tx_{i}_courses_june", "card_payment", "debit", "Courses", "Paiement carte supermarché (fictif)", courses_june, "2026-06-12"),
                        _tx(f"tx_{i}_rest_june", "card_payment", "debit", "Restaurants", "Paiement carte restaurant (fictif)", rest_june, "2026-06-20"),
                        _tx(f"tx_{i}_loyer_june", "direct_debit", "debit", "Logement", "Prélèvement loyer (fictif)", loyer_june, "2026-06-01"),
                        # Uniquement le mois dernier - aucune depense "Transport" ce mois-ci
                        # (permet de tester a la fois un resultat non nul et un resultat a zero).
                        _tx(f"tx_{i}_transport_june", "card_payment", "debit", "Transport", "Paiement carte transport (bus/taxi) (fictif)", transport_june, "2026-06-15"),
                    ],
                    carnet_id: [
                        _tx(f"tx_{i}_transfer_out", "transfer_out", "debit", "Virement interne",
                            "Virement vers compte courant (fictif)", transfer_in, "2026-07-26", related_account_id=courant_id),
                    ],
                },
                "beneficiaries": [
                    (f"ben_{i}_a", f"Bénéficiaire Démo {index}A", f"CIH •••• 2{i}"),
                    (f"ben_{i}_b", f"Bénéficiaire Démo {index}B", f"BMCE •••• 2{i}1"),
                ],
                "card": {
                    "card_id": f"card_{i}",
                    "account_id": courant_id,
                    "card_type": card_type,
                    "masked_card_number": f"•••• •••• •••• 1{i}",
                    "status": card_status,
                    "payment_limit": payment_limit,
                    "withdrawal_limit": withdrawal_limit,
                    "online_payments_enabled": online_enabled,
                    "international_payments_enabled": intl_enabled,
                },
            }
        )

    return customers


def seed_banking_data(db_path: Optional[str] = None) -> dict:
    """Insère les données bancaires fictives de démonstration (idempotent).

    Chaque ligne (client, compte, historique de solde, transaction,
    bénéficiaire, carte) est identifiée par une clé stable ; une ré-exécution
    ne crée jamais de seconde ligne, elle met à jour la ligne existante
    (`_upsert`). Les montants sont toujours des `Decimal` Python, stockés
    comme chaînes décimales — jamais `float`.
    """
    init_db(db_path)
    now = _utcnow_iso()
    stats = {
        "customers": {"inserted": 0, "updated": 0},
        "accounts": {"inserted": 0, "updated": 0},
        "account_balance_history": {"inserted": 0, "updated": 0},
        "transactions": {"inserted": 0, "updated": 0},
        "beneficiaries": {"inserted": 0, "updated": 0},
        "cards": {"inserted": 0, "updated": 0},
    }

    with closing(_get_connection(db_path)) as conn:
        for customer in _demo_customers():
            outcome = _upsert(
                conn,
                "customers",
                ["customer_id"],
                {
                    "customer_id": customer["customer_id"],
                    "full_name": customer["full_name"],
                    "status": "active",
                    "created_at": now,
                },
            )
            stats["customers"][outcome] += 1

            for account in customer["accounts"]:
                outcome = _upsert(
                    conn,
                    "accounts",
                    ["account_id"],
                    {
                        "account_id": account["account_id"],
                        "customer_id": customer["customer_id"],
                        "account_type": account["account_type"],
                        "currency": "MAD",
                        "masked_account_number": account["masked_account_number"],
                        "balance": str(account["balance"]),
                        "created_at": now,
                    },
                )
                stats["accounts"][outcome] += 1

                for as_of_date, balance in account["history"]:
                    outcome = _upsert(
                        conn,
                        "account_balance_history",
                        ["account_id", "as_of_date"],
                        {
                            "account_id": account["account_id"],
                            "as_of_date": as_of_date,
                            "balance": str(balance),
                            "created_at": now,
                        },
                    )
                    stats["account_balance_history"][outcome] += 1

            for account_id, transactions in customer["transactions"].items():
                for tx in transactions:
                    outcome = _upsert(
                        conn,
                        "transactions",
                        ["transaction_id"],
                        {
                            "transaction_id": tx["transaction_id"],
                            "account_id": account_id,
                            "transaction_date": tx["transaction_date"],
                            "transaction_type": tx["transaction_type"],
                            "direction": tx["direction"],
                            "description": tx["description"],
                            "category": tx["category"],
                            "amount": str(tx["amount"]),
                            "currency": "MAD",
                            "related_account_id": tx["related_account_id"],
                            "created_at": now,
                        },
                    )
                    stats["transactions"][outcome] += 1

            for beneficiary_id, display_name, masked_account_number in customer["beneficiaries"]:
                outcome = _upsert(
                    conn,
                    "beneficiaries",
                    ["beneficiary_id"],
                    {
                        "beneficiary_id": beneficiary_id,
                        "owner_customer_id": customer["customer_id"],
                        "display_name": display_name,
                        "masked_account_number": masked_account_number,
                        "status": "active",
                        "eligible_for_transfer": 1,
                        "created_at": now,
                    },
                )
                stats["beneficiaries"][outcome] += 1

            card = customer["card"]
            outcome = _upsert(
                conn,
                "cards",
                ["card_id"],
                {
                    "card_id": card["card_id"],
                    "account_id": card["account_id"],
                    "card_type": card["card_type"],
                    "masked_card_number": card["masked_card_number"],
                    "status": card["status"],
                    "payment_limit": str(card["payment_limit"]),
                    "withdrawal_limit": str(card["withdrawal_limit"]),
                    "online_payments_enabled": card["online_payments_enabled"],
                    "international_payments_enabled": card["international_payments_enabled"],
                    "created_at": now,
                },
            )
            stats["cards"][outcome] += 1

        conn.commit()

        counts = {
            "customers_in_db": conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
            "accounts_in_db": conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
            "balance_history_in_db": conn.execute("SELECT COUNT(*) FROM account_balance_history").fetchone()[0],
            "transactions_in_db": conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            "beneficiaries_in_db": conn.execute("SELECT COUNT(*) FROM beneficiaries").fetchone()[0],
            "cards_in_db": conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
        }

    return {"db_path": _resolve_path(db_path) if db_path else DEFAULT_DB_PATH, "changes": stats, **counts}


# ---------------------------------------------------------------------------
# Lecture seule — utilisée par l'Agent 1 authentifié (jamais par l'Agent 1
# public, jamais indexée dans ChromaDB). Chaque fonction exige un
# `customer_id` explicite et ne retourne jamais les données d'un autre client.
# ---------------------------------------------------------------------------


def get_accounts_for_customer(customer_id: str, db_path: Optional[str] = None) -> list[dict]:
    with closing(_get_connection(db_path)) as conn:
        rows = conn.execute(
            "SELECT account_id, account_type, masked_account_number, balance, currency "
            "FROM accounts WHERE customer_id = ?",
            (customer_id,),
        ).fetchall()
    return [
        {
            "account_id": row["account_id"],
            "account_type": row["account_type"],
            "masked_account_number": row["masked_account_number"],
            "balance": Decimal(row["balance"]),
            "currency": row["currency"],
        }
        for row in rows
    ]


def get_total_balance(customer_id: str, db_path: Optional[str] = None) -> Decimal:
    with closing(_get_connection(db_path)) as conn:
        rows = conn.execute("SELECT balance FROM accounts WHERE customer_id = ?", (customer_id,)).fetchall()
    return sum((Decimal(row["balance"]) for row in rows), Decimal("0"))


def get_balance_at_date(customer_id: str, as_of_date: str, db_path: Optional[str] = None) -> list[dict]:
    """Solde de chaque compte à une date passée (ex. `as_of_date="2026-01-01"`)."""
    with closing(_get_connection(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT accounts.account_type, account_balance_history.balance
            FROM account_balance_history
            JOIN accounts ON accounts.account_id = account_balance_history.account_id
            WHERE accounts.customer_id = ? AND account_balance_history.as_of_date = ?
            """,
            (customer_id, as_of_date),
        ).fetchall()
    return [{"account_type": row["account_type"], "balance": Decimal(row["balance"])} for row in rows]


def get_transactions(
    customer_id: str,
    *,
    account_type: Optional[str] = None,
    category: Optional[str] = None,
    transaction_type: Optional[str] = None,
    direction: Optional[str] = None,
    year_month: Optional[str] = None,
    date_from: Optional[str] = None,
    limit: Optional[int] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    """Transactions du client, filtrables et triées de la plus récente à la plus ancienne.

    `direction="debit"` exclut explicitement salaires, virements reçus et tout
    autre crédit — utilisé par les calculs de dépenses par catégorie (défense
    en profondeur, en plus de la séparation déjà assurée par les catégories).
    """
    query = [
        "SELECT transactions.transaction_id, transactions.transaction_date, transactions.transaction_type,",
        "       transactions.direction, transactions.description, transactions.category,",
        "       transactions.amount, transactions.currency, transactions.related_account_id,",
        "       accounts.account_type",
        "FROM transactions",
        "JOIN accounts ON accounts.account_id = transactions.account_id",
        "WHERE accounts.customer_id = ?",
    ]
    params: list = [customer_id]

    if account_type:
        query.append("AND accounts.account_type = ?")
        params.append(account_type)
    if category:
        query.append("AND transactions.category = ?")
        params.append(category)
    if transaction_type:
        query.append("AND transactions.transaction_type = ?")
        params.append(transaction_type)
    if direction:
        query.append("AND transactions.direction = ?")
        params.append(direction)
    if year_month:
        query.append("AND substr(transactions.transaction_date, 1, 7) = ?")
        params.append(year_month)
    if date_from:
        query.append("AND transactions.transaction_date >= ?")
        params.append(date_from)

    query.append("ORDER BY transactions.transaction_date DESC, transactions.transaction_id DESC")
    if limit:
        query.append("LIMIT ?")
        params.append(limit)

    with closing(_get_connection(db_path)) as conn:
        rows = conn.execute(" ".join(query), params).fetchall()

    return [
        {
            "transaction_id": row["transaction_id"],
            "transaction_date": row["transaction_date"],
            "transaction_type": row["transaction_type"],
            "direction": row["direction"],
            "description": row["description"],
            "category": row["category"],
            "amount": Decimal(row["amount"]),
            "currency": row["currency"],
            "related_account_id": row["related_account_id"],
            "account_type": row["account_type"],
        }
        for row in rows
    ]


def get_card_for_customer(customer_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    with closing(_get_connection(db_path)) as conn:
        row = conn.execute(
            """
            SELECT cards.card_id, cards.card_type, cards.masked_card_number, cards.status,
                   cards.payment_limit, cards.withdrawal_limit,
                   cards.online_payments_enabled, cards.international_payments_enabled
            FROM cards
            JOIN accounts ON accounts.account_id = cards.account_id
            WHERE accounts.customer_id = ?
            LIMIT 1
            """,
            (customer_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "card_id": row["card_id"],
        "card_type": row["card_type"],
        "masked_card_number": row["masked_card_number"],
        "status": row["status"],
        "payment_limit": Decimal(row["payment_limit"]),
        "withdrawal_limit": Decimal(row["withdrawal_limit"]),
        "online_payments_enabled": bool(row["online_payments_enabled"]),
        "international_payments_enabled": bool(row["international_payments_enabled"]),
    }


def get_beneficiaries_for_customer(customer_id: str, db_path: Optional[str] = None) -> list[dict]:
    with closing(_get_connection(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT beneficiary_id, display_name, masked_account_number, status, eligible_for_transfer
            FROM beneficiaries
            WHERE owner_customer_id = ?
            ORDER BY beneficiary_id
            """,
            (customer_id,),
        ).fetchall()
    return [
        {
            "beneficiary_id": row["beneficiary_id"],
            "display_name": row["display_name"],
            "masked_account_number": row["masked_account_number"],
            "status": row["status"],
            "eligible_for_transfer": bool(row["eligible_for_transfer"]),
        }
        for row in rows
    ]


def get_spending_total(
    customer_id: str,
    category: Optional[str] = None,
    year_month: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Decimal:
    """Somme des dépenses (jamais salaires/virements reçus/crédits) du client.

    `category=None` calcule le total **toutes catégories confondues** — exclut
    explicitement `transfer_out` (un virement entre les comptes du client
    lui-même n'est pas une "dépense") en plus du filtre `direction="debit"`
    déjà appliqué par `get_transactions`.
    """
    transactions = get_transactions(
        customer_id, category=category, year_month=year_month, direction="debit", db_path=db_path
    )
    return sum(
        (tx["amount"] for tx in transactions if tx["transaction_type"] != "transfer_out"),
        Decimal("0"),
    )
