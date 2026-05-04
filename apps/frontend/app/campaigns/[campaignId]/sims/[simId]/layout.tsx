'use client'

import { use } from 'react'
import { Tabs, type TabItem } from '@/components/ui/tabs'
import { useSim } from '@/lib/queries'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/data/skeleton'
import type { SimStatus } from '@/lib/types/backend'

const TONE: Record<SimStatus, 'success' | 'warning' | 'danger' | 'info' | 'neutral'> = {
  completed: 'success',
  running: 'warning',
  preparing: 'warning',
  ready: 'info',
  failed: 'danger',
  created: 'neutral',
}

export default function SimWorkspaceLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: Promise<{ campaignId: string; simId: string }>
}) {
  const { campaignId, simId } = use(params)
  const simQ = useSim(simId)

  const base = `/campaigns/${campaignId}/sims/${simId}`
  const tabs: TabItem[] = [
    { label: 'Run', href: base, match: 'exact' },
    { label: 'Agents', href: `${base}/agents` },
    { label: 'Tracing', href: `${base}/tracing` },
    { label: 'Graph', href: `${base}/graph` },
    { label: 'Analysis', href: `${base}/analysis` },
    { label: 'Report', href: `${base}/report` },
    { label: 'Survey', href: `${base}/survey` },
    { label: 'Interview', href: `${base}/interview` },
  ]

  return (
    <div className="-mx-6 -my-6 flex flex-col">
      <div className="border-b border-border bg-surface-subtle px-6 pt-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {simQ.isLoading ? (
            <Skeleton className="h-5 w-48" />
          ) : simQ.data ? (
            <>
              <span className="font-mono text-sm font-medium text-fg">
                {simQ.data.sim_id}
              </span>
              <Badge tone={TONE[simQ.data.status]} dot>
                {simQ.data.status}
              </Badge>
              <span className="text-xs text-fg-muted">·</span>
              <span className="text-xs text-fg-muted">
                {simQ.data.num_agents} agents
                {simQ.data.num_rounds ? ` · ${simQ.data.num_rounds} rounds` : ''}
              </span>
            </>
          ) : (
            <span className="font-mono text-sm font-medium text-fg">{simId}</span>
          )}
        </div>
        <Tabs items={tabs} />
      </div>

      <div className="px-6 py-6">{children}</div>
    </div>
  )
}
