<template>
  <div class="interview-page">
    <!-- Left: Agent List -->
    <aside class="agent-sidebar">
      <div class="sidebar-header">
        <span class="material-symbols-outlined" style="font-size:20px;color:#2DD4A8">forum</span>
        <h2>Agent Interview</h2>
      </div>
      <p class="sidebar-desc" v-if="simId">
        <span class="sim-badge">{{ simId }}</span>
      </p>

      <!-- Loading state -->
      <div v-if="loadingAgents" class="loading-agents">
        <div class="spinner"></div>
        <span>Đang tải danh sách agent...</span>
      </div>

      <!-- Agent cards -->
      <div v-else class="agent-list">
        <div
          v-for="agent in agents"
          :key="agent.agent_id"
          class="agent-card"
          :class="{ active: selectedAgent?.agent_id === agent.agent_id }"
          @click="selectAgent(agent)"
        >
          <div class="agent-avatar" :style="{ background: avatarColor(agent.agent_id) }">
            {{ agent.avatar_letter }}
          </div>
          <div class="agent-info">
            <div class="agent-name">{{ agent.name }}</div>
            <div class="agent-handle">{{ agent.handle }}</div>
            <div class="agent-stats">
              <span title="Bài đăng"><span class="material-symbols-outlined stat-icon">edit_note</span>{{ agent.posts }}</span>
              <span title="Bình luận"><span class="material-symbols-outlined stat-icon">chat_bubble</span>{{ agent.comments }}</span>
              <span title="Lượt thích"><span class="material-symbols-outlined stat-icon">favorite</span>{{ agent.likes }}</span>
            </div>
          </div>
          <div class="agent-stance" :class="agent.stance">
            <span class="material-symbols-outlined">{{ agent.stance === 'positive' ? 'thumb_up' : agent.stance === 'negative' ? 'thumb_down' : 'radio_button_checked' }}</span>
          </div>
        </div>
      </div>

      <!-- No sim selected -->
      <div v-if="!simId && !loadingAgents" class="no-sim">
        <span class="material-symbols-outlined" style="font-size:32px;color:#4A5568">person_search</span>
        <p>Chạy mô phỏng trước để phỏng vấn agent</p>
      </div>
    </aside>

    <!-- Right: Chat Area -->
    <main class="chat-area">
      <!-- No agent selected -->
      <div v-if="!selectedAgent" class="empty-chat">
        <div class="memphis-deco">
          <div class="deco-circle"></div>
          <div class="deco-triangle"></div>
          <div class="deco-squiggle"></div>
        </div>
        <div class="empty-icon-geo">
          <span class="material-symbols-outlined">forum</span>
        </div>
        <h3>Chọn một Agent để phỏng vấn</h3>
        <p>Chọn agent từ danh sách bên trái để bắt đầu cuộc phỏng vấn.</p>
        <p class="hint">Agent sẽ trả lời dựa trên những gì họ thực sự đã làm trong mô phỏng.</p>
      </div>

      <!-- Chat active -->
      <template v-else>
        <!-- Agent header -->
        <div class="chat-header">
          <div class="chat-agent-avatar" :style="{ background: avatarColor(selectedAgent.agent_id) }">
            {{ selectedAgent.avatar_letter }}
          </div>
          <div class="chat-agent-info">
            <div class="chat-agent-name">{{ selectedAgent.name }}</div>
            <div class="chat-agent-meta">
              <span class="mbti-badge" v-if="selectedAgent.mbti">{{ selectedAgent.mbti }}</span>
              <span class="stance-text">{{ selectedAgent.stance }}</span>
              <span class="stat"><span class="material-symbols-outlined" style="font-size:12px">edit_note</span> {{ selectedAgent.posts }} bài</span>
              <span class="stat"><span class="material-symbols-outlined" style="font-size:12px">chat_bubble</span> {{ selectedAgent.comments }} comments</span>
            </div>
            <button class="profile-btn" @click="openProfile" :disabled="loadingProfile">
              <span class="material-symbols-outlined" style="font-size:14px">person</span>
              {{ loadingProfile ? 'Đang tải...' : 'Xem Prompt Profile' }}
            </button>
          </div>
          <button class="clear-btn" @click="clearChat" title="Xóa lịch sử chat">
            <span class="material-symbols-outlined">delete_sweep</span>
          </button>
        </div>

        <!-- Agent persona -->
        <div class="persona-bar" v-if="selectedAgent.persona_short">
          <span class="persona-label">Persona:</span>
          <span class="persona-text">{{ selectedAgent.persona_short }}</span>
        </div>

        <!-- Messages -->
        <div class="messages-container" ref="messagesRef">
          <!-- Welcome message -->
          <div class="welcome-block" v-if="chatMessages.length === 0">
            <div class="welcome-agent-ring" :style="{ '--ring-color': avatarColor(selectedAgent.agent_id) }">
              <span class="welcome-avatar" :style="{ background: avatarColor(selectedAgent.agent_id) }">{{ selectedAgent.avatar_letter }}</span>
            </div>
            <p class="welcome-text">Bắt đầu phỏng vấn <strong>{{ selectedAgent.name }}</strong></p>
            <p class="welcome-sub">Agent sẽ trả lời dựa trên dữ liệu mô phỏng thực tế</p>
            <div class="suggestions">
              <button v-for="(s, si) in suggestions" :key="s" @click="sendSuggestion(s)" class="suggestion-chip" :style="{ animationDelay: si * 80 + 'ms' }">{{ s }}</button>
            </div>
          </div>

          <!-- Chat messages -->
          <div
            v-for="(msg, i) in chatMessages"
            :key="i"
            class="message"
            :class="msg.role"
          >
            <div class="message-avatar" v-if="msg.role === 'assistant'" :style="{ background: avatarColor(selectedAgent.agent_id) }">
              {{ selectedAgent.avatar_letter }}
            </div>
            <div class="message-bubble" :class="msg.role + '-bubble'">
              <div class="message-text" v-html="formatMessage(msg.content)"></div>
              <div class="message-time">{{ msg.time || '' }}</div>
            </div>
          </div>

          <!-- Typing indicator -->
          <div v-if="sending" class="message assistant">
            <div class="message-avatar" :style="{ background: avatarColor(selectedAgent.agent_id) }">
              {{ selectedAgent.avatar_letter }}
            </div>
            <div class="message-bubble assistant-bubble typing">
              <div class="typing-shapes">
                <span class="shape-tri"></span>
                <span class="shape-circle"></span>
                <span class="shape-square"></span>
              </div>
              <span class="typing-text">Đang suy nghĩ...</span>
            </div>
          </div>
        </div>

        <!-- Input area -->
        <div class="chat-input-area">
          <div class="input-wrapper">
            <textarea
              ref="inputRef"
              v-model="inputText"
              @keydown.enter.exact.prevent="sendMessage"
              placeholder="Nhập câu hỏi phỏng vấn..."
              rows="1"
              :disabled="sending"
            ></textarea>
            <button
              class="send-btn"
              @click="sendMessage"
              :disabled="!inputText.trim() || sending"
            >
              <span class="material-symbols-outlined">send</span>
            </button>
          </div>
          <div class="input-hint">
            Enter để gửi • Agent trả lời dựa trên dữ liệu mô phỏng thực tế
          </div>
        </div>
      </template>
    </main>

    <!-- Profile Modal (Memphis) -->
    <Teleport to="body">
      <div v-if="showProfile" class="profile-overlay" @click.self="showProfile = false">
        <div class="profile-modal">
          <!-- Header -->
          <div class="profile-modal-header">
            <div class="profile-modal-title">
              <div class="profile-avatar-sm" :style="{ background: avatarColor(selectedAgent?.agent_id || 0) }">
                {{ selectedAgent?.avatar_letter || '?' }}
              </div>
              <div>
                <h3>{{ profileData?.name || selectedAgent?.name }}</h3>
                <div class="profile-meta-row">
                  <span class="mbti-tag" v-if="selectedAgent?.mbti">{{ selectedAgent.mbti }}</span>
                  <span class="stance-tag" :class="selectedAgent?.stance">{{ selectedAgent?.stance || 'neutral' }}</span>
                </div>
              </div>
            </div>
            <div class="profile-modal-actions">
              <button class="copy-btn" @click="copyPrompt" :title="copied ? 'Đã copy!' : 'Copy prompt'">
                <span class="material-symbols-outlined">{{ copied ? 'check' : 'content_copy' }}</span>
              </button>
              <button class="close-btn" @click="showProfile = false">
                <span class="material-symbols-outlined">close</span>
              </button>
            </div>
          </div>

          <!-- Stats Bar -->
          <div class="profile-stats-bar" v-if="profileData?.action_stats">
            <div class="pstat-card">
              <span class="pstat-num">{{ profileData.action_stats.posts }}</span>
              <span class="pstat-label">Bài đăng</span>
            </div>
            <div class="pstat-card">
              <span class="pstat-num">{{ profileData.action_stats.comments }}</span>
              <span class="pstat-label">Bình luận</span>
            </div>
            <div class="pstat-card">
              <span class="pstat-num">{{ profileData.action_stats.likes }}</span>
              <span class="pstat-label">Lượt thích</span>
            </div>
            <div class="pstat-card">
              <span class="pstat-num">{{ profileData.action_stats.received_comments }}</span>
              <span class="pstat-label">Phản hồi</span>
            </div>
          </div>

          <!-- Body -->
          <div class="profile-modal-body">
            <!-- Context Section -->
            <div class="prompt-section" v-if="profileData?.context">
              <div class="prompt-label">
                <span class="material-symbols-outlined" style="font-size:14px">description</span>
                Dữ liệu hành động trong mô phỏng
              </div>
              <pre class="prompt-content context-content">{{ profileData.context }}</pre>
            </div>

            <!-- System Prompt Section -->
            <div class="prompt-section">
              <div class="prompt-label">
                <span class="material-symbols-outlined" style="font-size:14px">smart_toy</span>
                Full System Prompt (gửi cho LLM)
              </div>
              <pre class="prompt-content">{{ profileData?.system_prompt }}</pre>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import { interviewApi, reportApi } from '../api/client'
