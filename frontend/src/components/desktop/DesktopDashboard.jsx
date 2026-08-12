import Sidebar from './Sidebar.jsx'
import DesktopHeader from './DesktopHeader.jsx'
import SpendingChart from './SpendingChart.jsx'
import BankCard from './BankCard.jsx'
import AccountCard from '../shared/AccountCard.jsx'
import AccountSelector from '../shared/AccountSelector.jsx'
import OverviewStatusBanner from '../shared/OverviewStatusBanner.jsx'
import RecentTransactions from '../shared/RecentTransactions.jsx'
import QuickActions from '../shared/QuickActions.jsx'
import { useBankingApp } from '../../context/BankingAppProvider.jsx'
import { mockSpendingCategories } from '../../data/mockSpending.js'

/** Adapte la carte renvoyee par le backend au format attendu par `BankCard`.
 *
 * Le backend n'expose QUE le numero masque, le type et le statut : ni PAN
 * complet, ni CVV, ni PIN, ni date d'expiration. La vignette n'invente donc
 * pas d'echeance - elle affiche le statut, qui est une information reelle.
 *
 * Retourne `null` si le client n'a pas de carte : on n'affiche PAS `mockCard`
 * a la place. Une carte de demonstration presentee a un client authentifie
 * serait prise pour la sienne.
 */
function toBankCard(card) {
  if (!card) return null
  return {
    label: card.cardType,
    maskedNumber: card.maskedCardNumber,
    holder: '',
    expiry: card.status === 'active' ? 'Active' : card.status,
  }
}

// Dashboard desktop agrandi - voir DocsContext/05_interface_frontend.md §13.
// Meme carte de compte, memes six raccourcis, memes transactions que la version mobile (memes
// donnees issues de BankingAppProvider) ; ajoute uniquement des visualisations complementaires
// (graphique de depenses, carte bancaire fictive, encart de securite) presentant les memes donnees.
export default function DesktopDashboard() {
  const {
    account,
    balanceVisible,
    onToggleBalance,
    transactions,
    accounts,
    selectedAccountIndex,
    selectAccount,
    totalBalance,
    card,
    overviewStatus,
    overviewError,
    retryOverview,
  } = useBankingApp()

  // Meme condition que le panneau mobile : les deux rendus affichent et masquent
  // exactement les memes donnees au meme instant (CLAUDE.md §9.1).
  const donneesPretes = overviewStatus === 'ready'
  const bankCard = toBankCard(card)

  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar />

      <div className="flex-1 min-w-0">
        <DesktopHeader />

        <div className="grid grid-cols-1 gap-6 px-6 py-6 sm:px-8 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <OverviewStatusBanner
              status={overviewStatus}
              error={overviewError}
              onRetry={retryOverview}
            />

            {donneesPretes && (
              <>
                <AccountSelector
                  accounts={accounts}
                  selectedIndex={selectedAccountIndex}
                  onSelect={selectAccount}
                />
                <AccountCard
                  account={account}
                  balanceVisible={balanceVisible}
                  onToggleBalance={onToggleBalance}
                  totalBalance={totalBalance}
                />
              </>
            )}

            <QuickActions layout="row" />

            {donneesPretes && <RecentTransactions transactions={transactions} />}
          </div>

          {/* Colonne de visualisations complementaires. Elle ne s'affiche pas tant
              que les donnees reelles ne sont pas la : sinon, ses montants seraient
              les seuls chiffres a l'ecran pendant une panne, et seraient pris pour
              les vrais. */}
          {donneesPretes && (
            <div className="space-y-6">
              {/* SEUL element encore simule apres authentification : le backend
                  n'expose pas cette agregation via /api/banking/overview. Il est
                  donc explicitement etiquete comme tel a l'ecran. */}
              <div>
                <SpendingChart categories={mockSpendingCategories} />
                <p className="mt-2 text-center text-[11px] text-gray-400">
                  Répartition simulée — non issue de votre compte
                </p>
              </div>
              {bankCard && <BankCard card={bankCard} />}
            </div>
          )}
        </div>

        <p className="text-center text-[11px] text-gray-400 pb-6">
          Démonstration académique — aucune opération réelle
        </p>
      </div>
    </div>
  )
}
