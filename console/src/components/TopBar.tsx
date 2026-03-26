import React from 'react'
import { Server } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import { colors } from '../theme/colors'
import { formatUSD, formatPct } from '../lib/format'

const JOB_ABBREV: Record<string, string> = {
  autoresearch: 'AR',
  health: 'HC',
  cohort: 'CO',
  montecarlo: 'MC',
  filter_econ: 'FE',
}

function abbrev(id: string): string {
  const lower = id.toLowerCase()
  for (const [key, val] of Object.entries(JOB_ABBREV)) {
    if (lower.includes(key)) return val
  }
  return id.slice(0, 2).toUpperCase()
}

function JobBadge({ job }: { job: { id: string; last_result: 'success' | 'error' | null; next_run: string } }) {
  const dotColor =
    job.last_result === 'success'
      ? '#4ADE80'
      : job.last_result === 'error'
      ? '#FB7185'
      : '#FBBF24'

  const nextRunFormatted = (() => {
    try {
      const d = new Date(job.next_run)
      return `Next: ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    } catch {
      return 'Next: unknown'
    }
  })()

  return (
    <div
      className="relative group flex items-center gap-1 px-2 py-0.5 rounded text-xs cursor-default"
      style={{
        background: 'rgba(255,255,255,0.05)',
        border: `1px solid ${colors.border}`,
        color: colors.textSecondary,
      }}
    >
      <span
        className="inline-block w-1.5 h-1.5 rounded-full flex-shrink-0"
        style={{ background: dotColor }}
      />
      <span>{abbrev(job.id)}</span>
      {/* Tooltip */}
      <div
        className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2 py-1 rounded text-xs whitespace-nowrap pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity z-50"
        style={{
          background: colors.bgPanel,
          border: `1px solid ${colors.border}`,
          color: colors.textPrimary,
        }}
      >
        <div className="font-medium">{job.id}</div>
        <div style={{ color: colors.textMuted }}>{nextRunFormatted}</div>
      </div>
    </div>
  )
}

export const TopBar: React.FC = () => {
  const connectionStatus = useAppStore((s) => s.connectionStatus)
  const cohort = useAppStore((s) => s.cohort)
  const schedulerJobs = useAppStore((s) => s.schedulerJobs)
  const vpsStatus = useAppStore((s) => s.vpsStatus)

  const isOnline = connectionStatus === 'connected'
  const pnl = cohort?.gross_pnl_usd ?? 0
  const pnlPositive = pnl >= 0

  const vpsState = vpsStatus?.jj_live ?? 'unknown'
  const vpsColor =
    vpsState === 'active'
      ? colors.profit
      : vpsState === 'failed' || vpsState === 'inactive'
      ? colors.loss
      : colors.neutral

  return (
    <div
      className="flex items-center h-16 px-4 gap-6 flex-shrink-0 w-full"
      style={{
        background: colors.bgElevated,
        borderBottom: `1px solid ${colors.border}`,
      }}
    >
      {/* Connection status */}
      <div className="flex items-center gap-2 min-w-[90px]">
        <span
          className="inline-block w-2 h-2 rounded-full flex-shrink-0"
          style={{ background: isOnline ? '#4ADE80' : '#FB7185' }}
        />
        <span
          className="text-sm font-medium"
          style={{ color: isOnline ? '#4ADE80' : '#FB7185' }}
        >
          {isOnline ? 'Online' : connectionStatus === 'connecting' ? 'Connecting' : 'Offline'}
        </span>
      </div>

      {/* P&L */}
      <div className="flex flex-col min-w-[130px]">
        <span
          className="text-base font-semibold tabular-nums"
          style={{ color: pnlPositive ? colors.profit : colors.loss }}
        >
          {formatUSD(pnl)}
        </span>
        <span className="text-xs" style={{ color: colors.textMuted }}>
          {cohort?.resolved_down_fills ?? 0} fills
          {cohort?.win_rate != null
            ? ` · ${formatPct(cohort.win_rate)}`
            : ''}
        </span>
      </div>

      {/* Scheduler jobs */}
      <div className="flex items-center gap-1.5 flex-1">
        <span className="text-xs mr-1" style={{ color: colors.textMuted }}>
          Loops:
        </span>
        {schedulerJobs.length === 0 ? (
          <span className="text-xs" style={{ color: colors.textMuted }}>
            No jobs
          </span>
        ) : (
          schedulerJobs.map((job) => <JobBadge key={job.id} job={job} />)
        )}
      </div>

      {/* VPS status */}
      <div className="flex items-center gap-2">
        <Server size={14} style={{ color: vpsColor }} />
        <span className="text-sm" style={{ color: vpsColor }}>
          {vpsState.charAt(0).toUpperCase() + vpsState.slice(1)}
        </span>
      </div>
    </div>
  )
}
