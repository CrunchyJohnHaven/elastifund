import React, { useRef, useEffect, useCallback } from 'react'
import { colors } from '../../theme/colors'
import type { Hypothesis, HypothesisStatus } from '../../types/hypothesis'
import {
  getStatusColor,
  drawGlow,
  drawBeam,
  lerp,
} from './canvasUtils'

// ─── Types ────────────────────────────────────────────────────────────────────

interface NodeState {
  x: number
  y: number
  targetX: number
  targetY: number
  angle: number
  radius: number
  opacity: number
  killTime: number | null
}

interface TooltipData {
  id: string
  status: HypothesisStatus
  shadow_pnl: number | null
  win_rate: number | null
  screenX: number
  screenY: number
}

interface Props {
  hypotheses: Hypothesis[]
  selectedId: string | null
  onSelect: (id: string | null) => void
}

// ─── Constants ────────────────────────────────────────────────────────────────

const GOLDEN_ANGLE = 2.399 // radians
const LERP_FACTOR = 0.02
const MAX_NODE_RADIUS = 14
const MIN_NODE_RADIUS = 8
const KILL_FADE_DURATION = 2.0
const STATUS_PRIORITY: Record<HypothesisStatus, number> = {
  killed: 0,
  idle: 1,
  promoted: 2,
  testing: 3,
  incumbent: 4,
}

function nodeRadius(iterations: number): number {
  return Math.min(MAX_NODE_RADIUS, Math.max(MIN_NODE_RADIUS, MIN_NODE_RADIUS + iterations * 0.6))
}

