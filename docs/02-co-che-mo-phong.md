# 02 — Cơ chế mô phỏng theo bản phác thảo

Tài liệu này dùng các nhãn trạng thái được định nghĩa trong [mô tả sản phẩm](01-san-pham.md). Không coi công thức hoặc thiết kế chưa được thảo luận là yêu cầu đã chốt.

## Nguyên tắc xuyên suốt: deterministic kết hợp LLM

**Đã xác nhận:** không giao toàn bộ mô phỏng cho LLM. Kết hợp xử lý theo quy tắc/công thức xác định với LLM; mỗi lần gọi chỉ nhận thông tin cần thiết cho nhiệm vụ và phải có contract đầu ra rõ ràng.

Mục tiêu là giảm token không cần thiết, chi phí và thời gian xử lý mà vẫn giữ đủ context cho quyết định. “Tối thiểu” không có nghĩa bỏ lịch sử suy nghĩ và hành động với sản phẩm, đặc điểm liên quan hoặc thông tin bắt buộc ở bước đang thực hiện.

**Đã xác nhận:** suy nghĩ nội bộ của agent không phải một đoạn văn tự do. Chủ dự án sẽ thiết kế bộ tag; agent chọn tag trong bộ này để mô tả cảm xúc. Văn bản tự nhiên vẫn dùng cho bài viết; comment nếu được bổ sung ở giai đoạn sau sẽ có contract riêng.

Một bộ tag suy nghĩ nên có contract đóng, có thể gồm các nhóm:

- `emotion`: tò mò, thích thú, vui, lo lắng, khó chịu, tức giận, thất vọng, thờ ơ.
- `appraisal`: phù hợp, không phù hợp, đáng tin, đáng ngờ, hữu ích, phóng đại.
- `motivation`: muốn tìm hiểu, muốn thử, muốn cảnh báo, muốn phản đối, muốn bỏ qua.
- `barrier`: giá, chất lượng, thói quen, thiếu tin tưởng, chưa cần, đã có lựa chọn khác.

Các nhóm ngoài cảm xúc là đề xuất mở rộng, chưa phải danh mục tag cuối cùng và không thay việc chủ dự án thiết kế bộ tag. Có thể giới hạn số tag, thêm cường độ enum và đối tượng được đánh giá. Không cho LLM tự tạo tag mới trong lúc chạy; không dùng tag “mua” làm cảm xúc rồi coi quyết định mua là đã được giải quyết.

**Phân công đã làm rõ cho chuỗi phản ứng:**

- **Deterministic:** chuẩn bị context chọn lọc, xác định phạm vi đối tượng cho thuật toán chú ý, kiểm tra contract, cập nhật dữ liệu và tính chỉ số.
- **LLM:** chọn tag suy nghĩ, chọn tag cảm xúc sau khi đọc và trực tiếp chọn phản ứng qua các lời gọi riêng có structured output. Sinh nội dung bài và comment là những nhiệm vụ khác.
- **Ranh giới:** LLM trả kết quả theo contract; hệ thống kiểm tra trước khi áp dụng. LLM không tự sửa dữ liệu, tạo giao dịch hoặc bỏ qua quy tắc.

LLM trả hành động, không trả điểm để một policy khác chọn hành động thay nó. Kiểm tra contract không phải chấm lại hoặc ghi đè một quyết định hợp lệ của LLM.

Ba bước suy nghĩ ban đầu, cảm xúc sau khi đọc và phản ứng là ba lời gọi LLM riêng. Không tự gộp chúng hoặc truyền toàn bộ context của bước đầu vào các bước sau.

## 1. Chuẩn bị persona và mô tả thuộc tính

**Đã xác nhận:** dùng bộ persona MatrAIx được nhắc tới trong phác thảo. Mỗi persona có hơn một nghìn thuộc tính; các trường có tập giá trị enum.

Bản phác thảo đặt ra khả năng viết mô tả theo cấu trúc trường mẹ–trường con: giải thích ý nghĩa chung ở cấp mẹ, ý nghĩa riêng ở cấp con, tránh lặp lại cùng nội dung ở nhiều trường.

Từ đặc điểm persona, hệ thống cần xác định hoặc ước lượng:

