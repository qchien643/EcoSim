<template>
  <div class="campaign-memphis">
    <!-- Floating shapes -->
    <div class="memphis-deco">
      <div class="deco-circle"></div>
      <div class="deco-triangle"></div>
    </div>

    <!-- TOP BAR -->
    <header class="top-bar">
      <div class="top-bar-left">
        <span class="top-label">PROJECT</span>
        <span class="top-sep">/</span>
        <span class="top-active">CAMPAIGN UPLOAD</span>
      </div>
      <div class="top-bar-right">
        SYST_TIME <span class="time-value">{{ currentTime }}</span>
      </div>
    </header>

    <!-- Wizard Stepper -->
    <nav class="stepper-bar">
      <div v-for="(step, i) in stepLabels" :key="i" class="stepper-item">
        <div :class="['step-num', i === 0 ? 'active' : '']">{{ i + 1 }}</div>
        <span class="step-label">{{ step }}</span>
        <div v-if="i < stepLabels.length - 1" class="step-connector"></div>
      </div>
    </nav>

    <!-- Main content: 2 columns -->
    <div class="campaign-body">
      <!-- LEFT: Upload area -->
      <div class="upload-panel">
        <div class="panel-title-row">
          <span class="material-symbols-outlined panel-icon">description</span>
          <h2 class="panel-title">Campaign Input</h2>
        </div>
        <p class="panel-subtitle">Step 1 of 6 — System Initialization</p>

        <!-- Error -->
        <div v-if="error" class="error-bar">
          <span class="material-symbols-outlined">error</span>
          <span class="error-text">{{ error }}</span>
        </div>

        <!-- Upload zone -->
        <div
          @dragover.prevent="dragActive = true"
          @dragleave="dragActive = false"
          @drop.prevent="handleDrop"
          :class="['upload-zone', dragActive ? 'drag-active' : '']"
          @click="$refs.fileInput.click()"
        >
          <div class="upload-icon-box">
            <span class="material-symbols-outlined">upload_file</span>
          </div>
          <p class="upload-main">Drop files here or click to select</p>
          <p class="upload-hint">Supported: PDF, Markdown, TXT — Max 10MB</p>
          <input ref="fileInput" type="file" accept=".pdf,.md,.txt,.markdown" class="hidden-input" @change="handleFileSelect" />
        </div>

        <!-- Divider -->
        <div class="divider">
          <div class="divider-line"></div>
          <span class="divider-text">Or Enter Directly</span>
          <div class="divider-line"></div>
        </div>

        <!-- Text area -->
        <textarea
          v-model="textInput"
          class="text-input"
          placeholder="Describe your economic campaign details here for AI parsing..."
        ></textarea>

        <button
          @click="parseText"
          :disabled="!textInput.trim() || parsing"
          class="parse-btn"
        >
          <span v-if="parsing" class="parse-loading">
            <div class="mini-spinner"></div>
            PARSING...
          </span>
          <span v-else>PARSE CAMPAIGN</span>
        </button>

        <!-- Footer nav -->
        <div class="footer-nav">
          <router-link to="/" class="nav-back">
            <span class="material-symbols-outlined">arrow_back</span>
            <span>Back</span>
          </router-link>
          <div class="nav-right">
            <span class="autosave-status">AUTO_SAVE <span class="status-ok">SYNC</span></span>
            <router-link
              to="/graph"
              :class="['next-btn', spec ? 'ready' : 'disabled']"
            >
              Next: Knowledge Graph
              <span class="material-symbols-outlined">arrow_forward</span>
            </router-link>
          </div>
        </div>
      </div>

      <!-- RIGHT: Live Preview Panel -->
      <aside class="preview-panel" v-if="spec">
        <!-- Polka dot overlay -->
        <div class="preview-dots-overlay"></div>

        <div class="preview-header">
          <span class="preview-badge">LIVE_PREVIEW</span>
          <span class="preview-id">ID: {{ spec.campaign_id }}</span>
        </div>

        <!-- Campaign Name Block -->
        <div class="preview-block">
          <span class="preview-label">CAMPAIGN_NAME</span>
          <h3 class="preview-value-big">{{ spec.name }}</h3>
        </div>

        <!-- Budget block -->
        <div class="preview-block" v-if="spec.budget">
          <span class="preview-label">TOTAL_BUDGET</span>
          <div class="preview-value-highlight">{{ spec.budget }}</div>
        </div>

        <!-- Type & Market -->
        <div class="preview-grid-2">
          <div class="preview-block">
            <span class="preview-label">SECTOR_TYPE</span>
            <div class="preview-value">{{ spec.campaign_type }}</div>
          </div>
          <div class="preview-block">
            <span class="preview-label">GEO_TARGET</span>
            <div class="preview-value">{{ spec.market }}</div>
          </div>
        </div>

        <!-- Timeline -->
        <div class="preview-block" v-if="spec.timeline">
          <span class="preview-label">ACTIVE_WINDOW</span>
          <div class="preview-value">{{ spec.timeline }}</div>
        </div>

        <!-- Stakeholders -->
        <div class="preview-block" v-if="spec.stakeholders?.length">
          <span class="preview-label">STAKEHOLDER_MAPPING</span>
          <div class="tag-list">
            <span v-for="s in spec.stakeholders" :key="s" class="memphis-tag">{{ s }}</span>
          </div>
        </div>

        <!-- KPIs -->
        <div class="preview-block" v-if="spec.kpis?.length">
          <span class="preview-label">KPI_PROJECTIONS</span>
          <div class="kpi-list">
            <div v-for="kpi in spec.kpis" :key="kpi" class="kpi-item">{{ kpi }}</div>
          </div>
        </div>

        <!-- Risks -->
        <div class="preview-block" v-if="spec.identified_risks?.length">
          <span class="preview-label">RISK_FACTORS</span>
          <div class="risk-list">
            <div v-for="risk in spec.identified_risks" :key="risk" class="risk-item">
              <span class="material-symbols-outlined risk-icon">warning</span>
              <span>{{ risk }}</span>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { campaignApi } from '../api/client'
