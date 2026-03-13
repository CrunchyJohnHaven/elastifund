export interface AEProfile {
  id: string
  name: string
  email: string
  region: string
  territory: string
  team: string
  avatarUrl?: string
}

export interface Activity {
  id: string
  aeId: string
  type: ActivityType
  date: string
  description: string
  dealId?: string
  dealName?: string
  acv?: number
  notes?: string
}

export type ActivityType =
  | 'bvr_created'
  | 'bvr_delivered'
  | 'deal_support'
  | 'customer_meeting'
  | 'value_deck_created'
  | 'one_pager_created'
  | 'rfp_response'
  | 'workshop_delivered'
  | 'executive_briefing'
  | 'technical_validation'

export interface CalendarEvent {
  id: string
  aeId: string
  title: string
  date: string
  endDate?: string
  type: CalendarEventType
  dealId?: string
  location?: string
  attendees?: string[]
}

export type CalendarEventType =
  | 'customer_call'
  | 'internal_review'
  | 'deal_review'
  | 'workshop'
  | 'executive_briefing'
  | 'follow_up'

export interface ScoringDimension {
  id: string
  name: string
  description: string
  weight: number
  compute: (ae: AEProfile, activities: Activity[]) => number
}

export interface AEScore {
  aeId: string
  aeName: string
  region: string
  territory: string
  totalScore: number
  dimensionScores: Record<string, number>
  rank: number
  trend: 'up' | 'down' | 'stable'
}

export interface ScoringConfig {
  dimensions: ScoringDimension[]
  period: 'week' | 'month' | 'quarter'
  startDate: string
  endDate: string
}

export interface LeaderboardFilter {
  region?: string
  territory?: string
  team?: string
  period: 'week' | 'month' | 'quarter'
  activityType?: ActivityType
  minAcv?: number
}

export interface ExportOptions {
  title: string
  subtitle?: string
  period: string
  includeCharts: boolean
  includeDetails: boolean
  brandColor: string
}
