"""
Sim Zep Ontology — schema cho Zep Cloud `set_ontology` trên sim runtime graph.

Phase E.2: mỗi sim có graph_id="sim_<sid>" trên Zep server. Ontology riêng
(khác master KG ontology ở apps/simulation/zep_ontology.py).

Mục tiêu ontology:
- 4 entity types KẾ THỪA từ master (Company, Product, Campaign, Market) để
  Zep extract content recognize cross-domain — vd post nói "Shopee giảm giá"
  → Zep tạo Company:Shopee + edge MENTIONS_BRAND về master entity.
- 6 entity types SIM-SPECIFIC: Agent, Post, Topic, Sentiment, Trend, Concern.
- 10 edge types CONTENT-DRIVEN (structural như LIKED, FOLLOWED KHÔNG có ở đây
  vì đã được lưu trong oasis_simulation.db SQL — KG chỉ chứa ngữ nghĩa Phase 13).

Zep API limits: max 10 entity types + 10 edge types per project — đã trim
exact 10/10 (đã verify với master ontology Phase A).

Compatibility: code reuse `apply_ontology()` pattern từ `zep_ontology.py` —
caller pass `entities=SIM_ENTITY_TYPES, edges=SIM_EDGE_TYPES`.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from zep_cloud.external_clients.ontology import (
    EdgeModel,
    EntityModel,
    EntityText,
    Field,
)
from zep_cloud.types.entity_edge_source_target import EntityEdgeSourceTarget

logger = logging.getLogger("sim-svc.sim_zep_ontology")


# ──────────────────────────────────────────────
# Inherited from master KG (cho cross-domain extract recognize)
# ──────────────────────────────────────────────
class Company(EntityModel):
    """Doanh nghiệp/thương hiệu được nhắc trong post (Shopee, Lazada, Tiki)."""
    industry: EntityText = Field(description="Ngành (TMĐT, F&B, FinTech, ...)", default=None)
    brand_perception: EntityText = Field(
        description="Cảm nhận thương hiệu trong post (positive/negative/neutral)",
        default=None,
    )


class Product(EntityModel):
    """Sản phẩm cụ thể được nhắc trong post."""
    category: EntityText = Field(description="Loại sản phẩm", default=None)
    price_signal: EntityText = Field(
        description="Tín hiệu giá nếu có (giảm giá, tăng giá, ...)",
        default=None,
    )


class Campaign(EntityModel):
    """Chiến dịch/sự kiện marketing được agent thảo luận."""
    campaign_type: EntityText = Field(description="Loại chiến dịch", default=None)


class Market(EntityModel):
    """Thị trường/khu vực địa lý."""
    region: EntityText = Field(description="Khu vực", default=None)


# ──────────────────────────────────────────────
# Sim-specific
# ──────────────────────────────────────────────
class Agent(EntityModel):
    """Người dùng (agent) tham gia simulation."""
    role: EntityText = Field(
        description="Vai trò xã hội (KOL, người tiêu dùng, người ảnh hưởng, ...)",
        default=None,
    )
    interests: EntityText = Field(
        description="Chủ đề agent quan tâm",
        default=None,
    )


class Post(EntityModel):
    """Bài đăng trên Reddit do agent tạo."""
    content_summary: EntityText = Field(
        description="Tóm tắt nội dung post 1 câu",
        default=None,
    )
    post_type: EntityText = Field(
        description="Loại post (review, hỏi đáp, chia sẻ, quảng cáo, ...)",
        default=None,
    )


class Topic(EntityModel):
    """Chủ đề thảo luận extract từ content (vd 'Black Friday', 'TMĐT')."""
    category: EntityText = Field(
        description="Phân loại (khuyến mãi, sản phẩm, dịch vụ, xu hướng, ...)",
        default=None,
    )
    momentum: EntityText = Field(
        description="Đà phát triển (đang lên, ổn định, suy giảm)",
        default=None,
    )


class Sentiment(EntityModel):
    """Cảm xúc/thái độ thể hiện qua post."""
    polarity: EntityText = Field(
        description="positive | negative | neutral",
        default=None,
    )
    intensity: EntityText = Field(
        description="strong | moderate | weak",
        default=None,
    )


class Trend(EntityModel):
    """Xu hướng tổng hợp xuất hiện qua nhiều posts."""
    trajectory: EntityText = Field(
        description="Xu hướng tăng/giảm/ổn định",
        default=None,
    )


class Concern(EntityModel):
    """Vấn đề/quan ngại được agent nêu trong post."""
    severity: EntityText = Field(
        description="Mức độ (nhẹ, trung bình, nghiêm trọng)",
        default=None,
    )


# ──────────────────────────────────────────────
# Edge types — content-driven only
# Structural (LIKED, FOLLOWED, POSTED, COMMENTED_ON) sống ở oasis_simulation.db
# SQL — KG chỉ ghi ngữ nghĩa (Phase 13).
# ──────────────────────────────────────────────
class PostedAbout(EdgeModel):
    """Agent post nói về Topic/Company (high-level)."""
    sentiment: EntityText = Field(description="Cảm xúc kèm theo", default=None)


class Discusses(EdgeModel):
    """Post → Topic (chủ đề chính của post)."""
    depth: EntityText = Field(description="Mức độ thảo luận (sâu, lướt)", default=None)


class MentionsBrand(EdgeModel):
    """Post → Company (đề cập thương hiệu)."""
    sentiment_hint: EntityText = Field(
        description="Sắc thái (positive/negative/neutral)",
        default=None,
    )
    context: EntityText = Field(
        description="Bối cảnh (quảng cáo, review, so sánh, ...)",
        default=None,
    )


class Expresses(EdgeModel):
    """Post → Sentiment."""
    triggered_by: EntityText = Field(
        description="Nguyên nhân (giá, chất lượng, dịch vụ, ...)",
        default=None,
    )


class ReactsTo(EdgeModel):
    """Comment → Post (logical thread reply, distinct với structural COMMENTED_ON)."""
    reaction_type: EntityText = Field(
        description="Loại phản ứng (đồng tình, phản đối, hỏi thêm, ...)",
        default=None,
    )


class AgreesWith(EdgeModel):
    """Comment → Post (đồng tình rõ ràng)."""
    confidence: EntityText = Field(description="Mức độ đồng tình", default=None)


class DisagreesWith(EdgeModel):
    """Comment → Post (phản đối rõ ràng)."""
    confidence: EntityText = Field(description="Mức độ phản đối", default=None)


class Promotes(EdgeModel):
    """Post → Product/Campaign (ngôn ngữ quảng cáo/khuyến nghị)."""
    angle: EntityText = Field(
        description="Góc độ quảng bá (khuyến mãi, chất lượng, độc quyền, ...)",
        default=None,
    )


class Critiques(EdgeModel):
    """Post → Company/Product (đánh giá tiêu cực)."""
    issue: EntityText = Field(description="Vấn đề chính bị critique", default=None)
    severity: EntityText = Field(description="Mức độ nghiêm trọng", default=None)


class InfluencedBy(EdgeModel):
    """Agent chịu ảnh hưởng bởi Trend/Agent khác."""
    influence_strength: EntityText = Field(
        description="Mức độ ảnh hưởng",
        default=None,
    )


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _src_tgt(source: str, target: str) -> EntityEdgeSourceTarget:
    return EntityEdgeSourceTarget(source=source, target=target)


# ──────────────────────────────────────────────
# Registry — pass vào zep.graph.set_ontology
# ──────────────────────────────────────────────
SIM_ENTITY_TYPES: Dict[str, type] = {
    # Inherited (4)
    "Company": Company,
    "Product": Product,
    "Campaign": Campaign,
    "Market": Market,
    # Sim-specific (6)
    "Agent": Agent,
    "Post": Post,
    "Topic": Topic,
    "Sentiment": Sentiment,
    "Trend": Trend,
    "Concern": Concern,
}


SIM_EDGE_TYPES: Dict[str, Tuple[type, List[EntityEdgeSourceTarget]]] = {
    "POSTED_ABOUT": (
        PostedAbout,
        [
            _src_tgt("Agent", "Topic"),
            _src_tgt("Agent", "Company"),
            _src_tgt("Agent", "Product"),
        ],
    ),
    "DISCUSSES": (
        Discusses,
        [
            _src_tgt("Post", "Topic"),
            _src_tgt("Post", "Trend"),
        ],
    ),
    "MENTIONS_BRAND": (
        MentionsBrand,
        [_src_tgt("Post", "Company")],
    ),
    "EXPRESSES": (
        Expresses,
        [_src_tgt("Post", "Sentiment")],
    ),
    "REACTS_TO": (
        ReactsTo,
        [_src_tgt("Post", "Post")],
    ),
    "AGREES_WITH": (
        AgreesWith,
        [_src_tgt("Post", "Post")],
    ),
    "DISAGREES_WITH": (
        DisagreesWith,
        [_src_tgt("Post", "Post")],
    ),
    "PROMOTES": (
        Promotes,
        [
            _src_tgt("Post", "Product"),
            _src_tgt("Post", "Campaign"),
            _src_tgt("Post", "Company"),
        ],
    ),
    "CRITIQUES": (
        Critiques,
        [
            _src_tgt("Post", "Company"),
            _src_tgt("Post", "Product"),
        ],
    ),
    "INFLUENCED_BY": (
        InfluencedBy,
        [
            _src_tgt("Agent", "Trend"),
            _src_tgt("Agent", "Agent"),
        ],
    ),
}


async def apply_sim_ontology(zep_client, sim_graph_id: str) -> bool:
    """Push sim ontology lên Zep cho graph sim_<sid>.

    Returns True nếu set OK, False nếu fail (không raise — best effort,
    sim runtime vẫn chạy nếu ontology fail, chỉ mất quality extract).
    """
    try:
        await zep_client.graph.set_ontology(
            entities=SIM_ENTITY_TYPES,
            edges=SIM_EDGE_TYPES,
            graph_ids=[sim_graph_id],
        )
        logger.info(
            "Applied sim ontology to %s (%d entity types, %d edge types)",
            sim_graph_id,
            len(SIM_ENTITY_TYPES),
            len(SIM_EDGE_TYPES),
        )
        return True
    except Exception as e:
        logger.error("Failed to apply sim ontology to %s: %s", sim_graph_id, e)
        return False
