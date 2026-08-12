#!/usr/bin/env python3
"""Migre l'ancienne base bancaire vers le schéma métier réaliste.

    ancienne base (banking.db)          nouvelle base (demo_bancaire.db)
    ---------------------------         --------------------------------
    customers                    ->     CLIENT
    accounts                     ->     COMPTE_BANCAIRE      (+ rib, iban, numero_compte)
    cards                        ->     CARTE_BANCAIRE       (+ date_expiration)
    transactions                 ->     "TRANSACTION"
    beneficiaries                ->     BENEFICIAIRE         (+ rib)
    account_balance_history      ->     account_balance_history  (colonnes renommées)
    (aucune)                     ->     UTILISATEUR_E_BANKING    (voir ci-dessous)

Usage :
    python scripts/migrate_banking_database.py --dry-run
    python scripts/migrate_banking_database.py

PRINCIPE DE SÛRETÉ — la source n'est JAMAIS modifiée
----------------------------------------------------
La base source est ouverte en LECTURE SEULE (`mode=ro`), et le script refuse
de s'exécuter si source et cible désignent le même fichier. L'ancienne
`banking.db` reste donc intacte et peut servir de sauvegarde immédiate en cas
de retour arrière.

CHAMPS ABSENTS DE L'ANCIEN SCHÉMA
---------------------------------
`rib`, `iban`, `numero_compte`, `email`, `telephone_mobile` et
`date_expiration` n'existent pas dans l'ancienne base. Ils sont DÉRIVÉS de
façon déterministe des identifiants existants (mêmes fonctions que
`banking_db`), jamais tirés au hasard : deux exécutions produisent une base
identique.

UTILISATEUR_E_BANKING
---------------------
L'ancienne base ne contenait aucun compte d'accès en ligne (ils vivaient dans
`auth.db.users`). Ce script ne fabrique donc AUCUN compte d'accès : il ne
peut pas inventer de hash bcrypt, et n'a jamais accès à un mot de passe en
clair. Les utilisateurs migrés continuent de s'authentifier par le repli
legacy `auth.db.users` (voir `session_manager`), ou sont créés séparément par
`scripts/seed_demo_database.py`.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from app.banking import banking_db  # noqa: E402

DEFAULT_SOURCE = "./backend/data/banking.db"
DEFAULT_TARGET = "./backend/data/demo_bancaire.db"

# Tables attendues dans une base à l'ANCIEN schéma.
_LEGACY_TABLES = ("customers", "accounts", "transactions", "cards", "beneficiaries")


class MigrationError(RuntimeError):
    """Erreur bloquante de migration — toujours accompagnée de la marche à suivre."""


def _open_readonly(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _legacy_tables_present(conn: sqlite3.Connection) -> set:
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def inspect_source(source_path: str) -> dict:
    """Décrit la base source sans rien y écrire."""
    resolved = banking_db._resolve_path(source_path)
    if not Path(resolved).exists():
        raise MigrationError(
            f"Base source introuvable : {resolved}. "
            "Vérifiez --source, ou lancez directement scripts/seed_demo_database.py "
            "si vous n'avez pas d'ancienne base à convertir."
        )

    with closing(_open_readonly(resolved)) as conn:
        tables = _legacy_tables_present(conn)
        missing = [table for table in _LEGACY_TABLES if table not in tables]
        if missing:
            raise MigrationError(
                f"La base {resolved} ne contient pas l'ancien schéma "
                f"(tables manquantes : {', '.join(missing)}). "
                "Elle a peut-être déjà été migrée — dans ce cas il n'y a rien à faire."
            )
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in sorted(tables)}

    return {"path": resolved, "counts": counts}


def migrate(source_path: str = DEFAULT_SOURCE, target_path: str = DEFAULT_TARGET) -> dict:
    """Convertit la base source vers le nouveau schéma dans la base cible."""
    source_resolved = banking_db._resolve_path(source_path)
    target_resolved = banking_db._resolve_path(target_path)

    if Path(source_resolved) == Path(target_resolved):
        raise MigrationError(
            "La source et la cible désignent le même fichier. La migration écrit "
            "toujours dans une base DISTINCTE, pour que l'ancienne reste "
            "utilisable en sauvegarde."
        )

    inspect_source(source_resolved)
    banking_db.init_db(target_resolved)

    migrated = {"CLIENT": 0, "COMPTE_BANCAIRE": 0, "account_balance_history": 0,
                "TRANSACTION": 0, "BENEFICIAIRE": 0, "CARTE_BANCAIRE": 0}
    now = banking_db._utcnow_iso()

    with closing(_open_readonly(source_resolved)) as source, \
            closing(banking_db._get_connection(target_resolved)) as target:

        for row in source.execute("SELECT * FROM customers"):
            first_name, _, last_name = (row["full_name"] or "").partition(" ")
            index = row["customer_id"].split("_")[-1]
            banking_db._upsert(target, "CLIENT", ["id_client"], {
                "id_client": row["customer_id"],
                "nom": last_name or first_name or row["customer_id"],
                "prenom": first_name,
                # Absents de l'ancien schéma : générés de façon déterministe.
                "telephone_mobile": f"06000000{index[-2:]}",
                "email": f"client{index}@example.invalid",
                "statut_client": "actif" if row["status"] == "active" else row["status"],
                "date_creation": row["created_at"] or now,
            })
            migrated["CLIENT"] += 1

        for row in source.execute("SELECT * FROM accounts"):
            rib = banking_db._rib_from_account_id(row["account_id"] + row["account_type"])
            banking_db._upsert(target, "COMPTE_BANCAIRE", ["id_compte"], {
                "id_compte": row["account_id"],
                "id_client": row["customer_id"],
                "numero_compte": rib[6:22],
                "numero_compte_masque": row["masked_account_number"],
                "rib": rib,
                "iban": banking_db._iban_from_rib(rib),
                "type_compte": row["account_type"],
                "devise": row["currency"],
                "solde_disponible": row["balance"],
                "date_creation": row["created_at"] or now,
            })
            migrated["COMPTE_BANCAIRE"] += 1

        for row in source.execute("SELECT * FROM account_balance_history"):
            banking_db._upsert(target, "account_balance_history", ["id_compte", "as_of_date"], {
                "id_compte": row["account_id"],
                "as_of_date": row["as_of_date"],
                "solde": row["balance"],
                "date_creation": row["created_at"] or now,
            })
            migrated["account_balance_history"] += 1

        for row in source.execute("SELECT * FROM transactions"):
            banking_db._upsert(target, '"TRANSACTION"', ["id_transaction"], {
                "id_transaction": row["transaction_id"],
                "id_compte": row["account_id"],
                "date_operation": row["transaction_date"],
                "type_operation": row["transaction_type"],
                "sens": row["direction"],
                "libelle": row["description"],
                "categorie": row["category"],
                "montant": row["amount"],
                "devise": row["currency"],
                "id_compte_lie": row["related_account_id"],
                "date_creation": row["created_at"] or now,
            })
            migrated["TRANSACTION"] += 1

        for row in source.execute("SELECT * FROM beneficiaries"):
            banking_db._upsert(target, "BENEFICIAIRE", ["id_beneficiaire"], {
                "id_beneficiaire": row["beneficiary_id"],
                "id_client": row["owner_customer_id"],
                "nom_beneficiaire": row["display_name"],
                "rib": banking_db._rib_from_account_id(row["beneficiary_id"]),
                "numero_compte_masque": row["masked_account_number"],
                "statut": "actif" if row["status"] == "active" else row["status"],
                "eligible_virement": row["eligible_for_transfer"],
                "date_creation": row["created_at"] or now,
            })
            migrated["BENEFICIAIRE"] += 1

        for row in source.execute("SELECT * FROM cards"):
            banking_db._upsert(target, "CARTE_BANCAIRE", ["id_carte"], {
                "id_carte": row["card_id"],
                "id_compte": row["account_id"],
                "numero_carte_masque": row["masked_card_number"],
                "type_carte": row["card_type"],
                "date_expiration": "2029-12-31",  # absent de l'ancien schéma
                "statut_carte": row["status"],
                "plafond_paiement": row["payment_limit"],
                "plafond_retrait": row["withdrawal_limit"],
                "paiement_en_ligne_actif": row["online_payments_enabled"],
                "paiement_international_actif": row["international_payments_enabled"],
                "date_creation": row["created_at"] or now,
            })
            migrated["CARTE_BANCAIRE"] += 1

        target.commit()

    return {"source": source_resolved, "target": target_resolved, "migrated": migrated}


def main() -> None:
    parser = argparse.ArgumentParser(description="Migre banking.db vers le schéma métier réaliste.")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--dry-run", action="store_true", help="Inspecte la source sans rien écrire.")
    args = parser.parse_args()

    try:
        if args.dry_run:
            info = inspect_source(args.source)
            print(f"Source : {info['path']}  (LECTURE SEULE, aucune écriture)")
            for table, count in info["counts"].items():
                print(f"  {table:26} {count:5} lignes")
            print(f"\nCible qui serait écrite : {banking_db._resolve_path(args.target)}")
            return

        result = migrate(args.source, args.target)
        print(f"Source (inchangée) : {result['source']}")
        print(f"Cible              : {result['target']}")
        for table, count in result["migrated"].items():
            print(f"  {table:26} {count:5} lignes migrées")
        print("\nAucun compte UTILISATEUR_E_BANKING créé : l'ancienne base n'en contenait pas.")
        print("Lancez scripts/seed_demo_database.py pour la base de démonstration 100 clients.")
    except MigrationError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
