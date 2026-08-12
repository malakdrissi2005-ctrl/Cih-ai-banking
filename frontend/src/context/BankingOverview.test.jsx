// Integration du tableau de bord avec GET /api/banking/overview.
//
// CONTEXTE DU BUG : apres connexion, le tableau de bord affichait 15 420,50 MAD
// (mockAccount) pendant que le chatbot lisait 106 318,39 MAD dans
// demo_bancaire.db. Le frontend n'avait aucun endpoint bancaire a interroger et
// se rabattait sur des donnees simulees, y compris une fois authentifie.
//
// Ces tests prouvent que les valeurs authentifiees viennent desormais du
// backend, jamais des donnees simulees — meme en cas d'erreur reseau.
//
// Meme style que BankingAppProvider.test.jsx : `renderHook` + `vi.stubGlobal`.
// Pas de `screen` : `globals` n'est pas active dans vite.config.js, donc le
// nettoyage automatique de Testing Library ne s'execute pas entre les tests.

import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BankingAppProvider, useBankingApp } from './BankingAppProvider.jsx'
import { mockAccount } from '../data/mockAccount.js'
import { mockTransactions } from '../data/mockTransactions.js'

const SESSION_STORAGE_KEY = 'cih_session_id'

// Client possedant TROIS comptes dont DEUX du meme type — cas reel de CL0001.
// Un bug precedent du backend indexait les comptes par type dans un dict et
// perdait silencieusement le second carnet ; ce jeu de donnees le detecte.
const OVERVIEW_A = {
  customer_id: 'CL0001',
  full_name: 'Malak Drissi',
  total_balance: '106318.39',
  accounts: [
    {
      account_type: 'courant',
      masked_account_number: 'CIH •••• 1006',
      account_number: '0001100011000110',
      rib: '230810000110001100011006',
      iban: 'MA26230810000110001100011006',
      currency: 'MAD',
      balance: '68009.15',
    },
    {
      account_type: 'carnet',
      masked_account_number: 'CIH •••• 2009',
      account_number: '0002200022000220',
      rib: '230810000220002200022009',
      iban: 'MA26230810000220002200022009',
      currency: 'MAD',
      balance: '28010.49',
    },
    {
      account_type: 'carnet',
      masked_account_number: 'CIH •••• 3012',
      account_number: '0003300033000330',
      rib: '230810000330003300033012',
      iban: 'MA26230810000330003300033012',
      currency: 'MAD',
      balance: '10298.75',
    },
  ],
  recent_transactions: [
    {
      date: '2026-07-28',
      label: 'Paiement carte station-service',
      category: 'Carburant',
      direction: 'debit',
      amount: '1305.00',
      currency: 'MAD',
    },
    {
      date: '2026-07-26',
      label: 'Virement recu',
      category: 'Virement reçu',
      direction: 'credit',
      amount: '1050.62',
      currency: 'MAD',
    },
  ],
  card: {
    card_type: 'Visa Classic',
    masked_card_number: '450078XXXXXX7007',
    status: 'active',
    payment_limit: '5000',
    withdrawal_limit: '2000',
  },
}

// Second client : prouve l'isolation entre deux connexions successives.
const OVERVIEW_B = {
  customer_id: 'CL0042',
  full_name: 'Youssef Alaoui',
  total_balance: '25319.05',
  accounts: [
    {
      account_type: 'courant',
      masked_account_number: 'CIH •••• 9999',
      account_number: '0009900099000990',
      rib: '230810000990009900099999',
      iban: 'MA26230810000990009900099999',
      currency: 'MAD',
      balance: '25319.05',
    },
  ],
  recent_transactions: [],
  card: null,
}

/**
 * Backend simule, route par route.
 *
 * `overviewBehaviour` decrit le comportement de GET /api/banking/overview :
 *   { body }             -> 200 avec ce corps
 *   { status: 401 }      -> session invalide
 *   { throws: true }     -> backend injoignable
 * Une FONCTION peut aussi etre passee pour changer de comportement d'un appel
 * a l'autre (utilise par le test du bouton « Reessayer »).
 */
function stubBackend(overviewBehaviour = { body: OVERVIEW_A }) {
  const fetchMock = vi.fn(async (url, options) => {
    const href = String(url)

    if (href.includes('/api/auth/login')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ session_id: 'sess-test', expires_at: '2026-08-11T12:00:00Z' }),
      }
    }
    if (href.includes('/api/auth/logout')) {
      return { ok: true, status: 200, json: async () => ({}) }
    }
    if (href.includes('/api/auth/session')) {
      return { ok: true, status: 200, json: async () => ({ user_id: 'CL0001' }) }
    }
    if (href.includes('/api/banking/overview')) {
      const behaviour =
        typeof overviewBehaviour === 'function' ? overviewBehaviour(options) : overviewBehaviour
      if (behaviour.throws) throw new TypeError('Failed to fetch')
      const status = behaviour.status ?? 200
      return { ok: status === 200, status, json: async () => behaviour.body }
    }
    return { ok: false, status: 404, json: async () => ({}) }
  })

  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderBankingApp() {
  return renderHook(() => useBankingApp(), {
    wrapper: ({ children }) => <BankingAppProvider>{children}</BankingAppProvider>,
  })
}

