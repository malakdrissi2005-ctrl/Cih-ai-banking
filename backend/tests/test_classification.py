"""Tests du classifieur d'intention déterministe (agents/agent1_faq/classification.py)."""
import json
from pathlib import Path

import pytest

from agents.agent1_faq.classification import classify_intent

REPO_ROOT = Path(__file__).resolve().parents[2]
FAQ_PATH = REPO_ROOT / "data" / "faq_docs" / "faq.json"

# Limite connue et documentée (voir classification.py, _PROCEDURAL_FAQ_PREFIX) :
# formulée avec "puis-je", cette question FAQ publique reste mal classée en
# personal_data ("mon compte"). Un correctif complet nécessiterait une
# heuristique plus fine, hors périmètre de ce classifieur déterministe.
KNOWN_MISCLASSIFIED_FAQ_IDS = {"faq_009"}


@pytest.mark.parametrize(
    "message",
    [
        "Je veux virer 500 DH à Youssef",
        "Peux-tu faire un virement de 1000 dirhams vers mon frère ?",
        "J'aimerais transférer de l'argent à ma mère",
    ],
)
def test_virement_detected(message):
    assert classify_intent(message) == "virement"


@pytest.mark.parametrize(
    "message",
    [
        "Quel est mon solde actuel ?",
        "Montre-moi mes dernières transactions",
        "Je veux voir l'historique de mon compte",
        "Quels sont mes bénéficiaires enregistrés ?",
        # Questions bancaires personnelles supportées par l'Agent 1 authentifié
        "Combien me reste-t-il au total en additionnant mon compte courant et mon compte sur carnet ?",
        "Ai-je reçu un virement de mon salaire cette semaine ?",
        "Combien ai-je dépensé ce mois-ci dans la catégorie Restaurants ?",
        "Quel était mon solde exact au 1er janvier de cette année ?",
        "Quelles sont mes dernières opérations ?",
        "Affiche mes paiements du mois.",
        "À quelle date mon salaire a-t-il été crédité ?",
        "Quel est le dernier prélèvement effectué sur mon compte ?",
        "Quel est le plafond actuel de ma carte ?",
        "Ma carte permet-elle les achats en ligne ?",
        "Ma carte permet-elle les achats sur des sites internationaux ?",
        "Quel est le statut actuel de ma carte ?",
        # Questions combinees sur la carte (multi-intentions)
        "Donne-moi le statut actuel de ma carte ainsi que ses plafonds de paiement et de retrait.",
        "Ma carte est-elle active et autorisée pour les paiements sur Internet ?",
        "Est-ce que je peux utiliser ma carte pour effectuer un achat sur un site étranger ?",
        "Quels sont actuellement le plafond de paiement et le plafond de retrait associés à ma carte ?",
        "Vérifie si ma carte autorise les paiements en ligne et les paiements internationaux.",
        # Questions de depenses par categorie/periode
        "Combien ai-je dépensé dans les restaurants pendant le mois en cours ?",
        "Combien ai-je dépensé dans les restaurants ce mois-ci ?",
        "Quel montant ai-je consacré au transport le mois dernier ?",
        "Combien ai-je dépensé en transport durant le mois précédent ?",
        "Combien ai-je dépensé dans les supermarchés ce mois-ci ?",
    ],
)
def test_personal_data_detected(message):
    assert classify_intent(message) == "personal_data"


@pytest.mark.parametrize(
    "message",
    [
        "Je veux augmenter le plafond de ma carte",
        "Peux-tu augmenter mon plafond ?",
        "Merci de bloquer ma carte",
        "Peux-tu débloquer ma carte ?",
    ],
)
def test_account_action_detected(message):
    assert classify_intent(message) == "compte_action"


