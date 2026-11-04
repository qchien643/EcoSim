# Metrics và báo cáo v1

## Mục đích

`MetricsProjector` tạo dữ liệu phân tích từ `stage_events` sau mỗi session đã
chạy xong. Đây là dữ liệu dẫn xuất, có thể xóa và dựng lại; `stage_events` vẫn
là nguồn sự thật cho lịch sử agent.

Projector không gọi JEV/LLM và không suy diễn hành vi. `ReportService` chỉ đọc
các snapshot đã commit để giao diện có thể polling sau từng session hoặc vẽ
state chart.

## Snapshot

Mỗi metric lưu một dòng trong `metric_snapshots`:

```text
(run_id, session_id, session_no, scope_type, scope_id, metric_name,
 numerator, denominator, session_value,
 cumulative_numerator, cumulative_denominator, cumulative_value,
 calculation_version)
```

Khóa duy nhất gồm run, session, scope, metric và version. Project cùng một
session nhiều lần là idempotent. `null` denominator/value nghĩa là metric
không có mẫu số trong session đó; không đổi thành `0%`.

Snapshot và `sessions.status='completed'` được ghi trong cùng transaction.
Vì vậy UI chỉ thấy một session sau khi toàn bộ event và metric của session đó
đã được commit.

## Metric v1

Metric đếm gồm: bài/sản phẩm được đưa vào flow, chú ý, bỏ qua, đọc, like,
dislike, giữ/xóa phản ứng, ghé shop, chú ý sản phẩm, mua, không mua,
`empty_result`, `unresolved`, nguồn JEV/fallback và tag được chọn.

Các rate chính:

```text
post_attention_rate    = posts_attended / stage.A1.resolved
read_rate              = posts_read / posts_attended
shop_visit_rate        = shop_visits / stage.A5.resolved
product_attention_rate = products_attended / stage.B1.resolved
purchase_rate          = buys / stage.B3.resolved
```

`empty_result` và `unresolved` được báo riêng. Chúng không bị tính thành
`skip`, `no_reaction`, `not_buy` hoặc bất kỳ hành động từ chối nào. Metric
`current_likes` và `current_dislikes` là trạng thái cuối snapshot, không phải
tổng số lần action.

Giá trị cumulative dùng tổng tử số và tổng mẫu số từ đầu run đến session đó,
không lấy trung bình các phần trăm của từng session.

## Report API nội bộ

`ReportService.run_report(run_id)` trả:

- trạng thái run;
- version cách tính;
- danh sách session đã hoàn tất;
- từng metric với `session_value` và `cumulative_value`.

`metric_series(run_id, metric_name)` trả các mốc session của một metric.
`agent_history(run_id, agent_id)` trả event theo thứ tự session/event kèm
selected tag để marketer hoặc chatbot truy vết trải nghiệm của agent.

## Model usage

`ReportService.run_report(run_id)` cũng trả `model_usage`, được tổng hợp từ
usage do provider trả về trong từng `model_call`. Các trường chính gồm:

- `input_tokens`, `output_tokens`, `total_tokens`;
- `usage_records` và `attempts`;
- `by_session` để theo dõi mức dùng token ở từng phiên;
- `cost` chỉ là giá trị provider trả về nếu có, không tự suy ra bảng giá.

Model usage là số liệu vận hành, không phải metric hành vi và không tham gia
vào các rate của mô phỏng. Nếu provider không trả usage, event vẫn được lưu
nhưng record đó không được tính vào tổng token.

V1 dùng replay prefix khi project để đơn giản và rebuild được. Khi quy mô
thực tế cần tối ưu, có thể thêm bảng accumulator/checkpoint nhưng không thay
đổi contract snapshot hoặc nguồn sự thật.
