import { useEffect, useState } from 'react';
import { AlertTriangle, ArrowUpRight, Clock, Coins, TrendingUp } from 'lucide-react';
import toast from 'react-hot-toast';
import { SettingsGroup, SettingsSection } from '../../components/settings';
import { useTeam } from '../../contexts/TeamContext';
import { billingApi } from '../../lib/api';
import {
  SUBSCRIPTION_TIER_CREDITS,
  SUBSCRIPTION_TIER_LABELS,
  SUBSCRIPTION_TIER_PROJECTS,
} from '../../types/billing';
import type { CreditBalanceResponse, SubscriptionResponse, UsageSummaryResponse } from '../../types/billing';

/**
 * Corporate allocation view. Billing endpoints and quota enforcement remain
 * upstream-compatible; this surface deliberately does not expose purchases or Stripe.
 */
export default function BillingSettings() {
  const { can, teamSwitchKey } = useTeam();
  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [credits, setCredits] = useState<CreditBalanceResponse | null>(null);
  const [usage, setUsage] = useState<UsageSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadAllocation = async () => {
      try {
        setLoading(true);
        const [subscriptionResponse, creditsResponse, usageResponse] = await Promise.all([
          billingApi.getSubscription(),
          billingApi.getCreditsBalance(),
          billingApi.getUsage(),
        ]);
        setSubscription(subscriptionResponse);
        setCredits(creditsResponse);
        setUsage(usageResponse);
      } catch (error) {
        console.error('Failed to load allocation data:', error);
        toast.error('Unable to load allocation information');
      } finally {
        setLoading(false);
      }
    };

    void loadAllocation();
  }, [teamSwitchKey]);

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
  const remaining = credits?.total_credits || 0;
  const allowance = Math.max(credits?.monthly_allowance || 0, remaining, 1);
  const used = Math.max(allowance - remaining, 0);
  const usagePercent = Math.min((used / allowance) * 100, 100);
  const isLow = remaining > 0 && remaining <= Math.max(allowance * 0.2, 1);
  const isExhausted = remaining <= 0;

  return (
    <div key={teamSwitchKey} style={{ animation: 'fade-in 0.25s ease-out' }}>
      <SettingsSection
        title="Allocation"
        description="Review the capacity available to your workspace and its current usage."
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
                    Active allocation
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-[var(--text)]/50">
                  <span>{SUBSCRIPTION_TIER_PROJECTS[tier]} project allowance</span>
                  <span>{SUBSCRIPTION_TIER_CREDITS[tier]} capacity units per cycle</span>
                </div>
              </div>
              <a
                href="/feedback"
                className="inline-flex shrink-0 items-center justify-center rounded-lg border border-[var(--primary)]/30 px-4 py-2 text-sm font-medium text-[var(--primary)] transition-colors hover:bg-[var(--primary)]/10"
              >
                Request additional quota
              </a>
            </div>

            <div className="mt-6 max-w-xl">
              <div className="mb-2 flex items-baseline justify-between gap-3">
                <span className="text-sm text-[var(--text)]/55">Available capacity</span>
                <span className="text-sm font-semibold tabular-nums text-[var(--text)]">
                  {remaining.toLocaleString()} remaining
                </span>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-[var(--text)]/10">
                <div
                  className="h-full bg-[var(--primary)] transition-all duration-500"
                  style={{ width: `${usagePercent}%` }}
                />
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-[var(--text)]/40">
                <span>{used.toLocaleString()} used</span>
                <span>{allowance.toLocaleString()} allocated</span>
              </div>
              {credits?.credits_reset_date && (
                <p className="mt-3 flex items-center gap-1.5 text-xs text-[var(--text)]/40">
                  <Clock size={12} />
                  Allocation refreshes on {new Date(credits.credits_reset_date).toLocaleDateString()}
                </p>
              )}
              {(isLow || isExhausted) && (
                <div
                  className={`mt-4 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                    isExhausted
                      ? 'border-red-500/20 bg-red-500/5 text-red-400'
                      : 'border-amber-500/20 bg-amber-500/5 text-amber-400'
                  }`}
                >
                  <AlertTriangle size={14} />
                  {isExhausted
                    ? 'Capacity has been reached. Contact an administrator to request additional quota.'
                    : 'Available capacity is low. Contact an administrator if more is required.'}
                </div>
              )}
            </div>
          </div>
        </SettingsGroup>

        <SettingsGroup title="Usage this cycle">
          <div className="grid grid-cols-2 gap-4 p-5 md:grid-cols-4 md:p-6">
            {[
              { label: 'Requests', value: usage?.total_requests.toLocaleString() || '0', icon: <TrendingUp size={14} /> },
              { label: 'Input tokens', value: `${((usage?.total_tokens_input || 0) / 1000).toFixed(1)}K`, icon: <ArrowUpRight size={14} /> },
              { label: 'Output tokens', value: `${((usage?.total_tokens_output || 0) / 1000).toFixed(1)}K`, icon: <ArrowUpRight size={14} /> },
              { label: 'Capacity used', value: `${usage?.total_cost_cents || 0}`, icon: <Coins size={14} /> },
            ].map((stat) => (
              <div key={stat.label} className="rounded-lg bg-white/[0.02] p-3.5">
                <div className="mb-1.5 flex items-center gap-1.5 text-[var(--text)]/35">
                  {stat.icon}
                  <span className="text-xs">{stat.label}</span>
                </div>
                <div className="text-xl font-bold tabular-nums text-[var(--text)]">{stat.value}</div>
              </div>
            ))}
          </div>
        </SettingsGroup>

        {can('billing.manage') && (
          <p className="px-1 text-xs text-[var(--text)]/40">
            Administrators retain allocation controls. Requests are handled through the internal
            administration process; payment and purchase workflows are not exposed in VibeLab.
          </p>
        )}
      </SettingsSection>
    </div>
  );
}
