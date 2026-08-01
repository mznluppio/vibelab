import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Clock, Coins, Users } from 'lucide-react';
import toast from 'react-hot-toast';
import { SettingsGroup, SettingsSection } from '../../components/settings';
import { useTeam } from '../../contexts/TeamContext';
import { billingApi, type CreditAllocationResponse } from '../../lib/api';
import {
  SUBSCRIPTION_TIER_CREDITS,
  SUBSCRIPTION_TIER_LABELS,
  SUBSCRIPTION_TIER_PROJECTS,
} from '../../types/billing';
import type { SubscriptionResponse } from '../../types/billing';

/** Team allocation, backed by the same credit ledger used for every model call. */
export default function BillingSettings() {
  const { teamSwitchKey } = useTeam();
  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [allocation, setAllocation] = useState<CreditAllocationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingMemberId, setSavingMemberId] = useState<string | null>(null);

  const loadAllocation = useCallback(async () => {
    try {
      setLoading(true);
      const [subscriptionResponse, allocationResponse] = await Promise.all([
        billingApi.getSubscription(),
        billingApi.getAllocation(),
      ]);
      setSubscription(subscriptionResponse);
      setAllocation(allocationResponse);
    } catch (error) {
      console.error('Failed to load allocation data:', error);
      toast.error('Unable to load allocation information');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAllocation();
  }, [loadAllocation, teamSwitchKey]);

  if (loading) {
    return (
      <div key={teamSwitchKey} style={{ animation: 'fade-in 0.25s ease-out' }}>
        <SettingsSection title="Allocation" description="Loading available capacity">
          <div className="flex items-center justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-[var(--primary)]" />
          </div>
        </SettingsSection>
      </div>
    );
  }

  const tier = subscription?.tier || 'free';
  const teamRemaining = allocation?.team_remaining || 0;
  const teamCapacity = Math.max(allocation?.team_capacity || 0, teamRemaining, 1);
  const ownUsage = allocation?.member.consumed || 0;
  const ownRemaining = allocation?.member.remaining || 0;
  const usagePercent = Math.min((ownUsage / teamCapacity) * 100, 100);
  const isLow = teamRemaining > 0 && teamRemaining <= Math.max(teamCapacity * 0.2, 1);
  const isExhausted = teamRemaining <= 0 || (allocation?.mode === 'individual' && ownRemaining <= 0);

  return (
    <div key={teamSwitchKey} style={{ animation: 'fade-in 0.25s ease-out' }}>
      <SettingsSection
        title="Allocation"
        description="Review the capacity available to your workspace and your own consumption."
      >
        <SettingsGroup title="Available capacity">
          <div className="p-5 md:p-6">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="flex items-center gap-2.5">
                  <h3 className="text-2xl font-bold text-[var(--text)]">
                    {SUBSCRIPTION_TIER_LABELS[tier]}
                  </h3>
                  <span className="rounded-full bg-[var(--primary)]/10 px-2.5 py-0.5 text-xs font-medium text-[var(--primary)]">
                    {allocation?.mode === 'individual' ? 'Individual allocation' : 'Shared allocation'}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-[var(--text)]/50">
                  <span>{SUBSCRIPTION_TIER_PROJECTS[tier]} project allowance</span>
                  <span>{SUBSCRIPTION_TIER_CREDITS[tier]} capacity units per cycle</span>
                </div>
              </div>
              <a href="/feedback" className="inline-flex shrink-0 items-center justify-center rounded-lg border border-[var(--primary)]/30 px-4 py-2 text-sm font-medium text-[var(--primary)] transition-colors hover:bg-[var(--primary)]/10">
                Request additional quota
              </a>
            </div>

            <div className="mt-6 max-w-xl">
              <div className="mb-2 flex items-baseline justify-between gap-3">
                <span className="text-sm text-[var(--text)]/55">Team capacity remaining</span>
                <span className="text-sm font-semibold tabular-nums text-[var(--text)]">{teamRemaining.toLocaleString()} remaining</span>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-[var(--text)]/10">
                <div className="h-full bg-[var(--primary)] transition-all duration-500" style={{ width: `${usagePercent}%` }} />
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-[var(--text)]/40">
                <span>{ownUsage.toLocaleString()} used by you</span>
                <span>{teamCapacity.toLocaleString()} team capacity</span>
              </div>
              {allocation?.cycle_started_at && (
                <p className="mt-3 flex items-center gap-1.5 text-xs text-[var(--text)]/40">
                  <Clock size={12} /> Current allocation cycle started on {new Date(allocation.cycle_started_at).toLocaleDateString()}
                </p>
              )}
              {(isLow || isExhausted) && (
                <div className={`mt-4 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${isExhausted ? 'border-red-500/20 bg-red-500/5 text-red-400' : 'border-amber-500/20 bg-amber-500/5 text-amber-400'}`}>
                  <AlertTriangle size={14} />
                  {isExhausted ? 'Capacity has been reached. Contact an administrator to request more.' : 'Available capacity is low. Contact an administrator if more is required.'}
                </div>
              )}
            </div>
          </div>
        </SettingsGroup>

        <SettingsGroup title="Your usage this cycle">
          <div className="grid grid-cols-2 gap-4 p-5 md:grid-cols-3 md:p-6">
            {[
              { label: 'Capacity used', value: ownUsage.toLocaleString(), icon: <Coins size={14} /> },
              { label: 'Your remaining', value: ownRemaining.toLocaleString(), icon: <Coins size={14} /> },
              { label: 'Team remaining', value: teamRemaining.toLocaleString(), icon: <Users size={14} /> },
            ].map((stat) => (
              <div key={stat.label} className="rounded-lg bg-white/[0.02] p-3.5">
                <div className="mb-1.5 flex items-center gap-1.5 text-[var(--text)]/35">{stat.icon}<span className="text-xs">{stat.label}</span></div>
                <div className="text-xl font-bold tabular-nums text-[var(--text)]">{stat.value}</div>
              </div>
            ))}
          </div>
        </SettingsGroup>

        {allocation?.is_admin && (
          <SettingsGroup title="Team allocation controls">
            <div className="p-5 md:p-6">
              <label className="block max-w-xl text-sm font-medium text-[var(--text)]">
                Allocation model
                <select
                  value={allocation.mode}
                  onChange={async (event) => {
                    try {
                      await billingApi.updateAllocationMode(event.target.value as 'shared' | 'individual');
                      await loadAllocation();
                      toast.success('Allocation model updated');
                    } catch {
                      toast.error('Unable to update allocation model');
                    }
                  }}
                  className="mt-2 block w-full rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-sm text-[var(--text)]"
                >
                  <option value="shared">Shared team allocation</option>
                  <option value="individual">Individual member allocations</option>
                </select>
              </label>
              <p className="mt-2 max-w-2xl text-xs text-[var(--text)]/50">Shared uses one common team pool. Individual adds per-member ceilings while the team pool remains the final hard limit.</p>
              {allocation.mode === 'individual' && allocation.allocation_exceeds_capacity && (
                <div className="mt-4 flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-400"><AlertTriangle size={14} />Member limits exceed the team capacity. The shared balance still remains the final limit.</div>
              )}
              {allocation.members && (
                <div className="mt-6 overflow-x-auto">
                  <table className="w-full min-w-[600px] text-left text-sm">
                    <thead className="border-b border-[var(--border)] text-xs text-[var(--text)]/50"><tr><th className="pb-2 font-medium">Member</th><th className="pb-2 font-medium">Used</th><th className="pb-2 font-medium">Limit</th><th className="pb-2 font-medium">Remaining</th></tr></thead>
                    <tbody>{allocation.members.map((member) => (
                      <tr key={member.user_id} className="border-b border-[var(--border)]/70">
                        <td className="py-3"><div className="font-medium text-[var(--text)]">{member.name || member.email || 'Team member'}</div><div className="text-xs text-[var(--text)]/45">{member.role}</div></td>
                        <td className="py-3 tabular-nums">{member.consumed.toLocaleString()}</td>
                        <td className="py-3">{allocation.mode === 'individual' ? <input type="number" min="0" defaultValue={member.credit_limit} disabled={savingMemberId === member.user_id} onBlur={async (event) => {
                          const limit = Math.max(0, Number(event.target.value) || 0);
                          if (limit === member.credit_limit) return;
                          try { setSavingMemberId(member.user_id); await billingApi.updateMemberAllocation(member.user_id, limit); await loadAllocation(); }
                          catch { toast.error('Unable to update member allocation'); }
                          finally { setSavingMemberId(null); }
                        }} className="w-24 rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--bg)] px-2 py-1 tabular-nums" aria-label={`Allocation limit for ${member.name || member.email || 'member'}`} /> : <span className="text-[var(--text)]/45">Shared</span>}</td>
                        <td className="py-3 tabular-nums">{member.remaining.toLocaleString()}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </div>
          </SettingsGroup>
        )}
      </SettingsSection>
    </div>
  );
}
