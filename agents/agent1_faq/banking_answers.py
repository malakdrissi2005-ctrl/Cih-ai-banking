"""Formulation des réponses de l'Agent 1 authentifié aux questions bancaires personnelles.

Sous-classification **déterministe** (mots-clés sur texte normalisé, jamais
un LLM) de la question personnelle — pouvant désormais reconnaître
**plusieurs informations demandées dans une même phrase** (ex. statut de
carte + plafonds) — puis appel des fonctions de lecture seule correspondantes
dans `backend/app/banking/banking_db.py`, strictement filtrées par le
`user_id` de la session courante — **jamais** par un identifiant présent dans
le texte du message ou envoyé par le frontend. Aucune donnée bancaire n'est
indexée dans ChromaDB ni transmise telle quelle au frontend : seule une
phrase de réponse en langage naturel est retournée.

Hors périmètre (voir `CLAUDE.md`) : toute demande de modification (virement,
augmentation de plafond, blocage/déblocage de carte) est déjà écartée en
amont par `classification.classify_intent` (intents `virement`/`compte_action`)
avant d'atteindre ce module.
"""
from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal
from typing import Optional

from agents.agent1_faq import llm_router, personal_entities, query_parameters, response_localizer
from agents.agent1_faq.classification import _normalize
from app.banking import banking_db

GENERIC_PERSONAL_FALLBACK = (
    "Je ne peux pas encore répondre précisément à cette question personnelle. "
    "Essayez par exemple : solde total, dépenses par catégorie, dernières opérations, "
    "date de salaire, dernier prélèvement, ou informations de carte."
)

# ---------------------------------------------------------------------------
# Normalisation des catégories de dépenses — insensible aux majuscules, aux
# accents (déjà gérés par `_normalize`) et au singulier/pluriel. Chaque
# variante reconnue pointe vers la catégorie canonique stockée dans banking.db.
# ---------------------------------------------------------------------------
_CATEGORY_GROUPS = {
    "Restaurants": ["restaurant", "restaurants", "restauration"],
    "Transport": ["transport", "transports"],
    "Courses": ["supermarche", "supermarches", "courses", "alimentation"],
    "Carburant": ["carburant", "essence"],
    "Assurance": ["assurance", "assurances"],
    "Abonnement": ["abonnement", "abonnements"],
    "Logement": ["logement", "loyer", "loyers"],
    "Retrait": ["retrait", "retraits"],
}
_CATEGORY_KEYWORDS = {keyword: canonical for canonical, keywords in _CATEGORY_GROUPS.items() for keyword in keywords}

# Verbes/tournures indiquant une question de dépense (par opposition à une
# simple mention de la catégorie) — évite tout déclenchement accidentel.
_SPENDING_VERB_PATTERN = re.compile(r"\bdepenses?\b|\bconsacres?\b")

# ---------------------------------------------------------------------------
# Demande de VUE D'ENSEMBLE d'un compte ("détails de mon compte", "aperçu de
# mon compte", "récapitulatif de mon compte", "état de mes comptes"...).
#
# Même structure que `_CATEGORY_GROUPS` ci-dessus (groupes de synonymes +
# recherche par frontière de mot) — jamais une seconde architecture parallèle.
#
# Généralise l'ancienne condition en dur `("information" in normalized or
# "renseignement" in normalized) and "compte" in normalized`, qui ne
# reconnaissait que deux formulations. La règle exige TOUJOURS la co-présence
# d'un terme de synthèse ET d'un sujet de compte : un terme de synthèse seul
# ("je veux un récapitulatif", sans préciser de quoi) reste volontairement
# non résolu et retombe sur `assistant_explain` — réponse honnête pour une
# demande réellement ambiguë, plutôt qu'une supposition arbitraire.
_ACCOUNT_OVERVIEW_GROUPS = {
    "terme_de_synthese": [
        "information", "informations", "info", "infos",
        "renseignement", "renseignements",
        "detail", "details", "apercu", "recapitulatif", "recap", "resume",
        "bilan", "synthese", "point", "etat", "situation", "vue",
        # Verbes de CONSULTATION ("je veux consulter mon compte", "montre-moi
        # mon compte", "affiche mon compte") : demander à voir son compte est
        # une demande de vue d'ensemble. Sûrs à cet endroit uniquement grâce à
        # l'ordre de la chaîne — "je veux voir mes bénéficiaires" ou "montre-moi
        # mes dernières opérations" sont interceptés bien avant par leur
        # intention spécifique (voir "NOTE D'ORDRE" plus bas).
        "consulter", "consulte", "voir", "afficher", "affiche",
        "montre", "montrer",
        # Formulations de MONTANT DISPONIBLE ("quel est le montant disponible
        # sur mon compte ?") — le mot nu ne suffit jamais, la co-présence d'un
        # sujet de compte reste exigée.
        "montant", "somme", "avoir", "disponible", "restant",
    ],
    "sujet_de_compte": ["compte", "comptes", "finances", "financiere"],
}

# Termes de synthèse AUTO-SUFFISANTS : reconnus même sans sujet explicite
# ("je veux un récapitulatif", sans préciser de quoi).
#
# Pourquoi c'est sûr malgré l'absence de sujet : cette règle n'est évaluée
# qu'en TOUTE FIN de la chaîne de `classify_personal_intent`, après carte,
# bénéficiaires, dépenses, solde daté, salaire, prélèvement, paiements et
# opérations. Un message qui parvient jusqu'ici en portant le seul mot
# "récapitulatif" ne contient donc, par construction, aucun signal plus
# précis — le résoudre vers `total_balance` (total + détail par compte, la
# synthèse de compte standard) est le comportement le plus utile et le moins
# risqué. "récapitulatif de mes opérations" reste intercepté bien avant, par
# `recent_transactions`.
#
# Volontairement limité à ces deux termes : "resume", "bilan", "detail",
# "point", "etat", "situation", "information" restent soumis à la présence
# d'un sujet, car ils sont courants hors contexte bancaire personnel
# (ex. "le résumé des conditions générales") et créeraient des faux positifs.
_SELF_SUFFICIENT_OVERVIEW_TERMS = ["recapitulatif", "recap"]

# Demande de MONTANT DISPONIBLE sans mentionner le mot "compte" ni "solde"
# ("quel montant ai-je encore ?", "quelle somme est disponible ?", "quel est
# mon avoir disponible ?"). Même structure de groupes que ci-dessus : la
# co-présence des deux familles est TOUJOURS exigée — "montant" ou "somme"
# seuls ne déclenchent jamais rien (ils apparaissent dans des questions
# publiques sur les frais, les plafonds, etc.).
_AVAILABLE_AMOUNT_GROUPS = {
    "terme_de_montant": ["montant", "somme", "avoir", "argent", "fonds"],
    "terme_de_disponibilite": ["disponible", "disponibles", "restant", "restants", "reste", "encore"],
}


def _is_available_amount_request(normalized_text: str) -> bool:
    """Vrai si le message demande le montant encore disponible, sans employer
    les mots "solde" ni "compte" — voir `_AVAILABLE_AMOUNT_GROUPS`."""
    return all(
        any(re.search(rf"\b{keyword}\b", normalized_text) for keyword in keywords)
        for keywords in _AVAILABLE_AMOUNT_GROUPS.values()
    )


def _is_account_overview_request(normalized_text: str) -> bool:
    """Vrai si le message demande une vue d'ensemble d'un compte — voir
    commentaire de `_ACCOUNT_OVERVIEW_GROUPS`. Déterministe, aucun appel LLM.

    N'a volontairement AUCUNE garde sur "carte" : la priorité de
    `card_information` est déjà assurée structurellement par l'ordre de la
    chaîne dans `classify_personal_intent` (le bloc carte est évalué en
    premier), jamais par une exclusion ajoutée ici."""
    if any(
        re.search(rf"\b{keyword}\b", normalized_text) for keyword in _SELF_SUFFICIENT_OVERVIEW_TERMS
    ):
        return True

    return all(
        any(re.search(rf"\b{keyword}\b", normalized_text) for keyword in keywords)
        for keywords in _ACCOUNT_OVERVIEW_GROUPS.values()
    )

# ---------------------------------------------------------------------------
# Normalisation des périodes.
# ---------------------------------------------------------------------------
_CURRENT_MONTH_PATTERNS = [
    re.compile(pattern) for pattern in (r"\bce mois-ci\b", r"\bce mois\b", r"\bmois actuel\b", r"\bmois en cours\b")
]
_LAST_MONTH_PATTERNS = [
    re.compile(pattern)
    for pattern in (r"\bmois dernier\b", r"\bmois precedent\b", r"\ble mois passe\b", r"\bmois passe\b")
]

