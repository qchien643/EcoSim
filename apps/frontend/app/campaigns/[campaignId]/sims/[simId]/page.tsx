'use client'

import { use, useEffect, useState } from 'react'
import {
  Play,
  AlertTriangle,
  MessageSquare,
  Heart,
  Newspaper,
} from 'lucide-react'
import {
  useSim,
  useSimProgress,
  useSimActions,
  useSimFeed,
  useStartSim,
  useCrisisLog,
} from '@/lib/queries'
import { simStreamUrl } from '@/lib/api/sim'
import { useSse } from '@/hooks/use-sse'
import { useUiStore } from '@/stores/ui-store'
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/data/skeleton'
import { ErrorState } from '@/components/data/error-state'
import { EmptyState } from '@/components/data/empty-state'
import { cn, formatDate } from '@/lib/utils'
import type { SimAction, SimStatus } from '@/lib/types/backend'
import type { FeedPost } from '@/lib/api/sim'


export default function SimRunPage({
  params,
}: {
  params: Promise<{ campaignId: string; simId: string }>
}) {
  const { simId } = use(params)
  const ui = useUiStore()
  const simQ = useSim(simId)
  const progressQ = useSimProgress(simId)
  const actionsQ = useSimActions(simId)
  const startM = useStartSim()

  const status = simQ.data?.status
  const isRunning = status === 'running' || status === 'preparing'

  // Crisis fires mid-round → poll while sim is running so the "x/y triggered"
  // badge updates as soon as run_simulation writes the new count to meta.db.
  const crisisQ = useCrisisLog(simId, { polling: isRunning })

  // Phase 11: social media feed (posts + comments + likes) từ FalkorDB sim graph
  const feedQ = useSimFeed(simId, { polling: isRunning })

  // Phase 11: SSE only counts new actions for "Live" indicator —
  // feed itself comes from /api/sim/{sid}/feed (FalkorDB).
  const [liveActionCount, setLiveActionCount] = useState(0)

  useSse<{ actions?: SimAction[] }>(
    isRunning ? simStreamUrl(simId) : null,
    (data) => {
      if (Array.isArray(data?.actions) && data.actions.length) {
        setLiveActionCount((n) => n + data.actions!.length)
      }
    },
  )

  useEffect(() => {
    setLiveActionCount(0)
  }, [simId, isRunning])

  if (simQ.isError) {
    return (
      <ErrorState
        title="Could not load sim"
        description={(simQ.error as Error).message}
        onRetry={() => simQ.refetch()}
      />
    )
  }

  const sim = simQ.data
  const progress = progressQ.data
  const recentActionsCount =
    liveActionCount > 0 ? liveActionCount : actionsQ.data?.length || 0

  const pct =
    progress && progress.total_rounds > 0
      ? Math.min(100, Math.round((progress.current_round / progress.total_rounds) * 100))
      : 0

  return (
    <div className="grid grid-cols-3 gap-6 max-lg:grid-cols-1">
      {/* Main column — progress + feed */}
      <div className="col-span-2 flex flex-col gap-4 max-lg:col-span-1">
        {/* Progress card */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-end justify-between gap-3">
              <div>
                <CardTitle className="text-sm">
                  Round {progress?.current_round ?? 0}{' '}
                  <span className="font-normal text-fg-muted">
                    / {progress?.total_rounds ?? sim?.num_rounds ?? '?'}
                  </span>
                </CardTitle>
                <p className="mt-0.5 text-xs text-fg-muted">
                  {statusBlurb(status)}
                </p>
              </div>
              {status === 'ready' && (
                <Button
                  variant="primary"
                  size="sm"
                  loading={startM.isPending}
                  onClick={async () => {
                    try {
                      await startM.mutateAsync(simId)
                      ui.success('Started.', 2500)
                    } catch (e) {
                      ui.error('Start failed: ' + (e as Error).message)
                    }
                  }}
                >
                  <Play size={13} />
                  Start run
                </Button>
              )}
              {isRunning && (
                <span className="inline-flex items-center gap-1.5 text-xs text-warning-600">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inset-0 rounded-full animate-ping bg-warning-500 opacity-60" />
                    <span className="relative h-2 w-2 rounded-full bg-warning-500" />
                  </span>
                  Live
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-muted">
              <div
                className={cn(
                  'h-full rounded-full transition-all duration-500',
                  status === 'completed'
                    ? 'bg-success-500'
                    : status === 'failed'
                      ? 'bg-danger-500'
                      : 'bg-brand-500',
                )}
                style={{ width: `${status === 'completed' ? 100 : pct}%` }}
              />
            </div>
            <div className="mt-1.5 flex items-center justify-between text-2xs text-fg-faint">
              <span>{pct}% complete</span>
              <span>{recentActionsCount} recent action{recentActionsCount === 1 ? '' : 's'}</span>
            </div>
          </CardContent>
        </Card>

        {/* Phase 11: Social feed — posts từ FalkorDB sim graph */}
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">
                <span className="inline-flex items-center gap-1.5">
                  <Newspaper size={13} className="text-fg-muted" />
                  Feed
                  {feedQ.data && feedQ.data.length > 0 && (
                    <span className="text-2xs font-normal text-fg-faint">
                      {feedQ.data.length} post{feedQ.data.length === 1 ? '' : 's'}
                    </span>
                  )}
                </span>
              </CardTitle>
              {feedQ.data && feedQ.data.length > 0 && (
                <span className="text-2xs text-fg-faint">
                  {feedQ.data.reduce((s, p) => s + p.likes_count, 0)} likes ·{' '}
                  {feedQ.data.reduce((s, p) => s + p.comments_count, 0)} comments
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {feedQ.isLoading && !feedQ.data ? (
              <div className="space-y-3 p-4">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-24 w-full" />
                ))}
              </div>
            ) : !feedQ.data || feedQ.data.length === 0 ? (
              <EmptyState
                icon={Newspaper}
                title="Chưa có bài viết"
                description={
                  isRunning
                    ? 'Đợi agent đăng bài đầu tiên…'
                    : 'Start sim để xem feed.'
                }
                className="border-0 bg-transparent py-8"
              />
            ) : (
              <div className="max-h-[640px] overflow-y-auto divide-y divide-border-subtle">
                {feedQ.data.map((post) => (
                  <FeedPostCard key={post.post_id} post={post} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Side column — sim details + crisis */}
      <div className="flex flex-col gap-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Run details</CardTitle>
          </CardHeader>
          <CardContent>
            {simQ.isLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-3 w-3/4" />
                <Skeleton className="h-3 w-1/2" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            ) : sim ? (
              <div className="space-y-2 text-sm">
                <Row label="Sim ID">
                  <span className="font-mono text-xs text-fg">{sim.sim_id}</span>
                </Row>
                <Row label="Group">
                  <span className="font-mono text-xs text-fg">
                    {sim.group_id || '—'}
                  </span>
                </Row>
                <Row label="Status">
                  <SimStatusBadge status={sim.status} />
                </Row>
                <Row label="Agents">{sim.num_agents}</Row>
                <Row label="Rounds">{sim.num_rounds || '—'}</Row>
                <Row label="Created">{formatDate(sim.created_at)}</Row>
              </div>
            ) : (
              <p className="text-xs text-fg-muted">Not found.</p>
            )}
          </CardContent>
        </Card>

        {/* Crisis events */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">
              <span className="inline-flex items-center gap-1.5">
                <AlertTriangle size={13} className="text-warning-600" />
                Crisis events
                {crisisQ.data && crisisQ.data.crisis_count > 0 && (
                  <span className="text-xs font-normal text-fg-faint">
                    {crisisQ.data.crisis_triggered_count}/
                    {crisisQ.data.crisis_count} triggered
                  </span>
                )}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {crisisQ.isLoading ? (
              <Skeleton className="h-6 w-full" />
            ) : !crisisQ.data?.crises?.length ? (
              <p className="text-xs text-fg-muted">
                {crisisQ.data && crisisQ.data.crisis_count > 0
                  ? 'Đã lên lịch nhưng chưa crisis nào trigger.'
                  : 'Không có khủng hoảng nào.'}
              </p>
            ) : (
              <ul className="space-y-3">
                {crisisQ.data.crises.map((c, i) => (
                  <li
                    key={c.crisis_id || i}
                    className="rounded-md border border-border bg-warning-50 p-3 text-xs"
                  >
                    {/* Header: title + status badges */}
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 font-medium text-fg">
                        {c.title || 'Crisis'}
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <Badge tone="warning">
                          {c.triggered ? `R${c.triggered_round}` : `→R${c.trigger_round}`}
                        </Badge>
                        <span
                          className={cn(
                            'rounded px-1.5 py-0.5 text-2xs font-medium',
                            c.triggered
                              ? 'bg-brand-100 text-brand-700'
                              : 'bg-surface text-fg-muted',
                          )}
                        >
                          {c.triggered ? 'đã trigger' : 'chờ trigger'}
                        </span>
                      </div>
                    </div>

                    {/* Description */}
                    {c.description && (
                      <p className="mt-2 text-xs text-fg">
                        {c.description}
                      </p>
                    )}

                    {/* Meta row: type · severity · sentiment */}
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-2xs">
                      <span className="rounded bg-surface px-1.5 py-0.5 font-mono text-fg-muted">
                        {c.crisis_type}
                      </span>
                      <span className="rounded bg-surface px-1.5 py-0.5 font-mono text-fg-muted">
                        severity {c.severity.toFixed(2)}
                      </span>
                      <span
                        className={cn(
                          'rounded px-1.5 py-0.5 font-mono',
                          c.sentiment_shift === 'negative'
                            ? 'bg-danger-50 text-danger-600'
                            : c.sentiment_shift === 'positive'
                              ? 'bg-brand-100 text-brand-700'
                              : 'bg-surface text-fg-muted',
                        )}
                      >
                        {c.sentiment_shift}
                      </span>
                      <span className="rounded bg-surface px-1.5 py-0.5 text-fg-muted">
                        kéo dài {c.persist_rounds} round · phai ×
                        {c.intensity_decay.toFixed(2)}
                      </span>
                    </div>

                    {/* Affected domains */}
                    {c.affected_domains.length > 0 && (
                      <div className="mt-2">
                        <div className="text-2xs text-fg-faint">
                          Lĩnh vực ảnh hưởng
                        </div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {c.affected_domains.map((d, idx) => (
                            <span
                              key={idx}
                              className="rounded bg-surface px-1.5 py-0.5 text-2xs text-fg"
                            >
                              {d}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Interest keywords */}
                    {c.interest_keywords.length > 0 && (
                      <div className="mt-2">
                        <div className="text-2xs text-fg-faint">
                          Từ khoá inject vào hứng thú agent
                        </div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {c.interest_keywords.map((k, idx) => (
                            <span
                              key={idx}
                              className="rounded bg-brand-100 px-1.5 py-0.5 text-2xs text-brand-700"
                            >
                              {k}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Severity decay forecast (per-round intensity) */}
                    <div className="mt-2 border-t border-border/60 pt-2">
                      <div className="text-2xs text-fg-faint">
                        Cường độ theo round trong cửa sổ persist
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {Array.from({
                          length: Math.max(1, c.persist_rounds),
                        }).map((_, age) => {
                          const sev = c.severity * Math.pow(c.intensity_decay, age)
                          const round = c.trigger_round + age
                          const bucket =
                            sev >= 0.3 ? 'mạnh' : sev >= 0.15 ? 'vừa' : 'yếu'
                          const tone =
                            sev >= 0.3
                              ? 'bg-brand-100 text-brand-700'
                              : sev >= 0.15
                                ? 'bg-warning-50 text-warning-600'
                                : 'bg-surface text-fg-faint'
                          return (
                            <span
                              key={age}
                              className={cn(
                                'rounded px-1.5 py-0.5 font-mono text-2xs',
                                tone,
                              )}
                              title={`Round ${round} (age ${age}): ${bucket}`}
                            >
                              R{round}: {sev.toFixed(2)} ({bucket})
                            </span>
                          )
                        })}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function statusBlurb(status: SimStatus | undefined): string {
  switch (status) {
    case 'completed': return 'Run completed.'
    case 'running':   return 'Streaming via SSE.'
    case 'preparing': return 'Spawning subprocess…'
    case 'ready':     return 'Ready to launch.'
    case 'failed':    return 'Run failed.'
    case 'created':   return 'Created — preparing.'
    default:          return 'Waiting…'
  }
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-fg-muted">{label}</span>
      <span className="text-fg">{children}</span>
    </div>
  )
}

function SimStatusBadge({ status }: { status: SimStatus }) {
  const tone =
    status === 'completed'
      ? 'success'
      : status === 'running' || status === 'preparing'
        ? 'warning'
        : status === 'failed'
          ? 'danger'
          : status === 'ready'
            ? 'info'
            : 'neutral'
  return (
    <Badge tone={tone as 'success' | 'warning' | 'danger' | 'info' | 'neutral'} dot>
      {status}
    </Badge>
  )
}

// Phase 11: social media feed card (post + likes + comments)
function FeedPostCard({ post }: { post: FeedPost }) {
  const [showComments, setShowComments] = useState(false)
  return (
    <article className="px-4 py-3">
      {/* Author header */}
      <header className="flex items-start gap-2.5">
        <Avatar name={post.author.name} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-1.5 flex-wrap">
            <span className="text-sm font-medium text-fg">
              {post.author.name}
            </span>
            {post.author.mbti && (
              <span className="font-mono text-[10px] text-fg-faint">
                · {post.author.mbti}
              </span>
            )}
            <span className="font-mono text-2xs text-fg-faint">
              · R{post.round}
            </span>
            <span className="font-mono text-2xs text-fg-faint">
              · #{post.post_id}
            </span>
          </div>
          <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-fg">
            {post.content}
          </p>
        </div>
      </header>

      {/* Reaction bar */}
      <div className="mt-2.5 flex items-center gap-4 pl-10 text-xs text-fg-muted">
        <span className="inline-flex items-center gap-1">
          <Heart size={12} className="text-danger-500" />
          <span>{post.likes_count}</span>
          {post.likes.length > 0 && (
            <span className="ml-1 text-2xs text-fg-faint">
              {post.likes.slice(0, 3).map((l) => l.name).join(', ')}
              {post.likes.length > 3 && ` +${post.likes.length - 3}`}
            </span>
          )}
        </span>
        <button
          onClick={() => setShowComments((s) => !s)}
          className="inline-flex items-center gap-1 hover:text-fg transition-colors"
          disabled={post.comments_count === 0}
        >
          <MessageSquare size={12} className="text-brand-500" />
          <span>
            {post.comments_count} comment{post.comments_count === 1 ? '' : 's'}
          </span>
        </button>
      </div>

      {/* Comments */}
      {showComments && post.comments.length > 0 && (
        <div className="mt-3 space-y-2 border-l-2 border-border-subtle pl-3 ml-10">
          {post.comments.map((c) => (
            <div key={c.comment_id} className="flex items-start gap-2">
              <Avatar name={c.author.name} small />
              <div className="min-w-0 flex-1 rounded-lg bg-surface-subtle px-3 py-1.5">
                <div className="flex items-baseline gap-1.5 flex-wrap">
                  <span className="text-xs font-medium text-fg">
                    {c.author.name}
                  </span>
                  {c.author.mbti && (
                    <span className="font-mono text-[10px] text-fg-faint">
                      · {c.author.mbti}
                    </span>
                  )}
                  <span className="font-mono text-2xs text-fg-faint">
                    · R{c.round}
                  </span>
                </div>
                <p className="mt-0.5 whitespace-pre-wrap text-xs leading-relaxed text-fg-muted">
                  {c.content}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </article>
  )
}

// Avatar — first letter of name with stable color
function Avatar({ name, small = false }: { name: string; small?: boolean }) {
  const letter = (name || '?').trim().charAt(0).toUpperCase() || '?'
  // Stable color hash from name
  const colors = [
    'bg-rose-100 text-rose-700',
    'bg-amber-100 text-amber-700',
    'bg-emerald-100 text-emerald-700',
    'bg-sky-100 text-sky-700',
    'bg-violet-100 text-violet-700',
    'bg-fuchsia-100 text-fuchsia-700',
    'bg-teal-100 text-teal-700',
    'bg-orange-100 text-orange-700',
  ]
  const hash = Array.from(name).reduce((h, c) => h + c.charCodeAt(0), 0) % colors.length
  const size = small ? 'h-6 w-6 text-2xs' : 'h-8 w-8 text-xs'
  return (
    <span
      className={cn(
        'shrink-0 inline-flex items-center justify-center rounded-full font-semibold',
        size,
        colors[hash],
      )}
    >
      {letter}
    </span>
  )
}
