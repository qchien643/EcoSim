# Bộ tag cho luồng agent — bản thiết kế mới

**Trạng thái:** bộ từ vựng dùng policy v1 để triển khai thử, chưa calibration.
Policy: [FRD-05](../frd/05-session-policy-and-state.md). Chuẩn hóa kỳ vọng
mức/3; `top_k=3`; sàn emotion/thought=`0.30`, reason=`0.50`.
**Nguồn nghiệp vụ:** [luồng agent hiện tại](luong-agent-jev-va-llm.md) và các
làm rõ tiếp theo: chuẩn hóa trước khi chọn, trạng thái gần nhất theo đúng
bước xử lý, không đưa nội dung đầy đủ vào bước chú ý.

Bộ mới nằm tại [agent_flow_tags.v2.json](../../data/tags/agent_flow_tags.v2.json).
Đây là **registry từ vựng**, không phải JSON Schema của API JEV hoặc LLM.
Không kế thừa 112 tag hay mapping persona cũ. File cũ được giữ nguyên để
không phá dữ liệu, nhưng không dùng cho thiết kế này.

## 1. Phạm vi: 52 tag có nhiệm vụ cụ thể

| Bộ | Số tag | Nhiệm vụ |
| --- | ---: | --- |
| `enterprise` | 6 | Danh tính và định vị công khai của doanh nghiệp |
| `article` | 8 | Chủ đề, cách trình bày của bài quảng cáo |
| `product` | 12 | Loại, đặc điểm và lựa chọn phục vụ sản phẩm cafe |
| `thought` | 10 | Đánh giá, động lực, rào cản và cân nhắc thời điểm |
| `emotion` | 8 | Cảm xúc tại bước cảm nhận ban đầu hoặc sau đọc |
| `attention_reason` | 8 | Lý do agent không chú ý sau action `skip` |

Các mô tả, ranh giới, ví dụ đúng và phản ví dụ trong registry đều bằng
tiếng Anh. Phần hướng dẫn sử dụng này bằng tiếng Việt.

Đây là tập khởi đầu có chủ đích, không phải danh sách bao phủ mọi cafe hay
mọi cảm xúc. Chỉ bổ sung tag khi có tình huống trong flow mà tập hiện tại
không biểu đạt được; không sinh thêm tag chỉ để tăng số lượng.

## 2. Ma trận sử dụng theo bước

`stages` của ba bộ mô tả là **nơi được phép dùng làm context**; của ba bộ
trạng thái là **nơi được phép sinh và ghi trạng thái mới**. Được phép dùng
không có nghĩa phải đưa tất cả tag vào prompt.

| Bước | Tag/context liên quan | Trạng thái mới |
| --- | --- | --- |
| A1 — Chú ý bài | Flow, persona qua mapping, mô tả bài/doanh nghiệp được phép biết, lịch sử theo contract | Điểm chú ý và action; `skip` chuyển A1R |
| A1R — Lý do bỏ qua bài | Context A1 + action `skip` + trạng thái được phép dùng | `attention_reason` |
| A2 — Cảm nhận ban đầu | Mô tả được phép biết, persona liên quan, trạng thái A2 lần gần nhất | `emotion` |
| A3 — Đọc bài | Nội dung đầy đủ, tag doanh nghiệp/bài liên quan, cảm xúc A2 hiện tại và trạng thái A3 lần gần nhất | `emotion`, lưu riêng với A2 |
| A4 — Phản ứng | Cảm xúc A3 hiện tại và lịch sử phản ứng | Hành động, không phải tag mới |
| A5 — Ghé shop | Cảm xúc A3 hiện tại, context doanh nghiệp/shop và lịch sử được phép dùng | Quyết định ghé, không phải tag mới |
| B1 — Chú ý sản phẩm | Flow, persona liên quan, mô tả doanh nghiệp/sản phẩm được phép biết và lịch sử | Điểm chú ý và action; `skip` chuyển B1R |
| B1R — Lý do bỏ qua sản phẩm | Context B1 + action `skip` + trạng thái được phép dùng | `attention_reason` |
| B2 — Suy nghĩ sản phẩm | Context sản phẩm, persona liên quan, trạng thái B2 lần gần nhất | `thought` |
| B3 — Mua hàng | Thought tag B2 hiện tại, thông tin sản phẩm cần thiết và lịch sử | `buy` hoặc `not_buy`, không phải tag mới |

