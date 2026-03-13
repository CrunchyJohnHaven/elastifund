import { useMemo, useState } from 'react'
import { getUpcomingEvents, getAEs } from '../store/ae-data'
import type { CalendarEventType } from '../types'

const EVENT_COLORS: Record<CalendarEventType, string> = {
  customer_call: 'bg-elastic-blue text-white',
  internal_review: 'bg-brand-ice text-elastic-developer',
  deal_review: 'bg-elastic-midnight text-white',
  workshop: 'bg-elastic-teal text-elastic-developer',
  executive_briefing: 'bg-elastic-yellow text-elastic-developer',
  follow_up: 'bg-elastic-pink text-white',
}

const EVENT_LABELS: Record<CalendarEventType, string> = {
  customer_call: 'Customer Call',
  internal_review: 'Internal Review',
  deal_review: 'Deal Review',
  workshop: 'Workshop',
  executive_briefing: 'Exec Briefing',
  follow_up: 'Follow-up',
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T12:00:00')
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

function daysUntil(dateStr: string): number {
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const target = new Date(dateStr + 'T12:00:00')
  target.setHours(0, 0, 0, 0)
  return Math.round((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
}

export function CalendarOverlay() {
  const [days, setDays] = useState(14)
  const events = useMemo(() => getUpcomingEvents(days), [days])
  const aes = useMemo(() => getAEs(), [])
  const aeMap = useMemo(() => new Map(aes.map((ae) => [ae.id, ae])), [aes])

  const grouped = useMemo(() => {
    const groups = new Map<string, typeof events>()
    for (const e of events) {
      const existing = groups.get(e.date) ?? []
      existing.push(e)
      groups.set(e.date, existing)
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [events])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-brand-body dark:text-white">Calendar Overlay</h2>
          <p className="text-sm text-brand-medium-gray mt-1">Upcoming VE activities and customer engagements</p>
        </div>
        <div className="flex gap-2">
          {[7, 14, 30].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-elastic-blue ${
                days === d
                  ? 'bg-elastic-blue text-white'
                  : 'bg-brand-light-bg dark:bg-gray-700 text-brand-body dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
              aria-pressed={days === d}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {grouped.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-brand-border-gray dark:border-gray-700 p-12 text-center text-brand-medium-gray">
          No events in the next {days} days.
        </div>
      ) : (
        <div className="space-y-6">
          {grouped.map(([date, dayEvents]) => {
            const d = daysUntil(date)
            const label = d === 0 ? 'Today' : d === 1 ? 'Tomorrow' : `In ${d} days`

            return (
              <div key={date}>
                <div className="flex items-baseline gap-3 mb-3">
                  <h3 className="text-lg font-semibold text-brand-body dark:text-white">{formatDate(date)}</h3>
                  <span className="text-xs text-brand-medium-gray">{label}</span>
                </div>
                <div className="space-y-2">
                  {dayEvents.map((event) => {
                    const ae = aeMap.get(event.aeId)
                    return (
                      <div
                        key={event.id}
                        className="bg-white dark:bg-gray-800 rounded-lg border border-brand-border-gray dark:border-gray-700 p-4 flex items-start gap-4 hover:shadow-sm transition-shadow"
                      >
                        <span
                          className={`inline-flex px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap ${EVENT_COLORS[event.type]}`}
                        >
                          {EVENT_LABELS[event.type]}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-brand-body dark:text-white">{event.title}</div>
                          <div className="text-sm text-brand-medium-gray mt-1">
                            {ae ? `${ae.name} (${ae.territory})` : 'Unknown AE'}
                          </div>
                          {event.attendees && event.attendees.length > 0 && (
                            <div className="text-xs text-brand-medium-gray mt-1">
                              Attendees: {event.attendees.join(', ')}
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