@pytest.mark.parametrize(
    "message",
    [
        "Quels sont les papiers nécessaires pour ouvrir un compte CIH ?",
        "Quels sont les frais de tenue de compte ?",
        "Quelles sont vos horaires d'agence ?",
        # Questions FAQ publiques bien réelles de data/faq_docs/faq.json (catégorie
        # "virements") : mentionnent le mot "virement" sans exprimer de demande
        # explicite -> ne doivent jamais être classées comme une demande de virement.
        "Comment fonctionne un virement bancaire ?",
        "Quelle est la différence entre un virement interne et un virement externe ?",
        "Quel est le délai habituel d'exécution d'un virement ?",
        "Un virement peut-il être annulé après son exécution ?",
        "Qu'est-ce qu'un virement permanent ?",
        # Questions FAQ publiques réelles sur les cartes : mentionnent "carte" sans
        # possessif ("ma carte") -> ne doivent jamais être classées comme personnelles.
        "Quels types de cartes bancaires existent ?",
        "Comment demander une nouvelle carte bancaire ?",
        "Quelle est la durée de validité d'une carte bancaire ?",
    ],
)
def test_public_faq_detected(message):
    assert classify_intent(message) == "faq_generale"


@pytest.mark.parametrize(
    "message",
    [
        "Mon compte est bloqué",
        "Mon compte est verrouillé",
        "Mon accès est bloqué",
        "Je n'arrive plus à accéder à mon compte",
        "compte bloqué",
        "mon compte ne marche plus",
    ],
)
def test_account_lock_incident_detected_as_faq(message):
    """Régression : un signalement d'incident d'accès/blocage de COMPTE est une
    question de procédure (FAQ publique), jamais une lecture de donnée
    personnelle réelle — même principe que les incidents CARTE (voir
    `test_public_faq_detected`, "Quelle est la durée de validité d'une carte
    bancaire ?" etc.). Avant correctif, `\bmon compte\b`
    (`_PERSONAL_DATA_PATTERNS`) faisait basculer ces messages vers
    "personal_data" dans le repli déterministe, alors que Mistral les classe
    déjà correctement en `faq_search` en fonctionnement normal — voir
    classification.py, `_ACCOUNT_LOCK_INCIDENT_PATTERNS`."""
    assert classify_intent(message) == "faq_generale"


@pytest.mark.parametrize(
    "message",
    [
        "J'ai détecté une fraude sur mon compte",
        "Je pense que mon compte a été piraté",
        "Il y a une activité suspecte sur mon compte",
        "Je ne reconnais pas une transaction sur mon compte",
        "Mon compte a été compromis",
    ],
)
def test_fraud_incident_detected_as_faq(message):
    """Régression : un signalement de fraude/incident de sécurité est une
    question de procédure urgente (FAQ publique, voir faq_053), jamais une
    lecture de donnée personnelle réelle — voir classification.py,
    `_FRAUD_INCIDENT_PATTERNS`. Avant correctif, `\bmon compte\b`/
    `\btransactions?\b` (`_PERSONAL_DATA_PATTERNS`) faisaient basculer ces
    messages vers "personal_data" (connexion requise) au lieu de donner
    immédiatement la consigne de sécurité publique."""
    assert classify_intent(message) == "faq_generale"


@pytest.mark.parametrize(
    "message",
    [
        "J'ai perdu ma carte",
        "carte perdue",
        "On m'a volé ma carte",
        "Ma carte ne marche plus",
    ],
)
def test_card_incident_detected_as_faq(message):
    """Régression signalée après la simplification du prompt Mistral : "J'ai
    perdu ma carte" retournait à tort "Pour consulter vos informations
    personnelles, vous devez d'abord vous connecter" (repli déterministe
    `classify_fallback`) au lieu de la réponse FAQ incident carte attendue.

    Cause confirmée (voir investigation) : `graph.py` était INCHANGÉ ("unclear"
    route toujours vers `classify_fallback`, aucun court-circuit) et l'exemple
    "J'ai perdu ma carte" -> card_query était toujours présent dans
    `llm_router._SYSTEM_PROMPT` — le vrai trou était ici, dans
    `classification.py` : `\bma carte\b` (`_PERSONAL_DATA_PATTERNS`) faisait
    basculer ces messages vers "personal_data" dans le repli déterministe,
    exactement comme "mon compte est bloqué" avant son propre correctif — un
    trou pré-existant, jamais couvert avant, simplement révélé maintenant.
    Voir `classification.py`, `_CARD_INCIDENT_PATTERNS`/`_is_card_incident`."""
    assert classify_intent(message) == "faq_generale"


