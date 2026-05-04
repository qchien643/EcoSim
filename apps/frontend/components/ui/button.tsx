import * as React from 'react'
import { cn } from '@/lib/utils'

type Variant = 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger'
type Size = 'sm' | 'md' | 'lg'

const VARIANT: Record<Variant, string> = {
  primary:
    'bg-fg text-surface hover:bg-fg/90 active:bg-fg/80 disabled:bg-fg-faint',
  secondary:
    'bg-surface-muted text-fg border border-border hover:bg-surface-inset',
  ghost:
    'bg-transparent text-fg hover:bg-surface-muted',
  outline:
    'bg-surface text-fg border border-border hover:bg-surface-subtle hover:border-border-strong',
  danger:
    'bg-danger-500 text-white hover:bg-danger-600',
}

const SIZE: Record<Size, string> = {
  sm: 'h-7 px-2.5 text-xs gap-1.5',
  md: 'h-8 px-3 text-sm gap-2',
  lg: 'h-10 px-4 text-base gap-2',
}

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = 'secondary',
      size = 'md',
      className,
      children,
      loading,
      disabled,
      ...rest
    },
    ref,
  ) {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          'inline-flex items-center justify-center rounded-md font-medium',
          'transition-colors duration-100 ease-out',
          'focus-visible:outline-none disabled:opacity-50 disabled:pointer-events-none',
          'whitespace-nowrap select-none',
          VARIANT[variant],
          SIZE[size],
          className,
        )}
        {...rest}
      >
        {loading && (
          <span className="h-3 w-3 animate-spin rounded-full border-[1.5px] border-current border-t-transparent" />
        )}
        {children}
      </button>
    )
  },
)
