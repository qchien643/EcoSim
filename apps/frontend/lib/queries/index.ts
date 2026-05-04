import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listCampaigns,
  getCampaignSpec,
  uploadCampaign,
  deleteCampaign,
} from '../api/campaign'
import {
  listSims,
  getSim,
  prepareSim,
  startSim,
  getSimProgress,
  getSimActions,
  getSimFeed,
  getSimProfiles,
  getSimCognitive,
  getCrisisLog,
  deleteSim,
  type PrepareSimPayload,
} from '../api/sim'
import {
  listGraphs,
  buildGraph,
  graphStats,
  listEntities,
  listEdges,
  getCacheStatus,
} from '../api/graph'
import { getBuildProgress } from '../api/graph-progress'
import { checkHealth } from '../api/health'
import { listAgents, chatWithAgent } from '../api/interview'
import { getAnalysisCached, runAnalysis } from '../api/analysis'
import {
  generateReport,
  getReport,
  getReportOutline,
  getReportSection,
  getReportProgress,
} from '../api/report'
import {
  getDefaultQuestions,
  generateQuestions,
  createSurvey,
  conductSurvey,
  getSurveyResults,
  getLatestSurvey,
} from '../api/survey'
import { useUiStore } from '@/stores/ui-store'

// ──────────────────────────────────────────
// Query key factory
// ──────────────────────────────────────────
export const qk = {
  campaigns: ['campaigns'] as const,
  campaign: (id: string) => ['campaign', id] as const,
  sims: ['sims'] as const,
  sim: (id: string) => ['sim', id] as const,
  simProgress: (id: string) => ['sim', id, 'progress'] as const,
  simActions: (id: string) => ['sim', id, 'actions'] as const,
  simProfiles: (id: string) => ['sim', id, 'profiles'] as const,
  simCognitive: (id: string) => ['sim', id, 'cognitive'] as const,
  crisisLog: (id: string) => ['sim', id, 'crisis'] as const,
  graphs: ['graphs'] as const,
  graphStats: (g: string) => ['graph', g, 'stats'] as const,
  graphEntities: (g: string) => ['graph', g, 'entities'] as const,
  graphEdges: (g: string) => ['graph', g, 'edges'] as const,
  health: ['health'] as const,
  agents: (simId: string) => ['agents', simId] as const,
  analysis: (simId: string) => ['analysis', simId] as const,
  report: (simId: string) => ['report', simId] as const,
  reportProgress: (simId: string) => ['report', simId, 'progress'] as const,
  reportSection: (simId: string, idx: number) =>
    ['report', simId, 'section', idx] as const,
  surveyLatest: (simId: string) => ['survey', simId, 'latest'] as const,
  surveyResults: (id: string) => ['survey', id, 'results'] as const,
  defaultQuestions: ['survey', 'default-questions'] as const,
}

// ──────────────────────────────────────────
// Health
// ──────────────────────────────────────────
export const useHealth = () =>
  useQuery({
    queryKey: qk.health,
    queryFn: checkHealth,
    refetchInterval: 30_000,
    retry: 0,
  })

// ──────────────────────────────────────────
// Campaigns
// ──────────────────────────────────────────
export const useCampaigns = () =>
  useQuery({ queryKey: qk.campaigns, queryFn: listCampaigns })

export const useCampaignSpec = (id: string | null | undefined) =>
  useQuery({
    queryKey: id ? qk.campaign(id) : ['campaign', 'nil'],
    queryFn: () => getCampaignSpec(id as string),
    enabled: !!id,
  })

export const useUploadCampaign = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: uploadCampaign,
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.campaigns }),
  })
}

export const useDeleteCampaign = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteCampaign,
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.campaigns }),
  })
}

// ──────────────────────────────────────────
// Sims
// ──────────────────────────────────────────
export const useSims = (campaignId?: string) =>
  useQuery({
    // Cache key bao gồm campaignId để filter campaign A không invalidate cache campaign B
    queryKey: campaignId ? ['sims', { campaignId }] : qk.sims,
    queryFn: () => listSims(campaignId),
    refetchInterval: 10_000,
  })

