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
from pathlib import Path

import pytest

from agents.agent1_faq import llm_router
from agents.agent1_faq.graph import _merge_faq_candidates, run_agent1
from agents.agent1_faq.rag import (
    _VECTOR_DIM,
    FaqEmbeddingDimensionMismatchError,
    HashingBagOfWordsEmbedding,
    _light_stem,
    _tokenize,
    get_faq_collection,
    search_faq,
)
from scripts.ingest_faq import ingest_faq

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_FAQ_PATH = _REPO_ROOT / "data" / "faq_docs" / "faq.json"

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
# 0. Embedding local : stemming léger + dimension 1024 (voir rag.py).
#    Aucun de ces tests n'appelle Mistral — ils portent exclusivement sur
#    l'embedding déterministe local.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variants",
    [
        ("transaction", "transactions"),
        ("carte", "cartes"),
        ("virement", "virements"),
        ("consulter", "consulte", "consultent"),
        ("compte", "comptes"),
        ("solde", "soldes"),
        ("operation", "operations"),
        ("depense", "depenses"),
        ("beneficiaire", "beneficiaires"),
    ],
)
def test_light_stem_makes_lexical_variants_converge(variants):
    """Toutes les variantes d'un même mot doivent produire la MÊME racine.

    La racine produite n'est pas forcément le singulier correct
    ("carte" -> "cart") : seule la convergence compte, la même transformation
    étant appliquée au document et à la requête."""
    assert len({_light_stem(word) for word in variants}) == 1


@pytest.mark.parametrize(
    "token",
    [
        # Protection 1 — longueur minimale de racine : "mois"/"pays" ne doivent
        # jamais devenir "moi"/"pay" (fusion avec d'autres mots réels).
        "mois",
        "pays",
        "fois",
        "avis",
        # Protection 2 — liste d'invariants (singuliers terminés par "s").
        "frais",
        "temps",
        "cours",
        "especes",
        "interets",
        # Protection 3 — tokens non alphabétiques et mots courts intacts.
        "2026",
        "cih",
        "rib",
    ],
)
def test_light_stem_protects_words_that_must_not_be_altered(token):
    assert _light_stem(token) == token


@pytest.mark.parametrize(("first", "second"), [("mois", "moi"), ("pays", "payer"), ("frais", "frai")])
def test_light_stem_never_merges_distinct_words(first, second):
    """Faux positif à éviter : deux mots de sens différents ne doivent jamais
    se retrouver sur la même racine."""
    assert _light_stem(first) != _light_stem(second)


def test_light_stem_is_deterministic_across_calls():
    """Déterminisme strict : l'ingestion et la recherche tournent dans deux
    processus distincts et doivent produire exactement la même racine."""
    assert [_light_stem("transactions") for _ in range(5)] == ["transaction"] * 5


def test_tokenize_applies_stemming_inside_the_existing_pipeline():
    """Le stemming doit être intégré à `_tokenize` (donc au pipeline
    d'embedding existant), pas ajouté comme un système parallèle."""
    assert _tokenize("Mes transactions et mes cartes") == ["mes", "transaction", "et", "mes", "cart"]
    # Singulier et pluriel produisent la même suite de racines : c'est ce qui
    # rend les deux formulations équivalentes pour l'embedding.
    assert _tokenize("transactions cartes virements") == _tokenize("transaction carte virement")


def test_embedding_now_produces_1024_dimensions():
    assert _VECTOR_DIM == 1024
    vectors = HashingBagOfWordsEmbedding()(["une question de test"])
    assert len(vectors[0]) == 1024


def test_embedding_vector_is_l2_normalized():
    """Non-régression : la normalisation L2 (indispensable à la distance
    cosinus) est conservée malgré le changement de dimension."""
    vector = HashingBagOfWordsEmbedding()(["quels documents pour ouvrir un compte"])[0]
    assert abs(sum(value * value for value in vector) ** 0.5 - 1.0) < 1e-9


def test_stale_collection_is_refused_instead_of_being_used_silently(tmp_path, monkeypatch):
    """PROTECTION CENTRALE : une collection ChromaDB créée par l'ancien
    embedding (nom v1, 256 dimensions) ne doit JAMAIS être réutilisée
    silencieusement — elle doit lever une erreur explicite indiquant la
    marche à suivre.

    La collection obsolète est simulée en réinstallant temporairement
    l'ancienne signature (nom "hashing-bag-of-words", 256 dimensions) pour
    l'ingestion, puis en la rouvrant avec le code courant."""
    import agents.agent1_faq.rag as rag_module

    class _LegacyEmbedding(rag_module.HashingBagOfWordsEmbedding):
        @staticmethod
        def name() -> str:
            return "hashing-bag-of-words"

        def __call__(self, input):  # noqa: A002 — signature imposée par ChromaDB
            return [[0.0] * 255 + [1.0] for _ in input]

    persist_dir = str(tmp_path / "chroma_legacy")
    monkeypatch.setattr(rag_module, "HashingBagOfWordsEmbedding", _LegacyEmbedding)
    legacy = rag_module.get_faq_collection(persist_dir=persist_dir, collection_name="faq_legacy_test")
    legacy.upsert(ids=["x"], documents=["question ancienne"], metadatas=[{"question": "q", "answer": "a"}])
    monkeypatch.undo()
    rag_module._VERIFIED_COLLECTIONS.clear()

    with pytest.raises(FaqEmbeddingDimensionMismatchError) as excinfo:
        rag_module.get_faq_collection(persist_dir=persist_dir, collection_name="faq_legacy_test")

    # Le message doit être actionnable, pas seulement techniquement correct.
    assert "ingest_faq.py" in str(excinfo.value)


