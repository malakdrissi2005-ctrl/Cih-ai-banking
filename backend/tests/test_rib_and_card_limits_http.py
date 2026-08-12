"""RIB ciblé et plafonds de carte — via le VRAI flux HTTP `POST /api/chat`.

DEUX DÉFAUTS CORRIGÉS, DEUX CAUSES DISTINCTES :

1. RIB — la réponse listait les TROIS comptes avec RIB, IBAN et numéro de
   compte, plus un paragraphe de sécurité. Elle répondait à des questions que
   l'utilisateur n'avait pas posées et noyait la seule valeur utile. Le compte
   courant est désormais le défaut, et un seul compte est renvoyé à la fois.

2. PLAFONDS DE CARTE — « Quels sont les plafonds de ma carte ? » répondait
   « Votre carte est active. » CONFLIT DE PRIORITÉ : Mistral ne distingue pas
   les facettes d'une carte, `llm_router.to_personal_intent` traduit donc son
   `card_query` en `requested_fields = ["status"]`, et cette sortie primait sur
   la détection déterministe — qui avait pourtant parfaitement reconnu les deux
   plafonds. S'y ajoutaient des trous de vocabulaire : « limites », « combien
   puis-je payer/retirer » et toutes les formes darija n'étaient pas reconnues.

Chaque valeur affirmée ici est comparée à une requête SQL indépendante.
"""
import sqlite3
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

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
from scripts.seed_demo_database import DEMO_PASSWORD, FIXTURE_PASSWORD

CLIENT_DEMO = "CL0001"
AUTRE_CLIENT = "CL0042"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    racine = tmp_path_factory.mktemp("rib_cartes")
    chemin_bancaire = str(racine / "demo_bancaire.db")
    chemin_auth = str(racine / "auth.db")
    dossier_chroma = str(racine / "chroma")

    from scripts.seed_demo_database import seed_demo_database

    seed_demo_database(db_path=chemin_bancaire)
    session_manager.init_db(chemin_auth)
    ingest_faq(persist_dir=dossier_chroma, collection_name="faq_rib_cartes")
    collection = get_faq_collection(
        persist_dir=dossier_chroma, collection_name="faq_rib_cartes"
    )

    app.dependency_overrides[get_auth_db_path] = lambda: chemin_auth
    app.dependency_overrides[get_banking_db_path] = lambda: chemin_bancaire
    app.dependency_overrides[get_banking_db_path_dependency] = lambda: chemin_bancaire
    app.dependency_overrides[get_faq_collection_dependency] = lambda: collection
    # Mistral coupé par défaut : la voie déterministe doit suffire.
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: False

    yield {"client": TestClient(app), "banking_path": chemin_bancaire}

    app.dependency_overrides.clear()


def _connexion(env, id_client=CLIENT_DEMO):
    with sqlite3.connect(env["banking_path"]) as c:
        login = c.execute(
            "SELECT identifiant_connexion FROM UTILISATEUR_E_BANKING WHERE id_client = ?",
            (id_client,),
        ).fetchone()[0]
    mot_de_passe = DEMO_PASSWORD if id_client == CLIENT_DEMO else FIXTURE_PASSWORD
    reponse = env["client"].post(
        "/api/auth/login", json={"username": login, "password": mot_de_passe}
    )
    assert reponse.status_code == 200, reponse.text
    return {"Authorization": f"Bearer {reponse.json()['session_id']}"}


@pytest.fixture
def entetes(env):
    return _connexion(env)


def _demander(env, message, entetes=None):
    reponse = env["client"].post(
        "/api/chat", json={"message": message}, headers=entetes or {}
    )
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


# --- Vérité SQL indépendante -----------------------------------------------


def _comptes(env, id_client=CLIENT_DEMO, type_compte=None):
    requete = (
        "SELECT type_compte, rib, iban, numero_compte, numero_compte_masque "
        "FROM COMPTE_BANCAIRE WHERE id_client = ?"
    )
    parametres = [id_client]
    if type_compte:
        requete += " AND type_compte = ?"
        parametres.append(type_compte)
    requete += " ORDER BY id_compte"
    with sqlite3.connect(env["banking_path"]) as c:
        c.row_factory = sqlite3.Row
        return [dict(ligne) for ligne in c.execute(requete, parametres)]


