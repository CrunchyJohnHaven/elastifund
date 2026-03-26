import React, { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Loader2 } from 'lucide-react'
import HypothesisTank from '../canvas/HypothesisTank'
import { useAppStore } from '../../store/useAppStore'
import { colors } from '../../theme/colors'
import { api } from '../../lib/api'
import type { Hypothesis } from '../../types/hypothesis'

const STATUS_BADGE_COLORS: Record<string, { bg: string; text: string }> = {
  idle: { bg: 'rgba(154,164,178,0.15)', text: colors.textSecondary },
  testing: { bg: 'rgba(77,163,255,0.15)', text: '#4DA3FF' },
  promoted: { bg: 'rgba(74,222,128,0.15)', text: colors.profit },
  killed: { bg: 'rgba(251,113,133,0.15)', text: colors.loss },
  incumbent: { bg: 'rgba(254,197,20,0.15)', text: '#FEC514' },
}

function DetailPanel({ hypothesis, onClose }: { hypothesis: Hypothesis; onClose: () => void }) {
  const badge = STATUS_BADGE_COLORS[hypothesis.status] ?? STATUS_BADGE_COLORS.idle

  const paramEntries = Object.entries(hypothesis.params)

  return (
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 12, scale: 0.97 }}
      transition={{ duration: 0.15 }}
      style={{
        position: 'absolute',
        bottom: 16,
        right: 16,
        width: 300,
        background: colors.bgPanel,
        border: `1px solid rgba(255,255,255,0.12)`,
        borderRadius: 8,
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        zIndex: 20,
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 14px',
          borderBottom: `1px solid ${colors.border}`,
        }}
      >
        <div>
          <div style={{ fontSize: 12, fontFamily: 'monospace', color: colors.textPrimary, marginBottom: 4 }}>
            {hypothesis.id}
          </div>
          <span
            style={{
              display: 'inline-block',
              fontSize: 11,
              padding: '2px 8px',
              borderRadius: 4,
              background: badge.bg,
              color: badge.text,
              fontWeight: 600,
            }}
          >
            {hypothesis.status.toUpperCase()}
          </span>
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: colors.textMuted,
            cursor: 'pointer',
            padding: 4,
          }}
        >
          <X size={14} />
        </button>
      </div>

      {/* Stats */}
      <div style={{ padding: '10px 14px', borderBottom: `1px solid ${colors.border}` }}>
        <div style={{ display: 'flex', gap: 16 }}>
          <div>
            <div style={{ fontSize: 10, color: colors.textMuted, marginBottom: 3 }}>Shadow P&L</div>
            <div
              style={{
                fontSize: 15,
                fontWeight: 600,
                color:
                  hypothesis.shadow_pnl == null
                    ? colors.textMuted
                    : hypothesis.shadow_pnl >= 0
                    ? colors.profit
                    : colors.loss,
              }}
            >
              {hypothesis.shadow_pnl != null ? `$${hypothesis.shadow_pnl.toFixed(2)}` : 'N/A'}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 10, color: colors.textMuted, marginBottom: 3 }}>Win Rate</div>
            <div
              style={{
                fontSize: 15,
                fontWeight: 600,
                color:
                  hypothesis.win_rate == null
                    ? colors.textMuted
                    : hypothesis.win_rate >= 0.52
                    ? colors.profit
                    : colors.loss,
              }}
            >
              {hypothesis.win_rate != null ? `${(hypothesis.win_rate * 100).toFixed(1)}%` : 'N/A'}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 10, color: colors.textMuted, marginBottom: 3 }}>Iterations</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: colors.textPrimary }}>
              {hypothesis.iterations}
            </div>
          </div>
        </div>
        {hypothesis.kill_reason && (
          <div
            style={{
              marginTop: 8,
              fontSize: 11,
              color: colors.loss,
              background: 'rgba(251,113,133,0.08)',
              borderRadius: 4,
              padding: '4px 8px',
            }}
          >
            Kill reason: {hypothesis.kill_reason}
          </div>
        )}
      </div>

      {/* Parameters */}
      {paramEntries.length > 0 && (
        <div style={{ padding: '10px 14px', maxHeight: 180, overflowY: 'auto' }}>
          <div style={{ fontSize: 10, color: colors.textMuted, marginBottom: 6, fontWeight: 600, letterSpacing: '0.05em' }}>
            PARAMETERS
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {paramEntries.map(([key, val]) => (
              <div key={key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                <span style={{ color: colors.textSecondary }}>{key}</span>
                <span style={{ color: colors.textPrimary, fontFamily: 'monospace' }}>
                  {String(val)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  )
}

export const TankScreen: React.FC = () => {
  const hypotheses = useAppStore((s) => s.hypotheses)
  const selectedHypothesisId = useAppStore((s) => s.selectedHypothesisId)
  const selectHypothesis = useAppStore((s) => s.selectHypothesis)

  const [triggering, setTriggering] = useState(false)
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null)

  const selectedHypothesis = hypotheses.find((h) => h.id === selectedHypothesisId) ?? null

  async function handleTriggerAutoresearch() {
    setTriggering(true)
    setTriggerMsg(null)
    try {
      await api.post('/autoresearch/trigger')
      setTriggerMsg('Autoresearch triggered successfully.')
    } catch (e: unknown) {
      setTriggerMsg(`Error: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setTriggering(false)
    }
  }

  if (hypotheses.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center h-full gap-4"
        style={{ color: colors.textMuted }}
      >
        <div style={{ fontSize: 14, color: colors.textSecondary, textAlign: 'center', maxWidth: 340 }}>
          No hypotheses loaded. Autoresearch cycle will populate this view.
        </div>
        {triggerMsg && (
          <div
            style={{
              fontSize: 12,
              color: triggerMsg.startsWith('Error') ? colors.loss : colors.profit,
              background: triggerMsg.startsWith('Error')
                ? 'rgba(251,113,133,0.08)'
                : 'rgba(74,222,128,0.08)',
              border: `1px solid ${triggerMsg.startsWith('Error') ? 'rgba(251,113,133,0.25)' : 'rgba(74,222,128,0.25)'}`,
              borderRadius: 6,
              padding: '6px 14px',
            }}
          >
            {triggerMsg}
          </div>
        )}
        <button
          onClick={handleTriggerAutoresearch}
          disabled={triggering}
          style={{
            background: colors.elasticBlue,
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            padding: '8px 20px',
            fontSize: 13,
            fontWeight: 500,
            cursor: triggering ? 'not-allowed' : 'pointer',
            opacity: triggering ? 0.7 : 1,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          {triggering && <Loader2 size={13} className="animate-spin" />}
          Trigger Autoresearch
        </button>
      </div>
    )
  }

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <HypothesisTank
        hypotheses={hypotheses}
        selectedId={selectedHypothesisId}
        onSelect={selectHypothesis}
      />
      <AnimatePresence>
        {selectedHypothesis && (
          <DetailPanel
            key={selectedHypothesis.id}
            hypothesis={selectedHypothesis}
            onClose={() => selectHypothesis(null)}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
