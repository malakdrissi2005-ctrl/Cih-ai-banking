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

# Questions DÉFINITIONNELLES ("qu'est-ce qu'une transaction bancaire ?",
# "c'est quoi un découvert ?", "que signifie le solde comptable ?") : elles
# portent sur un CONCEPT bancaire général, jamais sur les données réelles du
# client — ce sont des questions de FAQ publique.
#
# Même rôle que `_PROCEDURAL_FAQ_PREFIX` ci-dessus, pour une autre famille de
# tournures. Corrige un faux positif PRÉ-EXISTANT mesuré avant enrichissement :
# "Qu'est-ce qu'une transaction bancaire ?" était classé `personal_data` à
# cause de `\btransactions?\b` (`_PERSONAL_DATA_PATTERNS`), et exigeait donc
# une connexion pour une simple question de vocabulaire.
#
# Volontairement restreint aux tournures suivies d'un ARTICLE INDÉFINI/DÉFINI
# ("qu'est-ce qu'un/une", "c'est quoi un/une") : une question possessive
# ("c'est quoi mon solde ?") n'est jamais interceptée et reste personnelle.
_DEFINITIONAL_QUESTION_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"^qu'?est[- ]?ce qu'?une?\b",
        r"^qu'?est[- ]?ce que l[ae']",
        r"^c'?est quoi une?\b",
        r"^c'?est quoi l[ae']",
        r"\bque signifie\b",
        r"\bqu'?entend[- ]on par\b",
        r"\bdefinition d",
        r"\ba quoi (sert|servent)\b",
    )
]


def _is_definitional_question(normalized_text: str) -> bool:
    """Détecte une question de définition/vocabulaire bancaire — voir
    commentaire de `_DEFINITIONAL_QUESTION_PATTERNS`. Déterministe, aucun appel
    LLM, utilisée uniquement par `classify_intent`."""
    return any(pattern.search(normalized_text) for pattern in _DEFINITIONAL_QUESTION_PATTERNS)

# Signalement d'incident d'accès/blocage de COMPTE (ex. "mon compte est
# bloqué", "mon compte est verrouillé", "mon accès est bloqué", "je n'arrive
# plus à accéder à mon compte", "mon compte ne marche plus") — même principe
# que pour les incidents CARTE (voir `card_query` dans `graph.py`, qui exclut
# déjà "carte bloquée"/"carte perdue" de toute lecture de donnée personnelle) :
# un signalement de panne/blocage est une question de PROCÉDURE, répondue par
# la FAQ publique, jamais par une lecture de `banking_db` — aucun outil
# existant n'expose de statut de blocage de compte à ce jour. Sans cette
# exclusion, `\bmon compte\b` ci-dessous (`_PERSONAL_DATA_PATTERNS`) faisait
# basculer ces messages vers "personal_data" dans le repli déterministe
# (`classify_fallback`), alors que Mistral (`llm_router.py`) les classe
# correctement en `faq_search` — incohérence entre les deux chemins, corrigée
# ici pour que le repli déterministe soit fiable même sans LLM. Volontairement
# restreint aux tournures d'incident : ne doit jamais intercepter une
# véritable question de compte différente (ex. "Quel est le solde de mon
# compte ?", toujours couvert par `_PERSONAL_DATA_PATTERNS` ci-dessous).
_ACCOUNT_LOCK_INCIDENT_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\bcompte\b.{0,20}\b(bloque|verrouille|suspendu)\b",
        r"\b(bloque|verrouille|suspendu)\b.{0,20}\bcompte\b",
        r"\bacces\b.{0,20}\bbloque\b",
        r"\bbloque\b.{0,20}\bacces\b",
        r"\barrive\s+(plus|pas)\s+a\s+(acceder|me connecter|entrer)\b",
        r"\bcompte\b.{0,20}\bne (marche|fonctionne)\s+(plus|pas)\b",
    )
]


def _is_account_lock_incident(normalized_text: str) -> bool:
    """Détecte un signalement d'incident d'accès/blocage de compte — voir
    commentaire de `_ACCOUNT_LOCK_INCIDENT_PATTERNS` ci-dessus. Déterministe,
    aucun appel LLM, utilisée uniquement par `classify_intent`."""
    return any(pattern.search(normalized_text) for pattern in _ACCOUNT_LOCK_INCIDENT_PATTERNS)


