export default function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 bg-white border border-gray-100 rounded-2xl px-4 py-3 w-fit shadow-sm">
      <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce [animation-delay:-0.3s]" />
      <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce [animation-delay:-0.15s]" />
      <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" />
    </div>
  )
}
