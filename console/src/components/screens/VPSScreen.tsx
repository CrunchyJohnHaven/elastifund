import React, { useEffect, useRef, useState } from 'react'
import { Loader2, RefreshCw, Rocket, Database } from 'lucide-react'
import { useAppStore } from '../../store/useAppStore'
import { colors } from '../../theme/colors'
import { api } from '../../lib/api'
import type { VPSStatus } from '../../types/system'

type ServiceName = 'jj-live.service' | 'btc-5min-maker.service'
type ServiceState = 'active' | 'inactive' | 'failed' | 'unknown'

interface ServiceCardProps {
  name: ServiceName
  state: ServiceState
  uptimeSeconds: number | null
}

function formatUptime(seconds: number | null): string {
  if (seconds === null) return 'unknown'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

const STATE_DOT: Record<ServiceState, string> = {
  active: colors.profit,
  inactive: colors.textMuted,
  failed: colors.loss,
  unknown: '#FBBF24',
}

const STATE_LABEL: Record<ServiceState, string> = {
  active: 'Active',
  inactive: 'Inactive',
  failed: 'Failed',
  unknown: 'Unknown',
}

const ServiceCard: React.FC<ServiceCardProps> = ({ name, state, uptimeSeconds }) => {
  const dotColor = STATE_DOT[state]
  const label = STATE_LABEL[state]
  return (
    <div
      style={{
        flex: 1,
        background: colors.bgPanel,
        border: `1px solid ${colors.border}`,
        borderRadius: 8,
        padding: '16px 18px',
      }}
    >
      <div style={{ fontSize: 11, color: colors.textMuted, marginBottom: 8 }}>{name}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span
          style={{
            display: 'inline-block',
            width: 10,
            height: 10,
            borderRadius: '50%',
            background: dotColor,
            boxShadow: `0 0 6px ${dotColor}`,
            flexShrink: 0,
          }}
        />
        <span style={{ fontSize: 18, fontWeight: 700, color: dotColor }}>{label}</span>
      </div>
      <div style={{ fontSize: 11, color: colors.textSecondary }}>
        Uptime: {formatUptime(uptimeSeconds)}
      </div>
    </div>
  )
}

interface ActionButtonProps {
  label: string
  icon: React.ReactNode
  color: string
  hoverColor: string
  loading: boolean
  onClick: () => void
}

const ActionButton: React.FC<ActionButtonProps> = ({
  label,
  icon,
  color,
  hoverColor,
  loading,
  onClick,
}) => {
  const [hovered, setHovered] = useState(false)
  return (
    <button
      onClick={onClick}
      disabled={loading}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        padding: '8px 0',
        background: hovered ? hoverColor : color,
        color: '#fff',
        border: 'none',
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 500,
        cursor: loading ? 'not-allowed' : 'pointer',
        opacity: loading ? 0.7 : 1,
        transition: 'background 0.15s',
      }}
    >
      {loading ? <Loader2 size={13} className="animate-spin" /> : icon}
      {loading ? 'Working...' : label}
    </button>
  )
}

function lineColor(level: string): string {
  if (level === 'error') return colors.loss
  if (level === 'warn') return '#FBBF24'
  return '#4ADE80'
}

