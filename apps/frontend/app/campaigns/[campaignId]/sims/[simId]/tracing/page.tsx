'use client'

import { use, useMemo, useState } from 'react'
import {
  Activity,
  Brain,
  Sparkles,
  TrendingUp,
  TrendingDown,
  Plus,
  ArrowRight,
  Network,
  MessagesSquare,
  Search,
  User,
} from 'lucide-react'
import { useSim, useSimCognitive } from '@/lib/queries'
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardDescription,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/data/skeleton'
import { ErrorState } from '@/components/data/error-state'
import { EmptyState } from '@/components/data/empty-state'
import { TRAIT_META } from '@/lib/cognitive-traits'
import { cn } from '@/lib/utils'
import type {
  CognitiveRound,
  InterestItem,
} from '@/lib/api/sim'

// ── Helpers ───────────────────────────────────────────────────────────

/** Diff interest_vector giữa 2 round → list keywords mới + bị bỏ + thay đổi weight */
type InterestDiff = {
  added: InterestItem[]
  removed: { keyword: string; prev_weight: number }[]
  changed: { keyword: string; prev: number; curr: number; delta: number }[]
}

function diffInterests(
  prev: InterestItem[] | undefined,
  curr: InterestItem[],
): InterestDiff {
  const prevMap = new Map((prev || []).map((i) => [i.keyword, i.weight]))
  const currMap = new Map(curr.map((i) => [i.keyword, i.weight]))

  const added: InterestItem[] = []
  const changed: InterestDiff['changed'] = []
  for (const item of curr) {
    if (!prevMap.has(item.keyword)) {
      added.push(item)
    } else {
      const pw = prevMap.get(item.keyword)!
      const delta = item.weight - pw
      if (Math.abs(delta) >= 0.01) {
        changed.push({ keyword: item.keyword, prev: pw, curr: item.weight, delta })
      }
    }
  }

  const removed: InterestDiff['removed'] = []
  for (const [kw, w] of prevMap) {
    if (!currMap.has(kw)) {
      removed.push({ keyword: kw, prev_weight: w })
    }
  }

  // sort changed by abs(delta) desc
  changed.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
  return { added, removed, changed }
}

/** Persona evolution: highlight change vs base */
function personaChanged(base: string, evolved: string): boolean {
  return Boolean(evolved) && evolved.trim() !== base.trim()
}

// ── Render helpers ────────────────────────────────────────────────────

function TraitBar({ value, range }: { value: number; range: [number, number] }) {
  const pct = Math.max(
    0,
    Math.min(100, ((value - range[0]) / (range[1] - range[0])) * 100),
  )
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-muted">
      <div className="h-full bg-brand-500" style={{ width: `${pct}%` }} />
    </div>
  )
}

function InterestChip({
  item,
  variant = 'default',
}: {
  item: InterestItem
  variant?: 'default' | 'added' | 'removed'
}) {
  const tone =
    variant === 'added'
      ? 'success'
      : variant === 'removed'
        ? 'danger'
        : item.trending
          ? 'info'
          : 'neutral'
  return (
    <Badge tone={tone} className="font-mono text-2xs">
      {variant === 'added' && <Plus className="h-2.5 w-2.5" />}
      <span>{item.keyword}</span>
      <span className="opacity-70">·{item.weight.toFixed(2)}</span>
      {item.is_new && variant === 'default' && (
        <span title="new this round">✨</span>
      )}
    </Badge>
  )
}

/**
 * Unified Interest table — show every keyword in 1 view với weight bar +
 * delta vs round trước. Group: current keywords first (sort by weight desc),
 * then removed keywords (struck-through).
 */
