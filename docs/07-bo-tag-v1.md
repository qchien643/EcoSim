# 07 — Bộ tag v1

## Trạng thái

Đây là bộ từ vựng tag đóng bản nháp cho ngành cafe:

[projectdut_cafe_tags.schema.json](../data/tags/projectdut_cafe_tags.schema.json)

LLM chỉ được trả về các `id` có trong file. Tag không phải action và không tự
quyết định `like`, `dislike`, `buy` hoặc `not_buy`. Comment chưa thuộc phạm vi
bản đầu.

Mapping tag doanh nghiệp và tag nội dung với các trường persona nằm riêng tại
[projectdut_cafe_tag_persona.mapping.json](../data/tags/projectdut_cafe_tag_persona.mapping.json).
Mapping hiện bao gồm `enterprise`, `article` và `product` tags. Nó dùng để
chọn context cho `enterprise_context`, `article_thought` và `product_thought`.
Nó chưa phải trọng số thuật toán chú ý, xác suất hành động hoặc quy tắc thay
đổi persona.

## Năm nhóm tag

- **Article tags:** chủ đề, phong cách trình bày và vai trò của bài trong chiến dịch.
- **Product tags:** loại sản phẩm, hương vị/cường độ, bối cảnh sử dụng, vị trí thương mại và lựa chọn ăn kiêng.
- **Enterprise tags:** danh tính công khai, định vị và đặc điểm công khai của doanh nghiệp/brand.
- **Thought tags:** cách agent diễn giải, đánh giá, hình thành động lực, nhận ra rào cản hoặc cân nhắc thời điểm.
- **Emotion tags:** phản ứng cảm xúc sau khi đọc bài hoặc chú ý đến món hàng.

Các nhóm có giới hạn số tag để output ổn định và tiết kiệm token. `max_tags`
chỉ giới hạn số lượng đầu ra; nó chưa phải quy tắc chọn action.

## Trạng thái mapping

- 41 tag enterprise/article/product có ít nhất một liên kết ứng viên tới persona.
- 24 tag enterprise/article/product ghi rõ chưa có trường phù hợp trong schema con hiện tại.
- 4 tag `role_*` được đánh dấu là metadata chiến dịch, không ánh xạ tới persona.
- Các liên kết có `primary` hoặc `supporting` priority; đây chỉ là mức ưu tiên
  chọn context, chưa phải điểm số.

## Chưa làm trong v1

- Chưa định nghĩa tag nào làm tăng/giảm điểm chú ý.
- Chưa dùng tag để thay thế quyết định trực tiếp của LLM.
- Chưa mapping thought/emotion tags sang persona hoặc thay đổi thuộc tính.
- Chưa triển khai ranking top-15 theo từng persona.
- Chưa chốt toàn bộ ý nghĩa nghiệp vụ của từng tag.

Mapping này là bản nháp cần review; các bước tiếp theo là review liên kết,
hoàn thiện logic chọn context theo từng persona, rồi mới xây policy chú ý và
LLM contracts.
