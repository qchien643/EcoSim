# API, SSE và báo cáo

## 1. Contract HTTP

[openapi.yaml](openapi.yaml) là contract OpenAPI 3.1 được API phục vụ tại
`/openapi.json`. `backend.api.self_check` kiểm tra request/response thực tế của
35 operation bằng TestClient và SQLite file tạm. API prefix `/api/v1`.
Định danh resource do server sinh, trừ ID đối tượng cục bộ marketer có thể
đặt để liên kết lịch; ID đều kiểm tra slug an toàn.

Không có endpoint login/member/organization-owner. Organization/brand nằm
trong `ScenarioSetup`. Chưa có bảo vệ tenant: chỉ bind local hoặc mạng nội bộ
tin cậy, không expose public khi chưa có lớp truy cập riêng.

| Bước màn hình | API |
| --- | --- |
| Chọn ngành, xem từ điển `!` | GET industries, industry bundle |
| Tạo từ mẫu | GET scenario templates; POST instantiate template |
| Tạo nội dung muốn truyền tải | POST campaigns; GET/PUT campaign |
| Tạo scenario, setup doanh nghiệp/brand/shop/bài/lịch | POST campaign scenarios; GET/PUT scenario |
| Xem nguồn/cohort và persona trước mô phỏng | GET datasets, cohorts, cohort members |
| Kiểm tra và xem phân bổ người tham gia | POST scenario validate; GET scenario participants |
| Chốt cấu hình | POST scenario freeze |
| Chuẩn bị lần chạy | POST scenario runs → run ready, chưa gọi model |
| Chạy hoặc chạy tiếp | POST run start/resume → 202 |
| Mở màn hình đang chạy | GET run, objects, agents, sessions; SSE run stream |
| Xem kết quả/line chart | GET metric definitions, metrics, report |
| Xem một agent nghĩ/làm gì | GET agent history theo phiên/đối tượng/stage |
| Tải cấu hình của một lần chạy | GET `/runs/{run_id}/configuration` → file JSON |

MVP setup dùng **PUT toàn bộ ScenarioSetup**, chưa thêm CRUD cho từng tag,
sản phẩm hay lịch. Form giữ local state và gửi lại setup, `expected_revision`
để chống ghi đè từ tab khác. Draft chấp nhận thiếu các phần; freeze mới bắt
buộc đầy đủ. PUT không xóa history hoặc sửa scenario ready.
Đây là lựa chọn ít endpoint nhất đủ các màn hình đã yêu cầu.

`validate` chỉ đọc/kiểm tra, không khóa, không gọi model; có danh sách
`issues[path,code,message,severity]` và `group_counts`; danh sách người tham gia
đọc qua endpoint `participants`.
`participants` phân trang, preview dùng đúng thuật toán selection/assignment
và revision hiện tại. Freeze thực hiện lại kiểm tra trong revision lock.
Nếu N/profile/cohort thay đổi, phải xác nhận lại nhóm/persona trước freeze.

Error envelope thống nhất `error.code/message/fields/retryable`.
400 query/cursor sai; 404 resource không tồn tại; 409 revision/status/busy/
idempotency conflict; 422 dữ liệu không hợp lệ; 503 worker chưa khả dụng.
Validation report trả 200 với `valid=false`, không nhầm với lỗi HTTP.
Các request-body schema từ chối unknown fields.

Create run, start, resume yêu cầu `Idempotency-Key` 1–128 ký tự. Cùng key và
payload trả lại cùng kết quả, không tạo run hoặc gọi model lần hai. Khác
payload trả 409. Khóa lưu cùng transaction của command. Status trả từ
command đã replay có thể cũ; frontend đọc GET run để lấy hiện tại.
PUT/freeze dùng expected_revision; freeze lại cùng revision đã ready trả
cùng scenario. Không hỗ trợ đổi mode/batch/provider khi resume; tạo run mới.

Danh sách phân trang `limit=50`, tối đa 200, cursor opaque ràng buộc resource/
filter; không dùng offset cho event stream. Response `items,next_cursor`;
cursor hết hạn/sai không âm thầm bỏ qua dữ liệu.

### Mẫu chiến dịch để thử trên web

Mẫu hư cấu nằm trong `data/scenario_templates/{industry}/`, không phải bản
nháp dùng chung trong SQLite. Mẫu gồm metadata, `CampaignInput` mặc định và
`ScenarioSetup`; chỉ tham chiếu cohort đã chuẩn bị, không chứa raw persona.

