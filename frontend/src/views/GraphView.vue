<template>
  <div class="flex-1 flex flex-col overflow-hidden">
    <!-- Header Section -->
    <header class="h-20 px-8 flex items-center justify-between border-b border-[#E0DDD5]/30 bg-[#F5F0E8]/50 flex-shrink-0">
      <div class="flex flex-col">
        <div class="flex items-center gap-3">
          <span class="material-symbols-outlined text-[#66BB6A]" style="font-size: 24px;">hub</span>
          <h1 class="text-2xl font-bold tracking-tight text-[#2D2D2D]">Knowledge Graph</h1>
          <span class="ml-4 px-2 py-0.5 bg-[#FBF8F3] text-[#6B6B6B] font-mono text-[10px] uppercase border border-[#E0DDD5]/50">Step 2 of 6</span>
        </div>
        <div class="mt-1 flex items-center gap-4">
          <span class="font-mono text-xs text-[#6B6B6B] uppercase">Graph:</span>
          <span class="font-mono text-xs text-[#66BB6A]">{{ activeGroupId || 'none' }}</span>
          <span class="text-[#E0DDD5]">|</span>
          <span class="font-mono text-xs text-[#6B6B6B]">{{ graphStats.nodes || 0 }} nodes, {{ graphStats.edges || 0 }} edges</span>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <!-- Graph Selector -->
        <select v-model="activeGroupId" @change="switchGraph"
                class="bg-[#FFFFFF] border border-[#E0DDD5] text-[#2D2D2D] font-mono text-xs px-3 py-2 focus:ring-1 focus:ring-[#66BB6A] focus:border-[#66BB6A]">
          <option value="">Select Graph...</option>
          <option v-for="g in availableGraphs" :key="g.name" :value="g.name">
            {{ g.name }} ({{ g.nodes }}N / {{ g.edges }}E)
          </option>
        </select>
        <button
          v-if="graphStats.nodes > 0"
          @click="clearGraph"
          :disabled="building"
          class="border border-[#FF8A80]/40 text-[#FF8A80] hover:bg-[#FF8A80]/10 px-4 py-2 font-mono text-xs uppercase tracking-wider transition-colors disabled:opacity-50"
        >Clear</button>
        <button
          @click="buildGraph"
          :disabled="building || !store.campaignId"
          class="bg-[#66BB6A] hover:bg-[#66BB6A]/90 text-[#F5F0E8] px-6 py-2.5 font-bold text-sm tracking-tight transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <div v-if="building" class="w-4 h-4 border-2 border-[#F5F0E8] border-t-transparent rounded-full animate-spin"></div>
          <span v-else class="material-symbols-outlined" style="font-variation-settings: 'wght' 700;">account_tree</span>
          {{ building ? 'BUILDING...' : 'BUILD GRAPH' }}
        </button>
      </div>
    </header>

    <!-- Error / Info bar -->
    <div v-if="error" class="mx-8 mt-4 bg-[#FBF8F3] border-l-2 border-[#FF8A80] px-6 py-3 flex items-center gap-3">
      <span class="material-symbols-outlined text-[#FF8A80] text-sm">error</span>
      <span class="text-xs font-mono text-[#FF8A80]">{{ error }}</span>
    </div>
    <div v-if="!store.campaignId && !graphHasData && availableGraphs.length === 0" class="mx-8 mt-4 bg-[#FBF8F3] border-l-2 border-[#FFE066] px-6 py-3 flex items-center gap-3">
      <span class="material-symbols-outlined text-[#FFE066] text-sm">info</span>
      <span class="text-xs font-mono text-[#FFE066]">Upload a campaign first to build the Knowledge Graph.</span>
      <router-link to="/campaign" class="ml-auto text-[10px] font-mono text-[#66BB6A] border border-[#66BB6A]/30 px-3 py-1 hover:bg-[#66BB6A]/10">GO TO CAMPAIGN</router-link>
    </div>

    <!-- Search Bar -->
    <div class="px-8 py-3 bg-[#FFFFFF] border-b border-[#E0DDD5]/30 flex items-center gap-4 flex-shrink-0">
      <span class="material-symbols-outlined text-[#6B6B6B]">search</span>
      <input
        v-model="searchQuery"
        @keyup.enter="searchGraph"
        type="text"
        placeholder="Search entities and relationships..."
        class="flex-1 bg-transparent text-sm text-[#2D2D2D] placeholder-[#6B6B6B]/40 focus:outline-none font-sans"
      />
      <button v-if="searchQuery.trim()" @click="searchQuery = ''; searchResults = []; clearHighlights()"
              class="text-[#6B6B6B] hover:text-[#2D2D2D] transition-colors">
        <span class="material-symbols-outlined text-sm">close</span>
      </button>
      <button @click="searchGraph" :disabled="!searchQuery.trim() || searching"
              class="px-4 py-1.5 bg-[#66BB6A]/10 text-[#66BB6A] font-mono text-xs uppercase border border-[#66BB6A]/30 hover:bg-[#66BB6A]/20 transition-colors disabled:opacity-50">
        {{ searching ? 'SEARCHING...' : 'SEARCH' }}
      </button>
    </div>

    <!-- Search Results -->
    <div v-if="searchResults.length" class="mx-8 mt-4 bg-[#FFFFFF] border border-[#E0DDD5]/40 max-h-[240px] overflow-y-auto">
      <div class="p-4 border-b border-[#E0DDD5]/30 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <span class="font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest">Results ({{ searchResults.length }})</span>
          <span v-if="searchMode" class="px-2 py-0.5 bg-[#66BB6A]/10 text-[#66BB6A] font-mono text-[9px] uppercase border border-[#66BB6A]/20">{{ searchMode }}</span>
        </div>
        <button @click="searchResults = []; clearHighlights()" class="text-[#6B6B6B] hover:text-[#2D2D2D]">
          <span class="material-symbols-outlined text-sm">close</span>
        </button>
      </div>
      <div v-for="(r, i) in searchResults" :key="i"
           class="px-4 py-3 border-b border-[#E0DDD5]/20 hover:bg-[#FBF8F3] transition-colors cursor-pointer"
           @click="highlightNode(r)">
        <div class="flex items-center gap-2 mb-1">
          <!-- Type badge -->
          <span v-if="r.type === 'entity'"
                class="px-1.5 py-0.5 bg-[#66BB6A]/15 text-[#66BB6A] font-mono text-[9px] uppercase border border-[#66BB6A]/20">Entity</span>
          <span v-else
                class="px-1.5 py-0.5 bg-[#D5C4F7]/15 text-[#D5C4F7] font-mono text-[9px] uppercase border border-[#D5C4F7]/20">Edge</span>
          <span v-if="r.name" class="text-sm font-bold text-[#2D2D2D]">{{ r.name }}</span>
        </div>
        <p v-if="r.fact" class="text-xs text-[#2D2D2D]/80 mt-1 line-clamp-2">{{ r.fact }}</p>
        <p v-if="r.source_description" class="text-[10px] font-mono text-[#6B6B6B] mt-1">{{ r.source_description }}</p>
      </div>
    </div>
    <!-- No results -->
    <div v-if="searchNoResults" class="mx-8 mt-4 bg-[#FBF8F3] border-l-2 border-[#FFE066] px-6 py-3 flex items-center gap-3">
      <span class="material-symbols-outlined text-[#FFE066] text-sm">search_off</span>
      <span class="text-xs font-mono text-[#FFE066]">No results found for "{{ lastSearchQuery }}"</span>
    </div>

    <!-- Dynamic Layout -->
    <section class="flex-1 flex overflow-hidden">
      <!-- Left Panel -->
      <aside class="w-[280px] border-r border-[#E0DDD5]/30 bg-[#FFFFFF]/30 p-6 overflow-y-auto flex-shrink-0">
        <h3 class="font-mono text-xs font-bold text-[#6B6B6B] uppercase tracking-[0.2em] mb-6">Entities</h3>
        <div v-if="entities.length === 0" class="text-xs text-[#6B6B6B] font-mono">No entities yet.</div>
        <div v-else class="space-y-2 max-h-[300px] overflow-y-auto">
          <div v-for="(e, i) in entities.slice(0, 50)" :key="e.name || i"
               class="group flex items-center gap-3 hover:bg-[#FBF8F3] px-3 py-2 -mx-3 transition-colors cursor-pointer"
               @click="selected = { name: e.name, summary: e.summary }">
            <div class="w-3 h-3 rounded-full flex-shrink-0" :style="{ background: TYPE_COLORS[i % TYPE_COLORS.length] }"></div>
            <span class="text-xs text-[#2D2D2D] truncate">{{ e.name }}</span>
          </div>
          <div v-if="entities.length > 50" class="text-[10px] font-mono text-[#6B6B6B] px-3">
            + {{ entities.length - 50 }} more entities
          </div>
        </div>

        <!-- Graph Stats -->
        <div class="mt-8 p-5 bg-[#FBF8F3] border border-[#E0DDD5]/20">
          <h4 class="font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest mb-4">Graph Stats</h4>
          <div class="space-y-3">
            <div class="flex justify-between">
              <span class="text-xs text-[#6B6B6B]">Graph</span>
              <span class="font-mono text-sm text-[#66BB6A]">{{ activeGroupId || '—' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-xs text-[#6B6B6B]">Nodes</span>
              <span class="font-mono text-sm text-[#66BB6A]">{{ graphStats.nodes || 0 }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-xs text-[#6B6B6B]">Edges</span>
              <span class="font-mono text-sm text-[#2D2D2D]">{{ graphStats.edges || 0 }}</span>
            </div>
            <div class="flex justify-between" v-if="graphStats.node_labels">
              <span class="text-xs text-[#6B6B6B]">Labels</span>
              <span class="font-mono text-sm text-[#2D2D2D]">{{ Object.keys(graphStats.node_labels).length }}</span>
            </div>
          </div>
        </div>

        <!-- Legend -->
        <div class="mt-6 text-[10px] font-mono text-[#6B6B6B] space-y-2">
          <p>🖱 Drag nodes to reposition</p>
          <p>⚙ Scroll to zoom in/out</p>
          <p>🔍 Click node for details</p>
        </div>
      </aside>

      <!-- Main Graph Area (D3) -->
      <div class="flex-1 bg-[#F5F0E8] relative overflow-hidden">
        <!-- Loading -->
        <div v-if="loadingGraph" class="absolute inset-0 flex flex-col items-center justify-center gap-3 text-[#6B6B6B] z-10">
          <div class="w-8 h-8 border-2 border-[#66BB6A] border-t-transparent rounded-full animate-spin"></div>
          <span class="font-mono text-xs">Loading graph...</span>
        </div>
        <!-- Empty state -->
        <div v-else-if="!graphHasData" class="absolute inset-0 flex flex-col items-center justify-center gap-4 text-[#6B6B6B]">
          <span class="material-symbols-outlined text-6xl text-[#E0DDD5]">hub</span>
          <p class="font-mono text-sm text-[#6B6B6B]">No graph data</p>
          <p class="font-mono text-xs text-[#6B6B6B]/60">Select a graph or build one from campaign</p>
        </div>
        <!-- D3 SVG Container -->
        <svg ref="svgRef" class="w-full h-full" v-show="graphHasData && !loadingGraph"></svg>

        <!-- Floating Selection Panel -->
        <div v-if="selected" class="absolute right-6 top-6 w-80 bg-[#FFFFFF]/95 backdrop-blur-md border border-[#E0DDD5]/50 p-6 shadow-2xl z-20">
          <div class="flex justify-between items-start mb-4">
            <div>
              <span class="font-mono text-[10px] text-[#66BB6A] uppercase tracking-widest mb-1 block">Selected Entity</span>
              <h2 class="text-lg font-bold tracking-tight text-[#2D2D2D]">{{ selected.name }}</h2>
            </div>
          </div>
          <div class="space-y-2" v-if="selected.summary">
            <span class="font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest">Summary</span>
            <p class="text-xs text-[#2D2D2D]">{{ selected.summary }}</p>
          </div>
          <button @click="selected = null" class="w-full mt-5 py-2 bg-[#FBF8F3] border border-[#E0DDD5]/30 font-mono text-xs uppercase text-[#6B6B6B] hover:text-white transition-colors">Close</button>
        </div>
      </div>
    </section>

    <!-- Bottom Nav -->
    <footer class="h-12 bg-[#FBF8F3] border-t border-[#E0DDD5]/30 px-8 flex items-center justify-between flex-shrink-0">
      <div class="flex items-center gap-6 font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest">
        <div class="flex items-center gap-2"><span>Nodes:</span><span class="text-[#2D2D2D]">{{ graphStats.nodes || 0 }}</span></div>
        <div class="flex items-center gap-2"><span>Edges:</span><span class="text-[#2D2D2D]">{{ graphStats.edges || 0 }}</span></div>
        <div class="flex items-center gap-2"><span>Graph:</span><span class="text-[#66BB6A]">{{ activeGroupId || 'none' }}</span></div>
      </div>
      <div class="flex items-center gap-12">
        <router-link to="/campaign" class="flex items-center gap-2 text-[#6B6B6B] hover:text-[#2D2D2D] transition-colors group">
          <span class="material-symbols-outlined text-sm group-hover:-translate-x-1 transition-transform">arrow_back</span>
          <span class="font-mono text-[10px] uppercase tracking-widest">Back: Campaign</span>
        </router-link>
        <router-link to="/simulation" class="flex items-center gap-2 text-[#66BB6A] hover:text-[#66BB6A]/80 transition-colors group">
          <span class="font-mono text-[10px] uppercase tracking-widest">Next: Simulation</span>
          <span class="material-symbols-outlined text-sm group-hover:translate-x-1 transition-transform">arrow_forward</span>
        </router-link>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import * as d3 from 'd3'
import { graphApi } from '../api/client'
import { useAppStore } from '../stores/appStore'

const store = useAppStore()

const svgRef = ref(null)
const loadingGraph = ref(false)
const building = ref(false)
const searching = ref(false)
const error = ref('')
const entities = ref([])
const graphEdges = ref([])
const graphStats = ref({})
const selected = ref(null)
const searchQuery = ref('')
const searchResults = ref([])
const searchMode = ref('')
const searchNoResults = ref(false)
const lastSearchQuery = ref('')
const availableGraphs = ref([])
const activeGroupId = ref(store.groupId || '')

let simulation = null
let resizeObserver = null

const TYPE_COLORS = ['#66BB6A','#66BB6A','#FFE066','#FF8A80','#D5C4F7','#FB923C','#6B6B6B','#64748B','#F472B6','#B5E8F0']

const graphHasData = computed(() => entities.value.length > 0)

function truncate(str, max) {
  return str && str.length > max ? str.slice(0, max) + '…' : str
}

// ── Search ──
async function searchGraph() {
  if (!searchQuery.value.trim()) return
  searching.value = true
  searchNoResults.value = false
  lastSearchQuery.value = searchQuery.value
  try {
    const res = await graphApi.search(searchQuery.value, activeGroupId.value, 10)
    searchResults.value = res.data.results || []
    searchMode.value = res.data.mode || 'cypher'
    searchNoResults.value = searchResults.value.length === 0
  } catch (e) {
    error.value = e.response?.data?.detail || 'Search failed'
    searchNoResults.value = true
  } finally {
    searching.value = false
  }
}

// ── Node Highlighting ──
function highlightNode(result) {
  if (!svgRef.value || !result.name) return
  clearHighlights()

  const svg = d3.select(svgRef.value)
  const matchName = result.name.toLowerCase()

  // Find matching node circles
  svg.selectAll('g > circle').each(function() {
    const parent = d3.select(this.parentNode)
    const nodeData = parent.datum()
    if (!nodeData) return

    const name = (nodeData.name || nodeData.id || '').toLowerCase()
    if (name.includes(matchName) || matchName.includes(name)) {
      // Pulse highlight
      d3.select(this)
        .classed('search-highlight', true)
        .transition().duration(300)
        .attr('stroke', '#FFD700')
        .attr('stroke-width', 4)
        .attr('stroke-opacity', 1)
        .attr('r', nodeData.r * 1.4)

      // Also select it in the detail panel
      selected.value = { name: nodeData.name, summary: nodeData.summary }
    }
  })
}

function clearHighlights() {
  if (!svgRef.value) return
  const svg = d3.select(svgRef.value)
  svg.selectAll('circle.search-highlight')
    .classed('search-highlight', false)
    .transition().duration(300)
    .attr('stroke-width', 2)
    .attr('stroke-opacity', 0.3)
    .each(function() {
      const d = d3.select(this.parentNode).datum()
      if (d) {
        d3.select(this)
          .attr('r', d.r)
          .attr('stroke', null)  // Reset to original
      }
    })
}

// ── Graph Switching ──
async function switchGraph() {
  store.setGroupId(activeGroupId.value)
  await loadGraphData()
}

async function loadAvailableGraphs() {
  try {
    const res = await graphApi.listGraphs()
    availableGraphs.value = (res.data.graphs || []).filter(g => g.nodes > 0)
  } catch { /* Simulation service not ready */ }
}

// ── D3 Force Graph ──
function renderD3Graph() {
  if (!svgRef.value || entities.value.length === 0) return

  if (simulation) simulation.stop()
  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()

  const rect = svgRef.value.getBoundingClientRect()
  const width = rect.width || 800
  const height = rect.height || 600

  // Build node map
  const nodeMap = new Map()
  entities.value.forEach((e, i) => {
    const id = e.name || `entity_${i}`
    nodeMap.set(id, {
      id,
      name: e.name || 'Unknown',
      summary: e.summary || '',
      r: Math.max(8, Math.min(24, 10 + (e.summary?.length || 0) / 20)),
    })
  })
  const nodes = Array.from(nodeMap.values())

  // Build links from edges
  const links = graphEdges.value
    .filter(e => nodeMap.has(e.source) && nodeMap.has(e.target))
    .map(e => ({
      source: e.source,
      target: e.target,
      relation: e.relation || '',
    }))

  // Increase node radius based on connection count
  const connectionCount = new Map()
  links.forEach(l => {
    const s = typeof l.source === 'string' ? l.source : l.source.id
    const t = typeof l.target === 'string' ? l.target : l.target.id
    connectionCount.set(s, (connectionCount.get(s) || 0) + 1)
    connectionCount.set(t, (connectionCount.get(t) || 0) + 1)
  })
  nodes.forEach(n => {
    n.r = Math.max(8, Math.min(30, n.r + (connectionCount.get(n.id) || 0) * 2))
  })

  // Zoom behavior
  const zoom = d3.zoom()
    .scaleExtent([0.2, 5])
    .on('zoom', (event) => {
      g.attr('transform', event.transform)
    })
  svg.call(zoom)

  const g = svg.append('g')

  // Arrow marker for directed edges
  const defs = svg.append('defs')
  defs.append('marker')
    .attr('id', 'arrowhead')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 20)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#E0DDD5')

  // Glow filter
  const filter = defs.append('filter').attr('id', 'glow')
  filter.append('feGaussianBlur').attr('stdDeviation', 3).attr('result', 'blur')
  filter.append('feMerge').selectAll('feMergeNode')
    .data(['blur', 'SourceGraphic'])
    .join('feMergeNode')
    .attr('in', d => d)

  // Links
  const link = g.append('g')
    .selectAll('line')
    .data(links)
    .join('line')
    .attr('stroke', '#E0DDD5')
    .attr('stroke-width', 1.5)
    .attr('stroke-opacity', 0.6)
    .attr('marker-end', 'url(#arrowhead)')

  // Link labels
  const linkLabel = g.append('g')
    .selectAll('text')
    .data(links)
    .join('text')
    .text(d => truncate(d.relation, 20))
    .attr('text-anchor', 'middle')
    .attr('font-size', 9)
    .attr('font-family', 'Geist, system-ui, sans-serif')
    .attr('fill', '#6B6B6B')
    .attr('fill-opacity', 0.6)
    .attr('pointer-events', 'none')

  // Node groups
  const node = g.append('g')
    .selectAll('g')
    .data(nodes)
    .join('g')
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', dragStarted)
      .on('drag', dragged)
      .on('end', dragEnded))
    .on('click', (event, d) => { selected.value = d })

  // Node circles
  node.append('circle')
    .attr('r', d => d.r)
    .attr('fill', (d, i) => TYPE_COLORS[i % TYPE_COLORS.length])
    .attr('fill-opacity', 0.85)
    .attr('stroke', (d, i) => TYPE_COLORS[i % TYPE_COLORS.length])
    .attr('stroke-width', 2)
    .attr('stroke-opacity', 0.3)
    .attr('filter', 'url(#glow)')
    .on('mouseenter', function(event, d) {
      d3.select(this)
        .transition().duration(200)
        .attr('r', d.r * 1.3)
        .attr('stroke-opacity', 0.8)
    })
    .on('mouseleave', function(event, d) {
      d3.select(this)
        .transition().duration(200)
        .attr('r', d.r)
        .attr('stroke-opacity', 0.3)
    })

  // Node labels
  node.append('text')
    .text(d => truncate(d.name, 16))
    .attr('dy', d => d.r + 14)
    .attr('text-anchor', 'middle')
    .attr('font-size', 11)
    .attr('font-family', 'Geist, system-ui, sans-serif')
    .attr('fill', '#6B6B6B')
    .attr('pointer-events', 'none')

  // Force simulation with links
  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(120))
    .force('charge', d3.forceManyBody().strength(-250))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(d => d.r + 15))
    .force('x', d3.forceX(width / 2).strength(0.04))
    .force('y', d3.forceY(height / 2).strength(0.04))
    .on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y)

      linkLabel
        .attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2 - 4)

      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })

  // Initial zoom to fit
  setTimeout(() => {
    const bounds = g.node()?.getBBox()
    if (bounds && bounds.width > 0) {
      const scale = Math.min(
        width / (bounds.width + 100),
        height / (bounds.height + 100),
        1.5
      )
      const tx = width / 2 - (bounds.x + bounds.width / 2) * scale
      const ty = height / 2 - (bounds.y + bounds.height / 2) * scale
      svg.transition().duration(750).call(
        zoom.transform,
        d3.zoomIdentity.translate(tx, ty).scale(scale)
      )
    }
  }, 1500)

  function dragStarted(event, d) {
    if (!event.active) simulation.alphaTarget(0.3).restart()
    d.fx = d.x; d.fy = d.y
  }
  function dragged(event, d) {
    d.fx = event.x; d.fy = event.y
  }
  function dragEnded(event, d) {
    if (!event.active) simulation.alphaTarget(0)
    d.fx = null; d.fy = null
  }
}

