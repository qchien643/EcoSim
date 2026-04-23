<template>
  <aside class="sidebar-memphis">
    <!-- Brand -->
    <div class="px-6 mb-8 relative z-10">
      <h1 class="text-2xl font-black tracking-tight text-black" style="font-family:'Rubik',sans-serif; font-weight:900; text-shadow: 2px 2px 0 #FFE500">EcoSim</h1>
      <p class="text-[10px] font-mono text-black tracking-widest mt-1 uppercase font-bold">Economic Simulation</p>
    </div>

    <nav class="flex-1 px-0 relative z-10">
      <!-- Pipeline Steps -->
      <p class="px-6 text-[10px] uppercase tracking-widest text-[#FF2D78] mb-2 font-black" style="font-family:'Rubik',sans-serif; letter-spacing:0.15em">● Pipeline</p>
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
              :style="isActive(item.path) ? 'color: #000' : store.isStepCompleted(item.step) ? 'color: #00C853' : ''"
            >{{ store.isStepCompleted(item.step) ? 'check_circle' : item.icon }}</span>
            <span>{{ item.label }}</span>
            <span v-if="store.isStepCompleted(item.step)" class="ml-auto text-[10px] text-[#00C853] font-mono font-bold">✓</span>
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
      <p class="px-6 text-[10px] uppercase tracking-widest text-[#FF2D78] mb-2 font-black" style="font-family:'Rubik',sans-serif; letter-spacing:0.15em">● Mở rộng</p>
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
        class="flex items-center w-full px-6 py-3 text-[#FF2D78] hover:bg-[#FF2D78] hover:text-white transition-colors duration-150 text-sm tracking-tight font-bold" style="font-family:'Rubik',sans-serif; font-weight:800">
        <span class="material-symbols-outlined mr-3">restart_alt</span>
        Phiên mới
      </button>
      <a class="flex items-center px-6 py-3 text-black hover:bg-[#FFE500] hover:text-black transition-colors duration-150 text-sm tracking-tight font-bold" style="font-family:'Rubik',sans-serif" href="#">
        <span class="material-symbols-outlined mr-3">settings</span>
        Settings
      </a>
      <div class="px-6 py-4 flex items-center border-t-[3px] border-black mt-2">
        <div class="w-10 h-10 bg-[#FFE500] flex items-center justify-center mr-3 text-xs font-black text-black border-[3px] border-black" style="box-shadow: 3px 3px 0 #FF2D78">AD</div>
        <div class="overflow-hidden">
          <p class="text-xs font-black text-black truncate" style="font-family:'Rubik',sans-serif">Admin</p>
          <p class="text-[10px] font-mono text-black/60 truncate">v2.5-WORKFLOW</p>
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
  background: #66BB6A;
  display: flex;
  flex-direction: column;
  padding-top: 1rem;
  padding-bottom: 0;
  z-index: 50;
  border-right: 4px solid #000000;
  overflow: hidden;
}

.sidebar-memphis::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    repeating-linear-gradient(
      45deg,
      transparent,
      transparent 10px,
      rgba(0,0,0,0.04) 10px,
      rgba(0,0,0,0.04) 12px
    );
  pointer-events: none;
  z-index: 0;
}

.sidebar-link {
  display: flex;
  align-items: center;
  padding: 0.625rem 1.5rem;
  border-left: 5px solid transparent;
  transition: all 0.15s ease;
  font-size: 0.875rem;
  font-family: 'Rubik', sans-serif;
  font-weight: 700;
  letter-spacing: 0;
  color: #000000;
}

.sidebar-link-active {
  color: #000000;
  border-left-color: #000000;
  background: #FFE500;
  font-weight: 800;
}

.sidebar-link-idle {
  color: #000000;
  border-left-color: transparent;
}

.sidebar-link-idle:hover {
  background: #FF2D78;
  color: #FFFFFF;
  border-left-color: #FF2D78;
}

.sidebar-link-locked {
  display: flex;
  align-items: center;
  padding: 0.625rem 1.5rem;
  border-left: 5px solid transparent;
  color: rgba(0,0,0,0.3);
  cursor: not-allowed;
  font-size: 0.875rem;
  font-family: 'Rubik', sans-serif;
  letter-spacing: 0;
}
</style>
