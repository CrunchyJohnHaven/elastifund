import React, { useState } from 'react'
import { CheckCircle2, XCircle, ChevronDown, ChevronUp } from 'lucide-react'
import { colors } from '../../theme/colors'
import type { DeployStatus } from '../../types/system'

interface DeployLogProps {
  entries: DeployStatus[]
}

function formatTs(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

const DeployEntry: React.FC<{ entry: DeployStatus }> = ({ entry }) => {
  const [expanded, setExpanded] = useState(false)
  const preview = entry.stdout
    ? entry.stdout.trim().split('\n').slice(-3).join('\n')
    : null
  const hasOutput = !!(entry.stdout || entry.stderr)

  return (
    <div
      className="px-3 py-2.5"
      style={{ borderBottom: `1px solid ${colors.border}` }}
    >
      <div className="flex items-center gap-2">
        {entry.success ? (
          <CheckCircle2 size={14} style={{ color: colors.profit, flexShrink: 0 }} />
        ) : (
          <XCircle size={14} style={{ color: colors.loss, flexShrink: 0 }} />
        )}

        <span
          className="text-xs font-medium flex-1 truncate"
          style={{ color: colors.textPrimary }}
        >
          {entry.profile}
        </span>

        <span className="text-xs flex-shrink-0" style={{ color: colors.textMuted }}>
          {formatTs(entry.timestamp)}
        </span>

        {hasOutput && (
          <button
            onClick={() => setExpanded((v) => !v)}
            style={{
              color: colors.textMuted,
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: 0,
              display: 'flex',
              alignItems: 'center',
            }}
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        )}
      </div>

      {/* Preview (collapsed) */}
      {!expanded && preview && (
        <div
          className="mt-1 font-mono text-xs truncate"
          style={{ color: colors.textMuted }}
        >
          {preview.split('\n').slice(-1)[0]}
        </div>
      )}

      {/* Full output (expanded) */}
      {expanded && hasOutput && (
        <div
          className="mt-2 rounded p-2 font-mono text-xs leading-relaxed whitespace-pre-wrap overflow-x-auto"
          style={{
            background: '#020408',
            color: '#c8d3f5',
            border: `1px solid ${colors.border}`,
            maxHeight: 200,
            overflowY: 'auto',
          }}
        >
          {entry.stdout && <div>{entry.stdout}</div>}
          {entry.stderr && (
            <div style={{ color: colors.loss }}>{entry.stderr}</div>
          )}
        </div>
      )}
    </div>
  )
}

export const DeployLog: React.FC<DeployLogProps> = ({ entries }) => {
  if (entries.length === 0) {
    return (
      <div className="px-4 py-6 text-xs text-center" style={{ color: colors.textMuted }}>
        No deploy history.
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      {entries.map((entry, i) => (
        <DeployEntry key={`${entry.timestamp}-${i}`} entry={entry} />
      ))}
    </div>
  )
}
