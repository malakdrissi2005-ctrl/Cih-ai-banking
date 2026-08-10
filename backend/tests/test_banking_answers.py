"""Tests de la formulation multi-intentions des réponses bancaires personnelles
(agents/agent1_faq/banking_answers.py)."""
import pytest

from agents.agent1_faq.banking_answers import build_personal_data_answer, classify_personal_intent
from agents.agent1_faq.darija_normalization import normalize_darija_message
from app.banking import banking_db


@pytest.fixture
def banking_path(tmp_path):
    path = str(tmp_path / "banking_answers_test.db")
    banking_db.seed_banking_data(db_path=path)
    return path


# ---------------------------------------------------------------------------
# 1. Questions combinées sur la carte (multi-intentions)
# ---------------------------------------------------------------------------


def test_arabizi_general_account_information_maps_to_total_balance():
    """Non-regression : "3afak 3tini lma3lomat 3la l7sab" (Arabizi, "donne-moi
    les informations sur mon compte") produisait auparavant `recent_transactions`
    au lieu de `total_balance`, faute de normalisation Darija (voir
    `darija_normalization.py`/`language_detection.py`). Verifie la chaine
    complete `normalize_darija_message` -> `classify_personal_intent`, telle
    qu'utilisee reellement par le graphe (`graph.py::_security_guard_node`)."""
    normalized = normalize_darija_message("3afak 3tini lma3lomat 3la l7sab")
    parsed = classify_personal_intent(normalized)
    assert parsed["intent"] == "total_balance"
    assert parsed["intent"] != "recent_transactions"
    assert parsed["intent"] != "card_information"


def test_classify_status_and_both_limits_together():
    parsed = classify_personal_intent(
        "Donne-moi le statut actuel de ma carte ainsi que ses plafonds de paiement et de retrait."
    )
    assert parsed["intent"] == "card_information"
    assert set(parsed["requested_fields"]) == {"status", "payment_limit", "withdrawal_limit"}


def test_status_and_limits_returns_complete_answer(banking_path):
    answer = build_personal_data_answer(
        "Donne-moi le statut actuel de ma carte ainsi que ses plafonds de paiement et de retrait.",
        "usr_001",
        banking_path,
    )
    assert "active" in answer.lower()
    assert "5000.00" in answer
    assert "2000.00" in answer


def test_status_and_online_payment_active_card(banking_path):
    answer = build_personal_data_answer(
        "Ma carte est-elle active et autorisée pour les paiements sur Internet ?", "usr_001", banking_path
    )
    assert "active" in answer.lower()
    assert "autorises" in answer.lower() or "autorisés" in answer.lower() or "autorise" in answer.lower()


def test_status_for_blocked_card(banking_path):
    # usr_004 a une carte au statut "blocked" dans le jeu de donnees fictif.
    answer = build_personal_data_answer("Quel est le statut actuel de ma carte ?", "usr_004", banking_path)
    assert "active" not in answer.lower()
    assert "blocked" in answer.lower()


def test_foreign_site_purchase_checks_ecommerce_and_international_both_enabled(banking_path):
    # usr_001 : online=1, international=1
    answer = build_personal_data_answer(
        "Est-ce que je peux utiliser ma carte pour effectuer un achat sur un site étranger ?", "usr_001", banking_path
    )
    assert answer == "Oui, votre carte autorise les paiements en ligne et les achats internationaux."


def test_foreign_site_purchase_ecommerce_enabled_but_international_disabled(banking_path):
    # usr_002 : online=1, international=0
    answer = build_personal_data_answer(
        "Est-ce que je peux utiliser ma carte pour effectuer un achat sur un site étranger ?", "usr_002", banking_path
    )
    assert answer == "Non, votre carte autorise les paiements en ligne, mais les achats internationaux sont désactivés."


def test_both_limits_without_status(banking_path):
    answer = build_personal_data_answer(
        "Quels sont actuellement le plafond de paiement et le plafond de retrait associés à ma carte ?",
        "usr_001",
        banking_path,
    )
    assert "5000.00" in answer
    assert "2000.00" in answer


def test_online_and_international_payments_check(banking_path):
    answer = build_personal_data_answer(
        "Vérifie si ma carte autorise les paiements en ligne et les paiements internationaux.", "usr_001", banking_path
    )
    assert answer == "Oui, votre carte autorise les paiements en ligne et les achats internationaux."


def test_card_multi_intent_never_returns_partial_answer(banking_path):
    answer = build_personal_data_answer(
        "Donne-moi le statut actuel de ma carte ainsi que ses plafonds de paiement et de retrait.",
        "usr_001",
        banking_path,
    )
    # Les trois informations demandees doivent toutes apparaitre.
    assert "active" in answer.lower()
    assert "5000.00" in answer
    assert "2000.00" in answer


