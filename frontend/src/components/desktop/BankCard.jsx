import { CreditCard } from 'lucide-react'

// Carte bancaire fictive et compacte - aucune marque/logo reel represente.
// Props: card = { holder, maskedNumber, expiry, label }
export default function BankCard({ card }) {
  return (
    <div className="rounded-2xl shadow-md p-4 bg-gradient-to-br from-cih-blue to-cih-blue-dark text-white flex items-center gap-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/15">
        <CreditCard className="w-4 h-4 text-white" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] uppercase tracking-widest text-white/60">{card.label}</p>
        <p className="text-sm font-semibold tracking-[0.15em] truncate">{card.maskedNumber}</p>
      </div>
      <div className="text-right shrink-0">
        <p className="text-[10px] text-white/60">Exp.</p>
        <p className="text-xs font-medium">{card.expiry}</p>
      </div>
    </div>
  )
}
