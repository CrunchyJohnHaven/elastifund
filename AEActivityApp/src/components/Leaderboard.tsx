import { useState, useMemo } from 'react'
import type { LeaderboardFilter as FilterType } from '../types'
import { getAEs, getFilteredActivities } from '../store/ae-data'
import { computeScores } from '../engine/scoring-engine'
import { LeaderboardFilterPanel } from './LeaderboardFilter'

function trendIcon(trend: 'up' | 'down' | 'stable') {
  switch (trend) {
    case 'up': return <span className="text-green-600" aria-label="Trending up">&#9650;</span>
    case 'down': return <span className="text-red-500" aria-label="Trending down">&#9660;</span>
    default: return <span className="text-brand-medium-gray" aria-label="Stable">&#8212;</span>
  }
}

function rankBadge(rank: number) {
  if (rank === 1) return <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-elastic-yellow text-elastic-developer font-bold text-sm">1</span>
  if (rank === 2) return <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-brand-ice text-elastic-developer font-bold text-sm">2</span>
  if (rank === 3) return <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-elastic-pink text-white font-bold text-sm">3</span>
  return <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-brand-light-bg dark:bg-gray-700 text-brand-body dark:text-gray-300 font-medium text-sm">{rank}</span>
}

function scoreBar(score: number) {
  let color = 'bg-red-400'
  if (score >= 70) color = 'bg-green-500'
  else if (score >= 50) color = 'bg-elastic-yellow'
  else if (score >= 30) color = 'bg-orange-400'

  return (
    <div className="flex items-center gap-2 min-w-[120px]">
      <div className="flex-1 h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden" role="progressbar" aria-valuenow={score} aria-valuemin={0} aria-valuemax={100}>
        <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-sm font-semibold text-brand-body dark:text-gray-200 w-8 text-right">{score}</span>
    </div>
  )
}

export function Leaderboard() {
  const [filter, setFilter] = useState<FilterType>({ period: 'quarter' })

  const scores = useMemo(() => {
    const aes = getAEs()
    const activities = getFilteredActivities(filter)
    return computeScores(aes, activities)
  }, [filter])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-brand-body dark:text-white">AE Activity Leaderboard</h2>
          <p className="text-sm text-brand-medium-gray mt-1">Value Engineering engagement scores across Public Sector</p>
        </div>
        <div className="text-right">
          <div className="text-3xl font-bold text-elastic-blue">{scores.length}</div>
          <div className="text-xs text-brand-medium-gray">Active AEs</div>
        </div>
      </div>

      <LeaderboardFilterPanel filter={filter} onChange={setFilter} />

      <div className="bg-white dark:bg-gray-800 rounded-lg border border-brand-border-gray dark:border-gray-700 overflow-hidden">
        <table className="w-full" role="table">
          <thead>
            <tr className="bg-brand-light-bg dark:bg-gray-900">
              <th className="px-4 py-3 text-left text-xs font-semibold text-brand-medium-gray uppercase tracking-wider" scope="col">Rank</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-brand-medium-gray uppercase tracking-wider" scope="col">Name</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-brand-medium-gray uppercase tracking-wider hidden sm:table-cell" scope="col">Region</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-brand-medium-gray uppercase tracking-wider hidden md:table-cell" scope="col">Territory</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-brand-medium-gray uppercase tracking-wider" scope="col">Score</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-brand-medium-gray uppercase tracking-wider" scope="col">Trend</th>
            </tr>
          </thead>
          <tbody>
            {scores.map((s, i) => (
              <tr
                key={s.aeId}
                className={`border-t border-brand-border-gray dark:border-gray-700 ${i % 2 === 0 ? '' : 'bg-brand-light-bg dark:bg-gray-850'} hover:bg-blue-50 dark:hover:bg-gray-750 transition-colors`}
              >
                <td className="px-4 py-3">{rankBadge(s.rank)}</td>
                <td className="px-4 py-3">
                  <div className="font-medium text-brand-body dark:text-white">{s.aeName}</div>
                </td>
                <td className="px-4 py-3 text-sm text-brand-medium-gray hidden sm:table-cell">{s.region}</td>
                <td className="px-4 py-3 text-sm text-brand-medium-gray hidden md:table-cell">{s.territory}</td>
                <td className="px-4 py-3">{scoreBar(s.totalScore)}</td>
                <td className="px-4 py-3">{trendIcon(s.trend)}</td>
              </tr>
            ))}
            {scores.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-brand-medium-gray">
                  No activity data for the selected filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
