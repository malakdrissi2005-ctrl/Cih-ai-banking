import { ArrowDownLeft, ArrowUpRight } from 'lucide-react'
import { formatAmount } from '../../data/money.js'

// Liste de transactions fictives, partagee mobile/desktop (voir DocsContext/05_interface_frontend.md §17).
// Props: transactions = [{ id, label, date, amount, direction }]
// `amount` est une chaine decimale non signee (ex. "342.50") - le sens vient de `direction`.
// Pas de marge externe : l'espacement est gere par le conteneur parent (mobile ou desktop).
export default function RecentTransactions({ transactions }) {
  return (
    <div className="bg-white rounded-2xl shadow-md border border-gray-100 p-4">
      <h2 className="text-sm font-semibold text-gray-900 mb-3">Transactions récentes</h2>
      <ul className="divide-y divide-gray-100">
        {transactions.map((t) => (
          <li key={t.id} className="flex items-center gap-3 py-3">
            <div
              className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 ${
                t.direction === 'in' ? 'bg-green-50' : 'bg-cih-orange-light'
              }`}
            >
              {t.direction === 'in' ? (
                <ArrowDownLeft className="w-4 h-4 text-green-600" />
              ) : (
                <ArrowUpRight className="w-4 h-4 text-cih-orange" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate">{t.label}</p>
              <p className="text-[11px] text-gray-400">{t.date}</p>
            </div>
            <span
              className={`text-sm font-semibold shrink-0 ${
                t.direction === 'in' ? 'text-green-600' : 'text-cih-orange'
              }`}
            >
              {t.direction === 'in' ? '+' : '-'}
              {formatAmount(t.amount)} MAD
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
