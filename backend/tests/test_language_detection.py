"""Tests de la détection déterministe de langue (agents/agent1_faq/language_detection.py)."""
import pytest

from agents.agent1_faq.language_detection import detect_language


@pytest.mark.parametrize(
    "message",
    [
        "Quel est mon solde ?",
        "Comment fonctionne un virement bancaire ?",
        "Combien ai-je dépensé dans les restaurants ce mois-ci ?",
        "Quel est le statut actuel de ma carte ?",
    ],
)
def test_french_detected(message):
    assert detect_language(message) == "fr"


@pytest.mark.parametrize(
    "message",
    [
        "شحال عندي فالحساب؟",
        "شحال عندي فالحساب الجاري؟",
        "شحال عندي فحساب التوفير؟",
        "وريني آخر العمليات ديالي",
        "واش دخل ليا الصالير هاد السيمانة؟",
        "شحال صرفت فالمطاعم هاد الشهر؟",
        "شحال صرفت فالنقل الشهر اللي فات؟",
        "واش الكارط ديالي خدامة؟",
        "شحال هو سقف الأداء والسحب؟",
        "واش نقدر نشري بالكارط من الإنترنت؟",
        "واش نقدر نشري من موقع أجنبي؟",
    ],
)
def test_darija_arabic_script_detected(message):
    assert detect_language(message) == "darija_ar"


@pytest.mark.parametrize(
    "message",
    [
        "ch7al 3ndi f compte?",
        "ch7al 3ndi f compte courant?",
        "wrini akhir les operations dyali",
        "wach dkhal lia salaire had simana?",
        "ch7al sraft f restaurant had chher?",
        "ch7al sraft f transport chher li fat?",
        "wach carte dyali khdama?",
        "ch7al plafond dyal paiement w retrait?",
        "wach n9der nchri biha mn internet?",
        "wach n9der nchri mn site etranger?",
    ],
)
def test_darija_latin_arabizi_detected(message):
    assert detect_language(message) == "darija_latn"
