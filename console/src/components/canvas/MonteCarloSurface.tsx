import React, { useRef, useEffect } from 'react'
import { scaleLinear } from 'd3-scale'
import { interpolateRgb } from 'd3-interpolate'
import { colors } from '../../theme/colors'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface DataPoint {
  priceFloor: number
  hourET: number
  expectedPnl: number
}

export interface CurrentParams {
  priceFloor: number
  suppressedHours: number[]
}

interface Props {
  data: DataPoint[] | null
  currentParams: CurrentParams | null
}

// ─── Constants ────────────────────────────────────────────────────────────────

const MARGIN = { top: 12, right: 12, bottom: 48, left: 40 }
const PRICE_FLOORS = Array.from({ length: 16 }, (_, i) => +(0.40 + i * 0.01).toFixed(2))
const HOURS = Array.from({ length: 24 }, (_, i) => i)

// ─── Color scale (red → black → green) ───────────────────────────────────────

function pnlToColor(pnl: number, min: number, max: number): string {
  if (min === max) return '#000000'
  if (pnl < 0) {
    const t = min !== 0 ? pnl / min : 0
    return interpolateRgb('#000000', '#7F1D1D')(Math.max(0, Math.min(1, t)))
  }
  const t = max !== 0 ? pnl / max : 0
  return interpolateRgb('#000000', '#166534')(Math.max(0, Math.min(1, t)))
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function MonteCarloSurface({ data, currentParams }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const sizeRef = useRef({ width: 0, height: 0, dpr: 1 })
  const tooltipDivRef = useRef<HTMLDivElement>(null)
  const dataRef = useRef(data)
  const paramsRef = useRef(currentParams)

  useEffect(() => { dataRef.current = data }, [data])
  useEffect(() => { paramsRef.current = currentParams }, [currentParams])

  // ResizeObserver
  useEffect(() => {
    const container = containerRef.current
    const canvas = canvasRef.current
    if (!container || !canvas) return

    const ro = new ResizeObserver(entries => {
      const entry = entries[0]
      if (!entry) return
      const { width, height } = entry.contentRect
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      sizeRef.current = { width, height, dpr }
      render()
    })
    ro.observe(container)
    return () => ro.disconnect()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Re-render on data change
  useEffect(() => { render() }, [data, currentParams]) // eslint-disable-line react-hooks/exhaustive-deps

  function render() {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const { width, height, dpr } = sizeRef.current
    if (width === 0 || height === 0) return

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    // Background
    ctx.fillStyle = colors.bg
    ctx.fillRect(0, 0, width, height)

    if (!dataRef.current || dataRef.current.length === 0) {
      ctx.font = '14px Inter, sans-serif'
      ctx.fillStyle = colors.textSecondary
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText('Run Monte Carlo to generate surface', width / 2, height / 2)
      return
    }

    const plotW = width - MARGIN.left - MARGIN.right
    const plotH = height - MARGIN.top - MARGIN.bottom
    const cellW = plotW / PRICE_FLOORS.length
    const cellH = plotH / HOURS.length

    // Build lookup map
    const lookup = new Map<string, number>()
    for (const d of dataRef.current) {
      lookup.set(`${d.priceFloor.toFixed(2)}_${d.hourET}`, d.expectedPnl)
    }

    const pnlValues = dataRef.current.map(d => d.expectedPnl)
    const minPnl = Math.min(...pnlValues)
    const maxPnl = Math.max(...pnlValues)

    const xScale = scaleLinear()
      .domain([0, PRICE_FLOORS.length])
      .range([MARGIN.left, MARGIN.left + plotW])

    const yScale = scaleLinear()
      .domain([0, HOURS.length])
      .range([MARGIN.top, MARGIN.top + plotH])

    // Draw cells
    PRICE_FLOORS.forEach((pf, pfIdx) => {
      HOURS.forEach((hr) => {
        const pnl = lookup.get(`${pf.toFixed(2)}_${hr}`) ?? 0
        const cellX = xScale(pfIdx)
        const cellY = yScale(hr)

        ctx.fillStyle = pnlToColor(pnl, minPnl, maxPnl)
        ctx.fillRect(cellX, cellY, cellW - 0.5, cellH - 0.5)

        // Suppressed hour hash marks
        if (paramsRef.current?.suppressedHours.includes(hr)) {
          ctx.save()
          ctx.strokeStyle = 'rgba(251, 113, 133, 0.4)'
          ctx.lineWidth = 0.8
          const spacing = 5
          for (let d = -cellH; d < cellW + cellH; d += spacing) {
            ctx.beginPath()
            ctx.moveTo(cellX + d, cellY)
            ctx.lineTo(cellX + d + cellH, cellY + cellH)
            ctx.stroke()
          }
          ctx.restore()
        }
      })
    })

    // Grid lines
    ctx.save()
    ctx.strokeStyle = 'rgba(255,255,255,0.04)'
    ctx.lineWidth = 0.5
    PRICE_FLOORS.forEach((_, pfIdx) => {
      const gx = xScale(pfIdx)
      ctx.beginPath()
      ctx.moveTo(gx, MARGIN.top)
      ctx.lineTo(gx, MARGIN.top + plotH)
      ctx.stroke()
    })
    HOURS.forEach((hr) => {
      const gy = yScale(hr)
      ctx.beginPath()
      ctx.moveTo(MARGIN.left, gy)
      ctx.lineTo(MARGIN.left + plotW, gy)
      ctx.stroke()
    })
    ctx.restore()

    // Current params crosshair
    if (paramsRef.current) {
      const pfIdx = PRICE_FLOORS.findIndex(
        pf => Math.abs(pf - paramsRef.current!.priceFloor) < 0.005
      )
      if (pfIdx >= 0) {
        const crossX = xScale(pfIdx) + cellW / 2
        ctx.save()
        ctx.strokeStyle = 'rgba(255,255,255,0.8)'
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.moveTo(crossX, MARGIN.top)
        ctx.lineTo(crossX, MARGIN.top + plotH)
        ctx.stroke()
        ctx.restore()
      }
    }

    // X-axis labels (price floors, rotated 45°)
    ctx.save()
    ctx.font = '9px Inter, sans-serif'
    ctx.fillStyle = colors.textSecondary
    ctx.textAlign = 'right'
    ctx.textBaseline = 'top'
    PRICE_FLOORS.forEach((pf, pfIdx) => {
      const lx = xScale(pfIdx) + cellW / 2
      const ly = MARGIN.top + plotH + 4
      ctx.save()
      ctx.translate(lx, ly)
      ctx.rotate(-Math.PI / 4)
      ctx.fillText(pf.toFixed(2), 0, 0)
      ctx.restore()
    })
    ctx.restore()

    // Y-axis labels (hours)
    ctx.save()
    ctx.font = '9px Inter, sans-serif'
    ctx.fillStyle = colors.textSecondary
    ctx.textAlign = 'right'
    ctx.textBaseline = 'middle'
    HOURS.forEach((hr) => {
      const ly = yScale(hr) + cellH / 2
      ctx.fillText(`${hr}h`, MARGIN.left - 4, ly)
    })
    ctx.restore()
  }

  // Hover tooltip
  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect || !dataRef.current) return
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const { width, height } = sizeRef.current
    const plotW = width - MARGIN.left - MARGIN.right
    const plotH = height - MARGIN.top - MARGIN.bottom
    const cellW = plotW / PRICE_FLOORS.length
    const cellH = plotH / HOURS.length

    const pfIdx = Math.floor((mx - MARGIN.left) / cellW)
    const hrIdx = Math.floor((my - MARGIN.top) / cellH)

    if (pfIdx < 0 || pfIdx >= PRICE_FLOORS.length || hrIdx < 0 || hrIdx >= HOURS.length) {
      if (tooltipDivRef.current) tooltipDivRef.current.style.display = 'none'
      return
    }

    const pf = PRICE_FLOORS[pfIdx]
    const hr = HOURS[hrIdx]
    const key = `${pf.toFixed(2)}_${hr}`
    const pnl = dataRef.current.find(d =>
      `${d.priceFloor.toFixed(2)}_${d.hourET}` === key
    )

    if (tooltipDivRef.current && pnl !== undefined) {
      tooltipDivRef.current.style.display = 'block'
      tooltipDivRef.current.style.left = `${e.clientX + 14}px`
      tooltipDivRef.current.style.top = `${e.clientY - 10}px`
      tooltipDivRef.current.innerHTML = `
        <div>Price floor: <b>${pf.toFixed(2)}</b></div>
        <div>Hour ET: <b>${hr}:00</b></div>
        <div>Exp P&amp;L: <b style="color:${pnl.expectedPnl >= 0 ? colors.profit : colors.loss}">${pnl.expectedPnl >= 0 ? '+' : ''}$${pnl.expectedPnl.toFixed(3)}</b></div>
      `
    } else if (tooltipDivRef.current) {
      tooltipDivRef.current.style.display = 'none'
    }
  }

  const handleMouseLeave = () => {
    if (tooltipDivRef.current) tooltipDivRef.current.style.display = 'none'
  }

  return (
    <div ref={containerRef} style={{ position: 'relative', width: '100%', height: '100%' }}>
      <canvas
        ref={canvasRef}
        style={{ display: 'block', width: '100%', height: '100%', cursor: 'crosshair' }}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      />
      <div
        ref={tooltipDivRef}
        style={{
          position: 'fixed',
          display: 'none',
          background: colors.bgPanel,
          border: `1px solid rgba(255,255,255,0.12)`,
          borderRadius: 6,
          padding: '8px 10px',
          fontSize: 12,
          color: colors.textPrimary,
          pointerEvents: 'none',
          zIndex: 9999,
          lineHeight: 1.7,
        }}
      />
    </div>
  )
}
