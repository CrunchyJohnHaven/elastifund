import { colors } from '../../theme/colors'
import type { HypothesisStatus } from '../../types/hypothesis'

// ─── Status → Color ──────────────────────────────────────────────────────────

export function getStatusColor(status: HypothesisStatus): string {
  switch (status) {
    case 'idle':      return colors.idle
    case 'testing':   return colors.testing
    case 'promoted':  return colors.promoted
    case 'killed':    return colors.killed
    case 'incumbent': return colors.incumbent
    default:          return colors.neutral
  }
}

// ─── Glow ─────────────────────────────────────────────────────────────────────

export function drawGlow(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  color: string,
  intensity: number
): void {
  const grad = ctx.createRadialGradient(x, y, 0, x, y, radius * 3)
  // Parse color to inject alpha — supports rgba(...) and hex-like strings
  const base = color.startsWith('rgba') ? color : hexToRgba(color, intensity)
  const transparent = color.startsWith('rgba') ? fadeRgba(color, 0) : hexToRgba(color, 0)
  const mid = color.startsWith('rgba') ? fadeRgba(color, intensity * 0.4) : hexToRgba(color, intensity * 0.4)

  grad.addColorStop(0, base)
  grad.addColorStop(0.4, mid)
  grad.addColorStop(1, transparent)

  ctx.save()
  ctx.globalAlpha = intensity
  ctx.fillStyle = grad
  ctx.beginPath()
  ctx.arc(x, y, radius * 3, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()
}

function hexToRgba(hex: string, alpha: number): string {
  const clean = hex.replace('#', '')
  const r = parseInt(clean.slice(0, 2), 16)
  const g = parseInt(clean.slice(2, 4), 16)
  const b = parseInt(clean.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

function fadeRgba(color: string, alpha: number): string {
  // rgba(r, g, b, a) → rgba(r, g, b, newAlpha)
  return color.replace(/[\d.]+\)$/, `${alpha})`)
}

// ─── Node ─────────────────────────────────────────────────────────────────────

export function drawNode(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  color: string,
  label: string,
  selected: boolean
): void {
  if (!isFinite(x) || !isFinite(y) || radius <= 0) return

  // Fill circle
  ctx.beginPath()
  ctx.arc(x, y, radius, 0, Math.PI * 2)
  ctx.fillStyle = color
  ctx.fill()

  // Selection ring
  if (selected) {
    ctx.beginPath()
    ctx.arc(x, y, radius + 4, 0, Math.PI * 2)
    ctx.strokeStyle = '#FFFFFF'
    ctx.lineWidth = 1.5
    ctx.stroke()
  }

  // Label below node
  ctx.font = '10px Inter, sans-serif'
  ctx.fillStyle = colors.textSecondary
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillText(label, x, y + radius + 4)
}

// ─── Beam ─────────────────────────────────────────────────────────────────────

export function drawBeam(
  ctx: CanvasRenderingContext2D,
  fromX: number,
  fromY: number,
  toX: number,
  toY: number,
  progress: number,
  color: string
): void {
  const headX = fromX + (toX - fromX) * progress
  const headY = fromY + (toY - fromY) * progress

  // Trail: fade from head back toward source
  const grad = ctx.createLinearGradient(fromX, fromY, headX, headY)
  grad.addColorStop(0, 'rgba(0,0,0,0)')
  grad.addColorStop(0.7, 'rgba(0,0,0,0)')
  grad.addColorStop(1, color)

  ctx.save()
  ctx.beginPath()
  ctx.moveTo(fromX, fromY)
  ctx.lineTo(headX, headY)
  ctx.strokeStyle = grad
  ctx.lineWidth = 1.5
  ctx.globalAlpha = 0.8
  ctx.stroke()
  ctx.restore()

  // Bright head dot
  ctx.save()
  ctx.beginPath()
  ctx.arc(headX, headY, 2.5, 0, Math.PI * 2)
  ctx.fillStyle = color
  ctx.globalAlpha = 1
  ctx.fill()
  ctx.restore()
}

// ─── Math helpers ─────────────────────────────────────────────────────────────

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

// ─── Golden-angle color ───────────────────────────────────────────────────────

export function goldenAngleColor(index: number): string {
  const hue = (index * 137.508) % 360
  return `hsl(${hue}, 70%, 65%)`
}

// ─── Text fitting ─────────────────────────────────────────────────────────────

export function fitText(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number
): string {
  if (ctx.measureText(text).width <= maxWidth) return text
  let truncated = text
  while (truncated.length > 1 && ctx.measureText(truncated + '…').width > maxWidth) {
    truncated = truncated.slice(0, -1)
  }
  return truncated + '…'
}
