import { Link, useLocation } from 'react-router-dom'
import { useTheme } from './ThemeProvider'
import type { ReactNode } from 'react'

const NAV_ITEMS = [
  { path: '/', label: 'Leaderboard', icon: 'L' },
  { path: '/calendar', label: 'Calendar', icon: 'C' },
  { path: '/scoring', label: 'Scoring', icon: 'S' },
  { path: '/export', label: 'Export', icon: 'E' },
]

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { theme, setTheme } = useTheme()

  return (
    <div className="min-h-screen bg-brand-light-bg dark:bg-gray-900 transition-colors">
      {/* Skip link for keyboard navigation */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-elastic-blue focus:text-white focus:rounded"
      >
        Skip to main content
      </a>

      {/* Header */}
      <header className="bg-white dark:bg-gray-800 border-b border-brand-border-gray dark:border-gray-700 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-md bg-elastic-blue flex items-center justify-center">
                <span className="text-white font-bold text-sm">AE</span>
              </div>
              <span className="font-semibold text-brand-body dark:text-white text-lg hidden sm:inline">
                AE Activity Tracker
              </span>
            </div>

            <nav className="flex items-center gap-1" aria-label="Main navigation">
              {NAV_ITEMS.map((item) => {
                const active = location.pathname === item.path
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={`px-3 py-2 text-sm rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-elastic-blue ${
                      active
                        ? 'bg-elastic-blue text-white'
                        : 'text-brand-body dark:text-gray-300 hover:bg-brand-light-bg dark:hover:bg-gray-700'
                    }`}
                    aria-current={active ? 'page' : undefined}
                  >
                    <span className="sm:hidden" aria-hidden="true">{item.icon}</span>
                    <span className="hidden sm:inline">{item.label}</span>
                  </Link>
                )
              })}
            </nav>

            {/* Theme toggle */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => setTheme(theme === 'dark' ? 'light' : theme === 'light' ? 'system' : 'dark')}
                className="p-2 rounded-md text-brand-medium-gray hover:text-brand-body dark:hover:text-white hover:bg-brand-light-bg dark:hover:bg-gray-700 transition-colors focus:outline-none focus:ring-2 focus:ring-elastic-blue"
                aria-label={`Current theme: ${theme}. Click to cycle.`}
                title={`Theme: ${theme}`}
              >
                {theme === 'dark' ? (
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" /></svg>
                ) : theme === 'light' ? (
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" /></svg>
                ) : (
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>
                )}
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main id="main-content" className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8" role="main">
        {children}
      </main>

      {/* Footer */}
      <footer className="border-t border-brand-border-gray dark:border-gray-700 mt-auto">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between text-xs text-brand-medium-gray">
            <span>Elastic Value Engineering</span>
            <span>v1.0.3</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
