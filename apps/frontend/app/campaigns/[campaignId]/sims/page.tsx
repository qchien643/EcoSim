'use client'

import { use, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Plus,
  FlaskConical,
  Loader2,
  AlertTriangle,
  Trash2,
  Brain,
  Zap,
  ChevronDown,
} from 'lucide-react'
import {
  useSims,
  usePrepareSim,
  useCacheStatus,
  useDeleteSim,
} from '@/lib/queries'
import { useUiStore } from '@/stores/ui-store'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogBody,
  DialogFooter,
} from '@/components/ui/dialog'
import { DataTable, type Column } from '@/components/data/data-table'
import { EmptyState } from '@/components/data/empty-state'
import { ErrorState } from '@/components/data/error-state'
import { formatDate, cn } from '@/lib/utils'
import type { SimSummary, SimStatus } from '@/lib/types/backend'
import type { CrisisEventDef } from '@/lib/api/sim'

const TONE: Record<SimStatus, 'success' | 'warning' | 'danger' | 'info' | 'neutral'> = {
  completed: 'success',
  running: 'warning',
  preparing: 'warning',
  ready: 'info',
  failed: 'danger',
  created: 'neutral',
}

export default function SimsPage({
  params,
}: {
  params: Promise<{ campaignId: string }>
}) {
  const { campaignId } = use(params)
  const router = useRouter()
  const ui = useUiStore()
  const simsQ = useSims()
  const deleteSimM = useDeleteSim()
  const [wizardOpen, setWizardOpen] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<SimSummary | null>(null)

  const sims = (simsQ.data || []).filter((s) => s.campaign_id === campaignId)

  async function confirmDeleteSim() {
    if (!pendingDelete) return
    const sid = pendingDelete.sim_id
    try {
      await deleteSimM.mutateAsync(sid)
      ui.success(`Deleted sim ${sid}.`, 3000)
      setPendingDelete(null)
    } catch (e) {
      ui.error('Delete failed: ' + (e as Error).message)
    }
  }

  const cols: Column<SimSummary>[] = [
    {
      key: 'sim_id',
      header: 'Sim',
      render: (s) => (
        <div className="flex items-center gap-2">
          <FlaskConical size={13} className="shrink-0 text-fg-muted" />
          <div className="min-w-0">
            <div className="truncate font-mono text-sm font-medium text-fg">
              {s.sim_id}
            </div>
            {s.group_id && (
              <div className="truncate text-2xs text-fg-faint">{s.group_id}</div>
            )}
          </div>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      width: '120px',
      render: (_, v) => (
        <Badge tone={TONE[v as SimStatus]} dot>
          {String(v)}
        </Badge>
      ),
    },
    {
      key: 'num_agents',
      header: 'Agents',
      width: '100px',
      align: 'right',
    },
    {
      key: 'num_rounds',
      header: 'Rounds',
      width: '100px',
      align: 'right',
      render: (_, v) => (v ? String(v) : <span className="text-fg-faint">—</span>),
    },
    {
      key: 'created_at',
      header: 'Created',
      width: '120px',
      align: 'right',
      render: (_, v) => formatDate(v as string),
    },
    {
      key: 'sim_id',
      header: '',
      width: '52px',
      align: 'right',
      render: (s) => (
        <Button
          variant="ghost"
          size="sm"
          aria-label="Delete sim"
          onClick={(e) => {
            e.stopPropagation()
            setPendingDelete(s)
          }}
          className="text-fg-faint hover:text-danger-500"
        >
          <Trash2 size={13} />
        </Button>
      ),
    },
  ]

  return (
    <div>
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h2 className="text-md font-semibold text-fg">Simulations</h2>
          <p className="mt-0.5 text-xs text-fg-muted">
            All sim runs for this campaign.{' '}
            {sims.length > 0 && (
              <span className="text-fg-faint">{sims.length} total</span>
            )}
          </p>
        </div>
        <Button variant="primary" onClick={() => setWizardOpen(true)}>
          <Plus size={14} />
          Prepare new sim
        </Button>
      </div>

      {simsQ.isError ? (
        <ErrorState
          title="Could not load simulations"
          description={(simsQ.error as Error).message}
          onRetry={() => simsQ.refetch()}
        />
      ) : !simsQ.isLoading && sims.length === 0 ? (
        <EmptyState
          icon={FlaskConical}
          title="No simulations"
          description="Prepare your first simulation for this campaign once a knowledge graph is ready."
        />
      ) : (
        <DataTable<SimSummary>
          columns={cols}
          rows={sims}
          rowKey="sim_id"
          onRowClick={(s) =>
            router.push(`/campaigns/${campaignId}/sims/${s.sim_id}`)
          }
          searchKeys={['sim_id', 'group_id', 'status']}
          loading={simsQ.isLoading}
        />
      )}

      <PrepareSimWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        campaignId={campaignId}
        onPrepared={(simId) =>
          router.push(`/campaigns/${campaignId}/sims/${simId}`)
        }
      />

      <Dialog
        open={!!pendingDelete}
        onClose={() => !deleteSimM.isPending && setPendingDelete(null)}
        size="sm"
      >
        <DialogHeader>
          <DialogTitle>Delete simulation?</DialogTitle>
          <DialogDescription>Cascade — không thể hoàn tác.</DialogDescription>
        </DialogHeader>
        <DialogBody>
          {pendingDelete ? (
            <div className="space-y-2 text-sm">
              <div>
                <span className="text-fg-muted">Sim ID:</span>{' '}
                <span className="font-mono text-xs text-fg">{pendingDelete.sim_id}</span>
              </div>
              <div>
                <span className="text-fg-muted">Status:</span>{' '}
                <Badge tone={TONE[pendingDelete.status]} dot>
                  {pendingDelete.status}
                </Badge>
              </div>
              <div className="mt-3 rounded border border-danger-200 bg-danger-50 px-3 py-2 text-xs text-danger-700">
                Sẽ xóa: meta.db row + agents + sentiment + folder{' '}
                <code className="rounded bg-danger-100 px-1">
                  data/campaigns/{campaignId}/sims/{pendingDelete.sim_id}
                </code>{' '}
                + FalkorDB graph <code className="rounded bg-danger-100 px-1">{pendingDelete.sim_id}</code>.
              </div>
            </div>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => setPendingDelete(null)}
            disabled={deleteSimM.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={confirmDeleteSim}
            loading={deleteSimM.isPending}
          >
            <Trash2 size={13} />
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  )
}

// ── Wizard ───────────────────────────────────────────────────────
//
// Form khớp `PrepareRequest` ở backend
// (apps/simulation/api/simulation.py:90-98):
//   campaign_id, num_agents, num_rounds, seed, cognitive_toggles, crisis_events
//
// Pre-flight check `useCacheStatus` để chặn prepare khi master KG chưa
// có trong FalkorDB lẫn snapshot — backend `prepare` sẽ fork master vào
// `sim_<sid>` graph (kg_fork.fork_master_to_sim) nên nếu master miss
// → fork fail → sim broken.

const MIN_AGENTS = 2
const MAX_AGENTS = 200
const MIN_ROUNDS = 1
const MAX_ROUNDS = 50

// Default toggles khớp backend (apps/simulation/api/simulation.py).
// Phase 15: re-introduce `enable_graph_cognition` — query FalkorDB sim graph
// để inject social context vào agent prompts. Default OFF vì cần Phase 15
// Zep extract chạy 1-2 round mới có data semantic.
const DEFAULT_TOGGLES = {
  enable_agent_memory: true,
  enable_mbti_modifiers: true,
  enable_interest_drift: true,
  enable_reflection: true,
  enable_graph_cognition: false,
} as const

type ToggleKey = keyof typeof DEFAULT_TOGGLES

const TOGGLE_META: Record<
  ToggleKey,
  { label: string; description: string; cost?: string }
> = {
  enable_agent_memory: {
    label: 'Agent memory',
    description: 'FIFO 5-round buffer + LLM-extracted memory nodes trong sim graph.',
  },
  enable_mbti_modifiers: {
    label: 'MBTI modifiers',
    description: 'Personality áp lên action probabilities (E/I, S/N, T/F, J/P).',
  },
  enable_interest_drift: {
    label: 'Interest drift',
    description: 'KeyBERT trích keyword từ engagement → drift interests qua rounds.',
  },
  enable_reflection: {
    label: 'Reflection',
    description: 'Mỗi round agent reflect → evolved persona. Cần Agent memory bật.',
  },
  enable_graph_cognition: {
    label: 'Graph cognition',
    description:
      'Trước khi sinh post/comment, query Graphiti hybrid search trên sim graph "agent X đã tương tác với ai, chủ đề gì?" rồi inject context vào prompt. Cần FalkorDB up + sim chạy ≥1 round mới có data.',
    cost: '+1 graph query/agent/action',
  },
}

function PrepareSimWizard({
  open,
  onClose,
  campaignId,
  onPrepared,
}: {
  open: boolean
  onClose: () => void
  campaignId: string
  onPrepared: (simId: string) => void
}) {
  const ui = useUiStore()
  const router = useRouter()
  const prepareM = usePrepareSim()

  const cacheQ = useCacheStatus({ campaignId: open ? campaignId : null })
  const cs = cacheQ.data
  const kgReady = cs?.kg_status === 'ready'

  const [numAgents, setNumAgents] = useState(10)
  const [numRounds, setNumRounds] = useState(3)
  const [seedStr, setSeedStr] = useState('')
  const [toggles, setToggles] = useState<Record<ToggleKey, boolean>>({
    ...DEFAULT_TOGGLES,
  })
  // Phase 15: Zep section dispatch luôn ON nếu ZEP_API_KEY có trong env
  // (auto detected backend). Frontend không expose toggle — đơn giản hóa UX.
  const [crisisEvents, setCrisisEvents] = useState<CrisisEventDef[]>([])

  // Reflection cần agent memory — auto-disable reflection nếu memory off.
  function setToggle(key: ToggleKey, value: boolean) {
    setToggles((prev) => {
      const next = { ...prev, [key]: value }
      if (key === 'enable_agent_memory' && !value) {
        next.enable_reflection = false
      }
      return next
    })
  }

  function reset() {
    setNumAgents(10)
    setNumRounds(3)
    setSeedStr('')
    setToggles({ ...DEFAULT_TOGGLES })
    setCrisisEvents([])
  }

  function handleClose() {
    if (prepareM.isPending) return
    onClose()
    setTimeout(reset, 200)
  }

  const seedNum = seedStr.trim() === '' ? undefined : Number(seedStr)
  const seedInvalid = seedStr.trim() !== '' && !Number.isFinite(seedNum)
  const agentsInvalid = numAgents < MIN_AGENTS || numAgents > MAX_AGENTS
  const roundsInvalid = numRounds < MIN_ROUNDS || numRounds > MAX_ROUNDS
  const crisisInvalid = crisisEvents.some(
    (c) =>
      !c.title.trim() ||
      c.trigger_round < 1 ||
      c.trigger_round > numRounds ||
      (c.severity != null && (c.severity < 0 || c.severity > 1)),
  )
  const formInvalid =
    agentsInvalid || roundsInvalid || seedInvalid || crisisInvalid

  async function handleSubmit() {
    if (formInvalid || !kgReady) return
    try {
      const res = await prepareM.mutateAsync({
        campaign_id: campaignId,
        num_agents: numAgents,
        num_rounds: numRounds,
        seed: seedNum,
        cognitive_toggles: toggles,
        crisis_events: crisisEvents,
      })
      const simId = res.sim_id
      ui.success(`Sim prepared: ${simId}. Agents inserted vào sim graph.`, 3500)

      onClose()
      reset()
      onPrepared(simId)
    } catch (e) {
      ui.error('Prepare failed: ' + (e as Error).message)
    }
  }

  const submitting = prepareM.isPending

  return (
    <Dialog open={open} onClose={handleClose} size="lg">
      <DialogHeader>
        <DialogTitle>Prepare new simulation</DialogTitle>
        <DialogDescription>
          Generate agent profiles + sim config từ campaign knowledge graph.
          Prepare ~30-60s tuỳ số agents (DuckDB sample + LLM enrichment).
        </DialogDescription>
      </DialogHeader>

      <DialogBody className="max-h-[70vh] overflow-y-auto">
        {cacheQ.isLoading ? (
          <div className="flex items-center gap-2 rounded-md bg-surface-muted px-3 py-2.5 text-xs text-fg-muted">
            <Loader2 size={13} className="animate-spin" />
            Checking knowledge graph…
          </div>
        ) : !kgReady ? (
          <div className="mb-3 rounded-md border border-warning-500/30 bg-warning-50 px-3 py-2.5 text-xs text-warning-600">
            <div className="flex items-start gap-2">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <div className="flex-1">
                <div className="font-medium text-warning-600">
                  Knowledge graph chưa sẵn sàng
                </div>
                <div className="mt-0.5 text-warning-600">
                  Build hoặc restore KG trước khi prepare sim. Backend sẽ fork
                  master graph vào sim graph — không có master → sim broken.
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-2 text-warning-600 hover:bg-warning-50"
                  onClick={() => {
                    onClose()
                    router.push(`/campaigns/${campaignId}/graph`)
                  }}
                >
                  Go to Graph tab →
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        {/* ── Section 1: Basics ── */}
        <SectionHeader title="Basics" />
        <div className="space-y-4">
          <NumberField
            label="Number of agents"
            hint={`${MIN_AGENTS}–${MAX_AGENTS}. Mỗi agent ~1 LLM call enrichment khi prepare.`}
            value={numAgents}
            onChange={setNumAgents}
            min={MIN_AGENTS}
            max={MAX_AGENTS}
            invalid={agentsInvalid}
          />

          <NumberField
            label="Number of rounds"
            hint={`${MIN_ROUNDS}–${MAX_ROUNDS}. Mỗi round ~30s (LLM-heavy reflection + posting).`}
            value={numRounds}
            onChange={setNumRounds}
            min={MIN_ROUNDS}
            max={MAX_ROUNDS}
            invalid={roundsInvalid}
          />

          <div>
            <label className="mb-1 block text-xs font-medium text-fg">
              Random seed{' '}
              <span className="text-fg-faint font-normal">(optional)</span>
            </label>
            <Input
              type="number"
              placeholder="Leave blank cho random"
              value={seedStr}
              onChange={(e) => setSeedStr(e.target.value)}
              className={seedInvalid ? 'border-danger-500' : ''}
            />
            <p className="mt-1 text-2xs text-fg-muted">
              Same seed + same KG → same agents (reproducible).
            </p>
          </div>
        </div>

        {/* ── Section 2: Cognitive toggles ── */}
        <SectionHeader title="Cognitive features" icon={Brain} className="mt-6" />
        <p className="mb-3 text-2xs text-fg-muted">
          Bật/tắt các module nhận thức của agent. Default match production preset.
        </p>
        <div className="space-y-2">
          {(Object.keys(DEFAULT_TOGGLES) as ToggleKey[]).map((key) => {
            const meta = TOGGLE_META[key]
            const disabled =
              key === 'enable_reflection' && !toggles.enable_agent_memory
            return (
              <ToggleRow
                key={key}
                label={meta.label}
                description={meta.description}
                cost={meta.cost}
                checked={toggles[key]}
                onChange={(v) => setToggle(key, v)}
                disabled={disabled}
                disabledHint={
                  disabled ? 'Cần Agent memory bật trước' : undefined
                }
              />
            )
          })}
        </div>

        {/* ── Section 3: Crisis events ── */}
        <SectionHeader title="Crisis events" icon={Zap} className="mt-6">
          <span className="text-2xs text-fg-faint">
            {crisisEvents.length === 0
              ? 'Không có'
              : `${crisisEvents.length} scheduled`}
          </span>
        </SectionHeader>
        <p className="mb-3 text-2xs text-fg-muted">
          Đến đúng round chỉ định, hệ thống tự đăng một bài "tin nóng"
          mô tả sự kiện và khiến các agent biết về nó — nhiều agent sẽ
          phản ứng (đăng bài, bình luận) bám theo crisis trong vài round
          kế tiếp. Bỏ trống = không có khủng hoảng nào trong sim.
        </p>
        <div className="space-y-2">
          {crisisEvents.map((event, idx) => (
            <CrisisEventEditor
              key={idx}
              event={event}
              maxRound={numRounds}
              onChange={(next) =>
                setCrisisEvents((prev) =>
                  prev.map((c, i) => (i === idx ? next : c)),
                )
              }
              onRemove={() =>
                setCrisisEvents((prev) => prev.filter((_, i) => i !== idx))
              }
            />
          ))}
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              setCrisisEvents((prev) => [
                ...prev,
                {
                  trigger_round: Math.min(2, numRounds),
                  crisis_type: 'custom',
                  title: '',
                  description: '',
                  severity: 0.5,
                  affected_domains: [],
                  sentiment_shift: 'negative',
                  n_keywords: 5,
                },
              ])
            }
            className="w-full justify-center border border-dashed border-border text-fg-muted hover:bg-surface-subtle"
          >
            <Plus size={13} />
            Add crisis event
          </Button>
        </div>

      </DialogBody>

      <DialogFooter>
        <Button variant="ghost" onClick={handleClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={handleSubmit}
          loading={submitting}
          disabled={formInvalid || !kgReady || submitting}
        >
          {submitting ? 'Preparing…' : 'Prepare'}
        </Button>
      </DialogFooter>
    </Dialog>
  )
}

// ── Building blocks ──────────────────────────────────────────────

function SectionHeader({
  title,
  icon: Icon,
  className,
  children,
}: {
  title: string
  icon?: React.ComponentType<{ size?: number; className?: string }>
  className?: string
  children?: React.ReactNode
}) {
  return (
    <div
      className={cn(
        'mb-2 flex items-center justify-between border-b border-border pb-1.5',
        className,
      )}
    >
      <div className="flex items-center gap-1.5">
        {Icon && <Icon size={13} className="text-fg-muted" />}
        <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
          {title}
        </h3>
      </div>
      {children}
    </div>
  )
}

function NumberField({
  label,
  hint,
  value,
  onChange,
  min,
  max,
  invalid,
}: {
  label: string
  hint?: string
  value: number
  onChange: (n: number) => void
  min: number
  max: number
  invalid?: boolean
}) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <label className="block text-xs font-medium text-fg">{label}</label>
        <span className="font-mono text-2xs text-fg-faint">
          {min}–{max}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <input
          type="range"
          min={min}
          max={max}
          value={Math.min(Math.max(value, min), max)}
          onChange={(e) => onChange(Number(e.target.value))}
          className="flex-1 accent-brand-500"
        />
        <Input
          type="number"
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className={`w-20 ${invalid ? 'border-danger-500' : ''}`}
        />
      </div>
      {hint && <p className="mt-1 text-2xs text-fg-muted">{hint}</p>}
    </div>
  )
}

function ToggleRow({
  label,
  description,
  cost,
  checked,
  onChange,
  disabled,
  disabledHint,
}: {
  label: string
  description: string
  cost?: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
  disabledHint?: string
}) {
  return (
    <label
      className={cn(
        'flex cursor-pointer items-start gap-3 rounded-md border border-border bg-surface px-3 py-2.5',
        disabled
          ? 'cursor-not-allowed opacity-50'
          : 'hover:border-fg-muted hover:bg-surface-subtle',
      )}
    >
      <input
        type="checkbox"
        checked={checked && !disabled}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-3.5 w-3.5 cursor-pointer accent-brand-500 disabled:cursor-not-allowed"
      />
      <div className="flex-1 text-xs">
        <div className="flex items-center gap-2">
          <span className="font-medium text-fg">{label}</span>
          {cost && (
            <Badge tone="warning" className="text-2xs">
              {cost}
            </Badge>
          )}
        </div>
        <div className="mt-0.5 text-fg-muted">{description}</div>
        {disabled && disabledHint && (
          <div className="mt-0.5 text-2xs text-warning-600">{disabledHint}</div>
        )}
      </div>
    </label>
  )
}

const CRISIS_TYPES: { value: CrisisEventDef['crisis_type']; label: string }[] = [
  { value: 'custom', label: 'Custom' },
  { value: 'price_change', label: 'Price change' },
  { value: 'scandal', label: 'Scandal' },
  { value: 'news', label: 'News' },
  { value: 'competitor', label: 'Competitor move' },
  { value: 'regulation', label: 'Regulation' },
  { value: 'positive_event', label: 'Positive event' },
]

const SENTIMENT_SHIFTS: {
  value: NonNullable<CrisisEventDef['sentiment_shift']>
  label: string
}[] = [
    { value: 'negative', label: 'Negative' },
    { value: 'positive', label: 'Positive' },
    { value: 'mixed', label: 'Mixed' },
  ]

function CrisisEventEditor({
  event,
  maxRound,
  onChange,
  onRemove,
}: {
  event: CrisisEventDef
  maxRound: number
  onChange: (next: CrisisEventDef) => void
  onRemove: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const titleInvalid = !event.title.trim()
  const roundInvalid = event.trigger_round < 1 || event.trigger_round > maxRound

  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2.5">
      <div className="flex items-center gap-2">
        <Input
          placeholder="Title (vd: Đối thủ giảm giá 50%)"
          value={event.title}
          onChange={(e) => onChange({ ...event, title: e.target.value })}
          className={cn('flex-1', titleInvalid && 'border-danger-500')}
        />
        <button
          onClick={onRemove}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-fg-muted hover:bg-danger-50 hover:text-danger-500"
          aria-label="Remove crisis"
        >
          <Trash2 size={13} />
        </button>
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2">
        <div>
          <label className="text-2xs text-fg-muted">Trigger round</label>
          <Input
            type="number"
            min={1}
            max={maxRound}
            value={event.trigger_round}
            onChange={(e) =>
              onChange({ ...event, trigger_round: Number(e.target.value) })
            }
            className={cn('mt-0.5', roundInvalid && 'border-danger-500')}
          />
        </div>
        <div>
          <label className="text-2xs text-fg-muted">Type</label>
          <select
            value={event.crisis_type}
            onChange={(e) =>
              onChange({
                ...event,
                crisis_type: e.target.value as CrisisEventDef['crisis_type'],
              })
            }
            className="mt-0.5 h-8 w-full rounded-md border border-border bg-surface px-2 text-xs text-fg focus-visible:border-brand-500 focus-visible:outline-none"
          >
            {CRISIS_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-2xs text-fg-muted">Sentiment</label>
          <select
            value={event.sentiment_shift || 'negative'}
            onChange={(e) =>
              onChange({
                ...event,
                sentiment_shift: e.target
                  .value as CrisisEventDef['sentiment_shift'],
              })
            }
            className="mt-0.5 h-8 w-full rounded-md border border-border bg-surface px-2 text-xs text-fg focus-visible:border-brand-500 focus-visible:outline-none"
          >
            {SENTIMENT_SHIFTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-2">
        <div className="flex items-baseline justify-between">
          <label className="text-2xs text-fg-muted">
            Severity{' '}
            <span className="font-mono text-fg-faint">
              {(event.severity ?? 0.5).toFixed(2)}
            </span>
          </label>
          <span className="text-2xs text-fg-faint">
            {(event.severity ?? 0) < 0.33
              ? 'mild'
              : (event.severity ?? 0) < 0.66
                ? 'moderate'
                : 'severe'}
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={event.severity ?? 0.5}
          onChange={(e) =>
            onChange({ ...event, severity: Number(e.target.value) })
          }
          className="mt-0.5 w-full accent-brand-500"
        />
      </div>

      <button
        onClick={() => setExpanded((v) => !v)}
        className="mt-2 flex items-center gap-1 text-2xs text-fg-muted hover:text-fg"
      >
        <ChevronDown
          size={11}
          className={cn('transition-transform', expanded && 'rotate-180')}
        />
        {expanded ? 'Less' : 'More'} options
      </button>

      {expanded && (
        <div className="mt-2 space-y-2">
          <div>
            <label className="text-2xs text-fg-muted">Description</label>
            <Input
              placeholder="Mô tả ngắn ngữ cảnh khủng hoảng"
              value={event.description || ''}
              onChange={(e) =>
                onChange({ ...event, description: e.target.value })
              }
              className="mt-0.5"
            />
          </div>
          <div>
            <label className="text-2xs text-fg-muted">
              Affected domains{' '}
              <span className="text-fg-faint">(comma-separated)</span>
            </label>
            <Input
              placeholder="ecommerce, retail"
              value={(event.affected_domains || []).join(', ')}
              onChange={(e) =>
                onChange({
                  ...event,
                  affected_domains: e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
              className="mt-0.5"
            />
          </div>
          <div>
            <label className="text-2xs text-fg-muted">
              Số từ khoá LLM trích xuất
            </label>
            <Input
              type="number"
              min={1}
              max={20}
              value={event.n_keywords ?? 5}
              onChange={(e) =>
                onChange({
                  ...event,
                  n_keywords: Math.max(
                    1,
                    Math.min(20, Number(e.target.value) || 5),
                  ),
                })
              }
              className="mt-0.5"
            />
            <div className="mt-1 text-2xs text-fg-faint">
              LLM đọc title + description + lĩnh vực ảnh hưởng để rút ra N
              keyphrase, dùng cho vector search và inject vào agent.
            </div>
          </div>
          <div className="rounded-md border border-border bg-surface-subtle px-3 py-2">
            <div className="text-2xs text-fg-muted">
              Khi crisis trigger, LLM tự trích N keyphrase từ thông tin trên,
              tiêm vào vector hứng thú của tất cả agent với cường độ ={' '}
              <span className="font-medium">severity</span> (UI nhập sao backend
              dùng vậy). Sau đó mỗi round, agent nào tương tác với chủ đề →
              cường độ tăng; agent không quan tâm → tự quên dần. Hệ thống tự
              quản lifecycle dựa trên hành vi từng agent.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
