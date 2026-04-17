<template>
  <div class="survey-root flex-1 overflow-y-auto">
    <div class="max-w-[1100px] mx-auto px-8 py-10 min-h-screen">
      <!-- Header -->
      <div class="mb-8 flex flex-col gap-1">
        <div class="flex items-center gap-3">
          <span class="material-symbols-outlined text-[#2D2D2D]">content_paste_search</span>
          <h1 class="text-2xl font-bold tracking-tight text-[#2D2D2D]">Agent Survey</h1>
          <span class="ml-4 px-2 py-0.5 border border-[#E0DDD5] text-[10px] text-[#6B6B6B] font-mono uppercase">MỞ RỘNG</span>
          <span class="text-[10px] text-[#66BB6A] font-mono">{{ store.simId || '—' }}</span>
        </div>
        <p v-if="!store.simId" class="text-xs text-[#FF8A80] font-mono mt-1">⚠ Hoàn thành simulation trước khi khảo sát.</p>
      </div>

      <!-- Stepper -->
      <div class="stepper">
        <div v-for="(s, i) in stepLabels" :key="i"
          :class="['step-item', { active: step === i, done: step > i }]"
          @click="i < step && goStep(i)">
          <div class="step-num">{{ step > i ? '✓' : i + 1 }}</div>
          <span class="step-label">{{ s }}</span>
        </div>
        <div class="step-line" :style="{ width: ((step / 2) * 100) + '%' }"></div>
      </div>

      <!-- Error -->
      <div v-if="error" class="error-bar">
        <span class="material-symbols-outlined text-sm">error</span>
        <span>{{ error }}</span>
        <button @click="error = ''" class="ml-auto text-[10px] opacity-60 hover:opacity-100">✕</button>
      </div>

      <!-- ═══════════ STEP 0: QUESTIONS ═══════════ -->
      <div v-if="step === 0" class="step-panel">
        <h2 class="panel-title">Chuẩn bị câu hỏi</h2>
        <p class="panel-desc">Thêm câu hỏi tùy chỉnh hoặc sử dụng bộ câu hỏi mẫu.</p>

        <!-- Quick actions -->
        <div class="flex gap-3 mb-6">
          <button @click="loadDefaults" :disabled="loadingDefaults" class="btn-secondary">
            <span class="material-symbols-outlined text-sm">auto_awesome</span>
            {{ loadingDefaults ? 'Đang tải...' : 'Sinh câu hỏi mẫu' }}
          </button>
          <button @click="clearQuestions" v-if="questions.length" class="btn-ghost">
            <span class="material-symbols-outlined text-sm">delete_sweep</span>
            Xóa tất cả
          </button>
        </div>

        <!-- Question List -->
        <div class="questions-list">
          <div v-for="(q, qi) in questions" :key="qi" class="question-card">
            <div class="q-header">
              <span class="q-index">Q{{ qi + 1 }}</span>
              <span class="q-type-badge">{{ typeLabel(q.question_type) }}</span>
              <button @click="removeQuestion(qi)" class="q-delete" title="Xóa">
                <span class="material-symbols-outlined text-sm">close</span>
              </button>
            </div>
            <p class="q-text">{{ q.text }}</p>
            <div v-if="q.options?.length" class="q-options">
              <span v-for="opt in q.options" :key="opt" class="q-option-chip">{{ opt }}</span>
            </div>
          </div>
        </div>

        <!-- Empty state -->
        <div v-if="!questions.length" class="empty-questions">
          <span class="material-symbols-outlined text-4xl text-[#E0DDD5]">quiz</span>
          <p>Chưa có câu hỏi nào. Thêm từ form bên dưới hoặc sinh câu hỏi mẫu.</p>
        </div>

        <!-- Add question form -->
        <div class="add-form">
          <h3 class="form-title">Thêm câu hỏi mới</h3>
          <div class="form-grid">
            <div class="form-group full">
              <label>Nội dung câu hỏi</label>
              <textarea v-model="newQ.text" rows="2" placeholder="Nhập câu hỏi khảo sát..."></textarea>
            </div>
            <div class="form-group">
              <label>Loại câu hỏi</label>
              <select v-model="newQ.question_type">
                <option value="open_ended">Tự do (Open-ended)</option>
                <option value="scale_1_10">Thang điểm 1-10</option>
                <option value="yes_no">Có / Không</option>
                <option value="multiple_choice">Trắc nghiệm</option>
              </select>
            </div>
            <div class="form-group">
              <label>Danh mục</label>
              <select v-model="newQ.category">
                <option value="general">Chung</option>
                <option value="sentiment">Cảm xúc</option>
                <option value="behavior">Hành vi</option>
                <option value="economic">Kinh tế</option>
              </select>
            </div>
            <div v-if="newQ.question_type === 'multiple_choice'" class="form-group full">
              <label>Tùy chọn (cách nhau bởi dấu phẩy)</label>
              <input v-model="newQ.optionsStr" type="text" placeholder="Tích cực, Trung lập, Tiêu cực" />
            </div>
          </div>
          <button @click="addQuestion" :disabled="!newQ.text.trim()" class="btn-primary mt-4">
            <span class="material-symbols-outlined text-sm">add</span>
            Thêm câu hỏi
          </button>
        </div>

        <!-- Next -->
        <div class="step-actions">
          <div></div>
          <button @click="goStep(1)" :disabled="!questions.length" class="btn-primary">
            Tiếp tục — Cấu hình
            <span class="material-symbols-outlined text-sm">arrow_forward</span>
          </button>
        </div>
      </div>

      <!-- ═══════════ STEP 1: CONFIGURATION ═══════════ -->
      <div v-if="step === 1" class="step-panel">
        <h2 class="panel-title">Cấu hình khảo sát</h2>
        <p class="panel-desc">Chọn số lượng agent và mức độ hiểu biết.</p>

        <div class="config-cards">
          <!-- Agent count -->
          <div class="config-card">
            <div class="config-icon">
              <span class="material-symbols-outlined">group</span>
            </div>
            <h3>Số lượng Agent</h3>
            <p class="config-desc">Khảo sát bao nhiêu agent trong mô phỏng?</p>
            <div class="config-control">
              <input type="range" v-model.number="config.numAgents" :min="1" :max="config.maxAgents" class="slider" />
              <div class="slider-labels">
                <span>1</span>
                <span class="slider-value">{{ config.numAgents }} agent{{ config.numAgents > 1 ? 's' : '' }}</span>
                <span>{{ config.maxAgents }}</span>
              </div>
            </div>
            <div class="config-badges">
              <button @click="config.numAgents = Math.min(5, config.maxAgents)" class="quick-badge">5</button>
              <button @click="config.numAgents = Math.min(10, config.maxAgents)" class="quick-badge">10</button>
              <button @click="config.numAgents = config.maxAgents" class="quick-badge">Tất cả</button>
            </div>
          </div>

          <!-- Knowledge level -->
          <div class="config-card">
            <div class="config-icon icon-brain">
              <span class="material-symbols-outlined">psychology</span>
            </div>
            <h3>Mức độ hiểu biết</h3>
            <p class="config-desc">Agent có biết về các hành động trong mô phỏng không?</p>
            <div class="knowledge-toggle">
              <button
                :class="['toggle-opt', { active: config.includeContext }]"
                @click="config.includeContext = true">
                <span class="material-symbols-outlined text-sm">visibility</span>
                <div>
                  <strong>Có ngữ cảnh</strong>
                  <span>Agent biết về hành động, bài viết, tương tác trong simulation</span>
                </div>
              </button>
              <button
                :class="['toggle-opt', { active: !config.includeContext }]"
                @click="config.includeContext = false">
                <span class="material-symbols-outlined text-sm">visibility_off</span>
                <div>
                  <strong>Không ngữ cảnh</strong>
                  <span>Agent chỉ biết profile cá nhân, không biết gì về mô phỏng</span>
                </div>
              </button>
            </div>
          </div>
        </div>

        <!-- Summary before run -->
        <div class="config-summary">
          <span class="material-symbols-outlined text-sm">summarize</span>
          <span>{{ questions.length }} câu hỏi × {{ config.numAgents }} agent{{ config.includeContext ? '' : ' (không ngữ cảnh)' }}</span>
          <span class="est">≈ {{ Math.ceil(questions.length * config.numAgents * 3 / 60) }} phút</span>
        </div>

        <div class="step-actions">
          <button @click="goStep(0)" class="btn-secondary">
            <span class="material-symbols-outlined text-sm">arrow_back</span>
            Quay lại
          </button>
          <button @click="goStep(2); runSurvey()" :disabled="!store.simId" class="btn-primary">
            <span class="material-symbols-outlined text-sm">play_arrow</span>
            Bắt đầu khảo sát
          </button>
        </div>
      </div>

      <!-- ═══════════ STEP 2: EXECUTE & RESULTS ═══════════ -->
      <div v-if="step === 2" class="step-panel">
        <!-- Loading state -->
        <div v-if="loading" class="executing">
          <div class="exec-spinner"></div>
          <h2 class="panel-title">Đang khảo sát agent...</h2>
          <p class="panel-desc">Mỗi agent sẽ trả lời {{ questions.length }} câu hỏi thông qua LLM. Quá trình này có thể mất vài phút.</p>
          <div class="exec-meta">
            <span>{{ config.numAgents }} agents</span>
            <span>•</span>
            <span>{{ questions.length }} câu hỏi</span>
            <span>•</span>
            <span>{{ config.includeContext ? 'Có ngữ cảnh' : 'Không ngữ cảnh' }}</span>
          </div>
        </div>

        <!-- Results -->
        <template v-if="results && !loading">
          <div class="results-header">
            <h2 class="panel-title">Kết quả khảo sát</h2>
            <div class="results-meta">
              <span class="meta-chip">{{ results.total_respondents }} respondents</span>
              <span class="meta-chip">{{ results.questions?.length || 0 }} câu hỏi</span>
              <span class="meta-chip done">HOÀN THÀNH</span>
            </div>
          </div>

          <!-- Question result cards -->
          <div class="results-grid">
            <div v-for="(q, qi) in results.questions" :key="q.question_id"
              :class="['result-card', qi % 2 === 0 ? 'wide' : 'narrow']">
              <h3 class="result-q-text">{{ q.question_text }}</h3>

              <!-- Scale -->
              <template v-if="q.question_type === 'scale_1_10' || q.question_type === 'rating'">
                <div class="scale-result">
                  <span class="scale-big">{{ q.average?.toFixed(1) || '—' }}</span>
                  <span class="scale-max">/10</span>
                </div>
                <div class="scale-bar">
                  <div class="scale-fill" :style="{ width: ((q.average || 0) * 10) + '%' }"></div>
                </div>
                <div class="response-list">
                  <div v-for="r in q.responses" :key="r.agent_name" class="response-row">
                    <span class="resp-name">{{ r.agent_name }} <span class="resp-role">({{ r.agent_role }})</span></span>
                    <span :class="['resp-score', parseFloat(r.answer) >= 5 ? 'good' : 'bad']">{{ r.answer }}</span>
                  </div>
                </div>
              </template>

              <!-- Yes/No -->
              <template v-else-if="q.question_type === 'yes_no'">
                <div class="yesno-result">
                  <span class="yesno-pct">{{ yesPercent(q) }}%</span>
                  <span class="yesno-label">{{ q.distribution?.YES || 0 }}/{{ q.responses?.length || 0 }} confirmed</span>
                </div>
              </template>

              <!-- Open-ended -->
              <template v-else-if="q.question_type === 'open_ended'">
                <div v-if="q.key_themes?.length" class="themes">
                  <span v-for="t in q.key_themes" :key="t" class="theme-chip">{{ t }}</span>
                </div>
                <div class="open-responses">
                  <div v-for="r in q.responses?.slice(0, 4)" :key="r.agent_name" class="open-row">
                    <div class="agent-avatar">{{ r.agent_name?.charAt(0) || '?' }}</div>
                    <div>
                      <span class="resp-name-sm">{{ r.agent_name }}</span>
                      <p class="resp-text">"{{ truncate(r.answer, 100) }}"</p>
                    </div>
                  </div>
                </div>
              </template>

              <!-- Multiple choice -->
              <template v-else-if="q.question_type === 'multiple_choice' && q.distribution">
                <div class="mc-chart">
                  <svg class="donut" viewBox="0 0 36 36">
                    <circle v-for="(seg, si) in donutSegments(q)" :key="si"
                      cx="18" cy="18" fill="none" r="16"
                      :stroke="seg.color" :stroke-dasharray="seg.dash" :stroke-dashoffset="seg.offset"
                      stroke-width="3" />
                  </svg>
                  <div class="donut-center">
                    <span>{{ Object.keys(q.distribution).length }}</span>
                    <small>Options</small>
                  </div>
                </div>
                <div class="mc-legend">
                  <div v-for="(count, label) in q.distribution" :key="label" class="legend-item">
                    <div class="legend-dot" :style="{ background: distColors[Object.keys(q.distribution).indexOf(label) % distColors.length] }"></div>
                    <span>{{ label }} ({{ count }})</span>
                  </div>
                </div>
              </template>

              <!-- Fallback -->
              <template v-else>
                <div class="response-list" v-if="q.responses?.length">
                  <div v-for="r in q.responses" :key="r.agent_name" class="response-row">
                    <span class="resp-name">{{ r.agent_name }} <span class="resp-role">({{ r.agent_role }})</span></span>
                    <p class="resp-text-sm">{{ r.answer }}</p>
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- Cross Analysis Table -->
          <div v-if="results.cross_analysis && Object.keys(results.cross_analysis).length" class="cross-section">
            <h3 class="section-title">Cross-Agent Analysis</h3>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th v-for="q in results.questions" :key="q.question_id">{{ q.question_id }}</th>
                    <th class="text-right">Role</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(data, agentName) in results.cross_analysis" :key="agentName">
                    <td class="font-mono">{{ agentName }}</td>
                    <td v-for="q in results.questions" :key="q.question_id">
                      <span :class="getAnswerColor(data[q.question_id])">{{ truncate(String(data[q.question_id] || '—'), 20) }}</span>
                    </td>
                    <td class="text-right"><span class="role-tag">{{ data.role || '—' }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Bottom actions -->
          <div class="step-actions mt-8">
            <button @click="exportJson" class="btn-secondary">
              <span class="material-symbols-outlined text-sm">ios_share</span>
              Export JSON
            </button>
            <div class="flex gap-3">
              <button @click="resetSurvey" class="btn-secondary">
                <span class="material-symbols-outlined text-sm">refresh</span>
                Khảo sát mới
              </button>
              <router-link to="/" class="btn-ghost">
                <span class="material-symbols-outlined text-sm">arrow_back</span>
                Dashboard
              </router-link>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { surveyApi } from '../api/client'
import { useAppStore } from '../stores/appStore'

const store = useAppStore()

const step = ref(0)
const stepLabels = ['Câu hỏi', 'Cấu hình', 'Khảo sát']
const loading = ref(false)
const error = ref('')
const results = ref(null)
const loadingDefaults = ref(false)

const questions = ref([])
const newQ = reactive({
  text: '',
  question_type: 'open_ended',
  category: 'general',
  optionsStr: '',
})

const config = reactive({
  numAgents: 10,
  maxAgents: 10,
  includeContext: true,
})

const distColors = ['#66BB6A','#FF8A80','#FFE066','#D5C4F7','#B5E8F0','#FB923C']

function goStep(s) { step.value = s }

function typeLabel(t) {
  const map = { scale_1_10: 'Thang 1-10', yes_no: 'Có/Không', open_ended: 'Tự do', multiple_choice: 'Trắc nghiệm' }
  return map[t] || t
}

function truncate(s, max) {
  return s && s.length > max ? s.slice(0, max) + '…' : s
}

function yesPercent(q) {
  const total = q.responses?.length || 1
  const yes = q.distribution?.YES || 0
  return Math.round((yes / total) * 100)
}

function donutSegments(q) {
  const entries = Object.entries(q.distribution || {})
  const total = entries.reduce((a, [, v]) => a + v, 0) || 1
  let offset = 0
  return entries.map(([, count], i) => {
    const pct = (count / total) * 100
    const seg = { color: distColors[i % distColors.length], dash: `${pct} ${100 - pct}`, offset: -offset }
    offset += pct
    return seg
  })
}

function getAnswerColor(val) {
  if (val === undefined || val === null) return 'neutral'
  const str = String(val).toLowerCase()
  if (str === 'yes' || str === 'positive') return 'good'
  if (str === 'no' || str === 'negative') return 'bad'
  const num = parseFloat(val)
  if (!isNaN(num)) return num >= 5 ? 'good' : 'bad'
  return 'neutral'
}

async function loadDefaults() {
  loadingDefaults.value = true
  try {
    const res = await surveyApi.defaultQuestions()
    const dqs = res.data.questions || []
    questions.value = dqs.map((q, i) => ({
      id: q.id || `q${i + 1}`,
      text: q.text,
      question_type: q.question_type,
      options: q.options || [],
      category: q.category || 'general',
    }))
  } catch {
    // Fallback: hardcoded defaults
    questions.value = [
      { id: 'q1', text: 'Bạn đánh giá mức độ tác động của chiến dịch này?', question_type: 'scale_1_10', options: [], category: 'economic' },
      { id: 'q2', text: 'Bạn có thay đổi hành vi sau biến cố không?', question_type: 'yes_no', options: [], category: 'behavior' },
      { id: 'q3', text: 'Cảm nhận chung của bạn về chiến dịch?', question_type: 'multiple_choice', options: ['Rất tích cực', 'Tích cực', 'Trung lập', 'Tiêu cực', 'Rất tiêu cực'], category: 'sentiment' },
      { id: 'q4', text: 'Đâu là rủi ro lớn nhất mà chiến dịch có thể gặp?', question_type: 'open_ended', options: [], category: 'economic' },
      { id: 'q5', text: 'Nếu có biến cố tương tự, bạn sẽ phản ứng thế nào?', question_type: 'open_ended', options: [], category: 'behavior' },
    ]
  } finally {
    loadingDefaults.value = false
  }
}

function addQuestion() {
  if (!newQ.text.trim()) return
  const opts = newQ.question_type === 'multiple_choice' && newQ.optionsStr
    ? newQ.optionsStr.split(',').map(s => s.trim()).filter(Boolean)
    : []
  questions.value.push({
    id: `q${questions.value.length + 1}`,
    text: newQ.text.trim(),
    question_type: newQ.question_type,
    options: opts,
    category: newQ.category,
  })
  newQ.text = ''
  newQ.optionsStr = ''
}

function removeQuestion(idx) { questions.value.splice(idx, 1) }
function clearQuestions() { questions.value = [] }

function resetSurvey() {
  step.value = 0
  results.value = null
  questions.value = []
  error.value = ''
}

async function runSurvey() {
  let simIdToUse = store.simId
  if (!simIdToUse) {
    try {
      const { reportApi } = await import('../api/client')
      const simsRes = await reportApi.listSims()
      const sims = simsRes.data?.simulations || []
      const withDb = sims.find(s => s.has_db)
      if (withDb) { simIdToUse = withDb.sim_id; store.setSimId(simIdToUse) }
    } catch {}
  }
  if (!simIdToUse) { error.value = 'Không tìm thấy simulation. Hãy hoàn thành simulation trước.'; step.value = 1; return }

  loading.value = true
  error.value = ''
  try {
    const qPayload = questions.value.map(q => ({
      text: q.text,
      question_type: q.question_type,
      options: q.options,
      category: q.category,
    }))
    const createRes = await surveyApi.create(simIdToUse, qPayload, {
      numAgents: config.numAgents,
      includeSimContext: config.includeContext,
    })
    const surveyId = createRes.data.survey_id
    store.setSurveyId(surveyId)

    await surveyApi.conduct(surveyId)
    const res = await surveyApi.results(surveyId)
    results.value = res.data
  } catch (e) {
    error.value = e.response?.data?.detail || e.response?.data?.error || 'Khảo sát thất bại'
    step.value = 1
  } finally {
    loading.value = false
  }
}

async function exportJson() {
  const surveyIdToUse = store.surveyId || results.value?.survey_id
  if (!surveyIdToUse) return
  try {
    const res = await surveyApi.export(surveyIdToUse)
    const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `survey_${surveyIdToUse}.json`; a.click()
    URL.revokeObjectURL(url)
  } catch { error.value = 'Export thất bại' }
}

onMounted(async () => {
  // Try loading existing results
  try {
    if (store.surveyId) {
      const res = await surveyApi.results(store.surveyId)
      if (res.data) { results.value = res.data; step.value = 2 }
    } else if (store.simId) {
      const res = await surveyApi.latest(store.simId)
      if (res.data?.found && res.data.results) {
        results.value = res.data.results
        if (res.data.survey_id) store.setSurveyId(res.data.survey_id)
        step.value = 2
      }
    }
  } catch {}

  // Try to get max agent count
  try {
    if (store.simId) {
      const { simApi } = await import('../api/client')
      const pRes = await simApi.profiles(store.simId)
      const count = pRes.data?.profiles?.length || pRes.data?.length || 10
      config.maxAgents = count
      config.numAgents = Math.min(config.numAgents, count)
    }
  } catch {}
})
</script>

<style scoped>
/* ═══════════ MEMPHIS SURVEY WIZARD ═══════════ */
.survey-root {
  font-family: 'DM Sans', system-ui, sans-serif;
}

/* ── Stepper ── */
.stepper {
  display: flex;
  align-items: center;
  gap: 32px;
  margin-bottom: 32px;
  padding: 16px 24px;
  background: #FFFFFF;
  border: 2px solid #E0DDD5;
  box-shadow: 4px 4px 0 rgba(45, 43, 85, 0.15);
  position: relative;
  overflow: hidden;
}

.step-line {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 3px;
  background: #66BB6A;
  transition: width 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.step-item {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  opacity: 0.4;
  transition: opacity 0.2s;
}
.step-item.active, .step-item.done { opacity: 1; }

.step-num {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid #E0DDD5;
  font-family: 'Space Mono', monospace;
  font-weight: 700;
  font-size: 12px;
  background: #FBF8F3;
  transition: all 0.2s;
}
.step-item.active .step-num {
  background: #FFE066;
  border-color: #2D2D2D;
  box-shadow: 2px 2px 0 #9B59B6;
}
.step-item.done .step-num {
  background: #66BB6A;
  border-color: #66BB6A;
  color: white;
}

.step-label {
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #2D2D2D;
}

/* ── Error bar ── */
.error-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  margin-bottom: 16px;
  background: #FFF5F5;
  border: 2px solid #FF8A80;
  color: #FF8A80;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  box-shadow: 3px 3px 0 rgba(255, 107, 107, 0.15);
}

/* ── Panels ── */
.step-panel {
  animation: fadeUp 0.3s ease;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.panel-title {
  font-family: 'Space Mono', monospace;
  font-size: 20px;
  font-weight: 700;
  color: #2D2D2D;
  margin-bottom: 4px;
}

.panel-desc {
  font-size: 13px;
  color: #6B6B6B;
  margin-bottom: 24px;
}

/* ── Buttons ── */
.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  background: #66BB6A;
  color: #F5F0E8;
  font-family: 'Space Mono', monospace;
  font-weight: 700;
  font-size: 12px;
  border: 2px solid #F5F0E8;
  box-shadow: 4px 4px 0 #9B59B6;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.btn-primary:hover:not(:disabled) { transform: translate(-2px, -2px); box-shadow: 6px 6px 0 #9B59B6; }
.btn-primary:active { transform: translate(2px, 2px); box-shadow: none; }
.btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: #FFFFFF;
  color: #2D2D2D;
  font-family: 'Space Mono', monospace;
  font-weight: 700;
  font-size: 11px;
  border: 2px solid #E0DDD5;
  box-shadow: 3px 3px 0 rgba(45, 43, 85, 0.15);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.btn-secondary:hover { transform: translate(-1px, -1px); box-shadow: 4px 4px 0 #D5C4F7; }
.btn-secondary:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: transparent;
  color: #6B6B6B;
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  border: 1px dashed #E0DDD5;
  cursor: pointer;
  text-decoration: none;
  transition: color 0.2s;
}
.btn-ghost:hover { color: #2D2D2D; border-color: #2D2D2D; }

/* ── Questions List ── */
.questions-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 24px;
}

.question-card {
  background: #FFFFFF;
  border: 2px solid #E0DDD5;
  padding: 14px 18px;
  box-shadow: 3px 3px 0 rgba(45, 43, 85, 0.12);
  transition: all 0.2s;
}
.question-card:hover { box-shadow: 4px 4px 0 #D5C4F7; transform: translate(-1px, -1px); }

.q-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.q-index {
  font-family: 'Space Mono', monospace;
  font-weight: 700;
  font-size: 11px;
  color: #9B59B6;
  background: #F3EDFF;
  padding: 2px 8px;
  border: 1px solid #D5C4F7;
}

.q-type-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #6B6B6B;
  background: #FBF8F3;
  padding: 2px 6px;
  border: 1px solid #E0DDD5;
}

.q-delete {
  margin-left: auto;
  color: #E0DDD5;
  cursor: pointer;
  transition: color 0.2s;
  background: none;
  border: none;
  display: flex;
}
.q-delete:hover { color: #FF8A80; }

.q-text {
  font-size: 13px;
  color: #2D2D2D;
  line-height: 1.5;
}

.q-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.q-option-chip {
  font-size: 10px;
  font-family: 'JetBrains Mono', monospace;
  padding: 2px 8px;
  border: 1px solid #B5E8F0;
  color: #6B6B6B;
  background: #F0FAFB;
}

.empty-questions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px;
  text-align: center;
}
.empty-questions p {
  font-size: 12px;
  color: #6B6B6B;
}

/* ── Add Form ── */
.add-form {
  background: #FBF8F3;
  border: 2px dashed #E0DDD5;
  padding: 20px;
  margin-bottom: 24px;
}

.form-title {
  font-family: 'Space Mono', monospace;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  color: #9B59B6;
  margin-bottom: 12px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.form-group.full { grid-column: 1 / -1; }

.form-group label {
  display: block;
  font-size: 10px;
  font-family: 'Space Mono', monospace;
  text-transform: uppercase;
  color: #6B6B6B;
  margin-bottom: 4px;
  letter-spacing: 0.05em;
}

.form-group textarea,
.form-group input,
.form-group select {
  width: 100%;
  padding: 8px 12px;
  font-size: 13px;
  font-family: 'DM Sans', sans-serif;
  border: 2px solid #E0DDD5;
  background: #FFFFFF;
  color: #2D2D2D;
  outline: none;
  transition: border-color 0.2s;
}
.form-group textarea:focus,
.form-group input:focus,
.form-group select:focus {
  border-color: #66BB6A;
}

/* ── Config Cards ── */
.config-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}

.config-card {
  background: #FFFFFF;
  border: 2px solid #E0DDD5;
  padding: 24px;
  box-shadow: 4px 4px 0 rgba(45, 43, 85, 0.15);
}

.config-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #FFE066;
  border: 2px solid #2D2D2D;
  box-shadow: 2px 2px 0 #9B59B6;
  margin-bottom: 14px;
  color: #2D2D2D;
}
.config-icon.icon-brain {
  background: #D5C4F7;
}

.config-card h3 {
  font-family: 'Space Mono', monospace;
  font-size: 14px;
  font-weight: 700;
  color: #2D2D2D;
  margin-bottom: 4px;
}

.config-desc {
  font-size: 12px;
  color: #6B6B6B;
  margin-bottom: 16px;
}

.config-control {
  margin-bottom: 12px;
}

.slider {
  width: 100%;
  height: 6px;
  -webkit-appearance: none;
  appearance: none;
  background: #E0DDD5;
  outline: none;
  cursor: pointer;
}
.slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  background: #66BB6A;
  border: 2px solid #2D2D2D;
  cursor: pointer;
}

