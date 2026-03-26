import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { colors } from '../../theme/colors'
import type { SafetyEvent } from '../../types/events'

interface SafetyFeedProps {
  events: SafetyEvent[]
}

const TYPE_LABELS: Record<string, string> = {
  cap_breach: 'Cap Breach',
  up_live_attempt: 'UP Live Attempt',
  config_mismatch: 'Config Mismatch',
  restart_loop: 'Restart Loop',
  duplicate_window: 'Duplicate Window',
}

function humanizeType(t: string): string {
  return (
    TYPE_LABELS[t] ??
    t
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ')
  )
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

function isNew(iso: string): boolean {
  try {
    return Date.now() - new Date(iso).getTime() < 10_000
  } catch {
    return false
  }
}

export const SafetyFeed: React.FC<SafetyFeedProps> = ({ events }) => {
  if (events.length === 0) {
    return (
      <div className="px-4 py-6 text-xs text-center" style={{ color: colors.textMuted }}>
        No safety events.
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      <AnimatePresence initial={false}>
        {events.map((e, i) => {
          const fresh = isNew(e.timestamp)
          return (
            <motion.div
              key={`${e.type}-${e.timestamp}-${i}`}
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
              className="px-3 py-2.5 flex items-start gap-2"
              style={{
                borderBottom: `1px solid ${colors.border}`,
                background: fresh ? 'rgba(251,113,133,0.08)' : 'transparent',
              }}
            >
              {/* Alert dot — pulses on new events */}
              <div className="flex-shrink-0 mt-0.5 relative">
                <span
                  className="inline-block w-2 h-2 rounded-full"
                  style={{ background: colors.loss }}
                />
                {fresh && (
                  <motion.span
                    className="absolute inset-0 rounded-full"
                    style={{ background: colors.loss }}
                    animate={{ opacity: [0.8, 0], scale: [1, 2] }}
                    transition={{ duration: 1.2, repeat: Infinity }}
                  />
                )}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="text-xs font-bold"
                    style={{ color: colors.loss }}
                  >
                    {humanizeType(e.type)}
                  </span>
                  <span className="text-xs flex-shrink-0" style={{ color: colors.textMuted }}>
                    {relTime(e.timestamp)}
                  </span>
                </div>
                <div
                  className="text-xs mt-0.5"
                  style={{ color: colors.textSecondary }}
                >
                  {e.details}
                </div>
              </div>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
