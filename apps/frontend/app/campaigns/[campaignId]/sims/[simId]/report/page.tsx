'use client'

import { use, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  BarChart3,
  Sparkles,
  FileText,
  Loader2,
  ChevronRight,
} from 'lucide-react'
import {
  useReport,
  useReportProgress,
  useReportOutline,
  useReportSection,
  useGenerateReport,
} from '@/lib/queries'
import { useUiStore } from '@/stores/ui-store'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/data/skeleton'
import { ErrorState } from '@/components/data/error-state'
import { EmptyState } from '@/components/data/empty-state'
import { cn } from '@/lib/utils'

export default function SimReportPage({
  params,
}: {
  params: Promise<{ campaignId: string; simId: string }>
}) {
  const { simId } = use(params)
  const ui = useUiStore()

  const reportQ = useReport(simId)
  const progressQ = useReportProgress(simId, true)
  const outlineQ = useReportOutline(simId)
  const generateM = useGenerateReport()

  const isGenerating =
    progressQ.data?.status === 'planning' || progressQ.data?.status === 'generating'

  const sections = outlineQ.data || []
  const [activeIdx, setActiveIdx] = useState<number>(1)

  // Auto-pick first section once outline arrives
  useEffect(() => {
    if (sections.length > 0 && (activeIdx == null || activeIdx === 0)) {
      setActiveIdx(sections[0].index)
    }
  }, [sections, activeIdx])

  const sectionQ = useReportSection(simId, activeIdx)

  // Report doesn't exist (404) and not generating → show CTA
  const reportMissing = reportQ.isError && !isGenerating

  async function onGenerate() {
    try {
      await generateM.mutateAsync({ simId, autoSentiment: true })
      ui.success('Report generation started.', 3000)
    } catch (e) {
      ui.error('Could not start: ' + (e as Error).message)
    }
  }

  if (reportMissing) {
    return (
      <EmptyState
        icon={BarChart3}
        title="No report yet"
        description="Generate a ReACT-style report from this simulation. The agent will outline 4-6 sections, then write each section with evidence anchors."
        action={
          <Button
            variant="primary"
            loading={generateM.isPending}
            onClick={onGenerate}
          >
            <Sparkles size={13} />
            Generate report
          </Button>
        }
      />
    )
  }

  return (
    <div className="grid grid-cols-[260px_1fr] gap-6 max-lg:grid-cols-1">
      {/* Outline sidebar */}
      <Card className="h-fit">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">Sections</CardTitle>
            {!isGenerating && (
              <Button
                variant="ghost"
                size="sm"
                loading={generateM.isPending}
                onClick={onGenerate}
                title="Regenerate"
                className="text-xs text-fg-muted"
              >
                Regenerate
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="px-2 pb-2">
          {isGenerating && (
            <div className="mb-2 flex items-center gap-2 rounded-md bg-warning-50 px-2.5 py-2 text-xs text-warning-600">
              <Loader2 size={13} className="animate-spin" />
              <span>
                {progressQ.data?.status === 'planning'
                  ? 'Outlining…'
                  : `Writing ${progressQ.data?.current_section ?? 1}/${progressQ.data?.total_sections ?? '?'}`}
              </span>
            </div>
          )}

          {outlineQ.isLoading ? (
            <div className="space-y-2 px-2">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-7" />
              ))}
            </div>
          ) : sections.length === 0 ? (
            <p className="px-2 py-2 text-xs text-fg-muted">
              No outline yet.
            </p>
          ) : (
            <ul className="space-y-0.5">
              {sections.map((s) => (
                <li key={s.index}>
                  <button
                    onClick={() => setActiveIdx(s.index)}
                    className={cn(
                      'group flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors',
                      activeIdx === s.index
                        ? 'bg-surface-muted text-fg'
                        : 'text-fg-muted hover:bg-surface-subtle hover:text-fg',
                    )}
                  >
                    <span
                      className={cn(
                        'mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md font-mono text-2xs',
                        activeIdx === s.index
                          ? 'bg-fg text-surface'
                          : 'bg-surface-muted text-fg-muted',
                      )}
                    >
                      {s.index}
                    </span>
                    <span className="leading-snug">{s.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>

        {reportQ.data?.meta && (
          <div className="border-t border-border px-3 py-2.5 text-xs text-fg-muted">
            {reportQ.data.meta.status && (
              <div className="flex items-center justify-between">
                <span>Status</span>
                <Badge tone={reportQ.data.meta.status === 'completed' ? 'success' : 'warning'}>
                  {reportQ.data.meta.status}
                </Badge>
              </div>
            )}
            {reportQ.data.meta.total_evidence != null && (
              <div className="mt-1 flex items-center justify-between">
                <span>Evidence</span>
                <span className="font-mono text-fg">
                  {reportQ.data.meta.total_evidence}
                </span>
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Section content */}
      <div className="min-w-0">
        {!sections.length && !isGenerating ? (
          <EmptyState
            icon={FileText}
            title="No sections yet"
            description="Trigger generation to start the ReACT loop."
          />
        ) : sectionQ.isLoading ? (
          <Card className="p-6">
            <div className="space-y-3">
              <Skeleton className="h-7 w-1/2" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-11/12" />
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-full" />
            </div>
          </Card>
        ) : sectionQ.isError ? (
          <ErrorState
            title="Could not load section"
            description={(sectionQ.error as Error).message}
            onRetry={() => sectionQ.refetch()}
          />
        ) : sectionQ.data ? (
          <Card className="p-6">
            <article className="prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {sectionQ.data.content}
              </ReactMarkdown>
            </article>
            <SectionNav
              sections={sections}
              activeIdx={activeIdx}
              onPick={setActiveIdx}
            />
          </Card>
        ) : null}
      </div>
    </div>
  )
}

function SectionNav({
  sections,
  activeIdx,
  onPick,
}: {
  sections: { index: number; title: string }[]
  activeIdx: number
  onPick: (i: number) => void
}) {
  const i = sections.findIndex((s) => s.index === activeIdx)
  const prev = i > 0 ? sections[i - 1] : null
  const next = i >= 0 && i < sections.length - 1 ? sections[i + 1] : null
  if (!prev && !next) return null
  return (
    <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
      {prev ? (
        <Button variant="ghost" size="sm" onClick={() => onPick(prev.index)}>
          <ChevronRight size={13} className="rotate-180" />
          {prev.title}
        </Button>
      ) : (
        <span />
      )}
      {next ? (
        <Button variant="secondary" size="sm" onClick={() => onPick(next.index)}>
          {next.title}
          <ChevronRight size={13} />
        </Button>
      ) : (
        <span />
      )}
    </div>
  )
}