Không thêm bước cảm xúc sản phẩm: B2 hiện trả suy nghĩ theo flow đang dùng.
Nếu muốn B2 trả cả cảm xúc thì cần chốt sửa flow trước, không âm thầm mở
phạm vi `emotion` sang B2.

`attention_reason` không phải emotion tag. Nó giải thích action `skip` sau khi
đã có score hợp lệ, không thay thế score/action của A1 hoặc B1. Nếu bước
A1R/B1R cũng không có output hợp lệ, lưu `unresolved` cho bước lý do nhưng
giữ nguyên action `skip`.

## 3. Tag mô tả: giới hạn thông tin trước khi chú ý

Tag mô tả phải có nguồn và phạm vi hiển thị. Ví dụ một bản gán tag:

```json
{
  "tag_id": "article.product_introduction",
  "source_ref": "post_01.preview_description",
  "visible_stages": ["A1", "A2", "A3"]
}
```

Nếu một chi tiết chỉ có trong nội dung đầy đủ thì nguồn là nội dung đó và
`visible_stages` chỉ có `A3`. Không dùng tag để tuồn nội dung chưa đọc vào
A1/A2. Quy tắc này áp dụng cả với mô tả được dựng từ tag.

- `enterprise.craft_focus` nói **doanh nghiệp nhấn mạnh tay nghề**, không
  khẳng định chất lượng thật hoặc agent tin doanh nghiệp.
- `article.sensory_presentation` nói **bài được trình bày theo hướng cảm
  giác**, không tự tiết lộ hương vị, giá hoặc công thức.
- `product.fruit_notes` nói **mô tả sản phẩm có ghi nốt hương trái cây**,
  không khẳng định có nguyên liệu trái cây.

Tên brand, giá cụ thể, khuyến mãi cụ thể, thành phần chi tiết và định danh
là dữ liệu có cấu trúc, không tạo một tag cho mỗi giá trị. Chỉ truyền chúng
nếu contract bước đó cho phép. Không suy luận giá cao/thấp từ định vị brand.

## 4. Suy nghĩ và cảm xúc không thay thế nhau

| Khái niệm | Tag | Ranh giới |
| --- | --- | --- |
| Cảm thấy tò mò, muốn biết thêm | `emotion.interest` | Không khẳng định đã dừng lại, đọc hoặc mua |
| Thấy đặc điểm hợp sở thích | `thought.personal_fit` | Đánh giá độ phù hợp, không phải cảm giác thích thú |
| Muốn trải nghiệm sản phẩm | `thought.want_to_try` | Động lực, không phải giao dịch |
| Cân nhắc quay lại sau | `thought.consider_later` | Không phải lời hứa mua hay action thứ ba |
| Thấy giá đáng trả | `thought.value_justified` | Không đồng nghĩa đủ ngân sách |
| Cảm thấy được trấn an | `emotion.reassurance` | Khác với đánh giá một tuyên bố đáng tin |
| Thờ ơ | `emotion.indifference` | Trạng thái rõ ràng, không phải thiếu dữ liệu |

Mỗi tag chỉ đo một khái niệm. Khi tên gần nhau, xem `boundary`, `example`
và `non_example`, không quyết định chỉ từ tên ID.

## 5. Chấm điểm, chuẩn hóa và chọn tag

Registry cung cấp hai **thang nháp bốn mức bằng mô tả tiếng Anh**:

- `emotion_intensity_draft`: mức hiện diện của một cảm xúc.
- `thought_salience_draft`: mức quan trọng của một suy nghĩ trong cân nhắc.

Đưa định nghĩa và ranh giới của **đúng tag** vào câu hỏi. ID chỉ phục vụ
tham chiếu, không thay cho mô tả ý nghĩa.

JEV và LLM dự phòng phải nhận cùng định nghĩa và hướng dẫn chấm. Kết quả
đi qua:

```text
Chấm từng tag → kiểm tra đầu ra → chuẩn hóa [0,1]
→ chọn theo policy → ghép mô tả chuẩn → lưu trạng thái của bước
```

Không chốt công thức chuẩn hóa, K, điểm sàn hay cách phá hòa tại đây:
các trường này để `null`, có nghĩa **chưa cấu hình**, không phải mặc định
bằng 0 hoặc không giới hạn. Thang nháp cần thử tình huống trước khi chốt.
Hai model dùng chung định dạng không bảo đảm chấm tương đương.

