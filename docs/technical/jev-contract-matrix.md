# Ma trận contract cho JEV và LLM fallback

**Trạng thái:** contract dùng policy v1 đã chấp thuận để triển khai thử  
**Nguồn policy:** [FRD-05](../frd/05-session-policy-and-state.md)
**Phạm vi:** contract nghiệp vụ cho luồng agent hiện tại; chưa phải JSON
Schema triển khai.

Policy chi tiết cho việc chuyển score, lưu trạng thái chú ý và xử lý output
rỗng nằm tại [attention-state-policy.md](attention-state-policy.md).

JSON Schema contract nội bộ nằm tại
[agent_model_output.schema.json](../../data/contracts/agent_model_output.schema.json).
Validator và fixture kiểm thử nằm tại
[validate_contract_schemas.py](../../paper_research/validate_contract_schemas.py).

Mapping persona hiện tại: [hướng dẫn mapping v2](agent-flow-tag-persona-mapping-v2.md).
Chỉ A1/A2/B1/B2 chọn persona field; A1R/B1R tái sử dụng snapshot của bước
chú ý vừa chạy. A3/A4/A5/B3 không truyền thêm persona field.

Prompt độc lập được dựng theo
[context-rendering-v2.md](context-rendering-v2.md), không gửi trực tiếp các
ID nội bộ trong mapping hoặc tag registry cho model.

## 1. Mục đích

Contract xác định chính xác một lời gọi model cần nhận gì và được trả gì.
`stage` xác định loại xử lý; `contract_variant` được dựng deterministic từ
context hiện tại và lịch sử của đúng agent–đối tượng–bước.

JEV và LLM fallback phải nhận cùng context, cùng danh sách tag/đáp án và cùng
ý nghĩa điểm. Model không được tự thêm đáp án, tag hoặc bước xử lý.

## 2. Quy tắc chung

Mỗi request phải có:

```json
{
  "stage": "A1",
  "contract_variant": "first_encounter",
  "flow_context": {},
  "persona_context": {},
  "object_context": {},
  "previous_same_stage_state": null
}
```

- `previous_same_stage_state` là trạng thái gần nhất của cùng
  `run_id + agent_id + object_id + stage`.
- Kết quả bước trước trong lượt hiện tại truyền ở trường riêng, không ghi
  đè lên trạng thái cùng bước của lần trước.
- Chỉ truyền các trường persona đã được mapping.
- Không đưa nội dung đầy đủ bài viết vào A1; chỉ đưa nội dung được phép hiển
  thị trước khi đọc.
- `n` của “lần thứ n” do hệ thống tính từ event hợp lệ, không gửi thành một
  đáp án riêng.

## 3. Ma trận tổng quát

| Stage | Xử lý | Loại output | Biến thể chính |
| --- | --- | --- | --- |
| A1 | Chú ý bài viết | `score` → action | `first_encounter`, `repeat_encounter` |
| A1R | Lý do bỏ qua bài | `tag_scores` | `skip_reason` |
| A2 | Cảm xúc ban đầu | `tag_scores` | `first_attention`, `repeat_attention` |
| A3 | Cảm xúc sau khi đọc | `tag_scores` | `first_read`, `repeat_read` |
| A4 | Phản ứng bài viết | `choice` | `first_reaction`, `existing_reaction` |
| A5 | Ghé shop | `choice` | `first_visit`, `repeat_visit` |
| B1 | Chú ý sản phẩm | `score` → action | `first_product_encounter`, `repeat_product_encounter` |
| B1R | Lý do bỏ qua sản phẩm | `tag_scores` | `skip_reason` |
| B2 | Suy nghĩ về sản phẩm | `tag_scores` | `first_consideration`, `repeat_consideration` |
| B3 | Mua hàng | `choice` | `first_purchase`, `repeat_purchase` |

`score` là điểm model đánh giá. Hệ thống chuẩn hóa về `[0,1]`, sau đó áp
dụng threshold policy để tạo action. Bản policy hiện tại dùng `>= 0.60` là
`attend` và `< 0.60` là `skip`. `tag_scores` là điểm riêng cho từng tag; các
điểm không cần cộng thành một.

## 4. Contract từng bước

### A1 — Chú ý bài viết

