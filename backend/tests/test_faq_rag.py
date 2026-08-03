"""Tests du pipeline FAQ/RAG amélioré : `llm_router.extract_faq_topic`,
`llm_router.rerank_faq_candidates`, `graph._merge_faq_candidates`, et le nœud
`graph._answer_faq_node` qui les orchestre.

Tous les appels à Mistral sont mockés ici (jamais un Ollama réel) — même
convention que `test_llm_router.py`/`test_llm_first_routing.py`, suite rapide
et déterministe. La fiabilité réelle du modèle sur des phrases avec fautes/
darija est vérifiée séparément, contre un Ollama réellement démarré, par
`test_ollama_integration.py` (désactivé par défaut) — mesurée empiriquement à
~80% (12/15, top_k=7) sur les 5 phrases "ouverture de compte" testées, jamais
100% : le repli déterministe (candidat le mieux classé par ChromaDB) reste la
garantie en toutes circonstances, jamais une erreur visible.
"""
from __future__ import annotations

import json

import pytest

from agents.agent1_faq import llm_router
from agents.agent1_faq.graph import _merge_faq_candidates, run_agent1
from agents.agent1_faq.rag import get_faq_collection
from scripts.ingest_faq import ingest_faq

# Corpus de test volontairement piégeux : deux entrées "ouvrir"/"fermer" ne
# différant que d'un mot (reproduit le cas réel qui trompait l'embedding
# "sac de mots haché" — voir rag.py), plus une entrée hors-sujet (virement).
FAQ_ENTRIES = [
    {
        "id": "test-ouverture",
        "question": "Quels documents sont nécessaires pour ouvrir un compte ?",
        "answer": "Généralement une pièce d'identité en cours de validité, un justificatif de domicile et parfois un justificatif de revenus sont demandés.",
    },
    {
        "id": "test-fermeture",
        "question": "Comment fermer un compte bancaire ?",
        "answer": "La fermeture d'un compte se demande généralement par écrit ou en agence, après régularisation du solde.",
    },
    {
        "id": "test-virement",
        "question": "Comment fonctionne un virement bancaire ?",
        "answer": "Un virement bancaire consiste à transférer des fonds d'un compte vers un autre.",
    },
]
OUVERTURE_ANSWER = FAQ_ENTRIES[0]["answer"]


@pytest.fixture
def faq_collection(tmp_path):
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(json.dumps(FAQ_ENTRIES), encoding="utf-8")
    persist_dir = str(tmp_path / "chroma")
    ingest_faq(faq_path=faq_path, persist_dir=persist_dir, collection_name="faq_rag_test")
    return get_faq_collection(persist_dir=persist_dir, collection_name="faq_rag_test")


# ---------------------------------------------------------------------------
# 1. extract_faq_topic — mocké.
# ---------------------------------------------------------------------------


def _fake_response(payload: dict):
    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"response": json.dumps(payload)}

    return _R()


def test_extract_faq_topic_valid(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _fake_response({"topic": "Comment ouvrir un compte bancaire"}))
    topic = llm_router.extract_faq_topic("je veux ouvre un comrt", "je veux ouvre un comrt", "fr")
    assert topic == "Comment ouvrir un compte bancaire"


def test_extract_faq_topic_rejects_forbidden_field(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    import httpx

    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: _fake_response({"topic": "Comment ouvrir un compte", "user_id": "usr_999"})
    )
    assert llm_router.extract_faq_topic("...", "...", "fr") is None


def test_extract_faq_topic_returns_none_on_timeout(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    import httpx

    def _raise(*a, **k):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "post", _raise)
    assert llm_router.extract_faq_topic("...", "...", "fr") is None


def test_extract_faq_topic_returns_none_when_not_configured(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert llm_router.extract_faq_topic("...", "...", "fr") is None


# ---------------------------------------------------------------------------
# 2. rerank_faq_candidates — mocké.
# ---------------------------------------------------------------------------


def test_rerank_returns_valid_index(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _fake_response({"best_match_index": 1}))
    candidates = [{"question": "A"}, {"question": "B"}]
    assert llm_router.rerank_faq_candidates("...", candidates) == 1


def test_rerank_rejects_out_of_bounds_index(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _fake_response({"best_match_index": 99}))
    candidates = [{"question": "A"}, {"question": "B"}]
    assert llm_router.rerank_faq_candidates("...", candidates) is None


def test_rerank_rejects_bool_index(monkeypatch):
    # bool est une sous-classe d'int en Python (True == 1) - doit être rejeté
    # explicitement, jamais interprété comme un index valide.
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _fake_response({"best_match_index": True}))
    candidates = [{"question": "A"}, {"question": "B"}]
    assert llm_router.rerank_faq_candidates("...", candidates) is None


