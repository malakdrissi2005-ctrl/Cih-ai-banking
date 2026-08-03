// Transactions fictives - prototype academique.
//
// Le montant est toujours une chaine decimale non signee (ex. "342.50", jamais -342.5 ou 342.5) ;
// le sens (credit/debit) est porte exclusivement par `direction`, jamais par le signe du montant.

export const mockTransactions = [
  {
    id: 't1',
    label: 'Salaire — Société Fictive SARL',
    date: '2026-07-24',
    amount: '8500.00',
    direction: 'in',
  },
  {
    id: 't2',
    label: 'Carrefour Market',
    date: '2026-07-23',
    amount: '342.50',
    direction: 'out',
  },
  {
    id: 't3',
    label: 'Facture Électricité',
    date: '2026-07-20',
    amount: '410.00',
    direction: 'out',
  },
  {
    id: 't4',
    label: 'Virement reçu — Amine T.',
    date: '2026-07-18',
    amount: '1200.00',
    direction: 'in',
  },
  {
    id: 't5',
    label: 'Abonnement Internet',
    date: '2026-07-15',
    amount: '199.00',
    direction: 'out',
  },
]
