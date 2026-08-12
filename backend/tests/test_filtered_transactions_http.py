"""Requêtes transactionnelles et de dépenses filtrées — VIA `POST /api/chat`.

Ces tests valident le RUNTIME, pas l'extracteur isolé : chaque question
traverse la route FastAPI réelle, le routeur, LangGraph, l'extraction de
paramètres, le SQL filtré et la localisation.

Ils couvrent les six défauts constatés en exécution réelle :
1. « Mes paiements restaurant de ce mois-ci » ignorait catégorie et période ;
2. « Ai-je reçu un paiement de 2000 MAD hier ? » ignorait sens/montant/date ;
3. « Quelles sommes sont entrées… » renvoyait un résumé de compte ;
4. « Quelle catégorie… la plus importante ? » renvoyait un total global ;
5. `werini akher 5 operations` partait en FAQ ;
6. `ch7al dkhel l compte courant had simana` renvoyait le solde.
"""
import sqlite3
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.banking import banking_db
from app.main import app
from app.routers.auth import get_auth_db_path, get_banking_db_path
from app.routers.chat import (
    get_banking_db_path_dependency,
    get_faq_collection_dependency,
    get_use_llm_router_dependency,
)
from app.security import session_manager

CLIENT_A = "CL0001"
CLIENT_B = "CL0042"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    from agents.agent1_faq.rag import get_faq_collection
    from scripts.ingest_faq import ingest_faq
    from scripts.seed_demo_database import seed_demo_database

    root = tmp_path_factory.mktemp("filtres")
    banking_path = str(root / "demo_bancaire.db")
    auth_path = str(root / "auth.db")
    chroma_dir = str(root / "chroma")

    seed_demo_database(db_path=banking_path)
    session_manager.init_db(auth_path)
    ingest_faq(persist_dir=chroma_dir, collection_name="faq_filtres_test")
    collection = get_faq_collection(persist_dir=chroma_dir, collection_name="faq_filtres_test")

    app.dependency_overrides[get_auth_db_path] = lambda: auth_path
    app.dependency_overrides[get_banking_db_path] = lambda: banking_path
    app.dependency_overrides[get_banking_db_path_dependency] = lambda: banking_path
    app.dependency_overrides[get_faq_collection_dependency] = lambda: collection
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: False

    yield {
        "client": TestClient(app, raise_server_exceptions=False),
        "db": banking_path,
        "auth": auth_path,
    }
    app.dependency_overrides.clear()


def _session_for(env, id_client):
    """Ouvre une session pour un client donné, sans dépendre de son mot de passe :
    le compte d'accès est créé à la volée dans la base de test."""
    import bcrypt

    mot_de_passe = "MotDePasseTest!2026"
    banking_db.upsert_ebanking_user(
        id_utilisateur=f"EB-TEST-{id_client}",
        id_client=id_client,
        identifiant_connexion=f"test.{id_client.lower()}",
        mot_de_passe_hash=bcrypt.hashpw(mot_de_passe.encode(), bcrypt.gensalt()).decode(),
        db_path=env["db"],
    )
    reponse = env["client"].post(
        "/api/auth/login", json={"username": f"test.{id_client.lower()}", "password": mot_de_passe}
    )
    assert reponse.status_code == 200
    return {"Authorization": f"Bearer {reponse.json()['session_id']}"}


@pytest.fixture(scope="module")
def headers_a(env):
    return _session_for(env, CLIENT_A)


@pytest.fixture(scope="module")
def headers_b(env):
    return _session_for(env, CLIENT_B)


def _ask(env, message, headers=None):
    return env["client"].post("/api/chat", json={"message": message}, headers=headers or {}).json()


# Les six questions auparavant en échec, plus leurs équivalents multilingues.
LES_SIX = [
    "Mes paiements restaurant de ce mois-ci",
    "Ai-je reçu un paiement de 2000 MAD hier ?",
    "Quelles sommes sont entrées sur mon compte courant cette semaine ?",
    "Quelle est ma catégorie de dépense la plus importante ?",
    "werini akher 5 operations",
    "ch7al dkhel l compte courant had simana",
]