def _courant(env, id_client=CLIENT_DEMO):
    return _comptes(env, id_client, "courant")[0]


def _carte(env, id_client=CLIENT_DEMO):
    with sqlite3.connect(env["banking_path"]) as c:
        c.row_factory = sqlite3.Row
        ligne = c.execute(
            "SELECT ca.statut_carte, ca.plafond_paiement, ca.plafond_retrait "
            "FROM CARTE_BANCAIRE ca JOIN COMPTE_BANCAIRE co ON co.id_compte = ca.id_compte "
            "WHERE co.id_client = ?",
            (id_client,),
        ).fetchone()
    return {
        "statut": ligne["statut_carte"],
        "paiement": Decimal(ligne["plafond_paiement"]),
        "retrait": Decimal(ligne["plafond_retrait"]),
    }


def _montant(valeur: Decimal) -> str:
    """Montant tel que composé dans la réponse (entier si pas de centimes)."""
    return str(int(valeur)) if valeur == valeur.to_integral_value() else str(valeur)


# ===========================================================================
# 1. RIB — comportement par défaut : compte courant uniquement
# ===========================================================================

DEMANDES_RIB_GENERALES = [
    "Quel est mon RIB ?",
    "Donne-moi mon RIB",
    "Je veux voir mon RIB",
    "C'est quoi mon RIB ?",
    "Je veux connaître mon RIB",
    "Affiche mon RIB",
]


@pytest.mark.parametrize("message", DEMANDES_RIB_GENERALES)
def test_une_demande_generale_renvoie_le_rib_du_compte_courant(env, entetes, message):
    courant = _courant(env)
    reponse = _demander(env, message, entetes)["response"]
    assert reponse == f"Le RIB de votre compte courant est : {courant['rib']}."


@pytest.mark.parametrize("message", DEMANDES_RIB_GENERALES)
def test_la_reponse_rib_ne_contient_ni_iban_ni_numero_ni_carnet(env, entetes, message):
    """Exigence de concision : tout ce qui n'a pas été demandé est absent."""
    reponse = _demander(env, message, entetes)["response"]
    courant = _courant(env)

    assert courant["iban"] not in reponse
    # Le numéro de compte n'est pas ANNONCÉ séparément. Il n'est pas testé par
    # sous-chaîne : le RIB le contient par construction (le RIB est bâti à
    # partir du numéro de compte), l'assertion inverse serait impossible.
    assert "numéro" not in reponse.lower()
    for carnet in _comptes(env, type_compte="carnet"):
        assert carnet["rib"] not in reponse
        assert carnet["iban"] not in reponse
    # Ni solde, ni paragraphe de sécurité.
    assert "MAD" not in reponse
    assert "tiers de confiance" not in reponse
    assert len(reponse.splitlines()) == 1


def test_toutes_les_formulations_generales_donnent_la_meme_reponse(env, entetes):
    reponses = {_demander(env, m, entetes)["response"] for m in DEMANDES_RIB_GENERALES}
    assert len(reponses) == 1


def test_l_iban_reste_accessible_par_sa_propre_question(env, entetes):
    """La concision ne supprime pas l'information : elle la rend adressable."""
    reponse = _demander(env, "Donne-moi mon IBAN", entetes)["response"]
    assert _courant(env)["iban"] in reponse


# ===========================================================================
# 2. RIB — sélection explicite d'un compte
# ===========================================================================


@pytest.mark.parametrize(
    "message",
    [
        "Quel est le RIB de mon compte carnet ?",
        "Donne-moi le RIB de mon compte épargne",
        "rib dyal compte carnet",
        "بغيت ريب حساب التوفير",
    ],
)
def test_plusieurs_carnets_declenchent_une_clarification(env, entetes, message):
    """Le client de démonstration a DEUX carnets : on demande lequel, on n'en
    choisit jamais un silencieusement."""
    reponse = _demander(env, message, entetes)["response"]
    carnets = _comptes(env, type_compte="carnet")
    assert len(carnets) == 2

    for carnet in carnets:
        # Les quatre derniers chiffres de chaque carnet servent de repère…
        assert carnet["numero_compte_masque"][-4:] in reponse
        # …mais aucun RIB n'est divulgué tant que le choix n'est pas fait.
        assert carnet["rib"] not in reponse
    assert "?" in reponse or "؟" in reponse


