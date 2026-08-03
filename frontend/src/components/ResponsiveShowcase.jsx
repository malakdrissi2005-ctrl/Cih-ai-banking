import MobileAppView from './mobile/MobileAppView.jsx'
import DesktopView from './DesktopView.jsx'
import PhonePreview from './PhonePreview.jsx'

// Organise l'affichage selon les regles de largeur exactes - voir CLAUDE.md §9.2 et
// DocsContext/05_interface_frontend.md §4 :
// - < 640px  : MobileAppView seul, plein ecran, sans cadre.
// - 640-899px: DesktopView seul, pleine largeur (telephone masque).
// - >= 900px : PhonePreview (gauche) + DesktopView (droite), simultanement.
//
// La bascule telephone+desktop (>= 900px) est geree en CSS pur via .showcase-layout /
// .showcase-phone / .showcase-desktop (voir src/index.css) - PAS de classe Tailwind `xl:`
// (1280px), afin de rester fiable meme lorsque la mise a l'echelle du systeme d'exploitation
// reduit la largeur CSS effective rapportee par le navigateur.
export default function ResponsiveShowcase() {
  return (
    <>
      {/* Vrai mobile (< 640px) */}
      <div className="sm:hidden">
        <MobileAppView />
      </div>

      {/* Desktop (>= 640px) */}
      <div className="hidden sm:block sm:overflow-x-hidden bg-gray-50">
        <div className="showcase-layout">
          <section className="showcase-phone">
            <PhonePreview />
          </section>

          <section className="showcase-desktop">
            <DesktopView />
          </section>
        </div>
      </div>
    </>
  )
}
