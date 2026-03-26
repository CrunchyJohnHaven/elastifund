import { useEffect, useRef } from 'react'
import { colors } from '../../theme/colors'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Props {
  wins: number
  losses: number
  label?: string
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function WinRateChart({ wins, losses, label }: Props) {
  const barRef = useRef<HTMLDivElement>(null)
  const total = wins + losses

  const winRate = total > 0 ? wins / total : 0
  const winPct = winRate * 100
  const lossRate = total > 0 ? losses / total : 0
  const lossPct = lossRate * 100

  const rateStr = total > 0 ? `${winPct.toFixed(1)}%` : 'N/A'
  const countStr = `(${wins}W / ${losses}L)`

  // Animate bar on mount
  useEffect(() => {
    const el = barRef.current
    if (!el) return
    el.style.width = '0%'
    const raf = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        el.style.width = `${winPct}%`
      })
    })
    return () => cancelAnimationFrame(raf)
  }, [winPct])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {/* Label row */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        {label && (
          <span style={{ fontSize: 10, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {label}
          </span>
        )}
        <span style={{
          fontSize: 13,
          fontWeight: 700,
          color: winRate >= 0.55 ? colors.profit : winRate >= 0.5 ? colors.warning : colors.loss,
        }}>
          {rateStr}
        </span>
        <span style={{ fontSize: 11, color: colors.textSecondary }}>
          {countStr}
        </span>
      </div>

      {/* Bar */}
      <div style={{
        position: 'relative',
        height: 24,
        borderRadius: 4,
        overflow: 'hidden',
        background: total > 0 ? `${colors.loss}55` : 'rgba(255,255,255,0.05)',
      }}>
        {total > 0 && (
          <div
            ref={barRef}
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              height: '100%',
              background: winRate >= 0.55 ? colors.profit : winRate >= 0.5 ? colors.warning : `${colors.profit}88`,
              borderRadius: 4,
              transition: 'width 0.5s cubic-bezier(0.4, 0, 0.2, 1)',
            }}
          />
        )}
        {/* Inline percentage labels inside bar */}
        {total > 0 && winPct > 20 && (
          <span style={{
            position: 'absolute',
            left: 8,
            top: '50%',
            transform: 'translateY(-50%)',
            fontSize: 10,
            fontWeight: 700,
            color: '#ffffff',
            pointerEvents: 'none',
          }}>
            W {winPct.toFixed(0)}%
          </span>
        )}
        {total > 0 && lossPct > 20 && (
          <span style={{
            position: 'absolute',
            right: 8,
            top: '50%',
            transform: 'translateY(-50%)',
            fontSize: 10,
            fontWeight: 700,
            color: '#ffffff',
            pointerEvents: 'none',
          }}>
            L {lossPct.toFixed(0)}%
          </span>
        )}
      </div>
    </div>
  )
}

// Named export
export { WinRateChart }
