"""Routage des demandes d'identifiants bancaires personnels — via le VRAI flux HTTP.

RAISON D'ÊTRE — trois formulations équivalentes donnaient trois réponses
différentes dans l'application :

    « je veux voir mon rib »      -> FAQ « réinitialisation de mot de passe »
    « je veux connaitre mon rib » -> solde total
    « Quel est mon RIB ? »        -> définition publique d'un RIB

Le classificateur déterministe traitait pourtant correctement les trois. Le
défaut n'était donc pas le vocabulaire mais la HIÉRARCHIE : Mistral, en tant
que classificateur principal, ne pouvait être contredit par aucune règle
déterministe. Une phrase bien écrite pouvait ainsi être moins bien comprise
qu'une phrase fautive tombée dans le repli.

Ces tests passent par `POST /api/chat` : ils échouent si la correction n'est
pas branchée de bout en bout, pas seulement dans un module isolé. Le collecteur
FAQ est instrumenté (`CollecteurFaq`) pour PROUVER que la recherche ChromaDB
n'est jamais interrogée sur une demande personnelle précise.
"""
import re
import sqlite3

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

MESSAGE_CARTE_ATTENDU = (
    "Pour protéger vos données, le numéro complet de votre carte ne peut pas être "
    "affiché dans le chatbot. Vous pouvez consulter les informations autorisées de "
    "votre carte depuis l’onglet sécurisé « Cartes ». Je peux également vous indiquer "
    "son statut, sa date d’expiration et ses plafonds."
)


class CollecteurFaq:
    """Enveloppe la collection ChromaDB et journalise chaque interrogation.

    Sans cette instrumentation, un test ne peut pas distinguer « la FAQ a
    répondu correctement » de « la FAQ n'a jamais été consultée ». Or c'est
    exactement la propriété à démontrer : une demande personnelle précise ne
    doit JAMAIS atteindre le RAG.
    """

    def __init__(self, collection):
        self._collection = collection
        self.appels = []

    def query(self, *args, **kwargs):
        self.appels.append(kwargs.get("query_texts", args[0] if args else None))
        return self._collection.query(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._collection, name)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    racine = tmp_path_factory.mktemp("rib_routing")
    chemin_bancaire = str(racine / "demo_bancaire.db")
    chemin_auth = str(racine / "auth.db")
    dossier_chroma = str(racine / "chroma")

    from scripts.seed_demo_database import seed_demo_database

    seed_demo_database(db_path=chemin_bancaire)
    session_manager.init_db(chemin_auth)
    ingest_faq(persist_dir=dossier_chroma, collection_name="faq_rib_test")
    collecteur = CollecteurFaq(
        get_faq_collection(persist_dir=dossier_chroma, collection_name="faq_rib_test")
    )

    app.dependency_overrides[get_auth_db_path] = lambda: chemin_auth
    app.dependency_overrides[get_banking_db_path] = lambda: chemin_bancaire
    app.dependency_overrides[get_banking_db_path_dependency] = lambda: chemin_bancaire
    app.dependency_overrides[get_faq_collection_dependency] = lambda: collecteur
    # Mistral coupé : prouve que la voie déterministe suffit (exigence
    # « Ollama indisponible »). Un test dédié ci-dessous rejoue les mêmes
    # formulations avec un Mistral qui répond FAUX, pour vérifier que la
    # décision déterministe l'emporte quand même.
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: False

    yield {
        "client": TestClient(app),
        "banking_path": chemin_bancaire,
        "collecteur": collecteur,
    }

    app.dependency_overrides.clear()


def _connexion(env, id_client=CLIENT_DEMO):
    with sqlite3.connect(env["banking_path"]) as c:
        login = c.execute(
            "SELECT identifiant_connexion FROM UTILISATEUR_E_BANKING WHERE id_client = ?",
            (id_client,),
        ).fetchone()[0]
    # Le générateur n'attribue DEMO_PASSWORD qu'au client de démonstration ;
    # les 99 autres reçoivent FIXTURE_PASSWORD.
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