_MONTH_NAMES = {
    "janvier": "01",
    "fevrier": "02",
    "mars": "03",
    "avril": "04",
    "mai": "05",
    "juin": "06",
    "juillet": "07",
    "aout": "08",
    "septembre": "09",
    "octobre": "10",
    "novembre": "11",
    "decembre": "12",
}
_DATE_PATTERN = re.compile(r"\b1(?:er)?\s+(" + "|".join(_MONTH_NAMES) + r")\b")

# ---------------------------------------------------------------------------
# Détection des champs de carte demandés (multi-intentions dans une même phrase).
# ---------------------------------------------------------------------------
_CARD_FIELD_ORDER = ["status", "payment_limit", "withdrawal_limit", "ecommerce_enabled", "international_enabled"]

# ---------------------------------------------------------------------------
# PROTECTION — demande du numéro de carte.
#
# Le numéro de carte complet (PAN) ne doit JAMAIS transiter par le chatbot :
# ni affiché, ni journalisé, ni transmis au LLM. La base elle-même ne stocke
# qu'un numéro masqué (`CARTE_BANCAIRE.numero_carte_masque`), et
# `_CARD_FIELD_ORDER` ci-dessus n'expose aucun champ de numéro — la donnée
# est donc structurellement absente du chemin de réponse.
#
# Cette détection ajoute la couche manquante : un REFUS EXPLICITE assorti
# d'une redirection vers un canal sécurisé, au lieu du message générique
# `assistant_explain` ("je ne peux pas encore…") qui était renvoyé jusqu'ici
# par accident plutôt que par décision.
#
# Évaluée en TOUT PREMIER dans `classify_personal_intent` : elle prime sur
# `card_information`, pour qu'une demande mêlant numéro et plafond ne puisse
# jamais retomber sur une réponse partielle.
# ---------------------------------------------------------------------------
_CARD_NUMBER_REQUEST_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\bnumero\b.{0,25}\bcartes?\b",
        r"\bcartes?\b.{0,25}\bnumero\b",
        r"\b(pan|numero de compte carte)\b",
        r"\b16 chiffres\b",
    )
]

# Message de refus du numéro de carte complet.
#
# L'ancienne rédaction contenait quatre affirmations inexactes, corrigées ici :
#   - « connectez-vous » était dit à un utilisateur DÉJÀ authentifié ;
#   - elle renvoyait en agence, ce que ce prototype ne peut pas promettre ;
#   - elle proposait « les derniers chiffres », que la réponse ne renvoie pas ;
#   - elle affirmait que le numéro complet était consultable ailleurs dans
#     l'application, alors qu'aucun écran ne l'implémente.
#
# Le texte ci-dessous ne promet donc que ce qui existe réellement : l'onglet
# « Cartes » et les trois informations que l'assistant sait effectivement
# donner (statut, expiration, plafonds).
CARD_NUMBER_REDIRECT_MESSAGE = response_localizer.CARD_NUMBER_REDIRECT_FR


# ---------------------------------------------------------------------------
# IDENTIFIANTS BANCAIRES — RIB, IBAN, numéro de compte.
#
# Ces trois champs existent dans `COMPTE_BANCAIRE` mais n'étaient exposés par
# aucune fonction de lecture ni reconnus par aucune intention : « Quel est mon
# RIB ? » tombait en `faq_generale` et la recherche RAG renvoyait une réponse
# sans rapport. Ce sont pourtant des données personnelles, soumises à session.
#
# Les valeurs renvoyées sont MASQUÉES par la couche d'accès aux données
# (`banking_db.get_account_identifiers_for_customer`) — le chatbot n'émet
# jamais un RIB ou un IBAN complet, même pour son propriétaire.
# ---------------------------------------------------------------------------
_ACCOUNT_IDENTIFIER_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\brib\b",
        r"\biban\b",
        r"\bbic\b",
        r"\bswift\b",
        r"\bnumero\b.{0,20}\bcomptes?\b",
        r"\bcomptes?\b.{0,20}\bnumero\b",
        r"\bcoordonnees bancaires\b",
        r"\bdomiciliation bancaire\b",
    )
]


def _requests_account_identifiers(normalized_text: str) -> bool:
    """Vrai si le message demande un identifiant bancaire (RIB/IBAN/n° de compte)."""
    return any(pattern.search(normalized_text) for pattern in _ACCOUNT_IDENTIFIER_PATTERNS)


def _requests_card_number(normalized_text: str) -> bool:
    """Vrai si le message demande le numéro de carte — voir commentaire
    ci-dessus. Déterministe, aucun appel LLM."""
    return any(pattern.search(normalized_text) for pattern in _CARD_NUMBER_REQUEST_PATTERNS)


def _find_category(normalized_text: str) -> Optional[str]:
    for keyword, category in _CATEGORY_KEYWORDS.items():
        if re.search(rf"\b{keyword}\b", normalized_text):
            return category
    return None


def _find_period(normalized_text: str) -> str:
    """Retourne "last_month" ou "current_month" (repli par défaut)."""
    if any(pattern.search(normalized_text) for pattern in _LAST_MONTH_PATTERNS):
        return "last_month"
    if any(pattern.search(normalized_text) for pattern in _CURRENT_MONTH_PATTERNS):
        return "current_month"
    return "current_month"


def _find_reference_date(normalized_text: str) -> Optional[str]:
    match = _DATE_PATTERN.search(normalized_text)
    if not match:
        return None
    year = "2026"
    match_year = re.search(r"\b(20\d{2})\b", normalized_text)
    if match_year:
        year = match_year.group(1)
    return f"{year}-{_MONTH_NAMES[match.group(1)]}-01"


# Plafonds de carte : les lexiques vivent dans `personal_entities` (source
# unique), pour que la reconnaissance d'entité et le choix des champs renvoyés
# ne puissent jamais diverger.
_CARD_LIMIT_PATTERN = personal_entities.CARD_LIMIT_PATTERN
_CARD_PAYMENT_PATTERN = personal_entities.CARD_PAYMENT_PATTERN
_CARD_WITHDRAWAL_PATTERN = personal_entities.CARD_WITHDRAWAL_PATTERN


def _find_requested_card_fields(normalized_text: str) -> list[str]:
    """Détecte, dans une même phrase, toutes les informations de carte demandées."""
    fields: set[str] = set()

    mentions_carte_word = bool(re.search(r"\bcarte\b", normalized_text))
    mentions_status = (
        bool(re.search(r"\bstatut\b", normalized_text))
        or bool(re.search(r"\bactive?\b", normalized_text))
        # "marche"/"fonctionne" ne comptent comme demande de statut que si "carte"
        # est également mentionnée - évite tout déclenchement hors contexte carte.
        or (mentions_carte_word and bool(re.search(r"\bmarche\b|\bfonctionne\b", normalized_text)))
    )

    # Un plafond peut se dire autrement que « plafond » : « limite », mais
    # surtout par la CAPACITÉ (« combien puis-je payer / retirer »), qui est la
    # formulation la plus naturelle et la seule employée en darija. Sans elle,
    # « Combien puis-je retirer ? » ne déclenchait aucun champ et retombait sur
    # le défaut générique `status` — d'où la réponse « Votre carte est active ».
    has_plafond = bool(re.search(_CARD_LIMIT_PATTERN, normalized_text))
    mentions_paiement_word = bool(re.search(_CARD_PAYMENT_PATTERN, normalized_text))
    mentions_retrait_word = bool(re.search(_CARD_WITHDRAWAL_PATTERN, normalized_text))

    mentions_ecommerce = (
        bool(re.search(r"en ligne", normalized_text))
        or bool(re.search(r"\binternet\b", normalized_text))
        or bool(re.search(r"\be-?commerce\b", normalized_text))
    )
    mentions_international = bool(re.search(r"internationa", normalized_text)) or bool(
        re.search(r"\betrange", normalized_text)
    )
    mentions_site = bool(re.search(r"\bsite\b", normalized_text))

    if mentions_status:
        fields.add("status")

    if has_plafond:
        if mentions_paiement_word and not mentions_retrait_word:
            fields.add("payment_limit")
        elif mentions_retrait_word and not mentions_paiement_word:
            fields.add("withdrawal_limit")
        else:
            # Les deux plafonds mentionnés ensemble, ou "plafond" seul sans
            # qualificatif -> on retourne l'information complète des deux.
            fields.add("payment_limit")
            fields.add("withdrawal_limit")

    if mentions_site and mentions_international:
        # "achat sur un site étranger/international" implique un achat en ligne.
        mentions_ecommerce = True

    if mentions_ecommerce:
        fields.add("ecommerce_enabled")
    if mentions_international:
        fields.add("international_enabled")

    # Demande GÉNÉRIQUE d'information sur la carte ("détails de ma carte",
    # "aperçu de ma carte", "informations sur ma carte") : aucune information
    # précise n'a été identifiée ci-dessus, mais le message porte clairement
    # sur la carte du client. On retombe alors sur "status" — exactement la
    # même valeur par défaut que le chemin Mistral
    # (`llm_router.to_personal_intent` : card_query -> ["status"]), pour que
    # les deux chemins restent cohérents.
    #
    # Appliqué UNIQUEMENT si `fields` est encore vide : ne modifie donc jamais
    # le résultat d'une demande déjà précise (plafonds, paiement en ligne,
    # statut explicite...), et ne change aucun comportement existant.
    #
    # Le POSSESSIF suffit également : "quelle est ma carte ?" est une demande
    # d'information légitime sur sa propre carte, sans terme de synthèse. Sans
    # cette règle, elle retombait sur `assistant_explain` — écart constaté lors
    # du test de bout en bout de la démonstration.
    if not fields and mentions_carte_word and (
        re.search(r"\b(ma|mes) cartes?\b", normalized_text)
        or any(
            re.search(rf"\b{keyword}\b", normalized_text)
            for keyword in _ACCOUNT_OVERVIEW_GROUPS["terme_de_synthese"]
        )
    ):
        fields.add("status")

    return [field for field in _CARD_FIELD_ORDER if field in fields]


