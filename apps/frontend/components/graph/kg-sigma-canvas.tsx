'use client'

/**
 * KGSigmaCanvas — Knowledge Graph viz dùng Sigma.js (WebGL) + Graphology.
 *
 * Khác biệt vs `KGFlowCanvas` (React Flow + dagre):
 *  - WebGL renderer: 5-10x nhanh hơn DOM khi >100 nodes.
 *  - ForceAtlas2 chạy trong Web Worker → không block main thread, layout
 *    settle dần trong ~2s rồi stop.
 *  - Dynamic import (sigma + graphology lazy) → giảm initial bundle.
 *
 * UX (match design hình tham khảo):
 *  - Node = circle nhỏ color theo canonical entity type.
 *  - Edge labels luôn visible (USES, COMPETES_WITH, ...).
 *  - Counter top-right "X nodes · Y cạnh".
 *  - Legend bottom: type → color swatch.
 *  - Hint bottom: "Kéo node · Scroll zoom · Double-click reset".
 *  - Click node → emit onSelect.
 *  - Drag node để re-position (FA2 đã stop sau settle).
 *  - Double-click stage → reset camera.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type { GraphEntity, GraphEdge } from '@/lib/types/backend'
import { cn } from '@/lib/utils'

// Color hex per canonical entity type — mirror với TYPE_STYLES ở
// kg-flow-canvas.tsx accent. WebGL renderer cần concrete hex (không Tailwind).
const TYPE_HEX: Record<string, string> = {
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

function colorOf(type?: string | null): string {
  return TYPE_HEX[type || 'Entity'] || TYPE_HEX.Entity
}

export interface KGSigmaCanvasProps {
  entities: GraphEntity[]
  edges: GraphEdge[]
  activeEntityName?: string | null
  activeType?: string | null
  /** Tên node đang focus (chỉ hiển thị node + neighbors). Null = full graph. */
  focusedName?: string | null
  onSelect?: (name: string) => void
  /** Double-click trên node → focus on 1-hop neighbors. Cùng node → reset. */
  onDoubleClickNode?: (name: string) => void
}

