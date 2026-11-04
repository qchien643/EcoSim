# Wireframe frontend React + Vite — MVP

## Trạng thái triển khai

Frontend mới nằm ở `../../frontend`, hướng dẫn chạy tại
[frontend/README.md](../../frontend/README.md). Các wireframe 01–03 và dashboard
HTML cũ đã được đưa ra khỏi dự án theo yêu cầu, không dùng làm nguồn thiết kế.
Ứng dụng dùng React + Vite, CSS theo `DESIGN.md`, Lucide và API hiện tại.
Các route trong bảng dưới được triển khai dưới dạng hash (`/#/...`) để
không cần server rewrite. Không thêm query client/router/chart dependency.
Các tab kết quả bài/cửa hàng/agent dùng chọn đối tượng trong cùng trang.

Phân biệt hai trạng thái: scenario chỉ `draft/ready`, run là
`ready/running/completed/failed`. Scenario khóa ngay khi freeze, chưa cần
start run. Nhóm quan hệ là tổ hợp bốn chiều, không cộng “chưa biết”,
“trung lập” và “đã mua” như ba chiều loại trừ độc lập.

## 1. Phạm vi

Tài liệu này là wireframe triển khai cho frontend MVP. React + Vite gọi
FastAPI qua `/api/v1`; chưa thêm API mới, chưa xử lý đăng nhập và chưa có
chức năng upload persona.

Luồng chính:

```text
Campaign
  → Scenario
  → Nội dung / Shop / Bài viết và lịch
  → Người tham gia
  → Kiểm tra và chốt
  → Tạo run
  → Mô phỏng
  → Kết quả
```

## 2. App shell dùng chung

```text
┌──────────────────────────────────────────────────────────────────────┐
│ ecosim       Campaign / Scenario     [Trạng thái]       [?]  [ ! ]   │
├────────────────┬─────────────────────────────────────────────────────┤
│ Tổng quan      │ Breadcrumb                                           │
│ Nội dung       │ Tiêu đề màn hình                                     │
│ Shop           │ Nội dung chính                                       │
│ Bài viết & lịch│                                                     │
│ Người tham gia │                                                     │
│ Kiểm tra       │                                                     │
│ Mô phỏng       │                                                     │
│ Kết quả        │                                                     │
└────────────────┴─────────────────────────────────────────────────────┘
```

- Nút `!` mở bảng tra cứu tag từ industry bundle.
- Header hiển thị tên campaign, tên scenario và trạng thái draft/ready/running/
  completed/failed.
- Scenario draft có nút **Lưu nháp** và **Tiếp tục**.
- Scenario ready hoặc run đã bắt đầu chỉ hiển thị dữ liệu đọc.
- Dùng Bricolage Grotesque cho tiêu đề, Inter cho nội dung, JetBrains Mono
  cho số liệu; màu và khoảng cách lấy từ `DESIGN.md`.

## 3. Route và API

| Route React | Mục đích | API chính |
|---|---|---|
| `/` | Giới thiệu, campaign gần đây | `GET /campaigns` |
| `/campaigns/new` | Tạo campaign | `POST /campaigns` |
| `/campaigns/:id` | Danh sách scenario | `GET /campaigns/:id/scenarios` |
| `/scenarios/:id/content` | Nội dung campaign và brand | `GET/PUT scenario` |
| `/scenarios/:id/shop` | Shop và catalog | `GET/PUT scenario` |
| `/scenarios/:id/schedule` | Bài viết và lịch đăng | `GET/PUT scenario` |
| `/scenarios/:id/participants` | Cohort và agent | `participants` |
| `/scenarios/:id/review` | Validate, freeze, tạo run | `validate/freeze/runs` |
| `/runs/:id/live` | Theo dõi mô phỏng | `run`, `sessions`, `objects`, `stream` |
| `/runs/:id/results` | Metric và báo cáo | `report/metrics/definitions` |
| `/runs/:id/articles/:articleId` | Chi tiết bài viết | `metrics` theo article |
| `/runs/:id/shop` | Chi tiết cửa hàng | `metrics` theo shop/product |
| `/runs/:id/agents/:agentId` | Lịch sử agent | `agent history` |

## 4. Màn hình giới thiệu và campaign

```text
┌──────────────────────────────────────────────────────────────┐
│ Mô phỏng phản ứng khách hàng trước khi triển khai chiến dịch │
│ Xem agent chú ý, đọc, ghé shop và mua như thế nào.           │
│                                                              │
│ [TẠO CAMPAIGN]                                               │
├──────────────────────────────────────────────────────────────┤
│ CAMPAIGN GẦN ĐÂY                                            │
│ Tên campaign       Scenario        Run gần nhất      Trạng thái│
│ Ra mắt đồ uống     Cafe MVP         Run 01            Hoàn tất │
└──────────────────────────────────────────────────────────────┘
```

