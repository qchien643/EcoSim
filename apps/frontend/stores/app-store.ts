'use client'

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

/**
 * App-level persistent state.
 *
 * Campaign-centric IA: routes are /campaigns/[id]/..., so the store doesn't
 * need an "active campaign" — the URL is the source of truth. We keep:
 *  - recentCampaignIds — for sidebar quick access
 *  - lastVisitedCampaignId — to redirect to last workspace on root
 *  - debugMode — power-user toggle
 */
interface AppState {
  recentCampaignIds: string[]
  lastVisitedCampaignId: string | null
  debugMode: boolean

  // Actions
  pushRecentCampaign: (id: string) => void
  clearRecent: () => void
  setLastVisited: (id: string | null) => void
  toggleDebug: () => void
  reset: () => void
}

const RECENT_LIMIT = 8

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      recentCampaignIds: [],
      lastVisitedCampaignId: null,
      debugMode: false,

      pushRecentCampaign: (id) => {
        if (!id) return
        const next = [id, ...get().recentCampaignIds.filter((x) => x !== id)]
        set({
          recentCampaignIds: next.slice(0, RECENT_LIMIT),
          lastVisitedCampaignId: id,
        })
      },

      clearRecent: () =>
        set({ recentCampaignIds: [], lastVisitedCampaignId: null }),

      setLastVisited: (id) => set({ lastVisitedCampaignId: id }),

      toggleDebug: () => set({ debugMode: !get().debugMode }),

      reset: () =>
        set({
          recentCampaignIds: [],
          lastVisitedCampaignId: null,
          debugMode: false,
        }),
    }),
    {
      name: 'ecosim.app',
      storage: createJSONStorage(() => localStorage),
    },
  ),
)
