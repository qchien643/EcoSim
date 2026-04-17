<template>
  <div class="dashboard-memphis">
    <!-- Floating geometric decorations -->
    <div class="memphis-deco">
      <div class="deco-circle"></div>
      <div class="deco-triangle"></div>
      <div class="deco-squiggle"></div>
      <div class="deco-dots"></div>
    </div>

    <!-- TOP bar -->
    <header class="top-bar">
      <div class="top-bar-left">
        <span class="top-label">ECOSIM_TERMINAL</span>
        <span class="top-sep">/</span>
        <span class="top-active">DASHBOARD</span>
      </div>
      <div class="top-bar-right">
        SYST_TIME <span class="time-value">{{ currentTime }}</span>
      </div>
    </header>

    <!-- Main content -->
    <div class="dashboard-content">
      <!-- Loading state -->
      <div v-if="loading" class="loading-state">
        <div class="memphis-spinner"></div>
        <span>Loading data from services...</span>
      </div>

      <!-- Error state -->
      <div v-if="error" class="error-bar">
        <span class="material-symbols-outlined">error</span>
        <span class="error-text">{{ error }}</span>
        <button @click="loadData" class="retry-btn">RETRY</button>
      </div>

      <!-- Service Health Bar -->
      <section class="health-bar">
        <span class="section-label">Service Status</span>
        <div class="health-indicators">
          <div v-for="(svc, name) in serviceHealth" :key="name" class="health-item">
            <div :class="['health-dot', svc.status === 'up' ? 'up' : 'down']"></div>
            <span :class="['health-name', svc.status === 'up' ? 'up' : 'down']">{{ name }}</span>
          </div>
        </div>
        <span v-if="gatewayStatus" class="gateway-status">
          GW: <span :class="gatewayStatus === 'ok' ? 'up' : 'down'">{{ gatewayStatus.toUpperCase() }}</span>
        </span>
      </section>

      <!-- Metric Grid -->
      <section class="metric-grid">
        <div class="metric-card" v-for="m in metrics" :key="m.label">
          <div class="metric-top">
            <span class="metric-label">{{ m.label }}</span>
            <div class="metric-icon-box" :style="{ background: m.color }">
              <span class="material-symbols-outlined">{{ m.icon }}</span>
            </div>
          </div>
          <div class="metric-value">{{ m.value }}</div>
          <span class="metric-sub" :style="{ color: m.subColor || '' }">{{ m.sub }}</span>
        </div>
      </section>

      <!-- Active Graph Selector -->
      <section v-if="graphs.length" class="section-card">
        <div class="section-header">
          <span class="section-label">Available Knowledge Graphs</span>
          <router-link to="/graph" class="section-link">VIEW GRAPH →</router-link>
        </div>
        <div class="graph-grid">
          <div v-for="g in graphs" :key="g.name"
               @click="selectGraph(g.name)"
               :class="['graph-item', store.groupId === g.name ? 'active' : '']">
            <div class="graph-name">{{ g.name }}</div>
            <div class="graph-stats">
              <span>{{ g.nodes }} nodes</span>
              <span>{{ g.edges }} edges</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Campaigns Table -->
      <section class="section-card">
        <div class="section-header">
          <span class="section-label">Recent Campaigns</span>
          <router-link to="/campaign" class="section-link">+ New Campaign</router-link>
        </div>
        <div v-if="campaigns.length === 0" class="empty-state">
          <span class="material-symbols-outlined">inbox</span>
          <p>No campaigns yet. <router-link to="/campaign">Upload one</router-link> to start.</p>
        </div>
        <table v-else class="memphis-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Name</th>
              <th>Type</th>
              <th>Market</th>
              <th class="text-right">Created</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in campaigns" :key="c.campaign_id"
                @click="selectCampaign(c.campaign_id)"
                class="clickable-row">
              <td class="td-id">{{ c.campaign_id }}</td>
              <td class="td-primary">{{ c.name }}</td>
              <td>{{ c.campaign_type }}</td>
              <td>{{ c.market }}</td>
              <td class="text-right">{{ formatDate(c.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Simulations Table -->
      <section class="section-card">
        <div class="section-header">
          <span class="section-label">Simulations</span>
        </div>
        <div v-if="simulations.length === 0" class="empty-state">
          <p>No simulations yet.</p>
        </div>
        <table v-else class="memphis-table">
          <thead>
            <tr>
              <th>SIM_ID</th>
              <th>Campaign</th>
              <th>Group</th>
              <th>Status</th>
              <th class="text-right">Agents</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in simulations" :key="s.sim_id"
                @click="selectSim(s.sim_id)"
                class="clickable-row">
              <td class="td-id">{{ s.sim_id }}</td>
              <td>{{ s.campaign_id }}</td>
              <td class="td-primary">{{ s.group_id || '—' }}</td>
              <td>
                <span :class="['status-badge', statusClass(s.status)]">{{ s.status }}</span>
              </td>
              <td class="text-right">{{ s.num_agents }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { campaignApi, simApi, graphApi, healthApi } from '../api/client'
import { useAppStore } from '../stores/appStore'

const router = useRouter()
const store = useAppStore()

const loading = ref(false)
const error = ref('')
const campaigns = ref([])
const simulations = ref([])
const graphs = ref([])
const stats = ref({
  campaignCount: 0,
  simCount: 0,
  graphNodes: 0,
  graphEdges: 0,
  graphCount: 0,
})
const currentTime = ref('')
const serviceHealth = ref({})
const gatewayStatus = ref('')

const metrics = computed(() => [
  { label: 'CAMPAIGNS', icon: 'ads_click', value: stats.value.campaignCount, sub: 'PARSED', color: '#9B59B6', subColor: '#66BB6A' },
  { label: 'SIMULATIONS', icon: 'biotech', value: stats.value.simCount, sub: 'TOTAL RUNS', color: '#B5E8F0' },
  { label: 'KG NODES', icon: 'hub', value: stats.value.graphNodes, sub: `${stats.value.graphEdges} EDGES`, color: '#FFE066' },
  { label: 'GRAPHS', icon: 'database', value: stats.value.graphCount, sub: 'FALKORDB', color: '#D5C4F7' },
])

function updateTime() {
  const now = new Date()
  currentTime.value = now.toLocaleTimeString('en-US', { hour12: false })
}

function formatDate(dateStr) {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function statusClass(status) {
  const map = { completed: 'success', running: 'warning', ready: 'success', failed: 'error', preparing: 'warning', created: 'neutral' }
  return map[status] || 'neutral'
}

function selectCampaign(id) {
  store.setCampaignId(id)
  router.push('/campaign')
}

function selectSim(id) {
  store.setSimId(id)
  router.push('/simulation')
}

function selectGraph(name) {
  store.setGroupId(name)
  router.push('/graph')
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    try {
      const healthRes = await healthApi.check()
      gatewayStatus.value = healthRes.data.status || 'ok'
      serviceHealth.value = healthRes.data.services || {}
    } catch {
      gatewayStatus.value = 'down'
    }

    const [campRes, simRes] = await Promise.all([
      campaignApi.list().catch(() => ({ data: { campaigns: [], count: 0 } })),
      simApi.list().catch(() => ({ data: { simulations: [], count: 0 } })),
    ])

    campaigns.value = campRes.data.campaigns || []
    simulations.value = simRes.data.simulations || []

    let graphList = []
    let totalNodes = 0
    let totalEdges = 0
    try {
      const gRes = await graphApi.listGraphs()
      graphList = gRes.data.graphs || []
      totalNodes = graphList.reduce((sum, g) => sum + (g.nodes || 0), 0)
      totalEdges = graphList.reduce((sum, g) => sum + (g.edges || 0), 0)
    } catch { /* graph service not ready */ }

    graphs.value = graphList

    stats.value = {
      campaignCount: campRes.data.count || campaigns.value.length,
      simCount: simRes.data.count || simulations.value.length,
      graphNodes: totalNodes,
      graphEdges: totalEdges,
      graphCount: graphList.length,
    }
  } catch (e) {
    error.value = e.response?.data?.error || e.message || 'Failed to load data'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  updateTime()
  setInterval(updateTime, 1000)
  loadData()
})
</script>

<style scoped>
/* ===== PASTEL MEMPHIS DASHBOARD ===== */
.dashboard-memphis {
  flex: 1;
  overflow-y: auto;
  position: relative;
  font-family: 'DM Sans', system-ui, sans-serif;
  color: #2D2D2D;
  background: #F5F0E8;
}

/* ===== FLOATING GEOMETRIC SHAPES (PASTEL) ===== */
.memphis-deco {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
}

.deco-circle {
  position: absolute;
  top: 8%;
  right: 5%;
  width: 200px;
  height: 200px;
  background: #FFB7B2;
  border-radius: 50%;
  opacity: 0.25;
  animation: floatGeo 8s ease-in-out infinite;
}

.deco-triangle {
  position: absolute;
  bottom: 10%;
  left: 3%;
  width: 0;
  height: 0;
  border-left: 70px solid transparent;
  border-right: 70px solid transparent;
  border-bottom: 120px solid #A8E6CF;
  opacity: 0.25;
  animation: floatGeo 10s ease-in-out infinite reverse;
}

.deco-squiggle {
  position: absolute;
  top: 45%;
  right: 20%;
  width: 120px;
  height: 120px;
  background: #FFE066;
  border-radius: 0;
  transform: rotate(15deg);
  opacity: 0.12;
  animation: floatGeo 9s ease-in-out infinite 2s;
}

.deco-dots {
  position: absolute;
  top: 25%;
  left: 25%;
  width: 100px;
  height: 100px;
  background-image: radial-gradient(circle, #D5C4F7 3px, transparent 3px);
  background-size: 14px 14px;
  opacity: 0.2;
  animation: floatGeo 7s ease-in-out infinite 1s;
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
  background: #FFFFFF;
  border-bottom: 1.5px solid #2D2D2D;
  position: relative;
  z-index: 2;
}

.top-bar::after { display: none; }

.top-bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.top-label {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: #9B9B9B;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}

.top-sep { color: #E0DDD5; }

.top-active {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: #9B59B6;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  font-weight: 700;
}

.top-bar-right {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: #9B9B9B;
}

.time-value {
  color: #2D2D2D;
  font-weight: 700;
  background: #FFE066;
  padding: 1px 6px;
}

/* ===== CONTENT ===== */
.dashboard-content {
  padding: 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  position: relative;
  z-index: 1;
  max-width: 1400px;
}

/* ===== LOADING ===== */
.loading-state {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 1.5rem;
  background: #FFFFFF;
  border: 1.5px solid #E0DDD5;
  border-radius: 4px;
}

.memphis-spinner {
  width: 24px;
  height: 24px;
  border: 3px solid #E0DDD5;
  border-top-color: #FFB7B2;
  border-right-color: #FFE066;
  border-radius: 50%;
  animation: spinSquare 1s linear infinite;
}

@keyframes spinSquare {
  to { transform: rotate(360deg); }
}

.loading-state span {
  font-family: 'Space Mono', monospace;
  font-size: 13px;
  color: #6B6B6B;
}

/* ===== ERROR ===== */
.error-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 1rem 1.5rem;
  background: #FFF0EF;
  border-left: 4px solid #FF8A80;
  border: 1.5px solid #FF8A80;
  border-radius: 4px;
}

.error-bar .material-symbols-outlined { color: #FF8A80; font-size: 20px; }

.error-text {
  flex: 1;
  font-family: 'Space Mono', monospace;
  font-size: 12px;
  color: #C62828;
}

.retry-btn {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: #6B6B6B;
  background: #FFFFFF;
  border: 1.5px solid #E0DDD5;
  border-radius: 4px;
  padding: 4px 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.retry-btn:hover {
  border-color: #2D2D2D;
  color: #2D2D2D;
  box-shadow: 2px 2px 0 rgba(45, 45, 45, 0.1);
}

/* ===== SERVICE HEALTH BAR ===== */
.health-bar {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 1rem 1.5rem;
  background: #FFFFFF;
  border: 1.5px solid #E0DDD5;
  border-radius: 4px;
  box-shadow: 2px 2px 0 rgba(45, 45, 45, 0.06);
  position: relative;
}

.health-bar::before { display: none; }

.health-indicators {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.health-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.health-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.health-dot.up { background: #66BB6A; }
.health-dot.down { background: #FF8A80; }

.health-name {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.health-name.up { color: #2E7D32; }
.health-name.down { color: #C62828; }

.gateway-status {
  margin-left: auto;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: #9B9B9B;
}

.gateway-status .up { color: #2E7D32; }
.gateway-status .down { color: #C62828; }

/* ===== METRIC CARDS ===== */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
}

.metric-card {
  background: #FFFFFF;
  border: 1.5px solid #2D2D2D;
  border-radius: 6px;
  padding: 1.5rem;
  box-shadow: 3px 3px 0 rgba(45, 45, 45, 0.1);
  transition: all 0.25s ease;
  position: relative;
}

.metric-card:hover {
  transform: translate(-2px, -2px);
  box-shadow: 5px 5px 0 rgba(45, 45, 45, 0.15);
}

.metric-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.metric-label {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: #6B6B6B;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.metric-icon-box {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1.5px solid #2D2D2D;
  border-radius: 4px;
}

.metric-icon-box .material-symbols-outlined {
  font-size: 16px;
  color: #2D2D2D;
}

.metric-value {
  font-family: 'Space Mono', monospace;
  font-size: 2.5rem;
  font-weight: 700;
  line-height: 1;
  color: #2D2D2D;
  letter-spacing: -0.02em;
  margin-bottom: 0.25rem;
}

.metric-sub {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: #9B9B9B;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* ===== SECTION CARD ===== */
.section-card {
  background: #FFFFFF;
  border: 1.5px solid #E0DDD5;
  border-radius: 6px;
  box-shadow: 2px 2px 0 rgba(45, 45, 45, 0.06);
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.5rem;
  border-bottom: 1.5px solid #FFE066;
  background: #FFFDE7;
  position: relative;
}

.section-header::after { display: none; }

.section-label {
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  color: #2D2D2D;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.section-link {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: #9B59B6;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  text-decoration: none;
  transition: all 0.15s;
}

.section-link:hover {
  color: #2D2D2D;
}

/* ===== GRAPH GRID ===== */
.graph-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0;
  padding: 1rem 1.5rem;
}

.graph-item {
  padding: 1rem;
  border: 1.5px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.graph-item:hover {
  border-color: #D5C4F7;
  background: #FAF6FF;
}

.graph-item.active {
  border: 1.5px solid #66BB6A;
  background: #F0FFF4;
  box-shadow: 2px 2px 0 rgba(102, 187, 106, 0.2);
}

.graph-name {
  font-family: 'Space Mono', monospace;
  font-size: 14px;
  font-weight: 700;
  color: #2D2D2D;
  margin-bottom: 4px;
}

.graph-stats {
  display: flex;
  gap: 12px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: #9B9B9B;
}

/* ===== MEMPHIS TABLE ===== */
.memphis-table {
  width: 100%;
  border-collapse: collapse;
}

.memphis-table thead tr {
  border-bottom: 1.5px solid #2D2D2D;
  background: #FFE066;
}

.memphis-table th {
  padding: 0.75rem 1.5rem;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  color: #2D2D2D;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  text-align: left;
}

.memphis-table td {
  padding: 0.75rem 1.5rem;
  font-family: 'DM Sans', sans-serif;
  font-size: 13px;
  color: #6B6B6B;
  border-bottom: 1px solid #F0EDE5;
}

.clickable-row {
  cursor: pointer;
  transition: all 0.15s;
}

.clickable-row:hover {
  background: #FBF8F3;
}

.clickable-row:hover .td-id {
  color: #2D2D2D;
}

.td-id {
  color: #9B59B6;
  font-weight: 600;
  font-family: 'Space Mono', monospace;
}

.td-primary {
  color: #2D2D2D;
  font-weight: 500;
}

.text-right { text-align: right; }

/* ===== STATUS BADGE ===== */
.status-badge {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  padding: 2px 8px;
  border: 1.5px solid;
  border-radius: 2px;
  letter-spacing: 0.04em;
}

.status-badge.success {
  color: #2E7D32;
  border-color: #A8E6CF;
  background: #E8F5E9;
}

.status-badge.warning {
  color: #8D6E00;
  border-color: #FFE066;
  background: #FFFDE7;
}

.status-badge.error {
  color: #C62828;
  border-color: #FFB7B2;
  background: #FFF0EF;
}

.status-badge.neutral {
  color: #9B9B9B;
  border-color: #E0DDD5;
  background: #FBF8F3;
}

/* ===== EMPTY STATE ===== */
.empty-state {
  padding: 3rem;
  text-align: center;
  color: #9B9B9B;
}

.empty-state .material-symbols-outlined {
  font-size: 40px;
  color: #E0DDD5;
  display: block;
  margin-bottom: 0.75rem;
}

.empty-state p {
  font-size: 13px;
  color: #6B6B6B;
}

.empty-state a {
  color: #9B59B6;
  text-decoration: none;
  font-weight: 600;
}

.empty-state a:hover {
  color: #2D2D2D;
}
</style>