- Tần suất hoạt động và xác suất tham gia một phiên.
- Số bài có thể xem, số sản phẩm có thể xem trong shop.
- Các yếu tố liên quan đến khả năng mua.
- Điểm sàn cho những hành động như xem bài hoặc mua; dưới sàn thì không thực hiện.

**Chưa chốt:** công thức, nguồn hiệu chỉnh, và cách xử lý thuộc tính không có thông tin. Bản phác thảo ban đầu dùng số giờ hoạt động/ngày làm bước trung gian; làm rõ mới nhất xác định phiên không cần gắn với thời gian thật. Vì vậy chưa giữ phép quy đổi giờ/ngày thành phiên như một yêu cầu bắt buộc.

## 2. Tag và thông tin persona liên quan

**Đã xác nhận:** chuẩn bị hai bộ tag phục vụ hai đối tượng:

- Tag sản phẩm: mô tả đặc điểm sản phẩm.
- Tag bài viết: mô tả bài quảng cáo, bao gồm phong cách thể hiện để tìm nội dung khiến agent chú ý.

Hiện tại xây nội dung tag phục vụ ngành cafe. Cơ chế liên kết tag–sản phẩm–bài viết–persona vẫn dùng khái niệm chung để bổ sung ngành khác về sau, không mã hóa cố định cafe vào logic mô phỏng.

Với từng persona và từng tag, chọn **top 15 trường persona** liên quan nhất đến khả năng persona bị ảnh hưởng bởi tag đó. Đây là cách hiểu sát bản phác thảo: không tự thay bằng một danh sách 15 trường chung cho mọi persona.

Các trường được chọn giúp cung cấp context phù hợp cho bước ra quyết định, thay vì đưa toàn bộ hồ sơ vào mọi bước.

**Chưa chốt:** danh mục tag, thước đo “liên quan/bị ảnh hưởng”, trường hợp có ít hơn 15 trường hữu ích, và khi nào cần tính lại kết quả chọn trường.

## 3. Chuẩn bị agent công ty và nội dung

**Đã xác nhận:** từ mô tả chiến dịch, hệ thống chuẩn bị một ngân hàng bài viết dự kiến đăng dưới nhiều góc độ và gian hàng có sản phẩm kèm tag. Marketer sắp xếp các bài vào những phiên cố định, sau đó duyệt và chốt lịch trước khi chạy.

Mỗi phiên thực thi đúng danh sách bài đã được phân bổ cho phiên đó: có thể đăng nhiều bài hoặc không đăng bài nào. Không dùng xác suất đăng để thay thế lịch, không tự thêm bài ngoài ngân hàng/lịch và không chỉnh lịch khi mô phỏng đã bắt đầu. Phiên không có bài vẫn là một phiên mô phỏng bình thường; agent vẫn có thể tiếp xúc với các nội dung đã xuất hiện trước đó theo cơ chế của kịch bản.

## 4. Chọn bài viết cho từng agent

**Đã xác nhận:** mỗi agent hoạt động chỉ xem một phần bài viết, không đọc toàn bộ mạng xã hội.

Trình tự được mô tả:

1. Dựa trên đặc điểm agent, xác định các tag có khả năng thu hút sự chú ý.
2. Tìm bài có một phần hoặc toàn bộ tag phù hợp.
3. Đo tương đồng giữa nội dung bài và mô tả agent.
4. Xếp hạng dựa trên tag phù hợp, tương đồng nội dung và các tín hiệu mà agent được phép nhìn thấy trong mạng xã hội mô phỏng.
5. Giới hạn lượng bài theo khả năng hoạt động của agent; cân nhắc lịch sử đã xem và giảm trọng số khi tiếp xúc lặp lại.

“Thu hút chú ý” không đồng nghĩa với “được yêu thích”. Bài gây phản đối vẫn có thể được đọc. Agent có thể thấy lại bài cũ, nhưng không mặc định đọc lại cùng danh sách ở mọi phiên.

**Đã chốt cho bản đầu:** agent chỉ tiếp xúc nội dung bài, không có comment trong flow và không đọc comment lẫn nhau. Comment nếu được bổ sung sau này sẽ phục vụ marketer phân tích.

