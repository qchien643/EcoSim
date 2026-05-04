'use client'

/**
 * MultiEdge — custom React Flow edge handling multiple edges giữa cùng 1 cặp
 * (source, target).
 *
 * Vấn đề: react-flow's default `smoothstep` / `bezier` edges KHÔNG offset
 * khi 2+ edges nối cùng 1 cặp nodes → labels overlap, paths đè nhau, user
 * không phân biệt được "Shopee COMPETES_WITH Lazada" vs "Shopee TARGETS
 * Lazada".
 *
 * Giải pháp (lấy ý từ MiroFish D3): với mỗi pair (source, target), assign
 * `pairIndex` + `pairTotal`. Path bezier qua control point offset dọc theo
 * normal vector (perpendicular đến đường thẳng source→target):
 *   offset = (pairIndex - (pairTotal-1)/2) * spacing
 *
 * Kết quả: N edges song song với khoảng cách đều. Labels không chồng nhau.
 * Single edge (pairTotal=1) → straight line through midpoint (offset=0).
 */

import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from '@xyflow/react'

const SPACING_PX = 28 // khoảng cách giữa các parallel edges, tune theo node size

interface MultiEdgeData extends Record<string, unknown> {
  pairIndex?: number
  pairTotal?: number
}

export function MultiEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  label,
  data,
  style,
  markerEnd,
}: EdgeProps) {
  const d = (data as MultiEdgeData) || {}
  const pairIndex = d.pairIndex ?? 0
  const pairTotal = d.pairTotal ?? 1

  // Midpoint
  const mx = (sourceX + targetX) / 2
  const my = (sourceY + targetY) / 2

  // Normal vector (perpendicular to source→target line)
  const dx = targetX - sourceX
  const dy = targetY - sourceY
  const len = Math.sqrt(dx * dx + dy * dy) || 1
  const nx = -dy / len
  const ny = dx / len

  // Offset proportional tới center của group: pairIndex 0,1,2 với total=3 →
  // offsets -1, 0, +1 × spacing.
  const offset = (pairIndex - (pairTotal - 1) / 2) * SPACING_PX

  const cx = mx + nx * offset
  const cy = my + ny * offset

  // Quadratic bezier qua control point. pairTotal=1 + offset=0 → control =
  // midpoint → degenerate thành straight line (visual không phân biệt được
  // với line, nhưng path SVG là valid).
  const path = `M ${sourceX},${sourceY} Q ${cx},${cy} ${targetX},${targetY}`

  return (
    <>
      <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} />
      {label && (
        <EdgeLabelRenderer>
          <div
            // Position label tại control point (offset từ midpoint), giúp
            // labels của parallel edges không chồng. Nudge vertical cho
            // single edge để label không overlap với path.
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${cx}px, ${cy}px)`,
              fontSize: 9,
              fontWeight: 500,
              color: '#52525b',
              background: 'rgba(250, 250, 250, 0.92)',
              padding: '2px 4px',
              borderRadius: 3,
              pointerEvents: 'none',
              whiteSpace: 'nowrap',
            }}
            className="nodrag nopan"
          >
            {String(label)}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
