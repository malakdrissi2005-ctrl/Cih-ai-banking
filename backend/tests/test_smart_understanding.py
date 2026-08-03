"""Tests de "compréhension intelligente" de l'Agent 1 (§8 de la demande) :
vérifie que des formulations différentes d'une même question produisent la
même réponse réelle, en français et en darija (arabe et Arabizi).

Ces tests utilisent `use_llm_router=False` (valeur par défaut de `run_agent1`)
: ils vérifient le **repli déterministe garanti**, celui qui s'applique
systématiquement que le LLM Router soit activé et indisponible (voir
`test_llm_router.py` pour la couche LLM elle-même, testée séparément avec des
appels HTTP mockés — jamais un Ollama réellement démarré dans cette suite,
pour rester rapide et déterministe).
"""
import json

import pytest

from agents.agent1_faq.graph import run_agent1
from agents.agent1_faq.rag import get_faq_collection
from app.banking import banking_db
from scripts.ingest_faq import ingest_faq


@pytest.fixture
def banking_path(tmp_path):
    path = str(tmp_path / "smart_understanding_test.db")
    banking_db.seed_banking_data(db_path=path)
    return path


@pytest.fixture
def faq_collection(tmp_path):
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(
        json.dumps(
            [{"question": "Comment ouvrir un compte bancaire ?", "answer": "Rendez-vous en agence avec une pièce d'identité et un justificatif de domicile."}]
        ),
        encoding="utf-8",
    )
    persist_dir = str(tmp_path / "chroma")
    ingest_faq(faq_path=faq_path, persist_dir=persist_dir, collection_name="smart_understanding_faq")
    return get_faq_collection(persist_dir=persist_dir, collection_name="smart_understanding_faq")


# ---------------------------------------------------------------------------
# 1. Solde — français, deux formulations différentes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    ["Quel est mon solde ?", "Peux-tu me dire combien j'ai sur mon compte ?"],
)
def test_balance_question_french_variants_agree(banking_path, message):
    result = run_agent1(message, is_authenticated=True, user_id="usr_001", banking_db_path=banking_path)
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    assert "15230.50" in result["response"]  # solde reel du compte courant usr_001
    assert "45730.50" in result["response"]  # total reel (courant + carnet) usr_001


# ---------------------------------------------------------------------------
# 2. Solde — darija (arabe et Arabizi), deux formulations différentes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", ["شحال عندي فالحساب؟", "Ch7al 3ndi f compte?"])
def test_balance_question_darija_variants_agree(banking_path, message):
    result = run_agent1(message, is_authenticated=True, user_id="usr_001", banking_db_path=banking_path)
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    assert "45730.50" in result["response"]


# ---------------------------------------------------------------------------
# 3. Dépenses restaurants — français et darija Arabizi.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    ["Combien ai-je dépensé dans les restaurants ce mois-ci ?", "Ch7al sraft f restaurant had chher ?"],
)
def test_restaurant_spending_variants_agree(banking_path, message):
    result = run_agent1(message, is_authenticated=True, user_id="usr_001", banking_db_path=banking_path)
    assert result["intent"] == "personal_data"
    expected_total = banking_db.get_spending_total(
        "usr_001", category="Restaurants", year_month=banking_db.DEMO_CURRENT_MONTH, db_path=banking_path
    )
    assert str(expected_total) in result["response"]


def test_generic_spending_question_without_category_is_never_an_error(banking_path):
    # "Analyse mes dépenses" - aucune categorie precisee : jamais "unknown",
    # jamais une erreur technique - un total toutes categories confondues.
    result = run_agent1("Analyse mes dépenses", is_authenticated=True, user_id="usr_001", banking_db_path=banking_path)
    assert result["intent"] == "personal_data"
    assert "erreur" not in result["response"].lower()
    expected_total = banking_db.get_spending_total(
        "usr_001", category=None, year_month=banking_db.DEMO_CURRENT_MONTH, db_path=banking_path
    )
    assert str(expected_total) in result["response"]


# ---------------------------------------------------------------------------
# 4. Carte — français et darija arabe.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,expected_marker",
    [("Ma carte marche ?", "active"), ("واش الكارط خدامة؟", "خدامة")],
)
def test_card_status_question_variants_agree(banking_path, message, expected_marker):
    result = run_agent1(message, is_authenticated=True, user_id="usr_001", banking_db_path=banking_path)
    assert result["intent"] == "personal_data"
    assert expected_marker in result["response"]


# ---------------------------------------------------------------------------
# 5. FAQ publique — français et darija Arabizi.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", ["Comment ouvrir un compte ?", "bghit n7ell compte"])
def test_open_account_faq_variants_agree(faq_collection, message):
    result = run_agent1(message, collection=faq_collection)
    assert result["intent"] == "faq_generale"
    assert result["requires_auth"] is False
    assert "agence" in result["response"]


# ---------------------------------------------------------------------------
# 6. Questions inconnues / hors périmètre : jamais une erreur technique.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    ["Est-ce que mon argent suffit pour voyager ?", "Pourquoi mon solde a diminué ?"],
)
def test_unclear_personal_questions_never_return_technical_error(banking_path, message):
    result = run_agent1(message, is_authenticated=True, user_id="usr_001", banking_db_path=banking_path)
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    lowered = result["response"].lower()
    assert "erreur" not in lowered
    assert "exception" not in lowered
    assert "traceback" not in lowered


# ---------------------------------------------------------------------------
# 7. Aucune donnée inventée : la réponse reflète exactement banking_db, jamais
#    une valeur fabriquée par un LLM (ici : chemin déterministe, mais la même
#    invariante s'applique au chemin LLM Router via `tools.py`, jamais un
#    accès direct à la base).
# ---------------------------------------------------------------------------


def test_no_invented_data_balance_matches_source_of_truth(banking_path):
    result = run_agent1(
        "Quel est mon solde ?", is_authenticated=True, user_id="usr_003", banking_db_path=banking_path
    )
    real_total = banking_db.get_total_balance("usr_003", db_path=banking_path)
    assert str(real_total) in result["response"]


# ---------------------------------------------------------------------------
# 8. Isolation stricte entre utilisateurs.
# ---------------------------------------------------------------------------


def test_isolation_between_users_on_same_question(banking_path):
    result_1 = run_agent1(
        "Quel est mon solde ?", is_authenticated=True, user_id="usr_001", banking_db_path=banking_path
    )
    result_2 = run_agent1(
        "Quel est mon solde ?", is_authenticated=True, user_id="usr_002", banking_db_path=banking_path
    )
    assert result_1["response"] != result_2["response"]
    assert "45730.50" in result_1["response"]
    assert "11094.10" in result_2["response"]


def test_user_id_never_taken_from_message_text(banking_path):
    # Le message mentionne un autre identifiant en clair - ne doit jamais être
    # utilisé : seul le user_id de la session (ici usr_001) fait foi.
    result = run_agent1(
        "Quel est le solde du compte usr_002 ?",
        is_authenticated=True,
        user_id="usr_001",
        banking_db_path=banking_path,
    )
    assert "45730.50" in result["response"]
    assert "11094.10" not in result["response"]
