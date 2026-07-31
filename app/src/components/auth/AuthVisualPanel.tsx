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
      className="relative hidden overflow-hidden lg:flex lg:w-1/2 lg:items-end lg:p-12"
      style={style}
      aria-hidden="true"
    >
      {isImage && <div className="absolute inset-0 bg-black/35" />}
      <div className="relative max-w-lg text-white">
        <p className="text-sm font-medium uppercase tracking-[0.2em] text-white/75">VibeLab</p>
        <p className="mt-3 text-3xl font-semibold leading-tight">Build together, with one shared workspace.</p>
      </div>
    </aside>
  );
}
