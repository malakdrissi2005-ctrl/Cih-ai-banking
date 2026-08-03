import { useBankingApp } from '../../context/BankingAppProvider.jsx'
import MobileLoginView from './MobileLoginView.jsx'
import MobileDashboard from './MobileDashboard.jsx'
import ChatFab from '../chat/ChatFab.jsx'

// Vrai ecran mobile (< 640px) - affiche directement l'application, sans cadre decoratif -
// voir DocsContext/05_interface_frontend.md §17. Utilise le meme etat global partage que
// PhonePreview/DesktopView (BankingAppProvider) : aucune logique dupliquee.
export default function MobileAppView() {
  const { isAuthenticated, chatOpen, chatHasUnread, toggleChat } = useBankingApp()

  return (
    <div className="relative min-h-screen">
      {isAuthenticated ? <MobileDashboard standalone /> : <MobileLoginView />}

      <div className="fixed bottom-6 right-6 z-40">
        <ChatFab onToggle={toggleChat} variant="mobile" hasUnread={chatHasUnread && !chatOpen} />
      </div>
    </div>
  )
}
