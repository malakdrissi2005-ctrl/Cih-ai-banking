"""Initialise `auth.db` avec les utilisateurs de démonstration de `data/auth/users_seed.json`.

Voir `backend/app/security/session_manager.py` (`seed_users`) pour la logique :
lecture/validation du fichier, création des tables si nécessaire, import
idempotent (upsert par `user_id`, jamais de doublon), hash bcrypt uniquement
(`DEMO_DEFAULT_PASSWORD` requise), aucune session créée.

Utilisation en CLI :
    python scripts/seed_auth_users.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Exécution directe en script : le répertoire ajouté automatiquement à
# sys.path est celui de ce fichier (scripts/), pas `backend/`. On ajoute donc
# explicitement `backend/` pour pouvoir importer `app.security.session_manager`
# exactement comme le fait `backend/app/main.py` lorsqu'il est lancé par uvicorn.
_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.security.session_manager import UsersSeedValidationError, seed_users  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed-path", default=None, help="Chemin vers users_seed.json (défaut : data/auth/users_seed.json)"
    )
    parser.add_argument(
        "--db-path", default=None, help="Chemin vers auth.db (défaut : AUTH_DB_PATH ou ./auth.db)"
    )
    args = parser.parse_args()

    try:
        stats = seed_users(seed_path=args.seed_path, db_path=args.db_path)
    except (UsersSeedValidationError, RuntimeError) as exc:
        print(f"Erreur d'initialisation des utilisateurs : {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Fichier source              : {stats['seed_path']}")
    print(f"Utilisateurs dans le fichier: {stats['total_entries']}")
    print(f"Insérés                     : {stats['inserted']}")
    print(f"Mis à jour                  : {stats['updated']}")
    print(f"Total dans auth.db (users)  : {stats['users_in_db']}")
    print(f"Total dans auth.db (sessions): {stats['sessions_in_db']}")


if __name__ == "__main__":
    main()