def _compte_courant_sql(env, id_client=CLIENT_DEMO):
    """Coordonnées du COMPTE COURANT — le compte répondu par défaut."""
    with sqlite3.connect(env["banking_path"]) as c:
        c.row_factory = sqlite3.Row
        return dict(
            c.execute(
                "SELECT rib, iban, numero_compte, numero_compte_masque FROM COMPTE_BANCAIRE "
                "WHERE id_client = ? AND type_compte = 'courant'",
                (id_client,),
            ).fetchone()
        )


def _coordonnees_sql(env, id_client=CLIENT_DEMO):
    with sqlite3.connect(env["banking_path"]) as c:
        c.row_factory = sqlite3.Row
        return [
            dict(ligne)
            for ligne in c.execute(
                "SELECT rib, iban, numero_compte, id_compte FROM COMPTE_BANCAIRE "
                "WHERE id_client = ? ORDER BY id_compte",
                (id_client,),
            )
        ]


# ---------------------------------------------------------------------------
# 1. Les trois formulations qui échouaient dans l'application
# ---------------------------------------------------------------------------

TROIS_BUGS = [
    "je veux voir mon rib",
    "je veux connaitre mon rib",
    "Quel est mon RIB ?",
]


@pytest.mark.parametrize("message", TROIS_BUGS)
def test_les_trois_formulations_en_echec_renvoient_le_vrai_rib(env, entetes, message):
    """NON-RÉGRESSION DIRECTE du défaut signalé : ces trois phrases doivent
    donner la MÊME réponse, celle des coordonnées réelles du client."""
    payload = _demander(env, message, entetes)
    courant = _compte_courant_sql(env)

    assert payload["requires_auth"] is False
    # RÉPONSE CONCISE : le RIB du compte courant, et lui seul.
    assert courant["rib"] in payload["response"]
    for compte in _coordonnees_sql(env):
        if compte["rib"] != courant["rib"]:
            assert compte["rib"] not in payload["response"]
    assert courant["iban"] not in payload["response"]


@pytest.mark.parametrize("message", TROIS_BUGS)
def test_les_trois_formulations_ne_renvoient_plus_la_mauvaise_reponse(env, entetes, message):
    """Chacune renvoyait une réponse d'une autre famille : mot de passe, solde
    total, définition publique. Aucune ne doit réapparaître."""
    texte = _demander(env, message, entetes)["response"].lower()

    assert "mot de passe" not in texte  # bug n°1 : FAQ réinitialisation
    assert "le total de vos comptes" not in texte  # bug n°2 : solde total
    # bug n°3 : définition publique ("le RIB est un relevé d'identité bancaire…")
    assert "releve d'identite bancaire" not in texte
    assert "relevé d'identité bancaire" not in texte


def test_les_trois_formulations_donnent_la_meme_reponse(env, entetes):
    """Le cœur du défaut : trois formulations équivalentes, trois réponses
    différentes. Elles doivent désormais être strictement identiques."""
    reponses = {_demander(env, m, entetes)["response"] for m in TROIS_BUGS}
    assert len(reponses) == 1


# ---------------------------------------------------------------------------
# 2 & 3. Variantes françaises, darija arabe et arabizi
# ---------------------------------------------------------------------------

VARIANTES_FR = [
    "Quel est mon RIB ?",
    "Je veux voir mon RIB",
    "Je veux connaître mon RIB",
    "Montre-moi mon RIB",
    "Donne-moi mon RIB",
    "Je veux consulter mon RIB",
    "Quel est mon IBAN ?",
    "J'ai besoin de mon RIB",
    "Peux-tu m'afficher mes coordonnées bancaires ?",
    "Quel est le numéro de mon compte ?",
]

VARIANTES_DARIJA = [
    "chno howa rib dyali",
    "bghit nchof rib dyali",
    "3tini rib dyali",
    "بغيت نشوف الريب ديالي",
    "شنو هو الريب ديالي",
]


@pytest.mark.parametrize("message", VARIANTES_FR)
def test_variantes_francaises_atteignent_les_coordonnees(env, entetes, message):
    payload = _demander(env, message, entetes)
    courant = _compte_courant_sql(env)
    # Chaque variante doit renvoyer une coordonnée RÉELLE du compte courant —
    # le RIB par défaut, l'IBAN ou le numéro si la question les vise.
    assert any(
        courant[champ] in payload["response"] for champ in ("rib", "iban", "numero_compte")
    ), payload["response"]


