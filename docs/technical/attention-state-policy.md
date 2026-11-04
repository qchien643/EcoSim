# Policy trạng thái chú ý

**Trạng thái:** v1 chốt để triển khai thử, chưa calibration  
**Nguồn policy chung:** [FRD-05](../frd/05-session-policy-and-state.md)
**Phạm vi:** A1 chú ý bài viết, B1 chú ý sản phẩm và bước lấy lý do sau khi
agent không chú ý.

## 1. Mục tiêu

Tách bốn khái niệm thường bị trộn lẫn:

1. Model chấm mức chú ý.
2. Policy chuyển điểm thành quyết định chú ý.
3. Agent thực sự đã làm gì.
4. Model có trả được kết quả hợp lệ hay không.

Số lần gặp chỉ là dữ liệu lịch sử. Nó không tự đại diện cho cảm xúc và không
được dùng như bằng chứng rằng agent sẽ chú ý nhiều hơn.

## 2. Chuyển attention score thành action

JEV hoặc LLM fallback chấm một attention score theo thang đã cấu hình. Adapter
chuẩn hóa score về `[0,1]` trước khi áp dụng policy.

Policy v1 dùng một ngưỡng deterministic:

```text
normalized_score >= 0.60 → attend
normalized_score <  0.60 → skip
```

Ngưỡng `0.60` là cấu hình phiên bản đầu để kiểm thử, không phải xác suất và
không phải kết luận tâm lý. Khi đã từng chú ý đối tượng, action tương ứng
được ghi là `attend_again`; khi dưới ngưỡng vẫn ghi `skip`.

Quy tắc bổ sung:

- Không lấy score cao nhất/thấp nhất của các đối tượng khác để thay đổi
  ngưỡng.
- Không cộng score với số lần gặp.
- Không dùng score cũ để tự nâng hoặc hạ score mới.
- Score cũ có thể được lưu để audit, phân tích và hiệu chỉnh policy sau này.
- Nếu score đúng `0.60`, chọn `attend` do dùng điều kiện `>=`.
- Nếu score không hợp lệ, không áp dụng threshold; chuyển sang fallback.

Về sau có thể cấu hình ngưỡng riêng cho A1 và B1, nhưng không thêm ngưỡng
riêng theo từng agent trong phiên bản đầu.

## 3. Trạng thái chính thức khi model rỗng

`unresolved` là trạng thái khi không có output usable và có ít nhất một lượt
lỗi/sai. Nếu cả hai lượt chấm tag đều hợp lệ nhưng dưới sàn, dùng
`empty_result`; không đổi thành `no_reaction`.

| Tình huống | Trạng thái lưu | Có phải action không? | Xử lý |
| --- | --- | --- | --- |
| Score hợp lệ dưới ngưỡng | `skip` | Có | Lưu event bỏ qua |
| Choice hợp lệ `no_reaction` | `no_reaction` | Có | Lưu hành vi không phản ứng |
| Cả hai model đều rỗng/sai | `unresolved` | Không | Dừng nhánh phụ thuộc |
| Hai lượt chấm tag hợp lệ nhưng dưới sàn | `empty_result` | Không | Lưu tags rỗng, dừng nhánh |
| Bước không được chạy vì bước trước dừng | `not_applicable` | Không | Không gọi model |

Không đổi `unresolved` thành `skip`, `no_reaction`, `not_buy` hoặc emotion
trung lập. Như vậy dữ liệu phân biệt được:

- agent đã được đánh giá và thật sự bỏ qua;
- agent đã được đánh giá và không phản ứng;
- hệ thống không xác định được kết quả.

Ở A1/B1, `unresolved` không tạo event chú ý hoặc bỏ qua. Ở A2/B2, nó dừng
nhánh trước bước kế tiếp. Ở A4/A5/B3, nó không tạo action thay thế. Retry
lỗi kết nối là policy kỹ thuật riêng, không biến lỗi thành `unresolved` trước
khi retry đã kết thúc.

## 4. Trạng thái cần lưu ở A1/B1

Phải lưu **cả score và action**, nhưng hai trường có vai trò khác nhau:

```json
{
  "stage": "A1",
  "status": "resolved",
  "attention": {
    "raw_score": 1.8,
    "normalized_score": 0.60,
    "scale_id": "attention_v1"
  },
  "decision": {
    "action": "attend_again",
    "policy_id": "attention_policy_v1"
  },
  "reason_state_ref": null
}
```

