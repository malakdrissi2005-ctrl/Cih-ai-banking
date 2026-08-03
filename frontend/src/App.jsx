import { BankingAppProvider } from './context/BankingAppProvider.jsx'
import ResponsiveShowcase from './components/ResponsiveShowcase.jsx'
import ChatWidget from './components/chat/ChatWidget.jsx'

// Racine de l'application - voir DocsContext/05_interface_frontend.md §17/§18.
// BankingAppProvider fournit l'etat partage unique ; ResponsiveShowcase organise les vues
// mobile/desktop selon la largeur ; ChatWidget est monte une seule fois (instance unique).
export default function App() {
  return (
    <BankingAppProvider>
      <ResponsiveShowcase />
      <ChatWidget />
    </BankingAppProvider>
  )
}
