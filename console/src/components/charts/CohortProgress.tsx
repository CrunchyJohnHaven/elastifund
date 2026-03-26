import { colors } from '../../theme/colors'
import type { CohortReport } from '../../types/cohort'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Props {
  cohort: CohortReport | null
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function recommendationLabel(rec: CohortReport['recommendation']): string {
  switch (rec) {
    case 'awaiting_data':         return 'Awaiting Data'
    case 'insufficient_data':     return 'Insufficient Data'
    case 'continue_collecting':   return 'Continue Collecting'
    case 'positive_first_cohort': return 'Positive First Cohort'
    case 'kill':                  return 'Kill'
    default:                      return rec
  }
}

function recommendationColor(rec: CohortReport['recommendation']): string {
  switch (rec) {
    case 'positive_first_cohort': return colors.profit
    case 'kill':                  return colors.loss
    case 'continue_collecting':   return colors.elasticBlue
    default:                      return colors.neutral
  }
}

function formatPnl(val: number): string {
  const sign = val >= 0 ? '+' : ''
  return `${sign}$${val.toFixed(2)}`
}

function formatWinRate(wr: number | null): string {
  if (wr === null) return 'N/A'
  return `${(wr * 100).toFixed(1)}%`
}

// ─── Sub-components ───────────────────────────────────────────────────────────

interface MetricCardProps {
  label: string
  value: string
  valueColor?: string
  sub?: string
}

function MetricCard({ label, value, valueColor, sub }: MetricCardProps) {
  return (
    <div style={{
      background: colors.bgElevated,
      border: `1px solid rgba(255,255,255,0.07)`,
      borderRadius: 8,
      padding: '10px 12px',
      display: 'flex',
      flexDirection: 'column',
      gap: 2,
    }}>
      <div style={{
        fontSize: 10,
        color: colors.textSecondary,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
      }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color: valueColor ?? colors.textPrimary, lineHeight: 1.2 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: colors.textSecondary }}>
          {sub}
        </div>
      )}
    </div>
  )
}

function ProgressRing({ value, max }: { value: number; max: number }) {
  const r = 18
  const circ = 2 * Math.PI * r
  const frac = max > 0 ? Math.min(1, value / max) : 0
  const dash = frac * circ
  return (
    <svg width={44} height={44} style={{ flexShrink: 0 }}>
      <circle cx={22} cy={22} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={3} />
      <circle
        cx={22} cy={22} r={r}
        fill="none"
        stroke={colors.elasticBlue}
        strokeWidth={3}
        strokeDasharray={`${dash} ${circ}`}
        strokeLinecap="round"
        transform="rotate(-90 22 22)"
      />
      <text
        x={22} y={22}
        textAnchor="middle"
        dominantBaseline="central"
        fill={colors.textPrimary}
        fontSize={10}
        fontWeight={700}
      >
        {value}
      </text>
    </svg>
  )
}

function BigProgressBar({ value, label }: { value: number; label: string }) {
  const total = 50
  const checkpoints = [10, 20, 30, 40, 50]
  const pct = Math.min(100, (value / total) * 100)
  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 11, color: colors.textSecondary }}>{label}</span>
        <span style={{ fontSize: 11, color: colors.textPrimary, fontWeight: 600 }}>
          {value} / {total}
        </span>
      </div>
      <div style={{ position: 'relative', height: 10, background: 'rgba(255,255,255,0.06)', borderRadius: 5 }}>
        <div style={{
          position: 'absolute',
          left: 0, top: 0,
          width: `${pct}%`,
          height: '100%',
          background: colors.elasticBlue,
          borderRadius: 5,
          transition: 'width 0.4s ease',
        }} />
        {checkpoints.map(cp => (
          <div
            key={cp}
            style={{
              position: 'absolute',
              left: `${(cp / total) * 100}%`,
              top: -4,
              width: 1,
              height: 18,
              background: 'rgba(255,255,255,0.22)',
              transform: 'translateX(-50%)',
            }}
          />
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
        {checkpoints.map(cp => (
          <span key={cp} style={{ fontSize: 9, color: colors.textSecondary }}>{cp}</span>
        ))}
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function CohortProgress({ cohort }: Props) {
  if (!cohort) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        color: colors.textSecondary,
        fontSize: 14,
      }}>
        No cohort data
      </div>
    )
  }

  const winRateColor =
    cohort.win_rate === null ? colors.neutral :
    cohort.win_rate >= 0.55  ? colors.profit :
    cohort.win_rate >= 0.5   ? colors.warning : colors.loss

  const pnlColor = cohort.gross_pnl_usd >= 0 ? colors.profit : colors.loss

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%', overflow: 'auto' }}>
      {/* 2×3 metric grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>

        {/* Fills with ring */}
        <div style={{
          background: colors.bgElevated,
          border: `1px solid rgba(255,255,255,0.07)`,
          borderRadius: 8,
          padding: '10px 12px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}>
          <ProgressRing value={cohort.resolved_down_fills} max={50} />
          <div>
            <div style={{ fontSize: 10, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Fills
            </div>
            <div style={{ fontSize: 16, fontWeight: 700, color: colors.textPrimary }}>
              {cohort.resolved_down_fills} / 50
            </div>
          </div>
        </div>

        {/* Win Rate */}
        <MetricCard
          label="Win Rate"
          value={formatWinRate(cohort.win_rate)}
          valueColor={winRateColor}
          sub={`${cohort.wins}W / ${cohort.losses}L`}
        />

        {/* Gross P&L */}
        <MetricCard
          label="Gross P&L"
          value={formatPnl(cohort.gross_pnl_usd)}
          valueColor={pnlColor}
        />

        {/* Avg Entry */}
        <MetricCard
          label="Avg Entry"
          value={cohort.avg_entry_price !== null ? cohort.avg_entry_price.toFixed(3) : 'N/A'}
        />

        {/* Fill Rate */}
        <MetricCard
          label="Fill Rate"
          value={cohort.fill_rate !== null ? `${(cohort.fill_rate * 100).toFixed(1)}%` : 'N/A'}
        />

        {/* Recommendation */}
        <div style={{
          background: colors.bgElevated,
          border: `1px solid rgba(255,255,255,0.07)`,
          borderRadius: 8,
          padding: '10px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
        }}>
          <div style={{ fontSize: 10, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Recommendation
          </div>
          <div style={{
            display: 'inline-block',
            padding: '3px 8px',
            borderRadius: 4,
            background: `${recommendationColor(cohort.recommendation)}20`,
            border: `1px solid ${recommendationColor(cohort.recommendation)}55`,
            color: recommendationColor(cohort.recommendation),
            fontSize: 11,
            fontWeight: 600,
            alignSelf: 'flex-start',
          }}>
            {recommendationLabel(cohort.recommendation)}
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <div style={{
        background: colors.bgElevated,
        border: `1px solid rgba(255,255,255,0.07)`,
        borderRadius: 8,
        padding: '12px 14px',
      }}>
        <BigProgressBar value={cohort.resolved_down_fills} label="Cohort Progress" />
      </div>
    </div>
  )
}

// Named export for backwards compat with any existing imports
export { CohortProgress }
