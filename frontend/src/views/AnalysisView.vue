<template>
  <div class="flex-1 flex flex-col overflow-hidden">
    <!-- Header -->
    <header class="h-20 px-8 flex items-center justify-between border-b border-[#E0DDD5]/30 bg-[#F5F0E8]/50 flex-shrink-0">
      <div class="flex flex-col">
        <div class="flex items-center gap-3">
          <span class="material-symbols-outlined text-[#D5C4F7]" style="font-size: 24px;">analytics</span>
          <h1 class="text-2xl font-bold tracking-tight text-[#2D2D2D]">Campaign Analysis</h1>
          <span class="ml-4 px-2 py-0.5 bg-[#FBF8F3] text-[#6B6B6B] font-mono text-[10px] uppercase border border-[#E0DDD5]/50">Step 4b of 6</span>
          <span v-if="cachedAt" class="px-2 py-0.5 bg-[#66BB6A]/10 text-[#66BB6A] font-mono text-[10px] border border-[#66BB6A]/30 flex items-center gap-1">
            <span class="material-symbols-outlined" style="font-size: 12px;">cached</span>
            Saved {{ cachedAt }}
          </span>
        </div>
        <span class="mt-1 font-mono text-xs text-[#6B6B6B]">Step-by-step data processing pipeline with sentiment analysis</span>
      </div>
      <button
        @click="runPipeline"
        :disabled="running || !simId"
        class="bg-[#D5C4F7] hover:bg-[#D5C4F7]/90 text-white px-6 py-2.5 font-bold text-sm tracking-tight transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <div v-if="running" class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
        <span v-else class="material-symbols-outlined" style="font-variation-settings: 'wght' 700;">play_arrow</span>
        {{ running ? 'ANALYZING...' : 'RUN ANALYSIS' }}
      </button>
    </header>

    <!-- Error -->
    <div v-if="error" class="mx-8 mt-4 bg-[#FBF8F3] border-l-2 border-[#FF8A80] px-6 py-3 flex items-center gap-3">
      <span class="material-symbols-outlined text-[#FF8A80] text-sm">error</span>
      <span class="text-xs font-mono text-[#FF8A80]">{{ error }}</span>
    </div>

    <!-- Pipeline Steps -->
    <div class="flex-1 overflow-y-auto p-8 space-y-4 bg-[#F5F0E8]">

      <!-- Step 1: Data Extraction -->
      <section class="bg-[#FFFFFF] border border-[#E0DDD5]/40 overflow-hidden">
        <div class="px-6 py-4 border-b border-[#E0DDD5]/30 flex items-center gap-3 cursor-pointer" @click="toggleStep(0)">
          <StepBadge :step="1" :status="steps[0].status" />
          <div class="flex-1">
            <h3 class="text-sm font-bold text-[#2D2D2D]">Data Extraction</h3>
            <p class="text-[10px] font-mono text-[#6B6B6B]">Extract raw metrics from simulation database</p>
          </div>
          <span v-if="steps[0].duration" class="font-mono text-[10px] text-[#6B6B6B]">{{ steps[0].duration }}ms</span>
          <span class="material-symbols-outlined text-sm text-[#6B6B6B] transition-transform" :class="{ 'rotate-180': steps[0].expanded }">expand_more</span>
        </div>
        <div v-if="steps[0].expanded && steps[0].data" class="p-6 grid grid-cols-4 gap-4">
          <div v-for="(item, key) in steps[0].data" :key="key" class="bg-[#FBF8F3] p-4 border border-[#E0DDD5]/20">
            <span class="font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest block mb-1">{{ formatKey(key) }}</span>
            <span class="text-xl font-bold text-[#66BB6A] font-sans">{{ item }}</span>
          </div>
        </div>
      </section>

      <!-- Step 2: Engagement Rate -->
      <section class="bg-[#FFFFFF] border border-[#E0DDD5]/40 overflow-hidden">
        <div class="px-6 py-4 border-b border-[#E0DDD5]/30 flex items-center gap-3 cursor-pointer" @click="toggleStep(1)">
          <StepBadge :step="2" :status="steps[1].status" />
          <div class="flex-1">
            <h3 class="text-sm font-bold text-[#2D2D2D]">Engagement Rate Calculation</h3>
            <p class="text-[10px] font-mono text-[#6B6B6B]">ER = (likes + comments) / (agents × rounds) × 100</p>
          </div>
          <span v-if="steps[1].data" class="px-3 py-1 font-mono text-xs font-bold"
                :class="erClass">{{ steps[1].data?.engagement_rate }}% — {{ steps[1].data?.rating }}</span>
          <span v-if="steps[1].duration" class="font-mono text-[10px] text-[#6B6B6B]">{{ steps[1].duration }}ms</span>
          <span class="material-symbols-outlined text-sm text-[#6B6B6B] transition-transform" :class="{ 'rotate-180': steps[1].expanded }">expand_more</span>
        </div>
        <div v-if="steps[1].expanded && steps[1].data" class="p-6">
          <div class="grid grid-cols-3 gap-4">
            <div class="bg-[#FBF8F3] p-4 border border-[#E0DDD5]/20">
              <span class="font-mono text-[10px] text-[#6B6B6B] uppercase block mb-1">Total Interactions</span>
              <span class="text-xl font-bold text-[#2D2D2D]">{{ steps[1].data.total_interactions }}</span>
            </div>
            <div class="bg-[#FBF8F3] p-4 border border-[#E0DDD5]/20">
              <span class="font-mono text-[10px] text-[#6B6B6B] uppercase block mb-1">Agents</span>
              <span class="text-xl font-bold text-[#2D2D2D]">{{ steps[1].data.agents }}</span>
            </div>
            <div class="bg-[#FBF8F3] p-4 border border-[#E0DDD5]/20">
              <span class="font-mono text-[10px] text-[#6B6B6B] uppercase block mb-1">Engagement Rate</span>
              <span class="text-2xl font-bold text-[#66BB6A]">{{ steps[1].data.engagement_rate }}%</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Step 3: Sentiment Analysis (Detailed) -->
      <section class="bg-[#FFFFFF] border-2 overflow-hidden" :class="steps[2].status === 'running' ? 'border-[#D5C4F7] animate-pulse' : 'border-[#E0DDD5]/40'">
        <div class="px-6 py-4 border-b border-[#E0DDD5]/30 flex items-center gap-3 cursor-pointer" @click="toggleStep(2)">
          <StepBadge :step="3" :status="steps[2].status" />
          <div class="flex-1">
            <h3 class="text-sm font-bold text-[#2D2D2D]">Sentiment Analysis</h3>
            <p class="text-[10px] font-mono text-[#6B6B6B]">
              Model: cardiffnlp/twitter-roberta-base-sentiment — classify each comment → positive / neutral / negative
            </p>
          </div>
          <span v-if="steps[2].data" class="px-3 py-1 font-mono text-xs font-bold"
                :class="nssClass">NSS: {{ steps[2].data?.nss }}</span>
          <span v-if="steps[2].duration" class="font-mono text-[10px] text-[#6B6B6B]">{{ steps[2].duration }}ms</span>
          <span class="material-symbols-outlined text-sm text-[#6B6B6B] transition-transform" :class="{ 'rotate-180': steps[2].expanded }">expand_more</span>
        </div>
        <div v-if="steps[2].expanded && steps[2].data" class="p-6 space-y-6">
          <!-- Sentiment Distribution Bar -->
          <div>
            <span class="font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest block mb-3">Distribution</span>
            <div class="flex h-8 rounded overflow-hidden">
              <div class="bg-[#66BB6A] flex items-center justify-center text-[10px] font-mono font-bold text-[#F5F0E8] transition-all"
                   :style="{ width: steps[2].data.positive_pct + '%' }">
                {{ steps[2].data.positive_pct }}%
              </div>
              <div class="bg-[#6B6B6B] flex items-center justify-center text-[10px] font-mono font-bold text-[#F5F0E8] transition-all"
                   :style="{ width: steps[2].data.neutral_pct + '%' }">
                {{ steps[2].data.neutral_pct }}%
              </div>
              <div class="bg-[#FF8A80] flex items-center justify-center text-[10px] font-mono font-bold text-white transition-all"
                   :style="{ width: steps[2].data.negative_pct + '%' }">
                {{ steps[2].data.negative_pct }}%
              </div>
            </div>
            <div class="flex justify-between mt-2 font-mono text-[10px] text-[#6B6B6B]">
              <span>🟢 Positive: {{ steps[2].data.distribution?.positive || 0 }}</span>
              <span>⚪ Neutral: {{ steps[2].data.distribution?.neutral || 0 }}</span>
              <span>🔴 Negative: {{ steps[2].data.distribution?.negative || 0 }}</span>
            </div>
          </div>

          <!-- NSS Gauge -->
          <div class="grid grid-cols-3 gap-4">
            <div class="bg-[#FBF8F3] p-4 border border-[#E0DDD5]/20 text-center">
              <span class="font-mono text-[10px] text-[#6B6B6B] uppercase block mb-2">Net Sentiment Score</span>
              <span class="text-3xl font-bold" :class="steps[2].data.nss >= 0 ? 'text-[#66BB6A]' : 'text-[#FF8A80]'">
                {{ steps[2].data.nss > 0 ? '+' : '' }}{{ steps[2].data.nss }}
              </span>
              <span class="block font-mono text-[9px] text-[#6B6B6B] mt-1">Range: -100 to +100</span>
            </div>
            <div class="bg-[#FBF8F3] p-4 border border-[#E0DDD5]/20 text-center">
              <span class="font-mono text-[10px] text-[#6B6B6B] uppercase block mb-2">Total Comments</span>
              <span class="text-3xl font-bold text-[#2D2D2D]">{{ steps[2].data.total_comments }}</span>
            </div>
            <div class="bg-[#FBF8F3] p-4 border border-[#E0DDD5]/20 text-center">
              <span class="font-mono text-[10px] text-[#6B6B6B] uppercase block mb-2">Model</span>
              <span class="text-xs font-mono text-[#D5C4F7] break-all">{{ steps[2].data.model || 'N/A' }}</span>
            </div>
          </div>

          <!-- Comment Details Table -->
          <div v-if="steps[2].data.details?.length">
            <span class="font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest block mb-3">Comment Classification Details</span>
            <div class="max-h-[300px] overflow-y-auto border border-[#E0DDD5]/20">
              <table class="w-full text-xs">
                <thead class="sticky top-0 bg-[#FBF8F3]">
                  <tr class="text-[#6B6B6B] font-mono text-[10px] uppercase">
                    <th class="px-3 py-2 text-left">Post</th>
                    <th class="px-3 py-2 text-left">Comment</th>
                    <th class="px-3 py-2 text-center">Sentiment</th>
                    <th class="px-3 py-2 text-right">Score</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(d, i) in steps[2].data.details" :key="i"
                      class="border-t border-[#E0DDD5]/20 hover:bg-[#FBF8F3]/50">
                    <td class="px-3 py-2 font-mono text-[#6B6B6B]">#{{ d.post_id }}</td>
                    <td class="px-3 py-2 text-[#2D2D2D] max-w-[400px] truncate">{{ d.content }}</td>
                    <td class="px-3 py-2 text-center">
                      <span class="px-2 py-0.5 font-mono text-[9px] uppercase border"
                            :class="sentimentClass(d.sentiment)">{{ d.sentiment }}</span>
                    </td>
                    <td class="px-3 py-2 text-right font-mono text-[#6B6B6B]">{{ d.score }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <!-- Step 4: Per-Round Breakdown -->
      <section class="bg-[#FFFFFF] border border-[#E0DDD5]/40 overflow-hidden">
        <div class="px-6 py-4 border-b border-[#E0DDD5]/30 flex items-center gap-3 cursor-pointer" @click="toggleStep(3)">
          <StepBadge :step="4" :status="steps[3].status" />
          <div class="flex-1">
            <h3 class="text-sm font-bold text-[#2D2D2D]">Per-Round Breakdown</h3>
            <p class="text-[10px] font-mono text-[#6B6B6B]">Metrics and sentiment trend across simulation rounds</p>
          </div>
          <span v-if="steps[3].duration" class="font-mono text-[10px] text-[#6B6B6B]">{{ steps[3].duration }}ms</span>
          <span class="material-symbols-outlined text-sm text-[#6B6B6B] transition-transform" :class="{ 'rotate-180': steps[3].expanded }">expand_more</span>
        </div>
        <div v-if="steps[3].expanded && steps[3].data?.length" class="p-6">
          <div class="overflow-x-auto border border-[#E0DDD5]/20">
            <table class="w-full text-xs">
              <thead class="bg-[#FBF8F3]">
                <tr class="text-[#6B6B6B] font-mono text-[10px] uppercase">
                  <th class="px-3 py-2 text-left">Round</th>
                  <th class="px-3 py-2 text-center">Posts</th>
                  <th class="px-3 py-2 text-center">Likes</th>
                  <th class="px-3 py-2 text-center">Comments</th>
                  <th class="px-3 py-2 text-center">😊</th>
                  <th class="px-3 py-2 text-center">😐</th>
                  <th class="px-3 py-2 text-center">😞</th>
                  <th class="px-3 py-2 text-center">NSS</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in steps[3].data" :key="r.round" class="border-t border-[#E0DDD5]/20 hover:bg-[#FBF8F3]/50">
                  <td class="px-3 py-2 font-mono font-bold text-[#D5C4F7]">R{{ r.round }}</td>
                  <td class="px-3 py-2 text-center text-[#2D2D2D]">{{ r.posts }}</td>
                  <td class="px-3 py-2 text-center text-[#2D2D2D]">{{ r.likes }}</td>
                  <td class="px-3 py-2 text-center text-[#2D2D2D]">{{ r.comments }}</td>
                  <td class="px-3 py-2 text-center text-[#66BB6A]">{{ r.sentiment?.positive || 0 }}</td>
                  <td class="px-3 py-2 text-center text-[#6B6B6B]">{{ r.sentiment?.neutral || 0 }}</td>
                  <td class="px-3 py-2 text-center text-[#FF8A80]">{{ r.sentiment?.negative || 0 }}</td>
                  <td class="px-3 py-2 text-center font-mono font-bold"
                      :class="r.nss >= 0 ? 'text-[#66BB6A]' : 'text-[#FF8A80]'">{{ r.nss }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- Step 5: Campaign Score -->
      <section class="bg-[#FFFFFF] border border-[#E0DDD5]/40 overflow-hidden">
        <div class="px-6 py-4 border-b border-[#E0DDD5]/30 flex items-center gap-3 cursor-pointer" @click="toggleStep(4)">
          <StepBadge :step="5" :status="steps[4].status" />
          <div class="flex-1">
            <h3 class="text-sm font-bold text-[#2D2D2D]">Campaign Effectiveness Score</h3>
            <p class="text-[10px] font-mono text-[#6B6B6B]">Weighted composite score: engagement × sentiment × growth × diversity</p>
          </div>
          <span v-if="steps[4].data" class="px-3 py-1 font-mono text-sm font-bold"
                :class="scoreClass">{{ steps[4].data?.campaign_score }} — {{ steps[4].data?.rating }}</span>
          <span v-if="steps[4].duration" class="font-mono text-[10px] text-[#6B6B6B]">{{ steps[4].duration }}ms</span>
          <span class="material-symbols-outlined text-sm text-[#6B6B6B] transition-transform" :class="{ 'rotate-180': steps[4].expanded }">expand_more</span>
        </div>
        <div v-if="steps[4].expanded && steps[4].data" class="p-6">
          <!-- Score Visualization -->
          <div class="text-center mb-6">
            <div class="inline-block relative">
              <div class="w-32 h-32 rounded-full border-8 flex items-center justify-center"
                   :class="scoreBorderClass">
                <span class="text-3xl font-bold text-[#2D2D2D]">{{ (steps[4].data.campaign_score * 100).toFixed(0) }}</span>
              </div>
              <span class="block mt-2 font-mono text-xs uppercase tracking-widest"
                    :class="scoreClass">{{ steps[4].data.rating }}</span>
            </div>
          </div>

          <!-- Component Breakdown -->
          <div class="grid grid-cols-4 gap-3">
            <div v-for="(val, key) in steps[4].data.components" :key="key"
                 class="bg-[#FBF8F3] p-3 border border-[#E0DDD5]/20 text-center">
              <span class="font-mono text-[9px] text-[#6B6B6B] uppercase block mb-1">{{ formatKey(key) }}</span>
              <div class="h-2 bg-[#E0DDD5] rounded-full mb-2">
                <div class="h-full bg-[#D5C4F7] rounded-full transition-all" :style="{ width: (val * 100) + '%' }"></div>
              </div>
              <span class="font-mono text-sm font-bold text-[#2D2D2D]">{{ (val * 100).toFixed(0) }}%</span>
            </div>
          </div>
        </div>
      </section>

    </div>

    <!-- Bottom Nav -->
    <footer class="h-12 bg-[#FBF8F3] border-t border-[#E0DDD5]/30 px-8 flex items-center justify-between flex-shrink-0">
      <router-link to="/simulation" class="flex items-center gap-2 text-[#6B6B6B] hover:text-[#2D2D2D] transition-colors group">
        <span class="material-symbols-outlined text-sm group-hover:-translate-x-1 transition-transform">arrow_back</span>
        <span class="font-mono text-[10px] uppercase tracking-widest">Back: Simulation</span>
      </router-link>
      <router-link to="/report" class="flex items-center gap-2 text-[#D5C4F7] hover:text-[#D5C4F7]/80 transition-colors group">
        <span class="font-mono text-[10px] uppercase tracking-widest">Next: Full Report</span>
        <span class="material-symbols-outlined text-sm group-hover:translate-x-1 transition-transform">arrow_forward</span>
      </router-link>
    </footer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { reportApi } from '../api/client'
import { useAppStore } from '../stores/appStore'

const store = useAppStore()
const error = ref('')
const running = ref(false)
const simId = ref('')
const numRounds = ref(1)
const cachedAt = ref('')

// Pipeline steps
const steps = reactive([
  { name: 'extraction',  status: 'pending', data: null, duration: null, expanded: false },
  { name: 'engagement',  status: 'pending', data: null, duration: null, expanded: false },
  { name: 'sentiment',   status: 'pending', data: null, duration: null, expanded: true },  // Start expanded
  { name: 'per_round',   status: 'pending', data: null, duration: null, expanded: false },
  { name: 'score',       status: 'pending', data: null, duration: null, expanded: false },
])

function toggleStep(idx) {
  steps[idx].expanded = !steps[idx].expanded
}

function formatKey(key) {
  return key.replace(/_/g, ' ').replace(/norm$/, '').trim()
}

function sentimentClass(label) {
  if (label === 'positive') return 'bg-[#66BB6A]/15 text-[#66BB6A] border-[#66BB6A]/30'
  if (label === 'negative') return 'bg-[#FF8A80]/15 text-[#FF8A80] border-[#FF8A80]/30'
  return 'bg-[#6B6B6B]/15 text-[#6B6B6B] border-[#6B6B6B]/30'
}

const erClass = computed(() => {
  const r = steps[1].data?.rating
  if (r === 'EXCELLENT') return 'bg-[#66BB6A]/15 text-[#66BB6A] border border-[#66BB6A]/30'
  if (r === 'GOOD') return 'bg-[#66BB6A]/15 text-[#66BB6A] border border-[#66BB6A]/30'
  if (r === 'AVERAGE') return 'bg-[#FFE066]/15 text-[#FFE066] border border-[#FFE066]/30'
  return 'bg-[#FF8A80]/15 text-[#FF8A80] border border-[#FF8A80]/30'
})

const nssClass = computed(() => {
  const nss = steps[2].data?.nss || 0
  if (nss >= 30) return 'bg-[#66BB6A]/15 text-[#66BB6A] border border-[#66BB6A]/30'
  if (nss >= 0) return 'bg-[#FFE066]/15 text-[#FFE066] border border-[#FFE066]/30'
  return 'bg-[#FF8A80]/15 text-[#FF8A80] border border-[#FF8A80]/30'
})

const scoreClass = computed(() => {
  const r = steps[4].data?.rating
  if (r === 'EXCELLENT') return 'text-[#66BB6A]'
  if (r === 'GOOD') return 'text-[#66BB6A]'
  if (r === 'ACCEPTABLE') return 'text-[#FFE066]'
  return 'text-[#FF8A80]'
})

const scoreBorderClass = computed(() => {
  const r = steps[4].data?.rating
  if (r === 'EXCELLENT') return 'border-[#66BB6A]'
  if (r === 'GOOD') return 'border-[#66BB6A]'
  if (r === 'ACCEPTABLE') return 'border-[#FFE066]'
  return 'border-[#FF8A80]'
})

// Pipeline runner
async function runStep(idx, apiFn) {
  steps[idx].status = 'running'
  const t0 = Date.now()
  try {
    const res = await apiFn()
    steps[idx].data = res.data
    steps[idx].status = 'done'
    steps[idx].duration = Date.now() - t0
    steps[idx].expanded = true
  } catch (e) {
    steps[idx].status = 'error'
    steps[idx].duration = Date.now() - t0
    throw e
  }
}

async function runPipeline() {
  running.value = true
  error.value = ''
  cachedAt.value = ''

  // Reset all steps
  for (const s of steps) {
    s.status = 'pending'
    s.data = null
    s.duration = null
  }

  try {
    // Single API call — returns all data including sentiment analysis
    // Backend auto-saves to analysis_results.json
    await runStep(0, () => reportApi.summary(simId.value, numRounds.value))
    const fullSummary = steps[0].data
    
    // Distribute data across all steps
    populateStepsFromData(fullSummary)
    // Keep step 0 timing from runStep
    steps[0].data = fullSummary.quantitative

    // Update cached badge
    cachedAt.value = new Date().toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })
    store.completeStep('analysis')

  } catch (e) {
    error.value = e.response?.data?.detail || e.message || 'Pipeline failed'
  } finally {
    running.value = false
  }
}

// Populate steps from cached/fresh data
function populateStepsFromData(data) {
  // Step 1: Data Extraction
  steps[0].data = data.quantitative
  steps[0].status = 'done'
  steps[0].expanded = true

  // Step 2: Engagement Rate
  steps[1].data = data.engagement
  steps[1].status = 'done'
  steps[1].expanded = true

  // Step 3: Sentiment Analysis
  steps[2].data = data.sentiment
  steps[2].status = 'done'
  steps[2].expanded = true

  // Step 4: Per-Round Breakdown
  steps[3].data = data.per_round || []
  steps[3].status = steps[3].data.length ? 'done' : 'skipped'
  steps[3].expanded = steps[3].data.length > 0

  // Step 5: Campaign Score
  steps[4].data = data.campaign_score
  steps[4].status = 'done'
  steps[4].expanded = true
}

// Auto-detect simulation ID and load cached results
onMounted(async () => {
  // Use simId from store (set by SimulationView when simulation completes)
  simId.value = store.simId || ''
  if (!simId.value) {
    try {
      const res = await reportApi.listSims()
      const sims = res.data?.simulations || []
      const withDb = sims.find(s => s.has_db)
      if (withDb) {
        simId.value = withDb.sim_id
        store.setSimId(withDb.sim_id)
      }
    } catch (e) {
      console.warn('Could not list simulations:', e.message)
    }
  }

  // Load cached results if available
  if (simId.value) {
    try {
      const cached = await reportApi.cachedAnalysis(simId.value)
      if (cached.data?.cached && cached.data.results) {
        populateStepsFromData(cached.data.results)
        // Format timestamp
        const ts = cached.data.timestamp
        if (ts) {
          const d = new Date(ts)
          cachedAt.value = d.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })
        }
      }
    } catch (e) {
      console.warn('No cached analysis:', e.message)
    }
  }
})

