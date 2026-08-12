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


# Base bancaire métier. Valeur par défaut portée de `banking.db` (ancien
# schéma, MVP) à `demo_bancaire.db` (schéma réaliste, 100 clients).
# `banking.db` n'est ni supprimée ni lue : elle reste disponible comme
# sauvegarde, et `scripts/migrate_banking_database.py` sait la convertir.
DEFAULT_DB_PATH = _resolve_path(os.getenv("BANKING_DB_PATH", "./backend/data/demo_bancaire.db"))

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
    """Crée les tables du schéma bancaire métier — idempotent.

    Schéma cible (voir décision de migration) : `CLIENT`,
    `UTILISATEUR_E_BANKING`, `COMPTE_BANCAIRE`, `CARTE_BANCAIRE`,
    `TRANSACTION`, `BENEFICIAIRE`, plus `account_balance_history` conservée.

    Les tables de l'ancien schéma (`customers`, `accounts`, `transactions`,
    `cards`, `beneficiaries`) ne sont **jamais** supprimées ici : la
    conversion des données existantes est le rôle explicite de
    `scripts/migrate_banking_database.py`, jamais un effet de bord silencieux
    de l'ouverture d'une connexion.

    Note : `TRANSACTION` est un mot réservé SQL — la table est donc toujours
    référencée entre guillemets doubles dans les requêtes de ce module.
    """
    with closing(_get_connection(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS CLIENT (
                id_client TEXT PRIMARY KEY,
                nom TEXT NOT NULL,
                prenom TEXT NOT NULL,
                telephone_mobile TEXT,
                email TEXT,
                statut_client TEXT NOT NULL DEFAULT 'actif',
                date_creation TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS UTILISATEUR_E_BANKING (
                id_utilisateur TEXT PRIMARY KEY,
                id_client TEXT NOT NULL,
                identifiant_connexion TEXT NOT NULL UNIQUE,
                mot_de_passe_hash TEXT NOT NULL,
                statut_connexion TEXT NOT NULL DEFAULT 'actif',
                derniere_connexion TEXT,
                date_creation TEXT NOT NULL,
                FOREIGN KEY (id_client) REFERENCES CLIENT(id_client)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS COMPTE_BANCAIRE (
                id_compte TEXT PRIMARY KEY,
                id_client TEXT NOT NULL,
                numero_compte TEXT NOT NULL,
                numero_compte_masque TEXT NOT NULL,
                rib TEXT NOT NULL,
                iban TEXT NOT NULL,
                type_compte TEXT NOT NULL CHECK (type_compte IN ('courant', 'carnet')),
                devise TEXT NOT NULL,
                solde_disponible TEXT NOT NULL,
                date_creation TEXT NOT NULL,
                FOREIGN KEY (id_client) REFERENCES CLIENT(id_client)
            )
            """
        )
        # Conservée telle quelle (hors spécification cible) : alimente
        # `get_balance_at_date()`, utilisée par la réponse "solde au <date>" et
        # couverte par les tests. La supprimer casserait cette fonctionnalité.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_balance_history (
                id_compte TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                solde TEXT NOT NULL,
                date_creation TEXT NOT NULL,
                PRIMARY KEY (id_compte, as_of_date),
                FOREIGN KEY (id_compte) REFERENCES COMPTE_BANCAIRE(id_compte)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS "TRANSACTION" (
                id_transaction TEXT PRIMARY KEY,
                id_compte TEXT NOT NULL,
                date_operation TEXT NOT NULL,
                type_operation TEXT NOT NULL,
                sens TEXT NOT NULL CHECK (sens IN ('credit', 'debit')),
                libelle TEXT NOT NULL,
                categorie TEXT NOT NULL,
                montant TEXT NOT NULL,
                devise TEXT NOT NULL,
                id_compte_lie TEXT,
                date_creation TEXT NOT NULL,
                FOREIGN KEY (id_compte) REFERENCES COMPTE_BANCAIRE(id_compte)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS BENEFICIAIRE (
                id_beneficiaire TEXT PRIMARY KEY,
                id_client TEXT NOT NULL,
                nom_beneficiaire TEXT NOT NULL,
                rib TEXT NOT NULL,
                numero_compte_masque TEXT NOT NULL,
                statut TEXT NOT NULL DEFAULT 'actif',
                eligible_virement INTEGER NOT NULL DEFAULT 1,
                date_creation TEXT NOT NULL,
                FOREIGN KEY (id_client) REFERENCES CLIENT(id_client)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS CARTE_BANCAIRE (
                id_carte TEXT PRIMARY KEY,
                id_compte TEXT NOT NULL,
                numero_carte_masque TEXT NOT NULL,
                type_carte TEXT NOT NULL,
                date_expiration TEXT NOT NULL,
                statut_carte TEXT NOT NULL DEFAULT 'active',
                plafond_paiement TEXT NOT NULL,
                plafond_retrait TEXT NOT NULL,
                paiement_en_ligne_actif INTEGER NOT NULL DEFAULT 1,
                paiement_international_actif INTEGER NOT NULL DEFAULT 1,
                date_creation TEXT NOT NULL,
                FOREIGN KEY (id_compte) REFERENCES COMPTE_BANCAIRE(id_compte)
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


def _rib_from_account_id(account_id: str) -> str:
    """RIB marocain fictif à 24 chiffres, dérivé de façon DÉTERMINISTE de
    l'identifiant de compte (banque 230, ville 810, compte 16 chiffres, clé 2).

    Déterministe pour que la donnée de démonstration reste stable d'une
    ré-exécution à l'autre — jamais un vrai RIB, jamais aléatoire.
    """
    digits = "".join(char for char in account_id if char.isdigit()) or "0"
    body = (digits * 16)[:16]
    key = f"{sum(int(char) for char in body) % 97:02d}"
    return f"230810{body}{key}"


def _iban_from_rib(rib: str) -> str:
    """IBAN marocain fictif (`MA` + clé + RIB), dérivé du RIB ci-dessus."""
    key = f"{sum(int(char) for char in rib) % 97:02d}"
    return f"MA{key}{rib}"


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
            # "Client Démo 1" -> prenom="Client", nom="Démo 1". Le jeu de test
            # historique ne porte qu'un `full_name` ; le découpage est
            # déterministe et sans incidence (aucune fonction de lecture
            # n'expose le nom du client).
            first_name, _, last_name = customer["full_name"].partition(" ")
            customer_index = customer["customer_id"].split("_")[-1]
            outcome = _upsert(
                conn,
                "CLIENT",
                ["id_client"],
                {
                    "id_client": customer["customer_id"],
                    "nom": last_name or first_name,
                    "prenom": first_name,
                    "telephone_mobile": f"06000000{customer_index[-2:]}",
                    "email": f"client{customer_index}@example.invalid",
                    "statut_client": "actif",
                    "date_creation": now,
                },
            )
            stats["customers"][outcome] += 1

            for account in customer["accounts"]:
                rib = _rib_from_account_id(account["account_id"] + account["account_type"])
                outcome = _upsert(
                    conn,
                    "COMPTE_BANCAIRE",
                    ["id_compte"],
                    {
                        "id_compte": account["account_id"],
                        "id_client": customer["customer_id"],
                        "numero_compte": rib[6:22],
                        "numero_compte_masque": account["masked_account_number"],
                        "rib": rib,
                        "iban": _iban_from_rib(rib),
                        "type_compte": account["account_type"],
                        "devise": "MAD",
                        "solde_disponible": str(account["balance"]),
                        "date_creation": now,
                    },
                )
                stats["accounts"][outcome] += 1

                for as_of_date, balance in account["history"]:
                    outcome = _upsert(
                        conn,
                        "account_balance_history",
                        ["id_compte", "as_of_date"],
                        {
                            "id_compte": account["account_id"],
                            "as_of_date": as_of_date,
                            "solde": str(balance),
                            "date_creation": now,
                        },
                    )
                    stats["account_balance_history"][outcome] += 1

            for account_id, transactions in customer["transactions"].items():
                for tx in transactions:
                    outcome = _upsert(
                        conn,
                        '"TRANSACTION"',
                        ["id_transaction"],
                        {
                            "id_transaction": tx["transaction_id"],
                            "id_compte": account_id,
                            "date_operation": tx["transaction_date"],
                            "type_operation": tx["transaction_type"],
                            "sens": tx["direction"],
                            "libelle": tx["description"],
                            "categorie": tx["category"],
                            "montant": str(tx["amount"]),
                            "devise": "MAD",
                            "id_compte_lie": tx["related_account_id"],
                            "date_creation": now,
                        },
                    )
                    stats["transactions"][outcome] += 1

            for beneficiary_id, display_name, masked_account_number in customer["beneficiaries"]:
                outcome = _upsert(
                    conn,
                    "BENEFICIAIRE",
                    ["id_beneficiaire"],
                    {
                        "id_beneficiaire": beneficiary_id,
                        "id_client": customer["customer_id"],
                        "nom_beneficiaire": display_name,
                        "rib": _rib_from_account_id(beneficiary_id),
                        "numero_compte_masque": masked_account_number,
                        "statut": "actif",
                        "eligible_virement": 1,
                        "date_creation": now,
                    },
                )
                stats["beneficiaries"][outcome] += 1

            card = customer["card"]
            outcome = _upsert(
                conn,
                "CARTE_BANCAIRE",
                ["id_carte"],
                {
                    "id_carte": card["card_id"],
                    "id_compte": card["account_id"],
                    "numero_carte_masque": card["masked_card_number"],
                    "type_carte": card["card_type"],
                    "date_expiration": "2029-12-31",
                    "statut_carte": card["status"],
                    "plafond_paiement": str(card["payment_limit"]),
                    "plafond_retrait": str(card["withdrawal_limit"]),
                    "paiement_en_ligne_actif": card["online_payments_enabled"],
                    "paiement_international_actif": card["international_payments_enabled"],
                    "date_creation": now,
                },
            )
            stats["cards"][outcome] += 1

        conn.commit()

        # Clés de statistiques inchangées (contrat public de cette fonction,
        # asserté par les tests) malgré le renommage physique des tables.
        counts = {
            "customers_in_db": conn.execute("SELECT COUNT(*) FROM CLIENT").fetchone()[0],
            "accounts_in_db": conn.execute("SELECT COUNT(*) FROM COMPTE_BANCAIRE").fetchone()[0],
            "balance_history_in_db": conn.execute("SELECT COUNT(*) FROM account_balance_history").fetchone()[0],
            "transactions_in_db": conn.execute('SELECT COUNT(*) FROM "TRANSACTION"').fetchone()[0],
            "beneficiaries_in_db": conn.execute("SELECT COUNT(*) FROM BENEFICIAIRE").fetchone()[0],
            "cards_in_db": conn.execute("SELECT COUNT(*) FROM CARTE_BANCAIRE").fetchone()[0],
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
            "SELECT id_compte AS account_id, type_compte AS account_type, "
            "       numero_compte_masque AS masked_account_number, "
            "       solde_disponible AS balance, devise AS currency "
            "FROM COMPTE_BANCAIRE WHERE id_client = ?",
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


def get_customer_profile(customer_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    """Profil client SÛR : nom, prénom, statut. Jamais de secret.

    `email` et `telephone_mobile` sont volontairement exclus : le dashboard
    n'en a pas besoin, et toute donnée non nécessaire est une donnée à ne pas
    exposer.
    """
    with closing(_get_connection(db_path)) as conn:
        if not _table_exists(conn, "CLIENT"):
            return None
        row = conn.execute(
            "SELECT nom, prenom, statut_client FROM CLIENT WHERE id_client = ?", (customer_id,)
        ).fetchone()

    if row is None:
        return None
    return {
        "full_name": f"{row['prenom']} {row['nom']}".strip(),
        "status": row["statut_client"],
    }


def _mask_identifier(value: str, visible_prefix: int = 0, visible_suffix: int = 4) -> str:
    """Masque un identifiant bancaire en ne laissant voir que ses extrémités.

    Le RIB et l'IBAN ne sont pas des secrets au même titre qu'un PAN de carte
    — un client les communique pour recevoir un virement. Ils restent
    néanmoins des identifiants bancaires complets : conformément à la
    politique déjà appliquée aux comptes (`numero_compte_masque`) et aux
    cartes (`numero_carte_masque`), le chatbot n'en émet jamais la valeur
    intégrale. Le RIB complet reste consultable dans l'espace client
    sécurisé.
    """
    if not value:
        return ""
    if len(value) <= visible_prefix + visible_suffix:
        return value
    prefix = value[:visible_prefix]
    suffix = value[-visible_suffix:]
    return f"{prefix} •••• •••• {suffix}".strip()


def get_account_identifiers_for_customer(customer_id: str, db_path: Optional[str] = None) -> list[dict]:
    """Identifiants bancaires (RIB, IBAN, numéro de compte) du client.

    POLITIQUE DE DIVULGATION — décidée explicitement, voir `CLAUDE.md` :

    - `rib` et `iban` sont retournés en CLAIR au propriétaire authentifié.
      Ce ne sont pas des secrets : un client communique son RIB pour recevoir
      un virement, et sa banque le lui affiche dans son espace client. Les
      masquer rendait la fonctionnalité inutile.
    - `numero_compte_masque` reste la référence d'affichage publique.
    - `account_id` (clé primaire interne `id_compte`) n'est JAMAIS exposé :
      c'est un identifiant technique, sans valeur pour le client et utile à
      un attaquant.
    - Le PAN de carte, le CVV, le PIN, les mots de passe, jetons et OTP
      restent interdits en toutes circonstances (voir `CARTE_BANCAIRE`).

    Comme toutes les lectures de ce module, elle exige un `customer_id`
    explicite et filtre dessus : aucun accès aux données d'un autre client.
    """
    with closing(_get_connection(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT id_compte AS account_id, type_compte AS account_type,
                   numero_compte, numero_compte_masque, rib, iban,
                   solde_disponible, devise AS currency
            FROM COMPTE_BANCAIRE
            WHERE id_client = ?
            ORDER BY CASE type_compte WHEN 'courant' THEN 0 ELSE 1 END, id_compte
            """,
            (customer_id,),
        ).fetchall()

    return [
        {
            # `account_id` (id_compte) volontairement ABSENT : clé technique.
            "account_type": row["account_type"],
            "masked_account_number": row["numero_compte_masque"],
            "account_number": row["numero_compte"],
            "rib": row["rib"],
            "iban": row["iban"],
            # Le solde est joint ICI plutôt que recomposé par type de compte :
            # un client peut posséder PLUSIEURS comptes du même type (CL0001 a
            # deux carnets), et un appariement par type en perdrait un.
            "balance": Decimal(row["solde_disponible"]),
            "currency": row["currency"],
        }
        for row in rows
    ]


def get_total_balance(customer_id: str, db_path: Optional[str] = None) -> Decimal:
    with closing(_get_connection(db_path)) as conn:
        rows = conn.execute(
            "SELECT solde_disponible AS balance FROM COMPTE_BANCAIRE WHERE id_client = ?", (customer_id,)
        ).fetchall()
    return sum((Decimal(row["balance"]) for row in rows), Decimal("0"))


def get_balance_at_date(customer_id: str, as_of_date: str, db_path: Optional[str] = None) -> list[dict]:
    """Solde de chaque compte à une date passée (ex. `as_of_date="2026-01-01"`)."""
    with closing(_get_connection(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT COMPTE_BANCAIRE.type_compte AS account_type,
                   account_balance_history.solde AS balance
            FROM account_balance_history
            JOIN COMPTE_BANCAIRE ON COMPTE_BANCAIRE.id_compte = account_balance_history.id_compte
            WHERE COMPTE_BANCAIRE.id_client = ? AND account_balance_history.as_of_date = ?
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
    date_to: Optional[str] = None,
    exact_date: Optional[str] = None,
    amount: Optional[Decimal] = None,
    description_contains: Optional[str] = None,
    order: str = "desc",
    limit: Optional[int] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    """Transactions du client, filtrables et triées de la plus récente à la plus ancienne.

    `direction="debit"` exclut explicitement salaires, virements reçus et tout
    autre crédit — utilisé par les calculs de dépenses par catégorie (défense
    en profondeur, en plus de la séparation déjà assurée par les catégories).
    """
    query = [
        'SELECT "TRANSACTION".id_transaction AS transaction_id,',
        '       "TRANSACTION".date_operation AS transaction_date,',
        '       "TRANSACTION".type_operation AS transaction_type,',
        '       "TRANSACTION".sens AS direction,',
        '       "TRANSACTION".libelle AS description,',
        '       "TRANSACTION".categorie AS category,',
        '       "TRANSACTION".montant AS amount,',
        '       "TRANSACTION".devise AS currency,',
        '       "TRANSACTION".id_compte_lie AS related_account_id,',
        "       COMPTE_BANCAIRE.type_compte AS account_type",
        'FROM "TRANSACTION"',
        'JOIN COMPTE_BANCAIRE ON COMPTE_BANCAIRE.id_compte = "TRANSACTION".id_compte',
        "WHERE COMPTE_BANCAIRE.id_client = ?",
    ]
    params: list = [customer_id]

    if account_type:
        query.append("AND COMPTE_BANCAIRE.type_compte = ?")
        params.append(account_type)
    if category:
        query.append('AND "TRANSACTION".categorie = ?')
        params.append(category)
    if transaction_type:
        query.append('AND "TRANSACTION".type_operation = ?')
        params.append(transaction_type)
    if direction:
        query.append('AND "TRANSACTION".sens = ?')
        params.append(direction)
    if year_month:
        query.append('AND substr("TRANSACTION".date_operation, 1, 7) = ?')
        params.append(year_month)
    if date_from:
        query.append('AND "TRANSACTION".date_operation >= ?')
        params.append(date_from)
    if date_to:
        query.append('AND "TRANSACTION".date_operation <= ?')
        params.append(date_to)
    if exact_date:
        query.append('AND "TRANSACTION".date_operation = ?')
        params.append(exact_date)
    if amount is not None:
        # Comparaison sur la valeur DÉCIMALE, jamais sur la chaîne stockée :
        # "2000.00" et "2000" désignent le même montant.
        query.append('AND CAST("TRANSACTION".montant AS REAL) = CAST(? AS REAL)')
        params.append(str(amount))
    if description_contains:
        query.append('AND LOWER("TRANSACTION".libelle) LIKE ?')
        params.append(f"%{description_contains.lower()}%")

    # `order` est une constante interne (jamais une valeur utilisateur) : la
    # seule valeur alternative acceptée est "asc", tout le reste retombe sur
    # "desc". Aucune interpolation de texte fourni par l'appelant final.
    sens = "ASC" if order == "asc" else "DESC"
    query.append(f'ORDER BY "TRANSACTION".date_operation {sens}, "TRANSACTION".id_transaction {sens}')
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


def get_cards_for_customer(customer_id: str, db_path: Optional[str] = None) -> list[dict]:
    """TOUTES les cartes du client, dans un ordre stable.

    `get_card_for_customer` ci-dessous applique `LIMIT 1` : pratique quand le
    client n'a qu'une carte, mais c'est une sélection SILENCIEUSE dès qu'il en
    a plusieurs. Cette fonction permet à l'assistant de demander laquelle plutôt
    que d'en choisir une au hasard.

    Les montants sont des `Decimal` (jamais `float`) — voir CLAUDE.md règle 7.
    """
    with closing(_get_connection(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT CARTE_BANCAIRE.id_carte AS card_id,
                   CARTE_BANCAIRE.type_carte AS card_type,
                   CARTE_BANCAIRE.numero_carte_masque AS masked_card_number,
                   CARTE_BANCAIRE.statut_carte AS status,
                   CARTE_BANCAIRE.plafond_paiement AS payment_limit,
                   CARTE_BANCAIRE.plafond_retrait AS withdrawal_limit,
                   CARTE_BANCAIRE.paiement_en_ligne_actif AS online_payments_enabled,
                   CARTE_BANCAIRE.paiement_international_actif AS international_payments_enabled
            FROM CARTE_BANCAIRE
            JOIN COMPTE_BANCAIRE ON COMPTE_BANCAIRE.id_compte = CARTE_BANCAIRE.id_compte
            WHERE COMPTE_BANCAIRE.id_client = ?
            ORDER BY CARTE_BANCAIRE.id_carte
            """,
            (customer_id,),
        ).fetchall()

    return [
        {
            "card_id": row["card_id"],
            "card_type": row["card_type"],
            "masked_card_number": row["masked_card_number"],
            "status": row["status"],
            "payment_limit": Decimal(row["payment_limit"]),
            "withdrawal_limit": Decimal(row["withdrawal_limit"]),
            "online_payments_enabled": bool(row["online_payments_enabled"]),
            "international_payments_enabled": bool(row["international_payments_enabled"]),
        }
        for row in rows
    ]


def get_card_for_customer(customer_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    with closing(_get_connection(db_path)) as conn:
        row = conn.execute(
            """
            SELECT CARTE_BANCAIRE.id_carte AS card_id,
                   CARTE_BANCAIRE.type_carte AS card_type,
                   CARTE_BANCAIRE.numero_carte_masque AS masked_card_number,
                   CARTE_BANCAIRE.statut_carte AS status,
                   CARTE_BANCAIRE.plafond_paiement AS payment_limit,
                   CARTE_BANCAIRE.plafond_retrait AS withdrawal_limit,
                   CARTE_BANCAIRE.paiement_en_ligne_actif AS online_payments_enabled,
                   CARTE_BANCAIRE.paiement_international_actif AS international_payments_enabled
            FROM CARTE_BANCAIRE
            JOIN COMPTE_BANCAIRE ON COMPTE_BANCAIRE.id_compte = CARTE_BANCAIRE.id_compte
            WHERE COMPTE_BANCAIRE.id_client = ?
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
            SELECT id_beneficiaire AS beneficiary_id,
                   nom_beneficiaire AS display_name,
                   numero_compte_masque AS masked_account_number,
                   statut AS status,
                   eligible_virement AS eligible_for_transfer
            FROM BENEFICIAIRE
            WHERE id_client = ?
            ORDER BY id_beneficiaire
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


# ---------------------------------------------------------------------------
# UTILISATEUR_E_BANKING — accès aux comptes d'accès en ligne.
#
# Cette table vit dans la base bancaire métier (décision d'architecture), alors
# que la table `sessions` reste dans `auth.db`. SQLite n'autorisant pas de
# `FOREIGN KEY` entre fichiers, la liaison entre une session et son utilisateur
# se fait **par valeur** (`id_utilisateur`), jamais par contrainte physique —
# même principe que la liaison historique `auth.db` <-> base bancaire.
#
# SÉCURITÉ : ce module ne hache ni ne vérifie jamais de mot de passe lui-même.
# Il ne fait que lire/écrire le champ `mot_de_passe_hash` déjà produit par
# bcrypt dans `security/session_manager.py`. Aucun mot de passe en clair n'est
# accepté, stocké ni journalisé ici.
# ---------------------------------------------------------------------------


def upsert_ebanking_user(
    id_utilisateur: str,
    id_client: str,
    identifiant_connexion: str,
    mot_de_passe_hash: str,
    statut_connexion: str = "actif",
    db_path: Optional[str] = None,
) -> str:
    """Crée ou met à jour un compte d'accès en ligne (idempotent).

    `mot_de_passe_hash` doit **déjà** être un hash bcrypt : cette fonction ne
    reçoit jamais de mot de passe en clair.
    """
    init_db(db_path)
    with closing(_get_connection(db_path)) as conn:
        outcome = _upsert(
            conn,
            "UTILISATEUR_E_BANKING",
            ["id_utilisateur"],
            {
                "id_utilisateur": id_utilisateur,
                "id_client": id_client,
                "identifiant_connexion": identifiant_connexion,
                "mot_de_passe_hash": mot_de_passe_hash,
                "statut_connexion": statut_connexion,
                "date_creation": _utcnow_iso(),
            },
        )
        conn.commit()
    return outcome


def find_ebanking_user_by_login(login: str, db_path: Optional[str] = None) -> Optional[dict]:
    """Recherche un compte d'accès par identifiant de connexion OU par e-mail.

    La comparaison est insensible à la casse des deux côtés — un e-mail saisi
    « Malak.Drissi@… » doit retrouver le compte enregistré en minuscules.
    Retourne le hash bcrypt pour vérification par l'appelant, jamais un mot de
    passe. `None` si aucun compte ne correspond.
    """
    if not login:
        return None

    with closing(_get_connection(db_path)) as conn:
        if not _table_exists(conn, "UTILISATEUR_E_BANKING"):
            return None
        row = conn.execute(
            """
            SELECT UTILISATEUR_E_BANKING.id_utilisateur,
                   UTILISATEUR_E_BANKING.id_client,
                   UTILISATEUR_E_BANKING.identifiant_connexion,
                   UTILISATEUR_E_BANKING.mot_de_passe_hash,
                   UTILISATEUR_E_BANKING.statut_connexion,
                   CLIENT.email
            FROM UTILISATEUR_E_BANKING
            LEFT JOIN CLIENT ON CLIENT.id_client = UTILISATEUR_E_BANKING.id_client
            WHERE LOWER(UTILISATEUR_E_BANKING.identifiant_connexion) = LOWER(?)
               OR LOWER(COALESCE(CLIENT.email, '')) = LOWER(?)
            LIMIT 1
            """,
            (login, login),
        ).fetchone()

    if row is None:
        return None

    return {
        "id_utilisateur": row["id_utilisateur"],
        "id_client": row["id_client"],
        "identifiant_connexion": row["identifiant_connexion"],
        "mot_de_passe_hash": row["mot_de_passe_hash"],
        "statut_connexion": row["statut_connexion"],
        "email": row["email"],
    }


def get_ebanking_user(id_utilisateur: str, db_path: Optional[str] = None) -> Optional[dict]:
    """Retourne un compte d'accès par son identifiant technique (sans le hash)."""
    with closing(_get_connection(db_path)) as conn:
        if not _table_exists(conn, "UTILISATEUR_E_BANKING"):
            return None
        row = conn.execute(
            """
            SELECT id_utilisateur, id_client, identifiant_connexion, statut_connexion
            FROM UTILISATEUR_E_BANKING
            WHERE id_utilisateur = ?
            """,
            (id_utilisateur,),
        ).fetchone()

    if row is None:
        return None

    return {
        "id_utilisateur": row["id_utilisateur"],
        "id_client": row["id_client"],
        "identifiant_connexion": row["identifiant_connexion"],
        "statut_connexion": row["statut_connexion"],
    }


def find_ebanking_user_by_client(id_client: str, db_path: Optional[str] = None) -> Optional[dict]:
    """Retourne le compte d'accès d'un CLIENT (sans le hash).

    C'est `id_client` — et non `id_utilisateur` — qui identifie une session :
    toutes les lectures bancaires (`get_total_balance`,
    `get_transactions`…) sont indexées dessus. Voir la note de
    `session_manager` sur la signification de `user_id`.
    """
    with closing(_get_connection(db_path)) as conn:
        if not _table_exists(conn, "UTILISATEUR_E_BANKING"):
            return None
        row = conn.execute(
            """
            SELECT id_utilisateur, id_client, identifiant_connexion, statut_connexion
            FROM UTILISATEUR_E_BANKING
            WHERE id_client = ?
            LIMIT 1
            """,
            (id_client,),
        ).fetchone()

    if row is None:
        return None

    return {
        "id_utilisateur": row["id_utilisateur"],
        "id_client": row["id_client"],
        "identifiant_connexion": row["identifiant_connexion"],
        "statut_connexion": row["statut_connexion"],
    }


def touch_last_login(id_utilisateur: str, db_path: Optional[str] = None) -> None:
    """Horodate la dernière connexion réussie. Silencieux si le compte n'existe pas."""
    with closing(_get_connection(db_path)) as conn:
        if not _table_exists(conn, "UTILISATEUR_E_BANKING"):
            return
        conn.execute(
            "UPDATE UTILISATEUR_E_BANKING SET derniere_connexion = ? WHERE id_utilisateur = ?",
            (_utcnow_iso(), id_utilisateur),
        )
        conn.commit()


def get_spending_breakdown(
    customer_id: str,
    *,
    account_type: Optional[str] = None,
    year_month: Optional[str] = None,
    date_from: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[tuple[str, Decimal]]:
    """Dépenses agrégées PAR CATÉGORIE, de la plus élevée à la plus faible.

    Permet de répondre à « quelle est ma catégorie de dépense la plus
    importante ? » sans ramener toutes les transactions côté Python.
    Exclut, comme `get_spending_total`, les crédits et les virements internes.
    """
    transactions = get_transactions(
        customer_id,
        account_type=account_type,
        year_month=year_month,
        date_from=date_from,
        direction="debit",
        db_path=db_path,
    )
    totaux: dict[str, Decimal] = {}
    for tx in transactions:
        if tx["transaction_type"] == "transfer_out":
            continue
        totaux[tx["category"]] = totaux.get(tx["category"], Decimal("0")) + tx["amount"]
    return sorted(totaux.items(), key=lambda item: item[1], reverse=True)


def get_spending_total(
    customer_id: str,
    category: Optional[str] = None,
    year_month: Optional[str] = None,
    db_path: Optional[str] = None,
    *,
    account_type: Optional[str] = None,
    date_from: Optional[str] = None,
) -> Decimal:
    """Somme des dépenses (jamais salaires/virements reçus/crédits) du client.

    `category=None` calcule le total **toutes catégories confondues** — exclut
    explicitement `transfer_out` (un virement entre les comptes du client
    lui-même n'est pas une "dépense") en plus du filtre `direction="debit"`
    déjà appliqué par `get_transactions`.
    """
    transactions = get_transactions(
        customer_id,
        category=category,
        year_month=year_month,
        account_type=account_type,
        date_from=date_from,
        direction="debit",
        db_path=db_path,
    )
    return sum(
        (tx["amount"] for tx in transactions if tx["transaction_type"] != "transfer_out"),
        Decimal("0"),
    )