def test_freshly_ingested_collection_is_accepted(tmp_path):
    """Contrepartie du test précédent : une collection ingérée avec le code
    courant doit s'ouvrir sans erreur (la garde ne doit pas sur-déclencher)."""
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(json.dumps(FAQ_ENTRIES), encoding="utf-8")
    persist_dir = str(tmp_path / "chroma_fresh")
    ingest_faq(faq_path=faq_path, persist_dir=persist_dir, collection_name="faq_fresh_test")
    collection = get_faq_collection(persist_dir=persist_dir, collection_name="faq_fresh_test")
    assert collection.count() == len(FAQ_ENTRIES)


def test_ingestion_contract_and_stable_ids_are_unchanged(tmp_path):
    """Non-régression du contrat d'ingestion : les IDs fournis restent
    inchangés et une ré-ingestion ne duplique rien, malgré le nouvel
    embedding."""
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(json.dumps(FAQ_ENTRIES), encoding="utf-8")
    persist_dir = str(tmp_path / "chroma_ids")
    first = ingest_faq(faq_path=faq_path, persist_dir=persist_dir, collection_name="faq_ids_test")
    second = ingest_faq(faq_path=faq_path, persist_dir=persist_dir, collection_name="faq_ids_test")
    assert first["collection_count"] == second["collection_count"] == len(FAQ_ENTRIES)
    collection = get_faq_collection(persist_dir=persist_dir, collection_name="faq_ids_test")
    assert sorted(collection.get(include=[])["ids"]) == sorted(entry["id"] for entry in FAQ_ENTRIES)


_LEXICAL_FAQ_ENTRIES = [
    {
        "id": "test-consulter-transactions",
        "question": "Comment consulter les transactions ?",
        "answer": "Les transactions sont consultables depuis l'espace client.",
    },
    {
        "id": "test-virement-fonctionnement",
        "question": "Comment fonctionne un virement bancaire ?",
        "answer": "Un virement transfère des fonds d'un compte à un autre.",
    },
]


@pytest.fixture
def lexical_faq_collection(tmp_path):
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(json.dumps(_LEXICAL_FAQ_ENTRIES), encoding="utf-8")
    persist_dir = str(tmp_path / "chroma_lex")
    ingest_faq(faq_path=faq_path, persist_dir=persist_dir, collection_name="faq_lexical_test")
    return get_faq_collection(persist_dir=persist_dir, collection_name="faq_lexical_test")


@pytest.mark.parametrize(
    ("question", "expected_marker"),
    [
        # Pluriel -> singulier et inversement, sur la question ET la réponse.
        ("Comment consulter la transaction ?", "espace client"),
        ("Comment consulter les transaction ?", "espace client"),
        ("Comment consultent les transactions ?", "espace client"),
        # L'entrée voisine (virement) doit rester distincte malgré le stemming.
        ("Comment fonctionnent les virements bancaires ?", "transfère des fonds"),
    ],
)
def test_lexical_variants_find_the_right_faq_without_mistral(lexical_faq_collection, question, expected_marker):
    """Recherche FAQ SANS Mistral (`use_llm_router=False`, donc chemin
    `search_faq` top-1 brut, sans aucun reranking) : une variation lexicale
    (singulier/pluriel, forme verbale) doit retrouver la bonne entrée grâce au
    stemming — et ne pas rapatrier l'entrée voisine."""
    result = run_agent1(question, collection=lexical_faq_collection, use_llm_router=False)
    assert result["intent"] == "faq_generale"
    assert expected_marker in result["response"]


def test_search_faq_top1_matches_singular_and_plural_identically(lexical_faq_collection):
    """Au niveau du RAG lui-même : la requête au singulier et au pluriel
    doivent renvoyer exactement la même entrée FAQ."""
    singular = search_faq(lexical_faq_collection, "consulter la transaction")
    plural = search_faq(lexical_faq_collection, "consulter les transactions")
    assert singular is not None and plural is not None
    assert singular["question"] == plural["question"] == "Comment consulter les transactions ?"


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


# ---------------------------------------------------------------------------
# 4. Non-regression : "compte bloqué" ne doit jamais renvoyer la FAQ fraude
#    (cause racine identifiée : la FAQ fraude entre dans le pool fusionné de
#    candidats quand la reformulation Mistral se rapproche de la formulation
#    exacte du bon FAQ - corrigé par l'enrichissement de la question faq_100
#    dans data/faq_docs/faq.json + une règle explicite dans
#    llm_router._FAQ_RERANK_SYSTEM_PROMPT). Utilise le VRAI jeu de données FAQ
#    (data/faq_docs/faq.json), pas le corpus réduit ci-dessus - ces cas
#    dépendent des vraies entrées faq_047/faq_053/faq_100.
# ---------------------------------------------------------------------------