Để phương án này nhất quán, không đưa comment của người khác, bản tóm tắt comment hoặc sentiment tổng hợp của chúng vào context, cập nhật persona hay thuật toán chú ý. Không chỉ ẩn comment trên giao diện rồi vẫn dùng nội dung đó ngầm tác động agent.

**Đã chốt cho bản đầu:** không dùng số like/dislike hoặc comment của người khác làm tín hiệu quyết định hay chú ý. Marketer vẫn thấy các thống kê được hệ thống hỗ trợ trên dashboard.

Kết quả chỉ mô tả phản ứng với nội dung chiến dịch và lịch sử riêng, không mô phỏng tranh luận, truyền miệng qua comment hay hiệu ứng đám đông. Quy tắc chi tiết bên trong thuật toán chú ý vẫn cần chốt.

## 5. Chuỗi quyết định khi gặp bài viết

**Đã xác nhận:** mỗi bước trong chuỗi dưới đây gọi LLM với prompt chỉ chứa thông tin cần thiết cho bước đó; đầu ra có cấu trúc theo contract.

| Bước | Đầu vào được mô tả | Đầu ra |
| --- | --- | --- |
| 1. Trước khi đọc | Mô tả người dùng/tính cách từ các trường liên quan đã chọn và mô tả bài viết dựa trên tag | Structured output chứa list tag suy nghĩ |
| 2. Đọc bài | Mô tả flow “bạn là người dùng mạng xã hội đang đọc một bài viết”, tag suy nghĩ và nội dung bài | Structured output chứa list tag cảm xúc sau khi đọc |
| 3. Phản ứng | Mô tả flow “bạn là người dùng mạng xã hội vừa đọc một bài viết” và tag cảm xúc sau khi đọc | Structured output thể hiện phản ứng do LLM chọn |
| 4. Ghé shop | Tag và suy nghĩ sau khi đọc | Có hoặc không ghé shop |

Không đưa lại persona vào bước đọc bài; không đưa lại persona, nội dung bài hoặc toàn bộ lịch sử vào bước phản ứng. Danh mục tag/action hợp lệ là phần contract. Ngữ cảnh nghiệp vụ truyền giữa các bước đúng như bảng, không thêm điểm model hoặc xác suất hành động.

Các quy tắc phản ứng đã chốt:

- Không đồng thời like và dislike cùng một bài.
- Ở lần đầu, phản ứng có thể là `like`, `dislike` hoặc `no_reaction`.
- Ở các lần sau, LLM có thể chọn `keep_current`, `remove_reaction` hoặc
  `no_reaction`.
- `keep_current` giữ nguyên phản ứng hiện tại; `remove_reaction` gỡ phản ứng
  hiện tại; `no_reaction` không tạo thay đổi mới.
- Comment chưa thuộc phạm vi bản đầu.

Không tự thêm điều kiện “phải like/comment mới được vào shop”: đầu vào được nêu cho quyết định ghé shop là cảm nhận sau khi đọc.

Không còn câu hỏi “kết hợp xác suất, điểm sàn và tag để policy chọn action” trong chuỗi này: đó là cách hiểu sai trước đây của trợ lý. LLM chọn phản ứng từ context ở bước 3. Các điểm sàn từng được nhắc ở phác thảo chưa được gán vị trí mới; không tự dùng chúng để thay quyết định hợp lệ của LLM.

## 6. Comment và tương tác trong shop

### 6.1. Comment chưa thuộc phạm vi bản đầu

Comment trong bài viết được để dành cho giai đoạn sau. Bản đầu không gọi LLM
để quyết định hoặc sinh comment, không lưu comment như một nhánh của flow
phản ứng và không dùng comment làm context cho agent khác. Khi mở lại tính
năng này, cần định nghĩa riêng contract, thời điểm gọi và cách lưu.

### 6.2. Chuỗi quyết định với sản phẩm trong shop

**Đã xác nhận:** tương tác với sản phẩm có cơ chế suy nghĩ theo bước tương tự khi xem bài viết, nhưng quy trình mua ngắn gọn hơn. Không sao chép toàn bộ chuỗi like/dislike/comment của bài viết sang sản phẩm.