def classify_personal_intent(message: str) -> dict:
    """Sous-classification déterministe d'une question personnelle déjà authentifiée.

    Retourne un dict `{"intent": ..., ...}` — jamais laissé à l'appréciation
    d'un LLM, mêmes principes que `classification.classify_intent`. Peut être
    remplacée par le résultat du LLM Router (voir `llm_router.py`) lorsque
    celui-ci est disponible et produit une extraction valide ; ce chemin
    déterministe reste le repli garanti en toutes circonstances.
    """
    normalized = _normalize(message)

    # PROTECTION — évaluée avant toute autre intention : une demande de numéro
    # de carte ne doit jamais pouvoir retomber sur `card_information` (réponse
    # partielle) ni sur `assistant_explain` (refus implicite). Voir
    # `_CARD_NUMBER_REQUEST_PATTERNS`.
    if _requests_card_number(normalized):
        return {"intent": "card_number_redirect"}

    card_fields = _find_requested_card_fields(normalized)
    if card_fields:
        return {"intent": "card_information", "requested_fields": card_fields}

    if "beneficiaire" in normalized:
        return {"intent": "beneficiaries"}

    # IDENTIFIANTS BANCAIRES (RIB / IBAN / numéro de compte).
    #
    # Placée APRÈS `beneficiaries` à dessein : « le RIB de mon bénéficiaire »
    # doit rester une question de bénéficiaires. Placée AVANT les règles
    # génériques de compte (`_is_account_overview_request`) et avant le
    # repli `solde`, pour qu'un mot générique comme « compte » ne vole pas
    # une demande plus précise.
    if _requests_account_identifiers(normalized):
        return {"intent": "account_identifiers"}

    if _SPENDING_VERB_PATTERN.search(normalized):
        # `category` peut être `None` (ex. "Analyse mes dépenses", sans
        # catégorie précisée) -> résumé toutes catégories confondues.
        return {"intent": "spending_by_category", "category": _find_category(normalized), "period": _find_period(normalized)}

    # REPLI TRANSACTIONNEL FILTRÉ — placé ICI, juste après la détection de
    # dépense et AVANT `total_balance` / la synthèse de compte.
    #
    # Sa position est le correctif structurant : « quelles sommes sont entrées
    # sur mon compte courant ? » et « ch7al dkhel l compte courant had simana »
    # étaient auparavant captés par `total_balance` (mot « compte ») ou par la
    # règle générique de synthèse (mot « somme »), et renvoyaient un solde au
    # lieu des opérations demandées.
    #
    # Il ne se déclenche que si la question exprime au moins un filtre
    # d'opération, et jamais après un verbe de dépense (déjà traité au-dessus
    # par `spending_by_category`) — sans quoi « combien ai-je dépensé ? »
    # basculerait à tort ici.
    # Deux types d'opération possèdent une intention DÉDIÉE plus bas dans la
    # chaîne (`salary`, `last_direct_debit`), avec leur propre formulation de
    # réponse : le repli ne doit jamais les leur voler. Sans cette garde,
    # « mon dernier prélèvement » et « wach dkhal lia salaire » basculaient à
    # tort vers une liste d'opérations brute.
    _params = query_parameters.extract_query_parameters(normalized, category_resolver=_find_category)
    _INTENTIONS_DEDIEES = ("salary", "direct_debit")
    if _params.transaction_type not in _INTENTIONS_DEDIEES and any(
        getattr(_params, champ) is not None
        for champ in ("direction", "transaction_type", "amount", "exact_date", "sort", "limit")
    ):
        return {"intent": "recent_transactions"}

    if ("total" in normalized and ("reste" in normalized or "solde" in normalized)) or (
        "courant" in normalized and "carnet" in normalized
    ):
        return {"intent": "total_balance"}

    # NOTE D'ORDRE : la demande générique de vue d'ensemble d'un compte
    # (anciennement testée ICI par `("information" or "renseignement") and
    # "compte"`) a été DÉPLACÉE plus bas, après les intentions spécifiques
    # (salaire, prélèvement, paiements, opérations). Raison : la règle est
    # désormais élargie à d'autres synonymes ("détails", "aperçu",
    # "récapitulatif"...) et, laissée à cette position, elle aurait pu voler
    # des messages appartenant à une intention plus précise — ex.
    # "récapitulatif de mes opérations sur mon compte" doit rester
    # `recent_transactions`. Le résultat des formulations déjà supportées est
    # strictement inchangé : aucune intention intermédiaire ne les intercepte.

    if "solde" in normalized and _DATE_PATTERN.search(normalized):
        reference_date = _find_reference_date(normalized)
        return {"intent": "balance_at_date", "date": reference_date}

    if "salaire" in normalized:
        return {"intent": "salary"}

    if "prelevement" in normalized:
        return {"intent": "last_direct_debit"}

    if "paiement" in normalized:
        return {"intent": "payments", "period": _find_period(normalized)}

    # "mouvement(s)" : synonyme bancaire courant d'"opération" ("affiche mes
    # mouvements", "mes derniers mouvements").
    if (
        "operation" in normalized
        or "transaction" in normalized
        or "historique" in normalized
        or "mouvement" in normalized
    ):
        return {"intent": "recent_transactions"}

    # Vue d'ensemble d'un compte — évaluée APRÈS toutes les intentions
    # spécifiques ci-dessus (voir "NOTE D'ORDRE" plus haut), pour ne jamais
    # leur voler un message. Couvre "détails/aperçu/récapitulatif/état/
    # informations ... de mon compte" et "bilan/résumé de mes finances", tous
    # résolus vers `total_balance` : c'est le seul outil de lecture existant
    # qui produit une vraie synthèse de compte (total + détail par compte).
    if _is_account_overview_request(normalized):
        return {"intent": "total_balance"}

    # Formulations naturelles sans mot-clé "solde" explicite (ex. "Peux-tu me
    # dire combien j'ai sur mon compte ?", "Combien il me reste ?").
    # "me reste" comblait un trou pré-existant : `classification.py` classait
    # déjà ces messages en `personal_data` via `\bme reste\b`, mais aucune
    # branche ici ne les reconnaissait — ils retombaient donc sur
    # `assistant_explain` au lieu du solde réel. Incohérence entre les deux
    # couches, corrigée ici.
    # "compte" accepté ici en plus de "j'ai"/"me reste" : couvre les tournures
    # Darija normalisées du type "combien ... mon compte" ("ch7al f l7ssab
    # dyali"). Sûr grâce à l'ordre : "combien ai-je dépensé sur mon compte ?"
    # est déjà intercepté par `spending_by_category` bien plus haut.
    if "combien" in normalized and (
        "j'ai" in normalized or "me reste" in normalized or "compte" in normalized
    ):
        return {"intent": "total_balance"}

    if "solde" in normalized or "argent" in normalized or _is_available_amount_request(normalized):
        return {"intent": "total_balance"}


    # Question personnelle reconnue (voir classification.classify_intent) mais
    # ne correspondant à aucun outil précis (ex. "Est-ce que mon argent suffit
    # pour voyager ?") : jamais une erreur technique - une explication honnête
    # des limites, complétée si possible par des données réelles disponibles.
    return {"intent": "assistant_explain"}