// ── Data Loading ──
async function loadGraphData() {
  if (!activeGroupId.value) return
  loadingGraph.value = true
  error.value = ''
  try {
    const [entRes, edgeRes, statsRes] = await Promise.all([
      graphApi.entities(activeGroupId.value, 200),
      graphApi.edges(activeGroupId.value, 500),
      graphApi.stats(activeGroupId.value),
    ])
    entities.value = entRes.data.entities || []
    graphEdges.value = edgeRes.data.edges || []
    graphStats.value = statsRes.data || {}

    await nextTick()
    renderD3Graph()
  } catch (e) {
    if (e.response?.status !== 404) {
      error.value = e.response?.data?.detail || e.message
    }
  } finally {
    loadingGraph.value = false
  }
}

async function buildGraph() {
  if (!store.campaignId) return
  building.value = true
  error.value = ''
  const groupId = activeGroupId.value || store.campaignId
  try {
    // Auto-clear existing graph before re-building to prevent stale data
    try {
      await graphApi.clear(groupId)
      console.log('[GraphView] Auto-cleared graph before rebuild:', groupId)
    } catch {
      // Graph may not exist yet, ignore 404
    }
    await graphApi.build({ campaign_id: store.campaignId, group_id: groupId })
    activeGroupId.value = groupId
    store.setGroupId(groupId)
    store.completeStep('graph')
    await loadAvailableGraphs()
    await loadGraphData()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Graph build failed'
  } finally {
    building.value = false
  }
}

