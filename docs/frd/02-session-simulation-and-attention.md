# FRD-02 — Mô phỏng Session và Attention

Policy v1 và thứ tự thực thi: [FRD-05](05-session-policy-and-state.md).

## Mục đích

Mô tả cách một session xác định agent nào đang hoạt động và bài viết hoặc sản
phẩm nào nhận đủ sự chú ý để tiếp tục tương tác sâu hơn.

## Luồng của một session

```text
Bắt đầu session
→ chọn agent hoạt động
→ xác định toàn bộ bài viết/sản phẩm hợp lệ trong phạm vi hiện tại
→ gọi JEV theo từng agent–đối tượng
→ fallback sang LLM nếu JEV không có đáp án hợp lệ
→ đánh giá attention theo từng agent và đối tượng
→ chỉ tiếp tục với đối tượng nhận đủ attention
→ lưu event của session
→ công bố metric của session
```

## Hành vi attention

Attention được đánh giá riêng cho từng cặp agent–đối tượng. Đối tượng có thể
là bài viết hoặc sản phẩm và luôn gắn với organization/brand đang quảng bá.

Danh tính brand có thể là một phần của điều agent nhận biết. Vì vậy agent có
thể chú ý đến một bài vì chủ đề, vì brand, vì sản phẩm hoặc vì sự kết hợp của
các yếu tố đó. Thái độ tiêu cực với brand không tự động chặn việc tiếp xúc.

Hệ thống phải phân biệt tối thiểu các kết quả nghiệp vụ:

- agent không có lần tiếp xúc đáng kể;
- agent nhận ra hoặc lướt qua đối tượng;
- agent đọc hoặc xem đủ sâu để tiếp tục chuỗi tương tác.

Nếu cả JEV và LLM fallback đều trả rỗng hoặc không có đáp án hợp lệ, hệ thống
ghi nhận `unresolved` và dừng nhánh của đối tượng đó; không thực hiện các bước
phụ thuộc tiếp theo.

Attention không đồng nghĩa với đồng ý hoặc yêu thích. Agent có thái độ tiêu
cực vẫn có thể chú ý, đọc, phê bình hoặc ghé shop.

## Bài viết

1. Chỉ những bài được lịch cố định đăng trong session mới được xem là bài mới
   của session đó.
2. Hệ thống gọi JEV cho từng agent đang hoạt động với toàn bộ bài hợp lệ.
3. Agent không bắt buộc phải đọc toàn bộ bài hợp lệ; mỗi bài được đánh giá độc
   lập.
4. Việc lướt qua bài và việc đọc kỹ bài phải được lưu khác nhau.
5. Đọc kỹ bài sẽ bắt đầu chuỗi tương tác bài viết.
6. Lướt qua có thể chỉ được lưu như một lần tiếp xúc, chưa bắt đầu chuỗi đọc
   bài.
7. Hệ thống không được dùng comment của agent khác làm nội dung hiển thị cho
   agent đang được đánh giá.
8. Nếu bài viết hiển thị tên hoặc thông tin brand, phần thông tin đó phải
   thuộc đúng brand của bài viết.

## Sản phẩm

1. Chỉ đánh giá attention sản phẩm sau khi agent đã ghé shop.
2. Hệ thống gọi JEV cho từng sản phẩm đang có trong shop đối với agent đó.
3. Xem sản phẩm sẽ bắt đầu chuỗi tương tác sản phẩm.
4. Xem sản phẩm không có nghĩa là chắc chắn mua.
5. Lần mua trước, lần không mua, lần xem trước và thought tag trước đó phải
   được phân biệt trong lịch sử.
6. Context sản phẩm phải xác định được brand/shop cung cấp sản phẩm; không
   gộp sản phẩm cùng tên của các brand khác nhau thành một sản phẩm.

## Ví dụ kiểm tra

- Agent tiêu cực vẫn có thể đọc bài rồi chọn `dislike`.
- Agent có thể chỉ lướt qua bài ở một session và đọc kỹ bài đó ở session sau.
- Agent có thể vào shop, xem sản phẩm rồi chọn `not_buy`.
- Bài chưa được đăng trong session hiện tại không được coi là bài mới của
  session đó.
- Nếu cả JEV và LLM fallback đều không có đáp án cho một bài hoặc sản phẩm,
  nhánh đó ghi `unresolved` và dừng. Nếu cả hai lượt chấm tag hợp lệ nhưng
  dưới sàn, ghi `empty_result`; không tạo action thay thế.
