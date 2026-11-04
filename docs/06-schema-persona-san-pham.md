# 06 — Schema persona dùng cho sản phẩm

## Mục đích và phạm vi

`data/matraix/persona_1m/projectdut_persona.schema.json` là schema con được
chọn từ 1.290 trường của MatrAIx cho phiên bản hiện tại của projectDut2026.
Schema giữ nguyên `id`, `label`, `category` và `values` từ nguồn, đồng thời
thêm mô tả trung lập và metadata phục vụ lựa chọn context.

`description` chỉ mô tả phạm vi ngữ nghĩa của trường. `product_relevance` và
`selection_groups` mô tả lý do sản phẩm chọn trường đó; đây không phải là một
phần của định nghĩa nguồn. LLM đọc schema cần phân biệt hai lớp này.

`limitations` nêu giới hạn diễn giải. `description_provenance` ghi nhận mô tả
tiếng Anh là bản nháp của dự án dựa trên nhãn và enum, không phải định nghĩa
chính thức của MatrAIx. `values` chứa nguyên văn các giá trị hợp lệ; thứ tự
trong mảng không mặc nhiên là thang tăng/giảm.

`product_relevance` chỉ là metadata định hướng sơ bộ cho các flow của sản phẩm.
Đã có bộ tag bản nháp tại
[projectdut_cafe_tags.schema.json](../data/tags/projectdut_cafe_tags.schema.json)
và [mapping tag–persona](../data/tags/projectdut_cafe_tag_persona.mapping.json).
Mapping chỉ chọn trường ứng viên cho `article_thought` và `product_thought`;
chưa ánh xạ tag suy nghĩ/cảm xúc sang thay đổi persona. Trạng thái hiện tại là
`tag_mapping_status: draft_enterprise_content_tags`.

Ví dụ: `trait_curiosity` mô tả mức tò mò của persona, không mô tả xác suất mua
sản phẩm mới. `att_brand_loyalty` mô tả thái độ với khái niệm trung thành
thương hiệu, không phải mức yêu thích một thương hiệu cụ thể.

Đây là **context persona tĩnh**, không phải toàn bộ trạng thái agent. Các dữ liệu
không thuộc schema này gồm:

- quan hệ với thương hiệu và thái độ với thương hiệu;
- lịch sử đọc bài, tag suy nghĩ/cảm xúc và hành động;
- lịch sử xem sản phẩm, `buy`/`not_buy`;
- trạng thái thuật toán chú ý và các thay đổi phát sinh trong mô phỏng.

Giá trị bị thiếu vẫn là thiếu. Không tự đổi thiếu thành `Neutral`, `None` hoặc
giá trị trung bình.

## Các nhóm trường đã chọn

### 1. Hoạt động và khả năng tiếp xúc — 12 trường

`age_bracket`, `region`, `urbanicity`, `socioeconomic_band`, `life_stage`,
`lstyle_screen_time`, `lstyle_social_battery`, `lstyle_primary_social`,
`big5_activity_level`, `lstyle_work_schedule`, `lstyle_sleep_schedule`,
`cog_attention_span`.

Vai trò trong sản phẩm: `agent_activation`, `content_exposure`.

### 2. Tính cách và nhận thức — 21 trường

`trait_curiosity`, `trait_open_mindedness`, `trait_prudence`,
`trait_self_regulation`, `trait_adaptability`, `big5_cautiousness`,
`big5_trust`, `big5_excitement_seeking`, `bfi2_facet_sociability`,
`bfi2_facet_assertiveness`, `bfi2_facet_intellectual_curiosity`,
`bfi2_facet_anxiety`, `bfi2_facet_emotional_volatility`, `risk_tolerance`,
`decision_style`, `cog_skepticism`, `cog_ambiguity_tolerance`,
`cog_decision_speed`, `cog_detail_orientation`, `need_for_cognition`,
`need_for_closure`.

Vai trò trong sản phẩm: `article_thought`, `article_emotion`,
`product_thought`. Các trường này không phải luật hành động; quan hệ giữa giá
trị persona và tag/action được xác định ở flow và contract tương ứng.