import { useAppStore } from '../stores/appStore'

const store = useAppStore()

const parsing = ref(false)
const error = ref('')
const textInput = ref('')
const dragActive = ref(false)
const spec = ref(null)
const currentTime = ref('')
const stepLabels = ['INPUT', 'GRAPH', 'SIMUL', 'RISK', 'OPTIM', 'FINAL']

function updateTime() {
  currentTime.value = new Date().toLocaleTimeString('en-US', { hour12: false })
}

onMounted(async () => {
  updateTime()
  setInterval(updateTime, 1000)
  if (store.campaignId) {
    try {
      const res = await campaignApi.get(store.campaignId)
      spec.value = res.data.spec
    } catch { /* campaign not found */ }
  }
})

async function handleFileSelect(e) {
  const file = e.target.files[0]
  if (file) await uploadFile(file)
}

async function handleDrop(e) {
  dragActive.value = false
  const file = e.dataTransfer.files[0]
  if (file) await uploadFile(file)
}

async function uploadFile(file) {
  parsing.value = true
  error.value = ''
  try {
    const res = await campaignApi.upload(file)
    spec.value = res.data.spec
    store.setCampaignId(res.data.campaign_id)
    store.setCampaignSpec(res.data.spec)
    store.completeStep('campaign')
  } catch (e) {
    error.value = e.response?.data?.error || 'Upload failed'
  } finally {
    parsing.value = false
  }
}

async function parseText() {
  if (!textInput.value.trim()) return
  parsing.value = true
  error.value = ''
  try {
    const res = await campaignApi.parse(textInput.value)
    spec.value = res.data.spec
    store.setCampaignId(res.data.campaign_id)
    store.setCampaignSpec(res.data.spec)
    store.completeStep('campaign')
  } catch (e) {
    error.value = e.response?.data?.error || 'Parse failed'
  } finally {
    parsing.value = false
  }
}
</script>

