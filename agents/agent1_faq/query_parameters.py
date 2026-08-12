"""Extraction COMPOSITIONNELLE des paramètres d'une question bancaire personnelle.

Pourquoi ce module existe
-------------------------
La couche d'accès aux données (`banking_db.get_transactions`) supporte déjà
sept filtres : `account_type`, `category`, `transaction_type`, `direction`,
`year_month`, `date_from`, `limit`. La couche langage, elle, n'en extrayait
que deux (`category`, `period`). Le goulot d'étranglement n'était donc pas le
SQL mais la compréhension : « mes 10 derniers paiements restaurant de ce
mois-ci » ne pouvait pas être servie, faute d'extraire `limit=10`,
`category=Restaurants`, `transaction_type=card_payment` et `year_month`.

Ce module produit ces paramètres par COMBINAISON de petits lexiques
indépendants, jamais par reconnaissance de phrases entières. Ajouter une
formulation revient à enrichir un lexique, pas à écrire une règle de plus.

Langues
-------
L'extraction opère sur le texte DÉJÀ NORMALISÉ en français : la darija (arabe
et Arabizi) est ramenée à une forme canonique française en amont par
`darija_normalization.py`. Les trois langues partagent donc un seul jeu de
lexiques — c'est ce qui évite de tripler les règles.

Déterminisme
------------
100 % déterministe, aucun appel LLM. Ce module n'extrait que des PARAMÈTRES de
lecture ; il ne décide jamais d'une authentification, d'une autorisation, ni
de l'accès à un client — ces décisions restent dans `graph.py` et
`classification.py` (voir `CLAUDE.md` §5).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

# Date de référence du jeu de démonstration — importée pour rester cohérente
# avec `banking_db` (jamais l'horloge système, voir `DEMO_REFERENCE_DATE`).
from app.banking import banking_db


@dataclass(frozen=True)
class QueryParameters:
    """Filtres de lecture extraits d'une question. Tous optionnels.

    `None` signifie « non demandé », jamais « valeur par défaut » : c'est
    l'appelant qui décide d'un défaut, pour ne jamais inventer un critère que
    l'utilisateur n'a pas exprimé.
    """

    account_type: Optional[str] = None       # "courant" | "carnet"
    category: Optional[str] = None           # "Restaurants", "Courses", ...
    transaction_type: Optional[str] = None   # "salary", "card_payment", ...
    direction: Optional[str] = None          # "credit" | "debit"
    year_month: Optional[str] = None         # "2026-07"
    date_from: Optional[str] = None          # "2026-07-21"
    exact_date: Optional[str] = None         # "2026-01-01"
    limit: Optional[int] = None              # "les 5 derniers" -> 5
    sort: Optional[str] = None               # "latest"|"oldest"|"largest"|"smallest"
    aggregation: Optional[str] = None        # "total"|"count"|"average"|"max_category"
    amount: Optional[Decimal] = None         # montant recherché, en Decimal
    currency: Optional[str] = None           # "MAD"

    def is_empty(self) -> bool:
        """Vrai si aucun filtre n'a été exprimé — utile pour détecter une
        demande trop vague et poser une question de clarification."""
        return all(getattr(self, field) is None for field in self.__dataclass_fields__)


# ---------------------------------------------------------------------------
# Lexiques — un par dimension, librement combinables.
# ---------------------------------------------------------------------------

# Type de compte. La darija normalisée produit déjà "compte"/"carnet".
_ACCOUNT_TYPE_LEXICON = {
    "courant": (r"\bcourants?\b", r"\bcompte courant\b", r"\bprincipal\b"),
    "carnet": (r"\bcarnets?\b", r"\bepargnes?\b", r"\blivrets?\b", r"\bcompte sur carnet\b"),
}

# Type d'opération, tel que stocké dans `"TRANSACTION".type_operation`.
_TRANSACTION_TYPE_LEXICON = {
    "salary": (r"\bsalaires?\b", r"\bpaies?\b", r"\bremunerations?\b", r"\brevenus?\b"),
    "direct_debit": (r"\bprelevements?\b", r"\bdomiciliations?\b", r"\biqtitaa\b"),
    "withdrawal": (r"\bretraits?\b", r"\bgab\b", r"\bdab\b", r"\bdistributeurs?\b"),
    "card_payment": (r"\bpaiements? carte\b", r"\bachats? carte\b", r"\bpaiements? par carte\b"),
    "incoming_transfer": (r"\bvirements? recus?\b", r"\bvirements? entrants?\b"),
}

# Sens de l'opération.
_DIRECTION_LEXICON = {
    "credit": (
        # "entrees" (participe au féminin pluriel) ne matchait pas `\bentres?\b`
        # — c'est ce qui faisait échouer « quelles sommes sont entrées ? ».
        r"\brecus?\b", r"\bentrees?\b", r"\bentres?\b", r"\bentrants?\b", r"\brentres?\b",
        r"\bcredits?\b", r"\bencaisses?\b", r"\bverses?\b", r"\best entre\b",
    ),
    "debit": (
        r"\bsortis?\b", r"\bsortants?\b", r"\bdepenses?\b", r"\bdepenses?\b",
        r"\bdebits?\b", r"\bpayes?\b", r"\bregles?\b",
    ),
}

# Tri demandé.
_SORT_LEXICON = {
    "largest": (r"\bplus (gros|grand|grosse|eleve|elevee|important|importante)\b", r"\bmaximum\b", r"\bmax\b"),
    "smallest": (r"\bplus (petit|petite|faible|bas|basse)\b", r"\bminimum\b", r"\bmin\b"),
    "oldest": (r"\bpremiere?s?\b", r"\bplus ancienne?s?\b", r"\bplus vieille?s?\b"),
    "latest": (r"\bdernie(r|re)s?\b", r"\brecentes?\b", r"\brecents?\b", r"\bderniers\b"),
}

# Agrégation demandée.
_AGGREGATION_LEXICON = {
    # « quelle est ma catégorie de dépense la plus importante ? » — le mot
    # "categorie" et le comparatif "plus" ne sont pas contigus, d'où la
    # fenêtre large et les deux ordres possibles.
    "max_category": (
        r"\bcategorie\b.{0,40}\bplus\b",
        r"\bplus\b.{0,40}\bcategorie\b",
        r"\bprincipal (poste|categorie)\b",
        r"\bfin sraft kter\b",
    ),
    "average": (r"\bmoyennes?\b", r"\ben moyenne\b"),
    "count": (r"\bcombien de\b", r"\bnombre d[e']\b", r"\bcombien d[e']operations\b"),
    "total": (r"\btotal\b", r"\bau total\b", r"\bsommes? totale\b", r"\bcumul\b"),
}

_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}

# Montant : "2000 dh", "2 000 MAD", "1500 dirhams".
_AMOUNT_PATTERN = re.compile(r"\b(\d[\d\s]{0,9})\s*(dh|dhs|mad|dirhams?)\b")
# Nombre de résultats : "les 5 derniers", "10 dernieres operations", "5 premieres".
_LIMIT_PATTERN = re.compile(r"\b(\d{1,3})\s+(?:dernie|premie|plus|operations?|transactions?|paiements?)")
_LIMIT_PATTERN_ALT = re.compile(r"\b(?:les|derniers?|dernieres?|premiers?|premieres?)\s+(\d{1,3})\b")
# Date ISO explicite.
_ISO_DATE_PATTERN = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# Date en toutes lettres : "1er janvier", "15 mars 2026".
_TEXT_DATE_PATTERN = re.compile(
    r"\b(\d{1,2})\s*(?:er|eme)?\s+(" + "|".join(_MONTHS) + r")\b(?:\s+(\d{4}))?"
)


def _match_lexicon(normalized_text: str, lexicon: dict) -> Optional[str]:
    """Première valeur dont l'un des motifs apparaît. L'ordre du lexique fait foi."""
    for value, patterns in lexicon.items():
        if any(re.search(pattern, normalized_text) for pattern in patterns):
            return value
    return None


def _extract_period(normalized_text: str) -> tuple[Optional[str], Optional[str]]:
    """Période relative -> (`year_month`, `date_from`).

    Ancrée sur `banking_db.DEMO_REFERENCE_DATE`, jamais sur l'horloge système :
    la démonstration doit rester reproductible.
    """
    if re.search(r"\b(semaine derniere|semaine passee|semaine precedente)\b", normalized_text):
        from datetime import date, timedelta

        debut = date.fromisoformat(banking_db.DEMO_THIS_WEEK_START) - timedelta(days=7)
        return None, debut.isoformat()
    if re.search(r"\b(cette semaine|semaine en cours|had l ?simana)\b", normalized_text):
        return None, banking_db.DEMO_THIS_WEEK_START
    if re.search(r"\b(mois dernier|mois precedent|mois passe|le mois d avant)\b", normalized_text):
        return banking_db.DEMO_LAST_MONTH, None
    if re.search(r"\b(ce mois|mois en cours|mois actuel|mois ci)\b", normalized_text):
        return banking_db.DEMO_CURRENT_MONTH, None
    if re.search(r"\b(cette annee|annee en cours)\b", normalized_text):
        return None, f"{banking_db.DEMO_REFERENCE_DATE[:4]}-01-01"
    return None, None


def _extract_exact_date(normalized_text: str) -> Optional[str]:
    """Date exacte : ISO (`2026-01-01`) ou en toutes lettres (`1er janvier`)."""
    iso = _ISO_DATE_PATTERN.search(normalized_text)
    if iso:
        return iso.group(0)

    textual = _TEXT_DATE_PATTERN.search(normalized_text)
    if textual:
        day = int(textual.group(1))
        month = _MONTHS[textual.group(2)]
        year = textual.group(3) or banking_db.DEMO_REFERENCE_DATE[:4]
        return f"{year}-{month:02d}-{day:02d}"

    if re.search(r"\bhier\b", normalized_text):
        from datetime import date, timedelta

        veille = date.fromisoformat(banking_db.DEMO_REFERENCE_DATE) - timedelta(days=1)
        return veille.isoformat()
    return None


def _extract_limit(normalized_text: str) -> Optional[int]:
    """Nombre de résultats demandé. Borné à 50 pour ne jamais déverser la base."""
    for pattern in (_LIMIT_PATTERN, _LIMIT_PATTERN_ALT):
        found = pattern.search(normalized_text)
        if found:
            value = int(found.group(1))
            if 1 <= value <= 50:
                return value
    return None


def _extract_amount(normalized_text: str) -> tuple[Optional[Decimal], Optional[str]]:
    """Montant recherché. Toujours `Decimal`, jamais `float` (`CLAUDE.md` règle 7)."""
    found = _AMOUNT_PATTERN.search(normalized_text)
    if not found:
        return None, None
    digits = found.group(1).replace(" ", "")
    if not digits:
        return None, None
    return Decimal(digits), "MAD"


def extract_query_parameters(normalized_text: str, category_resolver=None) -> QueryParameters:
    """Extrait tous les filtres exprimés dans une question déjà normalisée.

    `category_resolver` est injecté par l'appelant (`banking_answers._find_category`)
    pour réutiliser le lexique de catégories existant sans le dupliquer ici —
    et sans créer d'import circulaire.
    """
    year_month, date_from = _extract_period(normalized_text)
    amount, currency = _extract_amount(normalized_text)

    return QueryParameters(
        account_type=_match_lexicon(normalized_text, _ACCOUNT_TYPE_LEXICON),
        category=category_resolver(normalized_text) if category_resolver else None,
        transaction_type=_match_lexicon(normalized_text, _TRANSACTION_TYPE_LEXICON),
        direction=_match_lexicon(normalized_text, _DIRECTION_LEXICON),
        year_month=year_month,
        date_from=date_from,
        exact_date=_extract_exact_date(normalized_text),
        limit=_extract_limit(normalized_text),
        sort=_match_lexicon(normalized_text, _SORT_LEXICON),
        aggregation=_match_lexicon(normalized_text, _AGGREGATION_LEXICON),
        amount=amount,
        currency=currency,
    )
