'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'

export interface TabItem {
  label: string
  href: string
  /** Match strategy. 'exact' = pathname === href; 'prefix' = pathname.startsWith(href). Default 'exact' for href === base, 'prefix' otherwise. */
  match?: 'exact' | 'prefix'
}

/**
 * Underline tab bar — Linear/Vercel style. Tabs are <Link> for SSR + prefetch.
 */
export function Tabs({
  items,
  className,
}: {
  items: TabItem[]
  className?: string
}) {
  const pathname = usePathname() || ''

  return (
    <nav
      className={cn(
        'flex items-end gap-0 border-b border-border',
        className,
      )}
      role="tablist"
    >
      {items.map((t) => {
        const matchMode = t.match || 'prefix'
        const active =
          matchMode === 'exact'
            ? pathname === t.href
            : pathname === t.href || pathname.startsWith(t.href + '/')

        return (
          <Link
            key={t.href}
            href={t.href}
            role="tab"
            aria-selected={active}
            className={cn(
              'relative -mb-px inline-flex items-center px-3 pb-2.5 pt-1 text-sm transition-colors',
              active
                ? 'text-fg font-semibold'
                : 'text-fg-muted hover:text-fg',
            )}
          >
            {t.label}
            <span
              aria-hidden
              className={cn(
                'absolute bottom-[-1px] left-0 right-0 h-[2px] rounded-full',
                active ? 'bg-fg' : 'bg-transparent',
              )}
            />
          </Link>
        )
      })}
    </nav>
  )
}
