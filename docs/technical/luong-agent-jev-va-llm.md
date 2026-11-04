# Luồng agent: chú ý, cảm xúc, tương tác và mua hàng

**Trạng thái:** policy v1 đã có runtime tích hợp tại `simulation/`, kiểm tra
offline; chưa calibration hành vi khách hàng.
**Nguồn quyết định hiện hành:** [FRD-05](../frd/05-session-policy-and-state.md)
và `data/contracts/simulation-policy.v1.json`.

**Bộ tag mới:** xem [thiết kế tag theo flow](bo-tag-flow-v2.md) và
[registry v2](../../data/tags/agent_flow_tags.v2.json). Không dùng bộ tag hoặc
mapping persona cũ. Hướng dẫn tag mới phân biệt trạng thái cùng bước ở lần
gặp trước với kết quả bước trước trong lượt hiện tại. V1 chuẩn hóa kỳ vọng
mức/3; K=3; sàn emotion/thought=0.30, reason=0.50.

**Ma trận contract:** xem [ma trận contract JEV/LLM](jev-contract-matrix.md).
Ma trận này quy định biến thể đáp án theo context và lịch sử trước khi tạo
JSON Schema triển khai.

**Policy trạng thái chú ý:** xem [attention-state-policy.md](attention-state-policy.md).
Tài liệu này quy định threshold, trạng thái `unresolved`, dữ liệu A1/B1 cần
lưu và bước lấy lý do sau `skip`.

**Mapping persona:** xem
[agent-flow-tag-persona-mapping-v2.md](agent-flow-tag-persona-mapping-v2.md).
Mapping chỉ chọn trường persona cho context; không thay thế policy hành động.

**Context độc lập:** xem
[context-rendering-v2.md](context-rendering-v2.md) và
[context-rendering.v2.json](../../data/contracts/context-rendering.v2.json).
Renderer chuyển dữ liệu nội bộ sau mapping thành prompt độc lập cho JEV/LLM;
model không cần biết ID registry hoặc cấu trúc database.

Tài liệu mô tả phác thảo mới của chủ dự án: dùng JEV cho các câu hỏi hẹp
trong từng bước; dùng LLM với đầu ra có cấu trúc làm phương án dự phòng khi
không có tag cảm xúc nào vượt điểm sàn.

Vì có mô tả cách sử dụng model, tài liệu thuộc `technical/`, không thay thế
[SRS](../srs/01-system-requirements.md) hoặc tự chốt lại các FRD.

## 1. Phạm vi và trạng thái quyết định

- **Theo phác thảo:** năm bước với bài viết; context chọn lọc ở từng bước;
  chấm điểm tag cảm xúc, chọn top và lọc theo sàn; LLM dự phòng khi không
  tag cảm xúc nào được chọn.
- **Đã chốt cho v1:** ba bước trong shop gồm chú ý món hàng, nêu suy nghĩ
  khi thấy món hàng, rồi quyết định `buy` hoặc `not_buy`.
- **Bổ sung:** trước các bước xử lý nội dung, hệ thống mapping tag doanh
  nghiệp/brand, tag bài viết hoặc tag sản phẩm với các trường persona/context
  liên quan.
- **Đã chốt:** khi tương tác lại với bài đã có phản ứng, agent có thể giữ
  nguyên phản ứng, bỏ phản ứng hiện tại hoặc không tạo phản ứng mới.
- **Đã chốt:** nếu cả JEV và LLM dự phòng đều không trả được đáp án hợp lệ,
  lưu `unresolved` và dừng nhánh hiện tại, không tạo action `no_reaction`.
- **Đã chốt:** JEV đánh giá toàn bộ bài viết hoặc toàn bộ sản phẩm hợp lệ
  trong phạm vi đang xử lý; không dùng một tầng lọc trước để chọn trước một tập
  ứng viên.

Không thêm thuật toán đề xuất kiểu feed, không tự thêm công thức vector hay
điểm thưởng vào bước JEV quyết định chú ý. Không gọi model phân tích lại
“tiềm năng mua” sau `not_buy`.

## 2. Sơ đồ tổng thể