@pytest.mark.parametrize("message", VARIANTES_DARIJA)
def test_variantes_darija_atteignent_les_coordonnees(env, entetes, message):
    """Les données renvoyées sont identiques quelle que soit la langue : seule
    la mise en phrase change."""
    payload = _demander(env, message, entetes)
    assert _compte_courant_sql(env)["rib"] in payload["response"]


def test_une_phrase_correcte_n_est_jamais_moins_bien_comprise_qu_une_fautive(env, entetes):
    """Exigence explicite : « Quel est mon RIB ? » (irréprochable) doit être au
    moins aussi bien traitée que « kel é mon rib » (fautive)."""
    correcte = _demander(env, "Quel est mon RIB ?", entetes)["response"]
    fautive = _demander(env, "je ve voir mon rib", entetes)["response"]
    rib = _compte_courant_sql(env)["rib"]
    assert rib in correcte
    assert rib in fautive


# ---------------------------------------------------------------------------
# 4. Non authentifié vs authentifié
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", TROIS_BUGS + VARIANTES_DARIJA)
def test_sans_authentification_aucun_identifiant_n_est_revele(env, message):
    payload = _demander(env, message)
    assert payload["requires_auth"] is True
    for compte in _coordonnees_sql(env):
        assert compte["rib"] not in payload["response"]
        assert compte["iban"] not in payload["response"]
        assert compte["numero_compte"] not in payload["response"]


def test_un_jeton_invente_ne_revele_aucun_identifiant(env):
    payload = _demander(env, "Quel est mon RIB ?", {"Authorization": "Bearer jeton-invente"})
    for compte in _coordonnees_sql(env):
        assert compte["rib"] not in payload["response"]


# ---------------------------------------------------------------------------
# 5. Comparaison exacte avec SQL
# ---------------------------------------------------------------------------


def test_rib_et_iban_correspondent_exactement_a_la_base(env, entetes):
    courant = _compte_courant_sql(env)
    assert len(_coordonnees_sql(env)) == 3  # le client de démonstration a 3 comptes

    rib = _demander(env, "Quel est mon RIB ?", entetes)["response"]
    assert rib == f"Le RIB de votre compte courant est : {courant['rib']}."

    # L'IBAN reste accessible — par sa propre question.
    iban = _demander(env, "Donne-moi mon IBAN", entetes)["response"]
    assert courant["iban"] in iban


def test_aucun_rib_inconnu_de_la_base_n_est_invente(env, entetes):
    texte = _demander(env, "Quel est mon RIB ?", entetes)["response"]
    ribs_connus = {c["rib"] for c in _coordonnees_sql(env)}
    for candidat in re.findall(r"\b\d{20,26}\b", texte):
        assert candidat in ribs_connus or any(candidat in iban for iban in
                                              (c["iban"] for c in _coordonnees_sql(env)))


# ---------------------------------------------------------------------------
# 6. Deux clients, isolation stricte
# ---------------------------------------------------------------------------


def test_deux_clients_recoivent_chacun_ses_propres_coordonnees(env):
    entetes_a = _connexion(env, CLIENT_DEMO)
    entetes_b = _connexion(env, AUTRE_CLIENT)

    texte_a = _demander(env, "Quel est mon RIB ?", entetes_a)["response"]
    texte_b = _demander(env, "Quel est mon RIB ?", entetes_b)["response"]

    courant_a = _compte_courant_sql(env, CLIENT_DEMO)
    courant_b = _compte_courant_sql(env, AUTRE_CLIENT)

    assert texte_a != texte_b
    assert courant_a["rib"] in texte_a
    assert courant_b["rib"] in texte_b
    # Aucune coordonnée de l'un ne peut apparaître chez l'autre.
    for compte in _coordonnees_sql(env, AUTRE_CLIENT):
        assert compte["rib"] not in texte_a
    for compte in _coordonnees_sql(env, CLIENT_DEMO):
        assert compte["rib"] not in texte_b


