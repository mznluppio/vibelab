import { useNavigate } from 'react-router-dom';
import { VibeLabBrand } from '../components/ui/VibeLabBrand';

/**
 * Public Marketplace Footer
 * Clean, minimal, dark — matches Tesslate's design system.
 * SEO-friendly with proper navigation links.
 */
export function PublicMarketplaceFooter() {
  const navigate = useNavigate();

  const columns = [
    {
      title: 'Marketplace',
      links: [
        { label: 'AI Agents', href: '/marketplace/browse/agent' },
        { label: 'Project Templates', href: '/marketplace/browse/base' },
        { label: 'Skills', href: '/marketplace/browse/skill' },
        { label: 'MCP Servers', href: '/marketplace/browse/mcp_server' },
      ],
    },
    {
      title: 'Categories',
      links: [
        { label: 'Builder', href: '/marketplace/browse/agent?category=builder' },
        { label: 'Frontend', href: '/marketplace/browse/agent?category=frontend' },
        { label: 'Fullstack', href: '/marketplace/browse/agent?category=fullstack' },
        { label: 'Backend', href: '/marketplace/browse/agent?category=backend' },
        { label: 'Data & ML', href: '/marketplace/browse/agent?category=data' },
        { label: 'DevOps', href: '/marketplace/browse/agent?category=devops' },
      ],
    },
    {
      title: 'Company',
      links: [
        { label: 'About', href: '/' },
        { label: 'Help', href: '/feedback' },
        { label: 'Sign Up', href: '/register' },
        { label: 'Sign In', href: '/login' },
      ],
    },
  ];

  return (
    <footer className="border-t border-[var(--border)] mt-16">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          {columns.map((col) => (
            <div key={col.title}>
              <h3 className="text-[11px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider mb-4">
                {col.title}
              </h3>
              <ul className="space-y-2.5">
                {col.links.map((link) => (
                  <li key={link.label}>
                    {link.href.startsWith('http') ? (
                      <a
                        href={link.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
                      >
                        {link.label}
                      </a>
                    ) : (
                      <a
                        href={link.href}
                        className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
                      >
                        {link.label}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}

          {/* Get Started */}
          <div>
            <h3 className="text-[11px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider mb-4">
              Get Started
            </h3>
            <p className="text-xs text-[var(--text-muted)] mb-4 leading-relaxed">
              Build internal applications with AI assistance and governed templates.
            </p>
            <button
              onClick={() => navigate('/register')}
              className="btn btn-filled"
            >
              Get started
            </button>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="mt-12 pt-6 border-t border-[var(--border)] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="text-[11px] text-[var(--text-subtle)]">
              &copy; {new Date().getFullYear()} <VibeLabBrand compact />
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}

export default PublicMarketplaceFooter;
