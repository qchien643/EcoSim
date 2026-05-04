'use client'

import { use, useEffect, useState } from 'react'
import {
  ClipboardList,
  Sparkles,
  Play,
  ArrowRight,
  Loader2,
} from 'lucide-react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from 'recharts'
import {
  useDefaultQuestions,
  useGenerateQuestions,
  useCreateSurvey,
  useConductSurvey,
  useSurveyResults,
  useLatestSurvey,
} from '@/lib/queries'
import { useUiStore } from '@/stores/ui-store'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/data/skeleton'
import { ErrorState } from '@/components/data/error-state'
import { EmptyState } from '@/components/data/empty-state'
import { cn, truncate } from '@/lib/utils'
import type {
  SurveyQuestion,
  SurveyAggregate,
} from '@/lib/types/backend'

const QTYPE_TONE: Record<string, 'success' | 'warning' | 'info' | 'brand' | 'neutral'> = {
  scale_1_10: 'info',
  yes_no: 'success',
  multiple_choice: 'warning',
  open_ended: 'brand',
}

export default function SimSurveyPage({
  params,
}: {
  params: Promise<{ campaignId: string; simId: string }>
}) {
  const { simId } = use(params)
  const ui = useUiStore()

  const latestQ = useLatestSurvey(simId)
  const surveyId = latestQ.data?.survey_id || null
  const resultsQ = useSurveyResults(surveyId)

  const defaultQ = useDefaultQuestions()
  const generateM = useGenerateQuestions()
  const createM = useCreateSurvey()
  const conductM = useConductSurvey()

  // Local question draft (auto-load defaults until generation runs)
  const [draft, setDraft] = useState<SurveyQuestion[]>([])

  useEffect(() => {
    if (defaultQ.data && draft.length === 0) {
      setDraft(defaultQ.data)
    }
  }, [defaultQ.data, draft.length])

  async function onGenerate() {
    try {
      const qs = await generateM.mutateAsync({ sim_id: simId, count: 10 })
      setDraft(qs)
      ui.success(`Generated ${qs.length} questions.`, 2500)
    } catch (e) {
      ui.error('Generate failed: ' + (e as Error).message)
    }
  }

  async function onConduct() {
    if (draft.length === 0) {
      ui.warning('Add or generate questions first.', 2500)
      return
    }
    try {
      const created = await createM.mutateAsync({ sim_id: simId, questions: draft })
      ui.info(`Survey ${created.survey_id} — running…`, 2500)
      const res = await conductM.mutateAsync(created.survey_id)
      ui.success(`Done · ${res.total_respondents} respondents`, 3000)
      latestQ.refetch()
    } catch (e) {
      ui.error('Conduct failed: ' + (e as Error).message)
    }
  }

  if (resultsQ.isError && !latestQ.isLoading && !surveyId) {
    // No survey yet → composer
    return (
      <Composer
        draft={draft}
        loading={defaultQ.isLoading}
        onGenerate={onGenerate}
        onConduct={onConduct}
        generating={generateM.isPending}
        conducting={createM.isPending || conductM.isPending}
      />
    )
  }

  if (!latestQ.isLoading && !surveyId) {
    return (
      <Composer
        draft={draft}
        loading={defaultQ.isLoading}
        onGenerate={onGenerate}
        onConduct={onConduct}
        generating={generateM.isPending}
        conducting={createM.isPending || conductM.isPending}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 className="text-md font-semibold text-fg">Survey results</h2>
          {resultsQ.data && (
            <p className="mt-0.5 text-xs text-fg-muted">
              <span className="font-mono">{resultsQ.data.survey_id}</span> ·{' '}
              {resultsQ.data.total_respondents ?? 0} respondents ·{' '}
              {(resultsQ.data.questions || []).length} questions
            </p>
          )}
        </div>
        <Button
          variant="secondary"
          size="sm"
          loading={createM.isPending || conductM.isPending}
          onClick={onConduct}
        >
          <Play size={13} />
          Run again
        </Button>
      </div>

      {resultsQ.isLoading ? (
        <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : resultsQ.isError ? (
        <ErrorState
          title="Could not load results"
          description={(resultsQ.error as Error).message}
          onRetry={() => resultsQ.refetch()}
        />
      ) : (
        <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
          {(resultsQ.data?.aggregated || []).map((a, i) => (
            <AggregateCard key={i} agg={a} />
          ))}
          {(resultsQ.data?.aggregated || []).length === 0 && (
            <p className="col-span-full p-6 text-center text-sm text-fg-muted">
              No aggregated results yet.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────
// Composer — visible when no survey exists yet
// ──────────────────────────────────────────
function Composer({
  draft,
  loading,
  onGenerate,
  onConduct,
  generating,
  conducting,
}: {
  draft: SurveyQuestion[]
  loading: boolean
  onGenerate: () => void
  onConduct: () => void
  generating: boolean
  conducting: boolean
}) {
  return (
    <div className="grid grid-cols-3 gap-6 max-lg:grid-cols-1">
      <div className="col-span-2 max-lg:col-span-1">
        <Card>
          <CardHeader className="border-b border-border pb-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-sm">
                  Question set
                  {draft.length > 0 && (
                    <span className="ml-1.5 text-xs font-normal text-fg-faint">
                      {draft.length}
                    </span>
                  )}
                </CardTitle>
                <p className="mt-0.5 text-xs text-fg-muted">
                  Auto-generated or default. Each question is tagged by report
                  section so the report agent can cite it later.
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  loading={generating}
                  onClick={onGenerate}
                >
                  <Sparkles size={13} />
                  Generate
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  loading={conducting}
                  onClick={onConduct}
                  disabled={draft.length === 0}
                >
                  <Play size={13} />
                  Conduct
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {loading ? (
              <div className="space-y-2 p-4">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-10" />
                ))}
              </div>
            ) : draft.length === 0 ? (
              <EmptyState
                icon={ClipboardList}
                title="No questions yet"
                description="Click Generate to LLM-craft 10 questions tagged by report section, or use the defaults."
                className="border-0 bg-transparent"
              />
            ) : (
              <ul className="divide-y divide-border-subtle">
                {draft.map((q, i) => (
                  <li key={q.id || i} className="flex items-start gap-3 px-4 py-3">
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-muted font-mono text-2xs text-fg-muted">
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm leading-snug text-fg">{q.text}</p>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        <Badge tone={QTYPE_TONE[q.question_type] || 'neutral'}>
                          {q.question_type}
                        </Badge>
                        {q.report_section && (
                          <Badge tone="brand">{q.report_section}</Badge>
                        )}
                        {q.category && q.category !== 'general' && (
                          <Badge tone="neutral">{q.category}</Badge>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">How it runs</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-fg-muted">
          <Step n={1} text="Compose / generate question list." />
          <Step n={2} text="Each question routes to canonical interview intent." />
          <Step n={3} text="N agents × M questions answered by fast LLM." />
          <Step n={4} text="Aggregated distribution + key themes shown here." />
          <p className="mt-2 text-xs text-fg-faint">
            Cost-aware — uses{' '}
            <code className="rounded bg-surface-muted px-1 py-0.5 font-mono text-2xs">
              LLM_FAST_MODEL_NAME
            </code>{' '}
            via shared 2-phase interview flow.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

function Step({ n, text }: { n: number; text: string }) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-50 font-mono text-2xs text-brand-700">
        {n}
      </span>
      <span>{text}</span>
    </div>
  )
}

function AggregateCard({ agg }: { agg: SurveyAggregate }) {
  const dist = agg.distribution || {}
  const data = Object.entries(dist).map(([k, v]) => ({ label: k, count: v }))

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm leading-snug">
            {truncate(agg.question, 70)}
          </CardTitle>
          <Badge tone={QTYPE_TONE[agg.question_type] || 'neutral'}>
            {agg.question_type}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-2">
        {agg.question_type === 'open_ended' ? (
          <div>
            <div className="mb-2 text-2xs font-medium uppercase tracking-wider text-fg-faint">
              Top themes
            </div>
            {agg.key_themes && agg.key_themes.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {agg.key_themes.map((t) => (
                  <Badge key={t} tone="neutral">
                    {t}
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="text-xs text-fg-muted">No themes extracted.</p>
            )}
          </div>
        ) : data.length > 0 ? (
          <div className="h-40">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 10, fill: '#71717a' }}
                  tickLine={false}
                  axisLine={{ stroke: '#e4e4e7' }}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: '#71717a' }}
                  tickLine={false}
                  axisLine={false}
                  width={28}
                />
                <Tooltip
                  contentStyle={{
                    background: '#ffffff',
                    border: '1px solid #e4e4e7',
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                  cursor={{ fill: 'rgba(124, 58, 237, 0.06)' }}
                />
                <Bar dataKey="count" fill="#7c3aed" radius={[2, 2, 0, 0]}>
                  {data.map((_, i) => (
                    <Cell key={i} fill={i % 2 === 0 ? '#7c3aed' : '#a78bfa'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="py-4 text-center text-xs text-fg-muted">
            No data for this question.
          </p>
        )}

        {agg.average != null && (
          <div className="mt-2 flex items-center justify-between border-t border-border pt-2 text-xs text-fg-muted">
            <span>Average</span>
            <span className="font-mono text-fg">
              {agg.average.toFixed(2)}
              {agg.min != null && agg.max != null && (
                <span className="text-fg-faint">
                  {' '}
                  ({agg.min}–{agg.max})
                </span>
              )}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
