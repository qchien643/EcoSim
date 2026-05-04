'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Search,
  LayoutDashboard,
  FolderKanban,
  Plus,
  Settings,
  Bug,
  RotateCcw,
  PanelLeft,
  type LucideIcon,
} from 'lucide-react'
import { useUiStore } from '@/stores/ui-store'
import { useAppStore } from '@/stores/app-store'
import { useCampaigns } from '@/lib/queries'
import { Kbd } from '@/components/ui/kbd'
import { cn } from '@/lib/utils'

interface Cmd {
  id: string
  label: string
  hint?: string
  icon: LucideIcon
  action: () => void
}

function fuzzy(needle: string, hay: string): boolean {
  if (!needle) return true
  const n = needle.toLowerCase()
  const h = hay.toLowerCase()
  if (h.includes(n)) return true
  let i = 0
  for (const c of h) {
    if (c === n[i]) i++
    if (i === n.length) return true
  }
  return false
}

export function CommandPalette() {
  const router = useRouter()
  const ui = useUiStore()
  const app = useAppStore()
  const campaignsQ = useCampaigns()
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const commands: Cmd[] = useMemo(() => {
    const base: Cmd[] = [
      { id: 'nav-dash', label: 'Go to Dashboard', icon: LayoutDashboard, hint: 'Home', action: () => router.push('/') },
      { id: 'nav-campaigns', label: 'Browse all campaigns', icon: FolderKanban, action: () => router.push('/campaigns') },
      { id: 'nav-new', label: 'Create new campaign', icon: Plus, hint: 'Upload', action: () => router.push('/campaigns/new') },
      { id: 'nav-settings', label: 'Open settings', icon: Settings, action: () => router.push('/settings') },
      { id: 'act-sidebar', label: ui.sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar', icon: PanelLeft, action: () => ui.toggleSidebar() },
      { id: 'act-debug', label: app.debugMode ? 'Disable debug mode' : 'Enable debug mode', icon: Bug, action: () => { app.toggleDebug(); ui.info(app.debugMode ? 'Debug OFF' : 'Debug ON', 2000) } },
      { id: 'act-reset', label: 'Clear app state', icon: RotateCcw, hint: 'Reset', action: () => { if (confirm('Clear app state (recent campaigns, prefs)?')) { app.reset(); ui.success('Cleared.', 2000) } } },
    ]
    const cs = (campaignsQ.data || []).slice(0, 12).map<Cmd>((c) => ({
      id: 'go-' + c.campaign_id,
      label: 'Open ' + c.name,
      icon: FolderKanban,
      hint: c.campaign_type || c.market || 'Campaign',
      action: () => router.push(`/campaigns/${c.campaign_id}`),
    }))
    return [...base, ...cs]
  }, [router, ui, app, campaignsQ.data])

  const filtered = useMemo(() => {
    const n = q.trim()
    if (!n) return commands
    return commands.filter((c) => fuzzy(n, c.label + ' ' + (c.hint || '')))
  }, [q, commands])

  // Cmd/Ctrl+K toggle
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        ui.togglePalette()
      } else if (e.key === 'Escape' && ui.paletteOpen) {
        ui.closePalette()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ui])

  // Focus + reset on open
  useEffect(() => {
    if (ui.paletteOpen) {
      setQ('')
      setActive(0)
      setTimeout(() => inputRef.current?.focus(), 10)
    }
  }, [ui.paletteOpen])

  useEffect(() => {
    setActive(0)
  }, [q])

  if (!ui.paletteOpen) return null

  function run(cmd: Cmd) {
    ui.closePalette()
    try {
      cmd.action()
    } catch (e) {
      ui.error('Command failed: ' + (e as Error).message)
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => (filtered.length ? (a + 1) % filtered.length : 0))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) =>
        filtered.length ? (a - 1 + filtered.length) % filtered.length : 0,
      )
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const it = filtered[active]
      if (it) run(it)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[200] grid place-items-start justify-center overflow-y-auto bg-fg/30 px-4 pt-[12vh] animate-in"
      onClick={(e) => {
        if (e.target === e.currentTarget) ui.closePalette()
      }}
    >
      <div className="flex max-h-[70vh] w-full max-w-[600px] flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-lg">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
          <Search size={15} className="text-fg-muted" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search campaigns or commands…"
            className="min-w-0 flex-1 border-0 bg-transparent text-sm text-fg outline-none placeholder:text-fg-faint"
          />
          <Kbd>ESC</Kbd>
        </div>

        {filtered.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-fg-muted">
            No matches for <span className="font-medium">"{q}"</span>
          </div>
        ) : (
          <ul className="flex-1 overflow-y-auto py-1">
            {filtered.map((c, i) => {
              const Icon = c.icon
              return (
                <li
                  key={c.id}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => run(c)}
                  className={cn(
                    'flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm',
                    i === active && 'bg-surface-muted',
                  )}
                >
                  <Icon
                    size={14}
                    className={cn(
                      'shrink-0',
                      i === active ? 'text-brand-600' : 'text-fg-muted',
                    )}
                  />
                  <span className="flex-1 truncate text-fg">{c.label}</span>
                  {c.hint && (
                    <span className="text-2xs text-fg-faint">{c.hint}</span>
                  )}
                </li>
              )
            })}
          </ul>
        )}

        <div className="flex items-center justify-between border-t border-border bg-surface-subtle px-3 py-1.5 text-2xs text-fg-muted">
          <div className="flex gap-3">
            <span className="inline-flex items-center gap-1">
              <Kbd>↑</Kbd>
              <Kbd>↓</Kbd> navigate
            </span>
            <span className="inline-flex items-center gap-1">
              <Kbd>↵</Kbd> select
            </span>
          </div>
          <span>{filtered.length} result{filtered.length === 1 ? '' : 's'}</span>
        </div>
      </div>
    </div>
  )
}