def test_la_clarification_francaise_a_le_format_attendu(env, entetes):
    reponse = _demander(env, "Quel est le RIB de mon compte carnet ?", entetes)["response"]
    carnets = _comptes(env, type_compte="carnet")
    attendu = (
        f"Vous avez plusieurs comptes carnet : •••• {carnets[0]['numero_compte_masque'][-4:]} "
        f"et •••• {carnets[1]['numero_compte_masque'][-4:]}. Lequel souhaitez-vous consulter ?"
    )
    assert reponse == attendu


def test_preciser_les_derniers_chiffres_selectionne_le_bon_carnet(env, entetes):
    for carnet in _comptes(env, type_compte="carnet"):
        derniers = carnet["numero_compte_masque"][-4:]
        reponse = _demander(env, f"le rib du compte {derniers}", entetes)["response"]
        assert reponse == f"Le RIB de votre compte carnet est : {carnet['rib']}."


def test_un_compte_inexistant_est_annonce_clairement(env, entetes):
    reponse = _demander(env, "rib du compte 9999", entetes)["response"]
    assert reponse == "Aucun compte correspondant n’a été trouvé."


@pytest.mark.parametrize(
    "message",
    ["3tini rib dyal compte courant", "عطيني ريب الحساب الجاري", "RIB du compte courant"],
)
def test_le_compte_courant_explicite_renvoie_son_rib(env, entetes, message):
    assert _courant(env)["rib"] in _demander(env, message, entetes)["response"]


@pytest.mark.parametrize("message", ["chno howa rib dyali", "شنو هو الريب ديالي"])
def test_les_variantes_darija_generales_renvoient_le_compte_courant(env, entetes, message):
    """Mêmes données, même compte sélectionné : seule la langue change."""
    reponse = _demander(env, message, entetes)["response"]
    assert _courant(env)["rib"] in reponse
    for carnet in _comptes(env, type_compte="carnet"):
        assert carnet["rib"] not in reponse


# ===========================================================================
# 3. RIB — authentification
# ===========================================================================


@pytest.mark.parametrize(
    "message", DEMANDES_RIB_GENERALES + ["chno howa rib dyali", "شنو هو الريب ديالي"]
)
def test_sans_authentification_aucun_rib_n_est_revele(env, message):
    payload = _demander(env, message)
    assert payload["requires_auth"] is True
    for compte in _comptes(env):
        assert compte["rib"] not in payload["response"]
        assert compte["iban"] not in payload["response"]


@pytest.mark.parametrize(
    "message",
    ["Qu'est-ce qu'un RIB ?", "À quoi sert un RIB ?", "Quelle est la définition d'un IBAN ?"],
)
def test_les_definitions_publiques_restent_de_la_faq(env, entetes, message):
    payload = _demander(env, message, entetes)
    assert payload["intent"] == "faq_generale"
    for compte in _comptes(env):
        assert compte["rib"] not in payload["response"]


# ===========================================================================
# 4. Plafonds de carte
# ===========================================================================

LES_DEUX_PLAFONDS = [
    "Quels sont les plafonds de ma carte ?",
    "Donne-moi les limites de ma carte",
    "ch7al plafond dyal carte",
    "شنو هما سقوف البطاقة",
]

PLAFOND_PAIEMENT = [
    "Quel est mon plafond de paiement ?",
    "Combien puis-je payer avec ma carte ?",
    "ch7al nqder nkhless b carte",
    "شحال نقدر نخلص بالبطاقة",
]

PLAFOND_RETRAIT = [
    "Quel est mon plafond de retrait ?",
    "Combien puis-je retirer ?",
    "ch7al nqder ns7eb",
    "شحال نقدر نسحب",
]


@pytest.mark.parametrize("message", LES_DEUX_PLAFONDS)
def test_une_question_generale_renvoie_les_deux_plafonds(env, entetes, message):
    carte = _carte(env)
    reponse = _demander(env, message, entetes)["response"]
    assert _montant(carte["paiement"]) in reponse
    assert _montant(carte["retrait"]) in reponse


