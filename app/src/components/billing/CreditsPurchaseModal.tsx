import { X, Coins } from 'lucide-react';

interface CreditsPurchaseModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

const CreditsPurchaseModal = ({ isOpen, onClose }: CreditsPurchaseModalProps) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-[var(--surface)] border border-white/10 rounded-2xl max-w-md w-full overflow-hidden">
        <div className="p-6 border-b border-white/10 flex items-start justify-between gap-4">
          <div className="flex gap-3">
            <div className="w-10 h-10 bg-[var(--primary)]/20 rounded-xl flex items-center justify-center">
              <Coins className="w-5 h-5 text-[var(--primary)]" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-[var(--text)]">Request additional quota</h2>
              <p className="text-sm text-[var(--text)]/60 mt-1">Quota is managed centrally for VibeLab.</p>
            </div>
          </div>
          <button onClick={onClose} aria-label="Close" className="p-2 text-[var(--text)]/50 hover:text-[var(--text)]"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-6 text-sm text-[var(--text)]/70 space-y-3">
          <p>Share your project, expected usage, and duration with your VibeLab administrator.</p>
          <p>Existing quota controls continue to protect platform capacity while your request is reviewed.</p>
        </div>
        <div className="p-4 border-t border-white/10 flex justify-end">
          <button onClick={onClose} className="btn btn-filled">Understood</button>
        </div>
      </div>
    </div>
  );
};

export default CreditsPurchaseModal;