#### A. Đánh giá chú ý với toàn bộ sản phẩm

1. Xác định toàn bộ sản phẩm hợp lệ đang có trong shop.
2. Gọi JEV cho từng sản phẩm để đánh giá agent có chú ý hay bỏ qua.
3. Nếu JEV không có đáp án hợp lệ, gọi LLM fallback theo cùng contract.

Không có tầng lọc khác chọn trước một tập sản phẩm trong flow bản đầu.
Mỗi sản phẩm được đánh giá độc lập; chỉ sản phẩm nhận đủ chú ý mới đi vào
chuỗi quyết định riêng. Chú ý không tự quyết định mua.

#### B. Chuỗi tư duy và quyết định mua

Chuỗi này tương ứng với chuỗi khi agent gặp bài viết:

| Bước | Context trong prompt | Structured output |
| --- | --- | --- |
| 1. Trước khi xem món hàng | Mô tả người dùng/tính cách liên quan đã chọn lọc + mô tả món hàng dựa trên tag | List tag suy nghĩ khi nhìn thấy các tag món hàng |
| 2. Xem món hàng | Flow “bạn là khách hàng đang xem một món hàng trong shop” + tag suy nghĩ + tag/mô tả sản phẩm cần thiết | List tag cảm xúc sau khi xem món hàng |
| 3. Quyết định mua | Flow “bạn là khách hàng vừa xem một món hàng” + tag cảm xúc sau khi xem + thông tin cần thiết của món hàng | `buy` hoặc `not_buy` |

Mỗi bước là một lời gọi LLM riêng. Không đưa toàn bộ persona hoặc toàn bộ lịch sử vào mọi bước. Lời gọi đầu nhận mô tả người dùng đã lọc và tag món hàng; lời gọi thứ hai nhận flow hiện tại, tag suy nghĩ và thông tin sản phẩm cần đọc; lời gọi thứ ba nhận flow vừa xem món hàng và tag cảm xúc để chọn trực tiếp action.

Không có action `defer`, `consider_later` hay “chần chừ” trong structured output của bước mua. Nếu agent chọn `not_buy`, hệ thống vẫn lưu đầy đủ tag suy nghĩ, tag cảm xúc và action `not_buy`.

Các tag suy nghĩ trước khi xem và tag cảm xúc sau khi xem được lưu cùng action. Policy chú ý ở lần sau có thể dùng trực tiếp các tag và action này để tăng/giảm mức chú ý món hàng; không cần gọi thêm LLM để phân tích “tiềm năng mua”.

Quyết định mua chỉ có hai khả năng:

- **Mua:** thực hiện hành động mua trong mô phỏng.
- **Không mua:** không chọn mua ở lần xem này; không tự hiểu là vĩnh viễn không mua.

**Đã xác nhận:** `not_buy` là một hành động được lưu tương tự `buy`, không phải việc thiếu bản ghi giao dịch. Chưa xem sản phẩm hoặc chưa ra quyết định không được tự ghi thành `not_buy`.

Các tag suy nghĩ đã có **trước** quyết định, được lưu trong chuỗi diễn biến dù hành động là mua hay không mua. Không sinh thêm tag, không gọi model phân tích lại và không tạo trạng thái “có/không có tiềm năng mua” sau `not_buy`.

Nếu bộ tag có ý nghĩa như “muốn thử lần sau”, policy có thể quy định sẵn tag đó tác động thế nào đến mức chú ý ở lần sau. Đây là quy tắc trực tiếp theo tag đã lưu, không phải một bước suy luận mới.

### Điểm chú ý sản phẩm ở lần đề xuất sau

**Đã xác nhận:** khi đề xuất lần tiếp theo, policy deterministic đọc lịch sử suy nghĩ và hành động theo từng agent–sản phẩm:

- Có hành động `buy`: giảm mạnh điểm chú ý của sản phẩm đã mua.
- Có hành động `not_buy` và tag suy nghĩ trước quyết định nằm trong tập được policy quy định tăng điểm: áp dụng quy tắc tăng điểm tương ứng.
- Không coi mọi `not_buy` là bị từ chối vĩnh viễn hoặc tự động được tăng điểm. Mức tác động phụ thuộc các tag và điều kiện đã định nghĩa trong policy.

