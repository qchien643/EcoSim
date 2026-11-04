# Khởi động backend và frontend ecoSim

Hướng dẫn chạy cục bộ từ thư mục gốc `ecoSim/`. Mở **hai terminal riêng** và giữ
cả hai chạy khi dùng giao diện. Không cần kích hoạt môi trường Python bằng
`source`; các lệnh dưới đây gọi trực tiếp `.venv`.

## 1. Chuẩn bị lần đầu

Máy cần có Python 3.12+, Node.js và npm.

Tại thư mục dự án:

```bash
cd /duong/dan/toi/ecoSim
```

Nếu **chưa có** `.venv`, tạo môi trường:

```bash
python3 -m venv .venv
```

Cài dependency Python và frontend:

```bash
.venv/bin/python -m pip install -r requirements.txt
cd frontend
npm ci
cd ..
```

Bỏ qua bước cài đặt ở những lần mở sau nếu dependency không thay đổi.

### Cấu hình model

Tạo `.env` trong `ecoSim/` từ `.env.example` nếu cần gọi model. Checkout cũ
có thể dùng liên kết tới `.env` ở thư mục cha; **không ghi đè liên kết đang có**.
Giữ key trên máy, không đưa vào frontend. Runtime đọc các tên biến:

- `OPENROUTER_API_KEY`: gọi JEV.
- `OPENAI_API_KEY` và `OPENAI_MODEL`: OpenAI dự phòng.

Không cần key để nạp dữ liệu nền hoặc xem cấu hình/kết quả đã lưu.
Model gateway tự đọc `.env`; không cần chạy `source .env`.
Riêng `ECOSIM_DATABASE` cần được `export` trong terminal như hướng dẫn dưới.

### Chuẩn bị dữ liệu và nạp

Bản clone GitHub **không có** `data/personas/cafe_mvp/cohort.jsonl`, SQLite
hay Parquet. Chạy self-check offline trước nếu chỉ cần kiểm tra code:

```bash
.venv/bin/python -m backend.self_check
cd frontend && npm test && cd ..
```

Để chạy giao diện với người tham gia, cần có `data/personas/cafe_mvp/manifest.json`
và `cohort.jsonl` hợp lệ từ pipeline chuẩn bị dữ liệu. Không có sẵn công cụ
tải tự động cohort trong bản clone; xem [hướng dẫn dữ liệu](data/README.md).
**Không dùng dữ liệu MatrAIx cho mục đích thương mại nếu chưa được cấp quyền.**
Khi đã chuẩn bị đầy đủ, từ `ecoSim/`:

Từ `ecoSim`:

```bash
export ECOSIM_DATABASE="$PWD/data/ecosim-backend.sqlite"
.venv/bin/python -m backend.bootstrap
```

Lệnh này nạp bộ ngành cà phê, metadata MatrAIx và cohort 100 người dùng ảo
đã chuẩn bị; nếu thiếu hoặc không hợp lệ sẽ báo lỗi. Không tải persona mới,
không chạy mô phỏng và không gọi model.
Sau khi có cohort, chạy `.venv/bin/python -m backend.api.self_check` nếu muốn
kiểm tra thêm API và template với dữ liệu đã chuẩn bị.
Chạy lại với dữ liệu giống nhau không tạo trùng. Nếu báo xung đột dữ liệu,
không xóa database để xử lý: cần kiểm tra phiên bản dữ liệu đang nạp.

## 2. Terminal thứ nhất — backend

Mỗi lần khởi động:

```bash
cd /duong/dan/toi/ecoSim
export ECOSIM_DATABASE="$PWD/data/ecosim-backend.sqlite"
.venv/bin/python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Giữ terminal này mở. Tài liệu API ở `http://127.0.0.1:8000/docs`.
Chỉ dùng một worker; không bật `--reload` khi chạy mô phỏng vì việc nạp lại
tiến trình có thể làm gián đoạn lần chạy.