# ---------------------------------------------------------------------------
# 7. Les définitions publiques restent publiques
# ---------------------------------------------------------------------------

DEFINITIONS_PUBLIQUES = [
    "Qu'est-ce qu'un RIB ?",
    "À quoi sert un RIB ?",
    "Quelle est la définition d'un IBAN ?",
]


@pytest.mark.parametrize("message", DEFINITIONS_PUBLIQUES)
def test_les_definitions_restent_publiques_et_sans_donnee(env, entetes, message):
    """Sans possessif, une question de définition reste une question de FAQ —
    y compris pour un utilisateur authentifié, qui ne doit pas recevoir ses
    propres coordonnées à la place de l'explication demandée."""
    payload = _demander(env, message, entetes)
    for compte in _coordonnees_sql(env):
        assert compte["rib"] not in payload["response"]
        assert compte["iban"] not in payload["response"]


@pytest.mark.parametrize("message", DEFINITIONS_PUBLIQUES)
def test_les_definitions_sont_accessibles_sans_authentification(env, message):
    assert _demander(env, message)["requires_auth"] is False


def test_la_possession_l_emporte_sur_la_formulation_definitionnelle(env, entetes):
    """« c'est quoi mon rib » porte un marqueur de définition ET un possessif :
    le possessif tranche."""
    texte = _demander(env, "c'est quoi mon rib", entetes)["response"]
    assert _coordonnees_sql(env)[0]["rib"] in texte


# ---------------------------------------------------------------------------
# 8. Les questions de solde répondent toujours un solde
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    ["Quel est mon solde ?", "Combien j'ai sur mon compte ?", "chhal 3andi f l7sab"],
)
def test_les_questions_de_solde_renvoient_toujours_un_solde(env, entetes, message):
    """Non-régression : la nouvelle priorité des identifiants ne doit pas
    capturer les questions de solde."""
    from app.banking import banking_db

    total = banking_db.get_total_balance(CLIENT_DEMO, db_path=env["banking_path"])
    assert str(total) in _demander(env, message, entetes)["response"]


# ---------------------------------------------------------------------------
# 9. Numéro de compte : coordonnée client oui, clé technique jamais
# ---------------------------------------------------------------------------


def test_le_numero_de_compte_client_est_communique(env, entetes):
    texte = _demander(env, "Quel est le numéro de mon compte ?", entetes)["response"]
    assert _compte_courant_sql(env)["numero_compte"] in texte


def test_la_cle_technique_id_compte_n_est_jamais_communiquee(env, entetes):
    texte = _demander(env, "Quel est le numéro de mon compte ?", entetes)["response"]
    for compte in _coordonnees_sql(env):
        assert compte["id_compte"] not in texte


def test_la_note_de_securite_ne_renvoie_pas_vers_une_fonction_inexistante(env, entetes):
    texte = _demander(env, "Quel est mon RIB ?", entetes)["response"].lower()
    assert "agence" not in texte
    assert "connectez-vous" not in texte


# ---------------------------------------------------------------------------
# 10 & 11. Numéro de carte et secrets
# ---------------------------------------------------------------------------

DEMANDES_NUMERO_CARTE = [
    "Donne-moi mon numéro de carte complet",
    "Quel est le numéro de ma carte ?",
    "Je veux les 16 chiffres de ma carte",
]


@pytest.mark.parametrize("message", DEMANDES_NUMERO_CARTE)
def test_le_nouveau_message_carte_est_renvoye_mot_pour_mot(env, entetes, message):
    assert _demander(env, message, entetes)["response"] == MESSAGE_CARTE_ATTENDU


@pytest.mark.parametrize("message", DEMANDES_NUMERO_CARTE)
def test_le_message_carte_ne_contient_aucune_affirmation_inexacte(env, entetes, message):
    """Les quatre inexactitudes de l'ancienne rédaction, une par assertion."""
    texte = _demander(env, message, entetes)["response"].lower()
    assert "connectez-vous" not in texte  # l'utilisateur EST authentifié
    assert "agence" not in texte  # non implémenté
    assert "derniers chiffres" not in texte  # jamais renvoyés
    assert "numéro complet" in texte and "ne peut pas être affiché" in texte


