"""Initialise `backend/data/banking.db` avec les données bancaires fictives de démonstration.

Voir `backend/app/banking/banking_db.py` (`seed_banking_data`) pour la
logique : création des tables si nécessaire, upsert idempotent (jamais de
doublon), montants en `Decimal`/chaîne décimale. Base séparée de `auth.db`,
liée par valeur via `user_id`/`customer_id` (`usr_001`…`usr_005`).

Utilisation en CLI :
    python scripts/seed_banking_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Exécution directe en script : le répertoire ajouté automatiquement à
# sys.path est celui de ce fichier (scripts/), pas `backend/`. On ajoute donc
# explicitement `backend/`, comme le fait déjà `scripts/seed_auth_users.py`.
_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.banking.banking_db import seed_banking_data  # noqa: E402


def main() -> None:
    stats = seed_banking_data()

    print(f"Base bancaire            : {stats['db_path']}")
    print(f"Clients en base          : {stats['customers_in_db']}")
    print(f"Comptes en base          : {stats['accounts_in_db']}")
    print(f"Historique de solde      : {stats['balance_history_in_db']}")
    print(f"Transactions en base     : {stats['transactions_in_db']}")
    print(f"Bénéficiaires en base    : {stats['beneficiaries_in_db']}")
    print(f"Cartes en base           : {stats['cards_in_db']}")
    print("Détail de cette exécution (insertions / mises à jour) :")
    for table, counts in stats["changes"].items():
        print(f"  - {table:<14}: {counts['inserted']} insérée(s), {counts['updated']} mise(s) à jour")


if __name__ == "__main__":
    main()
