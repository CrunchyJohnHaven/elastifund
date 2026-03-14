import type { ScoringDimension, AEProfile, Activity } from '../types'

type DimensionFactory = (config?: Record<string, unknown>) => ScoringDimension

interface RegistryEntry {
  factory: DimensionFactory
  locked: boolean
}

const registry = new Map<string, RegistryEntry>()

export function registerDimension(
  id: string,
  factory: DimensionFactory,
  options?: { locked?: boolean }
): void {
  const existing = registry.get(id)
  if (existing?.locked) {
    console.warn(`Cannot override locked dimension: ${id}`)
    return
  }
  registry.set(id, { factory, locked: options?.locked ?? false })
}

export function removeDimension(id: string): boolean {
  const existing = registry.get(id)
  if (existing?.locked) {
    console.warn(`Cannot remove locked dimension: ${id}`)
    return false
  }
  return registry.delete(id)
}

export function isDimensionLocked(id: string): boolean {
  return registry.get(id)?.locked ?? false
}

export function getDimension(id: string, config?: Record<string, unknown>): ScoringDimension | undefined {
  const entry = registry.get(id)
  return entry ? entry.factory(config) : undefined
}

export function listRegisteredDimensions(): string[] {
  return Array.from(registry.keys())
}

export function buildScoringConfig(
  dimensionIds: string[],
  configs?: Record<string, Record<string, unknown>>
): ScoringDimension[] {
  return dimensionIds
    .map((id) => getDimension(id, configs?.[id]))
    .filter((d): d is ScoringDimension => d !== undefined)
}

// --- Extension support: config-driven dimensions with safe formula evaluation ---

export interface ScoringExtension {
  key: string
  label: string
  description: string
  weight: number
  formula: string // e.g. "count(bvr_created) * 15 + count(customer_meeting) * 10"
}

/**
 * Safe expression evaluator for scoring formulas.
 * Supports: count(activity_type), sum_acv, unique_deals, total_activities,
 * arithmetic operators (+, -, *, /), numbers, and parentheses.
 * No eval() or Function() used.
 */
function evaluateFormula(formula: string, _ae: AEProfile, activities: Activity[]): number {
  const activityCounts = new Map<string, number>()
  for (const a of activities) {
    activityCounts.set(a.type, (activityCounts.get(a.type) ?? 0) + 1)
  }

  const uniqueDeals = new Set(activities.filter((a) => a.dealName).map((a) => a.dealName)).size
  let totalAcv = 0
  const seenDeals = new Set<string>()
  for (const a of activities) {
    if (a.dealName && a.acv && !seenDeals.has(a.dealName)) {
      seenDeals.add(a.dealName)
      totalAcv += a.acv
    }
  }

  // Tokenize
  const tokens: string[] = []
  let i = 0
  const src = formula.trim()
  while (i < src.length) {
    if (/\s/.test(src[i])) { i++; continue }
    if ('+-*/()'.includes(src[i])) {
      tokens.push(src[i])
      i++
      continue
    }
    if (/[0-9.]/.test(src[i])) {
      let num = ''
      while (i < src.length && /[0-9.]/.test(src[i])) { num += src[i]; i++ }
      tokens.push(num)
      continue
    }
    if (/[a-zA-Z_]/.test(src[i])) {
      let ident = ''
      while (i < src.length && /[a-zA-Z0-9_]/.test(src[i])) { ident += src[i]; i++ }
      tokens.push(ident)
      continue
    }
    i++
  }

  // Recursive descent parser
  let pos = 0
  function peek(): string | undefined { return tokens[pos] }
  function consume(): string { return tokens[pos++] }

  function parseAtom(): number {
    const tok = peek()
    if (tok === '(') {
      consume()
      const val = parseExpr()
      if (peek() === ')') consume()
      return val
    }
    if (tok === 'count') {
      consume()
      if (peek() === '(') consume()
      const typeName = consume()
      if (peek() === ')') consume()
      return activityCounts.get(typeName) ?? 0
    }
    if (tok === 'sum_acv') { consume(); return totalAcv }
    if (tok === 'unique_deals') { consume(); return uniqueDeals }
    if (tok === 'total_activities') { consume(); return activities.length }
    if (tok !== undefined && /^[0-9]/.test(tok)) { consume(); return parseFloat(tok) || 0 }
    if (tok !== undefined) consume()
    return 0
  }

  function parseTerm(): number {
    let val = parseAtom()
    while (peek() === '*' || peek() === '/') {
      const op = consume()
      const right = parseAtom()
      if (op === '*') val *= right
      else if (right !== 0) val /= right
    }
    return val
  }

  function parseExpr(): number {
    let val = parseTerm()
    while (peek() === '+' || peek() === '-') {
      const op = consume()
      const right = parseTerm()
      if (op === '+') val += right
      else val -= right
    }
    return val
  }

  return parseExpr()
}

/**
 * Register extensions from config. Skips extensions conflicting with locked dimensions.
 */