@pytest.fixture
def real_faq_collection(tmp_path):
    persist_dir = str(tmp_path / "chroma_real")
    ingest_faq(faq_path=_REAL_FAQ_PATH, persist_dir=persist_dir, collection_name="faq_real_rerank_test")
    return get_faq_collection(persist_dir=persist_dir, collection_name="faq_real_rerank_test")


# Marqueur distinctif de la reponse fraude (faq_053) - jamais le simple mot
# "fraude", qui apparait AUSSI, legitimement, dans la bonne reponse
# "compte bloque" (faq_100 rassure explicitement l'utilisateur : "Ce blocage
# ne signifie pas necessairement une fraude...").
_FRAUD_ANSWER_MARKER = "afin de sécuriser le compte et signaler l'incident"


def test_rerank_prompt_forbids_fraud_candidate_unless_explicitly_mentioned():
    prompt = llm_router._FAQ_RERANK_SYSTEM_PROMPT
    assert "fraude" in prompt.lower()
    assert "JAMAIS" in prompt
    assert "EXPLICITEMENT" in prompt


@pytest.mark.parametrize("message", ["Mon compte est bloqué", "Mon compte est verrouillé"])
def test_account_lock_deterministic_search_never_returns_fraud(real_faq_collection, message):
    # Chemin deterministe pur (use_llm_router=False, aucun Mistral) : deja
    # correct avant ce correctif (recherche top-1 seule), verifie ici en
    # non-regression explicite avec les vraies donnees FAQ.
    result = run_agent1(message, collection=real_faq_collection)
    assert result["intent"] == "faq_generale"
    assert _FRAUD_ANSWER_MARKER not in result["response"].lower()


def test_merged_candidates_never_rank_fraud_above_account_lock_faq(real_faq_collection):
    # Verifie la partie deterministe du correctif (enrichissement de
    # data/faq_docs/faq.json) : meme dans le pool fusionne le plus piege
    # (reformulation tres proche de la formulation exacte du bon FAQ), la
    # fraude ne doit jamais etre le meilleur candidat pour une question de
    # blocage de compte.
    merged = _merge_faq_candidates(
        real_faq_collection,
        ["mon compte est bloque", "Que faire si mon compte est bloque"],
        top_k=7,
    )
    assert merged, "le pool fusionne ne doit jamais etre vide ici"
    assert "fraude" not in merged[0]["question"].lower()


def test_account_lock_with_mocked_mistral_never_returns_fraud_even_when_fraud_is_a_candidate(
    monkeypatch, real_faq_collection
):
    # Reproduit precisement la cause racine : la reformulation Mistral simulee
    # est volontairement proche de la formulation exacte du bon FAQ, ce qui
    # fait entrer la fraude dans le pool fusionne (voir test precedent). Le
    # reranking simule ici l'application CORRECTE de la nouvelle regle du
    # prompt (jamais l'index de la fraude) - verifie que `_answer_faq_node`
    # (inchange) restitue bien la reponse correspondante, jamais celle de la
    # fraude.
    monkeypatch.setattr(llm_router, "extract_faq_topic", lambda *a, **k: "Que faire si mon compte est bloqué")
    monkeypatch.setattr(
        llm_router,
        "rerank_faq_candidates",
        lambda question, candidates, **k: next(
            i for i, c in enumerate(candidates) if "fraude" not in c["question"].lower()
        ),
    )
    result = run_agent1("Mon compte est bloqué", collection=real_faq_collection, use_llm_router=True)
    assert result["intent"] == "faq_generale"
    assert _FRAUD_ANSWER_MARKER not in result["response"].lower()


def test_explicit_fraud_report_can_still_use_fraud_faq(monkeypatch, real_faq_collection):
    # Le correctif ne doit jamais rendre la FAQ fraude inaccessible : une
    # vraie mention de fraude doit toujours pouvoir l'utiliser. Simule aussi
    # `route_with_llm` (decision de bucket) : sans ce mock, le repli
    # deterministe classerait ce message "personal_data" ("mon compte" y
    # matche _PERSONAL_DATA_PATTERNS) avant meme d'atteindre le noeud FAQ -
    # ce test verifie specifiquement le chemin ou Mistral classe correctement
    # la question en faq_search, comme le prevoit le prompt existant.
    monkeypatch.setattr(
        llm_router,
        "route_with_llm",
        lambda *a, **k: {
            "intent": "faq_search",
            "category": None,
            "period": None,
            "card_fields": [],
            "faq_query": "Que faire si je soupçonne une fraude sur mon compte",
        },
    )
    monkeypatch.setattr(
        llm_router, "extract_faq_topic", lambda *a, **k: "Que faire si je soupçonne une fraude sur mon compte"
    )
    result = run_agent1(
        "J'ai détecté une fraude sur mon compte", collection=real_faq_collection, use_llm_router=True
    )
    assert result["intent"] == "faq_generale"
    assert _FRAUD_ANSWER_MARKER in result["response"].lower()
