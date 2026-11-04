# Đặc tả yêu cầu hệ thống — projectDut2026

**Trạng thái:** Bản nháp đang review  
**Người dùng chính:** Marketer  
**Ngành triển khai đầu tiên:** Cafe  
**Đơn vị mô phỏng:** Phiên; không bắt buộc tương ứng với đơn vị thời gian thật.

## 1. Mục đích sản phẩm

Sản phẩm mô phỏng cách các agent khách hàng chú ý đến nội dung chiến dịch,
đọc hoặc xem nội dung, phản ứng, ghé shop, mua hoặc không mua sản phẩm qua
nhiều phiên do marketer quy định.

Sản phẩm phải thể hiện được cả kết quả và quá trình: mức độ chú ý, lịch sử
tiếp xúc, tag suy nghĩ, tag cảm xúc, phản ứng, lượt ghé shop, lượt xem sản
phẩm, mua và không mua.

Đây là một mô hình phân tích. Doanh thu và hành vi mô phỏng không được trình
bày như kết quả chắc chắn của thế giới thật.

## 2. Thông tin doanh nghiệp và thương hiệu

**Bản nháp bổ sung:** đã xác định thiếu context doanh nghiệp; cách phân lớp
organization/brand/shop và danh mục thông tin dưới đây là đề xuất cần review,
không mặc định yêu cầu triển khai nhiều thương hiệu trong bản đầu.

Campaign không chỉ mô tả nội dung muốn quảng cáo. Campaign phải xác định
doanh nghiệp hoặc tổ chức đứng sau hoạt động quảng cáo và danh tính mà agent
nhìn thấy trên mạng xã hội hoặc trong shop.

Trong bản đầu, cần phân biệt ba lớp:

- **Organization:** doanh nghiệp hoặc tổ chức sở hữu hoạt động quảng cáo.
- **Brand:** danh tính công khai mà khách hàng nhận biết; có thể trùng với
  organization ở bản đầu.
- **Shop:** nơi doanh nghiệp/brand giới thiệu và bán sản phẩm trong mô phỏng.

Thông tin doanh nghiệp/brand có hai loại:

- **Thông tin công khai:** tên hiển thị, mô tả thương hiệu, lĩnh vực, định vị,
  lời hứa hoặc thông điệp mà agent có thể biết qua bài viết và shop.
- **Thông tin nội bộ:** mục tiêu campaign, cấu hình mô phỏng, nhóm khách hàng
  muốn phân tích và các ghi chú chỉ dành cho marketer.

Chỉ thông tin công khai phù hợp với tình huống mới được đưa vào context agent.
Không đưa hướng dẫn nội bộ của marketer vào context chỉ vì nó tồn tại trong
campaign.

Thông tin công khai không đồng nghĩa mọi agent đã biết. Context phải phân biệt
thông tin đang hiển thị trong lần tiếp xúc với thông tin agent đã biết từ
trạng thái khởi tạo hoặc lịch sử trước đó. Lời hứa của thương hiệu là tuyên bố
của bên quảng cáo, không tự trở thành niềm tin của agent.

Quan hệ của agent với thương hiệu phải được gắn với đúng organization/brand.
Các trạng thái như chưa biết, đã biết, đã mua, tích cực hoặc tiêu cực không
được tồn tại như một thái độ chung không có đối tượng.

## 3. Người dùng và actor

### Marketer

Marketer phải có khả năng:

- cung cấp bản mô tả chiến dịch;
- tạo một hoặc nhiều kịch bản từ chiến dịch;
- xem và chỉnh sửa bài viết, sản phẩm được chuẩn bị;
- chọn các nhóm khách hàng và số lượng của từng nhóm;
- phân bổ bài viết vào các phiên cố định;
- cấu hình số phiên và các tham số của kịch bản;
- bắt đầu mô phỏng sau khi kiểm tra cấu hình;
- xem kết quả theo phiên và các chỉ số tổng hợp.