# ---------------------------------------------------------------------------
# 1. Sans authentification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", LES_SIX)
def test_unauthenticated_requires_login_and_never_reaches_faq(env, message):
    payload = _ask(env, message)
    assert payload["requires_auth"] is True
    assert payload["intent"] == "personal_data"
    # Jamais de réponse FAQ publique.
    assert "Aucune réponse" not in payload["response"]


# ---------------------------------------------------------------------------
# 2. Les six défauts, authentifiés — chacun vérifié contre le SQL
# ---------------------------------------------------------------------------


def test_1_card_payments_apply_category_and_period(env, headers_a):
    payload = _ask(env, "Mes paiements restaurant de ce mois-ci", headers_a)
    assert payload["requires_auth"] is False
    assert "Restaurants" in payload["response"]

    attendus = banking_db.get_transactions(
        CLIENT_A, transaction_type="card_payment", category="Restaurants",
        year_month=banking_db.DEMO_CURRENT_MONTH, db_path=env["db"],
    )
    # Chaque montant listé provient bien de la base.
    for tx in attendus[:3]:
        assert f"{tx['amount']:.2f}" in payload["response"] or str(tx["amount"]) in payload["response"]


def test_2_amount_direction_and_exact_date_are_applied(env, headers_a):
    payload = _ask(env, "Ai-je reçu un paiement de 2000 MAD hier ?", headers_a)
    assert payload["requires_auth"] is False
    # Les trois filtres sont rappelés dans la réponse.
    for filtre in ("entrées", "2026-07-27", "2000"):
        assert filtre in payload["response"]


def test_3_incoming_sums_route_to_transactions_not_balance(env, headers_a):
    payload = _ask(env, "Quelles sommes sont entrées sur mon compte courant cette semaine ?", headers_a)
    assert "entrées" in payload["response"]
    assert "compte courant" in payload["response"]
    # NE DOIT PAS être le solde total.
    total = banking_db.get_total_balance(CLIENT_A, db_path=env["db"])
    assert str(total) not in payload["response"]


def test_4_max_category_is_computed_from_the_database(env, headers_a):
    """Sans période exprimée, le calcul porte sur TOUT l'historique : aucune
    période n'est inventée (exigence « ne jamais inventer une information
    manquante »)."""
    payload = _ask(env, "Quelle est ma catégorie de dépense la plus importante ?", headers_a)
    repartition = banking_db.get_spending_breakdown(CLIENT_A, db_path=env["db"])
    assert repartition
    top_categorie, top_montant = repartition[0]
    assert top_categorie in payload["response"]
    assert f"{top_montant:.2f}" in payload["response"]


def test_4bis_max_category_honours_an_explicit_period(env, headers_a):
    """Avec une période exprimée, elle est appliquée — le résultat diffère."""
    payload = _ask(env, "Quelle catégorie ai-je le plus dépensé ce mois-ci ?", headers_a)
    repartition = banking_db.get_spending_breakdown(
        CLIENT_A, year_month=banking_db.DEMO_CURRENT_MONTH, db_path=env["db"]
    )
    assert repartition
    assert f"{repartition[0][1]:.2f}" in payload["response"]


def test_5_arabizi_werini_returns_five_latest(env, headers_a):
    payload = _ask(env, "werini akher 5 operations", headers_a)
    assert payload["requires_auth"] is False
    # Réponse localisée en Arabizi, jamais un message FAQ.
    assert "dyalek" in payload["response"]
    assert "ma3loumat mtwafra" not in payload["response"]


def test_6_arabizi_incoming_on_current_account_is_not_the_balance(env, headers_a):
    payload = _ask(env, "ch7al dkhel l compte courant had simana", headers_a)
    total = banking_db.get_total_balance(CLIENT_A, db_path=env["db"])
    assert str(total) not in payload["response"]
    assert "operations" in payload["response"].lower()


# ---------------------------------------------------------------------------
# 3. Les filtres changent réellement le résultat
# ---------------------------------------------------------------------------


def test_filters_actually_change_the_result(env, headers_a):
    tout = _ask(env, "Montre-moi mes dernières opérations", headers_a)["response"]
    filtre = _ask(env, "Montre-moi mes retraits", headers_a)["response"]
    assert tout != filtre


def test_limit_is_applied(env, headers_a):
    trois = _ask(env, "Montre-moi mes 3 dernières opérations", headers_a)["response"]
    dix = _ask(env, "Montre-moi mes 10 dernières opérations", headers_a)["response"]
    assert trois.count(" : ") < dix.count(" : ")


