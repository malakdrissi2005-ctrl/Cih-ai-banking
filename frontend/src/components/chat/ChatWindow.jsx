import { Bot, X, Send } from 'lucide-react'
import ChatMessage from './ChatMessage.jsx'
import TypingIndicator from './TypingIndicator.jsx'
import QuickSuggestions from './QuickSuggestions.jsx'

export default function ChatWindow({
  activeAgent,
  messages,
  isTyping,
  draft,
  setDraft,
  onSend,
  onMinimize,
  suggestions,
  onPickSuggestion,
  onTransferConfirm,
  onTransferCancel,
  onOtpSubmit,
  onOtpResend,
}) {
  function handleSubmit(e) {
    e.preventDefault()
    if (!draft.trim()) return
    onSend(draft.trim())
  }

  return (
    <div
      className="fixed left-3 right-3 top-16 bottom-3 z-50 flex flex-col overflow-hidden
                rounded-2xl bg-white shadow-xl
                sm:left-auto sm:right-0 sm:top-0 sm:bottom-0 sm:h-screen sm:w-[400px]
                sm:rounded-none sm:rounded-l-2xl sm:shadow-2xl sm:border-l sm:border-gray-100"
    >
      {/* En-tête */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-full bg-cih-blue-light flex items-center justify-center">
            <Bot className="w-5 h-5 text-cih-blue" />
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-900">
              {activeAgent === 'secure_operation' ? 'Mode opération sécurisée' : 'Assistant bancaire'}
            </p>
            <p className="text-[11px] text-green-600 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500" /> En ligne
            </p>
          </div>
        </div>

        <button
          onClick={onMinimize}
          aria-label="Fermer l'assistant"
          className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition"
        >
          Fermer
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Zone de messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 bg-cih-surface">
        {messages.length === 0 && (
          <p className="text-xs text-gray-400 text-center pt-4">
            Posez une question, ou choisissez une suggestion ci-dessous.
          </p>
        )}
        {messages.map((m) => (
          <ChatMessage
            key={m.id}
            message={m}
            onTransferConfirm={onTransferConfirm}
            onTransferCancel={onTransferCancel}
            onOtpSubmit={onOtpSubmit}
            onOtpResend={onOtpResend}
          />
        ))}
        {isTyping && <TypingIndicator />}
      </div>

      <QuickSuggestions suggestions={suggestions} onPick={onPickSuggestion} disabled={isTyping} />

      {/* Zone de saisie */}
      <form onSubmit={handleSubmit} className="border-t border-gray-100 px-3 py-2.5 flex items-center gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Écrivez votre message…"
          className="flex-1 bg-gray-100 rounded-full px-4 py-2 text-sm
                     focus:outline-none focus:ring-2 focus:ring-cih-orange"
        />
        <button
          type="submit"
          aria-label="Envoyer"
          className="w-9 h-9 rounded-full bg-cih-orange text-white flex items-center
                     justify-center hover:bg-cih-orange-dark transition"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>
    </div>
  )
}
