# FRD-05 — Policy và trạng thái một phiên

**Chốt phiên bản đầu ngày 27/09/2026.** Các giá trị được chấp thuận để triển
khai thử, chưa được hiệu chỉnh bằng hành vi khách hàng thật.
Tài liệu này thay thế các đoạn “chưa chốt” hoặc cách dùng `no_reaction`
cho lỗi model trong các bản nháp trước.

Nguồn cấu hình: `data/contracts/simulation-policy.v1.json`.
Mã kiểm chứng offline: `python3 paper_research/simulation_policy_v1.py`.
Đã có runtime, transaction SQLite và adapter JEV/LLM fallback trong
`simulation/`. Kiểm thử offline không chứng minh độ chính xác hành vi model.

## 1. Chấm điểm và chọn tag

JEV và LLM trả phân phối trên cùng bốn mức 0–3 cho từng tag. Adapter kiểm
tra đủ tag, không trùng, giá trị hữu hạn, xác suất trong [0,1] và tổng bằng
1 trong sai số cấu hình. Điểm = Σ(mức × xác suất)/3; không làm tròn trước
khi so với sàn. Raw score JEV chỉ để đối chiếu/audit. Không ép tổng điểm
giữa các tag bằng 1.

| Stage | Điểm sàn | Giới hạn |
| --- | ---: | ---: |
| A2, A3 — emotion | 0.30 | 3 tag |
| B2 — thought | 0.30 | 3 tag |
| A1R, B1R — lý do bỏ qua | 0.50 | 3 tag |
| A1, B1 — chú ý | 0.60 | Một action |

Giữ điểm >= sàn, xếp giảm dần, hòa điểm theo tag ID tăng dần, lấy tối đa K.
Ghép mô tả tiếng Anh từ registry, không để model tạo định nghĩa mới.
Lưu cả điểm bị loại để audit. Không tự loại cặp `review_pairs`.
A1/B1 dưới sàn là `skip`; đạt sàn là `attend` hoặc `attend_again` nếu
đã từng chú ý, không chỉ vì đã từng gặp.

## 2. Fallback và trạng thái

Một attempt hợp lệ có tag đạt sàn hoặc attention/action hợp lệ là `usable`.
Phân phối đủ tag nhưng tất cả dưới sàn là `below_floor`. Output thiếu/sai,
rỗng về cấu trúc hoặc lỗi kết nối là `invalid`, không phải cảm xúc yếu.

| JEV | LLM dự phòng | Trạng thái cuối |
| --- | --- | --- |
| usable | Không gọi | resolved, source=jev |
| invalid/below_floor | usable | resolved, source=llm_fallback |
| below_floor | below_floor | empty_result |
| invalid/below_floor | invalid (hoặc invalid + below_floor) | unresolved |

Chỉ gọi fallback một lần với cùng snapshot, tag, thang điểm và policy.
Không cộng/trung bình hai kết quả; không ép model tạo tag vượt sàn.
Một JEV lỗi không làm hỏng kết quả fallback hợp lệ.
`resolved_jev`/`resolved_llm` chỉ là cách gọi tắt; lưu `status` và `source`
thành hai trường, không tạo hai enum trạng thái mới.

`empty_result` chỉ áp dụng stage sinh tag, danh sách chọn rỗng. `unresolved`
không có action thay thế. Cả hai dừng nhánh phụ thuộc; không hồi sinh state
cũ. `no_reaction` chỉ là lựa chọn A4 đầu tiên; `no_new_reaction` là lựa chọn
khi đã có phản ứng. Một action không phản ứng hợp lệ vẫn cho phép xét A5.
`not_applicable` là stage không chạy vì nhánh trước dừng, không gọi model.
A1R/B1R không thành công không xóa action `skip` đã lưu.

## 3. Model call, event và state

Mỗi attempt lưu: call ID, khóa bước, model/source, request snapshot và hash,
raw output, lỗi validate, thời gian ở client, versions và lý do fallback.
Không lưu khóa API. Thời gian client không được gọi là latency model.

Event nghiệp vụ lưu run/session/agent, organization/brand, object type/ID,
encounter, stage, thứ tự event, event cha, action hoặc selected tags và
policy version. State là kết quả mới nhất của đúng run–agent–object–stage.
Kết quả bước trước trong lượt hiện tại tách riêng khỏi ký ức cùng bước.

Khóa idempotency:

```text
run + session + agent + object_type + object_id + encounter_no + stage
```

