import { apiFetch } from './client'
import type {
  SimSummary,
  SimProgress,
  SimAction,
  CrisisEvent,
  AgentProfile,
} from '../types/backend'

export async function listSims(campaignId?: string): Promise<SimSummary[]> {
  // Server-side filter theo campaign — sau khi backend support
  // GET /api/sim/list?campaign_id=X (master+fork architecture).
  const qs = campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : ''
  const res = await apiFetch<{ simulations?: SimSummary[] }>(`/api/sim/list${qs}`)
  return res.simulations || []
}

export async function getSim(simId: string): Promise<SimSummary> {
  return apiFetch<SimSummary>(`/api/sim/status?sim_id=${encodeURIComponent(simId)}`)
}

// Khớp `CrisisEventDef` ở apps/simulation/api/simulation.py
export interface CrisisEventDef {
  trigger_round: number
  crisis_type:
    | 'price_change'
    | 'scandal'
    | 'news'
    | 'competitor'
    | 'regulation'
    | 'positive_event'
    | 'custom'
  title: string
  description?: string
  severity?: number // 0.0 (mild) → 1.0 (catastrophic)
  affected_domains?: string[]
  sentiment_shift?: 'negative' | 'positive' | 'mixed'
  // Số keyphrases LLM trích xuất từ title+description tại trigger time.
  // 1-20, default 5. Mỗi keyword được tiêm vào interest vector của mọi agent
  // với weight = severity.
  n_keywords?: number
}

// Khớp `PrepareRequest` ở apps/simulation/api/simulation.py:90-98
export interface PrepareSimPayload {
  campaign_id: string
  num_agents: number
  num_rounds?: number
  group_id?: string
  cognitive_toggles?: Record<string, boolean>
  tracked_agent_id?: number
  crisis_events?: CrisisEventDef[]
  seed?: number
  // Per-sim override cho ZEP_SIM_RUNTIME env. undefined = inherit env default.
  // true → bật Zep extract bridge edges (MENTIONS_BRAND/DISCUSSES) tới master
  // entities. Yêu cầu ZEP_API_KEY set, else backend trả 400.
  enable_zep_runtime?: boolean
}

export async function prepareSim(payload: PrepareSimPayload) {
  // Sau master+fork architecture, backend tự derive `kg_graph_name = "sim_<id>"`
  // và fork master KG (= graph campaign_id) sang sim graph trong /prepare.
  // Frontend không cần biết tên graph — chỉ pass campaign_id + config.
  return apiFetch<{ sim_id: string } & Record<string, unknown>>(
    '/api/sim/prepare',
    { method: 'POST', body: payload },
  )
}

export async function startSim(sim_id: string) {
  return apiFetch<{ status: string }>('/api/sim/start', {
    method: 'POST',
    body: { sim_id },
  })
}

export async function getSimProgress(simId: string): Promise<SimProgress> {
  return apiFetch<SimProgress>(`/api/sim/${simId}/progress`)
}

// ── Phase 11: Sim feed (social media view) ──────────────────────────
export interface FeedAuthor {
  agent_id: number
  name: string
  mbti?: string
}

export interface FeedComment {
  comment_id: number
  content: string
  round: number
  ts?: string
  author: FeedAuthor
}

export interface FeedLike {
  agent_id: number
  name: string
}

export interface FeedPost {
  post_id: number
  content: string
  round: number
  ts?: string
  author: FeedAuthor
  likes_count: number
  likes: FeedLike[]
  comments_count: number
  comments: FeedComment[]
}

export async function getSimFeed(simId: string, limit = 100): Promise<FeedPost[]> {
  const res = await apiFetch<{ posts?: FeedPost[] }>(
    `/api/sim/${encodeURIComponent(simId)}/feed?limit=${limit}`,
  )
  return res.posts || []
}


export async function getSimActions(simId: string, limit = 50): Promise<SimAction[]> {
  const res = await apiFetch<{ actions?: SimAction[] }>(
    `/api/sim/${simId}/actions?limit=${limit}`,
  )
  return res.actions || []
}

/** Fetch agent profiles sinh ra ở `/api/sim/prepare`. 404 nếu prepare chưa xong. */
export async function getSimProfiles(simId: string): Promise<AgentProfile[]> {
  const res = await apiFetch<{ profiles?: AgentProfile[] }>(
    `/api/sim/${encodeURIComponent(simId)}/profiles`,
  )
  return res.profiles || []
}

