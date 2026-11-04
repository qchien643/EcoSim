# FRD-04 — Dashboard và Phân tích

## Mục đích

Mô tả những gì marketer có thể theo dõi trong lúc mô phỏng chạy và sau khi
mô phỏng kết thúc.

## Màn hình chính

Màn hình mô phỏng gồm:

- khu vực mạng xã hội mô phỏng, hiển thị bài viết và tương tác;
- khu vực phân tích, hiển thị metric theo session và lũy kế.

Giao diện có thể hiển thị dần các session đã hoàn thành để tạo cảm giác theo
dõi trực tiếp. Dữ liệu hiển thị phải lấy từ event và metric đã được lưu.

## Kết quả bắt buộc hỗ trợ

Hệ thống phải hỗ trợ phân tích:

- like, dislike và trạng thái không phản ứng của bài viết;
- lượt xem sản phẩm;
- lượt mua và không mua;
- số lần không phản ứng hoặc dừng nhánh do không có đáp án hợp lệ;
- doanh thu hoặc giá trị mua mô phỏng nếu sản phẩm có giá;
- biến động theo từng session;
- tổng lũy kế của các session đã hoàn thành.

Bộ metric v1, cách giữ tử số/mẫu số và contract report được mô tả trong
[metrics-and-reporting-v1](../technical/metrics-and-reporting-v1.md). Mỗi
session chỉ được công bố sau khi event, snapshot metric và trạng thái hoàn
thành đã commit trong cùng transaction. Giá trị theo session và giá trị lũy
kế không được âm thầm trộn lẫn.

`empty_result` và `unresolved` phải hiển thị riêng; chúng không được tính
thành bỏ qua, không phản ứng hoặc không mua.

## Xem chi tiết nguyên nhân

Marketer nên có khả năng đi từ kết quả tổng hợp đến chuỗi event giải thích kết
quả đó, ví dụ:

```text
Lượt mua sản phẩm
→ sản phẩm
→ session
→ agent
→ thought tag
→ emotion tag
→ buy/not_buy
```

Đây là yêu cầu chức năng về khả năng giải thích; giao diện và bộ lọc cụ thể
vẫn cần được chốt.

## So sánh Scenario

Marketer có thể so sánh các run thuộc các scenario khác nhau. Hệ thống phải
giữ riêng định danh campaign, scenario, run và session để không trộn lịch sử
hoặc metric.

## Cập nhật theo session

Sau mỗi session hoàn tất, giao diện có thể đọc report bằng polling. Không yêu
cầu WebSocket trong v1. Report giữ cả snapshot session và cumulative để vẽ
đường biến đổi theo session; không chỉ lưu giá trị cuối run.