Điểm các tag không cần cộng thành 1. Phân phối các mức của **một câu hỏi**
và điểm của **nhiều cảm xúc khác nhau** là hai thứ khác nhau.

Không ép một cảm xúc trung lập xuất hiện để tránh đầu ra rỗng. Nếu cả hai
model không tạo được kết quả để tiếp tục, lưu bước dừng theo quy tắc flow;
không ghi `not_buy` hoặc bịa tag `emotion.boredom`.

## 6. Đồng xuất hiện và mâu thuẫn

Cho phép các trường hợp:

- `emotion.interest` cùng `emotion.worry`: quan tâm nhưng lo.
- `thought.want_to_try` cùng `thought.price_barrier`: muốn thử nhưng giá
  là rào cản.
- `thought.value_justified` cùng `thought.price_barrier`: thấy đáng tiền
  nhưng không muốn hoặc không thể chi mức đó lúc này.
- `product.sweet_profile` cùng `product.bitter_profile`: hai nét vị.
- `product.hot_serving` cùng `product.cold_serving`: hai lựa chọn phục vụ.

Chưa đặt luật loại trừ cứng cho cảm xúc. Ví dụ vừa hứng thú với sản phẩm,
vừa chán cách trình bày vẫn có thể hợp lý. Registry đánh dấu một số cặp
để review khi cùng điểm cao, không tự xóa tag hoặc chọn hành động thay model.
Nếu gặp thường xuyên trường hợp không phân biệt được khía cạnh, cần thiết
kế phạm vi khía cạnh trước khi thêm luật loại trừ.

## 7. Lưu trạng thái để dùng lại đúng bước

Khóa nhận diện: `run_id + agent_id + object_type + object_id + stage`.
Lưu từng sự kiện; lấy **lần gần nhất của chính khóa đó**, không lấy bất kỳ
trạng thái gần nhất nào của agent.

Ví dụ minh họa sau khi đã có policy chuẩn hóa/chọn hợp lệ:

```json
{
  "run_id": "run_01",
  "agent_id": "agent_01",
  "object_type": "article",
  "object_id": "post_01",
  "stage": "A2",
  "source_event_id": "event_12",
  "vocabulary_version": "2.0-draft",
  "scale_id": "emotion_intensity_draft",
  "normalization_policy_id": "example_only",
  "selection_policy_id": "example_only",
  "tags": [
    {
      "tag_id": "emotion.interest",
      "description": "The agent feels drawn to finding out more about the object.",
      "score": 0.62
    }
  ]
}
```

Số `0.62` chỉ minh họa cấu trúc, không phải kết quả kiểm thử hay điểm sàn.
Đây là dạng lưu dữ liệu, **không phải yêu cầu nhét nguyên JSON vào prompt**.
Có thể diễn đạt lại trạng thái bằng template từ tag, mô tả và điểm đã lưu.

Ở A3 lần tiếp theo, tách cảm xúc A2 của lượt hiện tại khỏi cảm xúc A3 của
lượt trước. A2 không ghi đè A3. Không có lịch sử thì ghi chưa có; nếu lượt
gần nhất rỗng thì giữ dấu vết rỗng, không lùi về lượt có tag rồi gọi đó là
“lần gần nhất”. Cách tận dụng trạng thái xa hơn khi lượt gần nhất rỗng còn mở.

## 8. Kiểm tra và phần chưa triển khai

Chạy không gọi API:

```bash
python3 paper_research/validate_flow_tags_v2.py
```

Kiểm tra registry, phạm vi bước, ID, mô tả, điểm chuẩn hóa và các fixture
sai. Đây là kiểm tra cấu trúc; không chứng minh bộ tag mô phỏng đúng con
người hoặc JEV hiểu thang nháp như mong muốn.

Mapping persona mới đã được dựng tại
[agent-flow-tag-persona-mapping-v2.json](../../data/tags/agent_flow_tag_persona.mapping.v2.json)
và được giải thích trong
[tài liệu mapping](agent-flow-tag-persona-mapping-v2.md). Chưa có client API,
policy tác động lịch sử hoặc cơ chế tự động cập nhật persona. Không chuyển
mapping cũ sang bằng cách đổi tên ID.
