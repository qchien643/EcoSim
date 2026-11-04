# 05 — Từ điển diễn giải thử nghiệm: cafe và hành vi mua sắm

> Schema con dùng cho sản phẩm đã được tạo tại
> [projectdut_persona.schema.json](../data/matraix/persona_1m/projectdut_persona.schema.json).
> Tài liệu này là bản diễn giải thử nghiệm rộng hơn; danh sách dùng mặc định
> hiện tại xem [Schema persona dùng cho sản phẩm](06-schema-persona-san-pham.md).

## Trạng thái và phạm vi

**Bản nháp diễn giải của dự án, cần duyệt trước khi sử dụng.** Gồm 22 trường lấy từ
`data/matraix/persona_1m/persona_codes.schema.json`. ID, category và enum giữ nguyên
nguồn; các diễn giải tiếng Việt, giới hạn sử dụng và thứ tự ngữ nghĩa là đề xuất,
không phải định nghĩa chính thức của MatrAIx.

Đây là lớp mô tả dùng chung, không bổ sung giá trị thiếu cho persona, không sửa
schema gốc, không triển khai mô phỏng và chưa cho phép tự động cập nhật thuộc tính.
Độ phủ dữ liệu được kiểm tra riêng trong [báo cáo](04-do-phu-persona.md).

## Contract tối thiểu cho bản diễn giải

Mỗi trường cần có: ID gốc, category gốc, nghĩa của trường, nghĩa từng enum,
điều không được suy ra và tình trạng duyệt. Trong bản nháp này, mọi trường đều
`draft`; enum dùng chung được diễn giải một lần ở phần thang giá trị.

Khi dùng trong prompt, lấy mô tả nhóm + mô tả trường + diễn giải giá trị hiện có.
Không đưa toàn bộ từ điển vào từng lời gọi. Những trường thiếu không được mô tả
như đã có giá trị; không mặc định thiếu là `Neutral`, `None` hoặc không quan tâm.
`None` dạng chuỗi là một enum có nghĩa, khác dữ liệu null.

## Nhóm mô tả dùng chung

Các category sau là nhãn có sẵn, **không phải bằng chứng về quan hệ nhân quả
hay trường mẹ–con trong graph gốc**. Diễn giải nhóm chỉ giúp tránh lặp mô tả:

| Category gốc | Diễn giải đề xuất | Giới hạn |
| --- | --- | --- |
| `Interests: Topics` | Mức quan tâm hoặc ác cảm đối với chủ đề. | Không đo mức thành thạo, tần suất sử dụng hay khả năng mua. |
| `Interests: Culture` | Các thói quen và lựa chọn đời sống được từng trường mô tả. | Không có một thang tăng/giảm chung cho cả nhóm. |
| `Expertise: Skills` | Mức thành thạo kỹ năng cụ thể. | Biết làm không đồng nghĩa thích làm hoặc thường xuyên làm. |
| `Interests: Food` | Sở thích với loại ẩm thực. | Không suy ra quốc tịch, nơi ở hay chế độ ăn bắt buộc. |
| `Professional: Industry` | Mức trải nghiệm nghề nghiệp/tiếp xúc với ngành. | Không phải nhu cầu mua hàng trong ngành đó. |
| `Worldview: Beliefs` | Thái độ chung đối với một quan niệm hoặc chủ đề xã hội. | Không thay thế thái độ với thương hiệu cụ thể. |
| `Health: Lifestyle` | Kiểu lựa chọn lối sống được ghi nhận. | Không suy ra bệnh, dị ứng hoặc nhu cầu điều trị. |
| `Behavior: Work` | Đặc điểm lịch làm việc. | Không tự suy ra lịch hoạt động của agent theo phiên. |

Không tạo “điểm trường mẹ” bằng cách cộng các trường trong category.

## Các bộ enum dùng chung