@pytest.mark.parametrize("message", LES_DEUX_PLAFONDS + PLAFOND_PAIEMENT + PLAFOND_RETRAIT)
def test_une_question_de_plafond_ne_renvoie_jamais_seulement_le_statut(env, entetes, message):
    """NON-RÉGRESSION DIRECTE du défaut signalé : la réponse était
    « Votre carte est active. »"""
    reponse = _demander(env, message, entetes)["response"]
    assert reponse.strip() != "Votre carte est active."
    assert "plafond" in reponse.lower() or "سقف" in reponse or "Plafond" in reponse
    # Un montant réel est toujours présent.
    carte = _carte(env)
    assert _montant(carte["paiement"]) in reponse or _montant(carte["retrait"]) in reponse


@pytest.mark.parametrize("message", PLAFOND_PAIEMENT)
def test_une_question_de_paiement_ne_renvoie_que_le_plafond_de_paiement(env, entetes, message):
    carte = _carte(env)
    reponse = _demander(env, message, entetes)["response"]
    assert _montant(carte["paiement"]) in reponse
    assert _montant(carte["retrait"]) not in reponse


@pytest.mark.parametrize("message", PLAFOND_RETRAIT)
def test_une_question_de_retrait_ne_renvoie_que_le_plafond_de_retrait(env, entetes, message):
    carte = _carte(env)
    reponse = _demander(env, message, entetes)["response"]
    assert _montant(carte["retrait"]) in reponse
    assert _montant(carte["paiement"]) not in reponse


def test_le_format_francais_des_deux_plafonds_est_exact(env, entetes):
    carte = _carte(env)
    reponse = _demander(env, "Quels sont les plafonds de ma carte ?", entetes)["response"]
    assert reponse == (
        f"Votre plafond de paiement est de {_montant(carte['paiement'])} MAD "
        f"et votre plafond de retrait est de {_montant(carte['retrait'])} MAD."
    )


@pytest.mark.parametrize(
    "message",
    ["Quel est le statut de ma carte ?", "ma carte est-elle active ?", "wach carte dyali khdama"],
)
def test_les_questions_de_statut_renvoient_toujours_le_statut(env, entetes, message):
    """Non-régression symétrique : donner la priorité aux plafonds ne doit pas
    faire disparaître le statut."""
    carte = _carte(env)
    reponse = _demander(env, message, entetes)["response"].lower()
    # « khdama » est la forme arabizi de « active » : la réponse est localisée,
    # la donnée reste la même.
    assert (
        carte["statut"].lower() in reponse
        or "active" in reponse
        or "khdama" in reponse
        or "خدامة" in reponse
    ), reponse
    # Et surtout : aucun plafond n'est renvoyé pour une question de statut.
    assert _montant(carte["paiement"]) not in reponse
    assert _montant(carte["retrait"]) not in reponse


@pytest.mark.parametrize("message", LES_DEUX_PLAFONDS + PLAFOND_PAIEMENT + PLAFOND_RETRAIT)
def test_sans_authentification_aucun_plafond_n_est_revele(env, message):
    carte = _carte(env)
    payload = _demander(env, message)
    assert payload["requires_auth"] is True
    assert _montant(carte["paiement"]) not in payload["response"]
    assert _montant(carte["retrait"]) not in payload["response"]


# ===========================================================================
# 5. Isolation entre clients, et Mistral hors service ou en désaccord
# ===========================================================================


def test_deux_clients_recoivent_leurs_propres_valeurs(env):
    entetes_a = _connexion(env, CLIENT_DEMO)
    entetes_b = _connexion(env, AUTRE_CLIENT)

    rib_a = _demander(env, "Quel est mon RIB ?", entetes_a)["response"]
    rib_b = _demander(env, "Quel est mon RIB ?", entetes_b)["response"]
    assert _courant(env, CLIENT_DEMO)["rib"] in rib_a
    assert _courant(env, AUTRE_CLIENT)["rib"] in rib_b
    assert _courant(env, AUTRE_CLIENT)["rib"] not in rib_a
    assert _courant(env, CLIENT_DEMO)["rib"] not in rib_b

    plafonds_a = _demander(env, "Quels sont les plafonds de ma carte ?", entetes_a)["response"]
    plafonds_b = _demander(env, "Quels sont les plafonds de ma carte ?", entetes_b)["response"]
    assert _montant(_carte(env, CLIENT_DEMO)["paiement"]) in plafonds_a
    assert _montant(_carte(env, AUTRE_CLIENT)["paiement"]) in plafonds_b


