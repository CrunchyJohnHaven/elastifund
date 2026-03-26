export interface CohortReport {
  generated_at: string
  cohort_id: string
  cohort_status: 'awaiting_deploy' | 'active' | 'completed' | 'killed'
  cohort_start_ts: number | null
  mutation_id: string | null
  config_hash: string | null
  resolved_down_fills: number
  wins: number
  losses: number
  win_rate: number | null
  gross_pnl_usd: number
  estimated_maker_rebate_usd: number
  net_pnl_after_estimated_rebate_usd: number
  avg_entry_price: number | null
  avg_trade_size_usd: number | null
  price_bucket_slice: Record<string, { fills: number; wins: number; win_rate: number | null }>
  hour_slice_et: Record<string, { fills: number; wins: number; win_rate: number | null }>
  fill_rate: number | null
  order_failed_rate: number | null
  partial_fill_count: number
  cancel_count: number
  cap_breach_events: number
  up_live_attempts: number
  config_hash_mismatch_count: number
  checkpoint_status: string
  recommendation: 'awaiting_data' | 'insufficient_data' | 'continue_collecting' | 'positive_first_cohort' | 'kill'
  safety_kill_triggered: boolean
}