export const useSim = (id: string | null | undefined) =>
  useQuery({
    queryKey: id ? qk.sim(id) : ['sim', 'nil'],
    queryFn: () => getSim(id as string),
    enabled: !!id,
  })

export const useSimProgress = (id: string | null | undefined, enabled = true) =>
  useQuery({
    queryKey: id ? qk.simProgress(id) : ['sim', 'nil', 'progress'],
    queryFn: () => getSimProgress(id as string),
    enabled: !!id && enabled,
    refetchInterval: 5_000,
  })

export const useSimActions = (id: string | null | undefined, limit = 50) =>
  useQuery({
    queryKey: id ? qk.simActions(id) : ['sim', 'nil', 'actions'],
    queryFn: () => getSimActions(id as string, limit),
    enabled: !!id,
    refetchInterval: 8_000,
  })

export const useSimFeed = (id: string | null | undefined, opts?: { polling?: boolean }) =>
  useQuery({
    queryKey: id ? (['sim', id, 'feed'] as const) : (['sim', 'nil', 'feed'] as const),
    queryFn: () => getSimFeed(id as string, 100),
    enabled: !!id,
    refetchInterval: opts?.polling ? 5_000 : 15_000,
  })

export const useCrisisLog = (
  id: string | null | undefined,
  opts?: { polling?: boolean },
) =>
  useQuery({
    queryKey: id ? qk.crisisLog(id) : ['sim', 'nil', 'crisis'],
    queryFn: () => getCrisisLog(id as string),
    enabled: !!id,
    // While the sim is running, crises can fire at any round → re-poll
    // so the UI badge stays in sync with `crisis_triggered_count` in
    // meta.db (updated by run_simulation.py at the end of each round).
    // After the sim completes the caller should pass `polling: false`
    // so we drop to a slow background refresh.
    refetchInterval: opts?.polling ? 5_000 : 30_000,
  })

// Profiles được sinh ở /api/sim/prepare và ghi `profiles.json`. Một khi
// prepare xong → profiles immutable trong sim runtime (chỉ có Tier B
// reflection append `persona_evolved` post-round). Không cần polling.
export const useSimProfiles = (id: string | null | undefined) =>
  useQuery({
    queryKey: id ? qk.simProfiles(id) : ['sim', 'nil', 'profiles'],
    queryFn: () => getSimProfiles(id as string),
    enabled: !!id,
    staleTime: 60_000,
  })

// Cognitive tracking — 1 sample agent timeline qua N+1 rounds.
// Backend: GET /api/sim/{sim_id}/cognitive (parse analysis/tracking.jsonl).
// Append-only writes mỗi round → polling 5s khi sim đang RUNNING.
export const useSimCognitive = (
  id: string | null | undefined,
  opts?: { polling?: boolean },
) =>
  useQuery({
    queryKey: id ? qk.simCognitive(id) : ['sim', 'nil', 'cognitive'],
    queryFn: () => getSimCognitive(id as string),
    enabled: !!id,
    staleTime: opts?.polling ? 0 : 30_000,
    refetchInterval: opts?.polling ? 5_000 : false,
  })

export const usePrepareSim = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: PrepareSimPayload) => prepareSim(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.sims }),
  })
}

export const useStartSim = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: startSim,
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.sims }),
  })
}

export const useDeleteSim = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteSim,
    onSuccess: () => {
      // Invalidate cả unfiltered list lẫn các campaign-filtered lists.
      qc.invalidateQueries({ queryKey: qk.sims })
      qc.invalidateQueries({ queryKey: ['sims'] })
    },
  })
}

// ──────────────────────────────────────────
// Graphs
// ──────────────────────────────────────────
export const useGraphs = (opts?: { polling?: boolean }) =>
  useQuery({
    queryKey: qk.graphs,
    queryFn: listGraphs,
    // Khi build đang chạy (polling=true), refetch mỗi 5s để pickup graph
    // mới được tạo bởi backend mà không cần user F5. Mặc định không poll
    // để tránh tải vô ích.
    refetchInterval: opts?.polling ? 5_000 : false,
  })