- `GET /api/v1/scenario-templates`: danh sách và quy mô.
- `GET /api/v1/scenario-templates/{template_id}`: nội dung mẫu.
- `POST /api/v1/scenario-templates/{template_id}/instantiate`: nhận
  `{campaign: CampaignInput, scenario_name: string}` và `Idempotency-Key`,
  trả `{campaign_id, scenario_id}`.

Backend đổi ID organization/brand/shop/post/product/group và toàn bộ
references, tạo campaign + scenario draft, validate dữ liệu ngành/cohort
trong một transaction. Lỗi rollback cả hai; không ghi đè bản cũ. Retry cùng
key/payload trả lại cùng IDs, khác payload trả 409. Thiếu dữ liệu nền trả
422; xem hướng dẫn bootstrap. Không freeze, tạo run hoặc gọi model.

Mỗi bản nháp chỉnh qua PUT hiện có. Mẫu gốc không thay đổi. Chưa có import,
lưu mẫu của người dùng hoặc clone một scenario bất kỳ. Không cần migration
database. Khi sửa nội dung mẫu chuẩn, tạo template ID/version mới.

Kiểm tra riêng: `.venv/bin/python -m backend.templates_self_check` từ
`ecoSim`; đã được gọi trong `backend.api.self_check`.

### Xuất cấu hình của lần mô phỏng

`GET /api/v1/runs/{run_id}/configuration` trả file UTF-8
`ecosim-run-configuration.json` với `Content-Disposition: attachment`,
`Cache-Control: no-store`. Run không tồn tại trả 404; không cần run hoàn thành.

File gồm `format_version`, `snapshot_hash` và `input_snapshot`: campaign tại
thời điểm chốt, doanh nghiệp/shop, sản phẩm và giá/tag, bài viết, lịch đăng,
persona đã chọn từ cohort có sẵn, seeds/cơ cấu, bundle ngành và chế độ chạy.
Luôn lấy snapshot của run, không đọc lại draft hoặc campaign hiện hành.
Hash là của frozen scenario snapshot (bỏ `run_id` và `execution` khỏi
`input_snapshot` để đối chiếu), không phải hash toàn bộ file tải về.

Không xuất API key, biến môi trường, lịch sử hay metrics. File có thông tin
persona và ghi chú chiến dịch: chỉ chia sẻ trong phạm vi được phép. Không
bao gồm phản hồi model hoặc bảo đảm kết quả model giống nhau khi chạy lại.
Đây là API xuất cấu hình, **không bổ sung upload/import persona**; cũng
chưa có API nhập file export. Muốn chạy lại vẫn tạo run từ scenario đã khóa.

Ví dụ, khi server dùng đúng database chứa run:

```bash
curl --fail --show-error \
  http://127.0.0.1:8000/api/v1/runs/run_8925979a5efa/configuration \
  --output run_8925979a5efa.configuration.json
```

Kiểm thử không gọi model: `.venv/bin/python -m backend.api.self_check`.

## 2. Metric và lịch sử: dữ liệu trả về

Metric chính thức theo `(run, session, scope, metric, calculation_version)`.
Scope MVP: run, article, shop, product. Không cần lưu report JSON trùng:
report dựng từ run snapshot, metric snapshots, model_calls và tiến độ.

| Nhóm | Định nghĩa |
| --- | --- |
| Bài viết | exposed = A1 đã ghi; attended = A1 resolved attend/attend_again; read/view = A3 resolved |
| Phản ứng | likes_added/dislikes_added đếm action mới; current_likes/current_dislikes là trạng thái cuối phiên, không cộng lũy kế |
| Cửa hàng | visits = A5 resolved visit/visit_again của bài thuộc shop; product counts cộng trong đúng shop |
| Sản phẩm | exposed = B1; view/attended = B1 resolved attend/attend_again; buys và not_buys = B3 resolved tương ứng |
| Chất lượng xử lý | Counts từng stage/status, empty_result, unresolved, selected tags, nguồn JEV/fallback |
| Tiến độ | agents_completed từ agent_sessions; active_count từ snapshot; không đếm số agent có event |
| Token | Tổng provider-reported input/output/total tokens qua **tất cả HTTP attempts**, kể cả lỗi hoặc chưa sinh event |