import { useAppStore } from '../stores/appStore'

const store = useAppStore()

const simId = ref('')
const agents = ref([])
const selectedAgent = ref(null)
const chatMessages = ref([])
const inputText = ref('')
const sending = ref(false)
const loadingAgents = ref(false)
const loadingProfile = ref(false)
const showProfile = ref(false)
const profileData = ref(null)
const copied = ref(false)
const messagesRef = ref(null)
const inputRef = ref(null)

const suggestions = [
  'Bạn đã đăng những bài viết gì trong mô phỏng?',
  'Bạn cảm thấy thế nào về chiến dịch?',
  'Bạn đã tương tác với ai nhiều nhất?',
  'Điều gì khiến bạn thích hoặc không thích về chiến dịch?',
]

const AVATAR_COLORS = [
  '#2DD4A8', '#D4A43E', '#A855F7', '#3B82F6', '#EF4444',
  '#06B6D4', '#F97316', '#EC4899', '#10B981', '#8B5CF6',
]

function avatarColor(id) {
  return AVATAR_COLORS[id % AVATAR_COLORS.length]
}

function formatMessage(text) {
  return text
    .replace(/\n/g, '<br>')
    .replace(/"([^"]+)"/g, '<em class="quote">"$1"</em>')
}

async function loadAgents() {
  if (!simId.value) return
  loadingAgents.value = true
  try {
    const res = await interviewApi.agents(simId.value)
    agents.value = res.data.agents || []
  } catch (e) {
    console.error('Failed to load agents:', e)
  } finally {
    loadingAgents.value = false
  }
}

