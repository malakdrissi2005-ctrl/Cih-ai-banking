"""Résolution COMPOSITIONNELLE et déterministe d'une demande de donnée bancaire personnelle.

POURQUOI CE MODULE EXISTE
=========================
Trois formulations équivalentes donnaient trois réponses différentes :

    « je veux voir mon rib »      -> FAQ « réinitialisation de mot de passe »
    « je veux connaitre mon rib » -> solde total
    « Quel est mon RIB ? »        -> définition publique d'un RIB

Le classificateur déterministe (`classification.classify_intent`) répondait
pourtant correctement aux trois. Le problème n'était donc pas le vocabulaire,
mais la HIÉRARCHIE : Mistral est le classificateur principal du graphe et
aucune règle déterministe ne pouvait le contredire. Une phrase parfaitement
écrite pouvait ainsi être moins bien comprise qu'une phrase mal orthographiée
tombée dans le repli déterministe — exactement l'inverse du comportement
attendu.

Ce module fournit la brique manquante : une reconnaissance **compositionnelle**
évaluée AVANT tout appel au LLM, dont la décision est finale.

LE MODÈLE COMPOSITIONNEL
========================
Aucune phrase complète n'est codée en dur. Une demande est reconnue par la
COMBINAISON de quatre familles de marqueurs indépendantes et réutilisables :

1. `entité bancaire`   — rib, iban, numéro de compte, solde, opérations…
2. `marqueur de possession` — mon, ma, mes, dyali, dyalti, ديالي…
3. `verbe / forme interrogative` — voir, montrer, donner, connaître, quel est…
4. `marqueur de définition` — qu'est-ce que, définition, à quoi sert…

Règles appliquées, dans cet ordre :

- entité + possession                      -> demande PERSONNELLE (décision finale)
- marqueur de définition SANS possession   -> question PUBLIQUE (FAQ/RAG)
- entité + verbe de demande, sans possession ni définition
                                           -> demande PERSONNELLE implicite
                                              (« RIB de mon compte » est déjà
                                              couvert par la possession ;
                                              ici : « afficher le rib »)
- rien de tout cela                        -> non résolu, le graphe continue

La possession l'emporte TOUJOURS sur la définition : « c'est quoi mon rib »
est une demande personnelle, pas une demande d'encyclopédie.

MULTILINGUE
===========
Les lexiques couvrent le français, la darija en caractères arabes et la darija
latine (arabizi). Le pipeline normalise déjà la darija vers un français
canonique (`darija_normalization`), mais ce module reste volontairement capable
de reconnaître les marqueurs d'origine : il est ainsi correct que la
normalisation soit appliquée ou non, et une future lacune de normalisation ne
peut plus faire échouer la reconnaissance.

CE MODULE NE FAIT JAMAIS
========================
- aucun accès base de données, aucun accès ChromaDB, aucun appel réseau ;
- aucune décision d'authentification (c'est `graph._route_decision_node`, à
  partir de la session serveur, jamais de ce texte) ;
- aucune exposition de valeur bancaire : il ne manipule que des libellés.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


def _normalize(text: str) -> str:
    """Minuscule sans accents — identique à `classification._normalize`.

    Volontairement NON destructif pour l'arabe : `unicodedata.combining`
    retirerait les diacritiques arabes, mais les lettres de base subsistent et
    les lexiques arabes ci-dessous sont écrits sans diacritique.
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


# ---------------------------------------------------------------------------
# 1. ENTITÉS BANCAIRES
#
# Chaque entité porte la sous-intention que `banking_answers` sait déjà traiter.
# Volontairement limité aux entités qui désignent sans ambiguïté une DONNÉE à
# consulter. « carte » seul en est absent : « j'ai perdu ma carte » est un
# incident (procédure, FAQ publique), pas une demande de donnée personnelle —
# c'est pourquoi seule une facette précise de la carte (numéro, statut,
# plafond, expiration) est listée.
# ---------------------------------------------------------------------------
ACCOUNT_IDENTIFIERS = "account_identifiers"
CARD_NUMBER = "card_number"
CARD_INFORMATION = "card_information"
BALANCE = "balance"
TRANSACTIONS = "transactions"
BENEFICIARIES = "beneficiaries"

