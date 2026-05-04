'use client'

import { use, useMemo, useState } from 'react'
import dynamic from 'next/dynamic'
import { Network, Hash, ArrowRight, Search } from 'lucide-react'
import {
  useCacheStatus,
  useGraphEntities,
  useGraphEdges,
  useSim,
} from '@/lib/queries'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/data/skeleton'
import { ErrorState } from '@/components/data/error-state'
import { EmptyState } from '@/components/data/empty-state'
import { cn, truncate } from '@/lib/utils'
import type { GraphEntity, KGStatus } from '@/lib/types/backend'

const KGSigmaCanvas = dynamic(
  () =>
    import('@/components/graph/kg-sigma-canvas').then((m) => m.KGSigmaCanvas),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center text-xs text-fg-faint">
        Đang tải graph engine…
      </div>
    ),
  },
)

const STATUS_TONE: Record<KGStatus, 'success' | 'warning' | 'danger' | 'info' | 'neutral'> = {
  not_built: 'neutral',
  building: 'warning',
  pending: 'neutral',
  forking: 'warning',
  ready: 'info',
  mutating: 'warning',
  completed: 'success',
  error: 'danger',
}

export default function SimGraphPage({
  params,
}: {
  params: Promise<{ campaignId: string; simId: string }>
}) {
  const { simId } = use(params)
  const simQ = useSim(simId)

  // Phase 10: cache-status từ meta.db trả về kg_graph_name = "sim_<sid>".
  // Polling khi sim đang running/mutating để pickup mutation real-time.
  const isLive =
    simQ.data?.status === 'running' ||
    simQ.data?.status === 'preparing'
  const cacheQ = useCacheStatus({ simId }, { polling: isLive })
  const cs = cacheQ.data
  const kgGraphName = cs?.kg_graph_name || ''
  const kgReady =
    cs?.kg_status === 'ready' ||
    cs?.kg_status === 'mutating' ||
    cs?.kg_status === 'completed'

  const entitiesQ = useGraphEntities(kgReady ? kgGraphName : null, 300, {
    polling: isLive,
  })
  const edgesQ = useGraphEdges(kgReady ? kgGraphName : null, 500, {
    polling: isLive,
  })

  const [filter, setFilter] = useState('')
  const [activeType, setActiveType] = useState<string | null>(null)
  const [activeEntity, setActiveEntity] = useState<GraphEntity | null>(null)
  // Focus mode: double-click node → show node + 1-hop neighbors only.
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

  const filteredEntities = useMemo(() => {
    let list = entities
    if (activeType) list = list.filter((e) => (e.type || 'Unknown') === activeType)
    if (filter) {
      const q = filter.toLowerCase()
      list = list.filter(
        (e) =>
          e.name.toLowerCase().includes(q) ||
          (e.summary || '').toLowerCase().includes(q),
      )
    }
    return list
  }, [entities, activeType, filter])

  // ── Focus mode: bypass type filter, build neighbor set từ FULL edges ──
  // Tránh case neighbors của focused node bị type filter loại trước → graph
  // không có nodes đó → graph.neighbors() trả empty.
  const visibleEntities = useMemo(() => {
    if (!focusedName) return filteredEntities
    const neighborNames = new Set<string>([focusedName])
    for (const e of edges) {
      if (!e.source || !e.target) continue
      if (e.source === focusedName) neighborNames.add(e.target)
      if (e.target === focusedName) neighborNames.add(e.source)
    }
    const subset = entities.filter((e) => neighborNames.has(e.name))
    // Synthesize stub cho neighbors không có trong /entities API (vd :Episodic)
    const presentNames = new Set(subset.map((e) => e.name))
    const stubs: GraphEntity[] = []
    for (const name of neighborNames) {
      if (!presentNames.has(name)) {
        stubs.push({ name, type: 'Entity', summary: '' } as GraphEntity)
      }
    }
    return [...subset, ...stubs]
  }, [focusedName, filteredEntities, entities, edges])

  const neighborhood = useMemo(() => {
    if (!activeEntity) return null
    const inbound = edges.filter((e) => e.target === activeEntity.name)
    const outbound = edges.filter((e) => e.source === activeEntity.name)
    return { inbound, outbound }
  }, [edges, activeEntity])

  // Loading + empty states ─────────────────────────────────────────
  if (simQ.isLoading || cacheQ.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-[60vh] w-full" />
      </div>
    )
  }

  if (cacheQ.isError) {
    return (
      <ErrorState
        title="Không load được trạng thái KG"
        description={(cacheQ.error as Error)?.message ?? 'Unknown error'}
        onRetry={() => cacheQ.refetch()}
      />
    )
  }

  if (!cs) {
    return (
      <EmptyState
        icon={Network}
        title="Sim chưa có graph metadata"
        description="meta.db không có kg_status cho sim này. Có thể sim được tạo bằng prepare flow cũ — tạo sim mới."
      />
    )
  }

  if (cs.kg_status === 'error') {
    return (
      <EmptyState
        icon={Network}
        title="Sim graph error"
        description={`Clone master KG vào sim graph thất bại. last_modified=${cs.last_modified_at?.slice(0, 16) ?? '?'}. Tạo sim mới để retry.`}
      />
    )
  }

  if (
    cs.kg_status === 'pending' ||
    cs.kg_status === 'forking'
  ) {
    return (
      <EmptyState
        icon={Network}
        title={`Sim graph đang ${cs.kg_status === 'forking' ? 'clone' : 'pending'}…`}
        description="Master KG đang được clone vào sim graph. Tự refresh khi xong."
      />
    )
  }

  // ── Render graph ─────────────────────────────────────────────────
  return (
    <div className="-mx-6 -my-6 grid h-[calc(100vh-120px)] grid-cols-[260px_1fr_320px] gap-0 overflow-hidden">
      {/* Left: types + filter */}
      <div className="flex flex-col border-r border-border bg-surface-subtle px-4 py-4">
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-muted">
          Sim KG
        </h3>
        <div className="mb-3 grid grid-cols-3 gap-2 text-center">
          <KPI label="Nodes" value={cs.node_count} />
          <KPI label="Edges" value={cs.edge_count} />
          <KPI label="Episodes" value={cs.episode_count} />
        </div>
        <div className="mb-3 flex items-center gap-1.5">
          <Badge tone={STATUS_TONE[cs.kg_status]} dot>
            {cs.kg_status}
          </Badge>
          <span className="text-[10px] text-fg-faint font-mono">
            {kgGraphName}
          </span>
        </div>

        <div className="relative mb-2">
          <Search
            size={12}
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-fg-faint"
          />
          <Input
            placeholder="Search nodes…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="pl-7"
          />
        </div>

        <div className="flex-1 overflow-y-auto pr-1">
          <div className="mb-1.5 text-[10px] uppercase tracking-wide text-fg-faint">
            Entity types ({typeCounts.length})
          </div>
          <div className="space-y-0.5">
            <button
              onClick={() => setActiveType(null)}
              className={cn(
                'w-full rounded px-2 py-1 text-left text-xs transition-colors',
                !activeType
                  ? 'bg-brand-100 text-brand-700'
                  : 'hover:bg-surface-emphasis text-fg-muted',
              )}
            >
              <span className="font-medium">All</span>
              <span className="float-right text-fg-faint">{entities.length}</span>
            </button>
            {typeCounts.map(([type, count]) => (
              <button
                key={type}
                onClick={() => setActiveType(type === activeType ? null : type)}
                className={cn(
                  'w-full rounded px-2 py-1 text-left text-xs transition-colors',
                  activeType === type
                    ? 'bg-brand-100 text-brand-700'
                    : 'hover:bg-surface-emphasis text-fg-muted',
                )}
              >
                <span className="font-medium">{type}</span>
                <span className="float-right text-fg-faint">{count}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Center: Sigma canvas */}
      <div className="relative">
        {entitiesQ.isLoading || edgesQ.isLoading ? (
          <div className="flex h-full items-center justify-center text-xs text-fg-faint">
            Loading graph…
          </div>
        ) : entities.length === 0 ? (
          <EmptyState
            icon={Network}
            title="Sim graph empty"
            description="Không có nodes nào. Có thể clone fail hoặc graph chưa load."
          />
        ) : (
          <>
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
              activeEntityName={activeEntity?.name ?? null}
              activeType={focusedName ? null : activeType}
              focusedName={focusedName}
              onSelect={(name) => {
                const found = entities.find((e) => e.name === name)
                if (found) setActiveEntity(found)
              }}
              onDoubleClickNode={(name) => {
                setFocusedName((prev) => (prev === name ? null : name))
                const found = entities.find((e) => e.name === name)
                if (found) setActiveEntity(found)
              }}
            />
          </>
        )}
      </div>

      {/* Right: detail panel */}
      <div className="flex flex-col border-l border-border bg-surface-subtle px-4 py-4">
        {activeEntity ? (
          <>
            <div className="mb-3 flex items-center gap-2">
              <Hash size={14} className="text-fg-muted" />
              <span className="font-mono text-sm font-medium text-fg">
                {truncate(activeEntity.name, 30)}
              </span>
            </div>
            <Badge tone="info">{activeEntity.type || 'Unknown'}</Badge>
            {activeEntity.summary ? (
              <p className="mt-3 text-xs leading-relaxed text-fg-muted">
                {activeEntity.summary}
              </p>
            ) : null}

            {neighborhood ? (
              <div className="mt-4 flex-1 overflow-y-auto">
                <Card className="mb-3">
                  <CardHeader>
                    <CardTitle className="text-xs">
                      Outbound edges ({neighborhood.outbound.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1">
                    {neighborhood.outbound.slice(0, 30).map((e, idx) => (
                      <div
                        key={idx}
                        className="flex items-start gap-1.5 text-xs text-fg-muted"
                      >
                        <ArrowRight size={10} className="mt-0.5 shrink-0" />
                        <div>
                          <span className="font-mono text-[10px] text-fg-faint">
                            {e.relation || 'RELATES_TO'}
                          </span>
                          <span className="ml-1 text-fg">→ {e.target}</span>
                        </div>
                      </div>
                    ))}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle className="text-xs">
                      Inbound edges ({neighborhood.inbound.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1">
                    {neighborhood.inbound.slice(0, 30).map((e, idx) => (
                      <div
                        key={idx}
                        className="flex items-start gap-1.5 text-xs text-fg-muted"
                      >
                        <ArrowRight size={10} className="mt-0.5 shrink-0 rotate-180" />
                        <div>
                          <span className="font-mono text-[10px] text-fg-faint">
                            {e.relation || 'RELATES_TO'}
                          </span>
                          <span className="ml-1 text-fg">← {e.source}</span>
                        </div>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              </div>
            ) : null}
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-center text-xs text-fg-faint">
            Click vào node trong graph để xem chi tiết.
          </div>
        )}
      </div>
    </div>
  )
}

function KPI({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-border bg-surface px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</div>
      <div className="text-sm font-semibold text-fg">{value.toLocaleString()}</div>
    </div>
  )
}