```text
Agent hoạt động và gặp một bài quảng cáo đã được đăng
  ↓
A0. Mapping tag doanh nghiệp/brand + tag bài viết → context persona
  ↓
A1. Chú ý / bỏ qua
  ├─ Bỏ qua → lưu sự kiện → A1R chấm lý do → kết thúc nhánh bài này
  └─ Chú ý
      ↓
    A2. Cảm xúc ban đầu từ tag bài, chưa đọc nội dung
      ↓
    A3. Đọc nội dung → cảm xúc sau đọc
      ↓
    A4. Like / dislike / không phản ứng hoặc cập nhật phản ứng
      ↓
    A5. Ghé shop / không ghé
      ├─ Không ghé → kết thúc nhánh
      └─ Ghé
          ↓
        B0. Mapping tag doanh nghiệp/brand + tag sản phẩm → context persona
          ↓
        B1. Chú ý từng món hàng trong shop: chú ý / bỏ qua
          ├─ Bỏ qua → B1R chấm lý do → không tạo quyết định mua cho món hàng đó
          └─ Chú ý
              ↓
            B2. Nêu suy nghĩ khi thấy món hàng → tag suy nghĩ
              ↓
            B3. Quyết định buy / not_buy → lưu cả hai trường hợp
```

A2 và A3 dùng cơ chế chấm tag và dự phòng ở mục 4. Việc áp dụng cơ chế tương
tự cho tag suy nghĩ tại B2 đã được chốt trong policy v1.

Ở A1 và B1, JEV được gọi cho từng đối tượng hợp lệ: toàn bộ bài viết đang
được xét trong nền tảng hoặc toàn bộ sản phẩm đang có trong shop. Hệ thống
không dùng một tầng lọc trước để rút gọn danh sách trước khi JEV đánh
giá. Phạm vi đối tượng chỉ dựa trên scenario, session, trạng thái
đăng/hiển thị và quan hệ shop–sản phẩm.

Nếu một bước chưa có kết quả hợp lệ, không tự cho chuỗi chạy tiếp với một
cảm xúc hoặc hành động được bịa ra.

## 3. Context và lịch sử dùng chung

### 3.1. Phân biệt “chú ý” và “đọc”

Trong tài liệu này chỉ dùng hai từ nghiệp vụ:

- **Chú ý:** agent dừng lại hoặc hướng sự chú ý đến bài viết/món hàng, nhưng
  chưa được coi là đã đọc nội dung bài hoặc đã nêu suy nghĩ đủ sâu về món hàng.
- **Đọc:** agent tiếp nhận nội dung bài viết đầy đủ và được phép chuyển sang
  các bước cảm xúc, phản ứng hoặc ghé shop.

A2 là cảm nhận sơ bộ sau khi chú ý bài, không phải cảm xúc sau đọc.

Chưa từng đọc không đồng nghĩa chưa từng gặp bài. Hệ thống phân biệt số lần
gặp, số lần chú ý và số lần đọc hoàn tất. Chỉ ghi nhận tiếp xúc khi agent
thực sự gặp đối tượng, không vì bài đã được đăng.

### 3.2. Lịch sử được chuyển thành mô tả

**Làm rõ cho bộ tag mới:** ký ức suy nghĩ/cảm xúc là trạng thái gần nhất
của đúng `run + agent + object + stage`, không phải toàn bộ lịch sử sự kiện
hay cảm xúc mới nhất ở bất kỳ bước nào. Kết quả bước trước trong lượt hiện
tại là đầu vào riêng. Các ví dụ hành động bên dưới chỉ được dùng khi
contract của bước cho phép, không mặc định đưa vào mọi prompt.

Ở A1/B1 lưu score và action; sau skip lưu lý do A1R/B1R riêng.
Không lấy trạng thái A2/B2 thay vào rồi gọi đó là trạng thái chú ý lần trước.
Ký ức mua/cân nhắc liên bước phải có nhãn và tham chiếu riêng theo FRD-05.

Context lịch sử lấy từ hành động đã lưu và tag tương ứng, chẳng hạn:

> Tôi đã đọc bài này một lần. Sau đó tôi ghé shop và thấy hứng thú với món P,
> nhưng đã quyết định không mua món P trong lần đó.

Đoạn này cần sự kiện đọc, sự kiện ghé shop, cảm xúc về P và action `not_buy`;
không được suy ra tất cả chỉ từ một tag cảm xúc.

**Đề xuất:** dựng mô tả bằng mẫu cố định. Nếu dùng diễn đạt ngôi thứ nhất,
vẫn phải giữ đúng đối tượng và dữ kiện nguồn; không sinh ký ức mới.

- Lịch sử bài: theo agent–bài viết.
- Lịch sử shop và số lần ghé: theo agent–shop, kể cả đến từ bài khác.
- Lịch sử sản phẩm: theo agent–sản phẩm.
- Quan hệ thương hiệu: theo agent–brand, tách khỏi tính cách chung.

