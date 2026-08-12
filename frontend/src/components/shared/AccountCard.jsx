import { Eye, EyeOff } from 'lucide-react'
import { formatAmount } from '../../data/money.js'

// Carte de compte et de solde - rendue a l'identique dans le telephone et le panneau desktop,
// a partir du meme etat partage (voir DocsContext/05_interface_frontend.md §17).
// Entierement controlee : aucun etat interne, `balanceVisible` vient de BankingAppProvider afin
// que le telephone et le desktop affichent/masquent le solde de maniere strictement synchronisee.
// `totalBalance` (optionnel, chaine decimale) : solde cumule de TOUS les comptes.
// Il n'est affiche que lorsqu'il differe du compte selectionne, c'est-a-dire pour
// un client multi-comptes. C'est ce total que le chatbot annonce lorsqu'on lui
// demande « mon solde » : l'afficher ici supprime la contradiction apparente
// entre le tableau de bord (un compte) et l'assistant (tous les comptes).
//
// Props: account = { type, number, balance }, balanceVisible (bool), onToggleBalance (),
//        totalBalance (string|null, optionnel)
export default function AccountCard({ account, balanceVisible, onToggleBalance, totalBalance = null }) {
  const afficherTotal = Boolean(totalBalance) && totalBalance !== account.balance

  return (
    <div className="mx-4 mt-4 bg-white rounded-2xl shadow-md border border-gray-100 p-5 text-center">
      <p className="text-xs text-gray-500">{account.type}</p>
      <p className="text-cih-blue font-medium text-sm mt-1">{account.number}</p>
      <p className="text-[11px] text-gray-400 mt-4">Solde</p>
      <div className="flex items-center justify-center gap-2 mt-1">
        <span className="text-xl font-bold text-gray-900 tracking-wide">
          {balanceVisible ? `${formatAmount(account.balance)} MAD` : '**** MAD'}
        </span>
        <button onClick={onToggleBalance} aria-label="Afficher/masquer le solde">
          {balanceVisible ? (
            <EyeOff className="w-5 h-5 text-cih-blue" />
          ) : (
            <Eye className="w-5 h-5 text-cih-blue" />
          )}
        </button>
      </div>

      {afficherTotal && (
        <div className="mt-4 border-t border-cih-orange-light pt-3">
          <p className="text-[11px] text-gray-400">Total tous comptes</p>
          <p className="text-sm font-semibold text-cih-blue mt-1">
            {balanceVisible ? `${formatAmount(totalBalance)} MAD` : '**** MAD'}
          </p>
        </div>
      )}
    </div>
  )
}
