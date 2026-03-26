import React, { useEffect, useState, useCallback } from 'react'
import PnLFrontier from '../charts/PnLFrontier'
import { CohortProgress } from '../charts/CohortProgress'
import { useAppStore } from '../../store/useAppStore'
import { colors } from '../../theme/colors'
import { api } from '../../lib/api'
import type { PnLPoint } from '../../types/system'

export const PnLScreen: React.FC = () => {
  const cohort = useAppStore((s) => s.cohort)
  const storePnlHistory = useAppStore((s) => s.pnlHistory)

  const [pnlData, setPnlData] = useState<PnLPoint[]>(storePnlHistory)
  const [loading, setLoading] = useState(false)
  const [lastFetched, setLastFetched] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchPnl = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<PnLPoint[] | { data: PnLPoint[] }>('/pnl/history')
      const points = Array.isArray(res) ? res : (res as { data: PnLPoint[] }).data ?? []
      setPnlData(points)
      setLastFetched(new Date())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load P&L data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPnl()
    const interval = setInterval(fetchPnl, 60_000)
    return () => clearInterval(interval)
  }, [fetchPnl])

  // Use local fetched data if available; otherwise fall back to store
  const displayData = pnlData.length > 0 ? pnlData : storePnlHistory

  // Build cohort-filtered data if cohort is set
  const cohortData =
    cohort?.cohort_start_ts != null
      ? displayData.filter((p) => p.ts >= cohort.cohort_start_ts!)
      : undefined

  return (
    <div className="flex flex-col h-full">
      {/* Header row */}
      <div
        className="flex items-center justify-between px-4 py-2 flex-shrink-0"
        style={{ borderBottom: `1px solid ${colors.border}` }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: colors.textPrimary }}>P&L Frontier</span>
        <div className="flex items-center gap-3">
          {error && (
            <span style={{ fontSize: 11, color: colors.loss }}>{error}</span>
          )}
          {lastFetched && !error && (
            <span style={{ fontSize: 11, color: colors.textMuted }}>
              Updated {lastFetched.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          <button
            onClick={fetchPnl}
            disabled={loading}
            style={{
              fontSize: 11,
              color: loading ? colors.textMuted : colors.elasticBlue,
              background: 'none',
              border: 'none',
              cursor: loading ? 'not-allowed' : 'pointer',
              padding: '2px 6px',
            }}
          >
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Chart — 65% */}
      <div style={{ flex: '0 0 65%', minHeight: 0, padding: '8px 4px 4px' }}>
        <PnLFrontier data={displayData} cohortData={cohortData} />
      </div>

      {/* Cohort progress — 35% */}
      <div
        style={{
          flex: '0 0 35%',
          minHeight: 0,
          borderTop: `1px solid ${colors.border}`,
          overflow: 'hidden',
        }}
      >
        <div
          className="flex items-center px-4 py-2"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <span style={{ fontSize: 12, fontWeight: 600, color: colors.textPrimary }}>
            Cohort Progress
          </span>
          {cohort && (
            <span
              style={{
                marginLeft: 8,
                fontSize: 11,
                color: colors.textMuted,
                fontFamily: 'monospace',
              }}
            >
              #{cohort.cohort_id.slice(0, 8)}
            </span>
          )}
        </div>
        <div style={{ height: 'calc(100% - 36px)', overflow: 'hidden' }}>
          <CohortProgress cohort={cohort} />
        </div>
      </div>
    </div>
  )
}