def test_sans_authentification_la_demande_de_carte_exige_une_connexion(env):
    payload = _demander(env, "Quel est le numéro de ma carte ?")
    assert payload["requires_auth"] is True
    assert payload["response"] != MESSAGE_CARTE_ATTENDU


def test_aucun_secret_n_apparait_jamais_dans_les_reponses(env, entetes):
    """PAN complet, CVV, PIN, hash, identifiants techniques et jeton de session."""
    messages = (
        TROIS_BUGS
        + VARIANTES_FR
        + VARIANTES_DARIJA
        + DEMANDES_NUMERO_CARTE
        + DEFINITIONS_PUBLIQUES
        + ["Quel est mon solde ?", "Quelle est ma carte ?"]
    )
    tout = "\n".join(_demander(env, m, entetes)["response"] for m in messages)

    with sqlite3.connect(env["banking_path"]) as c:
        masque = c.execute(
            "SELECT numero_carte_masque FROM CARTE_BANCAIRE ca "
            "JOIN COMPTE_BANCAIRE co ON co.id_compte = ca.id_compte WHERE co.id_client = ?",
            (CLIENT_DEMO,),
        ).fetchone()[0]

    assert masque not in tout
    assert "$2b$" not in tout
    assert DEMO_PASSWORD not in tout
    assert entetes["Authorization"].split()[1] not in tout
    for compte in _coordonnees_sql(env):
        assert compte["id_compte"] not in tout
    for mot in ("cvv", "cvc", "code pin", "mot de passe hash"):
        assert mot not in tout.lower()


# ---------------------------------------------------------------------------
# 12. Mistral indisponible ou en désaccord
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", TROIS_BUGS)
def test_fonctionne_avec_ollama_indisponible(env, entetes, message, monkeypatch):
    """`route_with_llm` retourne `None` quand Ollama est injoignable."""
    from agents.agent1_faq import graph as graph_module

    monkeypatch.setattr(
        graph_module.llm_router, "route_with_llm", lambda *a, **k: None
    )
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: True
    try:
        texte = _demander(env, message, entetes)["response"]
    finally:
        app.dependency_overrides[get_use_llm_router_dependency] = lambda: False
    assert _coordonnees_sql(env)[0]["rib"] in texte


@pytest.mark.parametrize(
    "intention_mistral", ["faq_search", "balance_query", "unclear"]
)
def test_la_decision_deterministe_l_emporte_sur_un_mistral_qui_se_trompe(
    env, entetes, intention_mistral, monkeypatch
):
    """LE test de la correction. C'est exactement ce qui produisait les trois
    réponses erronées : Mistral répondait `faq_search` ou `balance_query`, et
    aucune règle déterministe ne pouvait le contredire."""
    from agents.agent1_faq import graph as graph_module

    monkeypatch.setattr(
        graph_module.llm_router,
        "route_with_llm",
        lambda *a, **k: {"intent": intention_mistral},
    )
    app.dependency_overrides[get_use_llm_router_dependency] = lambda: True
    try:
        texte = _demander(env, "je veux voir mon rib", entetes)["response"]
    finally:
        app.dependency_overrides[get_use_llm_router_dependency] = lambda: False

    assert _coordonnees_sql(env)[0]["rib"] in texte
    assert "mot de passe" not in texte.lower()


# ---------------------------------------------------------------------------
# 13. La FAQ/RAG n'est jamais consultée pour une demande personnelle précise
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", TROIS_BUGS + VARIANTES_FR + VARIANTES_DARIJA)
def test_aucune_demande_de_rib_n_atteint_le_rag(env, entetes, message):
    """Preuve par instrumentation : le collecteur enregistre chaque appel à
    ChromaDB. Une demande personnelle précise ne doit en déclencher aucun."""
    collecteur = env["collecteur"]
    avant = len(collecteur.appels)
    _demander(env, message, entetes)
    assert len(collecteur.appels) == avant, (
        f"{message!r} a interrogé le RAG : {collecteur.appels[avant:]}"
    )


