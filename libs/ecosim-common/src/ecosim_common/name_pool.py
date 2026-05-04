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

# ── Vietnamese First Names (Tên) — split theo gender ──
# Một số tên unisex (An, Anh, Bảo, Minh, ...) xuất hiện ở cả hai pool.
FIRST_NAMES_MALE = [
    "An", "Anh", "Bảo", "Bình", "Cường", "Danh", "Dũng", "Đức",
    "Hải", "Hiếu", "Hoàng", "Hùng", "Huy",
    "Khánh", "Khoa", "Kiên", "Long", "Lý", "Minh",
    "Nam", "Nghĩa", "Nhân", "Phong", "Phúc",
    "Quân", "Quang", "Quốc", "Sơn", "Tâm", "Thắng", "Thanh", "Thành",
    "Thiên", "Thịnh", "Thuận", "Tiến", "Tín", "Toàn",
    "Trung", "Tuấn", "Tùng", "Vinh", "Việt", "Vũ",
    "Khôi", "Đạt", "Lộc", "Tài", "Nhật", "Khải", "Duy", "Hưng", "Phát",
]

FIRST_NAMES_FEMALE = [
    "An", "Anh", "Bảo", "Chi", "Dung",
    "Giang", "Hà", "Hạnh", "Hoà", "Hương",
    "Lan", "Linh", "Mai", "My",
    "Nga", "Ngọc", "Nhi", "Nhung", "Oanh",
    "Phương", "Thảo", "Thư", "Thủy", "Trang", "Trinh",
    "Trúc", "Uyên", "Vân", "Xuân",
    "Yến", "Hằng", "Diệu", "Thúy", "Hiền", "Tú",
    "Hoa", "Trâm", "Quyên", "Đan", "Thy",
    "Lam", "Kiều", "Châu", "Ngân", "Thùy", "Như", "Quỳnh", "Khanh", "Hân", "Phượng",
]

# Tất cả tên (dùng khi không xác định gender)
FIRST_NAMES = sorted(set(FIRST_NAMES_MALE + FIRST_NAMES_FEMALE))

# ── Middle name particles (Đệm) for natural-sounding names ──
# Thị thường cho nữ, Văn thường cho nam; còn lại unisex.
MIDDLE_NAMES_MALE = [
    "Văn", "Minh", "Thanh", "Hoàng", "Ngọc", "Quốc", "Đức", "Hữu", "Thành",
    "Kim", "Xuân", "Bảo", "Phúc", "Trọng", "Anh", "Thiên", "Tuấn",
]
MIDDLE_NAMES_FEMALE = [
    "Thị", "Minh", "Thanh", "Ngọc", "Kim", "Thuý", "Hồng", "Xuân",
    "Bảo", "Phúc", "Anh", "Thiên",
]
MIDDLE_NAMES = sorted(set(MIDDLE_NAMES_MALE + MIDDLE_NAMES_FEMALE))


class NamePool:
    """Collision-free Vietnamese name generator using pre-built pools.

    Gender-aware: nếu gender="male"/"female" thì chỉ pick trong pool tương ứng,
    tránh lệch giới (ví dụ "Nguyễn Thị Tuấn"). Nếu gender=None thì dùng pool unisex.

    Usage:
        pool = NamePool(seed=42)
        name1 = pool.pick(gender="female")  # e.g. "Nguyễn Thị Lan"
        name2 = pool.pick(gender="male")    # e.g. "Trần Văn Minh"
        pool.reset()                         # clear all used names
    """

    def __init__(self, seed: int = None):
        self._used: Set[Tuple[str, str, str]] = set()
        self._used_fullnames: Set[str] = set()
        self._rng = random.Random(seed)

    @property
    def capacity(self) -> int:
        """Max unique names ~ 100 × 20 × 100 = 200,000 (union of gender pools)."""
        return len(LAST_NAMES) * len(MIDDLE_NAMES) * len(FIRST_NAMES)

    @property
    def used_count(self) -> int:
        return len(self._used_fullnames)

    def reset(self):
        """Clear all used names — start fresh."""
        self._used.clear()
        self._used_fullnames.clear()

    def _pools_for(self, gender: Optional[str]) -> Tuple[list, list]:
        """Return (middle_pool, first_pool) appropriate for gender."""
        g = (gender or "").strip().lower()
        if g == "male":
            return MIDDLE_NAMES_MALE, FIRST_NAMES_MALE
        if g == "female":
            return MIDDLE_NAMES_FEMALE, FIRST_NAMES_FEMALE
        return MIDDLE_NAMES, FIRST_NAMES

    def pick(self, gender: Optional[str] = None) -> str:
        """Pick a unique Vietnamese full name (optionally gender-aware).

        Returns: "Họ Đệm Tên" e.g. "Nguyễn Văn An"
        Raises ValueError if pool exhausted for the requested gender.
        """
        middle_pool, first_pool = self._pools_for(gender)
        max_attempts = 50
        for _ in range(max_attempts):
            last = self._rng.choice(LAST_NAMES)
            middle = self._rng.choice(middle_pool)
            first = self._rng.choice(first_pool)
            key = (last, middle, first)
            if key not in self._used:
                self._used.add(key)
                fullname = f"{last} {middle} {first}"
                self._used_fullnames.add(fullname)
                return fullname

        # Fallback: linear scan within the gender pool
        for last in LAST_NAMES:
            for middle in middle_pool:
                for first in first_pool:
                    key = (last, middle, first)
                    if key not in self._used:
                        self._used.add(key)
                        fullname = f"{last} {middle} {first}"
                        self._used_fullnames.add(fullname)
                        return fullname

        raise ValueError(f"Name pool exhausted for gender={gender!r}")

    def is_used(self, fullname: str) -> bool:
        """Check if a full name has already been assigned."""
        return fullname in self._used_fullnames
