# ecoSim frontend

React + Vite, viết mới từ đầu theo `../../DESIGN.md` (Nocturne Stage).
Không dùng dashboard HTML cũ hoặc dữ liệu giả thay cho API.

## Chạy cục bộ

Xem [hướng dẫn khởi động đầy đủ](../KHOI-DONG.md) để cài môi trường bằng uv,
nạp dữ liệu có sẵn, chọn database và chạy hai terminal riêng.

Từ `ecoSim`, khởi động backend đã nạp cohort:

```bash
.venv/bin/python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Trong terminal khác, từ `ecoSim/frontend`:

```bash
npm ci
npm run dev
```

Mở `http://127.0.0.1:5173`. Vite chuyển `/api` tới backend cổng 8000.
Không đưa API key vào biến `VITE_*`, source hoặc bundle frontend.
Chỉ dùng local/nội bộ; backend hiện chưa có xác thực.

Muốn xem lần JEV/OpenAI đã lưu, khởi động backend với database tương ứng:

```bash
ECOSIM_DATABASE=experiments/api-live-smoke-w_oxt787/backend.sqlite \
  .venv/bin/python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
```

Sau đó mở `http://127.0.0.1:5173/#/runs/run_8925979a5efa/results`.
Chỉ xem kết quả không gọi model. Tạo run cũng chưa gọi model; nút bắt đầu/
chạy tiếp yêu cầu xác nhận phí trước khi gửi lệnh.

## Phần đã kết nối

- Campaign: tạo, sửa thông điệp, xem kịch bản và các lần chạy.
- Tạo từ mẫu: chọn “Mộc — Cà phê mỗi ngày”, tạo bản nháp 12 người / 3 phiên /
  3 bài / 4 sản phẩm, sửa trực tiếp trên web. Không freeze/start tự động.
  API cần dữ liệu nền đã bootstrap; retry mạng dùng lại command key.
- Scenario: ngành/cohort có sẵn, doanh nghiệp/brand, nhiều shop/sản phẩm,
  giá và mô tả, chọn tag từ registry; frontend tự gán nguồn và bước hiển thị.
- Cửa hàng: mỗi cửa hàng là một thẻ riêng; sản phẩm nằm trong đúng cửa hàng,
  hiển thị tên, giá và mô tả ngắn. Thêm/sửa mở cửa sổ riêng, đổi thứ tự bằng
  mũi tên, chuyển sản phẩm sang cửa hàng khác và không cho xóa cửa hàng khi
  còn sản phẩm/bài viết đang liên kết.
- Bài viết: nội dung trước/sau khi đọc, lịch phiên có thứ tự và đăng lại;
  nút lên/xuống thay cho yêu cầu kéo thả bằng chuột.
- Cơ cấu: nhập theo số người hoặc %, xem số lượng/tỷ lệ; phân bổ nguyên
  người chính thức và preview lấy từ validator/participants.
- Lưu draft bằng `expected_revision`; giữ form khi lỗi. Chốt rồi chỉ đọc.
- Tạo run tuần tự/song song, start/resume với idempotency key giữ qua retry.
- MVP ẩn lựa chọn kỹ thuật khi tạo run; frontend dùng mặc định trong
  `src/config/simulation-defaults.yaml`: chạy song song, batch 4 người.
  Nút tạo run chưa gọi model; nút “Bắt đầu mô phỏng” ở màn hình tiếp theo mới
  gửi lệnh gọi JEV/OpenAI.
- SSE theo batch, FIFO hiển thị giới hạn; polling dự phòng. Kết thúc ưu tiên
  hơn hàng chờ; chuyển tới kết quả chính thức, không giữ hoạt cảnh giả.
- Màn hình live trình diễn theo thứ tự: người đang xử lý, luồng các bước,
  biểu đồ trạng thái qua phiên, số liệu tích lũy, dòng sự kiện và nội dung
  rút gọn. Không hiển thị toàn bộ nội dung bài/sản phẩm trong khu vực live.
- Line chart theo phiên/lũy kế, scope run/article/shop/product, bảng giá trị,
  lịch đăng, token. Giữ null là thiếu dữ liệu, không đổi thành 0.
- Kết quả: tóm tắt lượt đọc/ghé/chú ý sản phẩm/mua, chọn chỉ số bằng nút
  tiếng Việt, biểu đồ đường và liên kết từ từng bài/sản phẩm đến chi tiết.
  Nội dung dài, lịch đăng, token và chỉ số bổ sung được thu gọn.
  “Lượt” không phải số người duy nhất; phản ứng thích/không thích dùng trạng
  thái cuối phiên, không cộng dồn. Tỷ lệ lấy trực tiếp từ báo cáo backend.
  Trang chưa có phiên hoàn tất hiển thị thiếu dữ liệu, không tự gán 0.