def _format_amount(amount: Decimal) -> str:
    return f"{amount} MAD"


def _answer_total_balance(customer_id: str, db_path: Optional[str]) -> str:
    accounts = banking_db.get_accounts_for_customer(customer_id, db_path=db_path)
    total = banking_db.get_total_balance(customer_id, db_path=db_path)
    detail = ", ".join(f"{acc['account_type']} : {_format_amount(acc['balance'])}" for acc in accounts)
    return f"Le total de vos comptes est de {_format_amount(total)} ({detail})."


def _answer_balance_at_date(customer_id: str, reference_date: Optional[str], db_path: Optional[str]) -> str:
    if reference_date is None:
        return (
            "Merci de préciser une date au format « 1er <mois> » (ex. 1er janvier) "
            "pour consulter un solde passé."
        )
    balances = banking_db.get_balance_at_date(customer_id, reference_date, db_path=db_path)
    if not balances:
        return (
            f"Aucun historique de solde n'est enregistré exactement à cette date ({reference_date}). "
            "Dates disponibles : 1er janvier, 1er avril, 1er juillet 2026."
        )
    detail = ", ".join(f"{b['account_type']} : {_format_amount(b['balance'])}" for b in balances)
    total = sum((b["balance"] for b in balances), Decimal("0"))
    return f"Au {reference_date}, votre solde était de {_format_amount(total)} ({detail})."


_PERIOD_LABELS = {
    "current_month": "pendant le mois en cours",
    "last_month": "le mois dernier",
}
_PERIOD_TO_YEAR_MONTH = {
    "current_month": banking_db.DEMO_CURRENT_MONTH,
    "last_month": banking_db.DEMO_LAST_MONTH,
}


def _answer_spending_by_category(
    customer_id: str,
    category: Optional[str],
    period: str,
    db_path: Optional[str],
    normalized_text: Optional[str] = None,
) -> str:
    """Dépenses, filtrées par catégorie, compte et période.

    `normalized_text` est optionnel pour préserver la signature historique ;
    lorsqu'il est fourni, les filtres supplémentaires (compte, période libre,
    agrégations) sont extraits par `query_parameters`.
    """
    if normalized_text is not None:
        params = query_parameters.extract_query_parameters(normalized_text, category_resolver=_find_category)

        # « Quelle est ma catégorie de dépense la plus importante ? »
        if params.aggregation == "max_category":
            repartition = banking_db.get_spending_breakdown(
                customer_id,
                account_type=params.account_type,
                year_month=params.year_month,
                date_from=params.date_from,
                db_path=db_path,
            )
            if not repartition:
                return "Vous n'avez enregistré aucune dépense sur la période demandée."
            top_categorie, top_montant = repartition[0]
            return (
                f"Votre principal poste de dépense est « {top_categorie} », "
                f"avec {_format_amount(top_montant)}."
            )

        # Filtres compte/période exprimés explicitement : on court-circuite la
        # période « figée » de la signature historique.
        if params.account_type or params.date_from or (params.year_month and params.year_month != _PERIOD_TO_YEAR_MONTH.get(period)):
            total = banking_db.get_spending_total(
                customer_id,
                category=params.category or category,
                year_month=params.year_month,
                account_type=params.account_type,
                date_from=params.date_from,
                db_path=db_path,
            )
            filtres = _describe_filters(params) or "toutes catégories confondues"
            if total == 0:
                return f"Vous n'avez enregistré aucune dépense ({filtres})."
            return f"Vous avez dépensé {_format_amount(total)} ({filtres})."

        if params.aggregation == "average":
            transactions = fetch_filtered_transactions(customer_id, params, db_path)
            if not transactions:
                return "Aucune dépense ne correspond à votre recherche."
            moyenne = sum((tx["amount"] for tx in transactions), Decimal("0")) / len(transactions)
            return (
                f"Votre dépense moyenne est de {_format_amount(moyenne.quantize(Decimal('0.01')))} "
                f"sur {len(transactions)} opération(s)."
            )

    year_month = _PERIOD_TO_YEAR_MONTH[period]
    period_label = _PERIOD_LABELS[period]

    # `get_spending_total` exclut toujours salaires/virements reçus/crédits/
    # remboursements positifs et les virements internes (`transfer_out`),
    # que `category` soit précisée ou non (résumé toutes catégories confondues).
    total = banking_db.get_spending_total(customer_id, category=category, year_month=year_month, db_path=db_path)
    category_label = category if category else "toutes catégories confondues"

    if total == 0:
        return f"Vous n'avez enregistré aucune dépense ({category_label}) {period_label}."
    return f"Vous avez dépensé {_format_amount(total)} ({category_label}) {period_label}."


def _answer_salary(customer_id: str, normalized_text: str, db_path: Optional[str]) -> str:
    salaries = banking_db.get_transactions(customer_id, transaction_type="salary", limit=1, db_path=db_path)
    if not salaries:
        return "Aucun salaire n'a été enregistré sur votre compte."
    salary = salaries[0]
    received_this_week = salary["transaction_date"] >= banking_db.DEMO_THIS_WEEK_START
    if "semaine" in normalized_text:
        if received_this_week:
            return f"Oui, un salaire de {_format_amount(salary['amount'])} a été crédité le {salary['transaction_date']}, cette semaine."
        return (
            f"Aucun salaire n'a été crédité cette semaine. Le dernier salaire enregistré "
            f"est du {salary['transaction_date']}, pour un montant de {_format_amount(salary['amount'])}."
        )
    return f"Votre salaire de {_format_amount(salary['amount'])} a été crédité le {salary['transaction_date']}."


def _answer_last_direct_debit(customer_id: str, db_path: Optional[str]) -> str:
    debits = banking_db.get_transactions(customer_id, transaction_type="direct_debit", limit=1, db_path=db_path)
    if not debits:
        return "Aucun prélèvement n'a été enregistré sur votre compte."
    debit = debits[0]
    return (
        f"Le dernier prélèvement effectué est « {debit['description']} » "
        f"de {_format_amount(debit['amount'])}, daté du {debit['transaction_date']}."
    )


def _answer_payments(
    customer_id: str, period: str, db_path: Optional[str], normalized_text: Optional[str] = None
) -> str:
    """Paiements carte, filtrables comme toute autre recherche d'opérations.

    Branché sur le MÊME pipeline que `recent_transactions` : sans cela,
    « mes paiements restaurant de ce mois-ci » ignorait la catégorie et
    renvoyait tous les paiements du mois. `normalized_text` reste optionnel
    pour préserver la signature historique.
    """
    if normalized_text is not None:
        params = query_parameters.extract_query_parameters(normalized_text, category_resolver=_find_category)
        # Un filtre plus précis que la simple période a été exprimé : on passe
        # par le pipeline commun, en forçant le type "paiement carte".
        if params.category or params.amount is not None or params.exact_date or params.limit or params.sort:
            params = replace(params, transaction_type=params.transaction_type or "card_payment")
            paiements = fetch_filtered_transactions(customer_id, params, db_path)
            filtres = _describe_filters(params)
            if not paiements:
                return f"Aucun paiement ne correspond à votre recherche ({filtres})."
            lignes = "; ".join(
                f"{p['transaction_date']} : {p['description']} ({_format_amount(p['amount'])})" for p in paiements
            )
            return f"Voici vos paiements ({filtres}) : {lignes}."

    year_month = _PERIOD_TO_YEAR_MONTH[period]
    period_label = "du mois dernier" if period == "last_month" else "de ce mois"

    payments = banking_db.get_transactions(
        customer_id, transaction_type="card_payment", year_month=year_month, db_path=db_path
    )
    if not payments:
        return f"Aucun paiement enregistré {period_label}."
    lines = "; ".join(f"{p['transaction_date']} : {p['description']} ({_format_amount(p['amount'])})" for p in payments)
    return f"Voici vos paiements {period_label} : {lines}."


_DEFAULT_TRANSACTION_LIMIT = 5
_MAX_TRANSACTION_LIMIT = 50


