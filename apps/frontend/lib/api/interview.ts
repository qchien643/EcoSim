import { apiFetch } from './client'
import type { AgentSummary, InterviewReply } from '../types/backend'

export async function listAgents(simId: string): Promise<AgentSummary[]> {
  const res = await apiFetch<{ agents?: AgentSummary[] }>(
    `/api/interview/agents?sim_id=${encodeURIComponent(simId)}`,
  )
  return res.agents || []
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatPayload {
  sim_id: string
  agent_id: number
  message: string
  history?: ChatMessage[]
}

export async function chatWithAgent(payload: ChatPayload): Promise<InterviewReply> {
  return apiFetch<InterviewReply>('/api/interview/chat', {
    method: 'POST',
    body: payload,
  })
}