**Context được phép:** flow đang lướt mạng xã hội; persona liên quan; tag
doanh nghiệp và tag bài viết đang hiển thị; lịch sử cùng bài và trạng thái
gần nhất của A1. Không đưa nội dung đầy đủ bài viết.

| Variant | Ý nghĩa điểm | Action sau policy |
| --- | --- | --- |
| `first_encounter` | Mức sẵn sàng chú ý bài lần đầu | `attend` hoặc `skip` |
| `repeat_encounter` | Mức sẵn sàng chú ý lại bài | `attend_again` hoặc `skip` |

Nếu `attend`/`attend_again`, tạo event chú ý và chuyển A2. Nếu `skip`, lưu
event bỏ qua, sau đó gọi A1R để lấy lý do. A1 không sinh emotion tag.

### A1R — Lý do không chú ý bài viết

Chỉ gọi sau khi A1 đã có action `skip`. Model chấm các tag thuộc family
`attention_reason` trong registry, dùng context A1 cộng với action `skip` và
trạng thái gần nhất được phép dùng. Output được chuẩn hóa, giữ tối đa 3 tag
đạt score floor `0.50` theo policy v1. A1R không thay đổi action `skip`.

### A2 — Cảm xúc ban đầu

**Context được phép:** flow đã chú ý nhưng chưa đọc; persona liên quan; tag
doanh nghiệp/bài viết được phép thấy; trạng thái A2 gần nhất.

Model chấm các tag `emotion` được phép ở A2. Output chuẩn hóa:

```json
{
  "selected_tags": [
    {
      "tag_id": "emotion.interest",
      "score": 0.72,
      "description": "The agent feels drawn to finding out more about the object."
    }
  ]
}
```

`first_attention` dùng khi chưa có A2 trước đó; `repeat_attention` dùng khi
đã có. Nếu không có tag hợp lệ sau cả hai model, ghi trạng thái rỗng theo
quy tắc flow và dừng trước A3.

### A3 — Cảm xúc sau khi đọc

**Context được phép:** flow đang đọc; nội dung đầy đủ bài viết; tag doanh
nghiệp/bài viết; emotion tags hiện tại từ A2; trạng thái A3 gần nhất.

Model chấm cùng registry `emotion`, nhưng đây là trạng thái riêng với A2.
Không dùng A2 để thay thế A3 nếu A3 rỗng.

| Variant | Điều kiện |
| --- | --- |
| `first_read` | Chưa có trạng thái A3 trước đó |
| `repeat_read` | Đã từng đọc bài và có trạng thái A3 trước đó |

Có tag hợp lệ thì chuyển A4. Không có tag hợp lệ thì giữ event đọc nhưng
không gọi A4/A5. Trạng thái model không xác định được là `unresolved`,
không phải `no_reaction`.

### A4 — Phản ứng bài viết

**Context được phép:** flow vừa đọc xong; emotion tags A3 hiện tại; brand
được phép biết; phản ứng hiện tại và lịch sử phản ứng của đúng bài.

| Variant | Đáp án |
| --- | --- |
| `first_reaction` | `like`, `dislike`, `no_reaction` |
| `existing_reaction` | `keep_current`, `remove_reaction`, `no_new_reaction` |

`keep_current` giữ nguyên phản ứng hiện tại. `remove_reaction` xóa phản ứng.
`no_new_reaction` không thay đổi phản ứng hiện tại. Comment không thuộc
contract này.

### A5 — Ghé shop

**Context được phép:** flow vừa đọc bài; emotion tags A3; tag doanh nghiệp;
shop/brand agent biết; lịch sử ghé của đúng shop.

| Variant | Đáp án |
| --- | --- |
| `first_visit` | `visit`, `not_visit` |
| `repeat_visit` | `visit_again`, `not_visit_again` |

`not_visit_again` chỉ có nghĩa không ghé trong lượt hiện tại, không phải cấm
vĩnh viễn. Nếu chọn ghé, lưu event trước khi bắt đầu B1.

### B1 — Chú ý sản phẩm

**Context được phép:** flow đang ở shop; persona liên quan; tag doanh nghiệp
và sản phẩm; tên, giá và phần giới thiệu được phép thấy; lịch sử đúng sản
phẩm; trạng thái gần nhất của B1.

JEV được gọi cho từng sản phẩm hợp lệ. Không có tầng lọc trước bằng thuật
toán khác.