# Signalement de FRAUDE/incident de sécurité (ex. "j'ai détecté une fraude sur
# mon compte", "mon compte a été piraté", "activité suspecte sur mon compte",
# "je ne reconnais pas cette transaction") — même principe que les incidents
# carte/compte ci-dessus : un signalement d'incident est une question de
# PROCÉDURE (répondue par la FAQ publique, voir `faq_053` dans
# `data/faq_docs/faq.json`), jamais une lecture de donnée personnelle réelle.
# Sans cette exclusion, `\bmon compte\b`/`\btransactions?\b`
# (`_PERSONAL_DATA_PATTERNS`) faisaient basculer ces messages vers
# "personal_data" (authentification requise) au lieu de donner immédiatement
# une consigne de sécurité publique, urgente par nature.
_FRAUD_INCIDENT_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\bfraudes?\b",
        r"\bfrauduleuse?\b",
        r"\bpirate[e]?\b",
        r"\bpiratage\b",
        r"\busurpation\b",
        r"\bcompromis(e)?\b",
        r"\bactivite\b.{0,20}\bsuspecte\b",
        r"\bne reconnais pas\b.{0,30}\btransaction\b",
        r"\btransaction\b.{0,30}\bne reconnais pas\b",
        r"\btransaction\b.{0,10}\bsuspecte\b",
    )
]


def _is_fraud_incident(normalized_text: str) -> bool:
    """Détecte un signalement de fraude/incident de sécurité — voir commentaire
    de `_FRAUD_INCIDENT_PATTERNS` ci-dessus. Déterministe, aucun appel LLM,
    utilisée uniquement par `classify_intent`."""
    return any(pattern.search(normalized_text) for pattern in _FRAUD_INCIDENT_PATTERNS)


# Signalement d'incident CARTE (perte, vol, panne) — même principe que les
# incidents compte/fraude ci-dessus : un signalement de perte/vol/panne de
# carte est une question de PROCÉDURE (voir `card_query` dans `graph.py`, qui
# applique déjà cette distinction côté Mistral via
# `_requests_personal_card_info`), jamais une lecture de donnée personnelle.
# Sans cette exclusion, `\bma carte\b` (`_PERSONAL_DATA_PATTERNS`) faisait
# basculer ces messages vers "personal_data" dans le repli déterministe
# (`classify_fallback`), alors que Mistral classe correctement "J'ai perdu ma
# carte" en `card_query` (traité ensuite comme FAQ par `graph.py`, sauf
# demande explicite d'info précise) — incohérence entre les deux chemins,
# corrigée ici pour que le repli déterministe soit fiable même sans LLM.
# Volontairement exclu si le message demande EN PLUS une information précise
# (numéro, statut, plafond) — reste alors "personal_data", même logique que
# `_requests_personal_card_info` déjà utilisée par `graph.py`, reproduite ici
# de façon autonome (ce module ne dépend jamais de `graph.py`).
_CARD_INCIDENT_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\bcarte\b.{0,20}\b(perdu|perdue|vole|volee)\b",
        r"\b(perdu|perdue|vole|volee)\b.{0,20}\bcarte\b",
        r"\bcarte\b.{0,20}\bne (marche|fonctionne)\s+(plus|pas)\b",
    )
]

_CARD_PRECISE_INFO_PATTERNS = [
    re.compile(pattern) for pattern in (r"\bnumero\b", r"\binformations?\b", r"\bstatut\b", r"\bplafond\b")
]


def _is_card_incident(normalized_text: str) -> bool:
    """Détecte un signalement d'incident carte (perte, vol, panne) — voir
    commentaire de `_CARD_INCIDENT_PATTERNS` ci-dessus. `False` si le message
    demande en plus une information précise (numéro/statut/plafond) : reste
    alors "personal_data". Déterministe, aucun appel LLM, utilisée uniquement
    par `classify_intent`."""
    if not any(pattern.search(normalized_text) for pattern in _CARD_INCIDENT_PATTERNS):
        return False
    return not any(pattern.search(normalized_text) for pattern in _CARD_PRECISE_INFO_PATTERNS)


# ---------------------------------------------------------------------------
# Généralisation architecturale (voir échange "je ne veux plus corriger les
# erreurs question par question") : les trois exclusions ci-dessus
# (_is_account_lock_incident/_is_fraud_incident/_is_card_incident) sont des
# LISTES DE PHRASES SPÉCIFIQUES — chaque nouvelle façon de signaler un
# problème (compte, carte, code SMS, accès, connexion, ou autre chose demain)
# exigerait une nouvelle liste. Preuve : "j'ai un souci avec ma carte" ou
# "mon compte a un problème de connexion" ne sont couverts par AUCUNE des
# trois listes ci-dessus et retombaient à tort en "personal_data".
#
# Ce détecteur remplace l'approche "une liste par sujet" par une grille
# combinatoire : un petit lexique FERMÉ et générique de mots-problème
# (bloqué, perdu, volé, en panne, souci, problème, ne marche pas...) croisé
# avec un petit ensemble de sujets bancaires (compte, carte, accès, connexion,
# code, application, mot de passe). Le français a un nombre restreint de
# façons de dire "problème" — contrairement au nombre quasi infini de façons
# de décrire un incident précis — donc cette grille généralise à toute
# formulation jamais vue, sans qu'aucune nouvelle liste spécifique soit
# nécessaire à l'avenir. Les trois exclusions ci-dessus restent en place
# (filet de sécurité redondant, déjà testé) ; ce détecteur est le mécanisme
# qui généralise réellement.
_GENERIC_PROBLEM_WORDS = (
    "bloque", "bloquee", "verrouille", "verrouillee", "suspendu", "suspendue",
    "perdu", "perdue", "vole", "volee", "panne", "souci", "probleme",
    "casse", "cassee", "marche pas", "marche plus", "fonctionne pas",
    "fonctionne plus", "erreur", "impossible",
)
_GENERIC_PROBLEM_SUBJECTS = (
    "compte", "carte", "acces", "connexion", "code", "application", "mot de passe",
)
_GENERIC_PROBLEM_WORD_PATTERN = re.compile(r"\b(" + "|".join(_GENERIC_PROBLEM_WORDS) + r")\b")
_GENERIC_PROBLEM_SUBJECT_PATTERN = re.compile(r"\b(" + "|".join(_GENERIC_PROBLEM_SUBJECTS) + r")\b")


