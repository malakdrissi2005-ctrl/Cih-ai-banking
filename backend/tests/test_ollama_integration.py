"""Vérification ponctuelle avec un Ollama réellement démarré (`mistral` tiré).

Désactivée par défaut : la suite automatisée reste rapide et déterministe en
mockant systématiquement `httpx.post` (voir `test_llm_router.py`), jamais un
vrai service Ollama. Ce fichier documente et vérifie manuellement la mesure de
performance citée dans `agents/agent1_faq/llm_router.py` (chargement à froid
~45-53s, appel à chaud ~6,5-7s) et confirme que `warm_up()` + le nouveau
timeout par défaut (10s) suffisent à obtenir une réponse LLM réelle sans
tomber en repli déterministe.

Pour l'exécuter (Ollama démarré, `ollama pull mistral` déjà fait) :

    RUN_OLLAMA_INTEGRATION=1 OLLAMA_BASE_URL=http://localhost:11434 \
    OLLAMA_MODEL=mistral pytest backend/tests/test_ollama_integration.py -v -s
"""
from __future__ import annotations

import os
import time

import pytest

from agents.agent1_faq import llm_router

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_INTEGRATION") != "1",
    reason="Intégration Ollama réelle désactivée par défaut (voir docstring du module).",
)


def test_warm_up_succeeds_against_real_ollama():
    assert llm_router.is_llm_configured(), "OLLAMA_BASE_URL/OLLAMA_MODEL doivent être définis pour ce test."
    assert llm_router.warm_up(timeout=90.0) is True


def test_route_with_llm_succeeds_within_default_timeout_once_warm():
    # Le modèle est supposé déjà chaud après le test précédent (même process
    # Ollama, keep_alive actif) — reproduit le scénario réel du backend
    # (réchauffement au démarrage, puis messages utilisateur ultérieurs).
    start = time.time()
    result = llm_router.route_with_llm(
        "Combien ai-je dépensé en restaurant ce mois-ci ?", "combien ai-je depense en restaurant ce mois-ci", "fr"
    )
    elapsed = time.time() - start

    assert result is not None, "Le routeur ne doit pas tomber en repli une fois le modèle chaud."
    assert result["intent"] == "spending_analysis"
    assert elapsed < llm_router._DEFAULT_TIMEOUT_SECONDS + 3, (
        f"Appel à chaud anormalement lent ({elapsed:.1f}s) — re-vérifier la mesure de performance documentée."
    )


# ---------------------------------------------------------------------------
# Vérification réelle des 5 formulations qui mettaient en échec la
# classification déterministe seule (fautes de frappe, darija arabe/Arabizi) —
# voir graph.py::_classify_intent_node (Mistral appelé en premier). Le prompt
# (`llm_router._SYSTEM_PROMPT`) inclut désormais des exemples few-shot pour ces
# formulations exactes.
#
# Mesuré manuellement (voir rapport) : ~19/20 appels réels corrects sur ces 5
# phrases après ajout des exemples (contre 3/5 phrases fiables avant). Le LLM
# reste un modèle de langage non déterministe : ce test tolère jusqu'à 2
# tentatives par phrase avant d'échouer, plutôt que d'exiger un succès au
# premier coup, pour éviter un flake ponctuel sur une variation d'échantillonnage.
# ---------------------------------------------------------------------------

FIVE_PHRASES = [
    "حال عندي فالحساب",
    "شحال عندي فالحساب",
    "ch7al 3ndi fl compte",
    "kel est mon sold",
    "combien jai",
]


@pytest.mark.parametrize("message", FIVE_PHRASES)
def test_five_phrases_return_balance_query_against_real_mistral(message):
    last_result = None
    for _attempt in range(2):
        last_result = llm_router.route_with_llm(message, message, "fr")
        if last_result is not None and last_result.get("intent") == "balance_query":
            return
    pytest.fail(
        f"'{message}' n'a pas donné 'balance_query' en 2 tentatives réelles (dernier résultat : {last_result!r})"
    )


# ---------------------------------------------------------------------------
# Vérification réelle du pipeline FAQ/RAG complet (extract_faq_topic +
# retrieval hybride `_merge_faq_candidates` + `rerank_faq_candidates`) contre
# le vrai corpus FAQ ingéré (`data/faq_docs/faq.json`, ~98 entrées), pour la
# phrase avec faute de frappe de la demande.
#
# Mesuré manuellement (calibration à 3 tentatives par phrase, voir rapport) :
# avec `_FAQ_CANDIDATE_TOP_K=7`, "je veux ouvre un comrt" est la formulation
# la PLUS fiable du lot testé (3/3) — contrairement à "comment créer un
# compte bancaire" (0/3), dont le vocabulaire ("créer un compte") entre en
# collision avec une entrée FAQ existante ("Comment créer un espace client ?")
# sur cet embedding "sac de mots haché" (voir rag.py). Le repli déterministe
# (candidat le mieux classé par distance ChromaDB) reste garanti dans tous
# les cas — jamais une exception, jamais une réponse inventée.
# ---------------------------------------------------------------------------

_OUVERTURE_COMPTE_MARKERS = [
    "pièce d'identité en cours de validité",  # "Quels documents ... pour ouvrir un compte ?"
    "ouverture de compte à distance",  # "Peut-on ouvrir un compte en ligne ... ?"
    "généralement nécessaire d'ouvrir un compte",  # "Comment devenir client de la banque ?"
    "délai d'ouverture varie",  # "Combien de temps prend l'ouverture d'un compte ?"
]


def test_typo_open_account_question_returns_ouverture_compte_answer_against_real_stack():
    from agents.agent1_faq.graph import run_agent1
    from agents.agent1_faq.rag import get_faq_collection

    collection = get_faq_collection()
    last_response = None
    for _attempt in range(2):
        result = run_agent1(
            "je veux ouvre un comrt", is_authenticated=False, use_llm_router=True, collection=collection
        )
        last_response = result["response"]
        if any(marker in last_response for marker in _OUVERTURE_COMPTE_MARKERS):
            return
    pytest.fail(
        f"'je veux ouvre un comrt' n'a pas donné de réponse ouverture_compte en 2 tentatives "
        f"(dernière réponse : {last_response!r})"
    )
