#!/usr/bin/env python3
"""Génère la base de démonstration `demo_bancaire.db` — 100 clients réalistes.

Usage :
    python scripts/seed_demo_database.py
    python scripts/seed_demo_database.py --db-path ./backend/data/demo_bancaire.db

DÉTERMINISME — propriété centrale de ce script
----------------------------------------------
Deux exécutions produisent des bases STRICTEMENT identiques (mêmes noms,
mêmes soldes, mêmes transactions, mêmes RIB). Cela repose sur trois règles,
qui doivent être préservées par toute évolution :

1. Un unique générateur `random.Random(SEED)` local, jamais le `random` global
   du module (que d'autres imports pourraient réamorcer).
2. Aucune dépendance à l'horloge : les dates sont ancrées sur
   `banking_db.DEMO_REFERENCE_DATE` (2026-07-28), jamais sur `datetime.now()`.
   C'est aussi ce qui garantit que « ce mois-ci » / « le mois dernier »
   renvoient des résultats stables en démonstration.
3. Les identifiants sont dérivés de l'index du client (`CL0001`, `EB0001`…),
   jamais tirés au hasard.

Le seul champ non déterministe possible serait le sel bcrypt ; il est neutralisé
en ne calculant QUE DEUX hashs (voir `_build_password_hashes`).

SÉCURITÉ
--------
- bcrypt est utilisé UNIQUEMENT pour produire les hashs. Aucun mot de passe en
  clair n'est écrit en base, ni journalisé, ni affiché par ce script.
- Les numéros de carte sont générés directement sous forme MASQUÉE
  (`450012XXXXXX3456`) : le numéro complet n'existe à aucun moment, pas même
  en mémoire.

DONNÉES FICTIVES
----------------
Toutes les données sont fictives (voir `CLAUDE.md` §9.5), à une exception
documentée : le client `CL0001` porte les coordonnées réelles de l'étudiante
propriétaire du projet, à sa demande explicite, pour servir de compte de
démonstration ACP/OCP.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "backend"))

import bcrypt  # noqa: E402

from app.banking import banking_db  # noqa: E402

# --- Paramètres de génération (toute modification change la base produite) ---
SEED = 20242025
NB_CLIENTS = 100
NAMES_PATH = _REPO_ROOT / "data" / "demo" / "moroccan_names.json"

# --- Client de démonstration, réservé au rang 1 ---
DEMO_CLIENT_ID = "CL0001"
DEMO_NOM = "Drissi"
DEMO_PRENOM = "Malak"
DEMO_EMAIL = "malakdrissi2005@gmail.com"
DEMO_TELEPHONE = "0690184186"
DEMO_LOGIN = "malak.drissi"
# Mot de passe en clair utilisé UNIQUEMENT pour produire le hash bcrypt
# ci-dessous. Il n'est jamais stocké en base.
DEMO_PASSWORD = "UnivEnsam20242025?!"
# Mot de passe commun aux 99 clients fictifs (aucun n'est un compte réel).
FIXTURE_PASSWORD = "Demo2026!Cih"

TYPES_CARTE = ("Visa Classic", "Visa Gold", "Mastercard")
STATUTS_CLIENT = ("actif", "actif", "actif", "actif", "inactif", "suspendu")

# Catégories de dépense, alignées sur celles que sait interroger l'Agent 1
# (voir `banking_answers._CATEGORY_GROUPS`).
CATEGORIES_DEPENSE = (
    ("Restaurants", "Paiement carte restaurant"),
    ("Courses", "Paiement carte supermarché"),
    ("Transport", "Paiement carte transport"),
    ("Carburant", "Paiement carte station-service"),
    ("Logement", "Prélèvement loyer"),
    ("Assurance", "Prélèvement assurance"),
    ("Abonnement", "Prélèvement abonnement internet"),
)

_REFERENCE_DATE = date.fromisoformat(banking_db.DEMO_REFERENCE_DATE)


def _load_names() -> dict:
    return json.loads(NAMES_PATH.read_text(encoding="utf-8"))


def _build_password_hashes() -> tuple[str, str]:
    """Calcule les DEUX seuls hashs bcrypt de tout le script.

    bcrypt est volontairement lent (~300 ms par hash, mesuré) : en hacher 100
    coûterait une trentaine de secondes. Les 99 clients fictifs partagent donc
    le même mot de passe de démonstration, donc le même hash, calculé une seule
    fois. Le client `CL0001` reçoit son propre hash, distinct.

    Le sel bcrypt étant aléatoire, ces deux hashs diffèrent d'une exécution à
    l'autre : c'est la seule valeur non déterministe de la base, et c'est
    voulu — un sel figé serait une faute de sécurité.
    """
    demo_hash = bcrypt.hashpw(DEMO_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    fixture_hash = bcrypt.hashpw(FIXTURE_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return demo_hash, fixture_hash


def _masked_card_number(rng: random.Random) -> str:
    """Numéro de carte au format masqué `450012XXXXXX3456`.

    Le numéro complet n'est jamais construit : seuls le BIN (6 chiffres) et
    les 4 derniers sont tirés, la partie centrale est littéralement `XXXXXX`.
    """
    bin_prefix = rng.choice(("450012", "450078", "521345"))
    last_four = f"{rng.randint(0, 9999):04d}"
    return f"{bin_prefix}XXXXXX{last_four}"


def _client_profile(index: int, names: dict, rng: random.Random) -> dict:
    """Identité d'un client. Le rang 1 est TOUJOURS le compte de démonstration."""
    if index == 1:
        return {
            "id_client": DEMO_CLIENT_ID,
            "nom": DEMO_NOM,
            "prenom": DEMO_PRENOM,
            "telephone_mobile": DEMO_TELEPHONE,
            "email": DEMO_EMAIL,
            "statut_client": "actif",
            "identifiant_connexion": DEMO_LOGIN,
            "est_compte_demo": True,
        }

    feminin = rng.random() < 0.5
    prenom = rng.choice(names["prenoms_feminins"] if feminin else names["prenoms_masculins"])
    nom = rng.choice(names["noms_famille"])
    slug = f"{prenom}.{nom}".lower().replace(" ", "").replace("'", "")
    return {
        "id_client": f"CL{index:04d}",
        "nom": nom,
        "prenom": prenom,
        # Numéro marocain fictif : préfixe mobile valide, suffixe dérivé de
        # l'index pour rester unique et déterministe.
        "telephone_mobile": f"06{rng.choice(('12', '61', '70', '77'))}{index:04d}{rng.randint(10, 99)}",
        # Domaine `.invalid` (RFC 2606) : jamais routable, aucune adresse réelle
        # ne peut être atteinte par accident.
        "email": f"{slug}{index:03d}@example.invalid",
        "statut_client": rng.choice(STATUTS_CLIENT),
        "identifiant_connexion": f"{slug}{index:03d}",
        "est_compte_demo": False,
    }