export function KGSigmaCanvas({
  entities,
  edges,
  activeEntityName,
  activeType,
  focusedName,
  onSelect,
  onDoubleClickNode,
}: KGSigmaCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  // Refs persisted across renders (Sigma + Graph instance + FA2 worker).
  const sigmaRef = useRef<unknown>(null)
  const graphRef = useRef<unknown>(null)
  const fa2Ref = useRef<{ stop: () => void; kill: () => void } | null>(null)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect
  const onDoubleClickNodeRef = useRef(onDoubleClickNode)
  onDoubleClickNodeRef.current = onDoubleClickNode

  const [ready, setReady] = useState(false)

  // Stable signature of data — chỉ rebuild graph khi entity/edge set thay đổi
  // (compare bằng count + first/last name) không phải mỗi lần parent re-render.
  const dataSig = useMemo(() => {
    const e0 = entities[0]?.name || ''
    const eN = entities[entities.length - 1]?.name || ''
    const ed0 = edges[0]
    const edN = edges[edges.length - 1]
    return `${entities.length}|${edges.length}|${e0}|${eN}|${ed0?.source}>${ed0?.target}|${edN?.source}>${edN?.target}`
  }, [entities, edges])

  const typeCounts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const e of entities) c[e.type || 'Entity'] = (c[e.type || 'Entity'] || 0) + 1
    return Object.entries(c).sort((a, b) => b[1] - a[1])
  }, [entities])

  // ── Build / rebuild Sigma + Graphology khi data sig đổi ─────────────
  useEffect(() => {
    if (!containerRef.current) return
    if (entities.length === 0) return

    let cancelled = false

    ;(async () => {
      // Lazy imports — split chunk, không vào initial bundle
      const [{ default: Graph }, { default: Sigma }, layoutMod, fa2Mod, fa2WorkerMod] =
        await Promise.all([
          import('graphology'),
          import('sigma'),
          import('graphology-layout'),
          import('graphology-layout-forceatlas2'),
          import('graphology-layout-forceatlas2/worker'),
        ])
      if (cancelled || !containerRef.current) return

      // Cleanup old instance trước khi build mới (data signature changed)
      if (fa2Ref.current) {
        try { fa2Ref.current.kill() } catch {}
        fa2Ref.current = null
      }
      if (sigmaRef.current) {
        try { (sigmaRef.current as { kill: () => void }).kill() } catch {}
        sigmaRef.current = null
      }

      // ── Build Graphology graph ──────────────────────────────────────
      const graph = new Graph({ multi: true, type: 'directed' })
      const present = new Set<string>()
      for (const e of entities) {
        if (graph.hasNode(e.name)) continue
        graph.addNode(e.name, {
          label: e.name,
          // size scale: 6-12 px, có size highlight ở effect khác
          size: 7,
          color: colorOf(e.type),
          entityType: e.type || 'Entity',
          summary: e.summary || '',
        })
        present.add(e.name)
      }
      // Edges chỉ thêm khi cả 2 endpoints có trong graph
      for (const e of edges) {
        if (!e.source || !e.target) continue
        if (!present.has(e.source) || !present.has(e.target)) continue
        graph.addEdgeWithKey(
          `${e.source}->${e.target}-${graph.size}`,
          e.source,
          e.target,
          {
            label: (e.relation || '').toUpperCase(),
            size: e.relation === 'MENTIONS' ? 0.8 : 1.4,
            color: e.relation === 'MENTIONS' ? '#d4d4d8' : '#a1a1aa',
            relation: e.relation || '',
            fact: e.fact || '',
          },
        )
      }

      // Initial positions — circular fallback (instant), FA2 sẽ refine
      ;(layoutMod.circular as { assign: (g: unknown) => void }).assign(graph)

      // ── Mount Sigma ────────────────────────────────────────────────
      // allowInvalidContainer: tránh throw khi container width=0 (vd grid
      // chưa layout xong khi mount). Sigma sẽ tự refresh khi container resize.
      const sigma = new (Sigma as new (
        g: unknown,
        c: HTMLElement,
        s: Record<string, unknown>,
      ) => unknown)(graph, containerRef.current, {
        renderEdgeLabels: true,
        defaultEdgeType: 'line',
        labelRenderedSizeThreshold: 6,
        labelDensity: 0.7,
        labelGridCellSize: 60,
        labelFont: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
        labelSize: 11,
        labelColor: { color: '#3f3f46' },
        edgeLabelFont: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
        edgeLabelSize: 9,
        edgeLabelColor: { color: '#71717a' },
        zIndex: true,
        minCameraRatio: 0.1,
        maxCameraRatio: 4,
        allowInvalidContainer: true,
      })

      sigmaRef.current = sigma
      graphRef.current = graph

      // ── Click node → onSelect ──────────────────────────────────────
      type SigmaEvent = {
        node?: string
        original?: Event
        preventSigmaDefault?: () => void
      }
      type CaptorEvent = {
        preventSigmaDefault?: () => void
        original?: { preventDefault: () => void; stopPropagation: () => void }
        x?: number
        y?: number
      }
      const sigmaTyped = sigma as {
        on: (ev: string, h: (e: SigmaEvent) => void) => void
        getMouseCaptor: () => {
          on: (ev: string, h: (e: CaptorEvent) => void) => void
        }
        viewportToGraph: (e: { x?: number; y?: number }) => { x: number; y: number }
        getCamera: () => { animatedReset: () => void }
      }
      sigmaTyped.on('clickNode', (e) => {
        if (e.node) onSelectRef.current?.(e.node)
      })
      // Double-click trên node → emit focus event (parent toggle 1-hop view)
      sigmaTyped.on('doubleClickNode', (e) => {
        if (e.node) {
          // Prevent default → tránh trigger doubleClickStage reset camera
          e.preventSigmaDefault?.()
          onDoubleClickNodeRef.current?.(e.node)
        }
      })

      // ── Drag node ──────────────────────────────────────────────────
      let draggedNode: string | null = null
      let isDragging = false
      const g = graph as unknown as {
        setNodeAttribute: (n: string, k: string, v: unknown) => void
        removeNodeAttribute: (n: string, k: string) => void
      }
      sigmaTyped.on('downNode', (e) => {
        if (!e.node) return
        draggedNode = e.node
        isDragging = true
        g.setNodeAttribute(e.node, 'highlighted', true)
      })
      const cap = sigmaTyped.getMouseCaptor()
      cap.on('mousemovebody', (e) => {
        if (!isDragging || !draggedNode) return
        const pos = sigmaTyped.viewportToGraph({ x: e.x, y: e.y })
        g.setNodeAttribute(draggedNode, 'x', pos.x)
        g.setNodeAttribute(draggedNode, 'y', pos.y)
        e.preventSigmaDefault?.()
        e.original?.preventDefault()
        e.original?.stopPropagation()
      })
      const onMouseUp = () => {
        if (draggedNode) {
          try { g.removeNodeAttribute(draggedNode, 'highlighted') } catch {}
        }
        isDragging = false
        draggedNode = null
      }
      cap.on('mouseup', onMouseUp)

      // ── Double-click stage → reset camera ──────────────────────────
      sigmaTyped.on('doubleClickStage', (e) => {
        e.preventSigmaDefault?.()
        sigmaTyped.getCamera().animatedReset()
      })

      // ── ForceAtlas2 layout in worker ───────────────────────────────
      // inferSettings tune barnesHutOptimize, scalingRatio, ... theo graph size.
      const settings = (
        fa2Mod as unknown as {
          inferSettings: (g: unknown) => Record<string, unknown>
        }
      ).inferSettings(graph)
      const FA2 = fa2WorkerMod.default as new (
        g: unknown,
        opts: { settings: Record<string, unknown> },
      ) => { start: () => void; stop: () => void; kill: () => void }
      const fa2 = new FA2(graph, { settings })
      fa2Ref.current = fa2
      fa2.start()

      // Stop sau settle window — đủ converge cho graph 100-500 nodes,
      // không CPU drain liên tục. Bigger graph cần dài hơn.
      const settleMs = entities.length > 200 ? 3500 : 2000
      const stopTimer = window.setTimeout(() => {
        try { fa2.stop() } catch {}
      }, settleMs)

      setReady(true)

      // Cleanup local timer khi effect re-run
      return () => {
        window.clearTimeout(stopTimer)
      }
    })()

    return () => {
      cancelled = true
    }
    // dataSig drives full rebuild; container ref stable
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataSig])

  // ── Highlight active entity / focus 1-hop / dim non-matching type ───
  useEffect(() => {
    const graph = graphRef.current as
      | {
          forEachNode: (cb: (n: string, attrs: Record<string, unknown>) => void) => void
          forEachEdge: (
            cb: (
              e: string,
              attrs: Record<string, unknown>,
              src: string,
              tgt: string,
            ) => void,
          ) => void
          setNodeAttribute: (n: string, k: string, v: unknown) => void
          setEdgeAttribute: (e: string, k: string, v: unknown) => void
          hasNode: (n: string) => boolean
          neighbors: (n: string) => string[]
        }
      | null
    const sigma = sigmaRef.current as { refresh: () => void } | null
    if (!graph || !sigma) return

    // Build focus visibility set: focused node + 1-hop neighbors
    const focusSet =
      focusedName && graph.hasNode(focusedName)
        ? new Set<string>([focusedName, ...graph.neighbors(focusedName)])
        : null

    graph.forEachNode((id, attrs) => {
      const t = (attrs.entityType as string) || 'Entity'
      const isActive = id === activeEntityName
      const isFocusRoot = id === focusedName
      const isInFocus = !focusSet || focusSet.has(id)
      const isDimmedByType = !!activeType && t !== activeType
      const isDimmedByFocus = !isInFocus
      const isDimmed = isDimmedByType || isDimmedByFocus
      const baseColor = colorOf(t)

      // Size: focus root largest, active medium, neighbors normal, dimmed small
      let size = 7
      if (isFocusRoot) size = 16
      else if (isActive) size = 14
      else if (focusSet && isInFocus) size = 9
      else if (isDimmed) size = 5

      graph.setNodeAttribute(id, 'size', size)
      graph.setNodeAttribute(
        id,
        'color',
        isDimmed ? '#e4e4e7' : baseColor,
      )
      graph.setNodeAttribute(
        id,
        'zIndex',
        isFocusRoot ? 3 : isActive ? 2 : isDimmed ? 0 : 1,
      )
      // Hidden cho nodes ngoài focus (nếu focus mode active)
      graph.setNodeAttribute(id, 'hidden', focusSet ? !isInFocus : false)
    })

    // Edges: chỉ visible nếu cả 2 endpoints trong focus set
    graph.forEachEdge((eid, _attrs, src, tgt) => {
      const visible = !focusSet || (focusSet.has(src) && focusSet.has(tgt))
      graph.setEdgeAttribute(eid, 'hidden', !visible)
    })

    sigma.refresh()
  }, [activeEntityName, activeType, focusedName, ready])

  // ── Cleanup on unmount ──────────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (fa2Ref.current) {
        try { fa2Ref.current.kill() } catch {}
        fa2Ref.current = null
      }
      if (sigmaRef.current) {
        try { (sigmaRef.current as { kill: () => void }).kill() } catch {}
        sigmaRef.current = null
      }
    }
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
      {/* Sigma container — fills parent */}
      <div ref={containerRef} className="absolute inset-0 sigma-bg-dotted" />

      {/* Top-left zoom hint badge — match design */}
      <div className="pointer-events-none absolute left-3 top-3 z-10 rounded-full border border-border bg-white/90 px-3 py-1 text-2xs font-medium text-fg-muted shadow-sm backdrop-blur-sm">
        Zoom để xem chi tiết
      </div>

      {/* Top-right counter "X nodes · Y cạnh" */}
      <div className="pointer-events-none absolute right-3 top-3 z-10 rounded-full border border-border bg-white/90 px-3 py-1 text-2xs font-medium text-fg shadow-sm backdrop-blur-sm">
        {entities.length} nodes · {edges.length} cạnh
      </div>

      {/* Bottom legend (chip type:color) + hint */}
      <div className="pointer-events-none absolute inset-x-3 bottom-3 z-10 flex items-end justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 rounded-md bg-white/85 px-2.5 py-1.5 text-2xs shadow-sm backdrop-blur-sm">
          {typeCounts.slice(0, 8).map(([type]) => (
            <div key={type} className="flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: colorOf(type) }}
              />
              <span className="font-medium text-fg-muted">{type}</span>
            </div>
          ))}
        </div>
        <div className="rounded-md bg-white/85 px-2.5 py-1 text-2xs text-fg-faint shadow-sm backdrop-blur-sm">
          Kéo node · Scroll zoom · Double-click node để focus 1-hop
        </div>
      </div>
    </div>
  )
}
