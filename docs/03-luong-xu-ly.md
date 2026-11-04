# 03 — Luồng xử lý, lưu trữ và các điểm cần làm rõ

Đọc cùng [mô tả sản phẩm](01-san-pham.md) và [các cơ chế](02-co-che-mo-phong.md). Đã chốt hướng đa ngành và deterministic kết hợp LLM; tài liệu chưa chọn công nghệ hay schema cơ sở dữ liệu cụ thể.

## 1. Từ chiến dịch đến một kịch bản chạy

Luồng tổng quát đã có trong bản phác thảo:

1. Nhận bản mô tả chiến dịch làm nguồn đầu vào gốc.
2. Tạo một kịch bản từ bản mô tả: chuẩn bị ngân hàng bài viết, shop/sản phẩm có tag và các thành phần cần thiết.
3. Gắn vào kịch bản các tham số: ngân hàng bài viết, lịch phân bổ bài theo phiên, tham số chú ý, số agent, cơ cấu agent và số phiên.
4. Cho marketer duyệt/chỉnh các thành phần của kịch bản, phân bổ bài vào từng phiên và chốt lịch.
5. Chuẩn bị tập agent theo kịch bản và chạy đúng số phiên đã quy định, ghi lại diễn biến và cập nhật giao diện.

Thứ tự kỹ thuật giữa chuẩn bị agent, tạo shop và sinh nội dung chưa được chốt. Các bước trên mô tả các đầu việc, không bắt buộc tất cả phải chạy nối tiếp.

Mỗi kịch bản có bài viết, lịch đăng, tham số chú ý, số agent, cơ cấu agent và trạng thái chạy riêng. Bản mô tả chiến dịch là nguồn chung duy nhất giữa các kịch bản; không tự kế thừa trạng thái agent hoặc thành phần đã sinh từ kịch bản khác.

Sau khi marketer chốt, lịch đăng là bất biến trong lần chạy đó. Một phiên có thể có nhiều bài hoặc không có bài; cả hai trường hợp đều được thực thi theo đúng cấu hình và không làm thay đổi số phiên mô phỏng.

Nếu marketer muốn so sánh có kiểm soát, có thể sao chép một kịch bản rồi thay đúng tham số cần thử. Hệ thống không tự quyết định phải giữ cohort, bài viết, lịch đăng hay số agent giống nhau.

## 2. Vòng lặp một phiên

### A. Chuẩn bị

- Chọn các agent hoạt động dựa trên xác suất/tần suất của họ.
- Lấy đúng danh sách bài đã được marketer xếp cho phiên hiện tại; danh sách có thể rỗng hoặc có nhiều bài, không bốc lại bằng xác suất.
- Chuẩn bị danh sách bài cho từng agent dựa trên đặc điểm, lịch sử, nội dung đang có và khả năng xem.

### B. Mô phỏng

- Agent gặp mô tả bài, chọn tag cảm xúc/trạng thái ban đầu, đọc bài và chọn tag sau khi đọc.
- Agent quyết định phản ứng và có ghé shop hay không. Comment chưa thuộc phạm
  vi bản đầu.
- Nếu ghé shop, JEV đánh giá toàn bộ sản phẩm hợp lệ trong shop; sản phẩm
  nhận đủ chú ý mới trải qua chuỗi LLM ngắn hơn: tag suy nghĩ trước khi xem →
  tag cảm xúc sau khi xem → action `buy` hoặc `not_buy`.
- Lưu tag suy nghĩ trước quyết định và hành động `buy` hoặc `not_buy`. `not_buy` cũng là một bản ghi hành động, không phải sự vắng mặt của giao dịch.
- Khi đề xuất tiếp theo, policy áp dụng trực tiếp quy tắc đã định nghĩa cho lịch sử tag và hành động. Không có bước phân tích sau `not_buy` hoặc lựa chọn thứ ba.
- Ghi nhận cả các nhánh không tương tác và không ghé shop; không tự biến việc chưa xem/chưa quyết định thành hành động không mua.

Các lựa chọn đều diễn ra theo cơ chế của agent; không coi chuỗi trên là yêu cầu mọi agent phải thực hiện mọi hành động.

### C. Kết thúc phiên