- Hành trình người tham gia được chia thành từng khung theo phiên. Mỗi khung
  nối các node theo `sequence_no`; node hiện hành động dễ hiểu như “Bỏ qua bài
  viết” hoặc “Mua sản phẩm”, kèm tên bài viết/sản phẩm. Nhấn hoặc dùng bàn phím
  chọn node sẽ mở một ô thông tin nhỏ ngay dưới đồ thị; ô này cho biết hành
  động, trạng thái, điểm, lý do bỏ qua và các tag suy nghĩ/cảm nhận liên quan.
  Các bước suy nghĩ và lý do bỏ qua được gộp vào phần chi tiết, không tạo node
  hoặc chú thích màu riêng. Khung có cuộn ngang để không chồng node khi một
  phiên gặp nhiều bài.
- Lần mô phỏng có tab “Cấu hình” riêng để xem lại thông tin đã chốt của đúng
  run đó: chiến dịch, doanh nghiệp, cửa hàng, sản phẩm, bài viết và lịch đăng.
  Đây là màn hình chỉ đọc; không đưa người dùng quay về luồng kiểm tra/chạy
  của scenario và không chỉnh sửa run cũ. Breadcrumb hiển thị chiến dịch,
  kịch bản, mã lần mô phỏng và phần đang xem.
- Từ lần chạy, tab “Cấu hình” chỉ mở snapshot đã chốt của đúng run; không đưa
  người dùng về luồng kiểm tra/chạy và không sửa hoặc ghi đè run cũ. Muốn chạy
  lại, người dùng tạo run mới từ scenario đã chốt.
- Lịch sử agent có bộ lọc bước/phiên, phân trang, tag và mô tả đã lưu.
- Từ điển registry, tải cấu hình JSON; không có upload persona.

## Kiểm tra

### Nhập liệu cho người không chuyên

- Bỏ nhãn trang trí viết hoa phía trên tiêu đề; câu hỏi và ví dụ hướng dẫn
  người chuẩn bị mở cửa hàng, giữ màu và font Nocturne Stage.
- Chọn đặc điểm bằng checkbox theo nhóm, không qua danh sách rồi bấm thêm.
  Nhãn tiếng Việt chỉ để hiển thị, không sửa ID/định nghĩa trong bundle.
- Không hiển thị hai trường kỹ thuật `source_ref` và `visible_stages`.
  Khi thêm đặc điểm, frontend lấy mặc định từ file cấu hình bên dưới.
- Nhấn nút kính lúp mới hiện ô tìm
  đặc điểm; đóng ô sẽ xóa từ khóa lọc. Tìm kiếm không ẩn mục đã chọn.
  Sản phẩm có thể thu gọn để nhìn được toàn bộ danh sách.
- Màn hình bài viết chỉ hiện tên và tối đa 100 từ đầu của `article_content`;
  không lấy đoạn trích từ `preview`. Thêm/sửa mở dialog trên nền mờ.
- Lịch đăng là lưới các phiên, mỗi ô ghi số bài. Dialog lịch cho chọn
  bài bằng checkbox, đổi thứ tự bằng mũi tên, thêm/xóa phiên. Một bài
  được phép có ở nhiều phiên; phiên trống vẫn hợp lệ. Không gán ngày/tháng.
- Dialog giữ bản sửa riêng. “Xác nhận bài viết/lịch đăng” yêu cầu xác nhận
  trước khi áp dụng vào bản nháp; X/Hủy/Escape hỏi trước khi bỏ thay đổi.
  Sau khi áp dụng, dùng “Lưu bản nháp” hoặc “Tiếp” để lưu lên máy chủ.
  Không tạo bài rỗng hoặc đổi lịch ngay khi mở cửa sổ.
  Rời trang khi cửa sổ còn bản sửa cũng cần xác nhận bỏ thay đổi.
- Các thao tác chốt, xóa, bắt đầu mô phỏng và rời màn hình khi còn thay đổi
  dùng hộp thoại xác nhận của ecoSim, không dùng hộp thoại mặc định của trình
  duyệt. Hộp thoại có nút “Tiếp tục chỉnh sửa” và “Bỏ thay đổi” rõ nghĩa.
- Nút “Tiếp” lưu thay đổi trước khi chuyển bước; lỗi lưu giữ nguyên dữ liệu.
  Cấu hình đã chốt vẫn chỉ đọc, không tự gọi mô hình.

### Mặc định cho đặc điểm

