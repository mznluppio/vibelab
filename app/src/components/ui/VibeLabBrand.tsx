interface VibeLabBrandProps {
  compact?: boolean;
  className?: string;
}

/**
 * Text-only product mark used until Legrand supplies approved brand assets.
 * It deliberately avoids imitating the Legrand corporate logo.
 */
export function VibeLabBrand({ compact = false, className = '' }: VibeLabBrandProps) {
  return (
    <span className={`inline-flex items-baseline gap-1 font-semibold tracking-tight ${className}`}>
      <span>VibeLab</span>
      {!compact && <span className="text-[0.7em] font-medium text-current/60">by Legrand</span>}
    </span>
  );
}