<style scoped>
/* ===== CAMPAIGN MEMPHIS ===== */
.campaign-memphis {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-family: 'DM Sans', system-ui, sans-serif;
  color: var(--m-text, #2D2D2D);
  position: relative;
}

/* ===== FLOATING SHAPES ===== */
.memphis-deco {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
}

.deco-circle {
  position: absolute;
  top: 20%;
  right: 10%;
  width: 140px;
  height: 140px;
  border: 4px solid var(--m-yellow, #FFE066);
  border-radius: 50%;
  opacity: 0.05;
  animation: floatGeo 9s ease-in-out infinite;
}

.deco-triangle {
  position: absolute;
  bottom: 10%;
  left: 8%;
  width: 0;
  height: 0;
  border-left: 40px solid transparent;
  border-right: 40px solid transparent;
  border-bottom: 70px solid var(--m-pink, #9B59B6);
  opacity: 0.05;
  animation: floatGeo 11s ease-in-out infinite reverse;
}

@keyframes floatGeo {
  0%, 100% { transform: translate(0, 0) rotate(0deg); }
  25% { transform: translate(12px, -18px) rotate(5deg); }
  50% { transform: translate(-8px, 12px) rotate(-3deg); }
  75% { transform: translate(10px, 6px) rotate(2deg); }
}

/* ===== TOP BAR ===== */
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 2rem;
  height: 52px;
  background: var(--m-bg, #F5F0E8);
  border-bottom: 3px solid var(--m-purple, #D5C4F7);
  flex-shrink: 0;
  position: relative;
  z-index: 2;
}

.top-bar::after {
  content: '';
  position: absolute;
  bottom: -11px;
  left: 0;
  right: 0;
  height: 8px;
  background: linear-gradient(135deg, var(--m-bg, #F5F0E8) 33.33%, transparent 33.33%) 0 0,
              linear-gradient(225deg, var(--m-bg, #F5F0E8) 33.33%, transparent 33.33%) 0 0;
  background-size: 12px 8px;
  background-repeat: repeat-x;
  z-index: 2;
}

.top-bar-left { display: flex; align-items: center; gap: 8px; }
.top-label { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--m-text-dim, #6B6B6B); letter-spacing: 0.2em; text-transform: uppercase; }
.top-sep { color: var(--m-border, #E0DDD5); }
.top-active { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--m-teal, #66BB6A); letter-spacing: 0.2em; text-transform: uppercase; font-weight: 600; }
.top-bar-right { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--m-text-dim, #6B6B6B); }
.time-value { color: var(--m-text, #2D2D2D); }

/* ===== STEPPER — MEMPHIS NUMBERED SQUARES ===== */
.stepper-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 1rem 2rem;
  background: var(--m-bg, #F5F0E8);
  border-bottom: 2px solid var(--m-border, #E0DDD5);
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}

.stepper-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-num {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--m-border, #E0DDD5);
  font-family: 'Space Mono', sans-serif;
  font-size: 12px;
  font-weight: 700;
  color: var(--m-text-dim, #6B6B6B);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.step-num.active {
  background: var(--m-teal, #66BB6A);
  border-color: var(--m-teal, #66BB6A);
  color: var(--m-bg, #F5F0E8);
  box-shadow: 3px 3px 0 rgba(107, 203, 119, 0.4);
}

.step-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--m-text-dim, #6B6B6B);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  display: none;
}

@media (min-width: 768px) {
  .step-label { display: block; }
}

.step-connector {
  width: 32px;
  height: 2px;
  background: var(--m-border, #E0DDD5);
}

/* ===== CAMPAIGN BODY ===== */
.campaign-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* ===== UPLOAD PANEL ===== */
.upload-panel {
  flex: 1;
  padding: 2rem;
  overflow-y: auto;
}

.panel-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}

.panel-icon { color: var(--m-yellow, #FFE066); font-size: 24px; }

.panel-title {
  font-family: 'Space Mono', sans-serif;
  font-size: 22px;
  font-weight: 700;
  color: var(--m-text, #2D2D2D);
  letter-spacing: -0.01em;
}

.panel-subtitle {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--m-text-dim, #6B6B6B);
  margin-bottom: 2rem;
}

/* Error bar */
.error-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0.75rem 1.5rem;
  border: 2px solid var(--m-coral, #FF8A80);
  box-shadow: 3px 3px 0 rgba(255, 107, 107, 0.2);
  margin-bottom: 1rem;
  background: var(--m-surface, #FFFFFF);
}

.error-bar .material-symbols-outlined { color: var(--m-coral, #FF8A80); font-size: 18px; }
.error-text { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--m-coral, #FF8A80); }

/* ===== UPLOAD ZONE — MEMPHIS DASHED ===== */
.upload-zone {
  border: 3px dashed var(--m-purple, #D5C4F7);
  padding: 3rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  cursor: pointer;
  margin-bottom: 2rem;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
  position: relative;
}

/* Polka dot on upload zone */
.upload-zone::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle, var(--m-purple, #D5C4F7) 1px, transparent 1px);
  background-size: 20px 20px;
  opacity: 0.04;
  pointer-events: none;
}

.upload-zone:hover {
  border-color: var(--m-teal, #66BB6A);
  box-shadow: 4px 4px 0 var(--m-teal, #66BB6A);
  transform: translate(-2px, -2px);
}

.upload-zone.drag-active {
  border-color: var(--m-teal, #66BB6A);
  background: rgba(107, 203, 119, 0.04);
  box-shadow: 6px 6px 0 var(--m-teal, #66BB6A);
}

.upload-icon-box {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 3px solid var(--m-yellow, #FFE066);
  box-shadow: 4px 4px 0 var(--m-pink, #9B59B6);
  background: var(--m-surface, #FFFFFF);
}

.upload-icon-box .material-symbols-outlined { font-size: 28px; color: var(--m-yellow, #FFE066); }

.upload-main { font-size: 14px; color: var(--m-text, #2D2D2D); position: relative; z-index: 1; }
.upload-hint { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--m-text-dim, #6B6B6B); position: relative; z-index: 1; }

.hidden-input { display: none; }

/* ===== DIVIDER ===== */
.divider {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 2rem;
}

.divider-line { flex: 1; height: 2px; background: var(--m-border, #E0DDD5); }

.divider-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--m-text-dim, #6B6B6B);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

/* ===== TEXT INPUT ===== */
.text-input {
  width: 100%;
  height: 10rem;
  background: var(--m-surface, #FFFFFF);
  border: 2px solid var(--m-border, #E0DDD5);
  padding: 1rem;
  font-family: 'DM Sans', sans-serif;
  font-size: 14px;
  color: var(--m-text, #2D2D2D);
  resize: none;
  transition: border-color 0.2s;
}

.text-input::placeholder { color: var(--m-text-dim, #6B6B6B); opacity: 0.5; }

.text-input:focus {
  outline: none;
  border-color: var(--m-teal, #66BB6A);
  box-shadow: 3px 3px 0 var(--m-teal, #66BB6A);
}

/* ===== PARSE BUTTON — MEMPHIS OFFSET ===== */
.parse-btn {
  margin-top: 1rem;
  padding: 0.75rem 1.5rem;
  background: var(--m-yellow, #FFE066);
  color: var(--m-bg, #F5F0E8);
  border: 2px solid var(--m-bg, #F5F0E8);
  font-family: 'Space Mono', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  cursor: pointer;
  box-shadow: 4px 4px 0 var(--m-pink, #9B59B6);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.parse-btn:hover {
  transform: translate(-2px, -2px);
  box-shadow: 6px 6px 0 var(--m-pink, #9B59B6);
}

.parse-btn:active {
  transform: translate(2px, 2px);
  box-shadow: 0 0 0 transparent;
}

.parse-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
  box-shadow: 2px 2px 0 var(--m-border, #E0DDD5);
}

.parse-loading { display: flex; align-items: center; gap: 8px; }

.mini-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--m-bg, #F5F0E8);
  border-top-color: transparent;
  animation: spinSquare 1s linear infinite;
}

@keyframes spinSquare { to { transform: rotate(360deg); } }

/* ===== FOOTER NAV ===== */
.footer-nav {
  margin-top: 3rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.nav-back {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--m-text-dim, #6B6B6B);
  text-decoration: none;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  transition: color 0.15s;
}

.nav-back .material-symbols-outlined { font-size: 14px; }
.nav-back:hover { color: var(--m-text, #2D2D2D); }

.nav-right { display: flex; align-items: center; gap: 1rem; }

.autosave-status {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--m-text-dim, #6B6B6B);
}

.status-ok { color: var(--m-teal, #66BB6A); }

.next-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0.5rem 1rem;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border: 2px solid;
  text-decoration: none;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.next-btn .material-symbols-outlined { font-size: 14px; }

.next-btn.ready {
  border-color: var(--m-teal, #66BB6A);
  color: var(--m-teal, #66BB6A);
  box-shadow: 3px 3px 0 rgba(107, 203, 119, 0.3);
}

.next-btn.ready:hover {
  background: rgba(107, 203, 119, 0.08);
  transform: translate(-1px, -1px);
  box-shadow: 4px 4px 0 var(--m-teal, #66BB6A);
}

.next-btn.disabled {
  border-color: var(--m-border, #E0DDD5);
  color: var(--m-text-dim, #6B6B6B);
  pointer-events: none;
}

/* ===== PREVIEW PANEL ===== */
.preview-panel {
  width: 380px;
  flex-shrink: 0;
  border-left: 3px solid var(--m-pink, #9B59B6);
  background: var(--m-surface, #FFFFFF);
  overflow-y: auto;
  padding: 1.5rem;
  position: relative;
}

.preview-dots-overlay {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle, var(--m-purple, #D5C4F7) 1px, transparent 1px);
  background-size: 24px 24px;
  opacity: 0.04;
  pointer-events: none;
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
  position: relative;
  z-index: 1;
}

.preview-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--m-teal, #66BB6A);
  text-transform: uppercase;
  padding: 3px 10px;
  border: 2px solid var(--m-teal, #66BB6A);
  box-shadow: 2px 2px 0 var(--m-teal, #66BB6A);
}

.preview-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--m-text-dim, #6B6B6B);
}

/* Preview blocks */
.preview-block {
  margin-bottom: 1.5rem;
  position: relative;
  z-index: 1;
}

.preview-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--m-pink, #9B59B6);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  display: block;
  margin-bottom: 6px;
}

.preview-value-big {
  font-family: 'Space Mono', sans-serif;
  font-size: 20px;
  font-weight: 700;
  color: var(--m-text, #2D2D2D);
}

.preview-value-highlight {
  font-family: 'Space Mono', sans-serif;
  font-size: 16px;
  font-weight: 700;
  color: var(--m-teal, #66BB6A);
}

.preview-value {
  font-family: 'DM Sans', sans-serif;
  font-size: 14px;
  color: var(--m-text, #2D2D2D);
}

.preview-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

/* Tags */
.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.memphis-tag {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--m-teal, #66BB6A);
  padding: 3px 8px;
  border: 2px solid var(--m-teal, #66BB6A);
  text-transform: uppercase;
  transition: all 0.15s;
}

.memphis-tag:hover {
  box-shadow: 2px 2px 0 var(--m-teal, #66BB6A);
}

/* KPI list */
.kpi-list { margin-top: 6px; }

.kpi-item {
  padding: 6px 0;
  font-size: 12px;
  color: var(--m-text, #2D2D2D);
  border-bottom: 1px solid var(--m-border, #E0DDD5);
}

/* Risk list */
.risk-list { margin-top: 6px; }

.risk-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
  color: var(--m-text-dim, #6B6B6B);
}

.risk-icon {
  color: var(--m-coral, #FF8A80);
  font-size: 14px !important;
  flex-shrink: 0;
}
</style>