Campaign cũ chỉ mở dữ liệu đã có; không hiển thị số liệu giả khi chưa có run.

## 5. Nội dung campaign

```text
┌──────────────────────────────┬────────────────────────────────┐
│ THÔNG TIN CAMPAIGN           │ THÔNG TIN CÔNG KHAI             │
│ Tên campaign                 │ Organization                   │
│ Ngành                        │ Brand                          │
│ Brief nội bộ                │ Mô tả brand                    │
│ Ghi chú marketer             │ Tag doanh nghiệp                │
│                              │                                │
│ [LƯU NHÁP]  [TIẾP TỤC]      │ Agent được phép thấy phần này   │
└──────────────────────────────┴────────────────────────────────┘
```

- Thông tin nội bộ chỉ lưu trong campaign, không đưa vào context agent.
- Ngành lấy từ `GET /industries`; hiện MVP chỉ bật profile cafe.
- Dữ liệu gửi bằng `PUT /scenarios/{id}` trong một `ScenarioSetup`.

## 6. Shop và sản phẩm

```text
┌────────────────────────────────────────────────────────────────┐
│ SHOP                                                             │
│ Tên shop  | Mô tả công khai  | Tag shop                         │
├────┬──────────────────────┬────────────┬────────────────────────┤
│ #  │ Sản phẩm             │ Giá        │ Tag                     │
│ 01 │ Cà phê cam lạnh      │ 39.000 VND │ coffee · orange · cold  │
│ 02 │ Cold brew vani       │ 45.000 VND │ coffee · vanilla · cold │
└────┴──────────────────────┴────────────┴────────────────────────┘
                         [THÊM SẢN PHẨM] [LƯU VÀ TIẾP TỤC]
```

Form sản phẩm gồm tên, giá, mô tả, tag và vị trí catalog. Frontend không suy
ra doanh thu từ giá; giá chỉ là thông tin được phép dùng trong context.

## 7. Bài viết và lịch đăng

```text
┌──────────────────────┬─────────────────────────────────────────┐
│ NGÂN HÀNG BÀI VIẾT  │ BÀI ĐANG CHỌN                           │
│ • Cà phê cam lạnh   │ Tiêu đề                                 │
│ • Cold brew vani    │ Preview trước khi chú ý                  │
│ [TẠO BÀI]           │ Nội dung đầy đủ khi đọc                 │
│                     │ Tag bài viết                            │
├──────────────────────┴─────────────────────────────────────────┤
│ LỊCH CỐ ĐỊNH                                                   │
│ Phiên 1 │ Vị trí 1 │ Cà phê cam lạnh                           │
│ Phiên 1 │ Vị trí 2 │ Cold brew vani                            │
│ Phiên 2 │ Không có bài                                          │
│ Phiên 3 │ Vị trí 1 │ Cà phê cam lạnh                           │
└────────────────────────────────────────────────────────────────┘
```

- Một bài được đăng lại ở nhiều phiên.
- `position` chỉ duy nhất trong từng phiên.
- Phiên không có bài vẫn hiển thị.
- Sau freeze, lịch chuyển sang chỉ đọc.

## 8. Người tham gia và kiểm tra

```text
┌──────────────────────────┬─────────────────────────────────────┐
│ NGUỒN PERSONA            │ PHÂN BỔ AGENT                        │
│ MatrAIx                   │ Cohort: cafe-mvp-cohort-v1           │
│ 100 persona có sẵn        │ Số agent: 12                         │
│                          │ Chưa biết: 4  (33.3%)                │
│                          │ Trung lập: 4  (33.3%)                │
│                          │ Đã thích: 4   (33.3%)                │
├──────────────────────────┴─────────────────────────────────────┤
│ AGENT PREVIEW: mã, nhóm quan hệ, các trường persona đã project  │
│ [KIỂM TRA CẤU HÌNH]                               [CHỐT]       │
└─────────────────────────────────────────────────────────────────┘
```

Số lượng và phần trăm luôn hiển thị cùng nhau. Dữ liệu lấy từ cohort có sẵn,
không có nút upload hoặc chỉnh sửa persona.

Màn hình kiểm tra hiển thị lỗi từ `validate`; nếu hợp lệ, nút **Chốt scenario**
gọi `freeze`, sau đó cho tạo run với mode tuần tự hoặc song song.