/** Full crisis record — scheduled definition + trigger status, returned by
 * `GET /api/sim/{id}/crisis-log` in the `crises` field. UI should prefer
 * this over the slim `crisis_log` array (kept for backward compat). */
export interface CrisisRecord {
  // Scheduled definition (mirrors CrisisEventDef payload)
  trigger_round: number
  title: string
  description: string
  crisis_type: CrisisEventDef['crisis_type']
  severity: number
  sentiment_shift: 'negative' | 'positive' | 'mixed'
  affected_domains: string[]
  interest_keywords: string[]
  persist_rounds: number
  intensity_decay: number
  // Trigger status
  triggered: boolean
  triggered_round: number | null
  crisis_id: string | null
}

/** Output of `GET /api/sim/{id}/crisis-log`. The backend resolves
 * `crisis_log_path` from meta.db (not by recomputing the convention) so
 * `crisis_count` / `crisis_triggered_count` are guaranteed to match the file
 * the log was read from. */
export interface CrisisLogResponse {
  /** Full per-crisis records — preferred by UI. */
  crises: CrisisRecord[]
  /** Slim triggered-log entries (back-compat). */
  crisis_log: CrisisEvent[]
  /** Scheduled crises in `config.json` at /prepare time. */
  crisis_count: number
  /** Crises that have actually fired in the sim so far (updated each round). */
  crisis_triggered_count: number
}

export async function getCrisisLog(simId: string): Promise<CrisisLogResponse> {
  const res = await apiFetch<Partial<CrisisLogResponse>>(
    `/api/sim/${simId}/crisis-log`,
  )
  return {
    crises: res.crises || [],
    crisis_log: res.crisis_log || [],
    crisis_count: res.crisis_count ?? 0,
    crisis_triggered_count: res.crisis_triggered_count ?? 0,
  }
}

/** URL (not a fetch) for EventSource — pass to `useSse`. */
export function simStreamUrl(simId: string): string {
  return `/api/sim/${simId}/stream`
}

// ── Cognitive tracking — GET /api/sim/{sim_id}/cognitive ──────────────────
// Mirror schema từ apps/simulation/agent_tracking_writer.py:parse_tracking_jsonl
// Track 1 sample agent qua N+1 rounds (Round 0 = baseline, 1..N = mỗi round)

export interface CognitiveTraitRender {
  value: number // 0.0 - 1.0
  label: string // Vietnamese label (vd "Độ bảo thủ")
  description: string
}

export interface InterestItem {
  keyword: string
  weight: number
  source?: string // 'initial' | 'engaged_post' | 'drift' | ...
  engagement_count?: number
  trending?: boolean
  is_new?: boolean
}

export interface SearchQuery {
  weight: number
  query: string
}

export interface RoundAction {
  type: string
  text: string
}

export interface CognitiveRound {
  round: number
  base_persona: string
  evolved_persona: string
  insights_count: number
  reflections: string
  memory: string
  cognitive_traits: Record<string, CognitiveTraitRender>
  interest_vector: InterestItem[]
  search_queries: SearchQuery[]
  drift_keywords: string[]
  initial_interests: string[]
  interest_query: string
  search_query: string
  mbti_modifiers: string
  graph_context: string
  actions: RoundAction[]
}

export interface CognitiveAgentTracking {
  agent: { name: string; id: number; mbti: string }
  rounds: CognitiveRound[]
  total_rounds: number
}

export interface CognitiveTracking {
  // Phase 15.tracking: multi-agent tracking. `agents` là list (default
  // 2 agents đầu). Top-level `agent`/`rounds`/`total_rounds` = agents[0]
  // cho backward compat.
  agents: CognitiveAgentTracking[]
  agent: { name: string; id: number; mbti: string }
  rounds: CognitiveRound[]
  total_rounds: number
}

export async function getSimCognitive(simId: string): Promise<CognitiveTracking> {
  return apiFetch<CognitiveTracking>(`/api/sim/${encodeURIComponent(simId)}/cognitive`)
}

/** Cascade delete 1 sim: drop FalkorDB sim graph + sim_dir + manifest entry. */
export async function deleteSim(simId: string) {
  return apiFetch<{
    sim_id: string
    deleted: boolean
    graph_dropped: boolean
    dir_removed: boolean
    manifest_removed: boolean
    campaign_id: string
  }>(`/api/sim/${encodeURIComponent(simId)}`, { method: 'DELETE' })
}