Khi nhắc trải nghiệm shop bắt nguồn từ một bài, phải có liên kết sự kiện
tương ứng; không lấy trải nghiệm từ bài khác rồi nói do bài hiện tại.

Chốt mốc lịch sử “trước lần gặp hiện tại” ở đầu chuỗi. Kết quả vừa tạo ở
bước trước được truyền riêng như context hiện tại, không gọi là ký ức lần
trước.

### 3.3. Danh tính và giới hạn thông tin

Chỉ đưa thông tin doanh nghiệp/brand đang hiển thị và thông tin agent đã
biết từ khởi tạo hoặc lịch sử. Không đưa mục tiêu nội bộ chiến dịch hoặc
comment của agent khác vào context.

Chỉ lấy các trường persona liên quan và có dữ liệu; không đưa cả hồ sơ.
Không tự suy ra sở thích từ trường thiếu.

### 3.4. Số lần và cách diễn đạt kết quả

Model chọn hành động; hệ thống đếm số lần từ sự kiện hợp lệ:

- “Đọc lại lần thứ n”: tính từ số lần đọc hoàn tất của bài.
- “Ghé shop lần thứ n”: tính từ số lần ghé shop.
- “Chú ý món hàng lần thứ n”: tính từ số lần chú ý món hàng.

Không ghi một lần đọc hoàn tất ngay khi A1 chọn chú ý. Không đếm lại sự kiện
chỉ vì một lời gọi được thử lại.

### 3.5. Contract đáp án phụ thuộc context

Kiểu bước (`score`, `tag_scores` hoặc `choice`) chỉ xác định **dạng câu
hỏi**. Danh sách đáp án cụ thể phải được dựng deterministic trước mỗi lời
gọi, dựa trên context hiện tại và snapshot lịch sử của đúng đối tượng.

Các cờ trạng thái tối thiểu gồm:

- `has_encountered`, `has_attended`, `has_read`;
- `has_current_reaction`;
- `has_visited`;
- `has_purchased`.

Ví dụ các biến thể contract:

| Bối cảnh | Đáp án gửi cho model |
| --- | --- |
| Bài chưa từng gặp | `attend`, `skip` |
| Bài đã từng chú ý/đọc | `attend_again`, `skip` |
| Chưa từng phản ứng | `like`, `dislike`, `no_reaction` |
| Đã có phản ứng | `keep_current`, `remove_reaction`, `no_new_reaction` |
| Chưa từng ghé shop | `visit`, `not_visit` |
| Đã từng ghé shop | `visit_again`, `not_visit_again` |
| Chưa từng mua sản phẩm | `buy`, `not_buy` |
| Đã từng mua sản phẩm | `buy_again`, `not_buy_again` |

Không tạo đáp án riêng như `buy_again_2`. Số lần `n` được hệ thống tính từ
event hợp lệ sau khi model chọn đáp án. `not_buy` và `not_buy_again` vẫn là
action cần lưu; chúng không bị biến thành “không có action”.

Với câu hỏi `score`, trục đo phải giữ cùng ý nghĩa để so sánh giữa các lần,
nhưng câu hỏi và mô tả có thể được tham số hóa theo bối cảnh: “mức muốn chú ý
đến sản phẩm” và “mức muốn chú ý lại đến sản phẩm” là hai context của cùng
trục chú ý. Với `tag_scores`, danh sách tag được phép được dựng theo stage
và context, nhưng không được tạo tag mới ngoài registry.

Adapter phải ghi lại `contract_variant`, điều kiện tạo variant và danh sách
đáp án đã gửi. Model không được tự suy ra hoặc tự mở rộng danh sách đáp án
từ nội dung quảng cáo.

### 3.6. Bước mapping context

Mapping là bước deterministic chuẩn bị context, không phải một lời gọi JEV và
không quyết định agent sẽ chú ý, đọc, like, ghé shop hay mua.

Input của mapping gồm:

- tag doanh nghiệp/brand công khai;
- tag bài viết khi xử lý mạng xã hội;
- tag sản phẩm khi xử lý shop;
- flow hiện tại;
- persona hiện tại và các trường có dữ liệu;
- giới hạn context của flow.

Output của mapping gồm:

- các trường persona liên quan được chọn;
- giá trị hiện tại của các trường đó;
- mô tả tag doanh nghiệp/brand và tag nội dung;
- các giới hạn diễn giải của mapping;
- context công khai được phép đưa cho agent.