# ---------------------------------------------------------------------------
# PLAFONDS DE CARTE — lexiques réutilisables, SOURCE UNIQUE.
#
# Déclarés ici plutôt que dans `banking_answers` pour deux raisons : la
# reconnaissance d'entité (ce module) et le choix des champs à renvoyer
# (`banking_answers`) doivent s'accorder exactement, et `banking_answers`
# importe déjà ce module — l'inverse créerait un cycle.
#
# Un plafond se dit rarement « plafond ». La formulation la plus naturelle est
# la CAPACITÉ : « combien puis-je retirer ». Elle exige « combien » ET un verbe
# d'opération : sans « combien », « Puis-je retirer à l'étranger ? » demande une
# autorisation, pas un montant — c'est une question de FAQ, pas une donnée
# personnelle.
CARD_LIMIT_CAPACITY_PATTERN = (
    r"\bcombien\b[\w\s'’-]{0,20}\b(puis-je|je peux|peut-on|on peut)\b"
    r"[\w\s'’-]{0,20}\b(payer|regler|depenser|retirer|sortir)\b"
)

CARD_LIMIT_PATTERN = (
    r"\bplafonds?\b"
    r"|\blimites?\b"
    r"|\bmaximums?\b"
    r"|" + CARD_LIMIT_CAPACITY_PATTERN
)

CARD_PAYMENT_PATTERN = r"\bpaiements?\b|\bpayer\b|\bregler\b|\bdepenser\b|\bachat\b"

CARD_WITHDRAWAL_PATTERN = r"\bretraits?\b|\bretirer\b|\bsortir\b"

# L'ordre compte : la première entité trouvée gagne. Le numéro de carte est
# testé avant toute autre facette de la carte, et les identifiants de compte
# avant le solde — « le rib de mon compte » ne doit jamais devenir « mon solde »,
# ce qui était précisément le bug n°2.
_ENTITY_PATTERNS: list[tuple[str, list[str]]] = [
    (
        CARD_NUMBER,
        [
            r"\bnumeros?\b[\w\s'’-]{0,25}\bcartes?\b",
            r"\bcartes?\b[\w\s'’-]{0,25}\bnumeros?\b",
            r"\b16\s*chiffres\b",
            r"\bpan\b",
            r"رقم[\s\w]{0,15}البطاقة",
            r"\bra9m\b[\s\w]{0,15}\b(carte|kart)\b",
        ],
    ),
    (
        ACCOUNT_IDENTIFIERS,
        [
            r"\brib\b",
            r"\biban\b",
            r"\bbic\b",
            r"\bswift\b",
            r"\bnumeros?\b[\w\s'’-]{0,20}\bcomptes?\b",
            r"\bcomptes?\b[\w\s'’-]{0,20}\bnumeros?\b",
            r"\bcoordonnees bancaires\b",
            r"\bdomiciliation bancaire\b",
            # darija : الريب / الحساب البنكي / rib
            r"الريب",
            r"\bريب\b",
            r"الايبان",
        ],
    ),
    (
        CARD_INFORMATION,
        [
            CARD_LIMIT_PATTERN,
            r"\bstatut\b[\w\s'’-]{0,15}\bcartes?\b",
            r"\bcartes?\b[\w\s'’-]{0,15}\bstatut\b",
            r"\bexpiration\b",
            r"\binformations?\b[\w\s'’-]{0,15}\bcartes?\b",
        ],
    ),
    (
        BALANCE,
        [
            r"\bsoldes?\b",
            r"\bavoirs?\b",
            # « combien j'ai », « combien 3andi », « chhal 3andi » : une
            # quantité rapportée à une possession EST une question de solde,
            # même sans le mot « solde ». Sans cette règle, « chhal 3andi f
            # l7sab » (normalisé « combien 3andi f compte ») partait en FAQ,
            # aucun motif ne reconnaissant la tournure darija.
            r"\b(combien|chhal|ch7al)\b[\w\s'’]{0,15}\b(j'?ai|ai-je|3andi|3ndi|3ndi)\b",
            r"\b(3andi|3ndi)\b[\w\s'’]{0,10}\b(f|fi)\b[\w\s'’]{0,10}\b(compte|l7sab|hsab)\b",
            r"الرصيد",
            r"\bsolde dyali\b",
        ],
    ),
    (
        TRANSACTIONS,
        [
            r"\btransactions?\b",
            r"\boperations?\b",
            r"\bmouvements?\b",
            r"\breleves?\b",
            r"\bhistorique\b",
            r"المعاملات",
        ],
    ),
    (
        BENEFICIARIES,
        [
            r"\bbeneficiaires?\b",
            r"المستفيدين",
        ],
    ),
]

