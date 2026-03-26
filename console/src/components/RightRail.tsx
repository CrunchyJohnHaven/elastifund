import React, { useRef } from 'react'
import { Activity, Skull, Rocket, Database, Loader2 } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import { colors } from '../theme/colors'
import { api } from '../lib/api'
import { formatUSD } from '../lib/format'
import type { FillRecord, MutationEvent, SafetyEvent } from '../types/events'
import type { DeployStatus } from '../types/system'

// ─── Unified event types ──────────────────────────────────────────────────────

type UnifiedEvent =
  | { kind: 'fill'; ts: number; data: FillRecord }
  | { kind: 'mutation'; ts: number; data: MutationEvent }
  | { kind: 'safety'; ts: number; data: SafetyEvent }

function toUnified(
  fills: FillRecord[],
  mutations: MutationEvent[],
  safety: SafetyEvent[]
): UnifiedEvent[] {
  const items: UnifiedEvent[] = [
    ...fills.map((f): UnifiedEvent => ({ kind: 'fill', ts: f.window_start_ts * 1000, data: f })),
    ...mutations.map((m): UnifiedEvent => ({
      kind: 'mutation',
      ts: new Date(m.timestamp).getTime(),
      data: m,
    })),
    ...safety.map((e): UnifiedEvent => ({
      kind: 'safety',
      ts: new Date(e.timestamp).getTime(),
      data: e,
    })),
  ]
  items.sort((a, b) => b.ts - a.ts)
  return items.slice(0, 100)
}

function relTime(ts: number): string {
  const diff = Math.floor((Date.now() - ts) / 1000)
  if (diff < 60) return `${diff}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}m`
  return `${Math.floor(diff / 3600)}h`
}

// ─── Event card renderers ─────────────────────────────────────────────────────

const FillCard: React.FC<{ f: FillRecord }> = ({ f }) => {
  const isDown = f.direction?.toLowerCase().includes('down')
  const pnl = f.pnl_usd
  return (
    <div
      className="flex items-center gap-2 px-3 py-2 text-xs"
      style={{ borderBottom: `1px solid ${colors.border}` }}
    >
      <span style={{ color: isDown ? colors.testing : colors.teal }}>
        {isDown ? '▼' : '▲'}
      </span>
      <span style={{ color: colors.textSecondary }}>${f.order_price?.toFixed(2) ?? '—'}</span>
      {pnl != null ? (
        <span
          className="ml-auto font-medium tabular-nums"
          style={{ color: pnl >= 0 ? colors.profit : colors.loss }}
        >
          {formatUSD(pnl)}
        </span>
      ) : (
        <span className="ml-auto" style={{ color: colors.textMuted }}>pending</span>
      )}
      <span style={{ color: colors.textMuted }}>{relTime(f.window_start_ts * 1000)}</span>
    </div>
  )
}

const MutationCard: React.FC<{ m: MutationEvent }> = ({ m }) => (
  <div
    className="flex items-center gap-2 px-3 py-2 text-xs"
    style={{ borderBottom: `1px solid ${colors.border}` }}
  >
    <span
      className="px-1.5 py-0.5 rounded text-xs font-medium"
      style={{
        background: m.type === 'promoted' ? 'rgba(74,222,128,0.15)' : 'rgba(251,113,133,0.15)',
        color: m.type === 'promoted' ? colors.promoted : colors.killed,
      }}
    >
      {m.type === 'promoted' ? 'Promoted' : 'Reverted'}
    </span>
    <span className="truncate flex-1" style={{ color: colors.textSecondary }}>
      {m.mutation_id.slice(0, 12)}
    </span>
    <span style={{ color: colors.textMuted }}>{relTime(new Date(m.timestamp).getTime())}</span>
  </div>
)

const SAFETY_LABELS: Record<string, string> = {
  cap_breach: 'Cap Breach',
  up_live_attempt: 'UP Live Attempt',
  config_mismatch: 'Config Mismatch',
  restart_loop: 'Restart Loop',
  duplicate_window: 'Duplicate Window',
}

const SafetyCard: React.FC<{ e: SafetyEvent }> = ({ e }) => (
  <div
    className="flex items-start gap-2 px-3 py-2 text-xs"
    style={{
      borderBottom: `1px solid ${colors.border}`,
      background: 'rgba(251,113,133,0.05)',
    }}
  >
    <span style={{ color: colors.loss }}>⚠</span>
    <div className="flex-1 min-w-0">
      <div className="font-medium" style={{ color: colors.loss }}>
        {SAFETY_LABELS[e.type] ?? e.type}
      </div>
      <div className="truncate" style={{ color: colors.textMuted }}>{e.details}</div>
    </div>
    <span className="flex-shrink-0" style={{ color: colors.textMuted }}>
      {relTime(new Date(e.timestamp).getTime())}
    </span>
  </div>
)

// ─── Control button ───────────────────────────────────────────────────────────

interface CtrlButtonProps {
  label: string
  icon: React.ReactNode
  bgColor: string
  hoverColor: string
  onClick: () => Promise<void>
  loading: boolean
  sub?: string
}