- `attention` phục vụ audit, phân tích và hiệu chỉnh threshold.
- `decision.action` là kết quả workflow đã thực thi.
- `status` cho biết output có hợp lệ hay không.
- `reason_state_ref` trỏ đến kết quả A1R/B1R nếu action là `skip`.

`previous_same_stage_state` ở lần sau chứa bản ghi A1/B1 gần nhất, nhưng
không được coi score cũ là cảm xúc. Context lịch sử lần sau nên ưu tiên:

1. reason tags mới nhất từ A1R/B1R;
2. emotion/thought state gần nhất của đúng object nếu flow cho phép;
3. action và score cũ như metadata mô tả trạng thái trước đó.

Điều này phù hợp với kết quả kiểm thử: chỉ thông báo “đã gặp nhiều lần”
không đủ làm điểm thay đổi rõ ràng; trạng thái cảm xúc hoặc lý do mới có
ảnh hưởng diễn giải được.

## 5. Bước lấy lý do sau khi không chú ý

Khi A1/B1 trả `skip`, gọi thêm một bước:

- `A1R`: lý do không chú ý bài viết;
- `B1R`: lý do không chú ý sản phẩm.

Đây không phải bước quyết định lại và không được đổi `skip` thành action khác.
Nó tạo `attention_reason` state để dùng ở lần gặp sau.

### Context

Giữ context A1/B1 vừa dùng, cộng thêm:

- action hiện tại là `skip`;
- previous same-stage state;
- emotion/thought gần nhất được phép dùng;
- lịch sử liên quan đã nén theo đúng agent–object.

Không đưa nội dung đầy đủ bài viết vào A1R. B1R chỉ dùng thông tin sản phẩm
đang được phép thấy ở B1.

### Output

Model chấm các reason tags được phép, chuẩn hóa về `[0,1]`, rồi áp dụng
`top_k = 3` và `score_floor = 0.50` trong policy v1. Đây là cấu hình ban
đầu đã chấp thuận để triển khai thử, chưa calibration và không phải xác suất.

Các reason tags có thể đồng thời xuất hiện, ví dụ `low_personal_fit` cùng
`competing_attention`. Không tự suy ra lý do chỉ từ action `skip`.

Nếu A1R/B1R cũng `unresolved`, vẫn giữ action `skip` của A1/B1; chỉ reason
state là rỗng và không bịa `indifference` hoặc `boredom`.

## 6. Mô hình dữ liệu tối thiểu

```json
{
  "run_id": "run_01",
  "agent_id": "agent_01",
  "object_type": "article",
  "object_id": "post_01",
  "stage": "A1",
  "encounter_no": 3,
  "status": "resolved",
  "attention": {
    "raw_score": 1.8,
    "normalized_score": 0.60,
    "scale_id": "attention_v1"
  },
  "decision": {
    "action": "skip",
    "policy_id": "attention_policy_v1"
  },
  "reason_state_ref": "state_A1R_003",
  "source": "jev",
  "contract_variant": "repeat_encounter"
}
```

Reason state được lưu riêng:

```json
{
  "state_id": "state_A1R_003",
  "stage": "A1R",
  "status": "resolved",
  "tags": [
    {
      "tag_id": "attention_reason.repetition_fatigue",
      "score": 0.81
    }
  ],
  "source": "jev"
}
```

## 7. Chuỗi xử lý chuẩn

```text
A1/B1 chấm score
  ↓
Validate + normalize [0,1]
  ├─ invalid/empty → fallback
  └─ valid
       ↓
  threshold 0.60
       ├─ attend → bước tiếp theo
       └─ skip → lưu action → gọi A1R/B1R
                              ↓
                       lưu reason hoặc unresolved
```

## 8. Việc còn lại

- Calibration để kiểm tra ngưỡng `0.60` trên dữ liệu mô phỏng.
- V1 đã chốt history chỉ đi qua context, không tự cộng/trừ score. Cần tích
  hợp renderer ký ức mua/cân nhắc liên bước.
- Cần calibration bằng fixture campaign đã xác nhận.
- JSON Schema request/raw response của từng adapter; output schema nội bộ đã
  có tại `data/contracts/agent_model_output.schema.json`.