## 3. Terminal thứ hai — frontend

```bash
cd /duong/dan/toi/ecoSim/frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Mở trình duyệt tại `http://127.0.0.1:5173`.
Frontend chuyển các yêu cầu `/api` tới backend cổng `8000`.
Không cần chạy `npm run build` để sử dụng chế độ phát triển này.

## 4. Kiểm tra đã kết nối

Trong terminal khác, có thể kiểm tra:

```bash
curl --fail http://127.0.0.1:8000/api/v1/industries
curl --fail http://127.0.0.1:5173/api/v1/cohorts
```

Lệnh đầu kiểm tra backend và dữ liệu ngành; lệnh sau kiểm tra cả đường
kết nối từ frontend tới backend. Sau khi nạp thành công phải có ngành
`cafe` và bộ người tham gia `cafe-mvp-cohort-v1`.

Trên giao diện: tạo chiến dịch → tạo kịch bản → nhập doanh nghiệp, cửa hàng,
sản phẩm, bài viết và lịch → chọn người tham gia → kiểm tra → chốt cấu hình
→ tạo lần chạy. **“Bắt đầu mô phỏng” hoặc “Chạy tiếp” mới gọi model và có
thể phát sinh phí**; khởi động hai server không tự chạy mô phỏng.

## 5. Dữ liệu và cách dừng

Để không nhập lại dữ liệu: trên trang đầu chọn **Tạo từ mẫu → Mộc — Cà phê
mỗi ngày → Dùng mẫu này**. Bạn nhận bản nháp điền sẵn để sửa các trường
cần thử; mẫu gốc không đổi. Cần bootstrap dữ liệu trước khi dùng mẫu.

- Database trong hướng dẫn là `ecoSim/data/ecosim-backend.sqlite`. Giữ nguyên
  file này để xem lại chiến dịch, kịch bản và kết quả sau khi khởi động lại.
- Nếu muốn mở một database backend khác, thay đường dẫn `ECOSIM_DATABASE`
  ở terminal backend. Không trỏ vào database của engine cũ.
- Đổi database có thể khiến danh sách chiến dịch khác đi; không có nghĩa dữ
  liệu trong file trước đã bị xóa.
- Đợi mô phỏng hoàn tất rồi nhấn `Ctrl+C` ở từng terminal để dừng server.
  Đây không phải chức năng tạm dừng mô phỏng.
- Chỉ chạy local: backend hiện chưa có xác thực, không mở ra Internet.

## 6. Các lỗi thường gặp

| Hiện tượng | Cách kiểm tra |
| --- | --- |
| Không thấy `.venv/bin/python` | Kiểm tra đang ở `ecoSim`; tạo môi trường và cài dependency theo bước 1. |
| Báo cổng đã được sử dụng | Kiểm tra terminal/server cũ trước; dừng đúng tiến trình của dự án. Không tùy tiện đổi cổng backend vì frontend đang chuyển tiếp tới `8000`. |
| Giao diện báo không kết nối được máy chủ | Kiểm tra terminal backend, thử lệnh `curl` trực tiếp cổng `8000`. |
| Không có ngành hoặc bộ người tham gia | Chạy bootstrap với đúng file database mà backend đang dùng. |
| Không thấy chiến dịch trước đây | Kiểm tra đường dẫn `ECOSIM_DATABASE`; một file mới sẽ có danh sách khác. |
| Mô phỏng lỗi khi gọi model | Xem log backend và cấu hình key/model trong `.env`; không chia sẻ key hoặc toàn bộ file `.env`. |

Kiểm tra frontend không gọi model:

```bash
cd /duong/dan/toi/ecoSim/frontend
npm test
npm run build
```

`npm run build` tạo `dist/`, không tự khởi động backend. Hướng dẫn này dành
cho chạy local bằng Vite, chưa phải hướng dẫn triển khai production.
