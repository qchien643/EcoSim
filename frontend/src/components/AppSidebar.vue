<template>
  <aside class="sidebar-memphis">
    <!-- Brand -->
    <div class="px-6 mb-8 relative z-10">
      <h1 class="text-xl font-black tracking-tight text-[#2D2D2D]" style="font-family:'Space Mono',monospace">EcoSim</h1>
      <p class="text-[10px] font-mono text-[#6B6B6B] tracking-widest mt-1 uppercase">Economic Simulation Platform</p>
    </div>

    <nav class="flex-1 px-0 relative z-10">
      <!-- Pipeline Steps -->
      <p class="px-6 text-[10px] uppercase tracking-widest text-[#9B59B6] mb-2 font-bold" style="font-family:'Space Mono',monospace">Pipeline</p>
      <ul class="space-y-0.5 mb-6">
        <li v-for="item in pipelineItems" :key="item.path">
          <router-link
            v-if="store.isStepUnlocked(item.step)"
            :to="item.path"
            :class="[
              'sidebar-link',
              isActive(item.path)
                ? 'sidebar-link-active'
                : 'sidebar-link-idle'
            ]"
          >
            <span
              class="material-symbols-outlined mr-3 text-[18px]"
              :style="isActive(item.path) ? 'color: #2D2D2D' : store.isStepCompleted(item.step) ? 'color: #66BB6A' : ''"
            >{{ store.isStepCompleted(item.step) ? 'check_circle' : item.icon }}</span>
            <span>{{ item.label }}</span>
            <span v-if="store.isStepCompleted(item.step)" class="ml-auto text-[10px] text-[#66BB6A] font-mono">✓</span>
          </router-link>
          <!-- Locked step -->
          <div
            v-else
            class="sidebar-link-locked"
            :title="'Hoàn thành bước trước để mở khóa'"
          >
            <span class="material-symbols-outlined mr-3 text-[18px]">lock</span>
            <span>{{ item.label }}</span>
          </div>
        </li>
      </ul>

      <!-- Extended Features -->
      <p class="px-6 text-[10px] uppercase tracking-widest text-[#9B59B6] mb-2 font-bold" style="font-family:'Space Mono',monospace">Mở rộng</p>
      <ul class="space-y-0.5">
        <li v-for="item in extendedItems" :key="item.path">
          <router-link
            v-if="store.isStepUnlocked(item.step)"
            :to="item.path"
            :class="[
              'sidebar-link',
              isActive(item.path)
                ? 'sidebar-link-active'
                : 'sidebar-link-idle'
            ]"
          >
            <span
              class="material-symbols-outlined mr-3 text-[18px]"
              :style="isActive(item.path) ? 'color: #2D2D2D' : ''"
            >{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </router-link>
          <!-- Locked -->
          <div
            v-else
            class="sidebar-link-locked"
            :title="'Hoàn thành Simulation để mở khóa'"
          >
            <span class="material-symbols-outlined mr-3 text-[18px]">lock</span>
            <span>{{ item.label }}</span>
          </div>
        </li>
      </ul>
    </nav>

    <div class="px-0 mt-auto relative z-10">
      <!-- New Session button -->
      <button @click="resetSession"
        class="flex items-center w-full px-6 py-3 text-[#FF8A80] hover:bg-[#FF8A80]/10 transition-colors duration-150 text-sm tracking-tight" style="font-family:'Space Mono',monospace; font-weight:700">
        <span class="material-symbols-outlined mr-3">restart_alt</span>
        Phiên mới
      </button>
      <a class="flex items-center px-6 py-3 text-[#6B6B6B] hover:bg-[#C8F7DC] hover:text-[#2D2D2D] transition-colors duration-150 text-sm tracking-tight" style="font-family:'DM Sans',sans-serif" href="#">
        <span class="material-symbols-outlined mr-3">settings</span>
        Settings
      </a>
      <div class="px-6 py-4 flex items-center border-t border-[#B2DFBC] mt-2">
        <div class="w-8 h-8 bg-[#FFE066] rounded-full flex items-center justify-center mr-3 text-xs font-bold text-[#2D2D2D] border-[1.5px] border-[#2D2D2D]">AD</div>
        <div class="overflow-hidden">
          <p class="text-xs font-bold text-[#2D2D2D] truncate" style="font-family:'Space Mono',monospace">Admin</p>
          <p class="text-[10px] font-mono text-[#9B9B9B] truncate">v2.5-WORKFLOW</p>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '../stores/appStore'

const route = useRoute()
const router = useRouter()
const store = useAppStore()

const pipelineItems = [
  { path: '/', label: 'Dashboard', icon: 'dashboard', step: 'dashboard' },
  { path: '/campaign', label: 'Campaigns', icon: 'ads_click', step: 'campaign' },
  { path: '/graph', label: 'Knowledge Graph', icon: 'hub', step: 'graph' },
  { path: '/simulation', label: 'Simulation', icon: 'biotech', step: 'simulation' },
]

const extendedItems = [
  { path: '/analysis', label: 'Analysis', icon: 'psychology', step: 'analysis' },
  { path: '/report', label: 'Reports', icon: 'analytics', step: 'report' },
  { path: '/survey', label: 'Survey', icon: 'quiz', step: 'survey' },
  { path: '/interview', label: 'Interview', icon: 'forum', step: 'interview' },
]

const isActive = (path) => {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function resetSession() {
  if (!confirm('Xóa toàn bộ dữ liệu phiên hiện tại và bắt đầu lại?')) return
  store.reset()
  router.push('/')
}
</script>

<style scoped>
.sidebar-memphis {
  position: fixed;
  left: 0;
  top: 0;
  height: 100vh;
  width: 240px;
  background: #D4EDDA;
  display: flex;
  flex-direction: column;
  padding-top: 1rem;
  padding-bottom: 0;
  z-index: 50;
  border-right: 3px solid #2D2D2D;
  overflow: hidden;
}

.sidebar-memphis::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: linear-gradient(#2D2D2D 1px, transparent 1px), linear-gradient(90deg, #2D2D2D 1px, transparent 1px);
  background-size: 24px 24px;
  opacity: 0.05;
  pointer-events: none;
  z-index: 0;
}

.sidebar-link {
  display: flex;
  align-items: center;
  padding: 0.625rem 1.5rem;
  border-left: 3px solid transparent;
  transition: all 0.2s ease;
  font-size: 0.875rem;
  font-family: 'DM Sans', sans-serif;
  font-weight: 500;
  letter-spacing: -0.01em;
  color: #4A4A4A;
}

.sidebar-link-active {
  color: #2D2D2D;
  border-left-color: #2D2D2D;
  background: #FFE066;
  font-weight: 700;
}

.sidebar-link-idle {
  color: #4A4A4A;
  border-left-color: transparent;
}

.sidebar-link-idle:hover {
  background: #C8F7DC;
  color: #2D2D2D;
  border-left-color: #66BB6A;
}

.sidebar-link-locked {
  display: flex;
  align-items: center;
  padding: 0.625rem 1.5rem;
  border-left: 3px solid transparent;
  color: #B2DFBC;
  cursor: not-allowed;
  font-size: 0.875rem;
  font-family: 'DM Sans', sans-serif;
  letter-spacing: -0.01em;
}
</style>
