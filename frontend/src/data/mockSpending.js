// Repartition fictive des depenses par categorie (donnees de demonstration uniquement).
// Les montants sont des chaines decimales - voir CLAUDE.md §5 et src/data/money.js.
// Les couleurs reprennent exactement les tokens du design system (cih-blue / cih-orange et leurs
// variantes), plus un gris neutre Tailwind pour la categorie "Autres".

export const mockSpendingCategories = [
  { label: 'Shopping', amount: '1245.00', percent: 30, color: '#005CA9' },
  { label: 'Alimentation', amount: '1037.50', percent: 25, color: '#F26522' },
  { label: 'Transport', amount: '830.00', percent: 20, color: '#00427A' },
  { label: 'Loisirs', amount: '622.50', percent: 15, color: '#D9530F' },
  { label: 'Autres', amount: '415.00', percent: 10, color: '#CBD5E1' },
]
