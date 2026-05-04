'use client'

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Upload, FileText, ArrowLeft } from 'lucide-react'
import { useUploadCampaign } from '@/lib/queries'
import { useUiStore } from '@/stores/ui-store'
import { useAppStore } from '@/stores/app-store'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export default function NewCampaignPage() {
  const router = useRouter()
  const ui = useUiStore()
  const app = useAppStore()
  const uploadM = useUploadCampaign()
  const fileRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  async function handleFile(file: File) {
    try {
      const spec = await uploadM.mutateAsync(file)
      app.pushRecentCampaign(spec.campaign_id)
      ui.success(`Uploaded: ${spec.name}`, 3000)
      router.push(`/campaigns/${spec.campaign_id}`)
    } catch (e) {
      ui.error('Upload failed: ' + (e as Error).message)
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-8">
      <Button
        variant="ghost"
        size="sm"
        className="mb-4 -ml-2"
        onClick={() => router.back()}
      >
        <ArrowLeft size={13} />
        Back
      </Button>

      <h1 className="text-2xl font-semibold tracking-tight text-fg">
        New campaign
      </h1>
      <p className="mt-1 text-sm text-fg-muted">
        Upload a brief — EcoSim will LLM-parse it into a structured CampaignSpec.
      </p>

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          const f = e.dataTransfer.files[0]
          if (f) handleFile(f)
        }}
        onClick={() => fileRef.current?.click()}
        className={cn(
          'mt-6 flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-16 text-center transition-all',
          dragging
            ? 'border-brand-500 bg-brand-50'
            : 'border-border bg-surface-subtle hover:border-border-strong hover:bg-surface-muted',
          uploadM.isPending && 'pointer-events-none opacity-60',
        )}
      >
        <input
          type="file"
          ref={fileRef}
          className="hidden"
          accept=".pdf,.md,.txt,.markdown"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleFile(f)
          }}
        />
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface text-fg-muted shadow-xs">
          <Upload size={20} strokeWidth={2} />
        </div>
        <div>
          <div className="text-md font-medium text-fg">
            {uploadM.isPending ? 'Parsing…' : 'Drop file or click to browse'}
          </div>
          <div className="mt-1 text-xs text-fg-muted">
            Accepts PDF, Markdown, or plain text · Max ~50 MB
          </div>
        </div>
      </div>

      {/* What happens next */}
      <div className="mt-8 rounded-lg border border-border bg-surface-subtle p-4">
        <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-fg">
          <FileText size={13} className="text-fg-muted" />
          What happens after upload
        </h3>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-fg-muted">
          <li>Document is chunked + parsed by LLM into CampaignSpec.</li>
          <li>Spec includes: name, type, market, KPIs, stakeholders, risks.</li>
          <li>You can then build a knowledge graph + run simulations.</li>
        </ol>
      </div>
    </div>
  )
}