.slider-labels {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #6B6B6B;
}
.slider-value {
  font-weight: 700;
  color: #2D2D2D;
  font-size: 13px;
}

.config-badges {
  display: flex;
  gap: 6px;
}

.quick-badge {
  padding: 4px 12px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  border: 1px solid #E0DDD5;
  background: #FBF8F3;
  cursor: pointer;
  color: #6B6B6B;
  transition: all 0.15s;
}
.quick-badge:hover {
  background: #FFE066;
  border-color: #2D2D2D;
  color: #2D2D2D;
}

/* ── Knowledge Toggle ── */
.knowledge-toggle {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toggle-opt {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border: 2px solid #E0DDD5;
  background: #FBF8F3;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s;
}
.toggle-opt.active {
  border-color: #66BB6A;
  background: #F0FFF0;
  box-shadow: 3px 3px 0 rgba(102, 187, 106, 0.2);
}

.toggle-opt strong {
  display: block;
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  color: #2D2D2D;
  margin-bottom: 2px;
}

.toggle-opt span {
  font-size: 11px;
  color: #6B6B6B;
  line-height: 1.4;
}

/* ── Config Summary ── */
.config-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #FBF8F3;
  border: 1px solid #E0DDD5;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #6B6B6B;
  margin-bottom: 24px;
}
.config-summary .est {
  margin-left: auto;
  color: #9B59B6;
  font-weight: 700;
}