async function connecter(result) {
  await act(async () => {
    await result.current.login('malak.drissi', 'MotDePasseDemo!42')
  })
}

beforeEach(() => {
  sessionStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

// ---------------------------------------------------------------------------
// Chargement nominal
// ---------------------------------------------------------------------------

describe('chargement de l’overview', () => {
  it('interroge /api/banking/overview apres une connexion reussie', async () => {
    const fetchMock = stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    const appel = fetchMock.mock.calls.find(([url]) => String(url).includes('/api/banking/overview'))
    expect(appel).toBeDefined()
    expect(appel[1].headers.Authorization).toBe('Bearer sess-test')
  })

  it('n’envoie jamais le session_id dans l’URL', async () => {
    const fetchMock = stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    for (const [url] of fetchMock.mock.calls) {
      expect(String(url)).not.toContain('sess-test')
    }
  })

  it('passe de idle a loading puis ready', async () => {
    // Le fetch overview est retenu jusqu'a ce qu'on le libere, ce qui rend
    // l'etat intermediaire `loading` reellement observable.
    let libererOverview
    const overviewEnAttente = new Promise((resolve) => {
      libererOverview = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        const href = String(url)
        if (href.includes('/api/auth/login')) {
          return { ok: true, status: 200, json: async () => ({ session_id: 'sess-test' }) }
        }
        await overviewEnAttente
        return { ok: true, status: 200, json: async () => OVERVIEW_A }
      }),
    )

    const { result } = renderBankingApp()
    expect(result.current.overviewStatus).toBe('idle')

    let connexion
    await act(async () => {
      connexion = result.current.login('malak.drissi', 'x')
    })
    expect(result.current.overviewStatus).toBe('loading')

    await act(async () => {
      libererOverview()
      await connexion
    })
    expect(result.current.overviewStatus).toBe('ready')
  })

  it('recharge l’overview quand une session existante est restauree', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, 'sess-restauree')
    const fetchMock = stubBackend()

    const { result } = renderBankingApp()
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    expect(result.current.isAuthenticated).toBe(true)
    const appel = fetchMock.mock.calls.find(([url]) => String(url).includes('/api/banking/overview'))
    expect(appel[1].headers.Authorization).toBe('Bearer sess-restauree')
  })
})

// ---------------------------------------------------------------------------
// Le tableau de bord affiche les valeurs du backend
// ---------------------------------------------------------------------------

