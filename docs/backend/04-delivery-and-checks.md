# Triển khai, vận hành và nghiệm thu

## 1. Code hiện tại so với đích

| Phần | Có hiện tại | Công việc mục tiêu |
| --- | --- | --- |
| MatrAIx | Decoder/projector/completion/cohort JSONL; `backend.bootstrap` nhập metadata/cohort vào SQLite | Xác minh lại raw shard riêng khi thay release nguồn |
| Ngành | Cafe bundle, hash checks | Dependency injection bundle cho validator/context/gateway/policy |
| Chuẩn bị | Loader JSON có validation | Campaign/scenario persistence, draft/revision/freeze, HTTP |
| Run | Sequential/parallel batches, checkpoints, shared backend snapshot | Agent-session completion, recovery, single-writer publication |
| Stage | JEV + OpenAI fallback, context/policy, attempt audit, bounded transport retry | Live latency/rate-limit calibration |
| History | Event/tag/context/state | Run-scoped keys, ordered updates, raw audit nội bộ |
| Metrics | Snapshot run/article/shop/product; read API; usage theo phiên từ model_calls | Calibration/load test; thống kê riêng từng HTTP retry bên trong provider |
| Frontend | Prototype dữ liệu tĩnh | SSE contract, progress/read models; chưa implement UI ở đợt này |

Runtime production không import `paper_research` hoặc `experiments`. Các script
nghiên cứu cũ vẫn có thể tham chiếu fixture/legacy store và không phải đường
chạy backend mới.

## 2. Thứ tự triển khai

1. Tạo schema SQLite mục tiêu, constraints và transaction test. Không cần
   tương thích database run thử cũ; không tự xóa dữ liệu đó.
2. Persona/catalog bundle ingestion + campaign/scenario draft/freeze. **Đã có
   persistence v1.**
3. Materialization run atomic + ownership khóa theo run, không tenant. **Đã có
   snapshot và idempotency.**
4. Nối stage/context/policy/gateway vào persistence mới; bounded retry,
   fallback, resume, rollback và sequential/parallel parity. **Đã triển khai.**
5. Metric scope + usage + history/progress/update read models. **Đã triển khai.**
6. FastAPI/OpenAPI và SSE. **Đã kiểm tra 35 operation HTTP bằng TestClient
   trong uv venv**, gồm history phân trang, scope metric, terminal backlog,
   resume/reset, reconnect/204 và error envelope.

Mỗi mốc chạy offline với fixture nhỏ trước. Live model chỉ chạy khi người
dùng yêu cầu rõ, có giới hạn agent/phiên/request; không nằm trong CI.

## 3. Ma trận nghiệm thu bắt buộc

| Case | Kết quả phải đạt |
| --- | --- |
| Dataset thiếu shard/hash sai/import gián đoạn | Không có cohort ready dùng được |
| Enum thiếu/override ngoài schema | Giữ provenance, từ chối hoặc xử lý theo policy rõ ràng |
| Cùng seed/cohort/profile | Cùng persona và nhóm; N vượt size bị chặn |
| Organization/brand khác giữa scenario | Context dùng đúng snapshot, không có phép kiểm tra membership |
| Hai scenario cùng post/product IDs | Không xung đột hoặc đọc nhầm dữ liệu |
| Sửa draft từ hai tab | expected_revision cũ trả 409 |
| Sửa campaign/scenario sau freeze | Run cũ và scenario frozen không đổi |
| Lỗi giữa materialization | Rollback run và toàn bộ con; không completed rỗng |
| Double-click start/resume | Một command, không gọi model trùng do HTTP retry |
| Hai start cho hai run đồng thời | Chỉ một running; yêu cầu còn lại 409 |
| Agent inactive/phiên không bài | Không gọi model; completion và metric đúng |
| Bài có lịch ở phiên 1, vắng phiên 2 | Phiên 2 không tự xét lại |
| A1/B1 trước/sau mua, attention skip | Memory đúng stage/object, lý do skip lưu riêng |
| A3 | Nhận nội dung đầy đủ; A1/A2 không nhận |
| Score đúng sàn/hòa/NaN/thiếu tag | Cùng policy deterministic, không tag tự bịa |
| Business tag sai `source_ref`/visibility | Freeze bị từ chối trước khi chạy model |
| JEV below-floor/invalid/timeout + mọi fallback outcomes | Đúng resolved/empty_result/unresolved; không action giả |
| DB error khi commit tag/state/checkpoint | Không có event nửa vời hoặc SSE ma |
| Crash trước/sau model response, trước/sau event commit | Resume không trùng event, reuse output đã lưu nếu hợp lệ |
| 4 agent sequential và parallel batch 4 | Scripted outputs cho cùng history/metric; thứ tự giữa agent có thể khác |
| Worker lỗi trong batch | Không phiên tiếp; drain an toàn; không event sau failed |
| Cùng event rebuild metrics hai lần | Không double-count; run/object/session đồng nhất |
| Like giữ/bỏ, not_buy, sản phẩm chưa từng xét | State/counter/rate đúng, denominator=0 trả null |
| Provider thiếu token hoặc request lỗi chưa có event | Coverage rõ; không bỏ attempt hoặc coi unknown=0 |
| SSE ngắt giữa batch, duplicate delivery | Cursor đọc bù, UI dedup |
| Stage/session commit rồi process crash trước publish | Update vẫn đọc được |
| Terminal sau backlog lớn | UI kết thúc ngay khi nhận, resync report; không chờ FIFO |
| Resume sau failed | Epoch mới; stream không replay failed cũ để kết thúc run mới |
| Client chậm/ngắt/tab đóng | Engine tiếp tục, bounded buffer không tăng vô hạn |
| Backup/restore | DB integrity/FK, snapshot và history đọc được, restore không tự chạy phí |