- Lưu các bài đã đọc và chuỗi suy nghĩ/hành động của từng agent.
- Lưu diễn biến chú ý sản phẩm, tag suy nghĩ trước quyết định và hành động `buy`/`not_buy` để policy thuật toán chú ý dùng lại.
- Ghi nhận các trường persona đổi mức enum, gồm giá trị trước và sau cập nhật, nếu có.
- Tính và lưu số liệu tổng hợp của phiên.
- Cung cấp dữ liệu đã lưu cho giao diện; tiếp tục xử lý phiên sau trong khi giao diện hiển thị diễn biến phiên vừa hoàn tất.

Comment chưa được mô phỏng trong bản đầu. Khi được triển khai, agent không
được thấy comment của agent khác; comment chỉ phục vụ phân tích của marketer.

**Chưa chốt:** agent cập nhật tag/thuộc tính ngay sau từng tương tác hay ở cuối phiên; các agent xử lý tuần tự hay đồng thời.

## 3. Những thông tin cần ghi lại

**Đã xác nhận:** lưu chuỗi suy nghĩ và hành động có thứ tự theo agent, phiên và bài viết; nếu agent vào shop thì lưu tiếp chuỗi tương ứng với sản phẩm.

Các mối liên hệ cần thể hiện được:

- Agent nào đọc bài nào, trong phiên nào.
- Bộ tag cảm xúc/trạng thái trước và sau khi đọc.
- Phản ứng với bài và quyết định ghé shop.
- Sau bài nào agent ghé shop; tag khi đọc món hàng, context dùng cho quyết định và quyết định sau khi xem.
- Sản phẩm nào được mua hoặc không mua; liên kết hành động đó với đúng bộ tag suy nghĩ đã có trước quyết định.
- Trường persona nào được cập nhật, giá trị enum cũ và mới; không nhầm lịch sử suy nghĩ với một sản phẩm cụ thể thành một thuộc tính chung của toàn bộ persona.
- Thứ tự các bước để có thể xem lại diễn biến.

Không thay yêu cầu lưu suy nghĩ bằng cách chỉ lưu điểm số rồi sinh lời giải thích sau. Có thể bổ sung dữ liệu có cấu trúc để phân tích, nhưng đó là phần bổ sung cần thống nhất.

**Cách hiểu cần xác nhận:** khi chạy nhiều kịch bản, dữ liệu phải phân biệt được chiến dịch, kịch bản và từng lần chạy để không trộn lịch sử hoặc số liệu. Chưa thiết kế bảng dữ liệu, định dạng log hay hệ lưu trữ.

## 4. Dashboard và phát lại diễn biến

**Đã xác nhận:** có biểu đồ biến động theo phiên về doanh thu, sức mua từng sản phẩm và các chỉ số truyền thông/marketing được lựa chọn. Các chỉ số được tính, lưu sau từng phiên để phục vụ hiển thị.

Bài viết trên mạng xã hội ảo hiển thị trạng thái like/dislike và các thay đổi
phản ứng được cập nhật theo diễn biến phiên.

**Cách hiểu cần xác nhận:** số liệu hiển thị phải phân biệt phần phát sinh trong một phiên với phần lũy kế. Các chỉ số như lượt ghé shop, tỷ lệ mua, nhóm khách hàng chuyển thái độ có thể hữu ích, nhưng chưa coi là danh sách dashboard đã chốt.

“Livestream” ở đây là cách trình bày dữ liệu mô phỏng đã hoàn tất từng phiên, không yêu cầu người dùng chờ agent tính đến đâu mới được hiển thị từng bước đến đó. Tốc độ phát lại và cách đồng bộ biểu đồ với bài viết còn mở.

## 5. Một tình huống để kiểm tra cách hiểu

Đây chỉ là ví dụ, không thêm luật vào mô phỏng:

> Một agent vốn không thích thương hiệu vẫn được đánh giá chú ý bài vì chủ đề khiến họ chú ý. Agent đọc bài, dislike, sau đó quyết định vào shop để xem thông tin. Agent chú ý sản phẩm mới nhưng không mua. Hệ thống giữ lại chuỗi suy nghĩ, phản ứng và việc không mua này. Ở phiên sau, lịch sử đó được policy chú ý sử dụng lại.

Ví dụ minh họa: agent xem sản phẩm P, chọn một tag có nghĩa “muốn thử lần sau”, rồi quyết định `not_buy`. Hệ thống lưu tag trước quyết định và hành động `not_buy` theo sản phẩm P. Khi đề xuất tiếp theo, nếu policy đã quy định tag này tăng điểm trong trường hợp chưa mua, hệ thống áp dụng trực tiếp quy tắc đó. Không gọi model phân tích lại, không sinh nhãn “tiềm năng mua”; nếu agent lại xem P, quyết định vẫn chỉ là `buy` hoặc `not_buy`.