| Variant | Ý nghĩa điểm | Action sau policy |
| --- | --- | --- |
| `first_product_encounter` | Mức sẵn sàng chú ý sản phẩm lần đầu | `attend` hoặc `skip` |
| `repeat_product_encounter` | Mức sẵn sàng chú ý lại sản phẩm | `attend_again` hoặc `skip` |

Lịch sử đã mua và tag `thought.consider_later` có thể ảnh hưởng B1 thông qua
policy deterministic đã chốt sau. Không tự coi `not_buy` là tăng chú ý nếu
policy chưa quy định điều đó.

### B1R — Lý do không chú ý sản phẩm

Chỉ gọi sau khi B1 đã có action `skip`. Model chấm các tag thuộc family
`attention_reason` trong registry, dùng context B1 cộng với action `skip` và
trạng thái gần nhất được phép dùng. Output được chuẩn hóa, giữ tối đa 3 tag
đạt score floor `0.50` theo policy v1. B1R không tạo `not_buy` và không thay
đổi action `skip`.

### B2 — Suy nghĩ về sản phẩm

**Context được phép:** flow đã chú ý sản phẩm; tag doanh nghiệp/sản phẩm;
giá và điều kiện mua; persona liên quan; trạng thái B2 gần nhất.

Model chấm các tag `thought` được phép ở B2, chẳng hạn:
`thought.personal_fit`, `thought.want_to_try`, `thought.price_barrier`,
`thought.consider_later` và `thought.information_gap`.

| Variant | Điều kiện |
| --- | --- |
| `first_consideration` | Chưa có trạng thái B2 trước đó |
| `repeat_consideration` | Đã có trạng thái B2 trước đó |

Không sinh suy nghĩ sau khi biết kết quả mua. Nếu không có tag hợp lệ, không
gọi B3 và không đổi trạng thái đó thành `not_buy`.

### B3 — Mua hàng

**Context được phép:** flow vừa nêu suy nghĩ; thought tags B2 hiện tại; thông
tin sản phẩm, giá và điều kiện mua; lịch sử mua/không mua của đúng sản phẩm.

| Variant | Đáp án |
| --- | --- |
| `first_purchase` | `buy`, `not_buy` |
| `repeat_purchase` | `buy_again`, `not_buy_again` |

`buy_again` và `not_buy_again` là các đáp án khác nhau do context lịch sử,
không phải hậu tố do hệ thống thêm vào sau khi model trả lời. Hệ thống vẫn
tự đếm số lần mua từ event hợp lệ. Cả `buy` và `not_buy` đều phải được lưu.

## 5. Quy trình xử lý request

```text
Đọc snapshot lịch sử
  ↓
Chọn contract_variant
  ↓
Mapping persona + object tags theo stage
  ↓
Tạo context và danh sách đáp án/tag được phép
  ↓
Gọi JEV
  ↓
Validate → chuẩn hóa [0,1] → áp dụng score floor/top-K hoặc choice policy
  ↓
Nếu không hợp lệ: gọi LLM fallback với cùng contract
  ↓
Lưu raw output, normalized output, variant, event và state mới
  ↓
Chuyển bước hoặc kết thúc nhánh
```

## 6. Dữ liệu phải lưu

Mỗi lần gọi cần lưu tối thiểu:

- `stage`, `contract_variant`, `run_id`, `agent_id`, `object_id`;
- các cờ lịch sử dùng để chọn variant;
- context đã gửi và danh sách tag/đáp án đã gửi;
- model, raw output, lỗi validate và nguồn kết quả (`jev` hoặc `llm_fallback`);
- điểm gốc, điểm chuẩn hóa, policy version và kết quả action;
- event/state mới được tạo.

Không lưu “lần thứ n” như một đáp án model. Đây là dữ liệu suy ra từ event.

## 7. Policy v1 và phần tích hợp còn lại

Attention `>= 0.60` là `attend`; emotion/thought floor=`0.30`;
attention-reason floor=`0.50`; `top_k=3`. Giữ cả score và action A1/B1.
Hai lượt chấm tag hợp lệ đều dưới sàn là `empty_result`; không có output
usable và có lỗi là `unresolved`. Fallback usable luôn được dùng dù JEV lỗi.
History chỉ đi qua context, không cộng/trừ trực tiếp score.

Còn cần engine, storage transaction, raw API adapters, renderer ký ức liên
bước và calibration bằng fixture campaign đã xác nhận.
