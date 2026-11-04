# 01 — Cách hiểu về sản phẩm

## Mục đích của bộ tài liệu

Đây là bản diễn giải để chủ dự án kiểm tra cách hiểu, chưa phải đặc tả đã chốt hay kế hoạch triển khai. Nguồn là [phacthaoduan.txt](../phacthaoduan.txt) và các làm rõ trong cuộc trao đổi.

- **Đã xác nhận**: yêu cầu có trong bản phác thảo hoặc được chủ dự án làm rõ.
- **Cách hiểu cần xác nhận**: cách nối các yêu cầu lại với nhau, chưa phải quyết định.
- **Chưa chốt**: bản phác thảo chưa xác định cơ chế.

Đọc tiếp: [Cơ chế mô phỏng](02-co-che-mo-phong.md) và [Luồng xử lý, lưu trữ](03-luong-xu-ly.md).

## Người dùng và mục đích

**Đã xác nhận:** người dùng hiện tại là marketer chuẩn bị triển khai chiến dịch.

Sản phẩm, tạm gọi là `projectDut2026`, mô phỏng phản ứng của khách hàng và xu hướng mua hàng khi họ tiếp xúc với chiến dịch qua nhiều phiên. Bản mô tả chiến dịch là nguồn đầu vào gốc; từ đó mỗi kịch bản có thể sinh và cấu hình một cách chạy riêng.

Đối tượng được quan sát không chỉ là lượt thích hoặc doanh thu cuối cùng, mà còn là quá trình: khách hàng chú ý điều gì, phản ứng ra sao, có ghé shop không, xem sản phẩm nào, có những tag suy nghĩ nào trước quyết định, rồi mua hoặc không mua. Hệ thống lưu cả suy nghĩ lẫn hành động để policy dùng lại khi đề xuất.

Việc sinh bài viết là một bước chuẩn bị cho mô phỏng, không phải toàn bộ sản phẩm. Cũng không phải mọi agent đều đi hết chuỗi đến mua hàng.

## Phạm vi ngành hàng

**Đã xác nhận:** sản phẩm mô phỏng phản ứng người dùng trong lĩnh vực bán hàng, có định hướng phục vụ nhiều ngành. **Ngành triển khai đầu tiên là cafe.**

Cafe là phạm vi nội dung và nghiệp vụ được triển khai trước, không phải giới hạn cố định của hệ thống hoặc cơ sở dữ liệu. Các khái niệm chung như chiến dịch, sản phẩm, shop, bài viết, agent và giao dịch không được thiết kế thành những đối tượng chỉ dùng cho cafe.

Thông tin riêng của ngành, chẳng hạn tag và đặc điểm sản phẩm cafe, cần phân biệt với phần dùng chung. Cách biểu diễn kỹ thuật chưa chốt; không mặc định dùng cùng một bộ tag hay cùng tham số hành vi cho mọi ngành.

**Đã xác nhận về hướng phát triển:** sau này có màn hình cho marketer chọn ngành. Hiện tại triển khai cafe trước, chưa cần xây các ngành khác hoặc màn hình chọn ngành ngay. Phạm vi cụ thể trong cafe, như đồ uống tại quán hay sản phẩm đóng gói, còn cần làm rõ.

## Chiến dịch, kịch bản và phiên

| Khái niệm | Cách hiểu |
| --- | --- |
| Chiến dịch | Bản mô tả chiến dịch, là nguồn gốc được dùng để sinh/cấu hình các thành phần mô phỏng. |
| Kịch bản | Một cách chạy cụ thể được tạo từ bản mô tả chiến dịch, gồm các tham số, nội dung sinh ra và trạng thái chạy riêng. |
| Lần chạy | Một lần thực hiện một kịch bản trong số phiên đã chọn. |
| Phiên | Đơn vị thời gian bên trong mô phỏng, không mặc định tương ứng với giờ, ngày hay đơn vị thời gian thực. |

**Đã xác nhận:** một bản mô tả chiến dịch có thể tạo ra nhiều kịch bản. Các kịch bản không bị giới hạn phải dùng chung bài viết, lịch đăng, tham số chú ý, số agent hay các tham số khác.

Ví dụ: cùng một bản mô tả chiến dịch cafe có thể tạo:

- Kịch bản A với một tập bài viết, lịch đăng, tham số chú ý và số agent.
- Kịch bản B với tập bài viết/lịch đăng được sinh hoặc chỉnh khác, tham số chú ý khác và số agent khác.

Các giá trị cụ thể thuộc cấu hình kịch bản, không phải thuộc bản mô tả chiến dịch.

Số phiên là thời lượng của một lần chạy và do marketer quy định trước. Mô phỏng kết thúc khi hoàn thành số phiên đó; không tự suy ra thời lượng từ giờ/ngày ngoài đời.

## Marketer cung cấp và kiểm soát gì?

**Đã xác nhận về nguồn và kịch bản:**

- Bản mô tả chiến dịch.
- Từ bản mô tả đó, hệ thống tạo ngân hàng bài viết dự kiến đăng, gian hàng/sản phẩm và các thành phần liên quan.
- Marketer sắp xếp các bài trong ngân hàng vào những phiên cố định; một phiên có thể có nhiều bài hoặc không có bài nào.
- Kịch bản chứa các tham số được chọn hoặc chỉnh trước khi chạy: ngân hàng bài viết, lịch đăng theo phiên, tham số chú ý, số agent, cơ cấu agent và số phiên.
- Marketer có thể duyệt/chỉnh các thành phần kịch bản trước khi chạy.
- Sau khi duyệt, lịch đăng được chốt và không thay đổi trong lúc mô phỏng.

**Chưa chốt:** cách biểu diễn đầy đủ bản mô tả chiến dịch; cách nhập/điều chỉnh danh mục sản phẩm, giá và thông tin gian hàng trong một kịch bản; cách chọn persona phù hợp với đối tượng của chiến dịch.

**Đã xác nhận:** cơ cấu khách hàng tách thành hai chiều: quan hệ với thương hiệu (vòng đời) và thái độ với thương hiệu. Không coi “đã mua” và “ghét thương hiệu” là hai nhóm loại trừ nhau; một agent có thể đồng thời thuộc cả hai.

### Cách phân chia khách hàng

Hai chiều đã thống nhất được diễn giải như sau:

| Vòng đời với thương hiệu | Thái độ ban đầu có thể chọn | Lưu ý |
| --- | --- | --- |
| Chưa biết thương hiệu | Chưa hình thành thái độ | Không đồng nhất với trung lập sau khi đã biết; vẫn có sở thích về cafe. |
| Đã biết, chưa mua | Tích cực / trung lập / tiêu cực | Tiêu cực có thể đến từ thông tin đã tiếp xúc, không bịa trải nghiệm mua. |
| Đã mua trước đó | Tích cực / trung lập / tiêu cực | Có thể thích, không có ấn tượng hoặc thất vọng sau trải nghiệm. |

### Cách marketer cấu hình cơ cấu

Marketer chọn những nhóm muốn đưa vào mô phỏng. Nhóm được xác định từ hai chiều trên, chẳng hạn “đã biết nhưng chưa mua + tích cực” hoặc “đã mua + tiêu cực”; các nhóm không chọn không được tạo agent trong cơ cấu đó.

Với mỗi nhóm đã chọn, marketer có thể nhập **tỷ lệ phần trăm** hoặc **số lượng agent cụ thể**. Hệ thống luôn tính và hiển thị đồng thời cả hai giá trị để marketer kiểm tra, cùng tổng số agent của kịch bản. Cách nhập không làm thay đổi mô hình hai chiều; đó chỉ là hai cách biểu diễn cùng một cơ cấu.

Ví dụ với 100 agent, marketer có thể chọn nhóm “đã biết nhưng chưa mua + tích cực” ở mức 20% hoặc 20 agent; giao diện phải hiển thị cả `20 agent (20%)`. Tổng số agent được phân bổ phải khớp với quy mô kịch bản; phần chưa phân bổ cần được thể hiện rõ trước khi chạy.

Ví dụ minh họa với 100 agent: 40 chưa biết; 35 đã biết chưa mua gồm 10 tích cực, 15 trung lập, 10 tiêu cực; 25 đã mua gồm 15 tích cực, 5 trung lập, 5 tiêu cực. Tổng cộng 15 người tiêu cực, nhưng vẫn biết họ nằm ở giai đoạn nào.