Trong cùng chiến dịch, marketer có thể thử kịch bản khác với tham số khác. Tài liệu không mặc định agent sẽ đổi thái độ hoặc kết quả sẽ tốt hơn.

## 6. Những quyết định còn mở

Các điểm dưới đây là để thảo luận dần, không yêu cầu phải trả lời toàn bộ ngay:

1. **Thay đổi thuộc tính:** whitelist trường nào, ngưỡng bằng chứng và mức suy giảm nào phù hợp?
2. **Contract phản ứng:** tên trường JSON và validation cụ thể cho `like`,
   `dislike`, `keep_current`, `remove_reaction` và `no_reaction`.
3. **Ảnh hưởng trong phiên:** bản đầu đã chốt agent không thấy comment của agent khác; có dùng số lượng tương tác như tín hiệu xếp hạng hay không?
4. **Thuật toán chú ý sản phẩm:** policy ánh xạ từng tag suy nghĩ và hành động sang tác động chú ý thế nào; mức giảm sau mua, cách kết hợp nhiều lần xem và thời hạn tác động là gì?

Chưa thêm cơ chế ngoài phác thảo như đối thủ cạnh tranh, đấu giá quảng cáo, thanh toán thật hoặc tự động đăng ra mạng xã hội thật.

## 7. Contract cho các lần gọi LLM

**Đã xác nhận:** mỗi nhiệm vụ LLM cần đầu vào có chọn lọc và contract đầu ra, không nhận toàn bộ hồ sơ/lịch sử theo mặc định hoặc trả văn bản tùy ý cho phần xử lý phía sau. Tag cảm xúc/trạng thái là đầu ra có cấu trúc thay cho đoạn suy nghĩ tự do.

**Cách cụ thể hóa đề xuất:** mỗi contract xác định các trường bắt buộc, kiểu dữ liệu, enum được phép, đối tượng được tham chiếu và giới hạn độ dài phần diễn giải. Ví dụ:

| Nhiệm vụ | Context cần thiết | Đầu ra cần ràng buộc |
| --- | --- | --- |
| Comment | Chưa thuộc phạm vi bản đầu | Sẽ bổ sung contract khi mở tính năng. |
| Suy nghĩ khi gặp bài | Mô tả người dùng/tính cách đã chọn lọc và mô tả bài dựa trên tag | List tag suy nghĩ theo contract. |
| Cảm xúc khi đọc bài | Flow đang đọc bài, tag suy nghĩ và nội dung bài | List tag cảm xúc theo contract. |
| Phản ứng với bài | Flow vừa đọc bài và tag cảm xúc sau khi đọc | LLM trả phản ứng theo contract; lần đầu là `like`, `dislike`, `no_reaction`; lần sau là `keep_current`, `remove_reaction`, `no_reaction`. |
| Suy nghĩ khi gặp món hàng | Mô tả người dùng/tính cách đã chọn lọc và mô tả món hàng dựa trên tag | List tag suy nghĩ theo contract. |
| Cảm xúc khi xem món hàng | Flow đang xem món hàng, tag suy nghĩ và mô tả sản phẩm cần thiết | List tag cảm xúc theo contract. |
| Quyết định mua | Flow vừa xem món hàng, tag cảm xúc sau khi xem và context sản phẩm cần thiết | LLM trực tiếp trả `buy` hoặc `not_buy`; không có action thứ ba. |
| Đề xuất cập nhật persona | Các trường ứng viên, giá trị hiện tại, enum hợp lệ và trải nghiệm liên quan | Những trường đề nghị đổi cùng giá trị mới hợp lệ; cho phép không thay đổi. |

Bảng này chưa ấn định tên trường JSON và danh mục tag. Riêng chuỗi phản ứng với bài đã rõ ba lời gọi LLM tách biệt, với context đúng theo ba bước trên.

Thuật toán chú ý dùng lại lịch sử tag suy nghĩ và hành động bằng policy deterministic. Đây không phải nhiệm vụ LLM và không có contract phân tích cảm xúc sau `not_buy`.

Luồng đề xuất: **chọn context → gọi LLM → kiểm tra contract và quy tắc nghiệp vụ → áp dụng kết quả hợp lệ → lưu diễn biến**.

Đầu ra sai định dạng, tham chiếu sai đối tượng hoặc vi phạm quy tắc không được tự tạo hành động hay làm hỏng trạng thái. Cách thử lại, giới hạn số lần và xử lý khi vẫn thất bại còn cần thống nhất. Nội dung chiến dịch/bài viết/sản phẩm là dữ liệu đầu vào, không được phép ghi đè contract hoặc quy tắc hệ thống.