| Bộ | Enum và diễn giải đề xuất |
| --- | --- |
| Quan tâm | `Passionate`: rất đam mê; `Interested`: quan tâm; `Neutral`: không nghiêng tích cực/tiêu cực; `Indifferent`: ít để tâm; `Averse`: có ác cảm/né tránh chủ đề. |
| Kỹ năng | `Master`: rất thành thạo; `Advanced`: trình độ cao; `Intermediate`: trung cấp; `Beginner`: mới bắt đầu; `None`: không có kỹ năng được mô tả. |
| Tần suất | `Daily`: hằng ngày; `Weekly`: hằng tuần; `Monthly`: hằng tháng; `Rarely`: hiếm khi; `Never`: không thực hiện. Đây là nhãn đời sống nguồn, không quy đổi thành số phiên. |
| Sở thích ẩm thực | `Love`: rất thích; `Like`: thích; `Neutral`: trung lập; `Avoid`: tránh lựa chọn. Không tự suy ra lý do tránh. |
| Trải nghiệm ngành | `Veteran`: dày dạn; `Experienced`: có kinh nghiệm; `Some exposure`: từng tiếp xúc; `None`: không có trải nghiệm được mô tả. Chưa gán số năm. |
| Thái độ | `Enthusiast`: rất ủng hộ; `Positive`: tích cực; `Neutral`: trung lập; `Skeptical`: hoài nghi; `Opposed`: phản đối. Đối tượng thái độ là khái niệm của từng trường. |

Các thang quan tâm, kỹ năng, tần suất, sở thích ẩm thực, trải nghiệm ngành và
thái độ có thể được đề xuất thứ tự ngữ nghĩa; **không suy ra khoảng cách bằng
nhau giữa hai enum**. Riêng `Neutral` và `Indifferent` cần duyệt kỹ ý nghĩa
trước khi dùng làm hai bậc chuyển tiếp.

## A. Cafe và bối cảnh ăn uống

### 1. `topic_coffee`

- Nhóm: `Interests: Topics`; enum: bộ Quan tâm.
- Nghĩa: mức quan tâm đến cafe nói chung.
- Không suy ra: số ly uống, thích vị đắng, thích một thương hiệu hoặc sẽ mua.
- `Neutral` → `Interested` có thể diễn giải là tăng quan tâm; một lượt like bài
  cafe chưa tự động đủ để cập nhật trường.

### 2. `lstyle_coffee_ritual`

- Nhóm: `Interests: Culture`; nghĩa: bối cảnh/thói quen cafe điển hình.
- Enum: `Home brew` = pha tại nhà; `Café regular` = thường đến quán;
  `Office coffee` = cafe ở nơi làm việc; `Tea instead` = chọn trà thay cafe;
  `None` = không có thói quen cafe được mô tả.
- Đây là các loại, không có thứ tự tăng/giảm. Không suy ra trung thành với quán
  đang mô phỏng; `Tea instead` không có nghĩa ghét cafe.

### 3. `lstyle_caffeine`

- Nhóm: `Interests: Culture`; nghĩa: mức sử dụng caffeine nói chung.
- Enum: `None` = không dùng; `Low` = thấp; `Moderate` = vừa; `High` = cao.
- Thứ tự mức dùng đề xuất: `None` < `Low` < `Moderate` < `High`.
- Không quy đổi sang mg/ngày hay số ly; caffeine không chỉ đến từ cafe.
  Không dùng trường này để suy ra tình trạng sức khỏe.

### 4–6. Các chủ đề gần cafe

| ID | Category | Nghĩa | Không suy ra |
| --- | --- | --- | --- |
| `topic_tea` | `Interests: Topics` | Quan tâm đến trà; bộ Quan tâm. | Trà luôn thay thế cafe hoặc hai sở thích loại trừ nhau. |
| `topic_cooking` | `Interests: Topics` | Quan tâm đến nấu ăn; bộ Quan tâm. | Có kỹ năng bếp hay muốn mua thiết bị. |
| `topic_baking` | `Interests: Topics` | Quan tâm đến làm bánh; bộ Quan tâm. | Thích mọi món bánh bán trong shop. |

