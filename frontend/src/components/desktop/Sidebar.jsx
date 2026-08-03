import { Home, ArrowLeftRight, CreditCard, Headphones, LogOut, Landmark } from 'lucide-react'
import { useBankingApp } from '../../context/BankingAppProvider.jsx'

// Sidebar desktop - adaptation de la navigation inferieure mobile (Accueil, Virements, Cartes,
// Assistance), voir DocsContext/05_interface_frontend.md §13.1. Navigation demonstrative (pas de
// routage reel en Phase 1) ; la deconnexion agit sur l'etat partage (BankingAppProvider).
export default function Sidebar() {
  const { logout } = useBankingApp()

  const items = [
    { icon: Home, label: 'Accueil', active: true },
    { icon: ArrowLeftRight, label: 'Virements' },
    { icon: CreditCard, label: 'Cartes' },
    { icon: Headphones, label: 'Assistance' },
  ]

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-gray-100 bg-white py-6">
      <div className="flex items-center gap-2 px-6 pb-8">
        <Landmark className="w-6 h-6 text-cih-blue shrink-0" />
        <span className="text-sm font-bold text-gray-900 leading-tight">
          CIH AI Banking
          <br />
          <span className="text-[11px] font-medium text-gray-400">Démonstration</span>
        </span>
      </div>

      <nav className="flex-1 space-y-1 px-3">
        {items.map((item) => (
          <div
            key={item.label}
            className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium ${
              item.active ? 'bg-cih-blue-light text-cih-blue' : 'text-gray-600'
            }`}
          >
            <item.icon className="w-5 h-5 shrink-0" />
            {item.label}
          </div>
        ))}
      </nav>

      <div className="px-3 pt-4">
        <button
          onClick={logout}
          className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-gray-500 hover:bg-red-50 hover:text-red-600 transition duration-200"
        >
          <LogOut className="w-5 h-5 shrink-0" />
          Déconnexion
        </button>
      </div>
    </aside>
  )
}
