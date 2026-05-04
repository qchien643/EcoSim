/**
 * Minimal TypeScript types mirroring backend Pydantic.
 * Keep only fields the UI actually consumes.
 */

// ── Campaign ──
export interface CampaignSpec {
  campaign_id: string
  name: string
  campaign_type?: string
  market?: string
  description?: string
  kpis?: string[]
  stakeholders?: string[]
  risks?: string[]
  created_at?: string
}

export interface CampaignSummary {
  campaign_id: string
  name: string
  campaign_type?: string
  market?: string
  created_at?: string
}

// ── Simulation ──
export type SimStatus =
  | 'created'
  | 'preparing'
  | 'ready'
  | 'running'
  | 'completed'
  | 'failed'

export interface SimSummary {
  sim_id: string
  campaign_id: string
  group_id?: string
  status: SimStatus
  num_agents: number
  num_rounds?: number
  created_at?: string
}

export interface SimProgress {
  sim_id: string
  status: SimStatus | 'waiting'
  current_round: number
  total_rounds: number
  is_running?: boolean
  recent_actions?: SimAction[]
}

export interface SimAction {
  round?: number
  action_type?: string
  user_id?: number | string
  agent_name?: string
  content?: string
  target?: string
  timestamp?: string
}

/** Shape of an entry in `crisis_log.json` (output, written by run_simulation
 * when a crisis fires). Mirrors `CrisisEngine.triggered_log` items. NOT to
 * be confused with `CrisisEventDef` (input form payload). */
export interface CrisisEvent {
  crisis_id: string
  round: number       // round at which the crisis fired
  title: string
  type?: string       // crisis_type (price_change | scandal | …)
  severity?: number
}

// ── Graph ──
export interface GraphSummary {
  name: string
  nodes: number
  edges: number
}

export interface GraphEntity {
  name: string
  type?: string
  summary?: string
  group_id?: string
}

export interface GraphEdge {
  source: string
  target: string
  // Backend returns `relation` (xem apps/simulation/api/graph.py:262).
  relation?: string
  fact?: string
}

// Backend shape (apps/simulation/api/graph.py:319-327):
//   { group_id, exists, nodes, edges, node_labels, edge_types, all_graphs }
// Field tên giữ nguyên backend để tránh adapter layer ở client.
export interface GraphStats {
  group_id: string
  exists: boolean
  nodes?: number
  edges?: number
  node_labels?: Record<string, number>
  edge_types?: Record<string, number>
  all_graphs?: string[]
}

// ── Phase 10: KG cache status từ meta.db ──
// Frontend gửi {campaign_id} hoặc {sim_id} → backend resolve graph_name + status
// từ meta.db. Khác với GraphStats (query FalkorDB live).
export type KGStatus =
  | 'not_built'
  | 'building'
  | 'pending'
  | 'forking'
  | 'ready'
  | 'mutating'
  | 'completed'
  | 'error'

export interface CacheStatus {
  kind: 'campaign' | 'simulation'
  owner_id: string
  campaign_id?: string
  kg_graph_name: string
  kg_status: KGStatus
  node_count: number
  edge_count: number
  episode_count: number
  built_at?: string | null
  forked_at?: string | null
  last_modified_at?: string | null
  embedding_model?: string | null
  embedding_dim?: number | null
}

// ── Health ──
// Backend Core (apps/core/app/__init__.py:42) returns: { status, service }.
// `services` (plural map) was an aspirational shape that never shipped — kept
// optional so future aggregator can add it without breaking consumers.
export interface HealthResponse {
  status: 'ok' | 'degraded' | 'down'
  service?: string
  services?: Record<string, { status: 'up' | 'down'; latency_ms?: number }>
}

// ── Agent Profile (sim prepare output) ──
// Khớp `AgentProfile` ở libs/ecosim-common/src/ecosim_common/agent_schemas.py:71-112
// Lưu tại data/simulations/<sid>/profiles.json sau khi `/api/sim/prepare`.
export type Gender = 'male' | 'female'

export type MBTIType =
  | 'INTJ' | 'INTP' | 'ENTJ' | 'ENTP'
  | 'INFJ' | 'INFP' | 'ENFJ' | 'ENFP'
  | 'ISTJ' | 'ISFJ' | 'ESTJ' | 'ESFJ'
  | 'ISTP' | 'ISFP' | 'ESTP' | 'ESFP'

