import { useMemo } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts'
import { colors } from '../../theme/colors'

// ─── Types ────────────────────────────────────────────────────────────────────

interface DataPoint {
  ts: number
  cumulative_pnl: number
  trade_count: number
  win_count: number
}

interface CohortPoint {
  ts: number
  cumulative_pnl: number
}

interface Props {
  data: DataPoint[]
  cohortData?: CohortPoint[]
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatTs(ts: number, isIntraday: boolean): string {
  const d = new Date(ts * 1000)
  if (isIntraday) {
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function formatUsd(val: number): string {
  return `$${val >= 0 ? '' : '-'}${Math.abs(val).toFixed(2)}`
}

// ─── Tooltip content ─────────────────────────────────────────────────────────

interface TooltipPayloadItem {
  name: string
  value: number
  color: string
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayloadItem[]
  label?: number
  isIntraday: boolean
}

const CustomTooltip = ({ active, payload, label, isIntraday }: CustomTooltipProps) => {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div style={{
      background: colors.bgPanel,
      border: `1px solid rgba(255,255,255,0.12)`,
      borderRadius: 6,
      padding: '8px 12px',
      fontSize: 12,
      color: colors.textPrimary,
    }}>
      <div style={{ marginBottom: 4, color: colors.textSecondary }}>
        {label !== undefined ? formatTs(label, isIntraday) : ''}
      </div>
      {payload.map((p) => (
        <div key={p.name} style={{ color: p.color, marginBottom: 2 }}>
          {p.name}: {formatUsd(p.value)}
        </div>
      ))}
    </div>
  )
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function PnLFrontier({ data, cohortData }: Props) {
  const isIntraday = useMemo(() => {
    if (data.length < 2) return false
    const span = (data[data.length - 1].ts - data[0].ts) / 3600
    return span < 24
  }, [data])

  const lastPnl = data.length > 0 ? data[data.length - 1].cumulative_pnl : 0
  const lineColor = lastPnl >= 0 ? colors.profit : colors.loss

  // Merge main data + cohort data by ts for recharts
  const merged = useMemo(() => {
    const map = new Map<number, { ts: number; all_pnl?: number; cohort_pnl?: number }>()
    data.forEach(d => map.set(d.ts, { ts: d.ts, all_pnl: d.cumulative_pnl }))
    cohortData?.forEach(d => {
      const existing = map.get(d.ts) ?? { ts: d.ts }
      existing.cohort_pnl = d.cumulative_pnl
      map.set(d.ts, existing)
    })
    return Array.from(map.values()).sort((a, b) => a.ts - b.ts)
  }, [data, cohortData])

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={merged} margin={{ top: 8, right: 16, left: 8, bottom: 4 }}>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="rgba(255,255,255,0.05)"
          vertical={false}
        />
        <XAxis
          dataKey="ts"
          tickFormatter={(ts: number) => formatTs(ts, isIntraday)}
          tick={{ fill: colors.textSecondary, fontSize: 11 }}
          axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
          tickLine={false}
        />
        <YAxis
          tickFormatter={(val: number) => formatUsd(val)}
          tick={{ fill: colors.textSecondary, fontSize: 11 }}
          axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
          tickLine={false}
          width={64}
        />
        <Tooltip
          content={({ active, payload, label }) => (
            <CustomTooltip
              active={active}
              payload={payload as TooltipPayloadItem[] | undefined}
              label={label as number | undefined}
              isIntraday={isIntraday}
            />
          )}
        />
        <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" strokeDasharray="4 4" />
        <Line
          type="monotone"
          dataKey="all_pnl"
          name="All P&L"
          stroke={lineColor}
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 3, fill: lineColor }}
          connectNulls
        />
        {cohortData && cohortData.length > 0 && (
          <Line
            type="monotone"
            dataKey="cohort_pnl"
            name="Cohort P&L"
            stroke={colors.teal}
            strokeWidth={1.5}
            strokeDasharray="5 5"
            dot={false}
            activeDot={{ r: 3, fill: colors.teal }}
            connectNulls
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  )
}