def fetch_filtered_transactions(customer_id: str, params, db_path: Optional[str]) -> list[dict]:
    """Applique les filtres extraits, DANS la couche d'accès aux données.

    Les filtres ne sont jamais appliqués après coup sur un résultat complet :
    ils sont poussés dans le SQL paramétré de `get_transactions`, ce qui évite
    de ramener toute la table puis de la filtrer en Python.

    Seul le tri par montant (`largest`/`smallest`) est fait ici : il porte sur
    une colonne stockée en TEXTE décimal, qu'un `ORDER BY` SQL trierait
    lexicographiquement ("9" > "100"). Le tri Python opère sur des `Decimal`,
    donc exactement.
    """
    limite = params.limit or _DEFAULT_TRANSACTION_LIMIT
    limite = min(limite, _MAX_TRANSACTION_LIMIT)

    # Un tri par montant doit voir toutes les lignes correspondantes avant de
    # découper : on ne limite qu'après tri.
    tri_par_montant = params.sort in ("largest", "smallest")

    transactions = banking_db.get_transactions(
        customer_id,
        account_type=params.account_type,
        category=params.category,
        transaction_type=params.transaction_type,
        direction=params.direction,
        year_month=params.year_month,
        date_from=params.date_from,
        exact_date=params.exact_date,
        amount=params.amount,
        order="asc" if params.sort == "oldest" else "desc",
        limit=None if tri_par_montant else limite,
        db_path=db_path,
    )

    if tri_par_montant:
        transactions.sort(key=lambda tx: tx["amount"], reverse=params.sort == "largest")
        transactions = transactions[:limite]

    return transactions


def _describe_filters(params) -> str:
    """Rappelle en clair les filtres appliqués, pour que la réponse soit
    vérifiable par l'utilisateur (exigence : indiquer le compte et la période)."""
    morceaux = []
    if params.category:
        morceaux.append(f"catégorie {params.category}")
    if params.transaction_type:
        morceaux.append(_TRANSACTION_TYPE_LABELS.get(params.transaction_type, params.transaction_type))
    if params.direction:
        morceaux.append("entrées" if params.direction == "credit" else "sorties")
    if params.account_type:
        morceaux.append(f"compte {params.account_type}")
    if params.exact_date:
        morceaux.append(f"le {params.exact_date}")
    elif params.year_month:
        morceaux.append(f"en {params.year_month}")
    elif params.date_from:
        morceaux.append(f"depuis le {params.date_from}")
    if params.amount is not None:
        morceaux.append(f"montant {_format_amount(params.amount)}")
    return ", ".join(morceaux)


_TRANSACTION_TYPE_LABELS = {
    "salary": "salaires",
    "direct_debit": "prélèvements",
    "withdrawal": "retraits",
    "card_payment": "paiements carte",
    "incoming_transfer": "virements reçus",
}


def _answer_recent_transactions(customer_id: str, normalized_text: str, db_path: Optional[str]) -> str:
    params = query_parameters.extract_query_parameters(normalized_text, category_resolver=_find_category)
    transactions = fetch_filtered_transactions(customer_id, params, db_path)
    filtres = _describe_filters(params)

    # AGRÉGATIONS : compter ou totaliser, plutôt que lister.
    if params.aggregation == "count":
        suffixe = f" ({filtres})" if filtres else ""
        return f"Vous avez {len(transactions)} opération(s) correspondant à votre demande{suffixe}."

    if params.aggregation == "total":
        total = sum((tx["amount"] for tx in transactions), Decimal("0"))
        suffixe = f" ({filtres})" if filtres else ""
        return f"Le total de ces opérations est de {_format_amount(total)}{suffixe}."

    if not transactions:
        # Aucun résultat n'est PAS une erreur technique : le message le dit
        # explicitement et rappelle les filtres, pour que l'utilisateur puisse
        # les corriger.
        if filtres:
            return f"Aucune opération ne correspond à votre recherche ({filtres})."
        return "Aucune opération n'est enregistrée sur votre compte."

    lines = "; ".join(
        f"{tx['transaction_date']} : {tx['description']} ({_format_amount(tx['amount'])})" for tx in transactions
    )
    entete = "Voici vos dernières opérations"
    if params.sort == "oldest":
        entete = "Voici vos premières opérations"
    elif params.sort == "largest":
        entete = "Voici vos opérations les plus élevées"
    elif params.sort == "smallest":
        entete = "Voici vos opérations les plus faibles"
    if filtres:
        entete += f" ({filtres})"
    return f"{entete} : {lines}."


def _compose_card_answer(card: dict, requested_fields: list[str]) -> str:
    """Compose une réponse couvrant **toutes** les informations de carte demandées.

    Ne renvoie jamais seulement une partie de la réponse lorsque plusieurs
    informations sont demandées dans la même phrase.
    """
    fields = set(requested_fields)

    # Cas particulier explicite : achat en ligne + international demandés
    # ensemble (typiquement "achat sur un site étranger") -> phrasé en une
    # seule réponse oui/non couvrant les deux conditions simultanément.
    if fields == {"ecommerce_enabled", "international_enabled"}:
        online = card["online_payments_enabled"]
        intl = card["international_payments_enabled"]
        if online and intl:
            return "Oui, votre carte autorise les paiements en ligne et les achats internationaux."
        if online and not intl:
            return "Non, votre carte autorise les paiements en ligne, mais les achats internationaux sont désactivés."
        if intl and not online:
            return "Non, les achats internationaux sont autorisés mais les paiements en ligne sont désactivés sur votre carte."
        return "Non, ni les paiements en ligne ni les achats internationaux ne sont autorisés sur votre carte."

    sentences: list[str] = []

    if "status" in fields:
        if card["status"] == "active":
            sentences.append("Votre carte est active.")
        else:
            sentences.append(f"Votre carte est actuellement « {card['status']} ».")

    has_status = "status" in fields
    if "payment_limit" in fields and "withdrawal_limit" in fields:
        pronoun = "Son" if has_status else "Votre"
        pronoun_lower = "son" if has_status else "votre"
        sentences.append(
            f"{pronoun} plafond de paiement est de {_format_amount(card['payment_limit'])} "
            f"et {pronoun_lower} plafond de retrait est de {_format_amount(card['withdrawal_limit'])}."
        )
    elif "payment_limit" in fields:
        pronoun = "Son" if has_status else "Votre"
        sentences.append(f"{pronoun} plafond de paiement est de {_format_amount(card['payment_limit'])}.")
    elif "withdrawal_limit" in fields:
        pronoun = "Son" if has_status else "Votre"
        sentences.append(f"{pronoun} plafond de retrait est de {_format_amount(card['withdrawal_limit'])}.")

    if "ecommerce_enabled" in fields:
        online = card["online_payments_enabled"]
        sentences.append(
            "Les paiements sur Internet sont autorisés." if online else "Les paiements sur Internet ne sont pas autorisés."
        )

    if "international_enabled" in fields:
        intl = card["international_payments_enabled"]
        sentences.append(
            "Les achats internationaux sont autorisés." if intl else "Les achats internationaux ne sont pas autorisés."
        )

    if not sentences:
        return f"Votre carte ({card['card_type']}) est actuellement « {card['status']} »."

    return " ".join(sentences)


def _answer_card_information(
    customer_id: str,
    requested_fields: list[str],
    db_path: Optional[str],
    normalized_text: Optional[str] = None,
) -> str:
    cards = banking_db.get_cards_for_customer(customer_id, db_path=db_path)
    if not cards:
        return "Aucune carte n'est enregistrée sur votre compte."

    if len(cards) > 1:
        # Jamais de sélection silencieuse : on demande, en s'appuyant uniquement
        # sur les références MASQUÉES (le numéro complet ne sort jamais d'ici).
        choisie = _select_card(cards, normalized_text)
        if choisie is None:
            references = " et ".join(_derniers_chiffres(c["masked_card_number"]) for c in cards)
            return (
                f"Vous avez {len(cards)} cartes : {references}. "
                "Laquelle souhaitez-vous consulter ?"
            )
        return _compose_card_answer(choisie, requested_fields)

    return _compose_card_answer(cards[0], requested_fields)


def _derniers_chiffres(reference_masquee: str) -> str:
    """Suffixe lisible d'une référence masquée, ex. « •••• 7007 ».

    Ne renvoie que les quatre derniers caractères significatifs : la référence
    complète, même masquée, n'a pas à être répétée dans une question.
    """
    chiffres = re.findall(r"\d", reference_masquee or "")
    return f"•••• {''.join(chiffres[-4:])}" if len(chiffres) >= 4 else reference_masquee


def _select_card(cards: list[dict], normalized_text: Optional[str]) -> Optional[dict]:
    """Carte désignée par les derniers chiffres cités, ou `None` si ambigu."""
    if not normalized_text:
        return None
    correspondances = [
        carte
        for carte in cards
        if _derniers_chiffres(carte["masked_card_number"]).split()[-1] in normalized_text
    ]
    return correspondances[0] if len(correspondances) == 1 else None


