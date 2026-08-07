"""Tests du garde déterministe (`_looks_like_banking`) ajouté à
`agents/router/conversational_understanding.py` pour réduire le risque
qu'une vraie question bancaire soit envoyée par erreur vers le General Agent
(Gemini) si Mistral se trompe.

`data/banking_keywords.json` (maintenu manuellement par l'utilisateur,
jamais modifié/créé/supprimé par ces tests) est chargé une seule fois au
niveau module de `conversational_understanding.py`. Ces tests n'en dépendent
jamais directement pour leurs assertions : ils injectent leurs propres
mots-clés contrôlés via `monkeypatch` (voir `_install_test_keywords`), pour
rester déterministes quel que soit le contenu réel du fichier — voir
`test_real_banking_keywords_file_load_never_raises` en fin de fichier, qui
documente uniquement le contrat de robustesse du chargeur sur le fichier réel.
"""
from __future__ import annotations

import re

from agents.router import conversational_understanding as cu


def _install_test_keywords(monkeypatch, fr=None, darija_latn=None, darija_ar=None):
    """Remplace les mots-clés chargés du module par un jeu contrôlé, en
    reproduisant exactement la même construction (normalisation, regex,
    vocabulaire flou) que le module lui-même — pour tester `_looks_like_banking`
    indépendamment du contenu réel (actuellement invalide, voir en bas de ce
    fichier) de `data/banking_keywords.json`."""
    fr = fr or []
    darija_latn = darija_latn or []
    darija_ar = darija_ar or []
    monkeypatch.setattr(cu, "_BANKING_KEYWORDS", {"fr": fr, "darija_latn": darija_latn, "darija_ar": darija_ar})

    normalized = sorted(
        {cu._normalize_for_banking_check(word) for word in fr + darija_latn if word.strip()},
        key=len,
        reverse=True,
    )
    pattern = re.compile(r"\b(" + "|".join(re.escape(word) for word in normalized) + r")\b") if normalized else None
    monkeypatch.setattr(cu, "_LATIN_KEYWORD_PATTERN", pattern)
    monkeypatch.setattr(cu, "_FUZZY_VOCAB", {token for phrase in normalized for token in phrase.split() if token})


# ---------------------------------------------------------------------------
# (a) mot-clé évident -> "banking", SANS jamais appeler Mistral.
# ---------------------------------------------------------------------------


def test_obvious_fr_keyword_classified_banking_without_calling_llm(monkeypatch):
    _install_test_keywords(monkeypatch, fr=["virement"])

    def _fail(*args, **kwargs):
        raise AssertionError("_classify_with_llm ne doit jamais etre appele quand le garde reconnait un mot-cle")

    monkeypatch.setattr(cu, "_classify_with_llm", _fail)

    result = cu.classify_domain("Je veux faire un virement", use_llm_router=True)
    assert result == {"domain": "banking", "intent": "unclear", "needs_web": False}


def test_obvious_arabic_keyword_classified_banking_without_calling_llm(monkeypatch):
    _install_test_keywords(monkeypatch, darija_ar=["حساب"])

    def _fail(*args, **kwargs):
        raise AssertionError("_classify_with_llm ne doit jamais etre appele quand le garde reconnait un mot-cle")

    monkeypatch.setattr(cu, "_classify_with_llm", _fail)

    result = cu.classify_domain("شحال عندي فحسابي", use_llm_router=True)
    assert result == {"domain": "banking", "intent": "unclear", "needs_web": False}


# ---------------------------------------------------------------------------
# (b) faute de frappe proche d'un mot-clé -> "banking" (tolérance difflib).
# ---------------------------------------------------------------------------


def test_typo_close_to_keyword_classified_banking(monkeypatch):
    _install_test_keywords(monkeypatch, fr=["beneficiaire"])

    def _fail(*args, **kwargs):
        raise AssertionError(
            "_classify_with_llm ne doit jamais etre appele quand le garde reconnait une faute de frappe proche"
        )

    monkeypatch.setattr(cu, "_classify_with_llm", _fail)

    # "beneficiare" (une lettre manquante) : ratio difflib ~0.96, bien au-dessus du seuil 0.82.
    result = cu.classify_domain("qui sont mes beneficiare", use_llm_router=True)
    assert result == {"domain": "banking", "intent": "unclear", "needs_web": False}


