'use client'

import { Info, CheckCircle2, AlertTriangle, XCircle, X } from 'lucide-react'
import { useUiStore, type Toast } from '@/stores/ui-store'
import { cn } from '@/lib/utils'

const ICON: Record<Toast['type'], React.ComponentType<{ size?: number }>> = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: XCircle,
}

const TONE: Record<Toast['type'], string> = {
  info: 'bg-surface text-fg border-border',
  success: 'bg-success-50 text-success-700 border-success-500/30',
  warning: 'bg-warning-50 text-warning-600 border-warning-500/30',
  error: 'bg-danger-50 text-danger-600 border-danger-500/30',
}

const ICON_TONE: Record<Toast['type'], string> = {
  info: 'text-fg-muted',
  success: 'text-success-600',
  warning: 'text-warning-600',
  error: 'text-danger-600',
}

export function ToastHost() {
  const ui = useUiStore()
  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-[300] flex max-w-sm flex-col gap-2">
      {ui.toasts.map((t) => {
        const Icon = ICON[t.type]
        return (
          <div
            key={t.id}
            role="status"
            className={cn(
              'pointer-events-auto flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm shadow-md animate-in',
              TONE[t.type],
            )}
          >
            <Icon size={16} />
            <div className={cn('mt-px hidden', ICON_TONE[t.type])} />
            <span className="flex-1 leading-snug">{t.msg}</span>
            <button
              onClick={() => ui.dismiss(t.id)}
              className="mt-px shrink-0 text-current opacity-50 hover:opacity-100"
              aria-label="Dismiss"
            >
              <X size={13} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
