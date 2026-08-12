"""Cohérence dashboard ↔ chatbot — source de vérité UNIQUE.

CONTEXTE DU BUG : après connexion, le dashboard affichait 15 420,50 MAD et la
référence « DEMO-****-4821 » (codées en dur dans
`frontend/src/data/mockAccount.js`) tandis que le chatbot annonçait
106 318,39 MAD lus dans `demo_bancaire.db`. Ce n'était pas un problème de
bases divergentes : le frontend n'avait AUCUN endpoint bancaire à interroger.

`GET /api/banking/overview` corrige cela en donnant au dashboard la même
source que le chatbot. Ces tests prouvent que les deux ne peuvent plus se
contredire, avec DEUX clients distincts.
"""
import re
import sqlite3
from decimal import Decimal

import bcrypt
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
MOT_DE_PASSE = "MotDePasseTest!2026"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    from agents.agent1_faq.rag import get_faq_collection
    from scripts.ingest_faq import ingest_faq
    from scripts.seed_demo_database import seed_demo_database

    root = tmp_path_factory.mktemp("coherence")
    banking_path = str(root / "demo_bancaire.db")
    auth_path = str(root / "auth.db")
    chroma_dir = str(root / "chroma")

    seed_demo_database(db_path=banking_path)
    session_manager.init_db(auth_path)
    ingest_faq(persist_dir=chroma_dir, collection_name="faq_coherence_test")
    collection = get_faq_collection(persist_dir=chroma_dir, collection_name="faq_coherence_test")

    app.dependency_overrides[get_auth_db_path] = lambda: auth_path
    app.dependency_overrides[get_banking_db_path] = lambda: banking_path
    app.dependency_overrides[get_banking_db_path_dependency] = lambda: banking_path
    app.dependency_overrides[get_faq_collection_dependency] = lambda: collection
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: False

    yield {"client": TestClient(app, raise_server_exceptions=False), "db": banking_path}
    app.dependency_overrides.clear()


def _headers(env, id_client):
    banking_db.upsert_ebanking_user(
        id_utilisateur=f"EB-COH-{id_client}",
        id_client=id_client,
        identifiant_connexion=f"coh.{id_client.lower()}",
        mot_de_passe_hash=bcrypt.hashpw(MOT_DE_PASSE.encode(), bcrypt.gensalt()).decode(),
        db_path=env["db"],
    )
    reponse = env["client"].post(
        "/api/auth/login", json={"username": f"coh.{id_client.lower()}", "password": MOT_DE_PASSE}
    )
    assert reponse.status_code == 200
    return {"Authorization": f"Bearer {reponse.json()['session_id']}"}


@pytest.fixture(scope="module")
def h_a(env):
    return _headers(env, CLIENT_A)


@pytest.fixture(scope="module")
def h_b(env):
    return _headers(env, CLIENT_B)


def _sql(env, requete, params=()):
    with sqlite3.connect(env["db"]) as conn:
        return conn.execute(requete, params).fetchall()


# ---------------------------------------------------------------------------
# 1. Authentification obligatoire
# ---------------------------------------------------------------------------


def test_overview_requires_a_session(env):
    assert env["client"].get("/api/banking/overview").status_code == 401


def test_overview_rejects_a_forged_token(env):
    reponse = env["client"].get(
        "/api/banking/overview", headers={"Authorization": "Bearer jeton-invente"}
    )
    assert reponse.status_code == 401


# ---------------------------------------------------------------------------
# 2. Le dashboard renvoie les données du BON client
# ---------------------------------------------------------------------------


def test_overview_returns_the_authenticated_customer(env, h_a):
    data = env["client"].get("/api/banking/overview", headers=h_a).json()
    assert data["customer_id"] == CLIENT_A


def test_overview_accounts_match_sql(env, h_a):
    data = env["client"].get("/api/banking/overview", headers=h_a).json()
    lignes = _sql(
        env,
        "SELECT type_compte, solde_disponible, rib, iban FROM COMPTE_BANCAIRE WHERE id_client = ?",
        (CLIENT_A,),
    )
    assert len(data["accounts"]) == len(lignes)
    # Appariement par RIB (unique), et non par type : un client peut posséder
    # plusieurs comptes du même type — CL0001 a deux carnets.
    par_rib = {c["rib"]: c for c in data["accounts"]}
    for type_compte, solde, rib, iban in lignes:
        assert par_rib[rib]["balance"] == solde
        assert par_rib[rib]["iban"] == iban
        assert par_rib[rib]["account_type"] == type_compte


