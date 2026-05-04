'use client'

import { use, useMemo, useState } from 'react'
import {
  Network,
  Sparkles,
  Hash,
  ArrowRight,
  Search,
  LayoutGrid,
  List as ListIcon,
} from 'lucide-react'
import {
  useGraphs,
  useGraphStats,
  useGraphEntities,
  useGraphEdges,
  useBuildGraph,
  useBuildProgress,
  useCacheStatus,
} from '@/lib/queries'
import { useUiStore } from '@/stores/ui-store'
import { useAppStore } from '@/stores/app-store'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/data/skeleton'
import { ErrorState } from '@/components/data/error-state'
import { EmptyState } from '@/components/data/empty-state'
import dynamic from 'next/dynamic'
import { cn, truncate } from '@/lib/utils'
import type { GraphEntity } from '@/lib/types/backend'

// Sigma dùng WebGL → client-only. Lazy import giảm initial bundle (Sigma +
// Graphology + FA2 worker tổng ~150KB gzipped, chỉ load khi user vào graph tab).
const KGSigmaCanvas = dynamic(
  () => import('@/components/graph/kg-sigma-canvas').then((m) => m.KGSigmaCanvas),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center text-xs text-fg-faint">
        Đang tải graph engine…
      </div>
    ),
  },
)

