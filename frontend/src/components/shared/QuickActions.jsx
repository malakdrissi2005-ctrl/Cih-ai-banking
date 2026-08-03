import { CreditCard, ArrowLeftRight, Smartphone, Receipt, Home, Car } from 'lucide-react'
import ShortcutCard from '../ShortcutCard.jsx'

// Six raccourcis bancaires, partages mobile/desktop (memes actions, memes donnees) -
// voir DocsContext/05_interface_frontend.md §12.4 et §13.4.
// Le virement se declenche via l'assistant (widget de chat), pas directement depuis ce raccourci.
// Props: layout = "grid" (2 colonnes, mobile) | "row" (une rangee, desktop)
export default function QuickActions({ layout = 'grid' }) {
  const actions = [
    { icon: CreditCard, label: 'Mes cartes' },
    { icon: ArrowLeftRight, label: 'Effectuer un virement' },
    { icon: Smartphone, label: 'Effectuer une recharge' },
    { icon: Receipt, label: 'Payer mes factures' },
    { icon: Home, label: 'Financer mon projet' },
    { icon: Car, label: 'Payer vignette' },
  ]

  const layoutClass = layout === 'row' ? 'grid grid-cols-3 lg:grid-cols-6 gap-3' : 'grid grid-cols-2 gap-3'

  return (
    <div className={layoutClass}>
      {actions.map((a) => (
        <ShortcutCard key={a.label} icon={a.icon} label={a.label} />
      ))}
    </div>
  )
}
