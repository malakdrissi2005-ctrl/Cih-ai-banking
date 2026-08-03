// Suggestions cliquables - de simples exemples, la saisie libre reste toujours possible (voir champ ChatWindow).
export default function QuickSuggestions({ suggestions, onPick, disabled = false }) {
  if (!suggestions?.length) return null

  return (
    <div className="flex flex-wrap gap-2 px-4 py-2 bg-cih-surface border-t border-gray-100">
      {suggestions.map((s) => (
        <button
          key={s}
          disabled={disabled}
          onClick={() => onPick(s)}
          className="text-xs text-cih-blue bg-cih-blue-light hover:bg-cih-blue hover:text-white
                     rounded-full px-3 py-1.5 transition duration-200 disabled:opacity-50"
        >
          {s}
        </button>
      ))}
    </div>
  )
}
