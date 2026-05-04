import { apiFetch } from './client'

export interface BuildProgress {
  stage: string
  percent: number
  message: string
  status: 'running' | 'done' | 'failed' | 'idle'
  started_at?: string
  updated_at?: string
  error?: string | null
  campaign_id: string
}

/**
 * Poll endpoint trả granular build progress (stage + percent + message).
 * Backend ghi vào `<UPLOAD_DIR>/<campaign_id>/kg/build_progress.json` mỗi
 * checkpoint trong pipeline (Stage 1 parse, Stage 2 LLM analyze, Stage 3
 * direct write, indexes). Idle = chưa bao giờ build hoặc file không có.
 */
export async function getBuildProgress(campaignId: string): Promise<BuildProgress> {
  return apiFetch<BuildProgress>(
    `/api/graph/build-progress?campaign_id=${encodeURIComponent(campaignId)}`,
  )
}