async function selectAgent(agent) {
  selectedAgent.value = agent
  chatMessages.value = []

  // Load chat history
  try {
    const res = await interviewApi.history(simId.value, agent.agent_id)
    const history = res.data.history || []
    chatMessages.value = history.map(h => ({
      ...h,
      time: '',
    }))
  } catch {}

  await nextTick()
  scrollToBottom()
  inputRef.value?.focus()
}

function clearChat() {
  chatMessages.value = []
}

async function openProfile() {
  if (!selectedAgent.value || loadingProfile.value) return
  loadingProfile.value = true
  try {
    const res = await interviewApi.profile(simId.value, selectedAgent.value.agent_id)
    profileData.value = res.data
    showProfile.value = true
  } catch (e) {
    console.error('Failed to load profile:', e)
  } finally {
    loadingProfile.value = false
  }
}

function copyPrompt() {
  if (!profileData.value?.system_prompt) return
  navigator.clipboard.writeText(profileData.value.system_prompt)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || sending.value || !selectedAgent.value) return

  // Add user message
  const now = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
  chatMessages.value.push({ role: 'user', content: text, time: now })
  inputText.value = ''
  sending.value = true
  await nextTick()
  scrollToBottom()

  try {
    // Build history for context
    const history = chatMessages.value
      .filter(m => m.role !== 'system')
      .slice(-20)
      .map(m => ({ role: m.role, content: m.content }))

    const res = await interviewApi.chat(
      simId.value,
      selectedAgent.value.agent_id,
      text,
      history.slice(0, -1), // Exclude current message (it's in "message" param)
    )

    const replyTime = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
    chatMessages.value.push({
      role: 'assistant',
      content: res.data.response,
      time: replyTime,
    })
  } catch (e) {
    chatMessages.value.push({
      role: 'assistant',
      content: `❌ Lỗi: ${e.response?.data?.detail || e.message || 'Không thể kết nối'}`,
      time: '',
    })
  } finally {
    sending.value = false
    await nextTick()
    scrollToBottom()
    inputRef.value?.focus()
  }
}