@pytest.mark.parametrize(
    "message", ["Quel est mon RIB ?", "Quels sont les plafonds de ma carte ?", "Combien puis-je retirer ?"]
)
def test_fonctionne_avec_ollama_indisponible(env, entetes, message, monkeypatch):
    from agents.agent1_faq import graph as graph_module

    monkeypatch.setattr(graph_module.llm_router, "route_with_llm", lambda *a, **k: None)
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: True
    try:
        reponse = _demander(env, message, entetes)["response"]
    finally:
        app.dependency_overrides[get_use_llm_router_dependency] = lambda: False

    assert reponse.strip() != "Votre carte est active."
    assert reponse


def test_la_detection_des_plafonds_l_emporte_sur_un_mistral_qui_dit_card_query(
    env, entetes, monkeypatch
):
    """LA cause du défaut. Mistral ne distingue pas les facettes d'une carte :
    son `card_query` devient `["status"]`, ce qui écrasait la détection
    déterministe des deux plafonds."""
    from agents.agent1_faq import graph as graph_module

    monkeypatch.setattr(
        graph_module.llm_router, "route_with_llm", lambda *a, **k: {"intent": "card_query"}
    )
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: True
    try:
        reponse = _demander(env, "Quels sont les plafonds de ma carte ?", entetes)["response"]
    finally:
        app.dependency_overrides[get_use_llm_router_dependency] = lambda: False

    carte = _carte(env)
    assert reponse.strip() != "Votre carte est active."
    assert _montant(carte["paiement"]) in reponse
    assert _montant(carte["retrait"]) in reponse


def test_un_mistral_qui_dit_card_query_laisse_le_statut_intact(env, entetes, monkeypatch):
    """Contre-preuve : la correction ne remplace que le DÉFAUT générique. Quand
    la question porte bien sur le statut, rien ne change."""
    from agents.agent1_faq import graph as graph_module

    monkeypatch.setattr(
        graph_module.llm_router, "route_with_llm", lambda *a, **k: {"intent": "card_query"}
    )
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: True
    try:
        reponse = _demander(env, "Quel est le statut de ma carte ?", entetes)["response"]
    finally:
        app.dependency_overrides[get_use_llm_router_dependency] = lambda: False

    assert _carte(env)["statut"].lower() in reponse.lower() or "active" in reponse.lower()


# ===========================================================================
# 6. Multi-cartes : jamais de sélection silencieuse
# ===========================================================================


def test_plusieurs_cartes_declenchent_une_clarification_masquee():
    """La base de démonstration ne contient qu'une carte par client ; la règle
    est donc vérifiée directement sur la fonction de mise en phrase, avec deux
    cartes fictives."""
    from agents.agent1_faq import banking_answers

    cartes = [
        {
            "card_id": "CA1",
            "card_type": "Visa Classic",
            "masked_card_number": "450078XXXXXX7007",
            "status": "active",
            "payment_limit": Decimal("5000"),
            "withdrawal_limit": Decimal("2000"),
            "online_payments_enabled": True,
            "international_payments_enabled": False,
        },
        {
            "card_id": "CA2",
            "card_type": "Visa Gold",
            "masked_card_number": "450078XXXXXX9112",
            "status": "active",
            "payment_limit": Decimal("15000"),
            "withdrawal_limit": Decimal("6000"),
            "online_payments_enabled": True,
            "international_payments_enabled": True,
        },
    ]

    # Sans précision, aucune carte n'est choisie : l'appelant doit demander.
    assert banking_answers._select_card(cartes, "plafonds de ma carte") is None

    # Les derniers chiffres cités lèvent l'ambiguïté.
    choisie = banking_answers._select_card(cartes, "plafonds de la carte 9112")
    assert choisie is not None and choisie["card_id"] == "CA2"

    # Le repère proposé à l'utilisateur reste masqué — jamais le PAN.
    reference = banking_answers._derniers_chiffres("450078XXXXXX7007")
    assert reference == "•••• 7007"
    assert "450078" not in reference
