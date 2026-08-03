import Sidebar from './Sidebar.jsx'
import DesktopHeader from './DesktopHeader.jsx'
import SpendingChart from './SpendingChart.jsx'
import BankCard from './BankCard.jsx'
import AccountCard from '../shared/AccountCard.jsx'
import RecentTransactions from '../shared/RecentTransactions.jsx'
import QuickActions from '../shared/QuickActions.jsx'
import { useBankingApp } from '../../context/BankingAppProvider.jsx'
import { mockCard } from '../../data/mockAccount.js'
import { mockSpendingCategories } from '../../data/mockSpending.js'

// Dashboard desktop agrandi - voir DocsContext/05_interface_frontend.md §13.
// Meme carte de compte, memes six raccourcis, memes transactions que la version mobile (memes
// donnees issues de BankingAppProvider) ; ajoute uniquement des visualisations complementaires
// (graphique de depenses, carte bancaire fictive, encart de securite) presentant les memes donnees.
export default function DesktopDashboard() {
  const { account, balanceVisible, onToggleBalance, transactions } = useBankingApp()

  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar />

      <div className="flex-1 min-w-0">
        <DesktopHeader />

        <div className="grid grid-cols-1 gap-6 px-6 py-6 sm:px-8 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <AccountCard account={account} balanceVisible={balanceVisible} onToggleBalance={onToggleBalance} />
            <QuickActions layout="row" />
            <RecentTransactions transactions={transactions} />
          </div>

          <div className="space-y-6">
            <SpendingChart categories={mockSpendingCategories} />
            <BankCard card={mockCard} />
          </div>
        </div>

        <p className="text-center text-[11px] text-gray-400 pb-6">
          Démonstration académique — aucune opération réelle
        </p>
      </div>
    </div>
  )
}