Mapping v2 chọn persona field tại A1/A2 với tag doanh nghiệp và bài viết,
tại B1/B2 với tag doanh nghiệp và sản phẩm. A1R/B1R tái sử dụng snapshot
context của A1/B1 trong lượt hiện tại, không chọn thêm field để giải thích
ngược hành động. A3/A4/A5/B3 không thêm persona field; chúng nhận kết quả
bước trước, thông tin object được phép và history theo contract. Phạm vi
này thay thế đề xuất mapping tại mọi bước trong bản nháp trước.

Thought, emotion và attention-reason tag của lịch sử được truyền như trạng
thái đã lưu, không dùng mapping này để biến chúng thành quy tắc action.

Một trường được mapping không có nghĩa là agent chắc chắn sẽ có cảm xúc hoặc
hành động tương ứng. Mapping chỉ chọn thông tin liên quan để context không
bị thiếu hoặc chứa toàn bộ persona.

## 4. Chấm tag cảm xúc và gọi LLM dự phòng

### 4.1. Luồng đã được yêu cầu

```text
Context của bước + bộ tag cảm xúc được phép + hướng dẫn chấm điểm
  ↓
JEV đánh điểm từng tag
  ↓
Kiểm tra kết quả → chuyển về thang [0, 1] cố định
  ↓
Xếp giảm dần → lấy tối đa K → bỏ tag dưới điểm sàn
  ├─ Còn tag → lưu và chuyển sang bước tiếp theo
  └─ Không còn tag
      ↓
    LLM với structured output chấm lại cùng bộ tag
      ↓
    Kiểm tra → chuẩn hóa → áp dụng cùng K và điểm sàn
      ├─ Còn tag → lưu và chuyển sang bước tiếp theo
      └─ Không còn tag → empty_result hoặc unresolved theo FRD-05 → dừng nhánh
```

LLM dự phòng nhận cùng context nghiệp vụ, danh sách tag và định nghĩa thang
điểm như lượt chấm bằng JEV. Không yêu cầu LLM cố tạo một tag vượt sàn.

### 4.2. Quy ước điểm — policy v1

- Dùng một thang có mô tả mức cố định cho mỗi loại chấm; không đổi thang
  theo từng agent hoặc từng lần gọi.
- Dùng phân phối trên bốn mức 0–3; `s = Σ(i × P(i))/3`.
  Kiểm tra đủ mức, giá trị hữu hạn và tổng xác suất trước khi tính.
  Không làm tròn trước khi lọc sàn.
- Không chuẩn hóa theo điểm thấp nhất/cao nhất của các tag trong cùng lượt:
  điều đó có thể biến một cảm xúc yếu thành điểm cao.
- Không ép tổng điểm các tag bằng 1, vì một agent có thể có nhiều cảm xúc.
- K=3; sàn A2/A3/B2=0.30, A1R/B1R=0.50. Giữ điểm `>=` sàn;
  khi bằng điểm, dùng thứ tự tag ID tăng dần. Đây là giá trị ban đầu,
  không phải kết luận calibration.
- Việc chọn tag phải dùng đúng phạm vi bước và định nghĩa trong
  [registry mới](../../data/tags/agent_flow_tags.v2.json).
  Không kế thừa giới hạn nhóm của bộ tag cũ.

Dùng cùng thang không bảo đảm hai model chấm tương đương; cần kiểm tra bằng
những tình huống mẫu trước khi sử dụng kết quả để phân tích mô phỏng.

### 4.3. Structured output của LLM dự phòng

Raw LLM trả mảng xác suất theo alias như renderer quy định:
`{"question_1": [0.05, 0.15, 0.60, 0.20]}`. Mỗi alias tương ứng đúng một
tag, đủ bốn mức và tổng bằng 1. Không yêu cầu LLM trả score trực tiếp.
Ví dụ sau là **output nội bộ sau chuẩn hóa**, không phải raw API:

```json
{
  "scores": [
    {
      "tag_id": "emotion.interest",
      "description": "The agent feels drawn to finding out more about the object.",
      "score": 0.72
    },
    {
      "tag_id": "emotion.worry",
      "description": "The agent feels uneasy about a possible unfavorable outcome related to the object.",
      "score": 0.41
    }
  ]
}
```

Contract cho mỗi lời gọi cần yêu cầu:

