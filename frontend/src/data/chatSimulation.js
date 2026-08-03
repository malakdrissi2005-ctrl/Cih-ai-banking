// Toutes les reponses de l'assistant proviennent desormais du vrai Backend Agent 1
// (POST /api/chat) : FAQ publique via ChromaDB, questions personnelles via banking.db
// pour un utilisateur authentifie (session_id transmis en en-tete Authorization), et
// message d'indisponibilite pour les virements/actions bancaires - voir CLAUDE.md.
// Agent 2/OTP restent hors perimetre : la logique de confirmation/OTP ci-dessous
// (buildOtpRequestMessage, confirmTransfer, submitOtp...) reste en place, prete a
// etre reconnectee lors de l'implementation reelle d'Agent 2.

import { mockBeneficiary, mockTransferDefaults, mockPhoneMasked } from './mockBeneficiary'

// Code de demonstration - reflete DEMO_OTP_CODE de .env.example. Jamais un vrai secret.
export const DEMO_OTP_CODE = '123456'
export const OTP_EXPIRATION_SECONDS = 180
export const OTP_MAX_ATTEMPTS = 3

// URL du Backend Agent 1 - configurable via VITE_API_BASE_URL (voir frontend/.env).
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

const ASSISTANT_UNAVAILABLE_MESSAGE = 'Le service de l’assistant est temporairement indisponible.'

async function fetchAgentReply(rawText, sessionId) {
  const headers = { 'Content-Type': 'application/json' }
  if (sessionId) {
    headers.Authorization = `Bearer ${sessionId}`
  }
  const res = await fetch(`${API_BASE_URL}/api/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ message: rawText }),
  })
  if (!res.ok) {
    throw new Error(`Backend /api/chat a répondu ${res.status}`)
  }
  return res.json()
}

let messageCounter = 0
function nextId() {
  messageCounter += 1
  return `sim-${Date.now()}-${messageCounter}`
}

export function textMessage(role, content) {
  return { id: nextId(), role, type: 'text', content }
}

/**
 * Reponse de l'assistant a un message utilisateur : delegue integralement au Backend
 * Agent 1. `sessionId` (session_id opaque, ou undefined si non connecte) est transmis
 * en en-tete Authorization ; le Backend determine seul si la question est publique,
 * personnelle (nécessitant une session valide) ou une demande indisponible.
 * Retourne { message, nextActiveAgent, requiresAuth }.
 */
export async function simulateAssistantReply(rawText, { sessionId } = {}) {
  try {
    const data = await fetchAgentReply(rawText, sessionId)
    return {
      message: textMessage('assistant', data.response),
      nextActiveAgent: 'assistant',
      requiresAuth: Boolean(data.requires_auth),
    }
  } catch (err) {
    return {
      message: textMessage('assistant', ASSISTANT_UNAVAILABLE_MESSAGE),
      nextActiveAgent: 'assistant',
      requiresAuth: false,
    }
  }
}

export function buildOtpRequestMessage() {
  return {
    id: nextId(),
    role: 'assistant',
    type: 'otp_request',
    data: {
      expiresIn: OTP_EXPIRATION_SECONDS,
      phoneMasked: mockPhoneMasked,
    },
  }
}

export function buildTransferResultMessage(status, reason) {
  return {
    id: nextId(),
    role: 'assistant',
    type: 'transfer_result',
    data: {
      status,
      reason: reason ?? null,
      beneficiary: mockBeneficiary.display_name,
      amount: mockTransferDefaults.amount,
      currency: mockTransferDefaults.currency,
      transactionId:
        status === 'success' ? `TX-DEMO-${Date.now().toString().slice(-8)}` : null,
    },
  }
}

export function buildCancelledMessage() {
  return textMessage('assistant', 'Virement annulé à votre demande. Aucune opération n’a été exécutée.')
}