const CtrlButton: React.FC<CtrlButtonProps> = ({
  label,
  icon,
  bgColor,
  hoverColor,
  onClick,
  loading,
  sub,
}) => {
  const [hovered, setHovered] = React.useState(false)
  return (
    <div>
      <button
        onClick={onClick}
        disabled={loading}
        className="w-full flex items-center justify-center gap-2 rounded text-sm font-medium transition-colors"
        style={{
          height: 36,
          background: hovered ? hoverColor : bgColor,
          color: '#fff',
          opacity: loading ? 0.7 : 1,
          cursor: loading ? 'not-allowed' : 'pointer',
          border: 'none',
        }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {loading ? (
          <Loader2 size={14} className="animate-spin" />
        ) : (
          icon
        )}
        <span>{loading ? 'Working...' : label}</span>
      </button>
      {sub && (
        <div className="mt-0.5 text-xs text-center" style={{ color: colors.textMuted }}>
          {sub}
        </div>
      )}
    </div>
  )
}

// ─── Toast ────────────────────────────────────────────────────────────────────

interface Toast {
  id: number
  message: string
  ok: boolean
}

// ─── Main component ───────────────────────────────────────────────────────────

export const RightRail: React.FC = () => {
  const recentFills = useAppStore((s) => s.recentFills)
  const mutations = useAppStore((s) => s.mutations)
  const safetyEvents = useAppStore((s) => s.safetyEvents)
  const deployLog = useAppStore((s) => s.deployLog)

  const [killLoading, setKillLoading] = React.useState(false)
  const [deployLoading, setDeployLoading] = React.useState(false)
  const [syncLoading, setSyncLoading] = React.useState(false)
  const [toasts, setToasts] = React.useState<Toast[]>([])
  const toastId = useRef(0)

  const unified = toUnified(recentFills, mutations, safetyEvents)

  const lastDeploy = deployLog[0] as DeployStatus | undefined
  const lastDeploySub = lastDeploy
    ? `Last: ${new Date(lastDeploy.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · ${lastDeploy.success ? 'OK' : 'Failed'}`
    : undefined

  function addToast(message: string, ok: boolean) {
    const id = ++toastId.current
    setToasts((t) => [...t, { id, message, ok }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3000)
  }

  async function handleKill() {
    setKillLoading(true)
    try {
      await api.post('/kill', { strategy: 'btc5' })
      addToast('Kill signal sent', true)
    } catch (e: unknown) {
      addToast(`Kill failed: ${e instanceof Error ? e.message : String(e)}`, false)
    } finally {
      setKillLoading(false)
    }
  }

  async function handleDeploy() {
    setDeployLoading(true)
    try {
      await api.post('/deploy')
      addToast('Deploy triggered', true)
    } catch (e: unknown) {
      addToast(`Deploy failed: ${e instanceof Error ? e.message : String(e)}`, false)
    } finally {
      setDeployLoading(false)
    }
  }

  async function handleSync() {
    setSyncLoading(true)
    try {
      await api.post('/vps/sync-db')
      addToast('DB sync complete', true)
    } catch (e: unknown) {
      addToast(`Sync failed: ${e instanceof Error ? e.message : String(e)}`, false)
    } finally {
      setSyncLoading(false)
    }
  }

  return (
    <div
      className="flex flex-col flex-shrink-0 h-full relative"
      style={{
        width: 320,
        background: colors.bgElevated,
        borderLeft: `1px solid ${colors.border}`,
      }}
    >
      {/* Toast container */}
      <div className="absolute top-2 left-2 right-2 z-50 flex flex-col gap-1 pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="px-3 py-1.5 rounded text-xs font-medium"
            style={{
              background: t.ok ? 'rgba(74,222,128,0.15)' : 'rgba(251,113,133,0.15)',
              border: `1px solid ${t.ok ? 'rgba(74,222,128,0.3)' : 'rgba(251,113,133,0.3)'}`,
              color: t.ok ? colors.profit : colors.loss,
            }}
          >
            {t.message}
          </div>
        ))}
      </div>

      {/* Live Feed */}
      <div
        className="flex items-center gap-2 px-4 py-3 flex-shrink-0"
        style={{ borderBottom: `1px solid ${colors.border}` }}
      >
        <Activity size={14} style={{ color: colors.textSecondary }} />
        <span className="text-sm font-bold" style={{ color: colors.textPrimary }}>
          Live Feed
        </span>
      </div>
      <div className="flex-1 overflow-y-auto min-h-0">
        {unified.length === 0 ? (
          <div className="px-4 py-6 text-xs text-center" style={{ color: colors.textMuted }}>
            Waiting for data...
          </div>
        ) : (
          unified.map((ev, i) => {
            if (ev.kind === 'fill') return <FillCard key={i} f={ev.data} />
            if (ev.kind === 'mutation') return <MutationCard key={i} m={ev.data} />
            return <SafetyCard key={i} e={ev.data} />
          })
        )}
      </div>

      {/* Controls */}
      <div
        className="flex-shrink-0 p-4"
        style={{ borderTop: `1px solid ${colors.border}` }}
      >
        <div
          className="text-sm font-bold mb-3"
          style={{ color: colors.textPrimary }}
        >
          Controls
        </div>
        <div className="flex flex-col gap-2">
          <CtrlButton
            label="KILL BTC5"
            icon={<Skull size={14} />}
            bgColor="#7F1D1D"
            hoverColor="#991B1B"
            onClick={handleKill}
            loading={killLoading}
          />
          <CtrlButton
            label="Deploy to VPS"
            icon={<Rocket size={14} />}
            bgColor={colors.elasticBlue}
            hoverColor="#0952B8"
            onClick={handleDeploy}
            loading={deployLoading}
            sub={lastDeploySub}
          />
          <CtrlButton
            label="Sync VPS DB"
            icon={<Database size={14} />}
            bgColor="rgba(255,255,255,0.08)"
            hoverColor="rgba(255,255,255,0.12)"
            onClick={handleSync}
            loading={syncLoading}
          />
        </div>
      </div>
    </div>
  )
}
