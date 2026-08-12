"""Identifiants bancaires personnels — RIB, IBAN, numéro de compte.

NON-RÉGRESSION D'UN BUG RÉEL : « chnahowa rib dyalti » (Arabizi) était classé
`faq_generale` et la recherche RAG renvoyait une réponse publique sans rapport
(délai d'exécution d'un virement). Trois défauts se cumulaient :

1. `rib`, `iban` et « numéro de compte » n'étaient dans AUCUN pattern
   personnel — ni en français ;
2. `dyalti` et `chnahowa` n'étaient pas des marqueurs de darija latine, donc
   le message était détecté « fr » et jamais normalisé ;
3. aucune sous-intention n'existait pour ces champs, pourtant présents dans
   `COMPTE_BANCAIRE` (`numero_compte`, `rib`, `iban`).

Couverture systématique des trois langues, en n'utilisant JAMAIS le chemin
Mistral (`use_llm_router=False`).
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from agents.agent1_faq.banking_answers import classify_personal_intent
from agents.agent1_faq.classification import classify_intent
from agents.agent1_faq.darija_normalization import normalize_darija_message
from agents.agent1_faq.language_detection import detect_language
from app.banking import banking_db
from app.main import app
from app.routers.auth import get_auth_db_path, get_banking_db_path
from app.routers.chat import (
    get_banking_db_path_dependency,
    get_faq_collection_dependency,
    get_use_llm_router_dependency,
)
from app.security import session_manager

DEMO_CLIENT = "CL0001"
AUTRE_CLIENT = "CL0042"

# Les formulations exigées, dans les trois langues.
DEMANDES_IDENTIFIANTS = [
    # --- Français ---
    "Quel est mon RIB ?",
    "Donne-moi mon IBAN",
    "Mon numéro de compte",
    "Quel est le numéro de mon compte ?",
    "Je veux mes coordonnées bancaires",
    # --- Arabizi / darija latine ---
    "chnahowa rib dyalti",
    "3tini rib dyali",
    "bghit iban dyali",
    "numero compte dyali",
    # --- Darija en écriture arabe ---
    "بغيت الريب ديالي",
    "عطيني رقم الحساب ديالي",
    "شنو هو الإيبان ديالي",
]


def _resolve(message: str) -> tuple[str, str]:
    """Bucket et sous-intention obtenus par le seul chemin déterministe."""
    normalized = message if detect_language(message) == "fr" else normalize_darija_message(message)
    bucket = classify_intent(normalized)
    if bucket != "personal_data":
        return bucket, "-"
    return bucket, classify_personal_intent(normalized)["intent"]


# ---------------------------------------------------------------------------
# 1. Classification : personnel AVANT toute recherche FAQ/RAG
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", DEMANDES_IDENTIFIANTS)
def test_identifier_requests_are_classified_personal_never_faq(message):
    bucket, _ = _resolve(message)
    assert bucket == "personal_data", f"{message!r} ne doit jamais partir en recherche FAQ"


@pytest.mark.parametrize("message", DEMANDES_IDENTIFIANTS)
def test_identifier_requests_resolve_to_the_dedicated_intent(message):
    _, intent = _resolve(message)
    assert intent == "account_identifiers"


@pytest.mark.parametrize(
    ("message", "expected_language"),
    [
        ("chnahowa rib dyalti", "darija_latn"),
        ("3tini rib dyali", "darija_latn"),
        ("بغيت الريب ديالي", "darija_ar"),
        # `rib`/`iban` ne sont PAS des marqueurs darija : une question
        # française doit rester française, sous peine de recevoir une réponse
        # en darija.
        ("Quel est mon RIB ?", "fr"),
        ("Donne-moi mon IBAN", "fr"),
    ],
)
def test_language_detection_is_correct_for_identifier_requests(message, expected_language):
    assert detect_language(message) == expected_language


# ---------------------------------------------------------------------------
# 2. Priorité : un mot générique ne doit pas voler une demande précise
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        # « bénéficiaire » reste prioritaire : c'est SON rib qui est demandé.
        ("Quel est le RIB de mon bénéficiaire ?", "beneficiaries"),
        # « compte » générique ne doit pas capturer une demande de RIB.
        ("Quel est le RIB de mon compte ?", "account_identifiers"),
        # Les intentions existantes ne doivent pas être volées par les
        # nouveaux patterns.
        ("Quel est mon solde ?", "total_balance"),
        ("Montre-moi mes dernières opérations", "recent_transactions"),
        ("Quel est le statut de ma carte ?", "card_information"),
        ("Combien ai-je dépensé en restaurants ?", "spending_by_category"),
        ("Quel est mon dernier prélèvement ?", "last_direct_debit"),
        ("Ai-je reçu mon salaire ?", "salary"),
    ],
)
def test_precise_intents_keep_priority(message, expected_intent):
    assert classify_personal_intent(message)["intent"] == expected_intent


def test_public_faq_about_rib_is_not_hijacked():
    """« Qu'est-ce qu'un RIB ? » porte sur un CONCEPT : elle doit rester
    publique. Protégée par le garde définitionnel (aucun possessif)."""
    assert classify_intent("Qu'est-ce qu'un RIB et à quoi sert-il ?") == "faq_generale"
    assert classify_intent("Comment obtenir un RIB ?") == "faq_generale"


# ---------------------------------------------------------------------------
# 3. Lecture en base : masquage et isolation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_db(tmp_path_factory):
    from scripts.seed_demo_database import seed_demo_database

    path = str(tmp_path_factory.mktemp("ident") / "demo_bancaire.db")
    seed_demo_database(db_path=path)
    return path


def test_identifiers_are_returned_in_full_to_their_owner(demo_db):
    """POLITIQUE ACTUELLE : le RIB et l'IBAN du propriétaire authentifié sont
    renvoyés en CLAIR. Ce ne sont pas des secrets — un client les communique
    pour recevoir un virement. Seule la clé technique `id_compte` est
    interdite."""
    comptes = banking_db.get_account_identifiers_for_customer(DEMO_CLIENT, db_path=demo_db)
    assert comptes

    with sqlite3.connect(demo_db) as conn:
        bruts = conn.execute(
            "SELECT rib, iban, numero_compte, id_compte FROM COMPTE_BANCAIRE WHERE id_client = ?",
            (DEMO_CLIENT,),
        ).fetchall()

    ribs = {c["rib"] for c in comptes}
    ibans = {c["iban"] for c in comptes}
    corps = str(comptes)
    for rib, iban, numero, id_compte in bruts:
        assert rib in ribs
        assert iban in ibans
        # La clé primaire interne n'est JAMAIS exposée.
        assert id_compte not in corps


def test_identifiers_are_isolated_between_customers(demo_db):
    miens = banking_db.get_account_identifiers_for_customer(DEMO_CLIENT, db_path=demo_db)
    autres = banking_db.get_account_identifiers_for_customer(AUTRE_CLIENT, db_path=demo_db)
    assert miens and autres
    # Comparaison par RIB : `account_id` n'est volontairement plus exposé.
    assert {c["rib"] for c in miens}.isdisjoint({c["rib"] for c in autres})


def test_unknown_customer_reads_nothing(demo_db):
    assert banking_db.get_account_identifiers_for_customer("CL9999", db_path=demo_db) == []


# ---------------------------------------------------------------------------
# 4. Bout en bout HTTP — avant et après authentification
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def http_env(tmp_path_factory, demo_db):
    from agents.agent1_faq.rag import get_faq_collection
    from scripts.ingest_faq import ingest_faq

    root = tmp_path_factory.mktemp("ident_http")
    auth_path = str(root / "auth.db")
    chroma_dir = str(root / "chroma")

    session_manager.init_db(auth_path)
    ingest_faq(persist_dir=chroma_dir, collection_name="faq_identifiers_test")
    collection = get_faq_collection(persist_dir=chroma_dir, collection_name="faq_identifiers_test")

    app.dependency_overrides[get_auth_db_path] = lambda: auth_path
    app.dependency_overrides[get_banking_db_path] = lambda: demo_db
    app.dependency_overrides[get_banking_db_path_dependency] = lambda: demo_db
    app.dependency_overrides[get_faq_collection_dependency] = lambda: collection
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: False

    yield {"client": TestClient(app, raise_server_exceptions=False), "db": demo_db}
    app.dependency_overrides.clear()


@pytest.fixture
def session_headers(http_env):
    from scripts.seed_demo_database import DEMO_EMAIL, DEMO_PASSWORD

    response = http_env["client"].post(
        "/api/auth/login", json={"username": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['session_id']}"}


@pytest.mark.parametrize("message", DEMANDES_IDENTIFIANTS)
def test_unauthenticated_identifier_request_requires_login(http_env, message):
    """LE bug d'origine : sans session, ces demandes recevaient une réponse
    FAQ publique. Elles doivent exiger une connexion."""
    payload = http_env["client"].post("/api/chat", json={"message": message}).json()
    assert payload["intent"] == "personal_data"
    assert payload["requires_auth"] is True
    # Aucune bribe de la FAQ publique sur les virements.
    assert "délai" not in payload["response"].lower()


@pytest.mark.parametrize("message", DEMANDES_IDENTIFIANTS)
def test_authenticated_identifier_request_returns_real_data(http_env, session_headers, message):
    payload = http_env["client"].post(
        "/api/chat", json={"message": message}, headers=session_headers
    ).json()
    assert payload["requires_auth"] is False
    # La réponse renvoie l'identifiant RÉELLEMENT demandé (RIB, IBAN ou numéro
    # de compte) — plus l'empilement des trois. On vérifie donc qu'une valeur
    # authentique du compte courant est présente.
    with sqlite3.connect(http_env["db"]) as conn:
        courant = conn.execute(
            "SELECT rib, iban, numero_compte FROM COMPTE_BANCAIRE "
            "WHERE id_client = ? AND type_compte = 'courant'",
            (DEMO_CLIENT,),
        ).fetchone()
    assert any(valeur in payload["response"] for valeur in courant), payload["response"]


@pytest.mark.parametrize("message", DEMANDES_IDENTIFIANTS)
def test_full_rib_and_iban_are_returned_to_their_owner(http_env, session_headers, message):
    """Les valeurs renvoyées correspondent EXACTEMENT à une requête SQL
    indépendante.

    RÉPONSE DÉSORMAIS CONCISE : la question porte sur UN identifiant d'UN
    compte, et c'est ce seul identifiant qui est renvoyé. Le test vérifie donc
    qu'au moins un identifiant réel du compte courant est présent, plutôt que
    l'ancien empilement RIB + IBAN + numéro de compte de tous les comptes.
    """
    with sqlite3.connect(http_env["db"]) as conn:
        courant = conn.execute(
            "SELECT rib, iban, numero_compte FROM COMPTE_BANCAIRE "
            "WHERE id_client = ? AND type_compte = 'courant'",
            (DEMO_CLIENT,),
        ).fetchone()
        cles_internes = [
            ligne[0]
            for ligne in conn.execute(
                "SELECT id_compte FROM COMPTE_BANCAIRE WHERE id_client = ?", (DEMO_CLIENT,)
            )
        ]

    reponse = http_env["client"].post(
        "/api/chat", json={"message": message}, headers=session_headers
    ).json()["response"]

    assert any(valeur in reponse for valeur in courant), reponse
    # La clé technique interne reste interdite, quelle que soit la question.
    for id_compte in cles_internes:
        assert id_compte not in reponse


def test_answer_is_localized_in_the_original_language(http_env, session_headers):
    client = http_env["client"]

    francais = client.post("/api/chat", json={"message": "Quel est mon RIB ?"}, headers=session_headers).json()
    assert "Le RIB de votre compte courant" in francais["response"]

    arabizi = client.post("/api/chat", json={"message": "chnahowa rib dyalti"}, headers=session_headers).json()
    assert "dyal compte courant" in arabizi["response"]

    arabe = client.post("/api/chat", json={"message": "بغيت الريب ديالي"}, headers=session_headers).json()
    assert "الحساب الجاري" in arabe["response"]


def test_no_other_customer_data_leaks(http_env, session_headers):
    with sqlite3.connect(http_env["db"]) as conn:
        rib_autre = conn.execute(
            "SELECT rib FROM COMPTE_BANCAIRE WHERE id_client = ? LIMIT 1", (AUTRE_CLIENT,)
        ).fetchone()[0]

    reponse = http_env["client"].post(
        "/api/chat", json={"message": "Quel est mon RIB ?"}, headers=session_headers
    ).json()["response"]
    assert rib_autre not in reponse
    # La réponse concise ne cite plus de référence masquée : elle donne le RIB
    # du compte courant, et rien d'autre. On vérifie donc la valeur elle-même.
    with sqlite3.connect(http_env["db"]) as conn:
        rib_courant = conn.execute(
            "SELECT rib FROM COMPTE_BANCAIRE WHERE id_client = ? AND type_compte = 'courant'",
            (DEMO_CLIENT,),
        ).fetchone()[0]
    assert rib_courant in reponse


def test_secrets_remain_protected(http_env, session_headers):
    """Ni PAN complet, ni hash, ni mot de passe dans une réponse d'identifiants."""
    import re

    from scripts.seed_demo_database import DEMO_PASSWORD

    reponse = http_env["client"].post(
        "/api/chat", json={"message": "Quel est mon RIB ?"}, headers=session_headers
    ).json()["response"]

    assert DEMO_PASSWORD not in reponse
    assert "$2b$" not in reponse

    # Le numéro de compte CLIENT (16 chiffres) est désormais communiqué à son
    # titulaire, au même titre que le RIB qui le contient déjà. L'assertion
    # porte donc précisément sur ce qui reste interdit — un PAN de carte —
    # et non sur « toute suite de 16 chiffres ».
    import sqlite3

    with sqlite3.connect(http_env["db"]) as conn:
        numeros_de_compte = {
            ligne[0]
            for ligne in conn.execute(
                "SELECT numero_compte FROM COMPTE_BANCAIRE WHERE id_client = ?", (DEMO_CLIENT,)
            )
        }
    assert not [
        suite for suite in re.findall(r"\b\d{16}\b", reponse) if suite not in numeros_de_compte
    ]


