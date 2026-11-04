# FRD-03 — Tương tác Agent và Lưu trữ

Chi tiết policy, idempotency và transaction: [FRD-05](05-session-policy-and-state.md).

## Mục đích

Mô tả các chuỗi tương tác có thể quan sát được và dữ liệu cần lưu để giải
thích điều gì đã xảy ra với từng agent.

## Chuỗi tương tác với bài viết

Khi agent đọc một bài viết, hệ thống xử lý theo thứ tự:

1. Chạy mapping tag doanh nghiệp/brand và tag bài viết để chọn context persona.
2. Tạo emotion tag ban đầu sau khi agent chú ý bài, trước khi đọc nội dung.
3. Tạo emotion tag sau khi đọc nội dung bài.
4. Chọn phản ứng với bài viết.
5. Có thể quyết định ghé shop hoặc không.

Phản ứng phải hỗ trợ các quy tắc đã thống nhất:

- Lần đầu: `like`, `dislike` hoặc `no_reaction`.
- Khi đã có phản ứng: `keep_current`, `remove_reaction` hoặc `no_new_reaction`.
- Không đồng thời like và dislike trên cùng một bài.
- Comment chưa thuộc phạm vi bản đầu.

## Chuỗi tương tác với sản phẩm

Khi agent chú ý đến một món hàng, hệ thống xử lý:

1. Chạy mapping tag doanh nghiệp/brand và tag sản phẩm để chọn context persona.
2. Gọi JEV cho toàn bộ sản phẩm trong shop; fallback sang LLM nếu cần.
3. Với sản phẩm được chú ý, nêu suy nghĩ khi agent chú ý món hàng.
4. Đúng một action mua hàng: `buy` hoặc `not_buy`.

Cả hai action đều được lưu. `not_buy` không phải là giao dịch bị thiếu và
không có nghĩa là từ chối vĩnh viễn.

## Yêu cầu lưu lịch sử

Mỗi event phải xác định được:

- campaign, scenario, run và session;
- organization và brand mà event đang hướng tới;
- agent;
- loại đối tượng và ID đối tượng;
- thứ tự event;
- trạng thái attention/tiếp xúc;
- thought tag;
- emotion tag;
- mô tả chuẩn của từng tag được chọn, lấy từ tag registry;
- reaction hoặc action mua hàng;
- event trước đó nếu chuỗi có liên kết.

Đối với quyết định sản phẩm, bản ghi phải liên kết action với thought tag
được tạo ngay trước quyết định đó.

Quan hệ giữa agent và brand phải được lưu riêng với persona chung. Ví dụ,
“agent không tin brand X” là một trạng thái gắn với brand X, không được biến
thành kết luận rằng agent không tin mọi thương hiệu.

## Trạng thái persona

Hệ thống có thể duy trì trạng thái persona hiện tại và event history, nhưng
đây là hai khái niệm khác nhau:

- history giải thích điều đã xảy ra;
- trạng thái persona thể hiện context hiện tại của agent trong mô phỏng.

Không bắt buộc phải thay đổi thuộc tính persona sau mọi event. Nếu có cập
nhật, phải lưu giá trị cũ, giá trị mới, lý do và session thực hiện cập nhật.

## Xử lý lỗi

Hệ thống không được tự tạo action khi output tương tác bị thiếu hoặc sai
contract. Cả hai lượt chấm tag hợp lệ nhưng dưới sàn: `empty_result`.
Nếu không có kết quả usable và có lượt lỗi/sai: `unresolved`.
Fallback usable vẫn được dùng dù JEV lỗi. Dừng nhánh phụ thuộc nếu không
resolved; không chuyển lỗi thành `no_reaction` hoặc `not_buy`.
