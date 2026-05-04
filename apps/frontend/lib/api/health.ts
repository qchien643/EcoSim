import { apiFetch } from './client'
import type { HealthResponse } from '../types/backend'

export async function checkHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/api/health')
}