Checker tài liệu chạy từ `ecoSim`:

```bash
python3 docs/backend/check_contract.py
```

Checker trên chỉ kiểm tra tài liệu. Integration check thực tế, không trả phí:

```bash
.venv/bin/python -m backend.api.self_check
.venv/bin/python -m backend.bootstrap_self_check
.venv/bin/python -m backend.self_check
.venv/bin/python -m simulation.execution.regression_check
.venv/bin/python -m gateways.openai
```

HTTP check dùng gateway scripted, database file tạm, không đọc key hoặc gọi
model thật. Nó xác minh 31 operation, shape theo OpenAPI, filter/cursor,
cohort/relationship preview, metric từng đối tượng, rebuild, history/tag,
report usage, parallel readers và WAL snapshot nhất quán. Không phải test
độ chính xác mô phỏng hay tải 100 agent với provider thật.

Giới hạn còn lại: chưa test slow-client/proxy SSE hay timeout gửi 5 giây;
history/progress vẫn đọc event prefix, cần đo tải trước khi thêm accumulator.
`model_calls` đếm attempt cấp gateway; retry HTTP ẩn trong transport/SDK chưa
được ghi thành từng dòng riêng nên không khẳng định token bao phủ các retry đó.
Bundle MVP chưa khai báo object extensions thì `industry_data` không được có
key tùy ý. Chưa thay đổi schema SQLite và không migrate database thử cũ.

## 4. Vận hành tối thiểu

- Không cài framework/dependency mới trong lượt chỉ viết thiết kế.
  Khi implement pin versions được kiểm tra; FastAPI/Pydantic dùng API schema
  đúng contract, sqlite3 làm persistence, chưa cần ORM.
- Key/model server config đọc từ môi trường; snapshot chỉ lưu model/provider,
  timeout/policy/version, tuyệt đối không lưu key. Kiểm tra config trước start.
- Giới hạn MVP mới: 1–100 agent/run, 1–20 phiên, tối đa 50 bài và 50 sản phẩm,
  batch 1–8; đây là safety limits ban đầu, tăng sau khi đo tải. Không công bố
  là kết quả load-test. HTTP body tối đa 2 MiB, text field tối đa 20.000 ký tự.
- Log có run/session/agent/stage/call_id và mã lỗi, không raw key. Raw
  request/response được redact, chỉ đọc nội bộ admin; public API trả normalized
  history. Không ghi full prompt vào application log.
- SQLite một writer, WAL, FK, busy timeout hữu hạn. Migration đánh số và chạy
  offline trước startup; lỗi migration thì không nhận run mới.
- Backup bằng SQLite backup API, không copy riêng file `.sqlite` khi WAL còn
  đang ghi. Sao lưu bundle/cohort metadata cùng version; secrets quản lý riêng.
  Backup trước migration và sau đợt thử có giá trị; kiểm tra restore vào path
  tạm, không overwrite database đang dùng.
- MVP giữ history/context/attempt của run cho tới khi người dùng yêu cầu xóa;
  chưa auto-cleanup. Cảnh báo dung lượng, không nhận run mới nếu storage không
  đủ để lưu an toàn; không tiếp tục mô phỏng khi persist thất bại.
- Manifest nguồn hiện có usage notice hạn chế sử dụng; lưu notice/revision
  cùng dataset, cần xác nhận quyền riêng trước phát hành thương mại. Đây là
  yêu cầu quản trị nguồn, không suy ra quyền từ nhãn “synthetic”.

## 5. Những gì không được tuyên bố

Self-check qua không chứng minh dự báo tương lai. Score [0,1] không tự là
xác suất hành vi đã calibration. LLM judge alignment không phải ground truth.
Snapshot/seed bảo đảm đầu vào và policy tái lập, không bảo đảm model live
trả cùng output. SSE realtime không làm thay đổi đơn vị thời gian của phiên.