@pytest.mark.parametrize(
    "message",
    [
        "Quel est le solde de mon compte ?",
        "Je veux voir l'historique de mon compte",
        "Mon compte",
    ],
)
def test_account_lock_fix_does_not_affect_real_personal_questions(message):
    """Non-régression : une vraie question personnelle mentionnant "mon compte"
    sans terme d'incident (bloqué/verrouillé/suspendu/accès impossible) reste
    classée "personal_data", exactement comme avant le correctif."""
    assert classify_intent(message) == "personal_data"


def test_card_incident_fix_does_not_affect_precise_card_info_requests(message="Quel est le statut de ma carte ?"):
    """Non-régression : une vraie demande d'information précise sur la carte
    (statut/numéro/plafond) reste classée "personal_data", même si elle
    mentionne "ma carte" — l'exclusion `_is_card_incident` ne s'applique
    jamais dans ce cas (voir `_CARD_PRECISE_INFO_PATTERNS`)."""
    assert classify_intent(message) == "personal_data"


# ---------------------------------------------------------------------------
# Généralisation architecturale (voir échange "je ne veux plus corriger les
# erreurs question par question") : formulations JAMAIS vues, absentes de
# `_ACCOUNT_LOCK_INCIDENT_PATTERNS`/`_FRAUD_INCIDENT_PATTERNS`/
# `_CARD_INCIDENT_PATTERNS` — si ces tests passent, c'est grâce au lexique
# générique `_is_generic_problem_report` (mots-problème x sujets bancaires),
# pas grâce à une règle ajoutée pour ces phrases précises.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "J'ai un souci avec ma carte",
        "Mon compte a un problème de connexion",
        "Ma carte pose problème",
        "J'ai un problème avec mon code SMS",
        "Je ne reçois pas mon code par SMS",
        "Mon accès pose souci",
        "J'ai un souci pour me connecter à mon compte",
    ],
)
def test_generic_problem_report_generalizes_to_unseen_phrasings(message):
    """Formulations absentes de toute liste d'incident spécifique existante —
    prouve que la généralisation vient du lexique générique
    (`_is_generic_problem_report`), pas d'une règle par phrase."""
    assert classify_intent(message) == "faq_generale"


@pytest.mark.parametrize(
    "message",
    [
        "Comment fonctionne la connexion à l'espace client ?",
        "Quels sont les avantages de l'application mobile ?",
    ],
)
def test_generic_problem_report_does_not_over_trigger_on_public_faq_questions(message):
    """Non-régression : une vraie question FAQ publique mentionnant un sujet
    du lexique générique (connexion, application) mais SANS mot-problème
    reste "faq_generale" pour la bonne raison (aucun trigger personal_data),
    pas parce que `_is_generic_problem_report` l'exclurait à tort."""
    assert classify_intent(message) == "faq_generale"


def test_real_faq_json_is_not_misclassified_as_personal_or_action():
    """Régression : les 98 vraies questions de data/faq_docs/faq.json doivent
    toutes rester `faq_generale` (à l'exception du cas connu et documenté ci-dessus)."""
    entries = json.loads(FAQ_PATH.read_text(encoding="utf-8"))
    unexpected = [
        (entry["id"], entry["question"], classify_intent(entry["question"]))
        for entry in entries
        if entry["id"] not in KNOWN_MISCLASSIFIED_FAQ_IDS and classify_intent(entry["question"]) != "faq_generale"
    ]
    assert unexpected == []