def test_short_token_below_four_chars_not_fuzzy_matched(monkeypatch):
    # Un token de moins de 4 caracteres n'est jamais compare via difflib (voir
    # spec) - evite les faux positifs sur des mots courts type "le", "un".
    _install_test_keywords(monkeypatch, fr=["compte"])
    assert cu._looks_like_banking("un abc") is False


# ---------------------------------------------------------------------------
# (c) aucun mot-clé -> comportement existant inchangé.
# ---------------------------------------------------------------------------


def test_no_keyword_match_falls_back_to_llm_when_enabled(monkeypatch):
    _install_test_keywords(monkeypatch, fr=["virement"], darija_latn=["ch7al"], darija_ar=["حساب"])
    monkeypatch.setattr(
        cu,
        "_classify_with_llm",
        lambda *a, **k: {"domain": "general", "intent": "knowledge_question", "needs_web": False},
    )

    result = cu.classify_domain("Qui est Albert Einstein ?", use_llm_router=True)
    assert result == {"domain": "general", "intent": "knowledge_question", "needs_web": False}


def test_no_keyword_match_defaults_to_banking_when_llm_disabled(monkeypatch):
    _install_test_keywords(monkeypatch, fr=["virement"])

    def _fail(*args, **kwargs):
        raise AssertionError("_classify_with_llm ne doit pas etre appele quand use_llm_router=False")

    monkeypatch.setattr(cu, "_classify_with_llm", _fail)

    result = cu.classify_domain("Qui est Albert Einstein ?", use_llm_router=False)
    assert result == {"domain": "banking", "intent": "unclear", "needs_web": False}


# ---------------------------------------------------------------------------
# (d) fichier JSON absent/invalide -> ne fait planter ni le chargeur ni
#     classify_domain.
# ---------------------------------------------------------------------------


def test_load_banking_keywords_missing_file_returns_empty_structure(monkeypatch, tmp_path):
    monkeypatch.setattr(cu, "_BANKING_KEYWORDS_PATH", tmp_path / "does_not_exist.json")
    assert cu._load_banking_keywords() == {"fr": [], "darija_latn": [], "darija_ar": []}


def test_load_banking_keywords_invalid_json_returns_empty_structure(monkeypatch, tmp_path):
    bad_file = tmp_path / "invalid.json"
    bad_file.write_text("ceci n'est pas du JSON valide {{{", encoding="utf-8")
    monkeypatch.setattr(cu, "_BANKING_KEYWORDS_PATH", bad_file)
    assert cu._load_banking_keywords() == {"fr": [], "darija_latn": [], "darija_ar": []}


def test_classify_domain_never_crashes_when_keywords_absent(monkeypatch):
    _install_test_keywords(monkeypatch)  # listes vides -> garde inactif
    result = cu.classify_domain("Quel est mon solde ?", use_llm_router=False)
    assert result == {"domain": "banking", "intent": "unclear", "needs_web": False}


def test_looks_like_banking_never_raises_on_edge_cases():
    assert cu._looks_like_banking("") is False
    assert cu._looks_like_banking("!!! ??? ...") is False


# ---------------------------------------------------------------------------
# État réel de `data/banking_keywords.json` (fourni manuellement par
# l'utilisateur, jamais modifié/créé/supprimé ici). Ce test documente
# uniquement le contrat de robustesse du chargeur sur le fichier réel — il
# doit rester vrai que ce fichier soit corrigé ou non entre-temps.
# ---------------------------------------------------------------------------


def test_real_banking_keywords_file_load_never_raises():
    result = cu._load_banking_keywords()
    assert set(result.keys()) == {"fr", "darija_latn", "darija_ar"}
    assert all(isinstance(value, list) for value in result.values())
