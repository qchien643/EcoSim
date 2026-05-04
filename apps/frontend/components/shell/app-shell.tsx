'use client'

import { Sidebar } from './sidebar'
import { TopBar } from './topbar'
import { CommandPalette } from './command-palette'
import { ToastHost } from './toast-host'
import { useUiStore } from '@/stores/ui-store'
import { useHydrated } from '@/hooks/use-hydration'

/**
 * App shell — simple CSS Grid (sidebar 256px | main 1fr) on desktop,
 * single column on mobile. No arbitrary `theme()` resolution, no
 * custom spacing tokens — all literal pixel values so CSS can never
 * fail to compile into the final stylesheet.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const ui = useUiStore()
  const hydrated = useHydrated()
  // Server / first client paint: always "expanded" so hydration matches.
  const collapsed = hydrated && ui.sidebarCollapsed

  const sidebarWidth = collapsed ? 56 : 256

  return (
    <div
      className="relative flex min-h-screen w-full bg-white"
      style={{ ['--sb-w' as string]: `${sidebarWidth}px` }}
    >
      {/* Sidebar: fixed position on desktop, slide-in drawer on mobile */}
      <Sidebar />

      {/* Main column — offset left by sidebar width on md+, full width below */}
      <div className="flex min-h-screen min-w-0 flex-1 flex-col md:ml-[var(--sb-w)]">
        <TopBar />
        <main className="flex flex-1 flex-col overflow-y-auto bg-white">
          {children}
        </main>
      </div>

      <CommandPalette />
      <ToastHost />
    </div>
  )
}
