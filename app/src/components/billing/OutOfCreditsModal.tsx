import type { SubscriptionTier } from '../../types/billing';
import { SUBSCRIPTION_TIER_CREDITS } from '../../types/billing';

interface OutOfCreditsModalProps {
  open: boolean;
  onClose: () => void;
  tier?: SubscriptionTier;
  creditsResetDate?: string;
}

export function OutOfCreditsModal({
  open,
  onClose,
  tier = 'free',
  creditsResetDate,
}: OutOfCreditsModalProps) {
  if (!open) return null;

  const daysUntilReset = creditsResetDate
    ? Math.ceil((new Date(creditsResetDate).getTime() - Date.now()) / (1000 * 60 * 60 * 24))
    : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-[var(--surface)] border border-white/10 rounded-2xl max-w-md w-full overflow-hidden">
        <div className="p-6 text-center border-b border-white/10">
          <h2 className="text-xl font-bold text-[var(--text)]">Usage quota reached</h2>
          <p className="text-sm text-[var(--text)]/60 mt-2">
            Your available AI capacity has been used. Contact a VibeLab administrator to request
            additional quota.
          </p>
        </div>
        <div className="p-6 space-y-3 text-sm text-[var(--text)]/70">
          <div className="rounded-xl bg-white/5 p-4">
            <div className="font-medium text-[var(--text)]">Current allocation</div>
            <div className="mt-1">{SUBSCRIPTION_TIER_CREDITS[tier]} capacity</div>
          </div>
          {daysUntilReset !== null && daysUntilReset > 0 && (
            <p>Your monthly allocation resets in {daysUntilReset} day{daysUntilReset === 1 ? '' : 's'}.</p>
          )}
        </div>
        <div className="p-4 border-t border-white/10 flex justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-[var(--text)]/70 hover:text-[var(--text)]">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