_COMPILED_ENTITIES = [
    (entity, [re.compile(p) for p in patterns]) for entity, patterns in _ENTITY_PATTERNS
]


# ---------------------------------------------------------------------------
# 2. MARQUEURS DE POSSESSION
#
# « mon / ma / mes » mais aussi les formes darija non normalisées. C'est le
# marqueur DÉCISIF : sa présence transforme n'importe quelle entité en donnée
# personnelle, et annule toute lecture définitionnelle.
# ---------------------------------------------------------------------------
_OWNERSHIP_PATTERNS = [
    re.compile(p)
    for p in (
        # français
        r"\bmon\b",
        r"\bma\b",
        r"\bmes\b",
        r"\bmien(ne)?s?\b",
        r"\bje possede\b",
        r"\bj'?ai\b",
        r"\bque je detiens\b",
        # « combien puis-je … » : une quantité demandée à la première personne
        # porte nécessairement sur son propre compte/sa propre carte. Restreint
        # à la forme « combien » : « Puis-je payer à l'étranger ? » demande une
        # autorisation (FAQ), pas un montant personnel.
        r"\bcombien\b[\w\s'’-]{0,20}\b(puis-je|je peux)\b",
        r"\bchez moi\b",
        # arabizi (darija latine)
        r"\bdyal[ait]?\b",
        r"\bdiali\b",
        r"\bdyali\b",
        r"\bdyalti\b",
        r"\btaw3i\b",
        r"\bnta3i\b",
        r"\bliya\b",
        r"\b3andi\b",
        r"\b3ndi\b",
        # arabe
        r"ديالي",
        r"ديالتي",
        r"متاعي",
        r"حسابي",
        r"بطاقتي",
        r"عندي",
    )
]


# ---------------------------------------------------------------------------
# 3. VERBES DE DEMANDE ET FORMES INTERROGATIVES
#
# « je veux voir », « montre-moi », « donne-moi », « quel est »… Ces marqueurs
# n'engagent rien seuls : ils servent à reconnaître une demande d'affichage
# sans possessif explicite (« afficher le rib »).
# ---------------------------------------------------------------------------
_REQUEST_PATTERNS = [
    re.compile(p)
    for p in (
        # français — verbes
        r"\bvoir\b",
        r"\bmontr(e|er|ez)\b",
        r"\bdonn(e|er|ez)\b",
        r"\baffich(e|er|ez)\b",
        r"\bconnaitre\b",
        r"\bconsulter\b",
        r"\bsavoir\b",
        r"\bobtenir\b",
        r"\brecuperer\b",
        r"\bcommuniquer\b",
        r"\bindiquer\b",
        r"\bfournir\b",
        r"\bveux\b",
        r"\bvoudrais\b",
        r"\bsouhaite\b",
        r"\bbesoin\b",
        r"\bpeux-tu\b",
        r"\bpouvez-vous\b",
        # français — formes interrogatives
        r"\bquel(le)?s? est\b",
        r"\bquel(le)?s? sont\b",
        r"\bc'?est quoi\b",
        r"\bcombien\b",
        r"\boù\b",
        r"\bou puis-je\b",
        # arabizi
        r"\bbghit\b",
        r"\bbgit\b",
        r"\bnchof\b",
        r"\bnchouf\b",
        r"\b3tini\b",
        r"\b3teni\b",
        r"\bwerini\b",
        r"\bwarini\b",
        r"\bchno howa\b",
        r"\bchnahowa\b",
        r"\bchnou\b",
        r"\bfin\b",
        # arabe
        r"بغيت",
        r"نشوف",
        r"عطيني",
        r"وريني",
        r"شنو",
        r"شحال",
        r"فين",
    )
]


# ---------------------------------------------------------------------------
# 4. MARQUEURS DE DÉFINITION
#
# Ne rendent une question publique QUE si aucun marqueur de possession n'est
# présent. « Qu'est-ce qu'un RIB ? » est publique ; « c'est quoi mon RIB ? »
# ne l'est pas.
# ---------------------------------------------------------------------------
_DEFINITION_PATTERNS = [
    re.compile(p)
    for p in (
        r"\bqu'?est[- ]ce\b",
        r"\bqu'?est ce\b",
        r"\bdefinition\b",
        r"\bdefinir\b",
        r"\ba quoi sert\b",
        r"\bça sert a quoi\b",
        r"\bca sert a quoi\b",
        r"\bcomment fonctionne\b",
        r"\bcomment marche\b",
        r"\bexplique[rz]?\b",
        r"\bsignifie\b",
        r"\bveut dire\b",
        r"\bquelle est la difference\b",
        r"\bpourquoi\b",
        r"\bcomment obtenir un\b",
        r"\bc'?est quoi un(e)?\b",
        r"\bqu'?un\b",
        r"شنو كايعني",
        r"علاش",
    )
]