@pytest.mark.parametrize("message", DEMANDES_NUMERO_CARTE)
def test_aucune_demande_de_numero_de_carte_n_atteint_le_rag(env, entetes, message):
    collecteur = env["collecteur"]
    avant = len(collecteur.appels)
    _demander(env, message, entetes)
    assert len(collecteur.appels) == avant


def test_le_collecteur_detecte_bien_les_appels_rag(env, entetes):
    """Contre-preuve indispensable : sans elle, les deux tests ci-dessus
    passeraient même si le collecteur était simplement cassé."""
    collecteur = env["collecteur"]
    avant = len(collecteur.appels)
    _demander(env, "Qu'est-ce qu'un RIB ?", entetes)
    assert len(collecteur.appels) > avant


# ---------------------------------------------------------------------------
# Repli personnel générique — clarification ciblée, jamais la FAQ
# ---------------------------------------------------------------------------


# Messages personnels volontairement vagues, MAIS portant tous une entité
# bancaire reconnue en plus du possessif — c'est la condition exacte posée par
# la règle du repli générique.
DEMANDES_VAGUES = [
    "j'aimerais comprendre mon solde",
    "que dit mon rib",
    "explique-moi mes operations",
]

# Contre-exemple assumé, documenté ici pour que la limite soit explicite :
# « mes affaires bancaires » porte un possessif mais AUCUNE entité bancaire
# reconnue. La règle du repli générique ne s'y applique donc pas, et le message
# suit normalement son chemin vers la FAQ — comportement voulu, pas un oubli.
SANS_ENTITE_RECONNUE = "aide-moi avec mes affaires bancaires"


@pytest.mark.parametrize("message", DEMANDES_VAGUES)
def test_une_demande_personnelle_vague_n_atteint_jamais_le_rag(env, entetes, message):
    """Exigence centrale du repli générique : ne jamais repartir vers la FAQ."""
    collecteur = env["collecteur"]
    avant = len(collecteur.appels)
    _demander(env, message, entetes)
    assert len(collecteur.appels) == avant


@pytest.mark.parametrize("message", DEMANDES_VAGUES)
def test_une_demande_vague_ne_renvoie_ni_mot_de_passe_ni_definition(env, entetes, message):
    texte = _demander(env, message, entetes)["response"].lower()
    assert "mot de passe" not in texte
    assert "relevé d'identité bancaire" not in texte


def test_une_demande_personnelle_vague_exige_une_connexion_sans_session(env):
    assert _demander(env, DEMANDES_VAGUES[0])["requires_auth"] is True


def test_un_possessif_sans_entite_reconnue_reste_une_question_de_faq(env, entetes):
    """Délimite précisément la règle : sans entité bancaire reconnue, le repli
    générique ne s'applique pas et la FAQ reste le bon destinataire."""
    from agents.agent1_faq import personal_entities

    assert personal_entities.resolve(SANS_ENTITE_RECONNUE).entity is None
    collecteur = env["collecteur"]
    avant = len(collecteur.appels)
    _demander(env, SANS_ENTITE_RECONNUE, entetes)
    assert len(collecteur.appels) > avant


@pytest.mark.parametrize(
    ("message", "attendu"),
    [
        ("aide moi avec mon rib", "coordonnées bancaires"),
        ("conseille-moi sur mon solde", "solde"),
        ("explique mes operations", "opérations"),
    ],
)
def test_la_clarification_ciblee_porte_sur_l_entite_mentionnee(message, attendu):
    """Test unitaire du repli ciblé : quand aucune sous-intention n'est
    résolue, la question posée porte sur l'entité que l'utilisateur vient de
    mentionner — jamais un catalogue générique, jamais la FAQ."""
    from agents.agent1_faq.banking_answers import _targeted_clarification

    clarification = _targeted_clarification(message)
    assert clarification is not None
    assert attendu.lower() in clarification.lower()
    assert clarification.rstrip().endswith("?")


def test_aucune_clarification_ciblee_sans_entite_reconnue():
    """Contre-preuve : sans entité, le repli ciblé se tait et laisse
    l'appelant produire sa réponse habituelle."""
    from agents.agent1_faq.banking_answers import _targeted_clarification

    assert _targeted_clarification("j'ai une question sur mes finances") is None
