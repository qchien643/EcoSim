'use client'

/**
 * KGFlowCanvas — Knowledge Graph visualization với React Flow + dagre layout.
 *
 * Render entities + edges từ FalkorDB-backed KG. Dagre auto-layout (left-right
 * hierarchical), color-coded nodes theo canonical entity type, edge labels là
 * canonical edge_type (COMPETES_WITH, PARTNERS_WITH, ...).
 *
 * Features:
 *  - Click node → emit `onSelect(name)` cho parent (highlight detail panel)
 *  - Active type filter → dim nodes không match
 *  - Active entity → highlight + scale up
 *  - Entrance fade-in animation khi data load (mỗi node stagger 30ms)
 *  - Replay animation button
 *  - Empty state khi không có data (đang build hoặc empty graph)
 *
 * Performance: ~500 nodes ổn (react-flow dùng react-reconciler virtual DOM),
 * dagre layout O(V+E) trên small graphs.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import dagre from 'dagre'
import { RotateCcw } from 'lucide-react'

import '@xyflow/react/dist/style.css'

import type { GraphEntity, GraphEdge } from '@/lib/types/backend'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { MultiEdge } from './multi-edge'

// Tailwind classes per canonical entity type. Pastel-ish, đủ contrast giữa
// các types khi render side-by-side. Match `CANONICAL_ENTITY_TYPES` ở
// apps/simulation/campaign_knowledge.py.
const TYPE_STYLES: Record<
  string,
  { bg: string; border: string; text: string; accent: string }
> = {
  Company: {
    bg: 'bg-blue-50',
    border: 'border-blue-400',
    text: 'text-blue-900',
    accent: 'bg-blue-500',
  },
  Consumer: {
    bg: 'bg-emerald-50',
    border: 'border-emerald-400',
    text: 'text-emerald-900',
    accent: 'bg-emerald-500',
  },
  Product: {
    bg: 'bg-purple-50',
    border: 'border-purple-400',
    text: 'text-purple-900',
    accent: 'bg-purple-500',
  },
  Competitor: {
    bg: 'bg-rose-50',
    border: 'border-rose-400',
    text: 'text-rose-900',
    accent: 'bg-rose-500',
  },
  Investor: {
    bg: 'bg-amber-50',
    border: 'border-amber-400',
    text: 'text-amber-900',
    accent: 'bg-amber-500',
  },
  Supplier: {
    bg: 'bg-teal-50',
    border: 'border-teal-400',
    text: 'text-teal-900',
    accent: 'bg-teal-500',
  },
  Regulator: {
    bg: 'bg-orange-50',
    border: 'border-orange-400',
    text: 'text-orange-900',
    accent: 'bg-orange-500',
  },
  MediaOutlet: {
    bg: 'bg-pink-50',
    border: 'border-pink-400',
    text: 'text-pink-900',
    accent: 'bg-pink-500',
  },
  Campaign: {
    bg: 'bg-violet-50',
    border: 'border-violet-400',
    text: 'text-violet-900',
    accent: 'bg-violet-500',
  },
  Market: {
    bg: 'bg-sky-50',
    border: 'border-sky-400',
    text: 'text-sky-900',
    accent: 'bg-sky-500',
  },
  Person: {
    bg: 'bg-fuchsia-50',
    border: 'border-fuchsia-400',
    text: 'text-fuchsia-900',
    accent: 'bg-fuchsia-500',
  },
  Organization: {
    bg: 'bg-slate-100',
    border: 'border-slate-400',
    text: 'text-slate-900',
    accent: 'bg-slate-500',
  },
  Policy: {
    bg: 'bg-indigo-50',
    border: 'border-indigo-400',
    text: 'text-indigo-900',
    accent: 'bg-indigo-500',
  },
  EconomicIndicator: {
    bg: 'bg-lime-50',
    border: 'border-lime-400',
    text: 'text-lime-900',
    accent: 'bg-lime-500',
  },
  Entity: {
    bg: 'bg-zinc-50',
    border: 'border-zinc-400',
    text: 'text-zinc-900',
    accent: 'bg-zinc-500',
  },
}

// Circular node footprint: circle 56px ở giữa + label area below.
// Tổng container 140w × 100h cho dagre layout (đủ space cho text 2 dòng).
const NODE_WIDTH = 140
const NODE_HEIGHT = 100
const CIRCLE_SIZE = 56

// ──────────────────────────────────────────────
// Custom node renderer
// ──────────────────────────────────────────────
type EntityNodeData = {
  label: string
  type: string
  summary?: string
  isActive: boolean
  isDimmed: boolean
  staggerDelay: number
}

function EntityNode({ data }: NodeProps) {
  const d = data as EntityNodeData
  const style = TYPE_STYLES[d.type] || TYPE_STYLES.Entity
  // Initial = first non-whitespace char (uppercase). Cho non-Latin (vd
  // "Bộ Công Thương") sẽ lấy "B" — vẫn readable.
  const initial = (d.label || '?').trim().charAt(0).toUpperCase() || '?'
  return (
    <div
      className={cn(
        'group relative flex flex-col items-center gap-1.5',
        'transition-all duration-300',
        d.isActive && 'scale-110',
        d.isDimmed && 'opacity-25',
        'animate-in fade-in-0 zoom-in-50',
      )}
      style={{
        width: NODE_WIDTH,
        animationDelay: `${d.staggerDelay}ms`,
        animationFillMode: 'both',
      }}
      title={d.summary || d.label}
    >
      {/* Circle node */}
      <div
        className={cn(
          'relative flex items-center justify-center rounded-full border-2 shadow-sm',
          'transition-shadow',
          style.bg,
          style.border,
          d.isActive && 'shadow-lg ring-2 ring-offset-2 ring-fg/30',
        )}
        style={{ width: CIRCLE_SIZE, height: CIRCLE_SIZE }}
      >
        <Handle
          type="target"
          position={Position.Left}
          className="!w-1.5 !h-1.5 !border-0 !bg-fg-muted/50"
        />
        {/* Type accent dot — top-right corner badge */}
        <span
          className={cn(
            'absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-white',
            style.accent,
          )}
        />
        {/* Initial */}
        <span className={cn('text-base font-bold leading-none', style.text)}>
          {initial}
        </span>
        <Handle
          type="source"
          position={Position.Right}
          className="!w-1.5 !h-1.5 !border-0 !bg-fg-muted/50"
        />
      </div>
      {/* Label below circle — name + type. Center-aligned, truncate dài. */}
      <div className="flex flex-col items-center gap-0 text-center leading-tight">
        <span
          className={cn(
            'block max-w-[130px] truncate text-[11px] font-medium text-fg',
            d.isActive && 'font-semibold',
          )}
        >
          {d.label}
        </span>
        <span className="block text-[9px] font-medium uppercase tracking-wider text-fg-faint">
          {d.type}
        </span>
      </div>
    </div>
  )
}

