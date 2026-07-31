import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTeam } from '../contexts/TeamContext';

const isTauriDesktop = (): boolean => {
  if (typeof window === 'undefined') return false;
  return '__TAURI_INTERNALS__' in window || '__TAURI__' in window;
};

function DesktopBootstrapLoader() {
  return (
    <div className="flex h-screen w-screen items-center justify-center bg-white">
      <div className="flex flex-col items-center gap-4 text-gray-600">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-200 border-t-gray-700" />
        <div className="text-sm">Setting up your workspace…</div>
      </div>
    </div>
  );
}

/**
 * PrivateRoute - Protects routes that require authentication
 * Uses the centralized AuthContext for consistent auth state
 */
export function PrivateRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  // Loading state. On desktop the bootstrap can take several seconds while the
  // Python sidecar warms up and mints the local-user JWT, so we render a
  // friendly loader instead of a blank null. In the browser this state is
  // sub-second, so null is fine.
  if (isLoading) {
    return isTauriDesktop() ? <DesktopBootstrapLoader /> : null;
  }

  // Not authenticated - redirect to login, preserving intended destination
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  // Authenticated - show protected content
  return <>{children}</>;
}

/**
 * PublicOnlyRoute - Redirects authenticated users away from auth pages (login, register)
 * Prevents logged-in users from seeing login/register forms
 */
export function PublicOnlyRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  // Loading state - show nothing while checking auth
  if (isLoading) {
    return null;
  }

  // Authenticated - redirect to saved destination or home
  if (isAuthenticated) {
    const from = (location.state as { from?: string })?.from || '/chat';
    return <Navigate to={from} replace />;
  }

  return <>{children}</>;
}


/** Redirect members away from team-governed product surfaces. */
export function TeamFeatureRoute({
  feature,
  children,
}: {
  feature: 'marketplace' | 'automations' | 'technical-settings';
  children: ReactNode;
}) {
  const { loading, membership, canAccessMarketplace, canAccessAutomations } = useTeam();

  if (loading) return null;
  const allowed =
    feature === 'marketplace'
      ? canAccessMarketplace
      : feature === 'automations'
        ? canAccessAutomations
        : membership?.role === 'admin';

  return allowed ? <>{children}</> : <Navigate to="/chat" replace />;
}
