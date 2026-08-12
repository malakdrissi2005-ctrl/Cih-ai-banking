"""Parcours de démonstration ACP/OCP de bout en bout, via le VRAI flux HTTP.

Rejoue ce que fera le frontend : `POST /api/auth/login` puis `POST /api/chat`
avec le jeton de session. Aucune fonction interne n'est appelée directement
pour le parcours utilisateur.

RAISON D'ÊTRE DE CE FICHIER — il a détecté un bug que les tests unitaires ne
pouvaient pas voir : `auth.py` et `chat.py` ne transmettaient jamais
`banking_db_path` à `session_manager`. Les tests unitaires le passaient
explicitement et passaient donc au vert, alors que l'API réelle renvoyait 401
sur un identifiant pourtant valide. Le câblage des dépendances FastAPI ne se
teste qu'en traversant réellement les routes.
"""
import re
import sqlite3

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
from agents.agent1_faq.rag import get_faq_collection
from scripts.ingest_faq import ingest_faq
from scripts.seed_demo_database import DEMO_EMAIL, DEMO_LOGIN, DEMO_PASSWORD

DEMO_CLIENT = "CL0001"
AUTRE_CLIENT = "CL0042"


@pytest.fixture(scope="module")
def demo_env(tmp_path_factory):
    """Environnement complet : base démo, auth isolée, FAQ ingérée, Mistral coupé."""
    root = tmp_path_factory.mktemp("e2e")
    banking_path = str(root / "demo_bancaire.db")
    auth_path = str(root / "auth.db")
    chroma_dir = str(root / "chroma")

    seed_demo_database(banking_path)
    session_manager.init_db(auth_path)
    ingest_faq(persist_dir=chroma_dir, collection_name="faq_e2e_test")
    collection = get_faq_collection(persist_dir=chroma_dir, collection_name="faq_e2e_test")

    app.dependency_overrides[get_auth_db_path] = lambda: auth_path
    app.dependency_overrides[get_banking_db_path] = lambda: banking_path
    app.dependency_overrides[get_banking_db_path_dependency] = lambda: banking_path
    app.dependency_overrides[get_faq_collection_dependency] = lambda: collection
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: False

    yield {"client": TestClient(app), "banking_path": banking_path}

    app.dependency_overrides.clear()


def seed_demo_database(path):
    from scripts.seed_demo_database import seed_demo_database as _seed

    _seed(db_path=path)


@pytest.fixture
def session_headers(demo_env):
    response = demo_env["client"].post(
        "/api/auth/login", json={"username": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['session_id']}"}


# ---------------------------------------------------------------------------
# 1. Login
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("login", [DEMO_EMAIL, DEMO_LOGIN])
def test_login_succeeds_over_http_with_email_and_identifier(demo_env, login):
    """NON-RÉGRESSION DU BUG DE CÂBLAGE : sans `banking_db_path` transmis par
    la route, ce test renvoie 401 alors que les identifiants sont valides."""
    response = demo_env["client"].post("/api/auth/login", json={"username": login, "password": DEMO_PASSWORD})
    assert response.status_code == 200
    assert response.json()["session_id"]


def test_login_rejects_a_wrong_password_over_http(demo_env):
    response = demo_env["client"].post(
        "/api/auth/login", json={"username": DEMO_EMAIL, "password": "MauvaisMdp!42"}
    )
    assert response.status_code == 401


def test_session_endpoint_returns_the_client_id(demo_env, session_headers):
    response = demo_env["client"].get("/api/auth/session", headers=session_headers)
    assert response.status_code == 200
    assert response.json()["user_id"] == DEMO_CLIENT


# ---------------------------------------------------------------------------
# 2-5. Questions bancaires
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "marqueurs"),
    [
        ("Quel est mon solde ?", ["MAD", "courant"]),
        ("Donne-moi mes dernières transactions", ["2026-07"]),
        ("Quelle est ma carte ?", ["carte"]),
        ("Qui sont mes bénéficiaires ?", ["••••"]),
    ],
)
def test_banking_questions_return_real_data_over_http(demo_env, session_headers, question, marqueurs):
    response = demo_env["client"].post("/api/chat", json={"message": question}, headers=session_headers)
    payload = response.json()
    assert payload["requires_auth"] is False
    for marqueur in marqueurs:
        assert marqueur.lower() in payload["response"].lower()


# ---------------------------------------------------------------------------
# 6. Numéro de carte complet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Donne-moi mon numéro de carte complet",
        "Quel est le numéro de ma carte ?",
        "Je veux les 16 chiffres de ma carte",
    ],
)
def test_card_number_request_is_refused_over_http(demo_env, session_headers, question):
    response = demo_env["client"].post("/api/chat", json={"message": question}, headers=session_headers)
    texte = response.json()["response"]
    # POLITIQUE ACTUELLE — le message de refus a été réécrit : il ne dit plus
    # « connectez-vous » à un utilisateur déjà authentifié, ne renvoie plus en
    # agence, ne promet plus « les derniers chiffres » (jamais renvoyés) et
    # n'affirme plus que le numéro complet est consultable ailleurs. Il ne
    # mentionne que l'onglet « Cartes » et les trois informations réellement
    # disponibles (statut, expiration, plafonds).
    assert "ne peut pas être affiché dans le chatbot" in texte
    assert "« Cartes »" in texte
    assert "agence" not in texte.lower()
    assert "connectez-vous" not in texte.lower()