export default function GraphPage({
  params,
}: {
  params: Promise<{ campaignId: string }>
}) {
  const { campaignId } = use(params)
  const ui = useUiStore()
  const app = useAppStore()

  // Track build in-flight cross-navigation (react-query mutation state local
  // per-component, mất khi unmount). ui-store giữ Set<campaignId>.
  const isBuilding = useUiStore((s) => s.isBuilding(campaignId))

  // Auto-poll graphs list khi đang build (5s) → pickup graph mới ngay khi
  // backend hoàn tất, không cần user F5.
  const graphsQ = useGraphs({ polling: isBuilding })
  // Mỗi campaign 1 graph riêng tên = campaign_id (xem buildGraph passes
  // group_id = campaign_id). Match exact để tránh chọn nhầm graph có tên
  // chứa substring (vd "abc" match "abc12345").
  const graph = (graphsQ.data || []).find((g) => g.name === campaignId)
  const groupId = graph?.name || ''

  // Khi build đang chạy, graph chưa có trong FalkorDB list → groupId rỗng.
  // Fallback dùng campaignId (master+fork architecture: graph name = campaign_id)
  // để có thể poll endpoints ngay từ đầu — backend trả empty list cho graph
  // chưa tồn tại, nên không lỗi. Real-time growing graph khi node xuất hiện.
  const liveGroupId = groupId || (isBuilding ? campaignId : '')
  const statsQ = useGraphStats(liveGroupId || null)
  const entitiesQ = useGraphEntities(liveGroupId || null, 200, {
    polling: isBuilding,
  })
  const edgesQ = useGraphEdges(liveGroupId || null, 200, {
    polling: isBuilding,
  })
  const buildM = useBuildGraph()
  // Granular progress poll khi build đang chạy. Backend ghi build_progress.json
  // mỗi stage; hook này poll 1.5s và stop khi done/failed.
  const progressQ = useBuildProgress(campaignId, isBuilding)
  const progress = progressQ.data

  // Phase 10: kg_status state machine từ meta.db
  //   not_built → user phải Build (~30-60s, LLM extract từ source docs)
  //   building  → progress bar (poll qua build_progress)
  //   ready     → render bình thường
  //   error     → fail state, hiển thị retry button
  const cacheStatusQ = useCacheStatus(
    { campaignId },
    { polling: isBuilding },
  )
  const cs = cacheStatusQ.data
  const graphState: 'fresh' | 'building' | 'active' | 'error' =
    cs?.kg_status === 'ready' || !!graph
      ? 'active'
      : cs?.kg_status === 'building'
      ? 'building'
      : cs?.kg_status === 'error'
      ? 'error'
      : 'fresh'

  const [filter, setFilter] = useState('')
  const [activeType, setActiveType] = useState<string | null>(null)
  const [activeEntity, setActiveEntity] = useState<GraphEntity | null>(null)
  // Toggle giữa graph viz (default) và list view ở center column.
  // Default = 'graph' để user thấy ngay đồ thị được build.
  const [viewMode, setViewMode] = useState<'graph' | 'list'>('graph')
  // Focus mode: double-click node → show node + 1-hop neighbors only.
  // Double-click cùng node hoặc click "Reset" → null.
  const [focusedName, setFocusedName] = useState<string | null>(null)

  const entities = entitiesQ.data || []
  const edges = edgesQ.data || []

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const e of entities) {
      const t = e.type || 'Unknown'
      counts[t] = (counts[t] || 0) + 1
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
  }, [entities])

  const filtered = useMemo(() => {
    return entities.filter((e) => {
      if (activeType && (e.type || 'Unknown') !== activeType) return false
      if (filter && !e.name.toLowerCase().includes(filter.toLowerCase()))
        return false
      return true
    })
  }, [entities, activeType, filter])

  // ── Focus mode: override type filter để show focused node + neighbors ──
  // Vấn đề tự nhiên: nếu filter type "Entity" + focus "chiến dịch", neighbors
  // của chiến dịch (vd KPI, Topic, Episodic) bị type filter loại trước khi
  // tới canvas → graph không có nodes đó → graph.neighbors() trả empty.
  // Fix: trong focus mode, compute subset từ `entities` đầy đủ (bypass type
  // filter), chỉ giữ focused node + 1-hop neighbors (theo edges).
  const visibleEntities = useMemo(() => {
    if (!focusedName) return filtered
    const neighborNames = new Set<string>([focusedName])
    for (const e of edges) {
      if (!e.source || !e.target) continue
      if (e.source === focusedName) neighborNames.add(e.target)
      if (e.target === focusedName) neighborNames.add(e.source)
    }
    // Lấy entities khớp tên (giữ thứ tự gốc cho stable layout)
    const filtered_subset = entities.filter((e) => neighborNames.has(e.name))
    // Nếu một số neighbor names không có trong entities (vd :Episodic bị API
    // exclude) — synthesize stub entity để node hiện lên
    const presentNames = new Set(filtered_subset.map((e) => e.name))
    const stubs: GraphEntity[] = []
    for (const name of neighborNames) {
      if (!presentNames.has(name)) {
        stubs.push({ name, type: 'Entity', summary: '' } as GraphEntity)
      }
    }
    return [...filtered_subset, ...stubs]
  }, [focusedName, filtered, entities, edges])

  const entityEdges = useMemo(() => {
    if (!activeEntity) return []
    return edges
      .filter(
        (e) =>
          e.source === activeEntity.name || e.target === activeEntity.name,
      )
      .slice(0, 30)
  }, [edges, activeEntity])

  async function onBuild() {
    if (!app.debugMode) {
      // Confirm message context-aware: lần đầu là "Build", có graph rồi là "Rebuild".
      // Backend cache extracted/sections.json + analyzed.json — rebuild thường
      // chỉ reload FalkorDB (~10s), không tốn LLM cost trừ khi user xóa cache.
      const isRebuild = !!graph
      const msg = isRebuild
        ? `Rebuild knowledge graph for ${campaignId}? Existing FalkorDB graph sẽ bị thay thế (cache LLM extract reuse, không tốn API cost).`
        : `Build knowledge graph for ${campaignId}?`
      if (!confirm(msg)) return
    }
    try {
      const res = await buildM.mutateAsync(campaignId)
      ui.success(`Graph built: ${res.nodes} nodes, ${res.edges} edges.`, 3000)
    } catch (e) {
      ui.error('Build failed: ' + (e as Error).message)
    }
  }

  // Phase 10: kg_status state machine — không còn snapshot/restore.
  //   fresh   → "Build graph" (full LLM pipeline)
  //   building → progress banner (fall through)
  //   active  → render Sigma viz (fall through)
  //   error   → fail state với retry button
  if (
    !graphsQ.isLoading &&
    !cacheStatusQ.isLoading &&
    graphState !== 'active' &&
    graphState !== 'building' &&
    !isBuilding
  ) {
    if (graphState === 'error') {
      return (
        <EmptyState
          icon={Network}
          title="KG build failed"
          description={
            `Last build attempt thất bại. ` +
            `Click Retry để rebuild từ source documents. ` +
            (cs?.last_modified_at ? `(Last error: ${cs.last_modified_at.slice(0, 16)})` : '')
          }
          action={
            <Button variant="primary" loading={buildM.isPending || isBuilding} onClick={onBuild}>
              <Sparkles size={13} />
              Retry build
            </Button>
          }
        />
      )
    }
    // graphState === 'fresh' (kg_status = 'not_built')
    return (
      <EmptyState
        icon={Network}
        title="No graph for this campaign"
        description="Build a knowledge graph from the campaign spec — extracts entities (Company, Product, Audience…) and their relationships into FalkorDB."
        action={
          <Button variant="primary" loading={buildM.isPending || isBuilding} onClick={onBuild}>
            <Sparkles size={13} />
            Build graph
          </Button>
        }
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {/* ── Build progress banner (granular stage + percent) ────────── */}
      {isBuilding && (
        <div className="rounded-md border border-brand-200 bg-brand-50 px-4 py-3 text-sm text-brand-900">
          <div className="flex items-center gap-3">
            <div className="relative flex h-2.5 w-2.5 shrink-0">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-75" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-500" />
            </div>
            <div className="flex-1">
              <span className="font-medium">
                {progress?.stage && progress.stage !== 'init'
                  ? formatStage(progress.stage)
                  : 'Đang build knowledge graph...'}
              </span>
              <span className="ml-2 text-fg-muted">
                {progress?.message ||
                  (entities.length > 0
                    ? `${entities.length} entities, ${edges.length} edges đã tạo. Tiếp tục...`
                    : 'Đang khởi tạo pipeline...')}
              </span>
            </div>
            {progress && progress.percent > 0 && (
              <span className="font-mono text-xs font-semibold tabular-nums text-brand-700">
                {progress.percent}%
              </span>
            )}
          </div>
          {/* Progress bar — animate khi % tăng */}
          {progress && progress.percent > 0 && (
            <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-brand-100">
              <div
                className="h-full rounded-full bg-brand-500 transition-all duration-700 ease-out"
                style={{ width: `${progress.percent}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* ── Top: Overview bar (horizontal compact) ─────────────────── */}
      <Card>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          {/* Stats inline */}
          <div className="flex items-center gap-4">
            <div>
              <div className="text-2xs font-medium uppercase tracking-wider text-fg-faint">
                Nodes
              </div>
              <div className="text-base font-semibold text-fg leading-tight">
                {statsQ.isLoading ? '—' : (graph?.nodes ?? 0)}
              </div>
            </div>
            <div className="h-8 w-px bg-border" aria-hidden />
            <div>
              <div className="text-2xs font-medium uppercase tracking-wider text-fg-faint">
                Edges
              </div>
              <div className="text-base font-semibold text-fg leading-tight">
                {statsQ.isLoading ? '—' : (graph?.edges ?? 0)}
              </div>
            </div>
            <div className="h-8 w-px bg-border" aria-hidden />
            <div>
              <div className="text-2xs font-medium uppercase tracking-wider text-fg-faint">
                Group
              </div>
              <div className="font-mono text-xs text-fg leading-tight">
                {groupId || '—'}
              </div>
            </div>
          </div>

          {/* Filter chips horizontal */}
          {typeCounts.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-2xs font-medium uppercase tracking-wider text-fg-faint mr-1">
                Filter:
              </span>
              <button
                onClick={() => setActiveType(null)}
                className={cn(
                  'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs transition-colors',
                  activeType === null
                    ? 'border-fg/30 bg-fg/5 text-fg'
                    : 'border-border bg-surface-subtle text-fg-muted hover:bg-surface hover:text-fg',
                )}
              >
                All
                <span className="font-mono text-2xs opacity-60">
                  {entities.length}
                </span>
              </button>
              {typeCounts.map(([type, count]) => (
                <button
                  key={type}
                  onClick={() =>
                    setActiveType(activeType === type ? null : type)
                  }
                  className={cn(
                    'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs transition-colors',
                    activeType === type
                      ? 'border-fg/30 bg-fg/5 text-fg'
                      : 'border-border bg-surface-subtle text-fg-muted hover:bg-surface hover:text-fg',
                  )}
                >
                  <span className="truncate">{type}</span>
                  <span className="font-mono text-2xs opacity-60">
                    {count}
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Rebuild button — pushed right */}
          <div className="ml-auto">
            <Button
              variant="secondary"
              size="sm"
              loading={buildM.isPending}
              onClick={onBuild}
            >
              <Sparkles size={13} />
              Rebuild
            </Button>
          </div>
        </div>
      </Card>

      {/* ── Bottom row: full-width canvas + detail sidebar ────────── */}
      <div className="grid grid-cols-[1fr_320px] gap-3 max-md:grid-cols-1">
        {/* Center: canvas / list */}
      <Card className="flex min-h-0 flex-col">
        <CardHeader className="border-b border-border pb-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <CardTitle className="text-sm">
                {viewMode === 'graph' ? 'Visualization' : 'Entities'}
                {filtered.length > 0 && (
                  <span className="ml-1.5 text-xs font-normal text-fg-faint">
                    {filtered.length}
                    {filtered.length !== entities.length && `/${entities.length}`}
                  </span>
                )}
              </CardTitle>
              {/* View mode toggle — Graph (default) vs List */}
              <div className="inline-flex items-center rounded-md border border-border bg-surface-subtle p-0.5 text-xs">
                <button
                  type="button"
                  onClick={() => setViewMode('graph')}
                  className={cn(
                    'inline-flex items-center gap-1 rounded px-2 py-1 transition-colors',
                    viewMode === 'graph'
                      ? 'bg-white text-fg shadow-sm'
                      : 'text-fg-muted hover:text-fg',
                  )}
                >
                  <LayoutGrid size={12} />
                  Graph
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode('list')}
                  className={cn(
                    'inline-flex items-center gap-1 rounded px-2 py-1 transition-colors',
                    viewMode === 'list'
                      ? 'bg-white text-fg shadow-sm'
                      : 'text-fg-muted hover:text-fg',
                  )}
                >
                  <ListIcon size={12} />
                  List
                </button>
              </div>
            </div>
            {viewMode === 'list' && (
              <div className="relative w-44">
                <Search
                  size={12}
                  className="absolute left-2 top-1/2 -translate-y-1/2 text-fg-faint"
                />
                <Input
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="Filter…"
                  className="h-7 pl-7 text-xs"
                />
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {entitiesQ.isError ? (
            <ErrorState
              title="Could not load entities"
              description={(entitiesQ.error as Error).message}
              onRetry={() => entitiesQ.refetch()}
            />
          ) : entitiesQ.isLoading ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : viewMode === 'graph' ? (
            // ── Graph viz (Sigma.js + Graphology + ForceAtlas2 worker) ──
            // WebGL renderer + off-main-thread layout — fast cho 100-500+
            // nodes. Fixed height ~75vh để full visible nhưng không che
            // footer/sidebar.
            <div className="relative h-[75vh] min-h-[500px]">
              {/* Focus mode banner */}
              {focusedName && (
                <div className="absolute left-3 top-12 z-20 flex items-center gap-2 rounded-md border border-brand-200 bg-brand-50/95 px-3 py-1.5 text-xs shadow-sm backdrop-blur-sm">
                  <span className="text-fg-muted">Focus:</span>
                  <span className="font-mono font-medium text-brand-700">
                    {focusedName}
                  </span>
                  <span className="text-2xs text-fg-muted">+ neighbors (1-hop)</span>
                  <button
                    onClick={() => setFocusedName(null)}
                    className="rounded px-1.5 py-0.5 text-2xs font-medium text-brand-700 hover:bg-brand-100"
                    title="Double-click vào node hoặc click đây để thoát focus"
                  >
                    Reset
                  </button>
                </div>
              )}
              <KGSigmaCanvas
                entities={visibleEntities}
                edges={edges}
                activeEntityName={activeEntity?.name || null}
                activeType={focusedName ? null : activeType}
                focusedName={focusedName}
                onSelect={(name) => {
                  const found = entities.find((e) => e.name === name)
                  if (found) setActiveEntity(found)
                }}
                onDoubleClickNode={(name) => {
                  // Toggle: double-click cùng node đang focus → reset
                  setFocusedName((prev) => (prev === name ? null : name))
                  // Cũng select node đó để sidebar detail show info
                  const found = entities.find((e) => e.name === name)
                  if (found) setActiveEntity(found)
                }}
              />
            </div>
          ) : filtered.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-fg-muted">
              No matches.
            </p>
          ) : (
            <ul className="max-h-[60vh] divide-y divide-border-subtle overflow-y-auto">
              {filtered.slice(0, 200).map((e, i) => (
                <li key={`${e.name}-${i}`}>
                  <button
                    onClick={() => setActiveEntity(e)}
                    className={cn(
                      'flex w-full items-start gap-2.5 px-4 py-2 text-left text-sm transition-colors',
                      activeEntity?.name === e.name
                        ? 'bg-surface-muted'
                        : 'hover:bg-surface-subtle',
                    )}
                  >
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-50 text-brand-600">
                      <Hash size={10} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2">
                        <span className="truncate font-medium text-fg">
                          {e.name}
                        </span>
                        {e.type && (
                          <span className="font-mono text-2xs text-fg-faint">
                            {e.type}
                          </span>
                        )}
                      </div>
                      {e.summary && (
                        <p className="mt-0.5 line-clamp-1 text-xs text-fg-muted">
                          {e.summary}
                        </p>
                      )}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Right: entity detail (edges) — luôn hiện vì layout 2-col rộng cho center */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">
            {activeEntity ? activeEntity.name : 'Detail'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {activeEntity ? (
            <div className="space-y-3 text-sm">
              {activeEntity.type && (
                <div>
                  <div className="text-2xs font-medium uppercase tracking-wider text-fg-faint">
                    Type
                  </div>
                  <Badge tone="brand" className="mt-1">
                    {activeEntity.type}
                  </Badge>
                </div>
              )}
              {activeEntity.summary && (
                <div>
                  <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-fg-faint">
                    Summary
                  </div>
                  <p className="leading-snug text-fg-muted">
                    {activeEntity.summary}
                  </p>
                </div>
              )}
              <div>
                <div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-fg-faint">
                  Edges
                  {entityEdges.length > 0 && (
                    <span className="ml-1.5 text-xs font-normal text-fg-faint normal-case">
                      {entityEdges.length}
                    </span>
                  )}
                </div>
                {entityEdges.length === 0 ? (
                  <p className="text-xs text-fg-muted">
                    No edges loaded for this entity.
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {entityEdges.map((e, i) => {
                      const fromMe = e.source === activeEntity.name
                      const other = fromMe ? e.target : e.source
                      return (
                        <li
                          key={i}
                          className="rounded-md border border-border bg-surface-subtle p-2 text-xs"
                        >
                          <div className="flex items-center gap-1.5">
                            {!fromMe && (
                              <ArrowRight
                                size={11}
                                className="rotate-180 text-fg-faint"
                              />
                            )}
                            <Badge tone="neutral">
                              {truncate(e.relation || 'rel', 18)}
                            </Badge>
                            {fromMe && (
                              <ArrowRight size={11} className="text-fg-faint" />
                            )}
                            <button
                              onClick={() =>
                                setActiveEntity(
                                  entities.find((x) => x.name === other) || null,
                                )
                              }
                              className="ml-1 truncate text-fg hover:text-brand-600"
                            >
                              {other}
                            </button>
                          </div>
                          {e.fact && (
                            <p className="mt-1 line-clamp-2 text-2xs text-fg-muted">
                              {e.fact}
                            </p>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            </div>
          ) : (
            <p className="text-xs text-fg-muted">
              Select an entity from the list to inspect its edges.
            </p>
          )}
        </CardContent>
      </Card>
      </div>
    </div>
  )
}

// Map machine stage codes (từ backend build_progress.py) → human label.
// Backend có thể thêm stages mới — fallback về stage code raw nếu chưa map.
function formatStage(stage: string): string {
  const map: Record<string, string> = {
    // Common stages
    init: 'Khởi tạo pipeline...',
    stage_1_parse: 'Stage 1: Parsing tài liệu',
    stage_1_cache_hit: 'Stage 1: Cache hit',
    stage_1_done: 'Stage 1: Parse xong',
    stage_2_analyzing: 'Stage 2: LLM analyze sections',
    stage_2_cache_hit: 'Stage 2: Cache hit (skip LLM)',
    stage_2_done: 'Stage 2: Analyze xong',
    stage_2_5_postprocess: 'Stage 2.5: Dedup canonical',
    stage_3_writing: 'Stage 3: Direct Cypher write',
    stage_3_indexes: 'Stage 3: Build indexes',
    // Zep hybrid stages
    zep_init: 'Zep: Init client',
    zep_create_graph: 'Zep: Create graph',
    zep_add_batch: 'Zep: Submit sections',
    zep_polling_tasks: 'Zep: Đang extract (server-side)',
    zep_fetch_nodes: 'Zep: Fetch entities + edges',
    zep_re_embedding: 'Re-embedding local',
    zep_cypher_mirror: 'Mirror to FalkorDB',
    zep_indexes: 'Build vector indexes',
    // Snapshot persistence (Phase A)
    snapshot_writing: 'Persist snapshot (JSON + ChromaDB)',
    snapshot_chroma_upsert: 'Upsert embeddings to ChromaDB',
    // Restore stages (Phase B)
    restore_lock: 'Acquiring restore lock',
    restore_chroma_fetch: 'Fetching embeddings from ChromaDB',
    restore_cypher_merge: 'Restoring graph to FalkorDB',
    restore_indexes: 'Rebuilding vector indexes',
    // Terminal
    done: 'Hoàn tất',
    failed: 'Build thất bại',
  }
  return map[stage] || stage
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-border bg-surface-subtle px-2.5 py-2">
      <div className="text-2xs font-medium uppercase tracking-wider text-fg-faint">
        {label}
      </div>
      <div className="text-lg font-semibold tabular-nums text-fg">{value}</div>
    </div>
  )
}
