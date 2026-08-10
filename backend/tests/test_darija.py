"""Tests de bout en bout du support Darija (arabe et Arabizi) de l'Agent 1.

Utilise le vrai pipeline `run_agent1` (détection de langue -> normalisation
-> classification -> lecture banking.db -> localisation de la réponse), avec
des bases ChromaDB/banking.db isolées (tmp_path) — jamais les vraies bases du
projet.
"""
import json

import pytest

from agents.agent1_faq.graph import run_agent1
from agents.agent1_faq.rag import get_faq_collection
from app.banking import banking_db
from scripts.ingest_faq import ingest_faq


@pytest.fixture
def collection(tmp_path):
    faq_path = tmp_path / "faq.json"
    faq_path.write_text(
        json.dumps(
            [{"question": "Quels documents pour ouvrir un compte ?", "answer": "CIN et justificatif de domicile."}]
        ),
        encoding="utf-8",
    )
    persist_dir = str(tmp_path / "chroma")
    ingest_faq(faq_path=faq_path, persist_dir=persist_dir, collection_name="faq_darija_test")
    return get_faq_collection(persist_dir=persist_dir, collection_name="faq_darija_test")


@pytest.fixture
def banking_path(tmp_path):
    path = str(tmp_path / "banking_darija_test.db")
    banking_db.seed_banking_data(db_path=path)
    return path


# ---------------------------------------------------------------------------
# Solde en arabe et en Arabizi
# ---------------------------------------------------------------------------


def test_balance_question_in_arabic(collection, banking_path):
    result = run_agent1(
        "شحال عندي فالحساب؟", is_authenticated=True, user_id="usr_001", collection=collection, banking_db_path=banking_path
    )
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    assert "45730.50" in result["response"]  # 15230.50 (courant) + 30500.00 (carnet)


def test_balance_question_in_arabizi(collection, banking_path):
    result = run_agent1(
        "ch7al 3ndi f compte?", is_authenticated=True, user_id="usr_001", collection=collection, banking_db_path=banking_path
    )
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    assert "45730.50" in result["response"]


# ---------------------------------------------------------------------------
# Demande generale d'informations sur le compte (non-regression) : le message
# Arabizi "3afak 3tini lma3lomat 3la l7sab" ("donne-moi les informations sur
# mon compte") repondait auparavant par l'historique des transactions au lieu
# d'un apercu du compte (total_balance) - le message n'etait pas reconnu comme
# darija par `language_detection.py`, donc jamais normalise par
# `darija_normalization.py`, donc envoye brut a Mistral (ou au repli
# deterministe) qui n'avait aucun element pour le rattacher a "compte".
# ---------------------------------------------------------------------------


