import { apiFetch } from './client'
import type {
  GraphSummary,
  GraphEntity,
  GraphEdge,
  GraphStats,
  CacheStatus,
} from '../types/backend'

// Re-export Phase 10 KG types for callers that imported from this module.
export type { CacheStatus } from '../types/backend'

export async function listGraphs(): Promise<GraphSummary[]> {
  const res = await apiFetch<{ graphs?: GraphSummary[] }>('/api/graph/list')
  return res.graphs || []
}

export async function buildGraph(campaign_id: string) {
  // CRITICAL: pass group_id = campaign_id để KG mỗi campaign nằm trong FalkorDB
  // graph riêng. Nếu bỏ trống, backend default về "default" → mọi campaign
  // ghi vào cùng 1 graph → entities lẫn lộn. Xem CLAUDE.md §11.
  return apiFetch<{ group_id: string; nodes: number; edges: number }>(
    '/api/graph/build',
    { method: 'POST', body: { campaign_id, group_id: campaign_id } },
  )
}

export async function graphStats(group_id: string): Promise<GraphStats> {
  const qs = group_id ? `?group_id=${encodeURIComponent(group_id)}` : ''
  return apiFetch<GraphStats>(`/api/graph/stats${qs}`)
}

export async function listEntities(group_id: string, limit = 200): Promise<GraphEntity[]> {
  const qs = new URLSearchParams({ group_id, limit: String(limit) })
  const res = await apiFetch<{ entities?: GraphEntity[] }>(
    `/api/graph/entities?${qs.toString()}`,
  )
  return res.entities || []
}

export async function listEdges(group_id: string, limit = 200): Promise<GraphEdge[]> {
  const qs = new URLSearchParams({ group_id, limit: String(limit) })
  const res = await apiFetch<{ edges?: GraphEdge[] }>(
    `/api/graph/edges?${qs.toString()}`,
  )
  return res.edges || []
}

// ── Phase 10: KG cache status từ meta.db ───────────────────────────
// Frontend gửi context {campaign_id} hoặc {sim_id} → backend resolve graph
// + status từ meta.db. Không còn snapshot tri-state — kg_status state machine.

export async function getCacheStatus(args: {
  campaignId?: string
  simId?: string
}): Promise<CacheStatus> {
  const params = new URLSearchParams()
  if (args.simId) params.set('sim_id', args.simId)
  if (args.campaignId) params.set('campaign_id', args.campaignId)
  return apiFetch<CacheStatus>(`/api/graph/cache-status?${params.toString()}`)
}