Tỷ lệ giữ tử số/mẫu số: attention/`A1.resolved`; read/attended;
visits/`A5.resolved`; product_attention/`B1.resolved`; buys/`B3.resolved`.
Mẫu số 0 → null, không 0%. Lũy kế rate tính từ tổng tử/mẫu, không trung bình
các rate phiên. Scope article không có purchase_rate mặc định; không tự
suy ra attribution mua hàng cho bài, doanh thu hay độ chính xác dự đoán.

Scope bài lọc article events đúng ID; scope product lọc product events;
scope shop ghép A5 của bài thuộc shop và B-events của sản phẩm thuộc shop.
Metric không áp dụng không trả như số 0. Phiên rỗng: counter 0, current
reactions giữ state trước, rate null nếu mẫu số 0. Objects chưa có exposure
vẫn có điểm 0 cho applicable counts ở các phiên completed.

Mỗi MetricPoint có `session_value`, `cumulative_value`, numerator/denominator,
version và watermark. UI chọn linechart theo phiên/lũy kế, state metric không
cộng hai lần. Rebuild cùng events và version phải giữ nguyên kết quả.

History trả tất cả processing records đã commit, kể cả session chưa xong;
có status phiên, event cha, stage, action, selected/all scored tags và
description snapshot. Filter mặc định tags selected; `include_all_scores`
cho audit. Không trả raw prompt, secrets hay tạo lời tự sự bằng LLM.
Chatbot tương lai đọc lịch sử này, không cần bổ sung “suy nghĩ” bịa.

Usage thiếu từ provider → null và usage_missing_attempts, không báo 0 token.
Report có tổng token đã biết và mức bao phủ. Chi phí tiền chỉ hiển thị nếu
có nguồn pricing xác nhận; MVP tập trung token, không suy đoán giá.
Benchmark Persona–Behavior Alignment là công cụ đánh giá riêng, không trộn
với metric campaign hay tự chạy judge trả phí khi mở report.

## 3. SSE theo dữ liệu đã commit

```mermaid
sequenceDiagram
    participant W as Writer SQLite
    participant R as Read API / SSE
    participant F as Frontend
    W->>W: Commit event + state + checkpoint + run_update
    R->>W: Đọc batch theo cursor bằng connection đọc ngắn
    W-->>R: Chỉ dữ liệu đã commit
    R-->>F: progress_batch
    F->>F: Counter từ backend; diễn biến vào FIFO
    W->>W: Commit metric + session completed + update
    R-->>F: session_completed
    W->>W: Commit run completed + update
    R-->>F: run_completed, ưu tiên hơn replay backlog
    F->>F: Bỏ hoạt cảnh chờ; đọc report chính thức
```

Endpoint `GET /runs/{run_id}/stream?after=...` trả `text/event-stream`.
Wire message có `id:` là cursor, `event:` là type, `data:` JSON theo
StreamMessage. Heartbeat là comment `: heartbeat`, không tăng cursor.
Headers: Cache-Control no-cache và tắt proxy buffering khi proxy hỗ trợ;
không yêu cầu header Connection cho mọi phiên bản HTTP.

Cursor v1 encode `{run_id,commit_seq}`, server kiểm tra run và watermark;
client coi opaque. `Last-Event-ID` nếu có được ưu tiên hơn query after khi
reconnect. Cursor vượt hiện tại/sai run → 400 trước khi mở stream.
Không truyền credential qua query. Cursor giữ được suốt thời gian lưu run.

Implementation dùng base64 của binding resource/filter và khóa cuối trang.
Cursor stream ràng buộc run và `commit_seq`; history ràng buộc thêm agent
và bộ lọc. Cursor là vị trí đọc, không phải token xác thực. Polling dùng
`next_cursor` là cursor cuối batch đã trả, không lấy watermark mới nhất để
bỏ qua các event chưa gửi. Với terminal/reset, việc nhảy watermark có
`resync_required=true` rõ ràng.

Các loại message:

| Type | Dữ liệu |
| --- | --- |
| `run_started` | Status running, execution_epoch, progress, cursor |
| `progress_batch` | Tối đa 100 stage events cùng session, cursor cuối, provisional counters |
| `session_completed` | session_no, metrics_ready=true, calculation_version, metrics watermark |
| `run_completed` | Status completed, report_ready=true, latest completed session, cursor |
| `run_failed` | Status failed, sanitized failure_code, kết quả các phiên đã hoàn tất, cursor |
| `reset` | Reconnect quá xa: yêu cầu tải snapshot hiển thị, không có nghĩa mất history |

