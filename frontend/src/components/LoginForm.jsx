import { useState } from 'react'
import { User, Lock } from 'lucide-react'

// Panneau d'authentification sombre semi-transparent (auth-panel) - voir
// DocsContext/05_interface_frontend.md §6/§10/§11. Reutilise a l'identique par MobileLoginView
// et DesktopLoginView ; le titre "Bienvenue", la mise en page exterieure et la mention academique
// restent la responsabilite de chaque vue appelante (largeurs differentes mobile/desktop).
// Props: highlight (boolean), onSubmit(identifiant, motDePasse, remember)
// Le retrait de la surbrillance (timer 2,5s) est pilote par le contexte partage (BankingAppProvider).
export default function LoginForm({ highlight = false, onSubmit }) {
  const [identifiant, setIdentifiant] = useState('')
  const [motDePasse, setMotDePasse] = useState('')
  const [remember, setRemember] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [loginError, setLoginError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!identifiant.trim() || !motDePasse.trim()) {
      setLoginError('Veuillez renseigner votre identifiant et votre mot de passe (valeurs de démonstration).')
      return
    }
    setLoginError(null)
    setIsSubmitting(true)
    const result = await onSubmit?.(identifiant, motDePasse, remember)
    setIsSubmitting(false)
    if (result && result.ok === false) {
      setLoginError('Identifiant ou mot de passe incorrect.')
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className={`bg-black/45 backdrop-blur-md border border-white/10 rounded-2xl shadow-md p-6 space-y-5 transition ${
        highlight ? 'ring-2 ring-cih-orange animate-pulse' : ''
      }`}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-white/70">Authentification</p>

      <div>
        <label className="block text-xs font-medium text-white/60 mb-1">Identifiant</label>
        <div className="flex items-center gap-2 rounded-xl border border-white/15 bg-white/10 px-3 py-2.5">
          <User className="w-4 h-4 text-white/60 shrink-0" />
          <input
            type="text"
            placeholder="Identifiant client (démo : Client Démo)"
            value={identifiant}
            onChange={(e) => {
              setIdentifiant(e.target.value)
              setLoginError(null)
            }}
            className="w-full bg-transparent text-sm text-white placeholder:text-white/40 focus:outline-none"
          />
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs font-medium text-white/60">Mot de passe</label>
          <a href="#" className="text-xs text-cih-orange font-medium" onClick={(e) => e.preventDefault()}>
            Oublié ?
          </a>
        </div>
        <div className="flex items-center gap-2 rounded-xl border border-white/15 bg-white/10 px-3 py-2.5">
          <Lock className="w-4 h-4 text-white/60 shrink-0" />
          <input
            type="password"
            placeholder="Mot de passe de démonstration"
            value={motDePasse}
            onChange={(e) => {
              setMotDePasse(e.target.value)
              setLoginError(null)
            }}
            className="w-full bg-transparent text-sm text-white placeholder:text-white/40 focus:outline-none"
          />
        </div>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-sm text-white/80">Se souvenir de moi</span>
        <button
          type="button"
          role="switch"
          aria-checked={remember}
          onClick={() => setRemember(!remember)}
          className={`w-10 h-6 rounded-full transition ${remember ? 'bg-cih-orange' : 'bg-white/20'}`}
        >
          <span
            className={`block w-4 h-4 bg-white rounded-full shadow transform transition ${
              remember ? 'translate-x-5' : 'translate-x-1'
            }`}
          />
        </button>
      </div>

      {loginError && <p className="text-xs text-orange-200">{loginError}</p>}

      <button
        type="submit"
        disabled={isSubmitting}
        className="w-full bg-cih-orange hover:bg-cih-orange-dark text-white font-semibold
                   py-3 rounded-xl transition duration-200 disabled:opacity-60"
      >
        {isSubmitting ? 'Connexion…' : 'Connexion'}
      </button>
    </form>
  )
}