- `tag_id` nằm trong danh sách cấp cho chính bước đó; không tạo tag mới.
- Chấm đủ mỗi tag được yêu cầu đúng một lần, không thiếu hoặc trùng.
- `score` sau adapter là số hữu hạn trong `[0, 1]`.
- `description` là mô tả chuẩn lấy từ tag registry, không phải câu model tự
  viết. Raw response dùng alias và phân phối; adapter bổ sung mô tả sau validate.
- Không trả thêm đoạn suy nghĩ tự do thay cho danh sách điểm.

Hệ thống lưu điểm gốc, điểm chuẩn hóa, tag được giữ, nguồn chấm và lý do
chuyển sang dự phòng. Không cộng/trung bình điểm của hai model; lượt dự
phòng hợp lệ được xử lý như một lượt chấm thay thế.

### 4.4. Đầu ra cảm xúc có mô tả tag

Output nghiệp vụ của A2 và A3 không chỉ là danh sách ID. Mỗi tag cảm xúc
được giữ lại phải có:

```json
{
  "tag_id": "emotion.interest",
  "description": "The agent feels drawn to finding out more about the object.",
  "score": 0.72
}
```

`description` phải được lấy từ định nghĩa chính thức trong tag registry. JEV
hoặc LLM chỉ chọn và chấm `tag_id`; lớp xử lý deterministic ghép mô tả theo
`tag_id` sau khi kiểm tra. Không dùng câu mô tả do model tự sinh làm định
nghĩa mới cho tag.

Nếu cùng một tag xuất hiện ở A2 và A3, hai bản ghi vẫn phải được giữ riêng vì
chúng thuộc hai trạng thái khác nhau: cảm xúc khi mới chú ý và cảm xúc sau
khi đọc.

### 4.5. Nếu cả JEV và LLM dự phòng đều rỗng

Đây là quy tắc đã chốt:

- gọi LLM dự phòng một lượt khi JEV lỗi/sai output hoặc toàn bộ tag dưới sàn;
- cả hai lượt hợp lệ nhưng không tag đạt sàn: `empty_result`;
- fallback usable: `resolved`, source=`llm_fallback`, kể cả JEV lỗi;
- không có kết quả usable và có ít nhất một lượt lỗi/sai: `unresolved`;
- không gọi bước phụ thuộc tiếp theo;
- không tự thêm tag trung lập, không hạ điểm sàn và không đổi kết quả thành
  `not_buy`.

Ví dụ, nếu A2 không có tag cảm xúc hợp lệ thì agent không đi tới A3, A4 hoặc
A5. Nếu B2 không có tag suy nghĩ hợp lệ thì agent không đi tới B3. Với bước
action, đáp án rỗng được lưu là `unresolved` và kết thúc nhánh, không tạo
action thay thế. `no_reaction` chỉ là một lựa chọn hợp lệ do model trả về
trong contract của A4.

Lỗi kết nối, response sai cấu trúc và kết quả hợp lệ nhưng dưới sàn là các
trường hợp khác nhau. Quy tắc retry lỗi kỹ thuật không nằm trong nhánh
“không tag nào đạt sàn” đã được yêu cầu.

## 5. Năm bước với bài viết

### A1. Quyết định chú ý

**Câu hỏi:** “Bạn đang lướt mạng xã hội. Bạn có muốn chú ý đến bài quảng cáo này không?”

**Context:**

- Flow hiện tại.
- Kết quả mapping: các trường persona liên quan đến tag doanh nghiệp/brand và
  tag bài viết, cùng giá trị hiện tại của chúng.
- Tag doanh nghiệp/brand và tag mô tả bài đang hiển thị; chưa có nội dung đầy
  đủ của bài.
- Lịch sử lần gặp trước: đã đọc chưa, đã làm gì, có cảm xúc gì.

**Kết quả:** model chấm score; code áp ngưỡng 0.60. Đạt sàn thì `attend`
nếu chưa từng chú ý, `attend_again` nếu đã từng chú ý; dưới sàn là `skip`.
Đã từng gặp nhưng chỉ skip không tự trở thành `attend_again`.

Nếu bỏ qua, lưu sự kiện, gọi A1R lấy lý do rồi kết thúc nhánh bài.
Không gọi A2/A3, không ghi rằng agent đã đọc hoặc có cảm xúc sau đọc.

### A2. Cảm nhận ban đầu trước khi đọc

**Câu hỏi:** “Bạn vừa chú ý đến quảng cáo này. Qua phần mô tả đang thấy, bạn có cảm xúc gì trước khi đọc?”

**Context:**

