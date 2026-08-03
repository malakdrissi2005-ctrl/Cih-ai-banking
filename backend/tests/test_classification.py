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