Message type ở API là projection từ `run_updates`, không cần lưu nguyên
batch serialized. Tối đa 100 updates/batch hoặc mỗi 250ms, heartbeat 15s;
đây là mặc định vận hành có thể tuning, không phải thời gian phiên mô phỏng.
Read/publish loop không nằm trên call stack stage và không tạo network
request mỗi commit. Live counters là deterministic projection tạm theo
watermark và có scope; chưa phải metric chính thức cuối phiên.

`progress` đính kèm batch là snapshot hiện tại, có `progress.cursor` riêng;
nó có thể mới hơn các event đang replay. UI **replace** counter từ snapshot,
không cộng lại event và không dùng `progress.cursor` thay cursor batch khi
cần đọc tiếp hoạt cảnh. `/progress` đọc status/counter/cursor trong cùng
WAL read transaction. Mỗi request có connection riêng, không giữ writer lock.

### Không mất event, không bị kẹt terminal

- Ghi run_update trong cùng transaction sự thật: crash sau commit/trước gửi
  vẫn đọc lại được. Delivery có thể trùng; client khử trùng event_id/cursor.
- SSE luôn kiểm tra **trạng thái hiện tại trước khi drain backlog**.
  Nếu terminal, gửi terminal ngay kèm cursor hiện tại; không bắt phát hết
  stage backlog. Ghi rõ `resync_required=true`; frontend tải report/history.
  Đây là bỏ replay trực tiếp có chủ đích, không xóa event.
- Với run còn chạy và backlog >1.000 updates, gửi `reset` tới watermark mới.
  Frontend tải GET progress (counter + cursor nhất quán), bỏ FIFO cũ rồi nối
  stream từ cursor snapshot. Event commit sau snapshot được đọc bù.
- GET progress lấy status/counters/cursor trong cùng read snapshot; không
  đọc counter cũ rồi cursor mới dẫn tới thiếu cập nhật.
- Hiện tại generator chỉ giữ một batch hữu hạn, tối đa 100 updates/lần đọc,
  không nằm trên writer. Write timeout 5s và thử nghiệm slow-client/proxy
  là mục tiêu vận hành **chưa triển khai/xác minh**, không coi self-check
  TestClient là chứng nhận backpressure ngoài mạng.
- Run terminal đã được client biết và cursor bằng terminal watermark:
  request stream mới trả 204. Frontend chủ động đóng EventSource khi nhận
  terminal. Resume mở connection mới từ progress snapshot epoch mới.
- Cursor trước `run_started` của lần resume nhận `reset` ở epoch hiện tại;
  không replay `run_failed` của epoch cũ khiến UI kết thúc nhầm.
- Network disconnect không đồng nghĩa failed. GET run/progress là phương
  án kiểm tra trạng thái nếu mất stream.

Frontend FIFO tối đa 500 item; gom chỉ khi cùng session/agent/object/
encounter. Không chờ FIFO để xử lý run terminal. Counter **replace từ snapshot
backend**, không cộng dựa hoạt cảnh. Không cùng lúc cộng event và replace
metric gây double-count. Nội dung UI chỉ ghép action/tag đã lưu.

Polling dự phòng `GET /runs/{id}/updates?after=&limit=` đọc cùng run_updates,
cùng message contract; GET progress/status dùng khi cần resync. Poll mỗi
1 giây khi mất SSE là mặc định MVP, không chạy cả hai subscription cùng lúc.
Event lịch sử đầy đủ đọc bằng history endpoint, không dùng SSE làm kho audit.

## 4. Chuẩn tham chiếu và giới hạn xác minh

Contract nhắm OpenAPI 3.1.1 và cơ chế EventSource/SSE. Đường dẫn tham chiếu:

```text
https://spec.openapis.org/oas/v3.1.1.html
https://html.spec.whatwg.org/multipage/server-sent-events.html
```

Tra cứu web trong lượt soạn không trả nội dung khả dụng; không coi tài liệu
này là xác nhận tính tương thích của một phiên bản framework/provider cụ thể.
Kiểm tra schema offline và integration SSE thật là hai cổng nghiệm thu riêng.
