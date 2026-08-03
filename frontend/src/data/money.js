// Utilitaires de formatage monetaire.
//
// Regle du projet (voir CLAUDE.md §5 : "Montants : toujours Decimal en Python, jamais float ;
// toujours une chaine decimale en JSON, jamais un nombre"). JavaScript n'a pas de type Decimal
// natif, mais la meme discipline est appliquee cote frontend pour les donnees simulees : tous les
// montants sont stockes comme chaines decimales (ex. "15420.50"), jamais comme nombre flottant brut
// (15420.5). Ces fonctions centralisent la conversion necessaire uniquement au moment de l'affichage.

export function toNumber(value) {
  return typeof value === 'string' ? Number(value) : value
}

export function formatAmount(value) {
  return toNumber(value).toLocaleString('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function sumAmounts(values) {
  return values.reduce((total, value) => total + toNumber(value), 0)
}
