// Client API d'authentification - POST /api/auth/login, GET /api/auth/session,
// POST /api/auth/logout. Session opaque (session_id), jamais un JWT - voir CLAUDE.md §4
// et backend/app/security/session_manager.py.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

export async function loginRequest(username, password) {
  try {
    const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      return { ok: false }
    }
    const data = await res.json()
    return { ok: true, sessionId: data.session_id, expiresAt: data.expires_at }
  } catch (err) {
    return { ok: false }
  }
}

export async function checkSessionRequest(sessionId) {
  try {
    const res = await fetch(`${API_BASE_URL}/api/auth/session`, {
      headers: { Authorization: `Bearer ${sessionId}` },
    })
    if (!res.ok) {
      return { ok: false }
    }
    const data = await res.json()
    return { ok: true, username: data.username, expiresAt: data.expires_at }
  } catch (err) {
    return { ok: false }
  }
}

export async function logoutRequest(sessionId) {
  try {
    await fetch(`${API_BASE_URL}/api/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${sessionId}` },
    })
  } catch (err) {
    // Deconnexion locale malgre tout, meme si l'appel reseau echoue.
  }
}
