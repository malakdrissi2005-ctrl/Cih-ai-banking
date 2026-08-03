import { formatAmount } from '../../data/money.js'

// Graphique circulaire (donut) des depenses par categorie - SVG pur, sans dependance externe.
// Props: categories = [{ label, amount, percent, color }]
export default function SpendingChart({ categories }) {
  const size = 168
  const strokeWidth = 24
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius

  let cumulativePercent = 0

  return (
    <div className="rounded-2xl shadow-md bg-white p-5">
      <h2 className="text-sm font-semibold text-gray-900 mb-4">Dépenses par catégorie</h2>

      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="mx-auto -rotate-90"
        role="img"
        aria-label="Répartition des dépenses par catégorie"
      >
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#F1F5F9" strokeWidth={strokeWidth} />
        {categories.map((cat) => {
          const dash = (cat.percent / 100) * circumference
          const gap = circumference - dash
          const offset = -((cumulativePercent / 100) * circumference)
          cumulativePercent += cat.percent
          return (
            <circle
              key={cat.label}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={cat.color}
              strokeWidth={strokeWidth}
              strokeDasharray={`${dash} ${gap}`}
              strokeDashoffset={offset}
            />
          )
        })}
      </svg>

      <ul className="mt-4 space-y-2">
        {categories.map((cat) => (
          <li key={cat.label} className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-2 text-gray-600">
              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: cat.color }} />
              {cat.label}
            </span>
            <span className="font-medium text-gray-800">{formatAmount(cat.amount)} MAD</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
