import { Search, Mail, Bell } from 'lucide-react'
import { useBankingApp } from '../../context/BankingAppProvider.jsx'

// En-tete du dashboard desktop - voir DocsContext/05_interface_frontend.md §13.2 :
// salutation (reprise a l'identique de la version mobile, taille agrandie), messages, notifications.
export default function DesktopHeader() {
  const { userName } = useBankingApp()

  return (
    <div className="flex items-center justify-between gap-4 px-6 py-5 sm:px-8">
      <div>
        <p className="text-lg font-bold text-gray-900">
          Bonjour <span className="text-cih-orange">{userName}</span> !
        </p>
        <p className="text-xs text-gray-400">Voici un aperçu de votre compte aujourd’hui.</p>
      </div>

      <div className="flex items-center gap-4">
        <button aria-label="Rechercher" className="text-gray-400 hover:text-cih-blue transition">
          <Search className="w-5 h-5" />
        </button>
        <button aria-label="Messages" className="text-gray-400 hover:text-cih-blue transition">
          <Mail className="w-5 h-5" />
        </button>
        <button aria-label="Notifications" className="relative text-gray-400 hover:text-cih-blue transition">
          <Bell className="w-5 h-5" />
          <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-cih-orange" />
        </button>
      </div>
    </div>
  )
}
