// Etat de chargement des donnees bancaires reelles - partage mobile/desktop
// (voir DocsContext/05_interface_frontend.md §17).
//
// REGLE DE SECURITE : quand GET /api/banking/overview echoue, l'application ne
// se rabat JAMAIS sur des donnees simulees. Elle le dit. Afficher un solde de
// demonstration a la place d'un solde reel indisponible serait le pire des deux
// mondes : l'utilisateur croirait lire son compte.
//
// Le message ne revele rien sur l'infrastructure (ni URL, ni code technique) et
// ne contient evidemment aucun identifiant de session.
//
// Props: status ('idle'|'loading'|'ready'|'error'), error ('unauthorized'|'network'|'invalid'),
//        onRetry (() => void)
const MESSAGES = {
  network: 'Vos données bancaires sont momentanément indisponibles.',
  invalid: 'Vos données bancaires n’ont pas pu être lues correctement.',
  unauthorized: 'Votre session a expiré. Veuillez vous reconnecter.',
}

export default function OverviewStatusBanner({ status, error, onRetry }) {
  if (status === 'idle' || status === 'ready') return null

  if (status === 'loading') {
    return (
      <div
        className="mx-4 mt-4 rounded-2xl border border-gray-100 bg-white p-4 shadow-md"
        role="status"
        aria-live="polite"
      >
        <div className="h-3 w-1/3 animate-pulse rounded-2xl bg-gray-100" />
        <div className="mt-3 h-6 w-2/3 animate-pulse rounded-2xl bg-gray-100" />
        <p className="mt-3 text-[11px] text-gray-400">Chargement de vos données bancaires…</p>
      </div>
    )
  }

  return (
    <div
      className="mx-4 mt-4 rounded-2xl border border-gray-100 bg-white p-4 shadow-md"
      role="alert"
    >
      <p className="text-sm font-medium text-gray-800">{MESSAGES[error] ?? MESSAGES.network}</p>
      <p className="mt-1 text-[11px] text-gray-400">
        Aucun montant n’est affiché tant que vos données réelles n’ont pas été reçues.
      </p>
      {error !== 'unauthorized' && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-2xl bg-cih-orange px-4 py-2 text-xs font-semibold text-white shadow-md"
        >
          Réessayer
        </button>
      )}
    </div>
  )
}
