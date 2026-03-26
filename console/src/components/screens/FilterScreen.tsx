import React, { useEffect, useState } from 'react'
import FilterEconomics from '../charts/FilterEconomics'
import { colors } from '../../theme/colors'
import { api } from '../../lib/api'

interface FilterData {
  net_value: number
  blocked_count: number
  blocked_pnl: number
}

type FilterApiResponse = Record<string, FilterData>

type TimePeriod = '24h' | '7d' | 'cohort'

const TIME_PERIODS: { key: TimePeriod; label: string }[] = [
  { key: '24h', label: '24h' },
  { key: '7d', label: '7d' },
  { key: 'cohort', label: 'Cohort' },
]

export const FilterScreen: React.FC = () => {
  const [filterData, setFilterData] = useState<FilterApiResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [period, setPeriod] = useState<TimePeriod>('cohort')

  useEffect(() => {
    async function fetchFilters() {
      setLoading(true)
      setError(null)
      try {
        const res = await api.get<FilterApiResponse>('/filters')
        setFilterData(res)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Failed to load filter data')
      } finally {
        setLoading(false)
      }
    }
    fetchFilters()
  }, [])

  const filterEntries = filterData ? Object.entries(filterData) : []

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-2 flex-shrink-0"
        style={{ borderBottom: `1px solid ${colors.border}` }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: colors.textPrimary }}>
          Filter Economics
        </span>

        {/* Time period toggle */}
        <div className="flex gap-1">
          {TIME_PERIODS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setPeriod(key)}
              style={{
                fontSize: 11,
                padding: '3px 10px',
                borderRadius: 4,
                border: `1px solid ${period === key ? colors.elasticBlue : colors.border}`,
                background: period === key ? 'rgba(11,100,221,0.15)' : 'transparent',
                color: period === key ? colors.textPrimary : colors.textMuted,
                cursor: 'pointer',
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Left — waterfall chart */}
        <div style={{ flex: '0 0 60%', borderRight: `1px solid ${colors.border}`, overflow: 'hidden', padding: '8px 4px' }}>
          {loading ? (
            <div className="flex items-center justify-center h-full" style={{ color: colors.textMuted, fontSize: 13 }}>
              Loading...
            </div>
          ) : error ? (
            <div className="flex items-center justify-center h-full" style={{ color: colors.loss, fontSize: 12 }}>
              {error}
            </div>
          ) : (
            <FilterEconomics data={filterData} />
          )}
        </div>

        {/* Right — per-filter detail cards */}
        <div style={{ flex: '0 0 40%', overflow: 'auto', padding: '12px 16px' }}>
          <div style={{ fontSize: 11, color: colors.textMuted, marginBottom: 8, fontWeight: 600, letterSpacing: '0.05em' }}>
            PER-FILTER BREAKDOWN
          </div>
          {filterEntries.length === 0 && !loading && (
            <div style={{ fontSize: 12, color: colors.textMuted }}>
              {error ? 'Error loading data' : 'No filter data yet'}
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {filterEntries.map(([name, stats]) => {
              const netPositive = stats.net_value >= 0
              return (
                <div
                  key={name}
                  style={{
                    background: colors.bgPanel,
                    border: `1px solid ${colors.border}`,
                    borderRadius: 6,
                    padding: '12px 16px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: colors.textPrimary }}>
                      {name}
                    </span>
                    <span
                      style={{
                        fontSize: 13,
                        fontWeight: 700,
                        color: netPositive ? colors.profit : colors.loss,
                        fontFamily: 'monospace',
                      }}
                    >
                      {netPositive ? '+' : ''}${stats.net_value.toFixed(2)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 16, fontSize: 11, color: colors.textSecondary }}>
                    <div>
                      <span style={{ color: colors.textMuted }}>Blocked: </span>
                      {stats.blocked_count} trades
                    </div>
                    <div>
                      <span style={{ color: colors.textMuted }}>Blocked P&L: </span>
                      <span style={{ color: stats.blocked_pnl >= 0 ? colors.profit : colors.loss }}>
                        ${stats.blocked_pnl.toFixed(2)}
                      </span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
