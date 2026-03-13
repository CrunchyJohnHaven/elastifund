import type { AEProfile, Activity, AEScore, ScoringDimension } from '../types'
import { buildScoringConfig } from './scoring-registry'

export const DEFAULT_DIMENSIONS = [
  'bvr_output',
  'customer_engagement',
  'pipeline_impact',
  'content_velocity',
]

export function computeScores(
  aes: AEProfile[],
  activities: Activity[],
  dimensionIds: string[] = DEFAULT_DIMENSIONS,
  dimensionConfigs?: Record<string, Record<string, unknown>>,
  previousScores?: Map<string, number>
): AEScore[] {
  const dimensions = buildScoringConfig(dimensionIds, dimensionConfigs)
  if (dimensions.length === 0) return []

  const totalWeight = dimensions.reduce((sum, d) => sum + d.weight, 0)

  const scores: AEScore[] = aes.map((ae) => {
    const aeActivities = activities.filter((a) => a.aeId === ae.id)
    const dimensionScores: Record<string, number> = {}

    let weighted = 0
    for (const dim of dimensions) {
      const raw = dim.compute(ae, aeActivities)
      const clamped = Math.max(0, Math.min(100, raw))
      dimensionScores[dim.id] = clamped
      weighted += clamped * (dim.weight / totalWeight)
    }

    const totalScore = Math.round(weighted)
    const prev = previousScores?.get(ae.id)
    let trend: 'up' | 'down' | 'stable' = 'stable'
    if (prev !== undefined) {
      if (totalScore > prev + 2) trend = 'up'
      else if (totalScore < prev - 2) trend = 'down'
    }

    return {
      aeId: ae.id,
      aeName: ae.name,
      region: ae.region,
      territory: ae.territory,
      totalScore,
      dimensionScores,
      rank: 0,
      trend,
    }
  })

  scores.sort((a, b) => b.totalScore - a.totalScore)
  scores.forEach((s, i) => {
    s.rank = i + 1
  })

  return scores
}

export function getDimensionBreakdown(
  dimensionIds: string[] = DEFAULT_DIMENSIONS,
  dimensionConfigs?: Record<string, Record<string, unknown>>
): ScoringDimension[] {
  return buildScoringConfig(dimensionIds, dimensionConfigs)
}
