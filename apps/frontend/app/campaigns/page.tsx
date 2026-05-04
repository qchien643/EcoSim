'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, FolderKanban, Trash2 } from 'lucide-react'
import { useCampaigns, useDeleteCampaign } from '@/lib/queries'
import { useUiStore } from '@/stores/ui-store'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
import { formatDate } from '@/lib/utils'
import type { CampaignSummary } from '@/lib/types/backend'

export default function CampaignsPage() {
  const router = useRouter()
  const ui = useUiStore()
  const campaignsQ = useCampaigns()
  const deleteM = useDeleteCampaign()
  const [pendingDelete, setPendingDelete] = useState<CampaignSummary | null>(null)

  const campaigns = campaignsQ.data || []

  async function confirmDelete() {
    if (!pendingDelete) return
    const cid = pendingDelete.campaign_id
    try {
      const res = await deleteM.mutateAsync(cid)
      const simNote = res.sims_dropped.length
        ? ` (cascade ${res.sims_dropped.length} sims)`
        : ''
      ui.success(`Deleted campaign ${cid}${simNote}.`, 4000)
      setPendingDelete(null)
    } catch (e) {
      ui.error('Delete failed: ' + (e as Error).message)
    }
  }

  const cols: Column<CampaignSummary>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (c) => (
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-brand-50 text-brand-600">
            <FolderKanban size={12} />
          </div>
          <div className="min-w-0">
            <div className="truncate font-medium text-fg">{c.name}</div>
            <div className="font-mono text-2xs text-fg-faint">
              {c.campaign_id}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: 'campaign_type',
      header: 'Type',
      width: '140px',
      render: (_, v) =>
        v ? <Badge tone="brand">{String(v)}</Badge> : <span className="text-fg-faint">—</span>,
    },
    {
      key: 'market',
      header: 'Market',
      width: '140px',
      render: (_, v) =>
        v ? <Badge tone="neutral">{String(v)}</Badge> : <span className="text-fg-faint">—</span>,
    },
    {
      key: 'created_at',
      header: 'Created',
      width: '120px',
      align: 'right',
      render: (_, v) => formatDate(v as string),
    },
    {
      key: 'campaign_id',
      header: '',
      width: '52px',
      align: 'right',
      render: (c) => (
        <Button
          variant="ghost"
          size="sm"
          aria-label="Delete campaign"
          onClick={(e) => {
            e.stopPropagation()
            setPendingDelete(c)
          }}
          className="text-fg-faint hover:text-danger-500"
        >
          <Trash2 size={13} />
        </Button>
      ),
    },
  ]

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-fg">
            Campaigns
          </h1>
          <p className="mt-1 text-sm text-fg-muted">
            All ingested campaign briefs.{' '}
            {campaigns.length > 0 && (
              <span className="text-fg-faint">{campaigns.length} total</span>
            )}
          </p>
        </div>
        <Button variant="primary" onClick={() => router.push('/campaigns/new')}>
          <Plus size={14} />
          New campaign
        </Button>
      </div>

      {campaignsQ.isError ? (
        <ErrorState
          title="Could not load campaigns"
          description={(campaignsQ.error as Error).message}
          onRetry={() => campaignsQ.refetch()}
        />
      ) : !campaignsQ.isLoading && campaigns.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="No campaigns yet"
          description="Upload a campaign brief — PDF, Markdown, or plain text. EcoSim will parse it into a structured spec."
          action={
            <Button variant="primary" onClick={() => router.push('/campaigns/new')}>
              <Plus size={14} />
              Create your first campaign
            </Button>
          }
        />
      ) : (
        <DataTable<CampaignSummary>
          columns={cols}
          rows={campaigns}
          rowKey="campaign_id"
          onRowClick={(c) => router.push(`/campaigns/${c.campaign_id}`)}
          initialSortKey="created_at"
          initialSortDir="desc"
          loading={campaignsQ.isLoading}
        />
      )}

      <Dialog
        open={!!pendingDelete}
        onClose={() => !deleteM.isPending && setPendingDelete(null)}
        size="sm"
      >
        <DialogHeader>
          <DialogTitle>Delete campaign?</DialogTitle>
          <DialogDescription>
            Cascade — không thể hoàn tác.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          {pendingDelete ? (
            <div className="space-y-2 text-sm">
              <div>
                <span className="text-fg-muted">Name:</span>{' '}
                <span className="font-medium text-fg">{pendingDelete.name}</span>
              </div>
              <div>
                <span className="text-fg-muted">ID:</span>{' '}
                <span className="font-mono text-xs text-fg">{pendingDelete.campaign_id}</span>
              </div>
              <div className="mt-3 rounded border border-danger-200 bg-danger-50 px-3 py-2 text-xs text-danger-700">
                Sẽ xóa: meta.db row + tất cả simulations + folder{' '}
                <code className="rounded bg-danger-100 px-1">data/campaigns/{pendingDelete.campaign_id}</code>{' '}
                + FalkorDB graph master + sim graphs.
              </div>
            </div>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => setPendingDelete(null)}
            disabled={deleteM.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={confirmDelete}
            loading={deleteM.isPending}
          >
            <Trash2 size={13} />
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  )
}
