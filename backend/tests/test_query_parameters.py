"""Extraction compositionnelle des paramètres (agents/agent1_faq/query_parameters.py).

Tests PARAMÉTRÉS et COMBINATOIRES : chaque dimension est testée isolément,
puis en combinaison libre — jamais sur une liste finie de phrases.

L'extraction opère sur du français normalisé ; la darija (arabe et Arabizi)
y est ramenée en amont par `darija_normalization.py`, ce qui permet aux trois
langues de partager un seul jeu de lexiques.
"""
import itertools
from decimal import Decimal

import pytest

from agents.agent1_faq.banking_answers import _find_category, _normalize
from agents.agent1_faq.darija_normalization import normalize_darija_message
from agents.agent1_faq.language_detection import detect_language
from agents.agent1_faq.query_parameters import QueryParameters, extract_query_parameters
from app.banking import banking_db


def _extract(message: str) -> QueryParameters:
    """Chaîne complète : détection de langue -> normalisation -> extraction."""
    texte = message if detect_language(message) == "fr" else normalize_darija_message(message)
    return extract_query_parameters(_normalize(texte), category_resolver=_find_category)


# ---------------------------------------------------------------------------
# 1. Chaque dimension, isolément
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "attendu"),
    [
        ("sur mon compte courant", "courant"),
        ("mon compte sur carnet", "carnet"),
        ("mon épargne", "carnet"),
        ("mon livret", "carnet"),
    ],
)
def test_account_type_extraction(message, attendu):
    assert _extract(message).account_type == attendu


@pytest.mark.parametrize(
    ("message", "attendu"),
    [
        ("mon salaire", "salary"),
        ("mes prélèvements", "direct_debit"),
        ("mes retraits GAB", "withdrawal"),
        ("mes paiements carte", "card_payment"),
        ("les virements reçus", "incoming_transfer"),
    ],
)
def test_transaction_type_extraction(message, attendu):
    assert _extract(message).transaction_type == attendu


@pytest.mark.parametrize(
    ("message", "attendu"),
    [
        ("combien est entré", "credit"),
        ("ce que j'ai reçu", "credit"),
        ("combien est sorti", "debit"),
        ("ce que j'ai dépensé", "debit"),
    ],
)
def test_direction_extraction(message, attendu):
    assert _extract(message).direction == attendu


@pytest.mark.parametrize(
    ("message", "attendu"),
    [
        ("mes dernières opérations", "latest"),
        ("mes premières opérations", "oldest"),
        ("mon plus gros retrait", "largest"),
        ("ma plus petite dépense", "smallest"),
    ],
)
def test_sort_extraction(message, attendu):
    assert _extract(message).sort == attendu


@pytest.mark.parametrize(
    ("message", "attendu"),
    [
        ("combien au total", "total"),
        ("combien de transactions", "count"),
        ("ma dépense moyenne", "average"),
        ("quelle catégorie ai-je le plus dépensé", "max_category"),
    ],
)
def test_aggregation_extraction(message, attendu):
    assert _extract(message).aggregation == attendu


@pytest.mark.parametrize(
    ("message", "champ", "attendu"),
    [
        ("ce mois-ci", "year_month", banking_db.DEMO_CURRENT_MONTH),
        ("le mois dernier", "year_month", banking_db.DEMO_LAST_MONTH),
        ("cette semaine", "date_from", banking_db.DEMO_THIS_WEEK_START),
        ("la semaine dernière", "date_from", "2026-07-14"),
        ("cette année", "date_from", "2026-01-01"),
    ],
)
def test_relative_period_extraction(message, champ, attendu):
    assert getattr(_extract(message), champ) == attendu


@pytest.mark.parametrize(
    ("message", "attendu"),
    [
        ("au 1er janvier", "2026-01-01"),
        ("le 15 mars", "2026-03-15"),
        ("le 2026-02-10", "2026-02-10"),
        ("hier", "2026-07-27"),
    ],
)
def test_exact_date_extraction(message, attendu):
    assert _extract(message).exact_date == attendu


@pytest.mark.parametrize(
    ("message", "attendu"),
    [("les 5 derniers", 5), ("mes 10 dernières opérations", 10), ("les 3 premières", 3)],
)
def test_limit_extraction(message, attendu):
    assert _extract(message).limit == attendu


def test_limit_is_bounded():
    """Un nombre absurde ne doit jamais déverser la base."""
    assert _extract("mes 9999 dernières opérations").limit is None