async function clearGraph() {
  if (!confirm('Clear all graph data? This cannot be undone.')) return
  try {
    await graphApi.clear(activeGroupId.value)
    entities.value = []
    graphStats.value = {}
    selected.value = null
    if (simulation) simulation.stop()
    const svg = d3.select(svgRef.value)
    svg.selectAll('*').remove()
    await loadAvailableGraphs()
  } catch (e) {
    error.value = 'Failed to clear graph'
  }
}

onMounted(async () => {
  await loadAvailableGraphs()
  // Auto-load if store has groupId
  if (store.groupId) {
    activeGroupId.value = store.groupId
    await loadGraphData()
  } else if (availableGraphs.value.length > 0) {
    activeGroupId.value = availableGraphs.value[0].name
    store.setGroupId(activeGroupId.value)
    await loadGraphData()
  }

  // Handle resize
  resizeObserver = new ResizeObserver(() => {
    if (graphHasData.value) renderD3Graph()
  })
  if (svgRef.value?.parentElement) {
    resizeObserver.observe(svgRef.value.parentElement)
  }
})

onUnmounted(() => {
  if (simulation) simulation.stop()
  if (resizeObserver) resizeObserver.disconnect()
})
</script>

<style scoped>
/* ===== MEMPHIS GRAPH OVERRIDES ===== */

