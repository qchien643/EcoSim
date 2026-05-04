'use client'

import { use } from 'react'
import {
  Brain,
  Sparkles,
  ThumbsUp,
  ThumbsDown,
} from 'lucide-react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
  Cell,
} from 'recharts'
import { useAnalysis, useRunAnalysis } from '@/lib/queries'
import { useUiStore } from '@/stores/ui-store'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/data/skeleton'
import { ErrorState } from '@/components/data/error-state'
import { EmptyState } from '@/components/data/empty-state'
import { truncate } from '@/lib/utils'
import type { SentimentExcerpt } from '@/lib/types/backend'

const COLORS = {
  positive: '#10b981',
  neutral: '#a1a1aa',
  negative: '#ef4444',
}

export default function SimAnalysisPage({
  params,
}: {
  params: Promise<{ campaignId: string; simId: string }>
}) {
  const { simId } = use(params)
  const ui = useUiStore()
  const analysisQ = useAnalysis(simId)
  const runM = useRunAnalysis()

  const data = analysisQ.data
  const perRound = data?.per_round || []

  async function onRun() {
    try {
      await runM.mutateAsync({ simId })
      ui.success('Analysis updated.', 2500)
    } catch (e) {
      ui.error('Run failed: ' + (e as Error).message)
    }
  }

  if (analysisQ.isError) {
    return (
      <ErrorState
        title="Could not load analysis"
        description={(analysisQ.error as Error).message}
        onRetry={() => analysisQ.refetch()}
      />
    )
  }

  if (!analysisQ.isLoading && !data) {
    return (
      <EmptyState
        icon={Brain}
        title="No sentiment results yet"
        description="Run sentiment analysis on this sim's comment feed. Uses local RoBERTa — no LLM cost."
        action={
          <Button variant="primary" loading={runM.isPending} onClick={onRun}>
            <Sparkles size={13} />
            Run analysis
          </Button>
        }
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header strip */}
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 className="text-md font-semibold text-fg">Sentiment</h2>
          {data?.totals && (
            <p className="mt-0.5 text-xs text-fg-muted">
              <span className="font-mono text-success-600">
                +{data.totals.positive}
              </span>{' '}
              <span className="font-mono text-fg-faint">
                ={data.totals.neutral}
              </span>{' '}
              <span className="font-mono text-danger-600">
                −{data.totals.negative}
              </span>{' '}
              across all rounds
            </p>
          )}
        </div>
        <Button variant="secondary" size="sm" loading={runM.isPending} onClick={onRun}>
          <Sparkles size={13} />
          Re-run
        </Button>
      </div>

      {/* Per-round chart */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Per-round distribution</CardTitle>
        </CardHeader>
        <CardContent className="pt-2">
          {analysisQ.isLoading ? (
            <Skeleton className="h-[280px] w-full" />
          ) : perRound.length === 0 ? (
            <p className="py-8 text-center text-xs text-fg-muted">
              No per-round data.
            </p>
          ) : (
            <div className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={perRound} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" vertical={false} />
                  <XAxis
                    dataKey="round"
                    tick={{ fontSize: 11, fill: '#71717a' }}
                    tickLine={false}
                    axisLine={{ stroke: '#e4e4e7' }}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: '#71717a' }}
                    tickLine={false}
                    axisLine={false}
                    width={32}
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#ffffff',
                      border: '1px solid #e4e4e7',
                      borderRadius: 6,
                      fontSize: 12,
                      boxShadow: '0 4px 8px -2px rgba(0,0,0,.08)',
                    }}
                    cursor={{ fill: 'rgba(124, 58, 237, 0.06)' }}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                    iconType="circle"
                    iconSize={8}
                  />
                  <Bar dataKey="positive" stackId="s" fill={COLORS.positive} radius={[0, 0, 0, 0]} />
                  <Bar dataKey="neutral" stackId="s" fill={COLORS.neutral} />
                  <Bar dataKey="negative" stackId="s" fill={COLORS.negative} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Top excerpts side by side */}
      <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
        <ExcerptList
          icon={ThumbsUp}
          title="Top positive"
          items={data?.top_positive}
          tone="success"
          loading={analysisQ.isLoading}
        />
        <ExcerptList
          icon={ThumbsDown}
          title="Top negative"
          items={data?.top_negative}
          tone="danger"
          loading={analysisQ.isLoading}
        />
      </div>
    </div>
  )
}

function ExcerptList({
  icon: Icon,
  title,
  items,
  tone,
  loading,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>
  title: string
  items?: SentimentExcerpt[]
  tone: 'success' | 'danger'
  loading?: boolean
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          <span
            className={
              'inline-flex items-center gap-1.5 ' +
              (tone === 'success' ? 'text-success-700' : 'text-danger-600')
            }
          >
            <Icon size={13} />
            {title}
            {items && (
              <span className="text-xs font-normal text-fg-faint">
                {items.length}
              </span>
            )}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : !items?.length ? (
          <p className="text-xs text-fg-muted">No excerpts.</p>
        ) : (
          <ul className="space-y-2.5">
            {items.slice(0, 5).map((it, i) => (
              <li
                key={it.comment_id ?? i}
                className="rounded-md border border-border bg-surface-subtle p-2.5 text-sm"
              >
                <p className="leading-snug text-fg">{truncate(it.content, 200)}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-2xs text-fg-faint">
                  {it.agent && <span>by {it.agent}</span>}
                  {it.round != null && (
                    <Badge tone="neutral">R{it.round}</Badge>
                  )}
                  {it.score != null && (
                    <span className="font-mono">
                      {it.score >= 0 ? '+' : ''}
                      {it.score.toFixed(2)}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