export const useGraphStats = (group: string | null | undefined) =>
  useQuery({
    queryKey: group ? qk.graphStats(group) : ['graph', 'nil', 'stats'],
    queryFn: () => graphStats(group as string),
    enabled: !!group,
  })

export const useGraphEntities = (
  group: string | null | undefined,
  limit = 200,
  opts?: { polling?: boolean },
) =>
  useQuery({
    queryKey: group ? qk.graphEntities(group) : ['graph', 'nil', 'entities'],
    queryFn: () => listEntities(group as string, limit),
    enabled: !!group,
    // Poll 2s khi build đang chạy → real-time growing graph viz.
    refetchInterval: opts?.polling ? 2_000 : false,
  })

export const useGraphEdges = (
  group: string | null | undefined,
  limit = 200,
  opts?: { polling?: boolean },
) =>
  useQuery({
    queryKey: group ? qk.graphEdges(group) : ['graph', 'nil', 'edges'],
    queryFn: () => listEdges(group as string, limit),
    enabled: !!group,
    refetchInterval: opts?.polling ? 2_000 : false,
  })

/**
 * Poll build progress (granular stage messages) khi đang build. Default poll
 * 1.5s khi isBuilding=true. Stop polling khi status='done' or 'failed'.
 */
export const useBuildProgress = (
  campaignId: string | null | undefined,
  isBuilding: boolean,
) =>
  useQuery({
    queryKey: campaignId
      ? ['graph', campaignId, 'build-progress']
      : ['graph', 'nil', 'build-progress'],
    queryFn: () => getBuildProgress(campaignId as string),
    enabled: !!campaignId && isBuilding,
    refetchInterval: 1_500,
    retry: 0,
  })

export const useBuildGraph = () => {
  const qc = useQueryClient()
  // Hook vào ui-store để track in-flight builds xuyên qua navigation.
  // Mutation state của react-query bị reset khi component unmount → navigate
  // qua tab khác sẽ mất "isPending". Dùng global store giải quyết.
  const startBuilding = useUiStore((s) => s.startBuilding)
  const stopBuilding = useUiStore((s) => s.stopBuilding)
  return useMutation({
    mutationFn: buildGraph,
    onMutate: (campaignId: string) => {
      startBuilding(campaignId)
    },
    onSettled: (_data, _err, campaignId: string) => {
      stopBuilding(campaignId)
      qc.invalidateQueries({ queryKey: qk.graphs })
      // Phase 10: invalidate cache-status để frontend pickup kg_status='ready'
      qc.invalidateQueries({ queryKey: ['graph', campaignId, 'cache-status'] })
    },
  })
}

// ── Phase 10: KG cache status từ meta.db ──────────────────────────
// useCacheStatus({campaignId|simId}, polling?) — poll khi build/clone
// đang chạy để detect kg_status flip ('building' → 'ready' / 'forking' → 'ready').
export const useCacheStatus = (
  args: { campaignId?: string | null; simId?: string | null },
  opts?: { polling?: boolean },
) => {
  const ownerId = args.simId || args.campaignId || null
  return useQuery({
    queryKey: ownerId
      ? (['graph', ownerId, 'cache-status'] as const)
      : (['graph', 'nil', 'cache-status'] as const),
    queryFn: () =>
      getCacheStatus({
        campaignId: args.campaignId || undefined,
        simId: args.simId || undefined,
      }),
    enabled: !!ownerId,
    refetchInterval: opts?.polling ? 2_000 : false,
    retry: 0,
  })
}

// Phase 10: useRestoreGraph removed — không còn snapshot.json để restore.
// Mất FalkorDB volume → user phải POST /api/graph/build từ source documents.
// Stub để code chưa migrate không break import (no-op mutation).
export const useRestoreGraph = () => {
  const qc = useQueryClient()
  const startBuilding = useUiStore((s) => s.startBuilding)
  const stopBuilding = useUiStore((s) => s.stopBuilding)
  return useMutation({
    mutationFn: async (_campaignId: string) => {
      throw new Error(
        'Restore endpoint removed Phase 10. Run /api/graph/build từ source documents.',
      )
    },
    onMutate: (campaignId: string) => {
      startBuilding(campaignId)
    },
    onSettled: (_data, _err, campaignId: string) => {
      stopBuilding(campaignId)
      qc.invalidateQueries({ queryKey: qk.graphs })
      qc.invalidateQueries({
        queryKey: ['graph', campaignId, 'cache-status'],
      })
    },
  })
}