/* Root */
.flex-1.flex.flex-col.overflow-hidden {
  font-family: 'DM Sans', system-ui, sans-serif;
  position: relative;
}

/* Floating geometric shapes */
.flex-1.flex.flex-col.overflow-hidden::before {
  content: '';
  position: fixed;
  top: 25%;
  right: 15%;
  width: 120px;
  height: 120px;
  border: 4px solid #66BB6A;
  border-radius: 0 50% 50% 0;
  opacity: 0.04;
  pointer-events: none;
  animation: gFloat 9s ease-in-out infinite;
  z-index: 0;
}

@keyframes gFloat {
  0%, 100% { transform: translate(0, 0) rotate(0deg); }
  50% { transform: translate(-10px, 15px) rotate(-5deg); }
}

/* Header — zigzag bottom + Memphis font */
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

h1, h2, h3, h4 {
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700 !important;
}

/* Step badge — square Memphis */
span[class*="bg-[#FBF8F3]"][class*="font-mono"] {
  border: 2px solid #E0DDD5 !important;
  box-shadow: 2px 2px 0 rgba(45, 43, 85, 0.3);
}

/* Buttons — Memphis offset */
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

/* Clear button */
button[class*="border-[#FF8A80]"] {
  border: 2px solid #FF8A80 !important;
  box-shadow: 2px 2px 0 rgba(255, 107, 107, 0.2);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

button[class*="border-[#FF8A80]"]:hover {
  box-shadow: 3px 3px 0 #FF8A80;
  transform: translate(-1px, -1px);
}

/* Select dropdown — square Memphis */
select {
  border: 2px solid #E0DDD5 !important;
  border-radius: 0 !important;
  font-family: 'JetBrains Mono', monospace !important;
}

select:focus {
  border-color: #66BB6A !important;
  box-shadow: 3px 3px 0 #66BB6A !important;
}

/* Search bar — thick bottom border */
.px-8.py-3 {
  border-bottom: 2px solid #E0DDD5 !important;
}

input[type="text"] {
  font-family: 'DM Sans', sans-serif !important;
}

/* Search button */
button[class*="bg-[#66BB6A]/10"] {
  border: 2px solid rgba(107, 203, 119, 0.4) !important;
  box-shadow: 2px 2px 0 rgba(107, 203, 119, 0.2);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Left sidebar — polka dots + pink border */
aside[class*="w-[280px]"] {
  border-right: 3px solid #9B59B6 !important;
  position: relative;
}

aside[class*="w-[280px]"]::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle, #D5C4F7 1px, transparent 1px);
  background-size: 20px 20px;
  opacity: 0.04;
  pointer-events: none;
}

/* Entity dots — square Memphis */
div[class*="w-3"][class*="h-3"][class*="rounded-full"] {
  border-radius: 0 !important;
  box-shadow: 1px 1px 0 rgba(0,0,0,0.3);
}

/* Entity items — hover effect */
.group:hover {
  background: rgba(132, 94, 194, 0.08) !important;
}

/* Stats panel — Memphis card */
div[class*="bg-[#FBF8F3]"][class*="border"] {
  border: 2px solid #E0DDD5 !important;
  box-shadow: 3px 3px 0 rgba(45, 43, 85, 0.3);
}

/* Selection panel — Memphis card */
div[class*="backdrop-blur"] {
  border: 2px solid #D5C4F7 !important;
  box-shadow: 5px 5px 0 #9B59B6 !important;
  backdrop-filter: blur(12px);
}

/* Spinner — square Memphis */
div[class*="rounded-full"][class*="animate-spin"] {
  border-radius: 0 !important;
}

/* Footer — Memphis style */
footer {
  border-top: 3px solid #D5C4F7 !important;
}

/* Search results cards */
div[class*="border-[#E0DDD5]/40"][class*="max-h"] {
  border: 2px solid #E0DDD5 !important;
  box-shadow: 3px 3px 0 rgba(45, 43, 85, 0.3);
}

/* Error/warning bars */
div[class*="border-l-2"][class*="border-[#FF8A80]"] {
  border: 2px solid #FF8A80 !important;
  border-left-width: 4px !important;
  box-shadow: 3px 3px 0 rgba(255, 107, 107, 0.2);
}

div[class*="border-l-2"][class*="border-[#FFE066]"] {
  border: 2px solid #FFE066 !important;
  border-left-width: 4px !important;
  box-shadow: 3px 3px 0 rgba(255, 217, 61, 0.2);
}

/* Type badges */
span[class*="py-0.5"][class*="text-[9px]"] {
  border-radius: 0 !important;
}
</style>