def _generate_accounts(profile: dict, index: int, rng: random.Random) -> list[dict]:
    """1 à 3 comptes par client, dont toujours un compte courant."""
    nb_comptes = rng.choice((1, 2, 2, 3))
    types = ["courant"] + rng.sample(["carnet", "epargne_projet"], k=min(nb_comptes - 1, 2))[: nb_comptes - 1]

    comptes = []
    for rang, type_brut in enumerate(types, start=1):
        # Le schéma n'autorise que 'courant' et 'carnet' : tout compte
        # secondaire est un carnet (contrainte CHECK de COMPTE_BANCAIRE).
        type_compte = "courant" if type_brut == "courant" else "carnet"
        id_compte = f"AC{index:04d}{rang}"
        rib = banking_db._rib_from_account_id(f"{id_compte}{type_compte}")
        solde = Decimal(rng.randint(10000, 10000000)) / Decimal(100)  # 100.00 -> 100000.00 MAD
        comptes.append(
            {
                "id_compte": id_compte,
                "type_compte": type_compte,
                "rib": rib,
                "iban": banking_db._iban_from_rib(rib),
                "numero_compte": rib[6:22],
                "numero_compte_masque": f"CIH •••• {rib[-4:]}",
                "solde_disponible": solde,
            }
        )
    return comptes


def _generate_balance_history(solde_actuel: Decimal, rng: random.Random) -> list[tuple[str, Decimal]]:
    """Historique trimestriel, cohérent avec le solde actuel (croissance douce)."""
    history = []
    solde = solde_actuel
    for as_of_date in ("2026-07-01", "2026-04-01", "2026-01-01"):
        variation = Decimal(rng.randint(500, 8000)) / Decimal(100)
        solde = max(Decimal("100.00"), solde - variation)
        history.append((as_of_date, solde))
    return list(reversed(history))


