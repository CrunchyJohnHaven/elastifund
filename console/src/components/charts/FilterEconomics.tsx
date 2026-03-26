import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  ReferenceLine,
  LabelList,
} from 'recharts'
import { colors } from '../../theme/colors'

// ─── Types ────────────────────────────────────────────────────────────────────

interface FilterData {
  net_value: number
  blocked_count: number
  blocked_pnl: number
}

interface Props {
  data: Record<string, FilterData> | null
}

interface ChartRow {
  name: string
  net_value: number
  blocked_count: number
  blocked_pnl: number
}

// ─── Tooltip ─────────────────────────────────────────────────────────────────

interface TooltipPayloadItem {
  payload: ChartRow
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayloadItem[]
}

const CustomTooltip = ({ active, payload }: CustomTooltipProps) => {
  if (!active || !payload || payload.length === 0) return null
  const d = payload[0].payload
  return (
    <div style={{
      background: colors.bgPanel,
      border: `1px solid rgba(255,255,255,0.12)`,
      borderRadius: 6,
      padding: '8px 12px',
      fontSize: 12,
      color: colors.textPrimary,
      lineHeight: 1.7,
    }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{d.name}</div>
      <div style={{ color: d.net_value >= 0 ? colors.profit : colors.loss }}>
        Net value: {d.net_value >= 0 ? '+' : ''}${d.net_value.toFixed(2)}
      </div>
      <div style={{ color: colors.textSecondary }}>
        Blocked: {d.blocked_count} trades (${d.blocked_pnl.toFixed(2)})
      </div>
    </div>
  )
}

// ─── Bar label ───────────────────────────────────────────────────────────────

interface BarLabelProps {
  x?: number
  y?: number
  width?: number
  height?: number
  value?: number
}

const BarLabel = ({ x = 0, y = 0, width = 0, height = 0, value = 0 }: BarLabelProps) => {
  const isPositive = value >= 0
  const lx = isPositive ? x + width + 4 : x + width - 4
  const anchor = isPositive ? 'start' : 'end'
  return (
    <text
      x={lx}
      y={y + height / 2}
      textAnchor={anchor}
      dominantBaseline="central"
      fontSize={11}
      fill={isPositive ? colors.profit : colors.loss}
    >
      {isPositive ? '+' : ''}${value.toFixed(2)}
    </text>
  )
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function FilterEconomics({ data }: Props) {
  if (!data) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        flexDirection: 'column',
        gap: 8,
        color: colors.textSecondary,
        fontSize: 14,
      }}>
        <div>No filter economics data</div>
        <div style={{ fontSize: 12, color: colors.textMuted }}>
          Data populates after strategy runs complete
        </div>
      </div>
    )
  }

  const chartData: ChartRow[] = Object.entries(data).map(([name, stats]) => ({
    name,
    net_value: stats.net_value,
    blocked_count: stats.blocked_count,
    blocked_pnl: stats.blocked_pnl,
  }))

  if (chartData.length === 0) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        color: colors.textSecondary,
        fontSize: 14,
      }}>
        No filter economics data
      </div>
    )
  }

  const absMax = Math.max(...chartData.map(d => Math.abs(d.net_value)), 0.01)
  const domain: [number, number] = [-absMax * 1.3, absMax * 1.3]

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={chartData}
        layout="vertical"
        margin={{ top: 8, right: 64, bottom: 8, left: 8 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
        <XAxis
          type="number"
          domain={domain}
          tickFormatter={(v: number) => `$${v.toFixed(0)}`}
          tick={{ fill: colors.textSecondary, fontSize: 11 }}
          axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fill: colors.textSecondary, fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={120}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
        <ReferenceLine x={0} stroke="rgba(255,255,255,0.2)" strokeWidth={1} />
        <Bar dataKey="net_value" radius={[0, 3, 3, 0]} maxBarSize={32}>
          <LabelList content={<BarLabel />} />
          {chartData.map((entry, index) => (
            <Cell
              key={index}
              fill={entry.net_value >= 0 ? colors.profit : colors.loss}
              fillOpacity={0.75}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// Named export for backwards compat
export { FilterEconomics }
