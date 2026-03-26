import React from 'react'
import {
  FlaskConical,
  TrendingUp,
  Grid3x3,
  Filter,
  Server,
  MessageSquare,
} from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import { colors } from '../theme/colors'

type Screen = 'tank' | 'pnl' | 'monte' | 'filter' | 'vps' | 'guide'

interface NavItem {
  screen: Screen
  label: string
  icon: React.ReactNode
}

const NAV_ITEMS: NavItem[] = [
  { screen: 'tank', label: 'Tank', icon: <FlaskConical size={16} /> },
  { screen: 'pnl', label: 'P&L', icon: <TrendingUp size={16} /> },
  { screen: 'monte', label: 'Monte Carlo', icon: <Grid3x3 size={16} /> },
  { screen: 'filter', label: 'Filters', icon: <Filter size={16} /> },
  { screen: 'vps', label: 'VPS', icon: <Server size={16} /> },
  { screen: 'guide', label: 'Guide', icon: <MessageSquare size={16} /> },
]

export const LeftRail: React.FC = () => {
  const activeScreen = useAppStore((s) => s.activeScreen)
  const setActiveScreen = useAppStore((s) => s.setActiveScreen)

  const today = new Date().toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })

  return (
    <div
      className="flex flex-col flex-shrink-0 h-full"
      style={{
        width: 220,
        background: colors.bgElevated,
        borderRight: `1px solid ${colors.border}`,
      }}
    >
      {/* Logo area */}
      <div className="px-4 pt-5 pb-4" style={{ borderBottom: `1px solid ${colors.border}` }}>
        <div
          className="text-xl font-bold tracking-wide"
          style={{ color: colors.textPrimary }}
        >
          JJ
        </div>
        <div className="text-xs mt-0.5" style={{ color: colors.textMuted }}>
          Command Console
        </div>
      </div>

      {/* Nav buttons */}
      <nav className="flex flex-col gap-2 px-3 py-4 flex-1">
        {NAV_ITEMS.map(({ screen, label, icon }) => {
          const isActive = activeScreen === screen
          return (
            <button
              key={screen}
              onClick={() => setActiveScreen(screen)}
              className="flex items-center gap-3 w-full rounded text-sm transition-colors"
              style={{
                height: 44,
                paddingLeft: isActive ? 'calc(0.75rem - 3px)' : '0.75rem',
                paddingRight: '0.75rem',
                background: isActive ? colors.bgPanel : 'transparent',
                borderLeft: isActive ? `3px solid ${colors.elasticBlue}` : '3px solid transparent',
                color: isActive ? colors.textPrimary : colors.textSecondary,
                cursor: 'pointer',
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  ;(e.currentTarget as HTMLButtonElement).style.background =
                    'rgba(16, 21, 32, 0.5)'
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  ;(e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                }
              }}
            >
              <span className="flex-shrink-0">{icon}</span>
              <span>{label}</span>
            </button>
          )
        })}
      </nav>

      {/* Footer */}
      <div
        className="px-4 py-3"
        style={{ borderTop: `1px solid ${colors.border}` }}
      >
        <div className="text-xs" style={{ color: colors.textMuted }}>
          v0.1.0
        </div>
        <div className="text-xs mt-0.5" style={{ color: colors.textMuted }}>
          {today}
        </div>
      </div>
    </div>
  )
}
