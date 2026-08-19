import type { CSSProperties } from 'react';
import type { PublicPlatformSettings } from '../../lib/api';

export function AuthVisualPanel({ appearance }: { appearance: PublicPlatformSettings }) {
  const isImage = appearance.auth_background_mode === 'image';
  const style: CSSProperties = isImage
    ? {
        backgroundImage: `url("${appearance.auth_background_value}")`,
        backgroundPosition: 'center',
        backgroundSize: 'cover',
      }
    : { background: appearance.auth_background_value };

  return (
    <aside
      className="relative hidden overflow-hidden lg:flex lg:w-1/2 lg:items-end lg:p-14"
      style={style}
      aria-hidden="true"
    >
      {isImage && <div className="absolute inset-0 bg-black/35" />}
      <div className="relative max-w-xl text-white">
        <p className="text-sm font-medium text-white/75">Un espace simple pour votre équipe</p>
        <p className="mt-4 text-4xl font-semibold leading-[1.08] tracking-[-0.03em] text-pretty">
          Transformez une idée en démo qui fonctionne.
        </p>
        <p className="mt-5 max-w-md text-sm leading-6 text-white/80">
          Décrivez votre besoin avec vos mots. VibeLab vous aide à obtenir un outil concret à
          montrer, tester et améliorer ensemble.
        </p>
        <p className="mt-10 text-xs font-semibold tracking-[0.12em] text-white/65">LEGRAND</p>
      </div>
    </aside>
  );
}
