import * as React from 'react'
import { cn } from '@/lib/utils'

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, type = 'text', ...rest }, ref) {
    return (
      <input
        ref={ref}
        type={type}
        className={cn(
          'h-8 w-full rounded-md border border-border bg-surface px-2.5 text-sm text-fg',
          'placeholder:text-fg-faint',
          'focus-visible:outline-none focus-visible:border-brand-500',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'transition-colors duration-100',
          className,
        )}
        {...rest}
      />
    )
  },
)
