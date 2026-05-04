/**
 * Mirror logic của `apps/simulation/agent_cognition.py:get_behavior_modifiers()`
 * (xem mapping ở `_MBTI_DIMENSION_MODIFIERS`).
 *
 * Backend tính multipliers tại runtime từ MBTI và áp lên base action
 * probabilities mỗi round. Mapping deterministic → frontend tái tạo
 * client-side để hiển thị, không cần endpoint mới.
 *
 * DRIFT WARNING: Nếu backend đổi `_MBTI_DIMENSION_MODIFIERS` thì sửa
 * `MBTI_OVERRIDES` ở file này để khớp. Ground truth: agent_cognition.py.
 *
 * NOTE: `reflection_boost` (N×1.3, S×0.8) đã bị xoá khỏi cả 2 phía vì
 * không có consumer nào trong sim runtime — chỉ là dead code "Phase 4".
 */
import type { MBTIType } from './types/backend'

export interface BehaviorModifiers {
  post_mult: number // Tần suất đăng bài — E×1.2, I×0.8
  comment_mult: number // Tần suất bình luận — E×1.3, I×0.7
  like_mult: number // Mức độ tương tác (like) — F×1.2, T×0.9
  feed_mult: number // Độ rộng khám phá feed — P×1.2, J×0.9
}

const DEFAULT_MODIFIERS: BehaviorModifiers = {
  post_mult: 1.0,
  comment_mult: 1.0,
  like_mult: 1.0,
  feed_mult: 1.0,
}

// Khớp `_MBTI_DIMENSION_MODIFIERS` ở agent_cognition.py
const MBTI_OVERRIDES: Record<string, Partial<BehaviorModifiers>> = {
  E: { post_mult: 1.2, comment_mult: 1.3 },
  I: { post_mult: 0.8, comment_mult: 0.7 },
  F: { like_mult: 1.2 },
  T: { like_mult: 0.9 },
  P: { feed_mult: 1.2 },
  J: { feed_mult: 0.9 },
}

export function getBehaviorModifiers(mbti: MBTIType | string): BehaviorModifiers {
  const result: BehaviorModifiers = { ...DEFAULT_MODIFIERS }
  for (const ch of (mbti || '').toUpperCase()) {
    const mods = MBTI_OVERRIDES[ch]
    if (!mods) continue
    if (mods.post_mult != null) result.post_mult = mods.post_mult
    if (mods.comment_mult != null) result.comment_mult = mods.comment_mult
    if (mods.like_mult != null) result.like_mult = mods.like_mult
    if (mods.feed_mult != null) result.feed_mult = mods.feed_mult
  }
  return result
}

export interface ModifierMeta {
  key: keyof BehaviorModifiers
  label: string // tiếng Việt user-facing
  hint: string // explain effect + MBTI dimension
}

export const MODIFIER_META: ModifierMeta[] = [
  {
    key: 'post_mult',
    label: 'Tần suất đăng bài',
    hint: 'E×1.2 / I×0.8 — nhân với posting probability mỗi round.',
  },
  {
    key: 'comment_mult',
    label: 'Tần suất bình luận',
    hint: 'E×1.3 / I×0.7 — nhân với comment probability.',
  },
  {
    key: 'like_mult',
    label: 'Mức độ tương tác (like)',
    hint: 'F×1.2 / T×0.9 — nhân với like probability.',
  },
  {
    key: 'feed_mult',
    label: 'Độ rộng khám phá feed',
    hint: 'P×1.2 / J×0.9 — số post nhìn được mỗi round.',
  },
]

// Visual range cho bar — ±0.3 quanh baseline 1.0 đủ cover toàn bộ giá trị
// (min 0.7 cho I+commenter, max 1.3 cho E+commenter).
export const MODIFIER_VISUAL_RANGE: [number, number] = [0.7, 1.3]
