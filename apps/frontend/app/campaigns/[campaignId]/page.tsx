'use client'

import { use } from 'react'
import Link from 'next/link'
import {
  FileText,
  Network,
  FlaskConical,
  ArrowRight,
  Calendar,
} from 'lucide-react'
import { useCampaignSpec, useSims, useGraphs } from '@/lib/queries'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/data/skeleton'
import { ErrorState } from '@/components/data/error-state'
import { formatDate, truncate } from '@/lib/utils'
import type { SimStatus } from '@/lib/types/backend'

export default function CampaignOverviewPage({
  params,
}: {
  params: Promise<{ campaignId: string }>
}) {
  const { campaignId } = use(params)
  const specQ = useCampaignSpec(campaignId)
  const simsQ = useSims()
  const graphsQ = useGraphs()

  const sims = (simsQ.data || []).filter((s) => s.campaign_id === campaignId)
  const lastSim = sims[0]

  // Heuristic: a graph "belongs" to this campaign if its name contains the id.
  const graph = (graphsQ.data || []).find((g) => g.name.includes(campaignId))

  if (specQ.isError) {
    return (
      <ErrorState
        title="Could not load campaign"
        description={(specQ.error as Error).message}
        onRetry={() => specQ.refetch()}
      />
    )
  }

  const spec = specQ.data

  return (
    <div className="grid grid-cols-3 gap-6 max-lg:grid-cols-1">
      {/* Main column */}
      <div className="col-span-2 flex flex-col gap-6 max-lg:col-span-1">
        {/* Description card */}
        <Card>
          <CardHeader>
            <CardTitle>About</CardTitle>
            <CardDescription>
              LLM-extracted summary from the original brief.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {specQ.isLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-11/12" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            ) : spec?.description ? (
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">
                {spec.description}
              </p>
            ) : (
              <p className="text-sm text-fg-faint">No description provided.</p>
            )}
          </CardContent>
        </Card>

        {/* KPIs / Stakeholders / Risks */}
        <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
          <ListCard
            title="KPIs"
            items={spec?.kpis}
            loading={specQ.isLoading}
            emptyHint="None defined."
          />
          <ListCard
            title="Stakeholders"
            items={spec?.stakeholders}
            loading={specQ.isLoading}
            emptyHint="None defined."
          />
          <ListCard
            title="Risks"
            items={spec?.risks}
            loading={specQ.isLoading}
            emptyHint="None defined."
          />
        </div>
      </div>

      {/* Side column */}
      <div className="flex flex-col gap-3">
        {/* Pipeline status */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Pipeline</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            <PipelineRow
              icon={FileText}
              label="Spec parsed"
              status={spec ? 'done' : specQ.isLoading ? 'pending' : 'pending'}
              href={`/campaigns/${campaignId}/spec`}
            />
            <PipelineRow
              icon={Network}
              label="Knowledge graph"
              status={graph ? 'done' : 'pending'}
              detail={graph ? `${graph.nodes} nodes, ${graph.edges} edges` : undefined}
              href={`/campaigns/${campaignId}/graph`}
            />
            <PipelineRow
              icon={FlaskConical}
              label="Simulations"
              status={sims.length > 0 ? 'done' : 'pending'}
              detail={
                sims.length > 0
                  ? `${sims.length} run${sims.length === 1 ? '' : 's'}`
                  : undefined
              }
              href={`/campaigns/${campaignId}/sims`}
            />
          </CardContent>
        </Card>

        {/* Quick info */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <DetailRow
              icon={Calendar}
              label="Created"
              value={spec?.created_at ? formatDate(spec.created_at) : '—'}
            />
            <DetailRow
              icon={Network}
              label="Type"
              value={
                spec?.campaign_type ? (
                  <Badge tone="brand">{spec.campaign_type}</Badge>
                ) : (
                  '—'
                )
              }
            />
            <DetailRow
              icon={FlaskConical}
              label="Market"
              value={
                spec?.market ? (
                  <Badge tone="neutral">{spec.market}</Badge>
                ) : (
                  '—'
                )
              }
            />
          </CardContent>
        </Card>

        {lastSim && (
          <Link
            href={`/campaigns/${campaignId}/sims/${lastSim.sim_id}`}
            className="group rounded-lg border border-border bg-surface-subtle p-3 transition-colors hover:bg-surface-muted"
          >
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-2xs font-medium uppercase tracking-wider text-fg-faint">
                Latest sim
              </span>
              <ArrowRight size={12} className="text-fg-faint transition-transform group-hover:translate-x-0.5" />
            </div>
            <div className="font-mono text-sm font-medium text-fg">
              {truncate(lastSim.sim_id, 22)}
            </div>
            <div className="mt-1 flex items-center gap-2 text-xs text-fg-muted">
              <SimStatusBadge status={lastSim.status} />
              <span>·</span>
              <span>{lastSim.num_agents} agents</span>
            </div>
          </Link>
        )}
      </div>
    </div>
  )
}

function ListCard({
  title,
  items,
  loading,
  emptyHint,
}: {
  title: string
  items?: string[]
  loading?: boolean
  emptyHint: string
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          {title}
          {items && items.length > 0 && (
            <span className="ml-1.5 text-xs font-normal text-fg-faint">
              {items.length}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        ) : !items?.length ? (
          <p className="text-xs text-fg-faint">{emptyHint}</p>
        ) : (
          <ul className="space-y-1.5 text-sm text-fg">
            {items.slice(0, 6).map((it, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-fg-faint" />
                <span className="leading-snug">{it}</span>
              </li>
            ))}
            {items.length > 6 && (
              <li className="pt-1 text-2xs text-fg-faint">
                + {items.length - 6} more
              </li>
            )}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function PipelineRow({
  icon: Icon,
  label,
  status,
  detail,
  href,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>
  label: string
  status: 'done' | 'pending'
  detail?: string
  href: string
}) {
  return (
    <Link
      href={href}
      className="group flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-surface-muted"
    >
      <span
        className={
          status === 'done'
            ? 'flex h-6 w-6 items-center justify-center rounded-full bg-success-50 text-success-600'
            : 'flex h-6 w-6 items-center justify-center rounded-full bg-surface-muted text-fg-faint'
        }
      >
        <Icon size={12} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-fg">{label}</div>
        {detail && (
          <div className="truncate text-2xs text-fg-faint">{detail}</div>
        )}
      </div>
      <ArrowRight
        size={12}
        className="text-fg-faint opacity-0 transition-opacity group-hover:opacity-100"
      />
    </Link>
  )
}

function DetailRow({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>
  label: string
  value: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="inline-flex items-center gap-1.5 text-fg-muted">
        <Icon size={12} className="text-fg-faint" />
        {label}
      </span>
      <span className="text-fg">{value}</span>
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
          : 'neutral'
  return (
    <Badge tone={tone as 'success' | 'warning' | 'danger' | 'neutral'} dot>
      {status}
    </Badge>
  )
}
