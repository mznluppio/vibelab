import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, Link, useLocation } from 'react-router-dom';
import { authApi, revokeServerSession } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { PulsingGridSpinner } from '../components/PulsingGridSpinner';
import { VibeLabBrand } from '../components/ui/VibeLabBrand';
import { useTheme } from '../theme/ThemeContext';
import { useFeatureFlag } from '../contexts/useFeatureFlag';
import { usePlatformAuthSettings } from '../hooks/usePlatformAuthSettings';
import { AuthVisualPanel } from '../components/auth/AuthVisualPanel';
import toast from 'react-hot-toast';

type LoginMode = 'password' | 'magic-email' | 'magic-sent' | 'magic-code';

const authInputClass =
  'w-full rounded-lg border border-slate-300 bg-white px-3.5 py-3 text-sm text-slate-950 shadow-none outline-none transition-[border-color,box-shadow] duration-200 placeholder:text-slate-500 focus:border-[#0055a4] focus:ring-4 focus:ring-[#0055a4]/10';
const authPrimaryButtonClass =
  'w-full rounded-lg bg-[#0055a4] px-4 py-3.5 text-sm font-semibold text-white transition-colors duration-200 hover:bg-[#004580] focus:outline-none focus:ring-4 focus:ring-[#0055a4]/20 disabled:cursor-not-allowed disabled:opacity-50';
