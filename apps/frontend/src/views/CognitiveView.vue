<template>
  <div class="flex-1 flex flex-col overflow-hidden">
    <!-- HEADER -->
    <header class="h-16 border-b border-[#E0DDD5] bg-[#F5F0E8] flex items-center justify-between px-8 flex-shrink-0">
      <div class="flex items-center gap-3">
        <span class="material-symbols-outlined text-[#9B59B6]">neurology</span>
        <h1 class="text-lg font-bold text-[#2D2D2D]" style="font-family:'Space Mono',monospace">
          Cognitive Pipeline Tracker
        </h1>
      </div>
      <div class="flex items-center gap-3">
        <select v-model="selectedSimId"
          class="text-xs font-mono px-3 py-1.5 bg-white border border-[#E0DDD5] text-[#2D2D2D] focus:border-[#66BB6A] outline-none"
          @change="loadCognitiveData">
          <option value="">— Select Simulation —</option>
          <option v-for="s in simulations" :key="s.sim_id" :value="s.sim_id">
            {{ s.sim_id }} ({{ s.status }})
          </option>
        </select>
      </div>
    </header>

    <!-- CONTENT -->
    <div class="flex-1 overflow-y-auto p-8">
      <!-- Empty State -->
      <div v-if="!data" class="flex flex-col items-center justify-center h-full gap-4 text-[#6B6B6B]">
        <span class="material-symbols-outlined text-6xl text-[#E0DDD5]">neurology</span>
        <p class="text-sm font-mono">Chọn simulation đã hoàn thành để xem cognitive evolution</p>
        <p class="text-xs text-[#9B9B9B]">Yêu cầu: <code class="bg-[#E0DDD5] px-1 py-0.5 text-[10px]">enable_reflection: true</code> và <code class="bg-[#E0DDD5] px-1 py-0.5 text-[10px]">tracked_agent_id</code> trong config</p>
      </div>

      <!-- Error -->
      <div v-else-if="error" class="bg-[#FF8A80]/10 border border-[#FF8A80]/30 p-4 text-sm text-[#FF8A80]">
        {{ error }}
      </div>

      <!-- Agent Info Banner -->
      <div v-else>
        <div class="mb-8 p-5 bg-white border border-[#E0DDD5] flex items-center justify-between">
          <div class="flex items-center gap-4">
            <div class="w-12 h-12 bg-[#9B59B6]/10 border border-[#9B59B6]/30 flex items-center justify-center text-[#9B59B6] font-mono font-bold text-lg">
              {{ data.agent.id }}
            </div>
            <div>
              <h2 class="text-base font-bold text-[#2D2D2D]" style="font-family:'Space Mono',monospace">
                {{ data.agent.name }}
              </h2>
              <div class="flex items-center gap-3 mt-1">
                <span class="text-[10px] font-mono px-2 py-0.5 bg-[#B5E8F0]/30 text-[#0097A7] border border-[#B5E8F0]">
                  MBTI: {{ data.agent.mbti }}
                </span>
                <span class="text-[10px] font-mono text-[#6B6B6B]">
                  {{ data.total_rounds }} rounds tracked
                </span>
              </div>
            </div>
          </div>
          <!-- Summary Stats -->
          <div class="flex gap-6">
            <div class="text-center">
              <div class="text-xl font-mono font-bold text-[#66BB6A]">{{ totalInsights }}</div>
              <div class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-widest">insights</div>
            </div>
            <div class="text-center">
              <div class="text-xl font-mono font-bold text-[#FFE066]">{{ totalActions }}</div>
              <div class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-widest">actions</div>
            </div>
            <div class="text-center">
              <div class="text-xl font-mono font-bold text-[#B5E8F0]">{{ driftEvolution.length }}</div>
              <div class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-widest">drift steps</div>
            </div>
          </div>
        </div>

        <!-- Tab Navigation -->
        <div class="flex border-b border-[#E0DDD5] mb-6 gap-6">
          <button v-for="tab in ['Timeline','Drift','Pipeline']" :key="tab"
            @click="activeTab = tab"
            :class="[
              'pb-2 text-sm font-mono tracking-tight transition-colors',
              activeTab === tab
                ? 'text-[#2D2D2D] border-b-2 border-[#2D2D2D] font-bold'
                : 'text-[#6B6B6B] hover:text-[#2D2D2D]'
            ]">
            {{ tab }}
          </button>
        </div>

        <!-- ═══ TIMELINE TAB ═══ -->
        <div v-if="activeTab === 'Timeline'" class="space-y-0">
          <div v-for="(rd, idx) in data.rounds" :key="rd.round"
            class="relative pl-8 border-l-2"
            :class="rd.insights_count > (idx > 0 ? data.rounds[idx-1].insights_count : 0)
              ? 'border-[#9B59B6]' : 'border-[#E0DDD5]'">

            <!-- Timeline Dot -->
            <div class="absolute left-[-9px] top-4 w-4 h-4 rounded-full border-2 border-white"
              :class="rd.insights_count > (idx > 0 ? data.rounds[idx-1].insights_count : 0)
                ? 'bg-[#9B59B6]' : 'bg-[#E0DDD5]'">
            </div>

            <!-- Round Card -->
            <div class="ml-4 mb-6 p-5 bg-white border border-[#E0DDD5] hover:border-[#9B59B6]/30 transition-colors">
              <!-- Round Header -->
              <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-3">
                  <span class="font-mono text-xs px-2 py-0.5 bg-[#F5F0E8] text-[#2D2D2D] font-bold">
                    R{{ rd.round }}
                  </span>
                  <span v-if="rd.round === 0" class="text-[9px] font-mono text-[#66BB6A] bg-[#66BB6A]/10 px-2 py-0.5">INITIAL STATE</span>
                  <span v-if="rd.insights_count > (idx > 0 ? data.rounds[idx-1].insights_count : 0)"
                    class="text-[9px] font-mono text-[#9B59B6] bg-[#9B59B6]/10 px-2 py-0.5">
                    ⭐ REFLECTION +{{ rd.insights_count - (idx > 0 ? data.rounds[idx-1].insights_count : 0) }}
                  </span>
                </div>
                <button @click="toggleExpand(rd.round)"
                  class="text-[9px] font-mono text-[#6B6B6B] hover:text-[#2D2D2D] transition-colors">
                  {{ expandedRounds.has(rd.round) ? '▼ Collapse' : '▶ Expand' }}
                </button>
              </div>

              <!-- Always visible: Key changes -->
              <div class="space-y-2">
                <!-- Reflection insight (highlighted) -->
                <div v-if="rd.reflections" class="bg-[#9B59B6]/5 border-l-2 border-[#9B59B6] px-3 py-2">
                  <span class="text-[9px] font-mono text-[#9B59B6] font-bold uppercase tracking-widest">Insights ({{ rd.insights_count }})</span>
                  <p class="text-xs text-[#2D2D2D] mt-1 leading-relaxed">{{ rd.reflections }}</p>
                </div>

                <!-- Actions summary -->
                <div v-if="rd.actions && rd.actions.length" class="flex flex-wrap gap-1.5">
                  <span v-for="(a, ai) in rd.actions" :key="ai"
                    class="text-[10px] font-mono px-2 py-0.5 border"
                    :class="actionColors[a.type] || 'bg-[#F5F0E8] text-[#6B6B6B] border-[#E0DDD5]'">
                    {{ actionLabels[a.type] || a.type }}
                  </span>
                </div>

                <!-- Drift keywords -->
                <div v-if="rd.drift_keywords && rd.drift_keywords.length" class="flex items-center gap-2 flex-wrap">
                  <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-widest">drift:</span>
                  <span v-for="kw in rd.drift_keywords" :key="kw"
                    class="text-[10px] font-mono px-1.5 py-0.5 bg-[#FFE066]/20 text-[#FF8F00] border border-[#FFE066]/40">
                    {{ kw }}
                  </span>
                </div>
              </div>

              <!-- Expanded details -->
              <div v-if="expandedRounds.has(rd.round)" class="mt-4 space-y-3 pt-3 border-t border-[#E0DDD5]">
                <!-- Memory -->
                <div v-if="rd.memory">
                  <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-widest block mb-1">Memory</span>
                  <pre class="text-[11px] text-[#2D2D2D] bg-[#F5F0E8] p-3 whitespace-pre-wrap font-mono leading-relaxed">{{ rd.memory }}</pre>
                </div>

                <!-- Evolved Persona -->
                <div v-if="rd.evolved_persona">
                  <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-widest block mb-1">Evolved Persona</span>
                  <pre class="text-[11px] text-[#2D2D2D] bg-[#F5F0E8] p-3 whitespace-pre-wrap font-mono leading-relaxed max-h-[300px] overflow-y-auto">{{ rd.evolved_persona }}</pre>
                </div>

                <!-- Full Interest Query -->
                <div v-if="rd.interest_query">
                  <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-widest block mb-1">Interest Query</span>
                  <pre class="text-[11px] text-[#2D2D2D] bg-[#B5E8F0]/10 p-3 whitespace-pre-wrap font-mono leading-relaxed border border-[#B5E8F0]/30">{{ rd.interest_query }}</pre>
                </div>

                <!-- MBTI Modifiers -->
                <div v-if="rd.mbti_modifiers">
                  <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-widest block mb-1">MBTI Modifiers</span>
                  <code class="text-[10px] text-[#0097A7] bg-[#B5E8F0]/10 px-2 py-1 border border-[#B5E8F0]/30">{{ rd.mbti_modifiers }}</code>
                </div>

                <!-- Graph Social Context -->
                <div v-if="rd.graph_context">
                  <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-widest block mb-1">Graph Social Context</span>
                  <pre class="text-[11px] text-[#2D2D2D] bg-[#66BB6A]/5 p-3 whitespace-pre-wrap font-mono border border-[#66BB6A]/20">{{ rd.graph_context }}</pre>
                </div>

                <!-- Actions detail -->
                <div v-if="rd.actions && rd.actions.length">
                  <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-widest block mb-1">Actions Detail</span>
                  <div class="space-y-1">
                    <div v-for="(a, ai) in rd.actions" :key="ai"
                      class="text-[11px] text-[#2D2D2D] bg-white p-2 border border-[#E0DDD5]">
                      <span class="font-mono text-[#6B6B6B] mr-2">{{ a.type }}:</span>
                      <span>{{ a.text || '—' }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ═══ DRIFT TAB ═══ -->
        <div v-if="activeTab === 'Drift'" class="space-y-6">
          <div class="p-5 bg-white border border-[#E0DDD5]">
            <h3 class="text-sm font-bold text-[#2D2D2D] mb-4" style="font-family:'Space Mono',monospace">Interest Drift Evolution</h3>
            <div class="space-y-3">
              <div v-for="(step, si) in driftEvolution" :key="si" class="flex items-start gap-4">
                <span class="font-mono text-xs px-2 py-0.5 bg-[#F5F0E8] text-[#2D2D2D] font-bold flex-shrink-0 mt-0.5">
                  R{{ step.round }}
                </span>
                <div class="flex-1">
                  <div class="flex flex-wrap gap-1.5 mb-1">
                    <span v-for="kw in step.keywords" :key="kw"
                      class="text-[10px] font-mono px-2 py-0.5"
                      :class="step.isNew(kw) ? 'bg-[#FFE066]/30 text-[#FF8F00] border border-[#FFE066] font-bold' : 'bg-[#F5F0E8] text-[#6B6B6B] border border-[#E0DDD5]'">
                      {{ kw }}{{ step.isNew(kw) ? ' ✦' : '' }}
                    </span>
                    <span v-if="!step.keywords.length" class="text-[10px] font-mono text-[#9B9B9B] italic">
                      (no drift keywords)
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Base Interest (always present) -->
          <div class="p-5 bg-white border border-[#E0DDD5]">
            <h3 class="text-sm font-bold text-[#2D2D2D] mb-3" style="font-family:'Space Mono',monospace">Base Interest (cố định)</h3>
            <pre v-if="baseInterest" class="text-[11px] text-[#0097A7] bg-[#B5E8F0]/10 p-3 whitespace-pre-wrap font-mono border border-[#B5E8F0]/30">{{ baseInterest }}</pre>
          </div>
        </div>

        <!-- ═══ PIPELINE TAB ═══ -->
        <div v-if="activeTab === 'Pipeline'" class="space-y-4">
          <div v-for="phase in pipelinePhases" :key="phase.id"
            class="p-5 bg-white border border-[#E0DDD5] hover:border-[#9B59B6]/30 transition-colors">
            <div class="flex items-center gap-3 mb-2">
              <span class="w-8 h-8 flex items-center justify-center font-mono text-xs font-bold text-white"
                :class="phase.color">
                {{ phase.id }}
              </span>
              <div>
                <h4 class="text-sm font-bold text-[#2D2D2D]" style="font-family:'Space Mono',monospace">{{ phase.name }}</h4>
                <span class="text-[10px] font-mono text-[#6B6B6B]">{{ phase.module }}</span>
              </div>
              <span class="ml-auto text-[10px] font-mono px-2 py-0.5 border"
                :class="phase.enabled ? 'bg-[#66BB6A]/10 text-[#66BB6A] border-[#66BB6A]/30' : 'bg-[#FF8A80]/10 text-[#FF8A80] border-[#FF8A80]/30'">
                {{ phase.enabled ? '✓ ACTIVE' : '✗ DISABLED' }}
              </span>
            </div>
            <p class="text-xs text-[#6B6B6B] leading-relaxed mb-2">{{ phase.problem }}</p>
            <p class="text-xs text-[#2D2D2D] leading-relaxed">
              <span class="font-bold text-[#9B59B6]">Giải pháp:</span> {{ phase.solution }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { simApi } from '../api/client'
import { useAppStore } from '../stores/appStore'

const store = useAppStore()

const simulations = ref([])
const selectedSimId = ref(store.simId || '')
const data = ref(null)
const error = ref('')
const activeTab = ref('Timeline')
const expandedRounds = ref(new Set())

const actionColors = {
  create_post: 'bg-[#66BB6A]/10 text-[#66BB6A] border-[#66BB6A]/30',
  create_comment: 'bg-[#B5E8F0]/20 text-[#0097A7] border-[#B5E8F0]',
  like_post: 'bg-[#FFE066]/20 text-[#FF8F00] border-[#FFE066]/40',
}

const actionLabels = {
  create_post: '📝 Post',
  create_comment: '💬 Comment',
  like_post: '❤️ Like',
}

// Pipeline phases info
const pipelinePhases = [
  {
    id: 1, name: 'Sensory Memory', module: 'AgentMemory', color: 'bg-[#66BB6A]',
    enabled: true,
    problem: 'Agent không nhớ gì giữa các round → hành vi lặp lại, không có tính liên tục.',
    solution: 'FIFO buffer ghi nhận hành động mỗi round, inject vào LLM prompt để agent biết mình đã làm gì.'
  },
  {
    id: 2, name: 'MBTI Modifiers', module: 'MBTIBehavior', color: 'bg-[#B5E8F0]',
    enabled: true,
    problem: 'Mọi agent có cùng xác suất hành động → hành vi đồng nhất, không phân biệt tính cách.',
    solution: 'Áp dụng multipliers dựa trên 4 chiều MBTI: E/I (activity), N/S (explore), F/T (engage), J/P (consistency).'
  },
  {
    id: 3, name: 'Interest Drift', module: 'InterestTracker', color: 'bg-[#FFE066]',
    enabled: true,
    problem: 'Feed recommendation dùng interest cố định → agent luôn thấy cùng loại content.',
    solution: 'FIFO buffer (max 5 keywords) trích xuất từ engagement, append vào ChromaDB query.'
  },
  {
    id: 4, name: 'Reflection', module: 'AgentReflection', color: 'bg-[#9B59B6]',
    enabled: true,
    problem: 'Persona cố định → agent không "trưởng thành" qua trải nghiệm, insight không tích lũy.',
    solution: 'Mỗi N rounds, LLM tạo 1 insight sentence từ memory + social context, append vào persona.'
  },
  {
    id: 5, name: 'Knowledge Graph', module: 'GraphCognitiveHelper', color: 'bg-[#FF8A80]',
    enabled: true,
    problem: 'Cognitive layer chỉ dùng in-memory data → không biết mối quan hệ xã hội giữa agents.',
    solution: 'Bridge FalkorDB graph memory vào reflection, post/comment gen, và interest drift qua COMBINED_HYBRID_SEARCH_RRF.'
  },
]

const totalInsights = computed(() => {
  if (!data.value?.rounds?.length) return 0
  return data.value.rounds[data.value.rounds.length - 1]?.insights_count || 0
})

const totalActions = computed(() => {
  if (!data.value?.rounds) return 0
  return data.value.rounds.reduce((sum, rd) => sum + (rd.actions?.length || 0), 0)
})

const driftEvolution = computed(() => {
  if (!data.value?.rounds) return []
  return data.value.rounds.map((rd, i) => {
    const prevKws = i > 0 ? new Set(data.value.rounds[i-1].drift_keywords || []) : new Set()
    return {
      round: rd.round,
      keywords: rd.drift_keywords || [],
      isNew: (kw) => !prevKws.has(kw),
    }
  })
})

const baseInterest = computed(() => {
  if (!data.value?.rounds?.length) return ''
  const r0 = data.value.rounds[0]
  return r0?.interest_query || ''
})

function toggleExpand(round) {
  const s = new Set(expandedRounds.value)
  if (s.has(round)) s.delete(round)
  else s.add(round)
  expandedRounds.value = s
}

async function loadSimulations() {
  try {
    const res = await simApi.list()
    simulations.value = (res.data.simulations || []).filter(s =>
      s.status === 'completed' || s.status === 'ready'
    )
    // Auto-select if store has simId
    if (store.simId && !selectedSimId.value) {
      selectedSimId.value = store.simId
    }
  } catch (e) {
    console.warn('Failed to load simulations:', e)
  }
}

async function loadCognitiveData() {
  if (!selectedSimId.value) { data.value = null; return }
  error.value = ''
  try {
    const res = await simApi.cognitive(selectedSimId.value)
    data.value = res.data
  } catch (e) {
    if (e.response?.status === 404) {
      error.value = 'Không tìm thấy file agent_tracking.txt. Hãy chạy simulation với enable_reflection: true và tracked_agent_id.'
    } else {
      error.value = e.response?.data?.detail || e.message
    }
    data.value = null
  }
}

onMounted(async () => {
  await loadSimulations()
  if (selectedSimId.value) await loadCognitiveData()
})
</script>