function computeNormalizedFitness(
  pnl: number | null,
  minPnl: number,
  maxPnl: number
): number {
  if (pnl === null) return 0.5
  if (maxPnl === minPnl) return 0.5
  return Math.max(0, Math.min(1, (pnl - minPnl) / (maxPnl - minPnl)))
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function HypothesisTank({ hypotheses, selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const nodePositions = useRef<Map<string, NodeState>>(new Map())
  const tooltipRef = useRef<TooltipData | null>(null)
  const tooltipDivRef = useRef<HTMLDivElement>(null)
  const sizeRef = useRef({ width: 0, height: 0, dpr: 1 })
  const hypothesesRef = useRef<Hypothesis[]>(hypotheses)
  const selectedIdRef = useRef<string | null>(selectedId)

  // Keep refs in sync without re-running animation loop
  useEffect(() => { hypothesesRef.current = hypotheses }, [hypotheses])
  useEffect(() => { selectedIdRef.current = selectedId }, [selectedId])

  // Sync node positions when hypotheses change
  useEffect(() => {
    const { width, height } = sizeRef.current
    const cx = width / 2
    const cy = height / 2
    const maxRadius = Math.min(width, height) * 0.42

    const pnls = hypotheses
      .map(h => h.shadow_pnl)
      .filter((p): p is number => p !== null)
    const minPnl = pnls.length ? Math.min(...pnls) : 0
    const maxPnl = pnls.length ? Math.max(...pnls) : 0

    hypotheses.forEach((h, index) => {
      if (nodePositions.current.has(h.id)) return // already tracked

      const fitness = computeNormalizedFitness(h.shadow_pnl, minPnl, maxPnl)
      let targetRadius: number
      if (h.status === 'incumbent') {
        targetRadius = maxRadius * 0.1
      } else if (h.status === 'killed') {
        targetRadius = maxRadius * 0.95
      } else {
        targetRadius = (1 - fitness) * maxRadius
      }

      const angle = index * GOLDEN_ANGLE
      const tx = cx + Math.cos(angle) * targetRadius
      const ty = cy + Math.sin(angle) * targetRadius

      nodePositions.current.set(h.id, {
        x: cx + Math.cos(angle) * maxRadius, // spawn at outer ring
        y: cy + Math.sin(angle) * maxRadius,
        targetX: tx,
        targetY: ty,
        angle,
        radius: targetRadius,
        opacity: 1,
        killTime: null,
      })
    })

    // Update target positions for existing nodes (status may have changed)
    hypotheses.forEach((h, index) => {
      const node = nodePositions.current.get(h.id)
      if (!node) return
      const fitness = computeNormalizedFitness(h.shadow_pnl, minPnl, maxPnl)
      let targetRadius: number
      if (h.status === 'incumbent') {
        targetRadius = maxRadius * 0.1
      } else if (h.status === 'killed') {
        targetRadius = maxRadius * 0.95
        if (!node.killTime) {
          node.killTime = performance.now() / 1000
        }
      } else {
        targetRadius = (1 - fitness) * maxRadius
      }
      const angle = index * GOLDEN_ANGLE
      node.angle = angle
      node.radius = targetRadius
      node.targetX = cx + Math.cos(angle) * targetRadius
      node.targetY = cy + Math.sin(angle) * targetRadius
    })

    // Mark nodes for removal if no longer in hypotheses list
    const currentIds = new Set(hypotheses.map(h => h.id))
    nodePositions.current.forEach((node, id) => {
      if (!currentIds.has(id) && !node.killTime) {
        node.killTime = performance.now() / 1000
      }
    })
  }, [hypotheses])

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
    })
    ro.observe(container)
    return () => ro.disconnect()
  }, [])

  // Animation loop
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const animate = (timestamp: number) => {
      const t = timestamp / 1000
      const ctx = canvas.getContext('2d')
      const { width, height, dpr } = sizeRef.current
      if (!ctx || width === 0 || height === 0) {
        rafRef.current = requestAnimationFrame(animate)
        return
      }

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

      const cx = width / 2
      const cy = height / 2
      const maxRadius = Math.min(width, height) * 0.42

      // Background
      ctx.fillStyle = colors.bg
      ctx.fillRect(0, 0, width, height)

      // Concentric ring guides (25%, 50%, 75%)
      ctx.save()
      ctx.setLineDash([4, 10])
      for (const frac of [0.25, 0.5, 0.75]) {
        ctx.beginPath()
        ctx.arc(cx, cy, maxRadius * frac, 0, Math.PI * 2)
        ctx.strokeStyle = 'rgba(255,255,255,0.03)'
        ctx.lineWidth = 0.8
        ctx.stroke()
      }
      ctx.setLineDash([])
      ctx.restore()

      // Center target dot
      const goldPulse = 0.5 + Math.sin(t * 2.1) * 0.3
      drawGlow(ctx, cx, cy, 8, colors.incumbent, goldPulse * 0.4)
      ctx.beginPath()
      ctx.arc(cx, cy, 4, 0, Math.PI * 2)
      ctx.fillStyle = colors.incumbent
      ctx.fill()

      const hyps = hypothesesRef.current
      const selId = selectedIdRef.current

      // Sort: killed first (draw behind), incumbent last (draw on top)
      const sorted = [...hyps].sort(
        (a, b) => STATUS_PRIORITY[a.status] - STATUS_PRIORITY[b.status]
      )

      const nowSec = timestamp / 1000

      sorted.forEach((h, _i) => {
        const indexInAll = hyps.indexOf(h)
        const node = nodePositions.current.get(h.id)
        if (!node) return

        // Small orbital oscillation
        const oscillatedAngle = node.angle + Math.sin(t * 0.3 + indexInAll) * 0.02
        const oscX = cx + Math.cos(oscillatedAngle) * node.radius
        const oscY = cy + Math.sin(oscillatedAngle) * node.radius
        node.targetX = oscX
        node.targetY = oscY

        // Lerp toward target
        node.x = lerp(node.x, node.targetX, LERP_FACTOR)
        node.y = lerp(node.y, node.targetY, LERP_FACTOR)

        // Kill fade
        if (node.killTime !== null) {
          const elapsed = nowSec - node.killTime
          node.opacity = Math.max(0, 1 - elapsed / KILL_FADE_DURATION)
        }

        if (node.opacity <= 0) return

        const { x, y } = node
        const color = getStatusColor(h.status)
        const r = nodeRadius(h.iterations)
        const isSelected = selId === h.id
        const isIncumbent = h.status === 'incumbent'

        ctx.save()
        ctx.globalAlpha = node.opacity

        // Glow halo
        let glowIntensity = 0.2
        if (isIncumbent) glowIntensity = 0.5 + Math.sin(t * 2.1) * 0.3
        else if (h.status === 'testing') glowIntensity = 0.6
        else if (h.status === 'promoted') glowIntensity = 0.5
        drawGlow(ctx, x, y, r, color, glowIntensity)

        // Node circle
        ctx.beginPath()
        ctx.arc(x, y, isIncumbent ? 16 : r, 0, Math.PI * 2)
        ctx.fillStyle = color
        ctx.fill()

        // Selection ring
        if (isSelected) {
          ctx.beginPath()
          ctx.arc(x, y, (isIncumbent ? 16 : r) + 4, 0, Math.PI * 2)
          ctx.strokeStyle = '#FFFFFF'
          ctx.lineWidth = 1.5
          ctx.stroke()
        }

        // Label
        const labelText = h.id.slice(0, 6)
        ctx.font = '10px Inter, sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        ctx.fillStyle = isIncumbent ? colors.incumbent : colors.textSecondary
        ctx.fillText(isIncumbent ? 'INCUMBENT' : labelText, x, y + (isIncumbent ? 16 : r) + 4)
        if (isIncumbent) {
          ctx.fillStyle = colors.textMuted
          ctx.fillText(h.id.slice(0, 6), x, y + (isIncumbent ? 16 : r) + 16)
        }

        // Testing beam toward center
        if (h.status === 'testing') {
          const beamProgress = (Math.sin(t * (Math.PI * 2) / 1.6) + 1) / 2
          drawBeam(ctx, x, y, cx, cy, beamProgress, color)
        }

        // Selected detail info
        if (isSelected) {
          const lines = [
            `P&L: ${h.shadow_pnl !== null ? '$' + h.shadow_pnl.toFixed(2) : 'N/A'}`,
            `WR: ${h.win_rate !== null ? (h.win_rate * 100).toFixed(1) + '%' : 'N/A'}`,
            `itr: ${h.iterations}`,
          ]
          const infoX = x + 20
          const infoY = y - 10
          ctx.font = '10px Inter, sans-serif'
          ctx.textAlign = 'left'
          ctx.textBaseline = 'top'
          lines.forEach((line, li) => {
            ctx.fillStyle = colors.textSecondary
            ctx.fillText(line, infoX, infoY + li * 13)
          })
        }

        ctx.restore()
      })

      rafRef.current = requestAnimationFrame(animate)
    }

    rafRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(rafRef.current)
  }, [])

  // Hit testing helpers
  const getHitHypothesis = useCallback((mx: number, my: number): Hypothesis | null => {
    let closest: Hypothesis | null = null
    let closestDist = 20
    hypothesesRef.current.forEach(h => {
      const node = nodePositions.current.get(h.id)
      if (!node || node.opacity <= 0) return
      const dx = node.x - mx
      const dy = node.y - my
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (dist < closestDist) {
        closestDist = dist
        closest = h
      }
    })
    return closest
  }, [])

  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const hit = getHitHypothesis(mx, my)
    onSelect(hit ? (hit.id === selectedIdRef.current ? null : hit.id) : null)
  }, [getHitHypothesis, onSelect])

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const hit = getHitHypothesis(mx, my)

    if (canvasRef.current) {
      canvasRef.current.style.cursor = hit ? 'pointer' : 'default'
    }

    if (hit) {
      tooltipRef.current = {
        id: hit.id,
        status: hit.status,
        shadow_pnl: hit.shadow_pnl,
        win_rate: hit.win_rate,
        screenX: e.clientX,
        screenY: e.clientY,
      }
      if (tooltipDivRef.current) {
        const t = tooltipRef.current
        tooltipDivRef.current.style.display = 'block'
        tooltipDivRef.current.style.left = `${t.screenX + 14}px`
        tooltipDivRef.current.style.top = `${t.screenY - 10}px`
        tooltipDivRef.current.innerHTML = `
          <div style="font-weight:600;margin-bottom:2px">${t.id}</div>
          <div>Status: ${t.status}</div>
          <div>P&amp;L: ${t.shadow_pnl !== null ? '$' + t.shadow_pnl.toFixed(2) : 'N/A'}</div>
          <div>Win rate: ${t.win_rate !== null ? (t.win_rate * 100).toFixed(1) + '%' : 'N/A'}</div>
        `
      }
    } else {
      tooltipRef.current = null
      if (tooltipDivRef.current) {
        tooltipDivRef.current.style.display = 'none'
      }
    }
  }, [getHitHypothesis])

  const handleMouseLeave = useCallback(() => {
    tooltipRef.current = null
    if (tooltipDivRef.current) tooltipDivRef.current.style.display = 'none'
    if (canvasRef.current) canvasRef.current.style.cursor = 'default'
  }, [])

  return (
    <div ref={containerRef} style={{ position: 'relative', width: '100%', height: '100%' }}>
      <canvas
        ref={canvasRef}
        onClick={handleClick}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        style={{ display: 'block', width: '100%', height: '100%' }}
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
          lineHeight: 1.6,
        }}
      />
    </div>
  )
}