# ---------------------------------------------------------------------------
# 2. Questions sur les depenses par categorie
# ---------------------------------------------------------------------------


def test_classify_spending_extracts_category_and_period():
    parsed = classify_personal_intent("Combien ai-je dépensé dans les restaurants pendant le mois en cours ?")
    assert parsed == {"intent": "spending_by_category", "category": "Restaurants", "period": "current_month"}


@pytest.mark.parametrize(
    "message",
    [
        "Combien ai-je dépensé dans les restaurants pendant le mois en cours ?",
        "Combien ai-je dépensé dans les restaurants ce mois-ci ?",
    ],
)
def test_restaurants_current_month(banking_path, message):
    answer = build_personal_data_answer(message, "usr_001", banking_path)
    # 89.90 + 120.00 + 76.50 = 286.40
    assert "286.40" in answer
    assert "Restaurants" in answer


@pytest.mark.parametrize(
    "message",
    [
        "Quel montant ai-je consacré au transport le mois dernier ?",
        "Combien ai-je dépensé en transport durant le mois précédent ?",
    ],
)
def test_transport_last_month(banking_path, message):
    answer = build_personal_data_answer(message, "usr_001", banking_path)
    assert "45.00" in answer
    assert "Transport" in answer


def test_transport_current_month_is_zero(banking_path):
    answer = build_personal_data_answer(
        "Combien ai-je dépensé en transport ce mois-ci ?", "usr_001", banking_path
    )
    assert "aucune depense" in answer.lower().replace("é", "e") or "aucune dépense" in answer
    assert "Transport" in answer


def test_supermarket_category_plural_and_accent(banking_path):
    answer = build_personal_data_answer("Combien ai-je dépensé dans les supermarchés ce mois-ci ?", "usr_001", banking_path)
    assert "Courses" in answer  # categorie canonique en base
    assert "300.00" in answer


def test_category_synonym_alimentation(banking_path):
    answer = build_personal_data_answer("Combien ai-je dépensé en alimentation ce mois-ci ?", "usr_001", banking_path)
    assert "Courses" in answer
    assert "300.00" in answer


def test_period_wording_mois_actuel(banking_path):
    parsed = classify_personal_intent("Combien ai-je dépensé dans les restaurants mois actuel ?")
    assert parsed["period"] == "current_month"


def test_period_wording_mois_passe(banking_path):
    parsed = classify_personal_intent("Combien ai-je dépensé dans les restaurants le mois passé ?")
    assert parsed["period"] == "last_month"


def test_zero_spending_message_is_explicit(banking_path):
    answer = build_personal_data_answer("Combien ai-je dépensé en transport ce mois-ci ?", "usr_002", banking_path)
    assert "Transport" in answer
    assert "0.00" not in answer  # la phrase doit etre explicite, pas juste "0.00 MAD"
    assert "aucune" in answer.lower()


def test_spending_never_includes_credits_or_salary(banking_path):
    # Le salaire (12000.00) et le virement recu (2000.00) ne doivent jamais
    # etre confondus avec une categorie de depense.
    answer = build_personal_data_answer("Combien ai-je dépensé dans les restaurants ce mois-ci ?", "usr_001", banking_path)
    assert "12000.00" not in answer
    assert "2000.00" not in answer


# ---------------------------------------------------------------------------
# 3. Vue d'ensemble d'un compte — formulations naturelles (repli déterministe)
#    Voir banking_answers.py, `_ACCOUNT_OVERVIEW_GROUPS` /
#    `_is_account_overview_request`. Chemin exercé ici : `classify_personal_intent`
#    seul, c'est-à-dire exactement le repli utilisé quand Mistral est
#    indisponible/désactivé (`llm_parsed=None`, cf. build_personal_data_answer).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Donne-moi les détails de mon compte",
        "Aperçu de mon compte",
        "Quel est l'état de mon compte ?",
        "Fais le point sur mes comptes",
        "Résumé de mes finances s'il te plaît",
        "Bilan de mes finances",
        "Quelle est ma situation financière ?",
        # Formulations historiques : doivent rester strictement inchangées
        # malgré le déplacement de la branche générique plus bas dans la chaîne.
        "Donne-moi les informations sur mon compte",
        "Je voudrais des renseignements sur mon compte",
    ],
)
def test_account_overview_phrasings_resolve_to_total_balance(message):
    """Une demande de vue d'ensemble se résout vers `total_balance` — seul
    outil de lecture existant produisant une vraie synthèse (total + détail
    par compte)."""
    assert classify_personal_intent(message)["intent"] == "total_balance"


