import Navbar from '../Navbar.jsx'
import LoginForm from '../LoginForm.jsx'
import PublicServicesGrid from '../PublicServicesGrid.jsx'
import { useBankingApp } from '../../context/BankingAppProvider.jsx'

// Ecran de connexion mobile - voir DocsContext/05_interface_frontend.md §10.
// Lit l'etat partage directement depuis BankingAppProvider (highlightLogin, login) afin que la
// mise en evidence du formulaire reste strictement synchronisee avec la vue desktop.
export default function MobileLoginView() {
  const { highlightLogin, login } = useBankingApp()

  return (
    <div className="min-h-full bg-[linear-gradient(160deg,#F26522_0%,#D9434B_35%,#1E3A6E_70%,#2E1A47_100%)] flex flex-col pb-28">
      <Navbar authenticated={false} />
      <div className="px-4 mt-6">
        <h1 className="text-3xl font-bold text-white mb-4">Bienvenue</h1>
        <LoginForm highlight={highlightLogin} onSubmit={login} />
      </div>
      <PublicServicesGrid columns={2} />

      <p className="text-center text-[11px] text-white/50 mt-6">Prototype académique non officiel</p>
    </div>
  )
}
