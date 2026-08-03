import { useBankingApp } from '../context/BankingAppProvider.jsx'
import MobileLoginView from './mobile/MobileLoginView.jsx'
import MobileDashboard from './mobile/MobileDashboard.jsx'
import ChatFab from './chat/ChatFab.jsx'

// Cadre de telephone REALISTE ET INTERACTIF (pas une image decorative) - affiche uniquement a
// partir de 1280px, aux cotes de DesktopView (voir DocsContext/05_interface_frontend.md §17).
// Lit l'etat partage directement depuis BankingAppProvider : toute action posee ici (connexion,
// solde, chat...) est immediatement visible dans DesktopView, et inversement.
export default function PhonePreview() {
  const { isAuthenticated, chatOpen, chatHasUnread, toggleChat } = useBankingApp()

  return (
    <div className="flex flex-col items-center gap-3">
      <p className="text-xs font-medium text-gray-400">Téléphone (interactif)</p>
      <div className="relative mx-auto aspect-[9/19.5] w-full max-w-[340px] overflow-hidden rounded-[2.25rem] border-[8px] border-gray-900 bg-white shadow-2xl">
        <div
          aria-hidden="true"
          className="absolute left-1/2 top-1.5 z-10 h-4 w-20 -translate-x-1/2 rounded-full bg-gray-900"
        />

        <div className="h-full w-full overflow-y-auto">
          {isAuthenticated ? <MobileDashboard standalone={false} /> : <MobileLoginView />}
        </div>

        <div className="absolute bottom-4 right-4 z-20">
          <ChatFab onToggle={toggleChat} variant="mobile" hasUnread={chatHasUnread && !chatOpen} />
        </div>
      </div>
    </div>
  )
}
