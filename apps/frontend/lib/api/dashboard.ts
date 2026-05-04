/**
 * Dashboard API client — cross-cutting analytics từ meta.db.
 * Backend: apps/core/app/api/dashboard.py
 */
import { apiFetch } from './client'

export interface DashboardSummary {
  campaigns: {
    total: number
    created?: number
    building?: number
    ready?: number
    failed?: number
  }
  simulations: {
    total: number
    created?: number
    preparing?: number
    ready?: number
    running?: number
    completed?: number
    failed?: number
  }
  kg: { total_nodes: number; total_edges: number }
  sentiment_avg: {
    positive: number
    negative: number
    neutral: number
    samples: number
  }
}

export interface RecentSim {
  sid: string
  cid: string
  campaign_name: string | null
  status: string
  num_agents: number | null
  num_rounds: number | null
  current_round: number | null
  created_at: string | null
  completed_at: string | null
  last_accessed_at: string | null
}

export interface SentimentPoint {
  round: number
  positive: number
  negative: number
  neutral: number
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  return apiFetch<DashboardSummary>('/api/dashboard/summary')
}

export async function getRecentSims(opts?: {
  days?: number
  status?: string
  limit?: number
}): Promise<{ sims: RecentSim[]; count: number; days: number }> {
  const qs = new URLSearchParams()
  if (opts?.days != null) qs.set('days', String(opts.days))
  if (opts?.status) qs.set('status', opts.status)
  if (opts?.limit != null) qs.set('limit', String(opts.limit))
  const suffix = qs.toString() ? `?${qs}` : ''
  return apiFetch(`/api/dashboard/recent-sims${suffix}`)
}

export async function getMbtiDistribution(
  cid?: string,
): Promise<{ distribution: Record<string, number>; campaign_id: string | null }> {
  const qs = cid ? `?cid=${encodeURIComponent(cid)}` : ''
  return apiFetch(`/api/dashboard/mbti-distribution${qs}`)
}

export async function getSentimentTimeseries(opts?: {
  sid?: string
  cid?: string
}): Promise<{ series: SentimentPoint[]; sim_id: string | null; campaign_id: string | null }> {
  const qs = new URLSearchParams()
  if (opts?.sid) qs.set('sid', opts.sid)
  if (opts?.cid) qs.set('cid', opts.cid)
  const suffix = qs.toString() ? `?${qs}` : ''
  return apiFetch(`/api/dashboard/sentiment-timeseries${suffix}`)
}