Mô phỏng vẫn có thể lấy mẫu ở bước chọn agent hoạt động. **Đề xuất:** dùng seed cho các bước ngẫu nhiên đã xác định và lưu kết quả LLM để phát lại. Điều này không thêm bước lấy mẫu hoặc argmax thay LLM chọn phản ứng.

## 8. Chuỗi quyết định bằng các lời gọi LLM có context riêng

Thay cho đề xuất chấm điểm và policy chọn action trước đây của trợ lý, cơ chế đã được chủ dự án làm rõ:

1. **Bài viết — lời gọi 1:** mô tả người dùng/tính cách liên quan + mô tả bài dựa trên tag → list tag suy nghĩ.
2. **Bài viết — lời gọi 2:** flow “đang đọc bài” + tag suy nghĩ + nội dung bài → list tag cảm xúc.
3. **Bài viết — lời gọi 3:** flow “vừa đọc bài” + tag cảm xúc → phản ứng theo
   contract; comment chưa thuộc bản đầu.
4. **Món hàng — lời gọi 1:** mô tả người dùng/tính cách liên quan + mô tả món hàng dựa trên tag → list tag suy nghĩ.
5. **Món hàng — lời gọi 2:** flow “đang xem món hàng” + tag suy nghĩ + mô tả sản phẩm cần thiết → list tag cảm xúc.
6. **Món hàng — lời gọi 3:** flow “vừa xem món hàng” + tag cảm xúc → action `buy` hoặc `not_buy` trong structured output.

Trong mỗi chuỗi, thông tin persona được chọn lọc chủ yếu đưa vào lời gọi đầu. Nội dung bài chỉ đưa vào lời gọi đọc bài; thông tin sản phẩm cần thiết chỉ đưa vào lời gọi xem món hàng/quyết định mua theo contract. Lời gọi action không nhận toàn bộ dữ liệu mô phỏng hoặc lịch sử ngoài context đã định nghĩa.

LLM chọn phản ứng hoặc quyết định mua; hệ thống validate contract và lưu các tag/action theo đúng agent, đối tượng và thứ tự. Không thay một phản ứng/quyết định hợp lệ bằng kết quả chấm điểm deterministic. Action mua luôn chỉ gồm `buy` hoặc `not_buy`. Khi phản ứng lặp lại, `keep_current` giữ trạng thái hiện tại, `remove_reaction` gỡ trạng thái hiện tại và `no_reaction` không tạo thay đổi.

Với shop, tập lựa chọn là `buy`, `not_buy`; cả hai đều được ghi vào lịch sử hành động cùng liên kết tới tag suy nghĩ trước quyết định. Ở lần đề xuất sau, policy tra trực tiếp quy tắc theo tag và lịch sử hành động để tăng/giảm điểm sản phẩm, không phân tích lại cảm xúc hoặc tạo trạng thái trung gian sau `not_buy`.

Policy deterministic vẫn có thể dùng tag và action đã lưu cho các tác vụ phân
 tích chú ý sau này, nhưng không chọn trước bài viết/sản phẩm trong flow bản đầu.

## 9. Không khóa thiết kế vào cafe

**Đã xác nhận:** hệ thống và cơ sở dữ liệu phải hỗ trợ bổ sung ngành sau này, dù hiện tại chỉ triển khai cafe.

**Nguyên tắc thiết kế đề xuất:**

- Giữ các đối tượng chiến dịch, kịch bản, shop, sản phẩm, bài viết và tương tác ở mức khái niệm chung; ghi nhận ngữ cảnh ngành khi cần.
- Tách đặc điểm riêng của ngành khỏi phần dùng chung. Ví dụ thuộc tính như mức rang không trở thành trường bắt buộc cho mọi sản phẩm của mọi ngành.
- Phần thay đổi theo ngành có thể gồm danh mục/tag, thông tin sản phẩm và tham số/quy tắc chuyên biệt; không mặc định chỉ thay tên ngành là đủ.
- Contract hành động chung không chứa tên riêng cafe; context cung cấp thông tin ngành và sản phẩm liên quan.

Chưa chọn bảng thuộc tính động, cột JSON hay hệ plugin. Cách làm tối thiểu là giữ ranh giới chung/riêng rõ ràng, triển khai cafe trước, không xây sẵn những ngành chưa cần.
