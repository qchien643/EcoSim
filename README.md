# ecoSim

ecoSim là nguyên mẫu nghiên cứu mô phỏng phản ứng của người dùng ảo trước
chiến dịch marketing: chú ý, đọc bài, phản ứng, ghé cửa hàng và mua hoặc không
mua. MVP tập trung vào ngành cà phê. **Mô hình ra quyết định** là trọng tâm:
context theo từng bước -> model trả kết quả có cấu trúc -> quy tắc chuyển trạng
thái -> ghi sự kiện -> tính chỉ số. Kết quả mô phỏng không phải dự báo hành vi
người thật đã được xác thực.

## Trạng thái

Backend MVP đã có FastAPI, runtime sequential/parallel và SQLite dùng chung.
Nguồn thiết kế chính thức là `docs/backend/`; runtime không gọi engine cũ.
Các operation HTTP có kiểm tra offline bằng TestClient. Điều này chưa
chứng nhận tải provider thật hoặc độ chính xác dự báo của mô phỏng.

## Cấu trúc thực tế

| Đường dẫn | Nội dung |
| --- | --- |
| `docs/srs/` | Yêu cầu sản phẩm |
| `docs/frd/` | Nghiệp vụ và luồng chức năng |
| `docs/technical/services/` | Thiết kế trách nhiệm từng service |
| `docs/technical/` | Context, policy, contract, ERD và đánh giá runtime |
| `docs/frontend/` | Wireframe và yêu cầu trình bày mô phỏng |
| `data/tags/` | Từ điển tag JSON và mapping persona |
| `data/contracts/` | Schema, contract và policy |
| `data/industries/` | Profile ngành có version |
| `data/matraix/` | Schema/metadata được chọn; dữ liệu nguồn tải riêng |
| `data/personas/` | Cohort persona cục bộ, không đưa lên Git |
| `data/scenarios/` | Kịch bản cục bộ, không đưa lên Git |
| `data/scenario_templates/` | Mẫu hư cấu bất biến để tạo campaign và scenario nháp trên web |
| `simulation/` | Context, quyết định, thực thi, chỉ số và persona |
| `paper_research/` | Paper, công cụ chuẩn bị persona, validator và benchmark |
| `experiments/` | Script thử nghiệm, log và database các lần chạy |
| `frontend/` | React + Vite mới, kết nối API setup/live/results |
| `backend/` | SQLite backend-v2, lifecycle, HTTP/stream và self-check |
| `DESIGN.md` | Quy chuẩn giao diện |
| `requirements.txt` | Dependency đã khai báo |

Các file cũ vẫn được giữ để truy vết; không phải mọi bản thiết kế/tag trong
thư mục đều đang được dùng. Bộ tag hiện được runtime tham chiếu là
`data/tags/agent_flow_tags.v2.json`, mapping là
`data/tags/agent_flow_tag_persona.mapping.v2.json`.

## Điểm bắt đầu đọc

- [Khởi động backend và frontend từng bước](KHOI-DONG.md)
- [Bản đồ tài liệu](docs/README.md)
- [Dữ liệu và luồng quyết định (giải thích)](docs/ECOSIM_DATA_AND_DECISION_MODEL.md)
- [Sơ đồ quyết định của agent (HTML)](docs/ecosim-agent-decision-workflow.html)
- [Sơ đồ kiến trúc (HTML)](docs/ecosim-decision-architecture.html)
- [Thiết kế các service](docs/technical/services/README.md)
- [Thiết kế backend source of truth](docs/backend/README.md)
- [Luồng agent](docs/technical/luong-agent-jev-va-llm.md)
- [Trạng thái triển khai và giới hạn kiểm thử](docs/backend/04-delivery-and-checks.md)
- [Wireframe React + Vite MVP](docs/frontend/04-wireframes-react-vite-mvp.md)
- [Chạy và kiểm thử frontend](frontend/README.md)

## Làm việc từ ecoSim

Chạy các lệnh từ thư mục này:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m backend.self_check
.venv/bin/python -m simulation.execution.regression_check
.venv/bin/python -m gateways.openai
.venv/bin/python docs/backend/check_contract.py
cd frontend && npm ci && npm test && npm run build
```

Đây là kiểm thử offline. Không tự chạy các probe trả phí.

**Bản clone GitHub không kèm cohort, Parquet hoặc SQLite.** Các lệnh kiểm tra
trong khối trên dùng fixture nhỏ và không cần key/dataset thật; riêng
`backend.api.self_check`, `backend.bootstrap_self_check` và sử dụng giao diện
với người tham gia cần cohort đã chuẩn bị, tuân thủ điều khoản nguồn. Đọc
[dữ liệu cần chuẩn bị](data/README.md) trước khi nạp:

```bash
.venv/bin/python -m backend.bootstrap
```

Lệnh nạp bundle cafe, metadata MatrAIx và cohort 100 persona **nếu đã đặt**
`data/personas/cafe_mvp/manifest.json` và `cohort.jsonl` hợp lệ. Thiếu cohort
thì lệnh dừng, không tự tải hay tự tạo persona. Chạy lại cùng dữ liệu không
tạo trùng; dữ liệu đổi cùng ID bị từ chối. Không gọi model hoặc đọc Parquet.
Xem [hướng dẫn nạp dữ liệu](docs/backend/06-bootstrap.md).

Sau bootstrap, trên trang đầu chọn **Tạo từ mẫu → Mộc — Cà phê mỗi ngày → Dùng
mẫu này** để lấy bản nháp 12 người, 3 phiên, 3 bài viết và 4 sản phẩm.
Template không thay thế cohort và chưa gọi model.

Chạy HTTP cục bộ (một worker):

```bash
.venv/bin/uvicorn backend.api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

`ECOSIM_DATABASE` chọn file SQLite backend mới; mặc định
`data/ecosim-backend.sqlite`. Không trỏ vào database experiment cũ.
Mở `/docs` để xem contract API; start/resume mới gọi model và có thể phát
sinh phí. Snapshot, stage events, metrics và lịch sử dùng chung backend DB.

## Đường dẫn tương thích và dữ liệu riêng

Các thư mục cùng tên ở cấp cha là symbolic link về đây, không phải bản sao.
Chúng giữ đường dẫn cũ cho script, tài liệu và snapshot đã lưu. Code và dữ
liệu thực nằm trong `ecoSim/`; chỉnh sửa tại đây.

Ở checkout hiện tại, `.env` là liên kết tới `.env` cấp cha; bản clone độc lập
hãy tạo `.env` từ `.env.example` (không commit key). Dữ liệu nguồn, cohort,
database, log thử nghiệm và file cấu hình riêng không được đưa lên Git.

`paper_research/` và `experiments/` dành cho chuẩn bị dữ liệu/benchmark.
Runtime mới dùng `simulation/context`, `decision`, `execution`, `metrics`,
`personas` và `gateways`; không import `simulation/legacy`.

## Trước khi công khai trên GitHub

Khởi tạo Git tại **thư mục `ecoSim/`**, không phải thư mục cha chứa các
symbolic link. Kiểm tra `git status --short` và `git diff --cached --stat`
trước khi commit; không dùng `git add -f` với file dữ liệu. `.gitignore` bỏ
qua key, cohort, SQLite, dataset, log và PDF bên thứ ba, nhưng không bảo vệ
các file đã từng được Git theo dõi. Hiện chưa có giấy phép mã nguồn được chọn;
chủ dự án cần quyết định LICENSE và quyền sử dụng dữ liệu trước khi phát hành.
