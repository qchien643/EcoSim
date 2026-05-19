import { apiFetch, ApiError } from './client'
import type {
  AnalysisResults,
  SentimentExcerpt,
  SentimentPoint,
} from '../types/backend'

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
 *
 * NORMALIZATION:
 *   Backend trả `results.sentiment.distribution + .details` và `results.per_round[]`
 *   với `.sentiment.{positive,neutral,negative}` lồng trong từng round.
 *   Frontend page expect flat: `data.totals`, `data.top_positive`,
 *   `data.top_negative`, `data.per_round[].positive` (flat).
 *   Adapter này flatten + derive trước khi trả cho React Query.
 */

interface CachedEnvelope {
  cached: boolean
  timestamp?: string
  results: BackendAnalysis | null
}

// Hình dạng RAW trả từ Sim service (apps/simulation/api/simulation.py).
interface BackendAnalysis {
  quantitative?: Record<string, unknown>
  engagement?: Record<string, unknown>
  sentiment?: {
    distribution?: { positive?: number; neutral?: number; negative?: number }
    nss?: number
    total_comments?: number
    positive_pct?: number
    neutral_pct?: number
    negative_pct?: number
    details?: Array<{
      comment_id?: number
      user_id?: number
      post_id?: number
      content?: string
      sentiment?: 'positive' | 'negative' | 'neutral'
      score?: number
      round?: number
      agent?: string
    }>
  }
  per_round?: Array<{
    round: number
    posts?: number
    likes?: number
    comments?: number
    sentiment?: { positive?: number; neutral?: number; negative?: number }
    nss?: number
  }>
  campaign_score?: Record<string, unknown>
  sim_db?: string
}

function flattenPerRound(raw: BackendAnalysis['per_round']): SentimentPoint[] {
  if (!Array.isArray(raw)) return []
  return raw.map((r) => {
    const s = r.sentiment || {}
    const positive = s.positive ?? 0
    const neutral = s.neutral ?? 0
    const negative = s.negative ?? 0
    return {
      round: r.round,
      positive,
      neutral,
      negative,
      total: positive + neutral + negative,
    }
  })
}

function deriveExcerpts(
  details: NonNullable<BackendAnalysis['sentiment']>['details'],
  polarity: 'positive' | 'negative',
  limit = 10,
): SentimentExcerpt[] {
  if (!Array.isArray(details)) return []
  // Cao điểm theo confidence score (RoBERTa output). Filter polarity trước,
  // sau đó sort descending by score.
  const matched = details.filter((d) => d.sentiment === polarity)
  matched.sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
  return matched.slice(0, limit).map((d) => ({
    comment_id: d.comment_id,
    content: d.content ?? '',
    score: d.score,
    agent: d.agent || (d.user_id != null ? `user_${d.user_id}` : undefined),
    round: d.round,
  }))
}

function normalize(
  raw: BackendAnalysis,
  simId: string,
  timestamp?: string,
): AnalysisResults {
  const dist = raw.sentiment?.distribution || {}
  return {
    sim_id: simId,
    analyzed_at: timestamp,
    per_round: flattenPerRound(raw.per_round),
    top_positive: deriveExcerpts(raw.sentiment?.details, 'positive'),
    top_negative: deriveExcerpts(raw.sentiment?.details, 'negative'),
    totals: {
      positive: dist.positive ?? 0,
      neutral: dist.neutral ?? 0,
      negative: dist.negative ?? 0,
    },
  }
}

export async function getAnalysisCached(simId: string): Promise<AnalysisResults | null> {
  try {
    const env = await apiFetch<CachedEnvelope>(
      `/api/analysis/cached?sim_id=${encodeURIComponent(simId)}`,
    )
    if (!env.cached || !env.results) return null
    return normalize(env.results, simId, env.timestamp)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}

export async function runAnalysis(simId: string, num_rounds = 1): Promise<AnalysisResults> {
  // GET /summary computes + auto-persists. Body-less, params via query string.
  // Backend trả raw shape — normalize y hệt path cached để UI đồng nhất.
  const qs = new URLSearchParams({ sim_id: simId, num_rounds: String(num_rounds) })
  const raw = await apiFetch<BackendAnalysis>(`/api/analysis/summary?${qs.toString()}`)
  return normalize(raw, simId, new Date().toISOString())
}