function sendSuggestion(text) {
  inputText.value = text
  sendMessage()
}

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

onMounted(async () => {
  // Auto-detect simId
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
    } catch {}
  }
  if (simId.value) {
    await loadAgents()
  }
})
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=DM+Sans:wght@400;500;600&display=swap');

/* ===== MEMPHIS DESIGN TOKENS ===== */
.interview-page {
  --m-pink: #9B59B6;
  --m-yellow: #FFE066;
  --m-teal: #66BB6A;
  --m-blue: #B5E8F0;
  --m-coral: #FF8A80;
  --m-purple: #D5C4F7;
  --m-bg: #F5F0E8;
  --m-surface: #FFFFFF;
  --m-surface-2: #FBF8F3;
  --m-text: #2D2D2D;
  --m-text-dim: #6B6B6B;
  --m-border: #E0DDD5;

  display: flex;
  height: 100vh;
  background: var(--m-bg);
  color: var(--m-text);
  font-family: 'DM Sans', 'Space Mono', system-ui, sans-serif;
}

/* ===== AGENT SIDEBAR ===== */
.agent-sidebar {
  width: 340px;
  min-width: 340px;
  background: var(--m-surface);
  border-right: 3px solid var(--m-pink);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

/* Polka dot pattern overlay */
.agent-sidebar::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle, var(--m-purple) 1px, transparent 1px);
  background-size: 24px 24px;
  opacity: 0.06;
  pointer-events: none;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 16px 8px;
  position: relative;
  z-index: 1;
}

.sidebar-header h2 {
  font-family: 'Space Mono', sans-serif;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--m-yellow);
}

.sidebar-header .material-symbols-outlined {
  color: var(--m-pink) !important;
}

.sidebar-desc {
  padding: 0 16px 12px;
  position: relative;
  z-index: 1;
}

.sim-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--m-teal);
  background: rgba(107, 203, 119, 0.12);
  padding: 3px 10px;
  border: 2px solid var(--m-teal);
  box-shadow: 2px 2px 0 var(--m-teal);
}

.loading-agents {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 40px 16px;
  color: var(--m-text-dim);
  font-size: 13px;
  position: relative;
  z-index: 1;
}

.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid var(--m-border);
  border-top-color: var(--m-pink);
  border-right-color: var(--m-yellow);
  border-radius: 0;
  animation: spinSquare 1s linear infinite;
}

@keyframes spinSquare {
  to { transform: rotate(360deg); }
}

.agent-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 10px;
  position: relative;
  z-index: 1;
}

.agent-list::-webkit-scrollbar { width: 6px; }
.agent-list::-webkit-scrollbar-thumb { background: var(--m-purple); border-radius: 0; }
.agent-list::-webkit-scrollbar-track { background: transparent; }

.agent-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  margin-bottom: 4px;
  border: 2px solid transparent;
  background: transparent;
  position: relative;
}

.agent-card:hover {
  background: rgba(132, 94, 194, 0.08);
  border-color: var(--m-purple);
  transform: translateX(4px);
}

.agent-card:active {
  transform: translateX(4px) scale(0.98);
}

.agent-card.active {
  background: rgba(255, 107, 157, 0.08);
  border: 2px solid var(--m-pink);
  box-shadow: 4px 4px 0 var(--m-pink);
}

.agent-avatar {
  width: 42px;
  height: 42px;
  border-radius: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Space Mono', sans-serif;
  font-weight: 700;
  font-size: 17px;
  color: var(--m-bg);
  flex-shrink: 0;
  border: 2px solid var(--m-bg);
  box-shadow: 2px 2px 0 rgba(0,0,0,0.3);
}

.agent-info { flex: 1; min-width: 0; }

.agent-name {
  font-family: 'Space Mono', sans-serif;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.agent-handle {
  font-size: 11px;
  color: var(--m-text-dim);
  font-family: 'JetBrains Mono', monospace;
}

.agent-stats {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--m-text-dim);
  margin-top: 3px;
}

