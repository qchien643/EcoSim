# Thiết kế luồng tiến độ mô phỏng qua SSE v1

**Ngày:** 29/09/2026  
**Trạng thái:** thiết kế MVP, chưa triển khai HTTP endpoint.

## Mục đích

SSE (Server-Sent Events) cho phép backend chủ động gửi tiến độ của một run
đang chạy đến frontend qua một kết nối một chiều:

```text
Frontend mở stream
→ Backend ghi stage event
→ Backend phát sự kiện tiến độ
→ Frontend đưa diễn biến vào hàng đợi FIFO
```

SSE chỉ truyền thông tin quan sát. Nó không tham gia quyết định agent, không
thay thế `stage_events`, không làm backend chờ frontend và không làm thay đổi
tốc độ gọi JEV/LLM.

## Endpoint

```http
GET /api/runs/{run_id}/events/stream?after={cursor}
Accept: text/event-stream
```

`after` là cursor tùy chọn. Nếu không có, stream bắt đầu từ sự kiện đầu tiên
được phép đọc của run. Cursor phải ổn định khi frontend reconnect; không dùng
`sequence_no` riêng của một agent làm cursor toàn run.

Header phản hồi:

```http
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

## Các loại sự kiện

### `run_started`

```json
{
  "run_id": "run_cafe_100x3",
  "status": "running",
  "session_count": 3,
  "cursor": "c_001"
}
```

### `progress_batch`

Đây là message chính trong lúc chạy. Backend có thể gom nhiều stage event
đã commit để tránh frontend phải render từng event:

```json
{
  "run_id": "run_cafe_100x3",
  "session_no": 2,
  "events": [
    {
      "event_id": "evt_123",
      "agent_id": "agent_cafe_mvp_001",
      "object_type": "article",
      "object_id": "cafe_post_orange_coffee",
      "stage": "A3",
      "status": "resolved",
      "action": null,
      "tags": ["emotion.interested"]
    }
  ],
  "metrics": {
    "session_no": 2,
    "posts_read": 18,
    "shop_visits": 5,
    "buys": 3
  },
  "cursor": "c_042"
}
```

Chỉ gửi dữ liệu đã commit. Không gửi raw prompt, API key, nội dung riêng của
agent khác hoặc thông tin không thuộc quyền đọc của run.

### `session_completed`

```json
{
  "run_id": "run_cafe_100x3",
  "session_no": 2,
  "status": "completed",
  "metrics_ready": true,
  "cursor": "c_043"
}
```

Frontend chỉ coi metric của session là chính thức sau sự kiện này.

### `run_completed`

```json
{
  "run_id": "run_cafe_100x3",
  "status": "completed",
  "latest_session_no": 3,
  "cursor": "c_120"
}
```

Đây là trạng thái kết thúc độc lập với hàng đợi hoạt cảnh. Frontend dừng phần
trình bày trực tiếp và đồng bộ report chính thức; không cần phát hết các item
đang còn trong hàng đợi.

### `run_failed`

```json
{
  "run_id": "run_cafe_100x3",
  "status": "failed",
  "failure_code": "MODEL_TIMEOUT",
  "last_completed_session_no": 1,
  "cursor": "c_051"
}
```

Frontend hiển thị lỗi và phần kết quả đã commit. Không đổi `failed` thành
`completed`.

### `heartbeat`

Gửi định kỳ khi chưa có dữ liệu mới để giữ kết nối sống:

```text
: heartbeat
```

Heartbeat không làm thay đổi cursor.

## Cursor và reconnect

Cursor được tạo từ một bảng/read model riêng hoặc từ một thứ tự commit toàn
run, ví dụ:

```text
run_id + commit_seq
```

Mỗi batch có đúng một cursor cuối. Khi mất kết nối, frontend mở lại stream
với `after=cursor_cuối`. Backend gửi lại các batch sau cursor đó. Frontend
khử trùng lặp bằng `event_id`.

`stage_events.sequence_no` vẫn giữ nguyên ý nghĩa lịch sử trong phạm vi
`run/session/agent`; không đổi mục đích của trường này để phục vụ SSE.

## Quy tắc hàng đợi frontend

- Nhận event theo thứ tự cursor và đưa vào hàng đợi FIFO.
- Có thể gom các event cùng session, agent và object.
- Không gom event khác session hoặc khác đối tượng thành một diễn biến.
- Giới hạn kích thước hàng đợi; khi quá tải chỉ rút gọn phần trình bày,
  không xóa `stage_events`.
- Counter lấy từ metric backend, không đếm số hoạt cảnh đã phát.
- Khi nhận `run_completed` hoặc `run_failed`, dừng hoạt cảnh trực tiếp ngay.
- Reconnect không được làm thay đổi kết quả mô phỏng.

## Quy tắc backend

- Không giữ transaction SQLite trong khi chờ SSE gửi dữ liệu.
- Không chờ frontend nhận message rồi mới chạy stage tiếp theo.
- Chỉ publish sau khi event và projection cần thiết đã commit.
- Nếu publish thất bại, run vẫn tiếp tục; frontend có thể đọc bù bằng cursor.
- Không cần bảng queue hoạt cảnh trong MVP. `stage_events` và cursor là nguồn
  dữ liệu; hàng đợi trình bày thuộc frontend.

## Polling fallback

Nếu môi trường chưa hỗ trợ SSE, frontend dùng cùng read model:

```http
GET /api/runs/{run_id}/events?after={cursor}&limit=100
GET /api/runs/{run_id}/status
```

Vì SSE và polling dùng chung cursor, có thể chuyển đổi giữa hai cơ chế mà
không thay đổi dữ liệu mô phỏng.
