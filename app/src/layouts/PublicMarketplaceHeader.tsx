import { useNavigate, useLocation } from 'react-router-dom';
import {
  SignIn,
  UserPlus,
  List,
  X,
} from '@phosphor-icons/react';
import { motion, AnimatePresence } from 'framer-motion';
import { useState } from 'react';
import { VibeLabBrand } from '../components/ui/VibeLabBrand';

interface PublicMarketplaceHeaderProps {
  isLoading?: boolean;
}

/**
 * Public Marketplace Header
 * Minimal dark design matching Tesslate's internal design system.
 * Tesslate logo, pill nav buttons, sign in/up CTAs.
 */
export function PublicMarketplaceHeader({ isLoading = false }: PublicMarketplaceHeaderProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const isMarketplaceHome = location.pathname === '/marketplace';
  const isBrowseAgents = location.pathname.includes('/browse/agent');
  const isBrowseBases = location.pathname.includes('/browse/base');

  const navItems = [
    { label: 'Explore', path: '/marketplace', active: isMarketplaceHome },
    { label: 'Agents', path: '/marketplace/browse/agent', active: isBrowseAgents },
    { label: 'Templates', path: '/marketplace/browse/base', active: isBrowseBases },
  ];

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--border)] bg-[var(--bg)]">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          {/* Logo + Nav */}
          <div className="flex items-center gap-6">
            <button
              onClick={() => navigate('/marketplace')}
              className="flex items-center gap-2.5 group"
            >
              <VibeLabBrand className="text-sm text-[var(--text)]" />
            </button>

            {/* Desktop Nav — pill buttons */}
            <nav className="hidden md:flex items-center gap-1">
              {navItems.map((item) => (
                <button
                  key={item.path}
                  onClick={() => navigate(item.path)}
                  className={`btn btn-sm ${item.active ? 'btn-tab-active' : 'btn-tab'}`}
                >
                  {item.label}
                </button>
              ))}
            </nav>
          </div>

          {/* Right side */}
          <div className="flex items-center gap-2">
            {/* Auth Buttons */}
            {!isLoading && (
              <>
                <button
                  onClick={() => navigate('/login')}
                  className="btn hidden sm:flex"
                >
                  <SignIn size={14} />
                  Sign In
                </button>
                <button
                  onClick={() => navigate('/register')}
                  className="btn btn-filled"
                >
                  <UserPlus size={14} />
                  <span className="hidden sm:inline">Create account</span>
                  <span className="sm:hidden">Sign Up</span>
                </button>
              </>
            )}

            {/* Mobile Menu Toggle */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="btn btn-icon md:hidden"
              aria-label="Menu"
            >
              {mobileMenuOpen ? <X size={16} /> : <List size={16} />}
            </button>
          </div>
        </div>

        {/* Mobile Menu */}
        <AnimatePresence>
          {mobileMenuOpen && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.2 }}
              className="md:hidden overflow-hidden border-t border-[var(--border)]"
            >
              <nav className="flex flex-col gap-1 py-3">
                {navItems.map((item) => (
                  <button
                    key={item.path}
                    onClick={() => { navigate(item.path); setMobileMenuOpen(false); }}
                    className={`w-full text-left px-3 py-2 rounded-[var(--radius-small)] text-xs font-medium transition-colors ${
                      item.active
                        ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                        : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </nav>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </header>
  );
}

export default PublicMarketplaceHeader;
