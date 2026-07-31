import { useEffect, useState } from 'react';
import { platformSettingsApi, type PublicPlatformSettings } from '../lib/api';

const defaults: PublicPlatformSettings = {
  show_home_integration_cards: false,
  show_google_sign_in: false,
  show_github_sign_in: false,
  auth_background_mode: 'gradient',
  auth_background_value: 'linear-gradient(135deg, #0f172a, #0055a4)',
};

/** Public settings shared by the unauthenticated login and registration pages. */
export function usePlatformAuthSettings() {
  const [settings, setSettings] = useState<PublicPlatformSettings>(defaults);

  useEffect(() => {
    let cancelled = false;
    platformSettingsApi
      .getPublic()
      .then((next) => {
        if (!cancelled) setSettings(next);
      })
      .catch(() => {
        // Keep the private-by-default UI if the public settings endpoint is
        // temporarily unavailable.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return settings;
}
