import { apiFetch, ApiError } from './client'
import type { AnalysisResults } from '../types/backend'

/**
 * Backend `/api/analysis/cached` shape:
 *   { cached: false, results: null }                 — never analyzed
 *   { cached: true,  timestamp, results: {...} }     — wrapped envelope
 *
 * Backend `/api/analysis/summary?sim_id=...&num_rounds=N`:
 *   Returns the full report `{quantitative, engagement, sentiment, per_round,
 *   campaign_score}` AND auto-saves it to `analysis_results.json`.
 *   This is the right endpoint to TRIGGER analysis (not `/save`, which is
 *   write-only persistence).
 */

interface CachedEnvelope {
  cached: boolean
  timestamp?: string
  results: AnalysisResults | null
}

export async function getAnalysisCached(simId: string): Promise<AnalysisResults | null> {
  try {
    const env = await apiFetch<CachedEnvelope>(
      `/api/analysis/cached?sim_id=${encodeURIComponent(simId)}`,
    )
    if (!env.cached || !env.results) return null
    // Stamp meta fields on the unwrapped results so callers can use them.
    return { ...env.results, sim_id: simId, analyzed_at: env.timestamp } as AnalysisResults
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}

export async function runAnalysis(simId: string, num_rounds = 1): Promise<AnalysisResults> {
  // GET /summary computes + auto-persists. Body-less, params via query string.
  const qs = new URLSearchParams({ sim_id: simId, num_rounds: String(num_rounds) })
  return apiFetch<AnalysisResults>(`/api/analysis/summary?${qs.toString()}`)
}
