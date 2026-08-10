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
from decimal import Decimal
from typing import Optional

from agents.agent1_faq import llm_router, response_localizer
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

    has_plafond = bool(re.search(r"\bplafonds?\b", normalized_text))
    mentions_paiement_word = bool(re.search(r"\bpaiements?\b", normalized_text))
    mentions_retrait_word = bool(re.search(r"\bretraits?\b", normalized_text))

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
    if (
        not fields
        and mentions_carte_word
        and any(
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

    card_fields = _find_requested_card_fields(normalized)
    if card_fields:
        return {"intent": "card_information", "requested_fields": card_fields}

    if "beneficiaire" in normalized:
        return {"intent": "beneficiaries"}

    if _SPENDING_VERB_PATTERN.search(normalized):
        # `category` peut être `None` (ex. "Analyse mes dépenses", sans
        # catégorie précisée) -> résumé toutes catégories confondues.
        return {"intent": "spending_by_category", "category": _find_category(normalized), "period": _find_period(normalized)}

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


def _answer_spending_by_category(customer_id: str, category: Optional[str], period: str, db_path: Optional[str]) -> str:
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


def _answer_payments(customer_id: str, period: str, db_path: Optional[str]) -> str:
    year_month = _PERIOD_TO_YEAR_MONTH[period]
    period_label = "du mois dernier" if period == "last_month" else "de ce mois"

    payments = banking_db.get_transactions(
        customer_id, transaction_type="card_payment", year_month=year_month, db_path=db_path
    )
    if not payments:
        return f"Aucun paiement enregistré {period_label}."
    lines = "; ".join(f"{p['transaction_date']} : {p['description']} ({_format_amount(p['amount'])})" for p in payments)
    return f"Voici vos paiements {period_label} : {lines}."


def _answer_recent_transactions(customer_id: str, db_path: Optional[str]) -> str:
    transactions = banking_db.get_transactions(customer_id, limit=5, db_path=db_path)
    if not transactions:
        return "Aucune opération n'est enregistrée sur votre compte."
    lines = "; ".join(
        f"{tx['transaction_date']} : {tx['description']} ({_format_amount(tx['amount'])})" for tx in transactions
    )
    return f"Voici vos dernières opérations : {lines}."


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


def _answer_card_information(customer_id: str, requested_fields: list[str], db_path: Optional[str]) -> str:
    card = banking_db.get_card_for_customer(customer_id, db_path=db_path)
    if card is None:
        return "Aucune carte n'est enregistrée sur votre compte."
    return _compose_card_answer(card, requested_fields)


def _answer_beneficiaries(customer_id: str, db_path: Optional[str]) -> str:
    beneficiaries = banking_db.get_beneficiaries_for_customer(customer_id, db_path=db_path)
    if not beneficiaries:
        return "Aucun bénéficiaire n'est enregistré sur votre compte."
    lines = "; ".join(f"{b['display_name']} ({b['masked_account_number']})" for b in beneficiaries)
    return f"Voici vos bénéficiaires enregistrés : {lines}."


def _answer_assistant_explain(customer_id: str, db_path: Optional[str]) -> str:
    """Repli honnête pour une question personnelle reconnue mais ne correspondant
    à aucun outil précis (ex. analyse/conseil financier) : jamais une erreur
    technique — explique la limite et joint, si possible, une donnée réelle
    utile (dernières opérations) plutôt qu'une réponse vide."""
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

    if parsed is None:
        parsed = classify_personal_intent(message)
    intent = parsed["intent"]

    if language == "fr":
        if intent == "card_information":
            return _answer_card_information(user_id, parsed["requested_fields"], banking_db_path)
        if intent == "spending_by_category":
            return _answer_spending_by_category(user_id, parsed["category"], parsed["period"], banking_db_path)
        if intent == "total_balance":
            return _answer_total_balance(user_id, banking_db_path)
        if intent == "balance_at_date":
            return _answer_balance_at_date(user_id, parsed["date"], banking_db_path)
        if intent == "salary":
            return _answer_salary(user_id, normalized, banking_db_path)
        if intent == "last_direct_debit":
            return _answer_last_direct_debit(user_id, banking_db_path)
        if intent == "payments":
            return _answer_payments(user_id, parsed["period"], banking_db_path)
        if intent == "recent_transactions":
            return _answer_recent_transactions(user_id, banking_db_path)
        if intent == "beneficiaries":
            return _answer_beneficiaries(user_id, banking_db_path)
        if intent == "assistant_explain":
            return _answer_assistant_explain(user_id, banking_db_path)
        return GENERIC_PERSONAL_FALLBACK

    # --- Darija (arabe ou latine) : mêmes données, mise en phrase localisée ---
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
        data = _fetch_recent_transactions_data(user_id, banking_db_path)
        return response_localizer.localize_recent_transactions_answer(data, language)
    if intent == "beneficiaries":
        data = _fetch_beneficiaries_data(user_id, banking_db_path)
        return response_localizer.localize_beneficiaries_answer(data, language)
    if intent == "assistant_explain":
        data = {"transactions": banking_db.get_transactions(user_id, limit=3, db_path=banking_db_path)}
        return response_localizer.localize_assistant_explain(data, language)

    return response_localizer.localize_generic_fallback(language)
