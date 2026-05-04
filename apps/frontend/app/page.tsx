'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import {
  Plus,
  ArrowRight,
  FolderKanban,
  FlaskConical,
  Network,
  Activity,
  Brain,
  TrendingUp,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis,
  Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts'
import {
  getDashboardSummary, getMbtiDistribution, getSentimentTimeseries,
  getRecentSims,
} from '@/lib/api/dashboard'
import { useCampaigns, useSims, useGraphs, useHealth } from '@/lib/queries'
import { useAppStore } from '@/stores/app-store'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Skeleton, SkeletonCard } from '@/components/data/skeleton'
import { EmptyState } from '@/components/data/empty-state'
import { ErrorState } from '@/components/data/error-state'
import { formatDate, truncate, cn } from '@/lib/utils'
import type { SimStatus } from '@/lib/types/backend'

export default function DashboardPage() {
  const router = useRouter()
  const app = useAppStore()
  const campaignsQ = useCampaigns()
  const simsQ = useSims()
  const graphsQ = useGraphs()
  const healthQ = useHealth()

  const campaigns = campaignsQ.data || []
  const sims = simsQ.data || []
  const graphs = graphsQ.data || []

  const completedSims = sims.filter((s) => s.status === 'completed').length
  const activeSims = sims.filter((s) =>
    (['running', 'preparing', 'ready'] as SimStatus[]).includes(s.status),
  )
  const totalNodes = graphs.reduce((s, g) => s + (g.nodes || 0), 0)

  // Recent: from app store first, fall back to API order
  const recentCampaigns = (() => {
    const ordered: typeof campaigns = []
    for (const id of app.recentCampaignIds) {
      const c = campaigns.find((x) => x.campaign_id === id)
      if (c) ordered.push(c)
    }
    for (const c of campaigns) {
      if (!ordered.some((x) => x.campaign_id === c.campaign_id)) ordered.push(c)
    }
    return ordered.slice(0, 6)
  })()

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8">
      {/* Header */}
      <div className="mb-8 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-fg">
            Dashboard
          </h1>
          <p className="mt-1 text-sm text-fg-muted">
            Overview of your campaigns, simulations, and active runs.
          </p>
        </div>
        <Button variant="primary" onClick={() => router.push('/campaigns/new')}>
          <Plus size={14} />
          New campaign
        </Button>
      </div>

      {/* Stats row */}
      <div className="mb-8 grid grid-cols-4 gap-3 max-md:grid-cols-2">
        <StatCard
          label="Campaigns"
          icon={FolderKanban}
          value={campaigns.length}
          loading={campaignsQ.isLoading}
        />
        <StatCard
          label="Simulations"
          icon={FlaskConical}
          value={sims.length}
          hint={`${completedSims} completed`}
          loading={simsQ.isLoading}
        />
        <StatCard
          label="KG nodes"
          icon={Network}
          value={totalNodes}
          hint={`${graphs.length} graphs`}
          loading={graphsQ.isLoading}
        />
        <StatCard
          label="Services"
          icon={Activity}
          value={
            healthQ.data?.status === 'ok' ? (
              <span className="inline-flex items-center gap-1.5 text-success-600">
                <span className="h-1.5 w-1.5 rounded-full bg-success-500" />
                Healthy
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 text-danger-600">
                <span className="h-1.5 w-1.5 rounded-full bg-danger-500" />
                Down
              </span>
            )
          }
          hint="Gateway"
          loading={healthQ.isLoading}
        />
      </div>

      {/* Active runs */}
      {activeSims.length > 0 && (
        <section className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-md font-semibold text-fg">In progress</h2>
            <Badge tone="warning" dot>
              {activeSims.length} active
            </Badge>
          </div>
          <Card>
            <ul className="divide-y divide-border">
              {activeSims.slice(0, 5).map((s) => (
                <li
                  key={s.sim_id}
                  className="flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-subtle"
                  onClick={() => router.push(`/campaigns/${s.campaign_id}/sims/${s.sim_id}`)}
                >
                  <SimStatusDot status={s.status} />
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-sm text-fg">{s.sim_id}</div>
                    <div className="text-xs text-fg-muted">
                      {s.campaign_id} · {s.num_agents} agents
                    </div>
                  </div>
                  <Badge tone="warning">{s.status}</Badge>
                  <ArrowRight size={14} className="text-fg-faint" />
                </li>
              ))}
            </ul>
          </Card>
        </section>
      )}

      {/* Recent campaigns */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-md font-semibold text-fg">Recent campaigns</h2>
          <Link
            href="/campaigns"
            className="text-xs text-fg-muted hover:text-fg"
          >
            View all →
          </Link>
        </div>

        {campaignsQ.isLoading ? (
          <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <SkeletonCard key={i} lines={2} />
            ))}
          </div>
        ) : campaignsQ.isError ? (
          <ErrorState
            title="Could not load campaigns"
            description={(campaignsQ.error as Error).message}
            onRetry={() => campaignsQ.refetch()}
          />
        ) : recentCampaigns.length === 0 ? (
          <EmptyState
            icon={FolderKanban}
            title="No campaigns yet"
            description="Upload your first campaign brief to start the pipeline."
            action={
              <Button variant="primary" onClick={() => router.push('/campaigns/new')}>
                <Plus size={14} />
                New campaign
              </Button>
            }
          />
        ) : (
          <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
            {recentCampaigns.map((c) => (
              <Link
                key={c.campaign_id}
                href={`/campaigns/${c.campaign_id}`}
                className="group rounded-lg border border-border bg-surface p-4 shadow-xs transition-all hover:border-border-strong hover:shadow-sm"
              >
                <div className="mb-2 flex items-start gap-2">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-brand-50 text-brand-600">
                    <FolderKanban size={14} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-fg">
                      {truncate(c.name, 32)}
                    </div>
                    <div className="font-mono text-2xs text-fg-faint">
                      {c.campaign_id}
                    </div>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {c.campaign_type && <Badge tone="brand">{c.campaign_type}</Badge>}
                  {c.market && <Badge tone="neutral">{c.market}</Badge>}
                </div>
                <div className="mt-3 flex items-center justify-between text-2xs text-fg-faint">
                  <span>{formatDate(c.created_at)}</span>
                  <span className="opacity-0 transition-opacity group-hover:opacity-100">
                    Open →
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* Phase 7.5: meta.db cross-cutting analytics */}
      <AnalyticsSection />
    </div>
  )
}

// ────────────────────────
// helpers
// ────────────────────────

function StatCard({
  label,
  icon: Icon,
  value,
  hint,
  loading,
}: {
  label: string
  icon: React.ComponentType<{ size?: number; className?: string }>
  value: React.ReactNode
  hint?: string
  loading?: boolean
}) {
  return (
    <Card className="p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-2xs font-medium uppercase tracking-wider text-fg-faint">
          {label}
        </span>
        <Icon size={14} className="text-fg-faint" />
      </div>
      {loading ? (
        <Skeleton className="h-7 w-16" />
      ) : (
        <div className="text-2xl font-semibold tracking-tight text-fg">
          {value}
        </div>
      )}
      {hint && !loading && (
        <div className="mt-0.5 text-xs text-fg-muted">{hint}</div>
      )}
    </Card>
  )
}

function SimStatusDot({ status }: { status: SimStatus }) {
  const cls: Record<SimStatus, string> = {
    running: 'bg-warning-500',
    preparing: 'bg-warning-500',
    ready: 'bg-info-500',
    completed: 'bg-success-500',
    failed: 'bg-danger-500',
    created: 'bg-fg-faint',
  }
  return (
    <span className="relative flex h-2 w-2 shrink-0">
      <span
        className={cn(
          'absolute inset-0 rounded-full animate-ping opacity-60',
          cls[status],
        )}
      />
      <span className={cn('relative h-2 w-2 rounded-full', cls[status])} />
    </span>
  )
}

// ────────────────────────
// Phase 7.5: Analytics section (meta.db backed)
// ────────────────────────

function AnalyticsSection() {
  const router = useRouter()
  const summaryQ = useQuery({
    queryKey: ['dashboard', 'summary'],
    queryFn: getDashboardSummary,
    refetchInterval: 30_000,
  })
  const mbtiQ = useQuery({
    queryKey: ['dashboard', 'mbti'],
    queryFn: () => getMbtiDistribution(),
  })
  const sentiQ = useQuery({
    queryKey: ['dashboard', 'sentiment'],
    queryFn: () => getSentimentTimeseries(),
  })
  const recentQ = useQuery({
    queryKey: ['dashboard', 'recent-sims'],
    queryFn: () => getRecentSims({ days: 7, limit: 10 }),
  })

  const summary = summaryQ.data
  const mbtiData = mbtiQ.data
    ? Object.entries(mbtiQ.data.distribution || {}).map(([mbti, count]) => ({
        mbti, count,
      }))
    : []
  const sentiData = sentiQ.data?.series || []
  const recent = recentQ.data?.sims || []

  if (!summary && summaryQ.isLoading) return null

  return (
    <section className="mt-8">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-md font-semibold text-fg">Analytics</h2>
        <span className="text-xs text-fg-muted">From meta.db (auto-refresh 30s)</span>
      </div>

      {/* DB-backed status breakdown */}
      {summary && (
        <div className="mb-4 grid grid-cols-4 gap-3 max-md:grid-cols-2">
          <Card>
            <CardContent className="pt-4">
              <div className="text-xs text-fg-muted">Campaigns by status</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(summary.campaigns).filter(([k]) => k !== 'total').map(([status, count]) => (
                  <Badge key={status} tone={status === 'ready' ? 'success' : status === 'failed' ? 'danger' : 'neutral'}>
                    {status}: {count as number}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <div className="text-xs text-fg-muted">Sims by status</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(summary.simulations).filter(([k]) => k !== 'total').map(([status, count]) => (
                  <Badge key={status} tone={status === 'completed' ? 'success' : status === 'running' ? 'warning' : status === 'failed' ? 'danger' : 'neutral'}>
                    {status}: {count as number}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <div className="text-xs text-fg-muted">KG totals</div>
              <div className="mt-1 font-mono text-lg text-fg">
                {summary.kg.total_nodes.toLocaleString()}n
                <span className="ml-2 text-fg-faint">/ {summary.kg.total_edges.toLocaleString()}e</span>
              </div>
              <div className="text-2xs text-fg-faint">across all campaigns</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <div className="text-xs text-fg-muted">Avg sentiment</div>
              <div className="mt-1 flex items-baseline gap-1.5 text-sm">
                <span className="text-success-600">+{summary.sentiment_avg.positive.toFixed(1)}</span>
                <span className="text-danger-500">−{summary.sentiment_avg.negative.toFixed(1)}</span>
                <span className="text-fg-muted">={summary.sentiment_avg.neutral.toFixed(1)}</span>
              </div>
              <div className="text-2xs text-fg-faint">{summary.sentiment_avg.samples} samples</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Charts */}
      <div className="mb-4 grid grid-cols-2 gap-3 max-lg:grid-cols-1">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">
              <span className="inline-flex items-center gap-1.5">
                <Brain size={13} className="text-brand-600" />
                MBTI distribution
              </span>
            </CardTitle>
            <CardDescription>Across all simulation agents</CardDescription>
          </CardHeader>
          <CardContent className="h-[220px] pt-2">
            {mbtiQ.isLoading ? (
              <Skeleton className="h-full w-full" />
            ) : mbtiData.length === 0 ? (
              <div className="flex h-full items-center justify-center text-xs text-fg-muted">
                No agent data yet — run a sim first
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={mbtiData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="mbti" fontSize={10} />
                  <YAxis fontSize={10} allowDecimals={false} />
                  <Tooltip wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="count" fill="#7c3aed" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">
              <span className="inline-flex items-center gap-1.5">
                <TrendingUp size={13} className="text-success-600" />
                Sentiment over rounds
              </span>
            </CardTitle>
            <CardDescription>Average across all sims with sentiment data</CardDescription>
          </CardHeader>
          <CardContent className="h-[220px] pt-2">
            {sentiQ.isLoading ? (
              <Skeleton className="h-full w-full" />
            ) : sentiData.length === 0 ? (
              <div className="flex h-full items-center justify-center text-xs text-fg-muted">
                No sentiment data — run analysis on completed sims
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={sentiData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="round" fontSize={10} />
                  <YAxis fontSize={10} />
                  <Tooltip wrapperStyle={{ fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} iconSize={8} />
                  <Line type="monotone" dataKey="positive" stroke="#10b981" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="negative" stroke="#ef4444" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="neutral" stroke="#a1a1aa" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent sims (last 7d) */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Recent simulations (last 7 days)</CardTitle>
          <CardDescription>{recent.length} sims</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {recentQ.isLoading ? (
            <div className="space-y-2 p-3">
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}
            </div>
          ) : recent.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-fg-muted">
              No simulations in the last 7 days.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-surface-subtle text-2xs uppercase text-fg-muted">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Sim</th>
                  <th className="px-4 py-2 text-left font-medium">Campaign</th>
                  <th className="px-4 py-2 text-left font-medium">Status</th>
                  <th className="px-4 py-2 text-right font-medium">Agents</th>
                  <th className="px-4 py-2 text-right font-medium">Round</th>
                  <th className="px-4 py-2 text-right font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {recent.map((s) => (
                  <tr
                    key={s.sid}
                    className="cursor-pointer hover:bg-surface-subtle"
                    onClick={() => router.push(`/campaigns/${s.cid}/sims/${s.sid}`)}
                  >
                    <td className="px-4 py-2 font-mono text-xs text-fg">{s.sid}</td>
                    <td className="px-4 py-2 text-xs text-fg-muted">
                      {truncate(s.campaign_name || s.cid, 40)}
                    </td>
                    <td className="px-4 py-2">
                      <Badge tone={
                        s.status === 'completed' ? 'success' :
                        s.status === 'running' ? 'warning' :
                        s.status === 'failed' ? 'danger' : 'neutral'
                      } dot>{s.status}</Badge>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">{s.num_agents ?? '—'}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {s.current_round ?? 0}/{s.num_rounds ?? '?'}
                    </td>
                    <td className="px-4 py-2 text-right text-xs text-fg-faint">
                      {formatDate(s.created_at || '')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </section>
  )
}
