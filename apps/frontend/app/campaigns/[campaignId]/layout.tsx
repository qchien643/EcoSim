'use client'

import { use, useEffect } from 'react'
import { Tabs, type TabItem } from '@/components/ui/tabs'
import { useCampaignSpec } from '@/lib/queries'
import { useAppStore } from '@/stores/app-store'
import { Skeleton } from '@/components/data/skeleton'
import { Badge } from '@/components/ui/badge'

/**
 * Workspace shell for a single campaign — sticky tabs strip + slot.
 * Pushes the campaign onto recent list when this layout mounts.
 */
export default function CampaignWorkspaceLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: Promise<{ campaignId: string }>
}) {
  const { campaignId } = use(params)
  const app = useAppStore()
  const specQ = useCampaignSpec(campaignId)

  useEffect(() => {
    if (campaignId) app.pushRecentCampaign(campaignId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignId])

  const base = `/campaigns/${campaignId}`
  const tabs: TabItem[] = [
    { label: 'Overview', href: base, match: 'exact' },
    { label: 'Spec', href: `${base}/spec` },
    { label: 'Knowledge graph', href: `${base}/graph` },
    { label: 'Simulations', href: `${base}/sims` },
  ]

  return (
    <div className="flex flex-col">
      {/* Header strip */}
      <div className="border-b border-border bg-surface px-6 pt-6">
        <div className="mx-auto w-full max-w-6xl">
          <div className="mb-3 flex items-end justify-between gap-4">
            <div className="min-w-0">
              {specQ.isLoading ? (
                <Skeleton className="h-7 w-64" />
              ) : specQ.data ? (
                <h1 className="truncate text-xl font-semibold tracking-tight text-fg">
                  {specQ.data.name}
                </h1>
              ) : (
                <h1 className="font-mono text-xl font-semibold text-fg">
                  {campaignId}
                </h1>
              )}
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-fg-muted">
                <span className="font-mono">{campaignId}</span>
                {specQ.data?.campaign_type && (
                  <>
                    <span className="text-fg-faint">·</span>
                    <Badge tone="brand">{specQ.data.campaign_type}</Badge>
                  </>
                )}
                {specQ.data?.market && (
                  <>
                    <span className="text-fg-faint">·</span>
                    <Badge tone="neutral">{specQ.data.market}</Badge>
                  </>
                )}
              </div>
            </div>
          </div>

          <Tabs items={tabs} />
        </div>
      </div>

      <div className="mx-auto w-full max-w-6xl px-6 py-6">{children}</div>
    </div>
  )
}
