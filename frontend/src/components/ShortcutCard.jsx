export default function ShortcutCard({ icon: Icon, label, onClick }) {
  return (
    <button
      onClick={onClick}
      className="bg-white rounded-2xl border border-cih-orange-light shadow-md
                 p-5 flex flex-col items-center gap-2 hover:bg-cih-orange-light
                 transition duration-200 min-h-[92px]"
    >
      <Icon className="w-6 h-6 text-cih-orange shrink-0" />
      <span className="text-xs font-medium text-gray-700 text-center leading-snug">{label}</span>
    </button>
  )
}
