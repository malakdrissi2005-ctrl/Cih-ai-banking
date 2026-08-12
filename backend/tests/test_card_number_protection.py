"""Protection du numéro de carte : refus explicite + redirection sécurisée.

Le numéro complet (PAN) ne doit jamais transiter par le chatbot. La défense
est en trois couches, chacune vérifiée ici :

1. La base ne stocke qu'un numéro MASQUÉ (`numero_carte_masque`) — voir
   `test_banking_db.py::test_card_number_is_stored_masked_only`.
2. `_CARD_FIELD_ORDER` n'expose aucun champ de numéro : la donnée est
   structurellement absente du chemin de réponse.
3. Une demande explicite déclenche un REFUS assorti d'une redirection vers un
   canal sécurisé — objet de ce fichier.

Tous les tests forcent le chemin déterministe (`use_llm_router=False`) ou
appellent directement la classification : jamais de dépendance à Mistral.
"""
import pytest

from agents.agent1_faq.banking_answers import (
    CARD_NUMBER_REDIRECT_MESSAGE,
    build_personal_data_answer,
    classify_personal_intent,
)
from agents.agent1_faq.classification import classify_intent
from agents.agent1_faq.graph import run_agent1
from app.banking import banking_db


@pytest.fixture
def banking_path(tmp_path):
    path = str(tmp_path / "card_protection_test.db")
    banking_db.seed_banking_data(db_path=path)
    return path


_CARD_NUMBER_REQUESTS = [
    "Donne-moi mon numéro de carte complet",
    "Quel est le numéro de ma carte ?",
    "Affiche le numéro complet de ma carte bancaire",
    "Je veux les 16 chiffres de ma carte",
    "C'est quoi le numéro de ma carte ?",
]


@pytest.mark.parametrize("message", _CARD_NUMBER_REQUESTS)
def test_card_number_request_reaches_personal_data(message):
    """Couche 1 : la demande doit atteindre `personal_data` (donc exiger une
    session) pour pouvoir être interceptée. Avant correctif, "Donne-moi mon
    numéro de carte complet" tombait en `faq_generale`."""
    assert classify_intent(message) == "personal_data"


@pytest.mark.parametrize("message", _CARD_NUMBER_REQUESTS)
def test_card_number_request_resolves_to_dedicated_intent(message):
    """Couche 2 : intention dédiée, jamais `card_information` (qui donnerait
    une réponse partielle) ni `assistant_explain` (refus implicite)."""
    assert classify_personal_intent(message)["intent"] == "card_number_redirect"


@pytest.mark.parametrize("message", _CARD_NUMBER_REQUESTS)
def test_card_number_request_is_refused_with_secure_redirect(banking_path, message):
    """Couche 3 : refus explicite + redirection vers l'espace sécurisé."""
    answer = build_personal_data_answer(message, "usr_001", banking_path)
    assert answer == CARD_NUMBER_REDIRECT_MESSAGE
    # POLITIQUE ACTUELLE — le message de refus a été réécrit : il ne dit plus
    # « connectez-vous » à un utilisateur déjà authentifié, ne renvoie plus en
    # agence, ne promet plus « les derniers chiffres » (jamais renvoyés) et
    # n'affirme plus que le numéro complet est consultable ailleurs. Il ne
    # mentionne que l'onglet « Cartes » et les trois informations réellement
    # disponibles (statut, expiration, plafonds).
    assert "ne peut pas être affiché dans le chatbot" in answer
    assert "« Cartes »" in answer
    assert "connectez-vous" not in answer.lower()
    assert "agence" not in answer.lower()
    assert "derniers chiffres" not in answer.lower()


@pytest.mark.parametrize("message", _CARD_NUMBER_REQUESTS)
def test_answer_never_contains_any_card_number(banking_path, message):
    """Aucune suite de chiffres pouvant ressembler à un PAN ne doit apparaître
    dans la réponse — ni complète, ni partielle."""
    answer = build_personal_data_answer(message, "usr_001", banking_path)
    digits = "".join(char for char in answer if char.isdigit())
    assert digits == ""


def test_protection_applies_end_to_end_without_mistral(banking_path):
    """Bout en bout sur le vrai pipeline, Mistral désactivé."""
    result = run_agent1(
        "Donne-moi mon numéro de carte complet",
        is_authenticated=True,
        user_id="usr_001",
        banking_db_path=banking_path,
        use_llm_router=False,
    )
    assert result["intent"] == "personal_data"
    assert result["response"] == CARD_NUMBER_REDIRECT_MESSAGE


def test_protection_holds_even_if_mistral_says_card_query(monkeypatch, banking_path):
    """La protection ne dépend jamais du LLM : même si Mistral classe la
    demande en `card_query`, le refus déterministe reprend la main."""
    from agents.agent1_faq import llm_router

    monkeypatch.setattr(
        llm_router,
        "route_with_llm",
        lambda *a, **k: {
            "intent": "card_query",
            "category": None,
            "period": None,
            "card_fields": ["status"],
            "faq_query": None,
        },
    )
    result = run_agent1(
        "Donne-moi mon numéro de carte complet",
        is_authenticated=True,
        user_id="usr_001",
        banking_db_path=banking_path,
        use_llm_router=True,
    )
    assert "numéro complet" in result["response"]
    assert "« Cartes »" in result["response"]
    assert "agence" not in result["response"].lower()


def test_unauthenticated_card_number_request_requires_login(banking_path):
    """Sécurité : sans session, la demande exige d'abord une connexion."""
    result = run_agent1(
        "Donne-moi mon numéro de carte complet",
        is_authenticated=False,
        banking_db_path=banking_path,
        use_llm_router=False,
    )
    assert result["requires_auth"] is True


# ---------------------------------------------------------------------------
# Non-régression : la protection ne doit pas sur-déclencher.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        ("Quel est le statut actuel de ma carte ?", "card_information"),
        ("Quel est le plafond de ma carte ?", "card_information"),
        ("Ma carte permet-elle les achats en ligne ?", "card_information"),
        ("Détails de ma carte", "card_information"),
        ("Quel est mon solde ?", "total_balance"),
        ("Montre-moi mes dernières opérations", "recent_transactions"),
    ],
)
def test_legitimate_card_and_account_questions_are_unaffected(message, expected_intent):
    assert classify_personal_intent(message)["intent"] == expected_intent


def test_phone_number_question_is_not_treated_as_a_card_number_request():
    """"numéro" seul ne doit rien déclencher : la FAQ publique réelle contient
    "Comment mettre à jour mon numéro de téléphone ?"."""
    assert classify_intent("Comment mettre à jour mon numéro de téléphone ?") == "faq_generale"


def test_card_status_answer_still_returns_real_data(banking_path):
    """Non-régression : une demande légitime continue de renvoyer la donnée."""
    answer = build_personal_data_answer("Quel est le statut actuel de ma carte ?", "usr_001", banking_path)
    assert "active" in answer.lower()
    assert answer != CARD_NUMBER_REDIRECT_MESSAGE
