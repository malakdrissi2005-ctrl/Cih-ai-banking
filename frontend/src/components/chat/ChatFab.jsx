import { Bot } from 'lucide-react'

// Bouton visuel Assistant IA - voir DocsContext/05_interface_frontend.md §14 : deux instances
// (une dans le telephone, une dans le panneau desktop) controlent le meme ChatWidget.
// Aucun positionnement fixe/absolu baked-in : chaque parent (PhonePreview, DesktopView,
// MobileAppView) place ce bouton a l'endroit qui convient a son propre contexte visuel.
// Props: onToggle(), variant ("mobile" | "desktop"), hasUnread (bool)
export default function ChatFab({ onToggle, variant = 'mobile', hasUnread }) {
  return (
    <button
      onClick={onToggle}
      aria-label="Ouvrir l'assistant IA"
      data-variant={variant}
      className="relative w-14 h-14 rounded-full bg-cih-orange text-white
                 shadow-xl ring-2 ring-cih-blue ring-offset-2 flex items-center justify-center
                 hover:bg-cih-orange-dark transition duration-200"
    >
      <Bot className="w-6 h-6" />
      {hasUnread && (
        <span className="absolute -top-1 -right-1 w-3.5 h-3.5 bg-cih-blue rounded-full border-2 border-white" />
      )}
    </button>
  )
}
