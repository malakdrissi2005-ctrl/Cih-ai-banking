// Donnees 100% fictives - prototype academique (voir CLAUDE.md / DocsContext/05_interface_frontend.md §4)

export const mockUser = {
  customer_id: 'CUST-DEMO-001',
  display_name: 'Malak',
}

// Numero de compte et de carte volontairement masques et fictifs - ne reprennent jamais
// un numero visible sur une capture d'ecran ou une application reelle.
//
// Tous les montants sont stockes comme chaines decimales ("15420.50"), jamais comme nombre
// flottant brut (15420.5) - voir CLAUDE.md §5 et src/data/money.js pour le formatage a l'affichage.
export const mockAccount = {
  type: 'Compte chèques',
  number: 'DEMO-****-4821',
  balance: '15420.50',
}

export const mockCard = {
  holder: 'CLIENT DEMONSTRATION',
  maskedNumber: '•••• 4587',
  expiry: '09/29',
  label: 'Carte Démo',
}

// Plafonds de demonstration - alignes sur DAILY_TRANSFER_LIMIT / MONTHLY_TRANSFER_LIMIT (.env.example)
export const mockLimits = {
  dailyTransferLimit: '20000.00',
  monthlyTransferLimit: '50000.00',
  currency: 'MAD',
}
