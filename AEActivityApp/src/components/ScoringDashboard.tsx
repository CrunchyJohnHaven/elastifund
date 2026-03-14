import { useMemo, useState } from 'react'
import { getAEs, getActivities } from '../store/ae-data'
import { computeScores, getDimensionBreakdown, DEFAULT_DIMENSIONS } from '../engine/scoring-engine'
import {
  listRegisteredDimensions,
  isDimensionLocked,
  registerExtensions,
  validateExtension,
  type ScoringExtension,
} from '../engine/scoring-registry'

const STORAGE_KEY = 'ae-scorecard-extensions'

function loadExtensions(): ScoringExtension[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveExtensions(exts: ScoringExtension[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(exts))
}

export function ScoringDashboard() {
  const [extensions, setExtensions] = useState<ScoringExtension[]>(() => {
    const exts = loadExtensions()
    if (exts.length > 0) registerExtensions(exts)
    return exts
  })
  const [refreshKey, setRefreshKey] = useState(0)

  // New extension form state
  const [newKey, setNewKey] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newWeight, setNewWeight] = useState('10')
  const [newFormula, setNewFormula] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)

  const allDimensionIds = useMemo(() => listRegisteredDimensions(), [refreshKey])
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>(DEFAULT_DIMENSIONS)

  const dimensions = useMemo(
    () => getDimensionBreakdown(selectedDimensions),
    [selectedDimensions, refreshKey]
  )
  const scores = useMemo(
    () => computeScores(getAEs(), getActivities(), selectedDimensions),
    [selectedDimensions, refreshKey]
  )

  const toggleDimension = (id: string) => {
    setSelectedDimensions((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    )
  }

  const handleAddExtension = () => {
    const ext: ScoringExtension = {
      key: newKey,
      label: newLabel,
      description: newDesc,
      weight: parseFloat(newWeight) || 0,
      formula: newFormula,
    }
    const error = validateExtension(ext)
    if (error) {
      setFormError(error)
      return
    }
    registerExtensions([ext])
    const updated = [...extensions, ext]
    setExtensions(updated)
    saveExtensions(updated)
    setSelectedDimensions((prev) => [...prev, ext.key])
    setNewKey('')
    setNewLabel('')
    setNewDesc('')
    setNewWeight('10')
    setNewFormula('')
    setFormError(null)
    setShowForm(false)
    setRefreshKey((k) => k + 1)
  }

  const handleRemoveExtension = (key: string) => {
    const updated = extensions.filter((e) => e.key !== key)
    setExtensions(updated)
    saveExtensions(updated)
    setSelectedDimensions((prev) => prev.filter((d) => d !== key))
    setRefreshKey((k) => k + 1)
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-brand-body dark:text-white">Scoring Configuration</h2>
        <p className="text-sm text-brand-medium-gray mt-1">
          Configure scoring dimensions and weights. Add custom dimensions via formula extensions.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Dimension selector */}
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-brand-border-gray dark:border-gray-700 p-4">
          <h3 className="text-sm font-semibold text-brand-body dark:text-gray-200 mb-3">Active Dimensions</h3>
          <div className="space-y-2">
            {allDimensionIds.map((id) => {
              const active = selectedDimensions.includes(id)
              const locked = isDimensionLocked(id)
              const isExtension = extensions.some((e) => e.key === id)
              return (
                <div key={id} className="flex items-center gap-2">
                  <label
                    className={`flex-1 flex items-center gap-3 p-2 rounded-md cursor-pointer transition-colors ${
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
                    <span className="text-sm text-brand-body dark:text-gray-300">
                      {id.replace(/_/g, ' ')}
                    </span>
                    {locked && (
                      <span className="text-xs bg-brand-light-bg dark:bg-gray-700 text-brand-medium-gray px-1.5 py-0.5 rounded" title="Core dimension, cannot be removed">
                        locked
                      </span>
                    )}
                    {isExtension && (
                      <span className="text-xs bg-elastic-teal/20 text-elastic-developer dark:text-elastic-teal px-1.5 py-0.5 rounded">
                        ext
                      </span>
                    )}
                  </label>
                  {isExtension && (
                    <button
                      onClick={() => handleRemoveExtension(id)}
                      className="text-xs text-red-500 hover:text-red-700 px-1"
                      aria-label={`Remove extension ${id}`}
                      title="Remove extension"
                    >
                      x
                    </button>
                  )}
                </div>
              )
            })}
          </div>

          <div className="mt-4 pt-3 border-t border-brand-border-gray dark:border-gray-700">
            {!showForm ? (
              <button
                onClick={() => setShowForm(true)}
                className="text-sm text-elastic-blue hover:underline focus:outline-none focus:ring-2 focus:ring-elastic-blue rounded"
              >
                + Add custom dimension
              </button>
            ) : (
              <div className="space-y-2">
                <input
                  type="text"
                  placeholder="key (e.g. rfp_speed)"
                  value={newKey}
                  onChange={(e) => setNewKey(e.target.value)}
                  className="w-full rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-2 py-1 text-xs focus:ring-2 focus:ring-elastic-blue focus:outline-none"
                />
                <input
                  type="text"
                  placeholder="Label (e.g. RFP Speed)"
                  value={newLabel}
                  onChange={(e) => setNewLabel(e.target.value)}
                  className="w-full rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-2 py-1 text-xs focus:ring-2 focus:ring-elastic-blue focus:outline-none"
                />
                <input
                  type="text"
                  placeholder="Description"
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  className="w-full rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-2 py-1 text-xs focus:ring-2 focus:ring-elastic-blue focus:outline-none"
                />
                <input
                  type="number"
                  placeholder="Weight"
                  value={newWeight}
                  onChange={(e) => setNewWeight(e.target.value)}
                  className="w-full rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-2 py-1 text-xs focus:ring-2 focus:ring-elastic-blue focus:outline-none"
                />
                <input
                  type="text"
                  placeholder="Formula: count(rfp_response) * 25"
                  value={newFormula}
                  onChange={(e) => setNewFormula(e.target.value)}
                  className="w-full rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-2 py-1 text-xs focus:ring-2 focus:ring-elastic-blue focus:outline-none font-mono"
                />
                {formError && <p className="text-xs text-red-500">{formError}</p>}
                <div className="flex gap-2">
                  <button
                    onClick={handleAddExtension}
                    className="px-3 py-1 text-xs bg-elastic-blue text-white rounded hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-elastic-blue"
                  >
                    Add
                  </button>
                  <button
                    onClick={() => { setShowForm(false); setFormError(null) }}
                    className="px-3 py-1 text-xs text-brand-medium-gray hover:text-brand-body dark:hover:text-gray-300 focus:outline-none"
                  >
                    Cancel
                  </button>
                </div>
                <p className="text-xs text-brand-medium-gray">
                  Formula functions: count(type), sum_acv, unique_deals, total_activities
                </p>
              </div>
            )}
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
