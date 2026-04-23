<template>
  <div class="flex-1 flex flex-col overflow-hidden">
    <!-- TopAppBar -->
    <header class="flex justify-between items-center w-full px-6 py-4 bg-[#F5F0E8] border-b border-[#E0DDD5] z-40 flex-shrink-0">
      <div class="flex items-center gap-4">
        <span class="material-symbols-outlined text-[#66BB6A]">bar_chart</span>
        <div>
          <h2 class="text-lg font-bold text-[#2D2D2D] font-sans">Economic Report</h2>
          <p class="text-xs font-mono text-[#6B6B6B] tracking-tight">{{ store.simId || 'No simulation selected' }}</p>
        </div>
      </div>
      <div class="flex items-center gap-4">
        <button @click="generateReport" :disabled="generating || !store.simId"
          class="font-mono text-xs font-bold bg-[#66BB6A] text-[#00382a] px-4 py-2 hover:bg-[#66BB6A]/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2">
          <div v-if="generating" class="w-3 h-3 border-2 border-[#00382a] border-t-transparent rounded-full animate-spin"></div>
          {{ generating ? 'Generating...' : 'Generate Report' }}
        </button>
      </div>
    </header>

    <!-- Error -->
    <div v-if="error" class="mx-6 mt-4 bg-[#FBF8F3] border-l-2 border-[#FF8A80] px-6 py-3 flex items-center gap-3 flex-shrink-0">
      <span class="material-symbols-outlined text-[#FF8A80] text-sm">error</span>
      <span class="text-xs font-mono text-[#FF8A80]">{{ error }}</span>
    </div>

    <!-- Content Canvas -->
    <div class="flex-1 overflow-y-auto p-6 space-y-6 bg-[#F5F0E8] pb-24">

      <!-- Analysis Summary Panel -->
      <section v-if="analysisData" class="bg-[#FFFFFF] border border-[#E0DDD5]">
        <div class="px-5 py-3 border-b border-[#E0DDD5] flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="material-symbols-outlined text-xs text-[#D5C4F7]">analytics</span>
            <span class="text-[10px] font-mono uppercase tracking-widest text-[#6B6B6B]">Campaign Analysis Summary</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="text-[10px] font-mono text-[#66BB6A]">✓ LOADED</span>
            <span v-if="analysisTimestamp" class="text-[10px] font-mono text-[#6B6B6B]">{{ analysisTimestamp }}</span>
          </div>
        </div>
        <div class="p-5 grid grid-cols-4 gap-4">
          <!-- Engagement Rate -->
          <div class="bg-[#FBF8F3] p-3 border border-[#E0DDD5]/20 text-center">
            <span class="font-mono text-[9px] text-[#6B6B6B] uppercase block mb-1">Engagement Rate</span>
            <span class="text-xl font-bold text-[#66BB6A]">{{ analysisData.engagement?.engagement_rate || '—' }}%</span>
            <span class="block text-[9px] font-mono" :class="analysisData.engagement?.rating === 'EXCELLENT' ? 'text-[#66BB6A]' : 'text-[#6B6B6B]'">{{ analysisData.engagement?.rating || '' }}</span>
          </div>
          <!-- Sentiment NSS -->
          <div class="bg-[#FBF8F3] p-3 border border-[#E0DDD5]/20 text-center">
            <span class="font-mono text-[9px] text-[#6B6B6B] uppercase block mb-1">Net Sentiment</span>
            <span class="text-xl font-bold" :class="(analysisData.sentiment?.nss || 0) >= 0 ? 'text-[#66BB6A]' : 'text-[#FF8A80]'">{{ analysisData.sentiment?.nss ?? '—' }}</span>
            <span class="block text-[9px] font-mono text-[#6B6B6B]">{{ analysisData.sentiment?.total_comments || 0 }} comments</span>
          </div>
          <!-- Campaign Score -->
          <div class="bg-[#FBF8F3] p-3 border border-[#E0DDD5]/20 text-center">
            <span class="font-mono text-[9px] text-[#6B6B6B] uppercase block mb-1">Campaign Score</span>
            <span class="text-xl font-bold text-[#2D2D2D]">{{ analysisData.campaign_score?.campaign_score ? (analysisData.campaign_score.campaign_score * 100).toFixed(0) : '—' }}</span>
            <span class="block text-[9px] font-mono" :class="analysisData.campaign_score?.rating === 'GOOD' ? 'text-[#66BB6A]' : 'text-[#6B6B6B]'">{{ analysisData.campaign_score?.rating || '' }}</span>
          </div>
          <!-- Data Points -->
          <div class="bg-[#FBF8F3] p-3 border border-[#E0DDD5]/20 text-center">
            <span class="font-mono text-[9px] text-[#6B6B6B] uppercase block mb-1">Data Points</span>
            <span class="text-xl font-bold text-[#D5C4F7]">{{ (analysisData.quantitative?.total_posts || 0) + (analysisData.quantitative?.total_comments || 0) + (analysisData.quantitative?.total_likes || 0) }}</span>
            <span class="block text-[9px] font-mono text-[#6B6B6B]">posts + comments + likes</span>
          </div>
        </div>
      </section>

      <!-- No Analysis Warning -->
      <div v-if="!analysisData && !loading && !generating" class="bg-[#FBF8F3] border border-[#FFE066]/30 px-6 py-4 flex items-center gap-3">
        <span class="material-symbols-outlined text-[#FFE066]">warning</span>
        <div>
          <p class="text-sm font-bold text-[#FFE066]">No Analysis Data Found</p>
          <p class="text-xs font-mono text-[#6B6B6B] mt-1">Run the analysis pipeline in the <router-link to="/analysis" class="text-[#D5C4F7] underline">Analysis</router-link> page first. The report will use sentiment and engagement data from the analysis.</p>
        </div>
      </div>

      <!-- Generation Progress -->
      <section v-if="generating || progressData" class="bg-[#FFFFFF] border border-[#E0DDD5] p-5">
        <div class="flex items-center justify-between mb-4">
          <div class="flex items-center gap-2">
            <span class="material-symbols-outlined text-xs text-[#66BB6A]">memory</span>
            <span class="text-[10px] font-mono uppercase tracking-widest text-[#6B6B6B]">ReACT Agent Pipeline</span>
          </div>
          <span class="text-[10px] font-mono" :class="generating ? 'text-[#FFE066]' : 'text-[#66BB6A]'">
            {{ generating ? 'IN PROGRESS' : 'COMPLETED' }}
          </span>
        </div>

        <!-- Progress Bar -->
        <div v-if="progressData" class="mb-3">
          <div class="flex justify-between text-[10px] font-mono text-[#6B6B6B] mb-1">
            <span>{{ progressData.message }}</span>
            <span>{{ progressData.sections_completed || 0 }}/{{ progressData.sections_total || '?' }}</span>
          </div>
          <div class="w-full h-1.5 bg-[#E0DDD5] rounded-full overflow-hidden">
            <div class="h-full bg-gradient-to-r from-[#66BB6A] to-[#66BB6A]/60 transition-all duration-500 rounded-full"
              :style="{ width: progressPct + '%' }"></div>
          </div>
        </div>

        <!-- Agent Log -->
        <div v-if="agentSteps.length" class="space-y-1 max-h-40 overflow-y-auto">
          <div v-for="(step, i) in agentSteps" :key="i"
            class="flex items-start gap-2 text-[11px] font-mono leading-relaxed">
            <span class="text-[#66BB6A] mt-0.5 shrink-0">›</span>
            <span :class="step.includes('tool_call') ? 'text-[#FFE066]' : 'text-[#6B6B6B]'">{{ step }}</span>
          </div>
        </div>
      </section>

      <!-- Empty state -->
      <div v-if="!reportMd && !generating" class="flex flex-col items-center justify-center py-20 gap-4">
        <span class="material-symbols-outlined text-5xl text-[#E0DDD5]">description</span>
        <p class="font-mono text-xs text-[#6B6B6B]">No report generated yet.</p>
        <p v-if="!store.simId" class="font-mono text-xs text-[#FFE066]">Run a simulation first, then generate a report.</p>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="flex items-center justify-center py-20">
        <div class="flex flex-col items-center gap-3">
          <div class="w-8 h-8 border-2 border-[#66BB6A] border-t-transparent rounded-full animate-spin"></div>
          <span class="font-mono text-xs text-[#6B6B6B]">Loading report...</span>
        </div>
      </div>

      <!-- Report Meta -->
      <section v-if="reportMeta && reportMeta.report_id" class="bg-[#FFFFFF] border border-[#E0DDD5] p-4">
        <div class="grid grid-cols-4 gap-4">
          <div v-for="stat in metaStats" :key="stat.label">
            <p class="text-[10px] font-mono uppercase tracking-widest text-[#6B6B6B]">{{ stat.label }}</p>
            <p class="text-lg font-bold text-[#2D2D2D] font-sans">{{ stat.value }}</p>
          </div>
        </div>
      </section>

      <!-- Main Report -->
      <section v-if="reportMd" class="bg-[#FFFFFF] border border-[#E0DDD5]">
        <div class="p-6 border-b border-[#E0DDD5] flex items-center justify-between">
          <h3 class="text-2xl font-semibold font-sans text-[#2D2D2D]">Campaign Report</h3>
          <div class="flex items-center gap-2">
            <button @click="viewMode = 'full'" :class="viewMode === 'full' ? 'text-[#66BB6A] border-[#66BB6A]' : 'text-[#6B6B6B] border-[#E0DDD5]'"
              class="px-3 py-1 text-[10px] font-mono uppercase border transition-colors">Full</button>
            <button @click="viewMode = 'sections'" :class="viewMode === 'sections' ? 'text-[#66BB6A] border-[#66BB6A]' : 'text-[#6B6B6B] border-[#E0DDD5]'"
              class="px-3 py-1 text-[10px] font-mono uppercase border transition-colors">Sections</button>
          </div>
        </div>
        <div class="p-6 prose prose-invert max-w-none report-content" v-html="renderedReport"></div>
      </section>

      <!-- Action Bar -->
      <div v-if="reportMd" class="flex items-center gap-3">
        <button @click="copyMarkdown" class="px-4 py-2 border border-[#E0DDD5] text-xs font-mono text-[#2D2D2D] hover:bg-[#FFFFFF] transition-colors">Copy Markdown</button>
        <button @click="showChat = !showChat" class="px-4 py-2 bg-[#FBF8F3] text-[#66BB6A] text-xs font-mono border border-[#66BB6A] flex items-center gap-2 hover:bg-[#E0DDD5] transition-colors">
          <span class="material-symbols-outlined text-sm">chat</span>
          {{ showChat ? 'Hide Chat' : 'Ask Questions' }}
        </button>
        <button @click="$router.push('/survey')" class="px-4 py-2 bg-[#FBF8F3] text-[#FFE066] text-xs font-mono border border-[#FFE066] flex items-center gap-2 hover:bg-[#E0DDD5] transition-colors">
          <span class="material-symbols-outlined text-sm">quiz</span>
          Next: Survey
        </button>
      </div>

      <!-- Chat Q&A -->
      <section v-if="showChat && reportMd" class="bg-[#FFFFFF] border border-[#E0DDD5]">
        <div class="p-4 border-b border-[#E0DDD5] flex items-center gap-2">
          <span class="material-symbols-outlined text-xs text-[#66BB6A]">forum</span>
          <span class="text-[10px] font-mono uppercase tracking-widest text-[#6B6B6B]">Report Q&A — Ask about the report</span>
        </div>
        <div class="p-4 space-y-3 max-h-80 overflow-y-auto">
          <div v-for="(msg, i) in chatMessages" :key="i"
            :class="msg.role === 'user' ? 'text-right' : 'text-left'">
            <div :class="msg.role === 'user' ? 'bg-[#66BB6A]/10 border-[#66BB6A]/30' : 'bg-[#FBF8F3] border-[#E0DDD5]'"
              class="inline-block px-4 py-2 border text-sm text-[#2D2D2D] max-w-[80%] text-left">
              {{ msg.content }}
            </div>
          </div>
        </div>
        <div class="p-4 border-t border-[#E0DDD5] flex gap-2">
          <input v-model="chatInput" @keyup.enter="sendChat" placeholder="Hỏi về báo cáo..."
            class="flex-1 bg-[#F5F0E8] border border-[#E0DDD5] px-4 py-2 text-sm text-[#2D2D2D] font-mono focus:border-[#66BB6A] outline-none" />
          <button @click="sendChat" :disabled="chatLoading || !chatInput.trim()"
            class="px-4 py-2 bg-[#66BB6A] text-[#00382a] text-xs font-mono font-bold disabled:opacity-50">
            {{ chatLoading ? '...' : 'Send' }}
          </button>
        </div>
      </section>
    </div>

    <!-- BottomNavBar -->
    <nav class="h-14 flex justify-between items-center px-8 bg-[#F5F0E8] border-t border-[#E0DDD5] flex-shrink-0">
      <router-link to="/simulation" class="flex items-center gap-2 text-[#6B6B6B] hover:text-[#2D2D2D] transition-all group">
        <span class="material-symbols-outlined text-sm">arrow_back</span>
        <span class="font-mono text-[10px] uppercase tracking-widest">Back: Simulation</span>
      </router-link>
      <router-link to="/survey" class="flex items-center gap-2 text-[#66BB6A] font-bold hover:text-[#66BB6A]/80 transition-all group">
        <span class="font-mono text-[10px] uppercase tracking-widest">Next: Survey</span>
        <span class="material-symbols-outlined text-sm">arrow_forward</span>
      </router-link>
    </nav>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { reportApi } from '../api/client'
import { useAppStore } from '../stores/appStore'

const store = useAppStore()

const loading = ref(false)
const generating = ref(false)
const error = ref('')
const reportMd = ref('')
const reportMeta = ref({})
const progressData = ref(null)
const agentSteps = ref([])
const viewMode = ref('full')
const showChat = ref(false)
const chatInput = ref('')
const chatLoading = ref(false)
const chatMessages = ref([])
const analysisData = ref(null)
const analysisTimestamp = ref('')
let progressPoller = null

// Progress percentage
const progressPct = computed(() => {
  if (!progressData.value) return 0
  const { sections_completed = 0, sections_total = 1 } = progressData.value
  return Math.round((sections_completed / Math.max(sections_total, 1)) * 100)
})

// Meta stats
const metaStats = computed(() => {
  const m = reportMeta.value || {}
  return [
    { label: 'Sections', value: m.sections_count || '—' },
    { label: 'Tool Calls', value: m.total_tool_calls || '—' },
    { label: 'Duration', value: m.duration_s ? `${m.duration_s}s` : '—' },
    { label: 'Status', value: m.status || '—' },
  ]
})

// Markdown renderer
const renderedReport = computed(() => {
  if (!reportMd.value) return ''
  return reportMd.value
    .replace(/^### (.*$)/gm, '<h3 class="text-lg font-bold text-[#2D2D2D] mt-6 mb-3">$1</h3>')
    .replace(/^## (.*$)/gm, '<h2 class="text-xl font-bold text-[#2D2D2D] mt-8 mb-4">$1</h2>')
    .replace(/^# (.*$)/gm, '<h1 class="text-2xl font-bold text-[#2D2D2D] mt-8 mb-4">$1</h1>')
    .replace(/\*\*(.*?)\*\*/g, '<strong class="text-[#2D2D2D]">$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/\[SIM\]/g, '<span class="text-[10px] font-mono bg-[#66BB6A]/10 text-[#66BB6A] px-1 rounded">SIM</span>')
    .replace(/\[KG\]/g, '<span class="text-[10px] font-mono bg-[#6366F1]/10 text-[#D5C4F7] px-1 rounded">KG</span>')
    .replace(/\[SPEC\]/g, '<span class="text-[10px] font-mono bg-[#FFE066]/10 text-[#FFE066] px-1 rounded">SPEC</span>')
    .replace(/\[CALC\]/g, '<span class="text-[10px] font-mono bg-[#FF8A80]/10 text-[#FF8A80] px-1 rounded">CALC</span>')
    .replace(/^- (.*$)/gm, '<li class="text-sm text-[#6B6B6B] leading-relaxed ml-4">$1</li>')
    .replace(/^(\d+)\. (.*$)/gm, '<li class="text-sm text-[#6B6B6B] leading-relaxed ml-4">$2</li>')
    .replace(/\n\n/g, '<br/><br/>')
    .replace(/\n/g, '<br/>')
})

async function loadReport() {
  if (!store.simId) return
  loading.value = true
  try {
    const res = await reportApi.get(store.simId)
    reportMd.value = res.data.report_md || ''
    reportMeta.value = res.data.meta || {}
  } catch {
    // Report not generated yet
  } finally {
    loading.value = false
  }
}

async function pollProgress() {
  if (!store.simId) return
  try {
    const res = await reportApi.progress(store.simId)
    progressData.value = res.data
    if (res.data.message) {
      const msg = `[${new Date().toLocaleTimeString()}] ${res.data.message}`
      if (!agentSteps.value.includes(msg)) agentSteps.value.push(msg)
    }
  } catch { /* ignore */ }
}

async function generateReport() {
  if (!store.simId) return
  generating.value = true
  error.value = ''
  agentSteps.value = [`[${new Date().toLocaleTimeString()}] Starting ReACT agent pipeline...`]
  progressData.value = { status: 'planning', message: 'Initializing...', sections_completed: 0, sections_total: 4 }

  // Start progress polling
  progressPoller = setInterval(pollProgress, 3000)

  try {
    const res = await reportApi.generate(store.simId)
    agentSteps.value.push(`[${new Date().toLocaleTimeString()}] Report completed! (${res.data.total_tool_calls} tool calls, ${res.data.duration_s}s)`)
    store.completeStep('report')
    await loadReport()
  } catch (e) {
    error.value = e.response?.data?.error || 'Report generation failed'
  } finally {
    generating.value = false
    clearInterval(progressPoller)
    await pollProgress() // Final poll
  }
}

async function sendChat() {
  const msg = chatInput.value.trim()
  if (!msg || chatLoading.value) return

  chatMessages.value.push({ role: 'user', content: msg })
  chatInput.value = ''
  chatLoading.value = true

  try {
    const history = chatMessages.value.map(m => ({ role: m.role, content: m.content }))
    const res = await reportApi.chat(store.simId, msg, history.slice(0, -1))
    chatMessages.value.push({ role: 'assistant', content: res.data.response })
  } catch (e) {
    chatMessages.value.push({ role: 'assistant', content: 'Lỗi: ' + (e.response?.data?.error || 'Không thể trả lời') })
  } finally {
    chatLoading.value = false
  }
}

function copyMarkdown() {
  navigator.clipboard.writeText(reportMd.value)
}

async function loadAnalysis() {
  if (!store.simId) return
  try {
    const res = await reportApi.cachedAnalysis(store.simId)
    if (res.data?.cached && res.data.results) {
      analysisData.value = res.data.results
      if (res.data.timestamp) {
        const d = new Date(res.data.timestamp)
        analysisTimestamp.value = d.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })
      }
    }
  } catch (e) {
    console.warn('No cached analysis:', e.message)
  }
}

onMounted(() => {
  loadReport()
  loadAnalysis()
})
onUnmounted(() => { if (progressPoller) clearInterval(progressPoller) })
</script>

<style>
.report-content h1, .report-content h2, .report-content h3 { font-family: 'Space Mono', sans-serif; font-weight: 700; }
.report-content li { list-style-type: disc; }
.report-content p, .report-content li { color: #6B6B6B; font-size: 14px; line-height: 1.8; }
</style>

<style scoped>
/* ===== MEMPHIS REPORT OVERRIDES ===== */
.flex-1.flex.flex-col.overflow-hidden {
  font-family: 'DM Sans', system-ui, sans-serif;
  position: relative;
}

.flex-1.flex.flex-col.overflow-hidden::before {
  content: '';
  position: fixed;
  top: 30%;
  left: 10%;
  width: 0;
  height: 0;
  border-left: 45px solid transparent;
  border-right: 45px solid transparent;
  border-bottom: 78px solid #66BB6A;
  opacity: 0.04;
  pointer-events: none;
  animation: rFloat 10s ease-in-out infinite;
  z-index: 0;
}

@keyframes rFloat {
  0%, 100% { transform: translate(0, 0) rotate(0deg); }
  50% { transform: translate(10px, -12px) rotate(5deg); }
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

h2, h3 {
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700 !important;
}

/* Generate button */
button[class*="bg-[#66BB6A]"] {
  border-radius: 0 !important;
  border: 2px solid #F5F0E8 !important;
  box-shadow: 4px 4px 0 #9B59B6;
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

button[class*="bg-[#66BB6A]"]:hover {
  transform: translate(-2px, -2px);
  box-shadow: 6px 6px 0 #9B59B6;
}

button[class*="bg-[#66BB6A]"]:active {
  transform: translate(2px, 2px);
  box-shadow: none;
}

/* Report sections — Memphis cards */
section[class*="bg-[#FFFFFF]"] {
  border: 2px solid #E0DDD5 !important;
  box-shadow: 3px 3px 0 rgba(45, 43, 85, 0.3);
}

/* Metric cards */
div[class*="bg-[#FBF8F3]"][class*="border"] {
  border: 2px solid #E0DDD5 !important;
  box-shadow: 2px 2px 0 rgba(45, 43, 85, 0.3);
}

/* Action buttons — Memphis style */
button[class*="border"][class*="font-mono"] {
  border: 2px solid !important;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

button[class*="border"][class*="font-mono"]:hover {
  box-shadow: 3px 3px 0 rgba(132, 94, 194, 0.3);
  transform: translate(-1px, -1px);
}

/* Progress bar — square */
div[class*="rounded-full"][class*="bg-[#E0DDD5]"] {
  border-radius: 0 !important;
}

div[class*="rounded-full"][class*="bg-gradient-to-r"] {
  border-radius: 0 !important;
}

/* Chat section — polka dots */
section[class*="bg-[#FFFFFF]"]:last-of-type {
  position: relative;
}

/* Chat input */
input[class*="bg-[#F5F0E8]"] {
  border: 2px solid #E0DDD5 !important;
  border-radius: 0 !important;
}

input[class*="bg-[#F5F0E8]"]:focus {
  border-color: #66BB6A !important;
  box-shadow: 3px 3px 0 #66BB6A !important;
}

/* Error bars */
div[class*="border-l-2"][class*="border-[#FF8A80]"] {
  border: 2px solid #FF8A80 !important;
  border-left-width: 4px !important;
  box-shadow: 3px 3px 0 rgba(255, 107, 107, 0.2);
}

/* Warning bar */
div[class*="border-[#FFE066]"] {
  border: 2px solid #FFE066 !important;
  box-shadow: 3px 3px 0 rgba(255, 217, 61, 0.2);
}

/* Bottom nav */
nav {
  border-top: 3px solid #D5C4F7 !important;
}

/* Spinners */
div[class*="rounded-full"][class*="animate-spin"] {
  border-radius: 0 !important;
}

/* View mode buttons — square */
button[class*="px-3"][class*="py-1"][class*="uppercase"] {
  border-radius: 0 !important;
}
</style>
