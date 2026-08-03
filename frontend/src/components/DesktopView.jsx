import { useBankingApp } from '../context/BankingAppProvider.jsx'
import DesktopLoginView from './desktop/DesktopLoginView.jsx'
import DesktopDashboard from './desktop/DesktopDashboard.jsx'
import ChatFab from './chat/ChatFab.jsx'

// Equivalent desktop de PhonePreview - voir DocsContext/05_interface_frontend.md §17.
// Recoit exactement le meme etat partage (BankingAppProvider) : jamais une copie, jamais une
// divergence possible avec le telephone. Rendu seul entre 640 et 1279px, aux cotes de
// PhonePreview a partir de 1280px (voir ResponsiveShowcase).
export default function DesktopView() {
  const { isAuthenticated, chatOpen, chatHasUnread, toggleChat } = useBankingApp()

  return (
    <div className="relative w-full min-w-0 overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-md">
      {isAuthenticated ? <DesktopDashboard /> : <DesktopLoginView />}

      <div className="absolute bottom-6 right-6 z-20">
        <ChatFab onToggle={toggleChat} variant="desktop" hasUnread={chatHasUnread && !chatOpen} />
      </div>
    </div>
  )
}
