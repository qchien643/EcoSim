"""
EcoSim canonical ontology cho Zep Cloud `set_ontology` API.

Zep dùng ontology định nghĩa entity_types + edge_types để extraction LLM
tuân theo schema này — output có labels (vd `["Entity", "Company"]`) và
attributes dict được populate đúng field names.

Không có ontology → Zep extract về labels=[] + attributes={"name": ...} only,
mất hết rich info (đó là vấn đề lần build trước).

Các canonical types align với:
- `apps/simulation/campaign_knowledge.py` CANONICAL_ENTITY_TYPES (14 types)
- `apps/simulation/campaign_knowledge.py` CANONICAL_EDGE_TYPES (12 types)

Field choices: chọn fields HAY GẶP trong tài liệu chiến dịch tiếng Việt để
LLM có hint tốt — vd Company.founded_year, Consumer.age_range, Product.category.
Tất cả fields default=None nên LLM tùy ý populate.
"""
from __future__ import annotations

import logging
from typing import Dict, Tuple, List

from zep_cloud.external_clients.ontology import (
    EntityModel,
    EdgeModel,
    EntityText,
    EntityInt,
    Field,
)
from zep_cloud.types.entity_edge_source_target import EntityEdgeSourceTarget

logger = logging.getLogger("sim-svc.zep_ontology")


# ──────────────────────────────────────────────────────────────────
# Entity types — 14 canonical
# ──────────────────────────────────────────────────────────────────
class Company(EntityModel):
    """Doanh nghiệp/công ty/thương hiệu/nền tảng (Shopee, Lazada, Tiki)."""
    industry: EntityText = Field(description="Ngành (TMĐT, Bán lẻ, FinTech, ...)", default=None)
    founded_year: EntityInt = Field(description="Năm thành lập", default=None)
    hq_location: EntityText = Field(description="Trụ sở chính (thành phố/quốc gia)", default=None)
    business_model: EntityText = Field(description="Mô hình kinh doanh (B2C, B2B, marketplace, ...)", default=None)
    scale: EntityText = Field(description="Quy mô (startup, SME, large enterprise, ...)", default=None)
    ceo: EntityText = Field(description="CEO/founder", default=None)


class Consumer(EntityModel):
    """Phân khúc khách hàng/người tiêu dùng/audience."""
    demographic: EntityText = Field(description="Nhóm nhân khẩu học (Gen Z, millennials, ...)", default=None)
    age_range: EntityText = Field(description="Độ tuổi (18-25, 25-34, ...)", default=None)
    location: EntityText = Field(description="Khu vực địa lý chính", default=None)
    income_level: EntityText = Field(description="Thu nhập (low, middle, high, ...)", default=None)
    segment: EntityText = Field(description="Phân khúc tiêu dùng (giá rẻ, cao cấp, eco-friendly)", default=None)


class Investor(EntityModel):
    """Nhà đầu tư/quỹ đầu tư mạo hiểm."""
    investor_type: EntityText = Field(description="Loại (VC, PE, angel, sovereign fund)", default=None)
    aum: EntityText = Field(description="Asset under management nếu có", default=None)
    location: EntityText = Field(description="Trụ sở", default=None)


class Regulator(EntityModel):
    """Cơ quan quản lý nhà nước/chính phủ."""
    jurisdiction: EntityText = Field(description="Khu vực quản lý (VN, ASEAN, ...)", default=None)
    authority_level: EntityText = Field(description="Cấp (TW, tỉnh/thành, bộ ngành)", default=None)
    domain: EntityText = Field(description="Lĩnh vực quản lý", default=None)


class Competitor(EntityModel):
    """Đối thủ cạnh tranh trực tiếp."""
    competitor_of: EntityText = Field(description="Là đối thủ của ai", default=None)
    market_share: EntityText = Field(description="Thị phần ước tính", default=None)


class Supplier(EntityModel):
    """Nhà cung cấp/đối tác cung ứng."""
    supplies: EntityText = Field(description="Loại hàng hóa/dịch vụ cung cấp", default=None)
    location: EntityText = Field(description="Khu vực cung ứng", default=None)


class MediaOutlet(EntityModel):
    """Kênh truyền thông/báo chí/influencer/KOL."""
    medium_type: EntityText = Field(description="Loại (báo, TV, social, KOL/influencer)", default=None)
    audience_size: EntityText = Field(description="Số lượng follower/độc giả", default=None)
    primary_topic: EntityText = Field(description="Chủ đề chính", default=None)


class EconomicIndicator(EntityModel):
    """Chỉ số kinh tế/KPI/metric."""
    metric_unit: EntityText = Field(description="Đơn vị đo (%, VNĐ, USD, lượng)", default=None)
    value: EntityText = Field(description="Giá trị nếu nêu trong văn bản", default=None)
    period: EntityText = Field(description="Kỳ tham chiếu", default=None)


