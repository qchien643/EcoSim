import { apiFetch } from './client'
import type { CampaignSummary, CampaignSpec } from '../types/backend'

interface CampaignEnvelope {
  campaign_id: string
  spec: Omit<CampaignSpec, 'campaign_id'>
  chunks_count?: number
  raw_text_length?: number
}

/** Backend returns `{ campaign_id, spec: {...} }`. Flatten into CampaignSpec. */
function unwrap(env: CampaignEnvelope): CampaignSpec {
  return { campaign_id: env.campaign_id, ...env.spec } as CampaignSpec
}

export async function listCampaigns(): Promise<CampaignSummary[]> {
  const res = await apiFetch<{ campaigns?: CampaignSummary[]; count?: number }>(
    '/api/campaign/list',
  )
  return res.campaigns || []
}

export async function getCampaignSpec(campaignId: string): Promise<CampaignSpec> {
  // Backend route: GET /api/campaign/<id> → { campaign_id, spec }
  const env = await apiFetch<CampaignEnvelope>(`/api/campaign/${campaignId}`)
  return unwrap(env)
}

export async function uploadCampaign(file: File): Promise<CampaignSpec> {
  const fd = new FormData()
  fd.append('file', file)
  const env = await apiFetch<CampaignEnvelope>('/api/campaign/upload', {
    method: 'POST',
    body: fd,
    raw: true,
  })
  return unwrap(env)
}

/**
 * Cascade delete: tất cả sims thuộc campaign → master KG graph → spec/manifest/uploaded doc.
 * Backend route DELETE /api/campaign/<id> được Caddy gateway forward sang Sim service
 * (vì cần FalkorDB access). Idempotent.
 */
export async function deleteCampaign(campaignId: string): Promise<{
  campaign_id: string
  deleted: boolean
  master_dropped: boolean
  sims_dropped: string[]
  sims_failed: string[]
  campaign_dir_removed: boolean
  db_row_deleted: boolean
}> {
  return apiFetch(`/api/campaign/${encodeURIComponent(campaignId)}`, {
    method: 'DELETE',
  })
}