def test_public_faq_still_works(http_env):
    payload = http_env["client"].post(
        "/api/chat", json={"message": "Quels documents pour ouvrir un compte ?"}
    ).json()
    assert payload["intent"] == "faq_generale"
    assert payload["requires_auth"] is False


@pytest.mark.parametrize("message", ["Je veux virer 500 dh", "Bloque ma carte"])
def test_sensitive_operations_remain_blocked(http_env, session_headers, message):
    payload = http_env["client"].post(
        "/api/chat", json={"message": message}, headers=session_headers
    ).json()
    assert payload["intent"] in ("virement", "compte_action")
    assert payload["response"] == "Ce service n'est pas disponible pour le moment."


@pytest.mark.parametrize("message", ["Quel est mon RIB ?", "chnahowa rib dyalti"])
def test_works_with_ollama_unavailable(monkeypatch, http_env, session_headers, message):
    """Repli déterministe : `route_with_llm` renvoie `None` quand Ollama est
    injoignable — la réponse doit rester correcte."""
    from agents.agent1_faq import llm_router

    monkeypatch.setattr(llm_router, "route_with_llm", lambda *a, **k: None)
    payload = http_env["client"].post(
        "/api/chat", json={"message": message}, headers=session_headers
    ).json()
    assert payload["requires_auth"] is False
    # Réponse concise : le RIB réel du compte courant, sans référence masquée.
    with sqlite3.connect(http_env["db"]) as conn:
        rib_courant = conn.execute(
            "SELECT rib FROM COMPTE_BANCAIRE WHERE id_client = ? AND type_compte = 'courant'",
            (DEMO_CLIENT,),
        ).fetchone()[0]
    assert rib_courant in payload["response"]