const nodeTypes = { entity: EntityNode }
const edgeTypes = { multi: MultiEdge }

// ──────────────────────────────────────────────
// Dagre auto-layout
// ──────────────────────────────────────────────
function applyDagreLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({
    rankdir: 'LR',           // left → right flow (chiều horizontal)
    ranksep: 140,            // khoảng cách giữa các "rank" (cột) — rộng hơn cho circular nodes dễ thấy
    nodesep: 50,              // khoảng cách giữa nodes cùng rank
    edgesep: 20,              // khoảng cách giữa edges cùng cặp source/target
    marginx: 40,
    marginy: 40,
    ranker: 'tight-tree',    // 'network-simplex' (default) | 'tight-tree' | 'longest-path'
                             // 'tight-tree' cho tree-like graph (ít cycles) layout compact hơn
  })

  nodes.forEach((n) => g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }))
  edges.forEach((e) => g.setEdge(e.source, e.target))

  dagre.layout(g)

  return nodes.map((n) => {
    const pos = g.node(n.id)
    return {
      ...n,
      position: pos
        ? { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 }
        : { x: 0, y: 0 },
    }
  })
}

// ──────────────────────────────────────────────
// Main component
// ──────────────────────────────────────────────
export interface KGFlowCanvasProps {
  entities: GraphEntity[]
  edges: GraphEdge[]
  /** Active entity name (highlighted + scaled up). */
  activeEntityName?: string | null
  /** Active type filter — non-matching nodes dimmed. Null = no filter. */
  activeType?: string | null
  /** Click node callback — pass entity name. */
  onSelect?: (name: string) => void
}

