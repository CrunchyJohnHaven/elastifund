import React, { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import MonteCarloSurface from '../canvas/MonteCarloSurface'
import type { DataPoint, CurrentParams } from '../canvas/MonteCarloSurface'
import { colors } from '../../theme/colors'
import { api } from '../../lib/api'

// ─── API response types (from backend) ────────────────────────────────────────

interface MCDataPoint {
  price_floor: number
  hour_filter: string
  expected_pnl: number
  win_rate: number
  fill_count: number
}

export interface MCResult {
  data_points: MCDataPoint[]
  best: MCDataPoint | null
  worst: MCDataPoint | null
  current_rank: number | null
  total_combinations: number
  generated_at: string
}

interface MCRunParams {
  price_floor_min: number
  price_floor_max: number
  hours_included: number[]
  iterations: number
}

// ─── Transform API result to canvas DataPoint[] ───────────────────────────────

function toCanvasPoints(result: MCResult): DataPoint[] {
  return result.data_points.map((d) => ({
    priceFloor: d.price_floor,
    hourET: parseInt(d.hour_filter, 10),
    expectedPnl: d.expected_pnl,
  }))
}

const ALL_HOURS = Array.from({ length: 24 }, (_, i) => i)

export const MonteCarloScreen: React.FC = () => {
  const [data, setData] = useState<MCResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Parameter inputs
  const [priceFloorMin, setPriceFloorMin] = useState(0.45)
  const [priceFloorMax, setPriceFloorMax] = useState(0.60)
  const [iterations, setIterations] = useState(10000)
  const [hoursIncluded, setHoursIncluded] = useState<Set<number>>(new Set(ALL_HOURS))

  // Fetch latest on mount
  useEffect(() => {
    async function fetchLatest() {
      setLoading(true)
      try {
        const res = await api.get<MCResult>('/montecarlo/latest')
        setData(res)
      } catch {
        // Not fatal — may not exist yet
      } finally {
        setLoading(false)
      }
    }
    fetchLatest()
  }, [])

  async function handleRun() {
    setRunning(true)
    setError(null)
    const params: MCRunParams = {
      price_floor_min: priceFloorMin,
      price_floor_max: priceFloorMax,
      hours_included: Array.from(hoursIncluded).sort((a, b) => a - b),
      iterations,
    }
    try {
      const res = await api.post<MCResult>('/montecarlo/run', params)
      setData(res)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Monte Carlo run failed')
    } finally {
      setRunning(false)
    }
  }

  function toggleHour(h: number) {
    setHoursIncluded((prev) => {
      const next = new Set(prev)
      if (next.has(h)) {
        next.delete(h)
      } else {
        next.add(h)
      }
      return next
    })
  }

  function selectAllHours() {
    setHoursIncluded(new Set(ALL_HOURS))
  }

  function clearAllHours() {
    setHoursIncluded(new Set())
  }

  // Build canvas-compatible props
  const canvasPoints: DataPoint[] | null = data ? toCanvasPoints(data) : null
  const currentParams: CurrentParams | null = data
    ? {
        priceFloor: priceFloorMin,
        suppressedHours: ALL_HOURS.filter((h) => !hoursIncluded.has(h)),
      }
    : null

  return (
    <div className="flex h-full" style={{ gap: 0 }}>
      {/* Left — chart */}
      <div style={{ flex: '0 0 70%', minWidth: 0, borderRight: `1px solid ${colors.border}`, overflow: 'hidden' }}>
        <div
          style={{
            padding: '10px 16px',
            borderBottom: `1px solid ${colors.border}`,
            fontSize: 13,
            fontWeight: 600,
            color: colors.textPrimary,
          }}
        >
          Monte Carlo Surface
        </div>
        <div style={{ height: 'calc(100% - 41px)', overflow: 'hidden', position: 'relative' }}>
          {(loading || running) && (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(0,0,0,0.4)',
                zIndex: 10,
                color: colors.textMuted,
                fontSize: 14,
                gap: 8,
              }}
            >
              <Loader2 size={16} className="animate-spin" />
              {running ? 'Running simulation...' : 'Loading...'}
            </div>
          )}
          <MonteCarloSurface data={canvasPoints} currentParams={currentParams} />
        </div>
      </div>

      {/* Right — control panel */}
      <div
        style={{
          flex: '0 0 30%',
          minWidth: 200,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'auto',
          padding: 16,
          gap: 16,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600, color: colors.textPrimary }}>
          Parameters
        </div>

        {/* Price floor range */}
        <div>
          <label style={{ fontSize: 11, color: colors.textMuted, display: 'block', marginBottom: 6 }}>
            Price Floor Range
          </label>
          <div className="flex gap-2 items-center">
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={priceFloorMin}
              onChange={(e) => setPriceFloorMin(parseFloat(e.target.value))}
              style={{
                width: 70,
                background: colors.bgPanel,
                border: `1px solid ${colors.border}`,
                borderRadius: 4,
                color: colors.textPrimary,
                padding: '4px 8px',
                fontSize: 12,
              }}
            />
            <span style={{ color: colors.textMuted, fontSize: 11 }}>to</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={priceFloorMax}
              onChange={(e) => setPriceFloorMax(parseFloat(e.target.value))}
              style={{
                width: 70,
                background: colors.bgPanel,
                border: `1px solid ${colors.border}`,
                borderRadius: 4,
                color: colors.textPrimary,
                padding: '4px 8px',
                fontSize: 12,
              }}
            />
          </div>
        </div>

        {/* Iterations */}
        <div>
          <label style={{ fontSize: 11, color: colors.textMuted, display: 'block', marginBottom: 6 }}>
            Iterations
          </label>
          <input
            type="number"
            min={100}
            max={100000}
            step={1000}
            value={iterations}
            onChange={(e) => setIterations(parseInt(e.target.value, 10))}
            style={{
              width: '100%',
              background: colors.bgPanel,
              border: `1px solid ${colors.border}`,
              borderRadius: 4,
              color: colors.textPrimary,
              padding: '4px 8px',
              fontSize: 12,
            }}
          />
        </div>

        {/* Hours checkboxes */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label style={{ fontSize: 11, color: colors.textMuted }}>Hours to Include (ET)</label>
            <div className="flex gap-2">
              <button
                onClick={selectAllHours}
                style={{ fontSize: 10, color: colors.elasticBlue, background: 'none', border: 'none', cursor: 'pointer' }}
              >
                All
              </button>
              <button
                onClick={clearAllHours}
                style={{ fontSize: 10, color: colors.textMuted, background: 'none', border: 'none', cursor: 'pointer' }}
              >
                None
              </button>
            </div>
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(6, 1fr)',
              gap: 4,
            }}
          >
            {ALL_HOURS.map((h) => {
              const checked = hoursIncluded.has(h)
              return (
                <button
                  key={h}
                  onClick={() => toggleHour(h)}
                  style={{
                    fontSize: 10,
                    padding: '3px 2px',
                    borderRadius: 3,
                    border: `1px solid ${checked ? colors.elasticBlue : colors.border}`,
                    background: checked ? 'rgba(11,100,221,0.15)' : colors.bgPanel,
                    color: checked ? colors.textPrimary : colors.textMuted,
                    cursor: 'pointer',
                    textAlign: 'center',
                  }}
                >
                  {h.toString().padStart(2, '0')}
                </button>
              )
            })}
          </div>
        </div>

        {/* Run button */}
        <div>
          {error && (
            <div
              style={{
                fontSize: 11,
                color: colors.loss,
                marginBottom: 8,
                padding: '4px 8px',
                background: 'rgba(251,113,133,0.08)',
                borderRadius: 4,
              }}
            >
              {error}
            </div>
          )}
          <button
            onClick={handleRun}
            disabled={running}
            style={{
              width: '100%',
              padding: '9px 0',
              background: running ? 'rgba(11,100,221,0.4)' : colors.elasticBlue,
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 500,
              cursor: running ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
            }}
          >
            {running && <Loader2 size={13} className="animate-spin" />}
            {running ? 'Running...' : 'Run Monte Carlo'}
          </button>
        </div>

        {/* Summary stats if data exists */}
        {data && !running && (
          <div
            style={{
              background: colors.bgPanel,
              border: `1px solid ${colors.border}`,
              borderRadius: 6,
              padding: 12,
              fontSize: 12,
            }}
          >
            <div style={{ fontWeight: 600, color: colors.textPrimary, marginBottom: 8 }}>
              Last Run Summary
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ color: colors.textSecondary }}>
                Combinations: <span style={{ color: colors.textPrimary }}>{data.total_combinations}</span>
              </div>
              {data.best && (
                <div style={{ color: colors.textSecondary }}>
                  Best P&L:{' '}
                  <span style={{ color: colors.profit }}>${data.best.expected_pnl.toFixed(2)}</span>
                </div>
              )}
              {data.worst && (
                <div style={{ color: colors.textSecondary }}>
                  Worst P&L:{' '}
                  <span style={{ color: colors.loss }}>${data.worst.expected_pnl.toFixed(2)}</span>
                </div>
              )}
              {data.current_rank != null && (
                <div style={{ color: colors.textSecondary }}>
                  Current Rank:{' '}
                  <span style={{ color: colors.elasticBlue }}>
                    #{data.current_rank} / {data.total_combinations}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