def test_period_changes_the_spending_total(env, headers_a):
    ce_mois = _ask(env, "Combien ai-je dépensé en restaurants ce mois-ci ?", headers_a)["response"]
    mois_dernier = _ask(env, "Combien ai-je dépensé en restaurants le mois dernier ?", headers_a)["response"]
    assert ce_mois != mois_dernier


# ---------------------------------------------------------------------------
# 4. Isolation entre deux clients authentifiés
# ---------------------------------------------------------------------------


def test_two_customers_receive_different_isolated_data(env, headers_a, headers_b):
    reponse_a = _ask(env, "Quel est mon solde ?", headers_a)["response"]
    reponse_b = _ask(env, "Quel est mon solde ?", headers_b)["response"]
    assert reponse_a != reponse_b

    total_a = banking_db.get_total_balance(CLIENT_A, db_path=env["db"])
    total_b = banking_db.get_total_balance(CLIENT_B, db_path=env["db"])
    assert str(total_a) in reponse_a and str(total_a) not in reponse_b
    assert str(total_b) in reponse_b and str(total_b) not in reponse_a


def test_transaction_search_is_isolated_between_customers(env, headers_a, headers_b):
    a = _ask(env, "Montre-moi mes 5 dernières opérations", headers_a)["response"]
    b = _ask(env, "Montre-moi mes 5 dernières opérations", headers_b)["response"]
    assert a != b


# ---------------------------------------------------------------------------
# 5. Résultat vide, Ollama indisponible, non-régression
# ---------------------------------------------------------------------------


def test_empty_result_is_explicit_and_not_an_error(env, headers_a):
    payload = _ask(env, "Ai-je reçu un paiement de 999999 MAD hier ?", headers_a)
    assert "Aucune opération ne correspond" in payload["response"]
    assert "Erreur" not in payload["response"]


@pytest.mark.parametrize("message", LES_SIX)
def test_works_with_ollama_unavailable(monkeypatch, env, headers_a, message):
    from agents.agent1_faq import llm_router

    monkeypatch.setattr(llm_router, "route_with_llm", lambda *a, **k: None)
    payload = _ask(env, message, headers_a)
    assert payload["requires_auth"] is False
    assert payload["response"]


@pytest.mark.parametrize(
    ("message", "attendu"),
    [
        ("Quel est mon solde ?", "total de vos comptes"),
        ("Combien ai-je dépensé ce mois-ci ?", "dépensé"),
    ],
)
def test_existing_intents_do_not_regress(env, headers_a, message, attendu):
    assert attendu in _ask(env, message, headers_a)["response"]


@pytest.mark.parametrize(
    "message",
    [
        "Comment fonctionne un virement bancaire ?",
        "Quel est le délai habituel d'exécution d'un virement ?",
        "Qu'est-ce qu'un RIB et à quoi sert-il ?",
    ],
)
def test_public_definition_questions_remain_faq(env, message):
    payload = _ask(env, message)
    assert payload["intent"] == "faq_generale"
    assert payload["requires_auth"] is False


@pytest.mark.parametrize("message", ["Je veux virer 500 dh", "Bloque ma carte"])
def test_sensitive_operations_remain_blocked(env, headers_a, message):
    payload = _ask(env, message, headers_a)
    assert payload["intent"] in ("virement", "compte_action")
    assert payload["response"] == "Ce service n'est pas disponible pour le moment."


def test_card_security_rules_unchanged(env, headers_a):
    payload = _ask(env, "Donne-moi mon numéro de carte complet", headers_a)
    assert "ne peut pas être affiché dans le chatbot" in payload["response"]


def test_amounts_keep_decimal_accuracy(env, headers_a):
    """Les montants affichés doivent correspondre EXACTEMENT aux `Decimal`
    stockés — aucune perte due à un passage par `float`."""
    total = banking_db.get_spending_total(
        CLIENT_A, category="Restaurants", year_month=banking_db.DEMO_LAST_MONTH, db_path=env["db"]
    )
    assert isinstance(total, Decimal)
    payload = _ask(env, "Combien ai-je dépensé en restaurants le mois dernier ?", headers_a)
    assert f"{total:.2f}" in payload["response"]
