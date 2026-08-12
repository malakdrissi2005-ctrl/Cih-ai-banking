"""`GET /api/banking/overview` — données bancaires du client authentifié.

RAISON D'ÊTRE
-------------
Le dashboard React affichait jusqu'ici des valeurs codées en dur
(`frontend/src/data/mockAccount.js` : 15 420,50 MAD, référence
« DEMO-****-4821 ») pendant que le chatbot lisait `demo_bancaire.db`. Les deux
se contredisaient à l'écran. Ce n'était pas un problème de bases divergentes :
le frontend n'avait tout simplement AUCUN endpoint bancaire à interroger.

Cet endpoint est le plus petit ajout permettant au dashboard et au chatbot de
partager la MÊME source pour la MÊME session. Il ne remplace rien et ne
modifie aucun contrat existant.

SÉCURITÉ
--------
- Session OBLIGATOIRE (401 sinon) — contrairement à `/api/chat` qui tolère
  l'anonymat pour les questions publiques.
- Le `customer_id` provient EXCLUSIVEMENT de la session ; aucun identifiant du
  corps de requête ou de l'URL n'est accepté, ce qui rend l'accès aux données
  d'un autre client structurellement impossible (pas d'IDOR).
- Lecture seule. Aucune écriture, aucune opération transactionnelle.
- Champs volontairement ABSENTS de la réponse : `id_compte` (clé technique
  interne), PAN complet, CVV, PIN, mot de passe, hash, jeton, OTP.
- `rib` et `iban` sont fournis en clair au propriétaire : ce sont ses propres
  coordonnées, qu'il communique pour recevoir un virement (même politique que
  la réponse du chatbot, pour que les deux ne se contredisent jamais).
- Les montants transitent en CHAÎNE décimale (`"15230.50"`), jamais en
  flottant JSON, pour préserver la précision `Decimal` (`CLAUDE.md` règle 7).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.banking import banking_db
from app.routers.auth import get_auth_db_path, get_banking_db_path
from app.security import session_manager

router = APIRouter(prefix="/api/banking", tags=["banking"])


class AccountView(BaseModel):
    account_type: str
    masked_account_number: str
    account_number: str
    rib: str
    iban: str
    currency: str
    balance: str  # chaîne décimale, jamais un float


class TransactionView(BaseModel):
    date: str
    label: str
    category: str
    direction: str
    amount: str  # chaîne décimale
    currency: str


class CardView(BaseModel):
    card_type: str
    masked_card_number: str
    status: str
    payment_limit: str
    withdrawal_limit: str


class OverviewResponse(BaseModel):
    customer_id: str
    full_name: str
    accounts: list[AccountView]
    total_balance: str
    recent_transactions: list[TransactionView]
    card: Optional[CardView]


def _require_session(authorization: Optional[str], auth_db_path: Optional[str], banking_db_path: Optional[str]) -> str:
    """Retourne le `customer_id` de la session, ou lève 401.

    Contrairement à `/api/chat`, cet endpoint EXIGE une session : il ne sert
    que des données personnelles, il n'a aucun mode public.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Session manquante ou invalide.")
    session_id = authorization.split(" ", 1)[1].strip()
    if not session_id:
        raise HTTPException(status_code=401, detail="Session manquante ou invalide.")

    session = session_manager.get_valid_session(
        session_id, db_path=auth_db_path, banking_db_path=banking_db_path
    )
    if session is None:
        raise HTTPException(status_code=401, detail="Session invalide ou expirée.")
    return session["user_id"]


@router.get("/overview", response_model=OverviewResponse)
def overview(
    authorization: Optional[str] = Header(default=None),
    auth_db_path: Optional[str] = Depends(get_auth_db_path),
    banking_db_path: Optional[str] = Depends(get_banking_db_path),
) -> OverviewResponse:
    """Vue complète du client authentifié — même source que le chatbot."""
    customer_id = _require_session(authorization, auth_db_path, banking_db_path)

    # Une seule requête fournit identifiants ET soldes : un appariement par
    # type de compte perdrait un compte chez un client en possédant plusieurs
    # du même type (cas réel : CL0001 a deux carnets).
    comptes = [
        AccountView(
            account_type=compte["account_type"],
            masked_account_number=compte["masked_account_number"],
            account_number=compte["account_number"],
            rib=compte["rib"],
            iban=compte["iban"],
            currency=compte["currency"],
            balance=str(compte["balance"]),
        )
        for compte in banking_db.get_account_identifiers_for_customer(customer_id, db_path=banking_db_path)
    ]

    transactions = banking_db.get_transactions(customer_id, limit=5, db_path=banking_db_path)
    carte = banking_db.get_card_for_customer(customer_id, db_path=banking_db_path)
    profil = banking_db.get_customer_profile(customer_id, db_path=banking_db_path)

    return OverviewResponse(
        customer_id=customer_id,
        full_name=profil["full_name"] if profil else customer_id,
        accounts=comptes,
        # Exactement le même total que celui annoncé par le chatbot.
        total_balance=str(banking_db.get_total_balance(customer_id, db_path=banking_db_path)),
        recent_transactions=[
            TransactionView(
                date=tx["transaction_date"],
                label=tx["description"],
                category=tx["category"],
                direction=tx["direction"],
                amount=str(tx["amount"]),
                currency=tx["currency"],
            )
            for tx in transactions
        ],
        card=CardView(
            card_type=carte["card_type"],
            masked_card_number=carte["masked_card_number"],
            status=carte["status"],
            payment_limit=str(carte["payment_limit"]),
            withdrawal_limit=str(carte["withdrawal_limit"]),
        )
        if carte
        else None,
    )
