import type { SystemEvent } from '../types/events'

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected'

class JJSocket {
  private ws: WebSocket | null = null
  private eventHandlers: Array<(event: SystemEvent) => void> = []
  private statusHandlers: Array<(status: ConnectionStatus) => void> = []
  private retryCount = 0
  private maxRetries = 10
  private baseDelay = 1000
  private maxDelay = 15000
  private multiplier = 1.5
  private shouldReconnect = true
  private retryTimer: ReturnType<typeof setTimeout> | null = null

  connect() {
    this.shouldReconnect = true
    this._connect()
  }

  private _connect() {
    this._notifyStatus('connecting')

    try {
      const WS_BASE = import.meta.env.VITE_WS_URL ||
        (window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.host
      const url = `${WS_BASE}/ws/live`
      this.ws = new WebSocket(url)
    } catch {
      this._scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.retryCount = 0
      this._notifyStatus('connected')
    }

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data as string) as SystemEvent
        if (data.type === 'ping') return
        this.eventHandlers.forEach(h => h(data))
      } catch {
        // ignore malformed messages
      }
    }

    this.ws.onerror = () => {
      // error will be followed by onclose
    }

    this.ws.onclose = () => {
      this.ws = null
      this._notifyStatus('disconnected')
      if (this.shouldReconnect) {
        this._scheduleReconnect()
      }
    }
  }

  private _scheduleReconnect() {
    if (this.retryCount >= this.maxRetries) return
    const delay = Math.min(
      this.baseDelay * Math.pow(this.multiplier, this.retryCount),
      this.maxDelay
    )
    this.retryCount++
    this.retryTimer = setTimeout(() => {
      this._connect()
    }, delay)
  }

  private _notifyStatus(status: ConnectionStatus) {
    this.statusHandlers.forEach(h => h(status))
  }

  onEvent(handler: (event: SystemEvent) => void) {
    this.eventHandlers.push(handler)
    return () => {
      this.eventHandlers = this.eventHandlers.filter(h => h !== handler)
    }
  }

  onStatus(handler: (status: ConnectionStatus) => void) {
    this.statusHandlers.push(handler)
    return () => {
      this.statusHandlers = this.statusHandlers.filter(h => h !== handler)
    }
  }

  send(command: object) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(command))
    }
  }

  close() {
    this.shouldReconnect = false
    if (this.retryTimer) {
      clearTimeout(this.retryTimer)
      this.retryTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this._notifyStatus('disconnected')
  }
}

export const socket = new JJSocket()
