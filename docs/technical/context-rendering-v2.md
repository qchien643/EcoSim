# Context renderer cho JEV và LLM

**Trạng thái:** bản nháp để review  
**Contract máy:** [context-rendering.v2.json](../../data/contracts/context-rendering.v2.json)  
**Mapping persona:** [agent-flow-tag-persona-mapping-v2.md](agent-flow-tag-persona-mapping-v2.md)

## 1. Context renderer là gì?

Context renderer là lớp deterministic đứng sau mapping. Mapping chọn field
persona và tag liên quan; renderer chuyển chúng thành một prompt độc lập mà
model khác có thể hiểu mà không cần đọc registry, database hoặc tài liệu
nội bộ.

```text
Persona + object tags + history
        ↓
Mapping chọn thông tin
        ↓
Renderer diễn giải thành ngôn ngữ tự nhiên
        ↓
JEV hoặc LLM fallback
```

Các ID như `A1`, `trait_curiosity`, `article.offer` chỉ tồn tại trong metadata
và log. Chúng không xuất hiện trong prompt cuối, trừ khi một contract kỹ
thuật bên ngoài yêu cầu rõ ràng.

## 2. Quy tắc render

- Mở đầu bằng vai trò và tình huống hiện tại.
- Diễn giải giá trị persona thành câu có nghĩa, ví dụ:
  `trait_curiosity: Strong` → “This person has a strong tendency to be
  curious about unfamiliar things.”
- Diễn giải tag bằng `description` canonical, không đọc ID cho model.
- Render lịch sử thành ký ức tự nhiên của cùng agent và object.
- Tách kết quả bước trước trong lượt hiện tại khỏi ký ức cùng bước ở lần
  trước.
- Không đưa dữ liệu chưa được phép thấy ở stage đó.
- Cuối prompt phải nêu rõ nhiệm vụ, giới hạn và output contract.

Context rỗng không được biến thành trạng thái tiêu cực. Nếu không có lịch sử,
render: “No prior interaction with this object is known.”

## 3. Mẫu A1 hoàn chỉnh

```text
You are simulating one individual who is scrolling through a social media
platform during a short break.

This person's relevant characteristics are:
- They have a strong tendency to be curious about unfamiliar things.
- Their attention span is average.
- They have a neutral attitude toward advertising.
- They tend to prefer novel experiences over familiar ones.

The business publicly presents itself as a local cafe and emphasizes careful
coffee preparation.

The visible advertisement introduces a coffee drink and presents it through
taste and sensory descriptions. The full post has not been read.

This person has encountered this same advertisement twice before. During the
previous encounter, they chose not to pay attention because the advertisement
felt repetitive.

Evaluate only the person's willingness to pay attention to this advertisement
now. Do not evaluate reading the full post, liking it, visiting the shop, or
buying anything.

Rate the current willingness to pay attention using these ordered levels:
1. No willingness to pay attention.
2. Slight willingness to pay attention.
3. Clear willingness to pay attention.
4. Strong willingness to pay attention.

Return the result using the required structured format.
```

## 4. Mẫu B2 hoàn chỉnh

```text
You are simulating one individual who is paying attention to a product inside
an online cafe shop.

This person's relevant characteristics are:
- They tend to make deliberative decisions.
- They are value-driven when evaluating purchases.
- They lean toward quality over quantity.
- They prefer novel experiences over familiar ones.

The business publicly emphasizes careful preparation and presents its products
as good value for money.

The product is a prepared coffee drink served cold and described as having
fruit-like flavor notes. Its listed price is 39,000 VND.

During a previous consideration of this same product, the person thought they
might return later and then decided not to buy it.

Evaluate only the thoughts currently central to considering this product.
Possible thoughts include personal fit, desire to try, price as a barrier,
missing information, and considering it later. Do not choose buy or not buy.

Return scores only for the supplied thought tags using the required structured
format.
```

## 5. Render theo từng nhóm stage

### A1/B1

Đây là context quyết định mức chú ý. Chỉ dùng preview được phép, persona
fields của mapping, business/object descriptions và memory liên quan. Kết quả
model là score; deterministic policy mới chuyển score thành `attend` hoặc
`skip`.

### A1R/B1R

