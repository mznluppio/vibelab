import { X, Info } from 'lucide-react';
import type { SubscriptionTier } from '../../types/billing';

interface UpgradeModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentTier?: SubscriptionTier;
  reason?: 'projects' | 'deploys' | 'features' | 'credits' | 'byok' | 'general';
  title?: string;
  message?: string;
  suggestedTier?: SubscriptionTier;
}

const reasonCopy: Record<NonNullable<UpgradeModalProps['reason']>, { title: string; message: string }> = {
  projects: { title: 'Project allowance reached', message: 'Contact an administrator to request capacity for another project.' },
  deploys: { title: 'Runtime capacity reached', message: 'Contact an administrator to request additional runtime capacity.' },
  features: { title: 'Access is managed centrally', message: 'Contact an administrator to request access to this capability.' },
  credits: { title: 'Usage quota reached', message: 'Contact an administrator to request additional AI usage quota.' },
  byok: { title: 'Provider access is managed centrally', message: 'Contact an administrator to request provider access.' },
  general: { title: 'Request additional capacity', message: 'Contact an administrator to review your VibeLab capacity request.' },
};

const UpgradeModal = ({ isOpen, onClose, reason = 'general', title, message }: UpgradeModalProps) => {
  if (!isOpen) return null;
  const copy = reasonCopy[reason];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-[var(--surface)] border border-white/10 rounded-2xl max-w-lg w-full overflow-hidden">
        <div className="p-6 border-b border-white/10 flex items-start justify-between gap-4">
          <div className="flex gap-3">
            <Info className="w-6 h-6 text-[var(--primary)] shrink-0" />
            <div>
              <h2 className="text-xl font-bold text-[var(--text)]">{title || copy.title}</h2>
              <p className="text-sm text-[var(--text)]/60 mt-1">{message || copy.message}</p>
            </div>
          </div>
          <button onClick={onClose} aria-label="Close" className="p-2 text-[var(--text)]/50 hover:text-[var(--text)]"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-6 text-sm text-[var(--text)]/70">
          Your existing usage limits remain active while the request is reviewed.
        </div>
        <div className="p-4 border-t border-white/10 flex justify-end">
          <button onClick={onClose} className="btn btn-filled">Understood</button>
        </div>
      </div>
    </div>
  );
};

export default UpgradeModal;