def _generate_transactions(compte: dict, index: int, rng: random.Random) -> list[dict]:
    """10 à 50 transactions par compte courant, ancrées sur la date de référence.

    Couvre les cinq familles demandées : salaire, virement, paiement carte,
    retrait GAB, prélèvement. Les dates couvrent le mois en cours et le mois
    précédent, pour que les questions temporelles de l'Agent 1 renvoient
    toujours un résultat.
    """
    nb = rng.randint(10, 50)
    transactions = []

    # Salaire mensuel — toujours présent, sur le compte courant uniquement.
    salaire = Decimal(rng.randint(400000, 3000000)) / Decimal(100)
    for mois, jour in (("2026-07", 25), ("2026-06", 25)):
        transactions.append(
            {
                "id_transaction": f"TX{index:04d}{len(transactions):03d}",
                "date_operation": f"{mois}-{jour:02d}",
                "type_operation": "salary",
                "sens": "credit",
                "libelle": "Virement salaire (fictif)",
                "categorie": "Salaire",
                "montant": salaire,
            }
        )

    # Virement reçu — permet de tester "ai-je reçu un virement cette semaine".
    transactions.append(
        {
            "id_transaction": f"TX{index:04d}{len(transactions):03d}",
            "date_operation": "2026-07-26",
            "type_operation": "incoming_transfer",
            "sens": "credit",
            "libelle": "Virement reçu (fictif)",
            "categorie": "Virement reçu",
            "montant": Decimal(rng.randint(10000, 500000)) / Decimal(100),
        }
    )

    # Retrait GAB — au moins un.
    transactions.append(
        {
            "id_transaction": f"TX{index:04d}{len(transactions):03d}",
            "date_operation": "2026-07-12",
            "type_operation": "withdrawal",
            "sens": "debit",
            "libelle": "Retrait GAB (fictif)",
            "categorie": "Retrait",
            "montant": Decimal(rng.randint(10000, 200000)) / Decimal(100),
        }
    )

    # Le reste : paiements carte et prélèvements, répartis sur deux mois.
    while len(transactions) < nb:
        categorie, libelle = rng.choice(CATEGORIES_DEPENSE)
        est_prelevement = categorie in ("Logement", "Assurance", "Abonnement")
        jours_avant = rng.randint(0, 58)
        jour = _REFERENCE_DATE - timedelta(days=jours_avant)
        transactions.append(
            {
                "id_transaction": f"TX{index:04d}{len(transactions):03d}",
                "date_operation": jour.isoformat(),
                "type_operation": "direct_debit" if est_prelevement else "card_payment",
                "sens": "debit",
                "libelle": f"{libelle} (fictif)",
                "categorie": categorie,
                "montant": Decimal(rng.randint(1500, 150000)) / Decimal(100),
            }
        )

    return transactions


def _generate_beneficiaries(profile: dict, index: int, names: dict, rng: random.Random) -> list[dict]:
    """1 à 4 bénéficiaires par client."""
    beneficiaires = []
    for rang in range(1, rng.randint(1, 4) + 1):
        prenom = rng.choice(names["prenoms_feminins"] + names["prenoms_masculins"])
        nom = rng.choice(names["noms_famille"])
        id_beneficiaire = f"BN{index:04d}{rang}"
        rib = banking_db._rib_from_account_id(id_beneficiaire)
        beneficiaires.append(
            {
                "id_beneficiaire": id_beneficiaire,
                "nom_beneficiaire": f"{prenom} {nom}",
                "rib": rib,
                "numero_compte_masque": f"{rng.choice(('CIH', 'BMCE', 'BP', 'AWB'))} •••• {rib[-4:]}",
                "statut": "actif",
                "eligible_virement": 1 if rng.random() < 0.9 else 0,
            }
        )
    return beneficiaires