### Agent khách hàng

Agent đại diện cho một khách hàng mô phỏng, có persona, quan hệ với thương
hiệu, thái độ, lịch sử và hành vi riêng theo từng phiên.

### Doanh nghiệp

Doanh nghiệp cung cấp chiến dịch, bài viết, shop và sản phẩm. Doanh nghiệp
không phải là agent khách hàng.

## 4. Các khái niệm chính

- **Organization:** doanh nghiệp hoặc tổ chức sở hữu campaign và hoạt động
  quảng cáo.
- **Brand:** danh tính công khai mà agent nhận biết trong campaign.
- **Campaign:** bản mô tả chiến dịch chung do marketer cung cấp, thuộc về một
  organization và được triển khai dưới một brand.
- **Scenario:** một cấu hình mô phỏng cụ thể được tạo từ campaign.
- **Run:** một lần chạy của một scenario.
- **Session:** một đơn vị mô phỏng bên trong một run.
- **Post:** bài viết thuộc chiến dịch, có thể được đăng trong một session.
- **Shop:** không gian bán hàng thuộc về organization/brand.
- **Product:** sản phẩm có trong shop mô phỏng.
- **Attention:** mức độ agent chú ý đến bài viết hoặc sản phẩm. Đây không phải
  là lượt thích, xác suất mua hay thứ hạng của feed mạng xã hội.
- **Event history:** chuỗi có thứ tự ghi lại việc tiếp xúc, suy nghĩ, cảm xúc,
  hành động, ghé shop, xem sản phẩm và mua hàng.

## 5. Yêu cầu chức năng

Nhóm `SRS-ORG-*` là yêu cầu bổ sung bản nháp, cần review cùng mục 2.

| ID | Yêu cầu |
| --- | --- |
| SRS-ORG-01 | Hệ thống phải gắn mỗi campaign với doanh nghiệp hoặc tổ chức đứng sau hoạt động quảng cáo. |
| SRS-ORG-02 | Hệ thống phải xác định danh tính brand mà agent nhìn thấy trong bài viết và shop. |
| SRS-ORG-03 | Bài viết, shop và sản phẩm trong scenario phải truy được về đúng organization/brand. |
| SRS-ORG-04 | Lịch sử quan hệ của agent phải được gắn với đúng organization/brand, không lưu như thái độ chung. |
| SRS-ORG-05 | Hệ thống phải phân biệt thông tin công khai mà agent có thể biết với thông tin nội bộ chỉ dành cho marketer. |
| SRS-CAM-01 | Hệ thống phải nhận bản mô tả chiến dịch làm nguồn chung để tạo các scenario. |
| SRS-CAM-02 | Một campaign phải hỗ trợ nhiều scenario độc lập. |
| SRS-SCN-01 | Mỗi scenario phải có bài viết, sản phẩm, cơ cấu khách hàng, tham số, lịch và số phiên riêng. |
| SRS-SCN-02 | Marketer phải được xem và chỉnh sửa nội dung của scenario trước khi chạy. |
| SRS-SCN-03 | Marketer phải được phân bổ không, một hoặc nhiều bài viết vào từng session cố định. |
| SRS-SCN-04 | Lịch phải được khóa sau khi run bắt đầu. |
| SRS-SCN-05 | Run phải kết thúc sau số session đã cấu hình. |
| SRS-CUS-01 | Marketer phải được chọn nhóm khách hàng theo hai chiều vòng đời và thái độ. |
| SRS-CUS-02 | Marketer phải được nhập tỷ lệ phần trăm hoặc số lượng cụ thể cho mỗi nhóm. |
| SRS-CUS-03 | Hệ thống phải hiển thị đồng thời số lượng, phần trăm và phần chưa phân bổ nếu có. |
| SRS-SIM-01 | Hệ thống phải xác định các agent hoạt động trong từng session. |
| SRS-SIM-02 | Hệ thống phải gọi cơ chế chú ý cho toàn bộ bài viết hợp lệ trong nền tảng và toàn bộ sản phẩm hợp lệ trong shop, rồi xác định đối tượng nào nhận đủ sự chú ý của từng agent. |
| SRS-SIM-03 | Agent có thái độ tiêu cực vẫn phải có khả năng chú ý và đọc nội dung chiến dịch. |
| SRS-SIM-04 | Hệ thống phải lưu cả action `buy` và `not_buy`. |
| SRS-SIM-05 | Comment chưa thuộc phạm vi bản đầu; khi được bổ sung, hệ thống không được cho agent này xem comment của agent khác. |
| SRS-REC-01 | Hệ thống phải lưu event history có thứ tự cho từng agent và session. |
| SRS-REC-02 | Hệ thống phải liên kết quyết định sản phẩm với các thought tag ngay trước quyết định đó. |
| SRS-UI-01 | Hệ thống phải hiển thị riêng kết quả theo session và kết quả lũy kế khi có cả hai. |
| SRS-UI-02 | Hệ thống phải hiển thị chỉ số tương tác chiến dịch và chỉ số mua sản phẩm để phân tích. |

