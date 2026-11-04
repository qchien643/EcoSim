# Mapping tag–persona cho flow agent

**Trạng thái:** bản nháp để review  
**Bộ tag:** [agent_flow_tags.v2.json](../../data/tags/agent_flow_tags.v2.json)  
**Mapping:** [agent_flow_tag_persona.mapping.v2.json](../../data/tags/agent_flow_tag_persona.mapping.v2.json)  
**Persona schema:** `data/matraix/persona_1m/projectdut_persona.schema.json`

## 1. Mapping này dùng để làm gì?

Mapping chọn các trường persona cần đưa vào context của từng stage khi agent
gặp tag doanh nghiệp, bài viết hoặc sản phẩm. Nó không phải công thức tính
điểm, không quyết định `attend`, `skip`, `buy` hay `not_buy`, và không cập
nhật giá trị persona.

Ví dụ: `article.product_introduction` có thể kích hoạt
`trait_curiosity` và `pref_novelty_vs_familiarity`. Điều đó chỉ có nghĩa
hai trường này đáng được cung cấp cho model trong context; model vẫn phải
đánh giá phản ứng dựa trên toàn bộ context được phép.

## 2. Phân biệt ba loại dữ liệu

| Loại | Ví dụ | Vai trò |
| --- | --- | --- |
| Tag mô tả đầu vào | `enterprise.value_positioning` | Mô tả thông tin công khai của object |
| Trường persona | `economic_motivation: "Cost-sensitive"` | Mô tả xu hướng của agent |
| Tag trạng thái | `emotion.interest`, `thought.price_barrier` | Kết quả của một bước xử lý |

Chỉ tag mô tả đầu vào kích hoạt mapping persona. Emotion, thought và
attention-reason tag được lưu theo stage; không dùng chúng để suy ngược hoặc
thay đổi tính cách agent.

## 3. Cách dựng context

```text
Đọc stage hiện tại
  ↓
Chọn base fields của stage
  ↓
Đọc các tag mô tả đầu vào đang được phép hiển thị
  ↓
Lấy fields từ rule của từng tag
  ↓
Loại trùng, giữ thứ tự deterministic
  ↓
Bỏ field thiếu/null
  ↓
Tạo persona_context tối thiểu cho contract
```

Các giá trị enum được giữ nguyên nhãn từ persona schema, ví dụ
`trait_curiosity: "Strong"`. Không đổi nhãn thành số và không tự coi thứ tự
enum là quan hệ nhân quả.

## 4. Base fields theo stage

| Stage | Trường nền được phép dùng |
| --- | --- |
| A1 | `att_advertising`, `cog_attention_span`, `trait_curiosity`, `pref_novelty_vs_familiarity` |
| A1R | Tái sử dụng context persona của A1 |
| A2 | `att_advertising`, `trait_curiosity`, `pref_novelty_vs_familiarity` |
| A3/A4/A5 | Không thêm persona field mới |
| B1 | `cog_attention_span`, `trait_curiosity`, `pref_novelty_vs_familiarity` |
| B1R | Tái sử dụng context persona của B1 |
| B2 | `decision_style`, `economic_motivation`, `pref_quality_vs_quantity`, `pref_novelty_vs_familiarity` |
| B3 | Không thêm persona field mới |

“Không thêm field mới” không có nghĩa context mất persona; các bước này dùng
kết quả hiện tại của bước trước, thông tin object được phép và history theo
contract.

## 5. Một số mapping tiêu biểu

| Tag | Field được chọn | Giới hạn diễn giải |
| --- | --- | --- |
| `enterprise.value_positioning` | `economic_motivation` | Không suy ra giá, ngân sách hoặc khả năng chi trả |
| `enterprise.craft_focus` | `pref_quality_vs_quantity`, `cog_skepticism` | Không xác nhận doanh nghiệp thật sự có tay nghề |
| `article.product_introduction` | `trait_curiosity`, `pref_novelty_vs_familiarity` | Không khẳng định agent thấy sản phẩm mới |
| `article.offer` | `economic_motivation`, `lstyle_shopping_style` | Không tự kết luận đây là món hời |
| `product.coffee_drink` | `topic_coffee`, `lstyle_coffee_ritual`, `lstyle_caffeine` | Không suy ra vị, liều caffeine hoặc nhu cầu hiện tại |
| `product.decaffeinated` | `lstyle_caffeine` | Không suy ra lý do y tế hoặc caffeine bằng không |

## 6. Các tag hiện chưa có field persona phù hợp

Schema persona hiện tại không có field trực tiếp cho:

- vị ngọt, đắng, trái cây;
- nhiệt độ nóng/lạnh;
- dairy hoặc reduced-sugar preference;
- ưu tiên doanh nghiệp địa phương/multi-location;
- khả năng tiếp nhận hài hước hoặc narrative advertisement.

Các tag này vẫn được giữ làm mô tả object. Mapping để trống là chủ ý, không
phải lỗi và không được thay bằng một field gần nghĩa nhưng không đủ bằng chứng.

## 7. Kiểm tra

```bash
python3 paper_research/validate_flow_tag_persona_mapping_v2.py
```

Validator kiểm tra phiên bản registry/schema, coverage của toàn bộ tag mô tả
đầu vào, field persona tồn tại, stage policy, và việc loại state tag khỏi
mapping. Nó không chứng minh mapping đã mô phỏng đúng hành vi con người; cần
calibration sau khi có prompt và kết quả JEV/LLM.

## 8. Chưa làm

- Xếp hạng field theo token budget.
- Trọng số causal giữa field và tag.
- Mapping emotion/thought sang cập nhật persona.
- Tự động thay đổi persona sau một event.
- JSON Schema riêng cho `persona_context` đã render.