- Flow đang lướt và đã chú ý vào một quảng cáo.
- Kết quả mapping cho tag doanh nghiệp/brand và tag bài viết.
- Mô tả công khai của doanh nghiệp/brand đang được hiển thị.
- Trải nghiệm trước lần gặp hiện tại theo mục 3.

**Kết quả:** chấm bộ tag cảm xúc và chọn theo mục 4, bao gồm LLM dự phòng
nếu cần. Mỗi tag được chọn phải đi kèm mô tả chuẩn của chính tag đó. Lưu
riêng là cảm xúc trước đọc. Nếu không chọn được tag sau fallback, lưu
`empty_result` hoặc `unresolved` theo mục 4.5 và không gọi A3.

### A3. Đọc bài và nêu cảm xúc sau đọc

**Câu hỏi:** “Với cảm xúc hiện tại, sau khi đọc bài quảng cáo này bạn cảm thấy thế nào?”

**Context:**

- Flow đang đọc bài quảng cáo của brand.
- Flow đang đọc nội dung bài đã chú ý.
- Các tag cảm xúc được giữ từ A2.
- Tag doanh nghiệp/brand và tag bài viết được phép biết; không chọn thêm
  persona field tại A3.
- Nội dung bài viết và thông tin công khai thực sự xuất hiện trong bài.

Không tự đưa lại toàn bộ persona hoặc lịch sử. Kết quả là bộ tag cảm xúc
sau đọc theo mục 4, lưu riêng với cảm xúc A2; mỗi tag có `tag_id`,
`description` và `score` sau chuẩn hóa.

Nếu chấm cảm xúc thất bại sau khi nội dung đã được xử lý, giữ sự kiện đọc.
Nếu sau fallback vẫn không có tag, lưu `empty_result` hoặc `unresolved` và
không gọi A4 hoặc A5.

### A4. Phản ứng với bài

**Câu hỏi:** “Bạn vừa đọc bài này. Bạn sẽ like hay dislike?”

**Context:** flow sau đọc, tag cảm xúc A3, trải nghiệm trước đó và phản ứng
hiện đang gắn với đúng bài này.

Context giữ danh tính brand được phép biết, không truyền lại persona context
của bước trước hoặc thông tin nội bộ campaign vào lời gọi.

- **Lần đầu:** LLM chọn `like`, `dislike` hoặc `no_reaction`.
- **Các lần sau:** LLM chọn `keep_current`, `remove_reaction` hoặc
  `no_reaction`.
- `keep_current` giữ nguyên `like` hoặc `dislike` hiện tại.
- `remove_reaction` xóa phản ứng hiện tại.
- `no_reaction` không tạo thay đổi mới đối với trạng thái phản ứng.

Comment chưa thuộc phạm vi thiết kế của flow hiện tại.

Lưu sự kiện thay đổi và trạng thái phản ứng hiện tại. Một agent không được
tính đồng thời là đang like và dislike cùng một bài.

### A5. Cân nhắc ghé shop

**Câu hỏi:** “Sau khi đọc quảng cáo, bạn có muốn ghé shop của họ không?”

**Context:** flow đang cân nhắc vào shop, danh tính shop/brand, tag cảm xúc A3,
trải nghiệm trước lần gặp hiện tại và lịch sử với đúng shop/brand. Không chọn
thêm persona field tại A5; dùng cảm xúc A3 hiện tại.

**Kết quả:** nếu chưa từng ghé, contract dùng `visit` hoặc `not_visit`; nếu
đã từng ghé, dùng `visit_again` hoặc `not_visit_again`. Số lần ghé lại do hệ
thống tính từ event, không phải do model tự tạo hậu tố số.
Không dùng like/dislike làm điều kiện bắt buộc để được vào shop.

**Policy v1:** “không ghé lại” là không ghé trong lượt này, chưa có
nghĩa cấm quay lại vĩnh viễn. Nếu chủ dự án muốn quyết định vĩnh viễn, cần
định nghĩa riêng.

Nếu ghé, lưu lượt ghé và bài dẫn đến lượt ghé trước khi bắt đầu B1.

## 6. Ba bước mua hàng — policy v1

Bổ sung này là policy v1 để triển khai thử. Không thêm bước cảm xúc sản phẩm
riêng như tài liệu cũ; mục tiêu là giữ chuỗi mua hàng ngắn hơn chuỗi bài viết.

### B1. Chú ý món hàng trong cửa hàng

**Câu hỏi:** “Bạn đang ở shop này. Bạn có muốn chú ý đến món hàng đang gặp không?”