### 3. Mua hàng và sở thích — 18 trường

`economic_motivation`, `lstyle_shopping_style`, `lstyle_frugality`,
`pref_quality_vs_quantity`, `pref_save_vs_spend`,
`pref_novelty_vs_familiarity`, `pref_routine_vs_variety`,
`pref_stability_vs_change`, `pref_plan_vs_spontaneous`,
`pref_early_vs_late`, `att_brand_loyalty`, `att_advertising`,
`att_online_reviews`, `att_influencers`, `att_consumerism`,
`schwartz_value_stimulation`, `schwartz_value_security`,
`schwartz_value_hedonism`.

Vai trò trong sản phẩm: `product_thought`, `product_emotion`,
`purchase_decision`, `attention`. Lịch sử tag/action và policy chú ý là dữ
liệu riêng.

### 4. Phản ứng xã hội và comment — 11 trường

`cog_directness`, `cog_politeness`, `cog_conflict_approach`,
`cog_storytelling`, `cog_verbosity`, `cog_precision_of_language`,
`cog_emoji_use`, `cog_emotional_expressiveness`, `cog_empathy_expression`,
`att_advertising`, `att_online_reviews`.

Vai trò trong sản phẩm: `article_reaction`. Comment chưa thuộc phạm vi bản đầu.

### 5. Ngữ cảnh cafe — 10 trường

`topic_coffee`, `lstyle_coffee_ritual`, `lstyle_caffeine`, `topic_tea`,
`topic_cooking`, `topic_baking`, `skill_cooking`, `skill_baking`,
`ind_food_beverage`, `ind_restaurants`.

Vai trò trong sản phẩm: `content_matching`, `article_thought`,
`product_thought`, `attention`. Việc thiếu giá trị được giữ nguyên và
không tự động suy ra một giá trị khác.

## Cách đưa vào từng flow

| Flow | Context persona ưu tiên |
| --- | --- |
| Chọn agent hoạt động | Hoạt động và khả năng tiếp xúc |
| Xếp hạng bài cần chú ý | Hoạt động + tính cách/nhận thức + trường liên quan tag bài |
| Suy nghĩ trước khi đọc bài | Trường liên quan tag bài, tối đa tập được chọn |
| Cảm xúc sau khi đọc | Tag suy nghĩ + nội dung bài; không nhồi toàn bộ persona |
| Phản ứng | Tag cảm xúc và trạng thái phản ứng cần thiết |
| Xếp hạng sản phẩm | Mua hàng/sở thích + lịch sử riêng của agent |
| Suy nghĩ khi xem sản phẩm | Trường liên quan tag sản phẩm |
| Quyết định mua | Tag cảm xúc sau khi xem + context sản phẩm cần thiết |

Schema này là tập trường ứng viên. Một flow có thể chọn tập con phù hợp thay
vì đưa toàn bộ 70 trường vào prompt. Cách chọn tập con và contract của từng
flow là phần thiết kế tiếp theo, không thay đổi nghĩa trung lập của trường.

## Những trường cố ý chưa đưa vào

Các trường trùng construct như `cog_curiosity`, `bfi2_domain_open_mindedness`,
`dominant_trait` và `mbti_type` chưa đưa vào context mặc định để tránh truyền
nhiều cách đo cùng một đặc điểm. Các trường chính trị, tôn giáo, sức khỏe,
xu hướng tính dục, ethnicity và nhóm developer cũng chưa đưa vào vì không cần
cho mô phỏng cafe hiện tại hoặc cần ngữ cảnh sản phẩm đặc biệt.

Việc chưa chọn không có nghĩa những trường đó vô dụng; chúng có thể được thêm
ở schema ngành hoặc flow riêng khi có lý do nghiệp vụ rõ ràng.

## Kiểm tra và tái tạo

```bash
python3 paper_research/build_product_persona_schema.py
python3 paper_research/build_product_persona_schema.py --check
```

Kết quả hiện tại: **70 trường**, định dạng phiên bản 2. Kiểm tra đối chiếu chính
xác ID, nhãn, category và enum với nguồn, cùng mô tả và các nhóm sử dụng.