Chỉnh [src/config/tag-defaults.yaml](src/config/tag-defaults.yaml), không chỉnh
backend hoặc engine mô phỏng. File dùng **cú pháp JSON hợp lệ trong YAML**
(dấu ngoặc, dấu phẩy, chuỗi có dấu nháy kép); chưa hỗ trợ YAML thụt dòng hoặc
comment. Dùng `JSON.parse` có sẵn, không thêm thư viện.

| Nơi chọn đặc điểm | `source_field` | `visible_stages` |
| --- | --- | --- |
| Doanh nghiệp/thương hiệu | `brand_description` | A1, A2, A3, A5, B1, B2, B3 |
| Cửa hàng | `public_profile` | A1, A2, A3, A5, B1, B2, B3 |
| Bài viết | `preview` | A1, A2, A3 |
| Sản phẩm | `product_description` | B2, B3 |

Frontend ghép `source_field` với loại đối tượng và ID hiện tại để tạo
`source_ref`, gửi cùng `tag_id` và `visible_stages` theo API hiện có.
Tag sản phẩm mới mặc định chỉ dùng từ bước cân nhắc B2; B1 vẫn nhận tên/giá,
không nhận tag lấy từ mô tả chi tiết. Người nhập vẫn cần viết nội dung nguồn
và chọn ý đúng với nội dung đó; frontend không tự suy diễn hoặc điền mô tả.

Mặc định chỉ áp dụng khi **thêm** tag. Đọc/lưu lại bản nháp giữ nguyên toàn bộ
tag đã có, kể cả nguồn và các bước khác mặc định; bỏ rồi chọn lại tag sẽ dùng
mặc định mới. Cấu hình sai nguồn/bước hiển thị sẽ báo lỗi và giữ dữ liệu nhập.
Sau khi sửa file, chạy kiểm tra bên dưới; bản triển khai tĩnh cần build lại.
Thay đổi này không đổi API, cơ sở dữ liệu hay cơ chế mô phỏng.

```bash
npm test
npm run build
```

`self-check.mjs` kiểm tra chart zero/null, xếp lịch không sửa input, FIFO
dedup, pagination, lỗi API, idempotency header, chọn/bỏ đặc điểm, giới hạn
nguồn thông tin, tìm tiếng Việt không dấu, trích 100 từ và chọn bài không
làm đổi lịch gốc; kiểm tra mặc định YAML trên registry thật, giữ tag cũ khi
thêm/lưu, từ chối cấu hình sai; không dùng framework test.
Đã kiểm tra thêm payload do helper frontend tạo với mặc định YAML cho toàn bộ
tag trong mẫu cafe: API tạo campaign/scenario, lưu giữ nguyên payload và
validate thành công trên SQLite tạm. Không khởi tạo run hoặc gọi model.
Smoke bằng trình duyệt đã đi từ campaign → scenario → sản phẩm/bài/lịch →
cohort → validate → freeze → run ready trên bản sao SQLite của live smoke.
Không start model trong bài kiểm tra giao diện. Kết quả/lịch sử/từ điển đọc
từ run live đã có; kiểm tra thêm desktop và mobile 375–390px.
Đã kiểm tra giữ form khi API trả 409, giữ thay đổi khi chuyển tab trong cùng
kịch bản, download JSON, đóng từ điển bằng Escape/trả focus. SSE
`progress_batch → run_completed` được kiểm tra bằng phản hồi chặn trong
trình duyệt theo contract thật; không phải chạy lại JEV/OpenAI.
Dialog bài/lịch đã được thử với mẫu cafe trên SQLite tạm: hủy không đổi
dữ liệu, xác nhận mới áp dụng, trích đúng 100 từ, xếp lại thứ tự, đăng lại,
phiên trống, xóa bài gỡ lịch, chặn rời trang, và chỉ đọc sau freeze.
Desktop 1440px, mobile 375px và ngang 812px không tràn nội dung; kiểm tra
Escape, trả focus và tìm đặc điểm bằng kính lúp. Không gọi mô hình.

## Giới hạn có chủ ý

- Hash routes (`/#/scenarios/...`) để mở trực tiếp trên static hosting
  không cần cấu hình rewrite. Không thêm router/query/chart library.
- Build tạo `dist/`; deployment phải reverse-proxy `/api` và không buffer
  SSE. Vite dev proxy không tự trở thành proxy production.
- Chưa hỗ trợ đăng nhập, upload/import persona, sinh bài tự động, chatbot,
  pause/cancel. Mô tả tag/persona chuẩn vẫn dùng tiếng Anh của backend.
- Cohort và bundle phải có trên backend; không tự bootstrap từ trình duyệt.
- Dữ liệu form chưa lưu nằm trong bộ nhớ; có cảnh báo khi rời kịch bản,
  không lưu thông tin campaign/persona vào localStorage.