def _is_generic_problem_report(normalized_text: str) -> bool:
    """Détecte tout signalement de problème générique : simple co-présence
    d'un sujet bancaire et d'un mot-problème dans le message, sans exigence de
    proximité — une question bancaire courte qui mentionne les deux n'est, en
    pratique, jamais une coïncidence. Voir commentaire ci-dessus.
    Déterministe, aucun appel LLM, utilisée uniquement par `classify_intent`."""
    return bool(_GENERIC_PROBLEM_SUBJECT_PATTERN.search(normalized_text)) and bool(
        _GENERIC_PROBLEM_WORD_PATTERN.search(normalized_text)
    )


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
        # --- Formulations naturelles de synthèse personnelle (ajout ciblé) ---
        # Mesuré avant ajout : ces trois tournures étaient les SEULES du lot
        # étudié à tomber à tort dans `faq_generale` — "details de mon compte",
        # "apercu de mon compte", "combien il me reste" et "point sur mes
        # comptes" atteignaient déjà `personal_data` via `\bmon compte\b`/
        # `\bmes comptes\b`/`\bme reste\b` ci-dessus, et n'ont donc demandé
        # aucun pattern supplémentaire ici.
        #
        # Faux positifs vérifiés contre les 100 entrées réelles de
        # `data/faq_docs/faq.json` avant ajout : 0 occurrence de
        # "recapitulatif", 0 de "mes finances", 0 de "situation financiere".
        # Volontairement NON ajoutés car trop génériques et à risque de faux
        # positif sur une FAQ publique future : "resume", "bilan", "apercu" et
        # "details" seuls — ces mots ne basculent en `personal_data` que
        # lorsqu'ils accompagnent un possessif déjà couvert plus haut
        # ("les details de mon compte" -> `\bmon compte\b`).
        #
        # `\bmes finances\b` (et non `\bfinances?\b`) : la frontière de mot
        # empêche toute collision avec "financement", présent dans la FAQ
        # publique réelle ("solutions de financement ou de crédit").
        r"\brecapitulatif\b",
        r"\brecaps?\b",
        r"\bmes finances\b",
        r"\bsituation financiere\b",
        # --- Enrichissement : montant/somme disponible, mouvements, paiements
        # Formulations naturelles mesurées comme tombant à tort dans
        # `faq_generale` avant ajout. Toutes vérifiées : 0 occurrence dans les
        # 100 entrées réelles de `data/faq_docs/faq.json`.
        #
        # Chaque pattern exige un ANCRAGE personnel (possessif "mon", tournure
        # "ai-je", ou qualificatif "disponible"/"restant") — jamais le mot nu
        # "montant", "somme", "avoir" ou "mouvement", qui apparaissent
        # légitimement dans des questions publiques.
        r"\bmon avoir\b",
        r"\bmontant (disponible|restant)\b",
        r"\bsomme\b[\w\s]{0,15}\bdisponible\b",
        r"\bai-je encore\b",
        r"\bmes\b[\w\s]{0,20}\bmouvements?\b",
        r"\bpaiements?\b[\w\s]{0,15}\bai-je\b",
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

    if (
        _is_account_lock_incident(normalized)
        or _is_fraud_incident(normalized)
        or _is_card_incident(normalized)
        or _is_generic_problem_report(normalized)
    ):
        return "faq_generale"

    # Deux familles de tournures PUBLIQUES par nature, évaluées avant tout
    # pattern personnel : question de procédure ("comment...", "que faire...")
    # et question de définition ("qu'est-ce qu'une transaction bancaire ?").
    is_public_phrasing = bool(_PROCEDURAL_FAQ_PREFIX.match(normalized)) or _is_definitional_question(normalized)
    if not is_public_phrasing and any(pattern.search(normalized) for pattern in _PERSONAL_DATA_PATTERNS):
        return "personal_data"

    return "faq_generale"
