'use client'

import { use, useEffect, useMemo, useState } from 'react'
import {
  Users,
  Search,
  Sparkles,
  Activity,
  Heart,
  Globe,
  Brain,
  Zap,
} from 'lucide-react'
import {
  getCognitiveTraits,
  TRAIT_META,
  TRAIT_RANGE,
} from '@/lib/cognitive-traits'
import {
  getBehaviorModifiers,
  MODIFIER_META,
  MODIFIER_VISUAL_RANGE,
} from '@/lib/mbti-modifiers'
import { useSimProfiles } from '@/lib/queries'
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/data/skeleton'
import { ErrorState } from '@/components/data/error-state'
import { EmptyState } from '@/components/data/empty-state'
import { cn } from '@/lib/utils'
import type { AgentProfile, MBTIType } from '@/lib/types/backend'

// MBTI grouping cho filter chip — 4 nhóm Keirsey temperament.
// Giúp user filter nhanh thay vì 16 buttons.
const MBTI_GROUPS: { label: string; types: MBTIType[]; tone: 'brand' | 'success' | 'warning' | 'info' }[] = [
  { label: 'Analysts (NT)', types: ['INTJ', 'INTP', 'ENTJ', 'ENTP'], tone: 'brand' },
  { label: 'Diplomats (NF)', types: ['INFJ', 'INFP', 'ENFJ', 'ENFP'], tone: 'success' },
  { label: 'Sentinels (SJ)', types: ['ISTJ', 'ISFJ', 'ESTJ', 'ESFJ'], tone: 'warning' },
  { label: 'Explorers (SP)', types: ['ISTP', 'ISFP', 'ESTP', 'ESFP'], tone: 'info' },
]

function mbtiTone(mbti: MBTIType): 'brand' | 'success' | 'warning' | 'info' | 'neutral' {
  for (const g of MBTI_GROUPS) {
    if (g.types.includes(mbti)) return g.tone
  }
  return 'neutral'
}