@pytest.mark.parametrize(
    "message",
    [
        "Combien il me reste ?",
        "Combien me reste-t-il ?",
    ],
)
def test_combien_me_reste_resolves_to_total_balance(message):
    """Trou pré-existant corrigé : `classification.py` classait déjà ces
    messages en `personal_data` (via `\\bme reste\\b`), mais aucune branche de
    `classify_personal_intent` ne les reconnaissait — ils retombaient sur
    `assistant_explain` au lieu du solde réel."""
    assert classify_personal_intent(message)["intent"] == "total_balance"


@pytest.mark.parametrize("message", ["Je veux un récapitulatif", "Je veux un récap", "Donne-moi un récapitulatif"])
def test_self_sufficient_overview_term_alone_resolves_to_total_balance(message):
    """Un terme de synthèse AUTO-SUFFISANT ("récapitulatif"/"récap") est résolu
    même sans sujet explicite.

    C'est sûr uniquement grâce à l'ordre de la chaîne : la règle est évaluée
    en dernier, donc un message qui parvient jusqu'ici avec le seul mot
    "récapitulatif" ne porte, par construction, aucun signal plus précis (voir
    `test_specific_intents_keep_priority_over_generic_overview`, qui prouve que
    "récapitulatif de mes opérations" est intercepté bien avant)."""
    assert classify_personal_intent(message)["intent"] == "total_balance"


@pytest.mark.parametrize(
    "message",
    [
        # Termes de synthèse NON auto-suffisants : sans sujet de compte, ils
        # ne doivent jamais être résolus (risque de faux positif hors contexte
        # bancaire personnel).
        "Je veux un résumé",
        "Donne-moi un bilan",
        "Je veux des détails",
        "Fais le point",
    ],
)
def test_non_self_sufficient_overview_terms_alone_stay_unresolved(message):
    """Non-régression faux positifs : seuls "récapitulatif"/"récap" sont
    auto-suffisants. "résumé", "bilan", "détails", "point" seuls restent
    volontairement non résolus (`assistant_explain`) — ils sont trop courants
    hors contexte bancaire personnel pour être devinés."""
    assert classify_personal_intent(message)["intent"] == "assistant_explain"


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        # Priorité carte : jamais capturée par la règle générique de compte.
        ("Détails de ma carte", "card_information"),
        ("Aperçu de ma carte", "card_information"),
        ("Récapitulatif de mes opérations sur mon compte", "recent_transactions"),
        ("Le point sur mes dépenses de mon compte", "spending_by_category"),
        ("Résumé de mes bénéficiaires sur mon compte", "beneficiaries"),
        ("Détails du dernier prélèvement sur mon compte", "last_direct_debit"),
        ("Aperçu de mon salaire sur mon compte", "salary"),
        ("Je veux voir l'historique de mon compte", "recent_transactions"),
    ],
)
def test_specific_intents_keep_priority_over_generic_overview(message, expected_intent):
    """Test d'ORDRE : la chaîne `if/elif` de `classify_personal_intent` est
    « premier match gagne ». La règle générique de vue d'ensemble est évaluée
    APRÈS toutes les intentions spécifiques et ne doit donc jamais leur voler
    un message, même quand celui-ci contient un terme de synthèse + "compte"."""
    assert classify_personal_intent(message)["intent"] == expected_intent


def test_generic_card_request_defaults_to_status_like_mistral_path():
    """Une demande générique sur la carte retombe sur "status" — même valeur
    par défaut que le chemin Mistral (`llm_router.to_personal_intent`,
    card_query -> ["status"]), pour que les deux chemins restent cohérents."""
    parsed = classify_personal_intent("Détails de ma carte")
    assert parsed["intent"] == "card_information"
    assert parsed["requested_fields"] == ["status"]


def test_mistral_unclear_does_not_override_a_better_deterministic_intent(banking_path):
    """Trou de repli corrigé : quand Mistral répond "unclear",
    `to_personal_intent` produit `assistant_explain`. `graph.py` ayant déjà
    rejeté ce signal de faible confiance pour le choix du bucket, il ne doit
    pas non plus l'emporter pour le choix de l'OUTIL — le repli déterministe,
    qui sait répondre ici, doit reprendre la main."""
    answer = build_personal_data_answer(
        "Donne-moi les détails de mon compte",
        "usr_001",
        banking_path,
        llm_parsed={"intent": "unclear"},
    )
    assert "45730.50" in answer
    assert "Je ne peux pas encore" not in answer