/* ── Step Actions ── */
.step-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #E0DDD5;
}

/* ── Executing ── */
.executing {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 0;
  text-align: center;
}

.exec-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #E0DDD5;
  border-top-color: #66BB6A;
  animation: spin 0.8s linear infinite;
  margin-bottom: 20px;
}
@keyframes spin { to { transform: rotate(360deg); } }

.exec-meta {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #6B6B6B;
}

/* ── Results ── */
.results-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.results-meta {
  display: flex;
  gap: 6px;
}

.meta-chip {
  padding: 3px 10px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  border: 1px solid #E0DDD5;
  color: #6B6B6B;
}
.meta-chip.done {
  background: #66BB6A;
  color: white;
  border-color: #66BB6A;
}

.results-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 32px;
}

.result-card {
  background: #FFFFFF;
  border: 2px solid #E0DDD5;
  padding: 20px;
  box-shadow: 3px 3px 0 rgba(45, 43, 85, 0.12);
  transition: all 0.2s;
}
.result-card:hover { box-shadow: 5px 5px 0 #D5C4F7; transform: translate(-1px, -1px); }
.result-card.wide { grid-column: span 3; }
.result-card.narrow { grid-column: span 2; }

.result-q-text {
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  color: #6B6B6B;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-bottom: 14px;
}

/* Scale */
.scale-result { display: flex; align-items: baseline; gap: 4px; margin-bottom: 8px; }
.scale-big { font-size: 42px; font-family: 'Space Mono', monospace; color: #2D2D2D; }
.scale-max { font-size: 18px; font-family: 'Space Mono', monospace; color: #6B6B6B; }
.scale-bar { width: 100%; height: 4px; background: #E0DDD5; }
.scale-fill { height: 100%; background: #66BB6A; transition: width 0.5s; }

/* Yes/No */
.yesno-result { text-align: center; padding: 20px 0; }
.yesno-pct { display: block; font-size: 56px; font-family: 'Space Mono', monospace; color: #66BB6A; line-height: 1; }
.yesno-label { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #6B6B6B; text-transform: uppercase; }

/* Responses */
.response-list { margin-top: 14px; }
.response-row { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; border-bottom: 1px solid #F0EDE5; }
.resp-name { font-size: 11px; color: #6B6B6B; }
.resp-role { font-family: 'JetBrains Mono', monospace; font-size: 9px; color: #E0DDD5; }
.resp-score { font-family: 'Space Mono', monospace; font-size: 13px; }
.resp-score.good { color: #66BB6A; }
.resp-score.bad { color: #FF8A80; }

/* Themes */
.themes { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.theme-chip { padding: 2px 8px; font-family: 'JetBrains Mono', monospace; font-size: 9px; text-transform: uppercase; border: 1px solid #E0DDD5; color: #6B6B6B; }

/* Open responses */
.open-responses { display: flex; flex-direction: column; gap: 10px; }
.open-row { display: flex; gap: 10px; }
.agent-avatar { width: 28px; height: 28px; background: #D5C4F7; border: 2px solid #9B59B6; display: flex; align-items: center; justify-content: center; font-family: 'Space Mono', monospace; font-size: 10px; color: #9B59B6; flex-shrink: 0; box-shadow: 2px 2px 0 rgba(155, 89, 182, 0.2); }
.resp-name-sm { font-size: 10px; font-weight: 700; color: #2D2D2D; display: block; }
.resp-text { font-size: 11px; color: #6B6B6B; font-style: italic; margin: 0; line-height: 1.4; }

/* Donut chart */
.mc-chart { position: relative; width: 120px; height: 120px; margin: 0 auto 12px; }
.donut { width: 100%; height: 100%; transform: rotate(-90deg); }
.donut-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.donut-center span { font-family: 'Space Mono', monospace; font-size: 20px; font-weight: 700; }
.donut-center small { font-size: 9px; color: #6B6B6B; text-transform: uppercase; }

.mc-legend { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 10px; color: #6B6B6B; text-transform: uppercase; }
.legend-dot { width: 8px; height: 8px; }

/* Cross Analysis */
.cross-section { margin-top: 32px; }
.section-title { font-family: 'Space Mono', monospace; font-size: 12px; font-weight: 700; text-transform: uppercase; color: #6B6B6B; letter-spacing: 0.05em; margin-bottom: 16px; }

.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; border: 2px solid #E0DDD5; }
thead tr { border-bottom: 2px solid #D5C4F7; }
th { font-family: 'Space Mono', monospace; font-size: 10px; font-weight: 700; text-transform: uppercase; padding: 10px; color: #FFE066; background: #2D2D2D; }
td { font-family: 'JetBrains Mono', monospace; font-size: 11px; padding: 8px 10px; border-bottom: 1px solid #F0EDE5; }
.role-tag { font-size: 9px; border: 1px solid #E0DDD5; padding: 2px 6px; color: #6B6B6B; }
.good { color: #66BB6A; }
.bad { color: #FF8A80; }
.neutral { color: #6B6B6B; }
.resp-text-sm { font-size: 11px; color: #6B6B6B; margin: 2px 0 0; }
</style>
