import { apiFetch } from './client'
import type {
  ReportMeta,
  ReportProgress,
  ReportOutlineSection,
} from '../types/backend'

export async function generateReport(simId: string, payload: { auto_run_sentiment?: boolean } = {}) {
  return apiFetch<{ status: string; sim_id: string }>('/api/report/generate', {
    method: 'POST',
    body: { sim_id: simId, auto_run_sentiment: payload.auto_run_sentiment ?? true },
  })
}

export async function getReport(simId: string): Promise<ReportMeta> {
  return apiFetch<ReportMeta>(`/api/report/${simId}`)
}

export async function getReportOutline(simId: string): Promise<ReportOutlineSection[]> {
  const res = await apiFetch<{ outline?: ReportOutlineSection[] }>(
    `/api/report/${simId}/outline`,
  )
  return res.outline || []
}

export async function getReportSection(simId: string, idx: number): Promise<{ title?: string; content: string }> {
  return apiFetch<{ title?: string; content: string }>(
    `/api/report/${simId}/section/${idx}`,
  )
}

export async function getReportProgress(simId: string): Promise<ReportProgress> {
  return apiFetch<ReportProgress>(`/api/report/${simId}/progress`)
}
