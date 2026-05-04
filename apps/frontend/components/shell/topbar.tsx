'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Menu, ChevronRight, Search } from 'lucide-react'
import { useUiStore } from '@/stores/ui-store'
import { useCampaigns } from '@/lib/queries'
import { Kbd } from '@/components/ui/kbd'
import { cn, truncate } from '@/lib/utils'

/**
 * Top bar — minimal: mobile menu (md down) + breadcrumb derived from URL.
 * Search trigger duplicated for mobile (sidebar search hidden when collapsed/drawer).
 */
export function TopBar({ right }: { right?: React.ReactNode }) {
  const ui = useUiStore()
  const pathname = usePathname() || '/'
  const campaignsQ = useCampaigns()

  const crumbs = useMemo(() => buildCrumbs(pathname, campaignsQ.data || []), [
    pathname,
    campaignsQ.data,
  ])

  return (
    <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
      <button
        className="flex h-8 w-8 items-center justify-center rounded text-fg-muted hover:bg-surface-muted hover:text-fg md:hidden"
        onClick={ui.openMobileDrawer}
        aria-label="Open menu"
      >
        <Menu size={16} />
      </button>

      <nav
        aria-label="Breadcrumb"
        className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto text-sm"
      >
        {crumbs.map((c, i) => {
          const isLast = i === crumbs.length - 1
          return (
            <span
              key={`${c.href}-${i}`}
              className="inline-flex items-center gap-1 whitespace-nowrap"
            >
              {i > 0 && (
                <ChevronRight
                  size={12}
                  className="shrink-0 text-fg-faint"
                  strokeWidth={2}
                />
              )}
              {isLast ? (
                <span className="font-medium text-fg">{c.label}</span>
              ) : (
                <Link
                  href={c.href}
                  className="text-fg-muted hover:text-fg"
                >
                  {c.label}
                </Link>
              )}
            </span>
          )
        })}
      </nav>

      <div className="ml-auto flex items-center gap-2">
        {/* Mobile-only search trigger */}
        <button
          onClick={ui.openPalette}
          className="flex items-center gap-1.5 rounded-md border border-border bg-surface-subtle px-2 py-1 text-xs text-fg-muted hover:border-border-strong hover:text-fg md:hidden"
          aria-label="Search"
        >
          <Search size={12} />
          <Kbd>⌘K</Kbd>
        </button>
        {right}
      </div>
    </header>
  )
}

import { useMemo } from 'react'
import type { CampaignSummary } from '@/lib/types/backend'

function buildCrumbs(
  pathname: string,
  campaigns: CampaignSummary[],
): { label: string; href: string }[] {
  const parts = pathname.split('/').filter(Boolean)
  if (parts.length === 0) {
    return [{ label: 'Dashboard', href: '/' }]
  }

  const crumbs: { label: string; href: string }[] = []
  let acc = ''

  for (let i = 0; i < parts.length; i++) {
    const seg = parts[i]
    acc += '/' + seg

    // Pretty labels per known segment
    let label = seg
    if (seg === 'campaigns') {
      label = 'Campaigns'
    } else if (seg === 'new') {
      label = 'New campaign'
    } else if (parts[i - 1] === 'campaigns') {
      // dynamic [campaignId] → resolve name
      const c = campaigns.find((x) => x.campaign_id === seg)
      label = c?.name ? truncate(c.name, 30) : seg
    } else if (seg === 'sims') {
      label = 'Simulations'
    } else if (parts[i - 1] === 'sims') {
      label = `Sim · ${truncate(seg, 12)}`
    } else if (seg === 'spec') {
      label = 'Spec'
    } else if (seg === 'graph') {
      label = 'Knowledge graph'
    } else if (seg === 'analysis') {
      label = 'Analysis'
    } else if (seg === 'report') {
      label = 'Report'
    } else if (seg === 'survey') {
      label = 'Survey'
    } else if (seg === 'interview') {
      label = 'Interview'
    } else if (seg === 'settings') {
      label = 'Settings'
    } else {
      label = seg.charAt(0).toUpperCase() + seg.slice(1)
    }

    crumbs.push({ label, href: acc })
  }
  return crumbs
}