.agent-stats span {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.stat-icon {
  font-size: 13px !important;
  opacity: 0.7;
}

.agent-stance { flex-shrink: 0; }
.agent-stance .material-symbols-outlined { font-size: 16px; opacity: 0.5; }
.agent-stance.positive .material-symbols-outlined { color: var(--m-teal); opacity: 1; }
.agent-stance.negative .material-symbols-outlined { color: var(--m-coral); opacity: 1; }

.no-sim {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 20px;
  text-align: center;
  color: var(--m-text-dim);
  font-size: 13px;
  position: relative;
  z-index: 1;
}

/* ===== CHAT AREA ===== */
.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

/* ===== EMPTY STATE — MEMPHIS GEOMETRIC ===== */
.empty-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  color: var(--m-text-dim);
  position: relative;
  overflow: hidden;
}

/* Decorative Memphis shapes */
.memphis-deco {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.deco-circle {
  position: absolute;
  top: 15%;
  right: 20%;
  width: 120px;
  height: 120px;
  border: 4px solid var(--m-pink);
  border-radius: 50%;
  opacity: 0.15;
  animation: floatGeo 6s ease-in-out infinite;
}

.deco-triangle {
  position: absolute;
  bottom: 20%;
  left: 15%;
  width: 0;
  height: 0;
  border-left: 50px solid transparent;
  border-right: 50px solid transparent;
  border-bottom: 86px solid var(--m-yellow);
  opacity: 0.1;
  animation: floatGeo 8s ease-in-out infinite reverse;
}

.deco-squiggle {
  position: absolute;
  top: 40%;
  left: 60%;
  width: 80px;
  height: 80px;
  border: 4px solid var(--m-teal);
  border-radius: 0 50% 50% 0;
  opacity: 0.12;
  animation: floatGeo 7s ease-in-out infinite 1s;
}

@keyframes floatGeo {
  0%, 100% { transform: translate(0, 0) rotate(0deg); }
  25% { transform: translate(10px, -15px) rotate(5deg); }
  50% { transform: translate(-5px, 10px) rotate(-3deg); }
  75% { transform: translate(8px, 5px) rotate(2deg); }
}

.empty-icon-geo {
  width: 80px;
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 3px solid var(--m-yellow);
  box-shadow: 5px 5px 0 var(--m-pink);
  position: relative;
  z-index: 1;
  background: var(--m-surface);
}

.empty-icon-geo .material-symbols-outlined {
  font-size: 36px;
  color: var(--m-yellow);
}

.empty-chat h3 {
  font-family: 'Space Mono', sans-serif;
  font-size: 20px;
  color: var(--m-text);
  font-weight: 700;
  position: relative;
  z-index: 1;
}

.empty-chat p {
  font-size: 13px;
  max-width: 360px;
  text-align: center;
  position: relative;
  z-index: 1;
}

.hint {
  font-size: 12px;
  color: var(--m-teal);
  font-style: italic;
}

/* ===== CHAT HEADER — ZIGZAG BOTTOM ===== */
.chat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 24px;
  background: var(--m-surface);
  border-bottom: 3px solid var(--m-yellow);
  position: relative;
}

/* Zigzag decoration */
.chat-header::after {
  content: '';
  position: absolute;
  bottom: -11px;
  left: 0;
  right: 0;
  height: 8px;
  background: linear-gradient(135deg, var(--m-surface) 33.33%, transparent 33.33%) 0 0,
              linear-gradient(225deg, var(--m-surface) 33.33%, transparent 33.33%) 0 0;
  background-size: 12px 8px;
  background-repeat: repeat-x;
  z-index: 2;
}

.chat-agent-avatar {
  width: 44px;
  height: 44px;
  border-radius: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Space Mono', sans-serif;
  font-weight: 700;
  font-size: 18px;
  color: var(--m-bg);
  border: 2px solid var(--m-bg);
  box-shadow: 3px 3px 0 var(--m-pink);
}

.chat-agent-info { flex: 1; }

.chat-agent-name {
  font-family: 'Space Mono', sans-serif;
  font-size: 16px;
  font-weight: 700;
  color: var(--m-text);
}

.chat-agent-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--m-text-dim);
  margin-top: 3px;
}

