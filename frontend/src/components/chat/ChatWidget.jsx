import ChatWindow from './ChatWindow.jsx'
import { useBankingApp } from '../../context/BankingAppProvider.jsx'

// Composant racine du chat - monte une seule fois dans App.jsx (voir CLAUDE.md §9.3 et
// DocsContext/05_interface_frontend.md §14). Ne possede aucun etat local : conversation, agent
// actif et etat d'ouverture proviennent tous de BankingAppProvider, la source unique partagee
// entre le telephone et le panneau desktop. Ne rend plus lui-meme de ChatFab : les deux boutons
// d'acces vivent dans PhonePreview/DesktopView/MobileAppView et pilotent ce meme widget via le
// contexte partage.
export default function ChatWidget() {
  const {
    chatOpen,
    closeChat,
    messages,
    isTyping,
    activeAgent,
    draft,
    setDraft,
    suggestions,
    sendMessage,
    confirmTransfer,
    cancelTransfer,
    submitOtp,
    resendOtp,
  } = useBankingApp()

  if (!chatOpen) return null

  return (
    <ChatWindow
      activeAgent={activeAgent}
      messages={messages}
      isTyping={isTyping}
      draft={draft}
      setDraft={setDraft}
      onSend={sendMessage}
      onMinimize={closeChat}
      suggestions={suggestions}
      onPickSuggestion={sendMessage}
      onTransferConfirm={confirmTransfer}
      onTransferCancel={cancelTransfer}
      onOtpSubmit={submitOtp}
      onOtpResend={resendOtp}
    />
  )
}