## 9. Màn hình mô phỏng

```text
┌──────────────────────────────────────────────────────────────────┐
│ Cà phê cam lạnh · Phiên 1/3 · ĐANG CHẠY       04/12 agent          │
├───────────────────────────────┬──────────────────────────────────┤
│ BÀI VIẾT                       │ CỬA HÀNG                         │
│ ┌───────────────────────────┐ │ ┌──────────────────────────────┐ │
│ │ Cà phê cam lạnh            │ │ │ Cà phê cam lạnh                │ │
│ │ View 04  Like 01  Dislike 0│ │ │ Lượt chú ý 02  Lượt mua 0      │ │
│ │ Đang xử lý...              │ │ │ Đang chờ agent                 │ │
│ └───────────────────────────┘ │ └──────────────────────────────┘ │
├───────────────────────────────┴──────────────────────────────────┤
│ DIỄN BIẾN                                                         │
│ Agent 04 · chú ý bài viết · cảm nhận đã ghi                         │
│ Agent 07 · bỏ qua bài viết · lý do đã ghi                           │
└──────────────────────────────────────────────────────────────────┘
```

Frontend nhận `progress_batch` từ SSE, đưa vào FIFO hiển thị; số liệu chính
được đọc lại từ API sau `session_completed` và khi run kết thúc. Không giả lập
nhịp chạy bằng delay ở frontend.

## 10. Màn hình kết quả

```text
┌──────────────────────────────────────────────────────────────────┐
│ KẾT QUẢ · 12 agent · 3 phiên · Hoàn tất       [TẢI CẤU HÌNH]      │
├──────────────────────┬───────────────────────────────────────────┤
│ CHỌN NHÓM            │ BIỂU ĐỒ THEO PHIÊN                         │
│ Bài viết             │ Tên chỉ số: Lượt đọc bài                   │
│ Cửa hàng             │                                             │
│ Sản phẩm             │     ●────●────●                             │
│ Chất lượng xử lý     │ Phiên 1  Phiên 2  Phiên 3                  │
├──────────────────────┴───────────────────────────────────────────┤
│ [CHI TIẾT BÀI VIẾT]  [CHI TIẾT CỬA HÀNG]  [CHI TIẾT AGENT]         │
└──────────────────────────────────────────────────────────────────┘
```

Danh sách chỉ số lấy từ `metric-definitions`, giá trị lấy từ `metrics`. Không
hardcode 102 tên metric vào component.

## 11. Chi tiết bài viết, shop và agent

### Bài viết

Hiển thị bài đang chọn, tag, lịch đăng và các line chart: bài được đưa ra,
được chú ý, lượt đọc, thích, không thích theo phiên. Chỉ hiển thị những metric
có trong response.

### Shop và sản phẩm

Hiển thị shop, catalog, giá/tag sản phẩm và line chart lượt ghé shop, sản phẩm
được chú ý, mua và không mua. Sản phẩm chưa phát sinh event vẫn hiện với giá
trị 0 cho metric áp dụng.

### Agent

```text
Agent 04
├── Persona đã project
├── Quan hệ ban đầu với brand
├── Phiên 1
│   ├── Bài viết: chú ý → đọc → không thích
│   └── Sản phẩm: chú ý → không mua
└── Phiên 2 ...
```

Chi tiết lấy từ history; tag hiển thị tên và mô tả snapshot. Không hiển thị
raw prompt hoặc secret.

## 12. Quy tắc trạng thái frontend

| Trạng thái | Cho phép |
|---|---|
| `draft` | Sửa campaign/scenario, validate |
| `ready` | Tạo run, xem cấu hình; không sửa scenario |
| `running` | Xem progress/SSE; không sửa dữ liệu |
| `completed` | Xem report, metrics, history, tải cấu hình |
| `failed` | Xem lỗi, resume theo API; không sửa snapshot |

Frontend dùng `expected_revision` khi lưu và `Idempotency-Key` cho create/start/
resume. Khi nhận lỗi `409`, giữ dữ liệu form cục bộ và yêu cầu tải lại revision.

## 13. Thành phần React tối thiểu

```text
src/
├── app/          router, layout, query client
├── api/          typed API client và SSE client
├── components/   Button, Card, TagDictionary, MetricChart, DataTable
├── features/
│   ├── campaigns/
│   ├── scenarios/
│   ├── simulation/
│   └── results/
└── pages/        các route ở trên
```

Giai đoạn code đầu tiên chỉ cần AppShell, campaign creation, scenario setup,
validation/freeze và run creation. Sau đó mới thêm live SSE và charts.
