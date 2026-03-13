import { seedAEs, seedActivities, seedCalendarEvents } from '../data/seed-data'
import type { AEProfile, Activity, CalendarEvent, LeaderboardFilter } from '../types'

let aes: AEProfile[] = [...seedAEs]
let activities: Activity[] = [...seedActivities]
let calendarEvents: CalendarEvent[] = [...seedCalendarEvents]

export function getAEs(): AEProfile[] {
  return aes
}

export function getActivities(): Activity[] {
  return activities
}

export function getCalendarEvents(): CalendarEvent[] {
  return calendarEvents
}

export function getFilteredActivities(filter: LeaderboardFilter): Activity[] {
  let filtered = [...activities]

  if (filter.activityType) {
    filtered = filtered.filter((a) => a.type === filter.activityType)
  }

  if (filter.minAcv) {
    filtered = filtered.filter((a) => (a.acv ?? 0) >= filter.minAcv!)
  }

  if (filter.period) {
    const now = new Date()
    let start: Date
    switch (filter.period) {
      case 'week':
        start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
        break
      case 'month':
        start = new Date(now.getFullYear(), now.getMonth() - 1, now.getDate())
        break
      case 'quarter':
        start = new Date(now.getFullYear(), now.getMonth() - 3, now.getDate())
        break
    }
    filtered = filtered.filter((a) => new Date(a.date) >= start)
  }

  if (filter.region || filter.territory || filter.team) {
    const matchingAeIds = new Set(
      aes
        .filter((ae) => {
          if (filter.region && ae.region !== filter.region) return false
          if (filter.territory && ae.territory !== filter.territory) return false
          if (filter.team && ae.team !== filter.team) return false
          return true
        })
        .map((ae) => ae.id)
    )
    filtered = filtered.filter((a) => matchingAeIds.has(a.aeId))
  }

  return filtered
}

export function getFilterOptions() {
  const regions = [...new Set(aes.map((ae) => ae.region))].sort()
  const territories = [...new Set(aes.map((ae) => ae.territory))].sort()
  const teams = [...new Set(aes.map((ae) => ae.team))].sort()
  return { regions, territories, teams }
}

export function getUpcomingEvents(days: number = 14): CalendarEvent[] {
  const now = new Date()
  const end = new Date(now.getTime() + days * 24 * 60 * 60 * 1000)
  return calendarEvents
    .filter((e) => {
      const d = new Date(e.date)
      return d >= now && d <= end
    })
    .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
}

export function addActivity(activity: Activity): void {
  activities = [...activities, activity]
}

export function addCalendarEvent(event: CalendarEvent): void {
  calendarEvents = [...calendarEvents, event]
}
