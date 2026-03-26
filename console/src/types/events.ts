import type { HealthSnapshot, VPSStatus, DeployStatus, PnLPoint } from './system'
import type { CohortReport } from './cohort'
import type { Hypothesis, HypothesisResult } from './hypothesis'

export type { VPSStatus, PnLPoint }

export interface FillRecord {
  window_start_ts: number
  direction: string
  order_price: number
  trade_size_usd: number
  order_status: string
  resolved_side: string | null
  won: boolean | null
  pnl_usd: number | null
}

export interface MutationEvent {
  type: 'promoted' | 'reverted'
  mutation_id: string
  config_hash: string
  timestamp: string
  reason?: string
}

export interface SafetyEvent {
  type: 'cap_breach' | 'up_live_attempt' | 'config_mismatch' | 'restart_loop' | 'duplicate_window'
  timestamp: string
  details: string
}

export type SystemEvent =
  | { type: 'snapshot'; payload: { health: HealthSnapshot; cohort: CohortReport; hypotheses: Hypothesis[] } }
  | { type: 'fill.live'; payload: FillRecord }
  | { type: 'fill.resolved'; payload: FillRecord }
  | { type: 'hypothesis.created'; payload: Hypothesis }
  | { type: 'hypothesis.tested'; payload: HypothesisResult }
  | { type: 'hypothesis.promoted'; payload: { hypothesis_id: string } }
  | { type: 'hypothesis.killed'; payload: { hypothesis_id: string; reason: string } }
  | { type: 'mutation.promoted'; payload: MutationEvent }
  | { type: 'mutation.reverted'; payload: MutationEvent }
  | { type: 'safety.breach'; payload: SafetyEvent }
  | { type: 'cohort.checkpoint'; payload: CohortReport }
  | { type: 'health.tick'; payload: HealthSnapshot }
  | { type: 'deploy.status'; payload: DeployStatus }
  | { type: 'vps.log'; payload: { line: string; level: 'info' | 'warn' | 'error' } }
  | { type: 'ping' }