def _answer_beneficiaries(customer_id: str, db_path: Optional[str]) -> str:
    beneficiaries = banking_db.get_beneficiaries_for_customer(customer_id, db_path=db_path)
    if not beneficiaries:
        return "Aucun bénéficiaire n'est enregistré sur votre compte."
    lines = "; ".join(f"{b['display_name']} ({b['masked_account_number']})" for b in beneficiaries)
    return f"Voici vos bénéficiaires enregistrés : {lines}."


def _fetch_account_identifiers_data(customer_id: str, db_path: Optional[str]) -> dict:
    return {"accounts": banking_db.get_account_identifiers_for_customer(customer_id, db_path=db_path)}


def _label_type_compte(account_type: str, pluriel: bool = False) -> str:
    """Libellé lisible d'un type de compte, au singulier ou au pluriel.

    En français, c'est « compte » qui prend la marque du pluriel, pas le type :
    « plusieurs comptes carnet », jamais « plusieurs compte carnets ».
    """
    nom = "comptes" if pluriel else "compte"
    return f"{nom} {account_type}"


def _answer_account_identifiers(customer_id: str, db_path: Optional[str], normalized_text: Optional[str] = None) -> str:
    """RIB du compte demandé — concis, un seul compte à la fois.

    RÈGLE PAR DÉFAUT : sans précision, on répond le RIB du COMPTE COURANT et
    rien d'autre. Lister les trois comptes avec RIB, IBAN et numéro de compte
    répondait à une question que l'utilisateur n'avait pas posée, et noyait la
    valeur utile dans un paragraphe. L'IBAN, le numéro de compte et le solde
    restent accessibles — ils font l'objet de leurs propres questions.

    SÉLECTION EXPLICITE : un type de compte cité restreint la recherche ; si
    plusieurs comptes de ce type existent, on demande lequel en s'appuyant sur
    les références masquées, sans jamais en choisir un silencieusement. Les
    derniers chiffres cités par l'utilisateur tranchent alors.
    """
    resultat = select_account_for_identifiers(
        _fetch_account_identifiers_data(customer_id, db_path)["accounts"], normalized_text
    )
    genre, charge = resultat

    if genre == "aucun_compte":
        return "Aucun compte n'est associé à votre profil."
    if genre == "introuvable":
        return "Aucun compte correspondant n’a été trouvé."
    if genre == "ambigu":
        references = " et ".join(_derniers_chiffres(a["masked_account_number"]) for a in charge)
        libelle = _label_type_compte(charge[0]["account_type"], pluriel=True)
        return (
            f"Vous avez plusieurs {libelle} : {references}. "
            "Lequel souhaitez-vous consulter ?"
        )
    return _phrase_rib(charge, _requested_identifier_field(normalized_text))


def select_account_for_identifiers(accounts: list[dict], normalized_text: Optional[str]):
    """Choisit LE compte dont l'utilisateur veut le RIB.

    Sélection purement déterministe, INDÉPENDANTE DE LA LANGUE : le français et
    la darija partagent exactement cette fonction, de sorte qu'une même demande
    désigne toujours le même compte, seule la mise en phrase changeant. Sans ce
    partage, le chemin darija continuait de lister tous les comptes.

    Retourne un couple `(genre, charge)` :
      - `("compte", account)`      — un compte identifié ;
      - `("ambigu", [accounts])`   — plusieurs candidats, il faut demander ;
      - `("introuvable", None)`    — rien ne correspond à la demande ;
      - `("aucun_compte", None)`   — le client n'a aucun compte.
    """
    if not accounts:
        return ("aucun_compte", None)

    texte = normalized_text or ""
    params = (
        query_parameters.extract_query_parameters(texte, category_resolver=None)
        if texte
        else None
    )
    type_demande = params.account_type if params is not None else None

    # Des derniers chiffres cités désignent un compte précis, quel que soit son
    # type — c'est typiquement la réponse à la clarification posée juste avant.
    par_chiffres = _comptes_par_derniers_chiffres(accounts, texte)
    if len(par_chiffres) == 1:
        return ("compte", par_chiffres[0])
    if texte and _cite_des_derniers_chiffres(texte) and not par_chiffres:
        return ("introuvable", None)

    # DÉFAUT : le compte courant. Sans précision, c'est le RIB que l'on
    # communique pour recevoir un virement.
    candidats = [
        a for a in accounts if a["account_type"] == (type_demande or "courant")
    ]
    if not candidats:
        return ("introuvable", None)
    if len(candidats) > 1:
        return ("ambigu", candidats)
    return ("compte", candidats[0])


# Identifiant réellement demandé. Le RIB est le défaut, mais une question qui
# porte explicitement sur l'IBAN ou sur le numéro de compte doit recevoir CE
# qu'elle demande — répondre le RIB à « Donne-moi mon IBAN » serait à côté.
_IBAN_PATTERN = re.compile(r"\biban\b|الايبان|الإيبان")
_ACCOUNT_NUMBER_PATTERN = re.compile(
    r"\bnumeros?\b[\w\s'’-]{0,20}\bcomptes?\b|\bcomptes?\b[\w\s'’-]{0,20}\bnumeros?\b"
)

_LIBELLE_IDENTIFIANT = {"rib": "Le RIB", "iban": "L'IBAN", "account_number": "Le numéro"}


def _requested_identifier_field(normalized_text: Optional[str]) -> str:
    """« iban », « account_number », ou « rib » par défaut."""
    texte = normalized_text or ""
    if _IBAN_PATTERN.search(texte):
        return "iban"
    if _ACCOUNT_NUMBER_PATTERN.search(texte):
        return "account_number"
    return "rib"


def _phrase_rib(account: dict, field: str = "rib") -> str:
    """Réponse concise : un compte, l'identifiant demandé, rien d'autre.

    Volontairement sans les DEUX autres identifiants, sans solde et sans
    paragraphe de sécurité — ce sont autant de questions distinctes, et les
    empiler noyait la seule valeur utile.
    """
    libelle = _LIBELLE_IDENTIFIANT[field]
    return f"{libelle} de votre {_label_type_compte(account['account_type'])} est : {account[field]}."


_DERNIERS_CHIFFRES_PATTERN = re.compile(r"\b(\d{3,4})\b")


def _cite_des_derniers_chiffres(normalized_text: str) -> bool:
    """Vrai si le message cite une suite de 3-4 chiffres isolée.

    Un montant ou une année n'est pas concerné : ce test n'est consulté que
    dans le contexte d'une demande de coordonnées bancaires.
    """
    return bool(_DERNIERS_CHIFFRES_PATTERN.search(normalized_text))


def _comptes_par_derniers_chiffres(accounts: list[dict], normalized_text: str) -> list[dict]:
    """Comptes dont la référence masquée se termine par les chiffres cités."""
    if not normalized_text:
        return []
    cites = set(_DERNIERS_CHIFFRES_PATTERN.findall(normalized_text))
    if not cites:
        return []
    return [
        compte
        for compte in accounts
        if any(
            "".join(re.findall(r"\d", compte["masked_account_number"])).endswith(suffixe)
            for suffixe in cites
        )
    ]


# Question de clarification CIBLÉE, par entité bancaire reconnue.
#
# Cas d'usage : le message porte bien un marqueur de possession et une entité
# bancaire (il est donc personnel, jamais renvoyé vers la FAQ/RAG), mais aucune
# sous-intention précise n'a pu être résolue. Plutôt qu'un catalogue générique
# de ce que l'assistant sait faire, on repose une question sur l'entité que
# l'utilisateur vient justement de mentionner.
_TARGETED_CLARIFICATIONS = {
    personal_entities.ACCOUNT_IDENTIFIERS: (
        "Vous m'interrogez sur vos coordonnées bancaires. Souhaitez-vous votre RIB, "
        "votre IBAN, ou le numéro d'un compte en particulier ?"
    ),
    personal_entities.BALANCE: (
        "Vous m'interrogez sur votre solde. Souhaitez-vous le total de tous vos comptes, "
        "le solde d'un compte précis, ou votre solde à une date donnée ?"
    ),
    personal_entities.TRANSACTIONS: (
        "Vous m'interrogez sur vos opérations. Souhaitez-vous vos dernières opérations, "
        "celles d'une période précise, ou celles d'une catégorie de dépenses ?"
    ),
    personal_entities.CARD_INFORMATION: (
        "Vous m'interrogez sur votre carte. Souhaitez-vous son statut, sa date "
        "d'expiration ou ses plafonds ?"
    ),
    personal_entities.BENEFICIARIES: (
        "Vous m'interrogez sur vos bénéficiaires. Souhaitez-vous la liste de ceux "
        "enregistrés sur votre compte ?"
    ),
}