# Un article indéfini juste après l'entité trahit une question générale :
# « un RIB », « le RIB en général ». Utilisé uniquement en l'absence de
# possession, comme signal supplémentaire de définition.
_INDEFINITE_ENTITY_PATTERN = re.compile(
    r"\b(un|une|le|la|les|des)\s+(rib|iban|bic|swift|compte bancaire|carte bancaire)\b"
)


@dataclass(frozen=True)
class PersonalEntityMatch:
    """Résultat de la résolution compositionnelle.

    `is_personal` est la seule conclusion à consommer par le graphe ; les
    autres champs existent pour le diagnostic et les tests, et rendent la
    décision entièrement explicable.
    """

    entity: Optional[str]
    has_ownership: bool
    has_request: bool
    has_definition_marker: bool
    is_personal: bool
    is_public_definition: bool


def _search_any(patterns, *texts: str) -> bool:
    return any(pattern.search(text) for pattern in patterns for text in texts if text)


def find_entity(*texts: str) -> Optional[str]:
    """Première entité bancaire reconnue, dans l'ordre de priorité déclaré."""
    for entity, patterns in _COMPILED_ENTITIES:
        for pattern in patterns:
            for text in texts:
                if text and pattern.search(text):
                    return entity
    return None


def has_ownership_marker(*texts: str) -> bool:
    return _search_any(_OWNERSHIP_PATTERNS, *texts)


def has_request_marker(*texts: str) -> bool:
    return _search_any(_REQUEST_PATTERNS, *texts)


def has_definition_marker(*texts: str) -> bool:
    return _search_any(_DEFINITION_PATTERNS, *texts)


def resolve(message: str, original_message: Optional[str] = None) -> PersonalEntityMatch:
    """Applique le modèle compositionnel décrit en tête de module.

    `message` est le texte normalisé par le pipeline (français canonique) ;
    `original_message`, s'il est fourni, est le texte tel que saisi. Les deux
    sont examinés : la reconnaissance reste ainsi correcte que la normalisation
    darija ait eu lieu ou non.
    """
    normalized = _normalize(message)
    raw = _normalize(original_message) if original_message else ""

    entity = find_entity(normalized, raw)
    ownership = has_ownership_marker(normalized, raw)
    request = has_request_marker(normalized, raw)
    definition = has_definition_marker(normalized, raw)

    if entity is None:
        return PersonalEntityMatch(None, ownership, request, definition, False, False)

    # Règle 1 — la possession tranche, et elle l'emporte sur la définition.
    if ownership:
        return PersonalEntityMatch(entity, True, request, definition, True, False)

    # Règle 2 — définition sans possession : question publique assumée.
    if definition or _INDEFINITE_ENTITY_PATTERN.search(normalized):
        return PersonalEntityMatch(entity, False, request, definition, False, True)

    # Règle 3 — le NUMÉRO DE CARTE est le seul cas où l'absence de possessif ne
    # change rien : demander un PAN n'est jamais une question de documentation,
    # la protection doit donc se déclencher aussi sur « donne le numéro de la
    # carte ».
    #
    # Aucune autre entité n'est capturée sans possessif. Un verbe de demande ne
    # suffit délibérément PAS : « Comment consulter la transaction ? » est une
    # question de procédure, à traiter par la FAQ. C'est bien le marqueur de
    # possession qui tranche, comme le veut la règle — et non le verbe, qui
    # ferait basculer vers le personnel des questions publiques légitimes.
    if entity == CARD_NUMBER:
        return PersonalEntityMatch(entity, False, request, definition, True, False)

    # Entité sans possessif : non résolu ici, le graphe poursuit normalement
    # (conversationnel, puis Mistral, puis repli déterministe, puis FAQ).
    return PersonalEntityMatch(entity, False, request, definition, False, False)


def is_personal_request(message: str, original_message: Optional[str] = None) -> bool:
    """Raccourci booléen de `resolve` — utilisé par le graphe."""
    return resolve(message, original_message).is_personal
