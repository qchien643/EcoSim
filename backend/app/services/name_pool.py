"""
Vietnamese Name Pool — Deterministic, collision-free name generator.

Pre-built pool of 100 first names × 100 last names = 10,000 possible combos.
No LLM calls needed. Tracks used combinations to guarantee uniqueness.
"""

import random
from typing import Optional, Set, Tuple

# ── 100 Vietnamese Last Names (Họ) ──
LAST_NAMES = [
    "Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng",
    "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý", "Đào", "Đinh", "Lâm", "Mai",
    "Trương", "Lương", "Hà", "Tạ", "Cao", "Châu", "Tô", "Từ", "Thái", "Quách",
    "Vương", "Tăng", "Kiều", "Triệu", "Diệp", "Sơn", "Nhan", "Mạc", "Ông", "Trịnh",
    "Liêu", "Tống", "Khổng", "Doãn", "Nghiêm", "Lục", "Quan", "Thiều", "La", "Biện",
    "Khương", "Thạch", "Cung", "Thi", "Tiêu", "Hứa", "Ninh", "Phùng", "Mã", "Cù",
    "Giáp", "Thân", "Chung", "Khuất", "Tôn", "Đoàn", "Bạch", "Lưu", "Quản", "Sử",
    "Âu", "Dư", "Văn", "Lã", "Tú", "Trà", "Ôn", "Phó", "Viên", "Tào",
    "Giang", "Bành", "Liễu", "Kha", "Đàm", "Hàn", "Ngọc", "Cổ", "Trang", "Mạnh",
    "Vy", "Tiết", "Kim", "Bảo", "Thiện", "An", "Thanh", "Long", "Phương", "Minh",
]

# ── 100 Vietnamese First Names (Tên) — mixed gender ──
FIRST_NAMES = [
    "An", "Anh", "Bảo", "Bình", "Chi", "Cường", "Danh", "Dung", "Dũng", "Đức",
    "Giang", "Hà", "Hải", "Hạnh", "Hiếu", "Hoà", "Hoàng", "Hùng", "Hương", "Huy",
    "Khánh", "Khoa", "Kiên", "Lan", "Linh", "Long", "Lý", "Mai", "Minh", "My",
    "Nam", "Nga", "Nghĩa", "Ngọc", "Nhân", "Nhi", "Nhung", "Oanh", "Phong", "Phúc",
    "Phương", "Quân", "Quang", "Quốc", "Sơn", "Tâm", "Thảo", "Thắng", "Thanh", "Thành",
    "Thiên", "Thịnh", "Thư", "Thuận", "Thủy", "Tiến", "Tín", "Toàn", "Trang", "Trinh",
    "Trung", "Trúc", "Tuấn", "Tùng", "Uyên", "Vân", "Vinh", "Việt", "Vũ", "Xuân",
    "Yến", "Hằng", "Diệu", "Thúy", "Hiền", "Tú", "Khôi", "Đạt", "Lộc", "Tài",
    "Hoa", "Nhật", "Trâm", "Quyên", "Đan", "Thy", "Khải", "Duy", "Hưng", "Phát",
    "Lam", "Kiều", "Châu", "Ngân", "Thùy", "Như", "Quỳnh", "Khanh", "Hân", "Phượng",
]

# ── Middle name particles (Đệm) for natural-sounding names ──
MIDDLE_NAMES = [
    "Văn", "Thị", "Minh", "Thanh", "Hoàng", "Ngọc", "Quốc", "Đức", "Hữu", "Thành",
    "Kim", "Thuý", "Hồng", "Xuân", "Bảo", "Phúc", "Trọng", "Anh", "Thiên", "Tuấn",
]


class NamePool:
    """Collision-free Vietnamese name generator using pre-built pools.

    Usage:
        pool = NamePool()
        name1 = pool.pick()  # e.g. "Nguyễn Văn An"
        name2 = pool.pick()  # e.g. "Trần Thị Lan" (guaranteed unique)
        pool.reset()         # clear all used names
    """

    def __init__(self, seed: int = None):
        self._used: Set[Tuple[int, int, int]] = set()  # (last_idx, mid_idx, first_idx)
        self._used_fullnames: Set[str] = set()
        self._rng = random.Random(seed)

    @property
    def capacity(self) -> int:
        """Max unique names: 100 × 20 × 100 = 200,000."""
        return len(LAST_NAMES) * len(MIDDLE_NAMES) * len(FIRST_NAMES)

    @property
    def used_count(self) -> int:
        return len(self._used_fullnames)

    def reset(self):
        """Clear all used names — start fresh."""
        self._used.clear()
        self._used_fullnames.clear()

    def pick(self) -> str:
        """Pick a random unique Vietnamese full name.

        Returns: "Họ Đệm Tên" e.g. "Nguyễn Văn An"
        Raises ValueError if pool exhausted (>200k agents).
        """
        if len(self._used) >= self.capacity:
            raise ValueError(f"Name pool exhausted ({self.capacity} names used)")

        max_attempts = 50
        for _ in range(max_attempts):
            last_idx = self._rng.randint(0, len(LAST_NAMES) - 1)
            mid_idx = self._rng.randint(0, len(MIDDLE_NAMES) - 1)
            first_idx = self._rng.randint(0, len(FIRST_NAMES) - 1)

            key = (last_idx, mid_idx, first_idx)
            if key not in self._used:
                self._used.add(key)
                fullname = f"{LAST_NAMES[last_idx]} {MIDDLE_NAMES[mid_idx]} {FIRST_NAMES[first_idx]}"
                self._used_fullnames.add(fullname)
                return fullname

        # Fallback: linear scan for any unused combo
        for li in range(len(LAST_NAMES)):
            for mi in range(len(MIDDLE_NAMES)):
                for fi in range(len(FIRST_NAMES)):
                    key = (li, mi, fi)
                    if key not in self._used:
                        self._used.add(key)
                        fullname = f"{LAST_NAMES[li]} {MIDDLE_NAMES[mi]} {FIRST_NAMES[fi]}"
                        self._used_fullnames.add(fullname)
                        return fullname

        raise ValueError("Name pool completely exhausted")

    def is_used(self, fullname: str) -> bool:
        """Check if a full name has already been assigned."""
        return fullname in self._used_fullnames