describe('valeurs affichees', () => {
  it('remplace mockAccount par le compte reel du backend', async () => {
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    expect(result.current.account.balance).toBe('68009.15')
    expect(result.current.account.balance).not.toBe(mockAccount.balance)
    expect(result.current.account.number).toBe('CIH •••• 1006')
    expect(result.current.account.number).not.toBe(mockAccount.number)
    expect(result.current.userName).toBe('Malak Drissi')
  })

  it('distingue le solde du compte selectionne du total tous comptes', async () => {
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    // C'est exactement la confusion qui rendait tableau de bord et chatbot
    // contradictoires : 68 009,15 est UN compte, 106 318,39 est le total.
    expect(result.current.account.balance).toBe('68009.15')
    expect(result.current.totalBalance).toBe('106318.39')
    expect(result.current.totalBalance).not.toBe(result.current.account.balance)
  })

  it('conserve les trois comptes, dont deux du meme type', async () => {
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    expect(result.current.accounts).toHaveLength(3)
    const carnets = result.current.accounts.filter((c) => c.accountType === 'carnet')
    expect(carnets).toHaveLength(2)
    // Chaque compte garde son identite propre (RIB distinct).
    const ribs = new Set(result.current.accounts.map((c) => c.rib))
    expect(ribs.size).toBe(3)
  })

  it('changer de compte selectionne met a jour le solde sans toucher au total', async () => {
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    act(() => result.current.selectAccount(1))

    expect(result.current.account.balance).toBe('28010.49')
    expect(result.current.account.type).toBe('carnet')
    expect(result.current.totalBalance).toBe('106318.39')
  })

  it('affiche les transactions du backend au format attendu par RecentTransactions', async () => {
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    expect(result.current.transactions).toHaveLength(2)
    expect(result.current.transactions[0].label).toBe('Paiement carte station-service')
    // Aucune trace des transactions simulees.
    const libellesSimules = mockTransactions.map((t) => t.label)
    for (const tx of result.current.transactions) {
      expect(libellesSimules).not.toContain(tx.label)
    }
  })

  it('traduit credit/debit en in/out sans signer le montant', async () => {
    // `RecentTransactions` ajoute lui-meme le signe : un montant deja signe
    // s'afficherait « --1305,00 ». Le contrat est donc : montant NON signe,
    // sens porte uniquement par `direction`, en 'in' / 'out'.
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    const [debit, credit] = result.current.transactions
    expect(debit.direction).toBe('out')
    expect(debit.amount).toBe('1305.00')
    expect(credit.direction).toBe('in')
    expect(credit.amount).toBe('1050.62')
    for (const tx of result.current.transactions) {
      expect(tx.amount).not.toMatch(/^-/)
      expect(['in', 'out']).toContain(tx.direction)
    }
  })

  it('donne a chaque transaction une cle stable et unique', async () => {
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    const cles = result.current.transactions.map((t) => t.id)
    expect(new Set(cles).size).toBe(cles.length)
    expect(cles.every(Boolean)).toBe(true)
  })

  it('conserve les montants en chaine decimale, jamais en nombre flottant', async () => {
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    expect(typeof result.current.account.balance).toBe('string')
    expect(typeof result.current.totalBalance).toBe('string')
    for (const compte of result.current.accounts) {
      expect(typeof compte.balance).toBe('string')
    }
  })

  it('expose une source d’etat unique, partagee par le mobile et le desktop', async () => {
    stubBackend()
    // Deux consommateurs distincts du contexte, comme PhonePreview et DesktopView.
    const { result } = renderHook(
      () => ({ telephone: useBankingApp(), bureau: useBankingApp() }),
      { wrapper: ({ children }) => <BankingAppProvider>{children}</BankingAppProvider> },
    )

    await act(async () => {
      await result.current.telephone.login('malak.drissi', 'x')
    })
    await waitFor(() => expect(result.current.bureau.overviewStatus).toBe('ready'))

    // Une action posee cote telephone est immediatement visible cote bureau.
    act(() => result.current.telephone.selectAccount(2))

    expect(result.current.bureau.account.balance).toBe('10298.75')
    expect(result.current.bureau.overview).toBe(result.current.telephone.overview)
    expect(result.current.bureau.totalBalance).toBe(result.current.telephone.totalBalance)
  })
})

// ---------------------------------------------------------------------------
// Erreurs : jamais de repli sur des donnees simulees
// ---------------------------------------------------------------------------

describe('gestion des erreurs', () => {
  it('une panne reseau n’affiche JAMAIS les donnees simulees', async () => {
    stubBackend({ throws: true })
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('error'))

    expect(result.current.overviewError).toBe('network')
    expect(result.current.overview).toBeNull()
    expect(result.current.totalBalance).toBeNull()
    expect(result.current.accounts).toHaveLength(0)
    expect(result.current.selectedAccount).toBeNull()
  })

  it('une reponse malformee est rejetee plutot qu’affichee partiellement', async () => {
    stubBackend({ body: { customer_id: 42 } })
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('error'))

    expect(result.current.overviewError).toBe('invalid')
    expect(result.current.overview).toBeNull()
  })

  it('le bouton Reessayer recharge les donnees avec la session courante', async () => {
    let premierAppel = true
    stubBackend(() => {
      if (premierAppel) {
        premierAppel = false
        return { throws: true }
      }
      return { body: OVERVIEW_A }
    })

    const { result } = renderBankingApp()
    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('error'))

    await act(async () => {
      await result.current.retryOverview()
    })

    expect(result.current.overviewStatus).toBe('ready')
    expect(result.current.totalBalance).toBe('106318.39')
  })

  it('un 401 repasse l’application en etat deconnecte et vide la session', async () => {
    stubBackend({ status: 401 })
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewError).toBe('unauthorized'))

    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.overview).toBeNull()
    expect(result.current.totalBalance).toBeNull()
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
  })

  it('Reessayer ne fait rien sans session (aucune requete envoyee)', async () => {
    const fetchMock = stubBackend()
    const { result } = renderBankingApp()

    await act(async () => {
      await result.current.retryOverview()
    })

    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.overviewStatus).toBe('idle')
  })
})

// ---------------------------------------------------------------------------
// Cloisonnement entre utilisateurs
// ---------------------------------------------------------------------------

