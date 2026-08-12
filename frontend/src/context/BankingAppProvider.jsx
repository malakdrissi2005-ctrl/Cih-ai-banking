import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { mockUser, mockAccount } from '../data/mockAccount.js'
import { mockTransactions } from '../data/mockTransactions.js'
import { publicSuggestions, authenticatedSuggestions } from '../data/chatSuggestions.js'
import {
  simulateAssistantReply,
  buildOtpRequestMessage,
  buildTransferResultMessage,
  buildCancelledMessage,
  buildInitializingMessage,
  textMessage,
  DEMO_OTP_CODE,
  OTP_MAX_ATTEMPTS,
  INITIALIZATION_DISPLAY_DURATION_MS,
} from '../data/chatSimulation.js'
import {
  loginRequest,
  checkSessionRequest,
  logoutRequest,
  fetchBankingOverview,
} from '../data/authApi.js'

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

  // --- Donnees bancaires REELLES du client authentifie (GET /api/banking/overview)
  // Source unique du tableau de bord ET du chatbot : avant cette integration, le
  // tableau de bord affichait mockAccount (15 420,50 MAD) pendant que le chatbot
  // lisait demo_bancaire.db (106 318,39 MAD). Les deux se contredisaient a l'ecran.
  const [overview, setOverview] = useState(null)
  const [overviewStatus, setOverviewStatus] = useState('idle') // idle|loading|ready|error
  const [overviewError, setOverviewError] = useState(null) // 'unauthorized'|'network'|'invalid'
  const [selectedAccountIndex, setSelectedAccountIndex] = useState(0)

  // Jeton de course : chaque chargement recoit un numero. Une reponse dont le
  // numero n'est plus le courant est ignoree. Empeche qu'une requete lente,
  // partie avant une deconnexion ou une autre connexion, ne vienne peupler
  // l'etat avec les donnees du client precedent.
  const overviewRequestRef = useRef(0)

  // --- Assistant IA : un seul etat de conversation pour les deux boutons d'acces ---
  const [chatOpen, setChatOpen] = useState(false)
  const [chatHasUnread, setChatHasUnread] = useState(false)
  const [messages, setMessages] = useState([])
  const [isTyping, setIsTyping] = useState(false)
  const [activeAgent, setActiveAgent] = useState('assistant')
  const [draft, setDraft] = useState('')
  // Purement UX, jamais lie a un etat reel (pas de backend/Ollama) : indique
  // si le message d'initialisation a deja ete affiche pour cette session de
  // navigation (reinitialise a chaque rechargement de page, comme le reste
  // de l'etat de conversation ci-dessus) - voir sendMessage.
  const [initializationShown, setInitializationShown] = useState(false)

  const suggestions = isAuthenticated ? authenticatedSuggestions : publicSuggestions

  // Au demarrage : si un session_id existe encore (onglet rouvert/rafraichi), verifie sa
  // validite aupres du Backend avant de considerer l'utilisateur comme authentifie.
  /** Efface TOUTE donnee bancaire personnelle de l'etat partage.
   *
   * Appelee a la deconnexion et avant chaque nouveau chargement : garantit
   * qu'un utilisateur ne peut jamais voir, meme brievement, les donnees du
   * precedent. Incremente aussi le jeton de course, ce qui neutralise toute
   * requete encore en vol.
   */
  // `useCallback` sans dependance : ces deux fonctions ne referencent que des
  // setters d'etat et une ref, tous stables. Elles peuvent donc figurer sans
  // risque dans le tableau de dependances de l'effet de restauration ci-dessous,
  // qui ne doit s'executer qu'une seule fois, au montage.
  const clearOverview = useCallback(() => {
    overviewRequestRef.current += 1
    setOverview(null)
    setOverviewStatus('idle')
    setOverviewError(null)
    setSelectedAccountIndex(0)
  }, [])

  const loadOverview = useCallback(async function loadOverview(sessionId) {
    clearOverview()
    const requestId = overviewRequestRef.current
    setOverviewStatus('loading')

    const result = await fetchBankingOverview(sessionId)

    // Reponse obsolete (deconnexion ou autre connexion entre-temps) : ignoree.
    if (requestId !== overviewRequestRef.current) return

    if (result.ok) {
      setOverview(result.overview)
      setOverviewStatus('ready')
      setOverviewError(null)
      return
    }

    // Jamais de repli silencieux sur des donnees simulees : on affiche l'erreur.
    setOverview(null)
    setOverviewStatus('error')
    setOverviewError(result.reason)

    // Session expiree ou invalide : on repasse l'application en etat deconnecte
    // plutot que de laisser un tableau de bord authentifie sans donnees.
    if (result.reason === 'unauthorized') {
      sessionStorage.removeItem(SESSION_STORAGE_KEY)
      setIsAuthenticated(false)
    }
  }, [clearOverview])

  /** Reessaie le chargement avec la session courante (bouton « Reessayer »). */
  async function retryOverview() {
    const storedSessionId = sessionStorage.getItem(SESSION_STORAGE_KEY)
    if (!storedSessionId) return
    await loadOverview(storedSessionId)
  }

  useEffect(() => {
    const storedSessionId = sessionStorage.getItem(SESSION_STORAGE_KEY)
    if (!storedSessionId) return

    checkSessionRequest(storedSessionId).then((result) => {
      if (result.ok) {
        setIsAuthenticated(true)
        // Session restauree (onglet rouvert) : les donnees bancaires doivent
        // etre rechargees, elles ne survivent volontairement pas au rafraichissement.
        loadOverview(storedSessionId)
      } else {
        sessionStorage.removeItem(SESSION_STORAGE_KEY)
      }
    })
  }, [loadOverview])

  async function login(username, password) {
    const result = await loginRequest(username, password)
    if (!result.ok) {
      return { ok: false }
    }
    sessionStorage.setItem(SESSION_STORAGE_KEY, result.sessionId)
    setIsAuthenticated(true)
    await loadOverview(result.sessionId)
    return { ok: true }
  }

  async function logout() {
    const storedSessionId = sessionStorage.getItem(SESSION_STORAGE_KEY)
    // Neutralise immediatement toute requete en vol AVANT l'appel reseau.
    clearOverview()
    if (storedSessionId) {
      await logoutRequest(storedSessionId)
    }
    sessionStorage.removeItem(SESSION_STORAGE_KEY)
    setIsAuthenticated(false)
    setBalanceVisible(false)
    // La conversation contient des donnees personnelles (soldes, operations).
    setMessages([])
    setActiveAgent('assistant')
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

    // Premier message de la session de navigation uniquement (voir
    // `initializationShown` ci-dessus) : affiche brievement un statut
    // d'initialisation avant l'indicateur de saisie habituel - purement
    // cosmetique, aucune dependance a l'etat reel du Backend/Ollama. Les
    // messages suivants passent directement a l'indicateur de saisie.
    if (!initializationShown) {
      appendMessage(buildInitializingMessage())
      await new Promise((resolve) => setTimeout(resolve, INITIALIZATION_DISPLAY_DURATION_MS))
      setInitializationShown(true)
    }

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

  // --- Derivation du compte selectionne et des transactions affichees -------
  // Une seule source : `overview`. Les donnees simulees ne servent plus QUE
  // avant authentification (ecran public/decoratif) — jamais en repli d'une
  // requete echouee, ce qui reintroduirait la contradiction d'affichage.
  const accounts = overview?.accounts ?? []
  const selectedAccount = accounts[selectedAccountIndex] ?? accounts[0] ?? null

  // Le compte affiche par la carte principale, au format attendu par les
  // composants existants (`AccountCard`, `MobileDashboard`, `DesktopDashboard`).
  const account = isAuthenticated && selectedAccount
    ? {
        type: selectedAccount.accountType,
        // Reference CLIENT masquee, jamais la cle technique `id_compte`.
        number: selectedAccount.maskedAccountNumber,
        balance: selectedAccount.balance,
        currency: selectedAccount.currency,
      }
    : mockAccount

  // Le contrat de `RecentTransactions` (voir son en-tete) : `amount` est une
  // chaine decimale NON SIGNEE, le sens est porte exclusivement par `direction`,
  // avec les valeurs 'in' / 'out'. Le backend, lui, parle 'credit' / 'debit' :
  // la traduction se fait ici, une seule fois. Signer le montant ici afficherait
  // un double signe ("--1305.00"), le composant ajoutant deja le sien.
  const transactions = isAuthenticated && overview
    ? overview.recentTransactions.map((tx, index) => ({
        id: `${tx.date}-${index}`,
        label: tx.label,
        category: tx.category,
        date: tx.date,
        amount: tx.amount,
        direction: tx.direction === 'credit' ? 'in' : 'out',
        currency: tx.currency,
      }))
    : mockTransactions

  const value = {
    // auth & session
    isAuthenticated,
    // Une fois authentifie, le nom vient de la base — jamais de `mockUser`.
    // Tant que l'overview n'est pas arrive, la salutation reste vide plutot que
    // d'afficher le nom d'un client de demonstration a un vrai utilisateur.
    userName: isAuthenticated ? overview?.fullName ?? '' : mockUser.display_name,
    highlightLogin,
    login,
    logout,
    // compte (selectionne)
    account,
    balanceVisible,
    onToggleBalance: toggleBalanceVisible,
    // --- Donnees bancaires reelles (source unique, partagee mobile/desktop) ---
    overview,
    overviewStatus,
    overviewError,
    retryOverview,
    accounts,
    selectedAccount,
    selectedAccountIndex,
    selectAccount: setSelectedAccountIndex,
    // Total TOUS COMPTES — distinct du solde du compte selectionne ci-dessus,
    // et identique a celui annonce par le chatbot.
    totalBalance: overview?.totalBalance ?? null,
    card: overview?.card ?? null,
    // transactions
    transactions,
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
