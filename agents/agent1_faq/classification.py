"""Classification déterministe de l'intention du message entrant.

Implémente le nœud `classify_intent` décrit dans
`DocsContext/02_architecture_multi_agents.md` (§2, §2.4). La classification
est purement programmatique (regex sur texte normalisé) et n'est **jamais**
laissée à l'appréciation d'un LLM — conformément à la règle du même document
selon laquelle le routage vers une action sensible est appliqué par une
condition explicite du graphe, pas par un modèle de langage.

Ce module expose deux fonctions à responsabilité distincte :
- `detect_sensitive_operation` : la SEULE utilisée par le Security Guard
  (`graph.py::_security_guard_node`) — détecte uniquement `virement`/
  `compte_action`, structurellement incapable de retourner `personal_data`/
  `faq_generale`. Le Security Guard protège l'accès, il ne choisit jamais
  l'intention (voir CLAUDE.md §2, §13 règle 5).
- `classify_intent` : le classificateur déterministe COMPLET (4 catégories),
  utilisé uniquement comme repli de secours (`graph.py::_classify_fallback_node`)
  quand Mistral (le classificateur principal, voir `llm_router.py`) est
  indisponible/désactivé/en échec.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal, Optional

Intent = Literal["virement", "compte_action", "personal_data", "faq_generale"]


def _normalize(text: str) -> str:
    """Minuscule, sans accents, pour un matching robuste et déterministe."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


# Détection des demandes de virement — vérifiée en premier : une phrase qui
# mentionne à la fois un virement et une notion de compte ("virer depuis mon
# compte") doit être classée comme "virement", pas comme "personal_data".
#
# Un simple mot-clé ("virement", "virer"...) ne suffit PAS à lui seul : la FAQ
# publique contient légitimement des questions générales sur le fonctionnement
# des virements (ex. "Comment fonctionne un virement bancaire ?", "Quel est le
# délai d'un virement ?"). Ces mots-clés ne déclenchent "virement" que s'ils
# sont accompagnés d'un marqueur de demande explicite (1re personne/impératif)
# ou d'un montant chiffré — sinon, la question reste une question publique.
_VIREMENT_KEYWORD_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\bvirements?\b",
        r"\bvirer\b",
        r"\bvire\b",
        r"\btransferts?\b",
        r"\btransferer\b",
    )
]

# Ces tournures encodent déjà une demande d'action et suffisent seules.
_VIREMENT_DIRECT_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\benvoyer\b.*\b(argent|dh|mad|dirhams?)\b",
        r"\benvoie\b.*\b(argent|dh|mad|dirhams?)\b",
    )
]

_TRANSFER_INTENT_MARKERS = [
    re.compile(pattern)
    for pattern in (
        r"\bje veux\b",
        r"\bje voudrais\b",
        r"\baimerais\b",
        r"\bpeux-tu\b",
        r"\bpouvez-vous\b",
        r"\bmerci de\b",
        r"\bstp\b",
        r"\bsvp\b",
    )
]

_AMOUNT_PATTERN = re.compile(r"\d+\s*(dh|mad|dirhams?)\b")

# Détection des demandes de modification bancaire (plafond, blocage de carte)
# — comme le virement, ces demandes ne sont jamais traitées (voir CLAUDE.md :
# "Ce service n'est pas disponible pour le moment"), quel que soit l'état
# d'authentification. Un simple verbe+"carte"/"plafond" ne suffit PAS à lui
# seul : la FAQ publique contient légitimement des questions de procédure
# générale ("Comment bloquer une carte bancaire ?"). Ces mots-clés ne
# déclenchent "compte_action" que s'ils sont accompagnés d'un marqueur de
# demande explicite ou d'un possessif ("ma carte", "mon plafond") — même
# principe que pour `_VIREMENT_KEYWORD_PATTERNS` ci-dessus.
_ACCOUNT_ACTION_KEYWORD_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\baugmente[r]?\b.{0,20}\bplafond\b",
        r"\bplafond\b.{0,20}\baugmente[r]?\b",
        r"\brelever\b.{0,20}\bplafond\b",
        r"\bmodifier\b.{0,20}\bplafond\b",
        r"\bbloque[r]?\b.{0,20}\bcarte\b",
        r"\bcarte\b.{0,20}\bbloque[r]?\b",
        r"\bdebloque[r]?\b.{0,20}\bcarte\b",
        r"\bcarte\b.{0,20}\bdebloque[r]?\b",
    )
]

_ACCOUNT_ACTION_POSSESSIVE_PATTERNS = [
    re.compile(pattern) for pattern in (r"\bma carte\b", r"\bmon plafond\b")
]

