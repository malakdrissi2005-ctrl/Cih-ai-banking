// Les DEUX tableaux de bord, montes ensemble dans un seul BankingAppProvider.
//
// C'est la preuve de bout en bout de la regle §9.1 de CLAUDE.md : le telephone
// et le panneau desktop ne sont pas deux applications, mais deux rendus d'un
// meme etat. Ce test les monte cote a cote et verifie qu'ils affichent les
// memes valeurs au meme instant — et qu'une action posee sur l'un se voit
// immediatement sur l'autre.

import { render, cleanup, waitFor, act, fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BankingAppProvider, useBankingApp } from '../context/BankingAppProvider.jsx'
import MobileDashboard from './mobile/MobileDashboard.jsx'
import DesktopDashboard from './desktop/DesktopDashboard.jsx'
import { mockAccount } from '../data/mockAccount.js'

const OVERVIEW = {
  customer_id: 'CL0001',
  full_name: 'Malak Drissi',
  total_balance: '106318.39',
  accounts: [
    { account_type: 'courant', masked_account_number: 'CIH •••• 1006', account_number: '0001100011000110',
      rib: '230810000110001100011006', iban: 'MA26230810000110001100011006', currency: 'MAD', balance: '68009.15' },
    { account_type: 'carnet', masked_account_number: 'CIH •••• 2009', account_number: '0001200012000120',
      rib: '230810000120001200012009', iban: 'MA26230810000120001200012009', currency: 'MAD', balance: '28010.49' },
    { account_type: 'carnet', masked_account_number: 'CIH •••• 3012', account_number: '0001300013000130',
      rib: '230810000130001300013012', iban: 'MA26230810000130001300013012', currency: 'MAD', balance: '10298.75' },
  ],
  recent_transactions: [
    { date: '2026-07-28', label: 'Paiement carte station-service', category: 'Carburant', direction: 'debit', amount: '1305.00', currency: 'MAD' },
    { date: '2026-07-26', label: 'Virement recu', category: 'Virement reçu', direction: 'credit', amount: '1050.62', currency: 'MAD' },
  ],
  card: { card_type: 'Visa Classic', masked_card_number: '450078XXXXXX7007', status: 'active', payment_limit: '5000', withdrawal_limit: '2000' },
}

let sonde = null

function Connexion() {
  sonde = useBankingApp()
  return null
}

function stubBackend({ overviewThrows = false } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url) => {
      const href = String(url)
      if (href.includes('/api/auth/login')) {
        return { ok: true, status: 200, json: async () => ({ session_id: 'sess-test' }) }
      }
      if (overviewThrows) throw new TypeError('Failed to fetch')
      return { ok: true, status: 200, json: async () => OVERVIEW }
    }),
  )
}

function monterLesDeux() {
  return render(
    <BankingAppProvider>
      <Connexion />
      <div data-testid="telephone">
        <MobileDashboard standalone={false} />
      </div>
      <div data-testid="bureau">
        <DesktopDashboard />
      </div>
    </BankingAppProvider>,
  )
}

const normaliser = (n) => n.textContent.replace(/[\u202f\u00a0]/g, ' ')

beforeEach(() => sessionStorage.clear())
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
  sonde = null
})

describe('Tableaux de bord mobile et desktop synchronises', () => {
  it('affichent tous deux les valeurs reelles du backend, jamais mockAccount', async () => {
    stubBackend()
    const { getByTestId } = monterLesDeux()

    await act(async () => {
      await sonde.login('malak.drissi', 'x')
    })
    await waitFor(() => expect(sonde.overviewStatus).toBe('ready'))
    act(() => sonde.onToggleBalance()) // rend les montants visibles

    for (const panneau of ['telephone', 'bureau']) {
      const texte = normaliser(getByTestId(panneau))
      expect(texte).toContain('68 009,15 MAD') // compte selectionne
      expect(texte).toContain('106 318,39 MAD') // total tous comptes
      expect(texte).toContain('CIH •••• 1006')
      expect(texte).not.toContain('15 420,50') // mockAccount
      expect(texte).not.toContain(mockAccount.number)
    }
  })

  it('reagissent ensemble et instantanement au changement de compte', async () => {
    stubBackend()
    const { getByTestId } = monterLesDeux()

    await act(async () => {
      await sonde.login('malak.drissi', 'x')
    })
    await waitFor(() => expect(sonde.overviewStatus).toBe('ready'))
    act(() => sonde.onToggleBalance())

    // Le clic est fait DANS le telephone ; le panneau desktop doit suivre.
    const boutonsTelephone = [...getByTestId('telephone').querySelectorAll('[aria-pressed]')]
    expect(boutonsTelephone).toHaveLength(3)
    fireEvent.click(boutonsTelephone[1])

    for (const panneau of ['telephone', 'bureau']) {
      const texte = normaliser(getByTestId(panneau))
      expect(texte).toContain('28 010,49 MAD') // nouveau compte selectionne
      expect(texte).toContain('CIH •••• 2009')
      expect(texte).toContain('106 318,39 MAD') // le total ne bouge pas
      expect(texte).not.toContain('68 009,15')
    }
  })

  it('affichent la meme erreur, et aucun montant, si l’API echoue', async () => {
    stubBackend({ overviewThrows: true })
    const { getByTestId } = monterLesDeux()

    await act(async () => {
      await sonde.login('malak.drissi', 'x')
    })
    await waitFor(() => expect(sonde.overviewStatus).toBe('error'))

    for (const panneau of ['telephone', 'bureau']) {
      const texte = normaliser(getByTestId(panneau))
      expect(texte).toContain('momentanément indisponibles')
      // Le point critique : AUCUN montant simule ne prend la place du vrai.
      expect(texte).not.toContain('15 420,50')
      expect(texte).not.toContain('MAD')
    }
  })

  it('n’affichent jamais le numero de carte complet', async () => {
    stubBackend()
    const { getByTestId } = monterLesDeux()

    await act(async () => {
      await sonde.login('malak.drissi', 'x')
    })
    await waitFor(() => expect(sonde.overviewStatus).toBe('ready'))

    const bureau = getByTestId('bureau').textContent
    expect(bureau).toContain('450078XXXXXX7007')
    expect(bureau).not.toMatch(/\b\d{16}\b/)
  })
})
