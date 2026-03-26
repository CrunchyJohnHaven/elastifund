import { create } from 'zustand'
import type { HealthSnapshot, VPSStatus, DeployStatus, PnLPoint, SchedulerJob } from '../types/system'
import type { CohortReport } from '../types/cohort'
import type { Hypothesis } from '../types/hypothesis'
import type { FillRecord, MutationEvent, SafetyEvent } from '../types/events'

interface AppState {
  connectionStatus: 'disconnected' | 'connecting' | 'connected'
  health: HealthSnapshot | null
  cohort: CohortReport | null
  hypotheses: Hypothesis[]
  recentFills: FillRecord[]
  mutations: MutationEvent[]
  safetyEvents: SafetyEvent[]
  deployLog: DeployStatus[]
  vpsStatus: VPSStatus | null
  pnlHistory: PnLPoint[]
  schedulerJobs: SchedulerJob[]
  activeScreen: 'tank' | 'pnl' | 'monte' | 'filter' | 'vps' | 'guide'
  selectedHypothesisId: string | null
  vpsLogLines: Array<{ line: string; level: string; ts: string }>

  setConnectionStatus: (s: 'disconnected' | 'connecting' | 'connected') => void
  setActiveScreen: (s: AppState['activeScreen']) => void
  selectHypothesis: (id: string | null) => void
  mergeSnapshot: (snapshot: Partial<AppState>) => void
  appendFill: (fill: FillRecord) => void
  appendMutation: (m: MutationEvent) => void
  appendSafetyEvent: (e: SafetyEvent) => void
  appendDeployStatus: (d: DeployStatus) => void
  appendVpsLog: (line: string, level: string) => void
  updateHealth: (h: HealthSnapshot) => void
  updateCohort: (c: CohortReport) => void
  updateHypotheses: (h: Hypothesis[]) => void
}

export const useAppStore = create<AppState>((set) => ({
  connectionStatus: 'disconnected',
  health: null,
  cohort: null,
  hypotheses: [],
  recentFills: [],
  mutations: [],
  safetyEvents: [],
  deployLog: [],
  vpsStatus: null,
  pnlHistory: [],
  schedulerJobs: [],
  activeScreen: 'tank',
  selectedHypothesisId: null,
  vpsLogLines: [],

  setConnectionStatus: (s) => set({ connectionStatus: s }),

  setActiveScreen: (s) => set({ activeScreen: s }),

  selectHypothesis: (id) => set({ selectedHypothesisId: id }),

  mergeSnapshot: (snapshot) => set((state) => ({ ...state, ...snapshot })),

  appendFill: (fill) =>
    set((state) => ({
      recentFills: [fill, ...state.recentFills].slice(0, 200),
    })),

  appendMutation: (m) =>
    set((state) => ({
      mutations: [m, ...state.mutations].slice(0, 100),
    })),

  appendSafetyEvent: (e) =>
    set((state) => ({
      safetyEvents: [e, ...state.safetyEvents].slice(0, 100),
    })),

  appendDeployStatus: (d) =>
    set((state) => ({
      deployLog: [d, ...state.deployLog],
    })),

  appendVpsLog: (line, level) =>
    set((state) => ({
      vpsLogLines: [
        { line, level, ts: new Date().toISOString() },
        ...state.vpsLogLines,
      ].slice(0, 500),
    })),

  updateHealth: (h) => set({ health: h }),

  updateCohort: (c) => set({ cohort: c }),

  updateHypotheses: (h) => set({ hypotheses: h }),
}))