def seed_demo_database(db_path: str | None = None, nb_clients: int = NB_CLIENTS) -> dict:
    """Génère la base de démonstration complète. Idempotent (upsert par clé)."""
    names = _load_names()
    rng = random.Random(SEED)
    demo_hash, fixture_hash = _build_password_hashes()

    banking_db.init_db(db_path)
    now = banking_db._utcnow_iso()

    stats = {"clients": 0, "utilisateurs": 0, "comptes": 0, "historique": 0,
             "transactions": 0, "cartes": 0, "beneficiaires": 0}

    from contextlib import closing

    with closing(banking_db._get_connection(db_path)) as conn:
        for index in range(1, nb_clients + 1):
            profile = _client_profile(index, names, rng)

            banking_db._upsert(conn, "CLIENT", ["id_client"], {
                "id_client": profile["id_client"],
                "nom": profile["nom"],
                "prenom": profile["prenom"],
                "telephone_mobile": profile["telephone_mobile"],
                "email": profile["email"],
                "statut_client": profile["statut_client"],
                "date_creation": now,
            })
            stats["clients"] += 1

            banking_db._upsert(conn, "UTILISATEUR_E_BANKING", ["id_utilisateur"], {
                "id_utilisateur": f"EB{index:04d}",
                "id_client": profile["id_client"],
                "identifiant_connexion": profile["identifiant_connexion"],
                # bcrypt uniquement — jamais de mot de passe en clair.
                "mot_de_passe_hash": demo_hash if profile["est_compte_demo"] else fixture_hash,
                "statut_connexion": "actif" if profile["statut_client"] == "actif" else "bloque",
                "derniere_connexion": None,
                "date_creation": now,
            })
            stats["utilisateurs"] += 1

            comptes = _generate_accounts(profile, index, rng)
            for compte in comptes:
                banking_db._upsert(conn, "COMPTE_BANCAIRE", ["id_compte"], {
                    "id_compte": compte["id_compte"],
                    "id_client": profile["id_client"],
                    "numero_compte": compte["numero_compte"],
                    "numero_compte_masque": compte["numero_compte_masque"],
                    "rib": compte["rib"],
                    "iban": compte["iban"],
                    "type_compte": compte["type_compte"],
                    "devise": "MAD",
                    "solde_disponible": str(compte["solde_disponible"]),
                    "date_creation": now,
                })
                stats["comptes"] += 1

                for as_of_date, solde in _generate_balance_history(compte["solde_disponible"], rng):
                    banking_db._upsert(conn, "account_balance_history", ["id_compte", "as_of_date"], {
                        "id_compte": compte["id_compte"],
                        "as_of_date": as_of_date,
                        "solde": str(solde),
                        "date_creation": now,
                    })
                    stats["historique"] += 1

            # Transactions et carte : sur le compte COURANT (le premier).
            compte_courant = comptes[0]
            for tx in _generate_transactions(compte_courant, index, rng):
                banking_db._upsert(conn, '"TRANSACTION"', ["id_transaction"], {
                    "id_transaction": tx["id_transaction"],
                    "id_compte": compte_courant["id_compte"],
                    "date_operation": tx["date_operation"],
                    "type_operation": tx["type_operation"],
                    "sens": tx["sens"],
                    "libelle": tx["libelle"],
                    "categorie": tx["categorie"],
                    "montant": str(tx["montant"]),
                    "devise": "MAD",
                    "id_compte_lie": None,
                    "date_creation": now,
                })
                stats["transactions"] += 1

            actif = profile["statut_client"] == "actif"
            banking_db._upsert(conn, "CARTE_BANCAIRE", ["id_carte"], {
                "id_carte": f"CB{index:04d}",
                "id_compte": compte_courant["id_compte"],
                "numero_carte_masque": _masked_card_number(rng),
                "type_carte": rng.choice(TYPES_CARTE),
                "date_expiration": f"{rng.randint(2027, 2030)}-{rng.randint(1, 12):02d}-28",
                "statut_carte": "active" if actif else "blocked",
                "plafond_paiement": str(Decimal(rng.choice((3000, 5000, 10000, 20000)))),
                "plafond_retrait": str(Decimal(rng.choice((1500, 2000, 4000, 8000)))),
                "paiement_en_ligne_actif": 1 if rng.random() < 0.85 else 0,
                "paiement_international_actif": 1 if rng.random() < 0.6 else 0,
                "date_creation": now,
            })
            stats["cartes"] += 1

            for beneficiaire in _generate_beneficiaries(profile, index, names, rng):
                banking_db._upsert(conn, "BENEFICIAIRE", ["id_beneficiaire"], {
                    "id_beneficiaire": beneficiaire["id_beneficiaire"],
                    "id_client": profile["id_client"],
                    "nom_beneficiaire": beneficiaire["nom_beneficiaire"],
                    "rib": beneficiaire["rib"],
                    "numero_compte_masque": beneficiaire["numero_compte_masque"],
                    "statut": beneficiaire["statut"],
                    "eligible_virement": beneficiaire["eligible_virement"],
                    "date_creation": now,
                })
                stats["beneficiaires"] += 1

        conn.commit()

    return {
        "db_path": banking_db._resolve_path(db_path) if db_path else banking_db.DEFAULT_DB_PATH,
        "seed": SEED,
        **stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère demo_bancaire.db (100 clients fictifs).")
    parser.add_argument("--db-path", default="./backend/data/demo_bancaire.db")
    parser.add_argument("--nb-clients", type=int, default=NB_CLIENTS)
    args = parser.parse_args()

    stats = seed_demo_database(db_path=args.db_path, nb_clients=args.nb_clients)

    print(f"Base générée : {stats['db_path']}")
    print(f"  graine déterministe : {stats['seed']}")
    print(f"  clients             : {stats['clients']}")
    print(f"  utilisateurs        : {stats['utilisateurs']}")
    print(f"  comptes             : {stats['comptes']}")
    print(f"  historique de solde : {stats['historique']}")
    print(f"  transactions        : {stats['transactions']}")
    print(f"  cartes              : {stats['cartes']}")
    print(f"  bénéficiaires       : {stats['beneficiaires']}")
    print()
    print(f"Compte de démonstration : {DEMO_EMAIL}  (identifiant : {DEMO_LOGIN})")
    print("Mot de passe : voir DEMO_PASSWORD dans ce script — jamais stocké en base.")


if __name__ == "__main__":
    main()