// Step Badge component (render function — no runtime template needed)
import { h as _h } from 'vue'

const StepBadge = {
  props: ['step', 'status'],
  setup(props) {
    return () => {
      const s = props.status
      let cls = 'bg-[#E0DDD5]/50 text-[#6B6B6B] border border-[#E0DDD5]'
      if (s === 'done') cls = 'bg-[#66BB6A]/20 text-[#66BB6A] border border-[#66BB6A]/30'
      else if (s === 'running') cls = 'bg-[#D5C4F7]/20 text-[#D5C4F7] border border-[#D5C4F7]/30'
      else if (s === 'error') cls = 'bg-[#FF8A80]/20 text-[#FF8A80] border border-[#FF8A80]/30'

      let inner
      if (s === 'done') inner = _h('span', { class: 'material-symbols-outlined text-sm' }, 'check')
      else if (s === 'running') inner = _h('span', { class: 'material-symbols-outlined text-sm animate-spin' }, 'progress_activity')
      else if (s === 'error') inner = _h('span', { class: 'material-symbols-outlined text-sm' }, 'close')
      else inner = String(props.step)

      return _h('div', {
        class: `w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold font-mono shrink-0 ${cls}`
      }, [inner])
    }
  }
}
</script>

<style scoped>
/* ===== MEMPHIS ANALYSIS OVERRIDES ===== */
.flex-1.flex.flex-col.overflow-hidden {
  font-family: 'DM Sans', system-ui, sans-serif;
  position: relative;
}