# Certaines questions FAQ publiques bien réelles sont formulées avec un
# possessif générique ("ma carte", "mon compte") sans être des demandes de
# lecture de données personnelles réelles (ex. "Que faire si ma carte est
# perdue ?", "Comment modifier les informations liées à mon compte ?"). Ces
# tournures procédurales ("comment...", "que faire si...") ne déclenchent
# jamais "personal_data" à elles seules. Limite connue : une question
# authentiquement personnelle formulée "Comment consulter mon solde ?"
# resterait à tort classée comme FAQ publique — non couvert par les
# exemples de ce projet, qui utilisent "Quel est mon solde ?".
_PROCEDURAL_FAQ_PREFIX = re.compile(r"^(comment|que faire)\b")

# Détection des questions personnelles. Volontairement restreint à des
# termes intrinsèquement personnels et possessifs (solde, mes transactions,
# ma carte, mon salaire...) — jamais un simple mot comme "compte" ou "carte"
# seuls, qui apparaissent aussi dans des questions publiques légitimes
# ("ouvrir un compte CIH", "quels types de cartes existent").
_PERSONAL_DATA_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\bsoldes?\b",
        r"\bmon compte\b",
        r"\bmes comptes\b",
        r"\btransactions?\b",
        r"\bhistorique\b",
        r"\bbeneficiaires?\b",
        r"\breleve\b",
        r"\bma carte\b",
        r"\bsalaires?\b",
        r"\bprelevements?\b",
        r"\bmes\b[\w\s]{0,20}\boperations?\b",
        r"\bmes\b[\w\s]{0,20}\bpaiements?\b",
        r"\bdepenses?\b",
        r"\bconsacres?\b",
        r"\bme reste\b",
        r"\bmon argent\b",
    )
]


SensitiveOperation = Literal["virement", "compte_action"]


def detect_sensitive_operation(message: str) -> Optional[SensitiveOperation]:
    """Détection ISOLÉE des opérations sensibles (virement, action de compte).

    La SEULE fonction appelée par le Security Guard (`graph.py::_security_guard_node`) :
    n'évalue et ne connaît jamais les patterns `personal_data`/`faq_generale`
    (`_PERSONAL_DATA_PATTERNS`, `_PROCEDURAL_FAQ_PREFIX` ci-dessous n'existent
    même pas dans cette fonction) — structurellement incapable de retourner
    autre chose que `"virement"`/`"compte_action"`/`None`, jamais une intention
    de classification (voir CLAUDE.md §2, §13 règle 5 : le Security Guard
    protège l'accès, il ne choisit jamais l'intention).
    """
    normalized = _normalize(message)

    if any(pattern.search(normalized) for pattern in _VIREMENT_DIRECT_PATTERNS):
        return "virement"

    if any(pattern.search(normalized) for pattern in _VIREMENT_KEYWORD_PATTERNS):
        has_intent_marker = any(pattern.search(normalized) for pattern in _TRANSFER_INTENT_MARKERS)
        has_amount = bool(_AMOUNT_PATTERN.search(normalized))
        if has_intent_marker or has_amount:
            return "virement"
        # Mention informative du terme "virement"/"transfert", sans demande
        # explicite : traité comme une question publique (voir commentaire
        # au-dessus de _VIREMENT_KEYWORD_PATTERNS).

    if any(pattern.search(normalized) for pattern in _ACCOUNT_ACTION_KEYWORD_PATTERNS):
        has_intent_marker = any(pattern.search(normalized) for pattern in _TRANSFER_INTENT_MARKERS)
        has_possessive = any(pattern.search(normalized) for pattern in _ACCOUNT_ACTION_POSSESSIVE_PATTERNS)
        if has_intent_marker or has_possessive:
            return "compte_action"
        # Question procédurale publique (ex. "Comment bloquer une carte bancaire ?")
        # sans demande explicite ni possessif : reste une question publique.

    return None


def classify_intent(message: str) -> Intent:
    """Retourne "virement", "compte_action", "personal_data" ou "faq_generale" (repli).

    Repli déterministe COMPLET, utilisé uniquement par `classify_fallback`
    (`graph.py`) quand Mistral est indisponible/désactivé/en échec — jamais
    par le Security Guard, qui appelle exclusivement `detect_sensitive_operation`
    ci-dessus. Mistral reste le classificateur principal pour `personal_data`/
    `faq_generale` (voir `llm_router.py`, `graph.py::_llm_router_node`) : ce
    repli n'est qu'un filet de sécurité en cas d'échec du LLM, jamais un
    classificateur concurrent en fonctionnement normal.
    """
    sensitive = detect_sensitive_operation(message)
    if sensitive is not None:
        return sensitive

    normalized = _normalize(message)
    is_procedural_faq_phrasing = bool(_PROCEDURAL_FAQ_PREFIX.match(normalized))
    if not is_procedural_faq_phrasing and any(pattern.search(normalized) for pattern in _PERSONAL_DATA_PATTERNS):
        return "personal_data"

    return "faq_generale"
