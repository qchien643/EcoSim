'use client'

import { create } from 'zustand'

export type ToastType = 'info' | 'success' | 'warning' | 'error'

export interface Toast {
  id: number
  type: ToastType
  msg: string
  ttl: number
}

interface UiState {
  // Sidebar
  sidebarCollapsed: boolean
  sidebarMobileOpen: boolean
  toggleSidebar: () => void
  setSidebarCollapsed: (v: boolean) => void
  openMobileDrawer: () => void
  closeMobileDrawer: () => void

  // Detail pane (right slide-in)
  detailPaneOpen: boolean
  openDetailPane: () => void
  closeDetailPane: () => void

  // Command palette
  paletteOpen: boolean
  openPalette: () => void
  closePalette: () => void
  togglePalette: () => void

  // Toasts
  toasts: Toast[]
  toast: (msg: string, type?: ToastType, ttl?: number) => number
  info: (m: string, ttl?: number) => number
  success: (m: string, ttl?: number) => number
  warning: (m: string, ttl?: number) => number
  error: (m: string, ttl?: number) => number
  dismiss: (id: number) => void

  // In-flight long-running ops — survive route navigation (mutation state
  // của react-query bị reset khi component unmount). Track ở đây để banner
  // "đang build/đang prepare" hiển thị xuyên tabs.
  buildingCampaigns: string[]   // campaign_ids đang build KG
  startBuilding: (campaignId: string) => void
  stopBuilding: (campaignId: string) => void
  isBuilding: (campaignId: string) => boolean
}

let _id = 1

export const useUiStore = create<UiState>((set, get) => ({
  sidebarCollapsed: false,
  sidebarMobileOpen: false,
  toggleSidebar: () => set({ sidebarCollapsed: !get().sidebarCollapsed }),
  setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),
  openMobileDrawer: () => set({ sidebarMobileOpen: true }),
  closeMobileDrawer: () => set({ sidebarMobileOpen: false }),

  detailPaneOpen: false,
  openDetailPane: () => set({ detailPaneOpen: true }),
  closeDetailPane: () => set({ detailPaneOpen: false }),

  paletteOpen: false,
  openPalette: () => set({ paletteOpen: true }),
  closePalette: () => set({ paletteOpen: false }),
  togglePalette: () => set({ paletteOpen: !get().paletteOpen }),

  toasts: [],
  toast: (msg, type = 'info', ttl = 5000) => {
    const id = _id++
    set({ toasts: [...get().toasts, { id, type, msg, ttl }] })
    if (ttl > 0) setTimeout(() => get().dismiss(id), ttl)
    return id
  },
  info: (m, ttl) => get().toast(m, 'info', ttl),
  success: (m, ttl) => get().toast(m, 'success', ttl),
  warning: (m, ttl) => get().toast(m, 'warning', ttl),
  error: (m, ttl = 0) => get().toast(m, 'error', ttl),
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),

  buildingCampaigns: [],
  startBuilding: (cid) => {
    const cur = get().buildingCampaigns
    if (cur.includes(cid)) return
    set({ buildingCampaigns: [...cur, cid] })
  },
  stopBuilding: (cid) =>
    set({ buildingCampaigns: get().buildingCampaigns.filter((c) => c !== cid) }),
  isBuilding: (cid) => get().buildingCampaigns.includes(cid),
}))
