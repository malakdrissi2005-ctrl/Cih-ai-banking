import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildInitializingMessage, simulateAssistantReply } from './chatSimulation.js'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('simulateAssistantReply - delegation integrale au Backend Agent 1', () => {
  it('interroge le Backend /api/chat sans en-tete Authorization quand aucune session', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          intent: 'faq_generale',
          requires_auth: false,
          response: 'Réponse FAQ réelle du Backend.',
        }),
      }),
    )

    const result = await simulateAssistantReply('Quels documents pour ouvrir un compte ?', {})

    const [, options] = fetch.mock.calls[0]
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/chat'), expect.any(Object))
    expect(options.headers.Authorization).toBeUndefined()
    expect(result.message.content).toBe('Réponse FAQ réelle du Backend.')
    expect(result.requiresAuth).toBe(false)
  })

  it('transmet le session_id en en-tete Authorization quand une session existe', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          intent: 'personal_data',
          requires_auth: false,
          response: 'Le total de vos comptes est de 45730.50 MAD.',
        }),
      }),
    )

    const result = await simulateAssistantReply('Combien me reste-t-il au total ?', {
      sessionId: 'un-session-id-valide',
    })

    const [, options] = fetch.mock.calls[0]
    expect(options.headers.Authorization).toBe('Bearer un-session-id-valide')
    expect(result.message.content).toBe('Le total de vos comptes est de 45730.50 MAD.')
    expect(result.requiresAuth).toBe(false)
  })

  it('relaie requires_auth=true pour une question personnelle sans session valide', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          intent: 'personal_data',
          requires_auth: true,
          response: 'Pour consulter vos informations personnelles, vous devez d’abord vous connecter.',
        }),
      }),
    )

    const result = await simulateAssistantReply('Quel est mon solde ?', {})

    expect(result.requiresAuth).toBe(true)
  })

  it('affiche un message d’indisponibilite si le Backend est injoignable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))

    const result = await simulateAssistantReply('Quels documents pour ouvrir un compte ?', {})

    expect(result.message.content).toBe('Le service de l’assistant est temporairement indisponible.')
    expect(result.requiresAuth).toBe(false)
  })
})

describe('buildInitializingMessage - statut UX (aucune dependance Backend/Ollama)', () => {
  it('produit un message texte assistant standard, meme forme que les autres messages assistant', () => {
    const message = buildInitializingMessage()

    expect(message.role).toBe('assistant')
    expect(message.type).toBe('text')
    expect(message.content).toContain("en cours d'initialisation")
  })
})