# ---------------------------------------------------------------------------
# 7. Audit de sécurité sur les réponses réellement renvoyées
# ---------------------------------------------------------------------------


@pytest.fixture
def toutes_les_reponses(demo_env, session_headers):
    questions = [
        "Quel est mon solde ?",
        "Donne-moi mes dernières transactions",
        "Quelle est ma carte ?",
        "Qui sont mes bénéficiaires ?",
        "Combien ai-je dépensé ce mois-ci ?",
        "Donne-moi mon numéro de carte complet",
        "Quel est mon RIB ?",
        "Donne-moi mon IBAN",
    ]
    return "\n".join(
        demo_env["client"].post("/api/chat", json={"message": q}, headers=session_headers).json()["response"]
        for q in questions
    )


def test_no_password_or_hash_is_ever_returned(toutes_les_reponses):
    assert DEMO_PASSWORD not in toutes_les_reponses
    assert "$2b$" not in toutes_les_reponses


def test_no_sixteen_digit_card_number_is_ever_returned(demo_env, toutes_les_reponses):
    # Un numéro de compte CLIENT fait aussi 16 chiffres et est désormais
    # communiqué à son titulaire (politique propriétaire en vigueur). La règle
    # à vérifier est donc précise : aucun PAN de carte, jamais — pas « aucune
    # suite de 16 chiffres », qui interdirait une donnée légitime.
    with sqlite3.connect(demo_env["banking_path"]) as conn:
        numeros_de_compte = {
            ligne[0]
            for ligne in conn.execute(
                "SELECT numero_compte FROM COMPTE_BANCAIRE WHERE id_client = ?", (DEMO_CLIENT,)
            )
        }
    suites_interdites = [
        suite
        for suite in re.findall(r"\b\d{16}\b", toutes_les_reponses)
        if suite not in numeros_de_compte
    ]
    assert not suites_interdites


def test_card_number_and_internal_keys_are_never_returned(demo_env, toutes_les_reponses):
    """POLITIQUE ACTUELLE — distinction assumée :

    - le numéro de carte (même masqué) ne transite JAMAIS par le chatbot ;
    - les clés techniques internes (`id_compte`) non plus ;
    - le RIB et l'IBAN, en revanche, sont désormais communiqués à leur
      propriétaire authentifié : ce sont ses propres coordonnées.
    """
    with sqlite3.connect(demo_env["banking_path"]) as conn:
        masque = conn.execute(
            "SELECT numero_carte_masque FROM CARTE_BANCAIRE ca "
            "JOIN COMPTE_BANCAIRE co ON co.id_compte = ca.id_compte WHERE co.id_client = ?",
            (DEMO_CLIENT,),
        ).fetchone()[0]
        cles_internes = [
            ligne[0]
            for ligne in conn.execute(
                "SELECT id_compte FROM COMPTE_BANCAIRE WHERE id_client = ?", (DEMO_CLIENT,)
            )
        ]

    assert masque not in toutes_les_reponses
    for id_compte in cles_internes:
        assert id_compte not in toutes_les_reponses


def test_no_other_client_data_leaks(demo_env, toutes_les_reponses):
    autre = banking_db.get_total_balance(AUTRE_CLIENT, db_path=demo_env["banking_path"])
    assert str(autre) not in toutes_les_reponses


def test_anonymous_request_requires_login_and_leaks_nothing(demo_env):
    mien = banking_db.get_total_balance(DEMO_CLIENT, db_path=demo_env["banking_path"])
    response = demo_env["client"].post("/api/chat", json={"message": "Quel est mon solde ?"})
    payload = response.json()
    assert payload["requires_auth"] is True
    assert str(mien) not in payload["response"]


def test_forged_session_token_leaks_nothing(demo_env):
    mien = banking_db.get_total_balance(DEMO_CLIENT, db_path=demo_env["banking_path"])
    response = demo_env["client"].post(
        "/api/chat", json={"message": "Quel est mon solde ?"},
        headers={"Authorization": "Bearer jeton-invente"},
    )
    assert str(mien) not in response.json()["response"]


def test_logout_revokes_access_to_personal_data(demo_env):
    client = demo_env["client"]
    login = client.post("/api/auth/login", json={"username": DEMO_EMAIL, "password": DEMO_PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['session_id']}"}

    avant = client.post("/api/chat", json={"message": "Quel est mon solde ?"}, headers=headers).json()
    assert avant["requires_auth"] is False

    client.post("/api/auth/logout", headers=headers)

    apres = client.post("/api/chat", json={"message": "Quel est mon solde ?"}, headers=headers).json()
    mien = banking_db.get_total_balance(DEMO_CLIENT, db_path=demo_env["banking_path"])
    assert str(mien) not in apres["response"]
