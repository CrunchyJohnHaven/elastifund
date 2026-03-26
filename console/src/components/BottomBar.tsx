import React from 'react'
import { useAppStore } from '../store/useAppStore'
import { colors } from '../theme/colors'

const FILL_TARGET = 50
const CHECKPOINTS = [
  { pct: 0.2, fills: 10 },
  { pct: 0.4, fills: 20 },
  { pct: 0.6, fills: 30 },
  { pct: 1.0, fills: 50 },
]

function relativeTime(iso: string): string {
  try {
    const diffMs = Date.now() - new Date(iso).getTime()
    const sec = Math.floor(diffMs / 1000)
    const min = Math.floor(sec / 60)
    const hr = Math.floor(min / 60)
    if (sec < 60) return `${sec}s ago`
    if (min < 60) return `${min}m ago`
    return `${hr}h ago`
  } catch {
    return 'unknown'
  }
}

export const BottomBar: React.FC = () => {
  const cohort = useAppStore((s) => s.cohort)

  const fills = cohort?.resolved_down_fills ?? 0
  const fillPct = Math.min(fills / FILL_TARGET, 1)
  const checkpointStatus = cohort?.checkpoint_status ?? 'No data'
  const generatedAt = cohort?.generated_at

  return (
    <div
      className="flex items-center h-12 px-4 gap-4 flex-shrink-0 w-full"
      style={{
        background: colors.bgElevated,
        borderTop: `1px solid ${colors.border}`,
      }}
    >
      {/* Progress bar — 60% width */}
      <div className="relative flex-shrink-0" style={{ width: '60%' }}>
        {/* Track */}
        <div
          className="relative h-2 rounded-full overflow-visible"
          style={{ background: colors.bgPanel }}
        >
          {/* Fill */}
          <div
            className="h-2 rounded-full transition-all duration-700"
            style={{
              width: `${fillPct * 100}%`,
              background: `linear-gradient(to right, ${colors.elasticBlue}, ${colors.teal})`,
            }}
          />
          {/* Checkpoint markers */}
          {CHECKPOINTS.map(({ pct, fills: needed }) => {
            const reached = fills >= needed
            return (
              <div
                key={pct}
                className="absolute top-1/2 -translate-y-1/2 w-px h-3"
                style={{
                  left: `${pct * 100}%`,
                  background: reached ? '#FEC514' : 'rgba(255,255,255,0.2)',
                }}
              />
            )
          })}
        </div>
      </div>

      {/* Checkpoint text */}
      <span className="text-xs flex-1 truncate" style={{ color: colors.textSecondary }}>
        {checkpointStatus}
      </span>

      {/* Last updated */}
      <span
        className="text-xs flex-shrink-0"
        style={{ color: colors.textMuted }}
      >
        {generatedAt ? `Updated ${relativeTime(generatedAt)}` : 'No data'}
      </span>
    </div>
  )
}
