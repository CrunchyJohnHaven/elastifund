import type { ScoringDimension, AEProfile, Activity } from '../types'

type DimensionFactory = (config?: Record<string, unknown>) => ScoringDimension

const registry = new Map<string, DimensionFactory>()

export function registerDimension(id: string, factory: DimensionFactory): void {
  registry.set(id, factory)
}

export function getDimension(id: string, config?: Record<string, unknown>): ScoringDimension | undefined {
  const factory = registry.get(id)
  return factory ? factory(config) : undefined
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
}))

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
}))

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
}))

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
}))

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
