'use client'
import { useEffect, useState } from 'react'

/**
 * Returns true only after first client render — use to guard code that reads
 * from localStorage or `window` to avoid SSR / hydration mismatches.
 */
export function useHydrated() {
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  return mounted
}