**Đề xuất bổ sung, chưa chốt:** định nghĩa các tag giảm điểm hoặc không tác động, giảm điểm khi xem lặp lại, và phối hợp với ưu tiên sản phẩm mới. Các ý nghĩa tag như “muốn thử lần sau” chỉ là minh họa; ID và danh mục chính thức do chủ dự án thiết kế.

Luồng dùng lại dữ liệu: **lịch sử tag + hành động → tra quy tắc policy → điều chỉnh điểm chú ý → xếp hạng sản phẩm**. Không cần một đầu ra LLM trung gian hay cờ “tiềm năng mua”. Tăng điểm chú ý không tự đổi hành động cũ hoặc bảo đảm lần tới mua.

**Chưa chốt:** ánh xạ tag sang mức tăng/giảm, phạm vi lịch sử được dùng, độ mạnh và thời hạn tác động, cách kết hợp tag trái chiều hoặc nhiều lần xem. Policy cũng cần quy định ưu tiên khi sản phẩm từng có tag tăng điểm nhưng sau đó đã được mua, để giữ đúng yêu cầu giảm mạnh điểm món đã mua. Chưa chọn công thức hay thêm cơ chế mua lặp lại.

Agent ghét thương hiệu vẫn có thể vào shop và xem sản phẩm. Suy nghĩ phê bình của họ cũng là thông tin marketer cần quan sát, không chỉ các giao dịch thành công.

## 7. Thay đổi qua các phiên

**Đã xác nhận về ý định:** dựa vào hoạt động hiện tại và lịch sử trước đó để chọn các trường persona bị tác động, đánh giá hướng tăng/giảm và chuyển giá trị hiện tại sang mức enum phù hợp của chính trường đó. Persona được cập nhật sẽ tham gia vào các quyết định tiếp theo.

“Tăng/giảm” ở đây là thay đổi mức độ mà giá trị enum biểu đạt, không đòi hỏi phải có một trường điểm số liên tục riêng.

Ví dụ đối chiếu trực tiếp với [schema đã tải](../data/matraix/persona_1m/persona_codes.schema.json):

| Trường | Các giá trị theo thứ tự trong schema | Ví dụ diễn giải chuyển mức |
| --- | --- | --- |
| `topic_fitness` | `Passionate`, `Interested`, `Neutral`, `Indifferent`, `Averse` | `Neutral → Interested`: tăng mức quan tâm tới fitness. |
| `att_advertising` | `Enthusiast`, `Positive`, `Neutral`, `Skeptical`, `Opposed` | `Neutral → Skeptical`: thái độ với quảng cáo trở nên tiêu cực hơn. |
| `cog_curiosity` | `Very high`, `High`, `Moderate`, `Low`, `None` | `Moderate → High`: tăng mức tò mò. |
| `risk_tolerance` | `Risk-averse`, `Cautious`, `Balanced`, `Risk-tolerant`, `Risk-seeking` | `Cautious → Balanced`: tăng mức chấp nhận rủi ro. |

Các ví dụ giải thích ý nghĩa của tăng/giảm, không khẳng định một lần đọc quảng cáo nhất định sẽ gây ra các thay đổi này. Chiều tăng phải theo nghĩa của trường: không mặc định tăng là đi tới phần tử tiếp theo trong mảng `values`.

Context cập nhật được phác thảo gồm:

- Bài đã đọc, được mô tả bằng tag thay vì phải đưa lại toàn bộ nội dung.
- Phản ứng với từng bài và quyết định ghé shop.
- Sản phẩm đã xem, tag suy nghĩ trước quyết định và hành động `buy` hoặc `not_buy` đã được lưu; không tạo thêm tag hậu quyết định.
- Lịch sử tiếp xúc và hành động trước phiên hiện tại.

Việc dùng tag ở bước cập nhật không có nghĩa bỏ nội dung đầy đủ ở bước đọc bài.

Luồng xử lý được hiểu là: tổng hợp context → xác định trường bị tác động → xét giá trị hiện tại và các mức được phép → giữ nguyên hoặc chọn mức mới → ghi nhận thay đổi để dùng về sau.

