import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useAppStore } from './store/useAppStore'
import { socket } from './lib/socket'
import { api } from './lib/api'
import { colors } from './theme/colors'
import type { HealthSnapshot } from './types/system'
import type { CohortReport } from './types/cohort'
import type { SystemEvent } from './types/events'

// Layout components
import { TopBar } from './components/TopBar'
import { LeftRail } from './components/LeftRail'
import { RightRail } from './components/RightRail'
import { BottomBar } from './components/BottomBar'

// Screen components
import { TankScreen } from './components/screens/TankScreen'
import { PnLScreen } from './components/screens/PnLScreen'
import { MonteCarloScreen } from './components/screens/MonteCarloScreen'
import { FilterScreen } from './components/screens/FilterScreen'
import { VPSScreen } from './components/screens/VPSScreen'
import { GuideScreen } from './components/screens/GuideScreen'

const SCREEN_MAP = {
  tank: TankScreen,
  pnl: PnLScreen,
  monte: MonteCarloScreen,
  filter: FilterScreen,
  vps: VPSScreen,
  guide: GuideScreen,
} as const

export default function App() {
  const {
    activeScreen,
    setConnectionStatus,
    mergeSnapshot,
    updateHealth,
    updateCohort,
    updateHypotheses,
    appendFill,
    appendMutation,
    appendSafetyEvent,
    appendDeployStatus,
    appendVpsLog,
  } = useAppStore()

  useEffect(() => {
    // Wire WebSocket connection status to store
    const unsubStatus = socket.onStatus((status) => {
      setConnectionStatus(status)
    })

    // Wire WebSocket events to store
    const unsubEvents = socket.onEvent((event: SystemEvent) => {
      switch (event.type) {
        case 'snapshot':
          mergeSnapshot({
            health: event.payload.health,
            cohort: event.payload.cohort,
            hypotheses: event.payload.hypotheses,
          })
          break
        case 'health.tick':
          updateHealth(event.payload)
          break
        case 'cohort.checkpoint':
          updateCohort(event.payload)
          break
        case 'fill.live':
        case 'fill.resolved':
          appendFill(event.payload)
          break
        case 'mutation.promoted':
        case 'mutation.reverted':
          appendMutation(event.payload)
          break
        case 'safety.breach':
          appendSafetyEvent(event.payload)
          break
        case 'deploy.status':
          appendDeployStatus(event.payload)
          break
        case 'vps.log':
          appendVpsLog(event.payload.line, event.payload.level)
          break
        case 'hypothesis.created':
        case 'hypothesis.tested':
        case 'hypothesis.promoted':
        case 'hypothesis.killed':
          // Hypothesis events trigger a re-fetch of the full hypotheses list
          api.get<{ hypotheses: unknown[] }>('/hypotheses')
            .then((res) => {
              if (Array.isArray(res)) updateHypotheses(res as Parameters<typeof updateHypotheses>[0])
              else if (res && Array.isArray((res as Record<string, unknown>).hypotheses))
                updateHypotheses((res as Record<string, unknown>).hypotheses as Parameters<typeof updateHypotheses>[0])
            })
            .catch(() => {/* non-fatal */})
          break
        default:
          break
      }
    })

    // Connect WebSocket
    socket.connect()

    // Fetch initial data
    api.get<HealthSnapshot>('/health')
      .then(updateHealth)
      .catch(() => {/* server may not be running */})

    api.get<CohortReport>('/cohort')
      .then(updateCohort)
      .catch(() => {/* server may not be running */})

    return () => {
      unsubStatus()
      unsubEvents()
      socket.close()
    }
  }, [
    setConnectionStatus,
    mergeSnapshot,
    updateHealth,
    updateCohort,
    updateHypotheses,
    appendFill,
    appendMutation,
    appendSafetyEvent,
    appendDeployStatus,
    appendVpsLog,
  ])

  const ActiveScreen = SCREEN_MAP[activeScreen]

  return (
    <div
      style={{ height: '100vh', width: '100vw', display: 'flex', flexDirection: 'column', background: colors.bg, color: colors.textPrimary, overflow: 'hidden' }}
    >
      {/* TopBar */}
      <div style={{ height: 64, flexShrink: 0 }}>
        <TopBar />
      </div>

      {/* Main content area */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {/* LeftRail */}
        <div style={{ width: 220, flexShrink: 0 }}>
          <LeftRail />
        </div>

        {/* Main screen with AnimatePresence transitions */}
        <main
          style={{ flex: 1, overflow: 'hidden', position: 'relative', padding: 0 }}
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={activeScreen}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              style={{ position: 'absolute', inset: 0 }}
            >
              <ActiveScreen />
            </motion.div>
          </AnimatePresence>
        </main>

        {/* RightRail */}
        <div style={{ width: 320, flexShrink: 0 }}>
          <RightRail />
        </div>
      </div>

      {/* BottomBar */}
      <div style={{ height: 48, flexShrink: 0 }}>
        <BottomBar />
      </div>
    </div>
  )
}
