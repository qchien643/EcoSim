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
  // Backend (apps/core/app/api/report.py:get_outline) trả về:
  //   { sim_id, outline: { title, summary, sections: [{title, description, ...}] } }
  // Section trong outline.json KHÔNG có field `index` — backend dùng position
  // (1-based) để map section_NN.md. Adapter stamp `index` từ array position
  // để khớp với ReportOutlineSection type + dùng làm React key.
  type RawSection = { title?: string; description?: string; index?: number }
  const res = await apiFetch<{
    outline?: { sections?: RawSection[] } | RawSection[]
  }>(`/api/report/${simId}/outline`)
  if (!res.outline) return []
  const raw = Array.isArray(res.outline) ? res.outline : res.outline.sections || []
  return raw.map((s, i) => ({
    index: s.index ?? i + 1, // 1-based — khớp với section_01.md, section_02.md, …
    title: s.title || `Section ${i + 1}`,
    description: s.description,
  }))
}

export async function getReportSection(simId: string, idx: number): Promise<{ title?: string; content: string }> {
  return apiFetch<{ title?: string; content: string }>(
    `/api/report/${simId}/section/${idx}`,
  )
}

export async function getReportProgress(simId: string): Promise<ReportProgress> {
  return apiFetch<ReportProgress>(`/api/report/${simId}/progress`)
}
