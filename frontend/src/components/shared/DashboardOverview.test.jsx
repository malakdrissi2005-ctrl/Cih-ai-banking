// Rendu des composants du tableau de bord alimentes par GET /api/banking/overview.
//
// Complete BankingOverview.test.jsx, qui verifie l'ETAT ; ici on verifie ce qui
// est reellement AFFICHE — c'est la contradiction visible a l'ecran entre le
// tableau de bord et le chatbot qui etait le probleme d'origine.

import { render, cleanup, fireEvent } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AccountCard from './AccountCard.jsx'
import AccountSelector from './AccountSelector.jsx'
import OverviewStatusBanner from './OverviewStatusBanner.jsx'
import RecentTransactions from './RecentTransactions.jsx'

// `globals` n'est pas active dans vite.config.js : le nettoyage automatique de
// Testing Library ne s'execute pas, il faut l'appeler explicitement.
afterEach(cleanup)

const COMPTE = { type: 'courant', number: 'CIH •••• 1006', balance: '68009.15' }

const COMPTES = [
  { accountType: 'courant', maskedAccountNumber: 'CIH •••• 1006' },
  { accountType: 'carnet', maskedAccountNumber: 'CIH •••• 2009' },
  { accountType: 'carnet', maskedAccountNumber: 'CIH •••• 3012' },
]

describe('AccountCard', () => {
  it('affiche le solde du compte et le total tous comptes, distincts', () => {
    const { container } = render(
      <AccountCard
        account={COMPTE}
        balanceVisible
        onToggleBalance={() => {}}
        totalBalance="106318.39"
      />,
    )
    // fr-FR separe les milliers par une espace insecable etroite (U+202F) :
    // on normalise avant de comparer.
    const texte = container.textContent.replace(/[\u202f\u00a0]/g, ' ')
    expect(texte).toContain('68 009,15 MAD')
    expect(texte).toContain('106 318,39 MAD')
    expect(texte).toContain('Total tous comptes')
  })

  it('n’affiche pas de total pour un client mono-compte', () => {
    const { container } = render(
      <AccountCard
        account={COMPTE}
        balanceVisible
        onToggleBalance={() => {}}
        totalBalance="68009.15"
      />,
    )
    expect(container.textContent).not.toContain('Total tous comptes')
  })

  it('reste compatible avec un appel sans totalBalance', () => {
    const { container } = render(
      <AccountCard account={COMPTE} balanceVisible onToggleBalance={() => {}} />,
    )
    expect(container.textContent).not.toContain('Total tous comptes')
    expect(container.textContent).toContain('CIH •••• 1006')
  })

  it('masque le total comme le solde quand la visibilite est coupee', () => {
    const { container } = render(
      <AccountCard
        account={COMPTE}
        balanceVisible={false}
        onToggleBalance={() => {}}
        totalBalance="106318.39"
      />,
    )
    // Aucun chiffre de solde ne doit fuiter quand l'utilisateur masque le montant.
    expect(container.textContent).not.toContain('68')
    expect(container.textContent).not.toContain('106')
    expect(container.textContent).toContain('**** MAD')
  })
})

describe('AccountSelector', () => {
  it('affiche un bouton par compte, y compris deux comptes du meme type', () => {
    const { container } = render(
      <AccountSelector accounts={COMPTES} selectedIndex={0} onSelect={() => {}} />,
    )
    const boutons = container.querySelectorAll('button')
    expect(boutons).toHaveLength(3)
    // Les deux carnets se distinguent par leur reference masquee.
    expect(container.textContent).toContain('CIH •••• 2009')
    expect(container.textContent).toContain('CIH •••• 3012')
  })

  it('marque le compte selectionne et notifie le changement', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <AccountSelector accounts={COMPTES} selectedIndex={1} onSelect={onSelect} />,
    )
    const boutons = [...container.querySelectorAll('button')]
    expect(boutons[1].getAttribute('aria-pressed')).toBe('true')
    expect(boutons[0].getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(boutons[2])
    expect(onSelect).toHaveBeenCalledWith(2)
  })

  it('ne s’affiche pas pour un client mono-compte', () => {
    const { container } = render(
      <AccountSelector accounts={[COMPTES[0]]} selectedIndex={0} onSelect={() => {}} />,
    )
    expect(container.innerHTML).toBe('')
  })
})

describe('OverviewStatusBanner', () => {
  it('reste invisible quand les donnees sont pretes', () => {
    const { container } = render(<OverviewStatusBanner status="ready" error={null} onRetry={() => {}} />)
    expect(container.innerHTML).toBe('')
  })

  it('annonce le chargement', () => {
    const { container } = render(<OverviewStatusBanner status="loading" error={null} onRetry={() => {}} />)
    expect(container.textContent).toContain('Chargement')
    expect(container.querySelector('[role="status"]')).not.toBeNull()
  })

  it('sur erreur reseau, propose de reessayer et n’affiche aucun montant', () => {
    const onRetry = vi.fn()
    const { container } = render(
      <OverviewStatusBanner status="error" error="network" onRetry={onRetry} />,
    )
    expect(container.textContent).toContain('momentanément indisponibles')
    // Aucun chiffre : surtout pas un solde de demonstration presente comme reel.
    expect(container.textContent).not.toMatch(/\d/)

    fireEvent.click(container.querySelector('button'))
    expect(onRetry).toHaveBeenCalled()
  })

  it('sur session expiree, invite a se reconnecter sans bouton Reessayer', () => {
    const { container } = render(
      <OverviewStatusBanner status="error" error="unauthorized" onRetry={() => {}} />,
    )
    expect(container.textContent).toContain('session a expiré')
    expect(container.querySelector('button')).toBeNull()
  })

  it('ne revele jamais de detail technique', () => {
    for (const raison of ['network', 'invalid', 'unauthorized']) {
      const { container } = render(
        <OverviewStatusBanner status="error" error={raison} onRetry={() => {}} />,
      )
      const texte = container.textContent
      expect(texte).not.toContain('/api/')
      expect(texte).not.toContain('401')
      expect(texte.toLowerCase()).not.toContain('bearer')
      cleanup()
    }
  })
})

describe('RecentTransactions avec les donnees du backend', () => {
  // Format produit par BankingAppProvider a partir de l'overview.
  const TRANSACTIONS = [
    { id: '2026-07-28-0', label: 'Paiement carte station-service', date: '2026-07-28', amount: '1305.00', direction: 'out' },
    { id: '2026-07-26-1', label: 'Virement recu', date: '2026-07-26', amount: '1050.62', direction: 'in' },
  ]

  it('affiche un seul signe par montant, du bon sens', () => {
    // NON-REGRESSION : une premiere version du provider signait deja le montant,
    // ce qui produisait « --1 305,00 » puisque le composant ajoute son signe.
    const { container } = render(<RecentTransactions transactions={TRANSACTIONS} />)
    const texte = container.textContent.replace(/[\u202f\u00a0]/g, ' ')
    expect(texte).toContain('-1 305,00 MAD')
    expect(texte).toContain('+1 050,62 MAD')
    expect(texte).not.toContain('--')
    expect(texte).not.toContain('+-')
  })
})