Phải có encounter để hai lần ghé cùng shop trong một phiên không bị gộp
nhầm. Retry dùng cùng khóa, attempt ID riêng. Hash input khác trên cùng
khóa là xung đột, không ghi đè. Database tương lai cần unique constraint
trên khóa và transaction ghi event, state, counter cùng checkpoint.
Không tuyên bố exactly-once API call: crash sau API nhưng trước lưu raw
có thể cần gọi lại; chỉ bảo đảm không nhân đôi event đã commit.
`resolved` sinh event hành vi; các trạng thái kết thúc khác lưu processing
record và checkpoint, không tăng counter mua/đọc thay cho action thật.

## 4. Điều phối phiên

1. Đọc scenario và lịch đăng đã khóa; không sửa lịch trong run.
2. Nhận danh sách agent hoạt động của phiên từ scenario; sắp xếp ID ổn định.
3. Với mỗi agent, xét toàn bộ bài đã đăng còn hiển thị, theo phiên đăng,
   vị trí trong lịch và ID. Không chỉ lấy bài mới và không lọc recommendation.
4. Với mỗi bài: A1; skip thì A1R và kết thúc nhánh bài. Attend thì
   A2 → A3 → A4 → A5, lưu sau mỗi stage.
5. Nếu ghé shop, xử lý toàn bộ sản phẩm hợp lệ theo ID:
   B1; skip thì B1R; attend thì B2 → B3. Lưu cả mua và không mua.
6. Quay về bài kế tiếp. Lỗi model chỉ dừng nhánh phụ thuộc; lỗi ghi dữ liệu
   phải dừng run để không tiếp tục với lịch sử chưa commit.
7. Hết danh sách thì đóng phiên, tổng hợp metric từ event đã commit;
   báo riêng số unresolved/empty_result, không coi là từ chối mua.

Mặc định thực thi tuần tự; có thêm mode agent song song theo batch với một
SQLite writer. Chờ toàn bộ batch trước batch sau; chờ toàn bộ session trước
công bố metrics hoặc mở session tiếp theo. Stage trong một agent vẫn tuần tự.
Thiết kế: [hai chế độ chạy](../technical/parallel-execution-v1.md).
Mỗi bài có một encounter/agent/phiên.
Mỗi visit là một encounter mới cho sản phẩm, kể cả cùng shop từ bài khác.
Mỗi encounter chốt snapshot lịch sử ở đầu; thay đổi từ encounter hoàn tất
trước đó trong cùng phiên được nhìn thấy. Không giả định giới hạn tiền,
tồn kho, thời lượng đọc hoặc số món mua khi chưa có yêu cầu.
Không cập nhật persona cố định sau từng event trong v1.

## 5. Lịch sử mua và không mua

V1 dùng context, không có bonus/penalty cộng trực tiếp vào score.
Lưu B3 action cùng tham chiếu suy nghĩ B2 tạo trước quyết định. Chỉ mô tả:
đã mua, từng cân nhắc lại, thấy giá là rào cản hoặc thấy không phù hợp.
Không suy ra đã dùng sản phẩm, hài lòng hay “trải nghiệm xấu” từ action.
Không biến `not_buy` thành ý định mua lần sau nếu thiếu thought phù hợp.

B1/B2 có thể nhận ký ức cân nhắc/mua đã kiểm tra đúng sản phẩm, với nhãn
riêng; không tráo thành `previous_same_stage_state` của B1. Mở rộng context
loader/renderer cho ký ức liên bước này là việc tích hợp còn lại, không
được nhét thêm field chưa hỗ trợ vào prompt hiện tại.

## 6. Kiểm thử và phần còn lại

Checks offline phải bao phủ điểm đúng sàn, dưới sàn, hòa điểm, tag sai family,
NaN, thiếu tag, mọi tổ hợp fallback và khôi phục không nhân đôi event.
Fixture dùng registry/schema thật; dữ liệu tổng hợp phải ghi rõ nguồn.
Không dùng câu placeholder làm bài quảng cáo để chọn threshold A3.
Cần marketer cung cấp/xác nhận bài và catalog trước calibration; chưa tự
tạo doanh nghiệp thật hoặc khẳng định lịch sử tổng hợp là hành vi quan sát.

Đã có session engine, storage, fallback, context theo stage và metrics.
Còn thiếu renderer ký ức liên bước mua/cân nhắc, pipeline persona MatrAIx,
relationship policy và fixture campaign đã xác nhận để calibration.
