'use client'

import { use } from 'react'
import { useCampaignSpec } from '@/lib/queries'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/data/skeleton'
import { ErrorState } from '@/components/data/error-state'
import { Badge } from '@/components/ui/badge'

export default function SpecPage({
  params,
}: {
  params: Promise<{ campaignId: string }>
}) {
  const { campaignId } = use(params)
  const specQ = useCampaignSpec(campaignId)

  if (specQ.isError) {
    return (
      <ErrorState
        title="Could not load spec"
        description={(specQ.error as Error).message}
        onRetry={() => specQ.refetch()}
      />
    )
  }

  const spec = specQ.data

  return (
    <div className="grid grid-cols-3 gap-6 max-lg:grid-cols-1">
      {/* Description */}
      <div className="col-span-2 max-lg:col-span-1">
        <Card>
          <CardHeader>
            <CardTitle>Spec</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {specQ.isLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-11/12" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            ) : (
              <>
                <Field label="Name" value={spec?.name} />
                <Field
                  label="Type"
                  value={
                    spec?.campaign_type ? (
                      <Badge tone="brand">{spec.campaign_type}</Badge>
                    ) : null
                  }
                />
                <Field
                  label="Market"
                  value={
                    spec?.market ? (
                      <Badge tone="neutral">{spec.market}</Badge>
                    ) : null
                  }
                />
                <Field
                  label="Description"
                  value={
                    spec?.description ? (
                      <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">
                        {spec.description}
                      </p>
                    ) : null
                  }
                />
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Lists */}
      <div className="space-y-3">
        <ListBlock title="KPIs" items={spec?.kpis} />
        <ListBlock title="Stakeholders" items={spec?.stakeholders} />
        <ListBlock title="Risks" items={spec?.risks} />
      </div>
    </div>
  )
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-fg-faint">
        {label}
      </div>
      <div className="text-sm text-fg">
        {value || <span className="text-fg-faint">—</span>}
      </div>
    </div>
  )
}

function ListBlock({ title, items }: { title: string; items?: string[] }) {
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
        {!items?.length ? (
          <p className="text-xs text-fg-faint">None.</p>
        ) : (
          <ul className="space-y-1.5 text-sm text-fg">
            {items.map((it, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-fg-faint" />
                <span className="leading-snug">{it}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
