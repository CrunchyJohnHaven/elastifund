import React, { useState, useEffect } from 'react'
import { Send, Loader2 } from 'lucide-react'
import { api } from '../../lib/api'
import { colors } from '../../theme/colors'

interface GuidanceEntry {
  id: string
  text: string
  created_at: string
}

export const GuidanceTerminal: React.FC = () => {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [history, setHistory] = useState<GuidanceEntry[]>([])
  const [loadingHistory, setLoadingHistory] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)

  useEffect(() => {
    loadHistory()
  }, [])

  async function loadHistory() {
    setLoadingHistory(true)
    try {
      const res = await api.get<GuidanceEntry[] | { entries: GuidanceEntry[] }>('/guidance/history')
      const entries = Array.isArray(res) ? res : res.entries ?? []
      setHistory(entries)
    } catch {
      // Non-fatal; history may not be available yet
      setHistory([])
    } finally {
      setLoadingHistory(false)
    }
  }

  async function handleSend() {
    if (!text.trim() || sending) return
    setSending(true)
    setError(null)
    setSent(false)
    try {
      await api.post('/guidance', { text: text.trim() })
      setSent(true)
      setText('')
      // Refresh history after send
      setTimeout(loadHistory, 500)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to send guidance')
    } finally {
      setSending(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      handleSend()
    }
  }

  function relTime(iso: string): string {
    try {
      const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
      if (diff < 60) return `${diff}s ago`
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
      return `${Math.floor(diff / 86400)}d ago`
    } catch {
      return iso
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Input area */}
      <div
        className="flex-shrink-0 p-4"
        style={{ borderBottom: `1px solid ${colors.border}` }}
      >
        <textarea
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setSent(false)
          }}
          onKeyDown={handleKeyDown}
          rows={5}
          placeholder="Type strategic guidance for the next autoresearch cycle..."
          className="w-full resize-none rounded p-3 text-sm font-mono leading-relaxed outline-none"
          style={{
            background: colors.bgPanel,
            border: `1px solid ${colors.border}`,
            color: colors.textPrimary,
            caretColor: colors.elasticBlue,
          }}
          onFocus={(e) => {
            (e.currentTarget as HTMLTextAreaElement).style.borderColor = 'rgba(11,100,221,0.6)'
          }}
          onBlur={(e) => {
            (e.currentTarget as HTMLTextAreaElement).style.borderColor = colors.border
          }}
        />
        <div className="flex items-center justify-between mt-2">
          <span className="text-xs" style={{ color: colors.textMuted }}>
            Ctrl+Enter to send
          </span>
          <div className="flex items-center gap-2">
            {error && (
              <span className="text-xs" style={{ color: colors.loss }}>{error}</span>
            )}
            {sent && !error && (
              <span className="text-xs" style={{ color: colors.profit }}>Sent</span>
            )}
            <button
              onClick={handleSend}
              disabled={!text.trim() || sending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium"
              style={{
                background: !text.trim() || sending ? 'rgba(11,100,221,0.3)' : colors.elasticBlue,
                color: '#fff',
                border: 'none',
                cursor: !text.trim() || sending ? 'not-allowed' : 'pointer',
              }}
            >
              {sending ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
              <span>{sending ? 'Sending...' : 'Send'}</span>
            </button>
          </div>
        </div>
      </div>

      {/* History */}
      <div className="flex-1 overflow-y-auto min-h-0 p-4">
        <div
          className="text-xs font-medium mb-3"
          style={{ color: colors.textMuted }}
        >
          Past Guidance
        </div>
        {loadingHistory ? (
          <div className="text-xs" style={{ color: colors.textMuted }}>
            Loading...
          </div>
        ) : history.length === 0 ? (
          <div className="text-xs" style={{ color: colors.textMuted }}>
            No past guidance yet.
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {history.map((entry) => (
              <div
                key={entry.id}
                className="rounded p-3"
                style={{
                  background: colors.bgPanel,
                  border: `1px solid ${colors.border}`,
                }}
              >
                <div
                  className="text-xs mb-1.5"
                  style={{ color: colors.textMuted }}
                >
                  {relTime(entry.created_at)}
                </div>
                <div
                  className="text-sm leading-relaxed whitespace-pre-wrap"
                  style={{ color: colors.textSecondary }}
                >
                  {entry.text}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
