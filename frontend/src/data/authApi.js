// Client API d'authentification - POST /api/auth/login, GET /api/auth/session,
// POST /api/auth/logout. Session opaque (session_id), jamais un JWT - voir CLAUDE.md §4
// et backend/app/security/session_manager.py.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

export async function loginRequest(username, password) {
  try {
    const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      return { ok: false }
    }
    const data = await res.json()
    return { ok: true, sessionId: data.session_id, expiresAt: data.expires_at }
  } catch (err) {
    return { ok: false }
  }
}

export async function checkSessionRequest(sessionId) {
  try {
    const res = await fetch(`${API_BASE_URL}/api/auth/session`, {
      headers: { Authorization: `Bearer ${sessionId}` },
    })
    if (!res.ok) {
      return { ok: false }
    }
    const data = await res.json()
    return { ok: true, username: data.username, expiresAt: data.expires_at }
  } catch (err) {
    return { ok: false }
  }
}

/**
 * GET /api/banking/overview - donnees bancaires REELLES du client authentifie.
 *
 * Remplace les donnees simulees du tableau de bord (mockAccount/mockTransactions),
 * qui affichaient 15 420,50 MAD pendant que le chatbot lisait 106 318,39 MAD dans
 * demo_bancaire.db. Le tableau de bord et le chatbot partagent desormais la meme
 * source pour la meme session.
 *
 * Retourne toujours un objet discriminant, jamais une exception :
 *   { ok: true, overview }            - donnees valides
 *   { ok: false, reason: 'unauthorized' } - session expiree/invalide (401)
 *   { ok: false, reason: 'network' }      - backend injoignable
 *   { ok: false, reason: 'invalid' }      - reponse inexploitable
 *
 * `reason` permet a l'appelant de distinguer une session a nettoyer d'une simple
 * panne reseau a reessayer - jamais de repli silencieux sur des donnees simulees.
 *
 * Le session_id circule uniquement dans l'en-tete Authorization, jamais dans l'URL
 * (il apparaitrait dans les logs serveur et l'historique du navigateur).
 */
export async function fetchBankingOverview(sessionId) {
  if (!sessionId) {
    return { ok: false, reason: 'unauthorized' }
  }

  let res
  try {
    res = await fetch(`${API_BASE_URL}/api/banking/overview`, {
      headers: { Authorization: `Bearer ${sessionId}` },
    })
  } catch (err) {
    return { ok: false, reason: 'network' }
  }

  if (res.status === 401) {
    return { ok: false, reason: 'unauthorized' }
  }
  if (!res.ok) {
    return { ok: false, reason: 'network' }
  }

  let data
  try {
    data = await res.json()
  } catch (err) {
    return { ok: false, reason: 'invalid' }
  }

  // Validation de forme : le tableau de bord ne doit jamais afficher une reponse
  // partielle en la faisant passer pour des donnees bancaires completes.
  if (!data || typeof data.customer_id !== 'string' || !Array.isArray(data.accounts)) {
    return { ok: false, reason: 'invalid' }
  }

  return {
    ok: true,
    overview: {
      customerId: data.customer_id,
      fullName: typeof data.full_name === 'string' ? data.full_name : '',
      // Montants conserves en CHAINE decimale (jamais parseFloat) : la conversion
      // n'a lieu qu'a l'affichage, via src/data/money.js - voir CLAUDE.md regle 7.
      totalBalance: String(data.total_balance ?? '0'),
      accounts: data.accounts.map((account) => ({
        accountType: account.account_type,
        maskedAccountNumber: account.masked_account_number,
        accountNumber: account.account_number,
        rib: account.rib,
        iban: account.iban,
        currency: account.currency,
        balance: String(account.balance ?? '0'),
      })),
      recentTransactions: Array.isArray(data.recent_transactions)
        ? data.recent_transactions.map((tx) => ({
            date: tx.date,
            label: tx.label,
            category: tx.category,
            direction: tx.direction,
            amount: String(tx.amount ?? '0'),
            currency: tx.currency,
          }))
        : [],
      card: data.card
        ? {
            cardType: data.card.card_type,
            maskedCardNumber: data.card.masked_card_number,
            status: data.card.status,
            paymentLimit: String(data.card.payment_limit ?? '0'),
            withdrawalLimit: String(data.card.withdrawal_limit ?? '0'),
          }
        : null,
    },
  }
}

export async function logoutRequest(sessionId) {
  try {
    await fetch(`${API_BASE_URL}/api/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${sessionId}` },
    })
  } catch (err) {
    // Deconnexion locale malgre tout, meme si l'appel reseau echoue.
  }
}
