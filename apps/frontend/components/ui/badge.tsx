import * as React from 'react'
import { cn } from '@/lib/utils'

type Tone =
  | 'neutral'
  | 'brand'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info'
  | 'outline'

const TONE: Record<Tone, string> = {
  neutral: 'bg-surface-muted text-fg border-transparent',
  brand: 'bg-brand-50 text-brand-700 border-transparent',
  success: 'bg-success-50 text-success-700 border-transparent',
  warning: 'bg-warning-50 text-warning-600 border-transparent',
  danger: 'bg-danger-50 text-danger-600 border-transparent',
  info: 'bg-info-50 text-info-600 border-transparent',
  outline: 'bg-surface text-fg-muted border-border',
}

export function Badge({
  tone = 'neutral',
  className,
  children,
  dot,
  ...rest
}: React.HTMLAttributes<HTMLSpanElement> & {
  tone?: Tone
  dot?: boolean
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-2xs font-medium leading-none',
        TONE[tone],
        className,
      )}
      {...rest}
    >
      {dot && (
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full',
            tone === 'success' && 'bg-success-500',
            tone === 'warning' && 'bg-warning-500',
            tone === 'danger' && 'bg-danger-500',
            tone === 'info' && 'bg-info-500',
            tone === 'brand' && 'bg-brand-500',
            tone === 'neutral' && 'bg-fg-faint',
            tone === 'outline' && 'bg-fg-faint',
          )}
        />
      )}
      {children}
    </span>
  )
}
