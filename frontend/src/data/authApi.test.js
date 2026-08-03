import { afterEach, describe, expect, it, vi } from 'vitest'
import { loginRequest, checkSessionRequest, logoutRequest } from './authApi.js'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('loginRequest', () => {
  it('retourne ok=true et le session_id en cas de succes', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ session_id: 'abc123', expires_at: '2026-01-01T00:00:00Z' }),
      }),
    )

    const result = await loginRequest('demo', 'Demo1234!')

    expect(result.ok).toBe(true)
    expect(result.sessionId).toBe('abc123')
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/auth/login'),
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('retourne ok=false en cas d’identifiants incorrects (401)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))

    const result = await loginRequest('demo', 'mauvais-mot-de-passe')

    expect(result.ok).toBe(false)
  })

  it('retourne ok=false si le reseau echoue', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))

    const result = await loginRequest('demo', 'Demo1234!')

    expect(result.ok).toBe(false)
  })
})

describe('checkSessionRequest', () => {
  it('retourne ok=true pour une session valide', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ authenticated: true, username: 'demo', expires_at: '2026-01-01T00:00:00Z' }),
      }),
    )

    const result = await checkSessionRequest('un-session-id-valide')

    expect(result.ok).toBe(true)
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/auth/session'),
      expect.objectContaining({ headers: { Authorization: 'Bearer un-session-id-valide' } }),
    )
  })

  it('retourne ok=false pour une session invalide ou expiree (401)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))

    const result = await checkSessionRequest('session-expiree-ou-invalide')

    expect(result.ok).toBe(false)
  })
})

describe('logoutRequest', () => {
  it('appelle POST /api/auth/logout avec le Bearer token', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))

    await logoutRequest('un-session-id')

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/auth/logout'),
      expect.objectContaining({
        method: 'POST',
        headers: { Authorization: 'Bearer un-session-id' },
      }),
    )
  })
})