**Đề xuất bổ sung, chưa chốt:** các quy tắc khởi tạo và cập nhật dưới đây không mặc nhiên được xác nhận cùng việc tách hai chiều.

Người tiêu cực có tag lý do và đối tượng liên quan: thương hiệu hay sản phẩm cụ thể. Ví dụ cần tách “không thích vị đắng” khỏi “từng thất vọng về đồ uống X”. Người chưa mua không được gán lý do “từng mua và thất vọng”. Danh mục lý do do sản phẩm định nghĩa, không cho model tự thêm tag.

Sở thích cafe, độ nhạy giá và mức hoạt động lấy từ persona hoặc giả định kịch bản được khai báo; không coi là các nhóm vòng đời bổ sung. Chưa cần thêm nhóm “trung thành”, “rời bỏ” nếu chưa định nghĩa đủ lịch sử mua.

Lưu cấu hình và nhóm khởi tạo để so sánh cohort, đồng thời lưu trạng thái hiện tại. Khi đọc bài lần đầu hoặc mua lần đầu, agent có thể chuyển vòng đời; thái độ không tự tăng chỉ vì đã mua. Cách phân bổ số nguyên khi tỷ lệ không cho ra số agent nguyên sẽ dùng một quy tắc xác định, không làm thay đổi tổng số agent.

## Những thành phần hiện diện trong mô phỏng

- **Agent công ty:** đại diện doanh nghiệp do người dùng điều khiển; nhận mô tả chiến dịch, có tập bài viết và gian hàng để phục vụ chiến dịch.
- **Agent khách hàng:** dựa trên persona, có đặc điểm, lịch sử và phản ứng riêng; chỉ một phần agent hoạt động trong mỗi phiên.
- **Mạng xã hội mô phỏng:** nơi bài quảng cáo xuất hiện và tích lũy like/dislike của agent.
- **Shop mô phỏng:** nơi agent chú ý sản phẩm, chọn tag suy nghĩ rồi quyết định mua hoặc không mua. Cả `buy` và `not_buy` đều được lưu thành hành động, cùng tag suy nghĩ trước quyết định. Thuật toán chú ý dùng trực tiếp lịch sử này qua policy deterministic đã định nghĩa, không thêm bước phân tích hay phân loại sau `not_buy`.

Người ghét vẫn có thể chú ý bài viết, đọc hoặc ghé shop. Không dùng “không thích” làm điều kiện tự động loại họ khỏi chuỗi tương tác.

## Trải nghiệm người dùng

Ba màn hình đã được mô tả:

1. **Nhập chiến dịch:** tải bản mô tả và chọn các điều chỉnh.
2. **Duyệt nội dung:** xem, sửa ngân hàng bài viết và sắp xếp bài vào lịch đăng theo phiên; chốt lịch trước khi chạy.
3. **Xem mô phỏng:** bên trái là mạng xã hội ảo, bên phải là biểu đồ; tương tác và số liệu thay đổi theo các phiên đã hoàn tất.

Giao diện tạo cảm giác đang theo dõi diễn biến trực tiếp, nhưng dùng dữ liệu phiên đã lưu trong khi hệ thống tiếp tục tính phiên tiếp theo.

Marketer có thể đối chiếu kết quả giữa các kịch bản, nhưng không có yêu cầu mặc định rằng một số thành phần phải giữ nguyên. Khi cần một thử nghiệm có kiểm soát, marketer có thể sao chép một kịch bản rồi chỉ thay một vài tham số; đó là cách sử dụng tùy chọn, không phải ràng buộc của hệ thống.

## Ranh giới của bản mô tả

Đã chốt cafe là ngành đầu tiên và deterministic kết hợp LLM là nguyên tắc xử lý. Số agent, tham số chú ý, bài viết và lịch đăng thuộc kịch bản, không phải thuộc nguồn chiến dịch. Chưa chốt công nghệ, công thức chú ý hay toàn bộ phạm vi MVP. Chưa khẳng định doanh thu mô phỏng sẽ bằng doanh thu ngoài thực tế; cách kiểm chứng mức độ dự đoán là vấn đề còn phải bàn, không phải lý do bỏ mục tiêu phân tích xu hướng mua hàng.