# ---------------------------------------------------------------------------
# 3. LE test central : dashboard et chatbot ne peuvent plus se contredire
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("id_client", [CLIENT_A, CLIENT_B])
def test_dashboard_total_equals_chatbot_total(env, request, id_client):
    headers = _headers(env, id_client)
    dashboard = env["client"].get("/api/banking/overview", headers=headers).json()
    chatbot = env["client"].post(
        "/api/chat", json={"message": "Quel est mon solde ?"}, headers=headers
    ).json()

    total_sql = banking_db.get_total_balance(id_client, db_path=env["db"])
    assert dashboard["total_balance"] == str(total_sql)
    assert str(total_sql) in chatbot["response"]


def test_dashboard_and_chatbot_agree_on_the_number_of_accounts(env, h_a):
    dashboard = env["client"].get("/api/banking/overview", headers=h_a).json()
    nb_sql = len(_sql(env, "SELECT 1 FROM COMPTE_BANCAIRE WHERE id_client = ?", (CLIENT_A,)))
    assert len(dashboard["accounts"]) == nb_sql

    chatbot = env["client"].post(
        "/api/chat", json={"message": "Quel est mon solde ?"}, headers=h_a
    ).json()["response"]
    # Chaque solde de compte annoncé par le dashboard figure dans la réponse
    # du chatbot : les deux décrivent la même réalité.
    for compte in dashboard["accounts"]:
        assert compte["balance"] in chatbot


def test_recent_transactions_match_between_dashboard_and_sql(env, h_a):
    dashboard = env["client"].get("/api/banking/overview", headers=h_a).json()
    attendues = banking_db.get_transactions(CLIENT_A, limit=5, db_path=env["db"])
    assert len(dashboard["recent_transactions"]) == len(attendues)
    for renvoyee, attendue in zip(dashboard["recent_transactions"], attendues):
        assert renvoyee["date"] == attendue["transaction_date"]
        assert renvoyee["amount"] == str(attendue["amount"])


# ---------------------------------------------------------------------------
# 4. RIB / IBAN complets pour le propriétaire authentifié
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Quel est mon RIB ?",
        "Donne-moi mon IBAN",
        "Je veux mon RIB complet",
        "chno howa rib dyali",
        "3tini iban dyali",
        "بغيت الريب ديالي",
    ],
)
def test_chatbot_returns_the_exact_rib_and_iban_after_login(env, h_a, question):
    """Le RIB et l'IBAN du propriétaire authentifié sont renvoyés en CLAIR — ce
    sont ses propres coordonnées, communiquées pour recevoir un virement.

    RÉPONSE DEVENUE CIBLÉE : la question porte sur UN identifiant, et c'est ce
    seul identifiant du COMPTE COURANT qui est renvoyé. On vérifie donc que la
    valeur attendue est celle de la base, plutôt que d'exiger la présence
    simultanée du RIB et de l'IBAN comme dans l'ancienne réponse-catalogue.
    """
    reponse = env["client"].post(
        "/api/chat", json={"message": question}, headers=h_a
    ).json()["response"]

    lignes = _sql(
        env,
        "SELECT rib, iban FROM COMPTE_BANCAIRE WHERE id_client = ? AND type_compte = 'courant'",
        (CLIENT_A,),
    )
    assert lignes
    rib, iban = lignes[0]
    attendu = iban if "iban" in question.lower() or "الايبان" in question else rib
    assert attendu in reponse, reponse


def test_rib_request_for_a_specific_account_type(env, h_a):
    reponse = env["client"].post(
        "/api/chat", json={"message": "RIB de mon compte courant"}, headers=h_a
    ).json()["response"]
    courant = _sql(
        env, "SELECT rib FROM COMPTE_BANCAIRE WHERE id_client = ? AND type_compte = 'courant'", (CLIENT_A,)
    )
    assert courant[0][0] in reponse


@pytest.mark.parametrize("question", ["Quel est mon RIB ?", "Donne-moi mon IBAN"])
def test_rib_requires_authentication(env, question):
    payload = env["client"].post("/api/chat", json={"message": question}).json()
    assert payload["requires_auth"] is True
    lignes = _sql(env, "SELECT rib FROM COMPTE_BANCAIRE WHERE id_client = ?", (CLIENT_A,))
    assert lignes[0][0] not in payload["response"]


