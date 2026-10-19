import { useEffect, useRef, useState } from 'react'
import { getToken } from '../api'
import type { RunEvent } from '../types'

export function useSocket(onEvent: (ev: RunEvent) => void) {
  const [connected, setConnected] = useState(false)
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent

  useEffect(() => {
    let ws: WebSocket | null = null
    let closed = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const token = getToken()
      const qs = token ? `?token=${encodeURIComponent(token)}` : ''
      ws = new WebSocket(`${proto}://${location.host}/ws${qs}`)
      ws.onopen = () => setConnected(true)
      ws.onmessage = (m) => {
        try {
          const data = JSON.parse(m.data)
          if (data.type === 'event' && data.event) handlerRef.current(data.event as RunEvent)
        } catch {
          /* ignore */
        }
      }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) retryTimer = setTimeout(connect, 2000)
      }
      ws.onerror = () => ws?.close()
    }
    connect()

    return () => {
      closed = true
      if (retryTimer) clearTimeout(retryTimer)
      ws?.close()
    }
  }, [])

  return connected
}