**Điều kiện:** agent đã ghé shop và đang gặp sản phẩm có trong danh mục của
kịch bản. Vào shop không tự có nghĩa đã nhìn thấy mọi sản phẩm.

**Context policy v1:**

- Flow đang quan sát gian hàng.
- Kết quả mapping cho tag doanh nghiệp/brand và tag sản phẩm.
- Mô tả công khai của doanh nghiệp/brand và shop đang được agent nhận biết.
- Tag sản phẩm, tên, giá và thông tin thực sự thấy được ở phần giới thiệu
  sơ bộ; không dùng chi tiết chỉ có sau khi mở nội dung đầy đủ.
- Danh tính shop/brand đang hiển thị và quan hệ đã biết.
- Cảm xúc sau bài quảng cáo dẫn đến lượt ghé hiện tại, nếu có.
- Lịch sử của đúng sản phẩm: từng chú ý, từng mua hay chưa, suy nghĩ/cảm xúc
  và action gần nhất.

**Kết quả:** chú ý hoặc bỏ qua cho từng sản phẩm. JEV được gọi lần lượt cho
toàn bộ sản phẩm hợp lệ trong shop; không chọn trước một danh sách sản phẩm
bằng tầng lọc khác. Nếu đã chú ý trước đó, ghi nhận chú ý lại; số lần lấy
từ lịch sử.

- Chọn chú ý: bắt đầu B2.
- Bỏ qua: lưu việc bỏ qua, không sinh action `not_buy`.
- Không có món được chú ý: có thể kết thúc lượt ghé mà không tạo quyết định
  mua nào.

V1 lưu lịch sử mua/không mua và thought tag vào context, nhưng không cộng/trừ
trực tiếp điểm B1. Cách này giữ cho JEV đánh giá lại từ context hiện tại;
calibration sau này mới quyết định có cần adjustment deterministic hay không.
Không khôi phục thuật toán xếp hạng feed hoặc tự thêm điểm số vào B1.

### B2. Nêu suy nghĩ khi thấy món hàng

**Câu hỏi:** “Bạn đang chú ý đến món hàng này. Bạn đánh giá điều gì, muốn điều gì hoặc có điều gì khiến bạn còn cân nhắc?”

**Context policy v1:**

- Flow đã chú ý và đang nêu suy nghĩ về món hàng.
- Kết quả mapping cho tag doanh nghiệp/brand và tag sản phẩm.
- Mô tả công khai của doanh nghiệp/brand/shop đang được agent biết trong flow.
- Tag và mô tả sản phẩm, giá, điều kiện ưu đãi nếu có.
- Các trường persona liên quan, không phải toàn bộ persona.
- Context dẫn đến lượt ghé và thông tin brand agent thực sự biết.
- Lịch sử chú ý/mua sản phẩm cùng tag của lần đánh giá trước.

**Kết quả policy v1:** JEV chấm các **tag suy nghĩ** trong bộ từ vựng đóng,
sau đó hệ thống giữ các tag đạt sàn và giới hạn số lượng.

Ví dụ tag mới: `thought.want_to_try`, `thought.consider_later`,
`thought.price_barrier`, `thought.information_gap`. Đây là các ví dụ độc
lập, không phải bộ tag bắt buộc phải cùng được chọn.

Tag suy nghĩ khác tag cảm xúc: “muốn thử”, “giá là rào cản” mô tả đánh giá
và động lực, không đồng nghĩa “hào hứng”, “khó chịu”.

**Policy v1:** dùng quy trình chấm/lọc và LLM dự phòng ở mục 4 cho
tag suy nghĩ, nhưng thay danh sách tag, hướng dẫn chấm, K và điểm sàn phù hợp.
Nếu sau fallback vẫn không có tag, phân loại theo mục 4.5 và không gọi B3.

Lưu tag suy nghĩ trước khi gọi B3. Không sinh suy nghĩ sau khi đã biết kết
quả mua để giải thích ngược cho quyết định.

### B3. Mua hoặc không mua

**Câu hỏi:** “Sau khi chú ý và nêu suy nghĩ về món hàng, bạn có mua món này ngay trong lượt này không?”

**Context policy v1:**

- Flow vừa chú ý và nêu suy nghĩ về món hàng, đang quyết định mua.
- Tag suy nghĩ được giữ từ B2.
- Danh tính brand/shop và thông tin công khai liên quan đã được mapping.
- Thông tin sản phẩm cần cho quyết định: sản phẩm nào, giá, điều kiện đang áp
  dụng và shop/brand cung cấp.
