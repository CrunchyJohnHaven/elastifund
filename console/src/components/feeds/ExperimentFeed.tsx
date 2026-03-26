import React from 'react'
import { colors } from '../../theme/colors'
import type { HypothesisResult } from '../../types/hypothesis'

interface ExperimentFeedProps {
  results: HypothesisResult[]
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

const VERDICT_STYLE: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  keep: {
    bg: 'rgba(74,222,128,0.12)',
    text: '#4ADE80',
    label: 'keep',
  },
  discard: {
    bg: 'rgba(251,113,133,0.12)',
    text: '#FB7185',
    label: 'discard',
  },
  crash: {
    bg: 'rgba(251,191,36,0.12)',
    text: '#FBBF24',
    label: 'crash',
  },
}

export const ExperimentFeed: React.FC<ExperimentFeedProps> = ({ results }) => {
  const visible = results.slice(0, 50)

  if (visible.length === 0) {
    return (
      <div className="px-4 py-6 text-xs text-center" style={{ color: colors.textMuted }}>
        No experiment results yet.
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      {visible.map((r, i) => {
        const pnlPos = r.shadow_pnl_delta >= 0
        const style = VERDICT_STYLE[r.verdict] ?? VERDICT_STYLE.crash
        return (
          <div
            key={i}
            className="px-3 py-2.5"
            style={{ borderBottom: `1px solid ${colors.border}` }}
          >
            <div className="flex items-center gap-2">
              {/* Hypothesis ID */}
              <span
                className="font-mono text-xs"
                style={{ color: colors.textMuted }}
              >
                {r.hypothesis_id.slice(0, 8)}
              </span>

              {/* Shadow P&L delta */}
              <span
                className="font-medium text-xs tabular-nums"
                style={{ color: pnlPos ? colors.profit : colors.loss }}
              >
                {pnlPos ? '+' : ''}${r.shadow_pnl_delta.toFixed(2)}
              </span>

              {/* Verdict badge */}
              <span
                className="ml-auto px-1.5 py-0.5 rounded text-xs font-medium"
                style={{ background: style.bg, color: style.text }}
              >
                {style.label}
              </span>

              {/* Timestamp */}
              <span className="text-xs" style={{ color: colors.textMuted }}>
                {relTime(r.tested_at)}
              </span>
            </div>

            {/* Params changed */}
            {r.params_changed.length > 0 && (
              <div
                className="mt-1 text-xs truncate"
                style={{ color: colors.textMuted }}
              >
                {r.params_changed.join(', ')}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