@pytest.mark.parametrize(
    ("message", "attendu"),
    [("2000 MAD", Decimal("2000")), ("1500 dh", Decimal("1500")), ("2 000 dirhams", Decimal("2000"))],
)
def test_amount_extraction_is_decimal(message, attendu):
    parametres = _extract(message)
    assert parametres.amount == attendu
    assert isinstance(parametres.amount, Decimal)  # jamais float (CLAUDE.md règle 7)
    assert parametres.currency == "MAD"


# ---------------------------------------------------------------------------
# 2. COMBINATOIRE : les dimensions doivent se composer librement
# ---------------------------------------------------------------------------

_COMPTES = [("sur mon compte courant", "courant"), ("sur mon carnet", "carnet")]
_PERIODES = [("ce mois-ci", banking_db.DEMO_CURRENT_MONTH), ("le mois dernier", banking_db.DEMO_LAST_MONTH)]
_CATEGORIES = [("en restaurants", "Restaurants"), ("en transport", "Transport")]


@pytest.mark.parametrize(
    ("compte", "periode", "categorie"), list(itertools.product(_COMPTES, _PERIODES, _CATEGORIES))
)
def test_dimensions_compose_freely(compte, periode, categorie):
    """8 combinaisons générées : compte × période × catégorie.

    Aucune de ces phrases n'est codée en dur — elles sont assemblées par le
    test lui-même, ce qui prouve la compositionnalité."""
    message = f"combien ai-je dépensé {categorie[0]} {compte[0]} {periode[0]}"
    parametres = _extract(message)
    assert parametres.account_type == compte[1]
    assert parametres.year_month == periode[1]
    assert parametres.category == categorie[1]


def test_complex_request_extracts_every_dimension():
    """« Mes 10 derniers paiements restaurant de ce mois-ci » — 4 dimensions."""
    parametres = _extract("Montre-moi mes 10 derniers paiements restaurant de ce mois-ci")
    assert parametres.limit == 10
    assert parametres.sort == "latest"
    assert parametres.category == "Restaurants"
    assert parametres.year_month == banking_db.DEMO_CURRENT_MONTH


def test_incoming_amount_on_a_given_account():
    """« Combien est entré sur mon compte courant ? » — direction + compte."""
    parametres = _extract("Combien est entré sur mon compte courant cette semaine ?")
    assert parametres.direction == "credit"
    assert parametres.account_type == "courant"
    assert parametres.date_from == banking_db.DEMO_THIS_WEEK_START


def test_amount_and_date_together():
    parametres = _extract("Est-ce qu'un paiement de 2000 MAD est arrivé hier ?")
    assert parametres.amount == Decimal("2000")
    assert parametres.exact_date == "2026-07-27"


# ---------------------------------------------------------------------------
# 3. Multilingue — les trois langues partagent les mêmes lexiques
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "champ", "attendu"),
    [
        ("ch7al sraft had chher", "year_month", banking_db.DEMO_CURRENT_MONTH),
        ("ch7al sraft chher lli fat", "year_month", banking_db.DEMO_LAST_MONTH),
        ("شحال صرفت هاد الشهر", "year_month", banking_db.DEMO_CURRENT_MONTH),
    ],
)
def test_periods_work_in_darija_and_arabizi(message, champ, attendu):
    """La darija est ramenée au français avant extraction : un seul lexique
    couvre les trois langues."""
    assert getattr(_extract(message), champ) == attendu


# ---------------------------------------------------------------------------
# 4. Absence de filtre — ne jamais inventer un critère
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", ["mes opérations", "mon compte", "bonjour"])
def test_no_filter_is_invented_when_none_is_expressed(message):
    """`None` signifie « non demandé », jamais une valeur par défaut : c'est
    ce qui permet à l'appelant de détecter une demande trop vague."""
    parametres = _extract(message)
    assert parametres.amount is None
    assert parametres.exact_date is None
    assert parametres.limit is None


def test_is_empty_detects_a_request_without_any_filter():
    assert _extract("bonjour").is_empty()
    assert not _extract("mes 5 dernières opérations").is_empty()


def test_extraction_is_deterministic():
    """Même entrée, même sortie — condition d'une démonstration reproductible."""
    message = "mes 10 derniers paiements restaurant de ce mois-ci"
    assert [_extract(message) for _ in range(3)].count(_extract(message)) == 3
