/**
 * EcoSim API Client — Microservice Architecture
 * 
 * All requests go through API Gateway (port 5000) which routes:
 *   /api/campaign/* → Core Service (5001)
 *   /api/report/*   → Core Service (5001)
 *   /api/sim/*      → Simulation Service (5002)
 *   /api/graph/*    → Simulation Service (5002)
 *   /api/survey/*   → Simulation Service (5002)
 */
import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

export default api

// --- Campaign (→ Core Service) ---
export const campaignApi = {
  upload: (file) => {
    const form = new FormData()
    form.append('file', file)
    return api.post('/campaign/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  parse: (text) => api.post('/campaign/parse', { text }),
  get: (id) => api.get(`/campaign/${id}`),
  list: () => api.get('/campaign/list'),
}

// --- Graph / Knowledge Graph (→ Simulation Service) ---
export const graphApi = {
  build: (payload) => api.post('/graph/build', payload),
  ingest: (docPath, groupId, sourceDescription = '') =>
    api.post('/graph/ingest', {
      doc_path: docPath,
      group_id: groupId,
      source_description: sourceDescription,
    }),
  search: (q, groupId = '', numResults = 10) =>
    api.get('/graph/search', { params: { q, group_id: groupId, num_results: numResults } }),
  entities: (groupId = 'default', limit = 100) =>
    api.get('/graph/entities', { params: { group_id: groupId, limit } }),
  edges: (groupId = 'default', limit = 500) =>
    api.get('/graph/edges', { params: { group_id: groupId, limit } }),
  stats: (groupId = 'default') =>
    api.get('/graph/stats', { params: { group_id: groupId } }),
  listGraphs: () => api.get('/graph/list'),
  clear: (groupId = 'default') =>
    api.delete('/graph/clear', { params: { group_id: groupId } }),
}

// --- Simulation (→ Simulation Service) ---
export const simApi = {
  prepare: (campaignId, numAgents = 10, numRounds = 3, groupId = '', cognitiveToggles = {}) =>
    api.post('/sim/prepare', {
      campaign_id: campaignId,
      num_agents: numAgents,
      num_rounds: numRounds,
      group_id: groupId,
      cognitive_toggles: cognitiveToggles,
    }, { timeout: 600000 }),
  start: (simId, groupId = '') =>
    api.post('/sim/start', { sim_id: simId, group_id: groupId }),
  status: (simId) => api.get('/sim/status', { params: { sim_id: simId } }),
  list: () => api.get('/sim/list'),
  profiles: (simId) => api.get(`/sim/${simId}/profiles`),
  config: (simId) => api.get(`/sim/${simId}/config`),
  actions: (simId) => api.get(`/sim/${simId}/actions`),
  progress: (simId) => api.get(`/sim/${simId}/progress`),
  cognitive: (simId) => api.get(`/sim/${simId}/cognitive`),
}

// --- Report (→ Core Service + Simulation Service) ---
export const reportApi = {
  // Core Service endpoints
  generate: (simId) => api.post('/report/generate', { sim_id: simId }, { timeout: 600000 }),
  get: (simId) => api.get(`/report/${simId}`),
  outline: (simId) => api.get(`/report/${simId}/outline`),
  section: (simId, idx) => api.get(`/report/${simId}/section/${idx}`),
  progress: (simId) => api.get(`/report/${simId}/progress`),
  chat: (simId, message, history = []) =>
    api.post(`/report/${simId}/chat`, { message, history }),
  // Simulation Service endpoints (sentiment analysis)
  listSims: () => api.get('/analysis/simulations'),
  cachedAnalysis: (simId = '') => api.get('/analysis/cached', { params: { sim_id: simId } }),
  saveAnalysis: (simId = '', data) => api.post('/analysis/save', data, { params: { sim_id: simId } }),
  summary: (simId = '', numRounds = 1) =>
    api.get('/analysis/summary', { params: { sim_id: simId, num_rounds: numRounds }, timeout: 300000 }),
  sentiment: (simId = '') =>
    api.get('/analysis/sentiment', { params: { sim_id: simId }, timeout: 300000 }),
  perRound: (simId = '') =>
    api.get('/analysis/per-round', { params: { sim_id: simId }, timeout: 300000 }),
  score: (simId = '', numRounds = 1) =>
    api.get('/analysis/score', { params: { sim_id: simId, num_rounds: numRounds }, timeout: 300000 }),
}

// --- Survey (→ Simulation Service) ---
export const surveyApi = {
  defaultQuestions: () => api.get('/survey/default-questions'),
  create: (simId, questions, { numAgents, includeSimContext } = {}) =>
    api.post('/survey/create', {
      sim_id: simId,
      questions,
      num_agents: numAgents,
      include_sim_context: includeSimContext,
    }),
  conduct: (surveyId) => api.post(`/survey/${surveyId}/conduct`, {}, { timeout: 600000 }),
  results: (surveyId) => api.get(`/survey/${surveyId}/results`),
  export: (surveyId) => api.get(`/survey/${surveyId}/results/export`),
  latest: (simId) => api.get('/survey/latest', { params: { sim_id: simId } }),
}

// --- Interview (→ Simulation Service) ---
export const interviewApi = {
  agents: (simId) => api.get('/interview/agents', { params: { sim_id: simId } }),
  chat: (simId, agentId, message, history = []) =>
    api.post('/interview/chat', { sim_id: simId, agent_id: agentId, message, history }, { timeout: 60000 }),
  history: (simId, agentId) =>
    api.get('/interview/history', { params: { sim_id: simId, agent_id: agentId } }),
  profile: (simId, agentId) =>
    api.get('/interview/profile', { params: { sim_id: simId, agent_id: agentId } }),
}

// --- Gateway Health ---
export const healthApi = {
  check: () => api.get('/health'),
}
