import { useState, useMemo } from 'react'
import { getAEs, getActivities, getCalendarEvents } from '../store/ae-data'
import { computeScores, getDimensionBreakdown, DEFAULT_DIMENSIONS } from '../engine/scoring-engine'
import { exportToPDF, exportSingleAEPDF, exportBatchPDFs } from '../engine/pdf-export'

type ExportMode = 'summary' | 'single' | 'batch'

export function PDFExport() {
  const [exporting, setExporting] = useState(false)
  const [includeDetails, setIncludeDetails] = useState(true)
  const [title, setTitle] = useState('AE Activity Report')
  const [subtitle, setSubtitle] = useState('Elastic Public Sector Value Engineering')
  const [mode, setMode] = useState<ExportMode>('summary')
  const [selectedAeId, setSelectedAeId] = useState<string>('')
  const [quarter, setQuarter] = useState('FY26Q3')

  const aes = useMemo(() => getAEs(), [])
  const activities = useMemo(() => getActivities(), [])
  const scores = useMemo(() => computeScores(aes, activities), [aes, activities])
  const dimensions = useMemo(() => getDimensionBreakdown(DEFAULT_DIMENSIONS), [])
  const events = useMemo(() => getCalendarEvents(), [])

  const downloadBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      if (mode === 'summary') {
        const blob = await exportToPDF(scores, dimensions, events, {
          title,
          subtitle,
          period: `Generated ${new Date().toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}`,
          includeCharts: true,
          includeDetails,
          brandColor: '#0B64DD',
        })
        downloadBlob(blob, `ae_activity_report_${new Date().toISOString().slice(0, 10)}.pdf`)
      } else if (mode === 'single') {
        const ae = aes.find((a) => a.id === selectedAeId)
        const score = scores.find((s) => s.aeId === selectedAeId)
        if (!ae || !score) return
        const blob = await exportSingleAEPDF(ae, score, dimensions, activities, events, quarter)
        const safeName = ae.name.replace(/\s+/g, '_')
        downloadBlob(blob, `AE_Scorecard_${safeName}_${quarter}.pdf`)
      } else {
        const blob = await exportBatchPDFs(aes, scores, dimensions, activities, events, quarter)
        downloadBlob(blob, `AE_Scorecards_Batch_${quarter}.zip`)
      }
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
        <p className="text-sm text-brand-medium-gray mt-1">Generate branded PDF reports of AE activity scores</p>
      </div>

      <div className="max-w-lg bg-white dark:bg-gray-800 rounded-lg border border-brand-border-gray dark:border-gray-700 p-6">
        <div className="space-y-4">
          {/* Export mode selector */}
          <div>
            <label className="block text-sm font-medium text-brand-body dark:text-gray-200 mb-2">
              Export Type
            </label>
            <div className="flex gap-2">
              {([
                { value: 'summary' as ExportMode, label: 'Summary Report' },
                { value: 'single' as ExportMode, label: 'Single AE' },
                { value: 'batch' as ExportMode, label: 'Batch (ZIP)' },
              ]).map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setMode(opt.value)}
                  className={`px-3 py-1.5 text-sm rounded-md border transition-colors focus:outline-none focus:ring-2 focus:ring-elastic-blue ${
                    mode === opt.value
                      ? 'bg-elastic-blue text-white border-elastic-blue'
                      : 'border-brand-border-gray dark:border-gray-600 text-brand-body dark:text-gray-300 hover:bg-brand-light-bg dark:hover:bg-gray-700'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Summary report options */}
          {mode === 'summary' && (
            <>
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
            </>
          )}

          {/* Single AE selector */}
          {mode === 'single' && (
            <div>
              <label htmlFor="ae-select" className="block text-sm font-medium text-brand-body dark:text-gray-200 mb-1">
                Select AE
              </label>
              <select
                id="ae-select"
                value={selectedAeId}
                onChange={(e) => setSelectedAeId(e.target.value)}
                className="w-full rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-3 py-2 text-sm focus:ring-2 focus:ring-elastic-blue focus:outline-none"
              >
                <option value="">Choose an AE...</option>
                {aes.map((ae) => {
                  const s = scores.find((sc) => sc.aeId === ae.id)
                  return (
                    <option key={ae.id} value={ae.id}>
                      {ae.name} ({ae.territory}) {s ? `- Score: ${s.totalScore}` : ''}
                    </option>
                  )
                })}
              </select>
            </div>
          )}

          {/* Quarter selector for single/batch */}
          {(mode === 'single' || mode === 'batch') && (
            <div>
              <label htmlFor="quarter-select" className="block text-sm font-medium text-brand-body dark:text-gray-200 mb-1">
                Quarter
              </label>
              <select
                id="quarter-select"
                value={quarter}
                onChange={(e) => setQuarter(e.target.value)}
                className="w-full rounded border border-brand-border-gray dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 px-3 py-2 text-sm focus:ring-2 focus:ring-elastic-blue focus:outline-none"
              >
                <option value="FY26Q3">FY26 Q3</option>
                <option value="FY26Q2">FY26 Q2</option>
                <option value="FY26Q1">FY26 Q1</option>
              </select>
            </div>
          )}

          <div className="pt-4 border-t border-brand-border-gray dark:border-gray-700">
            <div className="text-sm text-brand-medium-gray mb-3">
              {mode === 'summary' && (
                <>Report includes: {scores.length} AEs, {dimensions.length} scoring dimensions, {events.length} calendar events</>
              )}
              {mode === 'single' && selectedAeId && (
                <>Scorecard for {aes.find((a) => a.id === selectedAeId)?.name ?? 'selected AE'} with dimension breakdown, activity log, and upcoming events</>
              )}
              {mode === 'batch' && (
                <>Batch export: {aes.length} individual AE scorecards bundled as ZIP</>
              )}
            </div>
            <button
              onClick={handleExport}
              disabled={exporting || (mode === 'single' && !selectedAeId)}
              className="w-full py-2.5 px-4 rounded-md bg-elastic-blue text-white font-medium text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-elastic-blue focus:ring-offset-2"
            >
              {exporting
                ? mode === 'batch' ? 'Generating ZIP...' : 'Generating PDF...'
                : mode === 'batch' ? 'Download Batch ZIP' : 'Download PDF Report'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