export function registerExtensions(extensions: ScoringExtension[]): string[] {
  const registered: string[] = []
  for (const ext of extensions) {
    if (isDimensionLocked(ext.key)) {
      console.warn(`Extension "${ext.key}" conflicts with locked dimension, skipping`)
      continue
    }
    registerDimension(ext.key, () => ({
      id: ext.key,
      name: ext.label,
      description: ext.description,
      weight: ext.weight,
      compute: (ae: AEProfile, activities: Activity[]) => {
        try {
          const raw = evaluateFormula(ext.formula, ae, activities)
          return Math.max(0, Math.min(100, Math.round(raw)))
        } catch (err) {
          console.warn(`Extension "${ext.key}" formula evaluation failed:`, err)
          return 0
        }
      },
    }))
    registered.push(ext.key)
  }
  return registered
}

/**
 * Validate an extension config. Returns null if valid, or an error message.
 */
export function validateExtension(ext: ScoringExtension): string | null {
  if (!ext.key || !/^[a-z_][a-z0-9_]*$/.test(ext.key)) {
    return `Invalid key "${ext.key}": must be lowercase with underscores`
  }
  if (isDimensionLocked(ext.key)) {
    return `Cannot override locked dimension "${ext.key}"`
  }
  if (!ext.label || ext.label.length === 0) {
    return 'Label is required'
  }
  if (typeof ext.weight !== 'number' || ext.weight < 0) {
    return 'Weight must be a non-negative number'
  }
  if (!ext.formula || ext.formula.length === 0) {
    return 'Formula is required'
  }
  return null
}

// --- Built-in locked dimensions (core 4) ---

function countByType(activities: Activity[], types: string[]): number {
  return activities.filter((a) => types.includes(a.type)).length
}

function sumAcv(activities: Activity[]): number {
  const seen = new Set<string>()
  let total = 0
  for (const a of activities) {
    if (a.dealName && a.acv && !seen.has(a.dealName)) {
      seen.add(a.dealName)
      total += a.acv
    }
  }
  return total
}

registerDimension('bvr_output', () => ({
  id: 'bvr_output',
  name: 'BVR Output',
  description: 'Number of BVRs created and delivered',
  weight: 25,
  compute: (_ae: AEProfile, activities: Activity[]) => {
    const count = countByType(activities, ['bvr_created', 'bvr_delivered'])
    return Math.min(count * 20, 100)
  },
}), { locked: true })

registerDimension('customer_engagement', () => ({
  id: 'customer_engagement',
  name: 'Customer Engagement',
  description: 'Customer meetings, workshops, and executive briefings',
  weight: 25,
  compute: (_ae: AEProfile, activities: Activity[]) => {
    const meetings = countByType(activities, ['customer_meeting'])
    const workshops = countByType(activities, ['workshop_delivered'])
    const briefings = countByType(activities, ['executive_briefing'])
    return Math.min(meetings * 15 + workshops * 25 + briefings * 20, 100)
  },
}), { locked: true })

registerDimension('pipeline_impact', () => ({
  id: 'pipeline_impact',
  name: 'Pipeline Impact',
  description: 'Total ACV of deals with VE engagement',
  weight: 30,
  compute: (_ae: AEProfile, activities: Activity[]) => {
    const acv = sumAcv(activities)
    if (acv >= 3000000) return 100
    if (acv >= 2000000) return 85
    if (acv >= 1000000) return 70
    if (acv >= 500000) return 50
    if (acv >= 250000) return 30
    return Math.max(Math.round((acv / 250000) * 30), 0)
  },
}), { locked: true })

registerDimension('content_velocity', () => ({
  id: 'content_velocity',
  name: 'Content Velocity',
  description: 'Decks, one-pagers, RFP responses, and technical validations produced',
  weight: 20,
  compute: (_ae: AEProfile, activities: Activity[]) => {
    const count = countByType(activities, [
      'value_deck_created',
      'one_pager_created',
      'rfp_response',
      'technical_validation',
    ])
    return Math.min(count * 25, 100)
  },
}), { locked: true })

// --- Non-locked optional dimensions ---

registerDimension('deal_diversity', (config) => {
  const threshold = (config?.minDeals as number) ?? 2
  return {
    id: 'deal_diversity',
    name: 'Deal Diversity',
    description: `Unique deals engaged (threshold: ${threshold})`,
    weight: 10,
    compute: (_ae: AEProfile, activities: Activity[]) => {
      const uniqueDeals = new Set(activities.filter((a) => a.dealName).map((a) => a.dealName))
      const count = uniqueDeals.size
      if (count >= threshold * 2) return 100
      if (count >= threshold) return 70
      return Math.round((count / threshold) * 70)
    },
  }
})

registerDimension('recency_bonus', () => ({
  id: 'recency_bonus',
  name: 'Recency Bonus',
  description: 'Extra weight for activities in the last 7 days',
  weight: 10,
  compute: (_ae: AEProfile, activities: Activity[]) => {
    const now = new Date()
    const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
    const recent = activities.filter((a) => new Date(a.date) >= weekAgo).length
    return Math.min(recent * 20, 100)
  },
}))