describe('cloisonnement des donnees', () => {
  it('la deconnexion efface toutes les donnees bancaires de l’etat', async () => {
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    await act(async () => {
      await result.current.logout()
    })

    expect(result.current.overview).toBeNull()
    expect(result.current.overviewStatus).toBe('idle')
    expect(result.current.accounts).toHaveLength(0)
    expect(result.current.totalBalance).toBeNull()
    expect(result.current.card).toBeNull()
    expect(result.current.isAuthenticated).toBe(false)
    // La conversation contient elle aussi des donnees personnelles.
    expect(result.current.messages).toHaveLength(0)
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
  })

  it('une seconde connexion ne montre jamais les donnees du client precedent', async () => {
    stubBackend({ body: OVERVIEW_A })
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.totalBalance).toBe('106318.39'))

    await act(async () => {
      await result.current.logout()
    })

    vi.unstubAllGlobals()
    stubBackend({ body: OVERVIEW_B })
    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    expect(result.current.totalBalance).toBe('25319.05')
    expect(result.current.userName).toBe('Youssef Alaoui')
    expect(result.current.accounts).toHaveLength(1)
    expect(result.current.card).toBeNull()
    // Aucun reliquat du client precedent, y compris l'index de compte
    // selectionne, qui pointerait sinon hors du tableau.
    expect(result.current.selectedAccountIndex).toBe(0)
    expect(result.current.accounts.map((c) => c.rib)).not.toContain(OVERVIEW_A.accounts[0].rib)
  })

  it('une reponse lente arrivee apres la deconnexion est ignoree', async () => {
    // Le jeton de course (`overviewRequestRef`) doit neutraliser cette reponse :
    // sans lui, les donnees du client precedent reapparaitraient apres coup.
    let libererOverview
    const overviewEnAttente = new Promise((resolve) => {
      libererOverview = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        const href = String(url)
        if (href.includes('/api/auth/login')) {
          return { ok: true, status: 200, json: async () => ({ session_id: 'sess-test' }) }
        }
        if (href.includes('/api/auth/logout')) {
          return { ok: true, status: 200, json: async () => ({}) }
        }
        await overviewEnAttente
        return { ok: true, status: 200, json: async () => OVERVIEW_A }
      }),
    )

    const { result } = renderBankingApp()

    let connexion
    await act(async () => {
      connexion = result.current.login('malak.drissi', 'x')
    })
    expect(result.current.overviewStatus).toBe('loading')

    await act(async () => {
      await result.current.logout()
    })

    await act(async () => {
      libererOverview()
      await connexion
    })

    expect(result.current.overview).toBeNull()
    expect(result.current.overviewStatus).toBe('idle')
    expect(result.current.isAuthenticated).toBe(false)
  })

  it('avant authentification, aucune donnee bancaire reelle n’est exposee', async () => {
    stubBackend()
    const { result } = renderBankingApp()

    expect(result.current.overview).toBeNull()
    expect(result.current.totalBalance).toBeNull()
    expect(result.current.card).toBeNull()
    // L'ecran public reste sur les donnees de demonstration, assumees comme telles.
    expect(result.current.account).toBe(mockAccount)
    expect(result.current.transactions).toBe(mockTransactions)
  })
})

// ---------------------------------------------------------------------------
// Politique d'exposition des donnees sensibles
// ---------------------------------------------------------------------------

describe('donnees sensibles', () => {
  it('le compte affiche utilise la reference masquee, jamais la cle technique', async () => {
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    expect(result.current.account.number).toContain('••••')
    // `id_compte` n'est pas transmis par le backend : il ne doit exister nulle part.
    for (const compte of result.current.accounts) {
      expect(compte).not.toHaveProperty('accountId')
      expect(compte).not.toHaveProperty('id_compte')
    }
  })

  it('la carte reste masquee et ne porte ni CVV ni PIN', async () => {
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    expect(result.current.card.maskedCardNumber).toContain('XXXXXX')
    expect(result.current.card.maskedCardNumber).not.toMatch(/^\d{16}$/)
    expect(result.current.card).not.toHaveProperty('cvv')
    expect(result.current.card).not.toHaveProperty('pin')
  })

  it('le RIB et l’IBAN complets sont bien remis au proprietaire authentifie', async () => {
    // Politique assumee (revision de la regle initiale de masquage) : le client
    // authentifie recoit ses PROPRES coordonnees bancaires en clair.
    stubBackend()
    const { result } = renderBankingApp()

    await connecter(result)
    await waitFor(() => expect(result.current.overviewStatus).toBe('ready'))

    expect(result.current.accounts[0].rib).toBe('230810000110001100011006')
    expect(result.current.accounts[0].iban).toBe('MA26230810000110001100011006')
  })
})