# Sous-intention par DÉFAUT d'une entité, appliquée quand la chaîne de
# classification n'a rien su tirer de plus précis (`assistant_explain`).
#
# Répondre vaut toujours mieux que demander : si l'utilisateur parle de son
# solde, lui donner son solde est plus utile que lui demander lequel. La
# clarification ci-dessous n'est donc gardée que pour l'entité qui n'a pas de
# défaut raisonnable — la carte, dont les facettes (statut, expiration,
# plafonds) sont trop différentes pour en choisir une arbitrairement.
_ENTITY_DEFAULT_SUBINTENT = {
    personal_entities.ACCOUNT_IDENTIFIERS: "account_identifiers",
    personal_entities.BALANCE: "total_balance",
    personal_entities.TRANSACTIONS: "recent_transactions",
    personal_entities.BENEFICIARIES: "beneficiaries",
}


def _default_subintent_for_entity(normalized_text: str) -> Optional[str]:
    """Sous-intention de repli déduite de l'entité mentionnée, ou `None`.

    Garantit qu'une demande reconnue comme personnelle produit une VRAIE
    réponse plutôt qu'un catalogue générique — et ne repart jamais vers la
    FAQ/RAG, ce que le graphe a déjà exclu en amont.
    """
    match = personal_entities.resolve(normalized_text)
    if not match.is_personal:
        return None
    return _ENTITY_DEFAULT_SUBINTENT.get(match.entity)


def _targeted_clarification(normalized_text: str) -> Optional[str]:
    """Question de clarification portant sur l'entité effectivement mentionnée.

    Retourne `None` si aucune entité n'est reconnue — l'appelant retombe alors
    sur son repli habituel. Ne consulte jamais la base : il s'agit uniquement
    de reformuler une question, pas de révéler une donnée.
    """
    match = personal_entities.resolve(normalized_text)
    if match.entity is None or not match.is_personal:
        return None
    return _TARGETED_CLARIFICATIONS.get(match.entity)


def _answer_assistant_explain(
    customer_id: str, db_path: Optional[str], normalized_text: Optional[str] = None
) -> str:
    """Repli honnête pour une question personnelle reconnue mais ne correspondant
    à aucun outil précis (ex. analyse/conseil financier) : jamais une erreur
    technique — explique la limite et joint, si possible, une donnée réelle
    utile (dernières opérations) plutôt qu'une réponse vide.

    Si le message mentionne malgré tout une entité bancaire précise, on pose
    d'abord une question de clarification ciblée sur cette entité : c'est plus
    utile qu'un catalogue générique, et cela évite qu'une demande personnelle
    non résolue reparte vers la FAQ/RAG.
    """
    if normalized_text:
        clarification = _targeted_clarification(normalized_text)
        if clarification:
            return clarification

    transactions = banking_db.get_transactions(customer_id, limit=3, db_path=db_path)
    base = (
        "Je peux vous renseigner sur votre solde, vos dépenses par catégorie, vos dernières opérations, "
        "la date de votre salaire, votre dernier prélèvement, vos bénéficiaires ou les informations de votre carte. "
        "Je ne peux pas encore réaliser d'analyse ou de conseil financier personnalisé."
    )
    if not transactions:
        return base
    lines = "; ".join(f"{tx['transaction_date']} : {tx['description']} ({_format_amount(tx['amount'])})" for tx in transactions)
    return f"{base} Voici vos 3 dernières opérations, qui peuvent vous aider : {lines}."


# ---------------------------------------------------------------------------
# Récupération des données brutes (sans mise en phrase) — réutilisée par
# `response_localizer` pour produire une réponse en darija arabe/latine, sans
# dupliquer la logique d'accès à `banking_db`. Le chemin français ci-dessus
# reste strictement inchangé.
# ---------------------------------------------------------------------------


def _fetch_total_balance_data(customer_id: str, db_path: Optional[str]) -> dict:
    accounts = banking_db.get_accounts_for_customer(customer_id, db_path=db_path)
    total = banking_db.get_total_balance(customer_id, db_path=db_path)
    return {"accounts": accounts, "total": total}


def _fetch_balance_at_date_data(customer_id: str, reference_date: Optional[str], db_path: Optional[str]) -> dict:
    if reference_date is None:
        return {"reference_date": None, "balances": []}
    balances = banking_db.get_balance_at_date(customer_id, reference_date, db_path=db_path)
    total = sum((b["balance"] for b in balances), Decimal("0"))
    return {"reference_date": reference_date, "balances": balances, "total": total}


def _fetch_spending_data(customer_id: str, category: Optional[str], period: str, db_path: Optional[str]) -> dict:
    year_month = _PERIOD_TO_YEAR_MONTH[period]
    total = banking_db.get_spending_total(customer_id, category=category, year_month=year_month, db_path=db_path)
    return {"category": category, "period": period, "total": total}


def _fetch_beneficiaries_data(customer_id: str, db_path: Optional[str]) -> dict:
    return {"beneficiaries": banking_db.get_beneficiaries_for_customer(customer_id, db_path=db_path)}


def _fetch_salary_data(customer_id: str, db_path: Optional[str]) -> dict:
    salaries = banking_db.get_transactions(customer_id, transaction_type="salary", limit=1, db_path=db_path)
    if not salaries:
        return {"found": False}
    salary = salaries[0]
    received_this_week = salary["transaction_date"] >= banking_db.DEMO_THIS_WEEK_START
    return {
        "found": True,
        "amount": salary["amount"],
        "date": salary["transaction_date"],
        "received_this_week": received_this_week,
    }


def _fetch_last_direct_debit_data(customer_id: str, db_path: Optional[str]) -> dict:
    debits = banking_db.get_transactions(customer_id, transaction_type="direct_debit", limit=1, db_path=db_path)
    if not debits:
        return {"found": False}
    debit = debits[0]
    return {"found": True, "description": debit["description"], "amount": debit["amount"], "date": debit["transaction_date"]}


def _fetch_payments_data(customer_id: str, period: str, db_path: Optional[str]) -> dict:
    year_month = _PERIOD_TO_YEAR_MONTH[period]
    payments = banking_db.get_transactions(
        customer_id, transaction_type="card_payment", year_month=year_month, db_path=db_path
    )
    return {"period": period, "payments": payments}


def _fetch_filtered_transactions_data(customer_id: str, normalized_text: str, db_path: Optional[str]) -> dict:
    """Chemin DARIJA : mêmes filtres que le chemin français.

    Sans cette fonction, la darija aurait reçu une liste non filtrée alors que
    le français aurait été filtré — une divergence de comportement entre
    langues, inacceptable pour un assistant trilingue.
    """
    params = query_parameters.extract_query_parameters(normalized_text, category_resolver=_find_category)
    return {"transactions": fetch_filtered_transactions(customer_id, params, db_path)}


def _fetch_recent_transactions_data(customer_id: str, db_path: Optional[str]) -> dict:
    return {"transactions": banking_db.get_transactions(customer_id, limit=5, db_path=db_path)}


def _fetch_card_data(customer_id: str, db_path: Optional[str]) -> dict:
    return {"card": banking_db.get_card_for_customer(customer_id, db_path=db_path)}


