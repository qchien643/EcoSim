/**
 * Mirror logic của `apps/simulation/agent_cognition.py:CognitiveTraits + get_cognitive_traits()`.
 *
 * Backend tính traits tại runtime từ MBTI — KHÔNG lưu vào profiles.json.
 * Frontend tái tạo cùng mapping để hiển thị ở Agent detail panel
 * (cùng với các chỉ số runtime khác).
 *
 * Nếu backend đổi mapping ở agent_cognition.py thì sửa file này tương ứng
 * để tránh drift giữa giá trị hiển thị và behavior thực tế.
 */
import type { MBTIType } from './types/backend'

export interface CognitiveTraits {
  conviction: number // Độ bảo thủ — giữ sở thích lâu (0.1-1.0)
  forgetfulness: number // Độ hay quên — decay sở thích cũ (0.05-0.3)
  curiosity: number // Độ tò mò — pickup keyword mới (0.1-0.5)
  impressionability: number // Độ dễ bị ảnh hưởng (0.05-0.3)
}

const DEFAULT_TRAITS: CognitiveTraits = {
  conviction: 0.6,
  forgetfulness: 0.15,
  curiosity: 0.3,
  impressionability: 0.15,
}

// MBTI letter overrides — khớp `_MBTI_COGNITIVE_MAP` ở agent_cognition.py:317-326
const MBTI_OVERRIDES: Record<string, Partial<CognitiveTraits & { curiosity_bonus: number }>> = {
  J: { conviction: 0.8, curiosity: 0.2 },
  P: { conviction: 0.4, curiosity: 0.45 },
  S: { forgetfulness: 0.1 },
  N: { forgetfulness: 0.2 },
  F: { impressionability: 0.25 },
  T: { impressionability: 0.1 },
  E: { curiosity_bonus: 0.1 },
  I: { curiosity_bonus: -0.05 },
}

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v))
}

export function getCognitiveTraits(mbti: MBTIType | string): CognitiveTraits {
  const vals: CognitiveTraits = { ...DEFAULT_TRAITS }
  let curiosityBonus = 0
  for (const ch of (mbti || '').toUpperCase()) {
    const mods = MBTI_OVERRIDES[ch]
    if (!mods) continue
    if (mods.conviction != null) vals.conviction = mods.conviction
    if (mods.forgetfulness != null) vals.forgetfulness = mods.forgetfulness
    if (mods.curiosity != null) vals.curiosity = mods.curiosity
    if (mods.impressionability != null) vals.impressionability = mods.impressionability
    if (mods.curiosity_bonus) curiosityBonus = mods.curiosity_bonus
  }
  vals.curiosity = vals.curiosity + curiosityBonus

  // Final clamp — ranges khớp CognitiveTraits.__init__ ở agent_cognition.py:261-264
  return {
    conviction: clamp(vals.conviction, 0.1, 1.0),
    forgetfulness: clamp(vals.forgetfulness, 0.05, 0.3),
    curiosity: clamp(vals.curiosity, 0.1, 0.5),
    impressionability: clamp(vals.impressionability, 0.05, 0.3),
  }
}

// Range cho mỗi trait — dùng để render slider/bar chart đúng tỉ lệ.
export const TRAIT_RANGE: Record<keyof CognitiveTraits, [number, number]> = {
  conviction: [0.1, 1.0],
  forgetfulness: [0.05, 0.3],
  curiosity: [0.1, 0.5],
  impressionability: [0.05, 0.3],
}

export interface TraitMeta {
  key: keyof CognitiveTraits
  label: string // Vietnamese (user-facing)
  shortLabel: string // English compact (for chip)
  describe: (v: number) => string // Khớp CognitiveTraits.describe()
  hint: string // Effect lên simulation behavior
}

export const TRAIT_META: TraitMeta[] = [
  {
    key: 'conviction',
    label: 'Độ bảo thủ',
    shortLabel: 'Conviction',
    describe: (v) =>
      v >= 0.7
        ? 'Giữ sở thích lâu'
        : v <= 0.4
          ? 'Dễ thay đổi sở thích'
          : 'Trung bình',
    hint: 'Sở thích cũ giữ lại bao lâu khi không engage. Cao = bảo thủ.',
  },
  {
    key: 'forgetfulness',
    label: 'Độ hay quên',
    shortLabel: 'Forgetfulness',
    describe: (v) =>
      v >= 0.2
        ? 'Quên nhanh sở thích cũ'
        : v <= 0.1
          ? 'Nhớ lâu'
          : 'Trung bình',
    hint: 'Rate decay interest mỗi round: weight ×= (1 − forgetfulness).',
  },
  {
    key: 'curiosity',
    label: 'Độ tò mò',
    shortLabel: 'Curiosity',
    describe: (v) =>
      v >= 0.4
        ? 'Rất thích khám phá'
        : v <= 0.2
          ? 'Ít khám phá cái mới'
          : 'Trung bình',
    hint: 'Khả năng pickup keyword mới từ post engaged.',
  },
  {
    key: 'impressionability',
    label: 'Độ dễ bị ảnh hưởng',
    shortLabel: 'Impressionability',
    describe: (v) =>
      v >= 0.2
        ? 'Dễ thuyết phục'
        : v <= 0.1
          ? 'Khó thuyết phục'
          : 'Trung bình',
    hint: 'Mức độ thay đổi quan điểm sau khi đọc post của người khác.',
  },
]
