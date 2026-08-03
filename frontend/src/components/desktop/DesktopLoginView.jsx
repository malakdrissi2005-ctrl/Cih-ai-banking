import Navbar from '../Navbar.jsx'
import LoginForm from '../LoginForm.jsx'
import PublicServicesGrid from '../PublicServicesGrid.jsx'
import { useBankingApp } from '../../context/BankingAppProvider.jsx'

// Ecran de connexion desktop agrandi - voir DocsContext/05_interface_frontend.md §11.
// Exactement le meme ecran que MobileLoginView (memes champs, meme ordre, meme etat partage via
// BankingAppProvider), simplement respace pour la largeur disponible : en-tete etire, titre
// agrandi, panneau centre de largeur confortable, services sur une seule rangee de quatre.
export default function DesktopLoginView() {
  const { highlightLogin, login } = useBankingApp()

  return (
    <div className="min-h-full bg-[linear-gradient(160deg,#F26522_0%,#D9434B_35%,#1E3A6E_70%,#2E1A47_100%)] flex flex-col">
      <Navbar authenticated={false} />

      <div className="flex-1 flex flex-col items-center justify-center px-10 py-10">
        <h1 className="text-4xl font-bold text-white mb-6">Bienvenue</h1>

        <div className="w-full max-w-md">
          <LoginForm highlight={highlightLogin} onSubmit={login} />
        </div>

        <div className="w-full max-w-2xl mt-10">
          <PublicServicesGrid columns={4} />
        </div>
      </div>

      <p className="text-center text-[11px] text-white/50 pb-6">Prototype académique non officiel</p>
    </div>
  )
}