.chat-agent-meta .stat {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.mbti-badge {
  background: rgba(255, 107, 157, 0.15);
  color: var(--m-pink);
  padding: 2px 8px;
  font-weight: 700;
  font-family: 'Space Mono', sans-serif;
  font-size: 10px;
  border: 2px solid var(--m-pink);
  box-shadow: 2px 2px 0 var(--m-pink);
}

.stance-text { text-transform: capitalize; color: var(--m-blue); }

.clear-btn {
  background: none;
  border: 2px solid var(--m-coral);
  color: var(--m-coral);
  width: 36px;
  height: 36px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.clear-btn:hover {
  background: var(--m-coral);
  color: var(--m-bg);
  box-shadow: 3px 3px 0 rgba(255, 107, 107, 0.4);
}

.clear-btn:active { transform: translate(2px, 2px); box-shadow: none; }
.clear-btn .material-symbols-outlined { font-size: 18px; }

/* ===== PERSONA BAR ===== */
.persona-bar {
  padding: 8px 24px;
  background: var(--m-surface-2);
  border-bottom: 2px dashed var(--m-purple);
  font-size: 12px;
  color: var(--m-text-dim);
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.persona-label { color: var(--m-yellow); font-weight: 700; flex-shrink: 0; font-family: 'Space Mono', sans-serif; }
.persona-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ===== WELCOME BLOCK ===== */
.welcome-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 40px;
  position: relative;
}

/* Dotted grid background for welcome */
.welcome-block::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(circle, var(--m-pink) 1px, transparent 1px),
    radial-gradient(circle, var(--m-blue) 1px, transparent 1px);
  background-size: 40px 40px;
  background-position: 0 0, 20px 20px;
  opacity: 0.04;
  pointer-events: none;
}

.welcome-agent-ring {
  width: 80px;
  height: 80px;
  border: 4px solid var(--ring-color);
  box-shadow: 5px 5px 0 var(--m-yellow);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 1;
  animation: wobble 3s ease-in-out infinite;
}

@keyframes wobble {
  0%, 100% { transform: rotate(0deg); }
  25% { transform: rotate(3deg); }
  75% { transform: rotate(-3deg); }
}

.welcome-avatar {
  width: 68px;
  height: 68px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Space Mono', sans-serif;
  font-weight: 800;
  font-size: 28px;
  color: var(--m-bg);
}

.welcome-text {
  font-family: 'Space Mono', sans-serif;
  font-size: 18px;
  color: var(--m-text);
  font-weight: 700;
  position: relative;
  z-index: 1;
}

.welcome-sub {
  font-size: 12px;
  color: var(--m-text-dim);
  margin-top: -4px;
  position: relative;
  z-index: 1;
}

.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
  justify-content: center;
  max-width: 620px;
  position: relative;
  z-index: 1;
}

.suggestion-chip {
  background: var(--m-surface);
  border: 2px solid var(--m-purple);
  color: var(--m-text);
  padding: 8px 16px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  font-family: 'DM Sans', sans-serif;
  animation: chipBounce 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) backwards;
  box-shadow: 3px 3px 0 var(--m-purple);
}

.suggestion-chip:nth-child(odd) { transform: rotate(-1.5deg); }
.suggestion-chip:nth-child(even) { transform: rotate(1.5deg); }

.suggestion-chip:hover {
  background: var(--m-purple);
  color: white;
  transform: rotate(0deg) translateY(-3px);
  box-shadow: 4px 6px 0 rgba(132, 94, 194, 0.4);
}

.suggestion-chip:active {
  transform: translate(2px, 2px) rotate(0deg);
  box-shadow: 1px 1px 0 var(--m-purple);
}

@keyframes chipBounce {
  from { opacity: 0; transform: translateY(15px) scale(0.9); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

/* ===== MESSAGES ===== */
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 28px 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  position: relative;
}

/* Subtle dot pattern inside messages area */
.messages-container::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image: radial-gradient(circle, var(--m-yellow) 0.5px, transparent 0.5px);
  background-size: 30px 30px;
  opacity: 0.025;
  pointer-events: none;
  z-index: 0;
}

.messages-container::-webkit-scrollbar { width: 6px; }
.messages-container::-webkit-scrollbar-thumb { background: var(--m-pink); border-radius: 0; }

.message {
  display: flex;
  gap: 10px;
  max-width: 72%;
  animation: msgPop 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
  position: relative;
  z-index: 1;
}