def test_mistral_unclear_still_falls_back_to_assistant_explain_when_deterministic_also_fails(banking_path):
    """Non-régression du correctif ci-dessus : si le repli déterministe ne sait
    pas non plus répondre, le comportement reste exactement celui d'avant
    (`assistant_explain`) — le correctif ne peut jamais dégrader un résultat."""
    # "Mes finances vont-elles bien ?" atteint bien `personal_data` (via
    # `\bmes finances\b`) mais ne porte aucun terme de synthèse ni aucun autre
    # signal précis : le repli déterministe répond lui aussi
    # `assistant_explain`.
    answer = build_personal_data_answer(
        "Mes finances vont-elles bien ?",
        "usr_001",
        banking_path,
        llm_parsed={"intent": "unclear"},
    )
    assert "Je ne peux pas encore" in answer


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        # Consultation de compte (verbes de consultation + sujet de compte).
        ("Je veux consulter mon compte", "total_balance"),
        ("Montre-moi mon compte", "total_balance"),
        ("Je veux voir mon compte", "total_balance"),
        ("Affiche mon compte", "total_balance"),
        # Montant disponible SANS le mot "solde" ni "compte".
        ("Quel montant ai-je encore ?", "total_balance"),
        ("Quelle somme est disponible ?", "total_balance"),
        ("Quel est mon avoir disponible ?", "total_balance"),
        ("Quel est le montant disponible sur mon compte ?", "total_balance"),
        # "mouvements" = synonyme d'opérations.
        ("Affiche mes mouvements", "recent_transactions"),
        ("Mes derniers mouvements", "recent_transactions"),
        # Carte : demande générique via "infos".
        ("Infos sur ma carte", "card_information"),
        ("Quel est l'état de ma carte ?", "card_information"),
        # Paiements sans possessif.
        ("Quels paiements ai-je faits ?", "payments"),
    ],
)
def test_enriched_natural_phrasings_resolve_to_expected_intent(message, expected_intent):
    """Formulations naturelles enrichies : chacune doit atteindre l'intention
    précise attendue, jamais le repli générique `assistant_explain`."""
    assert classify_personal_intent(message)["intent"] == expected_intent


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        # ORDRE : les verbes de consultation ajoutés au groupe générique ne
        # doivent jamais voler un message à une intention plus spécifique.
        ("Je veux voir mes bénéficiaires", "beneficiaries"),
        ("Montre-moi mes dernières opérations", "recent_transactions"),
        ("Je veux consulter l'historique de mon compte", "recent_transactions"),
        ("Affiche mes dépenses de mon compte", "spending_by_category"),
        ("Je veux voir mon salaire sur mon compte", "salary"),
        ("Montre-moi le dernier prélèvement de mon compte", "last_direct_debit"),
        ("Je veux voir les détails de ma carte", "card_information"),
        # "combien" + "compte" ne doit pas voler une question de dépenses.
        ("Combien ai-je dépensé sur mon compte ?", "spending_by_category"),
    ],
)
def test_enriched_groups_keep_specific_intents_priority(message, expected_intent):
    """Test d'ORDRE élargi : la chaîne reste « premier match gagne » et les
    groupes génériques enrichis sont évalués en dernier."""
    assert classify_personal_intent(message)["intent"] == expected_intent


def test_account_overview_returns_real_balance_data(banking_path):
    """Bout en bout sur le repli déterministe (`llm_parsed` absent) : la
    réponse contient bien le solde réel de l'utilisateur, jamais le message
    générique d'`assistant_explain`."""
    answer = build_personal_data_answer("Donne-moi les détails de mon compte", "usr_001", banking_path)
    # usr_001 : courant 15230.50 + carnet 30500.00 = 45730.50
    assert "45730.50" in answer
    assert "Je ne peux pas encore" not in answer


# ---------------------------------------------------------------------------
# Isolation entre utilisateurs / absence de session
# ---------------------------------------------------------------------------


def test_isolation_between_users_for_spending(banking_path):
    answer_1 = build_personal_data_answer("Combien ai-je dépensé dans les restaurants ce mois-ci ?", "usr_001", banking_path)
    answer_2 = build_personal_data_answer("Combien ai-je dépensé dans les restaurants ce mois-ci ?", "usr_002", banking_path)
    assert answer_1 != answer_2
    assert "286.40" in answer_1
    assert "286.40" not in answer_2


def test_isolation_between_users_for_card(banking_path):
    answer_1 = build_personal_data_answer("Quel est le statut actuel de ma carte ?", "usr_001", banking_path)
    answer_2 = build_personal_data_answer("Quel est le statut actuel de ma carte ?", "usr_004", banking_path)
    assert "active" in answer_1.lower()
    assert "blocked" in answer_2.lower()
    assert answer_1 != answer_2


def test_missing_user_id_falls_back_gracefully(banking_path):
    answer = build_personal_data_answer("Quel est mon solde ?", None, banking_path)
    assert answer  # ne leve jamais d'exception, renvoie un message generique
