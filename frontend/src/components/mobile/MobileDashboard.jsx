import Navbar from '../Navbar.jsx'
import AccountCard from '../shared/AccountCard.jsx'
import RecentTransactions from '../shared/RecentTransactions.jsx'
import QuickActions from '../shared/QuickActions.jsx'
import BottomNav from './BottomNav.jsx'
import { useBankingApp } from '../../context/BankingAppProvider.jsx'

// Dashboard mobile - voir DocsContext/05_interface_frontend.md §12.
// Toutes les donnees et l'etat (solde visible, utilisateur) viennent de BankingAppProvider - rien
// n'est code en dur ni duplique localement, afin de rester strictement synchronise avec le desktop.
// Props: standalone (true = vrai mobile plein ecran ; false = miniature dans PhonePreview)
export default function MobileDashboard({ standalone = true }) {
  const { userName, account, balanceVisible, onToggleBalance, transactions, logout } = useBankingApp()
  const recentTransactions = transactions.slice(0, 3)

  return (
    <div className={`bg-cih-surface ${standalone ? 'min-h-screen pb-20' : 'h-full overflow-y-auto'}`}>
      <Navbar authenticated onLogout={logout} />

      <div className="px-4 pt-2 pb-2 border-b-2 border-cih-orange">
        <p className="text-cih-orange font-bold text-sm">Bonjour {userName} !</p>
      </div>

      <AccountCard account={account} balanceVisible={balanceVisible} onToggleBalance={onToggleBalance} />

      <div className="px-4 mt-4">
        <QuickActions layout="grid" />
      </div>

      <div className="mx-4 mt-4">
        <RecentTransactions transactions={recentTransactions} />
      </div>

      <p className="text-center text-[11px] text-gray-400 mt-4 px-4">
        Démonstration académique — aucune opération réelle
      </p>

      <div className={standalone ? '' : 'mt-2'}>
        <BottomNav />
      </div>
    </div>
  )
}