.flex-1.flex.flex-col.overflow-hidden::before {
  content: '';
  position: fixed;
  bottom: 25%;
  right: 10%;
  width: 100px;
  height: 100px;
  background-image: radial-gradient(circle, #D5C4F7 2px, transparent 2px);
  background-size: 14px 14px;
  opacity: 0.05;
  pointer-events: none;
  animation: aFloat 7s ease-in-out infinite;
  z-index: 0;
}

@keyframes aFloat {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(-8px, 12px); }
}

header {
  border-bottom: 3px solid #D5C4F7 !important;
  position: relative;
  z-index: 2;
}

header::after {
  content: '';
  position: absolute;
  bottom: -11px;
  left: 0; right: 0;
  height: 8px;
  background: linear-gradient(135deg, #F5F0E8 33.33%, transparent 33.33%) 0 0,
              linear-gradient(225deg, #F5F0E8 33.33%, transparent 33.33%) 0 0;
  background-size: 12px 8px;
  background-repeat: repeat-x;
  z-index: 2;
}

h1, h2, h3 {
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700 !important;
}

/* Run Analysis button */
button[class*="bg-[#D5C4F7]"] {
  border-radius: 0 !important;
  border: 2px solid #F5F0E8 !important;
  box-shadow: 4px 4px 0 #9B59B6;
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

button[class*="bg-[#D5C4F7]"]:hover {
  transform: translate(-2px, -2px);
  box-shadow: 6px 6px 0 #9B59B6;
}

button[class*="bg-[#D5C4F7]"]:active {
  transform: translate(2px, 2px);
  box-shadow: none;
}

/* Pipeline sections — Memphis cards */
section[class*="bg-[#FFFFFF]"] {
  border: 2px solid #E0DDD5 !important;
  box-shadow: 3px 3px 0 rgba(45, 43, 85, 0.3);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

section[class*="bg-[#FFFFFF]"]:hover {
  box-shadow: 4px 4px 0 #D5C4F7;
}

/* Data metric cards */
div[class*="bg-[#FBF8F3]"][class*="border"] {
  border: 2px solid #E0DDD5 !important;
  box-shadow: 2px 2px 0 rgba(45, 43, 85, 0.3);
}

/* Step badges — square */
div[class*="rounded-full"][class*="w-8"][class*="h-8"] {
  border-radius: 0 !important;
  box-shadow: 2px 2px 0 rgba(132, 94, 194, 0.3);
}

/* Sentiment distribution bar — square Memphis */
.flex.h-8 {
  border-radius: 0 !important;
  overflow: hidden;
}

/* Score circle — square Memphis */
div[class*="rounded-full"][class*="w-32"] {
  border-radius: 0 !important;
  box-shadow: 4px 4px 0 #9B59B6;
}

/* Progress bars — square */
div[class*="rounded-full"][class*="bg-[#E0DDD5]"] {
  border-radius: 0 !important;
}

div[class*="rounded-full"][class*="bg-[#D5C4F7]"] {
  border-radius: 0 !important;
}

/* Tables — Memphis header */
thead {
  border-bottom: 2px solid #D5C4F7 !important;
}

th {
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700;
  color: #FFE066 !important;
}

/* Error bars */
div[class*="border-l-2"][class*="border-[#FF8A80]"] {
  border: 2px solid #FF8A80 !important;
  border-left-width: 4px !important;
  box-shadow: 3px 3px 0 rgba(255, 107, 107, 0.2);
}

/* Footer */
footer {
  border-top: 3px solid #D5C4F7 !important;
}

/* Spinners */
div[class*="rounded-full"][class*="animate-spin"] {
  border-radius: 0 !important;
}

/* Sentiment badges — square */
span[class*="py-0.5"][class*="text-[9px]"] {
  border-radius: 0 !important;
}
</style>
