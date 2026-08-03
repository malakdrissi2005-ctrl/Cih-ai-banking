"""Outils internes de l'Agent 1 — seule surface que le LLM Router (`llm_router.py`)
est autorisé à *choisir* (jamais à appeler directement, jamais à générer
lui-même une donnée bancaire).

Le LLM ne reçoit et ne produit **jamais** de montant, de date, de solde ou
toute autre donnée personnelle : il se contente d'extraire un `intent` et des
paramètres (catégorie, période...) au format JSON. C'est le code Python
ci-dessous — jamais le modèle — qui appelle réellement `banking_db`/`rag` avec
le `user_id` fourni par la session validée côté serveur, et qui retourne la
donnée réelle à insérer dans une phrase de réponse déjà existante
(`banking_answers.py`/`response_localizer.py`).

Chaque fonction ci-dessous exige explicitement un `user_id` — jamais déduit
d'un texte libre ni d'un champ produit par le LLM — reprenant exactement la
même garantie d'isolation que `banking_db.py` (voir `CLAUDE.md` §5, §9 et
`agents/agent1_faq/banking_answers.py`).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from agents.agent1_faq.rag import get_faq_collection, search_faq
from app.banking import banking_db


def search_public_faq(question: str, collection: Any = None) -> Optional[dict]:
    """Recherche FAQ publique (ChromaDB) — jamais de donnée personnelle.

    `collection` permet l'injection d'une collection isolée en test ; par
    défaut, la collection persistante `faq_generale` est utilisée.
    """
    resolved_collection = collection or get_faq_collection()
    return search_faq(resolved_collection, question)


def get_account_balance(user_id: str, db_path: Optional[str] = None) -> dict:
    """Solde total + détail par compte, pour le `user_id` de la session authentifiée."""
    accounts = banking_db.get_accounts_for_customer(user_id, db_path=db_path)
    total = banking_db.get_total_balance(user_id, db_path=db_path)
    return {"accounts": accounts, "total": total}


def get_transactions(
    user_id: str,
    *,
    limit: Optional[int] = None,
    category: Optional[str] = None,
    year_month: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    """Dernières opérations du client, filtrables par catégorie/mois."""
    return banking_db.get_transactions(
        user_id, category=category, year_month=year_month, limit=limit, db_path=db_path
    )


def get_card_information(user_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    """Informations complètes de la carte du client (statut, plafonds, autorisations)."""
    return banking_db.get_card_for_customer(user_id, db_path=db_path)


def get_beneficiaries(user_id: str, db_path: Optional[str] = None) -> list[dict]:
    """Bénéficiaires enregistrés pour le client."""
    return banking_db.get_beneficiaries_for_customer(user_id, db_path=db_path)


def get_spending_summary(
    user_id: str,
    category: Optional[str] = None,
    period: str = "current_month",
    db_path: Optional[str] = None,
) -> Decimal:
    """Total des dépenses du client (catégorie optionnelle, période "current_month"/"last_month").

    `category=None` retourne le total toutes catégories confondues (voir
    `banking_db.get_spending_total`, qui exclut déjà les virements internes).
    """
    year_month = banking_db.DEMO_CURRENT_MONTH if period == "current_month" else banking_db.DEMO_LAST_MONTH
    return banking_db.get_spending_total(user_id, category=category, year_month=year_month, db_path=db_path)
