"""Normalisation des messages Darija (arabe ou Arabizi) vers des termes
canoniques français reconnus par le classificateur existant.

Couche linguistique strictement séparée de la logique métier. La sortie de
`normalize_darija_message` est envoyée **uniquement** au système de
classification existant (`classification.classify_intent`,
`banking_answers.classify_personal_intent`) — elle n'est **jamais** utilisée
pour construire une requête SQL (voir `CLAUDE.md` : `banking_db.py` continue
de ne recevoir que des `customer_id`/catégories/périodes déjà validés par ce
classificateur, jamais un texte libre).

Approche déterministe à deux niveaux :
1. Correspondances de **phrases complètes** (les plus fiables), calquées sur
   les tournures Darija les plus courantes pour les questions bancaires.
2. Repli par substitution **mot à mot** (best-effort), pour une couverture
   raisonnable au-delà des phrases explicitement répertoriées.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 1. Phrases completes (arabe et latin/Arabizi) -> equivalent francais canonique
#    directement exploitable par le classificateur existant. Verifiees en
#    premier, de la plus longue a la plus courte, sur le texte original
#    (arabe) et sur le texte en minuscules (latin).
# ---------------------------------------------------------------------------
_PHRASE_MAP: list[tuple[str, str]] = [
    # --- Solde ---
    ("شحال عندي فالحساب الجاري", "quel est mon solde compte courant"),
    ("شحال عندي فحساب التوفير", "quel est mon solde compte epargne"),
    ("شحال عندي فالحساب", "quel est mon solde total"),
    ("ch7al 3ndi f compte courant", "quel est mon solde compte courant"),
    ("ch7al 3ndi f compte", "quel est mon solde total"),
    # --- Dernieres operations ---
    ("وريني آخر العمليات ديالي", "montre-moi mes dernieres operations"),
    ("آخر العمليات", "dernieres operations"),
    ("wrini akhir les operations dyali", "montre-moi mes dernieres operations"),
    # --- Salaire ---
    ("واش دخل ليا الصالير هاد السيمانة", "ai-je recu mon salaire cette semaine"),
    ("wach dkhal lia salaire had simana", "ai-je recu mon salaire cette semaine"),
    # --- Depenses par categorie ---
    ("شحال صرفت فالمطاعم هاد الشهر", "combien ai-je depense dans les restaurants ce mois-ci"),
    ("شحال صرفت فالنقل الشهر اللي فات", "combien ai-je depense en transport le mois dernier"),
    ("ch7al sraft f restaurant had chher", "combien ai-je depense dans les restaurants ce mois-ci"),
    ("ch7al sraft f transport chher li fat", "combien ai-je depense en transport le mois dernier"),
    # --- Carte : statut ---
    ("واش الكارط ديالي خدامة", "quel est le statut de ma carte"),
    ("واش الكارط خدامة", "quel est le statut de ma carte"),
    ("wach carte dyali khdama", "quel est le statut de ma carte"),
    ("wach carte khdama", "quel est le statut de ma carte"),
    # --- FAQ publique : ouverture de compte ---
    ("bghit n7ell compte bancaire", "je veux ouvrir un compte bancaire"),
    ("bghit n7ell compte", "je veux ouvrir un compte"),
    # --- Carte : plafonds ---
    ("شحال هو سقف الأداء والسحب", "quel est le plafond de paiement et le plafond de retrait de ma carte"),
    ("سقف الأداء", "plafond de paiement"),
    ("سقف السحب", "plafond de retrait"),
    ("ch7al plafond dyal paiement w retrait", "quel est le plafond de paiement et le plafond de retrait de ma carte"),
    # --- Carte : paiement en ligne / international ---
    ("واش نقدر نشري بالكارط من الإنترنت", "ma carte permet-elle les paiements en ligne"),
    ("واش نقدر نشري من موقع أجنبي", "puis-je acheter avec ma carte sur un site etranger"),
    ("wach n9der nchri biha mn internet", "ma carte permet-elle les paiements en ligne"),
    ("wach n9der nchri mn site etranger", "puis-je acheter avec ma carte sur un site etranger"),
    # --- Actions indisponibles (virement / carte) ---
    ("حول ليا 500 درهم", "je veux virer 500 MAD"),
    ("bghit n7awel 500", "je veux virer 500 MAD"),
    ("بلوكي ليا الكارط", "je veux bloquer ma carte"),
    ("zid lia plafond dyal carte", "je veux augmenter le plafond de ma carte"),
]
_PHRASE_MAP.sort(key=lambda item: -len(item[0]))

# ---------------------------------------------------------------------------
# 2. Repli mot-a-mot (vocabulaire general, voir enonce de la tache).
# ---------------------------------------------------------------------------
_WORD_MAP: list[tuple[str, str]] = [
    ("الحساب الجاري", "compte courant"),
    ("حساب التوفير", "compte epargne"),
    ("هاد الشهر", "ce mois-ci"),
    ("had chher", "ce mois-ci"),
    ("الشهر اللي فات", "mois dernier"),
    ("chher li fat", "mois dernier"),
    ("هاد السيمانة", "cette semaine"),
    ("had simana", "cette semaine"),
    ("موقع أجنبي", "site etranger"),
    ("site etranger", "site etranger"),
    ("شحال", "combien"),
    ("ch7al", "combien"),
    ("عندي", "j'ai"),
    ("3ndi", "j'ai"),
    ("الحساب", "compte"),
    ("الكارط", "carte"),
    ("خدامة", "active"),
    ("khdama", "active"),
    ("الصالير", "salaire"),
    ("المطاعم", "restaurants"),
    ("restaurant", "restaurants"),
    ("النقل", "transport"),
    ("الإنترنت", "paiement en ligne internet"),
    ("نقدر", "je peux"),
    ("n9der", "je peux"),
    ("صرفت", "j'ai depense"),
    ("sraft", "j'ai depense"),
    ("دخل ليا", "j'ai recu"),
    ("dkhal lia", "j'ai recu"),
    ("حول ليا", "je veux virer"),
    ("n7awel", "je veux virer"),
    ("بلوكي", "je veux bloquer"),
    ("زيد ليا", "je veux augmenter"),
    ("zid lia", "je veux augmenter"),
    ("ديالي", "mon"),
    ("dyali", "mon"),
    ("dyalek", "mon"),
    ("dyal", "de"),
    ("bghit", "je veux"),
    ("n7ell", "ouvrir"),
    ("واش", ""),
    ("wach", ""),
]
_WORD_MAP.sort(key=lambda item: -len(item[0]))


def normalize_darija_message(message: str) -> str:
    """Convertit une formulation Darija (arabe ou latine/Arabizi) vers des
    termes canoniques français reconnus par le classificateur existant.

    N'est **jamais** utilisée pour construire une requête SQL — uniquement
    pour alimenter la classification déterministe existante.
    """
    if not message:
        return message

    stripped = message.strip()
    lowered = stripped.lower()

    for phrase, replacement in _PHRASE_MAP:
        if phrase in stripped or phrase in lowered:
            return replacement

    normalized = lowered
    for token, replacement in _WORD_MAP:
        if token in normalized or token in stripped:
            normalized = normalized.replace(token, replacement)
            # Egalement applique sur le texte original pour les tokens arabes
            # (la version "lowered" d'un texte arabe est identique au texte
            # original - l'appel ci-dessus suffit dans les deux cas).

    return re.sub(r"\s+", " ", normalized).strip()