export const VPSScreen: React.FC = () => {
  const vpsLogLines = useAppStore((s) => s.vpsLogLines)

  const [vpsStatus, setVpsStatus] = useState<VPSStatus | null>(null)
  const [loadingStatus, setLoadingStatus] = useState(false)
  const [restartLoading, setRestartLoading] = useState(false)
  const [deployLoading, setDeployLoading] = useState(false)
  const [syncLoading, setSyncLoading] = useState(false)
  const [actionMsg, setActionMsg] = useState<{ text: string; ok: boolean } | null>(null)

  const logEndRef = useRef<HTMLDivElement>(null)

  const fetchStatus = async () => {
    setLoadingStatus(true)
    try {
      const res = await api.get<VPSStatus>('/vps/status')
      setVpsStatus(res)
    } catch {
      // non-fatal
    } finally {
      setLoadingStatus(false)
    }
  }

  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 30_000)
    return () => clearInterval(interval)
  }, [])

  // Auto-scroll log to bottom when new lines arrive
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [vpsLogLines])

  async function handleRestart() {
    setRestartLoading(true)
    setActionMsg(null)
    try {
      await api.post('/vps/restart', { service: 'btc-5min-maker.service' })
      setActionMsg({ text: 'Restart signal sent', ok: true })
      setTimeout(fetchStatus, 3000)
    } catch (e: unknown) {
      setActionMsg({ text: `Restart failed: ${e instanceof Error ? e.message : String(e)}`, ok: false })
    } finally {
      setRestartLoading(false)
    }
  }

  async function handleDeploy() {
    setDeployLoading(true)
    setActionMsg(null)
    try {
      await api.post('/deploy')
      setActionMsg({ text: 'Deploy triggered', ok: true })
    } catch (e: unknown) {
      setActionMsg({ text: `Deploy failed: ${e instanceof Error ? e.message : String(e)}`, ok: false })
    } finally {
      setDeployLoading(false)
    }
  }

  async function handleSync() {
    setSyncLoading(true)
    setActionMsg(null)
    try {
      await api.post('/vps/sync-db')
      setActionMsg({ text: 'DB sync complete', ok: true })
    } catch (e: unknown) {
      setActionMsg({ text: `Sync failed: ${e instanceof Error ? e.message : String(e)}`, ok: false })
    } finally {
      setSyncLoading(false)
    }
  }

  const jjState = vpsStatus?.jj_live ?? 'unknown'
  const btcState = vpsStatus?.btc_5min_maker ?? 'unknown'
  const uptime = vpsStatus?.uptime_seconds ?? null

  // Display at most 500 lines, newest at bottom
  const displayLines = [...vpsLogLines].reverse().slice(0, 500)

  return (
    <div className="flex flex-col h-full">
      {/* Top 40% — service status */}
      <div
        style={{
          flex: '0 0 40%',
          minHeight: 0,
          padding: 16,
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          borderBottom: `1px solid ${colors.border}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: colors.textPrimary }}>
            Service Status
          </span>
          <button
            onClick={fetchStatus}
            disabled={loadingStatus}
            style={{
              background: 'none',
              border: 'none',
              color: loadingStatus ? colors.textMuted : colors.textSecondary,
              cursor: loadingStatus ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 11,
            }}
          >
            <RefreshCw size={12} style={{ animation: loadingStatus ? 'spin 1s linear infinite' : 'none' }} />
            {loadingStatus ? 'Checking...' : 'Refresh'}
          </button>
        </div>

        {/* Service cards */}
        <div style={{ display: 'flex', gap: 12 }}>
          <ServiceCard name="jj-live.service" state={jjState} uptimeSeconds={uptime} />
          <ServiceCard name="btc-5min-maker.service" state={btcState} uptimeSeconds={uptime} />
        </div>

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: 8 }}>
          <ActionButton
            label="Restart BTC5"
            icon={<RefreshCw size={13} />}
            color="#92400E"
            hoverColor="#B45309"
            loading={restartLoading}
            onClick={handleRestart}
          />
          <ActionButton
            label="Deploy"
            icon={<Rocket size={13} />}
            color={colors.elasticBlue}
            hoverColor="#0952B8"
            loading={deployLoading}
            onClick={handleDeploy}
          />
          <ActionButton
            label="Sync DB"
            icon={<Database size={13} />}
            color="rgba(255,255,255,0.08)"
            hoverColor="rgba(255,255,255,0.12)"
            loading={syncLoading}
            onClick={handleSync}
          />
        </div>

        {/* Action feedback */}
        {actionMsg && (
          <div
            style={{
              fontSize: 11,
              color: actionMsg.ok ? colors.profit : colors.loss,
              padding: '4px 10px',
              background: actionMsg.ok ? 'rgba(74,222,128,0.08)' : 'rgba(251,113,133,0.08)',
              border: `1px solid ${actionMsg.ok ? 'rgba(74,222,128,0.25)' : 'rgba(251,113,133,0.25)'}`,
              borderRadius: 5,
              alignSelf: 'flex-start',
            }}
          >
            {actionMsg.text}
          </div>
        )}
      </div>

      {/* Bottom 60% — terminal log */}
      <div
        style={{
          flex: '0 0 60%',
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            padding: '8px 16px',
            borderBottom: `1px solid ${colors.border}`,
            fontSize: 11,
            color: colors.textMuted,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <span
            style={{
              display: 'inline-block',
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: colors.profit,
            }}
          />
          VPS Log
          <span style={{ marginLeft: 'auto' }}>
            {displayLines.length} lines
          </span>
        </div>
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            background: '#0A0E14',
            fontFamily: '"JetBrains Mono", "Menlo", "Consolas", monospace',
            fontSize: 13,
            padding: '8px 12px',
          }}
        >
          {displayLines.length === 0 ? (
            <div style={{ color: colors.textMuted, padding: '12px 0' }}>
              Waiting for VPS log events via WebSocket...
            </div>
          ) : (
            displayLines.map((entry, i) => (
              <div
                key={i}
                style={{
                  color: lineColor(entry.level),
                  lineHeight: 1.7,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                <span style={{ color: 'rgba(255,255,255,0.25)', marginRight: 8, userSelect: 'none' }}>
                  {new Date(entry.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
                </span>
                {entry.line}
              </div>
            ))
          )}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  )
}
