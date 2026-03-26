import React from 'react'
import { colors } from '../../theme/colors'
import type { MutationEvent } from '../../types/events'

interface MutationFeedProps {
  events: MutationEvent[]
}

function relTime(iso: string): string {
  try {
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
    if (diff < 60) return `${diff}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    return `${Math.floor(diff / 3600)}h ago`
  } catch {
    return iso
  }
}

export const MutationFeed: React.FC<MutationFeedProps> = ({ events }) => {
  if (events.length === 0) {
    return (
      <div className="px-4 py-6 text-xs text-center" style={{ color: colors.textMuted }}>
        No mutations yet.
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      {events.map((m, i) => {
        const isPromoted = m.type === 'promoted'
        return (
          <div
            key={`${m.mutation_id}-${i}`}
            className="px-3 py-2.5"
            style={{ borderBottom: `1px solid ${colors.border}` }}
          >
            <div className="flex items-center gap-2">
              {/* Badge */}
              <span
                className="px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0"
                style={{
                  background: isPromoted
                    ? 'rgba(74,222,128,0.12)'
                    : 'rgba(251,113,133,0.12)',
                  color: isPromoted ? colors.promoted : colors.killed,
                }}
              >
                {isPromoted ? 'Promoted' : 'Reverted'}
              </span>

              {/* Mutation ID */}
              <span
                className="font-mono text-xs flex-1 truncate"
                style={{ color: colors.textSecondary }}
              >
                {m.mutation_id.slice(0, 16)}
              </span>

              {/* Timestamp */}
              <span className="text-xs flex-shrink-0" style={{ color: colors.textMuted }}>
                {relTime(m.timestamp)}
              </span>
            </div>

            {/* Config hash */}
            <div
              className="mt-0.5 text-xs font-mono truncate"
              style={{ color: colors.textMuted }}
            >
              {m.config_hash.slice(0, 12)}
            </div>

            {/* Reason (on reverts) */}
            {!isPromoted && m.reason && (
              <div
                className="mt-1 text-xs"
                style={{ color: colors.textSecondary }}
              >
                {m.reason}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
