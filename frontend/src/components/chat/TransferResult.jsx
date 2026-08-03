import { CheckCircle2, XCircle } from 'lucide-react'
import { formatAmount } from '../../data/money.js'

const REASON_LABELS = {
  invalid_otp: 'Code OTP incorrect après plusieurs tentatives.',
  otp_expired: 'Le code OTP a expiré.',
  user_cancelled: 'Opération annulée.',
}

// Props: data = { status: 'success' | 'failed', reason?, beneficiary, amount, currency, transactionId? }
// `amount` est une chaine decimale (ex. "1000.00"), jamais un nombre flottant.
export default function TransferResult({ data }) {
  const success = data.status === 'success'

  return (
    <div
      className={`rounded-xl p-3 text-sm space-y-1.5 min-w-[220px] ${
        success ? 'bg-green-50' : 'bg-red-50'
      }`}
    >
      <div className="flex items-center gap-2">
        {success ? (
          <CheckCircle2 className="w-5 h-5 text-green-600 shrink-0" />
        ) : (
          <XCircle className="w-5 h-5 text-red-600 shrink-0" />
        )}
        <span className={`font-semibold ${success ? 'text-green-700' : 'text-red-700'}`}>
          {success ? 'Virement effectué (démonstration)' : 'Virement échoué'}
        </span>
      </div>

      <div className="flex justify-between">
        <span className="text-gray-500">Bénéficiaire</span>
        <span className="font-medium">{data.beneficiary}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-gray-500">Montant</span>
        <span className="font-medium">
          {formatAmount(data.amount)} {data.currency}
        </span>
      </div>

      {success && data.transactionId && (
        <div className="flex justify-between">
          <span className="text-gray-500">Référence</span>
          <span className="font-mono text-xs">{data.transactionId}</span>
        </div>
      )}

      {!success && (
        <p className="text-xs text-red-600">
          {REASON_LABELS[data.reason] ?? 'Une erreur est survenue.'}
        </p>
      )}
    </div>
  )
}