### 7–8. Kỹ năng liên quan

| ID | Category | Nghĩa | Không suy ra |
| --- | --- | --- | --- |
| `skill_cooking` | `Expertise: Skills` | Thành thạo nấu ăn; bộ Kỹ năng. | Biết pha cafe chuyên nghiệp. |
| `skill_baking` | `Expertise: Skills` | Thành thạo làm bánh; bộ Kỹ năng. | Có nghề làm bánh hoặc muốn mua bánh. |

### 9. `lstyle_cooking_freq`

- Nhóm: `Interests: Culture`; enum: bộ Tần suất.
- Nghĩa: tần suất nấu ăn được nguồn ghi nhận.
- Không suy ra: lịch ghé shop, thời gian rảnh hoặc tự nấu thay vì mua cafe.

### 10. `cuis_vietnamese`

- Nhóm: `Interests: Food`; enum: bộ Sở thích ẩm thực.
- Nghĩa: sở thích với ẩm thực Việt Nam.
- Không suy ra: là người Việt, đang ở Việt Nam hoặc thích cafe Việt.

### 11–12. Trải nghiệm nghề nghiệp

| ID | Category | Nghĩa | Không suy ra |
| --- | --- | --- | --- |
| `ind_food_beverage` | `Professional: Industry` | Trải nghiệm trong ngành thực phẩm/đồ uống; bộ Trải nghiệm ngành. | Sở thích ăn uống hay sức mua. |
| `ind_restaurants` | `Professional: Industry` | Trải nghiệm trong ngành nhà hàng; bộ Trải nghiệm ngành. | Tần suất ăn ngoài hoặc đến quán cafe. |

Hai trường này chỉ là context phụ khi nội dung cần đến kinh nghiệm nghề nghiệp.
Độ phủ cao không khiến chúng trở thành bằng chứng trực tiếp về nhu cầu cafe.

## B. Mua sắm và phản ứng với quảng cáo

### 13. `lstyle_shopping_style`

- Nhóm: `Interests: Culture`; nghĩa: khuynh hướng mua sắm.
- Enum: `Researcher` = tìm hiểu trước khi mua; `Impulse buyer` = thiên về mua
  bộc phát; `Bargain hunter` = tìm món hời; `Brand loyal` = thiên về thương hiệu
  quen; `Minimalist` = thiên về mua ít/đủ dùng.
- Không có thứ tự tăng/giảm. Không tự biến loại mua sắm thành hành động bắt buộc
  hoặc xác suất mua; `Brand loyal` chưa chỉ rõ trung thành với thương hiệu nào.

### 14. `lstyle_frugality`

- Nhóm: `Interests: Culture`; nghĩa: khuynh hướng chi tiêu so với tiết kiệm.
- Enum: `Frugal saver` = tiết kiệm, dè sẻn; `Balanced` = cân bằng;
  `Spender` = thiên về chi tiêu; `Splurger` = có xu hướng chi mạnh.
- Thứ tự đề xuất theo **chi tiêu**, không phải “tốt hơn”:
  `Frugal saver` < `Balanced` < `Spender` < `Splurger`.
- Không suy ra thu nhập, ngân sách cụ thể hoặc độ nhạy giá bằng một con số.

### 15–17. Thái độ chung

| ID | Category | Nghĩa, dùng bộ Thái độ | Không suy ra |
| --- | --- | --- | --- |
| `att_brand_loyalty` | `Worldview: Beliefs` | Thái độ với việc trung thành thương hiệu nói chung. | Mức yêu thích/trung thành với thương hiệu chiến dịch. |
| `att_advertising` | `Worldview: Beliefs` | Thái độ với quảng cáo nói chung. | Tin hoặc ghét mọi bài quảng cáo cụ thể. |
| `att_consumerism` | `Worldview: Beliefs` | Thái độ với chủ nghĩa tiêu dùng. | Tần suất mua hoặc khả năng chi trả. |