export default function SimAgentsPage({
  params,
}: {
  params: Promise<{ campaignId: string; simId: string }>
}) {
  const { simId } = use(params)
  const profilesQ = useSimProfiles(simId)

  const [filter, setFilter] = useState('')
  const [activeMbti, setActiveMbti] = useState<MBTIType | null>(null)
  const [activeAgentId, setActiveAgentId] = useState<number | null>(null)

  const profiles = profilesQ.data || []

  const mbtiCounts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const p of profiles) m[p.mbti] = (m[p.mbti] || 0) + 1
    return m
  }, [profiles])

  const filtered = useMemo(() => {
    return profiles.filter((p) => {
      if (activeMbti && p.mbti !== activeMbti) return false
      if (filter) {
        const q = filter.toLowerCase()
        const hay = [
          p.realname,
          p.username,
          p.bio,
          p.persona,
          p.specific_domain,
          p.general_domain,
          ...(p.interests || []),
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [profiles, filter, activeMbti])

  const activeProfile =
    activeAgentId != null
      ? profiles.find((p) => p.agent_id === activeAgentId) || null
      : null

  // Auto-select đầu tiên khi load xong + chưa pick gì.
  useEffect(() => {
    if (!profilesQ.isLoading && profiles.length > 0 && activeAgentId == null) {
      setActiveAgentId(profiles[0].agent_id)
    }
  }, [profilesQ.isLoading, profiles, activeAgentId])

  if (profilesQ.isError) {
    const msg = (profilesQ.error as Error).message
    const isNotFound = /404|not found/i.test(msg)
    return (
      <ErrorState
        title={isNotFound ? 'Profiles chưa được sinh' : 'Could not load profiles'}
        description={
          isNotFound
            ? 'Sim này chưa hoàn tất Prepare. Khi Prepare xong → profiles.json sẽ xuất hiện ở data/simulations/<sid>/.'
            : msg
        }
        onRetry={() => profilesQ.refetch()}
      />
    )
  }

  return (
    <div className="grid grid-cols-[340px_1fr] gap-4 max-lg:grid-cols-1">
      {/* ── Left: list ── */}
      <div className="flex min-h-0 flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-md font-semibold text-fg">
            Agents{' '}
            <span className="ml-1 font-normal text-fg-muted">
              {profilesQ.isLoading ? '' : `(${profiles.length})`}
            </span>
          </h2>
        </div>

        <div className="relative">
          <Search
            size={13}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-faint"
          />
          <Input
            placeholder="Search name / interests / domain…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="pl-7"
          />
        </div>

        {/* MBTI temperament filter */}
        <div className="flex flex-wrap gap-1">
          <button
            onClick={() => setActiveMbti(null)}
            className={cn(
              'rounded-md px-2 py-0.5 text-2xs font-medium transition-colors',
              activeMbti == null
                ? 'bg-fg text-surface'
                : 'bg-surface-muted text-fg-muted hover:bg-surface-subtle hover:text-fg',
            )}
          >
            All ({profiles.length})
          </button>
          {MBTI_GROUPS.map((g) => {
            const total = g.types.reduce((s, t) => s + (mbtiCounts[t] || 0), 0)
            if (total === 0) return null
            return (
              <div key={g.label} className="flex items-center gap-0.5">
                {g.types.map((t) => {
                  const c = mbtiCounts[t] || 0
                  if (c === 0) return null
                  return (
                    <button
                      key={t}
                      onClick={() =>
                        setActiveMbti((prev) => (prev === t ? null : t))
                      }
                      className={cn(
                        'rounded-md px-1.5 py-0.5 font-mono text-2xs font-medium transition-colors',
                        activeMbti === t
                          ? 'bg-fg text-surface'
                          : 'bg-surface-muted text-fg-muted hover:bg-surface-subtle hover:text-fg',
                      )}
                      title={`${t} · ${c} agent${c > 1 ? 's' : ''}`}
                    >
                      {t}
                      <span className="ml-1 text-fg-faint">{c}</span>
                    </button>
                  )
                })}
              </div>
            )
          })}
        </div>

        {/* List */}
        <Card className="flex-1 overflow-hidden p-0">
          {profilesQ.isLoading ? (
            <div className="space-y-2 p-3">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={Users}
              title={profiles.length === 0 ? 'No agents' : 'No matches'}
              description={
                profiles.length === 0
                  ? 'Run Prepare to generate agents.'
                  : 'Adjust your search or filter.'
              }
              className="border-0 bg-transparent py-8"
            />
          ) : (
            <div className="max-h-[calc(100vh-22rem)] overflow-y-auto">
              <ul className="divide-y divide-border-subtle">
                {filtered.map((p) => (
                  <li key={p.agent_id}>
                    <button
                      onClick={() => setActiveAgentId(p.agent_id)}
                      className={cn(
                        'flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors',
                        activeAgentId === p.agent_id
                          ? 'bg-brand-50'
                          : 'hover:bg-surface-subtle',
                      )}
                    >
                      <Avatar
                        name={p.realname}
                        active={activeAgentId === p.agent_id}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-1.5">
                          <span className="truncate text-sm font-medium text-fg">
                            {p.realname}
                          </span>
                          <span className="font-mono text-2xs text-fg-faint">
                            #{p.agent_id}
                          </span>
                        </div>
                        <div className="mt-0.5 flex items-center gap-1.5 text-2xs text-fg-muted">
                          <Badge tone={mbtiTone(p.mbti)} className="text-2xs">
                            {p.mbti}
                          </Badge>
                          <span>·</span>
                          <span>{p.age}y</span>
                          <span>·</span>
                          <span className="capitalize">{p.gender}</span>
                        </div>
                        {p.bio && (
                          <p className="mt-1 line-clamp-1 text-2xs text-fg-muted">
                            {p.bio}
                          </p>
                        )}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>

      {/* ── Right: detail ── */}
      <div className="min-w-0">
        {profilesQ.isLoading ? (
          <Card className="p-6">
            <Skeleton className="mb-3 h-7 w-1/2" />
            <Skeleton className="mb-1.5 h-3 w-full" />
            <Skeleton className="mb-1.5 h-3 w-11/12" />
            <Skeleton className="h-3 w-3/4" />
          </Card>
        ) : !activeProfile ? (
          <EmptyState
            icon={Users}
            title="Pick an agent"
            description="Click an agent on the left to inspect persona + behavior parameters."
          />
        ) : (
          <AgentDetail profile={activeProfile} />
        )}
      </div>
    </div>
  )
}

// ── Detail panel ─────────────────────────────────────────────────

function AgentDetail({ profile: p }: { profile: AgentProfile }) {
  return (
    <div className="space-y-3">
      {/* Header */}
      <Card>
        <CardContent className="pt-5">
          <div className="flex items-start gap-4">
            <Avatar name={p.realname} size="lg" active />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-2">
                <h2 className="text-md font-semibold text-fg">{p.realname}</h2>
                <span className="font-mono text-xs text-fg-faint">
                  @{p.username} · #{p.agent_id}
                </span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
                <Badge tone={mbtiTone(p.mbti)} dot>
                  {p.mbti}
                </Badge>
                <span>·</span>
                <span>
                  {p.age}y · <span className="capitalize">{p.gender}</span>
                </span>
                {p.country && (
                  <>
                    <span>·</span>
                    <span className="inline-flex items-center gap-0.5">
                      <Globe size={11} className="text-fg-faint" />
                      {p.country}
                    </span>
                  </>
                )}
              </div>
              {p.bio && (
                <p className="mt-2 text-sm text-fg-muted">{p.bio}</p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Runtime stats */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            <span className="inline-flex items-center gap-1.5">
              <Activity size={13} className="text-fg-muted" />
              Runtime parameters
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-xs sm:grid-cols-4">
            <Stat
              label="Posts/week"
              value={p.posts_per_week ?? '—'}
              hint="Posting frequency cap"
            />
            <Stat
              label="Activity"
              value={
                p.activity_level != null
                  ? `${(p.activity_level * 100).toFixed(0)}%`
                  : '—'
              }
              hint="0=lurker · 1=power user"
            />
            <Stat
              label="Daily hrs"
              value={p.daily_hours != null ? p.daily_hours.toFixed(1) : '—'}
              hint="Avg time online"
            />
            <Stat label="Followers" value={p.followers ?? '—'} />
            {(p.general_domain || p.specific_domain) && (
              <div className="col-span-2 sm:col-span-3">
                <div className="text-2xs text-fg-muted">Domain</div>
                <div className="mt-0.5 text-fg">
                  {p.specific_domain || p.general_domain}
                  {p.general_domain && p.specific_domain && (
                    <span className="ml-1 text-fg-faint">
                      ({p.general_domain})
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Interests */}
          {p.interests && p.interests.length > 0 && (
            <div className="mt-4">
              <div className="mb-1.5 inline-flex items-center gap-1.5 text-2xs text-fg-muted">
                <Heart size={11} />
                Interests
              </div>
              <div className="flex flex-wrap gap-1">
                {p.interests.map((kw) => (
                  <Badge key={kw} tone="outline" className="font-normal">
                    {kw}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Cognitive traits — derived from MBTI ở runtime
          (xem agent_cognition.py:get_cognitive_traits()). */}
      <CognitiveTraitsCard mbti={p.mbti} />

      {/* MBTI behavior modifiers — derived from MBTI ở runtime
          (xem agent_cognition.py:get_behavior_modifiers()). */}
      <BehaviorModifiersCard mbti={p.mbti} />

      {/* Persona */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            <span className="inline-flex items-center gap-1.5">
              <Sparkles size={13} className="text-brand-500" />
              Persona
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="whitespace-pre-line text-sm leading-relaxed text-fg">
            {p.persona}
          </p>

          {/* Tier B post-reflection evolved persona */}
          {p.persona_evolved && p.persona_evolved !== p.persona && (
            <details className="mt-3">
              <summary className="cursor-pointer select-none text-2xs font-medium text-brand-600 hover:text-brand-700">
                Show evolved persona (post-reflection)
              </summary>
              <p className="mt-2 whitespace-pre-line border-l-2 border-brand-500 pl-3 text-sm leading-relaxed text-fg-muted">
                {p.persona_evolved}
              </p>
              {p.reflection_insights && p.reflection_insights.length > 0 && (
                <ul className="mt-2 space-y-0.5 pl-4 text-xs text-fg-muted">
                  {p.reflection_insights.map((ins, i) => (
                    <li key={i} className="list-disc">
                      {ins}
                    </li>
                  ))}
                </ul>
              )}
            </details>
          )}

          {p.original_persona &&
            p.original_persona !== p.persona &&
            p.original_persona !== p.persona_evolved && (
              <details className="mt-3">
                <summary className="cursor-pointer select-none text-2xs font-medium text-fg-muted hover:text-fg">
                  Show original (pre-enrichment)
                </summary>
                <p className="mt-2 whitespace-pre-line border-l-2 border-border pl-3 text-2xs leading-relaxed text-fg-muted">
                  {p.original_persona}
                </p>
              </details>
            )}
        </CardContent>
      </Card>
    </div>
  )
}

// ── Cognitive traits panel ───────────────────────────────────────

function CognitiveTraitsCard({ mbti }: { mbti: string }) {
  const traits = getCognitiveTraits(mbti)
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          <span className="inline-flex items-center gap-1.5">
            <Brain size={13} className="text-fg-muted" />
            Cognitive traits
            <span className="ml-1 text-2xs font-normal text-fg-faint">
              derived from {mbti}
            </span>
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {TRAIT_META.map((meta) => {
            const value = traits[meta.key]
            const [lo, hi] = TRAIT_RANGE[meta.key]
            const pct = ((value - lo) / (hi - lo)) * 100
            return (
              <div
                key={meta.key}
                className="rounded-md border border-border bg-surface-subtle px-3 py-2.5"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-xs font-medium text-fg">
                    {meta.label}
                  </span>
                  <span className="font-mono text-2xs text-fg-muted">
                    {value.toFixed(2)}
                    <span className="ml-1 text-fg-faint">
                      / {hi.toFixed(2)}
                    </span>
                  </span>
                </div>
                <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-muted">
                  <div
                    className="h-full bg-brand-500 transition-all"
                    style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
                  />
                </div>
                <div className="mt-1.5 flex items-baseline justify-between gap-2 text-2xs">
                  <span className="font-medium text-fg-muted">
                    {meta.describe(value)}
                  </span>
                </div>
                <p className="mt-1 text-2xs text-fg-faint">{meta.hint}</p>
              </div>
            )
          })}
        </div>
        <p className="mt-3 text-2xs text-fg-faint">
          Traits suy từ MBTI tại runtime — xem chi tiết ở{' '}
          <code className="font-mono">apps/simulation/agent_cognition.py</code>.
          Giá trị trên là baseline; reflection có thể nudge keywords
          (không đổi traits).
        </p>
      </CardContent>
    </Card>
  )
}

// ── Behavior modifiers panel ─────────────────────────────────────

function BehaviorModifiersCard({ mbti }: { mbti: string }) {
  const mods = getBehaviorModifiers(mbti)
  const [visMin, visMax] = MODIFIER_VISUAL_RANGE
  const visRange = visMax - visMin
  // Vị trí baseline 1.0 trong dải hiển thị → để vẽ vạch giữa.
  const baselinePct = ((1.0 - visMin) / visRange) * 100

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          <span className="inline-flex items-center gap-1.5">
            <Zap size={13} className="text-fg-muted" />
            Behavior modifiers
            <span className="ml-1 text-2xs font-normal text-fg-faint">
              derived from {mbti}
            </span>
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {MODIFIER_META.map((meta) => {
            const value = mods[meta.key]
            const valuePct = ((value - visMin) / visRange) * 100
            const tone =
              value > 1.0 ? 'amplify' : value < 1.0 ? 'dampen' : 'neutral'
            return (
              <div
                key={meta.key}
                className="rounded-md border border-border bg-surface-subtle px-3 py-2.5"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-xs font-medium text-fg">
                    {meta.label}
                  </span>
                  <span
                    className={cn(
                      'font-mono text-2xs font-semibold',
                      tone === 'amplify' && 'text-success-600',
                      tone === 'dampen' && 'text-danger-500',
                      tone === 'neutral' && 'text-fg-muted',
                    )}
                  >
                    {value.toFixed(2)}×
                  </span>
                </div>
                {/* Bar with baseline 1.0 marker */}
                <div className="relative mt-2 h-1.5 overflow-hidden rounded-full bg-surface-muted">
                  {/* Filled segment from baseline → value, direction depends on amplify/dampen */}
                  {tone !== 'neutral' && (
                    <div
                      className={cn(
                        'absolute inset-y-0',
                        tone === 'amplify' ? 'bg-success-500' : 'bg-danger-500',
                      )}
                      style={{
                        left:
                          tone === 'amplify'
                            ? `${baselinePct}%`
                            : `${valuePct}%`,
                        width: `${Math.abs(valuePct - baselinePct)}%`,
                      }}
                    />
                  )}
                  {/* Baseline 1.0 marker */}
                  <div
                    className="absolute inset-y-0 w-px bg-fg-muted"
                    style={{ left: `${baselinePct}%` }}
                  />
                </div>
                <div className="mt-1 flex justify-between text-2xs text-fg-faint">
                  <span>{visMin.toFixed(1)}</span>
                  <span className="font-mono text-fg-muted">1.0</span>
                  <span>{visMax.toFixed(1)}</span>
                </div>
                <p className="mt-1.5 text-2xs text-fg-muted">{meta.hint}</p>
              </div>
            )
          })}
        </div>
        <p className="mt-3 text-2xs text-fg-faint">
          Multipliers nhân vào base action probability mỗi round, chỉ apply
          khi <code className="font-mono">enable_mbti_modifiers=true</code>{' '}
          (toggle ở Prepare wizard). Mapping ở{' '}
          <code className="font-mono">apps/simulation/agent_cognition.py</code>.
        </p>
      </CardContent>
    </Card>
  )
}

// ── Bits ─────────────────────────────────────────────────────────

function Stat({
  label,
  value,
  hint,
}: {
  label: string
  value: string | number
  hint?: string
}) {
  return (
    <div>
      <div className="text-2xs text-fg-muted">{label}</div>
      <div className="mt-0.5 font-mono text-sm font-medium text-fg">
        {value}
      </div>
      {hint && <div className="mt-0.5 text-2xs text-fg-faint">{hint}</div>}
    </div>
  )
}

function Avatar({
  name,
  active,
  size = 'sm',
}: {
  name: string
  active?: boolean
  size?: 'sm' | 'lg'
}) {
  const initial = (name || '?').trim()[0]?.toUpperCase() || '?'
  const sz =
    size === 'lg' ? 'h-12 w-12 text-base' : 'h-8 w-8 text-xs'
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full font-semibold uppercase',
        sz,
        active
          ? 'bg-brand-500 text-white'
          : 'bg-surface-muted text-fg-muted',
      )}
    >
      {initial}
    </span>
  )
}