class Product(EntityModel):
    """Sản phẩm/dịch vụ/feature/voucher."""
    category: EntityText = Field(description="Danh mục (điện tử, thời trang, ...)", default=None)
    price_range: EntityText = Field(description="Khoảng giá", default=None)
    brand: EntityText = Field(description="Thương hiệu sở hữu", default=None)
    feature_summary: EntityText = Field(description="Đặc điểm nổi bật", default=None)


class Market(EntityModel):
    """Thị trường/khu vực địa lý/phân khúc thị trường."""
    region: EntityText = Field(description="Vùng (Bắc/Trung/Nam, ASEAN, global)", default=None)
    market_size: EntityText = Field(description="Quy mô thị trường", default=None)
    growth_rate: EntityText = Field(description="Tốc độ tăng trưởng", default=None)


class Person(EntityModel):
    """Cá nhân (CEO, KOL, expert, customer testimonial)."""
    role: EntityText = Field(description="Vai trò/chức danh", default=None)
    affiliation: EntityText = Field(description="Tổ chức/công ty thuộc về", default=None)
    expertise: EntityText = Field(description="Chuyên môn", default=None)


class Organization(EntityModel):
    """Tổ chức (NGO, hiệp hội, club, ...) — không phải doanh nghiệp."""
    org_type: EntityText = Field(description="Loại (NGO, association, ...)", default=None)
    purpose: EntityText = Field(description="Mục đích hoạt động", default=None)


class Campaign(EntityModel):
    """Chiến dịch marketing/PR/khuyến mãi/sự kiện."""
    campaign_type: EntityText = Field(description="Loại (brand, product launch, sale event)", default=None)
    start_date: EntityText = Field(description="Ngày bắt đầu", default=None)
    end_date: EntityText = Field(description="Ngày kết thúc", default=None)
    budget: EntityText = Field(description="Ngân sách", default=None)
    objective: EntityText = Field(description="Mục tiêu chính", default=None)
    target_audience: EntityText = Field(description="Đối tượng mục tiêu", default=None)


class Policy(EntityModel):
    """Chính sách/quy định/luật."""
    policy_type: EntityText = Field(description="Loại (luật, nghị định, thông tư, quy chế)", default=None)
    effective_date: EntityText = Field(description="Ngày hiệu lực", default=None)
    issuer: EntityText = Field(description="Cơ quan ban hành", default=None)
    impact_area: EntityText = Field(description="Lĩnh vực bị ảnh hưởng", default=None)


# ──────────────────────────────────────────────────────────────────
# Edge types — 12 canonical với fact extraction
# ──────────────────────────────────────────────────────────────────
class InvestsIn(EdgeModel):
    """Đầu tư vào (Investor → Company hoặc Company → Company)."""
    amount: EntityText = Field(description="Số tiền đầu tư nếu có", default=None)
    round_stage: EntityText = Field(description="Vòng (seed, series A, ...)", default=None)
    date: EntityText = Field(description="Thời điểm", default=None)


class CompetesWith(EdgeModel):
    """Cạnh tranh trực tiếp."""
    market_segment: EntityText = Field(description="Phân khúc cạnh tranh", default=None)
    intensity: EntityText = Field(description="Mức độ (gay gắt, vừa, nhẹ)", default=None)


class SuppliesTo(EdgeModel):
    """Cung cấp cho (Supplier → Company)."""
    supplied_items: EntityText = Field(description="Hàng hóa cung cấp", default=None)


class Regulates(EdgeModel):
    """Quản lý/áp đặt quy định lên."""
    regulatory_area: EntityText = Field(description="Lĩnh vực quy định", default=None)


class Consumes(EdgeModel):
    """Tiêu dùng/sử dụng (Consumer → Product/Company)."""
    frequency: EntityText = Field(description="Tần suất sử dụng", default=None)


class ReportsOn(EdgeModel):
    """Đưa tin về (MediaOutlet → Company/Campaign/Event)."""
    sentiment: EntityText = Field(description="Sắc thái (tích cực/tiêu cực/trung lập)", default=None)
    reach: EntityText = Field(description="Phạm vi lan tỏa", default=None)


class PartnersWith(EdgeModel):
    """Hợp tác/đối tác."""
    partnership_type: EntityText = Field(description="Loại (chiến lược, vận hành, marketing)", default=None)


class Affects(EdgeModel):
    """Tác động đến (general influence)."""
    impact: EntityText = Field(description="Mô tả tác động", default=None)
    direction: EntityText = Field(description="Tích cực/tiêu cực", default=None)