@keyframes msgPop {
  from { opacity: 0; transform: translateY(16px) scale(0.95); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.message.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.message-avatar {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Space Mono', sans-serif;
  font-weight: 700;
  font-size: 13px;
  color: var(--m-bg);
  flex-shrink: 0;
  border: 2px solid var(--m-bg);
}

.message-bubble {
  padding: 12px 16px;
  font-size: 13.5px;
  line-height: 1.65;
}

/* User bubble — Hot Pink with Yellow hard shadow */
.user-bubble {
  background: var(--m-pink);
  color: #F5F0E8;
  border: 2px solid #E0507A;
  box-shadow: 4px 4px 0 var(--m-yellow);
  font-weight: 500;
}

/* Agent bubble — thick border + subtle pattern */
.assistant-bubble {
  background: var(--m-surface-2);
  color: var(--m-text);
  border: 2px solid var(--m-blue);
  box-shadow: 4px 4px 0 rgba(77, 150, 255, 0.2);
  position: relative;
}

.message-text :deep(.quote) {
  color: var(--m-yellow);
  font-style: italic;
  font-weight: 600;
}

.message-time {
  font-size: 10px;
  color: var(--m-text-dim);
  margin-top: 4px;
  text-align: right;
  font-family: 'JetBrains Mono', monospace;
}

.user-bubble .message-time {
  color: rgba(26, 26, 46, 0.5);
}

/* ===== TYPING — GEOMETRIC SHAPES BOUNCE ===== */
.typing {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
}

.typing-shapes {
  display: flex;
  gap: 6px;
  align-items: center;
}

/* Triangle */
.shape-tri {
  width: 0;
  height: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-bottom: 9px solid var(--m-pink);
  animation: geoBounce 1.4s ease-in-out infinite;
}

/* Circle */
.shape-circle {
  width: 9px;
  height: 9px;
  background: var(--m-yellow);
  border-radius: 50%;
  animation: geoBounce 1.4s ease-in-out infinite 0.15s;
}

/* Square */
.shape-square {
  width: 8px;
  height: 8px;
  background: var(--m-teal);
  animation: geoBounce 1.4s ease-in-out infinite 0.3s;
}

@keyframes geoBounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-10px) rotate(180deg); opacity: 1; }
}

.typing-text {
  font-size: 12px;
  color: var(--m-text-dim);
  font-style: italic;
}

/* ===== INPUT AREA — THICK BORDER + HARD SHADOW ===== */
.chat-input-area {
  padding: 16px 24px 20px;
  background: var(--m-surface);
  border-top: 3px solid var(--m-teal);
  position: relative;
}

/* Zigzag top decoration */
.chat-input-area::before {
  content: '';
  position: absolute;
  top: -11px;
  left: 0;
  right: 0;
  height: 8px;
  background: linear-gradient(315deg, var(--m-surface) 33.33%, transparent 33.33%) 0 0,
              linear-gradient(45deg, var(--m-surface) 33.33%, transparent 33.33%) 0 0;
  background-size: 12px 8px;
  background-repeat: repeat-x;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  background: var(--m-bg);
  border: 2px solid var(--m-blue);
  padding: 4px 4px 4px 16px;
  box-shadow: 4px 4px 0 var(--m-blue);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.input-wrapper:focus-within {
  border-color: var(--m-pink);
  box-shadow: 4px 4px 0 var(--m-pink);
}

.input-wrapper textarea {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: var(--m-text);
  font-size: 13.5px;
  font-family: 'DM Sans', sans-serif;
  resize: none;
  padding: 8px 0;
  max-height: 120px;
  line-height: 1.5;
}

.input-wrapper textarea::placeholder {
  color: var(--m-text-dim);
}

.send-btn {
  background: var(--m-yellow);
  border: 2px solid #D4B432;
  color: var(--m-bg);
  width: 40px;
  height: 40px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s cubic-bezier(0.34, 1.56, 0.64, 1);
  flex-shrink: 0;
  box-shadow: 2px 2px 0 var(--m-pink);
}

.send-btn:hover:not(:disabled) {
  transform: translate(-2px, -2px);
  box-shadow: 4px 4px 0 var(--m-pink);
}

.send-btn:active:not(:disabled) {
  transform: translate(2px, 2px);
  box-shadow: 0px 0px 0 var(--m-pink);
}

.send-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
  box-shadow: none;
}

.send-btn .material-symbols-outlined { font-size: 18px; }

.input-hint {
  font-size: 10px;
  color: var(--m-text-dim);
  text-align: center;
  margin-top: 8px;
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.03em;
}

/* ===== PROFILE BUTTON ===== */
.profile-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  padding: 3px 10px;
  background: transparent;
  border: 2px solid var(--m-teal);
  color: var(--m-teal);
  font-size: 10px;
  font-family: 'JetBrains Mono', monospace;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  box-shadow: 2px 2px 0 var(--m-teal);
}

.profile-btn:hover:not(:disabled) {
  background: var(--m-teal);
  color: var(--m-bg);
}

