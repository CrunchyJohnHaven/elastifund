export interface HealthSnapshot {
  generated_at: string
  is_bot_running: boolean
  last_fill_ts: number | null
  last_fill_age_minutes: number | null
  rolling_win_rate: number | null
  rolling_wins: number
  rolling_losses: number
  deployed_params: Record<string, string>
  config_hash: string | null
  config_hash_match: boolean
}

export interface VPSStatus {
  jj_live: 'active' | 'inactive' | 'failed' | 'unknown'
  btc_5min_maker: 'active' | 'inactive' | 'failed' | 'unknown'
  last_check: string
  uptime_seconds: number | null
}

export interface DeployStatus {
  timestamp: string
  exit_code: number
  profile: string
  stdout: string
  stderr: string
  success: boolean
}

export interface PnLPoint {
  ts: number
  cumulative_pnl: number
  trade_count: number
  win_count: number
}

export interface SchedulerJob {
  id: string
  next_run: string
  last_run: string | null
  last_result: 'success' | 'error' | null
  interval: string
}