// ──────────────────────────────────────────
// Interview
// ──────────────────────────────────────────
export const useAgents = (simId: string | null | undefined) =>
  useQuery({
    queryKey: simId ? qk.agents(simId) : ['agents', 'nil'],
    queryFn: () => listAgents(simId as string),
    enabled: !!simId,
  })

export const useChatWithAgent = () =>
  useMutation({ mutationFn: chatWithAgent })

// ──────────────────────────────────────────
// Analysis
// ──────────────────────────────────────────
export const useAnalysis = (simId: string | null | undefined) =>
  useQuery({
    queryKey: simId ? qk.analysis(simId) : ['analysis', 'nil'],
    queryFn: () => getAnalysisCached(simId as string),
    enabled: !!simId,
  })

export const useRunAnalysis = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ simId, num_rounds }: { simId: string; num_rounds?: number }) =>
      runAnalysis(simId, num_rounds),
    onSuccess: (_data, vars) =>
      qc.invalidateQueries({ queryKey: qk.analysis(vars.simId) }),
  })
}

// ──────────────────────────────────────────
// Report
// ──────────────────────────────────────────
export const useReport = (simId: string | null | undefined) =>
  useQuery({
    queryKey: simId ? qk.report(simId) : ['report', 'nil'],
    queryFn: () => getReport(simId as string),
    enabled: !!simId,
    retry: 0,
  })

export const useReportProgress = (simId: string | null | undefined, enabled = true) =>
  useQuery({
    queryKey: simId ? qk.reportProgress(simId) : ['report', 'nil', 'progress'],
    queryFn: () => getReportProgress(simId as string),
    enabled: !!simId && enabled,
    refetchInterval: 4_000,
    retry: 0,
  })

export const useReportSection = (
  simId: string | null | undefined,
  idx: number | null,
) =>
  useQuery({
    queryKey:
      simId && idx != null
        ? qk.reportSection(simId, idx)
        : ['report', 'nil', 'section'],
    queryFn: () => getReportSection(simId as string, idx as number),
    enabled: !!simId && idx != null,
  })

export const useGenerateReport = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ simId, autoSentiment }: { simId: string; autoSentiment?: boolean }) =>
      generateReport(simId, { auto_run_sentiment: autoSentiment }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: qk.report(vars.simId) })
      qc.invalidateQueries({ queryKey: qk.reportProgress(vars.simId) })
    },
  })
}

export const useReportOutline = (simId: string | null | undefined) =>
  useQuery({
    queryKey: simId ? ['report', simId, 'outline'] : ['report', 'nil', 'outline'],
    queryFn: () => getReportOutline(simId as string),
    enabled: !!simId,
    retry: 0,
  })

// ──────────────────────────────────────────
// Survey
// ──────────────────────────────────────────
export const useDefaultQuestions = () =>
  useQuery({ queryKey: qk.defaultQuestions, queryFn: getDefaultQuestions })

export const useGenerateQuestions = () =>
  useMutation({ mutationFn: generateQuestions })

export const useCreateSurvey = () => useMutation({ mutationFn: createSurvey })

export const useConductSurvey = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: conductSurvey,
    onSuccess: (_data, surveyId) =>
      qc.invalidateQueries({ queryKey: qk.surveyResults(surveyId) }),
  })
}

export const useSurveyResults = (id: string | null | undefined) =>
  useQuery({
    queryKey: id ? qk.surveyResults(id) : ['survey', 'nil', 'results'],
    queryFn: () => getSurveyResults(id as string),
    enabled: !!id,
  })

export const useLatestSurvey = (simId: string | null | undefined) =>
  useQuery({
    queryKey: simId ? qk.surveyLatest(simId) : ['survey', 'nil', 'latest'],
    queryFn: () => getLatestSurvey(simId as string),
    enabled: !!simId,
    retry: 0,
  })
