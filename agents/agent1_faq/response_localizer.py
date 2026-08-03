"""Mise en phrase localisée des réponses de l'Agent 1 (darija arabe / darija latine).

Couche linguistique strictement séparée de la logique métier : ce module ne
lit ni n'écrit jamais dans `banking_db` — il reçoit uniquement des données
déjà récupérées (montants `Decimal`, dates, chaînes) par
`banking_answers.py`/`graph.py`, filtrées par le `user_id` de la session, et
se contente de choisir le gabarit de phrase adapté à la langue détectée.

Le français n'est **pas** géré ici pour les réponses personnelles (voir
`banking_answers.build_personal_data_answer`, qui conserve son chemin
français d'origine sans modification) ; ce module gère en revanche les
messages transverses (connexion requise, service indisponible, FAQ) pour les
trois langues, y compris "fr", par simple cohérence d'API.

Aucun montant, aucune date, aucun numéro n'est jamais recalculé ou modifié
ici — uniquement inséré tel quel dans un gabarit de phrase (voir le point 7
de l'énoncé : la réponse FAQ récupérée n'est jamais reformulée par un modèle,
seulement encadrée par une courte phrase d'introduction en darija).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

GENERIC_PERSONAL_FALLBACK_FR = (
    "Je ne peux pas encore répondre précisément à cette question personnelle. "
    "Essayez par exemple : solde total, dépenses par catégorie, dernières opérations, "
    "date de salaire, dernier prélèvement, ou informations de carte."
)

_CATEGORY_LABEL_AR = {
    "Restaurants": "المطاعم",
    "Transport": "النقل",
    "Courses": "السوق",
    "Carburant": "البنزين",
    "Assurance": "التأمين",
    "Abonnement": "الاشتراك",
    "Logement": "السكن",
    "Retrait": "السحب",
}


def _split_accounts(accounts: list[dict]) -> tuple[Optional[dict], Optional[dict]]:
    current = next((a for a in accounts if a["account_type"] == "courant"), None)
    savings = next((a for a in accounts if a["account_type"] == "carnet"), None)
    return current, savings


# ---------------------------------------------------------------------------
# Messages transverses (connexion requise, service indisponible, FAQ)
# ---------------------------------------------------------------------------


def localize_require_login(language: str) -> str:
    if language == "darija_ar":
        return "خاصك تدخل للحساب ديالك باش تشوف المعلومات البنكية الشخصية."
    if language == "darija_latn":
        return "Khassk tdkhol l compte dyalek bach tchouf les informations bancaires personnelles."
    return "Pour consulter vos informations personnelles, vous devez d'abord vous connecter à votre espace client."


def localize_service_unavailable(language: str) -> str:
    if language == "darija_ar":
        return "هاد الخدمة ما متوفراش دابا."
    if language == "darija_latn":
        return "Had service ma mtwafrach daba."
    return "Ce service n'est pas disponible pour le moment."


def localize_faq_answer(french_answer: str, language: str) -> str:
    """Encadre la réponse FAQ (française, issue de ChromaDB) d'une courte phrase
    d'introduction en darija — le contenu français récupéré n'est **jamais**
    modifié (montants, dates, conditions bancaires inchangés)."""
    if language == "darija_ar":
        return f"هذا هو الجواب اللي لقيت (بالفرنسية): {french_answer}"
    if language == "darija_latn":
        return f"Hada howa jawab li lqit (b lfrancais) : {french_answer}"
    return french_answer


def localize_no_faq_answer(language: str) -> str:
    if language == "darija_ar":
        return "ما كاينة حتى معلومة متوفرة دابا. عافاك عاود صيغ السؤال ديالك أو اتصل بخدمة الزبناء."
    if language == "darija_latn":
        return "Ma kaynach ma3loumat mtwafra daba. 3afak 3awd seg soualek aw tsel b khidma dyal client."
    return (
        "Aucune information n'est disponible pour le moment dans notre base de connaissances. "
        "Merci de reformuler votre question ou de contacter le service client."
    )


def localize_greeting(language: str) -> str:
    if language == "darija_ar":
        return "سلام 👋 كيفاش نقدر نعاونك؟"
    if language == "darija_latn":
        return "Salam 👋 Kifach n9der n3awnek?"
    return "Bonjour 👋 Comment puis-je vous aider ?"


def localize_thanks(language: str) -> str:
    if language == "darija_ar":
        return "بلا جميل."
    if language == "darija_latn":
        return "Bla jmil."
    return "Je vous en prie."


def localize_small_talk(language: str) -> str:
    if language == "darija_ar":
        return "لاباس، الحمد لله. كيفاش نقدر نعاونك اليوم؟"
    if language == "darija_latn":
        return "Labas, lhamdollah. Kifach n9der n3awnek lyoum?"
    return "Ça va bien, merci ! Comment puis-je vous aider aujourd'hui ?"


def localize_unclear_short(language: str) -> str:
    if language == "darija_ar":
        return "ماشي واضح عندي. تقدر تعاود تصيغ السؤال ديالك؟"
    if language == "darija_latn":
        return "Ma fhamtch mezyan. Twaddi t3awd seg soualek?"
    return "Je n'ai pas bien compris votre demande. Pouvez-vous préciser votre question ?"


def localize_generic_fallback(language: str) -> str:
    if language == "darija_ar":
        return "ما قدرتش نجاوب دقيق على هاد السؤال دابا."
    if language == "darija_latn":
        return "Ma qdertch njaweb bidaqa 3la had soual daba."
    return GENERIC_PERSONAL_FALLBACK_FR


# ---------------------------------------------------------------------------
# Réponses bancaires personnelles (darija arabe / darija latine uniquement —
# le français reste géré par `banking_answers.py`)
# ---------------------------------------------------------------------------


def localize_total_balance_answer(data: dict, language: str) -> str:
    total = data["total"]
    current, savings = _split_accounts(data["accounts"])
    current_balance = current["balance"] if current else Decimal("0")
    savings_balance = savings["balance"] if savings else Decimal("0")

    if language == "darija_ar":
        return (
            f"عندك فالمجموع {total} درهم: {current_balance} درهم فالحساب الجاري "
            f"و{savings_balance} درهم فحساب التوفير."
        )
    return (
        f"3andek f lmajmou3 {total} MAD: {current_balance} MAD f compte courant "
        f"w {savings_balance} MAD f compte d'epargne."
    )


def localize_balance_at_date_answer(data: dict, language: str) -> str:
    reference_date = data.get("reference_date")
    balances = data.get("balances") or []

    if reference_date is None:
        if language == "darija_ar":
            return "عافاك حدد تاريخ بالشكل « 1er <الشهر> » باش تشوف رصيد قديم."
        return "3afak 3ti tarikh b format 1er <chher> bach tchouf solde qdim."

    if not balances:
        if language == "darija_ar":
            return f"ما كاين حتى رصيد مسجل بالضبط فهاد التاريخ ({reference_date})."
        return f"Ma kayn ta solde msajel bedhabt f had tarikh ({reference_date})."

    total = data.get("total", sum((b["balance"] for b in balances), Decimal("0")))
    if language == "darija_ar":
        detail = "، ".join(f"{b['account_type']} : {b['balance']} درهم" for b in balances)
        return f"فـ{reference_date}، الرصيد ديالك كان {total} درهم ({detail})."
    detail = ", ".join(f"{b['account_type']} : {b['balance']} MAD" for b in balances)
    return f"F {reference_date}, solde dyalek kan {total} MAD ({detail})."


def localize_spending_answer(data: dict, language: str) -> str:
    total = data["total"]
    category = data["category"]
    period = data["period"]

    if language == "darija_ar":
        period_label = "هاد الشهر" if period == "current_month" else "الشهر اللي فات"
        category_label = _CATEGORY_LABEL_AR.get(category, category) if category else "المصاريف ديالك كاملين"
        if total == 0:
            return "ما عندك حتى مصروف مسجل فهاد الفئة خلال هاد الفترة."
        return f"صرفتي {total} درهم فـ{category_label} {period_label}."

    period_label = "had chher" if period == "current_month" else "chher li fat"
    category_label = category if category else "jami3 masarif dyalek"
    if total == 0:
        return "Ma 3andek ta depense msajla f had categorie f had periode."
    return f"Srafti {total} MAD f {category_label} {period_label}."


def localize_salary_answer(data: dict, mentions_semaine: bool, language: str) -> str:
    if not data.get("found"):
        if language == "darija_ar":
            return "ما كايناش صاليرات مسجلة فحسابك."
        return "Ma kaynach salaire msajel f compte dyalek."

    amount = data["amount"]
    date = data["date"]
    received_this_week = data["received_this_week"]

    if mentions_semaine:
        if received_this_week:
            if language == "darija_ar":
                return f"أيه، دخل ليك صاليرك ديال {amount} درهم فـ{date}، هاد السيمانة."
            return f"Ah, dkhal lik salaire dyalek dyal {amount} MAD f {date}, had simana."
        if language == "darija_ar":
            return f"ما دخلش الصالير هاد السيمانة. آخر صالير كان فـ{date} بـ{amount} درهم."
        return f"Ma dkhalch salaire had simana. Akhir salaire kan f {date} b {amount} MAD."

    if language == "darija_ar":
        return f"صاليرك ديال {amount} درهم دخل ليك فـ{date}."
    return f"Salaire dyalek dyal {amount} MAD dkhal lik f {date}."


def localize_last_direct_debit_answer(data: dict, language: str) -> str:
    if not data.get("found"):
        if language == "darija_ar":
            return "ما كاينش اقتطاع مسجل فحسابك."
        return "Ma kaynach prelevement msajel f compte dyalek."

    if language == "darija_ar":
        return f"آخر اقتطاع كان « {data['description']} » ديال {data['amount']} درهم، فـ{data['date']}."
    return f"Akhir prelevement kan « {data['description']} » dyal {data['amount']} MAD, f {data['date']}."


def localize_payments_answer(data: dict, language: str) -> str:
    payments = data["payments"]
    period = data["period"]
    period_label_ar = "ديال الشهر اللي فات" if period == "last_month" else "ديال هاد الشهر"
    period_label_latn = "dyal chher li fat" if period == "last_month" else "dyal had chher"

    if not payments:
        if language == "darija_ar":
            return "ما كاين حتى خلاص مسجل فهاد الفترة."
        return "Ma kayn ta paiement msajel f had periode."

    if language == "darija_ar":
        lines = "؛ ".join(f"{p['transaction_date']} : {p['description']} ({p['amount']} درهم)" for p in payments)
        return f"هاذو الخلاصات ديالك {period_label_ar} : {lines}."
    lines = "; ".join(f"{p['transaction_date']} : {p['description']} ({p['amount']} MAD)" for p in payments)
    return f"Hadou les paiements dyalek {period_label_latn} : {lines}."


def localize_recent_transactions_answer(data: dict, language: str) -> str:
    transactions = data["transactions"]
    if not transactions:
        if language == "darija_ar":
            return "ما كاين حتى عملية مسجلة فحسابك."
        return "Ma kayn ta operation msajla f compte dyalek."

    if language == "darija_ar":
        lines = "؛ ".join(f"{tx['transaction_date']} : {tx['description']} ({tx['amount']} درهم)" for tx in transactions)
        return f"هاذو آخر العمليات ديالك: {lines}."
    lines = "; ".join(f"{tx['transaction_date']} : {tx['description']} ({tx['amount']} MAD)" for tx in transactions)
    return f"Hadou akhir les operations dyalek : {lines}."


def localize_beneficiaries_answer(data: dict, language: str) -> str:
    beneficiaries = data["beneficiaries"]
    if not beneficiaries:
        if language == "darija_ar":
            return "ما عندكش بنيفيسيار مسجلين فحسابك."
        return "Ma 3andekch beneficiaires msajlin f compte dyalek."

    if language == "darija_ar":
        lines = "، ".join(f"{b['display_name']} ({b['masked_account_number']})" for b in beneficiaries)
        return f"هاذو البنيفيسيار المسجلين ديالك: {lines}."
    lines = "; ".join(f"{b['display_name']} ({b['masked_account_number']})" for b in beneficiaries)
    return f"Hadou les beneficiaires dyalek : {lines}."


def localize_assistant_explain(data: dict, language: str) -> str:
    transactions = data["transactions"]

    if language == "darija_ar":
        base = (
            "نقدر نعاونك فالرصيد، المصاريف حسب الفئة، آخر العمليات، تاريخ الصالير، "
            "آخر اقتطاع، البنيفيسيار ديالك أو معلومات الكارط. ما نقدرش دابا ندير تحليل أو نصيحة مالية شخصية."
        )
        if not transactions:
            return base
        lines = "؛ ".join(f"{tx['transaction_date']} : {tx['description']} ({tx['amount']} درهم)" for tx in transactions)
        return f"{base} هاذو آخر 3 عمليات ديالك، يمكن تعاونك: {lines}."

    base = (
        "N9der n3awnek f solde, masarif hasb category, akhir les operations, tarikh dyal salaire, "
        "akhir prelevement, beneficiaires dyalek aw les informations dyal carte. "
        "Mazal ma n9derch ndir analyse aw conseil financier personnel."
    )
    if not transactions:
        return base
    lines = "; ".join(f"{tx['transaction_date']} : {tx['description']} ({tx['amount']} MAD)" for tx in transactions)
    return f"{base} Hadou akhir 3 operations dyalek, ymkn t3awnek : {lines}."


def localize_card_answer(requested_fields: list[str], card: Optional[dict], language: str) -> str:
    """Compose une réponse carte couvrant **toutes** les informations demandées
    (même principe que `banking_answers._compose_card_answer`, en darija)."""
    if card is None:
        if language == "darija_ar":
            return "ما عندكش كارط مسجلة."
        return "Ma 3andekch carte msajla."

    fields = set(requested_fields)

    if fields == {"ecommerce_enabled", "international_enabled"}:
        online = card["online_payments_enabled"]
        intl = card["international_payments_enabled"]
        if language == "darija_ar":
            if online and intl:
                return "أيه، الكارط ديالك تقدر تخدم بيها فالإنترنت ومن المواقع الأجنبية."
            if online and not intl:
                return "لا، الكارط ديالك تقدر تخدم بيها فالإنترنت، ولكن الشرا من المواقع الأجنبية ماشي مفعل."
            if intl and not online:
                return "لا، الشرا من المواقع الأجنبية مفعل ولكن الأداء عبر الإنترنت ماشي مفعل فالكارط ديالك."
            return "لا، لا الأداء عبر الإنترنت ولا الشرا من المواقع الأجنبية مفعلين فالكارط ديالك."
        if online and intl:
            return "Ah, carte dyalek khadama f internet w f les sites internationaux."
        if online and not intl:
            return "La, carte dyalek khadama f internet, walakin les achats internationaux mamfa3linch."
        if intl and not online:
            return "La, les achats internationaux mfa3lin walakin le paiement f internet mamfa3elch f carte dyalek."
        return "La, la le paiement f internet la les achats internationaux mamfa3linch f carte dyalek."

    sentences: list[str] = []

    if "status" in fields:
        if language == "darija_ar":
            sentences.append("الكارط ديالك خدامة." if card["status"] == "active" else f"الكارط ديالك حالتها « {card['status']} ».")
        else:
            sentences.append(
                "Carte dyalek khdama." if card["status"] == "active" else f"Carte dyalek status dyalha « {card['status']} »."
            )

    if "payment_limit" in fields and "withdrawal_limit" in fields:
        if language == "darija_ar":
            sentences.append(f"سقف الأداء هو {card['payment_limit']} درهم وسقف السحب هو {card['withdrawal_limit']} درهم.")
        else:
            sentences.append(
                f"Plafond dyal paiement howa {card['payment_limit']} MAD "
                f"w plafond dyal retrait howa {card['withdrawal_limit']} MAD."
            )
    elif "payment_limit" in fields:
        if language == "darija_ar":
            sentences.append(f"سقف الأداء هو {card['payment_limit']} درهم.")
        else:
            sentences.append(f"Plafond dyal paiement howa {card['payment_limit']} MAD.")
    elif "withdrawal_limit" in fields:
        if language == "darija_ar":
            sentences.append(f"سقف السحب هو {card['withdrawal_limit']} درهم.")
        else:
            sentences.append(f"Plafond dyal retrait howa {card['withdrawal_limit']} MAD.")

    if "ecommerce_enabled" in fields:
        online = card["online_payments_enabled"]
        if language == "darija_ar":
            sentences.append("الأداء عبر الإنترنت مفعل." if online else "الأداء عبر الإنترنت ماشي مفعل.")
        else:
            sentences.append("Le paiement f internet mfa3el." if online else "Le paiement f internet mamfa3elch.")

    if "international_enabled" in fields:
        intl = card["international_payments_enabled"]
        if language == "darija_ar":
            sentences.append("الشرا من المواقع الأجنبية مفعل." if intl else "الشرا من المواقع الأجنبية ماشي مفعل.")
        else:
            sentences.append("Les achats internationaux mfa3lin." if intl else "Les achats internationaux mamfa3linch.")

    if not sentences:
        if language == "darija_ar":
            return f"الكارط ديالك حالتها « {card['status']} »."
        return f"Carte dyalek status dyalha « {card['status']} »."

    return " ".join(sentences)
