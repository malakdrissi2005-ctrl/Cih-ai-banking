import { formatAmount } from '../../data/money.js'

// Props: data = { beneficiary, amount, account? }, onConfirm(), onCancel() - voir 05_interface_frontend.md §5.5/§6.2
// `amount` est une chaine decimale (ex. "1000.00"), jamais un nombre flottant.
export default function TransferConfirmationCard({ data, onConfirm, onCancel }) {
  const locked = data.locked

  return (
    <div className="bg-cih-blue-light rounded-xl p-3 text-sm space-y-1.5 min-w-[220px]">
      <div className="flex justify-between">
        <span className="text-gray-500">Bénéficiaire</span>
        <span className="font-medium">{data.beneficiary}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-gray-500">Montant</span>
        <span className="font-bold text-cih-blue">
          {formatAmount(data.amount)} {data.currency}
        </span>
      </div>
      {!locked && (
        <div className="flex gap-2 pt-2">
          <button
            onClick={onConfirm}
            className="flex-1 bg-cih-orange text-white rounded-lg py-1.5 font-medium hover:bg-cih-orange-dark transition"
          >
            Confirmer
          </button>
          <button
            onClick={onCancel}
            className="flex-1 bg-white border border-gray-200 rounded-lg py-1.5 text-gray-600 hover:bg-gray-50 transition"
          >
            Annuler
          </button>
        </div>
      )}
      {locked && <p className="text-[11px] text-gray-500 pt-1">Demande traitée.</p>}
    </div>
  )
}