def test_general_account_information_request_in_arabizi(collection, banking_path):
    result = run_agent1(
        "3afak 3tini lma3lomat 3la l7sab",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    # Doit repondre par un apercu du compte (total_balance, localise en darija
    # latine par response_localizer) - jamais par l'historique des transactions
    # ni par les informations de carte.
    assert "45730.50" in result["response"]
    response_lower = result["response"].lower()
    assert "operation" not in response_lower
    assert "carte" not in response_lower


def test_general_account_information_request_in_arabic(collection, banking_path):
    result = run_agent1(
        "عطيني المعلومات على الحساب",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    # Reponse localisee en darija arabe (response_localizer.localize_total_balance_answer) :
    # meme non-regression, vocabulaire arabe cette fois (jamais "العمليات"/"كارط").
    assert "45730.50" in result["response"]
    assert "العمليات" not in result["response"]
    assert "كارط" not in result["response"]


# ---------------------------------------------------------------------------
# Dernieres operations
# ---------------------------------------------------------------------------


def test_recent_transactions_in_darija(collection, banking_path):
    result = run_agent1(
        "وريني آخر العمليات ديالي",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert "2026-07" in result["response"]


# ---------------------------------------------------------------------------
# Salaire cette semaine
# ---------------------------------------------------------------------------


def test_salary_this_week_in_arabic(collection, banking_path):
    result = run_agent1(
        "واش دخل ليا الصالير هاد السيمانة؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "12000.00" in result["response"]
    assert "2026-07-25" in result["response"]


def test_salary_this_week_in_arabizi(collection, banking_path):
    result = run_agent1(
        "wach dkhal lia salaire had simana?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "12000.00" in result["response"]
    assert "2026-07-25" in result["response"]


# ---------------------------------------------------------------------------
# Depenses par categorie/periode
# ---------------------------------------------------------------------------


def test_restaurants_current_month_in_arabic(collection, banking_path):
    result = run_agent1(
        "شحال صرفت فالمطاعم هاد الشهر؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "286.40" in result["response"]  # 89.90 + 120.00 + 76.50


def test_restaurants_current_month_in_arabizi(collection, banking_path):
    result = run_agent1(
        "ch7al sraft f restaurant had chher?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "286.40" in result["response"]


def test_transport_last_month_in_arabic(collection, banking_path):
    result = run_agent1(
        "شحال صرفت فالنقل الشهر اللي فات؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "45.00" in result["response"]


def test_transport_last_month_in_arabizi(collection, banking_path):
    result = run_agent1(
        "ch7al sraft f transport chher li fat?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "45.00" in result["response"]


# ---------------------------------------------------------------------------
# Carte : statut, plafonds, paiement Internet, achat international
# ---------------------------------------------------------------------------


def test_card_status_in_arabic(collection, banking_path):
    result = run_agent1(
        "واش الكارط ديالي خدامة؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert result["response"]  # reponse non vide


def test_card_status_inactive_card_in_arabizi(collection, banking_path):
    # usr_004 a une carte au statut "blocked" dans le jeu de donnees fictif.
    result = run_agent1(
        "wach carte dyali khdama?",
        is_authenticated=True,
        user_id="usr_004",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "active" not in result["response"].lower() or "blocked" in result["response"].lower()


def test_payment_and_withdrawal_limits_in_arabic(collection, banking_path):
    result = run_agent1(
        "شحال هو سقف الأداء والسحب؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "5000.00" in result["response"]
    assert "2000.00" in result["response"]


def test_payment_and_withdrawal_limits_in_arabizi(collection, banking_path):
    result = run_agent1(
        "ch7al plafond dyal paiement w retrait?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "5000.00" in result["response"]
    assert "2000.00" in result["response"]


def test_online_payment_in_arabic(collection, banking_path):
    result = run_agent1(
        "واش نقدر نشري بالكارط من الإنترنت؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert result["response"]


def test_online_payment_in_arabizi(collection, banking_path):
    result = run_agent1(
        "wach n9der nchri biha mn internet?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert result["response"]


def test_international_purchase_in_arabic(collection, banking_path):
    # usr_001 : online=1, international=1
    result = run_agent1(
        "واش نقدر نشري من موقع أجنبي؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["response"]


def test_international_purchase_disabled_in_arabizi(collection, banking_path):
    # usr_002 : online=1, international=0
    result = run_agent1(
        "wach n9der nchri mn site etranger?",
        is_authenticated=True,
        user_id="usr_002",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["response"]


# ---------------------------------------------------------------------------
# Demande personnelle sans session valide
# ---------------------------------------------------------------------------


def test_personal_question_without_session_in_arabic(collection, banking_path):
    result = run_agent1("شحال عندي فالحساب؟", collection=collection, banking_db_path=banking_path)
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is True
    assert "خاصك" in result["response"]


def test_personal_question_without_session_in_arabizi(collection, banking_path):
    result = run_agent1("ch7al 3ndi f compte?", collection=collection, banking_db_path=banking_path)
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is True
    assert "khassk" in result["response"].lower()


# ---------------------------------------------------------------------------
# Action de virement/carte indisponible
# ---------------------------------------------------------------------------


def test_virement_unavailable_in_arabic(collection, banking_path):
    result = run_agent1(
        "حول ليا 500 درهم", is_authenticated=True, user_id="usr_001", collection=collection, banking_db_path=banking_path
    )
    assert result["intent"] == "virement"
    assert "متوفراش" in result["response"]


def test_virement_unavailable_in_arabizi(collection, banking_path):
    result = run_agent1(
        "bghit n7awel 500 MAD",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "virement"
    assert "mtwafrach" in result["response"].lower()


def test_card_block_action_unavailable_in_arabic(collection, banking_path):
    result = run_agent1(
        "بلوكي ليا الكارط", is_authenticated=True, user_id="usr_001", collection=collection, banking_db_path=banking_path
    )
    assert result["intent"] == "compte_action"
    assert "متوفراش" in result["response"]


def test_card_limit_increase_action_unavailable_in_arabizi(collection, banking_path):
    result = run_agent1(
        "zid lia plafond dyal carte",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "compte_action"
    assert "mtwafrach" in result["response"].lower()


# ---------------------------------------------------------------------------
# Audit de robustesse (ETAPE 2) : trois vraies ambiguites/incoherences
# trouvees et corrigees - RIB, "code SMS" et "solde"/"transactions" ont ete
# testes et se sont averes deja corrects (aucun changement necessaire).
# ---------------------------------------------------------------------------


def test_open_account_request_in_arabic_reaches_faq(collection, banking_path):
    """Non-regression : "بغيت نحل حساب" (equivalent arabe de "bghit n7ell
    compte", deja couvert en Arabizi) n'etait pas traduit avant recherche FAQ -
    seul sujet du fichier sans sa paire arabe+latin. Toujours classe
    faq_generale par defaut, mais la recherche ChromaDB est desormais faite
    sur un texte francais normalise plutot que sur l'arabe brut."""
    result = run_agent1("بغيت نحل حساب", collection=collection, banking_db_path=banking_path)
    assert result["intent"] == "faq_generale"
    assert "CIN" in result["response"]


def test_beneficiaries_request_in_arabic(collection, banking_path):
    """Non-regression (bug reel trouve par l'audit) : "شكون هوما البنيفيسيار
    ديالي" ("qui sont mes beneficiaires") tombait dans faq_generale au lieu de
    la vraie liste de beneficiaires - seule la version arabe etait cassee, le
    francais et l'Arabizi fonctionnaient deja (le mot "beneficiaires" y
    apparait tel quel, jamais traduit depuis l'arabe)."""
    result = run_agent1(
        "شكون هوما البنيفيسيار ديالي",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    assert "بنيفيسيار" in result["response"]


def test_lost_card_request_in_arabizi_matches_french_behavior(collection, banking_path):
    """Non-regression, mise a jour apres le correctif classification.py
    (`_is_card_incident`) : "khsart carte dyali" ("j'ai perdu ma carte") doit
    converger vers le MEME comportement que la version francaise "J'ai perdu
    ma carte", desormais correctement classee `faq_generale` (signalement
    d'incident carte -> procedure publique, jamais une lecture de donnee
    personnelle - voir classification.py, `_CARD_INCIDENT_PATTERNS`). Avant ce
    correctif, la version francaise tombait elle-meme (a tort) dans
    "personal_data" ; ce test verifiait alors seulement la convergence entre
    langues sur ce comportement bugue - desormais les deux langues convergent
    sur le comportement CORRECT."""
    result = run_agent1(
        "khsart carte dyali",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "faq_generale"
    assert result["requires_auth"] is False


def test_lost_card_request_in_arabic_matches_french_behavior(collection, banking_path):
    result = run_agent1(
        "خسرت الكارط ديالي",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "faq_generale"
    assert result["requires_auth"] is False


# ---------------------------------------------------------------------------
# Isolation entre deux utilisateurs (en Darija)
# ---------------------------------------------------------------------------


def test_isolation_between_users_in_darija(collection, banking_path):
    result_1 = run_agent1(
        "شحال عندي فالحساب؟", is_authenticated=True, user_id="usr_001", collection=collection, banking_db_path=banking_path
    )
    result_2 = run_agent1(
        "شحال عندي فالحساب؟", is_authenticated=True, user_id="usr_002", collection=collection, banking_db_path=banking_path
    )
    assert result_1["response"] != result_2["response"]
    assert "45730.50" in result_1["response"]
    assert "45730.50" not in result_2["response"]
    assert "11094.10" in result_2["response"]


# ---------------------------------------------------------------------------
# Conservation exacte des montants (pas de float, pas de modification)
# ---------------------------------------------------------------------------


def test_amounts_are_preserved_exactly_across_languages(collection, banking_path):
    result_fr = run_agent1(
        "Combien ai-je dépensé dans les restaurants ce mois-ci ?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    result_ar = run_agent1(
        "شحال صرفت فالمطاعم هاد الشهر؟",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    result_latn = run_agent1(
        "ch7al sraft f restaurant had chher?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert "286.40" in result_fr["response"]
    assert "286.40" in result_ar["response"]
    assert "286.40" in result_latn["response"]


# ---------------------------------------------------------------------------
# Les questions francaises restent inchangees
# ---------------------------------------------------------------------------


def test_french_questions_still_work_unchanged(collection, banking_path):
    result = run_agent1(
        "Combien me reste-t-il au total ?",
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
    )
    assert result["intent"] == "personal_data"
    assert "Le total de vos comptes est de 45730.50 MAD" in result["response"]


def test_french_public_faq_still_works(collection):
    result = run_agent1("Quels documents pour ouvrir un compte ?", collection=collection)
    assert result["intent"] == "faq_generale"
    assert "CIN" in result["response"]


# ---------------------------------------------------------------------------
# Vue d'ensemble / synthèse du compte en Darija (arabe et Arabizi)
#
# Contrepartie Darija des formulations naturelles de synthèse ajoutées côté
# français. Tous ces tests passent par le VRAI pipeline `run_agent1` avec
# `use_llm_router=False` (valeur par défaut) : ils exercent donc exactement le
# chemin DÉTERMINISTE utilisé quand Mistral est indisponible, désactivé ou
# retourne "unclear" — jamais le chemin LLM.
#
# Mesuré avant ajout : ces messages tombaient tous dans `faq_generale`, alors
# que leur équivalent français atteignait déjà `personal_data`.
# Voir `darija_normalization._PHRASE_MAP`.
# ---------------------------------------------------------------------------

# 45730.50 = 15230.50 (courant) + 30500.00 (carnet) pour usr_001.
_EXPECTED_TOTAL_USR_001 = "45730.50"


@pytest.mark.parametrize(
    "message",
    [
        # "Combien me reste-t-il ?"
        "ch7al baqi 3ndi",
        "chhal baqi 3ndi",
        "ch7al baqi 3ndi f compte",
        "شحال باقي عندي",
        # "Détails / aperçu de mon compte"
        "3tini tafasil dyal l7sab",
        "bghit tafasil dyal l7sab",
        "bghit nchouf l7sab dyali",
        "عطيني تفاصيل الحساب",
        "بغيت نشوف الحساب ديالي",
        # "Situation financière"
        "wad3iya maliya dyali",
        "الوضعية المالية ديالي",
        # "Récapitulatif"
        "bghit recapitulatif",
        "3tini recapitulatif dyal l7sab",
    ],
)
def test_darija_account_overview_returns_real_balance(collection, banking_path, message):
    """Chaque formulation Darija de synthèse doit produire le solde réel —
    jamais une réponse FAQ publique, jamais le message générique
    d'`assistant_explain`."""
    result = run_agent1(
        message,
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
        use_llm_router=False,
    )
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    assert _EXPECTED_TOTAL_USR_001 in result["response"]


@pytest.mark.parametrize(
    ("message", "expected_active_marker"),
    [
        # La réponse est localisée dans l'écriture du message d'origine
        # (`response_localizer.localize_card_answer`) : "khdama" en Arabizi,
        # "خدامة" en arabe — la carte de usr_001 est active.
        ("tafasil dyal lkarta", "khdama"),
        ("تفاصيل الكارط ديالي", "خدامة"),
    ],
)
def test_darija_card_details_stay_card_information(collection, banking_path, message, expected_active_marker):
    """Test d'ORDRE en Darija : "détails de ma carte" doit rester une question
    de CARTE et ne jamais être capturé par la règle générique de compte —
    même garantie qu'en français. L'assertion négative sur le solde est le
    point central de ce test."""
    result = run_agent1(
        message,
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
        use_llm_router=False,
    )
    assert result["intent"] == "personal_data"
    assert expected_active_marker in result["response"].lower()
    assert _EXPECTED_TOTAL_USR_001 not in result["response"]


@pytest.mark.parametrize(
    "message",
    [
        "ch7al baqi 3ndi",
        "3tini tafasil dyal l7sab",
        "الوضعية المالية ديالي",
    ],
)
def test_darija_account_overview_requires_authentication(collection, banking_path, message):
    """Sécurité : une demande de synthèse Darija chez un utilisateur NON
    authentifié doit exiger une connexion et ne jamais laisser fuiter une
    donnée bancaire réelle."""
    result = run_agent1(
        message,
        is_authenticated=False,
        collection=collection,
        banking_db_path=banking_path,
        use_llm_router=False,
    )
    assert result["requires_auth"] is True
    assert _EXPECTED_TOTAL_USR_001 not in result["response"]


@pytest.mark.parametrize(
    "message",
    [
        # Questions FAQ publiques en Darija déjà supportées : les nouvelles
        # entrées de synthèse ne doivent pas les transformer en questions
        # personnelles.
        "bghit n7ell compte",
        "khsart carte dyali",
    ],
)
def test_darija_public_questions_not_captured_by_new_overview_rules(collection, message):
    """Non-régression faux positifs en Darija : une question publique reste
    publique malgré les nouvelles entrées de normalisation."""
    result = run_agent1(message, collection=collection, use_llm_router=False)
    assert result["intent"] == "faq_generale"
    assert result["requires_auth"] is False


# ---------------------------------------------------------------------------
# COUVERTURE ÉLARGIE — une intention à la fois, en Arabizi ET en arabe.
#
# Tous ces tests passent par le vrai pipeline `run_agent1` avec
# `use_llm_router=False` : ils exercent donc exclusivement le chemin
# DÉTERMINISTE (Mistral désactivé). La correction attendue est vérifiée sur
# l'intention résolue par `classify_personal_intent` après normalisation —
# la RÉPONSE, elle, est localisée en darija et son texte varie selon la
# langue, on ne l'utilise donc pas comme critère (sauf pour le solde, dont le
# montant n'est jamais traduit).
#
# Mesuré avant enrichissement : 17/33 Arabizi et 10/21 arabe corrects ;
# après : 33/33 et 21/21.
# ---------------------------------------------------------------------------


def _resolved_intent(message):
    """Intention fine obtenue par le chemin déterministe complet
    (détection de langue -> normalisation -> sous-classification)."""
    from agents.agent1_faq.banking_answers import classify_personal_intent
    from agents.agent1_faq.darija_normalization import normalize_darija_message
    from agents.agent1_faq.language_detection import detect_language

    normalized = normalize_darija_message(message) if detect_language(message) != "fr" else message
    return classify_personal_intent(normalized)["intent"]


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        # --- 1. Solde / argent disponible (Arabizi + variantes ortho.) ---
        ("ch7al baqi lia", "total_balance"),
        ("ch7al baqi liya f l7sab", "total_balance"),
        ("ch7el baqi lia", "total_balance"),
        ("chhal baqi liya", "total_balance"),
        ("ch7al 3ndi f l7sab dyali", "total_balance"),
        ("ch7al f l7ssab dyali", "total_balance"),
        ("bghit n3ref ch7al baqi lia", "total_balance"),
        # --- 1bis. Solde (arabe) ---
        ("شحال باقي ليا؟", "total_balance"),
        ("شحال باقي ليا فالحساب؟", "total_balance"),
        ("بغيت نعرف شحال باقي ليا", "total_balance"),
        # --- 2. Détails / aperçu / état du compte ---
        ("bghit nchof l7sab dyali", "total_balance"),
        ("bghit nchouf compte dyali", "total_balance"),
        ("chof lia compte dyali", "total_balance"),
        ("bghit n3ref l7ala dyal compte dyali", "total_balance"),
        ("بغيت نعرف الحالة ديال الحساب ديالي", "total_balance"),
        # --- 3. Transactions / opérations / historique ---
        ("3tini les dernieres operations", "recent_transactions"),
        ("bghit nchof les operations dyali", "recent_transactions"),
        ("chof lia les transactions dyali", "recent_transactions"),
        ("akhir l3amaliyat dyali", "recent_transactions"),
        ("عطيني العمليات الأخيرة", "recent_transactions"),
        ("بغيت نشوف المعاملات ديالي", "recent_transactions"),
        # --- 4. Dépenses ---
        ("bghit n3ref les depenses dyali", "spending_by_category"),
        ("ch7al sraft had chher", "spending_by_category"),
        ("المصاريف ديالي", "spending_by_category"),
        # --- 5-6. Carte / état de la carte ---
        ("l7ala dyal carte dyali", "card_information"),
        ("wach carte dyali khdama", "card_information"),
        ("الحالة ديال الكارط ديالي", "card_information"),
        # --- 7. Bénéficiaires ---
        ("bghit nchof les beneficiaires dyali", "beneficiaries"),
        ("شكون هوما البنيفيسيار ديالي", "beneficiaries"),
        # --- 8. Prélèvements ---
        ("akhir prelevement dyali", "last_direct_debit"),
        ("آخر اقتطاع ديالي", "last_direct_debit"),
        # --- 9. Paiements ---
        ("les paiements dyali", "payments"),
        # --- 10. Salaire ---
        ("wach dkhal lia salaire", "salary"),
        ("الراتب ديالي", "salary"),
        # --- 11-12. Situation financière / récapitulatif ---
        ("bghit resume dyal finances dyali", "total_balance"),
        ("bghit n3ref situation financiere dyali", "total_balance"),
        ("بغيت نعرف الوضعية المالية ديالي", "total_balance"),
        ("بغيت ملخص ديال الحساب", "total_balance"),
    ],
)
def test_darija_enriched_coverage_resolves_expected_intent(message, expected_intent):
    """Couverture élargie Darija/Arabizi/arabe : chaque formulation doit
    atteindre son intention précise via le seul chemin déterministe."""
    assert _resolved_intent(message) == expected_intent


@pytest.mark.parametrize(
    "message",
    [
        "ch7al baqi lia",
        "بغيت نعرف شحال باقي ليا",
        "bghit nchof l7sab dyali",
        "بغيت ملخص ديال الحساب",
    ],
)
def test_darija_enriched_coverage_end_to_end_returns_real_balance(collection, banking_path, message):
    """Bout en bout sur le pipeline réel, Mistral désactivé : le solde réel
    doit apparaître dans la réponse (montants jamais traduits)."""
    result = run_agent1(
        message,
        is_authenticated=True,
        user_id="usr_001",
        collection=collection,
        banking_db_path=banking_path,
        use_llm_router=False,
    )
    assert result["intent"] == "personal_data"
    assert result["requires_auth"] is False
    assert _EXPECTED_TOTAL_USR_001 in result["response"]


@pytest.mark.parametrize(
    "message",
    [
        "ch7al baqi lia",
        "بغيت نعرف شحال باقي ليا",
        "bghit nchof l7sab dyali",
        "المصاريف ديالي",
        "الراتب ديالي",
    ],
)
def test_darija_enriched_coverage_still_requires_authentication(collection, banking_path, message):
    """Sécurité : l'élargissement de la couverture Darija ne doit jamais
    permettre à un utilisateur non authentifié d'obtenir une donnée réelle."""
    result = run_agent1(
        message,
        is_authenticated=False,
        collection=collection,
        banking_db_path=banking_path,
        use_llm_router=False,
    )
    assert result["requires_auth"] is True
    assert _EXPECTED_TOTAL_USR_001 not in result["response"]


@pytest.mark.parametrize(
    "message",
    [
        # Les nouveaux marqueurs de langue ne doivent pas faire basculer un
        # message purement français vers la normalisation Darija.
        "Quel est mon solde ?",
        "Comment ouvrir un compte ?",
        "Quels types de cartes bancaires existent ?",
        "Combien ai-je dépensé dans les restaurants ce mois-ci ?",
    ],
)
def test_new_darija_markers_never_hijack_french_messages(message):
    """Non-régression : aucun des marqueurs Arabizi ajoutés à
    `language_detection.py` n'existe en français standard — un message
    français doit rester détecté "fr" et ne jamais être normalisé."""
    from agents.agent1_faq.language_detection import detect_language

    assert detect_language(message) == "fr"
