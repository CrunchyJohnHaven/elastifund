import React, { useEffect, useState } from 'react'
import { GuidanceTerminal } from '../controls/GuidanceTerminal'
import { useAppStore } from '../../store/useAppStore'
import { colors } from '../../theme/colors'
import { api } from '../../lib/api'

interface GuidanceEntry {
  id: string
  text: string
  created_at: string
  improved?: boolean | null
}

interface AutoresearchMeta {
  last_run: string | null
  hypotheses_tested: number | null
  best_delta: number | null
}

function relTime(iso: string): string {
  try {
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
    if (diff < 60) return `${diff}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  } catch {
    return iso
  }
}

export const GuideScreen: React.FC = () => {
  const health = useAppStore((s) => s.health)
  const cohort = useAppStore((s) => s.cohort)

  const [guidanceHistory, setGuidanceHistory] = useState<GuidanceEntry[]>([])
  const [autoresearchMeta, setAutoresearchMeta] = useState<AutoresearchMeta | null>(null)

  useEffect(() => {
    async function fetchHistory() {
      try {
        const res = await api.get<GuidanceEntry[] | { entries: GuidanceEntry[] }>('/guidance/history')
        const entries = Array.isArray(res) ? res : (res as { entries: GuidanceEntry[] }).entries ?? []
        setGuidanceHistory(entries)
      } catch {
        // non-fatal
      }
    }

    async function fetchAutoresearch() {
      try {
        const res = await api.get<AutoresearchMeta>('/autoresearch/meta')
        setAutoresearchMeta(res)
      } catch {
        // non-fatal
      }
    }

    fetchHistory()
    fetchAutoresearch()
  }, [])

  // Build current strategy params from health snapshot
  const strategyParams = health?.deployed_params ?? {}
  const strategyParamEntries = Object.entries(strategyParams)

  return (
    <div className="flex h-full">
      {/* Left — GuidanceTerminal */}
      <div
        style={{
          flex: '0 0 60%',
          minWidth: 0,
          borderRight: `1px solid ${colors.border}`,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            padding: '10px 16px',
            borderBottom: `1px solid ${colors.border}`,
            fontSize: 13,
            fontWeight: 600,
            color: colors.textPrimary,
          }}
        >
          Strategic Guidance
        </div>
        <div style={{ height: 'calc(100% - 41px)', overflow: 'hidden' }}>
          <GuidanceTerminal />
        </div>
      </div>

      {/* Right — context panel */}
      <div
        style={{
          flex: '0 0 40%',
          minWidth: 0,
          overflow: 'auto',
          padding: 16,
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        {/* Current Strategy section */}
        <div
          style={{
            background: colors.bgPanel,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            padding: 14,
          }}
        >
          <div style={{ fontSize: 11, fontWeight: 600, color: colors.textMuted, letterSpacing: '0.06em', marginBottom: 10 }}>
            CURRENT STRATEGY
          </div>
          {strategyParamEntries.length === 0 ? (
            <div style={{ fontSize: 12, color: colors.textMuted }}>No deployed params available</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {strategyParamEntries.map(([key, val]) => (
                <div
                  key={key}
                  style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}
                >
                  <span style={{ color: colors.textSecondary }}>{key}</span>
                  <span style={{ color: colors.textPrimary, fontFamily: 'monospace' }}>{val}</span>
                </div>
              ))}
            </div>
          )}
          {cohort && (
            <div
              style={{
                marginTop: 10,
                paddingTop: 10,
                borderTop: `1px solid ${colors.border}`,
                fontSize: 11,
                color: colors.textMuted,
              }}
            >
              Config hash:{' '}
              <span style={{ fontFamily: 'monospace', color: colors.textSecondary }}>
                {cohort.config_hash?.slice(0, 12) ?? 'N/A'}
              </span>
            </div>
          )}
        </div>

        {/* Last Autoresearch section */}
        <div
          style={{
            background: colors.bgPanel,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            padding: 14,
          }}
        >
          <div style={{ fontSize: 11, fontWeight: 600, color: colors.textMuted, letterSpacing: '0.06em', marginBottom: 10 }}>
            LAST AUTORESEARCH
          </div>
          {autoresearchMeta ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, fontSize: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: colors.textSecondary }}>Last run</span>
                <span style={{ color: colors.textPrimary }}>
                  {autoresearchMeta.last_run ? relTime(autoresearchMeta.last_run) : 'Never'}
                </span>
              </div>
              {autoresearchMeta.hypotheses_tested != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: colors.textSecondary }}>Hypotheses tested</span>
                  <span style={{ color: colors.textPrimary }}>{autoresearchMeta.hypotheses_tested}</span>
                </div>
              )}
              {autoresearchMeta.best_delta != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: colors.textSecondary }}>Best delta</span>
                  <span
                    style={{
                      color: autoresearchMeta.best_delta >= 0 ? colors.profit : colors.loss,
                      fontFamily: 'monospace',
                    }}
                  >
                    {autoresearchMeta.best_delta >= 0 ? '+' : ''}$
                    {autoresearchMeta.best_delta.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: colors.textMuted }}>No autoresearch data</div>
          )}
        </div>

        {/* Guidance Impact section */}
        <div
          style={{
            background: colors.bgPanel,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            padding: 14,
            flex: 1,
            overflow: 'auto',
          }}
        >
          <div style={{ fontSize: 11, fontWeight: 600, color: colors.textMuted, letterSpacing: '0.06em', marginBottom: 10 }}>
            GUIDANCE IMPACT
          </div>
          {guidanceHistory.length === 0 ? (
            <div style={{ fontSize: 12, color: colors.textMuted }}>
              No past guidance entries
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {guidanceHistory.slice(0, 10).map((entry) => (
                <div
                  key={entry.id}
                  style={{
                    borderLeft: `2px solid ${
                      entry.improved === true
                        ? colors.profit
                        : entry.improved === false
                        ? colors.loss
                        : colors.border
                    }`,
                    paddingLeft: 10,
                    paddingTop: 2,
                    paddingBottom: 2,
                  }}
                >
                  <div style={{ fontSize: 11, color: colors.textMuted, marginBottom: 3 }}>
                    {relTime(entry.created_at)}
                    {entry.improved === true && (
                      <span style={{ color: colors.profit, marginLeft: 6 }}>+improved</span>
                    )}
                    {entry.improved === false && (
                      <span style={{ color: colors.loss, marginLeft: 6 }}>no improvement</span>
                    )}
                  </div>
                  <div
                    style={{
                      fontSize: 12,
                      color: colors.textSecondary,
                      overflow: 'hidden',
                      display: '-webkit-box',
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical' as const,
                    }}
                  >
                    {entry.text}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
