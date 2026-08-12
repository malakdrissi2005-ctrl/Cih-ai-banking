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
    # --- Ajout audit robustesse : equivalent arabe de "bghit n7ell compte"
    # ci-dessus (seul manquant du fichier - tous les autres sujets ont deja
    # leur paire arabe+latin). Sans cette entree, le texte arabe brut atteint
    # quand meme le bucket faq_generale (bucket par defaut), mais sans etre
    # traduit avant la recherche ChromaDB - qualite de recherche degradee. ---
    ("بغيت نحل حساب", "je veux ouvrir un compte"),
    # --- Enrichissement : tournures dont la reconstruction mot-a-mot resterait
    # ambigue ("بغيت ملخص ديال الحساب" -> "je veux resume de compte", sans
    # possessif, donc non reconnu comme personnel). Traitees en phrase entiere,
    # comme les autres cas irreguliers ci-dessus. ---
    ("بغيت ملخص ديال الحساب", "quelles sont les informations de mon compte"),
    ("بغيت ملخص ديال الحساب ديالي", "quelles sont les informations de mon compte"),
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
    # --- Informations générales sur le compte ---
    ("عطيني المعلومات على الحساب", "quelles sont les informations de mon compte"),
    ("3afak 3tini lma3lomat 3la l7sab", "quelles sont les informations de mon compte"),
    ("afak 3tini lma3lomat 3la lhsab", "quelles sont les informations de mon compte"),
    ("3tini lma3lomat 3la l7sab", "quelles sont les informations de mon compte"),
    ("bghit lma3lomat 3la compte dyali", "quelles sont les informations de mon compte"),
    # --- Ajout audit robustesse : "carte perdue" en Arabizi/arabe tombait dans
    # faq_generale au lieu de personal_data (incoherent avec la version
    # francaise "J'ai perdu ma carte", deja classee personal_data - voir
    # classification.classify_intent, inchange). Mappe directement vers la
    # phrase francaise declenchante exacte pour garantir, par construction, le
    # meme resultat que la version francaise dans les deux chemins (LLM et
    # deterministe) - jamais une nouvelle branche de logique. ---
    ("khsart carte dyali", "j'ai perdu ma carte"),
    ("wdart carte dyali", "j'ai perdu ma carte"),
    ("خسرت الكارط ديالي", "j'ai perdu ma carte"),
    # --- Vue d'ensemble / synthèse du compte (Darija) ---
    # Contrepartie Darija des formulations naturelles de synthèse désormais
    # reconnues côté français (voir `classification._PERSONAL_DATA_PATTERNS`
    # et `banking_answers._ACCOUNT_OVERVIEW_GROUPS`). Mesuré avant ajout :
    # ces messages tombaient tous à tort dans `faq_generale`, alors que leur
    # équivalent français atteignait `personal_data` -> `total_balance`.
    #
    # Chaque entrée pointe vers une phrase française EXACTE déjà vérifiée
    # comme fonctionnelle, jamais vers une nouvelle branche de logique : c'est
    # le même principe que les entrées "carte perdue" plus haut, et cela
    # garantit par construction un résultat identique en français et en darija.
    ("عطيني تفاصيل الحساب", "quelles sont les informations de mon compte"),
    ("بغيت نشوف الحساب ديالي", "quelles sont les informations de mon compte"),
    ("3tini tafasil dyal l7sab", "quelles sont les informations de mon compte"),
    ("bghit tafasil dyal l7sab", "quelles sont les informations de mon compte"),
    ("bghit nchouf l7sab dyali", "quelles sont les informations de mon compte"),
    ("chouf l7sab dyali", "quelles sont les informations de mon compte"),
    ("tafasil dyal l7sab", "quelles sont les informations de mon compte"),
    ("tafasil dyal compte", "quelles sont les informations de mon compte"),
    # --- "Combien me reste-t-il ?" (Darija) ---
    # Distinct de "شحال عندي فالحساب" (solde brut) déjà présent plus haut :
    # ces tournures portent explicitement sur le RESTE disponible.
    ("شحال باقي عندي فالحساب", "combien il me reste"),
    ("شحال باقي عندي", "combien il me reste"),
    ("ch7al baqi 3ndi f compte", "combien il me reste"),
    ("ch7al baqi 3ndi", "combien il me reste"),
    ("chhal baqi 3ndi", "combien il me reste"),
    ("ch7al baqi liya", "combien il me reste"),
    # --- Situation financière (Darija) ---
    ("الوضعية المالية ديالي", "quelle est ma situation financiere"),
    ("wad3iya maliya dyali", "quelle est ma situation financiere"),
    ("l wad3iya maliya dyali", "quelle est ma situation financiere"),
    # --- Récapitulatif (Darija) ---
    ("3tini recapitulatif dyal l7sab", "quelles sont les informations de mon compte"),
    ("bghit recapitulatif", "je veux un recapitulatif"),
    # --- Détails de la carte (Darija) — pointe vers la phrase française déjà
    # vérifiée comme donnant `card_information`, jamais vers le compte. ---
    ("تفاصيل الكارط ديالي", "quel est le statut de ma carte"),
    ("tafasil dyal lkarta", "quel est le statut de ma carte"),
    ("tafasil dyal carte dyali", "quel est le statut de ma carte"),
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
    # --- Ajout audit robustesse : "البنيفيسيار" (beneficiaires, emprunt arabise
    # courant) n'etait couvert ni en phrase ni en mot - un message purement en
    # arabe ("شكون هوما البنيفيسيار ديالي") tombait dans faq_generale au lieu
    # de la vraie liste de beneficiaires (deja fonctionnel en francais et en
    # Arabizi, ou "beneficiaires" apparait deja tel quel dans le texte). Le mot
    # traduit suffit : `classify_personal_intent` ne cherche que la sous-chaine
    # "beneficiaire", peu importe le reste de la phrase (meme principe que les
    # autres entrees ci-dessous). ---
    # -----------------------------------------------------------------------
    # PLAFONDS DE CARTE et SÉLECTION DE COMPTE (darija arabe + Arabizi).
    #
    # Ces tokens manquaient : « ch7al nqder nkhless b carte », « شحال نقدر نسحب »
    # ou « شنو هما سقوف البطاقة » n'étaient traduits que partiellement et
    # tombaient en `assistant_explain`. Chaque entrée pointe vers la forme
    # française EXACTE déjà reconnue par la détection de champs de carte.
    #
    # Les formes composées sont placées avant leurs fragments : `_WORD_MAP` est
    # trié par longueur décroissante, mais les écrire dans cet ordre garde le
    # fichier lisible.
    # -----------------------------------------------------------------------
    ("شنو هما", "quels sont"),
    ("chno homa", "quels sont"),
    ("سقوف البطاقة", "plafonds de ma carte"),
    ("سقف البطاقة", "plafond de ma carte"),
    ("سقوف", "plafonds"),
    ("سقف", "plafond"),
    ("s9ouf", "plafonds"),
    ("sqouf", "plafonds"),
    ("s9af", "plafond"),
    ("بالبطاقة", "avec ma carte"),
    ("البطاقة", "carte"),
    ("b carte", "avec ma carte"),
    ("b lkarta", "avec ma carte"),
    ("blkarta", "avec ma carte"),
    ("lkarta", "carte"),
    ("nkhelles", "payer"),
    ("nkhalles", "payer"),
    ("nkhless", "payer"),
    ("khalles", "payer"),
    ("نخلص", "payer"),
    ("الأداء", "paiement"),
    ("الاداء", "paiement"),
    ("ns7eb", "retirer"),
    ("nsheb", "retirer"),
    ("ns7ab", "retirer"),
    ("نسحب", "retirer"),
    ("السحب", "retrait"),
    ("nqder", "je peux"),
    ("n9dar", "je peux"),
    # --- Sélection explicite d'un compte pour le RIB ---
    ("الحساب الجاري", "compte courant"),
    ("حساب التوفير", "compte epargne"),
    ("compte tawfir", "compte epargne"),
    ("l7sab jari", "compte courant"),
    ("الريب", "rib"),
    ("ريب", "rib"),
    ("البنيفيسيار", "beneficiaires"),
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
    ("lma3lomat", "les informations"),
    ("ma3lomat", "informations"),
    ("m3lomat", "informations"),
    ("l7sab", "compte"),
    ("lhsab", "compte"),
    ("7sab", "compte"),
    ("3tini", "donne-moi"),
    ("3afak", "s'il te plait"),
    ("afak", "s'il te plait"),
    ("3la", "sur"),
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
    # -----------------------------------------------------------------------
    # Enrichissement de la couverture Darija / Arabizi / arabe.
    #
    # Stratégie retenue pour éviter l'explosion combinatoire : privilégier le
    # _WORD_MAP (qui GÉNÉRALISE à toute phrase contenant le token) plutôt que
    # d'ajouter une entrée _PHRASE_MAP par formulation. Chaque token pointe
    # vers la forme française EXACTE déjà reconnue par le classificateur —
    # possessif inclus quand il est nécessaire ("العمليات" -> "mes operations"
    # et non "operations", car `_PERSONAL_DATA_PATTERNS` exige le possessif
    # pour ce mot, qui apparaît aussi dans des questions publiques).
    #
    # Rappel de fonctionnement : `_WORD_MAP` est trié par longueur
    # DÉCROISSANTE et appliqué par `str.replace` (sous-chaîne, pas frontière de
    # mot) — les entrées composées ci-dessous sont donc toujours traitées avant
    # leurs fragments ("bghit n3ref" avant "bghit" et "n3ref", "nchof" avant
    # "chof", "الحساب ديالي" avant "الحساب" et "ديالي").
    # -----------------------------------------------------------------------
    # --- Possessifs composés : produisent "mon compte"/"ma carte" (et non
    # "compte mon"), seule forme reconnue par `_PERSONAL_DATA_PATTERNS`. ---
    ("l7sab dyali", "mon compte"),
    ("lhsab dyali", "mon compte"),
    ("l7ssab dyali", "mon compte"),
    ("7sab dyali", "mon compte"),
    ("compte dyali", "mon compte"),
    ("carte dyali", "ma carte"),
    ("الحساب ديالي", "mon compte"),
    ("الكارط ديالي", "ma carte"),
    # --- "les X dyali" = "mes X" (tournure Darija très courante). ---
    ("les dernieres operations", "mes dernieres operations"),
    ("les operations dyali", "mes operations"),
    ("les transactions dyali", "mes transactions"),
    ("les paiements dyali", "mes paiements"),
    ("les depenses dyali", "mes depenses"),
    ("les beneficiaires dyali", "mes beneficiaires"),
    ("finances dyali", "mes finances"),
    # --- "combien me reste-t-il" ---
    ("baqi liya", "me reste"),
    ("baqi lia", "me reste"),
    ("باقي ليا", "me reste"),
    # --- Verbes / tournures d'intention ---
    ("bghit n3ref", "je veux savoir"),
    ("بغيت نعرف", "je veux savoir"),
    ("nchouf", "voir"),
    ("nchof", "voir"),
    ("chof", "montre-moi"),
    ("n3ref", "savoir"),
    ("نشوف", "voir"),
    ("نعرف", "savoir"),
    ("عطيني", "donne-moi"),
    ("بغيت", "je veux"),
    ("ديال", "de"),
    # --- Variantes orthographiques Arabizi fréquentes de "combien" / "compte" ---
    ("ch7el", "combien"),
    ("chhal", "combien"),
    ("cha7al", "combien"),
    ("l7ssab", "compte"),
    # --- Noms d'opérations / de produits ---
    ("l3amaliyat", "mes operations"),
    ("3amaliyat", "mes operations"),
    ("العمليات", "mes operations"),
    ("المعاملات", "mes transactions"),
    ("المصاريف", "mes depenses"),
    ("الراتب", "mon salaire"),
    ("اقتطاع", "prelevement"),
    ("الوضعية المالية", "situation financiere"),
    ("ملخص", "resume"),
    ("tafasil", "details"),
    ("تفاصيل", "details"),
    ("l7ala", "etat"),
    ("الحالة", "etat"),
    ("akhir", "dernier"),
    ("آخر", "dernier"),
    # -----------------------------------------------------------------------
    # Identifiants bancaires : RIB, IBAN, numéro de compte.
    #
    # Mesuré avant ajout : "chnahowa rib dyalti", "3tini rib dyali",
    # "bghit iban dyali" et leurs équivalents arabes tombaient tous en
    # `faq_generale`, et la recherche RAG renvoyait une réponse sans rapport
    # (délai d'exécution d'un virement).
    #
    # Les possessifs composés produisent "mon RIB"/"mon IBAN" — et non
    # "rib mon" — car `_PERSONAL_DATA_PATTERNS` et
    # `_ACCOUNT_IDENTIFIER_PATTERNS` raisonnent sur la forme française.
    # -----------------------------------------------------------------------
    # --- Verbes et périodes manquants, mesurés en échec de bout en bout ---
    # "werini akher 5 operations" et "ch7al dkhel l compte courant had simana"
    # n'étaient ni normalisés ni routés correctement.
    ("werini", "montre-moi"),
    ("wrini", "montre-moi"),
    ("warini", "montre-moi"),
    # "mes dernieres" (et non "dernier") : le possessif est nécessaire pour
    # que `\bmes\b[\w\s]{0,20}\boperations?\b` reconnaisse la demande comme
    # personnelle — sans lui, "werini akher 5 operations" partait en FAQ.
    ("akher", "mes dernieres"),
    ("dkhel lia", "est entre"),
    ("dkhel l", "est entre"),
    ("dkhel", "est entre"),
    ("had simana", "cette semaine"),
    ("had l simana", "cette semaine"),
    ("simana lli fatet", "semaine derniere"),
    ("lbareh", "hier"),
    ("lbare7", "hier"),
    # Période « mois dernier » en Arabizi (l'équivalent arabe existait déjà).
    ("chher lli fat", "mois dernier"),
    ("chhar lli fat", "mois dernier"),
    ("rib dyali", "mon rib"),
    ("rib dyalti", "mon rib"),
    ("iban dyali", "mon iban"),
    ("iban dyalti", "mon iban"),
    ("numero compte dyali", "mon numero de compte"),
    ("nomero compte dyali", "mon numero de compte"),
    ("dyalti", "mon"),
    # Interrogatifs darija ("c'est quoi", "quel est").
    ("chnahowa", "quel est"),
    ("chnahia", "quelle est"),
    ("chno howa", "quel est"),
    ("achno", "quel est"),
    ("chnou", "quel est"),
    ("chno", "quel est"),
    ("nomero", "numero"),
    # --- Équivalents en écriture arabe ---
    ("الريب ديالي", "mon rib"),
    ("الايبان ديالي", "mon iban"),
    ("الإيبان ديالي", "mon iban"),
    ("رقم الحساب ديالي", "mon numero de compte"),
    ("رقم الحساب", "numero de compte"),
    ("الريب", "rib"),
    ("الايبان", "iban"),
    ("الإيبان", "iban"),
    ("شنو هو", "quel est"),
    ("شنو هي", "quelle est"),
    ("شنو", "quel est"),
    ("رقم", "numero"),
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
