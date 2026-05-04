'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  FolderKanban,
  Plus,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  ChevronRight,
  type LucideIcon,
} from 'lucide-react'
import { useUiStore } from '@/stores/ui-store'
import { useCampaigns } from '@/lib/queries'
import { useHydrated } from '@/hooks/use-hydration'
import { cn, truncate } from '@/lib/utils'
import { Kbd } from '@/components/ui/kbd'

interface NavItem {
  label: string
  href: string
  icon: LucideIcon
}

const PRIMARY_NAV: NavItem[] = [
  { label: 'Dashboard', href: '/', icon: LayoutDashboard },
  { label: 'All campaigns', href: '/campaigns', icon: FolderKanban },
]

const FOOTER_NAV: NavItem[] = [
  { label: 'Settings', href: '/settings', icon: Settings },
]

export function Sidebar() {
  const ui = useUiStore()
  const pathname = usePathname() || '/'
  const hydrated = useHydrated()
  const collapsed = hydrated && ui.sidebarCollapsed
  const mobileOpen = hydrated && ui.sidebarMobileOpen

  const campaignsQ = useCampaigns()
  const campaigns = campaignsQ.data || []

  const activeCampaignId = pathname.match(/^\/campaigns\/([^/]+)/)?.[1] || null

  // Phase 16.fix: STABLE ordering. Trước đó dùng `recentCampaignIds` reorder
  // mỗi khi visit → user click campaign #3, nó nhảy lên top → tưởng "chỉ top
  // được highlight". Giờ sort theo `created_at` desc (campaign mới nhất ở top)
  // — vị trí cố định, active highlight ở đúng slot user click.
  const recent = (() => {
    const sorted = [...campaigns].sort((a, b) => {
      const ta = a.created_at || ''
      const tb = b.created_at || ''
      return tb.localeCompare(ta)
    })
    return sorted.slice(0, 5).map((c) => ({
      id: c.campaign_id,
      name: c.name || c.campaign_id,
    }))
  })()

  function isActive(href: string) {
    if (href === '/') return pathname === '/'
    return pathname === href || pathname.startsWith(href + '/')
  }

  return (
    <>
      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/30 md:hidden"
          onClick={ui.closeMobileDrawer}
        />
      )}

      <aside
        className={cn(
          'fixed left-0 top-0 z-50 flex h-screen flex-col border-r border-border bg-surface-subtle',
          'transition-[width,transform] duration-200 ease-out',
          collapsed ? 'w-[56px]' : 'w-[256px]',
          // Mobile drawer
          'max-md:-translate-x-full max-md:w-[256px]',
          mobileOpen && 'max-md:translate-x-0',
        )}
        aria-label="Sidebar"
      >
        {/* Brand + collapse */}
        <div className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-border px-3">
          <Link
            href="/"
            className={cn(
              'flex min-w-0 flex-1 items-center gap-2',
              collapsed && 'justify-center',
            )}
          >
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-fg text-[11px] font-bold tracking-tight text-white">
              E
            </div>
            {!collapsed && (
              <span className="font-semibold tracking-tight text-fg">EcoSim</span>
            )}
          </Link>
          {!collapsed && (
            <button
              onClick={ui.toggleSidebar}
              className="flex h-7 w-7 items-center justify-center rounded text-fg-muted hover:bg-surface-muted hover:text-fg"
              title="Collapse sidebar"
              aria-label="Collapse sidebar"
            >
              <PanelLeftClose size={15} />
            </button>
          )}
        </div>

        {/* Search trigger */}
        <div className="px-2 pt-2">
          <button
            onClick={ui.openPalette}
            title="Search (Ctrl+K)"
            className={cn(
              'flex w-full items-center gap-2 rounded-md border border-border bg-surface px-2 py-1.5 text-left text-sm text-fg-muted shadow-xs transition-colors hover:border-border-strong hover:text-fg',
              collapsed && 'justify-center',
            )}
          >
            <Search size={14} className="shrink-0" />
            {!collapsed && (
              <>
                <span className="flex-1 truncate">Search…</span>
                <Kbd>⌘K</Kbd>
              </>
            )}
          </button>
        </div>

        {/* Primary nav */}
        <nav className="px-2 pt-3">
          {PRIMARY_NAV.map((item) => (
            <SideLink
              key={item.href}
              item={item}
              active={isActive(item.href)}
              collapsed={collapsed}
            />
          ))}
        </nav>

        {/* Recent campaigns */}
        {!collapsed && (
          <div className="mt-5 flex min-h-0 flex-1 flex-col">
            <div className="flex items-center justify-between px-3 pb-1.5">
              <span className="text-2xs font-semibold uppercase tracking-wider text-fg-faint">
                Recent
              </span>
              <Link
                href="/campaigns/new"
                title="New campaign"
                className="flex h-5 w-5 items-center justify-center rounded text-fg-muted hover:bg-surface-muted hover:text-fg"
              >
                <Plus size={13} strokeWidth={2.5} />
              </Link>
            </div>
            <div className="overflow-y-auto px-2 pb-2">
              {campaignsQ.isLoading ? (
                <div className="space-y-1.5 px-2 py-1">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="skeleton h-5" />
                  ))}
                </div>
              ) : recent.length === 0 ? (
                <p className="px-2 py-2 text-xs text-fg-muted">
                  No campaigns yet.{' '}
                  <Link href="/campaigns/new" className="text-brand-600 hover:underline">
                    Create one
                  </Link>
                  .
                </p>
              ) : (
                recent.map((c) => {
                  const isActive = activeCampaignId === c.id
                  return (
                    <Link
                      key={c.id}
                      href={`/campaigns/${c.id}`}
                      onClick={ui.closeMobileDrawer}
                      className={cn(
                        'group relative flex items-center gap-1.5 rounded-md px-2 py-1 text-sm transition-all',
                        isActive
                          ? 'bg-brand-50 text-brand-700 font-semibold shadow-sm ring-1 ring-brand-200'
                          : 'text-fg-muted hover:bg-surface-muted hover:text-fg',
                      )}
                      title={c.name}
                      aria-current={isActive ? 'page' : undefined}
                    >
                      {/* Left accent bar khi active */}
                      {isActive && (
                        <span
                          aria-hidden
                          className="absolute left-0 top-1 bottom-1 w-0.5 rounded-r bg-brand-500"
                        />
                      )}
                      <ChevronRight
                        size={11}
                        className={cn(
                          'shrink-0 transition-transform',
                          isActive ? 'text-brand-600 translate-x-0.5' : 'text-fg-muted',
                        )}
                      />
                      <span className="truncate">{truncate(c.name, 28)}</span>
                    </Link>
                  )
                })
              )}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="mt-auto shrink-0 border-t border-border px-2 py-2">
          {FOOTER_NAV.map((item) => (
            <SideLink
              key={item.href}
              item={item}
              active={isActive(item.href)}
              collapsed={collapsed}
            />
          ))}
          <div
            className={cn(
              'mt-2 flex items-center gap-2 rounded-md px-2 py-1.5',
              collapsed && 'justify-center',
            )}
          >
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700">
              AD
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-fg">Admin</div>
                <div className="truncate text-2xs text-fg-faint">EcoSim · v3</div>
              </div>
            )}
          </div>

          {collapsed && (
            <button
              onClick={ui.toggleSidebar}
              className="mt-2 flex h-7 w-full items-center justify-center rounded text-fg-muted hover:bg-surface-muted hover:text-fg"
              title="Expand sidebar"
              aria-label="Expand sidebar"
            >
              <PanelLeftOpen size={15} />
            </button>
          )}
        </div>
      </aside>
    </>
  )
}

function SideLink({
  item,
  active,
  collapsed,
}: {
  item: NavItem
  active: boolean
  collapsed: boolean
}) {
  const Icon = item.icon
  return (
    <Link
      href={item.href}
      title={item.label}
      className={cn(
        'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors',
        collapsed && 'justify-center',
        active
          ? 'bg-surface text-fg shadow-xs ring-1 ring-border'
          : 'text-fg-muted hover:bg-surface-muted hover:text-fg',
      )}
    >
      <Icon
        size={15}
        strokeWidth={2}
        className={cn('shrink-0', active && 'text-brand-600')}
      />
      {!collapsed && <span>{item.label}</span>}
    </Link>
  )
}
