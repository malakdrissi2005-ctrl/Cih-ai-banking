import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BankingAppProvider, useBankingApp } from './BankingAppProvider.jsx'

const SESSION_STORAGE_KEY = 'cih_session_id'

function renderBankingApp() {
  return renderHook(() => useBankingApp(), {
    wrapper: ({ children }) => <BankingAppProvider>{children}</BankingAppProvider>,
  })
}

beforeEach(() => {
  sessionStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('login', () => {
  it('authentifie et conserve le session_id apres une connexion reussie', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ session_id: 'session-abc', expires_at: '2026-01-01T00:00:00Z' }),
      }),
    )

    const { result } = renderBankingApp()
    expect(result.current.isAuthenticated).toBe(false)

    let loginResult
    await act(async () => {
      loginResult = await result.current.login('demo', 'Demo1234!')
    })

    expect(loginResult.ok).toBe(true)
    expect(result.current.isAuthenticated).toBe(true)
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBe('session-abc')
  })

  it('refuse des identifiants incorrects sans authentifier ni stocker de session', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))

    const { result } = renderBankingApp()

    let loginResult
    await act(async () => {
      loginResult = await result.current.login('demo', 'mauvais-mot-de-passe')
    })

    expect(loginResult.ok).toBe(false)
    expect(result.current.isAuthenticated).toBe(false)
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
  })
})

describe('verification de session au demarrage', () => {
  it('restaure automatiquement une session valide', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, 'session-existante-valide')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ authenticated: true, username: 'demo', expires_at: '2026-01-01T00:00:00Z' }),
      }),
    )

    const { result } = renderBankingApp()

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true))
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBe('session-existante-valide')
  })

  it('supprime une session expiree ou invalide et reste non authentifie', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, 'session-expiree')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))

    const { result } = renderBankingApp()

    await waitFor(() => expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull())
    expect(result.current.isAuthenticated).toBe(false)
  })
})

describe('sendMessage - statut d’initialisation (UX premier message, purement frontend)', () => {
  function stubChatFetch(response) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => response }))
  }

  it(
    'affiche le statut d’initialisation avant la réponse réelle, au tout premier message de la session',
    async () => {
      stubChatFetch({ intent: 'faq_generale', requires_auth: false, response: 'Réponse réelle de l’assistant.' })

      const { result } = renderBankingApp()

      await act(async () => {
        await result.current.sendMessage('Quels documents pour ouvrir un compte ?')
      })

      const contents = result.current.messages.map((m) => m.content)
      expect(contents[0]).toBe('Quels documents pour ouvrir un compte ?')
      expect(contents[1]).toContain("en cours d'initialisation")
      expect(contents[2]).toBe('Réponse réelle de l’assistant.')
      expect(result.current.messages).toHaveLength(3)
    },
    10000,
  )

  it(
    'n’affiche le statut d’initialisation qu’une seule fois par session : les messages suivants passent directement à la réponse',
    async () => {
      stubChatFetch({ intent: 'faq_generale', requires_auth: false, response: 'Réponse réelle de l’assistant.' })

      const { result } = renderBankingApp()

      await act(async () => {
        await result.current.sendMessage('Première question')
      })
      await act(async () => {
        await result.current.sendMessage('Deuxième question')
      })

      const initializingCount = result.current.messages.filter((m) =>
        m.content?.includes("en cours d'initialisation"),
      ).length
      expect(initializingCount).toBe(1)
      // user1, init, reponse1, user2, reponse2 - jamais de 2e statut d'initialisation.
      expect(result.current.messages).toHaveLength(5)
      expect(result.current.messages[3].content).toBe('Deuxième question')
      expect(result.current.messages[4].content).toBe('Réponse réelle de l’assistant.')
    },
    10000,
  )
})

describe('logout', () => {
  it('appelle /api/auth/logout puis supprime la session locale', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, 'session-a-fermer')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderBankingApp()

    await act(async () => {
      await result.current.logout()
    })

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/auth/logout'),
      expect.objectContaining({ headers: { Authorization: 'Bearer session-a-fermer' } }),
    )
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
    expect(result.current.isAuthenticated).toBe(false)
  })
})
