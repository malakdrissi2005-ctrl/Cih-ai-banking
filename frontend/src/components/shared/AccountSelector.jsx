// Selecteur de compte - partage mobile/desktop (voir DocsContext/05_interface_frontend.md §17).
//
// Un client peut detenir PLUSIEURS comptes, dont plusieurs du meme type (le client
// de demonstration a un compte courant et deux carnets). Sans ce selecteur, le
// tableau de bord n'affichait que le premier compte et donnait l'impression que
// les autres n'existaient pas - une contradiction de plus avec le chatbot, qui
// lui les connait tous.
//
// Ne s'affiche pas pour un client mono-compte : rien a choisir.
// Le libelle distingue deux comptes de meme type par leur reference masquee,
// jamais par la cle technique `id_compte`, qui n'atteint pas le frontend.
//
// Props: accounts = [{ accountType, maskedAccountNumber }], selectedIndex (number),
//        onSelect (index => void)
export default function AccountSelector({ accounts, selectedIndex, onSelect }) {
  if (!accounts || accounts.length < 2) return null

  return (
    <div className="mx-4 mt-4 flex flex-wrap gap-2" role="group" aria-label="Choix du compte">
      {accounts.map((account, index) => {
        const actif = index === selectedIndex
        return (
          <button
            key={account.maskedAccountNumber}
            type="button"
            onClick={() => onSelect(index)}
            aria-pressed={actif}
            className={`rounded-2xl px-3 py-2 text-xs font-medium transition-colors ${
              actif
                ? 'bg-cih-orange text-white shadow-md'
                : 'bg-white text-cih-blue border border-gray-100 shadow-md hover:bg-cih-orange-light'
            }`}
          >
            <span className="capitalize">{account.accountType}</span>
            <span className={`ml-2 ${actif ? 'text-white/80' : 'text-gray-400'}`}>
              {account.maskedAccountNumber}
            </span>
          </button>
        )
      })}
    </div>
  )
}
