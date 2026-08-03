export default function ServiceCard({ icon: Icon, label, onClick, accent = 'orange' }) {
  const circleColor = accent === 'orange' ? 'bg-cih-orange/85' : 'bg-cih-blue/70'

  return (
    <button
      onClick={onClick}
      className="flex flex-col items-center gap-2 rounded-2xl border border-white/10 bg-white/10
                 p-4 shadow-md backdrop-blur-sm transition duration-200 hover:bg-white/20"
    >
      <div className={`flex h-10 w-10 items-center justify-center rounded-full ${circleColor}`}>
        <Icon className="w-5 h-5 text-white" />
      </div>
      <span className="text-center text-xs font-medium text-white/90">{label}</span>
    </button>
  )
}
