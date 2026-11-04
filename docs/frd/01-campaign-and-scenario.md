# FRD-01 — Chuẩn bị Campaign và Scenario

## Mục đích

Mô tả cách marketer chuẩn bị một lần mô phỏng trước khi session đầu tiên
bắt đầu.

## Luồng chính

```text
Tạo campaign
→ nhập thông tin organization/brand
→ chuẩn bị bài viết và sản phẩm
→ tạo scenario
→ cấu hình cơ cấu khách hàng
→ phân bổ bài vào các session
→ review và khóa cấu hình
→ bắt đầu run
```

## Hành vi chức năng

1. Marketer cung cấp một bản mô tả campaign.
2. Marketer cung cấp hoặc xác nhận organization và brand đứng sau campaign.
3. Hệ thống chuẩn bị ngân hàng bài viết và danh mục sản phẩm để marketer
   review.
4. Marketer có thể giữ lại, chỉnh sửa hoặc xóa bài viết và sản phẩm.
5. Marketer có thể tạo một hoặc nhiều scenario từ campaign.
6. Mỗi scenario có riêng:
   - ngân hàng bài viết;
   - danh mục sản phẩm của từng shop;
   - cơ cấu khách hàng;
   - lịch session;
   - số lượng session;
   - các tham số mô phỏng.
7. Mỗi bài viết, shop và sản phẩm phải có liên kết rõ ràng với organization
   hoặc brand mà marketer đang quảng bá.
8. Marketer phân bổ từng bài viết vào session cố định. Một session có thể
   không có, có một hoặc có nhiều bài viết.
9. Một bài viết có thể được phân bổ lại vào nhiều session; các lần đăng giữ
   cùng `post_id` nhưng có `position` riêng trong từng session.
10. Một shop có thể có nhiều sản phẩm. Mỗi sản phẩm có giá, mô tả và tag riêng.
    Khi agent ghé shop, hệ thống xét toàn bộ catalog hợp lệ theo thứ tự cố
    định; agent không bị giới hạn vào một sản phẩm duy nhất.
11. Giao diện hiển thị đồng thời số lượng và phần trăm của từng nhóm khách hàng.
12. Hệ thống không cho bắt đầu run nếu cơ cấu khách hàng chưa đủ hoặc không hợp
   lệ.
13. Sau khi run bắt đầu, lịch, danh tính quảng bá và cấu hình được dùng cho run đó không được
   chỉnh sửa.

## Thông tin cần chuẩn bị

Tối thiểu cần phân biệt:

- thông tin organization dùng để xác định chủ thể quảng cáo;
- thông tin brand hiển thị với agent;
- mô tả shop;
- mối liên hệ giữa brand và các sản phẩm;
- thông tin campaign chỉ dành cho marketer.

Không phải mọi thông tin marketer nhập đều được đưa cho agent. Agent chỉ nhận
những gì họ có thể biết trong bối cảnh đang xem bài viết hoặc vào shop.

## Cơ cấu khách hàng

Marketer chọn nhóm bằng cách kết hợp:

- **Vòng đời:** chưa biết thương hiệu, đã biết nhưng chưa mua, hoặc đã mua
  trước đó;
- **Thái độ ban đầu:** tích cực, trung lập hoặc tiêu cực khi phù hợp.

Vòng đời và thái độ là hai chiều riêng biệt. Agent đã mua trước đó vẫn có thể
có thái độ tiêu cực.

## Ví dụ kiểm tra

- Với 100 agent, nhóm được hiển thị như `20 agent (20%)`.
- Session không có bài viết vẫn tồn tại trong lịch và vẫn được thực thi.
- Thay đổi lịch sau khi run bắt đầu phải bị từ chối.
- Hai scenario từ cùng một campaign có thể dùng bài viết, lịch, số agent và
  tham số khác nhau.
- Bài viết và sản phẩm của hai brand khác nhau không được bị ghi nhận như
  cùng một brand.