## 6. Quy tắc nghiệp vụ

1. Bản mô tả campaign là đầu vào chung; scenario sở hữu cấu hình và trạng
   thái chạy riêng.
2. Session có thể không có bài viết và vẫn là một session hợp lệ.
3. Chú ý, đọc, thích, không thích, không phản ứng, ghé shop và mua là các sự kiện khác nhau. Comment chưa thuộc phạm vi bản đầu.
4. Phản ứng tiêu cực không tự động loại agent khỏi các lần tiếp xúc sau.
5. `not_buy` nghĩa là không mua trong lần xem sản phẩm đó, không phải từ chối
   vĩnh viễn.
6. Một agent có thể đã mua sản phẩm nhưng vẫn có thái độ tiêu cực với thương
   hiệu.
7. Comment chưa được mô phỏng trong bản đầu; nếu bổ sung sau này, comment chỉ phục vụ marketer phân tích và không hiển thị cho agent khác.
8. Ngành đầu tiên là cafe, nhưng các khái niệm dùng chung phải hỗ trợ ngành
   khác về sau.
9. Danh tính doanh nghiệp/brand là một phần của context khi agent tiếp xúc với
   bài viết, shop hoặc sản phẩm, nếu danh tính đó xuất hiện trong tình huống.
10. Thái độ và vòng đời của agent luôn có đối tượng là organization/brand cụ
    thể.

## 7. Phạm vi chưa bao gồm trong bản nháp

- đăng nội dung lên mạng xã hội hoặc shop thật;
- xử lý thanh toán thật;
- nội dung đối thủ hoặc đấu giá quảng cáo;
- cam kết mô phỏng tái tạo chính xác doanh thu thật;
- quy định công thức attention hoặc nhà cung cấp model cụ thể;
- quy định schema cơ sở dữ liệu.

## 8. Yêu cầu còn mở

Các điểm sau cần làm rõ trước khi SRS được xem là ổn định:

- Những trạng thái attention nào phải được lưu và hiển thị: chưa thấy, lướt
  qua, đã đọc?
- Bộ chỉ số dashboard tối thiểu gồm những gì?
- Một scenario có thể chạy lại với cùng agent và trạng thái ban đầu không?
- Khi một run hoặc một lời gọi model thất bại, hệ thống phải xử lý thế nào?
- Mức độ giải thích nào cần đi kèm với kết quả attention hoặc mua hàng?
- Phạm vi sản phẩm cafe nào thuộc bản phát hành đầu tiên?
- Một campaign trong bản đầu có được quảng bá nhiều brand của cùng một
  organization hay chỉ một brand?
- Organization và brand có cần là hai đối tượng độc lập ngay từ bản đầu hay
  có thể dùng cùng một hồ sơ khi chúng trùng nhau?