Các trường này cần duyệt cách diễn giải, nhất là khác biệt giữa thái độ về
một quan niệm và hành vi thực tế. Không đổi quan điểm chung chỉ vì một lần mua.

## C. Context phụ — chỉ dùng khi thật sự liên quan

### 18. `lstyle_diet_type`

- Nhóm: `Health: Lifestyle`; nghĩa: kiểu chế độ ăn.
- Enum: `Omnivore` = ăn tạp; `Flexitarian` = thiên thực vật nhưng linh hoạt;
  `Vegetarian` = ăn chay, chưa chỉ rõ trứng/sữa; `Vegan` = thuần chay;
  `Pescatarian` = có ăn cá/hải sản nhưng tránh thịt động vật trên cạn;
  `Keto/low-carb` = keto hoặc ít carbohydrate, chưa phân biệt hai kiểu.
- Không có thứ tự tăng/giảm. Không suy ra dị ứng, bệnh lý hoặc mức tuân thủ.
  Chỉ đưa vào context nếu thành phần món hàng khiến nó liên quan.

### 19. `lstyle_morning_routine`

- Nhóm: `Interests: Culture`; nghĩa: cách tổ chức sinh hoạt buổi sáng.
- Enum: `Highly structured` = rất có nề nếp; `Loosely structured` = có nề nếp
  linh hoạt; `Rushed` = vội; `Slow` = chậm rãi; `None` = không có nề nếp cụ thể.
- Các loại trộn nhiều khía cạnh, không ép thành một thang. Không suy ra có uống
  cafe sáng hoặc phiên nào tương ứng buổi sáng.

### 20. `lstyle_work_schedule`

- Nhóm: `Behavior: Work`; nghĩa: dạng lịch làm việc.
- Enum: `9-to-5` = giờ hành chính; `Flexible hours` = giờ linh hoạt;
  `Shift work` = làm theo ca; `On-call` = làm khi được gọi;
  `Freelance` = làm tự do; `Unemployed` = không có việc làm.
- Không có thứ tự tăng/giảm. Không suy ra thu nhập hay số phiên hoạt động;
  các nhãn có thể chồng lấn ngoài đời nhưng schema chỉ ghi một giá trị.

### 21. `lstyle_primary_social`

- Nhóm: `Interests: Culture`; nghĩa: nền tảng xã hội chính.
- Enum: `Instagram`, `TikTok`, `X / Twitter`, `Facebook`, `LinkedIn`,
  `YouTube`, `Reddit` là tên nền tảng tương ứng; `None` = không có nền tảng
  chính được mô tả.
- Không có thứ tự tăng/giảm. Không suy ra mức hoạt động hoặc tự động loại agent
  khỏi mạng xã hội mô phỏng.

### 22. `lstyle_screen_time`

- Nhóm: `Interests: Culture`; nghĩa: khoảng thời gian dùng màn hình mỗi ngày.
- Enum: `<2 hrs` = dưới 2 giờ; `2-4 hrs` = 2–4 giờ;
  `4-8 hrs` = 4–8 giờ; `8+ hrs` = từ 8 giờ.
- Nguồn chưa làm rõ tính bao gồm tại các mốc 4/8 giờ; giữ nguyên nhãn,
  không tự chọn giá trị trung bình hoặc quy đổi thành phiên.
- Có thứ tự về thời lượng, nhưng không đồng nghĩa thời gian dùng mạng xã hội.

## Trước khi dùng để thay đổi thuộc tính

1. Duyệt nghĩa nhóm, trường và từng enum; giữ trạng thái chưa rõ nếu thiếu căn cứ.
2. Tách trạng thái thương hiệu/sản phẩm của kịch bản khỏi thuộc tính persona chung.
3. Chỉ sau đó chọn trường có thể cập nhật và định nghĩa chuyển giá trị.

Chưa chọn whitelist, ngưỡng bằng chứng hay mức suy giảm. Bản nháp này không
gán các tham số đó và không thay đổi chuỗi quyết định LLM đã thống nhất.