# ---------------------------------------------------------------------------
# 5. Interdits absolus
# ---------------------------------------------------------------------------


def test_internal_primary_keys_are_never_exposed(env, h_a):
    """`id_compte` est une clé technique : ni le dashboard ni le chatbot ne
    doivent la divulguer."""
    dashboard = env["client"].get("/api/banking/overview", headers=h_a).json()
    identifiants_internes = [
        ligne[0] for ligne in _sql(env, "SELECT id_compte FROM COMPTE_BANCAIRE WHERE id_client = ?", (CLIENT_A,))
    ]
    corps = str(dashboard)
    for id_compte in identifiants_internes:
        assert id_compte not in corps

    reponse = env["client"].post(
        "/api/chat", json={"message": "Quel est mon RIB ?"}, headers=h_a
    ).json()["response"]
    for id_compte in identifiants_internes:
        assert id_compte not in reponse


def test_card_pan_and_secrets_remain_protected(env, h_a):
    dashboard = env["client"].get("/api/banking/overview", headers=h_a).json()
    corps = str(dashboard)
    assert "$2b$" not in corps

    # Le numéro de compte client fait 16 chiffres et est LÉGITIMEMENT exposé :
    # on l'exclut avant de chercher un PAN de carte résiduel.
    numeros_de_compte = {c["account_number"] for c in dashboard["accounts"]}
    suspects = [
        suite for suite in re.findall(r"\b\d{16}\b", corps) if suite not in numeros_de_compte
    ]
    assert not suspects, f"suite de 16 chiffres non identifiée : {suspects}"

    if dashboard["card"]:
        assert "XXXXXX" in dashboard["card"]["masked_card_number"]

    reponse = env["client"].post(
        "/api/chat", json={"message": "Donne-moi mon numéro de carte complet"}, headers=h_a
    ).json()["response"]
    assert "ne peut pas être affiché dans le chatbot" in reponse


# ---------------------------------------------------------------------------
# 6. Isolation entre deux clients
# ---------------------------------------------------------------------------


def test_customer_a_never_receives_customer_b_data(env, h_a, h_b):
    a = env["client"].get("/api/banking/overview", headers=h_a).json()
    b = env["client"].get("/api/banking/overview", headers=h_b).json()

    assert a["customer_id"] != b["customer_id"]
    assert a["total_balance"] != b["total_balance"]

    ribs_b = {c["rib"] for c in b["accounts"]}
    corps_a = str(a)
    for rib in ribs_b:
        assert rib not in corps_a


# ---------------------------------------------------------------------------
# 7. Robustesse et non-régression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Quel est mon solde ?",
        "Combien ai-je sur mon compte ?",
        "Je veux savoir combien j'ai dans mon compte",
        "ch7al 3ndi f l7sab",
        "شحال عندي فالحساب",
    ],
)
def test_balance_questions_agree_across_languages_and_wordings(env, h_a, question):
    """Toutes ces formulations doivent renvoyer LE MÊME total — et jamais être
    volées par les identifiants de compte ou la FAQ."""
    payload = env["client"].post("/api/chat", json={"message": question}, headers=h_a).json()
    total = banking_db.get_total_balance(CLIENT_A, db_path=env["db"])
    assert str(total) in payload["response"]


def test_works_with_ollama_unavailable(monkeypatch, env, h_a):
    from agents.agent1_faq import llm_router

    monkeypatch.setattr(llm_router, "route_with_llm", lambda *a, **k: None)
    dashboard = env["client"].get("/api/banking/overview", headers=h_a).json()
    chatbot = env["client"].post(
        "/api/chat", json={"message": "Quel est mon solde ?"}, headers=h_a
    ).json()
    assert dashboard["total_balance"] in chatbot["response"]


def test_amounts_are_decimal_strings_never_floats(env, h_a):
    dashboard = env["client"].get("/api/banking/overview", headers=h_a).json()
    assert isinstance(dashboard["total_balance"], str)
    for compte in dashboard["accounts"]:
        assert isinstance(compte["balance"], str)
        Decimal(compte["balance"])  # doit être parsable sans perte