function InterestTable({
  current,
  diff,
  hasPrev,
}: {
  current: InterestItem[]
  diff: InterestDiff
  hasPrev: boolean
}) {
  if (current.length === 0 && diff.removed.length === 0) {
    return (
      <div className="rounded border border-dashed border-border px-3 py-4 text-center text-xs italic text-fg-muted">
        Agent chưa có sở thích active. Có thể KeyBERT drift disabled hoặc round 0.
      </div>
    )
  }

  // Lookup map: keyword → {prev, delta} từ diff.changed
  const changedMap = new Map(
    diff.changed.map((c) => [c.keyword, c]),
  )
  const addedSet = new Set(diff.added.map((a) => a.keyword))

  // Sort current by weight desc
  const sortedCurrent = [...current].sort((a, b) => b.weight - a.weight)
  const maxWeight = sortedCurrent[0]?.weight || 1.0

  return (
    <div className="overflow-hidden rounded border border-border">
      <table className="w-full text-2xs">
        <thead className="bg-surface-subtle text-fg-muted">
          <tr>
            <th className="px-2 py-1.5 text-left font-medium">Keyword</th>
            <th className="px-2 py-1.5 text-left font-medium">Weight</th>
            <th className="px-2 py-1.5 text-right font-medium w-20">Δ</th>
          </tr>
        </thead>
        <tbody>
          {sortedCurrent.map((item) => {
            const isAdded = addedSet.has(item.keyword)
            const change = changedMap.get(item.keyword)
            const pct = (item.weight / maxWeight) * 100
            return (
              <tr
                key={item.keyword}
                className={cn(
                  'border-t border-border',
                  isAdded && 'bg-success-50/30',
                )}
              >
                <td className="px-2 py-1.5 font-mono">
                  <div className="flex items-center gap-1.5">
                    {isAdded && (
                      <Plus
                        className="h-3 w-3 text-success-700"
                        aria-label="new this round"
                      />
                    )}
                    {item.trending && !isAdded && (
                      <TrendingUp
                        className="h-3 w-3 text-info-600"
                        aria-label="trending"
                      />
                    )}
                    <span className="truncate" title={item.keyword}>
                      {item.keyword}
                    </span>
                    {item.source && item.source !== 'profile' && (
                      <Badge tone="outline" className="text-[10px]">
                        {item.source}
                      </Badge>
                    )}
                  </div>
                </td>
                <td className="px-2 py-1.5">
                  <div className="flex items-center gap-1.5">
                    <div className="h-1.5 flex-1 max-w-[120px] overflow-hidden rounded-full bg-surface-muted">
                      <div
                        className={cn(
                          'h-full',
                          isAdded ? 'bg-success-500' : 'bg-brand-500',
                        )}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="font-mono text-fg-muted shrink-0 w-9">
                      {item.weight.toFixed(2)}
                    </span>
                  </div>
                </td>
                <td className="px-2 py-1.5 text-right font-mono">
                  {isAdded ? (
                    <span className="text-success-700">NEW</span>
                  ) : change ? (
                    <span
                      className={
                        change.delta > 0
                          ? 'text-success-700'
                          : 'text-danger-600'
                      }
                    >
                      {change.delta > 0 ? '+' : ''}
                      {change.delta.toFixed(2)}
                    </span>
                  ) : hasPrev ? (
                    <span className="text-fg-muted opacity-50">—</span>
                  ) : (
                    <span className="text-fg-muted opacity-50">—</span>
                  )}
                </td>
              </tr>
            )
          })}
          {diff.removed.map((r) => (
            <tr
              key={`removed-${r.keyword}`}
              className="border-t border-border bg-danger-50/20 opacity-60"
            >
              <td className="px-2 py-1.5 font-mono">
                <div className="flex items-center gap-1.5">
                  <TrendingDown
                    className="h-3 w-3 text-danger-600"
                    aria-label="removed"
                  />
                  <span className="truncate line-through" title={r.keyword}>
                    {r.keyword}
                  </span>
                </div>
              </td>
              <td className="px-2 py-1.5">
                <div className="flex items-center gap-1.5">
                  <div className="h-1.5 flex-1 max-w-[120px] overflow-hidden rounded-full bg-surface-muted">
                    <div
                      className="h-full bg-danger-500/40"
                      style={{
                        width: `${(r.prev_weight / maxWeight) * 100}%`,
                      }}
                    />
                  </div>
                  <span className="font-mono text-fg-muted shrink-0 w-9 line-through">
                    {r.prev_weight.toFixed(2)}
                  </span>
                </div>
              </td>
              <td className="px-2 py-1.5 text-right font-mono text-danger-600">
                REMOVED
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────

export default function TracingPage({
  params,
}: {
  params: Promise<{ campaignId: string; simId: string }>
}) {
  const { simId } = use(params)
  const simQ = useSim(simId)
  const isRunning = simQ.data?.status === 'running'
  const cogQ = useSimCognitive(simId, { polling: isRunning })

  const [selectedRound, setSelectedRound] = useState<number | null>(null)
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null)

  // Phase 15.tracking: multi-agent tracking. Pick selected agent (default
  // first one trong list).
  const agentsList = cogQ.data?.agents || []
  const activeAgentTracking = useMemo(() => {
    if (agentsList.length === 0) return null
    if (selectedAgentId != null) {
      const found = agentsList.find((a) => a.agent.id === selectedAgentId)
      if (found) return found
    }
    return agentsList[0]
  }, [agentsList, selectedAgentId])

  // Auto-select latest round once data loads
  const rounds = activeAgentTracking?.rounds || []
  const activeRoundIdx = useMemo(() => {
    if (selectedRound != null) {
      const idx = rounds.findIndex((r) => r.round === selectedRound)
      if (idx >= 0) return idx
    }
    return Math.max(0, rounds.length - 1)
  }, [rounds, selectedRound])

  if (cogQ.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (cogQ.isError) {
    const msg = (cogQ.error as Error)?.message || ''
    if (msg.includes('404') || msg.toLowerCase().includes('not found')) {
      return (
        <EmptyState
          icon={Brain}
          title="Chưa có cognitive tracking"
          description={
            <>
              Sim này chưa bật tracking, hoặc chưa chạy round nào. Khi prepare
              sim, set <code className="font-mono">tracked_agent_id</code> {'>'}= 0
              để bật ghi <code className="font-mono">analysis/tracking.jsonl</code>.
            </>
          }
        />
      )
    }
    return <ErrorState title="Không tải được tracking" description={msg} />
  }

  if (!cogQ.data || agentsList.length === 0 || !activeAgentTracking) {
    return (
      <EmptyState
        icon={Brain}
        title="Tracking trống"
        description="File tracking.jsonl tồn tại nhưng chưa có round nào được ghi."
      />
    )
  }

  if (rounds.length === 0) {
    return (
      <EmptyState
        icon={Brain}
        title={`Agent ${activeAgentTracking.agent.name} chưa có round data`}
        description="Round 0 baseline có thể đã ghi cho agent khác. Chọn agent khác để xem."
      />
    )
  }

  const agent = activeAgentTracking.agent
  const currentRound: CognitiveRound = rounds[activeRoundIdx]
  const prevRound: CognitiveRound | undefined =
    activeRoundIdx > 0 ? rounds[activeRoundIdx - 1] : undefined
  const interestDiff = diffInterests(
    prevRound?.interest_vector,
    currentRound.interest_vector,
  )
  const personaEvolved = personaChanged(
    currentRound.base_persona,
    currentRound.evolved_persona,
  )

  return (
    <div className="space-y-6">
      {/* ── Header: agent info ───────────────────────────────────── */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <Brain className="h-5 w-5 text-brand-500" />
            <CardTitle>Cognitive Tracing — {agent.name || `Agent #${agent.id}`}</CardTitle>
            <Badge tone="brand">{agent.mbti}</Badge>
            <Badge tone="outline" className="font-mono">
              ID #{agent.id}
            </Badge>
            <span className="ml-auto text-xs text-fg-muted">
              {activeAgentTracking.total_rounds} rounds
              {agentsList.length > 1 && ` · ${agentsList.length} agents tracked`}
              {isRunning && (
                <span className="ml-2 inline-flex items-center gap-1 text-warning-600">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-warning-500" />
                  live
                </span>
              )}
            </span>
          </div>
          <CardDescription>
            Theo dõi sự tác động của các tính năng cognitive (memory, drift,
            reflection, graph context, MBTI modifiers) lên agent qua từng round.
          </CardDescription>
        </CardHeader>
      </Card>

      {/* ── Agent selector (multi-agent tracking) ────────────────── */}
      {agentsList.length > 1 && (
        <Card>
          <CardContent className="pt-4">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium text-fg-muted">
              <User className="h-3.5 w-3.5" />
              Chọn agent để xem ({agentsList.length} agents tracked)
            </div>
            <div className="flex flex-wrap gap-1.5">
              {agentsList.map((at) => {
                const isActive = at.agent.id === agent.id
                return (
                  <button
                    key={at.agent.id}
                    onClick={() => {
                      setSelectedAgentId(at.agent.id)
                      setSelectedRound(null)
                    }}
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition',
                      isActive
                        ? 'border-brand-500 bg-brand-50 text-brand-700'
                        : 'border-border bg-surface text-fg-muted hover:border-fg-muted hover:text-fg',
                    )}
                  >
                    <User className="h-3 w-3" />
                    <span className="font-medium">{at.agent.name || `Agent #${at.agent.id}`}</span>
                    <Badge tone={isActive ? 'brand' : 'outline'} className="text-2xs">
                      {at.agent.mbti}
                    </Badge>
                    <span className="font-mono text-2xs opacity-70">
                      #{at.agent.id} · {at.total_rounds}r
                    </span>
                  </button>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Round selector strip ─────────────────────────────────── */}
      <Card>
        <CardContent className="pt-4">
          <div className="mb-2 text-xs font-medium text-fg-muted">
            Chọn round để xem chi tiết
          </div>
          <div className="flex flex-wrap gap-1.5">
            {rounds.map((r, idx) => {
              const isActive = idx === activeRoundIdx
              const evolved = personaChanged(r.base_persona, r.evolved_persona)
              return (
                <button
                  key={r.round}
                  onClick={() => setSelectedRound(r.round)}
                  className={cn(
                    'group inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-mono transition',
                    isActive
                      ? 'border-brand-500 bg-brand-50 text-brand-700'
                      : 'border-border bg-surface text-fg-muted hover:border-fg-muted hover:text-fg',
                  )}
                >
                  <span>{r.round === 0 ? 'R0 (baseline)' : `R${r.round}`}</span>
                  {evolved && (
                    <Sparkles className="h-3 w-3 text-warning-500" aria-label="persona evolved" />
                  )}
                  {(r.drift_keywords || []).length > 0 && (
                    <Activity className="h-3 w-3 text-info-500" aria-label="drift detected" />
                  )}
                </button>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* ── Round detail ────────────────────────────────────────── */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Persona panel */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Sparkles className="h-4 w-4" />
              Persona
              {personaEvolved && (
                <Badge tone="warning" dot>
                  evolved
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div>
              <div className="mb-1 text-2xs uppercase tracking-wider text-fg-muted">
                Base persona
              </div>
              <div className="rounded border border-border bg-surface-subtle px-3 py-2 leading-relaxed">
                {currentRound.base_persona || (
                  <span className="text-fg-muted italic">(empty)</span>
                )}
              </div>
            </div>
            {personaEvolved && (
              <div>
                <div className="mb-1 text-2xs uppercase tracking-wider text-warning-600">
                  Evolved persona (sau reflection)
                </div>
                <div className="rounded border border-warning-200 bg-warning-50/50 px-3 py-2 leading-relaxed">
                  {currentRound.evolved_persona}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Cognitive traits panel */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Brain className="h-4 w-4" />
              Cognitive traits (MBTI-derived)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5">
            {TRAIT_META.map((tm) => {
              const t = currentRound.cognitive_traits[tm.key]
              if (!t) return null
              const range: [number, number] =
                tm.key === 'conviction'
                  ? [0.1, 1.0]
                  : tm.key === 'curiosity'
                    ? [0.1, 0.5]
                    : [0.05, 0.3]
              return (
                <div key={tm.key}>
                  <div className="mb-1 flex items-baseline justify-between gap-2">
                    <span className="text-xs font-medium">{tm.label}</span>
                    <span className="font-mono text-2xs text-fg-muted">
                      {t.value.toFixed(2)} · {tm.describe(t.value)}
                    </span>
                  </div>
                  <TraitBar value={t.value} range={range} />
                </div>
              )
            })}
            {currentRound.mbti_modifiers && (
              <div className="mt-3 border-t border-border pt-2">
                <div className="mb-1 text-2xs uppercase tracking-wider text-fg-muted">
                  MBTI action modifiers
                </div>
                <div className="font-mono text-2xs text-fg-muted">
                  {currentRound.mbti_modifiers}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Interest evolution — unified table ──────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <TrendingUp className="h-4 w-4" />
            Interest vector
            {prevRound && (
              <Badge tone="outline" className="ml-1 font-mono text-2xs">
                so với R{prevRound.round}
              </Badge>
            )}
            <span className="ml-auto text-2xs font-normal text-fg-muted">
              {currentRound.interest_vector.length} active
              {prevRound && interestDiff.added.length > 0 && (
                <span className="ml-2 text-success-700">
                  +{interestDiff.added.length} mới
                </span>
              )}
              {prevRound && interestDiff.removed.length > 0 && (
                <span className="ml-2 text-danger-600">
                  −{interestDiff.removed.length} bỏ
                </span>
              )}
            </span>
          </CardTitle>
          <CardDescription className="text-2xs">
            Sở thích của agent — KeyBERT drift + engagement adjust weight. Forgetfulness
            decay mỗi round; curiosity pickup keywords mới.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <InterestTable
            current={currentRound.interest_vector}
            diff={interestDiff}
            hasPrev={!!prevRound}
          />

          {currentRound.drift_keywords?.length > 0 && (
            <div className="mt-4 border-t border-border pt-3">
              <div className="mb-1.5 flex items-center gap-1 text-2xs uppercase tracking-wider text-info-600">
                <Activity className="h-3 w-3" />
                KeyBERT drift detected ({currentRound.drift_keywords.length})
              </div>
              <div className="flex flex-wrap gap-1">
                {currentRound.drift_keywords.map((k) => (
                  <Badge key={k} tone="info" className="font-mono text-2xs">
                    {k}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Search queries + memory + graph context ─────────────── */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Search className="h-4 w-4" />
              Search queries
            </CardTitle>
            <CardDescription className="text-2xs">
              Top semantic queries dùng cho feed retrieval
            </CardDescription>
          </CardHeader>
          <CardContent>
            {currentRound.search_queries.length > 0 ? (
              <ul className="space-y-1.5">
                {currentRound.search_queries.slice(0, 8).map((sq, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 rounded border border-border bg-surface-subtle px-2 py-1"
                  >
                    <span className="shrink-0 font-mono text-2xs text-brand-600">
                      {sq.weight.toFixed(2)}
                    </span>
                    <span className="line-clamp-2 text-2xs">{sq.query}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="rounded border border-dashed border-border px-3 py-4 text-center text-2xs italic text-fg-muted">
                Chưa có query nào — round 0 hoặc interest tracker disabled
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <MessagesSquare className="h-4 w-4" />
              Memory (FIFO 5-round)
            </CardTitle>
            <CardDescription className="text-2xs">
              Tóm tắt {' '}
              <span className="font-medium">5 round gần nhất</span>
              {' '}inject vào prompt sinh post/comment
            </CardDescription>
          </CardHeader>
          <CardContent>
            {currentRound.memory ? (
              <div className="max-h-64 overflow-y-auto rounded border border-border bg-surface-subtle px-2 py-2">
                <pre className="whitespace-pre-wrap text-2xs leading-relaxed text-fg">
                  {currentRound.memory}
                </pre>
              </div>
            ) : (
              <div className="rounded border border-dashed border-border px-3 py-4 text-center text-2xs italic text-fg-muted">
                Round 0 chưa có history. Hoặc cognitive_toggles.enable_agent_memory =
                false ở config.
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Network className="h-4 w-4" />
              Graph context
            </CardTitle>
            <CardDescription className="text-2xs">
              Context xã hội từ FalkorDB. Trước khi agent post/comment, hệ thống
              hỏi graph: <em>"agent này đã tương tác với ai, chủ đề gì?"</em>
              {' '}rồi inject kết quả tóm tắt vào prompt.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {currentRound.graph_context ? (
              <div className="max-h-64 overflow-y-auto rounded border border-border bg-surface-subtle px-2 py-2">
                <pre className="whitespace-pre-wrap text-2xs leading-relaxed text-fg">
                  {currentRound.graph_context}
                </pre>
              </div>
            ) : (
              <div className="rounded border border-dashed border-border px-3 py-3 text-2xs text-fg-muted">
                <div className="mb-1 font-medium text-fg">Empty</div>
                <ul className="space-y-0.5 list-disc pl-4">
                  <li>
                    <span className="font-mono">enable_graph_cognition</span> =
                    false ở SIM_CONFIG, hoặc
                  </li>
                  <li>Round 0 — graph chưa có agent activity history, hoặc</li>
                  <li>
                    Graphiti hybrid search trả empty (sim graph fresh, chưa có
                    semantic edges)
                  </li>
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Actions taken this round ────────────────────────────── */}
      {currentRound.actions?.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Activity className="h-4 w-4" />
              Actions trong round R{currentRound.round} ({currentRound.actions.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-xs">
              {currentRound.actions.map((a, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 border-b border-border py-1.5 last:border-0"
                >
                  <Badge tone="outline" className="font-mono shrink-0">
                    {a.type}
                  </Badge>
                  <span className="line-clamp-2 text-fg-muted">{a.text}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
