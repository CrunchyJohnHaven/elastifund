import { useMemo, useState } from 'react'
import { getAEs, getActivities } from '../store/ae-data'
import { computeScores, getDimensionBreakdown, DEFAULT_DIMENSIONS } from '../engine/scoring-engine'
import { listRegisteredDimensions } from '../engine/scoring-registry'

export function ScoringDashboard() {
  const allDimensionIds = useMemo(() => listRegisteredDimensions(), [])
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>(DEFAULT_DIMENSIONS)

  const dimensions = useMemo(
    () => getDimensionBreakdown(selectedDimensions),
    [selectedDimensions]
  )
  const scores = useMemo(
    () => computeScores(getAEs(), getActivities(), selectedDimensions),
    [selectedDimensions]
  )

  const toggleDimension = (id: string) => {
    setSelectedDimensions((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    )
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-brand-body dark:text-white">Scoring Configuration</h2>
        <p className="text-sm text-brand-medium-gray mt-1">
          Configure scoring dimensions and weights. The registry supports custom dimensions.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Dimension selector */}
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-brand-border-gray dark:border-gray-700 p-4">
          <h3 className="text-sm font-semibold text-brand-body dark:text-gray-200 mb-3">Active Dimensions</h3>
          <div className="space-y-2">
            {allDimensionIds.map((id) => {
              const active = selectedDimensions.includes(id)
              return (
                <label
                  key={id}
                  className={`flex items-center gap-3 p-2 rounded-md cursor-pointer transition-colors ${
                    active ? 'bg-blue-50 dark:bg-blue-900/20' : 'hover:bg-brand-light-bg dark:hover:bg-gray-700'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() => toggleDimension(id)}
                    className="rounded border-brand-border-gray text-elastic-blue focus:ring-elastic-blue"
                    aria-label={`Toggle ${id}`}
                  />
                  <span className="text-sm text-brand-body dark:text-gray-300">{id.replace(/_/g, ' ')}</span>
                </label>
              )
            })}
          </div>
        </div>

        {/* Dimension details */}
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-brand-border-gray dark:border-gray-700 p-4">
          <h3 className="text-sm font-semibold text-brand-body dark:text-gray-200 mb-3">Weight Distribution</h3>
          {dimensions.length === 0 ? (
            <p className="text-sm text-brand-medium-gray">Select at least one dimension.</p>
          ) : (
            <div className="space-y-3">
              {dimensions.map((d) => {
                const totalWeight = dimensions.reduce((s, dd) => s + dd.weight, 0)
                const pct = Math.round((d.weight / totalWeight) * 100)
                return (
                  <div key={d.id}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-brand-body dark:text-gray-300">{d.name}</span>
                      <span className="text-brand-medium-gray">{pct}%</span>
                    </div>
                    <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-elastic-blue rounded-full"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <p className="text-xs text-brand-medium-gray mt-1">{d.description}</p>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Score preview */}
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-brand-border-gray dark:border-gray-700 p-4">
          <h3 className="text-sm font-semibold text-brand-body dark:text-gray-200 mb-3">Score Preview</h3>
          {scores.length === 0 ? (
            <p className="text-sm text-brand-medium-gray">No scores to display.</p>
          ) : (
            <div className="space-y-2">
              {scores.map((s) => (
                <div key={s.aeId} className="flex items-center justify-between py-1.5 border-b border-brand-border-gray dark:border-gray-700 last:border-0">
                  <div>
                    <span className="text-sm font-medium text-brand-body dark:text-white">{s.aeName}</span>
                    <span className="text-xs text-brand-medium-gray ml-2">{s.region}</span>
                  </div>
                  <span className={`text-sm font-bold ${
                    s.totalScore >= 70 ? 'text-green-600' :
                    s.totalScore >= 50 ? 'text-elastic-yellow' :
                    'text-red-500'
                  }`}>
                    {s.totalScore}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
