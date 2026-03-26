import React, { useState, useEffect, useRef } from 'react'
import { Rocket, Loader2, CheckCircle2, XCircle, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '../../lib/api'
import { colors } from '../../theme/colors'

interface DeployResult {
  success: boolean
  exit_code: number
  stdout: string
  stderr: string
}

interface DeployButtonProps {
  lastDeployTime?: string
}

export const DeployButton: React.FC<DeployButtonProps> = ({ lastDeployTime }) => {
  const [deploying, setDeploying] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [stdout, setStdout] = useState<string[]>([])
  const [result, setResult] = useState<DeployResult | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const logRef = useRef<HTMLDivElement>(null)

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [stdout])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  async function handleDeploy() {
    setDeploying(true)
    setShowModal(true)
    setStdout([])
    setResult(null)

    try {
      const res = await api.post<DeployResult>('/deploy')
      // If the API returns immediately with full result (sync deploy)
      if (res && typeof res === 'object' && 'success' in res) {
        if (res.stdout) {
          setStdout(res.stdout.split('\n'))
        }
        setResult(res)
        setDeploying(false)
        return
      }

      // Async mode: poll for status
      let ticks = 0
      pollRef.current = setInterval(async () => {
        ticks++
        if (ticks > 120) {
          // 60 second timeout
          if (pollRef.current) clearInterval(pollRef.current)
          setResult({ success: false, exit_code: -1, stdout: '', stderr: 'Timed out waiting for deploy.' })
          setDeploying(false)
          return
        }
        try {
          const status = await api.get<{ done: boolean; stdout: string; exit_code: number; success: boolean }>('/deploy/status')
          if (status.stdout) {
            setStdout(status.stdout.split('\n'))
          }
          if (status.done) {
            if (pollRef.current) clearInterval(pollRef.current)
            setResult({ success: status.success, exit_code: status.exit_code, stdout: status.stdout, stderr: '' })
            setDeploying(false)
          }
        } catch {
          // polling transient error, keep going
        }
      }, 500)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setResult({ success: false, exit_code: -1, stdout: '', stderr: msg })
      setDeploying(false)
    }
  }

  function handleClose() {
    if (!deploying) {
      setShowModal(false)
      setResult(null)
      setStdout([])
    }
  }

  const lastDeployFormatted = lastDeployTime
    ? new Date(lastDeployTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null

  return (
    <>
      <div>
        <button
          onClick={handleDeploy}
          disabled={deploying}
          className="w-full flex items-center justify-center gap-2 rounded text-sm font-medium transition-colors"
          style={{
            height: 36,
            background: deploying ? '#0952B8' : colors.elasticBlue,
            color: '#fff',
            border: 'none',
            cursor: deploying ? 'not-allowed' : 'pointer',
            opacity: deploying ? 0.8 : 1,
          }}
          onMouseEnter={(e) => {
            if (!deploying) (e.currentTarget as HTMLButtonElement).style.background = '#0952B8'
          }}
          onMouseLeave={(e) => {
            if (!deploying) (e.currentTarget as HTMLButtonElement).style.background = colors.elasticBlue
          }}
        >
          {deploying ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Rocket size={14} />
          )}
          <span>{deploying ? 'Deploying...' : 'Deploy to VPS'}</span>
        </button>
        {lastDeployFormatted && !deploying && (
          <div className="mt-0.5 text-xs text-center" style={{ color: colors.textMuted }}>
            Last: {lastDeployFormatted}
          </div>
        )}
      </div>

      {/* Deploy modal */}
      <AnimatePresence>
        {showModal && (
          <motion.div
            key="overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 flex items-center justify-center z-50"
            style={{ background: 'rgba(0,0,0,0.7)' }}
          >
            <motion.div
              key="modal"
              initial={{ opacity: 0, scale: 0.92 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.92 }}
              transition={{ duration: 0.15 }}
              className="relative w-full max-w-lg mx-4 rounded-lg flex flex-col"
              style={{
                background: colors.bgElevated,
                border: `1px solid ${colors.border}`,
                maxHeight: '80vh',
              }}
            >
              {/* Header */}
              <div
                className="flex items-center justify-between px-4 py-3 flex-shrink-0"
                style={{ borderBottom: `1px solid ${colors.border}` }}
              >
                <div className="flex items-center gap-2">
                  {deploying && <Loader2 size={14} className="animate-spin" style={{ color: colors.elasticBlue }} />}
                  {result?.success === true && <CheckCircle2 size={14} style={{ color: colors.profit }} />}
                  {result?.success === false && <XCircle size={14} style={{ color: colors.loss }} />}
                  <span className="text-sm font-bold" style={{ color: colors.textPrimary }}>
                    {deploying ? 'Deploying to VPS...' : result?.success ? 'Deploy Succeeded' : 'Deploy Failed'}
                  </span>
                </div>
                {!deploying && (
                  <button
                    onClick={handleClose}
                    style={{ color: colors.textMuted, background: 'none', border: 'none', cursor: 'pointer' }}
                  >
                    <X size={16} />
                  </button>
                )}
              </div>

              {/* Log output */}
              <div
                ref={logRef}
                className="flex-1 overflow-y-auto p-4 font-mono text-xs leading-relaxed"
                style={{
                  background: '#020408',
                  color: '#c8d3f5',
                  minHeight: 200,
                  maxHeight: 400,
                }}
              >
                {stdout.length === 0 && deploying && (
                  <span style={{ color: colors.textMuted }}>Waiting for output...</span>
                )}
                {stdout.map((line, i) => (
                  <div key={i}>{line || '\u00A0'}</div>
                ))}
                {result?.stderr && result.stderr.trim() && (
                  <div style={{ color: colors.loss }}>{result.stderr}</div>
                )}
              </div>

              {/* Footer */}
              {result && (
                <div
                  className="flex items-center justify-between px-4 py-3 flex-shrink-0"
                  style={{ borderTop: `1px solid ${colors.border}` }}
                >
                  <span
                    className="text-xs"
                    style={{ color: result.success ? colors.profit : colors.loss }}
                  >
                    Exit code: {result.exit_code}
                  </span>
                  <button
                    onClick={handleClose}
                    className="px-3 py-1.5 rounded text-xs"
                    style={{
                      background: colors.bgPanel,
                      color: colors.textSecondary,
                      border: `1px solid ${colors.border}`,
                      cursor: 'pointer',
                    }}
                  >
                    Close
                  </button>
                </div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
