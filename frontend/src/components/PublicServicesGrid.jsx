import { Building2, ShieldCheck, MapPin, Handshake } from 'lucide-react'
import ServiceCard from './ServiceCard.jsx'

const publicServices = [
  { icon: Building2, label: 'Portail Immobilier' },
  { icon: ShieldCheck, label: 'Assurances' },
  { icon: MapPin, label: 'Agences' },
  { icon: Handshake, label: 'Partenaires' },
]

// Props: columns = 2 (grille 2x2, mobile - voir 05_interface_frontend.md §10) | 4 (une rangee, desktop - §11)
export default function PublicServicesGrid({ columns = 2 }) {
  const gridClass = columns === 4 ? 'grid grid-cols-2 sm:grid-cols-4 gap-3' : 'grid grid-cols-2 gap-3'

  return (
    <div className="px-4 mt-6">
      <h2 className="text-sm font-semibold text-white/90 mb-3">Nos services</h2>
      <div className={gridClass}>
        {publicServices.map((s, i) => (
          <ServiceCard
            key={s.label}
            icon={s.icon}
            label={s.label}
            accent={i % 2 === 0 ? 'orange' : 'blue'}
          />
        ))}
      </div>
    </div>
  )
}
