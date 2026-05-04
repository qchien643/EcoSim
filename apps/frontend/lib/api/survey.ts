import { apiFetch } from './client'
import type { SurveyQuestion, SurveyResults } from '../types/backend'

export async function getDefaultQuestions(): Promise<SurveyQuestion[]> {
  const res = await apiFetch<{ questions?: SurveyQuestion[] }>(
    '/api/survey/default-questions',
  )
  return res.questions || []
}

export async function generateQuestions(payload: {
  sim_id: string
  count?: number
  use_sentiment?: boolean
  use_crisis?: boolean
}): Promise<SurveyQuestion[]> {
  const res = await apiFetch<{ questions?: SurveyQuestion[] }>(
    '/api/survey/generate-questions',
    { method: 'POST', body: { count: 10, use_sentiment: true, use_crisis: true, ...payload } },
  )
  return res.questions || []
}

export async function createSurvey(payload: {
  sim_id: string
  questions?: SurveyQuestion[]
}): Promise<{ survey_id: string }> {
  return apiFetch<{ survey_id: string }>('/api/survey/create', {
    method: 'POST',
    body: payload,
  })
}

export async function conductSurvey(survey_id: string) {
  return apiFetch<{ status: string; total_respondents: number }>(
    `/api/survey/${survey_id}/conduct`,
    { method: 'POST' },
  )
}

export async function getSurveyResults(survey_id: string): Promise<SurveyResults> {
  return apiFetch<SurveyResults>(`/api/survey/${survey_id}/results`)
}

export async function getLatestSurvey(sim_id: string): Promise<{ survey_id?: string }> {
  return apiFetch<{ survey_id?: string }>(
    `/api/survey/latest?sim_id=${encodeURIComponent(sim_id)}`,
  )
}
