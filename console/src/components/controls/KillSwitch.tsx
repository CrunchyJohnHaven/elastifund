import React, { useState } from 'react'
import { Skull, Loader2, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '../../lib/api'
import { colors } from '../../theme/colors'

interface KillSwitchProps {
  /** Callback after a successful kill signal */
  onSuccess?: () => void
}

export const KillSwitch: React.FC<KillSwitchProps> = ({ onSuccess }) => {
  const [showModal, setShowModal] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)

  async function handleConfirm() {
    setLoading(true)
    try {
      await api.post('/kill', { strategy: 'btc5' })
      setResult({ ok: true, message: 'Kill signal sent. BTC5 live trading disabled.' })
      onSuccess?.()
    } catch (e: unknown) {
      setResult({
        ok: false,
        message: `Kill failed: ${e instanceof Error ? e.message : String(e)}`,
      })
    } finally {
      setLoading(false)
    }
  }

  function handleClose() {
    setShowModal(false)
    setResult(null)
  }

  return (
    <>
      {/* Trigger button */}
      <button
        onClick={() => setShowModal(true)}
        className="w-full flex items-center justify-center gap-2 rounded text-sm font-medium transition-colors"
        style={{
          height: 44,
          background: '#7F1D1D',
          color: '#fff',
          border: 'none',
          cursor: 'pointer',
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.background = '#991B1B'
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.background = '#7F1D1D'
        }}
      >
        <Skull size={16} />
        <span>KILL BTC5</span>
      </button>

      {/* Confirm modal */}
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
            onClick={(e) => {
              if (e.target === e.currentTarget && !loading) handleClose()
            }}
          >
            <motion.div
              key="modal"
              initial={{ opacity: 0, scale: 0.92 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.92 }}
              transition={{ duration: 0.15 }}
              className="relative w-full max-w-sm mx-4 rounded-lg p-6"
              style={{
                background: colors.bgElevated,
                border: `1px solid ${colors.border}`,
              }}
            >
              {/* Close */}
              {!loading && (
                <button
                  onClick={handleClose}
                  className="absolute top-3 right-3"
                  style={{ color: colors.textMuted, background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  <X size={16} />
                </button>
              )}

              {result ? (
                /* Post-action state */
                <div className="text-center">
                  <div
                    className="text-2xl mb-2"
                    style={{ color: result.ok ? colors.profit : colors.loss }}
                  >
                    {result.ok ? '✓' : '✗'}
                  </div>
                  <p className="text-sm" style={{ color: colors.textPrimary }}>
                    {result.message}
                  </p>
                  <button
                    onClick={handleClose}
                    className="mt-4 px-4 py-2 rounded text-sm"
                    style={{
                      background: colors.bgPanel,
                      color: colors.textSecondary,
                      border: `1px solid ${colors.border}`,
                      cursor: 'pointer',
                    }}
                  >
                    Dismiss
                  </button>
                </div>
              ) : (
                /* Confirmation state */
                <>
                  <div
                    className="flex items-center gap-3 mb-4"
                  >
                    <Skull size={20} style={{ color: colors.loss, flexShrink: 0 }} />
                    <h2
                      className="text-base font-bold"
                      style={{ color: colors.textPrimary }}
                    >
                      Kill BTC5 Live Trading?
                    </h2>
                  </div>
                  <p className="text-sm mb-1" style={{ color: colors.textSecondary }}>
                    This will disable all live order submission for the BTC5 strategy.
                  </p>
                  <p className="text-xs mb-6" style={{ color: colors.textMuted }}>
                    Open positions will not be force-closed. No new orders will be placed until
                    the strategy is re-enabled via a fresh deploy.
                  </p>

                  <div className="flex gap-3">
                    <button
                      onClick={handleClose}
                      disabled={loading}
                      className="flex-1 rounded text-sm py-2 font-medium"
                      style={{
                        background: colors.bgPanel,
                        color: colors.textSecondary,
                        border: `1px solid ${colors.border}`,
                        cursor: 'pointer',
                      }}
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleConfirm}
                      disabled={loading}
                      className="flex-1 rounded text-sm py-2 font-medium flex items-center justify-center gap-2"
                      style={{
                        background: '#991B1B',
                        color: '#fff',
                        border: 'none',
                        cursor: loading ? 'not-allowed' : 'pointer',
                        opacity: loading ? 0.7 : 1,
                      }}
                    >
                      {loading && <Loader2 size={14} className="animate-spin" />}
                      {loading ? 'Killing...' : 'Confirm Kill'}
                    </button>
                  </div>
                </>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