def test_rerank_accepts_null_index(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _fake_response({"best_match_index": None}))
    candidates = [{"question": "A"}]
    assert llm_router.rerank_faq_candidates("...", candidates) is None


def test_rerank_returns_none_for_empty_candidates(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    assert llm_router.rerank_faq_candidates("...", []) is None


# ---------------------------------------------------------------------------
# 3. _merge_faq_candidates — dédup + tri par distance.
# ---------------------------------------------------------------------------


def test_merge_faq_candidates_dedupes_and_keeps_best_distance(faq_collection):
    merged = _merge_faq_candidates(
        faq_collection, ["ouvrir un compte", "documents pour ouvrir un compte"], top_k=3
    )
    questions = [c["question"] for c in merged]
    assert len(questions) == len(set(questions)), "Aucun doublon attendu après fusion"
    # Trié du plus proche au moins proche.
    distances = [c["distance"] for c in merged]
    assert distances == sorted(distances)


def test_merge_faq_candidates_empty_queries_returns_empty(faq_collection):
    assert _merge_faq_candidates(faq_collection, [None, ""], top_k=3) == []


# ---------------------------------------------------------------------------
# 4. Bout en bout (mocké) : les 4 phrases de la demande, dont la FAQ.
#    "ch7al 3ndi fl compte" / "شحال عندي فالحساب" / "kel est mon sold" sont
#    déjà couvertes (balance_query) par test_llm_first_routing.py — ici on
#    vérifie spécifiquement la phrase FAQ ("je veux ouvre un comrt") à travers
#    le nouveau pipeline extraction+retrieval hybride+reranking.
# ---------------------------------------------------------------------------


def test_typo_faq_question_resolves_to_correct_answer_via_mocked_mistral(monkeypatch, faq_collection):
    # Mistral reformule le sujet correctement ET choisit le bon candidat parmi
    # ceux fusionnés (ouverture à l'index 0 après fusion/tri par distance).
    monkeypatch.setattr(llm_router, "extract_faq_topic", lambda *a, **k: "Comment ouvrir un compte bancaire")
    monkeypatch.setattr(llm_router, "rerank_faq_candidates", lambda question, candidates, **k: next(
        i for i, c in enumerate(candidates) if c["question"] == FAQ_ENTRIES[0]["question"]
    ))

    result = run_agent1("je veux ouvre un comrt", is_authenticated=False, use_llm_router=True, collection=faq_collection)
    assert result["intent"] == "faq_generale"
    assert result["response"] == OUVERTURE_ANSWER


def test_faq_falls_back_to_top_candidate_when_rerank_fails(monkeypatch, faq_collection):
    # rerank_faq_candidates échoue (None) -> repli garanti sur le premier
    # candidat fusionné (déjà trié par distance), jamais une exception.
    monkeypatch.setattr(llm_router, "extract_faq_topic", lambda *a, **k: "Comment ouvrir un compte bancaire")
    monkeypatch.setattr(llm_router, "rerank_faq_candidates", lambda *a, **k: None)

    result = run_agent1("je veux ouvre un comrt", is_authenticated=False, use_llm_router=True, collection=faq_collection)
    assert result["intent"] == "faq_generale"
    assert "erreur" not in result["response"].lower()


def test_faq_falls_back_to_normalized_text_when_topic_extraction_fails(monkeypatch, faq_collection):
    # extract_faq_topic échoue (None) -> repli garanti sur le texte normalisé
    # seul pour la recherche, comportement historique.
    monkeypatch.setattr(llm_router, "extract_faq_topic", lambda *a, **k: None)
    monkeypatch.setattr(llm_router, "rerank_faq_candidates", lambda *a, **k: None)

    result = run_agent1(
        "Quels documents sont nécessaires pour ouvrir un compte ?",
        is_authenticated=False,
        use_llm_router=True,
        collection=faq_collection,
    )
    assert result["response"] == OUVERTURE_ANSWER


def test_use_llm_router_false_uses_historical_single_candidate_path(monkeypatch, faq_collection):
    # use_llm_router=False : comportement historique STRICTEMENT inchangé,
    # ni extract_faq_topic ni rerank_faq_candidates ne doivent être appelés.
    def _fail(*a, **k):
        raise AssertionError("ne doit jamais être appelé quand use_llm_router=False")

    monkeypatch.setattr(llm_router, "extract_faq_topic", _fail)
    monkeypatch.setattr(llm_router, "rerank_faq_candidates", _fail)

    result = run_agent1(
        "Quels documents sont nécessaires pour ouvrir un compte ?",
        is_authenticated=False,
        use_llm_router=False,
        collection=faq_collection,
    )
    assert result["response"] == OUVERTURE_ANSWER