export interface AgentProfile {
  // Identity
  agent_id: number
  realname: string
  username: string
  age: number
  gender: Gender
  mbti: MBTIType
  country?: string

  // Narrative
  persona: string
  bio?: string
  original_persona?: string
  general_domain?: string
  specific_domain?: string
  interests?: string[]

  // Runtime behavior — chỉ giữ field có consumer thực tế trong sim runtime.
  // (xem _derive_runtime_fields ở apps/simulation/api/simulation.py +
  // verification report ở session 2026-04-26).
  // Removed `active_hours` + `posting_probability` (zero consumer).
  activity_level?: number
  posts_per_week?: number
  daily_hours?: number
  followers?: number

  // Tier B post-reflection enrichment (optional)
  persona_evolved?: string
  reflection_insights?: string[]
}

// ── Interview ──
export interface AgentSummary {
  agent_id: number
  user_id: number
  name: string
  handle?: string
  bio?: string
  persona_short?: string
  mbti?: string
  stance?: string
  avatar_letter?: string
  // any aggregated stats from /agents
  total_posts?: number
  total_comments?: number
  total_likes_given?: number
  total_engagement_received?: number
}

export interface InterviewIntent {
  classified_as: string
  confidence: number
  language: string
  context_blocks_loaded: string[]
  model_used?: string
}

export interface InterviewReply {
  agent_name: string
  response: string
  intent: InterviewIntent
  context_stats: {
    posts: number
    comments: number
    likes: number
    graph_context_len?: number
    blocks_used: number
  }
}

// ── Sentiment / Analysis ──
export interface SentimentPoint {
  round: number
  positive: number
  neutral: number
  negative: number
  total?: number
}

export interface SentimentExcerpt {
  comment_id?: string | number
  content: string
  score?: number
  agent?: string
  round?: number
}

export interface AnalysisResults {
  sim_id: string
  per_round?: SentimentPoint[]
  top_positive?: SentimentExcerpt[]
  top_negative?: SentimentExcerpt[]
  totals?: { positive: number; neutral: number; negative: number }
  analyzed_at?: string
}

// ── Report ──
export interface ReportOutlineSection {
  index: number
  title: string
  description?: string
}

export interface ReportProgress {
  status: 'pending' | 'planning' | 'generating' | 'completed' | 'failed'
  current_section?: number
  total_sections?: number
  message?: string
}

// Backend shape (apps/core/app/api/report.py:117-122):
//   { sim_id, report_md, report_length, meta: {...} }
// Trong đó `meta` được load từ data/simulations/<sid>/report/meta.json
// (xem report_agent.py:2447-2459 cho schema chi tiết).
export interface ReportMetaInner {
  report_id?: string
  sim_id?: string
  campaign_id?: string
  status?: 'completed' | 'failed' | 'generating' | string
  sections_count?: number
  total_tool_calls?: number
  total_evidence?: number
  evidence_refs_per_section?: Record<string, number>
  created_at?: number
  completed_at?: number
  duration_s?: number
  // outline được serve riêng qua /api/report/<sid>/outline — không nằm trong meta.json
  [key: string]: unknown
}

export interface ReportMeta {
  sim_id: string
  report_md: string
  report_length: number
  meta?: ReportMetaInner
}

// ── Survey ──
export type QuestionType = 'scale_1_10' | 'yes_no' | 'open_ended' | 'multiple_choice'

export interface SurveyQuestion {
  id?: string
  text: string
  question_type: QuestionType
  options?: string[]
  category?: string
  rationale?: string
  report_section?: string
}

export interface SurveyResponse {
  agent_name: string
  agent_role?: string
  question: string
  question_type: QuestionType
  category?: string
  report_section?: string
  intent?: string
  answer: string
}

export interface SurveyAggregate {
  question: string
  question_type: QuestionType
  distribution?: Record<string, number>
  average?: number
  min?: number
  max?: number
  key_themes?: string[]
}

export interface SurveyResults {
  survey_id: string
  sim_id: string
  status: 'created' | 'completed'
  total_respondents?: number
  questions?: SurveyQuestion[]
  responses?: SurveyResponse[]
  aggregated?: SurveyAggregate[]
  by_section?: Record<string, SurveyAggregate[]>
}
