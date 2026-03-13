import { useState, useMemo } from 'react'
import { getAEs, getActivities, getCalendarEvents } from '../store/ae-data'
import { computeScores, getDimensionBreakdown, DEFAULT_DIMENSIONS } from '../engine/scoring-engine'
import { exportToPDF } from '../engine/pdf-export'

export function PDFExport() {
  const [exporting, setExporting] = useState(false)
  const [includeDetails, setIncludeDetails] = useState(true)
  const [title, setTitle] = useState('AE Activity Report')
  const [subtitle, setSubtitle] = useState('Elastic Public Sector Value Engineering')

  const scores = useMemo(() => computeScores(getAEs(), getActivities()), [])
  const dimensions = useMemo(() => getDimensionBreakdown(DEFAULT_DIMENSIONS), [])
  const events = useMemo(() => getCalendarEvents(), [])

  const handleExport = async () => {
    setExporting(true)
    try {
      const blob = await exportToPDF(scores, dimensions, events, {
        title,
        subtitle,
        period: `Generated ${new Date().toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}`,
        includeCharts: true,
        includeDetails,
        brandColor: '#0B64DD',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `ae_activity_report_${new Date().toISOString().slice(0, 10)}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('PDF export failed:', err)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-brand-body dark:text-white">Export Report</h2>
        <p className="text-sm text-brand-medium-gray mt-1">Generate a branded PDF report of AE activity scores</p>
      </div>

      <div className="max-w-lg bg-white dark:bg-gray-800 rounded-lg border border-brand-border-gray dark:border-gray-700 p-6">
        <div className="space-y-4">
          <div>
            <label htmlFor="pdf-title" className="block text-sm font-medium text-brand-body dark:text-gray-200 mb-1">
              Report Title
            </label>
            <input
              id="pdf-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-3 py-2 text-sm focus:ring-2 focus:ring-elastic-blue focus:outline-none"
            />
          </div>

          <div>
            <label htmlFor="pdf-subtitle" className="block text-sm font-medium text-brand-body dark:text-gray-200 mb-1">
              Subtitle
            </label>
            <input
              id="pdf-subtitle"
              type="text"
              value={subtitle}
              onChange={(e) => setSubtitle(e.target.value)}
              className="w-full rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-3 py-2 text-sm focus:ring-2 focus:ring-elastic-blue focus:outline-none"
            />
          </div>

          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={includeDetails}
              onChange={(e) => setIncludeDetails(e.target.checked)}
              className="rounded border-brand-border-gray text-elastic-blue focus:ring-elastic-blue"
            />
            <span className="text-sm text-brand-body dark:text-gray-300">Include dimension breakdown and per-AE details</span>
          </label>

          <div className="pt-4 border-t border-brand-border-gray dark:border-gray-700">
            <div className="text-sm text-brand-medium-gray mb-3">
              Report includes: {scores.length} AEs, {dimensions.length} scoring dimensions, {events.length} calendar events
            </div>
            <button
              onClick={handleExport}
              disabled={exporting}
              className="w-full py-2.5 px-4 rounded-md bg-elastic-blue text-white font-medium text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-elastic-blue focus:ring-offset-2"
            >
              {exporting ? 'Generating PDF...' : 'Download PDF Report'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
