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
