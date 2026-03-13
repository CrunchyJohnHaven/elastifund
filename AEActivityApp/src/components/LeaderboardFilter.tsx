import { useState } from 'react'
import type { LeaderboardFilter as FilterType, ActivityType } from '../types'
import { getFilterOptions } from '../store/ae-data'

const ACTIVITY_TYPES: { value: ActivityType; label: string }[] = [
  { value: 'bvr_created', label: 'BVR Created' },
  { value: 'bvr_delivered', label: 'BVR Delivered' },
  { value: 'deal_support', label: 'Deal Support' },
  { value: 'customer_meeting', label: 'Customer Meeting' },
  { value: 'value_deck_created', label: 'Value Deck' },
  { value: 'one_pager_created', label: 'One-Pager' },
  { value: 'rfp_response', label: 'RFP Response' },
  { value: 'workshop_delivered', label: 'Workshop' },
  { value: 'executive_briefing', label: 'Executive Briefing' },
  { value: 'technical_validation', label: 'Technical Validation' },
]

interface Props {
  filter: FilterType
  onChange: (filter: FilterType) => void
}

export function LeaderboardFilterPanel({ filter, onChange }: Props) {
  const { regions, territories } = getFilterOptions()
  const [expanded, setExpanded] = useState(false)

  const update = (patch: Partial<FilterType>) => onChange({ ...filter, ...patch })

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-brand-border-gray dark:border-gray-700 p-4 mb-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-brand-body dark:text-gray-200">Filters</h3>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-elastic-blue hover:underline focus:outline-none focus:ring-2 focus:ring-elastic-blue rounded"
          aria-expanded={expanded}
          aria-controls="filter-panel"
        >
          {expanded ? 'Collapse' : 'Expand'}
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        <select
          value={filter.period}
          onChange={(e) => update({ period: e.target.value as FilterType['period'] })}
          className="rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-3 py-1.5 text-sm focus:ring-2 focus:ring-elastic-blue focus:outline-none"
          aria-label="Time period"
        >
          <option value="week">This Week</option>
          <option value="month">This Month</option>
          <option value="quarter">This Quarter</option>
        </select>

        <select
          value={filter.region ?? ''}
          onChange={(e) => update({ region: e.target.value || undefined })}
          className="rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-3 py-1.5 text-sm focus:ring-2 focus:ring-elastic-blue focus:outline-none"
          aria-label="Region"
        >
          <option value="">All Regions</option>
          {regions.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>

        <select
          value={filter.territory ?? ''}
          onChange={(e) => update({ territory: e.target.value || undefined })}
          className="rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-3 py-1.5 text-sm focus:ring-2 focus:ring-elastic-blue focus:outline-none"
          aria-label="Territory"
        >
          <option value="">All Territories</option>
          {territories.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {expanded && (
        <div id="filter-panel" className="mt-4 flex flex-wrap gap-3">
          <select
            value={filter.activityType ?? ''}
            onChange={(e) => update({ activityType: (e.target.value || undefined) as ActivityType | undefined })}
            className="rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-3 py-1.5 text-sm focus:ring-2 focus:ring-elastic-blue focus:outline-none"
            aria-label="Activity type"
          >
            <option value="">All Activity Types</option>
            {ACTIVITY_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>

          <input
            type="number"
            placeholder="Min ACV ($)"
            value={filter.minAcv ?? ''}
            onChange={(e) => update({ minAcv: e.target.value ? Number(e.target.value) : undefined })}
            className="rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-3 py-1.5 text-sm w-36 focus:ring-2 focus:ring-elastic-blue focus:outline-none"
            aria-label="Minimum ACV"
          />

          <button
            onClick={() => onChange({ period: 'month' })}
            className="text-xs text-elastic-pink hover:underline focus:outline-none focus:ring-2 focus:ring-elastic-pink rounded px-2 py-1"
          >
            Reset All
          </button>
        </div>
      )}
    </div>
  )
}
