import Navbar from '../Navbar.jsx'
import AccountCard from '../shared/AccountCard.jsx'
import AccountSelector from '../shared/AccountSelector.jsx'
import OverviewStatusBanner from '../shared/OverviewStatusBanner.jsx'
import RecentTransactions from '../shared/RecentTransactions.jsx'
import QuickActions from '../shared/QuickActions.jsx'
import BottomNav from './BottomNav.jsx'
import { useBankingApp } from '../../context/BankingAppProvider.jsx'

// Dashboard mobile - voir DocsContext/05_interface_frontend.md §12.
// Toutes les donnees et l'etat (solde visible, utilisateur) viennent de BankingAppProvider - rien
// n'est code en dur ni duplique localement, afin de rester strictement synchronise avec le desktop.
// Props: standalone (true = vrai mobile plein ecran ; false = miniature dans PhonePreview)
export default function MobileDashboard({ standalone = true }) {
  const {
    userName,
    account,
    balanceVisible,
    onToggleBalance,
    transactions,
    logout,
    accounts,
    selectedAccountIndex,
    selectAccount,
    totalBalance,
    overviewStatus,
    overviewError,
    retryOverview,
  } = useBankingApp()
  const recentTransactions = transactions.slice(0, 3)

  // Tant que les donnees reelles ne sont pas la, on n'affiche AUCUN montant :
  // pas de repli sur les donnees simulees, qui seraient prises pour de vraies.
  const donneesPretes = overviewStatus === 'ready'

  return (
    <div className={`bg-cih-surface ${standalone ? 'min-h-screen pb-20' : 'h-full overflow-y-auto'}`}>
      <Navbar authenticated onLogout={logout} />

      {userName && (
        <div className="px-4 pt-2 pb-2 border-b-2 border-cih-orange">
          <p className="text-cih-orange font-bold text-sm">Bonjour {userName} !</p>
        </div>
      )}

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

      <div className="px-4 mt-4">
        <QuickActions layout="grid" />
      </div>

      {donneesPretes && (
        <div className="mx-4 mt-4">
          <RecentTransactions transactions={recentTransactions} />
        </div>
      )}

      <p className="text-center text-[11px] text-gray-400 mt-4 px-4">
        Démonstration académique — aucune opération réelle
      </p>

      <div className={standalone ? '' : 'mt-2'}>
        <BottomNav />
      </div>
    </div>
  )
}