const authTextButtonClass =
  'text-sm font-medium text-slate-600 transition-colors duration-200 hover:text-[#0055a4] focus:outline-none focus-visible:rounded focus-visible:ring-2 focus-visible:ring-[#0055a4]';

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { refreshUserTheme } = useTheme();
  const { checkAuth, isAuthenticated } = useAuth();
  const redirectTo = (location.state as { from?: string })?.from || '/chat';

  // Redirect away if already authenticated (covers desktop auto-login injecting
  // the token after the page has mounted).
  useEffect(() => {
    if (isAuthenticated) {
      navigate(redirectTo, { replace: true });
    }
  }, [isAuthenticated, navigate, redirectTo]);
  const [formData, setFormData] = useState({
    email: '',
    password: '',
  });
  const [loading, setLoading] = useState(false);

  // 2FA state
  const [twoFaRequired, setTwoFaRequired] = useState(false);
  const [tempToken, setTempToken] = useState('');
  const [otpCode, setOtpCode] = useState(['', '', '', '', '', '']);
  const [resendCooldown, setResendCooldown] = useState(0);
  const otpInputRefs = useRef<(HTMLInputElement | null)[]>([]);

  // Magic-link state.
  // When the feature flag is on, the landing view is the email-link form
  // ('magic-email'); users explicitly click "Sign in with password" to
  // reveal the password form. When the flag is off, we fall back to the
  // classic password form and hide every magic-link affordance.
  //
  // Feature flags load asynchronously (FeatureFlagProvider fires a fetch on
  // mount). If we only read the flag in the useState initializer, the first
  // render sees `magicLinkEnabled=false` — before the network completes —
  // and mode gets locked to 'password' even after the flag resolves to
  // true. So we default to 'magic-email' optimistically and let the effect
  // below downgrade to 'password' once the flag has actually loaded. We
  // only overwrite mode if the user hasn't already made their own choice.
  const magicLinkEnabled = useFeatureFlag('magic_link_login');
  const [mode, setMode] = useState<LoginMode>('password');
  const [magicEmail, setMagicEmail] = useState('');
  const userOverrodeModeRef = useRef(false);
  const platformSettings = usePlatformAuthSettings();

  useEffect(() => {
    if (userOverrodeModeRef.current) return;
    setMode('password');
  }, [magicLinkEnabled]);

  // Resend cooldown timer
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = setTimeout(() => setResendCooldown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [resendCooldown]);

  const handleOtpChange = (index: number, value: string) => {
    if (!/^\d*$/.test(value)) return;
    const newCode = [...otpCode];
    newCode[index] = value.slice(-1);
    setOtpCode(newCode);
    if (value && index < 5) {
      otpInputRefs.current[index + 1]?.focus();
    }
  };

  const handleOtpKeyDown = (index: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !otpCode[index] && index > 0) {
      otpInputRefs.current[index - 1]?.focus();
    }
  };

  const handleOtpPaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
    if (pasted.length === 6) {
      setOtpCode(pasted.split(''));
      otpInputRefs.current[5]?.focus();
    }
  };

  const handleVerify2fa = async () => {
    const code = otpCode.join('');
    if (code.length !== 6) {
      toast.error('Saisissez les 6 chiffres');
      return;
    }
    setLoading(true);
    try {
      const response = await authApi.verify2fa(tempToken, code);
      localStorage.setItem('token', response.access_token);
      // Update AuthContext so PrivateRoute allows navigation
      await checkAuth({ force: true });
      refreshUserTheme();
      toast.success('Connexion réussie');
      setLoading(false);
      navigate(redirectTo);
    } catch {
      toast.error('Ce code est invalide ou a expiré');
      setOtpCode(['', '', '', '', '', '']);
      otpInputRefs.current[0]?.focus();
      setLoading(false);
    }
  };

  const handleResendCode = async () => {
    if (resendCooldown > 0) return;
    try {
      await authApi.resend2faCode(tempToken);
      setResendCooldown(60);
      toast.success('Un nouveau code a été envoyé');
    } catch {
      toast.error("Impossible d'envoyer un nouveau code");
    }
  };

  const handleBack = () => {
    setTwoFaRequired(false);
    setTempToken('');
    setOtpCode(['', '', '', '', '', '']);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      // Clear any stale auth state before attempting login
      localStorage.removeItem('token');
      revokeServerSession(); // non-blocking, best-effort

      const response = await authApi.login(formData.email, formData.password);

      if (response.access_token && !response.requires_2fa) {
        // 2FA disabled — JWT issued directly, complete login
        localStorage.setItem('token', response.access_token);
        await checkAuth({ force: true });
        refreshUserTheme();
        navigate(redirectTo);
        return;
      }

      // 2FA required — show OTP input
      setTwoFaRequired(true);
      setTempToken(response.temp_token);
      setResendCooldown(60);
      toast.success('Un code de vérification a été envoyé');
      setLoading(false);
      // Focus first OTP input after render
      setTimeout(() => otpInputRefs.current[0]?.focus(), 100);
    } catch (error: unknown) {
      // Handle validation errors (array format from FastAPI/Pydantic)
      const err = error as {
        statusCode?: number;
        code?: string;
        response?: { data?: { detail?: Array<{ msg: string }> | string } };
      };
      if (err.response?.data?.detail && Array.isArray(err.response.data.detail)) {
        const messages = err.response.data.detail.map((e) => e.msg).join(', ');
        toast.error(messages);
      } else if (typeof err.response?.data?.detail === 'string') {
        const errorMessage = err.response.data.detail;
        if (errorMessage === 'LOGIN_BAD_CREDENTIALS') {
          toast.error('Adresse e-mail ou mot de passe incorrect');
        } else {
          toast.error(errorMessage);
        }
      } else if (err.code === 'INVALID_CREDENTIALS') {
        toast.error('Adresse e-mail ou mot de passe incorrect');
      } else {
        toast.error('La connexion a échoué. Réessayez.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleMagicLinkRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!magicEmail) return;
    setLoading(true);
    try {
      await authApi.magicLinkRequest(magicEmail);
      // Stash the pre-login redirect target so MagicLinkConsume can honor it
      // after the user clicks the emailed link (which may open in a new tab).
      // Same browser = same sessionStorage, so round-trip survives.
      if (redirectTo && redirectTo !== '/chat') {
        sessionStorage.setItem('magic_link_redirect', redirectTo);
      } else {
        sessionStorage.removeItem('magic_link_redirect');
      }
      setMode('magic-sent');
      setResendCooldown(60);
      toast.success('Consultez votre e-mail pour vous connecter');
    } catch {
      // Request is designed to always succeed, but handle network errors
      toast.error("Impossible d'envoyer l'e-mail. Réessayez.");
    } finally {
      setLoading(false);
    }
  };

  const handleMagicLinkResend = async () => {
    if (resendCooldown > 0 || !magicEmail) return;
    try {
      await authApi.magicLinkRequest(magicEmail);
      setResendCooldown(60);
      toast.success('Un nouvel e-mail de connexion a été envoyé');
    } catch {
      toast.error("Impossible d'envoyer l'e-mail. Réessayez.");
    }
  };

  const handleMagicLinkVerify = async () => {
    const code = otpCode.join('');
    if (code.length !== 6) {
      toast.error('Saisissez les 6 chiffres');
      return;
    }
    setLoading(true);
    try {
      const response = await authApi.magicLinkVerify(magicEmail, code);
      localStorage.setItem('token', response.access_token);
      await checkAuth({ force: true });
      refreshUserTheme();
      toast.success('Connexion réussie');
      setLoading(false);
      navigate(redirectTo);
    } catch {
      toast.error('Ce code est invalide ou a expiré');
      setOtpCode(['', '', '', '', '', '']);
      otpInputRefs.current[0]?.focus();
      setLoading(false);
    }
  };

  // Switch from magic-link form to password form. Carry the typed email
  // forward so the user doesn't re-enter it.
  const handleSwitchToPassword = () => {
    userOverrodeModeRef.current = true;
    setFormData((prev) => ({ ...prev, email: magicEmail || prev.email }));
    setOtpCode(['', '', '', '', '', '']);
    setResendCooldown(0);
    setMode('password');
  };

  // Switch from password form to magic-link form. Carry the email forward.
  const handleSwitchToMagicEmail = () => {
    userOverrodeModeRef.current = true;
    setMagicEmail(formData.email || magicEmail);
    setFormData((prev) => ({ ...prev, password: '' }));
    setOtpCode(['', '', '', '', '', '']);
    setResendCooldown(0);
    setMode('magic-email');
  };

  // "Back" button from magic-sent/magic-code — return to the landing
  // magic-email form with the email preserved, so the user can edit and
  // retry without starting from scratch.
  const handleBackToMagicEmail = () => {
    setOtpCode(['', '', '', '', '', '']);
    setResendCooldown(0);
    setMode('magic-email');
  };

  const handleGithubLogin = async () => {
    try {
      setLoading(true);
      // Save intended destination so OAuth callback can redirect there
      sessionStorage.setItem('oauth_redirect', redirectTo);
      // Fetch the GitHub OAuth authorization URL from backend
      const authUrl = await authApi.getGithubAuthUrl();
      // Redirect to GitHub OAuth
      window.location.href = authUrl;
    } catch {
      toast.error('Impossible de démarrer la connexion avec GitHub');
      setLoading(false);
    }
  };

  const handleGoogleLogin = async () => {
    try {
      setLoading(true);
      // Save intended destination so OAuth callback can redirect there
      sessionStorage.setItem('oauth_redirect', redirectTo);
      // Fetch the Google OAuth authorization URL from backend
      const authUrl = await authApi.getGoogleAuthUrl();
      // Redirect to Google OAuth
      window.location.href = authUrl;
    } catch {
      toast.error('Impossible de démarrer la connexion avec Google');
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-100 lg:flex">
      <main className="flex w-full items-center justify-center bg-slate-100 p-5 sm:p-8 lg:w-1/2 lg:p-12">
        <div className="w-full max-w-[26rem] rounded-2xl bg-white p-7 shadow-sm sm:p-9">
          <div className="mb-10 flex items-center gap-3" aria-label="VibeLab, Legrand">
            <span className="grid h-10 w-10 place-items-center rounded-lg bg-[#0055a4] text-sm font-bold tracking-[-0.08em] text-white">
              V
            </span>
            <div className="flex items-baseline gap-2">
              <VibeLabBrand compact className="text-xl font-semibold text-slate-950" />
              <span className="border-l border-slate-300 pl-2 text-[10px] font-semibold tracking-[0.14em] text-slate-500">
                LEGRAND
              </span>
            </div>
          </div>

          <div className="mb-8">
            <h1 className="text-3xl font-semibold tracking-[-0.03em] text-slate-950">
              Bienvenue dans VibeLab
            </h1>
            <p className="mt-3 max-w-sm text-sm leading-6 text-slate-600">
              Décrivez ce que vous voulez créer et transformez vos idées en démonstrations
              utilisables, avec votre équipe.
            </p>
          </div>

          {twoFaRequired ? (
            /* OTP Verification UI */
            <div className="space-y-6">
              <div className="text-center">
                <p className="text-gray-600 text-sm">
                  Nous avons envoyé un code à 6 chiffres à <strong>{formData.email}</strong>
                </p>
              </div>

              {/* OTP Inputs */}
              <div className="flex justify-center gap-3">
                {otpCode.map((digit, index) => (
                  <input
                    key={index}
                    ref={(el) => {
                      otpInputRefs.current[index] = el;
                    }}
                    type="text"
                    inputMode="numeric"
                    maxLength={1}
                    value={digit}
                    onChange={(e) => handleOtpChange(index, e.target.value)}
                    onKeyDown={(e) => handleOtpKeyDown(index, e)}
                    onPaste={index === 0 ? handleOtpPaste : undefined}
                    className="h-14 w-11 rounded-lg border border-slate-300 bg-white text-center text-2xl font-semibold text-slate-950 outline-none transition-[border-color,box-shadow] duration-200 focus:border-[#0055a4] focus:ring-4 focus:ring-[#0055a4]/10"
                  />
                ))}
              </div>

              {/* Verify Button */}
              <button
                onClick={handleVerify2fa}
                disabled={loading || otpCode.join('').length !== 6}
                className={authPrimaryButtonClass}
              >
                {loading ? (
                  <div className="flex items-center justify-center gap-2">
                    <PulsingGridSpinner size={18} />
                    <span>Vérification…</span>
                  </div>
                ) : (
                  'Vérifier et se connecter'
                )}
              </button>

              {/* Resend / Back */}
              <div className="flex items-center justify-between text-sm">
                <button onClick={handleBack} className={authTextButtonClass}>
                  Retour à la connexion
                </button>
                <button
                  onClick={handleResendCode}
                  disabled={resendCooldown > 0}
                  className={`${authTextButtonClass} disabled:cursor-not-allowed disabled:text-slate-400`}
                >
                  {resendCooldown > 0 ? `Renvoyer dans ${resendCooldown}s` : 'Renvoyer le code'}
                </button>
              </div>
            </div>
          ) : mode === 'magic-email' ? (
            /* Magic Link — email entry */
            <>
              {(platformSettings.show_google_sign_in || platformSettings.show_github_sign_in) && (
                <div className="space-y-3 mb-6">
                  {platformSettings.show_google_sign_in && (
                    <button
                      onClick={handleGoogleLogin}
                      disabled={loading}
                      className="flex w-full items-center justify-center gap-3 rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-semibold text-slate-700 transition-colors duration-200 hover:border-slate-400 hover:bg-slate-50 focus:outline-none focus:ring-4 focus:ring-[#0055a4]/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <svg className="w-5 h-5" viewBox="0 0 24 24">
                        <path
                          fill="#4285F4"
                          d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                        />
                        <path
                          fill="#34A853"
                          d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                        />
                        <path
                          fill="#FBBC05"
                          d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                        />
                        <path
                          fill="#EA4335"
                          d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                        />
                      </svg>
                      Continuer avec Google
                    </button>
                  )}
                  {platformSettings.show_github_sign_in && (
                    <button
                      onClick={handleGithubLogin}
                      disabled={loading}
                      className="flex w-full items-center justify-center gap-3 rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-semibold text-slate-700 transition-colors duration-200 hover:border-slate-400 hover:bg-slate-50 focus:outline-none focus:ring-4 focus:ring-[#0055a4]/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                        <path
                          fillRule="evenodd"
                          d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                          clipRule="evenodd"
                        />
                      </svg>
                      Continuer avec GitHub
                    </button>
                  )}
                </div>
              )}

              <form onSubmit={handleMagicLinkRequest} className="space-y-4">
                <label className="grid gap-2 text-sm font-medium text-slate-700">
                  Adresse e-mail professionnelle
                  <input
                    type="email"
                    value={magicEmail}
                    onChange={(e) => setMagicEmail(e.target.value)}
                    className={authInputClass}
                    placeholder="name@company.com"
                    required
                    autoComplete="email"
                    maxLength={254}
                    autoFocus
                  />
                </label>
                <button
                  type="submit"
                  disabled={loading || !magicEmail}
                  className={authPrimaryButtonClass}
                >
                  {loading ? (
                    <div className="flex items-center justify-center gap-2">
                      <PulsingGridSpinner size={18} />
                      <span>Envoi…</span>
                    </div>
                  ) : (
                    'Recevoir un lien de connexion'
                  )}
                </button>
                <div className="text-center">
                  <button
                    type="button"
                    onClick={handleSwitchToPassword}
                    className={authTextButtonClass}
                  >
                    Se connecter avec un mot de passe
                  </button>
                </div>
              </form>
            </>
          ) : mode === 'magic-sent' ? (
            /* Magic Link — sent, waiting */
            <div className="space-y-6">
              <div className="text-center">
                <p className="text-gray-600 text-sm">
                  Nous avons envoyé un lien à <strong>{magicEmail}</strong>. Ouvrez-le depuis votre
                  e-mail, ou saisissez le code à 6 chiffres reçu.
                </p>
              </div>
              <button
                onClick={() => {
                  setOtpCode(['', '', '', '', '', '']);
                  setMode('magic-code');
                  setTimeout(() => otpInputRefs.current[0]?.focus(), 100);
                }}
                className={authPrimaryButtonClass}
              >
                Saisir un code à la place
              </button>
              <div className="flex items-center justify-between text-sm">
                <button onClick={handleBackToMagicEmail} className={authTextButtonClass}>
                  Utiliser une autre adresse
                </button>
                <button
                  onClick={handleMagicLinkResend}
                  disabled={resendCooldown > 0}
                  className={`${authTextButtonClass} disabled:cursor-not-allowed disabled:text-slate-400`}
                >
                  {resendCooldown > 0 ? `Renvoyer dans ${resendCooldown}s` : "Renvoyer l'e-mail"}
                </button>
              </div>
            </div>
          ) : mode === 'magic-code' ? (
            /* Magic Link — code entry */
            <div className="space-y-6">
              <div className="text-center">
                <p className="text-gray-600 text-sm">
                  Saisissez le code à 6 chiffres envoyé à <strong>{magicEmail}</strong>
                </p>
              </div>
              <div className="flex justify-center gap-3">
                {otpCode.map((digit, index) => (
                  <input
                    key={index}
                    ref={(el) => {
                      otpInputRefs.current[index] = el;
                    }}
                    type="text"
                    inputMode="numeric"
                    maxLength={1}
                    value={digit}
                    onChange={(e) => handleOtpChange(index, e.target.value)}
                    onKeyDown={(e) => handleOtpKeyDown(index, e)}
                    onPaste={index === 0 ? handleOtpPaste : undefined}
                    className="h-14 w-11 rounded-lg border border-slate-300 bg-white text-center text-2xl font-semibold text-slate-950 outline-none transition-[border-color,box-shadow] duration-200 focus:border-[#0055a4] focus:ring-4 focus:ring-[#0055a4]/10"
                  />
                ))}
              </div>
              <button
                onClick={handleMagicLinkVerify}
                disabled={loading || otpCode.join('').length !== 6}
                className={authPrimaryButtonClass}
              >
                {loading ? (
                  <div className="flex items-center justify-center gap-2">
                    <PulsingGridSpinner size={18} />
                    <span>Vérification…</span>
                  </div>
                ) : (
                  'Se connecter'
                )}
              </button>
              <div className="flex items-center justify-between text-sm">
                <button onClick={handleBackToMagicEmail} className={authTextButtonClass}>
                  Utiliser une autre adresse
                </button>
                <button
                  onClick={handleMagicLinkResend}
                  disabled={resendCooldown > 0}
                  className={`${authTextButtonClass} disabled:cursor-not-allowed disabled:text-slate-400`}
                >
                  {resendCooldown > 0 ? `Renvoyer dans ${resendCooldown}s` : 'Renvoyer le code'}
                </button>
              </div>
            </div>
          ) : (
            /* Password Login UI — no OAuth here; the magic-email landing
               view is the front door and offers every sign-in option. */
            <>
              {/* Email + Password Form */}
              <form onSubmit={handleSubmit} className="space-y-4">
                <label className="grid gap-2 text-sm font-medium text-slate-700">
                  Adresse e-mail professionnelle
                  <input
                    type="email"
                    value={formData.email}
                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                    className={authInputClass}
                    placeholder="name@company.com"
                    required
                    autoComplete="email"
                    maxLength={254}
                    pattern="[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$"
                  />
                </label>

                <label className="grid gap-2 text-sm font-medium text-slate-700">
                  Mot de passe
                  <input
                    type="password"
                    value={formData.password}
                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                    className={authInputClass}
                    placeholder="Votre mot de passe"
                    required
                    autoComplete="current-password"
                    maxLength={128}
                    minLength={6}
                  />
                </label>

                <div className="flex justify-end">
                  <Link
                    to="/forgot-password"
                    className="text-xs font-medium text-slate-600 transition-colors duration-200 hover:text-[#0055a4] focus:outline-none focus-visible:rounded focus-visible:ring-2 focus-visible:ring-[#0055a4]"
                  >
                    Mot de passe oublié ?
                  </Link>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className={`${authPrimaryButtonClass} mt-2`}
                >
                  {loading ? (
                    <div className="flex items-center justify-center gap-2">
                      <PulsingGridSpinner size={18} />
                      <span>Connexion…</span>
                    </div>
                  ) : (
                    'Se connecter'
                  )}
                </button>
              </form>

              {/* Magic links remain available when configured, while password
                  sign-in stays the primary entry point. */}
              {magicLinkEnabled && (
                <div className="mt-4 text-center">
                  <button
                    type="button"
                    onClick={handleSwitchToMagicEmail}
                    disabled={loading}
                    className={authTextButtonClass}
                  >
                    Se connecter avec un lien par e-mail
                  </button>
                </div>
              )}

              {/* Sign up link */}
              <div className="mt-6 text-center">
                <p className="text-gray-600 text-sm">
                  Vous n’avez pas encore de compte ?{' '}
                  <Link
                    to="/register"
                    state={{ from: redirectTo !== '/chat' ? redirectTo : undefined }}
                    className="font-semibold text-[#0055a4] underline decoration-[#0055a4]/30 underline-offset-4 transition-colors hover:text-[#004580]"
                  >
                    Créer un compte
                  </Link>
                </p>
              </div>
            </>
          )}
        </div>
      </main>

      <AuthVisualPanel appearance={platformSettings} />
    </div>
  );
}