class Runs(EdgeModel):
    """Vận hành/triển khai (Company → Campaign)."""
    role: EntityText = Field(description="Vai trò trong chiến dịch", default=None)


class Targets(EdgeModel):
    """Nhắm tới (Campaign/Product → Consumer/Market)."""
    target_specifics: EntityText = Field(description="Đặc thù đối tượng nhắm", default=None)


class Produces(EdgeModel):
    """Sản xuất/cung cấp (Company → Product)."""
    production_scale: EntityText = Field(description="Quy mô sản xuất", default=None)


class Employs(EdgeModel):
    """Tuyển dụng (Company → Person)."""
    position: EntityText = Field(description="Vị trí/chức danh", default=None)


# ──────────────────────────────────────────────────────────────────
# Registry maps cho Zep set_ontology call
# ──────────────────────────────────────────────────────────────────
# NOTE: Zep limit max 10 entity types + 10 edge types per project.
# Đã ưu tiên các types liên quan nhất cho marketing/campaign domain.
# Các types loại bỏ (Investor, Regulator, Supplier, Organization) sẽ
# fallback về :Entity ở FalkorDB — vẫn extract được nhưng không có canonical.
ECOSIM_ENTITY_TYPES: Dict[str, type] = {
    "Company": Company,
    "Consumer": Consumer,
    "Product": Product,
    "Campaign": Campaign,
    "Person": Person,
    "Market": Market,
    "MediaOutlet": MediaOutlet,
    "Competitor": Competitor,
    "EconomicIndicator": EconomicIndicator,
    "Policy": Policy,
}


def _src_tgt(src: str, tgt: str) -> EntityEdgeSourceTarget:
    return EntityEdgeSourceTarget(source=src, target=tgt)


# Edge mapping với (EdgeModel, [allowed source-target pairs]) — Zep dùng pairs
# để hint cho LLM khi nào dùng edge type này. Để rộng nhất → ít hint nhưng
# cao recall.
ECOSIM_EDGE_TYPES: Dict[str, Tuple[type, List[EntityEdgeSourceTarget]]] = {
    "COMPETES_WITH": (
        CompetesWith,
        [
            _src_tgt("Company", "Company"),
            _src_tgt("Company", "Competitor"),
            _src_tgt("Competitor", "Company"),
        ],
    ),
    "SUPPLIES_TO": (
        SuppliesTo,
        [_src_tgt("Company", "Company")],
    ),
    "CONSUMES": (
        Consumes,
        [
            _src_tgt("Consumer", "Product"),
            _src_tgt("Consumer", "Company"),
        ],
    ),
    "REPORTS_ON": (
        ReportsOn,
        [
            _src_tgt("MediaOutlet", "Company"),
            _src_tgt("MediaOutlet", "Campaign"),
            _src_tgt("MediaOutlet", "Person"),
        ],
    ),
    "PARTNERS_WITH": (
        PartnersWith,
        [
            _src_tgt("Company", "Company"),
            _src_tgt("Company", "Organization"),
        ],
    ),
    "AFFECTS": (
        Affects,
        [
            _src_tgt("EconomicIndicator", "Company"),
            _src_tgt("Policy", "Company"),
            _src_tgt("Campaign", "Consumer"),
        ],
    ),
    "RUNS": (
        Runs,
        [_src_tgt("Company", "Campaign")],
    ),
    "TARGETS": (
        Targets,
        [
            _src_tgt("Campaign", "Consumer"),
            _src_tgt("Campaign", "Market"),
            _src_tgt("Product", "Consumer"),
        ],
    ),
    "PRODUCES": (
        Produces,
        [_src_tgt("Company", "Product")],
    ),
    "EMPLOYS": (
        Employs,
        [_src_tgt("Company", "Person")],
    ),
}


async def apply_ontology(zep_client, graph_id: str) -> bool:
    """Push EcoSim ontology lên Zep cho specific graph.

    Returns True nếu set OK, False nếu fail (không raise — best effort,
    fallback vẫn extract được nodes nhưng không có canonical types).
    """
    try:
        await zep_client.graph.set_ontology(
            entities=ECOSIM_ENTITY_TYPES,
            edges=ECOSIM_EDGE_TYPES,
            graph_ids=[graph_id],
        )
        logger.info(
            "Applied ontology to graph %s (%d entity types, %d edge types)",
            graph_id, len(ECOSIM_ENTITY_TYPES), len(ECOSIM_EDGE_TYPES),
        )
        return True
    except Exception as e:
        logger.error(
            "Failed to apply ontology to graph %s: %s — Zep sẽ extract với "
            "default ontology (rich attrs sẽ thiếu)", graph_id, e,
        )
        return False