export function KGFlowCanvas({
  entities,
  edges,
  activeEntityName,
  activeType,
  onSelect,
}: KGFlowCanvasProps) {
  const [animKey, setAnimKey] = useState(0) // bump to replay animation

  const flowNodes = useMemo<Node[]>(() => {
    return entities.map((e, idx) => {
      const isActive = activeEntityName === e.name
      const isDimmed = !!activeType && (e.type || 'Unknown') !== activeType
      return {
        id: e.name,
        type: 'entity',
        position: { x: 0, y: 0 },
        data: {
          label: e.name,
          type: e.type || 'Entity',
          summary: e.summary,
          isActive,
          isDimmed,
          // 60ms stagger — total reveal ~1s cho 17 nodes, đủ visible để user
          // thấy "build progression" (từ nothing tới complete) khi data load
          // hoặc khi click Replay.
          staggerDelay: idx * 60,
        } satisfies EntityNodeData,
        draggable: true,
      }
    })
  }, [entities, activeEntityName, activeType])

  const flowEdges = useMemo<Edge[]>(() => {
    const valid = edges.filter((e) => e.source && e.target)

    // Pre-compute pairIndex + pairTotal cho multi-edge offset.
    // Key = "src→tgt" (directional), không gộp reverse direction để A→B và
    // B→A vẫn là 2 group riêng (rare nhưng đúng semantics directed graph).
    const pairCounts: Record<string, number> = {}
    const pairOrder: Record<string, number> = {}
    for (const e of valid) {
      const k = `${e.source}${e.target}`
      pairCounts[k] = (pairCounts[k] || 0) + 1
    }

    return valid.map((e, i) => {
      const isMentions = e.relation === 'MENTIONS'
      const k = `${e.source}${e.target}`
      const pairIndex = pairOrder[k] ?? 0
      pairOrder[k] = pairIndex + 1
      const pairTotal = pairCounts[k]

      return {
        id: `${e.source}->${e.target}-${i}`,
        source: e.source,
        target: e.target,
        label: e.relation,
        type: 'multi',
        data: { pairIndex, pairTotal },
        animated: false,
        // MENTIONS edges (Episodic → Entity) dashed thinner để bớt visual noise.
        style: isMentions
          ? { strokeDasharray: '4 4', stroke: '#a1a1aa', strokeWidth: 1 }
          : { stroke: '#71717a', strokeWidth: 1.5 },
      }
    })
  }, [edges])

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(flowNodes)
  const [edgesState, setEdgesState, onEdgesChange] = useEdgesState<Edge>(flowEdges)

  // Re-layout + re-render khi data hoặc filter đổi.
  useEffect(() => {
    const laid = applyDagreLayout(flowNodes, flowEdges)
    setNodes(laid)
    setEdgesState(flowEdges)
  }, [flowNodes, flowEdges, setNodes, setEdgesState])

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onSelect?.(node.id)
    },
    [onSelect],
  )

  const replayAnimation = useCallback(() => {
    setAnimKey((k) => k + 1)
  }, [])

  if (entities.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border bg-surface-subtle text-xs text-fg-faint">
        <div className="relative flex h-3 w-3">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-fg-faint/40 opacity-75" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-fg-faint/60" />
        </div>
        <span>Chưa có entities — đang đợi build / chưa build.</span>
      </div>
    )
  }

  return (
    <div className="relative h-full w-full overflow-hidden rounded-md border border-border bg-white">
      {/* Replay animation button — top-right overlay */}
      <button
        type="button"
        onClick={replayAnimation}
        className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-md border border-border bg-white/90 px-2 py-1 text-2xs font-medium text-fg-muted backdrop-blur-sm transition-colors hover:bg-surface hover:text-fg"
        title="Replay reveal animation"
      >
        <RotateCcw size={12} />
        Replay
      </button>

      <ReactFlow
        key={animKey} /* re-mount → re-trigger entrance animation */
        nodes={nodes}
        edges={edgesState}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        fitView
        fitViewOptions={{ padding: 0.15, includeHiddenNodes: false }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
        maxZoom={2.5}
        defaultEdgeOptions={{
          type: 'multi',
        }}
      >
        <Background gap={16} size={1} color="#e4e4e7" />
        <Controls position="bottom-right" showInteractive={false} />
        <MiniMap
          position="bottom-left"
          pannable
          zoomable
          nodeColor={(n) => {
            const t = (n.data as EntityNodeData)?.type || 'Entity'
            const style = TYPE_STYLES[t] || TYPE_STYLES.Entity
            // Map Tailwind class → hex (approximate, MiniMap không parse Tailwind)
            const ACCENT_HEX: Record<string, string> = {
              Company: '#3b82f6',
              Consumer: '#10b981',
              Product: '#a855f7',
              Competitor: '#f43f5e',
              Investor: '#f59e0b',
              Supplier: '#14b8a6',
              Regulator: '#f97316',
              MediaOutlet: '#ec4899',
              Campaign: '#8b5cf6',
              Market: '#0ea5e9',
              Person: '#d946ef',
              Organization: '#64748b',
              Policy: '#6366f1',
              EconomicIndicator: '#84cc16',
              Entity: '#71717a',
            }
            void style
            return ACCENT_HEX[t] || ACCENT_HEX.Entity
          }}
          maskColor="rgba(250, 250, 250, 0.7)"
        />
      </ReactFlow>
    </div>
  )
}