Không cần đổi tất cả các trường sau mỗi phiên. Những trường không biểu đạt mức độ, như ngôn ngữ chính, không thuộc cách tăng/giảm này. Cũng cần giữ đúng nghĩa của trường: `att_brand_loyalty` nói về thái độ đối với sự trung thành thương hiệu nói chung, không tự coi là mức yêu thích riêng thương hiệu đang mô phỏng.

### Solution đề xuất: tích lũy bằng chứng, chuyển enum có giới hạn

Phương án sau để chủ dự án duyệt, chưa phải cơ chế đã chốt:

1. **Whitelist theo nghĩa thuộc tính.** Giữ các thuộc tính nền ngoài tập cập nhật. Cho phép một tập nhỏ các trường quan tâm/thái độ thay đổi; khai báo thứ tự ngữ nghĩa và độ bền của từng trường. Không suy ra tính dễ thay đổi chỉ vì enum có mức cao/thấp.
2. **Chọn ứng viên.** Từ tag bài/sản phẩm và ánh xạ trường liên quan, chỉ đưa các trường nằm trong whitelist vào đánh giá. Không gọi model quét toàn bộ persona mỗi phiên.
3. **Model chọn tác động.** Nhận giá trị hiện tại, tag cảm xúc, sự kiện và lịch sử rút gọn của chính agent; trả cho từng trường ứng viên hướng `increase / decrease / unchanged`, mức bằng chứng rời rạc và ID sự kiện làm căn cứ. Không trả lời bằng văn bản tự do.
4. **Hệ thống tích lũy.** Quy đổi mức bằng chứng bằng trọng số cấu hình, giảm tác động của nội dung lặp lại và giới hạn tổng tác động một phiên. Mỗi sự kiện chỉ được tính một lần. Các tín hiệu trái chiều có thể bù trừ; không lấy hành động do chính cảm xúc sinh ra làm một bằng chứng độc lập để nhân đôi tác động.
5. **Chuyển mức cuối phiên.** Chỉ khi bằng chứng tích lũy vượt ngưỡng mới chuyển enum tối đa một mức theo chiều ngữ nghĩa; thiếu bằng chứng thì giữ nguyên. Trừ phần bằng chứng đã dùng sau chuyển mức, có ngưỡng đảo chiều để tránh dao động qua lại. Phiên kế tiếp dùng giá trị mới.
6. **Ghi nhận.** Giữ bản persona ban đầu, trạng thái hiện tại, phần bằng chứng chưa đủ ngưỡng và log chuyển giá trị gắn với các sự kiện. Hệ thống quyết định và kiểm tra enum cuối, không để model ghi thẳng vào dữ liệu.

Ví dụ theo schema: `topic_coffee` có `Passionate / Interested / Neutral / Indifferent / Averse`. Một lần thấy quảng cáo tạo cảm xúc tích cực chưa đủ để đổi `Neutral → Interested`; nhiều trải nghiệm liên quan, đủ bằng chứng theo ngưỡng đã cấu hình mới có thể chuyển. Lặp lại cùng bài không được coi ngang với nhiều bằng chứng độc lập.

Điểm tích lũy là cơ chế nội bộ đề xuất để tạo độ bền, không thay enum persona bằng điểm và không phải xác suất hành vi ngoài đời. Ngưỡng, trọng số, suy giảm theo phiên và whitelist cần được hiệu chỉnh, chưa đặt số cố định.

Cảm xúc tức thời với món hàng, thái độ riêng với thương hiệu và thuộc tính persona tổng quát không đồng nhất. Không tự đổi `big5_trust` hay `att_brand_loyalty` chỉ vì thất vọng với một món cafe. Lịch sử tag suy nghĩ và hành động tiếp tục gắn với sản phẩm, không làm tăng hàng loạt thuộc tính chung.

Ý định hiện tại vẫn là cập nhật các thuộc tính persona có liên quan bằng giá trị trong schema, đồng thời lưu lịch sử suy nghĩ và hành động với từng sản phẩm. Solution cập nhật persona này là đề xuất riêng, không thêm bước phân tích sau `not_buy` cho thuật toán chú ý.
