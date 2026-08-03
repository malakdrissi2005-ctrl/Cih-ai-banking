import { Menu, ShieldCheck, Landmark, Bell, LogOut } from 'lucide-react'

// Variante non-authentifiee (ecran de connexion) : wordmark "CIH ▶▶ BANK" inspire de l'identite
// visuelle CIH Bank. Exception explicitement confirmee par le porteur du projet a la regle
// generale "aucun logo officiel" (voir echange de validation) - une mention "Prototype academique
// non officiel" est affichee en bas de chaque ecran de connexion en consequence.
// Props : authenticated (bool), onLogout (utilise uniquement en variante authentifiee)
export default function Navbar({ authenticated = false, onLogout }) {
  return (
    <header
      className={`flex items-center justify-between px-4 pt-6 pb-4 ${
        !authenticated ? 'border-b-2 border-cih-orange' : ''
      }`}
    >
      <button aria-label="Ouvrir le menu" className="text-cih-blue">
        <Menu className="w-6 h-6" />
      </button>

      {authenticated ? (
        <div className="flex items-center gap-2 font-bold tracking-wide text-gray-900">
          <Landmark className="w-5 h-5 text-cih-blue" />
          <span className="text-sm">CIH AI Banking — Démonstration</span>
        </div>
      ) : (
        <div className="flex items-center gap-0.5 font-bold tracking-wide text-white" aria-label="CIH BANK">
          <span className="text-sm">CIH</span>
          <span className="relative w-4 h-4 shrink-0 mx-0.5" aria-hidden="true">
            <span
              className="absolute left-0 top-0 w-2.5 h-2.5 bg-cih-orange"
              style={{ clipPath: 'polygon(0 0, 100% 50%, 0 100%)' }}
            />
            <span
              className="absolute right-0 bottom-0 w-2.5 h-2.5 bg-cih-blue"
              style={{ clipPath: 'polygon(0 0, 100% 50%, 0 100%)' }}
            />
          </span>
          <span className="text-sm">BANK</span>
        </div>
      )}

      {authenticated ? (
        <div className="flex items-center gap-3">
          <button aria-label="Notifications" className="text-cih-blue">
            <Bell className="w-5 h-5" />
          </button>
          <button aria-label="Se déconnecter" onClick={onLogout} className="text-cih-blue">
            <LogOut className="w-5 h-5" />
          </button>
        </div>
      ) : (
        <ShieldCheck className="w-6 h-6 text-cih-blue" aria-hidden="true" />
      )}
    </header>
  )
}