.profile-btn:active:not(:disabled) {
  transform: translate(1px, 1px);
  box-shadow: 1px 1px 0 var(--m-teal);
}

.profile-btn:disabled {
  opacity: 0.5;
  cursor: wait;
}

/* ── Profile Modal (uses Teleport, not scoped) ── */
</style>

<style>
.profile-overlay {
  position: fixed;
  inset: 0;
  background: rgba(45, 45, 45, 0.6);
  backdrop-filter: blur(4px);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.15s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.profile-modal {
  background: #F5F0E8;
  border: 3px solid #2D2D2D;
  width: 90%;
  max-width: 780px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 8px 8px 0 #9B59B6;
  animation: modalIn 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes modalIn {
  from { opacity: 0; transform: scale(0.95) translateY(12px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.profile-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 3px solid #2D2D2D;
  background: #FFFFFF;
}

.profile-modal-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.profile-avatar-sm {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Space Mono', monospace;
  font-weight: 700;
  font-size: 16px;
  color: #F5F0E8;
  border: 2px solid #2D2D2D;
  box-shadow: 3px 3px 0 #FFE066;
  flex-shrink: 0;
}

.profile-modal-title h3 {
  font-size: 16px;
  font-weight: 700;
  color: #2D2D2D;
  margin: 0;
  font-family: 'Space Mono', monospace;
}

.profile-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}

.mbti-tag {
  font-size: 10px;
  font-weight: 700;
  font-family: 'Space Mono', monospace;
  color: #9B59B6;
  background: rgba(155, 89, 182, 0.1);
  border: 1.5px solid #9B59B6;
  padding: 1px 8px;
}

.stance-tag {
  font-size: 10px;
  font-family: 'Space Mono', monospace;
  text-transform: capitalize;
  padding: 1px 8px;
  border: 1.5px solid #E0DDD5;
  color: #6B6B6B;
}

.stance-tag.positive { border-color: #66BB6A; color: #66BB6A; background: rgba(102, 187, 106, 0.08); }
.stance-tag.negative { border-color: #FF8A80; color: #FF8A80; background: rgba(255, 138, 128, 0.08); }

.profile-modal-actions {
  display: flex;
  gap: 6px;
}

.copy-btn, .close-btn {
  background: none;
  border: 2px solid #E0DDD5;
  color: #6B6B6B;
  width: 34px;
  height: 34px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.copy-btn:hover {
  background: rgba(102, 187, 106, 0.1);
  border-color: #66BB6A;
  color: #66BB6A;
  box-shadow: 2px 2px 0 #66BB6A;
}

.close-btn:hover {
  background: rgba(255, 138, 128, 0.1);
  border-color: #FF8A80;
  color: #FF8A80;
  box-shadow: 2px 2px 0 #FF8A80;
}

.copy-btn .material-symbols-outlined,
.close-btn .material-symbols-outlined {
  font-size: 16px;
}

/* Stats Bar */
.profile-stats-bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
  border-bottom: 3px solid #2D2D2D;
  background: #FFFFFF;
}

.pstat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 8px;
  border-right: 1.5px solid #E0DDD5;
}

.pstat-card:last-child { border-right: none; }

.pstat-num {
  font-family: 'Space Mono', monospace;
  font-size: 20px;
  font-weight: 700;
  color: #2D2D2D;
}

.pstat-label {
  font-size: 10px;
  font-family: 'Space Mono', monospace;
  color: #6B6B6B;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-top: 2px;
}

/* Body */
.profile-modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.profile-modal-body::-webkit-scrollbar { width: 6px; }
.profile-modal-body::-webkit-scrollbar-thumb { background: #D5C4F7; }
.profile-modal-body::-webkit-scrollbar-track { background: transparent; }

.prompt-section {
  margin-bottom: 20px;
}

.prompt-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  font-weight: 700;
  color: #9B59B6;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 8px;
  font-family: 'Space Mono', monospace;
}

.prompt-content {
  background: #FFFFFF;
  border: 2px solid #2D2D2D;
  padding: 16px;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.7;
  color: #2D2D2D;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 50vh;
  overflow-y: auto;
  margin: 0;
  box-shadow: 4px 4px 0 #E0DDD5;
}

.prompt-content::-webkit-scrollbar { width: 6px; }
.prompt-content::-webkit-scrollbar-thumb { background: #D5C4F7; }

.context-content {
  border-color: #FFE066;
  box-shadow: 4px 4px 0 #FFE066;
  max-height: 35vh;
}
</style>
