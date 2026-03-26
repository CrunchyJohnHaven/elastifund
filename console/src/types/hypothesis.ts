export type HypothesisStatus = 'idle' | 'testing' | 'promoted' | 'killed' | 'incumbent'

export interface Hypothesis {
  id: string
  status: HypothesisStatus
  params: Record<string, number | string | boolean>
  shadow_pnl: number | null
  win_rate: number | null
  entry_price_range: [number, number] | null
  kill_reason: string | null
  created_at: string
  tested_at: string | null
  iterations: number
  parent_id: string | null
}

export interface HypothesisResult {
  hypothesis_id: string
  shadow_pnl_delta: number
  verdict: 'keep' | 'discard' | 'crash'
  params_changed: string[]
  tested_at: string
}
