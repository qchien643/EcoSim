'use client'
import { useEffect, useRef, useState } from 'react'

export type SseState = 'idle' | 'open' | 'closed' | 'error'

/**
 * Subscribe to an SSE endpoint. Null URL = disabled.
 * Messages are JSON-parsed automatically; raw string fallback on parse failure.
 */
export function useSse<T = unknown>(
  url: string | null,
  onMessage: (data: T) => void,
) {
  const [state, setState] = useState<SseState>('idle')
  const cbRef = useRef(onMessage)
  cbRef.current = onMessage

  useEffect(() => {
    if (!url) {
      setState('idle')
      return
    }
    const es = new EventSource(url)
    setState('open')

    es.onmessage = (e) => {
      try {
        cbRef.current(JSON.parse(e.data) as T)
      } catch {
        cbRef.current(e.data as unknown as T)
      }
    }
    es.onerror = () => {
      setState('error')
      es.close()
    }

    return () => {
      es.close()
      setState('closed')
    }
  }, [url])

  return state
}