def build_personal_data_answer(
    message: str,
    user_id: Optional[str],
    banking_db_path: Optional[str] = None,
    language: str = "fr",
    llm_parsed: Optional[dict] = None,
) -> str:
    """Point d'entrée : formule la réponse à une question personnelle déjà authentifiée.

    `user_id` provient exclusivement de la session validée côté serveur
    (jamais du texte du message, jamais du frontend) — c'est la seule
    garantie d'isolation entre utilisateurs. Toutes les opérations sont en
    lecture seule (aucune fonction de `banking_db` appelée ici n'écrit).

    `message` est le message déjà normalisé (voir `darija_normalization`) —
    identique au message original pour le français. `language` détermine
    uniquement la mise en phrase finale (`response_localizer`), jamais la
    classification ni les données récupérées, strictement identiques quelle
    que soit la langue.

    `llm_parsed` : sortie déjà validée du LLM Router (`llm_router.route_with_llm`),
    optionnelle. Quand présente et convertible (`llm_router.to_personal_intent`),
    remplace `classify_personal_intent(message)` pour choisir l'outil — mais ne
    change jamais le fait que l'accès est déjà authentifié (décidé en amont par
    `graph.py`, jamais recalculé ici) ni le `user_id` utilisé. Absente ou non
    convertible : repli intégral et silencieux sur `classify_personal_intent`.
    """
    if not user_id:
        return GENERIC_PERSONAL_FALLBACK if language == "fr" else response_localizer.localize_generic_fallback(language)

    normalized = _normalize(message)

    # SÉCURITÉ — évaluée AVANT toute prise en compte de la sortie de Mistral.
    # `CLAUDE.md` §5 : aucune sécurité ne repose sur la capacité du LLM à bien
    # se comporter. Sans cette position en tête, un `llm_parsed` valant
    # `card_query` suffisait à contourner la protection et à faire répondre
    # l'assistant sur la carte — vérifié par
    # `test_protection_holds_even_if_mistral_says_card_query`.
    if _requests_card_number(normalized):
        return response_localizer.localize_card_number_redirect(language)

    parsed = llm_router.to_personal_intent(llm_parsed) if llm_parsed else None

    # Trou de repli corrigé : quand Mistral répond "unclear" (signal de FAIBLE
    # CONFIANCE), `to_personal_intent` le traduit en `assistant_explain`. Or
    # `graph.py` a déjà décidé, dans ce cas précis, de NE PAS faire confiance à
    # Mistral pour le bucket et de retomber sur la classification déterministe
    # (voir `_llm_router_node` : "unclear" ne fait jamais basculer le bucket).
    # Laisser malgré tout `assistant_explain` gagner ici revenait à faire
    # confiance à Mistral pour le choix de l'OUTIL alors qu'on venait de le
    # rejeter pour le bucket — incohérence entre les deux couches, qui privait
    # l'utilisateur d'une vraie réponse quand le repli déterministe, lui,
    # savait répondre.
    #
    # Ne peut jamais dégrader le résultat : `assistant_explain` est déjà la
    # réponse la plus faible du système, donc on ne remplace un
    # `assistant_explain` que par une intention strictement plus précise — si
    # le repli déterministe ne sait pas non plus, le comportement est
    # identique à avant. `to_personal_intent` reste strictement inchangée.
    if parsed is not None and parsed.get("intent") == "assistant_explain":
        deterministic_parsed = classify_personal_intent(message)
        if deterministic_parsed["intent"] != "assistant_explain":
            parsed = deterministic_parsed

    # CONFLIT DE PRIORITÉ CORRIGÉ — la sous-intention PRÉCISE de carte doit être
    # évaluée avant l'intention générique de statut.
    #
    # `llm_router.to_personal_intent` traduit le `card_query` de Mistral en
    # `requested_fields = ["status"]` : c'est son seul défaut possible, Mistral
    # ne distinguant pas les facettes de la carte. Comme `llm_parsed` primait,
    # « Quels sont les plafonds de ma carte ? » répondait « Votre carte est
    # active. » alors que la détection déterministe avait parfaitement reconnu
    # les deux plafonds.
    #
    # On ne remplace donc QUE le défaut générique `["status"]`, et seulement par
    # une détection déterministe strictement plus précise : quand Mistral et la
    # détection s'accordent sur le statut, rien ne change.
    if parsed is not None and parsed.get("intent") == "card_information":
        if parsed.get("requested_fields") == ["status"]:
            champs_deterministes = _find_requested_card_fields(normalized)
            if champs_deterministes and champs_deterministes != ["status"]:
                parsed = {**parsed, "requested_fields": champs_deterministes}

    if parsed is None:
        parsed = classify_personal_intent(message)
    intent = parsed["intent"]

    # Demande reconnue comme personnelle, mais aucune sous-intention précise :
    # on répond avec l'outil par défaut de l'entité mentionnée plutôt que de
    # servir un catalogue générique. Ne peut jamais dégrader le résultat —
    # `assistant_explain` est déjà la réponse la plus faible du système.
    if intent == "assistant_explain":
        defaut = _default_subintent_for_entity(normalized)
        if defaut:
            parsed = classify_personal_intent(message)
            parsed = {**parsed, "intent": defaut}
            intent = defaut

    # PROTECTION numéro de carte — évaluée avant l'aiguillage par langue et
    # AVANT toute lecture en base : aucune donnée carte n'est chargée, le
    # refus est produit sans jamais approcher le numéro. Message identique
    # quelle que soit la langue détectée : une consigne de sécurité ne doit
    # pas dépendre d'une localisation susceptible d'en atténuer la portée.
    if intent == "card_number_redirect":
        return response_localizer.localize_card_number_redirect(language)

    if language == "fr":
        if intent == "account_identifiers":
            return _answer_account_identifiers(user_id, banking_db_path, normalized_text=normalized)
        if intent == "card_information":
            return _answer_card_information(
                user_id, parsed["requested_fields"], banking_db_path, normalized_text=normalized
            )
        if intent == "spending_by_category":
            return _answer_spending_by_category(
                user_id, parsed["category"], parsed["period"], banking_db_path, normalized_text=normalized
            )
        if intent == "total_balance":
            return _answer_total_balance(user_id, banking_db_path)
        if intent == "balance_at_date":
            return _answer_balance_at_date(user_id, parsed["date"], banking_db_path)
        if intent == "salary":
            return _answer_salary(user_id, normalized, banking_db_path)
        if intent == "last_direct_debit":
            return _answer_last_direct_debit(user_id, banking_db_path)
        if intent == "payments":
            return _answer_payments(user_id, parsed["period"], banking_db_path, normalized_text=normalized)
        if intent == "recent_transactions":
            return _answer_recent_transactions(user_id, normalized, banking_db_path)
        if intent == "beneficiaries":
            return _answer_beneficiaries(user_id, banking_db_path)
        if intent == "assistant_explain":
            return _answer_assistant_explain(user_id, banking_db_path, normalized_text=normalized)
        return GENERIC_PERSONAL_FALLBACK

    # --- Darija (arabe ou latine) : mêmes données, mise en phrase localisée ---
    if intent == "account_identifiers":
        # MÊME sélection déterministe qu'en français (voir
        # `select_account_for_identifiers`) : une demande identique désigne le
        # même compte quelle que soit la langue, seule la phrase change.
        genre, charge = select_account_for_identifiers(
            _fetch_account_identifiers_data(user_id, banking_db_path)["accounts"], normalized
        )
        return response_localizer.localize_rib_selection(
            genre,
            charge,
            language,
            derniers_chiffres=_derniers_chiffres,
            field=_requested_identifier_field(normalized),
        )
    if intent == "card_information":
        data = _fetch_card_data(user_id, banking_db_path)
        return response_localizer.localize_card_answer(parsed["requested_fields"], data["card"], language)
    if intent == "spending_by_category":
        data = _fetch_spending_data(user_id, parsed["category"], parsed["period"], banking_db_path)
        return response_localizer.localize_spending_answer(data, language)
    if intent == "total_balance":
        data = _fetch_total_balance_data(user_id, banking_db_path)
        return response_localizer.localize_total_balance_answer(data, language)
    if intent == "balance_at_date":
        data = _fetch_balance_at_date_data(user_id, parsed["date"], banking_db_path)
        return response_localizer.localize_balance_at_date_answer(data, language)
    if intent == "salary":
        data = _fetch_salary_data(user_id, banking_db_path)
        return response_localizer.localize_salary_answer(data, "semaine" in normalized, language)
    if intent == "last_direct_debit":
        data = _fetch_last_direct_debit_data(user_id, banking_db_path)
        return response_localizer.localize_last_direct_debit_answer(data, language)
    if intent == "payments":
        data = _fetch_payments_data(user_id, parsed["period"], banking_db_path)
        return response_localizer.localize_payments_answer(data, language)
    if intent == "recent_transactions":
        data = _fetch_filtered_transactions_data(user_id, normalized, banking_db_path)
        return response_localizer.localize_recent_transactions_answer(data, language)
    if intent == "beneficiaries":
        data = _fetch_beneficiaries_data(user_id, banking_db_path)
        return response_localizer.localize_beneficiaries_answer(data, language)
    if intent == "assistant_explain":
        # Même règle qu'en français : une demande personnelle non résolue reçoit
        # une clarification ciblée, jamais un renvoi vers la FAQ/RAG.
        clarification = response_localizer.localize_targeted_clarification(
            personal_entities.resolve(normalized).entity, language
        )
        if clarification:
            return clarification
        data = {"transactions": banking_db.get_transactions(user_id, limit=3, db_path=banking_db_path)}
        return response_localizer.localize_assistant_explain(data, language)

    return response_localizer.localize_generic_fallback(language)
