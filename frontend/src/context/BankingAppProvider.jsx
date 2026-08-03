import { createContext, useContext, useEffect, useState } from 'react'
import { mockUser, mockAccount } from '../data/mockAccount.js'
import { mockTransactions } from '../data/mockTransactions.js'
import { publicSuggestions, authenticatedSuggestions } from '../data/chatSuggestions.js'
import {
  simulateAssistantReply,
  buildOtpRequestMessage,
  buildTransferResultMessage,
  buildCancelledMessage,
  textMessage,
  DEMO_OTP_CODE,
  OTP_MAX_ATTEMPTS,
} from '../data/chatSimulation.js'
import { loginRequest, checkSessionRequest, logoutRequest } from '../data/authApi.js'

// Cle de stockage du session_id opaque (Backend, voir CLAUDE.md §4) - conserve uniquement
// pour la session de navigation courante (sessionStorage), jamais un JWT, jamais persiste
// au-dela de la fermeture de l'onglet.
const SESSION_STORAGE_KEY = 'cih_session_id'

// Source d'etat unique de l'application (voir CLAUDE.md §9.1 et DocsContext/05_interface_frontend.md §5).
// Le telephone (PhonePreview / MobileAppView) et le panneau desktop (DesktopView) lisent et
// modifient EXACTEMENT le meme etat via ce contexte - aucune divergence possible entre les deux
// rendus puisqu'il n'existe qu'une seule source de verite, jamais deux copies locales.
const BankingAppContext = createContext(null)

const HIGHLIGHT_DURATION_MS = 2500

export function BankingAppProvider({ children }) {
  // --- Authentification & session (partagees) ---
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [highlightLogin, setHighlightLogin] = useState(false)

  // --- Compte & solde (partages) ---
  const [balanceVisible, setBalanceVisible] = useState(false)

  // --- Assistant IA : un seul etat de conversation pour les deux boutons d'acces ---
  const [chatOpen, setChatOpen] = useState(false)
  const [chatHasUnread, setChatHasUnread] = useState(false)
  const [messages, setMessages] = useState([])
  const [isTyping, setIsTyping] = useState(false)
  const [activeAgent, setActiveAgent] = useState('assistant')
  const [draft, setDraft] = useState('')

  const suggestions = isAuthenticated ? authenticatedSuggestions : publicSuggestions

  // Au demarrage : si un session_id existe encore (onglet rouvert/rafraichi), verifie sa
  // validite aupres du Backend avant de considerer l'utilisateur comme authentifie.
  useEffect(() => {
    const storedSessionId = sessionStorage.getItem(SESSION_STORAGE_KEY)
    if (!storedSessionId) return

    checkSessionRequest(storedSessionId).then((result) => {
      if (result.ok) {
        setIsAuthenticated(true)
      } else {
        sessionStorage.removeItem(SESSION_STORAGE_KEY)
      }
    })
  }, [])

  async function login(username, password) {
    const result = await loginRequest(username, password)
    if (!result.ok) {
      return { ok: false }
    }
    sessionStorage.setItem(SESSION_STORAGE_KEY, result.sessionId)
    setIsAuthenticated(true)
    return { ok: true }
  }

  async function logout() {
    const storedSessionId = sessionStorage.getItem(SESSION_STORAGE_KEY)
    if (storedSessionId) {
      await logoutRequest(storedSessionId)
    }
    sessionStorage.removeItem(SESSION_STORAGE_KEY)
    setIsAuthenticated(false)
    setBalanceVisible(false)
  }

  function toggleBalanceVisible() {
    setBalanceVisible((prev) => !prev)
  }

  function requireAuthHighlight() {
    setHighlightLogin(true)
    setTimeout(() => setHighlightLogin(false), HIGHLIGHT_DURATION_MS)
  }

  function appendMessage(message) {
    setMessages((prev) => [...prev, message])
  }

  function updateMessage(messageId, updater) {
    setMessages((prev) => prev.map((m) => (m.id === messageId ? updater(m) : m)))
  }

  function toggleChat() {
    setChatOpen((prev) => {
      const next = !prev
      if (next) setChatHasUnread(false)
      return next
    })
  }

  function openChat() {
    setChatOpen(true)
    setChatHasUnread(false)
  }

  function closeChat() {
    setChatOpen(false)
  }

  function withTypingDelay(fn, delay = 700) {
    setIsTyping(true)
    setTimeout(() => {
      fn()
      setIsTyping(false)
      setChatOpen((open) => {
        if (!open) setChatHasUnread(true)
        return open
      })
    }, delay)
  }

  async function sendMessage(text) {
    appendMessage(textMessage('user', text))
    setDraft('')

    setIsTyping(true)
    const sessionId = sessionStorage.getItem(SESSION_STORAGE_KEY)
    const result = await simulateAssistantReply(text, { sessionId })
    appendMessage(result.message)
    setActiveAgent(result.nextActiveAgent)
    if (result.requiresAuth) requireAuthHighlight()
    setIsTyping(false)
    setChatOpen((open) => {
      if (!open) setChatHasUnread(true)
      return open
    })
  }

  function confirmTransfer(messageId) {
    updateMessage(messageId, (m) => ({ ...m, data: { ...m.data, locked: true } }))
    withTypingDelay(() => {
      appendMessage(buildOtpRequestMessage())
    })
  }

  function cancelTransfer(messageId) {
    updateMessage(messageId, (m) => ({ ...m, data: { ...m.data, locked: true } }))
    appendMessage(buildCancelledMessage())
    setActiveAgent('assistant')
  }

  function submitOtp(messageId, code) {
    const target = messages.find((m) => m.id === messageId)
    if (!target) return
    const attemptsLeft =
      typeof target.data.attemptsLeft === 'number' ? target.data.attemptsLeft : OTP_MAX_ATTEMPTS

    if (code === DEMO_OTP_CODE) {
      updateMessage(messageId, (m) => ({ ...m, data: { ...m.data, locked: true, error: null } }))
      withTypingDelay(() => {
        appendMessage(buildTransferResultMessage('success'))
        setActiveAgent('assistant')
      }, 500)
      return
    }

    const remaining = attemptsLeft - 1
    updateMessage(messageId, (m) => ({
      ...m,
      data: {
        ...m.data,
        attemptsLeft: remaining,
        error:
          remaining > 0
            ? `Code incorrect. Il vous reste ${remaining} tentative(s).`
            : 'Code incorrect.',
        locked: remaining <= 0,
      },
    }))

    if (remaining <= 0) {
      withTypingDelay(() => {
        appendMessage(buildTransferResultMessage('failed', 'invalid_otp'))
        setActiveAgent('assistant')
      }, 500)
    }
  }

  function resendOtp(messageId) {
    updateMessage(messageId, (m) => ({
      ...m,
      data: { ...m.data, resendCount: (m.data.resendCount ?? 0) + 1, error: null },
    }))
  }

  const value = {
    // auth & session
    isAuthenticated,
    userName: mockUser.display_name,
    highlightLogin,
    login,
    logout,
    // compte
    account: mockAccount,
    balanceVisible,
    onToggleBalance: toggleBalanceVisible,
    // transactions
    transactions: mockTransactions,
    // assistant / chat
    chatOpen,
    chatHasUnread,
    toggleChat,
    openChat,
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
  }

  return <BankingAppContext.Provider value={value}>{children}</BankingAppContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components -- pattern standard provider+hook
export function useBankingApp() {
  const ctx = useContext(BankingAppContext)
  if (!ctx) {
    throw new Error('useBankingApp doit etre utilise a l’interieur de <BankingAppProvider>')
  }
  return ctx
}