- Lịch sử mua/không mua và suy nghĩ trước đó của đúng sản phẩm, có phân biệt
  với suy nghĩ hiện tại.

Không đưa lại toàn bộ persona hoặc lịch sử toàn chiến dịch.

**Kết quả:** nếu chưa từng mua, contract dùng đúng một trong hai action
`buy`, `not_buy`; nếu đã từng mua, contract dùng `buy_again` hoặc
`not_buy_again`. Đây chỉ là thay đổi danh sách đáp án theo context lịch sử,
không tạo action thứ ba. Số lần mua lại do hệ thống tính từ event hợp lệ.

- Cả hai được lưu và liên kết với bộ tag B2 đã có trước quyết định.
- “Muốn thử lần sau” là tag suy nghĩ, không phải action thứ ba.
- Bỏ qua B1 hoặc lỗi ở B2/B3 không được đổi thành `not_buy`.
- Không dùng ngưỡng cảm xúc hay điểm chú ý để ghi đè action hợp lệ.
- Sau action, không gọi model phân tích lại khả năng sản phẩm có “tiềm năng mua”.
  Các lần sau sử dụng trực tiếp lịch sử và policy đã định nghĩa.

V1 xét từng sản phẩm, mỗi sản phẩm có thể tạo một quyết định mua trong lượt
ghé. Hết danh sách thì kết thúc lượt; không tự thêm giới hạn số món,
giỏ hàng, số lượng đơn vị hay thanh toán.

## 7. Dữ liệu cần giữ để theo dõi lại diễn biến

Mỗi bước giữ đúng phạm vi campaign, scenario, run, session, agent, bài viết,
shop, sản phẩm và brand khi áp dụng. Không trộn lịch sử giữa các lần chạy.

Với bước chấm tag, lưu:

- Context được dùng và mốc lịch sử.
- Danh mục/phiên bản tag, hướng dẫn thang điểm.
- Model được gọi; đầu ra gốc và kết quả kiểm tra.
- Điểm chuẩn hóa, K, điểm sàn, các tag được chọn.
- Có gọi LLM dự phòng không, vì sao và kết quả thế nào.

Với bước hành động, lưu lựa chọn, sự kiện liên quan và trạng thái trước/sau
nếu có thay đổi. Đếm lại số lần từ sự kiện, không từ câu mô tả của model.

Nội dung quảng cáo là dữ liệu để đánh giá, không phải hướng dẫn được phép
thay đổi danh sách đáp án hoặc quy tắc hệ thống.

## 8. Tình huống dùng để review luồng

1. Agent bỏ qua bài: không có cảm xúc sau đọc hoặc phản ứng được tạo thêm.
2. A2 không có tag đạt sàn: gọi LLM chấm lại; chỉ tiếp tục khi có kết quả hợp lệ.
3. A2 có tag nhưng A3 không có: dự phòng tại A3, không lấy tag A2 giả làm cảm
   xúc sau đọc.
4. Cả hai model hợp lệ nhưng dưới sàn: lưu `empty_result`, không gọi bước phụ thuộc và
   không tự thêm `emotion.indifference`.
5. Agent đọc lại bài đã like: có thể `keep_current`, `remove_reaction` hoặc
   `no_new_reaction`; không bắt buộc đổi sang dislike.
6. Agent từng ghé shop qua bài khác: không mô tả lượt ghé hiện tại là lần đầu.
7. Agent vào shop nhưng không chú ý sản phẩm nào: không phát sinh `not_buy`.
8. B2 có `thought.consider_later`, B3 trả `not_buy`: lưu cả tag lẫn action;
   không sinh thêm nhãn sau quyết định.
9. Agent từng mua món P nhưng lượt gần nhất không mua: lịch sử vẫn cho biết
   đã từng mua P; không bị mất chỉ vì action gần nhất là `not_buy`.

## 9. Phần triển khai và hiệu chỉnh còn lại

- Vị trí và contract của comment khi tính năng này được đưa vào lại.
- Kiểm chứng ngưỡng bằng bài quảng cáo/catalog đã xác nhận.
- Engine, database transaction và tích hợp LLM fallback.
- Renderer cho ký ức mua/cân nhắc liên bước ở B1/B2 theo FRD-05.

“Không ghé lại” chỉ áp dụng lượt hiện tại. Thứ tự sản phẩm ổn định theo ID;
lịch sử ảnh hưởng qua context, không cộng/trừ score. Policy offline và schema
đã có; không coi các probe API là simulation engine.