Đây là context sau một `skip` hợp lệ. Renderer giữ snapshot context vừa dùng,
thêm câu “The agent has just chosen not to pay attention”, rồi cung cấp
attention-reason tags. Model không được đổi action `skip`.

### A2

Agent đã chú ý nhưng chưa đọc bài. Renderer dùng preview, không dùng nội dung
đầy đủ. Persona được chọn lại theo A2; trạng thái A2 trước đó được viết thành
ký ức tự nhiên.

### A3

Agent đã đọc bài. Renderer đưa nội dung đầy đủ, emotion hiện tại từ A2 và
memory A3 gần nhất. Không thêm persona fields mới.

### A4/A5

Renderer chỉ đưa cảm xúc hiện tại, business/shop reference và lịch sử liên
quan. Không đưa toàn bộ persona hoặc nội dung bài đầy đủ.

### B1/B1R

B1 là bước chú ý sản phẩm. Context có tên sản phẩm, giá, tag sản phẩm được
phép thấy và persona liên quan. Mô tả chi tiết sản phẩm chưa được đưa vào B1.
B1R tái sử dụng chính context B1 để hỏi lý do `skip`, nên cũng không có thêm
mô tả chi tiết.

### B2/B3

B2 dùng tên, giá, mô tả sản phẩm, tag sản phẩm, persona liên quan và memory
cân nhắc trước đó để sinh thought tags. B3 dùng cùng thông tin sản phẩm, các
thought tags hiện tại và purchase history để chọn `buy` hoặc `not_buy`; không
tạo thought mới để giải thích ngược action.

Tóm tắt dữ liệu sản phẩm:

| Stage | Tên | Giá | Mô tả chi tiết | Tag sản phẩm |
| --- | --- | --- | --- | --- |
| B1 | Có | Có | Không | Có |
| B1R | Có | Có | Không | Giữ nguyên B1 |
| B2 | Có | Có | Có | Có |
| B3 | Có | Có | Có | Có |

## 6. Dữ liệu đầu vào nội bộ và prompt cuối

Renderer có thể nhận dữ liệu nội bộ như:

```json
{
  "field_id": "trait_curiosity",
  "value": "Strong",
  "description": "Curiosity as a character trait."
}
```

Nhưng prompt cuối phải render thành:

```text
This person has a strong tendency to be curious about unfamiliar things.
```

Tương tự:

```json
{
  "tag_id": "attention_reason.repetition_fatigue",
  "score": 0.81
}
```

được render thành:

```text
During the previous encounter, the advertisement felt repetitive to this
person.
```

Không render score lịch sử nếu score không cần cho nhiệm vụ. Có thể giữ score
trong context khi contract yêu cầu tích lũy định lượng; khi đó phải diễn giải
rõ đây là mức độ ghi nhận trước đó, không phải xác suất hành động.

## 7. Quy tắc lịch sử

Renderer phải phân biệt:

- **No history:** chưa có tương tác được biết.
- **Previous same-stage state:** trạng thái gần nhất của đúng object và stage.
- **Current upstream state:** kết quả vừa sinh ở bước trước trong lượt hiện tại.
- **Event history:** action đã xảy ra, như đã đọc, đã ghé hoặc đã mua.

Không viết “the latest state” nếu không nói rõ latest của bước nào. Không lấy
emotion A2 thay cho emotion A3, hoặc thought B2 thay cho trạng thái chú ý B1.

## 8. Validator và giới hạn hiện tại

Contract renderer hiện được lưu ở JSON và đã có prototype offline tại
`paper_research/render_agent_context_v2.py`. Đây chưa phải client gọi
OpenRouter/JEV. Khi bắt đầu tích hợp model, adapter phải:

1. validate input theo stage;
2. chọn variant từ history snapshot;
3. render prompt từ template cố định;
4. ghi prompt version và input references;
5. không cho object content ghi đè output contract.

Chạy renderer thử với dữ liệu mẫu:

```bash
python3 paper_research/render_agent_context_v2.py --example A1
python3 paper_research/render_agent_context_v2.py --example B3
python3 paper_research/validate_context_rendering_v2.py
```

Không thêm field persona chỉ vì còn budget token. Bổ sung field hoặc template
chỉ khi một scenario cụ thể cho thấy context hiện tại không đủ.
