import { Home, ArrowLeftRight, CreditCard, Headphones } from 'lucide-react'

// Navigation inferieure mobile - voir DocsContext/05_interface_frontend.md §12.6 : Accueil,
// Virements, Cartes, Assistance. Navigation demonstrative (pas de routage reel en Phase 1) ;
// l'ouverture de l'assistant se fait via le bouton Assistant IA dedie (ChatFab), pas depuis ici.
// Props: fixed (true = ancree en bas du vrai viewport ; false = flux normal, apercu telephone)
export default function BottomNav({ fixed = true }) {
  const items = [
    { icon: Home, label: 'Accueil', active: true },
    { icon: ArrowLeftRight, label: 'Virements' },
    { icon: CreditCard, label: 'Cartes' },
    { icon: Headphones, label: 'Assistance' },
  ]

  return (
    <nav
      className={`${fixed ? 'fixed inset-x-0 bottom-0 z-40' : 'relative'} flex items-center justify-around
                 border-t border-gray-100 bg-white px-1 py-2`}
    >
      {items.map((item) => (
        <div
          key={item.label}
          className={`flex flex-col items-center gap-1 rounded-xl px-3 py-1.5 text-[10px] font-medium ${
            item.active ? 'text-cih-blue' : 'text-gray-400'
          }`}
        >
          <item.icon className="w-5 h-5" />
          {item.label}
        </div>
      ))}
    </nav>
  )
}
